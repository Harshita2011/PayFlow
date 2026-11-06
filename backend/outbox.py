"""At-least-once side effects; no financial writes. Stable IDs deduplicate delivery."""
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import load_only, raiseload
from models import BankAccount
from payment_models import Payment
from outbox_models import OutboxEvent, ActivityNotification
from observability import correlation_id, count, log
from security_events import clock
from reliability_config import OUTBOX_BATCH, OUTBOX_LEASE, OUTBOX_ATTEMPTS


def enqueue_payment(db, payment):
    db.add(OutboxEvent(payment_id=payment.id, payload={'version':1, 'payment_id':payment.id},
                       correlation_id=correlation_id.get()))


def claim(db, *, batch=OUTBOX_BATCH, lease_seconds=OUTBOX_LEASE, max_attempts=OUTBOX_ATTEMPTS):
    if not 1 <= batch <= 100 or not 1 <= lease_seconds <= 600:
        raise ValueError('Unsafe claim bounds')
    now = clock(db)
    eligible = ((OutboxEvent.status == 'PENDING') & (OutboxEvent.available_at <= now)) | (
        (OutboxEvent.status == 'PROCESSING') & (OutboxEvent.locked_until <= now))
    rows = list(db.scalars(select(OutboxEvent).where(eligible).order_by(OutboxEvent.available_at,OutboxEvent.created_at,OutboxEvent.event_id)
                          .limit(batch).with_for_update(skip_locked=True)))
    claims = []
    for event in rows:
        if event.attempt_count >= max_attempts:
            event.status, event.last_error = 'DEAD', 'ATTEMPTS_EXHAUSTED'
            event.lease_token = event.locked_until = None
            count('worker', outcome='DEAD')
        else:
            event.status, event.lease_token = 'PROCESSING', str(uuid4())
            event.locked_until = now + timedelta(seconds=lease_seconds)
            event.attempt_count += 1
            claims.append((event.event_id, event.lease_token))
    db.commit()  # Release claims before doing any delivery work.
    return claims


def locked_claim(db, event_id, lease):
    event = db.scalar(select(OutboxEvent).where(OutboxEvent.event_id==event_id, OutboxEvent.status=='PROCESSING',
        OutboxEvent.lease_token==lease).with_for_update().execution_options(populate_existing=True))
    # A waiter may acquire the lock after its lease has expired. Sample time only
    # after acquiring the row, rather than trusting a predicate evaluated before waiting.
    return event if event is not None and event.locked_until > clock(db) else None


def deliver(db, event_id, lease):
    event = locked_claim(db, event_id, lease)
    if event is None:
        db.rollback(); return False
    if event.event_type != 'payment.posted.v1' or event.payload != {'version':1,'payment_id':event.payment_id}:
        raise ValueError('UNSUPPORTED_EVENT')
    payment = db.scalar(select(Payment).where(Payment.id==event.payment_id).options(
        raiseload('*'), load_only(Payment.id, Payment.status, Payment.actor_user_id, Payment.recipient_account_id)))
    if payment is None or payment.status != 'SUCCESS':
        raise ValueError('INVALID_PAYMENT_EVENT')
    recipients = {payment.actor_user_id}
    if payment.recipient_account_id:
        recipients.add(db.scalar(select(BankAccount.user_id).where(BankAccount.id==payment.recipient_account_id)))
    for user_id in sorted(recipients):
        db.execute(insert(ActivityNotification).values(id=str(uuid4()),event_id=event.event_id,
            user_id=user_id,payment_id=payment.id).on_conflict_do_nothing(index_elements=['event_id','user_id']))
    db.commit()  # A crash here causes redelivery; the consumer uniqueness constraint deduplicates.
    log('outbox_delivery', event_id=event.event_id, payment_id=event.payment_id,
        correlation_id=event.correlation_id, outcome='DELIVERED', attempt=event.attempt_count)
    return True


def acknowledge(db, event_id, lease):
    event = locked_claim(db,event_id,lease)
    if event is None:
        db.rollback(); count('worker',outcome='STALE'); return False
    event.status, event.processed_at = 'PROCESSED', clock(db)
    event.lease_token = event.locked_until = event.last_error = None
    db.commit()
    count('worker',outcome='DELIVERED')
    return True


def fail(db,event_id,lease, *, permanent=False, max_attempts=OUTBOX_ATTEMPTS):
    db.rollback()
    event = locked_claim(db,event_id,lease)
    if event is None:
        db.rollback(); return
    available_at = clock(db) + timedelta(seconds=min(300,2 ** event.attempt_count))
    event.status = 'DEAD' if permanent or event.attempt_count >= max_attempts else 'PENDING'
    event.last_error = 'INVALID_EVENT' if permanent else 'DELIVERY_UNAVAILABLE'
    event.available_at = available_at
    event.lease_token = event.locked_until = None
    db.commit()
    count('worker',outcome='DEAD' if event.status=='DEAD' else 'RETRY')
    log('outbox_failure',event_id=event.event_id,correlation_id=event.correlation_id,
        outcome=event.status, error_code=event.last_error)
