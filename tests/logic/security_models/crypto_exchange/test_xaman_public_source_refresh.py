from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.ops.security_verification.build_xaman_public_source_assessment import (
    build_assessment,
    build_public_source_refresh,
)


ROOT = Path(__file__).resolve().parents[4]
REFRESH_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/public-source-refresh.json'
ASSESSMENT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/public-source-assessment.json'

PINNED_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
REPO_URL = 'https://github.com/XRPL-Labs/Xaman-App'

EXPECTED_LOCKFILES = {
    'Gemfile.lock': '584c22420eb3969297a9ec35a946c8a809ca8f421ea1db14cff1c323738342a4',
    'ios/Podfile.lock': 'cc3f2f4efc8d7efcc3435ef25c16702c512e656df549edaa34f8ce1797c5e886',
    'package-lock.json': 'f27be60a558a178d6fefec5fb0cab13ff4c196d13b96c3406d600f32277b458a',
}

REQUIRED_UNMODELED_IDS = {
    'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation',
    'xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use',
    'xaman-xrpl-transaction:gap:trustset-offercreate-signerlistset-validation-is-todo',
    'xaman-runtime:gap:real-device-trace-bundle-missing',
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _assert_cid(payload: dict[str, Any]) -> None:
    body = dict(payload)
    artifact_cid = body.pop('artifact_cid')
    assert artifact_cid == _canonical_sha256(body)


def test_public_source_refresh_rebuilds_deterministically() -> None:
    checked_in = _json(REFRESH_PATH)
    rebuilt = build_public_source_refresh(ROOT)

    assert rebuilt == checked_in
    _assert_cid(checked_in)


def test_public_source_refresh_revalidates_pin_without_repinning_corpus() -> None:
    refresh = _json(REFRESH_PATH)

    assert refresh['schema_version'] == 'xaman-public-source-refresh/v1'
    assert refresh['task_id'] == 'PORTAL-CXTP-144'
    assert refresh['source_pin']['repo_url'] == REPO_URL
    assert refresh['source_pin']['commit_sha'] == PINNED_COMMIT
    assert refresh['source_pin']['requested_ref'] == PINNED_COMMIT
    assert refresh['source_pin']['exact_commit_required'] is True
    assert refresh['source_pin']['proof_corpus_pin_preserved'] is True
    assert refresh['source_pin']['proof_corpus_changed_by_refresh'] is False

    drift = refresh['upstream_drift']
    assert drift['method'].startswith('git ls-remote https://github.com/XRPL-Labs/Xaman-App')
    assert drift['default_branch'] == 'master'
    assert drift['main_ref_present'] is False
    assert drift['head_commit'] == PINNED_COMMIT
    assert drift['master_commit'] == PINNED_COMMIT
    assert drift['head_matches_pin'] is True
    assert drift['master_matches_pin'] is True
    assert drift['drift_detected'] is False
    assert drift['action'] == 'record_no_drift_and_keep_existing_proof_corpus'
    assert drift['latest_version_tag']['name'] == 'v3.3.0'


def test_public_source_refresh_records_lockfiles_and_disclosure_path() -> None:
    refresh = _json(REFRESH_PATH)

    lockfiles = {
        entry['path']: entry['sha256']
        for entry in refresh['lockfile_baseline']['dependency_lockfiles']
    }
    assert lockfiles == EXPECTED_LOCKFILES
    assert refresh['lockfile_baseline']['required_dependency_lockfiles'] == ['package-lock.json']
    assert refresh['lockfile_baseline']['all_required_lockfiles_present'] is True

    disclosure = refresh['responsible_disclosure']
    assert disclosure['primary_path'] == 'RESPONSIBLE-DISCLOSURE.md'
    assert disclosure['primary_path_present'] is True
    assert disclosure['required_paths'] == ['RESPONSIBLE-DISCLOSURE.md']
    assert {
        entry['path'] for entry in disclosure['security_disclosure_files']
    } == {
        'RESPONSIBLE-DISCLOSURE.md',
        'android/app/src/main/assets/security.txt',
        'ios/security.txt',
    }


def test_public_source_refresh_records_coverage_and_unmodeled_domains() -> None:
    refresh = _json(REFRESH_PATH)
    coverage = refresh['source_coverage']

    assert coverage['analysis_mode'] == 'manifest_only'
    assert coverage['aggregate_sha256'] == '575de917579a82d28998ab1c6b8b0946e45926846eac1418b89afcfb2157a460'
    assert coverage['summary']['manifest_files'] == 3444
    assert coverage['summary']['security_relevant_files'] == 711
    assert coverage['summary']['parsed_files'] == 0
    assert coverage['coverage_gap_count'] == 721
    assert coverage['blocking_gap_count'] == 653
    assert coverage['parsed_source_available'] is False
    assert set(coverage['categories_with_gaps']) == {
        'auth_component',
        'e2e_flow',
        'ledger',
        'path_alias',
        'payload',
        'service',
        'store',
        'vault',
    }

    domains = refresh['known_unmodeled_domains']
    assert refresh['acceptance_summary']['known_unmodeled_domain_count'] == 17
    assert REQUIRED_UNMODELED_IDS <= {entry['id'] for entry in domains}
    assert all(entry['status'] == 'NOT_MODELED' for entry in domains)
    assert all(entry['severity'].startswith('blocking') for entry in domains)


def test_public_source_refresh_records_public_build_digests_and_testnet_scope() -> None:
    refresh = _json(REFRESH_PATH)
    digests = refresh['public_build_digests']
    by_kind = {}
    for entry in digests:
        by_kind.setdefault(entry['kind'], []).append(entry)

    assert refresh['acceptance_summary']['public_build_digest_count'] == 12
    assert by_kind['testnet_debug_verifier_apk'][0]['sha256'] == (
        'c22cd33b580dd0ecd8b8c5529b42169dccb79676ac396cda8af448d31810a41d'
    )
    assert by_kind['testnet_transaction_trial_apk'][0]['digest_matches_device_report'] is True
    assert by_kind['firebase_disabled_testnet_build_kit_manifest'][0]['sha256'] == (
        '638c63ad73d0dc7756e058c49bf425c52add7588961dc4e85b4802bab359002f'
    )
    assert len(by_kind['release_r8_verifier_apk']) == 5
    assert {
        entry['file'] for entry in by_kind['release_r8_verifier_apk']
    } == {
        'app-universal-release.apk',
        'app-arm64-v8a-release.apk',
        'app-armeabi-v7a-release.apk',
        'app-x86-release.apk',
        'app-x86_64-release.apk',
    }
    assert all(entry['production_signing_claim'] is False for entry in by_kind['release_r8_verifier_apk'])

    scope = refresh['testnet_scope']
    assert scope['network'] == 'XRPL Testnet'
    assert scope['network_id'] == 1
    assert scope['production_security_result'] is False
    assert scope['not_a_production_security_result'] is True
    assert scope['production_usable'] is False
    assert scope['real_assets_allowed'] is False
    assert scope['fresh_testnet_accounts_only'] is True
    assert scope['assurance_verdict'] == 'TESTNET_SCOPE_NOT_SECURE'


def test_public_source_assessment_embeds_refresh_baseline_and_stays_blocked() -> None:
    checked_in = _json(ASSESSMENT_PATH)
    rebuilt = build_assessment(ROOT)

    assert rebuilt == checked_in
    _assert_cid(checked_in)
    assert checked_in['task_id'] == 'PORTAL-CXTP-144'
    assert checked_in['source']['repo_url'] == REPO_URL
    assert checked_in['source']['commit_sha'] == PINNED_COMMIT
    assert checked_in['source']['refresh_path'] == (
        'security_ir_artifacts/corpora/xaman-app/public-source-refresh.json'
    )
    assert checked_in['source']['upstream_drift_detected'] is False
    assert checked_in['source']['proof_corpus_changed_by_refresh'] is False
    assert checked_in['refresh_baseline']['upstream_drift']['master_matches_pin'] is True
    assert checked_in['refresh_baseline']['public_build_digest_count'] == 12
    assert checked_in['refresh_baseline']['known_unmodeled_domain_count'] == 17

    assert checked_in['overall_status'] == 'blocked'
    assert checked_in['public_source_result'] == 'blocked_public_source_assessment'
    assert checked_in['security_decision'] == 'BLOCK_PUBLIC_SOURCE_ASSESSMENT_NOT_RELEASE_APPROVAL'
    assert checked_in['production_release_approval'] is False
    assert checked_in['production_release_blocked'] is True
