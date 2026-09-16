from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pandas as pd


DEFAULT_MARKET_CALENDAR_PATH = Path("config/calendars/ar_market_calendar_2025_2026.csv")
CALENDAR_COLUMNS = [
    "date",
    "label",
    "official_type",
    "trading_closed",
    "settlement_closed",
    "source_url",
    "notes",
]


def load_market_calendar(path: Path | str = DEFAULT_MARKET_CALENDAR_PATH) -> pd.DataFrame:
    calendar_path = Path(path)
    frame = pd.read_csv(calendar_path, parse_dates=["date"], keep_default_na=False)
    missing_columns = [column for column in CALENDAR_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"Market calendar is missing required columns: {', '.join(missing_columns)}")

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["trading_closed"] = _parse_bool_column(frame["trading_closed"], "trading_closed")
    frame["settlement_closed"] = _parse_bool_column(frame["settlement_closed"], "settlement_closed")
    if frame["date"].isna().any():
        raise ValueError("Market calendar contains invalid dates.")
    if frame["date"].duplicated().any():
        duplicates = frame.loc[frame["date"].duplicated(keep=False), "date"].dt.strftime("%Y-%m-%d").tolist()
        raise ValueError(f"Market calendar contains duplicate dates: {duplicates}")
    return frame.sort_values("date").reset_index(drop=True)


def closed_dates(calendar: pd.DataFrame, mode: str = "settlement") -> set[date]:
    flag_column = _mode_to_flag_column(mode)
    return set(calendar.loc[calendar[flag_column], "date"].dt.date)


def business_day_range(
    start: pd.Timestamp | date | str,
    end: pd.Timestamp | date | str,
    closed: Iterable[pd.Timestamp | date | str],
) -> pd.DatetimeIndex:
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if end_ts < start_ts:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")

    blocked = _normalize_closed_dates(closed)
    days = []
    current = start_ts
    while current <= end_ts:
        if _is_open_day(current, blocked):
            days.append(current)
        current += pd.Timedelta(days=1)
    return pd.DatetimeIndex(days)


def is_open_day(value: pd.Timestamp | date | str, closed: Iterable[pd.Timestamp | date | str]) -> bool:
    return _is_open_day(pd.Timestamp(value).normalize(), _normalize_closed_dates(closed))


def next_business_day(
    value: pd.Timestamp | date | str,
    closed: Iterable[pd.Timestamp | date | str],
    min_days_ahead: int = 1,
) -> pd.Timestamp:
    if min_days_ahead < 0:
        raise ValueError("min_days_ahead must be non-negative.")

    blocked = _normalize_closed_dates(closed)
    current = pd.Timestamp(value).normalize()
    remaining = min_days_ahead
    while remaining > 0:
        current += pd.Timedelta(days=1)
        if _is_open_day(current, blocked):
            remaining -= 1

    while not _is_open_day(current, blocked):
        current += pd.Timedelta(days=1)
    return current


def add_business_days(
    value: pd.Timestamp | date | str,
    offset: int,
    closed: Iterable[pd.Timestamp | date | str],
) -> pd.Timestamp:
    blocked = _normalize_closed_dates(closed)
    current = pd.Timestamp(value).normalize()
    if offset == 0:
        while not _is_open_day(current, blocked):
            current += pd.Timedelta(days=1)
        return current

    step = 1 if offset > 0 else -1
    remaining = abs(offset)
    while remaining > 0:
        current += pd.Timedelta(days=step)
        if _is_open_day(current, blocked):
            remaining -= 1
    return current


def _mode_to_flag_column(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized == "trading":
        return "trading_closed"
    if normalized == "settlement":
        return "settlement_closed"
    raise ValueError("mode must be either 'trading' or 'settlement'.")


def _normalize_closed_dates(closed: Iterable[pd.Timestamp | date | str]) -> set[date]:
    return {pd.Timestamp(value).normalize().date() for value in closed}


def _is_open_day(value: pd.Timestamp, blocked: set[date]) -> bool:
    return value.weekday() < 5 and value.date() not in blocked


def _parse_bool_column(values: pd.Series, column_name: str) -> pd.Series:
    normalized = values.astype(str).str.strip().str.lower()
    mapping = {"true": True, "false": False}
    parsed = normalized.map(mapping)
    if parsed.isna().any():
        invalid_values = sorted(set(values[parsed.isna()].astype(str)))
        raise ValueError(f"Market calendar column '{column_name}' has invalid boolean values: {invalid_values}")
    return parsed
