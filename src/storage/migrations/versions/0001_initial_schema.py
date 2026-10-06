"""Create the original sensor schema.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("schema_version", sa.Column("version", sa.Integer, nullable=False))
    op.execute("INSERT INTO schema_version (version) VALUES (1)")
    op.create_table(
        "sensor_instance",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("logical_id", sa.Text, nullable=False),
        sa.Column("driver", sa.Text, nullable=False),
        sa.Column("bus_id", sa.Text, nullable=False),
        sa.Column("location", sa.Text, nullable=False),
        sa.Column("config_fingerprint", sa.Text, nullable=False),
        sa.Column("created_at_ns", sa.Integer, nullable=False),
        sa.UniqueConstraint("logical_id", "config_fingerprint"),
    )
    op.create_table(
        "field",
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
    op.create_table(
        "sample",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "sensor_instance_id",
            sa.Integer,
            sa.ForeignKey("sensor_instance.id"),
            nullable=False,
        ),
        sa.Column("wall_time_ns", sa.Integer, nullable=False),
        sa.Column("monotonic_ns", sa.Integer, nullable=False),
        sa.Column("boot_id", sa.Text, nullable=False),
    )
    op.create_index(
        "sample_sensor_time_idx", "sample", ["sensor_instance_id", "wall_time_ns"]
    )
    op.create_table(
        "measurement",
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


def downgrade() -> None:
    op.drop_table("measurement")
    op.drop_index("sample_sensor_time_idx", table_name="sample")
    op.drop_table("sample")
    op.drop_table("field")
    op.drop_table("sensor_instance")
    op.drop_table("schema_version")
