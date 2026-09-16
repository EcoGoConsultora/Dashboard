from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.cer_breakeven import (
    build_breakeven_monitor_live,
    cer_publication_window_end,
    load_cer_index_history,
    load_cer_price_history,
    select_target_breakeven_metrics,
)
from src.ingest.bcra import fetch_estadisticas_cambiarias_series, fetch_principales_variables_series
from src.ingest.byma import (
    _coerce_numeric,
    _extract_numeric_from_fields,
    _fetch_paginated_direct_records,
    QUOTE_COLUMNS,
    extract_quotes_from_snapshot,
    fetch_index_historical_series,
    fetch_dashboard_snapshot,
    load_quote_cache,
    merge_quote_cache,
    save_snapshot,
)
from src.ingest.iol import (
    load_iol_market_price_history,
    load_iol_zero_coupon_metrics,
    select_target_maturity_metrics,
    update_iol_market_price_cache,
)
from src.ingest.web_prices import (
    fetch_ambito_chart_series,
    fetch_argentinadatos_riesgo_pais_history,
    fetch_argentinadatos_riesgo_pais_snapshot,
    fetch_bondterminal_embi_history,
    fetch_bondterminal_riesgo_pais_snapshot,
    fetch_fred_graph_series,
    fetch_yahoo_chart_series,
    load_web_price_cache,
    merge_web_price_cache,
)


PRICE_COLUMNS = ["date", "asset", "asset_label", "category", "unit", "value_nominal", "source", "source_detail", "source_url"]
CPI_COLUMNS = ["date", "cpi_index"]
FUNDAMENTALS_COLUMNS = [
    "year",
    "asset",
    "asset_label",
    "category",
    "scope",
    "metric",
    "metric_label",
    "value",
    "source",
]

DEFAULT_PRICE_SOURCE_ID = "synthetic_prices"
DEFAULT_CPI_SOURCE_ID = "synthetic_cpi"
DEFAULT_FUNDAMENTALS_SOURCE_ID = "synthetic_fundamentals"

DEFAULT_SOURCE_DEFS: dict[str, dict[str, Any]] = {
    DEFAULT_PRICE_SOURCE_ID: {"kind": "synthetic_prices", "start_date": "2022-01-03"},
    DEFAULT_CPI_SOURCE_ID: {"kind": "synthetic_cpi", "start_date": "2021-12-01"},
    DEFAULT_FUNDAMENTALS_SOURCE_ID: {"kind": "synthetic_fundamentals", "history_years": 6, "min_year": 2018},
}


def _stable_seed(text: str) -> int:
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _asset_metadata_frame(assets: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "asset": asset_cfg["asset"],
            "asset_label_cfg": asset_cfg["label"],
            "category_cfg": asset_cfg["category"],
            "unit_cfg": asset_cfg["unit"],
            "metric_cfg": asset_cfg.get("fundamental_metric", "macro_proxy"),
            "metric_label_cfg": asset_cfg.get("fundamental_label", "Macro Proxy"),
        }
        for asset_cfg in assets
    ]
    return pd.DataFrame(rows)


def _get_source_defs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source_defs = {source_id: source_cfg.copy() for source_id, source_cfg in DEFAULT_SOURCE_DEFS.items()}
    for source_id, source_cfg in dict(config.get("sources", {})).items():
        if not isinstance(source_cfg, dict):
            raise ValueError(f"Source '{source_id}' must be an object.")
        merged = source_defs.get(source_id, {}).copy()
        merged.update(source_cfg)
        source_defs[source_id] = merged
    return source_defs


def _get_defaults(config: dict[str, Any]) -> dict[str, str]:
    defaults = {
        "price_source": DEFAULT_PRICE_SOURCE_ID,
        "fundamentals_source": DEFAULT_FUNDAMENTALS_SOURCE_ID,
        "cpi_source": DEFAULT_CPI_SOURCE_ID,
    }
    defaults.update(dict(config.get("defaults", {})))
    return defaults


def _resolve_source_path(config_path: Path, source_cfg: dict[str, Any]) -> Path:
    raw_path = source_cfg.get("path")
    if not raw_path:
        raise ValueError("CSV source is missing its 'path' setting.")

    return _resolve_config_path(config_path, raw_path)


def _resolve_config_path(config_path: Path, raw_path: Any) -> Path:
    if raw_path is None or raw_path == "":
        raise ValueError("Source path setting is missing.")

    path = Path(str(raw_path))
    if path.is_absolute():
        return path

    return (Path.cwd() / path).resolve()


def _load_previous_external_payload_prices(
    *,
    payload_path: Path,
    assets: list[dict[str, Any]],
    series_lookup: dict[str, dict[str, Any]],
    source_name: str,
    source_url_base: str,
) -> pd.DataFrame:
    if not payload_path.exists() or payload_path.stat().st_size == 0:
        return pd.DataFrame(columns=["date", "asset", "value_nominal", "source", "source_url", "source_detail"])

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return pd.DataFrame(columns=["date", "asset", "value_nominal", "source", "source_url", "source_detail"])

    external = payload.get("external_context", {})
    if not isinstance(external, dict):
        return pd.DataFrame(columns=["date", "asset", "value_nominal", "source", "source_url", "source_detail"])

    latest_items = external.get("benchmark_strip", [])
    latest_lookup = {
        str(item.get("asset")): item
        for item in latest_items
        if isinstance(item, dict) and item.get("asset") is not None
    }
    series_payload = external.get("series", {})
    if not isinstance(series_payload, dict):
        series_payload = {}

    rows: list[dict[str, Any]] = []
    for asset_cfg in assets:
        target_asset = str(asset_cfg["asset"])
        entry = series_lookup.get(target_asset, {})
        series_id = str(entry.get("series_id", "")).strip()
        source_url = (
            str(latest_lookup.get(target_asset, {}).get("source_url") or "").strip()
            or f"{source_url_base.rstrip('/')}/graph/fredgraph.csv?id={series_id}"
        )
        source_detail = f"fred_graph:{series_id}" if series_id else source_name
        asset_series = series_payload.get(target_asset, [])
        candidate_rows: list[dict[str, Any]] = []
        if isinstance(asset_series, list):
            for point in asset_series:
                if not isinstance(point, dict):
                    continue
                if point.get("date") is None or point.get("value") is None:
                    continue
                candidate_rows.append(
                    {
                        "date": point.get("date"),
                        "asset": target_asset,
                        "value_nominal": point.get("value"),
                        "source": source_name,
                        "source_url": source_url,
                        "source_detail": source_detail,
                    }
                )

        if candidate_rows:
            rows.extend(candidate_rows)
        else:
            latest = latest_lookup.get(target_asset)
            if isinstance(latest, dict):
                rows.append(
                    {
                        "date": latest.get("date"),
                        "asset": target_asset,
                        "value_nominal": latest.get("value"),
                        "source": source_name,
                        "source_url": source_url,
                        "source_detail": source_detail,
                    }
                )

    frame = pd.DataFrame(rows, columns=["date", "asset", "value_nominal", "source", "source_url", "source_detail"])
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["value_nominal"] = pd.to_numeric(frame["value_nominal"], errors="coerce")
    frame = frame.dropna(subset=["date", "asset", "value_nominal"]).copy()
    return frame.sort_values(["asset", "date"]).drop_duplicates(["date", "asset"], keep="last").reset_index(drop=True)


def _fill_column_from_join(frame: pd.DataFrame, column: str, fallback: str) -> pd.DataFrame:
    if column not in frame.columns:
        frame[column] = pd.NA
    if fallback in frame.columns:
        frame[column] = frame[column].fillna(frame[fallback])
        frame = frame.drop(columns=[fallback])
    return frame


def _validate_missing_columns(frame: pd.DataFrame, required_columns: list[str], label: str) -> None:
    missing_columns = [column for column in required_columns if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing_columns)}")


