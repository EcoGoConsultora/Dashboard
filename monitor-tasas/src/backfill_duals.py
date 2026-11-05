"""Add reconstructed dual histories to existing snapshots without revaluing other curves.

    py -3.14 -m src.backfill_duals --start 2026-01-02 --end 2026-11-04

Daily observations already saved are kept. Prices must match the requested day;
BCRA series are cut by effective date (not an archive of publication vintages).
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from statistics import fmean
from zoneinfo import ZoneInfo

import pandas as pd

from src import monitor
from src.backfill import fetch_peso_histories, quotes_on
from src.breakeven.calendar import MarketCalendar
from src.common.dual_curve import build_dual_nodes
from src.tamar_curve.calendar import make_bank_calendar, estimate_argentine_national_holidays


VINTAGE_POLICY = "current_official_BCRA_series_cut_by_effective_date; publication_vintages_not_verified"


def active_terms(entries: list[dict], day: date, calendar: MarketCalendar) -> list[dict]:
    settlement = calendar.next_business_day(day, 1)
    return [entry for entry in entries if date.fromisoformat(entry["issue_date"]) <= day
            and date.fromisoformat(entry["maturity_date"]) > settlement]


def nodes_on(entries, histories, failures, day, calendar, tamar, cer, fx, holidays, fixing_cutoff=None):
    """Calculate one historical day, excluding later TAMAR, FX and CER observations."""
    terms = active_terms(entries, day, calendar)
    quotes, errors = quotes_on(histories, failures, {entry["symbol"] for entry in terms}, day)
    if not quotes:
        return [], errors
    cutoff = min(day, fixing_cutoff or day)
    series = {row.date: float(row.value) for row in tamar.itertuples(index=False) if row.date <= cutoff}
    if not series:
        raise ValueError(f"Sin fijaciones TAMAR hasta {cutoff}")
    forecast = fmean(series[candidate] for candidate in sorted(series)[-5:])
    settlement = calendar.next_business_day(day, 1)
    # No future realized CER may be mistaken for a known contractual payoff.
    cer_asof = cer[cer["date"] <= settlement].copy()
    fx_asof = fx[fx["date"] <= day].sort_values("date")
    fx_reference = ({"date": fx_asof.iloc[-1]["date"].isoformat(), "value": float(fx_asof.iloc[-1]["value"])}
                    if not fx_asof.empty else {})
    rows = build_dual_nodes(terms, quotes, day, calendar, cer_asof, fx_reference,
                            series, make_bank_calendar(series, holidays), forecast)
    for row in rows:
        row["historical_reconstruction"] = True
        row["historical_bcra_vintage_policy"] = VINTAGE_POLICY
    return rows, errors


def merge_duals(snapshot: dict, rows: list[dict], errors: dict, warnings: list[str], stamp: str, registry_version: str):
    """Return a new snapshot, retaining every existing observation and its metadata."""
    result = deepcopy(snapshot)
    existing = result["curves"].setdefault("dual", [])
    symbols = {row["symbol"] for row in existing}
    additions = [row for row in rows if row["symbol"] not in symbols]
    previous_errors = snapshot.get("quality", {}).get("dual_backfill", {}).get("missing_prices")
    if not additions and (not errors or errors == previous_errors):
        return snapshot, []
    existing.extend(additions)
    existing.sort(key=lambda row: (row["maturity_date"], row["symbol"]))
    recovered = {row["symbol"] for row in additions}
    quality = result.setdefault("quality", {})
    quality["dual_backfill"] = {"missing_prices": errors, "warnings": warnings,
                                 "bcra_vintage_policy": VINTAGE_POLICY}
    quality["rava_errors"] = {key: value for key, value in quality.get("rava_errors", {}).items() if key not in recovered}
    quality["rava_errors"].update(errors)
    quality.setdefault("warnings", [])
    for warning in warnings + (["Duales históricos sin cierre de fecha: " + ", ".join(sorted(errors))] if errors else []):
        if warning not in quality["warnings"]:
            quality["warnings"].append(warning)
    if errors:
        result["meta"]["status"] = "partial"
    expected = {row["symbol"] for values in result["curves"].values() for row in values}
    expected |= set(quality.get("rava_errors", {})) | set(quality.get("missing_hard_dollar", []))
    expected |= set(snapshot.get("volumes", {}).get("missing_price_symbols", []))
    # Volume enrichment is additive: leave all previously saved non-dual curve rows intact.
    enriched_curves = deepcopy(result["curves"])
    result["volumes"] = monitor.add_volume_data(enriched_curves, result["meta"]["market_date"], expected)
    result["curves"]["dual"] = enriched_curves["dual"]
    result["schema_version"] = "1.1"
    result["meta"]["dual_history_backfill"] = {"generated_at": stamp, "registry_version": registry_version,
                                                "bcra_vintage_policy": VINTAGE_POLICY}
    return result, sorted(recovered)


def _original_fixing_cutoff(snapshot: dict, day: date) -> date:
    """Reuse the last fixing date observed by a real daily run when its raw record exists."""
    path = monitor.ROOT / "data/raw" / day.isoformat() / "bcra_reference.json"
    if not snapshot["meta"].get("backfill") and path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        dates = [date.fromisoformat(row["date"][:10]) for row in raw.get("tamar", [])]
        if dates:
            return min(day, max(dates))
    return day


def run(start: date | None = None, end: date | None = None) -> dict:
    registry = json.loads((monitor.ROOT / "config/market_instruments.json").read_text(encoding="utf-8"))
    entries = registry["dual"]
    paths = [path for path in sorted((monitor.ROOT / "output/history").glob("*.json"))
             if (start is None or date.fromisoformat(path.stem) >= start)
             and (end is None or date.fromisoformat(path.stem) <= end)]
    if not paths:
        raise ValueError("No hay snapshots para el rango pedido")
    calendar = MarketCalendar.from_csv(monitor.CALENDAR_PATH)
    stamp = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    raw_dir = monitor.ROOT / "data/raw/dual_backfill" / stamp.strftime("%Y-%m-%d_%H%M%S")
    raw_dir.mkdir(parents=True, exist_ok=True)
    histories, failures = fetch_peso_histories({entry["symbol"] for entry in entries})
    if failures:
        raise ValueError(f"Falló la descarga de historias duales: {failures}")
    for symbol, frame in histories.items():
        frame.to_csv(raw_dir / f"rava_{symbol}.csv", index=False)
    first, last = (date.fromisoformat(path.stem) for path in (paths[0], paths[-1]))
    tamar = monitor.fetch_variable(44, date(2025, 1, 1), last)
    cer = monitor.fetch_cer(first, calendar.next_business_day(last, 1))
    fx = monitor.fetch_variable(5, first, last)
    tamar.to_csv(raw_dir / "bcra_tamar.csv", index=False)
    cer.to_csv(raw_dir / "bcra_cer.csv", index=False)
    fx.to_csv(raw_dir / "bcra_a3500.csv", index=False)
    holidays, estimated_years = {}, set()
    for year in range(first.year, max(date.fromisoformat(entry["maturity_date"]).year for entry in entries) + 1):
        try:
            holidays[year] = set(monitor.fetch_bcra_bank_holidays(year))
        except Exception:
            holidays[year] = set(estimate_argentine_national_holidays(year))
            estimated_years.add(year)
    monitor._write_json(raw_dir / "bank_calendars.json", {
        str(year): {"estimated": year in estimated_years, "closed_dates": sorted(day.isoformat() for day in dates)}
        for year, dates in holidays.items()})
    report = {"generated_at": stamp.isoformat(), "start": first.isoformat(), "end": last.isoformat(),
              "snapshots_updated": 0, "observations_added": 0, "by_symbol": {}, "missing_prices": {},
              "bcra_vintage_policy": VINTAGE_POLICY, "raw_directory": str(raw_dir)}
    for path in paths:
        day = date.fromisoformat(path.stem)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        rows, errors = nodes_on(entries, histories, failures, day, calendar, tamar, cer, fx, holidays,
                               _original_fixing_cutoff(snapshot, day))
        active = active_terms(entries, day, calendar)
        max_year = max([day.year] + [date.fromisoformat(entry["maturity_date"]).year for entry in active])
        warnings = [f"Calendario bancario {year} estimado" for year in sorted(estimated_years) if day.year <= year <= max_year]
        updated, added = merge_duals(snapshot, rows, errors, warnings, stamp.isoformat(), registry["registry_version"])
        if errors:
            report["missing_prices"][day.isoformat()] = errors
        if updated is snapshot:
            continue
        backup = raw_dir / "snapshots_before" / path.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
        monitor._write_json(path, updated)
        report["snapshots_updated"] += 1
        report["observations_added"] += len(added)
        for row in rows:
            if row["symbol"] not in added:
                continue
            coverage = report["by_symbol"].setdefault(row["symbol"], {"count": 0, "first": day.isoformat(), "last": day.isoformat()})
            coverage["count"] += 1
            coverage["last"] = day.isoformat()
        if report["snapshots_updated"] % 25 == 0:
            print(f"{day}: {report['snapshots_updated']} ruedas completadas", flush=True)
    coverage = {}
    report["snapshots_with_duals"] = 0
    report["total_dual_observations"] = 0
    for path in paths:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        rows = snapshot["curves"].get("dual", [])
        report["snapshots_with_duals"] += bool(rows)
        report["total_dual_observations"] += len(rows)
        for row in rows:
            item = coverage.setdefault(row["symbol"], {"count": 0, "first": path.stem, "last": path.stem})
            item["count"] += 1
            item["last"] = path.stem
    report["history_coverage_by_symbol"] = coverage
    # Regenerate the existing design so its embedded history contains the additions.
    # The daily payload and template are not rewritten.
    latest = json.loads((monitor.ROOT / "output/latest.json").read_text(encoding="utf-8"))
    monitor._publish_static_html(latest)
    monitor._write_json(raw_dir / "report.json", report)
    monitor._write_json(monitor.ROOT / "docs/revisions" / f"{stamp:%Y-%m-%d}-dual-history.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Completa sólo duales en snapshots ya guardados")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    args = parser.parse_args()
    print(json.dumps(run(args.start, args.end), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
