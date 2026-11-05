"""PIN lifecycle and one-payment grants. No reset using only an active JWT."""
import hashlib
import secrets
from datetime import timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, HTTPException
from pydantic import ValidationError
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session
from accounts import lock_account_config
from database import get_db
from models import BankAccount, User
from security import get_current_user, password_hasher
from security_events import PolicyError, audit, clock, enforce_rate
from security_models import PinCredential, PaymentAuthorization, PaymentLimitCounter, SecurityAuditEvent
from security_settings import settings
from pin_schemas import PinSetup, PinChange, AuthorizationInput, AuthorizationResponse, SecurityStatus, AuditItem, AuditPage

router = APIRouter(prefix="/security", tags=["Payment security"])


def verify_secret(value, stored):
    try:
        return password_hasher.verify(value, stored)
    except (UnknownHashError, ValueError):
        return False


def checked_credential(db, user_id, pin):
    # All callers hold config lock 709 before touching credential/version state.
    credential = db.scalar(select(PinCredential).where(PinCredential.user_id == user_id).with_for_update())
    if credential is None:
        raise PolicyError(403, "PIN_NOT_CONFIGURED", "Set a payment PIN in Security Settings before paying.")
    now = clock(db)
    if credential.locked_until:
        until = credential.locked_until
        if until.tzinfo is None:
            from datetime import timezone
            until = until.replace(tzinfo=timezone.utc)
        if until > now:
            raise PolicyError(423, "PIN_LOCKED", "Payment PIN is temporarily locked. Try again later.", retry_after=max(1, int((until-now).total_seconds())))
        credential.failed_attempts, credential.locked_until = 0, None
    if not verify_secret(pin, credential.pin_hash):
        credential.failed_attempts += 1
        audit(db, "PIN_VERIFICATION_FAILURE", user_id)
        locked = credential.failed_attempts >= settings.pin_attempts
        if locked:
            credential.locked_until = now + timedelta(seconds=settings.pin_lock_seconds)
            audit(db, "PIN_LOCKED", user_id)
        credential.updated_at = now
        db.commit()  # No financial mutations exist in this PIN-only transaction.
        raise PolicyError(423 if locked else 400, "PIN_LOCKED" if locked else "PIN_INVALID",
            "Payment PIN is temporarily locked. Try again later." if locked else "Incorrect payment PIN.",
            retry_after=settings.pin_lock_seconds if locked else None)
    credential.failed_attempts, credential.locked_until, credential.updated_at = 0, None, now
    return credential


