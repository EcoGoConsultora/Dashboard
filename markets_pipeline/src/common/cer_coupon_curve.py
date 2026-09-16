from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.calendar import DEFAULT_MARKET_CALENDAR_PATH, add_business_days, closed_dates, load_market_calendar, next_business_day
from src.common.cer_breakeven import load_cer_index_history, load_cer_price_history
from src.common.cer_curve import CER_ZERO_COUPON_COLUMNS, _days_360_excel_us, _xirr
from src.common.fixed_income import cer_bond_metadata_frame


CER_COUPON_BOND_SYMBOLS = {"TX26", "TX28", "TX31", "DIPO", "DICP"}


@dataclass(frozen=True)
class CouponScheduleRow:
    observed_date: str
    coupon_rate: float
    capital_pct: float


def build_cer_coupon_metrics(
    cer_price_history_path: Path | str,
    cer_index_path: Path | str,
    calendar_path: Path | str = DEFAULT_MARKET_CALENDAR_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = load_cer_price_history(cer_price_history_path)
    cer_index = load_cer_index_history(cer_index_path)
    cer_meta = cer_bond_metadata_frame()
    cer_meta = cer_meta[cer_meta["symbol"].isin(CER_COUPON_BOND_SYMBOLS)].copy()

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
    prices = prices[prices["symbol"].isin(CER_COUPON_BOND_SYMBOLS)].copy()
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
    merged["capitalization_coefficient"] = pd.to_numeric(merged["capitalization_coefficient"], errors="coerce").fillna(1.0)
    merged = merged.dropna(
        subset=["date", "maturity_date", "target_lag_business_days", "cer_base_index", "capitalization_coefficient"]
    ).copy()
    merged = merged[merged["symbol"].isin(CER_COUPON_BOND_SYMBOLS)].copy()
    if merged.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    merged["settlement_date"] = merged["date"].map(
        lambda value: next_business_day(value, settlement_closed, min_days_ahead=1)
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

    rows: list[dict[str, object]] = []
    for row in merged.itertuples(index=False):
        pricing_row = _build_coupon_row(row, settlement_closed)
        if pricing_row is not None:
            rows.append(pricing_row)

    history = pd.DataFrame(rows, columns=CER_ZERO_COUPON_COLUMNS)
    if history.empty:
        empty = pd.DataFrame(columns=CER_ZERO_COUPON_COLUMNS)
        return empty.copy(), empty.copy()

    history = history.sort_values(["date", "maturity_date", "symbol"]).reset_index(drop=True)
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


def _build_coupon_row(row: object, settlement_closed: set[object]) -> dict[str, object] | None:
    schedule = _coupon_schedule(row.symbol)
    if not schedule:
        return None

    settlement_date = pd.Timestamp(row.settlement_date).normalize()
    cer_current_index = float(row.cer_current_index) if pd.notna(row.cer_current_index) else np.nan
    capitalization_coefficient = float(row.capitalization_coefficient) if pd.notna(row.capitalization_coefficient) else 1.0
    if not np.isfinite(cer_current_index) or cer_current_index <= 0:
        return None
    if not np.isfinite(capitalization_coefficient) or capitalization_coefficient <= 0:
        return None

    future_rows = [item for item in schedule if item["payment_date"] > settlement_date]
    if not future_rows:
        return None

    cashflows = [(settlement_date.to_pydatetime(), -float(row.price))]
    discounted_rows: list[tuple[float, float]] = []
    future_capital_amounts: list[float] = []
    final_effective_payment_date: pd.Timestamp | None = None

    for item in future_rows:
        residual_before_pct = float(item["residual_before_pct"])
        capital_pct = float(item["capital_pct"])
        coupon_rate = float(item["coupon_rate"])
        period_days_360 = _days_360_excel_us(item["previous_observed_date"].date(), item["observed_date"].date())

        residual_amount = (
            100.0
            * residual_before_pct
            / 100.0
            * cer_current_index
            / float(row.cer_base_index)
            * capitalization_coefficient
        )
        capital_amount = (
            100.0
            * capital_pct
            / 100.0
            * cer_current_index
            / float(row.cer_base_index)
            * capitalization_coefficient
        )
        interest_amount = residual_amount * coupon_rate * (period_days_360 / 360.0)
        total_amount = capital_amount + interest_amount
        payment_date = next_business_day(item["observed_date"], settlement_closed, min_days_ahead=0)

        cashflows.append((payment_date.to_pydatetime(), total_amount))
        years_to_payment = (payment_date - settlement_date).days / 365.0
        discounted_rows.append((years_to_payment, total_amount))
        future_capital_amounts.append(capital_amount)
        final_effective_payment_date = payment_date

    tir = _xirr(cashflows)
    if pd.isna(tir):
        duration = np.nan
        modified_duration = np.nan
    else:
        present_values = [amount / ((1.0 + tir) ** years) for years, amount in discounted_rows]
        price_value = float(row.price)
        duration = (
            sum(years * pv for (years, _), pv in zip(discounted_rows, present_values)) / price_value
            if price_value > 0
            else np.nan
        )
        modified_duration = duration / (1.0 + tir) if pd.notna(duration) and tir > -1.0 else np.nan

    if final_effective_payment_date is None:
        return None
    final_payment_date = final_effective_payment_date
    technical_price = float(sum(future_capital_amounts))
    parity = float(row.price) / technical_price * 100.0 if technical_price > 0 else np.nan

    return {
        "date": pd.Timestamp(row.date).normalize(),
        "symbol": row.symbol,
        "maturity_date": pd.Timestamp(row.maturity_date).normalize(),
        "settlement_date": settlement_date,
        "payment_date": final_payment_date,
        "cer_reference_date": pd.Timestamp(row.cer_reference_date).normalize(),
        "target_lag_business_days": int(row.target_lag_business_days),
        "cer_base_index": float(row.cer_base_index),
        "capitalization_coefficient": capitalization_coefficient,
        "cer_current_index": cer_current_index,
        "price": float(row.price),
        "volume": float(row.volume) if pd.notna(row.volume) else np.nan,
        "technical_price": technical_price,
        "parity": parity,
        "tir": tir,
        "duration": duration,
        "modified_duration": modified_duration,
        "days_360_to_payment": _days_360_excel_us(settlement_date.date(), final_payment_date.date()),
    }


def _coupon_schedule(symbol: str) -> list[dict[str, object]]:
    raw_rows = _CER_COUPON_SCHEDULES.get(str(symbol).strip().upper(), [])
    schedule: list[dict[str, object]] = []
    residual_before_pct = 100.0
    previous_observed_date: pd.Timestamp | None = None

    for raw in raw_rows:
        observed_date = pd.Timestamp(raw.observed_date).normalize()
        payment_date = observed_date
        residual_after_pct = max(0.0, residual_before_pct - float(raw.capital_pct))
        schedule.append(
            {
                "observed_date": observed_date,
                "payment_date": payment_date,
                "previous_observed_date": previous_observed_date if previous_observed_date is not None else observed_date,
                "coupon_rate": float(raw.coupon_rate),
                "capital_pct": float(raw.capital_pct),
                "residual_before_pct": residual_before_pct,
                "residual_after_pct": residual_after_pct,
            }
        )
        previous_observed_date = observed_date
        residual_before_pct = residual_after_pct

    return schedule


_CER_COUPON_SCHEDULES: dict[str, list[CouponScheduleRow]] = {
    "TX26": [
        CouponScheduleRow("2021-05-10", 0.02, 0.0),
        CouponScheduleRow("2021-11-09", 0.02, 0.0),
        CouponScheduleRow("2022-05-09", 0.02, 0.0),
        CouponScheduleRow("2022-11-09", 0.02, 0.0),
        CouponScheduleRow("2023-05-09", 0.02, 0.0),
        CouponScheduleRow("2023-11-09", 0.02, 0.0),
        CouponScheduleRow("2024-05-09", 0.02, 0.0),
        CouponScheduleRow("2024-11-11", 0.02, 20.0),
        CouponScheduleRow("2025-05-09", 0.02, 20.0),
        CouponScheduleRow("2025-11-10", 0.02, 20.0),
        CouponScheduleRow("2026-05-11", 0.02, 20.0),
        CouponScheduleRow("2026-11-09", 0.02, 20.0),
    ],
    "TX28": [
        CouponScheduleRow("2021-05-10", 0.0225, 0.0),
        CouponScheduleRow("2021-11-09", 0.0225, 0.0),
        CouponScheduleRow("2022-05-09", 0.0225, 0.0),
        CouponScheduleRow("2022-11-09", 0.0225, 0.0),
        CouponScheduleRow("2023-05-09", 0.0225, 0.0),
        CouponScheduleRow("2023-11-09", 0.0225, 0.0),
        CouponScheduleRow("2024-05-09", 0.0225, 10.0),
        CouponScheduleRow("2024-11-11", 0.0225, 10.0),
        CouponScheduleRow("2025-05-09", 0.0225, 10.0),
        CouponScheduleRow("2025-11-10", 0.0225, 10.0),
        CouponScheduleRow("2026-05-11", 0.0225, 10.0),
        CouponScheduleRow("2026-11-09", 0.0225, 10.0),
        CouponScheduleRow("2027-05-10", 0.0225, 10.0),
        CouponScheduleRow("2027-11-09", 0.0225, 10.0),
        CouponScheduleRow("2028-05-09", 0.0225, 10.0),
        CouponScheduleRow("2028-11-09", 0.0225, 10.0),
    ],
    "TX31": [
        CouponScheduleRow("2022-11-30", 0.025, 0.0),
        CouponScheduleRow("2023-05-30", 0.025, 0.0),
        CouponScheduleRow("2023-11-30", 0.025, 0.0),
        CouponScheduleRow("2024-05-30", 0.025, 0.0),
        CouponScheduleRow("2024-12-02", 0.025, 0.0),
        CouponScheduleRow("2025-05-30", 0.025, 0.0),
        CouponScheduleRow("2025-12-01", 0.025, 0.0),
        CouponScheduleRow("2026-06-01", 0.025, 0.0),
        CouponScheduleRow("2026-11-30", 0.025, 0.0),
        CouponScheduleRow("2027-05-31", 0.025, 10.0),
        CouponScheduleRow("2027-11-30", 0.025, 10.0),
        CouponScheduleRow("2028-05-30", 0.025, 10.0),
        CouponScheduleRow("2028-11-30", 0.025, 10.0),
        CouponScheduleRow("2029-05-30", 0.025, 10.0),
        CouponScheduleRow("2029-11-30", 0.025, 10.0),
        CouponScheduleRow("2030-05-30", 0.025, 10.0),
        CouponScheduleRow("2030-12-02", 0.025, 10.0),
        CouponScheduleRow("2031-05-30", 0.025, 10.0),
        CouponScheduleRow("2031-12-01", 0.025, 10.0),
    ],
    "DIPO": [
        CouponScheduleRow("2010-06-30", 0.0583, 0.0),
        CouponScheduleRow("2010-12-31", 0.0583, 0.0),
        CouponScheduleRow("2011-06-30", 0.0583, 0.0),
        CouponScheduleRow("2011-12-31", 0.0583, 0.0),
        CouponScheduleRow("2012-06-30", 0.0583, 0.0),
        CouponScheduleRow("2012-12-31", 0.0583, 0.0),
        CouponScheduleRow("2013-06-30", 0.0583, 0.0),
        CouponScheduleRow("2013-12-31", 0.0583, 0.0),
        CouponScheduleRow("2014-06-30", 0.0583, 0.0),
        CouponScheduleRow("2014-12-31", 0.0583, 0.0),
        CouponScheduleRow("2015-06-30", 0.0583, 0.0),
        CouponScheduleRow("2015-12-31", 0.0583, 0.0),
        CouponScheduleRow("2016-06-30", 0.0583, 0.0),
        CouponScheduleRow("2016-12-31", 0.0583, 0.0),
        CouponScheduleRow("2017-06-30", 0.0583, 0.0),
        CouponScheduleRow("2017-12-31", 0.0583, 0.0),
        CouponScheduleRow("2018-06-30", 0.0583, 0.0),
        CouponScheduleRow("2018-12-31", 0.0583, 0.0),
        CouponScheduleRow("2019-06-30", 0.0583, 0.0),
        CouponScheduleRow("2019-12-31", 0.0583, 0.0),
        CouponScheduleRow("2020-06-30", 0.0583, 0.0),
        CouponScheduleRow("2020-12-31", 0.0583, 0.0),
        CouponScheduleRow("2021-06-30", 0.0583, 0.0),
        CouponScheduleRow("2021-12-31", 0.0583, 0.0),
        CouponScheduleRow("2022-06-30", 0.0583, 0.0),
        CouponScheduleRow("2022-12-31", 0.0583, 0.0),
        CouponScheduleRow("2023-06-30", 0.0583, 0.0),
        CouponScheduleRow("2023-12-31", 0.0583, 0.0),
        CouponScheduleRow("2024-06-30", 0.0583, 5.0),
        CouponScheduleRow("2024-12-31", 0.0583, 5.0),
        CouponScheduleRow("2025-06-30", 0.0583, 5.0),
        CouponScheduleRow("2025-12-31", 0.0583, 5.0),
        CouponScheduleRow("2026-06-30", 0.0583, 5.0),
        CouponScheduleRow("2026-12-31", 0.0583, 5.0),
        CouponScheduleRow("2027-06-30", 0.0583, 5.0),
        CouponScheduleRow("2027-12-31", 0.0583, 5.0),
        CouponScheduleRow("2028-06-30", 0.0583, 5.0),
        CouponScheduleRow("2028-12-31", 0.0583, 5.0),
        CouponScheduleRow("2029-06-30", 0.0583, 5.0),
        CouponScheduleRow("2029-12-31", 0.0583, 5.0),
        CouponScheduleRow("2030-06-30", 0.0583, 5.0),
        CouponScheduleRow("2030-12-31", 0.0583, 5.0),
        CouponScheduleRow("2031-06-30", 0.0583, 5.0),
        CouponScheduleRow("2031-12-31", 0.0583, 5.0),
        CouponScheduleRow("2032-06-30", 0.0583, 5.0),
        CouponScheduleRow("2032-12-31", 0.0583, 5.0),
        CouponScheduleRow("2033-06-30", 0.0583, 5.0),
        CouponScheduleRow("2033-12-31", 0.0583, 5.0),
    ],
    "DICP": [
        CouponScheduleRow("2004-06-30", 0.0279, 0.0),
        CouponScheduleRow("2004-12-31", 0.0279, 0.0),
        CouponScheduleRow("2005-06-30", 0.0279, 0.0),
        CouponScheduleRow("2005-12-31", 0.0279, 0.0),
        CouponScheduleRow("2006-06-30", 0.0279, 0.0),
        CouponScheduleRow("2006-12-31", 0.0279, 0.0),
        CouponScheduleRow("2007-06-30", 0.0279, 0.0),
        CouponScheduleRow("2007-12-31", 0.0279, 0.0),
        CouponScheduleRow("2008-06-30", 0.0279, 0.0),
        CouponScheduleRow("2008-12-31", 0.0279, 0.0),
        CouponScheduleRow("2009-06-30", 0.0406, 0.0),
        CouponScheduleRow("2009-12-31", 0.0406, 0.0),
        CouponScheduleRow("2010-06-30", 0.0406, 0.0),
        CouponScheduleRow("2010-12-31", 0.0406, 0.0),
        CouponScheduleRow("2011-06-30", 0.0406, 0.0),
        CouponScheduleRow("2011-12-31", 0.0406, 0.0),
        CouponScheduleRow("2012-06-30", 0.0406, 0.0),
        CouponScheduleRow("2012-12-31", 0.0406, 0.0),
        CouponScheduleRow("2013-06-30", 0.0406, 0.0),
        CouponScheduleRow("2013-12-31", 0.0406, 0.0),
        CouponScheduleRow("2014-06-30", 0.0583, 0.0),
        CouponScheduleRow("2014-12-31", 0.0583, 0.0),
        CouponScheduleRow("2015-06-30", 0.0583, 0.0),
        CouponScheduleRow("2015-12-31", 0.0583, 0.0),
        CouponScheduleRow("2016-06-30", 0.0583, 0.0),
        CouponScheduleRow("2016-12-31", 0.0583, 0.0),
        CouponScheduleRow("2017-06-30", 0.0583, 0.0),
        CouponScheduleRow("2017-12-31", 0.0583, 0.0),
        CouponScheduleRow("2018-06-30", 0.0583, 0.0),
        CouponScheduleRow("2018-12-31", 0.0583, 0.0),
        CouponScheduleRow("2019-06-30", 0.0583, 0.0),
        CouponScheduleRow("2019-12-31", 0.0583, 0.0),
        CouponScheduleRow("2020-06-30", 0.0583, 0.0),
        CouponScheduleRow("2020-12-31", 0.0583, 0.0),
        CouponScheduleRow("2021-06-30", 0.0583, 0.0),
        CouponScheduleRow("2021-12-31", 0.0583, 0.0),
        CouponScheduleRow("2022-06-30", 0.0583, 0.0),
        CouponScheduleRow("2022-12-31", 0.0583, 0.0),
        CouponScheduleRow("2023-06-30", 0.0583, 0.0),
        CouponScheduleRow("2023-12-31", 0.0583, 0.0),
        CouponScheduleRow("2024-06-30", 0.0583, 5.0),
        CouponScheduleRow("2024-12-31", 0.0583, 5.0),
        CouponScheduleRow("2025-06-30", 0.0583, 5.0),
        CouponScheduleRow("2025-12-31", 0.0583, 5.0),
        CouponScheduleRow("2026-06-30", 0.0583, 5.0),
        CouponScheduleRow("2026-12-31", 0.0583, 5.0),
        CouponScheduleRow("2027-06-30", 0.0583, 5.0),
        CouponScheduleRow("2027-12-31", 0.0583, 5.0),
        CouponScheduleRow("2028-06-30", 0.0583, 5.0),
        CouponScheduleRow("2028-12-31", 0.0583, 5.0),
        CouponScheduleRow("2029-06-30", 0.0583, 5.0),
        CouponScheduleRow("2029-12-31", 0.0583, 5.0),
        CouponScheduleRow("2030-06-30", 0.0583, 5.0),
        CouponScheduleRow("2030-12-31", 0.0583, 5.0),
        CouponScheduleRow("2031-06-30", 0.0583, 5.0),
        CouponScheduleRow("2031-12-31", 0.0583, 5.0),
        CouponScheduleRow("2032-06-30", 0.0583, 5.0),
        CouponScheduleRow("2032-12-31", 0.0583, 5.0),
        CouponScheduleRow("2033-06-30", 0.0583, 5.0),
        CouponScheduleRow("2033-12-31", 0.0583, 5.0),
    ],
}
