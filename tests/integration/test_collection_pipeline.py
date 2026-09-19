from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from sensors.application import Collector
from sensors.config import (
    AppConfig,
    BusConfig,
    CollectorConfig,
    DatabaseConfig,
    SensorConfig,
)


class CollectionPipelineTest(unittest.TestCase):
    def test_mock_samples_reach_database_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "sensors.db"
            status_path = root / "status.json"
            config = AppConfig(
                1,
                CollectorConfig(
                    queue_size=100,
                    batch_size=2,
                    flush_interval_ms=50,
                    status_interval_ms=50,
                    shutdown_timeout_s=2,
                ),
                DatabaseConfig(database_path),
                {"mock": BusConfig("mock", "mock")},
                (
                    SensorConfig(
                        "counter",
                        "mock",
                        "mock",
                        20,
                        "test",
                        True,
                        options={"start": 5, "step": 2},
                    ),
                ),
            )
            collector = Collector(config, status_path)
            thread = threading.Thread(
                target=collector.run, kwargs={"install_signal_handlers": False}
            )
            thread.start()
            time.sleep(0.25)
            collector.stop()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            connection = sqlite3.connect(database_path)
            values = [
                row[0]
                for row in connection.execute(
                    "SELECT value FROM measurement ORDER BY sample_id"
                )
            ]
            connection.close()
            self.assertGreaterEqual(len(values), 5)
            self.assertEqual(values[:3], [5.0, 7.0, 9.0])
            status = json.loads(status_path.read_text())
            self.assertGreaterEqual(status["sensors"]["counter"]["successful_reads"], 5)
            self.assertIsNotNone(status["last_commit_ns"])
