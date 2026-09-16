from __future__ import annotations


MONETARY_VARIABLE_WINDOW_MONTHS = 24
MONETARY_VARIABLE_UNIT = "ARS mn"
MONETARY_USD_UNIT = "USD mn"
MONETARY_RATE_UNIT = "TNA %"

MONETARY_CORE_SPECS = [
    {
        "metric": "base_monetaria",
        "label": "Base monetaria",
        "source_id": 15,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "circulacion_monetaria",
        "label": "Circulacion monetaria",
        "source_id": 16,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "m2_privado",
        "label": "M2 privado",
        "source_id": 1239,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "pases_pasivos_bcra",
        "label": "Pases pasivos BCRA",
        "source_id": 152,
        "unit": MONETARY_VARIABLE_UNIT,
    },
]

MONETARY_COMPOSITION_SPECS = [
    {
        "metric": "m2_total",
        "label": "M2",
        "source_id": 109,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "m3_total",
        "label": "M3",
        "source_id": 1234,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "depositos_vista_privado",
        "label": "Depositos a la vista",
        "source_id": 1241,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "depositos_plazo_privado",
        "label": "Depositos a plazo",
        "source_id": 1242,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "depositos_privados_ars",
        "label": "Depositos en pesos",
        "source_id": 104,
        "unit": MONETARY_VARIABLE_UNIT,
    },
    {
        "metric": "depositos_privados_usd",
        "label": "Depositos en dolares",
        "source_id": 108,
        "unit": MONETARY_USD_UNIT,
    },
]

MONETARY_VARIABLE_SPECS = MONETARY_CORE_SPECS + [
    spec
    for spec in MONETARY_COMPOSITION_SPECS
    if spec["metric"] not in {item["metric"] for item in MONETARY_CORE_SPECS}
]

MONETARY_VARIABLE_METRICS = [spec["metric"] for spec in MONETARY_VARIABLE_SPECS]
MONETARY_CORE_METRICS = [spec["metric"] for spec in MONETARY_CORE_SPECS]
MONETARY_VARIABLE_LABELS = {spec["metric"]: spec["label"] for spec in MONETARY_VARIABLE_SPECS}
MONETARY_VARIABLE_SOURCE_IDS = {spec["metric"]: int(spec["source_id"]) for spec in MONETARY_VARIABLE_SPECS}
MONETARY_VARIABLE_UNITS = {spec["metric"]: spec["unit"] for spec in MONETARY_VARIABLE_SPECS}

MONETARY_BLOCK_WINDOWS = {
    "core_latest": 3,
    "economy_pib_history": 45,
    "peso_usd_pib_history": 45,
    "usd_stocks_history": 45,
    "rates_tna": 5,
}

MONETARY_VARIABLE_RAW_COLUMNS = [
    "date",
    "metric",
    "label",
    "value",
    "source_id",
    "unit",
]

MONETARY_VARIABLE_CORE_LATEST_COLUMNS = [
    "metric",
    "label",
    "date",
    "value",
    "unit",
    "source_id",
    "change_30d_pct",
    "change_yoy_pct",
    "lag_days",
]

MONETARY_ECONOMY_PIB_HISTORY_COLUMNS = [
    "month",
    "month_label",
    "circulacion_pct_pib",
    "depositos_vista_pct_pib",
    "depositos_plazo_pct_pib",
    "m2_pct_pib",
    "m3_pct_pib",
]

MONETARY_PESO_USD_PIB_HISTORY_COLUMNS = [
    "month",
    "month_label",
    "circulacion_pct_pib",
    "depositos_pesos_pct_pib",
    "depositos_usd_pct_pib",
    "total_pct_pib",
]

MONETARY_USD_STOCKS_HISTORY_COLUMNS = [
    "month",
    "month_label",
    "m2_usd_mn",
    "depositos_pesos_usd_mn",
    "depositos_usd_mn",
    "total_usd_mn",
]

MONETARY_BLOCK_FRESHNESS_COLUMNS = [
    "block",
    "label",
    "latest_date",
    "window_days",
    "lag_days",
]

MONETARY_SOURCE_TABLE_COLUMNS = [
    "series_key",
    "label",
    "date",
    "value",
    "unit",
    "lag_days",
]

MONETARY_RATES_TNA_SPECS = [
    {
        "metric": "badlar_privados",
        "label": "BADLAR privados",
        "source_id": 139,
        "unit": MONETARY_RATE_UNIT,
    },
    {
        "metric": "tm20_privados",
        "label": "TM20 privados",
        "source_id": 143,
        "unit": MONETARY_RATE_UNIT,
    },
    {
        "metric": "plazo_fijo_30d",
        "label": "Plazo fijo 30d",
        "source_id": 1207,
        "unit": MONETARY_RATE_UNIT,
    },
    {
        "metric": "plazo_fijo_pesos",
        "label": "Plazo fijo pesos",
        "source_id": 1189,
        "unit": MONETARY_RATE_UNIT,
    },
    {
        "metric": "tasa_politica",
        "label": "Tasa de politica monetaria",
        "source_id": 160,
        "unit": MONETARY_RATE_UNIT,
    },
]

MONETARY_RATES_TNA_METRICS = [spec["metric"] for spec in MONETARY_RATES_TNA_SPECS]
MONETARY_RATES_TNA_LABELS = {spec["metric"]: spec["label"] for spec in MONETARY_RATES_TNA_SPECS}
MONETARY_RATES_TNA_SOURCE_IDS = {spec["metric"]: int(spec["source_id"]) for spec in MONETARY_RATES_TNA_SPECS}

MONETARY_RATES_TNA_RAW_COLUMNS = MONETARY_VARIABLE_RAW_COLUMNS.copy()

MONETARY_RATES_TNA_SERIES_COLUMNS = [
    "date",
    "metric",
    "label",
    "value",
]

MONETARY_RATES_TNA_REFERENCE_COLUMNS = [
    "date",
    "metric",
    "label",
    "value",
    "source_type",
]

MONETARY_RATES_TNA_LATEST_COLUMNS = [
    "metric",
    "label",
    "date",
    "value",
    "lag_days",
    "spread_vs_reference_pct",
]
