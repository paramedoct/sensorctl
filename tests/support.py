from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from config import (
    AppConfig,
    BusConfig,
    CollectorConfig,
    DatabaseConfig,
    SensorConfig,
)


def make_mock_config(
    database_path: Path,
    *,
    collector: CollectorConfig | None = None,
    interval_ms: int = 100,
    location: str = "test",
    options: Mapping[str, object] | None = None,
) -> AppConfig:
    return AppConfig(
        version=1,
        collector=collector or CollectorConfig(),
        database=DatabaseConfig(database_path),
        buses={"mock": BusConfig("mock", "mock")},
        sensors=(
            SensorConfig(
                id="counter",
                driver="mock",
                bus="mock",
                interval_ms=interval_ms,
                location=location,
                enabled=True,
                options=options or {},
            ),
        ),
    )
