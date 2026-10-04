#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.optimizer_policy import build_optimizer_acceptance_decision


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Assess optimizer acceptance policy from baseline/candidate reports")
    ap.add_argument("--baseline", required=True, help="Baseline report JSON path")
    ap.add_argument("--candidate", required=True, help="Candidate report JSON path")
    ap.add_argument("--min-gain-threshold", type=float, default=0.0)
    ap.add_argument("--max-modality-regression", type=float, default=0.0)
    ap.add_argument("--default-modality-floor", type=float, default=0.85)
    ap.add_argument("--output", required=True, help="Output policy decision JSON path")
    args = ap.parse_args()

    baseline = _load_json(args.baseline)
    candidate = _load_json(args.candidate)
    decision = build_optimizer_acceptance_decision(
        baseline,
        candidate,
        min_gain_threshold=args.min_gain_threshold,
        max_modality_regression=args.max_modality_regression,
        default_modality_floor=args.default_modality_floor,
    )
    _write_json(args.output, decision)

    summary = decision.get("summary") or {}
    print(f"decision_id={summary.get('decision_id')}")
    print(f"accepted={summary.get('accepted')}")
    print(f"failure_count={summary.get('failure_count')}")
    print(f"global_gain={summary.get('global_gain')}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
