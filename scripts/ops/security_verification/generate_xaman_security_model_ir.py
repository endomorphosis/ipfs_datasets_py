#!/usr/bin/env python3
"""Generate the canonical Xaman SecurityModelIR baseline.

The generated model is intentionally source-artifact backed: it binds the
manifest commit, environment probe, reviewed source facts, Xaman assumptions,
security claims, solver obligations, disproof vectors, and deterministic CID
sidecar used by downstream proof tasks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import (
    canonicalize_ir_json,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
    make_evidence_ref,
    validate_ir,
)


CORPUS_DIR = Path('security_ir_artifacts/corpora/xaman-app')
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
DOC_PATH = Path('docs/security_verification/xaman_security_model_ir.md')

SOURCE_MANIFEST_PATH = CORPUS_DIR / 'source-manifest.json'
SOURCE_COVERAGE_PATH = CORPUS_DIR / 'source-coverage.json'
ENVIRONMENT_PROBE_PATH = CORPUS_DIR / 'environment-probe.json'
WALLET_AUTH_PATH = CORPUS_DIR / 'wallet-auth-facts.json'
PAYLOAD_LIFECYCLE_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'
XRPL_TRANSACTION_PATH = CORPUS_DIR / 'xrpl-transaction-facts.json'
SECURITY_CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'
POLICY_PATH = Path('security_ir_artifacts/policies/security-decision-policy.json')

FACT_ARTIFACTS = (
    WALLET_AUTH_PATH,
    PAYLOAD_LIFECYCLE_PATH,
    XRPL_TRANSACTION_PATH,
)

CATEGORY_TO_DOMAIN = {
    'custody': 'vault',
    'authentication': 'auth_component',
    'payload_integrity': 'payload',
    'replay_prevention': 'payload',
    'network_binding': 'ledger',
    'transaction_semantics': 'ledger',
    'backend_trust': 'service',
    'runtime_equivalence': 'e2e_flow',
    'proof_consumer_policy': 'service',
}

CATEGORY_TO_OWNER = {
    'custody': 'wallet-key-management',
    'authentication': 'wallet-authentication',
    'payload_integrity': 'payload-security',
    'replay_prevention': 'payload-security',
    'network_binding': 'ledger-networking',
    'transaction_semantics': 'xrpl-transaction-safety',
    'backend_trust': 'backend-platform',
    'runtime_equivalence': 'release-engineering',
    'proof_consumer_policy': 'security-verification',
}

CLAIM_EVENTS = {
    'custody': ['event:xaman:auth-success', 'event:xaman:vault-opened', 'event:xaman:transaction-signed'],
    'authentication': ['event:xaman:auth-success', 'event:xaman:vault-opened'],
    'payload_integrity': [
        'event:xaman:payload-reference-received',
        'event:xaman:payload-digest-verified',
        'event:xaman:payload-reviewed',
        'event:xaman:transaction-signed',
    ],
    'replay_prevention': [
        'event:xaman:payload-digest-verified',
        'event:xaman:transaction-signed',
        'event:xaman:payload-resolved-patch',
    ],
    'network_binding': [
        'event:xaman:payload-reviewed',
        'event:xaman:transaction-signed',
        'event:xaman:ledger-submit-requested',
    ],
    'transaction_semantics': [
        'event:xaman:payload-reviewed',
        'event:xaman:transaction-signed',
        'event:xaman:ledger-submit-requested',
    ],
    'backend_trust': [
        'event:xaman:payload-reference-received',
        'event:xaman:payload-resolved-patch',
    ],
    'runtime_equivalence': ['event:xaman:runtime-profile-bound'],
    'proof_consumer_policy': ['event:xaman:proof-packet-consumed'],
}

DISPROOF_TACTICS = {
    'custody': 'mutate:vault_open_precondition_to_absent_secret_read',
    'authentication': 'bypass:signing_without_fresh_authentication_event',
    'payload_integrity': 'substitute:payload_json_after_digest_review',
    'replay_prevention': 'race:double_resolve_same_payload_uuid',
    'network_binding': 'substitute:force_network_or_submit_node_mismatch',
    'transaction_semantics': 'mutate:reviewed_field_before_signing',
    'backend_trust': 'forge:unauthorized_backend_patch_or_resolution',
    'runtime_equivalence': 'substitute:deployed_binary_or_backend_digest',
    'proof_consumer_policy': 'consume:unknown_or_mismatched_proof_packet',
}


def _load_json(repo_root: Path, path: Path) -> dict[str, Any]:
    return json.loads((repo_root / path).read_text(encoding='utf-8'))


def _artifact_ref(path: Path, notes: str, *, kind: str = 'manual_review') -> dict[str, Any]:
    return make_evidence_ref(
        kind=kind,
        path=str(path),
        review_status='human_reviewed',
        notes=notes,
    )


def _source_ref(reference: Mapping[str, Any], *, notes: str | None = None) -> dict[str, Any]:
    return make_evidence_ref(
        kind='source_code',
        path=str(reference['path']),
        line_start=reference.get('line_start'),
        line_end=reference.get('line_end'),
        sha256=reference.get('sha256'),
        review_status='human_reviewed',
        notes=notes or reference.get('notes'),
    )


def _dedupe_refs(refs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for ref in refs:
        normalized = {key: value for key, value in ref.items() if value is not None}
        key = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
        if key in seen:
            continue
        deduped.append(normalized)
        seen.add(key)
    return deduped


def _slug(identifier: str) -> str:
    return identifier.rsplit(':', 1)[-1].replace('_', '-')


def _fact_indexes(repo_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Path]]:
    facts: dict[str, dict[str, Any]] = {}
    gaps: dict[str, dict[str, Any]] = {}
    artifact_by_id: dict[str, Path] = {}
    for path in FACT_ARTIFACTS:
        artifact = _load_json(repo_root, path)
        for fact in artifact['modeled_facts']:
            facts[fact['id']] = fact
            artifact_by_id[fact['id']] = path
        for gap in artifact['not_modeled_gaps']:
            gaps[gap['id']] = gap
            artifact_by_id[gap['id']] = path
    return facts, gaps, artifact_by_id


def _claim_evidence_refs(
    claim: Mapping[str, Any],
    facts: Mapping[str, Mapping[str, Any]],
    gaps: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for fact_id in claim.get('evidence_fact_ids', []):
        record = facts.get(fact_id) or gaps.get(fact_id)
        if not record:
            continue
        for source_ref in record.get('evidence', []):
            if source_ref.get('kind') == 'source_code':
                refs.append(_source_ref(source_ref, notes=f'Reviewed source evidence for {fact_id}.'))
    if not refs and claim.get('category') == 'proof_consumer_policy':
        refs.extend(
            [
                _artifact_ref(POLICY_PATH, 'Fail-closed security decision policy.', kind='policy_doc'),
                _artifact_ref(
                    Path('docs/security_verification/proof_receipt_consumer_policy.md'),
                    'Proof receipt consumer policy.',
                    kind='policy_doc',
                ),
            ]
        )
    refs.append(_artifact_ref(SECURITY_CLAIMS_PATH, f'Claim declaration for {claim["id"]}.'))
    return _dedupe_refs(refs)


def _assumption_evidence_refs(assumption: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for evidence in assumption.get('evidence', []):
        refs.extend(_review_reference_to_ir_refs(evidence, prefix='Evidence'))
    for evidence in assumption.get('blocking_references', []):
        refs.extend(_review_reference_to_ir_refs(evidence, prefix='Blocking reference'))
    if not refs:
        refs.append(_artifact_ref(SECURITY_CLAIMS_PATH, f'Assumption declaration for {assumption["id"]}.'))
    return _dedupe_refs(refs)


def _review_reference_to_ir_refs(reference: Mapping[str, Any], *, prefix: str) -> list[dict[str, Any]]:
    kind = reference.get('kind')
    if kind == 'source_manifest':
        return [
            _artifact_ref(
                Path(reference['artifact_path']),
                f'{prefix}: pinned source manifest {reference.get("commit_sha", "")}.'.strip(),
            )
        ]
    if kind in {'dependency_fact', 'dependency_gap'}:
        ids_key = 'fact_ids' if kind == 'dependency_fact' else 'gap_ids'
        ids = ', '.join(reference.get(ids_key, []))
        return [
            _artifact_ref(
                Path(reference['artifact_path']),
                f'{prefix}: reviewed {kind} entries {ids}.',
            )
        ]
    if kind == 'policy_artifact':
        return [
            _artifact_ref(
                Path(reference['artifact_path']),
                f'{prefix}: policy artifact bound to {reference.get("document_path", "policy document")}.',
                kind='policy_doc',
            )
        ]
    if kind == 'policy_document':
        return [
            _artifact_ref(
                Path(reference['document_path']),
                f'{prefix}: proof-consumer policy document.',
                kind='policy_doc',
            )
        ]
    return [_artifact_ref(SECURITY_CLAIMS_PATH, f'{prefix}: {kind or "review"} reference.')]


def _build_assumptions(claims_artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    assumptions: list[dict[str, Any]] = []
    for assumption in claims_artifact['assumptions']:
        category = assumption['category']
        assumptions.append(
            {
                'id': assumption['id'],
                'description': assumption['statement'],
                'custom': True,
                'owner': CATEGORY_TO_OWNER.get(category, 'security-verification'),
                'evidence_refs': _assumption_evidence_refs(assumption),
                'last_reviewed_at': '2026-07-08T00:00:00Z',
                'evidence_expires_at': '2027-01-08T00:00:00Z',
                'xaman_category': category,
                'severity': assumption['severity'],
                'acceptance_status': assumption['status'],
                'blocking_reason': assumption.get('blocking_reason'),
                'required_evidence_to_accept': assumption.get('required_evidence_to_accept', []),
            }
        )
    return assumptions


def _build_claims(
    claims_artifact: Mapping[str, Any],
    facts: Mapping[str, Mapping[str, Any]],
    gaps: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for claim in claims_artifact['security_claims']:
        category = claim['category']
        claims.append(
            {
                'id': claim['id'],
                'description': claim['claim'],
                'domain': CATEGORY_TO_DOMAIN[category],
                'severity': claim['release_gate'],
                'required_assumptions': list(claim['assumption_ids']),
                'evidence_refs': _claim_evidence_refs(claim, facts, gaps),
                'xaman_category': category,
                'risk': claim['risk'],
                'source_status': claim['status'],
                'blocking_assumption_ids': list(claim['blocking_assumption_ids']),
                'evidence_fact_ids': list(claim.get('evidence_fact_ids', [])),
                'proof_obligation_statement': claim['proof_obligation'],
                'consumer_policy': claim['consumer_policy'],
            }
        )
    return claims


def _build_proof_obligations(claims_artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    obligations: list[dict[str, Any]] = []
    for claim in claims_artifact['security_claims']:
        claim_slug = _slug(claim['id'])
        for prover in ('z3', 'cvc5'):
            obligations.append(
                {
                    'id': f'obligation:xaman:{claim_slug}:{prover}',
                    'claim_id': claim['id'],
                    'prover': prover,
                    'status': 'NOT_MODELED',
                    'evidence_refs': [
                        _artifact_ref(SECURITY_CLAIMS_PATH, f'Obligation source statement for {claim["id"]}.')
                    ],
                    'blocked_by_assumptions': list(claim['blocking_assumption_ids']),
                    'expected_solver_contract': claim['proof_obligation'],
                }
            )
    return obligations


def _build_disproof_vectors(claims_artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    vectors: list[dict[str, Any]] = []
    for claim in claims_artifact['security_claims']:
        category = claim['category']
        vectors.append(
            {
                'id': f'disproof:xaman:{_slug(claim["id"])}',
                'claim_id': claim['id'],
                'tactic': DISPROOF_TACTICS[category],
                'status': 'UNKNOWN',
                'counterexample': {
                    'search_space': category,
                    'blocked_by_assumptions': list(claim['blocking_assumption_ids']),
                    'expected_failure_mode': 'claim cannot be accepted until the blocked assumptions are evidenced and solver obligations discharge',
                },
                'evidence_refs': [
                    _artifact_ref(SECURITY_CLAIMS_PATH, f'Disproof vector derived from {claim["id"]}.')
                ],
            }
        )
    return vectors


def _build_solver_results(claims_artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for claim in claims_artifact['security_claims']:
        claim_slug = _slug(claim['id'])
        for solver in ('z3', 'cvc5'):
            results.append(
                {
                    'id': f'solver:xaman:{claim_slug}:{solver}',
                    'claim_id': claim['id'],
                    'solver_name': solver,
                    'result': 'not-modeled',
                    'evidence_refs': [
                        _artifact_ref(SECURITY_CLAIMS_PATH, f'Baseline solver result pending SMT emission for {claim["id"]}.')
                    ],
                }
            )
    return results


def _artifact_summary(repo_root: Path, path: Path) -> dict[str, Any]:
    artifact = _load_json(repo_root, path)
    summary = {
        'artifact_path': str(path),
        'schema_version': artifact.get('schema_version'),
        'task_id': artifact.get('task_id'),
    }
    if 'review' in artifact:
        summary['review_status'] = artifact['review'].get('review_status')
        summary['reviewed_at'] = artifact['review'].get('reviewed_at')
    if 'modeled_facts' in artifact:
        summary['modeled_fact_count'] = len(artifact['modeled_facts'])
        summary['not_modeled_gap_count'] = len(artifact.get('not_modeled_gaps', []))
    return summary


def _reviewed_fact_metadata(
    facts: Mapping[str, Mapping[str, Any]],
    gaps: Mapping[str, Mapping[str, Any]],
    artifact_by_id: Mapping[str, Path],
) -> dict[str, Any]:
    return {
        'modeled_facts': [
            {
                'id': fact_id,
                'category': fact.get('category'),
                'status': fact.get('status'),
                'artifact_path': str(artifact_by_id[fact_id]),
            }
            for fact_id, fact in sorted(facts.items())
        ],
        'not_modeled_gaps': [
            {
                'id': gap_id,
                'category': gap.get('category'),
                'status': gap.get('status'),
                'severity': gap.get('severity'),
                'artifact_path': str(artifact_by_id[gap_id]),
            }
            for gap_id, gap in sorted(gaps.items())
        ],
    }


def build_xaman_security_model_ir(repo_root: Path) -> SecurityModelIR:
    manifest = _load_json(repo_root, SOURCE_MANIFEST_PATH)
    coverage = _load_json(repo_root, SOURCE_COVERAGE_PATH)
    environment = _load_json(repo_root, ENVIRONMENT_PROBE_PATH)
    claims_artifact = _load_json(repo_root, SECURITY_CLAIMS_PATH)
    facts, gaps, artifact_by_id = _fact_indexes(repo_root)

    model = SecurityModelIR(
        schema_version='security-model-ir/v1',
        model_id='xaman-app-security-model-ir-baseline',
        entities=[
            {'id': 'entity:xaman_user', 'kind': 'wallet_user', 'name': 'Xaman wallet user'},
            {'id': 'entity:xaman_mobile_app', 'kind': 'react_native_wallet', 'name': 'Xaman mobile app'},
            {'id': 'entity:xaman_backend_payload_api', 'kind': 'backend_service', 'name': 'Xaman payload API'},
            {'id': 'entity:xrpl_network', 'kind': 'ledger_network', 'name': 'XRPL network selected by Xaman'},
            {'id': 'entity:xaman_proof_consumer', 'kind': 'proof_consumer', 'name': 'Xaman proof-consuming release gate'},
        ],
        assets=[
            {'id': 'asset:xrp', 'symbol': 'XRP', 'decimals': 6},
            {'id': 'asset:xrpl_issued_currency', 'symbol': 'XRPL_IOU', 'decimals': 15},
            {'id': 'asset:xaman_payload_reference', 'symbol': 'PAYLOAD_REF', 'decimals': 0},
            {'id': 'asset:security_proof_receipt', 'symbol': 'PROOF_RECEIPT', 'decimals': 0},
        ],
        wallets=[
            {
                'id': 'wallet:xaman_software_account',
                'owner': 'principal:xaman_user',
                'asset': 'asset:xrp',
                'status': 'active',
                'custody_mode': 'software_vault',
            },
            {
                'id': 'wallet:xaman_tangem_account',
                'owner': 'principal:xaman_user',
                'asset': 'asset:xrp',
                'status': 'active',
                'custody_mode': 'tangem_card_session',
            },
        ],
        accounts=[
            {
                'id': 'account:xaman_selected_xrpl_account',
                'owner': 'principal:xaman_user',
                'wallet_id': 'wallet:xaman_software_account',
                'asset_id': 'asset:xrp',
                'balance': 0,
                'evidence_refs': [
                    _artifact_ref(WALLET_AUTH_PATH, 'Reviewed account storage and signing-boundary facts.')
                ],
            }
        ],
        roles=[
            {'id': 'role:xaman_user', 'name': 'xaman_user'},
            {'id': 'role:xaman_backend_service', 'name': 'xaman_backend_service'},
            {'id': 'role:xrpl_ledger_service', 'name': 'xrpl_ledger_service'},
            {'id': 'role:proof_consumer', 'name': 'proof_consumer'},
        ],
        principals=[
            {'id': 'principal:xaman_user', 'role': 'role:xaman_user'},
            {'id': 'principal:xaman_backend_service', 'role': 'role:xaman_backend_service'},
            {'id': 'principal:xrpl_ledger_service', 'role': 'role:xrpl_ledger_service'},
            {'id': 'principal:xaman_proof_consumer', 'role': 'role:proof_consumer'},
        ],
        capabilities=[
            {
                'id': 'capability:xaman_software_signing',
                'principal': 'principal:xaman_user',
                'resource_id': 'wallet:xaman_software_account',
                'actions': ['authenticate', 'open_vault', 'sign_reviewed_transaction'],
                'evidence_refs': [_artifact_ref(WALLET_AUTH_PATH, 'Software signing path facts.')],
            },
            {
                'id': 'capability:xaman_backend_payload_resolution',
                'principal': 'principal:xaman_backend_service',
                'resource_id': 'entity:xaman_backend_payload_api',
                'actions': ['create_payload', 'fetch_payload', 'validate_payload', 'patch_payload_resolution'],
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Payload backend boundary facts and gaps.')],
            },
            {
                'id': 'capability:xaman_proof_packet_consumption',
                'principal': 'principal:xaman_proof_consumer',
                'resource_id': 'entity:xaman_proof_consumer',
                'actions': ['validate_model_cid', 'validate_report_cid', 'reject_non_proved_claim'],
                'evidence_refs': [_artifact_ref(POLICY_PATH, 'Fail-closed proof-consumer policy.', kind='policy_doc')],
            },
        ],
        policies=[
            {
                'id': f'policy:xaman:{claim["category"]}',
                'name': f'xaman_{claim["category"]}_fail_closed',
                'enabled': True,
                'claim_id': claim['id'],
                'release_gate': claim['release_gate'],
                'evidence_refs': [_artifact_ref(SECURITY_CLAIMS_PATH, f'Fail-closed policy for {claim["category"]}.')],
            }
            for claim in claims_artifact['security_claims']
        ],
        events=[
            {
                'id': 'event:xaman:payload-reference-received',
                'event': 'xaman_payload_reference_received',
                'custom': True,
                'description': 'QR, deep-link, push, event-list, or local payload reference enters client review flow.',
                'principal': 'principal:xaman_user',
                'timestamp': 1,
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Payload intake facts.')],
            },
            {
                'id': 'event:xaman:payload-digest-verified',
                'event': 'xaman_payload_digest_verified',
                'custom': True,
                'description': 'Remote payload request JSON digest is verified before review.',
                'timestamp': 2,
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Payload digest verification facts.')],
            },
            {
                'id': 'event:xaman:payload-reviewed',
                'event': 'xaman_payload_reviewed',
                'custom': True,
                'description': 'User-visible review displays app, source account, transaction, network, and accept control.',
                'principal': 'principal:xaman_user',
                'account_id': 'account:xaman_selected_xrpl_account',
                'timestamp': 3,
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Payload review UI facts.')],
            },
            {
                'id': 'event:xaman:auth-success',
                'event': 'xaman_authentication_succeeded',
                'custom': True,
                'description': 'Passcode, passphrase, biometric-assisted passcode, or Tangem card authentication succeeds.',
                'principal': 'principal:xaman_user',
                'timestamp': 4,
                'evidence_refs': [_artifact_ref(WALLET_AUTH_PATH, 'Authentication overlay facts.')],
            },
            {
                'id': 'event:xaman:vault-opened',
                'event': 'xaman_vault_opened',
                'custom': True,
                'description': 'Vault or Tangem signing path opens for the selected account after authentication.',
                'wallet_id': 'wallet:xaman_software_account',
                'timestamp': 5,
                'evidence_refs': [_artifact_ref(WALLET_AUTH_PATH, 'Vault access and signing precondition facts.')],
            },
            {
                'id': 'event:xaman:transaction-signed',
                'event': 'xaman_transaction_signed',
                'custom': True,
                'description': 'Reviewed XRPL transaction bytes are signed by software vault or Tangem path.',
                'wallet_id': 'wallet:xaman_software_account',
                'account_id': 'account:xaman_selected_xrpl_account',
                'timestamp': 6,
                'evidence_refs': [_artifact_ref(XRPL_TRANSACTION_PATH, 'XRPL transaction semantics facts.')],
            },
            {
                'id': 'event:xaman:payload-resolved-patch',
                'event': 'xaman_payload_resolved_patch',
                'custom': True,
                'description': 'Signed, rejected, or dispatch result is patched back to the backend payload service.',
                'principal': 'principal:xaman_backend_service',
                'timestamp': 7,
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Payload patching facts.')],
            },
            {
                'id': 'event:xaman:ledger-submit-requested',
                'event': 'xaman_ledger_submit_requested',
                'custom': True,
                'description': 'Client requests optional XRPL submission for a signed transaction.',
                'principal': 'principal:xrpl_ledger_service',
                'timestamp': 8,
                'evidence_refs': [_artifact_ref(XRPL_TRANSACTION_PATH, 'Ledger submit and transaction field facts.')],
            },
            {
                'id': 'event:xaman:runtime-profile-bound',
                'event': 'xaman_runtime_profile_bound',
                'custom': True,
                'description': 'Source commit, environment probe, deployment digests, and runtime traces are bound to a proof packet.',
                'timestamp': 9,
                'evidence_refs': [_artifact_ref(ENVIRONMENT_PROBE_PATH, 'Environment probe profile.')],
            },
            {
                'id': 'event:xaman:proof-packet-consumed',
                'event': 'xaman_proof_packet_consumed',
                'custom': True,
                'description': 'Release consumer validates model, proof report, receipt or signature, assumptions, and evidence freshness.',
                'principal': 'principal:xaman_proof_consumer',
                'timestamp': 10,
                'evidence_refs': [_artifact_ref(POLICY_PATH, 'Fail-closed consumer policy.', kind='policy_doc')],
            },
        ],
        state_machines=[
            {
                'id': 'state_machine:xaman_payload_signing',
                'states': ['intake', 'digest_verified', 'reviewed', 'authenticated', 'signed', 'patched', 'submitted'],
                'current': 'submitted',
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Payload lifecycle model.')],
            },
            {
                'id': 'state_machine:xaman_proof_consumption',
                'states': ['untrusted', 'model_bound', 'assumptions_checked', 'solver_checked', 'accepted', 'rejected'],
                'current': 'rejected',
                'evidence_refs': [_artifact_ref(POLICY_PATH, 'Fail-closed proof-consumer decision model.', kind='policy_doc')],
            },
        ],
        invariants=[
            {
                'id': 'invariant:xaman:no_secret_use_without_vault_or_tangem',
                'description': 'Software private-key use for signing is only modeled through authenticated vault or Tangem paths.',
                'evidence_refs': [_artifact_ref(WALLET_AUTH_PATH, 'Custody source facts and native-vault gaps.')],
            },
            {
                'id': 'invariant:xaman:payload_uuid_single_terminal_resolution',
                'description': 'A payload UUID has at most one successful signed, rejected, or submitted terminal resolution.',
                'evidence_refs': [_artifact_ref(PAYLOAD_LIFECYCLE_PATH, 'Replay control facts and backend gaps.')],
            },
            {
                'id': 'invariant:xaman:signed_transaction_matches_reviewed_semantics',
                'description': 'Signed XRPL bytes preserve the reviewed account, amount, fee, sequence, network, memo, IOU, trustline, multisign, and transaction-type semantics.',
                'evidence_refs': [_artifact_ref(XRPL_TRANSACTION_PATH, 'XRPL transaction semantics facts and gaps.')],
            },
            {
                'id': 'invariant:xaman:proof_consumers_fail_closed',
                'description': 'Proof consumers reject all non-proved, stale, mismatched, unsupported, or assumption-blocked Xaman claims.',
                'evidence_refs': [_artifact_ref(POLICY_PATH, 'Security decision policy.', kind='policy_doc')],
            },
        ],
        claims=_build_claims(claims_artifact, facts, gaps),
        proof_obligations=_build_proof_obligations(claims_artifact),
        disproof_vectors=_build_disproof_vectors(claims_artifact),
        runtime_traces=[
            {
                'id': f'trace:xaman:{claim["category"]}',
                'description': f'Reviewed baseline trace projection for the {claim["category"]} Xaman claim.',
                'domain': CATEGORY_TO_DOMAIN[claim['category']],
                'events': CLAIM_EVENTS[claim['category']],
                'conformance_status': 'blocked_by_assumptions',
                'evidence_refs': [_artifact_ref(SECURITY_CLAIMS_PATH, f'Trace obligation for {claim["id"]}.')],
                'claim_id': claim['id'],
            }
            for claim in claims_artifact['security_claims']
        ],
        solver_results=_build_solver_results(claims_artifact),
        assumptions=_build_assumptions(claims_artifact),
        prover_targets=['z3', 'cvc5'],
        metadata={
            'task_id': 'PORTAL-CXTP-068',
            'corpus': {
                'name': 'xaman-app',
                'repo_url': manifest['source']['repo_url'],
                'requested_ref': manifest['source']['requested_ref'],
                'commit_sha': manifest['source']['commit_sha'],
                'manifest_schema_version': manifest['schema_version'],
                'manifest_aggregate_sha256': manifest['reproducibility']['aggregate_sha256'],
                'manifest_file_count': manifest['reproducibility']['file_count'],
            },
            'environment_probe': {
                'artifact_path': str(ENVIRONMENT_PROBE_PATH),
                'schema_version': environment['schema_version'],
                'task_id': environment['task_id'],
                'overall_status': environment['overall_status'],
                'security_decision': environment['security_decision'],
                'proof_acceptance_blocked': environment['proof_acceptance_blocked'],
                'optional_capability_gap_count': len(environment.get('optional_capability_gaps', [])),
            },
            'source_coverage': {
                'artifact_path': str(SOURCE_COVERAGE_PATH),
                'schema_version': coverage['schema_version'],
                'coverage_summary': coverage['coverage_summary'],
                'security_relevant_roots': coverage['security_relevant_roots'],
            },
            'dependency_artifacts': [
                _artifact_summary(repo_root, WALLET_AUTH_PATH),
                _artifact_summary(repo_root, PAYLOAD_LIFECYCLE_PATH),
                _artifact_summary(repo_root, XRPL_TRANSACTION_PATH),
                _artifact_summary(repo_root, SECURITY_CLAIMS_PATH),
            ],
            'reviewed_source_facts': _reviewed_fact_metadata(facts, gaps, artifact_by_id),
            'claim_category_to_ir_domain': CATEGORY_TO_DOMAIN,
            'production_decision': claims_artifact['production_decision'],
            'canonical_output': {
                'json_path': str(MODEL_PATH),
                'cid_path': str(CID_PATH),
                'canonicalization': 'canonicalize_ir_json sort_keys separators comma-colon ensure_ascii',
            },
        },
    )
    return validate_ir(model)


def render_markdown(model: SecurityModelIR, cid_value: str) -> str:
    claims_by_domain: dict[str, int] = {}
    for claim in model.claims:
        claims_by_domain[claim['domain']] = claims_by_domain.get(claim['domain'], 0) + 1
    domain_rows = '\n'.join(
        f'| `{domain}` | {count} |'
        for domain, count in sorted(claims_by_domain.items())
    )
    claim_rows = '\n'.join(
        f'| `{claim["xaman_category"]}` | `{claim["domain"]}` | `{claim["severity"]}` | `{claim["source_status"]}` | `{claim["id"]}` |'
        for claim in model.claims
    )
    artifact_rows = '\n'.join(
        f'| `{entry["artifact_path"]}` | `{entry.get("schema_version")}` | `{entry.get("task_id")}` |'
        for entry in model.metadata['dependency_artifacts']
    )
    blocking_assumptions = [
        assumption
        for assumption in model.assumptions
        if isinstance(assumption, Mapping) and assumption.get('acceptance_status') == 'BLOCKING'
    ]

    return f"""# Xaman SecurityModelIR Baseline

