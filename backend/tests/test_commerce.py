import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from payment_support import PaymentDatabaseTestCase


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Requires PostgreSQL")
class CommerceTests(PaymentDatabaseTestCase):
    def post_recharge(self, user=0, key=None, **changes):
        return self.client.post("/recharge", headers={**self.headers[user], "Idempotency-Key": key or str(uuid4())},
            json={"mobile": "9876543210", "plan_id": "payflow-mobile-99", "source_account_id": self.accounts[user]["id"], **changes})

    def lookup(self, user=0, **changes):
        return self.client.post("/bills/lookup", headers=self.headers[user], json={"biller_id": "electric", "reference": "DEMO000001", **changes})

    def pay_bill(self, bill_id, user=0, key=None, **changes):
        return self.client.post(f"/bills/{bill_id}/pay", headers={**self.headers[user], "Idempotency-Key": key or str(uuid4())},
            json={"source_account_id": self.accounts[user]["id"], **changes})

    def count(self, table):
        with self.engine.connect() as connection:
            return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()

    def test_catalogs_and_seed_repeat(self):
        operators = self.client.get("/recharge/operators", headers=self.headers[0]).json()
        self.assertEqual(len(operators), 3)
        plans = self.client.get("/recharge/plans?operator_id=payflow-mobile", headers=self.headers[0]).json()
        self.assertEqual([p["price"] for p in plans], ["99.00", "199.00", "299.00", "599.00"])
        self.assertEqual(len(self.client.get("/billers", headers=self.headers[0]).json()), 4)
        from commerce_seed import seed
        with self.engine.begin() as c:
            seed(c)
            seed(c)
        self.assertEqual(self.count("demo_recharge_plans"), 12)

    def test_all_endpoints_require_auth(self):
        for path in ["/recharge/operators", "/recharge/plans?operator_id=novatel", "/billers", "/bills", "/bills/history", "/recharge/history", "/saved-billers"]:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post("/recharge", json={}).status_code, 401)
        self.assertEqual(self.client.post("/bills/lookup", json={}).status_code, 401)

    def test_mobile_validation_and_price_injection(self):
        for mobile in ["123", "1234567890", "+919876543210", "98765432100", 9876543210]:
            self.assertEqual(self.post_recharge(mobile=mobile).status_code, 422)
        self.assertEqual(self.post_recharge(amount="1.00").status_code, 422)
        self.assertEqual(self.post_recharge(user_id=2).status_code, 422)

    def test_unknown_and_inactive_plans(self):
        self.assertEqual(self.post_recharge(plan_id="missing").status_code, 404)
        with self.engine.begin() as c:
            c.execute(text("UPDATE demo_recharge_plans SET active=false WHERE id='payflow-mobile-99'"))
        self.assertEqual(self.post_recharge().status_code, 404)
        self.assertEqual(self.count("payments"), 0)

    def test_inactive_operator(self):
        with self.engine.begin() as c:
            c.execute(text("UPDATE demo_operators SET active=false WHERE id='payflow-mobile'"))
        self.assertEqual(self.post_recharge().status_code, 404)
        self.assertEqual(self.client.get("/recharge/plans?operator_id=payflow-mobile", headers=self.headers[0]).json(), [])

    def test_recharge_success_history_privacy_and_receipt(self):
        self.assertEqual(self.fund().status_code, 201)
        result = self.post_recharge()
        self.assertEqual(result.status_code, 201, result.text)
        body = result.json()
        self.assertEqual((body["type"], body["amount"], body["status"]), ("MOBILE_RECHARGE", "99.00", "SUCCESS"))
        self.assertEqual(body["source_bank"], "Grove Demo Bank")
        self.assertEqual(self.balances()[0], Decimal("901.00"))
        page = self.client.get("/recharge/history", headers=self.headers[0]).json()
        item = page["items"][0]
        self.assertEqual(item["status"], "COMPLETED")
        self.assertNotIn("9876543210", str(item))
        self.assertEqual(item["masked_mobile"], "••••••3210")
        self.assertEqual(self.client.get(f'/recharge/{item["id"]}', headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.get("/recharge/history", headers=self.headers[1]).json()["items"], [])
        self.assertEqual(self.client.get("/payments/history", headers=self.headers[0]).json()["items"][0]["type"], "MOBILE_RECHARGE")
        self.assert_reconciled()

    def test_recharge_insufficient_and_wrong_source(self):
        result = self.post_recharge()
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(self.count("mobile_recharges"), 0)
        self.assertEqual(self.count("ledger_entries"), 0)
        self.assertEqual(self.post_recharge(source_account_id=self.accounts[1]["id"]).status_code, 404)
        self.assert_reconciled()

    def test_recharge_retry_changed_payload_and_lost_response(self):
        self.fund()
        key = str(uuid4())
        first = self.post_recharge(key=key)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(self.post_recharge(key=key).json(), first.json())
        self.assertEqual(self.post_recharge(key=key, mobile="9876543211").status_code, 409)
        self.assertEqual(self.post_recharge(key=key, plan_id="payflow-mobile-199").status_code, 409)
        self.assertEqual(self.count("mobile_recharges"), 1)
        self.assert_reconciled()

    def test_concurrent_recharge_duplicates(self):
        self.fund()
        key = str(uuid4())
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(lambda _: self.post_recharge(key=key), range(2)))
        self.assertEqual([r.status_code for r in rows], [201, 201])
        self.assertEqual(rows[0].json(), rows[1].json())
        self.assertEqual(self.count("mobile_recharges"), 1)
        self.assertEqual(self.balances()[0], Decimal("901"))
        self.assert_reconciled()

    def test_fulfillment_failure_rolls_back_whole_recharge(self):
        self.fund()
        key = str(uuid4())
        with patch("commerce_service.fulfill_purchase", side_effect=RuntimeError("injected")):
            self.assertEqual(self.post_recharge(key=key).status_code, 503)
        self.assertEqual(self.balances()[0], Decimal("1000"))
        self.assertEqual(self.count("mobile_recharges"), 0)
        self.assertEqual(self.count("payments"), 1)
        self.assertEqual(self.post_recharge(key=key).status_code, 201)
        self.assert_reconciled()

    def test_recharge_history_pagination(self):
        self.fund()
        for _ in range(3):
            self.assertEqual(self.post_recharge().status_code, 201)
        page = self.client.get("/recharge/history?limit=2", headers=self.headers[0]).json()
        next_page = self.client.get("/recharge/history?limit=2&before=" + page["next_cursor"], headers=self.headers[0]).json()
        self.assertEqual(len(page["items"]) + len(next_page["items"]), 3)

    def test_bill_lookup_is_stable_and_user_scoped(self):
        first, repeat, other = self.lookup().json(), self.lookup().json(), self.lookup(user=1).json()
        self.assertEqual(first, repeat)
        self.assertNotEqual(first["id"], other["id"])
        self.assertEqual(first["amount_due"], other["amount_due"])
        self.assertEqual(self.client.get('/bills/'+first["id"], headers=self.headers[1]).status_code, 404)
        self.assertNotIn("DEMO000001", str(first))
        self.assertEqual(self.balances(), [Decimal(0)] * 3)

    def test_bill_reference_and_unknown_biller(self):
        for reference in ["123456", "DEMO1", "DEMO1234567", "demo000001", "DEMO<test>"]:
            self.assertEqual(self.lookup(reference=reference).status_code, 422)
        self.assertEqual(self.lookup(biller_id="real-provider").status_code, 404)

    def test_bill_payment_and_paid_history(self):
        self.fund()
        bill = self.lookup().json()
        result = self.pay_bill(bill["id"])
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["amount"], bill["amount_due"])
        self.assertEqual(result.json()["type"], "BILL_PAYMENT")
        paid = self.client.get('/bills/'+bill["id"], headers=self.headers[0]).json()
        self.assertEqual(paid["status"], "PAID")
        self.assertEqual(paid["receipt"]["transaction_id"], result.json()["transaction_id"])
        self.assertEqual(self.balances()[0], Decimal("1000") - Decimal(bill["amount_due"]))
        self.assertEqual(self.client.get('/bills/history?paid_only=true', headers=self.headers[0]).json()["items"][0]["id"], bill["id"])
        self.assert_reconciled()

    def test_bill_retry_same_and_different_keys(self):
        self.fund()
        bill = self.lookup().json()
        key = str(uuid4())
        first = self.pay_bill(bill["id"], key=key)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(self.pay_bill(bill["id"], key=key).json(), first.json())
        again = self.pay_bill(bill["id"])
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(self.pay_bill(bill["id"], key=key, source_account_id=self.accounts[1]["id"]).status_code, 409)
        self.assertEqual(self.count("payments"), 2)
        self.assert_reconciled()

    def test_bill_concurrent_different_keys(self):
        self.fund()
        bill = self.lookup().json()
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(lambda _: self.pay_bill(bill["id"]), range(2)))
        self.assertEqual(sorted(r.status_code for r in rows), [200, 201])
        self.assertEqual(rows[0].json(), rows[1].json())
        self.assertEqual(self.count("payments"), 2)
        self.assert_reconciled()

    def test_bill_concurrent_same_key(self):
        self.fund()
        bill = self.lookup().json()
        key = str(uuid4())
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(lambda _: self.pay_bill(bill["id"], key=key), range(2)))
        self.assertEqual([r.status_code for r in rows], [201, 201])
        self.assertEqual(rows[0].json(), rows[1].json())
        self.assert_reconciled()

    def test_bill_insufficient_ownership_and_price(self):
        bill = self.lookup().json()
        self.assertEqual(self.pay_bill(bill["id"]).status_code, 400)
        self.assertEqual(self.pay_bill(bill["id"], user=1).status_code, 404)
        self.assertEqual(self.pay_bill(bill["id"], source_account_id=self.accounts[1]["id"]).status_code, 404)
        self.assertEqual(self.pay_bill(bill["id"], amount="0.01").status_code, 422)
        self.assertEqual(self.lookup().json()["status"], "UNPAID")
        self.assert_reconciled()

    def test_bill_atomic_rollback_and_retry(self):
        self.fund()
        bill = self.lookup().json()
        key = str(uuid4())
        with patch("commerce_service.fulfill_purchase", side_effect=RuntimeError("injected")):
            self.assertEqual(self.pay_bill(bill["id"], key=key).status_code, 503)
        self.assertEqual(self.lookup().json()["status"], "UNPAID")
        self.assertEqual(self.balances()[0], Decimal("1000"))
        self.assertEqual(self.pay_bill(bill["id"], key=key).status_code, 201)
        self.assert_reconciled()

    def test_saved_biller_duplicate_owner_mask_and_lookup(self):
        body = {"biller_id": "water", "reference": "DEMO123456", "nickname": "Home"}
        first = self.client.post('/saved-billers', headers=self.headers[0], json=body)
        self.assertEqual(first.status_code, 201, first.text)
        item = first.json()
        self.assertNotIn("DEMO123456", str(item))
        self.assertEqual(self.client.post('/saved-billers', headers=self.headers[0], json=body).status_code, 409)
        self.assertEqual(len(self.client.get('/saved-billers', headers=self.headers[0]).json()), 1)
        self.assertEqual(self.client.get('/saved-billers', headers=self.headers[1]).json(), [])
        path = '/saved-billers/'+item["id"]
        self.assertEqual(self.client.post(path+'/lookup', headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.delete(path, headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.post(path+'/lookup', headers=self.headers[0]).status_code, 200)
        self.assertEqual(self.client.delete(path, headers=self.headers[0]).status_code, 204)
        self.assertEqual(self.count("utility_bills"), 1)

    def test_internal_accounts_are_not_bank_accounts(self):
        self.fund()
        self.post_recharge()
        accounts = self.client.get('/accounts', headers=self.headers[0]).json()
        self.assertEqual(len(accounts), 1)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM ledger_accounts WHERE id LIKE 'settlement-%' AND bank_account_id IS NULL")).scalar_one(), 2)
            self.assertEqual(c.execute(text("SELECT sum(amount) FROM ledger_entries WHERE ledger_account_id='settlement-recharge'")).scalar_one(), Decimal(99))
        self.assert_reconciled()

    def test_recharge_records_immutable(self):
        self.fund()
        self.post_recharge()
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("UPDATE mobile_recharges SET masked_mobile='changed'"))

    def test_bill_terms_and_paid_records_immutable(self):
        self.fund()
        bill = self.lookup().json()
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("UPDATE utility_bills SET amount_due=1"))
        self.pay_bill(bill["id"])
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("UPDATE utility_bills SET status='UNPAID',payment_id=NULL,paid_at=NULL"))

    def test_lookup_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.lookup().status_code, 200)
        self.assertEqual(self.lookup().status_code, 429)

    def test_same_key_different_bill_conflict(self):
        self.fund()
        first = self.lookup().json()
        second = self.lookup(reference="DEMO000002").json()
        key = str(uuid4())
        self.assertEqual(self.pay_bill(first["id"], key=key).status_code, 201)
        self.assertEqual(self.pay_bill(second["id"], key=key).status_code, 409)
        self.assert_reconciled()

    def test_concurrent_purchases_cannot_overspend(self):
        self.fund()
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(lambda _: self.post_recharge(plan_id="payflow-mobile-599"), range(2)))
        self.assertEqual(sorted(r.status_code for r in rows), [201, 400])
        self.assertEqual(self.balances()[0], Decimal("401.00"))
        self.assertEqual(self.count("mobile_recharges"), 1)
        self.assert_reconciled()

    def test_purchase_rate_limit(self):
        self.fund()
        for _ in range(10):
            self.assertEqual(self.post_recharge().status_code, 201)
        self.assertEqual(self.post_recharge().status_code, 429)
        self.assertEqual(self.count("mobile_recharges"), 10)
        self.assert_reconciled()

    def test_bill_unpaid_history_pagination(self):
        for index in range(3):
            self.assertEqual(self.lookup(reference=f"DEMO{index:06d}").status_code, 200)
        page = self.client.get('/bills?limit=2', headers=self.headers[0]).json()
        next_page = self.client.get('/bills?limit=2&before='+page["next_cursor"], headers=self.headers[0]).json()
        self.assertEqual(len(page["items"])+len(next_page["items"]), 3)
        self.assertEqual(self.client.get('/bills?paid_only=true', headers=self.headers[0]).json()["items"], [])

    def test_missing_idempotency_key_rejected(self):
        self.assertEqual(self.client.post('/recharge', headers=self.headers[0], json={"mobile": "9876543210", "plan_id": "payflow-mobile-99", "source_account_id": self.accounts[0]["id"]}).status_code, 422)
        bill = self.lookup().json()
        self.assertEqual(self.client.post('/bills/'+bill["id"]+'/pay', headers=self.headers[0], json={"source_account_id": self.accounts[0]["id"]}).status_code, 422)

    def test_new_qr_channel_is_a_transfer_not_a_second_engine(self):
        self.fund()
        response = self.transfer(channel="QR")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["channel"], "QR")
        self.assertEqual(response.json()["type"], "TRANSFER")
        self.assert_reconciled()

    def test_demo_number_format_configuration(self):
        import re
        import runpy
        from pathlib import Path
        config_path = Path(__file__).resolve().parents[1] / "config.py"
        with patch.dict(os.environ, {"PAYFLOW_DEMO_MOBILE_PREFIXES": "5"}):
            config = runpy.run_path(str(config_path))
            self.assertTrue(re.fullmatch(config["DEMO_MOBILE_PATTERN"], "5123456789"))
            self.assertFalse(re.fullmatch(config["DEMO_MOBILE_PATTERN"], "9123456789"))
        with patch.dict(os.environ, {"PAYFLOW_DEMO_MOBILE_PREFIXES": ".*"}):
            with self.assertRaises(RuntimeError):
                runpy.run_path(str(config_path))
