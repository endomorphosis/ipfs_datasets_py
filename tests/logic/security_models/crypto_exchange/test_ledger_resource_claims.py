import pytest
from copy import deepcopy

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.ledger import (
    GlobalAssetConservationClaim,
    NoDoubleSpendInternalBalanceClaim,
    NoOverReservedInternalAccountClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


pytest.importorskip('z3')



def test_double_spend_counterexample_is_found_for_non_atomic_reservation() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.accounts[0]['reservation_requests'] = [4, 4]
    report = Z3Runner().run_claim(NoOverReservedInternalAccountClaim(), model)
    assert report.status == 'DISPROVED'



def test_atomic_reservation_proves_balance_conservation() -> None:
    model = deepcopy(example_minimal_exchange_model())
    report = Z3Runner().run_claim(NoOverReservedInternalAccountClaim(), model)
    assert report.status == 'PROVED'



def test_all_asset_conservation_violation_is_detected() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.metadata['ledger_totals']['customer_liabilities']['asset:btc'] = 10
    report = Z3Runner().run_claim(GlobalAssetConservationClaim(), model)
    assert report.status == 'DISPROVED'


def test_backward_compatible_combined_ledger_claim_still_detects_violation() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.accounts[0]['reservation_requests'] = [4, 4]
    report = Z3Runner().run_claim(NoDoubleSpendInternalBalanceClaim(), model)
    assert report.status == 'DISPROVED'
