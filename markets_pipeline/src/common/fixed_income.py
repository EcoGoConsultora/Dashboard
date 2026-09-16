from __future__ import annotations

from pathlib import Path

import pandas as pd


DEFAULT_IOL_INSTRUMENTS_DROP_PATH = Path("Instrumentos.xlsx")
DEFAULT_IOL_INSTRUMENTS_METADATA_PATH = Path("legacy/iol_reference/Instrumentos.xlsx")

CER_BOND_COLUMNS = [
    "symbol",
    "source_symbol",
    "cer_base_index",
    "capitalization_coefficient",
    "maturity_date",
    "target_lag_business_days",
]
CER_PAIR_COLUMNS = [
    "pair_label",
    "fixed_symbol",
    "cer_symbol",
]
HARD_DOLLAR_BOND_COLUMNS = [
    "symbol",
    "source_symbol",
    "family",
    "issue_date",
    "maturity_date",
    "currency",
    "price_basis",
    "coupon_day_count_basis",
    "settlement_lag_business_days",
    "schedule_source",
    "schedule_source_url",
]


_CER_BOND_ROWS = [
    {"symbol": "TX26", "source_symbol": "TX26", "cer_base_index": 22.54395985093912, "capitalization_coefficient": 1.0, "maturity_date": "2026-11-09", "target_lag_business_days": 10},
    {"symbol": "TX28", "source_symbol": "TX28", "cer_base_index": 22.54395985093912, "capitalization_coefficient": 1.0, "maturity_date": "2028-11-09", "target_lag_business_days": 10},
    {"symbol": "TX31", "source_symbol": "TX31", "cer_base_index": 46.91286021393639, "capitalization_coefficient": 1.0, "maturity_date": "2031-11-30", "target_lag_business_days": 10},
    {"symbol": "DIPO", "source_symbol": "DIP0", "cer_base_index": 1.4550634181245061, "capitalization_coefficient": 1.2699357, "maturity_date": "2033-12-31", "target_lag_business_days": 10},
    {"symbol": "DICP", "source_symbol": "DICP", "cer_base_index": 1.4550634181245061, "capitalization_coefficient": 1.2699357, "maturity_date": "2033-12-31", "target_lag_business_days": 10},
    {"symbol": "TZXD5", "source_symbol": "TZXD5", "cer_base_index": 271.05, "capitalization_coefficient": 1.0, "maturity_date": "2025-12-15", "target_lag_business_days": 10},
    {"symbol": "TZXM6", "source_symbol": "TZXM6", "cer_base_index": 337.03, "capitalization_coefficient": 1.0, "maturity_date": "2026-03-31", "target_lag_business_days": 10},
    {"symbol": "TZXD6", "source_symbol": "TZXD6", "cer_base_index": 271.05, "capitalization_coefficient": 1.0, "maturity_date": "2026-12-15", "target_lag_business_days": 10},
    {"symbol": "TZX26", "source_symbol": "TZX26", "cer_base_index": 200.39, "capitalization_coefficient": 1.0, "maturity_date": "2026-06-30", "target_lag_business_days": 10},
    {"symbol": "X15Y6", "source_symbol": "X15Y6", "cer_base_index": 701.61, "capitalization_coefficient": 1.0, "maturity_date": "2026-05-15", "target_lag_business_days": 10},
    {"symbol": "X29Y6", "source_symbol": "X29Y6", "cer_base_index": 651.90, "capitalization_coefficient": 1.0, "maturity_date": "2026-05-29", "target_lag_business_days": 10},
    {"symbol": "X31L6", "source_symbol": "X31L6", "cer_base_index": 685.55, "capitalization_coefficient": 1.0, "maturity_date": "2026-07-31", "target_lag_business_days": 10},
    {"symbol": "X30S6", "source_symbol": "X30S6", "cer_base_index": 714.98, "capitalization_coefficient": 1.0, "maturity_date": "2026-09-30", "target_lag_business_days": 10},
    {"symbol": "TZXO6", "source_symbol": "TZXO6", "cer_base_index": 480.15, "capitalization_coefficient": 1.0, "maturity_date": "2026-10-30", "target_lag_business_days": 10},
    {"symbol": "X30N6", "source_symbol": "X30N6", "cer_base_index": 659.68, "capitalization_coefficient": 1.0, "maturity_date": "2026-11-30", "target_lag_business_days": 10},
    {"symbol": "TZXA7", "source_symbol": "TZXA7", "cer_base_index": 651.90, "capitalization_coefficient": 1.0, "maturity_date": "2027-04-30", "target_lag_business_days": 10},
    {"symbol": "TZXY7", "source_symbol": "TZXY7", "cer_base_index": 659.68, "capitalization_coefficient": 1.0, "maturity_date": "2027-05-31", "target_lag_business_days": 10},
    {"symbol": "TZX27", "source_symbol": "TZX27", "cer_base_index": 200.39, "capitalization_coefficient": 1.0, "maturity_date": "2027-06-30", "target_lag_business_days": 10},
    {"symbol": "TZXD7", "source_symbol": "TZXD7", "cer_base_index": 271.05, "capitalization_coefficient": 1.0, "maturity_date": "2027-12-15", "target_lag_business_days": 10},
    {"symbol": "TZXM7", "source_symbol": "TZXM7", "cer_base_index": 361.32, "capitalization_coefficient": 1.0, "maturity_date": "2027-03-31", "target_lag_business_days": 10},
    {"symbol": "TZX28", "source_symbol": "TZX28", "cer_base_index": 200.39, "capitalization_coefficient": 1.0, "maturity_date": "2028-06-30", "target_lag_business_days": 10},
]

