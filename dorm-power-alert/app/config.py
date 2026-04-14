"""Application configuration management."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class EmailSenderAccount:
    """SMTP sender account used by sender pool."""

    smtp_host: str
    smtp_port: int
    use_tls: bool
    username: str
    password: str
    sender: str


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
    email_sender_pool: tuple[EmailSenderAccount, ...]
    email_queue_max_size: int
    email_queue_put_timeout_seconds: int
    email_queue_max_attempts: int
    email_queue_retry_backoff_seconds: float

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
        email_queue_max_size = _get_int("EMAIL_QUEUE_MAX_SIZE", 200)
        email_queue_put_timeout_seconds = _get_int("EMAIL_QUEUE_PUT_TIMEOUT_SECONDS", 2)
        email_queue_max_attempts = _get_int("EMAIL_QUEUE_MAX_ATTEMPTS", 3)
        email_queue_retry_backoff_seconds = _get_float("EMAIL_QUEUE_RETRY_BACKOFF_SECONDS", 1.5)

        single_sender_account = _build_single_email_account(
            smtp_host=email_smtp_host,
            smtp_port=email_smtp_port,
            use_tls=email_use_tls,
            username=email_username,
            password=email_password,
            sender=email_from,
        )
        sender_pool = _load_email_sender_pool(
            default_smtp_port=email_smtp_port,
            default_use_tls=email_use_tls,
        )
        if single_sender_account is not None:
            sender_pool.insert(0, single_sender_account)

        if not email_to:
            raise ConfigError("Missing required environment variable for email notifier: EMAIL_TO")

        if not sender_pool:
            raise ConfigError(
                "No email sender is configured. "
                "Set EMAIL_SMTP_HOST/EMAIL_USERNAME/EMAIL_PASSWORD/EMAIL_FROM "
                "or provide EMAIL_POOL / EMAIL_POOL_FILE."
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
            email_sender_pool=tuple(sender_pool),
            email_queue_max_size=email_queue_max_size,
            email_queue_put_timeout_seconds=email_queue_put_timeout_seconds,
            email_queue_max_attempts=email_queue_max_attempts,
            email_queue_retry_backoff_seconds=email_queue_retry_backoff_seconds,
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


def _build_single_email_account(
    *,
    smtp_host: str | None,
    smtp_port: int,
    use_tls: bool,
    username: str | None,
    password: str | None,
    sender: str | None,
) -> EmailSenderAccount | None:
    fields = {
        "EMAIL_SMTP_HOST": smtp_host,
        "EMAIL_USERNAME": username,
        "EMAIL_PASSWORD": password,
        "EMAIL_FROM": sender,
    }
    if all(value is None for value in fields.values()):
        return None

    missing = [key for key, value in fields.items() if not value]
    if missing:
        raise ConfigError(
            "Missing required environment variables for single SMTP sender: "
            + ", ".join(missing)
        )

    return EmailSenderAccount(
        smtp_host=smtp_host or "",
        smtp_port=smtp_port,
        use_tls=use_tls,
        username=username or "",
        password=password or "",
        sender=sender or "",
    )


def _load_email_sender_pool(
    *,
    default_smtp_port: int,
    default_use_tls: bool,
) -> list[EmailSenderAccount]:
    raw = _get_optional_str("EMAIL_POOL")
    path = _get_optional_str("EMAIL_POOL_FILE")

    if raw and path:
        raise ConfigError("EMAIL_POOL and EMAIL_POOL_FILE cannot be set at the same time")
    if not raw and not path:
        return []

    source_name = "EMAIL_POOL"
    source_content = raw
    if path:
        source_name = f"EMAIL_POOL_FILE({path})"
        pool_path = Path(path).expanduser()
        try:
            source_content = pool_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Failed to read {source_name}: {exc}") from exc

    if source_content is None:
        return []

    try:
        parsed = json.loads(source_content)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{source_name} must be valid JSON array: {exc}") from exc

    if not isinstance(parsed, list) or not parsed:
        raise ConfigError(f"{source_name} must be a non-empty JSON array")

    result: list[EmailSenderAccount] = []
    for index, item in enumerate(parsed, start=1):
        result.append(
            _parse_email_sender_pool_item(
                item=item,
                source_name=source_name,
                index=index,
                default_smtp_port=default_smtp_port,
                default_use_tls=default_use_tls,
            )
        )
    return result


def _parse_email_sender_pool_item(
    *,
    item: Any,
    source_name: str,
    index: int,
    default_smtp_port: int,
    default_use_tls: bool,
) -> EmailSenderAccount:
    if not isinstance(item, dict):
        raise ConfigError(f"{source_name} item #{index} must be an object")

    smtp_host = _as_non_empty_str(item.get("smtp_host"))
    username = _as_non_empty_str(item.get("username"))
    password = _as_non_empty_str(item.get("password"))
    sender = _as_non_empty_str(item.get("sender"))
    missing = [
        key
        for key, value in {
            "smtp_host": smtp_host,
            "username": username,
            "password": password,
            "sender": sender,
        }.items()
        if not value
    ]
    if missing:
        raise ConfigError(
            f"{source_name} item #{index} is missing required fields: " + ", ".join(missing)
        )

    smtp_port = _parse_positive_int(
        item.get("smtp_port", default_smtp_port),
        f"{source_name} item #{index} smtp_port",
    )
    use_tls = _parse_bool_like(
        item.get("use_tls", default_use_tls),
        f"{source_name} item #{index} use_tls",
    )

    return EmailSenderAccount(
        smtp_host=smtp_host or "",
        smtp_port=smtp_port,
        use_tls=use_tls,
        username=username or "",
        password=password or "",
        sender=sender or "",
    )


def _as_non_empty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be a positive integer")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than 0")
    return parsed


def _parse_bool_like(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ConfigError(f"{name} must be a boolean: true/false")

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean: true/false")
