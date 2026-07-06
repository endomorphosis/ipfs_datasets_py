import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import canonicalize_ir
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import SecurityModelIR


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / 'pytest.ini').exists():
            return candidate
    raise RuntimeError('repository root not found')


REPO_ROOT = _repo_root()
TEST_VECTOR_DIR = REPO_ROOT / 'docs' / 'security_verification' / 'test_vectors'


def test_canonicalization_is_stable() -> None:
    model = example_minimal_exchange_model()
    original = canonicalize_ir(model)
    shuffled = SecurityModelIR.from_dict(model.to_dict())
    assert canonicalize_ir(shuffled) == original


def test_canonicalization_matches_committed_test_vector() -> None:
    model = example_minimal_exchange_model()
    committed_vector = json.loads(
        (TEST_VECTOR_DIR / 'security_model_minimal.canonical.json').read_text(encoding='utf-8')
    )
    assert json.loads(canonicalize_ir(model).decode('utf-8')) == committed_vector
