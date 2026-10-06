from __future__ import annotations

import json
import logging
import os
import queue
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sensorctl.model import Sample

LOGGER = logging.getLogger(__name__)


@dataclass
class SensorStatus:
    successful_reads: int = 0
    failed_reads: int = 0
    missed_deadlines: int = 0
    dropped_samples: int = 0
    consecutive_failures: int = 0
    backoff_until_ms: int = 0
    last_read_at: str | None = None
    last_recorded_at: str | None = None
    last_error: str | None = None
    pending: bool = False


class RuntimeStats:
    def __init__(self, sensor_ids: list[str]) -> None:
        self._lock = threading.Lock()
        self._sensors = {sensor_id: SensorStatus() for sensor_id in sensor_ids}
        self.started_at = _local_now()
        self.last_commit_at: str | None = None
        self._accepted = 0
        self._committed = 0
        self._shutdown: dict[str, object] | None = None

    def accepted(self) -> None:
        with self._lock:
            self._accepted += 1

    def shutdown(self, alive: list[str], errors: list[str]) -> None:
        with self._lock:
            self._shutdown = {
                "complete": not alive and not errors,
                "alive_threads": alive,
                "errors": list(errors),
                "pending_tasks": sum(s.pending for s in self._sensors.values()),
                "uncommitted_samples": self._accepted - self._committed,
            }

    def dispatch(self, sensor_id: str) -> bool:
        with self._lock:
            status = self._sensors[sensor_id]
            if status.pending:
                status.missed_deadlines += 1
                return False
            status.pending = True
            return True

    def can_run(self, sensor_id: str, now_ms: int) -> bool:
        with self._lock:
            return now_ms >= self._sensors[sensor_id].backoff_until_ms

    def success(self, sensor_id: str, read_at: str) -> bool:
        with self._lock:
            status = self._sensors[sensor_id]
            recovered = status.consecutive_failures > 0
            status.pending = False
            status.successful_reads += 1
            status.consecutive_failures = 0
            status.backoff_until_ms = 0
            status.last_read_at = read_at
            status.last_error = None
            return recovered

    def failure(self, sensor_id: str, error: Exception, now_ms: int) -> None:
        with self._lock:
            status = self._sensors[sensor_id]
            status.pending = False
            status.failed_reads += 1
            status.consecutive_failures += 1
            delay_seconds = min(60, 2 ** (status.consecutive_failures - 1))
            status.backoff_until_ms = now_ms + delay_seconds * 1000
            status.last_error = f"{type(error).__name__}: {error}"

    def dropped(self, sensor_id: str) -> None:
        with self._lock:
            self._sensors[sensor_id].dropped_samples += 1

    def missed(self, sensor_id: str, count: int) -> None:
        with self._lock:
            self._sensors[sensor_id].missed_deadlines += count

    def committed(self, samples: list[Sample]) -> None:
        committed_at = _local_now()
        with self._lock:
            self.last_commit_at = committed_at
            self._committed += len(samples)
            for sample in samples:
                self._sensors[sample.sensor_id].last_recorded_at = sample.time

    def snapshot(self, queue_size: int, queue_capacity: int) -> dict[str, object]:
        with self._lock:
            return {
                "started_at": self.started_at,
                "updated_at": _local_now(),
                "last_commit_at": self.last_commit_at,
                "accepted_samples": self._accepted,
                "committed_samples": self._committed,
                "shutdown": self._shutdown,
                "queue": {"size": queue_size, "capacity": queue_capacity},
                "sensors": {
                    sensor_id: asdict(status)
                    for sensor_id, status in self._sensors.items()
                },
            }


class StatusWriter(threading.Thread):
    def __init__(
        self,
        path: Path,
        stats: RuntimeStats,
        results: queue.Queue[Sample | None],
        capacity: int,
        interval_ms: int,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="status-writer", daemon=True)
        self._path = path
        self._stats = stats
        self._results = results
        self._capacity = capacity
        self._interval = interval_ms / 1000
        self._stop_event = stop_event
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            while not self._stop_event.wait(self._interval):
                self.write()
        except Exception as error:
            self.error = error
            LOGGER.exception("status writer failed")
            self._stop_event.set()

    def write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._stats.snapshot(self._results.qsize(), self._capacity)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n")
        os.replace(temporary, self._path)


def _local_now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="milliseconds")
