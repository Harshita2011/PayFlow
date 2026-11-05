from alembic import context
from sqlalchemy import create_engine, pool

from config import DATABASE_URL
from database import Base
import models  # Register all model metadata for future migration comparisons.
import payment_models
import social_models
import split_models
import commerce_models
import security_models


target_metadata = Base.metadata


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Use online migrations: the users baseline must inspect existing tables")
else:
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        run_migrations(supplied_connection)
    else:
        engine = create_engine(
            DATABASE_URL, poolclass=pool.NullPool, connect_args={"connect_timeout": 5}
        )
        with engine.connect() as connection:
            # Fail rather than wait indefinitely for an application transaction.
            connection.exec_driver_sql("SET lock_timeout = '5s'")
            connection.commit()
            run_migrations(connection)
        engine.dispose()
