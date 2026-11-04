"""Owner-scoped address books and collect-request lifecycle. No balance writes here."""
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import case, func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from database import get_db
from models import BankAccount, User
from payment_models import Payment
from payment_schemas import FundingRequest, PaymentReceipt, RequestPayInput, TransferRequest
from payments import execute_payment, own_account, request_fingerprint, resolve_recipient
from security import get_current_user
from social_models import Contact, MoneyRequest, RequestDestination
from request_limits import reserve_capacity
from accounts import lock_account_config
from split_service import lock_linked_split
from social_schemas import ContactCreate, ContactResponse, FavoriteUpdate, MoneyRequestCreate, MoneyRequestPage, MoneyRequestResponse, PublicPerson, RecentContact

router = APIRouter(tags=["Contacts and money requests"])
REQUEST_TTL = timedelta(days=7)


def contact_query(owner_id):
    return select(Contact, User.full_name, BankAccount.upi_id).join(User, User.id == Contact.contact_user_id).join(
        BankAccount, BankAccount.user_id == User.id).where(Contact.owner_user_id == owner_id, BankAccount.is_primary.is_(True))


def contact_output(row):
    item, name, upi = row
    return ContactResponse(id=item.id, display_name=name, upi_id=upi, is_favorite=item.is_favorite,
        created_at=item.created_at, updated_at=item.updated_at)


