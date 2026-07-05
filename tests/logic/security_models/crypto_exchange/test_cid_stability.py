import importlib
import json
import types
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir import cid as cid_module
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport


REPO_ROOT = Path(__file__).resolve().parents[4]
TEST_VECTOR_DIR = REPO_ROOT / 'docs' / 'security_verification' / 'test_vectors'


def _raise_import_error(name: str):
    raise ImportError(name)



def test_model_cid_is_stable() -> None:
    model = example_minimal_exchange_model()
    assert cid_module.calculate_model_cid(model) == cid_module.calculate_model_cid(model.to_dict())


def test_model_cid_matches_committed_test_vector() -> None:
    model = example_minimal_exchange_model()
    expected_cid = (TEST_VECTOR_DIR / 'security_model_minimal.cid.txt').read_text(encoding='utf-8').strip()
    assert cid_module.calculate_model_cid(model) == expected_cid



def test_sha256_fallback_is_stable_when_cid_utility_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(cid_module, 'import_module', _raise_import_error)
    model = example_minimal_exchange_model()
    cid_value = cid_module.calculate_model_cid(model)
    assert cid_value.startswith('sha256:')
    assert cid_value == cid_module.calculate_model_cid(model)



def test_module_import_remains_safe_without_cid_dependencies() -> None:
    reloaded = importlib.reload(cid_module)
    assert reloaded.calculate_artifact_cid({'hello': 'world'})



def test_model_cid_is_stable_with_cid_utility_present(monkeypatch) -> None:
    fake_module = types.SimpleNamespace(cid_for_bytes=lambda payload: f'cid:{len(payload)}')
    monkeypatch.setattr(cid_module, 'import_module', lambda name: fake_module)
    model = example_minimal_exchange_model()
    assert cid_module.calculate_model_cid(model) == cid_module.calculate_model_cid(model)
    assert cid_module.calculate_model_cid(model).startswith('cid:')


def test_proof_report_deterministic_cid_matches_committed_test_vector() -> None:
    payload = json.loads((TEST_VECTOR_DIR / 'proof_report_minimal.json').read_text(encoding='utf-8'))
    expected_cid = (TEST_VECTOR_DIR / 'proof_report_minimal.deterministic_cid.txt').read_text(encoding='utf-8').strip()
    report = ProofReport.from_dict(payload)
    assert report.deterministic_payload_cid == expected_cid
