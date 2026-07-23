from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.ops.security_verification.build_xaman_source_claim_coverage import (
    build_markdown_report,
    build_native_boundary_coverage,
    build_source_claim_map,
)


ROOT = Path(__file__).resolve().parents[4]
CLAIM_MAP_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/source-claim-map.json'
NATIVE_COVERAGE_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_source_claim_coverage.md'
MANIFEST_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'

PINNED_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
REPO_URL = 'https://github.com/XRPL-Labs/Xaman-App'

REQUIRED_BOUNDARIES = {
    'wallet_auth',
    'payload_review',
    'signing_decision',
    'deep_link',
    'qr',
    'network_selection',
    'receipt_consumer',
    'native_bridge',
}

REQUIRED_NOT_MODELED = {
    'vault_cryptography',
    'biometrics',
    'native_keystore_behavior',
    'backend_behavior',
}

REQUIRED_FACT_IDS = {
    'xaman-wallet-auth:fact:vault-access-is-through-native-module',
    'xaman-wallet-auth:fact:transaction-signing-preconditions-before-vault-overlay',
    'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
    'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
    'xaman-payload-lifecycle:fact:approval-enters-vault-signing-boundary',
    'xaman-payload-lifecycle:fact:qr-payload-reference-intake-fetches-and-routes-to-review',
    'xaman-payload-lifecycle:fact:deep-link-payload-reference-intake-fetches-and-routes-to-review',
    'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
    'xaman-xrpl-transaction:fact:signing-requires-fee-sequence-network-and-supported-type',
}

