"""Daily, source-auditable data feed for the Eco Go rates monitor.

This module produces data only. A separate static HTML can consume
``output/latest.json`` without a web server.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import json
import math
import re
import time
from pathlib import Path
from statistics import fmean
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.breakeven.calendar import MarketCalendar
from src.breakeven.fixed_rate import fixed_leg_metrics
from src.breakeven.sources_bcra import fetch_cer, fetch_variable
from src.breakeven.sources_rava import fetch_rava_bond_prices
from src.common.fixed_income import hard_dollar_symbols
from src.common.hard_dollar_curve import build_hard_dollar_metrics
from src.ingest.rava import fetch_rava_hard_dollar_prices, merge_rava_price_history
from src.tamar_curve.calendar import estimate_argentine_national_holidays, make_bank_calendar
from src.tamar_curve.model import InstrumentTerms, calculate_curve_node
from src.tamar_curve.sources import fetch_bcra_bank_holidays


ROOT = Path(__file__).resolve().parents[1]
A3_BASE = "https://api.marketdata.mae.com.ar/api/"
BCRA_BASE = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/"
CALENDAR_PATH = ROOT / "config/calendars/ar_market_calendar_2025_2026.csv"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


HISTORY_TEXT_FIELDS = {"symbol", "family", "maturity_date", "settlement_date"}
# Lo que la página compara contra fechas previas: rendimientos, plazo y precio.
HISTORY_NUMERIC_FIELDS = {
    "yield_tea_pct", "yield_tem_pct", "real_yield_tea_pct", "nominal_yield_tea_pct_if_known",
    "tir_tea_pct", "tir_tna_pct", "tir_tem_pct", "usd_equivalent_yield_tea_pct", "modified_duration_years",
    "parity_pct", "price_ars_per_vn100", "price_per_vn_100", "price_usd_equivalent_per_vn100", "price_usd_dirty_per_vn100",
}
HISTORY_MAX_DAYS = 400


def _compact_history_row(row: dict) -> dict:
    compact = {}
    for key, value in row.items():
        if key in HISTORY_TEXT_FIELDS:
            compact[key] = value
        elif (key in HISTORY_NUMERIC_FIELDS and isinstance(value, (int, float))
              and not isinstance(value, bool) and math.isfinite(value)):
            compact[key] = round(float(value), 4)
    return compact


def _history_for_html(payload: dict, max_days: int = HISTORY_MAX_DAYS) -> dict:
    """Earlier snapshots, reduced to identifiers and numbers, for curve comparisons in the page."""
    current = date.fromisoformat(payload["meta"]["market_date"])
    snapshots = {}
    for path in sorted((ROOT / "output/history").glob("*.json")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not 0 < (current - day).days <= max_days:
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshots[day.isoformat()] = {
            "backfill": bool(snapshot.get("meta", {}).get("backfill")),
            "curves": {group: [_compact_history_row(row) for row in rows]
                       for group, rows in snapshot.get("curves", {}).items()},
            "money_market": {key: {"date": value.get("date"), "tna_pct": value.get("tna_pct")}
                             for key, value in snapshot.get("money_market", {}).items() if isinstance(value, dict)},
        }
    return {"dates": sorted(snapshots), "snapshots": snapshots}


def _publish_static_html(payload: dict) -> bool:
    """Fill Claude's template when present; this pipeline owns no page markup."""
    template = ROOT / "site/template.html"
    if not template.exists():
        return False
    markup = template.read_text(encoding="utf-8")
    token = "__MONITOR_DATA_JSON__"
    history_token = "__MONITOR_HISTORY_JSON__"
    if markup.count(token) != 1:
        raise ValueError(f"site/template.html debe contener {token} exactamente una vez")
    if markup.count(history_token) > 1:
        raise ValueError(f"site/template.html debe contener {history_token} a lo sumo una vez")
    as_script = lambda value, **kw: json.dumps(value, ensure_ascii=False, allow_nan=False, **kw).replace("<", "\\u003c")
    if history_token in markup:
        markup = markup.replace(history_token, as_script(_history_for_html(payload), separators=(",", ":")))
    output = ROOT / "index.html"  # en la raíz: es lo primero que se ve al abrir la carpeta
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(markup.replace(token, as_script(payload)), encoding="utf-8")
    temporary.replace(output)
    return True


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _validate_registry(registry: dict, tamar_registry: dict) -> None:
    entries = [entry for family in ("fixed", "cer", "dollar_linked") for entry in registry[family]]
    entries += [entry for entry in tamar_registry["instruments"] if entry.get("include_in_curve")]
    symbols = [str(entry["symbol"]).upper() for entry in entries]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Hay tickers duplicados entre familias")
    for entry in entries:
        maturity = date.fromisoformat(entry["maturity_date"])
        if "issue_date" in entry and date.fromisoformat(entry["issue_date"]) >= maturity:
            raise ValueError(f"Fechas contractuales inválidas: {entry['symbol']}")
        if not (entry.get("terms_source") or entry.get("terms_sources")):
            raise ValueError(f"Falta fuente de condiciones: {entry['symbol']}")
        if entry in registry["fixed"] and not 0 <= float(entry["tem_decimal"]) < 1:
            raise ValueError(f"TEM de emisión inválida: {entry['symbol']}")
        if entry in registry["cer"] and float(entry["cer_base_index"]) <= 0:
            raise ValueError(f"CER base inválido: {entry['symbol']}")


