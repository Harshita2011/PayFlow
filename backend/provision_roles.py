"""Permissions for the new local Compose database, never existing dev roles."""
from sqlalchemy import inspect, text


def grant_roles(connection):
    roles=set(connection.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('payflow_app','payflow_worker')")).scalars())
    if roles != {'payflow_app','payflow_worker'}:
        raise RuntimeError('Expected pre-provisioned local Compose roles')
    connection.execute(text('GRANT USAGE ON SCHEMA public TO payflow_app, payflow_worker'))
    for name in inspect(connection).get_table_names(schema='public'):
        identifier=connection.dialect.identifier_preparer.quote(name)
        connection.execute(text(f'GRANT SELECT ON TABLE public.{identifier} TO payflow_app'))
        if name!='alembic_version':
            connection.execute(text(f'GRANT INSERT,UPDATE,DELETE ON TABLE public.{identifier} TO payflow_app'))
    connection.execute(text('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO payflow_app'))
    connection.execute(text('REVOKE UPDATE,DELETE ON payments,ledger_entries,ledger_accounts,security_audit_events,fraud_risk_decisions FROM payflow_app'))
    connection.execute(text('REVOKE DELETE ON bank_accounts,payment_authorizations,payment_limit_counters,outbox_events FROM payflow_app'))
    connection.execute(text('GRANT SELECT ON outbox_events,activity_notifications TO payflow_worker'))
    connection.execute(text('GRANT INSERT ON activity_notifications TO payflow_worker'))
    connection.execute(text('GRANT UPDATE(status,attempt_count,available_at,locked_until,lease_token,processed_at,last_error) ON outbox_events TO payflow_worker'))
    connection.execute(text('GRANT SELECT(id,status,actor_user_id,recipient_account_id) ON payments TO payflow_worker'))
    connection.execute(text('GRANT SELECT(id,user_id) ON bank_accounts TO payflow_worker'))
