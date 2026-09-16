from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from src.common.config import DEFAULT_CONFIG_PATH, load_config
from src.common.dollar_linked import DOLLAR_LINKED_MARKET, DOLLAR_LINKED_SYMBOLS
from src.common.fixed_income import DEFAULT_IOL_INSTRUMENTS_DROP_PATH, hard_dollar_symbols
from src.common.io import RAW_DIR, ensure_data_dirs
from src.common.monetary_variables import (
    MONETARY_RATES_TNA_METRICS,
    MONETARY_RATES_TNA_RAW_COLUMNS,
    MONETARY_RATES_TNA_SPECS,
    MONETARY_VARIABLE_METRICS,
    MONETARY_VARIABLE_RAW_COLUMNS,
    MONETARY_VARIABLE_SPECS,
)
from src.ingest.bcra import fetch_principales_variables_series
from src.ingest.iol import fetch_iol_quote_page_snapshots, update_iol_market_price_cache
from src.ingest.run_cer_reference import run_cer_reference
from src.ingest.run_hard_dollar_reference import run_hard_dollar_reference
from src.ingest.run_iol_reference import (
    DEFAULT_HISTORY_INPUT_PATH as DEFAULT_IOL_HISTORY_INPUT_PATH,
    DEFAULT_METRICS_OUTPUT_PATH as DEFAULT_IOL_METRICS_OUTPUT_PATH,
    run_iol_reference,
)
from src.ingest.sources import build_cpi, build_fundamentals, build_prices


PRICES_FILE = RAW_DIR / "prices_nominal_daily.csv"
CPI_FILE = RAW_DIR / "cpi_monthly.csv"
FUNDAMENTALS_FILE = RAW_DIR / "fundamentals_annual_long.csv"
WARNINGS_FILE = RAW_DIR / "fundamentals_warnings.txt"
IOL_MARKET_PRICES_FILE = RAW_DIR / "iol_market_prices_history.csv"
DOLLAR_LINKED_SNAPSHOT_FILE = RAW_DIR / "iol_dollar_linked_snapshot.csv"
MONETARY_VARIABLES_FILE = RAW_DIR / "bcra_monetary_variables_daily.csv"
MONETARY_RATES_TNA_FILE = RAW_DIR / "bcra_rates_tna_daily.csv"


def _sync_iol_metadata_workbook(target_path: Path) -> list[str]:
    notes: list[str] = []
    drop_path = DEFAULT_IOL_INSTRUMENTS_DROP_PATH
    if not drop_path.exists():
        return notes

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_path.exists() or drop_path.read_bytes() != target_path.read_bytes():
        shutil.copy2(drop_path, target_path)
        notes.append(f"prep[iol_zero_coupon] synced metadata workbook from {drop_path.as_posix()} to {target_path.as_posix()}")
    return notes


def _refresh_iol_zero_coupon_if_needed(config: dict, end_ts: pd.Timestamp) -> list[str]:
    sources = dict(config.get("sources", {}))
    needs_refresh = any(
        isinstance(source_cfg, dict) and str(source_cfg.get("kind", "")).strip() == "iol_zero_coupon_roll_prices"
        for source_cfg in sources.values()
    )
    if not needs_refresh:
        return []

    refresh_cfg = dict(config.get("project", {}).get("iol_reference_refresh", {}))
    if refresh_cfg.get("enabled", True) is False:
        return ["prep[iol_zero_coupon] refresh disabled by project.iol_reference_refresh.enabled=false"]

    metadata_path = Path(refresh_cfg.get("metadata_path", "legacy/iol_reference/Instrumentos.xlsx"))
    prep_notes = _sync_iol_metadata_workbook(metadata_path)
    market = str(refresh_cfg.get("market", "BCBA"))
    show_browser = bool(refresh_cfg.get("show_browser", False))

    try:
        result = run_iol_reference(
            metadata=metadata_path,
            history_input=None,
            market=market,
            show_browser=show_browser,
        )
        return [
            *prep_notes,
            "prep[iol_zero_coupon] refreshed live metrics "
            f"symbols={result['symbol_count']} history_rows={result['history_rows']} "
            f"metric_rows={result['metric_rows']} source={result['history_source']}"
        ]
    except Exception as exc:
        cached_fallback_note = _reuse_iol_cached_outputs_note()
        if cached_fallback_note is not None:
            return [
                *prep_notes,
                "prep[iol_zero_coupon] live refresh failed; reused cached outputs "
                f"reason={type(exc).__name__}: {exc}",
                cached_fallback_note,
            ]

        workbook_fallback = _refresh_iol_zero_coupon_from_workbook(
            metadata_path=metadata_path,
            market=market,
            live_error=exc,
        )
        if workbook_fallback is not None:
            return [*prep_notes, *workbook_fallback]
        raise


