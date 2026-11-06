"""Separate PostgreSQL worker. Run python -m outbox_worker; Ctrl+C drains the current item."""
import argparse
import signal
import threading
from sqlalchemy import select
from sqlalchemy.orm import Session
from database import engine as default_engine
from outbox import claim, deliver, acknowledge, fail
from outbox_models import OutboxEvent
from observability import log
from reliability_config import OUTBOX_POLL
from worker_health import heartbeat


def run(engine, stop, *, once=False):
    while not stop.is_set():
        try:
            with Session(engine,expire_on_commit=False) as db:
                claims = claim(db)
            for event_id, lease in claims:
                if stop.is_set(): break  # Other leases safely expire and can be reclaimed.
                with Session(engine,expire_on_commit=False) as db:
                    try:
                        if deliver(db,event_id,lease): acknowledge(db,event_id,lease)
                    except ValueError:
                        fail(db,event_id,lease,permanent=True)
                    except Exception:
                        fail(db,event_id,lease)
            heartbeat()
        except Exception:
            # Never log exception bodies/DSNs. Unacknowledged leases recover automatically.
            log('worker_unavailable',outcome='ERROR',error_code='DATABASE_OR_DELIVERY_UNAVAILABLE')
        if once: break
        stop.wait(OUTBOX_POLL)
    log('worker_stopped',outcome='SUCCESS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--inspect-dead',action='store_true',help='Read-only bounded dead-letter inspection (no payloads)')
    args = parser.parse_args()
    stop = threading.Event()
    for name in ('SIGINT','SIGTERM'):
        if hasattr(signal,name): signal.signal(getattr(signal,name), lambda *_: stop.set())
    try:
        if args.inspect_dead:
            with Session(default_engine) as db:
                for row in db.execute(select(OutboxEvent.event_id,OutboxEvent.attempt_count,OutboxEvent.last_error)
                    .where(OutboxEvent.status=='DEAD').order_by(OutboxEvent.created_at).limit(100)):
                    print(dict(row._mapping))
        else:
            run(default_engine,stop,once=args.once)
    finally:
        default_engine.dispose()