Task: `PORTAL-CXTP-068`

The canonical SecurityModelIR artifact is
`security_ir_artifacts/corpora/xaman-app/security-model-ir.json`. Its
deterministic content address is stored in
`security_ir_artifacts/corpora/xaman-app/security-model-ir.cid`.

## Source Binding

- Corpus: `xaman-app`
- Repository: `{model.metadata['corpus']['repo_url']}`
- Commit: `{model.metadata['corpus']['commit_sha']}`
- Manifest aggregate SHA-256: `{model.metadata['corpus']['manifest_aggregate_sha256']}`
- Environment probe: `{model.metadata['environment_probe']['artifact_path']}`
- Environment decision: `{model.metadata['environment_probe']['security_decision']}`
- Canonical model CID: `{cid_value}`

## Dependency Inputs

| Artifact | Schema | Task |
| --- | --- | --- |
{artifact_rows}

The IR binds {len(model.metadata['reviewed_source_facts']['modeled_facts'])}
reviewed source facts and {len(model.metadata['reviewed_source_facts']['not_modeled_gaps'])}
explicit `NOT_MODELED` gaps from the wallet-auth, payload-lifecycle, and XRPL
transaction artifacts.

## Claim Projection

| Xaman category | IR domain | Gate | Source status | Claim |
| --- | --- | --- | --- | --- |
{claim_rows}

