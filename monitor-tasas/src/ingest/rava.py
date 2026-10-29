from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


RAVA_PROFILE_URL = "https://www.rava.com/perfil/{symbol}"
RAVA_PRICE_COLUMNS = ["date", "symbol", "price", "volume", "source", "source_url", "fetched_at"]
_PROFILE_RES_PATTERN = re.compile(r'<perfil-p\b[^>]*\s:res="(?P<payload>[^"]+)"', re.IGNORECASE | re.DOTALL)
_HISTORICAL_TABLE_PATTERN = re.compile(
    r'<div[^>]*class="[^"]*\bp2-coti-hist\b[^"]*"[^>]*>.*?<tbody>(?P<body>.*?)</tbody>',
    re.IGNORECASE | re.DOTALL,
)
_TABLE_ROW_PATTERN = re.compile(r"<tr\b[^>]*>(?P<row>.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TABLE_CELL_PATTERN = re.compile(r"<td\b[^>]*>(?P<cell>.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")


def fetch_rava_hard_dollar_prices(
    symbols: Iterable[str],
    *,
    timeout_seconds: int = 30,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch Rava's public latest quote and daily history for each D-denominated bond."""

    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9",
        }
    )

    frames: list[pd.DataFrame] = []
    failures: dict[str, str] = {}
    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        source_url = RAVA_PROFILE_URL.format(symbol=symbol)
        try:
            response = session.get(source_url, timeout=timeout_seconds)
            response.raise_for_status()
            frame = parse_rava_profile_prices(response.text, symbol=symbol, source_url=source_url)
            if frame.empty:
                raise ValueError("Rava profile did not include a usable quote or price history.")
            frames.append(frame)
        except Exception as exc:  # Keep a partial curve if one profile is temporarily unavailable.
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=RAVA_PRICE_COLUMNS)
    if prices.empty:
        return prices, failures
    prices = prices.sort_values(["date", "symbol", "fetched_at"]).drop_duplicates(["date", "symbol"], keep="last")
    return prices.reset_index(drop=True), failures


def parse_rava_profile_prices(html_text: str, *, symbol: str, source_url: str) -> pd.DataFrame:
    """Parse a Rava profile page into a canonical daily price history."""

    symbol_key = str(symbol).strip().upper()
    fetched_at = pd.Timestamp(datetime.now().astimezone()).tz_localize(None)
    rows: list[dict[str, object]] = []

    try:
        profile = _parse_profile_payload(html_text)
    except ValueError as exc:
        rows = _parse_profile_history_table(
            html_text,
            symbol=symbol_key,
            source_url=source_url,
            fetched_at=fetched_at,
        )
        if rows:
            return _price_frame(rows)
        raise exc

    for quote in profile.get("coti_hist", []):
        row = _normalize_price_row(quote, symbol_key, source_url, fetched_at)
        if row is not None:
            rows.append(row)

    current_quotes = profile.get("cotizaciones", [])
    selected_quote = next(
        (
            quote
            for quote in current_quotes
            if isinstance(quote, dict) and str(quote.get("simbolo", "")).strip().upper() == symbol_key
        ),
        next((quote for quote in current_quotes if isinstance(quote, dict)), None),
    )
    if isinstance(selected_quote, dict):
        # A profile can include the current trading date in both blocks. Make the
        # explicitly current quote win deterministically over the historical close.
        row = _normalize_price_row(
            selected_quote,
            symbol_key,
            source_url,
            fetched_at + pd.Timedelta(microseconds=1),
        )
        if row is not None:
            rows.append(row)

    return _price_frame(rows)


def _price_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=RAVA_PRICE_COLUMNS)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    return frame.dropna(subset=["date", "symbol", "price"])[RAVA_PRICE_COLUMNS].copy()


