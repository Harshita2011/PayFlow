"""Shared split locking for request pay, decline/cancel, renewal and split cancellation."""
from sqlalchemy import func, select

from social_models import MoneyRequest
from split_models import ExpenseSplit, SplitParticipant, SplitRequestLink


def lock_linked_split(db, request_id):
    sid = db.scalar(select(SplitParticipant.split_id).join(SplitRequestLink, SplitRequestLink.participant_id == SplitParticipant.id).where(SplitRequestLink.request_id == request_id))
    if sid is None:
        return None
    return db.scalar(select(ExpenseSplit).where(ExpenseSplit.id == sid).with_for_update().execution_options(populate_existing=True))


def linked_request_is_current(db, request_id):
    return db.scalar(select(SplitParticipant.id).where(SplitParticipant.current_request_id == request_id)) is not None


def settle_if_paid(db, split):
    if split is None:
        return
    db.flush()  # Pending PAID assignment must be visible to the aggregate in this transaction.
    unpaid = db.scalar(select(func.count()).select_from(SplitParticipant).join(MoneyRequest, MoneyRequest.id == SplitParticipant.current_request_id).where(SplitParticipant.split_id == split.id, MoneyRequest.status != "PAID"))
    if unpaid == 0:
        now = db.scalar(select(func.clock_timestamp()))
        split.status, split.updated_at = "SETTLED", now
