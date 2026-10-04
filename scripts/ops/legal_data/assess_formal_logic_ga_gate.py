#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.shadow_mode import build_ga_gate_assessment


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Assess GA gate readiness for formal logic rollout")
    ap.add_argument("--shadow-audit", required=True, help="Shadow mode audit JSON path")
    ap.add_argument("--canary-decision", required=True, help="Canary decision JSON path")
    ap.add_argument("--candidate-report", required=True, help="Hybrid/candidate report JSON path")
    ap.add_argument("--runtime-stats", default="", help="Optional runtime stats JSON path (p95_latency_ms, timeout_rate, error_rate)")
    ap.add_argument("--allow-missing-runtime-stats", action="store_true", help="Do not fail GA gate when runtime stats are missing")
    ap.add_argument("--output", required=True, help="Output GA gate assessment JSON path")
    args = ap.parse_args()

    shadow_audit = _load_json(args.shadow_audit)
    canary_decision = _load_json(args.canary_decision)
    candidate_report = _load_json(args.candidate_report)
    runtime_stats = _load_json(args.runtime_stats) if args.runtime_stats else None

    assessment = build_ga_gate_assessment(
        shadow_audit,
        canary_decision,
        candidate_report,
        runtime_stats=runtime_stats,
        require_latency_stats=not args.allow_missing_runtime_stats,
    )
    _write_json(args.output, assessment)

    summary = assessment.get("summary") or {}
    print(f"ga_ready={summary.get('ga_ready')}")
    print(f"failure_count={summary.get('failure_count')}")
    print(f"check_count={summary.get('check_count')}")
    print(f"assessment_output={args.output}")


if __name__ == "__main__":
    main()
