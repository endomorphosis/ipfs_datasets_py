from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_protocol_projection import (
    PROTOCOL_CATEGORIES,
    PROTOCOL_REPORT_PATH,
    REQUIRED_ACTION_FACTS,
    REQUIRED_LEMMAS,
    REQUIRED_RULES,
    SCHEMA_VERSION,
    TAMARIN_ARTIFACT_PATH,
    TASK_ID,
    THEORY_NAME,
    XAMAN_PAYLOAD_PROTOCOL_SPTHY,
    build_xaman_protocol_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
LIFECYCLE_FACTS_PATH = CORPUS_DIR / 'payload-lifecycle-facts.json'
WALLET_AUTH_FACTS_PATH = CORPUS_DIR / 'wallet-auth-facts.json'
TAMARIN_PATH = REPO_ROOT / TAMARIN_ARTIFACT_PATH
REPORT_PATH = REPO_ROOT / PROTOCOL_REPORT_PATH
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_protocol_model.md'

REQUIRED_FACT_IDS = {
    'xaman-payload-lifecycle:fact:payload-build-creates-local-sign-request',
    'xaman-payload-lifecycle:fact:payload-types-carry-expiration-origin-and-network-fields',
    'xaman-payload-lifecycle:fact:remote-payload-fetch-verifies-request-json-digest',
    'xaman-payload-lifecycle:fact:remote-fetch-blocks-resolved-or-expired-payloads',
    'xaman-payload-lifecycle:fact:qr-payload-reference-intake-fetches-and-routes-to-review',
    'xaman-payload-lifecycle:fact:deep-link-payload-reference-intake-fetches-and-routes-to-review',
    'xaman-payload-lifecycle:fact:push-notification-payload-intake-fetches-with-push-origin',
    'xaman-payload-lifecycle:fact:event-list-loads-pending-payloads-and-opens-review',
    'xaman-payload-lifecycle:fact:review-preflight-binds-forced-network-and-signer',
    'xaman-payload-lifecycle:fact:review-ui-displays-app-source-account-transaction-and-accept-control',
    'xaman-payload-lifecycle:fact:approval-revalidates-non-generated-payload-before-signing',
    'xaman-payload-lifecycle:fact:approval-enters-vault-signing-boundary',
    'xaman-payload-lifecycle:fact:network-binding-applies-to-templates-review-and-signing',
    'xaman-payload-lifecycle:fact:signed-payload-is-patched-before-optional-ledger-broadcast',
    'xaman-payload-lifecycle:fact:broadcast-only-when-submit-true-non-pseudo-and-not-multisign',
    'xaman-payload-lifecycle:fact:ledger-submit-has-local-single-submit-and-abort-guards',
    'xaman-payload-lifecycle:fact:dispatch-result-is-patched-after-ledger-submit',
    'xaman-payload-lifecycle:fact:submit-request-type-boundary-is-xrpl-submit',
    'xaman-wallet-auth:fact:account-secret-vaulted-for-full-access',
    'xaman-wallet-auth:fact:vault-access-is-through-native-module',
    'xaman-wallet-auth:fact:vault-overlay-selects-signer-and-auth-method-from-access-and-encryption-level',
    'xaman-wallet-auth:fact:software-private-key-signing-requires-vault-open-with-encryption-key',
    'xaman-wallet-auth:fact:transaction-signing-preconditions-before-vault-overlay',
    'xaman-wallet-auth:fact:signed-object-callback-must-include-blob-pubkey-method-and-id-for-non-pseudo',
    'xaman-wallet-auth:fact:submit-requires-signed-blob-single-submit-and-not-aborted',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }


def _expected_report() -> dict[str, Any]:
    return build_xaman_protocol_report(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        lifecycle_facts=_load_json(LIFECYCLE_FACTS_PATH),
        wallet_auth_facts=_load_json(WALLET_AUTH_FACTS_PATH),
        tamarin_source=TAMARIN_PATH.read_text(encoding='utf-8').rstrip('\n'),
        tamarin_executable=None,
        tamarin_version=None,
        proverif_executable=None,
        proverif_version=None,
    )


def test_xaman_protocol_report_is_generated_from_current_inputs() -> None:
    checked_in = _load_json(REPORT_PATH)
    expected = _expected_report()

    assert checked_in == expected
    assert checked_in['schema_version'] == SCHEMA_VERSION
    assert checked_in['task_id'] == TASK_ID
    assert checked_in['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert checked_in['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in)
    )
    assert checked_in['protocol_model']['artifact_cid'] == calculate_artifact_cid(
        {
            'theory_name': THEORY_NAME,
            'source': TAMARIN_PATH.read_text(encoding='utf-8').rstrip('\n'),
        }
    )


