from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sensorctl.model import Sample
from sensorctl.runtime import RuntimeStats, StatusWriter


class StatusWriterTest(unittest.TestCase):
    def test_shutdown_waits_for_periodic_write_before_final_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            entered = threading.Event()
            release = threading.Event()
            results: queue.Queue[Sample | None] = queue.Queue()
            writer = StatusWriter(
                Path(directory) / "status.json",
                RuntimeStats([]),
                results,
                10,
                1,
                stop,
            )
            original_write = writer.write

            def delayed_write() -> None:
                entered.set()
                if not release.wait(2):
                    raise TimeoutError("test did not release status writer")
                original_write()

            with patch.object(writer, "write", side_effect=delayed_write) as write:
                writer.start()
                try:
                    self.assertTrue(entered.wait(2))
                    stop.set()
                    self.assertTrue(writer.is_alive())
                finally:
                    release.set()
                    writer.join(2)
                self.assertFalse(writer.is_alive())
                self.assertIsNone(writer.error)
                self.assertEqual(write.call_count, 1)
                writer.write()
                self.assertEqual(write.call_count, 2)

    def test_write_failure_requests_stop_and_is_reported(self) -> None:
        stop = threading.Event()
        results: queue.Queue[Sample | None] = queue.Queue()
        writer = StatusWriter(Path("unused"), RuntimeStats([]), results, 10, 1, stop)
        error = OSError("status unavailable")
        with (
            patch.object(writer, "write", side_effect=error),
            self.assertLogs("sensorctl.runtime", level="ERROR"),
        ):
            writer.start()
            writer.join(2)
        self.assertFalse(writer.is_alive())
        self.assertTrue(stop.is_set())
        self.assertIs(writer.error, error)