def _get_a3(path: str, params: dict | None = None) -> object:
    response = requests.get(
        A3_BASE + path,
        params=params,
        headers={"Origin": "https://marketdata.mae.com.ar", "Referer": "https://marketdata.mae.com.ar/"},
        timeout=(5, 30),
    )
    response.raise_for_status()
    return response.json()


def _fetch_quotes(symbols: set[str], market_date: date) -> tuple[dict[str, dict], dict[str, str]]:
    quotes: dict[str, dict] = {}
    errors: dict[str, str] = {}

    def one(symbol: str) -> tuple[str, dict | None, str | None]:
        try:
            frame = fetch_rava_bond_prices([symbol], as_of=market_date)
            if frame.empty:
                return symbol, None, "Sin precio"
            row = frame.sort_values("date").iloc[-1]
            quoted = row["date"]
            if quoted != market_date:
                return symbol, None, f"Cotización de {quoted}, se esperaba {market_date}"
            return symbol, {
                "price": float(row["price"]),
                "volume_nominal": float(row["volume"]),
                "market_date": quoted.isoformat(),
                "source_url": f"https://www2.rava.com/perfil/{symbol}",
            }, None
        except Exception as exc:
            return symbol, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in as_completed({pool.submit(one, symbol): symbol for symbol in symbols}):
            symbol, quote, error = future.result()
            if quote is not None:
                quotes[symbol] = quote
            else:
                errors[symbol] = error or "Sin cotización"
    return quotes, errors


def _money_market(market_date: date) -> tuple[dict, dict]:
    request_range = {"fechaDesde": market_date.isoformat(), "fechaHasta": market_date.isoformat()}
    repo_raw = _get_a3("mercado/repo", {"oRueda": json.dumps(request_range, separators=(",", ":"))})
    caucion_raw = _get_a3("mercado/titulo/historicocauciones", {"oTitulo": json.dumps(request_range, separators=(",", ":"))})
    if not isinstance(repo_raw, list) or not isinstance(caucion_raw, list):
        raise ValueError("A3 devolvió un formato inesperado")
    # La "tasa a un día" es la de la próxima rueda hábil: plazo 003 un viernes, más si hay feriado.
    calendar = MarketCalendar.from_csv(CALENDAR_PATH)
    tenor = (calendar.next_business_day(market_date, 1) - market_date).days
    plazo = f"{tenor:03d}"
    repo_details = [r for day in repo_raw if str(day.get("fecha", ""))[:10] == market_date.isoformat() for r in day.get("details", [])]
    cauc_details = [r for day in caucion_raw if str(day.get("fecha", ""))[:10] == market_date.isoformat() for r in day.get("details", [])]
    a3_rows = []
    for row in repo_details:
        if row.get("moneda") != "$" or row.get("plazo") != plazo:
            continue
        if row.get("rueda") not in {"REPO", "SIMU"}:
            continue
        a3_rows.append({
            "series": "repo_1d" if row["rueda"] == "REPO" else "simu_1d",
            "date": market_date.isoformat(), "tna_pct": row.get("tasaPP"),
            "last_tna_pct": row.get("ultimaTasa"), "volume_ars": row.get("volumen"),
            "operations": row.get("cantOperaciones"), "tenor_days": tenor,
            "source": "A3 Mercado Data", "source_url": "https://marketdata.mae.com.ar/repo/historico",
        })
    for row in cauc_details:
        if row.get("moneda") == "$" and row.get("plazo") == plazo and row.get("ticker") == "CAARS":
            a3_rows.append({
                "series": "caucion_1d", "date": market_date.isoformat(),
                "tna_pct": row.get("tasaPP"), "last_tna_pct": row.get("ultimaTasa"),
                "volume_ars": row.get("montoConcertado"), "tenor_days": tenor,
                "source": "A3 Mercado Data", "source_url": "https://marketdata.mae.com.ar/cauciones/historico",
            })
    raw = {"repo": repo_raw, "cauciones": caucion_raw}
    return {row["series"]: row for row in a3_rows}, raw


