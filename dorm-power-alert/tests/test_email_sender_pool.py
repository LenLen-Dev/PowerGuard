"""Tests for email sender pool behavior."""

from __future__ import annotations

import unittest

from app.notifiers.base import Notifier
from app.notifiers.email import EmailNotifierError
from app.notifiers.email_pool import EmailSenderPool


class _RecordingNotifier(Notifier):
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[tuple[str, str]] = []

    def send(self, title: str, message: str) -> None:
        self.calls.append((title, message))
        if self.should_fail:
            raise RuntimeError("mock send failed")


class TestEmailSenderPool(unittest.TestCase):
    def test_round_robin_across_senders(self) -> None:
        n1 = _RecordingNotifier()
        n2 = _RecordingNotifier()
        n3 = _RecordingNotifier()
        pool = EmailSenderPool([n1, n2, n3])

        pool.send("A", "1")
        pool.send("B", "2")
        pool.send("C", "3")

        self.assertEqual(n1.calls, [("A", "1")])
        self.assertEqual(n2.calls, [("B", "2")])
        self.assertEqual(n3.calls, [("C", "3")])

    def test_failover_to_next_sender(self) -> None:
        bad = _RecordingNotifier(should_fail=True)
        good = _RecordingNotifier()
        pool = EmailSenderPool([bad, good])

        pool.send("Alert", "Low balance")

        self.assertEqual(len(bad.calls), 1)
        self.assertEqual(good.calls, [("Alert", "Low balance")])

    def test_raise_if_all_senders_fail(self) -> None:
        n1 = _RecordingNotifier(should_fail=True)
        n2 = _RecordingNotifier(should_fail=True)
        pool = EmailSenderPool([n1, n2])

        with self.assertRaises(EmailNotifierError):
            pool.send("Alert", "Low balance")


if __name__ == "__main__":
    unittest.main()
