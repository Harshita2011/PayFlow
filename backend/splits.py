"""Expense records create obligations, never balances or a second payment engine."""
import hashlib
import json
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import exists, func, or_, select, text, tuple_
from sqlalchemy.orm import Session

from accounts import lock_account_config
from database import get_db
from models import BankAccount, User
from payment_schemas import FundingRequest
from payments import charge_lookup, own_account
from request_limits import reserve_capacity
from security import get_current_user
from social_models import Contact, MoneyRequest, RequestDestination
from social_schemas import PublicPerson
from split_models import ExpenseSplit, SplitParticipant, SplitRequestLink
from split_schemas import RequestAttempt, SplitCreate, SplitPage, SplitPersonResponse, SplitResponse

router = APIRouter(prefix="/splits", tags=["Simulated expense splits"])


def visible(user_id):
    return or_(ExpenseSplit.creator_user_id == user_id, exists(select(SplitParticipant.id).where(
        SplitParticipant.split_id == ExpenseSplit.id, SplitParticipant.user_id == user_id)))


def split_query():
    return select(ExpenseSplit, User.full_name, BankAccount.upi_id).join(User, User.id == ExpenseSplit.creator_user_id).join(BankAccount, BankAccount.id == ExpenseSplit.destination_account_id)


def effective_status(request, now):
    return "EXPIRED" if request.status == "PENDING" and request.expires_at <= now else request.status


def load_splits(db, rows, viewer_id):
    ids = [row[0].id for row in rows]
    if not ids:
        return []
    now = db.scalar(select(func.clock_timestamp()))
    people = db.execute(select(SplitParticipant, User.full_name, BankAccount.upi_id, MoneyRequest)
        .join(User, User.id == SplitParticipant.user_id).join(BankAccount, (BankAccount.user_id == User.id) & BankAccount.is_primary.is_(True))
        .outerjoin(MoneyRequest, MoneyRequest.id == SplitParticipant.current_request_id)
        .where(SplitParticipant.split_id.in_(ids)).order_by(SplitParticipant.created_at, SplitParticipant.id)).all()
    history = db.execute(select(SplitRequestLink.participant_id, MoneyRequest).join(MoneyRequest, MoneyRequest.id == SplitRequestLink.request_id)
        .join(SplitParticipant, SplitParticipant.id == SplitRequestLink.participant_id).where(SplitParticipant.split_id.in_(ids)).order_by(MoneyRequest.created_at)).all()
    attempts = {}
    for pid, request in history:
        attempts.setdefault(pid, []).append(RequestAttempt(request_id=request.id, status=effective_status(request, now), payment_id=request.payment_id, created_at=request.created_at))
    result = []
    for split, creator_name, creator_upi in rows:
        participants = []
        creator_share = received = Decimal("0.00")
        for part, name, upi, request in people:
            if part.split_id != split.id:
                continue
            creator = part.user_id == split.creator_user_id
            authorized = viewer_id in {split.creator_user_id, part.user_id}
            status = "CREATOR_SHARE" if creator else effective_status(request, now)
            if creator:
                creator_share += part.share_amount
            elif status == "PAID":
                received += part.share_amount
            participants.append(SplitPersonResponse(id=part.id, person=PublicPerson(display_name=name, upi_id=upi), share_amount=part.share_amount,
                is_creator_share=creator, status=status, request_id=part.current_request_id if authorized else None, payment_id=request.payment_id if request and authorized else None,
                can_pay=not creator and part.user_id == viewer_id and status == "PENDING" and split.status == "OPEN", attempts=attempts.get(part.id, []) if authorized else []))
        result.append(SplitResponse(id=split.id, title=split.title, description=split.description, total_amount=split.total_amount,
            creator_share=creator_share, contributions_received=received, outstanding_amount=split.total_amount-creator_share-received,
            status=split.status, creator=PublicPerson(display_name=creator_name, upi_id=creator_upi), is_creator=split.creator_user_id == viewer_id,
            participant_count=len(participants), participants=participants, created_at=split.created_at, updated_at=split.updated_at))
    return result


def public_split(db, split_id, viewer_id):
    row = db.execute(split_query().where(ExpenseSplit.id == split_id, visible(viewer_id))).first()
    if row is None:
        raise HTTPException(404, "Split not found")
    return load_splits(db, [row], viewer_id)[0]