def test_xaman_tamarin_theory_declares_required_protocol_surface() -> None:
    spthy = TAMARIN_PATH.read_text(encoding='utf-8')

    assert spthy.rstrip('\n') == XAMAN_PAYLOAD_PROTOCOL_SPTHY
    assert spthy.startswith(f'theory {THEORY_NAME}')
    assert 'TODO' not in spthy
    assert 'builtins: signing, hashing' in spthy
    assert 'BackendPayloadAuthorized' in spthy
    assert 'VaultSecretStored' in spthy
    assert 'LedgerBroadcastRequested' in spthy

    for rule in REQUIRED_RULES:
        assert re.search(rf'^rule {re.escape(rule)}:', spthy, re.MULTILINE), rule

    for lemma in REQUIRED_LEMMAS:
        assert re.search(rf'^lemma {re.escape(lemma)}:', spthy, re.MULTILINE), lemma

    for action_fact in REQUIRED_ACTION_FACTS:
        assert f'{action_fact}(' in spthy, action_fact

    for origin in ['QR', 'DEEP_LINK', 'PUSH_NOTIFICATION', 'EVENT_LIST']:
        assert origin in spthy


def test_xaman_protocol_report_covers_required_evidence_and_categories() -> None:
    report = _load_json(REPORT_PATH)
    lifecycle_facts = _load_json(LIFECYCLE_FACTS_PATH)
    wallet_auth_facts = _load_json(WALLET_AUTH_FACTS_PATH)
    fact_ids = {
        fact['id']
        for payload in [lifecycle_facts, wallet_auth_facts]
        for fact in payload['modeled_facts']
    }
    properties = report['properties']

    assert report['protocol_model']['categories'] == list(PROTOCOL_CATEGORIES)
    assert {entry['category'] for entry in properties} == set(PROTOCOL_CATEGORIES)
    assert {fact_id for entry in properties for fact_id in entry['evidence_fact_ids']} >= (
        REQUIRED_FACT_IDS
    )
    assert report['evidence_scope']['missing_evidence_fact_ids'] == []
    assert report['evidence_scope']['missing_gap_record_ids'] == []
    assert report['summary']['missing_evidence_count'] == 0

    for entry in properties:
        assert entry['modeled'] is True
        assert entry['lemma'] in report['protocol_model']['required_lemmas']
        assert set(entry['rule_names']) <= set(report['protocol_model']['required_rules'])
        assert set(entry['action_facts']) <= set(
            report['protocol_model']['required_action_facts']
        )
        assert entry['claim_ids'], entry['category']
        assert entry['assumption_ids'], entry['category']
        assert set(entry['evidence_fact_ids']) <= fact_ids
        assert entry['description']


def test_xaman_protocol_report_marks_missing_protocol_solvers_as_blockers() -> None:
    report = _load_json(REPORT_PATH)
    summary = report['summary']

    assert report['solvers']['tamarin'] == {
        'available': False,
        'blocker': {
            'kind': 'missing_solver',
            'message': 'tamarin-prover executable was not available when this protocol report was generated; symbolic protocol checks are solver-blocked and must not be accepted as proved.',
            'required_action': 'Install tamarin-prover and rerun the XamanPayloadProtocol protocol checks before promoting any protocol property to PROVED.',
            'solver': 'tamarin-prover',
        },
        'executable': None,
        'solver': 'tamarin-prover',
        'status': 'BLOCKED',
        'version': None,
    }
    assert report['solvers']['proverif'] == {
        'available': False,
        'blocker': {
            'kind': 'missing_solver',
            'message': 'proverif executable was not available when this protocol report was generated; symbolic protocol checks are solver-blocked and must not be accepted as proved.',
            'required_action': 'Install proverif and rerun the XamanPayloadProtocol protocol checks before promoting any protocol property to PROVED.',
            'solver': 'proverif',
        },
        'executable': None,
        'solver': 'proverif',
        'status': 'BLOCKED',
        'version': None,
    }
    assert summary == {
        'blocked_property_count': 9,
        'checked_property_count': 0,
        'missing_evidence_count': 0,
        'modeled_property_count': 9,
        'negative_case_count': 7,
        'property_count': 9,
        'proverif_available': False,
        'rejected_claim_count': 5,
        'release_ready': False,
        'tamarin_available': False,
    }

    for entry in report['properties']:
        assert entry['classification'] == 'BLOCKED'
        assert entry['solver_status'] == 'BLOCKED'
        assert entry['solver_blocker'] == report['solvers']['tamarin']['blocker']
        assert entry['tamarin_command'][0] == 'tamarin-prover'
        assert entry['proverif_equivalent_query']['status'] == 'BLOCKED'
        assert 'PROVED' not in entry.values()


