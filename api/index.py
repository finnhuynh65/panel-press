"""Vercel API for chapter discovery and image-page manifests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

import webapp

MAX_CHAPTERS_PER_MANIFEST = 1
MAX_BODY_BYTES = 1_000_000
MAX_PACKAGE_PAGES = 300
MAX_PACKAGE_BYTES = 128 * 1024 * 1024
MAX_BROWSER_PAGE_BYTES = 16 * 1024 * 1024


def conversion_pages(payload: dict[str, object]) -> dict[str, object]:
    """Return an ordered page manifest; image transfer and packaging stay in the browser."""
    selected = payload.get('chapters')
    if not isinstance(selected, list) or len(selected) != MAX_CHAPTERS_PER_MANIFEST:
        raise ValueError('Request one chapter per page manifest.')
    source_url = payload.get('url')
    if not isinstance(source_url, str) or urlparse(source_url).scheme not in {'http', 'https'}:
        raise ValueError('Enter an HTTP or HTTPS series URL.')
    delay = webapp.request_delay(payload.get('delay'))
    locator = payload.get('locator') if isinstance(payload.get('locator'), dict) else None
    pages: list[dict[str, object]] = []
    for chapter_index, row in enumerate(selected, 1):
        if not isinstance(row, dict) or not isinstance(row.get('url'), str):
            raise ValueError('A selected chapter is invalid.')
        chapter_url = row['url']
        if urlparse(chapter_url).scheme not in {'http', 'https'}:
            raise ValueError('A chapter URL must use HTTP or HTTPS.')
        chapter = webapp.Chapter(str(row.get('number') or chapter_index),
                                 str(row.get('title') or f'Chapter {chapter_index}'),
                                 chapter_url, str(row.get('chapter_id') or ''))
        image_urls = webapp.chapter_pages(chapter, delay, locator)
        if not image_urls:
            raise ValueError(f'No pages were found for {chapter.title}.')
        for page_index, image_url in enumerate(image_urls, 1):
            parsed = urlparse(image_url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or len(image_url) > 2048:
                raise ValueError('A page image URL is invalid.')
            pages.append({'url': image_url, 'referer': chapter_url,
                          'chapter': chapter.title, 'chapter_number': chapter.number,
                          'chapter_index': chapter_index, 'page_index': page_index})
    return {'title': Path(urlparse(source_url).path.rstrip('/')).name or 'Comic',
            'pages': pages, 'max_page_bytes': MAX_BROWSER_PAGE_BYTES,
            'max_part_pages': MAX_PACKAGE_PAGES,
            'max_part_bytes': MAX_PACKAGE_BYTES,
            'delay': delay,
            'direction': webapp.resolve_direction('auto', source_url)}


class handler(webapp.Handler):
    """Same scan contract as the local app, with browser-side conversion."""

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
                            'hosted': True, 'chapters_per_manifest': MAX_CHAPTERS_PER_MANIFEST,
                            'max_pages_per_file': MAX_PACKAGE_PAGES,
                            'max_total_bytes_per_file': MAX_PACKAGE_BYTES,
                            'max_page_bytes': MAX_BROWSER_PAGE_BYTES})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        route = self._route_path()
        origin = self.headers.get('Origin')
        if origin and not self._allowed_origin():
            self.send_json({'error': 'Origin is not allowed.'}, 403)
            return
        if route not in {'/api/v1/scans', '/api/scan', '/api/v1/pages'}:
            self.send_error(404)
            return
        content_type = self.headers.get('Content-Type', '')
        if not content_type.lower().startswith('application/json'):
            self.send_json({'error': 'Hosted API accepts JSON only.'}, 415)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY_BYTES:
                self.send_json({'error': f'Request body must be between 1 and {MAX_BODY_BYTES} bytes.'}, 413)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON object.')
            if 'files' in payload or '_upload_dir' in payload:
                raise ValueError('Image files are converted in the browser and must not be uploaded.')
            if route in {'/api/v1/scans', '/api/scan'}:
                result = webapp.scan_preview(str(payload.get('url') or ''),
                                             webapp.request_delay(payload.get('delay')),
                                             payload.get('locator') if isinstance(payload.get('locator'), dict) else None)
            else:
                result = conversion_pages(payload)
            self.send_json(result)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.send_json({'error': str(exc)}, 400)
        except Exception as exc:
            self.send_json({'error': str(exc)}, 500)
