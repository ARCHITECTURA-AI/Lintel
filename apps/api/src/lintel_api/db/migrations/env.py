"""Alembic environment. Migrations run as the database owner, never as lintel_app."""

from alembic import context
from lintel_api.config import get_settings
from lintel_api.db.models import Base
from sqlalchemy import create_engine, pool

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
