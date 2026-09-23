"""Vercel Queues consumer for hosted comic conversions."""

from __future__ import annotations

import asyncio
import shutil
import threading
from pathlib import Path

import webapp
from vercel.blob import AsyncBlobClient
from vercel.functions import RuntimeCache
from vercel.queue import Message, subscribe


QUEUE_TOPIC = 'panel-press-conversions'
JOB_TTL_SECONDS = 7 * 24 * 60 * 60
JOB_CACHE = RuntimeCache(namespace='panel-press-jobs')
WORK_DIR = Path('/tmp/panel-press-worker')
webapp.OUTPUT = WORK_DIR / 'output'
webapp.EXPORTS = webapp.OUTPUT / 'exports'


def set_state(job_id: str, status: str, message: str,
              files: list[str] | None = None) -> None:
    state = {'status': status, 'message': message}
    if files is not None:
        state['files'] = files
    JOB_CACHE.set(f'job:{job_id}', state, {'ttl': JOB_TTL_SECONDS})


async def file_chunks(path: Path):
    with path.open('rb') as source:
        while True:
            chunk = await asyncio.to_thread(source.read, 1024 * 1024)
            if not chunk:
                break
            yield chunk


async def publish_outputs(paths: list[Path], job_id: str) -> list[str]:
    client = AsyncBlobClient()
    urls = []
    for path in paths:
        blob = await client.put(
            f'panel-press/{job_id}/{path.name}', file_chunks(path), access='public',
            content_type='application/octet-stream', multipart=True, overwrite=True,
        )
        urls.append(blob.url)
    return urls


def cleanup_job(job_id: str) -> None:
    for book in webapp.EXPORTS.glob('*'):
        shutil.rmtree(book / job_id, ignore_errors=True)


@subscribe(topic=QUEUE_TOPIC, max_concurrency=1, max_attempts=5)
async def process_conversion(message: Message[dict[str, object]]) -> None:
    payload = message.payload
    job_id = str(payload['job_id'])
    conversion_payload = payload['payload']
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    with webapp.JOBS_LOCK:
        webapp.JOBS[job_id] = {'status': 'working', 'message': 'Worker started…'}
    set_state(job_id, 'working', 'Worker started…', [])

    stop_reporter = threading.Event()

    def report_progress() -> None:
        while not stop_reporter.wait(2):
            with webapp.JOBS_LOCK:
                current = dict(webapp.JOBS.get(job_id, {}))
            if current.get('status') == 'working':
                set_state(job_id, 'working', str(current.get('message', 'Conversion running…')))

    reporter = threading.Thread(target=report_progress, daemon=True)
    reporter.start()
    try:
        await asyncio.to_thread(webapp.convert_job, job_id, conversion_payload, hosted_limits=True)
        stop_reporter.set()
        reporter.join(timeout=16)
        with webapp.JOBS_LOCK:
            result = dict(webapp.JOBS[job_id])
        if result.get('status') != 'done':
            set_state(job_id, 'error', str(result.get('message', 'Conversion failed.')), [])
            return
        paths = [webapp.downloadable_path(url) for url in result.get('files', [])]
        if not paths or any(path is None for path in paths):
            raise RuntimeError('Generated files are unavailable for upload.')
        urls = await publish_outputs(paths, job_id)
        set_state(job_id, 'done', str(result.get('message', 'Conversion complete.')), urls)
    except Exception as exc:
        if message.delivery_count >= 5:
            set_state(job_id, 'error', f'Conversion failed after retries: {exc}', [])
            return
        set_state(job_id, 'queued', f'Conversion will retry: {exc}')
        raise
    finally:
        stop_reporter.set()
        reporter.join(timeout=1)
        with webapp.JOBS_LOCK:
            webapp.JOBS.pop(job_id, None)
        cleanup_job(job_id)
