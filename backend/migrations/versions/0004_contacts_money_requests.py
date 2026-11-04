"""Add personal contacts and collect requests without touching financial history."""
from alembic import op
import sqlalchemy as sa

revision = "0004_contacts_money_requests"
down_revision = "0003_payment_engine"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("contact_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("owner_user_id", "contact_user_id", name="uq_contacts_pair"),
        sa.CheckConstraint("owner_user_id <> contact_user_id", name="ck_contacts_not_self"))
    op.create_index("ix_contacts_owner", "contacts", ["owner_user_id", "id"])
    op.create_table("money_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requester_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("note", sa.String(140), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id", ondelete="RESTRICT"), unique=True),
        sa.Column("creation_key", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("requester_user_id", "creation_key", name="uq_money_requests_creation"),
        sa.CheckConstraint("requester_user_id <> payer_user_id", name="ck_money_request_not_self"),
        sa.CheckConstraint("amount > 0 AND amount <= 100000.00", name="ck_money_request_amount"),
        sa.CheckConstraint("status IN ('PENDING','PAID','DECLINED','CANCELLED','EXPIRED')", name="ck_money_request_status"),
        sa.CheckConstraint("(status='PAID') = (payment_id IS NOT NULL)", name="ck_money_request_link"),
        sa.CheckConstraint("expires_at > created_at AND length(fingerprint)=64", name="ck_money_request_metadata"))
    op.create_index("ix_money_requests_incoming", "money_requests", ["payer_user_id", "created_at", "id"])
    op.create_index("ix_money_requests_outgoing", "money_requests", ["requester_user_id", "created_at", "id"])
    op.create_table("request_creation_limits",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False))
    op.execute("""CREATE FUNCTION payflow_guard_money_request() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Collect requests are retained' USING ERRCODE='23514'; END IF;
      IF OLD.status <> 'PENDING' OR
        ROW(NEW.id,NEW.requester_user_id,NEW.payer_user_id,NEW.amount,NEW.note,NEW.creation_key,NEW.fingerprint,NEW.created_at,NEW.expires_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.requester_user_id,OLD.payer_user_id,OLD.amount,OLD.note,OLD.creation_key,OLD.fingerprint,OLD.created_at,OLD.expires_at)
      THEN RAISE EXCEPTION 'Collect request terms are immutable' USING ERRCODE='23514'; END IF;
      IF NEW.status='PAID' AND clock_timestamp() >= NEW.expires_at THEN
        RAISE EXCEPTION 'Collect request expired' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER guard_money_request BEFORE UPDATE OR DELETE ON money_requests FOR EACH ROW EXECUTE FUNCTION payflow_guard_money_request()")
    op.execute("""CREATE FUNCTION payflow_check_money_request() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r money_requests%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM money_requests WHERE id=NEW.id;
      IF r.status='PAID' AND NOT EXISTS (
        SELECT 1 FROM payments p JOIN bank_accounts s ON s.id=p.sender_account_id
        JOIN bank_accounts t ON t.id=p.recipient_account_id
        WHERE p.id=r.payment_id AND p.status='SUCCESS' AND p.type='TRANSFER'
          AND p.actor_user_id=r.payer_user_id AND s.user_id=r.payer_user_id
          AND t.user_id=r.requester_user_id AND p.amount=r.amount AND p.note=r.note
          AND p.created_at >= r.created_at AND p.created_at < r.expires_at
      ) THEN RAISE EXCEPTION 'Collect request must link its exact successful transfer' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER check_money_request AFTER INSERT OR UPDATE ON money_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_money_request()")


def downgrade():
    raise RuntimeError("Preserve contacts and request history; use a reviewed forward migration")