def _reuse_iol_cached_outputs_note() -> str | None:
    metrics_path = DEFAULT_IOL_METRICS_OUTPUT_PATH
    if not metrics_path.exists() or metrics_path.stat().st_size == 0:
        return None

    updated_at = metrics_path.stat().st_mtime
    updated_ts = pd.Timestamp(updated_at, unit="s", tz="UTC").tz_convert("America/Buenos_Aires")
    return (
        "prep[iol_zero_coupon] cached metrics kept in place "
        f"path={metrics_path.as_posix()} updated_at={updated_ts.isoformat()}"
    )


def _refresh_iol_zero_coupon_from_workbook(
    *,
    metadata_path: Path,
    market: str,
    live_error: Exception,
) -> list[str] | None:
    workbook_path = DEFAULT_IOL_HISTORY_INPUT_PATH
    if not workbook_path.exists():
        return None

    result = run_iol_reference(
        metadata=metadata_path,
        history_input=workbook_path,
        market=market,
        show_browser=False,
    )
    return [
        "prep[iol_zero_coupon] live refresh failed; regenerated metrics from workbook "
        f"reason={type(live_error).__name__}: {live_error}",
        "prep[iol_zero_coupon] workbook fallback completed "
        f"symbols={result['symbol_count']} history_rows={result['history_rows']} "
        f"metric_rows={result['metric_rows']} source={result['history_source']}",
    ]


def _refresh_cer_reference_if_needed(config: dict, end_ts: pd.Timestamp) -> list[str]:
    assets = list(config.get("assets", []))
    needs_refresh = any(str(asset.get("asset", "")).strip() == "cer_1y_breakeven" for asset in assets)
    if not needs_refresh:
        return []

    refresh_cfg = dict(config.get("project", {}).get("cer_reference_refresh", {}))
    if refresh_cfg.get("enabled", True) is False:
        return ["prep[cer_reference] refresh disabled by project.cer_reference_refresh.enabled=false"]

    result = run_cer_reference(
        market=str(refresh_cfg.get("market", "BCBA")),
        headless=bool(refresh_cfg.get("headless", True)),
        timeout_seconds=int(refresh_cfg.get("timeout_seconds", 20)),
        page_size=int(refresh_cfg.get("page_size", 50)),
        iol_cache_path=Path(refresh_cfg.get("iol_cache_path", "data/raw/iol_cer_prices_history.csv")),
        history_out=Path(refresh_cfg.get("history_path", "data/raw/cer_bond_prices_history.csv")),
        cer_index_out=Path(refresh_cfg.get("cer_index_path", "data/raw/bcra_cer_index_daily.csv")),
        end_date=end_ts,
        cer_index_start_date=str(refresh_cfg.get("cer_index_start_date", "2025-01-01")),
        cer_index_variable_id=int(refresh_cfg.get("cer_index_variable_id", 30)),
        verify_ssl=bool(refresh_cfg.get("verify_ssl", False)),
    )
    return [
        "prep[cer_reference] refreshed live CER history "
        f"symbols={result['symbol_count']} history_rows={result['history_rows']} "
        f"cer_index_rows={result['cer_index_rows']} quote_status={result['quote_overlay_status']}"
    ]


