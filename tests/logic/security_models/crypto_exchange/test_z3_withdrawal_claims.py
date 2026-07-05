import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.withdrawal import NoUnauthorizedWithdrawalClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


pytest.importorskip('z3')


def test_bad_model_finds_unauthorized_withdrawal_counterexample() -> None:
    model = example_minimal_exchange_model()
    model.policies = [policy for policy in model.policies if policy.get('name') != 'authorization_required']
    report = Z3Runner().run_claim(NoUnauthorizedWithdrawalClaim(), model)
    assert report.status == 'DISPROVED'
    assert report.counterexample


def test_good_model_proves_withdrawal_requires_authorization() -> None:
    model = example_minimal_exchange_model()
    report = Z3Runner().run_claim(NoUnauthorizedWithdrawalClaim(), model)
    assert report.status == 'PROVED'
