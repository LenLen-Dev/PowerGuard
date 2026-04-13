"""HTTP client for dorm electric balance API."""

from __future__ import annotations

import json
from typing import Any

import requests

from app.config import AppConfig


class ElectricClientError(RuntimeError):
    """Raised when room info query fails."""


class ElectricClient:
    """Encapsulates API request details and HTTP session management."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 16; RMX3820 Build/BP2A.250605.015; wv) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                    "Chrome/146.0.7680.120 Mobile Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "http://tysf.ahpu.edu.cn:8063",
                "Referer": config.referer,
                "Cookie": f"JSESSIONID={config.jsessionid}",
            }
        )

    def query_room_info(self) -> dict[str, Any]:
        """Query room electric info and return decoded JSON payload."""
        form_data = {
            "jsondata": self._build_jsondata(),
            "funname": "synjones.onecard.query.elec.roominfo",
            "json": "true",
        }

        try:
            response = self._session.post(
                self._config.base_url,
                data=form_data,
                timeout=self._config.request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise ElectricClientError("Electric API request timed out") from exc
        except requests.RequestException as exc:
            raise ElectricClientError(f"Electric API request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            text_preview = response.text[:200].replace("\n", " ")
            raise ElectricClientError(
                f"Electric API returned non-JSON response: {text_preview}"
            ) from exc

        if not isinstance(payload, dict):
            raise ElectricClientError("Electric API JSON body is not an object")

        return payload

    def _build_jsondata(self) -> str:
        data = {
            "query_elec_roominfo": {
                "aid": self._config.aid,
                "account": self._config.account,
                "room": {
                    "roomid": self._config.room_id,
                    "room": self._config.room_name,
                },
                "floor": {
                    "floorid": "",
                    "floor": "",
                },
                "area": {
                    "area": self._config.area,
                    "areaname": self._config.area_name,
                },
                "building": {
                    "buildingid": self._config.building_id,
                    "building": self._config.building_name,
                },
            }
        }
        return json.dumps(data, ensure_ascii=False)
