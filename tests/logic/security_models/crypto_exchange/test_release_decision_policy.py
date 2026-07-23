import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
    SECURITY_DECISION_POLICY_ARTIFACT,
    SECURITY_DECISION_POLICY_DOCUMENT,
    blocking_claim_is_secure_outcome,
    build_security_decision_policy,
    classify_release_consumer_outcome,
    decision_outcome_for_proof_status,
    release_policy_entries,
    security_decision_outcomes,
    validate_security_decision_policy,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport


REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_PATH = REPO_ROOT / SECURITY_DECISION_POLICY_ARTIFACT
DOC_PATH = REPO_ROOT / SECURITY_DECISION_POLICY_DOCUMENT


def _report(
    status: str,
    *,
    claim_id: str = 'no_unauthorized_withdrawal',
) -> ProofReport:
    solver_result = {
        'PROVED': 'unsat',
        'DISPROVED': 'sat',
        'UNKNOWN': 'unknown',
        'NOT_MODELED': 'not-modeled',
    }[status]
    return ProofReport(
        claim_id=claim_id,
        claim_version='1.0',
        model_cid='cid:model',
        model_schema_version='security-model-ir/v1',
        status=status,
        prover='z3',
        solver_name='z3',
        solver_version='4.test',
        solver_result=solver_result,
        proof_or_trace_cid='cid:proof',
        assumptions=['A3', 'A4', 'A5', 'A8'],
        compiler_cid='cid:compiler',
        risk='blocking',
        signatures=[],
        evidence_refs=[
            {
                'kind': 'test_fixture',
                'path': 'fixture.json',
                'review_status': 'trusted_fixture',
            }
        ],
        soundness_notes=[],
    )


def test_checked_in_security_decision_policy_matches_authoritative_builder() -> None:
    checked_in = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))
    expected = build_security_decision_policy()

    validate_security_decision_policy(checked_in)
    assert checked_in == expected
    assert checked_in['policy_document'] == SECURITY_DECISION_POLICY_DOCUMENT
    assert checked_in['artifact_path'] == SECURITY_DECISION_POLICY_ARTIFACT


def test_decision_policy_freezes_required_outcomes_and_security_semantics() -> None:
    outcomes = {outcome.outcome: outcome for outcome in security_decision_outcomes()}

    assert set(outcomes) == {
        'prove',
        'disprove',
        'unknown',
        'not-modeled',
        'stale-evidence',
        'missing-solver',
        'blocked-production',
    }
    assert outcomes['prove'].secure_for_blocking_claims is True
    assert blocking_claim_is_secure_outcome('prove') is True

    for outcome_id, outcome in outcomes.items():
        if outcome_id == 'prove':
            continue
        assert outcome.secure_for_blocking_claims is False
        assert outcome.production_release_effect == 'blocked-production'
        assert blocking_claim_is_secure_outcome(outcome_id) is False


@pytest.mark.parametrize(
    ('status', 'outcome', 'secure'),
    [
        ('PROVED', 'prove', True),
        ('DISPROVED', 'disprove', False),
        ('UNKNOWN', 'unknown', False),
        ('NOT_MODELED', 'not-modeled', False),
    ],
)
def test_proof_report_statuses_map_to_consumer_outcomes(
    status: str,
    outcome: str,
    secure: bool,
) -> None:
    assert decision_outcome_for_proof_status(status) == outcome

    decision = classify_release_consumer_outcome(_report(status), release_gate='blocking')

    assert decision['outcome'] == outcome
    assert decision['secure_for_release'] is secure
    if not secure:
        assert decision['consumer_result'] == 'non-secure'
        assert 'release consumers must treat non-proved blocking claims as non-secure' in decision['reasons']


def test_blocking_claims_fail_closed_for_stale_evidence_missing_solver_and_missing_report() -> None:
    stale = classify_release_consumer_outcome(
        _report('PROVED'),
        release_gate='blocking',
        evidence_current=False,
    )
    missing_solver = classify_release_consumer_outcome(
        _report('PROVED'),
        release_gate='blocking',
        solver_available=False,
    )
    missing_report = classify_release_consumer_outcome(None, release_gate='blocking')

    assert stale['outcome'] == 'stale-evidence'
    assert missing_solver['outcome'] == 'missing-solver'
    assert missing_report['outcome'] == 'blocked-production'
    assert stale['secure_for_release'] is False
    assert missing_solver['secure_for_release'] is False
    assert missing_report['secure_for_release'] is False


def test_proof_boundary_lists_all_release_claims_and_non_secure_blocking_outcomes() -> None:
    policy = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))
    boundary = policy['proof_boundary']
    release_claims = {entry.claim_id: entry for entry in release_policy_entries()}

    assert boundary['secure_blocking_outcome'] == 'prove'
    assert set(boundary['blocking_claims']) == {
        claim_id
        for claim_id, entry in release_claims.items()
        if entry.release_gate == 'blocking'
    }
    assert set(boundary['high_risk_claims']) == {
        claim_id
        for claim_id, entry in release_claims.items()
        if entry.release_gate == 'high'
    }
    assert set(boundary['non_secure_blocking_outcomes']) == {
        'disprove',
        'unknown',
        'not-modeled',
        'stale-evidence',
        'missing-solver',
        'blocked-production',
    }


def test_policy_document_defines_outcomes_and_consumer_rule() -> None:
    text = DOC_PATH.read_text(encoding='utf-8')

    assert SECURITY_DECISION_POLICY_ARTIFACT in text
    for outcome in (
        'prove',
        'disprove',
        'unknown',
        'not-modeled',
        'stale-evidence',
        'missing-solver',
        'blocked-production',
    ):
        assert f'`{outcome}`' in text
    assert 'must treat every non-`prove` outcome for a blocking claim as non-secure' in text
