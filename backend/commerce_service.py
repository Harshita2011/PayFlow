"""Fulfillment hooks inside execute_payment's transaction; never mutate balances here."""
from fastapi import HTTPException
from sqlalchemy import select
from commerce_models import DemoBiller, DemoOperator, RechargePlan, MobileRecharge, UtilityBill


def prepare_purchase(db, user_id, kind, payload, bill_id):
    if kind == "MOBILE_RECHARGE":
        row = db.execute(select(RechargePlan, DemoOperator).join(DemoOperator,
            RechargePlan.operator_id == DemoOperator.id).where(RechargePlan.id == payload.plan_id,
            RechargePlan.active.is_(True), DemoOperator.active.is_(True)).with_for_update(read=True)).first()
        if row is None:
            raise HTTPException(404, "Demo plan not available")
        plan, operator = row
        return {"amount": plan.price, "name": operator.name, "note": f"Simulated recharge · {plan.name}", "plan": plan,
            "settlement": "settlement-recharge"}
    bill = db.scalar(select(UtilityBill).where(UtilityBill.id == bill_id, UtilityBill.user_id == user_id)
        .with_for_update().execution_options(populate_existing=True))
    if bill is None:
        raise HTTPException(404, "Bill not found")
    return {"amount": bill.amount_due, "name": db.get(DemoBiller, bill.biller_id).name,
        "note": f"Simulated bill · {bill.billing_period}", "bill": bill, "settlement": "settlement-bills"}


def fulfill_purchase(db, user_id, payment, payload, purchase):
    if payment.type == "MOBILE_RECHARGE":
        # The full mobile number exists only in the validated request, not in history.
        db.add(MobileRecharge(user_id=user_id, plan_id=purchase["plan"].id,
            masked_mobile="••••••" + payload.mobile[-4:], payment_id=payment.id))
    else:
        from sqlalchemy import func
        now = db.scalar(select(func.clock_timestamp()))
        bill = purchase["bill"]
        bill.status, bill.payment_id, bill.paid_at, bill.updated_at = "PAID", payment.id, now, now
