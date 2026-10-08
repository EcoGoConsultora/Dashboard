"""
ECO GO Dashboard - Refresh de datos
====================================
Re-lee los Excel originales y regenera los archivos JSON/JS del dashboard.

Uso:
  - Doble click a refresh.bat (recomendado)
  - O desde terminal: python refresh.py

Los archivos Excel NO se modifican (read-only).
"""

import os
import sys
import json
import re
import functools
import traceback
from datetime import datetime

# Asegurar consola con soporte unicode en Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# =====================================================================
#  CONFIGURACIÓN — Editá estas rutas si los Excel cambian de ubicación
# =====================================================================
# Directorio del dashboard = donde está este script
# (definido aquí para que BASE_EXCEL pueda derivarse de él en Linux)
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

import platform as _platform
if _platform.system() == 'Windows':
    BASE_EXCEL = r"C:\Users\fscalise\OneDrive - ECOGO S.A\BD"
else:
    # En Linux (sandbox Cowork): el dashboard está en BD/07 Tableros/EcoGo-Dashboard
    # → BASE_EXCEL es dos niveles arriba
    BASE_EXCEL = os.path.dirname(os.path.dirname(DASHBOARD_DIR))

EXCEL_PATHS = {
    "ipc":         os.path.join(BASE_EXCEL, "Precios", "IPC TODESCA.xlsx"),
    "gd":          os.path.join(BASE_EXCEL, "Precios", "Gráficos de dispersión - copia - copia.xlsx"),
    "cm":          os.path.join(BASE_EXCEL, "Precios", "CM - DB.xlsx"),  # opcional (ya no se usa para proyeccion)
    "rpm_cuadro":  os.path.join(BASE_EXCEL, "Precios", "RPM Estudio Bein", "Alimentos Scrapping", "Cuadro Mensual - Capítulos Nuevo.xlsx"),
    "empleo":      os.path.join(BASE_EXCEL, "Empleo",  "Empleo_limpio.xlsx"),
    "salarios":    os.path.join(BASE_EXCEL, "Empleo",  "Salarios.xlsx"),
    "tcr_bandas":  os.path.join(BASE_EXCEL, "Tipo de Cambio", "TCR bandas.xlsx"),
    "rofex":       os.path.join(BASE_EXCEL, "Tipo de Cambio", "Rofex.xlsx"),
    "com3500":     os.path.join(BASE_EXCEL, "Tipo de Cambio", "com3500.xls"),  # TCN A3500 historico
    "copia_blue":  os.path.join(BASE_EXCEL, "Tipo de Cambio", "Copia de Blue.xlsx"),  # Blue, MEP, CCL
    "base_esae":      os.path.join(BASE_EXCEL, "Actividad", "02 Indicador de Actividad CN2004", "Base EsAE.xlsx"),
    "emae":           os.path.join(BASE_EXCEL, "Actividad", "EMAE.xlsx"),
    "monitor_actividad": os.path.join(BASE_EXCEL, "Actividad", "Monitor de Actividad.xlsx"),
    "pasivos_res":    os.path.join(BASE_EXCEL, "Monetarias", "pasivos reservas.xlsx"),
    "res_dep":        os.path.join(BASE_EXCEL, "Monetarias", "Reservas brutas y depósitos.xlsx"),
    "agregados_mon":  os.path.join(BASE_EXCEL, "Monetarias", "Copia de Agregados monetarios.xlsx"),
    "monitor_mon":    os.path.join(BASE_EXCEL, "Monetarias", "Monitor monetario mensual.xlsx"),
    # Carpeta del proyecto, no un archivo: adentro hay una subcarpeta por corrida
    # con la fecha en el nombre (dlk_futuros_m2_AAAAMMDD_HHMMSS).
    "tenencia_dlk":   os.path.join(BASE_EXCEL, "Monetarias", "Tenencia DLK BCRA"),
    "rigi":           os.path.join(BASE_EXCEL, "Códigos", "Python", "Patru", "rigi", "Proyectos RIGI.xlsx"),
    "deuda_lopez_murphy":     os.path.join(BASE_EXCEL, "Deuda", "Deuda Lopez Murphy.xlsx"),
    "deuda_en_pesos":         os.path.join(BASE_EXCEL, "Deuda", "Deuda en pesos.xlsx"),
    "deuda_refinanciamiento": os.path.join(BASE_EXCEL, "Deuda", "Ejercicio refinanciamiento.xlsx"),
    "comex":       os.path.join(BASE_EXCEL, "Comercio", "Comercio exterior.xlsx"),
    "comex_tdi":   os.path.join(BASE_EXCEL, "Comercio", "Terminos del Intercambio.xlsx"),
    "comex_proy":  os.path.join(BASE_EXCEL, "Comercio", "01 Proyecciones", "Estimación Comercio Ext.xlsx"),
    "monitor_tasas":  os.path.join(BASE_EXCEL, "Mercados", "Monitor tasas"),
    "potencial_exportador": os.path.join(
        BASE_EXCEL, "Comercio", "01 Proyecciones", "Proyecciones 2036",
        "perspectiva_exportaciones_2036_20260705",
        "Cuadros y graficos - Perspectiva exportaciones Argentina 2026-2036 v2.xlsx"),
}

# Monitor mundial — el updater que baja los datos oficiales de la seccion
# Internacional. La copia que corre el refresh vive DENTRO del repo, asi queda
# versionada en git: antes estaba suelta en OneDrive y cualquier arreglo se
# podia perder sin que nadie se enterara.
MONITOR_MUNDIAL_DIR = os.path.join(DASHBOARD_DIR, "monitor-mundial")
MONITOR_MUNDIAL_JS = os.path.join(MONITOR_MUNDIAL_DIR, "data", "monitor-data.js")

# Carpeta original del Monitor mundial. El resultado se copia tambien ahi para
# que el dashboard standalone (su propio index.html) siga funcionando igual.
MONITOR_MUNDIAL_ESPEJO = os.path.join(BASE_EXCEL, "Internacional", "Monitor mundial",
                                      "data", "monitor-data.js")

# Carpeta donde se dejan los PDF de LatinFocus Consensus Forecast.
# Se busca de forma recursiva (adentro hay una subcarpeta por anio: 2025, 2026...)
# y se toma el mas nuevo, asi en enero no hay que tocar nada.
PROYECCIONES_INTL = os.path.join(BASE_EXCEL, "Proyecciones Bein", "Latin Focus")

DATA_DIR = os.path.join(DASHBOARD_DIR, "assets", "data")

# Pipeline local de Mercados. Es una copia autocontenida del núcleo de datos
# del antiguo Markets Dashboard; el frontend original no forma parte del flujo.
MARKETS_PIPELINE_DIR = os.path.join(DASHBOARD_DIR, "markets_pipeline")
MARKETS_PIPELINE_RUNNER = os.path.join(MARKETS_PIPELINE_DIR, "run_dashboard_export.py")
MARKETS_PIPELINE_PAYLOAD = os.path.join(MARKETS_PIPELINE_DIR, "output", "dashboard_payload.json")

# =====================================================================
#  Helpers
# =====================================================================


def _leer_bytes(path):
    """Lee un Excel a bytes aunque este abierto en Excel o a medio sincronizar
    por OneDrive.

    El open() de Python pide el archivo sin FILE_SHARE_DELETE, y con eso Windows
    lo rechaza mientras Excel lo tiene abierto (shutil.copy2 y 'copy' de cmd
    fallan por lo mismo). Se reintenta con CreateFileW pidiendo los tres modos
    de uso compartido, que si lo permite; si aun asi no se puede, se saca una
    copia con PowerShell y se lee de ahi.

    Sin esto, con solo tener el Excel abierto esa seccion se caia y el refresh
    terminaba sin ese dato."""
    try:
        with open(path, 'rb') as _f:
            return _f.read()
    except PermissionError:
        pass

    # 1) leer directo pidiendo uso compartido completo (lectura/escritura/borrado)
    try:
        import ctypes, msvcrt
        from ctypes import wintypes
        GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
        SHARE_TODO = 0x1 | 0x2 | 0x4
        k = ctypes.windll.kernel32
        k.CreateFileW.restype = wintypes.HANDLE
        h = k.CreateFileW(str(path), GENERIC_READ, SHARE_TODO, None,
                          OPEN_EXISTING, 0x80, None)
        if h != wintypes.HANDLE(-1).value:
            fd = msvcrt.open_osfhandle(h, os.O_RDONLY)
            with os.fdopen(fd, 'rb') as _f:
                return _f.read()
    except Exception:
        pass

    # 2) ultimo recurso: copiar con PowerShell, que tampoco se traba
    import subprocess as _sub, tempfile as _tmp
    destino = os.path.join(_tmp.gettempdir(),
                           f"_ecogo_{os.getpid()}_{os.path.basename(path)}")
    try:
        _sub.run(["powershell", "-NoProfile", "-Command",
                  f'Copy-Item -LiteralPath "{path}" -Destination "{destino}" -Force'],
                 capture_output=True, timeout=120)
        with open(destino, 'rb') as _f:
            return _f.read()
    finally:
        try:
            os.remove(destino)
        except OSError:
            pass

def _open_wb(path, data_only=True, read_only=True):
    """Abre un Excel leyendo primero a bytes para evitar problemas con OneDrive mount."""
    import io as _io
    import openpyxl as _opx
    return _opx.load_workbook(_io.BytesIO(_leer_bytes(path)),
                              data_only=data_only, read_only=read_only)

def _read_text(path, encoding='utf-8'):
    """Lee un archivo de texto sorteando el [Errno 22] que a veces tira el
    mount de OneDrive: si la lectura de texto falla, se reintenta en binario.

    Antes esto se resolvia llamando a 'cat', que existe en Git Bash pero no en
    Windows a secas. Desde Jupyter no estaba en el PATH y subprocess LEVANTABA
    FileNotFoundError en vez de devolver un codigo de error, asi que el
    fallback de mas abajo nunca llegaba a ejecutarse."""
    try:
        with open(path, encoding=encoding) as f:
            return f.read()
    except OSError:
        with open(path, 'rb') as f:
            return f.read().decode(encoding, errors='replace')

class Status:
    def __init__(self):
        self.results = []
    def ok(self, name, detail=""):
        self.results.append(("OK", name, detail))
        print(f"  [OK]   {name}" + (f" — {detail}" if detail else ""))
    def warn(self, name, detail=""):
        self.results.append(("WARN", name, detail))
        print(f"  [---]  {name}" + (f" — {detail}" if detail else ""))
    def fail(self, name, detail=""):
        self.results.append(("FAIL", name, detail))
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))

def save_data(name, data):
    """Guarda como JSON + JS con la variable global esperada."""
    json_path = os.path.join(DATA_DIR, f"{name}.json")
    js_path   = os.path.join(DATA_DIR, f"{name}.js")
    json_str  = json.dumps(data, ensure_ascii=False, default=str)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_str)
    except OSError:
        pass  # OneDrive bloquea .json existentes — solo escribimos el .js
    var_name = {"precios":"PRECIOS_DATA","empleo":"EMPLEO_DATA","salarios":"SALARIOS_DATA","tipo-cambio":"TC_DATA","reservas":"RESERVAS_DATA"}.get(name, name.upper()+"_DATA")
    js = f"// Datos de {name} - regenerado por refresh.py el {datetime.now().strftime('%Y-%m-%d %H:%M')}\nwindow.{var_name} = {json_str};\n"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js)
    return os.path.getsize(js_path)

