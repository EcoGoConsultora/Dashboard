from __future__ import annotations

from calendar import monthrange
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Iterable
import re
import unicodedata

import numpy as np
import pandas as pd
import requests

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, closed_dates, load_market_calendar, next_business_day
from src.ingest.chrome_runtime import build_chrome_driver


IOL_HISTORY_COLUMNS = ["date", "symbol", "price", "volume", "market", "source"]
IOL_MARKET_HISTORY_COLUMNS = [*IOL_HISTORY_COLUMNS, "fetched_at"]
IOL_QUOTE_SNAPSHOT_COLUMNS = [*IOL_HISTORY_COLUMNS[:4], "amount", "market", "source", "fetched_at"]
IOL_METADATA_COLUMNS = [
    "symbol",
    "issue_date",
    "maturity_date",
    "annual_rate",
    "payment_amount",
    "instrument_family",
]
IOL_METRIC_COLUMNS = [
    "date",
    "symbol",
    "instrument_family",
    "issue_date",
    "maturity_date",
    "annual_rate",
    "price",
    "volume",
    "next_business_day",
    "payment_date",
    "technical_price",
    "payment_amount",
    "parity",
    "tea",
    "tem",
    "modified_duration",
    "days_360_to_maturity",
]
IOL_ROLL_SELECTION_COLUMNS = [
    *IOL_METRIC_COLUMNS,
    "target_days_360",
    "days_to_target",
]
IOL_QUOTE_BASE_URL = "https://iol.invertironline.com/titulo/cotizacion"
IOL_MARKET_PAGE_URLS = (
    "https://iol.invertironline.com/mercado/cotizaciones/argentina/bonos/todos",
    "https://iol.invertironline.com/mercado/cotizaciones/argentina/letras",
)
IOL_QUOTE_TIMEOUT_SECONDS = 30
IOL_QUOTE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


def load_iol_instrument_metadata(path: Path | str) -> pd.DataFrame:
    frame = pd.read_excel(path)
    frame.columns = frame.columns.astype(str).str.strip()

    column_map = {
        "Instrumento": "symbol",
        "Fecha de emision": "issue_date",
        "Fecha de vencimiento": "maturity_date",
        "Tasa": "annual_rate",
        "Pago": "payment_amount",
    }
    renamed: dict[str, str] = {}
    for column in frame.columns:
        normalized = _normalize_column_name(column)
        if normalized in column_map:
            renamed[column] = column_map[normalized]
    frame = frame.rename(columns=renamed)

    required = ["symbol", "issue_date", "maturity_date", "annual_rate"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"IOL instrument metadata is missing required columns: {', '.join(missing)}")

    if "payment_amount" not in frame.columns:
        frame["payment_amount"] = np.nan

    metadata = frame[["symbol", "issue_date", "maturity_date", "annual_rate", "payment_amount"]].copy()
    metadata["symbol"] = metadata["symbol"].astype(str).str.strip().str.upper()
    metadata["issue_date"] = pd.to_datetime(metadata["issue_date"], errors="coerce").dt.normalize()
    metadata["maturity_date"] = pd.to_datetime(metadata["maturity_date"], errors="coerce").dt.normalize()
    metadata["annual_rate"] = metadata["annual_rate"].apply(_parse_local_number)
    metadata["payment_amount"] = metadata["payment_amount"].apply(_parse_local_number)
    metadata["instrument_family"] = metadata["symbol"].map(_infer_instrument_family)

    metadata = metadata.dropna(subset=["symbol", "issue_date", "maturity_date", "annual_rate"]).copy()
    metadata = metadata.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)
    return metadata[IOL_METADATA_COLUMNS]


def load_iol_history_workbook(path: Path | str, market: str = "BCBA") -> pd.DataFrame:
    frame = pd.read_excel(path)
    return _normalize_iol_history_frame(frame, market=market, source="IOL_WORKBOOK")


def scrape_iol_histories(
    symbols: Iterable[str],
    market: str = "BCBA",
    headless: bool = True,
    timeout_seconds: int = 20,
    page_size: int = 200,
) -> pd.DataFrame:
    symbol_list = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if not symbol_list:
        return pd.DataFrame(columns=IOL_HISTORY_COLUMNS)

    driver = _build_iol_driver(headless=headless)
    try:
        frames: list[pd.DataFrame] = []
        for symbol in symbol_list:
            frame = scrape_iol_history(
                driver=driver,
                symbol=symbol,
                market=market,
                timeout_seconds=timeout_seconds,
                page_size=page_size,
            )
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=IOL_HISTORY_COLUMNS)
        combined = pd.concat(frames, ignore_index=True)
        return combined.sort_values(["symbol", "date"]).reset_index(drop=True)
    finally:
        driver.quit()


