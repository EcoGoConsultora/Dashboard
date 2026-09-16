from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, closed_dates, load_market_calendar
from src.common.hard_dollar_curve import _prepare_schedule


HARD_DOLLAR_WEIGHTED_PARITY_COLUMNS = [
    "date",
    "family",
    "weighted_parity",
    "total_outstanding",
    "bond_count",
]
HARD_DOLLAR_WEIGHTED_PARITY_LATEST_COLUMNS = [
    "family",
    "date",
    "weighted_parity",
    "total_outstanding",
    "bond_count",
]

# Eco Go weighted-parity methodology replicated with current scraped D prices.
# Family weights are explicit and adjusted forward by each bond's effective
# amortization schedule. The newer AO27D/AN29D are now included to extend the
# current desk monitor even though they were not present in the older notebook.
WEIGHTED_FAMILY_SYMBOLS = {
    "AL": ["AL29D", "AN29D", "AL30D", "AO27D", "AL35D", "AE38D", "AL41D"],
    "GD": ["GD29D", "GD30D", "GD35D", "GD38D", "GD41D", "GD46D"],
}
WEIGHTED_BASE_ISSUED_AMOUNTS = {
    "AL29D": 2196.0,
    "AN29D": 1000.0,
    "AL30D": 13581.0,
    "AO27D": 500.0,
    "AL35D": 19077.0,
    "AE38D": 7254.0,
    "AL41D": 1542.0,
    "GD29D": 2635.0,
    "GD30D": 16091.0,
    "GD35D": 20502.0,
    "GD38D": 11405.0,
    "GD41D": 10482.0,
    "GD46D": 2092.0,
}


def build_weighted_parity_history(
    hard_dollar_history_path: Path | str,
    reference_flow_path: Path | str,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    history = _load_curve_history(hard_dollar_history_path)
    reference_flow = _load_reference_flow(reference_flow_path)
    return build_weighted_parity_history_from_frames(
        history=history,
        reference_flow=reference_flow,
        calendar_path=calendar_path,
    )


def build_weighted_parity_history_from_frames(
    history: pd.DataFrame,
    reference_flow: pd.DataFrame,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if history.empty or reference_flow.empty:
        empty_history = pd.DataFrame(columns=HARD_DOLLAR_WEIGHTED_PARITY_COLUMNS)
        empty_latest = pd.DataFrame(columns=HARD_DOLLAR_WEIGHTED_PARITY_LATEST_COLUMNS)
        return empty_history.copy(), empty_latest.copy()

    history = history[history["symbol"].isin(WEIGHTED_BASE_ISSUED_AMOUNTS)].copy()
    if history.empty:
        empty_history = pd.DataFrame(columns=HARD_DOLLAR_WEIGHTED_PARITY_COLUMNS)
        empty_latest = pd.DataFrame(columns=HARD_DOLLAR_WEIGHTED_PARITY_LATEST_COLUMNS)
        return empty_history.copy(), empty_latest.copy()

    market_calendar = load_market_calendar(calendar_path)
    settlement_closed = closed_dates(market_calendar, mode="settlement")

    symbol_frames: list[pd.DataFrame] = []
    for symbol, base_amount in WEIGHTED_BASE_ISSUED_AMOUNTS.items():
        symbol_history = history[history["symbol"] == symbol].copy()
        if symbol_history.empty:
            continue
        symbol_flows = reference_flow[reference_flow["symbol"] == symbol].copy()
        if symbol_flows.empty:
            continue
        schedule = _prepare_schedule(symbol_flows, settlement_closed)
        if schedule.empty:
            continue

        residuals = (
            schedule[["payment_date", "residual_after_pct"]]
            .rename(columns={"payment_date": "effective_date"})
            .sort_values("effective_date")
            .copy()
        )
        residuals["effective_date"] = pd.to_datetime(residuals["effective_date"], errors="coerce").dt.normalize()
        residuals["residual_after_pct"] = pd.to_numeric(residuals["residual_after_pct"], errors="coerce")
        residuals = residuals.dropna(subset=["effective_date", "residual_after_pct"])
        symbol_history = symbol_history.sort_values("date").copy()
        merged = pd.merge_asof(
            symbol_history,
            residuals,
            left_on="date",
            right_on="effective_date",
            direction="backward",
        )
        merged["residual_live_pct"] = pd.to_numeric(merged["residual_after_pct"], errors="coerce").fillna(100.0)
        merged["base_issued_amount"] = base_amount
        merged["outstanding_weight"] = merged["base_issued_amount"] * merged["residual_live_pct"] / 100.0
        symbol_frames.append(merged)

    weighted_source = pd.concat(symbol_frames, ignore_index=True) if symbol_frames else pd.DataFrame()
    if weighted_source.empty:
        empty_history = pd.DataFrame(columns=HARD_DOLLAR_WEIGHTED_PARITY_COLUMNS)
        empty_latest = pd.DataFrame(columns=HARD_DOLLAR_WEIGHTED_PARITY_LATEST_COLUMNS)
        return empty_history.copy(), empty_latest.copy()

    weighted_source["weighted_parity_component"] = weighted_source["parity"] * weighted_source["outstanding_weight"]
    weighted_source["family"] = weighted_source["symbol"].map(_symbol_family)
    weighted_source = weighted_source.dropna(subset=["family", "date", "parity", "outstanding_weight"]).copy()
    weighted_source = weighted_source[weighted_source["outstanding_weight"] > 0].copy()

    grouped = (
        weighted_source.groupby(["date", "family"], as_index=False)
        .agg(
            weighted_component=("weighted_parity_component", "sum"),
            total_outstanding=("outstanding_weight", "sum"),
            bond_count=("symbol", "nunique"),
        )
    )
    grouped["weighted_parity"] = grouped["weighted_component"] / grouped["total_outstanding"]
    grouped = grouped.drop(columns=["weighted_component"]).sort_values(["date", "family"]).reset_index(drop=True)
    history_out = grouped[HARD_DOLLAR_WEIGHTED_PARITY_COLUMNS].copy()
    latest_out = (
        history_out.sort_values("date")
        .groupby("family", as_index=False)
        .tail(1)
        .sort_values("family")
        .reset_index(drop=True)
    )
    latest_out = latest_out[HARD_DOLLAR_WEIGHTED_PARITY_LATEST_COLUMNS].copy()
    return history_out, latest_out


def _symbol_family(symbol: str) -> str | None:
    symbol_upper = str(symbol).upper()
    for family, symbols in WEIGHTED_FAMILY_SYMBOLS.items():
        if symbol_upper in symbols:
            return family
    return None


def _load_curve_history(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["parity"] = pd.to_numeric(frame["parity"], errors="coerce")
    frame = frame.dropna(subset=["date", "symbol", "parity"]).copy()
    frame = frame[frame["parity"] > 0].copy()
    return frame


def _load_reference_flow(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["observed_date"] = pd.to_datetime(frame["observed_date"], errors="coerce").dt.normalize()
    frame["payment_date_reference"] = pd.to_datetime(frame["payment_date_reference"], errors="coerce").dt.normalize()
    frame["residual_after_pct"] = pd.to_numeric(frame["residual_after_pct"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "observed_date", "payment_date_reference", "residual_after_pct"]).copy()
    return frame
