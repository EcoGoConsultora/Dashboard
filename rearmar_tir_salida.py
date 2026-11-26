# -*- coding: utf-8 -*-
r"""
Rearma pages/tir-salida-clientes.html desde el prototipo interactivo.

La pagina de TIR de salida no se escribe a mano: es el prototipo que armo el
ejercicio, con la estetica del tablero encima. Este script hace ese pasaje, y
se corre solo cuando el prototipo cambia (bonos nuevos, flujos corregidos,
otra fecha de salida).

    python rearmar_tir_salida.py

Lo que cambia:
  - la paleta y la tipografia pasan a ser las de Eco Go,
  - el CSS del prototipo se encierra bajo .tir para no pelearse con theme.css,
  - la cabecera propia del prototipo la reemplaza la del tablero.

Lo que NO cambia: el markup del simulador, los datos embebidos y toda la
logica van tal cual. Es la misma herramienta, no una version del tablero.

Los precios del dia los agrega refresh.py en assets/data/tir_salida_precios.js
y se pisan sobre los embebidos, asi que esto no hace falta para actualizar.
"""
import io
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(os.path.dirname(os.path.dirname(AQUI)),
                     "Mercados", "Ejercicio TIR de salida", "outputs",
                     "prototipo-tir-salida.html")
if not os.path.exists(PROTO):
    PROTO = (r"C:\Users\fscalise\OneDrive - ECOGO S.A\BD\Mercados"
             r"\Ejercicio TIR de salida\outputs\prototipo-tir-salida.html")
DEST = os.path.join(AQUI, "pages", "tir-salida-clientes.html")
V = "202611261608"          # sellar_versiones() lo reescribe en cada corrida

ROOT = ".tir"


# =====================================================================
#  1. El CSS del prototipo, encerrado bajo .tir
# =====================================================================
def scope_sel(sel):
    """Prefija cada selector. :root y body pasan a ser el contenedor."""
    salida = []
    for parte in sel.split(","):
        p = parte.strip()
        if not p:
            continue
        if p in (":root", "body", "html"):
            salida.append(ROOT)
        elif p.startswith("@"):
            salida.append(p)
        else:
            salida.append(ROOT + " " + p)
    vistos, unicos = set(), []
    for s in salida:
        if s not in vistos:
            vistos.add(s)
            unicos.append(s)
    return ", ".join(unicos)


def scope_css(texto):
    """Recorre el CSS contando llaves, para entrar en los @media."""
    res, i, n, buf = [], 0, len(texto), ""
    while i < n:
        if texto[i] == "{":
            prof, j = 1, i + 1
            while j < n and prof:
                if texto[j] == "{":
                    prof += 1
                elif texto[j] == "}":
                    prof -= 1
                j += 1
            cabeza, cuerpo = buf.strip(), texto[i + 1:j - 1]
            if cabeza.startswith("@media") or cabeza.startswith("@supports"):
                res.append("\n" + cabeza + " {" + scope_css(cuerpo) + "}\n")
            else:
                res.append("\n" + scope_sel(cabeza) + " {" + cuerpo.strip() + "}")
            buf, i = "", j
        else:
            buf += texto[i]
            i += 1
    if buf.strip():
        res.append(buf)
    return "".join(res)


