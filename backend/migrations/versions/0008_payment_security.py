"""Add security state; never rewrite existing users or financial history."""
from alembic import op
import sqlalchemy as sa

revision = "0008_payment_security"
down_revision = "0007_bills_recharge"
branch_labels = None
depends_on = None


def fk(name, target, **kwargs):
    return sa.Column(name, sa.Integer() if target in {"users.id", "bank_accounts.id"} else sa.String(36), sa.ForeignKey(target, ondelete="RESTRICT"), **kwargs)


def timestamp(name, **kwargs):
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade():
    op.create_table("payment_pin_credentials", fk("user_id", "users.id", primary_key=True),
        sa.Column("pin_hash", sa.String(255), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False), timestamp("locked_until"),
        timestamp("updated_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("failed_attempts >= 0 AND version > 0", name="ck_pin_state"))
    op.create_table("payment_authorizations", sa.Column("token_digest", sa.String(64), primary_key=True),
        fk("user_id", "users.id", nullable=False), fk("source_account_id", "bank_accounts.id", nullable=False),
        sa.Column("operation", sa.String(20), nullable=False), sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("amount", sa.Numeric(18,2), nullable=False),
        sa.Column("destination_digest", sa.String(64), nullable=False), sa.Column("pin_version", sa.Integer(), nullable=False),
        timestamp("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), timestamp("expires_at", nullable=False),
        timestamp("consumed_at"), fk("payment_id", "payments.id", unique=True),
        sa.CheckConstraint("amount > 0 AND pin_version > 0 AND expires_at > created_at", name="ck_authorization_terms"),
        sa.CheckConstraint("length(token_digest)=64 AND length(fingerprint)=64", name="ck_authorization_digests"),
        sa.CheckConstraint("(consumed_at IS NULL) = (payment_id IS NULL)", name="ck_authorization_consumption"))
    op.create_index("ix_authorizations_owner", "payment_authorizations", ["user_id", "created_at"])
    op.create_table("payment_limit_counters", fk("user_id", "users.id", primary_key=True), sa.Column("utc_day", sa.Date(), primary_key=True),
        sa.Column("amount", sa.Numeric(18,2), nullable=False), sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount >= 0 AND transaction_count >= 0", name="ck_daily_usage"))
    op.create_table("security_rate_windows", sa.Column("bucket", sa.String(32), primary_key=True),
        sa.Column("subject_digest", sa.String(64), primary_key=True), timestamp("window_start", primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.CheckConstraint("attempts > 0", name="ck_rate_attempts"))
    op.create_table("security_audit_events", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False), fk("actor_user_id", "users.id"),
        timestamp("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("operation_id", sa.String(36)), sa.Column("outcome", sa.String(12), nullable=False), sa.Column("details", sa.JSON(), nullable=False))
    op.create_index("ix_security_events_owner", "security_audit_events", ["actor_user_id", "created_at", "id"])
    op.create_table("fraud_risk_decisions", sa.Column("id", sa.String(36), primary_key=True), fk("user_id", "users.id", nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False), sa.Column("operation", sa.String(20), nullable=False), fk("payment_id", "payments.id"),
        sa.Column("risk_level", sa.String(6), nullable=False), sa.Column("decision", sa.String(5), nullable=False), sa.Column("rules", sa.JSON(), nullable=False),
        timestamp("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("risk_level IN ('LOW','MEDIUM','HIGH') AND decision IN ('ALLOW','BLOCK')", name="ck_risk_decision"))
    op.create_index("ix_risk_owner", "fraud_risk_decisions", ["user_id", "created_at", "id"])
    op.execute("""CREATE FUNCTION payflow_guard_authorization() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.consumed_at IS NOT NULL OR ROW(NEW.token_digest,NEW.user_id,NEW.source_account_id,NEW.operation,NEW.idempotency_key,NEW.fingerprint,NEW.amount,NEW.destination_digest,NEW.pin_version,NEW.created_at,NEW.expires_at)
        IS DISTINCT FROM ROW(OLD.token_digest,OLD.user_id,OLD.source_account_id,OLD.operation,OLD.idempotency_key,OLD.fingerprint,OLD.amount,OLD.destination_digest,OLD.pin_version,OLD.created_at,OLD.expires_at)
      THEN RAISE EXCEPTION 'Authorization terms are immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER guard_authorization BEFORE UPDATE ON payment_authorizations FOR EACH ROW EXECUTE FUNCTION payflow_guard_authorization()")
    for table in ['security_audit_events', 'fraud_risk_decisions']:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION payflow_immutable()")
    # Applies only to newly inserted payments, leaving all historical postings untouched.
    op.execute("""CREATE FUNCTION payflow_check_payment_authorization() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE n integer;
    BEGIN
      IF NEW.status<>'SUCCESS' OR NEW.type='DEMO_FUNDING' THEN RETURN NULL; END IF;
      SELECT count(*) INTO n FROM payment_authorizations a JOIN payment_requests r
        ON r.user_id=a.user_id AND r.key=a.idempotency_key AND r.payment_id=NEW.id AND r.fingerprint=a.fingerprint
        WHERE a.payment_id=NEW.id AND a.user_id=NEW.actor_user_id AND a.source_account_id=NEW.sender_account_id
          AND a.amount=NEW.amount AND a.consumed_at IS NOT NULL AND a.consumed_at<a.expires_at;
      IF n<>1 THEN RAISE EXCEPTION 'Payment requires a consumed bound authorization' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER check_payment_authorization AFTER INSERT ON payments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_payment_authorization()")


def downgrade():
    raise RuntimeError("Security and financial history must be preserved; use a reviewed forward migration")
