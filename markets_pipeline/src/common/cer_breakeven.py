from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, add_business_days, closed_dates, load_market_calendar, next_business_day
from src.common.fixed_income import cer_bond_metadata_frame, cer_pair_specs_frame


CER_PRICE_HISTORY_COLUMNS = ["date", "symbol", "price", "volume", "market", "source"]
CER_INDEX_COLUMNS = ["date", "cer_index"]
BREAKEVEN_HISTORY_COLUMNS = [
    "date",
    "pair_label",
    "fixed_symbol",
    "cer_symbol",
    "maturity_date",
    "cer_target_date",
    "latest_cer_date",
    "latest_cer_value",
    "implied_cer",
    "breakeven_monthly",
    "breakeven_monthly_pct",
    "breakeven_annual_equivalent",
    "horizon_days",
    "is_active",
]
BREAKEVEN_MONTHLY_COLUMNS = [
    "date",
    "month",
    "month_label",
    "source_pair_label",
    "fixed_symbol",
    "cer_symbol",
    "maturity_date",
    "cer_target_date",
    "latest_cer_date",
    "latest_cer_value",
    "implied_cer",
    "avg_monthly",
    "avg_monthly_pct",
    "cumulative_factor",
    "months_count",
    "block_months",
    "forward_monthly",
    "forward_monthly_pct",
    "is_gap_fill",
]


def load_cer_price_history(path: Path | str) -> pd.DataFrame:
    history_path = Path(path)
    if not history_path.exists() or history_path.stat().st_size == 0:
        return pd.DataFrame(columns=CER_PRICE_HISTORY_COLUMNS)

    frame = pd.read_csv(history_path, parse_dates=["date"])
    for column in CER_PRICE_HISTORY_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame["market"] = frame["market"].astype(str).str.strip().str.upper()
    frame["source"] = frame["source"].astype(str).str.strip()
    frame = frame.dropna(subset=["date", "symbol", "price"]).copy()
    return frame[CER_PRICE_HISTORY_COLUMNS].sort_values(["symbol", "date"]).reset_index(drop=True)


def load_cer_index_history(path: Path | str) -> pd.DataFrame:
    cer_path = Path(path)
    if not cer_path.exists() or cer_path.stat().st_size == 0:
        return pd.DataFrame(columns=CER_INDEX_COLUMNS)

    frame = pd.read_csv(cer_path, parse_dates=["date"])
    if "cer_index" not in frame.columns and "value" in frame.columns:
        frame = frame.rename(columns={"value": "cer_index"})
    for column in CER_INDEX_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["cer_index"] = pd.to_numeric(frame["cer_index"], errors="coerce")
    frame = frame.dropna(subset=["date", "cer_index"]).copy()
    return frame[CER_INDEX_COLUMNS].sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)


