from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests

from src.common.fixed_income import hard_dollar_metadata_frame


BONISTAS_URL_TEMPLATE = "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/{symbol}"
NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>')


@dataclass(frozen=True)
class BonistasFetchResult:
    symbol: str
    source_url: str
    issue_date: pd.Timestamp
    maturity_date: pd.Timestamp
    description: str
    tir_reference: float | None
    modified_duration_reference: float | None
    parity_reference: float | None
    technical_value_reference: float | None
    price_reference: float | None
    schedule_rows: list[dict[str, object]]


def fetch_hard_dollar_reference(symbols: list[str] | None = None, timeout_seconds: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    metadata = hard_dollar_metadata_frame()
    if symbols is not None:
        selected = {str(symbol).strip().upper() for symbol in symbols}
        metadata = metadata[metadata["symbol"].isin(selected)].copy()
    if metadata.empty:
        return pd.DataFrame(), pd.DataFrame()

    metadata_rows: list[dict[str, object]] = []
    flow_rows: list[dict[str, object]] = []
    for row in metadata.itertuples(index=False):
        fetched = fetch_bonistas_bond_data(row.symbol, timeout_seconds=timeout_seconds)
        metadata_rows.append(
            {
                "symbol": fetched.symbol,
                "source_url": fetched.source_url,
                "issue_date": fetched.issue_date,
                "maturity_date": fetched.maturity_date,
                "description": fetched.description,
                "tir_reference": fetched.tir_reference,
                "modified_duration_reference": fetched.modified_duration_reference,
                "parity_reference": fetched.parity_reference,
                "technical_value_reference": fetched.technical_value_reference,
                "price_reference": fetched.price_reference,
            }
        )
        flow_rows.extend(fetched.schedule_rows)

    return pd.DataFrame(metadata_rows), pd.DataFrame(flow_rows)


def fetch_bonistas_bond_data(symbol: str, timeout_seconds: int = 20) -> BonistasFetchResult:
    symbol_key = str(symbol).strip().upper()
    source_url = BONISTAS_URL_TEMPLATE.format(symbol=symbol_key)
    response = requests.get(source_url, timeout=timeout_seconds, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    match = NEXT_DATA_PATTERN.search(response.text)
    if not match:
        raise ValueError(f"No pude encontrar __NEXT_DATA__ para {symbol_key}.")

    payload = json.loads(match.group(1))
    bond_data = payload.get("props", {}).get("pageProps", {}).get("bondData", {})
    if not isinstance(bond_data, dict):
        manual = _manual_hard_dollar_reference(symbol_key)
        if manual is not None:
            return manual
        raise ValueError(f"No encontré bondData estructurado para {symbol_key}.")

    bond = bond_data.get("bond", {})
    if not bond:
        manual = _manual_hard_dollar_reference(symbol_key)
        if manual is not None:
            return manual
        raise ValueError(f"No encontré bondData.bond para {symbol_key}.")

    issue_date = pd.Timestamp(bond.get("start_date")).normalize()
    maturity_date = pd.Timestamp(bond.get("end_date")).normalize()
    description = str(bond.get("description") or "")
    flow = list(bond_data.get("flow_past") or []) + list(bond_data.get("flow") or [])
    if not flow:
        manual = _manual_hard_dollar_reference(symbol_key)
        if manual is not None:
            return manual
        raise ValueError(f"No encontré cashflows en Bonistas para {symbol_key}.")

    schedule_rows = _build_schedule_rows(symbol_key, flow)
    return BonistasFetchResult(
        symbol=symbol_key,
        source_url=source_url,
        issue_date=issue_date,
        maturity_date=maturity_date,
        description=description,
        tir_reference=_to_optional_float(bond.get("tir")),
        modified_duration_reference=_to_optional_float(bond.get("modified_duration")),
        parity_reference=_to_optional_float(bond.get("parity")),
        technical_value_reference=_to_optional_float(bond.get("tc_value")),
        price_reference=_to_optional_float(bond.get("last_price")),
        schedule_rows=schedule_rows,
    )


def _build_schedule_rows(symbol: str, flow_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in flow_rows:
        payment_date = pd.Timestamp(raw["fecha"]).normalize()
        principal_pct = float(raw.get("principal") or 0.0)
        residual_before_pct = float(raw.get("saldo") or 0.0)
        residual_after_pct = residual_before_pct - principal_pct
        coupon_amount = float(raw.get("cupon") or 0.0)
        if symbol in {"AO27D", "AO28D"}:
            coupon_rate = coupon_amount / residual_before_pct * 12.0 if residual_before_pct > 0 else 0.0
        else:
            coupon_rate = coupon_amount / residual_before_pct * 2.0 if residual_before_pct > 0 else 0.0
        observed_date = _derive_observed_date(symbol, payment_date)
        rows.append(
            {
                "symbol": symbol,
                "observed_date": observed_date,
                "payment_date_reference": payment_date,
                "coupon_rate": coupon_rate,
                "capital_pct": principal_pct,
                "residual_before_pct": residual_before_pct,
                "residual_after_pct": residual_after_pct,
                "coupon_amount_reference": coupon_amount,
                "capital_amount_reference": principal_pct,
                "total_amount_reference": float(raw.get("total") or 0.0),
                "schedule_source": "bonistas_next_data",
            }
        )
    return rows


def _manual_hard_dollar_reference(symbol: str) -> BonistasFetchResult | None:
    symbol_key = str(symbol).strip().upper()
    if symbol_key != "AO28D":
        return None

    issue_date = pd.Timestamp("2026-03-31")
    maturity_date = pd.Timestamp("2028-10-31")
    coupon_rate = 0.06
    residual_before_pct = 100.0
    observed_dates = pd.date_range(issue_date + pd.offsets.MonthEnd(1), maturity_date, freq="ME")
    schedule_rows: list[dict[str, object]] = []
    for observed_date in observed_dates:
        is_final = observed_date.normalize() == maturity_date.normalize()
        capital_pct = 100.0 if is_final else 0.0
        residual_after_pct = residual_before_pct - capital_pct
        coupon_amount = residual_before_pct * coupon_rate * (30.0 / 360.0)
        total_amount = coupon_amount + capital_pct
        schedule_rows.append(
            {
                "symbol": symbol_key,
                "observed_date": observed_date.normalize(),
                "payment_date_reference": observed_date.normalize(),
                "coupon_rate": coupon_rate,
                "capital_pct": capital_pct,
                "residual_before_pct": residual_before_pct,
                "residual_after_pct": residual_after_pct,
                "coupon_amount_reference": coupon_amount,
                "capital_amount_reference": capital_pct,
                "total_amount_reference": total_amount,
                "schedule_source": "manual_monthly_coupon_6pct",
            }
        )
        residual_before_pct = residual_after_pct

    return BonistasFetchResult(
        symbol=symbol_key,
        source_url="https://iol.invertironline.com/titulo/cotizacion/BCBA/AO28D/",
        issue_date=issue_date.normalize(),
        maturity_date=maturity_date.normalize(),
        description="AO28D - Bono Tesoro Nacional 6% 31/10/28 USD. Referencia manual temporal hasta contar con flujo estructurado público.",
        tir_reference=None,
        modified_duration_reference=None,
        parity_reference=None,
        technical_value_reference=None,
        price_reference=None,
        schedule_rows=schedule_rows,
    )


def _derive_observed_date(symbol: str, payment_date: pd.Timestamp) -> pd.Timestamp:
    symbol_key = str(symbol).strip().upper()
    if symbol_key in {"AL29D", "AL30D", "AL35D", "AE38D", "AL41D", "GD29D", "GD30D", "GD35D", "GD38D", "GD41D", "GD46D"}:
        day = 9
        month = 1 if payment_date.month == 1 or payment_date.month == 7 and payment_date.day <= 15 else 7
        if payment_date.month == 7:
            month = 7
        elif payment_date.month == 1:
            month = 1
        else:
            month = payment_date.month
        return pd.Timestamp(date(payment_date.year, month, day))
    if symbol_key == "AN29D":
        if payment_date.month in {5, 6}:
            return pd.Timestamp(date(payment_date.year, 5, 30))
        return pd.Timestamp(date(payment_date.year, 11, 30))
    return payment_date


def _to_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
