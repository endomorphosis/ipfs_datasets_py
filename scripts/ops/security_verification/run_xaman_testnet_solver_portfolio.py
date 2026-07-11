#!/usr/bin/env python3
"""Generate the reconciled Xaman Testnet multi-solver proof portfolio."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_solver_portfolio import (  # noqa: E402
    APALACHE_REPORT_PATH,
    ASSUMPTIONS_PATH,
    CLAIM_TRACE_MAP_PATH,
    COQ_DECISION_PATH,
    CVC5_RUNNER_REPORT_PATH,
    DISPROOF_VECTORS_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    FUZZ_REPORT_PATH,
    LEAN_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PORTFOLIO_DOC_PATH,
    PORTFOLIO_MANIFEST_PATH,
    PORTFOLIO_REPORT_PATH,
    PROOF_WORKER_LOCK_PATH,
    PROTOCOL_REPORT_PATH,
    SMT_REPORT_PATH,
    SOURCE_CLAIM_MAP_PATH,
    SOURCE_MANIFEST_PATH,
    XRPL_TRANSACTION_COVERAGE_PATH,
    build_xaman_testnet_solver_portfolio_manifest,
    build_xaman_testnet_solver_portfolio_report,
    render_xaman_testnet_solver_portfolio_markdown,
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


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def generate(repo_root: Path, *, out: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    assumptions_payload = _load_json(repo_root / ASSUMPTIONS_PATH)
    claim_trace_map = _load_json(repo_root / CLAIM_TRACE_MAP_PATH)
    proof_worker_lock = _load_json(repo_root / PROOF_WORKER_LOCK_PATH)
    cvc5_runner_report = _load_json(repo_root / CVC5_RUNNER_REPORT_PATH)
    smt_report = _load_json(repo_root / SMT_REPORT_PATH)
    apalache_report = _load_json(repo_root / APALACHE_REPORT_PATH)
    protocol_report = _load_json(repo_root / PROTOCOL_REPORT_PATH)
    lean_report = _load_json(repo_root / LEAN_REPORT_PATH)
    coq_decision = _load_json(repo_root / COQ_DECISION_PATH)
    fuzz_report = _load_json(repo_root / FUZZ_REPORT_PATH)
    fuzz_counterexample_manifest = _load_json(repo_root / FUZZ_COUNTEREXAMPLE_MANIFEST_PATH)
    source_manifest = _load_json(repo_root / SOURCE_MANIFEST_PATH, required=False)
    source_claim_map = _load_json(repo_root / SOURCE_CLAIM_MAP_PATH, required=False)
    xrpl_transaction_coverage = _load_json(repo_root / XRPL_TRANSACTION_COVERAGE_PATH, required=False)
    disproof_vectors = _load_json(repo_root / DISPROOF_VECTORS_PATH, required=False)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()

    if (
        model_payload is None
        or assumptions_payload is None
        or claim_trace_map is None
        or proof_worker_lock is None
        or cvc5_runner_report is None
        or smt_report is None
        or apalache_report is None
        or protocol_report is None
        or lean_report is None
        or coq_decision is None
        or fuzz_report is None
        or fuzz_counterexample_manifest is None
    ):
        raise FileNotFoundError('required Testnet solver portfolio inputs are missing')

    manifest = build_xaman_testnet_solver_portfolio_manifest(
        model_payload=model_payload,
        model_cid=model_cid,
        assumptions_payload=assumptions_payload,
        claim_trace_map=claim_trace_map,
        proof_worker_lock=proof_worker_lock,
        cvc5_runner_report=cvc5_runner_report,
        smt_report=smt_report,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
        source_manifest=source_manifest,
        source_claim_map=source_claim_map,
        xrpl_transaction_coverage=xrpl_transaction_coverage,
        disproof_vectors=disproof_vectors,
        repo_root=repo_root,
    )
    report = build_xaman_testnet_solver_portfolio_report(
        manifest=manifest,
        model_payload=model_payload,
        model_cid=model_cid,
        assumptions_payload=assumptions_payload,
        smt_report=smt_report,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
    )
    markdown = render_xaman_testnet_solver_portfolio_markdown(manifest, report)

    _write_json(repo_root / PORTFOLIO_MANIFEST_PATH, manifest)
    _write_json(out or (repo_root / PORTFOLIO_REPORT_PATH), report)
    _write_text(repo_root / PORTFOLIO_DOC_PATH, markdown)
    return manifest, report, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument(
        '--out',
        default=PORTFOLIO_REPORT_PATH,
        help='Portfolio report output path. The manifest and markdown use their standard task paths.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    manifest, report, _markdown = generate(repo_root, out=out)
    print(
        json.dumps(
            {
                'manifest_path': PORTFOLIO_MANIFEST_PATH,
                'manifest_cid': manifest['artifact_cid'],
                'report_path': str(out.relative_to(repo_root) if out.is_relative_to(repo_root) else out),
                'report_cid': report['artifact_cid'],
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'doc_path': PORTFOLIO_DOC_PATH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
