from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from sensors.config import AppConfig, SensorConfig
from sensors.drivers.base import SensorDriver
from sensors.model import Sample, StoredSensor
from sensors.storage.database import Database
from sensors.transports.base import Transport

LOGGER = logging.getLogger(__name__)


@dataclass
class SensorStatus:
    successful_reads: int = 0
    failed_reads: int = 0
    missed_deadlines: int = 0
    dropped_samples: int = 0
    consecutive_failures: int = 0
    backoff_until_ns: int = 0
    last_read_ns: int | None = None
    last_recorded_ns: int | None = None
    last_error: str | None = None
    pending: bool = False


class RuntimeStats:
    def __init__(self, sensor_ids: list[str]) -> None:
        self._lock = threading.Lock()
        self._sensors = {sensor_id: SensorStatus() for sensor_id in sensor_ids}
        self.started_at_ns = time.time_ns()
        self.last_commit_ns: int | None = None

    def dispatch(self, sensor_id: str) -> bool:
        with self._lock:
            status = self._sensors[sensor_id]
            if status.pending:
                status.missed_deadlines += 1
                return False
            status.pending = True
            return True

    def can_run(self, sensor_id: str, now_ns: int) -> bool:
        with self._lock:
            return now_ns >= self._sensors[sensor_id].backoff_until_ns

    def success(self, sensor_id: str, wall_time_ns: int) -> bool:
        with self._lock:
            status = self._sensors[sensor_id]
            recovered = status.consecutive_failures > 0
            status.pending = False
            status.successful_reads += 1
            status.consecutive_failures = 0
            status.backoff_until_ns = 0
            status.last_read_ns = wall_time_ns
            status.last_error = None
            return recovered

    def failure(self, sensor_id: str, error: Exception, now_ns: int) -> None:
        with self._lock:
            status = self._sensors[sensor_id]
            status.pending = False
            status.failed_reads += 1
            status.consecutive_failures += 1
            delay_seconds = min(60, 2 ** (status.consecutive_failures - 1))
            status.backoff_until_ns = now_ns + delay_seconds * 1_000_000_000
            status.last_error = f"{type(error).__name__}: {error}"

    def dropped(self, sensor_id: str) -> None:
        with self._lock:
            self._sensors[sensor_id].dropped_samples += 1

    def missed(self, sensor_id: str, count: int) -> None:
        with self._lock:
            self._sensors[sensor_id].missed_deadlines += count

    def committed(self, samples: list[Sample]) -> None:
        committed_at = time.time_ns()
        with self._lock:
            self.last_commit_ns = committed_at
            for sample in samples:
                self._sensors[sample.sensor_id].last_recorded_ns = sample.wall_time_ns

    def snapshot(self, queue_size: int, queue_capacity: int) -> dict[str, object]:
        with self._lock:
            return {
                "started_at_ns": self.started_at_ns,
                "updated_at_ns": time.time_ns(),
                "last_commit_ns": self.last_commit_ns,
                "queue": {"size": queue_size, "capacity": queue_capacity},
                "sensors": {
                    sensor_id: asdict(status)
                    for sensor_id, status in self._sensors.items()
                },
            }


@dataclass(frozen=True)
class ReadTask:
    sensor: SensorConfig


class BusWorker(threading.Thread):
    def __init__(
        self,
        bus_id: str,
        transport: Transport,
        drivers: Mapping[str, SensorDriver],
        tasks: queue.Queue[ReadTask | None],
        results: queue.Queue[Sample | None],
        stats: RuntimeStats,
        stop_event: threading.Event,
        boot_id: str,
        retries: int,
    ) -> None:
        super().__init__(name=f"bus-{bus_id}", daemon=True)
        self._transport = transport
        self._drivers = drivers
        self._tasks = tasks
        self._results = results
        self._stats = stats
        self._stop_event = stop_event
        self._boot_id = boot_id
        self._retries = retries
        self.error: Exception | None = None
        self._last_warning: dict[str, float] = {}

    def run(self) -> None:
        initialized: set[str] = set()
        try:
            self._transport.open()
            while not self._stop_event.is_set() or not self._tasks.empty():
                try:
                    task = self._tasks.get(timeout=0.1)
                except queue.Empty:
                    continue
                if task is None:
                    self._tasks.task_done()
                    break
                sensor = task.sensor
                try:
                    driver = self._drivers[sensor.id]
                    if sensor.id not in initialized:
                        driver.initialize(self._transport)
                        initialized.add(sensor.id)
                    wall_time_ns = 0
                    monotonic_ns = 0
                    values: dict[str, float] | None = None
                    last_error: Exception | None = None
                    for _ in range(self._retries + 1):
                        try:
                            wall_time_ns = time.time_ns()
                            monotonic_ns = time.monotonic_ns()
                            values = dict(driver.read(self._transport))
                            break
                        except Exception as error:
                            last_error = error
                    if values is None:
                        assert last_error is not None
                        raise last_error
                    expected = {definition.name for definition in driver.fields}
                    if set(values) != expected:
                        raise ValueError("driver returned an unexpected field set")
                    if any(not math.isfinite(value) for value in values.values()):
                        raise ValueError("driver returned a non-finite value")
                    sample = Sample(
                        sensor.id,
                        wall_time_ns,
                        monotonic_ns,
                        self._boot_id,
                        values,
                    )
                    try:
                        self._results.put_nowait(sample)
                    except queue.Full:
                        self._stats.dropped(sensor.id)
                    if self._stats.success(sensor.id, wall_time_ns):
                        LOGGER.info("sensor %s recovered", sensor.id)
                except Exception as error:
                    initialized.discard(sensor.id)
                    self._stats.failure(sensor.id, error, time.monotonic_ns())
                    now = time.monotonic()
                    if now - self._last_warning.get(sensor.id, 0.0) >= 60:
                        LOGGER.warning("sensor %s read failed: %s", sensor.id, error)
                        self._last_warning[sensor.id] = now
                finally:
                    self._tasks.task_done()
        except Exception as error:
            self.error = error
            LOGGER.exception("bus worker failed")
        finally:
            for driver in self._drivers.values():
                driver.close()
            self._transport.close()


class DatabaseWriter(threading.Thread):
    def __init__(
        self,
        config: AppConfig,
        results: queue.Queue[Sample | None],
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
                        pass
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

    def run(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        while not self._stop_event.wait(self._interval):
            self.write()
        self.write()

    def write(self) -> None:
        payload = self._stats.snapshot(self._results.qsize(), self._capacity)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n")
        os.replace(temporary, self._path)
