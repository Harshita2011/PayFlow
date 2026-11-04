"""Shared collect-request capacity for standalone requests and split contributions."""
from fastapi import HTTPException
from sqlalchemy import func, select, text

from social_models import MoneyRequest


def reserve_capacity(db, requester_id: int, payer_ids: list[int]):
    for uid in sorted({requester_id, *payer_ids}):
        db.execute(text("SELECT pg_advisory_xact_lock(707,:uid)"), {"uid": uid})
    now = db.scalar(select(func.clock_timestamp()))
    count = len(payer_ids)
    attempts = db.execute(text("""INSERT INTO request_creation_limits(user_id,window_start,attempts)
        VALUES (:uid,date_trunc('hour',clock_timestamp()),:cost)
        ON CONFLICT(user_id) DO UPDATE SET window_start=EXCLUDED.window_start,
        attempts=CASE WHEN request_creation_limits.window_start=EXCLUDED.window_start
          THEN LEAST(request_creation_limits.attempts+:cost,11) ELSE :cost END RETURNING attempts"""), {"uid": requester_id, "cost": count}).scalar_one()
    active = (MoneyRequest.status == "PENDING", MoneyRequest.expires_at > now)
    outgoing = db.scalar(select(func.count()).select_from(MoneyRequest).where(MoneyRequest.requester_user_id == requester_id, *active))
    incoming = dict(db.execute(select(MoneyRequest.payer_user_id, func.count()).where(MoneyRequest.payer_user_id.in_(payer_ids), *active).group_by(MoneyRequest.payer_user_id)).all())
    if attempts > 10 or outgoing + count > 20 or any(incoming.get(uid, 0) >= 50 for uid in payer_ids):
        # Called before new request/split rows are added: only the abuse counter commits.
        db.commit()
        raise HTTPException(429, "Request limit reached. Try later or resolve outstanding requests", headers={"Retry-After": "3600"})
    return now
