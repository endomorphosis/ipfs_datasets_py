"""Incremental Git revision AST ingestion for the DuckDB ``asts`` catalog (DQK-032).

Ingests tracked Git source revisions into :class:`~.duckdb_ast_store.DuckDBASTStore`:

* resolve explicit Git object identity (full commit + tree SHAs);
* apply an explicit dirty-tree policy (fail-closed by default);
* reuse unchanged source shards by source CID without reparsing;
* invalidate changed/deleted files and the symbols/edges they own;
* publish each complete revision atomically (build fully, then commit).

Importing this module is inert — no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
    SourceProvenance,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTCatalogProjection,
    DuckDBASTStore,
    InvalidationRow,
    SymbolRow,
    build_duckdb_ast_store,
    project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)
from ipfs_datasets_py.logic.software_contracts.repository import (
    DISPOSITION_PARSEABLE,
    MODE_EXECUTABLE,
    MODE_REGULAR,
    TrackedBlob,
    batch_blob_bytes,
    checkout_identity,
    classify_blob,
    detect_language,
    is_git_checkout,
    list_tree_entries,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_INGEST_INTERFACE: Final = "DuckDBASTIngest@1"
DUCKDB_INGEST_SCHEMA_VERSION: Final = "duckdb-ast-ingest/v1"

# Full Git object identities (SHA-1 or SHA-256 hex, lowercase).
_GIT_OBJECT_RE: Final = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

# Languages the ingestor will attempt to parse when a frontend is registered.
DEFAULT_INGEST_LANGUAGES: Final[frozenset[str]] = frozenset(
    {"python", "typescript", "javascript"}
)

# Actor identity written on automatic invalidations.
INGEST_ACTOR_ID: Final = "duckdb-ast-ingest"

# Closed action vocabulary for per-file ingest decisions.
INGEST_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "parsed",
        "reused",
        "skipped",
        "parse_failed",
    }
)


class DuckDBIngestError(ValueError):
    """Raised when incremental AST ingestion fails closed."""


class DirtyTreeError(DuckDBIngestError):
    """Raised when dirty-tree policy rejects a working tree."""


class GitObjectIdentityError(DuckDBIngestError):
    """Raised when a Git object identity is missing or malformed."""


class DirtyTreePolicy(StrEnum):
    """Explicit dirty-tree policy for revision ingestion.

    * ``reject`` — fail closed when the working tree is dirty (default).
    * ``allow_with_marker`` — accept a dirty tree but mark the identity
      ``dirty=True`` so callers cannot mistake it for a clean commit view.
    """

    REJECT = "reject"
    ALLOW_WITH_MARKER = "allow_with_marker"


class IngestAction(StrEnum):
    """Per-file decision recorded during a revision ingest."""

    PARSED = "parsed"
    REUSED = "reused"
    SKIPPED = "skipped"
    PARSE_FAILED = "parse_failed"


# ---------------------------------------------------------------------------
# Frontend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ASTFrontendProtocol(Protocol):
    """Minimal extract surface shared by Python and TypeScript frontends."""

    def extract_from_source(
        self,
        source: str | bytes,
        *,
        path: str = ...,
        repository_id: str = ...,
        revision: str = ...,
        repository_tree_cid: str | None = ...,
        module_name: str | None = ...,
    ) -> ASTRecord: ...


# ---------------------------------------------------------------------------
# Identity and inventory models
# ---------------------------------------------------------------------------


def validate_git_object_id(value: object, *, field_name: str) -> str:
    """Require a full lowercase Git object identity (40- or 64-char hex)."""

    if type(value) is not str:
        raise GitObjectIdentityError(
            f"{field_name} must be a full lowercase Git object identity"
        )
    text = value.strip().lower()
    if not _GIT_OBJECT_RE.fullmatch(text):
        raise GitObjectIdentityError(
            f"{field_name} must be a full lowercase Git object identity "
            f"(got {value!r})"
        )
    if text != value.strip() or any(ch.isupper() for ch in value.strip()):
        # Canonical form is lowercase; reject mixed/upper to keep identity exact.
        if value.strip() != text:
            raise GitObjectIdentityError(
                f"{field_name} must be a full lowercase Git object identity"
            )
    return text


def repository_id_for_git(
    *,
    commit: str,
    tree: str,
    label: str = "repository",
) -> str:
    """Deterministic repository identity bound to Git commit + tree."""

    commit_id = validate_git_object_id(commit, field_name="commit")
    tree_id = validate_git_object_id(tree, field_name="tree")
    safe_label = str(label or "repository").strip() or "repository"
    return f"repository:git-commit:{commit_id}:tree:{tree_id}:label:{safe_label}"


def tree_cid_for_git_tree(tree: str) -> str:
    """Content-address the Git tree object identity for provenance."""

    tree_id = validate_git_object_id(tree, field_name="tree")
    return cid_for_structured(
        {
            "kind": "git-tree",
            "tree": tree_id,
            "schema": "duckdb-ast-ingest/git-tree@1",
        }
    )


@dataclass(frozen=True, slots=True)
class GitObjectIdentity:
    """Explicit Git object identity for one ingested revision.

    ``commit`` and ``tree`` are full lowercase object IDs.  ``dirty`` is an
    explicit working-tree marker; clean commit views require ``dirty=False``.
    """

    commit: str
    tree: str
    dirty: bool
    dirty_entry_count: int
    repository_path: str
    treeish: str = "HEAD"
    branch: str = ""
    dirty_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "commit",
            validate_git_object_id(self.commit, field_name="commit"),
        )
        object.__setattr__(
            self,
            "tree",
            validate_git_object_id(self.tree, field_name="tree"),
        )
        if type(self.dirty) is not bool:
            raise GitObjectIdentityError("dirty must be an exact bool")
        if type(self.dirty_entry_count) is not int or self.dirty_entry_count < 0:
            raise GitObjectIdentityError(
                "dirty_entry_count must be a non-negative integer"
            )
        if self.dirty and self.dirty_entry_count == 0:
            raise GitObjectIdentityError(
                "dirty identity requires dirty_entry_count > 0"
            )
        if not self.dirty and self.dirty_entry_count != 0:
            raise GitObjectIdentityError(
                "clean identity requires dirty_entry_count == 0"
            )
        object.__setattr__(
            self, "repository_path", str(self.repository_path or "").strip()
        )
        object.__setattr__(
            self, "treeish", str(self.treeish or "HEAD").strip() or "HEAD"
        )
        object.__setattr__(self, "branch", str(self.branch or ""))
        paths = tuple(str(item) for item in self.dirty_paths)
        object.__setattr__(self, "dirty_paths", paths)

    @property
    def clean(self) -> bool:
        return not self.dirty

    @property
    def revision(self) -> str:
        """Revision string bound into AST provenance.

        Clean trees use the commit object id alone.  Dirty trees append an
        explicit ``+dirty`` marker so they never collide with the clean
        commit view of the same object.
        """

        if self.dirty:
            return f"{self.commit}+dirty"
        return self.commit

    def repository_id(self, *, label: str = "repository") -> str:
        return repository_id_for_git(
            commit=self.commit, tree=self.tree, label=label
        )

    def repository_tree_cid(self) -> str:
        return tree_cid_for_git_tree(self.tree)

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "tree": self.tree,
            "dirty": self.dirty,
            "dirty_entry_count": self.dirty_entry_count,
            "clean": self.clean,
            "repository_path": self.repository_path,
            "treeish": self.treeish,
            "branch": self.branch,
            "dirty_paths": list(self.dirty_paths),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GitObjectIdentity":
        if not isinstance(value, Mapping):
            raise GitObjectIdentityError("Git object identity must be an object")
        return cls(
            commit=str(value["commit"]),
            tree=str(value["tree"]),
            dirty=bool(value["dirty"]),
            dirty_entry_count=int(value.get("dirty_entry_count") or 0),
            repository_path=str(value.get("repository_path") or ""),
            treeish=str(value.get("treeish") or "HEAD"),
            branch=str(value.get("branch") or ""),
            dirty_paths=tuple(value.get("dirty_paths") or ()),
        )


def _git_rev_parse(repository: Path, treeish: str) -> tuple[str, str]:
    """Return ``(commit, tree)`` object ids for ``treeish``."""

    def _run(args: Sequence[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repository),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.decode("utf-8", errors="replace").strip()

    commit = _run(["rev-parse", treeish])
    tree = _run(["rev-parse", f"{treeish}^{{tree}}"])
    if not commit or not tree:
        raise GitObjectIdentityError(
            f"unable to resolve treeish {treeish!r} in {repository}"
        )
    return commit, tree


def resolve_git_object_identity(
    repository: Path | str,
    *,
    treeish: str = "HEAD",
) -> GitObjectIdentity:
    """Resolve full commit/tree identity and dirty state for a checkout.

    Identity always comes from Git objects (``rev-parse``), never from ambient
    filesystem mtimes.  Dirty status is recorded explicitly and does not alter
    the commit/tree object ids.
    """

    root = Path(repository).resolve()
    if not is_git_checkout(root):
        raise GitObjectIdentityError(
            f"path is not a git checkout: {root}"
        )
    identity = checkout_identity(root, label="ingest", relative_path=".")
    if identity is None:
        raise GitObjectIdentityError(
            f"unable to resolve git identity for {root}"
        )
    if treeish in {"HEAD", "head", "@"}:
        commit = str(identity.get("commit") or "")
        tree = str(identity.get("tree") or "")
        if not commit or not tree:
            raise GitObjectIdentityError(
                f"unable to resolve HEAD identity for {root}"
            )
    else:
        commit, tree = _git_rev_parse(root, treeish)

    dirty = bool(identity.get("dirty"))
    dirty_count = int(identity.get("dirty_entry_count") or 0)
    dirty_paths: tuple[str, ...] = ()
    if dirty:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        status = status_result.stdout.decode("utf-8", errors="replace")
        dirty_paths = tuple(
            line[3:].strip() if len(line) > 3 else line.strip()
            for line in status.splitlines()
            if line.strip()
        )
        dirty_count = max(dirty_count, len(dirty_paths))
    return GitObjectIdentity(
        commit=commit,
        tree=tree,
        dirty=dirty,
        dirty_entry_count=dirty_count if dirty else 0,
        repository_path=str(root),
        treeish=treeish,
        branch=str(identity.get("branch") or ""),
        dirty_paths=dirty_paths,
    )


def apply_dirty_tree_policy(
    identity: GitObjectIdentity,
    policy: DirtyTreePolicy | str = DirtyTreePolicy.REJECT,
) -> GitObjectIdentity:
    """Apply the explicit dirty-tree policy; fail closed by default."""

    if not isinstance(identity, GitObjectIdentity):
        raise DuckDBIngestError("identity must be an exact GitObjectIdentity")
    policy_value = DirtyTreePolicy(str(policy))
    if not identity.dirty:
        return identity
    if policy_value is DirtyTreePolicy.REJECT:
        raise DirtyTreeError(
            "repository working tree is dirty; AST ingestion requires a clean "
            "tree under DirtyTreePolicy.REJECT "
            f"(dirty_entry_count={identity.dirty_entry_count}, "
            f"paths={list(identity.dirty_paths[:8])})"
        )
    # allow_with_marker: identity already carries dirty=True and +dirty revision.
    return identity


# ---------------------------------------------------------------------------
# Ingest result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FileIngestDecision:
    """One file's ingest outcome within a revision publication."""

    path: str
    source_cid: str
    language: str
    action: str
    git_oid: str
    blob_id: str | None = None
    ast_cid: str | None = None
    parse_count: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        action = str(self.action)
        if action not in INGEST_ACTIONS:
            raise DuckDBIngestError(f"unknown ingest action: {action!r}")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "path", _normalize_repo_path(self.path))
        if type(self.parse_count) is not int or self.parse_count < 0:
            raise DuckDBIngestError("parse_count must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_cid": self.source_cid,
            "language": self.language,
            "action": self.action,
            "git_oid": self.git_oid,
            "blob_id": self.blob_id,
            "ast_cid": self.ast_cid,
            "parse_count": self.parse_count,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class RevisionIngestStats:
    """Aggregate counters for one atomic revision publication."""

    scanned_path_count: int = 0
    parseable_path_count: int = 0
    parsed_count: int = 0
    reused_count: int = 0
    skipped_count: int = 0
    parse_failed_count: int = 0
    invalidated_count: int = 0
    deleted_path_count: int = 0
    changed_path_count: int = 0
    renamed_path_count: int = 0
    published_file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_path_count": self.scanned_path_count,
            "parseable_path_count": self.parseable_path_count,
            "parsed_count": self.parsed_count,
            "reused_count": self.reused_count,
            "skipped_count": self.skipped_count,
            "parse_failed_count": self.parse_failed_count,
            "invalidated_count": self.invalidated_count,
            "deleted_path_count": self.deleted_path_count,
            "changed_path_count": self.changed_path_count,
            "renamed_path_count": self.renamed_path_count,
            "published_file_count": self.published_file_count,
            "parse_invocations": self.parsed_count + self.parse_failed_count,
        }


