from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import requests


PRICE_COLUMNS = ["date", "symbol", "price", "volume", "market", "source"]


def normalize_prices(df: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    df = df.copy()
    rename = {
        "ticker": "symbol",
        "last": "price",
        "dirty_price": "price",
        "volume_nominal": "volume",
    }
    for old, new in rename.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    missing = {"symbol", "price"} - set(df.columns)
    if missing:
        raise ValueError(f"Price data missing columns: {sorted(missing)}")
    if "date" not in df.columns:
        if as_of is None:
            raise ValueError("Price data needs date or explicit as_of")
        df["date"] = as_of.isoformat()
    if "volume" not in df.columns:
        if "amount" in df.columns:
            df["volume"] = pd.to_numeric(df["amount"], errors="coerce") / pd.to_numeric(df["price"], errors="coerce") * 100.0
        else:
            df["volume"] = pd.NA
    if "market" not in df.columns:
        df["market"] = "BCBA"
    if "source" not in df.columns:
        df["source"] = "csv"

    df["date"] = pd.to_datetime(df["date"]).dt.date
    if as_of is not None:
        df = df[df["date"] <= as_of]
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df[df["price"] > 0].copy()

    source_rank = df["source"].astype(str).str.lower().map({"iol_overlay": 0, "overlay": 0, "iol_history": 1, "history": 1}).fillna(2)
    df["_source_rank"] = source_rank
    df = (
        df.sort_values(["symbol", "date", "_source_rank"])
        .groupby(["date", "symbol"], as_index=False)
        .head(1)
        .sort_values(["symbol", "date"])
        .groupby("symbol", as_index=False)
        .tail(1)
    )
    return df[PRICE_COLUMNS].reset_index(drop=True)


def load_price_csv(path: Path, as_of: date | None = None) -> pd.DataFrame:
    return normalize_prices(pd.read_csv(path), as_of=as_of)


def fetch_iol_export(url: str | None = None, as_of: date | None = None) -> pd.DataFrame:
    """Fetch a normalized CSV export produced by IOL or an internal bridge."""
    export_url = url or os.getenv("IOL_EXPORT_URL")
    if not export_url:
        raise ValueError("Set IOL_EXPORT_URL or pass a price CSV with --prices")
    response = requests.get(export_url, timeout=(5, 30))
    response.raise_for_status()
    tmp = Path("data/raw/iol_export_latest.csv")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(response.text, encoding="utf-8")
    return load_price_csv(tmp, as_of=as_of)
