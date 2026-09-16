from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, closed_dates, load_market_calendar, next_business_day
from src.common.cer_curve import _days_360_excel_us, _xirr
from src.common.fixed_income import hard_dollar_metadata_frame


HARD_DOLLAR_COLUMNS = [
    "date",
    "symbol",
    "family",
    "issue_date",
    "maturity_date",
    "settlement_date",
    "payment_date",
    "currency",
    "price_basis",
    "coupon_day_count_basis",
    "settlement_lag_business_days",
    "schedule_source",
    "price",
    "volume",
    "technical_price",
    "parity",
    "tir",
    "duration",
    "modified_duration",
    "days_360_to_payment",
]
HARD_DOLLAR_AUDIT_COLUMNS = [
    "date",
    "symbol",
    "family",
    "settlement_date",
    "observed_date",
    "payment_date",
    "coupon_rate",
    "capital_pct",
    "residual_before_pct",
    "residual_after_pct",
    "coupon_amount",
    "capital_amount",
    "total_amount",
]


def build_hard_dollar_metrics(
    price_history_path: Path | str,
    reference_metadata_path: Path | str,
    reference_flow_path: Path | str,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices = _load_price_history(price_history_path)
    reference_meta = _load_reference_metadata(reference_metadata_path)
    reference_flow = _load_reference_flow(reference_flow_path)
    hard_dollar_meta = hard_dollar_metadata_frame()

    if prices.empty or reference_meta.empty or reference_flow.empty or hard_dollar_meta.empty:
        empty = pd.DataFrame(columns=HARD_DOLLAR_COLUMNS)
        empty_audit = pd.DataFrame(columns=HARD_DOLLAR_AUDIT_COLUMNS)
        return empty.copy(), empty.copy(), empty_audit.copy()

    market_calendar = load_market_calendar(calendar_path)
    settlement_closed = closed_dates(market_calendar, mode="settlement")

    metadata = hard_dollar_meta.merge(reference_meta, on="symbol", how="left", suffixes=("", "_reference"))
    metadata["issue_date"] = metadata["issue_date"].fillna(metadata["issue_date_reference"])
    metadata["maturity_date"] = metadata["maturity_date"].fillna(metadata["maturity_date_reference"])
    metadata["schedule_source"] = metadata["schedule_source"].fillna(metadata["schedule_source_reference"])
    metadata = metadata.dropna(subset=["issue_date", "maturity_date"]).copy()

    merged = prices.merge(metadata, on="symbol", how="inner")
    if merged.empty:
        empty = pd.DataFrame(columns=HARD_DOLLAR_COLUMNS)
        empty_audit = pd.DataFrame(columns=HARD_DOLLAR_AUDIT_COLUMNS)
        return empty.copy(), empty.copy(), empty_audit.copy()

    issue_date_lookup = metadata.set_index("symbol")["issue_date"].to_dict()
    schedule_cache = {
        symbol: _prepare_schedule(symbol_flow.copy(), settlement_closed, issue_date_lookup.get(symbol))
        for symbol, symbol_flow in reference_flow.groupby("symbol", sort=True)
    }

    rows: list[dict[str, object]] = []
    for symbol, symbol_prices in merged.sort_values(["symbol", "date"]).groupby("symbol", sort=True):
        schedule = schedule_cache.get(symbol)
        if schedule is None or schedule.empty:
            continue
        previous_tir = 0.10
        for price_row in symbol_prices.itertuples(index=False):
            pricing_row = _build_hard_dollar_row(price_row, schedule, settlement_closed, guess=previous_tir)
            if pricing_row is not None:
                rows.append(pricing_row)
                if pd.notna(pricing_row["tir"]):
                    previous_tir = float(pricing_row["tir"])

    history = pd.DataFrame(rows, columns=HARD_DOLLAR_COLUMNS)
    if history.empty:
        empty = pd.DataFrame(columns=HARD_DOLLAR_COLUMNS)
        empty_audit = pd.DataFrame(columns=HARD_DOLLAR_AUDIT_COLUMNS)
        return empty.copy(), empty.copy(), empty_audit.copy()

    history = history.sort_values(["date", "payment_date", "symbol"]).reset_index(drop=True)
    reference_date = history["date"].max()
    active_cutoff = max(pd.Timestamp(reference_date).normalize(), pd.Timestamp.today().normalize())
    latest = (
        history.sort_values("date")
        .groupby("symbol", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    latest = latest[pd.to_datetime(latest["payment_date"], errors="coerce") > active_cutoff].copy()
    latest = latest.sort_values(["family", "payment_date", "symbol"]).reset_index(drop=True)
    audit = _build_hard_dollar_audit(latest, reference_flow, settlement_closed)
    return history, latest, audit


def _load_price_history(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame.dropna(subset=["date", "symbol", "price"]).copy()
    frame = frame[frame["price"] > 0].copy()
    return frame


def _load_reference_metadata(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    return pd.DataFrame(
        {
            "symbol": frame["symbol"],
            "issue_date_reference": pd.to_datetime(frame.get("issue_date"), errors="coerce").dt.normalize(),
            "maturity_date_reference": pd.to_datetime(frame.get("maturity_date"), errors="coerce").dt.normalize(),
            "tir_reference": pd.to_numeric(frame.get("tir_reference"), errors="coerce"),
            "modified_duration_reference": pd.to_numeric(frame.get("modified_duration_reference"), errors="coerce"),
            "parity_reference": pd.to_numeric(frame.get("parity_reference"), errors="coerce"),
            "technical_value_reference": pd.to_numeric(frame.get("technical_value_reference"), errors="coerce"),
            "price_reference": pd.to_numeric(frame.get("price_reference"), errors="coerce"),
            "schedule_source_reference": frame.get("source_url"),
        }
    )


def _load_reference_flow(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    for column in (
        "observed_date",
        "payment_date_reference",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    numeric_columns = [
        "coupon_rate",
        "capital_pct",
        "residual_before_pct",
        "residual_after_pct",
        "coupon_amount_reference",
        "capital_amount_reference",
        "total_amount_reference",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["symbol", "observed_date", "payment_date_reference"]).copy()


def _prepare_schedule(
    reference_flow: pd.DataFrame,
    settlement_closed: set[object],
    issue_date: pd.Timestamp | object | None = None,
) -> pd.DataFrame:
    schedule = reference_flow.copy().sort_values("observed_date").reset_index(drop=True)
    if schedule.empty:
        return schedule
    normalized_issue_date = pd.Timestamp(issue_date).normalize() if issue_date is not None and not pd.isna(issue_date) else None
    schedule["payment_date"] = schedule["observed_date"].map(
        lambda value: next_business_day(value, settlement_closed, min_days_ahead=0)
    )
    schedule["previous_observed_date"] = schedule["observed_date"].shift(1)
    schedule["previous_payment_date"] = schedule["payment_date"].shift(1)
    if normalized_issue_date is not None:
        schedule["previous_observed_date"] = schedule["previous_observed_date"].fillna(normalized_issue_date)
    else:
        schedule["previous_observed_date"] = schedule["previous_observed_date"].fillna(schedule["observed_date"])
    schedule["previous_payment_date"] = schedule["previous_payment_date"].fillna(schedule["payment_date"])
    schedule["period_days_360"] = schedule.apply(
        lambda row: _days_360_excel_us(pd.Timestamp(row["previous_observed_date"]).date(), pd.Timestamp(row["observed_date"]).date()),
        axis=1,
    )
    schedule["coupon_amount_full"] = pd.to_numeric(schedule.get("coupon_amount_reference"), errors="coerce")
    fallback_coupon = (
        pd.to_numeric(schedule["residual_before_pct"], errors="coerce")
        * pd.to_numeric(schedule["coupon_rate"], errors="coerce")
        * (pd.to_numeric(schedule["period_days_360"], errors="coerce") / 360.0)
    )
    schedule["coupon_amount_full"] = schedule["coupon_amount_full"].fillna(fallback_coupon)
    schedule["capital_amount_full"] = pd.to_numeric(schedule.get("capital_amount_reference"), errors="coerce")
    schedule["capital_amount_full"] = schedule["capital_amount_full"].fillna(pd.to_numeric(schedule["capital_pct"], errors="coerce"))
    schedule["total_amount_full"] = pd.to_numeric(schedule.get("total_amount_reference"), errors="coerce")
    schedule["total_amount_full"] = schedule["total_amount_full"].fillna(schedule["coupon_amount_full"] + schedule["capital_amount_full"])
    return schedule


def _build_hard_dollar_row(
    price_row: object,
    schedule: pd.DataFrame,
    settlement_closed: set[object],
    *,
    guess: float = 0.10,
) -> dict[str, object] | None:
    settlement_date = pd.Timestamp(price_row.date).normalize()
    lag_days = int(price_row.settlement_lag_business_days)
    settlement_date = next_business_day(settlement_date, settlement_closed, min_days_ahead=lag_days)

    future_rows = schedule[schedule["observed_date"] > settlement_date].copy()
    if future_rows.empty:
        return None

    current_period = future_rows.iloc[0]
    current_residual = float(current_period["residual_before_pct"])
    accrued_interest = _compute_accrued_interest(current_period, settlement_date, str(price_row.coupon_day_count_basis))
    technical_price = current_residual + accrued_interest
    parity = float(price_row.price) / technical_price * 100.0 if technical_price > 0 else np.nan

    cashflows = [(settlement_date.to_pydatetime(), -float(price_row.price))]
    discounted_rows: list[tuple[float, float]] = []
    final_payment_date: pd.Timestamp | None = None

    for flow in future_rows.itertuples(index=False):
        coupon_amount = float(flow.coupon_amount_full)
        capital_amount = float(flow.capital_amount_full)
        total_amount = float(flow.total_amount_full)
        payment_date = pd.Timestamp(flow.payment_date).normalize()
        cashflows.append((payment_date.to_pydatetime(), total_amount))
        discounted_rows.append((((payment_date - settlement_date).days / 365.0), total_amount))
        final_payment_date = payment_date

    tir = _xirr(cashflows, guess=guess)
    if pd.isna(tir):
        duration = np.nan
        modified_duration = np.nan
    else:
        present_values = [amount / ((1.0 + tir) ** years) for years, amount in discounted_rows]
        price_value = float(price_row.price)
        duration = (
            sum(years * pv for (years, _), pv in zip(discounted_rows, present_values)) / price_value
            if price_value > 0
            else np.nan
        )
        modified_duration = duration / (1.0 + tir) if pd.notna(duration) and tir > -1.0 else np.nan

    if final_payment_date is None:
        return None

    return {
        "date": pd.Timestamp(price_row.date).normalize(),
        "symbol": price_row.symbol,
        "family": str(price_row.family).upper(),
        "issue_date": pd.Timestamp(price_row.issue_date).normalize(),
        "maturity_date": pd.Timestamp(price_row.maturity_date).normalize(),
        "settlement_date": settlement_date,
        "payment_date": final_payment_date,
        "currency": str(price_row.currency),
        "price_basis": str(price_row.price_basis),
        "coupon_day_count_basis": str(price_row.coupon_day_count_basis),
        "settlement_lag_business_days": lag_days,
        "schedule_source": str(price_row.schedule_source),
        "price": float(price_row.price),
        "volume": float(price_row.volume) if pd.notna(price_row.volume) else np.nan,
        "technical_price": technical_price,
        "parity": parity,
        "tir": tir,
        "duration": duration,
        "modified_duration": modified_duration,
        "days_360_to_payment": _days_360_excel_us(settlement_date.date(), final_payment_date.date()),
    }


def _compute_accrued_interest(current_period: pd.Series, settlement_date: pd.Timestamp, basis: str) -> float:
    previous_observed_date = pd.Timestamp(current_period["previous_observed_date"]).normalize()
    observed_date = pd.Timestamp(current_period["observed_date"]).normalize()
    residual_before_pct = float(current_period["residual_before_pct"])
    coupon_rate = float(current_period["coupon_rate"])
    if basis.strip().upper() != "30/360":
        raise ValueError(f"Unsupported day-count basis for hard-dollar curve: {basis}")
    full_period_days = _days_360_excel_us(previous_observed_date.date(), observed_date.date())
    accrued_days = _days_360_excel_us(previous_observed_date.date(), settlement_date.date())
    if full_period_days <= 0 or accrued_days <= 0:
        return 0.0
    full_coupon = residual_before_pct * coupon_rate * (full_period_days / 360.0)
    return full_coupon * accrued_days / full_period_days


def _build_hard_dollar_audit(
    latest: pd.DataFrame,
    reference_flow: pd.DataFrame,
    settlement_closed: set[object],
) -> pd.DataFrame:
    if latest.empty:
        return pd.DataFrame(columns=HARD_DOLLAR_AUDIT_COLUMNS)

    rows: list[dict[str, object]] = []
    latest = latest.copy().sort_values(["family", "payment_date", "symbol"])
    for row in latest.itertuples(index=False):
        schedule = _prepare_schedule(
            reference_flow[reference_flow["symbol"] == row.symbol].copy(),
            settlement_closed,
            row.issue_date,
        )
        if schedule.empty:
            continue
        future_rows = schedule[schedule["observed_date"] > pd.Timestamp(row.settlement_date).normalize()].copy()
        for flow in future_rows.itertuples(index=False):
            coupon_amount = float(flow.coupon_amount_full)
            capital_amount = float(flow.capital_amount_full)
            rows.append(
                {
                    "date": pd.Timestamp(row.date).normalize(),
                    "symbol": row.symbol,
                    "family": row.family,
                    "settlement_date": pd.Timestamp(row.settlement_date).normalize(),
                    "observed_date": pd.Timestamp(flow.observed_date).normalize(),
                    "payment_date": pd.Timestamp(flow.payment_date).normalize(),
                    "coupon_rate": float(flow.coupon_rate),
                    "capital_pct": capital_amount,
                    "residual_before_pct": float(flow.residual_before_pct),
                    "residual_after_pct": float(flow.residual_after_pct),
                    "coupon_amount": coupon_amount,
                    "capital_amount": capital_amount,
                    "total_amount": coupon_amount + capital_amount,
                }
            )
    return pd.DataFrame(rows, columns=HARD_DOLLAR_AUDIT_COLUMNS)
