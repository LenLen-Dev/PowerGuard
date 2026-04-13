"""Core data models used by the monitoring workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ElectricReading:
    """Normalized electric reading parsed from remote API payload."""

    balance: float
    message: str
    raw: dict
    account: str
    room_name: str
    building_name: str
    fetched_at: datetime


@dataclass(frozen=True)
class AlertDecision:
    """Alert decision produced by monitor service for observability/testing."""

    should_alert: bool
    reason: str


@dataclass(frozen=True)
class QueryResult:
    """One monitor query result including parsed reading and alert outcome."""

    reading: ElectricReading
    decision: AlertDecision
    alert_sent: bool
