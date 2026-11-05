from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class PinCredential(Base):
    __tablename__ = "payment_pin_credentials"
    __table_args__ = (CheckConstraint("failed_attempts >= 0 AND version > 0", name="ck_pin_state"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class PaymentAuthorization(Base):
    __tablename__ = "payment_authorizations"
    __table_args__ = (
        CheckConstraint("amount > 0 AND pin_version > 0 AND expires_at > created_at", name="ck_authorization_terms"),
        CheckConstraint("length(token_digest)=64 AND length(fingerprint)=64", name="ck_authorization_digests"),
        CheckConstraint("(consumed_at IS NULL) = (payment_id IS NULL)", name="ck_authorization_consumption"),
        Index("ix_authorizations_owner", "user_id", "created_at"),
    )
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source_account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id", ondelete="RESTRICT"))
    operation: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    destination_digest: Mapped[str] = mapped_column(String(64))
    pin_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)


class PaymentLimitCounter(Base):
    __tablename__ = "payment_limit_counters"
    __table_args__ = (CheckConstraint("amount >= 0 AND transaction_count >= 0", name="ck_daily_usage"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    utc_day: Mapped[date] = mapped_column(Date, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)


class SecurityRateWindow(Base):
    __tablename__ = "security_rate_windows"
    __table_args__ = (CheckConstraint("attempts > 0", name="ck_rate_attempts"),)
    bucket: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (Index("ix_security_events_owner", "actor_user_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(40))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    operation_id: Mapped[str | None] = mapped_column(String(36))
    outcome: Mapped[str] = mapped_column(String(12))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class FraudRiskDecision(Base):
    __tablename__ = "fraud_risk_decisions"
    __table_args__ = (
        CheckConstraint("risk_level IN ('LOW','MEDIUM','HIGH') AND decision IN ('ALLOW','BLOCK')", name="ck_risk_decision"),
        Index("ix_risk_owner", "user_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    operation_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(20))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    risk_level: Mapped[str] = mapped_column(String(6))
    decision: Mapped[str] = mapped_column(String(5))
    rules: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
