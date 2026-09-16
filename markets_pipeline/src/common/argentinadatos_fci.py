from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, business_day_range, closed_dates, load_market_calendar


ARGENTINADATOS_BASE_URL = "https://api.argentinadatos.com/v1/finanzas/fci"
FCI_CATEGORY_CONFIG = {
    "mercado_dinero": {"path": "mercadoDinero", "label": "Mercado de dinero"},
    "renta_fija": {"path": "rentaFija", "label": "Renta fija"},
    "renta_mixta": {"path": "rentaMixta", "label": "Renta mixta"},
    "renta_variable": {"path": "rentaVariable", "label": "Renta variable"},
}
FCI_CATEGORY_COLUMNS = [
    "date",
    "category_key",
    "category_label",
    "patrimony",
    "fund_count",
    "source_url",
]
FCI_CURRENCY_COLUMNS = [
    "date",
    "currency_label",
    "patrimony",
    "row_count",
    "source_url",
]
FCI_MONEY_MARKET_COLUMNS = [
    "date",
    "fund",
    "patrimony",
    "vcp",
    "ccp",
    "horizon",
    "source_url",
]
FCI_HORIZON_COLUMNS = [
    "date",
    "horizon",
    "patrimony",
    "fund_count",
    "source_url",
]
FCI_REPORTED_SLICE_COLUMNS = [
    "date",
    "category_key",
    "category_label",
    "dimension_key",
    "dimension_label",
    "slice_label",
    "patrimony",
    "source_url",
]
FCI_REPORTED_DIMENSION_MAP = {
    "Benchmark": "benchmark",
    "Duration": "duration",
    "Moneda": "currency",
    "Region": "region",
    "Tipo de Renta Mixta": "mixed_type",
    "Tipo de Fondos": "fund_type",
}


def fetch_fci_category_history(
    *,
    existing: pd.DataFrame | None = None,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
    lookback_days: int = 220,
    max_workers: int = 8,
    timeout: int = 25,
) -> pd.DataFrame:
    calendar = load_market_calendar(calendar_path)
    trading_closed = closed_dates(calendar, mode="trading")

    end_date = pd.Timestamp.today().normalize()
    start_date = end_date - pd.Timedelta(days=lookback_days)
    trading_days = business_day_range(start_date, end_date, trading_closed)
    if trading_days.empty:
        return _normalize_history(existing)

    cached = _normalize_history(existing)
    if not cached.empty:
        cached = cached[cached["date"] >= trading_days.min()].copy()
        cached_days = set(cached["date"].dt.normalize())
    else:
        cached_days = set()

    pending_days = [day for day in trading_days if pd.Timestamp(day).normalize() not in cached_days]
    fetched_rows: list[dict[str, object]] = []
    if pending_days:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for day in pending_days:
                for category_key, config in FCI_CATEGORY_CONFIG.items():
                    futures[executor.submit(_fetch_fci_category_snapshot, day, category_key, config, timeout)] = (
                        day,
                        category_key,
                    )
            for future in as_completed(futures):
                row = future.result()
                if row is not None:
                    fetched_rows.append(row)

    fetched = pd.DataFrame(fetched_rows, columns=FCI_CATEGORY_COLUMNS) if fetched_rows else pd.DataFrame(columns=FCI_CATEGORY_COLUMNS)
    if cached.empty:
        combined = fetched.copy()
    elif fetched.empty:
        combined = cached.copy()
    else:
        combined = pd.concat([cached, fetched], ignore_index=True)
    combined = _normalize_history(combined)
    return combined.drop_duplicates(subset=["date", "category_key"], keep="last").sort_values(["date", "category_key"]).reset_index(drop=True)


