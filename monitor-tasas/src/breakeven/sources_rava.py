from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from typing import Iterable

import pandas as pd
import requests

from .sources_iol import normalize_prices


RAVA_PROFILE_URL = "https://www2.rava.com/perfil/{symbol}"
_PROFILE_COMPONENT_RE = re.compile(r'<perfil-p\b[^>]*\s:res="([^"]+)"', re.IGNORECASE | re.DOTALL)
_PROFILE2_ROW_RE = re.compile(
    r'<div[^>]*\bp2-coti-hist\b[^>]*>.*?<tbody>\s*<tr>(?P<row>.*?)</tr>',
    re.IGNORECASE | re.DOTALL,
)
_IDENTIFIER_RE = re.compile(r'"identifier"\s*:\s*"(?P<symbol>[^"]+)"', re.IGNORECASE)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


class RavaError(RuntimeError):
    """Rava's public bond quotation page could not be read."""


class RavaUntraded(RavaError):
    """Rava lists the instrument but still has no trade history."""


def _clean_text(value: str) -> str:
    value = _TAG_RE.sub("", value)
    return html.unescape(value).replace("\xa0", " ").strip()


def _parse_rava_number(value: str, *, integer_grouping: bool = False) -> float:
    cleaned = re.sub(r"[^\d,.\-]", "", _clean_text(value))
    if not cleaned:
        raise RavaError("Rava numeric field is empty")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1 or (integer_grouping and re.fullmatch(r"-?\d{1,3}\.\d{3}", cleaned)):
        cleaned = cleaned.replace(".", "")
    return float(cleaned)


def _profile_payload(page: str) -> dict:
    """Parse the JSON payload embedded in Rava's ``perfil-p`` component."""
    match = _PROFILE_COMPONENT_RE.search(page)
    if not match:
        raise RavaError("Rava profile quotation payload was not found in the page")
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise RavaError("Rava profile quotation payload is not valid JSON") from exc


def _extract_profile_quote(page: str) -> dict:
    """Extract the current quote embedded in Rava's ``perfil-p`` component."""
    try:
        payload = _profile_payload(page)
    except RavaError:
        return _extract_profile2_quote(page)

    quotes = payload.get("cotizaciones")
    if not isinstance(quotes, list) or not quotes:
        if _has_never_traded(payload):
            raise RavaUntraded("Rava profile has no current quotation history")
        raise RavaError("Rava profile has no current quotation")
    return quotes[0]


def _extract_profile2_quote(page: str) -> dict:
    """Extract the current quote from Rava's 2026 ``perfil2`` HTML page."""
    symbol_match = _IDENTIFIER_RE.search(page)
    row_match = _PROFILE2_ROW_RE.search(page)
    if not symbol_match or not row_match:
        raise RavaError("Rava profile quotation payload was not found in the page")

    cells = [_clean_text(cell) for cell in _TD_RE.findall(row_match.group("row"))]
    if len(cells) < 6:
        raise RavaError("Rava profile historical quote row is incomplete")
    try:
        quote_date = datetime.strptime(cells[0], "%d/%m/%Y").date()
    except ValueError as exc:
        raise RavaError(f"Rava profile quote date is invalid: {cells[0]}") from exc

    return {
        "simbolo": symbol_match.group("symbol").upper(),
        "ultimo": _parse_rava_number(cells[4]),
        "volnominal": _parse_rava_number(cells[5], integer_grouping=True),
        "fecha": quote_date.isoformat(),
        "mercado": "AR-Bonos",
    }


def _has_never_traded(payload: dict) -> bool:
    """True when Rava lists the instrument but holds no price history for it.

    A bond issued in the last auction is already in Rava's instrument master
    while its secondary market is still empty. That case must not abort the
    batch; anything that has traded before is expected to quote.
    """
    return not (payload.get("coti_hist") or [])


def fetch_rava_bond_prices(
    symbols: Iterable[str] | None = None,
    as_of: date | None = None,
    url_template: str = RAVA_PROFILE_URL,
) -> pd.DataFrame:
    """Fetch current ARS bond quotes from Rava's public instrument pages.

    Rava embeds a JSON quote in each server-rendered instrument page. ``ultimo``
    is the last traded price and ``volnominal`` is the nominal traded volume.
    This function keeps Rava's quoted date instead of relabelling live data as
    a historical valuation date.
    """
    if symbols is None:
        raise ValueError("Rava fetching requires the configured instrument symbols")
    requested = {symbol.upper().strip() for symbol in symbols}
    rows: list[dict] = []
    missing: list[str] = []
    untraded: list[str] = []
    for symbol in sorted(requested):
        try:
            response = requests.get(
                url_template.format(symbol=symbol),
                headers={"User-Agent": "Mozilla/5.0 (compatible; CER-breakeven-batch/1.0)"},
                timeout=(5, 30),
            )
            response.raise_for_status()
            page = response.text
        except requests.RequestException:
            missing.append(symbol)
            continue
        try:
            row = _extract_profile_quote(page)
        except RavaUntraded:
            # Newly issued instruments are listed before they ever trade.
            untraded.append(symbol)
            continue
        except RavaError:
            missing.append(symbol)
            continue
        if str(row.get("simbolo", "")).upper() != symbol:
            missing.append(symbol)
            continue
        rows.append(row)
    if missing:
        raise RavaError(f"Rava did not return configured symbols: {', '.join(missing)}")
    if untraded:
        print(f"WARNING: sin cotizacion Rava todavia, se omite: {', '.join(untraded)}")

    raw = pd.DataFrame(rows)
    quotes = pd.DataFrame(
        {
            "date": raw.get("fecha"),
            "symbol": raw.get("simbolo"),
            "price": raw.get("ultimo"),
            "volume": raw.get("volnominal"),
            "market": raw.get("mercado", "AR-Bonos"),
            "source": "rava",
        }
    )

    normalized = normalize_prices(quotes, as_of=as_of)
    if normalized.empty:
        requested_date = as_of.isoformat() if as_of else "the requested valuation date"
        raise RavaError(f"Rava returned no valid prices on or before {requested_date}")
    return normalized
