# Encargo de HTML estático para Claude

Diseñar el monitor Eco Go en `site/template.html`. Este repositorio ya produce `output/latest.json`; no implementar scraping ni cálculos financieros en el navegador.

Poner exactamente una vez el marcador `__MONITOR_DATA_JSON__` en una expresión JavaScript, por ejemplo:

```html
<script>
const monitorData = __MONITOR_DATA_JSON__;
// Renderizar a partir de monitorData.
</script>
```

La corrida diaria sustituye el marcador y escribe `index.html` en la raíz del proyecto, autónomo para abrir desde el disco. Los grupos están en `monitorData.curves.fixed`, `cer`, `tamar`, `dollar_linked` y `hard_dollar`. Las tasas a un día y bancarias están en `monitorData.money_market`. Todos los valores de tasas usan porcentaje, con la convención en el nombre del campo (`tea`, `tna`, `tem`).

Mostrar siempre `meta.market_date`, `meta.generated_at`, `meta.status` y `quality.warnings`. Cada tasa BCRA tiene su propia `date`, que puede rezagarse uno o dos días respecto de la rueda. Un instrumento ausente por precio viejo no debe aparecer como cotización de hoy; mostrar su símbolo y causa desde `quality.rava_errors` si se desea informar cobertura. Para TAMAR, indicar que la TIR depende de una proyección de fijaciones futuras. Para CER, `real_yield_tea_pct` es una aproximación con CER de liquidación; `nominal_yield_tea_pct_if_known` sólo aparece cuando la fijación contractual ya se publicó. Para dólar linked, la TEA en USD equivalentes usa la A3500 vigente y no proyecta el tipo de cambio futuro. Para hard dollar, el precio es dirty.

No usar `fetch()` de un archivo hermano: el navegador puede bloquearlo bajo `file://`. El JSON se inserta en el HTML al generar el archivo final.

Para comparar contra fechas previas, la plantilla declara `var monitorHistory = __MONITOR_HISTORY_JSON__;` (a lo sumo una vez). Trae las ruedas de `output/history` anteriores a la del día, con los mismos nombres de campo que `curves` y `money_market` pero sólo identificadores, rendimientos, duración y precio.


## Ampliación de datos 05/11/2026 — contrato 1.1

Los campos previos se conservan. Se agregan `curves.dual` y `volumes`. Este cambio no modifica `site/template.html`.

### Volumen

Cada nodo conserva `volume_nominal` y suma `market_date`, `nominal_currency`, `trading_currency` y `turnover_at_close_estimate`. Este último es **VN negociado × precio de cierre / 100**: es una estimación, no el monto efectivo operado durante la rueda. La moneda de esa estimación es `trading_currency`. `null` significa desconocido; cero significa cero informado.

`volumes.instruments` tiene una fila por especie. `volumes.by_type` agrega por familia y `volumes.by_curve_group` por curva. Ambas listas separan moneda nominal y moneda de negociación: nunca sumar VN ARS y VN USD, ni montos ARS y USD. En `dual` hay dos monedas nominales. Los totales sólo cubren las especies con precio de fecha y métricas en el monitor, no todo el mercado. Cada agregado informa `instrument_count`, `volume_observed_count`, `turnover_observed_count`, `missing_volume_symbols`; los totales pueden ser parciales. `volumes.missing_price_symbols` enumera especies esperadas sin nodo y `missing_volume_symbols` las de volumen desconocido. REPO/SIMU/caución conservan sus montos efectivos separados en `money_market.*.volume_ars` y no se suman a los bonos.

El histórico compacto incorpora volumen, monedas, estimación de monto y métricas por pata en los snapshots que los contienen. No rellenar campos ausentes de snapshots antiguos con cero. El histórico de duales se reconstruyó para las ruedas guardadas desde el 02/01/2026, desde la emisión de cada especie y sólo cuando Rava tiene cierre exacto. Incluye TTM26, TTJ26 y TTS26 para sus períodos previos al vencimiento.

### Duales y curvas comparables

| Familia | Especies | Campo para cada curva |
| --- | --- | --- |
| `DUAL_FIXED_TAMAR` | TTD26 | Fija: `fixed_yield_tea_pct` / `fixed_modified_duration_years`; nominal condicional del dual: `yield_tea_pct` / `modified_duration_years` |
| `DUAL_CER_TAMAR` | TXMJ8, TXMD8, TXMJ9, TXMD9, TXMJ0 | CER: `real_yield_tea_pct` / `cer_modified_duration_years` |
| `DUAL_TAMAR_DOLLAR_LINKED` | TMVE8 | Dólar linked: `usd_equivalent_yield_tea_pct` / `dollar_linked_modified_duration_years` |
| Todas | Las siete especies | TAMAR: `tamar_yield_tea_pct` / `tamar_modified_duration_years`; TEM: `tamar_yield_tem_pct` |

