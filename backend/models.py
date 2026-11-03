from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    bank_account: Mapped["BankAccount | None"] = relationship(
        back_populates="owner", uselist=False, passive_deletes=True
    )


class DemoBank(str, Enum):
    GROVE = "Grove Demo Bank"
    ORBIT = "Orbit Demo Bank"
    RIVER = "River Demo Bank"


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_bank_accounts_user_id"),
        UniqueConstraint("account_number", name="uq_bank_accounts_account_number"),
        UniqueConstraint("upi_id", name="uq_bank_accounts_upi_id"),
        CheckConstraint(
            "balance >= 0 AND balance <= 9999999999999999.99",
            name="ck_bank_accounts_balance_range",
        ),
        CheckConstraint(
            "bank_name IN ('Grove Demo Bank', 'Orbit Demo Bank', 'River Demo Bank')",
            name="ck_bank_accounts_bank_name",
        ),
        CheckConstraint(
            "account_number ~ '^SIM[0-9]{16}$'",
            name="ck_bank_accounts_number_format",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "upi_id ~ '^[a-z0-9][a-z0-9-]{0,39}@payflow$'",
            name="ck_bank_accounts_upi_format",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_bank_accounts_user_id"),
        nullable=False,
    )
    bank_name: Mapped[str] = mapped_column(String(50), nullable=False)
    account_number: Mapped[str] = mapped_column(String(19), nullable=False)
    upi_id: Mapped[str] = mapped_column(String(48), nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), server_default=text("0.00"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"), nullable=False,
    )
    owner: Mapped[User] = relationship(back_populates="bank_account")
