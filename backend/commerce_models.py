"""Fictional catalogs and owned service records. No real services are activated."""
from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class DemoOperator(Base):
    __tablename__ = "demo_operators"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class RechargePlan(Base):
    __tablename__ = "demo_recharge_plans"
    __table_args__ = (CheckConstraint("price > 0 AND price <= 100000 AND validity_days > 0", name="ck_recharge_plan_terms"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("demo_operators.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(80))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    validity_days: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class DemoBiller(Base):
    __tablename__ = "demo_billers"
    __table_args__ = (CheckConstraint("category IN ('Electricity','Water','Gas','Broadband')", name="ck_biller_category"),)
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class MobileRecharge(Base):
    __tablename__ = "mobile_recharges"
    __table_args__ = (CheckConstraint("status = 'COMPLETED'", name="ck_recharge_status"), Index("ix_recharges_owner", "user_id", "created_at", "id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("demo_recharge_plans.id", ondelete="RESTRICT"))
    masked_mobile: Mapped[str] = mapped_column(String(16))
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="COMPLETED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))


class UtilityBill(Base):
    __tablename__ = "utility_bills"
    __table_args__ = (
        UniqueConstraint("user_id", "biller_id", "reference", "billing_period", name="uq_demo_bill"),
        CheckConstraint("amount_due > 0 AND amount_due <= 100000", name="ck_bill_amount"),
        CheckConstraint("(status='UNPAID' AND payment_id IS NULL AND paid_at IS NULL) OR (status='PAID' AND payment_id IS NOT NULL AND paid_at IS NOT NULL)", name="ck_bill_state"),
        Index("ix_bills_owner", "user_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    biller_id: Mapped[str] = mapped_column(ForeignKey("demo_billers.id", ondelete="RESTRICT"))
    reference: Mapped[str] = mapped_column(String(20))
    billing_period: Mapped[str] = mapped_column(String(7))
    amount_due: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(6), default="UNPAID")
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SavedBiller(Base):
    __tablename__ = "saved_billers"
    __table_args__ = (UniqueConstraint("user_id", "biller_id", "reference", name="uq_saved_biller"), Index("ix_saved_billers_owner", "user_id", "id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    biller_id: Mapped[str] = mapped_column(ForeignKey("demo_billers.id", ondelete="RESTRICT"))
    reference: Mapped[str] = mapped_column(String(20))
    nickname: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
