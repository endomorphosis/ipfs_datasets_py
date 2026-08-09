"""Bounded streaming inventory of file-authoritative producers (DQK-001).

This module classifies repository and runtime artifacts into the five
control-plane kinds required by the DuckDB + Quack rollout:

* authored documentation
* mutable state
* immutable evidence
* derived exports
* unsafe serialization

The scanner is deliberately streaming and deterministic: paths are emitted in
sorted UTF-8 order and digests are computed by reading fixed-size chunks so a
~970 MB production-hardening corpus can be inventoried without loading the
file into memory.

Every record carries path, kind, size, digest, producer, consumer, and
proposed authority so later importer/exporter tasks can migrate producers
without re-deriving classification policy ad hoc.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Final

SCHEMA_VERSION: Final = "DuckDBControlInventory@1"
DEFAULT_CHUNK_SIZE: Final = 1 << 20  # 1 MiB — bound peak digest buffer
DIGEST_ALGORITHM: Final = "sha256"

# Directory basenames skipped during walks (never descended into).
DEFAULT_SKIP_DIR_NAMES: Final = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".eggs",
        "*.egg-info",
        ".ipynb_checkpoints",
    }
)

# Suffixes treated as unsafe serialization regardless of path.
_UNSAFE_SUFFIXES: Final = frozenset(
    {
        ".pkl",
        ".pickle",
        ".joblib",
        ".dill",
        ".marshal",
        ".cpickle",
        ".p",
    }
)

# Content-addressed / evidence formats.
_EVIDENCE_SUFFIXES: Final = frozenset(
    {
        ".car",
        ".parquet",
        ".arrow",
        ".cid",
        ".sig",
        ".signature",
        ".attestation",
    }
)

# Operational / mutable state formats.
_STATE_SUFFIXES: Final = frozenset(
    {
        ".duckdb",
        ".wal",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".lock",
        ".pid",
        ".lease",
        ".tmp",
        ".temp",
    }
)

# Derived export formats (when under export/projection path patterns).
_EXPORT_SUFFIXES: Final = frozenset(
    {
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".ndjson",
        ".md",
        ".html",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
    }
)

# Authored documentation suffixes.
_DOC_SUFFIXES: Final = frozenset(
    {
        ".md",
        ".rst",
        ".txt",
        ".adoc",
        ".org",
    }
)

# Path segment / filename tokens that force a classification.
_UNSAFE_NAME_TOKENS: Final = frozenset(
    {
        "pickle",
        "pickled",
        "joblib",
        "dill",
        "faiss_index",
        "faiss-index",
        "unpickle",
    }
)

_EVIDENCE_NAME_TOKENS: Final = frozenset(
    {
        "receipt",
        "receipts",
        "evidence",
        "attestation",
        "attestations",
        "digest",
        "digests",
        "checksum",
        "checksums",
        "cid",
        "cids",
        "proof",
        "proofs",
        "golden",
        "fixture",
        "fixtures",
        "corpus",
        "corpora",
        "snapshot",
        "snapshots",
        "car",
        "ipld",
    }
)

_EXPORT_NAME_TOKENS: Final = frozenset(
    {
        "export",
        "exports",
        "projection",
        "projections",
        "derived",
        "report",
        "reports",
        "dump",
        "dumps",
        "render",
        "renders",
        "publish",
        "published",
    }
)

_STATE_NAME_TOKENS: Final = frozenset(
    {
        "state",
        "queue",
        "queues",
        "lease",
        "leases",
        "heartbeat",
        "heartbeats",
        "claim",
        "claims",
        "lock",
        "locks",
        "checkpoint",
        "checkpoints",
        "cursor",
        "cursors",
        "todo",
        "todos",
        "backlog",
        "control",
        "runtime",
        "worktree",
        "worktrees",
        "lane",
        "lanes",
        "session",
        "sessions",
        "cache",
        "caches",
        "tmp",
        "temp",
        "scratch",
    }
)

_DOC_NAME_TOKENS: Final = frozenset(
    {
        "docs",
        "doc",
        "readme",
        "changelog",
        "architecture",
        "plan",
        "plans",
        "design",
        "adr",
        "rfc",
        "guide",
        "manual",
        "spec",
        "specification",
    }
)

# Path prefixes (posix, relative) with fixed producer / consumer / authority.
_PREFIX_PRODUCER_RULES: Final = tuple(
    sorted(
        (
            ("data/agent_supervisor/", "agent_supervisor", "duckdb_control_importer"),
            ("data/", "dataset_runtime", "duckdb_control_importer"),
            ("docs/", "human_author", "documentation_consumers"),
            ("workspace/", "workspace_pipeline", "duckdb_control_importer"),
            ("archive/", "legacy_archive", "migration_importers"),
            ("tests/fixtures/", "test_fixture_builder", "unit_and_integration_tests"),
            ("ipfs_datasets_py/", "ipfs_datasets_py", "duckdb_control"),
            ("ipfs_accelerate_py/", "ipfs_accelerate_py", "agent_supervisor"),
            ("scripts/", "ops_scripts", "operators"),
            ("requirements/", "dependency_policy", "capability_gates"),
            ("state/", "runtime_state", "agent_supervisor"),
        ),
        key=lambda item: (-len(item[0]), item[0]),
    )
)

_AUTHORITY_BY_KIND: Final = {
    "authored_documentation": "git_authored",
    "mutable_state": "control",
    "immutable_evidence": "content_addressed_store",
    "derived_export": "export_only",
    "unsafe_serialization": "quarantine",
}


class InventoryKind(str, Enum):
    """Classification of a file-authoritative artifact."""

    AUTHORED_DOCUMENTATION = "authored_documentation"
    MUTABLE_STATE = "mutable_state"
    IMMUTABLE_EVIDENCE = "immutable_evidence"
    DERIVED_EXPORT = "derived_export"
    UNSAFE_SERIALIZATION = "unsafe_serialization"

    @classmethod
    def values(cls) -> frozenset[str]:
        return frozenset(item.value for item in cls)


REQUIRED_RECORD_FIELDS: Final = frozenset(
    {
        "path",
        "kind",
        "size",
        "digest",
        "producer",
        "consumer",
        "proposed_authority",
    }
)


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    """One inventoried file with control-plane classification metadata."""

    path: str
    kind: str
    size: int
    digest: str
    producer: str
    consumer: str
    proposed_authority: str

    def __post_init__(self) -> None:
        if not self.path or self.path.startswith("/") or "\\" in self.path:
            raise ValueError(f"path must be a non-empty posix-relative path: {self.path!r}")
        if ".." in PurePosixPath(self.path).parts:
            raise ValueError(f"path must not contain '..': {self.path!r}")
        if self.kind not in InventoryKind.values():
            raise ValueError(f"unknown inventory kind: {self.kind!r}")
        if self.size < 0:
            raise ValueError(f"size must be non-negative: {self.size}")
        if not self.digest.startswith(f"{DIGEST_ALGORITHM}:") or len(self.digest) != len(
            DIGEST_ALGORITHM
        ) + 1 + 64:
            raise ValueError(f"digest must be {DIGEST_ALGORITHM}:<64 hex chars>: {self.digest!r}")
        hex_part = self.digest.split(":", 1)[1]
        if not re.fullmatch(r"[0-9a-f]{64}", hex_part):
            raise ValueError(f"digest hex must be lowercase sha256: {self.digest!r}")
        for field_name in ("producer", "consumer", "proposed_authority"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

    def as_dict(self) -> dict[str, Any]:
        """Return a plain JSON-serializable mapping with required fields."""

        return asdict(self)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> InventoryRecord:
        missing = REQUIRED_RECORD_FIELDS - set(payload)
        if missing:
            raise ValueError(f"inventory record missing fields: {sorted(missing)}")
        return cls(
            path=str(payload["path"]),
            kind=str(payload["kind"]),
            size=int(payload["size"]),
            digest=str(payload["digest"]),
            producer=str(payload["producer"]),
            consumer=str(payload["consumer"]),
            proposed_authority=str(payload["proposed_authority"]),
        )


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    """A deterministic classification rule with explicit priority.

    Higher ``priority`` wins. When priorities tie, the rule with the longer
    path-prefix match wins, then the rule id (lexicographic) for stability.
    """

    rule_id: str
    kind: InventoryKind
    producer: str
    consumer: str
    proposed_authority: str
    priority: int = 0
    path_prefix: str = ""
    path_regex: str | None = None
    name_tokens: frozenset[str] = frozenset()
    suffixes: frozenset[str] = frozenset()
    predicate: Callable[[str], bool] | None = None

    def matches(self, relative_path: str) -> bool:
        posix = relative_path.replace("\\", "/")
        lower = posix.lower()
        name = PurePosixPath(posix).name.lower()
        suffix = PurePosixPath(posix).suffix.lower()
        parts = {part.lower() for part in PurePosixPath(posix).parts}

        if self.path_prefix and not lower.startswith(self.path_prefix.lower()):
            return False
        if self.suffixes and suffix not in {item.lower() for item in self.suffixes}:
            return False
        if self.name_tokens:
            tokens = {token.lower() for token in self.name_tokens}
            if not (tokens & parts) and not any(token in name for token in tokens):
                return False
        if self.path_regex is not None and re.search(self.path_regex, posix) is None:
            return False
        if self.predicate is not None and not self.predicate(posix):
            return False
        # A rule with no selectors would match everything; require at least one.
        has_selector = bool(
            self.path_prefix
            or self.path_regex
            or self.name_tokens
            or self.suffixes
            or self.predicate
        )
        return has_selector


def normalize_relative_path(value: str | Path, *, root: Path | None = None) -> str:
    """Return a stable repository-relative posix path string."""

    if isinstance(value, Path) and root is not None:
        resolved = value.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
        try:
            relative = resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"path {value} is not under root {root}") from exc
        raw = relative.as_posix()
    else:
        raw = str(value).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"paths must be non-empty and repository-relative: {value!r}")
    return path.as_posix()


def format_digest(hex_digest: str) -> str:
    """Prefix a lowercase hex digest with the algorithm name."""

    if not re.fullmatch(r"[0-9a-f]{64}", hex_digest):
        raise ValueError(f"expected lowercase sha256 hex, got {hex_digest!r}")
    return f"{DIGEST_ALGORITHM}:{hex_digest}"


def digest_file(
    path: Path | str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    on_chunk: Callable[[bytes], None] | None = None,
) -> tuple[int, str]:
    """Stream-hash a file without loading it fully into memory.

    Returns ``(size_bytes, "sha256:<hex>")``. Peak buffer size is bounded by
    ``chunk_size`` (plus hashlib internal state). ``on_chunk`` is invoked for
    each read chunk so callers can assert streaming behaviour in tests.
    """

    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    file_path = Path(path)
    hasher = hashlib.sha256()
    total = 0
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            hasher.update(chunk)
            if on_chunk is not None:
                on_chunk(chunk)
    # Prefer OS size when available so sparse-file sizes stay correct even if
    # a platform elides zero ranges; fall back to bytes actually read.
    try:
        size = file_path.stat().st_size
    except OSError:
        size = total
    return size, format_digest(hasher.hexdigest())


def _path_tokens(relative_path: str) -> set[str]:
    posix = relative_path.replace("\\", "/").lower()
    pure = PurePosixPath(posix)
    tokens = {part for part in pure.parts}
    stem = pure.stem.lower()
    tokens.add(stem)
    # Split common separators in the filename stem.
    for fragment in re.split(r"[_\-.]+", stem):
        if fragment:
            tokens.add(fragment)
    return tokens


def _producer_consumer_for_path(relative_path: str) -> tuple[str, str]:
    lower = relative_path.replace("\\", "/").lower()
    for prefix, producer, consumer in _PREFIX_PRODUCER_RULES:
        if lower.startswith(prefix):
            return producer, consumer
    return "filesystem", "duckdb_control_importer"


def classify_path(relative_path: str) -> tuple[InventoryKind, str, str, str]:
    """Classify a relative path into kind + producer/consumer/authority.

    Classification is pure and deterministic. Precedence (highest first):

    1. Unsafe serialization suffixes / tokens
    2. Mutable state databases, locks, and runtime path segments
    3. Immutable evidence formats and evidence path tokens
    4. Derived export path tokens
    5. Authored documentation
    6. Fallback by suffix (JSON/YAML under data → mutable state; else docs/export)
    """

    posix = normalize_relative_path(relative_path)
    lower = posix.lower()
    pure = PurePosixPath(lower)
    suffix = pure.suffix
    name = pure.name
    tokens = _path_tokens(posix)
    producer, consumer = _producer_consumer_for_path(posix)

    def result(kind: InventoryKind) -> tuple[InventoryKind, str, str, str]:
        return kind, producer, consumer, _AUTHORITY_BY_KIND[kind.value]

    # 1. Unsafe serialization
    if suffix in _UNSAFE_SUFFIXES or tokens & _UNSAFE_NAME_TOKENS:
        return result(InventoryKind.UNSAFE_SERIALIZATION)
    if name.endswith(".pkl.gz") or name.endswith(".pickle.gz"):
        return result(InventoryKind.UNSAFE_SERIALIZATION)

    # 2. Mutable operational state
    if suffix in _STATE_SUFFIXES or tokens & _STATE_NAME_TOKENS:
        # Exception: documentation under docs/ describing state remains authored.
        if not (lower.startswith("docs/") and suffix in _DOC_SUFFIXES):
            # Evidence receipts under state-like names still win as evidence
            # when they carry strong evidence tokens and evidence suffixes.
            if not (
                suffix in _EVIDENCE_SUFFIXES
                or (tokens & _EVIDENCE_NAME_TOKENS and suffix in {".json", ".jsonl", ".md"})
            ):
                return result(InventoryKind.MUTABLE_STATE)

    # 3. Immutable evidence
    if suffix in _EVIDENCE_SUFFIXES or tokens & _EVIDENCE_NAME_TOKENS:
        # Export-named receipts stay evidence (content-bound).
        return result(InventoryKind.IMMUTABLE_EVIDENCE)

    # 4. Derived exports
    if tokens & _EXPORT_NAME_TOKENS:
        return result(InventoryKind.DERIVED_EXPORT)
    if "/exports/" in f"/{lower}/" or "/projections/" in f"/{lower}/":
        return result(InventoryKind.DERIVED_EXPORT)

    # 5. Authored documentation
    if lower.startswith("docs/") or suffix in _DOC_SUFFIXES or tokens & _DOC_NAME_TOKENS:
        return result(InventoryKind.AUTHORED_DOCUMENTATION)

    # 6. Fallback by common operational formats
    if suffix in {".json", ".jsonl", ".yaml", ".yml", ".toml", ".ndjson"}:
        if lower.startswith("data/") or lower.startswith("workspace/") or lower.startswith(
            "state/"
        ):
            return result(InventoryKind.MUTABLE_STATE)
        if lower.startswith("archive/"):
            return result(InventoryKind.DERIVED_EXPORT)
        return result(InventoryKind.MUTABLE_STATE)

    if suffix in _EXPORT_SUFFIXES:
        return result(InventoryKind.DERIVED_EXPORT)

    # Default: treat unknown binaries under data/agent_supervisor as mutable state
    # so they are not silently ignored as documentation.
    if lower.startswith("data/") or lower.startswith("state/"):
        return result(InventoryKind.MUTABLE_STATE)
    return result(InventoryKind.AUTHORED_DOCUMENTATION)


class InventoryRegistry:
    """Registry of classification rules and optional collected records.

    The registry is the policy surface for DQK-001. Scans stream through
    :meth:`scan` and never require materializing the full tree. Callers that
    need a full list for small fixtures may use :meth:`collect`.
    """

    def __init__(
        self,
        rules: Sequence[ClassificationRule] | None = None,
        *,
        default_chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self._rules: list[ClassificationRule] = list(rules or ())
        self._records: list[InventoryRecord] = []
        self.default_chunk_size = default_chunk_size

    @property
    def rules(self) -> tuple[ClassificationRule, ...]:
        return tuple(self._rules)

    @property
    def records(self) -> tuple[InventoryRecord, ...]:
        return tuple(self._records)

    def clear_records(self) -> None:
        self._records.clear()

    def register_rule(self, rule: ClassificationRule) -> None:
        if not rule.rule_id.strip():
            raise ValueError("rule_id must be non-empty")
        if any(existing.rule_id == rule.rule_id for existing in self._rules):
            raise ValueError(f"duplicate classification rule id: {rule.rule_id}")
        self._rules.append(rule)
        # Keep stable sort: priority desc, prefix length desc, rule_id asc.
        self._rules.sort(
            key=lambda item: (-item.priority, -len(item.path_prefix), item.rule_id)
        )

    def classify(
        self, relative_path: str
    ) -> tuple[InventoryKind, str, str, str]:
        """Classify using registered rules first, then built-in policy."""

        posix = normalize_relative_path(relative_path)
        for rule in self._rules:
            if rule.matches(posix):
                return (
                    rule.kind,
                    rule.producer,
                    rule.consumer,
                    rule.proposed_authority,
                )
        return classify_path(posix)

    def build_record(
        self,
        absolute_path: Path,
        relative_path: str,
        *,
        chunk_size: int | None = None,
        on_chunk: Callable[[bytes], None] | None = None,
    ) -> InventoryRecord:
        kind, producer, consumer, authority = self.classify(relative_path)
        size, digest = digest_file(
            absolute_path,
            chunk_size=chunk_size if chunk_size is not None else self.default_chunk_size,
            on_chunk=on_chunk,
        )
        return InventoryRecord(
            path=normalize_relative_path(relative_path),
            kind=kind.value,
            size=size,
            digest=digest,
            producer=producer,
            consumer=consumer,
            proposed_authority=authority,
        )

    def scan(
        self,
        roots: Path | str | Sequence[Path | str],
        *,
        relative_to: Path | str | None = None,
        chunk_size: int | None = None,
        follow_symlinks: bool = False,
        skip_dir_names: Iterable[str] | None = None,
        collect: bool = False,
        on_chunk: Callable[[bytes], None] | None = None,
    ) -> Iterator[InventoryRecord]:
        """Stream inventory records for files under ``roots``.

        Records are yielded in deterministic ascending path order. When
        ``collect`` is true, records are also retained on the registry (only
        appropriate for small fixture trees — not multi-hundred-MB corpora).
        """

        root_list = _coerce_roots(roots)
        base = Path(relative_to).resolve(strict=False) if relative_to is not None else None
        if base is None and len(root_list) == 1:
            base = root_list[0]
        skip = frozenset(
            name.lower()
            for name in (
                DEFAULT_SKIP_DIR_NAMES if skip_dir_names is None else skip_dir_names
            )
        )
        effective_chunk = (
            chunk_size if chunk_size is not None else self.default_chunk_size
        )

        file_entries = list(
            _iter_files_deterministic(
                root_list,
                base=base,
                follow_symlinks=follow_symlinks,
                skip_dir_names=skip,
            )
        )
        # Sort by relative path bytes for stable UTF-8 order across locales.
        file_entries.sort(key=lambda item: item[1].encode("utf-8"))

        if collect:
            self._records.clear()

        for absolute, relative in file_entries:
            record = self.build_record(
                absolute,
                relative,
                chunk_size=effective_chunk,
                on_chunk=on_chunk,
            )
            if collect:
                self._records.append(record)
            yield record

    def collect(
        self,
        roots: Path | str | Sequence[Path | str],
        **kwargs: Any,
    ) -> list[InventoryRecord]:
        """Materialize a full inventory list (small trees only)."""

        kwargs = dict(kwargs)
        kwargs["collect"] = True
        return list(self.scan(roots, **kwargs))

    def summary(
        self, records: Sequence[InventoryRecord] | None = None
    ) -> dict[str, Any]:
        """Return deterministic counts for a record sequence or stored records."""

        items = list(records) if records is not None else list(self._records)
        kind_counts = {kind.value: 0 for kind in InventoryKind}
        authority_counts: dict[str, int] = {}
        total_bytes = 0
        for record in items:
            kind_counts[record.kind] = kind_counts.get(record.kind, 0) + 1
            authority_counts[record.proposed_authority] = (
                authority_counts.get(record.proposed_authority, 0) + 1
            )
            total_bytes += record.size
        return {
            "schema_version": SCHEMA_VERSION,
            "record_count": len(items),
            "total_bytes": total_bytes,
            "kind_counts": dict(sorted(kind_counts.items())),
            "authority_counts": dict(sorted(authority_counts.items())),
        }


def _coerce_roots(roots: Path | str | Sequence[Path | str]) -> list[Path]:
    if isinstance(roots, (str, Path, os.PathLike)):
        items: Sequence[Path | str] = [roots]  # type: ignore[list-item]
    else:
        items = roots
    resolved: list[Path] = []
    for root in items:
        path = Path(root).resolve(strict=False)
        if not path.exists():
            raise FileNotFoundError(f"inventory root does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"inventory root is not a directory: {path}")
        resolved.append(path)
    # Deterministic root order.
    resolved.sort(key=lambda item: str(item).encode("utf-8"))
    return resolved


def _iter_files_deterministic(
    roots: Sequence[Path],
    *,
    base: Path | None,
    follow_symlinks: bool,
    skip_dir_names: frozenset[str],
) -> Iterator[tuple[Path, str]]:
    seen: set[str] = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(
            root,
            topdown=True,
            followlinks=follow_symlinks,
        ):
            # Prune skipped directories in-place (deterministic residual order).
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name.lower() not in skip_dir_names
                and not name.endswith(".egg-info")
            )
            current = Path(dirpath)
            for filename in sorted(filenames):
                absolute = current / filename
                if not follow_symlinks and absolute.is_symlink():
                    # Still inventory the symlink target metadata as a file if
                    # it is a regular file; skip dangling / directory links.
                    if not absolute.exists() or absolute.is_dir():
                        continue
                if not absolute.is_file():
                    continue
                rel_base = base if base is not None else root
                try:
                    relative = normalize_relative_path(absolute, root=rel_base)
                except ValueError:
                    # File outside relative_to — skip rather than invent paths.
                    continue
                if relative in seen:
                    continue
                seen.add(relative)
                yield absolute, relative


def scan_inventory(
    roots: Path | str | Sequence[Path | str],
    *,
    relative_to: Path | str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    follow_symlinks: bool = False,
    skip_dir_names: Iterable[str] | None = None,
    registry: InventoryRegistry | None = None,
    collect: bool = False,
    on_chunk: Callable[[bytes], None] | None = None,
) -> Iterator[InventoryRecord]:
    """Stream a deterministic inventory of file-authoritative producers.

    This is the primary DQK-001 entrypoint. It never loads whole file bodies
    into memory; digests are computed in ``chunk_size`` windows.
    """

    active = registry if registry is not None else InventoryRegistry(
        default_chunk_size=chunk_size
    )
    yield from active.scan(
        roots,
        relative_to=relative_to,
        chunk_size=chunk_size,
        follow_symlinks=follow_symlinks,
        skip_dir_names=skip_dir_names,
        collect=collect,
        on_chunk=on_chunk,
    )


def inventory_snapshot(
    roots: Path | str | Sequence[Path | str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a small-tree inventory payload with schema metadata.

    Not intended for multi-hundred-MB corpora — use :func:`scan_inventory`
    for streaming. Useful for fixtures and unit tests.
    """

    records = list(scan_inventory(roots, collect=False, **kwargs))
    registry = InventoryRegistry()
    summary = registry.summary(records)
    return {
        **summary,
        "records": [record.as_dict() for record in records],
    }


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_CHUNK_SIZE",
    "DIGEST_ALGORITHM",
    "DEFAULT_SKIP_DIR_NAMES",
    "REQUIRED_RECORD_FIELDS",
    "InventoryKind",
    "InventoryRecord",
    "ClassificationRule",
    "InventoryRegistry",
    "normalize_relative_path",
    "format_digest",
    "digest_file",
    "classify_path",
    "scan_inventory",
    "inventory_snapshot",
]
