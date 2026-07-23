#!/usr/bin/env python3
"""Lock the Xaman Testnet SMT proof worker and run CVC5 differential evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (  # noqa: E402
    SecurityModelIR,
    validate_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_smt_worker import (  # noqa: E402
    ASSUMPTIONS_PATH,
    CVC5_RUNNER_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROOF_WORKER_LOCK_PATH,
    SMTLIB_DIR,
    TRACE_MAP_PATH,
    build_xaman_testnet_smt_worker_artifacts,
    compile_pinned_testnet_smtlib_artifacts,
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def _safe_filename(claim_id: str) -> str:
    safe = ''.join(character if character.isalnum() or character in {'-', '_'} else '_' for character in claim_id)
    return safe or 'claim'


def _write_smtlib_artifacts(repo_root: Path, model_payload: dict[str, object]) -> None:
    smtlib_dir = repo_root / SMTLIB_DIR
    if smtlib_dir.exists():
        shutil.rmtree(smtlib_dir)
    smtlib_dir.mkdir(parents=True, exist_ok=True)

    model = validate_ir(SecurityModelIR.from_untrusted_dict(model_payload, strict=True))
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    artifacts = compile_pinned_testnet_smtlib_artifacts(model, model_cid=model_cid)
    manifest_entries: list[dict[str, object]] = []
    for artifact in artifacts:
        filename = f'{_safe_filename(artifact.claim_id)}.smt2'
        (smtlib_dir / filename).write_text(artifact.smtlib, encoding='utf-8')
        manifest_entries.append(
            {
                'claim_id': artifact.claim_id,
                'claim_version': artifact.claim_version,
                'path': filename,
                'artifact_cid': artifact.artifact_cid,
                'logic': artifact.metadata['logic'],
                'query_kind': artifact.metadata['query_kind'],
                'assertion_count': artifact.metadata['assertion_count'],
                'blocking_assumption_ids': list(artifact.metadata.get('blocking_assumption_ids', [])),
                'blocking_assumption_count': len(artifact.metadata.get('blocking_assumption_ids', [])),
                'severity': artifact.metadata['severity'],
                'domain': artifact.metadata.get('domain'),
            }
        )
    manifest = {
        'schema_version': 'xaman-testnet-smtlib-manifest/v1',
        'task_id': 'PORTAL-CXTP-132',
        'model_id': model.model_id,
        'model_schema_version': model.schema_version,
        'model_cid': model_cid,
        'claim_count': len(manifest_entries),
        'query_kind': artifacts[0].metadata['query_kind'] if artifacts else 'none',
        'logic': artifacts[0].metadata['logic'] if artifacts else 'none',
        'artifacts': manifest_entries,
    }
    _write_json(smtlib_dir / 'manifest.json', manifest)


def generate(repo_root: Path, *, timeout_ms: int, cvc5_executable: str | None = None) -> dict[str, dict[str, object]]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map_payload = _load_json(repo_root / TRACE_MAP_PATH)
    assumptions_payload = _load_json(repo_root / ASSUMPTIONS_PATH)
    artifacts = build_xaman_testnet_smt_worker_artifacts(
        model_payload,
        model_cid=model_cid,
        trace_map_payload=trace_map_payload,
        assumptions_payload=assumptions_payload,
        timeout_ms=timeout_ms,
        cvc5_executable=cvc5_executable,
    )

    _write_smtlib_artifacts(repo_root, model_payload)
    _write_json(repo_root / PROOF_WORKER_LOCK_PATH, artifacts['proof_worker_lock'])
    _write_json(repo_root / CVC5_RUNNER_REPORT_PATH, artifacts['cvc5_runner_report'])
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument('--timeout-ms', type=int, default=5_000, help='Per-claim solver timeout in milliseconds.')
    parser.add_argument('--cvc5-executable', default=None, help='Optional explicit cvc5 executable path.')
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    artifacts = generate(repo_root, timeout_ms=args.timeout_ms, cvc5_executable=args.cvc5_executable)
    report = artifacts['cvc5_runner_report']
    print(
        json.dumps(
            {
                'proof_worker_lock_path': PROOF_WORKER_LOCK_PATH,
                'cvc5_runner_report_path': CVC5_RUNNER_REPORT_PATH,
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'claim_count': report['summary']['claim_count'],
                'solver_blocker_count': report['summary']['solver_blocker_count'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
