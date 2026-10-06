from __future__ import annotations

from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL, Connection

_HEAD = "0002"
_BASE = "0001"
_LEGACY_V1_COLUMNS = {
    "sensor_instance": {
        "id",
        "logical_id",
        "driver",
        "bus_id",
        "location",
        "config_fingerprint",
        "created_at_ns",
    },
    "sample": {
        "id",
        "sensor_instance_id",
        "wall_time_ns",
        "monotonic_ns",
        "boot_id",
    },
    "field": {"id", "sensor_instance_id", "name", "unit"},
    "measurement": {"sample_id", "field_id", "value"},
}
_CURRENT_COLUMNS = {
    "sensor_instance": {
        "id",
        "logical_id",
        "driver",
        "bus_id",
        "location",
        "config_fingerprint",
        "created_at",
    },
    "sample": {"id", "sensor_instance_id", "time", "monotonic_ms", "boot_id"},
    "field": {"id", "sensor_instance_id", "name", "unit"},
    "measurement": {"sample_id", "field_id", "value"},
}


def upgrade_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(path)))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            revision = _legacy_revision(connection)
            if revision is not None:
                _run_alembic(connection, "stamp", revision)
                connection.commit()
            _run_alembic(connection, "upgrade")
            _validate_current_schema(connection)
            _remove_legacy_version_table(connection)
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
    finally:
        engine.dispose()


def _legacy_revision(connection: Connection) -> str | None:
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    if "alembic_version" in table_names or "schema_version" not in table_names:
        return None
    row = connection.exec_driver_sql("SELECT version FROM schema_version").fetchone()
    if row is None or row[0] not in {1, 2}:
        raise RuntimeError("unsupported legacy database schema version")
    expected = _LEGACY_V1_COLUMNS if row[0] == 1 else _CURRENT_COLUMNS
    for table, columns in expected.items():
        if table not in table_names:
            raise RuntimeError(f"legacy database is missing table {table}")
        actual = {column["name"] for column in inspector.get_columns(table)}
        if not columns <= actual:
            raise RuntimeError(f"legacy database table {table} has an unknown schema")
    return _BASE if row[0] == 1 else _HEAD


def _run_alembic(connection: Connection, action: str, revision: str = "head") -> None:
    config = Config()
    config.attributes["connection"] = connection
    with ExitStack() as stack:
        migration_path = stack.enter_context(
            as_file(files("storage").joinpath("migrations"))
        )
        config.set_main_option("script_location", str(migration_path))
        if action == "stamp":
            command.stamp(config, revision)
        else:
            command.upgrade(config, revision)


def _remove_legacy_version_table(connection: Connection) -> None:
    if "schema_version" in inspect(connection).get_table_names():
        connection.exec_driver_sql("DROP TABLE schema_version")


def _validate_current_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    for table, columns in _CURRENT_COLUMNS.items():
        if table not in table_names:
            raise RuntimeError(f"database is missing table {table}")
        actual = {column["name"] for column in inspector.get_columns(table)}
        if not columns <= actual:
            raise RuntimeError(f"database table {table} has an unknown schema")
    index_names = {index["name"] for index in inspector.get_indexes("sample")}
    if "sample_sensor_time_idx" not in index_names:
        raise RuntimeError("database is missing index sample_sensor_time_idx")
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("database contains foreign key violations")
