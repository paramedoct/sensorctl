from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sensorctl.collector import Collector
from sensorctl.config import CollectorConfig
from sensorctl.drivers.registry import DriverRegistry
from sensorctl.model import Sample
from sensorctl.runtime import SampleQueue, StatusWriter
from tests.support import make_mock_config


class ShutdownTest(unittest.TestCase):
    def test_final_status_follows_buffer_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_mock_config(root / "db")
            prepared = DriverRegistry().prepare(config)
            collector = Collector(config, prepared, root / "status.json")

            def read(_transport: object) -> dict[str, float]:
                collector.stop()
                return {"value": 7.0}

            with patch.object(
                prepared.by_sensor_id["counter"], "read", side_effect=read
            ):
                collector.run(install_signal_handlers=False)
            status = json.loads((root / "status.json").read_text())
            self.assertTrue(status["shutdown"]["complete"])
            self.assertEqual(status["shutdown"]["uncommitted_samples"], 0)
            self.assertEqual(status["accepted_samples"], 1)
            self.assertEqual(status["committed_samples"], 1)
            with sqlite3.connect(root / "db") as database:
                self.assertEqual(
                    database.execute("SELECT value FROM measurement").fetchall(),
                    [(7.0,)],
                )

    def test_blocked_read_fails_shutdown_and_cannot_submit_late_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_mock_config(
                root / "db", collector=CollectorConfig(shutdown_timeout_s=1)
            )
            prepared = DriverRegistry().prepare(config)
            collector = Collector(config, prepared, root / "status.json")
            release = threading.Event()
            threads: list[threading.Thread] = []
            queues: list[SampleQueue] = []
            original_close = SampleQueue.close

            def close(results: SampleQueue) -> None:
                queues.append(results)
                original_close(results)

            def read(_transport: object) -> dict[str, float]:
                threads.append(threading.current_thread())
                collector.stop()
                if not release.wait(3):
                    raise TimeoutError("test did not release sensor")
                return {"value": 7.0}

            with (
                patch.object(
                    prepared.by_sensor_id["counter"], "read", side_effect=read
                ),
                patch.object(SampleQueue, "close", close),
                self.assertLogs("sensorctl.collector", level="ERROR"),
            ):
                try:
                    with self.assertRaisesRegex(
                        RuntimeError, "shutdown deadline exceeded"
                    ):
                        collector.run(install_signal_handlers=False)
                    status = json.loads((root / "status.json").read_text())
                    self.assertFalse(status["shutdown"]["complete"])
                    self.assertIn("bus-mock", status["shutdown"]["alive_threads"])
                    self.assertEqual(status["shutdown"]["pending_tasks"], 1)
                finally:
                    release.set()
                    for thread in threads:
                        thread.join(2)
                        self.assertFalse(thread.is_alive())
                    for thread in threading.enumerate():
                        if thread.name == "database-writer":
                            thread.join(2)
            self.assertTrue(queues[0].empty())
            with sqlite3.connect(root / "db") as database:
                self.assertEqual(
                    database.execute("SELECT COUNT(*) FROM sample").fetchone(), (0,)
                )

    def test_blocked_commit_is_reported_as_uncommitted(self) -> None:
        self._check_storage_failure(block=True)

    def test_failed_commit_is_reported_as_uncommitted(self) -> None:
        self._check_storage_failure(block=False)

    def _check_storage_failure(self, *, block: bool) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_mock_config(
                root / "db", collector=CollectorConfig(shutdown_timeout_s=1)
            )
            prepared = DriverRegistry().prepare(config)
            collector = Collector(config, prepared, root / "status.json")
            release = threading.Event()
            threads: list[threading.Thread] = []

            def read(_transport: object) -> dict[str, float]:
                collector.stop()
                return {"value": 7.0}

            def write(*_args: object) -> None:
                threads.append(threading.current_thread())
                if block:
                    if not release.wait(3):
                        raise TimeoutError("test did not release database")
                else:
                    raise OSError("database unavailable")

            with (
                patch.object(
                    prepared.by_sensor_id["counter"], "read", side_effect=read
                ),
                patch("sensorctl.runtime.Database.write_samples", side_effect=write),
                self.assertLogs(level="ERROR"),
            ):
                try:
                    with self.assertRaises(RuntimeError):
                        collector.run(install_signal_handlers=False)
                    status = json.loads((root / "status.json").read_text())
                    self.assertFalse(status["shutdown"]["complete"])
                    self.assertEqual(status["shutdown"]["uncommitted_samples"], 1)
                    self.assertEqual(status["committed_samples"], 0)
                    if block:
                        self.assertIn(
                            "database-writer", status["shutdown"]["alive_threads"]
                        )
                    else:
                        self.assertIn(
                            "database unavailable", str(status["shutdown"]["errors"])
                        )
                finally:
                    release.set()
                    for thread in threads:
                        thread.join(2)
                        self.assertFalse(thread.is_alive())

    def test_status_failure_still_drains_accepted_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_mock_config(
                root / "db",
                collector=CollectorConfig(status_interval_ms=1),
            )
            prepared = DriverRegistry().prepare(config)
            collector = Collector(config, prepared, root / "status.json")
            accepted = threading.Event()
            original_submit = SampleQueue.submit
            original_write = StatusWriter.write

            def submit(results: SampleQueue, sample: Sample) -> None:
                original_submit(results, sample)
                accepted.set()

            def write(writer: StatusWriter) -> None:
                if threading.current_thread() is writer:
                    if not accepted.wait(2):
                        raise TimeoutError("no sample accepted")
                    raise OSError("status unavailable")
                original_write(writer)

            with (
                patch.object(SampleQueue, "submit", submit),
                patch.object(StatusWriter, "write", write),
                self.assertLogs(level="ERROR"),
                self.assertRaisesRegex(RuntimeError, "status unavailable"),
            ):
                collector.run(install_signal_handlers=False)
            status = json.loads((root / "status.json").read_text())
            self.assertFalse(status["shutdown"]["complete"])
            self.assertGreater(status["accepted_samples"], 0)
            self.assertEqual(status["accepted_samples"], status["committed_samples"])
            self.assertEqual(status["shutdown"]["uncommitted_samples"], 0)
