# Panel Press

Small, resumable crawler for a manga series. It discovers the complete chapter list, preserves chapter order, writes metadata, and optionally downloads page images into one folder per chapter.

Use this only where you have permission to download the material. Check the source site's terms and robots policy, and keep the rate limit conservative.

## Usage

No third-party Python packages are required for `crawler.py`.

Run the standard-library regression checks with `python3 -m unittest discover -s tests -v`.

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

Each chapter writes its own `chapter.json` once its page list is discovered, and `chapters.json` aggregates those rows. Existing non-empty page files are skipped, `.part` files are replaced atomically, and a chapter whose saved pages already match its recorded `page_count` is skipped, so an interrupted crawl can resume.

`--chapter-workers` controls concurrent chapter/page-list discovery. After discovery, `--workers` is one shared global image-download pool, so all discovered chapters can download concurrently instead of waiting chapter-by-chapter. If the host starts returning HTTP 429, lower either value or add a small `--delay`; 429 responses receive automatic backoff.

## Web app

Panel Press provides a local browser UI around the crawler and KCC conversion
flow:

```bash
python3 webapp.py
# open http://127.0.0.1:8080
```

The local API accepts JSON for scans and URL-based conversions, and multipart
uploads for local files. Uploads are limited to 1 GB per request; JSON requests
are limited to 1 MB. At most 50 conversion jobs are retained or running at once.

Or start the local app with:

```bash
./start.sh
```

On Windows, run `start.bat` from Command Prompt or double-click it.

Use `PORT=8081 ./start.sh` to run it on another port.

For complete Terminal instructions, see [START.md](START.md).

To deploy the frontend and bounded Python API together as one Vercel project,
with Vercel Queues handling queued conversion work, follow
[VERCEL.md](VERCEL.md).

Paste a series or chapter URL, scan its chapters, review the page counts and first-page links from a sample of up to three chapters, select the chapters to include, and
build a reader file. The UI also accepts local image files, a single PDF,
several PDFs (imported as ordered chapter folders), or a whole crawler folder.
Panel Press includes the KCC source under `vendor/kcc` and invokes its official
`kcc-c2e` CLI with the selected device profile, manga/webtoon mode, reading
direction, and output format. Kindle profiles request MOBI when KindleGen is
available, otherwise they request fixed-layout EPUB for Send to Kindle. Kobo
profiles request EPUB/KEPUB. If KCC's Python dependencies are unavailable, the app
creates a built-in CBZ, fixed-layout EPUB, or PDF fallback.

The output format is selectable in the UI: Auto, MOBI, EPUB, KEPUB, CBZ, or
PDF. When KindleGen is missing, the UI disables MOBI and an explicit API
request fails with KCC's error; Auto chooses fixed-layout EPUB for Kindle in
that case. Reading direction also
supports Auto: known manga sources such as WeebCentral default to right-to-left,
webtoons default to left-to-right, and explicit left-to-right/right-to-left
choices always override detection.

Packaging is also selectable: one combined file with KCC chapter navigation,
or separate output files for every chapter directory. Combined packaging can
add a generated divider image before each chapter.

The book name is editable and becomes the combined filename or batch prefix;
for example, `My Collection - 001-chapter-1.kepub.epub`. Quality presets map
to KCC settings: Balanced uses JPEG quality 85, Best enables KCC's
high-quality mode with JPEG quality 92, and Compact uses JPEG quality 72 to
reduce file size. Balanced is the recommended quality/size tradeoff for most
Kindle and Kobo devices.

The reader profile picker supports Kindle Basic, Paperwhite generations,
Voyage, Oasis, Colorsoft, and Scribe devices, plus Kobo Mini, Glo/Glo HD,
Aura/Aura HD/Aura H2O/Aura ONE, Nia, Clara, Libra, Forma, Sage, and Elipsa
models (including the Clara Colour and Libra Colour profiles). Profiles use
KCC's native device identifiers when KCC is installed.

The local picker supports a whole directory as well as individual files. For
example, choosing `output/Fire_Punch` imports every supported image beneath
the folder, orders them by relative path, and ignores `series.json`,
`chapters.json`, and `chapter.json` as pages. The source URL recorded in
`series.json` is reused to infer reading direction; direction itself is not
stored in the metadata, so a local folder from an unrecognized host defaults
to left-to-right unless chosen explicitly.

