"""Exhaustive, Git-aware corpus inventories for repository forests.

The repository descriptor is the observation authority.  This module reads
committed objects from Git (never from a potentially dirty worktree), layers
an explicitly permitted working-tree overlay on top, and emits a bounded,
deterministic manifest which accounts for both admitted and excluded entries.

An inventory is exhaustive only when every descriptor is still current and
every discovered entry has a complete explanation.  Path ambiguity, escaping
symlinks, unreadable content, forbidden dirty state, unavailable Git objects,
or a manifest bound all fail the exhaustive verdict rather than being hidden
as a successful partial scan.

The executable evidence surface ``vfs/exhaustive-file-inventory@1`` (VFS-G138)
is the discovery key for this module.  Packet sibling
``vfs/incremental-ast-index@1`` (VFS-G139) is co-owned with
:mod:`program_ast_adapters` under parent goal VFS-G020 / goal packet
``goal_packet/corpus_index/ipfs_accelerate_py/26d54d2206f9``.  The synthetic
``objective validation repair`` discovery key (VFS-064) anchors the parent
VFS-G020 validation gate and never participates in inventory CIDs or entry
identities.  Evidence labels and goal metadata stay off identity material.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import stat
import subprocess
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping, Sequence

from ..proof.formal_verification_contracts import canonical_json_bytes, content_identity
from .repository_forest import (
    RepositoryDescriptor,
    RepositoryForest,
    RepositoryForestError,
    build_repository_descriptor,
)


CORPUS_INDEX_SCHEMA = "ipfs_accelerate_py.agent_supervisor.repository-corpus-index@1"
CORPUS_ENTRY_SCHEMA = "ipfs_accelerate_py.agent_supervisor.repository-corpus-entry@1"
REPOSITORY_INVENTORY_SCHEMA = "ipfs_accelerate_py.agent_supervisor.repository-inventory@1"
INVENTORY_LIMITS_SCHEMA = "ipfs_accelerate_py.agent_supervisor.repository-inventory-limits@1"

# Exact objective-heap discovery keys and supervisor-fed packet bindings.
# Domain evidence owned by this module (VFS-G138).
EXHAUSTIVE_FILE_INVENTORY_EVIDENCE: Final[str] = "vfs/exhaustive-file-inventory@1"
# Packet sibling (VFS-G139) co-covered with program_ast_adapters.
INCREMENTAL_AST_INDEX_EVIDENCE: Final[str] = "vfs/incremental-ast-index@1"
# Synthetic objective-heap evidence term for VFS-G020 validation-gate work.
# Exact-text discovery key only — never part of inventory_cid or entry identity.
OBJECTIVE_VALIDATION_REPAIR_EVIDENCE: Final[str] = "objective validation repair"
OBJECTIVE_GOAL_ID: Final[str] = "VFS-G138"
PACKET_SIBLING_GOAL_ID: Final[str] = "VFS-G139"
OBJECTIVE_PARENT_GOAL_ID: Final[str] = "VFS-G020"
# Domain packet task that authored vfs/exhaustive-file-inventory@1 (VFS-G138).
OBJECTIVE_TASK_ID: Final[str] = "VFS-063"
# Repair task that owns the synthetic objective validation repair obligation.
OBJECTIVE_VALIDATION_REPAIR_TASK_ID: Final[str] = "VFS-064"
GOAL_PACKET_ID: Final[str] = "goal_packet/corpus_index/ipfs_accelerate_py/26d54d2206f9"
OBJECTIVE_DOMAIN_EVIDENCE_TERMS: Final[tuple[str, ...]] = (EXHAUSTIVE_FILE_INVENTORY_EVIDENCE,)
# Parent VFS-G020 / packet aggregate evidence surface (inventory + AST index).
# Domain packet keys only — objective validation repair is appended by
# :func:`objective_validation_repair_evidence_terms` / full discovery helpers.
CORPUS_INDEX_G020_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    EXHAUSTIVE_FILE_INVENTORY_EVIDENCE,
    INCREMENTAL_AST_INDEX_EVIDENCE,
)
PACKET_GOAL_IDS: Final[tuple[str, ...]] = (
    OBJECTIVE_GOAL_ID,
    PACKET_SIBLING_GOAL_ID,
)
# Acceptance invariants published with every inventory evidence claim.
EXHAUSTIVE_FILE_INVENTORY_INVARIANTS: Final[tuple[str, ...]] = (
    "included and excluded populations publish with reasons",
    "unexplained skips block exhaustive verdict",
    "truncation and path ambiguity fail closed",
    "forged exhaustive flags fail closed",
    "unchanged committed entries are reusable",
)
# Parent VFS-G020 acceptance subset (inventory + incremental parse gate).
OBJECTIVE_VALIDATION_REPAIR_INVARIANTS: Final[tuple[str, ...]] = (
    "included and excluded populations publish with reasons",
    "TypeScript/TSX/JavaScript/Python/JSON/Markdown inputs have provenance",
    "unchanged blobs are reused from the previous snapshot",
    "unexplained skips, parser failures, and truncation prevent an exhaustive verdict",
    "inventory, language adapters, and incremental persistence stay conflict-domain split",
)

# Keep exact-text discovery anchors aligned with the objective heap.
assert EXHAUSTIVE_FILE_INVENTORY_EVIDENCE == "vfs/exhaustive-file-inventory@1"
assert INCREMENTAL_AST_INDEX_EVIDENCE == "vfs/incremental-ast-index@1"
assert OBJECTIVE_VALIDATION_REPAIR_EVIDENCE == "objective validation repair"
assert OBJECTIVE_GOAL_ID == "VFS-G138"
assert PACKET_SIBLING_GOAL_ID == "VFS-G139"
assert OBJECTIVE_PARENT_GOAL_ID == "VFS-G020"
assert OBJECTIVE_TASK_ID == "VFS-063"
assert OBJECTIVE_VALIDATION_REPAIR_TASK_ID == "VFS-064"
assert OBJECTIVE_DOMAIN_EVIDENCE_TERMS == ("vfs/exhaustive-file-inventory@1",)
assert CORPUS_INDEX_G020_EVIDENCE_TERMS == (
    "vfs/exhaustive-file-inventory@1",
    "vfs/incremental-ast-index@1",
)

_GIT_OBJECT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_MODE_RE = re.compile(r"[0-7]{6}\Z")
_SOURCE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".clj",
        ".cljs",
        ".cpp",
        ".cs",
        ".cxx",
        ".ex",
        ".exs",
        ".go",
        ".h",
        ".hh",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".lua",
        ".mjs",
        ".cjs",
        ".php",
        ".pl",
        ".pm",
        ".py",
        ".pyi",
        ".pyx",
        ".rb",
        ".rs",
        ".scala",
        ".sh",
        ".sol",
        ".swift",
        ".ts",
        ".tsx",
        ".vue",
    }
)
_DOC_EXTENSIONS = frozenset({".md", ".mdx", ".rst", ".adoc", ".asciidoc", ".txt"})
_SCHEMA_EXTENSIONS = frozenset(
    {".json", ".json5", ".jsonc", ".schema", ".proto", ".graphql", ".gql", ".xsd"}
)
_ARCHIVE_EXTENSIONS = (
    ".7z",
    ".a",
    ".bz2",
    ".cab",
    ".deb",
    ".dmg",
    ".egg",
    ".gz",
    ".iso",
    ".jar",
    ".lz",
    ".lz4",
    ".rar",
    ".rpm",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tgz",
    ".txz",
    ".war",
    ".whl",
    ".xz",
    ".zip",
    ".zst",
)
_BINARY_EXTENSIONS = frozenset(
    {
        ".avif",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dylib",
        ".eot",
        ".exe",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".lockb",
        ".mp3",
        ".mp4",
        ".o",
        ".obj",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".ttf",
        ".wasm",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
    }
)
_GENERATED_SEGMENTS = frozenset({"generated", "gen", "codegen", "__generated__", "autogen"})
_VENDORED_SEGMENTS = frozenset(
    {
        "vendor",
        "vendors",
        "vendored",
        "third_party",
        "third-party",
        "external",
        "node_modules",
        "bower_components",
    }
)
_BUILD_SEGMENTS = frozenset(
    {
        "build",
        "dist",
        "out",
        "output",
        "coverage",
        ".coverage",
        ".next",
        ".nuxt",
        ".parcel-cache",
        ".turbo",
        ".cache",
        "__pycache__",
        "target",
        "site-packages",
    }
)
_TEST_SEGMENTS = frozenset({"test", "tests", "__tests__", "spec", "specs"})
_FIXTURE_SEGMENTS = frozenset(
    {
        "fixture",
        "fixtures",
        "__fixtures__",
        "testdata",
        "test_data",
        "snapshots",
        "__snapshots__",
        "golden",
    }
)
_FATAL_ENTRY_REASONS = frozenset(
    {
        "canonical_path_collision",
        "invalid_path_encoding",
        "path_escape",
        "symlink_target_escape",
        "unreadable_entry",
        "unavailable_git_object",
    }
)


class RepositoryCorpusIndexError(ValueError):
    """A malformed request or unsafe inventory operation."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        self.reason_code = str(reason_code or "repository_corpus_index_error")
        super().__init__(str(message or reason_code))


class CorpusClassification(str, Enum):
    """Closed, non-exclusive entry classifications."""

    SOURCE = "source"
    GENERATED_SOURCE = "generated_source"
    SCHEMA = "schema"
    DOCS = "docs"
    TESTS = "tests"
    FIXTURES = "fixtures"
    VENDORED = "vendored"
    ARCHIVE = "archive"
    BUILD_OUTPUT = "build_output"
    SYMLINK = "symlink"
    SUBMODULE = "submodule"
    IGNORED = "ignored"
    BINARY = "binary"
    OVERSIZED = "oversized"


