from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    DEFAULT_THREAT_MODEL_ASSUMPTIONS,
    SecurityModelIR,
    validate_event_registry,
    validate_ir_payload,
    validate_ir,
    validate_state_machines,
)



def test_ir_schema_validates_example_model() -> None:
    model = example_minimal_exchange_model()
    validated = validate_ir(model)
    assert validated.model_id == 'minimal-btc-exchange'
    assert validated.assumptions
    assert validated.policies
    assert validated.assumptions == DEFAULT_THREAT_MODEL_ASSUMPTIONS
    assert all(policy['evidence_refs'] for policy in validated.policies)
    assumption_ids = [
        assumption if isinstance(assumption, str) else assumption['id']
        for assumption in validated.assumptions
    ]
    assert assumption_ids == [f'A{index}' for index in range(1, 11)]


@pytest.mark.parametrize(
    ('mutator', 'message'),
    [
        (lambda payload: payload.pop('events'), 'Missing required top-level SecurityModelIR field'),
        (lambda payload: payload.__setitem__('unexpected_field', True), 'Unknown top-level SecurityModelIR field'),
        (lambda payload: payload.__setitem__('metadata', 'not-a-dict'), 'metadata must be a dict'),
        (lambda payload: payload['events'].__setitem__(0, 'not-a-dict'), 'events\\[0\\] must be a dict'),
        (lambda payload: payload.__setitem__('capablities', []), 'Unknown top-level SecurityModelIR field'),
    ],
)
def test_validate_ir_payload_strict_rejects_invalid_top_level_payloads(mutator, message: str) -> None:
    payload = deepcopy(example_minimal_exchange_model().to_dict())
    mutator(payload)
    with pytest.raises(ValueError, match=message):
        validate_ir_payload(payload, strict=True)


def test_from_untrusted_dict_uses_strict_payload_validation() -> None:
    payload = deepcopy(example_minimal_exchange_model().to_dict())
    payload['proover_targets'] = ['z3']
    with pytest.raises(ValueError, match='Unknown top-level SecurityModelIR field'):
        SecurityModelIR.from_untrusted_dict(payload, strict=True)



def test_validate_event_registry_allows_custom_events_only_in_non_strict_mode() -> None:
    custom_event = {
        'id': 'event:custom:1',
        'event': 'custom_security_event',
        'custom': True,
        'description': 'Modeled extension event.',
    }
    assert validate_event_registry([custom_event]) == []
    assert validate_event_registry([custom_event], strict=True) == [
        "event event:custom:1 uses unknown event type 'custom_security_event'"
    ]



def test_validate_event_registry_rejects_unknown_events_without_custom_metadata() -> None:
    errors = validate_event_registry([{'id': 'event:custom:bad', 'event': 'custom_security_event'}])
    assert errors == [
        "event event:custom:bad uses unknown event type 'custom_security_event' without custom modeling metadata"
    ]



def test_validate_state_machines_reports_empty_and_invalid_current() -> None:
    errors = validate_state_machines([
        {'id': 'sm:empty', 'states': [], 'current': None},
        {'id': 'sm:bad-current', 'states': ['requested'], 'current': 'missing'},
    ])
    assert errors == [
        'state_machine sm:empty.states must not be empty',
        'state_machine sm:bad-current.current must be present in state_machine.states',
    ]
