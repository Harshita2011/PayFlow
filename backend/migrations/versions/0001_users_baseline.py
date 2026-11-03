"""Adopt the existing users table without changing rows; support a fresh database."""
from alembic import op
import sqlalchemy as sa

revision = "0001_users_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("users"):
        columns = {column["name"]: column for column in inspector.get_columns("users")}
        expected = {"id", "full_name", "email", "password_hash", "created_at"}
        valid = set(columns) == expected and all(not column["nullable"] for column in columns.values())
        valid = valid and isinstance(columns["id"]["type"], sa.Integer)
        for name, length in [("full_name", 100), ("email", 255), ("password_hash", 255)]:
            valid = valid and isinstance(columns[name]["type"], sa.String) and columns[name]["type"].length == length
        valid = valid and isinstance(columns["created_at"]["type"], sa.DateTime) and columns["created_at"]["type"].timezone
        valid = valid and inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
        valid = valid and any(item["column_names"] == ["email"] for item in inspector.get_unique_constraints("users"))
        if not valid:
            raise RuntimeError("Existing users schema differs from Phase 2; inspect it before migrating")
        return
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="users_email_key"),
    )


def downgrade():
    raise RuntimeError("Refusing to remove the users baseline; existing users must be preserved")
