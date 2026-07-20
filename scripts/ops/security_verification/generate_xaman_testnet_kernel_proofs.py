#!/usr/bin/env python3
"""Generate checked Lean and independent Rocq Testnet kernel evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_kernel_proofs import (  # noqa: E402
    ASSUMPTIONS_PATH,
    COQ_DECISION_PATH,
    COQ_KERNEL_PATH,
    LEAN_KERNEL_PATH,
    LEAN_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    TRACE_MAP_PATH,
    build_xaman_testnet_coq_coverage_decision,
    build_xaman_testnet_lean_report,
    run_coq_kernel_check,
    run_lean_kernel_check,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def generate(repo_root: Path) -> tuple[dict, dict]:
    model = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map = _load_json(repo_root / TRACE_MAP_PATH)
    assumptions = _load_json(repo_root / ASSUMPTIONS_PATH)
    lean_source = (repo_root / LEAN_KERNEL_PATH).read_text(encoding='utf-8')

    lean_executable, lean_version, lean_check = run_lean_kernel_check(repo_root=repo_root)
    lean_report = build_xaman_testnet_lean_report(
        model_payload=model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
        lean_source=lean_source,
        lean_executable=lean_executable,
        lean_version=lean_version,
        lean_compile=lean_check,
    )
    _write_json(repo_root / LEAN_REPORT_PATH, lean_report)

    coqc_executable, coqc_version, coq_source, coq_check = run_coq_kernel_check(repo_root=repo_root)
    coq_decision = build_xaman_testnet_coq_coverage_decision(
        model_payload=model,
        model_cid=model_cid,
        lean_report=lean_report,
        coq_kernel_source=coq_source,
        coqc_executable=coqc_executable,
        coqc_version=coqc_version,
        coq_check=coq_check,
    )
    _write_json(repo_root / COQ_DECISION_PATH, coq_decision)
    return lean_report, coq_decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    args = parser.parse_args(argv)

    lean_report, coq_decision = generate(Path(args.repo_root).resolve())
    print(
        json.dumps(
            {
                'lean_overall_status': lean_report['overall_status'],
                'coq_decision': coq_decision['decision'],
                'coq_overall_status': coq_decision['overall_status'],
                'testnet_assurance_blocked': coq_decision['testnet_assurance_blocked'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
