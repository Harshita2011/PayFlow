import hashlib
import json
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import get_db
from models import BankAccount, User
from payment_models import LedgerEntry, Payment, PaymentRequest
from payment_schemas import DemoFundingRequest, FundingRequest, SelfTransferRequest, PaymentHistory, PaymentReceipt, RecipientRequest, RecipientResponse, TransferRequest
from security import get_current_user
from social_models import MoneyRequest
from accounts import lock_account_config
from split_service import lock_linked_split, linked_request_is_current, settle_if_paid

router = APIRouter(tags=["Simulated payments"])
FUNDING_AMOUNT = Decimal("1000.00")
FUNDING_LIMIT = 3


def receipt(payment: Payment, viewer_account_id: int) -> PaymentReceipt:
    incoming = payment.recipient_account_id == viewer_account_id and payment.sender_account_id != viewer_account_id
    funding = payment.type == "DEMO_FUNDING"
    self_transfer = payment.type == "SELF_TRANSFER"
    return PaymentReceipt(
        transaction_id=payment.id, type=payment.type, status=payment.status,
        direction="SELF" if self_transfer else "FUNDING" if funding else "INCOMING" if incoming else "OUTGOING",
        amount=payment.amount,
        counterparty_name="Transfer between your accounts" if self_transfer else payment.sender_name if incoming else payment.recipient_name,
        counterparty_upi_id=payment.sender_upi_id if incoming else payment.recipient_upi_id,
        recipient_upi_id=payment.recipient_upi_id, note=payment.note,
        failure_reason=payment.failure_reason, created_at=payment.created_at,
        source_bank=payment.sender_account.bank_name if self_transfer else None,
        source_masked_account="SIM •••• •••• •••• " + payment.sender_account.account_number[-4:] if self_transfer else None,
        destination_bank=payment.recipient_account.bank_name if self_transfer else None,
        destination_masked_account="SIM •••• •••• •••• " + payment.recipient_account.account_number[-4:] if self_transfer else None,
    )


def own_account(db: Session, user_id: int) -> BankAccount:
    account = db.scalar(select(BankAccount).where(BankAccount.user_id == user_id, BankAccount.is_primary.is_(True)))
    if account is None:
        raise HTTPException(status_code=404, detail="Create a simulated bank account first")
    return account


