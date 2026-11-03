import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.errors import NotNullViolation, UniqueViolation
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config import DATABASE_URL
from database import get_db
from main import app, password_hasher
from models import User


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        # PostgreSQL mode uses an outer transaction: test rows are never committed.
        self.postgres = os.getenv("REGISTER_TEST_POSTGRES") == "1"
        if self.postgres:
            self.engine = create_engine(
                DATABASE_URL, connect_args={"connect_timeout": 5}
            )
            self.connection = self.engine.connect()
            self.transaction = self.connection.begin()
            self.db = Session(
                bind=self.connection, join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
        else:
            self.engine = create_engine(
                "sqlite://", connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            User.__table__.create(self.engine)
            self.db = Session(self.engine, expire_on_commit=False)

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.payload = {
            "full_name": "  Test User  ",
            "email": f"registration-{uuid4().hex}@example.com",
            "password": "Learning-PayFlow-2026!",
        }

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.db.close()
        if self.postgres:
            self.transaction.rollback()
            self.connection.close()
        self.engine.dispose()


class RegistrationTests(DatabaseTestCase):
    def test_registration_stores_hash_and_returns_only_public_fields(self):
        response = self.client.post("/register", json=self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.json()), {"id", "full_name", "email", "created_at"}
        )
        self.assertEqual(response.json()["full_name"], "Test User")
        user = self.db.scalar(select(User).where(User.email == self.payload["email"]))
        self.assertTrue(user.password_hash.startswith("$argon2id$"))
        self.assertTrue(password_hasher.verify(self.payload["password"], user.password_hash))
        self.assertNotIn(self.payload["password"], response.text)
        self.assertNotIn(user.password_hash, response.text)

    def test_password_hashes_use_different_salts(self):
        first = self.client.post("/register", json=self.payload)
        self.payload["email"] = f"registration-{uuid4().hex}@example.com"
        second = self.client.post("/register", json=self.payload)
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertNotEqual(
            self.db.get(User, first.json()["id"]).password_hash,
            self.db.get(User, second.json()["id"]).password_hash,
        )

    def test_duplicate_email_is_case_insensitive(self):
        self.assertEqual(self.client.post("/register", json=self.payload).status_code, 201)
        self.payload["email"] = self.payload["email"].upper()
        response = self.client.post("/register", json=self.payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_email_is_saved_in_lowercase(self):
        self.payload["email"] = self.payload["email"].upper()
        response = self.client.post("/register", json=self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], self.payload["email"].lower())

    def test_invalid_fields_never_echo_input(self):
        cases = [
            ("full_name", "   "), ("full_name", "x" * 101),
            ("email", "invalid-email"), ("email", "x" * 256 + "@example.com"),
            ("password", "short"), ("password", "x" * 129),
            ("password", None), ("password", 12345678),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                payload = {**self.payload, field: value}
                response = self.client.post("/register", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(self.payload["password"], response.text)
                for error in response.json()["detail"]:
                    self.assertEqual(set(error), {"type", "loc", "msg"})

    def test_missing_fields_and_extra_fields_are_rejected(self):
        for field in self.payload:
            payload = {key: value for key, value in self.payload.items() if key != field}
            self.assertEqual(self.client.post("/register", json=payload).status_code, 422)
        response = self.client.post(
            "/register", json={**self.payload, "password_hash": "client-controlled"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("client-controlled", response.text)

    def test_malformed_json_does_not_echo_password(self):
        response = self.client.post(
            "/register", content='{"password":"sensitive-password",',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("sensitive-password", response.text)

    def test_concurrent_duplicate_error_rolls_back(self):
        error = IntegrityError("INSERT", {}, UniqueViolation())
        with patch.object(self.db, "commit", side_effect=error), patch.object(
            self.db, "rollback", wraps=self.db.rollback
        ) as rollback:
            response = self.client.post("/register", json=self.payload)
            self.assertEqual(response.status_code, 409)
            rollback.assert_called_once()
        self.assertEqual(self.client.post("/register", json=self.payload).status_code, 201)

    def test_other_constraint_errors_are_not_reported_as_duplicates(self):
        error = IntegrityError("INSERT", {}, NotNullViolation())
        with patch.object(self.db, "commit", side_effect=error), patch.object(
            self.db, "rollback", wraps=self.db.rollback
        ) as rollback:
            response = self.client.post("/register", json=self.payload)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"detail": "Database unavailable"})
            rollback.assert_called_once()

    @unittest.skipUnless(
        os.getenv("REGISTER_TEST_POSTGRES") == "1", "Requires PostgreSQL test mode"
    )
    def test_postgres_unique_constraint_catches_duplicate_after_precheck(self):
        self.assertEqual(self.client.post("/register", json=self.payload).status_code, 201)
        # Simulate another request inserting the email after the initial lookup.
        with patch.object(self.db, "scalar", return_value=None):
            response = self.client.post("/register", json=self.payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_docs_and_existing_endpoints(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/health").json(), {"status": "healthy"})
        self.assertEqual(self.client.get("/").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("201", schema["paths"]["/register"]["post"]["responses"])
        self.assertEqual(
            set(schema["components"]["schemas"]["UserResponse"]["properties"]),
            {"id", "full_name", "email", "created_at"},
        )


if __name__ == "__main__":
    unittest.main()
