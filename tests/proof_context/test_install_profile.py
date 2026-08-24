"""Install-profile checks for the immutable datasets proof-context artifact."""

from __future__ import annotations

import email
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _build_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / "dist"
    environment = os.environ | {"SOURCE_DATE_EPOCH": "0"}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(output),
            str(PROJECT_ROOT),
        ],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    wheel, = output.glob("*.whl")
    sdist, = output.glob("*.tar.gz")
    return wheel, sdist


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    return _build_artifacts(tmp_path_factory.mktemp("package-artifacts"))


def test_wheel_and_sdist_contain_the_provider_and_core_metadata(
    artifacts: tuple[Path, Path],
) -> None:
    wheel, sdist = artifacts

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        metadata_name, = (
            name for name in members if name.endswith(".dist-info/METADATA")
        )
        metadata = email.message_from_bytes(archive.read(metadata_name))

    assert any(name.endswith("ipfs_datasets_py/proof_context/__init__.py") for name in members)
    assert any(name.endswith("ipfs_datasets_py/proof_context/provider.py") for name in members)
    assert metadata["Name"] == "ipfs_datasets_py"
    assert metadata["Version"] == "0.2.0"
    core_requirements = [
        value for value in metadata.get_all("Requires-Dist", []) if "extra ==" not in value
    ]
    assert core_requirements == []
    all_requirements = metadata.get_all("Requires-Dist", [])
    assert not any("git+" in value or "file:" in value or "@main" in value for value in all_requirements)
    # Existing published feature selections remain selectable rather than being
    # pulled into the proof-context core.
    extras = set(metadata.get_all("Provides-Extra", []))
    assert {"ipld", "logic", "theorem-provers", "test"} <= extras

    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
    source_prefix = sdist.name.removesuffix(".tar.gz")
    assert f"{source_prefix}/ipfs_datasets_py/proof_context/provider.py" in names


def test_installed_wheel_exports_provider_without_source_tree_or_dependencies(
    artifacts: tuple[Path, Path], tmp_path: Path
) -> None:
    wheel, _sdist = artifacts
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True)

    probe = (
        "import ipfs_datasets_py.proof_context as port; "
        "provider = port.get_provider(); "
        "assert port.SCHEMA == provider.schema; "
        "assert port.INTERFACE == provider.interface; "
        "assert port.PRODUCER == provider.producer; "
        "print(port.__file__)"
    )
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
        "IPFS_DATASETS_AUTO_INSTALL": "0",
        "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    }
    result = subprocess.run(
        [str(python), "-I", "-c", probe],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(PROJECT_ROOT) not in result.stdout
    assert "site-packages/ipfs_datasets_py/proof_context/__init__.py" in result.stdout
