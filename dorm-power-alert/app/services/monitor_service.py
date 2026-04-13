"""Core monitoring service."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.clients.electric_client import ElectricClient
from app.config import AppConfig
from app.models import AlertDecision, ElectricReading, QueryResult
from app.notifiers.base import Notifier
from app.parsers.electric_parser import ElectricParser

logger = logging.getLogger(__name__)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class MonitorService:
    """Runs periodic checks and emits alerts with cooldown control."""

    def __init__(
        self,
        config: AppConfig,
        client: ElectricClient,
        parser: ElectricParser,
        notifier: Notifier,
    ) -> None:
        self._config = config
        self._client = client
        self._parser = parser
        self._notifier = notifier

        self._last_alert_time: datetime | None = None
        self._in_low_balance_state = False

    def run_once(self) -> QueryResult:
        """Run one monitor cycle and return query result."""
        payload = self._client.query_room_info()
        reading = self._parser.parse(payload)

        logger.info(
            "Current balance: %.2f | room=%s%s | account=%s | message=%s",
            reading.balance,
            reading.building_name,
            reading.room_name,
            reading.account,
            reading.message,
        )

        decision = self._decide_alert(reading)
        alert_sent = False
        if decision.should_alert:
            if self._is_quiet_hours_beijing():
                # Final safety guard: never send low-balance alerts during quiet hours.
                logger.warning(
                    "Alert suppressed by quiet-hours guard (BJT 00:00-08:00): room=%s%s balance=%.2f",
                    reading.building_name,
                    reading.room_name,
                    reading.balance,
                )
                decision = AlertDecision(False, "quiet_hours_guard_00_to_08_bjt")
            else:
                title, content = self._build_alert_message(reading)
                self._notifier.send(title, content)
                self._last_alert_time = datetime.now(timezone.utc)
                self._in_low_balance_state = True
                alert_sent = True
                logger.warning("Alert sent: %s", decision.reason)
        if not decision.should_alert:
            logger.info("No alert sent: %s", decision.reason)

        return QueryResult(reading=reading, decision=decision, alert_sent=alert_sent)

    def run_forever(self) -> None:
        """Run monitor loop forever."""
        logger.info(
            "Monitor started: interval=%ss threshold=%.2f cooldown=%ss",
            self._config.check_interval_seconds,
            self._config.low_balance_threshold,
            self._config.alert_cooldown_seconds,
        )

        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Monitor cycle failed")
            time.sleep(self._config.check_interval_seconds)

    def _decide_alert(self, reading: ElectricReading) -> AlertDecision:
        now = datetime.now(timezone.utc)
        threshold = self._config.low_balance_threshold

        if reading.balance <= threshold:
            if self._is_quiet_hours_beijing():
                self._in_low_balance_state = True
                return AlertDecision(False, "quiet_hours_00_to_08_bjt")

            if not self._in_low_balance_state:
                logger.warning(
                    "Balance dropped below threshold first time: %.2f <= %.2f",
                    reading.balance,
                    threshold,
                )
                return AlertDecision(True, "first_low_balance")

            if self._last_alert_time is None:
                return AlertDecision(True, "low_balance_without_previous_timestamp")

            cooldown_elapsed = (now - self._last_alert_time).total_seconds()
            if cooldown_elapsed >= self._config.alert_cooldown_seconds:
                return AlertDecision(True, "cooldown_elapsed")

            left = self._config.alert_cooldown_seconds - int(cooldown_elapsed)
            return AlertDecision(False, f"still_in_cooldown_{left}s")

        if self._in_low_balance_state:
            logger.info(
                "Balance recovered above threshold: %.2f > %.2f, low-balance state cleared",
                reading.balance,
                threshold,
            )

        self._in_low_balance_state = False
        return AlertDecision(False, "balance_above_threshold")

    @staticmethod
    def _is_quiet_hours_beijing(now_bj: datetime | None = None) -> bool:
        current_bj = now_bj or datetime.now(BEIJING_TZ)
        seconds_since_midnight = (
            current_bj.hour * 3600
            + current_bj.minute * 60
            + current_bj.second
            + current_bj.microsecond / 1_000_000
        )
        return 0 <= seconds_since_midnight <= 8 * 3600

    def _build_alert_message(self, reading: ElectricReading) -> tuple[str, str]:
        title = "[电量预警] 宿舍剩余电量过低"
        query_time = reading.fetched_at.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        content = (
            f"项目: {self._config.app_name}\n"
            f"房间: {reading.building_name}{reading.room_name}\n"
            f"账号: {reading.account}\n"
            f"当前剩余电量: {reading.balance:.2f}\n"
            f"接口提示: {reading.message}\n"
            f"查询时间(北京时间): {query_time}"
        )
        return title, content