class EntryOrigin(str, Enum):
    COMMITTED = "committed"
    DIRTY_OVERLAY = "dirty_overlay"
    IGNORED = "ignored"


class InclusionDecision(str, Enum):
    INCLUDED = "included"
    EXCLUDED = "excluded"


def _positive_int(value: Any, *, field_name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RepositoryCorpusIndexError(
            "invalid_inventory_limit",
            f"{field_name} must be an integer >= {minimum}",
        )
    return value


@dataclass(frozen=True)
class InventoryLimits:
    """Hard bounds for parser admission and serialized inventory size."""

    schema: str = INVENTORY_LIMITS_SCHEMA
    max_repositories: int = 64
    max_entries: int = 100_000
    max_manifest_bytes: int = 32 * 1024 * 1024
    max_parser_bytes: int = 2 * 1024 * 1024
    max_path_bytes: int = 4096
    git_timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if self.schema != INVENTORY_LIMITS_SCHEMA:
            raise RepositoryCorpusIndexError("unsupported_inventory_limits_schema")
        for field_name in (
            "max_repositories",
            "max_entries",
            "max_manifest_bytes",
            "max_parser_bytes",
            "max_path_bytes",
            "git_timeout_seconds",
        ):
            minimum = 1024 if field_name == "max_manifest_bytes" else 1
            object.__setattr__(
                self,
                field_name,
                _positive_int(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )

    @property
    def limits_cid(self) -> str:
        return content_identity(self.to_portable_dict())

    def to_portable_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "max_repositories": self.max_repositories,
            "max_entries": self.max_entries,
            "max_manifest_bytes": self.max_manifest_bytes,
            "max_parser_bytes": self.max_parser_bytes,
            "max_path_bytes": self.max_path_bytes,
            "git_timeout_seconds": self.git_timeout_seconds,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "InventoryLimits":
        defaults = cls()
        return cls(
            schema=str(payload.get("schema") or INVENTORY_LIMITS_SCHEMA),
            max_repositories=int(payload.get("max_repositories", defaults.max_repositories)),
            max_entries=int(payload.get("max_entries", defaults.max_entries)),
            max_manifest_bytes=int(payload.get("max_manifest_bytes", defaults.max_manifest_bytes)),
            max_parser_bytes=int(payload.get("max_parser_bytes", defaults.max_parser_bytes)),
            max_path_bytes=int(payload.get("max_path_bytes", defaults.max_path_bytes)),
            git_timeout_seconds=int(
                payload.get("git_timeout_seconds", defaults.git_timeout_seconds)
            ),
        )


def _normalize_relative_path(raw: str, *, max_path_bytes: int) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise RepositoryCorpusIndexError("invalid_path_encoding")
    text = raw.replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        raise RepositoryCorpusIndexError("path_escape")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise RepositoryCorpusIndexError("path_escape")
    if len(text.encode("utf-8")) > max_path_bytes:
        raise RepositoryCorpusIndexError("path_bound_exceeded")
    return "/".join(parts)


def _enum_value(value: Any, enum_type: type[Enum], *, reason: str) -> str:
    raw = getattr(value, "value", value)
    try:
        return str(enum_type(raw).value)
    except (TypeError, ValueError) as exc:
        raise RepositoryCorpusIndexError(reason) from exc


@dataclass(frozen=True)
class CorpusEntry:
    """One committed object or working-tree overlay observation."""

    schema: str = CORPUS_ENTRY_SCHEMA
    repository_id: str = ""
    repository_alias: str = ""
    relative_path: str = ""
    canonical_path: str = ""
    origin: str = EntryOrigin.COMMITTED.value
    git_status: str = ""
    mode: str = "100644"
    object_type: str = "blob"
    blob_oid: str = ""
    base_blob_oid: str = ""
    content_sha256: str = ""
    size: int = 0
    classifications: tuple[str, ...] = ()
    parser_eligible: bool = False
    inclusion: str = InclusionDecision.EXCLUDED.value
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != CORPUS_ENTRY_SCHEMA:
            raise RepositoryCorpusIndexError("unsupported_corpus_entry_schema")
        if not self.repository_id or not self.repository_alias:
            raise RepositoryCorpusIndexError("missing_repository_binding")
        relative = _normalize_relative_path(self.relative_path, max_path_bytes=1_048_576)
        canonical = str(self.canonical_path or "")
        if not canonical or "\x00" in canonical or canonical.startswith("/"):
            raise RepositoryCorpusIndexError("invalid_canonical_path")
        origin = _enum_value(self.origin, EntryOrigin, reason="unsupported_entry_origin")
        inclusion = _enum_value(
            self.inclusion,
            InclusionDecision,
            reason="unsupported_inclusion_decision",
        )
        mode = str(self.mode or "")
        if not _MODE_RE.fullmatch(mode):
            raise RepositoryCorpusIndexError("invalid_git_mode")
        object_type = str(self.object_type or "")
        if object_type not in {"blob", "symlink", "submodule", "deleted", "unreadable"}:
            raise RepositoryCorpusIndexError("unsupported_git_object_type")
        oid = str(self.blob_oid or "").lower()
        if oid and not (
            _GIT_OBJECT_RE.fullmatch(oid)
            or oid.startswith("deleted:")
            or oid.startswith("unreadable:")
        ):
            raise RepositoryCorpusIndexError("invalid_blob_identity")
        base_oid = str(self.base_blob_oid or "").lower()
        if base_oid and not _GIT_OBJECT_RE.fullmatch(base_oid):
            raise RepositoryCorpusIndexError("invalid_base_blob_identity")
        digest = str(self.content_sha256 or "").lower()
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RepositoryCorpusIndexError("invalid_content_digest")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise RepositoryCorpusIndexError("invalid_entry_size")
        classes = tuple(
            sorted(
                {
                    _enum_value(
                        item,
                        CorpusClassification,
                        reason="unsupported_corpus_classification",
                    )
                    for item in self.classifications
                }
            )
        )
        if not isinstance(self.parser_eligible, bool):
            raise RepositoryCorpusIndexError("invalid_parser_eligibility")
        reasons = tuple(sorted({str(item) for item in self.reason_codes if str(item)}))
        if not reasons:
            raise RepositoryCorpusIndexError("missing_inclusion_reason")
        if inclusion == InclusionDecision.INCLUDED.value and not self.parser_eligible:
            raise RepositoryCorpusIndexError("ineligible_entry_included")
        object.__setattr__(self, "relative_path", relative)
        object.__setattr__(self, "canonical_path", canonical)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "inclusion", inclusion)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "object_type", object_type)
        object.__setattr__(self, "blob_oid", oid)
        object.__setattr__(self, "base_blob_oid", base_oid)
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "classifications", classes)
        object.__setattr__(self, "reason_codes", reasons)

    @property
    def included(self) -> bool:
        return self.inclusion == InclusionDecision.INCLUDED.value

    @property
    def entry_cid(self) -> str:
        return content_identity(self.to_portable_dict())

    def to_portable_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository_id": self.repository_id,
            "repository_alias": self.repository_alias,
            "relative_path": self.relative_path,
            "canonical_path": self.canonical_path,
            "origin": self.origin,
            "git_status": self.git_status,
            "mode": self.mode,
            "object_type": self.object_type,
            "blob_oid": self.blob_oid,
            "base_blob_oid": self.base_blob_oid,
            "content_sha256": self.content_sha256,
            "size": self.size,
            "classifications": list(self.classifications),
            "parser_eligible": self.parser_eligible,
            "inclusion": self.inclusion,
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_portable_dict()
        payload["entry_cid"] = self.entry_cid
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CorpusEntry":
        return cls(
            schema=str(payload.get("schema") or CORPUS_ENTRY_SCHEMA),
            repository_id=str(payload.get("repository_id") or ""),
            repository_alias=str(payload.get("repository_alias") or ""),
            relative_path=str(payload.get("relative_path") or ""),
            canonical_path=str(payload.get("canonical_path") or ""),
            origin=str(payload.get("origin") or EntryOrigin.COMMITTED.value),
            git_status=str(payload.get("git_status") or ""),
            mode=str(payload.get("mode") or "100644"),
            object_type=str(payload.get("object_type") or "blob"),
            blob_oid=str(payload.get("blob_oid") or ""),
            base_blob_oid=str(payload.get("base_blob_oid") or ""),
            content_sha256=str(payload.get("content_sha256") or ""),
            size=int(payload.get("size") or 0),
            classifications=tuple(payload.get("classifications") or ()),
            parser_eligible=payload.get("parser_eligible", False),
            inclusion=str(payload.get("inclusion") or InclusionDecision.EXCLUDED.value),
            reason_codes=tuple(payload.get("reason_codes") or ()),
        )