Mantener duales identificados como tales en los overlays. No duplicarlos para sumar volumen: `volumes` ya los cuenta una sola vez. No mezclar TIR real, nominal y equivalente USD en el mismo eje sin aclaración. `tamar_yield_tea_pct` es nominal y usa las últimas cinco fijaciones BCRA publicadas para proyectar las futuras; no es un spread sobre TAMAR ni un forward observado.

TTD26 paga el máximo entre fija TEM 2,14% y TAMAR. Para ese bono `yield_tea_pct` usa el mayor pago bajo la proyección TAMAR y `selected_leg` identifica la pata seleccionada en ese escenario. Los CER/TAMAR tienen margen TNA de 3 puntos en la fórmula contractual TAMAR; TMVE8 no tiene margen y su pata TAMAR parte del A3500 inicial de emisión, no del actual.

En CER/TAMAR y TAMAR/dólar linked, `yield_tea_pct`, `yield_tem_pct`, `modified_duration_years`, `terminal_value_per_vn100` y `selected_leg` quedan `null` mientras el otro pago no se conozca. Sin una trayectoria de inflación/dólar no existe una TIR nominal única determinada. `projected_nominal_floor_yield_tea_pct` es el rendimiento de la pata TAMAR bajo su escenario: el pago dual será al menos esa pata **si se cumple ese escenario**. No mostrarlo como TIR total del dual.

Se incluyen precios técnicos y paridades por pata (`fixed_*`, `cer_*`, `tamar_*`, `dollar_linked_*`), pagos de cada pata cuando son calculables y las fechas de referencia/fijación. Las TIR CER y dólar linked son las mismas aproximaciones de normalización que usan las curvas puras: no proyectan inflación ni devaluación. Las duraciones mantienen fijo el flujo proyectado: no representan duración efectiva de una opción ni sensibilidad total ante cambios de TAMAR/CER/FX. `option_valuation = not_estimated`.

Umbrales condicionales de empate entre pagos: `cer_switch_index`, `cer_switch_monthly_pct`, `fx_switch_ars_per_usd`, `fx_switch_monthly_pct`, `tamar_switch_average_tna_pct` y `tamar_switch_future_tna_pct`. Las tasas mensuales de CER/FX expresan crecimiento compuesto de 30 días desde la referencia hasta la fijación objetivo; no son proyecciones ni inflación IPC exacta. El umbral de TAMAR futura puede quedar negativo cuando la historia acumulada ya favorece TAMAR.

Los marcadores `__MONITOR_DATA_JSON__` y `__MONITOR_HISTORY_JSON__` siguen con su contrato anterior. La extensión de esquema es aditiva.

### Volumen diario en el HTML (Claude, 05/11/2026)

Cada pestaña de curva muestra debajo del gráfico la evolución diaria del monto estimado, con filtro por familia, período y apilado por especie (las cinco mayores más "Otras"). Para las ruedas guardadas antes del contrato 1.1, `_history_for_html` deriva `turnover_at_close_estimate` con `src.common.volumes.turnover_estimate`, la misma fórmula de la corrida diaria; los snapshots en disco no se modifican. El volumen de fechas viejas está subestimado porque sólo cuenta especies del registro. La sección "Volumen de la rueda" se reemplazó por este bloque.


### Historia reconstruida de duales

`output/history` ahora contiene duales desde el inicio del histórico del monitor (02/01/2026), sujeto al cierre de cada fecha y a la emisión/vencimiento de cada especie. La serie de TTD26 empieza en enero; los CER/TAMAR y TMVE8 empiezan desde sus emisiones de 2026. TTM26, TTJ26 y TTS26 completan el universo de duales ya vencidos. No arrastrar el último precio si una especie no tiene cierre de esa rueda.

`meta.dual_history_backfill` identifica la incorporación reconstruida aunque el snapshot original haya sido diario (`meta.backfill = false`). En el histórico compacto para el HTML el indicador es `dual_backfill`. Cada nodo reconstruido también tiene `historical_reconstruction = true` y la política de datos BCRA. Las otras curvas, tasas y metadatos originales se conservan.

Las fijaciones TAMAR y A3500 se cortan por fecha efectiva para cada rueda; cuando existe un registro crudo de una corrida diaria, se respeta su última fecha TAMAR observada. Se usa la serie oficial BCRA disponible actualmente: no es un archivo de versiones históricas de publicación y no garantiza reproducir correcciones posteriores ni el horario de disponibilidad de cada dato. No entran fijaciones TAMAR posteriores ni CER realizados futuros al cálculo histórico. La proyección TAMAR se recalcula para cada rueda, no se aplica la actual a toda la historia. Las bases CER y A3500 iniciales contractuales no cambian.


Cobertura al 05/11: 1.142 nodos duales, en 204 ruedas entre 02/01 y 04/11/2026. Hay dos ruedas sin cierres duales en Rava (13/01 y 02/03); no convertir esos vacíos en ceros ni repetir el precio anterior. El informe de cobertura por especie está en `docs/revisions/2026-11-05-dual-history.json`.