def _bcra_series(variable: int, market_date: date, lookback_days: int = 45) -> tuple[dict, list[dict]]:
    frame = fetch_variable(variable, market_date - timedelta(days=lookback_days), market_date)
    frame = frame[frame["date"] <= market_date]
    if frame.empty:
        raise ValueError(f"BCRA variable {variable}: serie vacía")
    row = frame.sort_values("date").iloc[-1]
    return {
        "date": row["date"].isoformat(), "tna_pct": float(row["value"]),
        "source": "BCRA", "source_url": BCRA_BASE + str(variable),
        "variable_id": variable,
    }, _records(frame)


def _fixed_nodes(entries: list[dict], quotes: dict[str, dict], market_date: date, calendar: MarketCalendar) -> list[dict]:
    rows = []
    settlement = calendar.next_business_day(market_date, 1)
    for entry in entries:
        symbol = entry["symbol"]
        if symbol not in quotes or date.fromisoformat(entry["maturity_date"]) <= settlement:
            continue
        maturity = date.fromisoformat(entry["maturity_date"])
        payment = calendar.next_business_day(maturity, 0)
        quote = quotes[symbol]
        metrics = fixed_leg_metrics(
            price=quote["price"], issue_date=date.fromisoformat(entry["issue_date"]),
            maturity_date=maturity, settlement_date=settlement, payment_date=payment,
            annual_rate=float(entry["tem_decimal"]),
        )
        rows.append({
            "symbol": symbol, "family": entry["family"], "maturity_date": maturity.isoformat(),
            "settlement_date": settlement.isoformat(), "price_ars_per_vn100": quote["price"],
            "volume_nominal": quote["volume_nominal"], "issue_tem_pct": entry["tem_decimal"] * 100,
            "technical_price": metrics["technical_price"], "parity_pct": metrics["parity"],
            "yield_tea_pct": metrics["tea"] * 100, "yield_tem_pct": metrics["tem"] * 100,
            "modified_duration_years": metrics["modified_duration"],
            "terms_source": entry["terms_source"], "price_source_url": quote["source_url"],
        })
    return sorted(rows, key=lambda row: (row["maturity_date"], row["symbol"]))


def _cer_nodes(entries: list[dict], quotes: dict[str, dict], market_date: date, calendar: MarketCalendar, cer: pd.DataFrame) -> list[dict]:
    settlement = calendar.next_business_day(market_date, 1)
    known = cer[cer["date"] <= settlement].sort_values("date")
    if known.empty:
        raise ValueError("No hay CER BCRA disponible para la fecha de liquidación")
    cer_row = known.iloc[-1]
    cer_value = float(cer_row["cer_index"])
    rows = []
    for entry in entries:
        symbol = entry["symbol"]
        maturity = date.fromisoformat(entry["maturity_date"])
        if symbol not in quotes or maturity <= settlement or not entry.get("zero_coupon"):
            continue
        quote = quotes[symbol]
        base = float(entry["cer_base_index"])
        technical = 100 * cer_value / base
        years = (maturity - settlement).days / 365
        real_tea = (technical / quote["price"]) ** (1 / years) - 1
        if not math.isfinite(real_tea):
            continue
        target = calendar.add_business_days(maturity, -10)
        target_values = cer[cer["date"] == target]
        known_payoff = None
        nominal_tea = None
        if not target_values.empty:
            known_payoff = 100 * float(target_values.iloc[-1]["cer_index"]) / base
            nominal_tea = (known_payoff / quote["price"]) ** (1 / years) - 1
        rows.append({
            "symbol": symbol, "family": entry["family"], "maturity_date": maturity.isoformat(),
            "settlement_date": settlement.isoformat(), "price_ars_per_vn100": quote["price"],
            "volume_nominal": quote["volume_nominal"], "cer_base_index": base,
            "cer_reference_date": cer_row["date"].isoformat(), "cer_reference_value": cer_value,
            "technical_price": technical, "parity_pct": quote["price"] / technical * 100,
            "real_yield_tea_pct": real_tea * 100,
            "cer_target_date": target.isoformat(), "known_nominal_payoff_per_vn100": known_payoff,
            "nominal_yield_tea_pct_if_known": nominal_tea * 100 if nominal_tea is not None else None,
            "modified_duration_years": years / (1 + real_tea),
            "yield_method": "zero_coupon_real_CER_proxy; contractual_nominal_yield_if_target_CER_known",
            "terms_source": entry["terms_source"],
            "price_source_url": quote["source_url"],
        })
    return sorted(rows, key=lambda row: (row["maturity_date"], row["symbol"]))


