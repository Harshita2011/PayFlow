"""Central authorization/limits/risk checks inside the existing payment transaction."""
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from models import BankAccount
from payment_models import Payment
from security_events import PolicyError, audit, clock
from security_models import PaymentAuthorization, PinCredential, PaymentLimitCounter, FraudRiskDecision, SecurityAuditEvent
from security_settings import settings
from social_models import Contact


def destination_digest(kind, payload, target, *, money_request_id=None, bill_id=None):
    identity = bill_id or money_request_id or (f"{payload.plan_id}:{payload.mobile}" if kind == "MOBILE_RECHARGE" else str(target.id))
    return hashlib.sha256(f"{kind}:{identity}".encode()).hexdigest()


def day_boundary(now):
    return datetime.combine(now.astimezone(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc)


def daily_usage(db, user_id, now):
    # Caller holds the same owner-config lock as all payments and primary changes.
    start = day_boundary(now)
    existing = db.scalar(select(PaymentLimitCounter).where(PaymentLimitCounter.user_id == user_id,
        PaymentLimitCounter.utc_day == start.date()).with_for_update())
    if existing is not None:
        return existing
    amount, count = db.execute(select(func.coalesce(func.sum(Payment.amount), 0), func.count()).where(
        Payment.actor_user_id == user_id, Payment.status == "SUCCESS", Payment.type != "DEMO_FUNDING", Payment.created_at >= start)).one()
    db.execute(insert(PaymentLimitCounter).values(user_id=user_id, utc_day=start.date(), amount=amount,
        transaction_count=count).on_conflict_do_nothing(index_elements=["user_id", "utc_day"]))
    return db.scalar(select(PaymentLimitCounter).where(PaymentLimitCounter.user_id == user_id,
        PaymentLimitCounter.utc_day == start.date()).with_for_update())


def assess_risk(db, user_id, kind, amount, target, now):
    recent = (Payment.actor_user_id == user_id, Payment.type != "DEMO_FUNDING", Payment.created_at >= now - timedelta(minutes=10))
    velocity, destinations, repeated, services = db.execute(select(
        func.count().filter(Payment.created_at >= now-timedelta(minutes=1)),
        func.count(func.distinct(Payment.recipient_account_id)).filter(Payment.type=='TRANSFER'),
        func.count().filter(Payment.recipient_account_id==(target.id if target else -1)),
        func.count().filter(Payment.type.in_(['MOBILE_RECHARGE','BILL_PAYMENT']))
    ).where(*recent,Payment.status=='SUCCESS')).one()
    rules, high = [], False
    if velocity >= settings.risk_velocity:
        rules.append("PAYMENT_VELOCITY"); high = True
    if amount >= settings.risk_large:
        rules.append("LARGE_PAYMENT"); high = True
    elif amount >= settings.risk_medium:
        rules.append("ELEVATED_AMOUNT")
    if kind == "TRANSFER" and target and repeated == 0 and destinations >= settings.risk_distinct:
        rules.append("MANY_RECIPIENTS"); high = True
    insufficient = db.scalar(select(func.count()).select_from(Payment).where(*recent, Payment.failure_reason == "Insufficient simulated funds"))
    if insufficient >= settings.risk_insufficient:
        rules.append("REPEATED_INSUFFICIENT_FUNDS"); high = True
    if kind in {"MOBILE_RECHARGE", "BILL_PAYMENT"} and services >= settings.risk_services:
        rules.append("SERVICE_VELOCITY"); high = True
    pin_failures = db.scalar(select(func.count()).select_from(SecurityAuditEvent).where(SecurityAuditEvent.actor_user_id == user_id,
        SecurityAuditEvent.event_type == "PIN_VERIFICATION_FAILURE", SecurityAuditEvent.created_at >= now - timedelta(minutes=10)))
    if pin_failures >= 3:
        rules.append("RECENT_PIN_FAILURES")
    if kind == "TRANSFER" and target:
        fresh = db.scalar(select(Contact.id).where(Contact.owner_user_id == user_id, Contact.contact_user_id == target.user_id,
            Contact.created_at >= now - timedelta(days=1)))
        if fresh and repeated >= settings.risk_new_contact:
            rules.append("REPEATED_NEW_CONTACT_PAYMENTS")
    return "HIGH" if high else "MEDIUM" if rules else "LOW", rules


def authorize_posting(db, user_id, key, fingerprint, kind, payload, sender, target, amount, raw_token, *, money_request_id=None, bill_id=None):
    now = clock(db)
    # Explicit central exemption: funding is a controlled fictional issuer action,
    # governed by the unchanged lifetime allowance and shared submission throttle.
    if kind == "DEMO_FUNDING":
        return None, None, "LOW", [], now
    digest = hashlib.sha256((raw_token or "").encode()).hexdigest()
    grant = db.scalar(select(PaymentAuthorization).where(PaymentAuthorization.token_digest == digest,
        PaymentAuthorization.user_id == user_id).with_for_update()) if raw_token and len(raw_token) <= 128 else None
    credential = db.get(PinCredential, user_id)
    if credential is None:
        raise PolicyError(403, "PIN_NOT_CONFIGURED", "Set a payment PIN in Security Settings before paying.")
    if grant is None:
        raise PolicyError(403, "PAYMENT_AUTHORIZATION_REQUIRED", "Confirm this payment with your payment PIN.")
    if grant.expires_at <= now:
        raise PolicyError(403, "AUTHORIZATION_EXPIRED", "Payment authorization expired. Confirm your PIN again.")
    expected_operation = "REQUEST" if money_request_id else kind
    destination = destination_digest(kind, payload, target, money_request_id=money_request_id, bill_id=bill_id)
    if (grant.consumed_at is not None or grant.idempotency_key != key or grant.fingerprint != fingerprint or
        grant.source_account_id != sender.id or grant.operation != expected_operation or grant.amount != amount or
        grant.destination_digest != destination or grant.pin_version != credential.version):
        raise PolicyError(403, "AUTHORIZATION_MISMATCH", "Payment authorization does not match this payment. Verify your PIN again.")
    if credential.locked_until and credential.locked_until > now:
        raise PolicyError(423, "PIN_LOCKED", "Payment PIN is temporarily locked. Try again after the lockout interval.", retry_after=max(1, int((credential.locked_until-now).total_seconds())))
    usage = daily_usage(db, user_id, now)
    if amount > settings.single_amount or usage.amount + amount > settings.daily_amount or usage.transaction_count >= settings.daily_count:
        raise PolicyError(403, "LIMIT_EXCEEDED", "Payment limit exceeded. Daily limits reset at 00:00 UTC.")
    level, rules = assess_risk(db, user_id, kind, amount, target, now)
    if level == "HIGH":
        raise PolicyError(403, "RISK_BLOCKED", "Payment blocked by a demo security rule: " + ", ".join(rules) + ". Try again after the activity window or review the amount.", rules=rules)
    return grant, usage, level, rules, now


def record_decision(db, user_id, key, operation, level, rules, payment_id=None, blocked=False):
    db.add(FraudRiskDecision(user_id=user_id, operation_id=key, operation=operation, payment_id=payment_id,
        risk_level=level, decision="BLOCK" if blocked else "ALLOW", rules=rules))
    if rules:
        audit(db, "RISK_RULE_TRIGGERED", user_id, key, "DENIED" if blocked else "ALLOWED", operation=operation, rules=rules, risk_level=level)


def record_denial(db, user_id, key, kind, error, *, charge_submission=False):
    # The financial transaction was rolled back. Persist only the security outcome.
    if charge_submission:
        from security_events import enforce_rate
        from security_settings import settings as current_settings
        try:
            enforce_rate(db, "payment-submit", str(user_id), current_settings.submit_per_minute, 60, user_id, commit=False)
        except PolicyError:
            pass  # Persists the rate-denial event and counter with the security-only outcome.
    audit(db, "PAYMENT_BLOCKED", user_id, key, code=error.code, operation=kind)
    if error.rules:
        record_decision(db, user_id, key, kind, "HIGH", error.rules, blocked=True)
    db.commit()
