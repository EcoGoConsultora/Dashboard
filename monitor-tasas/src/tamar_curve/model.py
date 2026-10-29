"""Contractual cash-flow and yield calculations for pure TAMAR instruments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import math
from statistics import fmean
from typing import Any, Mapping

from .calendar import BankBusinessCalendar


VN_BASE = 100.0
TAMAR_PERIODS_PER_YEAR = 365.0 / 32.0


@dataclass(frozen=True)
class InstrumentTerms:
    symbol: str
    issue_date: date
    maturity_date: date
    margin_tna_pct: float
    instrument_type: str
    terms_sources: tuple[str, ...]


@dataclass(frozen=True)
class CurveNode:
    symbol: str
    instrument_type: str
    issue_date: date
    maturity_date: date
    settlement_date: date
    price_per_vn_100: float
    margin_tna_pct: float
    fixing_window_start: date
    fixing_window_end: date
    fixing_as_of: date
    total_fixings: int
    known_fixings: int
    projected_fixings: int
    known_average_tna_pct: float
    projected_tna_pct: float
    contractual_tamar_average_tna_pct: float
    tamar_tem_pct: float
    terminal_value_per_vn_100: float
    days_30_360: int
    tir_tea_pct: float
    tir_tna_pct: float
    tir_tem_pct: float
    macauley_duration_years: float
    modified_duration_years: float
    forecast_method: str

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "issue_date", "maturity_date", "settlement_date", "fixing_window_start",
            "fixing_window_end", "fixing_as_of",
        ):
            result[key] = result[key].isoformat()
        return result


def days_30_360_us(start: date, end: date) -> int:
    """Excel ``DAYS360(..., FALSE)`` / 30-360 US (NASD) day count."""

    if end < start:
        raise ValueError("La fecha final no puede preceder a la inicial")

    def is_month_end(candidate: date) -> bool:
        return (candidate + timedelta(days=1)).month != candidate.month

    d1 = start.day
    d2 = end.day
    end_month = end.month
    end_year = end.year
    if is_month_end(start):
        d1 = 30
    if is_month_end(end):
        if d1 < 30:
            d2 = 1
            if end_month == 12:
                end_month = 1
                end_year += 1
            else:
                end_month += 1
        else:
            d2 = 30
    elif d2 == 31 and d1 >= 30:
        d2 = 30
    return 360 * (end_year - start.year) + 30 * (end_month - start.month) + d2 - d1


def tamar_tem(tamar_average_tna_pct: float, margin_tna_pct: float) -> float:
    """Contractual monthly effective rate from TAMAR private plus margin."""

    annual_rate = (tamar_average_tna_pct + margin_tna_pct) / 100.0
    if annual_rate <= -TAMAR_PERIODS_PER_YEAR:
        raise ValueError("TAMAR mas margen no admite capitalizacion contractual")
    return (1.0 + annual_rate / TAMAR_PERIODS_PER_YEAR) ** (TAMAR_PERIODS_PER_YEAR / 12.0) - 1.0


def single_cashflow_xirr(price: float, payoff: float, settlement_date: date, maturity_date: date) -> float:
    """Exact XIRR for one initial outflow and one terminal cash flow."""

    if price <= 0 or payoff <= 0 or maturity_date <= settlement_date:
        raise ValueError("Flujos o fechas invalidas para calcular TIR")
    actual_days = (maturity_date - settlement_date).days
    return (payoff / price) ** (365.0 / actual_days) - 1.0


def calculate_curve_node(
    terms: InstrumentTerms,
    price_per_vn_100: float,
    market_date: date,
    tamar_private_tna: Mapping[date, float],
    calendar: BankBusinessCalendar,
    forecast_tna_pct: float,
    forecast_method: str,
    settlement_business_days: int = 1,
) -> CurveNode:
    """Value a pure-TAMAR cash flow under an explicit fixing forecast.

    This reports a market-return node conditional on the supplied projection
    for unknown future TAMAR observations. It does not label that assumption
    as an observed or risk-neutral forward TAMAR curve.
    """

    if price_per_vn_100 <= 0:
        raise ValueError(f"Precio invalido para {terms.symbol}")
    fixing_as_of = max(tamar_private_tna)
    window_start = calendar.shift(terms.issue_date, -10)
    window_end = calendar.shift(terms.maturity_date, -10)
    fixing_dates = calendar.business_days_inclusive(window_start, window_end)
    known_dates = [candidate for candidate in fixing_dates if candidate in tamar_private_tna]
    unknown_dates = [candidate for candidate in fixing_dates if candidate > fixing_as_of]
    missing_past = [candidate for candidate in fixing_dates if candidate <= fixing_as_of and candidate not in tamar_private_tna]
    if missing_past:
        raise ValueError(
            f"Faltan {len(missing_past)} fijaciones TAMAR historicas dentro de la ventana de {terms.symbol}"
        )
    if not known_dates:
        raise ValueError(f"No hay fijaciones TAMAR conocidas para {terms.symbol}")
    if len(known_dates) + len(unknown_dates) != len(fixing_dates):
        raise AssertionError("Particion de fijaciones inconsistente")

    known_average = fmean(tamar_private_tna[candidate] for candidate in known_dates)
    contractual_average = (
        sum(tamar_private_tna[candidate] for candidate in known_dates)
        + len(unknown_dates) * forecast_tna_pct
    ) / len(fixing_dates)
    monthly_rate = tamar_tem(contractual_average, terms.margin_tna_pct)
    settlement = calendar.shift(market_date, settlement_business_days)
    contractual_days = days_30_360_us(terms.issue_date, terms.maturity_date)
    terminal_value = VN_BASE * (1.0 + monthly_rate) ** (contractual_days / 30.0)
    tir_tea = single_cashflow_xirr(price_per_vn_100, terminal_value, settlement, terms.maturity_date)
    actual_days = (terms.maturity_date - settlement).days
    tir_tna = (365.0 / actual_days) * ((1.0 + tir_tea) ** (actual_days / 365.0) - 1.0)
    tir_tem = (1.0 + tir_tea) ** (30.0 / 360.0) - 1.0
    macauley_duration = actual_days / 365.0
    modified_duration = macauley_duration / (1.0 + tir_tea)
    if not all(math.isfinite(value) for value in (terminal_value, tir_tea, tir_tna, tir_tem)):
        raise ValueError(f"Resultado no finito para {terms.symbol}")
    return CurveNode(
        symbol=terms.symbol,
        instrument_type=terms.instrument_type,
        issue_date=terms.issue_date,
        maturity_date=terms.maturity_date,
        settlement_date=settlement,
        price_per_vn_100=price_per_vn_100,
        margin_tna_pct=terms.margin_tna_pct,
        fixing_window_start=window_start,
        fixing_window_end=window_end,
        fixing_as_of=fixing_as_of,
        total_fixings=len(fixing_dates),
        known_fixings=len(known_dates),
        projected_fixings=len(unknown_dates),
        known_average_tna_pct=known_average,
        projected_tna_pct=forecast_tna_pct,
        contractual_tamar_average_tna_pct=contractual_average,
        tamar_tem_pct=monthly_rate * 100.0,
        terminal_value_per_vn_100=terminal_value,
        days_30_360=contractual_days,
        tir_tea_pct=tir_tea * 100.0,
        tir_tna_pct=tir_tna * 100.0,
        tir_tem_pct=tir_tem * 100.0,
        macauley_duration_years=macauley_duration,
        modified_duration_years=modified_duration,
        forecast_method=forecast_method,
    )
