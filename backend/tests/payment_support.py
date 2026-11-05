"""Real commits and independent sessions in a separate test database, never development data."""
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import re
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
from security import create_access_token, password_hasher
from security_models import PinCredential
from security_settings import settings


TEST_PIN = "482951"


class PinAwareClient(TestClient):
    """Legacy regressions still exercise real PIN grants; no backend test bypass exists."""
    auto_authorize = True

    def post(self, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        body = kwargs.get("json")
        operation, reference = None, None
        if url == "/payments/transfer": operation = "TRANSFER"
        elif url == "/payments/self-transfer": operation = "SELF_TRANSFER"
        elif url == "/recharge": operation = "MOBILE_RECHARGE"
        elif match := re.fullmatch(r"/payment-requests/([^/]+)/pay", str(url)): operation, reference = "REQUEST", match[1]
        elif match := re.fullmatch(r"/bills/([^/]+)/pay", str(url)): operation, reference = "BILL_PAYMENT", match[1]
        if self.auto_authorize and operation and isinstance(body, dict) and "Authorization" in headers and "Idempotency-Key" in headers and "Payment-Authorization" not in headers:
            command = {"pin": TEST_PIN, "operation": operation, "payload": body}
            if reference: command["reference_id"] = reference
            grant = super().post("/security/payment-authorizations", json=command, headers=headers)
            if grant.status_code == 201:
                kwargs["headers"] = {**headers, "Payment-Authorization": grant.json()["authorization_token"]}
        return super().post(url, **kwargs)


class PaymentDatabaseTestCase(unittest.TestCase):
    auto_authorize = True
    relax_security_limits = True
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
        if self.relax_security_limits:
            relaxed = replace(settings, daily_amount=__import__('decimal').Decimal("1000000000"), daily_count=10000,
                risk_velocity=10000, risk_distinct=10000, risk_large=__import__('decimal').Decimal("1000000000"),
                risk_insufficient=10000, risk_services=10000, risk_new_contact=10000, risk_requests=10000,
                requests_per_day=10000, pin_per_minute=10000, submit_per_minute=10000)
            for module in ["payment_policy", "pin_security", "request_limits"]:
                context = patch(module + ".settings", relaxed)
                context.start()
                self.addCleanup(context.stop)
            context = patch("security_settings.settings", relaxed)
            context.start()
            self.addCleanup(context.stop)
        self.client = PinAwareClient(app)
        self.client.auto_authorize = self.auto_authorize
        self.accounts = []
        self.headers = []
        with Session(self.engine) as db:
            for index in range(3):
                user = User(full_name=f"Payment Learner {index}", email=f"learner{index}@example.com", password_hash="test-only")
                db.add(user)
                db.flush()
                if self.auto_authorize:
                    db.add(PinCredential(user_id=user.id, pin_hash=password_hasher.hash(TEST_PIN)))
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
