import pytest
from copy import deepcopy

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.capability import (
    CapabilityDelegationMonotonicityClaim,
    RevokedCapabilityClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


pytest.importorskip('z3')



def test_revoked_capability_cannot_authorize_future_action() -> None:
    model = deepcopy(example_minimal_exchange_model())
    report = Z3Runner().run_claim(RevokedCapabilityClaim(), model)
    assert report.status == 'PROVED'



def test_missing_revocation_enforcement_finds_counterexample() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.capabilities[0]['revoked_before_action'] = True
    model.capabilities[0]['privileged_action_attempted'] = True
    model.policies = [policy for policy in model.policies if policy.get('name') != 'revocation_enforced']
    report = Z3Runner().run_claim(RevokedCapabilityClaim(), model)
    assert report.status == 'DISPROVED'



def test_second_capability_violation_is_detected() -> None:
    model = deepcopy(example_minimal_exchange_model())
    violating = deepcopy(model.capabilities[0])
    violating['id'] = 'cap:withdraw:second'
    violating['delegated_resources'] = ['wallet:exchange_hot']
    model.capabilities.append(violating)
    report = Z3Runner().run_claim(CapabilityDelegationMonotonicityClaim(), model)
    assert report.status == 'DISPROVED'



def test_expired_capability_cannot_authorize() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.capabilities[0]['expired'] = True
    model.capabilities[0]['privileged_action_attempted'] = True
    report = Z3Runner().run_claim(RevokedCapabilityClaim(), model)
    assert report.status == 'DISPROVED'
