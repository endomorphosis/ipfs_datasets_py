import types
import importlib.util
import sys


def test_dependency_installer_honors_legacy_auto_install_truthy(monkeypatch):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.delenv("IPFS_DATASETS_AUTO_INSTALL", raising=False)
    monkeypatch.setenv("IPFS_AUTO_INSTALL", "yes")

    installer = auto_installer.DependencyInstaller(auto_install=None)

    assert installer.auto_install is True


def test_get_installer_uses_shared_truthy_env_parser(monkeypatch):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.setattr(auto_installer, "_installer", None)
    monkeypatch.setenv("IPFS_DATASETS_AUTO_INSTALL", "1")
    monkeypatch.setenv("IPFS_INSTALL_VERBOSE", "on")

    installer = auto_installer.get_installer()

    assert installer.auto_install is True
    assert installer.verbose is True


def test_web_scraper_packages_install_lxml_clean_companion(monkeypatch):
    import ipfs_datasets_py.auto_installer as auto_installer

    installer = auto_installer.DependencyInstaller(auto_install=True)
    installed_specs: list[str] = []
    monkeypatch.setattr(
        installer,
        "_pip_install",
        lambda package_spec: installed_specs.append(package_spec) or True,
    )

    assert installer.install_python_dependency("newspaper3k") is True

    assert "newspaper3k>=0.2.8,<1.0.0" in installed_specs
    assert "lxml_html_clean>=0.4.0" in installed_specs


def test_test_component_installs_pytest_extras(monkeypatch):
    import ipfs_datasets_py.auto_installer as auto_installer

    installer = auto_installer.DependencyInstaller(auto_install=True)
    ensured: list[tuple[str, str | None, tuple[str, ...]]] = []
    monkeypatch.setattr(auto_installer, "_installer", installer)

    def _fake_ensure_dependency(module_name, package_name=None, system_deps=None):
        ensured.append((module_name, package_name, tuple(system_deps or ())))
        return True, object()

    monkeypatch.setattr(installer, "ensure_dependency", _fake_ensure_dependency)

    assert auto_installer.install_for_component("test") is True

    assert ("pytest_asyncio", "pytest-asyncio", ()) in ensured
    assert ("pytest_mock", "pytest-mock", ()) in ensured
    assert ("hypothesis", "hypothesis", ()) in ensured