def _validate_duplicate_keys(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    duplicates = frame[frame.duplicated(keys, keep=False)]
    if not duplicates.empty:
        sample = duplicates[keys].head(3).to_dict(orient="records")
        raise ValueError(f"{label} has duplicate keys on {keys}: {sample}")


def _get_series_lookup(source_cfg: dict[str, Any], source_id: str, label: str) -> dict[str, dict[str, Any]]:
    raw_entries = source_cfg.get("series", [])
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(f"{label} source '{source_id}' must define a non-empty 'series' list.")

    lookup: dict[str, dict[str, Any]] = {}
    for entry in raw_entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{label} source '{source_id}' has a non-object series entry.")
        asset = str(entry.get("asset", "")).strip()
        if not asset:
            raise ValueError(f"{label} source '{source_id}' has a series entry without 'asset'.")
        if asset in lookup:
            raise ValueError(f"{label} source '{source_id}' repeats asset '{asset}' in its series mapping.")
        lookup[asset] = entry
    return lookup


def _normalize_prices_frame(
    frame: pd.DataFrame,
    assets: list[dict[str, Any]],
    source_id: str,
    allow_partial: bool,
) -> tuple[pd.DataFrame, list[str]]:
    asset_meta = _asset_metadata_frame(assets)
    expected_assets = {str(asset_cfg["asset"]) for asset_cfg in assets}
    notes: list[str] = []

    _validate_missing_columns(frame, ["date", "asset", "value_nominal"], f"Price source '{source_id}'")
    merged = frame.copy()
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.normalize()
    merged["asset"] = merged["asset"].astype(str)
    merged["value_nominal"] = pd.to_numeric(merged["value_nominal"], errors="coerce")
    merged = merged[merged["asset"].isin(expected_assets)].copy()
    merged = merged.merge(asset_meta[["asset", "asset_label_cfg", "category_cfg", "unit_cfg"]], on="asset", how="left")
    merged = _fill_column_from_join(merged, "asset_label", "asset_label_cfg")
    merged = _fill_column_from_join(merged, "category", "category_cfg")
    merged = _fill_column_from_join(merged, "unit", "unit_cfg")
    if "source" not in merged.columns:
        merged["source"] = source_id
    merged["source"] = merged["source"].fillna(source_id)
    if "source_detail" not in merged.columns:
        merged["source_detail"] = source_id
    merged["source_detail"] = merged["source_detail"].fillna(source_id)
    if "source_url" not in merged.columns:
        merged["source_url"] = ""
    merged["source_url"] = merged["source_url"].fillna("")

    _validate_missing_columns(merged, PRICE_COLUMNS, f"Price source '{source_id}'")
    if merged[PRICE_COLUMNS].isna().any().any():
        raise ValueError(f"Price source '{source_id}' contains null values after normalization.")
    _validate_duplicate_keys(merged, ["date", "asset"], f"Price source '{source_id}'")

    observed_assets = set(merged["asset"].unique())
    missing_assets = sorted(expected_assets - observed_assets)
    if missing_assets:
        message = f"Price source '{source_id}' is missing configured assets: {', '.join(missing_assets)}"
        if allow_partial:
            notes.append(message)
        else:
            raise ValueError(message)

    return merged[PRICE_COLUMNS].sort_values(["category", "asset_label", "date"]).reset_index(drop=True), notes


def _normalize_cpi_frame(frame: pd.DataFrame, source_id: str) -> pd.DataFrame:
    _validate_missing_columns(frame, CPI_COLUMNS, f"CPI source '{source_id}'")
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    normalized["cpi_index"] = pd.to_numeric(normalized["cpi_index"], errors="coerce")
    if normalized[CPI_COLUMNS].isna().any().any():
        raise ValueError(f"CPI source '{source_id}' contains null values after normalization.")
    _validate_duplicate_keys(normalized, ["date"], f"CPI source '{source_id}'")
    return normalized[CPI_COLUMNS].sort_values("date").reset_index(drop=True)


def _normalize_fundamentals_frame(
    frame: pd.DataFrame,
    assets: list[dict[str, Any]],
    source_id: str,
    allow_partial: bool,
) -> tuple[pd.DataFrame, list[str]]:
    asset_meta = _asset_metadata_frame(assets)
    expected_assets = {str(asset_cfg["asset"]) for asset_cfg in assets}
    notes: list[str] = []

    _validate_missing_columns(frame, ["year", "asset", "value"], f"Fundamentals source '{source_id}'")
    merged = frame.copy()
    merged["year"] = pd.to_numeric(merged["year"], errors="coerce").astype("Int64")
    merged["asset"] = merged["asset"].astype(str)
    merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
    merged = merged[merged["asset"].isin(expected_assets)].copy()
    merged = merged.merge(asset_meta, on="asset", how="left")
    merged = _fill_column_from_join(merged, "asset_label", "asset_label_cfg")
    merged = _fill_column_from_join(merged, "category", "category_cfg")
    merged = _fill_column_from_join(merged, "metric", "metric_cfg")
    merged = _fill_column_from_join(merged, "metric_label", "metric_label_cfg")
    if "scope" not in merged.columns:
        merged["scope"] = "Argentina"
    else:
        merged["scope"] = merged["scope"].fillna("Argentina")
    if "source" not in merged.columns:
        merged["source"] = source_id
    else:
        merged["source"] = merged["source"].fillna(source_id)

    _validate_missing_columns(merged, FUNDAMENTALS_COLUMNS, f"Fundamentals source '{source_id}'")
    if merged[FUNDAMENTALS_COLUMNS].isna().any().any():
        raise ValueError(f"Fundamentals source '{source_id}' contains null values after normalization.")
    _validate_duplicate_keys(merged, ["year", "asset", "metric"], f"Fundamentals source '{source_id}'")

    observed_assets = set(merged["asset"].unique())
    missing_assets = sorted(expected_assets - observed_assets)
    if missing_assets:
        message = f"Fundamentals source '{source_id}' is missing configured assets: {', '.join(missing_assets)}"
        if allow_partial:
            notes.append(message)
        else:
            raise ValueError(message)

    return (
        merged[FUNDAMENTALS_COLUMNS].sort_values(["category", "asset_label", "year", "metric"]).reset_index(drop=True),
        notes,
    )


def _build_synthetic_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    start_date = str(source_cfg.get("start_date", "2022-01-03"))
    dates = pd.bdate_range(start_date, end_ts)
    frames: list[pd.DataFrame] = []
    for asset_cfg in assets:
        seed = _stable_seed(str(asset_cfg["asset"]))
        rng = np.random.default_rng(seed)
        drift = float(asset_cfg.get("daily_drift", 0.0003))
        vol = float(asset_cfg.get("daily_vol", 0.0080))
        base_value = float(asset_cfg.get("base_value", 100.0))
        shocks = rng.normal(loc=drift, scale=vol, size=len(dates))
        cycle = 0.015 * np.sin(np.linspace(0, 8 * np.pi, len(dates)))
        series = base_value * np.exp(np.cumsum(shocks + cycle / 252.0))
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "asset": asset_cfg["asset"],
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "unit": asset_cfg["unit"],
                    "value_nominal": np.round(series, 4),
                }
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def _build_synthetic_cpi(source_cfg: dict[str, Any], end_ts: pd.Timestamp) -> pd.DataFrame:
    start_date = str(source_cfg.get("start_date", "2021-12-01"))
    months = pd.date_range(start_date, end_ts, freq="MS")
    monthly_inflation = 0.055 + 0.01 * np.sin(np.linspace(0, 4 * np.pi, len(months)))
    cpi = [100.0]
    for inflation in monthly_inflation[1:]:
        cpi.append(cpi[-1] * (1.0 + inflation))
    return pd.DataFrame({"date": months, "cpi_index": np.round(cpi, 4)})