# =====================================================================
#  2. Armado de la pagina
# =====================================================================
OVERRIDES = """
    /* ---------------------------------------------------------------
       Re-skin: el simulador entra al tablero con la paleta y la
       tipografia de Eco Go. Solo cambian colores, fuentes y bordes --
       la estructura y el comportamiento son los del prototipo.
       --------------------------------------------------------------- */
    .tir{
      --ink:var(--color-text); --muted:var(--color-text-muted);
      --teal:var(--eg-teal-dark); --dark:var(--eg-teal-dark);
      --paper:transparent; --white:var(--color-surface);
      --line:var(--color-border); --soft:rgba(60,151,148,.07);
      --loss:var(--eg-red); --gain:var(--eg-teal-dark);
      font-family:inherit; font-size:inherit;
    }
    .tir .shell{width:100%;margin-inline:0}
    .tir h1,.tir h2,.tir h3,.tir .return{font-family:inherit}
    .tir .return{font-weight:800;letter-spacing:-.025em}
    .tir .section-title,.tir .matrix h2{color:var(--eg-teal-dark);font-weight:800}
    .tir .eyebrow{color:var(--eg-teal)}
    .tir .mode-picker{background:var(--eg-gray-100);border-radius:20px;padding:3px}
    .tir .mode-picker span{border-radius:16px}
    .tir .mode-picker input:checked + span{background:var(--eg-teal-dark)}
    .tir .controls{border-radius:var(--radius) var(--radius) 0 0}
    .tir .workspace{border-radius:0 0 var(--radius) var(--radius)}
    .tir .table-scroll{border-radius:var(--radius)}
    .tir .button{border-radius:8px}
    .tir select,.tir .entry,.tir .scenario-input,.tir .rate-box{border-color:var(--color-border);border-radius:8px}
    .tir input[type="range"]{accent-color:var(--eg-teal)}
    .tir thead th{background:rgba(60,151,148,.07);color:var(--eg-teal-dark)}
    .tir thead th.active-rate{background:var(--color-primary-soft);color:var(--eg-teal-dark)}
    .tir tbody tr.selected th{background:var(--color-primary-soft);box-shadow:inset 3px 0 var(--eg-teal)}
    .tir tbody .rate-cell button[aria-pressed="true"]{box-shadow:inset 0 0 0 2px var(--eg-teal)}
    .tir .method{border-block-color:var(--color-border)}
    .tir summary{color:var(--eg-teal-dark)}

    /* el horizonte de salida viaja al encabezado del tablero */
    .tir-horizon{flex:none;padding-left:16px;border-left:3px solid var(--eg-teal);text-align:left}
    .tir-horizon span{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;
      color:var(--color-text-muted);font-weight:600}
    .tir-horizon time{display:block;font-weight:800;font-size:1.05rem;color:var(--eg-teal-dark)}

    /* aviso: toda la matriz cuelga del precio de compra */
    .tir-aviso{display:none;gap:10px;align-items:flex-start;background:rgba(254,139,95,.12);
      border:1px solid rgba(254,139,95,.45);border-left:4px solid var(--eg-orange);
      border-radius:var(--radius);padding:12px 16px;margin-bottom:18px;font-size:.84rem;line-height:1.45}
    .tir-aviso.visible{display:flex}
    .tir-aviso strong{color:#9c4a1f}
"""

# La paleta tambien vive adentro del canvas y de la matriz, que se dibujan por
# codigo: ahi los colores se cambian uno por uno.
RECOLOR = [
    ("rgba(44, 157, 113, ${strength})", "rgba(60, 151, 148, ${strength})"),   # ganancia
    ("rgba(180, 91, 77, ${strength})",  "rgba(218, 69, 49, ${strength})"),    # perdida
    ('"#4e6662"', '"#6E7679"'),          # rotulos de los ejes
    ('"#e0e7e2"', '"#E2E8E8"'),          # grilla
    ('"#91a9a0"', '"#B8BEC0"'),          # linea del cero
    ('"#89a69c"', '"#B8BEC0"'),          # eje
    ('"#006b62"', '"#1B5F5E"'),          # curva activa
    ('"#866124"', '"#FE8B5F"'),          # curva comparada
    ("12px 'Segoe UI', sans-serif", "12px 'HK Grotesk', system-ui, sans-serif"),
]

# Unico cambio de logica: el prototipo trae sus precios embebidos y sigue
# andando solo, pero si refresh.py dejo ruedas mas nuevas, mandan esas.
ANCLA = ('const { snapshots, bonds, defaultScenarios, exitDate } = '
         'JSON.parse(document.getElementById("market-data").textContent);')
INYECCION = """
    /* Ruedas que sumo refresh.py desde Rava, despues del prototipo. */
    if (window.TIR_SALIDA_PRECIOS_DATA && window.TIR_SALIDA_PRECIOS_DATA.snapshots) {
      Object.assign(snapshots, window.TIR_SALIDA_PRECIOS_DATA.snapshots);
    }"""

