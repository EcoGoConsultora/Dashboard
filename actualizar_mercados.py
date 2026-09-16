"""Actualiza las secciones Mercados e Internacional · Mercados.

Este acceso manual usa el mismo pipeline local que refresh.py y los
notebooks. No consulta el antiguo Cloudflare Worker, que quedó desactualizado.
"""

from __future__ import annotations

import sys

import refresh


def main() -> int:
    status = refresh.Status()
    ok = refresh.extract_mercados(status)

    print()
    for result, name, detail in status.results:
        print(f"[{result}] {name}" + (f" — {detail}" if detail else ""))

    if ok:
        print("\nLISTO: recargá el dashboard en el navegador.")
        return 0

    print("\nNo se publicaron datos nuevos de Mercados; se conserva el último mercados.js válido.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
