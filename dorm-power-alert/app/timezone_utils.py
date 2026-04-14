"""Timezone helpers with fallback for minimal Linux/OpenWrt environments."""

from __future__ import annotations

from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_beijing_tz() -> tzinfo:
    """Return Asia/Shanghai when available, otherwise fallback to fixed UTC+8."""
    try:
        return ZoneInfo("Asia/Shanghai")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8), name="UTC+8")


BEIJING_TZ = get_beijing_tz()

