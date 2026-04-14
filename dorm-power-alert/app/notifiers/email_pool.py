"""Email sender pool with round-robin failover."""

from __future__ import annotations

import logging
import threading
from typing import Sequence

from app.notifiers.base import Notifier
from app.notifiers.email import EmailNotifierError

logger = logging.getLogger(__name__)


class EmailSenderPool(Notifier):
    """Dispatch emails across multiple SMTP notifiers with fallback."""

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        if not notifiers:
            raise ValueError("Email sender pool requires at least one notifier")
        self._notifiers = tuple(notifiers)
        self._lock = threading.Lock()
        self._next_index = 0

    def send(self, title: str, message: str) -> None:
        start_index = self._reserve_start_index()
        failures: list[str] = []

        for offset in range(len(self._notifiers)):
            index = (start_index + offset) % len(self._notifiers)
            notifier = self._notifiers[index]
            try:
                notifier.send(title, message)
                logger.info("Email sender pool delivered via sender #%s", index + 1)
                return
            except Exception as exc:  # noqa: BLE001 - keep failover path robust
                failures.append(f"sender#{index + 1}: {exc}")
                logger.warning("Email sender #%s failed: %s", index + 1, exc)

        raise EmailNotifierError(
            "All email senders failed in sender pool: " + " | ".join(failures)
        )

    def _reserve_start_index(self) -> int:
        with self._lock:
            start_index = self._next_index
            self._next_index = (self._next_index + 1) % len(self._notifiers)
            return start_index
