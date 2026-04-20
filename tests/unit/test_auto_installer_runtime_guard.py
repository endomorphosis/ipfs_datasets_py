import types


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
