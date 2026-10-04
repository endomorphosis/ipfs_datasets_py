"""Native imports do not initialize the optional neural prover or its config."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


PACKAGE = "ipfs_datasets_py.logic.external_provers"
EXPORTS = ("SymbolicAIProverBridge", "SYMBOLICAI_AVAILABLE", "NeuralProofResult")
ROOT = Path(__file__).resolve().parents[4]


def test_canonical_native_imports_never_load_neural_or_symai_in_fresh_python():
    source = r'''
import importlib.abc, json, sys
sys.path.insert(0, sys.argv[1])
attempted = []
class DenyNeural(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if (fullname == "symai" or fullname.startswith("symai.")
                or fullname.startswith("ipfs_datasets_py.logic.external_provers.neural")
                or fullname == "ipfs_datasets_py.utils.symai_config"):
            attempted.append(fullname)
            raise AssertionError("native import initialized optional neural dependency: " + fullname)
sys.meta_path.insert(0, DenyNeural())
def audit(event, arguments):
    if event == "open" and ".symai" in str(arguments[0]):
        raise AssertionError("native import accessed SymbolicAI configuration")
sys.addaudithook(audit)
from ipfs_datasets_py.logic.backends.kernel.isabelle import IsabelleKernelBackend
from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend
from ipfs_datasets_py.logic.backends.kernel.rocq import RocqKernelBackend
import ipfs_datasets_py.logic.external_provers as package
assert package.check_prover_availability("not-a-prover") is False
for name in ("Z3", "CVC5", "Lean", "Coq"):
    package.check_prover_availability(name)
assert not attempted
assert not any(name in package.__dict__ for name in (
    "SymbolicAIProverBridge", "SYMBOLICAI_AVAILABLE", "NeuralProofResult"))
assert set(("SymbolicAIProverBridge", "SYMBOLICAI_AVAILABLE", "NeuralProofResult")) <= set(dir(package))
print(json.dumps({"attempted": attempted, "isabelle": IsabelleKernelBackend.__name__}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", source, str(ROOT)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        "attempted": [], "isabelle": "IsabelleKernelBackend"}


@pytest.fixture
def package(monkeypatch):
    module = importlib.import_module(PACKAGE)
    previous = {name: module.__dict__[name] for name in EXPORTS if name in module.__dict__}
    for name in EXPORTS:
        module.__dict__.pop(name, None)
    yield module
    for name in EXPORTS:
        module.__dict__.pop(name, None)
    module.__dict__.update(previous)


def loader(monkeypatch, package, *, error=None, available=True):
    calls = []
    values = SimpleNamespace(SymbolicAIProverBridge=type("Bridge", (), {}),
                             NeuralProofResult=type("Result", (), {}),
                             SYMBOLICAI_AVAILABLE=available)

    def load(name, parent=None):
        calls.append((name, parent))
        if error is not None:
            raise error
        return values

    monkeypatch.setattr(package, "importlib", SimpleNamespace(import_module=load))
    return calls, values


@pytest.mark.parametrize("first_name", EXPORTS)
def test_explicit_named_exports_load_once_and_preserve_identity(package, monkeypatch, first_name):
    calls, values = loader(monkeypatch, package)
    namespace = {}
    exec(f"from {PACKAGE} import {first_name}", namespace)
    assert namespace[first_name] is getattr(values, first_name)
    for name in EXPORTS:
        assert name in package.__all__
        assert getattr(package, name) is getattr(values, name)
    assert calls == [(".neural.symbolicai_prover_bridge", PACKAGE)]


def test_optional_import_absence_caches_legacy_fallback(package, monkeypatch):
    calls, _ = loader(monkeypatch, package, error=ModuleNotFoundError("optional dependency missing"))
    assert package.SymbolicAIProverBridge is None
    assert package.NeuralProofResult is None
    assert package.SYMBOLICAI_AVAILABLE is False
    assert package.check_prover_availability("SymbolicAI") is False
    assert "SymbolicAI" not in package.get_available_provers()
    assert len(calls) == 1


@pytest.mark.parametrize("error", [PermissionError("optional config is not writable"),
                                   RuntimeError("optional backend initialization failed"),
                                   KeyboardInterrupt(), SystemExit(7)])
def test_explicit_neural_initialization_failures_are_not_swallowed(package, monkeypatch, error):
    calls, _ = loader(monkeypatch, package, error=error)
    with pytest.raises(type(error)) as caught:
        package.SymbolicAIProverBridge
    assert caught.value is error
    assert not any(name in package.__dict__ for name in EXPORTS)
    assert len(calls) == 1


def test_native_availability_and_unknown_attributes_remain_neural_free(package, monkeypatch):
    calls, _ = loader(monkeypatch, package)
    for name in ("Z3", "CVC5", "Lean", "Coq", "unknown"):
        assert isinstance(package.check_prover_availability(name), bool)
    with pytest.raises(AttributeError, match="has no attribute"):
        package.MissingProver
    assert set(EXPORTS) <= set(dir(package))
    assert not calls


@pytest.mark.parametrize("available", [False, True])
def test_full_availability_and_symbolicai_check_resolve_and_cache_neural(package, monkeypatch, available):
    calls, _ = loader(monkeypatch, package, available=available)
    assert ("SymbolicAI" in package.get_available_provers()) is available
    assert package.check_prover_availability("symbolicai") is available
    assert len(calls) == 1
