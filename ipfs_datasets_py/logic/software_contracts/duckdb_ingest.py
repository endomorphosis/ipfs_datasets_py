"""Incremental Git revision AST ingestion for the DuckDB ``asts`` catalog (DQK-032).

Ingests tracked Git source revisions into :class:`~.duckdb_ast_store.DuckDBASTStore`:

* resolve explicit Git object identity (full commit + tree SHAs);
* apply an explicit dirty-tree policy (fail-closed by default);
* reuse unchanged source shards only under the same extraction context;
* invalidate changed/deleted files and the symbols/edges they own;
* publish each complete revision atomically (build fully, then commit).

Importing this module is inert — no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
    SourceProvenance,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTCatalogProjection,
    DuckDBASTStore,
    InvalidationRow,
    SymbolRow,
    build_duckdb_ast_store,
    classify_parse_status,
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


@dataclass(frozen=True, slots=True)
class SnapshotIngestIdentity:
    """Exact canonical snapshot identity, independent of Git availability."""

    snapshot: RepositorySnapshot

    @property
    def snapshot_cid(self) -> str:
        return self.snapshot.snapshot_cid

    @property
    def revision(self) -> str:
        return f"snapshot:{self.snapshot_cid}"

    def repository_id(self, *, label: str = "repository") -> str:
        return self.snapshot.repository_id

    def repository_tree_cid(self) -> str:
        return self.snapshot_cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "duckdb-ast-ingest/snapshot-identity@1",
            "snapshot_cid": self.snapshot_cid,
            "revision": self.revision,
            "snapshot": self.snapshot.to_dict(),
        }


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
    identity: GitObjectIdentity | SnapshotIngestIdentity
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
    """Rebind an already-parsed ASTRecord to new provenance at the same path.

    Structural facts (scopes, symbols, edges, frontend) are preserved.  Only
    :class:`SourceProvenance` changes, so the source CID stays identical and
    no parser is invoked.  The AST IR CID changes with the new provenance
    binding, matching the shared IR identity rules.
    """

    if type(record) is not ASTRecord:
        raise DuckDBIngestError("rebind_ast_record requires an exact ASTRecord")
    if _normalize_repo_path(path) != record.provenance.path:
        raise DuckDBIngestError("path changes require reparsing module and symbol names")
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
# Extraction-context shard cache (reuse without reparse)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceShardContext:
    """All non-source inputs to a qualified, provenance-independent parser."""

    language: str
    path: str
    module_name: str | None
    frontend_cid: str
    configuration_cid: str
    implementation_cid: str
    ast_schema: str

    @property
    def cid(self) -> str:
        return cid_for_structured({
            "schema": "duckdb-ast-ingest/source-shard-context@1",
            "language": self.language, "path": self.path,
            "module_name": self.module_name, "frontend_cid": self.frontend_cid,
            "configuration_cid": self.configuration_cid,
            "implementation_cid": self.implementation_cid, "ast_schema": self.ast_schema,
        })

    def verify(self, record: ASTRecord, source_cid: str) -> None:
        if (type(record) is not ASTRecord
                or record.provenance.source_cid != source_cid
                or record.provenance.path != self.path
                or record.frontend.cid != self.frontend_cid
                or record.schema_version.identifier != self.ast_schema
                or (self.module_name is not None and record.module.name != self.module_name)):
            raise DuckDBIngestError("cached AST does not match its source/extraction context")


@dataclass(frozen=True, slots=True)
class SnapshotPreparedMember:
    """One source-local extraction result, without publication authority."""

    source_key: str
    decision: FileIngestDecision
    projection: ASTCatalogProjection | None
    context: SourceShardContext | None

    def __post_init__(self) -> None:
        if type(self.source_key) is not str or not self.source_key.startswith("raw:"):
            raise DuckDBIngestError("prepared member requires an exact raw source key")
        if type(self.decision) is not FileIngestDecision:
            raise DuckDBIngestError("prepared member requires an exact ingest decision")
        if self.projection is not None and type(self.projection) is not ASTCatalogProjection:
            raise DuckDBIngestError("prepared member requires an exact AST projection")
        if self.context is not None and type(self.context) is not SourceShardContext:
            raise DuckDBIngestError("prepared member requires an exact source context")


SOURCE_SHARD_RESTART_SCHEMA: Final = "duckdb-ast-ingest/source-shard-restart-cache@1"
SOURCE_SHARD_RESTART_MAX_ENTRIES: Final = 4096
SOURCE_SHARD_RESTART_MAX_AST_BYTES: Final = 4 * 1024 * 1024
SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES: Final = 64 * 1024 * 1024
_SOURCE_SHARD_CONTEXT_FIELDS = frozenset({
    "language", "path", "module_name", "frontend_cid", "configuration_cid",
    "implementation_cid", "ast_schema",
})
_SOURCE_SHARD_CONTEXT_SCHEMA = "duckdb-ast-ingest/source-shard-context@1"
_SOURCE_SHARD_CONTEXT_MAX_BYTES = 64 * 1024
_SOURCE_SHARD_RESTART_ENTRY_FIELDS = frozenset({
    "source_cid", "context_cid", "context", "ast_cid", "ast_payload",
})


def _restart_cid(value: Any, codec: str) -> str:
    if type(value) is not str:
        raise DuckDBIngestError("restart cache CID must be an exact canonical " + codec + " CID")
    try:
        return validate_cid(value, codecs={codec})
    except (ValueError, TypeError) as error:
        raise DuckDBIngestError("restart cache CID must be an exact canonical " + codec + " CID") from error


def _restart_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuckDBIngestError("restart cache JSON contains a duplicate key")
        result[key] = value
    return result


def _restart_json_constant(value: str) -> None:
    raise DuckDBIngestError("restart cache JSON must be finite")


def _restart_json(raw: bytes) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_restart_json_pairs,
                          parse_constant=_restart_json_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if type(error) is DuckDBIngestError:
            raise
        raise DuckDBIngestError("restart cache requires finite UTF-8 JSON") from error


def _restart_canonical(value: Any) -> bytes:
    try:
        return canonical_dag_json_bytes(value)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise DuckDBIngestError("restart cache requires canonical native structured bytes") from error


def _source_shard_context_payload(context: SourceShardContext) -> dict[str, Any]:
    if type(context) is not SourceShardContext:
        raise DuckDBIngestError("cache requires an exact SourceShardContext")
    return {"schema": _SOURCE_SHARD_CONTEXT_SCHEMA,
            **{name: getattr(context, name) for name in _SOURCE_SHARD_CONTEXT_FIELDS}}


def _restart_context(value: Any) -> SourceShardContext:
    if (type(value) is not dict or set(value) != _SOURCE_SHARD_CONTEXT_FIELDS | {"schema"}
            or value["schema"] != _SOURCE_SHARD_CONTEXT_SCHEMA):
        raise DuckDBIngestError("restart cache context must have closed native fields")
    for name in ("language", "path", "ast_schema"):
        if (type(value[name]) is not str or not value[name]
                or value[name] != value[name].strip()):
            raise DuckDBIngestError("restart cache context text must be exact nonempty trimmed strings")
    if _normalize_repo_path(value["path"]) != value["path"]:
        raise DuckDBIngestError("restart cache context path must be canonical")
    if value["module_name"] is not None and (
            type(value["module_name"]) is not str or not value["module_name"]
            or value["module_name"] != value["module_name"].strip()):
        raise DuckDBIngestError("restart cache module name must be null or exact nonempty trimmed text")
    for name in ("frontend_cid", "configuration_cid", "implementation_cid"):
        _restart_cid(value[name], "dag-json")
    if len(_restart_canonical(value)) > _SOURCE_SHARD_CONTEXT_MAX_BYTES:
        raise DuckDBIngestError("restart cache context exceeds its byte bound")
    return SourceShardContext(**{name: value[name] for name in _SOURCE_SHARD_CONTEXT_FIELDS})


def _restart_entry(value: Any) -> tuple[tuple[str, str], tuple[str, bytes], bytes]:
    if type(value) is not dict or set(value) != _SOURCE_SHARD_RESTART_ENTRY_FIELDS:
        raise DuckDBIngestError("restart cache entry must have closed native fields")
    source_cid = _restart_cid(value["source_cid"], "raw")
    context_cid = _restart_cid(value["context_cid"], "dag-json")
    ast_cid = _restart_cid(value["ast_cid"], "dag-json")
    context = _restart_context(value["context"])
    context_raw = _restart_canonical(value["context"])
    if context.cid != context_cid:
        raise DuckDBIngestError("restart cache context CID does not verify")
    if type(value["ast_payload"]) is not dict:
        raise DuckDBIngestError("restart cache AST must be an exact native object")
    payload = _restart_canonical(value["ast_payload"])
    if not 0 < len(payload) <= SOURCE_SHARD_RESTART_MAX_AST_BYTES:
        raise DuckDBIngestError("restart cache AST exceeds its byte bound")
    try:
        record = ASTRecord.from_dict(value["ast_payload"])
        if record.cid != ast_cid or record.canonical_bytes != payload:
            raise DuckDBIngestError("restart cache AST CID or canonical payload does not verify")
        context.verify(record, source_cid)
        if record.frontend.language != context.language:
            raise DuckDBIngestError("restart cache AST language does not match its context")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        if type(error) is DuckDBIngestError:
            raise
        raise DuckDBIngestError("restart cache AST is not a verified native record") from error
    return (source_cid, context_cid), (ast_cid, payload), context_raw


def _restart_bundle_bytes(entries: dict, contexts: dict) -> bytes:
    if type(entries) is not dict or type(contexts) is not dict:
        raise DuckDBIngestError("restart cache requires exact private entry and context dictionaries")
    if len(entries) > SOURCE_SHARD_RESTART_MAX_ENTRIES:
        raise DuckDBIngestError("restart cache entry count exceeds its bound")
    if set(entries) != set(contexts):
        raise DuckDBIngestError("restart cache context inventory differs from its entries")
    # Bound retained input bytes before decoding/collecting every entry. Existing
    # warm caches remain usable above these export-only profile bounds.
    retained = 0
    for key, saved in entries.items():
        if (type(key) is not tuple or len(key) != 2
                or type(saved) is not tuple or len(saved) != 2
                or type(saved[1]) is not bytes or type(contexts[key]) is not bytes):
            raise DuckDBIngestError("restart cache private entry layout differs")
        if not 0 < len(saved[1]) <= SOURCE_SHARD_RESTART_MAX_AST_BYTES:
            raise DuckDBIngestError("restart cache AST exceeds its byte bound")
        if not 0 < len(contexts[key]) <= _SOURCE_SHARD_CONTEXT_MAX_BYTES:
            raise DuckDBIngestError("restart cache context exceeds its byte bound")
        retained += len(saved[1]) + len(contexts[key])
        if retained > SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES:
            raise DuckDBIngestError("restart cache aggregate entry bytes exceed the bundle bound")
        _restart_cid(key[0], "raw")
        _restart_cid(key[1], "dag-json")
    values = []
    total = len(_restart_canonical({"schema": SOURCE_SHARD_RESTART_SCHEMA, "entries": []}))
    for key in sorted(entries):
        ast_cid, payload = entries[key]
        context_raw = contexts[key]
        value = {"source_cid": key[0], "context_cid": key[1],
                 "context": _restart_json(context_raw), "ast_cid": ast_cid,
                 "ast_payload": _restart_json(payload)}
        verified_key, verified_saved, verified_context = _restart_entry(value)
        if verified_key != key or verified_saved != entries[key] or verified_context != context_raw:
            raise DuckDBIngestError("restart cache private payload is not canonical")
        row_bytes = _restart_canonical(value)
        total += len(row_bytes) + bool(values)
        if total > SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES:
            raise DuckDBIngestError("restart cache serialized bundle exceeds its byte bound")
        values.append(value)
    raw = _restart_canonical({"schema": SOURCE_SHARD_RESTART_SCHEMA, "entries": values})
    if len(raw) != total or len(raw) > SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES:
        raise DuckDBIngestError("restart cache serialized bundle exceeds its byte bound")
    return raw


SNAPSHOT_RESTART_PUBLICATION_SCHEMA: Final = "duckdb-ast-ingest/snapshot-restart-publication@1"
SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES: Final = 4096
SNAPSHOT_RESTART_PUBLICATION_MAX_AST_BYTES: Final = 4 * 1024 * 1024
SNAPSHOT_RESTART_PUBLICATION_MAX_MANIFEST_BYTES: Final = 16 * 1024 * 1024
SNAPSHOT_RESTART_PUBLICATION_MAX_BUNDLE_BYTES: Final = 64 * 1024 * 1024
SNAPSHOT_RESTART_PUBLICATION_MAX_INVALIDATIONS: Final = 8192
_PUBLICATION_RESTART_FIELDS = frozenset({
    "schema", "languages", "context_inventory", "publication", "projections", "invalidations",
})
_PUBLICATION_RESTART_PROJECTION_FIELDS = frozenset({
    "path", "source_cid", "ast_cid", "ast_payload", "created_at_hex", "invalidations",
})
_PUBLICATION_RESTART_CONTEXT_FIELDS = frozenset({
    "path", "source_cid", "language", "state", "context",
})
_PUBLICATION_RESTART_INVALIDATION_FIELDS = frozenset({
    "invalidation_id", "blob_id", "file_id", "revision_id", "reason", "actor_id",
    "detail", "created_at_hex",
})


def _publication_timestamp_hex(value: Any) -> str:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise DuckDBIngestError("restart publication timestamps must be finite native numbers")
    return float(value).hex()


def _publication_timestamp(value: Any) -> float:
    if type(value) is not str:
        raise DuckDBIngestError("restart publication timestamps must be canonical hexadecimal strings")
    try:
        result = float.fromhex(value)
    except (ValueError, OverflowError) as error:
        raise DuckDBIngestError("restart publication timestamp does not verify") from error
    if not math.isfinite(result) or result.hex() != value:
        raise DuckDBIngestError("restart publication timestamp does not verify")
    return result


def _publication_metadata(publication: RevisionPublication) -> dict[str, Any]:
    value = publication.to_dict()
    value["created_at_hex"] = _publication_timestamp_hex(value.pop("created_at"))
    return value


def _publication_invalidation_payload(row: InvalidationRow) -> dict[str, Any]:
    if type(row) is not InvalidationRow:
        raise DuckDBIngestError("restart publication invalidations must be exact native rows")
    value = row.to_dict()
    value["created_at_hex"] = _publication_timestamp_hex(value.pop("created_at"))
    return value


def _publication_invalidations(values: Any) -> tuple[InvalidationRow, ...]:
    if type(values) is not list or len(values) > SNAPSHOT_RESTART_PUBLICATION_MAX_INVALIDATIONS:
        raise DuckDBIngestError("restart publication invalidation inventory exceeds its bound")
    result = []
    for value in values:
        if type(value) is not dict or set(value) != _PUBLICATION_RESTART_INVALIDATION_FIELDS:
            raise DuckDBIngestError("restart publication invalidations require closed native fields")
        for name in ("invalidation_id", "reason", "actor_id"):
            if type(value[name]) is not str or not value[name] or value[name] != value[name].strip():
                raise DuckDBIngestError("restart publication invalidation identity must be exact trimmed text")
        for name in ("blob_id", "file_id", "revision_id"):
            if value[name] is not None and (type(value[name]) is not str or not value[name]
                                           or value[name] != value[name].strip()):
                raise DuckDBIngestError("restart publication invalidation selectors must be null or trimmed text")
        if type(value["detail"]) is not str:
            raise DuckDBIngestError("restart publication invalidation detail must be exact text")
        row = InvalidationRow(**{name: item for name, item in value.items() if name != "created_at_hex"},
                              created_at=_publication_timestamp(value["created_at_hex"]))
        if _publication_invalidation_payload(row) != value:
            raise DuckDBIngestError("restart publication invalidation does not round-trip")
        result.append(row)
    if len({row.invalidation_id for row in result}) != len(result):
        raise DuckDBIngestError("restart publication invalidation identities must be distinct")
    return tuple(result)


def _publication_restart_inventory(value: Any, snapshot: RepositorySnapshot) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) != len(snapshot.entries):
        raise DuckDBIngestError("restart publication context inventory must cover the complete snapshot")
    entries = {entry.path: entry for entry in snapshot.entries}
    if [item.get("path") if type(item) is dict else None for item in value] != sorted(entries):
        raise DuckDBIngestError("restart publication contexts require distinct sorted snapshot paths")
    for item in value:
        if type(item) is not dict or set(item) != _PUBLICATION_RESTART_CONTEXT_FIELDS:
            raise DuckDBIngestError("restart publication context inventory requires closed native fields")
        entry = entries[item["path"]]
        if item["source_cid"] != entry.source_cid or item["language"] != _language_for_path(entry.path):
            raise DuckDBIngestError("restart publication context inventory differs from its snapshot")
        state = item["state"]
        if entry.is_opaque:
            if state != "opaque" or item["context"] is not None:
                raise DuckDBIngestError("restart publication opaque inventory differs")
        elif state == "qualified":
            context = _restart_context(item["context"])
            if context.path != entry.path or context.language != item["language"]:
                raise DuckDBIngestError("restart publication parser context differs from its path")
        elif state != "skipped" or item["context"] is not None:
            raise DuckDBIngestError("restart publication context state is unsupported")
    return value


def _decode_restart_publication(raw: bytes, *, expected_cid: str) -> tuple[RevisionPublication, tuple[str, ...], list[dict[str, Any]]]:
    """Stage a complete snapshot publication without adopting ingestor state."""
    expected_cid = _restart_cid(expected_cid, "raw")
    if type(raw) is not bytes or not 0 < len(raw) <= SNAPSHOT_RESTART_PUBLICATION_MAX_BUNDLE_BYTES:
        raise DuckDBIngestError("restart publication bundle exceeds its byte bound")
    if cid_for_bytes(raw) != expected_cid:
        raise DuckDBIngestError("restart publication bytes differ from the externally admitted CID")
    value = _restart_json(raw)
    if (type(value) is not dict or set(value) != _PUBLICATION_RESTART_FIELDS
            or value["schema"] != SNAPSHOT_RESTART_PUBLICATION_SCHEMA or _restart_canonical(value) != raw):
        raise DuckDBIngestError("restart publication requires its closed canonical schema")
    languages = value["languages"]
    if (type(languages) is not list or len(languages) > SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES
            or any(type(item) is not str or not item or item != item.strip() for item in languages)
            or languages != sorted(set(languages))):
        raise DuckDBIngestError("restart publication languages must be distinct sorted native text")
    metadata = value["publication"]
    if type(metadata) is not dict or type(metadata.get("identity")) is not dict:
        raise DuckDBIngestError("restart publication metadata must be an exact snapshot object")
    identity_value = metadata["identity"]
    if set(identity_value) != {"schema", "snapshot_cid", "revision", "snapshot"} or identity_value["schema"] != "duckdb-ast-ingest/snapshot-identity@1":
        raise DuckDBIngestError("restart publication only admits snapshot identities")
    if type(identity_value["snapshot"]) is not dict or len(_restart_canonical(identity_value["snapshot"])) > SNAPSHOT_RESTART_PUBLICATION_MAX_MANIFEST_BYTES:
        raise DuckDBIngestError("restart publication snapshot manifest exceeds its byte bound")
    try:
        snapshot = RepositorySnapshot.from_dict(identity_value["snapshot"])
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise DuckDBIngestError("restart publication snapshot manifest does not verify") from error
    if len(snapshot.entries) > SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES:
        raise DuckDBIngestError("restart publication snapshot inventory exceeds its entry bound")
    identity = SnapshotIngestIdentity(snapshot)
    if identity.to_dict() != identity_value:
        raise DuckDBIngestError("restart publication snapshot identity does not round-trip")
    inventory = _publication_restart_inventory(value["context_inventory"], snapshot)
    context_by_path = {item["path"]: item for item in inventory}
    projection_values = value["projections"]
    if type(projection_values) is not list or len(projection_values) > SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES:
        raise DuckDBIngestError("restart publication projection inventory exceeds its entry bound")
    projections = []
    for item in projection_values:
        if type(item) is not dict or set(item) != _PUBLICATION_RESTART_PROJECTION_FIELDS:
            raise DuckDBIngestError("restart publication projection requires closed native fields")
        if type(item["path"]) is not str or item["path"] not in context_by_path:
            raise DuckDBIngestError("restart publication AST path is outside its snapshot")
        context_entry = context_by_path[item["path"]]
        if context_entry["state"] != "qualified" or context_entry["source_cid"] != item["source_cid"]:
            raise DuckDBIngestError("restart publication AST lacks its qualified source context")
        context = _restart_context(context_entry["context"])
        if type(item["ast_payload"]) is not dict:
            raise DuckDBIngestError("restart publication AST body must be a native object")
        payload = _restart_canonical(item["ast_payload"])
        if not 0 < len(payload) <= SNAPSHOT_RESTART_PUBLICATION_MAX_AST_BYTES:
            raise DuckDBIngestError("restart publication AST exceeds its byte bound")
        try:
            record = ASTRecord.from_dict(item["ast_payload"])
            context.verify(record, _restart_cid(item["source_cid"], "raw"))
            if (record.cid != _restart_cid(item["ast_cid"], "dag-json") or record.canonical_bytes != payload
                    or record.frontend.language != context.language
                    or record.provenance != SourceProvenance(source_cid=item["source_cid"], path=item["path"],
                        repository_id=snapshot.repository_id, revision=identity.revision,
                        repository_tree_cid=identity.snapshot_cid)):
                raise DuckDBIngestError("restart publication AST source or revision provenance does not verify")
            projection = project_ast_record(record, created_at=_publication_timestamp(item["created_at_hex"]))
            projection = replace(projection, invalidations=_publication_invalidations(item["invalidations"]))
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            if type(error) is DuckDBIngestError:
                raise
            raise DuckDBIngestError("restart publication AST is not a verified native record") from error
        projections.append(projection)
    qualified_paths = sorted(item["path"] for item in inventory if item["state"] == "qualified")
    if [row.source_file.path for row in projections] != qualified_paths:
        raise DuckDBIngestError("restart publication AST inventory must exactly cover qualified paths")
    invalidations = _publication_invalidations(value["invalidations"])
    if len(invalidations) + sum(len(row.invalidations) for row in projections) > SNAPSHOT_RESTART_PUBLICATION_MAX_INVALIDATIONS:
        raise DuckDBIngestError("restart publication aggregate invalidation inventory exceeds its bound")
    decision_values = metadata.get("decisions")
    if type(decision_values) is not list or len(decision_values) != len(snapshot.entries):
        raise DuckDBIngestError("restart publication decisions must cover the complete snapshot")
    decisions = []
    decision_fields = set(FileIngestDecision("x", "", "", "skipped", "").to_dict())
    projection_by_path = {row.source_file.path: row for row in projections}
    entries = {entry.path: entry for entry in snapshot.entries}
    for item in decision_values:
        if type(item) is not dict or set(item) != decision_fields:
            raise DuckDBIngestError("restart publication decisions require closed native fields")
        if type(item["path"]) is not str or item["path"] not in entries:
            raise DuckDBIngestError("restart publication decision path is outside its snapshot")
        for name in ("source_cid", "language", "action", "git_oid", "detail"):
            if type(item[name]) is not str:
                raise DuckDBIngestError("restart publication decision text must be exact native text")
        entry = entries[item["path"]]
        context_entry = context_by_path[item["path"]]
        if (item["source_cid"] != (entry.source_cid or "") or item["language"] != context_entry["language"]
                or item["git_oid"] != ((entry.git_blob_oid or "") if entry.is_opaque else "")):
            raise DuckDBIngestError("restart publication decisions differ from their snapshot")
        projection = projection_by_path.get(item["path"])
        if projection is None:
            expected_detail = entry.opaque_reason if entry.is_opaque else "no_frontend_for_language:" + item["language"]
            if (item["action"] != "skipped" or item["blob_id"] is not None or item["ast_cid"] is not None
                    or item["parse_count"] != 0 or item["detail"] != expected_detail):
                raise DuckDBIngestError("restart publication skipped decision does not verify")
        elif (item["blob_id"] != projection.blob_id or item["ast_cid"] != projection.ast_cid
                or item["action"] not in {"parsed", "reused", "parse_failed"}
                or (item["action"] != "reused" and
                    (classify_parse_status(ASTRecord.from_json(projection.ast_blob.payload_json)) == "failed") != (item["action"] == "parse_failed"))
                or item["parse_count"] != (1 if item["action"] == "parsed" else 0)
                or item["detail"] != ("parse_failed" if item["action"] == "parse_failed" else "")):
            raise DuckDBIngestError("restart publication AST decision does not verify")
        decisions.append(FileIngestDecision(**item))
    if len({item.path for item in decisions}) != len(decisions):
        raise DuckDBIngestError("restart publication decision paths must be distinct")
    stats_value = metadata.get("stats")
    stats_fields = set(RevisionIngestStats().to_dict())
    if (type(stats_value) is not dict or set(stats_value) != stats_fields
            or any(type(item) is not int or item < 0 for item in stats_value.values())):
        raise DuckDBIngestError("restart publication statistics require closed nonnegative native counters")
    stats = RevisionIngestStats(**{name: item for name, item in stats_value.items() if name != "parse_invocations"})
    counts = {action: sum(item.action == action for item in decisions) for action in INGEST_ACTIONS}
    if (stats.to_dict() != stats_value or stats.scanned_path_count != len(snapshot.entries)
            or stats.parseable_path_count != len(projections) or stats.published_file_count != len(projections)
            or stats.parsed_count != counts["parsed"] or stats.reused_count != counts["reused"]
            or stats.skipped_count != counts["skipped"] or stats.parse_failed_count != counts["parse_failed"]
            or stats.invalidated_count != len(invalidations)):
        raise DuckDBIngestError("restart publication statistics differ from the complete publication")
    publication = RevisionPublication(
        revision_id=_revision_id(snapshot.repository_id, identity.revision), repository_id=snapshot.repository_id,
        revision=identity.revision, identity=identity, repository_tree_cid=identity.snapshot_cid,
        projections=tuple(projections), decisions=tuple(decisions), invalidations=invalidations,
        stats=stats, dirty_tree_policy="captured_snapshot", published=True,
        created_at=_publication_timestamp(metadata.get("created_at_hex")),
    )
    if _publication_metadata(publication) != metadata:
        raise DuckDBIngestError("restart publication metadata does not completely round-trip")
    return publication, tuple(languages), inventory


@dataclass
class SourceShardCache:
    """Verified AST bytes keyed by source and complete extraction context.

    Legacy source-only calls remain callable but cannot produce cache hits.
    Revision rebinding is allowed only for a parser whose context is qualified
    independently of repository provenance. Custom frontends are reparsed.
    """

    _entries: dict[tuple[str, str], tuple[str, bytes]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    _contexts: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def get(self, source_cid: str, *, context: SourceShardContext | None = None) -> ASTRecord | None:
        if context is not None and type(context) is not SourceShardContext:
            raise DuckDBIngestError("cache requires an exact SourceShardContext")
        found = None if context is None else self._entries.get((source_cid, context.cid))
        if found is None:
            self.misses += 1
            return None
        expected_cid, payload = found
        record = ASTRecord.from_dict(json.loads(payload))
        if record.cid != expected_cid:
            raise DuckDBIngestError("cached AST payload identity does not verify")
        context.verify(record, source_cid)
        self.hits += 1
        return record

    def put(self, record: ASTRecord, *, context: SourceShardContext | None = None) -> None:
        if type(record) is not ASTRecord:
            raise DuckDBIngestError("cache requires an exact ASTRecord")
        if context is not None:
            if type(context) is not SourceShardContext:
                raise DuckDBIngestError("cache requires an exact SourceShardContext")
            context.verify(record, record.provenance.source_cid)
            key = (record.provenance.source_cid, context.cid)
            saved = (record.cid, record.canonical_bytes)
            context_raw = _restart_canonical(_source_shard_context_payload(context))
            self._entries[key] = saved
            self._contexts[key] = context_raw

    def export_bundle(self) -> bytes:
        """Export bounded complete parser bytes; caller retains the raw CID.

        This carries historical qualified parser shards only. It establishes no
        active publication, catalog head, source freshness or proof authority.
        The owning ingestor serializes access; no whole-store hydration occurs.
        """
        return _restart_bundle_bytes(self._entries, self._contexts)

    def hydrate_bundle(self, raw: bytes, *, expected_cid: str) -> None:
        """Adopt only a fully verified externally anchored immutable bundle.

        The expected raw CID must arrive through the trusted owner's separate
        admission channel. Computing it from received database bytes supplies
        no independent anchor. Every entry validates before any cache changes.
        Subsequent native ingestion still hashes fresh source bytes and obtains
        the current exact parser context before consulting these historical keys.
        """
        if type(raw) is not bytes or not 0 < len(raw) <= SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES:
            raise DuckDBIngestError("restart cache bundle must be exact bounded bytes")
        _restart_cid(expected_cid, "raw")
        if cid_for_bytes(raw) != expected_cid:
            raise DuckDBIngestError("restart cache bundle raw CID does not verify")
        value = _restart_json(raw)
        if (type(value) is not dict or set(value) != {"schema", "entries"}
                or value["schema"] != SOURCE_SHARD_RESTART_SCHEMA
                or type(value["entries"]) is not list):
            raise DuckDBIngestError("restart cache bundle must have closed native fields")
        if len(value["entries"]) > SOURCE_SHARD_RESTART_MAX_ENTRIES:
            raise DuckDBIngestError("restart cache entry count exceeds its bound")
        if _restart_canonical(value) != raw:
            raise DuckDBIngestError("restart cache bundle bytes must be canonical")
        staged_entries, staged_contexts = {}, {}
        previous = None
        for member in value["entries"]:
            key, saved, context_raw = _restart_entry(member)
            if previous is not None and key <= previous:
                raise DuckDBIngestError("restart cache entry keys must be sorted and unique")
            previous = key
            staged_entries[key] = saved
            staged_contexts[key] = context_raw
        if type(self._entries) is not dict or type(self._contexts) is not dict:
            raise DuckDBIngestError("restart cache requires exact private entry and context dictionaries")
        if (len(self._entries) > SOURCE_SHARD_RESTART_MAX_ENTRIES
                or len(self._contexts) > SOURCE_SHARD_RESTART_MAX_ENTRIES):
            raise DuckDBIngestError("restart cache entry count exceeds its bound")
        if len(set(self._entries) | set(staged_entries)) > SOURCE_SHARD_RESTART_MAX_ENTRIES:
            raise DuckDBIngestError("restart cache entry count exceeds its bound")
        entries, contexts = dict(self._entries), dict(self._contexts)
        for key, saved in staged_entries.items():
            if key in entries and (entries[key] != saved or contexts.get(key) != staged_contexts[key]):
                raise DuckDBIngestError("restart cache conflicts with an existing contextual entry")
            entries[key] = saved
            contexts[key] = staged_contexts[key]
        # Recheck the complete merged inventory and all aggregate limits before
        # adoption. Neither malformed tails nor capacity refusals mutate state.
        _restart_bundle_bytes(entries, contexts)
        self._entries, self._contexts = entries, contexts

    def __contains__(self, source_cid: object) -> bool:
        return any(key[0] == source_cid for key in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._contexts.clear()
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


def _frontend_cache_context(frontend: ASTFrontendProtocol, *, language: str, path: str) -> SourceShardContext | None:
    """Qualify the native Python parser's complete extraction inputs.

    Arbitrary protocol implementations may depend on revision, external state
    or undeclared options. They remain usable, but are never cached by guessing
    their configuration from a name or capability declaration. External-worker
    frontends likewise require a separately qualified toolchain cache profile.
    """
    while type(frontend) is CountingFrontend:
        frontend = frontend._frontend
    if type(frontend) is not PythonASTExtractor or language != "python":
        return None
    expected_options = {"feature_version", "max_source_bytes", "max_ast_nodes", "max_ast_depth"}
    if set(vars(frontend)) != expected_options:
        return None
    from . import ast_ir, python_frontend, schema_versions

    capability = frontend.capability
    return SourceShardContext(
        language=language, path=path, module_name=None,
        frontend_cid=capability.cid,
        configuration_cid=cid_for_structured({
            key: list(value) if isinstance(value, tuple) else value
            for key, value in vars(frontend).items()
        }),
        implementation_cid=cid_for_structured({
            module.__name__: cid_for_bytes(Path(module.__file__).read_bytes())
            for module in (ast_ir, python_frontend, schema_versions)
        }),
        ast_schema=capability.ast_schema.identifier,
    )


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
    4. For each path: reuse the exact qualified extraction context or parse once.
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
        optimized_decision_lookup: bool = True,
        optimized_restart_cache: bool = True,
        restart_cache_cid: str | None = None,
        optimized_restart_publication: bool = True,
        restart_publication_cid: str | None = None,
    ) -> None:
        if type(optimized_decision_lookup) is not bool:
            raise DuckDBIngestError("optimized_decision_lookup must be an exact boolean")
        if type(optimized_restart_cache) is not bool:
            raise DuckDBIngestError("optimized_restart_cache must be an exact boolean")
        if type(optimized_restart_publication) is not bool:
            raise DuckDBIngestError("optimized_restart_publication must be an exact boolean")
        if restart_cache_cid is not None:
            _restart_cid(restart_cache_cid, "raw")
        if restart_publication_cid is not None:
            _restart_cid(restart_publication_cid, "raw")
        self._optimized_restart_cache = optimized_restart_cache
        self._restart_cache_cid = restart_cache_cid
        self._optimized_restart_publication = optimized_restart_publication
        self._restart_publication_cid = restart_publication_cid
        self._optimized_decision_lookup = optimized_decision_lookup
        self._store = store if store is not None else build_duckdb_ast_store()
        self._lock = threading.RLock()
        self._shard_cache = SourceShardCache()
        self._publications: dict[str, RevisionPublication] = {}
        self._latest_by_label: dict[str, str] = {}
        self._publication_restart_contexts: dict[str, tuple[tuple[str, ...], list[dict[str, Any]]]] = {}
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
        if restart_cache_cid is not None and optimized_restart_cache:
            with self._lock:
                payload = self._store.get_source_shard_cache(restart_cache_cid)
                if payload is None:
                    raise DuckDBIngestError("admitted restart cache bundle is missing from its owner")
                self._shard_cache.hydrate_bundle(payload, expected_cid=restart_cache_cid)
        if restart_publication_cid is not None and optimized_restart_publication:
            with self._lock:
                payload = self._store.get_source_shard_cache(restart_publication_cid)
                if payload is None:
                    raise DuckDBIngestError("admitted restart publication bundle is missing from its owner")
                publication, languages, inventory = _decode_restart_publication(payload, expected_cid=restart_publication_cid)
                current_inventory = self._publication_context_inventory(publication.identity.snapshot)
                # Context mismatches are misses, matching a fresh opt-out
                # ingestor. They do not silently bind a historical revision to
                # different parser options or an unqualified custom frontend.
                if languages == tuple(sorted(self._languages)) and current_inventory == inventory:
                    if not self._validate_active_publication(publication):
                        raise DuckDBIngestError("admitted restart publication has different active store membership")
                    if current_inventory != self._publication_context_inventory(publication.identity.snapshot):
                        raise DuckDBIngestError("restart publication extraction context changed during admission")
                    self._publications = {publication.revision_id: publication}
                    self._latest_by_label = {self._publication_chain(publication.identity): publication.revision_id}
                    self._publication_restart_contexts = {publication.revision_id: (languages, inventory)}

    def export_restart_cache(self) -> str:
        """Persist an opaque immutable bundle and return its independently retained CID.

        The caller must retain and later admit this CID separately from database
        rows. Export never selects a current source/catalog head or publishes an
        AST revision; cancellation can leave only an unreferenced cache bundle.
        """
        with self._lock:
            raw = self._shard_cache.export_bundle()
            expected = cid_for_bytes(raw)
            stored = self._store.put_source_shard_cache(raw)
            if _restart_cid(stored, "raw") != expected:
                raise DuckDBIngestError("restart cache owner returned a different bundle CID")
            return stored

    def export_restart_publication(self, revision_id: str) -> str:
        """Persist one explicitly selected, current, owner-admitted snapshot.

        Its RAW CID must be retained independently of database rows. The bundle
        admits a historical complete publication, not global source freshness,
        a supervisor head, proof authority, or an executable worker instruction.
        Explicit publication opt-out skips this publication-state I/O.
        """
        if not self._optimized_restart_publication:
            raise DuckDBIngestError("restart publication export is disabled")
        if type(revision_id) is not str or not revision_id:
            raise DuckDBIngestError("restart publication export requires an explicit native revision ID")
        with self._lock:
            publication = self._publications.get(revision_id)
            if (publication is None or not publication.published or type(publication.identity) is not SnapshotIngestIdentity
                    or self._latest_by_label.get(self._publication_chain(publication.identity)) != revision_id):
                raise DuckDBIngestError("restart publication export requires the explicitly selected current snapshot")
            saved = self._publication_restart_contexts.get(revision_id)
            inventory = self._publication_context_inventory(publication.identity.snapshot)
            if saved is None or saved != (tuple(sorted(self._languages)), inventory):
                raise DuckDBIngestError("restart publication export requires exact qualified current contexts")
            if not self._validate_active_publication(publication):
                raise DuckDBIngestError("restart publication export has different active store membership")
            snapshot = publication.identity.snapshot
            if len(snapshot.entries) > SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES or len(_restart_canonical(snapshot.to_dict())) > SNAPSHOT_RESTART_PUBLICATION_MAX_MANIFEST_BYTES:
                raise DuckDBIngestError("restart publication snapshot exceeds its export bounds")
            if (len(publication.projections) > SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES
                    or len(publication.invalidations) + sum(len(row.invalidations) for row in publication.projections)
                    > SNAPSHOT_RESTART_PUBLICATION_MAX_INVALIDATIONS):
                raise DuckDBIngestError("restart publication projection or invalidation inventory exceeds its export bounds")
            value = {"schema": SNAPSHOT_RESTART_PUBLICATION_SCHEMA,
                "languages": list(saved[0]), "context_inventory": saved[1],
                "publication": _publication_metadata(publication), "projections": [],
                "invalidations": [_publication_invalidation_payload(row) for row in publication.invalidations]}
            serialized_bytes = len(_restart_canonical(value))
            if serialized_bytes > SNAPSHOT_RESTART_PUBLICATION_MAX_BUNDLE_BYTES:
                raise DuckDBIngestError("restart publication metadata exceeds its export byte bound")
            projections = []
            total_ast_bytes = 0
            for projection in publication.projections:
                record = ASTRecord.from_json(projection.ast_blob.payload_json)
                payload = record.canonical_bytes
                if not 0 < len(payload) <= SNAPSHOT_RESTART_PUBLICATION_MAX_AST_BYTES:
                    raise DuckDBIngestError("restart publication AST exceeds its export byte bound")
                total_ast_bytes += len(payload)
                if total_ast_bytes > SNAPSHOT_RESTART_PUBLICATION_MAX_BUNDLE_BYTES:
                    raise DuckDBIngestError("restart publication AST aggregate exceeds its export byte bound")
                item = {"path": projection.source_file.path, "source_cid": projection.source_cid,
                    "ast_cid": projection.ast_cid, "ast_payload": record.to_dict(),
                    "created_at_hex": _publication_timestamp_hex(projection.ast_blob.created_at),
                    "invalidations": [_publication_invalidation_payload(row) for row in projection.invalidations]}
                serialized_bytes += len(_restart_canonical(item)) + bool(projections)
                if serialized_bytes > SNAPSHOT_RESTART_PUBLICATION_MAX_BUNDLE_BYTES:
                    raise DuckDBIngestError("restart publication serialized bundle exceeds its export byte bound")
                projections.append(item)
            value["projections"] = projections
            raw = _restart_canonical(value)
            if len(raw) != serialized_bytes:
                raise DuckDBIngestError("restart publication serialized bundle size does not verify")
            expected = cid_for_bytes(raw)
            staged, languages, staged_inventory = _decode_restart_publication(raw, expected_cid=expected)
            if staged != publication or (languages, staged_inventory) != saved:
                raise DuckDBIngestError("restart publication export does not completely round-trip")
            if saved != (tuple(sorted(self._languages)), self._publication_context_inventory(snapshot)):
                raise DuckDBIngestError("restart publication extraction context changed during export")
            stored = self._store.put_source_shard_cache(raw)
            if _restart_cid(stored, "raw") != expected:
                raise DuckDBIngestError("restart publication owner returned a different bundle CID")
            return stored

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
        with self._lock:
            return self._ingest_sources(
                sources=sources, identity=identity, blobs=blobs,
                dirty_tree_policy=policy.value, created_at=created_at,
                repository_id=repository_id,
            )

    def ingest_snapshot(
        self,
        snapshot: RepositorySnapshot,
        *,
        created_at: float | None = None,
        checkpoint: Callable[[], None] | None = None,
        before_publish: Callable[[RevisionPublication], None] | None = None,
        publish_batch: Callable[[RevisionPublication], None] | None = None,
    ) -> RevisionPublication:
        """Publish exact captured bytes for clean, dirty, unborn or filesystem views.

        A deserialized manifest without its captured bytes cannot be ingested.
        ``publish_batch`` is a trusted owner integration: it replaces the default
        store mutation and must atomically commit the complete projection batch.
        It also runs for an idempotent cached publication, so the owner can check
        its durable operation and expected head. It must raise on failure.
        No current checkout bytes or Git commands are consulted. Opaque entries
        remain explicit skipped decisions and part of the snapshot root.
        ``before_publish`` may seal referenced immutable artifacts before SQL
        publication. Failure leaves the previous catalog view active. The
        callback receives a complete unpublished plan, or an existing active
        publication on an idempotent retry.
        """
        if type(snapshot) is not RepositorySnapshot:
            raise DuckDBIngestError("ingest_snapshot requires an exact RepositorySnapshot")
        # Replay the closed manifest contract independently of ephemeral bytes.
        verified = RepositorySnapshot.from_dict(snapshot.to_dict())
        sources: dict[str, bytes] = {}
        skipped: list[FileIngestDecision] = []
        for entry in snapshot.entries:
            if checkpoint is not None:
                checkpoint()
            if entry.is_opaque:
                skipped.append(FileIngestDecision(
                    path=entry.path, source_cid=entry.source_cid or "",
                    language=_language_for_path(entry.path), action=IngestAction.SKIPPED.value,
                    git_oid=entry.git_blob_oid or "", detail=entry.opaque_reason or "opaque",
                ))
                continue
            data = entry.captured_bytes
            if (type(data) is not bytes or cid_for_bytes(data) != entry.source_cid
                    or entry.size_bytes != len(data) or len(data) > snapshot.max_file_bytes):
                raise DuckDBIngestError(f"snapshot captured bytes do not verify: {entry.path}")
            if _normalize_repo_path(entry.path) != entry.path:
                raise DuckDBIngestError(f"snapshot path cannot be represented by AST provenance: {entry.path}")
            sources[entry.path] = data
        identity = SnapshotIngestIdentity(verified)
        with self._lock:
            revision_id = _revision_id(identity.snapshot.repository_id, identity.revision)
            existing = self._publications.get(revision_id)
            saved = self._publication_restart_contexts.get(revision_id)
            if (self._optimized_restart_publication and existing is not None and existing.published
                    and self._latest_by_label.get(self._publication_chain(identity)) == revision_id
                    and saved is not None and existing.identity.to_dict() == identity.to_dict()
                    and saved == (tuple(sorted(self._languages)), self._publication_context_inventory(verified))):
                # All captured bytes and the complete snapshot inventory above
                # have verified. Repeat phase-one cancellation points before
                # using the admitted publication without parsing/rebinding or
                # projecting it again. The store validates every native family
                # and exact active revision membership in its own transaction.
                if checkpoint is not None:
                    for _path in sorted(sources):
                        checkpoint()
                    checkpoint()
                if self._validate_active_publication(existing, checkpoint=checkpoint):
                    if saved != (tuple(sorted(self._languages)), self._publication_context_inventory(verified)):
                        raise DuckDBIngestError("restart publication extraction context changed during reuse")
                    if before_publish is not None:
                        before_publish(existing)
                    if checkpoint is not None:
                        checkpoint()
                    if publish_batch is not None:
                        publish_batch(existing)
                    # Durable shard reuse can be off. Repeating an admitted publication
                    # is still one cache hit and must not parse again.
                    self._shard_cache.hits += 1
                    return existing
                # Invalidated or replaced rows are not a reusable publication.
                # Fall through and republish the verified snapshot.
            return self._ingest_sources(
                sources=sources, identity=identity, dirty_tree_policy="captured_snapshot",
                created_at=created_at, skipped_decisions=skipped, checkpoint=checkpoint,
                before_publish=before_publish, publish_batch=publish_batch,
            )

    def prepare_snapshot_subset(
        self,
        snapshot: RepositorySnapshot,
        source_bytes: dict[str, bytes],
        *,
        start_index: int,
        end_index: int,
        created_at: float,
        checkpoint: Callable[[], None] | None = None,
    ) -> tuple[SnapshotPreparedMember, ...]:
        """Extract at most 64 exact snapshot members without publishing them.

        Bytes are keyed by the selected nonopaque members' raw source keys.
        Provenance binds the complete original snapshot, including members
        outside this interval. Parser shards and parser invocation counters may
        change; store rows, publications, heads and publication stats do not.
        Unqualified custom frontends remain fresh-parse eligible and return a
        null context, which is insufficient for durable contextual reuse.
        """
        if type(snapshot) is not RepositorySnapshot:
            raise DuckDBIngestError("preparation requires an exact RepositorySnapshot")
        if (type(start_index) is not int or type(end_index) is not int
                or not 0 <= start_index <= end_index <= len(snapshot.entries)
                or end_index - start_index > 64):
            raise DuckDBIngestError("preparation requires a bounded contiguous snapshot interval")
        if type(created_at) not in (int, float):
            raise DuckDBIngestError("preparation clock must be an exact finite native number")
        try:
            now = float(created_at)
        except (ValueError, OverflowError) as error:
            raise DuckDBIngestError("preparation clock must be finite") from error
        if not math.isfinite(now):
            raise DuckDBIngestError("preparation clock must be finite")
        if checkpoint is not None and not callable(checkpoint):
            raise DuckDBIngestError("preparation checkpoint must be callable")
        try:
            manifest = snapshot.to_dict()
            raw_manifest = canonical_dag_json_bytes(manifest)
            if len(raw_manifest) > 4 * 1024 * 1024:
                raise DuckDBIngestError("preparation snapshot manifest exceeds its byte bound")
            verified = RepositorySnapshot.from_dict(json.loads(raw_manifest))
            if canonical_dag_json_bytes(verified.to_dict()) != raw_manifest:
                raise DuckDBIngestError("preparation snapshot does not completely round-trip")
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            if type(error) is DuckDBIngestError:
                raise
            raise DuckDBIngestError("preparation snapshot does not verify") from error
        if end_index > len(verified.entries):
            raise DuckDBIngestError("preparation interval exceeds the verified snapshot")
        selected = verified.entries[start_index:end_index]
        if type(source_bytes) is not dict or any(type(key) is not str for key in source_bytes):
            raise DuckDBIngestError("preparation source bytes require an exact native dictionary")
        sources = dict(source_bytes)
        if set(sources) != {entry.source_key for entry in selected if not entry.is_opaque}:
            raise DuckDBIngestError("preparation source keys must exactly cover selected nonopaque members")
        for entry in selected:
            if entry.is_opaque:
                continue
            data = sources[entry.source_key]
            if (type(data) is not bytes or len(data) != entry.size_bytes
                    or len(data) > verified.max_file_bytes
                    or validate_cid(entry.source_cid, codecs={"raw"}) != cid_for_bytes(data)
                    or _normalize_repo_path(entry.path) != entry.path):
                raise DuckDBIngestError("preparation source bytes or path do not verify")
        identity = SnapshotIngestIdentity(verified)
        with self._lock:
            def current_context() -> tuple[Any, ...]:
                if any(type(language) is not str for language in self._languages):
                    raise DuckDBIngestError("preparation languages require exact native text")
                if type(self._frontends) is not dict or any(type(language) is not str for language in self._frontends):
                    raise DuckDBIngestError("preparation frontend inventory must be exact")
                qualified = []
                for language, frontend in sorted(self._frontends.items()):
                    context = _frontend_cache_context(
                        frontend, language=language, path="__preparation_context__.py",
                    )
                    qualified.append((language, id(frontend), None if context is None else context.cid))
                return tuple(sorted(self._languages)), tuple(qualified)

            initial_context = current_context()
            owned_frontends = dict(self._frontends)

            def check() -> None:
                if checkpoint is not None:
                    checkpoint()
                if (current_context() != initial_context
                        or any(self._frontends[language] is not frontend
                               for language, frontend in owned_frontends.items())):
                    raise DuckDBIngestError("preparation extraction context changed")

            prepared = []
            check()
            for entry in selected:
                check()
                language = _language_for_path(entry.path)
                if entry.is_opaque or language not in self._languages or language not in self._frontends:
                    decision = FileIngestDecision(
                        path=entry.path, source_cid=entry.source_cid or "", language=language,
                        action=IngestAction.SKIPPED.value,
                        git_oid=(entry.git_blob_oid or "") if entry.is_opaque else "",
                        detail=(entry.opaque_reason or "opaque") if entry.is_opaque
                               else f"no_frontend_for_language:{language}",
                    )
                    prepared.append(SnapshotPreparedMember(entry.source_key, decision, None, None))
                    check()
                    continue
                context = _frontend_cache_context(
                    self._frontends[language], language=language, path=entry.path,
                )
                record, action = self._parse_or_reuse(
                    source_cid=entry.source_cid, data=sources[entry.source_key], path=entry.path,
                    language=language, repository_id=verified.repository_id,
                    revision=identity.revision, repository_tree_cid=identity.repository_tree_cid(),
                )
                # Frontends can retain their returned objects. Keep subsequent
                # checkpoints from changing these facts through that alias.
                record = ASTRecord.from_dict(json.loads(record.canonical_bytes))
                if record.provenance != SourceProvenance(
                        source_cid=entry.source_cid, path=entry.path,
                        repository_id=verified.repository_id, revision=identity.revision,
                        repository_tree_cid=identity.repository_tree_cid()):
                    raise DuckDBIngestError("preparation AST provenance differs from its full snapshot")
                check()
                if context != _frontend_cache_context(self._frontends[language], language=language, path=entry.path):
                    raise DuckDBIngestError("preparation source context changed during extraction")
                if context is not None:
                    context.verify(record, entry.source_cid)
                projection = project_ast_record(record, created_at=now)
                decision = FileIngestDecision(
                    path=entry.path, source_cid=entry.source_cid, language=language,
                    action=action.value, git_oid="", blob_id=projection.blob_id,
                    ast_cid=projection.ast_cid, parse_count=1 if action is IngestAction.PARSED else 0,
                    detail="parse_failed" if action is IngestAction.PARSE_FAILED else "",
                )
                prepared.append(SnapshotPreparedMember(entry.source_key, decision, projection, context))
                check()
            check()
            return tuple(prepared)

    def _ingest_sources(
        self,
        *,
        sources: Mapping[str, bytes],
        identity: GitObjectIdentity | SnapshotIngestIdentity,
        dirty_tree_policy: str,
        blobs: Sequence[TrackedBlob] | None = None,
        created_at: float | None = None,
        repository_id: str | None = None,
        skipped_decisions: Sequence[FileIngestDecision] = (),
        checkpoint: Callable[[], None] | None = None,
        before_publish: Callable[[RevisionPublication], None] | None = None,
        publish_batch: Callable[[RevisionPublication], None] | None = None,
    ) -> RevisionPublication:
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
        if len(normalized_sources) != len(sources) or any(type(data) is not bytes for data in normalized_sources.values()):
            raise DuckDBIngestError("sources require distinct normalized paths and exact bytes")
        blob_by_path: dict[str, TrackedBlob] = {}
        if blobs is not None:
            for blob in blobs:
                blob_by_path[_normalize_repo_path(blob.path)] = blob
        restart_contexts = None
        if self._optimized_restart_publication and type(identity) is SnapshotIngestIdentity:
            inventory = self._publication_context_inventory(identity.snapshot)
            if inventory is not None:
                restart_contexts = (tuple(sorted(self._languages)), inventory)

        # --- Phase 1: plan (no store mutations) ---------------------------
        decisions: list[FileIngestDecision] = list(skipped_decisions)
        planned: list[tuple[str, ASTRecord, IngestAction]] = []
        parseable_paths = 0
        parsed = 0
        reused = 0
        skipped = len(skipped_decisions)
        parse_failed = 0

        for path in sorted(normalized_sources):
            if checkpoint is not None:
                checkpoint()
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
        decision_positions: dict[str, list[int]] | None = None
        if self._optimized_decision_lookup:
            decision_positions = {}
            # Reversed positions let pop retain the original first eligible
            # decision, including duplicate paths in internal skipped decisions.
            for index in range(len(decisions) - 1, -1, -1):
                decision = decisions[index]
                if decision.blob_id is None:
                    decision_positions.setdefault(decision.path, []).append(index)
        projections: list[ASTCatalogProjection] = []
        for path, record, action in planned:
            projection = project_ast_record(record, created_at=now)
            projections.append(projection)
            # Fill decision identities now that projection exists.
            if decision_positions is not None:
                positions = decision_positions.get(path)
                if positions:
                    index = positions.pop()
                    decision = decisions[index]
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
            else:
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
        previous = self._previous_publication(identity)
        invalidations: list[InvalidationRow] = []
        deleted_paths = 0
        changed_paths = 0
        renamed_paths = 0
        if previous is not None and previous.revision_id != revision_id:
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
            scanned_path_count=len(normalized_sources) + len(skipped_decisions),
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
            if checkpoint is not None:
                checkpoint()
            if revision_id in self._publications:
                existing = self._publications[revision_id]
                if existing.published:
                    if (existing.identity.to_dict() != identity.to_dict()
                            or [(row.source_file.path, row.ast_cid) for row in existing.projections]
                            != [(row.source_file.path, row.ast_cid) for row in projections]):
                        raise DuckDBIngestError("revision identity already binds different source or extraction context")
                    latest_id = self._latest_by_label.get(self._publication_chain(identity))
                    if latest_id == revision_id and all(
                        self._store.get_by_ast_cid(row.ast_cid) == row
                        for row in existing.projections
                    ):
                        if before_publish is not None:
                            before_publish(existing)
                        if checkpoint is not None:
                            checkpoint()
                        if publish_batch is not None:
                            publish_batch(existing)
                        return existing
            pending_publication = RevisionPublication(
                revision_id=revision_id,
                repository_id=repo_id,
                revision=revision,
                identity=identity,
                repository_tree_cid=tree_cid,
                projections=tuple(projections),
                decisions=tuple(decisions),
                invalidations=tuple(invalidations),
                stats=stats,
                dirty_tree_policy=dirty_tree_policy,
                published=False,
                created_at=now,
            )
            if before_publish is not None:
                before_publish(pending_publication)
            if checkpoint is not None:
                checkpoint()
            if restart_contexts is not None and restart_contexts != (
                    tuple(sorted(self._languages)), self._publication_context_inventory(identity.snapshot)):
                raise DuckDBIngestError("restart publication extraction context changed during publication")
            if publish_batch is None:
                committed_projections, committed_invalidations = self._store.apply_batch(
                    projections=projections, invalidations=invalidations,
                )
            else:
                publish_batch(pending_publication)
                committed_projections, committed_invalidations = tuple(projections), tuple(invalidations)
            publication = replace(
                pending_publication, projections=tuple(committed_projections),
                invalidations=tuple(committed_invalidations), published=True,
            )
            self._publications[revision_id] = publication
            # Canonical snapshots have a stable repository identity. Legacy Git
            # ingestion chains commit-bound identities by its configured label.
            chain = self._publication_chain(identity)
            self._latest_by_label[chain] = revision_id
            if restart_contexts is not None:
                self._publication_restart_contexts[revision_id] = restart_contexts
            self._stats["revisions_published"] += 1
            self._stats["parse_invocations"] += parsed + parse_failed
            self._stats["reuse_hits"] += reused
            self._stats["invalidations"] += len(committed_invalidations)
            return publication

    # -- internals ---------------------------------------------------------

    def _publication_context_inventory(self, snapshot: RepositorySnapshot) -> list[dict[str, Any]] | None:
        if len(snapshot.entries) > SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES:
            return None
        result = []
        for entry in sorted(snapshot.entries, key=lambda item: item.path):
            language = _language_for_path(entry.path)
            context = None
            if entry.is_opaque:
                state = "opaque"
            elif language not in self._languages or language not in self._frontends:
                state = "skipped"
            else:
                qualified = _frontend_cache_context(self._frontends[language], language=language, path=entry.path)
                if qualified is None:
                    return None
                context = _source_shard_context_payload(qualified)
                state = "qualified"
            result.append({"path": entry.path, "source_cid": entry.source_cid,
                           "language": language, "state": state, "context": context})
        return result

    def _validate_active_publication(self, publication: RevisionPublication, *, checkpoint: Callable[[], None] | None = None) -> bool:
        return self._store.validate_active_revision(publication.projections, publication.invalidations,
            revision_id=publication.revision_id, repository_id=publication.repository_id,
            revision=publication.revision, repository_tree_cid=publication.repository_tree_cid,
            checkpoint=checkpoint)

    def _publication_chain(self, identity: GitObjectIdentity | SnapshotIngestIdentity) -> str:
        if isinstance(identity, SnapshotIngestIdentity):
            return "snapshot:" + identity.snapshot.repository_id
        return "git-label:" + self._repository_label

    def _previous_publication(
        self, identity: GitObjectIdentity | SnapshotIngestIdentity,
    ) -> RevisionPublication | None:
        latest_id = self._latest_by_label.get(self._publication_chain(identity))
        return self._publications.get(latest_id) if latest_id is not None else None

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
        frontend = self._frontends.get(language)
        if frontend is None:
            raise DuckDBIngestError(f"no frontend registered for {language}")
        if cid_for_bytes(data) != source_cid:
            raise DuckDBIngestError("source identity does not match exact parser bytes")
        context = _frontend_cache_context(frontend, language=language, path=path)
        cached = self._shard_cache.get(source_cid, context=context)
        if cached is not None:
            rebound = rebind_ast_record(
                cached, path=path, repository_id=repository_id, revision=revision,
                repository_tree_cid=repository_tree_cid,
            )
            return rebound, IngestAction.REUSED

        record = frontend.extract_from_source(
            data, path=path, repository_id=repository_id, revision=revision,
            repository_tree_cid=repository_tree_cid,
        )
        expected = SourceProvenance(
            source_cid=source_cid, path=path, repository_id=repository_id,
            revision=revision, repository_tree_cid=repository_tree_cid,
        )
        if type(record) is not ASTRecord or record.provenance != expected:
            raise DuckDBIngestError("frontend returned AST provenance inconsistent with supplied source")
        if context != _frontend_cache_context(frontend, language=language, path=path):
            raise DuckDBIngestError("frontend extraction context changed during parsing")
        self._shard_cache.put(record, context=context)
        # Parse failures remain durable AST facts; classify action for stats.
        failed = classify_parse_status(record) == "failed"
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
            "reuse_by_source_cid": False,
            "reuse_by_source_and_extraction_context": True,
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
    "SourceShardContext",
    "SOURCE_SHARD_RESTART_SCHEMA",
    "SOURCE_SHARD_RESTART_MAX_ENTRIES",
    "SOURCE_SHARD_RESTART_MAX_AST_BYTES",
    "SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES",
    "SNAPSHOT_RESTART_PUBLICATION_SCHEMA",
    "SNAPSHOT_RESTART_PUBLICATION_MAX_ENTRIES",
    "SNAPSHOT_RESTART_PUBLICATION_MAX_AST_BYTES",
    "SNAPSHOT_RESTART_PUBLICATION_MAX_MANIFEST_BYTES",
    "SNAPSHOT_RESTART_PUBLICATION_MAX_BUNDLE_BYTES",
    "SNAPSHOT_RESTART_PUBLICATION_MAX_INVALIDATIONS",
    "SnapshotIngestIdentity",
    "apply_dirty_tree_policy",
    "build_duckdb_ast_ingestor",
    "ingest_schema_descriptor",
    "rebind_ast_record",
    "repository_id_for_git",
    "resolve_git_object_identity",
    "tree_cid_for_git_tree",
    "validate_git_object_id",
]
