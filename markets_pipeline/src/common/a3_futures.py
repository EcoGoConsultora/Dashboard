from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd
import requests

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, add_business_days, closed_dates, load_market_calendar


A3_CEM_BASE_URL = "https://apicem.matbarofex.com.ar"
A3_CEM_CLOSING_PRICES_URL = f"{A3_CEM_BASE_URL}/api/v2/closing-prices"
A3_CEM_VERSION = "1.0.11"
A3_FUTURES_COLUMNS = [
    "as_of_date",
    "symbol",
    "contract_month",
    "maturity_date",
    "settlement",
    "volume",
    "open_interest",
    "implied_rate",
    "source_url",
]
DLR_FUTURE_SYMBOL_RE = re.compile(r"^DLR(\d{2})(\d{4})$")
SPANISH_MONTH_ABBR = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}


def fetch_a3_dollar_futures_curve(
    *,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
    lookback_days: int = 45,
    page_size: int = 200,
    timeout: int = 40,
) -> pd.DataFrame:
    session = requests.Session()
    market_calendar = load_market_calendar(calendar_path)
    settlement_closed = closed_dates(market_calendar, mode="settlement")

    start_date = (pd.Timestamp.today().normalize() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    base_params = {
        "version": A3_CEM_VERSION,
        "product": "DLR",
        "from": start_date,
        "pageSize": page_size,
    }

    probe = session.get(A3_CEM_CLOSING_PRICES_URL, params={**base_params, "page": 1}, timeout=timeout)
    probe.raise_for_status()
    probe_payload = probe.json()
    total_entries = int(probe_payload.get("totalEntries", 0) or 0)
    total_pages = max(1, math.ceil(total_entries / page_size))

    frames: list[pd.DataFrame] = []
    for page in range(1, total_pages + 1):
        response = session.get(
            A3_CEM_CLOSING_PRICES_URL,
            params={**base_params, "page": page},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        frame = pd.DataFrame(payload.get("data", []))
        if not frame.empty:
            frames.append(frame)

    normalized_frames = [frame.dropna(axis=1, how="all") for frame in frames if not frame.empty]
    if not normalized_frames:
        return pd.DataFrame(columns=A3_FUTURES_COLUMNS)

    raw = pd.concat(normalized_frames, ignore_index=True)
    raw["symbol"] = raw["symbol"].astype(str).str.strip().str.upper()
    raw = raw[raw["symbol"].str.match(DLR_FUTURE_SYMBOL_RE)].copy()
    if raw.empty:
        return pd.DataFrame(columns=A3_FUTURES_COLUMNS)

    raw["dateTime"] = pd.to_datetime(raw["dateTime"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    for column in ("settlement", "volume", "openInterest", "impliedRate"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw = raw.dropna(subset=["dateTime", "symbol", "settlement"]).copy()
    if raw.empty:
        return pd.DataFrame(columns=A3_FUTURES_COLUMNS)

    as_of_date = raw["dateTime"].max()
    latest = raw[raw["dateTime"] == as_of_date].copy()
    latest["maturity_date"] = latest["symbol"].map(lambda value: _contract_maturity(value, settlement_closed))
    latest["contract_month"] = latest["symbol"].map(_contract_month_label)
    latest["source_url"] = A3_CEM_CLOSING_PRICES_URL
    latest = latest.dropna(subset=["maturity_date"]).copy()
    latest = latest.sort_values(["maturity_date", "symbol"]).reset_index(drop=True)

    return pd.DataFrame(
        {
            "as_of_date": pd.Timestamp(as_of_date).normalize(),
            "symbol": latest["symbol"],
            "contract_month": latest["contract_month"],
            "maturity_date": latest["maturity_date"],
            "settlement": latest["settlement"],
            "volume": latest["volume"],
            "open_interest": latest["openInterest"],
            "implied_rate": latest["impliedRate"],
            "source_url": latest["source_url"],
        },
        columns=A3_FUTURES_COLUMNS,
    )


def _contract_month_label(symbol: str) -> str | None:
    match = DLR_FUTURE_SYMBOL_RE.match(str(symbol).upper())
    if not match:
        return None
    month = int(match.group(1))
    year = int(match.group(2))
    return f"{SPANISH_MONTH_ABBR.get(month, month):s} {year}"


def _contract_maturity(symbol: str, settlement_closed: set[object]) -> pd.Timestamp | pd.NaT:
    match = DLR_FUTURE_SYMBOL_RE.match(str(symbol).upper())
    if not match:
        return pd.NaT
    month = int(match.group(1))
    year = int(match.group(2))
    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    # Contracts are represented on the last settlement business day of the month.
    maturity = add_business_days(month_end.normalize(), 0, settlement_closed)
    if maturity.month != month:
        maturity = add_business_days(month_end.normalize(), -1, settlement_closed)
    return maturity.normalize()
