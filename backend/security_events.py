"""Safe, structured DB events. Never accepts arbitrary request bodies or exception strings."""
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from config import JWT_SECRET_KEY
from security_models import SecurityAuditEvent, SecurityRateWindow


class PolicyError(Exception):
    def __init__(self, status, code, message, *, retry_after=None, rules=None):
        self.status, self.code, self.message = status, code, message
        self.retry_after, self.rules = retry_after, rules or []


def clock(db):
    if db.bind.dialect.name == "postgresql":
        return db.scalar(select(func.clock_timestamp()))
    return datetime.now(timezone.utc)


def audit(db, event_type, user_id=None, operation_id=None, outcome="DENIED", **metadata):
    allowed = {"operation", "code", "rules", "bucket", "risk_level"}
    if set(metadata) - allowed:
        raise ValueError("Unsafe audit metadata key")
    db.add(SecurityAuditEvent(event_type=event_type, actor_user_id=user_id, operation_id=operation_id,
        outcome=outcome, details=metadata))


def opaque_subject(bucket, value):
    return hmac.new(JWT_SECRET_KEY.encode(), f"rate:{bucket}:{value}".encode(), hashlib.sha256).hexdigest()


def enforce_rate(db, bucket, subject, limit, seconds, user_id=None, *, commit=True):
    """Default own commit boundary; commit=False joins the payment transaction."""
    now = clock(db)
    start = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, timezone.utc)
    statement = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    attempts = db.scalar(statement(SecurityRateWindow).values(bucket=bucket, subject_digest=opaque_subject(bucket, subject),
        window_start=start, attempts=1).on_conflict_do_update(index_elements=["bucket", "subject_digest", "window_start"],
        set_={"attempts": SecurityRateWindow.attempts + 1}).returning(SecurityRateWindow.attempts))
    retry = max(1, int((start + timedelta(seconds=seconds) - now).total_seconds()) + 1)
    if attempts > limit:
        audit(db, "RATE_LIMIT_EXCEEDED", user_id, bucket=bucket)
    if commit:
        db.commit()
    if attempts > limit:
        raise PolicyError(429, "RATE_LIMIT_EXCEEDED", "Too many attempts. Try again later.", retry_after=retry)
