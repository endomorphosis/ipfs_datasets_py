import pytest
from copy import deepcopy

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.ledger import NoDoubleSpendInternalBalanceClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


pytest.importorskip('z3')


def test_double_spend_counterexample_is_found_for_non_atomic_reservation() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.accounts[0]['reservation_requests'] = [4, 4]
    model.policies = [policy for policy in model.policies if policy.get('name') != 'atomic_reservation']
    report = Z3Runner().run_claim(NoDoubleSpendInternalBalanceClaim(), model)
    assert report.status == 'DISPROVED'


def test_atomic_reservation_proves_balance_conservation() -> None:
    model = deepcopy(example_minimal_exchange_model())
    report = Z3Runner().run_claim(NoDoubleSpendInternalBalanceClaim(), model)
    assert report.status == 'PROVED'
