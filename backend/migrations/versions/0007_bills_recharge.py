"""Add fictional service purchases without rewriting financial history."""
from alembic import op
import sqlalchemy as sa

revision = "0007_bills_recharge"
down_revision = "0006_multiple_accounts"
branch_labels = None
depends_on = None


def fk(name, target, **kw):
    return sa.Column(name, sa.Integer() if target.endswith('.id') and target.split('.')[0] in {'users', 'bank_accounts'} else sa.String(36), sa.ForeignKey(target, ondelete="RESTRICT"), **kw)


def stamp(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def upgrade():
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("SET CONSTRAINTS ALL DEFERRED")
    op.drop_constraint("ck_ledger_account_identity", "ledger_accounts", type_="check")
    op.create_check_constraint("ck_ledger_account_identity", "ledger_accounts", "(id IN ('demo-funding','settlement-recharge','settlement-bills') AND bank_account_id IS NULL) OR (bank_account_id IS NOT NULL AND id='bank-' || CAST(bank_account_id AS TEXT))")
    op.execute("INSERT INTO ledger_accounts(id) VALUES ('settlement-recharge'),('settlement-bills') ON CONFLICT DO NOTHING")
    op.add_column("payments", sa.Column("settlement_ledger_account_id", sa.String(48), sa.ForeignKey("ledger_accounts.id", ondelete="RESTRICT")))
    op.add_column("payments", sa.Column("channel", sa.String(16)))
    op.drop_constraint("ck_payment_type", "payments", type_="check")
    op.create_check_constraint("ck_payment_type", "payments", "type IN ('TRANSFER','DEMO_FUNDING','SELF_TRANSFER','MOBILE_RECHARGE','BILL_PAYMENT')")
    op.drop_constraint("ck_payment_participants", "payments", type_="check")
    op.create_check_constraint("ck_payment_participants", "payments", "status='FAILED' OR (type IN ('MOBILE_RECHARGE','BILL_PAYMENT') AND sender_account_id IS NOT NULL AND recipient_account_id IS NULL AND settlement_ledger_account_id IS NOT NULL) OR (settlement_ledger_account_id IS NULL AND recipient_account_id IS NOT NULL AND ((type='DEMO_FUNDING' AND sender_account_id IS NULL) OR (type IN ('TRANSFER','SELF_TRANSFER') AND sender_account_id IS NOT NULL AND sender_account_id<>recipient_account_id)))")
    op.create_check_constraint("ck_payment_settlement", "payments", "settlement_ledger_account_id IS NULL OR (type='MOBILE_RECHARGE' AND settlement_ledger_account_id='settlement-recharge') OR (type='BILL_PAYMENT' AND settlement_ledger_account_id='settlement-bills')")
    op.create_check_constraint("ck_payment_channel", "payments", "channel IS NULL OR (type='TRANSFER' AND channel IN ('QR','REQUEST'))")
    op.create_table("demo_operators", sa.Column("id", sa.String(24), primary_key=True), sa.Column("name", sa.String(80), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_table("demo_recharge_plans", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("operator_id", sa.String(24), sa.ForeignKey("demo_operators.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False), sa.Column("price", sa.Numeric(18,2), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False), sa.Column("description", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("price > 0 AND price <= 100000 AND validity_days > 0", name="ck_recharge_plan_terms"))
    op.create_table("demo_billers", sa.Column("id", sa.String(24), primary_key=True), sa.Column("name", sa.String(80), nullable=False),
        sa.Column("category", sa.String(16), nullable=False), sa.Column("description", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("category IN ('Electricity','Water','Gas','Broadband')", name="ck_biller_category"))
    op.create_table("mobile_recharges", sa.Column("id", sa.String(36), primary_key=True), fk("user_id", "users.id", nullable=False),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("demo_recharge_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("masked_mobile", sa.String(16), nullable=False), fk("payment_id", "payments.id", nullable=False, unique=True),
        sa.Column("status", sa.String(12), nullable=False), stamp("created_at"), sa.CheckConstraint("status='COMPLETED'", name="ck_recharge_status"))
    op.create_index("ix_recharges_owner", "mobile_recharges", ["user_id", "created_at", "id"])
    op.create_table("utility_bills", sa.Column("id", sa.String(36), primary_key=True), fk("user_id", "users.id", nullable=False),
        sa.Column("biller_id", sa.String(24), sa.ForeignKey("demo_billers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reference", sa.String(20), nullable=False), sa.Column("billing_period", sa.String(7), nullable=False),
        sa.Column("amount_due", sa.Numeric(18,2), nullable=False), sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(6), nullable=False), fk("payment_id", "payments.id", unique=True), stamp("created_at"), stamp("updated_at"),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "biller_id", "reference", "billing_period", name="uq_demo_bill"),
        sa.CheckConstraint("amount_due > 0 AND amount_due <= 100000", name="ck_bill_amount"),
        sa.CheckConstraint("(status='UNPAID' AND payment_id IS NULL AND paid_at IS NULL) OR (status='PAID' AND payment_id IS NOT NULL AND paid_at IS NOT NULL)", name="ck_bill_state"))
    op.create_index("ix_bills_owner", "utility_bills", ["user_id", "created_at", "id"])
    op.create_table("saved_billers", sa.Column("id", sa.String(36), primary_key=True), fk("user_id", "users.id", nullable=False),
        sa.Column("biller_id", sa.String(24), sa.ForeignKey("demo_billers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reference", sa.String(20), nullable=False), sa.Column("nickname", sa.String(40), nullable=False), stamp("created_at"),
        sa.UniqueConstraint("user_id", "biller_id", "reference", name="uq_saved_biller"))
    op.create_index("ix_saved_billers_owner", "saved_billers", ["user_id", "id"])
    from commerce_seed import seed
    seed(op.get_bind())
    # Reuse the original deferred posting validator, extending only its credit destination.
    op.execute("""CREATE OR REPLACE FUNCTION payflow_check_posting() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p payments%ROWTYPE; n integer; net numeric; debits integer; credits integer; pid text;
    BEGIN
      IF TG_TABLE_NAME='payments' THEN pid:=NEW.id; ELSE pid:=NEW.payment_id; END IF;
      SELECT * INTO p FROM payments WHERE id=pid;
      SELECT count(*),coalesce(sum(amount),0),
        count(*) FILTER(WHERE amount=-p.amount AND ledger_account_id=CASE WHEN p.type='DEMO_FUNDING' THEN 'demo-funding' ELSE 'bank-'||p.sender_account_id END),
        count(*) FILTER(WHERE amount=p.amount AND ledger_account_id=coalesce(p.settlement_ledger_account_id,'bank-'||p.recipient_account_id))
      INTO n,net,debits,credits FROM ledger_entries WHERE payment_id=pid;
      IF (p.status='SUCCESS' AND (n<>2 OR net<>0 OR debits<>1 OR credits<>1)) OR (p.status='FAILED' AND n<>0)
      THEN RAISE EXCEPTION 'Invalid double-entry posting' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION payflow_check_payment_owners() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE s integer; r integer;
    BEGIN
      IF NEW.status<>'SUCCESS' THEN RETURN NULL; END IF;
      SELECT user_id INTO s FROM bank_accounts WHERE id=NEW.sender_account_id;
      SELECT user_id INTO r FROM bank_accounts WHERE id=NEW.recipient_account_id;
      IF (NEW.type='SELF_TRANSFER' AND (s IS DISTINCT FROM NEW.actor_user_id OR r IS DISTINCT FROM NEW.actor_user_id))
        OR (NEW.type='TRANSFER' AND (s IS DISTINCT FROM NEW.actor_user_id OR s=r))
        OR (NEW.type IN ('MOBILE_RECHARGE','BILL_PAYMENT') AND s IS DISTINCT FROM NEW.actor_user_id)
        OR (NEW.type='DEMO_FUNDING' AND r IS DISTINCT FROM NEW.actor_user_id)
      THEN RAISE EXCEPTION 'Invalid payment ownership' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE TRIGGER immutable_mobile_recharges BEFORE UPDATE OR DELETE ON mobile_recharges FOR EACH ROW EXECUTE FUNCTION payflow_immutable()")
    op.execute("""CREATE FUNCTION payflow_guard_bill() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Bill history is preserved' USING ERRCODE='23514'; END IF;
      IF OLD.status='PAID' OR ROW(NEW.id,NEW.user_id,NEW.biller_id,NEW.reference,NEW.billing_period,NEW.amount_due,NEW.due_date,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.user_id,OLD.biller_id,OLD.reference,OLD.billing_period,OLD.amount_due,OLD.due_date,OLD.created_at)
      THEN RAISE EXCEPTION 'Bill terms are immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER guard_bill BEFORE UPDATE OR DELETE ON utility_bills FOR EACH ROW EXECUTE FUNCTION payflow_guard_bill()")
    # A successful service payment and exactly one matching fulfillment must coexist at commit.
    op.execute("""CREATE FUNCTION payflow_check_fulfillment() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p payments%ROWTYPE; pid text; n integer;
    BEGIN
      IF TG_TABLE_NAME='payments' THEN pid:=NEW.id; ELSE pid:=NEW.payment_id; END IF;
      IF pid IS NULL THEN RETURN NULL; END IF;
      SELECT * INTO p FROM payments WHERE id=pid;
      IF p.type='MOBILE_RECHARGE' THEN
        SELECT count(*) INTO n FROM mobile_recharges r WHERE r.payment_id=pid AND r.user_id=p.actor_user_id AND r.status='COMPLETED';
      ELSIF p.type='BILL_PAYMENT' THEN
        SELECT count(*) INTO n FROM utility_bills b WHERE b.payment_id=pid AND b.user_id=p.actor_user_id AND b.status='PAID' AND b.amount_due=p.amount;
      ELSE n:=0; END IF;
      IF (p.type IN ('MOBILE_RECHARGE','BILL_PAYMENT') AND p.status='SUCCESS' AND n<>1)
        OR (TG_TABLE_NAME<>'payments' AND (p.status<>'SUCCESS' OR n<>1 OR
          (TG_TABLE_NAME='utility_bills' AND p.type<>'BILL_PAYMENT') OR (TG_TABLE_NAME='mobile_recharges' AND p.type<>'MOBILE_RECHARGE')))
      THEN RAISE EXCEPTION 'Payment and fulfillment must commit together' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    for table in ['payments', 'mobile_recharges', 'utility_bills']:
        op.execute(f"CREATE CONSTRAINT TRIGGER check_fulfillment_{table} AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_fulfillment()")


def downgrade():
    raise RuntimeError("Service and payment history must be preserved; use a reviewed forward migration")
