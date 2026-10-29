# Monitor de tasas Eco Go — feed de datos

Este repositorio descarga datos de mercado y produce `output/latest.json` para un HTML estático. **No genera el HTML.** La fecha de mercado es explícita; ninguna cotización vieja se renombra como cierre nuevo.

## Correr

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 -m src.monitor --date 2026-09-23
```

Sin `--date` usa la fecha local de Buenos Aires. `scripts/run_daily.ps1` (la tarea de las 17:30) procesa siempre la última rueda cerrada: antes de las 17:00, o en fin de semana o feriado, toma la rueda hábil anterior. Si esa rueda no es la de hoy (la tarea corrió tarde porque la PC estaba apagada), la valúa con el cierre histórico de Rava vía `src.backfill --publish`, y después completa las ruedas de las últimas dos semanas que falten en `output/history`. Una corrida sin ninguna cotización de la fecha falla y no reemplaza el monitor publicado. Si la rueda ya fue publicada (por ejemplo, por la otra PC que comparte la carpeta de OneDrive), no se rehace salvo con `-Force`. Para instalar la tarea en otra máquina, ver `INSTALAR_EN_NOTEBOOK.md`. Caución, REPO y SIMU toman el plazo hasta la próxima rueda hábil (3 días un viernes); las series conservan los nombres `*_1d` y `tenor_days` informa el plazo. La tarea de Windows en `scripts/install_daily_task.ps1` ejecuta el pipeline a las 17:30. Está instalada desde esta carpeta de OneDrive; si el repo cambia de lugar, ejecutar `scripts/install_daily_task.ps1 -ReplaceExisting` desde la nueva ubicación. La tarea usa la sesión interactiva del usuario, así que corre sólo con la sesión iniciada; conviene marcar la carpeta como "Mantener siempre en este dispositivo" en OneDrive.

## Fuentes y métricas

| Grupo | Fuente | Métrica principal |
| --- | --- | --- |
| LECAP/BONCAP | Precio y volumen Rava; condiciones en `config/market_instruments.json` | TIR TEA/TEM, paridad, duración modificada. TEM de emisión con 30/360. |
| LECER/BONCER cero cupón | Rava, CER BCRA, base original en registro | TIR real TEA aproximada con CER de liquidación; TIR nominal contractual cuando ya se publicó el CER aplicable al vencimiento (diez días hábiles previos). No se incluyen bonos CER con cupones sin flujos contractuales. |
| TAMAR puro | Rava, TAMAR bancos privados BCRA variable 44, calendario bancario | TIR condicional a proyección de fijaciones futuras: media simple de últimas cinco. |
| Dólar linked cero cupón | Rava, A3500 BCRA variable 5 | Rendimiento TEA en USD equivalentes con tipo de cambio actual. No es una proyección de devaluación. |
| Hard dollar | Rava y flujos contractuales cacheados | TIR TEA sobre precio dirty, duración y paridad; T+1. |
| REPO, SIMU y caución a 1 día | A3 Market Data público | TNA promedio ponderada por volumen (VWAP), última tasa y volumen. Se separa `REPO` de `REPX`. |
| TAMAR y activa bancaria | BCRA variables 44 y 145 | Último dato publicado con su fecha efectiva. La activa corresponde a adelantos a empresas de 1 a 7 días y $10 millones o más. |

## Archivos

- `output/latest.json`: contrato de datos para Claude. Las tasas llevan sufijos `_pct`, con TEA/TNA/TEM en el nombre.
- `output/history/YYYY-MM-DD.json`: snapshot por fecha de mercado; una nueva corrida de la misma fecha lo reemplaza.
  Los snapshots reconstruidos con `src.backfill` llevan `meta.backfill = true`.
- `data/raw/YYYY-MM-DD/`: respuestas y cotizaciones utilizadas en cada corrida.
- `data/reference/`: flujos hard dollar cacheados; no actualizar automáticamente sin auditar términos.
- `data/history/hard_dollar_prices.csv`: histórico de cotizaciones por fecha.
- `config/market_instruments.json`: registro versionado de tickers, condiciones y fuentes.
- `config/tamar_instruments.json`: registro TAMAR puro del repo Curva TAMAR.

El campo `meta.status` es `partial` cuando faltan series A3 o cotizaciones de instrumentos vigentes; `quality` explica qué faltó. El frontend debe mostrar la fecha de mercado y la fecha propia de cada tasa BCRA. El archivo se escribe atómicamente, por lo que el HTML no leerá JSON incompleto.

## Entrega al HTML de Claude

Claude puede crear `site/template.html` con el marcador `__MONITOR_DATA_JSON__` **una sola vez**, por ejemplo en JavaScript como `const monitorData = __MONITOR_DATA_JSON__;`. El pipeline insertará el JSON diario y publicará `index.html` en la raíz del proyecto, un archivo autónomo que se abre desde `file://` sin servidor. El pipeline sólo completa ese marcador; diseño e interacción quedan en la plantilla de Claude. No conviene usar `fetch('output/latest.json')` desde un HTML local porque los navegadores suelen bloquear lecturas `file://` cruzadas.

