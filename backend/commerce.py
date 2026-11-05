"""Authenticated fictional catalogs, billing and receipts; money moves only in payments.py."""
import calendar
import hashlib
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import get_db
from security import get_current_user
from models import User
from payment_models import Payment
from payments import charge_lookup, execute_payment, receipt
from commerce_models import DemoOperator, RechargePlan, DemoBiller, MobileRecharge, UtilityBill, SavedBiller
from commerce_schemas import RechargeInput, BillLookup, SaveBillerInput, BillPayInput, RechargeOperatorOut, PlanOut, BillerOut, RechargeOut, BillOut, SavedBillerOut, CommercePage
from payment_schemas import PaymentReceipt

router = APIRouter(tags=["Fictional bills and recharge"])


def require_biller(db, code):
    biller = db.scalar(select(DemoBiller).where(DemoBiller.id == code, DemoBiller.active.is_(True)))
    if biller is None:
        raise HTTPException(404, "Demo biller not available")
    return biller


@router.get("/recharge/operators", response_model=list[RechargeOperatorOut])
def operators(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(DemoOperator).where(DemoOperator.active.is_(True)).order_by(DemoOperator.id)))


@router.get("/recharge/plans", response_model=list[PlanOut])
def plans(operator_id: str = Query(max_length=24), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(RechargePlan).join(DemoOperator).where(RechargePlan.operator_id == operator_id,
        RechargePlan.active.is_(True), DemoOperator.active.is_(True)).order_by(RechargePlan.price, RechargePlan.id)))


@router.post("/recharge", response_model=PaymentReceipt, status_code=201)
def recharge(payload: RechargeInput, idempotency_key: UUID = Header(), payment_authorization: str | None = Header(default=None, max_length=128), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return execute_payment(db, user, str(idempotency_key), "MOBILE_RECHARGE", payload, authorization_token=payment_authorization)


@router.get("/billers", response_model=list[BillerOut])
def billers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(DemoBiller).where(DemoBiller.active.is_(True)).order_by(DemoBiller.category)))


def bill_view(row, db):
    bill, biller, payment = row
    today = db.scalar(select(func.current_date()))
    return BillOut(id=bill.id, biller_id=biller.id, biller=biller.name, category=biller.category,
        masked_reference="DEMO••" + bill.reference[-4:], billing_period=bill.billing_period, amount_due=bill.amount_due,
        due_date=bill.due_date, status="OVERDUE" if bill.status == "UNPAID" and bill.due_date < today else bill.status,
        created_at=bill.created_at, paid_at=bill.paid_at,
        receipt=receipt(payment, payment.sender_account_id) if payment else None)


def bill_query(user_id):
    return select(UtilityBill, DemoBiller, Payment).join(DemoBiller, DemoBiller.id == UtilityBill.biller_id).outerjoin(
        Payment, Payment.id == UtilityBill.payment_id).where(UtilityBill.user_id == user_id)


def owned_bill(db, user_id, bill_id):
    row = db.execute(bill_query(user_id).where(UtilityBill.id == bill_id)).first()
    if row is None:
        raise HTTPException(404, "Bill not found")
    return bill_view(row, db)


def lookup_bill(db, user_id, biller_id, reference):
    require_biller(db, biller_id)
    # One deterministic monthly bill per owner/biller/reference. No live lookup or PII.
    today = db.scalar(select(func.current_date()))
    period = today.strftime("%Y-%m")
    existing = db.scalar(select(UtilityBill.id).where(UtilityBill.user_id == user_id, UtilityBill.biller_id == biller_id,
        UtilityBill.reference == reference, UtilityBill.billing_period == period))
    if existing:
        return owned_bill(db, user_id, existing)
    # Serialize catalog-created records per owner to enforce a bounded demo store.
    from sqlalchemy import text
    db.execute(text("SELECT pg_advisory_xact_lock(712,:uid)"), {"uid": user_id})
    if db.scalar(select(func.count()).select_from(UtilityBill).where(UtilityBill.user_id == user_id)) >= 100:
        raise HTTPException(429, "Demo bill storage limit reached (100 per user)")
    digest = hashlib.sha256(f"{biller_id}:{reference}:{period}".encode()).hexdigest()
    amount = Decimal(10000 + int(digest[:8], 16) % 40001) / Decimal(100)
    bill_id = str(uuid4())
    db.execute(insert(UtilityBill).values(id=bill_id, user_id=user_id, biller_id=biller_id, reference=reference,
        billing_period=period, amount_due=amount, due_date=today.replace(day=calendar.monthrange(today.year, today.month)[1]),
        status="UNPAID").on_conflict_do_nothing(constraint="uq_demo_bill"))
    db.commit()
    actual = db.scalar(select(UtilityBill.id).where(UtilityBill.user_id == user_id, UtilityBill.biller_id == biller_id,
        UtilityBill.reference == reference, UtilityBill.billing_period == period))
    return owned_bill(db, user_id, actual)