def _refresh_hard_dollar_reference_if_needed(config: dict) -> list[str]:
    sources = dict(config.get("sources", {}))
    hard_dollar_set = set(hard_dollar_symbols())
    needs_refresh = False
    for source_cfg in sources.values():
        if not isinstance(source_cfg, dict):
            continue
        for entry in source_cfg.get("series", []) or []:
            if str(entry.get("symbol", "")).strip().upper() in hard_dollar_set:
                needs_refresh = True
                break
        if needs_refresh:
            break
    if not needs_refresh:
        return []

    refresh_cfg = dict(config.get("project", {}).get("hard_dollar_reference_refresh", {}))
    if refresh_cfg.get("enabled", True) is False:
        return ["prep[hard_dollar_reference] refresh disabled by project.hard_dollar_reference_refresh.enabled=false"]

    result = run_hard_dollar_reference(
        timeout_seconds=int(refresh_cfg.get("timeout_seconds", 20)),
    )
    if result.get("source") == "cached":
        return [
            "prep[hard_dollar_reference] live refresh failed; reused cached contractual reference "
            f"reason={result.get('fallback_reason', 'unknown')}",
            "prep[hard_dollar_reference] cached dataset kept in place "
            f"symbols={result['symbol_count']} metadata_rows={result['metadata_rows']} "
            f"flow_rows={result['flow_rows']}",
        ]
    return [
        "prep[hard_dollar_reference] refreshed contractual reference "
        f"symbols={result['symbol_count']} metadata_rows={result['metadata_rows']} "
        f"flow_rows={result['flow_rows']}"
    ]


def _refresh_dollar_linked_if_needed(config: dict) -> list[str]:
    refresh_cfg = dict(config.get("project", {}).get("dollar_linked_refresh", {}))
    if refresh_cfg.get("enabled", True) is False:
        return ["prep[dollar_linked] refresh disabled by project.dollar_linked_refresh.enabled=false"]

    # Keep the public monitor aligned with the hard-dollar path: the same-day
    # quote-page overlay should advance the historical cache before IOL's
    # historical table catches up.
    history = update_iol_market_price_cache(
        path=Path(refresh_cfg.get("history_path", IOL_MARKET_PRICES_FILE)),
        symbols=DOLLAR_LINKED_SYMBOLS,
        market=str(refresh_cfg.get("market", DOLLAR_LINKED_MARKET)),
        headless=bool(refresh_cfg.get("headless", True)),
        timeout_seconds=int(refresh_cfg.get("timeout_seconds", 20)),
        page_size=int(refresh_cfg.get("page_size", 200)),
        include_quote_overlay=True,
    )
    history = history[history["symbol"].isin(DOLLAR_LINKED_SYMBOLS)].copy()

    snapshots = fetch_iol_quote_page_snapshots(
        symbols=DOLLAR_LINKED_SYMBOLS,
        market=str(refresh_cfg.get("market", DOLLAR_LINKED_MARKET)),
        timeout_seconds=int(refresh_cfg.get("quote_timeout_seconds", 30)),
    )
    DOLLAR_LINKED_SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    snapshots.to_csv(Path(refresh_cfg.get("snapshot_path", DOLLAR_LINKED_SNAPSHOT_FILE)), index=False)

    latest_history_date = None
    if not history.empty and "date" in history.columns:
        latest_history_date = pd.to_datetime(history["date"], errors="coerce").dropna().max()

    snapshot_date = None
    if not snapshots.empty and "date" in snapshots.columns:
        snapshot_date = pd.to_datetime(snapshots["date"], errors="coerce").dropna().max()

    return [
        "prep[dollar_linked] refreshed monitor universe "
        f"symbols={len(DOLLAR_LINKED_SYMBOLS)} history_rows={len(history)} "
        f"snapshot_rows={len(snapshots)} "
        f"history_latest={(latest_history_date.strftime('%Y-%m-%d') if latest_history_date is not None else 'n/a')} "
        f"snapshot_date={(snapshot_date.strftime('%Y-%m-%d') if snapshot_date is not None else 'n/a')}"
    ]