@dataclass(frozen=True, slots=True)
class RevisionPublication:
    """Complete, atomically published AST revision snapshot.

    Callers treat a publication as authoritative only when ``published`` is
    true.  Partials never leave the store in a half-written revision state:
    either every planned put/invalidation lands, or none do.
    """

    revision_id: str
    repository_id: str
    revision: str
    identity: GitObjectIdentity
    repository_tree_cid: str
    projections: tuple[ASTCatalogProjection, ...]
    decisions: tuple[FileIngestDecision, ...]
    invalidations: tuple[InvalidationRow, ...]
    stats: RevisionIngestStats
    dirty_tree_policy: str
    published: bool
    schema_version: str = DUCKDB_INGEST_SCHEMA_VERSION
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if type(self.published) is not bool:
            raise DuckDBIngestError("published must be an exact bool")
        paths = [item.source_file.path for item in self.projections]
        if len(set(paths)) != len(paths):
            raise DuckDBIngestError(
                "revision publication must not contain duplicate paths"
            )

    @property
    def symbols(self) -> tuple[SymbolRow, ...]:
        rows: list[SymbolRow] = []
        for projection in self.projections:
            rows.extend(projection.symbols)
        return tuple(rows)

    def symbols_for_path(self, path: str) -> tuple[SymbolRow, ...]:
        normalized = _normalize_repo_path(path)
        for projection in self.projections:
            if projection.source_file.path == normalized:
                return projection.symbols
        return ()

    def projection_for_path(self, path: str) -> ASTCatalogProjection | None:
        normalized = _normalize_repo_path(path)
        for projection in self.projections:
            if projection.source_file.path == normalized:
                return projection
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision_id": self.revision_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "identity": self.identity.to_dict(),
            "repository_tree_cid": self.repository_tree_cid,
            "dirty_tree_policy": self.dirty_tree_policy,
            "published": self.published,
            "created_at": self.created_at,
            "stats": self.stats.to_dict(),
            "paths": [item.source_file.path for item in self.projections],
            "decisions": [item.to_dict() for item in self.decisions],
            "invalidation_ids": [
                item.invalidation_id for item in self.invalidations
            ],
            "symbol_names": sorted({row.name for row in self.symbols}),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_repo_path(path: str) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise DuckDBIngestError("repository path must be non-empty")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts:
        raise DuckDBIngestError(f"repository path escapes its root: {path!r}")
    return pure.as_posix()


