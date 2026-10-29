"""Rebuild earlier market dates in ``output/history`` from Rava's daily closes.

Rava's public profile lists about a year of daily closes per bond. Each rebuilt
date goes through the same valuation as the daily run (``monitor.run``), with
the close of that exact date, and is written only to ``output/history`` with
``meta.backfill = true``; ``output/latest.json`` and the HTML are left alone.
Snapshots saved by a real daily run are kept unless ``--force`` is passed.

    py -3.14 -m src.backfill --start 2026-01-02 --end 2026-09-22
    py -3.14 -m src.backfill --start 2026-01-02 --only-missing   # reintenta fechas que fallaron
    py -3.14 -m src.backfill --start 2026-09-25 --end 2026-09-25 --force --publish

``--publish`` publica la fecha más reciente del rango como monitor del día (``latest.json``
y HTML): es lo que usa ``scripts/run_daily.ps1`` cuando recupera una rueda ya cerrada.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
import json
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src import monitor
from src.breakeven.calendar import MarketCalendar
from src.ingest.rava import parse_rava_profile_prices

RAVA_PESO_PROFILE_URL = "https://www2.rava.com/perfil/{symbol}"
# Especies ya vencidas cuyas condiciones heredadas (legacy:Infla breakeven) no cierran con los
# precios de Rava: TIR de 3% a más de 300% durante semanas y, en S17A6, un vencimiento que no
# coincide con el ticker. Se excluyen de los snapshots reconstruidos hasta verificar sus
# condiciones contra Secretaría de Finanzas / Boletín Oficial.
UNVERIFIED_TERMS = {"S17A6", "S15Y6", "S29Y6", "T30J6"}


def _registry_symbols() -> set[str]:
    registry = json.loads((monitor.ROOT / "config/market_instruments.json").read_text(encoding="utf-8"))
    tamar = json.loads((monitor.ROOT / "config/tamar_instruments.json").read_text(encoding="utf-8"))
    symbols = {entry["symbol"] for family in ("fixed", "cer", "dollar_linked") for entry in registry[family]}
    symbols |= {entry["symbol"] for entry in tamar["instruments"] if entry.get("include_in_curve")}
    return {symbol.upper() for symbol in symbols}


def fetch_peso_histories(symbols: set[str]) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Daily closes per symbol from Rava's profile history table."""

    def one(symbol: str):
        url = RAVA_PESO_PROFILE_URL.format(symbol=symbol)
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(5, 30))
            response.raise_for_status()
            return symbol, parse_rava_profile_prices(response.text, symbol=symbol, source_url=url), None
        except Exception as exc:
            return symbol, None, f"{type(exc).__name__}: {exc}"

    histories, failures = {}, {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for symbol, frame, error in pool.map(one, sorted(symbols)):
            if frame is None:
                failures[symbol] = error
            else:
                histories[symbol] = frame
    return histories, failures


def quotes_on(histories: dict[str, pd.DataFrame], failures: dict[str, str], symbols: set[str], market_date: date):
    """Same output as ``monitor._fetch_quotes``, but only with the close of ``market_date``."""
    quotes, errors = {}, {}
    for symbol in symbols:
        frame = histories.get(symbol)
        if frame is None:
            errors[symbol] = failures.get(symbol, "Sin historia en Rava")
            continue
        rows = frame[pd.to_datetime(frame["date"]).dt.date == market_date]
        if rows.empty:
            errors[symbol] = f"Sin cierre histórico en Rava para {market_date}"
            continue
        row = rows.iloc[-1]
        volume = pd.to_numeric(row["volume"], errors="coerce")
        quotes[symbol] = {
            "price": float(row["price"]),
            "volume_nominal": float(volume) if pd.notna(volume) else None,
            "market_date": market_date.isoformat(),
            "source_url": RAVA_PESO_PROFILE_URL.format(symbol=symbol),
        }
    return quotes, errors


@contextmanager
def _cached_sources(first: date, last: date):
    """Download BCRA series and Rava hard-dollar histories once for the whole range."""
    originals = {name: getattr(monitor, name) for name in
                 ("fetch_variable", "fetch_cer", "fetch_rava_hard_dollar_prices", "fetch_bcra_bank_holidays", "_money_market")}
    start, end = min(first - timedelta(days=120), date(2025, 1, 1)), last + timedelta(days=60)

    @lru_cache(maxsize=None)
    def variable(variable_id: int) -> pd.DataFrame:
        return originals["fetch_variable"](variable_id, start, end)

    @lru_cache(maxsize=None)
    def cer() -> pd.DataFrame:
        return originals["fetch_cer"](start, end)

    @lru_cache(maxsize=None)
    def hard_dollar(symbols: tuple[str, ...]):
        return originals["fetch_rava_hard_dollar_prices"](list(symbols), timeout_seconds=20)

    between = lambda frame, a, b: frame[(frame["date"] >= a) & (frame["date"] <= b)].reset_index(drop=True)
    monitor.fetch_variable = lambda variable_id, a, b: between(variable(variable_id), a, b)
    monitor.fetch_cer = lambda a, b: between(cer(), a, b)
    monitor.fetch_rava_hard_dollar_prices = lambda symbols, timeout_seconds=20: tuple(
        frame.copy() if isinstance(frame, pd.DataFrame) else dict(frame) for frame in hard_dollar(tuple(symbols)))
    monitor.fetch_bcra_bank_holidays = lru_cache(maxsize=None)(originals["fetch_bcra_bank_holidays"])

    def money_market(market_date: date):
        # A3 no sirve historia de REPO/caución anterior a unos siete meses: se guardan
        # igual las curvas y el snapshot queda "partial" con las series A3 faltantes.
        try:
            return originals["_money_market"](market_date)
        except requests.HTTPError as exc:
            return {}, {"error": f"{type(exc).__name__}: {exc}"}
    monitor._money_market = money_market
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(monitor, name, value)


def drop_unverified(day: date) -> None:
    """Remove UNVERIFIED_TERMS from a rebuilt snapshot, leaving a warning."""
    path = monitor.ROOT / "output/history" / f"{day.isoformat()}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("meta", {}).get("backfill"):
        return
    dropped = sorted({row["symbol"] for rows in payload["curves"].values() for row in rows if row["symbol"] in UNVERIFIED_TERMS})
    if not dropped:
        return
    payload["curves"] = {group: [row for row in rows if row["symbol"] not in UNVERIFIED_TERMS]
                         for group, rows in payload["curves"].items()}
    payload["quality"]["warnings"].append("Excluidas por condiciones sin verificar: " + ", ".join(dropped))
    monitor._write_json(path, payload)


def market_dates(start: date, end: date) -> list[date]:
    calendar = MarketCalendar.from_csv(monitor.CALENDAR_PATH)
    days, day = [], start
    while day <= end:
        if day.weekday() < 5 and day not in calendar.trading_closed:
            days.append(day)
        day += timedelta(days=1)
    return days


def _is_daily_snapshot(day: date) -> bool:
    path = monitor.ROOT / "output/history" / f"{day.isoformat()}.json"
    if not path.exists():
        return False
    return not json.loads(path.read_text(encoding="utf-8")).get("meta", {}).get("backfill")


def _merge_missing_closes(original: dict, rebuilt: dict) -> tuple[dict, list[str]]:
    """Add exact-date closes recovered later without changing the original daily observations."""
    added = []
    for group, rows in rebuilt["curves"].items():
        existing = original["curves"].setdefault(group, [])
        known = {row["symbol"] for row in existing}
        for row in rows:
            if row["symbol"] not in known:
                existing.append(row)
                added.append(row["symbol"])
        existing.sort(key=lambda row: (row.get("maturity_date", ""), row["symbol"]))
    if not added:
        return original, added
    added_set = set(added)
    quality = original["quality"]
    quality["rava_errors"] = {k: v for k, v in quality.get("rava_errors", {}).items() if k not in added_set}
    quality["missing_hard_dollar"] = [s for s in quality.get("missing_hard_dollar", []) if s not in added_set]
    warnings = [w for w in quality.get("warnings", [])
                if not w.startswith(("Rava sin precio de fecha:", "Hard dollar sin precio de fecha:"))]
    if quality["rava_errors"]:
        warnings.append("Rava sin precio de fecha: " + ", ".join(sorted(quality["rava_errors"])))
    if quality["missing_hard_dollar"]:
        warnings.append("Hard dollar sin precio de fecha: " + ", ".join(quality["missing_hard_dollar"]))
    quality["warnings"] = warnings
    if not quality.get("missing_money_market") and not quality["rava_errors"] and not quality["missing_hard_dollar"]:
        original["meta"]["status"] = "complete"
    original["meta"]["historical_prices_recovered_at"] = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).isoformat()
    original["meta"]["historical_prices_recovered_with_registry"] = rebuilt["meta"]["registry_version"]
    return original, sorted(added)


