"""Notifier abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """Abstract base class for all notifiers."""

    @abstractmethod
    def send(self, title: str, message: str) -> None:
        """Send alert message."""
        raise NotImplementedError
