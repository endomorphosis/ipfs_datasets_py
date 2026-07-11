#!/usr/bin/env python3
"""Build Xaman source-to-claim coverage artifacts.

The generated artifacts bind modeled Xaman claims to immutable source evidence
from the pinned public corpus. Native cryptography, biometrics, keystore, and
backend behavior are intentionally kept as NOT_MODELED unless a reviewed source
artifact supplies evidence for that exact boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
DEFAULT_CLAIM_MAP_OUT = CORPUS_DIR / 'source-claim-map.json'
DEFAULT_NATIVE_OUT = CORPUS_DIR / 'native-boundary-coverage.json'
DEFAULT_DOC_OUT = Path('docs/security_verification/xaman_source_claim_coverage.md')

SOURCE_MANIFEST_PATH = CORPUS_DIR / 'source-manifest.json'
SOURCE_COVERAGE_PATH = CORPUS_DIR / 'source-coverage.json'
PUBLIC_SOURCE_REFRESH_PATH = CORPUS_DIR / 'public-source-refresh.json'
PUBLIC_SOURCE_ASSESSMENT_PATH = CORPUS_DIR / 'public-source-assessment.json'
WALLET_AUTH_PATH = CORPUS_DIR / 'wallet-auth-facts.json'
PAYLOAD_LIFECYCLE_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'
XRPL_TRANSACTION_PATH = CORPUS_DIR / 'xrpl-transaction-facts.json'
SECURITY_CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'
PROOF_CONSUMER_REPORT_PATH = CORPUS_DIR / 'proof-kernel/proof-consumer-report.json'
PROOF_CONSUMER_KERNEL_PATH = CORPUS_DIR / 'proof-kernel/XamanReceipt.lean'
NATIVE_FIREBASE_REPORT_PATH = CORPUS_DIR / 'runtime/native-firebase-boundary-report.json'
RUNTIME_TRACE_REPORT_PATH = CORPUS_DIR / 'runtime-trace-report.json'
SECURITY_DECISION_POLICY_PATH = Path('security_ir_artifacts/policies/security-decision-policy.json')
OPTIONAL_SOLVER_REPORT_PATH = Path('security_ir_artifacts/environment/optional-solver-install-report.json')

TASK_ID = 'PORTAL-CXTP-145'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'

FACT_ARTIFACTS: tuple[tuple[str, str, Path], ...] = (
    ('wallet_auth', 'wallet-auth', WALLET_AUTH_PATH),
    ('payload_lifecycle', 'payload-lifecycle', PAYLOAD_LIFECYCLE_PATH),
    ('xrpl_transaction', 'xrpl-transaction', XRPL_TRANSACTION_PATH),
)

REQUIRED_BOUNDARY_FAMILIES = (
    'wallet_auth',
    'payload_review',
    'signing_decision',
    'deep_link',
    'qr',
    'network_selection',
    'receipt_consumer',
    'native_bridge',
)

REQUIRED_NOT_MODELED_BOUNDARIES = (
    'vault_cryptography',
    'biometrics',
    'native_keystore_behavior',
    'backend_behavior',
)

PAYLOAD_CATEGORY_TO_BOUNDARY = {
    'payload_creation': 'payload_review',
    'replay_control': 'payload_review',
    'expiration': 'payload_review',
    'push_intake': 'payload_review',
    'event_list_intake': 'payload_review',
    'review_ui': 'payload_review',
    'approval': 'signing_decision',
    'rejection': 'payload_review',
    'broadcast_boundary': 'payload_review',
    'deep_link_intake': 'deep_link',
    'qr_intake': 'qr',
    'network_binding': 'network_selection',
}

XRPL_CATEGORY_TO_BOUNDARY = {
    'fee_sequence_network': 'network_selection',
    'broadcast_submit': 'signing_decision',
}

CLAIM_CATEGORY_TO_BOUNDARY = {
    'custody': 'wallet_auth',
    'authentication': 'signing_decision',
    'payload_integrity': 'payload_review',
    'replay_prevention': 'payload_review',
    'network_binding': 'network_selection',
    'backend_trust': 'payload_review',
    'runtime_equivalence': 'native_bridge',
    'proof_consumer_policy': 'receipt_consumer',
    'transaction_semantics': 'signing_decision',
}

NOT_MODELED_BY_ID = {
    'vault_cryptography': 'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation',
    'biometrics': 'xaman-wallet-auth:gap:biometric-native-security-properties',
    'native_keystore_behavior': 'xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation',
    'backend_behavior': 'xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use',
}


def _load_json(repo_root: Path, path: Path) -> dict[str, Any]:
    return json.loads((repo_root / path).read_text(encoding='utf-8'))


def _sha256_file(repo_root: Path, path: Path) -> str:
    return 'sha256:' + hashlib.sha256((repo_root / path).read_bytes()).hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def _with_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body['artifact_cid'] = _canonical_sha256(body)
    return body


def _artifact_ref(repo_root: Path, path: Path, *, role: str) -> dict[str, Any]:
    payload = _load_json(repo_root, path)
    ref = {
        'role': role,
        'path': str(path),
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'sha256': _sha256_file(repo_root, path),
    }
    artifact_cid = payload.get('artifact_cid')
    if artifact_cid is not None:
        ref['artifact_cid'] = artifact_cid
    return ref


def _manifest_files(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {entry['path']: entry for entry in manifest['files']}


def _github_url(repo_url: str, commit_sha: str, path: str, line_start: int, line_end: int) -> str:
    return f'{repo_url}/blob/{commit_sha}/{path}#L{line_start}-L{line_end}'


def _source_location(
    *,
    evidence: Mapping[str, Any],
    manifest_files: Mapping[str, Mapping[str, Any]],
    repo_url: str,
    commit_sha: str,
) -> dict[str, Any]:
    path = evidence['path']
    location = {
        'kind': evidence['kind'],
        'repo_url': repo_url,
        'commit_sha': commit_sha,
        'path': path,
        'line_start': evidence.get('line_start'),
        'line_end': evidence.get('line_end'),
        'sha256': evidence.get('sha256'),
        'review_status': evidence.get('review_status'),
    }
    manifest_entry = manifest_files.get(path)
    if manifest_entry is not None:
        location['git_blob_sha1'] = manifest_entry.get('git_blob_sha1')
        location['git_mode'] = manifest_entry.get('git_mode')
        location['size_bytes'] = manifest_entry.get('size_bytes')
    if location['line_start'] is not None and location['line_end'] is not None:
        location['url'] = _github_url(
            repo_url,
            commit_sha,
            path,
            int(location['line_start']),
            int(location['line_end']),
        )
    if evidence.get('notes'):
        location['notes'] = evidence['notes']
    return {key: value for key, value in location.items() if value is not None}


def _artifact_location(repo_root: Path, path: Path, *, kind: str, line_start: int, line_end: int) -> dict[str, Any]:
    return {
        'kind': kind,
        'path': str(path),
        'line_start': line_start,
        'line_end': line_end,
        'sha256': _sha256_file(repo_root, path),
        'review_status': 'reviewed',
    }


def _find_line(repo_root: Path, path: Path, needle: str) -> int:
    text = (repo_root / path).read_text(encoding='utf-8')
    for line_number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return line_number
    return 1


def _source_boundary(source_model: str, category: str, fact_id: str) -> str:
    if source_model == 'wallet_auth':
        if category == 'vault_access':
            return 'native_bridge'
        return 'wallet_auth'
    if source_model == 'payload_lifecycle':
        return PAYLOAD_CATEGORY_TO_BOUNDARY.get(category, 'payload_review')
    if source_model == 'xrpl_transaction':
        return XRPL_CATEGORY_TO_BOUNDARY.get(category, 'signing_decision')
    return 'payload_review'


def _fact_index(payloads: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for payload in payloads:
        for fact in payload.get('modeled_facts', []):
            indexed[fact['id']] = fact
        for gap in payload.get('not_modeled_gaps', []):
            indexed[gap['id']] = gap
    return indexed


def _evidence_locations_for_entry(
    entry: Mapping[str, Any],
    *,
    manifest_files: Mapping[str, Mapping[str, Any]],
    repo_url: str,
    commit_sha: str,
) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for evidence in entry.get('evidence', []):
        if evidence.get('kind') == 'source_code':
            locations.append(
                _source_location(
                    evidence=evidence,
                    manifest_files=manifest_files,
                    repo_url=repo_url,
                    commit_sha=commit_sha,
                )
            )
    return locations


def _source_claims(
    *,
    manifest: Mapping[str, Any],
    fact_payloads: list[tuple[str, str, Path, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    repo_url = manifest['source']['repo_url']
    commit_sha = manifest['source']['commit_sha']
    manifest_files = _manifest_files(manifest)
    claims: list[dict[str, Any]] = []
    for source_model, claim_prefix, artifact_path, payload in fact_payloads:
        for fact in payload.get('modeled_facts', []):
            locations = _evidence_locations_for_entry(
                fact,
                manifest_files=manifest_files,
                repo_url=repo_url,
                commit_sha=commit_sha,
            )
            claims.append(
                {
                    'claim_id': fact['id'],
                    'boundary_family': _source_boundary(source_model, fact['category'], fact['id']),
                    'source_model': source_model,
                    'source_artifact': str(artifact_path),
                    'status': 'MODELED',
                    'public_source_support': 'source_supported',
                    'category': fact.get('category'),
                    'summary': fact.get('summary'),
                    'normalized_fact': fact.get('normalized_fact', {}),
                    'evidence_locations': locations,
                    'immutable_public_source_location_count': len(locations),
                    'source_fact_ids': [fact['id']],
                    'model_boundary': f'{claim_prefix}:{fact.get("category")}',
                }
            )
    return sorted(claims, key=lambda entry: entry['claim_id'])


def _not_modeled_claims(
    *,
    repo_root: Path,
    manifest: Mapping[str, Any],
    fact_payloads: list[tuple[str, str, Path, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    repo_url = manifest['source']['repo_url']
    commit_sha = manifest['source']['commit_sha']
    manifest_files = _manifest_files(manifest)
    claims: list[dict[str, Any]] = []
    for source_model, _claim_prefix, artifact_path, payload in fact_payloads:
        for gap in payload.get('not_modeled_gaps', []):
            source_locations = _evidence_locations_for_entry(
                gap,
                manifest_files=manifest_files,
                repo_url=repo_url,
                commit_sha=commit_sha,
            )
            artifact_locations = [
                _artifact_location(
                    repo_root,
                    artifact_path,
                    kind='source_model_artifact',
                    line_start=1,
                    line_end=1,
                )
            ]
            claims.append(
                {
                    'claim_id': gap['id'],
                    'boundary_family': _source_boundary(source_model, gap.get('category', ''), gap['id']),
                    'source_model': source_model,
                    'source_artifact': str(artifact_path),
                    'status': gap.get('status', 'NOT_MODELED'),
                    'public_source_support': 'not_modeled_from_public_source_gap',
                    'category': gap.get('category'),
                    'severity': gap.get('severity', 'blocking'),
                    'summary': gap.get('summary'),
                    'required_evidence_to_model': gap.get('required_evidence_to_model', []),
                    'evidence_locations': source_locations + artifact_locations,
                    'immutable_public_source_location_count': len(source_locations),
                }
            )
    return sorted(claims, key=lambda entry: entry['claim_id'])


def _formal_claim_bindings(
    *,
    repo_root: Path,
    security_claims: Mapping[str, Any],
    fact_payloads: list[tuple[str, str, Path, Mapping[str, Any]]],
    source_claims: list[Mapping[str, Any]],
    not_modeled_claims: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    indexed_facts = _fact_index(payload for _model, _prefix, _path, payload in fact_payloads)
    indexed_claims = {claim['claim_id']: claim for claim in source_claims + not_modeled_claims}
    bindings: list[dict[str, Any]] = []
    for claim in security_claims['claims']:
        fact_ids: list[str] = []
        artifact_locations: list[dict[str, Any]] = []
        for evidence in claim.get('evidence', []):
            fact_ids.extend(evidence.get('fact_ids', []))
            path = evidence.get('path')
            if path:
                artifact_path = Path(path)
                if (repo_root / artifact_path).exists():
                    artifact_locations.append(
                        _artifact_location(
                            repo_root,
                            artifact_path,
                            kind=evidence.get('kind', 'artifact'),
                            line_start=1,
                            line_end=1,
                        )
                    )

        locations: list[dict[str, Any]] = []
        for fact_id in fact_ids:
            source_claim = indexed_claims.get(fact_id)
            if source_claim is not None:
                locations.extend(source_claim.get('evidence_locations', []))

        if claim['id'] == 'xaman-claim:proof-consumer-must-reject-non-proved-results':
            policy_line = _find_line(repo_root, SECURITY_DECISION_POLICY_PATH, 'NOT_MODELED')
            kernel_line = _find_line(repo_root, PROOF_CONSUMER_KERNEL_PATH, 'def canAccept')
            locations.extend(
                [
                    _artifact_location(
                        repo_root,
                        SECURITY_DECISION_POLICY_PATH,
                        kind='policy_source',
                        line_start=policy_line,
                        line_end=policy_line,
                    ),
                    _artifact_location(
                        repo_root,
                        PROOF_CONSUMER_KERNEL_PATH,
                        kind='proof_consumer_kernel_source',
                        line_start=kernel_line,
                        line_end=kernel_line,
                    ),
                ]
            )
            if (repo_root / OPTIONAL_SOLVER_REPORT_PATH).exists():
                locations.append(
                    _artifact_location(
                        repo_root,
                        OPTIONAL_SOLVER_REPORT_PATH,
                        kind='solver_environment_report',
                        line_start=1,
                        line_end=1,
                    )
                )

        bindings.append(
            {
                'claim_id': claim['id'],
                'boundary_family': CLAIM_CATEGORY_TO_BOUNDARY.get(claim.get('category'), 'payload_review'),
                'category': claim.get('category'),
                'status': claim.get('status'),
                'summary': claim.get('summary'),
                'assumptions': claim.get('assumptions', []),
                'release_policy': claim.get('release_policy'),
                'source_fact_ids': fact_ids,
                'source_fact_statuses': {
                    fact_id: indexed_facts.get(fact_id, {}).get('status', 'MISSING_SOURCE_FACT')
                    for fact_id in fact_ids
                },
                'evidence_locations': locations + artifact_locations,
                'immutable_location_count': len(locations + artifact_locations),
                'production_release_approval': False,
                'consumer_rule': 'block_unless_claim_is_proved_and_all_assumptions_are_cleared',
            }
        )
    return sorted(bindings, key=lambda entry: entry['claim_id'])


def _coverage_matrix(
    source_claims: Iterable[Mapping[str, Any]],
    formal_claims: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    matrix: dict[str, dict[str, Any]] = {
        family: {
            'boundary_family': family,
            'modeled_source_claim_ids': [],
            'formal_claim_ids': [],
            'status': 'NO_MODELED_CLAIMS',
        }
        for family in REQUIRED_BOUNDARY_FAMILIES
    }
    for claim in source_claims:
        family = claim['boundary_family']
        matrix.setdefault(
            family,
            {
                'boundary_family': family,
                'modeled_source_claim_ids': [],
                'formal_claim_ids': [],
                'status': 'NO_MODELED_CLAIMS',
            },
        )
        matrix[family]['modeled_source_claim_ids'].append(claim['claim_id'])
    for claim in formal_claims:
        family = claim['boundary_family']
        matrix.setdefault(
            family,
            {
                'boundary_family': family,
                'modeled_source_claim_ids': [],
                'formal_claim_ids': [],
                'status': 'NO_MODELED_CLAIMS',
            },
        )
        matrix[family]['formal_claim_ids'].append(claim['claim_id'])

    for entry in matrix.values():
        if entry['modeled_source_claim_ids'] or entry['formal_claim_ids']:
            entry['status'] = 'COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS'
        entry['modeled_source_claim_count'] = len(entry['modeled_source_claim_ids'])
        entry['formal_claim_count'] = len(entry['formal_claim_ids'])
    return dict(sorted(matrix.items()))


def _native_boundary(
    boundary_id: str,
    *,
    title: str,
    status: str,
    category: str,
    summary: str,
    source_claim_ids: Iterable[str],
    evidence_locations: Iterable[Mapping[str, Any]],
    required_evidence_to_model: Iterable[str],
    source_support: str,
) -> dict[str, Any]:
    locations = list(evidence_locations)
    return {
        'boundary_id': boundary_id,
        'title': title,
        'category': category,
        'status': status,
        'summary': summary,
        'source_claim_ids': sorted(source_claim_ids),
        'evidence_locations': locations,
        'evidence_location_count': len(locations),
        'required_evidence_to_model': list(required_evidence_to_model),
        'public_source_support': source_support,
        'production_release_approval': False,
    }


def _native_boundary_coverage(
    *,
    repo_root: Path,
    source_claim_map: Mapping[str, Any],
    native_firebase_report: Mapping[str, Any],
) -> dict[str, Any]:
    source_claims = {entry['claim_id']: entry for entry in source_claim_map['modeled_source_claims']}
    not_modeled = {entry['claim_id']: entry for entry in source_claim_map['not_modeled_claims']}

    vault_bridge = source_claims['xaman-wallet-auth:fact:vault-access-is-through-native-module']
    biometric_gap = not_modeled['xaman-wallet-auth:gap:biometric-native-security-properties']
    vault_gap = not_modeled['xaman-wallet-auth:gap:native-vault-manager-cryptographic-implementation']
    backend_gap = not_modeled['xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use']
    intake_gap = not_modeled['xaman-payload-lifecycle:gap:string-decoder-and-native-intake-integrity']
    signing_gap = not_modeled['xaman-wallet-auth:gap:third-party-signing-library-correctness']

    boundaries = [
        _native_boundary(
            'xaman-native-boundary:vault-manager-js-bridge',
            title='VaultManagerModule JavaScript bridge',
            status='MODELED_JS_BRIDGE_NATIVE_IMPLEMENTATION_NOT_MODELED',
            category='native_bridge',
            summary='The TypeScript vault facade calls VaultManagerModule, but the Android/iOS native implementation is outside the public source model.',
            source_claim_ids=[vault_bridge['claim_id'], vault_gap['claim_id']],
            evidence_locations=vault_bridge['evidence_locations'] + vault_gap['evidence_locations'],
            required_evidence_to_model=vault_gap['required_evidence_to_model'],
            source_support='js_bridge_source_supported_native_impl_not_modeled',
        ),
        _native_boundary(
            'xaman-native-boundary:vault-cryptography',
            title='Vault cryptography',
            status='NOT_MODELED',
            category='vault_cryptography',
            summary='Cipher mode, hardware backing, key migration, keychain/keystore accessibility, and memory handling are not proved by the TypeScript facade.',
            source_claim_ids=[vault_gap['claim_id']],
            evidence_locations=vault_gap['evidence_locations'],
            required_evidence_to_model=vault_gap['required_evidence_to_model'],
            source_support='not_modeled_no_native_crypto_source',
        ),
        _native_boundary(
            'xaman-native-boundary:biometric-policy',
            title='Native biometric policy',
            status='NOT_MODELED',
            category='biometrics',
            summary='The app models calls into the biometric helper, not platform prompt policy, enrollment binding, secure-enclave behavior, or spoof resistance.',
            source_claim_ids=[biometric_gap['claim_id']],
            evidence_locations=biometric_gap['evidence_locations'],
            required_evidence_to_model=biometric_gap['required_evidence_to_model'],
            source_support='not_modeled_no_native_biometric_source',
        ),
        _native_boundary(
            'xaman-native-boundary:native-keystore-behavior',
            title='Native keystore/keychain behavior',
            status='NOT_MODELED',
            category='native_keystore_behavior',
            summary='Native keychain and Android keystore storage class, accessibility, hardware-backed settings, and migration behavior are not modeled.',
            source_claim_ids=[vault_gap['claim_id']],
            evidence_locations=vault_gap['evidence_locations'],
            required_evidence_to_model=vault_gap['required_evidence_to_model'],
            source_support='not_modeled_no_keystore_keychain_source',
        ),
        _native_boundary(
            'xaman-native-boundary:qr-camera-and-os-link-dispatch',
            title='QR camera and OS deep-link dispatch',
            status='NOT_MODELED',
            category='native_intake',
            summary='Client dispatch after decoder output is modeled, but native camera parsing, OS link dispatch, clipboard, and decoder correctness are not proved.',
            source_claim_ids=[intake_gap['claim_id']],
            evidence_locations=intake_gap['evidence_locations'],
            required_evidence_to_model=intake_gap['required_evidence_to_model'],
            source_support='not_modeled_native_intake_integrity_gap',
        ),
        _native_boundary(
            'xaman-native-boundary:third-party-signing-and-tangem',
            title='Third-party signing libraries and Tangem SDK',
            status='NOT_MODELED',
            category='signing_cryptography',
            summary='Source facts record when signing libraries are called, but do not prove accountlib signing correctness, Tangem firmware behavior, or SDK attestation.',
            source_claim_ids=[signing_gap['claim_id']],
            evidence_locations=signing_gap['evidence_locations'],
            required_evidence_to_model=signing_gap['required_evidence_to_model'],
            source_support='not_modeled_third_party_signing_correctness_gap',
        ),
        _native_boundary(
            'xaman-native-boundary:backend-payload-service',
            title='Backend payload service behavior',
            status='NOT_MODELED',
            category='backend_behavior',
            summary='Client fetch, validate, patch, and reject calls are modeled, but backend authorization, atomic single-use, replay races, and PATCH conflict behavior are not proved.',
            source_claim_ids=[backend_gap['claim_id']],
            evidence_locations=backend_gap['evidence_locations'],
            required_evidence_to_model=backend_gap['required_evidence_to_model'],
            source_support='not_modeled_no_backend_source_or_formal_contract',
        ),
    ]

    firebase_line = _find_line(repo_root, NATIVE_FIREBASE_REPORT_PATH, 'native_firebase_fully_disabled')
    boundaries.append(
        _native_boundary(
            'xaman-native-boundary:native-firebase-packaging',
            title='Native Firebase packaging',
            status='BLOCKED_NATIVE_PACKAGING_PRESENT',
            category='native_packaging',
            summary=native_firebase_report.get('boundary_statement', 'Native Firebase packaging remains blocked.'),
            source_claim_ids=[],
            evidence_locations=[
                _artifact_location(
                    repo_root,
                    NATIVE_FIREBASE_REPORT_PATH,
                    kind='native_boundary_report',
                    line_start=firebase_line,
                    line_end=firebase_line,
                )
            ],
            required_evidence_to_model=[
                'APK with native Firebase manifest components removed',
                'startup trace proving no native Firebase initialization',
            ],
            source_support='runtime_apk_boundary_report_blocks_full_disable_claim',
        )
    )

    by_required = {
        'vault_cryptography': 'xaman-native-boundary:vault-cryptography',
        'biometrics': 'xaman-native-boundary:biometric-policy',
        'native_keystore_behavior': 'xaman-native-boundary:native-keystore-behavior',
        'backend_behavior': 'xaman-native-boundary:backend-payload-service',
    }
    required_statuses = {
        name: next(entry['status'] for entry in boundaries if entry['boundary_id'] == boundary_id)
        for name, boundary_id in by_required.items()
    }
    payload = {
        'schema_version': 'xaman-native-boundary-coverage/v1',
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'source_claim_map_path': str(DEFAULT_CLAIM_MAP_OUT),
        'inputs': [
            _artifact_ref(repo_root, NATIVE_FIREBASE_REPORT_PATH, role='native_firebase_boundary_report'),
            _artifact_ref(repo_root, PUBLIC_SOURCE_REFRESH_PATH, role='public_source_refresh'),
        ],
        'coverage_policy': {
            'native_crypto_requires_native_source_or_vendor_evidence': True,
            'backend_behavior_requires_backend_source_or_formal_contract': True,
            'not_modeled_blocks_production_release': True,
        },
        'required_not_modeled_boundaries': required_statuses,
        'boundaries': sorted(boundaries, key=lambda entry: entry['boundary_id']),
        'summary': {
            'boundary_count': len(boundaries),
            'not_modeled_count': sum(1 for entry in boundaries if entry['status'] == 'NOT_MODELED'),
            'modeled_js_bridge_count': sum(
                1 for entry in boundaries if entry['status'] == 'MODELED_JS_BRIDGE_NATIVE_IMPLEMENTATION_NOT_MODELED'
            ),
            'blocked_native_packaging_count': sum(
                1 for entry in boundaries if entry['status'] == 'BLOCKED_NATIVE_PACKAGING_PRESENT'
            ),
            'required_not_modeled_count': len(required_statuses),
            'production_release_approval_count': 0,
        },
        'overall_status': 'blocked',
        'security_decision': 'BLOCK_NATIVE_BACKEND_BOUNDARY_CLAIMS_WITHOUT_SOURCE_SUPPORTED_EVIDENCE',
        'production_release_blocked': True,
    }
    return _with_artifact_cid(payload)


def build_source_claim_map(repo_root: Path) -> dict[str, Any]:
    manifest = _load_json(repo_root, SOURCE_MANIFEST_PATH)
    refresh = _load_json(repo_root, PUBLIC_SOURCE_REFRESH_PATH)
    assessment = _load_json(repo_root, PUBLIC_SOURCE_ASSESSMENT_PATH)
    security_claims = _load_json(repo_root, SECURITY_CLAIMS_PATH)
    proof_consumer = _load_json(repo_root, PROOF_CONSUMER_REPORT_PATH)

    fact_payloads = [
        (source_model, claim_prefix, artifact_path, _load_json(repo_root, artifact_path))
        for source_model, claim_prefix, artifact_path in FACT_ARTIFACTS
    ]
    modeled_claims = _source_claims(manifest=manifest, fact_payloads=fact_payloads)
    not_modeled_claims = _not_modeled_claims(
        repo_root=repo_root,
        manifest=manifest,
        fact_payloads=fact_payloads,
    )
    formal_claims = _formal_claim_bindings(
        repo_root=repo_root,
        security_claims=security_claims,
        fact_payloads=fact_payloads,
        source_claims=modeled_claims,
        not_modeled_claims=not_modeled_claims,
    )
    coverage_matrix = _coverage_matrix(modeled_claims, formal_claims)

    missing_evidence = [
        claim['claim_id']
        for claim in modeled_claims
        if claim['status'] == 'MODELED' and claim['immutable_public_source_location_count'] == 0
    ]
    required_boundary_status = {
        family: coverage_matrix[family]['status']
        for family in REQUIRED_BOUNDARY_FAMILIES
    }
    required_not_modeled = {
        name: next(
            claim['status']
            for claim in not_modeled_claims
            if claim['claim_id'] == gap_id
        )
        for name, gap_id in NOT_MODELED_BY_ID.items()
    }
    payload = {
        'schema_version': 'xaman-source-claim-map/v1',
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'source': {
            'repo_url': manifest['source']['repo_url'],
            'commit_sha': manifest['source']['commit_sha'],
            'requested_ref': manifest['source']['requested_ref'],
            'manifest_path': str(SOURCE_MANIFEST_PATH),
            'manifest_sha256': _sha256_file(repo_root, SOURCE_MANIFEST_PATH),
            'manifest_aggregate_sha256': manifest['reproducibility']['aggregate_sha256'],
            'coverage_path': str(SOURCE_COVERAGE_PATH),
            'coverage_aggregate_sha256': refresh['source_coverage']['aggregate_sha256'],
            'public_source_only': True,
            'upstream_drift_detected': refresh['upstream_drift']['drift_detected'],
            'proof_corpus_changed_by_refresh': refresh['source_pin']['proof_corpus_changed_by_refresh'],
        },
        'inputs': [
            _artifact_ref(repo_root, SOURCE_MANIFEST_PATH, role='source_manifest'),
            _artifact_ref(repo_root, SOURCE_COVERAGE_PATH, role='source_coverage'),
            _artifact_ref(repo_root, PUBLIC_SOURCE_REFRESH_PATH, role='public_source_refresh'),
            _artifact_ref(repo_root, PUBLIC_SOURCE_ASSESSMENT_PATH, role='public_source_assessment'),
            _artifact_ref(repo_root, WALLET_AUTH_PATH, role='wallet_auth_facts'),
            _artifact_ref(repo_root, PAYLOAD_LIFECYCLE_PATH, role='payload_lifecycle_facts'),
            _artifact_ref(repo_root, XRPL_TRANSACTION_PATH, role='xrpl_transaction_facts'),
            _artifact_ref(repo_root, SECURITY_CLAIMS_PATH, role='security_claims'),
            _artifact_ref(repo_root, PROOF_CONSUMER_REPORT_PATH, role='proof_consumer_report'),
        ],
        'mapping_policy': {
            'immutable_public_source_locations_required_for_modeled_source_claims': True,
            'source_locations_must_include_commit_path_line_and_sha256': True,
            'formal_claims_with_non_proved_status_block_release': True,
            'vault_cryptography_biometrics_keystore_backend_default': 'NOT_MODELED',
            'production_release_approval_allowed': False,
        },
        'coverage_matrix': coverage_matrix,
        'required_boundary_status': required_boundary_status,
        'required_not_modeled_boundaries': required_not_modeled,
        'modeled_source_claims': modeled_claims,
        'formal_claim_bindings': formal_claims,
        'not_modeled_claims': not_modeled_claims,
        'proof_consumer_binding': {
            'claim_id': proof_consumer['claim_id'],
            'kernel_path': proof_consumer['kernel']['path'],
            'kernel_artifact_cid': proof_consumer['kernel']['artifact_cid'],
            'accepted_statuses': proof_consumer['invariant_policy']['accepted_statuses'],
            'rejected_statuses': proof_consumer['invariant_policy']['rejected_statuses'],
            'overall_status': proof_consumer['overall_status'],
            'production_release_blocked': proof_consumer['production_release_blocked'],
        },
        'public_source_assessment': {
            'path': str(PUBLIC_SOURCE_ASSESSMENT_PATH),
            'artifact_cid': assessment.get('artifact_cid'),
            'overall_status': assessment['overall_status'],
            'security_decision': assessment['security_decision'],
            'production_release_approval': assessment['production_release_approval'],
        },
        'summary': {
            'modeled_source_claim_count': len(modeled_claims),
            'formal_claim_binding_count': len(formal_claims),
            'not_modeled_claim_count': len(not_modeled_claims),
            'required_boundary_family_count': len(REQUIRED_BOUNDARY_FAMILIES),
            'covered_required_boundary_family_count': sum(
                1 for status in required_boundary_status.values() if status == 'COVERED_BY_IMMUTABLE_SOURCE_LOCATIONS'
            ),
            'modeled_claims_missing_immutable_source_count': len(missing_evidence),
            'production_release_approval_count': 0,
        },
        'modeled_claims_missing_immutable_source': missing_evidence,
        'overall_status': 'blocked',
        'security_decision': 'BLOCK_UNMODELED_NATIVE_BACKEND_AND_NON_PROVED_FORMAL_CLAIMS',
        'production_release_blocked': True,
    }
    return _with_artifact_cid(payload)


def build_native_boundary_coverage(repo_root: Path, source_claim_map: Mapping[str, Any]) -> dict[str, Any]:
    native_firebase = _load_json(repo_root, NATIVE_FIREBASE_REPORT_PATH)
    return _native_boundary_coverage(
        repo_root=repo_root,
        source_claim_map=source_claim_map,
        native_firebase_report=native_firebase,
    )


def build_markdown_report(source_claim_map: Mapping[str, Any], native_coverage: Mapping[str, Any]) -> str:
    matrix_rows = '\n'.join(
        f"| `{family}` | {entry['modeled_source_claim_count']} | {entry['formal_claim_count']} | `{entry['status']}` |"
        for family, entry in source_claim_map['coverage_matrix'].items()
    )
    not_modeled_rows = '\n'.join(
        f"| `{name}` | `{status}` |"
        for name, status in sorted(source_claim_map['required_not_modeled_boundaries'].items())
    )
    native_rows = '\n'.join(
        f"| `{entry['boundary_id']}` | `{entry['status']}` | {entry['summary']} |"
        for entry in native_coverage['boundaries']
    )
    formal_rows = '\n'.join(
        f"| `{entry['claim_id']}` | `{entry['boundary_family']}` | `{entry['status']}` | {entry['immutable_location_count']} |"
        for entry in source_claim_map['formal_claim_bindings']
    )
    return f"""# Xaman Source Claim Coverage

