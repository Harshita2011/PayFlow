"""Session advisory lock shared by CLI migration runners, held across DDL commits."""
from contextlib import contextmanager
from sqlalchemy import text

LOCK_ID = 746159250012


@contextmanager
def migration_lock(connection):
    if not connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_ID}):
        connection.rollback()
        raise RuntimeError('Another migration runner holds the deployment lock')
    connection.commit()
    try:
        yield
    finally:
        connection.rollback()
        connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_ID})
        connection.commit()
