from decimal import Decimal
import os
import re
import unittest
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError, OperationalError

from models import BankAccount, DemoBank, User
from security import create_access_token
from test_register import DatabaseTestCase


class AccountTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        response = self.client.post("/register", json=self.payload)
        self.assertEqual(response.status_code, 201)
        self.user_id = response.json()["id"]
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user_id)}"}
        self.body = {"bank_name": DemoBank.GROVE.value}

    def create(self, **kwargs):
        return self.client.post("/accounts", json=self.body, headers=self.headers, **kwargs)

    def other_user(self):
        user = User(full_name="Other Learner", email="other-" + self.payload["email"], password_hash="test-only-hash")
        self.db.add(user)
        self.db.flush()
        return user

    def test_create_zero_balance_masked_account_and_upi(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(set(data), {"id", "bank_name", "masked_account_number", "upi_id", "balance", "created_at", "is_primary"})
        account = self.db.get(BankAccount, data["id"])
        self.assertEqual(account.user_id, self.user_id)
        self.assertEqual(account.balance, Decimal("0.00"))
        self.assertIsInstance(account.balance, Decimal)
        self.assertEqual(data["balance"], "0.00")
        self.assertRegex(account.account_number, r"^SIM\d{16}$")
        self.assertNotIn(account.account_number, response.text)
        self.assertTrue(data["masked_account_number"].endswith(account.account_number[-4:]))
        self.assertRegex(data["upi_id"], r"^[a-z0-9][a-z0-9-]{0,39}@payflow$")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_endpoints_require_authentication(self):
        for headers in [{}, {"Authorization": "Bearer invalid"}]:
            for method, endpoint in [("GET", "/accounts"), ("GET", "/accounts/1"), ("GET", "/accounts/banks"), ("POST", "/accounts")]:
                response = self.client.request(method, endpoint, headers=headers, json=self.body if method == "POST" else None)
                self.assertEqual(response.status_code, 401)

    def test_list_empty_and_owner_only_detail(self):
        self.assertEqual(self.client.get("/accounts", headers=self.headers).json(), [])
        created = self.create().json()
        self.assertEqual(self.client.get("/accounts", headers=self.headers).json(), [created])
        self.assertEqual(self.client.get(f"/accounts/{created['id']}", headers=self.headers).json(), created)
        other = self.other_user()
        other_headers = {"Authorization": f"Bearer {create_access_token(other.id)}"}
        self.assertEqual(self.client.get("/accounts", headers=other_headers).json(), [])
        response = self.client.get(f"/accounts/{created['id']}", headers=other_headers)
        self.assertEqual(response.status_code, 404)
        missing = self.client.get("/accounts/2147483647", headers=other_headers)
        self.assertEqual(response.json(), missing.json())

    def test_multiple_accounts_are_bounded_and_first_is_primary(self):
        for index in range(4):
            result = self.create()
            self.assertEqual(result.status_code, 201)
            self.assertEqual(result.json()["is_primary"], index == 0)
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(len(self.client.get("/accounts", headers=self.headers).json()), 4)

    def test_client_cannot_supply_private_fields_or_invalid_bank(self):
        for extra in [{"user_id": 999}, {"balance": "1000.00"}, {"account_number": "SIM123"}, {"upi_id": "claimed@payflow"}, {"bank_name": "Real Bank"}, {}]:
            body = {**self.body, **extra} if extra else {}
            response = self.client.post("/accounts", json=body, headers=self.headers)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/accounts", headers=self.headers).json(), [])
        self.assertEqual(self.client.get("/accounts/banks", headers=self.headers).json(), [bank.value for bank in DemoBank])

    def test_identifiers_are_unique_for_different_users(self):
        first = self.create().json()
        other = self.other_user()
        second = self.client.post("/accounts", json=self.body, headers={"Authorization": f"Bearer {create_access_token(other.id)}"})
        self.assertEqual(second.status_code, 201)
        a, b = self.db.get(BankAccount, first["id"]), self.db.get(BankAccount, second.json()["id"])
        self.assertNotEqual(a.account_number, b.account_number)
        self.assertNotEqual(a.upi_id, b.upi_id)

    def test_balance_serializes_as_exact_decimal_string(self):
        account = self.db.get(BankAccount, self.create().json()["id"])
        # Test-only fixture change, not a funding endpoint. PostgreSQL rollback isolates it.
        account.balance = Decimal("12345678901234.56")
        self.db.flush()
        response = self.client.get("/accounts", headers=self.headers)
        self.assertEqual(response.json()[0]["balance"], "12345678901234.56")

    def test_upi_generation_handles_non_ascii_names(self):
        from accounts import generate_upi_id
        for name in ["東京", "  Éva / Doe!  ", "A" * 100, "---"]:
            self.assertIsNotNone(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}@payflow", generate_upi_id(name)))

    def test_constraints_block_invalid_rows(self):
        created = self.create().json()
        account = self.db.get(BankAccount, created["id"])
        other = self.other_user()
        base = dict(user_id=other.id, bank_name=DemoBank.RIVER.value, account_number="SIM9876543210123456", upi_id="constraint-test@payflow", balance=Decimal("0.00"))
        for change in [{"user_id": self.user_id, "is_primary": True}, {"account_number": account.account_number}, {"upi_id": account.upi_id}, {"balance": Decimal("-0.01")}, {"bank_name": "Invalid"}, {"user_id": 2147483647}, {"bank_name": None}]:
            with self.subTest(field=list(change)):
                with self.assertRaises(IntegrityError):
                    with self.db.begin_nested():
                        self.db.execute(BankAccount.__table__.insert().values(**{**base, **change}))

    @unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "PostgreSQL constraints")
    def test_postgres_format_and_nan_constraints(self):
        base = dict(user_id=self.user_id, bank_name=DemoBank.RIVER.value, account_number="SIM9876543210123456", upi_id="constraint-test@payflow", balance=Decimal("0.00"))
        for change in [{"account_number": "real-account-number"}, {"upi_id": "Bad ID@payflow"}, {"balance": Decimal("NaN")}]:
            with self.subTest(field=list(change)):
                with self.assertRaises(IntegrityError):
                    with self.db.begin_nested():
                        self.db.execute(BankAccount.__table__.insert().values(**{**base, **change}))

    def test_database_errors_are_safe(self):
        error = OperationalError("SELECT", {}, Exception("private database details"))
        with patch.object(self.db, "scalar", side_effect=error):
            response = self.create()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Database unavailable"})

    def test_generated_identifier_collisions_are_retried(self):
        first = self.db.get(BankAccount, self.create().json()["id"])
        other = self.other_user()
        headers = {"Authorization": f"Bearer {create_access_token(other.id)}"}
        with patch("accounts.generate_account_number", side_effect=[first.account_number, "SIM1122334455667788", "SIM1122334455667788"]), patch(
            "accounts.generate_upi_id", side_effect=["new-id@payflow", first.upi_id, "other-id@payflow"]
        ):
            response = self.client.post("/accounts", json=self.body, headers=headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["upi_id"], "other-id@payflow")

    def test_collision_retry_limit_returns_safe_error(self):
        first = self.db.get(BankAccount, self.create().json()["id"])
        other = self.other_user()
        with patch("accounts.generate_account_number", return_value=first.account_number):
            response = self.client.post("/accounts", json=self.body, headers={"Authorization": f"Bearer {create_access_token(other.id)}"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(first.account_number, response.text)

    @unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "PostgreSQL unique constraint")
    def test_duplicate_primary_is_rejected_by_database(self):
        self.create()
        with self.assertRaises(IntegrityError), self.db.begin_nested():
            self.db.execute(BankAccount.__table__.insert().values(user_id=self.user_id, bank_name=DemoBank.RIVER.value,
                account_number="SIM9999888877776666", upi_id="duplicate-primary@payflow", is_primary=True))
