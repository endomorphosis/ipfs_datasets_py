from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import canonicalize_ir
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import SecurityModelIR


def test_canonicalization_is_stable() -> None:
    model = example_minimal_exchange_model()
    original = canonicalize_ir(model)
    shuffled = SecurityModelIR.from_dict(model.to_dict())
    assert canonicalize_ir(shuffled) == original
