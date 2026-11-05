"""Operator-only retention preview. --apply affects eligible security rows, never money/history."""
import argparse
from datetime import timedelta
from sqlalchemy import delete, func, select
from database import engine
from security_events import clock
from security_models import SecurityAuditEvent, SecurityRateWindow, PaymentAuthorization, FraudRiskDecision
from security_settings import settings
from sqlalchemy.orm import Session


def retention(db, apply=False):
    now = clock(db)
    cutoff = now - timedelta(days=settings.audit_days)
    candidates = [
        (SecurityAuditEvent, SecurityAuditEvent.created_at < cutoff),
        (FraudRiskDecision, (FraudRiskDecision.created_at < cutoff) & FraudRiskDecision.payment_id.is_(None)),
        (PaymentAuthorization, (PaymentAuthorization.expires_at < cutoff) & PaymentAuthorization.consumed_at.is_(None)),
        (SecurityRateWindow, SecurityRateWindow.window_start < now - timedelta(days=2)),
    ]
    counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(condition)) for model, condition in candidates}
    if apply:
        for model, condition in candidates:
            db.execute(delete(model).where(condition))
        db.commit()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Explicitly prune eligible security records after reviewing the default preview")
    args = parser.parse_args()
    with Session(engine) as db:
        print({"applied": args.apply, "eligible_counts": retention(db, args.apply)})
