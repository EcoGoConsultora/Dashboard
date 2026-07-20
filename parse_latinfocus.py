#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_latinfocus.py  —  Extrae el Consensus Forecast del PDF LatinFocus
y genera assets/data/internacional2.js para el dashboard EcoGo.

Uso:
  python parse_latinfocus.py "LatinFocus Consensus Forecast - May 2026.pdf"
  python parse_latinfocus.py "...pdf" --dry-run   (solo muestra datos, no escribe)

El script parsea la página "Forecast Summary" del PDF (normalmente la p.3 o p.4),
que contiene toda la tabla con GDP / Inflación / Fiscal / Cuenta Corriente.
"""
import sys, re, json, os
from datetime import datetime

try:
    import pdfplumber
except ImportError:
    print("Instalando pdfplumber..."); os.system("pip install pdfplumber --break-system-packages -q")
    import pdfplumber

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_JS = os.path.join(DASHBOARD_DIR, "assets", "data", "internacional2.js")

# Mapa de nombres del PDF → id interno
COUNTRY_MAP = {
    "world":            "mundo",
    "united states":    "usa",
    "euro area":        "eurozona",
    "china":            "china",
    "latin america":    "latam",
    "argentina":        "argentina",
    "bolivia":          "bolivia",
    "brazil":           "brasil",
    "chile":            "chile",
    "colombia":         "colombia",
    "ecuador":          "ecuador",
    "mexico":           "mexico",
    "paraguay":         "paraguay",
    "peru":             "peru",
    "uruguay":          "uruguay",
    "venezuela":        "venezuela",
}

# IDs que se incluyen en el JS final (en este orden)
OUTPUT_IDS = [
    "mundo", "usa", "eurozona", "china",           # Referencias globales
    "latam",                                        # Agregado regional
    "argentina", "brasil", "chile", "mexico",
    "colombia", "paraguay", "uruguay", "peru",
    "ecuador", "bolivia", "venezuela",
]

# Metadatos de display para cada id
META = {
    "mundo":     {"flag": "🌍", "type": "ref", "name": "Mundo"},
    "usa":       {"flag": "🇺🇸", "type": "ref", "name": "Estados Unidos"},
    "eurozona":  {"flag": "🇪🇺", "type": "ref", "name": "Zona Euro"},
    "china":     {"flag": "🇨🇳", "type": "ref", "name": "China"},
    "latam":     {"flag": "🌎", "type": "grp", "name": "América Latina"},
    "argentina": {"flag": "🇦🇷", "type": "arg", "name": "Argentina"},
    "brasil":    {"flag": "🇧🇷", "type": "cnt", "name": "Brasil"},
    "chile":     {"flag": "🇨🇱", "type": "cnt", "name": "Chile"},
    "mexico":    {"flag": "🇲🇽", "type": "cnt", "name": "México"},
    "colombia":  {"flag": "🇨🇴", "type": "cnt", "name": "Colombia"},
    "paraguay":  {"flag": "🇵🇾", "type": "cnt", "name": "Paraguay"},
    "uruguay":   {"flag": "🇺🇾", "type": "cnt", "name": "Uruguay"},
    "peru":      {"flag": "🇵🇪", "type": "cnt", "name": "Perú"},
    "ecuador":   {"flag": "🇪🇨", "type": "cnt", "name": "Ecuador"},
    "bolivia":   {"flag": "🇧🇴", "type": "cnt", "name": "Bolivia"},
    "venezuela": {"flag": "🇻🇪", "type": "cnt", "name": "Venezuela"},
}


def fmt(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def extract_5nums(text):
    """Extrae exactamente 5 números de un string (puede contener nombre de país al inicio)."""
    vals = re.findall(r'-?\d+\.?\d*', str(text or ""))
    return [fmt(v) for v in vals[:5]]


def find_summary_page(pdf):
    """
    Encuentra la página "Forecast Summary" buscando por contenido.
    Devuelve el objeto de página.
    """
    for i, page in enumerate(pdf.pages):
        txt = page.extract_text() or ""
        if "Forecast Summary" in txt and "Fiscal Balance" in txt and "Current Account" in txt:
            print(f"  Página Summary: {i + 1}")
            return page
    # Fallback: página 3
    print("  ⚠️  No se encontró 'Forecast Summary', usando página 3 como fallback")
    return pdf.pages[2] if len(pdf.pages) > 2 else None


def parse_summary_table(tables, section_header):
    """
    Parsea una de las dos sub-tablas de la página Summary.
    section_header: 'GDP' o 'Fiscal'
    Devuelve dict {country_id: [v2023, v2024, v2025, v2026, v2027]}
    """
    data = {}
    in_section = False

    for table in tables:
        for row in table:
            if not row or not row[0]:
                continue
            cell0 = str(row[0]).strip()

            # Detectar encabezado de sección
            if "Fiscal Balance" in cell0 or "Current Account" in cell0:
                in_section = (section_header == "Fiscal")
                continue
            if "Real GDP" in cell0 or "Gross Domestic Product" in cell0:
                in_section = (section_header == "GDP")
                continue
            if "Inflation" in cell0 or "Consumer Prices" in cell0:
                # La sub-tabla de GDP también contiene Inflación en cell[7]
                continue

            # Detectar fila de país: cell0 comienza con nombre de país + números
            lower0 = cell0.lower()
            country_id = None
            for name, k in COUNTRY_MAP.items():
                if lower0.startswith(name):
                    country_id = k
                    break
            if not country_id:
                continue

            vals = extract_5nums(cell0)
            if len(vals) == 5 and any(v is not None for v in vals):
                data[country_id] = vals

    return data


def parse_page3(page):
    """
    Parsea la página Summary completa.
    Retorna: gdp, cpi, fis, ca — cada uno es dict {id: [2023,2024,2025,2026,2027]}
    """
    tables = page.extract_tables()
    text   = page.extract_text() or ""

    gdp, cpi, fis, ca = {}, {}, {}, {}

    # La tabla tiene dos bloques visuales, separados en el texto:
    # Bloque 1: GDP (cols 1-6) | CPI (cols 8-12)  ← en cell[0] y cell[7]
    # Bloque 2: Fiscal (cols 1-6) | CA (cols 8-12) ← misma estructura

    block = None   # 'gdp_cpi' | 'fis_ca'

    for table in tables:
        for row in table:
            if not row:
                continue
            cell0 = str(row[0] or "").strip()
            # ¿Qué bloque es este?
            if "Real GDP" in cell0 or ("Gross Domestic Product" in cell0 and "ann" in cell0):
                block = "gdp_cpi"; continue
            if "Fiscal Balance" in cell0:
                block = "fis_ca"; continue
            if not cell0 or not block:
                continue

            # Detectar nombre de país
            lower0 = cell0.lower()
            country_id = None
            for name, k in COUNTRY_MAP.items():
                if lower0.startswith(name):
                    country_id = k
                    break
            if not country_id:
                continue

            # Columna izquierda: nombre + 5 valores
            left  = extract_5nums(cell0)
            # Columna derecha: cell[7] ó último no-None con 5 números
            right_cell = None
            for c in row[6:]:
                if c and re.search(r'-?\d', str(c)):
                    right_cell = c; break
            right = extract_5nums(right_cell) if right_cell else [None]*5

            if block == "gdp_cpi":
                if len(left) == 5:  gdp[country_id] = left
                if len(right) == 5: cpi[country_id] = right
            elif block == "fis_ca":
                if len(left) == 5:  fis[country_id] = left
                if len(right) == 5: ca[country_id]  = right

    # ── Fallback: parsear desde el texto plano si las tablas fallan ──
    if len(gdp) < 5:
        gdp_txt, cpi_txt, fis_txt, ca_txt = parse_text_fallback(text)
        for d_from, d_to in [(gdp_txt, gdp), (cpi_txt, cpi),
                             (fis_txt, fis), (ca_txt, ca)]:
            for k, v in d_from.items():
                if k not in d_to:
                    d_to[k] = v

    return gdp, cpi, fis, ca


def parse_text_fallback(text):
    """
    Parsea la página Summary desde texto plano cuando las tablas no funcionan.
    El texto tiene el formato:
      CountryName v1 v2 v3 v4 v5 [más números]
    separados en dos bloques (GDP/CPI) y (Fiscal/CA).
    """
    gdp, cpi, fis, ca = {}, {}, {}, {}
    block = None

    for raw in text.split('\n'):
        line = re.sub(r'[]', '', raw).strip()
        line = re.sub(r'\s+', ' ', line)

        if "Real GDP" in line or "Gross Domestic Product" in line:
            block = "gdp_cpi"; continue
        if "Fiscal Balance" in line:
            block = "fis_ca"; continue
        if not block:
            continue

        lower = line.lower()
        country_id = None
        for name, k in COUNTRY_MAP.items():
            if lower.startswith(name):
                country_id = k; break
        if not country_id:
            continue

        all_nums = re.findall(r'-?\d+\.?\d*', line)
        fmted = [fmt(v) for v in all_nums]

        if block == "gdp_cpi":
            # Los primeros 5 son GDP, los siguientes 5 son CPI
            if len(fmted) >= 5:  gdp[country_id] = fmted[:5]
            if len(fmted) >= 10: cpi[country_id] = fmted[5:10]
        elif block == "fis_ca":
            if len(fmted) >= 5:  fis[country_id] = fmted[:5]
            if len(fmted) >= 10: ca[country_id]  = fmted[5:10]

    return gdp, cpi, fis, ca


def extract(pdf_path):
    """Abre el PDF y extrae todos los datos de la página Summary."""
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        print(f"  PDF: {n_pages} páginas")

        summary_page = find_summary_page(pdf)
        if summary_page is None:
            raise ValueError("No se encontró la página Summary en el PDF")

        gdp, cpi, fis, ca = parse_page3(summary_page)

        print(f"  GDP parsed: {list(gdp.keys())}")
        print(f"  CPI parsed: {list(cpi.keys())}")
        print(f"  Fiscal parsed: {list(fis.keys())}")
        print(f"  CA parsed: {list(ca.keys())}")

        # Detectar mes/año de la edición
        first_text = pdf.pages[0].extract_text() or ""
        month_match = re.search(
            r'(January|February|March|April|May|June|July|'
            r'August|September|October|November|December)\s+(\d{4})',
            first_text
        )
        edition = month_match.group(0) if month_match else "Unknown"
        print(f"  Edición detectada: {edition}")

    return gdp, cpi, fis, ca, edition


def build_js(pdf_path):
    """Genera el contenido JS a partir del PDF."""
    gdp, cpi, fis, ca, edition = extract(pdf_path)

    rows = []
    for cid in OUTPUT_IDS:
        m = META.get(cid, {})
        g = gdp.get(cid, [None]*5)
        i = cpi.get(cid, [None]*5)
        f = fis.get(cid, [None]*5)
        c = ca.get(cid,  [None]*5)

        row = {
            "id":   cid,
            "flag": m.get("flag", ""),
            "type": m.get("type", "cnt"),
            "name": m.get("name", cid),
            "gdp":  g,
            "inf":  i,
            "fis":  f,
            "ca":   c,
        }
        rows.append(row)
        print(f"  → {m.get('name', cid):20s}  gdp={g[3]}/{g[4]}  inf={i[3]}/{i[4]}  fis={f[3]}/{f[4]}  ca={c[3]}/{c[4]}")

    payload = {
        "edition":   edition,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "years":     ["2023", "2024", "2025", "2026f", "2027f"],
        "summary":   rows,
    }

    js = (
        f"// internacional2.js — generado por parse_latinfocus.py el {payload['generated']}\n"
        f"// Edición LatinFocus: {edition}\n"
        f"window.CF_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"
    )
    return js, edition


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if not args:
        print("Uso: python parse_latinfocus.py <ruta_pdf> [--dry-run]")
        print("Ejemplo: python parse_latinfocus.py 'LatinFocus Consensus Forecast - May 2026.pdf'")
        sys.exit(1)

    pdf_path = args[0]
    if not os.path.exists(pdf_path):
        print(f"Error: no se encontró '{pdf_path}'")
        sys.exit(1)

    print(f"\nProcesando: {os.path.basename(pdf_path)}")
    js_content, edition = build_js(pdf_path)

    if dry_run:
        print("\n── JS generado (primeras 80 líneas) ──")
        for line in js_content.split('\n')[:80]:
            print(line)
    else:
        os.makedirs(os.path.dirname(OUT_JS), exist_ok=True)
        with open(OUT_JS, 'w', encoding='utf-8') as f:
            f.write(js_content)
        sz = os.path.getsize(OUT_JS)
        print(f"\n✅  Guardado: {OUT_JS}")
        print(f"    Edición: {edition}  |  {sz:,} bytes")
