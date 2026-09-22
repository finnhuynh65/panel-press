# Comic Crawler

Small, resumable crawler for a manga series. It discovers the complete chapter list, preserves chapter order, writes metadata, and optionally downloads page images into one folder per chapter.

Use this only where you have permission to download the material. Check the source site's terms and robots policy, and keep the rate limit conservative.

## Usage

No third-party Python packages are required.

For Comix, install Playwright and its Chromium browser once:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
python3 comix_browser.py https://comix.ws/title/9gdx5-trace --metadata-only
```

Remove `--metadata-only` to download pages. This uses a real browser session because Comix protects its API from direct HTTP clients.

```bash
python3 crawler.py --metadata-only
python3 crawler.py --output ./output/crawled --delay 0 --workers 32 --chapter-workers 4
```

The default URL is the Fire Punch series from the request. A different series can be supplied as the first argument.

Output:

```text
output/crawled/Fire_Punch/
├── series.json
├── chapters.json
└── chapters/
    ├── 001-chapter-1/
    │   ├── chapter.json
    │   ├── 0001.png
    │   └── ...
    └── ...
```

Existing non-empty page files are skipped, `.part` files are replaced atomically, and `chapters.json` is updated after each chapter so an interrupted crawl can resume.

`--chapter-workers` controls concurrent chapter/page-list discovery. After discovery, `--workers` is one shared global image-download pool, so all discovered chapters can download concurrently instead of waiting chapter-by-chapter. If the host starts returning HTTP 429, lower either value or add a small `--delay`; 429 responses receive automatic backoff.

## Web app

Panel Press provides a local browser UI around the crawler and KCC conversion
flow:

```bash
python3 webapp.py
# open http://127.0.0.1:8080
```

Or start the local app with:

```bash
./start.sh
```

On Windows, run `start.bat` from Command Prompt or double-click it.

Use `PORT=8081 ./start.sh` to run it on another port.

For complete Terminal instructions, see [START.md](START.md).

Paste a series URL, scan its chapters, select the chapters to include, and
build a reader file. The UI also accepts local image files or a PDF. Panel
Press includes the KCC source under `vendor/kcc` and invokes its official
`kcc-c2e` CLI with the selected device profile, manga/webtoon mode, reading
direction, and output format. Kindle profiles request MOBI when KindleGen is
available, otherwise they request fixed-layout EPUB for Send to Kindle. Kobo
profiles request EPUB/KEPUB. If KCC's Python dependencies are unavailable, the app
creates a built-in CBZ or fixed-layout EPUB fallback.

The output format is selectable in the UI: Auto, MOBI, EPUB, KEPUB, CBZ, or
PDF. Explicit MOBI selection reports a clear error when KindleGen is missing;
Auto chooses fixed-layout EPUB for Kindle in that case. Reading direction also
supports Auto: known manga sources such as WeebCentral default to right-to-left,
webtoons default to left-to-right, and explicit left-to-right/right-to-left
choices always override detection.

Packaging is also selectable: one combined file with KCC chapter navigation,
or separate output files for every chapter directory. Combined packaging can
add a generated divider image before each chapter after the first.

The book name is editable and becomes the combined filename or batch prefix;
for example, `My Collection - 001-chapter-1.kepub.epub`. Quality presets map
to KCC settings: Balanced uses high-quality JPEG output, Best enables KCC's
high-quality mode with JPEG quality 92, and Compact uses JPEG quality 72 to
reduce file size. Balanced is the recommended quality/size tradeoff for most
Kindle and Kobo devices.

The reader profile picker supports Kindle Basic, Paperwhite generations,
Voyage, Oasis, Colorsoft, and Scribe devices, plus Kobo Mini, Glo, Aura, Nia,
Clara, Libra, Forma, Sage, and Elipsa models (including the Clara Colour and
Libra Colour profiles). Profiles use KCC's native device identifiers when KCC
is installed.

The local picker supports a whole directory as well as individual files. For
example, choosing `output/Fire_Punch` imports every supported image beneath
the folder, orders them by relative path, and ignores `series.json`,
`chapters.json`, and `chapter.json` metadata files.

For a native KCC run, those relative directories are preserved in the staged
source passed to `kcc-c2e`; KCC can use each chapter directory as an ebook
navigation chapter. The dependency-free fallback remains a single continuous
book because it does not include KCC's chapter-navigation builder.

For KCC, importing original page images is usually the better route for a web
comic: it preserves the source page boundaries and avoids an extra
rasterization step. Import a PDF when it is the highest-quality source, has
intentional spreads, or is already a well-formed scan. KCC accepts both, but
its PDF path extracts/rasterizes pages to the selected device resolution.

The URL is intentionally configurable. The built-in adapter uses a source's
series-list and chapter-image endpoints when available. Other sites use a fallback parser
that looks for links labelled like `chapter`, `episode`, or `volume`, then
reads image tags from each chapter page (including common lazy-loading
attributes such as `data-src`). For a site with a different structure, add a
site-specific adapter beside `generic_discover` and `generic_discover_pages`
in `webapp.py`.

Crawler downloads are stored under `output/crawled/<series>/`. Converted files
are stored separately under `output/exports/<book>/files/`, with batch chapter
folders under `output/exports/<book>/chapters/`. Install the bundled KCC
runtime packages once per Python environment:

```bash
python3 -m pip install -r vendor/kcc/requirements.txt
```

No separate KCC application install or `KCC_COMMAND` setting is needed. You
can still set `KCC_COMMAND` to override the bundled copy. MOBI conversion
additionally requires KindleGen/Kindle Previewer, as it does in KCC itself;
that proprietary tool is not bundled.

Only download material you are authorized to access, and keep the request
delay respectful of the source site's terms and robots policy.