def _revision_id(repository_id: str, revision: str) -> str:
    return f"rev:{repository_id}:{revision}"


def rebind_ast_record(
    record: ASTRecord,
    *,
    path: str,
    repository_id: str,
    revision: str,
    repository_tree_cid: str | None,
) -> ASTRecord:
    """Rebind an already-parsed ASTRecord to a new revision/path.

    Structural facts (scopes, symbols, edges, frontend) are preserved.  Only
    :class:`SourceProvenance` changes, so the source CID stays identical and
    no parser is invoked.  The AST IR CID changes with the new provenance
    binding, matching the shared IR identity rules.
    """

    if type(record) is not ASTRecord:
        raise DuckDBIngestError("rebind_ast_record requires an exact ASTRecord")
    provenance = SourceProvenance(
        source_cid=record.provenance.source_cid,
        path=_normalize_repo_path(path),
        repository_id=repository_id,
        revision=revision,
        repository_tree_cid=repository_tree_cid,
    )
    return ASTRecord(
        provenance=provenance,
        frontend=record.frontend,
        module=record.module,
        scopes=record.scopes,
        symbols=record.symbols,
        imports=record.imports,
        references=record.references,
        calls=record.calls,
        effects=record.effects,
        diagnostics=record.diagnostics,
        unsupported=record.unsupported,
        schema_version=record.schema_version,
    )