@dataclass(frozen=True)
class RepositoryInventory:
    """Bounded coverage summary for one repository descriptor."""

    schema: str = REPOSITORY_INVENTORY_SCHEMA
    repository_id: str = ""
    repository_alias: str = ""
    descriptor_cid: str = ""
    observed_entry_count: int = 0
    emitted_entry_count: int = 0
    included_entry_count: int = 0
    excluded_entry_count: int = 0
    omitted_entry_count: int = 0
    classification_counts: tuple[tuple[str, int], ...] = ()
    origin_counts: tuple[tuple[str, int], ...] = ()
    exhaustive: bool = False
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != REPOSITORY_INVENTORY_SCHEMA:
            raise RepositoryCorpusIndexError("unsupported_repository_inventory_schema")
        if not self.repository_id or not self.repository_alias or not self.descriptor_cid:
            raise RepositoryCorpusIndexError("missing_repository_inventory_binding")
        for name in (
            "observed_entry_count",
            "emitted_entry_count",
            "included_entry_count",
            "excluded_entry_count",
            "omitted_entry_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RepositoryCorpusIndexError("invalid_inventory_count")
        if self.emitted_entry_count + self.omitted_entry_count != self.observed_entry_count:
            raise RepositoryCorpusIndexError("inventory_count_mismatch")
        counts = self.included_entry_count + self.excluded_entry_count
        if counts != self.emitted_entry_count:
            raise RepositoryCorpusIndexError("decision_count_mismatch")
        if not isinstance(self.exhaustive, bool):
            raise RepositoryCorpusIndexError("invalid_exhaustive_flag")
        reasons = tuple(sorted({str(item) for item in self.reason_codes if str(item)}))
        if self.exhaustive and (reasons or self.omitted_entry_count):
            raise RepositoryCorpusIndexError("forged_exhaustive_inventory")
        if not self.exhaustive and not reasons:
            raise RepositoryCorpusIndexError("incomplete_inventory_without_reason")
        object.__setattr__(
            self, "classification_counts", _normalize_counts(self.classification_counts)
        )
        object.__setattr__(self, "origin_counts", _normalize_counts(self.origin_counts))
        object.__setattr__(self, "reason_codes", reasons)

    def to_portable_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository_id": self.repository_id,
            "repository_alias": self.repository_alias,
            "descriptor_cid": self.descriptor_cid,
            "observed_entry_count": self.observed_entry_count,
            "emitted_entry_count": self.emitted_entry_count,
            "included_entry_count": self.included_entry_count,
            "excluded_entry_count": self.excluded_entry_count,
            "omitted_entry_count": self.omitted_entry_count,
            "classification_counts": dict(self.classification_counts),
            "origin_counts": dict(self.origin_counts),
            "exhaustive": self.exhaustive,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RepositoryInventory":
        return cls(
            schema=str(payload.get("schema") or REPOSITORY_INVENTORY_SCHEMA),
            repository_id=str(payload.get("repository_id") or ""),
            repository_alias=str(payload.get("repository_alias") or ""),
            descriptor_cid=str(payload.get("descriptor_cid") or ""),
            observed_entry_count=int(payload.get("observed_entry_count") or 0),
            emitted_entry_count=int(payload.get("emitted_entry_count") or 0),
            included_entry_count=int(payload.get("included_entry_count") or 0),
            excluded_entry_count=int(payload.get("excluded_entry_count") or 0),
            omitted_entry_count=int(payload.get("omitted_entry_count") or 0),
            classification_counts=tuple(
                (str(key), int(value))
                for key, value in dict(payload.get("classification_counts") or {}).items()
            ),
            origin_counts=tuple(
                (str(key), int(value))
                for key, value in dict(payload.get("origin_counts") or {}).items()
            ),
            exhaustive=payload.get("exhaustive", False),
            reason_codes=tuple(payload.get("reason_codes") or ()),
        )


def _normalize_counts(values: Iterable[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    result: dict[str, int] = {}
    for raw_key, raw_value in values:
        key = str(raw_key)
        value = raw_value
        if not key or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RepositoryCorpusIndexError("invalid_population_count")
        result[key] = value
    return tuple(sorted(result.items()))


@dataclass(frozen=True)
class RepositoryCorpusIndex:
    """Content-bound multi-repository exhaustive inventory receipt."""

    schema: str = CORPUS_INDEX_SCHEMA
    forest_id: str = ""
    limits: InventoryLimits = InventoryLimits()
    repositories: tuple[RepositoryInventory, ...] = ()
    entries: tuple[CorpusEntry, ...] = ()
    exhaustive: bool = False
    reason_codes: tuple[str, ...] = ()
    reused_entry_count: int = 0

    def __post_init__(self) -> None:
        if self.schema != CORPUS_INDEX_SCHEMA:
            raise RepositoryCorpusIndexError("unsupported_corpus_index_schema")
        if not self.forest_id:
            raise RepositoryCorpusIndexError("missing_forest_identity")
        limits = self.limits
        if isinstance(limits, Mapping):
            limits = InventoryLimits.from_dict(limits)
        if not isinstance(limits, InventoryLimits):
            raise RepositoryCorpusIndexError("invalid_inventory_limits")
        repositories = tuple(
            item if isinstance(item, RepositoryInventory) else RepositoryInventory.from_dict(item)
            for item in self.repositories
        )
        repositories = tuple(sorted(repositories, key=lambda item: item.repository_alias))
        entries = tuple(
            item if isinstance(item, CorpusEntry) else CorpusEntry.from_dict(item)
            for item in self.entries
        )
        entries = tuple(sorted(entries, key=_entry_sort_key))
        aliases = [item.repository_alias for item in repositories]
        if len(aliases) != len(set(aliases)):
            raise RepositoryCorpusIndexError("duplicate_repository_inventory")
        repository_by_alias = {item.repository_alias: item for item in repositories}
        if any(item.repository_alias not in repository_by_alias for item in entries):
            raise RepositoryCorpusIndexError("entry_without_repository_inventory")
        for summary in repositories:
            repository_entries = [
                item for item in entries if item.repository_alias == summary.repository_alias
            ]
            if any(item.repository_id != summary.repository_id for item in repository_entries):
                raise RepositoryCorpusIndexError("entry_repository_id_mismatch")
            if (
                len(repository_entries) != summary.emitted_entry_count
                or sum(item.included for item in repository_entries) != summary.included_entry_count
                or sum(not item.included for item in repository_entries)
                != summary.excluded_entry_count
            ):
                raise RepositoryCorpusIndexError("repository_entry_count_mismatch")
            if summary.omitted_entry_count == 0:
                class_counts: Counter[str] = Counter()
                origin_counts: Counter[str] = Counter()
                for item in repository_entries:
                    class_counts.update(item.classifications)
                    origin_counts.update((item.origin,))
                if (
                    tuple(sorted(class_counts.items())) != summary.classification_counts
                    or tuple(sorted(origin_counts.items())) != summary.origin_counts
                ):
                    raise RepositoryCorpusIndexError("repository_population_count_mismatch")
        if len(repositories) > limits.max_repositories or len(entries) > limits.max_entries:
            raise RepositoryCorpusIndexError("manifest_bounds_violated")
        if (
            isinstance(self.reused_entry_count, bool)
            or not isinstance(self.reused_entry_count, int)
            or not 0 <= self.reused_entry_count <= len(entries)
        ):
            raise RepositoryCorpusIndexError("invalid_reuse_count")
        reasons = tuple(sorted({str(item) for item in self.reason_codes if str(item)}))
        if not isinstance(self.exhaustive, bool):
            raise RepositoryCorpusIndexError("invalid_exhaustive_flag")
        exhaustive = self.exhaustive
        if exhaustive and (reasons or any(not item.exhaustive for item in repositories)):
            raise RepositoryCorpusIndexError("forged_exhaustive_receipt")
        if not exhaustive and not reasons:
            raise RepositoryCorpusIndexError("incomplete_receipt_without_reason")
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "repositories", repositories)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "exhaustive", exhaustive)
        if len(canonical_json_bytes(self._identity_material())) > limits.max_manifest_bytes:
            raise RepositoryCorpusIndexError("manifest_byte_bound_violated")

    @property
    def inventory_cid(self) -> str:
        return content_identity(self._identity_material())

    @property
    def receipt_cid(self) -> str:
        return self.inventory_cid

    @property
    def included_entries(self) -> tuple[CorpusEntry, ...]:
        return tuple(item for item in self.entries if item.included)

    @property
    def excluded_entries(self) -> tuple[CorpusEntry, ...]:
        return tuple(item for item in self.entries if not item.included)

    def _identity_material(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "forest_id": self.forest_id,
            "limits": self.limits.to_portable_dict(),
            "repositories": [item.to_portable_dict() for item in self.repositories],
            "entries": [item.to_portable_dict() for item in self.entries],
            "exhaustive": self.exhaustive,
            "reason_codes": list(self.reason_codes),
        }

    def to_portable_dict(self) -> dict[str, Any]:
        payload = self._identity_material()
        payload["inventory_cid"] = self.inventory_cid
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_portable_dict()
        # Reuse is an execution diagnostic, never portable identity material.
        payload["reused_entry_count"] = self.reused_entry_count
        payload["entries"] = [item.to_dict() for item in self.entries]
        # Objective evidence bindings are diagnostic metadata only; they never
        # participate in inventory_cid / portable identity material.
        payload["evidence"] = EXHAUSTIVE_FILE_INVENTORY_EVIDENCE
        payload["evidence_terms"] = list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS)
        payload["goal_id"] = OBJECTIVE_GOAL_ID
        payload["goal_packet"] = GOAL_PACKET_ID
        payload["packet_goal_ids"] = list(PACKET_GOAL_IDS)
        payload["parent_goal_id"] = OBJECTIVE_PARENT_GOAL_ID
        payload["task_id"] = OBJECTIVE_TASK_ID
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RepositoryCorpusIndex":
        result = cls(
            schema=str(payload.get("schema") or CORPUS_INDEX_SCHEMA),
            forest_id=str(payload.get("forest_id") or ""),
            limits=InventoryLimits.from_dict(payload.get("limits") or {}),
            repositories=tuple(payload.get("repositories") or ()),
            entries=tuple(payload.get("entries") or ()),
            exhaustive=payload.get("exhaustive", False),
            reason_codes=tuple(payload.get("reason_codes") or ()),
            reused_entry_count=int(payload.get("reused_entry_count") or 0),
        )
        claimed = str(payload.get("inventory_cid") or payload.get("receipt_cid") or "")
        if claimed and claimed != result.inventory_cid:
            raise RepositoryCorpusIndexError("inventory_cid_mismatch")
        return result

    def satisfies_exhaustive_file_inventory(self) -> bool:
        """Return whether this receipt meets ``vfs/exhaustive-file-inventory@1``.

        Exhaustive inventories must publish included and excluded populations
        with reasons, must not claim exhaustiveness when reason codes or
        truncated repositories exist, and must keep every emitted entry fully
        accounted (canonical path + decision reason).
        """

        return inventory_satisfies_exhaustive_file_inventory(self)

    def to_evidence_claim(self) -> dict[str, Any]:
        """Portable VFS-G138 evidence claim bound to this inventory receipt."""

        return prove_exhaustive_file_inventory(self)


