from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "si", "sí"}


@dataclass(frozen=True)
class MarketCalendar:
    settlement_closed: frozenset[date]
    trading_closed: frozenset[date]

    @classmethod
    def from_csv(cls, path: Path) -> "MarketCalendar":
        if not path.exists():
            return cls(frozenset(), frozenset())
        df = pd.read_csv(path, parse_dates=["date"])
        if "settlement_closed" in df.columns:
            settlement = {
                row.date.date()
                for row in df.itertuples(index=False)
                if _to_bool(row.settlement_closed)
            }
        else:
            settlement = {
                row.date.date()
                for row in df.itertuples(index=False)
                if not _to_bool(getattr(row, "is_business_day", True))
            }
        if "trading_closed" in df.columns:
            trading = {
                row.date.date()
                for row in df.itertuples(index=False)
                if _to_bool(row.trading_closed)
            }
        else:
            trading = settlement
        return cls(frozenset(settlement), frozenset(trading))

    def is_business_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.settlement_closed

    def next_business_day(self, value: date, min_days_ahead: int = 1) -> date:
        current = value + timedelta(days=min_days_ahead)
        while not self.is_business_day(current):
            current += timedelta(days=1)
        return current

    def add_business_days(self, value: date, offset: int) -> date:
        if offset == 0:
            return self.next_business_day(value, min_days_ahead=0)
        step = 1 if offset > 0 else -1
        current = value
        remaining = abs(offset)
        while remaining:
            current += timedelta(days=step)
            if self.is_business_day(current):
                remaining -= 1
        return current
