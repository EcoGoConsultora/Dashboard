from __future__ import annotations

from datetime import date

import numpy as np


def days360_excel_us(start: date, end: date) -> int:
    """Excel DAYS360 US/NASD convention."""
    sd = 30 if start.day == 31 else start.day
    if end.day == 31 and sd >= 30:
        ed = 30
    else:
        ed = end.day
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (ed - sd)


def year_fraction(start: date, end: date) -> float:
    return (end - start).days / 365.0


def xnpv(rate: float, cashflows: list[tuple[date, float]]) -> float:
    anchor = min(day for day, _ in cashflows)
    return sum(amount / ((1.0 + rate) ** year_fraction(anchor, day)) for day, amount in cashflows)


def xirr(cashflows: list[tuple[date, float]]) -> float:
    amounts = [amount for _, amount in cashflows]
    if not any(amount > 0 for amount in amounts) or not any(amount < 0 for amount in amounts):
        raise ValueError("XIRR requires at least one positive and one negative cashflow")
    if len(cashflows) == 2:
        ordered = sorted(cashflows, key=lambda item: item[0])
        (start_date, start_amount), (end_date, end_amount) = ordered
        if start_amount < 0 < end_amount:
            years = year_fraction(start_date, end_date)
            return (end_amount / abs(start_amount)) ** (1.0 / years) - 1.0

    low, high = -0.9999, 10.0
    low_value = xnpv(low, cashflows)
    high_value = xnpv(high, cashflows)
    while low_value * high_value > 0 and high < 100:
        high *= 2
        high_value = xnpv(high, cashflows)
    if low_value * high_value > 0:
        raise ValueError("Could not bracket XIRR")

    for _ in range(160):
        mid = (low + high) / 2.0
        mid_value = xnpv(mid, cashflows)
        if abs(mid_value) < 1e-10:
            return mid
        if low_value * mid_value <= 0:
            high = mid
            high_value = mid_value
        else:
            low = mid
            low_value = mid_value
    return (low + high) / 2.0


def fixed_leg_metrics(
    price: float,
    issue_date: date,
    maturity_date: date,
    settlement_date: date,
    payment_date: date,
    annual_rate: float,
) -> dict[str, float | int]:
    periods_to_settlement = days360_excel_us(issue_date, settlement_date) / 30.0
    periods_to_maturity = days360_excel_us(issue_date, maturity_date) / 30.0
    technical_price = 100.0 * (1.0 + annual_rate) ** periods_to_settlement
    payment_amount = 100.0 * (1.0 + annual_rate) ** periods_to_maturity
    tea = xirr([(settlement_date, -price), (payment_date, payment_amount)])
    tem = (1.0 + tea) ** (1.0 / 12.0) - 1.0
    years_to_payment = year_fraction(settlement_date, payment_date)
    return {
        "technical_price": technical_price,
        "payment_amount": payment_amount,
        "parity": price / technical_price * 100.0,
        "tea": tea,
        "tem": tem,
        "modified_duration": years_to_payment / (1.0 + tea),
        "days_360_to_maturity": days360_excel_us(settlement_date, maturity_date),
        "years_to_payment": years_to_payment,
    }
