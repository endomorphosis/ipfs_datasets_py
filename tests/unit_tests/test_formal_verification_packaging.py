"""Release-packaging gates for formal-verification installers and assets."""

from __future__ import annotations

import tomllib
from pathlib import Path

from setuptools import find_namespace_packages

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_setup_discovers_formal_verification_namespace_packages() -> None:
    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    assert "find_namespace_packages(" in setup_source
    assert "packages=find_packages(" not in setup_source

    discovered = set(
        find_namespace_packages(
            where=str(REPO_ROOT),
            include=["ipfs_datasets_py*"],
        )
    )
    assert {
        "ipfs_datasets_py.logic.backends",
        "ipfs_datasets_py.logic.backends.installers",
        "ipfs_datasets_py.logic.software_verification",
        "ipfs_datasets_py.logic.software_verification.monitoring",
    } <= discovered


def test_runtime_mtl_vendor_sources_are_declared_for_sdist_and_wheel() -> None:
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    installer_source = (
        REPO_ROOT
        / "ipfs_datasets_py"
        / "logic"
        / "backends"
        / "installers"
        / "runtime_mtl.py"
    ).read_text(encoding="utf-8")

    assert "recursive-include typescript/logic-runtime-mtl *.json *.ts" in manifest
    assert "prune typescript/logic-runtime-mtl/node_modules" in manifest
    assert "prune typescript/logic-runtime-mtl/dist" in manifest
    assert "_BuildPyWithFormalVerificationAssets" in setup_source
    assert '"_vendor"' in setup_source
    assert '"logic-runtime-mtl"' in setup_source
    assert '"_vendor" / "logic-runtime-mtl"' in installer_source

    source_root = REPO_ROOT / "typescript" / "logic-runtime-mtl"
    for relative in (
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "src/index.ts",
        "src/cli.ts",
    ):
        assert (source_root / relative).is_file()


def test_lazy_extra_contains_complete_python_theorem_profile() -> None:
    metadata = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_find = metadata["tool"]["setuptools"]["packages"]["find"]
    assert package_find["namespaces"] is True
    assert package_find["include"] == [
        "ipfs_datasets_py",
        "ipfs_datasets_py.*",
    ]
    lazy = set(metadata["project"]["optional-dependencies"]["lazy"])
    theorem = {
        line.strip()
        for line in (
            REPO_ROOT / "requirements-theorem-provers.txt"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    # SymbolicAI is an advisor/LLM integration and remains in the explicit
    # theorem profile; the shared lazy dependency proxy covers deterministic
    # Python solver and validation dependencies.
    deterministic_theorem = {
        requirement
        for requirement in theorem
        if not requirement.lower().startswith("symbolicai")
    }
    assert deterministic_theorem <= lazy

    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    requirements_lazy = (REPO_ROOT / "requirements-lazy.txt").read_text(
        encoding="utf-8"
    )
    for requirement in deterministic_theorem:
        assert requirement in setup_source
        assert requirement in requirements_lazy
