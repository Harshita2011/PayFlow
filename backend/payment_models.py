from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (CheckConstraint(
        "(id IN ('demo-funding','settlement-recharge','settlement-bills') AND bank_account_id IS NULL) OR "
        "(bank_account_id IS NOT NULL AND id = 'bank-' || CAST(bank_account_id AS TEXT))",
        name="ck_ledger_account_identity",
    ),)
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"), unique=True)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0 AND amount <= 9999999999999999.99", name="ck_payment_amount"),
        CheckConstraint("currency = 'INR'", name="ck_payment_currency"),
        CheckConstraint("type IN ('TRANSFER', 'DEMO_FUNDING', 'SELF_TRANSFER','MOBILE_RECHARGE','BILL_PAYMENT')", name="ck_payment_type"),
        CheckConstraint("status IN ('SUCCESS', 'FAILED')", name="ck_payment_status"),
        CheckConstraint(
            "status = 'FAILED' OR (type IN ('MOBILE_RECHARGE','BILL_PAYMENT') AND sender_account_id IS NOT NULL AND recipient_account_id IS NULL AND settlement_ledger_account_id IS NOT NULL) OR (settlement_ledger_account_id IS NULL AND recipient_account_id IS NOT NULL AND "
            "((type = 'DEMO_FUNDING' AND sender_account_id IS NULL) OR "
            "(type IN ('TRANSFER','SELF_TRANSFER') AND sender_account_id IS NOT NULL AND sender_account_id <> recipient_account_id)))",
            name="ck_payment_participants",
        ),
        CheckConstraint("channel IS NULL OR (type='TRANSFER' AND channel IN ('QR','REQUEST'))", name="ck_payment_channel"),
        CheckConstraint("settlement_ledger_account_id IS NULL OR (type='MOBILE_RECHARGE' AND settlement_ledger_account_id='settlement-recharge') OR (type='BILL_PAYMENT' AND settlement_ledger_account_id='settlement-bills')", name="ck_payment_settlement"),
        Index("ix_payments_sender_history", "sender_account_id", "created_at", "id"),
        Index("ix_payments_recipient_history", "recipient_account_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    sender_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"))
    recipient_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"))
    settlement_ledger_account_id: Mapped[str | None] = mapped_column(ForeignKey("ledger_accounts.id", ondelete="RESTRICT"))
    channel: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(7))
    sender_upi_id: Mapped[str | None] = mapped_column(String(48))
    recipient_upi_id: Mapped[str | None] = mapped_column(String(48))
    sender_name: Mapped[str] = mapped_column(String(100))
    recipient_name: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(String(140), default="")
    failure_reason: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    sender_account = relationship("BankAccount", foreign_keys=[sender_account_id], lazy="selectin")
    recipient_account = relationship("BankAccount", foreign_keys=[recipient_account_id], lazy="selectin")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint(
        "amount <> 0 AND amount >= -9999999999999999.99 AND amount <= 9999999999999999.99",
        name="ck_ledger_entry_amount",
    ),)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), primary_key=True)
    ledger_account_id: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), primary_key=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class PaymentRequest(Base):
    __tablename__ = "payment_requests"
    __table_args__ = (CheckConstraint(
        "length(fingerprint) = 64 AND (http_status IS NULL OR http_status BETWEEN 200 AND 599)",
        name="ck_payment_request_result",
    ),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    key: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))


class RecipientLookupLimit(Base):
    __tablename__ = "recipient_lookup_limits"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)