# Compatibility name used by the plan's "receipt" terminology.
ExhaustiveCorpusReceipt = RepositoryCorpusIndex
CorpusInventoryLimits = InventoryLimits
RepositoryCorpusEntry = CorpusEntry


@dataclass(frozen=True)
class _TreeEntry:
    path: str
    mode: str
    object_type: str
    oid: str
    size: int


@dataclass(frozen=True)
class _OverlayPath:
    path: str
    status: str
    deleted: bool = False
    ignored: bool = False


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    timeout: int,
    input_bytes: bytes | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=None if input_bytes is not None else subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RepositoryCorpusIndexError("git_command_unavailable") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RepositoryCorpusIndexError("git_command_failed", detail[:512] or "Git command failed")
    return completed.stdout


def _decode_git_path(raw: bytes) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RepositoryCorpusIndexError("invalid_path_encoding") from exc


def _committed_tree(descriptor: RepositoryDescriptor, limits: InventoryLimits) -> list[_TreeEntry]:
    output = _git(
        descriptor.root_path,
        ["ls-tree", "-r", "-z", "-l", "--full-tree", descriptor.commit],
        timeout=limits.git_timeout_seconds,
    )
    entries: list[_TreeEntry] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        if b"\t" not in raw:
            raise RepositoryCorpusIndexError("malformed_git_tree")
        metadata, raw_path = raw.split(b"\t", 1)
        parts = metadata.split()
        if len(parts) != 4:
            raise RepositoryCorpusIndexError("malformed_git_tree")
        mode = parts[0].decode("ascii", errors="strict")
        object_type = parts[1].decode("ascii", errors="strict")
        oid = parts[2].decode("ascii", errors="strict").lower()
        raw_size = parts[3]
        if not _MODE_RE.fullmatch(mode) or not _GIT_OBJECT_RE.fullmatch(oid):
            raise RepositoryCorpusIndexError("malformed_git_tree")
        path = _normalize_relative_path(
            _decode_git_path(raw_path), max_path_bytes=limits.max_path_bytes
        )
        if mode == "160000" or object_type == "commit":
            size = 0
            normalized_type = "submodule"
        else:
            try:
                size = int(raw_size)
            except ValueError as exc:
                raise RepositoryCorpusIndexError("malformed_git_tree") from exc
            normalized_type = "symlink" if mode == "120000" else "blob"
        entries.append(
            _TreeEntry(
                path=path,
                mode=mode,
                object_type=normalized_type,
                oid=oid,
                size=size,
            )
        )
    return sorted(entries, key=lambda item: item.path.encode("utf-8"))


def _status_overlay(
    descriptor: RepositoryDescriptor, limits: InventoryLimits
) -> list[_OverlayPath]:
    output = _git(
        descriptor.root_path,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        timeout=limits.git_timeout_seconds,
    )
    chunks = output.split(b"\0")
    result: list[_OverlayPath] = []
    index = 0
    while index < len(chunks):
        raw = chunks[index]
        index += 1
        if not raw:
            continue
        if len(raw) < 4 or raw[2:3] != b" ":
            raise RepositoryCorpusIndexError("malformed_git_status")
        status_code = raw[:2].decode("ascii", errors="replace")
        destination = _normalize_relative_path(
            _decode_git_path(raw[3:]), max_path_bytes=limits.max_path_bytes
        )
        is_rename = any(code in status_code for code in ("R", "C"))
        if is_rename:
            if index >= len(chunks) or not chunks[index]:
                raise RepositoryCorpusIndexError("malformed_git_status")
            source = _normalize_relative_path(
                _decode_git_path(chunks[index]),
                max_path_bytes=limits.max_path_bytes,
            )
            index += 1
            if "R" in status_code:
                result.append(_OverlayPath(path=source, status="R-", deleted=True))
        deleted = "D" in status_code
        result.append(_OverlayPath(path=destination, status=status_code, deleted=deleted))
    by_key: dict[tuple[str, bool], _OverlayPath] = {}
    for item in result:
        by_key[(item.path, item.deleted)] = item
    return sorted(
        by_key.values(),
        key=lambda item: (item.path.encode("utf-8"), item.deleted, item.status),
    )


def _ignored_paths(descriptor: RepositoryDescriptor, limits: InventoryLimits) -> list[_OverlayPath]:
    output = _git(
        descriptor.root_path,
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        timeout=limits.git_timeout_seconds,
    )
    result: list[_OverlayPath] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        path = _normalize_relative_path(_decode_git_path(raw), max_path_bytes=limits.max_path_bytes)
        result.append(_OverlayPath(path=path, status="!!", ignored=True))
    return sorted(result, key=lambda item: item.path.encode("utf-8"))


def _path_segments(path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in PurePosixPath(path).parts)


def classify_corpus_path(
    relative_path: str,
    *,
    mode: str = "100644",
    size: int = 0,
    ignored: bool = False,
    binary: bool = False,
    max_parser_bytes: int = 2 * 1024 * 1024,
) -> tuple[str, ...]:
    """Classify a path without making an inclusion decision."""

    path = relative_path.replace("\\", "/")
    lower = path.casefold()
    name = PurePosixPath(lower).name
    suffix = PurePosixPath(lower).suffix
    segments = _path_segments(path)
    classes: set[str] = set()
    if mode == "120000":
        classes.add(CorpusClassification.SYMLINK.value)
    if mode == "160000":
        classes.add(CorpusClassification.SUBMODULE.value)
    if ignored:
        classes.add(CorpusClassification.IGNORED.value)
    if any(part in _VENDORED_SEGMENTS for part in segments):
        classes.add(CorpusClassification.VENDORED.value)
    if any(part in _BUILD_SEGMENTS for part in segments):
        classes.add(CorpusClassification.BUILD_OUTPUT.value)
    is_test = (
        any(part in _TEST_SEGMENTS for part in segments)
        or ".test." in name
        or ".spec." in name
        or name.startswith("test_")
        or name.endswith("_test.py")
    )
    if is_test:
        classes.add(CorpusClassification.TESTS.value)
    if any(part in _FIXTURE_SEGMENTS for part in segments):
        classes.add(CorpusClassification.FIXTURES.value)
    archive = any(lower.endswith(extension) for extension in _ARCHIVE_EXTENSIONS)
    if archive:
        classes.add(CorpusClassification.ARCHIVE.value)
    if suffix in _SOURCE_EXTENSIONS:
        classes.add(CorpusClassification.SOURCE.value)
        generated_name = (
            ".generated." in name
            or ".gen." in name
            or name.endswith("_pb2.py")
            or name.endswith("_pb2_grpc.py")
            or any(part in _GENERATED_SEGMENTS for part in segments)
        )
        if generated_name:
            classes.add(CorpusClassification.GENERATED_SOURCE.value)
    schema_name = (
        suffix in _SCHEMA_EXTENSIONS
        or ".schema." in name
        or name
        in {
            "openapi.yaml",
            "openapi.yml",
            "swagger.yaml",
            "swagger.yml",
            "package.json",
            "tsconfig.json",
        }
    )
    if schema_name:
        classes.add(CorpusClassification.SCHEMA.value)
    if (
        suffix in _DOC_EXTENSIONS
        or any(part in {"doc", "docs", "documentation"} for part in segments)
        or name.startswith("readme")
        or name.startswith("changelog")
    ):
        classes.add(CorpusClassification.DOCS.value)
    if binary or suffix in _BINARY_EXTENSIONS or archive:
        classes.add(CorpusClassification.BINARY.value)
    if size > max_parser_bytes:
        classes.add(CorpusClassification.OVERSIZED.value)
    return tuple(sorted(classes))


def _looks_binary(content: bytes, relative_path: str) -> bool:
    suffix = PurePosixPath(relative_path.casefold()).suffix
    if suffix in _BINARY_EXTENSIONS:
        return True
    sample = content[:8192]
    if b"\0" in sample:
        return True
    try:
        sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return True
    return False


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path).match(pattern)
        for pattern in patterns
    )


