from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.common.fixed_income import hard_dollar_symbols
from src.common.io import RAW_DIR, ensure_data_dirs
from src.ingest.bonistas import fetch_hard_dollar_reference


DEFAULT_METADATA_OUTPUT_PATH = RAW_DIR / "hard_dollar_reference_metadata.csv"
DEFAULT_FLOW_OUTPUT_PATH = RAW_DIR / "hard_dollar_reference_flows.csv"


def run_hard_dollar_reference(
    metadata_out: Path = DEFAULT_METADATA_OUTPUT_PATH,
    flow_out: Path = DEFAULT_FLOW_OUTPUT_PATH,
    timeout_seconds: int = 20,
) -> dict[str, object]:
    ensure_data_dirs()
    metadata_out.parent.mkdir(parents=True, exist_ok=True)
    flow_out.parent.mkdir(parents=True, exist_ok=True)

    try:
        metadata, flows = fetch_hard_dollar_reference(symbols=hard_dollar_symbols(), timeout_seconds=timeout_seconds)
    except Exception as exc:
        cached = _load_cached_hard_dollar_reference(metadata_out=metadata_out, flow_out=flow_out)
        if cached is None:
            raise
        metadata, flows = cached
        return _build_result(
            metadata=metadata,
            flows=flows,
            metadata_out=metadata_out,
            flow_out=flow_out,
            source="cached",
            fallback_reason=f"{type(exc).__name__}: {exc}",
        )

    metadata.to_csv(metadata_out, index=False)
    flows.to_csv(flow_out, index=False)
    return _build_result(metadata=metadata, flows=flows, metadata_out=metadata_out, flow_out=flow_out, source="live")


def _load_cached_hard_dollar_reference(metadata_out: Path, flow_out: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    if not metadata_out.exists() or not flow_out.exists():
        return None
    if metadata_out.stat().st_size == 0 or flow_out.stat().st_size == 0:
        return None

    metadata = pd.read_csv(metadata_out)
    flows = pd.read_csv(flow_out)
    if metadata.empty or flows.empty:
        return None
    return metadata, flows


def _build_result(
    *,
    metadata: pd.DataFrame,
    flows: pd.DataFrame,
    metadata_out: Path,
    flow_out: Path,
    source: str,
    fallback_reason: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "symbol_count": _unique_count(metadata, "symbol"),
        "metadata_rows": len(metadata),
        "flow_rows": len(flows),
        "metadata_out": metadata_out,
        "flow_out": flow_out,
        "source": source,
    }
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


def _unique_count(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].nunique())


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh hard-dollar contractual reference metadata and schedules.")
    parser.add_argument("--metadata-out", type=Path, default=DEFAULT_METADATA_OUTPUT_PATH, help="Metadata output CSV.")
    parser.add_argument("--flow-out", type=Path, default=DEFAULT_FLOW_OUTPUT_PATH, help="Flow output CSV.")
    parser.add_argument("--timeout-seconds", type=int, default=20, help="HTTP timeout for Bonistas requests.")
    args = parser.parse_args()

    result = run_hard_dollar_reference(
        metadata_out=args.metadata_out,
        flow_out=args.flow_out,
        timeout_seconds=args.timeout_seconds,
    )
    verb = "reused cached" if result.get("source") == "cached" else "refreshed"
    print(
        f"[hard-dollar] {verb} {result['symbol_count']} symbols | "
        f"metadata={result['metadata_rows']} rows -> {result['metadata_out']} | "
        f"flows={result['flow_rows']} rows -> {result['flow_out']}"
    )
    if result.get("fallback_reason"):
        print(f"[hard-dollar] live refresh failed: {result['fallback_reason']}")


if __name__ == "__main__":
    main()
