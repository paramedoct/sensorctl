from __future__ import annotations

from hw.transports.base import Transport


class MockTransport(Transport):
    def open(self) -> None:
        pass

    def close(self) -> None:
        pass
