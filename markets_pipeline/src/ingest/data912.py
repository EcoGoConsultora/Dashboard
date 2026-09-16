from __future__ import annotations

from typing import Iterable

import pandas as pd
import requests

from src.ingest.iol import IOL_HISTORY_COLUMNS


DATA912_BASE_URL = "https://data912.com"
DATA912_LIVE_BONDS_PATH = "/live/arg_bonds"
DATA912_TIMEOUT_SECONDS = 20
DATA912_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def fetch_data912_live_bond_overlay(
    symbols: Iterable[str],
    market: str = "BCBA",
    timeout_seconds: int = DATA912_TIMEOUT_SECONDS,
    verify_ssl: bool = False,
) -> pd.DataFrame:
    symbol_set = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    if not symbol_set:
        return pd.DataFrame(columns=IOL_HISTORY_COLUMNS)

    session = requests.Session()
    session.headers.update(DATA912_HEADERS)
    session.trust_env = False
    response = session.get(
        f"{DATA912_BASE_URL}{DATA912_LIVE_BONDS_PATH}",
        timeout=timeout_seconds,
        verify=verify_ssl,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("data912 live bonds endpoint returned a non-list payload.")

    market_date = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None).normalize()
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if symbol not in symbol_set:
            continue
        price = pd.to_numeric(item.get("c"), errors="coerce")
        if pd.isna(price) or float(price) <= 0:
            continue
        volume = pd.to_numeric(item.get("v"), errors="coerce")
        rows.append(
            {
                "date": market_date,
                "symbol": symbol,
                "price": float(price),
                "volume": float(volume) if pd.notna(volume) else pd.NA,
                "market": str(market).strip().upper() or "BCBA",
                "source": "DATA912_LIVE",
            }
        )

    return pd.DataFrame(rows, columns=IOL_HISTORY_COLUMNS)
