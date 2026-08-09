"""Bounded, streaming inventory of file-authoritative producers (DQK-001).

This module classifies paths under dataset and agent-supervisor trees into the
closed kind set required by the DuckDB control-plane rollout:

* authored documentation
* mutable state
* immutable evidence
* derived exports
* unsafe serialization

The scanner is deliberately **streaming** and **deterministic**:

* files are walked depth-first with lexicographically sorted directory entries;
* digests are computed with a fixed-size chunked SHA-256 read so multi-hundred
  megabyte corpora (including the ~970 MB production-hardening fixture) never
  need to be loaded into memory as a single buffer;
* every yielded :class:`InventoryRecord` carries ``path``, ``kind``, ``size``,
  ``digest``, ``producer``, ``consumer``, and ``proposed_authority``.

Importing this module is side-effect free.  No DuckDB connection is opened and
no optional extensions are loaded.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)

__all__ = [
    "DEFAULT_DIGEST_CHUNK_SIZE",
    "DEFAULT_SKIP_DIR_NAMES",
    "INVENTORY_SCHEMA",
    "InventoryError",
    "InventoryKind",
    "InventoryRecord",
    "InventoryRegistry",
    "InventorySnapshot",
    "ProposedAuthority",
    "classify_path",
    "digest_file",
    "iter_inventory",
    "scan_inventory",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

INVENTORY_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-inventory@1"

# 1 MiB keeps peak read buffers far below the multi-hundred-MB production
# hardening corpus while remaining efficient on modern disks.
DEFAULT_DIGEST_CHUNK_SIZE: Final[int] = 1024 * 1024

DEFAULT_SKIP_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".eggs",
        "*.egg-info",  # matched by exact name only; egg-info dirs use suffix rule
    }
)

_SKIP_DIR_SUFFIXES: Final[tuple[str, ...]] = (".egg-info",)

_DIGEST_PREFIX: Final[str] = "sha256:"


class InventoryError(ValueError):
    """Raised when inventory inputs, records, or configuration are invalid."""


class InventoryKind(str, Enum):
    """Closed classification of file-authoritative producers."""

    AUTHORED_DOCUMENTATION = "authored_documentation"
    MUTABLE_STATE = "mutable_state"
    IMMUTABLE_EVIDENCE = "immutable_evidence"
    DERIVED_EXPORT = "derived_export"
    UNSAFE_SERIALIZATION = "unsafe_serialization"


class ProposedAuthority(str, Enum):
    """Where authority for a classified path should move after cutover.

    Values intentionally align with the control-plane catalog families and the
    plan's export-only / quarantine outcomes for legacy files.
    """

    GIT_DOCUMENTATION = "git_documentation"
    DUCKDB_CONTROL = "duckdb:control"
    DUCKDB_META = "duckdb:meta"
    DUCKDB_OBSERVABILITY = "duckdb:observability"
    DUCKDB_GRAPHS = "duckdb:graphs"
    DUCKDB_PROOFS = "duckdb:proofs"
    DUCKDB_VECTORS = "duckdb:vectors"
    DUCKDB_WALLET = "duckdb:wallet"
    DUCKDB_ASTS = "duckdb:asts"
    DUCKLAKE_PARQUET = "ducklake:parquet"
    IPLD_CAR = "ipld_car"
    OBJECT_STORAGE = "object_storage"
    EXPORT_PROJECTION = "export_projection"
    RETAIN_IMMUTABLE = "retain_immutable"
    QUARANTINE = "quarantine"


# ---------------------------------------------------------------------------
# Record / snapshot types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    """One inventoried file with full classification metadata.

    Required fields match DQK-001 acceptance: path, kind, size, digest,
    producer, consumer, and proposed_authority.
    """

    path: str
    kind: InventoryKind
    size: int
    digest: str
    producer: str
    consumer: str
    proposed_authority: ProposedAuthority
    root: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise InventoryError("path must be a non-empty string")
        if "\\" in self.path:
            raise InventoryError("path must use POSIX separators")
        if not isinstance(self.kind, InventoryKind):
            object.__setattr__(self, "kind", InventoryKind(self.kind))
        if not isinstance(self.proposed_authority, ProposedAuthority):
            object.__setattr__(
                self,
                "proposed_authority",
                ProposedAuthority(self.proposed_authority),
            )
        if not isinstance(self.size, int) or self.size < 0:
            raise InventoryError("size must be a non-negative int")
        if not isinstance(self.digest, str) or not self.digest.startswith(
            _DIGEST_PREFIX
        ):
            raise InventoryError(
                f"digest must start with {_DIGEST_PREFIX!r}, got {self.digest!r}"
            )
        hex_part = self.digest[len(_DIGEST_PREFIX) :]
        if len(hex_part) != 64 or any(
            character not in "0123456789abcdef" for character in hex_part
        ):
            raise InventoryError(f"digest must be sha256 hex, got {self.digest!r}")
        for name in ("producer", "consumer"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise InventoryError(f"{name} must be a non-empty string")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "kind": self.kind.value,
                "size": self.size,
                "digest": self.digest,
                "producer": self.producer,
                "consumer": self.consumer,
                "proposed_authority": self.proposed_authority.value,
                "root": self.root,
            }
        )


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    """Deterministic aggregate over a completed inventory stream."""

    schema: str
    roots: tuple[str, ...]
    record_count: int
    total_bytes: int
    kind_counts: Mapping[str, int]
    snapshot_digest: str
    records: tuple[InventoryRecord, ...] = field(default_factory=tuple)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "roots": list(self.roots),
                "record_count": self.record_count,
                "total_bytes": self.total_bytes,
                "kind_counts": dict(self.kind_counts),
                "snapshot_digest": self.snapshot_digest,
            }
        )


# ---------------------------------------------------------------------------
# Classification tables
# ---------------------------------------------------------------------------

_UNSAFE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".pkl",
        ".pickle",
        ".joblib",
        ".dill",
        ".p",
        ".npy",
        ".npz",
        ".pt",
        ".pth",
        ".ckpt",
        ".safetensors",  # binary model weights are not control-plane authority
        ".msgpack",
        ".bin",  # ambiguous binary blobs treated as unsafe until typed
    }
)

_EVIDENCE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".car",
        ".cid",
        ".parquet",
        ".arrow",
        ".feather",
        ".orc",
    }
)

_MUTABLE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".duckdb",
        ".wal",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".pid",
        ".lock",
        ".tmp",
        ".temp",
    }
)

_DOC_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".md",
        ".rst",
        ".adoc",
        ".txt",
        ".markdown",
    }
)

_EXPORT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".csv",
        ".tsv",
        ".ndjson",
    }
)

# Directory / path segment tokens (matched as whole path parts, case-folded).
_MUTABLE_DIR_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "state",
        "checkpoints",
        "checkpoint",
        "worktrees",
        "worktree",
        "leases",
        "heartbeats",
        "locks",
        "cache",
        "tmp",
        "temp",
        "runtime",
        "queues",
        "queue",
        "logs",
        "merge-queue",
        "merge_queue",
        "implementation_checkpoints",
        "implementation_logs",
        "task_queue",
    }
)

_EVIDENCE_DIR_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "receipts",
        "evidence",
        "attestations",
        "proofs",
        "scan_receipts",
        "merge_receipts",
        "acceptance_evidence",
        "parity",
        "cids",
        "ipld",
        "car",
        "fixtures",
        "golden",
        "corpus",
        "production_hardening",
        "knowledge_graphs_production_hardening",
    }
)

_EXPORT_DIR_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "export",
        "exports",
        "projection",
        "projections",
        "derived",
        "generated",
        "reports",
        "report",
        "publish",
        "publication",
        "snapshots",  # derived DB snapshots for external consumers
    }
)

_DOC_DIR_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "docs",
        "doc",
        "documentation",
        "guides",
        "architecture",
        "runbooks",
        "plans",
        "discovery",
        "readme",
    }
)

_EVIDENCE_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(receipt|evidence|attestation|parity|digest|checksum|cid[-_]?|"
    r"content[-_]?id|manifest|seal|fingerprint)",
    re.IGNORECASE,
)

_MUTABLE_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(status|queue|lease|heartbeat|checkpoint|cursor|lock|pid|"
    r"events?\.jsonl|task[_-]?state|task[_-]?queue|control\.duckdb|"
    r"\.wal$|supervisor[_-]?status|daemon)",
    re.IGNORECASE,
)

_EXPORT_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(export|projection|derived|generated|report|publish)",
    re.IGNORECASE,
)

_UNSAFE_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(pickle|joblib|cloudpickle|dill|torch[_-]?save|numpy[_-]?save)",
    re.IGNORECASE,
)

# Producer / consumer resolution from leading path segments.
_PRODUCER_RULES: Final[tuple[tuple[tuple[str, ...], str, str], ...]] = (
    (("data", "agent_supervisor"), "agent_supervisor", "control_plane"),
    (("ipfs_accelerate_py", "agent_supervisor"), "agent_supervisor", "control_plane"),
    (("agent_supervisor",), "agent_supervisor", "control_plane"),
    (("ipfs_datasets_py", "knowledge_graphs"), "knowledge_graphs", "graph_query"),
    (("knowledge_graphs",), "knowledge_graphs", "graph_query"),
    (("ipfs_datasets_py", "vector_stores"), "vector_stores", "vector_query"),
    (("vector_stores",), "vector_stores", "vector_query"),
    (("ipfs_datasets_py", "wallet"), "wallet", "wallet_query"),
    (("wallet",), "wallet", "wallet_query"),
    (("ipfs_datasets_py", "processors", "wallets"), "wallet_processors", "wallet_query"),
    (("ipfs_datasets_py", "logic"), "logic", "proof_query"),
    (("proofs",), "proofs", "proof_query"),
    (("security_ir",), "security_ir", "verification"),
    (("security_ir_artifacts",), "security_ir", "verification"),
    (("docs",), "documentation", "human_reader"),
    (("tests",), "tests", "validation"),
    (("benchmarks",), "benchmarks", "performance"),
    (("archive",), "archive", "historical_reference"),
    (("data",), "datasets", "dataset_loader"),
    (("ipfs_datasets_py",), "ipfs_datasets_py", "library_consumer"),
    (("scripts",), "scripts", "operator"),
)


# ---------------------------------------------------------------------------
# Digest (streaming)
# ---------------------------------------------------------------------------


def digest_file(
    path: str | Path,
    *,
    chunk_size: int = DEFAULT_DIGEST_CHUNK_SIZE,
) -> tuple[int, str]:
    """Return ``(size_bytes, 'sha256:<hex>')`` by streaming ``path``.

    Never loads the full file into memory.  ``chunk_size`` must be a positive
    integer; the default is sized for the multi-hundred-megabyte production
    hardening corpus.
    """

    if chunk_size <= 0:
        raise InventoryError("chunk_size must be a positive integer")
    target = Path(path)
    if not target.is_file() and not target.is_symlink():
        # is_file() follows symlinks; reject missing / non-regular paths.
        if not target.exists():
            raise InventoryError(f"path does not exist: {target}")
        raise InventoryError(f"path is not a regular file: {target}")

    hasher = hashlib.sha256()
    size = 0
    # Open without following symlinks for the open() call itself when possible;
    # pathlib read still opens the final target for regular files.
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
    return size, f"{_DIGEST_PREFIX}{hasher.hexdigest()}"


def _digest_bytes(data: bytes) -> str:
    return f"{_DIGEST_PREFIX}{hashlib.sha256(data).hexdigest()}"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _posix_relative(path: str) -> str:
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _parts(relative_path: str) -> tuple[str, ...]:
    pure = PurePosixPath(_posix_relative(relative_path))
    return tuple(part for part in pure.parts if part not in ("", "."))


def _suffix(relative_path: str) -> str:
    name = PurePosixPath(_posix_relative(relative_path)).name
    if name.startswith(".") and name.count(".") == 1:
        return name.lower()
    return PurePosixPath(name).suffix.lower()


def _name(relative_path: str) -> str:
    return PurePosixPath(_posix_relative(relative_path)).name


def _folded_parts(relative_path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in _parts(relative_path))


def resolve_producer_consumer(relative_path: str) -> tuple[str, str]:
    """Map a relative path to ``(producer, consumer)`` labels."""

    parts = _folded_parts(relative_path)
    for prefix, producer, consumer in _PRODUCER_RULES:
        prefix_folded = tuple(item.casefold() for item in prefix)
        if len(parts) >= len(prefix_folded) and parts[: len(prefix_folded)] == prefix_folded:
            return producer, consumer
        # Also match the prefix anywhere as a contiguous segment for nested
        # supervisor / dataset checkouts.
        if len(prefix_folded) == 1 and prefix_folded[0] in parts:
            return producer, consumer
        for index in range(len(parts) - len(prefix_folded) + 1):
            if parts[index : index + len(prefix_folded)] == prefix_folded:
                return producer, consumer
    return "unknown", "unknown"


def _parts_match_tokens(
    parts: Sequence[str],
    tokens: frozenset[str],
) -> bool:
    """Return True when any path part equals or embeds a classification token."""

    for part in parts:
        if part in tokens:
            return True
        for token in tokens:
            if len(token) < 3:
                # Avoid short-token false positives (e.g. ``car`` in ``scar``).
                continue
            if (
                part.startswith(f"{token}_")
                or part.startswith(f"{token}-")
                or part.endswith(f"_{token}")
                or part.endswith(f"-{token}")
                or f"_{token}_" in f"_{part}_"
                or f"-{token}-" in f"-{part}-"
            ):
                return True
    return False


def _authority_for(
    kind: InventoryKind,
    relative_path: str,
) -> ProposedAuthority:
    parts = _folded_parts(relative_path)
    joined = "/".join(parts)

    if kind is InventoryKind.UNSAFE_SERIALIZATION:
        return ProposedAuthority.QUARANTINE

    if kind is InventoryKind.AUTHORED_DOCUMENTATION:
        return ProposedAuthority.GIT_DOCUMENTATION

    if kind is InventoryKind.DERIVED_EXPORT:
        if any(part.endswith(".parquet") or part == "parquet" for part in parts) or joined.endswith(
            ".parquet"
        ):
            return ProposedAuthority.DUCKLAKE_PARQUET
        return ProposedAuthority.EXPORT_PROJECTION

    if kind is InventoryKind.IMMUTABLE_EVIDENCE:
        suffix = _suffix(relative_path)
        if suffix in {".car", ".cid"} or "ipld" in parts or "car" in parts:
            return ProposedAuthority.IPLD_CAR
        if suffix in {".parquet", ".arrow", ".feather", ".orc"}:
            return ProposedAuthority.DUCKLAKE_PARQUET
        if "proof" in joined or "proofs" in parts:
            return ProposedAuthority.DUCKDB_PROOFS
        return ProposedAuthority.RETAIN_IMMUTABLE

    # mutable_state → domain-specific DuckDB catalog when possible
    if "wallet" in parts or "wallets" in parts:
        return ProposedAuthority.DUCKDB_WALLET
    if "vector" in joined or "embeddings" in parts:
        return ProposedAuthority.DUCKDB_VECTORS
    if "proof" in joined or "proofs" in parts or "logic" in parts:
        return ProposedAuthority.DUCKDB_PROOFS
    if "graph" in joined or "knowledge_graphs" in parts:
        return ProposedAuthority.DUCKDB_GRAPHS
    if "ast" in parts or "asts" in parts:
        return ProposedAuthority.DUCKDB_ASTS
    if "audit" in parts or "observability" in parts or "metrics" in parts:
        return ProposedAuthority.DUCKDB_OBSERVABILITY
    if "meta" in parts or "schema" in parts or "migration" in joined:
        return ProposedAuthority.DUCKDB_META
    return ProposedAuthority.DUCKDB_CONTROL


def classify_path(relative_path: str) -> tuple[
    InventoryKind,
    str,
    str,
    ProposedAuthority,
]:
    """Classify ``relative_path`` into kind, producer, consumer, authority.

    Classification is pure and deterministic: it depends only on the relative
    path string (POSIX form).  Order of precedence:

    1. unsafe serialization (pickle / joblib / binary weight formats)
    2. immutable evidence (receipts, CIDs, CAR, golden fixtures, corpus)
    3. mutable state (supervisor state, DuckDB files, locks, queues)
    4. derived exports (export/projection/report trees)
    5. authored documentation (docs, markdown, discovery notes)
    6. conservative fallback to mutable state for operational JSON/YAML/JSONL,
       otherwise authored documentation for remaining source-like files
    """

    relative = _posix_relative(relative_path)
    if not relative:
        raise InventoryError("relative_path must be non-empty")

    parts = _folded_parts(relative)
    name = _name(relative)
    name_folded = name.casefold()
    suffix = _suffix(relative)
    producer, consumer = resolve_producer_consumer(relative)

    # 1. Unsafe serialization -------------------------------------------------
    if suffix in _UNSAFE_SUFFIXES or _UNSAFE_NAME_RE.search(name):
        kind = InventoryKind.UNSAFE_SERIALIZATION
        return kind, producer, consumer, _authority_for(kind, relative)

    # 2. Immutable evidence ---------------------------------------------------
    if (
        suffix in _EVIDENCE_SUFFIXES
        or _parts_match_tokens(parts, _EVIDENCE_DIR_TOKENS)
        or _EVIDENCE_NAME_RE.search(name)
        or _EVIDENCE_NAME_RE.search(relative)
    ):
        # Parquet under export/projection directories is a derived export, not
        # retained evidence — check before committing to evidence.
        if suffix == ".parquet" and _parts_match_tokens(parts, _EXPORT_DIR_TOKENS):
            kind = InventoryKind.DERIVED_EXPORT
            return kind, producer, consumer, _authority_for(kind, relative)
        kind = InventoryKind.IMMUTABLE_EVIDENCE
        return kind, producer, consumer, _authority_for(kind, relative)

    # 3. Mutable state --------------------------------------------------------
    if (
        suffix in _MUTABLE_SUFFIXES
        or _parts_match_tokens(parts, _MUTABLE_DIR_TOKENS)
        or _MUTABLE_NAME_RE.search(name)
        or name_folded in {"task_queue.json", "control.duckdb", "status.json"}
        or name_folded.endswith(".jsonl")
    ):
        kind = InventoryKind.MUTABLE_STATE
        return kind, producer, consumer, _authority_for(kind, relative)

    # 4. Derived exports ------------------------------------------------------
    if (
        _parts_match_tokens(parts, _EXPORT_DIR_TOKENS)
        or _EXPORT_NAME_RE.search(name)
        or suffix in _EXPORT_SUFFIXES
    ):
        kind = InventoryKind.DERIVED_EXPORT
        return kind, producer, consumer, _authority_for(kind, relative)

    # 5. Authored documentation -----------------------------------------------
    if (
        suffix in _DOC_SUFFIXES
        or _parts_match_tokens(parts, _DOC_DIR_TOKENS)
        or name_folded in {"readme", "readme.md", "changelog.md", "contributing.md", "license"}
        or name_folded.startswith("readme.")
    ):
        kind = InventoryKind.AUTHORED_DOCUMENTATION
        return kind, producer, consumer, _authority_for(kind, relative)

    # 6. Fallbacks ------------------------------------------------------------
    # Operational structured config that still acts as file authority.
    if suffix in {".json", ".yaml", ".yml", ".toml"} and any(
        token in parts
        for token in (
            "config",
            "configs",
            "state",
            "data",
            "agent_supervisor",
            "control",
        )
    ):
        kind = InventoryKind.MUTABLE_STATE
        return kind, producer, consumer, _authority_for(kind, relative)

    # Source and remaining assets are treated as authored git content rather
    # than operational authority.
    kind = InventoryKind.AUTHORED_DOCUMENTATION
    return kind, producer, consumer, _authority_for(kind, relative)


# ---------------------------------------------------------------------------
# Deterministic walk + streaming inventory
# ---------------------------------------------------------------------------


def _should_skip_dir(name: str, skip_dir_names: frozenset[str]) -> bool:
    if name in skip_dir_names:
        return True
    return any(name.endswith(suffix) for suffix in _SKIP_DIR_SUFFIXES)


def _iter_files_deterministic(
    root: Path,
    *,
    skip_dir_names: frozenset[str],
    follow_symlinks: bool,
) -> Iterator[Path]:
    """Yield files under ``root`` in deterministic order without preloading."""

    if not root.exists():
        raise InventoryError(f"inventory root does not exist: {root}")
    if not root.is_dir():
        if root.is_file():
            yield root
            return
        raise InventoryError(f"inventory root is not a directory or file: {root}")

    # Explicit stack keeps memory proportional to tree depth, not file count.
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise InventoryError(f"cannot scan directory {current}: {exc}") from exc

        # Sort for determinism; process directories after files at this level by
        # pushing them in reverse so lexicographically smaller names pop first.
        entries.sort(key=lambda entry: entry.name)

        directories: list[Path] = []
        for entry in entries:
            name = entry.name
            try:
                is_symlink = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                is_file = entry.is_file(follow_symlinks=follow_symlinks)
            except OSError:
                continue

            if is_dir:
                if is_symlink and not follow_symlinks:
                    continue
                if _should_skip_dir(name, skip_dir_names):
                    continue
                directories.append(Path(entry.path))
                continue

            if is_file:
                if is_symlink and not follow_symlinks:
                    # Inventory the symlink node itself only when it is a
                    # non-directory symlink we choose not to follow: skip to
                    # avoid hashing through external targets by default.
                    continue
                yield Path(entry.path)

        for directory in reversed(directories):
            stack.append(directory)


def _relative_posix(path: Path, root: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        relative = Path(path.name)
    return relative.as_posix()


def iter_inventory(
    roots: str | Path | Sequence[str | Path],
    *,
    base_dir: str | Path | None = None,
    skip_dir_names: Iterable[str] = DEFAULT_SKIP_DIR_NAMES,
    follow_symlinks: bool = False,
    chunk_size: int = DEFAULT_DIGEST_CHUNK_SIZE,
    classify: Callable[[str], tuple[InventoryKind, str, str, ProposedAuthority]]
    | None = None,
) -> Iterator[InventoryRecord]:
    """Stream :class:`InventoryRecord` values for every regular file under roots.

    Parameters
    ----------
    roots:
        One or more filesystem roots (directories or single files).  Roots are
        sorted by their resolved path string before scanning so repeated calls
        yield the same order.
    base_dir:
        Optional path used only for display; record ``path`` values are always
        relative to their own root.
    skip_dir_names:
        Directory basenames to skip (``.git``, ``__pycache__``, …).
    follow_symlinks:
        When false (default), directory and file symlinks are not followed.
    chunk_size:
        Digest read size in bytes; must stay bounded for large corpora.
    classify:
        Optional override for :func:`classify_path` (used by tests).
    """

    if chunk_size <= 0:
        raise InventoryError("chunk_size must be a positive integer")

    if isinstance(roots, (str, Path)):
        root_list = [Path(roots)]
    else:
        root_list = [Path(item) for item in roots]
    if not root_list:
        raise InventoryError("at least one inventory root is required")

    # Deterministic root order.
    ordered_roots = sorted(root_list, key=lambda item: str(item.resolve(strict=False)))
    skip = frozenset(skip_dir_names)
    classify_fn = classify or classify_path
    _ = base_dir  # reserved for future multi-root relative displays

    for root in ordered_roots:
        root_resolved = root.resolve(strict=False)
        root_label = root_resolved.as_posix()
        for file_path in _iter_files_deterministic(
            root_resolved if root.is_dir() else root,
            skip_dir_names=skip,
            follow_symlinks=follow_symlinks,
        ):
            if root.is_file():
                relative = file_path.name
            else:
                relative = _relative_posix(file_path, root_resolved)

            size, digest = digest_file(file_path, chunk_size=chunk_size)
            kind, producer, consumer, authority = classify_fn(relative)
            yield InventoryRecord(
                path=relative,
                kind=kind,
                size=size,
                digest=digest,
                producer=producer,
                consumer=consumer,
                proposed_authority=authority,
                root=root_label,
            )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class InventoryRegistry:
    """In-memory registry of inventory records keyed by relative path.

    The registry stores **metadata only** (never file bodies).  Building a
    registry from a 970 MB corpus therefore retains only per-file classification
    rows, while :func:`iter_inventory` remains the memory-bounded streaming API.
    """

    def __init__(self) -> None:
        self._records: dict[str, InventoryRecord] = {}

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, path: object) -> bool:
        return isinstance(path, str) and path in self._records

    def add(self, record: InventoryRecord) -> None:
        if not isinstance(record, InventoryRecord):
            raise InventoryError("record must be an InventoryRecord")
        self._records[record.path] = record

    def extend(self, records: Iterable[InventoryRecord]) -> None:
        for record in records:
            self.add(record)

    def get(self, path: str) -> InventoryRecord | None:
        return self._records.get(path)

    def require(self, path: str) -> InventoryRecord:
        record = self.get(path)
        if record is None:
            raise InventoryError(f"path not registered: {path}")
        return record

    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))

    def records(self) -> tuple[InventoryRecord, ...]:
        return tuple(self._records[path] for path in sorted(self._records))

    def by_kind(self, kind: InventoryKind | str) -> tuple[InventoryRecord, ...]:
        expected = InventoryKind(kind)
        return tuple(record for record in self.records() if record.kind is expected)

    def kind_counts(self) -> Mapping[str, int]:
        counts: dict[str, int] = {kind.value: 0 for kind in InventoryKind}
        for record in self._records.values():
            counts[record.kind.value] += 1
        return MappingProxyType(counts)

    def total_bytes(self) -> int:
        return sum(record.size for record in self._records.values())

    def snapshot_digest(self) -> str:
        """Content digest over sorted record fields (deterministic)."""

        hasher = hashlib.sha256()
        for record in self.records():
            line = (
                f"{record.path}\0{record.kind.value}\0{record.size}\0"
                f"{record.digest}\0{record.producer}\0{record.consumer}\0"
                f"{record.proposed_authority.value}\n"
            )
            hasher.update(line.encode("utf-8"))
        return f"{_DIGEST_PREFIX}{hasher.hexdigest()}"

    def to_snapshot(
        self,
        *,
        roots: Sequence[str] = (),
        include_records: bool = True,
    ) -> InventorySnapshot:
        records = self.records() if include_records else ()
        return InventorySnapshot(
            schema=INVENTORY_SCHEMA,
            roots=tuple(roots),
            record_count=len(self),
            total_bytes=self.total_bytes(),
            kind_counts=self.kind_counts(),
            snapshot_digest=self.snapshot_digest(),
            records=records,
        )


def scan_inventory(
    roots: str | Path | Sequence[str | Path],
    *,
    skip_dir_names: Iterable[str] = DEFAULT_SKIP_DIR_NAMES,
    follow_symlinks: bool = False,
    chunk_size: int = DEFAULT_DIGEST_CHUNK_SIZE,
    include_records: bool = True,
    classify: Callable[[str], tuple[InventoryKind, str, str, ProposedAuthority]]
    | None = None,
) -> InventorySnapshot:
    """Scan ``roots`` and return a deterministic :class:`InventorySnapshot`.

    This is a convenience wrapper around :func:`iter_inventory` plus
    :class:`InventoryRegistry`.  Prefer :func:`iter_inventory` when callers
    must bound memory to a single record at a time.
    """

    if isinstance(roots, (str, Path)):
        root_seq: Sequence[str | Path] = (roots,)
    else:
        root_seq = roots

    registry = InventoryRegistry()
    registry.extend(
        iter_inventory(
            root_seq,
            skip_dir_names=skip_dir_names,
            follow_symlinks=follow_symlinks,
            chunk_size=chunk_size,
            classify=classify,
        )
    )
    root_labels = tuple(
        sorted(
            Path(root).resolve(strict=False).as_posix() for root in root_seq
        )
    )
    return registry.to_snapshot(roots=root_labels, include_records=include_records)
