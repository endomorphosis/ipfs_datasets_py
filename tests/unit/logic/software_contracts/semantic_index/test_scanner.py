"""Tests for deterministic repository-state assembly and verified incremental reuse."""

from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
from pathlib import Path

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.index import scan_repository
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    RelationType,
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import PythonSemanticAnalyzer
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import (
    RepositoryScanner,
    scan_repository_state,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import snapshot_repository


FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "software_contracts" / "incremental_semantic_index"


def _symbols(state):
    return {symbol.qualified_name: symbol for symbol in state.symbols}


def test_cold_and_incremental_scans_have_the_same_root(tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "sample.py").write_text("def answer(value: int) -> int:\n    return value + 1\n", encoding="utf-8")
    first = scan_repository_state(tmp_path, repository_id="repo:scanner")
    second = scan_repository_state(tmp_path, repository_id="repo:scanner", previous_state=first)
    assert first.state_cid == second.state_cid
    assert first == second
    assert first.to_dict() == second.to_dict()


def test_formatting_and_unrelated_edits_do_not_change_other_symbol_versions(tmp_path) -> None:
    path = tmp_path / "module.py"
    path.write_text("def stable():\n    return 1\n\ndef changed():\n    return 2\n", encoding="utf-8")
    first = scan_repository_state(tmp_path, repository_id="repo:scanner")
    path.write_text("\n\ndef stable():\n\treturn 1\n\ndef changed():\n    return 3\n", encoding="utf-8")
    second = scan_repository_state(tmp_path, repository_id="repo:scanner", previous_state=first)
    old, new = _symbols(first), _symbols(second)
    assert old["module.stable"].stable_id == new["module.stable"].stable_id
    assert old["module.stable"].version_cid == new["module.stable"].version_cid
    assert old["module.changed"].version_cid != new["module.changed"].version_cid


def test_syntax_failure_is_an_explicit_opaque_artifact(tmp_path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    state = scan_repository_state(tmp_path, repository_id="repo:scanner")
    artifact = next(item for item in state.artifacts if item.path == "broken.py")
    assert artifact.kind == "python-analysis"
    assert artifact.confidence == "opaque"
    assert artifact.metadata["diagnostics"]


def test_clean_scan_uses_indexed_blob_not_smudged_worktree_bytes(tmp_path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("config", "filter.fixture.smudge", "sed s/indexed/smudged/g")
    git("config", "filter.fixture.clean", "sed s/smudged/indexed/g")
    (tmp_path / ".gitattributes").write_text("module.py filter=fixture\n", encoding="utf-8")
    (tmp_path / "module.py").write_text("value = 'indexed'\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "initial")
    (tmp_path / "module.py").unlink()
    git("checkout", "--", "module.py")
    assert "smudged" in (tmp_path / "module.py").read_text(encoding="utf-8")
    snapshot = snapshot_repository(tmp_path)
    state = RepositoryScanner().scan(tmp_path, snapshot=snapshot)
    assert snapshot.mode == "git-clean"
    assert snapshot.entries[1].path == "module.py"
    module = _symbols(state)["module"]
    assert module.source_cid == cid_for_bytes(b"value = 'indexed'\n")


def test_working_file_mutation_after_snapshot_is_explicit_opaque_artifact(tmp_path) -> None:
    path = tmp_path / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    snapshot = snapshot_repository(tmp_path, repository_id="repo:race")
    path.write_text("value = 2\n", encoding="utf-8")
    state = RepositoryScanner(repository_id="repo:race").scan(tmp_path, snapshot=snapshot)
    artifact = next(item for item in state.artifacts if item.path == "module.py")
    assert artifact.confidence == "opaque"
    assert artifact.metadata["opaque_reason"] == "source_cid_mismatch"
    assert not state.symbols


def test_scan_repository_resolves_calls_to_stable_symbol_cids_never_parallel_lexical(tmp_path) -> None:
    (tmp_path / "module.py").write_text(
        "def service(value: int) -> int:\n    return value\n\n"
        "def caller() -> int:\n    return service(1)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text(
        "from module import service\n\ndef test_service():\n    assert service(1) == 1\n",
        encoding="utf-8",
    )
    state = scan_repository(tmp_path)
    by_qn = _symbols(state)
    service = by_qn["module.service"]
    caller = by_qn["module.caller"]
    test = by_qn["tests.test_service.test_service"]
    assert test.kind == "test"
    # Exactly one identity per logical binding — no parallel function+test clones.
    assert sum(1 for item in state.symbols if item.qualified_name == test.qualified_name) == 1

    def resolved_calls(source_id: str):
        return [
            edge for edge in state.edges
            if edge.relation == RelationType.CALLS.value and edge.source_id == source_id
            and edge.target_id == service.stable_id
        ]

    caller_calls = resolved_calls(caller.stable_id)
    test_calls = resolved_calls(test.stable_id)
    assert caller_calls and caller_calls[0].metadata.get("resolution") == "definite"
    assert test_calls and test_calls[0].metadata.get("resolution") == "definite"
    # No resolvable call may remain as a parallel lexical: target for service.
    residual = [
        edge for edge in state.edges
        if edge.relation == RelationType.CALLS.value
        and edge.target_id.startswith("lexical:")
        and edge.target_id.rstrip(".").endswith("service")
    ]
    assert residual == []
    tested = [
        edge for edge in state.edges
        if edge.relation == RelationType.TESTED_BY.value and edge.source_id == service.stable_id
    ]
    assert tested and tested[0].target_id == test.stable_id


def test_production_signature_change_reaches_callers_and_pytest_tests(tmp_path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURES / "pytest_identity" / "v1", repository)
    previous = scan_repository(repository)
    shutil.rmtree(repository)
    shutil.copytree(FIXTURES / "pytest_identity" / "v2", repository)
    current = scan_repository(repository, previous)
    prev = _symbols(previous)
    cur = _symbols(current)
    assert prev["pkg.service.service"].stable_id == cur["pkg.service.service"].stable_id
    assert prev["pkg.service.service"].version_cid != cur["pkg.service.service"].version_cid
    # Real callers and tests remain wired to the production symbol via committed edges.
    service = cur["pkg.service.service"]
    caller = cur["pkg.service.caller"]
    test = cur["tests.test_service.test_service"]
    assert any(
        edge.relation == RelationType.CALLS.value
        and edge.source_id == caller.stable_id
        and edge.target_id == service.stable_id
        for edge in current.edges
    )
    assert any(
        edge.relation == RelationType.CALLS.value
        and edge.source_id == test.stable_id
        and edge.target_id == service.stable_id
        for edge in current.edges
    )
    assert any(
        edge.relation == RelationType.TESTED_BY.value
        and edge.source_id == service.stable_id
        and edge.target_id == test.stable_id
        for edge in current.edges
    )


def test_fixture_body_edit_changes_one_version_cid(tmp_path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURES / "pytest_identity" / "v1", repository)
    previous = scan_repository(repository)
    shutil.rmtree(repository)
    shutil.copytree(FIXTURES / "pytest_identity" / "v2", repository)
    current = scan_repository(repository, previous)
    prev_fixture = next(
        item for item in previous.symbols
        if item.kind == "fixture" and item.qualified_name.endswith(".database")
    )
    cur_fixture = next(
        item for item in current.symbols
        if item.kind == "fixture" and item.qualified_name.endswith(".database")
    )
    assert prev_fixture.stable_id == cur_fixture.stable_id
    assert prev_fixture.version_cid != cur_fixture.version_cid
    # Exactly one fixture identity for database.
    assert sum(1 for item in current.symbols if item.kind == "fixture" and item.qualified_name.endswith(".database")) == 1
    # Dependent tests remain linked via uses_fixture.
    test = next(item for item in current.symbols if item.qualified_name.endswith(".test_service") and item.kind == "test")
    assert any(
        edge.relation == RelationType.USES_FIXTURE.value
        and edge.source_id == test.stable_id
        and edge.target_id == cur_fixture.stable_id
        for edge in current.edges
    )


def test_public_state_edges_are_source_rooted_and_survive_round_trip(tmp_path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURES / "pytest_identity" / "v1", repository)
    state = scan_repository(repository)
    relations = {edge.relation for edge in state.edges}
    assert RelationType.TESTED_BY.value in relations
    assert RelationType.USES_FIXTURE.value in relations
    assert RelationType.CONFIGURED_BY.value in relations
    assert RelationType.CALLS.value in relations
    for edge in state.edges:
        if edge.relation in {
            RelationType.TESTED_BY.value,
            RelationType.USES_FIXTURE.value,
            RelationType.CONFIGURED_BY.value,
            RelationType.SERIALIZES.value,
            RelationType.DESERIALIZES.value,
            RelationType.VALIDATES.value,
            RelationType.GENERATED_FROM.value,
            RelationType.PROOF_DEPENDS_ON.value,
        }:
            assert edge.metadata.get("source_bound") is True or edge.extraction_method
            assert edge.span is not None or edge.relation == RelationType.TESTED_BY.value
    restored = RepositoryState.from_dict(state.to_dict())
    assert restored.state_cid == state.state_cid
    assert restored.edges == state.edges
    assert restored.symbols == state.symbols


def test_instrumented_reuse_skips_unchanged_files_and_reanalyzes_changed(tmp_path, monkeypatch) -> None:
    """Unchanged sources reuse verified analysis; changed files recompute."""
    (tmp_path / "stable.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    (tmp_path / "mutable.py").write_text(
        "from stable import keep\ndef use():\n    return keep()\n",
        encoding="utf-8",
    )
    scanner = RepositoryScanner(repository_id="repo:reuse")
    cold = scanner.scan(tmp_path)
    assert scanner.last_reuse_diagnostics is not None
    assert scanner.last_reuse_diagnostics.previous_state_accepted is False
    assert set(scanner.last_reuse_diagnostics.analyzed_paths) == {"stable.py", "mutable.py"}

    analyzed: list[str] = []
    original = PythonSemanticAnalyzer.analyze

    def instrumented(self, source, path):  # type: ignore[no-untyped-def]
        analyzed.append(path)
        return original(self, source, path)

    monkeypatch.setattr(PythonSemanticAnalyzer, "analyze", instrumented)

    identical = scanner.scan(tmp_path, previous_state=cold)
    assert analyzed == []
    assert identical == cold
    assert identical.state_cid == cold.state_cid
    diag = scanner.last_reuse_diagnostics
    assert diag is not None
    assert diag.previous_state_accepted is True
    assert diag.reject_reason is None
    assert set(diag.reused_paths) == {"stable.py", "mutable.py"}
    assert diag.analyzed_paths == ()
    assert diag.resolution_recomputed is True
    # Diagnostics are outside durable identity.
    assert "reused_paths" not in identical.to_dict()
    assert diag.to_dict()["schema"]

    analyzed.clear()
    (tmp_path / "mutable.py").write_text(
        "from stable import keep\ndef use():\n    return keep() + 1\n",
        encoding="utf-8",
    )
    incremental = scanner.scan(tmp_path, previous_state=cold)
    assert analyzed == ["mutable.py"]
    diag = scanner.last_reuse_diagnostics
    assert diag is not None
    assert set(diag.reused_paths) == {"stable.py"}
    assert set(diag.analyzed_paths) == {"mutable.py"}
    assert diag.resolution_recomputed is True

    # Dependent resolution still binds the reused caller to the stable target.
    by_qn = _symbols(incremental)
    assert any(
        edge.relation == RelationType.CALLS.value
        and edge.source_id == by_qn["mutable.use"].stable_id
        and edge.target_id == by_qn["stable.keep"].stable_id
        and edge.metadata.get("resolution") == "definite"
        for edge in incremental.edges
    )
    # Cold scan of the same bytes matches the incremental result.
    cold_after = RepositoryScanner(repository_id="repo:reuse").scan(tmp_path)
    assert cold_after == incremental
    assert cold_after.state_cid == incremental.state_cid


def test_forged_or_mismatched_previous_states_are_never_reused(tmp_path, monkeypatch) -> None:
    (tmp_path / "module.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    scanner = RepositoryScanner(repository_id="repo:gate")
    genuine = scanner.scan(tmp_path)

    analyzed: list[str] = []
    original = PythonSemanticAnalyzer.analyze

    def instrumented(self, source, path):  # type: ignore[no-untyped-def]
        analyzed.append(path)
        return original(self, source, path)

    monkeypatch.setattr(PythonSemanticAnalyzer, "analyze", instrumented)

    # Bypass constructors that refuse forged envelopes so the scanner gate is
    # the code under test (optimization admission, not model construction).
    repo_forged = replace(genuine, extractor_version=genuine.extractor_version)
    object.__setattr__(repo_forged, "repository_id", "repo:other")
    schema_forged = replace(genuine, extractor_version=genuine.extractor_version)
    object.__setattr__(schema_forged, "schema", "ipfs-datasets.software-contracts.semantic-index@1")

    for forged, reason in (
        (repo_forged, "repository_id_mismatch"),
        (replace(genuine, extractor_name="forged-extractor"), "extractor_name_mismatch"),
        (replace(genuine, extractor_version="999"), "extractor_version_mismatch"),
        (schema_forged, "schema_mismatch"),
    ):
        analyzed.clear()
        result = scanner.scan(tmp_path, previous_state=forged)
        assert analyzed == ["module.py"], reason
        diag = scanner.last_reuse_diagnostics
        assert diag is not None
        assert diag.previous_state_accepted is False
        assert diag.reject_reason == reason
        assert diag.reused_paths == ()
        assert result.state_cid == genuine.state_cid

    # Matching previous_state still reuses.
    analyzed.clear()
    reused = scanner.scan(tmp_path, previous_state=genuine)
    assert analyzed == []
    assert reused == genuine
    assert scanner.last_reuse_diagnostics is not None
    assert scanner.last_reuse_diagnostics.previous_state_accepted is True
