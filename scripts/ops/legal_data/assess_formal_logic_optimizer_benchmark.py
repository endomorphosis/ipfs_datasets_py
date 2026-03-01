#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.optimizer_policy import build_optimizer_onoff_benchmark


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build optimizer on/off benchmark comparison")
    ap.add_argument("--optimizer-off", required=True, help="Optimizer-off report JSON path")
    ap.add_argument("--optimizer-on", required=True, help="Optimizer-on report JSON path")
    ap.add_argument("--output", required=True, help="Output benchmark JSON path")
    args = ap.parse_args()

    off_report = _load_json(args.optimizer_off)
    on_report = _load_json(args.optimizer_on)
    benchmark = build_optimizer_onoff_benchmark(off_report, on_report)
    _write_json(args.output, benchmark)

    summary = benchmark.get("summary") or {}
    print(f"benchmark_id={summary.get('benchmark_id')}")
    print(f"improvement_count={summary.get('improvement_count')}")
    print(f"regression_count={summary.get('regression_count')}")
    print(f"net_score={summary.get('net_score')}")
    print(f"semantic_gain={summary.get('semantic_gain')}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
