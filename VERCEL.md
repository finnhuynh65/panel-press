# Vercel deployment

Deploy the frontend and API as **one Vercel project** with the repository root (`.`) as the project root. The static interface is built from `apps/web`; Python handles chapter discovery and page manifests; a Node function streams source images to the browser.

## Configure the project

1. Set the Vercel project's Root Directory to the repository root.
2. Deploy. No Blob store, queue, Redis, or storage token is required.

`vercel.json` builds `apps/web/dist`, routes `/api/*` to the Python API, and exposes `/api/page-image` as a streaming image proxy. URL conversion downloads selected chapter pages sequentially into the browser, stores them in IndexedDB, and creates EPUB/CBZ files locally. Local image imports use the same browser-side path. No source images or finished books are uploaded to a storage service.

## Hosted limits

- Select any number of chapters. Each chapter is a separate download; chapters over 300 pages or 128 MiB are split into numbered parts. Each image is limited to 16 MiB. The browser discovers chapter page lists and fetches images concurrently, using the visible concurrency setting (1–6, default 3) and image request delay. It builds one part at a time. It keeps chapter files and source pages in IndexedDB. A batch ZIP is available for saved chapter files up to 256 MiB; larger batches remain available as individual downloads.
- Keep the browser tab open while pages are downloaded and the reader file is built. Page images and the finished file remain in browser memory/IndexedDB; clear saved images and chapter downloads from the interface when no longer needed. Browser storage quota varies by device and browser.
- Browser-side conversion supports EPUB and CBZ. PDF/MOBI/KEPUB and KCC device processing require the desktop app.
- The image proxy only accepts public HTTP(S) image hosts and streams each response with a 16 MiB cap.

See [Vercel's monorepo guide](https://vercel.com/docs/monorepos), [Python runtime guide](https://vercel.com/docs/functions/runtimes/python), and [Function limits](https://vercel.com/docs/functions/limitations).

## Local checks

```bash
python3 -m unittest discover -s tests -v
cd apps/web && npm run build
```

For a local frontend build, `PANEL_API_ORIGIN` defaults to `http://127.0.0.1:8080`; start the local API with `python3 webapp.py`.
