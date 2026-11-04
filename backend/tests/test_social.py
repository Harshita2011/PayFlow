from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import os
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from payment_support import PaymentDatabaseTestCase


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Phase 7 requires PostgreSQL")
class SocialTests(PaymentDatabaseTestCase):
    def create_request(self, requester=0, payer=1, amount="125.50", key=None, **extra):
        return self.client.post("/payment-requests", headers={**self.headers[requester], "Idempotency-Key": key or str(uuid4())},
            json={"upi_id": self.accounts[payer]["upi_id"], "amount": amount, "note": "Lunch", **extra})

    def action(self, request_id, action, user=1, key=None, **body):
        return self.client.post(f"/payment-requests/{request_id}/{action}", json=body,
            headers={**self.headers[user], "Idempotency-Key": key or str(uuid4())})

    def get_request(self, request_id, user=0):
        return self.client.get(f"/payment-requests/{request_id}", headers=self.headers[user])

    def add_contact(self, owner=0, contact=1):
        return self.client.post("/contacts", json={"upi_id": self.accounts[contact]["upi_id"]}, headers=self.headers[owner])

    def parallel(self, actions):
        barrier = threading.Barrier(len(actions))
        def invoke(fn):
            barrier.wait(timeout=10)
            return fn()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(invoke, actions))

    def test_contacts_private_personal_and_duplicate(self):
        first = self.add_contact()
        self.assertEqual(first.status_code, 201, first.text)
        again = self.add_contact()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.json(), again.json())
        data = first.json()
        self.assertEqual(set(data), {"id", "display_name", "upi_id", "is_favorite", "created_at", "updated_at"})
        self.assertEqual(self.client.get("/contacts", headers=self.headers[1]).json(), [])
        self.assertEqual(len(self.client.get("/contacts", headers=self.headers[0]).json()), 1)

    def test_contacts_self_unknown_and_private_input(self):
        self.assertEqual(self.add_contact(contact=0).status_code, 400)
        self.assertEqual(self.client.post("/contacts", headers=self.headers[0], json={"upi_id": "unknown@payflow"}).status_code, 404)
        self.assertEqual(self.client.post("/contacts", headers=self.headers[0], json={"upi_id": self.accounts[1]["upi_id"], "owner_user_id": 2}).status_code, 422)

    def test_contact_ownership_favorite_and_remove(self):
        item = self.add_contact().json()
        path = f"/contacts/{item['id']}"
        self.assertEqual(self.client.patch(path + "/favorite", json={"is_favorite": True}, headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.delete(path, headers=self.headers[1]).status_code, 404)
        for favorite in [True, False]:
            result = self.client.patch(path + "/favorite", json={"is_favorite": favorite}, headers=self.headers[0])
            self.assertEqual(result.json()["is_favorite"], favorite)
        self.assertEqual(self.client.delete(path, headers=self.headers[0]).status_code, 204)
        self.assertEqual(self.client.get("/contacts", headers=self.headers[0]).json(), [])
        self.assertEqual(len(self.balances()), 3)

    def test_concurrent_contact_adds_deduplicate(self):
        responses = self.parallel([lambda: self.add_contact() for _ in range(3)])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 200, 201])
        self.assertEqual(len({r.json()["id"] for r in responses}), 1)

    def test_recent_contacts_order_dedup_and_ownership(self):
        self.fund()
        self.transfer("10.00", recipient=1)
        self.transfer("20.00", recipient=2)
        self.transfer("1.00", recipient=1)
        recent = self.client.get("/contacts/recent", headers=self.headers[0]).json()
        self.assertEqual([r["upi_id"] for r in recent], [self.accounts[1]["upi_id"], self.accounts[2]["upi_id"]])
        self.assertEqual(len(self.client.get("/contacts/recent", headers=self.headers[1]).json()), 1)
        self.assertEqual(set(recent[0]), {"display_name", "upi_id", "last_interacted_at"})

    def test_create_request_no_money_and_private_fields(self):
        response = self.create_request()
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        self.assertEqual(item["status"], "PENDING")
        self.assertEqual(item["amount"], "125.50")
        self.assertEqual(item["requester"], {"display_name": "Payment Learner 0", "upi_id": self.accounts[0]["upi_id"]})
        self.assertNotIn("requester_user_id", item)
        self.assertEqual(self.balances(), [0, 0, 0])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM payments")).scalar_one(), 0)
        self.assert_reconciled()

    def test_creation_idempotency_and_fingerprint_conflict(self):
        key = str(uuid4())
        first = self.create_request(key=key)
        self.assertEqual(self.create_request(key=key).json(), first.json())
        self.assertEqual(self.create_request(key=key, amount="126.50").status_code, 409)

    def test_concurrent_request_creation_same_key(self):
        key = str(uuid4())
        results = self.parallel([lambda: self.create_request(key=key) for _ in range(3)])
        self.assertEqual(sorted(r.status_code for r in results), [200, 200, 201])
        self.assertEqual(len({r.json()["id"] for r in results}), 1)

    def test_invalid_amounts_self_unknown_and_extras(self):
        for amount in ["0", "-1", "1.001", "100000.01", "NaN", "1e3", 1.2]:
            self.assertEqual(self.create_request(amount=amount).status_code, 422)
        self.assertEqual(self.create_request(payer=0).status_code, 400)
        self.assertEqual(self.create_request(upi_id="unknown@payflow").status_code, 404)
        self.assertEqual(self.create_request(payer_user_id=2).status_code, 422)

    def test_authorization_on_lists_details_actions_and_authentication(self):
        item = self.create_request().json()
        rid = item["id"]
        self.assertEqual(self.get_request(rid, 2).status_code, 404)
        self.assertEqual(self.action(rid, "pay", 0).status_code, 404)
        self.assertEqual(self.action(rid, "decline", 0).status_code, 404)
        self.assertEqual(self.action(rid, "cancel", 1).status_code, 404)
        for path in ["/contacts", "/contacts/recent", "/payment-requests/incoming", "/payment-requests/outgoing", f"/payment-requests/{rid}"]:
            self.assertEqual(self.client.get(path).status_code, 401)
        for action in ["pay", "cancel", "decline"]:
            self.assertEqual(self.client.post(f"/payment-requests/{rid}/{action}", json={}).status_code, 401)

    def test_decline_and_cancel_are_terminal_and_repeatable(self):
        for action, user, status in [("decline", 1, "DECLINED"), ("cancel", 0, "CANCELLED")]:
            rid = self.create_request().json()["id"]
            self.assertEqual(self.action(rid, action, user).json()["status"], status)
            self.assertEqual(self.action(rid, action, user).json()["status"], status)
            self.assertEqual(self.action(rid, "pay").status_code, 409)
        self.assertEqual(self.balances(), [0, 0, 0])

    def test_success_payment_balance_ledger_and_receipt_link(self):
        self.fund(1)
        rid = self.create_request().json()["id"]
        paid = self.action(rid, "pay")
        self.assertEqual(paid.status_code, 201, paid.text)
        item = self.get_request(rid).json()
        self.assertEqual((item["status"], item["payment_id"]), ("PAID", paid.json()["transaction_id"]))
        self.assertEqual(self.balances(), [Decimal("125.50"), Decimal("874.50"), 0])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT amount FROM ledger_entries WHERE payment_id=:id ORDER BY amount"), {"id": item["payment_id"]}).scalars().all(), [Decimal("-125.50"), Decimal("125.50")])
        self.assert_reconciled()

    def test_insufficient_funds_stays_pending_then_new_intent_can_pay(self):
        rid = self.create_request().json()["id"]
        key = str(uuid4())
        failed = self.action(rid, "pay", key=key)
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.get_request(rid).json()["status"], "PENDING")
        self.fund(1)
        self.assertEqual(self.action(rid, "pay", key=key).json(), failed.json())
        self.assertEqual(self.action(rid, "pay").status_code, 201)
        self.assert_reconciled()

    def test_pay_replay_same_or_different_key_never_posts_twice(self):
        self.fund(1)
        rid = self.create_request().json()["id"]
        key = str(uuid4())
        first = self.action(rid, "pay", key=key)
        self.assertEqual(self.action(rid, "pay", key=key).json(), first.json())
        self.assertEqual(self.action(rid, "pay").json(), first.json())
        self.assertEqual(self.balances()[0], Decimal("125.50"))
        self.assertEqual(self.action(rid, "pay", amount="1.00").status_code, 422)
        self.assert_reconciled()

    def test_key_cannot_cross_transfer_or_another_request(self):
        self.fund(1)
        key = str(uuid4())
        self.transfer("1.00", sender=1, recipient=0, key=key)
        rid = self.create_request().json()["id"]
        self.assertEqual(self.action(rid, "pay", key=key).status_code, 409)
        second = self.create_request().json()["id"]
        key = str(uuid4())
        self.action(rid, "pay", key=key)
        self.assertEqual(self.action(second, "pay", key=key).status_code, 409)

    def test_concurrent_pay_same_and_different_keys(self):
        self.fund(1)
        for same in [True, False]:
            rid = self.create_request().json()["id"]
            key = str(uuid4())
            results = self.parallel([lambda: self.action(rid, "pay", key=key if same else None) for _ in range(4)])
            self.assertEqual([r.status_code for r in results], [201]*4, [r.text for r in results])
            self.assertEqual(len({r.json()["transaction_id"] for r in results}), 1)
        self.assertEqual(self.balances()[0], Decimal("251.00"))
        self.assert_reconciled()

    def test_cancel_pay_and_decline_pay_races(self):
        self.fund(1)
        for action, actor in [("cancel", 0), ("decline", 1)]:
            rid = self.create_request().json()["id"]
            results = self.parallel([lambda: self.action(rid, "pay"), lambda: self.action(rid, action, actor)])
            item = self.get_request(rid).json()
            if item["status"] == "PAID":
                self.assertEqual([r.status_code for r in results], [201, 409])
            else:
                self.assertEqual([r.status_code for r in results], [409, 200])
                self.assertIsNone(item["payment_id"])
        self.assert_reconciled()

    def test_expired_requests_cannot_pay_and_are_displayed_expired(self):
        with patch("social.REQUEST_TTL", timedelta(milliseconds=100)):
            rid = self.create_request().json()["id"]
        time.sleep(.15)
        self.assertEqual(self.get_request(rid).json()["status"], "EXPIRED")
        self.assertEqual(self.action(rid, "pay").status_code, 409)
        self.assertEqual(self.get_request(rid).json()["status"], "EXPIRED")
        self.assertEqual(self.balances(), [0, 0, 0])

    def test_atomic_rollback_on_injected_failure(self):
        self.fund(1)
        rid = self.create_request().json()["id"]
        key = str(uuid4())
        from payments import post_ledger
        def fail(db, payment):
            post_ledger(db, payment)
            raise RuntimeError("injected after ledger")
        with patch("payments.post_ledger", fail):
            self.assertEqual(self.action(rid, "pay", key=key).status_code, 503)
        self.assertEqual(self.get_request(rid).json()["status"], "PENDING")
        self.assertEqual(self.balances(), [0, 1000, 0])
        self.assertEqual(self.action(rid, "pay", key=key).status_code, 201)
        self.assert_reconciled()

    def test_request_and_normal_transfer_cannot_overspend(self):
        self.fund(1)
        rid = self.create_request(amount="800.00").json()["id"]
        results = self.parallel([lambda: self.action(rid, "pay"), lambda: self.transfer("800.00", sender=1, recipient=2)])
        self.assertEqual(sorted(r.status_code for r in results), [201, 400])
        self.assertEqual(self.balances()[1], 200)
        self.assertEqual(sum(self.balances()), 1000)
        self.assert_reconciled()

    def test_expiration_while_waiting_for_account_lock(self):
        self.fund(1)
        with patch("social.REQUEST_TTL", timedelta(seconds=1)):
            rid = self.create_request().json()["id"]
        with self.engine.connect() as lock:
            transaction = lock.begin()
            lock.execute(text("SELECT id FROM bank_accounts WHERE id=:id FOR UPDATE"), {"id": self.accounts[1]["id"]})
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(lambda: self.action(rid, "pay"))
                time.sleep(1.1)
                transaction.rollback()
                self.assertEqual(pending.result(timeout=10).status_code, 409)
        self.assertEqual(self.get_request(rid).json()["status"], "EXPIRED")
        self.assertEqual(self.balances(), [0, 1000, 0])
        self.assert_reconciled()

    def test_pagination_pending_count_and_private_activity(self):
        for _ in range(3):
            self.create_request()
        page = self.client.get("/payment-requests/incoming?limit=2", headers=self.headers[1]).json()
        self.assertEqual((len(page["items"]), page["pending_count"]), (2, 3))
        next_page = self.client.get(f"/payment-requests/incoming?limit=2&before={page['next_cursor']}", headers=self.headers[1]).json()
        self.assertEqual(len(next_page["items"]), 1)
        self.assertEqual(self.client.get("/payment-requests/incoming", headers=self.headers[2]).json()["items"], [])
        self.assertEqual(self.client.get(f"/payment-requests/incoming?before={page['items'][0]['id']}", headers=self.headers[2]).status_code, 404)

    def test_database_prevents_term_mutation_and_fake_paid_link(self):
        rid = self.create_request().json()["id"]
        for statement in ["UPDATE money_requests SET amount=1 WHERE id=:id", "UPDATE money_requests SET status='PAID' WHERE id=:id"]:
            with self.assertRaises(IntegrityError), self.engine.begin() as c:
                c.execute(text(statement), {"id": rid})
        self.fund(1)
        payment_id = self.transfer("1.00", sender=1, recipient=0).json()["transaction_id"]
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("UPDATE money_requests SET status='PAID',payment_id=:p WHERE id=:id"), {"id": rid, "p": payment_id})
        self.assert_reconciled()

    def test_creation_spam_and_lookup_limits(self):
        for _ in range(10):
            self.assertEqual(self.create_request().status_code, 201)
        with self.engine.begin() as c:
            c.execute(text("UPDATE recipient_lookup_limits SET window_start=window_start-interval '1 minute'"))
        self.assertEqual(self.create_request().status_code, 429)
        self.assertEqual(self.client.get("/payment-requests/outgoing", headers=self.headers[0]).json()["pending_count"], 10)

