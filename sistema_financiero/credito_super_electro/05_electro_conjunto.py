"""Agrega al Excel de crédito de supermercados la mora de las cadenas de electrodomésticos y el
conjunto supermercados + electro.

Entradas:
  - Credito_Supermercados.xlsx (salida del paso 04): series de supermercados y deflactor implícito
    (pesos constantes / pesos corrientes de la columna Total de "Crédito mensual").
  - PNFC.xlsx (proyecto PNFC): saldo e irregularidad (sit. 3+4+5) mensual por entidad desde la
    Central de Deudores, en miles de millones de $.
  - hechos_<periodo>.parquet (proyecto Ranking de crédito): entidad x persona x situación -> saldo,
    para la situación 2 (mora temprana). Solo los meses disponibles.

Requiere openpyxl >= 3.1, que conserva los gráficos existentes al abrir el xlsx (se verifica que
las hojas originales mantengan un gráfico cada una).
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import openpyxl
import pandas as pd
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties

from xlsx_marca import GRAY_LIGHT, TEAL, TEAL_DARK, celda, encabezados, pie, titulo

ORIG, PNFC, HECHOS, DESTINO = (Path(a) for a in sys.argv[1:5])

PALETA = ["3C9794", "8FCCCA", "1B5F5E", "84BF84", "FEB15F", "DA4531", "89C442", "FE8B5F", "70A134"]
MM = "#,##0"
PCT = "0.0%"
MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
IPC_ULTIMO = 202609
F_CENDEU = "Fuente: EcoGo en base a BCRA, Central de Deudores del Sistema Financiero (24DSF)"

# código BCRA -> (nombre, cadena). Megatone, Cetrogar, Frávega, Favanet y Carsa figuran como
# "Retail y electrodomésticos" en la taxonomía del ranking de crédito; Naldo Lombardi figura como
# "Otros proveedores no financieros" y se incorpora por ser la razón social de la cadena Naldo.
ELECTRO = {
    55027: ("Electrónica Megatone S.R.L.", "Megatone"),
    55041: ("Naldo Lombardi S.A.", "Naldo"),
    55011: ("Cetrogar S.A.", "Cetrogar"),
    55030: ("Frávega S.A.C.I. e I.", "Frávega"),
    55028: ("Favanet S.A.", "Favanet"),
    55009: ("Carsa S.A.", "Musimundo (Carsa)"),
}
SUPER = [(332, "BSF (Carrefour Banco)"), (70147, "Cencosud S.A. (Tarjeta Cencosud)"),
         (70224, "Tarjetas del Mar S.A. (Tarjeta La Anónima)"), (70140, "Coto CIC (Tarjeta TCI)")]


def etiqueta(p: int) -> str:
    return f"{MES[p % 100 - 1]}-{str(p)[2:4]}"


def periodo(lab: str) -> int:
    m, a = lab.split("-")
    return 2000_00 + int(a) * 100 + MES.index(m) + 1


def sumar_meses(p: int, n: int) -> int:
    t = (p // 100) * 12 + p % 100 - 1 + n
    return (t // 12) * 100 + t % 12 + 1


# ---------------------------------------------------------------- datos

def datos_super(wb):
    """Saldo, mora y sit. 2 por entidad de supermercados, y deflactor implícito, desde el Excel."""
    cm, mo = wb["Crédito mensual"], wb["Mora mensual"]
    filas = {}
    for r in range(5, cm.max_row + 1):
        lab = cm.cell(r, 1).value
        if not isinstance(lab, str) or "-" not in lab or len(lab) > 7:
            continue
        p = periodo(lab.rstrip("*"))
        assert mo.cell(r, 1).value == lab
        filas[p] = {"factor": cm.cell(r, 11).value / cm.cell(r, 6).value}
        for i, (e, _) in enumerate(SUPER):
            s = cm.cell(r, 2 + i).value
            filas[p][e] = {"saldo": s, "irr": s * mo.cell(r, 2 + i).value, "sit2": s * mo.cell(r, 7 + i).value}
    return filas


def datos_pnfc(periodos):
    wb = openpyxl.load_workbook(PNFC, read_only=True, data_only=True)
    out = {}
    for hoja, campo in (("Carteras", "saldo"), ("Irregularidad", "irr")):
        rows = list(wb[hoja].iter_rows(values_only=True))
        enc = [periodo(c) for c in rows[4][2:]]
        for r in rows[5:]:
            if r[0] in ELECTRO:
                for p, v in zip(enc, r[2:]):
                    out.setdefault(r[0], {}).setdefault(p, {})[campo] = v * 1000  # miles de millones -> millones
    for e in ELECTRO:
        assert all(p in out[e] for p in periodos), f"faltan meses de {e} en PNFC"
    return out


def datos_sit2():
    """sit. 2 / saldo y saldo por entidad (electro) en los meses con hechos disponibles."""
    out = {}
    for f in sorted(glob.glob(str(HECHOS / "hechos_*.parquet"))):
        d = pd.read_parquet(f)
        p = int(d["periodo"].iloc[0])
        for e in ELECTRO:
            x = d[d["entidad"] == e]
            out.setdefault(e, {})[p] = {"saldo": x["saldo_mm"].sum(),
                                        "sit2": x.loc[x["situacion"] == 2, "saldo_mm"].sum()}
    return out


# ---------------------------------------------------------------- utilidades

def anchos(ws, cols):
    from openpyxl.utils import get_column_letter
    for j, w in cols.items():
        ws.column_dimensions[get_column_letter(j)].width = w


def estilo_eje(ch, eje_y, fmt):
    ch.y_axis.title = eje_y
    ch.y_axis.numFmt = fmt
    ch.y_axis.majorGridlines.spPr = GraphicalProperties(ln=LineProperties(solidFill="D9D9D9"))
    ch.x_axis.number_format = "@"
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.legend.position = "b"


def grafico(ws, titulo_g, eje_y, fila_enc, fila_fin, cols, ancla, fmt=MM, ancho=22, alto=9.5, colores=None,
            marcadores=False):
    """Igual a 04_excel.py (líneas)."""
    ch = LineChart()
    ch.title = titulo_g
    estilo_eje(ch, eje_y, fmt)
    ch.width, ch.height = ancho, alto
    for i, col in enumerate(cols):
        ch.add_data(Reference(ws, min_col=col, min_row=fila_enc, max_row=fila_fin), titles_from_data=True)
        serie = ch.series[-1]
        serie.graphicalProperties.line.solidFill = (colores or PALETA)[i % len(colores or PALETA)]
        serie.graphicalProperties.line.width = 22000
        serie.smooth = False
        if marcadores:  # meses aislados con dato (sit. 2 de electro) no se verían como línea
            serie.marker.symbol, serie.marker.size = "circle", 4
            serie.marker.graphicalProperties = GraphicalProperties(solidFill=(colores or PALETA)[i % len(colores or PALETA)])
            serie.marker.graphicalProperties.line.solidFill = (colores or PALETA)[i % len(colores or PALETA)]
    ch.set_categories(Reference(ws, min_col=1, min_row=fila_enc + 1, max_row=fila_fin))
    ws.add_chart(ch, ancla)


def tabla_mensual(ws, fila0, periodos, columnas):
    encabezados(ws, fila0, ["Mes", *[c[0] for c in columnas]])
    for i, p in enumerate(periodos, start=1):
        f = fila0 + i
        fill = GRAY_LIGHT if i % 2 == 0 else None
        celda(ws, f, 1, etiqueta(p), fill=fill, h="center")
        for j, (_, serie, fmt) in enumerate(columnas, start=2):
            celda(ws, f, j, serie.get(p), fmt=fmt, fill=fill, h="right")
    return fila0 + len(periodos)


def pc(x: float) -> str:
    return f"{x:.1%}".replace(".", ",")


def var(a, b):
    return a / b - 1 if a is not None and b else None


# ---------------------------------------------------------------- gráficos originales

def graficos_originales(wb):
    grafico(wb["Crédito mensual"], f"Saldo en pesos constantes de {etiqueta(IPC_ULTIMO)} ($ millones)", "$ millones",
            4, 51, [7, 8, 9, 10], "M4")
    grafico(wb["Mora mensual"], "Mora: situación 3+4+5 sobre saldo total", "%", 4, 51, [2, 3, 4, 5, 6], "M4",
            fmt="0%")
    grafico(wb["Serie larga IEF"], f"Préstamos en pesos constantes de {etiqueta(IPC_ULTIMO)} ($ millones)",
            "$ millones", 4, 120, [6, 11], "M4")
    grafico(wb["Mora IEF"], "BSF (Carrefour Banco): mora según su balance", "%", 5, 39, [8], "K4", fmt="0%",
            ancho=18, alto=8)


# ---------------------------------------------------------------- hojas nuevas

def hoja_electro_credito(wb, periodos, el, factor):
    ws = wb.create_sheet("Electro crédito")
    n = len(ELECTRO) + 1
    titulo(ws, "Saldo de financiaciones de las cadenas de electrodomésticos",
           f"Millones de pesos corrientes y pesos constantes de {etiqueta(IPC_ULTIMO)} (IPC INDEC) · Central de "
           f"Deudores · último dato: {etiqueta(periodos[-1])}", 2 * n + 1)
    celda(ws, 3, 2, "Pesos corrientes ($ millones)", bold=True, color=TEAL)
    celda(ws, 3, 2 + n, f"Pesos constantes de {etiqueta(IPC_ULTIMO)} ($ millones)", bold=True, color=TEAL)
    cols = []
    for real in (False, True):
        tot = {}
        for e, (nom, _) in ELECTRO.items():
            d = {p: el[e][p]["saldo"] * (factor[p] if real else 1) for p in periodos}
            cols.append((nom, d, MM))
            for k, v in d.items():
                tot[k] = tot.get(k, 0) + v
        cols.append(("Total electro", tot, MM))
    fin = tabla_mensual(ws, 4, periodos, cols)
    ws.row_dimensions[4].height = 44
    pie(ws, fin + 1, f"{F_CENDEU}. Saldo = préstamos + garantías otorgadas + otros conceptos, por entidad "
                     "(Base_Unificada_24DSF, procesada en PNFC.xlsx). Datos provisorios del BCRA.", 2 * n + 1)
    anchos(ws, {1: 9, **{j: 15 for j in range(2, 2 * n + 2)}})
    ws.freeze_panes = "B5"
    grafico(ws, f"Electro: saldo en pesos constantes de {etiqueta(IPC_ULTIMO)} ($ millones)", "$ millones", 4, fin,
            list(range(2 + n, 2 * n + 1)), "Q4")


def hoja_electro_mora(wb, periodos, el, s2, s2_meses):
    ws = wb.create_sheet("Electro mora")
    n = len(ELECTRO) + 1
    titulo(ws, "Mora de las cadenas de electrodomésticos (situación 3+4+5 sobre saldo total)",
           "Central de Deudores · situación 2 (seguimiento especial) como señal adelantada, en los meses con dato "
           f"por situación disponible · último dato: {etiqueta(periodos[-1])}", 2 * n + 1)
    celda(ws, 3, 2, "Mora (sit. 3+4+5 / total)", bold=True, color=TEAL)
    celda(ws, 3, 2 + n, "Situación 2 / total", bold=True, color=TEAL)
    cols = []
    for e, (nom, _) in ELECTRO.items():
        cols.append((nom, {p: el[e][p]["irr"] / el[e][p]["saldo"] for p in periodos}, PCT))
    cols.append(("Total electro (ponderado por saldo)",
                 {p: sum(el[e][p]["irr"] for e in ELECTRO) / sum(el[e][p]["saldo"] for e in ELECTRO)
                  for p in periodos}, PCT))
    for e, (nom, _) in ELECTRO.items():
        cols.append((nom, {p: s2[e][p]["sit2"] / s2[e][p]["saldo"] for p in s2_meses}, PCT))
    cols.append(("Total electro (ponderado por saldo)",
                 {p: sum(s2[e][p]["sit2"] for e in ELECTRO) / sum(s2[e][p]["saldo"] for e in ELECTRO)
                  for p in s2_meses}, PCT))
    fin = tabla_mensual(ws, 4, periodos, cols)
    ws.row_dimensions[4].height = 44
    faltan = [etiqueta(p) for p in periodos if p not in s2_meses]
    nota = ("Situación 2: sin dato en " + ", ".join(faltan) + ". Esos meses de la tabla de hechos por situación no "
            "pudieron descargarse en esta actualización (ver Metodología); saldo y mora 3+4+5 están completos.")
    pie(ws, fin + 1, f"{F_CENDEU}. El saldo incluye irrecuperables fuera de balance (otros conceptos). Los "
                     "proveedores no financieros no están alcanzados por las normas de previsionamiento y baja de "
                     "cartera de las entidades financieras: la cartera irrecuperable tiende a quedar informada.",
        2 * n + 1, nota=nota)
    anchos(ws, {1: 9, **{j: 15 for j in range(2, 2 * n + 2)}})
    ws.freeze_panes = "B5"
    grafico(ws, "Electro: mora (situación 3+4+5 sobre saldo total)", "%", 4, fin, list(range(2, 2 + n)), "Q4",
            fmt="0%")


def hoja_conjunto(wb, periodos, sp, el, s2, s2_meses):
    ws = wb.create_sheet("Super + Electro")
    titulo(ws, "Supermercados + electrodomésticos: crédito y mora del conjunto",
           f"Central de Deudores · $ millones de {etiqueta(IPC_ULTIMO)} (IPC INDEC) y % del saldo · último dato: "
           f"{etiqueta(periodos[-1])}", 13)
    S = [e for e, _ in SUPER]
    E = list(ELECTRO)
    g = {}
    for p in periodos:
        f = sp[p]["factor"]
        ss = sum(sp[p][e]["saldo"] for e in S)
        es = sum(el[e][p]["saldo"] for e in E)
        si = sum(sp[p][e]["irr"] for e in S)
        ei = sum(el[e][p]["irr"] for e in E)
        g[p] = dict(ss=ss, es=es, si=si, ei=ei, f=f, s2s=sum(sp[p][e]["sit2"] for e in S) / ss)
        if p in s2_meses:
            # sit. 2 de electro con su propio saldo de la tabla de hechos (misma fuente que el numerador)
            e2 = sum(s2[e][p]["sit2"] for e in E) / sum(s2[e][p]["saldo"] for e in E)
            g[p]["s2e"] = e2
            g[p]["s2c"] = (g[p]["s2s"] * ss + e2 * es) / (ss + es)
    celda(ws, 3, 2, f"Saldo en pesos constantes de {etiqueta(IPC_ULTIMO)} ($ millones)", bold=True, color=TEAL)
    celda(ws, 3, 5, "Mora (sit. 3+4+5 / total)", bold=True, color=TEAL)
    celda(ws, 3, 8, "Mora temprana (sit. 2 / total)", bold=True, color=TEAL)
    celda(ws, 3, 11, "Saldo en pesos corrientes ($ millones)", bold=True, color=TEAL)
    col = lambda fn: {p: fn(g[p]) for p in periodos if fn(g[p]) is not None}  # noqa: E731
    cols = [
        ("Supermercados", col(lambda x: x["ss"] * x["f"]), MM),
        ("Electrodomésticos", col(lambda x: x["es"] * x["f"]), MM),
        ("Total super + electro", col(lambda x: (x["ss"] + x["es"]) * x["f"]), MM),
        ("Mora supermercados", col(lambda x: x["si"] / x["ss"]), PCT),
        ("Mora electrodomésticos", col(lambda x: x["ei"] / x["es"]), PCT),
        ("Mora conjunta", col(lambda x: (x["si"] + x["ei"]) / (x["ss"] + x["es"])), PCT),
        ("Mora temprana supermercados", col(lambda x: x["s2s"]), PCT),
        ("Mora temprana electrodomésticos", col(lambda x: x.get("s2e")), PCT),
        ("Mora temprana conjunta", col(lambda x: x.get("s2c")), PCT),
        ("Supermercados", col(lambda x: x["ss"]), MM),
        ("Electrodomésticos", col(lambda x: x["es"]), MM),
        ("Total super + electro", col(lambda x: x["ss"] + x["es"]), MM),
    ]
    fin = tabla_mensual(ws, 4, periodos, cols)
    ws.row_dimensions[4].height = 44
    faltan = [etiqueta(p) for p in periodos if p not in s2_meses]
    nota = ("Mora temprana de electro y conjunta: sin dato en " + ", ".join(faltan) + " (ver Metodología). "
            "Supermercados: BSF, Cencosud, Tarjetas del Mar y Coto. Electro: Megatone, Naldo, Cetrogar, Frávega, "
            "Favanet y Carsa. Las tasas del conjunto se ponderan por saldo.")
    pie(ws, fin + 1, f"{F_CENDEU}; procesamiento EcoGo (PNFC y tabla de hechos mensual). Pesos constantes de "
                     f"{etiqueta(IPC_ULTIMO)} (IPC INDEC), con el mismo deflactor que \"Crédito mensual\".", 13,
        nota=nota)
    anchos(ws, {1: 9, **{j: 14 for j in range(2, 14)}})
    ws.freeze_panes = "B5"

    # 1) saldo real (columnas apiladas) + mora conjunta (línea, eje secundario)
    bar = BarChart()
    bar.type, bar.grouping, bar.overlap, bar.gapWidth = "col", "stacked", 100, 40
    bar.title = f"Saldo en pesos constantes de {etiqueta(IPC_ULTIMO)} y mora conjunta"
    estilo_eje(bar, "$ millones", MM)
    for i, c in enumerate((2, 3)):
        bar.add_data(Reference(ws, min_col=c, min_row=4, max_row=fin), titles_from_data=True)
        bar.series[-1].graphicalProperties.solidFill = ["8FCCCA", "1B5F5E"][i]
        bar.series[-1].graphicalProperties.line.noFill = True
    bar.set_categories(Reference(ws, min_col=1, min_row=5, max_row=fin))
    lin = LineChart()
    lin.add_data(Reference(ws, min_col=7, min_row=4, max_row=fin), titles_from_data=True)
    lin.series[0].graphicalProperties.line.solidFill = "DA4531"
    lin.series[0].graphicalProperties.line.width = 28000
    lin.series[0].smooth = False
    lin.y_axis.axId = 200
    lin.y_axis.title = "Mora (%)"
    lin.y_axis.numFmt = "0%"
    lin.y_axis.majorGridlines = None
    lin.y_axis.crosses = "max"
    lin.y_axis.delete = False
    bar += lin
    bar.width, bar.height = 24, 11
    ws.add_chart(bar, "P4")
    # 2) mora electro, super y conjunta
    grafico(ws, "Mora (sit. 3+4+5): supermercados, electrodomésticos y conjunta", "%", 4, fin, [5, 6, 7], "P27",
            fmt="0%", ancho=24, alto=11, colores=["3C9794", "FEB15F", "DA4531"])
    # 3) mora temprana electro, super y conjunta
    grafico(ws, "Mora temprana (sit. 2): cadenas de supermercados y de electrodomésticos", "%", 4, fin, [8, 9, 10],
            "P50", fmt="0.0%", ancho=24, alto=11, colores=["3C9794", "FEB15F", "DA4531"], marcadores=True)
    return g


def hoja_resumen_electro(wb, periodos, sp, el, s2, s2_meses, g):
    ws = wb.create_sheet("Resumen electro y conjunto")
    p = periodos[-1]
    p12, pdic = sumar_meses(p, -12), (p // 100 - 1) * 100 + 12
    ps2 = max(s2_meses)
    titulo(ws, "Crédito de las cadenas de electrodomésticos y total con supermercados",
           f"Saldo de financiaciones y mora por entidad · Central de Deudores · último dato: {etiqueta(p)}", 10)
    enc = ["Entidad", "Cadena", f"Saldo {etiqueta(p)}\n($ millones)", "Participación",
           f"Var. real i.a.\n({etiqueta(p)} vs {etiqueta(p12)})", f"Var. real vs {etiqueta(pdic)}",
           f"Mora {etiqueta(p12)}", f"Mora {etiqueta(p)}", "Δ mora (pp)", f"Mora temprana\n(sit. 2) {etiqueta(ps2)}"]
    encabezados(ws, 4, enc)
    ws.row_dimensions[4].height = 44
    fmts = [None, None, MM, PCT, PCT, PCT, PCT, PCT, "0.0", PCT]
    f_ = lambda q: sp[q]["factor"]  # noqa: E731
    tot = sum(el[e][p]["saldo"] for e in ELECTRO)
    f = 5
    for e, (nom, cad) in ELECTRO.items():
        d = el[e]
        m0, m1 = d[p12]["irr"] / d[p12]["saldo"], d[p]["irr"] / d[p]["saldo"]
        fila = [nom, cad, d[p]["saldo"], d[p]["saldo"] / tot,
                var(d[p]["saldo"] * f_(p), d[p12]["saldo"] * f_(p12)),
                var(d[p]["saldo"] * f_(p), d[pdic]["saldo"] * f_(pdic)), m0, m1, (m1 - m0) * 100,
                s2[e][ps2]["sit2"] / s2[e][ps2]["saldo"]]
        for j, (v, fm) in enumerate(zip(fila, fmts), start=1):
            celda(ws, f, j, v, fmt=fm, h="left" if j <= 2 else "right")
        ws.row_dimensions[f].height = 20
        f += 1
    x0, x1, xd = g[p12], g[p], g[pdic]
    filas_tot = [
        ("Total electrodomésticos", "es", "ei", "s2e"),
        ("Total supermercados", "ss", "si", "s2s"),
        ("Total super + electro", None, None, "s2c"),
    ]
    f += 1
    celda(ws, f, 1, "Agregados por segmento", bold=True, color=TEAL_DARK)
    f += 1
    encabezados(ws, f, ["Segmento", "", f"Saldo {etiqueta(p)}\n($ millones)", "Participación en el conjunto",
                        f"Var. real i.a.\n({etiqueta(p)} vs {etiqueta(p12)})", f"Var. real vs {etiqueta(pdic)}",
                        f"Mora {etiqueta(p12)}", f"Mora {etiqueta(p)}", "Δ mora (pp)",
                        f"Mora temprana\n(sit. 2) {etiqueta(ps2)}"])
    ws.row_dimensions[f].height = 44
    f += 1
    sal = lambda x, k: x["ss"] + x["es"] if k is None else x[k]  # noqa: E731
    irr = lambda x, k: x["si"] + x["ei"] if k is None else x[k]  # noqa: E731
    for lab, ks, ki, k2 in filas_tot:
        m0, m1 = irr(x0, ki) / sal(x0, ks), irr(x1, ki) / sal(x1, ks)
        fila = [lab, "", sal(x1, ks), sal(x1, ks) / sal(x1, None),
                var(sal(x1, ks) * x1["f"], sal(x0, ks) * x0["f"]), var(sal(x1, ks) * x1["f"], sal(xd, ks) * xd["f"]),
                m0, m1, (m1 - m0) * 100, g[ps2][k2]]
        tot_row = ks is None
        for j, (v, fm) in enumerate(zip(fila, fmts), start=1):
            celda(ws, f, j, v, fmt=fm, bold=tot_row, fill="DDEFEE" if tot_row else None,
                  h="left" if j <= 2 else "right")
        f += 1
    f += 1
    notas = [
        "Lectura",
        f"• Mora del conjunto en {etiqueta(p)}: {pc((x1['si'] + x1['ei']) / (x1['ss'] + x1['es']))} del saldo "
        f"(supermercados {pc(x1['si'] / x1['ss'])}; electrodomésticos {pc(x1['ei'] / x1['es'])}).",
        "• Electro: entidades no financieras que financian a las cadenas (proveedores no financieros de crédito, "
        "códigos BCRA 55xxx). Mismo criterio de saldo y de mora que la hoja \"Mora mensual\" de supermercados.",
        f"• Mora temprana (sit. 2): la columna toma {etiqueta(ps2)}, último mes con apertura por situación disponible "
        f"para electro; {etiqueta(p)} no pudo descargarse en esta actualización.",
        "• No incluido: Coppel S.A. (tienda departamental; informa de forma intermitente a la Central), Hogar Total "
        "S.A. y Hendel Hogar S.A. (no se verificó su vínculo con cadenas de electrodomésticos).",
    ]
    for i, t in enumerate(notas):
        celda(ws, f, 1, t, bold=i == 0, color=TEAL_DARK if i == 0 else "333333", wrap=True, v="top")
        ws.merge_cells(start_row=f, start_column=1, end_row=f, end_column=10)
        ws.row_dimensions[f].height = 16 if i == 0 else 30
        f += 1
    pie(ws, f, f"{F_CENDEU}; procesamiento EcoGo. Variaciones reales en pesos constantes de {etiqueta(IPC_ULTIMO)} "
               f"(IPC INDEC). Último dato: {etiqueta(p)}.", 10)
    anchos(ws, {1: 32, 2: 18, 3: 14, 4: 13, 5: 15, 6: 14, 7: 11, 8: 11, 9: 10, 10: 14})
    ws.freeze_panes = "A5"


def metodologia(wb, periodos, s2_meses):
    ws = wb["Metodología"]
    f0 = 4
    while ws.cell(f0, 1).value and not str(ws.cell(f0, 1).value).startswith("Fuente"):
        f0 += 1
    # f0 = primera fila vacía después de las filas originales; se borran pie y web y se agregan filas
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row >= f0:
            ws.unmerge_cells(str(rng))
    for r in range(f0, ws.max_row + 1):
        for c in (1, 2):
            ws.cell(r, c).value = None
    faltan = [etiqueta(p) for p in periodos if p not in s2_meses]
    filas = [
        ("Universo electro", "Proveedores no financieros de crédito de las cadenas de electrodomésticos: Electrónica "
         "Megatone S.R.L. (55027), Naldo Lombardi S.A. (55041), Cetrogar S.A. (55011), Frávega S.A.C.I. e I. (55030), "
         "Favanet S.A. (55028) y Carsa S.A. (55009). Las cinco últimas, salvo Naldo, figuran como \"Retail y "
         "electrodomésticos\" en la taxonomía del ranking de crédito; Naldo Lombardi figura como \"Otros proveedores "
         "no financieros\" y se incorpora por ser la razón social de la cadena Naldo. Coto CIC, que la taxonomía "
         "también clasifica como retail, se mantiene en supermercados."),
        ("Saldo y mora electro", "Misma definición que supermercados: suma del monto de la Central de Deudores por "
         "entidad (préstamos + garantías + otros conceptos) y mora = saldo en situación 3, 4 y 5 sobre el total. "
         "Fuente operativa: PNFC.xlsx (Carteras e Irregularidad, Base_Unificada_24DSF), en miles de millones, pasada "
         "a millones. Se verificó que coincide con la tabla de hechos mensual (p. ej. Megatone jul-26: $353.136 "
         "millones y 59,55% de mora en ambas fuentes) y que reproduce la serie de supermercados de este archivo."),
        ("Mora temprana electro", "Situación 2 sobre saldo, desde la tabla de hechos mensual (entidad x situación). "
         "Disponible para " + str(len(s2_meses)) + " de " + str(len(periodos)) + " meses; sin dato en "
         + ", ".join(faltan) + ": esos archivos no pudieron descargarse en esta actualización. Para completarla "
         "basta agregar las seis entidades a ENTIDADES en config.py y correr 02_cendeu.py, que ya calcula la "
         "situación 2 por entidad. Los 22 archivos usados reproducen la mora y la situación 2 de supermercados de "
         "este Excel (diferencia máxima 0,0014 pp)."),
        ("Conjunto super + electro", "Suma de saldos de ambos segmentos; las tasas del conjunto (mora y mora "
         "temprana) se ponderan por saldo. Pesos constantes de " + etiqueta(IPC_ULTIMO) + " con el mismo deflactor "
         "que \"Crédito mensual\" (IPC INDEC)."),
        ("Comparabilidad", "Los proveedores no financieros no aplican las normas de previsionamiento y baja de "
         "cartera de las entidades financieras: la cartera irrecuperable tiende a quedar informada en la Central y "
         "eleva la mora sobre el total. Supuestos no verificados: Carsa S.A. se atribuye a Musimundo; Favanet S.A. "
         "se toma según la clasificación de la taxonomía. Datos de la Central marcados como provisorios en la fuente."),
    ]
    for i, (k, v) in enumerate(filas, start=f0):
        celda(ws, i, 1, k, bold=True, color=TEAL_DARK, v="top", wrap=True)
        celda(ws, i, 2, v, wrap=True, v="top")
        ws.row_dimensions[i].height = 90
    pie(ws, f0 + len(filas), f"{F_CENDEU}; BCRA, Información de Entidades Financieras (balhist y esd); "
                                 "INDEC (IPC).", 2)


def main():
    wb = openpyxl.load_workbook(ORIG)
    sp = datos_super(wb)
    periodos = sorted(sp)
    el = datos_pnfc(periodos)
    s2 = datos_sit2()
    s2_meses = sorted(p for p in s2[55027] if p in sp)
    factor = {p: sp[p]["factor"] for p in periodos}
    g = hoja_conjunto(wb, periodos, sp, el, s2, s2_meses)
    hoja_resumen_electro(wb, periodos, sp, el, s2, s2_meses, g)
    hoja_electro_credito(wb, periodos, el, factor)
    hoja_electro_mora(wb, periodos, el, s2, s2_meses)
    metodologia(wb, periodos, s2_meses)
    orden = ["Resumen", "Resumen electro y conjunto", "Super + Electro", "Crédito mensual", "Mora mensual",
             "Electro crédito", "Electro mora", "Serie larga IEF", "Mora IEF", "Control componentes", "Metodología"]
    assert sorted(orden) == sorted(ws.title for ws in wb.worksheets)
    wb._sheets = [wb[t] for t in orden]
    wb.active = 0
    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = TEAL
    for t in ("Crédito mensual", "Mora mensual", "Serie larga IEF", "Mora IEF"):
        assert len(wb[t]._charts) == 1, f"{t}: se perdió o duplicó el gráfico original"
    wb.save(DESTINO)
    print("->", DESTINO, [ws.title for ws in wb.worksheets])


if __name__ == "__main__":
    main()
