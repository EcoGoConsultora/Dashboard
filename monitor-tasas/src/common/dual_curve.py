"""Auditable leg metrics for sovereign duals; no option-price model is implied."""
from __future__ import annotations

from datetime import date
import math

from src.tamar_curve.model import InstrumentTerms, calculate_curve_node, days_30_360_us


def _return_metrics(price: float, payoff: float, settlement: date, payment: date) -> dict:
    if price <= 0 or payoff <= 0 or payment <= settlement:
        raise ValueError("Flujos o fechas inválidos para calcular TIR dual")
    years = (payment - settlement).days / 365
    annual_log_return = math.log(payoff / price) / years
    # Near maturity a losing leg's TEA can round to -1. Computing 1 + TEA
    # would then divide by zero even though its discount duration is finite.
    return {"yield_tea_pct": math.expm1(annual_log_return) * 100,
            "yield_tem_pct": math.expm1(annual_log_return / 12) * 100,
            "yield_tna_pct": (payoff / price - 1) / years * 100,
            "duration_macaulay_years": years, "modified_duration_years": years * math.exp(-annual_log_return)}


def build_dual_nodes(entries, quotes, market_date, market_calendar, cer, fx, series, bank_calendar, forecast):
    """Report comparable legs, and a complete nominal yield only with known other payoff.

    The CER and FX leg yields use the current index as a normalization, like the
    pure curves. They are not forecasts of nominal cash flows. TAMAR uses the
    explicit trailing-five-fixings scenario; its duration holds that payoff fixed.
    """
    settlement = market_calendar.next_business_day(market_date, 1)
    rows = []
    for entry in entries:
        symbol = entry["symbol"]
        issue, maturity = (date.fromisoformat(entry[key]) for key in ("issue_date", "maturity_date"))
        if symbol not in quotes or issue > settlement or maturity <= settlement:
            continue
        payment = bank_calendar.shift(maturity, 0)
        while not bank_calendar.is_business_day(payment):
            payment = bank_calendar.shift(payment, 1)
        price = quotes[symbol]["price"]
        node = calculate_curve_node(
            InstrumentTerms(symbol, issue, maturity, entry["margin_tna_pct"], entry["family"],
                            tuple(entry["terms_sources"])),
            price, market_date, series, bank_calendar, forecast, "trailing_5_published_fixings",
        )
        # Use the market settlement and adjusted payment for all leg yields.
        multiplier = entry.get("initial_fx_ars_per_usd", 1.0)
        tamar_payoff = node.terminal_value_per_vn_100 * multiplier
        tamar_technical = 100 * multiplier * (1 + node.tamar_tem_pct / 100) ** (days_30_360_us(issue, settlement) / 30)
        tamar_metrics = _return_metrics(price, tamar_payoff, settlement, payment)
        row = {
            "symbol": symbol, "family": entry["family"], "issue_date": issue.isoformat(),
            "maturity_date": maturity.isoformat(), "payment_date": payment.isoformat(),
            "settlement_date": settlement.isoformat(), "market_date": quotes[symbol]["market_date"],
            "price_ars_per_vn100": price, "volume_nominal": quotes[symbol]["volume_nominal"],
            "nominal_currency": entry["nominal_currency"], "terms_sources": entry["terms_sources"],
            "price_source_url": quotes[symbol]["source_url"],
            "payoff_rule": "max_of_contractual_terminal_legs",
            "yield_tea_pct": None, "yield_tem_pct": None, "modified_duration_years": None,
            "terminal_value_per_vn100": None, "selected_leg": None,
            "tamar_payoff_per_vn100": tamar_payoff, "tamar_technical_price": tamar_technical,
            "tamar_parity_pct": price / tamar_technical * 100,
            "tamar_yield_tea_pct": tamar_metrics["yield_tea_pct"],
            "tamar_yield_tem_pct": tamar_metrics["yield_tem_pct"],
            "tamar_yield_tna_pct": tamar_metrics["yield_tna_pct"],
            "tamar_modified_duration_years": tamar_metrics["modified_duration_years"],
            "projected_nominal_floor_yield_tea_pct": tamar_metrics["yield_tea_pct"],
            "margin_tna_pct": entry["margin_tna_pct"],
            **{key: node.as_dict()[key] for key in (
                "fixing_window_start", "fixing_window_end", "fixing_as_of", "total_fixings",
                "known_fixings", "projected_fixings", "known_average_tna_pct", "projected_tna_pct",
                "contractual_tamar_average_tna_pct", "tamar_tem_pct", "forecast_method")},
            "yield_method": "separate_legs; TAMAR_conditional_on_forecast; no_CER_or_FX_forecast",
            "duration_method": "single_cashflow_discount_yield_sensitivity_holding_projected_payoff_fixed",
            "option_valuation": "not_estimated",
        }
        other_payoff = None
        other_leg = None
        if entry["family"] == "DUAL_FIXED_TAMAR":
            monthly = entry["fixed_tem_decimal"]
            other_payoff = 100 * (1 + monthly) ** (days_30_360_us(issue, maturity) / 30)
            technical = 100 * (1 + monthly) ** (days_30_360_us(issue, settlement) / 30)
            metrics = _return_metrics(price, other_payoff, settlement, payment)
            row.update({"fixed_tem_pct": monthly * 100, "fixed_payoff_per_vn100": other_payoff,
                        "fixed_technical_price": technical, "fixed_parity_pct": price / technical * 100,
                        "fixed_yield_tea_pct": metrics["yield_tea_pct"],
                        "fixed_yield_tem_pct": metrics["yield_tem_pct"],
                        "fixed_modified_duration_years": metrics["modified_duration_years"]})
            periods = 365 / 32
            threshold_average = periods * ((1 + monthly) ** (12 / periods) - 1) * 100 - entry["margin_tna_pct"]
            row["tamar_switch_average_tna_pct"] = threshold_average
            row["tamar_switch_future_tna_pct"] = (
                (threshold_average * node.total_fixings - node.known_average_tna_pct * node.known_fixings)
                / node.projected_fixings if node.projected_fixings else None)
            other_leg = "fixed"
        elif entry["family"] == "DUAL_CER_TAMAR":
            base = entry["cer_base_index"]
            reference = cer[cer["date"] <= settlement].sort_values("date").iloc[-1]
            technical = 100 * float(reference["cer_index"]) / base
            metrics = _return_metrics(price, technical, settlement, payment)
            target = bank_calendar.shift(maturity, -10)
            known = cer[cer["date"] == target]
            if not known.empty:
                other_payoff = 100 * float(known.iloc[-1]["cer_index"]) / base
            row.update({"cer_base_date": entry["cer_base_date"], "cer_base_index": base,
                        "cer_target_date": target.isoformat(), "cer_reference_date": reference["date"].isoformat(),
                        "cer_reference_value": float(reference["cer_index"]), "cer_technical_price": technical,
                        "cer_parity_pct": price / technical * 100,
                        "real_yield_tea_pct": metrics["yield_tea_pct"],
                        "cer_modified_duration_years": metrics["modified_duration_years"],
                        "known_cer_payoff_per_vn100": other_payoff,
                        "cer_switch_index": base * tamar_payoff / 100,
                        "cer_switch_monthly_pct": ((tamar_payoff / technical) ** (30 / (target - reference["date"]).days) - 1) * 100
                        if target > reference["date"] else None})
            other_leg = "cer"
        elif entry["family"] == "DUAL_TAMAR_DOLLAR_LINKED":
            technical = 100 * fx["value"]
            metrics = _return_metrics(price, technical, settlement, payment)
            target = bank_calendar.shift(payment, -3)
            if fx["date"] == target.isoformat():
                other_payoff = technical
            row.update({"initial_fx_date": entry["initial_fx_date"], "initial_fx_ars_per_usd": multiplier,
                        "fx_a3500_date": fx["date"], "fx_a3500_ars_per_usd": fx["value"],
                        "fx_target_date": target.isoformat(), "dollar_linked_technical_price": technical,
                        "dollar_linked_parity_pct": price / technical * 100,
                        "price_usd_equivalent_per_vn100": price / fx["value"],
                        "usd_equivalent_yield_tea_pct": metrics["yield_tea_pct"],
                        "dollar_linked_modified_duration_years": metrics["modified_duration_years"],
                        "fx_switch_ars_per_usd": tamar_payoff / 100,
                        "fx_switch_monthly_pct": ((tamar_payoff / technical) ** (30 / (target - date.fromisoformat(fx["date"])).days) - 1) * 100
                        if target > date.fromisoformat(fx["date"]) else None})
            other_leg = "dollar_linked"
        else:
            raise ValueError(f"Familia dual desconocida: {entry['family']}")
        if other_payoff is not None:
            payoff = max(tamar_payoff, other_payoff)
            row.update(_return_metrics(price, payoff, settlement, payment))
            row.update({"terminal_value_per_vn100": payoff,
                        "selected_leg": "tamar" if tamar_payoff > other_payoff else other_leg,
                        "yield_method": "max_contractual_legs; TAMAR_conditional_on_forecast"})
        if any(isinstance(value, float) and not math.isfinite(value) for value in row.values()):
            raise ValueError(f"Resultado dual no finito: {symbol}")
        rows.append(row)
    return sorted(rows, key=lambda row: (row["maturity_date"], row["symbol"]))
