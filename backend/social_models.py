"""Personal address books and collect requests; neither is a financial posting."""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "contact_user_id", name="uq_contacts_pair"),
        CheckConstraint("owner_user_id <> contact_user_id", name="ck_contacts_not_self"),
        Index("ix_contacts_owner", "owner_user_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    contact_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    is_favorite: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class MoneyRequest(Base):
    # payment_requests already means payment-engine idempotency. Never rename/replace it.
    __tablename__ = "money_requests"
    __table_args__ = (
        UniqueConstraint("requester_user_id", "creation_key", name="uq_money_requests_creation"),
        CheckConstraint("requester_user_id <> payer_user_id", name="ck_money_request_not_self"),
        CheckConstraint("amount > 0 AND amount <= 100000.00", name="ck_money_request_amount"),
        CheckConstraint("status IN ('PENDING','PAID','DECLINED','CANCELLED','EXPIRED')", name="ck_money_request_status"),
        CheckConstraint("(status='PAID') = (payment_id IS NOT NULL)", name="ck_money_request_link"),
        CheckConstraint("expires_at > created_at AND length(fingerprint)=64", name="ck_money_request_metadata"),
        Index("ix_money_requests_incoming", "payer_user_id", "created_at", "id"),
        Index("ix_money_requests_outgoing", "requester_user_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    note: Mapped[str] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'PENDING'"))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    creation_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequestCreationLimit(Base):
    __tablename__ = "request_creation_limits"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)


class RequestDestination(Base):
    """Pins incoming request payments without modifying any existing request terms."""
    __tablename__ = "money_request_destinations"
    request_id: Mapped[str] = mapped_column(ForeignKey("money_requests.id", ondelete="RESTRICT"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"))
