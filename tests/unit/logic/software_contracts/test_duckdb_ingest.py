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
    GitObjectIdentity,
    GitObjectIdentityError,
    IngestAction,
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


def test_rename_reuses_source_cid_without_reparse() -> None:
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
    assert second.stats.reused_count == 1
    assert second.stats.parsed_count == 0
    assert second.stats.renamed_path_count == 1
    assert frontend.parse_invocations == 0
    assert second.projection_for_path("pkg/new_name.py") is not None
    assert second.projection_for_path("pkg/old_name.py") is None


def test_rebind_preserves_source_cid_without_parser() -> None:
    record = PythonASTExtractor().extract_from_source(
        SRC_ALPHA,
        path="a.py",
        repository_id="repository:x",
        revision=COMMIT_A,
    )
    rebound = rebind_ast_record(
        record,
        path="b.py",
        repository_id="repository:y",
        revision=COMMIT_B,
        repository_tree_cid=record.provenance.repository_tree_cid,
    )
    assert rebound.provenance.source_cid == record.provenance.source_cid
    assert rebound.provenance.path == "b.py"
    assert rebound.provenance.revision == COMMIT_B
    assert rebound.symbols == record.symbols
    # Provenance is part of IR identity, so AST CID changes with rebind.
    assert rebound.cid != record.cid


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
