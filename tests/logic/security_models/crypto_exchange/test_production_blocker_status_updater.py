"""Tests for PORTAL-CXTP-095 guarded production blocker status updater."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'update_production_blocker_status.py'
)
ARTIFACT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'production' / 'blocker-status-update-report.json'
PACKETS_PATH = REPO_ROOT / 'security_ir_artifacts' / 'production' / 'blocker-evidence-packets.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'production_blocker_status_updater.md'


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'update_production_blocker_status',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load production blocker status updater')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _minimal_packet() -> dict:
    return {
        'id': 'evidence-request:blocker-fixture',
        'source_packet_blocker_id': 'blocker:fixture',
        'source_blocker_status': 'blocked_missing_production_evidence',
        'source_task_id': 'PORTAL-CXTP-076',
        'required_production_evidence_domains': ['production_source', 'human_review'],
        'blocked_claim_ids': ['claim:fixture'],
        'evidence_requests': [
            {
                'domain': 'production_source',
                'evidence_bundle_category': 'source_snapshots',
                'expected_owner': 'mobile-appsec-source-owner',
                'accepted_review_statuses': ['human_reviewed', 'trusted_fixture'],
            },
            {
                'domain': 'human_review',
                'evidence_bundle_category': 'owner_signoff',
                'expected_owner': 'named-security-release-owner',
                'accepted_review_statuses': ['approved-owner-signoff'],
            },
        ],
    }


def _accepted_report() -> dict:
    return {
        'overall_status': 'pass',
        'production_release_blocked': False,
        'security_decision': 'PRODUCTION_EVIDENCE_BUNDLE_ACCEPTED',
        'blockers': [],
    }


def _accepted_bundle() -> dict:
    return {
        'bundle_id': 'fixture-bundle',
        'source_snapshots': [
            {
                'id': 'source',
                'owner': 'mobile-appsec-source-owner',
                'review_status': 'human_reviewed',
            }
        ],
        'owner_signoff': [
            {
                'id': 'signoff',
                'owner': 'named-security-release-owner',
                'decision': 'approved',
            }
        ],
        'solver_reports': [
            {
                'id': 'solver',
                'claim_id': 'claim:fixture',
                'outcome': 'prove',
            }
        ],
    }


def test_checked_in_artifact_preserves_blocked_production_state() -> None:
    payload = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert payload['schema_version'] == 'production-blocker-status-update/v1'
    assert payload['task_id'] == 'PORTAL-CXTP-095'
    assert payload['overall_status'] == 'blocked'
    assert payload['production_release_blocked'] is True
    assert payload['may_mark_production_secure'] is False
    assert 'PORTAL-CXTP-077' in payload['blocked_task_ids_preserved']
    assert payload['summary']['packet_count'] >= 0
    assert payload['summary']['status_update_allowed_count'] == 0
    assert payload['summary']['status_update_blocked_count'] == payload['summary']['packet_count']
    if payload['summary']['packet_count'] == 0:
        codes = {blocker['code'] for blocker in payload['blockers']}
        assert 'PACKETS_FILE_MISSING' in codes or 'PACKETS_ARRAY_MISSING' in codes


def test_missing_or_blocked_evidence_report_blocks_every_packet(tmp_path: Path) -> None:
    module = _load_script_module()
    packets = {'packets': [_minimal_packet()]}
    packets_path = tmp_path / 'packets.json'
    evidence_report_path = tmp_path / 'evidence-report.json'
    bundle_path = tmp_path / 'bundle.json'
    _write_json(packets_path, packets)
    _write_json(
        evidence_report_path,
        {
            'overall_status': 'blocked',
            'production_release_blocked': True,
            'security_decision': 'BLOCK_PRODUCTION_EVIDENCE_INTAKE',
            'blockers': [{'code': 'BUNDLE_FILE_MISSING'}],
        },
    )

    report = module.build_status_update_report(
        repo_root=tmp_path,
        packets_path=packets_path,
        evidence_report_path=evidence_report_path,
        evidence_bundle_path=bundle_path,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['summary']['status_update_allowed_count'] == 0
    update = report['status_updates'][0]
    codes = {blocker['code'] for blocker in update['blockers']}
    assert 'EVIDENCE_VALIDATION_REPORT_BLOCKED' in codes
    assert 'EVIDENCE_BUNDLE_UNAVAILABLE' in codes
    assert 'PACKET_BLOCKED_CLAIM_NOT_PROVED' in codes


def test_accepted_bundle_with_matching_packet_domains_allows_manual_candidate(tmp_path: Path) -> None:
    module = _load_script_module()
    packets_path = tmp_path / 'packets.json'
    evidence_report_path = tmp_path / 'report.json'
    bundle_path = tmp_path / 'bundle.json'
    _write_json(packets_path, {'packets': [_minimal_packet()]})
    _write_json(evidence_report_path, _accepted_report())
    _write_json(bundle_path, _accepted_bundle())

    report = module.build_status_update_report(
        repo_root=tmp_path,
        packets_path=packets_path,
        evidence_report_path=evidence_report_path,
        evidence_bundle_path=bundle_path,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'ready'
    assert report['production_release_blocked'] is False
    update = report['status_updates'][0]
    assert update['status_update_allowed'] is True
    assert update['proposed_status'] == 'evidence-accepted-pending-owner-close'
    assert update['may_mark_production_secure'] is False


def test_cli_writes_dry_run_report(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'out.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--dry-run',
            '--packets',
            PACKETS_PATH.relative_to(REPO_ROOT).as_posix(),
            '--out',
            out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['overall_status'] == 'blocked'
    assert report['summary']['dry_run'] is True


def test_document_explains_fail_closed_status_policy() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-095' in doc
    assert 'fail-closed' in doc
    assert 'security_ir_artifacts/production/blocker-status-update-report.json' in doc
    assert 'does not remove production blockers from the taskboard by itself' in doc