REQUIRED_FORMAL_CLAIMS = {
    'xaman-claim:software-custody-requires-vault-authentication',
    'xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
    'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
    'xaman-claim:client-replay-controls-exist-but-backend-single-use-is-blocking',
    'xaman-claim:network-binding-prevents-wrong-network-signing',
    'xaman-claim:backend-payload-service-is-trusted-not-proved',
    'xaman-claim:proof-consumer-must-reject-non-proved-results',
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


def _manifest_files() -> dict[str, dict[str, Any]]:
    return {entry['path']: entry for entry in _json(MANIFEST_PATH)['files']}


def test_xaman_source_claim_map_rebuilds_deterministically() -> None:
    checked_in = _json(CLAIM_MAP_PATH)
    rebuilt = build_source_claim_map(ROOT)

    assert rebuilt == checked_in
    _assert_cid(checked_in)


def test_xaman_native_boundary_coverage_rebuilds_deterministically() -> None:
    claim_map = _json(CLAIM_MAP_PATH)
    checked_in = _json(NATIVE_COVERAGE_PATH)
    rebuilt = build_native_boundary_coverage(ROOT, claim_map)

    assert rebuilt == checked_in
    _assert_cid(checked_in)


def test_xaman_source_claim_map_schema_source_pin_and_summary() -> None:
    claim_map = _json(CLAIM_MAP_PATH)

    assert claim_map['schema_version'] == 'xaman-source-claim-map/v1'
    assert claim_map['task_id'] == 'PORTAL-CXTP-145'
    assert claim_map['source']['repo_url'] == REPO_URL
    assert claim_map['source']['commit_sha'] == PINNED_COMMIT
    assert claim_map['source']['public_source_only'] is True
    assert claim_map['source']['upstream_drift_detected'] is False
    assert claim_map['source']['proof_corpus_changed_by_refresh'] is False
    assert claim_map['overall_status'] == 'blocked'
    assert claim_map['production_release_blocked'] is True
    assert claim_map['summary']['modeled_source_claim_count'] == 54
    assert claim_map['summary']['formal_claim_binding_count'] == 10
    assert claim_map['summary']['modeled_claims_missing_immutable_source_count'] == 0
    assert claim_map['summary']['production_release_approval_count'] == 0


def test_xaman_source_claim_map_covers_required_boundary_families() -> None:
    claim_map = _json(CLAIM_MAP_PATH)
    matrix = claim_map['coverage_matrix']

    assert set(claim_map['required_boundary_status']) == REQUIRED_BOUNDARIES
    assert set(matrix) >= REQUIRED_BOUNDARIES
    assert all(
        claim_map['required_boundary_status'][boundary] == 'COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS'
        for boundary in REQUIRED_BOUNDARIES
    )

    assert matrix['wallet_auth']['modeled_source_claim_count'] >= 10
    assert matrix['payload_review']['modeled_source_claim_count'] >= 8
    assert matrix['signing_decision']['modeled_source_claim_count'] >= 5
    assert matrix['deep_link']['modeled_source_claim_count'] >= 1
    assert matrix['qr']['modeled_source_claim_count'] >= 1
    assert matrix['network_selection']['modeled_source_claim_count'] >= 2
    assert matrix['receipt_consumer']['formal_claim_count'] == 1
    assert matrix['native_bridge']['modeled_source_claim_count'] >= 1


def test_xaman_modeled_source_claims_have_immutable_public_source_locations() -> None:
    claim_map = _json(CLAIM_MAP_PATH)
    manifest_files = _manifest_files()
    by_id = {entry['claim_id']: entry for entry in claim_map['modeled_source_claims']}

    assert REQUIRED_FACT_IDS <= set(by_id)
    for claim in claim_map['modeled_source_claims']:
        assert claim['status'] == 'MODELED'
        assert claim['public_source_support'] == 'source_supported'
        assert claim['immutable_public_source_location_count'] >= 1, claim['claim_id']
        assert claim['evidence_locations'], claim['claim_id']
        for location in claim['evidence_locations']:
            assert location['kind'] == 'source_code'
            assert location['repo_url'] == REPO_URL
            assert location['commit_sha'] == PINNED_COMMIT
            assert location['review_status'] == 'reviewed'
            assert location['line_start'] >= 1
            assert location['line_end'] >= location['line_start']
            assert location['path'] in manifest_files
            assert location['sha256'] == manifest_files[location['path']]['sha256']
            assert location['git_blob_sha1'] == manifest_files[location['path']]['git_blob_sha1']
            assert location['url'].startswith(f'{REPO_URL}/blob/{PINNED_COMMIT}/')


def test_xaman_formal_claim_bindings_include_source_facts_and_receipt_consumer() -> None:
    claim_map = _json(CLAIM_MAP_PATH)
    formal = {entry['claim_id']: entry for entry in claim_map['formal_claim_bindings']}

    assert REQUIRED_FORMAL_CLAIMS <= set(formal)
    assert all(entry['production_release_approval'] is False for entry in formal.values())
    assert all(entry['immutable_location_count'] >= 1 for entry in formal.values())

    receipt = formal['xaman-claim:proof-consumer-must-reject-non-proved-results']
    assert receipt['boundary_family'] == 'receipt_consumer'
    assert receipt['status'] == 'POLICY_DEFINED_NOT_YET_KERNEL_PROVED'
    assert receipt['assumptions'] == ['xaman-assumption:proof-consumer-kernel-validation']
    assert {
        location['kind'] for location in receipt['evidence_locations']
    } >= {
        'policy_source',
        'proof_consumer_kernel_source',
    }

    proof_binding = claim_map['proof_consumer_binding']
    assert proof_binding['accepted_statuses'] == ['PROVED']
    assert set(proof_binding['rejected_statuses']) == {'DISPROVED', 'UNKNOWN', 'NOT_MODELED'}
    assert proof_binding['production_release_blocked'] is True


def test_xaman_required_native_backend_boundaries_remain_not_modeled() -> None:
    claim_map = _json(CLAIM_MAP_PATH)
    native = _json(NATIVE_COVERAGE_PATH)

    assert set(claim_map['required_not_modeled_boundaries']) == REQUIRED_NOT_MODELED
    assert all(status == 'NOT_MODELED' for status in claim_map['required_not_modeled_boundaries'].values())
    assert set(native['required_not_modeled_boundaries']) == REQUIRED_NOT_MODELED
    assert all(status == 'NOT_MODELED' for status in native['required_not_modeled_boundaries'].values())

    not_modeled_claims = {entry['claim_id']: entry for entry in claim_map['not_modeled_claims']}
    assert not_modeled_claims[
        'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation'
    ]['status'] == 'NOT_MODELED'
    assert not_modeled_claims[
        'xaman-wallet-auth:gap:biometric-native-security-properties'
    ]['status'] == 'NOT_MODELED'
    assert not_modeled_claims[
        'xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use'
    ]['status'] == 'NOT_MODELED'


def test_xaman_native_boundary_coverage_records_bridge_and_blockers() -> None:
    native = _json(NATIVE_COVERAGE_PATH)
    by_id = {entry['boundary_id']: entry for entry in native['boundaries']}

    assert native['schema_version'] == 'xaman-native-boundary-coverage/v1'
    assert native['task_id'] == 'PORTAL-CXTP-145'
    assert native['overall_status'] == 'blocked'
    assert native['production_release_blocked'] is True
    assert native['security_decision'] == 'BLOCK_NATIVE_BACKEND_BOUNDARY_CLAIMS_WITHOUT_SOURCE_SUPPORTED_EVIDENCE'
    assert native['summary']['production_release_approval_count'] == 0

    bridge = by_id['xaman-native-boundary:vault-manager-js-bridge']
    assert bridge['status'] == 'MODELED_JS_BRIDGE_NATIVE_IMPLEMENTATION_NOT_MODELED'
    assert 'xaman-wallet-auth:fact:vault-access-is-through-native-module' in bridge['source_claim_ids']
    assert 'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation' in bridge['source_claim_ids']

    assert by_id['xaman-native-boundary:vault-cryptography']['status'] == 'NOT_MODELED'
    assert by_id['xaman-native-boundary:biometric-policy']['status'] == 'NOT_MODELED'
    assert by_id['xaman-native-boundary:native-keystore-behavior']['status'] == 'NOT_MODELED'
    assert by_id['xaman-native-boundary:backend-payload-service']['status'] == 'NOT_MODELED'
    assert by_id['xaman-native-boundary:native-firebase-packaging']['status'] == 'BLOCKED_NATIVE_PACKAGING_PRESENT'


def test_xaman_source_claim_coverage_document_tracks_generated_artifacts() -> None:
    claim_map = _json(CLAIM_MAP_PATH)
    native = _json(NATIVE_COVERAGE_PATH)
    rebuilt = build_markdown_report(claim_map, native)
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert rebuilt == doc
    assert 'PORTAL-CXTP-145' in doc
    assert 'source-claim-map.json' in doc
    assert 'native-boundary-coverage.json' in doc
    assert 'Vault cryptography, biometrics, native keystore behavior, and backend behavior' in doc
    assert '`NOT_MODELED`' in doc