def test_runtime_installer_runs_when_marker_missing(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.setenv("IPFS_DATASETS_ENSURE_INSTALLER", "1")
    marker_path = tmp_path / "runtime_installer_state.json"
    calls: list[str] = []

    module = types.SimpleNamespace(
        ensure_main_ipfs_kit_py=lambda: calls.append("ensure_main_ipfs_kit_py"),
        ensure_libp2p_main=lambda: calls.append("ensure_libp2p_main"),
        ensure_ipfs_accelerate_py=lambda: calls.append("ensure_ipfs_accelerate_py"),
    )

    monkeypatch.setattr(auto_installer, "_runtime_installer_marker_path", lambda: marker_path)
    monkeypatch.setattr(auto_installer, "_current_repo_revision", lambda: "rev-a")
    monkeypatch.setattr(auto_installer, "_load_setup_install_module", lambda: module)

    changed = auto_installer.ensure_repo_installer_current()

    assert changed is True
    assert calls == [
        "ensure_main_ipfs_kit_py",
        "ensure_libp2p_main",
        "ensure_ipfs_accelerate_py",
    ]
    state = auto_installer._load_runtime_installer_state()
    assert state["repo_revision"] == "rev-a"
    assert state["status"] == "success"


def test_runtime_installer_skips_by_default_when_auto_install_disabled(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.delenv("IPFS_DATASETS_ENSURE_INSTALLER", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_AUTO_INSTALL", "false")
    monkeypatch.setenv("IPFS_AUTO_INSTALL", "false")

    marker_path = tmp_path / "runtime_installer_state.json"
    calls: list[str] = []
    module = types.SimpleNamespace(
        ensure_main_ipfs_kit_py=lambda: calls.append("ensure_main_ipfs_kit_py"),
        ensure_libp2p_main=lambda: calls.append("ensure_libp2p_main"),
        ensure_ipfs_accelerate_py=lambda: calls.append("ensure_ipfs_accelerate_py"),
    )

    monkeypatch.setattr(auto_installer, "_runtime_installer_marker_path", lambda: marker_path)
    monkeypatch.setattr(auto_installer, "_current_repo_revision", lambda: "rev-a")
    monkeypatch.setattr(auto_installer, "_load_setup_install_module", lambda: module)

    changed = auto_installer.ensure_repo_installer_current()

    assert changed is False
    assert calls == []
    assert not marker_path.exists()


def test_runtime_installer_skips_when_marker_matches_revision(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.setenv("IPFS_DATASETS_ENSURE_INSTALLER", "1")
    marker_path = tmp_path / "runtime_installer_state.json"
    auto_installer._save_runtime_installer_state = auto_installer._save_runtime_installer_state
    monkeypatch.setattr(auto_installer, "_runtime_installer_marker_path", lambda: marker_path)
    auto_installer._save_runtime_installer_state(
        {
            "completed_helpers": ["ensure_main_ipfs_kit_py"],
            "failures": [],
            "repo_revision": "rev-a",
            "status": "success",
        }
    )

    calls: list[str] = []
    module = types.SimpleNamespace(
        ensure_main_ipfs_kit_py=lambda: calls.append("ensure_main_ipfs_kit_py"),
    )
    monkeypatch.setattr(auto_installer, "_current_repo_revision", lambda: "rev-a")
    monkeypatch.setattr(auto_installer, "_load_setup_install_module", lambda: module)

    changed = auto_installer.ensure_repo_installer_current()

    assert changed is False
    assert calls == []


def test_runtime_installer_reruns_when_revision_changes(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.setenv("IPFS_DATASETS_ENSURE_INSTALLER", "1")
    marker_path = tmp_path / "runtime_installer_state.json"
    monkeypatch.setattr(auto_installer, "_runtime_installer_marker_path", lambda: marker_path)
    auto_installer._save_runtime_installer_state(
        {
            "completed_helpers": ["ensure_main_ipfs_kit_py"],
            "failures": [],
            "repo_revision": "rev-old",
            "status": "success",
        }
    )

    calls: list[str] = []
    module = types.SimpleNamespace(
        ensure_main_ipfs_kit_py=lambda: calls.append("ensure_main_ipfs_kit_py"),
        ensure_libp2p_main=lambda: calls.append("ensure_libp2p_main"),
        ensure_ipfs_accelerate_py=lambda: calls.append("ensure_ipfs_accelerate_py"),
    )

    monkeypatch.setattr(auto_installer, "_current_repo_revision", lambda: "rev-new")
    monkeypatch.setattr(auto_installer, "_load_setup_install_module", lambda: module)

    changed = auto_installer.ensure_repo_installer_current()

    assert changed is True
    assert calls == [
        "ensure_main_ipfs_kit_py",
        "ensure_libp2p_main",
        "ensure_ipfs_accelerate_py",
    ]
    state = auto_installer._load_runtime_installer_state()
    assert state["repo_revision"] == "rev-new"


def test_setup_installer_uses_existing_ipfs_accelerate_checkout(monkeypatch, tmp_path, capsys):
    install_path = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "scripts"
        / "setup"
        / "install.py"
    )
    spec = importlib.util.spec_from_file_location("test_setup_install_ipfs_accel", install_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    checkout = tmp_path / "ipfs_accelerate_py"
    package_root = checkout / "ipfs_accelerate_py"
    (package_root / "p2p_tasks").mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "p2p_tasks" / "__init__.py").write_text("", encoding="utf-8")

    calls: list[object] = []
    monkeypatch.setattr(module, "_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setenv("IPFS_ACCELERATE_PY_ROOT", str(checkout))
    monkeypatch.setattr(module, "_ipfs_accelerate_service_active", lambda: True)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: calls.append(args) or None)
    sys.modules.pop("ipfs_accelerate_py", None)
    sys.modules.pop("ipfs_accelerate_py.p2p_tasks", None)

    try:
        module.ensure_ipfs_accelerate_py()
    finally:
        sys.modules.pop("ipfs_accelerate_py", None)
        sys.modules.pop("ipfs_accelerate_py.p2p_tasks", None)
        try:
            sys.path.remove(str(checkout))
        except ValueError:
            pass

    output = capsys.readouterr().out
    assert "available from local checkout" in output
    assert "running systemd service" in output
    assert calls == []