def fetch_fci_currency_history(
    *,
    existing: pd.DataFrame | None = None,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
    lookback_days: int = 220,
    max_workers: int = 8,
    timeout: int = 25,
) -> pd.DataFrame:
    calendar = load_market_calendar(calendar_path)
    trading_closed = closed_dates(calendar, mode="trading")

    end_date = pd.Timestamp.today().normalize()
    start_date = end_date - pd.Timedelta(days=lookback_days)
    trading_days = business_day_range(start_date, end_date, trading_closed)
    if trading_days.empty:
        return _normalize_currency_history(existing)

    cached = _normalize_currency_history(existing)
    if not cached.empty:
        cached = cached[cached["date"] >= trading_days.min()].copy()
        cached_days = set(cached["date"].dt.normalize())
    else:
        cached_days = set()

    pending_days = [day for day in trading_days if pd.Timestamp(day).normalize() not in cached_days]
    fetched_rows: list[dict[str, object]] = []
    if pending_days:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for day in pending_days:
                for category_key, config in FCI_CATEGORY_CONFIG.items():
                    futures[executor.submit(_fetch_fci_currency_snapshot, day, category_key, config, timeout)] = (
                        day,
                        category_key,
                    )
            for future in as_completed(futures):
                rows = future.result()
                if rows:
                    fetched_rows.extend(rows)

    fetched = pd.DataFrame(fetched_rows, columns=FCI_CURRENCY_COLUMNS) if fetched_rows else pd.DataFrame(columns=FCI_CURRENCY_COLUMNS)
    if cached.empty:
        combined = fetched.copy()
    elif fetched.empty:
        combined = cached.copy()
    else:
        combined = pd.concat([cached, fetched], ignore_index=True)
    combined = _normalize_currency_history(combined)
    if combined.empty:
        return combined
    combined = (
        combined.groupby(["date", "currency_label"], as_index=False)
        .agg(
            patrimony=("patrimony", "sum"),
            row_count=("row_count", "sum"),
            source_url=("source_url", "last"),
        )
        .sort_values(["date", "currency_label"])
        .reset_index(drop=True)
    )
    return combined[FCI_CURRENCY_COLUMNS]


def fetch_money_market_fund_latest(*, timeout: int = 25) -> pd.DataFrame:
    url = f"{ARGENTINADATOS_BASE_URL}/mercadoDinero/ultimo"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    frame = pd.DataFrame(response.json())
    if frame.empty:
        return pd.DataFrame(columns=FCI_MONEY_MARKET_COLUMNS)

    frame["date"] = pd.to_datetime(frame.get("fecha"), errors="coerce")
    frame["patrimony"] = pd.to_numeric(frame.get("patrimonio"), errors="coerce")
    frame["vcp"] = pd.to_numeric(frame.get("vcp"), errors="coerce")
    frame["ccp"] = pd.to_numeric(frame.get("ccp"), errors="coerce")
    frame["fund"] = frame.get("fondo").astype(str)
    frame["horizon"] = frame.get("horizonte").astype(str)
    frame["source_url"] = url
    funds = frame.dropna(subset=["date"]).copy()
    if funds.empty:
        return pd.DataFrame(columns=FCI_MONEY_MARKET_COLUMNS)
    latest_date = funds["date"].max()
    funds = funds[funds["date"] == latest_date].copy()
    funds = funds[["date", "fund", "patrimony", "vcp", "ccp", "horizon", "source_url"]]
    return funds.sort_values(["patrimony", "fund"], ascending=[False, True]).reset_index(drop=True)


