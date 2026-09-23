"""Vercel entry point for bounded, URL-based Panel Press conversions."""

from __future__ import annotations

import json
import os
import asyncio
import uuid
from urllib.parse import parse_qs, urlparse, urlsplit

import webapp
from vercel.functions import RuntimeCache
from vercel.queue import send


MAX_CHAPTERS = webapp.MAX_HOSTED_CHAPTERS
MAX_BODY_BYTES = 1_000_000
JOB_TTL_SECONDS = 7 * 24 * 60 * 60
QUEUE_TOPIC = 'panel-press-conversions'
JOB_CACHE = RuntimeCache(namespace='panel-press-jobs')


def enqueue_conversion(payload: dict[str, object]) -> dict[str, str]:
    """Persist a conversion request and return without downloading pages."""
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
    if options.packaging != 'combined' or options.divider or options.webtoon:
        raise ValueError('Hosted conversion supports combined comic or manga EPUB/CBZ output without divider pages.')
    if options.quality != 'balanced':
        raise ValueError('Hosted conversion uses balanced image quality.')

    job_id = uuid.uuid4().hex
    state = {'status': 'queued', 'message': 'Waiting for a worker…', 'files': []}
    JOB_CACHE.set(f'job:{job_id}', state, {'ttl': JOB_TTL_SECONDS})
    try:
        asyncio.run(send(QUEUE_TOPIC, {'job_id': job_id, 'payload': payload},
                         idempotency_key=job_id, retention=JOB_TTL_SECONDS))
    except Exception:
        JOB_CACHE.delete(f'job:{job_id}')
        raise
    return {'job_id': job_id, 'status': 'queued', 'message': state['message']}


def conversion_status(job_id: str) -> dict[str, object]:
    if not all(char in '0123456789abcdef' for char in job_id) or len(job_id) != 32:
        return {'status': 'error', 'message': 'Unknown job.'}
    row = JOB_CACHE.get(f'job:{job_id}')
    if not row:
        return {'status': 'error', 'message': 'Unknown or expired job.'}
    return {'status': row.get('status', 'error'), 'message': row.get('message', ''),
            'files': row.get('files', [])}


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

    def _route_path(self) -> str:
        parsed = urlsplit(self.path)
        rewritten = parse_qs(parsed.query).get('__pp_route', [])
        if rewritten and rewritten[0].startswith('/api/'):
            return rewritten[0]
        return parsed.path

    def do_OPTIONS(self) -> None:
        if not self._allowed_origin():
            self.send_error(403)
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self) -> None:
        route = self._route_path()
        if route in {'/api/v1/capabilities', '/api/capabilities'}:
            self.send_json({'kcc': False, 'kindlegen': False, 'pillow': webapp._has_pillow(),
                            'hosted': True, 'max_chapters': MAX_CHAPTERS,
                            'max_pages': webapp.MAX_HOSTED_PAGES,
                            'max_total_bytes': webapp.MAX_HOSTED_BYTES,
                            'max_page_bytes': webapp.MAX_HOSTED_PAGE_BYTES})
            return
        if route.startswith('/api/v1/conversions/'):
            self.send_json(conversion_status(route.rsplit('/', 1)[-1]))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        route = self._route_path()
        origin = self.headers.get('Origin')
        if origin and not self._allowed_origin():
            self.send_json({'error': 'Origin is not allowed.'}, 403)
            return
        if route not in {'/api/v1/scans', '/api/scan', '/api/v1/conversions', '/api/convert'}:
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
            if route in {'/api/v1/scans', '/api/scan'}:
                result = webapp.scan_preview(str(payload.get('url') or ''),
                                             webapp.request_delay(payload.get('delay')),
                                             payload.get('locator') if isinstance(payload.get('locator'), dict) else None)
            else:
                result = enqueue_conversion(payload)
            self.send_json(result)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.send_json({'error': str(exc)}, 400)
        except Exception as exc:
            self.send_json({'error': str(exc)}, 500)
