from __future__ import annotations

from calendar import monthrange
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, add_business_days, closed_dates, load_market_calendar, next_business_day
from src.common.cer_breakeven import load_cer_index_history, load_cer_price_history
from src.common.fixed_income import cer_bond_metadata_frame


CER_ZERO_COUPON_COLUMNS = [
    "date",
    "symbol",
    "maturity_date",
    "settlement_date",
    "payment_date",
    "cer_reference_date",
    "target_lag_business_days",
    "cer_base_index",
    "cer_current_index",
    "price",
    "volume",
    "technical_price",
    "parity",
    "tir",
    "duration",
    "modified_duration",
    "days_360_to_payment",
]
NON_ZERO_COUPON_CER_SYMBOLS = {"TX26", "TX28", "TX31", "DIPO", "DICP", "PAPO", "PARP", "CUAP"}


def build_cer_zero_coupon_metrics(
    cer_price_history_path: Path | str,
    cer_index_path: Path | str,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = load_cer_price_history(cer_price_history_path)
    cer_index = load_cer_index_history(cer_index_path)
    cer_meta = cer_bond_metadata_frame()
    cer_meta = cer_meta[~cer_meta["symbol"].isin(NON_ZERO_COUPON_CER_SYMBOLS)].copy()

    if prices.empty or cer_index.empty or cer_meta.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    market_calendar = load_market_calendar(calendar_path)
    settlement_closed = closed_dates(market_calendar, mode="settlement")

    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce").dt.normalize()
    prices["symbol"] = prices["symbol"].astype(str).str.strip().str.upper()
    prices["price"] = pd.to_numeric(prices["price"], errors="coerce")
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")
    prices = prices.dropna(subset=["date", "symbol", "price"]).copy()
    prices = prices[prices["price"] > 0].copy()
    if prices.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    cer_index = cer_index.copy()
    cer_index["date"] = pd.to_datetime(cer_index["date"], errors="coerce").dt.normalize()
    cer_index["cer_index"] = pd.to_numeric(cer_index["cer_index"], errors="coerce")
    cer_index = cer_index.dropna(subset=["date", "cer_index"]).sort_values("date").copy()
    if cer_index.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    merged = prices.merge(cer_meta, on="symbol", how="inner")
    merged["maturity_date"] = pd.to_datetime(merged["maturity_date"], errors="coerce").dt.normalize()
    merged["target_lag_business_days"] = pd.to_numeric(merged["target_lag_business_days"], errors="coerce")
    merged["cer_base_index"] = pd.to_numeric(merged["cer_base_index"], errors="coerce")
    merged = merged.dropna(subset=["date", "maturity_date", "target_lag_business_days", "cer_base_index"]).copy()
    merged = merged[merged["date"] < merged["maturity_date"]].copy()
    if merged.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    merged["settlement_date"] = merged["date"].map(
        lambda value: next_business_day(value, settlement_closed, min_days_ahead=1)
    )
    merged["payment_date"] = merged["maturity_date"].map(
        lambda value: next_business_day(value, settlement_closed, min_days_ahead=0)
    )
    merged["cer_reference_date"] = merged.apply(
        lambda row: add_business_days(row["settlement_date"], -int(row["target_lag_business_days"]), settlement_closed),
        axis=1,
    )

    merged = pd.merge_asof(
        merged.sort_values("cer_reference_date"),
        cer_index.rename(columns={"date": "cer_reference_fixing_date", "cer_index": "cer_current_index"}).sort_values(
            "cer_reference_fixing_date"
        ),
        left_on="cer_reference_date",
        right_on="cer_reference_fixing_date",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values(["symbol", "date"]).reset_index(drop=True)

    merged["technical_price"] = 100.0 * merged["cer_current_index"] / merged["cer_base_index"]
    merged["parity"] = np.where(merged["technical_price"] > 0, merged["price"] / merged["technical_price"] * 100.0, np.nan)
    merged["tir"] = merged.apply(
        lambda row: _xirr(
            [
                (pd.Timestamp(row["settlement_date"]).to_pydatetime(), -float(row["price"])),
                (pd.Timestamp(row["payment_date"]).to_pydatetime(), float(row["technical_price"])),
            ]
        ),
        axis=1,
    )
    merged["duration"] = (
        (pd.to_datetime(merged["payment_date"]) - pd.to_datetime(merged["settlement_date"])).dt.days / 365.0
    )
    merged["modified_duration"] = np.where(
        merged["tir"].notna() & (merged["tir"] > -1.0),
        merged["duration"] / (1.0 + merged["tir"]),
        np.nan,
    )
    merged["days_360_to_payment"] = merged.apply(
        lambda row: _days_360_excel_us(
            pd.Timestamp(row["settlement_date"]).date(),
            pd.Timestamp(row["payment_date"]).date(),
        ),
        axis=1,
    )

    history = merged[CER_ZERO_COUPON_COLUMNS].dropna(
        subset=["settlement_date", "payment_date", "cer_reference_date", "cer_current_index", "technical_price"]
    ).copy()
    history = history.sort_values(["date", "maturity_date", "symbol"]).reset_index(drop=True)
    if history.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    reference_date = history["date"].max()
    active_cutoff = max(pd.Timestamp(reference_date).normalize(), pd.Timestamp.today().normalize())
    latest = (
        history.sort_values("date")
        .groupby("symbol", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    latest = latest[pd.to_datetime(latest["payment_date"], errors="coerce") > active_cutoff].copy()
    latest = latest.sort_values(["payment_date", "symbol"]).reset_index(drop=True)
    return history, latest


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