def fetch_fci_horizon_history(
    *,
    existing: pd.DataFrame | None = None,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
    lookback_days: int = 220,
    max_workers: int = 8,
    timeout: int = 25,
) -> pd.DataFrame:
    calendar = load_market_calendar(calendar_path)
    trading_closed = closed_dates(calendar, mode="trading")

    end_date = pd.Timestamp.today().normalize()
    start_date = end_date - pd.Timedelta(days=lookback_days)
    trading_days = business_day_range(start_date, end_date, trading_closed)
    if trading_days.empty:
        return _normalize_horizon_history(existing)

    cached = _normalize_horizon_history(existing)
    if not cached.empty:
        cached = cached[cached["date"] >= trading_days.min()].copy()
        cached_days = set(cached["date"].dt.normalize())
    else:
        cached_days = set()

    pending_days = [day for day in trading_days if pd.Timestamp(day).normalize() not in cached_days]
    fetched_rows: list[dict[str, object]] = []
    if pending_days:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for day in pending_days:
                for category_key, config in FCI_CATEGORY_CONFIG.items():
                    futures[executor.submit(_fetch_fci_horizon_snapshot, day, category_key, config, timeout)] = (
                        day,
                        category_key,
                    )
            for future in as_completed(futures):
                try:
                    rows = future.result()
                except Exception:
                    rows = []
                if rows:
                    fetched_rows.extend(rows)

    fetched = pd.DataFrame(fetched_rows, columns=FCI_HORIZON_COLUMNS) if fetched_rows else pd.DataFrame(columns=FCI_HORIZON_COLUMNS)
    if cached.empty:
        combined = fetched.copy()
    elif fetched.empty:
        combined = cached.copy()
    else:
        combined = pd.concat([cached, fetched], ignore_index=True)
    combined = _normalize_horizon_history(combined)
    if combined.empty:
        return combined
    combined = (
        combined.groupby(["date", "horizon"], as_index=False)
        .agg(
            patrimony=("patrimony", "sum"),
            fund_count=("fund_count", "sum"),
            source_url=("source_url", "last"),
        )
        .sort_values(["date", "horizon"])
        .reset_index(drop=True)
    )
    return combined[FCI_HORIZON_COLUMNS]


def fetch_fci_reported_slice_history(
    *,
    existing: pd.DataFrame | None = None,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
    lookback_days: int = 220,
    max_workers: int = 8,
    timeout: int = 25,
) -> pd.DataFrame:
    calendar = load_market_calendar(calendar_path)
    trading_closed = closed_dates(calendar, mode="trading")

    end_date = pd.Timestamp.today().normalize()
    start_date = end_date - pd.Timedelta(days=lookback_days)
    trading_days = business_day_range(start_date, end_date, trading_closed)
    if trading_days.empty:
        return _normalize_reported_slice_history(existing)

    cached = _normalize_reported_slice_history(existing)
    if not cached.empty:
        cached = cached[cached["date"] >= trading_days.min()].copy()
        cached_days = set(cached["date"].dt.normalize())
    else:
        cached_days = set()

    pending_days = [day for day in trading_days if pd.Timestamp(day).normalize() not in cached_days]
    fetched_rows: list[dict[str, object]] = []
    if pending_days:
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for day in pending_days:
                for category_key, config in FCI_CATEGORY_CONFIG.items():
                    futures[executor.submit(_fetch_fci_reported_slice_snapshot, day, category_key, config, timeout)] = (
                        day,
                        category_key,
                    )
            for future in as_completed(futures):
                try:
                    rows = future.result()
                except Exception:
                    rows = []
                if rows:
                    fetched_rows.extend(rows)

    fetched = pd.DataFrame(fetched_rows, columns=FCI_REPORTED_SLICE_COLUMNS) if fetched_rows else pd.DataFrame(columns=FCI_REPORTED_SLICE_COLUMNS)
    if cached.empty:
        combined = fetched.copy()
    elif fetched.empty:
        combined = cached.copy()
    else:
        combined = pd.concat([cached, fetched], ignore_index=True)
    combined = _normalize_reported_slice_history(combined)
    if combined.empty:
        return combined
    combined = (
        combined.groupby(
            ["date", "category_key", "category_label", "dimension_key", "dimension_label", "slice_label"],
            as_index=False,
        )
        .agg(
            patrimony=("patrimony", "sum"),
            source_url=("source_url", "last"),
        )
        .sort_values(["date", "category_key", "dimension_key", "patrimony", "slice_label"], ascending=[True, True, True, False, True])
        .reset_index(drop=True)
    )
    return combined[FCI_REPORTED_SLICE_COLUMNS]


