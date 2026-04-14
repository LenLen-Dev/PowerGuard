"""Queued email notifier to smooth burst traffic and retry on failures."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from app.notifiers.base import Notifier
from app.notifiers.email import EmailNotifierError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _QueuedEmailTask:
    title: str
    message: str


class QueuedEmailNotifier(Notifier):
    """Queue email notifications and deliver them in a background worker."""

    def __init__(
        self,
        downstream: Notifier,
        *,
        max_queue_size: int,
        put_timeout_seconds: float,
        max_attempts: int,
        retry_backoff_seconds: float,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be greater than 0")
        if put_timeout_seconds <= 0:
            raise ValueError("put_timeout_seconds must be greater than 0")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than 0")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be greater than or equal to 0")

        self._downstream = downstream
        self._queue: queue.Queue[_QueuedEmailTask] = queue.Queue(maxsize=max_queue_size)
        self._put_timeout_seconds = put_timeout_seconds
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, name="email-queue-worker", daemon=True)
        self._worker.start()

    def send(self, title: str, message: str) -> None:
        task = _QueuedEmailTask(title=title, message=message)
        try:
            self._queue.put(task, timeout=self._put_timeout_seconds)
        except queue.Full as exc:
            raise EmailNotifierError(
                "Email queue is full. Increase EMAIL_QUEUE_MAX_SIZE or reduce alert burst."
            ) from exc

        logger.info("Email task queued (pending=%s)", self._queue.qsize())

    def close(self, timeout_seconds: float | None = None) -> None:
        """Stop worker after current queue is drained."""
        self._stop_event.set()
        self._worker.join(timeout=timeout_seconds)

    def _worker_loop(self) -> None:
        while True:
            if self._stop_event.is_set() and self._queue.empty():
                return
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._deliver_with_retry(task)
            except Exception:  # noqa: BLE001 - avoid worker crash on one bad task
                logger.exception("Queued email delivery failed after retries")
            finally:
                self._queue.task_done()

    def _deliver_with_retry(self, task: _QueuedEmailTask) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                self._downstream.send(task.title, task.message)
                logger.info("Queued email sent successfully (attempt=%s)", attempt)
                return
            except Exception as exc:  # noqa: BLE001 - retry needs broad exception handling
                last_error = exc
                if attempt < self._max_attempts:
                    logger.warning(
                        "Queued email send failed (attempt=%s/%s), retrying: %s",
                        attempt,
                        self._max_attempts,
                        exc,
                    )
                    if self._retry_backoff_seconds > 0:
                        time.sleep(self._retry_backoff_seconds)
                else:
                    logger.error(
                        "Queued email send failed (attempt=%s/%s), giving up: %s",
                        attempt,
                        self._max_attempts,
                        exc,
                    )

        raise EmailNotifierError(f"Queued email delivery exhausted retries: {last_error}")