def _dollar_linked_nodes(entries: list[dict], quotes: dict[str, dict], market_date: date, calendar: MarketCalendar, fx: dict) -> list[dict]:
    settlement = calendar.next_business_day(market_date, 1)
    rows = []
    for entry in entries:
        symbol = entry["symbol"]
        maturity = date.fromisoformat(entry["maturity_date"])
        if symbol not in quotes or maturity <= settlement or not entry.get("zero_coupon"):
            continue
        quote = quotes[symbol]
        usd_price = quote["price"] / fx["value"]
        years = (maturity - settlement).days / 365
        tea = (100 / usd_price) ** (1 / years) - 1
        rows.append({
            "symbol": symbol, "family": entry["family"], "maturity_date": maturity.isoformat(),
            "settlement_date": settlement.isoformat(), "price_ars_per_vn100_usd": quote["price"],
            "price_usd_equivalent_per_vn100": usd_price, "volume_nominal": quote["volume_nominal"],
            "fx_a3500_date": fx["date"], "fx_a3500_ars_per_usd": fx["value"],
            "usd_equivalent_yield_tea_pct": tea * 100,
            "modified_duration_years": years / (1 + tea),
            "yield_method": "zero_coupon_USD_equivalent_at_latest_A3500",
            "terms_source": entry["terms_source"], "price_source_url": quote["source_url"],
        })
    return sorted(rows, key=lambda row: (row["maturity_date"], row["symbol"]))


def _tamar_nodes(entries: list[dict], quotes: dict[str, dict], market_date: date, tamar_frame: pd.DataFrame) -> tuple[list[dict], list[str]]:
    series = {row.date: float(row.value) for row in tamar_frame.itertuples(index=False) if row.date <= market_date}
    if not series:
        raise ValueError("TAMAR BCRA vacía")
    latest = max(series)
    max_maturity = max(date.fromisoformat(entry["maturity_date"]).year for entry in entries)
    holidays = {}
    warnings = []
    for year in range(latest.year, max_maturity + 1):
        try:
            holidays[year] = fetch_bcra_bank_holidays(year).keys()
        except Exception:
            holidays[year] = estimate_argentine_national_holidays(year).keys()
            warnings.append(f"Calendario bancario {year} estimado")
    bank_calendar = make_bank_calendar(series, holidays)
    forecast = fmean(series[day] for day in sorted(series)[-5:])
    rows = []
    for entry in entries:
        symbol = entry["symbol"]
        if symbol not in quotes or date.fromisoformat(entry["maturity_date"]) <= market_date:
            continue
        terms = InstrumentTerms(
            symbol=symbol, issue_date=date.fromisoformat(entry["issue_date"]),
            maturity_date=date.fromisoformat(entry["maturity_date"]),
            margin_tna_pct=float(entry["margin_tna_pct"]), instrument_type=entry["instrument_type"],
            terms_sources=tuple(entry["terms_sources"]),
        )
        node = calculate_curve_node(terms, quotes[symbol]["price"], market_date, series,
                                    bank_calendar, forecast, "trailing_5_published_fixings")
        row = node.as_dict()
        row["volume_nominal"] = quotes[symbol]["volume_nominal"]
        row["price_source_url"] = quotes[symbol]["source_url"]
        rows.append(row)
    return sorted(rows, key=lambda row: (row["maturity_date"], row["symbol"])), warnings


