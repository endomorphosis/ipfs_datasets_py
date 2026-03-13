import hashlib
import importlib
import os
import sys
import types

import pytest


def _purge_modules(prefix: str) -> None:
    for name in list(sys.modules.keys()):
        if name == prefix or name.startswith(prefix + "."):
            del sys.modules[name]


def _install_fake_ipfs_kit(factory):
    package = types.ModuleType("ipfs_kit_py")
    module = types.ModuleType("ipfs_kit_py.ipfs_kit")
    module.ipfs_kit = factory
    sys.modules["ipfs_kit_py"] = package
    sys.modules["ipfs_kit_py.ipfs_kit"] = module


def test_ipfs_kit_backend_uses_ipfs_add_and_extracts_nested_cid(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE", "0")

    _purge_modules("ipfs_datasets_py")

    calls = []

    class FakeKit:
        def ipfs_add(self, path, recursive=False, pin=False):
            calls.append({"path": path, "recursive": recursive, "pin": pin, "exists": os.path.isfile(path)})
            return {"success": True, "data": {"Hash": "bafykitcid"}}

    _install_fake_ipfs_kit(lambda **kwargs: FakeKit())

    ipfs_backend_router = importlib.import_module("ipfs_datasets_py.ipfs_backend_router")

    backend = ipfs_backend_router.get_ipfs_backend(use_cache=False)
    cid = backend.add_bytes(b"router review", pin=False)

    assert cid == "bafykitcid"
    assert calls == [{"path": calls[0]["path"], "recursive": False, "pin": False, "exists": True}]


def test_ipfs_kit_backend_uses_simulated_cid_for_non_pinned_add_failures(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_ROUTER_CACHE", "0")

    _purge_modules("ipfs_datasets_py")

    class FakeKit:
        def ipfs_add(self, path, recursive=False, pin=False):
            return {"success": False, "error": "backend offline"}

    _install_fake_ipfs_kit(lambda **kwargs: FakeKit())

    ipfs_backend_router = importlib.import_module("ipfs_datasets_py.ipfs_backend_router")

    backend = ipfs_backend_router.get_ipfs_backend(use_cache=False)
    payload = b"router review"
    cid = backend.add_bytes(payload, pin=False)

    assert cid == f"Qm{hashlib.sha256(payload).hexdigest()[:44]}"

    with pytest.raises(RuntimeError, match="backend offline"):
        backend.add_bytes(payload, pin=True)
