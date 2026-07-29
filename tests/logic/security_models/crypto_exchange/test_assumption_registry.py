from copy import deepcopy

from ipfs_datasets_py.logic.security_models.crypto_exchange.assumption_registry import (
    evaluate_assumption_registry,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model


AS_OF = '2026-07-07T00:00:00Z'


def test_assumption_registry_accepts_default_owned_current_assumptions() -> None:
    model = example_minimal_exchange_model()

    evaluation = evaluate_assumption_registry(
        model,
        required_assumptions=['A3', 'A4', 'A5'],
        as_of=AS_OF,
    )

    assert evaluation['release_ready'] is True
    assert evaluation['summary']['total'] == 3
    assert evaluation['summary']['owned'] == 3
    assert evaluation['summary']['evidenced'] == 3
    assert evaluation['summary']['current'] == 3
    assert evaluation['failures'] == []


def test_assumption_registry_fails_stale_evidence() -> None:
    model = deepcopy(example_minimal_exchange_model())
    for assumption in model.assumptions:
        if isinstance(assumption, dict) and assumption['id'] == 'A4':
            assumption['last_reviewed_at'] = '2025-01-01T00:00:00Z'
            assumption['evidence_expires_at'] = '2026-01-01T00:00:00Z'

    evaluation = evaluate_assumption_registry(model, required_assumptions=['A4'], as_of=AS_OF)

    assert evaluation['release_ready'] is False
    assert evaluation['summary']['stale'] == 1
    assert evaluation['failures'][0]['assumption_id'] == 'A4'
    assert 'evidence is stale' in evaluation['failures'][0]['reasons']


def test_assumption_registry_flags_string_only_legacy_assumptions_as_not_production_ready() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.assumptions = ['A4']

    evaluation = evaluate_assumption_registry(model, required_assumptions=['A4'], as_of=AS_OF)

    assert evaluation['release_ready'] is False
    assert evaluation['summary']['owned'] == 0
    assert evaluation['summary']['evidenced'] == 0
    assert evaluation['summary']['current'] == 0
    assert evaluation['failures'][0]['reasons'] == [
        'missing operational owner',
        'missing evidence references',
        'missing evidence_expires_at',
    ]


def test_assumption_registry_can_require_explicit_accepted_assumptions() -> None:
    model = example_minimal_exchange_model()

    evaluation = evaluate_assumption_registry(
        model,
        required_assumptions=['A4', 'A5'],
        accepted_assumptions=['A4'],
        as_of=AS_OF,
    )

    assert evaluation['release_ready'] is False
    assert evaluation['summary']['accepted'] == 1
    assert evaluation['failures'][0]['assumption_id'] == 'A5'
    assert 'assumption was not accepted' in evaluation['failures'][0]['reasons']
