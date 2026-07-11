#!/usr/bin/env python3
"""Prove or disprove the frozen Xaman Testnet SecurityModelIR claim set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_smt_results import (  # noqa: E402
    ASSUMPTIONS_PATH,
    COUNTEREXAMPLE_DIR,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROOF_REPORT_PATH,
    PROOF_WORKER_LOCK_PATH,
    CVC5_RUNNER_REPORT_PATH,
    build_xaman_testnet_smt_results,
    counterexample_artifacts,
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def generate(repo_root: Path) -> dict[str, object]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    assumptions_payload = _load_json(repo_root / ASSUMPTIONS_PATH)
    proof_worker_lock = _load_json(repo_root / PROOF_WORKER_LOCK_PATH)
    cvc5_runner_report = _load_json(repo_root / CVC5_RUNNER_REPORT_PATH)

    report = build_xaman_testnet_smt_results(
        model_payload,
        model_cid=model_cid,
        assumptions_payload=assumptions_payload,
        proof_worker_lock=proof_worker_lock,
        cvc5_runner_report=cvc5_runner_report,
    )

    counterexample_dir = repo_root / COUNTEREXAMPLE_DIR
    if counterexample_dir.exists():
        shutil.rmtree(counterexample_dir)
    for rel_path, artifact in counterexample_artifacts(report).items():
        _write_json(repo_root / rel_path, artifact)
    _write_json(repo_root / PROOF_REPORT_PATH, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report = generate(repo_root)
    print(
        json.dumps(
            {
                'proof_report_path': PROOF_REPORT_PATH,
                'counterexample_dir': COUNTEREXAMPLE_DIR,
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'proved_count': report['summary']['proved_count'],
                'counterexample_count': report['summary']['counterexample_count'],
                'incomplete_count': report['summary']['incomplete_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