def split_fingerprint(payload):
    data = payload.model_dump(mode="json", exclude_none=True)
    data["total_amount"] = format(payload.total_amount, ".2f")
    if payload.creator_share is not None:
        data["creator_share"] = format(payload.creator_share, ".2f")
    data["participants"] = sorted([{**item.model_dump(mode="json", exclude_none=True), **({"share_amount": format(item.share_amount, ".2f")} if item.share_amount is not None else {})} for item in payload.participants], key=lambda item: item["upi_id"])
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def new_request(db, split, payer_id, share, now, key=None, fingerprint=None):
    from social import REQUEST_TTL
    request = MoneyRequest(requester_user_id=split.creator_user_id, payer_user_id=payer_id, amount=share,
        note="Split: " + split.title, creation_key=key or str(uuid4()), fingerprint=fingerprint or hashlib.sha256(f"split:{split.id}:{payer_id}".encode()).hexdigest(),
        created_at=now, updated_at=now, expires_at=now + REQUEST_TTL)
    db.add(request)
    db.flush()
    db.add(RequestDestination(request_id=request.id, account_id=split.destination_account_id))
    return request


@router.post("", response_model=SplitResponse, status_code=201)
def create_split(payload: SplitCreate, response: Response, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fingerprint = split_fingerprint(payload)
    def replay():
        old = db.scalar(select(ExpenseSplit).where(ExpenseSplit.creator_user_id == user.id, ExpenseSplit.creation_key == str(idempotency_key)))
        if old:
            if old.fingerprint != fingerprint:
                raise HTTPException(409, "Idempotency key was already used for a different split")
            response.status_code = 200
            return public_split(db, old.id, user.id)
    previous = replay()
    if previous:
        return previous
    ids = [item.upi_id for item in payload.participants]
    if len(ids) != len(set(ids)) or len(ids) + int(payload.include_creator) > 10:
        raise HTTPException(422, "Choose unique participants, at most ten including your share")
    known = set(db.scalars(select(BankAccount.upi_id).join(Contact, Contact.contact_user_id == BankAccount.user_id).where(Contact.owner_user_id == user.id, BankAccount.upi_id.in_(ids))))
    charge_lookup(db, user.id, max(1, len(set(ids)-known)))
    targets = list(db.scalars(select(BankAccount).where(BankAccount.upi_id.in_(ids)).order_by(BankAccount.upi_id)))
    if len(targets) != len(ids):
        raise HTTPException(404, "A split participant is not available")
    payer_ids = [target.user_id for target in targets]
    if user.id in payer_ids or len(payer_ids) != len(set(payer_ids)):
        raise HTTPException(422, "Use the creator toggle for yourself and choose each other person only once")
    n = len(targets) + int(payload.include_creator)
    if payload.mode == "EQUAL":
        if payload.creator_share is not None or any(item.share_amount is not None for item in payload.participants):
            raise HTTPException(422, "Equal shares are calculated by the server")
        paise = int(payload.total_amount * 100)
        if paise < n:
            raise HTTPException(422, "The total must provide at least one paise per participant")
        q, remainder = divmod(paise, n)
        amounts = [Decimal(q + int(index < remainder))/100 for index in range(n)]
    else:
        shares = {item.upi_id: item.share_amount for item in payload.participants}
        if any(value is None for value in shares.values()) or (payload.include_creator and payload.creator_share is None) or (not payload.include_creator and payload.creator_share is not None):
            raise HTTPException(422, "Enter each positive custom share, including the creator when selected")
        amounts = ([payload.creator_share] if payload.include_creator else []) + [shares[target.upi_id] for target in targets]
        if sum(amounts) != payload.total_amount:
            raise HTTPException(422, "Custom shares must add exactly to the expense total")
    db.execute(text("SELECT pg_advisory_xact_lock(711,:uid)"), {"uid": user.id})
    previous = replay()
    if previous:
        return previous
    now = reserve_capacity(db, user.id, payer_ids)
    lock_account_config(db, user.id)
    destination = own_account(db, user.id)
    split = ExpenseSplit(creator_user_id=user.id, destination_account_id=destination.id, title=payload.title, description=payload.description,
        total_amount=payload.total_amount, creation_key=str(idempotency_key), fingerprint=fingerprint, created_at=now, updated_at=now)
    db.add(split)
    db.flush()
    allocation = ([user.id] if payload.include_creator else []) + payer_ids
    for payer_id, amount in zip(allocation, amounts):
        request = None if payer_id == user.id else new_request(db, split, payer_id, amount, now)
        part = SplitParticipant(split_id=split.id, user_id=payer_id, share_amount=amount, current_request_id=request.id if request else None)
        db.add(part)
        db.flush()
        if request:
            db.add(SplitRequestLink(request_id=request.id, participant_id=part.id))
    db.flush()
    result = public_split(db, split.id, user.id)
    db.commit()
    return result


@router.get("", response_model=SplitPage)
def list_splits(scope: Literal["all", "created", "shared", "settled"] = "all", limit: int = Query(20, ge=1, le=50), before: UUID | None = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = split_query().where(visible(user.id))
    if scope == "created":
        query = query.where(ExpenseSplit.creator_user_id == user.id)
    elif scope == "shared":
        query = query.where(ExpenseSplit.creator_user_id != user.id)
    elif scope == "settled":
        query = query.where(ExpenseSplit.status == "SETTLED")
    if before:
        cursor = db.scalar(select(ExpenseSplit).where(ExpenseSplit.id == str(before), visible(user.id)))
        if cursor is None:
            raise HTTPException(404, "Split not found")
        query = query.where(tuple_(ExpenseSplit.created_at, ExpenseSplit.id) < (cursor.created_at, cursor.id))
    rows = db.execute(query.order_by(ExpenseSplit.created_at.desc(), ExpenseSplit.id.desc()).limit(limit+1)).all()
    return SplitPage(items=load_splits(db, rows[:limit], user.id), next_cursor=rows[limit-1][0].id if len(rows)>limit else None)


@router.get("/{split_id}", response_model=SplitResponse)
def get_split(split_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return public_split(db, str(split_id), user.id)


@router.get("/{split_id}/participants")
def get_participants(split_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return public_split(db, str(split_id), user.id).participants


@router.post("/{split_id}/cancel", response_model=SplitResponse)
def cancel_split(split_id: UUID, payload: FundingRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(text("SET LOCAL lock_timeout='5s'"))
    split = db.scalar(select(ExpenseSplit).where(ExpenseSplit.id == str(split_id), ExpenseSplit.creator_user_id == user.id).with_for_update())
    if split is None:
        raise HTTPException(404, "Split not found")
    if split.status == "CANCELLED":
        return public_split(db, split.id, user.id)
    requests = list(db.scalars(select(MoneyRequest).join(SplitParticipant, SplitParticipant.current_request_id == MoneyRequest.id).where(SplitParticipant.split_id == split.id).order_by(MoneyRequest.id).with_for_update(of=MoneyRequest)))
    if split.status != "OPEN" or any(request.status == "PAID" for request in requests):
        raise HTTPException(409, "A split with paid contributions cannot be cancelled; no refunds are automatic")
    now = db.scalar(select(func.clock_timestamp()))
    for request in requests:
        if request.status == "PENDING":
            request.status, request.updated_at = ("EXPIRED" if request.expires_at <= now else "CANCELLED"), now
    split.status, split.updated_at = "CANCELLED", now
    db.flush()
    result = public_split(db, split.id, user.id)
    db.commit()
    return result


@router.post("/{split_id}/participants/{participant_id}/renew", response_model=SplitResponse)
def renew_request(split_id: UUID, participant_id: UUID, payload: FundingRequest, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    split = db.scalar(select(ExpenseSplit).where(ExpenseSplit.id == str(split_id), ExpenseSplit.creator_user_id == user.id).with_for_update())
    if split is None:
        raise HTTPException(404, "Split not found")
    part = db.scalar(select(SplitParticipant).where(SplitParticipant.id == str(participant_id), SplitParticipant.split_id == split.id))
    if part is None or part.current_request_id is None:
        raise HTTPException(404, "Contribution not found")
    fingerprint = hashlib.sha256(f"renew:{split.id}:{part.id}".encode()).hexdigest()
    previous = db.scalar(select(MoneyRequest).where(MoneyRequest.requester_user_id == user.id, MoneyRequest.creation_key == str(idempotency_key)))
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for a different request")
        return public_split(db, split.id, user.id)
    old = db.scalar(select(MoneyRequest).where(MoneyRequest.id == part.current_request_id).with_for_update())
    now = db.scalar(select(func.clock_timestamp()))
    if split.status != "OPEN" or effective_status(old, now) in {"PENDING", "PAID"}:
        raise HTTPException(409, "Only a closed unpaid request on an open split can be renewed")
    now = reserve_capacity(db, user.id, [part.user_id])
    if old.status == "PENDING":
        old.status, old.updated_at = "EXPIRED", now
        db.flush()
    request = new_request(db, split, part.user_id, part.share_amount, now, str(idempotency_key), fingerprint)
    part.current_request_id = request.id
    db.add(SplitRequestLink(request_id=request.id, participant_id=part.id))
    db.flush()
    result = public_split(db, split.id, user.id)
    db.commit()
    return result
