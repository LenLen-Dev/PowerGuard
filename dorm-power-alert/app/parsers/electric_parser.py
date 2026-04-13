"""Parser for electric API payload."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.models import ElectricReading


class ElectricParseError(RuntimeError):
    """Raised when electric API payload cannot be parsed."""


class ElectricParser:
    """Convert raw API response into domain model."""

    _PRIMARY_BALANCE_PATTERN = re.compile(r"剩余电量\s*([+-]?\d+(?:\.\d+)?)")
    _FLOAT_PATTERN = re.compile(r"([+-]?\d+(?:\.\d+)?)")

    def parse(self, payload: dict[str, Any]) -> ElectricReading:
        """Parse API payload into an ElectricReading object."""
        if not isinstance(payload, dict):
            raise ElectricParseError("Payload must be a JSON object")

        room_info = payload.get("query_elec_roominfo")
        if not isinstance(room_info, dict):
            raise ElectricParseError("Missing or invalid 'query_elec_roominfo' in payload")

        retcode = str(room_info.get("retcode", ""))
        errmsg = room_info.get("errmsg")
        if not isinstance(errmsg, str) or not errmsg.strip():
            raise ElectricParseError("Missing or invalid 'errmsg' in query_elec_roominfo")

        if retcode != "0":
            raise ElectricParseError(f"API returned non-zero retcode={retcode}, errmsg={errmsg}")

        balance = self._extract_balance(errmsg)

        account = self._safe_str(room_info.get("account"))
        room_name = self._safe_str((room_info.get("room") or {}).get("room"))
        building_name = self._safe_str((room_info.get("building") or {}).get("building"))

        if not account:
            raise ElectricParseError("Missing 'account' in query_elec_roominfo")
        if not room_name:
            raise ElectricParseError("Missing room name in query_elec_roominfo.room.room")
        if not building_name:
            raise ElectricParseError("Missing building name in query_elec_roominfo.building.building")

        return ElectricReading(
            balance=balance,
            message=errmsg,
            raw=payload,
            account=account,
            room_name=room_name,
            building_name=building_name,
            fetched_at=datetime.now(timezone.utc),
        )

    def _extract_balance(self, errmsg: str) -> float:
        primary = self._PRIMARY_BALANCE_PATTERN.search(errmsg)
        if primary:
            return float(primary.group(1))

        fallback = self._FLOAT_PATTERN.search(errmsg)
        if fallback:
            return float(fallback.group(1))

        raise ElectricParseError(f"Cannot extract balance number from errmsg: {errmsg}")

    @staticmethod
    def _safe_str(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()
