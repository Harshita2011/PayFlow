"""Add immutable double-entry payments, idempotency, and lookup limits."""
from alembic import op
import sqlalchemy as sa

revision = "0003_payment_engine"
down_revision = "0002_bank_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ledger_accounts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT"), unique=True),
        sa.CheckConstraint("(id = 'demo-funding' AND bank_account_id IS NULL) OR (bank_account_id IS NOT NULL AND id = 'bank-' || CAST(bank_account_id AS TEXT))", name="ck_ledger_account_identity"),
    )
    op.create_table("payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sender_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT")),
        sa.Column("recipient_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT")),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(7), nullable=False),
        sa.Column("sender_upi_id", sa.String(48)),
        sa.Column("recipient_upi_id", sa.String(48)),
        sa.Column("sender_name", sa.String(100), nullable=False),
        sa.Column("recipient_name", sa.String(100), nullable=False),
        sa.Column("note", sa.String(140), nullable=False),
        sa.Column("failure_reason", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("amount > 0 AND amount <= 9999999999999999.99", name="ck_payment_amount"),
        sa.CheckConstraint("currency = 'INR'", name="ck_payment_currency"),
        sa.CheckConstraint("type IN ('TRANSFER', 'DEMO_FUNDING')", name="ck_payment_type"),
        sa.CheckConstraint("status IN ('SUCCESS', 'FAILED')", name="ck_payment_status"),
        sa.CheckConstraint("status = 'FAILED' OR (recipient_account_id IS NOT NULL AND ((type = 'DEMO_FUNDING' AND sender_account_id IS NULL) OR (type = 'TRANSFER' AND sender_account_id IS NOT NULL AND sender_account_id <> recipient_account_id)))", name="ck_payment_participants"),
    )
    op.create_index("ix_payments_actor_user_id", "payments", ["actor_user_id"])
    op.create_index("ix_payments_sender_history", "payments", ["sender_account_id", "created_at", "id"])
    op.create_index("ix_payments_recipient_history", "payments", ["recipient_account_id", "created_at", "id"])
    op.create_table("ledger_entries",
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("ledger_account_id", sa.String(48), sa.ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("amount <> 0 AND amount >= -9999999999999999.99 AND amount <= 9999999999999999.99", name="ck_ledger_entry_amount"),
    )
    op.create_index("ix_ledger_entries_ledger_account_id", "ledger_entries", ["ledger_account_id"])
    op.create_table("payment_requests",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("key", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id", ondelete="RESTRICT"), unique=True),
        sa.Column("http_status", sa.Integer()),
        sa.Column("response_body", sa.JSON()),
        sa.CheckConstraint("length(fingerprint) = 64 AND (http_status IS NULL OR http_status BETWEEN 200 AND 599)", name="ck_payment_request_result"),
    )
    op.create_table("recipient_lookup_limits",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO ledger_accounts(id) VALUES ('demo-funding')")
    op.execute("INSERT INTO ledger_accounts(id, bank_account_id) SELECT 'bank-' || id, id FROM bank_accounts")
    # Preserve any pre-engine balances via explicit, balanced opening postings.
    op.execute("""INSERT INTO payments(id, actor_user_id, recipient_account_id, amount, currency, type, status,
        recipient_upi_id, sender_name, recipient_name, note)
        SELECT gen_random_uuid()::text, a.user_id, a.id, a.balance, 'INR', 'DEMO_FUNDING', 'SUCCESS',
        a.upi_id, 'PayFlow demo funding', u.full_name, 'Phase 3 opening balance'
        FROM bank_accounts a JOIN users u ON u.id=a.user_id WHERE a.balance > 0""")
    op.execute("""INSERT INTO ledger_entries(payment_id, ledger_account_id, amount)
        SELECT id, 'demo-funding', -amount FROM payments
        UNION ALL SELECT id, 'bank-' || recipient_account_id, amount FROM payments""")
    install_triggers()


def install_triggers():
    op.execute("""CREATE FUNCTION payflow_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Posted financial records are immutable' USING ERRCODE='23514'; END $$""")
    for table in ["payments", "ledger_entries", "ledger_accounts"]:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION payflow_immutable()")
    op.execute("""CREATE FUNCTION payflow_register_account() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN INSERT INTO ledger_accounts(id, bank_account_id) VALUES ('bank-' || NEW.id, NEW.id); RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER register_ledger_account AFTER INSERT ON bank_accounts FOR EACH ROW EXECUTE FUNCTION payflow_register_account()")
    op.execute("""CREATE FUNCTION payflow_check_posting() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p payments%ROWTYPE; n integer; net numeric; debits integer; credits integer; pid text;
    BEGIN
      IF TG_TABLE_NAME='payments' THEN pid:=NEW.id; ELSE pid:=NEW.payment_id; END IF;
      SELECT * INTO p FROM payments WHERE id=pid;
      SELECT count(*), coalesce(sum(amount),0),
        count(*) FILTER (WHERE amount=-p.amount AND ledger_account_id=CASE WHEN p.type='DEMO_FUNDING' THEN 'demo-funding' ELSE 'bank-' || p.sender_account_id END),
        count(*) FILTER (WHERE amount=p.amount AND ledger_account_id='bank-' || p.recipient_account_id)
        INTO n,net,debits,credits FROM ledger_entries WHERE payment_id=pid;
      IF (p.status='SUCCESS' AND (n<>2 OR net<>0 OR debits<>1 OR credits<>1)) OR (p.status='FAILED' AND n<>0) THEN
        RAISE EXCEPTION 'Invalid double-entry posting' USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $$""")
    for table in ["payments", "ledger_entries"]:
        op.execute(f"CREATE CONSTRAINT TRIGGER check_posting_{table} AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_posting()")
    op.execute("""CREATE FUNCTION payflow_check_balance() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE aid integer; cached numeric; journal numeric;
    BEGIN
      IF TG_TABLE_NAME='bank_accounts' THEN aid:=NEW.id;
      ELSE SELECT bank_account_id INTO aid FROM ledger_accounts WHERE id=NEW.ledger_account_id; END IF;
      IF aid IS NULL THEN RETURN NULL; END IF;
      SELECT balance INTO cached FROM bank_accounts WHERE id=aid;
      SELECT coalesce(sum(e.amount),0) INTO journal FROM ledger_entries e JOIN ledger_accounts l ON l.id=e.ledger_account_id WHERE l.bank_account_id=aid;
      IF cached<>journal THEN RAISE EXCEPTION 'Balance does not reconcile with ledger' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER check_bank_balance AFTER INSERT OR UPDATE ON bank_accounts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_balance()")
    op.execute("CREATE CONSTRAINT TRIGGER check_entry_balance AFTER INSERT ON ledger_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_balance()")
    op.execute("""CREATE FUNCTION payflow_guard_request() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.response_body IS NOT NULL OR TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Completed payment requests are immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER guard_request BEFORE UPDATE OR DELETE ON payment_requests FOR EACH ROW EXECUTE FUNCTION payflow_guard_request()")
    op.execute("""CREATE FUNCTION payflow_check_request() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r payment_requests%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM payment_requests WHERE user_id=NEW.user_id AND key=NEW.key;
      IF r.response_body IS NULL OR r.http_status IS NULL THEN
        RAISE EXCEPTION 'Unfinished payment request' USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER complete_request AFTER INSERT ON payment_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_request()")


def downgrade():
    raise RuntimeError("Financial history must be preserved; use a reviewed forward migration")
