from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass

from config import SensorConfig
from hw.drivers.base import SensorDriver
from hw.transports.base import Transport
from model import Sample
from runtime.queue import SampleQueue
from runtime.status import RuntimeStats, _local_now

LOGGER = logging.getLogger(__name__)


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
        results: SampleQueue,
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
                    read_at = ""
                    monotonic_ms = 0
                    values: dict[str, float] | None = None
                    last_error: Exception | None = None
                    for _ in range(self._retries + 1):
                        try:
                            read_at = _local_now()
                            monotonic_ms = time.monotonic_ns() // 1_000_000
                            values = dict(driver.read(self._transport))
                            break
                        except Exception as error:
                            last_error = error
                            if self._stop_event.is_set():
                                break
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
                        read_at,
                        monotonic_ms,
                        self._boot_id,
                        values,
                    )
                    self._results.submit(sample)
                    if self._stats.success(sensor.id, read_at):
                        LOGGER.info("sensor %s recovered", sensor.id)
                except Exception as error:
                    initialized.discard(sensor.id)
                    self._stats.failure(
                        sensor.id, error, time.monotonic_ns() // 1_000_000
                    )
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
                try:
                    driver.close()
                except Exception as error:
                    self.error = error
                    LOGGER.exception("driver cleanup failed")
            try:
                self._transport.close()
            except Exception as error:
                self.error = error
                LOGGER.exception("transport cleanup failed")