def _refresh_monetary_variables_if_needed(config: dict, end_ts: pd.Timestamp) -> list[str]:
    refresh_cfg = dict(config.get("project", {}).get("monetary_variables_refresh", {}))
    if refresh_cfg.get("enabled", True) is False:
        return ["prep[monetary_variables] refresh disabled by project.monetary_variables_refresh.enabled=false"]

    output_path = Path(refresh_cfg.get("path", MONETARY_VARIABLES_FILE))
    start_date = refresh_cfg.get("start_date", "2022-01-01")
    page_size = int(refresh_cfg.get("page_size", 1000))
    verify_ssl = bool(refresh_cfg.get("verify_ssl", False))

    rows: list[pd.DataFrame] = []
    try:
        for spec in MONETARY_VARIABLE_SPECS:
            frame = fetch_principales_variables_series(
                id_variable=int(spec["source_id"]),
                start_date=start_date,
                end_date=end_ts,
                page_size=page_size,
                verify_ssl=verify_ssl,
            )
            if frame.empty:
                continue
            frame = frame.rename(columns={"id_variable": "source_id"})
            frame["metric"] = spec["metric"]
            frame["label"] = spec["label"]
            frame["unit"] = spec["unit"]
            rows.append(frame[MONETARY_VARIABLE_RAW_COLUMNS])
    except Exception as exc:
        if output_path.exists() and output_path.stat().st_size > 0:
            cached = pd.read_csv(output_path)
            latest_date = None
            if "date" in cached.columns and not cached.empty:
                latest_date = pd.to_datetime(cached["date"], errors="coerce").dropna().max()
            return [
                "prep[monetary_variables] live refresh failed; reused cached output "
                f"reason={type(exc).__name__}: {exc}",
                "prep[monetary_variables] cached dataset kept in place "
                f"metrics={cached.get('metric', pd.Series(dtype='object')).astype(str).nunique()} "
                f"rows={len(cached)} "
                f"latest_date={(latest_date.strftime('%Y-%m-%d') if latest_date is not None else 'n/a')}",
            ]
        raise

    combined = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=MONETARY_VARIABLE_RAW_COLUMNS)
    combined["date"] = pd.to_datetime(combined.get("date"), errors="coerce").dt.normalize()
    combined["value"] = pd.to_numeric(combined.get("value"), errors="coerce")
    combined["source_id"] = pd.to_numeric(combined.get("source_id"), errors="coerce").astype("Int64")
    combined = combined.dropna(subset=["date", "metric", "value"]).copy()
    combined = (
        combined.sort_values(["metric", "date", "source_id"])
        .drop_duplicates(subset=["metric", "date"], keep="last")
        .reset_index(drop=True)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)

    latest_date = pd.to_datetime(combined["date"], errors="coerce").dropna().max() if not combined.empty else None
    return [
        "prep[monetary_variables] refreshed BCRA monetary series "
        f"metrics={combined['metric'].nunique() if not combined.empty else 0} "
        f"rows={len(combined)} "
        f"tracked_metrics={combined['metric'].isin(MONETARY_VARIABLE_METRICS).sum()} "
        f"latest_date={(latest_date.strftime('%Y-%m-%d') if latest_date is not None else 'n/a')}"
    ]


def _refresh_monetary_rates_tna_if_needed(config: dict, end_ts: pd.Timestamp) -> list[str]:
    refresh_cfg = dict(config.get("project", {}).get("monetary_rates_tna_refresh", {}))
    if refresh_cfg.get("enabled", True) is False:
        return ["prep[monetary_rates_tna] refresh disabled by project.monetary_rates_tna_refresh.enabled=false"]

    output_path = Path(refresh_cfg.get("path", MONETARY_RATES_TNA_FILE))
    start_date = refresh_cfg.get("start_date", "2022-01-01")
    page_size = int(refresh_cfg.get("page_size", 1000))
    verify_ssl = bool(refresh_cfg.get("verify_ssl", False))

    rows: list[pd.DataFrame] = []
    try:
        for spec in MONETARY_RATES_TNA_SPECS:
            frame = fetch_principales_variables_series(
                id_variable=int(spec["source_id"]),
                start_date=start_date,
                end_date=end_ts,
                page_size=page_size,
                verify_ssl=verify_ssl,
            )
            if frame.empty:
                continue
            frame = frame.rename(columns={"id_variable": "source_id"})
            frame["metric"] = spec["metric"]
            frame["label"] = spec["label"]
            frame["unit"] = spec["unit"]
            rows.append(frame[MONETARY_RATES_TNA_RAW_COLUMNS])
    except Exception as exc:
        if output_path.exists() and output_path.stat().st_size > 0:
            cached = pd.read_csv(output_path)
            latest_date = None
            if "date" in cached.columns and not cached.empty:
                latest_date = pd.to_datetime(cached["date"], errors="coerce").dropna().max()
            return [
                "prep[monetary_rates_tna] live refresh failed; reused cached output "
                f"reason={type(exc).__name__}: {exc}",
                "prep[monetary_rates_tna] cached dataset kept in place "
                f"metrics={cached.get('metric', pd.Series(dtype='object')).astype(str).nunique()} "
                f"rows={len(cached)} "
                f"latest_date={(latest_date.strftime('%Y-%m-%d') if latest_date is not None else 'n/a')}",
            ]
        raise

    combined = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=MONETARY_RATES_TNA_RAW_COLUMNS)
    combined["date"] = pd.to_datetime(combined.get("date"), errors="coerce").dt.normalize()
    combined["value"] = pd.to_numeric(combined.get("value"), errors="coerce")
    combined["source_id"] = pd.to_numeric(combined.get("source_id"), errors="coerce").astype("Int64")
    combined = combined.dropna(subset=["date", "metric", "value"]).copy()
    combined = (
        combined.sort_values(["metric", "date", "source_id"])
        .drop_duplicates(subset=["metric", "date"], keep="last")
        .reset_index(drop=True)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)

    latest_date = pd.to_datetime(combined["date"], errors="coerce").dropna().max() if not combined.empty else None
    return [
        "prep[monetary_rates_tna] refreshed BCRA rate series "
        f"metrics={combined['metric'].nunique() if not combined.empty else 0} "
        f"rows={len(combined)} "
        f"tracked_metrics={combined['metric'].isin(MONETARY_RATES_TNA_METRICS).sum()} "
        f"latest_date={(latest_date.strftime('%Y-%m-%d') if latest_date is not None else 'n/a')}"
    ]


