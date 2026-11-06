"""Explicit release migration command; never runs inside API or worker startup."""
import argparse
import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool
from config import DATABASE_URL
from migration_lock import migration_lock


def current_revision(connection):
    if not inspect(connection).has_table('alembic_version'):
        return 'base'
    return connection.scalar(text('SELECT version_num FROM alembic_version')) or 'base'


def release(connection, *, apply=False, expected=None, grant_local=False):
    config=Config(str(Path(__file__).with_name('alembic.ini')))
    config.attributes['connection']=connection
    head=ScriptDirectory.from_config(config).get_current_head()
    with migration_lock(connection):
        current=current_revision(connection)
        connection.commit()
        if apply:
            if not expected:
                raise RuntimeError('An explicit --expected-current revision (or base) is required')
            if current != head and current != expected:
                raise RuntimeError('Current schema differs from the approved expected revision')
            command.upgrade(config,'head')
            connection.commit()
        elif current != head:
            raise RuntimeError('Pending migration; back up and approve an explicit upgrade')
        command.check(config)
        if grant_local:
            if os.getenv('PAYFLOW_LOCAL_ROLE_GRANTS')!='1':
                raise RuntimeError('Local Compose role provisioning was not explicitly enabled')
            from provision_roles import grant_roles
            grant_roles(connection)
        connection.commit()
        return {'revision':head,'upgraded':apply and current!=head}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-current')
    parser.add_argument('--grant-local-roles',action='store_true')
    args=parser.parse_args()
    engine=create_engine(DATABASE_URL,poolclass=NullPool,connect_args={'connect_timeout':5,'options':'-clock_timeout=5000 -cstatement_timeout=120000'})
    try:
        with engine.connect() as connection:
            print(release(connection,apply=args.apply,expected=args.expected_current,grant_local=args.grant_local_roles))
    finally:
        engine.dispose()
