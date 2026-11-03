"""Read-only reconciliation. Never repairs or changes balances automatically."""
from sqlalchemy import text

from database import engine


def reconcile(connection):
    mismatches = connection.execute(text("""SELECT a.id FROM bank_accounts a
        WHERE a.balance <> (SELECT coalesce(sum(e.amount),0) FROM ledger_entries e
        JOIN ledger_accounts l ON l.id=e.ledger_account_id WHERE l.bank_account_id=a.id)""")).scalars().all()
    net = connection.execute(text("SELECT coalesce(sum(amount),0) FROM ledger_entries")).scalar_one()
    invalid = connection.execute(text("""SELECT p.id FROM payments p LEFT JOIN ledger_entries e ON e.payment_id=p.id
        GROUP BY p.id HAVING
        (p.status='SUCCESS' AND (count(e.payment_id)<>2 OR coalesce(sum(e.amount),0)<>0 OR
        count(*) FILTER (WHERE e.amount=-p.amount AND e.ledger_account_id=CASE WHEN p.type='DEMO_FUNDING' THEN 'demo-funding' ELSE 'bank-' || p.sender_account_id END)<>1 OR
        count(*) FILTER (WHERE e.amount=p.amount AND e.ledger_account_id='bank-' || p.recipient_account_id)<>1))
        OR (p.status='FAILED' AND count(e.payment_id)<>0)""")).scalars().all()
    return {"balanced": net == 0, "account_mismatches": mismatches, "invalid_postings": invalid}


if __name__ == "__main__":
    with engine.connect() as connection:
        # Both reads observe one consistent snapshot while payments may be arriving.
        connection.execution_options(isolation_level="REPEATABLE READ")
        result = reconcile(connection)
    print(result)
    raise SystemExit(0 if result["balanced"] and not result["account_mismatches"] and not result["invalid_postings"] else 1)
