"""Redacted structured logs and process-local, low-cardinality Prometheus telemetry."""
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import threading
import time
from uuid import UUID, uuid4
from config import LOG_LEVEL

correlation_id = ContextVar('correlation_id', default=None)
_lock = threading.Lock()
_http = defaultdict(lambda: [0, 0.0, [0] * 8])
_events = defaultdict(int)
BUCKETS = (.01, .025, .05, .1, .25, .5, 1, 5)
logger = logging.getLogger('payflow')
logger.propagate = False
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(getattr(logging, LOG_LEVEL))


def log(event, **fields):
    allowed = {'request_id','correlation_id','route','method','status','duration_ms','operation','payment_id','event_id','outcome','attempt','error_code'}
    if set(fields) - allowed:
        raise ValueError('Unsafe log field')
    status = fields.get('status',0)
    severity = 'ERROR' if status >= 500 or fields.get('outcome')=='ERROR' else (
        'WARNING' if status >= 400 or fields.get('error_code') or fields.get('outcome') in {'DEAD','BLOCKED','FAILED'} else 'INFO')
    getattr(logger,severity.lower())(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'severity': severity,
        'service': 'payflow', 'event': event, **fields}, separators=(',', ':')))


def count(event, operation='OTHER', outcome='UNKNOWN'):
    # Call sites supply fixed enums, never identifiers or exception text.
    if event not in {'payment','idempotency','transaction_error','worker'}:
        raise ValueError('Unknown metric')
    if operation not in {'TRANSFER','DEMO_FUNDING','SELF_TRANSFER','MOBILE_RECHARGE','BILL_PAYMENT','REQUEST','OTHER'}:
        operation = 'OTHER'
    if outcome not in {'SUCCESS','FAILED','REPLAY','CONFLICT','BLOCKED','ERROR','DELIVERED','RETRY','DEAD','STALE','UNKNOWN'}:
        outcome = 'UNKNOWN'
    with _lock:
        _events[(event,operation,outcome)] += 1


def render_metrics():
    lines = ['# TYPE payflow_http_requests_total counter', '# TYPE payflow_http_duration_seconds histogram']
    with _lock:
        for (route, method, status), (total, duration, buckets) in _http.items():
            labels = f'route={json.dumps(route)},method="{method}",status="{status}"'
            lines += [f'payflow_http_requests_total{{{labels}}} {total}',
                      f'payflow_http_duration_seconds_count{{{labels}}} {total}',
                      f'payflow_http_duration_seconds_sum{{{labels}}} {duration}']
            for bound, value in zip(BUCKETS, buckets):
                lines.append(f'payflow_http_duration_seconds_bucket{{{labels},le="{bound}"}} {value}')
            lines.append(f'payflow_http_duration_seconds_bucket{{{labels},le="+Inf"}} {total}')
        for (event, operation, outcome), value in _events.items():
            lines.append(f'payflow_{event}_total{{operation="{operation}",outcome="{outcome}"}} {value}')
    return '\n'.join(lines) + '\n'


def uuid_header(headers, name):
    try:
        return str(UUID(headers.get(name, '')))
    except (ValueError, TypeError, AttributeError):
        return str(uuid4())


class RequestTelemetry:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin1').lower(): v.decode('latin1') for k,v in scope.get('headers', [])
                   if k.lower() in {b'x-request-id',b'x-correlation-id'}}
        request_id = uuid_header(headers, 'x-request-id')
        correlation = uuid_header(headers, 'x-correlation-id') if 'x-correlation-id' in headers else request_id
        token = correlation_id.set(correlation)
        start, status = time.perf_counter(), 500
        async def wrapped(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message['headers'] = [*message.get('headers', []), (b'x-request-id', request_id.encode()), (b'x-correlation-id',correlation.encode())]
            await send(message)
        try:
            await self.app(scope, receive, wrapped)
        finally:
            duration = time.perf_counter() - start
            route = getattr(scope.get('route'), 'path', 'UNMATCHED')
            method = scope.get('method', 'OTHER')
            if method not in {'GET','POST','PATCH','DELETE','PUT','OPTIONS','HEAD'}: method = 'OTHER'
            with _lock:
                values = _http[(route, method, str(status))]
                values[0] += 1; values[1] += duration
                for i, bound in enumerate(BUCKETS):
                    values[2][i] += duration <= bound
            log('http_request', request_id=request_id, correlation_id=correlation, route=route,
                method=method, status=status, duration_ms=round(duration*1000, 3))
            correlation_id.reset(token)
