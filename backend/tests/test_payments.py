from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import OperationalError
from psycopg.errors import DeadlockDetected, SerializationFailure

from payment_models import LedgerEntry
from payment_support import PaymentDatabaseTestCase


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Payment engine requires PostgreSQL")
class PaymentTests(PaymentDatabaseTestCase):
    def test_funding_and_balanced_system_debit(self):
        response = self.fund()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["amount"], "1000.00")
        self.assertEqual(response.json()["direction"], "FUNDING")
        self.assertEqual(self.balances(), [Decimal("1000.00"), 0, 0])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT amount FROM ledger_entries WHERE ledger_account_id='demo-funding'")).scalar_one(), Decimal("-1000.00"))
        self.assert_reconciled()

    def test_funding_limit_and_replay(self):
        key = str(uuid4())
        first = self.fund(key=key)
        self.assertEqual(self.fund(key=key).json(), first.json())
        self.assertEqual(self.fund().status_code, 201)
        self.assertEqual(self.fund().status_code, 201)
        limited_key = str(uuid4())
        failed = self.fund(key=limited_key)
        self.assertEqual(failed.status_code, 429)
        self.assertEqual(self.fund(key=limited_key).json(), failed.json())
        self.assertEqual(self.balances()[0], Decimal("3000.00"))
        self.assert_reconciled()

    def test_transfer_exact_balances_and_ledger(self):
        self.assertEqual(self.fund().status_code, 201)
        response = self.transfer("12.34")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "SUCCESS")
        self.assertEqual(self.balances(), [Decimal("987.66"), Decimal("12.34"), 0])
        with self.engine.connect() as c:
            values = c.execute(text("SELECT amount FROM ledger_entries WHERE payment_id=:id ORDER BY amount"), {"id": response.json()["transaction_id"]}).scalars().all()
            self.assertEqual(values, [Decimal("-12.34"), Decimal("12.34")])
        self.assert_reconciled()

    def test_insufficient_funds_is_final_for_key(self):
        key = str(uuid4())
        response = self.transfer(key=key)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["receipt"]["status"], "FAILED")
        self.fund()
        self.assertEqual(self.transfer(key=key).json(), response.json())
        self.assertEqual(self.balances(), [1000, 0, 0])
        self.assert_reconciled()

    def test_input_validation_and_private_fields(self):
        for amount in ["0", "-1", "1.001", "1.000", "100000.01", "NaN", "Infinity", "1e2", 1.2, True, None]:
            with self.subTest(amount=amount):
                self.assertEqual(self.transfer(amount).status_code, 422)
        for changes in [{"sender_account_id": 1}, {"balance": "10.00"}, {"upi_id": "invalid"}, {"note": "x"*141}]:
            self.assertEqual(self.transfer(**changes).status_code, 422)
        self.assertEqual(self.client.post("/demo/fund", json={"amount": "999"}, headers={**self.headers[0], "Idempotency-Key": str(uuid4())}).status_code, 422)

    def test_unknown_and_self_recipient(self):
        self.assertEqual(self.transfer(upi_id="missing@payflow").status_code, 404)
        response = self.transfer(recipient=0)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["receipt"]["direction"], "OUTGOING")
        self.assert_reconciled()

    def test_lookup_minimal_fields_and_shared_rate_limit(self):
        response = self.client.post("/payments/resolve", json={"upi_id": self.accounts[1]["upi_id"].upper()}, headers=self.headers[0])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"display_name", "bank_name", "upi_id"})
        self.assertEqual(self.client.post("/payments/resolve", json={"upi_id": self.accounts[0]["upi_id"]}, headers=self.headers[0]).status_code, 400)
        for _ in range(8):
            self.assertEqual(self.client.post("/payments/resolve", json={"upi_id": "missing@payflow"}, headers=self.headers[0]).status_code, 404)
        self.assertEqual(self.client.post("/payments/resolve", json={"upi_id": self.accounts[1]["upi_id"]}, headers=self.headers[0]).status_code, 429)

    def test_authentication_and_required_key(self):
        for method, url, body in [("POST", "/demo/fund", {}), ("POST", "/payments/transfer", {"upi_id":"other@payflow","amount":"1.00"}), ("POST", "/payments/resolve", {"upi_id":"other@payflow"}), ("GET", "/payments/history", None), ("GET", f"/payments/{uuid4()}", None)]:
            self.assertEqual(self.client.request(method, url, json=body).status_code, 401)
        self.assertEqual(self.client.post("/demo/fund", json={}, headers=self.headers[0]).status_code, 422)

    def test_idempotency_replay_conflict_and_scope(self):
        self.fund()
        key = str(uuid4())
        first = self.transfer(key=key)
        self.assertEqual(self.transfer("100", key=key).json(), first.json())
        self.assertEqual(self.transfer("101.00", key=key).status_code, 409)
        self.assertEqual(self.transfer(key=key, note="changed").status_code, 409)
        self.assertEqual(self.fund(key=key).status_code, 409)
        self.assertEqual(self.fund(user=1, key=key).status_code, 201)
        self.assert_reconciled()

    def test_injected_failure_rolls_back_everything_and_allows_same_key_retry(self):
        self.fund()
        key = str(uuid4())
        def fail_after_partial_posting(db, payment):
            db.flush()  # Send BOTH cached balance updates to PostgreSQL first.
            db.add(LedgerEntry(payment_id=payment.id, ledger_account_id=f"bank-{payment.sender_account_id}", amount=-payment.amount))
            db.flush()  # A deliberately incomplete posting must also roll back.
            raise RuntimeError("injected failure after SQL writes")
        with patch("payments.post_ledger", side_effect=fail_after_partial_posting):
            self.assertEqual(self.transfer(key=key).status_code, 503)
        self.assertEqual(self.balances(), [1000, 0, 0])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM payments")).scalar_one(), 1)
            self.assertEqual(c.execute(text("SELECT count(*) FROM payment_requests")).scalar_one(), 1)
        self.assertEqual(self.transfer(key=key).status_code, 201)
        self.assert_reconciled()

    def test_deadlock_and_serialization_failures_allow_same_key_retry(self):
        self.fund()
        for failure in [DeadlockDetected(), SerializationFailure()]:
            key = str(uuid4())
            with patch("payments.post_ledger", side_effect=OperationalError("test", {}, failure)):
                self.assertEqual(self.transfer(key=key).status_code, 503)
            self.assertEqual(self.transfer(key=key).status_code, 201)
        self.assertEqual(self.balances(), [800, 200, 0])
        self.assert_reconciled()

    def parallel(self, functions):
        barrier = threading.Barrier(len(functions))
        def invoke(fn):
            barrier.wait(timeout=10)
            return fn()
        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            return list(executor.map(invoke, functions))

    def test_concurrent_same_key_posts_once(self):
        self.fund()
        key = str(uuid4())
        results = self.parallel([lambda: self.transfer("100.00", key=key) for _ in range(4)])
        self.assertEqual([r.status_code for r in results], [201]*4)
        self.assertEqual(len({r.json()["transaction_id"] for r in results}), 1)
        self.assertEqual(self.balances(), [900, 100, 0])
        self.assert_reconciled()

    def test_concurrent_same_key_different_payload_conflicts(self):
        self.fund()
        key = str(uuid4())
        results = self.parallel([lambda: self.transfer("100.00", key=key), lambda: self.transfer("200.00", key=key)])
        self.assertEqual(sorted(r.status_code for r in results), [201,409])
        self.assertIn(self.balances()[0], [800,900])
        self.assertEqual(sum(self.balances()), 1000)
        self.assert_reconciled()

    def test_concurrent_spending_cannot_overdraw(self):
        self.fund()
        results = self.parallel([lambda: self.transfer("800.00", recipient=1), lambda: self.transfer("800.00", recipient=2)])
        self.assertEqual(sorted(r.status_code for r in results), [201, 400])
        balances = self.balances()
        self.assertEqual(balances[0], 200)
        self.assertEqual(sum(balances), 1000)
        self.assertTrue(all(b >= 0 for b in balances))
        self.assert_reconciled()

    def test_concurrent_funding_enforces_limit(self):
        results = self.parallel([lambda: self.fund() for _ in range(5)])
        self.assertEqual(sorted(r.status_code for r in results), [201,201,201,429,429])
        self.assertEqual(self.balances()[0], 3000)
        self.assert_reconciled()

    def test_opposing_transfers_use_consistent_lock_order(self):
        self.fund(0)
        self.fund(1)
        results = self.parallel([lambda: self.transfer("100.00"), lambda: self.transfer("250.00", sender=1, recipient=0)])
        self.assertEqual([r.status_code for r in results], [201,201])
        self.assertEqual(self.balances(), [1150,850,0])
        self.assert_reconciled()

    def test_history_receipt_access_and_pagination(self):
        self.fund()
        sent = self.transfer().json()
        self.transfer("1.00")
        seen=[]
        before=None
        while True:
            response=self.client.get("/payments/history", params={"limit":1, **({"before":before} if before else {})}, headers=self.headers[0])
            self.assertEqual(response.status_code,200)
            data=response.json()
            seen.extend(p["transaction_id"] for p in data["items"])
            before=data["next_cursor"]
            if before is None: break
        self.assertEqual(len(seen),3)
        self.assertEqual(len(set(seen)),3)
        incoming=self.client.get(f"/payments/{sent['transaction_id']}",headers=self.headers[1])
        self.assertEqual(incoming.status_code,200)
        self.assertEqual(incoming.json()["direction"],"INCOMING")
        self.assertEqual(self.client.get(f"/payments/{sent['transaction_id']}",headers=self.headers[2]).status_code,404)
        self.assertEqual(self.client.get("/payments/history",headers=self.headers[2]).json()["items"],[])
        self.assertEqual(self.client.get("/payments/history",params={"before":sent["transaction_id"]},headers=self.headers[2]).status_code,404)

    def test_database_guards_immutability_reconciliation_and_missing_postings(self):
        self.fund()
        for sql in ["UPDATE payments SET note='changed'", "UPDATE ledger_entries SET amount=amount+1", "UPDATE ledger_accounts SET id=id", "UPDATE payment_requests SET fingerprint=fingerprint"]:
            with self.assertRaises(DBAPIError):
                with self.engine.begin() as c: c.execute(text(sql))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as c:
                c.execute(text("UPDATE bank_accounts SET balance=balance+1 WHERE id=:id"), {"id":self.accounts[0]["id"]})
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as c:
                c.execute(text("""INSERT INTO payments(id,actor_user_id,recipient_account_id,amount,currency,type,status,sender_name,recipient_name,note)
                    VALUES (:id,:uid,:aid,1,'INR','DEMO_FUNDING','SUCCESS','system','test','')"""), {"id":str(uuid4()),"uid":self.accounts[0]["user_id"],"aid":self.accounts[0]["id"]})
        self.assert_reconciled()
