"""Real PostgreSQL, isolated data; crash boundaries below are deterministic injection."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session
from payment_support import PaymentDatabaseTestCase
from database import get_db
from main import app
from outbox import claim, deliver, acknowledge, fail
from outbox_models import OutboxEvent
from outbox_worker import run


@unittest.skipUnless(os.getenv('REGISTER_TEST_POSTGRES')=='1','Requires PostgreSQL')
class ReliabilityTests(PaymentDatabaseTestCase):
    def scalar(self,sql):
        with self.engine.connect() as c: return c.scalar(text(sql))

    def claims(self,**kwargs):
        with Session(self.engine,expire_on_commit=False) as db: return claim(db,**kwargs)

    def expire(self):
        with self.engine.begin() as c:
            c.execute(text("UPDATE outbox_events SET locked_until=clock_timestamp()-interval '1 second' WHERE status='PROCESSING'"))

    def test_success_and_event_commit_together_and_payload_is_minimal(self):
        response=self.fund()
        self.assertEqual(response.status_code,201,response.text)
        with Session(self.engine) as db:
            row=db.scalar(select(OutboxEvent))
            self.assertEqual(row.payload,{'version':1,'payment_id':response.json()['transaction_id']})
            self.assertEqual(row.status,'PENDING')
        self.assert_reconciled()

    def test_missing_event_fails_closed_at_database_boundary(self):
        with patch('payments.enqueue_payment'):
            self.assertEqual(self.fund().status_code,503)
        self.assertEqual(self.scalar('SELECT count(*) FROM payments'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM outbox_events'),0)
        self.assert_reconciled()

    def test_crash_before_commit_rolls_back_event_balances_and_grant(self):
        self.fund()
        before=self.balances()
        from payments import post_ledger
        def injected(db,payment):
            post_ledger(db,payment)
            raise RuntimeError('simulated precommit crash')
        with patch('payments.post_ledger',side_effect=injected):
            self.assertEqual(self.transfer().status_code,503)
        self.assertEqual(before,self.balances())
        self.assertEqual(self.scalar('SELECT count(*) FROM outbox_events'),1)
        self.assert_reconciled()

    def test_lost_response_after_commit_same_key_recovers_only_one_event(self):
        self.fund(); key=str(uuid4())
        from payments import JSONResponse
        lost=False
        def response(**kwargs):
            nonlocal lost
            if kwargs.get('status_code')==201 and not lost:
                lost=True; raise RuntimeError('simulated response loss after commit')
            return JSONResponse(**kwargs)
        with patch('payments.JSONResponse',side_effect=response):
            self.assertEqual(self.transfer(key=key).status_code,503)
        recovered=self.transfer(key=key)
        self.assertEqual(recovered.status_code,201,recovered.text)
        self.assertEqual(recovered.headers['Idempotency-Replayed'],'true')
        self.assertEqual(self.transfer(key=key,amount='2.00').status_code,409)
        self.assertEqual(self.scalar('SELECT count(*) FROM outbox_events'),2)
        self.assert_reconciled()

    def test_crash_after_claim_recovers_lease_and_fences_stale_worker(self):
        self.fund(); old=self.claims(lease_seconds=1)[0]
        self.expire(); fresh=self.claims()[0]
        self.assertEqual(old[0],fresh[0]); self.assertNotEqual(old[1],fresh[1])
        with Session(self.engine,expire_on_commit=False) as db:
            self.assertFalse(deliver(db,*old)); self.assertFalse(acknowledge(db,*old))
            self.assertTrue(deliver(db,*fresh)); self.assertTrue(acknowledge(db,*fresh))
        self.assertEqual(self.scalar('SELECT count(*) FROM activity_notifications'),1)
        self.assert_reconciled()

    def test_crash_after_delivery_before_ack_deduplicates_consumer(self):
        self.fund(); old=self.claims()[0]
        with Session(self.engine,expire_on_commit=False) as db: self.assertTrue(deliver(db,*old))
        self.expire(); fresh=self.claims()[0]
        with Session(self.engine,expire_on_commit=False) as db:
            self.assertTrue(deliver(db,*fresh)); self.assertTrue(acknowledge(db,*fresh))
        self.assertEqual(self.scalar('SELECT count(*) FROM activity_notifications'),1)

    def test_lease_is_revalidated_after_waiting_for_row_lock(self):
        self.fund(); item=self.claims(lease_seconds=1)[0]
        connection=self.engine.connect(); transaction=connection.begin()
        connection.execute(text('SELECT event_id FROM outbox_events FOR UPDATE'))
        started=threading.Event()
        def waiter():
            with Session(self.engine,expire_on_commit=False) as db:
                started.set(); return deliver(db,*item)
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(waiter)
            try:
                self.assertTrue(started.wait(2)); time.sleep(1.1)
            finally:
                transaction.rollback(); connection.close()
            self.assertFalse(future.result(timeout=3))
        self.assertEqual(self.scalar('SELECT count(*) FROM activity_notifications'),0)
        fresh=self.claims()[0]
        with Session(self.engine,expire_on_commit=False) as db:
            self.assertTrue(deliver(db,*fresh)); self.assertTrue(acknowledge(db,*fresh))
        self.assert_reconciled()

    def test_duplicate_delivery_has_one_notification_per_participant(self):
        self.fund(); self.transfer()
        for item in self.claims():
            with Session(self.engine,expire_on_commit=False) as db:
                deliver(db,*item); deliver(db,*item); acknowledge(db,*item)
        self.assertEqual(self.scalar('SELECT count(*) FROM activity_notifications'),3)
        self.assert_reconciled()

    def test_bounded_retry_backoff(self):
        self.fund(); item=self.claims()[0]
        with Session(self.engine,expire_on_commit=False) as db: fail(db,*item)
        self.assertEqual(self.claims(),[])
        self.assertEqual(self.scalar("SELECT last_error FROM outbox_events"),'DELIVERY_UNAVAILABLE')
        with self.engine.begin() as c: c.execute(text("UPDATE outbox_events SET available_at=clock_timestamp()-interval '1 second'"))
        self.assertEqual(len(self.claims()),1)

    def test_crashing_at_final_attempt_dead_letters_without_financial_change(self):
        self.fund(); before=self.balances(); self.claims(max_attempts=1); self.expire()
        self.assertEqual(self.claims(max_attempts=1),[])
        self.assertEqual(self.scalar('SELECT status FROM outbox_events'),'DEAD')
        self.assertEqual(before,self.balances()); self.assert_reconciled()

    def test_permanent_failure_is_dead_and_error_is_safe(self):
        self.fund(); item=self.claims()[0]
        with Session(self.engine,expire_on_commit=False) as db: fail(db,*item,permanent=True)
        self.assertEqual(self.scalar('SELECT status FROM outbox_events'),'DEAD')
        self.assertEqual(self.scalar('SELECT last_error FROM outbox_events'),'INVALID_EVENT')

    def test_multiple_workers_claim_disjoint_batches(self):
        for i in range(3): self.fund(i)
        with ThreadPoolExecutor(2) as pool: batches=list(pool.map(lambda _:self.claims(batch=2),range(2)))
        ids=[item[0] for batch in batches for item in batch]
        self.assertEqual(len(ids),3); self.assertEqual(len(set(ids)),3)
        with ThreadPoolExecutor(2) as pool:
            def process(item):
                with Session(self.engine,expire_on_commit=False) as db:
                    return deliver(db,*item) and acknowledge(db,*item)
            self.assertTrue(all(pool.map(process,[item for batch in batches for item in batch])))
        self.assert_reconciled()

    def test_worker_graceful_stop_finishes_current_delivery(self):
        for i in range(3): self.fund(i)
        stop=threading.Event()
        def current(db,*item):
            result=deliver(db,*item); stop.set(); return result
        with patch('outbox_worker.deliver',side_effect=current): run(self.engine,stop)
        self.assertEqual(self.scalar("SELECT count(*) FROM outbox_events WHERE status='PROCESSED'"),1)
        self.expire()
        run(self.engine,threading.Event(),once=True)
        self.assertEqual(self.scalar("SELECT count(*) FROM outbox_events WHERE status='PROCESSED'"),3)

    def test_worker_has_no_financial_writes(self):
        self.fund(); statements=[]
        def capture(conn,cursor,sql,params,context,many): statements.append(sql.lower().strip())
        event.listen(self.engine,'before_cursor_execute',capture)
        try: run(self.engine,threading.Event(),once=True)
        finally: event.remove(self.engine,'before_cursor_execute',capture)
        for sql in statements:
            self.assertFalse(any(sql.startswith(verb+' '+table) for verb in ['update','delete from','insert into']
                for table in ['payments','bank_accounts','ledger_entries','payment_authorizations']))
        self.assert_reconciled()

    def test_notifications_are_private_paginated_and_receipt_linked(self):
        self.fund(); self.transfer(); run(self.engine,threading.Event(),once=True)
        first=self.client.get('/activity/notifications?limit=1',headers=self.headers[0]).json()
        self.assertEqual(len(first['items']),1); self.assertIsNotNone(first['next_cursor'])
        second=self.client.get('/activity/notifications?limit=1&before='+first['next_cursor'],headers=self.headers[0]).json()
        self.assertNotEqual(first['items'][0]['id'],second['items'][0]['id'])
        self.assertEqual(self.client.get('/activity/notifications',headers=self.headers[2]).json()['items'],[])
        self.assertEqual(self.client.get('/activity/notifications?before='+first['next_cursor'],headers=self.headers[2]).status_code,404)
        self.assertEqual(self.client.get('/activity/notifications').status_code,401)

    def test_event_identity_is_immutable(self):
        self.fund()
        with self.assertRaises(IntegrityError),self.engine.begin() as c:
            c.execute(text("UPDATE outbox_events SET payload='{}'::json"))

    def test_health_ready_live_and_unavailable_database(self):
        self.assertEqual(self.client.get('/health/live').status_code,200)
        self.assertEqual(self.client.get('/health/ready').status_code,200)
        class Broken:
            def execute(self,*args): raise OperationalError('safe',{},Exception('secret-db-dsn'))
            def rollback(self): pass
        app.dependency_overrides[get_db]=lambda:Broken()
        try:
            self.assertEqual(self.client.get('/health/live').status_code,200)
            response=self.client.get('/health/ready')
            self.assertEqual(response.status_code,503); self.assertNotIn('secret',response.text)
        finally:
            def override():
                with Session(self.engine,expire_on_commit=False) as db: yield db
            app.dependency_overrides[get_db]=override

    def test_pool_exhaustion_returns_bounded_safe_503(self):
        small=create_engine(self.test_url,pool_size=1,max_overflow=0,pool_timeout=.1,
            connect_args={'options':f'-csearch_path={self.schema}'})
        def override():
            with Session(small) as db: yield db
        held=small.connect(); app.dependency_overrides[get_db]=override
        try:
            start=time.perf_counter()
            result=self.client.get('/accounts',headers=self.headers[0])
            self.assertEqual(result.status_code,503); self.assertLess(time.perf_counter()-start,2)
            self.assertNotIn('QueuePool',result.text)
        finally:
            held.close(); small.dispose()

    def test_statement_timeout_cancels_only_test_query_and_connection_recovers(self):
        with self.engine.connect() as c:
            c.execute(text("SET LOCAL statement_timeout='30ms'"))
            with self.assertRaises(DBAPIError): c.execute(text('SELECT pg_sleep(1)'))
            c.rollback(); self.assertEqual(c.scalar(text('SELECT 1')),1)
        self.assert_reconciled()

    def test_metrics_are_protected_low_cardinality_and_include_backlog(self):
        self.fund()
        self.assertEqual(self.client.get('/metrics').status_code,404)
        with patch('operations.OPS_TOKEN','operator-test-only-'+'x'*32):
            result=self.client.get('/metrics',headers={'X-Ops-Token':'operator-test-only-'+'x'*32})
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('payflow_outbox_events{state="PENDING"} 1',result.text)
        self.assertNotIn(self.accounts[0]['upi_id'],result.text)

    def test_logs_redact_raw_urls_headers_body_and_propagate_correlation(self):
        correlation=str(uuid4())
        with patch('observability.logger.info') as output:
            response=self.client.post('/demo/fund?secret=never-log',json={},headers={**self.headers[0],
                'Idempotency-Key':str(uuid4()),'X-Correlation-ID':correlation,'X-Request-ID':'invalid-secret'})
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.headers['X-Correlation-ID'],correlation)
        logs=' '.join(call.args[0] for call in output.call_args_list)
        for value in ['never-log','invalid-secret',self.headers[0]['Authorization']]: self.assertNotIn(value,logs)
        self.assertIn(correlation,logs)
        self.assertEqual(self.scalar('SELECT correlation_id FROM outbox_events'),correlation)

    def test_application_shutdown_disposes_its_pool(self):
        with patch('main.engine.dispose') as dispose:
            with TestClient(app) as client: self.assertEqual(client.get('/health/live').status_code,200)
            dispose.assert_called_once()

    def test_hot_settlement_concurrent_purchases_reconcile(self):
        for i in [0,1]: self.fund(i)
        def purchase(i):
            return self.client.post('/recharge',json={'mobile':'9876543210','plan_id':'payflow-mobile-99',
                'source_account_id':self.accounts[i]['id']},headers={**self.headers[i],'Idempotency-Key':str(uuid4())})
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(purchase,[0,1]))
        self.assertEqual([r.status_code for r in results],[201,201])
        self.assertEqual(self.scalar("SELECT sum(amount) FROM ledger_entries WHERE ledger_account_id='settlement-recharge'"),198)
        self.assert_reconciled()