def _language_for_path(path: str) -> str:
    return detect_language(path)


# ---------------------------------------------------------------------------
# Source-CID shard cache (reuse without reparse)
# ---------------------------------------------------------------------------


@dataclass
class SourceShardCache:
    """In-memory cache of parsed AST IR keyed by source-byte CID.

    Unchanged source shards are reused across revisions and renames by looking
    up ``source_cid`` — the parser is never re-entered for a cache hit.
    """

    _by_source_cid: dict[str, ASTRecord] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, source_cid: str) -> ASTRecord | None:
        found = self._by_source_cid.get(source_cid)
        if found is None:
            self.misses += 1
            return None
        self.hits += 1
        return found

    def put(self, record: ASTRecord) -> None:
        if type(record) is not ASTRecord:
            raise DuckDBIngestError("cache requires an exact ASTRecord")
        self._by_source_cid[record.provenance.source_cid] = record

    def __contains__(self, source_cid: object) -> bool:
        return source_cid in self._by_source_cid

    def __len__(self) -> int:
        return len(self._by_source_cid)

    def clear(self) -> None:
        self._by_source_cid.clear()
        self.hits = 0
        self.misses = 0


# ---------------------------------------------------------------------------
# Counting frontend wrapper (test / telemetry)
# ---------------------------------------------------------------------------


class CountingFrontend:
    """Wrap an :class:`ASTFrontendProtocol` and count parse invocations."""

    def __init__(self, frontend: ASTFrontendProtocol) -> None:
        self._frontend = frontend
        self.parse_invocations = 0
        self.parsed_paths: list[str] = []

    def extract_from_source(
        self,
        source: str | bytes,
        *,
        path: str = "source.py",
        repository_id: str = "repository:unknown",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        module_name: str | None = None,
    ) -> ASTRecord:
        self.parse_invocations += 1
        self.parsed_paths.append(path)
        return self._frontend.extract_from_source(
            source,
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
            module_name=module_name,
        )

    def reset_counts(self) -> None:
        self.parse_invocations = 0
        self.parsed_paths.clear()


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------


