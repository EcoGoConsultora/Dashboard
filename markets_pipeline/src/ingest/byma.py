from __future__ import annotations

import base64
import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.ingest.chrome_runtime import build_chrome_driver


DASHBOARD_URL = "https://open.bymadata.com.ar/#/dashboard"
DIRECT_API_BASE_URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
API_PATH_MARKER = "/bymadata/free/"
DEFAULT_WAIT_SECONDS = 8.0
DEFAULT_POLL_ATTEMPTS = 3
DEFAULT_POLL_WAIT_SECONDS = 2.0
DEFAULT_DIRECT_TIMEOUT_SECONDS = 30.0
DEFAULT_DIRECT_OPTIONS = "renta-fija"
DEFAULT_DIRECT_TOKEN = "dc826d4c2dde7519e882a250359a23a9"
QUOTE_COLUMNS = [
    "date",
    "asset",
    "endpoint",
    "symbol",
    "value_nominal",
    "value_field_used",
    "trade",
    "closing_price",
    "previous_closing_price",
    "volume",
    "volume_amount",
    "vwap",
    "currency",
    "trade_hour",
    "description",
    "fetched_at",
]
FIXED_RATE_HISTORY_COLUMNS = ["date", "symbol", "price", "volume", "market", "source"]
INDEX_HISTORY_COLUMNS = ["date", "symbol", "price", "source_url", "source"]


def build_driver(headless: bool = True) -> webdriver.Chrome:
    return build_chrome_driver(
        context="byma",
        headless=headless,
        chrome_binary_env_vars=("BYMA_CHROME_BINARY", "IOL_CHROME_BINARY", "CHROME_BINARY"),
        enable_performance_logging=True,
    )


def _wait_for_dashboard(driver: webdriver.Chrome, wait_seconds: float) -> str:
    driver.get(DASHBOARD_URL)
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "app-root")))
    time.sleep(wait_seconds)
    return driver.find_element(By.TAG_NAME, "body").text


def _decode_response_body(response_body: dict[str, Any] | None) -> str | None:
    if not response_body:
        return None
    body = response_body.get("body")
    if not body:
        return None
    if response_body.get("base64Encoded"):
        return base64.b64decode(body).decode("utf-8", errors="replace")
    return str(body)


def _build_direct_headers(options: str = DEFAULT_DIRECT_OPTIONS) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache,no-store,max-age=1,must-revalidate",
        "Content-Type": "application/json",
        "Expires": "1",
        "Options": options,
        "Referer": "https://open.bymadata.com.ar/",
        "Token": DEFAULT_DIRECT_TOKEN,
        "User-Agent": "Mozilla/5.0",
    }


def _request_direct_json(
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: float = DEFAULT_DIRECT_TIMEOUT_SECONDS,
    verify_ssl: bool = False,
    options: str = DEFAULT_DIRECT_OPTIONS,
) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        f"{DIRECT_API_BASE_URL}/{endpoint.strip('/')}",
        headers=_build_direct_headers(options=options),
        json=payload,
        timeout=timeout_seconds,
        verify=verify_ssl,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError(f"BYMA direct endpoint '{endpoint}' returned a non-object payload.")
    return body