def merge_rava_price_history(path: Path | str, fresh: pd.DataFrame) -> pd.DataFrame:
    """Persist one canonical Rava observation per bond and market date."""

    history_path = Path(path)
    try:
        existing = pd.read_csv(history_path, parse_dates=["date", "fetched_at"])
    except (FileNotFoundError, pd.errors.EmptyDataError):
        existing = pd.DataFrame(columns=RAVA_PRICE_COLUMNS)

    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh.copy()
    if combined.empty:
        return pd.DataFrame(columns=RAVA_PRICE_COLUMNS)
    for column in RAVA_PRICE_COLUMNS:
        if column not in combined.columns:
            combined[column] = pd.NA
    combined = combined[RAVA_PRICE_COLUMNS].copy()
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.normalize()
    combined["fetched_at"] = pd.to_datetime(combined["fetched_at"], errors="coerce")
    combined["symbol"] = combined["symbol"].astype(str).str.strip().str.upper()
    combined["price"] = pd.to_numeric(combined["price"], errors="coerce")
    combined["volume"] = pd.to_numeric(combined["volume"], errors="coerce")
    combined = combined.dropna(subset=["date", "symbol", "price"])
    combined = combined[combined["price"] > 0].copy()
    combined["_fetched_at"] = combined["fetched_at"].fillna(pd.Timestamp.min)
    combined = combined.sort_values(["date", "symbol", "_fetched_at"]).drop_duplicates(["date", "symbol"], keep="last")
    combined = combined.drop(columns=["_fetched_at"]).reset_index(drop=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(history_path, index=False)
    return combined


def _parse_profile_payload(html_text: str) -> dict[str, Any]:
    match = _PROFILE_RES_PATTERN.search(html_text)
    if match is None:
        raise ValueError("Rava profile did not expose the perfil-p :res payload.")
    payload = json.loads(html.unescape(match.group("payload")))
    if not isinstance(payload, dict):
        raise ValueError("Rava profile payload is not a JSON object.")
    return payload


def _parse_profile_history_table(
    html_text: str,
    *,
    symbol: str,
    source_url: str,
    fetched_at: pd.Timestamp,
) -> list[dict[str, object]]:
    match = _HISTORICAL_TABLE_PATTERN.search(html_text)
    if match is None:
        return []

    rows: list[dict[str, object]] = []
    for row_match in _TABLE_ROW_PATTERN.finditer(match.group("body")):
        cells = [_html_text(cell) for cell in _TABLE_CELL_PATTERN.findall(row_match.group("row"))]
        if len(cells) < 6:
            continue
        date = pd.to_datetime(cells[0], format="%d/%m/%Y", errors="coerce")
        price = _argentine_number(cells[4])
        if pd.isna(date) or pd.isna(price) or float(price) <= 0:
            continue
        volume = _argentine_number(cells[5])
        rows.append(
            {
                "date": pd.Timestamp(date).normalize(),
                "symbol": symbol,
                "price": float(price),
                "volume": float(volume) if pd.notna(volume) else pd.NA,
                "source": "rava_public_profile",
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
        )
    return rows


def _html_text(value: str) -> str:
    return " ".join(html.unescape(_TAG_PATTERN.sub(" ", value)).split())


def _argentine_number(value: str) -> float:
    normalized = value.strip().replace(".", "").replace(",", ".")
    parsed = pd.to_numeric(normalized, errors="coerce")
    return float(parsed) if pd.notna(parsed) else float("nan")


def _normalize_price_row(
    quote: object,
    symbol: str,
    source_url: str,
    fetched_at: pd.Timestamp,
) -> dict[str, object] | None:
    if not isinstance(quote, dict):
        return None
    date = pd.to_datetime(quote.get("fecha"), errors="coerce")
    price = pd.to_numeric(quote.get("ultimo", quote.get("cierre")), errors="coerce")
    if pd.isna(date) or pd.isna(price) or float(price) <= 0:
        return None
    volume = pd.to_numeric(quote.get("volnominal", quote.get("volumen")), errors="coerce")
    return {
        "date": pd.Timestamp(date).normalize(),
        "symbol": symbol,
        "price": float(price),
        "volume": float(volume) if pd.notna(volume) else pd.NA,
        "source": "rava_public_profile",
        "source_url": source_url,
        "fetched_at": fetched_at,
    }
