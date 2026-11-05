"""Nominal trading volumes and explicitly estimated turnover for monitored bonds."""
import math


def _nonnegative(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


PRICE_KEYS = ("price_ars_per_vn100", "price_per_vn_100", "price_ars_per_vn100_usd", "price_usd_dirty_per_vn100")


def turnover_estimate(row: dict):
    """VN negociado × precio de cierre / 100, en la moneda de negociación; None si falta un dato."""
    price_key = next((key for key in PRICE_KEYS if key in row), None)
    volume = _nonnegative(row.get("volume_nominal"))
    price = _nonnegative(row.get(price_key))
    return volume * price / 100 if volume is not None and price is not None else None


def add_volume_data(curves: dict, market_date: str, expected_symbols=()) -> dict:
    """Enrich rows, then aggregate within matching nominal and trading currencies.

    Rava supplies nominal volume. Closing price * VN / 100 is an estimate of
    turnover, not the sum of cash amounts actually traded throughout the day.
    """
    instruments = []
    seen = set()
    for group, rows in curves.items():
        for row in rows:
            if row["symbol"] in seen:
                raise ValueError(f"Volumen duplicado: {row['symbol']}")
            seen.add(row["symbol"])
            nominal_currency = row.get("nominal_currency", "USD" if group in {"hard_dollar", "dollar_linked"} else "ARS")
            trading_currency = "USD" if group == "hard_dollar" else "ARS"
            volume = _nonnegative(row.get("volume_nominal"))
            estimate = turnover_estimate(row)
            row.update({"market_date": market_date, "volume_nominal": volume,
                        "nominal_currency": nominal_currency, "trading_currency": trading_currency,
                        "turnover_at_close_estimate": estimate,
                        "turnover_method": "nominal_volume_times_closing_price_divided_by_100"})
            instruments.append({key: row[key] for key in ("symbol", "market_date", "volume_nominal", "nominal_currency",
                                                         "trading_currency", "turnover_at_close_estimate", "turnover_method")})
            instruments[-1].update({"curve_group": group, "family": row.get("family", row.get("instrument_type", group)),
                                    "source_url": row.get("price_source_url")})

    def aggregate(key):
        buckets = {}
        for row in instruments:
            identity = (row[key], row["nominal_currency"], row["trading_currency"])
            bucket = buckets.setdefault(identity, {key: identity[0], "nominal_currency": identity[1],
                "trading_currency": identity[2], "instrument_count": 0, "volume_observed_count": 0,
                "turnover_observed_count": 0, "volume_nominal": 0.0, "turnover_at_close_estimate": 0.0,
                "missing_volume_symbols": []})
            bucket["instrument_count"] += 1
            if row["volume_nominal"] is None:
                bucket["missing_volume_symbols"].append(row["symbol"])
            else:
                bucket["volume_observed_count"] += 1
                bucket["volume_nominal"] += row["volume_nominal"]
            if row["turnover_at_close_estimate"] is not None:
                bucket["turnover_observed_count"] += 1
                bucket["turnover_at_close_estimate"] += row["turnover_at_close_estimate"]
        for bucket in buckets.values():
            if not bucket["volume_observed_count"]:
                bucket["volume_nominal"] = None
            if not bucket["turnover_observed_count"]:
                bucket["turnover_at_close_estimate"] = None
        return [buckets[key] for key in sorted(buckets)]

    return {"market_date": market_date, "scope": "priced_curve_instruments_in_monitor_registry; not_total_market",
            "turnover_method": "nominal_volume_times_closing_price_divided_by_100; estimate_not_actual_traded_amount",
            "instruments": sorted(instruments, key=lambda row: row["symbol"]),
            "by_curve_group": aggregate("curve_group"), "by_type": aggregate("family"),
            "missing_price_symbols": sorted(set(expected_symbols) - seen),
            "missing_volume_symbols": sorted(row["symbol"] for row in instruments if row["volume_nominal"] is None)}
