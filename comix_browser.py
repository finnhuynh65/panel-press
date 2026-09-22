#!/usr/bin/env python3
"""Browser-backed Comix crawler.

Comix protects its JSON API with browser-generated client state, so this
adapter uses Playwright instead of making direct API requests. Use only for
material you are authorized to download.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


CHROME_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", str(value), flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    return cleaned or "untitled"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def chapter_number(url: str, fallback: int) -> str:
    match = re.search(r"chapter-([0-9]+(?:[.][0-9]+)?)", url, re.I)
    return match.group(1) if match else str(fallback)


def discover_chapters(page, series_url: str) -> list[str]:
    page.goto(series_url, wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(1_000)
    pages = page.locator("button.npager__num")
    page_count = pages.count()
    urls: set[str] = set()
    for page_index in range(page_count):
        if page_index:
            page.locator("button.npager__num").nth(page_index).click(force=True)
            page.wait_for_timeout(500)
        for url in page.locator("a").evaluate_all("els => els.map(e => e.href).filter(Boolean)"):
            if "/title/" in url and "chapter-" in url:
                urls.add(url)
    return sorted(urls, key=lambda url: float(chapter_number(url, 0)))


def extract_pages(page, chapter_url: str) -> list[str]:
    page.goto(chapter_url, wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(1_000)
    return list(dict.fromkeys(page.locator("img").evaluate_all("els => els.map(e => e.currentSrc || e.src).filter(Boolean)")))


def crawl(series_url: str, output: Path, metadata_only: bool) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=CHROME_UA, viewport={"width": 1440, "height": 900})
        page = context.new_page()
        title = urlparse(series_url).path.rstrip("/").split("/")[-1].split("-")[-1] or "comix"
        title = page.title() if page.url else title
        chapters = discover_chapters(page, series_url)
        title = page.title() or title
        root = output / safe_name(title)
        (root / "chapters").mkdir(parents=True, exist_ok=True)
        rows = []
        for index, url in enumerate(chapters, 1):
            number = chapter_number(url, index)
            folder = root / "chapters" / f"{index:03d}-chapter-{safe_name(number)}"
            print(f"[{index}/{len(chapters)}] Chapter {number}", flush=True)
            pages = extract_pages(page, url)
            row = {"order": index, "number": number, "url": url, "page_count": len(pages), "directory": str(folder.relative_to(root))}
            write_json(folder / "chapter.json", row)
            rows.append(row)
            if not metadata_only:
                for page_index, image_url in enumerate(pages, 1):
                    target = folder / f"{page_index:04d}.jpg"
                    if target.exists() and target.stat().st_size:
                        continue
                    response = context.request.get(image_url, headers={"Referer": url})
                    if not response.ok:
                        raise RuntimeError(f"image request failed ({response.status}): {image_url}")
                    temporary = target.with_suffix(".jpg.part")
                    temporary.write_bytes(response.body())
                    temporary.replace(target)
        write_json(root / "series.json", {"title": title, "source": series_url, "chapter_count": len(rows)})
        write_json(root / "chapters.json", rows)
        browser.close()
        print(f"Done: {len(rows)} chapters in {root}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl a Comix series through a browser session.")
    parser.add_argument("series_url")
    parser.add_argument("-o", "--output", type=Path, default=Path("output"))
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    crawl(args.series_url, args.output, args.metadata_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