class DuckDBASTIngestor:
    """Incremental AST ingestor with CID reuse and atomic revision publish.

    Workflow for each revision:

    1. Resolve and validate :class:`GitObjectIdentity` (or accept an explicit
       identity for synthetic fixtures).
    2. Apply :class:`DirtyTreePolicy`.
    3. Inventory tracked parseable blobs (Git objects, not dirty worktree
       bytes, unless the caller supplies an explicit source map).
    4. For each path: reuse by ``source_cid`` or parse once.
    5. Diff against the previous complete publication for the same
       ``repository_id`` label family: invalidate deleted/changed paths.
    6. Publish the complete revision atomically into the AST store.
    """

    def __init__(
        self,
        *,
        store: DuckDBASTStore | None = None,
        frontends: Mapping[str, ASTFrontendProtocol] | None = None,
        dirty_tree_policy: DirtyTreePolicy | str = DirtyTreePolicy.REJECT,
        languages: Sequence[str] | frozenset[str] | None = None,
        repository_label: str = "repository",
    ) -> None:
        self._store = store if store is not None else build_duckdb_ast_store()
        self._lock = threading.RLock()
        self._shard_cache = SourceShardCache()
        self._publications: dict[str, RevisionPublication] = {}
        self._latest_by_label: dict[str, str] = {}
        self._dirty_tree_policy = DirtyTreePolicy(str(dirty_tree_policy))
        self._repository_label = str(repository_label or "repository")
        self._languages: frozenset[str] = frozenset(
            languages if languages is not None else DEFAULT_INGEST_LANGUAGES
        )
        if frontends is None:
            python = CountingFrontend(PythonASTExtractor())
            self._frontends: dict[str, ASTFrontendProtocol] = {
                "python": python,
            }
        else:
            self._frontends = {
                str(language): frontend for language, frontend in frontends.items()
            }
        self._stats = {
            "revisions_published": 0,
            "parse_invocations": 0,
            "reuse_hits": 0,
            "invalidations": 0,
        }

    @property
    def interface(self) -> str:
        return DUCKDB_INGEST_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_INGEST_SCHEMA_VERSION

    @property
    def store(self) -> DuckDBASTStore:
        return self._store

    @property
    def dirty_tree_policy(self) -> DirtyTreePolicy:
        return self._dirty_tree_policy

    @property
    def shard_cache(self) -> SourceShardCache:
        return self._shard_cache

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                **self._stats,
                "cache_size": len(self._shard_cache),
                "cache_hits": self._shard_cache.hits,
                "cache_misses": self._shard_cache.misses,
                "publication_count": len(self._publications),
            }

    def get_publication(self, revision_id: str) -> RevisionPublication | None:
        with self._lock:
            return self._publications.get(revision_id)

    def list_publications(self) -> tuple[RevisionPublication, ...]:
        with self._lock:
            return tuple(self._publications.values())

    def symbols_for_revision(self, revision_id: str) -> tuple[SymbolRow, ...]:
        """Return only symbols published under ``revision_id`` (no leakage)."""

        publication = self.get_publication(revision_id)
        if publication is None or not publication.published:
            return ()
        return publication.symbols

    # -- public ingest entry points ----------------------------------------

    def ingest_git_revision(
        self,
        repository: Path | str,
        *,
        treeish: str = "HEAD",
        dirty_tree_policy: DirtyTreePolicy | str | None = None,
        created_at: float | None = None,
        path_prefix: str | None = None,
    ) -> RevisionPublication:
        """Ingest one tracked Git revision from object identity."""

        identity = resolve_git_object_identity(repository, treeish=treeish)
        policy = (
            self._dirty_tree_policy
            if dirty_tree_policy is None
            else DirtyTreePolicy(str(dirty_tree_policy))
        )
        identity = apply_dirty_tree_policy(identity, policy)
        root = Path(repository).resolve()
        blobs = self._list_tracked_source_blobs(
            root, treeish=treeish, path_prefix=path_prefix
        )
        sources = self._materialize_blob_bytes(root, blobs)
        return self.ingest_revision(
            sources=sources,
            identity=identity,
            blobs=blobs,
            dirty_tree_policy=policy,
            created_at=created_at,
        )

    def ingest_revision(
        self,
        *,
        sources: Mapping[str, bytes],
        identity: GitObjectIdentity,
        blobs: Sequence[TrackedBlob] | None = None,
        dirty_tree_policy: DirtyTreePolicy | str | None = None,
        created_at: float | None = None,
        repository_id: str | None = None,
    ) -> RevisionPublication:
        """Build and atomically publish one complete revision from sources.

        ``sources`` maps repository-relative paths to exact source bytes.  When
        a prior complete publication exists for the same repository label, file
        decisions reuse source CIDs and emit invalidations for deleted/changed
        paths so older symbols cannot leak into the new revision.
        """

        if not isinstance(identity, GitObjectIdentity):
            raise DuckDBIngestError("identity must be an exact GitObjectIdentity")
        policy = (
            self._dirty_tree_policy
            if dirty_tree_policy is None
            else DirtyTreePolicy(str(dirty_tree_policy))
        )
        identity = apply_dirty_tree_policy(identity, policy)
        now = time.time() if created_at is None else float(created_at)
        repo_id = repository_id or identity.repository_id(
            label=self._repository_label
        )
        revision = identity.revision
        revision_id = _revision_id(repo_id, revision)
        tree_cid = identity.repository_tree_cid()

        normalized_sources = {
            _normalize_repo_path(path): data for path, data in sources.items()
        }
        blob_by_path: dict[str, TrackedBlob] = {}
        if blobs is not None:
            for blob in blobs:
                blob_by_path[_normalize_repo_path(blob.path)] = blob

        # --- Phase 1: plan (no store mutations) ---------------------------
        decisions: list[FileIngestDecision] = []
        planned: list[tuple[str, ASTRecord, IngestAction]] = []
        parseable_paths = 0
        parsed = 0
        reused = 0
        skipped = 0
        parse_failed = 0

        for path in sorted(normalized_sources):
            data = normalized_sources[path]
            language = _language_for_path(path)
            blob = blob_by_path.get(path)
            git_oid = blob.git_oid if blob is not None else ""
            source_cid = (
                blob.cid
                if blob is not None and blob.cid
                else cid_for_bytes(data)
            )
            # Prefer recomputed source CID so identity matches the bytes we parse.
            recomputed = cid_for_bytes(data)
            if source_cid != recomputed:
                source_cid = recomputed

            if blob is not None and blob.parser_disposition != DISPOSITION_PARSEABLE:
                # Still allow languages with registered frontends when the
                # repository inventory marks them unsupported (e.g. TypeScript
                # before inventory disposition expansion).
                if language not in self._frontends or language not in self._languages:
                    decisions.append(
                        FileIngestDecision(
                            path=path,
                            source_cid=source_cid,
                            language=language,
                            action=IngestAction.SKIPPED.value,
                            git_oid=git_oid,
                            detail=blob.exclusion_reason or blob.parser_disposition,
                        )
                    )
                    skipped += 1
                    continue

            if language not in self._frontends or language not in self._languages:
                decisions.append(
                    FileIngestDecision(
                        path=path,
                        source_cid=source_cid,
                        language=language,
                        action=IngestAction.SKIPPED.value,
                        git_oid=git_oid,
                        detail=f"no_frontend_for_language:{language}",
                    )
                )
                skipped += 1
                continue

            parseable_paths += 1
            record, action = self._parse_or_reuse(
                source_cid=source_cid,
                data=data,
                path=path,
                language=language,
                repository_id=repo_id,
                revision=revision,
                repository_tree_cid=tree_cid,
            )
            if action is IngestAction.PARSED:
                parsed += 1
            elif action is IngestAction.REUSED:
                reused += 1
            elif action is IngestAction.PARSE_FAILED:
                parse_failed += 1
            planned.append((path, record, action))
            decisions.append(
                FileIngestDecision(
                    path=path,
                    source_cid=source_cid,
                    language=language,
                    action=action.value,
                    git_oid=git_oid,
                    parse_count=1 if action is IngestAction.PARSED else 0,
                    detail="" if action is not IngestAction.PARSE_FAILED else "parse_failed",
                )
            )

        # Build projections off-store so publish is atomic.
        projections: list[ASTCatalogProjection] = []
        for path, record, action in planned:
            projection = project_ast_record(record, created_at=now)
            projections.append(projection)
            # Fill decision identities now that projection exists.
            for index, decision in enumerate(decisions):
                if decision.path == path and decision.blob_id is None:
                    decisions[index] = FileIngestDecision(
                        path=decision.path,
                        source_cid=decision.source_cid,
                        language=decision.language,
                        action=decision.action,
                        git_oid=decision.git_oid,
                        blob_id=projection.blob_id,
                        ast_cid=projection.ast_cid,
                        parse_count=decision.parse_count,
                        detail=decision.detail,
                    )
                    break

        # Diff against previous complete publication for invalidations.
        previous = self._previous_publication(repo_id)
        invalidations: list[InvalidationRow] = []
        deleted_paths = 0
        changed_paths = 0
        renamed_paths = 0
        if previous is not None:
            prev_by_path = {
                item.source_file.path: item for item in previous.projections
            }
            curr_by_path = {
                item.source_file.path: item for item in projections
            }
            curr_by_source = {
                item.source_cid: item for item in projections
            }
            for path, old in sorted(prev_by_path.items()):
                replacement = curr_by_path.get(path)
                if replacement is not None:
                    if replacement.source_cid == old.source_cid:
                        continue
                    changed_paths += 1
                    invalidations.append(
                        self._plan_invalidation(
                            blob_id=old.blob_id,
                            file_id=old.source_file.file_id,
                            revision_id=previous.revision_id,
                            reason="source_changed",
                            detail=(
                                f"path {path} source_cid "
                                f"{old.source_cid} -> {replacement.source_cid}"
                            ),
                            created_at=now,
                        )
                    )
                else:
                    # Path removed.  If the source CID appears at a new path,
                    # count as rename rather than pure deletion of the shard.
                    if old.source_cid in curr_by_source:
                        renamed_paths += 1
                        invalidations.append(
                            self._plan_invalidation(
                                blob_id=old.blob_id,
                                file_id=old.source_file.file_id,
                                revision_id=previous.revision_id,
                                reason="path_removed",
                                detail=(
                                    f"path {path} renamed/moved; "
                                    f"source_cid {old.source_cid} reused"
                                ),
                                created_at=now,
                            )
                        )
                    else:
                        deleted_paths += 1
                        invalidations.append(
                            self._plan_invalidation(
                                blob_id=old.blob_id,
                                file_id=old.source_file.file_id,
                                revision_id=previous.revision_id,
                                reason="path_removed",
                                detail=f"path {path} deleted in {revision}",
                                created_at=now,
                            )
                        )
            # Supersede the previous revision as a whole once a successor exists.
            invalidations.append(
                self._plan_invalidation(
                    blob_id=None,
                    file_id=None,
                    revision_id=previous.revision_id,
                    reason="revision_superseded",
                    detail=f"superseded by {revision_id}",
                    created_at=now,
                )
            )

        stats = RevisionIngestStats(
            scanned_path_count=len(normalized_sources),
            parseable_path_count=parseable_paths,
            parsed_count=parsed,
            reused_count=reused,
            skipped_count=skipped,
            parse_failed_count=parse_failed,
            invalidated_count=len(invalidations),
            deleted_path_count=deleted_paths,
            changed_path_count=changed_paths,
            renamed_path_count=renamed_paths,
            published_file_count=len(projections),
        )

        # --- Phase 2: atomic publish --------------------------------------
        with self._lock:
            if revision_id in self._publications:
                existing = self._publications[revision_id]
                if existing.published:
                    return existing
            committed_projections: list[ASTCatalogProjection] = []
            committed_invalidations: list[InvalidationRow] = []
            try:
                for projection in projections:
                    stored = self._store.put_projection(projection)
                    committed_projections.append(stored)
                    # Seed shard cache from durable payload so subsequent
                    # revisions can rebind without reparsing.
                    try:
                        record = ASTRecord.from_dict(
                            json.loads(stored.ast_blob.payload_json)
                        )
                        self._shard_cache.put(record)
                    except Exception:
                        # Cache population is best-effort; projection already stored.
                        pass
                for planned_inv in invalidations:
                    row = self._store.invalidate(
                        blob_id=planned_inv.blob_id,
                        file_id=planned_inv.file_id,
                        revision_id=planned_inv.revision_id,
                        reason=planned_inv.reason,
                        actor_id=planned_inv.actor_id,
                        detail=planned_inv.detail,
                        created_at=planned_inv.created_at,
                    )
                    committed_invalidations.append(row)
                publication = RevisionPublication(
                    revision_id=revision_id,
                    repository_id=repo_id,
                    revision=revision,
                    identity=identity,
                    repository_tree_cid=tree_cid,
                    projections=tuple(committed_projections),
                    decisions=tuple(decisions),
                    invalidations=tuple(committed_invalidations),
                    stats=stats,
                    dirty_tree_policy=policy.value,
                    published=True,
                    created_at=now,
                )
                self._publications[revision_id] = publication
                # Track latest by stable label (not commit-bound repository_id)
                # so successive commits for the same logical repo chain.
                self._latest_by_label[self._repository_label] = revision_id
                self._stats["revisions_published"] += 1
                self._stats["parse_invocations"] += parsed + parse_failed
                self._stats["reuse_hits"] += reused
                self._stats["invalidations"] += len(committed_invalidations)
                return publication
            except Exception:
                # Best-effort rollback of projections written in this attempt.
                for projection in committed_projections:
                    try:
                        self._store.invalidate(
                            blob_id=projection.blob_id,
                            file_id=projection.source_file.file_id,
                            revision_id=projection.source_revision.revision_id,
                            reason="manual",
                            actor_id=INGEST_ACTOR_ID,
                            detail="atomic_publish_rollback",
                            created_at=now,
                        )
                    except Exception:
                        pass
                raise

    # -- internals ---------------------------------------------------------

    def _previous_publication(
        self, repository_id: str
    ) -> RevisionPublication | None:
        """Return the previous complete publication for the logical repo label.

        Publications bind ``repository_id`` to a specific commit/tree, so chain
        continuity uses the stable ``repository_label`` rather than equality of
        the commit-bound id.
        """

        latest_id = self._latest_by_label.get(self._repository_label)
        if latest_id is None:
            # Fallback: any published revision sharing the label prefix pattern.
            for publication in reversed(list(self._publications.values())):
                if publication.published:
                    return publication
            return None
        return self._publications.get(latest_id)

    def _parse_or_reuse(
        self,
        *,
        source_cid: str,
        data: bytes,
        path: str,
        language: str,
        repository_id: str,
        revision: str,
        repository_tree_cid: str,
    ) -> tuple[ASTRecord, IngestAction]:
        cached = self._shard_cache.get(source_cid)
        if cached is not None and cached.provenance.source_cid == source_cid:
            rebound = rebind_ast_record(
                cached,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
            )
            return rebound, IngestAction.REUSED

        frontend = self._frontends.get(language)
        if frontend is None:
            raise DuckDBIngestError(f"no frontend registered for {language}")
        record = frontend.extract_from_source(
            data,
            path=path,
            repository_id=repository_id,
            revision=revision,
            repository_tree_cid=repository_tree_cid,
        )
        # Ensure provenance source_cid matches the inventory identity.
        if record.provenance.source_cid != source_cid:
            record = rebind_ast_record(
                record,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
            )
            # rebind preserves prior source_cid; force alignment when parse
            # used the same bytes (cid_for_bytes must match).
            if record.provenance.source_cid != source_cid:
                # Rebuild provenance with the inventory CID when bytes agree.
                if cid_for_bytes(data) == source_cid:
                    record = ASTRecord(
                        provenance=SourceProvenance(
                            source_cid=source_cid,
                            path=path,
                            repository_id=repository_id,
                            revision=revision,
                            repository_tree_cid=repository_tree_cid,
                        ),
                        frontend=record.frontend,
                        module=record.module,
                        scopes=record.scopes,
                        symbols=record.symbols,
                        imports=record.imports,
                        references=record.references,
                        calls=record.calls,
                        effects=record.effects,
                        diagnostics=record.diagnostics,
                        unsupported=record.unsupported,
                        schema_version=record.schema_version,
                    )
        self._shard_cache.put(record)
        # Parse failures remain durable AST facts; classify action for stats.
        failed = any(
            "parse_error" in item.code
            or "invalid_encoding" in item.code
            or item.code.endswith("resource_limit")
            for item in record.diagnostics
        ) and not record.symbols
        action = IngestAction.PARSE_FAILED if failed else IngestAction.PARSED
        return record, action

    def _plan_invalidation(
        self,
        *,
        blob_id: str | None,
        file_id: str | None,
        revision_id: str | None,
        reason: str,
        detail: str,
        created_at: float,
    ) -> InvalidationRow:
        invalidation_id = (
            f"inv:{blob_id or file_id or revision_id or 'global'}:"
            f"{reason}:{int(created_at * 1_000_000)}"
        )
        return InvalidationRow(
            invalidation_id=invalidation_id,
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            reason=reason,
            actor_id=INGEST_ACTOR_ID,
            detail=detail,
            created_at=created_at,
        )

    def _list_tracked_source_blobs(
        self,
        repository: Path,
        *,
        treeish: str,
        path_prefix: str | None,
    ) -> list[TrackedBlob]:
        entries = list_tree_entries(repository, treeish=treeish)
        blobs: list[TrackedBlob] = []
        prefix = (
            _normalize_repo_path(path_prefix) + "/"
            if path_prefix
            else ""
        )
        for entry in entries:
            if entry.get("type") != "blob":
                continue
            path = _normalize_repo_path(str(entry["path"]))
            if prefix and not (path == prefix.rstrip("/") or path.startswith(prefix)):
                continue
            mode = str(entry.get("mode") or MODE_REGULAR)
            if mode not in {MODE_REGULAR, MODE_EXECUTABLE}:
                continue
            size_bytes = int(entry.get("size_bytes") or 0)
            language, disposition, reason, coverage = classify_blob(
                path,
                mode=mode,
                size_bytes=size_bytes,
            )
            # Include parseable inventory rows and languages we can front-end
            # even when the repository disposition still says unsupported.
            if disposition != DISPOSITION_PARSEABLE and language not in self._frontends:
                continue
            if language not in self._languages and disposition != DISPOSITION_PARSEABLE:
                continue
            blobs.append(
                TrackedBlob(
                    path=path,
                    mode=mode,
                    git_oid=str(entry.get("oid") or ""),
                    size_bytes=size_bytes,
                    cid="",  # filled after materialization
                    language=language,
                    parser_disposition=disposition,
                    exclusion_reason=reason,
                    coverage_status=coverage,
                    logical_root=path.split("/", 1)[0] if "/" in path else path,
                )
            )
        return blobs

    def _materialize_blob_bytes(
        self,
        repository: Path,
        blobs: Sequence[TrackedBlob],
    ) -> dict[str, bytes]:
        oids = [blob.git_oid for blob in blobs if blob.git_oid]
        fetched = batch_blob_bytes(repository, oids) if oids else {}
        sources: dict[str, bytes] = {}
        for blob in blobs:
            data = fetched.get(blob.git_oid)
            if data is None:
                continue
            sources[blob.path] = data
        return sources


