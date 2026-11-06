"""Deployment controls; config tests never connect, database tests use isolated schemas."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from sqlalchemy import text
from config import parse_origins
from test_database import test_target
from payment_support import PaymentDatabaseTestCase
from migration_lock import migration_lock


class ConfigurationTests(unittest.TestCase):
    def config(self,**settings):
        env={**os.environ,'DATABASE_URL':'postgresql://fixture:dummy@127.0.0.1/payflow_anchor',
             'JWT_SECRET_KEY':'fixture-config-key-with-more-than-thirty-two-bytes','PAYFLOW_ENV':'test',
             'CORS_ALLOWED_ORIGINS':'http://localhost:5173','LOG_LEVEL':'WARNING',**settings}
        return subprocess.run([sys.executable,'-B','-c','import config; print("configured")'],
            cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=10)

    def test_development_settings_remain_compatible(self):
        self.assertEqual(self.config().returncode,0)

    def test_provider_postgresql_url_is_normalized(self):
        result=self.config(DATABASE_URL='postgres://fixture:dummy@127.0.0.1/payflow_anchor')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_non_postgresql_configuration_is_rejected(self):
        self.assertNotEqual(self.config(DATABASE_URL='sqlite:///test.db').returncode,0)

    def test_demo_requires_https_origins_and_encrypted_database(self):
        self.assertNotEqual(self.config(PAYFLOW_ENV='demo').returncode,0)
        self.assertNotEqual(self.config(PAYFLOW_ENV='demo',CORS_ALLOWED_ORIGINS='https://demo.invalid').returncode,0)
        result=self.config(PAYFLOW_ENV='demo',CORS_ALLOWED_ORIGINS='https://demo.invalid',
            DATABASE_URL='postgresql://fixture:dummy@127.0.0.1/payflow_anchor?sslmode=require')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_wildcards_credentials_paths_and_preview_globs_are_rejected(self):
        for origin in ['*','https://*.vercel.app','https://user:password@demo.invalid','https://demo.invalid/path','null','https://demo.invalid?token=secret']:
            with self.subTest(origin=origin),self.assertRaises((RuntimeError,ValueError)):
                parse_origins(origin,'demo')

    def test_invalid_mode_and_log_level_fail_startup(self):
        self.assertNotEqual(self.config(PAYFLOW_ENV='production-misspelled').returncode,0)
        self.assertNotEqual(self.config(LOG_LEVEL='DEBUG').returncode,0)

    def test_test_target_rejects_same_database_and_demo_mode(self):
        source='postgresql+psycopg://fixture:dummy@localhost/payflow_guard_tests'
        with self.assertRaises(RuntimeError): test_target(source,'payflow_guard_tests')
        with self.assertRaises(RuntimeError): test_target(source,'payflow_other_tests',environment='demo')

    def test_test_target_requires_verified_name_and_postgres(self):
        with self.assertRaises(RuntimeError):
            test_target('postgresql+psycopg://fixture:dummy@production.invalid/payflow','payflow_ci_tests')
        for name in ['payflow','production','payflow_tests; DROP DATABASE payflow','payflow_test']:
            with self.assertRaises(RuntimeError): test_target('postgresql+psycopg://fixture:dummy@localhost/anchor',name)
        with self.assertRaises(RuntimeError):
            test_target('postgresql+psycopg://fixture:dummy@localhost/anchor','payflow_ci_tests','sqlite:///payflow_ci_tests')

    def test_explicit_dedicated_test_credentials_are_supported(self):
        result=test_target('postgresql+psycopg://app:dummy@localhost/anchor','payflow_ci_tests',
            'postgresql://test_role:dummy@postgres/payflow_ci_tests',environment='test')
        self.assertEqual(result.username,'test_role')
        self.assertEqual(result.drivername,'postgresql+psycopg')


@unittest.skipUnless(os.getenv('REGISTER_TEST_POSTGRES')=='1','Requires PostgreSQL')
class DeploymentDatabaseTests(PaymentDatabaseTestCase):
    def test_concurrent_migration_runners_are_serialized(self):
        with self.engine.connect() as first,self.engine.connect() as second:
            with migration_lock(first):
                with self.assertRaisesRegex(RuntimeError,'Another migration'):
                    with migration_lock(second): self.fail('Second runner entered the migration section')
            with migration_lock(second): self.assertEqual(second.scalar(text('SELECT 1')),1)

    def test_pending_upgrade_requires_expected_revision(self):
        from migrate import release
        with self.engine.connect() as c,patch('migrate.current_revision',return_value='0008_payment_security'):
            with self.assertRaisesRegex(RuntimeError,'approved expected'):
                release(c,apply=True,expected='base')
        self.assertEqual(self.client.get('/health/ready').status_code,200)

    def test_security_headers_and_exact_cors(self):
        response=self.client.get('/health/live',headers={'Origin':'http://localhost:5173'})
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'],'DENY')
        self.assertEqual(response.headers['Access-Control-Allow-Origin'],'http://localhost:5173')
        denied=self.client.get('/health/live',headers={'Origin':'https://attacker.invalid'})
        self.assertNotIn('Access-Control-Allow-Origin',denied.headers)
        with patch('main.ENVIRONMENT','demo'):
            secured=self.client.get('/health/live')
            self.assertIn('max-age=',secured.headers['Strict-Transport-Security'])

    def test_deployment_does_not_mount_fixture_administration(self):
        self.assertEqual(self.client.get('/__benchmark/bootstrap').status_code,404)
        self.assertEqual(self.client.post('/__benchmark/stop').status_code,404)
