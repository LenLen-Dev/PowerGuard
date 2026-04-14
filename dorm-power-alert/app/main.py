"""Application entry assembly."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.clients.electric_client import ElectricClient
from app.config import AppConfig
from app.logging_setup import setup_logging
from app.models import QueryResult
from app.notifiers.email import EmailNotifier
from app.parsers.electric_parser import ElectricParser
from app.services.monitor_service import MonitorService
from app.timezone_utils import BEIJING_TZ

logger = logging.getLogger(__name__)


def build_email_notifier(config: AppConfig) -> EmailNotifier:
    """Build email notifier from config."""
    return EmailNotifier(
        smtp_host=config.email_smtp_host or "",
        smtp_port=config.email_smtp_port,
        use_tls=config.email_use_tls,
        username=config.email_username or "",
        password=config.email_password or "",
        sender=config.email_from or "",
        recipient=config.email_to or "",
        timeout_seconds=config.request_timeout_seconds,
    )


def build_monitor_service(config: AppConfig) -> MonitorService:
    """Build monitor service from app config."""
    client = ElectricClient(config)
    parser = ElectricParser()
    notifier = build_email_notifier(config)
    return MonitorService(config=config, client=client, parser=parser, notifier=notifier)


@dataclass
class MultiRuntime:
    """Runtime state for a single dorm profile in headless mode."""

    profile_label: str
    config: AppConfig
    service: MonitorService
    summary_notifier: EmailNotifier
    interval_seconds: int
    next_run_at: datetime
    busy: bool = False
    last_result: QueryResult | None = None
    last_error: str | None = None
    daily_date: str | None = None
    daily_consumption: float = 0.0
    last_balance: float | None = None
    last_balance_at: datetime | None = None
    avg_hourly_rate: float = 0.0
    summary_sent_date: str | None = None


def _profile_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _build_config_for_profile(base: AppConfig, item: dict[str, Any]) -> AppConfig:
    building_id = str(_profile_value(item, "building_id") or "").strip()
    building_name = str(_profile_value(item, "building_name") or "").strip()
    room_raw = str(_profile_value(item, "room", "room_id", "room_name") or "").strip()
    if not building_id or not building_name or not room_raw:
        raise ValueError("profile must include building_id, building_name and room/room_id/room_name")

    email_to = str(_profile_value(item, "alert_email", "email", "email_to") or base.email_to or "").strip()
    if not email_to:
        raise ValueError("profile must include alert_email/email/email_to")

    interval = int(_profile_value(item, "interval_seconds") or base.check_interval_seconds)
    if interval <= 0:
        raise ValueError("interval_seconds must be > 0")

    threshold = float(_profile_value(item, "threshold") or base.low_balance_threshold)
    if threshold < 0:
        raise ValueError("threshold must be >= 0")

    account = str(_profile_value(item, "account") or base.account).strip()
    if not account:
        raise ValueError("account cannot be empty")

    return replace(
        base,
        account=account,
        building_id=building_id,
        building_name=building_name,
        room_id=room_raw,
        room_name=room_raw,
        email_to=email_to,
        check_interval_seconds=interval,
        low_balance_threshold=threshold,
    )


def _build_multi_runtimes(base_config: AppConfig, profile_items: list[dict[str, Any]]) -> list[MultiRuntime]:
    runtimes: list[MultiRuntime] = []
    now = datetime.now()

    for idx, item in enumerate(profile_items, start=1):
        try:
            cfg = _build_config_for_profile(base_config, item)
            service = build_monitor_service(cfg)
            summary_notifier = build_email_notifier(cfg)
            label = str(_profile_value(item, "name") or f"{cfg.building_name}{cfg.room_name}")
            runtimes.append(
                MultiRuntime(
                    profile_label=label,
                    config=cfg,
                    service=service,
                    summary_notifier=summary_notifier,
                    interval_seconds=cfg.check_interval_seconds,
                    next_run_at=now,
                )
            )
        except Exception as exc:
            logger.error("Skip invalid profile #%s: %s", idx, exc)

    return runtimes


def _refresh_daily_usage(runtime: MultiRuntime, result: QueryResult) -> None:
    now_bj = datetime.now(BEIJING_TZ)
    day_key = now_bj.strftime("%Y-%m-%d")
    balance = result.reading.balance

    if runtime.daily_date != day_key:
        runtime.daily_date = day_key
        runtime.daily_consumption = 0.0
        runtime.avg_hourly_rate = 0.0
        runtime.last_balance = balance
        runtime.last_balance_at = now_bj
        runtime.summary_sent_date = None
        return

    if runtime.last_balance is not None and runtime.last_balance_at is not None:
        delta = runtime.last_balance - balance
        elapsed_h = max((now_bj - runtime.last_balance_at).total_seconds() / 3600.0, 1e-6)
        if delta > 0:
            runtime.daily_consumption += delta
            instant_rate = delta / elapsed_h
            if runtime.avg_hourly_rate <= 0:
                runtime.avg_hourly_rate = instant_rate
            else:
                runtime.avg_hourly_rate = runtime.avg_hourly_rate * 0.7 + instant_rate * 0.3
        else:
            runtime.avg_hourly_rate *= max(0.0, 1.0 - min(elapsed_h * 0.2, 0.6))

    runtime.last_balance = balance
    runtime.last_balance_at = now_bj


def _compose_nightly_summary(runtime: MultiRuntime) -> tuple[str, str] | None:
    if runtime.last_result is None:
        return None
    reading = runtime.last_result.reading
    now_bj = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    today_usage = max(0.0, runtime.daily_consumption)

    if reading.balance <= runtime.config.low_balance_threshold:
        title = "[电量预警] 每晚电量提醒（低电量）"
    else:
        title = "[电量提醒] 每晚电量汇总"

    content = (
        f"项目: {runtime.config.app_name}\n"
        f"房间: {runtime.config.building_name}{runtime.config.room_name}\n"
        f"账号: {runtime.config.account}\n"
        f"当前剩余电量: {reading.balance:.2f}\n"
        f"今日耗电量: {today_usage:.2f}\n"
        f"接口提示: {reading.message}\n"
        f"查询时间(北京时间): {now_bj}"
    )
    return title, content


def _run_profile_once(runtime: MultiRuntime) -> None:
    try:
        result = runtime.service.run_once()
        runtime.last_result = result
        runtime.last_error = None
        _refresh_daily_usage(runtime, result)
    except Exception as exc:
        runtime.last_error = str(exc)
        logger.exception("Profile %s run failed", runtime.profile_label)
    finally:
        runtime.busy = False


def _maybe_send_nightly_summary(runtime: MultiRuntime, now_bj: datetime) -> None:
    day_key = now_bj.strftime("%Y-%m-%d")
    if now_bj.hour != 22:
        return
    if runtime.summary_sent_date == day_key:
        return
    if runtime.daily_date != day_key:
        return
    if runtime.last_result is None:
        logger.warning("Skip nightly summary for %s: no reading yet", runtime.profile_label)
        return

    payload = _compose_nightly_summary(runtime)
    if payload is None:
        return
    title, content = payload
    try:
        runtime.summary_notifier.send(title, content)
        runtime.summary_sent_date = day_key
        logger.info("Nightly summary sent: %s", runtime.profile_label)
    except Exception:
        logger.exception("Nightly summary send failed: %s", runtime.profile_label)


def _apply_midnight_reset(runtimes: list[MultiRuntime], now_bj: datetime) -> None:
    day_key = now_bj.strftime("%Y-%m-%d")
    for rt in runtimes:
        if rt.daily_date == day_key:
            continue
        is_first_init = rt.daily_date is None
        rt.daily_date = day_key
        rt.daily_consumption = 0.0
        rt.avg_hourly_rate = 0.0
        rt.last_balance = None
        rt.last_balance_at = None
        rt.last_result = None
        rt.last_error = None
        rt.summary_sent_date = None
        rt.next_run_at = datetime.now()  # Force immediate query after midnight
        if not is_first_init:
            logger.info("Daily counters reset at 00:00 BJT: %s", rt.profile_label)


def run_multi_forever(runtimes: list[MultiRuntime]) -> None:
    """Run multi-dorm monitor loop in headless mode."""
    if not runtimes:
        raise ValueError("No valid dorm profiles to run")

    logger.info("Headless mode started with %s dorm profiles", len(runtimes))
    for rt in runtimes:
        logger.info("Profile loaded: %s (interval=%ss)", rt.profile_label, rt.interval_seconds)

    while True:
        now = datetime.now()
        now_bj = datetime.now(BEIJING_TZ)
        _apply_midnight_reset(runtimes, now_bj)

        for rt in runtimes:
            _maybe_send_nightly_summary(rt, now_bj)
            if rt.busy:
                continue
            if now < rt.next_run_at:
                continue
            rt.busy = True
            rt.next_run_at = now + timedelta(seconds=rt.interval_seconds)
            threading.Thread(target=_run_profile_once, args=(rt,), daemon=True).start()
        time.sleep(1)


def _load_profile_items(profile_file: Path) -> list[dict[str, Any]]:
    if not profile_file.exists():
        return []
    try:
        payload = json.loads(profile_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse profile file {profile_file}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Profile file {profile_file} must be a JSON array")

    items: list[dict[str, Any]] = []
    for entry in payload:
        if isinstance(entry, dict):
            items.append(entry)
    return items


def main() -> None:
    """Program main function for headless mode."""
    config = AppConfig.from_env()
    headless_log_file = os.getenv("HEADLESS_LOG_FILE", "logs/headless_monitor.log")
    setup_logging(config.log_level, log_file=headless_log_file, weekly_reset=True)

    profile_path = Path(os.getenv("DORM_PROFILES_FILE", "gui_profiles.json")).expanduser()
    try:
        items = _load_profile_items(profile_path)
    except Exception as exc:
        logger.error("Load multi-dorm profile file failed: %s", exc)
        items = []

    if items:
        runtimes = _build_multi_runtimes(config, items)
        run_multi_forever(runtimes)
        return

    logger.info(
        "No multi-dorm profile file found or empty (%s). Fallback to single dorm runtime scheduler.",
        profile_path,
    )
    single = MultiRuntime(
        profile_label=f"{config.building_name}{config.room_name}",
        config=config,
        service=build_monitor_service(config),
        summary_notifier=build_email_notifier(config),
        interval_seconds=config.check_interval_seconds,
        next_run_at=datetime.now(),
    )
    run_multi_forever([single])
