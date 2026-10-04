#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.shadow_mode import build_shadow_mode_audit


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build shadow mode audit from baseline and hybrid formal logic reports")
    ap.add_argument("--baseline", required=True, help="Baseline report JSON path")
    ap.add_argument("--candidate", required=True, help="Hybrid/candidate report JSON path")
    ap.add_argument("--output", required=True, help="Output audit JSON path")
    args = ap.parse_args()

    baseline = _load_json(args.baseline)
    candidate = _load_json(args.candidate)
    audit = build_shadow_mode_audit(baseline, candidate)
    _write_json(args.output, audit)

    summary = audit.get("summary") or {}
    print(f"shadow_ready={summary.get('shadow_ready')}")
    print(f"failure_count={summary.get('failure_count')}")
    print(f"baseline_segment_count={summary.get('baseline_segment_count')}")
    print(f"candidate_segment_count={summary.get('candidate_segment_count')}")
    print(f"audit_output={args.output}")


if __name__ == "__main__":
    main()
