from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH
from src.common.io import PROCESSED_DIR, RAW_DIR, ensure_data_dirs
from src.ingest.iol import (
    compute_zero_coupon_metrics,
    fetch_iol_quote_page_overlay,
    latest_zero_coupon_snapshot,
    load_iol_history_workbook,
    load_iol_instrument_metadata,
    merge_iol_history_with_overlay,
    scrape_iol_histories,
)


DEFAULT_METADATA_PATH = Path("legacy/iol_reference/Instrumentos.xlsx")
DEFAULT_HISTORY_INPUT_PATH = Path("legacy/iol_reference/historico_actualizado.xlsx")
DEFAULT_HISTORY_OUTPUT_PATH = RAW_DIR / "iol_prices_history.csv"
DEFAULT_METRICS_OUTPUT_PATH = PROCESSED_DIR / "iol_zero_coupon_metrics.csv"
DEFAULT_SNAPSHOT_OUTPUT_PATH = PROCESSED_DIR / "iol_zero_coupon_snapshot.csv"


def run_iol_reference(
    metadata: Path = DEFAULT_METADATA_PATH,
    history_input: Path | None = DEFAULT_HISTORY_INPUT_PATH,
    market: str = "BCBA",
    calendar: Path = DEFAULT_MARKET_CALENDAR_PATH,
    symbols: str = "",
    show_browser: bool = False,
    history_out: Path = DEFAULT_HISTORY_OUTPUT_PATH,
    metrics_out: Path = DEFAULT_METRICS_OUTPUT_PATH,
    snapshot_out: Path = DEFAULT_SNAPSHOT_OUTPUT_PATH,
) -> dict[str, Path | int | str]:
    ensure_data_dirs()
    metadata_frame = load_iol_instrument_metadata(metadata)
    selected_symbols = _parse_symbol_filter(symbols)
    if selected_symbols:
        metadata_frame = metadata_frame[metadata_frame["symbol"].isin(selected_symbols)].copy()
    if metadata_frame.empty:
        raise ValueError("No instruments remain after applying the symbol filter.")

    supplemental_history_rows = 0
    supplemental_history_symbols = 0
    if history_input is not None and history_input.exists():
        history = load_iol_history_workbook(history_input, market=market)
        history_source = f"workbook={history_input}"
        history_symbols = set(history["symbol"].astype(str).str.upper().dropna().unique().tolist())
        missing_symbols = [
            symbol
            for symbol in metadata_frame["symbol"].astype(str).str.upper().tolist()
            if symbol not in history_symbols
        ]
        if missing_symbols:
            supplemental = scrape_iol_histories(
                symbols=missing_symbols,
                market=market,
                headless=not show_browser,
            )
            supplemental = supplemental[supplemental["symbol"].isin(missing_symbols)].copy()
            supplemental_history_rows = len(supplemental)
            supplemental_history_symbols = int(supplemental["symbol"].nunique()) if not supplemental.empty else 0
            if not supplemental.empty:
                history = (
                    pd.concat([history, supplemental], ignore_index=True)
                    .sort_values(["date", "symbol", "market", "source"])
                    .drop_duplicates(subset=["date", "symbol", "market"], keep="last")
                    .sort_values(["symbol", "date"])
                    .reset_index(drop=True)
                )
                history_source = f"{history_source}+live_missing"
    else:
        history = scrape_iol_histories(
            symbols=metadata_frame["symbol"].tolist(),
            market=market,
            headless=not show_browser,
        )
        history_source = "live_iol_scrape"

    history = history[history["symbol"].isin(metadata_frame["symbol"])].copy()
    if history.empty:
        raise ValueError("IOL history ingestion produced no rows for the selected symbols.")

    quote_overlay_rows = 0
    quote_overlay_symbols = 0
    quote_overlay_status = "disabled"
    try:
        quote_overlay = fetch_iol_quote_page_overlay(symbols=metadata_frame["symbol"].tolist(), market=market)
        quote_overlay = quote_overlay[quote_overlay["symbol"].isin(metadata_frame["symbol"])].copy()
        quote_overlay_rows = len(quote_overlay)
        quote_overlay_symbols = int(quote_overlay["symbol"].nunique()) if not quote_overlay.empty else 0
        history = merge_iol_history_with_overlay(history=history, overlay=quote_overlay)
        quote_overlay_status = "ok" if quote_overlay_rows > 0 else "empty"
    except Exception as exc:
        quote_overlay_status = f"failed: {exc}"

    metrics = compute_zero_coupon_metrics(history=history, metadata=metadata_frame, calendar_path=calendar)
    snapshot = latest_zero_coupon_snapshot(metrics)

    history_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    snapshot_out.parent.mkdir(parents=True, exist_ok=True)

    history.to_csv(history_out, index=False)
    metrics.to_csv(metrics_out, index=False)
    snapshot.to_csv(snapshot_out, index=False)

    return {
        "metadata_path": metadata,
        "history_source": history_source,
        "history_out": history_out,
        "metrics_out": metrics_out,
        "snapshot_out": snapshot_out,
        "symbol_count": len(metadata_frame),
        "history_rows": len(history),
        "metric_rows": len(metrics),
        "snapshot_rows": len(snapshot),
        "quote_overlay_rows": quote_overlay_rows,
        "quote_overlay_symbols": quote_overlay_symbols,
        "quote_overlay_status": quote_overlay_status,
        "supplemental_history_rows": supplemental_history_rows,
        "supplemental_history_symbols": supplemental_history_symbols,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize the IOL legacy reference into repo CSV outputs.")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH, help="Path to the IOL metadata workbook.")
    parser.add_argument(
        "--history-input",
        type=Path,
        default=DEFAULT_HISTORY_INPUT_PATH,
        help="Optional existing IOL history workbook. If missing, the script scrapes live history from IOL.",
    )
    parser.add_argument("--market", type=str, default="BCBA", help="IOL market code.")
    parser.add_argument("--calendar", type=Path, default=DEFAULT_MARKET_CALENDAR_PATH, help="Business calendar CSV.")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Optional comma-separated symbol subset. Default uses every symbol in the metadata workbook.",
    )
    parser.add_argument("--show-browser", action="store_true", help="Run Selenium with a visible browser window.")
    parser.add_argument("--history-out", type=Path, default=DEFAULT_HISTORY_OUTPUT_PATH, help="Normalized daily history CSV.")
    parser.add_argument(
        "--metrics-out",
        type=Path,
        default=DEFAULT_METRICS_OUTPUT_PATH,
        help="Per-date zero-coupon metric history CSV.",
    )
    parser.add_argument(
        "--snapshot-out",
        type=Path,
        default=DEFAULT_SNAPSHOT_OUTPUT_PATH,
        help="Latest available metric snapshot CSV.",
    )
    args = parser.parse_args()

    result = run_iol_reference(
        metadata=args.metadata,
        history_input=args.history_input,
        market=args.market,
        calendar=args.calendar,
        symbols=args.symbols,
        show_browser=args.show_browser,
        history_out=args.history_out,
        metrics_out=args.metrics_out,
        snapshot_out=args.snapshot_out,
    )

    print(f"[iol] metadata loaded: {result['symbol_count']} symbols from {args.metadata}")
    print(f"[iol] history loaded from {result['history_source']}: {result['history_rows']} rows")
    print(
        "[iol] quote-page overlay "
        f"status={result['quote_overlay_status']} rows={result['quote_overlay_rows']} "
        f"symbols={result['quote_overlay_symbols']}"
    )
    if result["supplemental_history_symbols"]:
        print(
            "[iol] supplemental live history "
            f"rows={result['supplemental_history_rows']} symbols={result['supplemental_history_symbols']}"
        )
    print(f"[iol] history written: {args.history_out}")
    print(f"[iol] metrics written: {args.metrics_out} ({result['metric_rows']} rows)")
    print(f"[iol] snapshot written: {args.snapshot_out} ({result['snapshot_rows']} rows)")


def _parse_symbol_filter(raw_value: str) -> set[str]:
    if not raw_value.strip():
        return set()
    return {symbol.strip().upper() for symbol in raw_value.split(",") if symbol.strip()}


if __name__ == "__main__":
    main()
