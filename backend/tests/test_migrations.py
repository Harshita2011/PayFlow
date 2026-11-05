import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from config import DATABASE_URL
from models import User


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Requires PostgreSQL")
class MigrationTests(unittest.TestCase):
    def setUp(self):
        from payment_support import PaymentDatabaseTestCase
        PaymentDatabaseTestCase.setUpClass()
        self.engine = create_engine(PaymentDatabaseTestCase.test_url, connect_args={"connect_timeout": 5})
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.schema = "phase3_test_" + uuid4().hex
        self.connection.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.connection.exec_driver_sql(f'SET LOCAL search_path TO "{self.schema}"')
        self.config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        self.config.attributes["connection"] = self.connection

    def tearDown(self):
        # The new schema and all test rows disappear by rolling back their creation.
        self.transaction.rollback()
        self.connection.close()
        self.engine.dispose()

    def test_fresh_database_and_repeat_upgrade(self):
        command.upgrade(self.config, "head")
        command.upgrade(self.config, "head")
        inspector = inspect(self.connection)
        self.assertEqual(set(inspector.get_table_names()), {"users", "bank_accounts", "alembic_version", "ledger_accounts", "payments", "ledger_entries", "payment_requests", "recipient_lookup_limits", "contacts", "money_requests", "request_creation_limits", "money_request_destinations", "expense_splits", "expense_split_participants", "split_request_links", "demo_operators", "demo_recharge_plans", "demo_billers", "mobile_recharges", "utility_bills", "saved_billers", "payment_pin_credentials", "payment_authorizations", "payment_limit_counters", "security_rate_windows", "security_audit_events", "fraud_risk_decisions"})
        balance = next(c for c in inspector.get_columns("bank_accounts") if c["name"] == "balance")
        self.assertEqual((balance["type"].precision, balance["type"].scale), (18, 2))
        self.assertEqual(self.connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0008_payment_security")
        command.check(self.config)

    def test_existing_users_are_adopted_without_changes(self):
        User.__table__.create(self.connection)
        self.connection.execute(User.__table__.insert().values(
            full_name="Migration Learner", email="migration@example.com", password_hash="test-only-hash"
        ))
        before = self.connection.execute(User.__table__.select()).all()
        command.upgrade(self.config, "head")
        after = self.connection.execute(User.__table__.select()).all()
        self.assertEqual(before, after)
        self.assertTrue(inspect(self.connection).has_table("bank_accounts"))

    def test_legacy_positive_balance_gets_balanced_opening_entries(self):
        command.upgrade(self.config, "0002_bank_accounts")
        self.connection.execute(User.__table__.insert().values(
            full_name="Opening Balance Learner", email="opening@example.com", password_hash="test-only"
        ))
        self.connection.execute(text("""INSERT INTO bank_accounts(user_id,bank_name,account_number,upi_id,balance)
            SELECT id,'Grove Demo Bank','SIM1234567890123456','opening@payflow',12.34 FROM users"""))
        command.upgrade(self.config, "head")
        self.assertEqual(str(self.connection.execute(text("SELECT balance FROM bank_accounts")).scalar_one()), "12.34")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM ledger_entries")).scalar_one(), 2)
        self.assertEqual(self.connection.execute(text("SELECT sum(amount) FROM ledger_entries")).scalar_one(), 0)
        self.assertEqual(self.connection.execute(text("SELECT note FROM payments")).scalar_one(), "Phase 3 opening balance")

    def test_phase7_financial_rows_and_paid_request_are_preserved(self):
        command.upgrade(self.config, "0004_contacts_money_requests")
        for index in [1, 2]:
            self.connection.execute(text("INSERT INTO users(id,full_name,email,password_hash,created_at) VALUES (:id,'Legacy Learner',:email,'unchanged-hash',CURRENT_TIMESTAMP)"), {"id": index, "email": f"legacy{index}@example.com"})
            self.connection.execute(text("INSERT INTO bank_accounts(id,user_id,bank_name,account_number,upi_id,balance) VALUES (:id,:id,'Grove Demo Bank',:number,:upi,0)"), {"id": index, "number": "SIM"+str(index).zfill(16), "upi": f"legacy{index}@payflow"})
        self.connection.execute(text("""INSERT INTO payments(id,actor_user_id,sender_account_id,recipient_account_id,amount,currency,type,status,sender_name,recipient_name,note)
            VALUES ('legacy-fund',2,NULL,2,100,'INR','DEMO_FUNDING','SUCCESS','System','Legacy Learner','Demo'),
            ('legacy-transfer',2,2,1,12.34,'INR','TRANSFER','SUCCESS','Legacy Learner','Legacy Learner','Lunch')"""))
        self.connection.execute(text("""INSERT INTO ledger_entries(payment_id,ledger_account_id,amount) VALUES
            ('legacy-fund','demo-funding',-100),('legacy-fund','bank-2',100),
            ('legacy-transfer','bank-2',-12.34),('legacy-transfer','bank-1',12.34)"""))
        self.connection.execute(text("UPDATE bank_accounts SET balance=CASE WHEN id=1 THEN 12.34 ELSE 87.66 END"))
        self.connection.execute(text("""INSERT INTO money_requests(id,requester_user_id,payer_user_id,amount,note,status,payment_id,creation_key,fingerprint,expires_at)
            VALUES ('legacy-request',1,2,12.34,'Lunch','PAID','legacy-transfer','legacy-key',repeat('a',64),CURRENT_TIMESTAMP+interval '7 days')"""))
        names = ["users", "bank_accounts", "payments", "ledger_entries", "money_requests"]
        def snapshot():
            return {name: sorted(self.connection.execute(text(f"SELECT (to_jsonb(t)-'is_primary'-'settlement_ledger_account_id'-'channel')::text FROM {name} t")).scalars()) for name in names}
        before = snapshot()
        command.upgrade(self.config, "head")
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.connection.execute(text("SELECT account_id FROM money_request_destinations WHERE request_id='legacy-request'")).scalar_one(), 1)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM bank_accounts WHERE is_primary")).scalar_one(), 2)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM payment_pin_credentials")).scalar_one(), 0)
        # The first daily counter includes pre-security outgoing history, not only new postings.
        from sqlalchemy.orm import Session
        from payment_policy import daily_usage
        from security_events import clock
        from accounts import lock_account_config
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as db:
            lock_account_config(db, 2)
            usage = daily_usage(db, 2, clock(db))
            self.assertEqual(str(usage.amount), "12.34")
            self.assertEqual(usage.transaction_count, 1)