@router.post("/payments/resolve", response_model=RecipientResponse)
def resolve_recipient(payload: RecipientRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    charge_lookup(db, user.id)
    found = db.execute(select(BankAccount, User.full_name).join(User, User.id == BankAccount.user_id).where(BankAccount.upi_id == payload.upi_id)).first()
    if found is None:
        raise HTTPException(status_code=404, detail="Recipient not available")
    account, name = found
    if account.user_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot pay yourself")
    return RecipientResponse(display_name=name, bank_name=account.bank_name, upi_id=account.upi_id)


def charge_lookup(db, user_id, cost=1):
    attempts = db.execute(text("""INSERT INTO recipient_lookup_limits(user_id, window_start, attempts)
        VALUES (:uid, date_trunc('minute', clock_timestamp()), :cost)
        ON CONFLICT (user_id) DO UPDATE SET window_start=EXCLUDED.window_start,
        attempts=CASE WHEN recipient_lookup_limits.window_start=EXCLUDED.window_start
          THEN LEAST(recipient_lookup_limits.attempts+:cost,11) ELSE :cost END RETURNING attempts"""), {"uid": user_id, "cost": cost}).scalar_one()
    # Count misses as well as hits, across API workers. This is not a money-changing request.
    db.commit()
    if attempts > 10:
        raise HTTPException(status_code=429, detail="Too many recipient lookups. Try again next minute", headers={"Retry-After": "60"})


def request_fingerprint(kind: str, payload: FundingRequest | TransferRequest | SelfTransferRequest) -> str:
    data = payload.model_dump(mode="json", exclude_none=True)
    if kind in {"TRANSFER", "SELF_TRANSFER"}:
        data["amount"] = format(payload.amount, ".2f")
    return hashlib.sha256(json.dumps({"type": kind, **data}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def post_ledger(db: Session, payment: Payment):
    debit = "demo-funding" if payment.type == "DEMO_FUNDING" else f"bank-{payment.sender_account_id}"
    db.add_all([
        LedgerEntry(payment_id=payment.id, ledger_account_id=debit, amount=-payment.amount),
        LedgerEntry(payment_id=payment.id, ledger_account_id=f"bank-{payment.recipient_account_id}", amount=payment.amount),
    ])
    db.flush()


def execute_payment(db: Session, user: User, key: str, kind: str, payload: FundingRequest | TransferRequest | SelfTransferRequest, *, money_request_id: str | None = None):
    fingerprint = request_fingerprint(kind, payload)
    if money_request_id:
        fingerprint = hashlib.sha256(f"collect:{money_request_id}:{fingerprint}".encode()).hexdigest()
    user_id = user.id
    try:
        # ON CONFLICT waits for a concurrent request with the same scoped key.
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        reserved = db.scalar(insert(PaymentRequest).values(user_id=user_id, key=key, fingerprint=fingerprint)
            .on_conflict_do_nothing(index_elements=["user_id", "key"]).returning(PaymentRequest.key))
        request = db.scalar(select(PaymentRequest).where(PaymentRequest.user_id == user_id, PaymentRequest.key == key).with_for_update())
        if reserved is None:
            if request.fingerprint != fingerprint:
                db.rollback()
                return JSONResponse(status_code=409, content={"detail": "Idempotency key was already used for a different request"})
            body, status = request.response_body, request.http_status
            db.rollback()
            return JSONResponse(status_code=status, content=body)

        def finish_collect(status, body):
            # Completes the same scoped reservation even for lifecycle conflicts/replays.
            request.http_status, request.response_body = status, body
            db.flush()
            db.commit()
            return JSONResponse(status_code=status, content=body)

        collect = None
        split = None
        if money_request_id:
            split = lock_linked_split(db, money_request_id)
            # Global order: scoped retry key -> collect row -> sorted account rows.
            # Cancel/decline take only this collect row, never an account or retry-key lock.
            collect = db.scalar(select(MoneyRequest).where(MoneyRequest.id == money_request_id,
                MoneyRequest.payer_user_id == user_id).with_for_update().execution_options(populate_existing=True))
            if collect is None:
                return finish_collect(404, {"detail": "Request not found"})
            if collect.status == "PAID":
                original = db.get(Payment, collect.payment_id)
                return finish_collect(201, receipt(original, original.sender_account_id).model_dump(mode="json"))
            if split and (split.status != "OPEN" or not linked_request_is_current(db, money_request_id)):
                return finish_collect(409, {"detail": "This split contribution is no longer payable"})
            now = db.scalar(select(func.clock_timestamp()))
            if collect.status == "PENDING" and collect.expires_at <= now:
                collect.status, collect.updated_at = "EXPIRED", now
            if collect.status != "PENDING":
                return finish_collect(409, {"detail": "Request is no longer pending or has expired"})

        lock_account_config(db, user_id)
        source_id = getattr(payload, "source_account_id", None) or (getattr(payload, "account_id", None) if kind == "DEMO_FUNDING" else None)
        sender = db.scalar(select(BankAccount).where(BankAccount.user_id == user_id,
            BankAccount.id == source_id if source_id is not None else BankAccount.is_primary.is_(True)))
        if sender is None:
            return finish_collect(404, {"detail": "Account not found" if source_id else "Create a simulated bank account first"})
        if kind == "SELF_TRANSFER":
            target = db.scalar(select(BankAccount).where(BankAccount.id == payload.destination_account_id, BankAccount.user_id == user_id))
            if target is None:
                return finish_collect(404, {"detail": "Account not found"})
        else:
            target = sender if kind == "DEMO_FUNDING" else db.scalar(select(BankAccount).where(BankAccount.upi_id == payload.upi_id))
        ids = sorted({sender.id} | ({target.id} if target else set()))
        # Refresh cached ORM state after waiting for locks. Lock order is shared by all payments.
        locked = {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.id.in_(ids))
            .order_by(BankAccount.id).with_for_update().execution_options(populate_existing=True))}
        sender = locked[sender.id]
        target = locked[target.id] if target else None
        amount = FUNDING_AMOUNT if kind == "DEMO_FUNDING" else payload.amount
        if collect:
            now = db.scalar(select(func.clock_timestamp()))
            if collect.expires_at <= now:
                collect.status, collect.updated_at = "EXPIRED", now
                return finish_collect(409, {"detail": "Request has expired"})
            # Terms came from the immutable request, never from the paying client.
            if not target or target.user_id != collect.requester_user_id or amount != collect.amount or payload.note != collect.note:
                return finish_collect(409, {"detail": "Request details do not match"})
        reason, error_status = None, 400
        if kind == "DEMO_FUNDING":
            used = db.scalar(select(func.count()).select_from(Payment).where(
                Payment.actor_user_id == user_id, Payment.type == kind, Payment.status == "SUCCESS"))
            if used >= FUNDING_LIMIT:
                reason, error_status = "Demo funding limit reached (3 actions per user)", 429
        elif target is None:
            reason, error_status = "Recipient not available", 404
        elif kind == "SELF_TRANSFER" and target.id == sender.id:
            reason = "Choose two different accounts"
        elif kind == "TRANSFER" and target.user_id == user_id:
            reason = "You cannot pay yourself"
        elif sender.balance < amount:
            reason = "Insufficient simulated funds"
        if target and target.balance + amount > Decimal("9999999999999999.99"):
            reason = "Recipient balance limit reached"

        payment = Payment(
            actor_user_id=user_id, sender_account_id=sender.id if kind != "DEMO_FUNDING" else None,
            recipient_account_id=target.id if target else None, amount=amount, currency="INR",
            type=kind, status="FAILED" if reason else "SUCCESS",
            sender_upi_id=sender.upi_id if kind != "DEMO_FUNDING" else None,
            recipient_upi_id=target.upi_id if target else payload.upi_id,
            sender_name=user.full_name if kind != "DEMO_FUNDING" else "PayFlow demo funding",
            recipient_name=target.owner.full_name if target else "Unavailable recipient",
            note=payload.note if kind != "DEMO_FUNDING" else "Fictional test funds",
            failure_reason=reason,
        )
        payment.sender_account = sender if kind != "DEMO_FUNDING" else None
        payment.recipient_account = target
        db.add(payment)
        db.flush()
        if not reason:
            if kind != "DEMO_FUNDING":
                sender.balance -= amount
            target.balance += amount
            post_ledger(db, payment)
            if collect:
                posted_at = db.scalar(select(func.clock_timestamp()))
                collect.status, collect.payment_id, collect.updated_at = "PAID", payment.id, posted_at
        if collect and not reason:
            settle_if_paid(db, split)
        public = receipt(payment, sender.id).model_dump(mode="json")
        request.payment_id = payment.id
        request.http_status = error_status if reason else 201
        request.response_body = {"detail": reason, "receipt": public} if reason else public
        db.flush()
        # Check deferred journal/cache invariants before responding, including in test savepoints.
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        db.commit()
        return JSONResponse(status_code=request.http_status, content=request.response_body)
    except Exception:
        # Includes deadlocks, serialization errors, injected failures, and uncertain commit failures.
        db.rollback()
        return JSONResponse(status_code=503, content={"detail": "Payment outcome could not be confirmed. Retry with the same idempotency key"})


@router.post("/demo/fund", response_model=PaymentReceipt, status_code=201)
def fund(payload: DemoFundingRequest, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return execute_payment(db, user, str(idempotency_key), "DEMO_FUNDING", payload)


@router.post("/payments/transfer", response_model=PaymentReceipt, status_code=201)
def transfer(payload: TransferRequest, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return execute_payment(db, user, str(idempotency_key), "TRANSFER", payload)


@router.post("/payments/self-transfer", response_model=PaymentReceipt, status_code=201)
def self_transfer(payload: SelfTransferRequest, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return execute_payment(db, user, str(idempotency_key), "SELF_TRANSFER", payload)


def visible_to(account_ids):
    return or_(Payment.sender_account_id.in_(account_ids),
        Payment.recipient_account_id.in_(account_ids) & ((Payment.status == "SUCCESS") | (Payment.type == "DEMO_FUNDING")))


@router.get("/payments/history", response_model=PaymentHistory)
def history(limit: int = Query(10, ge=1, le=50), before: UUID | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account_ids = list(db.scalars(select(BankAccount.id).where(BankAccount.user_id == user.id)))
    query = select(Payment).where(visible_to(account_ids))
    if before:
        cursor = db.scalar(select(Payment).where(Payment.id == str(before), visible_to(account_ids)))
        if cursor is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        query = query.where(tuple_(Payment.created_at, Payment.id) < (cursor.created_at, cursor.id))
    rows = list(db.scalars(query.order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit + 1)))
    return PaymentHistory(items=[receipt(p, p.recipient_account_id if p.recipient_account_id in account_ids else p.sender_account_id) for p in rows[:limit]], next_cursor=rows[limit-1].id if len(rows) > limit else None)


@router.get("/payments/{transaction_id}", response_model=PaymentReceipt)
def get_receipt(transaction_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account_ids = list(db.scalars(select(BankAccount.id).where(BankAccount.user_id == user.id)))
    payment = db.scalar(select(Payment).where(Payment.id == str(transaction_id), visible_to(account_ids)))
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return receipt(payment, payment.recipient_account_id if payment.recipient_account_id in account_ids else payment.sender_account_id)
