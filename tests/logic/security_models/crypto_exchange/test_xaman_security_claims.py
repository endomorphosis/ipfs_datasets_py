import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
CLAIMS_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'security-claims.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_security_claims.md'
MANIFEST_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-manifest.json'
)
COVERAGE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-coverage.json'
)
POLICY_PATH = REPO_ROOT / 'security_ir_artifacts' / 'policies' / 'security-decision-policy.json'

DEPENDENCY_ARTIFACTS = {
    'PORTAL-CXTP-064': (
        REPO_ROOT
        / 'security_ir_artifacts'
        / 'corpora'
        / 'xaman-app'
        / 'wallet-auth-facts.json'
    ),
    'PORTAL-CXTP-065': (
        REPO_ROOT
        / 'security_ir_artifacts'
        / 'corpora'
        / 'xaman-app'
        / 'payload-lifecycle-facts.json'
    ),
    'PORTAL-CXTP-066': (
        REPO_ROOT
        / 'security_ir_artifacts'
        / 'corpora'
        / 'xaman-app'
        / 'xrpl-transaction-facts.json'
    ),
}

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
    'xaman-security:claim:custody-software-private-key-not-available-without-authorized-vault-path',
    'xaman-security:claim:authentication-gates-vault-and-signing',
    'xaman-security:claim:payload-integrity-before-review-and-signing',
    'xaman-security:claim:payload-replay-prevention-is-single-use',
    'xaman-security:claim:network-binding-prevents-cross-network-signing',
    'xaman-security:claim:xrpl-transaction-semantics-match-reviewed-signing-intent',
    'xaman-security:claim:backend-trust-boundary-is-safe-for-payload-resolution',
    'xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime',
    'xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims',
}