def scrape_iol_history(
    driver,
    symbol: str,
    market: str = "BCBA",
    timeout_seconds: int = 20,
    page_size: int = 200,
) -> pd.DataFrame:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import Select, WebDriverWait

    wait = WebDriverWait(driver, timeout_seconds)
    url = f"https://iol.invertironline.com/Titulo/DatosHistoricos?simbolo={symbol}&mercado={market}"
    driver.get(url)

    try:
        wait.until(ec.presence_of_element_located((By.NAME, "tbcotizaciones_length")))
        select = Select(driver.find_element(By.NAME, "tbcotizaciones_length"))
        available_values = [option.get_attribute("value") for option in select.options]
        target_value = str(page_size) if str(page_size) in available_values else available_values[-1]
        select.select_by_value(target_value)
        wait.until(ec.presence_of_element_located((By.CSS_SELECTOR, "table.table")))
    except TimeoutException:
        return pd.DataFrame(columns=IOL_HISTORY_COLUMNS)

    page_frames: list[pd.DataFrame] = []
    seen_html: set[str] = set()
    while True:
        table = driver.find_element(By.CSS_SELECTOR, "table.table")
        table_html = table.get_attribute("outerHTML")
        if table_html in seen_html:
            break
        seen_html.add(table_html)
        page_frames.append(pd.read_html(StringIO(table_html))[0])

        next_button = _find_next_button(driver)
        if next_button is None or _is_disabled_element(next_button):
            break

        driver.execute_script("arguments[0].click();", next_button)
        try:
            wait.until(
                lambda current_driver: current_driver.find_element(By.CSS_SELECTOR, "table.table").get_attribute("outerHTML") != table_html
            )
        except TimeoutException:
            break

    if not page_frames:
        return pd.DataFrame(columns=IOL_HISTORY_COLUMNS)
    raw_history = pd.concat(page_frames, ignore_index=True)
    return _normalize_iol_history_frame(
        raw_history,
        market=market,
        source="IOL_SCRAPER",
        fallback_symbol=symbol,
        date_format="%m/%d/%Y",
    )


def load_iol_market_price_history(path: Path | str) -> pd.DataFrame:
    cache_path = Path(path)
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        return pd.DataFrame(columns=IOL_MARKET_HISTORY_COLUMNS)

    frame = pd.read_csv(cache_path, parse_dates=["date", "fetched_at"])
    for column in IOL_MARKET_HISTORY_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    normalized = frame[IOL_MARKET_HISTORY_COLUMNS].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    normalized["symbol"] = normalized["symbol"].astype(str).str.strip().str.upper()
    normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce")
    normalized["volume"] = pd.to_numeric(normalized["volume"], errors="coerce")
    normalized["market"] = normalized["market"].astype(str).str.strip().str.upper()
    normalized["source"] = normalized["source"].astype(str).str.strip()
    normalized["fetched_at"] = pd.to_datetime(normalized["fetched_at"], errors="coerce")
    return normalized[IOL_MARKET_HISTORY_COLUMNS].copy()


