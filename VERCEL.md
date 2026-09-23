# Vercel deployment

Deploy the frontend, Python API, and queue consumer as **one Vercel project**.
The project root is the repository root (`.`); the root configuration builds
the static interface from `apps/web` and routes `/api/*` to the Python API.

## Configure the project

1. Set the Vercel project's **Root Directory** to the repository root.
2. Enable Vercel Queues for the project. The API publishes conversion jobs to
   `panel-press-conversions`; `pyproject.toml` registers the Python subscriber.
3. Create a **public** Vercel Blob store and enable its read-write token for
   this project.
4. Deploy. The frontend always calls `/api/*` on its own domain in Vercel.
   `PANEL_API_ORIGIN` is only used by local builds.

`vercel.json` runs `cd apps/web && npm run build`, serves `apps/web/dist`, and
routes `/api/*` to `api/index.py`. The API accepts same-origin requests without
extra CORS settings.

Vercel Queues invokes the Python consumer and retries failed deliveries. Job
status and progress are stored in Vercel Runtime Cache for seven days. Finished
exports are uploaded to Blob in 1 MiB chunks, so the complete archive is never
copied into one in-memory byte string.

## Hosted limits

- Select up to three chapters per conversion. The queue consumer also stops
  before downloading more than 300 pages, 256 MiB total, or 16 MiB for one
  image. These limits are in [`webapp.py`](webapp.py).
- Hosted conversion accepts URL sources and produces Auto, EPUB, or CBZ. Use
  the local app for PDF/MOBI/KEPUB, local uploads, source-folder exports, or
  larger batches.
- The queue consumer downloads hosted page images sequentially to enforce the
  total byte cap with bounded memory. Vercel Queues controls delivery
  concurrency.
- Vercel Functions limit request and response bodies to 4.5 MB. Finished files
  go from the queue consumer to Vercel Blob in chunks, so they do not pass
  through the API response. Blob URLs are public and can be opened by anyone
  who has the URL.

See [Vercel's monorepo guide](https://vercel.com/docs/monorepos),
[Python runtime guide](https://vercel.com/docs/functions/runtimes/python),
[Queues guide](https://vercel.com/docs/queues),
[Function limits](https://vercel.com/docs/functions/limitations), and
[Blob upload guide](https://vercel.com/docs/vercel-blob/using-blob-sdk).

## Local checks

```bash
python3 -m unittest discover -s tests -v
cd apps/web && npm run build
```

For a local frontend build, `PANEL_API_ORIGIN` defaults to
`http://127.0.0.1:8080`; start the local API with `python3 webapp.py`.
