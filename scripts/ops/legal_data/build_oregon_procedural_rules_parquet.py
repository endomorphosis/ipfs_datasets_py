#!/usr/bin/env python3
"""Build parquet indexes for Oregon procedural rules with IPFS CID keys.

The script reads Oregon civil procedure, criminal procedure, and local court
rules records from existing JSONL artifacts, computes a deterministic CID per
record, and writes one parquet file per family.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore
except Exception as exc:  # pragma: no cover - dependency error path
    raise SystemExit(f"Missing dependency 'pyarrow': {exc}")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def _record_code_name(record: Dict[str, Any]) -> str:
    is_part_of = record.get("isPartOf")
    if isinstance(is_part_of, dict):
        name = is_part_of.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    code_name = record.get("code_name")
    if isinstance(code_name, str):
        return code_name.strip()
    return ""


def _canonical_json_bytes(record: Dict[str, Any]) -> bytes:
    # Exclude CID fields to keep hashing stable across rebuilds.
    normalized = {k: v for k, v in record.items() if k not in {"ipfs_cid", "cid"}}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _ipfs_cid(record: Dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json_bytes(record)).digest()
    # CIDv1 bytes: <version=1><codec=raw><multihash(sha2-256,digest)>
    multihash_bytes = bytes([0x12, 0x20]) + digest
    cid_bytes = bytes([0x01, 0x55]) + multihash_bytes
    base32 = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return f"b{base32}"


def _indexed_records(records: Iterable[Dict[str, Any]], family: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        cid = _ipfs_cid(record)
        if cid in seen:
            continue
        seen.add(cid)

        indexed = dict(record)
        indexed["ipfs_cid"] = cid
        indexed["dataset_family"] = family
        out.append(indexed)

    out.sort(key=lambda item: item["ipfs_cid"])
    return out


def _write_parquet(records: List[Dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(records)
    pq.write_table(table, out_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index Oregon procedural rules into parquet using IPFS CID keys"
    )
    parser.add_argument(
        "--civil-jsonl",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/jsonld/oregon_rules_of_civil_procedure.jsonl",
        help="Input ORCP JSONL path",
    )
    parser.add_argument(
        "--criminal-jsonl",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/jsonld/oregon_rules_of_criminal_procedure.jsonl",
        help="Input ORCrP JSONL path",
    )
    parser.add_argument(
        "--state-or-jsonl",
        default="/home/barberb/.ipfs_datasets/state_laws/state_laws_jsonld/STATE-OR.jsonld",
        help="Consolidated Oregon JSONL used to extract local court rules",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/barberb/.ipfs_datasets/state_laws/OR/parsed/parquet",
        help="Directory for indexed parquet outputs",
    )
    args = parser.parse_args()

    civil_path = Path(args.civil_jsonl).expanduser().resolve()
    criminal_path = Path(args.criminal_jsonl).expanduser().resolve()
    state_or_path = Path(args.state_or_jsonl).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    civil_records = _read_jsonl(civil_path)
    criminal_records = _read_jsonl(criminal_path)
    all_or_records = _read_jsonl(state_or_path)
    local_records = [
        record
        for record in all_or_records
        if _record_code_name(record) == "Oregon Local Court Rules"
    ]

    indexed_civil = _indexed_records(civil_records, family="orcp")
    indexed_criminal = _indexed_records(criminal_records, family="orcrp")
    indexed_local = _indexed_records(local_records, family="local_court_rules")

    out_civil = output_dir / "oregon_rules_of_civil_procedure_indexed.parquet"
    out_criminal = output_dir / "oregon_rules_of_criminal_procedure_indexed.parquet"
    out_local = output_dir / "oregon_local_court_rules_indexed.parquet"

    _write_parquet(indexed_civil, out_civil)
    _write_parquet(indexed_criminal, out_criminal)
    _write_parquet(indexed_local, out_local)

    result = {
        "status": "success",
        "inputs": {
            "civil_jsonl": str(civil_path),
            "criminal_jsonl": str(criminal_path),
            "state_or_jsonl": str(state_or_path),
        },
        "outputs": {
            "orcp": str(out_civil),
            "orcrp": str(out_criminal),
            "local_court_rules": str(out_local),
        },
        "counts": {
            "orcp": len(indexed_civil),
            "orcrp": len(indexed_criminal),
            "local_court_rules": len(indexed_local),
        },
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