def merge_iol_market_price_cache(path: Path | str, fresh_history: pd.DataFrame) -> pd.DataFrame:
    cache_path = Path(path)
    existing = load_iol_market_price_history(cache_path)
    fresh = _prepare_iol_market_history_frame(fresh_history)

    if existing.empty:
        combined = fresh.copy()
    elif fresh.empty:
        combined = existing.copy()
    else:
        combined = pd.concat([existing, fresh], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=IOL_MARKET_HISTORY_COLUMNS)

    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.normalize()
    combined["symbol"] = combined["symbol"].astype(str).str.strip().str.upper()
    combined["price"] = pd.to_numeric(combined["price"], errors="coerce")
    combined["volume"] = pd.to_numeric(combined["volume"], errors="coerce")
    combined["market"] = combined["market"].astype(str).str.strip().str.upper()
    combined["source"] = combined["source"].astype(str).str.strip()
    combined["fetched_at"] = pd.to_datetime(combined["fetched_at"], errors="coerce")
    combined = combined.dropna(subset=["date", "symbol", "market", "price"]).copy()
    combined = combined[combined["price"] > 0].copy()
    combined = (
        combined.sort_values(["date", "symbol", "market", "fetched_at"])
        .drop_duplicates(subset=["date", "symbol", "market"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(cache_path, index=False)
    return combined[IOL_MARKET_HISTORY_COLUMNS].copy()


def update_iol_market_price_cache(
    path: Path | str,
    symbols: Iterable[str],
    market: str = "BCBA",
    headless: bool = True,
    timeout_seconds: int = 20,
    page_size: int = 200,
    include_quote_overlay: bool = False,
    quote_timeout_seconds: int = IOL_QUOTE_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    fetched_at = pd.Timestamp.now(tz="America/Buenos_Aires")
    fresh_history = scrape_iol_histories(
        symbols=symbols,
        market=market,
        headless=headless,
        timeout_seconds=timeout_seconds,
        page_size=page_size,
    )
    if include_quote_overlay:
        quote_overlay = fetch_iol_quote_page_overlay(
            symbols=symbols,
            market=market,
            timeout_seconds=quote_timeout_seconds,
        )
        fresh_history = merge_iol_history_with_overlay(history=fresh_history, overlay=quote_overlay)
    fresh_history = _prepare_iol_market_history_frame(fresh_history, fetched_at=fetched_at)
    return merge_iol_market_price_cache(path=path, fresh_history=fresh_history)


def fetch_iol_quote_page_overlay(
    symbols: Iterable[str],
    market: str = "BCBA",
    timeout_seconds: int = IOL_QUOTE_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    snapshots = fetch_iol_quote_page_snapshots(
        symbols=symbols,
        market=market,
        timeout_seconds=timeout_seconds,
    )
    if snapshots.empty:
        return pd.DataFrame(columns=IOL_HISTORY_COLUMNS)

    overlay = snapshots[["date", "symbol", "price", "volume", "market", "source"]].copy()
    return overlay[IOL_HISTORY_COLUMNS]


def fetch_iol_quote_page_snapshots(
    symbols: Iterable[str],
    market: str = "BCBA",
    timeout_seconds: int = IOL_QUOTE_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    symbol_list = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if not symbol_list:
        return pd.DataFrame(columns=IOL_QUOTE_SNAPSHOT_COLUMNS)

    session = requests.Session()
    session.headers.update(IOL_QUOTE_HEADERS)
    fetched_at = pd.Timestamp.now(tz="America/Buenos_Aires")
    market_date = fetched_at.tz_localize(None).normalize()
    rows: list[dict[str, object]] = []

    for symbol in symbol_list:
        quote = fetch_iol_quote_page_snapshot(
            symbol=symbol,
            market=market,
            session=session,
            timeout_seconds=timeout_seconds,
        )
        if quote is not None:
            rows.append(
                {
                    "date": market_date,
                    "symbol": symbol,
                    "price": quote["price"],
                    "volume": quote["volume"],
                    "amount": quote.get("amount", np.nan),
                    "market": market,
                    "source": "IOL_QUOTE_PAGE",
                    "fetched_at": fetched_at,
                }
            )

    quote_frame = pd.DataFrame(rows, columns=IOL_QUOTE_SNAPSHOT_COLUMNS)
    market_frame = fetch_iol_market_page_snapshots(
        symbols=symbol_list,
        market=market,
        session=session,
        timeout_seconds=timeout_seconds,
    )
    return _merge_iol_intraday_snapshots(
        quote_frame=quote_frame,
        market_frame=market_frame,
        market=market,
        fetched_at=fetched_at,
    )


def fetch_iol_quote_page_snapshot(
    symbol: str,
    market: str = "BCBA",
    session: requests.Session | None = None,
    timeout_seconds: int = IOL_QUOTE_TIMEOUT_SECONDS,
) -> dict[str, float] | None:
    quote_session = session or requests.Session()
    if session is None:
        quote_session.headers.update(IOL_QUOTE_HEADERS)

    response = quote_session.get(
        f"{IOL_QUOTE_BASE_URL}/{market.strip().upper()}/{str(symbol).strip().upper()}/",
        timeout=timeout_seconds,
        allow_redirects=True,
    )
    response.raise_for_status()
    html = response.text

    price = _extract_quote_page_field(html, "UltimoPrecio")
    volume = _extract_quote_page_field(html, "VolumenNominal", prefix="Q:")
    amount = _extract_quote_page_field(html, "MontoOperado", prefix="$")
    if price is None:
        return None
    return {
        "price": price,
        "volume": volume if volume is not None else np.nan,
        "amount": amount if amount is not None else np.nan,
    }


def fetch_iol_market_page_snapshots(
    symbols: Iterable[str],
    market: str = "BCBA",
    session: requests.Session | None = None,
    timeout_seconds: int = IOL_QUOTE_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    symbol_set = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    if not symbol_set:
        return pd.DataFrame(columns=IOL_QUOTE_SNAPSHOT_COLUMNS)

    quote_session = session or requests.Session()
    if session is None:
        quote_session.headers.update(IOL_QUOTE_HEADERS)

    fetched_at = pd.Timestamp.now(tz="America/Buenos_Aires")
    market_date = fetched_at.tz_localize(None).normalize()
    rows: list[dict[str, object]] = []

    for url in IOL_MARKET_PAGE_URLS:
        try:
            response = quote_session.get(url, timeout=timeout_seconds, allow_redirects=True)
            response.raise_for_status()
        except requests.RequestException:
            continue
        rows.extend(_extract_iol_market_page_rows(response.text, symbol_set))

    if not rows:
        return pd.DataFrame(columns=IOL_QUOTE_SNAPSHOT_COLUMNS)

    frame = pd.DataFrame(rows)
    frame["date"] = market_date
    frame["market"] = market
    frame["source"] = "IOL_MARKET_PAGE"
    frame["fetched_at"] = fetched_at
    frame["volume"] = np.nan
    return frame[IOL_QUOTE_SNAPSHOT_COLUMNS].drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)


def _extract_iol_market_page_rows(html: str, symbol_set: set[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    row_pattern = re.compile(r"<tr\b[^>]*>.*?</tr>", flags=re.IGNORECASE | re.DOTALL)
    symbol_pattern = re.compile(r'data-symbol="([A-Z0-9]+)"', flags=re.IGNORECASE)
    field_pattern = r'data-field="{field}"[^>]*>\s*(.*?)\s*</td>'

    for row_html in row_pattern.findall(html):
        symbol_match = symbol_pattern.search(row_html)
        if symbol_match is None:
            continue
        symbol = symbol_match.group(1).strip().upper()
        if symbol not in symbol_set:
            continue

        price = _extract_market_row_field(row_html, field_pattern.format(field="UltimoPrecio"))
        amount = _extract_market_row_field(row_html, field_pattern.format(field="MontoOperado"))
        if price is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "price": price,
                "amount": amount if amount is not None else np.nan,
            }
        )
    return rows


def _extract_market_row_field(row_html: str, pattern: str) -> float | None:
    match = re.search(pattern, row_html, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    raw_value = re.sub(r"<[^>]+>", "", match.group(1))
    return _parse_local_number(raw_value)


def _merge_iol_intraday_snapshots(
    *,
    quote_frame: pd.DataFrame,
    market_frame: pd.DataFrame,
    market: str,
    fetched_at: pd.Timestamp,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not quote_frame.empty:
        frames.append(quote_frame.copy())
    if not market_frame.empty:
        frames.append(market_frame.copy())
    if not frames:
        return pd.DataFrame(columns=IOL_QUOTE_SNAPSHOT_COLUMNS)

    merged = pd.concat(frames, ignore_index=True)
    for column in IOL_QUOTE_SNAPSHOT_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA

    merged["symbol"] = merged["symbol"].astype(str).str.strip().str.upper()
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.normalize()
    merged["price"] = pd.to_numeric(merged["price"], errors="coerce")
    merged["volume"] = pd.to_numeric(merged["volume"], errors="coerce")
    merged["amount"] = pd.to_numeric(merged["amount"], errors="coerce")
    merged["market"] = merged["market"].fillna(market).astype(str).str.strip().str.upper()
    merged["source"] = merged["source"].astype(str).str.strip()
    merged["fetched_at"] = pd.to_datetime(merged["fetched_at"], errors="coerce").fillna(pd.Timestamp(fetched_at))

    grouped_rows: list[dict[str, object]] = []
    for symbol, symbol_frame in merged.groupby("symbol", sort=True):
        quote_rows = symbol_frame[symbol_frame["source"].str.contains("QUOTE_PAGE", case=False, na=False)]
        market_rows = symbol_frame[symbol_frame["source"].str.contains("MARKET_PAGE", case=False, na=False)]

        quote_row = quote_rows.sort_values("fetched_at").tail(1)
        market_row = market_rows.sort_values("fetched_at").tail(1)

        quote_data = quote_row.iloc[0] if not quote_row.empty else None
        market_data = market_row.iloc[0] if not market_row.empty else None
        selected_price = (
            float(market_data["price"])
            if market_data is not None and pd.notna(market_data["price"])
            else float(quote_data["price"])
            if quote_data is not None and pd.notna(quote_data["price"])
            else np.nan
        )
        selected_amount = (
            float(market_data["amount"])
            if market_data is not None and pd.notna(market_data["amount"])
            else float(quote_data["amount"])
            if quote_data is not None and pd.notna(quote_data["amount"])
            else np.nan
        )
        derived_nominal_volume = _derive_iol_nominal_volume_from_amount(
            price=selected_price,
            amount=selected_amount,
        )
        quote_volume = (
            float(quote_data["volume"])
            if quote_data is not None and pd.notna(quote_data["volume"])
            else np.nan
        )

        grouped_rows.append(
            {
                "date": (
                    market_data["date"]
                    if market_data is not None and pd.notna(market_data["date"])
                    else quote_data["date"] if quote_data is not None else pd.NaT
                ),
                "symbol": symbol,
                "price": selected_price,
                "volume": derived_nominal_volume if pd.notna(derived_nominal_volume) else quote_volume,
                "amount": selected_amount,
                "market": market,
                "source": (
                    "IOL_MARKET_PAGE+QUOTE_PAGE"
                    if market_data is not None and quote_data is not None
                    else "IOL_MARKET_PAGE"
                    if market_data is not None
                    else "IOL_QUOTE_PAGE"
                ),
                "fetched_at": (
                    max(
                        [
                            value
                            for value in (
                                market_data["fetched_at"] if market_data is not None else pd.NaT,
                                quote_data["fetched_at"] if quote_data is not None else pd.NaT,
                            )
                            if pd.notna(value)
                        ],
                        default=pd.Timestamp(fetched_at),
                    )
                ),
            }
        )

    return pd.DataFrame(grouped_rows, columns=IOL_QUOTE_SNAPSHOT_COLUMNS)


def _derive_iol_nominal_volume_from_amount(*, price: float, amount: float) -> float:
    numeric_price = pd.to_numeric(price, errors="coerce")
    numeric_amount = pd.to_numeric(amount, errors="coerce")
    if pd.isna(numeric_price) or pd.isna(numeric_amount):
        return np.nan
    if float(numeric_price) <= 0 or float(numeric_amount) <= 0:
        return np.nan
    # IOL quote and market pages report sovereign/treasury prices per 100 VN.
    # The dashboard history stores nominal volume, so derive VN from traded amount.
    return float(numeric_amount) / float(numeric_price) * 100.0


def merge_iol_history_with_overlay(history: pd.DataFrame, overlay: pd.DataFrame) -> pd.DataFrame:
    base = history.copy()
    for column in IOL_HISTORY_COLUMNS:
        if column not in base.columns:
            base[column] = pd.NA
    base = base[IOL_HISTORY_COLUMNS]

    if overlay.empty:
        return base

    overlay_frame = overlay.copy()
    for column in IOL_HISTORY_COLUMNS:
        if column not in overlay_frame.columns:
            overlay_frame[column] = pd.NA
    overlay_frame = overlay_frame[IOL_HISTORY_COLUMNS]

    combined = pd.concat([base, overlay_frame], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.normalize()
    combined["symbol"] = combined["symbol"].astype(str).str.strip().str.upper()
    combined["price"] = pd.to_numeric(combined["price"], errors="coerce")
    combined["volume"] = pd.to_numeric(combined["volume"], errors="coerce")
    combined["market"] = combined["market"].astype(str).str.strip().str.upper()
    combined["source"] = combined["source"].astype(str).str.strip()
    combined["source_priority"] = combined["source"].map(_history_source_priority)
    combined = combined.dropna(subset=["date", "symbol", "price"]).copy()
    combined = combined[combined["price"] > 0].copy()
    combined = (
        combined.sort_values(["date", "symbol", "market", "source_priority", "source"])
        .drop_duplicates(subset=["date", "symbol", "market"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    return combined[IOL_HISTORY_COLUMNS].copy()


def compute_zero_coupon_metrics(
    history: pd.DataFrame,
    metadata: pd.DataFrame,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> pd.DataFrame:
    if history.empty or metadata.empty:
        return pd.DataFrame(columns=IOL_METRIC_COLUMNS)

    market_calendar = load_market_calendar(calendar_path)
    settlement_closed = closed_dates(market_calendar, mode="settlement")

    prices = history.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce").dt.normalize()
    prices["symbol"] = prices["symbol"].astype(str).str.strip().str.upper()
    prices["price"] = pd.to_numeric(prices["price"], errors="coerce")
    if "volume" not in prices.columns:
        prices["volume"] = np.nan

    merged = prices.merge(metadata, on="symbol", how="inner")
    merged = merged.dropna(subset=["date", "price", "issue_date", "maturity_date", "annual_rate"]).copy()
    merged = merged[merged["date"] < merged["maturity_date"]].copy()
    if merged.empty:
        return pd.DataFrame(columns=IOL_METRIC_COLUMNS)

    merged = merged.sort_values(["symbol", "date"]).reset_index(drop=True)
    metric_frame = merged.apply(
        lambda row: _calculate_zero_coupon_row(row, settlement_closed),
        axis=1,
        result_type="expand",
    )
    metric_frame.columns = [
        "next_business_day",
        "payment_date",
        "technical_price",
        "payment_amount",
        "parity",
        "tea",
        "tem",
        "modified_duration",
        "days_360_to_maturity",
    ]

    base_frame = merged.drop(columns=["payment_amount"]).reset_index(drop=True)
    result = pd.concat([base_frame, metric_frame], axis=1)
    return result[IOL_METRIC_COLUMNS].sort_values(["symbol", "date"]).reset_index(drop=True)


def latest_zero_coupon_snapshot(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return pd.DataFrame(columns=IOL_METRIC_COLUMNS)
    return (
        metrics.sort_values("date")
        .groupby("symbol", as_index=False)
        .tail(1)
        .sort_values(["instrument_family", "symbol"])
        .reset_index(drop=True)
    )


def load_iol_zero_coupon_metrics(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for column in ["date", "issue_date", "maturity_date", "next_business_day", "payment_date"]:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()

    missing = [column for column in IOL_METRIC_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"IOL zero-coupon metrics are missing required columns: {', '.join(missing)}")

    metrics = frame[IOL_METRIC_COLUMNS].copy()
    metrics["symbol"] = metrics["symbol"].astype(str).str.strip().str.upper()
    metrics["instrument_family"] = metrics["instrument_family"].astype(str).str.strip().str.lower()
    return metrics


def select_target_maturity_metrics(
    metrics: pd.DataFrame,
    instrument_families: Iterable[str],
    target_days_360: int,
    metric_column: str = "tea",
    min_days_360: int | None = None,
    max_days_360: int | None = None,
    min_volume: float = 0.0,
) -> pd.DataFrame:
    if metric_column not in metrics.columns:
        raise ValueError(f"IOL target-maturity selection cannot find metric column '{metric_column}'.")

    normalized_families = {str(value).strip().lower() for value in instrument_families if str(value).strip()}
    frame = metrics.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["instrument_family"] = frame["instrument_family"].astype(str).str.strip().str.lower()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["days_360_to_maturity"] = pd.to_numeric(frame["days_360_to_maturity"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    frame[metric_column] = pd.to_numeric(frame[metric_column], errors="coerce")
    frame["modified_duration"] = pd.to_numeric(frame["modified_duration"], errors="coerce")

    if normalized_families:
        frame = frame[frame["instrument_family"].isin(normalized_families)].copy()
    frame = frame.dropna(subset=["date", "symbol", "days_360_to_maturity", metric_column]).copy()

    if min_days_360 is not None:
        frame = frame[frame["days_360_to_maturity"] >= int(min_days_360)].copy()
    if max_days_360 is not None:
        frame = frame[frame["days_360_to_maturity"] <= int(max_days_360)].copy()
    if min_volume > 0:
        frame = frame[frame["volume"] >= float(min_volume)].copy()
    if frame.empty:
        return pd.DataFrame(columns=IOL_ROLL_SELECTION_COLUMNS)

    frame["target_days_360"] = int(target_days_360)
    frame["days_to_target"] = (frame["days_360_to_maturity"] - int(target_days_360)).abs()
    selected = (
        frame.sort_values(["date", "days_to_target", "volume", "symbol"], ascending=[True, True, False, True])
        .groupby("date", as_index=False)
        .head(1)
        .sort_values("date")
        .reset_index(drop=True)
    )
    return selected[IOL_ROLL_SELECTION_COLUMNS]


def _prepare_iol_market_history_frame(
    frame: pd.DataFrame,
    fetched_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=IOL_MARKET_HISTORY_COLUMNS)

    normalized = frame.copy()
    for column in IOL_HISTORY_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    if fetched_at is None:
        fetched_at = pd.Timestamp.now(tz="America/Buenos_Aires")
    if "fetched_at" not in normalized.columns:
        normalized["fetched_at"] = fetched_at

    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    normalized["symbol"] = normalized["symbol"].astype(str).str.strip().str.upper()
    normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce")
    normalized["volume"] = pd.to_numeric(normalized["volume"], errors="coerce")
    normalized["market"] = normalized["market"].astype(str).str.strip().str.upper()
    normalized["source"] = normalized["source"].astype(str).str.strip()
    normalized["fetched_at"] = pd.to_datetime(normalized["fetched_at"], errors="coerce").fillna(pd.Timestamp(fetched_at))
    normalized = normalized.dropna(subset=["date", "symbol", "market", "price"]).copy()
    normalized = normalized[normalized["price"] > 0].copy()
    return normalized[IOL_MARKET_HISTORY_COLUMNS].copy()


def _normalize_iol_history_frame(
    frame: pd.DataFrame,
    market: str,
    source: str,
    fallback_symbol: str | None = None,
    date_format: str | None = None,
) -> pd.DataFrame:
    column_lookup = {_normalize_column_name(column): column for column in frame.columns}
    date_column = column_lookup.get("Fecha Cotizacion") or column_lookup.get("Fecha")
    price_column = column_lookup.get("Cierre") or column_lookup.get("Ultimo")
    volume_column = column_lookup.get("Volumen") or column_lookup.get("Volumen Nominal")
    symbol_column = column_lookup.get("Instrumento") or column_lookup.get("Simbolo")

    if date_column is None or price_column is None:
        raise ValueError("IOL history frame is missing date or price columns.")

    normalized = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce", format=date_format).dt.normalize()
            if date_format
            else pd.to_datetime(frame[date_column], errors="coerce", dayfirst=True).dt.normalize(),
            "symbol": frame[symbol_column].astype(str).str.strip().str.upper() if symbol_column else fallback_symbol,
            "price": frame[price_column].apply(_parse_local_number),
            "volume": frame[volume_column].apply(_parse_local_number) if volume_column else np.nan,
        }
    )
    normalized["market"] = market
    normalized["source"] = source
    normalized = normalized.dropna(subset=["date", "price"]).copy()
    normalized = normalized[normalized["price"] > 0].copy()
    normalized = normalized[normalized["symbol"].notna()].copy()
    normalized = normalized.drop_duplicates(subset=["date", "symbol"], keep="last")
    return normalized[IOL_HISTORY_COLUMNS].sort_values(["symbol", "date"]).reset_index(drop=True)


def _extract_quote_page_field(html: str, field: str, prefix: str = "") -> float | None:
    pattern = rf'data-field="{re.escape(field)}"[^>]*>\s*([^<]+?)\s*<'
    match = re.search(pattern, html, flags=re.IGNORECASE)
    if match is None:
        return None
    raw_value = match.group(1).strip()
    if prefix and raw_value.upper().startswith(prefix.upper()):
        raw_value = raw_value[len(prefix) :].strip()
    return _parse_local_number(raw_value)


def _history_source_priority(source: object) -> int:
    normalized = str(source or "").strip().upper()
    priorities = {
        "IOL_WORKBOOK": 0,
        "IOL_SCRAPER": 1,
        "IOL_QUOTE_PAGE": 2,
        "IOL_MARKET_PAGE": 2,
        "IOL_MARKET_PAGE+QUOTE_PAGE": 3,
        "DATA912_LIVE": 3,
    }
    return priorities.get(normalized, 0)


def _build_iol_driver(headless: bool):
    try:
        import selenium  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("selenium is required for live IOL scraping. Install requirements first.") from exc

    return build_chrome_driver(
        context="iol",
        headless=headless,
        chrome_binary_env_vars=("IOL_CHROME_BINARY", "BYMA_CHROME_BINARY", "CHROME_BINARY"),
    )


def _find_next_button(driver):
    from selenium.webdriver.common.by import By

    locators = [
        (By.CSS_SELECTOR, "#tbcotizaciones_next"),
        (By.CSS_SELECTOR, "li.paginate_button.next"),
        (By.CSS_SELECTOR, "a.paginate_button.next"),
    ]
    for by, selector in locators:
        try:
            element = driver.find_element(by, selector)
            if element.tag_name.lower() == "li":
                return element.find_element(By.TAG_NAME, "a")
            return element
        except Exception:
            continue
    return None


def _is_disabled_element(element) -> bool:
    classes = str(element.get_attribute("class") or "").lower()
    aria_disabled = str(element.get_attribute("aria-disabled") or "").lower()
    return "disabled" in classes or aria_disabled == "true"


def _normalize_column_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    return "".join(character for character in text if ord(character) < 128).strip()


def _parse_local_number(value: object) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "--"}:
        return np.nan
    text = text.replace("\xa0", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return np.nan


def _infer_instrument_family(symbol: str) -> str:
    upper_symbol = str(symbol).upper()
    if upper_symbol.startswith("TO"):
        return "boncer"
    if upper_symbol.startswith("TY"):
        return "bonte"
    if upper_symbol.startswith("T"):
        return "boncap"
    if upper_symbol.startswith("S"):
        return "lecap"
    if upper_symbol.startswith("D"):
        return "dollar_linked"
    return "unknown"


def _calculate_zero_coupon_row(row: pd.Series, settlement_closed: set[date]) -> pd.Series:
    settlement_date = next_business_day(row["date"], settlement_closed, min_days_ahead=1)
    issue_date = pd.Timestamp(row["issue_date"]).normalize()
    maturity_date = pd.Timestamp(row["maturity_date"]).normalize()
    payment_date = next_business_day(maturity_date, settlement_closed, min_days_ahead=0)
    annual_rate = float(row["annual_rate"])
    price = float(row["price"])

    periods_to_settlement = _days_360_excel_us(issue_date.date(), settlement_date.date()) / 30.0
    periods_to_maturity = _days_360_excel_us(issue_date.date(), maturity_date.date()) / 30.0

    technical_price = 100.0 * (1.0 + annual_rate) ** periods_to_settlement
    # Match the legacy processing workbook: the single-payment cashflow is
    # always rebuilt from the annual rate and the 30/360 accrual window,
    # instead of trusting the optional workbook "Pago" field.
    payment_amount = float(100.0 * (1.0 + annual_rate) ** periods_to_maturity)

    parity = price / technical_price * 100.0 if technical_price else np.nan
    tea = _xirr(
        [
            (settlement_date.to_pydatetime(), -price),
            (payment_date.to_pydatetime(), payment_amount),
        ]
    )
    tem = (1.0 + tea) ** (1.0 / 12.0) - 1.0 if pd.notna(tea) else np.nan
    years_to_payment = (payment_date - settlement_date).days / 365.0
    modified_duration = years_to_payment / (1.0 + tea) if pd.notna(tea) and tea > -1.0 else np.nan
    days_to_payment = _days_360_excel_us(settlement_date.date(), payment_date.date())

    return pd.Series(
        [
            settlement_date,
            payment_date,
            round(technical_price, 6),
            round(payment_amount, 6),
            round(parity, 6) if pd.notna(parity) else np.nan,
            round(tea, 8) if pd.notna(tea) else np.nan,
            round(tem, 8) if pd.notna(tem) else np.nan,
            round(modified_duration, 8) if pd.notna(modified_duration) else np.nan,
            days_to_payment,
        ]
    )


def _days_360_excel_us(start: date, end: date) -> int:
    start_day, start_month, start_year = start.day, start.month, start.year
    end_day, end_month, end_year = end.day, end.month, end.year

    if start_day == 31 or _is_last_day_of_february(start):
        start_day = 30
    if end_day == 31:
        if start_day in (30, 31):
            end_day = 30
    elif _is_last_day_of_february(end) and start_day == 30:
        end_day = 30

    return (end_year - start_year) * 360 + (end_month - start_month) * 30 + (end_day - start_day)


def _is_last_day_of_february(value: date) -> bool:
    return value.month == 2 and value.day == monthrange(value.year, 2)[1]


def _xnpv(rate: float, cashflows: list[tuple[object, float]]) -> float:
    if rate <= -0.999999999:
        return np.inf
    base_date = pd.Timestamp(cashflows[0][0])
    total = 0.0
    for current_date, amount in cashflows:
        years = (pd.Timestamp(current_date) - base_date).days / 365.0
        total += float(amount) / (1.0 + rate) ** years
    return total


def _xnpv_derivative(rate: float, cashflows: list[tuple[object, float]]) -> float:
    if rate <= -0.999999999:
        return np.inf
    base_date = pd.Timestamp(cashflows[0][0])
    total = 0.0
    for current_date, amount in cashflows:
        years = (pd.Timestamp(current_date) - base_date).days / 365.0
        if years == 0:
            continue
        total += -years * float(amount) / (1.0 + rate) ** (years + 1.0)
    return total


def _xirr(cashflows: list[tuple[object, float]], guess: float = 0.1) -> float:
    ordered = sorted(cashflows, key=lambda item: pd.Timestamp(item[0]))
    amounts = [float(amount) for _, amount in ordered]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return np.nan

    rate = guess
    for _ in range(50):
        value = _xnpv(rate, ordered)
        derivative = _xnpv_derivative(rate, ordered)
        if not np.isfinite(value) or not np.isfinite(derivative) or abs(derivative) < 1e-12:
            break
        next_rate = rate - value / derivative
        if next_rate <= -0.999999999 or not np.isfinite(next_rate):
            break
        if abs(next_rate - rate) < 1e-10:
            return next_rate
        rate = next_rate

    lower, upper = -0.95, 10.0
    lower_value = _xnpv(lower, ordered)
    upper_value = _xnpv(upper, ordered)
    if not np.isfinite(lower_value) or not np.isfinite(upper_value) or lower_value * upper_value > 0:
        return np.nan

    midpoint = np.nan
    for _ in range(200):
        midpoint = (lower + upper) / 2.0
        midpoint_value = _xnpv(midpoint, ordered)
        if abs(midpoint_value) < 1e-10:
            return midpoint
        if lower_value * midpoint_value <= 0:
            upper = midpoint
            upper_value = midpoint_value
        else:
            lower = midpoint
            lower_value = midpoint_value
    return midpoint
