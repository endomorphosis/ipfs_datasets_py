import types


def test_runtime_installer_runs_when_marker_missing(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

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


def test_runtime_installer_skips_when_marker_matches_revision(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

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