def _fetch_fci_category_snapshot(
    day: pd.Timestamp,
    category_key: str,
    config: dict[str, str],
    timeout: int,
) -> dict[str, object] | None:
    path = config["path"]
    url = f"{ARGENTINADATOS_BASE_URL}/{path}/{day.strftime('%Y/%m/%d')}"
    response = requests.get(url, timeout=timeout)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    frame = pd.DataFrame(payload)
    if frame.empty:
        return None

    frame["fecha"] = pd.to_datetime(frame.get("fecha"), errors="coerce")
    frame["patrimonio"] = pd.to_numeric(frame.get("patrimonio"), errors="coerce")
    funds = frame.dropna(subset=["fecha"]).copy()
    if funds.empty:
        return None

    snapshot_date = funds["fecha"].dropna().max().normalize()
    patrimony = funds["patrimonio"].dropna().sum(min_count=1)
    fund_count = int(funds["fondo"].dropna().nunique()) if "fondo" in funds.columns else int(len(funds))
    if pd.isna(patrimony):
        return None

    return {
        "date": snapshot_date,
        "category_key": category_key,
        "category_label": config["label"],
        "patrimony": float(patrimony),
        "fund_count": fund_count,
        "source_url": url,
    }


def _fetch_fci_currency_snapshot(
    day: pd.Timestamp,
    category_key: str,
    config: dict[str, str],
    timeout: int,
) -> list[dict[str, object]]:
    path = config["path"]
    url = f"{ARGENTINADATOS_BASE_URL}/{path}/{day.strftime('%Y/%m/%d')}"
    response = requests.get(url, timeout=timeout)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    frame = pd.DataFrame(payload)
    if frame.empty or "fondo" not in frame.columns:
        return []

    currency_rows = frame[frame["fondo"].astype(str).str.startswith("Moneda:", na=False)].copy()
    if currency_rows.empty:
        return []

    currency_rows["currency_label"] = (
        currency_rows["fondo"].astype(str).str.replace("Moneda:", "", regex=False).str.strip()
    )
    currency_rows["patrimonio"] = pd.to_numeric(currency_rows.get("patrimonio"), errors="coerce")
    currency_rows = currency_rows.dropna(subset=["currency_label", "patrimonio"]).copy()
    if currency_rows.empty:
        return []

    grouped = (
        currency_rows.groupby("currency_label", as_index=False)
        .agg(patrimony=("patrimonio", "sum"), row_count=("currency_label", "size"))
        .sort_values("currency_label")
    )

    return [
        {
            "date": pd.Timestamp(day).normalize(),
            "currency_label": row.currency_label,
            "patrimony": float(row.patrimony),
            "row_count": int(row.row_count),
            "source_url": url,
        }
        for row in grouped.itertuples(index=False)
    ]


def _fetch_fci_horizon_snapshot(
    day: pd.Timestamp,
    category_key: str,
    config: dict[str, str],
    timeout: int,
) -> list[dict[str, object]]:
    path = config["path"]
    url = f"{ARGENTINADATOS_BASE_URL}/{path}/{day.strftime('%Y/%m/%d')}"
    response = requests.get(url, timeout=timeout)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    frame = pd.DataFrame(payload)
    if frame.empty:
        return []

    frame["date"] = pd.to_datetime(frame.get("fecha"), errors="coerce")
    frame["patrimony"] = pd.to_numeric(frame.get("patrimonio"), errors="coerce")
    frame["horizon"] = frame.get("horizonte").astype(str).str.strip().str.lower()
    funds = frame.dropna(subset=["date", "patrimony"]).copy()
    funds = funds[funds["horizon"].ne("") & funds["horizon"].ne("nan")].copy()
    if funds.empty:
        return []

    grouped = (
        funds.groupby("horizon", as_index=False)
        .agg(patrimony=("patrimony", "sum"), fund_count=("fondo", "nunique"))
        .sort_values("horizon")
    )

    return [
        {
            "date": pd.Timestamp(day).normalize(),
            "horizon": row.horizon,
            "patrimony": float(row.patrimony),
            "fund_count": int(row.fund_count),
            "source_url": url,
        }
        for row in grouped.itertuples(index=False)
    ]


