"""Isolated backend launcher: independent ephemeral signing key, no dotenv overwrite."""
import os
from pathlib import Path
import secrets
import subprocess
import sys

if __name__=='__main__':
    if os.getenv('PAYFLOW_ENV')=='demo': raise SystemExit('Refusing test execution from demo mode')
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'PAYFLOW_ENV':'test','REGISTER_TEST_POSTGRES':'1',
         'JWT_SECRET_KEY':secrets.token_hex(32),'LOG_LEVEL':os.getenv('LOG_LEVEL','ERROR')}
    env.setdefault('PAYFLOW_TEST_DATABASE','payflow_ci_local_tests')
    print('Running PostgreSQL tests with an independent ephemeral test signing key (not printed).',flush=True)
    raise SystemExit(subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v',*sys.argv[1:]],
        cwd=root/'backend',env=env).returncode)
