from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    DEFAULT_THREAT_MODEL_ASSUMPTIONS,
    validate_ir_payload,
    validate_ir,
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
