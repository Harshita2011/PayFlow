import hashlib
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from payment_support import PaymentDatabaseTestCase, TEST_PIN
from security import password_hasher
from security_settings import settings
from security_models import PinCredential, PaymentAuthorization
from models import User

PASSWORD = "Learning-Security-2026!"


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Security integration requires PostgreSQL")
class SecurityTests(PaymentDatabaseTestCase):
    auto_authorize = False
    relax_security_limits = False

    def setUp(self):
        super().setUp()
        with Session(self.engine) as db:
            hashed = password_hasher.hash(PASSWORD)
            for account in self.accounts:
                db.get(User, account["user_id"]).password_hash = hashed
            db.commit()

    def setup_pin(self, user=0, **changes):
        return self.client.post("/security/pin", headers=self.headers[user], json={"pin": TEST_PIN, "password": PASSWORD, **changes})

    def body(self, amount="10.00", **changes):
        return {"upi_id": self.accounts[1]["upi_id"], "source_account_id": self.accounts[0]["id"], "amount": amount, "note": "Demo", **changes}

    def grant(self, key, body=None, operation="TRANSFER", reference=None, user=0, pin=TEST_PIN):
        command = {"pin": pin, "operation": operation, "payload": body if body is not None else self.body()}
        if reference: command["reference_id"] = reference
        return self.client.post("/security/payment-authorizations", headers={**self.headers[user], "Idempotency-Key": key}, json=command)

    def send(self, key, body=None, token=None, path="/payments/transfer", user=0):
        headers = {**self.headers[user], "Idempotency-Key": key}
        if token: headers["Payment-Authorization"] = token
        return self.client.post(path, headers=headers, json=self.body() if body is None else body)

    def ready(self, body=None, operation="TRANSFER", reference=None):
        self.assertEqual(self.setup_pin().status_code, 201)
        self.assertEqual(self.fund().status_code, 201)
        key = str(uuid4())
        grant = self.grant(key, body, operation, reference)
        self.assertEqual(grant.status_code, 201, grant.text)
        return key, grant.json()["authorization_token"]

    def scalar(self, sql):
        with self.engine.connect() as c:
            return c.execute(text(sql)).scalar_one()

    def test_existing_users_have_no_default_pin(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM payment_pin_credentials"), 0)
        status = self.client.get('/security/status', headers=self.headers[0]).json()
        self.assertFalse(status['pin_configured'])
        self.fund()
        response = self.send(str(uuid4()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'PIN_NOT_CONFIGURED')
        self.assertEqual(self.balances()[0], Decimal(1000))

    def test_pin_setup_hash_and_duplicate_prevention(self):
        result = self.setup_pin()
        self.assertEqual(result.status_code, 201, result.text)
        self.assertNotIn(TEST_PIN, result.text)
        hashed = self.scalar("SELECT pin_hash FROM payment_pin_credentials")
        self.assertTrue(hashed.startswith('$argon2id$'))
        self.assertTrue(password_hasher.verify(TEST_PIN, hashed))
        self.assertEqual(self.setup_pin().status_code, 409)

    def test_weak_and_malformed_pins_rejected(self):
        for value in ['000000', '123456', '111111', '654321', '121212', '123123', '112233', '123321', '12345', '1234567', 'abcdef', '１２３４５６', 482951]:
            response = self.setup_pin(pin=value)
            self.assertEqual(response.status_code, 422, str(value))
            self.assertNotIn(str(value), response.text)

    def test_setup_requires_account_password(self):
        self.assertEqual(self.setup_pin(password='wrong-password').status_code, 400)
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_pin_credentials'), 0)
        self.assertEqual(self.client.post('/security/pin', json={'pin': TEST_PIN, 'password': PASSWORD}).status_code, 401)

    def test_authorization_is_digest_only_and_bound(self):
        key, token = self.ready()
        with Session(self.engine) as db:
            record = db.scalar(select(PaymentAuthorization))
            self.assertEqual(record.token_digest, hashlib.sha256(token.encode()).hexdigest())
            self.assertEqual(record.idempotency_key, key)
            self.assertEqual(record.amount, Decimal(10))
            self.assertEqual(record.source_account_id, self.accounts[0]['id'])
            self.assertIsNone(record.consumed_at)
        self.assertEqual(self.send(key, token=token).status_code, 201)
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_authorizations WHERE consumed_at IS NOT NULL'), 1)
        self.assert_reconciled()

    def test_wrong_pin_and_temporary_lockout(self):
        self.setup_pin()
        key = str(uuid4())
        for attempt in range(settings.pin_attempts):
            result = self.grant(key, pin='135790')
            self.assertEqual(result.status_code, 423 if attempt == settings.pin_attempts-1 else 400)
        self.assertEqual(self.grant(key).status_code, 423)
        self.assertEqual(self.scalar("SELECT count(*) FROM security_audit_events WHERE event_type='PIN_LOCKED'"), 1)
        with self.engine.begin() as c:
            c.execute(text("UPDATE payment_pin_credentials SET locked_until=clock_timestamp()-interval '1 second'"))
        recovered = self.client.get('/security/status', headers=self.headers[0]).json()
        self.assertIsNone(recovered['locked_until'])
        self.assertEqual(recovered['remaining_attempts'], settings.pin_attempts)
        self.assertEqual(self.grant(key).status_code, 201)
        self.assertEqual(self.scalar('SELECT failed_attempts FROM payment_pin_credentials'), 0)

    def test_pin_change_revokes_old_grants(self):
        key, token = self.ready()
        response = self.client.post('/security/pin/change', headers=self.headers[0], json={'current_pin': TEST_PIN, 'new_pin': '579248'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.send(key, token=token).json()['code'], 'AUTHORIZATION_MISMATCH')
        grant = self.grant(key, pin='579248')
        self.assertEqual(grant.status_code, 201)
        self.assertEqual(self.send(key, token=grant.json()['authorization_token']).status_code, 201)

    def test_pin_change_requires_current_pin_and_no_reset_route(self):
        self.setup_pin()
        self.assertEqual(self.client.post('/security/pin/change', headers=self.headers[0], json={'current_pin': '135790', 'new_pin': '579248'}).status_code, 400)
        self.assertEqual(self.client.post('/security/pin/reset', headers=self.headers[0], json={'password': PASSWORD, 'pin': '579248'}).status_code, 404)
        self.assertEqual(self.client.post('/security/pin/change', headers=self.headers[0], json={'new_pin': '579248'}).status_code, 422)

    def test_new_payment_requires_authorization_even_with_key(self):
        self.setup_pin(); self.fund()
        result = self.send(str(uuid4()))
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.json()['code'], 'PAYMENT_AUTHORIZATION_REQUIRED')
        self.assertEqual(self.scalar('SELECT count(*) FROM payments'), 1)

    def test_changed_amount_or_destination_cannot_use_grant(self):
        key, token = self.ready()
        for body in [self.body(amount='11.00'), self.body(upi_id=self.accounts[2]['upi_id'])]:
            result = self.send(key, body, token)
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result.json()['code'], 'AUTHORIZATION_MISMATCH')
        self.assertEqual(self.send(key, token=token).status_code, 201)

    def test_changed_source_and_other_user_rejected(self):
        key, token = self.ready()
        second = self.client.post('/accounts', headers=self.headers[0], json={'bank_name': 'Orbit Demo Bank'}).json()
        self.assertEqual(self.send(key, self.body(source_account_id=second['id']), token).json()['code'], 'AUTHORIZATION_MISMATCH')
        self.assertEqual(self.grant(str(uuid4()), self.body(source_account_id=self.accounts[1]['id'])).status_code, 404)
        self.assertEqual(self.send(str(uuid4()), self.body(upi_id=self.accounts[2]['upi_id'], source_account_id=self.accounts[1]['id']), token, user=1).status_code, 403)

    def test_expired_authorization_not_consumed(self):
        key, token = self.ready()
        with self.engine.connect() as c:
            now = c.execute(text('SELECT clock_timestamp()')).scalar_one()
        with patch('payment_policy.clock', return_value=now+timedelta(seconds=settings.authorization_seconds+1)):
            result = self.send(key, token=token)
        self.assertEqual(result.json()['code'], 'AUTHORIZATION_EXPIRED')
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_authorizations WHERE consumed_at IS NOT NULL'), 0)

    def test_grant_cannot_replay_under_another_key(self):
        key, token = self.ready()
        self.assertEqual(self.send(key, token=token).status_code, 201)
        self.assertEqual(self.send(str(uuid4()), token=token).status_code, 403)
        self.assertEqual(self.balances()[0], Decimal('990'))

    def test_committed_retry_needs_no_new_grant(self):
        key, token = self.ready()
        first = self.send(key, token=token)
        replay = self.send(key)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(self.send(key, self.body(amount='20')).status_code, 409)
        self.assertEqual(self.scalar('SELECT transaction_count FROM payment_limit_counters'), 1)

    def test_rollback_does_not_consume_grant_or_daily_allowance(self):
        key, token = self.ready()
        with patch('payments.post_ledger', side_effect=RuntimeError('injected')):
            self.assertEqual(self.send(key, token=token).status_code, 503)
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_authorizations WHERE consumed_at IS NOT NULL'), 0)
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_limit_counters'), 0)
        self.assertEqual(self.send(key, token=token).status_code, 201)
        self.assert_reconciled()

    def test_insufficient_funds_does_not_consume_allowance(self):
        self.setup_pin()
        key = str(uuid4()); token = self.grant(key).json()['authorization_token']
        self.assertEqual(self.send(key, token=token).status_code, 400)
        self.assertEqual(self.scalar('SELECT transaction_count FROM payment_limit_counters'), 0)
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_authorizations WHERE consumed_at IS NOT NULL'), 0)
        self.assert_reconciled()

    def test_single_daily_amount_and_count_limits(self):
        key, token = self.ready()
        for policy in [replace(settings, single_amount=Decimal('9')), replace(settings, daily_amount=Decimal('9')), replace(settings, daily_count=1)]:
            with patch('payment_policy.settings', policy):
                if policy.daily_count == 1:
                    self.assertEqual(self.send(key, token=token).status_code, 201)
                    key = str(uuid4()); token = self.grant(key).json()['authorization_token']
                result = self.send(key, token=token)
                self.assertEqual(result.json()['code'], 'LIMIT_EXCEEDED')
        self.assertEqual(self.scalar('SELECT transaction_count FROM payment_limit_counters'), 1)

    def test_concurrent_daily_limit_enforcement(self):
        self.setup_pin(); self.fund()
        keys = [str(uuid4()), str(uuid4())]
        tokens = [self.grant(key).json()['authorization_token'] for key in keys]
        with patch('payment_policy.settings', replace(settings, daily_amount=Decimal('15'))), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda pair: self.send(pair[0], token=pair[1]), zip(keys, tokens)))
        self.assertEqual(sorted(r.status_code for r in results), [201, 403])
        self.assertEqual(self.balances()[0], Decimal('990'))
        self.assertEqual(self.scalar('SELECT transaction_count FROM payment_limit_counters'), 1)
        self.assert_reconciled()

    def test_concurrent_duplicate_grant_consumed_once(self):
        key, token = self.ready()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.send(key, token=token), range(2)))
        self.assertEqual([r.status_code for r in results], [201, 201])
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_authorizations WHERE consumed_at IS NOT NULL'), 1)

    def test_velocity_block_and_risk_audit(self):
        key, token = self.ready()
        self.assertEqual(self.send(key, token=token).status_code, 201)
        second = str(uuid4()); grant = self.grant(second).json()['authorization_token']
        with patch('payment_policy.settings', replace(settings, risk_velocity=1)):
            result = self.send(second, token=grant)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.json()['code'], 'RISK_BLOCKED')
        self.assertNotIn('transaction_id', result.json())
        self.assertEqual(self.scalar("SELECT count(*) FROM fraud_risk_decisions WHERE decision='BLOCK'"), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM security_audit_events WHERE event_type='RISK_RULE_TRIGGERED'"), 1)

    def test_large_amount_block(self):
        key, token = self.ready()
        with patch('payment_policy.settings', replace(settings, risk_large=Decimal('10'))):
            self.assertEqual(self.send(key, token=token).json()['code'], 'RISK_BLOCKED')

    def test_many_recipient_signal(self):
        key, token = self.ready(); self.send(key, token=token)
        body = self.body(upi_id=self.accounts[2]['upi_id'])
        second = str(uuid4()); grant = self.grant(second, body).json()['authorization_token']
        with patch('payment_policy.settings', replace(settings, risk_distinct=1)):
            self.assertIn('MANY_RECIPIENTS', self.send(second, body, grant).json()['rules'])

    def test_insufficient_funds_signal(self):
        self.setup_pin()
        key = str(uuid4()); token = self.grant(key).json()['authorization_token']
        self.send(key, token=token); self.fund()
        second = str(uuid4()); token = self.grant(second).json()['authorization_token']
        with patch('payment_policy.settings', replace(settings, risk_insufficient=1)):
            self.assertIn('REPEATED_INSUFFICIENT_FUNDS', self.send(second, token=token).json()['rules'])

    def test_pin_rate_limit(self):
        self.setup_pin()
        with patch('pin_security.settings', replace(settings, pin_per_minute=1)):
            self.assertEqual(self.grant(str(uuid4())).status_code, 429)

    def test_login_and_registration_rate_limits_ignore_forwarded_headers(self):
        with patch('main.settings', replace(settings, login_per_ip=2, register_per_ip=1)):
            for index in range(3):
                response = self.client.post('/login', json={'email': 'unknown@example.com', 'password': 'unknown'}, headers={'X-Forwarded-For': f'192.0.2.{index}'})
                self.assertEqual(response.status_code, 429 if index == 2 else 401)
            self.assertIn('Retry-After', response.headers)
            body = {'full_name': 'Demo', 'email': 'extra@example.com', 'password': PASSWORD}
            self.assertEqual(self.client.post('/register', json=body).status_code, 201)
            body['email'] = 'different@example.com'
            self.assertEqual(self.client.post('/register', json=body).status_code, 429)

    def test_payment_rate_limit_and_replay_bypass(self):
        key, token = self.ready()
        with patch('security_settings.settings', replace(settings, submit_per_minute=1)):
            # Funding has already used one new-submission slot in the shared bucket.
            self.assertEqual(self.send(key, token=token).status_code, 429)
        self.assertEqual(self.send(key, token=token).status_code, 201)
        with patch('security_settings.settings', replace(settings, submit_per_minute=1)):
            self.assertEqual(self.send(key).status_code, 201)

    def test_lookup_limit_is_audited(self):
        for _ in range(11):
            response = self.client.post('/payments/resolve', headers=self.headers[0], json={'upi_id': self.accounts[1]['upi_id']})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.scalar("SELECT count(*) FROM security_audit_events WHERE event_type='RATE_LIMIT_EXCEEDED'"), 1)

    def test_daily_request_cap_and_velocity(self):
        body = {'upi_id': self.accounts[1]['upi_id'], 'amount': '10.00', 'note': 'Demo'}
        def create():
            return self.client.post('/payment-requests', headers={**self.headers[0], 'Idempotency-Key': str(uuid4())}, json=body)
        self.assertEqual(create().status_code, 201)
        with patch('request_limits.settings', replace(settings, requests_per_day=1)):
            self.assertEqual(create().status_code, 429)
        with patch('request_limits.settings', replace(settings, risk_requests=1)):
            self.assertEqual(create().status_code, 429)

    def test_no_secrets_or_private_subjects_in_audit(self):
        key, token = self.ready(); self.send(key, token=token)
        self.client.post('/login', json={'email': 'learner0@example.com', 'password': 'wrong-password'})
        with self.engine.connect() as c:
            serialized = str(c.execute(text('SELECT to_jsonb(e)::text FROM security_audit_events e')).scalars().all())
        for secret in [TEST_PIN, PASSWORD, token, self.headers[0]['Authorization'], 'learner0@example.com', 'wrong-password']:
            self.assertNotIn(secret, serialized)

    def test_security_events_are_owner_only_and_paginated(self):
        self.setup_pin()
        self.assertEqual(self.client.get('/security/events').status_code, 401)
        self.assertEqual(self.client.get('/security/events', headers=self.headers[1]).json()['items'], [])
        item = self.client.get('/security/events?limit=1', headers=self.headers[0]).json()['items'][0]
        self.assertEqual(self.client.get('/security/events?before='+item['id'], headers=self.headers[1]).status_code, 404)

    def test_all_payment_entry_points_require_grants(self):
        self.setup_pin(); self.fund()
        second = self.client.post('/accounts', headers=self.headers[0], json={'bank_name': 'Orbit Demo Bank'}).json()
        recharge = {'mobile': '9876543210', 'plan_id': 'payflow-mobile-99', 'source_account_id': self.accounts[0]['id']}
        bill = self.client.post('/bills/lookup', headers=self.headers[0], json={'biller_id': 'electric', 'reference': 'DEMO000001'}).json()
        request = self.client.post('/payment-requests', headers={**self.headers[1], 'Idempotency-Key': str(uuid4())}, json={'upi_id': self.accounts[0]['upi_id'], 'amount': '10.00'}).json()
        cases = [('/payments/transfer', self.body(channel='QR')), ('/payments/self-transfer', {'source_account_id': self.accounts[0]['id'], 'destination_account_id': second['id'], 'amount': '10.00'}),
            ('/recharge', recharge), ('/bills/'+bill['id']+'/pay', {'source_account_id': self.accounts[0]['id']}), ('/payment-requests/'+request['id']+'/pay', {})]
        for path, body in cases:
            result = self.send(str(uuid4()), body, path=path)
            self.assertEqual(result.status_code, 403, path+result.text)
        self.assertEqual(self.balances()[0], Decimal(1000))
        self.assert_reconciled()

    def test_direct_db_posting_without_authorization_rejected(self):
        self.fund()
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("""INSERT INTO payments(id,actor_user_id,sender_account_id,recipient_account_id,amount,currency,type,status,sender_name,recipient_name,note)
                VALUES ('unapproved',1,1,2,1,'INR','TRANSFER','SUCCESS','Demo','Demo','')"""))
            c.execute(text("INSERT INTO ledger_entries(payment_id,ledger_account_id,amount) VALUES ('unapproved','bank-1',-1),('unapproved','bank-2',1)"))
            c.execute(text('UPDATE bank_accounts SET balance=CASE WHEN id=1 THEN balance-1 WHEN id=2 THEN balance+1 ELSE balance END'))

    def test_grant_is_bound_to_note_and_qr_channel(self):
        key, token = self.ready()
        self.assertEqual(self.send(key, self.body(note='Different'), token).json()['code'], 'AUTHORIZATION_MISMATCH')
        self.assertEqual(self.send(key, self.body(channel='QR'), token).json()['code'], 'AUTHORIZATION_MISMATCH')
        self.assertEqual(self.send(key, token=token).status_code, 201)

    def test_default_source_cannot_change_after_grant(self):
        body = self.body(); body.pop('source_account_id')
        key, token = self.ready(body)
        second = self.client.post('/accounts', headers=self.headers[0], json={'bank_name': 'Orbit Demo Bank'}).json()
        self.client.patch('/accounts/'+str(second['id'])+'/primary', headers=self.headers[0])
        self.assertEqual(self.send(key, body, token).json()['code'], 'AUTHORIZATION_MISMATCH')
        self.assertEqual(self.balances()[0], Decimal(1000))

    def test_other_configured_user_cannot_use_stolen_grant(self):
        key, token = self.ready()
        self.setup_pin(user=1); self.fund(user=1)
        body = self.body(upi_id=self.accounts[2]['upi_id'], source_account_id=self.accounts[1]['id'])
        response = self.send(str(uuid4()), body, token, user=1)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'PAYMENT_AUTHORIZATION_REQUIRED')
        self.assertEqual(self.send(key, token=token).status_code, 201)

    def test_utc_daily_reset_and_counter_reconciliation(self):
        key, token = self.ready(); self.send(key, token=token)
        from payment_policy import day_boundary
        with self.engine.connect() as c:
            now = c.execute(text('SELECT clock_timestamp()')).scalar_one()
        future = day_boundary(now) + timedelta(days=1, seconds=1)
        next_key = str(uuid4())
        with patch('pin_security.clock', return_value=future):
            grant = self.grant(next_key)
        self.assertEqual(grant.status_code, 201, grant.text)
        with patch('payment_policy.clock', return_value=future), patch('security_events.clock', return_value=future):
            # execute_payment imports the same clock at call time.
            self.assertEqual(self.send(next_key, token=grant.json()['authorization_token']).status_code, 201)
        self.assertEqual(self.scalar('SELECT count(*) FROM payment_limit_counters'), 2)
        self.assert_reconciled()

    def test_rate_store_failure_is_fail_closed_but_committed_replay_survives(self):
        from sqlalchemy.exc import SQLAlchemyError
        key, token = self.ready(); first = self.send(key, token=token)
        new_key = str(uuid4()); new_token = self.grant(new_key).json()['authorization_token']
        with patch('security_events.clock', side_effect=SQLAlchemyError('injected store failure')):
            self.assertEqual(self.send(new_key, token=new_token).status_code, 503)
            self.assertEqual(self.send(key).json(), first.json())
        self.assertEqual(self.scalar('SELECT transaction_count FROM payment_limit_counters'), 1)

    def test_authorization_terms_are_immutable(self):
        self.ready()
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(text("UPDATE payment_authorizations SET amount=1"))

    def test_new_contact_signal_is_explainable_medium_allow(self):
        key, token = self.ready()
        self.client.post('/contacts', headers=self.headers[0], json={'upi_id': self.accounts[1]['upi_id']})
        self.send(key, token=token)
        next_key = str(uuid4()); grant = self.grant(next_key).json()['authorization_token']
        with patch('payment_policy.settings', replace(settings, risk_new_contact=1)):
            self.assertEqual(self.send(next_key, token=grant).status_code, 201)
        self.assertEqual(self.scalar("SELECT count(*) FROM fraud_risk_decisions WHERE risk_level='MEDIUM' AND decision='ALLOW'"), 1)

    def test_server_price_change_requires_new_authorization(self):
        body = {'mobile': '9876543210', 'plan_id': 'payflow-mobile-99', 'source_account_id': self.accounts[0]['id']}
        key, token = self.ready(body, 'MOBILE_RECHARGE')
        with self.engine.begin() as c:
            c.execute(text("UPDATE demo_recharge_plans SET price=199 WHERE id='payflow-mobile-99'"))
        self.assertEqual(self.send(key, body, token, '/recharge').json()['code'], 'AUTHORIZATION_MISMATCH')
        fresh = self.grant(key, body, 'MOBILE_RECHARGE').json()['authorization_token']
        result = self.send(key, body, fresh, '/recharge')
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()['amount'], '199.00')
        self.assert_reconciled()

    def test_retention_preview_does_not_remove_events(self):
        from security_retention import retention
        self.setup_pin()
        count = self.scalar('SELECT count(*) FROM security_audit_events')
        with Session(self.engine) as db:
            summary = retention(db)
        self.assertIn('security_audit_events', summary)
        self.assertEqual(self.scalar('SELECT count(*) FROM security_audit_events'), count)

    def test_concurrent_same_key_uses_only_one_submission_rate_slot(self):
        key, token = self.ready()
        with patch('security_settings.settings', replace(settings, submit_per_minute=2)), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.send(key, token=token), range(2)))
        self.assertEqual([r.status_code for r in results], [201, 201])
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(self.scalar("SELECT sum(attempts) FROM security_rate_windows WHERE bucket='payment-submit'"), 2)
        self.assert_reconciled()