@router.post("/pin", status_code=201)
def setup_pin(payload: PinSetup, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_rate(db, "pin", str(user.id), settings.pin_per_minute, 60, user.id)
    lock_account_config(db, user.id)
    if db.get(PinCredential, user.id) is not None:
        raise PolicyError(409, "PIN_EXISTS", "A PIN already exists. Change it using your current PIN.")
    if not verify_secret(payload.password.get_secret_value(), user.password_hash):
        audit(db, "PIN_SETUP_FAILURE", user.id)
        db.commit()
        raise PolicyError(400, "CREDENTIAL_INVALID", "Account password could not be verified.")
    db.add(PinCredential(user_id=user.id, pin_hash=password_hasher.hash(payload.pin.get_secret_value())))
    audit(db, "PIN_CREATED", user.id, outcome="SUCCESS")
    db.commit()
    return {"message": "Payment PIN configured."}


@router.post("/pin/change")
def change_pin(payload: PinChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_rate(db, "pin", str(user.id), settings.pin_per_minute, 60, user.id)
    lock_account_config(db, user.id)
    credential = checked_credential(db, user.id, payload.current_pin.get_secret_value())
    credential.pin_hash = password_hasher.hash(payload.new_pin.get_secret_value())
    credential.version += 1  # All unconsumed grants issued under the old PIN become invalid.
    audit(db, "PIN_CHANGED", user.id, outcome="SUCCESS")
    db.commit()
    return {"message": "Payment PIN changed. Earlier payment authorizations are invalid."}


def operation_terms(db, user_id, command):
    from payment_schemas import TransferRequest, SelfTransferRequest, RequestPayInput
    from commerce_schemas import RechargeInput, BillPayInput
    from commerce_service import prepare_purchase
    from social_models import MoneyRequest, RequestDestination
    from payments import request_fingerprint
    kind, reference = command.operation, str(command.reference_id) if command.reference_id else None
    if kind not in {"REQUEST", "BILL_PAYMENT"} and reference is not None:
        raise HTTPException(422, "This operation does not accept a reference ID")
    try:
        model = {"TRANSFER": TransferRequest, "SELF_TRANSFER": SelfTransferRequest, "REQUEST": RequestPayInput,
            "MOBILE_RECHARGE": RechargeInput, "BILL_PAYMENT": BillPayInput}[kind]
        payload = model.model_validate(command.payload)
    except ValidationError:
        raise HTTPException(422, "Invalid payment details") from None
    money_request_id, bill_id = None, None
    if kind == "REQUEST":
        item = db.scalar(select(MoneyRequest).where(MoneyRequest.id == reference, MoneyRequest.payer_user_id == user_id))
        if item is None:
            raise HTTPException(404, "Request not found")
        if item.status != "PENDING" or item.expires_at <= clock(db):
            raise HTTPException(409, "Request is no longer payable")
        target = db.scalar(select(BankAccount).join(RequestDestination, RequestDestination.account_id == BankAccount.id).where(RequestDestination.request_id == item.id))
        payload = TransferRequest(upi_id=target.upi_id, amount=format(item.amount, ".2f"), note=item.note, source_account_id=payload.source_account_id)
        kind, money_request_id = "TRANSFER", item.id
    purchase = prepare_purchase(db, user_id, kind, payload, reference) if kind in {"MOBILE_RECHARGE", "BILL_PAYMENT"} else None
    if kind == "BILL_PAYMENT":
        bill_id = reference
        if purchase["bill"].status != "UNPAID":
            raise HTTPException(409, "Bill is already paid. Open its receipt instead.")
    source_id = getattr(payload, "source_account_id", None)
    source = db.scalar(select(BankAccount).where(BankAccount.user_id == user_id,
        BankAccount.id == source_id if source_id else BankAccount.is_primary.is_(True)))
    if source is None:
        raise HTTPException(404, "Account not found")
    if kind == "TRANSFER":
        target = db.scalar(select(BankAccount).where(BankAccount.upi_id == payload.upi_id))
        if target is None:
            raise HTTPException(404, "Recipient not available")
        if target.user_id == user_id:
            raise HTTPException(400, "You cannot pay yourself")
    elif kind == "SELF_TRANSFER":
        target = db.scalar(select(BankAccount).where(BankAccount.id == payload.destination_account_id, BankAccount.user_id == user_id))
        if target is None:
            raise HTTPException(404, "Account not found")
        if target.id == source.id:
            raise HTTPException(400, "Choose two different accounts")
    else:
        target = None
    fingerprint = request_fingerprint(kind, payload)
    if money_request_id:
        fingerprint = hashlib.sha256(f"collect:{money_request_id}:{fingerprint}".encode()).hexdigest()
    if bill_id:
        fingerprint = hashlib.sha256(f"bill:{bill_id}:{fingerprint}".encode()).hexdigest()
    from payment_policy import destination_digest
    amount = purchase["amount"] if purchase else payload.amount
    destination = destination_digest(kind, payload, target, money_request_id=money_request_id, bill_id=bill_id)
    return source.id, amount, fingerprint, destination


@router.post("/payment-authorizations", response_model=AuthorizationResponse, status_code=201)
def payment_authorization(payload: AuthorizationInput, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_rate(db, "pin", str(user.id), settings.pin_per_minute, 60, user.id)
    # Resolve immutable terms first. Bill/catalog locks precede owner configuration locks.
    try:
        source, amount, fingerprint, destination = operation_terms(db, user.id, payload)
    except HTTPException as error:
        if error.status_code == 404 and error.detail == "Account not found":
            audit(db, "UNAUTHORIZED_ACCOUNT_ACCESS", user.id, str(idempotency_key), code="ACCOUNT_UNAVAILABLE")
            db.commit()
        raise
    lock_account_config(db, user.id)
    # Re-resolve the selected source after primary changes could have committed.
    resolved = operation_terms(db, user.id, payload)
    if resolved != (source, amount, fingerprint, destination):
        raise PolicyError(409, "PAYMENT_DETAILS_CHANGED", "Payment details changed. Review the payment again.")
    credential = checked_credential(db, user.id, payload.pin.get_secret_value())
    now = clock(db)
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(seconds=settings.authorization_seconds)
    db.add(PaymentAuthorization(token_digest=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
        source_account_id=source, operation=payload.operation, idempotency_key=str(idempotency_key), fingerprint=fingerprint,
        amount=amount, destination_digest=destination, pin_version=credential.version, created_at=now, expires_at=expires))
    audit(db, "PAYMENT_AUTHORIZED", user.id, str(idempotency_key), "ALLOWED", operation=payload.operation)
    db.commit()
    return AuthorizationResponse(authorization_token=token, expires_at=expires, source_account_id=source, amount=format(amount, ".2f"), operation=payload.operation)


@router.get("/status", response_model=SecurityStatus)
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    credential = db.get(PinCredential, user.id)
    from payment_policy import day_boundary
    from payment_models import Payment
    now = clock(db)
    start = day_boundary(now)
    locked_until = credential.locked_until if credential and credential.locked_until and credential.locked_until > now else None
    attempts = credential.failed_attempts if credential and (not credential.locked_until or locked_until) else 0
    amount, count = db.execute(select(func.coalesce(func.sum(Payment.amount), 0), func.count()).where(Payment.actor_user_id == user.id,
        Payment.status == "SUCCESS", Payment.type != "DEMO_FUNDING", Payment.created_at >= start)).one()
    return SecurityStatus(pin_configured=credential is not None, locked_until=locked_until,
        remaining_attempts=max(0, settings.pin_attempts-attempts),
        single_limit=format(settings.single_amount, ".2f"), daily_limit=format(settings.daily_amount, ".2f"),
        daily_count_limit=settings.daily_count, daily_amount_used=format(amount, ".2f"), daily_count_used=count)


@router.get("/events", response_model=AuditPage)
def events(limit: int = Query(20, ge=1, le=50), before: UUID | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(SecurityAuditEvent).where(SecurityAuditEvent.actor_user_id == user.id,
        SecurityAuditEvent.created_at >= clock(db) - timedelta(days=settings.audit_days))
    if before:
        cursor = db.scalar(select(SecurityAuditEvent).where(SecurityAuditEvent.id == str(before), SecurityAuditEvent.actor_user_id == user.id))
        if cursor is None:
            raise HTTPException(404, "Event not found")
        query = query.where(tuple_(SecurityAuditEvent.created_at, SecurityAuditEvent.id) < (cursor.created_at, cursor.id))
    rows = list(db.scalars(query.order_by(SecurityAuditEvent.created_at.desc(), SecurityAuditEvent.id.desc()).limit(limit+1)))
    return AuditPage(items=[AuditItem(id=r.id, event_type=r.event_type, created_at=r.created_at, operation_id=r.operation_id,
        outcome=r.outcome, details=r.details) for r in rows[:limit]], next_cursor=rows[limit-1].id if len(rows)>limit else None)
