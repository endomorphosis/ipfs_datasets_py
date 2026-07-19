"""Tests for Xaman source-bounded gap remediation status."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_gap_remediation_status import (
    SCHEMA_VERSION,
    TASK_ID,
    build_gap_remediation_status,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
GAP_MANIFEST_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/final-gap-remediation-manifest.json'
SOLVER_PORTFOLIO_REPORT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json'
FUZZ_REPORT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json'
STATUS_REPORT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/gap-remediation-status.json'


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _build() -> dict:
    return build_gap_remediation_status(
        gap_manifest=_load(GAP_MANIFEST_PATH),
        solver_portfolio_report=_load(SOLVER_PORTFOLIO_REPORT_PATH),
        fuzz_report=_load(FUZZ_REPORT_PATH),
    )


def test_gap_remediation_status_summarizes_local_remediation_and_external_blockers() -> None:
    report = _build()

    assert report['schema_version'] == SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['overall_status'] == 'source_bounded_remediation_complete_with_external_blockers'
    assert report['security_decision'] == 'LOCAL_GAPS_REMEDIATED_PRODUCTION_STILL_BLOCKED'
    assert report['production_release_blocked'] is True
    assert report['testnet_assurance_promotion_allowed'] is False
    assert report['summary']['entry_count'] == 37
    assert report['summary']['local_remediated_count'] == 35
    assert report['summary']['external_blocked_count'] == 2
    assert report['summary']['solver_proved_claim_count'] == 0
    assert report['summary']['solver_fail_closed_claim_count'] == 12
    assert report['summary']['fuzz_counterexample_count'] == 25


def test_gap_remediation_status_preserves_fail_closed_blocker_actions() -> None:
    report = _build()
    blocked = {entry['entry_id']: entry for entry in report['blocked_entries']}

    assert set(blocked) == {
        'xaman-disproof:backend-double-use',
        'xaman-disproof:runtime-equivalence-missing',
    }
    assert all(entry['blocked_by'] == ['EXTERNAL_EVIDENCE_REQUIRED'] for entry in blocked.values())
    assert all(entry['proof_promotion_allowed'] is False for entry in blocked.values())
    assert any('backend payload-service evidence' in action for action in blocked['xaman-disproof:backend-double-use']['next_actions'])
    assert any('release-equivalent wallet path' in action for action in blocked['xaman-disproof:runtime-equivalence-missing']['next_actions'])


def test_gap_remediation_status_artifact_is_regenerable() -> None:
    checked_in = _load(STATUS_REPORT_PATH)
    generated = _build()

    assert generated == checked_in
    body = dict(generated)
    artifact_cid = body.pop('artifact_cid')
    assert artifact_cid == calculate_artifact_cid(body)
