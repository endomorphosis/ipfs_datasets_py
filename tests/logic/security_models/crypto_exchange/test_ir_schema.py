from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    DEFAULT_THREAT_MODEL_ASSUMPTIONS,
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
