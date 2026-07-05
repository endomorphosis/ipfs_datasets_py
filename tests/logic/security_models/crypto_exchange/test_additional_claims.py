import pytest
from copy import deepcopy

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.capability import CapabilityDelegationMonotonicityClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.deposit import NoDepositCreditedBeforeFinalityClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.hsm import NoSigningAfterWalletFreezeClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.ledger import AuditEventExistsForCriticalTransitionClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import (
    DEFAULT_PROVERS,
    _normalize_provers,
    prove_claims,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.proverif_runner import ProVerifRunner
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
    model.events.append({'event': 'signing_request', 'wallet_id': 'wallet:user_alice'})
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


def test_prove_claims_proves_complete_default_z3_claim_set() -> None:
    reports = prove_claims(example_minimal_exchange_model(), ['z3'])
    assert [report.claim_id for report in reports] == [claim.claim_id for claim in default_claims()]
    assert all(report.status == 'PROVED' for report in reports)


def test_default_prover_list_includes_proverif_stub() -> None:
    assert 'proverif' in DEFAULT_PROVERS
    assert 'proverif' in example_minimal_exchange_model().prover_targets


def test_prove_claims_falls_through_when_z3_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted_claims: list[str] = []

    def _stub_proverif_run(self, claim, model):
        attempted_claims.append(claim.claim_id)
        return self.unknown_report(claim, model, 'stubbed proverif fallback')

    monkeypatch.setattr(Z3Runner, 'is_available', staticmethod(lambda: False))
    monkeypatch.setattr(ProVerifRunner, 'run_claim', _stub_proverif_run)
    reports = prove_claims(example_minimal_exchange_model(), ['z3', 'proverif'])
    assert attempted_claims == [claim.claim_id for claim in default_claims()]
    assert all(report.prover == ProVerifRunner.prover_name for report in reports)


def test_normalize_provers_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match='Unsupported provers: fake'):
        _normalize_provers(['z3', 'fake'])