def build_breakeven_monitor_live(
    fixed_metrics: pd.DataFrame,
    cer_price_history: pd.DataFrame,
    cer_index_history: pd.DataFrame,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_specs = cer_pair_specs_frame()
    cer_meta = cer_bond_metadata_frame()
    if fixed_metrics.empty or cer_price_history.empty or cer_index_history.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_HISTORY_COLUMNS)
        return empty.copy(), empty.copy()

    prices = _normalize_price_history_frame(cer_price_history)
    if prices.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_HISTORY_COLUMNS)
        return empty.copy(), empty.copy()

    metrics = _normalize_fixed_metrics_frame(fixed_metrics)
    if metrics.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_HISTORY_COLUMNS)
        return empty.copy(), empty.copy()

    cer_index = cer_index_history.copy()
    cer_index["date"] = pd.to_datetime(cer_index["date"], errors="coerce").dt.normalize()
    cer_index["cer_index"] = pd.to_numeric(cer_index["cer_index"], errors="coerce")
    cer_index = cer_index.dropna(subset=["date", "cer_index"]).sort_values("date").copy()
    if cer_index.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_HISTORY_COLUMNS)
        return empty.copy(), empty.copy()

    market_calendar = load_market_calendar(calendar_path)
    settlement_closed = closed_dates(market_calendar, mode="settlement")

    merged_rows: list[pd.DataFrame] = []
    for pair in pair_specs.itertuples(index=False):
        fixed_columns = ["date", "tea", "maturity_date"]
        for optional_column in ("settlement_date", "next_business_day"):
            if optional_column in metrics.columns:
                fixed_columns.append(optional_column)
        fixed_leg = metrics[metrics["symbol"] == pair.fixed_symbol][fixed_columns].copy()
        cer_leg = prices[prices["symbol"] == pair.cer_symbol][["date", "price"]].copy()
        cer_leg = cer_leg.rename(columns={"price": "cer_price"})
        cer_meta_row = cer_meta[cer_meta["symbol"] == pair.cer_symbol].copy()
        if fixed_leg.empty or cer_leg.empty or cer_meta_row.empty:
            continue

        pair_frame = fixed_leg.merge(cer_leg, on="date", how="inner")
        if pair_frame.empty:
            continue

        meta_row = cer_meta_row.iloc[0]
        pair_frame["pair_label"] = pair.pair_label
        pair_frame["fixed_symbol"] = pair.fixed_symbol
        pair_frame["cer_symbol"] = pair.cer_symbol
        pair_frame["cer_maturity_date"] = pd.Timestamp(meta_row["maturity_date"]).normalize()
        pair_frame["cer_base_index"] = float(meta_row["cer_base_index"])
        pair_frame["cer_target_date"] = add_business_days(
            pair_frame["cer_maturity_date"].iloc[0],
            -int(meta_row["target_lag_business_days"]),
            settlement_closed,
        )
        if "settlement_date" in pair_frame.columns:
            pair_frame["settlement_date"] = pd.to_datetime(pair_frame["settlement_date"], errors="coerce").dt.normalize()
        elif "next_business_day" in pair_frame.columns:
            pair_frame["settlement_date"] = pd.to_datetime(pair_frame["next_business_day"], errors="coerce").dt.normalize()
        else:
            pair_frame["settlement_date"] = pair_frame["date"].map(
                lambda value: next_business_day(value, settlement_closed, min_days_ahead=1)
            )
        pair_frame["settlement_date"] = pair_frame["settlement_date"].fillna(
            pair_frame["date"].map(lambda value: next_business_day(value, settlement_closed, min_days_ahead=1))
        )
        pair_frame["cer_payment_date"] = next_business_day(
            pair_frame["cer_maturity_date"].iloc[0],
            settlement_closed,
            min_days_ahead=0,
        )
        pair_frame["year_fraction"] = (
            (pair_frame["cer_payment_date"] - pair_frame["settlement_date"]).dt.days.clip(lower=0) / 365.0
        )
        pair_frame["implied_cer"] = pair_frame["cer_base_index"] * (
            pair_frame["cer_price"] * np.power(1.0 + pair_frame["tea"], pair_frame["year_fraction"])
        ) / 100.0
        merged_rows.append(pair_frame)

    if not merged_rows:
        empty = pd.DataFrame(columns=BREAKEVEN_HISTORY_COLUMNS)
        return empty.copy(), empty.copy()

    history = pd.concat(merged_rows, ignore_index=True)
    history = history.sort_values(["pair_label", "date"]).reset_index(drop=True)
    history["cer_publication_end_date"] = history["date"].map(cer_publication_window_end)
    history = pd.merge_asof(
        history.sort_values("cer_publication_end_date"),
        cer_index.rename(columns={"date": "latest_cer_date", "cer_index": "latest_cer_value"}).sort_values("latest_cer_date"),
        left_on="cer_publication_end_date",
        right_on="latest_cer_date",
        direction="backward",
    ).sort_values(["date", "maturity_date", "pair_label"]).reset_index(drop=True)
    history["horizon_days"] = (
        pd.to_datetime(history["cer_target_date"], errors="coerce").dt.normalize()
        - pd.to_datetime(history["latest_cer_date"], errors="coerce").dt.normalize()
    ).dt.days
    valid_ratio = (
        history["implied_cer"].gt(0)
        & pd.to_numeric(history["latest_cer_value"], errors="coerce").gt(0)
        & pd.to_numeric(history["horizon_days"], errors="coerce").gt(0)
    )
    history["breakeven_monthly"] = np.where(
        valid_ratio,
        np.power(history["implied_cer"] / history["latest_cer_value"], 30.0 / history["horizon_days"]) - 1.0,
        np.nan,
    )
    history["breakeven_monthly_pct"] = history["breakeven_monthly"] * 100.0
    history["breakeven_annual_equivalent"] = np.where(
        history["breakeven_monthly"].gt(-0.999999),
        np.power(1.0 + history["breakeven_monthly"], 12.0) - 1.0,
        np.nan,
    )
    history["is_active"] = history["horizon_days"].gt(0)
    history = history.dropna(
        subset=["date", "pair_label", "fixed_symbol", "cer_symbol", "maturity_date", "latest_cer_date", "latest_cer_value", "implied_cer"]
    ).copy()
    history = history[BREAKEVEN_HISTORY_COLUMNS].sort_values(["date", "maturity_date", "pair_label"]).reset_index(drop=True)

    if history.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_HISTORY_COLUMNS)
        return empty.copy(), empty.copy()

    reference_date = history["date"].max()
    latest = (
        history[history["is_active"]]
        .sort_values("date")
        .groupby("pair_label", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    latest = latest[pd.to_datetime(latest["maturity_date"], errors="coerce") > reference_date].copy()
    latest = latest.sort_values(["maturity_date", "pair_label"]).reset_index(drop=True)
    return history, latest


def _normalize_fixed_metrics_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["symbol"] = work["symbol"].astype(str).str.strip().str.upper()
    work["maturity_date"] = pd.to_datetime(work["maturity_date"], errors="coerce").dt.normalize()
    for optional_column in ("settlement_date", "next_business_day"):
        if optional_column in work.columns:
            work[optional_column] = pd.to_datetime(work[optional_column], errors="coerce").dt.normalize()
    if "tea" in work.columns:
        work["tea"] = pd.to_numeric(work["tea"], errors="coerce")
    elif "tea_pct" in work.columns:
        work["tea"] = pd.to_numeric(work["tea_pct"], errors="coerce") / 100.0
    elif "tem" in work.columns:
        work["tea"] = (1.0 + pd.to_numeric(work["tem"], errors="coerce")) ** 12.0 - 1.0
    elif "tem_pct" in work.columns:
        work["tea"] = (1.0 + pd.to_numeric(work["tem_pct"], errors="coerce") / 100.0) ** 12.0 - 1.0
    else:
        work["tea"] = pd.NA
    work["tea"] = pd.to_numeric(work["tea"], errors="coerce")
    work = work.dropna(subset=["date", "symbol", "tea", "maturity_date"]).copy()
    return work


def _normalize_price_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["symbol"] = work["symbol"].astype(str).str.strip().str.upper()
    work["price"] = pd.to_numeric(work["price"], errors="coerce")
    work = work.dropna(subset=["date", "symbol", "price"]).copy()
    work = work[work["price"] > 0].copy()
    return work


def cer_publication_window_end(value: pd.Timestamp) -> pd.Timestamp:
    current = pd.Timestamp(value).normalize()
    if current.day <= 15:
        return current.replace(day=15)
    next_month = current + pd.offsets.MonthBegin(1)
    return next_month.replace(day=15).normalize()


def select_target_breakeven_metrics(
    history: pd.DataFrame,
    target_horizon_days: int,
    metric_column: str = "breakeven_annual_equivalent",
    min_horizon_days: int | None = None,
    max_horizon_days: int | None = None,
) -> pd.DataFrame:
    if metric_column not in history.columns:
        raise ValueError(f"Break-even selection cannot find metric column '{metric_column}'.")

    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    frame[metric_column] = pd.to_numeric(frame[metric_column], errors="coerce")
    frame = frame.dropna(subset=["date", "horizon_days", metric_column]).copy()
    frame = frame[frame["horizon_days"] > 0].copy()

    if min_horizon_days is not None:
        frame = frame[frame["horizon_days"] >= int(min_horizon_days)].copy()
    if max_horizon_days is not None:
        frame = frame[frame["horizon_days"] <= int(max_horizon_days)].copy()
    if frame.empty:
        return pd.DataFrame(columns=[*BREAKEVEN_HISTORY_COLUMNS, "target_horizon_days", "days_to_target"])

    frame["target_horizon_days"] = int(target_horizon_days)
    frame["days_to_target"] = (frame["horizon_days"] - int(target_horizon_days)).abs()
    selected = (
        frame.sort_values(["date", "days_to_target", "horizon_days", "pair_label"])
        .groupby("date", as_index=False)
        .head(1)
        .sort_values("date")
        .reset_index(drop=True)
    )
    return selected[[*BREAKEVEN_HISTORY_COLUMNS, "target_horizon_days", "days_to_target"]]


def build_breakeven_forward_monthly(
    history: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if history.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_MONTHLY_COLUMNS)
        return empty.copy(), empty.copy()

    work = history.copy()
    work = work.dropna(subset=["date", "maturity_date", "latest_cer_date", "breakeven_monthly"]).copy()
    work = work[work["breakeven_monthly"] > -0.999999].copy()
    if work.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_MONTHLY_COLUMNS)
        return empty.copy(), empty.copy()

    # The monthly breakeven strip should start at the last fully accrued
    # inflation month implied by the latest CER print. Example:
    # CER through 2026-04-15 still maps to mar-26; CER through 2026-05-15
    # maps to abr-26.
    work["start_month"] = _breakeven_display_month_start(work["latest_cer_date"])
    work["end_month"] = _month_start_from_maturity(work["maturity_date"], months_back=2)
    work["months_count"] = _inclusive_month_span(work["start_month"], work["end_month"])
    work = work[work["months_count"] > 0].copy()
    if work.empty:
        empty = pd.DataFrame(columns=BREAKEVEN_MONTHLY_COLUMNS)
        return empty.copy(), empty.copy()

    monthly_rows: list[dict[str, object]] = []
    for _, date_group in work.groupby("date", sort=True):
        curve = (
            date_group.sort_values(["end_month", "horizon_days", "maturity_date", "pair_label"])
            .drop_duplicates(subset=["end_month"], keep="first")
            .sort_values("end_month")
            .reset_index(drop=True)
        )
        if curve.empty:
            continue

        prev_cumulative_factor = 1.0
        prev_months_count = 0
        start_month = curve["start_month"].min()

        for row in curve.itertuples(index=False):
            block_months = int(row.months_count) - prev_months_count
            if block_months <= 0:
                continue

            cumulative_factor = float((1.0 + float(row.breakeven_monthly)) ** int(row.months_count))
            block_factor = cumulative_factor / prev_cumulative_factor
            forward_monthly = block_factor ** (1.0 / block_months) - 1.0

            for offset in range(block_months):
                month = _add_months(start_month, prev_months_count + offset)
                monthly_rows.append(
                    {
                        "date": row.date,
                        "month": month,
                        "month_label": _format_month_label(month),
                        "source_pair_label": row.pair_label,
                        "fixed_symbol": row.fixed_symbol,
                        "cer_symbol": row.cer_symbol,
                        "maturity_date": row.maturity_date,
                        "cer_target_date": row.cer_target_date,
                        "latest_cer_date": row.latest_cer_date,
                        "latest_cer_value": row.latest_cer_value,
                        "implied_cer": row.implied_cer,
                        "avg_monthly": row.breakeven_monthly,
                        "avg_monthly_pct": row.breakeven_monthly_pct,
                        "cumulative_factor": cumulative_factor,
                        "months_count": int(row.months_count),
                        "block_months": block_months,
                        "forward_monthly": forward_monthly,
                        "forward_monthly_pct": forward_monthly * 100.0,
                        "is_gap_fill": block_months > 1,
                    }
                )

            prev_cumulative_factor = cumulative_factor
            prev_months_count = int(row.months_count)

    if not monthly_rows:
        empty = pd.DataFrame(columns=BREAKEVEN_MONTHLY_COLUMNS)
        return empty.copy(), empty.copy()

    monthly_history = pd.DataFrame(monthly_rows, columns=BREAKEVEN_MONTHLY_COLUMNS).copy()
    monthly_history["date"] = pd.to_datetime(monthly_history["date"], errors="coerce").dt.normalize()
    monthly_history["month"] = pd.to_datetime(monthly_history["month"], errors="coerce").dt.normalize()
    monthly_history["maturity_date"] = pd.to_datetime(monthly_history["maturity_date"], errors="coerce").dt.normalize()
    monthly_history["cer_target_date"] = pd.to_datetime(monthly_history["cer_target_date"], errors="coerce").dt.normalize()
    monthly_history["latest_cer_date"] = pd.to_datetime(monthly_history["latest_cer_date"], errors="coerce").dt.normalize()
    monthly_history = monthly_history.sort_values(["date", "month", "source_pair_label"]).reset_index(drop=True)

    latest_date = monthly_history["date"].max()
    monthly_latest = monthly_history[monthly_history["date"] == latest_date].copy().reset_index(drop=True)
    return monthly_history, monthly_latest


def _month_start_from_maturity(value: pd.Series, months_back: int) -> pd.Series:
    periods = value.dt.to_period("M") - months_back
    return periods.dt.to_timestamp()


def _breakeven_display_month_start(value: pd.Series) -> pd.Series:
    periods = value.dt.to_period("M") - 1
    return periods.dt.to_timestamp()


def _inclusive_month_span(start: pd.Series, end: pd.Series) -> pd.Series:
    return (end.dt.year - start.dt.year) * 12 + (end.dt.month - start.dt.month) + 1


def _add_months(value: pd.Timestamp, months: int) -> pd.Timestamp:
    period = value.to_period("M") + months
    return period.to_timestamp().normalize()


def _format_month_label(value: pd.Timestamp) -> str:
    month_labels = {
        1: "ene",
        2: "feb",
        3: "mar",
        4: "abr",
        5: "may",
        6: "jun",
        7: "jul",
        8: "ago",
        9: "sep",
        10: "oct",
        11: "nov",
        12: "dic",
    }
    return f"{month_labels[value.month]}-{str(value.year)[-2:]}"