def test_xaman_protocol_properties_encode_acceptance_cases() -> None:
    properties = {
        entry['category']: entry
        for entry in _load_json(REPORT_PATH)['properties']
    }

    assert properties['session_identity']['lemma'] == 'requester_binding_precedes_review'
    assert 'PayloadSessionCreated' in properties['session_identity']['action_facts']

    requester = properties['requester_binding']
    assert requester['lemma'] == 'requester_binding_precedes_review'
    assert 'xaman-security:claim:network-binding-prevents-cross-network-signing' in (
        requester['claim_ids']
    )

    intake = properties['intake']
    assert intake['lemma'] == 'qr_and_deep_link_intake_preserve_requester'
    assert {
        'xaman-payload-lifecycle:fact:qr-payload-reference-intake-fetches-and-routes-to-review',
        'xaman-payload-lifecycle:fact:deep-link-payload-reference-intake-fetches-and-routes-to-review',
    } <= set(intake['evidence_fact_ids'])

    assert properties['payload_integrity']['lemma'] == 'review_requires_verified_payload'
    assert properties['replay']['lemma'] == 'local_replay_after_signing_is_blocked'

    secrets = properties['secrets']
    assert secrets['lemma'] == 'modeled_vault_secret_not_revealed'
    assert 'xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path' in (
        secrets['claim_ids']
    )

    signatures = properties['signatures']
    assert signatures['lemma'] == 'signing_requires_auth_revalidation_and_network'
    assert 'xaman-security:claim:authentication-gates-vault-and-signing' in (
        signatures['claim_ids']
    )
    assert 'xaman-security:assumption:authentication-overlay-gates-vault-signing' in (
        signatures['assumption_ids']
    )

    assert properties['backend_trust_boundary']['lemma'] == (
        'signed_patch_requires_backend_trust'
    )
    assert properties['broadcast_boundary']['lemma'] == 'broadcast_requires_signed_patch'


def test_xaman_protocol_projection_rejects_unavailable_evidence_claims() -> None:
    report = _load_json(REPORT_PATH)
    rejected = {
        entry['id']: entry
        for entry in report['rejected_claims']
    }

    assert set(rejected) == {
        'xaman-protocol:rejected:backend-global-single-use-and-authorization',
        'xaman-protocol:rejected:native-intake-parser-and-delivery-integrity',
        'xaman-protocol:rejected:native-vault-cryptographic-secrecy',
        'xaman-protocol:rejected:third-party-signature-correctness',
        'xaman-protocol:rejected:deployed-runtime-equivalence',
    }
    for entry in rejected.values():
        assert entry['classification'] == 'REJECTED_UNAVAILABLE_EVIDENCE'
        assert entry['modeled'] is False
        assert entry['solver_status'] == 'NOT_SUBMITTED'
        assert entry['blocked_by_assumption_ids']
        assert entry['required_evidence_to_accept']
        assert entry['gap_summaries']
        assert entry['reason']

    backend = rejected[
        'xaman-protocol:rejected:backend-global-single-use-and-authorization'
    ]
    assert 'xaman-security:assumption:backend-payload-api-single-use-and-authorization' in (
        backend['blocked_by_assumption_ids']
    )
    assert 'xaman-payload-lifecycle:gap:backend-payload-creation-auth-and-single-use' in (
        backend['gap_ids']
    )

    native_vault = rejected['xaman-protocol:rejected:native-vault-cryptographic-secrecy']
    assert 'xaman-security:assumption:native-vault-cryptographic-confidentiality' in (
        native_vault['blocked_by_assumption_ids']
    )


def test_xaman_protocol_negative_cases_cover_replay_and_boundary_failures() -> None:
    report = _load_json(REPORT_PATH)
    negative_cases = {
        entry['attack_class']: entry
        for entry in report['negative_cases']
    }

    assert set(negative_cases) == {
        'auth_precondition_removed',
        'digest_tampering',
        'duplicate_submit',
        'replay_payload',
        'requester_substitution',
        'stale_or_resolved_payload',
        'wrong_network',
    }
    assert negative_cases['replay_payload']['expected_action_fact'] == 'ReplayBlocked'
    assert negative_cases['auth_precondition_removed']['expected_action_fact'] == (
        'AuthenticatedVaultOpen'
    )
    assert negative_cases['digest_tampering']['blocked_by_property_id'] == (
        'xaman-protocol:property:digest-verification-precedes-review'
    )


def test_xaman_protocol_doc_links_artifacts_and_fail_closed_policy() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    normalized_doc = ' '.join(doc.split())

    assert 'PORTAL-CXTP-072' in doc
    assert TAMARIN_ARTIFACT_PATH in doc
    assert PROTOCOL_REPORT_PATH in doc
    assert 'generate_xaman_protocol_projection.py' in doc
    assert 'test_xaman_protocol_projection.py' in doc
    assert 'Tamarin and ProVerif are not available' in normalized_doc
    assert 'REJECTED_UNAVAILABLE_EVIDENCE' in doc
    assert (
        'must not promote' in normalized_doc
        or 'must not be accepted as proved' in normalized_doc
    )
