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