Domain coverage in the baseline:

| IR domain | Claim count |
| --- | ---: |
{domain_rows}

## Assumptions And Blocking State

The model carries {len(model.assumptions)} Xaman assumptions from
`security-claims.json`. {len(blocking_assumptions)} assumptions remain
`BLOCKING`; therefore every proof obligation is emitted with status
`NOT_MODELED` and every solver result is `not-modeled` until the missing
evidence is supplied and reviewed.

Blocking assumptions are not erased by the IR. They remain attached to claims,
proof obligations, disproof vectors, and metadata so proof consumers can fail
closed instead of accepting a partial model.

## Solver Obligations And Disproof Vectors

- Proof obligations: {len(model.proof_obligations)} (`z3` and `cvc5` for each Xaman claim)
- Solver results: {len(model.solver_results)} baseline `not-modeled` entries
- Disproof vectors: {len(model.disproof_vectors)} mutation, bypass, replay, substitution, and consumer-policy vectors
- Runtime trace projections: {len(model.runtime_traces)}

The next solver task can compile these obligations to SMT-LIB without needing
to rediscover the source commit, environment profile, reviewed fact IDs,
assumption IDs, or disproof tactics.

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q
```

The tests validate schema conformance, dependency bindings, claim and
assumption closure, proof and disproof coverage, canonical JSON stability, and
CID sidecar recomputation.
"""


def write_artifacts(repo_root: Path) -> tuple[SecurityModelIR, str]:
    model = build_xaman_security_model_ir(repo_root)
    canonical_json = canonicalize_ir_json(model)
    cid_value = calculate_model_cid(model)

    (repo_root / MODEL_PATH).write_text(canonical_json, encoding='utf-8')
    (repo_root / CID_PATH).write_text(f'{cid_value}\n', encoding='utf-8')
    (repo_root / DOC_PATH).write_text(render_markdown(model, cid_value), encoding='utf-8')
    return model, cid_value


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    model, cid_value = write_artifacts(repo_root)
    print(f'Wrote {MODEL_PATH} ({len(model.claims)} claims, CID {cid_value})')


if __name__ == '__main__':
    main()
