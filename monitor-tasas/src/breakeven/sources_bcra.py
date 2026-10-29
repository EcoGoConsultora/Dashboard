from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd
import requests


CER_XLS_URL = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/diar_cer.xls"
API_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias"


class BCRAError(RuntimeError):
    pass


def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=(5, 30))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            sleep(1 + attempt)
    raise BCRAError(f"BCRA request failed: {last_error}")


def fetch_variable(variable_id: int, start: date, end: date) -> pd.DataFrame:
    payload = _request_json(
        f"{API_URL}/{variable_id}",
        {"desde": start.isoformat(), "hasta": end.isoformat(), "limit": 3000},
    )
    rows = payload.get("results", [{}])[0].get("detalle", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "value", "id_variable"])
    df = df.rename(columns={"fecha": "date", "valor": "value"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["id_variable"] = variable_id
    return df.sort_values("date").reset_index(drop=True)


def fetch_cer_from_xls(start: date, end: date, url: str = CER_XLS_URL) -> pd.DataFrame:
    response = requests.get(url, timeout=(5, 30))
    response.raise_for_status()
    raw = pd.read_excel(BytesIO(response.content), header=None)
    if raw.shape[1] < 2:
        raise BCRAError("BCRA CER XLS has fewer than two columns")
    df = raw.iloc[:, :2].copy()
    df.columns = ["date", "cer_index"]
    parsed_dates = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")
    serial_dates = pd.to_numeric(df["date"], errors="coerce")
    serial_mask = parsed_dates.isna() & serial_dates.notna()
    if serial_mask.any():
        parsed_dates.loc[serial_mask] = pd.to_datetime(
            serial_dates.loc[serial_mask], unit="D", origin="1899-12-30", errors="coerce"
        )
    df["date"] = parsed_dates.dt.date
    df["cer_index"] = pd.to_numeric(df["cer_index"], errors="coerce")
    df = df.dropna(subset=["date", "cer_index"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    if df.empty:
        raise BCRAError("BCRA CER XLS returned no rows for requested window")
    return df.sort_values("date").reset_index(drop=True)


def fetch_cer(start: date, end: date, variable_id: int = 30) -> pd.DataFrame:
    try:
        return fetch_cer_from_xls(start, end)
    except Exception:
        df = fetch_variable(variable_id, start, end)
        return df.rename(columns={"value": "cer_index"})[["date", "cer_index", "id_variable"]]


def fetch_monthly_inflation(start: date, end: date, variable_id: int = 27) -> pd.DataFrame:
    df = fetch_variable(variable_id, start, end).rename(columns={"value": "inflation_pct"})
    if not df.empty:
        df["inflation_monthly"] = df["inflation_pct"] / 100.0
        df["month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    return df


def write_raw_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