def load_existing(name):
    json_path = os.path.join(DATA_DIR, f"{name}.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def col_idx(letter):
    n = 0
    for c in letter:
        n = n * 26 + ord(c) - 64
    return n

def fmt_n(v):
    return v if isinstance(v, (int, float)) else None

def _a_fecha(v):
    """Interpreta 'YYYY-MM', 'YYYY-MM-DD' o un datetime. None si no puede."""
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(s if fmt == "%Y-%m-%d" else s[:7], fmt)
        except ValueError:
            pass
    return None

def _nunca_rompe(nombre):
    """Convierte cualquier excepcion del paso en un WARN. Estos pasos dependen
    de archivos que pueden estar bloqueados, a medio sincronizar o directamente
    no estar: que falte el PDF del mes no puede cortar el refresh entero."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(status, *a, **kw):
            try:
                return fn(status, *a, **kw)
            except Exception as e:
                status.warn(nombre, f"{type(e).__name__}: {e}")
                # Detalle en una linea, no un traceback: el paso quedo en WARN y
                # el refresh sigue. Un traceback entero acá hace pensar que se
                # corto la corrida cuando en realidad no paso nada de eso.
                tb = traceback.extract_tb(sys.exc_info()[2])
                if tb:
                    ult = tb[-1]
                    print(f"         (el refresh sigue · origen: {os.path.basename(ult.filename)}"
                          f":{ult.lineno} {ult.name})")
                return False
        return wrapper
    return deco

def _avisar_si_viejo(status, nombre, ultima_fecha, meses=3, extra=""):
    """Marca WARN cuando el ultimo dato de una serie quedo mas de `meses`
    atras. Es la red de seguridad de todo esto: un rango que se queda corto,
    una hoja que se renombra o una fuente que se apaga no rompen nada — el
    refresh termina diciendo LISTO igual. Sin este chequeo, la unica forma de
    enterarse es que alguien mire el grafico semanas despues."""
    d = _a_fecha(ultima_fecha)
    if d is None:
        return
    atraso = (datetime.now().year - d.year) * 12 + (datetime.now().month - d.month)
    if atraso > meses:
        status.warn(nombre, f"ultimo dato {d.strftime('%b-%y')} — {atraso} meses de atraso"
                            + (f" ({extra})" if extra else ""))

def cols_por_encabezado(ws, fila_label, fila_unidad=None, col_ini=3, col_fin=30):
    """Devuelve [(columna, etiqueta, unidad)] leyendo los encabezados del propio
    Excel, en vez de tenerlos escritos a mano en el codigo. Toma toda columna de
    col_ini..col_fin que tenga algo en fila_label; las fechas las formatea
    'mmm-aa'.

    Los mapeos fijos de columna son la peor version del problema de los rangos
    fijos: cuando el analista intercala una columna, no falta un dato — se
    muestra el dato correcto bajo la etiqueta equivocada."""
    # strftime('%b') da el mes en ingles ("Aug-18"); el dashboard va en castellano
    MESES_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
    out = []
    for c in range(col_ini, col_fin + 1):
        lab = ws.cell(fila_label, c).value
        if isinstance(lab, datetime):
            lab = f"{MESES_ES[lab.month - 1]}-{lab.strftime('%y')}"
        elif isinstance(lab, str):
            lab = lab.replace('\n', ' ').strip()
        else:
            lab = None
        if not lab:
            continue
        uni = ws.cell(fila_unidad, c).value if fila_unidad else None
        uni = str(uni).replace('\n', ' ').strip() if uni else ''
        out.append((c, lab, uni))
    return out

def last_data_row(ws, cols, start_row, hard_max=3000, gap=18):
    """Ultima fila, desde start_row, con algun valor numerico en alguna de
    `cols` (letras de columna). Corta despues de `gap` filas seguidas sin
    datos, asi no se come las filas de meses futuros que el analista deja
    preparadas y todavia vacias.

    Sirve para no dejar topes de fila fijos en el codigo: cuando el Excel
    suma un mes, el refresh lo toma solo. Si el rango se hardcodea, la serie
    se queda corta en silencio y nadie se entera hasta que alguien mira el
    grafico."""
    idxs = [col_idx(c) for c in cols]
    limite = min(ws.max_row or hard_max, hard_max)
    last, vacias = start_row - 1, 0
    for r in range(start_row, limite + 1):
        if any(isinstance(ws.cell(r, i).value, (int, float)) for i in idxs):
            last, vacias = r, 0
        else:
            vacias += 1
            if vacias >= gap:
                break
    return last

def _parse_ref(ref):
    """Separa una referencia de Excel tipo "'Hoja X'!$A$1:$A$10" en (hoja, rango)."""
    sheet_part, cell_part = ref.split('!', 1)
    return sheet_part.strip("'"), cell_part

def _read_range_values(wb, ref):
    """Lee los valores de un rango de celdas (una columna) dado por su referencia."""
    from openpyxl.utils.cell import range_boundaries
    sheet_name, cell_part = _parse_ref(ref)
    ws = wb[sheet_name]
    min_col, min_row, max_col, max_row = range_boundaries(cell_part)
    vals = []
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True):
        vals.extend(row)
    return vals

def _read_ref_values(wb, ref):
    """Como _read_range_values pero soporta referencias de rango multiple
    (selecciones no contiguas de Excel) tipo
    "('Hoja'!$E$1:$G$1,'Hoja'!$I$1:$K$1)". Si el analista agrega o saca
    columnas de la seleccion del grafico en Excel, el refresh sigue esa
    seleccion automaticamente."""
    ref = ref.strip()
    if ref.startswith('('):
        inner = ref[1:-1] if ref.endswith(')') else ref[1:]
        parts = []
        depth = 0
        cur = ''
        for ch in inner:
            if ch == ',' and depth == 0:
                parts.append(cur)
                cur = ''
                continue
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            cur += ch
        if cur.strip():
            parts.append(cur)
        vals = []
        for p in parts:
            vals.extend(_read_range_values(wb, p.strip()))
        return vals
    return _read_range_values(wb, ref)

def _read_single_value(wb, ref):
    return _read_range_values(wb, ref)[0]

def get_chart_series(wb, chartsheet_name):
    """Lee las series (fechas + valores + nombre) del primer grafico de una
    hoja-grafico de Excel (Chartsheet), leyendo directo de las celdas que el
    grafico referencia. Si el analista extiende el rango de datos del
    grafico en Excel, el refresh sigue ese rango automaticamente."""
    ws = wb[chartsheet_name]
    chart = ws._charts[0]
    cats = None
    series_out = []
    for s in chart.series:
        val_ref = s.val.numRef.f
        vals = _read_ref_values(wb, val_ref)
        if cats is None and s.cat is not None:
            cat_ref = s.cat.numRef.f if s.cat.numRef else (s.cat.strRef.f if s.cat.strRef else None)
            if cat_ref:
                cats = _read_ref_values(wb, cat_ref)
        if s.tx is not None and s.tx.strRef is not None:
            label = _read_single_value(wb, s.tx.strRef.f)
        elif s.tx is not None and s.tx.v:
            label = s.tx.v
        else:
            label = None
        if isinstance(label, str):
            label = label.strip()
        series_out.append((label, vals))
    return cats, series_out

def _chart_block(wb, chart_name, scale=1.0):
    """Arma {dates, series} a partir de un grafico de Excel (ver get_chart_series).
    scale permite normalizar unidades (ej.: 0.01 si el Excel guarda el dato
    ya multiplicado por 100, para dejarlo como fraccion 0-1 igual que el
    resto del dashboard)."""
    cats, series_list = get_chart_series(wb, chart_name)
    n = 0
    for d in (cats or []):
        if isinstance(d, datetime):
            n += 1
        else:
            break
    dates = [d.strftime('%Y-%m-%d') for d in cats[:n]]
    series = {}
    for label, vals in series_list:
        if not label:
            continue
        series[label] = [round(v * scale, 4) if isinstance(v, (int, float)) else None for v in vals[:n]]
    return {'dates': dates, 'series': series}

def sin_cola_vacia(bloque):
    """Saca del final los periodos en los que ninguna serie tiene dato.

    Pasa cuando el rango del grafico de Excel llega mas lejos que los datos
    cargados: el eje se estira hasta ahi y la linea queda cortada antes del
    borde, como si la serie terminara antes de lo que termina."""
    fechas = bloque.get('dates') or []
    series = bloque.get('series') or {}
    if not fechas or not series:
        return bloque
    ultimo = -1
    for vals in series.values():
        for i, v in enumerate(vals[:len(fechas)]):
            if v is not None and i > ultimo:
                ultimo = i
    if ultimo < 0 or ultimo == len(fechas) - 1:
        return bloque
    return {'dates': fechas[:ultimo + 1],
            'series': {k: v[:ultimo + 1] for k, v in series.items()}}

def _chart_block_categorical(wb, chart_name, scale=1.0):
    """Como _chart_block, pero para graficos cuyas categorias NO son fechas
    (por ejemplo anios sueltos o etiquetas de texto, con selecciones no
    contiguas de columnas). Devuelve {categories, series} en vez de
    {dates, series}."""
    cats, series_list = get_chart_series(wb, chart_name)
    labels = []
    for c in (cats or []):
        if isinstance(c, str):
            labels.append(c.replace('\n', ' ').strip())
        elif isinstance(c, (int, float)):
            labels.append(str(int(c)) if float(c).is_integer() else str(c))
        elif isinstance(c, datetime):
            labels.append(c.strftime('%Y-%m-%d'))
        else:
            labels.append('' if c is None else str(c))
    series = {}
    for label, vals in series_list:
        if not label:
            continue
        series[label] = [round(v * scale, 4) if isinstance(v, (int, float)) else None for v in vals[:len(labels)]]
    return {'categories': labels, 'series': series}

def extract_visible_table(ws, header_rows, data_start_row, max_scan_row, start_col, end_col,
                           key_col=None, stop_values=(None, '', 'Total', 'TOTAL'),
                           stop_on_fill=False, fill_cols=None):
    """Extrae un cuadro de Excel respetando lo que el analista deja oculto:
       - salta columnas ocultas dentro de start_col..end_col
       - salta filas ocultas dentro del rango de datos
       - arma encabezados combinando header_rows (con forward-fill de celdas combinadas)
       - detecta sola donde termina la tabla (primera fila VISIBLE cuya
         columna clave esta vacia o dice 'Total'), asi que si el analista
         agrega una fila nueva al final en Excel, el proximo refresh la toma
         sin tocar el codigo (siempre que no pase de max_scan_row)
       - con stop_on_fill=True corta ademas en la primera fila VISIBLE que
         este pintada con un color de fondo. Se usa para dejar afuera el
         bloque de proyeccion: cuando el analista despinta un mes porque ya
         tiene el dato observado, ese mes entra solo en el proximo refresh,
         sin tocar el codigo. fill_cols limita que columnas se miran para
         decidir si la fila esta pintada (por defecto, todas las visibles).
       - descarta columnas espaciadoras (encabezado y datos vacios) y
         columnas que duplican exactamente la primera columna (ej.: una
         fecha repetida para alinear dos bloques del mismo cuadro)
    Devuelve {'headers': [...], 'rows': [[...], ...]}
    """
    from openpyxl.utils import get_column_letter, column_index_from_string

    def is_hidden_col(letter):
        d = ws.column_dimensions.get(letter)
        return bool(d and d.hidden)

    def is_hidden_row(r):
        d = ws.row_dimensions.get(r)
        return bool(d and d.hidden)

    col_start_idx = column_index_from_string(start_col)
    col_end_idx = column_index_from_string(end_col)
    cols = [get_column_letter(i) for i in range(col_start_idx, col_end_idx + 1)
            if not is_hidden_col(get_column_letter(i))]

    key_col = key_col or start_col

    def row_is_filled(r):
        for c in (fill_cols or cols):
            f = ws[f"{c}{r}"].fill
            if f is not None and f.patternType not in (None, 'none'):
                return True
        return False

    first_data_row = None
    r = data_start_row
    while r <= max_scan_row:
        if not is_hidden_row(r):
            first_data_row = r
            break
        r += 1

    data_rows = []
    if first_data_row is not None:
        for r in range(first_data_row, max_scan_row + 1):
            if is_hidden_row(r):
                continue
            v = ws[f"{key_col}{r}"].value
            if v in stop_values:
                break
            if stop_on_fill and row_is_filled(r):
                break
            data_rows.append(r)

    def build_header_layer(hr):
        raw = {c: ws[f"{c}{hr}"].value for c in cols}
        merges = [mc for mc in ws.merged_cells.ranges if mc.min_row <= hr <= mc.max_row]
        filled = dict(raw)
        for c in cols:
            if filled[c] is not None:
                continue
            ci = column_index_from_string(c)
            for mc in merges:
                if mc.min_col <= ci <= mc.max_col:
                    topleft = ws.cell(row=mc.min_row, column=mc.min_col).value
                    if topleft is not None:
                        filled[c] = topleft
                    break
        return filled

    header_layers = [build_header_layer(hr) for hr in header_rows]
    headers = []
    for c in cols:
        parts = []
        for layer in header_layers:
            v = layer.get(c)
            if v not in (None, ''):
                s = str(v).replace('\n', ' ').strip()
                if s and s not in parts:
                    parts.append(s)
        headers.append(' · '.join(parts))

    def fmt_cell(v):
        if isinstance(v, datetime):
            return v.strftime('%Y-%m')
        if isinstance(v, float):
            return round(v, 4)
        return v

    rows = [[fmt_cell(ws[f"{c}{r}"].value) for c in cols] for r in data_rows]

    keep = []
    for i in range(len(cols)):
        has_header = bool(headers[i])
        has_data = any(row[i] not in (None, '') for row in rows)
        if has_header or has_data:
            keep.append(i)
    cols = [cols[i] for i in keep]
    headers = [headers[i] for i in keep]
    rows = [[row[i] for i in keep] for row in rows]

    if len(cols) > 1:
        keep2 = [0]
        for i in range(1, len(cols)):
            dup = all(row[i] == row[0] for row in rows) if rows else False
            if not dup:
                keep2.append(i)
        cols = [cols[i] for i in keep2]
        headers = [headers[i] for i in keep2]
        rows = [[row[i] for i in keep2] for row in rows]

    return {'headers': headers, 'rows': rows}

# =====================================================================
#  PRECIOS
# =====================================================================
def extract_precios(status):
    import openpyxl

    if not os.path.exists(EXCEL_PATHS["ipc"]):
        status.fail("Precios", f"No se encontró: {EXCEL_PATHS['ipc']}")
        return None
    if not os.path.exists(EXCEL_PATHS["gd"]):
        status.fail("Precios - GD", f"No se encontró: {EXCEL_PATHS['gd']}")
        return None

    data = {}

    # ---- IPC último + series ----
    # read_only=False para acceso random por celda (col DK = 115) — BytesIO ya está en RAM
    wb = _open_wb(EXCEL_PATHS["ipc"], read_only=False)
    ws = wb["1. Nuevo IPC Nacional"]

    last = None
    for r in range(ws.max_row, 0, -1):
        if ws.cell(r, 20).value is not None:  # col T (nucleo m/m)
            last = r
            break

    def g(r, col):
        return ws.cell(r, col_idx(col)).value

    # Último mes
    fecha = g(last, 'A')
    data['ultimo'] = {
        "fecha": fecha.strftime("%Y-%m-%d") if isinstance(fecha, datetime) else str(fecha),
        "general_mm":   fmt_n(g(last, 'AF')),
        "general_ia":   fmt_n(g(last, 'AT')),
        "nucleo_mm":    fmt_n(g(last, 'T')),
        "nucleo_ia":    fmt_n(g(last, 'U')),
        "estacional_mm": fmt_n(g(last, 'P')),
        "estacional_ia": fmt_n(g(last, 'BV')),
        "regulados_mm": fmt_n(g(last, 'V')),
        "regulados_ia": fmt_n(g(last, 'W'))
    }

    # Series 24 meses
    series = []
    for r in range(max(6, last - 24), last + 1):
        fecha = g(r, 'A')
        if not isinstance(fecha, datetime): continue
        series.append({
            "fecha": fecha.strftime("%Y-%m-%d"),
            "general_mm": fmt_n(g(r, 'AF')), "general_ia": fmt_n(g(r, 'AT')),
            "nucleo_mm": fmt_n(g(r, 'T')),   "nucleo_ia": fmt_n(g(r, 'U')),
            "estacional_mm": fmt_n(g(r, 'P')), "estacional_ia": fmt_n(g(r, 'BV')),
            "regulados_mm": fmt_n(g(r, 'V')), "regulados_ia": fmt_n(g(r, 'W'))
        })
    data['series_24m'] = series

    # ---- Chart 21: '1. Nuevo IPC Nacional'!A17:A114, DJ, DK, AT ----
    def range_get(sheet, col, r1, r2):
        out = []
        for r in range(r1, r2+1):
            v = sheet.cell(r, col_idx(col)).value
            out.append(v)
        return out

    # el final lo detecta solo: antes estaba fijo en la fila 114 y la serie
    # se quedo clavada en ene-26 aunque el Excel siguiera creciendo
    fin21 = last_data_row(ws, ['DJ', 'DK', 'AT'], 17)
    cats = range_get(ws, 'A', 17, fin21)
    chart21 = []
    mensual21 = range_get(ws, 'DJ', 17, fin21)
    prom21    = range_get(ws, 'DK', 17, fin21)
    varia21   = range_get(ws, 'AT', 17, fin21)
    for i, c in enumerate(cats):
        if c is None: continue
        chart21.append({
            "fecha": c.strftime("%Y-%m-%d") if isinstance(c, datetime) else str(c),
            "mensual": mensual21[i],
            "promedio_anual": prom21[i],
            "var_ia": varia21[i]
        })
    data['chart21'] = chart21
    if chart21:
        _avisar_si_viejo(status, "Precios - chart21", chart21[-1]['fecha'], meses=3)

    # ---- Chart 23: A6:.., AF, AT, U, W, DK (el final tambien se detecta solo) ----
    fin23 = last_data_row(ws, ['AF', 'AT', 'U', 'W', 'DK'], 6)
    cats5 = range_get(ws, 'A', 6, fin23)
    chart23 = []
    var_men = range_get(ws,'AF',6,fin23)
    var_ia5 = range_get(ws,'AT',6,fin23)
    nucleo_ia = range_get(ws,'U',6,fin23)
    w_series = range_get(ws,'W',6,fin23)
    prom_men = range_get(ws,'DK',6,fin23)
    for i, c in enumerate(cats5):
        if c is None: continue
        chart23.append({
            "fecha": c.strftime("%Y-%m-%d") if isinstance(c, datetime) else str(c),
            "var_men": var_men[i], "var_ia": var_ia5[i],
            "nucleo_ia": nucleo_ia[i], "regulados_ia": w_series[i],
            "prom_men": prom_men[i]
        })
    data['chart23'] = chart23

    # ---- Chart 22 (RPM): '4. Proyecciones'!B100:B201, C/E/F/H ----
    ws2 = wb["4. Proyecciones"]
    chart22 = []
    fin22 = last_data_row(ws2, ['C', 'E', 'F', 'H'], 100)
    for r in range(100, fin22 + 1):
        fecha = ws2.cell(r, 2).value
        if fecha is None: continue
        chart22.append({
            "fecha": fecha.strftime("%Y-%m-%d") if isinstance(fecha, datetime) else str(fecha),
            "rpm_mm": fmt_n(ws2.cell(r, 3).value),
            "ipc_gba": fmt_n(ws2.cell(r, 5).value),
            "ipc_nac": fmt_n(ws2.cell(r, 6).value),
            "rpm_ia": fmt_n(ws2.cell(r, 8).value)
        })
    data['chart22'] = chart22

    # ---- Chart 5: Gráficos de dispersión - Hoja3 ----
    wb_gd = _open_wb(EXCEL_PATHS["gd"])
    ws_gd = wb_gd["Hoja3"]
    CATS = {
        'Pan y cereales':'Bienes','Carnes y derivados':'Bienes',
        'Leche, productos lácteos y huevos':'Bienes','Aceites, grasas y manteca':'Bienes',
        'Frutas y verduras':'Bienes','Azúcar, dulces, chocolates':'Bienes',
        'Bebidas':'Bienes','Tabaco':'Bienes','Indumentaria':'Bienes',
        'Medicamentos':'Bienes','Medicamentos ':'Bienes',
        'Adquisición de vehículos':'Bienes','Combustibles':'Bienes',
        'Electrodomésticos':'Bienes','Bienes y servicios para la conservación del hogar':'Bienes',
        'Bienes':'Bienes',
        'Vivienda':'Servicios','Alquiler de la vivienda y gastos conexos':'Servicios',
        'Prepagas':'Servicios','Servicios recreativos':'Servicios','Servicios recreativos ':'Servicios',
        'Educación':'Servicios','Restaurantes':'Servicios','Servicios':'Servicios',
        'Electricidad, gas y otros combustibles':'Regulados','Transporte público':'Regulados',
        'Servicios  de telefonía e internet':'Regulados','Servicios de telefonía e internet':'Regulados',
        'Tarifa de Agua':'Regulados','Regulados':'Regulados',
        'Salarios Formales Privados':'Salarios','Salarios Informales':'Salarios',
        'Salarios Informales ':'Salarios','Jubilación Mínima c/Bono':'Salarios',
        'Jubilación s/Bono':'Salarios','Salarios Formales Públicos':'Salarios',
        'AUH':'Salarios','Salario de Cuentapropistas':'Salarios',
        'Dólar CCL':'Dólar','Dólar Oficial':'Dólar',
        'ICC(Materiales p/construcción)':'Construcción','ICC (Nivel Gral.)':'Construcción',
        'ICC (Mano de Obra)':'Construcción','ICC (Gastos Generales)':'Construcción',
        'IPIM (Nivel General)':'Mayorista','IPIM (Nacionales)':'Mayorista',
        'IPIM (Importados)':'Mayorista'
    }
    points = []
    for r in list(range(3, 42)) + list(range(44, 48)):
        label = ws_gd.cell(r, 1).value
        x = ws_gd.cell(r, 6).value
        y = ws_gd.cell(r, 7).value
        if label and x is not None and y is not None:
            cat = CATS.get(label, 'Otros') if not isinstance(label, str) else CATS.get(label.strip(), 'Otros')
            points.append({"label": str(label).strip(), "categoria": cat, "x": x, "y": y})
    def _fmt_scatter_label(raw):
        """'Nov23-Jun26' → 'Nov 2023 – Jun 2026 (gap vs Nivel general)'"""
        import re as _re
        if not raw:
            return str(raw or "")
        mt = _re.match(r'([A-Za-z]+)(\d{2})-([A-Za-z]+)(\d{2})', str(raw).strip())
        if mt:
            return f"{mt.group(1)} 20{mt.group(2)} – {mt.group(3)} 20{mt.group(4)} (gap vs Nivel general)"
        return str(raw)

    data['chart5'] = {
        "title": "Precios relativos: cuánto corregimos y cuánto falta corregir",
        "x_label": _fmt_scatter_label(ws_gd.cell(1, 6).value),
        "y_label": _fmt_scatter_label(ws_gd.cell(1, 7).value),
        "points": points
    }

    # ---- Proyección RPM (Cuadro Mensual - Capítulos Nuevo.xlsx, hoja siguiente a 'base') ----
    if os.path.exists(EXCEL_PATHS["rpm_cuadro"]):
        try:
            wb_cm = _open_wb(EXCEL_PATHS["rpm_cuadro"])
            # La hoja de datos es siempre la que está al lado de 'base' (índice 1)
            # Las hojas tienen formato YYMM (ej: '2605'), ordenadas de más reciente a más antigua
            idx_base = next((i for i, s in enumerate(wb_cm.sheetnames) if s.strip().lower() == 'base'), None)
            if idx_base is not None and idx_base + 1 < len(wb_cm.sheetnames):
                hoja = wb_cm.sheetnames[idx_base + 1]
            else:
                # Fallback: hoja YYMM más reciente
                yymm = sorted([s for s in wb_cm.sheetnames if s.strip().isdigit() and len(s.strip()) == 4], reverse=True)
                hoja = yymm[0] if yymm else None
            if hoja:
                ws_cm = wb_cm[hoja]
                # Sección limpia: filas 26-40 (1-indexed), cols A-D
                # Fila 26: título, fila 30+: datos (capítulo, mensual, anual, acumulada)
                rows = list(ws_cm.iter_rows(min_row=26, max_row=42, max_col=4, values_only=True))
                titulo = str(rows[0][0] or "").strip()
                proy = {
                    "titulo": titulo,
                    "header_periodo": f"Proyección — RPM Eco Go · {hoja}",
                    "filas": []
                }
                for r in rows:
                    cap = r[0]
                    if not cap or not isinstance(cap, str): continue
                    cap = cap.strip()
                    if not cap or cap.startswith("Fuente") or cap.startswith("PIEBGEB"): continue
                    mensual = r[1]; anual = r[2]; acum = r[3]
                    if mensual is None and anual is None: continue
                    proy["filas"].append({
                        "capitulo": cap,
                        "mensual": fmt_n(mensual),
                        "anual":   fmt_n(anual),
                        "acumulada": fmt_n(acum)
                    })
                data['proyeccion'] = proy
                status.ok("Precios - Proyección RPM", f"hoja {hoja}, {len(proy['filas'])} filas")
            else:
                _keep_old_proy(data, status)
        except Exception as e:
            status.warn("Precios - Proyección RPM", f"error: {e}; mantengo datos previos")
            _keep_old_proy(data, status)
    else:
        _keep_old_proy(data, status)

    return data

def _keep_old_proy(data, status):
    """Si no hay CM-DB, conservar la proyección anterior del JSON existente."""
    old = load_existing("precios")
    if old and "proyeccion" in old:
        data["proyeccion"] = old["proyeccion"]
        status.warn("Precios - Proyección RPM", "CM-DB no encontrado, mantengo dato previo")
    else:
        status.warn("Precios - Proyección RPM", "sin CM-DB ni dato previo")

# =====================================================================
#  EMPLEO (EPH + Cuadro Trim + SIPA + Provincias)
# =====================================================================
def _sin_acentos(txt):
    import unicodedata
    s = unicodedata.normalize('NFKD', str(txt))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s.replace('.', ' ')).strip().upper()

def _hoja_empleo(wb, candidatas):
    """Primera hoja que exista de la lista. Acepta el nombre nuevo y el viejo,
    asi el refresh sigue andando si se vuelve al Excel anterior."""
    por_nombre = {n.strip().lower(): n for n in wb.sheetnames}
    for c in candidatas:
        if c.strip().lower() in por_nombre:
            return wb[por_nombre[c.strip().lower()]]
    return None

def _mapa_eph(ws):
    """Ubica, en el cuadro de tasas EPH, la columna del periodo y la de cada
    indicador, leyendo los encabezados en vez de dar por fijas las posiciones.

    Devuelve (col_fecha, col_etiqueta, {clave: columna}, primera_fila_de_datos).
    col_etiqueta es la columna de texto del periodo ("I-26", "may-91") cuando el
    Excel la trae aparte de la fecha; es la que se muestra en el dashboard.

    En los dos formatos conocidos la columna que lleva el nombre del indicador
    es tambien la del total (las de al lado son GBA y Resto), asi que alcanza
    con encontrar donde esta escrito cada nombre."""
    def es_periodo(v):
        if isinstance(v, datetime):
            return True
        if isinstance(v, str):
            t = v.strip()
            return bool(re.match(r'(IV|III|II|I)-\d{2,4}$', t)
                        or re.match(r'\d\s*º?\s*trim\s*\d{4}', t, re.IGNORECASE)
                        or re.match(r'[a-zA-Z]{3}-\d{2,4}$', t))
        return False

    # primera fila con un periodo en alguna de las dos primeras columnas
    fila_datos, col_fecha = None, 1
    for r in range(1, 30):
        for c in (1, 2):
            if es_periodo(ws.cell(r, c).value):
                fila_datos = r
                break
        if fila_datos:
            break
    if fila_datos is None:
        return 1, None, {}, 8

    # de las dos primeras columnas, preferir la que trae fechas de verdad
    for c in (1, 2):
        if isinstance(ws.cell(fila_datos, c).value, datetime):
            col_fecha = c
            break
    else:
        col_fecha = 1 if es_periodo(ws.cell(fila_datos, 1).value) else 2

    # la otra, si es texto, es la etiqueta que escribe el analista
    col_etiqueta = None
    for c in (1, 2):
        if c != col_fecha and isinstance(ws.cell(fila_datos, c).value, str):
            col_etiqueta = c
            break

    # el nombre de cada indicador esta en alguna fila de encabezado de arriba
    REGLAS = [
        ('subocup_nodem', lambda t: 'SUBOCUP' in t and 'NO DEMANDANTE' in t),
        ('subocup_dem',   lambda t: 'SUBOCUP' in t and 'DEMANDANTE' in t),
        ('subocup',       lambda t: 'SUBOCUP' in t),
        ('ocup_dem',      lambda t: 'OCUPADA' in t and 'DEMANDANTE' in t),
        ('desocup',       lambda t: t.startswith('DESOCUP')),
        ('empleo',        lambda t: t == 'EMPLEO'),
        ('actividad',     lambda t: t == 'ACTIVIDAD'),
    ]
    cols = {}
    for r in range(1, fila_datos):
        for c in range(1, min(ws.max_column or 30, 40) + 1):
            v = ws.cell(r, c).value
            if not isinstance(v, str):
                continue
            t = _sin_acentos(v)
            for clave, test in REGLAS:
                if clave not in cols and test(t):
                    cols[clave] = c
                    break
    return col_fecha, col_etiqueta, cols, fila_datos

def _filas_encabezado(ws, col_cat=2, col_dato=3, max_scan=14):
    """Para los cuadros tipo 'Cuadro empleo trim' / 'Cuadro SIPA ext': encuentra
    la primera fila de datos (categoria en col_cat y numero en col_dato) y
    deduce que los periodos estan dos filas arriba y las unidades una arriba.

    Al pasar a Empleo_limpio.xlsx estos cuadros bajaron una fila; con esto se
    acomodan solos en vez de tener el numero de fila escrito en el codigo."""
    for r in range(1, max_scan):
        cat = ws.cell(r, col_cat).value
        for c in range(col_dato, col_dato + 6):
            if isinstance(cat, str) and cat.strip() and isinstance(ws.cell(r, c).value, (int, float)):
                return max(1, r - 2), max(1, r - 1), r
    return 2, 3, 4

def extract_empleo(status):
    import openpyxl
    if not os.path.exists(EXCEL_PATHS["empleo"]):
        status.fail("Empleo", f"No se encontró: {EXCEL_PATHS['empleo']}")
        return None

    wb = _open_wb(EXCEL_PATHS["empleo"])
    data = {}

    # ---- Tasas EPH ----
    # Ni la hoja, ni la fila donde arrancan los datos, ni las columnas de cada
    # indicador estan fijas: al pasar de Empleo_nuevo.xlsx a Empleo_limpio.xlsx
    # cambio el nombre de la hoja, se sumo una columna "Fecha" (corriendo todo
    # una posicion) y los datos pasaron de la fila 8 a la 6. Se ubica cada
    # indicador por su encabezado, que es lo unico que se mantuvo igual.
    ws = _hoja_empleo(wb, ['EPH_Resumen Tasas', 'Tasas EPH'])
    col_fecha, col_etiqueta, cols_eph, fila_datos = _mapa_eph(ws)
    if not cols_eph:
        status.fail("Empleo - Tasas EPH",
                    f"no pude ubicar los indicadores en la hoja '{ws.title}'")
        return None

    # El final se detecta solo. Antes estaba fijo y el cuadro se quedaba en
    # IV-25 aunque I-26 ya estuviera cargado justo debajo. Dos guardas, porque
    # abajo del cuadro la hoja puede seguir con otro bloque que arranca de nuevo
    # en un periodo viejo:
    #   - cortar tras varias filas seguidas sin periodo (hay huecos sueltos
    #     adentro del cuadro, asi que una sola no alcanza)
    #   - cortar si el periodo deja de avanzar en el tiempo
    eph = []
    _vacias, _ult_ord = 0, None
    for r in range(fila_datos, fila_datos + 400):
        fecha = ws.cell(r, col_fecha).value
        if fecha is None:
            _vacias += 1
            if eph and _vacias >= 4: break
            continue
        if isinstance(fecha, datetime):
            fecha_str = fecha.strftime("%Y-%m-%d")
            ord_idx = (fecha.year * 4) + (fecha.month - 1) // 3
            label = fecha.strftime("%b-%Y")
        elif isinstance(fecha, str):
            m = re.match(r'(IV|III|II|I)-(\d{2,4})', fecha.strip())
            if m:
                qmap = {'I':1,'II':2,'III':3,'IV':4}
                q = qmap[m.group(1)]
                yy = int(m.group(2))
                if yy < 100: yy += 2000
                label = fecha.strip()
            else:
                m2 = re.match(r'(\d)\s*º?\s*trim\s*(\d{4})', fecha.strip(), re.IGNORECASE)
                if not m2:
                    _vacias += 1
                    if eph and _vacias >= 4: break
                    continue
                q = int(m2.group(1))
                yy = int(m2.group(2))
                label = f"{['','I','II','III','IV'][q]}-{str(yy)[2:]}"
            fecha_str = f"{yy}-{(q-1)*3+1:02d}-01"
            ord_idx = (yy * 4) + (q - 1)
        else:
            _vacias += 1
            if eph and _vacias >= 4: break
            continue
        # si el periodo dejo de avanzar, esto ya es otro bloque de la hoja
        if _ult_ord is not None and ord_idx <= _ult_ord:
            break
        _vacias, _ult_ord = 0, ord_idx
        # si el Excel trae la etiqueta escrita ("I-26"), esa manda: es la que se
        # muestra en el dashboard y la que venia usando el formato anterior
        if col_etiqueta:
            _et = ws.cell(r, col_etiqueta).value
            if isinstance(_et, str) and _et.strip():
                label = _et.strip()
        fila = {"fecha": fecha_str, "ord": ord_idx, "label": label}
        for clave, col in cols_eph.items():
            fila[clave] = fmt_n(ws.cell(r, col).value)
        eph.append(fila)
    eph.sort(key=lambda x: x['ord'])
    data['eph'] = eph
    data['eph_ultimo'] = eph[-1] if eph else None

    # ---- Cuadro empleo trim ----
    # Los periodos salen de la fila 3 del propio Excel. Antes estaban escritos
    # a mano en el codigo: cuando el analista intercalo una columna, las
    # etiquetas quedaron corridas y el dashboard mostraba cada valor bajo el
    # trimestre equivocado, sin que nada avisara.
    ws = _hoja_empleo(wb, ['Cuadro empleo trim'])
    f_lab, f_uni, f_ini = _filas_encabezado(ws)
    cols_trim = cols_por_encabezado(ws, fila_label=f_lab, fila_unidad=f_uni)
    trim = {"periodos": [lab for _, lab, _ in cols_trim], "filas": []}
    _dup = [p for p in set(trim["periodos"]) if trim["periodos"].count(p) > 1]
    if _dup:
        status.warn("Empleo - Cuadro trim",
                    f"hay periodos repetidos en la fila {f_lab} del Excel: {_dup} — revisar los encabezados")
    for r in range(f_ini, f_ini + 16):
        cat = ws.cell(r, 2).value
        if not cat: continue
        valores = []
        for col_n, _, _ in cols_trim:
            v = ws.cell(r, col_n).value
            valores.append(v if isinstance(v, (int, float)) else None)
        trim["filas"].append({"categoria": str(cat).strip(), "valores": valores})
    data['trim'] = trim

    # ---- Cuadro SIPA ext (2) ----
    # Mismo criterio: los meses salen de la fila 2 y las columnas "Dif." de la
    # fila 3, en vez de estar escritos a mano. El "vs <mes>" de cada diferencia
    # se arma resolviendo el (n) contra el mes que lleva ese numero.
    ws = _hoja_empleo(wb, ['Cuadro SIPA ext', 'Cuadro SIPA ext (2)'])
    s_lab, s_uni, s_ini = _filas_encabezado(ws)
    cols_sipa = []
    ref_mes = {}          # "(1)" -> "jun-12"
    for c, lab, uni in cols_por_encabezado(ws, fila_label=s_lab, fila_unidad=s_uni, col_fin=20):
        m = re.search(r'\((\d+)\)', uni or '')
        if m:
            ref_mes[m.group(1)] = lab
        cols_sipa.append({"col": c, "header": lab, "sub": (uni or '').split('(')[0].strip(), "tipo": "stock"})
    for c in range(3, 21):
        v = ws.cell(s_uni, c).value
        txt = str(v).replace('\n', ' ').strip() if v else ''
        if not txt.lower().startswith('dif'):
            continue
        nums = re.findall(r'\((\d+)\)', txt)
        contra = ref_mes.get(nums[1]) if len(nums) > 1 else None
        cols_sipa.append({"col": c, "header": re.sub(r'\s+', ' ', txt),
                          "sub": f"vs {contra}" if contra else '', "tipo": "diff"})
    cols_sipa.sort(key=lambda x: x["col"])

    sipa = {"cols": [{"header": c["header"], "sub": c["sub"], "tipo": c["tipo"]} for c in cols_sipa],
            "filas": []}
    for r in range(s_ini, s_ini + 10):
        cat = ws.cell(r, 2).value
        if not cat: continue
        if str(cat).strip().lower().startswith('fuente'):
            sipa["fuente"] = str(cat).strip()   # nota al pie, no fila de datos
            continue
        valores = []
        for c in cols_sipa:
            v = ws.cell(r, c["col"]).value
            valores.append(v if isinstance(v, (int, float)) else None)
        sipa["filas"].append({"categoria": str(cat).strip(), "valores": valores})
    data['sipa'] = sipa

    # ---- Provincias (solo en el Excel viejo) ----
    # Empleo_limpio.xlsx ya no trae la Hoja7: lo mas parecido es SIPA_provincia,
    # que es otra tabla (serie mensual completa, con las provincias en columnas
    # en vez de en filas). No se remapea porque ninguna pagina lee esta clave:
    # el panel Provincias del dashboard sale de assets/data/sipa_provincias.js.
    ws = _hoja_empleo(wb, ['Hoja7'])
    if ws is not None:
        provincias = {"fechas": [], "datos": []}
        for c in range(3, 9):
            v = ws.cell(3, c).value
            if isinstance(v, datetime):
                provincias["fechas"].append(v.strftime("%Y-%m"))
        for r in range(5, 30):
            prov = ws.cell(r, 2).value
            if not prov: continue
            vals = []
            for c in range(3, 9):
                v = ws.cell(r, c).value
                vals.append(v if isinstance(v, (int, float)) else None)
            if any(v is not None for v in vals):
                provincias["datos"].append({"provincia": str(prov).strip(), "valores": vals})
        data['provincias'] = provincias

    return data

# =====================================================================
#  SALARIOS
# =====================================================================
def extract_salarios(status):
    import openpyxl
    if not os.path.exists(EXCEL_PATHS["salarios"]):
        status.fail("Salarios", f"No se encontró: {EXCEL_PATHS['salarios']}")
        return None

    wb = _open_wb(EXCEL_PATHS["salarios"])
    data = {}

    # ---- G Sal real: 1.1 INDEC desde A186, CE/CF/CH/CI ----
    # el final se detecta solo (antes estaba fijo en 298 y se cortaba en abr-26)
    ws = wb["1.1 INDEC"]
    sal_real = []
    fin_sal = last_data_row(ws, ['CE', 'CF', 'CH', 'CI'], 186)
    for r in range(186, fin_sal + 1):
        fecha = ws.cell(r, 1).value
        if not isinstance(fecha, datetime): continue
        priv = fmt_n(ws.cell(r, 83).value)  # CE
        pub  = fmt_n(ws.cell(r, 84).value)  # CF
        nor  = fmt_n(ws.cell(r, 86).value)  # CH
        tot  = fmt_n(ws.cell(r, 87).value)  # CI
        if any(v is not None for v in [priv, pub, nor, tot]):
            sal_real.append({
                "fecha": fecha.strftime("%Y-%m-%d"),
                "label": fecha.strftime("%b-%y"),
                "priv": priv, "pub": pub, "nor": nor, "tot": tot
            })
    data['sal_real'] = sal_real
    if sal_real:
        _avisar_si_viejo(status, "Salarios - serie real", sal_real[-1]['fecha'], meses=4)

    # ---- Cuadro INDEC 1.3 ----
    ws = wb["1.3 Cuadro INDEC"]
    fecha_actual = ws.cell(3, 2).value
    fecha_compar = ws.cell(3, 11).value
    def iso(v):
        if isinstance(v, datetime): return v.strftime("%Y-%m-%d")
        return str(v) if v else ''
    cuadro = {
        "fecha_actual": iso(fecha_actual),
        "fecha_comparacion": iso(fecha_compar),
        "headers": [],
        "filas": []
    }
    for c in range(3, 11):
        v = ws.cell(4, c).value
        cuadro["headers"].append(str(v).replace('\n',' ').strip() if v else '')
    for r in range(5, 10):
        cat = ws.cell(r, 2).value
        if not cat: continue
        valores = []
        for c in range(3, 11):
            v = ws.cell(r, c).value
            valores.append(v if isinstance(v, (int, float)) else None)
        cuadro["filas"].append({"categoria": str(cat).strip(), "valores": valores})
    data['cuadro'] = cuadro

    # ---- G real 21: 1.6. Datos grafico base 21 desde A5, cols B-H ----
    # el final se detecta solo (antes estaba fijo en 56 y se cortaba en mar-26)
    ws = wb["1.6. Datos grafico base 21"]
    real_21 = []
    keys = [(2,'sal_priv'),(3,'sal_pub_nac'),(4,'sal_pub_prov'),
            (5,'jub_min'),(6,'jub_no_min'),(7,'no_reg'),(8,'auh')]
    fin_21 = last_data_row(ws, ['B', 'C', 'D', 'E', 'F', 'G', 'H'], 5)
    for r in range(5, fin_21 + 1):
        fecha = ws.cell(r, 1).value
        if not isinstance(fecha, datetime): continue
        point = {"fecha": fecha.strftime("%Y-%m-%d"), "label": fecha.strftime("%b-%y")}
        for c, key in keys:
            point[key] = fmt_n(ws.cell(r, c).value)
        if any(point[k] is not None for k in [x[1] for x in keys]):
            real_21.append(point)
    data['real_21'] = real_21

    return data

# =====================================================================
#  TIPO DE CAMBIO (TCR bandas + Rofex)
# =====================================================================
def extract_tipo_cambio(status):
    import openpyxl
    from datetime import datetime, date, timedelta
    if not os.path.exists(EXCEL_PATHS["rofex"]):
        status.fail("Rofex", f"No se encontró: {EXCEL_PATHS['rofex']}")
        return None

    data = {}

    # ---- TCN series (TCR bandas - hoja TCN) ----
    # Col C=fecha, D=oficial, E=CCL, F=Banda inferior, G=Banda superior
    # Si está bloqueado/sincronizando, mantener datos previos
    tcn = None
    if os.path.exists(EXCEL_PATHS["tcr_bandas"]):
        try:
            wb = _open_wb(EXCEL_PATHS["tcr_bandas"])
            ws = wb["TCN"]
            tcn = []
            for row in ws.iter_rows(min_row=3, values_only=True):  # iter_rows es O(n), no O(n²)
                fecha = row[2]  # col C = índice 2
                if not isinstance(fecha, (datetime, date)): continue
                point = {
                    "fecha":    fecha.strftime("%Y-%m-%d"),
                    "oficial":  fmt_n(row[3]),   # D
                    "ccl":      fmt_n(row[4]),   # E
                    "banda_inf":fmt_n(row[5]),   # F
                    "banda_sup":fmt_n(row[6]),   # G
                }
                if any(v is not None for k, v in point.items() if k != 'fecha'):
                    tcn.append(point)
        except Exception as e:
            status.warn("TCR bandas", f"no se pudo leer ({e}); mantengo datos previos")
            tcn = None

    if tcn is None:
        # Fallback: usar JSON existente
        old = load_existing("tipo-cambio")
        if old and "tcn_series" in old:
            tcn = old["tcn_series"]
    data['tcn_series'] = tcn or []

    # ---- TCN serie LARGA desde com3500 (A3500 BCRA desde 2002) ----
    if os.path.exists(EXCEL_PATHS["com3500"]):
        try:
            import xlrd
            wb_c = xlrd.open_workbook(EXCEL_PATHS["com3500"])
            sh = wb_c.sheet_by_name("TCR diario y TCNPM")
            def xl_date(n):
                return (datetime(1899, 12, 30) + timedelta(days=int(n))).strftime("%Y-%m-%d")
            tcn_long = []
            for r in range(4, sh.nrows):
                fecha = sh.cell(r, 2).value
                val = sh.cell(r, 3).value
                if isinstance(fecha, (int, float)) and isinstance(val, (int, float)) and val > 0:
                    tcn_long.append({"fecha": xl_date(fecha), "oficial": val})
            data['tcn_long'] = tcn_long
            status.ok("Tipo de Cambio - com3500", f"{len(tcn_long)} puntos · {tcn_long[0]['fecha']} → {tcn_long[-1]['fecha']}")
        except ImportError:
            status.warn("Tipo de Cambio - com3500", "falta xlrd (instalar: pip install xlrd)")
        except Exception as e:
            status.warn("Tipo de Cambio - com3500", f"error: {e}")
    else:
        status.warn("Tipo de Cambio - com3500", "archivo no encontrado")

    # ---- Series Blue / MEP / CCL históricas (Copia de Blue.xlsx - hoja Diario) ----
    # Col A=fecha, B=Blue, C=MEP, D=CCL
    if os.path.exists(EXCEL_PATHS["copia_blue"]):
        try:
            wb_b = _open_wb(EXCEL_PATHS["copia_blue"])
            ws_b = wb_b["Diario"]
            blue_long, mep_long, ccl_long = [], [], []
            for row in ws_b.iter_rows(min_row=2, values_only=True):  # iter_rows es O(n), no O(n²)
                fecha = row[0]
                if not isinstance(fecha, (datetime, date)): continue
                fecha_str = fecha.strftime("%Y-%m-%d") if isinstance(fecha, datetime) else fecha.isoformat()
                blue_v = row[1]
                mep_v  = row[2]
                ccl_v  = row[3]
                if isinstance(blue_v, (int, float)) and blue_v > 0:
                    blue_long.append({"fecha": fecha_str, "valor": blue_v})
                if isinstance(mep_v, (int, float)) and mep_v > 0:
                    mep_long.append({"fecha": fecha_str, "valor": mep_v})
                if isinstance(ccl_v, (int, float)) and ccl_v > 0:
                    ccl_long.append({"fecha": fecha_str, "valor": ccl_v})
            data['blue_long'] = blue_long
            data['mep_long']  = mep_long
            data['ccl_long']  = ccl_long
            status.ok("Tipo de Cambio - Blue/MEP/CCL",
                      f"Blue {len(blue_long)} pts · MEP {len(mep_long)} pts · CCL {len(ccl_long)} pts")
        except Exception as e:
            status.warn("Tipo de Cambio - Blue/MEP/CCL", f"error: {e}")
    else:
        status.warn("Tipo de Cambio - Blue/MEP/CCL", "Copia de Blue.xlsx no encontrado")

    # ---- Rofex (Cuadros para informes) ----
    # Salta filas y columnas OCULTAS del Excel (regla del usuario)
    # read_only=False es necesario para que column_dimensions / row_dimensions funcionen
    wb2 = _open_wb(EXCEL_PATHS["rofex"], read_only=False)
    ws2 = wb2["Cuadros para informes"]

    # Detectar ocultas
    hidden_cols = set()
    for letter, dim in ws2.column_dimensions.items():
        if dim.hidden:
            hidden_cols.add(openpyxl.utils.column_index_from_string(letter))
    hidden_rows = set()
    for r_num, dim in ws2.row_dimensions.items():
        if dim.hidden:
            hidden_rows.add(r_num)

    BLOQUES = [
        {"id":"nominal", "label":"Nominal $/USD",  "fmt":"money", "header_row":5,  "month_row":6,  "data_start":7,  "data_end":29},
        {"id":"tna",     "label":"TNA %",          "fmt":"pct",   "header_row":36, "month_row":37, "data_start":38, "data_end":60},
        {"id":"varmens", "label":"Var. % mensual", "fmt":"pct",   "header_row":66, "month_row":67, "data_start":68, "data_end":90},
        {"id":"interes", "label":"Interés abierto","fmt":"int",   "header_row":96, "month_row":97, "data_start":98, "data_end":120},
    ]
    rofex = {}
    for b in BLOQUES:
        # Meses: saltar columnas ocultas
        meses = []
        col_indices = []
        for c in range(3, 25):
            if c in hidden_cols: continue
            v = ws2.cell(b["month_row"], c).value
            if isinstance(v, (datetime, date)):
                meses.append(v.strftime("%Y-%m"))
                col_indices.append(c)
            elif v is None and meses:
                break

        # Filas: saltar ocultas y filas sin fecha
        filas = []
        for r in range(b["data_start"], b["data_end"]+1):
            if r in hidden_rows: continue
            fecha = ws2.cell(r, 2).value
            if not isinstance(fecha, (datetime, date)): continue
            valores = []
            for c in col_indices:
                v = ws2.cell(r, c).value
                if isinstance(v, (int, float)):
                    valores.append(None if v == 0 else v)
                else:
                    valores.append(None)
            if any(v is not None for v in valores):
                filas.append({"fecha": fecha.strftime("%Y-%m-%d"), "valores": valores})

        # Drop columnas que están TODAS en None (meses vencidos sin datos)
        keep_idx = []
        for c_i in range(len(meses)):
            if any(row['valores'][c_i] is not None for row in filas):
                keep_idx.append(c_i)
        meses = [meses[i] for i in keep_idx]
        for row in filas:
            row['valores'] = [row['valores'][i] for i in keep_idx]

        rofex[b["id"]] = {"label": b["label"], "fmt": b["fmt"], "meses": meses, "filas": filas}
    data['rofex'] = rofex

    return data

# =====================================================================
#  EMAE SERIES (actividad.html → window.EMAE_SERIES)
# =====================================================================
def extract_emae_series(status):
    """
    Lee Base EsAE.xlsx y genera emae_series.js con la estructura:
      { original: [{date, original, desest}],
        sector_ce: [{date, vals:[16]}],
        sector_se: [{date, vals:[16]}],
        sector_labels: [16 strings] }

    Lee BD/Actividad/EMAE.xlsx:
      - Hoja "EMAE": col A=fecha, B=serie original, C=serie desestacionalizada
      - Hoja "EMAE por sector de actividad CE": col A=fecha, B-Q = 16 sectores
      - Hoja "EMAE por sector de actividad SE": idem, sin estacionalidad

    No asume en que fila arranca cada cuadro: busca la primera fila cuya
    columna A es una fecha y toma los nombres de los sectores de la fila
    inmediatamente anterior. Si el analista agrega filas arriba (titulos,
    ponderadores) o meses nuevos abajo, el refresh lo sigue solo.
    """
    import io as _io
    import openpyxl as _opx
    from datetime import datetime as _dt

    SECTOR_LABELS = [
        'Agro', 'Pesca', 'Minería', 'Industria', 'Electricidad',
        'Construcción', 'Comercio', 'Hot. y rest.', 'Transp. y com.',
        'Int. financiera', 'Act. empresariales', 'Adm. pública',
        'Enseñanza', 'Serv. sociales', 'Otras act.', 'Imp. netos'
    ]

    path = EXCEL_PATHS["emae"]
    if not os.path.exists(path):
        status.warn("EMAE Series", f"no se encontró {path}")
        return None

    try:
        _data = _leer_bytes(path)
        # read_only=False: hace falta ver el relleno de las celdas para
        # detectar donde arranca el bloque de proyeccion.
        wb = _opx.load_workbook(_io.BytesIO(_data), data_only=True, read_only=False)
    except Exception as e:
        status.warn("EMAE Series", f"no se pudo abrir el Excel: {e}")
        return None

    def _find_sheet(wb, candidates):
        names_lower = {s.lower().strip(): s for s in wb.sheetnames}
        for c in candidates:
            if c.lower() in names_lower:
                return wb[names_lower[c.lower()]]
        # Búsqueda parcial
        for c in candidates:
            for k, v in names_lower.items():
                if c.lower() in k:
                    return wb[v]
        return None

    def _parse_date(v):
        if v is None: return None
        if isinstance(v, str):
            v = v.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%Y"):
                try: return _dt.strptime(v, fmt)
                except: pass
        if hasattr(v, 'year'): return v
        return None

    def _fmt_date(v):
        if v is None: return None
        try: return v.strftime("%Y-%m")
        except: return str(v)[:7]

    def _read_dated_block(ws, ncols, stop_on_fill=False):
        """Lee un cuadro cuya columna A son fechas, sin asumir en que fila
           arranca: busca la primera fila con fecha y toma los encabezados de
           la fila anterior.

           Con stop_on_fill=True corta ademas en la primera fila pintada, que
           es como el analista marca la proyeccion en la hoja EMAE — cuando
           despinta un mes porque ya salio el dato observado, entra solo en el
           proximo refresh. Si la PRIMERA fila de datos ya viene pintada, el
           relleno es el estilo del cuadro y no una marca (pasa en las hojas de
           sectores): en ese caso se ignora el color y se lee todo.

           Devuelve (encabezados, filas)."""
        max_row = ws.max_row or 0
        first = next((r for r in range(1, min(max_row, 40) + 1)
                      if _parse_date(ws.cell(r, 1).value) is not None), None)
        if first is None:
            return [], []
        labels = [str(ws.cell(first - 1, c).value).strip().replace('\n', ' ')
                  if first > 1 and ws.cell(first - 1, c).value is not None else ''
                  for c in range(2, ncols + 2)]

        def _pintada(r):
            for c in range(2, ncols + 2):
                f = ws.cell(r, c).fill
                if f is not None and f.patternType not in (None, 'none'):
                    return True
            return False

        # si el cuadro entero esta pintado, el color no marca proyeccion
        usar_color = stop_on_fill and not _pintada(first)

        out = []
        for r in range(first, max_row + 1):
            d = _parse_date(ws.cell(r, 1).value)
            if d is None:
                continue
            if usar_color and _pintada(r):
                break
            vals = [fmt_n(ws.cell(r, c).value) for c in range(2, ncols + 2)]
            if all(v is None for v in vals):
                continue
            out.append({"date": _fmt_date(d), "vals": vals})
        return labels, out

    # ---- Serie original + desestacionalizada ----
    ws_orig = _find_sheet(wb, ['EMAE'])
    original = []
    if ws_orig:
        _, filas = _read_dated_block(ws_orig, 2, stop_on_fill=True)
        original = [{"date": f["date"], "original": f["vals"][0], "desest": f["vals"][1]}
                    for f in filas]
    else:
        status.warn("EMAE Series", "no se encontró la hoja 'EMAE'")

    # ---- Sectores con estacionalidad ----
    ws_ce = _find_sheet(wb, ['EMAE por sector de actividad CE', 'sector de actividad ce', 'sector ce'])
    sector_ce = []
    if ws_ce:
        labels_ce, sector_ce = _read_dated_block(ws_ce, 16)
        # Los nombres cortos de SECTOR_LABELS se muestran en el dashboard, pero
        # dependen de que el orden de columnas del Excel no cambie. El Excel los
        # rotula "A - Agricultura...", "B - Pesca", ...: si esa secuencia deja de
        # ser A,B,C,... el orden cambio y hay que revisar SECTOR_LABELS.
        letras = [l.split('-')[0].strip() for l in labels_ce if l]
        esperado = [chr(ord('A') + i) for i in range(15)]
        if letras[:15] != esperado:
            status.warn("EMAE Series",
                        f"cambió el orden de los sectores en el Excel (leí {letras[:6]}...): "
                        f"revisar SECTOR_LABELS antes de confiar en las etiquetas")
    else:
        status.warn("EMAE Series", "no se encontró la hoja de sectores CE")

    # ---- Sectores sin estacionalidad ----
    ws_se = _find_sheet(wb, ['EMAE por sector de actividad SE', 'sector de actividad se', 'sector se'])
    sector_se = []
    if ws_se:
        _, sector_se = _read_dated_block(ws_se, 16)
    else:
        status.warn("EMAE Series", "no se encontró la hoja de sectores SE")

    if not original and not sector_ce and not sector_se:
        status.fail("EMAE Series", f"no se extrajo ningún dato de {os.path.basename(path)}. Verificar nombres de hojas: {wb.sheetnames[:8]}")
        return None

    result = {
        "original":      original,
        "sector_ce":     sector_ce,
        "sector_se":     sector_se,
        "sector_labels": SECTOR_LABELS,
    }
    status.ok("EMAE Series", f"{len(original)} meses - {len(sector_ce)} CE - {len(sector_se)} SE"
                             + (f" - hasta {original[-1]['date']}" if original else ""))
    if original:
        _avisar_si_viejo(status, "EMAE Series", original[-1]['date'], meses=4)
    if sector_ce:
        _avisar_si_viejo(status, "EMAE sectores", sector_ce[-1]['date'], meses=4)
    return result

def save_emae_series(data):
    """Guarda emae_series.js (sin .json ya que es solo lectura del dashboard)."""
    js_path = os.path.join(DATA_DIR, "emae_series.js")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    js = (
        f"// EMAE series data - EcoGo - {ts}\n"
        f"window.EMAE_SERIES = {json.dumps(data, ensure_ascii=False, default=str)};\n"
    )
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js)
    return os.path.getsize(js_path)

# =====================================================================
#  RESERVAS (pasivos reservas.xlsx + Reservas brutas y depositos.xlsx)
# =====================================================================
def extract_reservas(status):
    import io as _io
    import openpyxl as _opx
    from datetime import datetime as _dt

    ROW_META = {
        'reservas brutas':        (0, False, None,   'Reservas brutas'),
        'inconvertible':          (1, False, None,   'Inconvertible'),
        'reservas convertibles':  (1, True,  'conv', 'Reservas convertibles'),
        'valores':                (2, False, 'conv', 'Valores'),
        'divisas':                (2, False, 'conv', 'Divisas'),
        'degs':                   (2, False, 'conv', 'DEGs'),
        'oro':                    (2, False, 'conv', 'Oro'),
        'otros':                  (2, False, 'conv', 'Otros'),
        'pasivos brutos':         (0, True,  'pas',  'Pasivos brutos'),
        'encajes':                (1, False, 'pas',  'Encajes'),
        'swap china':             (1, False, 'pas',  'Swap China'),
        'swap basilea':           (1, False, 'pas',  'Swap Basilea + CAF'),
        'swap sedesa':            (1, False, 'pas',  'Swap SEDESA / Repo'),
        'swap activado eeuu':     (1, False, 'pas',  'Swap activado EEUU'),
        'otras obligaciones':     (1, False, 'pas',  'Otras obligaciones'),
        'bopreal':                (1, False, 'pas',  'BOPREAL'),
        'depositos del gobierno': (1, False, 'pas',  'Depositos del Gobierno'),
        'reservas liquidas':      (0, False, None,   'Reservas liquidas'),
        'reservas netas':         (0, False, None,   'Reservas netas'),
        'rin gob':                (0, False, None,   'RIN Gob. Nac.'),
    }

    def _norm(s):
        import unicodedata as _u
        s = _u.normalize('NFD', str(s).lower())
        s = ''.join(c for c in s if _u.category(c) != 'Mn')
        return re.sub(r'[^a-z\s]', '', s).strip()

    def _match_meta(label):
        nl = _norm(label)
        for key, meta in ROW_META.items():
            if nl.startswith(key):
                return meta
        return None

    MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
    def _fmt_date(dt):
        return f"{dt.day:02d}/{MESES[dt.month-1]}-{str(dt.year)[2:]}"

    data = {}

    # RIN cuadro
    rin_path = EXCEL_PATHS["pasivos_res"]
    if not os.path.exists(rin_path):
        status.warn("Reservas - RIN", f"no se encontro {rin_path}")
    else:
        try:
            _d = _leer_bytes(rin_path)
            wb = _opx.load_workbook(_io.BytesIO(_d), data_only=True, read_only=True)
            ws = wb['Cuadro RIN']

            date_row = list(ws.iter_rows(min_row=4, max_row=4, max_col=60, values_only=True))[0]
            date_cols = []
            last_dt = None
            for ci, v in enumerate(date_row):
                if isinstance(v, _dt):
                    if last_dt is None or v > last_dt:
                        date_cols.append((ci, v, _fmt_date(v)))
                        last_dt = v

            dates_labels = [lbl for _, _, lbl in date_cols]
            col_indices  = [ci for ci, _, _ in date_cols]

            def _extract_vals(row):
                vals = []
                for ci in col_indices:
                    v = row[ci] if ci < len(row) else None
                    if isinstance(v, str) and v.startswith('#'): v = None
                    vals.append(round(v, 1) if isinstance(v, float) else v)
                return vals

            rows_out = []
            for row in ws.iter_rows(min_row=5, max_row=26, max_col=60, values_only=True):
                label = row[0]
                if not label or not isinstance(label, str): continue
                label = label.strip()
                if not label or label.startswith(('1 ', '2 ', '3 ')): continue
                meta = _match_meta(label)
                if meta is None: continue
                indent, expandable, group, display = meta
                rows_out.append({
                    'label': display, 'indent': indent,
                    'expandable': expandable, 'group': group,
                    'vals': _extract_vals(row),
                })

            for row in ws.iter_rows(min_row=27, max_row=36, max_col=60, values_only=True):
                label = row[0]
                if not label or not isinstance(label, str): continue
                if 'tmu' in _norm(label):
                    rows_out.append({
                        'label': 'RIN TMU FMI', 'indent': 0,
                        'expandable': False, 'group': None,
                        'vals': _extract_vals(row),
                    })
                    break

            data['rin'] = {'dates': dates_labels, 'rows': rows_out}
            status.ok("Reservas - RIN", f"{len(dates_labels)} fechas - {len(rows_out)} filas")
        except Exception as e:
            status.fail("Reservas - RIN", str(e))
            traceback.print_exc()

    # G5: serie diaria
    dep_path = EXCEL_PATHS["res_dep"]
    if not os.path.exists(dep_path):
        status.warn("Reservas - G5", f"no se encontro {dep_path}")
    else:
        try:
            _d = _leer_bytes(dep_path)
            wb2 = _opx.load_workbook(_io.BytesIO(_d), data_only=True, read_only=True)

            def _leer_diaria(nombre):
                if nombre not in wb2.sheetnames:
                    return []
                out = []
                for row in wb2[nombre].iter_rows(min_row=3, max_col=5, values_only=True):
                    dt = row[0] or row[1]
                    r = fmt_n(row[2])
                    if not isinstance(dt, _dt) or r is None:
                        continue
                    out.append({'d': dt.strftime('%Y-%m-%d'), 'r': r,
                                'dep': fmt_n(row[3]), 'pre': fmt_n(row[4])})
                return out

            # El Excel tiene dos hojas con la misma estructura y el analista
            # dejo de cargar una: 'Datos' quedo en jun-25 mientras 'Datos
            # extendido' sigue al dia y ademas arranca mucho antes. En vez de
            # fijar una, se toma la que llegue mas lejos, asi el dia que
            # cambien cual mantienen el refresh sigue solo.
            candidatas = {n: _leer_diaria(n) for n in ('Datos extendido', 'Datos')}
            candidatas = {n: v for n, v in candidatas.items() if v}
            if not candidatas:
                status.warn("Reservas - G5", "ninguna hoja de serie diaria trajo datos")
                g5 = []
            else:
                hoja_g5 = max(candidatas, key=lambda n: candidatas[n][-1]['d'])
                g5 = candidatas[hoja_g5]
                data['g5'] = g5
                descartadas = [f"{n} llega a {v[-1]['d']}"
                               for n, v in candidatas.items() if n != hoja_g5]
                status.ok("Reservas - G5",
                          f"{len(g5)} dias - ultimo: {g5[-1]['d']} (hoja '{hoja_g5}'"
                          + (f"; {', '.join(descartadas)})" if descartadas else ")"))
                _avisar_si_viejo(status, "Reservas - serie diaria", g5[-1]['d'], meses=2,
                                 extra=f"la hoja '{hoja_g5}' es la mas nueva del Excel")
        except Exception as e:
            status.fail("Reservas - G5", str(e))
            traceback.print_exc()

    # ---- Evolucion de las reservas netas (serie diaria) ----
    # Sale del "Gráfico4" de pasivos reservas.xlsx, que es el que el analista
    # mantiene al dia: tres metodologias de netas sobre la misma serie diaria.
    # El cuadro RIN de arriba compara fechas sueltas; esto muestra el recorrido.
    if os.path.exists(EXCEL_PATHS["pasivos_res"]):
        try:
            wb3 = _open_wb(EXCEL_PATHS["pasivos_res"])
            # El rango del grafico llega unos dias mas lejos que los datos
            # cargados; sin recortar esa cola la linea termina antes del borde
            # del eje y parece que la serie esta mas atrasada de lo que esta.
            netas = sin_cola_vacia(_chart_block(wb3, "Gráfico4"))
            data['netas'] = netas
            status.ok("Reservas - Netas",
                      f"{len(netas['dates'])} dias · {len(netas['series'])} metodologias "
                      f"· hasta {netas['dates'][-1] if netas['dates'] else '?'}")
            if netas['dates']:
                _avisar_si_viejo(status, "Reservas - Netas", netas['dates'][-1], meses=2)
        except Exception as e:
            status.fail("Reservas - Netas", str(e))
            traceback.print_exc()

    return data if data else None

# =====================================================================
#  MONETARIAS — agregados monetarios, prestamos privados y monetizacion
# =====================================================================
def extract_monetarias(status):
    """
    Lee los graficos armados a mano en dos Excel de BD/Monetarias y
    reproduce esas mismas series (rango de fechas y columnas que el propio
    grafico de Excel referencia). Alcanza con extender el rango del grafico
    en Excel para que el proximo refresh levante los datos nuevos.
    """
    data = {}

    # ---- Agregados monetarios (niveles reales y % del PIB) ----
    path1 = EXCEL_PATHS["agregados_mon"]
    if not os.path.exists(path1):
        status.warn("Monetarias - Agregados", f"no se encontro: {path1}")
    else:
        try:
            wb1 = _open_wb(path1)
            niveles = _chart_block(wb1, "Gráfico2")
            pib     = _chart_block(wb1, "Gráfico3")
            data['agregados'] = {
                'dates':   niveles['dates'],
                'niveles': niveles['series'],
                'pib':     pib['series'],
            }
            status.ok("Monetarias - Agregados", f"{len(niveles['dates'])} meses")
        except Exception as e:
            status.fail("Monetarias - Agregados", str(e))
            traceback.print_exc()

        # ---- M3 en USD CCL (seccion Monetarias del dashboard clientes) ----
        try:
            wb1b = _open_wb(path1)
            data['cliente_m3_usd'] = _chart_block(wb1b, "Gráfico10")
            status.ok("Monetarias - Cliente M3 USD", f"{len(data['cliente_m3_usd']['dates'])} meses")
        except Exception as e:
            status.fail("Monetarias - Cliente M3 USD", str(e))
            traceback.print_exc()

    # ---- Prestamos privados y monetizacion (Monitor monetario mensual) ----
    path2 = EXCEL_PATHS["monitor_mon"]
    if not os.path.exists(path2):
        status.warn("Monetarias - Prestamos", f"no se encontro: {path2}")
    else:
        try:
            wb2 = _open_wb(path2)
            # Los graficos de este Excel guardan el dato ya como numero de
            # porcentaje (3.01 = 3.01%), no como fraccion — normalizamos con
            # scale=0.01 para que quede en fraccion 0-1, igual que el resto
            # del dashboard (agregados monetarios, precios, etc.).
            data['prestamos'] = {
                'pesos':   _chart_block(wb2, "(Gr) Prestamos en pesos", scale=0.01),
                'dolares': _chart_block(wb2, "(Gr) Prestamos en dólares", scale=0.01),
                'totales': _chart_block(wb2, "(Gr) Prestamos totales", scale=0.01),
            }
            status.ok("Monetarias - Prestamos", f"{len(data['prestamos']['pesos']['dates'])} meses")

            data['monetizacion'] = {
                'total':         _chart_block(wb2, "Gráfico4", scale=0.01),
                'pesos_dolares': _chart_block(wb2, "Gráfico5", scale=0.01),
            }
            status.ok("Monetarias - Monetizacion", f"{len(data['monetizacion']['total']['dates'])} meses")
        except Exception as e:
            status.fail("Monetarias - Prestamos/Monetizacion", str(e))
            traceback.print_exc()

    return data if data else None

# =====================================================================
#  DEUDA (dashboard clientes)
# =====================================================================
def extract_deuda(status):
    """
    Cuadro Lopez Murphy (deuda publica bruta/neta, historico anual), cuadro
    de vencimientos mensuales de deuda en pesos, y grafico de perfil de
    vencimientos con privados (Ejercicio refinanciamiento). Las tablas se
    leen respetando las filas/columnas que el analista deja ocultas en el
    Excel, y detectan solas donde termina la tabla — si se agrega un anio
    o un mes nuevo en Excel, el proximo refresh lo toma sin tocar el codigo.
    """
    data = {}

    # ---- Deuda Lopez Murphy: serie 2005-en adelante, bruta y neta ----
    path1 = EXCEL_PATHS["deuda_lopez_murphy"]
    if not os.path.exists(path1):
        status.warn("Deuda - Lopez Murphy", f"no se encontro: {path1}")
    else:
        try:
            wb1 = _open_wb(path1, read_only=False)
            ws1 = wb1["2005-2021 (vertical)"]
            tbl = extract_visible_table(
                ws1, header_rows=(4, 5), data_start_row=6, max_scan_row=76,
                start_col="B", end_col="Z",
            )
            tbl['headers'][0] = 'Período'
            data['lopez_murphy'] = tbl
            status.ok("Deuda - Lopez Murphy", f"{len(tbl['rows'])} períodos · {len(tbl['headers'])} columnas")
        except Exception as e:
            status.fail("Deuda - Lopez Murphy", str(e))
            traceback.print_exc()

    # ---- Deuda en pesos: vencimientos mensuales (Total y con privados) ----
    path2 = EXCEL_PATHS["deuda_en_pesos"]
    if not os.path.exists(path2):
        status.warn("Deuda - Vencimientos mensual", f"no se encontro: {path2}")
    else:
        try:
            wb2 = _open_wb(path2, read_only=False)
            ws2 = wb2["Vencimientos mensual"]
            tbl = extract_visible_table(
                ws2, header_rows=(3, 4), data_start_row=5, max_scan_row=95,
                start_col="D", end_col="R",
            )
            tbl['headers'][0] = 'Período'
            data['vencimientos_mensual'] = tbl
            status.ok("Deuda - Vencimientos mensual", f"{len(tbl['rows'])} períodos · {len(tbl['headers'])} columnas")
        except Exception as e:
            status.fail("Deuda - Vencimientos mensual", str(e))
            traceback.print_exc()

    # ---- Ejercicio refinanciamiento: perfil de vencimientos con privados ----
    path3 = EXCEL_PATHS["deuda_refinanciamiento"]
    if not os.path.exists(path3):
        status.warn("Deuda - Refinanciamiento", f"no se encontro: {path3}")
    else:
        try:
            wb3 = _open_wb(path3)
            data['refinanciamiento'] = _chart_block_categorical(wb3, "Gráfico1")
            status.ok("Deuda - Refinanciamiento", f"{len(data['refinanciamiento']['categories'])} categorías")
        except Exception as e:
            status.fail("Deuda - Refinanciamiento", str(e))
            traceback.print_exc()

    return data if data else None

# =====================================================================
#  COMERCIO EXTERIOR (dashboard clientes)
# =====================================================================
def extract_comercio(status):
    """
    Seccion Comercio exterior del dashboard clientes:
      - Importaciones desestacionalizadas ("G impo desest" de Comercio exterior.xlsx)
      - Saldos comerciales acum. 12 meses ("Gráfico6" del mismo Excel)
      - Precios y terminos de intercambio ("Gráfico3" de Terminos del Intercambio.xlsx)
      - Cuadro mensual Expo/Impo/Saldo (hoja Proy_mensual de Estimación Comercio Ext.xlsx)

    Los tres graficos siguen el rango que el propio grafico de Excel
    referencia: si el analista extiende el rango, el refresh lo toma solo.
    El cuadro respeta filas y columnas ocultas y corta donde arranca la
    proyeccion (primera fila pintada), asi que cuando se despinta un mes
    porque ya hay dato observado, ese mes entra solo.
    """
    data = {}

    # ---- Comercio exterior.xlsx: impo desestacionalizadas y saldos ----
    path1 = EXCEL_PATHS["comex"]
    if not os.path.exists(path1):
        status.warn("Comercio - Comercio exterior", f"no se encontro: {path1}")
    else:
        try:
            wb1 = _open_wb(path1)
            # "G impo desest" trae impo y expo en el mismo grafico. En el
            # dashboard van separadas, un cuadro para cada flujo, asi que se
            # reparten las series por su nombre. Lo que no empiece con "Expo"
            # queda del lado de las importaciones: si manana se agrega otra
            # serie de impo, entra sola.
            bloque = _chart_block(wb1, "G impo desest")
            impo = {k: v for k, v in bloque['series'].items() if not k.lower().startswith('expo')}
            expo = {k: v for k, v in bloque['series'].items() if k.lower().startswith('expo')}
            data['impo_desest'] = {'dates': bloque['dates'], 'series': impo}
            status.ok("Comercio - Impo desest",
                      f"{len(bloque['dates'])} meses · {len(impo)} series")
            if expo:
                data['expo_desest'] = {'dates': bloque['dates'], 'series': expo}
                status.ok("Comercio - Expo desest",
                          f"{len(bloque['dates'])} meses · {len(expo)} series")
            else:
                status.warn("Comercio - Expo desest",
                            "el grafico no trae ninguna serie que empiece con 'Expo'")
        except Exception as e:
            status.fail("Comercio - Impo/Expo desest", str(e))
            traceback.print_exc()

        try:
            wb1b = _open_wb(path1)
            data['saldos'] = _chart_block(wb1b, "Gráfico6")
            status.ok("Comercio - Saldos 12M", f"{len(data['saldos']['dates'])} meses")
        except Exception as e:
            status.fail("Comercio - Saldos 12M", str(e))
            traceback.print_exc()

    # ---- Terminos del Intercambio.xlsx: precios X/M y terminos ----
    path2 = EXCEL_PATHS["comex_tdi"]
    if not os.path.exists(path2):
        status.warn("Comercio - Terminos de intercambio", f"no se encontro: {path2}")
    else:
        try:
            wb2 = _open_wb(path2)
            data['terminos'] = _chart_block(wb2, "Gráfico3")
            status.ok("Comercio - Terminos de intercambio", f"{len(data['terminos']['dates'])} meses")
        except Exception as e:
            status.fail("Comercio - Terminos de intercambio", str(e))
            traceback.print_exc()

    # ---- Estimación Comercio Ext.xlsx: cuadro mensual observado ----
    path3 = EXCEL_PATHS["comex_proy"]
    if not os.path.exists(path3):
        status.warn("Comercio - Cuadro mensual", f"no se encontro: {path3}")
    else:
        try:
            wb3 = _open_wb(path3, read_only=False)
            ws3 = wb3["Proy_mensual"]
            # Columnas A-E (A=fecha, B repite la fecha y se descarta sola,
            # C/D/E = Expo/Impo/Saldo). F ("Int. Comex") esta oculta en el
            # Excel, asi que queda afuera por el filtro de columnas ocultas.
            # El fondo pintado solo aparece en B:E, no en la columna A.
            tbl = extract_visible_table(
                ws3, header_rows=(3,), data_start_row=4, max_scan_row=408,
                start_col="A", end_col="E",
                stop_on_fill=True, fill_cols=["B", "C", "D", "E"],
            )
            tbl['headers'][0] = 'Período'
            data['cuadro_mensual'] = tbl
            ultimo = tbl['rows'][-1][0] if tbl['rows'] else '—'
            status.ok("Comercio - Cuadro mensual", f"{len(tbl['rows'])} meses · hasta {ultimo}")
        except Exception as e:
            status.fail("Comercio - Cuadro mensual", str(e))
            traceback.print_exc()

    return data if data else None

# =====================================================================
#  TENENCIA DLK BCRA (dashboard clientes)
# =====================================================================
def extract_tenencia_dlk(status):
    """
    Seccion Tenencia DLK BCRA, con los dos cuadros que hoy se publican como
    imagen:

      1) DLK privados + short sobre M2, diario. Sale del CSV que deja la
         corrida del modelo, no del PNG, asi queda interactivo.
      2) El tablero de tenencia completo (apilado por tenedor, indicadores,
         absorcion diaria, canjes y que titulos tiene el BCRA), del Excel
         'Tenencia DLK BCRA.xlsx' de la raiz de la carpeta.

    La corrida del modelo deja una subcarpeta con la fecha en el nombre
    (dlk_futuros_m2_AAAAMMDD_HHMMSS), asi que se toma la mas nueva en vez de
    fijar una: cuando vuelvan a correr el modelo, el refresh la encuentra solo.
    """
    import csv as _csv
    base = EXCEL_PATHS["tenencia_dlk"]
    if not os.path.isdir(base):
        status.warn("Tenencia DLK", f"no existe la carpeta {base}")
        return None

    data = {}

    # ---- 1) DLK privados + short sobre M2 (serie diaria del modelo) ----
    try:
        corridas = []
        for raiz, dirs, _ in os.walk(base):
            if raiz.count(os.sep) - base.count(os.sep) > 2:
                dirs[:] = []
                continue
            for d in dirs:
                if d.lower().startswith('dlk_futuros_m2_'):
                    corridas.append(os.path.join(raiz, d))
        if not corridas:
            status.warn("Tenencia DLK - sobre M2", "no encontre ninguna carpeta dlk_futuros_m2_*")
        else:
            # el nombre lleva la fecha, asi que ordenar por nombre alcanza
            corrida = sorted(corridas, key=lambda p: os.path.basename(p))[-1]
            csvs = [f for f in os.listdir(corrida)
                    if f.lower().endswith('.csv') and 'con_dual' in f.lower()] or \
                   [f for f in os.listdir(corrida) if f.lower().endswith('.csv')]
            if not csvs:
                status.warn("Tenencia DLK - sobre M2", f"no hay CSV en {os.path.basename(corrida)}")
            else:
                ruta = os.path.join(corrida, sorted(csvs)[-1])
                with open(ruta, encoding='utf-8-sig', newline='') as f:
                    filas = list(_csv.DictReader(f))

                def num(fila, col):
                    v = (fila.get(col) or '').strip()
                    try:
                        return round(float(v), 4)
                    except ValueError:
                        return None

                fechas, prov = [], []
                # El dual esta adentro del DLK privados, asi que para apilar sin
                # contar dos veces se grafica el DLK lineal (privados - dual).
                series = {'DLK lineal': [], 'Bono dual TAMAR/A3500': [], 'Short futuros': []}
                for fila in filas:
                    fe = (fila.get('fecha') or '').strip()[:10]
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', fe):
                        continue
                    dlk, dual = num(fila, 'dlk_m2_pct'), num(fila, 'dual_m2_pp')
                    fechas.append(fe)
                    series['DLK lineal'].append(
                        round(dlk - dual, 4) if dlk is not None and dual is not None else dlk)
                    series['Bono dual TAMAR/A3500'].append(dual)
                    series['Short futuros'].append(num(fila, 'short_m2_pct'))
                    prov.append((fila.get('tramo_provisional') or '').strip().lower() == 'true')

                data['sobre_m2'] = {'dates': fechas, 'series': series, 'provisional': prov,
                                    'corrida': os.path.basename(corrida)}
                desde_prov = next((f for f, p in zip(fechas, prov) if p), None)
                status.ok("Tenencia DLK - sobre M2",
                          f"{len(fechas)} dias ({fechas[0]}–{fechas[-1]}) · corrida "
                          f"{os.path.basename(corrida)}"
                          + (f" · provisional desde {desde_prov}" if desde_prov else ""))
                if fechas:
                    _avisar_si_viejo(status, "Tenencia DLK - sobre M2", fechas[-1], meses=2)
    except Exception as e:
        status.fail("Tenencia DLK - sobre M2", str(e))
        traceback.print_exc()

    # ---- 2) El tablero de tenencia (Tenencia DLK BCRA.xlsx, en la raiz) ----
    # Ojo: en outputs/ hay un "sin restriccion stock BCRA.xlsx" que quedo
    # congelado en julio. El que se mantiene al dia es el de la raiz, y ademas
    # es el que trae todo el tablero: tenedores, absorcion, eventos y titulos.
    try:
        xlsx = os.path.join(base, "Tenencia DLK BCRA.xlsx")
        if not os.path.exists(xlsx):
            status.warn("Tenencia DLK - tablero", f"no se encontro {xlsx}")
        else:
            wb = _open_wb(xlsx, read_only=False)

            def _col(ws, *claves):
                """Numero de columna cuyo encabezado empieza con alguna clave."""
                for c in range(1, (ws.max_column or 30) + 1):
                    h = str(ws.cell(1, c).value or "").strip().lower()
                    if any(h.startswith(k) for k in claves):
                        return c
                return None

            # --- 2a) Serie diaria: apilado por tenedor + absorcion diaria ---
            ws = wb["Serie diaria"]
            COLS = [("stock bcra", "Stock BCRA"),
                    ("stock fgs", "Stock FGS"),
                    ("circulacion privada dlk", "Privados DLK"),
                    ("bono dual", "Dual TAMAR/A3500")]
            cols = [(_col(ws, k), lab) for k, lab in COLS]
            cols = [(c, lab) for c, lab in cols if c]
            c_tot = _col(ws, "total sistema")
            c_abs = _col(ws, "absorcion dlk bcra")
            c_exp = _col(ws, "explicacion")

            fechas, total, absorcion, explic = [], [], [], []
            series = {lab: [] for _, lab in cols}
            for r in range(2, (ws.max_row or 0) + 1):
                f = ws.cell(r, 1).value
                if not isinstance(f, datetime):
                    continue
                fechas.append(f.strftime("%Y-%m-%d"))
                for c, lab in cols:
                    series[lab].append(fmt_n(ws.cell(r, c).value))
                total.append(fmt_n(ws.cell(r, c_tot).value) if c_tot else None)
                absorcion.append(fmt_n(ws.cell(r, c_abs).value) if c_abs else None)
                explic.append(str(ws.cell(r, c_exp).value or "").strip() if c_exp else "")

            data["tenedores"] = {"dates": fechas, "series": series, "total": total,
                                 "absorcion": absorcion, "explicacion": explic}
            status.ok("Tenencia DLK - por tenedor",
                      f"{len(fechas)} dias ({fechas[0]}-{fechas[-1]}) · {len(cols)} tenedores"
                      if fechas else "sin filas")
            if fechas:
                _avisar_si_viejo(status, "Tenencia DLK - por tenedor", fechas[-1], meses=2)

            # --- 2b) Resumen: los indicadores de cabecera, tal cual el Excel ---
            res = {}
            wr = wb["Resumen"]
            for r in range(2, (wr.max_row or 0) + 1):
                k = str(wr.cell(r, 1).value or "").strip()
                if not k:
                    continue
                v = wr.cell(r, 2).value
                res[k] = {"valor": v.strftime("%Y-%m-%d") if isinstance(v, datetime) else fmt_n(v),
                          "unidad": str(wr.cell(r, 3).value or "").strip(),
                          "nota": str(wr.cell(r, 4).value or "").strip()}
            data["resumen"] = res

            # --- 2c) Por instrumento: que tiene el BCRA, al ultimo dia ---
            wi = wb["Por instrumento"]
            c_tk, c_bc = _col(wi, "ticker"), _col(wi, "bcra")
            c_pr, c_cl = _col(wi, "privados"), _col(wi, "clase")
            ult, porf = None, {}
            for r in range(2, (wi.max_row or 0) + 1):
                f = wi.cell(r, 1).value
                if not isinstance(f, datetime):
                    continue
                porf.setdefault(f, []).append(r)
                ult = f if ult is None or f > ult else ult
            titulos = []
            for r in porf.get(ult, []):
                b = fmt_n(wi.cell(r, c_bc).value) if c_bc else None
                if not b:
                    continue
                titulos.append({"ticker": str(wi.cell(r, c_tk).value or "").strip(),
                                "bcra": b,
                                "privados": fmt_n(wi.cell(r, c_pr).value) if c_pr else None,
                                "clase": str(wi.cell(r, c_cl).value or "").strip()})
            titulos.sort(key=lambda t: -(t["bcra"] or 0))
            data["por_titulo"] = {"fecha": ult.strftime("%Y-%m-%d") if ult else None,
                                  "items": titulos}
            status.ok("Tenencia DLK - BCRA por titulo",
                      f"{len(titulos)} titulos al {data['por_titulo']['fecha']}")

            # --- 2d) Eventos: las marcas que el grafico pone sobre el eje ---
            # Se separan como en el tablero: lo que pasa en el mercado
            # (licitaciones y canjes) de los canjes contra el BCRA.
            MERCADO = ("emision mercado", "canje/conversion mercado",
                       "baja por canje/conversion mercado")
            BCRA = ("canje/conversion bcra", "baja por canje/conversion bcra",
                    "canje oculto bcra entrada", "canje oculto bcra salida",
                    "reclasificacion canje oculto bcra")
            we = wb["Eventos"]
            desde = fechas[0] if fechas else "0000-00-00"
            ev = {"mercado": {}, "bcra": {}}
            for r in range(2, (we.max_row or 0) + 1):
                f = we.cell(r, 1).value
                if not isinstance(f, datetime):
                    continue
                fe = f.strftime("%Y-%m-%d")
                if fe < desde:
                    continue
                tipo = str(we.cell(r, 3).value or "").strip().lower()
                cual = "mercado" if tipo in MERCADO else ("bcra" if tipo in BCRA else None)
                if not cual:
                    continue
                tk = str(we.cell(r, 2).value or "").strip()
                ev[cual].setdefault(fe, [])
                if tk and tk not in ev[cual][fe]:
                    ev[cual][fe].append(tk)
            data["eventos"] = ev
            status.ok("Tenencia DLK - eventos",
                      f"{len(ev['mercado'])} dias con licitacion/canje de mercado · "
                      f"{len(ev['bcra'])} con canje BCRA")
    except Exception as e:
        status.fail("Tenencia DLK - tablero", str(e))
        traceback.print_exc()

    return data if data else None

# =====================================================================
#  MONITOR DE TASAS (completa la seccion Mercados)
# =====================================================================
@_nunca_rompe("Monitor de tasas")
def extract_monitor_tasas(status):
    """
    Completa Mercados con lo que el tablero no tenia: la curva TAMAR y las
    tasas de referencia de dinero a un dia.

    El proyecto 'Monitor tasas' ya deja un contrato de datos limpio en
    output/latest.json y un snapshot por rueda en output/history, asi que aca
    no se recalcula nada: se traduce a lo que espera la pagina. Si el monitor
    no corrio hoy, se publica igual la ultima rueda que si tenga datos y el
    aviso queda en el status.
    """
    base = EXCEL_PATHS["monitor_tasas"]
    if not os.path.isdir(base):
        status.warn("Monitor de tasas", f"no existe la carpeta {base}")
        return None

    ult = os.path.join(base, "output", "latest.json")
    if not os.path.exists(ult):
        status.warn("Monitor de tasas", "no encontre output/latest.json")
        return None

    d = json.loads(_leer_bytes(ult).decode("utf-8"))
    meta = d.get("meta", {})
    cal = d.get("quality", {}) or {}

    data = {"meta": {"market_date": meta.get("market_date"),
                     "generated_at": meta.get("generated_at"),
                     "status": meta.get("status"),
                     "registry_version": meta.get("registry_version"),
                     "warnings": cal.get("warnings", []),
                     "rava_errors": cal.get("rava_errors", {})}}

    def num(v):
        return fmt_n(v) if isinstance(v, (int, float)) else None

    # ---- Curva TAMAR ----
    # Son bonos a tasa variable: el rendimiento depende de fijaciones que
    # todavia no existen, asi que se guarda cuantas estan conocidas y cuantas
    # proyectadas para poder decirlo en la pagina.
    tamar = []
    for it in d.get("curves", {}).get("tamar", []):
        tamar.append({
            "symbol": it.get("symbol"),
            "maturity_date": it.get("maturity_date"),
            "tir_pct": num(it.get("tir_tea_pct")),
            "tir_tna_pct": num(it.get("tir_tna_pct")),
            "tir_tem_pct": num(it.get("tir_tem_pct")),
            "margin_tna_pct": num(it.get("margin_tna_pct")),
            "duration": num(it.get("modified_duration_years")),
            "price": num(it.get("price_per_vn_100")),
            "volume": num(it.get("volume_nominal")),
            "known_fixings": it.get("known_fixings"),
            "total_fixings": it.get("total_fixings"),
            "projected_tna_pct": num(it.get("projected_tna_pct")),
            "forecast_method": it.get("forecast_method"),
        })
    tamar.sort(key=lambda x: x["duration"] if x["duration"] is not None else 99)
    data["tamar"] = tamar

    # ---- Tasas de dinero a un dia ----
    ETIQUETAS = {"repo_1d": "REPO 1 dia",
                 "simu_1d": "SIMU 1 dia",
                 "caucion_1d": "Caucion 1 dia",
                 "tamar_private": "TAMAR bancos privados",
                 "bank_lending_1_7d_10m": "Activa bancaria 1-7 dias"}
    mm = d.get("money_market", {}) or {}
    latest = {}
    for k, lab in ETIQUETAS.items():
        s = mm.get(k) or {}
        if not s:
            continue
        latest[k] = {"label": lab, "date": s.get("date"), "tna_pct": num(s.get("tna_pct")),
                     "last_tna_pct": num(s.get("last_tna_pct")),
                     "volume_ars": num(s.get("volume_ars")),
                     "operations": s.get("operations"),
                     "tenor_days": s.get("tenor_days"),
                     "source": s.get("source")}

    # ---- Historia: una serie por tasa y la curva TAMAR por rueda ----
    hist_dir = os.path.join(base, "output", "history")
    fechas, series = [], {k: [] for k in ETIQUETAS}
    volumen = {"repo_1d": [], "caucion_1d": []}
    curvas = {}
    if os.path.isdir(hist_dir):
        archivos = sorted(f for f in os.listdir(hist_dir) if f.endswith(".json"))
        for nombre in archivos:
            try:
                snap = json.loads(_leer_bytes(os.path.join(hist_dir, nombre)).decode("utf-8"))
            except Exception:
                continue
            fe = (snap.get("meta", {}) or {}).get("market_date") or nombre[:10]
            fechas.append(fe)
            smm = snap.get("money_market", {}) or {}
            for k in ETIQUETAS:
                series[k].append(num((smm.get(k) or {}).get("tna_pct")))
            for k in volumen:
                volumen[k].append(num((smm.get(k) or {}).get("volume_ars")))
            fila = []
            for it in (snap.get("curves", {}) or {}).get("tamar", []):
                fila.append({"symbol": it.get("symbol"),
                             "tir_pct": num(it.get("tir_tea_pct")),
                             "duration": num(it.get("modified_duration_years")),
                             "volume": num(it.get("volume_nominal"))})
            if fila:
                curvas[fe] = fila

    data["money_market"] = {"latest": latest, "etiquetas": ETIQUETAS,
                            "history": {"dates": fechas, "series": series, "volume": volumen}}
    # La pagina ya sabe navegar un historial con esta forma (dates + curves),
    # asi que la curva TAMAR usa la misma y hereda los botones -1D/-1S.
    data["tamar_history"] = {"dates": [f for f in fechas if f in curvas], "curves": curvas}

    fe = meta.get("market_date")
    status.ok("Monitor de tasas",
              f"rueda {fe} · {len(tamar)} TAMAR · {len(latest)} tasas de referencia · "
              f"{len(fechas)} ruedas de historia")
    if meta.get("status") and meta["status"] != "ok":
        detalle = "; ".join(cal.get("warnings", [])[:2]) or meta["status"]
        status.warn("Monitor de tasas", f"el monitor se publico como '{meta['status']}': {detalle}")
    # _avisar_si_viejo razona en meses y esta serie es diaria: una semana sin
    # rueda nueva ya es sintoma de que la tarea de las 17:30 dejo de correr.
    dia = _a_fecha(fe)
    if dia is not None:
        atraso = (datetime.now() - dia).days
        if atraso > 7:
            status.warn("Monitor de tasas",
                        f"ultima rueda {dia.strftime('%d-%m-%Y')} — {atraso} dias de atraso "
                        f"(revisar la tarea de las 17:30 en la carpeta 'Monitor tasas')")
    return data


@_nunca_rompe("Mercados - instrumentos")
def completar_mercados(status, monitor):
    """
    Completa las curvas de Mercados con los instrumentos que el worker no trae
    y saca los que ya vencieron.

    El worker que alimenta Mercados y el Monitor de tasas miran el mismo
    mercado pero no el mismo universo: el Monitor mantiene un registro
    versionado de especies, con terminos verificados contra Finanzas, y da de
    baja las vencidas en cada corrida. El worker, en cambio, no incorpora las
    emisiones nuevas y arrastra especies muertas con el ultimo precio
    conocido. Por eso en el tablero faltaban LECAP vigentes y un hard dollar,
    y seguian figurando tres dolar linked ya vencidos.

    Esto no reemplaza al worker: le suma lo que le falta y le saca lo vencido.
    Los CER con cupon (TX*, DICP, DIPO) quedan como estan: el Monitor no los
    calcula a proposito, asi que su ausencia alli no significa que vencieron.
    """
    if not monitor:
        return
    try:
        ruta = os.path.join(BASE_EXCEL, "Mercados", "Monitor tasas", "output", "latest.json")
        curvas = json.loads(_leer_bytes(ruta).decode("utf-8")).get("curves", {}) or {}
    except Exception as e:
        status.warn("Mercados - instrumentos", f"no pude releer el monitor: {e}")
        return
    if not curvas:
        return

    js = os.path.join(DATA_DIR, "mercados.js")
    if not os.path.exists(js):
        status.warn("Mercados - instrumentos", "todavia no existe mercados.js")
        return
    m = re.search(r"=\s*(\{.*\});?\s*$", _leer_bytes(js).decode("utf-8"), re.S)
    if not m:
        status.warn("Mercados - instrumentos", "no pude parsear mercados.js")
        return
    M = json.loads(m.group(1))

    def n(v):
        return fmt_n(v) if isinstance(v, (int, float)) else None

    rueda = (monitor.get("meta") or {}).get("market_date") or datetime.now().strftime("%Y-%m-%d")
    sumados, bajas = [], []

    def vencido(it):
        """Un instrumento vencido no deja de cotizar en el worker: se queda con
        el ultimo precio conocido, que parece del dia."""
        f = it.get("payment_date") or it.get("maturity_date")
        return bool(f) and str(f)[:10] < rueda

    def limpiar(lista, etiqueta):
        vivos = []
        for it in lista or []:
            if vencido(it):
                bajas.append(f"{etiqueta} {it['symbol']}")
            else:
                vivos.append(it)
        return vivos

    # ---- Tasa fija ----
    M["fixed_curve"] = limpiar(M.get("fixed_curve"), "tasa fija")
    hay = {x["symbol"] for x in M["fixed_curve"]}
    for it in curvas.get("fixed", []):
        if it["symbol"] in hay:
            continue
        M["fixed_curve"].append({
            "symbol": it["symbol"],
            # el tablero colorea por familia y sus claves van en minuscula
            "family": (it.get("family") or "").lower(),
            "tir_pct": n(it.get("yield_tea_pct")),
            "duration": n(it.get("modified_duration_years")),
            "maturity_date": it.get("maturity_date"),
            "payment_date": it.get("maturity_date"),
            "volume": n(it.get("volume_nominal")),
            "fuente": "monitor",
        })
        sumados.append("tasa fija " + it["symbol"])

    # ---- CER ----
    M["cer_curve"] = limpiar(M.get("cer_curve"), "CER")
    hay = {x["symbol"] for x in M["cer_curve"]}
    for it in curvas.get("cer", []):
        if it["symbol"] in hay:
            continue
        M["cer_curve"].append({
            "symbol": it["symbol"],
            "family": (it.get("family") or "").lower(),
            "tir_pct": n(it.get("real_yield_tea_pct")),
            "duration": n(it.get("modified_duration_years")),
            "payment_date": it.get("maturity_date"),
            "price": n(it.get("price_ars_per_vn100")),
            "technical_price": n(it.get("technical_price")),
            "parity": n(it.get("parity_pct")),
            "volume": n(it.get("volume_nominal")),
            "fuente": "monitor",
        })
        sumados.append("CER " + it["symbol"])

    # ---- Hard dollar: el monitor marca la ley en 'family' (A o G) ----
    hd = M.setdefault("hard_dollar", {})
    for c in ("a_curve", "g_curve"):
        hd[c] = limpiar(hd.get(c), "hard dollar")
    hay = {x["symbol"] for c in ("a_curve", "g_curve") for x in hd.get(c, [])}
    for it in curvas.get("hard_dollar", []):
        if it["symbol"] in hay:
            continue
        destino = "g_curve" if (it.get("family") or "").upper() == "G" else "a_curve"
        hd.setdefault(destino, []).append({
            "symbol": it["symbol"],
            "price": n(it.get("price_usd_dirty_per_vn100")),
            "tir_pct": n(it.get("yield_tea_pct")),
            "duration": n(it.get("modified_duration_years")),
            "technical_price": n(it.get("technical_price")),
            "parity": n(it.get("parity_pct")),
            "payment_date": it.get("maturity_date"),
            "volume": n(it.get("volume_nominal")),
            "fuente": "monitor",
        })
        sumados.append("hard dollar " + it["symbol"])

    # ---- Dolar linked ----
    # Aca el worker no publica el vencimiento, asi que la baja se decide con el
    # registro del Monitor, que si lo tiene.
    #
    # Ojo con la tentacion de usar la publicacion del dia en vez del registro:
    # el Monitor deja afuera de latest.json cualquier especie para la que no
    # consiguio precio fresco (hoy mismo, D10Y7, que vence en 2027). Si la
    # ausencia de ese archivo contara como baja, un bono vivo desapareceria del
    # tablero el dia que Rava no responda.
    dl = M.setdefault("dollar_linked", {})
    por_sim = {it["symbol"]: it for it in curvas.get("dollar_linked", [])}
    registro = {}
    try:
        cfg = os.path.join(BASE_EXCEL, "Mercados", "Monitor tasas",
                           "config", "market_instruments.json")
        for x in json.loads(_leer_bytes(cfg).decode("utf-8")).get("dollar_linked", []):
            registro[x["symbol"]] = x.get("maturity_date")
    except Exception as e:
        status.warn("Mercados - instrumentos",
                    f"no pude leer el registro del monitor ({e}); no doy de baja dolar linked")

    quedan = []
    for it in (dl.get("latest") or []):
        s = it["symbol"]
        if s in registro:
            # registrada: manda la fecha de vencimiento
            muere = bool(registro[s]) and str(registro[s])[:10] < rueda
        elif not registro:
            muere = False           # sin registro no hay con que decidir
        else:
            # no registrada: no hay vencimiento, pero una especie que hace
            # ruedas que no opera es un precio arrastrado, no un mercado
            muere = not it.get("volume")
        (bajas.append("dolar linked " + s) if muere else quedan.append(it))
    muertos = [b.split()[-1] for b in bajas if b.startswith("dolar linked ")]

    for s, it in por_sim.items():
        actual = next((x for x in quedan if x["symbol"] == s), None)
        if actual is None:
            actual = {"date": rueda, "symbol": s,
                      "price": n(it.get("price_ars_per_vn100_usd")),
                      "volume": n(it.get("volume_nominal")), "amount": None,
                      "fuente": "monitor"}
            quedan.append(actual)
            sumados.append("dolar linked " + s)
        # el worker solo trae precio y volumen; el rendimiento lo calcula el monitor
        actual["tir_pct"] = n(it.get("usd_equivalent_yield_tea_pct"))
        actual["duration"] = n(it.get("modified_duration_years"))
        actual["maturity_date"] = it.get("maturity_date")

    quedan.sort(key=lambda x: x.get("maturity_date") or "9999")
    dl["latest"] = quedan
    dl["symbols"] = [x["symbol"] for x in quedan]
    if muertos:
        # tambien del historial, para que el grafico de volumen no los dibuje
        dl["history"] = [h for h in (dl.get("history") or []) if h.get("symbol") not in muertos]

    M.setdefault("meta", {})["completado_con_monitor"] = {
        "rueda": rueda, "sumados": sumados, "bajas": bajas}

    save_data("mercados", M)
    status.ok("Mercados - instrumentos",
              f"{len(sumados)} sumados del monitor · {len(bajas)} vencidos dados de baja")
    if sumados:
        print("    sumados: " + ", ".join(sumados))
    if bajas:
        print("    bajas:   " + ", ".join(bajas))


# =====================================================================
#  POTENCIAL EXPORTADOR 2026-2036 (dashboard clientes)
# =====================================================================
def extract_potencial_exportador(status):
    """
    Los dos graficos del Excel de perspectiva exportadora 2026-2036:

      'Gráfico1' -> composicion exportadora por bloque (area apilada), que sale
                    del cuadro Consolidado.
      'Gráfico2' -> proyecciones del sector agropecuario.

    El primero se lee siguiendo el rango que referencia el propio grafico. El
    segundo NO: su rango de categorias (11 anios) es mas corto que el de
    valores (14), asi que reproducirlo tal cual desalinearia cada valor con su
    anio. Se lee la hoja Agro directamente, que ademas trae la columna 'Tramo'
    para distinguir lo observado de lo proyectado.
    """
    path = EXCEL_PATHS["potencial_exportador"]
    if not os.path.exists(path):
        status.warn("Potencial exportador", f"no se encontro: {path}")
        return None

    data = {}

    # ---- Composicion exportadora por bloque ----
    try:
        wb = _open_wb(path)
        comp = _chart_block_categorical(wb, "Gráfico1")
        data['composicion'] = comp
        status.ok("Potencial exportador - Composicion",
                  f"{len(comp['categories'])} anios · {len(comp['series'])} bloques")
        # El cuadro Consolidado convierte en 0 las celdas vacias de la hoja de
        # origen. Un 0 en un bloque que exporta decenas de miles de millones no
        # es un dato, es un hueco: conviene avisarlo antes de graficarlo.
        for nombre, vals in comp['series'].items():
            huecos = [comp['categories'][i] for i, v in enumerate(vals) if v == 0]
            if huecos and any(v for v in vals if v):
                status.warn("Potencial exportador - Composicion",
                            f"'{nombre}' figura en 0 en {', '.join(huecos)} "
                            f"— en el Excel esas celdas estan vacias, no en cero")
    except Exception as e:
        status.fail("Potencial exportador - Composicion", str(e))
        traceback.print_exc()

    # ---- Proyecciones del sector agropecuario ----
    try:
        wb2 = _open_wb(path, read_only=False)
        ws = wb2["Agro"]
        fila_enc = next((r for r in range(1, 20)
                         if str(ws.cell(r, 1).value or '').strip().lower() == 'año'), 5)
        cols = [(c, str(ws.cell(fila_enc, c).value or '').replace('\n', ' ').strip())
                for c in range(2, 7)]
        cols = [(c, t) for c, t in cols if t and not t.lower().startswith('tramo')]
        col_tramo = next((c for c in range(2, 8)
                          if str(ws.cell(fila_enc, c).value or '').strip().lower() == 'tramo'), None)

        anios, filas, tramos = [], {t: [] for _, t in cols}, []
        for r in range(fila_enc + 1, (ws.max_row or 40) + 1):
            a = ws.cell(r, 1).value
            if a is None or not re.fullmatch(r'\d{4}', str(a).strip()):
                continue
            anios.append(str(a).strip())
            for c, t in cols:
                filas[t].append(fmt_n(ws.cell(r, c).value))
            tramos.append(str(ws.cell(r, col_tramo).value).strip() if col_tramo else '')

        data['agro'] = {"anios": anios, "series": filas, "tramos": tramos}
        proy = [a for a, t in zip(anios, tramos) if t.lower().startswith('proy')]
        status.ok("Potencial exportador - Agro",
                  f"{len(anios)} anios ({anios[0]}–{anios[-1]}) · "
                  f"{len(cols)} series · proyeccion desde {proy[0] if proy else '?'}")
    except Exception as e:
        status.fail("Potencial exportador - Agro", str(e))
        traceback.print_exc()

    return data if data else None

# =====================================================================
#  MONITOR DE ACTIVIDAD (dashboard clientes)
# =====================================================================
def extract_monitor_actividad(status):
    """
    Los tres cuadros del Monitor de Actividad, que comparten estructura
    (mismas series, mismos meses) y en el dashboard se muestran como un solo
    cuadro con un boton para cambiar de vista:

      'Cuadro Monitor'             -> indice (nivel s.e., 2017=100)
      'Cuadro Monitor (var%)'      -> variacion mensual
      'Cuadro Monitor (var%) (2)'  -> variacion interanual

    Los meses salen de la fila 2 del Excel, no de un rango fijo: el cuadro es
    una ventana movil de 14 meses, asi que cada mes nuevo agrega una columna a
    la derecha y saca la de la izquierda. Las filas cortan solas en el
    'Fuente:' del pie.
    """
    path = EXCEL_PATHS["monitor_actividad"]
    if not os.path.exists(path):
        status.warn("Monitor de Actividad", f"no se encontro: {path}")
        return None

    VISTAS = [
        ("indice",  "Cuadro Monitor",             "Índice"),
        ("var_men", "Cuadro Monitor (var%)",      "Var. % mensual"),
        ("var_ia",  "Cuadro Monitor (var%) (2)",  "Var. % i.a."),
    ]

    wb = _open_wb(path)
    hojas = {n.strip().lower(): n for n in wb.sheetnames}

    def _hoja(nombre):
        return wb[hojas[nombre.strip().lower()]] if nombre.strip().lower() in hojas else None

    base = _hoja(VISTAS[0][1])
    if base is None:
        status.fail("Monitor de Actividad",
                    f"no encontre la hoja 'Cuadro Monitor'. Hay: {wb.sheetnames}")
        return None

    # meses = columnas con fecha en la fila 2
    cols_mes = [(c, base.cell(2, c).value) for c in range(1, 40)
                if isinstance(base.cell(2, c).value, datetime)]
    if not cols_mes:
        status.fail("Monitor de Actividad", "no encontre columnas con fecha en la fila 2")
        return None
    meses = [d.strftime('%Y-%m') for _, d in cols_mes]

    # filas: desde la 3 hasta el 'Fuente:' del pie
    filas, fuente = [], ""
    grupo = ""
    for r in range(3, (base.max_row or 60) + 1):
        a = base.cell(r, 1).value
        b = base.cell(r, 2).value
        if a and str(a).strip().lower().startswith('fuente'):
            fuente = str(a).replace('\n', ' ').strip()
            break
        def _limpio(v):
            return re.sub(r'\s+', ' ', str(v).replace('\n', ' ')).strip()
        if a:
            grupo = _limpio(a)
        if not b:
            continue
        filas.append({"fila": r, "grupo": grupo, "serie": _limpio(b),
                      "nivel": fmt_n(base.cell(r, 3).value)})

    vistas = {}
    for clave, hoja, label in VISTAS:
        ws = _hoja(hoja)
        if ws is None:
            status.warn("Monitor de Actividad", f"falta la hoja '{hoja}' — esa vista no se publica")
            continue
        # cada hoja se lee con sus propias columnas de mes, por si alguna
        # quedo desfasada respecto de las otras
        cm = [c for c in range(1, 40) if isinstance(ws.cell(2, c).value, datetime)]
        if [ws.cell(2, c).value.strftime('%Y-%m') for c in cm] != meses:
            status.warn("Monitor de Actividad",
                        f"'{hoja}' no tiene los mismos meses que 'Cuadro Monitor' — revisar el Excel")
        datos = [[fmt_n(ws.cell(f["fila"], c).value) for c in cm] for f in filas]
        vistas[clave] = {"label": label,
                         "titulo": str(ws.cell(2, 1).value or '').replace('\n', ' ').strip(),
                         "datos": datos}

    data = {
        "meses": meses,
        "fuente": fuente or "Fuente: Eco Go",
        "series": [{"grupo": f["grupo"], "serie": f["serie"], "nivel": f["nivel"]} for f in filas],
        "vistas": vistas,
    }
    status.ok("Monitor de Actividad",
              f"{len(filas)} series · {len(meses)} meses ({meses[0]} a {meses[-1]}) · "
              f"{len(vistas)} vistas")
    _avisar_si_viejo(status, "Monitor de Actividad", meses[-1], meses=3)
    return data

# =====================================================================
#  INTERNACIONAL · MERCADOS · LATINFOCUS
# =====================================================================
@_nunca_rompe("Version de datos")
def sellar_versiones(status):
    """Le pone ?v=<fecha> a los <script src=".../assets/data/*.js"> de todas las
    paginas, y tambien a assets/js/*.js y assets/css/*.css (asi un cambio de
    codigo como layout.js no queda tapado por el cache del navegador).

    Sin esto, la URL de cada archivo de datos no cambia nunca: GitHub Pages los
    sirve con cache y el navegador te sigue mostrando el archivo viejo aunque
    el refresh haya corrido bien y el push haya salido. Con el sello, cada
    actualizacion genera una URL distinta y el navegador la baja si o si.

    Trabaja sobre bytes a proposito: algunas paginas tienen bytes que no son
    UTF-8 valido y releerlas como texto las corromperia."""
    sello = datetime.now().strftime('%Y%m%d%H%M').encode()
    patron = re.compile(rb'((?:src|href)=["\'][^"\']*assets/(?:data/[^"\'?]+\.js|js/[^"\'?]+\.js|css/[^"\'?]+\.css))(\?v=[0-9]+)?(["\'])')
    tocadas = 0
    for carpeta in (DASHBOARD_DIR, os.path.join(DASHBOARD_DIR, 'pages')):
        if not os.path.isdir(carpeta):
            continue
        for nombre in os.listdir(carpeta):
            if not nombre.endswith('.html'):
                continue
            ruta = os.path.join(carpeta, nombre)
            with open(ruta, 'rb') as f:
                orig = f.read()
            nuevo_b = patron.sub(rb'\1?v=' + sello + rb'\3', orig)
            if nuevo_b != orig:
                with open(ruta, 'wb') as f:
                    f.write(nuevo_b)
                tocadas += 1
    status.ok("Version de datos", f"{tocadas} paginas selladas con ?v={sello.decode()}")
    return True

@_nunca_rompe("Monitor mundial")
def run_monitor_mundial(status):
    """Corre el updater del Monitor mundial (node scripts/update-data.mjs), que
    es quien baja los datos de las fuentes oficiales y regenera monitor-data.js.

    Antes esto dependia de una tarea programada aparte: si no corria, el
    refresh copiaba prolijamente un archivo viejo. Corriendolo aca, una sola
    corrida del notebook deja la seccion Internacional al dia de verdad."""
    import shutil, subprocess
    if not os.path.isdir(MONITOR_MUNDIAL_DIR):
        status.warn("Monitor mundial", f"no existe {MONITOR_MUNDIAL_DIR}")
        return False
    # node esta instalado pero no siempre en el PATH que hereda Jupyter, asi que
    # si no aparece se lo busca en las ubicaciones tipicas antes de rendirse
    node = shutil.which("node")
    if not node:
        for cand in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs", "node.exe"),
                     os.path.join(os.environ.get("ProgramFiles(x86)", ""), "nodejs", "node.exe"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "nodejs", "node.exe"),
                     os.path.join(os.environ.get("APPDATA", ""), "npm", "node.exe")):
            if cand and os.path.exists(cand):
                node = cand
                break
    if not node:
        status.warn("Monitor mundial",
                    "no encontre node (ni en el PATH ni en Program Files); "
                    "se usa el monitor-data.js que haya")
        return False
    script = os.path.join(MONITOR_MUNDIAL_DIR, "scripts", "update-data.mjs")
    if not os.path.exists(script):
        status.warn("Monitor mundial", f"no existe {script}")
        return False

    r = subprocess.run([node, script], cwd=MONITOR_MUNDIAL_DIR,
                       capture_output=True, text=True, timeout=900)
    salida = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    ultima = salida[-1] if salida else ""
    if r.returncode != 0:
        status.warn("Monitor mundial", f"el updater fallo: {ultima[:180]}")
        return False
    alertas = [l for l in salida if " WARN " in l or " ERROR " in l]

    # Espejar el resultado a la carpeta original para que el Monitor mundial
    # standalone siga viendo los mismos datos. Si falla la copia no pasa nada
    # grave: el dashboard usa el del repo, que es el que acaba de generarse.
    espejo = ""
    try:
        if os.path.exists(MONITOR_MUNDIAL_JS) and MONITOR_MUNDIAL_ESPEJO != MONITOR_MUNDIAL_JS:
            os.makedirs(os.path.dirname(MONITOR_MUNDIAL_ESPEJO), exist_ok=True)
            import shutil as _sh
            _sh.copy2(MONITOR_MUNDIAL_JS, MONITOR_MUNDIAL_ESPEJO)
            espejo = " · espejado a la carpeta original"
    except OSError as e:
        espejo = f" · no se pudo espejar ({type(e).__name__})"

    status.ok("Monitor mundial", f"{ultima[:110]}"
              + (f" · {len(alertas)} avisos" if alertas else "") + espejo)
    return True

@_nunca_rompe("Internacional")
def extract_internacional(status):
    """Copia el monitor-data.js del Monitor mundial a internacional.js."""
    # Normalmente usa el que genera la copia del repo; si todavia no corrio
    # (clon nuevo, node faltante), cae en el de la carpeta original.
    origen = MONITOR_MUNDIAL_JS
    if not os.path.exists(origen) and os.path.exists(MONITOR_MUNDIAL_ESPEJO):
        origen = MONITOR_MUNDIAL_ESPEJO
    if not os.path.exists(origen):
        status.warn("Internacional", f"no se encontro {MONITOR_MUNDIAL_JS}")
        return False
    src = _read_text(origen)
    m = re.search(r'window\.MONITOR_DATA\s*=\s*(\{.*\});?\s*$', src, re.DOTALL)
    if not m:
        status.fail("Internacional", "no pude parsear monitor-data.js")
        return False
    intl_data = json.loads(m.group(1))
    _intl_str = json.dumps(intl_data, ensure_ascii=False, default=str)
    try:
        with open(os.path.join(DATA_DIR, "internacional.json"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_intl_str)
    except OSError:
        pass
    js_path = os.path.join(DATA_DIR, "internacional.js")
    with open(js_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"// Datos Internacional - regenerado por refresh.py el {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"window.INTERNACIONAL_DATA = {_intl_str};\n")
    sello_origen = datetime.fromtimestamp(os.path.getmtime(origen)).strftime('%d/%m %H:%M')
    status.ok("Internacional",
              f"{os.path.getsize(js_path):,} bytes - {len(intl_data.get('countries',[]))} paises "
              f"(origen del {sello_origen})")

    # El archivo puede estar recien generado y aun asi traer series viejas: el
    # Monitor mundial se regenera todos los dias, pero si una fuente deja de
    # responder arrastra el ultimo dato que consiguio. Mirar la fecha del
    # archivo no alcanza, hay que mirar adentro.
    arg = (intl_data.get('series') or {}).get('ARG') or {}
    # el umbral va por indicador: la inflacion es mensual y sale rapido, el
    # desempleo es trimestral (EPH) y siempre mira varios meses para atras
    for ind, tope in (('inflationYoy', 3), ('gdpGrowth', 6), ('unemployment', 7)):
        fechas = sorted(set(re.findall(r'\d{4}-\d{2}', json.dumps(arg.get(ind, ''), default=str))))
        if fechas:
            _avisar_si_viejo(status, f"Internacional - ARG {ind}", fechas[-1], meses=tope,
                             extra="el dato viejo viene del Monitor mundial, no del refresh")
    return True

def _publicar_mercados_payload(status, payload_path):
    """Valida y publica un payload local ya generado, sin recalcularlo."""
    if not os.path.isfile(payload_path):
        status.warn("Mercados", "el pipeline termino pero no genero dashboard_payload.json")
        return False

    payload = json.loads(_read_text(payload_path))
    subset = {k: payload.get(k, d) for k, d in [
        ("meta", {}), ("external_context", {}), ("overview", {}),
        ("fixed_curve", []), ("fixed_curve_history", {"dates": [], "curves": {}}),
        ("cer_curve", []), ("cer_curve_history", {"dates": [], "curves": {}}),
        ("dollar_linked", {}), ("hard_dollar", {}),
        ("hard_dollar_curve_history", {"dates": [], "curves": {}}), ("hero_metrics", []),
    ]}
    required_blocks = ("external_context", "fixed_curve", "cer_curve", "dollar_linked", "hard_dollar")
    missing_blocks = [key for key in required_blocks if not subset.get(key)]
    if missing_blocks:
        status.warn("Mercados", f"el pipeline genero un payload incompleto ({', '.join(missing_blocks)}); se conserva mercados.js")
        return False

    js_path = os.path.join(DATA_DIR, "mercados.js")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Forzamos LF para que Git no marque como whitespace toda la línea JSON
    # cuando el refresh se ejecuta desde Windows.
    with open(js_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("// Mercados data - generado por pipeline local - " + ts + "\n"
                "window.MERCADOS_DATA = " + json.dumps(subset, ensure_ascii=False, default=str) + ";\n")
    fin = (subset.get("meta") or {}).get("end_date", "")
    externo = (subset.get("external_context") or {}).get("latest_date", "")
    status.ok(
        "Mercados",
        f"{os.path.getsize(js_path):,} bytes - mercado local hasta {fin or '?'} · externo hasta {externo or '?'}",
    )
    _avisar_si_viejo(status, "Mercados", externo or fin, meses=1,
                     extra="verificar fuentes de mercado del pipeline local")
    return True


@_nunca_rompe("Mercados")
def extract_mercados(status):
    """Genera Mercados localmente y publica el subconjunto usado por la web.

    Antes esta funcion descargaba un JSON armado por un Cloudflare Worker que
    quedo detenido. Ahora corre el pipeline local (BCRA, Ambito,
    ArgentinaDatos, IOL, BYMA, Yahoo Finance y FRED), conserva sus caches y
    recien reemplaza mercados.js cuando obtuvo un payload valido.
    """
    import importlib.util
    import subprocess

    if not os.path.isfile(MARKETS_PIPELINE_RUNNER):
        status.warn("Mercados", "no existe el pipeline local de Mercados; se conserva mercados.js")
        return False

    # El refresh puede partir de una instalacion nueva. Instalamos solo las
    # dependencias que faltan y en el mismo interprete que ejecuto el notebook.
    required_modules = ("pandas", "numpy", "requests", "openpyxl", "xlrd", "selenium", "lxml")
    missing = [name for name in required_modules if importlib.util.find_spec(name) is None]
    if missing:
        requirements = os.path.join(MARKETS_PIPELINE_DIR, "requirements.txt")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", requirements],
            cwd=MARKETS_PIPELINE_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0:
            detail = ((r.stderr or r.stdout) or "fallo sin detalle").strip().splitlines()
            status.warn("Mercados", f"no pude instalar dependencias ({', '.join(missing)}): {detail[-1][:180] if detail else 'sin detalle'}")
            return False

    r = subprocess.run(
        [sys.executable, MARKETS_PIPELINE_RUNNER],
        cwd=MARKETS_PIPELINE_DIR,
        capture_output=True,
        text=True,
        timeout=900,
    )
    output = ((r.stdout or "") + "\n" + (r.stderr or "")).strip().splitlines()
    last_line = output[-1][:240] if output else "sin salida"
    if r.returncode != 0:
        status.warn("Mercados", f"el pipeline local fallo; se conserva mercados.js: {last_line}")
        return False
    return _publicar_mercados_payload(status, MARKETS_PIPELINE_PAYLOAD)

@_nunca_rompe("Internacional Consensus")
def run_latinfocus(status):
    """Busca el PDF de LatinFocus mas nuevo dentro de PROYECCIONES_INTL
    (recursivo: hay una subcarpeta por anio) y lo procesa. No hay que escribir
    el nombre del archivo en ningun lado: alcanza con dejar el PDF del mes ahi.

    Que no haya un PDF nuevo es lo normal la mayor parte del mes, asi que no
    es un error: avisa "no se encontro actualizacion" y sigue de largo. Nada
    de lo que pase aca corta el refresh."""
    import subprocess
    if not os.path.isdir(PROYECCIONES_INTL):
        status.warn("Internacional Consensus", f"no existe la carpeta {PROYECCIONES_INTL}")
        return False

    MESES = {m: i for i, m in enumerate(
        ['january','february','march','april','may','june',
         'july','august','september','october','november','december'], 1)}
    cands = []
    for raiz, _dirs, archivos in os.walk(PROYECCIONES_INTL):
        for f in archivos:
            if not f.lower().endswith('.pdf') or 'latinfocus' not in f.lower():
                continue
            ruta = os.path.join(raiz, f)
            m = re.search(r'(' + '|'.join(MESES) + r')\s+(\d{4})', f, re.IGNORECASE)
            # OneDrive puede tener el archivo "solo en la nube" y hacer fallar el
            # getmtime; ese PDF se saltea en vez de cortar el refresh
            try:
                mtime = os.path.getmtime(ruta)
            except OSError:
                continue
            # si el nombre no dice el mes, desempata por fecha de modificacion
            clave = ((int(m.group(2)), MESES[m.group(1).lower()]) if m else (0, 0), mtime)
            cands.append((clave, ruta, f))
    if not cands:
        status.warn("Internacional Consensus",
                    f"no se encontro actualizacion (no hay PDFs de LatinFocus en {PROYECCIONES_INTL})")
        return False

    cands.sort(key=lambda x: x[0])
    _, pdf, nombre = cands[-1]

    js_path = os.path.join(DATA_DIR, "internacional2.js")
    if os.path.exists(js_path) and os.path.getmtime(js_path) >= os.path.getmtime(pdf):
        status.ok("Internacional Consensus",
                  f"no se encontro actualizacion — el mas nuevo sigue siendo {nombre}")
        return True

    try:
        r = subprocess.run([sys.executable, os.path.join(DASHBOARD_DIR, "parse_latinfocus.py"), pdf],
                           capture_output=True, text=True, cwd=DASHBOARD_DIR, timeout=600)
    except Exception as e:
        status.warn("Internacional Consensus", f"no se pudo procesar {nombre}: {e}")
        return False
    if r.returncode != 0:
        status.warn("Internacional Consensus",
                    f"no se pudo procesar {nombre}: {(r.stderr or r.stdout).strip()[:180]}")
        return False
    status.ok("Internacional Consensus", f"procesado {nombre}")
    return True

def run_resto(status):
    """Corre las secciones que el notebook de clientes no cubre: Empleo,
    Salarios, Tipo de cambio, Actividad IPI, Series largas, Internacional
    (Monitor mundial + LatinFocus) y Mercados.

    Existe para no tener que correr el notebook y ademas refresh.bat: con
    esto, una sola corrida deja todo el dashboard al dia."""
    def _paso(nombre, fn):
        try:
            fn()
        except Exception as e:
            status.fail(nombre, str(e))
            traceback.print_exc()

    def _guardar(nombre, extractor, archivo):
        d = extractor(status)
        if d:
            sz = save_data(archivo, d)
            status.ok(nombre, f"{sz:,} bytes")

    _paso("Empleo",         lambda: _guardar("Empleo", extract_empleo, "empleo"))
    _paso("Salarios",       lambda: _guardar("Salarios", extract_salarios, "salarios"))
    _paso("Tipo de Cambio", lambda: _guardar("Tipo de Cambio", extract_tipo_cambio, "tipo-cambio"))

    def _ipi():
        from extract_actividad_ipi import run_extraction as run_ipi
        r = run_ipi(os.path.join(BASE_EXCEL, "Actividad", "IPI - Todos.xlsx"), DASHBOARD_DIR)
        (status.ok if r["ok"] else status.fail)("Actividad IPI", r["msg"])
    _paso("Actividad IPI", _ipi)

    def _series():
        from extract_series_largas import run_extraction
        anexo = os.path.join(BASE_EXCEL, "03 Informes y Anexos", "Cuadros y Anexos",
                             "Anexos nuevos", "Anexo.xlsx")
        r = run_extraction(anexo, DASHBOARD_DIR)
        (status.ok if r["ok"] else status.fail)("Series Largas", r["msg"])
    _paso("Series Largas", _series)

    _paso("Monitor mundial",        lambda: run_monitor_mundial(status))
    _paso("Internacional",          lambda: extract_internacional(status))
    _paso("Internacional Consensus", lambda: run_latinfocus(status))
    _paso("Mercados",               lambda: extract_mercados(status))

# =====================================================================
#  GITHUB — copiar datos actualizados al repo clonado y hacer push
# =====================================================================
def push_to_github(status):
    """
    Hace git add + commit + push directo desde DASHBOARD_DIR: esta misma
    carpeta es el clon local del repo de GitHub (EcoGoConsultora/Dashboard).
    Antes de subir, trae los cambios del remoto (fetch + merge) para evitar
    que el push se rechace por estar desactualizado.
    No falla el refresh si git no está disponible o no hay cambios: solo
    deja un WARN/FAIL en el resumen.
    """
    import subprocess

    def _run(cmd):
        return subprocess.run(cmd, cwd=DASHBOARD_DIR, capture_output=True, text=True)

    try:
        r = _run(["git", "--version"])
        if r.returncode != 0:
            status.warn("GitHub", "git no est\u00e1 disponible en PATH; instalar Git for Windows")
            return
    except FileNotFoundError:
        status.warn("GitHub", "git no est\u00e1 instalado o no est\u00e1 en PATH")
        return

    if not os.path.isdir(os.path.join(DASHBOARD_DIR, ".git")):
        status.warn("GitHub", f"{DASHBOARD_DIR} no es un repo git (falta la carpeta .git)")
        return

    # Limpiar lock viejo si quedo pegado (p. ej. GitHub Desktop corriendo en simultaneo)
    lock_path = os.path.join(DASHBOARD_DIR, ".git", "index.lock")
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except Exception:
            pass

    r = _run(["git", "add", "-A"])
    if r.returncode != 0:
        status.fail("GitHub - git add", (r.stderr or r.stdout).strip())
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    r = _run(["git", "commit", "-m", f"Actualizacion automatica de datos - {ts}"])
    nothing_local_to_commit = False
    if r.returncode != 0:
        out = (r.stdout + r.stderr).lower()
        if "nothing to commit" in out:
            nothing_local_to_commit = True
        else:
            status.fail("GitHub - git commit", (r.stdout + r.stderr).strip())
            return

    # Traer lo ultimo de GitHub y mezclarlo (por si se subio algo desde otro lado)
    r = _run(["git", "fetch", "origin"])
    if r.returncode != 0:
        status.warn("GitHub - git fetch", (r.stderr or r.stdout).strip())
    else:
        r = _run(["git", "merge", "--no-edit", "origin/main"])
        if r.returncode != 0:
            status.fail(
                "GitHub - git merge",
                (r.stdout + r.stderr).strip() + " (puede necesitar resolucion manual de conflictos en GitHub Desktop)"
            )
            return

    if nothing_local_to_commit:
        r = _run(["git", "rev-list", "--count", "origin/main..HEAD"])
        pending = r.stdout.strip() if r.returncode == 0 else "?"
        if pending in ("0", ""):
            status.ok("GitHub", "sin cambios para subir")
            return

    r = _run(["git", "push", "origin", "main"])
    if r.returncode != 0:
        status.fail("GitHub - git push", (r.stderr or r.stdout).strip())
    else:
        status.ok("GitHub", "cambios subidos a GitHub")

# =====================================================================
#  MAIN
# =====================================================================
def main():
    print("=" * 64)
    print("ECO GO DASHBOARD - Refresh de datos")
    print("=" * 64)
    print(f"Dashboard dir: {DASHBOARD_DIR}")
    print(f"Excel base:    {BASE_EXCEL}")
    print(f"Data dir:      {DATA_DIR}")
    print()

    if not os.path.isdir(DATA_DIR):
        print(f"ERROR: no existe la carpeta {DATA_DIR}")
        return 1

    try:
        import openpyxl  # noqa
    except ImportError:
        print("\nERROR: falta el modulo 'openpyxl'.")
        print("   pip install openpyxl")
        return 1

    status = Status()

    # ---- Precios ----
    print("[1/17] Procesando Precios...")
    try:
        d = extract_precios(status)
        if d:
            sz = save_data("precios", d)
            status.ok("Precios", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Precios", str(e))
        traceback.print_exc()

    # ---- EMAE Series ----
    print("\n[2/17] Procesando EMAE Series (actividad)...")
    try:
        d = extract_emae_series(status)
        if d:
            sz = save_emae_series(d)
            status.ok("EMAE Series", f"{sz:,} bytes guardados en emae_series.js")
    except Exception as e:
        status.fail("EMAE Series", str(e))
        traceback.print_exc()

    # ---- Empleo ----
    print("\n[3/17] Procesando Empleo...")
    try:
        d = extract_empleo(status)
        if d:
            sz = save_data("empleo", d)
            status.ok("Empleo", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Empleo", str(e))
        traceback.print_exc()

    # ---- Salarios ----
    print("\n[4/17] Procesando Salarios...")
    try:
        d = extract_salarios(status)
        if d:
            sz = save_data("salarios", d)
            status.ok("Salarios", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Salarios", str(e))
        traceback.print_exc()

    # ---- Tipo de Cambio ----
    print("\n[5/17] Procesando Tipo de Cambio...")
    try:
        d = extract_tipo_cambio(status)
        if d:
            sz = save_data("tipo-cambio", d)
            status.ok("Tipo de Cambio", f"{sz:,} bytes - {len(d.get('tcn_series',[]))} pts TCN")
    except Exception as e:
        status.fail("Tipo de Cambio", str(e))
        traceback.print_exc()

    # ---- Reservas ----
    print("\n[6/17] Procesando Reservas...")
    try:
        d = extract_reservas(status)
        if d:
            sz = save_data("reservas", d)
            status.ok("Reservas", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Reservas", str(e))
        traceback.print_exc()

    # ---- Internacional ----
    print("\n[7/17] Procesando Internacional (Monitor mundial)...")
    try:
        run_monitor_mundial(status)
        extract_internacional(status)
        run_latinfocus(status)
    except Exception as e:
        status.fail("Internacional", str(e))
        traceback.print_exc()

    # ---- Mercados (API) ----
    print("\n[8/17] Actualizando Mercados (EcoGo Markets API)...")
    try:
        extract_mercados(status)
    except Exception as e:
        status.warn("Mercados", f"no se pudo actualizar desde la API: {e}")

    # ---- Actividad IPI (Indicadores de actividad) ----
    print("\n[9/17] Actualizando Indicadores de Actividad (IPI - Todos.xlsx)...")
    try:
        from extract_actividad_ipi import run_extraction as run_ipi
        ipi_path = os.path.join(BASE_EXCEL, "Actividad", "IPI - Todos.xlsx")
        result = run_ipi(ipi_path, DASHBOARD_DIR)
        if result["ok"]:
            status.ok("Actividad IPI", result["msg"])
        else:
            status.fail("Actividad IPI", result["msg"])
    except Exception as e:
        status.fail("Actividad IPI", str(e))
        traceback.print_exc()

    # ---- Series Largas (Anexo histórico) ----
    print("\n[10/17] Actualizando Series Largas (Anexo.xlsx)...")
    try:
        from extract_series_largas import run_extraction
        anexo_path = os.path.join(BASE_EXCEL, "03 Informes y Anexos", "Cuadros y Anexos", "Anexos nuevos", "Anexo.xlsx")
        result = run_extraction(anexo_path, DASHBOARD_DIR)
        if result["ok"]:
            status.ok("Series Largas", result["msg"])
        else:
            status.fail("Series Largas", result["msg"])
    except Exception as e:
        status.fail("Series Largas", str(e))
        traceback.print_exc()

    # ---- Monetarias ----
    print("\n[11/17] Procesando Monetarias...")
    try:
        d = extract_monetarias(status)
        if d:
            sz = save_data("monetarias", d)
            status.ok("Monetarias", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Monetarias", str(e))
        traceback.print_exc()

    # ---- Deuda ----
    print("\n[12/17] Procesando Deuda...")
    try:
        d = extract_deuda(status)
        if d:
            sz = save_data("deuda", d)
            status.ok("Deuda", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Deuda", str(e))
        traceback.print_exc()

    # ---- Monitor de Actividad ----
    print("\n[13/17] Procesando Monitor de Actividad...")
    try:
        d = extract_monitor_actividad(status)
        if d:
            status.ok("Monitor de Actividad", f"{save_data('monitor_actividad', d):,} bytes")
    except Exception as e:
        status.fail("Monitor de Actividad", str(e))
        traceback.print_exc()

    # ---- Comercio exterior ----
    print("\n[14/17] Procesando Comercio exterior...")
    try:
        d = extract_comercio(status)
        if d:
            sz = save_data("comercio", d)
            status.ok("Comercio exterior", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Comercio exterior", str(e))
        traceback.print_exc()

    # ---- Potencial exportador 2026-2036 ----
    print("\n[15/17] Procesando Potencial exportador...")
    try:
        d = extract_potencial_exportador(status)
        if d:
            sz = save_data("potencial_exportador", d)
            status.ok("Potencial exportador", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Potencial exportador", str(e))
        traceback.print_exc()

    # ---- Tenencia DLK BCRA ----
    print("\n[16/17] Procesando Tenencia DLK BCRA...")
    try:
        d = extract_tenencia_dlk(status)
        if d:
            sz = save_data("tenencia_dlk", d)
            status.ok("Tenencia DLK BCRA", f"{sz:,} bytes")
    except Exception as e:
        status.fail("Tenencia DLK BCRA", str(e))
        traceback.print_exc()

    # ---- Monitor de tasas (completa Mercados) ----
    print("\n[17/17] Procesando Monitor de tasas...")
    try:
        d = extract_monitor_tasas(status)
        if d:
            sz = save_data("monitor_tasas", d)
            status.ok("Monitor de tasas", f"{sz:,} bytes")
            completar_mercados(status, d)
    except Exception as e:
        status.fail("Monitor de tasas", str(e))
        traceback.print_exc()

    # ---- Sellar la version de los datos en las paginas ----
    # Va justo antes del push para que el cambio de HTML entre en el commit.
    sellar_versiones(status)

    # ---- Subir cambios a GitHub ----
    print("\nSubiendo cambios a GitHub...")
    try:
        push_to_github(status)
    except Exception as e:
        status.fail("GitHub", str(e))
        traceback.print_exc()

    # ---- Resumen ----
    print()
    print("=" * 64)
    ok   = sum(1 for r in status.results if r[0] == "OK")
    warn = sum(1 for r in status.results if r[0] == "WARN")
    fail = sum(1 for r in status.results if r[0] == "FAIL")
    print(f"Resumen: {ok} OK - {warn} warnings - {fail} errores")
    print()
    if fail == 0:
        print("LISTO: refrescar el dashboard en el navegador.")
        return 0
    else:
        print("Hubo errores. Revisar las rutas en CONFIGURACION del script.")
        return 1

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
