"""Bounded, non-PII request telemetry and authenticated operational status."""
import json
import logging
from collections import defaultdict
from threading import Lock
import os
import time
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .auth import require
from .ledger import db
from .security import decrypt, production

router = APIRouter(prefix='/api', tags=['Operations'])
logger = logging.getLogger('carbon.requests')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False
_lock = Lock()
_metrics = defaultdict(lambda: {'requests': 0, 'errors': 0, 'total_ms': 0, 'max_ms': 0})
_started = time.monotonic()


async def observe(request: Request, call_next):
    started = time.perf_counter()
    request_id = uuid.uuid4().hex
    status = 500
    try:
        length = request.headers.get('content-length')
        if length and (not length.isdecimal() or int(length) > 55 * 1024 * 1024):
            response = JSONResponse({'detail': 'Request body exceeds 55 MB'}, status_code=413)
        else:
            response = await call_next(request)
        status = response.status_code
        response.headers['X-Request-ID'] = request_id
        return response
    finally:
        route = getattr(request.scope.get('route'), 'path', None)
        route = route if route and route.startswith('/api/') else 'static-or-unmatched'
        duration = round((time.perf_counter() - started) * 1000, 2)
        method = request.method if request.method in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'} else 'OTHER'
        # Path templates only. Never log queries, cookies, bodies, usernames or evidence names.
        with _lock:
            metric = _metrics[(method, route)]
            metric['requests'] += 1
            metric['errors'] += status >= 500
            metric['total_ms'] += duration
            metric['max_ms'] = max(metric['max_ms'], duration)
        logger.info(json.dumps({'request_id': request_id, 'method': method,
                                'route': route, 'status': status, 'duration_ms': duration}))


@router.get('/ready')
def ready():
    try:
        with db._conn() as conn:
            conn.execute('SELECT 1').fetchone()
            row = conn.execute('SELECT body FROM revisions ORDER BY created_at DESC LIMIT 1').fetchone()
            if row:
                json.loads(decrypt(row[0]))
        return {'ready': True}
    except Exception:
        return JSONResponse({'ready': False}, status_code=503)


@router.get('/operations')
def status(request: Request):
    require(request, 'admin')
    with _lock:
        requests = [{'method': method, 'route': route, **values,
                     'average_ms': round(values['total_ms'] / values['requests'], 2)}
                    for (method, route), values in _metrics.items()]
    return {'deployment': 'production' if production() else 'local',
            'uptime_seconds': round(time.monotonic() - _started),
            'telemetry_scope': 'Current process since startup; not aggregated across workers',
            'requests': requests, 'email_delivery': 'disabled; approval-gated drafts only',
            'legal_filing': 'not enabled', 'sso_mfa': 'not configured',
            'backup_key_configured': bool(os.getenv('BACKUP_ENCRYPTION_KEY') or os.getenv('BACKUP_ENCRYPTION_KEY_FILE'))}
