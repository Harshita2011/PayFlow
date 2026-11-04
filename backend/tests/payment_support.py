"""Real commits and independent sessions in a separate test database, never development data."""
from pathlib import Path
from uuid import uuid4
import unittest

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from config import DATABASE_URL
from database import get_db
from main import app
from models import BankAccount, DemoBank, User
from security import create_access_token


class PaymentDatabaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = make_url(DATABASE_URL)
        cls.test_url = source.set(database="payflow_phase4_tests")
        if source.database == cls.test_url.database:
            raise RuntimeError("Development DATABASE_URL must not point at the dedicated payment test database")
        admin = create_engine(source, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
        with admin.connect() as connection:
            if not connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": cls.test_url.database}).scalar():
                connection.exec_driver_sql('CREATE DATABASE "payflow_phase4_tests"')
        admin.dispose()

    def setUp(self):
        self.schema = "payment_test_" + uuid4().hex
        admin = create_engine(self.test_url, connect_args={"connect_timeout": 5})
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        admin.dispose()
        self.engine = create_engine(self.test_url, connect_args={
            "connect_timeout": 5, "options": f"-csearch_path={self.schema}",
        })
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        def override_db():
            with Session(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.accounts = []
        self.headers = []
        with Session(self.engine) as db:
            for index in range(3):
                user = User(full_name=f"Payment Learner {index}", email=f"learner{index}@example.com", password_hash="test-only")
                db.add(user)
                db.flush()
                account = BankAccount(user_id=user.id, bank_name=DemoBank.GROVE.value,
                    account_number="SIM" + str(index + 1).zfill(16), upi_id=f"learner-{index}@payflow", is_primary=True)
                db.add(account)
                db.flush()
                self.accounts.append({"id": account.id, "upi_id": account.upi_id, "user_id": user.id})
                self.headers.append({"Authorization": f"Bearer {create_access_token(user.id)}"})
            db.commit()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()
        # No DROP/DELETE/TRUNCATE. Isolated schemas remain in the dedicated test DB.

    def fund(self, user=0, key=None):
        return self.client.post("/demo/fund", json={}, headers={**self.headers[user], "Idempotency-Key": key or str(uuid4())})

    def transfer(self, amount="100.00", sender=0, recipient=1, key=None, **changes):
        body = {"upi_id": self.accounts[recipient]["upi_id"], "amount": amount, "note": "test transfer", **changes}
        return self.client.post("/payments/transfer", json=body, headers={**self.headers[sender], "Idempotency-Key": key or str(uuid4())})

    def balances(self):
        with self.engine.connect() as connection:
            return list(connection.execute(text("SELECT balance FROM bank_accounts ORDER BY id")).scalars())

    def assert_reconciled(self):
        from reconcile import reconcile
        with self.engine.connect() as connection:
            audit = reconcile(connection)
            self.assertTrue(audit["balanced"])
            for key, value in audit.items():
                if key != "balanced":
                    self.assertEqual(value, [], key)
            self.assertEqual(connection.execute(text("SELECT coalesce(sum(amount),0) FROM ledger_entries")).scalar_one(), 0)
            self.assertEqual(connection.execute(text("""SELECT count(*) FROM bank_accounts a WHERE balance <>
                (SELECT coalesce(sum(e.amount),0) FROM ledger_entries e JOIN ledger_accounts l ON l.id=e.ledger_account_id WHERE l.bank_account_id=a.id)""")).scalar_one(), 0)
