"""Add fictional accounts and UPI identities without modifying existing users."""
from alembic import op
import sqlalchemy as sa

revision = "0002_bank_accounts"
down_revision = "0001_users_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bank_name", sa.String(50), nullable=False),
        sa.Column("account_number", sa.String(19), nullable=False),
        sa.Column("upi_id", sa.String(48), nullable=False),
        sa.Column("balance", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_bank_accounts_user_id", ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", name="uq_bank_accounts_user_id"),
        sa.UniqueConstraint("account_number", name="uq_bank_accounts_account_number"),
        sa.UniqueConstraint("upi_id", name="uq_bank_accounts_upi_id"),
        sa.CheckConstraint("balance >= 0 AND balance <= 9999999999999999.99", name="ck_bank_accounts_balance_range"),
        sa.CheckConstraint("bank_name IN ('Grove Demo Bank', 'Orbit Demo Bank', 'River Demo Bank')", name="ck_bank_accounts_bank_name"),
        sa.CheckConstraint("account_number ~ '^SIM[0-9]{16}$'", name="ck_bank_accounts_number_format"),
        sa.CheckConstraint("upi_id ~ '^[a-z0-9][a-z0-9-]{0,39}@payflow$'", name="ck_bank_accounts_upi_format"),
    )


def downgrade():
    raise RuntimeError("Refusing to drop bank_accounts; use a reviewed forward migration")