def _fetch_fci_reported_slice_snapshot(
    day: pd.Timestamp,
    category_key: str,
    config: dict[str, str],
    timeout: int,
) -> list[dict[str, object]]:
    path = config["path"]
    url = f"{ARGENTINADATOS_BASE_URL}/{path}/{day.strftime('%Y/%m/%d')}"
    response = requests.get(url, timeout=timeout)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    frame = pd.DataFrame(payload)
    if frame.empty or "fondo" not in frame.columns:
        return []

    special_rows = frame[frame.get("fecha").isna()].copy()
    if special_rows.empty:
        return []

    special_rows["fondo"] = special_rows["fondo"].astype(str).str.strip()
    special_rows = special_rows[special_rows["fondo"].str.contains(":", regex=False, na=False)].copy()
    if special_rows.empty:
        return []

    labels = special_rows["fondo"].str.split(":", n=1, expand=True)
    special_rows["dimension_label"] = labels[0].astype(str).str.strip()
    special_rows["slice_label"] = labels[1].astype(str).str.strip()
    special_rows["dimension_key"] = special_rows["dimension_label"].map(FCI_REPORTED_DIMENSION_MAP)
    special_rows["patrimony"] = pd.to_numeric(special_rows.get("patrimonio"), errors="coerce")
    special_rows = special_rows.dropna(subset=["dimension_key", "slice_label", "patrimony"]).copy()
    if special_rows.empty:
        return []

    grouped = (
        special_rows.groupby(["dimension_key", "dimension_label", "slice_label"], as_index=False)
        .agg(patrimony=("patrimony", "sum"))
        .sort_values(["dimension_key", "patrimony", "slice_label"], ascending=[True, False, True])
    )

    return [
        {
            "date": pd.Timestamp(day).normalize(),
            "category_key": category_key,
            "category_label": config["label"],
            "dimension_key": row.dimension_key,
            "dimension_label": row.dimension_label,
            "slice_label": row.slice_label,
            "patrimony": float(row.patrimony),
            "source_url": url,
        }
        for row in grouped.itertuples(index=False)
    ]


def _normalize_history(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FCI_CATEGORY_COLUMNS)
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["patrimony"] = pd.to_numeric(normalized["patrimony"], errors="coerce")
    normalized["fund_count"] = pd.to_numeric(normalized["fund_count"], errors="coerce")
    normalized["category_key"] = normalized["category_key"].astype(str)
    normalized["category_label"] = normalized["category_label"].astype(str)
    normalized["source_url"] = normalized["source_url"].astype(str)
    normalized = normalized.dropna(subset=["date", "patrimony"]).copy()
    return normalized[FCI_CATEGORY_COLUMNS]


def _normalize_currency_history(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FCI_CURRENCY_COLUMNS)
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["patrimony"] = pd.to_numeric(normalized["patrimony"], errors="coerce")
    normalized["row_count"] = pd.to_numeric(normalized["row_count"], errors="coerce")
    normalized["currency_label"] = normalized["currency_label"].astype(str)
    normalized["source_url"] = normalized["source_url"].astype(str)
    normalized = normalized.dropna(subset=["date", "patrimony"]).copy()
    return normalized[FCI_CURRENCY_COLUMNS]


def _normalize_horizon_history(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FCI_HORIZON_COLUMNS)
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["patrimony"] = pd.to_numeric(normalized["patrimony"], errors="coerce")
    normalized["fund_count"] = pd.to_numeric(normalized["fund_count"], errors="coerce")
    normalized["horizon"] = normalized["horizon"].astype(str)
    normalized["source_url"] = normalized["source_url"].astype(str)
    normalized = normalized.dropna(subset=["date", "patrimony"]).copy()
    return normalized[FCI_HORIZON_COLUMNS]


def _normalize_reported_slice_history(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FCI_REPORTED_SLICE_COLUMNS)
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["patrimony"] = pd.to_numeric(normalized["patrimony"], errors="coerce")
    normalized["category_key"] = normalized["category_key"].astype(str)
    normalized["category_label"] = normalized["category_label"].astype(str)
    normalized["dimension_key"] = normalized["dimension_key"].astype(str)
    normalized["dimension_label"] = normalized["dimension_label"].astype(str)
    normalized["slice_label"] = normalized["slice_label"].astype(str)
    normalized["source_url"] = normalized["source_url"].astype(str)
    normalized = normalized.dropna(subset=["date", "patrimony"]).copy()
    return normalized[FCI_REPORTED_SLICE_COLUMNS]