_CER_PAIR_ROWS = [
    {"pair_label": "T15D5 - TZXD5", "fixed_symbol": "T15D5", "cer_symbol": "TZXD5"},
    {"pair_label": "S17A6 - TZXM6", "fixed_symbol": "S17A6", "cer_symbol": "TZXM6"},
    {"pair_label": "S15Y6 - X15Y6", "fixed_symbol": "S15Y6", "cer_symbol": "X15Y6"},
    {"pair_label": "S29Y6 - X29Y6", "fixed_symbol": "S29Y6", "cer_symbol": "X29Y6"},
    {"pair_label": "T30J6 - TZX26", "fixed_symbol": "T30J6", "cer_symbol": "TZX26"},
    {"pair_label": "S31L6 - X31L6", "fixed_symbol": "S31L6", "cer_symbol": "X31L6"},
    {"pair_label": "S30S6 - X30S6", "fixed_symbol": "S30S6", "cer_symbol": "X30S6"},
    {"pair_label": "S30O6 - TZXO6", "fixed_symbol": "S30O6", "cer_symbol": "TZXO6"},
    {"pair_label": "S30N6 - X30N6", "fixed_symbol": "S30N6", "cer_symbol": "X30N6"},
    {"pair_label": "T30A7 - TZXM7", "fixed_symbol": "T30A7", "cer_symbol": "TZXM7"},
]
_HARD_DOLLAR_BOND_ROWS = [
    {
        "symbol": "AL29D",
        "source_symbol": "AL29D",
        "family": "A",
        "issue_date": "2020-09-04",
        "maturity_date": "2029-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AL29D",
    },
    {
        "symbol": "AN29D",
        "source_symbol": "AN29D",
        "family": "A",
        "issue_date": "2025-12-12",
        "maturity_date": "2029-11-30",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "bonistas_next_data",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AN29D",
    },
    {
        "symbol": "AL30D",
        "source_symbol": "AL30D",
        "family": "A",
        "issue_date": "2020-09-04",
        "maturity_date": "2030-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AL30D",
    },
    {
        "symbol": "AO27D",
        "source_symbol": "AO27D",
        "family": "A",
        "issue_date": "2026-02-27",
        "maturity_date": "2027-10-29",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "bonistas_next_data",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AO27D",
    },
    {
        "symbol": "AO28D",
        "source_symbol": "AO28D",
        "family": "A",
        "issue_date": "2026-03-31",
        "maturity_date": "2028-10-31",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "manual_monthly_coupon_6pct",
        "schedule_source_url": "https://iol.invertironline.com/titulo/cotizacion/BCBA/AO28D/",
    },
    {
        "symbol": "AL35D",
        "source_symbol": "AL35D",
        "family": "A",
        "issue_date": "2020-09-04",
        "maturity_date": "2035-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AL35D",
    },
    {
        "symbol": "AE38D",
        "source_symbol": "AE38D",
        "family": "A",
        "issue_date": "2020-09-04",
        "maturity_date": "2038-01-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AE38D",
    },
    {
        "symbol": "AL41D",
        "source_symbol": "AL41D",
        "family": "A",
        "issue_date": "2020-09-04",
        "maturity_date": "2041-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/AL41D",
    },
    {
        "symbol": "GD29D",
        "source_symbol": "GD29D",
        "family": "G",
        "issue_date": "2020-09-04",
        "maturity_date": "2029-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/GD29D",
    },
    {
        "symbol": "GD30D",
        "source_symbol": "GD30D",
        "family": "G",
        "issue_date": "2020-09-04",
        "maturity_date": "2030-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/GD30D",
    },
    {
        "symbol": "GD35D",
        "source_symbol": "GD35D",
        "family": "G",
        "issue_date": "2020-09-04",
        "maturity_date": "2035-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/GD35D",
    },
    {
        "symbol": "GD38D",
        "source_symbol": "GD38D",
        "family": "G",
        "issue_date": "2020-09-04",
        "maturity_date": "2038-01-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/GD38D",
    },
    {
        "symbol": "GD41D",
        "source_symbol": "GD41D",
        "family": "G",
        "issue_date": "2020-09-04",
        "maturity_date": "2041-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/GD41D",
    },
    {
        "symbol": "GD46D",
        "source_symbol": "GD46D",
        "family": "G",
        "issue_date": "2020-09-04",
        "maturity_date": "2046-07-09",
        "currency": "USD",
        "price_basis": "dirty",
        "coupon_day_count_basis": "30/360",
        "settlement_lag_business_days": 1,
        "schedule_source": "official_terms + bonistas_flow",
        "schedule_source_url": "https://bonistas.com/bono-cotizacion-rendimiento-precio-hoy/GD46D",
    },
]


