#!/usr/bin/env python3
"""Generate the Xaman XRPL Testnet scoped assurance bundle and verdict."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_assurance_verdict import (  # noqa: E402
    APALACHE_REPORT_PATH,
    ASSUMPTIONS_PATH,
    BUNDLE_PATH,
    CLAIM_TRACE_MAP_PATH,
    COQ_DECISION_PATH,
    FUZZ_REPORT_PATH,
    LEAN_REPORT_PATH,
    LEANSTRAL_AUDIT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROTOCOL_REPORT_PATH,
    SMT_REPORT_PATH,
    VERDICT_DOC_PATH,
    VERDICT_PATH,
    build_xaman_testnet_assurance_bundle,
    build_xaman_testnet_assurance_verdict,
    render_xaman_testnet_assurance_verdict_markdown,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def generate(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    bundle = build_xaman_testnet_assurance_bundle(
        model_payload=_load_json(repo_root / MODEL_PATH),
        model_cid=(repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip(),
        assumptions_payload=_load_json(repo_root / ASSUMPTIONS_PATH),
        claim_trace_map=_load_json(repo_root / CLAIM_TRACE_MAP_PATH),
        smt_report=_load_json(repo_root / SMT_REPORT_PATH),
        apalache_report=_load_json(repo_root / APALACHE_REPORT_PATH),
        protocol_report=_load_json(repo_root / PROTOCOL_REPORT_PATH),
        lean_report=_load_json(repo_root / LEAN_REPORT_PATH),
        coq_decision=_load_json(repo_root / COQ_DECISION_PATH),
        fuzz_report=_load_json(repo_root / FUZZ_REPORT_PATH),
        leanstral_audit=_load_json(repo_root / LEANSTRAL_AUDIT_PATH),
    )
    verdict = build_xaman_testnet_assurance_verdict(bundle)
    markdown = render_xaman_testnet_assurance_verdict_markdown(bundle, verdict)

    _write_json(repo_root / BUNDLE_PATH, bundle)
    _write_json(repo_root / VERDICT_PATH, verdict)
    _write_text(repo_root / VERDICT_DOC_PATH, markdown)
    return bundle, verdict, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    args = parser.parse_args(argv)

    bundle, verdict, _markdown = generate(Path(args.repo_root).resolve())
    print(
        json.dumps(
            {
                'bundle_path': BUNDLE_PATH,
                'bundle_cid': bundle['artifact_cid'],
                'verdict_path': VERDICT_PATH,
                'verdict_cid': verdict['artifact_cid'],
                'verdict': verdict['verdict'],
                'doc_path': VERDICT_DOC_PATH,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