REQUIRED_BLOCKING_ASSUMPTIONS = {
    'xaman-security:assumption:native-vault-cryptographic-confidentiality',
    'xaman-security:assumption:passcode-kdf-and-secret-protection',
    'xaman-security:assumption:biometric-native-binding',
    'xaman-security:assumption:third-party-signing-correctness',
    'xaman-security:assumption:backend-payload-api-single-use-and-authorization',
    'xaman-security:assumption:intake-decoder-and-os-delivery-integrity',
    'xaman-security:assumption:deployed-network-and-node-config-equivalence',
    'xaman-security:assumption:trustset-and-signerlist-client-validation',
    'xaman-security:assumption:xrpl-server-rule-enforcement-and-consensus',
    'xaman-security:assumption:external-multisign-coordination',
    'xaman-security:assumption:deployed-runtime-equivalence',
    'xaman-security:assumption:proof-receipt-cid-or-signature-validation',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _dependency_ids() -> tuple[set[str], set[str]]:
    fact_ids: set[str] = set()
    gap_ids: set[str] = set()
    for path in DEPENDENCY_ARTIFACTS.values():
        artifact = _load_json(path)
        fact_ids.update(entry['id'] for entry in artifact['modeled_facts'])
        gap_ids.update(entry['id'] for entry in artifact['not_modeled_gaps'])
    return fact_ids, gap_ids


def test_xaman_security_claims_schema_source_and_dependencies() -> None:
    claims = _load_json(CLAIMS_PATH)
    manifest = _load_json(MANIFEST_PATH)
    coverage = _load_json(COVERAGE_PATH)

    assert claims['schema_version'] == 'xaman-security-claims/v1'
    assert claims['task_id'] == 'PORTAL-CXTP-067'
    assert claims['corpus'] == 'xaman-app'
    assert claims['source']['repo_url'] == manifest['source']['repo_url']
    assert claims['source']['commit_sha'] == manifest['source']['commit_sha']
    assert claims['source']['manifest_schema_version'] == manifest['schema_version']
    assert claims['source']['manifest_aggregate_sha256'] == manifest['reproducibility']['aggregate_sha256']
    assert claims['source']['coverage_schema_version'] == coverage['schema_version']
    assert claims['review']['review_status'] == 'reviewed'
    assert REQUIRED_CATEGORIES <= set(claims['review']['review_scope'])

    dependencies = {entry['task_id']: entry for entry in claims['dependencies']}
    assert set(dependencies) == set(DEPENDENCY_ARTIFACTS)
    for task_id, path in DEPENDENCY_ARTIFACTS.items():
        dependency = dependencies[task_id]
        assert dependency['artifact_path'] == str(path.relative_to(REPO_ROOT))
        assert path.exists()
        assert dependency['schema_version'] == _load_json(path)['schema_version']
        assert (REPO_ROOT / dependency['document_path']).exists()


def test_xaman_security_claims_cover_required_gates_and_categories() -> None:
    claims = _load_json(CLAIMS_PATH)
    security_claims = claims['security_claims']

    assert len(security_claims) == 9
    assert {claim['id'] for claim in security_claims} == REQUIRED_CLAIM_IDS
    assert {claim['category'] for claim in security_claims} == REQUIRED_CATEGORIES
    assert all(claim['release_gate'] in {'blocking', 'high'} for claim in security_claims)
    assert all(claim['risk'] in {'blocking', 'high'} for claim in security_claims)
    assert all(claim['status'] == 'BLOCKED_BY_ASSUMPTIONS' for claim in security_claims)
    assert all(claim['claim'] and claim['proof_obligation'] for claim in security_claims)
    assert all(claim['consumer_policy'].startswith('fail_closed') for claim in security_claims)

    blocking = {claim['category'] for claim in security_claims if claim['release_gate'] == 'blocking'}
    high = {claim['category'] for claim in security_claims if claim['release_gate'] == 'high'}
    assert {
        'custody',
        'authentication',
        'replay_prevention',
        'backend_trust',
        'runtime_equivalence',
        'proof_consumer_policy',
    } <= blocking
    assert {'payload_integrity', 'network_binding', 'transaction_semantics'} <= high

    decision = claims['production_decision']
    assert decision['outcome'] == 'blocked-production'
    assert set(decision['blocking_claim_ids']).isdisjoint(decision['high_risk_claim_ids'])
    assert set(decision['blocking_claim_ids']) | set(decision['high_risk_claim_ids']) == REQUIRED_CLAIM_IDS
    assert decision['required_next_artifacts']


def test_xaman_security_assumptions_are_evidenced_or_marked_blocking() -> None:
    claims = _load_json(CLAIMS_PATH)
    assumptions = claims['assumptions']

    assert len(assumptions) >= 18
    assert {entry['id'] for entry in assumptions} >= REQUIRED_BLOCKING_ASSUMPTIONS
    assert {entry['category'] for entry in assumptions} >= REQUIRED_CATEGORIES
    assert all(entry['severity'] in {'blocking', 'high'} for entry in assumptions)
    assert all(entry['statement'] for entry in assumptions)

    for assumption in assumptions:
        if assumption['status'] == 'EVIDENCED':
            assert assumption['evidence'], assumption['id']
            for evidence in assumption['evidence']:
                assert evidence['review_status'] == 'reviewed'
        elif assumption['status'] == 'BLOCKING':
            assert assumption['blocking_reason'], assumption['id']
            assert assumption['blocking_references'], assumption['id']
            assert assumption['required_evidence_to_accept'], assumption['id']
            assert all(
                reference['review_status'] == 'reviewed'
                for reference in assumption['blocking_references']
            )
        else:
            raise AssertionError(f"Unexpected assumption status: {assumption}")


def test_xaman_security_claim_assumption_references_are_closed_and_blocking() -> None:
    claims = _load_json(CLAIMS_PATH)
    assumptions = {entry['id']: entry for entry in claims['assumptions']}

    for claim in claims['security_claims']:
        assert claim['assumption_ids'], claim['id']
        assert set(claim['assumption_ids']) <= set(assumptions), claim['id']
        assert claim['blocking_assumption_ids'], claim['id']
        assert set(claim['blocking_assumption_ids']) <= set(claim['assumption_ids']), claim['id']
        assert all(
            assumptions[assumption_id]['status'] == 'BLOCKING'
            for assumption_id in claim['blocking_assumption_ids']
        ), claim['id']

    claim_policy = claims['claim_policy']
    assert claim_policy['allowed_secure_statuses_for_production'] == ['PROVED']
    assert 'BLOCKED_BY_ASSUMPTIONS' in claim_policy['non_secure_statuses_for_production']
    assert 'status EVIDENCED with reviewed evidence or status BLOCKING' in claim_policy['assumption_rule']
    assert 'fail closed' in claim_policy['consumer_rule']


def test_xaman_security_dependency_fact_and_gap_references_exist() -> None:
    claims = _load_json(CLAIMS_PATH)
    fact_ids, gap_ids = _dependency_ids()

    for assumption in claims['assumptions']:
        refs = assumption.get('evidence', []) + assumption.get('blocking_references', [])
        for ref in refs:
            artifact_path = ref.get('artifact_path')
            if ref['kind'] == 'dependency_fact':
                assert artifact_path
                assert (REPO_ROOT / artifact_path).exists()
                assert set(ref['fact_ids']) <= fact_ids
            elif ref['kind'] == 'dependency_gap':
                assert artifact_path
                assert (REPO_ROOT / artifact_path).exists()
                assert set(ref['gap_ids']) <= gap_ids
            elif ref['kind'] == 'source_manifest':
                assert artifact_path == 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
                assert ref['sha256'] == claims['source']['manifest_aggregate_sha256']
            elif ref['kind'] == 'policy_artifact':
                assert artifact_path == 'security_ir_artifacts/policies/security-decision-policy.json'
                assert (REPO_ROOT / artifact_path).exists()
                assert (REPO_ROOT / ref['document_path']).exists()
            elif ref['kind'] == 'policy_document':
                assert (REPO_ROOT / ref['document_path']).exists()
            else:
                raise AssertionError(f'Unexpected reference kind: {ref}')

    known_ids = fact_ids | gap_ids
    for claim in claims['security_claims']:
        assert set(claim['evidence_fact_ids']) <= known_ids


def test_xaman_security_proof_consumer_policy_is_fail_closed() -> None:
    claims = _load_json(CLAIMS_PATH)
    policy = _load_json(POLICY_PATH)

    assert policy['default_consumer_rule'].startswith('Only outcome prove')
    assert policy['proof_boundary']['non_secure_blocking_outcomes']
    assert all(
        outcome in policy['proof_boundary']['non_secure_blocking_outcomes']
        for outcome in [
            'blocked-production',
            'disprove',
            'missing-solver',
            'not-modeled',
            'stale-evidence',
            'unknown',
        ]
    )

    by_id = {claim['id']: claim for claim in claims['security_claims']}
    consumer_claim = by_id['xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims']
    assert consumer_claim['release_gate'] == 'blocking'
    assert consumer_claim['status'] == 'BLOCKED_BY_ASSUMPTIONS'
    assert 'xaman-security:assumption:proof-consumer-fail-closed-policy' in consumer_claim['assumption_ids']
    assert (
        'xaman-security:assumption:proof-receipt-cid-or-signature-validation'
        in consumer_claim['blocking_assumption_ids']
    )

    by_assumption = {entry['id']: entry for entry in claims['assumptions']}
    fail_closed = by_assumption['xaman-security:assumption:proof-consumer-fail-closed-policy']
    assert fail_closed['status'] == 'EVIDENCED'
    assert any(ref['kind'] == 'policy_artifact' for ref in fail_closed['evidence'])


def test_xaman_security_claims_document_covers_artifact_claims_and_blockers() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    claims = _load_json(CLAIMS_PATH)

    assert 'PORTAL-CXTP-067' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/security-claims.json' in doc
    assert claims['source']['commit_sha'] in doc
    assert 'blocked-production' in doc
    assert 'BLOCKED_BY_ASSUMPTIONS' in doc
    for section in [
        'Custody',
        'Authentication',
        'Payload Integrity',
        'Replay Prevention',
        'Network Binding',
        'Transaction Semantics',
        'Backend Trust',
        'Runtime Equivalence',
        'Proof-Consumer Policy',
        'Assumption Rule',
    ]:
        assert section in doc
