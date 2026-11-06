"""Browser QA backend: fresh schema in the dedicated test database, never dev payments.

Run from the repository root with backend/.venv/Scripts/python.exe.
Stop with Ctrl+C; schemas are deliberately retained, never dropped.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import multiprocessing as mp
import hmac

backend = Path(__file__).resolve().parents[2] / "backend"
sys.path[:0] = [str(backend), str(backend / "tests")]
os.chdir(backend)

import uvicorn  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from config import DATABASE_URL  # noqa: E402
from main import app  # noqa: E402
from payment_support import PaymentDatabaseTestCase  # noqa: E402
from fastapi import Header, HTTPException  # noqa: E402


def run_worker(url,schema,stop):
    from outbox_worker import run
    worker_engine=create_engine(url,pool_size=2,max_overflow=0,
        connect_args={'connect_timeout':5,'options':f'-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=5000'})
    try: run(worker_engine,stop)
    finally: worker_engine.dispose()


def snapshot():
    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        result = {name: hashlib.sha256(json.dumps(sorted(connection.execute(
            text(f"SELECT row_to_json(t)::text FROM {name} t")
        ).scalars())).encode()).hexdigest() for name in names if inspect(connection).has_table(name)}
    engine.dispose()
    return result


if __name__ == "__main__":
    original = snapshot()
    PaymentDatabaseTestCase.setUpClass()
    fixture = PaymentDatabaseTestCase()
    fixture.auto_authorize = False
    fixture.relax_security_limits = False
    fixture.setUp()
    stop=mp.Event()
    worker=mp.Process(target=run_worker,args=(fixture.test_url.render_as_string(hide_password=False),fixture.schema,stop))
    worker.start()
    key=os.getenv('PAYFLOW_E2E_KEY')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18016,proxy_headers=False,access_log=False))
    if key:
        if len(key)<32: raise RuntimeError('E2E fixture key must have at least 32 characters')
        def authorize(value):
            if not hmac.compare_digest(value.encode(),key.encode()): raise HTTPException(404,'Not found')

        @app.get('/__qa/ready',include_in_schema=False)
        def qa_ready(x_qa_key: str=Header()):
            authorize(x_qa_key)
            return {'isolated':True}

        @app.get('/__qa/drained',include_in_schema=False)
        def drained(x_qa_key: str=Header()):
            authorize(x_qa_key)
            from reconcile import reconcile
            with fixture.engine.connect() as c:
                count=c.scalar(text("SELECT count(*) FROM outbox_events WHERE status<>'PROCESSED'"))
                result=reconcile(c)
            if count: raise HTTPException(503,'Worker has not drained the isolated queue')
            if not result['balanced'] or any(v for k,v in result.items() if k!='balanced'):
                raise HTTPException(503,'Isolated reconciliation failed')
            return {'reconciled':True,'queue_drained':True}

        @app.post('/__qa/stop',include_in_schema=False)
        def qa_stop(x_qa_key: str=Header()):
            authorize(x_qa_key)
            server.should_exit=True
            return {'status':'stopping isolated test fixture'}
    print(f"Browser QA uses {fixture.test_url.database} / {fixture.schema}", flush=True)
    try:
        server.run()
    finally:
        stop.set(); worker.join(20)
        if worker.is_alive():
            worker.terminate(); worker.join()
            raise RuntimeError('Isolated worker did not stop gracefully')
        fixture.assert_reconciled()
        fixture.tearDown()
        fixture.doCleanups()
        unchanged = original == snapshot()
        print(f"Ledger reconciled; development data unchanged: {unchanged}", flush=True)
        if not unchanged:
            raise RuntimeError("Development records changed during browser QA")
