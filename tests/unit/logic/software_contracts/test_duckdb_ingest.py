"""Unit tests for incremental DuckDB AST ingestion (DQK-032).

Acceptance coverage:

* Unchanged source is not reparsed
* Deleted/renamed symbols cannot leak from older revisions
* Dirty-tree policy and Git object identity are explicit
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    build_duckdb_ast_store,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import (
    DUCKDB_INGEST_INTERFACE,
    DUCKDB_INGEST_SCHEMA_VERSION,
    CountingFrontend,
    DirtyTreeError,
    DirtyTreePolicy,
    DuckDBASTIngestor,
    DuckDBIngestError,
    GitObjectIdentity,
    GitObjectIdentityError,
    IngestAction,
    SourceShardCache,
    apply_dirty_tree_policy,
    build_duckdb_ast_ingestor,
    ingest_schema_descriptor,
    rebind_ast_record,
    repository_id_for_git,
    resolve_git_object_identity,
    validate_git_object_id,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot,
    SnapshotEntry,
)


COMMIT_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COMMIT_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
COMMIT_C = "cccccccccccccccccccccccccccccccccccccccc"
TREE_A = "1111111111111111111111111111111111111111"
TREE_B = "2222222222222222222222222222222222222222"
TREE_C = "3333333333333333333333333333333333333333"

SRC_ALPHA = b"def alpha():\n    return 1\n"
SRC_BETA = b"def beta():\n    return 2\n"
SRC_ALPHA_V2 = b"def alpha():\n    return 99\n"
SRC_GAMMA = b"def gamma():\n    return 3\n"


def _identity(
    commit: str,
    tree: str,
    *,
    dirty: bool = False,
    dirty_entry_count: int = 0,
    dirty_paths: tuple[str, ...] = (),
) -> GitObjectIdentity:
    return GitObjectIdentity(
        commit=commit,
        tree=tree,
        dirty=dirty,
        dirty_entry_count=dirty_entry_count if dirty else 0,
        repository_path="/tmp/synthetic-repo",
        treeish="HEAD",
        dirty_paths=dirty_paths if dirty else (),
    )


def _ingestor(
    *,
    dirty_tree_policy: DirtyTreePolicy = DirtyTreePolicy.REJECT,
) -> tuple[DuckDBASTIngestor, CountingFrontend]:
    frontend = CountingFrontend(PythonASTExtractor())
    store = build_duckdb_ast_store()
    ingestor = build_duckdb_ast_ingestor(
        store=store,
        frontends={"python": frontend},
        dirty_tree_policy=dirty_tree_policy,
        languages=("python",),
        repository_label="test-repo",
    )
    return ingestor, frontend


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # Avoid depending on default-branch name differences.
    _git(repo, "checkout", "-b", "main")
    return repo


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_interface_and_schema_are_pinned() -> None:
    ingestor = build_duckdb_ast_ingestor()
    assert ingestor.interface == DUCKDB_INGEST_INTERFACE
    assert ingestor.schema_version == DUCKDB_INGEST_SCHEMA_VERSION
    assert DUCKDB_INGEST_INTERFACE == "DuckDBASTIngest@1"

    descriptor = ingest_schema_descriptor()
    assert descriptor["interface"] == DUCKDB_INGEST_INTERFACE
    assert descriptor["default_dirty_tree_policy"] == DirtyTreePolicy.REJECT.value
    assert descriptor["guarantees"]["unchanged_source_not_reparsed"] is True
    assert descriptor["guarantees"]["deleted_symbols_cannot_leak"] is True
    assert descriptor["guarantees"]["dirty_tree_policy_explicit"] is True
    assert descriptor["guarantees"]["git_object_identity_explicit"] is True
    assert descriptor["guarantees"]["atomic_revision_publish"] is True


def test_module_import_is_inert() -> None:
    mod = importlib.import_module(
        "ipfs_datasets_py.logic.software_contracts.duckdb_ingest"
    )
    assert mod.DUCKDB_INGEST_INTERFACE == "DuckDBASTIngest@1"
    assert mod.DirtyTreePolicy.REJECT.value == "reject"


# ---------------------------------------------------------------------------
# Acceptance: dirty-tree policy and Git object identity are explicit
# ---------------------------------------------------------------------------


def test_validate_git_object_id_requires_full_lowercase_hex() -> None:
    assert validate_git_object_id(COMMIT_A, field_name="commit") == COMMIT_A
    with pytest.raises(GitObjectIdentityError):
        validate_git_object_id("abc123", field_name="commit")
    with pytest.raises(GitObjectIdentityError):
        validate_git_object_id("A" * 40, field_name="commit")
    with pytest.raises(GitObjectIdentityError):
        validate_git_object_id(123, field_name="commit")


def test_git_object_identity_is_explicit_and_canonical() -> None:
    identity = _identity(COMMIT_A, TREE_A)
    assert identity.clean is True
    assert identity.dirty is False
    assert identity.revision == COMMIT_A
    assert identity.commit == COMMIT_A
    assert identity.tree == TREE_A
    payload = identity.to_dict()
    assert payload["commit"] == COMMIT_A
    assert payload["tree"] == TREE_A
    assert payload["dirty"] is False
    assert payload["clean"] is True
    assert "revision" in payload

    dirty = _identity(
        COMMIT_A,
        TREE_A,
        dirty=True,
        dirty_entry_count=1,
        dirty_paths=("pkg/mod.py",),
    )
    assert dirty.revision == f"{COMMIT_A}+dirty"
    assert dirty.clean is False

    with pytest.raises(GitObjectIdentityError):
        _identity(COMMIT_A, TREE_A, dirty=True, dirty_entry_count=0)


def test_repository_id_binds_commit_and_tree() -> None:
    repo_id = repository_id_for_git(commit=COMMIT_A, tree=TREE_A, label="pkg")
    assert COMMIT_A in repo_id
    assert TREE_A in repo_id
    assert repo_id.startswith("repository:git-commit:")


def test_dirty_tree_policy_reject_is_default_and_fail_closed() -> None:
    dirty = _identity(
        COMMIT_A,
        TREE_A,
        dirty=True,
        dirty_entry_count=2,
        dirty_paths=("a.py", "b.py"),
    )
    with pytest.raises(DirtyTreeError):
        apply_dirty_tree_policy(dirty, DirtyTreePolicy.REJECT)

    allowed = apply_dirty_tree_policy(dirty, DirtyTreePolicy.ALLOW_WITH_MARKER)
    assert allowed.dirty is True
    assert allowed.revision.endswith("+dirty")

    clean = _identity(COMMIT_A, TREE_A)
    assert apply_dirty_tree_policy(clean, DirtyTreePolicy.REJECT) is clean


def test_ingestor_rejects_dirty_identity_under_default_policy() -> None:
    ingestor, _frontend = _ingestor()
    dirty = _identity(
        COMMIT_A,
        TREE_A,
        dirty=True,
        dirty_entry_count=1,
        dirty_paths=("x.py",),
    )
    with pytest.raises(DirtyTreeError):
        ingestor.ingest_revision(
            sources={"pkg/a.py": SRC_ALPHA},
            identity=dirty,
        )


def test_ingestor_allow_dirty_marks_revision_explicitly() -> None:
    ingestor, _frontend = _ingestor(
        dirty_tree_policy=DirtyTreePolicy.ALLOW_WITH_MARKER
    )
    dirty = _identity(
        COMMIT_A,
        TREE_A,
        dirty=True,
        dirty_entry_count=1,
        dirty_paths=("pkg/a.py",),
    )
    publication = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA},
        identity=dirty,
        created_at=1.0,
    )
    assert publication.published is True
    assert publication.identity.dirty is True
    assert publication.revision == f"{COMMIT_A}+dirty"
    assert publication.dirty_tree_policy == DirtyTreePolicy.ALLOW_WITH_MARKER.value
    assert publication.revision_id.endswith(f":{COMMIT_A}+dirty")


def test_resolve_git_object_identity_from_real_checkout(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "hello.py").write_text("def hello():\n    return 0\n", encoding="utf-8")
    _git(repo, "add", "hello.py")
    _git(repo, "commit", "-m", "init")
    identity = resolve_git_object_identity(repo)
    assert identity.dirty is False
    assert len(identity.commit) == 40
    assert len(identity.tree) == 40
    assert identity.commit == identity.commit.lower()
    assert identity.tree == identity.tree.lower()
    assert identity.revision == identity.commit

    # Dirty tree is explicit.
    (repo / "hello.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    dirty = resolve_git_object_identity(repo)
    assert dirty.dirty is True
    assert dirty.dirty_entry_count >= 1
    assert dirty.commit == identity.commit  # object id unchanged
    assert dirty.revision == f"{identity.commit}+dirty"

    with pytest.raises(DirtyTreeError):
        apply_dirty_tree_policy(dirty, DirtyTreePolicy.REJECT)


def test_ingest_git_revision_end_to_end(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "mod.py").write_text("def ready():\n    return True\n", encoding="utf-8")
    _git(repo, "add", "mod.py")
    _git(repo, "commit", "-m", "mod")

    frontend = CountingFrontend(PythonASTExtractor())
    ingestor = build_duckdb_ast_ingestor(
        frontends={"python": frontend},
        languages=("python",),
        repository_label="e2e",
    )
    publication = ingestor.ingest_git_revision(repo, created_at=10.0)
    assert publication.published is True
    assert publication.stats.parsed_count == 1
    assert publication.stats.reused_count == 0
    names = {row.name for row in publication.symbols}
    assert "ready" in names
    assert publication.identity.dirty is False
    assert len(publication.identity.commit) == 40


# ---------------------------------------------------------------------------
# Acceptance: unchanged source is not reparsed
# ---------------------------------------------------------------------------


def test_unchanged_source_is_not_reparsed_across_revisions() -> None:
    ingestor, frontend = _ingestor()

    first = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA, "pkg/b.py": SRC_BETA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    assert first.published is True
    assert first.stats.parsed_count == 2
    assert first.stats.reused_count == 0
    assert frontend.parse_invocations == 2
    parsed_after_first = frontend.parse_invocations

    # Second revision: a.py unchanged, b.py unchanged — must not reparse.
    second = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA, "pkg/b.py": SRC_BETA},
        identity=_identity(COMMIT_B, TREE_B),
        created_at=2.0,
    )
    assert second.published is True
    assert second.stats.reused_count == 2
    assert second.stats.parsed_count == 0
    assert frontend.parse_invocations == parsed_after_first
    assert all(
        decision.action == IngestAction.REUSED.value
        for decision in second.decisions
        if decision.action != IngestAction.SKIPPED.value
    )


def test_only_changed_files_are_reparsed() -> None:
    ingestor, frontend = _ingestor()

    ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA, "pkg/b.py": SRC_BETA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    frontend.reset_counts()

    second = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA_V2, "pkg/b.py": SRC_BETA},
        identity=_identity(COMMIT_B, TREE_B),
        created_at=2.0,
    )
    assert second.stats.parsed_count == 1
    assert second.stats.reused_count == 1
    assert second.stats.changed_path_count == 1
    assert frontend.parse_invocations == 1
    assert frontend.parsed_paths == ["pkg/a.py"]

    actions = {item.path: item.action for item in second.decisions}
    assert actions["pkg/a.py"] == IngestAction.PARSED.value
    assert actions["pkg/b.py"] == IngestAction.REUSED.value


def test_rename_reparses_module_and_qualified_symbol_names() -> None:
    ingestor, frontend = _ingestor()

    first = ingestor.ingest_revision(
        sources={"pkg/old_name.py": SRC_ALPHA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    assert first.stats.parsed_count == 1
    frontend.reset_counts()

    second = ingestor.ingest_revision(
        sources={"pkg/new_name.py": SRC_ALPHA},
        identity=_identity(COMMIT_B, TREE_B),
        created_at=2.0,
    )
    assert second.stats.reused_count == 0
    assert second.stats.parsed_count == 1
    assert second.stats.renamed_path_count == 1
    assert frontend.parse_invocations == 1
    assert second.projection_for_path("pkg/new_name.py") is not None
    assert second.projection_for_path("pkg/old_name.py") is None
    assert {row.qualified_name for row in second.symbols} == {"pkg.new_name.alpha"}


def test_rebind_preserves_source_cid_without_parser() -> None:
    record = PythonASTExtractor().extract_from_source(
        SRC_ALPHA,
        path="a.py",
        repository_id="repository:x",
        revision=COMMIT_A,
    )
    rebound = rebind_ast_record(
        record,
        path="a.py",
        repository_id="repository:y",
        revision=COMMIT_B,
        repository_tree_cid=record.provenance.repository_tree_cid,
    )
    assert rebound.provenance.source_cid == record.provenance.source_cid
    assert rebound.provenance.path == "a.py"
    assert rebound.provenance.revision == COMMIT_B
    assert rebound.symbols == record.symbols
    # Provenance is part of IR identity, so AST CID changes with rebind.
    assert rebound.cid != record.cid
    with pytest.raises(DuckDBIngestError, match="path changes require reparsing"):
        rebind_ast_record(record, path="b.py", repository_id="repository:y",
                          revision=COMMIT_B, repository_tree_cid=None)


# ---------------------------------------------------------------------------
# Acceptance: deleted/renamed symbols cannot leak from older revisions
# ---------------------------------------------------------------------------


def test_deleted_symbols_do_not_appear_in_successor_revision() -> None:
    ingestor, _frontend = _ingestor()

    first = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA, "pkg/b.py": SRC_BETA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    first_names = {row.name for row in first.symbols}
    assert first_names == {"alpha", "beta"}

    # Delete b.py entirely.
    second = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA},
        identity=_identity(COMMIT_B, TREE_B),
        created_at=2.0,
    )
    second_names = {row.name for row in second.symbols}
    assert second_names == {"alpha"}
    assert "beta" not in second_names
    assert second.stats.deleted_path_count == 1
    assert second.projection_for_path("pkg/b.py") is None

    # Historical revision still reports its own symbols via publication.
    assert {row.name for row in ingestor.symbols_for_revision(first.revision_id)} == {
        "alpha",
        "beta",
    }
    assert {row.name for row in ingestor.symbols_for_revision(second.revision_id)} == {
        "alpha"
    }


def test_renamed_symbols_do_not_leak_under_old_path() -> None:
    ingestor, _frontend = _ingestor()

    first = ingestor.ingest_revision(
        sources={"pkg/old.py": SRC_ALPHA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    second = ingestor.ingest_revision(
        sources={"pkg/new.py": SRC_ALPHA},
        identity=_identity(COMMIT_B, TREE_B),
        created_at=2.0,
    )
    assert second.symbols_for_path("pkg/old.py") == ()
    assert {row.name for row in second.symbols_for_path("pkg/new.py")} == {"alpha"}
    # Old path must not be part of the new revision publication.
    assert "pkg/old.py" not in [p.source_file.path for p in second.projections]
    # Invalidations record the path removal from the prior revision.
    reasons = {item.reason for item in second.invalidations}
    assert "path_removed" in reasons


def test_changed_file_invalidates_old_symbols() -> None:
    ingestor, _frontend = _ingestor()

    first = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    assert {row.name for row in first.symbols} == {"alpha"}

    # Replace alpha with gamma in the same path.
    second = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_GAMMA},
        identity=_identity(COMMIT_B, TREE_B),
        created_at=2.0,
    )
    assert {row.name for row in second.symbols} == {"gamma"}
    assert "alpha" not in {row.name for row in second.symbols}
    assert second.stats.changed_path_count == 1
    assert any(item.reason == "source_changed" for item in second.invalidations)

    # Prior revision retains historical alpha; successor must not.
    assert {
        row.name for row in ingestor.symbols_for_revision(first.revision_id)
    } == {"alpha"}
    assert {
        row.name for row in ingestor.symbols_for_revision(second.revision_id)
    } == {"gamma"}


def test_publication_is_atomic_complete_snapshot() -> None:
    ingestor, _frontend = _ingestor()
    publication = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA, "pkg/b.py": SRC_BETA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    assert publication.published is True
    assert publication.stats.published_file_count == 2
    assert len(publication.projections) == 2
    # Every projection binds the same revision identity.
    for projection in publication.projections:
        assert projection.source_revision.revision == COMMIT_A
        assert projection.source_revision.revision_id == publication.revision_id
    payload = publication.to_dict()
    assert payload["published"] is True
    assert sorted(payload["paths"]) == ["pkg/a.py", "pkg/b.py"]
    assert set(payload["symbol_names"]) == {"alpha", "beta"}


def test_source_cid_matches_bytes_for_reuse_key() -> None:
    ingestor, _frontend = _ingestor()
    publication = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA},
        identity=_identity(COMMIT_A, TREE_A),
        created_at=1.0,
    )
    decision = publication.decisions[0]
    assert decision.source_cid == cid_for_bytes(SRC_ALPHA)
    assert publication.projections[0].source_cid == decision.source_cid


def test_duplicate_revision_publish_is_idempotent() -> None:
    ingestor, frontend = _ingestor()
    identity = _identity(COMMIT_A, TREE_A)
    first = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA},
        identity=identity,
        created_at=1.0,
    )
    second = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA},
        identity=identity,
        created_at=2.0,
    )
    assert first.revision_id == second.revision_id
    assert second is first or second.published is True
    # Second call must not reparse when returning the existing publication.
    assert frontend.parse_invocations == 1


def _snapshot(sources, *, mode="filesystem", repository_id="repository:snapshot", opaque=()):
    return RepositorySnapshot(
        repository_id=repository_id,
        entries=tuple(SnapshotEntry(path, "source", len(data), cid_for_bytes(data),
                                   captured_bytes=data, disposition="filesystem")
                      for path, data in sources.items()) + tuple(opaque),
        mode=mode,
        git_commit=COMMIT_A if mode in {"git-clean", "git-working"} else None,
        git_tree=TREE_A if mode in {"git-clean", "git-working"} else None,
    )


def test_identical_bytes_at_distinct_paths_keep_distinct_modules():
    ingestor, frontend = _ingestor()
    publication = ingestor.ingest_revision(
        sources={"pkg/a.py": SRC_ALPHA, "pkg/b.py": SRC_ALPHA},
        identity=_identity(COMMIT_A, TREE_A),
    )
    assert frontend.parse_invocations == 2
    assert {row.qualified_name for row in publication.symbols} == {"pkg.a.alpha", "pkg.b.alpha"}


@pytest.mark.parametrize("change", ["frontend_version", "parser_version", "configuration"])
def test_cache_separates_native_frontend_version_toolchain_and_configuration(monkeypatch, change):
    from ipfs_datasets_py.logic.software_contracts import python_frontend
    ingestor, frontend = _ingestor()
    first = ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=_identity(COMMIT_A, TREE_A))
    if change == "frontend_version":
        monkeypatch.setattr(python_frontend, "PYTHON_FRONTEND_VERSION", "1.2.999")
    elif change == "parser_version":
        frontend._frontend.feature_version = (3, 9)
    else:
        frontend._frontend.max_ast_nodes = 1
    second = ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=_identity(COMMIT_B, TREE_B))
    assert frontend.parse_invocations == 2
    assert second.stats.reused_count == 0
    if change == "configuration":
        assert second.stats.parse_failed_count == 1
        assert not second.symbols
    else:
        assert second.projections[0].ast_cid != first.projections[0].ast_cid


def test_custom_frontend_is_not_assumed_revision_independent():
    class RevisionFrontend:
        def __init__(self):
            self.calls = 0
        def extract_from_source(self, source, **options):
            self.calls += 1
            return PythonASTExtractor().extract_from_source(
                source, module_name="revision_" + options["revision"], **options)
    frontend = RevisionFrontend()
    ingestor = DuckDBASTIngestor(frontends={"python": frontend})
    first = ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=_identity(COMMIT_A, TREE_A))
    second = ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=_identity(COMMIT_B, TREE_B))
    assert frontend.calls == 2
    assert first.symbols[0].qualified_name != second.symbols[0].qualified_name
    assert second.stats.reused_count == 0


def test_same_bytes_in_another_registered_language_do_not_reuse_python():
    js = CountingFrontend(PythonASTExtractor())
    ingestor = DuckDBASTIngestor(frontends={"python": PythonASTExtractor(), "javascript": js})
    first = ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=_identity(COMMIT_A, TREE_A))
    second = ingestor.ingest_revision(sources={"b.js": SRC_ALPHA}, identity=_identity(COMMIT_B, TREE_B))
    assert first.stats.parsed_count == second.stats.parsed_count == 1
    assert js.parse_invocations == 1
    assert second.stats.reused_count == 0
    assert {row.qualified_name for row in second.symbols} == {"b.js.alpha"}


@pytest.mark.parametrize("field", ["source_cid", "path", "revision", "repository_id", "repository_tree_cid"])
def test_frontend_provenance_mismatch_fails_before_publication(field):
    class WrongFrontend:
        def extract_from_source(self, source, **options):
            record = PythonASTExtractor().extract_from_source(source, **options)
            wrong = {"source_cid": cid_for_bytes(b"wrong"), "path": "wrong.py",
                     "revision": "wrong", "repository_id": "repository:wrong",
                     "repository_tree_cid": cid_for_bytes(b"wrong tree")}
            return replace(record, provenance=replace(record.provenance, **{field: wrong[field]}))
    ingestor = DuckDBASTIngestor(frontends={"python": WrongFrontend()})
    with pytest.raises(DuckDBIngestError, match="provenance inconsistent"):
        ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=_identity(COMMIT_A, TREE_A))
    assert ingestor.list_publications() == ()
    assert len(ingestor.shard_cache) == 0


def test_source_only_cache_calls_cannot_mint_contextual_hits():
    cache = SourceShardCache()
    record = PythonASTExtractor().extract_from_source(SRC_ALPHA)
    cache.put(record)
    assert cache.get(record.provenance.source_cid) is None
    assert len(cache) == 0


def test_cache_payload_and_context_are_reverified():
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import _frontend_cache_context
    extractor = PythonASTExtractor()
    context = _frontend_cache_context(extractor, language="python", path="a.py")
    record = extractor.extract_from_source(SRC_ALPHA, path="a.py")
    cache = SourceShardCache()
    cache.put(record, context=context)
    assert cache.get(record.provenance.source_cid, context=context) == record
    assert cache.get(record.provenance.source_cid, context=replace(context, ast_schema="other-schema")) is None
    with pytest.raises(DuckDBIngestError, match="extraction context"):
        cache.put(record, context=replace(context, path="b.py"))
    key = (record.provenance.source_cid, context.cid)
    other = extractor.extract_from_source(SRC_BETA, path="a.py")
    cache._entries[key] = (record.cid, other.canonical_bytes)
    with pytest.raises(DuckDBIngestError, match="payload identity"):
        cache.get(record.provenance.source_cid, context=context)


@pytest.mark.parametrize("mode", ["filesystem", "git-unborn", "git-clean", "git-working"])
def test_ingest_captured_snapshot_modes_and_idempotence(mode):
    ingestor, frontend = _ingestor()
    snapshot = _snapshot({"pkg/a.py": SRC_ALPHA}, mode=mode)
    first = ingestor.ingest_snapshot(snapshot, created_at=1)
    again = ingestor.ingest_snapshot(snapshot, created_at=2)
    assert again is first
    assert first.identity.snapshot_cid == snapshot.snapshot_cid
    assert first.revision == "snapshot:" + snapshot.snapshot_cid
    assert first.repository_tree_cid == snapshot.snapshot_cid
    assert first.identity.snapshot.to_dict() == snapshot.to_dict()
    assert first.repository_id == snapshot.repository_id
    assert frontend.parse_invocations == 1
    assert first.stats.published_file_count == 1
    assert first.identity.snapshot.entries[0].captured_bytes is None


def test_dirty_changes_at_same_head_get_distinct_snapshot_revisions():
    ingestor, frontend = _ingestor()
    first = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA, "b.py": SRC_BETA}, mode="git-working"))
    second = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_GAMMA, "b.py": SRC_BETA}, mode="git-working"))
    assert first.identity.snapshot.git_commit == second.identity.snapshot.git_commit
    assert first.revision_id != second.revision_id
    assert first.repository_tree_cid != second.repository_tree_cid
    assert second.stats.reused_count == 1
    assert frontend.parse_invocations == 3
    assert {row.name for row in second.symbols} == {"gamma", "beta"}


def test_snapshot_manifest_only_or_changed_capture_is_rejected():
    ingestor, _ = _ingestor()
    snapshot = _snapshot({"a.py": SRC_ALPHA})
    manifest_only = RepositorySnapshot.from_dict(snapshot.to_dict())
    with pytest.raises(DuckDBIngestError, match="captured bytes do not verify"):
        ingestor.ingest_snapshot(manifest_only)
    object.__setattr__(snapshot.entries[0], "captured_bytes", SRC_BETA)
    with pytest.raises(DuckDBIngestError, match="captured bytes do not verify"):
        ingestor.ingest_snapshot(snapshot)
    assert ingestor.list_publications() == ()


def test_snapshot_opaque_inventory_remains_bound_and_skipped():
    ingestor, _ = _ingestor()
    opaque = SnapshotEntry("deleted.py", "opaque", None, opaque_reason="unstaged_deleted",
                           acquisition="opaque", disposition="unstaged_deleted")
    snapshot = _snapshot({"a.py": SRC_ALPHA}, opaque=(opaque,))
    publication = ingestor.ingest_snapshot(snapshot)
    assert publication.stats.scanned_path_count == 2
    assert publication.stats.skipped_count == 1
    assert publication.identity.snapshot.to_dict() == snapshot.to_dict()
    assert any(row.path == "deleted.py" and row.detail == "unstaged_deleted" for row in publication.decisions)


def test_checkpoint_aborts_before_atomic_snapshot_publication():
    ingestor, frontend = _ingestor()
    before = ingestor.store.stats()
    def checkpoint():
        if frontend.parse_invocations == 1:
            raise TimeoutError("total deadline exceeded")
    with pytest.raises(TimeoutError, match="total deadline"):
        ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA}), checkpoint=checkpoint)
    assert ingestor.list_publications() == ()
    assert ingestor.store.stats() == before


def test_distinct_snapshot_repositories_do_not_invalidate_each_other():
    ingestor, _ = _ingestor()
    first = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA}, repository_id="repository:first"))
    second = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA}, repository_id="repository:second"))
    assert second.invalidations == ()
    assert ingestor.get_publication(first.revision_id) is first


def test_duplicate_git_revision_cannot_silently_rebind_different_bytes():
    ingestor, _ = _ingestor()
    identity = _identity(COMMIT_A, TREE_A)
    first = ingestor.ingest_revision(sources={"a.py": SRC_ALPHA}, identity=identity)
    with pytest.raises(DuckDBIngestError, match="already binds different"):
        ingestor.ingest_revision(sources={"a.py": SRC_BETA}, identity=identity)
    assert ingestor.get_publication(first.revision_id) is first


def test_snapshot_restore_republishes_invalidated_projections():
    ingestor, frontend = _ingestor()
    snapshot_a = _snapshot({"a.py": SRC_ALPHA})
    first = ingestor.ingest_snapshot(snapshot_a, created_at=1)
    second = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_BETA}), created_at=2)
    assert ingestor.store.get_by_ast_cid(first.projections[0].ast_cid) is None
    restored = ingestor.ingest_snapshot(snapshot_a, created_at=3)
    assert restored.revision_id == first.revision_id
    assert restored is not first
    assert restored.stats.reused_count == 1
    assert frontend.parse_invocations == 2
    assert ingestor.store.get_by_ast_cid(restored.projections[0].ast_cid) is not None
    assert ingestor.store.get_by_ast_cid(second.projections[0].ast_cid) is None
    assert ingestor.ingest_snapshot(snapshot_a, created_at=4) is restored


def test_snapshot_restore_empty_revision_invalidates_current_contents():
    ingestor, _ = _ingestor()
    empty = _snapshot({})
    first = ingestor.ingest_snapshot(empty, created_at=1)
    second = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA}), created_at=2)
    restored = ingestor.ingest_snapshot(empty, created_at=3)
    assert restored.revision_id == first.revision_id
    assert restored.projections == ()
    assert ingestor.store.get_by_ast_cid(second.projections[0].ast_cid) is None


def test_snapshot_republishes_after_external_store_invalidation():
    ingestor, _ = _ingestor()
    snapshot = _snapshot({"a.py": SRC_ALPHA})
    first = ingestor.ingest_snapshot(snapshot, created_at=1)
    ingestor.store.invalidate(blob_id=first.projections[0].blob_id, reason="manual", created_at=2)
    restored = ingestor.ingest_snapshot(snapshot, created_at=3)
    assert ingestor.store.get_by_ast_cid(restored.projections[0].ast_cid) is not None


def test_before_publish_failure_keeps_previous_complete_snapshot_active():
    ingestor, _ = _ingestor()
    first = ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA}), created_at=1)
    before_invalidations = ingestor.store.list_invalidations()
    attempted = []
    def refuse(publication):
        assert publication.published is False
        assert {row.name for row in publication.symbols} == {"beta"}
        assert ingestor.store.get_by_ast_cid(first.projections[0].ast_cid) is not None
        attempted.append(publication)
        raise OSError("manifest sealing failed")
    with pytest.raises(OSError, match="manifest sealing"):
        ingestor.ingest_snapshot(_snapshot({"a.py": SRC_BETA}), created_at=2, before_publish=refuse)
    assert len(attempted) == 1
    assert ingestor.list_publications() == (first,)
    assert ingestor.store.list_invalidations() == before_invalidations
    assert ingestor.store.get_by_ast_cid(first.projections[0].ast_cid) is not None
    assert ingestor.store.get_by_ast_cid(attempted[0].projections[0].ast_cid) is None


def test_before_publish_runs_for_active_idempotent_snapshot():
    ingestor, _ = _ingestor()
    snapshot = _snapshot({"a.py": SRC_ALPHA})
    prepared = []
    first = ingestor.ingest_snapshot(snapshot, created_at=1, before_publish=prepared.append)
    assert prepared[0].published is False
    again = ingestor.ingest_snapshot(snapshot, created_at=2, before_publish=prepared.append)
    assert again is first
    assert prepared[1] is first


def test_deadline_rechecked_after_artifact_sealing_before_sql_commit():
    ingestor, _ = _ingestor()
    sealed = []
    def checkpoint():
        if sealed:
            raise TimeoutError("deadline expired during sealing")
    with pytest.raises(TimeoutError, match="during sealing"):
        ingestor.ingest_snapshot(_snapshot({"a.py": SRC_ALPHA}),
                                 checkpoint=checkpoint, before_publish=sealed.append)
    assert len(sealed) == 1
    assert ingestor.list_publications() == ()
    assert ingestor.store.get_by_ast_cid(sealed[0].projections[0].ast_cid) is None


def test_owner_publisher_replaces_default_batch_and_runs_on_cached_retry():
    ingestor, _ = _ingestor()
    snapshot = _snapshot({"a.py": SRC_ALPHA})
    published = []
    def owner(publication):
        published.append(publication)
        ingestor.store.apply_batch(publication.projections, publication.invalidations)
    first = ingestor.ingest_snapshot(snapshot, created_at=1, publish_batch=owner)
    assert ingestor.store.stats()["puts"] == 1
    again = ingestor.ingest_snapshot(snapshot, created_at=2, publish_batch=owner)
    assert again is first
    assert len(published) == 2
    assert published[0].published is False and published[1].published is True
    assert ingestor.store.stats()["puts"] == 2


def test_owner_rejection_cannot_publish_or_bypass_cached_snapshot_checks():
    ingestor, _ = _ingestor()
    snapshot = _snapshot({"a.py": SRC_ALPHA})
    def reject(publication):
        raise ValueError("owner generation conflict")
    with pytest.raises(ValueError, match="owner generation conflict"):
        ingestor.ingest_snapshot(snapshot, publish_batch=reject)
    assert ingestor.list_publications() == ()
    assert ingestor.store.stats()["puts"] == 0
    first = ingestor.ingest_snapshot(snapshot)
    with pytest.raises(ValueError, match="owner generation conflict"):
        ingestor.ingest_snapshot(snapshot, publish_batch=reject)
    assert ingestor.list_publications() == (first,)
    assert ingestor.store.stats()["puts"] == 1
