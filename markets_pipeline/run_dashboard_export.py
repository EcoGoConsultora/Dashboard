"""Genera el payload de Mercados consumido por EcoGo-Dashboard.

Este ejecutor conserva el flujo del antiguo Markets Dashboard (ingest ->
transform -> export) pero omite su frontend y el PDF semanal. El resultado se
deja en output/dashboard_payload.json para que refresh.py publique solamente
el subconjunto que usan las páginas de este repositorio.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "output" / "dashboard_payload.json"

# Contrato que usan pages/mercados.html y pages/mercados-global.html. El
# exportador original también incluye FCI, monetarias y otros bloques de su
# propia web; no deben bloquear la publicación de estas dos secciones.
PAYLOAD_DEFAULTS = {
    "meta": {},
    "external_context": {},
    "overview": {},
    "fixed_curve": [],
    "fixed_curve_history": {"dates": [], "curves": {}},
    "cer_curve": [],
    "cer_curve_history": {"dates": [], "curves": {}},
    "dollar_linked": {},
    "hard_dollar": {},
    "hard_dollar_curve_history": {"dates": [], "curves": {}},
    "hero_metrics": [],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh local del payload de Mercados.")
    parser.add_argument(
        "--end-date",
        help="Fecha máxima opcional para la ingesta (YYYY-MM-DD). Por defecto usa hoy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.chdir(ROOT)

    # Las importaciones quedan después del chdir: los módulos del pipeline usan
    # paths relativos para configuración, calendarios y cachés de mercado.
    from src.ingest.run_ingest import run as run_ingest
    from src.reporting.export_web_bundle import build_payload
    from src.transform.run_transform import run as run_transform

    ingest = run_ingest(end_date=args.end_date)
    print(
        "[markets] ingesta completada: "
        f"{ingest['prices'].name}, {ingest['cpi'].name}, {ingest['fundamentals'].name}"
    )
    transform = run_transform()
    print(
        "[markets] transformacion completada: "
        f"{transform['prices'].name}, {transform['latest_prices'].name}"
    )

    payload = build_payload()
    dashboard_payload = {
        key: payload.get(key, default)
        for key, default in PAYLOAD_DEFAULTS.items()
    }
    serialized = json.dumps(dashboard_payload, ensure_ascii=False, allow_nan=False)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_FILE.with_suffix(".json.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(OUTPUT_FILE)

    meta = dashboard_payload["meta"]
    external = dashboard_payload["external_context"]
    print(
        "[markets] payload listo: "
        f"end_date={meta.get('end_date', '?')} "
        f"external_date={external.get('latest_date', '?')} "
        f"fixed_curve={len(dashboard_payload['fixed_curve'])} "
        f"cer_curve={len(dashboard_payload['cer_curve'])}"
    )


if __name__ == "__main__":
    main()
