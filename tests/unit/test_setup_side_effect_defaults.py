"""Packaging defaults must keep optional work explicit."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
import setuptools
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_accelerator_is_not_a_base_requirements_dependency() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "-e ./ipfs_accelerate_py" not in requirements


def test_accelerator_is_optional_in_both_packaging_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: captured.update(kwargs))
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv("IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES", "1")
    runpy.run_path(str(PROJECT_ROOT / "setup.py"), run_name="_ptr_setup_metadata")

    install_requires = [str(value) for value in captured["install_requires"]]
    assert not any("ipfs_accelerate_py" in value for value in install_requires)
    setup_extras = captured["extras_require"]
    assert isinstance(setup_extras, dict)
    assert any("ipfs_accelerate_py" in str(value) for value in setup_extras["accelerate"])

    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_extra = project["project"]["optional-dependencies"]["accelerate"]
    assert any("ipfs_accelerate_py" in value for value in project_extra)


def test_package_import_does_not_refresh_the_installer() -> None:
    source = (PROJECT_ROOT / "ipfs_datasets_py" / "__init__.py").read_text(encoding="utf-8")
    assert "ensure_repo_installer_current()" not in source
