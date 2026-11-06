"""Provision ephemeral GitHub job databases only; never accepts a development/cloud target."""
import os
from pathlib import Path
import secrets
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

if __name__=='__main__':
    source=make_url(os.environ['DATABASE_URL'])
    if os.getenv('CI')!='true' or os.getenv('PAYFLOW_ENV')!='test' or source.host!='127.0.0.1' or source.database!='payflow_ci_anchor':
        raise SystemExit('CI provisioning requires the explicit ephemeral local anchor')
    with psycopg.connect(host=source.host,port=source.port or 5432,user=source.username,password=source.password,
        dbname=source.database,autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname='ci_test'").fetchone():
            raise SystemExit('CI test role already exists; refusing to overwrite credentials')
        target=make_url(os.environ['PAYFLOW_TEST_DATABASE_URL'])
        if target.database!='payflow_ci_tests' or target.username!='ci_test' or target.host!=source.host:
            raise SystemExit('Unexpected CI test target')
        connection.execute(sql.SQL('CREATE ROLE ci_test LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Literal(target.password)))
        connection.execute('CREATE DATABASE payflow_ci_tests OWNER ci_test')
    with Path(os.environ['GITHUB_ENV']).open('a') as stream:
        stream.write('JWT_SECRET_KEY='+secrets.token_hex(32)+'\n')
    print('Ephemeral CI role/database provisioned; generated JWT key was not printed.')
