from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model


def test_model_cid_is_stable() -> None:
    model = example_minimal_exchange_model()
    assert calculate_model_cid(model) == calculate_model_cid(model.to_dict())
