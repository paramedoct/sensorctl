from __future__ import annotations

import unittest
from typing import Any, cast

from runtime import RuntimeStats


class RuntimeStatsTest(unittest.TestCase):
    def status(self, stats: RuntimeStats) -> dict[str, Any]:
        snapshot = stats.snapshot(0, 10)
        sensors = cast(dict[str, dict[str, Any]], snapshot["sensors"])
        return sensors["sensor"]

    def test_failure_uses_exponential_backoff(self) -> None:
        stats = RuntimeStats(["sensor"])
        stats.failure("sensor", RuntimeError("first"), 1_000_000_000)
        self.assertEqual(self.status(stats)["backoff_until_ns"], 2_000_000_000)
        stats.failure("sensor", RuntimeError("second"), 2_000_000_000)
        self.assertEqual(self.status(stats)["backoff_until_ns"], 4_000_000_000)

    def test_pending_read_counts_as_missed(self) -> None:
        stats = RuntimeStats(["sensor"])
        self.assertTrue(stats.dispatch("sensor"))
        self.assertFalse(stats.dispatch("sensor"))
        self.assertEqual(self.status(stats)["missed_deadlines"], 1)

    def test_success_reports_recovery(self) -> None:
        stats = RuntimeStats(["sensor"])
        stats.failure("sensor", RuntimeError("failure"), 1)
        self.assertTrue(stats.success("sensor", 2))
        self.assertFalse(stats.success("sensor", 3))
