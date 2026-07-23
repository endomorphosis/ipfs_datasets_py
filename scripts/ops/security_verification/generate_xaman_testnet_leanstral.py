#!/usr/bin/env python3
"""Generate the Xaman Testnet Leanstral untrusted assistant lock and audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_leanstral import (  # noqa: E402
    ASSUMPTIONS_PATH,
    AUDIT_PATH,
    LEAN_SOLVER_LANE_REPORT_PATH,
    LEANSTRAL_ENV_REPORT_PATH,
    LOCK_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    TESTNET_COQ_DECISION_PATH,
    TESTNET_LEAN_REPORT_PATH,
    TESTNET_SMT_REPORT_PATH,
    TRACE_MAP_PATH,
    build_xaman_testnet_leanstral_candidate_audit,
    build_xaman_testnet_leanstral_lock,
)


def _load_json(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.is_file():
        if required:
            raise FileNotFoundError(path)
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'{path} did not contain a JSON object')
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def generate(repo_root: Path) -> dict[str, dict[str, Any]]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    assumptions_payload = _load_json(repo_root / ASSUMPTIONS_PATH)
    trace_map_payload = _load_json(repo_root / TRACE_MAP_PATH)
    testnet_lean_report = _load_json(repo_root / TESTNET_LEAN_REPORT_PATH)
    smt_report = _load_json(repo_root / TESTNET_SMT_REPORT_PATH)
    coq_decision = _load_json(repo_root / TESTNET_COQ_DECISION_PATH)
    leanstral_report = _load_json(repo_root / LEANSTRAL_ENV_REPORT_PATH, required=False)
    lean_solver_report = _load_json(repo_root / LEAN_SOLVER_LANE_REPORT_PATH, required=False)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()

    if model_payload is None or assumptions_payload is None or trace_map_payload is None:
        raise FileNotFoundError('required Testnet model inputs are missing')
    if testnet_lean_report is None or smt_report is None or coq_decision is None:
        raise FileNotFoundError('required Testnet checker reports are missing')

    lock = build_xaman_testnet_leanstral_lock(
        model_payload=model_payload,
        model_cid=model_cid,
        assumptions_payload=assumptions_payload,
        trace_map_payload=trace_map_payload,
        leanstral_report=leanstral_report,
        lean_solver_report=lean_solver_report,
        testnet_lean_report=testnet_lean_report,
        smt_report=smt_report,
        coq_decision=coq_decision,
    )
    audit = build_xaman_testnet_leanstral_candidate_audit(
        lock=lock,
        model_payload=model_payload,
        model_cid=model_cid,
        testnet_lean_report=testnet_lean_report,
        smt_report=smt_report,
        coq_decision=coq_decision,
    )

    _write_json(repo_root / LOCK_PATH, lock)
    _write_json(repo_root / AUDIT_PATH, audit)
    return {'leanstral_assistant_lock': lock, 'leanstral_candidate_audit': audit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    args = parser.parse_args(argv)

    artifacts = generate(Path(args.repo_root).resolve())
    lock = artifacts['leanstral_assistant_lock']
    audit = artifacts['leanstral_candidate_audit']
    print(
        json.dumps(
            {
                'leanstral_assistant_lock_path': LOCK_PATH,
                'leanstral_candidate_audit_path': AUDIT_PATH,
                'lock_status': lock['overall_status'],
                'audit_status': audit['overall_status'],
                'security_decision': audit['security_decision'],
                'promoted_candidate_count': audit['summary']['promoted_candidate_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