Task: `{TASK_ID}`

This report binds modeled Xaman wallet-auth, payload review, signing decision,
deep-link, QR, network-selection, receipt-consumer, and native-bridge claims to
immutable source locations from the pinned public corpus.

## Source Pin

- Repository: `{source_claim_map['source']['repo_url']}`
- Commit: `{source_claim_map['source']['commit_sha']}`
- Manifest: `{source_claim_map['source']['manifest_path']}`
- Coverage: `{source_claim_map['source']['coverage_path']}`
- Source-claim map: `{DEFAULT_CLAIM_MAP_OUT}`
- Native-boundary coverage: `{DEFAULT_NATIVE_OUT}`

The map is not a production release approval. It preserves the public-source
assessment decision and keeps release blocked while formal claims remain
non-proved or depend on uncleared assumptions.

## Boundary Coverage

| Boundary | Modeled source claims | Formal claims | Status |
| --- | ---: | ---: | --- |
{matrix_rows}

## Required NOT_MODELED Boundaries

| Boundary | Status |
| --- | --- |
{not_modeled_rows}

Vault cryptography, biometrics, native keystore behavior, and backend behavior
remain `NOT_MODELED` because the public source evidence only supports client
facades and call sites, not the native or backend implementations.

## Formal Claim Bindings

