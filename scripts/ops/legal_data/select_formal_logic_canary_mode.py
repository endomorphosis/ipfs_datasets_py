#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.shadow_mode import build_canary_mode_decision


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Select canary route from shadow-mode audit")
    ap.add_argument("--audit", required=True, help="Shadow mode audit JSON path")
    ap.add_argument("--risk-level", choices=["low", "medium", "high"], default="low")
    ap.add_argument("--allow-without-shadow-ready", action="store_true", help="Allow hybrid routing even when shadow_ready is false")
    ap.add_argument("--output", required=True, help="Output decision JSON path")
    args = ap.parse_args()

    audit = _load_json(args.audit)
    decision = build_canary_mode_decision(
        audit,
        risk_level=args.risk_level,
        require_shadow_ready=not args.allow_without_shadow_ready,
    )
    _write_json(args.output, decision)

    print(f"route={decision['route']}")
    print(f"hybrid_enabled={decision['hybrid_enabled']}")
    print(f"reason={decision['reason']}")
    print(f"proof_audit_required={decision['proof_audit_required']}")
    print(f"decision_output={args.output}")


if __name__ == "__main__":
    main()
