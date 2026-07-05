from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import validate_ir


def test_ir_schema_validates_example_model() -> None:
    model = example_minimal_exchange_model()
    validated = validate_ir(model)
    assert validated.model_id == 'minimal-btc-exchange'
    assert validated.assumptions
    assert validated.policies
