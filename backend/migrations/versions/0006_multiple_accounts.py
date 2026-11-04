"""Adapt only account cardinality and payment classification; keep all money unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0006_multiple_accounts"
down_revision = "0005_expense_splits"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("SET CONSTRAINTS ALL DEFERRED")
    op.add_column("bank_accounts", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.execute("UPDATE bank_accounts SET is_primary=true")  # Old schema guarantees one per owner.
    # Validate queued balance checks before DDL; never disable financial triggers.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("SET CONSTRAINTS ALL DEFERRED")
    op.create_index("uq_bank_accounts_primary", "bank_accounts", ["user_id"], unique=True, postgresql_where=sa.text("is_primary"))
    op.create_index("ix_bank_accounts_user", "bank_accounts", ["user_id", "id"])
    op.drop_constraint("uq_bank_accounts_user_id", "bank_accounts", type_="unique")
    op.execute("""CREATE FUNCTION payflow_check_primary() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE n integer; primaries integer;
    BEGIN
      SELECT count(*),count(*) FILTER(WHERE is_primary) INTO n,primaries FROM bank_accounts WHERE user_id=NEW.user_id;
      IF n>4 OR (n>0 AND primaries<>1) THEN RAISE EXCEPTION 'Need one primary and at most four accounts' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER check_primary AFTER INSERT OR UPDATE ON bank_accounts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_primary()")
    op.execute("""CREATE FUNCTION payflow_lock_account_creation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN PERFORM pg_advisory_xact_lock(709,NEW.user_id); RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER lock_account_creation BEFORE INSERT ON bank_accounts FOR EACH ROW EXECUTE FUNCTION payflow_lock_account_creation()")
    op.execute("""CREATE FUNCTION payflow_guard_account_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Account history must be preserved' USING ERRCODE='23514'; END IF;
      IF ROW(NEW.id,NEW.user_id,NEW.account_number,NEW.upi_id,NEW.bank_name,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.user_id,OLD.account_number,OLD.upi_id,OLD.bank_name,OLD.created_at)
      THEN RAISE EXCEPTION 'Account identity and UPI routing are immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER guard_account_identity BEFORE UPDATE OR DELETE ON bank_accounts FOR EACH ROW EXECUTE FUNCTION payflow_guard_account_identity()")
    op.drop_constraint("ck_payment_type", "payments", type_="check")
    op.create_check_constraint("ck_payment_type", "payments", "type IN ('TRANSFER', 'DEMO_FUNDING', 'SELF_TRANSFER')")
    op.drop_constraint("ck_payment_participants", "payments", type_="check")
    op.create_check_constraint("ck_payment_participants", "payments", "status = 'FAILED' OR (recipient_account_id IS NOT NULL AND ((type = 'DEMO_FUNDING' AND sender_account_id IS NULL) OR (type IN ('TRANSFER','SELF_TRANSFER') AND sender_account_id IS NOT NULL AND sender_account_id <> recipient_account_id)))")
    op.execute("""CREATE FUNCTION payflow_check_payment_owners() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE s integer; r integer;
    BEGIN
      IF NEW.status<>'SUCCESS' THEN RETURN NULL; END IF;
      SELECT user_id INTO s FROM bank_accounts WHERE id=NEW.sender_account_id;
      SELECT user_id INTO r FROM bank_accounts WHERE id=NEW.recipient_account_id;
      IF (NEW.type='SELF_TRANSFER' AND (s IS DISTINCT FROM NEW.actor_user_id OR r IS DISTINCT FROM NEW.actor_user_id))
        OR (NEW.type='TRANSFER' AND (s IS DISTINCT FROM NEW.actor_user_id OR s=r))
        OR (NEW.type='DEMO_FUNDING' AND r IS DISTINCT FROM NEW.actor_user_id)
      THEN RAISE EXCEPTION 'Invalid payment ownership' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER check_payment_owners AFTER INSERT ON payments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_payment_owners()")


def downgrade():
    raise RuntimeError("Multiple accounts and financial history cannot be collapsed; use a reviewed forward migration")
