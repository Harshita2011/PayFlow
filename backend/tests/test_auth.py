from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from sqlalchemy.exc import OperationalError

from config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_SECRET_KEY
from models import User
from security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from test_register import DatabaseTestCase


class AuthenticationTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        response = self.client.post("/register", json=self.payload)
        self.assertEqual(response.status_code, 201)
        self.user_id = response.json()["id"]
        self.credentials = {
            "email": self.payload["email"], "password": self.payload["password"]
        }

    def login(self):
        response = self.client.post("/login", json=self.credentials)
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def assert_unauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertNotIn(self.payload["password"], response.text)
        self.assertNotIn("password_hash", response.text)

    def test_login_issues_signed_short_lived_token(self):
        self.credentials["email"] = self.credentials["email"].upper()
        response = self.client.post("/login", json=self.credentials)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"access_token", "token_type", "expires_in"})
        self.assertEqual(response.json()["token_type"], "bearer")
        self.assertEqual(response.headers["cache-control"], "no-store")
        claims = jwt.decode(
            response.json()["access_token"], JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE, issuer=JWT_ISSUER,
        )
        self.assertEqual(claims["sub"], str(self.user_id))
        self.assertEqual(claims["token_use"], "access")
        self.assertEqual(claims["exp"] - claims["iat"], ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        self.assertNotIn("email", claims)
        self.assertNotIn("password", claims)

    def test_invalid_credentials_use_same_generic_error(self):
        wrong_password = self.client.post(
            "/login", json={**self.credentials, "password": "wrong-password"}
        )
        unknown_email = self.client.post(
            "/login", json={**self.credentials, "email": "unknown@example.com"}
        )
        for response in [wrong_password, unknown_email]:
            self.assert_unauthorized(response)
            self.assertEqual(response.json(), {"detail": "Invalid email or password"})

    def test_invalid_login_input(self):
        for payload in [{}, {**self.credentials, "email": "invalid"},
                        {**self.credentials, "password": ""},
                        {**self.credentials, "password": "x" * 129}]:
            response = self.client.post("/login", json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(self.payload["password"], response.text)

    def test_me_requires_authorization(self):
        self.assert_unauthorized(self.client.get("/me"))
        self.assert_unauthorized(self.client.get("/me", headers={"Authorization": "Basic abc"}))

    def test_me_returns_current_user_only(self):
        token = self.login()
        response = self.client.get("/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.user_id)
        self.assertEqual(set(response.json()), {"id", "full_name", "email", "created_at"})
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_rejects_malformed_and_tampered_tokens(self):
        token = self.login()
        header, payload, signature = token.split(".")
        changed = ("A" if signature[0] != "A" else "B") + signature[1:]
        for invalid in ["not-a-jwt", f"{header}.{payload}.{changed}"]:
            self.assert_unauthorized(self.client.get(
                "/me", headers={"Authorization": f"Bearer {invalid}"}
            ))

    def test_rejects_expired_missing_and_invalid_claims(self):
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(self.user_id), "iat": now, "exp": now + timedelta(minutes=5),
            "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "token_use": "access",
        }
        invalid_claims = [
            {**claims, "iat": now - timedelta(minutes=10), "exp": now - timedelta(minutes=5)},
            {**claims, "iss": "other-service"}, {**claims, "aud": "other-app"},
            {**claims, "token_use": "refresh"}, {**claims, "sub": "not-an-id"},
            {**claims, "sub": "0"}, {**claims, "sub": "9" * 100},
            {**claims, "sub": 1}, {**claims, "iat": now + timedelta(hours=1)},
            {**claims, "exp": "invalid"},
        ]
        invalid_claims.extend(
            {key: value for key, value in claims.items() if key != missing}
            for missing in claims
        )
        for invalid in invalid_claims:
            with self.subTest(claims=list(invalid)):
                token = jwt.encode(invalid, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
                self.assert_unauthorized(self.client.get(
                    "/me", headers={"Authorization": f"Bearer {token}"}
                ))

    def test_wrong_signing_key_or_algorithm_is_rejected(self):
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(self.user_id), "iat": now, "exp": now + timedelta(minutes=5),
            "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "token_use": "access",
        }
        for key, algorithm in [("a-different-key-with-at-least-32-bytes", "HS256"),
                               (JWT_SECRET_KEY, "HS384")]:
            token = jwt.encode(claims, key, algorithm=algorithm)
            self.assert_unauthorized(self.client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            ))

    def test_nonexistent_user_is_rejected(self):
        token = self.login()
        with patch.object(self.db, "get", return_value=None):
            self.assert_unauthorized(self.client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            ))

    def test_corrupt_stored_hash_is_not_exposed(self):
        user = self.db.get(User, self.user_id)
        user.password_hash = "unusable-hash"
        self.db.flush()
        self.assert_unauthorized(self.client.post("/login", json=self.credentials))

    def test_database_failures_return_safe_errors(self):
        error = OperationalError("SELECT", {}, Exception("sensitive details"))
        with patch.object(self.db, "scalar", side_effect=error):
            for endpoint, body in [("/login", self.credentials), ("/register", self.payload)]:
                response = self.client.post(endpoint, json=body)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Database unavailable"})

    def test_cors_allows_local_auth_requests_only(self):
        headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "content-type,authorization"}
        response = self.client.options("/login", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        response = self.client.options("/login", headers={**headers, "Origin": "https://other.example"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)
