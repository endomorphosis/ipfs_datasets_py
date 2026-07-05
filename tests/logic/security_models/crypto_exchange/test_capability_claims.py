import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.capability import RevokedCapabilityClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


z3 = pytest.importorskip('z3')


def test_revoked_capability_cannot_authorize_future_action() -> None:
    _ = z3
    model = example_minimal_exchange_model()
    report = Z3Runner().run_claim(RevokedCapabilityClaim(), model)
    assert report.status == 'PROVED'


def test_missing_revocation_enforcement_finds_counterexample() -> None:
    _ = z3
    model = example_minimal_exchange_model()
    model.capabilities[0]['revoked_before_action'] = True
    model.policies = [policy for policy in model.policies if policy.get('name') != 'revocation_enforced']
    report = Z3Runner().run_claim(RevokedCapabilityClaim(), model)
    assert report.status == 'DISPROVED'
