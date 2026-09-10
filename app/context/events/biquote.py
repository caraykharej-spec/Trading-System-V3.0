from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.context.models import EconomicEvent, EventImportance


class BiQuoteCalendarProvider:
    """Free, no-key economic calendar adapter."""

    name = "biquote_calendar"

    def __init__(self, base_url: str = "https://biquote.io/api/calendar", timeout: float = 10.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def _fetch_json(self) -> object:
        url = f"{self.base_url}?{urlencode({'from': 'yesterday', 'to': '+7 days'})}"
        request = Request(url, headers={"User-Agent": "Trading-System-V3/3.0"})
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _dt(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)

    @staticmethod
    def _importance(value: object) -> EventImportance:
        text = str(value or "").upper()
        return {
            "CRITICAL": EventImportance.CRITICAL,
            "HIGH": EventImportance.HIGH,
            "MEDIUM": EventImportance.MEDIUM,
            "LOW": EventImportance.LOW,
        }.get(text, EventImportance.NONE)

    @staticmethod
    def _number(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def fetch(self, *, limit: int = 100) -> list[EconomicEvent]:
        if limit < 1:
            raise ValueError("limit must be positive")
        payload = self._fetch_json()
        rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        result: list[EconomicEvent] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            event_time = self._dt(row.get("date") or row.get("eventTime") or row.get("time"))
            if event_time is None:
                continue
            name = str(row.get("name") or row.get("title") or "").strip()
            if not name:
                continue
            country = str(row.get("country") or "").strip()
            currency = str(row.get("currency") or "").strip() or None
            event_id = str(row.get("id") or f"{event_time.isoformat()}:{name}:{country}")
            result.append(EconomicEvent(event_id=event_id, name=name, event_time=event_time, country=country, currency=currency, importance=self._importance(row.get("importance") or row.get("impact")), actual=self._number(row.get("actual")), forecast=self._number(row.get("forecast")), previous=self._number(row.get("previous"))))
        return result