AVISO = """
  <script>
  /* El precio de compra de referencia tiene fecha. Si quedo viejo, toda la
     matriz lo esta -- y se ve igual de prolija. Por eso se avisa arriba. */
  (function(){
    try{
      var d = JSON.parse(document.getElementById('market-data').textContent);
      var extra = (window.TIR_SALIDA_PRECIOS_DATA || {}).snapshots || {};
      var fechas = Object.keys(d.snapshots || {}).concat(Object.keys(extra)).sort();
      if (!fechas.length) return;
      var ultima = fechas[fechas.length - 1];
      var dias = Math.round((Date.now() - new Date(ultima + 'T12:00:00')) / 86400000);
      if (dias < 21) return;
      var p = ultima.split('-');
      document.getElementById('tirAviso').innerHTML =
        '<span>&#9888;</span><span><strong>Precios al ' + p[2] + '/' + p[1] + '/' + p[0] + '</strong> (' +
        dias + ' d&iacute;as). Los retornos se calculan contra ese precio de compra: ' +
        'mientras no entre una rueda nueva, toda la matriz queda anclada ah&iacute;.</span>';
      document.getElementById('tirAviso').className = 'tir-aviso visible';
    }catch(e){}
  })();
  </script>
"""

CABECERA = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta name="description" content="Simulador de retornos de bonos argentinos en dolares segun la TIR o la paridad de salida."/>
  <title>TIR de salida &middot; Eco Go</title>
  <link rel="stylesheet" href="../assets/css/theme.css?v=%(v)s"/>
  <link rel="icon" type="image/jpeg" href="../assets/img/logo-ecogo.jpg"/>
  <style>
%(css)s
%(over)s
  </style>
</head>
<body data-depth="1" data-active-section="tir-salida">
  <div class="eg-app">
    <aside class="eg-sidebar" id="egSidebar"></aside>
    <header class="eg-header" id="egHeader"></header>
    <main class="eg-main">
      <section class="eg-page-header">
        <div>
          <h1 class="eg-page-header__title">TIR y paridad de salida</h1>
          <p class="eg-page-header__subtitle">Compar&aacute; el retorno total en d&oacute;lares de los bonos argentinos seg&uacute;n el precio de compra y el escenario de venta.</p>
        </div>
        <div class="tir-horizon"><span>Fecha de salida</span> <time datetime="%(salida)s">%(salida_txt)s</time></div>
      </section>

      <div class="tir-aviso" id="tirAviso"></div>

      <div class="tir">
%(body)s
      </div>

      <footer class="eg-footer">
        <span>TIR de salida &middot; Eco Go</span>
        <a href="../index-clientes.html">&larr; Volver al inicio</a>
      </footer>
    </main>
  </div>

  <script src="../assets/js/layout.js?v=%(v)s"></script>
  <script src="../assets/data/tir_salida_precios.js?v=%(v)s"></script>
"""


def main():
    if not os.path.exists(PROTO):
        raise SystemExit(f"No encontre el prototipo en {PROTO}")
    html = io.open(PROTO, encoding="utf-8").read()

    # ---- Las tres piezas que se copian tal cual ----
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    # del primer <section> del simulador hasta el cierre de la metodologia
    cuerpo = re.search(r'(<section aria-label="Simulador de bonos">.*?</details>)\s*</main>',
                       html, re.S).group(1)
    datos = re.search(r'(<script id="market-data".*?</script>)', html, re.S).group(1)
    logica = re.search(r'</script>\s*(<script>\s*"use strict";.*?</script>)', html, re.S).group(1)

    for viejo, nuevo in RECOLOR:
        if viejo not in logica:
            print(f"  aviso: no encontre {viejo!r} para recolorear")
        logica = logica.replace(viejo, nuevo)

    if ANCLA not in logica:
        raise SystemExit("El prototipo cambio: no encontre donde enganchar los precios del pipeline.")
    logica = logica.replace(ANCLA, ANCLA + INYECCION)

    cuerpo = cuerpo.replace("background:#ecd5d0", "background:rgba(218,69,49,.32)")
    cuerpo = cuerpo.replace("background:#cbe7da", "background:rgba(60,151,148,.38)")

    # ---- La fecha de salida sale del prototipo, no se escribe a mano ----
    salida = re.search(r'"exitDate":\s*"(\d{4}-\d{2}-\d{2})"', datos).group(1)
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    a, m, d = salida.split("-")
    salida_txt = f"{int(d)} de {meses[int(m) - 1]} de {a}"

    pagina = (CABECERA % {"v": V, "css": scope_css(css), "over": OVERRIDES,
                          "body": cuerpo, "salida": salida, "salida_txt": salida_txt}
              + datos + "\n" + logica + AVISO + "\n</body>\n</html>\n")
    io.open(DEST, "w", encoding="utf-8").write(pagina)
    print(f"OK  {DEST}  ({len(pagina):,} bytes) - salida {salida_txt}")


if __name__ == "__main__":
    main()
