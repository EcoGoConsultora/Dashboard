from __future__ import annotations

from typing import Any

import pandas as pd
import requests
import urllib3


API_BASE_URL = "https://api.bcra.gob.ar"
DEFAULT_PAGE_SIZE = 1000
DEFAULT_TIMEOUT_SECONDS = 60


def _format_date(value: str | pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _request_json(path: str, params: dict[str, Any] | None = None, verify_ssl: bool = True) -> dict[str, Any]:
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(
        f"{API_BASE_URL}{path}",
        params=params,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        verify=verify_ssl,
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("status", 200)) != 200:
        raise ValueError(f"BCRA API returned a non-success payload for {path}: {payload}")
    return payload


def fetch_principales_variables_series(
    id_variable: int,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    verify_ssl: bool = True,
) -> pd.DataFrame:
    params: dict[str, Any] = {
        "limit": int(page_size),
        "offset": 0,
    }
    if start_date is not None:
        params["desde"] = _format_date(start_date)
    if end_date is not None:
        params["hasta"] = _format_date(end_date)

    rows: list[dict[str, Any]] = []
    while True:
        payload = _request_json(
            f"/estadisticas/v4.0/monetarias/{int(id_variable)}",
            params=params,
            verify_ssl=verify_ssl,
        )
        resultset = dict(payload.get("metadata", {}).get("resultset", {}))
        results = list(payload.get("results", []))
        if not results:
            break

        detail = list(results[0].get("detalle", []))
        for item in detail:
            rows.append(
                {
                    "date": item["fecha"],
                    "value": item["valor"],
                    "id_variable": int(id_variable),
                }
            )

        count = int(resultset.get("count", len(rows)))
        offset = int(resultset.get("offset", params["offset"]))
        limit = int(resultset.get("limit", params["limit"]))
        if offset + limit >= count or not detail:
            break
        params["offset"] = offset + limit

    frame = pd.DataFrame(rows, columns=["date", "value", "id_variable"])
    if frame.empty:
        return frame

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).drop_duplicates(subset=["date"], keep="last")
    return frame.sort_values("date").reset_index(drop=True)


def fetch_estadisticas_cambiarias_series(
    currency_code: str,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    verify_ssl: bool = True,
) -> pd.DataFrame:
    params: dict[str, Any] = {
        "limit": int(page_size),
        "offset": 0,
    }
    if start_date is not None:
        params["fechaDesde"] = _format_date(start_date)
    if end_date is not None:
        params["fechaHasta"] = _format_date(end_date)

    rows: list[dict[str, Any]] = []
    while True:
        payload = _request_json(
            f"/estadisticascambiarias/v1.0/Cotizaciones/{currency_code.upper()}",
            params=params,
            verify_ssl=verify_ssl,
        )
        resultset = dict(payload.get("metadata", {}).get("resultset", {}))
        results = list(payload.get("results", []))
        if not results:
            break

        for item in results:
            detail = list(item.get("detalle", []))
            if not detail:
                continue
            quote = detail[0]
            rows.append(
                {
                    "date": item["fecha"],
                    "currency_code": quote["codigoMoneda"],
                    "description": quote["descripcion"],
                    "tipo_pase": quote["tipoPase"],
                    "tipo_cotizacion": quote["tipoCotizacion"],
                }
            )

        count = int(resultset.get("count", len(rows)))
        offset = int(resultset.get("offset", params["offset"]))
        limit = int(resultset.get("limit", params["limit"]))
        if offset + limit >= count or not results:
            break
        params["offset"] = offset + limit

    frame = pd.DataFrame(
        rows,
        columns=["date", "currency_code", "description", "tipo_pase", "tipo_cotizacion"],
    )
    if frame.empty:
        return frame

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["tipo_pase"] = pd.to_numeric(frame["tipo_pase"], errors="coerce")
    frame["tipo_cotizacion"] = pd.to_numeric(frame["tipo_cotizacion"], errors="coerce")
    frame = frame.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")
    return frame.sort_values("date").reset_index(drop=True)
