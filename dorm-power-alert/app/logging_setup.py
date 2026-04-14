"""Logging bootstrap helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime
from app.timezone_utils import BEIJING_TZ


class WeeklyResetFileHandler(logging.FileHandler):
    """A file handler that truncates the same log file when week changes."""

    def __init__(self, filename: str, *, encoding: str = "utf-8") -> None:
        super().__init__(filename=filename, mode="a", encoding=encoding, delay=False)
        self._week_key = self._current_week_key()

    def emit(self, record: logging.LogRecord) -> None:
        self._maybe_reset_weekly()
        super().emit(record)

    def _current_week_key(self) -> str:
        now_bj = datetime.now(BEIJING_TZ)
        iso = now_bj.isocalendar()
        return f"{iso.year}-{iso.week:02d}"

    def _maybe_reset_weekly(self) -> None:
        current = self._current_week_key()
        if current == self._week_key:
            return
        self.acquire()
        try:
            if self.stream:
                self.stream.close()
                self.stream = None
            with open(self.baseFilename, "w", encoding=self.encoding or "utf-8"):
                pass
            self.stream = self._open()
            self._week_key = current
        finally:
            self.release()


def setup_logging(level: str, *, log_file: str | None = None, weekly_reset: bool = False) -> None:
    """Configure logging for console and optional file output."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if weekly_reset:
            file_handler: logging.Handler = WeeklyResetFileHandler(str(log_path))
        else:
            file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