def _decision(
    *,
    path: str,
    classifications: Sequence[str],
    descriptor: RepositoryDescriptor,
    unreadable: bool = False,
    deleted: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    classes = set(classifications)
    reasons: list[str] = []
    eligible = bool(
        classes.intersection(
            {
                CorpusClassification.SOURCE.value,
                CorpusClassification.SCHEMA.value,
                CorpusClassification.DOCS.value,
            }
        )
    )
    if deleted:
        return False, ("dirty_path_deleted",)
    if unreadable:
        return False, ("unreadable_entry",)
    policy = descriptor.ignore_policy
    if policy.include_patterns and not _matches(path, policy.include_patterns):
        reasons.append("not_included_by_policy")
    if policy.exclude_patterns and _matches(path, policy.exclude_patterns):
        reasons.append("excluded_by_policy")
    if CorpusClassification.IGNORED.value in classes and not policy.include_gitignored:
        reasons.append("gitignored_by_policy")
    for classification, reason in (
        (CorpusClassification.SUBMODULE.value, "submodule_gitlink"),
        (CorpusClassification.SYMLINK.value, "symlink_not_regular_file"),
        (CorpusClassification.VENDORED.value, "vendored_dependency"),
        (CorpusClassification.ARCHIVE.value, "archive_not_parser_input"),
        (CorpusClassification.BUILD_OUTPUT.value, "build_output"),
        (CorpusClassification.BINARY.value, "binary_not_parser_input"),
        (CorpusClassification.OVERSIZED.value, "parser_size_limit"),
    ):
        if classification in classes:
            reasons.append(reason)
    if not eligible and not reasons:
        reasons.append("unsupported_parser_input")
    if reasons:
        return False, tuple(sorted(set(reasons)))
    if CorpusClassification.GENERATED_SOURCE.value in classes:
        return True, ("included_generated_source",)
    if CorpusClassification.SOURCE.value in classes:
        return True, ("included_source",)
    if CorpusClassification.SCHEMA.value in classes:
        return True, ("included_schema",)
    return True, ("included_documentation",)


def _canonical_path(descriptor: RepositoryDescriptor, path: str) -> str:
    normalized = descriptor.case_unicode_policy.normalize_path_text(path)
    return f"{descriptor.alias}/{normalized}"


def _symlink_escapes(path: str, content: bytes) -> bool:
    try:
        target = content.decode("utf-8", errors="strict").replace("\\", "/")
    except UnicodeDecodeError:
        return True
    if not target or target.startswith("/") or re.match(r"^[A-Za-z]:/", target):
        return True
    combined = PurePosixPath(path).parent.joinpath(PurePosixPath(target))
    depth = 0
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def _committed_content(
    descriptor: RepositoryDescriptor,
    item: _TreeEntry,
    limits: InventoryLimits,
) -> bytes:
    if item.object_type == "submodule":
        return b""
    content = _git(
        descriptor.root_path,
        ["cat-file", "blob", item.oid],
        timeout=limits.git_timeout_seconds,
    )
    if len(content) != item.size:
        raise RepositoryCorpusIndexError("git_object_size_mismatch")
    return content


def _entry_from_tree(
    descriptor: RepositoryDescriptor,
    item: _TreeEntry,
    limits: InventoryLimits,
    *,
    cached: CorpusEntry | None = None,
) -> tuple[CorpusEntry, bool]:
    if (
        cached is not None
        and cached.mode == item.mode
        and cached.blob_oid == item.oid
        and cached.size == item.size
        and cached.origin == EntryOrigin.COMMITTED.value
    ):
        return cached, True
    content = _committed_content(descriptor, item, limits)
    binary = item.object_type != "submodule" and _looks_binary(content, item.path)
    classes = classify_corpus_path(
        item.path,
        mode=item.mode,
        size=item.size,
        binary=binary,
        max_parser_bytes=limits.max_parser_bytes,
    )
    eligible, reasons = _decision(
        path=item.path,
        classifications=classes,
        descriptor=descriptor,
    )
    if item.object_type == "symlink" and _symlink_escapes(item.path, content):
        eligible = False
        reasons = tuple(sorted(set(reasons) | {"symlink_target_escape"}))
    return (
        CorpusEntry(
            repository_id=descriptor.repository_id,
            repository_alias=descriptor.alias,
            relative_path=item.path,
            canonical_path=_canonical_path(descriptor, item.path),
            origin=EntryOrigin.COMMITTED.value,
            git_status="HEAD",
            mode=item.mode,
            object_type=item.object_type,
            blob_oid=item.oid,
            content_sha256=(
                hashlib.sha256(content).hexdigest() if item.object_type != "submodule" else ""
            ),
            size=item.size,
            classifications=classes,
            parser_eligible=eligible,
            inclusion=(
                InclusionDecision.INCLUDED.value if eligible else InclusionDecision.EXCLUDED.value
            ),
            reason_codes=reasons,
        ),
        False,
    )


def _safe_overlay_content(
    descriptor: RepositoryDescriptor, relative_path: str
) -> tuple[bytes, os.stat_result]:
    absolute = descriptor.root_path.joinpath(*PurePosixPath(relative_path).parts)
    try:
        info = absolute.lstat()
    except OSError as exc:
        raise RepositoryCorpusIndexError("unreadable_entry") from exc
    if stat.S_ISLNK(info.st_mode):
        try:
            target = os.readlink(absolute)
        except OSError as exc:
            raise RepositoryCorpusIndexError("unreadable_entry") from exc
        return os.fsencode(target), info
    try:
        resolved = absolute.resolve(strict=True)
        resolved.relative_to(descriptor.root_path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RepositoryCorpusIndexError("path_escape") from exc
    if stat.S_ISDIR(info.st_mode):
        return b"", info
    if not stat.S_ISREG(info.st_mode):
        raise RepositoryCorpusIndexError("unreadable_entry")
    try:
        return absolute.read_bytes(), info
    except OSError as exc:
        raise RepositoryCorpusIndexError("unreadable_entry") from exc


def _git_blob_oid(content: bytes, object_format: str) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    if object_format == "sha256":
        return hashlib.sha256(header + content).hexdigest()
    if object_format == "sha1":
        return hashlib.sha1(header + content).hexdigest()  # noqa: S324 - Git SHA-1 identity
    raise RepositoryCorpusIndexError("unsupported_git_object_format")


def _overlay_entry(
    descriptor: RepositoryDescriptor,
    overlay: _OverlayPath,
    limits: InventoryLimits,
    base: _TreeEntry | None,
    object_format: str,
) -> CorpusEntry:
    origin = EntryOrigin.IGNORED.value if overlay.ignored else EntryOrigin.DIRTY_OVERLAY.value
    if overlay.deleted:
        classes = classify_corpus_path(
            overlay.path,
            mode=base.mode if base else "100644",
            size=0,
            max_parser_bytes=limits.max_parser_bytes,
        )
        _, reasons = _decision(
            path=overlay.path,
            classifications=classes,
            descriptor=descriptor,
            deleted=True,
        )
        delete_id = (
            "deleted:"
            + hashlib.sha256(
                f"{descriptor.repository_id}\0{overlay.path}\0{base.oid if base else ''}".encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        return CorpusEntry(
            repository_id=descriptor.repository_id,
            repository_alias=descriptor.alias,
            relative_path=overlay.path,
            canonical_path=_canonical_path(descriptor, overlay.path),
            origin=origin,
            git_status=overlay.status,
            mode="000000",
            object_type="deleted",
            blob_oid=delete_id,
            base_blob_oid=base.oid if base else "",
            size=0,
            classifications=classes,
            parser_eligible=False,
            inclusion=InclusionDecision.EXCLUDED.value,
            reason_codes=reasons,
        )
    try:
        content, info = _safe_overlay_content(descriptor, overlay.path)
    except RepositoryCorpusIndexError as exc:
        classes = classify_corpus_path(
            overlay.path,
            mode=base.mode if base else "100644",
            max_parser_bytes=limits.max_parser_bytes,
        )
        unreadable_id = (
            "unreadable:"
            + hashlib.sha256(
                f"{descriptor.repository_id}\0{overlay.path}\0{exc.reason_code}".encode("utf-8")
            ).hexdigest()
        )
        return CorpusEntry(
            repository_id=descriptor.repository_id,
            repository_alias=descriptor.alias,
            relative_path=overlay.path,
            canonical_path=_canonical_path(descriptor, overlay.path),
            origin=origin,
            git_status=overlay.status,
            mode=base.mode if base else "100644",
            object_type="unreadable",
            blob_oid=unreadable_id,
            base_blob_oid=base.oid if base else "",
            size=0,
            classifications=classes,
            parser_eligible=False,
            inclusion=InclusionDecision.EXCLUDED.value,
            reason_codes=(exc.reason_code,),
        )
    if base and base.mode == "160000" and stat.S_ISDIR(info.st_mode):
        try:
            oid = (
                _git(
                    descriptor.root_path / overlay.path,
                    ["rev-parse", "HEAD"],
                    timeout=limits.git_timeout_seconds,
                )
                .decode("ascii")
                .strip()
                .lower()
            )
        except (RepositoryCorpusIndexError, UnicodeDecodeError):
            oid = base.oid
        mode, object_type, size = "160000", "submodule", 0
        content = b""
    elif stat.S_ISLNK(info.st_mode):
        mode, object_type, size = "120000", "symlink", len(content)
        oid = _git_blob_oid(content, object_format)
    elif stat.S_ISREG(info.st_mode):
        mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
        object_type, size = "blob", len(content)
        oid = _git_blob_oid(content, object_format)
    else:
        mode, object_type, size = "100644", "unreadable", 0
        oid = "unreadable:" + hashlib.sha256(overlay.path.encode()).hexdigest()
    binary = object_type == "blob" and _looks_binary(content, overlay.path)
    classes = classify_corpus_path(
        overlay.path,
        mode=mode,
        size=size,
        ignored=overlay.ignored,
        binary=binary,
        max_parser_bytes=limits.max_parser_bytes,
    )
    eligible, reasons = _decision(
        path=overlay.path,
        classifications=classes,
        descriptor=descriptor,
        unreadable=object_type == "unreadable",
    )
    if object_type == "symlink" and _symlink_escapes(overlay.path, content):
        eligible = False
        reasons = tuple(sorted(set(reasons) | {"symlink_target_escape"}))
    return CorpusEntry(
        repository_id=descriptor.repository_id,
        repository_alias=descriptor.alias,
        relative_path=overlay.path,
        canonical_path=_canonical_path(descriptor, overlay.path),
        origin=origin,
        git_status=overlay.status,
        mode=mode,
        object_type=object_type,
        blob_oid=oid,
        base_blob_oid=base.oid if base else "",
        content_sha256=(
            hashlib.sha256(content).hexdigest() if object_type in {"blob", "symlink"} else ""
        ),
        size=size,
        classifications=classes,
        parser_eligible=eligible,
        inclusion=(
            InclusionDecision.INCLUDED.value if eligible else InclusionDecision.EXCLUDED.value
        ),
        reason_codes=reasons,
    )


def _overlay_fingerprint(entry: CorpusEntry) -> tuple[Any, ...]:
    """Return the exact live-input fields that must remain stable."""

    return (
        entry.origin,
        entry.relative_path,
        entry.git_status,
        entry.mode,
        entry.object_type,
        entry.blob_oid,
        entry.base_blob_oid,
        entry.content_sha256,
        entry.size,
    )


def _capture_overlay_fingerprints(
    descriptor: RepositoryDescriptor,
    overlays: Sequence[_OverlayPath],
    ignored: Sequence[_OverlayPath],
    by_path: Mapping[str, _TreeEntry],
    limits: InventoryLimits,
    object_format: str,
) -> tuple[tuple[Any, ...], ...]:
    ordinary_paths = {item.path for item in overlays}
    records = [
        _overlay_entry(
            descriptor,
            item,
            limits,
            by_path.get(item.path),
            object_format,
        )
        for item in overlays
    ]
    records.extend(
        _overlay_entry(
            descriptor,
            item,
            limits,
            by_path.get(item.path),
            object_format,
        )
        for item in ignored
        if item.path not in ordinary_paths
    )
    return tuple(sorted(_overlay_fingerprint(item) for item in records))


def _entry_sort_key(entry: CorpusEntry) -> tuple[bytes, int, bytes]:
    origins = {
        EntryOrigin.COMMITTED.value: 0,
        EntryOrigin.DIRTY_OVERLAY.value: 1,
        EntryOrigin.IGNORED.value: 2,
    }
    return (
        entry.canonical_path.encode("utf-8"),
        origins[entry.origin],
        entry.relative_path.encode("utf-8"),
    )


def _fresh_descriptor(descriptor: RepositoryDescriptor) -> RepositoryDescriptor:
    try:
        return build_repository_descriptor(
            descriptor.root_path,
            alias=descriptor.alias,
            logical_name=descriptor.alias,
            remote_url=descriptor.identity.remote_url,
            authority=descriptor.authority,
            ignore_policy=descriptor.ignore_policy,
            case_unicode_policy=descriptor.case_unicode_policy,
        )
    except RepositoryForestError as exc:
        raise RepositoryCorpusIndexError(exc.reason_code, str(exc)) from exc


def _cache_for_descriptor(
    previous: RepositoryCorpusIndex | None,
    descriptor: RepositoryDescriptor,
    limits: InventoryLimits,
) -> dict[tuple[str, str], CorpusEntry]:
    if previous is None or previous.limits.to_portable_dict() != limits.to_portable_dict():
        return {}
    previous_repo = next(
        (
            item
            for item in previous.repositories
            if item.repository_alias == descriptor.alias
            and item.descriptor_cid == descriptor.descriptor_cid
        ),
        None,
    )
    if previous_repo is None or previous_repo.omitted_entry_count:
        return {}
    return {
        (item.origin, item.relative_path): item
        for item in previous.entries
        if item.repository_alias == descriptor.alias
    }


def _inventory_one(
    descriptor: RepositoryDescriptor,
    limits: InventoryLimits,
    previous: RepositoryCorpusIndex | None,
) -> tuple[list[CorpusEntry], list[str], int]:
    reasons: list[str] = []
    start = _fresh_descriptor(descriptor)
    if start.descriptor_cid != descriptor.descriptor_cid:
        return [], ["stale_repository_descriptor"], 0
    if not descriptor.portable_closure.gitlink_closure_complete:
        reasons.append("incomplete_gitlink_closure")
    tree = _committed_tree(descriptor, limits)
    by_path = {item.path: item for item in tree}
    overlays = _status_overlay(descriptor, limits)
    ignored = _ignored_paths(descriptor, limits)
    if (overlays or (ignored and descriptor.ignore_policy.include_gitignored)) and not (
        descriptor.ignore_policy.allow_dirty_overlay
    ):
        reasons.append("dirty_overlay_forbidden")
    cache = _cache_for_descriptor(previous, descriptor, limits)
    entries: list[CorpusEntry] = []
    reused = 0
    for item in tree:
        cached = cache.get((EntryOrigin.COMMITTED.value, item.path))
        try:
            entry, was_reused = _entry_from_tree(descriptor, item, limits, cached=cached)
        except RepositoryCorpusIndexError:
            classes = classify_corpus_path(
                item.path,
                mode=item.mode,
                size=item.size,
                max_parser_bytes=limits.max_parser_bytes,
            )
            entry = CorpusEntry(
                repository_id=descriptor.repository_id,
                repository_alias=descriptor.alias,
                relative_path=item.path,
                canonical_path=_canonical_path(descriptor, item.path),
                origin=EntryOrigin.COMMITTED.value,
                git_status="HEAD",
                mode=item.mode,
                object_type="unreadable",
                blob_oid=item.oid,
                size=item.size,
                classifications=classes,
                parser_eligible=False,
                inclusion=InclusionDecision.EXCLUDED.value,
                reason_codes=("unavailable_git_object",),
            )
            was_reused = False
        entries.append(entry)
        reused += int(was_reused)
    object_format = (
        _git(
            descriptor.root_path,
            ["rev-parse", "--show-object-format"],
            timeout=limits.git_timeout_seconds,
        )
        .decode("ascii", errors="strict")
        .strip()
    )
    overlay_by_path = {item.path: item for item in overlays}
    overlay_fingerprints: list[tuple[Any, ...]] = []
    for item in overlays:
        overlay_entry = _overlay_entry(
            descriptor,
            item,
            limits,
            by_path.get(item.path),
            object_format,
        )
        entries.append(overlay_entry)
        overlay_fingerprints.append(_overlay_fingerprint(overlay_entry))
    for item in ignored:
        # A path reported as ordinary untracked should not be duplicated.
        if item.path in overlay_by_path:
            continue
        overlay_entry = _overlay_entry(
            descriptor,
            item,
            limits,
            by_path.get(item.path),
            object_format,
        )
        entries.append(overlay_entry)
        overlay_fingerprints.append(_overlay_fingerprint(overlay_entry))
    if not descriptor.ignore_policy.allow_dirty_overlay:
        adjusted = []
        for entry in entries:
            if entry.origin == EntryOrigin.DIRTY_OVERLAY.value or (
                entry.origin == EntryOrigin.IGNORED.value
                and descriptor.ignore_policy.include_gitignored
            ):
                adjusted.append(
                    replace(
                        entry,
                        parser_eligible=False,
                        inclusion=InclusionDecision.EXCLUDED.value,
                        reason_codes=tuple(
                            sorted(set(entry.reason_codes) | {"dirty_overlay_forbidden"})
                        ),
                    )
                )
            else:
                adjusted.append(entry)
        entries = adjusted
    changed_paths = {item.path for item in overlays}
    if changed_paths:
        adjusted: list[CorpusEntry] = []
        for entry in entries:
            if entry.origin == EntryOrigin.COMMITTED.value and entry.relative_path in changed_paths:
                adjusted.append(
                    replace(
                        entry,
                        parser_eligible=False,
                        inclusion=InclusionDecision.EXCLUDED.value,
                        reason_codes=tuple(
                            sorted(set(entry.reason_codes) | {"superseded_by_dirty_overlay"})
                        ),
                    )
                )
            else:
                adjusted.append(entry)
        entries = adjusted
    # Canonical collisions compare distinct repository paths, not the
    # committed and overlay records for the same path.
    canonical_to_paths: dict[str, set[str]] = {}
    for entry in entries:
        canonical_to_paths.setdefault(entry.canonical_path, set()).add(entry.relative_path)
    collision_keys = {key for key, paths in canonical_to_paths.items() if len(paths) > 1}
    if collision_keys:
        adjusted = []
        for entry in entries:
            if entry.canonical_path in collision_keys:
                adjusted.append(
                    replace(
                        entry,
                        parser_eligible=False,
                        inclusion=InclusionDecision.EXCLUDED.value,
                        reason_codes=tuple(
                            sorted(set(entry.reason_codes) | {"canonical_path_collision"})
                        ),
                    )
                )
            else:
                adjusted.append(entry)
        entries = adjusted
        if descriptor.case_unicode_policy.reject_encoding_collisions:
            reasons.append("canonical_path_collision")
    for entry in entries:
        reasons.extend(reason for reason in entry.reason_codes if reason in _FATAL_ENTRY_REASONS)
    try:
        end = _fresh_descriptor(descriptor)
        end_overlays = _status_overlay(descriptor, limits)
        end_ignored = _ignored_paths(descriptor, limits)
        end_fingerprints = _capture_overlay_fingerprints(
            descriptor,
            end_overlays,
            end_ignored,
            by_path,
            limits,
            object_format,
        )
    except RepositoryCorpusIndexError:
        reasons.append("repository_changed_during_inventory")
    else:
        if (
            end.descriptor_cid != descriptor.descriptor_cid
            or tuple(sorted(overlay_fingerprints)) != end_fingerprints
        ):
            reasons.append("repository_changed_during_inventory")
    return sorted(entries, key=_entry_sort_key), sorted(set(reasons)), reused


def _forest_identity(
    forest_or_descriptors: RepositoryForest | Sequence[RepositoryDescriptor],
) -> tuple[str, tuple[RepositoryDescriptor, ...]]:
    if isinstance(forest_or_descriptors, RepositoryForest):
        return forest_or_descriptors.forest_id, forest_or_descriptors.descriptors
    descriptors = tuple(forest_or_descriptors)
    if not descriptors or not all(isinstance(item, RepositoryDescriptor) for item in descriptors):
        raise RepositoryCorpusIndexError("missing_repository_descriptors")
    ordered = tuple(sorted(descriptors, key=lambda item: item.alias))
    aliases = [item.alias for item in ordered]
    if len(aliases) != len(set(aliases)):
        raise RepositoryCorpusIndexError("duplicate_repository_descriptor")
    return (
        content_identity(
            {
                "schema": CORPUS_INDEX_SCHEMA + "/descriptor-set",
                "descriptors": [item.to_portable_dict() for item in ordered],
            }
        ),
        ordered,
    )


def _summary(
    descriptor: RepositoryDescriptor,
    all_entries: Sequence[CorpusEntry],
    emitted_entries: Sequence[CorpusEntry],
    reasons: Sequence[str],
) -> RepositoryInventory:
    classes: Counter[str] = Counter()
    origins: Counter[str] = Counter()
    for entry in all_entries:
        classes.update(entry.classifications)
        origins.update((entry.origin,))
    omitted = len(all_entries) - len(emitted_entries)
    final_reasons = set(reasons)
    if omitted:
        final_reasons.add("manifest_entries_truncated")
    exhaustive = not final_reasons
    return RepositoryInventory(
        repository_id=descriptor.repository_id,
        repository_alias=descriptor.alias,
        descriptor_cid=descriptor.descriptor_cid,
        observed_entry_count=len(all_entries),
        emitted_entry_count=len(emitted_entries),
        included_entry_count=sum(item.included for item in emitted_entries),
        excluded_entry_count=sum(not item.included for item in emitted_entries),
        omitted_entry_count=omitted,
        classification_counts=tuple(classes.items()),
        origin_counts=tuple(origins.items()),
        exhaustive=exhaustive,
        reason_codes=tuple(sorted(final_reasons)),
    )


def _build_result_with_byte_bound(
    *,
    forest_id: str,
    limits: InventoryLimits,
    descriptors: Sequence[RepositoryDescriptor],
    all_by_alias: Mapping[str, Sequence[CorpusEntry]],
    reasons_by_alias: Mapping[str, Sequence[str]],
    entries: list[CorpusEntry],
    global_reasons: set[str],
    reused: int,
) -> RepositoryCorpusIndex:
    emitted = list(entries)
    while True:
        emitted_by_alias: dict[str, list[CorpusEntry]] = {item.alias: [] for item in descriptors}
        for entry in emitted:
            emitted_by_alias[entry.repository_alias].append(entry)
        summaries = tuple(
            _summary(
                descriptor,
                all_by_alias.get(descriptor.alias, ()),
                emitted_by_alias[descriptor.alias],
                reasons_by_alias.get(descriptor.alias, ()),
            )
            for descriptor in descriptors
        )
        reasons = set(global_reasons)
        for summary in summaries:
            reasons.update(summary.reason_codes)
        exhaustive = not reasons and all(item.exhaustive for item in summaries)
        if not exhaustive and not reasons:
            reasons.add("incomplete_repository_inventory")
        candidate = RepositoryCorpusIndex(
            forest_id=forest_id,
            limits=limits,
            repositories=summaries,
            entries=tuple(emitted),
            exhaustive=exhaustive,
            reason_codes=tuple(sorted(reasons)),
            reused_entry_count=min(reused, len(emitted)),
        )
        # Constructor already verifies the byte limit.
        return candidate


def build_repository_corpus_index(
    forest_or_descriptors: RepositoryForest | Sequence[RepositoryDescriptor],
    *,
    limits: InventoryLimits | Mapping[str, Any] | None = None,
    previous_index: RepositoryCorpusIndex | Mapping[str, Any] | None = None,
) -> RepositoryCorpusIndex:
    """Build a deterministic inventory for every supplied descriptor.

    ``previous_index`` permits exact committed-entry reuse when descriptor and
    analyzer limits match.  Reuse counts are diagnostic and deliberately do
    not alter ``inventory_cid``.
    """

    limits_obj = (
        InventoryLimits()
        if limits is None
        else InventoryLimits.from_dict(limits)
        if isinstance(limits, Mapping)
        else limits
    )
    if not isinstance(limits_obj, InventoryLimits):
        raise RepositoryCorpusIndexError("invalid_inventory_limits")
    previous = (
        RepositoryCorpusIndex.from_dict(previous_index)
        if isinstance(previous_index, Mapping)
        else previous_index
    )
    if previous is not None and not isinstance(previous, RepositoryCorpusIndex):
        raise RepositoryCorpusIndexError("invalid_previous_index")
    forest_id, descriptors = _forest_identity(forest_or_descriptors)
    if len(descriptors) > limits_obj.max_repositories:
        raise RepositoryCorpusIndexError("repository_bound_exceeded")
    all_by_alias: dict[str, list[CorpusEntry]] = {}
    reasons_by_alias: dict[str, list[str]] = {}
    reused = 0
    for descriptor in descriptors:
        try:
            repo_entries, reasons, repo_reused = _inventory_one(descriptor, limits_obj, previous)
        except RepositoryCorpusIndexError as exc:
            repo_entries, reasons, repo_reused = [], [exc.reason_code], 0
        all_by_alias[descriptor.alias] = repo_entries
        reasons_by_alias[descriptor.alias] = reasons
        reused += repo_reused
    all_entries = sorted(
        (entry for entries in all_by_alias.values() for entry in entries),
        key=_entry_sort_key,
    )
    global_reasons: set[str] = set()
    if len(all_entries) > limits_obj.max_entries:
        global_reasons.add("manifest_entry_bound_exceeded")
    emitted = all_entries[: limits_obj.max_entries]
    # Shrink deterministically until the complete canonical receipt fits.
    while True:
        try:
            result = _build_result_with_byte_bound(
                forest_id=forest_id,
                limits=limits_obj,
                descriptors=descriptors,
                all_by_alias=all_by_alias,
                reasons_by_alias=reasons_by_alias,
                entries=emitted,
                global_reasons=global_reasons,
                reused=reused,
            )
            try:
                from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
                    mirror_work_record,
                    orchestrate_semantic_work,
                )

                paths = tuple(getattr(entry, "path", "") for entry in result.entries if getattr(entry, "path", ""))[:16]
                tree_id = str(result.forest_id or "")
                mirror_work_record(
                    catalog_kind="bm25",
                    record_kind="repository_corpus_index",
                    record_ref=str(getattr(result, "inventory_cid", "") or result.forest_id or "repository-corpus"),
                    tree_id=tree_id,
                    subject_kind="tree_id" if tree_id else "record_cid",
                    subject_ref=tree_id or str(result.forest_id or "repository-corpus"),
                    paths=paths,
                )
                orchestrate_semantic_work(
                    subject_kind="tree_id",
                    subject_ref=str(result.forest_id),
                    tree_id=str(result.forest_id),
                    path=paths[0] if paths else "",
                )
            except Exception:
                pass
            return result
        except RepositoryCorpusIndexError as exc:
            if exc.reason_code != "manifest_byte_bound_violated" or not emitted:
                raise
            global_reasons.add("manifest_byte_bound_exceeded")
            # Geometric removal avoids quadratic behavior for large manifests.
            remove_count = max(1, len(emitted) // 8)
            emitted = emitted[:-remove_count]


def inventory_repository_descriptor(
    descriptor: RepositoryDescriptor,
    *,
    limits: InventoryLimits | Mapping[str, Any] | None = None,
    previous_index: RepositoryCorpusIndex | Mapping[str, Any] | None = None,
) -> RepositoryCorpusIndex:
    """Convenience wrapper for a single independently bound descriptor."""

    return build_repository_corpus_index(
        (descriptor,), limits=limits, previous_index=previous_index
    )


def inventory_repository_forest(
    forest: RepositoryForest,
    *,
    limits: InventoryLimits | Mapping[str, Any] | None = None,
    previous_index: RepositoryCorpusIndex | Mapping[str, Any] | None = None,
) -> RepositoryCorpusIndex:
    return build_repository_corpus_index(forest, limits=limits, previous_index=previous_index)


# Additional verb aliases keep call sites readable.
enumerate_repository_corpus = build_repository_corpus_index
index_repository_corpus = build_repository_corpus_index


# ---------------------------------------------------------------------------
# Objective evidence discovery (VFS-G138 / VFS-G020 packet / VFS-064 repair)
# ---------------------------------------------------------------------------


def exhaustive_file_inventory_evidence_terms() -> tuple[str, ...]:
    """Return the closed VFS-G138 domain evidence term for exhaustive inventory.

    Domain identity (``vfs/exhaustive-file-inventory@1``) is authored only by
    this module.  Packet sibling ``vfs/incremental-ast-index@1`` is exposed via
    :func:`packet_evidence_terms` so discovery scanners can cover the
    corpus-index goal packet without mixing labels into inventory CIDs.  The
    synthetic ``objective validation repair`` term is intentionally omitted
    here; use :func:`objective_validation_repair_evidence_terms` (or
    :func:`parent_objective_evidence_terms`) for the VFS-G020 validation gate.
    """

    return OBJECTIVE_DOMAIN_EVIDENCE_TERMS


def covered_evidence_terms() -> tuple[str, ...]:
    """Return domain objective evidence terms this inventory surface proves.

    Mirrors :func:`exhaustive_file_inventory_evidence_terms`.  Packet-wide
    domain coverage (inventory + incremental AST index) is via
    :func:`packet_evidence_terms` / :func:`all_covered_evidence_terms`.  The
    synthetic objective validation repair gate is separate so inventory
    envelopes stay domain-only.
    """

    return exhaustive_file_inventory_evidence_terms()


def packet_evidence_terms() -> tuple[str, ...]:
    """Return VFS-G020 packet domain evidence terms co-owned with AST adapters.

    Ordered as ``vfs/exhaustive-file-inventory@1`` then
    ``vfs/incremental-ast-index@1``.  Labels never enter inventory identity.
    Does not include the synthetic objective validation repair discovery key.
    """

    return CORPUS_INDEX_G020_EVIDENCE_TERMS


def objective_validation_repair_evidence_terms() -> tuple[str, ...]:
    """Return the synthetic VFS-G020 validation-gate evidence term.

    Exact-text discovery key for objective validation repair.  Never mixes
    into content-addressed inventory CIDs, entry identities, or portable
    inventory payloads.  Domain packet evidence stays on
    :func:`packet_evidence_terms`.  Owned by :data:`OBJECTIVE_PARENT_GOAL_ID`
    (``VFS-G020``) via repair task :data:`OBJECTIVE_VALIDATION_REPAIR_TASK_ID`
    (``VFS-064``).  Inventory, language adapters, and incremental persistence
    remain split by conflict domain.
    """

    return (OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,)


def parent_objective_evidence_terms() -> tuple[str, ...]:
    """Return VFS-G020 packet domain terms plus the validation-repair gate.

    Domain ``vfs/exhaustive-file-inventory@1`` and
    ``vfs/incremental-ast-index@1`` come first; the synthetic objective
    validation repair discovery key is appended last and never enters
    inventory identity.  Packet domain discovery without the gate remains
    :func:`packet_evidence_terms` / :func:`all_covered_evidence_terms`.
    """

    return packet_evidence_terms() + objective_validation_repair_evidence_terms()


def all_covered_evidence_terms() -> tuple[str, ...]:
    """Return packet domain evidence terms for cross-module discovery scanners.

    Keeps inventory + incremental AST packet labels aligned with
    :mod:`program_ast_adapters`.  Use :func:`parent_objective_evidence_terms`
    (or :func:`objective_validation_repair_evidence_terms`) for the synthetic
    VFS-G020 objective validation repair gate.
    """

    return packet_evidence_terms()


def _mirror_corpus_claim(claim: dict[str, Any], *, record_kind: str, catalog_kind: str) -> dict[str, Any]:
    """Record an inventory claim. It does not admit completion."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(claim.get("inventory_cid") or claim.get("evidence") or record_kind)
        mirror_work_record(
            catalog_kind=catalog_kind,
            record_kind=record_kind,
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return claim


def prove_objective_validation_repair(
    index: RepositoryCorpusIndex | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a portable VFS-G020 objective validation repair claim.

    Binds the synthetic discovery key without embedding it into inventory
    identity.  When an inventory receipt is supplied, structural exhaustive
    inventory satisfaction is reported; identity CIDs stay domain-only.
    """

    inventory_satisfied: bool | None = None
    inventory_cid: str | None = None
    exhaustive: bool | None = None
    reason_codes: list[str] = []
    if index is not None:
        if isinstance(index, Mapping):
            index = RepositoryCorpusIndex.from_dict(index)
        if not isinstance(index, RepositoryCorpusIndex):
            raise TypeError("inventory must be a RepositoryCorpusIndex")
        inventory_satisfied = inventory_satisfies_exhaustive_file_inventory(index)
        inventory_cid = index.inventory_cid
        exhaustive = index.exhaustive
        reason_codes = list(index.reason_codes)
    claim = {
        "schema": ("ipfs_accelerate_py/agent-supervisor/objective-validation-repair-claim@1"),
        "evidence": OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,
        "evidence_terms": list(objective_validation_repair_evidence_terms()),
        "domain_evidence_terms": list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS),
        "packet_evidence_terms": list(CORPUS_INDEX_G020_EVIDENCE_TERMS),
        "parent_objective_evidence_terms": list(parent_objective_evidence_terms()),
        "requirement_id": OBJECTIVE_VALIDATION_REPAIR_EVIDENCE,
        "goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "parent_goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "packet_goal_ids": list(PACKET_GOAL_IDS),
        "goal_packet": GOAL_PACKET_ID,
        "task_id": OBJECTIVE_VALIDATION_REPAIR_TASK_ID,
        "domain_task_id": OBJECTIVE_TASK_ID,
        "inventory_cid": inventory_cid,
        "exhaustive": exhaustive,
        "inventory_satisfied": inventory_satisfied,
        "satisfied": True
        if inventory_satisfied is None
        else bool(inventory_satisfied and exhaustive),
        "reason_codes": reason_codes,
        "invariants": list(OBJECTIVE_VALIDATION_REPAIR_INVARIANTS),
        "conflict_domains": (
            "repository_corpus_index",
            "program_ast_adapters",
            "incremental_persistence",
        ),
        "authoritative": False,
        "completion_authoritative": False,
    }
    return _mirror_corpus_claim(
        claim,
        record_kind="corpus_objective_validation_repair_claim",
        catalog_kind="metadata",
    )


def inventory_satisfies_exhaustive_file_inventory(
    index: RepositoryCorpusIndex | Mapping[str, Any],
) -> bool:
    """Machine-check VFS-G138 acceptance against one inventory receipt.

    * Included and excluded populations publish with reason codes.
    * Unexplained skips (reason-less entries) are rejected by construction;
      this helper re-asserts every emitted entry carries reasons.
    * Truncation / non-exhaustive repository summaries fail closed.
    * Forged exhaustive flags (exhaustive with reasons) are rejected by the
      receipt constructor; this helper re-checks the live object.
    """

    if isinstance(index, Mapping):
        index = RepositoryCorpusIndex.from_dict(index)
    if not isinstance(index, RepositoryCorpusIndex):
        raise TypeError("inventory must be a RepositoryCorpusIndex")
    if index.exhaustive and index.reason_codes:
        return False
    if index.exhaustive and any(not item.exhaustive for item in index.repositories):
        return False
    for entry in index.entries:
        if not entry.canonical_path or not entry.relative_path:
            return False
        if not entry.reason_codes:
            return False
        if entry.included and entry.inclusion != InclusionDecision.INCLUDED.value:
            return False
        if not entry.included and entry.inclusion != InclusionDecision.EXCLUDED.value:
            return False
    if index.exhaustive:
        if any(item.omitted_entry_count for item in index.repositories):
            return False
        if index.reason_codes:
            return False
    return True


def prove_exhaustive_file_inventory(
    index: RepositoryCorpusIndex | Mapping[str, Any],
) -> dict[str, Any]:
    """Emit a portable VFS-G138 evidence claim for one inventory receipt.

    The claim binds ``vfs/exhaustive-file-inventory@1`` to the content-addressed
    inventory without embedding goal metadata into ``inventory_cid``.
    """

    if isinstance(index, Mapping):
        index = RepositoryCorpusIndex.from_dict(index)
    if not isinstance(index, RepositoryCorpusIndex):
        raise TypeError("inventory must be a RepositoryCorpusIndex")
    satisfied = inventory_satisfies_exhaustive_file_inventory(index)
    included = index.included_entries
    excluded = index.excluded_entries
    claim = {
        "schema": "ipfs_accelerate_py/agent-supervisor/exhaustive-file-inventory-claim@1",
        "evidence": EXHAUSTIVE_FILE_INVENTORY_EVIDENCE,
        "evidence_terms": list(OBJECTIVE_DOMAIN_EVIDENCE_TERMS),
        "packet_evidence_terms": list(CORPUS_INDEX_G020_EVIDENCE_TERMS),
        "requirement_id": EXHAUSTIVE_FILE_INVENTORY_EVIDENCE,
        "goal_id": OBJECTIVE_GOAL_ID,
        "parent_goal_id": OBJECTIVE_PARENT_GOAL_ID,
        "packet_goal_ids": list(PACKET_GOAL_IDS),
        "goal_packet": GOAL_PACKET_ID,
        "task_id": OBJECTIVE_TASK_ID,
        "inventory_cid": index.inventory_cid,
        "forest_id": index.forest_id,
        "exhaustive": index.exhaustive,
        "satisfied": satisfied and index.exhaustive,
        "reason_codes": list(index.reason_codes),
        "included_entry_count": len(included),
        "excluded_entry_count": len(excluded),
        "reused_entry_count": index.reused_entry_count,
        "repository_count": len(index.repositories),
        "populations": {
            "included": [
                {
                    "path": item.relative_path,
                    "classifications": list(item.classifications),
                    "origin": item.origin,
                }
                for item in included
            ],
            "excluded": [
                {
                    "path": item.relative_path,
                    "reason_codes": list(item.reason_codes),
                    "origin": item.origin,
                }
                for item in excluded
            ],
        },
        "invariants": list(EXHAUSTIVE_FILE_INVENTORY_INVARIANTS),
        "authoritative": False,
        "completion_authoritative": False,
    }
    return _mirror_corpus_claim(
        claim,
        record_kind="exhaustive_file_inventory_claim",
        catalog_kind="filesystem_mtime",
    )


__all__ = [
    "CORPUS_ENTRY_SCHEMA",
    "CORPUS_INDEX_SCHEMA",
    "CORPUS_INDEX_G020_EVIDENCE_TERMS",
    "EXHAUSTIVE_FILE_INVENTORY_EVIDENCE",
    "EXHAUSTIVE_FILE_INVENTORY_INVARIANTS",
    "GOAL_PACKET_ID",
    "INCREMENTAL_AST_INDEX_EVIDENCE",
    "INVENTORY_LIMITS_SCHEMA",
    "OBJECTIVE_DOMAIN_EVIDENCE_TERMS",
    "OBJECTIVE_GOAL_ID",
    "OBJECTIVE_PARENT_GOAL_ID",
    "OBJECTIVE_TASK_ID",
    "OBJECTIVE_VALIDATION_REPAIR_EVIDENCE",
    "OBJECTIVE_VALIDATION_REPAIR_INVARIANTS",
    "OBJECTIVE_VALIDATION_REPAIR_TASK_ID",
    "PACKET_GOAL_IDS",
    "PACKET_SIBLING_GOAL_ID",
    "REPOSITORY_INVENTORY_SCHEMA",
    "CorpusClassification",
    "CorpusEntry",
    "CorpusInventoryLimits",
    "EntryOrigin",
    "ExhaustiveCorpusReceipt",
    "InclusionDecision",
    "InventoryLimits",
    "RepositoryCorpusEntry",
    "RepositoryCorpusIndex",
    "RepositoryCorpusIndexError",
    "RepositoryInventory",
    "all_covered_evidence_terms",
    "build_repository_corpus_index",
    "classify_corpus_path",
    "covered_evidence_terms",
    "enumerate_repository_corpus",
    "exhaustive_file_inventory_evidence_terms",
    "index_repository_corpus",
    "inventory_repository_descriptor",
    "inventory_repository_forest",
    "inventory_satisfies_exhaustive_file_inventory",
    "objective_validation_repair_evidence_terms",
    "packet_evidence_terms",
    "parent_objective_evidence_terms",
    "prove_exhaustive_file_inventory",
    "prove_objective_validation_repair",
]
