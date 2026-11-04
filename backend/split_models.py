"""Expense obligations. Payment/request state remains the monetary source of truth."""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ExpenseSplit(Base):
    __tablename__ = "expense_splits"
    __table_args__ = (
        UniqueConstraint("creator_user_id", "creation_key", name="uq_split_creation"),
        CheckConstraint("total_amount > 0 AND total_amount <= 100000.00", name="ck_split_total"),
        CheckConstraint("currency='INR' AND expense_model='EXTERNAL_RECORD'", name="ck_split_currency_model"),
        CheckConstraint("status IN ('OPEN','SETTLED','CANCELLED')", name="ck_split_status"),
        CheckConstraint("length(fingerprint)=64", name="ck_split_fingerprint"),
        Index("ix_splits_creator", "creator_user_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    destination_account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(240), default="")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    expense_model: Mapped[str] = mapped_column(String(20), default="EXTERNAL_RECORD")
    status: Mapped[str] = mapped_column(String(9), default="OPEN")
    creation_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class SplitParticipant(Base):
    __tablename__ = "expense_split_participants"
    __table_args__ = (
        UniqueConstraint("split_id", "user_id", name="uq_split_user"),
        CheckConstraint("share_amount > 0 AND share_amount <= 100000.00", name="ck_split_share"),
        Index("ix_split_participant_user", "user_id", "split_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    split_id: Mapped[str] = mapped_column(ForeignKey("expense_splits.id", ondelete="RESTRICT"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    share_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    current_request_id: Mapped[str | None] = mapped_column(ForeignKey("money_requests.id", ondelete="RESTRICT"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class SplitRequestLink(Base):
    __tablename__ = "split_request_links"
    request_id: Mapped[str] = mapped_column(ForeignKey("money_requests.id", ondelete="RESTRICT"), primary_key=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("expense_split_participants.id", ondelete="RESTRICT"), index=True)