def main() -> None:
    today = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
    parser = argparse.ArgumentParser(description="Reconstruye snapshots históricos del monitor con cierres de Rava")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, default=today - timedelta(days=1))
    parser.add_argument("--force", action="store_true", help="Reemplaza también snapshots de corridas diarias")
    parser.add_argument("--repair-existing", action="store_true", help="Completa cierres exactos faltantes sin cambiar datos ya guardados")
    parser.add_argument("--only-missing", action="store_true", help="Sólo fechas sin snapshot (por ejemplo, tras errores de A3)")
    parser.add_argument("--publish", action="store_true", help="Publica la fecha más reciente como latest.json e HTML")
    args = parser.parse_args()
    if args.force and args.repair_existing:
        parser.error("--force y --repair-existing son incompatibles")

    exists = lambda day: (monitor.ROOT / "output/history" / f"{day.isoformat()}.json").exists()
    days = [day for day in market_dates(args.start, args.end)
            if (exists(day) if args.repair_existing else
                not (args.only_missing and exists(day)) and (args.force or not _is_daily_snapshot(day)))]
    if not days:
        print("Sin ruedas a reconstruir")
        return
    symbols = _registry_symbols()
    histories, failures = fetch_peso_histories(symbols)
    print(f"Historias Rava: {len(histories)} especies, {len(failures)} sin historia; {len(days)} ruedas a reconstruir")
    fetch = lambda wanted, market_date: quotes_on(histories, failures, wanted, market_date)
    failed = False
    with _cached_sources(min(days), max(days)):
        for day in reversed(days):  # las más recientes primero
            try:
                path = monitor.ROOT / "output/history" / f"{day.isoformat()}.json"
                original = json.loads(path.read_text(encoding="utf-8")) if args.repair_existing else None
                raw_dir = monitor.ROOT / "data/raw" / day.isoformat()
                original_raw = {p: p.read_bytes() for p in raw_dir.iterdir() if p.is_file()} if original and raw_dir.exists() else {}
                publish = args.publish and day == days[-1]
                try:
                    payload = monitor.run(day, publish=publish and not args.repair_existing, quote_fetcher=fetch)
                    if args.repair_existing:
                        drop_unverified(day)
                        rebuilt = json.loads(path.read_text(encoding="utf-8"))
                        payload, added = _merge_missing_closes(original, rebuilt)
                        monitor._write_json(path, payload)
                        print(f"{day} cierres recuperados: {', '.join(added) if added else 'ninguno'}", flush=True)
                    else:
                        drop_unverified(day)
                except Exception:
                    if original is not None:
                        monitor._write_json(path, original)
                    raise
                finally:
                    # La recuperación vuelve a consultar fuentes. Los archivos crudos de la
                    # corrida diaria siguen siendo el registro de lo observado entonces.
                    for raw_path, content in original_raw.items():
                        raw_path.write_bytes(content)
                if publish and args.repair_existing:
                    latest_path = monitor.ROOT / "output/latest.json"
                    latest = json.loads(latest_path.read_text(encoding="utf-8"))
                    if latest["meta"]["market_date"] == day.isoformat():
                        # La rueda reparada es la publicada: el monitor tiene que mostrar los cierres recuperados.
                        latest = payload
                        monitor._write_json(latest_path, latest)
                    monitor._publish_static_html(latest)
                counts = {key: len(rows) for key, rows in payload["curves"].items()}
                print(f"{day} {payload['meta']['status']} {counts}", flush=True)
            except Exception as exc:
                failed = failed or (args.publish and day == days[-1])
                print(f"{day} ERROR {type(exc).__name__}: {exc}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
