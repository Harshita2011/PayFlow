"""Bounded in-process ASGI benchmark, isolated schemas; NOT a network capacity claim."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from sqlalchemy import create_engine, inspect, text
from config import DATABASE_URL
from payment_support import PaymentDatabaseTestCase


def snapshot():
    engine = create_engine(DATABASE_URL, connect_args={'connect_timeout': 5})
    try:
        with engine.connect() as c:
            return {name: hashlib.sha256(json.dumps(sorted(c.execute(text(f'SELECT row_to_json(t)::text FROM "{name}" t')).scalars())).encode()).hexdigest()
                    for name in inspect(c).get_table_names()}
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=18, choices=range(3, 31))
    args = parser.parse_args()
    original = snapshot()
    PaymentDatabaseTestCase.setUpClass()
    case = PaymentDatabaseTestCase()
    case.relax_security_limits = False
    case.setUp()
    try:
        for i in range(3):
            assert case.fund(i).status_code == 201
        def send(i):
            start = time.perf_counter()
            response = case.transfer('1.00', sender=i % 3, recipient=(i + 1) % 3)
            return time.perf_counter() - start, response.status_code
        start = time.perf_counter()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(send, range(args.count)))
        elapsed = time.perf_counter() - start
        latencies = sorted(t * 1000 for t, _ in results)
        case.assert_reconciled()
        with case.engine.connect() as c:
            committed = c.scalar(text("SELECT count(*) FROM payments WHERE type='TRANSFER' AND status='SUCCESS'"))
            db_settings = {key: c.scalar(text('SHOW ' + key)) for key in ['server_version','max_connections','shared_buffers','synchronous_commit','fsync']}
        report = {'kind': 'in-process ASGI + real PostgreSQL + real Argon2 PIN grants',
                  'api_workers': 1, 'load_threads': 2, 'dataset_users': 3, 'source_accounts': 3,
                  'security_overrides': False, 'transactions_attempted': args.count, 'committed_transfers': committed,
                  'seconds': round(elapsed, 3), 'committed_tps': round(committed / elapsed, 3),
                  'p50_ms': round(latencies[int((len(latencies)-1)*.50)], 2),
                  'p95_ms': round(latencies[int((len(latencies)-1)*.95)], 2),
                  'p99_ms': round(latencies[int((len(latencies)-1)*.99)], 2),
                  'errors': sum(code != 201 for _, code in results), 'reconciliation': 'passed',
                  'postgresql': db_settings, 'python': platform.python_version(), 'os': platform.system(),
                  'development_records_unchanged': original == snapshot()}
        assert report['development_records_unchanged']
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
        assert committed == args.count
    finally:
        case.tearDown()
        case.doCleanups()


if __name__ == '__main__':
    main()
