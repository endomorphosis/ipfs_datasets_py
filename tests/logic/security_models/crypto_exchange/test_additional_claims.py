import pytest
from copy import deepcopy

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.capability import CapabilityDelegationMonotonicityClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.deposit import NoDepositCreditedBeforeFinalityClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.hsm import NoSigningAfterWalletFreezeClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.ledger import AuditEventExistsForCriticalTransitionClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.withdrawal import NoUnauthorizedWithdrawalClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import DEFAULT_PROVERS, _normalize_provers, prove_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


pytest.importorskip('z3')

ESCALATED_DELEGATED_AUTHORITY = 4



def test_good_model_proves_remaining_claims() -> None:
    model = deepcopy(example_minimal_exchange_model())
    claim_types = (
        NoDepositCreditedBeforeFinalityClaim,
        NoSigningAfterWalletFreezeClaim,
        CapabilityDelegationMonotonicityClaim,
        AuditEventExistsForCriticalTransitionClaim,
    )
    for claim_type in claim_types:
        report = Z3Runner().run_claim(claim_type(), model)
        assert report.status == 'PROVED'



def test_bad_model_finds_deposit_before_finality_counterexample() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.events = [
        event
        for event in model.events
        if not (event.get('event') == 'deposit_finalized' and event.get('txid') == 'tx:1')
    ]
    report = Z3Runner().run_claim(NoDepositCreditedBeforeFinalityClaim(), model)
    assert report.status == 'DISPROVED'



def test_bad_model_finds_signing_after_freeze_counterexample() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.events.append({'id': 'event:sign:1', 'event': 'signing_request', 'wallet_id': 'wallet:user_alice', 'timestamp': 11})
    report = Z3Runner().run_claim(NoSigningAfterWalletFreezeClaim(), model)
    assert report.status == 'DISPROVED'



def test_bad_model_finds_capability_authority_escalation() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.capabilities[0]['delegated_authority'] = ESCALATED_DELEGATED_AUTHORITY
    report = Z3Runner().run_claim(CapabilityDelegationMonotonicityClaim(), model)
    assert report.status == 'DISPROVED'



def test_bad_model_finds_missing_audit_for_critical_transition() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.events = [event for event in model.events if event.get('event') != 'audit_logged']
    report = Z3Runner().run_claim(AuditEventExistsForCriticalTransitionClaim(), model)
    assert report.status == 'DISPROVED'



def test_bad_withdrawal_counterexample_names_violating_withdrawal_id() -> None:
    model = deepcopy(example_minimal_exchange_model())
    broadcast = next(event for event in model.events if event.get('event') == 'withdrawal_broadcast')
    broadcast['authorized'] = False
    report = Z3Runner().run_claim(NoUnauthorizedWithdrawalClaim(), model)
    assert report.status == 'DISPROVED'
    assert report.counterexample is not None
    assert report.counterexample['compiler_artifact']['violating_withdrawals'] == ['withdrawal:1']
    assert any(fact.get('withdrawal_id') == 'withdrawal:1' for fact in report.counterexample['source_facts'])



def test_prove_claims_proves_complete_default_z3_claim_set() -> None:
    reports = prove_claims(example_minimal_exchange_model(), ['z3'])
    assert [report.claim_id for report in reports] == [claim.claim_id for claim in default_claims()]
    assert all(report.status == 'PROVED' for report in reports)



def test_proved_or_disproved_reports_always_include_evidence_or_soundness_note() -> None:
    reports = prove_claims(example_minimal_exchange_model(), ['z3'])
    for report in reports:
        if report.status not in {'PROVED', 'DISPROVED'}:
            continue
        assert report.evidence_refs or report.soundness_notes



def test_default_prover_list_is_limited_to_implemented_runners() -> None:
    assert DEFAULT_PROVERS == ('z3',)
    assert example_minimal_exchange_model().prover_targets == ['z3']



def test_prove_claims_returns_unknown_reports_when_z3_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Z3Runner, 'is_available', staticmethod(lambda: False))
    reports = prove_claims(example_minimal_exchange_model(), ['z3'])
    assert [report.claim_id for report in reports] == [claim.claim_id for claim in default_claims()]
    assert all(report.prover == Z3Runner.prover_name for report in reports)
    assert all(report.status == 'UNKNOWN' for report in reports)



def test_prove_claims_preserves_unknown_when_z3_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Z3Runner,
        'run_claim',
        lambda self, claim, model: self.unknown_report(claim, model, 'forced z3 unknown'),
    )
    reports = prove_claims(example_minimal_exchange_model(), ['z3'])
    assert [report.claim_id for report in reports] == [claim.claim_id for claim in default_claims()]
    assert all(report.prover == Z3Runner.prover_name for report in reports)
    assert all(report.status == 'UNKNOWN' for report in reports)



def test_default_claims_return_not_modeled_when_required_domains_are_missing() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.events = []
    model.capabilities = []
    model.accounts = []
    reports = prove_claims(model, ['z3'])
    status_by_claim = {report.claim_id: report.status for report in reports}
    assert status_by_claim['no_double_spend_internal_balance'] == 'NOT_MODELED'
    assert status_by_claim['no_deposit_before_finality'] == 'NOT_MODELED'
    assert status_by_claim['no_signing_request_after_wallet_freeze'] == 'NOT_MODELED'
    assert status_by_claim['capability_delegation_no_authority_increase'] == 'NOT_MODELED'
    assert status_by_claim['revoked_capability_no_future_authorization'] == 'NOT_MODELED'
    assert status_by_claim['audit_event_exists_for_critical_transition'] == 'NOT_MODELED'



def test_normalize_provers_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match='Unsupported provers: fake'):
        _normalize_provers(['z3', 'fake'])
