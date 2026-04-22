import builtins
import importlib
import sys
import types


_MISSING = object()


def _reload_with_mocked(module_path: str, mocked: dict[str, object]):
    original_modules: dict[str, object] = {}
    for name, value in mocked.items():
        original_modules[name] = sys.modules.pop(name, _MISSING)
        sys.modules[name] = value

    original_target = sys.modules.pop(module_path, _MISSING)

    try:
        return importlib.import_module(module_path)
    finally:
        if original_target is _MISSING:
            sys.modules.pop(module_path, None)
        else:
            sys.modules[module_path] = original_target

        for name, value in original_modules.items():
            if value is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_ipfs_simple_api_retries_after_fastapi_install(monkeypatch):
    import ipfs_kit_py.high_level_api as high_level_api
    import ipfs_datasets_py.auto_installer as auto_installer

    install_calls: list[tuple[str, str]] = []

    class DummyImpl:
        pass

    class DummyLoader:
        def __init__(self):
            self.exec_calls = 0

        def exec_module(self, module):
            self.exec_calls += 1
            if self.exec_calls == 1:
                raise ModuleNotFoundError("No module named 'fastapi'", name="fastapi")
            module.IPFSSimpleAPI = DummyImpl

    loader = DummyLoader()
    dummy_spec = types.SimpleNamespace(loader=loader)

    monkeypatch.setattr(high_level_api, "_IPFS_SIMPLE_API_IMPL", None)
    monkeypatch.setattr(high_level_api, "_IPFS_SIMPLE_API_LOAD_ATTEMPTED", False)
    monkeypatch.setattr(high_level_api, "_IPFS_SIMPLE_API_LOAD_ERROR", None)
    monkeypatch.setattr(
        high_level_api.importlib.util,
        "spec_from_file_location",
        lambda *args, **kwargs: dummy_spec,
    )
    monkeypatch.setattr(
        high_level_api.importlib.util,
        "module_from_spec",
        lambda spec: types.ModuleType("ipfs_kit_py._high_level_api_impl"),
    )
    monkeypatch.setattr(
        auto_installer,
        "ensure_module",
        lambda module_name, package_name=None, **kwargs: install_calls.append((module_name, package_name)) or object(),
    )
    sys.modules.pop("ipfs_kit_py._high_level_api_impl", None)

    impl = high_level_api._try_load_ipfs_simple_api()

    assert impl is DummyImpl
    assert loader.exec_calls == 2
    assert install_calls == [("fastapi", "fastapi")]


def test_modal_logic_extension_installs_symai_after_permission_error(monkeypatch):
    module_path = "ipfs_datasets_py.logic.integration.converters.modal_logic_extension"
    original_import = builtins.__import__
    import_attempts = {"symai": 0}
    install_calls: list[str] = []
    ensure_calls: list[str] = []

    fake_symai = types.ModuleType("symai")

    class FakeSymbol:
        def __init__(self, value: str, semantic: bool = False, **kwargs):
            self.value = value
            self.semantic = semantic

    class FakeExpression:
        pass

    fake_symai.Symbol = FakeSymbol
    fake_symai.Expression = FakeExpression

    fake_symai_config = types.ModuleType("ipfs_datasets_py.utils.symai_config")
    fake_symai_config.ensure_symai_config_for_import = lambda *args, **kwargs: ensure_calls.append("called") or None

    installer = types.SimpleNamespace(
        auto_install=True,
        install_python_dependency=lambda package_spec: install_calls.append(package_spec) or True,
    )
    fake_auto_installer = types.ModuleType("ipfs_datasets_py.auto_installer")
    fake_auto_installer.get_installer = lambda: installer

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "symai":
            import_attempts["symai"] += 1
            if import_attempts["symai"] == 1:
                raise PermissionError("[Errno 13] Permission denied: '/usr/.symai'")
            return fake_symai
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", controlled_import)

    new_mod = _reload_with_mocked(
        module_path,
        {
            "ipfs_datasets_py.auto_installer": fake_auto_installer,
            "ipfs_datasets_py.utils.symai_config": fake_symai_config,
            "symai": fake_symai,
        },
    )

    assert new_mod.SYMBOLIC_AI_AVAILABLE is True
    assert import_attempts["symai"] == 2
    assert install_calls == ["symbolicai>=1.14.0,<2.0.0"]
    assert ensure_calls == ["called", "called"]