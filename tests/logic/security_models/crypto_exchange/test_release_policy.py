from ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy import (
    evaluate_release_policy,
    release_policy_entries,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport


def _report(
    claim_id: str,
    *,
    status: str = 'PROVED',
    assumptions: list[str] | None = None,
    evidence_refs: list[dict[str, str]] | None = None,
) -> ProofReport:
    return ProofReport(
        claim_id=claim_id,
        claim_version='1.0',
        model_cid='cid:model',
        model_schema_version='security-model-ir/v1',
        status=status,
        prover='z3',
        solver_name='z3',
        solver_version='4.test',
        solver_result='unsat' if status == 'PROVED' else 'unknown',
        proof_or_trace_cid='cid:proof',
        assumptions=assumptions or [],
        compiler_cid='cid:compiler',
        risk='blocking',
        signatures=[],
        evidence_refs=evidence_refs or [],
        soundness_notes=[],
    )


def _trusted_fixture_ref() -> dict[str, str]:
    return {
        'kind': 'test_fixture',
        'path': 'fixture.json',
        'review_status': 'trusted_fixture',
    }


def test_release_policy_classifies_default_claims() -> None:
    entries = release_policy_entries()
    by_claim = {entry.claim_id: entry for entry in entries}

    assert len(entries) == 8
    assert by_claim['no_unauthorized_withdrawal'].release_gate == 'blocking'
    assert by_claim['no_over_reserved_internal_account'].release_gate == 'blocking'
    assert by_claim['global_asset_conservation'].release_gate == 'blocking'
    assert by_claim['no_deposit_before_finality'].release_gate == 'high'
    assert by_claim['no_signing_request_after_wallet_freeze'].release_gate == 'high'
    assert by_claim['capability_delegation_no_authority_increase'].release_gate == 'high'
    assert by_claim['revoked_capability_no_future_authorization'].release_gate == 'high'
    assert by_claim['audit_event_exists_for_critical_transition'].release_gate == 'medium'


def test_release_policy_accepts_all_reviewed_proved_claims() -> None:
    reports = [
        _report(
            entry.claim_id,
            assumptions=list(entry.required_assumptions),
            evidence_refs=[_trusted_fixture_ref()],
        )
        for entry in release_policy_entries()
    ]

    evaluation = evaluate_release_policy(reports)

    assert evaluation['release_ready'] is True
    assert evaluation['gates']['blocking']['accepted'] == 3
    assert evaluation['gates']['high']['accepted'] == 4
    assert evaluation['gates']['medium']['accepted'] == 1
    assert evaluation['failures'] == []


def test_release_policy_fails_high_unknown_but_triages_medium_unknown() -> None:
    reports = []
    for entry in release_policy_entries():
        status = 'PROVED'
        if entry.claim_id == 'no_deposit_before_finality':
            status = 'UNKNOWN'
        if entry.claim_id == 'audit_event_exists_for_critical_transition':
            status = 'UNKNOWN'
        reports.append(
            _report(
                entry.claim_id,
                status=status,
                assumptions=list(entry.required_assumptions),
                evidence_refs=[_trusted_fixture_ref()],
            )
        )

    evaluation = evaluate_release_policy(reports)

    assert evaluation['release_ready'] is False
    assert evaluation['gates']['high']['failed'] == 1
    assert evaluation['gates']['medium']['attention'] == 1
    assert [item['claim_id'] for item in evaluation['failures']] == ['no_deposit_before_finality']
    assert [item['claim_id'] for item in evaluation['attention']] == ['audit_event_exists_for_critical_transition']


def test_release_policy_requires_reviewed_evidence_for_blocking_and_high_claims() -> None:
    reports = [
        _report(entry.claim_id, assumptions=list(entry.required_assumptions))
        for entry in release_policy_entries()
    ]

    strict_evaluation = evaluate_release_policy(reports)
    relaxed_evaluation = evaluate_release_policy(reports, require_reviewed_evidence=False)

    assert strict_evaluation['release_ready'] is False
    assert strict_evaluation['gates']['blocking']['failed'] == 3
    assert strict_evaluation['gates']['high']['failed'] == 4
    assert relaxed_evaluation['release_ready'] is True
