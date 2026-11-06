"""Synthetic, isolated EXPLAIN experiment. Not payment throughput or production data."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'benchmarks')]
from sqlalchemy import text
from payment_support import PaymentDatabaseTestCase
from smoke import snapshot


if __name__=='__main__':
    original=snapshot()
    PaymentDatabaseTestCase.setUpClass(); case=PaymentDatabaseTestCase(); case.setUp()
    try:
        with case.engine.begin() as c:
            # Drop only the candidate index in this newly generated TEST schema for comparison.
            # No existing table, row, financial record or development index is removed.
            c.execute(text('DROP INDEX IF EXISTS ix_payments_actor_time'))
            c.execute(text("""INSERT INTO payments(id,actor_user_id,sender_account_id,recipient_account_id,amount,currency,type,status,sender_name,recipient_name,note,created_at)
              SELECT 'plan-sample-'||i,1,1,2,1,'INR','TRANSFER','FAILED','Synthetic','Synthetic','Query sample',
              CURRENT_TIMESTAMP - CASE WHEN i<=19990 THEN interval '30 days' ELSE interval '1 minute' END
              FROM generate_series(1,20000) i"""))
        with case.engine.begin() as c:
            c.execute(text('ANALYZE payments'))
            sql="EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT count(*) FROM payments WHERE actor_user_id=1 AND created_at >= CURRENT_TIMESTAMP-interval '10 minutes'"
            before=c.scalar(text(sql))[0]
            c.execute(text('CREATE INDEX ix_payments_actor_time ON payments(actor_user_id,created_at)'))
            c.execute(text('ANALYZE payments'))
            after=c.scalar(text(sql))[0]
        report={'dataset_rows':20000,'matching_rows':10,'before':before,'after':after,
            'scope':'isolated synthetic FAILED records; query plan only, not payment throughput',
            'development_records_unchanged':original==snapshot()}
        Path('benchmarks/results/query-plan.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'before_ms':before['Execution Time'],'after_ms':after['Execution Time'],
            'before_plan':before['Plan']['Plans'][0]['Node Type'],'after_plan':after['Plan']['Plans'][0]['Node Type']}))
        case.assert_reconciled(); assert report['development_records_unchanged']
    finally:
        case.tearDown(); case.doCleanups()