def _build_synthetic_fundamentals(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    history_years = int(source_cfg.get("history_years", 6))
    min_year = int(source_cfg.get("min_year", 2018))
    current_year = int(end_ts.year)
    years = range(max(min_year, current_year - history_years), current_year + 1)
    rows: list[dict[str, Any]] = []

    for asset_cfg in assets:
        seed = _stable_seed(f"fundamentals-{asset_cfg['asset']}")
        rng = np.random.default_rng(seed)
        base_value = float(asset_cfg.get("fundamental_base", 100.0))
        level = base_value
        for year in years:
            shock = rng.normal(0.02, 0.03)
            level = max(0.1, level * (1.0 + shock))
            rows.append(
                {
                    "year": year,
                    "asset": asset_cfg["asset"],
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "scope": "Argentina",
                    "metric": asset_cfg.get("fundamental_metric", "macro_proxy"),
                    "metric_label": asset_cfg.get("fundamental_label", "Macro Proxy"),
                    "value": round(level, 2),
                    "source": "SCAFFOLD_PLACEHOLDER",
                }
            )

    return pd.DataFrame(rows, columns=FUNDAMENTALS_COLUMNS)


def _load_csv_prices(source_cfg: dict[str, Any], config_path: Path, end_ts: pd.Timestamp) -> pd.DataFrame:
    path = _resolve_source_path(config_path, source_cfg)
    frame = pd.read_csv(path, parse_dates=["date"])
    return frame[frame["date"] <= end_ts].copy()


def _load_csv_cpi(source_cfg: dict[str, Any], config_path: Path, end_ts: pd.Timestamp) -> pd.DataFrame:
    path = _resolve_source_path(config_path, source_cfg)
    frame = pd.read_csv(path, parse_dates=["date"])
    return frame[frame["date"] <= end_ts].copy()


def _load_csv_fundamentals(source_cfg: dict[str, Any], config_path: Path, end_ts: pd.Timestamp) -> pd.DataFrame:
    path = _resolve_source_path(config_path, source_cfg)
    frame = pd.read_csv(path)
    years = pd.to_numeric(frame["year"], errors="coerce")
    return frame[years <= int(end_ts.year)].copy()


def _build_ambito_chart_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path_raw = source_cfg.get("cache_path")
    if not cache_path_raw:
        raise ValueError(f"Price source '{source_id}' must define 'cache_path'.")

    cache_path = _resolve_config_path(config_path, cache_path_raw)
    base_url = str(source_cfg.get("base_url", "https://mercados.ambito.com"))
    timeout_seconds = int(source_cfg.get("timeout_seconds", 30))
    default_period = str(source_cfg.get("period", "anual")).strip() or "anual"
    fresh_frames: list[pd.DataFrame] = []
    notes: list[str] = []

    try:
        for asset_cfg in assets:
            asset = str(asset_cfg["asset"])
            entry = series_lookup.get(asset)
            if entry is None:
                raise ValueError(f"Price source '{source_id}' is missing an Ámbito chart mapping for asset '{asset}'.")

            chart_path = str(entry.get("chart_path", source_cfg.get("chart_path", ""))).strip()
            if not chart_path:
                raise ValueError(f"Price source '{source_id}' must define 'chart_path' for asset '{asset}'.")

            period = str(entry.get("period", default_period)).strip() or default_period
            history = fetch_ambito_chart_series(
                chart_path=chart_path,
                period=period,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
            if history.empty:
                continue

            fresh = history.copy()
            fresh["asset"] = asset
            fresh["fetched_at"] = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None)
            fresh["source_url"] = f"{base_url.rstrip('/')}/{chart_path.strip('/')}/{period}"
            fresh["source_detail"] = f"ambito:{chart_path}:{period}"
            fresh_frames.append(fresh)

        fresh_rows = (
            pd.concat(fresh_frames, ignore_index=True)
            if fresh_frames
            else pd.DataFrame(columns=["date", "asset", "value_nominal", "fetched_at", "source_url", "source_detail"])
        )
        cache = merge_web_price_cache(cache_path, fresh_rows)
        notes.append(f"Ámbito chart cache updated rows={len(cache)} path={cache_path.as_posix()}")
    except Exception as exc:
        if cache_path.exists():
            cache = load_web_price_cache(cache_path)
            notes.append(f"Ámbito live refresh failed; reused cache at {cache_path.as_posix()}: {exc}")
        else:
            raise

    prices = cache[cache["asset"].isin([str(asset_cfg["asset"]) for asset_cfg in assets])][["date", "asset", "value_nominal"]].copy()
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_fred_graph_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path = _resolve_config_path(config_path, source_cfg.get("cache_path"))
    base_url = str(source_cfg.get("base_url", "https://fred.stlouisfed.org")).strip()
    timeout_seconds = int(source_cfg.get("timeout_seconds", 30))
    default_start_date = source_cfg.get("start_date")
    allow_partial = bool(source_cfg.get("allow_partial", False))
    fallback_payload_path = _resolve_config_path(
        config_path,
        source_cfg.get("fallback_payload_path", "web/data/dashboard_payload.json"),
    )
    notes: list[str] = []
    fresh_frames: list[pd.DataFrame] = []

    for asset_cfg in assets:
        target_asset = str(asset_cfg["asset"])
        entry = series_lookup.get(target_asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing a FRED mapping for asset '{target_asset}'.")

        series_id = str(entry.get("series_id", "")).strip()
        if not series_id:
            raise ValueError(f"Price source '{source_id}' requires 'series_id' for asset '{target_asset}'.")
        series_start_date = entry.get("start_date", default_start_date)

        try:
            series = fetch_fred_graph_series(
                series_id=series_id,
                start_date=series_start_date,
                end_date=end_ts,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            if allow_partial:
                notes.append(f"FRED graph refresh failed for asset={target_asset} series={series_id}: {exc}")
                continue
            raise

        if series.empty:
            notes.append(f"FRED graph returned no rows for asset={target_asset} series={series_id}")
            continue

        fresh_frames.append(
            pd.DataFrame(
                {
                    "date": series["date"],
                    "asset": target_asset,
                    "value_nominal": series["value_nominal"],
                    "source": "FRED",
                    "fetched_at": pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None),
                    "source_url": f"{base_url.rstrip('/')}/graph/fredgraph.csv?id={series_id}",
                    "source_detail": f"fred_graph:{series_id}",
                }
            )
        )

    cache: pd.DataFrame
    if fresh_frames:
        fresh_rows = pd.concat(fresh_frames, ignore_index=True)
        cache = merge_web_price_cache(cache_path, fresh_rows)
        notes.append(f"FRED graph cache updated rows={len(cache)} path={cache_path.as_posix()}")
    elif cache_path.exists():
        cache = load_web_price_cache(cache_path)
        notes.append(f"FRED graph refresh produced no new rows; reused cache at {cache_path.as_posix()}")
    else:
        cache = pd.DataFrame(columns=["date", "asset", "value_nominal", "source", "source_url", "source_detail"])
        notes.append(f"FRED graph refresh produced no rows and cache is missing at {cache_path.as_posix()}")

    requested_assets = {str(asset_cfg["asset"]) for asset_cfg in assets}
    cached_assets = set(cache.get("asset", pd.Series(dtype="object")).astype(str).unique()) if not cache.empty else set()
    missing_assets = sorted(requested_assets - cached_assets)
    if missing_assets:
        fallback_assets = [asset_cfg for asset_cfg in assets if str(asset_cfg["asset"]) in missing_assets]
        fallback = _load_previous_external_payload_prices(
            payload_path=fallback_payload_path,
            assets=fallback_assets,
            series_lookup=series_lookup,
            source_name="FRED",
            source_url_base=base_url,
        )
        if not fallback.empty:
            cache = fallback.copy() if cache.empty else pd.concat([cache, fallback], ignore_index=True)
            restored_assets = sorted(set(fallback["asset"].astype(str).unique()))
            notes.append(
                "FRED graph fallback restored assets from previous payload "
                f"path={fallback_payload_path.as_posix()} assets={','.join(restored_assets)}"
            )
        else:
            notes.append(
                "FRED graph fallback found no previous payload rows "
                f"path={fallback_payload_path.as_posix()} assets={','.join(missing_assets)}"
            )

    prices = cache[cache["asset"].isin([str(asset_cfg["asset"]) for asset_cfg in assets])][["date", "asset", "value_nominal", "source", "source_detail", "source_url"]].copy()
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_yahoo_chart_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path = _resolve_config_path(config_path, source_cfg.get("cache_path"))
    base_url = str(source_cfg.get("base_url", "https://query1.finance.yahoo.com")).strip()
    timeout_seconds = int(source_cfg.get("timeout_seconds", 30))
    default_start_date = source_cfg.get("start_date")
    allow_partial = bool(source_cfg.get("allow_partial", False))
    notes: list[str] = []
    fresh_frames: list[pd.DataFrame] = []

    for asset_cfg in assets:
        target_asset = str(asset_cfg["asset"])
        entry = series_lookup.get(target_asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing a Yahoo mapping for asset '{target_asset}'.")

        symbol = str(entry.get("symbol", "")).strip()
        if not symbol:
            raise ValueError(f"Price source '{source_id}' requires 'symbol' for asset '{target_asset}'.")
        series_start_date = entry.get("start_date", default_start_date)

        try:
            series = fetch_yahoo_chart_series(
                symbol=symbol,
                start_date=series_start_date,
                end_date=end_ts,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            if allow_partial:
                notes.append(f"Yahoo chart refresh failed for asset={target_asset} symbol={symbol}: {exc}")
                continue
            raise

        if series.empty:
            notes.append(f"Yahoo chart returned no rows for asset={target_asset} symbol={symbol}")
            continue

        fresh_frames.append(
            pd.DataFrame(
                {
                    "date": series["date"],
                    "asset": target_asset,
                    "value_nominal": series["value_nominal"],
                    "source": "Yahoo Finance",
                    "fetched_at": pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None),
                    "source_url": f"https://finance.yahoo.com/quote/{symbol}/history",
                    "source_detail": f"yahoo_chart:{symbol}",
                }
            )
        )

    cache: pd.DataFrame
    if fresh_frames:
        fresh_rows = pd.concat(fresh_frames, ignore_index=True)
        cache = merge_web_price_cache(cache_path, fresh_rows)
        notes.append(f"Yahoo chart cache updated rows={len(cache)} path={cache_path.as_posix()}")
    elif cache_path.exists():
        cache = load_web_price_cache(cache_path)
        notes.append(f"Yahoo chart refresh produced no new rows; reused cache at {cache_path.as_posix()}")
    else:
        cache = pd.DataFrame(columns=["date", "asset", "value_nominal", "source", "source_url", "source_detail"])
        notes.append(f"Yahoo chart refresh produced no rows and cache is missing at {cache_path.as_posix()}")

    prices = cache[cache["asset"].isin([str(asset_cfg["asset"]) for asset_cfg in assets])][["date", "asset", "value_nominal", "source", "source_detail", "source_url"]].copy()
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_bondterminal_embi_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path_raw = source_cfg.get("cache_path")
    if not cache_path_raw:
        raise ValueError(f"Price source '{source_id}' must define 'cache_path'.")

    cache_path = _resolve_config_path(config_path, cache_path_raw)
    base_url = str(source_cfg.get("base_url", "https://bondterminal.com"))
    timeout_seconds = int(source_cfg.get("timeout_seconds", 30))
    default_start_date = str(source_cfg.get("start_date", "2022-01-01"))
    fresh_frames: list[pd.DataFrame] = []
    notes: list[str] = []

    try:
        for asset_cfg in assets:
            asset = str(asset_cfg["asset"])
            entry = series_lookup.get(asset)
            if entry is None:
                raise ValueError(f"Price source '{source_id}' is missing a BondTerminal mapping for asset '{asset}'.")

            start_date = entry.get("start_date", default_start_date)
            history = fetch_bondterminal_embi_history(
                start_date=start_date,
                end_date=end_ts,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
            if not history.empty:
                historical_rows = history.copy()
                historical_rows["asset"] = asset
                historical_rows["fetched_at"] = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None)
                historical_rows["source_url"] = f"{base_url.rstrip('/')}/api/riesgo-pais/embi-history"
                historical_rows["source_detail"] = "bondterminal:embi-history"
                fresh_frames.append(historical_rows)

            today_local = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None).normalize()
            if pd.Timestamp(end_ts).normalize() >= today_local:
                value_fields = entry.get("snapshot_value_fields")
                date_fields = entry.get("snapshot_date_fields")
                snapshot = fetch_bondterminal_riesgo_pais_snapshot(
                    base_url=base_url,
                    timeout_seconds=timeout_seconds,
                    value_fields=[str(field) for field in value_fields] if isinstance(value_fields, list) else None,
                    date_fields=[str(field) for field in date_fields] if isinstance(date_fields, list) else None,
                )
                snapshot_date = pd.Timestamp(snapshot["date"]).normalize()
                if snapshot_date <= pd.Timestamp(end_ts).normalize():
                    latest_row = pd.DataFrame(
                        [
                            {
                                "date": snapshot_date,
                                "asset": asset,
                                "value_nominal": float(snapshot["value_nominal"]),
                                "fetched_at": snapshot["fetched_at"],
                                "source_url": snapshot["source_url"],
                                "source_detail": snapshot["source_detail"],
                            }
                        ]
                    )
                    fresh_frames.append(latest_row)

        fresh_rows = (
            pd.concat(fresh_frames, ignore_index=True)
            if fresh_frames
            else pd.DataFrame(columns=["date", "asset", "value_nominal", "fetched_at", "source_url", "source_detail"])
        )
        cache = merge_web_price_cache(cache_path, fresh_rows)
        notes.append(f"BondTerminal EMBI cache updated rows={len(cache)} path={cache_path.as_posix()}")
    except Exception as exc:
        if cache_path.exists():
            cache = load_web_price_cache(cache_path)
            notes.append(f"BondTerminal live refresh failed; reused cache at {cache_path.as_posix()}: {exc}")
        else:
            raise

    prices = cache[cache["asset"].isin([str(asset_cfg["asset"]) for asset_cfg in assets])][["date", "asset", "value_nominal"]].copy()
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_argentinadatos_riesgo_pais_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path_raw = source_cfg.get("cache_path")
    if not cache_path_raw:
        raise ValueError(f"Price source '{source_id}' must define 'cache_path'.")

    cache_path = _resolve_config_path(config_path, cache_path_raw)
    base_url = str(source_cfg.get("base_url", "https://api.argentinadatos.com/v1"))
    timeout_seconds = int(source_cfg.get("timeout_seconds", 30))
    default_start_date = str(source_cfg.get("start_date", "1999-01-22"))
    fresh_frames: list[pd.DataFrame] = []
    notes: list[str] = []

    try:
        for asset_cfg in assets:
            asset = str(asset_cfg["asset"])
            entry = series_lookup.get(asset)
            if entry is None:
                raise ValueError(f"Price source '{source_id}' is missing an ArgentinaDatos mapping for asset '{asset}'.")

            start_date = entry.get("start_date", default_start_date)
            history = fetch_argentinadatos_riesgo_pais_history(
                start_date=start_date,
                end_date=end_ts,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
            if not history.empty:
                historical_rows = history.copy()
                historical_rows["asset"] = asset
                historical_rows["fetched_at"] = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None)
                historical_rows["source_url"] = f"{base_url.rstrip('/')}/finanzas/indices/riesgo-pais"
                historical_rows["source_detail"] = "argentinadatos:historico"
                fresh_frames.append(historical_rows)

            today_local = pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None).normalize()
            if pd.Timestamp(end_ts).normalize() >= today_local:
                snapshot = fetch_argentinadatos_riesgo_pais_snapshot(
                    base_url=base_url,
                    timeout_seconds=timeout_seconds,
                )
                snapshot_date = pd.Timestamp(snapshot["date"]).normalize()
                if snapshot_date <= pd.Timestamp(end_ts).normalize():
                    latest_row = pd.DataFrame(
                        [
                            {
                                "date": snapshot_date,
                                "asset": asset,
                                "value_nominal": float(snapshot["value_nominal"]),
                                "fetched_at": snapshot["fetched_at"],
                                "source_url": snapshot["source_url"],
                                "source_detail": snapshot["source_detail"],
                            }
                        ]
                    )
                    fresh_frames.append(latest_row)

        fresh_rows = (
            pd.concat(fresh_frames, ignore_index=True)
            if fresh_frames
            else pd.DataFrame(columns=["date", "asset", "value_nominal", "fetched_at", "source_url", "source_detail"])
        )
        cache = merge_web_price_cache(cache_path, fresh_rows)
        notes.append(f"ArgentinaDatos riesgo-pais cache updated rows={len(cache)} path={cache_path.as_posix()}")
    except Exception as exc:
        if cache_path.exists():
            cache = load_web_price_cache(cache_path)
            notes.append(f"ArgentinaDatos live refresh failed; reused cache at {cache_path.as_posix()}: {exc}")
        else:
            raise

    prices = cache[cache["asset"].isin([str(asset_cfg["asset"]) for asset_cfg in assets])][["date", "asset", "value_nominal"]].copy()
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_bcra_principales_variables_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    start_date = source_cfg.get("start_date")
    page_size = int(source_cfg.get("page_size", 1000))
    verify_ssl = bool(source_cfg.get("verify_ssl", True))
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    frames: list[pd.DataFrame] = []

    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup.get(asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing a BCRA mapping for asset '{asset}'.")

        series = fetch_principales_variables_series(
            id_variable=int(entry["id_variable"]),
            start_date=entry.get("start_date", start_date),
            end_date=end_ts,
            page_size=page_size,
            verify_ssl=verify_ssl,
        )
        if series.empty:
            continue

        value_scale = float(entry.get("value_scale", 1.0))
        frames.append(
            pd.DataFrame(
                {
                    "date": series["date"],
                    "asset": asset,
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "unit": asset_cfg["unit"],
                    "value_nominal": series["value"] * value_scale,
                }
            )
        )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def _build_bcra_estadisticas_cambiarias_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    start_date = source_cfg.get("start_date")
    page_size = int(source_cfg.get("page_size", 1000))
    verify_ssl = bool(source_cfg.get("verify_ssl", True))
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    frames: list[pd.DataFrame] = []

    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup.get(asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing an FX mapping for asset '{asset}'.")

        series = fetch_estadisticas_cambiarias_series(
            currency_code=str(entry["currency_code"]),
            start_date=entry.get("start_date", start_date),
            end_date=end_ts,
            page_size=page_size,
            verify_ssl=verify_ssl,
        )
        if series.empty:
            continue

        value_field = str(entry.get("value_field", "tipo_cotizacion")).lower()
        if value_field not in {"tipo_cotizacion", "tipo_pase"}:
            raise ValueError(f"Price source '{source_id}' has unsupported FX value_field '{value_field}'.")
        series_value_column = "tipo_cotizacion" if value_field == "tipo_cotizacion" else "tipo_pase"
        value_scale = float(entry.get("value_scale", 1.0))
        frames.append(
            pd.DataFrame(
                {
                    "date": series["date"],
                    "asset": asset,
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "unit": asset_cfg["unit"],
                    "value_nominal": series[series_value_column] * value_scale,
                }
            )
        )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def _build_bcra_cpi_index(source_cfg: dict[str, Any], end_ts: pd.Timestamp) -> pd.DataFrame:
    id_variable = int(source_cfg.get("id_variable", 27))
    start_date = source_cfg.get("start_date", "2021-12-01")
    page_size = int(source_cfg.get("page_size", 1000))
    base_value = float(source_cfg.get("base_value", 100.0))
    verify_ssl = bool(source_cfg.get("verify_ssl", True))

    series = fetch_principales_variables_series(
        id_variable=id_variable,
        start_date=start_date,
        end_date=end_ts,
        page_size=page_size,
        verify_ssl=verify_ssl,
    )
    if series.empty:
        return pd.DataFrame(columns=CPI_COLUMNS)

    monthly = (
        series.assign(date=lambda df: df["date"].dt.to_period("M").dt.to_timestamp())
        .sort_values("date")
        .groupby("date", as_index=False)
        .tail(1)
        .sort_values("date")
        .reset_index(drop=True)
    )
    if monthly.empty:
        return pd.DataFrame(columns=CPI_COLUMNS)

    index_values = [base_value]
    for pct_change in monthly["value"].iloc[1:]:
        index_values.append(index_values[-1] * (1.0 + float(pct_change) / 100.0))

    return pd.DataFrame({"date": monthly["date"], "cpi_index": np.round(index_values, 4)})


def _build_bcra_principales_variables_fundamentals(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    start_date = source_cfg.get("start_date", "2018-01-01")
    page_size = int(source_cfg.get("page_size", 1000))
    verify_ssl = bool(source_cfg.get("verify_ssl", True))
    series_lookup = _get_series_lookup(source_cfg, source_id, "Fundamentals")
    rows: list[dict[str, Any]] = []

    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup.get(asset)
        if entry is None:
            raise ValueError(f"Fundamentals source '{source_id}' is missing a BCRA mapping for asset '{asset}'.")

        series = fetch_principales_variables_series(
            id_variable=int(entry["id_variable"]),
            start_date=entry.get("start_date", start_date),
            end_date=end_ts,
            page_size=page_size,
            verify_ssl=verify_ssl,
        )
        if series.empty:
            continue

        annual = (
            series.sort_values("date")
            .assign(year=lambda df: df["date"].dt.year)
            .groupby("year", as_index=False)
            .tail(1)
            .sort_values("year")
        )
        value_scale = float(entry.get("value_scale", 1.0))
        for row in annual.itertuples(index=False):
            rows.append(
                {
                    "year": int(row.year),
                    "asset": asset,
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "scope": entry.get("scope", "Argentina"),
                    "metric": asset_cfg.get("fundamental_metric", "macro_proxy"),
                    "metric_label": asset_cfg.get("fundamental_label", "Macro Proxy"),
                    "value": round(float(row.value) * value_scale, 4),
                    "source": entry.get("source", "BCRA_PRINCIPALES_VARIABLES"),
                }
            )

    return pd.DataFrame(rows, columns=FUNDAMENTALS_COLUMNS)


def _build_iol_zero_coupon_roll_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    path = _resolve_source_path(config_path, source_cfg)
    metrics = load_iol_zero_coupon_metrics(path)
    metrics = metrics[metrics["date"] <= end_ts].copy()
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    frames: list[pd.DataFrame] = []

    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup.get(asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing an IOL roll mapping for asset '{asset}'.")

        selected = select_target_maturity_metrics(
            metrics=metrics,
            instrument_families=entry.get("instrument_families", []),
            target_days_360=int(entry.get("target_days_360", 90)),
            metric_column=str(entry.get("metric_column", "tea")),
            min_days_360=int(entry["min_days_360"]) if entry.get("min_days_360") is not None else None,
            max_days_360=int(entry["max_days_360"]) if entry.get("max_days_360") is not None else None,
            min_volume=float(entry.get("min_volume", 0.0)),
        )
        if selected.empty:
            continue

        value_column = str(entry.get("metric_column", "tea"))
        value_scale = float(entry.get("value_scale", 1.0))
        frames.append(
            pd.DataFrame(
                {
                    "date": selected["date"],
                    "asset": asset,
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "unit": asset_cfg["unit"],
                    "value_nominal": pd.to_numeric(selected[value_column], errors="coerce") * value_scale,
                }
            )
        )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def _build_cer_breakeven_roll_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    fixed_metrics_path = _resolve_config_path(config_path, source_cfg.get("fixed_metrics_path", "data/processed/iol_zero_coupon_metrics.csv"))
    cer_price_history_path = _resolve_config_path(config_path, source_cfg.get("cer_price_history_path", "data/raw/cer_bond_prices_history.csv"))
    cer_index_path = _resolve_config_path(config_path, source_cfg.get("cer_index_path", "data/raw/bcra_cer_index_daily.csv"))

    fixed_metrics = load_iol_zero_coupon_metrics(fixed_metrics_path)
    fixed_metrics = fixed_metrics[fixed_metrics["date"] <= end_ts].copy()
    cer_price_history = load_cer_price_history(cer_price_history_path)
    cer_price_history = cer_price_history[cer_price_history["date"] <= end_ts].copy()
    cer_index_history = load_cer_index_history(cer_index_path)
    cer_index_cutoff = cer_publication_window_end(end_ts)
    cer_index_history = cer_index_history[cer_index_history["date"] <= cer_index_cutoff].copy()

    breakeven_history, _ = build_breakeven_monitor_live(
        fixed_metrics=fixed_metrics,
        cer_price_history=cer_price_history,
        cer_index_history=cer_index_history,
    )
    if breakeven_history.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    frames: list[pd.DataFrame] = []
    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup.get(asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing a CER breakeven mapping for asset '{asset}'.")

        selected = select_target_breakeven_metrics(
            history=breakeven_history,
            target_horizon_days=int(entry.get("target_horizon_days", 365)),
            metric_column=str(entry.get("metric_column", "breakeven_annual_equivalent")),
            min_horizon_days=int(entry["min_horizon_days"]) if entry.get("min_horizon_days") is not None else None,
            max_horizon_days=int(entry["max_horizon_days"]) if entry.get("max_horizon_days") is not None else None,
        )
        if selected.empty:
            continue

        value_column = str(entry.get("metric_column", "breakeven_annual_equivalent"))
        value_scale = float(entry.get("value_scale", 1.0))
        frames.append(
            pd.DataFrame(
                {
                    "date": selected["date"],
                    "asset": asset,
                    "asset_label": asset_cfg["label"],
                    "category": asset_cfg["category"],
                    "unit": asset_cfg["unit"],
                    "value_nominal": pd.to_numeric(selected[value_column], errors="coerce") * value_scale,
                }
            )
        )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def _build_iol_symbol_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path_raw = source_cfg.get("cache_path")
    if not cache_path_raw:
        raise ValueError(f"Price source '{source_id}' must define 'cache_path'.")

    cache_path = _resolve_config_path(config_path, cache_path_raw)
    default_market = str(source_cfg.get("market", "BCBA")).strip().upper() or "BCBA"
    headless = bool(source_cfg.get("headless", True))
    timeout_seconds = int(source_cfg.get("timeout_seconds", 20))
    page_size = int(source_cfg.get("page_size", 200))
    include_quote_overlay = bool(source_cfg.get("quote_overlay", False))
    quote_timeout_seconds = int(source_cfg.get("quote_timeout_seconds", 30))

    symbols_by_market: dict[str, list[str]] = {}
    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup.get(asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing an IOL symbol mapping for asset '{asset}'.")

        symbol = str(entry.get("symbol", "")).strip().upper()
        market = str(entry.get("market", default_market)).strip().upper() or default_market
        if not symbol:
            raise ValueError(f"Price source '{source_id}' must define 'symbol' for asset '{asset}'.")
        symbols_by_market.setdefault(market, [])
        if symbol not in symbols_by_market[market]:
            symbols_by_market[market].append(symbol)

    notes: list[str] = []
    try:
        for market, symbols in sorted(symbols_by_market.items()):
            cache = update_iol_market_price_cache(
                path=cache_path,
                symbols=symbols,
                market=market,
                headless=headless,
                timeout_seconds=timeout_seconds,
                page_size=page_size,
                include_quote_overlay=include_quote_overlay,
                quote_timeout_seconds=quote_timeout_seconds,
            )
            notes.append(
                "IOL history cache updated "
                f"market={market} symbols={','.join(symbols)} rows={len(cache)} path={cache_path.as_posix()}"
            )
            if include_quote_overlay:
                notes.append(
                    "IOL quote-page overlay enabled "
                    f"market={market} symbols={','.join(symbols)} timeout={quote_timeout_seconds}s"
                )
    except Exception as exc:
        if cache_path.exists():
            notes.append(f"IOL live refresh failed; reused history cache at {cache_path.as_posix()}: {exc}")
        else:
            raise

    history = load_iol_market_price_history(cache_path)
    if history.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS), notes

    history = history[history["date"] <= end_ts].copy()
    frames: list[pd.DataFrame] = []
    for asset_cfg in assets:
        asset = str(asset_cfg["asset"])
        entry = series_lookup[asset]
        symbol = str(entry.get("symbol", "")).strip().upper()
        market = str(entry.get("market", default_market)).strip().upper() or default_market
        field = str(entry.get("field", source_cfg.get("field", "price"))).strip()
        if field not in history.columns:
            raise ValueError(f"Price source '{source_id}' requested unsupported IOL field '{field}'.")

        value_scale = float(entry.get("value_scale", source_cfg.get("value_scale", 1.0)))
        asset_history = history[(history["symbol"] == symbol) & (history["market"] == market)].copy()
        if asset_history.empty:
            continue

        frame = pd.DataFrame(
            {
                "date": asset_history["date"],
                "asset": asset,
                "value_nominal": pd.to_numeric(asset_history[field], errors="coerce") * value_scale,
            }
        )
        frame = frame.dropna(subset=["value_nominal"]).copy()
        frames.append(frame)

    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_byma_browser_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    asset_ids = [str(asset_cfg["asset"]) for asset_cfg in assets]
    required_endpoints = {str(series_lookup[asset]["endpoint"]).strip() for asset in asset_ids}

    quote_cache_raw_path = source_cfg.get("quote_cache_path") or source_cfg.get("cache_path")
    if not quote_cache_raw_path:
        raise ValueError(f"Price source '{source_id}' must define 'quote_cache_path' or 'cache_path'.")
    quote_cache_path = _resolve_config_path(config_path, quote_cache_raw_path)

    snapshot_path_raw = source_cfg.get("snapshot_path")
    snapshot_path = _resolve_config_path(config_path, snapshot_path_raw) if snapshot_path_raw else None

    notes: list[str] = []
    quotes = pd.DataFrame()
    try:
        snapshot = fetch_dashboard_snapshot(
            required_endpoints=required_endpoints,
            wait_seconds=float(source_cfg.get("wait_seconds", 8.0)),
            poll_attempts=int(source_cfg.get("poll_attempts", 3)),
            poll_wait_seconds=float(source_cfg.get("poll_wait_seconds", 2.0)),
        )
        if snapshot_path is not None:
            save_snapshot(snapshot_path, snapshot)
        quotes = extract_quotes_from_snapshot(
            snapshot=snapshot,
            series_lookup={asset: series_lookup[asset] for asset in asset_ids},
        )
        quotes = merge_quote_cache(quote_cache_path, quotes)
        notes.append(
            f"BYMA live snapshot fetched market_date={snapshot['market_date']} endpoints={','.join(sorted(required_endpoints))}"
        )
        notes.append(f"BYMA quote cache updated rows={len(quotes)} path={quote_cache_path.as_posix()}")
    except Exception as exc:
        if quote_cache_path.exists():
            quotes = load_quote_cache(quote_cache_path)
            notes.append(f"BYMA live refresh failed; reused quote cache at {quote_cache_path.as_posix()}: {exc}")
        else:
            raise

    if quotes.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS), notes

    prices = quotes[quotes["asset"].isin(asset_ids)][["date", "asset", "value_nominal"]].copy()
    prices = prices[prices["date"] <= end_ts].reset_index(drop=True)
    return prices, notes


def _build_byma_direct_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    asset_ids = [str(asset_cfg["asset"]) for asset_cfg in assets]
    required_endpoints = sorted({str(series_lookup[asset]["endpoint"]).strip() for asset in asset_ids})

    quote_cache_raw_path = source_cfg.get("quote_cache_path") or source_cfg.get("cache_path")
    if not quote_cache_raw_path:
        raise ValueError(f"Price source '{source_id}' must define 'quote_cache_path' or 'cache_path'.")
    quote_cache_path = _resolve_config_path(config_path, quote_cache_raw_path)

    endpoint_payloads = dict(source_cfg.get("endpoint_payloads", {}))
    timeout_seconds = float(source_cfg.get("timeout_seconds", 30.0))
    verify_ssl = bool(source_cfg.get("verify_ssl", False))
    options = str(source_cfg.get("options", "renta-fija"))
    notes: list[str] = []
    quotes = pd.DataFrame()

    try:
        record_lookup: dict[str, dict[str, dict[str, Any]]] = {}
        for endpoint in required_endpoints:
            payload = endpoint_payloads.get(endpoint, {"page_number": 1})
            records = _fetch_paginated_direct_records(
                endpoint=endpoint,
                payload=payload,
                timeout_seconds=timeout_seconds,
                verify_ssl=verify_ssl,
                options=options,
            )
            endpoint_records: dict[str, dict[str, Any]] = {}
            for record in records:
                symbol = str(record.get("symbol", "")).strip()
                if symbol:
                    endpoint_records[symbol] = record
            record_lookup[endpoint] = endpoint_records

        market_date = pd.Timestamp(end_ts).normalize()
        fetched_at = pd.Timestamp.now(tz="America/Buenos_Aires").isoformat()
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

            record = record_lookup.get(endpoint, {}).get(symbol)
            if record is None:
                raise ValueError(f"BYMA direct endpoint '{endpoint}' did not return symbol '{symbol}' for asset '{asset}'.")

            value, value_field_used = _extract_numeric_from_fields(
                record,
                [field, *fallback_fields],
                treat_zero_as_missing=treat_zero_as_missing,
            )
            if value is None:
                raise ValueError(
                    f"BYMA direct symbol '{symbol}' from endpoint '{endpoint}' is missing numeric fields "
                    f"'{', '.join([field, *fallback_fields])}' for asset '{asset}'."
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

        quotes = pd.DataFrame(rows, columns=QUOTE_COLUMNS)
        quotes = merge_quote_cache(quote_cache_path, quotes)
        notes.append(f"BYMA direct fetch endpoints={','.join(required_endpoints)} rows={len(quotes)} path={quote_cache_path.as_posix()}")
    except Exception as exc:
        if quote_cache_path.exists():
            quotes = load_quote_cache(quote_cache_path)
            notes.append(f"BYMA direct refresh failed; reused quote cache at {quote_cache_path.as_posix()}: {exc}")
        else:
            raise

    if quotes.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS), notes

    prices = quotes[quotes["asset"].isin(asset_ids)][["date", "asset", "value_nominal"]].copy()
    prices = prices[prices["date"] <= end_ts].reset_index(drop=True)
    return prices, notes


def _build_byma_chart_index_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    cache_path_raw = source_cfg.get("cache_path")
    if not cache_path_raw:
        raise ValueError(f"Price source '{source_id}' must define 'cache_path'.")

    cache_path = _resolve_config_path(config_path, cache_path_raw)
    timeout_seconds = float(source_cfg.get("timeout_seconds", 30.0))
    verify_ssl = bool(source_cfg.get("verify_ssl", False))
    default_start_date = source_cfg.get("start_date", "2024-04-01")
    notes: list[str] = []
    fresh_frames: list[pd.DataFrame] = []

    try:
        for asset_cfg in assets:
            asset = str(asset_cfg["asset"])
            entry = series_lookup.get(asset)
            if entry is None:
                raise ValueError(f"Price source '{source_id}' is missing a BYMA chart mapping for asset '{asset}'.")

            symbol = str(entry.get("symbol", "")).strip().upper()
            if not symbol:
                raise ValueError(f"Price source '{source_id}' must define 'symbol' for asset '{asset}'.")

            history = fetch_index_historical_series(
                symbol=symbol,
                start_date=entry.get("start_date", default_start_date),
                end_date=end_ts,
                resolution=str(entry.get("resolution", source_cfg.get("resolution", "D"))),
                timeout_seconds=timeout_seconds,
                verify_ssl=verify_ssl,
            )
            if history.empty:
                continue

            fresh_frames.append(
                pd.DataFrame(
                    {
                        "date": history["date"],
                        "asset": asset,
                        "value_nominal": history["price"],
                        "fetched_at": pd.Timestamp.now(tz="America/Buenos_Aires").tz_localize(None),
                        "source_url": history["source_url"],
                        "source_detail": history["source"],
                    }
                )
            )

        fresh_rows = (
            pd.concat(fresh_frames, ignore_index=True)
            if fresh_frames
            else pd.DataFrame(columns=["date", "asset", "value_nominal", "fetched_at", "source_url", "source_detail"])
        )
        cache = merge_web_price_cache(cache_path, fresh_rows)
        notes.append(f"BYMA chart index cache updated rows={len(cache)} path={cache_path.as_posix()}")
    except Exception as exc:
        if cache_path.exists():
            cache = load_web_price_cache(cache_path)
            notes.append(f"BYMA chart index refresh failed; reused cache at {cache_path.as_posix()}: {exc}")
        else:
            raise

    prices = cache[cache["asset"].isin([str(asset_cfg["asset"]) for asset_cfg in assets])][["date", "asset", "value_nominal"]].copy()
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _merge_price_frames_by_priority(
    primary_frame: pd.DataFrame,
    secondary_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    if primary_frame.empty and secondary_frame.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS), 0, 0
    if primary_frame.empty:
        overlay = secondary_frame.copy()
        return overlay[PRICE_COLUMNS].sort_values(["category", "asset_label", "date"]).reset_index(drop=True), len(overlay), int(
            overlay["asset"].nunique()
        )
    if secondary_frame.empty:
        return primary_frame[PRICE_COLUMNS].sort_values(["category", "asset_label", "date"]).reset_index(drop=True), 0, 0

    primary = primary_frame.copy()
    secondary = secondary_frame.copy()
    primary["date"] = pd.to_datetime(primary["date"], errors="coerce").dt.normalize()
    secondary["date"] = pd.to_datetime(secondary["date"], errors="coerce").dt.normalize()

    primary_last_dates = (
        primary.groupby("asset", as_index=False)["date"]
        .max()
        .rename(columns={"date": "primary_last_date"})
    )
    overlay = secondary.merge(primary_last_dates, on="asset", how="left")
    overlay = overlay[(overlay["primary_last_date"].isna()) | (overlay["date"] > overlay["primary_last_date"])].copy()
    overlay = overlay.drop(columns=["primary_last_date"])

    combined = pd.concat([primary, overlay], ignore_index=True)
    combined = (
        combined.sort_values(["asset", "date"])
        .drop_duplicates(["date", "asset"], keep="last")
        .sort_values(["category", "asset_label", "date"])
        .reset_index(drop=True)
    )
    return combined[PRICE_COLUMNS].copy(), len(overlay), int(overlay["asset"].nunique())


def _build_merged_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    source_defs: dict[str, dict[str, Any]],
    config_path: Path,
    end_ts: pd.Timestamp,
    build_stack: tuple[str, ...],
    all_assets: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    primary_source_id = str(source_cfg.get("primary_source", "")).strip()
    secondary_source_id = str(source_cfg.get("secondary_source", "")).strip()
    if not primary_source_id or not secondary_source_id:
        raise ValueError(f"Price source '{source_id}' must define 'primary_source' and 'secondary_source'.")
    if primary_source_id == secondary_source_id:
        raise ValueError(f"Price source '{source_id}' cannot reuse the same source for primary and secondary merge inputs.")

    primary_frame, primary_notes = _build_price_source(
        source_id=primary_source_id,
        source_assets=assets,
        source_defs=source_defs,
        config_path=config_path,
        end_ts=end_ts,
        build_stack=build_stack,
        all_assets=all_assets,
    )
    secondary_frame, secondary_notes = _build_price_source(
        source_id=secondary_source_id,
        source_assets=assets,
        source_defs=source_defs,
        config_path=config_path,
        end_ts=end_ts,
        build_stack=build_stack,
        all_assets=all_assets,
    )

    merged, overlay_rows, overlay_assets = _merge_price_frames_by_priority(primary_frame, secondary_frame)
    notes = [f"merge[{source_id}] primary={primary_source_id} secondary={secondary_source_id} overlay_rows={overlay_rows} overlay_assets={overlay_assets}"]
    notes.extend(primary_notes)
    notes.extend(secondary_notes)
    return merged, notes


def _build_derived_ratio_prices(
    assets: list[dict[str, Any]],
    source_cfg: dict[str, Any],
    source_id: str,
    source_defs: dict[str, dict[str, Any]],
    config_path: Path,
    end_ts: pd.Timestamp,
    build_stack: tuple[str, ...],
    all_assets: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    series_lookup = _get_series_lookup(source_cfg, source_id, "Price")
    asset_lookup = {str(asset_cfg["asset"]): asset_cfg for asset_cfg in all_assets}
    notes: list[str] = []
    frames: list[pd.DataFrame] = []

    for asset_cfg in assets:
        target_asset = str(asset_cfg["asset"])
        entry = series_lookup.get(target_asset)
        if entry is None:
            raise ValueError(f"Price source '{source_id}' is missing a derived ratio mapping for asset '{target_asset}'.")

        numerator_asset = str(entry.get("numerator_asset", "")).strip()
        denominator_asset = str(entry.get("denominator_asset", "")).strip()
        numerator_source = str(entry.get("numerator_source", "")).strip()
        denominator_source = str(entry.get("denominator_source", "")).strip()
        operation = str(entry.get("operation", "divide")).strip().lower()
        value_scale = float(entry.get("value_scale", 1.0))

        if operation != "divide":
            raise ValueError(f"Price source '{source_id}' only supports operation='divide'.")
        if not numerator_asset or not denominator_asset or not numerator_source or not denominator_source:
            raise ValueError(
                f"Price source '{source_id}' requires numerator and denominator assets and sources for asset '{target_asset}'."
            )
        if numerator_asset not in asset_lookup or denominator_asset not in asset_lookup:
            raise ValueError(
                f"Price source '{source_id}' references unknown numerator or denominator assets for '{target_asset}'."
            )

        numerator_frame, numerator_notes = _build_price_source(
            source_id=numerator_source,
            source_assets=[asset_lookup[numerator_asset]],
            source_defs=source_defs,
            config_path=config_path,
            end_ts=end_ts,
            build_stack=build_stack,
            all_assets=all_assets,
        )
        denominator_frame, denominator_notes = _build_price_source(
            source_id=denominator_source,
            source_assets=[asset_lookup[denominator_asset]],
            source_defs=source_defs,
            config_path=config_path,
            end_ts=end_ts,
            build_stack=build_stack,
            all_assets=all_assets,
        )

        numerator_series = (
            numerator_frame[numerator_frame["asset"] == numerator_asset][["date", "value_nominal"]]
            .rename(columns={"value_nominal": "numerator_value"})
            .sort_values("date")
        )
        denominator_series = (
            denominator_frame[denominator_frame["asset"] == denominator_asset][["date", "value_nominal"]]
            .rename(columns={"value_nominal": "denominator_value"})
            .sort_values("date")
        )
        if numerator_series.empty or denominator_series.empty:
            continue

        derived = pd.merge_asof(
            numerator_series,
            denominator_series,
            on="date",
            direction="backward",
            allow_exact_matches=True,
        )
        derived["numerator_value"] = pd.to_numeric(derived["numerator_value"], errors="coerce")
        derived["denominator_value"] = pd.to_numeric(derived["denominator_value"], errors="coerce")
        derived = derived[derived["numerator_value"].notna() & derived["denominator_value"].notna()].copy()
        derived = derived[~np.isclose(derived["denominator_value"], 0.0)].copy()
        if derived.empty:
            continue

        frames.append(
            pd.DataFrame(
                {
                    "date": derived["date"],
                    "asset": target_asset,
                    "value_nominal": (derived["numerator_value"] / derived["denominator_value"]) * value_scale,
                }
            )
        )
        notes.append(
            "derived_ratio[{}] asset={} numerator={}/{} denominator={}/{} rows={}".format(
                source_id,
                target_asset,
                numerator_source,
                numerator_asset,
                denominator_source,
                denominator_asset,
                len(derived),
            )
        )
        notes.extend(numerator_notes)
        notes.extend(denominator_notes)

    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
    return prices[prices["date"] <= end_ts].reset_index(drop=True), notes


def _build_price_source(
    source_id: str,
    source_assets: list[dict[str, Any]],
    source_defs: dict[str, dict[str, Any]],
    config_path: Path,
    end_ts: pd.Timestamp,
    build_stack: tuple[str, ...] = (),
    all_assets: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    if source_id in build_stack:
        cycle = " -> ".join([*build_stack, source_id])
        raise ValueError(f"Cyclic merged price source dependency detected: {cycle}")

    source_cfg = source_defs.get(source_id)
    if source_cfg is None:
        raise ValueError(f"Unknown price source '{source_id}'.")

    kind = str(source_cfg.get("kind", "")).strip()
    source_notes: list[str] = []
    next_stack = (*build_stack, source_id)
    all_assets = all_assets or source_assets
    if kind == "synthetic_prices":
        frame = _build_synthetic_prices(source_assets, source_cfg, end_ts)
    elif kind == "csv_prices":
        frame = _load_csv_prices(source_cfg, config_path, end_ts)
    elif kind == "bcra_principales_variables_prices":
        frame = _build_bcra_principales_variables_prices(source_assets, source_cfg, source_id, end_ts)
    elif kind == "bcra_estadisticas_cambiarias_prices":
        frame = _build_bcra_estadisticas_cambiarias_prices(source_assets, source_cfg, source_id, end_ts)
    elif kind == "ambito_chart_prices":
        frame, source_notes = _build_ambito_chart_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "fred_graph_prices":
        frame, source_notes = _build_fred_graph_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "yahoo_chart_prices":
        frame, source_notes = _build_yahoo_chart_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "iol_zero_coupon_roll_prices":
        frame = _build_iol_zero_coupon_roll_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "cer_breakeven_roll_prices":
        frame = _build_cer_breakeven_roll_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "iol_symbol_prices":
        frame, source_notes = _build_iol_symbol_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "byma_browser_prices":
        frame, source_notes = _build_byma_browser_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "byma_direct_prices":
        frame, source_notes = _build_byma_direct_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "byma_chart_index_prices":
        frame, source_notes = _build_byma_chart_index_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "bondterminal_embi_prices":
        frame, source_notes = _build_bondterminal_embi_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "argentinadatos_riesgo_pais_prices":
        frame, source_notes = _build_argentinadatos_riesgo_pais_prices(source_assets, source_cfg, source_id, config_path, end_ts)
    elif kind == "merged_prices":
        frame, source_notes = _build_merged_prices(
            assets=source_assets,
            source_cfg=source_cfg,
            source_id=source_id,
            source_defs=source_defs,
            config_path=config_path,
            end_ts=end_ts,
            build_stack=next_stack,
            all_assets=all_assets,
        )
    elif kind == "derived_ratio_prices":
        frame, source_notes = _build_derived_ratio_prices(
            assets=source_assets,
            source_cfg=source_cfg,
            source_id=source_id,
            source_defs=source_defs,
            config_path=config_path,
            end_ts=end_ts,
            build_stack=next_stack,
            all_assets=all_assets,
        )
    else:
        raise ValueError(f"Unsupported price source kind '{kind}' for source '{source_id}'.")

    normalized, normalize_notes = _normalize_prices_frame(
        frame=frame,
        assets=source_assets,
        source_id=source_id,
        allow_partial=bool(source_cfg.get("allow_partial", False)),
    )
    notes = [f"prices[{source_id}] kind={kind} assets={len(source_assets)} rows={len(normalized)}"]
    notes.extend(source_notes)
    notes.extend(normalize_notes)
    return normalized, notes


def build_prices(
    config: dict[str, Any],
    assets: list[dict[str, Any]],
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    source_defs = _get_source_defs(config)
    defaults = _get_defaults(config)
    groups: dict[str, list[dict[str, Any]]] = {}
    for asset_cfg in assets:
        source_id = str(asset_cfg.get("price_source") or defaults["price_source"])
        groups.setdefault(source_id, []).append(asset_cfg)

    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    for source_id, source_assets in groups.items():
        normalized, source_notes = _build_price_source(
            source_id=source_id,
            source_assets=source_assets,
            source_defs=source_defs,
            config_path=config_path,
            end_ts=end_ts,
            all_assets=assets,
        )
        frames.append(normalized)
        notes.extend(source_notes)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
    _validate_duplicate_keys(combined, ["date", "asset"], "Combined price frame")
    return combined.sort_values(["category", "asset_label", "date"]).reset_index(drop=True), notes


def build_cpi(config: dict[str, Any], config_path: Path, end_ts: pd.Timestamp) -> tuple[pd.DataFrame, list[str]]:
    source_defs = _get_source_defs(config)
    defaults = _get_defaults(config)
    source_id = str(dict(config.get("project", {})).get("cpi_source") or defaults["cpi_source"])
    source_cfg = source_defs.get(source_id)
    if source_cfg is None:
        raise ValueError(f"Unknown CPI source '{source_id}'.")

    kind = str(source_cfg.get("kind", "")).strip()
    if kind == "synthetic_cpi":
        frame = _build_synthetic_cpi(source_cfg, end_ts)
    elif kind == "csv_cpi":
        frame = _load_csv_cpi(source_cfg, config_path, end_ts)
    elif kind == "bcra_cpi_index":
        frame = _build_bcra_cpi_index(source_cfg, end_ts)
    else:
        raise ValueError(f"Unsupported CPI source kind '{kind}' for source '{source_id}'.")

    normalized = _normalize_cpi_frame(frame, source_id)
    return normalized, [f"cpi[{source_id}] kind={kind} rows={len(normalized)}"]


def build_fundamentals(
    config: dict[str, Any],
    assets: list[dict[str, Any]],
    config_path: Path,
    end_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    source_defs = _get_source_defs(config)
    defaults = _get_defaults(config)
    groups: dict[str, list[dict[str, Any]]] = {}
    for asset_cfg in assets:
        source_id = str(asset_cfg.get("fundamentals_source") or defaults["fundamentals_source"])
        groups.setdefault(source_id, []).append(asset_cfg)

    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    for source_id, source_assets in groups.items():
        source_cfg = source_defs.get(source_id)
        if source_cfg is None:
            raise ValueError(f"Unknown fundamentals source '{source_id}'.")

        kind = str(source_cfg.get("kind", "")).strip()
        if kind == "synthetic_fundamentals":
            frame = _build_synthetic_fundamentals(source_assets, source_cfg, end_ts)
        elif kind == "csv_fundamentals":
            frame = _load_csv_fundamentals(source_cfg, config_path, end_ts)
        elif kind == "bcra_principales_variables_fundamentals":
            frame = _build_bcra_principales_variables_fundamentals(source_assets, source_cfg, source_id, end_ts)
        else:
            raise ValueError(f"Unsupported fundamentals source kind '{kind}' for source '{source_id}'.")

        normalized, source_notes = _normalize_fundamentals_frame(
            frame=frame,
            assets=source_assets,
            source_id=source_id,
            allow_partial=bool(source_cfg.get("allow_partial", False)),
        )
        frames.append(normalized)
        notes.append(f"fundamentals[{source_id}] kind={kind} assets={len(source_assets)} rows={len(normalized)}")
        notes.extend(source_notes)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
    _validate_duplicate_keys(combined, ["year", "asset", "metric"], "Combined fundamentals frame")
    return combined.sort_values(["category", "asset_label", "year", "metric"]).reset_index(drop=True), notes
