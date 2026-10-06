"""Convert nanosecond integer timestamps to local millisecond text.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("ALTER TABLE measurement RENAME TO measurement_v1")
    connection.exec_driver_sql("ALTER TABLE field RENAME TO field_v1")
    connection.exec_driver_sql("ALTER TABLE sample RENAME TO sample_v1")
    connection.exec_driver_sql(
        "ALTER TABLE sensor_instance RENAME TO sensor_instance_v1"
    )
    connection.exec_driver_sql("DROP INDEX sample_sensor_time_idx")
    connection.exec_driver_sql("""CREATE TABLE sensor_instance (
        id INTEGER PRIMARY KEY, logical_id TEXT NOT NULL, driver TEXT NOT NULL,
        bus_id TEXT NOT NULL, location TEXT NOT NULL,
        config_fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE (logical_id, config_fingerprint))""")
    connection.exec_driver_sql("""INSERT INTO sensor_instance
        SELECT id, logical_id, driver, bus_id, location, config_fingerprint,
        strftime('%Y-%m-%d %H:%M:%f', created_at_ns / 1000000000.0,
        'unixepoch', 'localtime') FROM sensor_instance_v1""")
    connection.exec_driver_sql("""CREATE TABLE field (
        id INTEGER PRIMARY KEY,
        sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
        name TEXT NOT NULL, unit TEXT NOT NULL,
        UNIQUE (sensor_instance_id, name))""")
    connection.exec_driver_sql("INSERT INTO field SELECT * FROM field_v1")
    connection.exec_driver_sql("""CREATE TABLE sample (
        id INTEGER PRIMARY KEY,
        sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
        time TEXT NOT NULL, monotonic_ms INTEGER NOT NULL, boot_id TEXT NOT NULL)""")
    connection.exec_driver_sql("""INSERT INTO sample
        SELECT id, sensor_instance_id,
        strftime('%Y-%m-%d %H:%M:%f', wall_time_ns / 1000000000.0,
        'unixepoch', 'localtime'), CAST(monotonic_ns / 1000000 AS INTEGER), boot_id
        FROM sample_v1""")
    connection.exec_driver_sql("""CREATE TABLE measurement (
        sample_id INTEGER NOT NULL REFERENCES sample(id) ON DELETE CASCADE,
        field_id INTEGER NOT NULL REFERENCES field(id), value REAL NOT NULL,
        PRIMARY KEY (sample_id, field_id))""")
    connection.exec_driver_sql("INSERT INTO measurement SELECT * FROM measurement_v1")
    connection.exec_driver_sql("DROP TABLE measurement_v1")
    connection.exec_driver_sql("DROP TABLE sample_v1")
    connection.exec_driver_sql("DROP TABLE field_v1")
    connection.exec_driver_sql("DROP TABLE sensor_instance_v1")
    connection.exec_driver_sql("DROP TABLE schema_version")
    connection.exec_driver_sql(
        "CREATE INDEX sample_sensor_time_idx ON sample (sensor_instance_id, time)"
    )


def downgrade() -> None:
    raise RuntimeError("timestamp data migration cannot be downgraded safely")
