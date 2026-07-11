#!/usr/bin/env python3
"""Generate and validate the Xaman Testnet runtime conformance report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_runtime_conformance import (  # noqa: E402
    CLAIM_TRACE_MAP_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PUBLIC_BUILD_ENVIRONMENT_PATH,
    PUBLIC_BUILD_REPRODUCTION_PATH,
    RUNTIME_CONFORMANCE_DOC_PATH,
    RUNTIME_CONFORMANCE_REPORT_PATH,
    RUNTIME_CONFORMANCE_TRACE_MAP_PATH,
    SOLVER_PORTFOLIO_REPORT_PATH,
    TRANSACTION_TRIAL_PATH,
    build_runtime_conformance_report,
    build_runtime_conformance_trace_map,
    render_runtime_conformance_markdown,
    validate_runtime_conformance_artifacts,
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'{path} did not contain a JSON object')
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')


def generate(repo_root: Path, *, out: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    claim_trace_map = _load_json(repo_root / CLAIM_TRACE_MAP_PATH)
    transaction_trial = _load_json(repo_root / TRANSACTION_TRIAL_PATH)
    public_build_reproduction = _load_json(repo_root / PUBLIC_BUILD_REPRODUCTION_PATH)
    public_build_environment = _load_json(repo_root / PUBLIC_BUILD_ENVIRONMENT_PATH)
    solver_portfolio_report = _load_json(repo_root / SOLVER_PORTFOLIO_REPORT_PATH)
    fuzz_counterexample_manifest = _load_json(repo_root / FUZZ_COUNTEREXAMPLE_MANIFEST_PATH)

    trace_map = build_runtime_conformance_trace_map(
        model_payload=model_payload,
        model_cid=model_cid,
        claim_trace_map=claim_trace_map,
        transaction_trial=transaction_trial,
        repo_root=repo_root,
    )
    _write_json(repo_root / RUNTIME_CONFORMANCE_TRACE_MAP_PATH, trace_map)
    report = build_runtime_conformance_report(
        model_payload=model_payload,
        model_cid=model_cid,
        claim_trace_map=claim_trace_map,
        transaction_trial=transaction_trial,
        public_build_reproduction=public_build_reproduction,
        public_build_environment=public_build_environment,
        solver_portfolio_report=solver_portfolio_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
        trace_map=trace_map,
        repo_root=repo_root,
    )
    markdown = render_runtime_conformance_markdown(report, trace_map)
    validate_runtime_conformance_artifacts(report=report, trace_map=trace_map, model_cid=model_cid)

    _write_json(out or (repo_root / RUNTIME_CONFORMANCE_REPORT_PATH), report)
    _write_text(repo_root / RUNTIME_CONFORMANCE_DOC_PATH, markdown)
    return trace_map, report, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument(
        '--out',
        default=RUNTIME_CONFORMANCE_REPORT_PATH,
        help='Runtime conformance report output path. The trace map and markdown use their standard task paths.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    trace_map, report, _markdown = generate(repo_root, out=out)
    print(
        json.dumps(
            {
                'trace_map_path': RUNTIME_CONFORMANCE_TRACE_MAP_PATH,
                'trace_map_cid': trace_map['artifact_cid'],
                'report_path': str(out.relative_to(repo_root) if out.is_relative_to(repo_root) else out),
                'report_cid': report['artifact_cid'],
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'doc_path': RUNTIME_CONFORMANCE_DOC_PATH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