def fetch_index_historical_series(
    symbol: str,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    resolution: str = "D",
    timeout_seconds: float = DEFAULT_DIRECT_TIMEOUT_SECONDS,
    verify_ssl: bool = False,
) -> pd.DataFrame:
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        return pd.DataFrame(columns=INDEX_HISTORY_COLUMNS)

    end_ts = pd.Timestamp(end_date or pd.Timestamp.now(tz="America/Buenos_Aires")).normalize()
    start_ts = pd.Timestamp(start_date or pd.Timestamp("2024-04-01")).normalize()
    if start_ts > end_ts:
        return pd.DataFrame(columns=INDEX_HISTORY_COLUMNS)

    params = {
        "symbol": normalized_symbol,
        "resolution": str(resolution).strip().upper() or "D",
        # BYMA's chart API responds "no_data" for explicit historical lower bounds that
        # are otherwise inside the available window. Request the full server-side range
        # and trim locally to keep the contract stable.
        "from": 0,
        "to": int((end_ts + pd.Timedelta(days=1)).timestamp()),
    }
    url = f"{DIRECT_API_BASE_URL}/chart/index-historical-series/history"
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        url,
        params=params,
        headers={"Referer": "https://open.bymadata.com.ar/", "User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=timeout_seconds,
        verify=verify_ssl,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"BYMA index historical payload for symbol '{normalized_symbol}' is invalid.")
    status = str(payload.get("s", "")).lower()
    if status == "no_data":
        return pd.DataFrame(columns=INDEX_HISTORY_COLUMNS)
    if status != "ok":
        raise ValueError(f"BYMA index historical payload for symbol '{normalized_symbol}' is invalid.")

    timestamps = list(payload.get("t") or [])
    closes = list(payload.get("c") or [])
    rows: list[dict[str, Any]] = []
    for raw_ts, raw_close in zip(timestamps, closes, strict=False):
        date_value = pd.to_datetime(raw_ts, unit="s", utc=True, errors="coerce")
        close_value = pd.to_numeric(raw_close, errors="coerce")
        if pd.isna(date_value) or pd.isna(close_value):
            continue
        rows.append(
            {
                "date": date_value.tz_convert("America/Argentina/Buenos_Aires").tz_localize(None).normalize(),
                "symbol": normalized_symbol,
                "price": float(close_value),
                "source_url": response.url,
                "source": "BYMA_CHART_INDEX_HISTORY",
            }
        )

    frame = pd.DataFrame(rows, columns=INDEX_HISTORY_COLUMNS)
    if frame.empty:
        return frame
    return (
        frame[(frame["date"] >= start_ts) & (frame["date"] <= end_ts)]
        .sort_values("date")
        .drop_duplicates(["date", "symbol"], keep="last")
        .reset_index(drop=True)
    )


def _extract_direct_records(body: dict[str, Any]) -> list[dict[str, Any]]:
    direct_records = body.get("data")
    if isinstance(direct_records, list):
        return [item for item in direct_records if isinstance(item, dict)]
    return _payload_records(body)


def _fetch_paginated_direct_records(
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: float = DEFAULT_DIRECT_TIMEOUT_SECONDS,
    verify_ssl: bool = False,
    options: str = DEFAULT_DIRECT_OPTIONS,
) -> list[dict[str, Any]]:
    page_number = int(payload.get("page_number", 1) or 1)
    page_count = page_number
    records: list[dict[str, Any]] = []

    while page_number <= page_count:
        page_payload = payload.copy()
        page_payload["page_number"] = page_number
        body = _request_direct_json(
            endpoint=endpoint,
            payload=page_payload,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            options=options,
        )
        records.extend(_extract_direct_records(body))
        content = body.get("content")
        if isinstance(content, dict):
            page_count = int(content.get("page_count", page_number) or page_number)
        else:
            page_count = page_number
        page_number += 1

    return records


def _extract_endpoint_key(url: str) -> str | None:
    path = urlparse(url).path
    if API_PATH_MARKER not in path:
        return None
    return path.split(API_PATH_MARKER, 1)[1].strip("/")


def _collect_response_payloads(
    driver: webdriver.Chrome,
    raw_logs: list[dict[str, Any]],
    required_endpoints: set[str],
) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for entry in raw_logs:
        try:
            message = json.loads(entry["message"])["message"]
        except Exception:
            continue
        if message.get("method") != "Network.responseReceived":
            continue

        params = message.get("params", {})
        response = params.get("response", {})
        status = int(response.get("status", 0) or 0)
        if status != 200:
            continue

        url = str(response.get("url") or "")
        endpoint = _extract_endpoint_key(url)
        if endpoint not in required_endpoints:
            continue

        request_id = params.get("requestId")
        if not request_id:
            continue

        try:
            response_body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        except Exception:
            continue

        body_text = _decode_response_body(response_body)
        if not body_text:
            continue

        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            continue

        payloads[endpoint] = {"url": url, "status": status, "body": body}
    return payloads


