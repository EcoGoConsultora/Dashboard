"""Auditable, dependency-free clients for market and reference sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import html
import json
import re
from typing import Any
from urllib.request import Request, urlopen


RAVA_PROFILE_URL = "https://www2.rava.com/perfil/{symbol}"
BCRA_TAMAR_PRIVATE_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/44"
BCRA_BANK_HOLIDAYS_URL = "https://www.bcra.gob.ar/consulta-feriados-bancarios-{year}/"
USER_AGENT = "EcoGo-TAMAR-Curve/0.1 (market-data-audit)"


@dataclass(frozen=True)
class RavaQuote:
    symbol: str
    price: float
    nominal_volume: float
    market_date: date
    market_time: str
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["market_date"] = self.market_date.isoformat()
        return result


def _get_text(url: str, timeout_seconds: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _parse_rava_profile(symbol: str, source_url: str, page: str) -> RavaQuote:
    """Parse the latest quote from a saved or freshly downloaded Rava profile."""

    normalized_symbol = symbol.upper().strip()
    match = re.search(r'<perfil-p\b[\s\S]*?:res="([^"]*)"', page)
    if not match:
        raise ValueError(f"Rava no expuso el bloque de datos esperado para {normalized_symbol}")
    payload = json.loads(html.unescape(match.group(1)))
    raw_quotes = payload.get("cotizaciones")
    if not isinstance(raw_quotes, list) or not raw_quotes:
        raise ValueError(f"Rava no informo cotizaciones vigentes para {normalized_symbol}")

    def quote_timestamp(record: dict[str, Any]) -> datetime:
        return datetime.fromisoformat(f"{record['fecha']}T{record.get('hora') or '00:00:00'}")

    quote = max(raw_quotes, key=quote_timestamp)
    price = float(quote["ultimo"])
    volume = float(quote["volnominal"])
    if price <= 0 or volume < 0:
        raise ValueError(f"Cotizacion invalida de Rava para {normalized_symbol}: {quote}")
    return RavaQuote(
        symbol=normalized_symbol,
        price=price,
        nominal_volume=volume,
        market_date=date.fromisoformat(quote["fecha"]),
        market_time=str(quote.get("hora") or "00:00:00"),
        source_url=source_url,
    )


def fetch_rava_quote(symbol: str) -> RavaQuote:
    """Fetch the latest public quote embedded in a Rava instrument profile."""

    normalized_symbol = symbol.upper().strip()
    source_url = RAVA_PROFILE_URL.format(symbol=normalized_symbol)
    return _parse_rava_profile(normalized_symbol, source_url, _get_text(source_url))


def fetch_bcra_tamar_private() -> dict[date, float]:
    """Return the official private-bank TAMAR TNA series (BCRA variable 44)."""

    payload = json.loads(_get_text(BCRA_TAMAR_PRIVATE_URL))
    if payload.get("status") != 200:
        raise ValueError(f"Respuesta BCRA invalida: {payload}")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError("La API BCRA no devolvio una unica serie TAMAR privada")
    series: dict[date, float] = {}
    for point in results[0].get("detalle", []):
        observation_date = date.fromisoformat(point["fecha"])
        rate = float(point["valor"])
        if rate < 0 or observation_date in series:
            raise ValueError(f"Observacion TAMAR invalida o duplicada: {point}")
        series[observation_date] = rate
    if not series:
        raise ValueError("La API BCRA devolvio la serie TAMAR vacia")
    return series


def fetch_bcra_bank_holidays(year: int) -> dict[date, str]:
    """Read the annual BCRA bank-holiday table without inventing future dates."""

    source_url = BCRA_BANK_HOLIDAYS_URL.format(year=year)
    page = _get_text(source_url)
    months = {
        "ene": 1, "feb": 2, "mar": 3, "abr": 4,
        "may": 5, "jun": 6, "jul": 7, "ago": 8,
        "sep": 9, "set": 9, "oct": 10, "nov": 11,
        "dic": 12,
    }
    rows = re.findall(
        r"<tr>\s*<td>\s*(\d{1,2})\s+([a-z]{3})\s+(\d{4})\s*</td>\s*<td>(.*?)</td>\s*</tr>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    holidays: dict[date, str] = {}
    for day_text, month_text, row_year, description in rows:
        month = months.get(month_text.lower())
        if month is None or int(row_year) != year:
            continue
        holiday_date = date(year, month, int(day_text))
        if holiday_date in holidays:
            raise ValueError(f"Feriado BCRA duplicado: {holiday_date.isoformat()}")
        clean_description = re.sub(r"<[^>]+>", "", html.unescape(description))
        holidays[holiday_date] = re.sub(r"\s+", " ", clean_description).strip()
    if not holidays:
        raise ValueError(f"BCRA no publico una tabla valida de feriados bancarios para {year}: {source_url}")
    return holidays
