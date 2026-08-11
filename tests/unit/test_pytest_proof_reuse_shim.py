"""Tests for the cold optional proof-reuse bridge."""

from __future__ import annotations

import importlib.util
import types
from importlib.machinery import ModuleSpec

import pytest


_BRIDGE_PATH = importlib.util.find_spec("ipfs_datasets_py.pytest_proof_reuse").origin


def _load_bridge(
    monkeypatch: pytest.MonkeyPatch,
    importer,
    top_level_spec=None,
    plugin_spec=None,
):
    spec = importlib.util.spec_from_file_location("_proof_reuse_bridge_test", _BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("importlib.import_module", importer)
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: (
            top_level_spec
            if name == "ipfs_accelerate_py"
            else plugin_spec
            if name == "ipfs_accelerate_py.testing.proof_reuse.plugin"
            else None
        ),
    )
    spec.loader.exec_module(module)
    return module


def test_shim_registers_accelerator_canonically_without_reexporting_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = types.ModuleType("accelerator_plugin")
    plugin.pytest_addoption = lambda parser: None
    regular = ModuleSpec("ipfs_accelerate_py", loader=object(), origin="installed/__init__.py")
    import_calls: list[str] = []

    def importer(name: str):
        import_calls.append(name)
        return plugin

    bridge = _load_bridge(monkeypatch, importer, regular)
    assert import_calls == []
    assert bridge.PLUGIN_NAME == "ipfs-proof-reuse"

    class Manager:
        def __init__(self) -> None:
            self.plugins: dict[str, object] = {}

        def get_plugin(self, name):
            return self.plugins.get(name)

        def is_registered(self, registered):
            return registered in self.plugins.values()

        def register(self, registered, name):
            assert name == "ipfs-proof-reuse"
            self.plugins[name] = registered

    manager = Manager()
    bridge.pytest_addoption(object(), manager)
    bridge.pytest_configure(types.SimpleNamespace(pluginmanager=manager))
    assert import_calls == [bridge.ACCELERATOR_PLUGIN_MODULE]
    assert manager.plugins == {"ipfs-proof-reuse": plugin}


def test_shim_suppresses_only_absent_accelerator_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    def absent(_: str):
        raise ModuleNotFoundError("missing", name="ipfs_accelerate_py")

    bridge = _load_bridge(monkeypatch, absent)
    assert bridge._load_accelerator_plugin() is None

    namespace = ModuleSpec("ipfs_accelerate_py", loader=None, is_package=True)
    namespace.origin = None
    namespace.submodule_search_locations = []

    def empty_namespace(_: str):
        raise ModuleNotFoundError("missing testing", name="ipfs_accelerate_py.testing")

    bridge = _load_bridge(monkeypatch, empty_namespace, namespace)
    assert bridge._load_accelerator_plugin() is None

    regular = ModuleSpec("ipfs_accelerate_py", loader=object(), origin="installed/__init__.py")
    bridge = _load_bridge(monkeypatch, empty_namespace, regular)
    with pytest.raises(ModuleNotFoundError, match="missing testing"):
        bridge._load_accelerator_plugin()

    def broken(_: str):
        raise ModuleNotFoundError("missing dependency", name="required_transitive_dependency")

    bridge = _load_bridge(monkeypatch, broken, namespace)
    with pytest.raises(ModuleNotFoundError, match="missing dependency"):
        bridge._load_accelerator_plugin()


def test_shim_keeps_namespace_plugin_failures_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin found below PEP 420 parents is not optional absence."""

    namespace = ModuleSpec("ipfs_accelerate_py", loader=None, is_package=True)
    namespace.origin = None
    namespace.submodule_search_locations = []
    plugin = ModuleSpec(
        "ipfs_accelerate_py.testing.proof_reuse.plugin",
        loader=object(),
        origin="namespace-portion/plugin.py",
    )

    def broken(_: str):
        raise ModuleNotFoundError(
            "missing plugin dependency",
            name="ipfs_accelerate_py.testing.runtime_dependency",
        )

    bridge = _load_bridge(monkeypatch, broken, namespace, plugin)
    with pytest.raises(ModuleNotFoundError, match="missing plugin dependency"):
        bridge._load_accelerator_plugin()
