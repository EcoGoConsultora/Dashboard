from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests


DEFAULT_TIMEOUT_SECONDS = 60
WEB_CACHE_COLUMNS = ["date", "asset", "value_nominal", "fetched_at", "source", "source_url", "source_detail"]
DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _build_session(extra_headers: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(DEFAULT_BROWSER_HEADERS)
    if extra_headers:
        session.headers.update(extra_headers)
    return session


def _format_date(value: str | pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _now_buenos_aires() -> pd.Timestamp:
    return pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None)


def fetch_ambito_chart_series(
    chart_path: str,
    period: str = "anual",
    base_url: str = "https://mercados.ambito.com",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    normalized_path = chart_path.strip("/")
    normalized_period = period.strip("/")
    url = f"{base_url.rstrip('/')}/{normalized_path}/{normalized_period}"
    session = _build_session({"Referer": "https://www.ambito.com/contenidos/dolar-cl.html", "Accept": "*/*"})
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) <= 1:
        return pd.DataFrame(columns=["date", "value_nominal"])

    rows: list[dict[str, Any]] = []
    for item in payload[1:]:
        if not isinstance(item, list) or len(item) < 2:
            continue
        date_value = pd.to_datetime(item[0], dayfirst=True, errors="coerce")
        numeric_value = pd.to_numeric(item[1], errors="coerce")
        if pd.isna(date_value) or pd.isna(numeric_value):
            continue
        rows.append({"date": date_value.normalize(), "value_nominal": float(numeric_value)})

    frame = pd.DataFrame(rows, columns=["date", "value_nominal"])
    if frame.empty:
        return frame
    return frame.sort_values("date").drop_duplicates(["date"], keep="last").reset_index(drop=True)


def fetch_fred_graph_series(
    series_id: str,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    base_url: str = "https://fred.stlouisfed.org",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    normalized_series_id = str(series_id or "").strip()
    if not normalized_series_id:
        raise ValueError("FRED graph series id is required.")

    response = requests.get(
        f"{base_url.rstrip('/')}/graph/fredgraph.csv",
        params={"id": normalized_series_id},
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    frame = pd.read_csv(StringIO(response.text))
    if frame.empty or len(frame.columns) < 2:
        return pd.DataFrame(columns=["date", "value_nominal"])

    date_column = frame.columns[0]
    value_column = frame.columns[1]
    frame = frame.rename(columns={date_column: "date", value_column: "value_nominal"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["value_nominal"] = pd.to_numeric(frame["value_nominal"], errors="coerce")
    frame = frame.dropna(subset=["date", "value_nominal"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "value_nominal"])

    start_ts = pd.to_datetime(start_date, errors="coerce").normalize() if start_date is not None else None
    end_ts = pd.to_datetime(end_date, errors="coerce").normalize() if end_date is not None else None
    if start_ts is not None and pd.notna(start_ts):
        frame = frame[frame["date"] >= start_ts].copy()
    if end_ts is not None and pd.notna(end_ts):
        frame = frame[frame["date"] <= end_ts].copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "value_nominal"])

    return frame.sort_values("date").drop_duplicates(["date"], keep="last").reset_index(drop=True)


def fetch_bondterminal_embi_history(
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    base_url: str = "https://bondterminal.com",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    params = {
        "start": _format_date(start_date),
        "end": _format_date(end_date),
    }
    session = _build_session({"Accept": "application/json"})
    response = session.get(f"{base_url.rstrip('/')}/api/riesgo-pais/embi-history", params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    points = list(payload.get("points", [])) if isinstance(payload, dict) else []
    rows: list[dict[str, Any]] = []
    for item in points:
        if not isinstance(item, dict):
            continue
        date_value = pd.to_datetime(item.get("fecha"), errors="coerce")
        numeric_value = pd.to_numeric(item.get("valor"), errors="coerce")
        if pd.isna(date_value) or pd.isna(numeric_value):
            continue
        rows.append({"date": date_value.normalize(), "value_nominal": float(numeric_value)})

    frame = pd.DataFrame(rows, columns=["date", "value_nominal"])
    if frame.empty:
        return frame
    return frame.sort_values("date").drop_duplicates(["date"], keep="last").reset_index(drop=True)


def fetch_argentinadatos_riesgo_pais_history(
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    base_url: str = "https://api.argentinadatos.com/v1",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    session = _build_session({"Accept": "application/json"})
    response = session.get(f"{base_url.rstrip('/')}/finanzas/indices/riesgo-pais", timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []

    start_ts = pd.to_datetime(start_date, errors="coerce").normalize() if start_date is not None else None
    end_ts = pd.to_datetime(end_date, errors="coerce").normalize() if end_date is not None else None

    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        date_value = pd.to_datetime(item.get("fecha"), errors="coerce")
        numeric_value = pd.to_numeric(item.get("valor"), errors="coerce")
        if pd.isna(date_value) or pd.isna(numeric_value):
            continue
        normalized_date = pd.Timestamp(date_value).normalize()
        if start_ts is not None and normalized_date < start_ts:
            continue
        if end_ts is not None and normalized_date > end_ts:
            continue
        rows.append({"date": normalized_date, "value_nominal": float(numeric_value)})

    frame = pd.DataFrame(rows, columns=["date", "value_nominal"])
    if frame.empty:
        return frame
    return frame.sort_values("date").drop_duplicates(["date"], keep="last").reset_index(drop=True)


def fetch_yahoo_chart_series(
    symbol: str,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    base_url: str = "https://query1.finance.yahoo.com",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    normalized_symbol = str(symbol or "").strip()
    if not normalized_symbol:
        raise ValueError("Yahoo symbol is required.")

    start_ts = pd.to_datetime(start_date, errors="coerce").normalize() if start_date is not None else pd.Timestamp("2000-01-01")
    end_ts = pd.to_datetime(end_date, errors="coerce").normalize() if end_date is not None else _now_buenos_aires().normalize()
    if pd.isna(start_ts) or pd.isna(end_ts):
        raise ValueError("Yahoo start_date/end_date could not be parsed.")

    period1 = int(pd.Timestamp(start_ts).tz_localize("UTC").timestamp())
    period2 = int((pd.Timestamp(end_ts) + pd.Timedelta(days=1)).tz_localize("UTC").timestamp())
    session = _build_session({"Accept": "application/json", "Referer": "https://finance.yahoo.com/"})
    response = session.get(
        f"{base_url.rstrip('/')}/v8/finance/chart/{normalized_symbol}",
        params={
            "interval": "1d",
            "includePrePost": "false",
            "events": "div,splits",
            "period1": period1,
            "period2": period2,
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        return pd.DataFrame(columns=["date", "value_nominal"])

    entry = result[0] or {}
    timestamps = entry.get("timestamp") or []
    indicators = ((entry.get("indicators") or {}).get("quote") or [{}])[0] or {}
    closes = indicators.get("close") or []
    rows: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        date_value = pd.to_datetime(timestamp, unit="s", utc=True, errors="coerce")
        numeric_value = pd.to_numeric(close, errors="coerce")
        if pd.isna(date_value) or pd.isna(numeric_value):
            continue
        rows.append(
            {
                "date": pd.Timestamp(date_value).tz_localize(None).normalize(),
                "value_nominal": float(numeric_value),
            }
        )

    frame = pd.DataFrame(rows, columns=["date", "value_nominal"])
    if frame.empty:
        return frame
    return frame.sort_values("date").drop_duplicates(["date"], keep="last").reset_index(drop=True)


def _pick_first_numeric(payload: dict[str, Any], fields: list[str]) -> tuple[float, str]:
    for field in fields:
        value = pd.to_numeric(payload.get(field), errors="coerce")
        if pd.notna(value):
            return float(value), field
    raise ValueError(f"BondTerminal riesgo-pais payload is missing numeric fields: {', '.join(fields)}.")


def _pick_first_timestamp(payload: dict[str, Any], fields: list[str]) -> pd.Timestamp:
    for field in fields:
        date_value = pd.to_datetime(payload.get(field), errors="coerce")
        if pd.notna(date_value):
            if getattr(date_value, "tzinfo", None) is not None:
                return date_value.tz_localize(None)
            return pd.Timestamp(date_value)
    return _now_buenos_aires()


def fetch_bondterminal_riesgo_pais_snapshot(
    base_url: str = "https://bondterminal.com",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    value_fields: list[str] | None = None,
    date_fields: list[str] | None = None,
) -> dict[str, Any]:
    session = _build_session({"Accept": "application/json"})
    response = session.get(f"{base_url.rstrip('/')}/api/riesgo-pais", timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("BondTerminal riesgo-pais payload is not a JSON object.")

    selected_value_fields = value_fields or ["weightedSpreadBps", "ambitoValue"]
    selected_date_fields = date_fields or ["valuationDate", "asOf", "lastDataTickIso", "ambitoDate"]
    value, value_field = _pick_first_numeric(payload, selected_value_fields)
    date_value = _pick_first_timestamp(payload, selected_date_fields)

    return {
        "date": pd.Timestamp(date_value).normalize(),
        "value_nominal": value,
        "source_url": f"{base_url.rstrip('/')}/api/riesgo-pais",
        "source_detail": f"bondterminal:{value_field}",
        "fetched_at": _now_buenos_aires(),
    }


def fetch_argentinadatos_riesgo_pais_snapshot(
    base_url: str = "https://api.argentinadatos.com/v1",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    session = _build_session({"Accept": "application/json"})
    response = session.get(f"{base_url.rstrip('/')}/finanzas/indices/riesgo-pais/ultimo", timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("ArgentinaDatos riesgo-pais latest payload is not a JSON object.")

    date_value = pd.to_datetime(payload.get("fecha"), errors="coerce")
    numeric_value = pd.to_numeric(payload.get("valor"), errors="coerce")
    if pd.isna(date_value) or pd.isna(numeric_value):
        raise ValueError("ArgentinaDatos riesgo-pais latest payload is missing 'fecha' or 'valor'.")

    return {
        "date": pd.Timestamp(date_value).normalize(),
        "value_nominal": float(numeric_value),
        "source_url": f"{base_url.rstrip('/')}/finanzas/indices/riesgo-pais/ultimo",
        "source_detail": "argentinadatos:ultimo",
        "fetched_at": _now_buenos_aires(),
    }


def load_web_price_cache(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=WEB_CACHE_COLUMNS)

    frame = pd.read_csv(path, parse_dates=["date", "fetched_at"])
    for column in WEB_CACHE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["fetched_at"] = pd.to_datetime(frame["fetched_at"], errors="coerce")
    frame["value_nominal"] = pd.to_numeric(frame["value_nominal"], errors="coerce")
    frame = frame.dropna(subset=["date", "asset", "value_nominal"]).copy()
    return frame[WEB_CACHE_COLUMNS].sort_values(["date", "asset", "fetched_at"]).reset_index(drop=True)


def merge_web_price_cache(path: Path, fresh_rows: pd.DataFrame) -> pd.DataFrame:
    existing = load_web_price_cache(path)
    if existing.empty:
        combined = fresh_rows.copy()
    elif fresh_rows.empty:
        combined = existing.copy()
    else:
        existing_for_concat = existing.dropna(axis=1, how="all")
        fresh_for_concat = fresh_rows.dropna(axis=1, how="all")
        combined = pd.concat([existing_for_concat, fresh_for_concat], ignore_index=True)
        for column in WEB_CACHE_COLUMNS:
            if column not in combined.columns:
                combined[column] = pd.NA
        combined = combined[WEB_CACHE_COLUMNS]

    if combined.empty:
        return pd.DataFrame(columns=WEB_CACHE_COLUMNS)

    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.normalize()
    combined["fetched_at"] = pd.to_datetime(combined["fetched_at"], errors="coerce")
    combined["value_nominal"] = pd.to_numeric(combined["value_nominal"], errors="coerce")
    combined = combined.dropna(subset=["date", "asset", "value_nominal"]).copy()
    combined["_fetched_sort"] = combined["fetched_at"].fillna(pd.Timestamp.min)
    combined = (
        combined.sort_values(["date", "asset", "_fetched_sort"])
        .drop_duplicates(["date", "asset"], keep="last")
        .drop(columns=["_fetched_sort"])
        .reset_index(drop=True)
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return combined[WEB_CACHE_COLUMNS].copy()
