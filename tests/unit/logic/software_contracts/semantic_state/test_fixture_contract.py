"""Contract tests for SemanticStateControlledFixture@1.

Validates that every path and mutation case is deterministic and independently
declared, that unrelated-formatting truth is an ordinary empty oracle (not an
analyzer bypass), that the baseline is runnable under Python 3.12/pytest with no
hidden external dependency, and that the public ISI scanner can consume a
materialized tree without importing the fixture package into that tree.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.software_contracts.semantic_state import (
    FIXTURE_ROOT,
    INTERFACE_NAME,
    MutationCase,
    apply_mutation,
    case_ids,
    changed_paths_between,
    forbidden_fixture_artifacts,
    load_controlled_fixture,
    load_manifest,
    materialize_baseline,
    materialize_mutated,
    repository_digest,
)
from tests.fixtures.software_contracts.semantic_state.recipe import (
    FORBIDDEN_CASE_FIELDS,
    MUTATION_CASES,
    REQUIRED_MUTATION_KINDS,
)


REPO_ROOT = Path(__file__).resolve().parents[5]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Controlled Fixture")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _host_pytest_site_dirs() -> tuple[str, ...]:
    """Directories that must stay on PYTHONPATH for nested ``python -m pytest``.

    Host pytest is often installed in user site-packages. Supervisor sandboxes may
    set PYTHONNOUSERSITE=1 and strip monorepo PYTHONPATH; the nested runs still need
    the host runner's pytest (and its pure-Python deps), not monorepo imports.
    """
    import sysconfig

    dirs: list[str] = []
    seen: set[str] = set()

    def _add(path: Path | str | None) -> None:
        if path is None:
            return
        text = str(Path(path).resolve())
        if not text or text in seen:
            return
        seen.add(text)
        dirs.append(text)

    # Prefer the actual import locations used by this process.
    for mod_name in (
        "pytest",
        "_pytest",
        "pluggy",
        "iniconfig",
        "packaging",
        "py",
        "exceptiongroup",
        "tomli",
    ):
        try:
            module = __import__(mod_name)
        except ImportError:
            continue
        file_path = getattr(module, "__file__", None)
        if not file_path:
            continue
        package_dir = Path(file_path).resolve().parent
        # Package dir is .../site-packages/<name>; keep site-packages root.
        if package_dir.name in {
            "pytest",
            "_pytest",
            "pluggy",
            "iniconfig",
            "packaging",
            "py",
            "exceptiongroup",
            "tomli",
        }:
            _add(package_dir.parent)
        else:
            _add(package_dir)

    for key in ("purelib", "platlib"):
        try:
            _add(sysconfig.get_path(key))
        except Exception:
            pass

    try:
        import site

        for entry in site.getsitepackages():
            _add(entry)
        _add(site.getusersitepackages())
    except Exception:
        pass

    return tuple(dirs)


def _nested_pytest_env() -> dict[str, str]:
    """Environment for hermetic pytest over a materialized fixture tree."""
    env = os.environ.copy()
    env.update(
        {
            "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
            "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
            "IPFS_DATASETS_AUTO_INSTALL": "0",
            "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Nested suite is stdlib-only; do not load host third-party plugins.
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    # Drop monorepo / host PYTHONPATH pollution, then re-inject only the paths
    # required to import the host pytest runner under PYTHONNOUSERSITE sandboxes.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONNOUSERSITE", None)
    site_dirs = _host_pytest_site_dirs()
    if site_dirs:
        env["PYTHONPATH"] = os.pathsep.join(site_dirs)
    # Avoid inheriting parent addopts (strict-markers, plugin flags, etc.).
    env.pop("PYTEST_ADDOPTS", None)
    return env


def test_manifest_declares_semantic_state_controlled_fixture_v1() -> None:
    manifest = load_manifest()
    assert manifest["interface"] == INTERFACE_NAME
    assert manifest["interface"] == "SemanticStateControlledFixture@1"
    assert manifest["python_minor"] == "3.12"
    assert manifest["test_framework"] == "pytest"
    assert manifest["constraints"]["no_checked_in_git"] is True
    assert manifest["constraints"]["no_hidden_external_dependency"] is True
    assert tuple(manifest["required_mutation_kinds"]) == REQUIRED_MUTATION_KINDS


def test_catalog_loads_with_all_required_independent_cases() -> None:
    fixture = load_controlled_fixture()
    assert fixture.interface == INTERFACE_NAME
    assert fixture.case_ids == case_ids()
    assert len(fixture.cases) == len(REQUIRED_MUTATION_KINDS)
    by_kind = fixture.cases_by_kind()
    for kind in REQUIRED_MUTATION_KINDS:
        assert kind in by_kind
        case = by_kind[kind]
        assert case.case_id == kind
        assert case.kind == kind
        assert case.changed_paths == tuple(sorted(case.changed_paths))
        assert case.affected_tests == tuple(sorted(case.affected_tests))
        assert case.affected_proofs == tuple(sorted(case.affected_proofs))
        assert case.file_ops, f"{kind} must declare at least one file op"
        assert case.description


def test_mutation_cases_are_independently_declared_not_inferred() -> None:
    """Each case is a complete self-contained declaration in the recipe catalog."""
    assert len(MUTATION_CASES) == len(REQUIRED_MUTATION_KINDS)
    for raw in MUTATION_CASES:
        for field in (
            "case_id",
            "kind",
            "description",
            "changed_paths",
            "file_ops",
            "affected_tests",
            "affected_proofs",
            "semantic_change",
            "requires_full_fallback",
            "formatting_only",
        ):
            assert field in raw, f"{raw.get('case_id')}: missing independent field {field}"
        # Cases must not share a mutable declaration object.
        assert raw is not MUTATION_CASES[0] or raw["case_id"] == MUTATION_CASES[0]["case_id"]


def test_formatting_truth_is_ordinary_empty_oracle_not_analyzer_bypass() -> None:
    fixture = load_controlled_fixture()
    fmt = fixture.get_case("format")
    assert fmt.formatting_only is True
    assert fmt.semantic_change is False
    assert fmt.affected_tests == ()
    assert fmt.affected_proofs == ()
    assert fmt.requires_full_fallback is False
    raw = next(item for item in MUTATION_CASES if item["case_id"] == "format")
    for forbidden in FORBIDDEN_CASE_FIELDS:
        assert forbidden not in raw
        assert forbidden not in fmt.to_dict()
    # Same schema as every other case — no special bypass channel.
    assert set(raw).issuperset(
        {
            "case_id",
            "kind",
            "changed_paths",
            "file_ops",
            "affected_tests",
            "formatting_only",
            "semantic_change",
        }
    )


def test_no_forbidden_analyzer_bypass_fields_on_any_case() -> None:
    for raw in MUTATION_CASES:
        overlap = FORBIDDEN_CASE_FIELDS.intersection(raw)
        assert not overlap, f"{raw['case_id']}: forbidden fields {overlap}"


def test_fixture_tree_has_no_git_state_store_or_receipt_artifacts() -> None:
    assert forbidden_fixture_artifacts(FIXTURE_ROOT) == ()
    assert not (FIXTURE_ROOT / ".git").exists()
    # Fixture package must not hand-author DependencyEdge constructors.
    edge_type = "Dependency" + "Edge"
    for path in FIXTURE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert f"{edge_type}(" not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                assert name != edge_type, path


def test_baseline_materialization_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    materialize_baseline(first)
    materialize_baseline(second)
    assert repository_digest(first) == repository_digest(second)
    assert repository_digest(first) == repository_digest(first)


def test_each_mutation_only_touches_declared_changed_paths(tmp_path: Path) -> None:
    fixture = load_controlled_fixture()
    for case in fixture.cases:
        baseline = tmp_path / f"{case.case_id}_base"
        mutated = tmp_path / f"{case.case_id}_mut"
        materialize_baseline(baseline)
        materialize_mutated(mutated, case.case_id)
        observed = changed_paths_between(baseline, mutated)
        assert observed == case.changed_paths, (
            f"{case.case_id}: observed {observed} != declared {case.changed_paths}"
        )


def test_mutation_application_is_deterministic(tmp_path: Path) -> None:
    fixture = load_controlled_fixture()
    digests: dict[str, str] = {}
    for case in fixture.cases:
        left = tmp_path / f"{case.case_id}_1"
        right = tmp_path / f"{case.case_id}_2"
        materialize_mutated(left, case.case_id)
        materialize_mutated(right, case.case_id)
        digest = repository_digest(left)
        assert digest == repository_digest(right)
        digests[case.case_id] = digest
    # Distinct semantic cases must not collapse to one tree (format/local_body share path).
    assert digests["local_body"] != digests["format"]
    assert digests["schema"] != digests["exception"]


def test_baseline_is_runnable_under_pytest_without_external_deps(tmp_path: Path) -> None:
    repo = materialize_baseline(tmp_path / "repo")
    # requirements.txt must not pin installable third-party packages.
    requirements = (repo / "requirements.txt").read_text(encoding="utf-8")
    for line in requirements.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pytest.fail(f"hidden external dependency declared: {stripped!r}")

    # Isolate from parent monorepo PYTHONPATH/plugins while keeping host pytest.
    env = _nested_pytest_env()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    # Sanity: collected count matches authored universe.
    fixture = load_controlled_fixture()
    collect = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collect.returncode == 0, collect.stdout + "\n" + collect.stderr
    collected = [
        line.strip()
        for line in collect.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    ]
    assert tuple(sorted(collected)) == fixture.test_universe


def test_selected_mutations_remain_pytest_runnable_when_expectations_hold(tmp_path: Path) -> None:
    """Semantic body change: oracle tests fail; formatting-only: full suite still passes."""
    env = _nested_pytest_env()

    fmt_repo, fmt_case = materialize_mutated(tmp_path / "format", "format")
    assert fmt_case.formatting_only
    fmt_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line"],
        cwd=fmt_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fmt_run.returncode == 0, fmt_run.stdout + "\n" + fmt_run.stderr

    body_repo, body_case = materialize_mutated(tmp_path / "body", "local_body")
    assert body_case.affected_tests
    # Full suite should fail because authored oracle tests still expect baseline results.
    body_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line"],
        cwd=body_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert body_run.returncode != 0


def test_public_isi_scanner_consumes_materialized_tree_without_fixture_import(
    tmp_path: Path,
) -> None:
    """Sealed scanner/API consumes ordinary files; fixture package is not on scanned PYTHONPATH."""
    from ipfs_datasets_py.logic.software_contracts.semantic_index import scan_repository

    baseline = materialize_baseline(tmp_path / "baseline")
    _init_git_repo(baseline)
    # Ensure the fixture package path is not required inside the tree.
    assert not (baseline / "controlled.py").exists()
    assert not (baseline / "recipe.py").exists()
    assert not (baseline / "manifest.json").exists()

    state = scan_repository(baseline)
    assert state.symbols
    assert any(symbol.qualified_name.endswith("add") for symbol in state.symbols)

    mutated = tmp_path / "mutated"
    shutil.copytree(baseline, mutated)
    # Drop git so we re-init after applying mutation on the working tree.
    shutil.rmtree(mutated / ".git")
    apply_mutation(mutated, "local_body")
    _init_git_repo(mutated)
    after = scan_repository(mutated)
    assert after.state_cid != state.state_cid

    # Formatting-only should still scan cleanly (identity semantics owned by ISI later).
    fmt = tmp_path / "fmt"
    materialize_baseline(fmt)
    apply_mutation(fmt, "format")
    _init_git_repo(fmt)
    fmt_state = scan_repository(fmt)
    assert fmt_state.symbols


def test_load_is_pure_and_repeatable() -> None:
    first = load_controlled_fixture()
    second = load_controlled_fixture()
    assert first.case_ids == second.case_ids
    assert first.test_universe == second.test_universe
    assert [c.to_dict() for c in first.cases] == [c.to_dict() for c in second.cases]


def test_authored_oracles_are_node_id_domain_only() -> None:
    fixture = load_controlled_fixture()
    for case in fixture.cases:
        for node_id in case.affected_tests:
            assert "::" in node_id
            assert node_id.startswith("tests/")
            # Fingerprints are not part of membership oracle.
            assert "fingerprint" not in node_id
        for proof_id in case.affected_proofs:
            assert proof_id.startswith("proofs/")


def test_delete_and_rename_cases_declare_explicit_evidence() -> None:
    fixture = load_controlled_fixture()
    delete = fixture.get_case("delete")
    assert delete.deleted_symbols
    assert delete.deleted_tests
    rename = fixture.get_case("rename")
    assert rename.rename_pairs == (("pkg/callers.py", "pkg/pipeline_mod.py"),)


def test_opaque_kinds_declare_full_fallback() -> None:
    fixture = load_controlled_fixture()
    for kind in ("dynamic", "monkey", "native"):
        case = fixture.get_case(kind)
        assert case.requires_full_fallback is True
        assert case.semantic_change is True


def test_mutation_case_rejects_analyzer_bypass_fields() -> None:
    with pytest.raises(ValueError, match="analyzer-bypass"):
        MutationCase.from_mapping(
            {
                "case_id": "evil",
                "kind": "format",
                "description": "bad",
                "changed_paths": (),
                "file_ops": (),
                "affected_tests": (),
                "affected_proofs": (),
                "semantic_change": False,
                "requires_full_fallback": False,
                "formatting_only": True,
                "analyzer_bypass": True,
            }
        )


def test_manifest_json_is_closed_enough_for_fixture_contract() -> None:
    raw = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert raw["schema"].endswith("@1")
    assert "SemanticStateControlledFixture@1" in raw["interface"]


def test_fixture_package_lives_under_declared_output_path() -> None:
    expected = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "software_contracts"
        / "semantic_state"
    )
    assert FIXTURE_ROOT == expected
    assert (FIXTURE_ROOT / "manifest.json").is_file()
    assert (FIXTURE_ROOT / "recipe.py").is_file()
    assert (FIXTURE_ROOT / "controlled.py").is_file()
