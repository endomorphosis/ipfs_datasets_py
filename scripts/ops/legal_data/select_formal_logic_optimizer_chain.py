#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.optimizer_policy import build_optimizer_chain_plan


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Select optimizer chain stage toggles from policy decision")
    ap.add_argument("--decision", required=True, help="Optimizer acceptance decision JSON path")
    ap.add_argument("--output", required=True, help="Output chain plan JSON path")
    args = ap.parse_args()

    decision = _load_json(args.decision)
    plan = build_optimizer_chain_plan(decision)
    _write_json(args.output, plan)

    summary = plan.get("summary") or {}
    env = plan.get("env") or {}
    print(f"post_parse_enabled={summary.get('post_parse_enabled')}")
    print(f"post_compile_enabled={summary.get('post_compile_enabled')}")
    print(f"env_ENABLE_POST_PARSE_OPTIMIZERS={env.get('ENABLE_POST_PARSE_OPTIMIZERS')}")
    print(f"env_ENABLE_POST_COMPILE_OPTIMIZERS={env.get('ENABLE_POST_COMPILE_OPTIMIZERS')}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
