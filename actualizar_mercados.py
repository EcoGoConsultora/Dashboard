"""
ECO GO — Actualizar datos de Mercados
======================================
Conecta a la API de EcoGo Markets, baja el payload completo
y guarda assets/data/mercados.js con los historiales de curvas
(necesarios para los botones -1D/-2D/-3D/-1S del dashboard).

Funciona tanto como script (python actualizar_mercados.py)
como celda de Jupyter Notebook.
"""

import os, json, urllib.request
from datetime import datetime

# ── Rutas ──────────────────────────────────────────────────────────
try:
    DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # En Jupyter __file__ no existe; ajustar si la carpeta es diferente
    DASHBOARD_DIR = r"C:\Users\fscalise\OneDrive - ECOGO S.A\BD\07 Tableros\EcoGo-Dashboard"

DATA_DIR = os.path.join(DASHBOARD_DIR, "assets", "data")
JS_PATH  = os.path.join(DATA_DIR, "mercados.js")

# ── API ────────────────────────────────────────────────────────────
API_URL = "https://ecogomarkets.honorio-zabaleta.workers.dev/data/dashboard_payload.json"

print("Conectando a la API de EcoGo Markets...")
req = urllib.request.Request(API_URL, headers={"User-Agent": "EcoGo-Dashboard-Refresh/1.0"})
with urllib.request.urlopen(req, timeout=30) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
print(f"  Payload recibido. Claves: {list(payload.keys())[:6]} ...")

# ── Subset ─────────────────────────────────────────────────────────
subset = {
    "meta":                      payload.get("meta", {}),
    "external_context":          payload.get("external_context", {}),
    "overview":                  payload.get("overview", {}),
    "fixed_curve":               payload.get("fixed_curve", []),
    "fixed_curve_history":       payload.get("fixed_curve_history",       {"dates": [], "curves": {}}),
    "cer_curve":                 payload.get("cer_curve", []),
    "cer_curve_history":         payload.get("cer_curve_history",         {"dates": [], "curves": {}}),
    "dollar_linked":             payload.get("dollar_linked", {}),
    "hard_dollar":               payload.get("hard_dollar", {}),
    "hard_dollar_curve_history": payload.get("hard_dollar_curve_history", {"dates": [], "curves": {}}),
    "hero_metrics":              payload.get("hero_metrics", []),
}

# ── Guardar ────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y-%m-%d %H:%M")
js_content = (
    "// Mercados data - extraido de dashboard_payload · " + ts + "\n"
    "window.MERCADOS_DATA = "
    + json.dumps(subset, ensure_ascii=False, default=str)
    + ";\n"
)
with open(JS_PATH, "w", encoding="utf-8") as f:
    f.write(js_content)

sz = os.path.getsize(JS_PATH)

# ── Reporte ────────────────────────────────────────────────────────
fch = subset["fixed_curve_history"]
cch = subset["cer_curve_history"]
hch = subset["hard_dollar_curve_history"]

print(f"\n  [OK] mercados.js guardado — {sz:,} bytes · {ts}")
print(f"  Historiales de curvas:")
print(f"    Tasa Fija : {len(fch.get('dates', []))} fechas")
print(f"    CER       : {len(cch.get('dates', []))} fechas")
print(f"    Hard $ A*/G*: {len(hch.get('dates', []))} fechas")
print(f"\n  Recargá el dashboard en el navegador.")
