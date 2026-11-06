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
        count(*) FILTER (WHERE e.amount=p.amount AND e.ledger_account_id=coalesce(p.settlement_ledger_account_id,'bank-' || p.recipient_account_id))<>1))
        OR (p.status='FAILED' AND count(e.payment_id)<>0)""")).scalars().all()
    self_invalid = connection.execute(text("""SELECT p.id FROM payments p
        JOIN bank_accounts s ON s.id=p.sender_account_id JOIN bank_accounts t ON t.id=p.recipient_account_id
        WHERE p.type='SELF_TRANSFER' AND p.status='SUCCESS' AND
          (s.id=t.id OR s.user_id<>p.actor_user_id OR t.user_id<>p.actor_user_id OR
           (SELECT coalesce(sum(e.amount),0) FROM ledger_entries e JOIN ledger_accounts l ON l.id=e.ledger_account_id
            JOIN bank_accounts a ON a.id=l.bank_account_id WHERE e.payment_id=p.id AND a.user_id=p.actor_user_id)<>0)""")).scalars().all()
    request_invalid = connection.execute(text("""SELECT r.id FROM money_requests r
        LEFT JOIN money_request_destinations d ON d.request_id=r.id LEFT JOIN bank_accounts a ON a.id=d.account_id
        LEFT JOIN payments p ON p.id=r.payment_id LEFT JOIN bank_accounts s ON s.id=p.sender_account_id
        WHERE d.account_id IS NULL OR a.user_id<>r.requester_user_id OR (r.status='PAID' AND
          (p.id IS NULL OR p.status<>'SUCCESS' OR p.type<>'TRANSFER' OR p.amount<>r.amount OR p.note<>r.note
           OR p.recipient_account_id<>d.account_id OR s.user_id<>r.payer_user_id))""")).scalars().all()
    split_invalid = connection.execute(text("""SELECT s.id FROM expense_splits s
        LEFT JOIN expense_split_participants t ON t.split_id=s.id LEFT JOIN money_requests r ON r.id=t.current_request_id
        GROUP BY s.id HAVING coalesce(sum(t.share_amount),0)<>s.total_amount OR
          (s.status='SETTLED' AND count(*) FILTER(WHERE t.user_id<>s.creator_user_id AND r.status='PAID')
             <>count(*) FILTER(WHERE t.user_id<>s.creator_user_id)) OR
          (s.status='OPEN' AND count(*) FILTER(WHERE t.user_id<>s.creator_user_id AND r.status='PAID')
             =count(*) FILTER(WHERE t.user_id<>s.creator_user_id)) OR
          (s.status='CANCELLED' AND count(*) FILTER(WHERE r.status IN ('PENDING','PAID'))>0)""")).scalars().all()
    primary_invalid = connection.execute(text("""SELECT user_id FROM bank_accounts GROUP BY user_id
        HAVING count(*)>4 OR count(*) FILTER(WHERE is_primary)<>1""")).scalars().all()
    service_invalid = connection.execute(text("""SELECT p.id FROM payments p WHERE p.status='SUCCESS' AND (
        (p.type='MOBILE_RECHARGE' AND (SELECT count(*) FROM mobile_recharges r WHERE r.payment_id=p.id AND r.user_id=p.actor_user_id AND r.status='COMPLETED')<>1)
        OR (p.type='BILL_PAYMENT' AND (SELECT count(*) FROM utility_bills b WHERE b.payment_id=p.id AND b.user_id=p.actor_user_id AND b.status='PAID' AND b.amount_due=p.amount)<>1))
        UNION SELECT r.id FROM mobile_recharges r LEFT JOIN payments p ON p.id=r.payment_id WHERE p.id IS NULL OR p.type<>'MOBILE_RECHARGE' OR p.status<>'SUCCESS' OR p.actor_user_id<>r.user_id
        UNION SELECT b.id FROM utility_bills b LEFT JOIN payments p ON p.id=b.payment_id WHERE b.status='PAID' AND (p.id IS NULL OR p.type<>'BILL_PAYMENT' OR p.status<>'SUCCESS' OR p.actor_user_id<>b.user_id OR p.amount<>b.amount_due)""")).scalars().all()
    security_invalid = connection.execute(text("""SELECT a.idempotency_key FROM payment_authorizations a
        LEFT JOIN payments p ON p.id=a.payment_id LEFT JOIN payment_requests r ON r.payment_id=p.id
        WHERE a.consumed_at IS NOT NULL AND (p.id IS NULL OR p.status<>'SUCCESS' OR p.type='DEMO_FUNDING'
          OR p.actor_user_id<>a.user_id OR p.sender_account_id<>a.source_account_id OR p.amount<>a.amount
          OR a.consumed_at>=a.expires_at OR r.key IS DISTINCT FROM a.idempotency_key OR r.fingerprint IS DISTINCT FROM a.fingerprint)
        UNION SELECT c.user_id::text FROM payment_limit_counters c WHERE c.amount<>
          (SELECT coalesce(sum(p.amount),0) FROM payments p WHERE p.actor_user_id=c.user_id AND p.status='SUCCESS'
            AND p.type<>'DEMO_FUNDING' AND (p.created_at AT TIME ZONE 'UTC')::date=c.utc_day)
          OR c.transaction_count<>(SELECT count(*) FROM payments p WHERE p.actor_user_id=c.user_id AND p.status='SUCCESS'
            AND p.type<>'DEMO_FUNDING' AND (p.created_at AT TIME ZONE 'UTC')::date=c.utc_day)""")).scalars().all()
    event_invalid = connection.execute(text("""SELECT e.event_id FROM outbox_events e LEFT JOIN payments p ON p.id=e.payment_id
        WHERE p.id IS NULL OR p.status<>'SUCCESS' OR e.event_type<>'payment.posted.v1'
          OR e.payload::jsonb<>jsonb_build_object('version',1,'payment_id',e.payment_id)
        UNION SELECT n.id FROM activity_notifications n JOIN outbox_events e ON e.event_id=n.event_id
        JOIN payments p ON p.id=n.payment_id LEFT JOIN bank_accounts a ON a.id=p.recipient_account_id
        WHERE e.payment_id<>n.payment_id OR (n.user_id<>p.actor_user_id AND n.user_id IS DISTINCT FROM a.user_id)""")).scalars().all()
    return {"invalid_event_links": event_invalid, "invalid_security_links": security_invalid, "invalid_service_links": service_invalid, "balanced": net == 0, "account_mismatches": mismatches, "invalid_postings": invalid,
        "invalid_self_transfers": self_invalid, "invalid_request_links": request_invalid,
        "invalid_splits": split_invalid, "invalid_primary_accounts": primary_invalid}


if __name__ == "__main__":
    with engine.connect() as connection:
        # Both reads observe one consistent snapshot while payments may be arriving.
        connection.execution_options(isolation_level="REPEATABLE READ")
        result = reconcile(connection)
    print(result)
    raise SystemExit(0 if result["balanced"] and not any(value for key, value in result.items() if key != "balanced") else 1)