La plantilla puede tener además, a lo sumo una vez, `__MONITOR_HISTORY_JSON__`. El pipeline lo reemplaza por `{"dates": [...], "snapshots": {fecha: {"backfill", "curves", "money_market"}}}` con las ruedas de `output/history` anteriores a la del día (hasta 400 días), reducidas a identificadores, rendimientos, duración y precio. El HTML lo usa para comparar curvas contra una fecha previa.

## Exportar series a Excel

Para pasar las series diarias de rendimientos CER, TAMAR y dólar linked:

```powershell
py -3.14 -m src.export_series
```

Escribe `output/exports/Series_CER_TAMAR_DL_<última rueda>.xlsx` con la marca Eco Go: una hoja por familia (fechas en filas, especies ordenadas por vencimiento en columnas, más la TAMAR BCRA y la A3500), una hoja `Datos` en formato largo y una de notas metodológicas. Lee `output/history` sin recalcular nada. En las hojas por familia omite las especies con menos de 30 días al vencimiento (`--min-days`), porque la TIR anualizada se dispara; `Datos` las conserva. `--start`/`--end` acotan el período y `--out` cambia el destino.

## Historia para comparar

La corrida diaria agrega su snapshot a `output/history`. Para reconstruir ruedas anteriores con los cierres diarios que publica Rava (cerca de un año por especie), A3 y BCRA:

```powershell
py -3.14 -m src.backfill --start 2026-01-02 --end 2026-09-22
```

Cada fecha pasa por la misma valuación que la corrida diaria, con el cierre exacto de esa fecha, y se escribe sólo en `output/history` (no toca `latest.json` ni el HTML). No reemplaza snapshots de corridas diarias salvo con `--force`. El relleno usa el registro vigente: incluye las especies vencidas que siguen cargadas, pero no las que nunca se registraron. Las de `UNVERIFIED_TERMS` en `src/backfill.py` (condiciones heredadas que no cierran con los precios) se excluyen de los snapshots reconstruidos hasta verificarlas. A3 no sirve REPO/caución anterior a unos siete meses: esas fechas quedan sólo con curvas y tasas BCRA.

## Mantenimiento

Los vencidos se filtran automáticamente. Las nuevas especies requieren verificación de ticker, tipo, fecha de emisión original, vencimiento, TEM/base CER/margen TAMAR o flujos. La revisión quincenal debe comparar el universo público de BYMA, A3 y Rava con este registro, confirmar términos en Secretaría de Finanzas/Boletín Oficial, y recién entonces modificar configuración y ejecutar una corrida de control. Ver `docs/provenance.md`.

El calendario de liquidación cargado llega a 2026. Antes del primer cierre de 2027 se debe incorporar el calendario oficial de 2027. La curva TAMAR usa feriados BCRA y marca los años estimados cuando no hay tabla oficial.