def build_duckdb_ast_ingestor(
    *,
    store: DuckDBASTStore | None = None,
    frontends: Mapping[str, ASTFrontendProtocol] | None = None,
    dirty_tree_policy: DirtyTreePolicy | str = DirtyTreePolicy.REJECT,
    languages: Sequence[str] | frozenset[str] | None = None,
    repository_label: str = "repository",
) -> DuckDBASTIngestor:
    """Construct a :class:`DuckDBASTIngestor` with standard defaults."""

    return DuckDBASTIngestor(
        store=store,
        frontends=frontends,
        dirty_tree_policy=dirty_tree_policy,
        languages=languages,
        repository_label=repository_label,
    )


def ingest_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable ingest interface statement."""

    return {
        "interface": DUCKDB_INGEST_INTERFACE,
        "schema_version": DUCKDB_INGEST_SCHEMA_VERSION,
        "dirty_tree_policies": sorted(item.value for item in DirtyTreePolicy),
        "default_dirty_tree_policy": DirtyTreePolicy.REJECT.value,
        "ingest_actions": sorted(INGEST_ACTIONS),
        "default_languages": sorted(DEFAULT_INGEST_LANGUAGES),
        "guarantees": {
            "unchanged_source_not_reparsed": True,
            "reuse_by_source_cid": True,
            "deleted_symbols_cannot_leak": True,
            "atomic_revision_publish": True,
            "dirty_tree_policy_explicit": True,
            "git_object_identity_explicit": True,
            "import_inert": True,
        },
    }


__all__ = [
    "ASTFrontendProtocol",
    "CountingFrontend",
    "DEFAULT_INGEST_LANGUAGES",
    "DUCKDB_INGEST_INTERFACE",
    "DUCKDB_INGEST_SCHEMA_VERSION",
    "DirtyTreeError",
    "DirtyTreePolicy",
    "DuckDBASTIngestor",
    "DuckDBIngestError",
    "FileIngestDecision",
    "GitObjectIdentity",
    "GitObjectIdentityError",
    "INGEST_ACTIONS",
    "INGEST_ACTOR_ID",
    "IngestAction",
    "RevisionIngestStats",
    "RevisionPublication",
    "SourceShardCache",
    "apply_dirty_tree_policy",
    "build_duckdb_ast_ingestor",
    "ingest_schema_descriptor",
    "rebind_ast_record",
    "repository_id_for_git",
    "resolve_git_object_identity",
    "tree_cid_for_git_tree",
    "validate_git_object_id",
]