For a native KCC run, those relative directories are preserved in the staged
source passed to `kcc-c2e`; KCC can use each chapter directory as an ebook
navigation chapter. Several PDFs cannot be mixed with images and are expanded
into one ordered chapter folder each; a browser folder upload wrapped in a
single selected folder has that wrapper removed before KCC runs. Combined
EPUB/KEPUB output keeps KCC's chapter navigation but rewrites chapter labels
and drops the duplicate page-list view, and combined PDF output gets a bookmark
outline. The dependency-free fallback remains a single continuous
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

The scan checks the first, middle, and last chapter when available. It shows
errors and source-locator suggestions if a sampled chapter has no readable
pages, and enables Build after the sample passes. The sample is a quick check;
other chapters are discovered during conversion.

Crawler downloads are stored under `output/crawled/<series>/`. Each conversion
gets a separate `output/exports/<book>/<job-id>/files/` directory, with batch
chapter folders under the same job's `chapters/` directory. Enabling the
"Source image folder" option also copies the staged images to
`output/crawled/<book>/<job-id>/` and exports them as a `…source.zip` beside the
converted files. Install the bundled KCC
runtime packages once per Python environment:

```bash
python3 -m pip install -r vendor/kcc/requirements.txt
```

No separate KCC application install or `KCC_COMMAND` setting is needed. You
can still set `KCC_COMMAND` to override the bundled copy. MOBI conversion
additionally requires KindleGen/Kindle Previewer, as it does in KCC itself;
that proprietary tool is not bundled.

## Citation

If Panel Press is useful in your work, cite this repository. Replace the URL
below with the canonical repository or your fork where appropriate:

```bibtex
@software{panel_press,
  title  = {Panel Press: a local comic crawler and ebook builder},
  author = {{Panel Press contributors}},
  year   = {2026},
  note   = {Web UI and crawler built on Kindle Comic Converter (KCC)},
  url    = {https://github.com/finnhuynh65/panel-press}
}
```

Conversion output is produced by KCC. If you publish results that relied on
KCC, cite it as well:

```bibtex
@software{kcc,
  title  = {Kindle Comic Converter (KCC)},
  author = {Gonano, Ciro Mattia and Jastrz{\k{e}}bski, Pawe{\l} and Darodi and Xu, Alex},
  year   = {2012--2025},
  url    = {https://github.com/ciromattia/kcc}
}
```

## Used libraries and credits

The crawler (`crawler.py`) and web server (`webapp.py`) run on the Python
standard library. The Comix browser adapter (`comix_browser.py`) additionally
requires Playwright. Other third-party components are optional and are used
only for the features below:

| Component | Used for | License |
| --- | --- | --- |
| [Kindle Comic Converter](https://github.com/ciromattia/kcc) (bundled at `vendor/kcc`) | Device profiles and MOBI/EPUB/KEPUB/CBZ conversion | ISC |
| [Playwright](https://playwright.dev/) | Headless Chromium session for Comix | Apache-2.0 |
| [Pillow](https://python-pillow.org/) | Chapter dividers and the fallback EPUB/PDF builders | MIT-CMU |
| [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) | PDF bookmark/outline generation and KCC's own PDF handling | AGPL-3.0 (or commercial) |

PDF import rasterizes pages with the system `pdftoppm` command (Poppler) unless
a single PDF is handed straight to KCC, which uses PyMuPDF.

Installing KCC's runtime with `vendor/kcc/requirements.txt` also installs KCC's
own dependencies: PySide6 (LGPL-3.0), Pillow, psutil (BSD-3-Clause), requests
(Apache-2.0), python-slugify (MIT), packaging (Apache-2.0/BSD-2-Clause),
mozjpeg-lossless-optimization, natsort (MIT), numpy (BSD-3-Clause), and
PyMuPDF. See `vendor/kcc/requirements.txt` and `vendor/kcc/README.md` for the
authoritative list and versions.

KindleGen / Kindle Previewer is proprietary and is not bundled; it is only
needed for KCC's MOBI output.

KCC is Copyright (c) 2012-2025 Ciro Mattia Gonano, Paweł Jastrzębski, Darodi,
and Alex Xu, released under the ISC License (`vendor/kcc/LICENSE.txt`). KCC's
README additionally credits `DualMetaFix` by K. Hendricks, `image.py` from
[Mangle](https://github.com/FooSoft/mangle/) by Alex Yatskov, and its icon by
Nikolay Verin.

Only download material you are authorized to access, and keep the request
delay respectful of the source site's terms and robots policy.
