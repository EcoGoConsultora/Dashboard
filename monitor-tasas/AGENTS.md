# Monitor de tasas Eco Go

Este repo produce datos para un HTML estático; el diseño de `site/template.html` lo mantiene Claude. En una actualización de mercado o revisión quincenal:

1. Confirmar la fecha de mercado de cada precio Rava y no usar un cierre anterior como si fuera actual.
2. Incorporar un ticker sólo después de verificar familia, emisión original, vencimiento y término financiero contra Secretaría de Finanzas o Boletín Oficial. Para BONCER verificar base CER original con BCRA; para hard dollar usar flujos contractuales completos, precio dirty y T+1.
3. Editar `config/market_instruments.json` o `config/tamar_instruments.json`, y cache de flujos si corresponde. No deducir TEM, base CER ni márgenes del nombre del ticker.
4. Ejecutar `py -3.14 -m unittest discover -s tests -v` y `py -3.14 -m src.monitor --date YYYY-MM-DD` para la última rueda cerrada. Revisar `output/latest.json` y `quality.warnings`.
5. Mantener el contrato JSON y los marcadores de `site/template.html` (`__MONITOR_DATA_JSON__` y `__MONITOR_HISTORY_JSON__`); si cambia el esquema, coordinarlo con el frontend. No sobrescribir el HTML diseñado por Claude.

La tarea de Windows `EcoGo Monitor Tasas Diario` corre a las 17:30 desde esta carpeta de OneDrive (instalada el 2026-09-24; si el repo se mueve, reinstalarla desde la nueva ubicación con `scripts/install_daily_task.ps1 -ReplaceExisting`). La misma tarea está instalada en la notebook de casa (ver `INSTALAR_EN_NOTEBOOK.md`); las dos PCs comparten esta carpeta por OneDrive y `run_daily.ps1` no rehace una rueda ya publicada. El HTML publicado es `index.html` en la raíz. El monitor quincenal de Codex opera sobre esta misma carpeta, sólo desde la PC de la oficina. La copia anterior en `G:\Mi unidad\Eco Go\Mercados\Monitor tasas` quedó sólo como respaldo.