def _hard_dollar_nodes(market_date: date) -> tuple[list[dict], dict[str, str]]:
    symbols = hard_dollar_symbols()
    fresh, failures = fetch_rava_hard_dollar_prices(symbols, timeout_seconds=20)
    fresh = fresh[pd.to_datetime(fresh["date"]).dt.date <= market_date].copy()
    history_path = ROOT / "data/history/hard_dollar_prices.csv"
    # The original curve code handles contract cash flows, amortization and dirty prices.
    history = merge_rava_price_history(history_path, fresh)
    valid = history[pd.to_datetime(history["date"]).dt.date <= market_date].copy()
    temp_path = ROOT / "data/raw" / market_date.isoformat() / "hard_dollar_prices_for_valuation.csv"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    valid.to_csv(temp_path, index=False)
    _, latest, _ = build_hard_dollar_metrics(
        temp_path, ROOT / "data/reference/hard_dollar_metadata.csv",
        ROOT / "data/reference/hard_dollar_flows.csv", CALENDAR_PATH,
    )
    if latest.empty:
        return [], failures
    latest = latest[pd.to_datetime(latest["date"]).dt.date == market_date].copy()
    rows = []
    for row in _records(latest):
        rows.append({
            "symbol": row["symbol"], "family": row["family"],
            "maturity_date": row["maturity_date"][:10], "settlement_date": row["settlement_date"][:10],
            "price_usd_dirty_per_vn100": row["price"], "volume_nominal": row["volume"],
            "technical_price": row["technical_price"], "parity_pct": row["parity"],
            "yield_tea_pct": row["tir"] * 100, "duration_macaulay_years": row["duration"],
            "modified_duration_years": row["modified_duration"],
            "cashflow_source": row["schedule_source"],
            "price_source_url": f"https://www.rava.com/perfil/{row['symbol']}",
        })
    return sorted(rows, key=lambda row: (row["family"], row["maturity_date"], row["symbol"])), failures


def run(market_date: date, root: Path = ROOT, *, publish: bool = True, quote_fetcher=None) -> dict:
    """Build one market date. ``publish=False`` writes only its history snapshot (backfill)."""
    if root != ROOT:
        raise ValueError("Esta versión usa la raíz del repositorio")
    registry = json.loads((ROOT / "config/market_instruments.json").read_text(encoding="utf-8"))
    tamar_registry = json.loads((ROOT / "config/tamar_instruments.json").read_text(encoding="utf-8"))
    _validate_registry(registry, tamar_registry)
    calendar = MarketCalendar.from_csv(CALENDAR_PATH)
    active = lambda entry: date.fromisoformat(entry["maturity_date"]) > market_date
    all_terms = [entry for family in ("fixed", "cer", "dollar_linked") for entry in registry[family] if active(entry)]
    active_tamar = [entry for entry in tamar_registry["instruments"] if entry.get("include_in_curve") and active(entry)]
    quotes, errors = (quote_fetcher or _fetch_quotes)({entry["symbol"] for entry in all_terms + active_tamar}, market_date)
    raw_dir = ROOT / "data/raw" / market_date.isoformat()
    _write_json(raw_dir / "rava_quotes.json", {"quotes": quotes, "errors": errors})
    money, a3_raw = _money_market(market_date)
    _write_json(raw_dir / "a3_money_market.json", a3_raw)
    tamar_rate, tamar_raw = _bcra_series(44, market_date)
    bank_rate, bank_raw = _bcra_series(145, market_date)
    fx_frame = fetch_variable(5, market_date - timedelta(days=10), market_date)
    if fx_frame.empty:
        raise ValueError("BCRA A3500 vacía")
    fx_row = fx_frame.iloc[-1]
    fx = {"date": fx_row["date"].isoformat(), "value": float(fx_row["value"]), "source_url": BCRA_BASE + "5"}
    cer = fetch_cer(market_date - timedelta(days=90), market_date + timedelta(days=60))
    _write_json(raw_dir / "bcra_reference.json", {"tamar": tamar_raw, "bank_lending": bank_raw,
                                                    "fx_a3500": _records(fx_frame), "cer": _records(cer)})
    tamar_full = fetch_variable(44, date(2025, 1, 1), market_date)
    tamar_nodes, tamar_warnings = _tamar_nodes(active_tamar, quotes, market_date, tamar_full)
    hard_nodes, hard_errors = _hard_dollar_nodes(market_date)
    money["tamar_private"] = {"series": "tamar_private", **tamar_rate}
    money["bank_lending_1_7d_10m"] = {"series": "bank_lending_1_7d_10m", **bank_rate}
    curves = {
        "fixed": _fixed_nodes(registry["fixed"], quotes, market_date, calendar),
        "cer": _cer_nodes(registry["cer"], quotes, market_date, calendar, cer),
        "tamar": tamar_nodes,
        "dollar_linked": _dollar_linked_nodes(registry["dollar_linked"], quotes, market_date, calendar, fx),
        "hard_dollar": hard_nodes,
    }
    if not any(curves.values()):
        # Típico de una corrida antes del cierre o de una rueda que Rava todavía no actualizó:
        # no se guarda ni se publica un monitor vacío encima del último válido.
        raise ValueError(f"Sin cotizaciones Rava de {market_date}; no se publica")
    missing_money = sorted(set(["repo_1d", "simu_1d", "caucion_1d"]) - money.keys())
    missing_hard = sorted(set(hard_dollar_symbols()) - {row["symbol"] for row in hard_nodes})
    missing_bonds = sorted(symbol for symbol in errors if symbol in {entry["symbol"] for entry in all_terms + active_tamar})
    warnings = tamar_warnings + [f"Falta {item} en A3" for item in missing_money]
    if missing_hard:
        warnings.append("Hard dollar sin precio de fecha: " + ", ".join(missing_hard))
    if missing_bonds:
        warnings.append("Rava sin precio de fecha: " + ", ".join(missing_bonds))
    payload = {
        "schema_version": "1.0", "meta": {
            "market_date": market_date.isoformat(),
            "generated_at": datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).isoformat(),
            "status": "complete" if not missing_money and not missing_bonds and not missing_hard else "partial",
            "registry_version": registry["registry_version"],
            "rate_units": "pct; annual rates TEA unless field says TNA or TEM",
            **({} if publish else {"backfill": True}),
        },
        "curves": curves, "money_market": money,
        "quality": {"warnings": warnings, "rava_errors": errors, "hard_dollar_fetch_errors": hard_errors,
                    "missing_money_market": missing_money, "missing_hard_dollar": missing_hard},
    }
    _write_json(ROOT / "output/history" / f"{market_date.isoformat()}.json", payload)
    if publish:
        _write_json(ROOT / "output/latest.json", payload)
        _publish_static_html(payload)
    return payload


