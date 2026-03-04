#!/usr/bin/env python3
"""Extract state civil/criminal procedure rules into a consolidated JSONL dataset.

This script scans normalized state JSONL outputs and keeps records that match
civil procedure or criminal procedure rule patterns.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES

TERRITORIES: Dict[str, str] = {
    "AS": "American Samoa",
    "GU": "Guam",
    "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands",
}

CIVIL_PATTERNS = [
    re.compile(r"\brules?\s+of\s+civil\s+procedure\b", re.IGNORECASE),
    re.compile(r"\bcivil\s+procedure\s+rules?\b", re.IGNORECASE),
    re.compile(r"\b(?:state\s+)?r(?:ule)?\.?\s*c(?:iv)?\.?\s*p(?:roc)?\b", re.IGNORECASE),
]

CRIMINAL_PATTERNS = [
    re.compile(r"\brules?\s+of\s+criminal\s+procedure\b", re.IGNORECASE),
    re.compile(r"\bcriminal\s+procedure\s+rules?\b", re.IGNORECASE),
    re.compile(r"\b(?:state\s+)?r(?:ule)?\.?\s*cr(?:im)?\.?\s*p(?:roc)?\b", re.IGNORECASE),
]


def _get_code_name(record: Dict[str, Any]) -> str:
    part = record.get("isPartOf")
    if isinstance(part, dict):
        name = part.get("name")
        if isinstance(name, str):
            return name
    value = record.get("code_name")
    return value if isinstance(value, str) else ""


def _joined_signal_text(record: Dict[str, Any]) -> str:
    values: List[str] = []
    for key in [
        "name",
        "titleName",
        "chapterName",
        "sectionName",
        "legislationType",
        "text",
    ]:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    code_name = _get_code_name(record)
    if code_name.strip():
        values.append(code_name.strip())
    return "\n".join(values)


def _classify_procedure_family(record: Dict[str, Any]) -> Optional[str]:
    signal = _joined_signal_text(record)
    if any(pattern.search(signal) for pattern in CIVIL_PATTERNS):
        return "civil_procedure"
    if any(pattern.search(signal) for pattern in CRIMINAL_PATTERNS):
        return "criminal_procedure"
    return None


def _state_files(input_dir: Path) -> Iterable[Path]:
    return sorted(input_dir.glob("STATE-*.jsonld"))


def _jurisdiction_code_from_path(path: Path) -> str:
    return path.stem.replace("STATE-", "").upper()


def _extract_record(row: Dict[str, Any], jurisdiction_code: str, family: str) -> Dict[str, Any]:
    return {
        "jurisdiction_code": jurisdiction_code,
        "jurisdiction_name": US_STATES.get(jurisdiction_code, jurisdiction_code),
        "territory": False,
        "procedure_family": family,
        "ipfs_cid": row.get("ipfs_cid"),
        "name": row.get("name"),
        "titleName": row.get("titleName"),
        "chapterName": row.get("chapterName"),
        "sectionName": row.get("sectionName"),
        "sourceUrl": row.get("sourceUrl"),
        "code_name": _get_code_name(row),
        "text": row.get("text"),
        "record": row,
    }


def run_extraction(input_dir: Path, output_jsonl: Path, output_summary: Path) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    per_jurisdiction = Counter()
    per_family = Counter()
    supported_codes = set(US_STATES.keys())

    found_files = list(_state_files(input_dir))
    file_codes = {_jurisdiction_code_from_path(p) for p in found_files}

    for path in found_files:
        code = _jurisdiction_code_from_path(path)
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                family = _classify_procedure_family(row)
                if not family:
                    continue
                out = _extract_record(row, jurisdiction_code=code, family=family)
                records.append(out)
                per_jurisdiction[code] += 1
                per_family[family] += 1

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    missing_supported = sorted(code for code in supported_codes if code not in file_codes)
    without_matches = sorted(code for code in file_codes if per_jurisdiction[code] == 0)

    summary = {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "output_jsonl": str(output_jsonl),
        "total_records": len(records),
        "counts_by_family": dict(per_family),
        "counts_by_jurisdiction": dict(sorted(per_jurisdiction.items())),
        "supported_jurisdiction_count": len(supported_codes),
        "supported_jurisdictions": dict(sorted(US_STATES.items())),
        "supported_missing_files": missing_supported,
        "supported_with_no_procedural_matches": without_matches,
        "territories_requested": dict(sorted(TERRITORIES.items())),
        "territories_supported_by_state_scraper": [],
        "territory_note": "Current state scraper supports 50 states + DC only; territories require dedicated source connectors.",
    }

    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract US civil/criminal procedure rules from state JSONL corpus")
    parser.add_argument(
        "--input-dir",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "state_laws_jsonld"),
        help="Directory containing STATE-*.jsonld files",
    )
    parser.add_argument(
        "--output-jsonl",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules.jsonl"),
        help="Consolidated procedural-rules JSONL output",
    )
    parser.add_argument(
        "--output-summary",
        default=str(Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules" / "us_state_procedural_rules_summary.json"),
        help="Coverage and counts summary JSON output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_extraction(
        input_dir=Path(args.input_dir).expanduser().resolve(),
        output_jsonl=Path(args.output_jsonl).expanduser().resolve(),
        output_summary=Path(args.output_summary).expanduser().resolve(),
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