def cer_bond_metadata_frame() -> pd.DataFrame:
    frame = pd.DataFrame(_CER_BOND_ROWS, columns=CER_BOND_COLUMNS).copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["source_symbol"] = frame["source_symbol"].astype(str).str.strip().str.upper()
    frame["cer_base_index"] = pd.to_numeric(frame["cer_base_index"], errors="coerce")
    frame["capitalization_coefficient"] = pd.to_numeric(frame["capitalization_coefficient"], errors="coerce").fillna(1.0)
    frame["maturity_date"] = pd.to_datetime(frame["maturity_date"], errors="coerce").dt.normalize()
    frame["target_lag_business_days"] = pd.to_numeric(frame["target_lag_business_days"], errors="coerce").astype("Int64")
    return frame.dropna(
        subset=["symbol", "source_symbol", "cer_base_index", "capitalization_coefficient", "maturity_date", "target_lag_business_days"]
    ).reset_index(drop=True)


def cer_pair_specs_frame() -> pd.DataFrame:
    frame = pd.DataFrame(_CER_PAIR_ROWS, columns=CER_PAIR_COLUMNS).copy()
    for column in ("pair_label", "fixed_symbol", "cer_symbol"):
        frame[column] = frame[column].astype(str).str.strip().str.upper()
    return frame.drop_duplicates(subset=["pair_label"], keep="last").reset_index(drop=True)


def cer_bond_symbols() -> list[str]:
    return cer_bond_metadata_frame()["symbol"].tolist()


def hard_dollar_metadata_frame() -> pd.DataFrame:
    frame = pd.DataFrame(_HARD_DOLLAR_BOND_ROWS, columns=HARD_DOLLAR_BOND_COLUMNS).copy()
    for column in ("symbol", "source_symbol", "family", "currency", "price_basis", "coupon_day_count_basis", "schedule_source", "schedule_source_url"):
        frame[column] = frame[column].astype(str).str.strip()
    frame["symbol"] = frame["symbol"].str.upper()
    frame["source_symbol"] = frame["source_symbol"].str.upper()
    frame["family"] = frame["family"].str.upper()
    frame["issue_date"] = pd.to_datetime(frame["issue_date"], errors="coerce").dt.normalize()
    frame["maturity_date"] = pd.to_datetime(frame["maturity_date"], errors="coerce").dt.normalize()
    frame["settlement_lag_business_days"] = pd.to_numeric(frame["settlement_lag_business_days"], errors="coerce").astype("Int64")
    return frame.dropna(
        subset=[
            "symbol",
            "source_symbol",
            "family",
            "issue_date",
            "maturity_date",
            "currency",
            "price_basis",
            "coupon_day_count_basis",
            "settlement_lag_business_days",
            "schedule_source",
            "schedule_source_url",
        ]
    ).reset_index(drop=True)


def hard_dollar_symbols() -> list[str]:
    return hard_dollar_metadata_frame()["symbol"].tolist()
