import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import (
    canonicalize_ir_json,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
    validate_ir,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_security_model_ir.md'

MANIFEST_PATH = CORPUS_DIR / 'source-manifest.json'
COVERAGE_PATH = CORPUS_DIR / 'source-coverage.json'
ENVIRONMENT_PATH = CORPUS_DIR / 'environment-probe.json'
CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'

DEPENDENCY_FACT_ARTIFACTS = [
    CORPUS_DIR / 'wallet-auth-facts.json',
    CORPUS_DIR / 'payload-lifecycle-facts.json',
    CORPUS_DIR / 'xrpl-transaction-facts.json',
]

EXPECTED_CATEGORY_DOMAIN = {
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _dependency_fact_and_gap_ids() -> tuple[set[str], set[str]]:
    fact_ids: set[str] = set()
    gap_ids: set[str] = set()
    for path in DEPENDENCY_FACT_ARTIFACTS:
        artifact = _load_json(path)
        fact_ids.update(entry['id'] for entry in artifact['modeled_facts'])
        gap_ids.update(entry['id'] for entry in artifact['not_modeled_gaps'])
    return fact_ids, gap_ids


def test_xaman_security_model_ir_schema_source_and_canonical_cid() -> None:
    payload = _load_json(MODEL_PATH)
    manifest = _load_json(MANIFEST_PATH)
    environment = _load_json(ENVIRONMENT_PATH)

    model = validate_ir(SecurityModelIR.from_untrusted_dict(payload, strict=True))
    assert model.schema_version == 'security-model-ir/v1'
    assert model.model_id == 'xaman-app-security-model-ir-baseline'
    assert model.prover_targets == ['z3', 'cvc5']

    assert payload['metadata']['task_id'] == 'PORTAL-CXTP-068'
    assert payload['metadata']['corpus']['name'] == 'xaman-app'
    assert payload['metadata']['corpus']['repo_url'] == manifest['source']['repo_url']
    assert payload['metadata']['corpus']['commit_sha'] == manifest['source']['commit_sha']
    assert (
        payload['metadata']['corpus']['manifest_aggregate_sha256']
        == manifest['reproducibility']['aggregate_sha256']
    )
    assert payload['metadata']['environment_probe']['artifact_path'] == (
        'security_ir_artifacts/corpora/xaman-app/environment-probe.json'
    )
    assert payload['metadata']['environment_probe']['schema_version'] == environment['schema_version']
    assert payload['metadata']['environment_probe']['overall_status'] == environment['overall_status']
    assert payload['metadata']['environment_probe']['security_decision'] == environment['security_decision']

    assert MODEL_PATH.read_text(encoding='utf-8') == canonicalize_ir_json(payload)
    assert CID_PATH.read_text(encoding='utf-8').strip() == calculate_model_cid(payload)


def test_xaman_security_model_ir_binds_dependency_artifacts_and_reviewed_facts() -> None:
    payload = _load_json(MODEL_PATH)
    coverage = _load_json(COVERAGE_PATH)
    fact_ids, gap_ids = _dependency_fact_and_gap_ids()

    dependencies = {
        entry['artifact_path']: entry
        for entry in payload['metadata']['dependency_artifacts']
    }
    assert set(dependencies) == {
        'security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json',
        'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',
        'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json',
        'security_ir_artifacts/corpora/xaman-app/security-claims.json',
    }
    for path, entry in dependencies.items():
        artifact = _load_json(REPO_ROOT / path)
        assert entry['schema_version'] == artifact['schema_version']
        assert entry['task_id'] == artifact['task_id']

    metadata_facts = payload['metadata']['reviewed_source_facts']['modeled_facts']
    metadata_gaps = payload['metadata']['reviewed_source_facts']['not_modeled_gaps']
    assert {entry['id'] for entry in metadata_facts} == fact_ids
    assert {entry['id'] for entry in metadata_gaps} == gap_ids
    assert len(metadata_facts) == 71
    assert len(metadata_gaps) == 14

    assert payload['metadata']['source_coverage']['schema_version'] == coverage['schema_version']
    assert payload['metadata']['source_coverage']['coverage_summary'] == coverage['coverage_summary']
    assert payload['metadata']['claim_category_to_ir_domain'] == EXPECTED_CATEGORY_DOMAIN


def test_xaman_security_model_ir_claims_and_assumptions_are_closed() -> None:
    payload = _load_json(MODEL_PATH)
    source_claims = _load_json(CLAIMS_PATH)
    fact_ids, gap_ids = _dependency_fact_and_gap_ids()
    known_evidence_ids = fact_ids | gap_ids

    ir_claims = {claim['id']: claim for claim in payload['claims']}
    source_claim_by_id = {claim['id']: claim for claim in source_claims['security_claims']}
    assumptions = {entry['id']: entry for entry in payload['assumptions']}
    source_assumptions = {entry['id']: entry for entry in source_claims['assumptions']}

    assert set(ir_claims) == set(source_claim_by_id)
    assert set(assumptions) == set(source_assumptions)
    assert len(ir_claims) == 9
    assert len(assumptions) == 20

    for claim_id, claim in ir_claims.items():
        source_claim = source_claim_by_id[claim_id]
        assert claim['description'] == source_claim['claim']
        assert claim['xaman_category'] == source_claim['category']
        assert claim['domain'] == EXPECTED_CATEGORY_DOMAIN[source_claim['category']]
        assert claim['severity'] == source_claim['release_gate']
        assert claim['source_status'] == 'BLOCKED_BY_ASSUMPTIONS'
        assert set(claim['required_assumptions']) == set(source_claim['assumption_ids'])
        assert set(claim['required_assumptions']) <= set(assumptions)
        assert set(claim['blocking_assumption_ids']) == set(source_claim['blocking_assumption_ids'])
        assert set(claim['blocking_assumption_ids']) <= set(claim['required_assumptions'])
        assert set(claim['evidence_fact_ids']) == set(source_claim['evidence_fact_ids'])
        assert set(claim['evidence_fact_ids']) <= known_evidence_ids
        assert claim['evidence_refs']

    for assumption_id, assumption in assumptions.items():
        source_assumption = source_assumptions[assumption_id]
        assert assumption['description'] == source_assumption['statement']
        assert assumption['custom'] is True
        assert assumption['acceptance_status'] in {'EVIDENCED', 'BLOCKING'}
        assert assumption['xaman_category'] == source_assumption['category']
        assert assumption['evidence_refs']
        if assumption['acceptance_status'] == 'BLOCKING':
            assert assumption['blocking_reason']
            assert assumption['required_evidence_to_accept']


def test_xaman_security_model_ir_solver_obligations_disproofs_and_traces_cover_claims() -> None:
    payload = _load_json(MODEL_PATH)
    claim_ids = {claim['id'] for claim in payload['claims']}

    obligations_by_claim: dict[str, set[str]] = {}
    for obligation in payload['proof_obligations']:
        obligations_by_claim.setdefault(obligation['claim_id'], set()).add(obligation['prover'])
        assert obligation['status'] == 'NOT_MODELED'
        assert obligation['blocked_by_assumptions']
        assert obligation['expected_solver_contract']
    assert obligations_by_claim == {claim_id: {'z3', 'cvc5'} for claim_id in claim_ids}

    solvers_by_claim: dict[str, set[str]] = {}
    for result in payload['solver_results']:
        solvers_by_claim.setdefault(result['claim_id'], set()).add(result['solver_name'])
        assert result['result'] == 'not-modeled'
    assert solvers_by_claim == {claim_id: {'z3', 'cvc5'} for claim_id in claim_ids}

    vectors_by_claim = {vector['claim_id']: vector for vector in payload['disproof_vectors']}
    assert set(vectors_by_claim) == claim_ids
    for vector in vectors_by_claim.values():
        assert vector['status'] == 'UNKNOWN'
        assert vector['tactic']
        assert vector['counterexample']['blocked_by_assumptions']

    event_ids = {event['id'] for event in payload['events']}
    traces_by_claim = {trace['claim_id']: trace for trace in payload['runtime_traces']}
    assert set(traces_by_claim) == claim_ids
    for trace in traces_by_claim.values():
        assert trace['conformance_status'] == 'blocked_by_assumptions'
        assert set(trace['events']) <= event_ids


def test_xaman_security_model_ir_document_covers_artifact_cid_and_validation() -> None:
    document = DOC_PATH.read_text(encoding='utf-8')
    cid = CID_PATH.read_text(encoding='utf-8').strip()

    assert 'PORTAL-CXTP-068' in document
    assert 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json' in document
    assert 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid' in document
    assert cid in document
    assert '942f43876265a7af44f233288ad2b1d00841d5fa' in document
    assert 'reviewed source facts' in document
    assert 'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_security_model_ir.py -q' in document
