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


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Phase 8 requires PostgreSQL")
class Phase8Tests(PaymentDatabaseTestCase):
    def second(self, user=0):
        result = self.client.post("/accounts", json={"bank_name": "Orbit Demo Bank"}, headers=self.headers[user])
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def self_pay(self, target, amount="100.00", key=None, source=None, **extra):
        return self.client.post("/payments/self-transfer", headers={**self.headers[0], "Idempotency-Key": key or str(uuid4())},
            json={"source_account_id": source or self.accounts[0]["id"], "destination_account_id": target, "amount": amount, "note": "Moving demo funds", **extra})

    def split(self, key=None, **extra):
        body = {"title": "Dinner", "total_amount": "100.00", "include_creator": True, "mode": "EQUAL",
            "participants": [{"upi_id": self.accounts[1]["upi_id"]}, {"upi_id": self.accounts[2]["upi_id"]}], **extra}
        return self.client.post("/splits", json=body, headers={**self.headers[0], "Idempotency-Key": key or str(uuid4())})

    def detail(self, sid, user=0):
        return self.client.get(f"/splits/{sid}", headers=self.headers[user])

    def request_pay(self, rid, payer, key=None, source=None):
        return self.client.post(f"/payment-requests/{rid}/pay", json={"source_account_id": source} if source else {},
            headers={**self.headers[payer], "Idempotency-Key": key or str(uuid4())})

    def parallel(self, actions):
        barrier = threading.Barrier(len(actions))
        def invoke(action):
            barrier.wait(timeout=10)
            return action()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(invoke, actions))

    def test_second_account_preserves_original_and_unique_identifiers(self):
        old = self.client.get("/accounts", headers=self.headers[0]).json()[0]
        added = self.second()
        all_accounts = self.client.get("/accounts", headers=self.headers[0]).json()
        self.assertEqual(all_accounts[0], old)
        self.assertFalse(added["is_primary"])
        self.assertNotEqual(old["upi_id"], added["upi_id"])
        self.assertEqual(added["balance"], "0.00")

    def test_primary_switch_ownership_and_exact_upi_routing(self):
        added = self.second()
        self.assertEqual(self.client.patch(f"/accounts/{added['id']}/primary", headers=self.headers[1]).status_code, 404)
        result = self.client.patch(f"/accounts/{added['id']}/primary", headers=self.headers[0])
        self.assertEqual(result.status_code, 200, result.text)
        self.fund(1)
        sent = self.transfer("12.34", sender=1, recipient=0)
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(self.balances(), [Decimal("12.34"), Decimal("987.66"), 0, 0])
        lookup = self.client.post("/payments/resolve", json={"upi_id": self.accounts[0]["upi_id"]}, headers=self.headers[1])
        self.assertEqual(lookup.json()["bank_name"], "Grove Demo Bank")

    def test_funding_limit_is_user_wide_across_accounts(self):
        added = self.second()
        self.assertEqual(self.fund().status_code, 201)
        for _ in range(2):
            self.assertEqual(self.client.post("/demo/fund", json={"account_id": added["id"]}, headers={**self.headers[0], "Idempotency-Key": str(uuid4())}).status_code, 201)
        self.assertEqual(self.fund().status_code, 429)
        self.assertEqual(sum(self.balances()), 3000)
        self.assert_reconciled()

    def test_concurrent_account_creation_limit_and_one_primary(self):
        results = self.parallel([lambda: self.client.post("/accounts", json={"bank_name": "Orbit Demo Bank"}, headers=self.headers[0]) for _ in range(5)])
        self.assertEqual(sorted(r.status_code for r in results), [201,201,201,409,409])
        accounts = self.client.get("/accounts", headers=self.headers[0]).json()
        self.assertEqual(sum(account["is_primary"] for account in accounts), 1)

    def test_concurrent_primary_switches_preserve_one_primary(self):
        a, b = self.second(), self.second()
        results = self.parallel([lambda: self.client.patch(f"/accounts/{a['id']}/primary", headers=self.headers[0]), lambda: self.client.patch(f"/accounts/{b['id']}/primary", headers=self.headers[0])])
        self.assertEqual([r.status_code for r in results], [200,200])
        self.assertEqual(sum(account["is_primary"] for account in self.client.get("/accounts", headers=self.headers[0]).json()), 1)

    def test_default_source_follows_primary_and_explicit_source_is_owned(self):
        added = self.second()
        self.client.patch(f"/accounts/{added['id']}/primary", headers=self.headers[0])
        self.fund()
        self.assertEqual(self.transfer("1.00").status_code, 201)
        bad = self.transfer("1.00", source_account_id=self.accounts[1]["id"])
        self.assertEqual(bad.status_code, 404)
        self.assertEqual(self.balances(), [0,1,0,999])

    def test_self_transfer_exact_conservation_ledger_and_receipt(self):
        added = self.second()
        self.fund()
        paid = self.self_pay(added["id"], "125.50")
        self.assertEqual(paid.status_code, 201, paid.text)
        receipt = paid.json()
        self.assertEqual((receipt["type"], receipt["direction"]), ("SELF_TRANSFER", "SELF"))
        self.assertEqual(receipt["destination_bank"], "Orbit Demo Bank")
        self.assertTrue(receipt["source_masked_account"].startswith("SIM •"))
        self.assertEqual(self.balances(), [Decimal("874.50"),0,0,Decimal("125.50")])
        self.assertEqual(sum(self.balances()), 1000)
        self.assert_reconciled()

    def test_self_transfer_errors_and_precise_validation(self):
        added = self.second()
        self.assertEqual(self.self_pay(added["id"]).status_code, 400)
        self.assertEqual(self.self_pay(self.accounts[0]["id"]).status_code, 400)
        self.assertEqual(self.self_pay(self.accounts[1]["id"]).status_code, 404)
        self.assertEqual(self.self_pay(added["id"], source=self.accounts[1]["id"]).status_code, 404)
        for amount in ["0", "-1", "1.001", "100000.01", 1.2]:
            self.assertEqual(self.self_pay(added["id"], amount).status_code, 422)
        self.assertEqual(self.self_pay(added["id"], balance="10000").status_code, 422)
        self.assertEqual(sum(self.balances()), 0)

    def test_normal_transfer_to_another_own_upi_is_rejected(self):
        added = self.second()
        self.fund()
        self.assertEqual(self.transfer("1.00", upi_id=added["upi_id"]).status_code, 400)

    def test_self_idempotency_replay_conflict_and_concurrency(self):
        added = self.second()
        self.fund()
        key = str(uuid4())
        results = self.parallel([lambda: self.self_pay(added["id"], "100.00", key=key) for _ in range(4)])
        self.assertEqual([r.status_code for r in results], [201]*4, [r.text for r in results])
        self.assertEqual(len({r.json()["transaction_id"] for r in results}), 1)
        self.assertEqual(self.self_pay(added["id"], "200.00", key=key).status_code, 409)
        self.assertEqual(self.balances()[0], 900)
        self.assertEqual(sum(self.balances()), 1000)

    def test_self_and_other_spending_cannot_overdraw(self):
        added = self.second()
        self.fund()
        results = self.parallel([lambda: self.self_pay(added["id"], "800.00"), lambda: self.transfer("800.00")])
        self.assertEqual(sorted(r.status_code for r in results), [201,400])
        self.assertEqual(self.balances()[0], 200)
        self.assertEqual(sum(self.balances()), 1000)
        self.assert_reconciled()

    def test_self_rollback_and_same_key_recovery(self):
        added = self.second()
        self.fund()
        key = str(uuid4())
        from payments import post_ledger
        def fail(db, payment):
            post_ledger(db, payment)
            raise RuntimeError("injected after posting")
        with patch("payments.post_ledger", fail):
            self.assertEqual(self.self_pay(added["id"], key=key).status_code, 503)
        self.assertEqual(self.balances(), [1000,0,0,0])
        self.assertEqual(self.self_pay(added["id"], key=key).status_code, 201)
        self.assert_reconciled()

    def test_history_all_accounts_self_once_and_receipt_privacy(self):
        added = self.second()
        self.fund()
        paid = self.self_pay(added["id"]).json()
        self.client.patch(f"/accounts/{added['id']}/primary", headers=self.headers[0])
        history = self.client.get("/payments/history", headers=self.headers[0]).json()["items"]
        self.assertEqual(len(history), 2)
        self.assertEqual(sum(item["type"] == "SELF_TRANSFER" for item in history), 1)
        self.assertEqual(self.client.get(f"/payments/{paid['transaction_id']}", headers=self.headers[1]).status_code, 404)

    def test_equal_rounding_creator_share_and_no_money_moved(self):
        result = self.split()
        self.assertEqual(result.status_code, 201, result.text)
        split = result.json()
        self.assertEqual(sorted(p["share_amount"] for p in split["participants"]), ["33.33","33.33","33.34"])
        self.assertEqual((split["creator_share"], split["outstanding_amount"]), ("33.34", "66.66"))
        self.assertEqual(sum(p["request_id"] is not None for p in split["participants"]), 2)
        self.assertEqual(sum(self.balances()), 0)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM payments")).scalar_one(), 0)

    def test_custom_split_and_no_creator_share(self):
        result = self.split(include_creator=False, mode="CUSTOM", participants=[{"upi_id": self.accounts[1]["upi_id"], "share_amount": "40.00"}, {"upi_id": self.accounts[2]["upi_id"], "share_amount": "60.00"}])
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["creator_share"], "0.00")
        self.assertEqual(result.json()["outstanding_amount"], "100.00")

    def test_invalid_split_totals_shares_duplicates_and_unknown_users(self):
        for amount in ["0", "1.001", "100000.01", 1.2]:
            self.assertEqual(self.split(total_amount=amount).status_code, 422)
        self.assertEqual(self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]*2).status_code, 422)
        self.assertEqual(self.split(participants=[{"upi_id": self.accounts[0]["upi_id"]}]).status_code, 422)
        self.assertEqual(self.split(participants=[{"upi_id": "unknown@payflow"}]).status_code, 404)
        self.assertEqual(self.split(mode="CUSTOM", creator_share="20.00", participants=[{"upi_id": self.accounts[1]["upi_id"], "share_amount": "40.00"}]).status_code, 422)
        self.assertEqual(self.split(total_amount="0.01").status_code, 422)
        for share in ["0", "-1", "1.001"]:
            self.assertEqual(self.split(mode="CUSTOM", creator_share="20.00", participants=[{"upi_id": self.accounts[1]["upi_id"], "share_amount": share}]).status_code, 422)

    def test_duplicate_user_with_different_upis_is_rejected(self):
        added = self.second(1)
        result = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}, {"upi_id": added["upi_id"]}])
        self.assertEqual(result.status_code, 422)

    def test_split_creation_idempotency_and_changed_payload(self):
        key = str(uuid4())
        results = self.parallel([lambda: self.split(key=key) for _ in range(3)])
        self.assertEqual(sorted(r.status_code for r in results), [200,200,201], [r.text for r in results])
        self.assertEqual(len({r.json()["id"] for r in results}), 1)
        self.assertEqual(self.split(key=key, title="Different").status_code, 409)

    def test_share_paid_via_requests_updates_progress_and_settlement(self):
        split = self.split().json()
        self.fund(1); self.fund(2)
        parts = [part for part in split["participants"] if not part["is_creator_share"]]
        for index, part in enumerate(parts):
            payer = 1 if part["person"]["upi_id"] == self.accounts[1]["upi_id"] else 2
            paid = self.request_pay(part["request_id"], payer)
            self.assertEqual(paid.status_code, 201, paid.text)
            detail = self.detail(split["id"]).json()
            self.assertEqual(detail["status"], "OPEN" if index == 0 else "SETTLED")
            current = next(p for p in detail["participants"] if p["id"] == part["id"])
            self.assertEqual(current["payment_id"], paid.json()["transaction_id"])
            self.assertEqual(self.request_pay(part["request_id"], payer).json(), paid.json())
        self.assertEqual(self.detail(split["id"]).json()["outstanding_amount"], "0.00")
        self.assert_reconciled()

    def test_concurrent_share_payment_one_posting(self):
        split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        self.fund(1)
        part = next(p for p in split["participants"] if p["request_id"])
        results = self.parallel([lambda: self.request_pay(part["request_id"], 1) for _ in range(3)])
        self.assertEqual([r.status_code for r in results], [201]*3, [r.text for r in results])
        self.assertEqual(len({r.json()["transaction_id"] for r in results}), 1)
        self.assertEqual(self.balances()[0], 50)
        self.assert_reconciled()

    def test_cancel_unpaid_split_closes_requests_and_cannot_pay(self):
        split = self.split().json()
        response = self.client.post(f"/splits/{split['id']}/cancel", json={}, headers=self.headers[0])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "CANCELLED")
        part = next(p for p in split["participants"] if p["request_id"])
        payer = 1 if part["person"]["upi_id"] == self.accounts[1]["upi_id"] else 2
        self.assertEqual(self.request_pay(part["request_id"], payer).status_code, 409)

    def test_cancellation_after_any_contribution_is_rejected(self):
        split = self.split().json()
        self.fund(1)
        part = next(p for p in split["participants"] if p["person"]["upi_id"] == self.accounts[1]["upi_id"])
        self.request_pay(part["request_id"], 1)
        self.assertEqual(self.client.post(f"/splits/{split['id']}/cancel", json={}, headers=self.headers[0]).status_code, 409)
        self.assertEqual(self.detail(split["id"]).json()["status"], "OPEN")

    def test_split_cancel_pay_race_is_atomic(self):
        split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        self.fund(1)
        part = next(p for p in split["participants"] if p["request_id"])
        results = self.parallel([lambda: self.request_pay(part["request_id"], 1), lambda: self.client.post(f"/splits/{split['id']}/cancel", json={}, headers=self.headers[0])])
        status = self.detail(split["id"]).json()["status"]
        self.assertEqual([r.status_code for r in results], [201,409] if status == "SETTLED" else [409,200])
        self.assert_reconciled()

    def test_declined_share_renewal_retains_audit_and_old_request_cannot_pay(self):
        split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        part = next(p for p in split["participants"] if p["request_id"])
        self.client.post(f"/payment-requests/{part['request_id']}/decline", json={}, headers=self.headers[1])
        key = str(uuid4())
        path = f"/splits/{split['id']}/participants/{part['id']}/renew"
        result = self.client.post(path, json={}, headers={**self.headers[0], "Idempotency-Key": key})
        self.assertEqual(result.status_code, 200, result.text)
        updated = next(p for p in result.json()["participants"] if p["id"] == part["id"])
        self.assertEqual(len(updated["attempts"]), 2)
        self.assertNotEqual(updated["request_id"], part["request_id"])
        self.assertEqual(self.client.post(path, json={}, headers={**self.headers[0], "Idempotency-Key": key}).json(), result.json())
        self.assertEqual(self.request_pay(part["request_id"], 1).status_code, 409)
        self.fund(1)
        self.assertEqual(self.request_pay(updated["request_id"], 1).status_code, 201)
        self.assert_reconciled()

    def test_expired_share_is_not_paid_and_can_be_renewed(self):
        with patch("social.REQUEST_TTL", timedelta(milliseconds=150)):
            split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        time.sleep(.2)
        part = next(p for p in self.detail(split["id"]).json()["participants"] if p["request_id"])
        self.assertEqual(part["status"], "EXPIRED")
        self.assertEqual(self.request_pay(part["request_id"], 1).status_code, 409)
        renewed = self.client.post(f"/splits/{split['id']}/participants/{part['id']}/renew", json={}, headers={**self.headers[0], "Idempotency-Key": str(uuid4())})
        self.assertEqual(renewed.status_code, 200, renewed.text)

    def test_split_participant_and_creator_authorization(self):
        split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        self.assertEqual(self.detail(split["id"], 1).status_code, 200)
        self.assertEqual(self.detail(split["id"], 2).status_code, 404)
        self.assertEqual(self.client.post(f"/splits/{split['id']}/cancel", json={}, headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.get("/splits", headers=self.headers[2]).json()["items"], [])
        self.assertEqual(self.client.get("/splits").status_code, 401)
        self.assertEqual(self.client.post("/payments/self-transfer", json={}).status_code, 401)

    def test_pinned_request_destination_survives_primary_switch(self):
        split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        added = self.second()
        self.client.patch(f"/accounts/{added['id']}/primary", headers=self.headers[0])
        part = next(p for p in split["participants"] if p["request_id"])
        self.fund(1)
        paid = self.request_pay(part["request_id"], 1)
        self.assertEqual(paid.status_code, 201, paid.text)
        self.assertEqual(self.balances(), [50,950,0,0])

    def test_database_rejects_wrong_shares_fake_settlement_and_identity_changes(self):
        split = self.split().json()
        statements = ["UPDATE expense_splits SET status='SETTLED' WHERE id=:id", "UPDATE expense_splits SET total_amount=1 WHERE id=:id", "UPDATE expense_split_participants SET share_amount=1 WHERE split_id=:id"]
        for statement in statements:
            with self.assertRaises(IntegrityError), self.engine.begin() as c:
                c.execute(text(statement), {"id": split["id"]})
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("UPDATE bank_accounts SET upi_id='changed@payflow' WHERE id=:id"), {"id": self.accounts[0]["id"]})

    def test_other_participants_do_not_receive_private_request_or_receipt_ids(self):
        split = self.split().json()
        shared = self.detail(split["id"], 1).json()
        other = next(part for part in shared["participants"] if part["person"]["upi_id"] == self.accounts[2]["upi_id"])
        self.assertIsNone(other["request_id"])
        self.assertIsNone(other["payment_id"])
        self.assertEqual(other["attempts"], [])

    def test_old_transfer_fingerprints_remain_compatible_without_source_selection(self):
        import hashlib
        import json
        from payment_schemas import TransferRequest
        from payments import request_fingerprint
        old = {"type": "TRANSFER", "upi_id": self.accounts[1]["upi_id"], "amount": "12.30", "note": "Lunch"}
        expected = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(request_fingerprint("TRANSFER", TransferRequest(upi_id=old["upi_id"], amount="12.3", note="Lunch")), expected)

    def test_different_participants_can_settle_concurrently(self):
        split = self.split().json()
        self.fund(1); self.fund(2)
        parts = {part["person"]["upi_id"]: part for part in split["participants"]}
        results = self.parallel([lambda: self.request_pay(parts[self.accounts[1]["upi_id"]]["request_id"], 1), lambda: self.request_pay(parts[self.accounts[2]["upi_id"]]["request_id"], 2)])
        self.assertEqual([response.status_code for response in results], [201,201])
        self.assertEqual(self.detail(split["id"]).json()["status"], "SETTLED")
        self.assert_reconciled()

    def test_request_can_be_paid_from_an_explicit_owned_secondary_account(self):
        added = self.second(1)
        self.fund(1)
        moved = self.client.post("/payments/self-transfer", headers={**self.headers[1], "Idempotency-Key": str(uuid4())}, json={"source_account_id": self.accounts[1]["id"], "destination_account_id": added["id"], "amount": "500.00"})
        self.assertEqual(moved.status_code, 201, moved.text)
        split = self.split(participants=[{"upi_id": self.accounts[1]["upi_id"]}]).json()
        part = next(part for part in split["participants"] if part["request_id"])
        self.assertEqual(self.request_pay(part["request_id"], 1, source=added["id"]).status_code, 201)
        self.assertEqual(self.balances(), [50,500,0,450])
        self.assert_reconciled()

    def test_recent_contacts_deduplicate_counterparty_users_across_accounts(self):
        added = self.second(1)
        self.fund()
        self.transfer("1.00", recipient=1)
        self.transfer("2.00", upi_id=added["upi_id"])
        recent = self.client.get("/contacts/recent", headers=self.headers[0]).json()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["upi_id"], self.accounts[1]["upi_id"])

