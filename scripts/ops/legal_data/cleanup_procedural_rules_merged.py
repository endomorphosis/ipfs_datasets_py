#!/usr/bin/env python3
"""Clean merged procedural-rules JSONL by removing obvious non-substantive rows.

Default behavior keeps output separate from input and writes a JSON report.
Use --in-place to replace the input file after writing an optional backup.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ASSET_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
)


def _load_rows(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _coverage(rows: Iterable[Dict[str, object]]) -> Dict[str, object]:
    by_state: Dict[str, Set[str]] = defaultdict(set)
    total = 0
    for row in rows:
        total += 1
        state = str(row.get("jurisdiction_code") or "").strip().upper()
        family = str(row.get("procedure_family") or "").strip()
        if state and family:
            by_state[state].add(family)

    full = 0
    partial = 0
    none = 0
    partial_states: List[str] = []
    for state, families in sorted(by_state.items()):
        has_civil = "civil_procedure" in families or "civil_and_criminal_procedure" in families
        has_criminal = "criminal_procedure" in families or "civil_and_criminal_procedure" in families
        if has_civil and has_criminal:
            full += 1
        elif has_civil or has_criminal:
            partial += 1
            partial_states.append(state)
        else:
            none += 1

    return {
        "records": total,
        "states": len(by_state),
        "full_both": full,
        "partial": partial,
        "none": none,
        "partial_states": partial_states,
    }


def _should_drop(row: Dict[str, object], keep_ia_pdf_marker: bool) -> Tuple[bool, str]:
    state = str(row.get("jurisdiction_code") or "").strip().upper()
    name = str(row.get("name") or "").strip().lower()
    url = str(row.get("sourceUrl") or "").strip().lower()

    if name.startswith("skip to "):
        return True, "skip_label"

    is_asset = url.endswith(ASSET_EXTENSIONS)
    if is_asset:
        if keep_ia_pdf_marker and state == "IA" and "click to view the pdf file" in name:
            return False, ""
        return True, "asset_url"

    return False, ""


def _default_paths() -> Tuple[Path, Path]:
    base = Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules"
    src = base / "us_state_procedural_rules_merged_with_rjina.jsonl"
    out = base / "us_state_procedural_rules_merged_with_rjina.cleaned.jsonl"
    return src, out


def parse_args() -> argparse.Namespace:
    default_in, default_out = _default_paths()
    parser = argparse.ArgumentParser(description="Clean merged procedural rules JSONL")
    parser.add_argument("--input", default=str(default_in), help="Input merged JSONL")
    parser.add_argument("--output", default=str(default_out), help="Output cleaned JSONL")
    parser.add_argument("--report-json", default="", help="Optional report JSON path")
    parser.add_argument("--in-place", action="store_true", help="Replace input file with cleaned output")
    parser.add_argument("--backup", default="", help="Backup path used when --in-place is set")
    parser.add_argument(
        "--require-equal-coverage",
        action="store_true",
        help="Fail when cleaned coverage is worse than source (always enforced for --in-place)",
    )
    parser.add_argument(
        "--no-keep-ia-pdf-marker",
        action="store_true",
        help="Do not preserve IA legacy 'Click to view the PDF File' marker rows",
    )
    return parser.parse_args()


def _coverage_regression(source: Dict[str, object], cleaned: Dict[str, object]) -> Dict[str, object]:
    source_full = int(source.get("full_both", 0))
    source_partial = int(source.get("partial", 0))
    source_none = int(source.get("none", 0))
    cleaned_full = int(cleaned.get("full_both", 0))
    cleaned_partial = int(cleaned.get("partial", 0))
    cleaned_none = int(cleaned.get("none", 0))

    regressed = (
        cleaned_full < source_full
        or cleaned_partial > source_partial
        or cleaned_none > source_none
    )
    return {
        "regressed": regressed,
        "source_full_both": source_full,
        "cleaned_full_both": cleaned_full,
        "source_partial": source_partial,
        "cleaned_partial": cleaned_partial,
        "source_none": source_none,
        "cleaned_none": cleaned_none,
    }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    keep_ia_pdf_marker = not bool(args.no_keep_ia_pdf_marker)

    rows = list(_load_rows(input_path))
    source_metrics = _coverage(rows)

    removed_by_reason: Counter[str] = Counter()
    removed_examples: List[Dict[str, object]] = []
    cleaned_rows: List[Dict[str, object]] = []

    for row in rows:
        drop, reason = _should_drop(row, keep_ia_pdf_marker=keep_ia_pdf_marker)
        if drop:
            removed_by_reason[reason] += 1
            if len(removed_examples) < 30:
                removed_examples.append(
                    {
                        "state": row.get("jurisdiction_code"),
                        "family": row.get("procedure_family"),
                        "name": row.get("name"),
                        "sourceUrl": row.get("sourceUrl"),
                        "reason": reason,
                    }
                )
            continue
        cleaned_rows.append(row)

    cleaned_metrics = _coverage(cleaned_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in cleaned_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    coverage_check = _coverage_regression(source_metrics, cleaned_metrics)
    enforce_coverage = bool(args.require_equal_coverage or args.in_place)
    blocked_in_place = bool(args.in_place and enforce_coverage and coverage_check["regressed"])

    if args.in_place and not blocked_in_place:
        backup_path = Path(args.backup).expanduser().resolve() if args.backup else input_path.with_suffix(".pre_cleanup_backup.jsonl")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(input_path.read_text(encoding="utf-8"), encoding="utf-8")
        input_path.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "output": str(output_path),
        "in_place": bool(args.in_place),
        "keep_ia_pdf_marker": keep_ia_pdf_marker,
        "enforce_coverage": enforce_coverage,
        "source_metrics": source_metrics,
        "cleaned_metrics": cleaned_metrics,
        "coverage_check": coverage_check,
        "blocked_in_place": blocked_in_place,
        "removed_total": int(sum(removed_by_reason.values())),
        "removed_by_reason": dict(removed_by_reason),
        "removed_examples": removed_examples,
    }

    report_path = Path(args.report_json).expanduser().resolve() if args.report_json else output_path.with_suffix(".cleanup_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    if enforce_coverage and coverage_check["regressed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