@router.post("/bills/lookup", response_model=BillOut)
def lookup(payload: BillLookup, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    charge_lookup(db, user.id)
    return lookup_bill(db, user.id, payload.biller_id, payload.reference)


@router.get("/bills", response_model=CommercePage)
@router.get("/bills/history", response_model=CommercePage)
def bills(limit: int = Query(10, ge=1, le=50), before: UUID | None = None, paid_only: bool = False,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = bill_query(user.id)
    if paid_only:
        query = query.where(UtilityBill.status == "PAID")
    if before:
        cursor = db.scalar(select(UtilityBill).where(UtilityBill.id == str(before), UtilityBill.user_id == user.id))
        if cursor is None:
            raise HTTPException(404, "Bill not found")
        query = query.where(tuple_(UtilityBill.created_at, UtilityBill.id) < (cursor.created_at, cursor.id))
    rows = db.execute(query.order_by(UtilityBill.created_at.desc(), UtilityBill.id.desc()).limit(limit + 1)).all()
    return CommercePage(items=[bill_view(row, db) for row in rows[:limit]], next_cursor=rows[limit-1][0].id if len(rows) > limit else None)


@router.get("/bills/{bill_id}", response_model=BillOut)
def bill_detail(bill_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return owned_bill(db, user.id, str(bill_id))


@router.post("/bills/{bill_id}/pay", response_model=PaymentReceipt, status_code=201)
def pay_bill(bill_id: UUID, payload: BillPayInput, idempotency_key: UUID = Header(), payment_authorization: str | None = Header(default=None, max_length=128), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return execute_payment(db, user, str(idempotency_key), "BILL_PAYMENT", payload, bill_id=str(bill_id), authorization_token=payment_authorization)


def recharge_query(user_id):
    return select(MobileRecharge, RechargePlan, DemoOperator, Payment).join(RechargePlan, RechargePlan.id == MobileRecharge.plan_id).join(
        DemoOperator, DemoOperator.id == RechargePlan.operator_id).join(Payment, Payment.id == MobileRecharge.payment_id).where(MobileRecharge.user_id == user_id)


def recharge_view(row):
    item, plan, operator, payment = row
    return RechargeOut(id=item.id, operator=operator.name, plan_id=plan.id, plan_name=plan.name, masked_mobile=item.masked_mobile,
        status=item.status, created_at=item.created_at, receipt=receipt(payment, payment.sender_account_id))


@router.get("/recharge/history", response_model=CommercePage)
def recharge_history(limit: int = Query(10, ge=1, le=50), before: UUID | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = recharge_query(user.id)
    if before:
        cursor = db.scalar(select(MobileRecharge).where(MobileRecharge.id == str(before), MobileRecharge.user_id == user.id))
        if cursor is None:
            raise HTTPException(404, "Recharge not found")
        query = query.where(tuple_(MobileRecharge.created_at, MobileRecharge.id) < (cursor.created_at, cursor.id))
    rows = db.execute(query.order_by(MobileRecharge.created_at.desc(), MobileRecharge.id.desc()).limit(limit + 1)).all()
    return CommercePage(items=[recharge_view(row) for row in rows[:limit]], next_cursor=rows[limit-1][0].id if len(rows) > limit else None)


@router.get("/recharge/{recharge_id}", response_model=RechargeOut)
def recharge_detail(recharge_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(recharge_query(user.id).where(MobileRecharge.id == str(recharge_id))).first()
    if row is None:
        raise HTTPException(404, "Recharge not found")
    return recharge_view(row)


def saved_view(item, biller):
    return SavedBillerOut(id=item.id, biller_id=biller.id, biller=biller.name, nickname=item.nickname, masked_reference="DEMO••" + item.reference[-4:])


@router.get("/saved-billers", response_model=list[SavedBillerOut])
def saved(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [saved_view(item, biller) for item, biller in db.execute(select(SavedBiller, DemoBiller).join(DemoBiller).where(SavedBiller.user_id == user.id).order_by(SavedBiller.created_at.desc(), SavedBiller.id))]


@router.post("/saved-billers", response_model=SavedBillerOut, status_code=201)
def save(payload: SaveBillerInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    charge_lookup(db, user.id)
    biller = require_biller(db, payload.biller_id)
    from sqlalchemy import text
    db.execute(text("SELECT pg_advisory_xact_lock(712,:uid)"), {"uid": user.id})
    if db.scalar(select(func.count()).select_from(SavedBiller).where(SavedBiller.user_id == user.id)) >= 20:
        raise HTTPException(429, "Saved biller limit reached (20)")
    row_id = db.scalar(insert(SavedBiller).values(user_id=user.id, **payload.model_dump()).on_conflict_do_nothing(constraint="uq_saved_biller").returning(SavedBiller.id))
    db.commit()
    if row_id is None:
        raise HTTPException(409, "Biller and reference already saved")
    return saved_view(db.get(SavedBiller, row_id), biller)


@router.post("/saved-billers/{saved_id}/lookup", response_model=BillOut)
def saved_lookup(saved_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    charge_lookup(db, user.id)
    item = db.scalar(select(SavedBiller).where(SavedBiller.id == str(saved_id), SavedBiller.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Saved biller not found")
    return lookup_bill(db, user.id, item.biller_id, item.reference)


@router.delete("/saved-billers/{saved_id}", status_code=204)
def remove(saved_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(SavedBiller).where(SavedBiller.id == str(saved_id), SavedBiller.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Saved biller not found")
    db.delete(item)
    db.commit()
    return Response(status_code=204)
