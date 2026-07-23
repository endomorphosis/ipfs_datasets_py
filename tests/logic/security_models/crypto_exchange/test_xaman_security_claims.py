import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
CLAIMS_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'security-claims.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_security_claims.md'


REQUIRED_CATEGORIES = {
    'custody',
    'authentication',
    'payload_integrity',
    'replay_prevention',
    'network_binding',
    'transaction_semantics',
    'backend_trust',
    'runtime_equivalence',
    'proof_consumer_policy',
}

REQUIRED_CLAIM_IDS = {
    'xaman-claim:software-custody-requires-vault-authentication',
    'xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
    'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
    'xaman-claim:client-replay-controls-exist-but-backend-single-use-is-blocking',
    'xaman-claim:network-binding-prevents-wrong-network-signing',
    'xaman-claim:payment-semantics-check-amount-balance-and-trustlines',
    'xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
    'xaman-claim:backend-payload-service-is-trusted-not-proved',
    'xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
    'xaman-claim:proof-consumer-must-reject-non-proved-results',
}

REQUIRED_BLOCKING_ASSUMPTIONS = {
    'xaman-assumption:native-vault-crypto-and-biometric-security',
    'xaman-assumption:backend-payload-api-auth-single-use-and-expiration',
    'xaman-assumption:xrpl-consensus-node-honesty-and-finality',
    'xaman-assumption:deployed-runtime-equivalence',
    'xaman-assumption:incomplete-transaction-class-validation',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_security_claims_schema_source_and_models() -> None:
    claims = _load_json(CLAIMS_PATH)

    assert claims['schema_version'] == 'xaman-security-claims/v1'
    assert claims['task_id'] == 'PORTAL-CXTP-067'
    assert claims['corpus'] == 'xaman-app'
    assert claims['source']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert claims['review']['review_status'] == 'reviewed'
    assert {
        'wallet_auth',
        'payload_lifecycle',
        'xrpl_transaction',
        'runtime_trace',
        'optional_solver_install',
    } <= set(claims['source_models'])
    assert all(model['path'] for model in claims['source_models'].values())


def test_xaman_security_claims_cover_required_categories_and_ids() -> None:
    claims = _load_json(CLAIMS_PATH)
    entries = claims['claims']

    assert {entry['id'] for entry in entries} >= REQUIRED_CLAIM_IDS
    assert {entry['category'] for entry in entries} >= REQUIRED_CATEGORIES
    assert all(entry['evidence'] for entry in entries)
    assert all(entry['assumptions'] for entry in entries)
    assert all(entry['release_policy'] != 'accept_as_secure_without_proof' for entry in entries)


def test_xaman_security_claims_blocking_assumptions_are_explicit() -> None:
    claims = _load_json(CLAIMS_PATH)
    assumptions = claims['assumptions']

    assert {entry['id'] for entry in assumptions if entry['status'] == 'BLOCKING'} >= REQUIRED_BLOCKING_ASSUMPTIONS
    assert all(entry['required_evidence_to_clear'] for entry in assumptions)

    by_id = {entry['id']: entry for entry in assumptions}
    assert by_id['xaman-assumption:deployed-runtime-equivalence']['source'] == 'runtime_trace_report'
    assert by_id['xaman-assumption:backend-payload-api-auth-single-use-and-expiration']['source'] == 'payload_lifecycle_gaps'


def test_xaman_security_claims_proof_consumer_policy_fails_closed() -> None:
    claims = _load_json(CLAIMS_PATH)
    policy = claims['proof_consumer_policy']

    assert policy['accept_only_result'] == 'proved'
    assert {
        'disproved',
        'unknown',
        'not_modeled',
        'stale_evidence',
        'missing_solver',
        'blocked_assumption',
    } <= set(policy['reject_results'])
    assert policy['requires_model_cid'] is True
    assert policy['requires_corpus_commit'] is True
    assert policy['requires_fresh_environment_probe'] is True


def test_xaman_security_claims_decision_remains_blocked() -> None:
    claims = _load_json(CLAIMS_PATH)

    assert claims['security_decision'] == 'BLOCK_SECURITY_CLAIMS_PENDING_PROOFS_AND_ASSUMPTIONS'
    assert claims['production_release_blocked'] is True
    assert claims['claim_summary']['blocking_claim_count'] >= 4
    assert claims['claim_summary']['proved_claim_count'] == 0


def test_xaman_security_claims_document_covers_artifact_and_blockers() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-067' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/security-claims.json' in doc
    for section in [
        'Custody And Authentication',
        'Payload Integrity And Replay',
        'Network And Transaction Semantics',
        'Backend And Runtime Blocking Assumptions',
        'Proof Consumer Policy',
    ]:
        assert section in doc
