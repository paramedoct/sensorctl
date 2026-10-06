from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from storage.schema import metadata

config = context.config
connection = config.attributes.get("connection")


def run_migrations_offline() -> None:
    context.configure(
        url="sqlite://",
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    assert isinstance(connection, Connection)
    context.configure(
        connection=connection,
        target_metadata=metadata,
        transaction_per_migration=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
