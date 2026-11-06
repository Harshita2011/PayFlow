"""Fail-closed selection of isolated test targets. No reset/delete API exists."""
import re
from sqlalchemy.engine import make_url


def test_target(source_url, name, explicit_url=None, environment='development'):
    if environment not in {'development','test'}:
        raise RuntimeError('Tests cannot run in the demo environment')
    if not re.fullmatch(r'payflow_[a-z0-9_]+_tests',name):
        raise RuntimeError('Test database names must match payflow_*_tests')
    source = make_url(source_url)
    if not explicit_url and (source.host or '').lower() not in {'localhost','127.0.0.1','::1','postgres'}:
        raise RuntimeError('Remote tests require an explicitly provisioned isolated URL and credentials')
    target = make_url(explicit_url) if explicit_url else source.set(database=name)
    if target.drivername in {'postgres','postgresql'}:
        target = target.set(drivername='postgresql+psycopg')
    if target.drivername != 'postgresql+psycopg' or target.database != name or target.database == source.database:
        raise RuntimeError('Test target must be a separate, explicitly named PostgreSQL database')
    if not target.host or target.username is None:
        raise RuntimeError('Test target must explicitly identify its host and user')
    return target