def _payload_records(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        if isinstance(body.get("data"), list):
            return [item for item in body["data"] if isinstance(item, dict)]
        if isinstance(body.get("options"), list):
            return [item for item in body["options"] if isinstance(item, dict)]
    return []


def _coerce_numeric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    numeric = pd.to_numeric([value], errors="coerce")[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _extract_numeric_from_fields(
    record: dict[str, Any],
    fields: list[str],
    treat_zero_as_missing: bool = False,
) -> tuple[float | None, str | None]:
    for field in fields:
        if not field:
            continue
        value = _coerce_numeric(record.get(field))
        if treat_zero_as_missing and value == 0:
            continue
        if value is not None:
            return value, field
    return None, None


def _normalize_fixed_rate_rows(
    records: list[dict[str, Any]],
    market_date: pd.Timestamp,
    source: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        symbol = str(record.get("symbol", "")).strip().upper()
        if not symbol:
            continue

        price, _ = _extract_numeric_from_fields(
            record,
            ["closingPrice", "settlementPrice", "trade", "previousSettlementPrice", "previousClosingPrice"],
            treat_zero_as_missing=True,
        )
        if price is None:
            continue

        volume, _ = _extract_numeric_from_fields(record, ["volume", "tradeVolume"], treat_zero_as_missing=False)
        rows.append(
            {
                "date": market_date,
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "market": str(record.get("market") or "BYMA").strip().upper(),
                "source": source,
            }
        )

    return pd.DataFrame(rows, columns=FIXED_RATE_HISTORY_COLUMNS)


def _merge_fixed_rate_overlay_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    available = [frame.copy() for frame in frames if not frame.empty]
    if not available:
        return pd.DataFrame(columns=FIXED_RATE_HISTORY_COLUMNS)

    combined = pd.concat(available, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.normalize()
    combined["symbol"] = combined["symbol"].astype(str).str.strip().str.upper()
    combined["price"] = pd.to_numeric(combined["price"], errors="coerce")
    combined["volume"] = pd.to_numeric(combined["volume"], errors="coerce")
    combined["market"] = combined["market"].astype(str).str.strip().str.upper()
    combined["source"] = combined["source"].astype(str).str.strip()
    combined = combined.dropna(subset=["date", "symbol", "price"]).copy()
    combined = combined[combined["price"] > 0].copy()
    combined = (
        combined.sort_values(["date", "symbol", "market", "source"])
        .drop_duplicates(subset=["date", "symbol", "market"], keep="first")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    return combined[FIXED_RATE_HISTORY_COLUMNS].copy()


def _infer_market_date(payloads: dict[str, dict[str, Any]], page_text: str, fetched_at: pd.Timestamp) -> pd.Timestamp:
    candidates: list[pd.Timestamp] = []
    for endpoint in ("index-price", "getBymaIndexsMep"):
        payload = payloads.get(endpoint)
        if not payload:
            continue
        for record in _payload_records(payload.get("body")):
            date_value = record.get("date")
            if not date_value:
                continue
            timestamp = pd.to_datetime(date_value, errors="coerce")
            if pd.notna(timestamp):
                candidates.append(timestamp.normalize())

    if candidates:
        return max(candidates)

    date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", page_text)
    if date_match:
        timestamp = pd.to_datetime(date_match.group(1), dayfirst=True, errors="coerce")
        if pd.notna(timestamp):
            return timestamp.normalize()

    return fetched_at.normalize()


def fetch_dashboard_snapshot(
    required_endpoints: set[str],
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    poll_attempts: int = DEFAULT_POLL_ATTEMPTS,
    poll_wait_seconds: float = DEFAULT_POLL_WAIT_SECONDS,
) -> dict[str, Any]:
    driver = build_driver()
    try:
        page_text = _wait_for_dashboard(driver, wait_seconds=wait_seconds)
        raw_logs = driver.get_log("performance")
        payloads = _collect_response_payloads(driver, raw_logs, required_endpoints)

        for _ in range(poll_attempts):
            missing = required_endpoints - set(payloads.keys())
            if not missing:
                break
            time.sleep(poll_wait_seconds)
            raw_logs.extend(driver.get_log("performance"))
            payloads = _collect_response_payloads(driver, raw_logs, required_endpoints)

        missing = required_endpoints - set(payloads.keys())
        if missing:
            raise RuntimeError(f"BYMA dashboard did not expose required endpoints: {', '.join(sorted(missing))}")

        fetched_at = pd.Timestamp.now(tz="America/Buenos_Aires").isoformat()
        market_date = _infer_market_date(
            payloads=payloads,
            page_text=page_text,
            fetched_at=pd.Timestamp(fetched_at),
        )

        return {
            "fetched_at": fetched_at,
            "market_date": market_date.date().isoformat(),
            "page_text": page_text,
            "payloads": payloads,
        }
    finally:
        driver.quit()


def fetch_fixed_rate_reference_overlay(
    symbols: list[str] | set[str] | tuple[str, ...],
    timeout_seconds: float = DEFAULT_DIRECT_TIMEOUT_SECONDS,
    verify_ssl: bool = False,
) -> pd.DataFrame:
    normalized_symbols = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    if not normalized_symbols:
        return pd.DataFrame(columns=FIXED_RATE_HISTORY_COLUMNS)

    market_date = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None).normalize()

    public_bonds_records = _fetch_paginated_direct_records(
        endpoint="public-bonds",
        payload={"T1": True, "T0": False, "Content-Type": "application/json, text/plain"},
        timeout_seconds=timeout_seconds,
        verify_ssl=verify_ssl,
    )
    public_bonds_frame = _normalize_fixed_rate_rows(
        [record for record in public_bonds_records if str(record.get("symbol", "")).strip().upper() in normalized_symbols],
        market_date=market_date,
        source="BYMA_OPEN_PUBLIC_BONDS",
    )

    letras_frames: list[pd.DataFrame] = []
    for settlement_flag, source in (("T0", "BYMA_OPEN_LETRAS_T0"), ("T1", "BYMA_OPEN_LETRAS_T1")):
        letras_records = _fetch_paginated_direct_records(
            endpoint="get-market-data",
            payload={
                "excludeZeroPxAndQty": False,
                settlement_flag: True,
                "page_number": 1,
                "page_size": 5000,
                "btnLetras": True,
                "Content-Type": "application/json",
            },
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
        )
        letras_frames.append(
            _normalize_fixed_rate_rows(
                [record for record in letras_records if str(record.get("symbol", "")).strip().upper() in normalized_symbols],
                market_date=market_date,
                source=source,
            )
        )

    overlay = _merge_fixed_rate_overlay_frames([*letras_frames, public_bonds_frame])
    return overlay[overlay["symbol"].isin(sorted(normalized_symbols))].reset_index(drop=True)


def extract_quotes_from_snapshot(
    snapshot: dict[str, Any],
    series_lookup: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    payloads = dict(snapshot.get("payloads", {}))
    market_date = pd.Timestamp(str(snapshot["market_date"])).normalize()
    fetched_at = pd.Timestamp(str(snapshot["fetched_at"]))
    record_lookup: dict[str, dict[str, dict[str, Any]]] = {}

    for endpoint, payload in payloads.items():
        endpoint_records: dict[str, dict[str, Any]] = {}
        for record in _payload_records(payload.get("body")):
            symbol = str(record.get("symbol", "")).strip()
            if symbol:
                endpoint_records[symbol] = record
        record_lookup[endpoint] = endpoint_records

    rows: list[dict[str, Any]] = []
    for asset, entry in series_lookup.items():
        endpoint = str(entry.get("endpoint", "")).strip()
        symbol = str(entry.get("symbol", "")).strip()
        field = str(entry.get("field", "closingPrice")).strip()
        fallback_fields = [str(item).strip() for item in entry.get("fallback_fields", []) if str(item).strip()]
        if field == "closingPrice" and "price" not in fallback_fields:
            fallback_fields.append("price")
        treat_zero_as_missing = bool(entry.get("treat_zero_as_missing", False))
        value_scale = float(entry.get("value_scale", 1.0))

        if not endpoint or not symbol:
            raise ValueError(f"BYMA series mapping for asset '{asset}' requires 'endpoint' and 'symbol'.")

        record = record_lookup.get(endpoint, {}).get(symbol)
        if record is None:
            raise ValueError(f"BYMA endpoint '{endpoint}' did not return symbol '{symbol}' for asset '{asset}'.")

        value, value_field_used = _extract_numeric_from_fields(
            record,
            [field, *fallback_fields],
            treat_zero_as_missing=treat_zero_as_missing,
        )
        if value is None:
            raise ValueError(
                f"BYMA symbol '{symbol}' from endpoint '{endpoint}' is missing numeric fields '{', '.join([field, *fallback_fields])}' for asset '{asset}'."
            )

        rows.append(
            {
                "date": market_date,
                "asset": asset,
                "endpoint": endpoint,
                "symbol": symbol,
                "value_nominal": value * value_scale,
                "value_field_used": value_field_used or "",
                "trade": _coerce_numeric(record.get("trade")),
                "closing_price": _coerce_numeric(record.get("closingPrice") or record.get("price")),
                "previous_closing_price": _coerce_numeric(
                    record.get("previousClosingPrice") or record.get("previousSettlementPrice")
                ),
                "volume": _coerce_numeric(record.get("volume")),
                "volume_amount": _coerce_numeric(record.get("volumeAmount")),
                "vwap": _coerce_numeric(record.get("vwap")),
                "currency": str(record.get("denominationCcy") or record.get("country") or ""),
                "trade_hour": str(record.get("tradeHour") or record.get("time") or ""),
                "description": str(record.get("description") or record.get("securityDesc") or ""),
                "fetched_at": fetched_at,
            }
        )

    return pd.DataFrame(rows, columns=QUOTE_COLUMNS)


def load_quote_cache(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=QUOTE_COLUMNS)

    frame = pd.read_csv(path, parse_dates=["date", "fetched_at"])
    for column in QUOTE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[QUOTE_COLUMNS].copy()


def merge_quote_cache(path: Path, fresh_quotes: pd.DataFrame) -> pd.DataFrame:
    existing = load_quote_cache(path)
    if existing.empty:
        combined = fresh_quotes.copy()
    elif fresh_quotes.empty:
        combined = existing.copy()
    else:
        existing_for_concat = existing.dropna(axis=1, how="all")
        fresh_for_concat = fresh_quotes.dropna(axis=1, how="all")
        combined = pd.concat([existing_for_concat, fresh_for_concat], ignore_index=True)
        for column in QUOTE_COLUMNS:
            if column not in combined.columns:
                combined[column] = pd.NA
        combined = combined[QUOTE_COLUMNS]
    if combined.empty:
        return pd.DataFrame(columns=QUOTE_COLUMNS)

    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.normalize()
    combined["fetched_at"] = pd.to_datetime(combined["fetched_at"], errors="coerce")
    combined = (
        combined.sort_values(["date", "asset", "fetched_at"])
        .drop_duplicates(["date", "asset"], keep="last")
        .reset_index(drop=True)
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return combined[QUOTE_COLUMNS].copy()


def save_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
