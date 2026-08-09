"""Bounded, streaming inventory scanner for file-authoritative producers (DQK-001).

Classifies paths across datasets and supervisor trees into:

* authored documentation
* mutable state
* immutable evidence
* derived exports
* unsafe serialization

The scanner walks roots in deterministic order, hashes file bytes in fixed-size
chunks (never loading an entire file into memory), and yields
:class:`InventoryRecord` values with path, kind, size, digest, producer,
consumer, and proposed authority.

Importing this module is inert: it performs no filesystem I/O until a scan or
classification entry point is called.
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
    Callable,
    Final,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Sequence,
)

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_IGNORE_DIR_NAMES",
    "DEFAULT_ROOT_NAMES",
    "DEFAULT_RULES",
    "INVENTORY_SCHEMA",
    "ArtifactKind",
    "ClassificationRule",
    "InventoryRecord",
    "InventoryRegistry",
    "ProposedAuthority",
    "build_registry",
    "classify_path",
    "default_scan_roots",
    "digest_file_streaming",
    "inventory_snapshot_digest",
    "iter_inventory",
    "iter_sorted_files",
    "normalize_rel_path",
    "record_required_fields",
    "scan_inventory",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

INVENTORY_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-inventory@1"

# Fixed read size keeps peak memory independent of file size (970 MB corpus).
DEFAULT_CHUNK_SIZE: Final[int] = 1024 * 1024

DEFAULT_ROOT_NAMES: Final[tuple[str, ...]] = (
    "docs",
    "data",
    "data/agent_supervisor",
    "ipfs_datasets_py",
    "scripts",
    "tests",
    "archive",
    "workspace",
    "requirements",
)

# Directory basenames skipped during walks. Suffix patterns such as
# ``*.egg-info`` are handled separately in :func:`_should_ignore_dir`.
DEFAULT_IGNORE_DIR_NAMES: Final[frozenset[str]] = frozenset(
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
        "dist",
        "build",
        ".ipynb_checkpoints",
    }
)

RECORD_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "path",
    "kind",
    "size",
    "digest",
    "producer",
    "consumer",
    "proposed_authority",
)


def record_required_fields() -> tuple[str, ...]:
    """Return the canonical required field names for every inventory record."""
    return RECORD_REQUIRED_FIELDS


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ArtifactKind(str, Enum):
    """High-level classification of a file-authoritative artifact."""

    AUTHORED_DOCUMENTATION = "authored_documentation"
    MUTABLE_STATE = "mutable_state"
    IMMUTABLE_EVIDENCE = "immutable_evidence"
    DERIVED_EXPORT = "derived_export"
    UNSAFE_SERIALIZATION = "unsafe_serialization"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: str | ArtifactKind) -> ArtifactKind:
        if isinstance(value, ArtifactKind):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "authored": cls.AUTHORED_DOCUMENTATION,
            "authored_docs": cls.AUTHORED_DOCUMENTATION,
            "documentation": cls.AUTHORED_DOCUMENTATION,
            "docs": cls.AUTHORED_DOCUMENTATION,
            "mutable": cls.MUTABLE_STATE,
            "state": cls.MUTABLE_STATE,
            "evidence": cls.IMMUTABLE_EVIDENCE,
            "immutable": cls.IMMUTABLE_EVIDENCE,
            "export": cls.DERIVED_EXPORT,
            "derived": cls.DERIVED_EXPORT,
            "derived_exports": cls.DERIVED_EXPORT,
            "unsafe": cls.UNSAFE_SERIALIZATION,
            "pickle": cls.UNSAFE_SERIALIZATION,
            "serialization": cls.UNSAFE_SERIALIZATION,
        }
        if text in aliases:
            return aliases[text]
        return cls(text)


class ProposedAuthority(str, Enum):
    """Where truth for this path should live after control-plane cutover."""

    GIT_AUTHORED = "git_authored"
    CONTROL_DUCKDB = "control_duckdb"
    DOMAIN_DUCKDB = "domain_duckdb"
    CONTENT_ADDRESSED = "content_addressed"
    EXPORT_ONLY = "export_only"
    ONE_TIME_IMPORT = "one_time_import"
    QUARANTINE = "quarantine"
    RETAIN_FILE = "retain_file"

    @classmethod
    def parse(cls, value: str | ProposedAuthority) -> ProposedAuthority:
        if isinstance(value, ProposedAuthority):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        return cls(text)


# ---------------------------------------------------------------------------
# Records and rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    """One inventoried file with classification and migration guidance.

    Every record always exposes the seven required acceptance fields:
    path, kind, size, digest, producer, consumer, proposed_authority.
    """

    path: str
    kind: ArtifactKind
    size: int
    digest: str
    producer: str
    consumer: str
    proposed_authority: ProposedAuthority
    rule_id: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("path must be a non-empty posix-relative string")
        if self.size < 0:
            raise ValueError(f"size must be non-negative, got {self.size}")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError(
                f"digest must be a lowercase sha256 hex digest, got {self.digest!r}"
            )
        if not self.producer:
            raise ValueError("producer must be non-empty")
        if not self.consumer:
            raise ValueError("consumer must be non-empty")

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain JSON-friendly mapping (sorted-key friendly)."""
        return {
            "path": self.path,
            "kind": self.kind.value,
            "size": self.size,
            "digest": self.digest,
            "producer": self.producer,
            "consumer": self.consumer,
            "proposed_authority": self.proposed_authority.value,
            "rule_id": self.rule_id,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> InventoryRecord:
        missing = [name for name in RECORD_REQUIRED_FIELDS if name not in data]
        if missing:
            raise ValueError(f"inventory record missing fields: {missing}")
        return cls(
            path=str(data["path"]),
            kind=ArtifactKind.parse(str(data["kind"])),
            size=int(data["size"]),  # type: ignore[arg-type]
            digest=str(data["digest"]),
            producer=str(data["producer"]),
            consumer=str(data["consumer"]),
            proposed_authority=ProposedAuthority.parse(
                str(data["proposed_authority"])
            ),
            rule_id=str(data.get("rule_id") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    """Ordered rule that maps a relative path to kind / lineage / authority."""

    rule_id: str
    kind: ArtifactKind
    producer: str
    consumer: str
    proposed_authority: ProposedAuthority
    # Match when any predicate returns True. Empty matchers never match.
    path_globs: tuple[str, ...] = ()
    path_regexes: tuple[str, ...] = ()
    name_suffixes: tuple[str, ...] = ()
    path_substrings: tuple[str, ...] = ()
    notes: str = ""
    _compiled: tuple[re.Pattern[str], ...] = field(
        default=(), repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("rule_id must be non-empty")
        compiled = tuple(
            re.compile(pattern, re.IGNORECASE) for pattern in self.path_regexes
        )
        object.__setattr__(self, "_compiled", compiled)

    def matches(self, rel_path: str) -> bool:
        """Return True when this rule applies to the posix-relative path."""
        path = rel_path.replace("\\", "/")
        name = PurePosixPath(path).name
        lower = path.lower()
        name_lower = name.lower()

        for suffix in self.name_suffixes:
            if name_lower.endswith(suffix.lower()):
                return True
        for fragment in self.path_substrings:
            if fragment.lower() in lower:
                return True
        for pattern in self._compiled:
            if pattern.search(path):
                return True
        for glob in self.path_globs:
            if PurePosixPath(path).match(glob) or PurePosixPath(name).match(glob):
                return True
        return False


def _rule(
    rule_id: str,
    kind: ArtifactKind,
    producer: str,
    consumer: str,
    proposed_authority: ProposedAuthority,
    *,
    path_globs: Sequence[str] = (),
    path_regexes: Sequence[str] = (),
    name_suffixes: Sequence[str] = (),
    path_substrings: Sequence[str] = (),
    notes: str = "",
) -> ClassificationRule:
    return ClassificationRule(
        rule_id=rule_id,
        kind=kind,
        producer=producer,
        consumer=consumer,
        proposed_authority=proposed_authority,
        path_globs=tuple(path_globs),
        path_regexes=tuple(path_regexes),
        name_suffixes=tuple(name_suffixes),
        path_substrings=tuple(path_substrings),
        notes=notes,
    )


# Ordered from most specific / highest severity to broad fallbacks.
DEFAULT_RULES: Final[tuple[ClassificationRule, ...]] = (
    # --- Unsafe serialization (fail closed / one-time import) ---
    _rule(
        "unsafe-pickle",
        ArtifactKind.UNSAFE_SERIALIZATION,
        producer="legacy vector / cache pickle writers",
        consumer="vector stores, process-local caches",
        proposed_authority=ProposedAuthority.ONE_TIME_IMPORT,
        name_suffixes=(".pkl", ".pickle", ".joblib"),
        notes="Pickle is never a runtime authority after cutover.",
    ),
    _rule(
        "unsafe-wallet-records-jsonl",
        ArtifactKind.UNSAFE_SERIALIZATION,
        producer="wallet / processor record writers",
        consumer="wallet processors, migration importers",
        proposed_authority=ProposedAuthority.ONE_TIME_IMPORT,
        name_suffixes=("records.jsonl",),
        path_substrings=("/records.jsonl",),
        notes="Legacy wallet records.jsonl is import-only.",
    ),
    _rule(
        "unsafe-meta-sidecar",
        ArtifactKind.UNSAFE_SERIALIZATION,
        producer="dataset / parquet sidecar writers",
        consumer="dataset loaders, directory scanners",
        proposed_authority=ProposedAuthority.ONE_TIME_IMPORT,
        name_suffixes=(".meta.json", ".metadata.json"),
        path_substrings=(".meta.json",),
        notes="Mutable metadata sidecars must not remain discovery authority.",
    ),
    _rule(
        "unsafe-parquet-manifest-sidecar",
        ArtifactKind.UNSAFE_SERIALIZATION,
        producer="legacy parquet directory scanners",
        consumer="dataset loaders, knowledge-graph parquet storage",
        proposed_authority=ProposedAuthority.DOMAIN_DUCKDB,
        path_regexes=(
            r"(^|/)manifests?\.json$",
            r"(^|/)[^/]*_manifest\.json$",
            r"(^|/)sidecar[^/]*\.json$",
        ),
        path_substrings=("/sidecars/", "/parquet_manifest"),
        notes="Parquet discovery must move to lake registry / snapshot receipts.",
    ),
    _rule(
        "unsafe-todo-markdown-authority",
        ArtifactKind.UNSAFE_SERIALIZATION,
        producer="agent supervisor / objective refill writers",
        consumer="todo daemons, planning loops",
        proposed_authority=ProposedAuthority.CONTROL_DUCKDB,
        name_suffixes=(
            ".todo.md",
            ".taskboard.todo.md",
            "master_todo_list.md",
            "objectives.md",
            "taskboard.todo.md",
        ),
        path_regexes=(
            r"(^|/)todo(_list)?\.md$",
            r"\.taskboard\.todo\.md$",
            r"(^|/)objectives\.md$",
        ),
        notes="Mutable orchestration must not remain Markdown-authoritative.",
    ),
    # --- Immutable evidence ---
    _rule(
        "evidence-receipts",
        ArtifactKind.IMMUTABLE_EVIDENCE,
        producer="validation gates, release / merge / canary workflows",
        consumer="acceptance evidence, cutover verifiers",
        proposed_authority=ProposedAuthority.CONTENT_ADDRESSED,
        path_substrings=(
            "/receipts/",
            "/evidence/",
            "-receipt.json",
            "_receipt.json",
            "acceptance_evidence",
            "merge_receipt",
            "parity_receipt",
            "snapshot_receipt",
        ),
        name_suffixes=("-receipt.json", "_receipt.json", ".receipt.json"),
        notes="Receipts remain content-addressed immutable evidence.",
    ),
    _rule(
        "evidence-content-addressed-bytes",
        ArtifactKind.IMMUTABLE_EVIDENCE,
        producer="IPLD / CAR / CID exporters",
        consumer="proof, graph, and lake content loaders",
        proposed_authority=ProposedAuthority.CONTENT_ADDRESSED,
        name_suffixes=(".car", ".cid", ".ipld", ".dag-json", ".dag-cbor"),
        path_substrings=("/ipld/", "/cars/", "/cids/"),
        notes="Immutable content-addressed blobs stay outside DuckDB.",
    ),
    _rule(
        "evidence-security-ir-artifacts",
        ArtifactKind.IMMUTABLE_EVIDENCE,
        producer="security IR verification workflows",
        consumer="security_ir inventory and audit consumers",
        proposed_authority=ProposedAuthority.CONTENT_ADDRESSED,
        path_substrings=(
            "security_ir_artifacts/",
            "/security_verification/",
            "/proof_evidence/",
        ),
    ),
    # --- Mutable operational state ---
    _rule(
        "state-duckdb-control",
        ArtifactKind.MUTABLE_STATE,
        producer="agent supervisor control plane",
        consumer="implementation daemon, task source, leases",
        proposed_authority=ProposedAuthority.CONTROL_DUCKDB,
        name_suffixes=(".duckdb", ".duckdb.wal", ".wal"),
        path_substrings=(
            "control.duckdb",
            "/agent_supervisor/",
            "/implementation_checkpoints/",
            "/leases/",
            "/heartbeats/",
        ),
        notes="Control DuckDB becomes the orchestration authority.",
    ),
    _rule(
        "state-checkpoints-cursors",
        ArtifactKind.MUTABLE_STATE,
        producer="streaming importers, wallet cursors, supervisor lanes",
        consumer="resume / recovery paths",
        proposed_authority=ProposedAuthority.CONTROL_DUCKDB,
        path_substrings=(
            "/checkpoints/",
            "/cursors/",
            "/state/",
            "/locks/",
            "checkpoint",
            "cursor.json",
            "lease.json",
            "heartbeat",
        ),
        name_suffixes=(
            ".lock",
            ".pid",
            ".ckpt",
            ".checkpoint",
            "checkpoint.json",
            "cursor.json",
        ),
    ),
    _rule(
        "state-runtime-logs",
        ArtifactKind.MUTABLE_STATE,
        producer="runtime processes, daemons, dashboards",
        consumer="operators, observability importers",
        proposed_authority=ProposedAuthority.DOMAIN_DUCKDB,
        name_suffixes=(".log", ".out", ".err"),
        path_substrings=("/logs/", "/log/"),
        notes="Operational logs migrate to observability catalog events.",
    ),
    # --- Derived exports ---
    _rule(
        "export-deterministic-projections",
        ArtifactKind.DERIVED_EXPORT,
        producer="duckdb_control exporter / deterministic projection jobs",
        consumer="operators, documentation surfaces, CI artifacts",
        proposed_authority=ProposedAuthority.EXPORT_ONLY,
        path_substrings=(
            "/exports/",
            "/derived/",
            "/projections/",
            "/release_exports/",
            "export_jobs",
        ),
        path_regexes=(
            r"(^|/)exports?/",
            r"(^|/)derived/",
            r"(^|/)projections?/",
        ),
        notes="Exports are one-way projections bound to a snapshot + digest.",
    ),
    _rule(
        "export-benchmark-results",
        ArtifactKind.DERIVED_EXPORT,
        producer="benchmarks and soak harnesses",
        consumer="performance reports, CI",
        proposed_authority=ProposedAuthority.EXPORT_ONLY,
        path_substrings=("/benchmarks/results/", "/results/"),
        path_regexes=(r"(^|/)benchmarks/.+/results/",),
    ),
    # --- Authored documentation ---
    _rule(
        "docs-architecture-plans",
        ArtifactKind.AUTHORED_DOCUMENTATION,
        producer="human authors / design process",
        consumer="implementers, reviewers, projection-only readers",
        proposed_authority=ProposedAuthority.GIT_AUTHORED,
        path_substrings=("docs/", "/architecture/", "/implementation/plans/"),
        name_suffixes=(".md", ".rst", ".adoc", ".txt"),
        path_globs=("README*", "CHANGELOG*", "CONTRIBUTING*", "LICENSE*"),
        notes="Authored docs remain Git-authored; not operational authority.",
    ),
    _rule(
        "docs-markdown-generic",
        ArtifactKind.AUTHORED_DOCUMENTATION,
        producer="human authors / design process",
        consumer="implementers, reviewers",
        proposed_authority=ProposedAuthority.GIT_AUTHORED,
        name_suffixes=(".md", ".rst", ".adoc"),
    ),
    # --- Fallback: unknown ---
    _rule(
        "unknown-fallback",
        ArtifactKind.UNKNOWN,
        producer="unclassified producer",
        consumer="inventory refinement / residual analysis",
        proposed_authority=ProposedAuthority.RETAIN_FILE,
        path_regexes=(r".*",),
        notes="Residual path for refinement (DQK-080) and cutover scans.",
    ),
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def normalize_rel_path(path: str | os.PathLike[str] | Path) -> str:
    """Normalize a path to a portable posix-relative form without leading './'."""
    text = os.fspath(path).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    text = text.lstrip("/")
    # Collapse redundant separators without resolving symlinks (identity-safe).
    parts = [part for part in text.split("/") if part not in ("", ".")]
    return "/".join(parts)


def default_scan_roots(base: str | os.PathLike[str] | Path) -> tuple[Path, ...]:
    """Resolve default datasets / supervisor scan roots under *base* if present."""
    root = Path(base).resolve()
    found: list[Path] = []
    seen: set[Path] = set()
    for name in DEFAULT_ROOT_NAMES:
        candidate = (root / name).resolve()
        if not candidate.exists():
            continue
        if candidate in seen:
            continue
        # Prefer the more specific agent_supervisor root when both data and
        # data/agent_supervisor exist; still allow plain data if only that exists.
        if name == "data" and (root / "data" / "agent_supervisor").exists():
            continue
        seen.add(candidate)
        found.append(candidate)
    if not found:
        found.append(root)
    return tuple(found)


def _should_ignore_dir(name: str, ignore_dir_names: frozenset[str]) -> bool:
    """Return True when a directory basename should be pruned from the walk.

    Exact-name matches use *ignore_dir_names*. Packaging metadata directories
    that end with ``.egg-info`` are always ignored so scanner walks stay
    bounded and free of build-tool noise.
    """
    if name in ignore_dir_names:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def iter_sorted_files(
    roots: Sequence[str | os.PathLike[str] | Path],
    *,
    ignore_dir_names: Iterable[str] = DEFAULT_IGNORE_DIR_NAMES,
    follow_symlinks: bool = False,
) -> Iterator[tuple[Path, str]]:
    """Yield ``(absolute_path, relative_posix_path)`` in deterministic order.

    Directory entries are sorted by UTF-8 path bytes so scans are stable across
    locales. Symlinks to directories are not followed by default.
    """
    ignore = frozenset(ignore_dir_names)
    # Stable multi-root order by relative display path when roots share a parent.
    resolved_roots = [Path(root).resolve() for root in roots]
    # Sort roots by their path string for determinism.
    ordered_roots = sorted(resolved_roots, key=lambda p: str(p).encode("utf-8"))

    # When all roots share a common base, emit paths relative to that base;
    # otherwise emit relative to each root (prefixed with root name if useful).
    common_base: Optional[Path] = None
    if ordered_roots:
        try:
            common_base = Path(os.path.commonpath([str(p) for p in ordered_roots]))
            if not common_base.is_dir() and common_base.parent.is_dir():
                common_base = common_base.parent
        except ValueError:
            common_base = None

    seen_files: set[Path] = set()

    for root in ordered_roots:
        if not root.exists():
            continue
        if root.is_file():
            if root in seen_files:
                continue
            seen_files.add(root)
            rel = _relative_to_base(root, common_base, root)
            yield root, rel
            continue

        # Iterative DFS with reverse-sorted children → lexicographic yield order.
        stack: list[Path] = [root]
        while stack:
            current = stack.pop()
            try:
                is_symlink = current.is_symlink()
                is_file = current.is_file()
                is_dir = current.is_dir()
            except OSError:
                continue

            # Directory symlinks are skipped unless explicitly followed.
            if is_dir and is_symlink and not follow_symlinks and current != root:
                continue

            if is_file:
                if follow_symlinks:
                    try:
                        key = current.resolve()
                    except OSError:
                        key = current
                else:
                    key = current
                if key in seen_files:
                    continue
                seen_files.add(key)
                rel = _relative_to_base(current, common_base, root)
                yield current, rel
                continue

            if not is_dir:
                continue

            try:
                children = list(current.iterdir())
            except OSError:
                continue

            def _sort_key(path: Path) -> bytes:
                return path.name.encode("utf-8", errors="surrogateescape")

            children.sort(key=_sort_key)
            # Push reversed so the smallest name is processed first (stack LIFO).
            for child in reversed(children):
                try:
                    name = child.name
                except OSError:
                    continue
                try:
                    child_is_dir = child.is_dir()
                    child_is_symlink = child.is_symlink()
                except OSError:
                    continue
                if child_is_dir and _should_ignore_dir(name, ignore):
                    continue
                if child_is_dir and child_is_symlink and not follow_symlinks:
                    continue
                stack.append(child)


def _relative_to_base(
    path: Path, common_base: Optional[Path], root: Path
) -> str:
    if common_base is not None:
        try:
            return normalize_rel_path(path.relative_to(common_base).as_posix())
        except ValueError:
            pass
    try:
        return normalize_rel_path(path.relative_to(root).as_posix())
    except ValueError:
        return normalize_rel_path(path.as_posix())


# ---------------------------------------------------------------------------
# Streaming digest
# ---------------------------------------------------------------------------


def digest_file_streaming(
    path: str | os.PathLike[str] | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    digest_factory: Callable[[], object] = hashlib.sha256,
) -> tuple[int, str]:
    """Hash *path* with bounded memory; return ``(size_bytes, hex_digest)``.

    Reads at most *chunk_size* bytes at a time. Suitable for multi-hundred-MB
    production-hardening corpora without loading them into RAM.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")

    target = Path(path)
    hasher = digest_factory()
    update = getattr(hasher, "update")
    hexdigest = getattr(hasher, "hexdigest")
    size = 0
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            update(chunk)
    return size, str(hexdigest())


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_path(
    rel_path: str,
    *,
    rules: Sequence[ClassificationRule] = DEFAULT_RULES,
) -> ClassificationRule:
    """Return the first matching classification rule for *rel_path*."""
    normalized = normalize_rel_path(rel_path)
    for rule in rules:
        if rule.matches(normalized):
            return rule
    # DEFAULT_RULES ends with a match-all; keep a hard fallback for custom sets.
    return ClassificationRule(
        rule_id="unknown-hard-fallback",
        kind=ArtifactKind.UNKNOWN,
        producer="unclassified producer",
        consumer="inventory refinement / residual analysis",
        proposed_authority=ProposedAuthority.RETAIN_FILE,
        path_regexes=(r".*",),
        notes="No rule matched.",
    )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def iter_inventory(
    roots: Sequence[str | os.PathLike[str] | Path],
    *,
    rules: Sequence[ClassificationRule] = DEFAULT_RULES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    ignore_dir_names: Iterable[str] = DEFAULT_IGNORE_DIR_NAMES,
    follow_symlinks: bool = False,
    include_kinds: Optional[Iterable[ArtifactKind | str]] = None,
) -> Iterator[InventoryRecord]:
    """Stream inventory records for files under *roots* (deterministic).

    Records are yielded in sorted path order. File contents are hashed in
    *chunk_size* windows so large corpora never load fully into memory.
    """
    kind_filter: Optional[set[ArtifactKind]] = None
    if include_kinds is not None:
        kind_filter = {ArtifactKind.parse(k) for k in include_kinds}

    for absolute, rel in iter_sorted_files(
        roots,
        ignore_dir_names=ignore_dir_names,
        follow_symlinks=follow_symlinks,
    ):
        rule = classify_path(rel, rules=rules)
        if kind_filter is not None and rule.kind not in kind_filter:
            continue
        try:
            size, digest = digest_file_streaming(absolute, chunk_size=chunk_size)
        except OSError:
            # Unreadable files are skipped rather than aborting the whole scan.
            continue
        yield InventoryRecord(
            path=rel,
            kind=rule.kind,
            size=size,
            digest=digest,
            producer=rule.producer,
            consumer=rule.consumer,
            proposed_authority=rule.proposed_authority,
            rule_id=rule.rule_id,
            notes=rule.notes,
        )


def scan_inventory(
    base: str | os.PathLike[str] | Path,
    *,
    roots: Optional[Sequence[str | os.PathLike[str] | Path]] = None,
    rules: Sequence[ClassificationRule] = DEFAULT_RULES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    ignore_dir_names: Iterable[str] = DEFAULT_IGNORE_DIR_NAMES,
    follow_symlinks: bool = False,
    include_kinds: Optional[Iterable[ArtifactKind | str]] = None,
) -> Iterator[InventoryRecord]:
    """Scan default or explicit roots under *base* and stream records.

    When *roots* is omitted, :func:`default_scan_roots` selects present datasets
    and supervisor trees. This is the primary DQK-001 entry point.
    """
    base_path = Path(base).resolve()
    if roots is None:
        scan_roots = default_scan_roots(base_path)
    else:
        scan_roots = tuple(
            (base_path / root).resolve()
            if not Path(root).is_absolute()
            else Path(root).resolve()
            for root in roots
        )
    yield from iter_inventory(
        scan_roots,
        rules=rules,
        chunk_size=chunk_size,
        ignore_dir_names=ignore_dir_names,
        follow_symlinks=follow_symlinks,
        include_kinds=include_kinds,
    )


def inventory_snapshot_digest(
    records: Iterable[InventoryRecord],
) -> str:
    """Compute a deterministic sha256 over the canonical record stream.

    Paths and fields are serialized in encounter order; callers should pass a
    deterministically ordered iterable (as produced by :func:`iter_inventory`).
    """
    hasher = hashlib.sha256()
    for record in records:
        payload = (
            f"{record.path}\0{record.kind.value}\0{record.size}\0"
            f"{record.digest}\0{record.producer}\0{record.consumer}\0"
            f"{record.proposed_authority.value}\n"
        )
        hasher.update(payload.encode("utf-8"))
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class InventoryRegistry:
    """In-memory index over an inventory stream, built incrementally.

    Construction from :meth:`from_iterable` still streams the source; only the
    compact record objects are retained. Use :func:`iter_inventory` alone when
    even that bound is too high.
    """

    __slots__ = ("_by_path", "_schema", "_source_roots")

    def __init__(
        self,
        *,
        schema: str = INVENTORY_SCHEMA,
        source_roots: Sequence[str] = (),
    ) -> None:
        self._by_path: dict[str, InventoryRecord] = {}
        self._schema = schema
        self._source_roots = tuple(source_roots)

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def source_roots(self) -> tuple[str, ...]:
        return self._source_roots

    def __len__(self) -> int:
        return len(self._by_path)

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, str):
            return False
        return normalize_rel_path(path) in self._by_path

    def __iter__(self) -> Iterator[InventoryRecord]:
        # Deterministic iteration by path bytes.
        for key in sorted(self._by_path.keys(), key=lambda p: p.encode("utf-8")):
            yield self._by_path[key]

    def add(self, record: InventoryRecord) -> None:
        """Insert or replace a record keyed by normalized path."""
        self._by_path[normalize_rel_path(record.path)] = record

    def get(self, path: str) -> Optional[InventoryRecord]:
        return self._by_path.get(normalize_rel_path(path))

    def by_kind(self, kind: ArtifactKind | str) -> tuple[InventoryRecord, ...]:
        target = ArtifactKind.parse(kind)
        return tuple(record for record in self if record.kind is target)

    def by_authority(
        self, authority: ProposedAuthority | str
    ) -> tuple[InventoryRecord, ...]:
        target = ProposedAuthority.parse(authority)
        return tuple(
            record for record in self if record.proposed_authority is target
        )

    def kind_counts(self) -> Mapping[str, int]:
        """Return sorted kind → count tallies over the registry."""
        counts: dict[str, int] = {}
        for record in self._by_path.values():
            key = record.kind.value
            counts[key] = counts.get(key, 0) + 1
        return MappingProxyType(dict(sorted(counts.items())))

    def authority_counts(self) -> Mapping[str, int]:
        """Return sorted proposed_authority → count tallies over the registry."""
        counts: dict[str, int] = {}
        for record in self._by_path.values():
            key = record.proposed_authority.value
            counts[key] = counts.get(key, 0) + 1
        return MappingProxyType(dict(sorted(counts.items())))

    def rule_counts(self) -> Mapping[str, int]:
        """Return sorted classification rule_id → count tallies.

        Empty ``rule_id`` values are counted under the literal key ``""`` so
        residual/unclassified producers remain visible in snapshots.
        """
        counts: dict[str, int] = {}
        for record in self._by_path.values():
            key = record.rule_id
            counts[key] = counts.get(key, 0) + 1
        return MappingProxyType(dict(sorted(counts.items())))

    def by_rule_id(self, rule_id: str) -> tuple[InventoryRecord, ...]:
        """Return records matched by *rule_id* in deterministic path order."""
        target = str(rule_id)
        return tuple(record for record in self if record.rule_id == target)

    def snapshot_digest(self) -> str:
        return inventory_snapshot_digest(self)

    def to_list(self) -> list[dict[str, object]]:
        return [record.to_dict() for record in self]

    def paths(self) -> tuple[str, ...]:
        """Return every registered path in deterministic UTF-8 order."""
        return tuple(
            sorted(self._by_path.keys(), key=lambda p: p.encode("utf-8"))
        )

    @classmethod
    def from_iterable(
        cls,
        records: Iterable[InventoryRecord],
        *,
        schema: str = INVENTORY_SCHEMA,
        source_roots: Sequence[str] = (),
    ) -> InventoryRegistry:
        registry = cls(schema=schema, source_roots=source_roots)
        for record in records:
            registry.add(record)
        return registry


def build_registry(
    base: str | os.PathLike[str] | Path,
    *,
    roots: Optional[Sequence[str | os.PathLike[str] | Path]] = None,
    rules: Sequence[ClassificationRule] = DEFAULT_RULES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    ignore_dir_names: Iterable[str] = DEFAULT_IGNORE_DIR_NAMES,
    follow_symlinks: bool = False,
    include_kinds: Optional[Iterable[ArtifactKind | str]] = None,
) -> InventoryRegistry:
    """Scan and materialize an :class:`InventoryRegistry` for *base*."""
    base_path = Path(base).resolve()
    if roots is None:
        scan_roots = default_scan_roots(base_path)
    else:
        scan_roots = tuple(
            (base_path / root).resolve()
            if not Path(root).is_absolute()
            else Path(root).resolve()
            for root in roots
        )
    records = iter_inventory(
        scan_roots,
        rules=rules,
        chunk_size=chunk_size,
        ignore_dir_names=ignore_dir_names,
        follow_symlinks=follow_symlinks,
        include_kinds=include_kinds,
    )
    return InventoryRegistry.from_iterable(
        records,
        source_roots=tuple(normalize_rel_path(str(r)) for r in scan_roots),
    )
