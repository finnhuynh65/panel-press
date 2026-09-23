"""Vercel entry point for bounded, URL-based Panel Press conversions."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import webapp


# Functions can write to /tmp, while the deployed source tree is read-only.
webapp.OUTPUT = Path(tempfile.gettempdir()) / 'panel-press-output'
webapp.EXPORTS = webapp.OUTPUT / 'exports'
MAX_CHAPTERS = 3
MAX_BODY_BYTES = 1_000_000


def convert_small(payload: dict[str, object]) -> dict[str, object]:
    """Build during the request and publish the finished files to Blob."""
    if not os.environ.get('BLOB_READ_WRITE_TOKEN'):
        raise RuntimeError('BLOB_READ_WRITE_TOKEN is required for hosted conversions.')
    selected = payload.get('chapters')
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_CHAPTERS:
        raise ValueError(f'Select 1 to {MAX_CHAPTERS} chapters for a hosted conversion.')
    if not isinstance(payload.get('url'), str) or not payload['url'].strip():
        raise ValueError('A series URL is required.')
    if urlparse(payload['url']).scheme not in {'http', 'https'}:
        raise ValueError('Enter an HTTP or HTTPS series URL.')
    if payload.get('save_source') is True or payload.get('save_source') == 'true' or payload.get('folder_mode') == 'separate':
        raise ValueError('Hosted conversion does not save source folders. Use the local app for that option.')
    options = webapp.ConversionOptions.from_payload(payload)
    if options.output_format not in {'auto', 'epub', 'cbz'}:
        raise ValueError('Hosted conversion supports Auto, EPUB, and CBZ formats.')

    job_id = uuid.uuid4().hex
    with webapp.JOBS_LOCK:
        webapp.JOBS[job_id] = {'status': 'working', 'message': 'Starting…'}
    try:
        webapp.convert_job(job_id, payload)
        with webapp.JOBS_LOCK:
            result = dict(webapp.JOBS[job_id])
        if result.get('status') != 'done':
            return result

        from vercel.blob import BlobClient

        client = BlobClient()
        urls = []
        for download in result['files']:
            path = webapp.downloadable_path(download)
            if path is None:
                raise RuntimeError('Generated file is unavailable.')
            blob = client.put(f'panel-press/{job_id}/{path.name}', path.read_bytes(),
                              access='public', content_type='application/octet-stream')
            urls.append(blob.url)
        return {'status': 'done', 'message': result['message'], 'files': urls}
    finally:
        with webapp.JOBS_LOCK:
            webapp.JOBS.pop(job_id, None)
        # Every conversion writes to its own job directory.
        for book in webapp.EXPORTS.glob('*'):
            shutil.rmtree(book / job_id, ignore_errors=True)


class handler(webapp.Handler):
    """Same scan contract as the local app, with Vercel-safe conversion."""

    def _allowed_origin(self) -> str | None:
        origin = self.headers.get('Origin')
        configured = os.environ.get('PANEL_WEB_ORIGIN', '').rstrip('/')
        if origin and (origin == configured or origin == f'https://{self.headers.get("Host")}'):
            return origin
        return None

    def end_headers(self) -> None:
        origin = self._allowed_origin()
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self) -> None:
        if not self._allowed_origin():
            self.send_error(403)
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in {'/api/v1/capabilities', '/api/capabilities'}:
            self.send_json({'kcc': False, 'kindlegen': False, 'pillow': webapp._has_pillow(),
                            'hosted': True, 'max_chapters': MAX_CHAPTERS})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        origin = self.headers.get('Origin')
        if origin and not self._allowed_origin():
            self.send_json({'error': 'Origin is not allowed.'}, 403)
            return
        if self.path not in {'/api/v1/scans', '/api/scan', '/api/v1/conversions', '/api/convert'}:
            self.send_error(404)
            return
        content_type = self.headers.get('Content-Type', '')
        if not content_type.lower().startswith('application/json'):
            self.send_json({'error': 'Hosted API accepts JSON only. Use the local app for file imports.'}, 415)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY_BYTES:
                self.send_json({'error': 'Request body must be between 1 and 1000000 bytes.'}, 413)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON object.')
            if 'files' in payload or '_upload_dir' in payload:
                raise ValueError('Local files are not supported by the hosted API.')
            if self.path in {'/api/v1/scans', '/api/scan'}:
                result = webapp.scan_preview(str(payload.get('url') or ''),
                                             webapp.request_delay(payload.get('delay')),
                                             payload.get('locator') if isinstance(payload.get('locator'), dict) else None)
            else:
                result = convert_small(payload)
            self.send_json(result)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.send_json({'error': str(exc)}, 400)
        except Exception as exc:
            self.send_json({'error': str(exc)}, 500)
