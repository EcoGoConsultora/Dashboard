from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.common.fixed_income import cer_bond_metadata_frame
from src.common.io import PROCESSED_DIR, RAW_DIR, ensure_data_dirs
from src.ingest.bcra import fetch_principales_variables_series
from src.ingest.iol import (
    fetch_iol_quote_page_overlay,
    IOL_HISTORY_COLUMNS,
    load_iol_market_price_history,
    merge_iol_history_with_overlay,
    update_iol_market_price_cache,
)


DEFAULT_MARKET = "BCBA"
DEFAULT_IOL_CACHE_PATH = RAW_DIR / "iol_cer_prices_history.csv"
DEFAULT_HISTORY_OUTPUT_PATH = RAW_DIR / "cer_bond_prices_history.csv"
DEFAULT_CER_INDEX_OUTPUT_PATH = RAW_DIR / "bcra_cer_index_daily.csv"
DEFAULT_CER_INDEX_FALLBACK_HISTORY_PATH = PROCESSED_DIR / "cer_curve_history.csv"
DEFAULT_BCRA_CER_VARIABLE_ID = 30
DEFAULT_CER_START_DATE = "2025-01-01"


def _load_existing_cer_index(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["date", "cer_index"])
    frame = pd.read_csv(path, parse_dates=["date"])
    if "cer_index" not in frame.columns:
        return pd.DataFrame(columns=["date", "cer_index"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["cer_index"] = pd.to_numeric(frame["cer_index"], errors="coerce")
    frame = frame.dropna(subset=["date", "cer_index"]).copy()
    return frame[["date", "cer_index"]].drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)


def _load_cer_index_from_processed_curve(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["date", "cer_index"])
    frame = pd.read_csv(path, parse_dates=["cer_reference_date"])
    required = {"cer_reference_date", "cer_current_index"}
    if not required.issubset(frame.columns):
        return pd.DataFrame(columns=["date", "cer_index"])
    frame["cer_reference_date"] = pd.to_datetime(frame["cer_reference_date"], errors="coerce").dt.normalize()
    frame["cer_current_index"] = pd.to_numeric(frame["cer_current_index"], errors="coerce")
    frame = frame.dropna(subset=["cer_reference_date", "cer_current_index"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "cer_index"])
    frame = (
        frame[["cer_reference_date", "cer_current_index"]]
        .drop_duplicates(subset=["cer_reference_date"], keep="last")
        .rename(columns={"cer_reference_date": "date", "cer_current_index": "cer_index"})
        .sort_values("date")
        .reset_index(drop=True)
    )
    return frame


def run_cer_reference(
    market: str = DEFAULT_MARKET,
    headless: bool = True,
    timeout_seconds: int = 20,
    page_size: int = 50,
    iol_cache_path: Path = DEFAULT_IOL_CACHE_PATH,
    history_out: Path = DEFAULT_HISTORY_OUTPUT_PATH,
    cer_index_out: Path = DEFAULT_CER_INDEX_OUTPUT_PATH,
    end_date: str | pd.Timestamp | None = None,
    cer_index_start_date: str = DEFAULT_CER_START_DATE,
    cer_index_variable_id: int = DEFAULT_BCRA_CER_VARIABLE_ID,
    verify_ssl: bool = False,
) -> dict[str, Path | int | str]:
    ensure_data_dirs()
    metadata = cer_bond_metadata_frame()
    symbol_map = metadata[["symbol", "source_symbol"]].drop_duplicates(subset=["source_symbol"], keep="last").copy()
    source_to_internal = dict(zip(symbol_map["source_symbol"], symbol_map["symbol"]))
    source_symbols = symbol_map["source_symbol"].tolist()
    end_ts = pd.Timestamp(end_date).normalize() if end_date is not None else pd.Timestamp.today().normalize()

    cache_refresh_status = "ok"
    try:
        cache = update_iol_market_price_cache(
            path=iol_cache_path,
            symbols=source_symbols,
            market=market,
            headless=headless,
            timeout_seconds=timeout_seconds,
            page_size=page_size,
        )
    except Exception as exc:
        if iol_cache_path.exists():
            cache = load_iol_market_price_history(iol_cache_path)
            cache_refresh_status = f"reused_cache: {exc}"
        else:
            cache = pd.DataFrame(columns=[*IOL_HISTORY_COLUMNS, "fetched_at"])
            cache_refresh_status = f"empty_cache: {exc}"
    history = load_iol_market_price_history(iol_cache_path)
    history = history[history["symbol"].isin(source_symbols)].copy()
    history = history[IOL_HISTORY_COLUMNS].copy() if not history.empty else pd.DataFrame(columns=IOL_HISTORY_COLUMNS)

    quote_overlay_rows = 0
    quote_overlay_symbols = 0
    quote_overlay_status = "disabled"
    try:
        quote_overlay = fetch_iol_quote_page_overlay(symbols=source_symbols, market=market, timeout_seconds=timeout_seconds)
        quote_overlay = quote_overlay[quote_overlay["symbol"].isin(source_symbols)].copy()
        quote_overlay_rows = len(quote_overlay)
        quote_overlay_symbols = int(quote_overlay["symbol"].nunique()) if not quote_overlay.empty else 0
        history = merge_iol_history_with_overlay(history=history, overlay=quote_overlay)
        quote_overlay_status = "ok" if quote_overlay_rows > 0 else "empty"
    except Exception as exc:
        quote_overlay_status = f"failed: {exc}"

    if not history.empty:
        history["symbol"] = history["symbol"].map(source_to_internal).fillna(history["symbol"])
    history = history[history["date"] <= end_ts].copy()
    history_out.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(history_out, index=False)

    existing_cer_index = _load_existing_cer_index(cer_index_out)
    processed_curve_fallback = _load_cer_index_from_processed_curve(DEFAULT_CER_INDEX_FALLBACK_HISTORY_PATH)
    cer_index_status = "live"
    try:
        cer_index = fetch_principales_variables_series(
            id_variable=int(cer_index_variable_id),
            start_date=cer_index_start_date,
            end_date=end_ts,
            verify_ssl=verify_ssl,
        )
        cer_index = cer_index.rename(columns={"value": "cer_index"})[["date", "cer_index"]].copy()
        if cer_index.empty:
            if not existing_cer_index.empty:
                cer_index = existing_cer_index.copy()
                cer_index_status = "reused_existing_file"
            elif not processed_curve_fallback.empty:
                cer_index = processed_curve_fallback.copy()
                cer_index_status = "rebuilt_from_processed_curve"
            else:
                cer_index_status = "empty_live_response"
        else:
            cer_index_status = "live"
    except Exception as exc:
        if not existing_cer_index.empty:
            cer_index = existing_cer_index.copy()
            cer_index_status = f"reused_existing_file: {exc}"
        elif not processed_curve_fallback.empty:
            cer_index = processed_curve_fallback.copy()
            cer_index_status = f"rebuilt_from_processed_curve: {exc}"
        else:
            cer_index = pd.DataFrame(columns=["date", "cer_index"])
            cer_index_status = f"failed_without_fallback: {exc}"
    cer_index_out.parent.mkdir(parents=True, exist_ok=True)
    cer_index.to_csv(cer_index_out, index=False)

    return {
        "market": market,
        "symbol_count": len(source_symbols),
        "history_rows": len(history),
        "cache_rows": len(cache),
        "cache_refresh_status": cache_refresh_status,
        "history_out": history_out,
        "cer_index_rows": len(cer_index),
        "cer_index_out": cer_index_out,
        "cer_index_status": cer_index_status,
        "quote_overlay_rows": quote_overlay_rows,
        "quote_overlay_symbols": quote_overlay_symbols,
        "quote_overlay_status": quote_overlay_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh live CER bond prices from IOL with same-day IOL quote-page overlay.")
    parser.add_argument("--market", type=str, default=DEFAULT_MARKET, help="IOL market code.")
    parser.add_argument("--show-browser", action="store_true", help="Run Selenium with a visible browser window.")
    parser.add_argument("--timeout-seconds", type=int, default=20, help="Selenium wait timeout per symbol.")
    parser.add_argument("--page-size", type=int, default=50, help="IOL rows per page.")
    parser.add_argument("--iol-cache-path", type=Path, default=DEFAULT_IOL_CACHE_PATH, help="IOL CER cache CSV.")
    parser.add_argument("--history-out", type=Path, default=DEFAULT_HISTORY_OUTPUT_PATH, help="Merged CER history CSV.")
    parser.add_argument("--cer-index-out", type=Path, default=DEFAULT_CER_INDEX_OUTPUT_PATH, help="BCRA CER index CSV.")
    parser.add_argument("--end-date", type=str, default=None, help="Optional inclusive end date YYYY-MM-DD.")
    parser.add_argument("--cer-index-start-date", type=str, default=DEFAULT_CER_START_DATE, help="BCRA CER history start date.")
    parser.add_argument("--cer-index-variable-id", type=int, default=DEFAULT_BCRA_CER_VARIABLE_ID, help="BCRA variable id for CER.")
    parser.add_argument("--verify-ssl", action="store_true", help="Verify SSL when hitting the BCRA API.")
    args = parser.parse_args()

    result = run_cer_reference(
        market=args.market,
        headless=not args.show_browser,
        timeout_seconds=args.timeout_seconds,
        page_size=args.page_size,
        iol_cache_path=args.iol_cache_path,
        history_out=args.history_out,
        cer_index_out=args.cer_index_out,
        end_date=args.end_date,
        cer_index_start_date=args.cer_index_start_date,
        cer_index_variable_id=args.cer_index_variable_id,
        verify_ssl=args.verify_ssl,
    )

    print(f"[cer] refreshed {result['symbol_count']} symbols for market {result['market']}")
    print(f"[cer] cache refresh status: {result['cache_refresh_status']}")
    print(f"[cer] history written: {args.history_out} ({result['history_rows']} rows)")
    print(
        f"[cer] BCRA CER index written: {args.cer_index_out} "
        f"({result['cer_index_rows']} rows, status={result['cer_index_status']})"
    )
    print(
        "[cer] quote-page overlay "
        f"status={result['quote_overlay_status']} rows={result['quote_overlay_rows']} "
        f"symbols={result['quote_overlay_symbols']}"
    )


if __name__ == "__main__":
    main()
