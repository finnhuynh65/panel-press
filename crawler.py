#!/usr/bin/env python3
"""Polite, resumable manga series crawler.

Use only for material you are authorized to download. The default worker count
and delay are intentionally conservative; check the site's terms and robots
policy before running a large crawl.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_SERIES = "https://weebcentral.com/series/01J76XYBR7JHFW7Q80MHJP5VYW/Fire-Punch"
USER_AGENT = "PanelPress/1.0 (+respectful, rate-limited downloader)"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.images: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and attrs_dict.get("href"):
            self._href = attrs_dict["href"]
            self._text = []
        elif tag == "img" and attrs_dict.get("src"):
            self.images.append((attrs_dict["src"], attrs_dict.get("alt", "")))

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


@dataclass(frozen=True)
class Chapter:
    number: str
    title: str
    url: str
    chapter_id: str


def fetch(url: str, *, retries: int = 3, delay: float = 0.0) -> bytes:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise RuntimeError(f"Unsupported URL scheme for {url!r}: only http and https are allowed")
    if delay:
        time.sleep(delay)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,image/*,*/*;q=0.8"})
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            with urlopen(request, timeout=45) as response:
                return response.read()
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= max(1, retries):
                break
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = max(5.0, float(retry_after)) if retry_after else 10.0 * (attempt + 1)
                except ValueError:
                    wait = 10.0 * (attempt + 1)
                time.sleep(wait)
            else:
                time.sleep(2 ** attempt)
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


DEFAULT_CHAPTER_NUMBER_PATTERN = r"\b(?:chapter|ch|episode|ep|volume|vol|meeting)\s*[._#:-]*\s*([0-9]+(?:[.]\d+)?)\b"


def parse_chapter_number(label: str, pattern: str | None = None) -> str | None:
    # WeebCentral may label installments as Chapter, Ch., Episode, Volume,
    # or titles such as Meeting 1.
    try:
        match = re.search(pattern or DEFAULT_CHAPTER_NUMBER_PATTERN, label, re.I)
    except re.error:
        match = re.search(DEFAULT_CHAPTER_NUMBER_PATTERN, label, re.I)
    return match.group(1) if match and match.lastindex else None


def clean_chapter_label(label: str) -> str:
    """Remove reader-status metadata that sites append to chapter links."""
    return re.sub(r"\s+last\s+read\b.*$", "", " ".join(label.split()), flags=re.I).strip()


def number_key(number: str) -> tuple[int, int]:
    whole, _, fraction = number.partition(".")
    return int(whole), int((fraction + "00")[:2]) if fraction else 0


def discover_chapters(series_url: str, delay: float, locator: dict[str, object] | None = None) -> tuple[str, list[Chapter]]:
    base = f"{urlparse(series_url).scheme}://{urlparse(series_url).netloc}"
    series_html = fetch(series_url, delay=delay).decode("utf-8", "replace")
    parser = PageParser()
    parser.feed(series_html)
    series_title = re.search(r"<h1[^>]*>\s*(.*?)\s*</h1>", series_html, re.I | re.S)
    title = re.sub(r"<[^>]+>", "", series_title.group(1)).strip() if series_title else "series"

    # Older pages exposed a full-chapter-list endpoint. Newer pages can render
    # the complete list directly, so prefer the endpoint when it yields
    # chapters and fall back to the series landing page otherwise.
    locator = locator or {}
    href_pattern = str(locator.get("chapter_href_pattern") or r"/chapters/")
    number_pattern = str(locator.get("chapter_number_pattern") or DEFAULT_CHAPTER_NUMBER_PATTERN)
    try:
        href_re = re.compile(href_pattern, re.I)
    except re.error:
        href_re = re.compile(r"/chapters/", re.I)
    endpoint_match = re.search(r'hx-get="([^"]+/full-chapter-list)"', series_html)
    series_base = series_url.rstrip("/") + "/"
    full_list_url = urljoin(series_base, endpoint_match.group(1) if endpoint_match else "full-chapter-list")

    def parse_chapter_page(markup: str) -> dict[str, Chapter]:
        page_parser = PageParser()
        page_parser.feed(markup)
        found: dict[str, Chapter] = {}
        for href, label in page_parser.links:
            if not href_re.search(href):
                continue
            number = parse_chapter_number(label, number_pattern)
            if number is None:
                continue
            label = clean_chapter_label(label)
            url = urljoin(base, href)
            chapter_id = url.rstrip("/").split("/")[-1]
            found[chapter_id] = Chapter(number, label, url, chapter_id)
        return found

    chapters: dict[str, Chapter] = {}
    try:
        chapters = parse_chapter_page(fetch(full_list_url, delay=delay).decode("utf-8", "replace"))
    except RuntimeError:
        chapters = {}
    if not chapters:
        chapters = parse_chapter_page(series_html)
    return title, sorted(chapters.values(), key=lambda c: number_key(c.number))


def discover_pages(chapter: Chapter, delay: float, locator: dict[str, object] | None = None) -> list[str]:
    locator = locator or {}
    page_suffix = str(locator.get("page_list_suffix") or "/images?is_prev=False")
    images_url = chapter.url.rstrip("/") + page_suffix
    html = fetch(images_url, delay=delay).decode("utf-8", "replace")
    parser = PageParser()
    parser.feed(html)
    return [urljoin(chapter.url, src) for src, _ in parser.images if src and "broken_image" not in src]


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", str(value), flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    return cleaned or "untitled"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def image_extension(header: bytes) -> str | None:
    """Recognize supported image formats when a URL lacks an extension."""
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'webp'
    return None


def download_page(url: str, target: Path, delay: float, retries: int) -> None:
    if target.suffix == '.img':
        for suffix in ('.jpg', '.png', '.gif', '.webp'):
            existing = target.with_suffix(suffix)
            if existing.exists() and existing.stat().st_size > 0:
                return
    if target.suffix == '.img' and target.exists() and target.stat().st_size > 0:
        with target.open('rb') as source:
            extension = image_extension(source.read(12))
        if extension:
            target.replace(target.with_suffix('.' + extension))
            return
    if target.suffix != '.img' and target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    data = fetch(url, delay=delay, retries=retries)
    if target.suffix == '.img':
        extension = image_extension(data[:12])
        if extension is None:
            raise RuntimeError(f'Unsupported image data from {url}')
        target = target.with_suffix('.' + extension)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(target)


def crawl(series_url: str, output: Path, delay: float, workers: int, chapter_workers: int, metadata_only: bool, retries: int) -> None:
    title, chapters = discover_chapters(series_url, delay)
    root = output / safe_name(title)
    (root / "chapters").mkdir(parents=True, exist_ok=True)
    write_json(root / "series.json", {"title": title, "source": series_url, "chapter_count": len(chapters)})

    def discover_chapter(item: tuple[int, Chapter]) -> tuple[dict[str, object], list[tuple[str, Path]]]:
        index, chapter = item
        folder = root / "chapters" / f"{index:03d}-chapter-{safe_name(chapter.number)}"
        existing_meta = folder / "chapter.json"
        if existing_meta.exists():
            try:
                cached = json.loads(existing_meta.read_text(encoding="utf-8"))
                present = {int(p.stem) for p in folder.iterdir()
                           if p.is_file() and re.fullmatch(r"[0-9]{4}", p.stem)
                           and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                           and p.stat().st_size > 0}
                page_count = int(cached.get("page_count", -1))
                if (not metadata_only and cached.get("url") == chapter.url
                        and page_count > 0 and present.issuperset(range(1, page_count + 1))):
                    print(f"[{index}/{len(chapters)}] Chapter {chapter.number}: already complete", flush=True)
                    return cached, []
            except (OSError, ValueError, TypeError):
                pass
        print(f"[{index}/{len(chapters)}] Chapter {chapter.number}: discovering pages", flush=True)
        pages = discover_pages(chapter, delay)
        row = {**asdict(chapter), "order": index, "page_count": len(pages), "directory": str(folder.relative_to(root))}
        write_json(folder / "chapter.json", row)
        jobs = [(page_url, folder / f"{page_index:04d}.{guess_extension(page_url)}") for page_index, page_url in enumerate(pages, start=1)]
        return row, jobs

    # Discover every chapter's page list concurrently first. Then use one
    # shared page pool so workers never sit idle behind a small chapter.
    with ThreadPoolExecutor(max_workers=max(1, chapter_workers)) as chapter_pool:
        futures = [chapter_pool.submit(discover_chapter, item) for item in enumerate(chapters, start=1)]
        discovered = [future.result() for future in as_completed(futures)]
    chapter_rows = [row for row, _ in discovered]
    write_json(root / "chapters.json", sorted(chapter_rows, key=lambda value: int(value["order"])))
    if not metadata_only:
        jobs = [job for _, chapter_jobs in discovered for job in chapter_jobs]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as page_pool:
            futures = [page_pool.submit(download_page, page_url, target, delay, retries) for page_url, target in jobs]
            for future in as_completed(futures):
                future.result()
        print(f"  saved {len(jobs)} newly discovered page targets", flush=True)
    print(f"Done: {len(chapters)} chapters in {root}")


def guess_extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if suffix in {"jpg", "jpeg", "png", "webp", "gif"} else "img"


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl a manga series into ordered chapter folders.")
    parser.add_argument("series_url", nargs="?", default=DEFAULT_SERIES)
    parser.add_argument("-o", "--output", type=Path, default=Path("output") / "crawled")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (default: 1)")
    parser.add_argument("--workers", type=int, default=1, help="Parallel image downloads (default: 1)")
    parser.add_argument("--chapter-workers", type=int, default=1, help="Chapters processed concurrently (default: 1)")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--metadata-only", action="store_true", help="Discover chapters/pages without downloading images")
    args = parser.parse_args()
    try:
        crawl(args.series_url, args.output, max(0.0, args.delay), max(1, args.workers), max(1, args.chapter_workers), args.metadata_only, max(1, args.retries))
    except KeyboardInterrupt:
        print("Interrupted; rerun the same command to resume.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