@router.post("/contacts", response_model=ContactResponse, status_code=201)
def add_contact(payload: ContactCreate, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    resolve_recipient(payload, user, db)  # Existing exact lookup, self protection and DB-backed rate limit.
    target = db.scalar(select(BankAccount).where(BankAccount.upi_id == payload.upi_id))
    db.execute(text("SELECT pg_advisory_xact_lock(708, :uid)"), {"uid": user.id})
    existing = db.scalar(select(Contact).where(Contact.owner_user_id == user.id, Contact.contact_user_id == target.user_id))
    if existing:
        response.status_code = 200
        return contact_output(db.execute(contact_query(user.id).where(Contact.id == existing.id)).one())
    if db.scalar(select(func.count()).select_from(Contact).where(Contact.owner_user_id == user.id)) >= 200:
        raise HTTPException(429, "Saved contact limit reached (200)")
    item = Contact(owner_user_id=user.id, contact_user_id=target.user_id)
    db.add(item)
    db.flush()
    result = contact_output(db.execute(contact_query(user.id).where(Contact.id == item.id)).one())
    db.commit()
    return result


@router.get("/contacts", response_model=list[ContactResponse])
def contacts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [contact_output(row) for row in db.execute(contact_query(user.id).order_by(Contact.is_favorite.desc(), User.full_name, Contact.id).limit(200))]


@router.delete("/contacts/{contact_id}", status_code=204)
def remove_contact(contact_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(Contact).where(Contact.id == str(contact_id), Contact.owner_user_id == user.id).with_for_update())
    if item is None:
        raise HTTPException(404, "Contact not found")
    db.delete(item)  # Explicit removal from this user's personal address book only.
    db.commit()
    return Response(status_code=204)


@router.patch("/contacts/{contact_id}/favorite", response_model=ContactResponse)
def favorite(contact_id: UUID, payload: FavoriteUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(Contact).where(Contact.id == str(contact_id), Contact.owner_user_id == user.id).with_for_update())
    if item is None:
        raise HTTPException(404, "Contact not found")
    item.is_favorite = payload.is_favorite
    item.updated_at = db.scalar(select(func.clock_timestamp()))
    db.flush()
    result = contact_output(db.execute(contact_query(user.id).where(Contact.id == item.id)).one())
    db.commit()
    return result


@router.get("/contacts/recent", response_model=list[RecentContact])
def recent_contacts(limit: int = Query(10, ge=1, le=20), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    own_account(db, user.id)
    own_ids = select(BankAccount.id).where(BankAccount.user_id == user.id)
    other_id = case((Payment.sender_account_id.in_(own_ids), Payment.recipient_account_id), else_=Payment.sender_account_id)
    other = aliased(BankAccount)
    activity = select(other.user_id.label("user_id"), func.max(Payment.created_at).label("latest")).join_from(
        Payment, other, other.id == other_id).where(Payment.type == "TRANSFER", Payment.status == "SUCCESS",
        or_(Payment.sender_account_id.in_(own_ids), Payment.recipient_account_id.in_(own_ids)), other.user_id != user.id
    ).group_by(other.user_id).subquery()
    rows = db.execute(select(User.full_name, BankAccount.upi_id, activity.c.latest).join_from(
        activity, User, User.id == activity.c.user_id).join(BankAccount, BankAccount.user_id == User.id)
        .where(BankAccount.is_primary.is_(True)).order_by(activity.c.latest.desc(), BankAccount.upi_id).limit(limit))
    return [RecentContact(display_name=name, upi_id=upi, last_interacted_at=latest) for name, upi, latest in rows]



def participant(user_id):
    return or_(MoneyRequest.requester_user_id == user_id, MoneyRequest.payer_user_id == user_id)


def request_query():
    requester, payer = aliased(User), aliased(User)
    requester_account, payer_account = aliased(BankAccount), aliased(BankAccount)
    return select(MoneyRequest, requester.full_name, requester_account.upi_id, payer.full_name, payer_account.upi_id).join(
        requester, requester.id == MoneyRequest.requester_user_id).join(RequestDestination, RequestDestination.request_id == MoneyRequest.id).join(requester_account, requester_account.id == RequestDestination.account_id).join(
        payer, payer.id == MoneyRequest.payer_user_id).join(payer_account, (payer_account.user_id == payer.id) & payer_account.is_primary.is_(True))


def request_output(row, now):
    item, requester_name, requester_upi, payer_name, payer_upi = row
    status = "EXPIRED" if item.status == "PENDING" and item.expires_at <= now else item.status
    return MoneyRequestResponse(id=item.id, requester=PublicPerson(display_name=requester_name, upi_id=requester_upi),
        payer=PublicPerson(display_name=payer_name, upi_id=payer_upi), amount=item.amount, note=item.note,
        status=status, payment_id=item.payment_id, created_at=item.created_at, updated_at=item.updated_at, expires_at=item.expires_at)


def public_request(db, request_id):
    return request_output(db.execute(request_query().where(MoneyRequest.id == request_id)).one(), db.scalar(select(func.clock_timestamp())))


@router.post("/payment-requests", response_model=MoneyRequestResponse, status_code=201)
def create_request(payload: MoneyRequestCreate, response: Response, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fingerprint = request_fingerprint("TRANSFER", payload)
    existing = db.scalar(select(MoneyRequest).where(MoneyRequest.requester_user_id == user.id, MoneyRequest.creation_key == str(idempotency_key)))
    if existing:
        if existing.fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for a different request")
        response.status_code = 200
        return public_request(db, existing.id)
    own_account(db, user.id)
    resolve_recipient(payload, user, db)
    target = db.scalar(select(BankAccount).where(BankAccount.upi_id == payload.upi_id))
    # Only creation takes these sorted advisory locks. Payments never acquire them.
    # They serialize owner/payer spam-cap checks without modifying existing users.
    for uid in sorted({user.id, target.user_id}):
        db.execute(text("SELECT pg_advisory_xact_lock(707, :uid)"), {"uid": uid})
    existing = db.scalar(select(MoneyRequest).where(MoneyRequest.requester_user_id == user.id, MoneyRequest.creation_key == str(idempotency_key)))
    if existing:
        if existing.fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for a different request")
        response.status_code = 200
        return public_request(db, existing.id)
    now = reserve_capacity(db, user.id, [target.user_id])
    lock_account_config(db, user.id)
    destination = own_account(db, user.id)
    item = MoneyRequest(requester_user_id=user.id, payer_user_id=target.user_id, amount=payload.amount,
        note=payload.note, creation_key=str(idempotency_key), fingerprint=fingerprint, created_at=now, updated_at=now, expires_at=now + REQUEST_TTL)
    db.add(item)
    db.flush()
    db.add(RequestDestination(request_id=item.id, account_id=destination.id))
    db.flush()
    result = public_request(db, item.id)
    db.commit()
    return result


def request_page(db, user_id, direction, limit, before):
    own_filter = MoneyRequest.payer_user_id == user_id if direction == "incoming" else MoneyRequest.requester_user_id == user_id
    query = request_query().where(own_filter)
    if before:
        cursor = db.scalar(select(MoneyRequest).where(MoneyRequest.id == str(before), own_filter))
        if cursor is None:
            raise HTTPException(404, "Request not found")
        query = query.where(tuple_(MoneyRequest.created_at, MoneyRequest.id) < (cursor.created_at, cursor.id))
    now = db.scalar(select(func.clock_timestamp()))
    rows = db.execute(query.order_by(MoneyRequest.created_at.desc(), MoneyRequest.id.desc()).limit(limit + 1)).all()
    count = db.scalar(select(func.count()).select_from(MoneyRequest).where(own_filter, MoneyRequest.status == "PENDING", MoneyRequest.expires_at > now))
    return MoneyRequestPage(items=[request_output(row, now) for row in rows[:limit]],
        next_cursor=rows[limit-1][0].id if len(rows) > limit else None, pending_count=count)


@router.get("/payment-requests/incoming", response_model=MoneyRequestPage)
def incoming(limit: int = Query(20, ge=1, le=50), before: UUID | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return request_page(db, user.id, "incoming", limit, before)


@router.get("/payment-requests/outgoing", response_model=MoneyRequestPage)
def outgoing(limit: int = Query(20, ge=1, le=50), before: UUID | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return request_page(db, user.id, "outgoing", limit, before)


@router.get("/payment-requests/{request_id}", response_model=MoneyRequestResponse)
def get_request(request_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(MoneyRequest.id).where(MoneyRequest.id == str(request_id), participant(user.id))) is None:
        raise HTTPException(404, "Request not found")
    return public_request(db, str(request_id))


def close_request(db, request_id, user_id, status):
    owner = MoneyRequest.payer_user_id if status == "DECLINED" else MoneyRequest.requester_user_id
    db.execute(text("SET LOCAL lock_timeout='5s'"))
    lock_linked_split(db, str(request_id))
    item = db.scalar(select(MoneyRequest).where(MoneyRequest.id == str(request_id), owner == user_id).with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(404, "Request not found")
    if item.status == status:
        return public_request(db, item.id)  # Repeated same action is safe.
    if item.status != "PENDING":
        raise HTTPException(409, "Request is no longer pending")
    now = db.scalar(select(func.clock_timestamp()))
    item.status = "EXPIRED" if item.expires_at <= now else status
    item.updated_at = now
    db.flush()
    result = public_request(db, item.id)
    db.commit()
    return result


@router.post("/payment-requests/{request_id}/decline", response_model=MoneyRequestResponse)
def decline(request_id: UUID, payload: FundingRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return close_request(db, request_id, user.id, "DECLINED")


@router.post("/payment-requests/{request_id}/cancel", response_model=MoneyRequestResponse)
def cancel(request_id: UUID, payload: FundingRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return close_request(db, request_id, user.id, "CANCELLED")


@router.post("/payment-requests/{request_id}/pay", response_model=PaymentReceipt, status_code=201)
def pay_request(request_id: UUID, payload: RequestPayInput, idempotency_key: UUID = Header(), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(MoneyRequest).where(MoneyRequest.id == str(request_id), MoneyRequest.payer_user_id == user.id))
    if item is None:
        raise HTTPException(404, "Request not found")
    account = db.scalar(select(BankAccount).join(RequestDestination, RequestDestination.account_id == BankAccount.id).where(RequestDestination.request_id == item.id))
    transfer = TransferRequest(upi_id=account.upi_id, amount=format(item.amount, ".2f"), note=item.note, source_account_id=payload.source_account_id)
    return execute_payment(db, user, str(idempotency_key), "TRANSFER", transfer, money_request_id=item.id)
