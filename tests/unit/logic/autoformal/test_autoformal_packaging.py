"""Bounded package-data coverage for the installed autoformal navigator.

The fixture builds only catalog-selected source and canonical documentation.
No repository setup hook, package initializer, numerical owner or model runs.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[4]
PACKAGE = Path("ipfs_datasets_py")
AUTOFORMAL = PACKAGE / "logic/autoformal"
PATTERNS = (
    "logic/autoformal/README.md",
    "logic/autoformal/docs/*.md",
    "logic/autoformal/docs/*.json",
    "logic/autoformal/docs/guides/*.md",
    "logic/autoformal/docs/history/pre-consolidation.zip",
)
DECOYS = (
    AUTOFORMAL / "docs/history/weights.safetensors",
    AUTOFORMAL / "docs/history/transcript.jsonl",
    AUTOFORMAL / "docs/history/run-metadata.json",
    AUTOFORMAL / "docs/history/unselected-archive.zip",
    AUTOFORMAL / "docs/workspace/receipt.json",
    AUTOFORMAL / "workspace/checkpoint.pt",
    AUTOFORMAL / "workspace/transcript.json",
    Path("workspace/test-logs/receipt.json"),
    Path("artifacts/unselected-run/checkpoint.json"),
)


def _declared_package_data():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    calls = [
        node for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "setup"
    ]
    assert len(calls) == 1
    keywords = {item.arg: item.value for item in calls[0].value.keywords}
    legacy = ast.literal_eval(keywords["package_data"])["ipfs_datasets_py"]
    modern = metadata["tool"]["setuptools"]["package-data"]["ipfs_datasets_py"]
    return metadata, keywords, legacy, modern


def _manifest_rules():
    return [
        line.strip() for line in (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        and "ipfs_datasets_py/logic/autoformal" in line
    ]


def test_autoformal_package_data_agrees_across_packaging_entry_points():
    metadata, keywords, legacy, modern = _declared_package_data()
    assert ast.literal_eval(keywords["include_package_data"]) is True
    assert metadata["tool"]["setuptools"]["include-package-data"] is True
    for declared in (legacy, modern):
        selected = [item for item in declared if item.startswith("logic/autoformal/")]
        assert len(selected) == len(PATTERNS)
        assert set(selected) == set(PATTERNS)
    expected_manifest = {"include ipfs_datasets_py/" + pattern for pattern in PATTERNS}
    assert set(_manifest_rules()) == expected_manifest


@pytest.fixture(scope="module")
def installed_catalog(tmp_path_factory):
    """Use real setuptools data selection, then discard the fixture checkout."""
    from setuptools import Distribution
    from setuptools.command.build_py import build_py

    # pytest's numbered mktemp creates a "current" symlink. The existing
    # owned-validation inventory requires physical, unaliased output paths.
    temporary = Path(tempfile.mkdtemp(prefix="autoformal-packaging-",
                                      dir=tmp_path_factory.getbasetemp()))
    source = temporary / "source"
    installed = temporary / "installed"
    source.mkdir()
    catalog = json.loads((ROOT / AUTOFORMAL / "docs/work_catalog.json").read_text())
    sources = {AUTOFORMAL / "work_catalog.py"}
    sources.update(Path(item["path"]) for item in catalog["components"])
    resources = {AUTOFORMAL / "README.md"}
    for folder, suffix in (
        (AUTOFORMAL / "docs", "*.md"),
        (AUTOFORMAL / "docs", "*.json"),
        (AUTOFORMAL / "docs/guides", "*.md"),
    ):
        resources.update(path.relative_to(ROOT) for path in (ROOT / folder).glob(suffix))
    resources.add(AUTOFORMAL / "docs/history/pre-consolidation.zip")
    assert set(map(Path, catalog["required_documentation"])) <= resources
    packages = set()
    for relative in sources:
        directory = relative.parent
        while directory != Path("."):
            packages.add(directory.as_posix().replace("/", "."))
            initializer = source / directory / "__init__.py"
            initializer.parent.mkdir(parents=True, exist_ok=True)
            initializer.write_text(
                "raise AssertionError('packaging fixture initializer must not execute')\n"
            )
            directory = directory.parent
    for relative in sources | resources:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    for relative in DECOYS:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"unselected run evidence\n")
    (source / "setup.py").write_text("# Metadata is supplied directly to Distribution.\n")
    (source / "MANIFEST.in").write_text("\n".join(_manifest_rules()) + "\n")
    _, _, _, declared = _declared_package_data()
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(source)
        distribution = Distribution({
            "name": "autoformal-packaging-fixture",
            "version": "0.0.0",
            "packages": sorted(packages),
            "package_data": {"ipfs_datasets_py": declared},
            "include_package_data": True,
        })
        distribution.script_name = "setup.py"
        command = build_py(distribution)
        command.build_lib = str(installed)
        command.ensure_finalized()
        command.run()
    shutil.rmtree(source)
    assert not source.exists()
    return installed, resources, catalog


def _run_installed_navigator(installed, operation):
    code = r"""
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys

class DenyOwners(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in {
            "ipfs_datasets_py", "torch", "numpy", "transformers", "pyarrow"
        }:
            raise AssertionError("navigator imported an owner: " + fullname)

sys.meta_path.insert(0, DenyOwners())
path = Path(sys.argv[1]) / "ipfs_datasets_py/logic/autoformal/work_catalog.py"
spec = importlib.util.spec_from_file_location("_installed_autoformal_catalog", path)
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)
if sys.argv[2] == "inspect":
    result = {
        "check": owner.check_catalog(),
        "tasks": owner.tasks(),
        "component": owner.component("definition-use-native"),
    }
else:
    result = getattr(owner, sys.argv[2])()
print(json.dumps(result, sort_keys=True))
"""
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(installed), operation],
        cwd=installed,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_built_catalog_works_without_checkout_and_excludes_run_evidence(installed_catalog):
    installed, resources, catalog = installed_catalog
    for relative in resources:
        assert (installed / relative).read_bytes() == (ROOT / relative).read_bytes()
    for relative in DECOYS:
        assert not (installed / relative).exists(), relative
    result = _run_installed_navigator(installed, "inspect")
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    report = observed["check"]
    assert report["valid"] is True, report["errors"]
    assert report["components_checked"] == len(catalog["components"])
    assert report["documentation_paths_checked"] == len(catalog["required_documentation"])
    assert report["archive_paths_traversed"] == report["registered_owners_imported"] == 0
    assert report["model_or_native_execution"] is False
    assert report["qualification_or_proof_admission_performed"] is False
    assert len(observed["tasks"]) == report["active_task_count"] == 24
    assert observed["component"]["id"] == "definition-use-native"


def test_missing_installed_metadata_cannot_fall_back_to_checkout(installed_catalog, tmp_path):
    installed, _, _ = installed_catalog
    for filename, operation in (("work_catalog.json", "load_catalog"), ("BACKLOG.json", "tasks")):
        incomplete = tmp_path / filename
        for relative in (
            AUTOFORMAL / "work_catalog.py",
            AUTOFORMAL / "docs/work_catalog.json",
            AUTOFORMAL / "docs/BACKLOG.json",
        ):
            destination = incomplete / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(installed / relative, destination)
        missing = incomplete / AUTOFORMAL / "docs" / filename
        missing.unlink()
        result = _run_installed_navigator(incomplete, operation)
        assert result.returncode != 0
        assert "FileNotFoundError" in result.stderr
        assert str(missing) in result.stderr
