from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

sensor_instance = sa.Table(
    "sensor_instance",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("logical_id", sa.Text, nullable=False),
    sa.Column("driver", sa.Text, nullable=False),
    sa.Column("bus_id", sa.Text, nullable=False),
    sa.Column("location", sa.Text, nullable=False),
    sa.Column("config_fingerprint", sa.Text, nullable=False),
    sa.Column("created_at", sa.Text, nullable=False),
    sa.UniqueConstraint("logical_id", "config_fingerprint"),
)
field = sa.Table(
    "field",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column(
        "sensor_instance_id",
        sa.Integer,
        sa.ForeignKey("sensor_instance.id"),
        nullable=False,
    ),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("unit", sa.Text, nullable=False),
    sa.UniqueConstraint("sensor_instance_id", "name"),
)
sample = sa.Table(
    "sample",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column(
        "sensor_instance_id",
        sa.Integer,
        sa.ForeignKey("sensor_instance.id"),
        nullable=False,
    ),
    sa.Column("time", sa.Text, nullable=False),
    sa.Column("monotonic_ms", sa.Integer, nullable=False),
    sa.Column("boot_id", sa.Text, nullable=False),
)
sa.Index("sample_sensor_time_idx", sample.c.sensor_instance_id, sample.c.time)
measurement = sa.Table(
    "measurement",
    metadata,
    sa.Column(
        "sample_id",
        sa.Integer,
        sa.ForeignKey("sample.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("field_id", sa.Integer, sa.ForeignKey("field.id"), nullable=False),
    sa.Column("value", sa.Float, nullable=False),
    sa.PrimaryKeyConstraint("sample_id", "field_id"),
)
