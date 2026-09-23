# Vercel deployment

The `vercel` branch contains two deployable projects in one repository:

| Project | Root Directory | Runtime | Purpose |
| --- | --- | --- | --- |
| API | repository root (`.`) | Python 3.12 Function | Scan, sample preview, small URL conversions |
| Web | `apps/web` | static build | Browser interface |

Python remains the backend language so the existing source adapters and EPUB/CBZ
builder can be reused. The desktop KCC dependencies are not installed in the
Function.

## Configure the API project

1. Import this repository into Vercel and set **Root Directory** to the repository root.
2. Create a **public** Vercel Blob store connected to the API project. It supplies
   `BLOB_READ_WRITE_TOKEN` for exported files.
3. Set `PANEL_WEB_ORIGIN` to the exact deployed frontend origin, such as
   `https://panel-press-web.vercel.app` (no trailing slash).
4. Deploy. The API endpoint is `https://<api-project>/api/v1/capabilities`.

The root [`vercel.json`](vercel.json) configures the Python Function and routes
`/api/*` to it. The Function writes intermediate files to `/tmp`, builds during
the HTTP request, uploads the result to Blob, and removes its temporary files.

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

- Select up to three chapters per conversion. The scan still discovers the full
  chapter list and previews a sample of up to three chapters.
- Hosted conversion accepts URL sources and produces Auto, EPUB, or CBZ. Use
  the local app for PDF/MOBI/KEPUB, local uploads, source-folder exports, or
  larger batches.
- Conversion runs within one Function request. A slow source or large chapter
  can reach the Vercel duration or memory limit. The hosted UI shows errors
  directly instead of relying on the local app's in-memory job poller.
- Vercel Functions limit request and response bodies to 4.5 MB. Finished files
  go directly to Vercel Blob, so they do not pass through the Function response.
  Blob URLs are public and can be opened by anyone who has the URL.

See [Vercel's monorepo guide](https://vercel.com/docs/monorepos),
[Python runtime guide](https://vercel.com/docs/functions/runtimes/python),
[Function limits](https://vercel.com/docs/functions/limitations), and
[Blob upload guide](https://vercel.com/docs/vercel-blob/server-upload).

## Local checks

```bash
python3 -m unittest discover -s tests -v
cd apps/web && npm run build
```

For a local frontend build, `PANEL_API_ORIGIN` defaults to
`http://127.0.0.1:8080`; start the local API with `python3 webapp.py`.
