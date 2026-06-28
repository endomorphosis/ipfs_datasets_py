from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "ipfs_datasets_py"
BUILD_SCRIPT = PACKAGE_ROOT / "processors" / "provekit_backend" / "build.sh"


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _setup_text() -> str:
    return (REPO_ROOT / "setup.py").read_text(encoding="utf-8")


def _manifest_text() -> str:
    return (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")


def test_provekit_extra_is_declared_without_vcs_or_rust_install_side_effects():
    project = _pyproject()
    deps = project["project"]["optional-dependencies"]["provekit"]

    assert deps
    assert all("git+" not in dependency for dependency in deps)
    assert all("cargo" not in dependency.lower() for dependency in deps)
    assert "provekit" in _setup_text()


def test_provekit_package_data_allowlists_only_read_only_backend_assets():
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]["ipfs_datasets_py"]
    manifest = _manifest_text()

    assert "processors/provekit_backend/README.md" in package_data
    assert "processors/provekit_backend/build.sh" in package_data
    assert "logic/zkp/provekit/circuits/*/Nargo.toml" in package_data
    assert "logic/zkp/provekit/circuits/*/src/*.nr" in package_data
    assert "recursive-include ipfs_datasets_py/logic/zkp/provekit/circuits Nargo.toml *.nr" in manifest
    assert "*.pkp" not in package_data
    assert "*.pkv" not in package_data
    assert "*.np" not in package_data
    assert "Prover.toml" not in package_data
    assert "recursive-exclude ipfs_datasets_py/logic/zkp/provekit/circuits *.pkp *.pkv *.np Prover.toml" in manifest


def test_provekit_build_script_is_manual_checkable_and_non_networked():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert BUILD_SCRIPT.exists()
    assert os.access(BUILD_SCRIPT, os.X_OK)
    assert "IPFS_DATASETS_PROVEKIT_CLI" in script
    assert "IPFS_DATASETS_PROVEKIT_HOME" in script
    assert "git clone" not in script
    assert "cargo build" not in script
    assert "curl " not in script
    assert "wget " not in script

    result = subprocess.run(
        [str(BUILD_SCRIPT), "--check"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "IPFS_DATASETS_PROVEKIT_CLI": "", "IPFS_DATASETS_PROVEKIT_HOME": ""},
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "Packaging check passed" in result.stdout


def test_provekit_import_path_does_not_prepare_artifacts_on_import(tmp_path, monkeypatch):
    marker = tmp_path / "prepared"

    def fail_run(*args, **kwargs):  # pragma: no cover - executed only on regression
        marker.write_text("called", encoding="utf-8")
        raise AssertionError("imports must not run ProveKit subprocesses")

    monkeypatch.setattr(subprocess, "run", fail_run)

    import ipfs_datasets_py.logic.zkp.provekit.artifacts  # noqa: F401
    import ipfs_datasets_py.logic.zkp.provekit.cli  # noqa: F401

    assert not marker.exists()
