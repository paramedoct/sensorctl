from __future__ import annotations

import queue
import threading

from sensorctl.model import Sample
from sensorctl.runtime.status import RuntimeStats


class SampleQueue(queue.Queue[Sample | None]):
    """Close producer admission without needing space for a sentinel."""

    def __init__(self, capacity: int, stats: RuntimeStats) -> None:
        super().__init__(capacity)
        self._admission_lock = threading.Lock()
        self._closed = threading.Event()
        self._stats = stats

    def submit(self, sample: Sample) -> None:
        with self._admission_lock:
            if self._closed.is_set():
                self._stats.dropped(sample.sensor_id)
                return
            try:
                self.put_nowait(sample)
            except queue.Full:
                self._stats.dropped(sample.sensor_id)
            else:
                self._stats.accepted()

    def close(self) -> None:
        with self._admission_lock:
            self._closed.set()

    def drained(self) -> bool:
        return self._closed.is_set() and self.empty()
