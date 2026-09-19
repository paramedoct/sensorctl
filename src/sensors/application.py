from __future__ import annotations

import logging
import queue
import signal
import threading
import time
from pathlib import Path
from types import FrameType

from sensors.config import AppConfig
from sensors.drivers.registry import PreparedDrivers
from sensors.model import Sample
from sensors.runtime import (
    BusWorker,
    DatabaseWriter,
    ReadTask,
    RuntimeStats,
    StatusWriter,
)
from sensors.storage.database import Database
from sensors.transports.base import create_transport

LOGGER = logging.getLogger(__name__)


class Collector:
    def __init__(
        self,
        config: AppConfig,
        prepared: PreparedDrivers,
        status_path: Path = Path("/run/sensors/status.json"),
    ) -> None:
        self._config = config
        self._prepared = prepared
        self._status_path = status_path
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self, install_signal_handlers: bool = True) -> None:
        enabled = self._prepared.sensors
        drivers = self._prepared.by_sensor_id
        if not enabled:
            raise RuntimeError("at least one enabled sensor is required")
        database = Database(self._config.database.path)
        database.open()
        stored = database.register_sensors(self._config, drivers)
        database.close()
        boot_id = _read_boot_id()
        stats = RuntimeStats([sensor.id for sensor in enabled])
        results: queue.Queue[Sample | None] = queue.Queue(
            self._config.collector.queue_size
        )
        bus_tasks: dict[str, queue.Queue[ReadTask | None]] = {
            bus_id: queue.Queue() for bus_id in {sensor.bus for sensor in enabled}
        }
        workers: list[BusWorker] = []
        for bus_id, tasks in bus_tasks.items():
            bus_drivers = {
                sensor.id: drivers[sensor.id]
                for sensor in enabled
                if sensor.bus == bus_id
            }
            worker = BusWorker(
                bus_id,
                create_transport(self._config.buses[bus_id]),
                bus_drivers,
                tasks,
                results,
                stats,
                self._stop_event,
                boot_id,
                self._config.buses[bus_id].retries,
            )
            workers.append(worker)
        writer = DatabaseWriter(self._config, results, stored, stats, self._stop_event)
        status_writer = StatusWriter(
            self._status_path,
            stats,
            results,
            self._config.collector.queue_size,
            self._config.collector.status_interval_ms,
            self._stop_event,
        )
        if install_signal_handlers:
            self._install_signal_handlers()
        writer.start()
        status_writer.start()
        for worker in workers:
            worker.start()
        intervals = {sensor.id: sensor.interval_ms * 1_000_000 for sensor in enabled}
        deadlines = {sensor.id: time.monotonic_ns() for sensor in enabled}
        try:
            while not self._stop_event.is_set():
                now = time.monotonic_ns()
                for sensor in enabled:
                    deadline = deadlines[sensor.id]
                    if now < deadline:
                        continue
                    interval = intervals[sensor.id]
                    periods = (now - deadline) // interval + 1
                    deadlines[sensor.id] = deadline + periods * interval
                    if periods > 1:
                        stats.missed(sensor.id, periods - 1)
                    if not stats.can_run(sensor.id, now):
                        stats.missed(sensor.id, 1)
                        continue
                    if stats.dispatch(sensor.id):
                        bus_tasks[sensor.bus].put_nowait(ReadTask(sensor))
                if writer.error is not None:
                    raise RuntimeError("database writer stopped") from writer.error
                worker_error = next(
                    (worker.error for worker in workers if worker.error is not None),
                    None,
                )
                if worker_error is not None:
                    raise RuntimeError("bus worker stopped") from worker_error
                nearest = min(deadlines.values())
                self._stop_event.wait(
                    min(0.1, max(0.0, (nearest - time.monotonic_ns()) / 1_000_000_000))
                )
        finally:
            self._stop_event.set()
            for tasks in bus_tasks.values():
                tasks.put(None)
            shutdown_deadline = (
                time.monotonic() + self._config.collector.shutdown_timeout_s
            )
            for worker in workers:
                worker.join(max(0.0, shutdown_deadline - time.monotonic()))
            if writer.is_alive():
                try:
                    results.put(
                        None,
                        timeout=max(0.0, shutdown_deadline - time.monotonic()),
                    )
                except queue.Full:
                    LOGGER.error("result queue did not drain before shutdown deadline")
            writer.join(max(0.0, shutdown_deadline - time.monotonic()))
            status_writer.write()
            status_writer.join(max(0.0, shutdown_deadline - time.monotonic()))
        if writer.error is not None:
            raise RuntimeError("database writer failed") from writer.error

    def _install_signal_handlers(self) -> None:
        def handle_signal(signum: int, frame: FrameType | None) -> None:
            del signum, frame
            self.stop()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)


def _read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"