def pending_closes(payload: dict) -> list[str]:
    """Especies que cotizaron hace pocos días pero todavía sin cierre de la fecha en Rava.

    A las 17:30 Rava a veces no consolidó el cierre de parte de las especies (pasó el
    28/09, 1/10, 5/10 y 13/10 de 2026). Una especie sin operaciones desde hace semanas
    (p. ej. D10Y7) no cuenta: reintentar no la va a traer.
    """
    market_date = date.fromisoformat(payload["meta"]["market_date"])
    pending = set(payload["quality"].get("missing_hard_dollar", []))
    for symbol, message in payload["quality"].get("rava_errors", {}).items():
        quoted = re.search(r"(\d{4}-\d{2}-\d{2}), se esperaba", str(message))
        if quoted and (market_date - date.fromisoformat(quoted.group(1))).days <= 7:
            pending.add(symbol)
    return sorted(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el feed JSON diario del monitor de tasas")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="Fecha de mercado YYYY-MM-DD")
    parser.add_argument("--retry-until", type=lambda value: datetime.strptime(value, "%H:%M").time(), default=None,
                        help="HH:MM. Si faltan cierres del día en Rava, reintenta y republica hasta esa hora")
    parser.add_argument("--retry-every", type=int, default=20, help="Minutos entre reintentos")
    args = parser.parse_args()
    tz = ZoneInfo("America/Argentina/Buenos_Aires")
    today = datetime.now(tz).date()
    market_date = args.date or today
    while True:
        try:
            result, error = run(market_date), None
            pending = pending_closes(result)
        except ValueError as exc:
            if not str(exc).startswith("Sin cotizaciones Rava"):
                raise
            result, error, pending = None, exc, ["todas"]
        next_try = datetime.now(tz) + timedelta(minutes=args.retry_every)
        if not pending or args.retry_until is None or next_try.time() > args.retry_until:
            break
        print(f"{datetime.now(tz):%H:%M} Rava todavía sin cierre de {market_date} para: {', '.join(pending)}. "
              f"Reintento a las {next_try:%H:%M}.", flush=True)
        time.sleep(args.retry_every * 60)
    if result is None:
        raise error
    print(json.dumps({"market_date": market_date.isoformat(), "status": result["meta"]["status"],
                      "counts": {key: len(value) for key, value in result["curves"].items()},
                      "money_market": sorted(result["money_market"]),
                      "warnings": result["quality"]["warnings"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
