#!/usr/bin/env python3
"""Generate the Xaman public-source/Testnet bounded assurance verdict."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_public_source_testnet_assurance_verdict import (  # noqa: E402
    FUZZ_CAMPAIGN_MANIFEST_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    FUZZ_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PUBLIC_BUILD_ENVIRONMENT_PATH,
    PUBLIC_BUILD_REPRODUCTION_PATH,
    PUBLIC_SOURCE_ASSESSMENT_PATH,
    PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH,
    PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH,
    PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH,
    RUNTIME_CONFORMANCE_REPORT_PATH,
    RUNTIME_CONFORMANCE_TRACE_MAP_PATH,
    SOLVER_PORTFOLIO_REPORT_PATH,
    build_public_source_testnet_assurance_bundle,
    build_public_source_testnet_assurance_verdict,
    render_public_source_testnet_assurance_markdown,
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'{path} did not contain a JSON object')
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')


def generate(repo_root: Path, *, out: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    model_payload = _load_json(repo_root / MODEL_PATH)
    model_cid = (repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    bundle = build_public_source_testnet_assurance_bundle(
        model_payload=model_payload,
        model_cid=model_cid,
        public_source_assessment=_load_json(repo_root / PUBLIC_SOURCE_ASSESSMENT_PATH),
        public_build_reproduction=_load_json(repo_root / PUBLIC_BUILD_REPRODUCTION_PATH),
        public_build_environment=_load_json(repo_root / PUBLIC_BUILD_ENVIRONMENT_PATH),
        solver_portfolio_report=_load_json(repo_root / SOLVER_PORTFOLIO_REPORT_PATH),
        fuzz_campaign_manifest=_load_json(repo_root / FUZZ_CAMPAIGN_MANIFEST_PATH),
        fuzz_counterexample_manifest=_load_json(repo_root / FUZZ_COUNTEREXAMPLE_MANIFEST_PATH),
        fuzz_report=_load_json(repo_root / FUZZ_REPORT_PATH),
        runtime_conformance_report=_load_json(repo_root / RUNTIME_CONFORMANCE_REPORT_PATH),
        runtime_conformance_trace_map=_load_json(repo_root / RUNTIME_CONFORMANCE_TRACE_MAP_PATH),
        repo_root=repo_root,
    )
    verdict = build_public_source_testnet_assurance_verdict(bundle)
    markdown = render_public_source_testnet_assurance_markdown(bundle, verdict)

    _write_json(repo_root / PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH, bundle)
    _write_json(out or (repo_root / PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH), verdict)
    _write_text(repo_root / PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH, markdown)
    return bundle, verdict, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    parser.add_argument(
        '--out',
        default=PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH,
        help='Verdict output path. The bundle and markdown use their standard task paths.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    bundle, verdict, _markdown = generate(repo_root, out=out)
    print(
        json.dumps(
            {
                'bundle_path': PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH,
                'bundle_cid': bundle['artifact_cid'],
                'verdict_path': str(out.relative_to(repo_root) if out.is_relative_to(repo_root) else out),
                'verdict_cid': verdict['artifact_cid'],
                'verdict': verdict['verdict'],
                'doc_path': PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
