from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.ops.security_verification.build_xaman_public_source_assessment import (
    build_assessment,
)


ROOT = Path(__file__).resolve().parents[4]
ASSESSMENT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/public-source-assessment.json'

EXPECTED_ASSUMPTIONS = {
    'xaman-assumption:native-vault-crypto-and-biometric-security',
    'xaman-assumption:backend-payload-api-auth-single-use-and-expiration',
    'xaman-assumption:xrpl-consensus-node-honesty-and-finality',
    'xaman-assumption:deployed-runtime-equivalence',
    'xaman-assumption:incomplete-transaction-class-validation',
    'xaman-assumption:proof-consumer-kernel-validation',
}

EXPECTED_SOLVER_LANES = {
    'smt_z3_cvc5',
    'tla_apalache',
    'protocol_tamarin_proverif',
    'proof_consumer_kernel',
}

REQUIRED_UNMODELED_COMPONENTS = {
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


def test_xaman_public_source_assessment_schema_and_source_binding() -> None:
    assessment = _json(ASSESSMENT_PATH)

    assert assessment['schema_version'] == 'xaman-public-source-assessment/v1'
    assert assessment['task_id'] == 'PORTAL-CXTP-144'
    assert assessment['corpus'] == 'xaman-app'
    assert assessment['source']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert assessment['source']['public_source_only'] is True
    assert assessment['source']['manifest_path'] == (
        'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
    )

    cid_payload = dict(assessment)
    artifact_cid = cid_payload.pop('artifact_cid')
    assert artifact_cid == _canonical_sha256(cid_payload)


def test_xaman_public_source_assessment_rebuilds_deterministically() -> None:
    checked_in = _json(ASSESSMENT_PATH)
    rebuilt = build_assessment(ROOT)

    assert rebuilt == checked_in


def test_xaman_public_source_assessment_fails_closed_not_release_approval() -> None:
    assessment = _json(ASSESSMENT_PATH)

    assert assessment['overall_status'] == 'blocked'
    assert assessment['public_source_result'] == 'blocked_public_source_assessment'
    assert assessment['security_decision'] == 'BLOCK_PUBLIC_SOURCE_ASSESSMENT_NOT_RELEASE_APPROVAL'
    assert assessment['production_release_approval'] is False
    assert assessment['production_release_blocked'] is True
    assert assessment['release_decision'] == 'not_a_release_decision_public_source_only'
    assert assessment['assessment_boundary']['not_a_production_release_approval'] is True
    assert assessment['assessment_boundary']['may_be_used_for_production_release_approval'] is False
    assert assessment['summary']['production_release_approval_count'] == 0
    assert assessment['summary']['proved_public_source_claim_count'] == 0

    prohibited = set(assessment['assessment_boundary']['prohibited_public_source_labels'])
    public_results = {
        item['public_source_result']
        for bucket in [
            'conditional_claims',
            'known_counterexamples',
            'missing_evidence_disproof_vectors',
            'unmodeled_components',
            'external_assumptions',
            'solver_coverage_gaps',
            'vendor_only_evidence',
        ]
        for item in assessment[bucket]
        if 'public_source_result' in item
    }
    assert public_results.isdisjoint(prohibited)
    assert all(not result.startswith('approved') for result in public_results)


def test_xaman_public_source_assessment_separates_source_facts_and_conditional_claims() -> None:
    assessment = _json(ASSESSMENT_PATH)
    facts = assessment['source_supported_facts']
    claims = assessment['conditional_claims']

    assert assessment['summary']['source_supported_fact_count'] == 54
    assert assessment['summary']['conditional_claim_count'] == 10
    assert {fact['source_model'] for fact in facts} == {
        'wallet_auth',
        'payload_lifecycle',
        'xrpl_transaction',
    }
    assert all(fact['status'] == 'MODELED' for fact in facts)
    assert all(fact['public_source_support'] == 'source_supported_fact' for fact in facts)
    assert all(fact['evidence'] for fact in facts)

    assert all(claim['assumptions'] for claim in claims)
    assert all(claim['production_release_approval'] is False for claim in claims)
    assert all(claim['public_source_result'] == 'conditional_or_blocked_not_production_approval' for claim in claims)
    assert all(claim['release_policy'].startswith('block_until') for claim in claims)
    assert {claim['source_status'] for claim in claims}.isdisjoint({'PROVED', 'APPROVED'})


def test_xaman_public_source_assessment_tracks_counterexamples_and_unmodeled_components() -> None:
    assessment = _json(ASSESSMENT_PATH)

    assert assessment['summary']['known_counterexample_count'] == 7
    assert assessment['summary']['missing_evidence_disproof_vector_count'] == 2
    assert all(entry['result'] == 'counterexample_found' for entry in assessment['known_counterexamples'])
    assert all(entry['release_policy'] == 'block' for entry in assessment['known_counterexamples'])
    assert {
        entry['claim_id'] for entry in assessment['missing_evidence_disproof_vectors']
    } == {
        'xaman-claim:backend-payload-service-is-trusted-not-proved',
        'xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
    }

    unmodeled_ids = {entry['id'] for entry in assessment['unmodeled_components']}
    assert assessment['summary']['unmodeled_component_count'] == 17
    assert REQUIRED_UNMODELED_COMPONENTS <= unmodeled_ids
    assert all(entry['status'] == 'NOT_MODELED' for entry in assessment['unmodeled_components'])


def test_xaman_public_source_assessment_keeps_assumptions_and_vendor_evidence_explicit() -> None:
    assessment = _json(ASSESSMENT_PATH)
    assumptions = assessment['external_assumptions']
    vendor_evidence = assessment['vendor_only_evidence']

    assert {entry['id'] for entry in assumptions} == EXPECTED_ASSUMPTIONS
    assert all(entry['status'] == 'BLOCKING' for entry in assumptions)
    assert all(entry['required_evidence_to_clear'] for entry in assumptions)
    assert assessment['summary']['vendor_only_evidence_count'] >= 20
    assert any(
        entry['required_evidence'] == 'backend API source snapshot'
        for entry in vendor_evidence
    )
    assert any(
        entry['required_evidence'] == 'real-device trace bundle'
        for entry in vendor_evidence
    )
    assert all(entry['availability'] == 'vendor_or_operator_only_until_provided' for entry in vendor_evidence)


def test_xaman_public_source_assessment_records_solver_coverage_gaps() -> None:
    assessment = _json(ASSESSMENT_PATH)
    lanes = {entry['lane']: entry for entry in assessment['solver_coverage_gaps']}

    assert set(lanes) == EXPECTED_SOLVER_LANES
    assert lanes['smt_z3_cvc5']['blocked_claim_count'] == 10
    assert lanes['smt_z3_cvc5']['overall_status'] == 'blocked'
    assert lanes['tla_apalache']['overall_status'] == 'checked_bounded_model_only'
    assert lanes['tla_apalache']['missing'] == []
    assert lanes['tla_apalache']['public_source_result'] == 'solver_lane_checked_bounded_only'
    assert lanes['protocol_tamarin_proverif']['overall_status'] == 'blocked_optional_lane'
    assert set(lanes['protocol_tamarin_proverif']['missing']) == {'tamarin-prover', 'proverif'}
    assert lanes['proof_consumer_kernel']['overall_status'] == 'ready_lean_checked_coq_unavailable'
    assert lanes['proof_consumer_kernel']['missing'] == ['coqc']
    assert all(entry['public_source_result'] != 'production_release_approval' for entry in lanes.values())
