"""Add expense obligations and pin request destinations; preserve all old rows."""
from alembic import op
import sqlalchemy as sa

revision = "0005_expense_splits"
down_revision = "0004_contacts_money_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("money_request_destinations",
        sa.Column("request_id", sa.String(36), sa.ForeignKey("money_requests.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False))
    op.execute("""INSERT INTO money_request_destinations(request_id,account_id)
        SELECT r.id,a.id FROM money_requests r JOIN bank_accounts a ON a.user_id=r.requester_user_id""")
    op.create_table("expense_splits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("creator_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("destination_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(80), nullable=False), sa.Column("description", sa.String(240), nullable=False),
        sa.Column("total_amount", sa.Numeric(18,2), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expense_model", sa.String(20), nullable=False), sa.Column("status", sa.String(9), nullable=False),
        sa.Column("creation_key", sa.String(36), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("creator_user_id", "creation_key", name="uq_split_creation"),
        sa.CheckConstraint("total_amount > 0 AND total_amount <= 100000.00", name="ck_split_total"),
        sa.CheckConstraint("currency='INR' AND expense_model='EXTERNAL_RECORD'", name="ck_split_currency_model"),
        sa.CheckConstraint("status IN ('OPEN','SETTLED','CANCELLED')", name="ck_split_status"),
        sa.CheckConstraint("length(fingerprint)=64", name="ck_split_fingerprint"))
    op.create_index("ix_splits_creator", "expense_splits", ["creator_user_id", "created_at", "id"])
    op.create_table("expense_split_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("split_id", sa.String(36), sa.ForeignKey("expense_splits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("share_amount", sa.Numeric(18,2), nullable=False),
        sa.Column("current_request_id", sa.String(36), sa.ForeignKey("money_requests.id", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("split_id", "user_id", name="uq_split_user"),
        sa.CheckConstraint("share_amount > 0 AND share_amount <= 100000.00", name="ck_split_share"))
    op.create_index("ix_split_participant_user", "expense_split_participants", ["user_id", "split_id"])
    op.create_table("split_request_links",
        sa.Column("request_id", sa.String(36), sa.ForeignKey("money_requests.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("participant_id", sa.String(36), sa.ForeignKey("expense_split_participants.id", ondelete="RESTRICT"), nullable=False))
    op.create_index("ix_split_request_links_participant_id", "split_request_links", ["participant_id"])
    for table in ["money_request_destinations", "split_request_links"]:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION payflow_immutable()")
    op.execute("""CREATE OR REPLACE FUNCTION payflow_check_money_request() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r money_requests%ROWTYPE; aid integer;
    BEGIN
      SELECT * INTO r FROM money_requests WHERE id=NEW.id;
      SELECT d.account_id INTO aid FROM money_request_destinations d JOIN bank_accounts a ON a.id=d.account_id
        WHERE d.request_id=r.id AND a.user_id=r.requester_user_id;
      IF aid IS NULL THEN RAISE EXCEPTION 'Request needs its owned pinned destination' USING ERRCODE='23514'; END IF;
      IF r.status='PAID' AND NOT EXISTS (
        SELECT 1 FROM payments p JOIN bank_accounts s ON s.id=p.sender_account_id
        WHERE p.id=r.payment_id AND p.status='SUCCESS' AND p.type='TRANSFER'
          AND p.actor_user_id=r.payer_user_id AND s.user_id=r.payer_user_id
          AND p.recipient_account_id=aid AND p.amount=r.amount AND p.note=r.note
          AND p.created_at >= r.created_at AND p.created_at < r.expires_at
      ) THEN RAISE EXCEPTION 'Request must link its exact transfer' USING ERRCODE='23514'; END IF;
      RETURN NULL;
    END $$""")
    op.execute("""CREATE FUNCTION payflow_guard_split() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Expense history is retained' USING ERRCODE='23514'; END IF;
      IF TG_TABLE_NAME='expense_splits' THEN
        IF OLD.status<>'OPEN' OR ROW(NEW.id,NEW.creator_user_id,NEW.destination_account_id,NEW.title,NEW.description,NEW.total_amount,NEW.currency,NEW.expense_model,NEW.creation_key,NEW.fingerprint,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.creator_user_id,OLD.destination_account_id,OLD.title,OLD.description,OLD.total_amount,OLD.currency,OLD.expense_model,OLD.creation_key,OLD.fingerprint,OLD.created_at)
        THEN RAISE EXCEPTION 'Expense terms are immutable' USING ERRCODE='23514'; END IF;
      ELSE
        IF ROW(NEW.id,NEW.split_id,NEW.user_id,NEW.share_amount,NEW.created_at) IS DISTINCT FROM ROW(OLD.id,OLD.split_id,OLD.user_id,OLD.share_amount,OLD.created_at)
        OR EXISTS(SELECT 1 FROM money_requests WHERE id=OLD.current_request_id AND status IN ('PENDING','PAID'))
        THEN RAISE EXCEPTION 'Share cannot change or duplicate a live obligation' USING ERRCODE='23514'; END IF;
      END IF;
      RETURN NEW;
    END $$""")
    for table in ["expense_splits", "expense_split_participants"]:
        op.execute(f"CREATE TRIGGER guard_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION payflow_guard_split()")
    op.execute("""CREATE FUNCTION payflow_validate_split(sid text) RETURNS void LANGUAGE plpgsql AS $$
    DECLARE s expense_splits%ROWTYPE; n integer; total numeric; owed integer; paid integer;
    BEGIN
      SELECT * INTO s FROM expense_splits WHERE id=sid;
      IF NOT FOUND THEN RETURN; END IF;
      SELECT count(*),coalesce(sum(share_amount),0),count(*) FILTER(WHERE p.user_id<>s.creator_user_id),
        count(*) FILTER(WHERE p.user_id<>s.creator_user_id AND r.status='PAID') INTO n,total,owed,paid
        FROM expense_split_participants p LEFT JOIN money_requests r ON r.id=p.current_request_id WHERE p.split_id=sid;
      IF n>10 OR owed<1 OR total<>s.total_amount OR
        NOT EXISTS(SELECT 1 FROM bank_accounts WHERE id=s.destination_account_id AND user_id=s.creator_user_id) OR
        EXISTS(SELECT 1 FROM expense_split_participants p LEFT JOIN money_requests r ON r.id=p.current_request_id
          LEFT JOIN money_request_destinations d ON d.request_id=r.id
          LEFT JOIN split_request_links l ON l.request_id=r.id AND l.participant_id=p.id WHERE p.split_id=sid AND
          ((p.user_id=s.creator_user_id AND p.current_request_id IS NOT NULL) OR
           (p.user_id<>s.creator_user_id AND (r.id IS NULL OR l.request_id IS NULL OR r.payer_user_id<>p.user_id OR
            r.requester_user_id<>s.creator_user_id OR r.amount<>p.share_amount OR d.account_id<>s.destination_account_id)))) OR
        EXISTS(SELECT 1 FROM split_request_links l JOIN expense_split_participants p ON p.id=l.participant_id
          JOIN money_requests r ON r.id=l.request_id WHERE p.split_id=sid AND l.request_id<>p.current_request_id AND r.status IN ('PENDING','PAID')) OR
        (s.status='SETTLED' AND paid<>owed) OR (s.status='OPEN' AND paid=owed) OR
        (s.status='CANCELLED' AND (paid>0 OR EXISTS(SELECT 1 FROM expense_split_participants p JOIN money_requests r ON r.id=p.current_request_id WHERE p.split_id=sid AND r.status='PENDING')))
      THEN RAISE EXCEPTION 'Invalid expense shares, request links or settlement' USING ERRCODE='23514'; END IF;
    END $$""")
    op.execute("""CREATE FUNCTION payflow_check_split() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE sid text;
    BEGIN
      IF TG_TABLE_NAME='expense_splits' THEN sid:=NEW.id;
      ELSIF TG_TABLE_NAME='expense_split_participants' THEN sid:=NEW.split_id;
      ELSIF TG_TABLE_NAME='split_request_links' THEN SELECT split_id INTO sid FROM expense_split_participants WHERE id=NEW.participant_id;
      ELSE SELECT p.split_id INTO sid FROM split_request_links l JOIN expense_split_participants p ON p.id=l.participant_id WHERE l.request_id=NEW.id; END IF;
      IF sid IS NOT NULL THEN PERFORM payflow_validate_split(sid); END IF;
      RETURN NULL;
    END $$""")
    for table in ["expense_splits", "expense_split_participants", "split_request_links", "money_requests"]:
        op.execute(f"CREATE CONSTRAINT TRIGGER check_split_{table} AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION payflow_check_split()")


def downgrade():
    raise RuntimeError("Preserve expense and request history; use a reviewed forward migration")
