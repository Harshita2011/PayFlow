"""Safe public probes, protected metrics and owner-only asynchronous activity."""
from datetime import datetime
import hmac
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from database import engine, get_db
from models import User
from security import get_current_user
from outbox_models import OutboxEvent, ActivityNotification
from observability import render_metrics
from reliability_config import OPS_TOKEN

router = APIRouter(tags=['Reliability'])


@router.get('/health/live')
def live():
    return {'status':'alive'}


@router.get('/health/ready')
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SET LOCAL statement_timeout='2000ms'"))
        version = db.scalar(text('SELECT version_num FROM alembic_version'))
        if version != '0009_reliability_outbox':
            raise HTTPException(503, 'Service not ready')
        return {'status':'ready'}
    except SQLAlchemyError:
        raise HTTPException(503,'Service not ready') from None
    finally:
        db.rollback()


def operator(x_ops_token: str | None = Header(default=None, max_length=256)):
    if not OPS_TOKEN or not x_ops_token or not hmac.compare_digest(x_ops_token.encode(),OPS_TOKEN.encode()):
        raise HTTPException(404,'Not found')


@router.get('/metrics',dependencies=[Depends(operator)], include_in_schema=False)
def metrics(db: Session = Depends(get_db)):
    # These are shared DB gauges; scrape once per DB to avoid summing duplicates.
    db.execute(text("SET LOCAL statement_timeout='2000ms'"))
    rows = db.execute(select(OutboxEvent.status,func.count()).group_by(OutboxEvent.status)).all()
    lag = db.scalar(select(func.coalesce(func.extract('epoch',func.clock_timestamp()-func.min(OutboxEvent.created_at)),0))
        .where(OutboxEvent.status.in_(['PENDING','PROCESSING'])))
    body = render_metrics()
    for state in ['PENDING','PROCESSING','PROCESSED','DEAD']:
        body += f'payflow_outbox_events{{state="{state}"}} {dict(rows).get(state,0)}\n'
    body += f'payflow_outbox_oldest_seconds {max(0,float(lag))}\n'
    attempts = db.scalar(select(func.coalesce(func.sum(OutboxEvent.attempt_count),0)))
    retries = db.scalar(select(func.coalesce(func.sum(func.greatest(OutboxEvent.attempt_count-1,0)),0)))
    body += f'payflow_outbox_delivery_attempts_total {attempts}\npayflow_outbox_retry_attempts_total {retries}\n'
    deadlocks = db.scalar(text('SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()'))
    connections = db.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()'))
    waiters = db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
    body += f'payflow_db_deadlocks_total {deadlocks}\npayflow_db_connections {connections}\npayflow_db_lock_waiters {waiters}\n'
    pool = engine.pool
    body += f'payflow_db_pool_checked_out {pool.checkedout()}\npayflow_db_pool_size {pool.size()}\n'
    body += f'payflow_db_pool_overflow {max(0,pool.overflow())}\n'
    return Response(body,media_type='text/plain; version=0.0.4',headers={'Cache-Control':'no-store'})


class Notification(BaseModel):
    id: str
    payment_id: str
    created_at: datetime


class Notifications(BaseModel):
    items: list[Notification]
    next_cursor: str | None


@router.get('/activity/notifications',response_model=Notifications)
def notifications(limit: int = Query(10,ge=1,le=50),before: UUID | None=None,
                  user: User=Depends(get_current_user),db: Session=Depends(get_db)):
    query = select(ActivityNotification).where(ActivityNotification.user_id==user.id)
    if before:
        cursor = db.scalar(query.where(ActivityNotification.id==str(before)))
        if cursor is None: raise HTTPException(404,'Activity not found')
        query = query.where(tuple_(ActivityNotification.created_at,ActivityNotification.id)<(cursor.created_at,cursor.id))
    rows = list(db.scalars(query.order_by(ActivityNotification.created_at.desc(),ActivityNotification.id.desc()).limit(limit+1)))
    return Notifications(items=[Notification(id=r.id,payment_id=r.payment_id,created_at=r.created_at) for r in rows[:limit]],
                         next_cursor=rows[limit-1].id if len(rows)>limit else None)
