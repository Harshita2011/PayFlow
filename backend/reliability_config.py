"""Small validated limits; no secrets or mutable money live in process-local state."""
import os
from security_settings import integer

POOL_SIZE = integer('DB_POOL_SIZE', 5, maximum=50)
POOL_OVERFLOW = integer('DB_MAX_OVERFLOW', 5, minimum=0, maximum=50)
POOL_TIMEOUT = integer('DB_POOL_TIMEOUT_SECONDS', 5, maximum=60)
POOL_RECYCLE = integer('DB_POOL_RECYCLE_SECONDS', 1800, maximum=86400)
STATEMENT_MS = integer('DB_STATEMENT_TIMEOUT_MS', 15000, maximum=120000)
LOCK_MS = integer('DB_LOCK_TIMEOUT_MS', 5000, maximum=30000)
CONNECT_SECONDS = integer('DB_CONNECT_TIMEOUT_SECONDS', 5, maximum=30)
OUTBOX_BATCH = integer('OUTBOX_BATCH_SIZE', 10, maximum=100)
OUTBOX_LEASE = integer('OUTBOX_LEASE_SECONDS', 30, maximum=600)
OUTBOX_ATTEMPTS = integer('OUTBOX_MAX_ATTEMPTS', 5, maximum=20)
OUTBOX_POLL = integer('OUTBOX_POLL_SECONDS', 1, maximum=60)
OPS_TOKEN = os.getenv('PAYFLOW_OPS_TOKEN', '')
if OPS_TOKEN and len(OPS_TOKEN.encode()) < 32:
    raise RuntimeError('PAYFLOW_OPS_TOKEN must be empty (disabled) or at least 32 bytes')
