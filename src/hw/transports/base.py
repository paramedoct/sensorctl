from __future__ import annotations

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def open(self) -> None:
        """Open the underlying device."""

    @abstractmethod
    def close(self) -> None:
        """Close the underlying device."""
