from __future__ import annotations

import unittest
from typing import Any, cast

from model import Sample
from runtime import RuntimeStats, SampleQueue


class RuntimeStatsTest(unittest.TestCase):
    def status(self, stats: RuntimeStats) -> dict[str, Any]:
        snapshot = stats.snapshot(0, 10)
        sensors = cast(dict[str, dict[str, Any]], snapshot["sensors"])
        return sensors["sensor"]

    def test_failure_uses_exponential_backoff(self) -> None:
        stats = RuntimeStats(["sensor"])
        stats.failure("sensor", RuntimeError("first"), 1000)
        self.assertEqual(self.status(stats)["backoff_until_ms"], 2000)
        stats.failure("sensor", RuntimeError("second"), 2000)
        self.assertEqual(self.status(stats)["backoff_until_ms"], 4000)

    def test_pending_read_counts_as_missed(self) -> None:
        stats = RuntimeStats(["sensor"])
        self.assertTrue(stats.dispatch("sensor"))
        self.assertFalse(stats.dispatch("sensor"))
        self.assertEqual(self.status(stats)["missed_deadlines"], 1)

    def test_success_reports_recovery(self) -> None:
        stats = RuntimeStats(["sensor"])
        stats.failure("sensor", RuntimeError("failure"), 1)
        self.assertTrue(stats.success("sensor", "2026-09-20 00:00:00.002"))
        self.assertFalse(stats.success("sensor", "2026-09-20 00:00:00.003"))


class SampleQueueTest(unittest.TestCase):
    def test_full_queue_can_close_and_reject_late_samples(self) -> None:
        stats = RuntimeStats(["sensor"])
        results = SampleQueue(1, stats)
        sample = Sample("sensor", "2026-10-06 00:00:00.000", 0, "boot", {"value": 1.0})
        results.submit(sample)
        results.submit(sample)
        results.close()
        results.submit(sample)
        self.assertFalse(results.drained())
        self.assertEqual(results.get_nowait(), sample)
        self.assertTrue(results.drained())
        snapshot = stats.snapshot(0, 1)
        self.assertEqual(snapshot["accepted_samples"], 1)
        sensors = cast(dict[str, dict[str, Any]], snapshot["sensors"])
        self.assertEqual(sensors["sensor"]["dropped_samples"], 2)