| Claim | Boundary | Status | Evidence locations |
| --- | --- | --- | ---: |
{formal_rows}

## Native Boundary Coverage

| Boundary | Status | Summary |
| --- | --- | --- |
{native_rows}

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_source_claim_coverage.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/build_xaman_source_claim_coverage.py --out security_ir_artifacts/corpora/xaman-app/source-claim-map.json
```
"""


def generate(
    repo_root: Path,
    *,
    claim_map_out: Path = DEFAULT_CLAIM_MAP_OUT,
    native_out: Path = DEFAULT_NATIVE_OUT,
    doc_out: Path = DEFAULT_DOC_OUT,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    source_claim_map = build_source_claim_map(repo_root)
    native_coverage = build_native_boundary_coverage(repo_root, source_claim_map)
    markdown = build_markdown_report(source_claim_map, native_coverage)
    _write_json(repo_root / claim_map_out, source_claim_map)
    _write_json(repo_root / native_out, native_coverage)
    _write_text(repo_root / doc_out, markdown)
    return source_claim_map, native_coverage, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        default=str(ROOT_DIR),
        help='Repository root containing security_ir_artifacts.',
    )
    parser.add_argument(
        '--out',
        default=str(DEFAULT_CLAIM_MAP_OUT),
        help='Output path for source-claim-map.json, relative to repo root unless absolute.',
    )
    parser.add_argument(
        '--native-out',
        default=str(DEFAULT_NATIVE_OUT),
        help='Output path for native-boundary-coverage.json.',
    )
    parser.add_argument(
        '--doc-out',
        default=str(DEFAULT_DOC_OUT),
        help='Output path for xaman_source_claim_coverage.md.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    claim_out = Path(args.out)
    native_out = Path(args.native_out)
    doc_out = Path(args.doc_out)
    if claim_out.is_absolute():
        claim_out = claim_out.relative_to(repo_root)
    if native_out.is_absolute():
        native_out = native_out.relative_to(repo_root)
    if doc_out.is_absolute():
        doc_out = doc_out.relative_to(repo_root)

    source_claim_map, native_coverage, _markdown = generate(
        repo_root,
        claim_map_out=claim_out,
        native_out=native_out,
        doc_out=doc_out,
    )
    print(
        'Wrote '
        f'{claim_out} '
        f'({source_claim_map["summary"]["modeled_source_claim_count"]} modeled, '
        f'{source_claim_map["summary"]["not_modeled_claim_count"]} not modeled) '
        f'and {native_out} '
        f'({native_coverage["summary"]["boundary_count"]} native/backend boundaries)'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
