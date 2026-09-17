from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from config import Config

logger = logging.getLogger(__name__)
_development_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='report-worker')


def enqueue_report(user_id, line_user_id, items, user_settings, request_id=None):
    """Queue work outside the webhook; Redis/RQ is the production transport."""
    request_id = request_id or uuid4().hex
    payload = {
        'user_id': user_id,
        'line_user_id': line_user_id,
        'items': items,
        'user_settings': user_settings,
        'request_id': request_id,
    }
    if Config.REDIS_URL and Config.REPORT_QUEUE_MODE != 'local':
        try:
            from redis import Redis
            from rq import Queue

            queue = Queue(Config.QUEUE_NAME, connection=Redis.from_url(Config.REDIS_URL))
            queue.enqueue('tasks.worker.process_report_job', payload, job_id=request_id, result_ttl=86400)
            return {'id': request_id, 'transport': 'rq'}
        except Exception as exc:
            if Config.REPORT_QUEUE_MODE == 'rq':
                raise RuntimeError(f'Could not enqueue Redis report job: {exc}') from exc
            logger.warning('Redis queue unavailable; using development worker: %s', exc)

    # This is intentionally a managed development fallback. Production should set
    # REDIS_URL and use an RQ worker process, not rely on web-process memory.
    _development_executor.submit(_run_local, payload)
    return {'id': request_id, 'transport': 'development'}


def _run_local(payload):
    from tasks.worker import process_report_job
    process_report_job(payload)
