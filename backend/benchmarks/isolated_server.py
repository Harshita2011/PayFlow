"""Loopback-only benchmark API and optional separate worker; never uses dev financial data."""
import argparse
import hmac
import multiprocessing as mp
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'benchmarks')]
from fastapi import Header, HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
import uvicorn
from payment_support import PaymentDatabaseTestCase, TEST_PIN
from models import User, BankAccount, DemoBank
from security_models import PinCredential
from security import password_hasher, create_access_token
from main import app
from smoke import snapshot


def worker(url,schema,stop):
    from outbox_worker import run
    engine=create_engine(url,pool_size=2,max_overflow=0,pool_timeout=5,
        connect_args={'connect_timeout':5,'options':f'-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=5000'})
    try: run(engine,stop)
    finally: engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    key=os.environ.get('PAYFLOW_BENCH_KEY','')
    if len(key)<32: raise RuntimeError('Set a random PAYFLOW_BENCH_KEY of at least 32 characters')
    users=int(os.environ.get('BENCH_USERS','12'))
    if not 3<=users<=100: raise RuntimeError('BENCH_USERS must be 3..100; larger datasets require reviewed tooling')
    before=snapshot()
    PaymentDatabaseTestCase.setUpClass()
    fixture=PaymentDatabaseTestCase()
    fixture.auto_authorize=False; fixture.relax_security_limits=False
    fixture.setUp()
    password='Benchmark-Learning-Only-2026!'
    password_hash=password_hasher.hash(password); pin_hash=password_hasher.hash(TEST_PIN)
    identities=[]
    with Session(fixture.engine) as db:
        existing=list(db.scalars(select(User).order_by(User.id)))
        for i in range(users):
            user=existing[i] if i<len(existing) else User(full_name=f'Benchmark User {i}',email=f'bench{i}@example.com',password_hash=password_hash)
            db.add(user); user.password_hash=password_hash; db.flush()
            if i>=len(existing):
                db.add(BankAccount(user_id=user.id,bank_name=DemoBank.GROVE.value,
                    account_number='SIM'+str(i+1).zfill(16),upi_id=f'bench-{i}@payflow',is_primary=True))
                db.flush()
            db.add(BankAccount(user_id=user.id,bank_name=DemoBank.ORBIT.value,
                account_number='SIM'+str(1000+i).zfill(16),upi_id=f'bench-second-{i}@payflow',is_primary=False))
            db.add(PinCredential(user_id=user.id,pin_hash=pin_hash))
            db.flush()
            accounts=list(db.scalars(select(BankAccount).where(BankAccount.user_id==user.id).order_by(BankAccount.id)))
            identities.append({'email':user.email,'token':create_access_token(user.id),
                'source':accounts[0].id,'destination':accounts[1].id,'upi':accounts[0].upi_id})
        db.commit()
    for i in range(users):
        from uuid import uuid4
        from payments import execute_payment
        from payment_schemas import DemoFundingRequest
        for _ in range(3):
            with Session(fixture.engine,expire_on_commit=False) as db:
                user=db.scalar(select(User).where(User.email==identities[i]['email']))
                result=execute_payment(db,user,str(uuid4()),'DEMO_FUNDING',DemoFundingRequest())
                assert result.status_code==201

    def authorized(value):
        if not value or not hmac.compare_digest(value,key): raise HTTPException(404,'Not found')

    @app.get('/__benchmark/bootstrap',include_in_schema=False)
    def bootstrap(x_benchmark_key: str=Header()):
        authorized(x_benchmark_key)
        return {'users':identities,'password':password,'pin':TEST_PIN,'isolated':True}

    @app.get('/__benchmark/report',include_in_schema=False)
    def report(x_benchmark_key: str=Header()):
        authorized(x_benchmark_key)
        with fixture.engine.connect() as c:
            return {'committed':c.scalar(text("SELECT count(*) FROM payments WHERE status='SUCCESS' AND type<>'DEMO_FUNDING'")),
                'failed':c.scalar(text("SELECT count(*) FROM payments WHERE status='FAILED'")),
                'outbox':dict(c.execute(text('SELECT status,count(*) FROM outbox_events GROUP BY status')).all()),
                'deadlocks':c.scalar(text('SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()')),
                'connections':c.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()')),
                'lock_waiters':c.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))}

    @app.post('/__benchmark/stop',include_in_schema=False)
    def shutdown(x_benchmark_key: str=Header()):
        authorized(x_benchmark_key)
        server.should_exit=True
        return {'status':'stopping isolated fixture'}

    stop=mp.Event(); process=None
    if args.worker:
        process=mp.Process(target=worker,args=(fixture.test_url.render_as_string(hide_password=False),fixture.schema,stop))
        process.start()
    print(f'Benchmark isolated schema ready: {users} users, {users*2} accounts; loopback :18017',flush=True)
    try:
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18017,proxy_headers=False,access_log=False))
        server.run()
    finally:
        stop.set()
        if process:
            process.join(20)
            if process.is_alive(): raise RuntimeError('Worker did not drain; inspect retained test schema')
        fixture.assert_reconciled()
        fixture.tearDown(); fixture.doCleanups()
        unchanged=before==snapshot()
        print(f'Benchmark ledger reconciled; all development records unchanged: {unchanged}',flush=True)
        assert unchanged


if __name__=='__main__':
    main()
