import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from config import DATABASE_URL
from models import User


@unittest.skipUnless(os.getenv("REGISTER_TEST_POSTGRES") == "1", "Requires PostgreSQL")
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.schema = "phase3_test_" + uuid4().hex
        self.connection.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.connection.exec_driver_sql(f'SET LOCAL search_path TO "{self.schema}"')
        self.config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        self.config.attributes["connection"] = self.connection

    def tearDown(self):
        # The new schema and all test rows disappear by rolling back their creation.
        self.transaction.rollback()
        self.connection.close()
        self.engine.dispose()

    def test_fresh_database_and_repeat_upgrade(self):
        command.upgrade(self.config, "head")
        command.upgrade(self.config, "head")
        inspector = inspect(self.connection)
        self.assertEqual(set(inspector.get_table_names()), {"users", "bank_accounts", "alembic_version"})
        balance = next(c for c in inspector.get_columns("bank_accounts") if c["name"] == "balance")
        self.assertEqual((balance["type"].precision, balance["type"].scale), (18, 2))
        self.assertEqual(self.connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0002_bank_accounts")
        command.check(self.config)

    def test_existing_users_are_adopted_without_changes(self):
        User.__table__.create(self.connection)
        self.connection.execute(User.__table__.insert().values(
            full_name="Migration Learner", email="migration@example.com", password_hash="test-only-hash"
        ))
        before = self.connection.execute(User.__table__.select()).all()
        command.upgrade(self.config, "head")
        after = self.connection.execute(User.__table__.select()).all()
        self.assertEqual(before, after)
        self.assertTrue(inspect(self.connection).has_table("bank_accounts"))
