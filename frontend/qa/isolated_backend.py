"""Browser QA backend: fresh schema in the dedicated test database, never dev payments.

Run from the repository root with backend/.venv/Scripts/python.exe.
Stop with Ctrl+C; schemas are deliberately retained, never dropped.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

backend = Path(__file__).resolve().parents[2] / "backend"
sys.path[:0] = [str(backend), str(backend / "tests")]
os.chdir(backend)

import uvicorn  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402
from config import DATABASE_URL  # noqa: E402
from main import app  # noqa: E402
from payment_support import PaymentDatabaseTestCase  # noqa: E402


def snapshot():
    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
    names = ["users", "bank_accounts", "payments", "ledger_accounts", "ledger_entries",
             "payment_requests", "recipient_lookup_limits", "alembic_version",
             "contacts", "money_requests", "request_creation_limits"]
    with engine.connect() as connection:
        result = {name: hashlib.sha256(json.dumps(sorted(connection.execute(
            text(f"SELECT row_to_json(t)::text FROM {name} t")
        ).scalars())).encode()).hexdigest() for name in names if inspect(connection).has_table(name)}
    engine.dispose()
    return result


if __name__ == "__main__":
    original = snapshot()
    PaymentDatabaseTestCase.setUpClass()
    fixture = PaymentDatabaseTestCase()
    fixture.setUp()
    print(f"Browser QA uses payflow_phase4_tests / {fixture.schema}", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=18016)
    finally:
        fixture.assert_reconciled()
        fixture.tearDown()
        unchanged = original == snapshot()
        print(f"Ledger reconciled; development data unchanged: {unchanged}", flush=True)
        if not unchanged:
            raise RuntimeError("Development records changed during browser QA")
