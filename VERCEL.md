# Vercel deployment

The `vercel` branch contains two deployable projects in one repository:

| Project | Root Directory | Runtime | Purpose |
| --- | --- | --- | --- |
| API | repository root (`.`) | Python 3.12 Function | Scan, sample preview, queue requests, job status |
| Web | `apps/web` | static build | Browser interface |
| Conversion consumer | `queues/conversions.py` | Python Queue Function | Download, convert, stream files to Blob |

Python remains the backend language so the existing source adapters and EPUB/CBZ
builder can be reused. The desktop KCC dependencies are not installed in the
Function.

## Configure the API project

1. Import this repository into Vercel and set **Root Directory** to the repository root.
2. Enable Vercel Queues for the project. The API publishes conversion jobs to
   the `panel-press-conversions` topic; `pyproject.toml` registers the Python
   subscriber. No Redis service or separate worker host is required.
3. Set `PANEL_WEB_ORIGIN` to the exact deployed frontend origin, such as
   `https://panel-press-web.vercel.app` (no trailing slash).
4. Deploy. The API endpoint is `https://<api-project>/api/v1/capabilities`.

The root [`vercel.json`](vercel.json) routes `/api/*` to the Python API.
Vercel Queues invokes the registered Python consumer and retries failed
deliveries. Job status and progress are stored in Vercel Runtime Cache for seven
days. Create a **public** Vercel Blob store and enable its read-write token for
the project. Finished exports are uploaded in 1 MiB chunks, so the complete
archive is never copied into one in-memory byte string.

## Configure the web project

1. Import the **same repository** again as a second Vercel project and set
   **Root Directory** to `apps/web`.
2. Set `PANEL_API_ORIGIN` to the API project's origin, such as
   `https://panel-press-api.vercel.app` (no trailing slash).
3. Deploy. Its build writes `dist/index.html` and `dist/config.js`.

The frontend sends API requests to that configured origin. For a preview web
deployment, set the API project's `PANEL_WEB_ORIGIN` to the preview origin if
you want to test cross-origin requests there.

## Hosted limits

- Select up to three chapters per conversion. The queue consumer also stops before
  downloading more than 300 pages, 256 MiB total, or 16 MiB for one image. These
  bounds are in [`webapp.py`](webapp.py) and can be adjusted for the worker size.
- Hosted conversion accepts URL sources and produces Auto, EPUB, or CBZ. Use
  the local app for PDF/MOBI/KEPUB, local uploads, source-folder exports, or
  larger batches.
- The queue consumer downloads hosted page images sequentially to enforce the total byte
  cap with bounded memory. This trades throughput for a predictable memory
  ceiling. Vercel Queues controls delivery concurrency.
- Vercel Functions limit request and response bodies to 4.5 MB. Finished files
  go from the queue consumer to Vercel Blob in chunks, so they do not pass through the
  Function response.
  Blob URLs are public and can be opened by anyone who has the URL.

See [Vercel's monorepo guide](https://vercel.com/docs/monorepos),
[Python runtime guide](https://vercel.com/docs/functions/runtimes/python),
[Function limits](https://vercel.com/docs/functions/limitations), and
[Blob upload guide](https://vercel.com/docs/vercel-blob/using-blob-sdk).

## Local checks

```bash
python3 -m unittest discover -s tests -v
cd apps/web && npm run build
```

For a local frontend build, `PANEL_API_ORIGIN` defaults to
`http://127.0.0.1:8080`; start the local API with `python3 webapp.py`.
