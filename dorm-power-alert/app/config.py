"""Application configuration management."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration loaded from environment variables."""

    app_name: str
    check_interval_seconds: int
    low_balance_threshold: float
    alert_cooldown_seconds: int
    request_timeout_seconds: int
    log_level: str

    base_url: str
    referer: str
    jsessionid: str
    aid: str
    account: str
    area: str
    area_name: str
    building_id: str
    building_name: str
    room_id: str
    room_name: str

    email_smtp_host: str | None
    email_smtp_port: int
    email_use_tls: bool
    email_username: str | None
    email_password: str | None
    email_from: str | None
    email_to: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from `.env` and process environment variables."""
        load_dotenv()

        email_smtp_host = _get_optional_str("EMAIL_SMTP_HOST")
        email_smtp_port = _get_int("EMAIL_SMTP_PORT", 587)
        email_use_tls = _get_bool("EMAIL_USE_TLS", True)
        email_username = _get_optional_str("EMAIL_USERNAME")
        email_password = _get_optional_str("EMAIL_PASSWORD")
        email_from = _get_optional_str("EMAIL_FROM")
        email_to = _get_optional_str("EMAIL_TO")

        missing = [
            key
            for key, value in {
                "EMAIL_SMTP_HOST": email_smtp_host,
                "EMAIL_USERNAME": email_username,
                "EMAIL_PASSWORD": email_password,
                "EMAIL_FROM": email_from,
                "EMAIL_TO": email_to,
            }.items()
            if not value
        ]
        if missing:
            raise ConfigError(
                "Missing required environment variables for email notifier: "
                + ", ".join(missing)
            )

        return cls(
            app_name=_get_str("APP_NAME", "DormPowerAlert"),
            check_interval_seconds=_get_int("CHECK_INTERVAL_SECONDS", 300),
            low_balance_threshold=_get_float("LOW_BALANCE_THRESHOLD", 10.0),
            alert_cooldown_seconds=_get_int("ALERT_COOLDOWN_SECONDS", 1800),
            request_timeout_seconds=_get_int("REQUEST_TIMEOUT_SECONDS", 15),
            log_level=_get_str("LOG_LEVEL", "INFO").upper(),
            base_url=_get_str("BASE_URL", "http://tysf.ahpu.edu.cn:8063/web/Common/Tsm.html"),
            referer=_get_required_str("REFERER"),
            jsessionid=_get_required_str("JSESSIONID"),
            aid=_get_required_str("AID"),
            account=_get_required_str("ACCOUNT"),
            area=_get_required_str("AREA"),
            area_name=_get_required_str("AREA_NAME"),
            building_id=_get_required_str("BUILDING_ID"),
            building_name=_get_required_str("BUILDING_NAME"),
            room_id=_get_required_str("ROOM_ID"),
            room_name=_get_required_str("ROOM_NAME"),
            email_smtp_host=email_smtp_host,
            email_smtp_port=email_smtp_port,
            email_use_tls=email_use_tls,
            email_username=email_username,
            email_password=email_password,
            email_from=email_from,
            email_to=email_to,
        )


def _get_required_str(key: str) -> str:
    value = os.getenv(key)
    if value is None or not value.strip():
        raise ConfigError(f"Missing required environment variable: {key}")
    return value.strip()


def _get_str(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _get_optional_str(key: str) -> str | None:
    value = os.getenv(key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{key} must be greater than 0")
    return parsed


def _get_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a float") from exc
    if parsed < 0:
        raise ConfigError(f"{key} must be greater than or equal to 0")
    return parsed


def _get_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be a boolean: true/false")
