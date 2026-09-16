# Pipeline local de Mercados

Este directorio contiene el núcleo de datos del antiguo repositorio
`Markets-dashboard`, separado de su web, Streamlit, PDF semanal y despliegue.

`run_dashboard_export.py` ejecuta la secuencia `ingest -> transform -> export`
y escribe `output/dashboard_payload.json`. `refresh.py` toma de ese payload
las claves que necesitan `pages/mercados.html` y
`pages/mercados-global.html` y genera `assets/data/mercados.js`.

Las fuentes configuradas incluyen BCRA, Ámbito, ArgentinaDatos, IOL, BYMA,
Yahoo Finance y FRED. Los archivos de `data/raw`, `data/processed` y `output`
son cachés regenerables: no se versionan, pero permiten recuperar una última
lectura válida si alguna fuente de mercado falla temporalmente.