def run(config_path: Path = DEFAULT_CONFIG_PATH, end_date: str | None = None) -> dict[str, Path]:
    ensure_data_dirs()
    config_path = Path(config_path)
    config = load_config(config_path)
    assets = list(config.get("assets", []))
    if not assets:
        raise ValueError("Config file is missing assets.")

    end_ts = pd.Timestamp(end_date).normalize() if end_date else pd.Timestamp.today().normalize()
    prep_notes = _refresh_iol_zero_coupon_if_needed(config=config, end_ts=end_ts)
    prep_notes.extend(_refresh_cer_reference_if_needed(config=config, end_ts=end_ts))
    prep_notes.extend(_refresh_hard_dollar_reference_if_needed(config=config))
    prep_notes.extend(_refresh_dollar_linked_if_needed(config=config))
    prep_notes.extend(_refresh_monetary_variables_if_needed(config=config, end_ts=end_ts))
    prep_notes.extend(_refresh_monetary_rates_tna_if_needed(config=config, end_ts=end_ts))

    prices, price_notes = build_prices(config=config, assets=assets, config_path=config_path, end_ts=end_ts)
    cpi, cpi_notes = build_cpi(config=config, config_path=config_path, end_ts=end_ts)
    fundamentals, fundamentals_notes = build_fundamentals(
        config=config,
        assets=assets,
        config_path=config_path,
        end_ts=end_ts,
    )
    if prices.empty:
        raise ValueError("Price ingestion produced no rows. Check the configured price sources.")
    if cpi.empty:
        raise ValueError("CPI ingestion produced no rows. Check the configured CPI source.")

    prices.to_csv(PRICES_FILE, index=False)
    cpi.to_csv(CPI_FILE, index=False)
    fundamentals.to_csv(FUNDAMENTALS_FILE, index=False)

    warning_lines = [
        "Ingestion source summary:",
        *[f"- {note}" for note in prep_notes],
        *[f"- {note}" for note in price_notes],
        *[f"- {note}" for note in cpi_notes],
        *[f"- {note}" for note in fundamentals_notes],
    ]
    synthetic_kinds = [note for note in price_notes + cpi_notes + fundamentals_notes if "kind=synthetic_" in note]
    if synthetic_kinds:
        warning_lines.append(
            "- Active sources still include scaffold placeholders. Replace them with CSV or API connectors for production."
        )
    WARNINGS_FILE.write_text("\n".join(warning_lines) + "\n", encoding="utf-8")

    return {
        "prices": PRICES_FILE,
        "cpi": CPI_FILE,
        "fundamentals": FUNDAMENTALS_FILE,
        "fundamentals_warnings": WARNINGS_FILE,
        "monetary_variables_raw": MONETARY_VARIABLES_FILE,
        "monetary_rates_tna_raw": MONETARY_RATES_TNA_FILE,
    }


if __name__ == "__main__":
    run()
