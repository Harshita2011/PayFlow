from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_URL
from reliability_config import POOL_SIZE, POOL_OVERFLOW, POOL_TIMEOUT, POOL_RECYCLE, CONNECT_SECONDS, STATEMENT_MS, LOCK_MS


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=POOL_SIZE, max_overflow=POOL_OVERFLOW, pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    connect_args={"connect_timeout": CONNECT_SECONDS,
                  "options": f"-cstatement_timeout={STATEMENT_MS} -clock_timeout={LOCK_MS} -cidle_in_transaction_session_timeout=30000"},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db


def test_connection():
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT 1")
        )
        return result.scalar_one()
