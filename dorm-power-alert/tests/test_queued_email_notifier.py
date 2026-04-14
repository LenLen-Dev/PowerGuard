"""Tests for queued email notifier behavior."""

from __future__ import annotations

import threading
import unittest

from app.notifiers.base import Notifier
from app.notifiers.queued_email import QueuedEmailNotifier


class _RetryableNotifier(Notifier):
    def __init__(self, *, fail_times: int = 0) -> None:
        self._fail_times = fail_times
        self.calls: list[tuple[str, str]] = []
        self.sent_event = threading.Event()
        self._lock = threading.Lock()

    def send(self, title: str, message: str) -> None:
        with self._lock:
            self.calls.append((title, message))
            if self._fail_times > 0:
                self._fail_times -= 1
                raise RuntimeError("mock temporary failure")
        self.sent_event.set()


class TestQueuedEmailNotifier(unittest.TestCase):
    def test_send_enqueues_and_delivers(self) -> None:
        downstream = _RetryableNotifier()
        queued = QueuedEmailNotifier(
            downstream,
            max_queue_size=8,
            put_timeout_seconds=1,
            max_attempts=2,
            retry_backoff_seconds=0.01,
        )
        self.addCleanup(queued.close)

        queued.send("T1", "M1")

        self.assertTrue(downstream.sent_event.wait(1.0))
        self.assertEqual(downstream.calls, [("T1", "M1")])

    def test_retry_until_success(self) -> None:
        downstream = _RetryableNotifier(fail_times=2)
        queued = QueuedEmailNotifier(
            downstream,
            max_queue_size=8,
            put_timeout_seconds=1,
            max_attempts=3,
            retry_backoff_seconds=0.01,
        )
        self.addCleanup(queued.close)

        queued.send("T2", "M2")

        self.assertTrue(downstream.sent_event.wait(1.0))
        self.assertEqual(
            downstream.calls,
            [("T2", "M2"), ("T2", "M2"), ("T2", "M2")],
        )


if __name__ == "__main__":
    unittest.main()
