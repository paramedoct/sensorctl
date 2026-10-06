from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Mapping

from config import AppConfig
from model import Sample, StoredSensor
from runtime.queue import SampleQueue
from runtime.status import RuntimeStats
from storage.database import Database

LOGGER = logging.getLogger(__name__)


class DatabaseWriter(threading.Thread):
    def __init__(
        self,
        config: AppConfig,
        results: SampleQueue,
        stored: Mapping[str, StoredSensor],
        stats: RuntimeStats,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="database-writer", daemon=True)
        self._config = config
        self._results = results
        self._stored = stored
        self._stats = stats
        self._stop_event = stop_event
        self.error: Exception | None = None

    def run(self) -> None:
        batch: list[Sample] = []
        flush_seconds = self._config.collector.flush_interval_ms / 1000
        deadline = time.monotonic() + flush_seconds
        try:
            with Database(self._config.database.path) as database:
                while True:
                    timeout = max(0.0, deadline - time.monotonic())
                    try:
                        sample = self._results.get(timeout=min(timeout, 0.1))
                        if sample is None:
                            self._results.task_done()
                            break
                        batch.append(sample)
                        self._results.task_done()
                    except queue.Empty:
                        if self._results.drained():
                            break
                    now = time.monotonic()
                    should_flush = len(batch) >= self._config.collector.batch_size or (
                        bool(batch) and now >= deadline
                    )
                    if should_flush:
                        self._flush(database, batch)
                    if should_flush or now >= deadline:
                        deadline = now + flush_seconds
                self._flush(database, batch)
        except Exception as error:
            self.error = error
            LOGGER.exception("database writer failed")
            self._stop_event.set()

    def _flush(self, database: Database, batch: list[Sample]) -> None:
        if not batch:
            return
        database.write_samples(batch, self._stored)
        self._stats.committed(batch)
        batch.clear()
