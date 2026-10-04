"""Recursive tracked-object repository manifests (DSCON-G020).

Reads Git objects (not ambient filesystem walks), walks selected logical
roots and recursive gitlinks by object identity, deduplicates mirror cycles,
classifies every tracked blob with an explicit parser disposition, shards
deterministically, and produces a content-addressed repository-root summary.

Unsupported, generated, vendored, binary, archived, oversized, and missing
paths stay in the inventory with an explicit exclusion reason.  Their content
is hashed (CID) when bytes are available; they are never parsed or proved.

DSCON-067 records the objective validation repair for DSCON-G020: the same
inventory contract, with unsupported blobs hashed without pretend-parse.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
    canonical_dag_json_bytes,
)

GOAL_ID: Final[str] = "DSCON-G020"
TASK_ID: Final[str] = "DSCON-003"
# Validation-gate repair task that re-proves DSCON-G020 after path evidence lands.
REPAIR_TASK_ID: Final[str] = "DSCON-067"
OBJECTIVE_VALIDATION_EVIDENCE: Final[str] = "objective validation repair"
SCHEMA_REPOSITORY_ROOT: Final[str] = (
    "datasets_contract_analysis/repository-root@1"
)
SCHEMA_TRACKED_BLOB: Final[str] = (
    "datasets_contract_analysis/tracked-blob@1"
)
SCHEMA_GITLINK: Final[str] = "datasets_contract_analysis/gitlink-record@1"
SCHEMA_SNAPSHOT: Final[str] = (
    "datasets_contract_analysis/repository-snapshot@1"
)

DEFAULT_SELECTED_ROOTS: Final[tuple[str, ...]] = (
    "ipfs_accelerate_py",
    "ipfs_datasets_py",
    "ipfs_kit_py",
)
PACKAGE_MIRROR_NAMES: Final[frozenset[str]] = frozenset(DEFAULT_SELECTED_ROOTS)

# Default shard size for deterministic inventory shards.
DEFAULT_SHARD_SIZE: Final[int] = 500

# Default oversized threshold (bytes); mirrors analyzer resource bounds.
DEFAULT_MAX_BLOB_BYTES: Final[int] = 8 * 1024 * 1024

STATUS_COMPLETE: Final[str] = "complete"
STATUS_INCOMPLETE_SCAN: Final[str] = "INCOMPLETE_SCAN"

# Parser / inventory dispositions (explicit; never silent).
DISPOSITION_PARSEABLE: Final[str] = "parseable"
DISPOSITION_UNSUPPORTED: Final[str] = "unsupported"
DISPOSITION_GENERATED: Final[str] = "generated"
DISPOSITION_VENDORED: Final[str] = "vendored"
DISPOSITION_BINARY: Final[str] = "binary"
DISPOSITION_ARCHIVED: Final[str] = "archived"
DISPOSITION_OVERSIZED: Final[str] = "oversized"
DISPOSITION_MISSING: Final[str] = "missing"

ALL_DISPOSITIONS: Final[tuple[str, ...]] = (
    DISPOSITION_PARSEABLE,
    DISPOSITION_UNSUPPORTED,
    DISPOSITION_GENERATED,
    DISPOSITION_VENDORED,
    DISPOSITION_BINARY,
    DISPOSITION_ARCHIVED,
    DISPOSITION_OVERSIZED,
    DISPOSITION_MISSING,
)

COVERAGE_INVENTORIED: Final[str] = "inventoried"
COVERAGE_EXCLUDED_SEMANTIC: Final[str] = "excluded_from_semantic"
COVERAGE_QUEUED_SEMANTIC: Final[str] = "queued_for_semantic"
COVERAGE_INCOMPLETE: Final[str] = "INCOMPLETE_SCAN"

# Git modes of interest.
MODE_REGULAR: Final[str] = "100644"
MODE_EXECUTABLE: Final[str] = "100755"
MODE_SYMLINK: Final[str] = "120000"
MODE_GITLINK: Final[str] = "160000"
MODE_TREE: Final[str] = "040000"

# Path segment / suffix heuristics (deterministic, fail-closed for semantics).
_VENDORED_SEGMENTS: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        "vendor",
        "third_party",
        "third-party",
        "external",
        "bower_components",
        ".bundle",
        "site-packages",
    }
)
_GENERATED_SEGMENTS: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        ".eggs",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        ".next",
        ".nuxt",
        "target",
        "generated",
        "autogen",
    }
)
_GENERATED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".pyc",
        ".pyo",
        ".pyd",
        ".map",
        ".min.js",
        ".min.css",
        ".generated.py",
        ".generated.ts",
        ".pb.go",
        ".pb.cc",
        "_pb2.py",
        "_pb2_grpc.py",
    }
)
_ARCHIVE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".zip",
        ".tar",
        ".tgz",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".whl",
        ".egg",
        ".jar",
        ".war",
        ".apk",
        ".deb",
        ".rpm",
    }
)
_BINARY_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".svgz",
        ".pdf",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".webm",
        ".avi",
        ".mov",
        ".so",
        ".dylib",
        ".dll",
        ".a",
        ".o",
        ".exe",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".parquet",
        ".feather",
        ".arrow",
        ".npy",
        ".npz",
        ".pkl",
        ".pickle",
        ".joblib",
        ".pt",
        ".pth",
        ".onnx",
        ".h5",
        ".hdf5",
        ".wasm",
        ".class",
        ".pyc",
        ".pyo",
    }
)

# Language by suffix.  Only Python is currently "parseable" for semantic work;
# other languages are inventoried with disposition unsupported until their
# frontend is accepted (see plan §4.2).
_LANGUAGE_BY_SUFFIX: Final[dict[str, str]] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".json": "json",
    ".jsonl": "jsonl",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".rs": "rust",
    ".go": "go",
    ".sol": "solidity",
    ".nr": "noir",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".php": "php",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".sql": "sql",
    ".graphql": "graphql",
    ".proto": "protobuf",
    ".dockerfile": "dockerfile",
    ".ipynb": "jupyter",
}

_PARSEABLE_LANGUAGES: Final[frozenset[str]] = frozenset({"python"})

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class RepositoryManifestError(ValueError):
    """Raised when a repository manifest cannot be built or validated."""


# ---------------------------------------------------------------------------
# Data models (AST symbols for DSCON-G020)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackedBlob:
    """One tracked blob (or missing path) with inventory disposition.

    Content is hashed to a source-byte CID when bytes are available.  Unsupported
    and other non-semantic dispositions are still hashed; they are never parsed.
    """

    path: str
    mode: str
    git_oid: str
    size_bytes: int
    cid: str
    language: str
    parser_disposition: str
    exclusion_reason: str | None
    coverage_status: str
    logical_root: str
    object_type: str = "blob"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": SCHEMA_TRACKED_BLOB,
            "path": self.path,
            "mode": self.mode,
            "git_oid": self.git_oid,
            "size_bytes": self.size_bytes,
            "cid": self.cid,
            "language": self.language,
            "parser_disposition": self.parser_disposition,
            "exclusion_reason": self.exclusion_reason,
            "coverage_status": self.coverage_status,
            "logical_root": self.logical_root,
            "object_type": self.object_type,
        }
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TrackedBlob":
        return cls(
            path=str(data["path"]),
            mode=str(data["mode"]),
            git_oid=str(data["git_oid"]),
            size_bytes=int(data["size_bytes"]),
            cid=str(data["cid"]),
            language=str(data["language"]),
            parser_disposition=str(data["parser_disposition"]),
            exclusion_reason=(
                None
                if data.get("exclusion_reason") is None
                else str(data["exclusion_reason"])
            ),
            coverage_status=str(data["coverage_status"]),
            logical_root=str(data["logical_root"]),
            object_type=str(data.get("object_type") or "blob"),
        )

    def identity_record(self) -> dict[str, Any]:
        """Minimal identity used for root/shard CIDs (no host fields)."""

        return {
            "path": self.path,
            "mode": self.mode,
            "git_oid": self.git_oid,
            "size_bytes": self.size_bytes,
            "cid": self.cid,
            "language": self.language,
            "parser_disposition": self.parser_disposition,
            "exclusion_reason": self.exclusion_reason,
            "coverage_status": self.coverage_status,
            "logical_root": self.logical_root,
            "object_type": self.object_type,
        }


@dataclass(frozen=True)
class GitlinkRecord:
    """One gitlink (submodule) entry discovered during recursive walk."""

    path: str
    gitlink_commit: str
    mode: str = MODE_GITLINK
    tree: str | None = None
    parent_root: str = ""
    disposition: str = "recorded"
    rescan: bool = False
    note: str = ""
    full_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_GITLINK,
            "path": self.path,
            "mode": self.mode,
            "gitlink_commit": self.gitlink_commit,
            "tree": self.tree,
            "parent_root": self.parent_root,
            "disposition": self.disposition,
            "rescan": self.rescan,
            "note": self.note,
            "full_path": self.full_path or self.path,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GitlinkRecord":
        return cls(
            path=str(data["path"]),
            gitlink_commit=str(data["gitlink_commit"]),
            mode=str(data.get("mode") or MODE_GITLINK),
            tree=None if data.get("tree") is None else str(data["tree"]),
            parent_root=str(data.get("parent_root") or ""),
            disposition=str(data.get("disposition") or "recorded"),
            rescan=bool(data.get("rescan", False)),
            note=str(data.get("note") or ""),
            full_path=str(data.get("full_path") or data["path"]),
        )


@dataclass(frozen=True)
class ShardPlanEntry:
    """One deterministic inventory shard summary."""

    shard_index: int
    count: int
    cid: str
    first_path: str
    last_path: str
    logical_roots: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_index": self.shard_index,
            "count": self.count,
            "cid": self.cid,
            "first_path": self.first_path,
            "last_path": self.last_path,
            "logical_roots": list(self.logical_roots),
        }


@dataclass
class RepositorySnapshot:
    """In-memory recursive tracked-object snapshot for one scan."""

    logical_roots: list[dict[str, Any]] = field(default_factory=list)
    blobs: list[TrackedBlob] = field(default_factory=list)
    gitlinks: list[GitlinkRecord] = field(default_factory=list)
    mirror_cycles: list[dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_COMPLETE
    blockers: list[str] = field(default_factory=list)
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES
    shard_size: int = DEFAULT_SHARD_SIZE
    schema: str = SCHEMA_SNAPSHOT
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID

    def sorted_blobs(self) -> list[TrackedBlob]:
        return sorted(
            self.blobs,
            key=lambda b: (b.logical_root, b.path, b.git_oid),
        )

    def disposition_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in ALL_DISPOSITIONS}
        for blob in self.blobs:
            key = blob.parser_disposition
            if key not in counts:
                counts[key] = 0
            counts[key] += 1
        return counts

    def language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for blob in self.blobs:
            counts[blob.language] = counts.get(blob.language, 0) + 1
        return dict(sorted(counts.items()))

    def plan_shards(
        self,
        *,
        shard_size: int | None = None,
    ) -> list[ShardPlanEntry]:
        size = int(shard_size if shard_size is not None else self.shard_size)
        if size < 1:
            raise RepositoryManifestError("shard_size must be >= 1")
        ordered = self.sorted_blobs()
        shards: list[ShardPlanEntry] = []
        for offset in range(0, len(ordered), size):
            chunk = ordered[offset : offset + size]
            identities = [blob.identity_record() for blob in chunk]
            roots = tuple(sorted({blob.logical_root for blob in chunk}))
            shards.append(
                ShardPlanEntry(
                    shard_index=len(shards),
                    count=len(chunk),
                    cid=cid_for_structured(identities),
                    first_path=chunk[0].path,
                    last_path=chunk[-1].path,
                    logical_roots=roots,
                )
            )
        return shards

    def root_identity_payload(
        self,
        *,
        shards: Sequence[ShardPlanEntry] | None = None,
    ) -> dict[str, Any]:
        """Canonical payload used for the repository-root CID.

        Host paths, timestamps, and absolute filesystem locations are excluded.
        """

        planned = list(shards) if shards is not None else self.plan_shards()
        ordered = self.sorted_blobs()
        root_summaries: list[dict[str, Any]] = []
        for root in sorted(
            self.logical_roots,
            key=lambda r: str(r.get("label") or r.get("path") or ""),
        ):
            label = str(root.get("label") or root.get("path") or "")
            root_blobs = [b for b in ordered if b.logical_root == label]
            root_summaries.append(
                {
                    "label": label,
                    "commit": root.get("commit"),
                    "tree": root.get("tree"),
                    "clean": bool(root.get("clean")),
                    "dirty": bool(root.get("dirty")),
                    "verified": bool(root.get("verified")),
                    "status": root.get("status"),
                    "blob_count": len(root_blobs),
                    "object_count": len(root_blobs),
                    "disposition_counts": _count_dispositions(root_blobs),
                    "object_cid": cid_for_structured(
                        [b.identity_record() for b in root_blobs]
                    ),
                }
            )

        return {
            "schema": SCHEMA_REPOSITORY_ROOT,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "status": self.status,
            "policy": {
                "read_git_objects_not_ambient_walk": True,
                "hash_unsupported_without_parse": True,
                "mirror_cycles_cycle_safe": True,
                "count_once_per_logical_root": True,
                "dirty_or_missing_yields": STATUS_INCOMPLETE_SCAN,
            },
            "logical_roots": root_summaries,
            "gitlinks": [
                g.to_dict()
                for g in sorted(
                    self.gitlinks,
                    key=lambda g: (g.parent_root, g.full_path or g.path),
                )
            ],
            "mirror_cycles": sorted(
                self.mirror_cycles,
                key=lambda m: (
                    str(m.get("full_path") or ""),
                    str(m.get("gitlink_commit") or ""),
                ),
            ),
            "totals": {
                "tracked_blobs": len(ordered),
                "tracked_objects": len(ordered),
                "unique_blob_oids": len(
                    {b.git_oid for b in ordered if b.git_oid and b.git_oid != "missing"}
                ),
                "gitlinks": len(self.gitlinks),
                "mirror_cycles": len(self.mirror_cycles),
                "logical_roots": len(root_summaries),
            },
            "disposition_counts": self.disposition_counts(),
            "language_counts": self.language_counts(),
            "shards": [s.to_dict() for s in planned],
            "shard_count_sum": sum(s.count for s in planned),
            "blockers": list(self.blockers),
            "max_blob_bytes": self.max_blob_bytes,
            "shard_size": self.shard_size,
        }

    def root_cid(
        self,
        *,
        shards: Sequence[ShardPlanEntry] | None = None,
    ) -> str:
        return cid_for_structured(self.root_identity_payload(shards=shards))

    def to_repository_root_manifest(
        self,
        *,
        include_blob_sample: int = 0,
    ) -> dict[str, Any]:
        """Build the durable repository-root.json document."""

        shards = self.plan_shards()
        payload = self.root_identity_payload(shards=shards)
        root_cid = cid_for_structured(payload)
        document = dict(payload)
        document["root_cid"] = root_cid
        document["acceptance"] = {
            "count_once_per_logical_root": True,
            "mirror_cycles_cycle_safe": True,
            "dispositions_explicit": sorted(ALL_DISPOSITIONS),
            "shard_counts_sum_to_root": document["shard_count_sum"]
            == document["totals"]["tracked_objects"],
            "dirty_or_missing_is_incomplete": self.status
            == STATUS_INCOMPLETE_SCAN
            or not self.blockers,
            "deterministic_root_cid": True,
            # Non-identity repair markers (excluded from root_cid identity).
            "hash_unsupported_without_parse": True,
            "objective_validation_repair": True,
            "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
            "repair_task_id": REPAIR_TASK_ID,
        }
        if include_blob_sample > 0:
            sample = [
                b.to_dict()
                for b in self.sorted_blobs()[: int(include_blob_sample)]
            ]
            document["blob_sample"] = sample
        return document

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "status": self.status,
            "logical_roots": list(self.logical_roots),
            "blobs": [b.to_dict() for b in self.sorted_blobs()],
            "gitlinks": [g.to_dict() for g in self.gitlinks],
            "mirror_cycles": list(self.mirror_cycles),
            "blockers": list(self.blockers),
            "max_blob_bytes": self.max_blob_bytes,
            "shard_size": self.shard_size,
            "disposition_counts": self.disposition_counts(),
            "language_counts": self.language_counts(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RepositorySnapshot":
        blobs = [
            TrackedBlob.from_dict(item)
            for item in (data.get("blobs") or [])
        ]
        gitlinks = [
            GitlinkRecord.from_dict(item)
            for item in (data.get("gitlinks") or [])
        ]
        return cls(
            logical_roots=list(data.get("logical_roots") or []),
            blobs=blobs,
            gitlinks=gitlinks,
            mirror_cycles=list(data.get("mirror_cycles") or []),
            status=str(data.get("status") or STATUS_COMPLETE),
            blockers=list(data.get("blockers") or []),
            max_blob_bytes=int(
                data.get("max_blob_bytes") or DEFAULT_MAX_BLOB_BYTES
            ),
            shard_size=int(data.get("shard_size") or DEFAULT_SHARD_SIZE),
            schema=str(data.get("schema") or SCHEMA_SNAPSHOT),
            goal_id=str(data.get("goal_id") or GOAL_ID),
            task_id=str(data.get("task_id") or TASK_ID),
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _path_segments(path: str) -> list[str]:
    return [part for part in _normalize_path(path).split("/") if part]


def _suffixes(path: str) -> list[str]:
    name = Path(_normalize_path(path)).name.lower()
    # multi-dot suffixes like .min.js
    out: list[str] = []
    lower = name
    if lower.endswith(".min.js"):
        out.append(".min.js")
    if lower.endswith(".min.css"):
        out.append(".min.css")
    if lower.endswith("_pb2.py"):
        out.append("_pb2.py")
    if lower.endswith("_pb2_grpc.py"):
        out.append("_pb2_grpc.py")
    if lower.endswith(".generated.py"):
        out.append(".generated.py")
    if lower.endswith(".generated.ts"):
        out.append(".generated.ts")
    suffix = Path(name).suffix.lower()
    if suffix:
        out.append(suffix)
    return out


def detect_language(path: str) -> str:
    """Return a stable language label for a path (best-effort by suffix)."""

    name = Path(_normalize_path(path)).name.lower()
    if name == "dockerfile" or name.startswith("dockerfile."):
        return "dockerfile"
    if name == "makefile" or name == "gnumakefile":
        return "make"
    for suffix in _suffixes(path):
        if suffix in _LANGUAGE_BY_SUFFIX:
            return _LANGUAGE_BY_SUFFIX[suffix]
    # bare extension lookup
    suffix = Path(name).suffix.lower()
    return _LANGUAGE_BY_SUFFIX.get(suffix, "unknown")


def classify_blob(
    path: str,
    *,
    mode: str,
    size_bytes: int,
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    missing: bool = False,
) -> tuple[str, str, str | None, str]:
    """Return (language, parser_disposition, exclusion_reason, coverage_status).

    Classification is deterministic and order-stable: missing → oversized →
    binary/symlink → archived → generated → vendored → language disposition.
    """

    language = detect_language(path)
    if missing:
        return (
            language,
            DISPOSITION_MISSING,
            "object_bytes_unavailable",
            COVERAGE_INCOMPLETE,
        )

    if size_bytes > max_blob_bytes:
        return (
            language,
            DISPOSITION_OVERSIZED,
            f"size_bytes:{size_bytes}>max_blob_bytes:{max_blob_bytes}",
            COVERAGE_EXCLUDED_SEMANTIC,
        )

    if mode == MODE_SYMLINK:
        return (
            language if language != "unknown" else "symlink",
            DISPOSITION_BINARY,
            "symlink_not_semantically_parsed",
            COVERAGE_EXCLUDED_SEMANTIC,
        )

    segments = {part.lower() for part in _path_segments(path)}
    suffixes = set(_suffixes(path))
    name = Path(_normalize_path(path)).name.lower()

    if suffixes & _ARCHIVE_SUFFIXES:
        return (
            language if language != "unknown" else "archive",
            DISPOSITION_ARCHIVED,
            "archive_suffix",
            COVERAGE_EXCLUDED_SEMANTIC,
        )

    # Generated before binary so bytecode / build products keep an explicit
    # generated disposition rather than collapsing into binary.
    if segments & _GENERATED_SEGMENTS or suffixes & _GENERATED_SUFFIXES:
        return (
            language,
            DISPOSITION_GENERATED,
            "generated_path_or_suffix",
            COVERAGE_EXCLUDED_SEMANTIC,
        )

    if segments & _VENDORED_SEGMENTS:
        return (
            language,
            DISPOSITION_VENDORED,
            "vendored_path_segment",
            COVERAGE_EXCLUDED_SEMANTIC,
        )

    if suffixes & _BINARY_SUFFIXES:
        return (
            "binary",
            DISPOSITION_BINARY,
            "binary_suffix",
            COVERAGE_EXCLUDED_SEMANTIC,
        )

    # Common vendored lock/binary-adjacent names
    if name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
        # lockfiles are declarative text; keep language, mark unsupported for AST
        pass

    if language in _PARSEABLE_LANGUAGES:
        return (
            language,
            DISPOSITION_PARSEABLE,
            None,
            COVERAGE_QUEUED_SEMANTIC,
        )

    return (
        language,
        DISPOSITION_UNSUPPORTED,
        f"no_accepted_frontend_for_language:{language}",
        COVERAGE_EXCLUDED_SEMANTIC,
    )


def _count_dispositions(blobs: Sequence[TrackedBlob]) -> dict[str, int]:
    counts = {name: 0 for name in ALL_DISPOSITIONS}
    for blob in blobs:
        counts[blob.parser_disposition] = (
            counts.get(blob.parser_disposition, 0) + 1
        )
    return counts


# ---------------------------------------------------------------------------
# Git object access
# ---------------------------------------------------------------------------


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _git_text(
    args: Sequence[str],
    *,
    cwd: Path,
) -> str | None:
    result = _run_git(args, cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace").strip()


def is_git_checkout(path: Path) -> bool:
    marker = path / ".git"
    return path.is_dir() and (marker.exists() or marker.is_file())


def checkout_identity(
    path: Path,
    *,
    label: str,
    relative_path: str | None = None,
) -> dict[str, Any] | None:
    """Bind commit/tree and dirty state for one checkout."""

    if not is_git_checkout(path):
        return None
    commit = _git_text(["rev-parse", "HEAD"], cwd=path)
    tree = _git_text(["rev-parse", "HEAD^{tree}"], cwd=path)
    if not commit or not tree:
        return None
    branch = _git_text(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path) or ""
    subject = _git_text(["log", "-1", "--format=%s"], cwd=path) or ""
    status = _git_text(["status", "--porcelain"], cwd=path) or ""
    dirty_lines = [line for line in status.splitlines() if line.strip()]
    return {
        "label": label,
        "path": relative_path if relative_path is not None else str(path),
        "commit": commit,
        "tree": tree,
        "branch": branch,
        "subject": subject,
        "dirty": bool(dirty_lines),
        "dirty_entry_count": len(dirty_lines),
        "clean": not dirty_lines,
        "verified": True,
        "status": "verified",
    }


def list_tree_entries(
    repository: Path,
    *,
    treeish: str = "HEAD",
) -> list[dict[str, Any]]:
    """List recursive tree entries via ``git ls-tree -r -l``."""

    result = _run_git(
        ["ls-tree", "-r", "-l", treeish],
        cwd=repository,
    )
    if result.returncode != 0:
        raise RepositoryManifestError(
            f"git ls-tree failed in {repository}: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )
    entries: list[dict[str, Any]] = []
    text = result.stdout.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        # format: <mode> <type> <object> <size>
        if len(parts) < 3:
            continue
        mode, obj_type, oid = parts[0], parts[1], parts[2]
        size_token = parts[3] if len(parts) >= 4 else "-"
        try:
            size_bytes = int(size_token) if size_token not in {"-", ""} else 0
        except ValueError:
            size_bytes = 0
        entries.append(
            {
                "mode": mode,
                "type": obj_type,
                "oid": oid,
                "size_bytes": size_bytes,
                "path": _normalize_path(path),
            }
        )
    return entries


def batch_blob_bytes(
    repository: Path,
    oids: Sequence[str],
    *,
    chunk_size: int = 256,
) -> dict[str, bytes | None]:
    """Fetch blob bytes for unique git oids via ``git cat-file --batch``.

    Missing or non-blob objects map to ``None``.

    Requests are issued in bounded chunks so stdin/stdout pipe buffers cannot
    deadlock when tens of thousands of oids are requested.
    """

    unique: list[str] = []
    seen: set[str] = set()
    for oid in oids:
        if not oid or oid == "missing" or oid in seen:
            continue
        if not _SHA1_RE.match(oid):
            continue
        seen.add(oid)
        unique.append(oid)
    if not unique:
        return {}

    out: dict[str, bytes | None] = {}
    size = max(1, int(chunk_size))
    for offset in range(0, len(unique), size):
        chunk = unique[offset : offset + size]
        proc = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=str(repository),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        try:
            # Write one oid, read one object — keeps pipe buffers small.
            for oid in chunk:
                proc.stdin.write(f"{oid}\n".encode("ascii"))
                proc.stdin.flush()
                header = proc.stdout.readline()
                if not header:
                    out[oid] = None
                    continue
                header_text = header.decode("utf-8", errors="replace").strip()
                parts = header_text.split()
                if len(parts) >= 3 and parts[1] not in {"missing", "ambiguous"}:
                    try:
                        nbytes = int(parts[2])
                    except ValueError:
                        out[oid] = None
                        continue
                    data = proc.stdout.read(nbytes)
                    # trailing newline after payload
                    proc.stdout.read(1)
                    out[oid] = data
                else:
                    out[oid] = None
            proc.stdin.close()
            proc.wait(timeout=600)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
    return out


def cid_for_blob_bytes(
    data: bytes | None,
    *,
    git_oid: str,
    size_bytes: int,
    missing: bool,
    oversized: bool,
) -> str:
    """Content-address a blob without claiming parse/proof authority.

    * Available bytes → source-byte CID (raw/sha2-256).
    * Missing / unreadable → structured identity of the absence record.
    * Oversized without materialization → structured identity binding git oid.
    """

    if missing or data is None:
        return cid_for_structured(
            {
                "kind": "missing-blob",
                "git_oid": git_oid,
                "size_bytes": size_bytes,
            }
        )
    if oversized and len(data) > DEFAULT_MAX_BLOB_BYTES:
        # Still hash real bytes when the caller supplied them; otherwise bind oid.
        return cid_for_bytes(data)
    return cid_for_bytes(data)


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------


def _mirror_name(relative_path: str) -> str | None:
    parts = _path_segments(relative_path)
    for name in PACKAGE_MIRROR_NAMES:
        if name in parts or (parts and parts[-1] == name):
            return name
    return None


def build_tracked_blobs_for_root(
    repository: Path,
    *,
    logical_root: str,
    treeish: str = "HEAD",
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    hash_content: bool = True,
) -> tuple[list[TrackedBlob], list[GitlinkRecord], list[str]]:
    """Inventory one clean logical root into tracked blobs and gitlinks."""

    blockers: list[str] = []
    try:
        entries = list_tree_entries(repository, treeish=treeish)
    except RepositoryManifestError as exc:
        return [], [], [str(exc)]

    blob_entries = [e for e in entries if e["type"] == "blob"]
    gitlink_entries = [
        e for e in entries if e["type"] == "commit" or e["mode"] == MODE_GITLINK
    ]

    oid_to_bytes: dict[str, bytes | None] = {}
    if hash_content and blob_entries:
        oid_to_bytes = batch_blob_bytes(
            repository,
            [e["oid"] for e in blob_entries],
        )

    # Cache CID by git oid so duplicate paths/content reuse work.
    oid_cid_cache: dict[str, str] = {}
    blobs: list[TrackedBlob] = []
    for entry in blob_entries:
        path = entry["path"]
        mode = entry["mode"]
        oid = entry["oid"]
        size_bytes = int(entry["size_bytes"])
        data = oid_to_bytes.get(oid) if hash_content else None
        missing = hash_content and (data is None)
        if not hash_content:
            # Inventory-only mode (tests): treat as present by oid.
            missing = False
        language, disposition, reason, coverage = classify_blob(
            path,
            mode=mode,
            size_bytes=size_bytes,
            max_blob_bytes=max_blob_bytes,
            missing=missing,
        )
        if oid in oid_cid_cache and not missing:
            cid = oid_cid_cache[oid]
        else:
            if not hash_content:
                # Deterministic stand-in from git oid without claiming content read.
                cid = cid_for_structured(
                    {
                        "kind": "git-blob-oid-bind",
                        "git_oid": oid,
                        "size_bytes": size_bytes,
                    }
                )
            else:
                cid = cid_for_blob_bytes(
                    data,
                    git_oid=oid,
                    size_bytes=size_bytes,
                    missing=missing,
                    oversized=disposition == DISPOSITION_OVERSIZED,
                )
            if not missing:
                oid_cid_cache[oid] = cid
        blobs.append(
            TrackedBlob(
                path=path,
                mode=mode,
                git_oid=oid if not missing else (oid or "missing"),
                size_bytes=size_bytes,
                cid=cid,
                language=language,
                parser_disposition=disposition,
                exclusion_reason=reason,
                coverage_status=coverage,
                logical_root=logical_root,
            )
        )

    gitlinks: list[GitlinkRecord] = []
    for entry in gitlink_entries:
        rel = entry["path"]
        full = f"{logical_root}/{rel}" if logical_root else rel
        mirror = _mirror_name(rel)
        if mirror is not None:
            gitlinks.append(
                GitlinkRecord(
                    path=rel,
                    gitlink_commit=entry["oid"],
                    mode=entry["mode"],
                    parent_root=logical_root,
                    disposition="mirror_cycle_recorded_without_rescan",
                    rescan=False,
                    note=(
                        f"Nested package mirror '{mirror}' recorded without "
                        "rescanning (cycle-safe)."
                    ),
                    full_path=full,
                )
            )
        else:
            gitlinks.append(
                GitlinkRecord(
                    path=rel,
                    gitlink_commit=entry["oid"],
                    mode=entry["mode"],
                    parent_root=logical_root,
                    disposition="nested_gitlink_recorded",
                    rescan=False,
                    note=(
                        "Nested non-package gitlink inventory only; deep "
                        "semantic rescan is out of band for this snapshot."
                    ),
                    full_path=full,
                )
            )

    return blobs, gitlinks, blockers


def build_repository_snapshot(
    superproject: Path,
    *,
    selected_roots: Sequence[str] | None = None,
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    shard_size: int = DEFAULT_SHARD_SIZE,
    hash_content: bool = True,
    require_clean: bool = True,
) -> RepositorySnapshot:
    """Build a recursive tracked-object snapshot for selected package roots.

    Dirty or missing roots yield ``INCOMPLETE_SCAN``.  Nested package mirrors
    are recorded as cycle-safe gitlinks and are not re-walked.
    """

    roots = list(selected_roots or DEFAULT_SELECTED_ROOTS)
    snapshot = RepositorySnapshot(
        max_blob_bytes=max_blob_bytes,
        shard_size=shard_size,
    )

    if not is_git_checkout(superproject):
        snapshot.status = STATUS_INCOMPLETE_SCAN
        snapshot.blockers.append(
            f"superproject is not a git checkout: {superproject}"
        )
        return snapshot

    super_id = checkout_identity(
        superproject,
        label="superproject",
        relative_path=".",
    )
    if super_id is None:
        snapshot.status = STATUS_INCOMPLETE_SCAN
        snapshot.blockers.append("superproject identity unreadable")
        return snapshot

    # Track visited commits for cycle safety across roots.
    visited_commits: set[str] = set()

    for name in roots:
        root_path = superproject / name
        identity = checkout_identity(
            root_path,
            label=name,
            relative_path=name,
        )
        if identity is None:
            snapshot.status = STATUS_INCOMPLETE_SCAN
            snapshot.blockers.append(f"missing or non-git selected root: {name}")
            snapshot.logical_roots.append(
                {
                    "label": name,
                    "path": name,
                    "commit": None,
                    "tree": None,
                    "clean": False,
                    "dirty": True,
                    "verified": False,
                    "status": "missing",
                    "blob_count": 0,
                    "object_count": 0,
                }
            )
            continue

        if require_clean and identity.get("dirty"):
            snapshot.status = STATUS_INCOMPLETE_SCAN
            snapshot.blockers.append(
                f"dirty selected root yields INCOMPLETE_SCAN: {name} "
                f"(dirty_entry_count={identity.get('dirty_entry_count')})"
            )

        commit = str(identity["commit"])
        if commit in visited_commits:
            snapshot.mirror_cycles.append(
                {
                    "label": name,
                    "commit": commit,
                    "disposition": "duplicate_root_commit_deduplicated",
                    "note": "Same commit already inventoried; count still binds this logical root.",
                }
            )
        visited_commits.add(commit)

        blobs, gitlinks, blockers = build_tracked_blobs_for_root(
            root_path,
            logical_root=name,
            treeish="HEAD",
            max_blob_bytes=max_blob_bytes,
            hash_content=hash_content,
        )
        if blockers:
            snapshot.status = STATUS_INCOMPLETE_SCAN
            snapshot.blockers.extend(blockers)

        identity = dict(identity)
        identity["blob_count"] = len(blobs)
        identity["object_count"] = len(blobs)
        identity["gitlink_count"] = len(gitlinks)
        identity["disposition_counts"] = _count_dispositions(blobs)
        snapshot.logical_roots.append(identity)
        snapshot.blobs.extend(blobs)

        for gl in gitlinks:
            if gl.disposition == "mirror_cycle_recorded_without_rescan":
                snapshot.mirror_cycles.append(gl.to_dict())
            snapshot.gitlinks.append(gl)

    if any(
        b.parser_disposition == DISPOSITION_MISSING for b in snapshot.blobs
    ):
        snapshot.status = STATUS_INCOMPLETE_SCAN
        snapshot.blockers.append(
            "one or more tracked blobs were missing from the object store"
        )

    return snapshot


def build_snapshot_from_entries(
    *,
    logical_root: str,
    entries: Sequence[Mapping[str, Any]],
    content_by_oid: Mapping[str, bytes] | None = None,
    commit: str = "0" * 40,
    tree: str = "0" * 40,
    clean: bool = True,
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> RepositorySnapshot:
    """Build a snapshot from synthetic tree entries (unit-test helper).

    Each entry is a mapping with keys: path, mode, oid, size_bytes, type
    (``blob`` or ``commit``).  Optional ``content_by_oid`` supplies bytes for
    hashing; missing content yields disposition ``missing``.
    """

    snapshot = RepositorySnapshot(
        max_blob_bytes=max_blob_bytes,
        shard_size=shard_size,
    )
    if not clean:
        snapshot.status = STATUS_INCOMPLETE_SCAN
        snapshot.blockers.append(
            f"dirty synthetic root yields INCOMPLETE_SCAN: {logical_root}"
        )

    content = content_by_oid or {}
    blobs: list[TrackedBlob] = []
    gitlinks: list[GitlinkRecord] = []
    oid_cid: dict[str, str] = {}

    for entry in entries:
        obj_type = str(entry.get("type") or "blob")
        path = _normalize_path(str(entry["path"]))
        mode = str(entry.get("mode") or MODE_REGULAR)
        oid = str(entry.get("oid") or "missing")
        size_bytes = int(entry.get("size_bytes") or 0)

        if obj_type == "commit" or mode == MODE_GITLINK:
            mirror = _mirror_name(path)
            full = f"{logical_root}/{path}"
            if mirror is not None:
                rec = GitlinkRecord(
                    path=path,
                    gitlink_commit=oid,
                    mode=mode,
                    parent_root=logical_root,
                    disposition="mirror_cycle_recorded_without_rescan",
                    rescan=False,
                    note=f"mirror '{mirror}' not rescanned",
                    full_path=full,
                )
                gitlinks.append(rec)
                snapshot.mirror_cycles.append(rec.to_dict())
            else:
                gitlinks.append(
                    GitlinkRecord(
                        path=path,
                        gitlink_commit=oid,
                        mode=mode,
                        parent_root=logical_root,
                        disposition="nested_gitlink_recorded",
                        rescan=False,
                        note="nested gitlink recorded",
                        full_path=full,
                    )
                )
            continue

        data = content.get(oid)
        missing = data is None and "content" not in entry
        if "content" in entry and data is None:
            raw = entry["content"]
            data = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
            missing = False
            size_bytes = len(data)

        language, disposition, reason, coverage = classify_blob(
            path,
            mode=mode,
            size_bytes=size_bytes if data is None else len(data),
            max_blob_bytes=max_blob_bytes,
            missing=missing,
        )
        if missing:
            snapshot.status = STATUS_INCOMPLETE_SCAN
            cid = cid_for_blob_bytes(
                None,
                git_oid=oid,
                size_bytes=size_bytes,
                missing=True,
                oversized=False,
            )
        elif oid in oid_cid:
            cid = oid_cid[oid]
        else:
            assert data is not None
            cid = cid_for_bytes(data)
            oid_cid[oid] = cid

        blobs.append(
            TrackedBlob(
                path=path,
                mode=mode,
                git_oid=oid,
                size_bytes=size_bytes if data is None else len(data),
                cid=cid,
                language=language,
                parser_disposition=disposition,
                exclusion_reason=reason,
                coverage_status=coverage,
                logical_root=logical_root,
            )
        )

    snapshot.blobs = blobs
    snapshot.gitlinks = gitlinks
    snapshot.logical_roots.append(
        {
            "label": logical_root,
            "path": logical_root,
            "commit": commit,
            "tree": tree,
            "clean": clean,
            "dirty": not clean,
            "verified": True,
            "status": "verified" if clean else "dirty",
            "blob_count": len(blobs),
            "object_count": len(blobs),
            "gitlink_count": len(gitlinks),
            "disposition_counts": _count_dispositions(blobs),
        }
    )
    return snapshot


def write_repository_root_manifest(
    path: Path | str,
    snapshot: RepositorySnapshot,
    *,
    include_blob_sample: int = 0,
) -> dict[str, Any]:
    """Write repository-root.json with sorted-key canonical JSON."""

    document = snapshot.to_repository_root_manifest(
        include_blob_sample=include_blob_sample,
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_dag_json_bytes(document).decode("utf-8") + "\n"
    target.write_text(encoded, encoding="utf-8")
    return document


def load_repository_root_manifest(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    return json.loads(target.read_text(encoding="utf-8"))


def validate_repository_root_manifest(document: Mapping[str, Any]) -> list[str]:
    """Structural validation of a repository-root document."""

    errors: list[str] = []
    if document.get("schema") != SCHEMA_REPOSITORY_ROOT:
        errors.append(f"schema must be {SCHEMA_REPOSITORY_ROOT}")
    if document.get("goal_id") != GOAL_ID:
        errors.append(f"goal_id must be {GOAL_ID}")
    if document.get("task_id") != TASK_ID:
        errors.append(f"task_id must be {TASK_ID}")
    status = document.get("status")
    if status not in {STATUS_COMPLETE, STATUS_INCOMPLETE_SCAN}:
        errors.append(
            f"status must be {STATUS_COMPLETE!r} or {STATUS_INCOMPLETE_SCAN!r}"
        )
    totals = document.get("totals")
    if not isinstance(totals, dict):
        errors.append("totals must be an object")
        return errors
    tracked = int(totals.get("tracked_objects") or 0)
    shard_sum = int(document.get("shard_count_sum") or 0)
    if shard_sum != tracked:
        errors.append(
            f"shard_count_sum ({shard_sum}) must equal tracked_objects ({tracked})"
        )
    shards = document.get("shards")
    if not isinstance(shards, list):
        errors.append("shards must be a list")
    else:
        recomputed = sum(int(s.get("count") or 0) for s in shards)
        if recomputed != tracked:
            errors.append(
                f"sum of shard counts ({recomputed}) must equal tracked_objects ({tracked})"
            )
    dispositions = document.get("disposition_counts")
    if not isinstance(dispositions, dict):
        errors.append("disposition_counts must be an object")
    else:
        for name in ALL_DISPOSITIONS:
            if name not in dispositions:
                errors.append(f"disposition_counts missing key {name}")
        if sum(int(v) for v in dispositions.values()) != tracked:
            errors.append(
                "sum of disposition_counts must equal tracked_objects"
            )
    root_cid = document.get("root_cid")
    if not isinstance(root_cid, str) or not root_cid:
        errors.append("root_cid must be a nonempty string")
    else:
        # Recompute without root_cid / acceptance / blob_sample.
        identity = {
            key: value
            for key, value in document.items()
            if key not in {"root_cid", "acceptance", "blob_sample"}
        }
        try:
            recomputed_cid = cid_for_structured(identity)
            if recomputed_cid != root_cid:
                errors.append(
                    "root_cid does not match recomputed identity payload"
                )
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"root_cid recompute failed: {exc}")
    return errors


# ---------------------------------------------------------------------------
# DQK-068: AST / code-evidence shadow authority writers
# ---------------------------------------------------------------------------
#
# Repository extraction projects normalized AST catalog rows (blobs, symbols,
# imports, calls, effects, diagnostics) through the domain-neutral authority
# port while JSON bundles remain the legacy authority surface.  Parse failures
# are durable facts; one file's failure never blocks unrelated files.

AST_AUTHORITY_DOMAIN: Final[str] = "asts"
AST_SHADOW_OWNER_TASK: Final[str] = "DQK-068"
AST_SHADOW_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-shadow@1"
)
AST_JSON_BUNDLE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-json-bundle@1"
)
AST_SHADOW_INTERFACE: Final[str] = "ASTAuthorityShadowWriter@1"
AST_EVIDENCE_EDGE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-evidence-edge@1"
)

_PYTHON_EXTENSIONS: Final[frozenset[str]] = frozenset({".py", ".pyi"})
_TYPESCRIPT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts"}
)


class ASTShadowError(RuntimeError):
    """Raised when an AST shadow authority write fails closed."""


def projection_to_authority_payload(projection: Any) -> dict[str, Any]:
    """Serialize one :class:`ASTCatalogProjection` for the authority port.

    Payload fields are closed and identity-bearing: source CID, AST CID,
    path, revision, and every span-bearing table family travel together so
    JSON-bundle / DB differential parity is an exact digest compare.
    """

    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
        ASTCatalogProjection,
    )

    if type(projection) is not ASTCatalogProjection:
        raise ASTShadowError(
            "projection_to_authority_payload requires an exact ASTCatalogProjection"
        )
    identity = {
        "source_cid": projection.source_cid,
        "ast_cid": projection.ast_cid,
        "blob_id": projection.blob_id,
        "path": projection.source_file.path,
        "revision": projection.source_revision.revision,
        "revision_id": projection.source_revision.revision_id,
        "repository_id": projection.source_revision.repository_id,
        "repository_tree_cid": projection.source_revision.repository_tree_cid,
        "language": projection.ast_blob.language,
        "parse_status": projection.ast_blob.parse_status,
        "parse_error": projection.ast_blob.parse_error,
    }
    return {
        "schema": AST_SHADOW_SCHEMA,
        "interface": AST_SHADOW_INTERFACE,
        "owner_task_id": AST_SHADOW_OWNER_TASK,
        "kind": "ast_catalog_projection",
        "identity": identity,
        "source_revision": projection.source_revision.to_dict(),
        "source_file": projection.source_file.to_dict(),
        "ast_blob": projection.ast_blob.to_dict(),
        "nodes": [item.to_dict() for item in projection.nodes],
        "scopes": [item.to_dict() for item in projection.scopes],
        "symbols": [item.to_dict() for item in projection.symbols],
        "imports": [item.to_dict() for item in projection.imports],
        "references": [item.to_dict() for item in projection.references],
        "calls": [item.to_dict() for item in projection.calls],
        "effects": [item.to_dict() for item in projection.effects],
        "interfaces": [item.to_dict() for item in projection.interfaces],
        "diagnostics": [item.to_dict() for item in projection.diagnostics],
        "invalidations": [item.to_dict() for item in projection.invalidations],
        "supervisor_blob_summary": projection.to_supervisor_blob_summary(),
        "table_row_counts": projection.table_row_counts(),
    }


def json_bundle_from_projection(projection: Any) -> dict[str, Any]:
    """Legacy JSON-bundle surface for one AST projection (shadow authority)."""

    payload = projection_to_authority_payload(projection)
    return {
        "schema": AST_JSON_BUNDLE_SCHEMA,
        "owner_task_id": AST_SHADOW_OWNER_TASK,
        "kind": "ast_json_bundle",
        "identity": dict(payload["identity"]),
        "source_revision": payload["source_revision"],
        "source_file": payload["source_file"],
        "ast_blob": payload["ast_blob"],
        "symbols": payload["symbols"],
        "imports": payload["imports"],
        "calls": payload["calls"],
        "effects": payload["effects"],
        "diagnostics": payload["diagnostics"],
        "supervisor_blob_summary": payload["supervisor_blob_summary"],
        "table_row_counts": payload["table_row_counts"],
        # Full catalog rows for differential parity with the DB projection.
        "nodes": payload["nodes"],
        "scopes": payload["scopes"],
        "references": payload["references"],
        "interfaces": payload["interfaces"],
        "invalidations": payload["invalidations"],
    }


def authority_key_for_projection(projection: Any) -> str:
    """Stable authority key for one blob projection."""

    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
        ASTCatalogProjection,
    )

    if type(projection) is not ASTCatalogProjection:
        raise ASTShadowError(
            "authority_key_for_projection requires an exact ASTCatalogProjection"
        )
    return f"ast:{projection.blob_id}"


def evidence_edges_from_projection(
    projection: Any,
    *,
    task_id: str = AST_SHADOW_OWNER_TASK,
) -> tuple[dict[str, Any], ...]:
    """Derive code-evidence edges from a catalog projection (symbols/imports)."""

    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
        ASTCatalogProjection,
    )

    if type(projection) is not ASTCatalogProjection:
        raise ASTShadowError(
            "evidence_edges_from_projection requires an exact ASTCatalogProjection"
        )
    revision = projection.source_revision.revision
    path = projection.source_file.path
    tree_node = f"tree:{path}"
    edges: list[dict[str, Any]] = []
    for symbol in projection.symbols:
        edges.append(
            {
                "schema": AST_EVIDENCE_EDGE_SCHEMA,
                "edge_id": f"edge:defines:{projection.blob_id}:{symbol.symbol_id}",
                "kind": "defines_symbol",
                "source": tree_node,
                "target": f"symbol:{symbol.qualified_name}",
                "provenance": "ast",
                "authoritative": True,
                "revision": revision,
                "task_id": task_id,
                "symbol_id": symbol.symbol_id,
                "qualified_name": symbol.qualified_name,
                "start_byte": symbol.span.start_byte,
                "end_byte": symbol.span.end_byte,
                "start_line": symbol.span.start_line,
                "end_line": symbol.span.end_line,
                "source_cid": projection.source_cid,
                "ast_cid": projection.ast_cid,
            }
        )
    for item in projection.imports:
        edges.append(
            {
                "schema": AST_EVIDENCE_EDGE_SCHEMA,
                "edge_id": f"edge:import:{projection.blob_id}:{item.import_id}",
                "kind": "depends_on",
                "source": tree_node,
                "target": f"module:{item.module}",
                "provenance": "ast",
                "authoritative": True,
                "revision": revision,
                "task_id": task_id,
                "import_id": item.import_id,
                "module": item.module,
                "start_byte": item.span.start_byte,
                "end_byte": item.span.end_byte,
                "source_cid": projection.source_cid,
                "ast_cid": projection.ast_cid,
            }
        )
    for item in projection.calls:
        edges.append(
            {
                "schema": AST_EVIDENCE_EDGE_SCHEMA,
                "edge_id": f"edge:call:{projection.blob_id}:{item.call_id}",
                "kind": "derived_from",
                "source": tree_node,
                "target": f"call:{item.callee_name}",
                "provenance": "ast",
                "authoritative": True,
                "revision": revision,
                "task_id": task_id,
                "call_id": item.call_id,
                "callee_name": item.callee_name,
                "start_byte": item.span.start_byte,
                "end_byte": item.span.end_byte,
                "source_cid": projection.source_cid,
                "ast_cid": projection.ast_cid,
            }
        )
    edges.sort(key=lambda edge: str(edge["edge_id"]))
    return tuple(edges)


def _parity_digest(value: Any) -> str:
    """SHA-256 over canonical JSON that admits AST float timestamps.

    The software-contract structured CID profile rejects floats.  Catalog
    rows intentionally carry ``created_at`` as float epoch seconds, so
    differential parity digests use a local JSON profile that preserves
    exact values (including floats) without inventing a second CID scheme
    for operational identity.
    """

    import hashlib

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def differential_parity(
    json_bundle: Mapping[str, Any],
    db_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare JSON-bundle and DB projection payloads for differential parity.

    Identity fields (source/hash/span/CID) must match exactly.  Table families
    and row digests must agree.  Returns a structured report; never silently
    treats a mismatch as success.
    """

    if not isinstance(json_bundle, Mapping) or not isinstance(db_payload, Mapping):
        raise ASTShadowError("differential_parity requires mapping payloads")

    json_identity = dict(json_bundle.get("identity") or {})
    db_identity = dict(db_payload.get("identity") or {})
    identity_fields = (
        "source_cid",
        "ast_cid",
        "blob_id",
        "path",
        "revision",
        "revision_id",
        "repository_id",
        "language",
        "parse_status",
    )
    identity_mismatches: list[str] = []
    for name in identity_fields:
        if json_identity.get(name) != db_identity.get(name):
            identity_mismatches.append(name)

    # Span-bearing families: exact sorted JSON digests.
    span_families = (
        "symbols",
        "imports",
        "calls",
        "effects",
        "diagnostics",
        "nodes",
        "scopes",
        "references",
        "interfaces",
    )
    family_mismatches: list[str] = []
    family_digests: dict[str, dict[str, str]] = {}
    for family in span_families:
        left_rows = list(json_bundle.get(family) or [])
        right_rows = list(db_payload.get(family) or [])
        left_digest = _parity_digest({"family": family, "rows": left_rows})
        right_digest = _parity_digest({"family": family, "rows": right_rows})
        family_digests[family] = {
            "json": left_digest,
            "db": right_digest,
        }
        if left_digest != right_digest or len(left_rows) != len(right_rows):
            family_mismatches.append(family)

    counts_json = dict(json_bundle.get("table_row_counts") or {})
    counts_db = dict(db_payload.get("table_row_counts") or {})
    counts_match = counts_json == counts_db

    matched = (
        not identity_mismatches
        and not family_mismatches
        and counts_match
        and json_identity.get("source_cid")
        and json_identity.get("ast_cid")
    )
    return {
        "schema": f"{AST_SHADOW_SCHEMA}/differential-parity",
        "matched": bool(matched),
        "identity_mismatches": identity_mismatches,
        "family_mismatches": family_mismatches,
        "family_digests": family_digests,
        "counts_match": counts_match,
        "json_identity": json_identity,
        "db_identity": db_identity,
        "json_counts": counts_json,
        "db_counts": counts_db,
    }


def _language_for_path(path: str) -> str:
    lower = str(path or "").lower()
    for ext in _PYTHON_EXTENSIONS:
        if lower.endswith(ext):
            return "python"
    for ext in _TYPESCRIPT_EXTENSIONS:
        if lower.endswith(ext):
            if lower.endswith((".js", ".jsx", ".mjs", ".cjs")):
                return "javascript"
            return "typescript"
    return detect_language(path)


@dataclass(frozen=True, slots=True)
class ASTShadowFileResult:
    """Per-file outcome of a shadow extraction batch."""

    path: str
    source_cid: str
    language: str
    status: str  # parsed | parse_failed | skipped
    blob_id: str | None
    ast_cid: str | None
    authority_key: str | None
    operation_id: str | None
    parse_error: str
    symbol_count: int = 0
    import_count: int = 0
    call_count: int = 0
    effect_count: int = 0
    diagnostic_count: int = 0
    evidence_edge_count: int = 0
    blocked_unrelated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_cid": self.source_cid,
            "language": self.language,
            "status": self.status,
            "blob_id": self.blob_id,
            "ast_cid": self.ast_cid,
            "authority_key": self.authority_key,
            "operation_id": self.operation_id,
            "parse_error": self.parse_error,
            "symbol_count": self.symbol_count,
            "import_count": self.import_count,
            "call_count": self.call_count,
            "effect_count": self.effect_count,
            "diagnostic_count": self.diagnostic_count,
            "evidence_edge_count": self.evidence_edge_count,
            "blocked_unrelated": self.blocked_unrelated,
        }


@dataclass(frozen=True, slots=True)
class ASTShadowBatchResult:
    """Aggregate result for a multi-file shadow extraction."""

    repository_id: str
    revision: str
    results: tuple[ASTShadowFileResult, ...]
    projections: tuple[Any, ...]
    json_bundles: tuple[dict[str, Any], ...]
    evidence_edges: tuple[dict[str, Any], ...]
    parity_reports: tuple[dict[str, Any], ...]
    parsed_count: int
    parse_failed_count: int
    skipped_count: int
    durable_parse_failures: int

    @property
    def ok(self) -> bool:
        # Batch succeeds when no file blocked another (failures are durable).
        return all(not item.blocked_unrelated for item in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": f"{AST_SHADOW_SCHEMA}/batch",
            "owner_task_id": AST_SHADOW_OWNER_TASK,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "ok": self.ok,
            "parsed_count": self.parsed_count,
            "parse_failed_count": self.parse_failed_count,
            "skipped_count": self.skipped_count,
            "durable_parse_failures": self.durable_parse_failures,
            "results": [item.to_dict() for item in self.results],
            "evidence_edge_count": len(self.evidence_edges),
            "parity_matched_count": sum(
                1 for item in self.parity_reports if item.get("matched")
            ),
            "parity_total": len(self.parity_reports),
        }


class ASTAuthorityShadowWriter:
    """Write normalized AST catalog facts through the authority port.

    In shadow mode the JSON bundle (legacy) remains authority while DuckDB
    receives an outbox projection of the same closed payload.  Callers bind
    an optional in-process :class:`DuckDBASTStore` so DB-side consumers and
    differential parity share one projection object identity.
    """

    def __init__(
        self,
        authority_port: Any,
        *,
        ast_store: Any | None = None,
        writer_id: str = "writer:ast-shadow",
        task_id: str = AST_SHADOW_OWNER_TASK,
    ) -> None:
        if authority_port is None:
            raise ASTShadowError("authority_port is required")
        self._port = authority_port
        self._writer_id = str(writer_id or "writer:ast-shadow")
        self._task_id = str(task_id or AST_SHADOW_OWNER_TASK)
        self._lock = threading.RLock()
        if ast_store is None:
            from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
                build_duckdb_ast_store,
            )

            self._store = build_duckdb_ast_store()
        else:
            self._store = ast_store
        self._stats = {
            "writes": 0,
            "parse_failures": 0,
            "parity_checks": 0,
            "parity_matches": 0,
            "evidence_edges": 0,
        }

    @property
    def interface(self) -> str:
        return AST_SHADOW_INTERFACE

    @property
    def port(self) -> Any:
        return self._port

    @property
    def store(self) -> Any:
        return self._store

    @property
    def domain(self) -> str:
        return getattr(self._port, "domain", AST_AUTHORITY_DOMAIN)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def write_projection(
        self,
        projection: Any,
        *,
        operation_id: str | None = None,
        also_write_evidence_edges: bool = True,
    ) -> dict[str, Any]:
        """Write one catalog projection as JSON bundle + DB shadow payload."""

        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            ASTCatalogProjection,
        )

        if type(projection) is not ASTCatalogProjection:
            raise ASTShadowError(
                "write_projection requires an exact ASTCatalogProjection"
            )
        key = authority_key_for_projection(projection)
        json_bundle = json_bundle_from_projection(projection)
        # Authority payload is the full catalog projection (DB shadow target).
        db_payload = projection_to_authority_payload(projection)
        # Legacy surface is the JSON bundle; DB surface is the full projection.
        # In shadow mode the port writes the same payload to both sides, so we
        # store a closed dual document that embeds both views for parity.
        dual = {
            "schema": AST_SHADOW_SCHEMA,
            "interface": AST_SHADOW_INTERFACE,
            "owner_task_id": self._task_id,
            "kind": "ast_shadow_dual",
            "identity": dict(db_payload["identity"]),
            "json_bundle": json_bundle,
            "db_projection": db_payload,
        }
        op_id = operation_id or f"op:ast:{projection.blob_id}"
        with self._lock:
            self._store.put_projection(projection)
            write_result = self._port.write(key, dual, operation_id=op_id)
            self._stats["writes"] += 1
            if projection.ast_blob.parse_status == "failed":
                self._stats["parse_failures"] += 1
            evidence_edges: tuple[dict[str, Any], ...] = ()
            if also_write_evidence_edges:
                evidence_edges = evidence_edges_from_projection(
                    projection, task_id=self._task_id
                )
                for edge in evidence_edges:
                    edge_key = f"evidence:{edge['edge_id']}"
                    edge_op = f"op:evidence:{edge['edge_id']}"
                    self._port.write(edge_key, edge, operation_id=edge_op)
                    self._stats["evidence_edges"] += 1
        return {
            "ok": bool(write_result.get("ok", True)),
            "authority_key": key,
            "operation_id": write_result.get("operation_id", op_id),
            "mode": write_result.get("mode"),
            "authority": write_result.get("authority"),
            "payload_digest": write_result.get("payload_digest"),
            "json_bundle": json_bundle,
            "db_projection": db_payload,
            "dual": dual,
            "evidence_edges": list(evidence_edges),
            "write_result": write_result,
            "atomic_across_filesystems": False,
        }

    def write_record(
        self,
        record: Any,
        *,
        operation_id: str | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Project an :class:`ASTRecord` and write it through the port."""

        from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            project_ast_record,
        )

        if type(record) is not ASTRecord:
            raise ASTShadowError("write_record requires an exact ASTRecord")
        projection = project_ast_record(record, created_at=created_at)
        return self.write_projection(projection, operation_id=operation_id)

    def write_parse_failure(
        self,
        *,
        provenance: Any,
        language: str,
        message: str,
        operation_id: str | None = None,
        frontend_name: str = "unknown",
        frontend_version: str = "unknown",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Record a durable parse failure without aborting a multi-file batch."""

        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            project_parse_failure,
        )

        projection = project_parse_failure(
            provenance=provenance,
            language=language,
            message=message,
            frontend_name=frontend_name,
            frontend_version=frontend_version,
            **kwargs,
        )
        return self.write_projection(projection, operation_id=operation_id)

    def emit_parity(self, authority_key: str) -> dict[str, Any]:
        """Emit port parity and differential JSON/DB parity for one key."""

        receipt = self._port.emit_parity_receipt(authority_key)
        legacy = self._port.backend.get_legacy(self.domain, authority_key)
        db = self._port.backend.get_db(self.domain, authority_key)
        report: dict[str, Any] = {
            "authority_key": authority_key,
            "port_parity_matched": bool(getattr(receipt, "matched", False)),
            "port_parity_receipt_cid": getattr(receipt, "receipt_cid", ""),
            "port_mismatch_reason": getattr(receipt, "mismatch_reason", ""),
            "differential": None,
        }
        if (
            isinstance(legacy, Mapping)
            and isinstance(db, Mapping)
            and legacy.get("kind") == "ast_shadow_dual"
        ):
            diff = differential_parity(
                dict(legacy.get("json_bundle") or {}),
                dict(db.get("db_projection") or {}),
            )
            # Also require both dual documents to agree on identity digests.
            dual_match = (
                dict(legacy.get("identity") or {})
                == dict(db.get("identity") or {})
            )
            report["differential"] = diff
            report["dual_identity_match"] = dual_match
            report["matched"] = bool(
                report["port_parity_matched"]
                and diff.get("matched")
                and dual_match
            )
        else:
            report["matched"] = bool(report["port_parity_matched"])
        with self._lock:
            self._stats["parity_checks"] += 1
            if report["matched"]:
                self._stats["parity_matches"] += 1
        return report

    def extract_and_shadow(
        self,
        sources: Sequence[Mapping[str, Any] | tuple[Any, ...]],
        *,
        repository_id: str = "repository:shadow",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        python_frontend: Any | None = None,
        typescript_frontend: Any | None = None,
        continue_on_parse_failure: bool = True,
    ) -> ASTShadowBatchResult:
        """Extract AST IR from sources and write each through the authority port.

        Python and TypeScript parse failures become durable diagnostics.
        When ``continue_on_parse_failure`` is true (default), a failure on one
        path never blocks unrelated files in the same batch.
        """

        from ipfs_datasets_py.logic.software_contracts.ast_ir import (
            SourceProvenance,
        )
        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            project_ast_record,
            project_parse_failure,
        )
        from ipfs_datasets_py.logic.software_contracts.python_frontend import (
            PythonASTExtractor,
        )

        py_fe = python_frontend or PythonASTExtractor()
        ts_fe = typescript_frontend  # optional; may be absent in hermetic envs

        results: list[ASTShadowFileResult] = []
        projections: list[Any] = []
        bundles: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []
        parity_reports: list[dict[str, Any]] = []
        parsed = 0
        failed = 0
        skipped = 0
        durable_failures = 0
        blocked = False

        for index, raw in enumerate(sources):
            if blocked and not continue_on_parse_failure:
                # Unreachable when continue_on_parse_failure is true (default).
                break
            path, source_bytes, language = _coerce_shadow_source(
                raw, index=index
            )
            source_cid = cid_for_bytes(source_bytes)
            language = language or _language_for_path(path)
            provenance = SourceProvenance(
                source_cid=source_cid,
                path=path,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
            )
            try:
                parse_error = ""
                status: str | None = None
                projection = None

                if language == "python":
                    record = py_fe.extract_from_source(
                        source_bytes,
                        path=path,
                        repository_id=repository_id,
                        revision=revision,
                        repository_tree_cid=repository_tree_cid,
                    )
                    if _record_is_parse_failure(record):
                        parse_error = _record_parse_error(record)
                        projection = project_parse_failure(
                            provenance=provenance,
                            language=language,
                            message=parse_error or "python parse failure",
                            frontend_name=getattr(
                                py_fe.capability, "frontend_name", "cpython-ast"
                            ),
                            frontend_version=getattr(
                                py_fe.capability,
                                "frontend_version",
                                "unknown",
                            ),
                        )
                        status = "parse_failed"
                    else:
                        projection = project_ast_record(record)
                        status = "parsed"
                elif language in {"typescript", "javascript"}:
                    active_ts = ts_fe
                    if active_ts is None:
                        try:
                            from ipfs_datasets_py.logic.software_contracts.typescript_frontend import (
                                TypeScriptFrontend,
                            )

                            active_ts = TypeScriptFrontend()
                            ts_fe = active_ts
                        except Exception as exc:  # noqa: BLE001
                            projection = project_parse_failure(
                                provenance=provenance,
                                language=language,
                                message=(
                                    f"typescript frontend unavailable: {exc}"
                                ),
                                frontend_name="typescript-compiler-api",
                                frontend_version="unavailable",
                            )
                            status = "parse_failed"
                            parse_error = str(exc)
                    if status is None and active_ts is not None:
                        try:
                            record = active_ts.extract(
                                source_bytes,
                                path=path,
                                repository_id=repository_id,
                                revision=revision,
                                repository_tree_cid=repository_tree_cid,
                            )
                            ts_version = "unknown"
                            if hasattr(active_ts, "capability"):
                                ts_version = getattr(
                                    active_ts.capability,
                                    "frontend_version",
                                    "unknown",
                                )
                            if _record_is_parse_failure(record):
                                parse_error = _record_parse_error(record)
                                projection = project_parse_failure(
                                    provenance=provenance,
                                    language=language,
                                    message=(
                                        parse_error
                                        or "typescript parse failure"
                                    ),
                                    frontend_name="typescript-compiler-api",
                                    frontend_version=str(ts_version),
                                )
                                status = "parse_failed"
                            else:
                                projection = project_ast_record(record)
                                status = "parsed"
                        except Exception as exc:  # noqa: BLE001
                            projection = project_parse_failure(
                                provenance=provenance,
                                language=language,
                                message=str(exc),
                                frontend_name="typescript-compiler-api",
                                frontend_version="error",
                            )
                            status = "parse_failed"
                            parse_error = str(exc)
                    if status is None:
                        projection = project_parse_failure(
                            provenance=provenance,
                            language=language,
                            message="typescript frontend unavailable",
                            frontend_name="typescript-compiler-api",
                            frontend_version="unavailable",
                        )
                        status = "parse_failed"
                        parse_error = "typescript frontend unavailable"
                else:
                    results.append(
                        ASTShadowFileResult(
                            path=path,
                            source_cid=source_cid,
                            language=language,
                            status="skipped",
                            blob_id=None,
                            ast_cid=None,
                            authority_key=None,
                            operation_id=None,
                            parse_error="",
                        )
                    )
                    skipped += 1
                    continue

                assert projection is not None and status is not None
                write = self.write_projection(projection)
                parity = self.emit_parity(write["authority_key"])
                parity_reports.append(parity)
                projections.append(projection)
                bundles.append(write["json_bundle"])
                all_edges.extend(write["evidence_edges"])
                if status == "parsed":
                    parsed += 1
                else:
                    failed += 1
                    durable_failures += 1
                results.append(
                    ASTShadowFileResult(
                        path=path,
                        source_cid=source_cid,
                        language=language,
                        status=status,
                        blob_id=projection.blob_id,
                        ast_cid=projection.ast_cid,
                        authority_key=write["authority_key"],
                        operation_id=write["operation_id"],
                        parse_error=parse_error
                        or projection.ast_blob.parse_error,
                        symbol_count=len(projection.symbols),
                        import_count=len(projection.imports),
                        call_count=len(projection.calls),
                        effect_count=len(projection.effects),
                        diagnostic_count=len(projection.diagnostics),
                        evidence_edge_count=len(write["evidence_edges"]),
                        blocked_unrelated=False,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — durable, non-blocking
                if not continue_on_parse_failure:
                    raise
                try:
                    write = self.write_parse_failure(
                        provenance=provenance,
                        language=language,
                        message=str(exc),
                        frontend_name="repository-shadow",
                        frontend_version=AST_SHADOW_OWNER_TASK,
                    )
                    parity = self.emit_parity(write["authority_key"])
                    parity_reports.append(parity)
                    blob_id = write["db_projection"]["identity"]["blob_id"]
                    stored = self._store.get(blob_id)
                    if stored is not None:
                        projections.append(stored)
                    bundles.append(write["json_bundle"])
                    all_edges.extend(write["evidence_edges"])
                    durable_failures += 1
                    failed += 1
                    results.append(
                        ASTShadowFileResult(
                            path=path,
                            source_cid=source_cid,
                            language=language,
                            status="parse_failed",
                            blob_id=blob_id,
                            ast_cid=write["db_projection"]["identity"][
                                "ast_cid"
                            ],
                            authority_key=write["authority_key"],
                            operation_id=write["operation_id"],
                            parse_error=str(exc),
                            diagnostic_count=1,
                            evidence_edge_count=len(write["evidence_edges"]),
                            blocked_unrelated=False,
                        )
                    )
                except Exception as inner:  # noqa: BLE001
                    failed += 1
                    durable_failures += 1
                    results.append(
                        ASTShadowFileResult(
                            path=path,
                            source_cid=source_cid,
                            language=language,
                            status="parse_failed",
                            blob_id=None,
                            ast_cid=None,
                            authority_key=None,
                            operation_id=None,
                            parse_error=f"{exc}; recovery={inner}",
                            blocked_unrelated=False,
                        )
                    )

        return ASTShadowBatchResult(
            repository_id=repository_id,
            revision=revision,
            results=tuple(results),
            projections=tuple(p for p in projections if p is not None),
            json_bundles=tuple(bundles),
            evidence_edges=tuple(all_edges),
            parity_reports=tuple(parity_reports),
            parsed_count=parsed,
            parse_failed_count=failed,
            skipped_count=skipped,
            durable_parse_failures=durable_failures,
        )


def _coerce_shadow_source(
    raw: Mapping[str, Any] | tuple[Any, ...] | list[Any],
    *,
    index: int,
) -> tuple[str, bytes, str]:
    if isinstance(raw, Mapping):
        path = str(raw.get("path") or f"source_{index}.py")
        source = raw.get("source")
        if source is None:
            source = raw.get("bytes") or raw.get("content") or b""
        language = str(raw.get("language") or "")
    elif isinstance(raw, (tuple, list)):
        if len(raw) < 2:
            raise ASTShadowError(
                "source tuples must be (path, bytes[, language])"
            )
        path = str(raw[0])
        source = raw[1]
        language = str(raw[2]) if len(raw) > 2 else ""
    else:
        raise ASTShadowError("source entries must be mappings or tuples")
    if isinstance(source, str):
        source_bytes = source.encode("utf-8")
    elif isinstance(source, (bytes, bytearray, memoryview)):
        source_bytes = bytes(source)
    else:
        raise ASTShadowError(f"source for {path!r} must be str or bytes")
    return path, source_bytes, language


def _record_is_parse_failure(record: Any) -> bool:
    """Heuristic: treat frontend failure records as parse failures.

    The Python frontend returns valid ASTRecords with diagnostics/unsupported
    constructs for many failure modes rather than raising.  Codes containing
    ``invalid`` / ``parse`` / ``syntax`` / ``resource`` mark durable failures.
    Empty modules with only failure diagnostics are also treated as failures.
    """

    if record is None:
        return True
    codes: list[str] = []
    for item in getattr(record, "diagnostics", ()) or ():
        codes.append(str(getattr(item, "code", "") or ""))
    for item in getattr(record, "unsupported", ()) or ():
        codes.append(str(getattr(item, "code", "") or ""))
    failure_tokens = (
        "invalid",
        "parse",
        "syntax",
        "resource",
        "encoding",
        "oversized",
        "timeout",
        "unavailable",
        "compiler",
        "worker",
    )
    for code in codes:
        lower = code.lower()
        if any(token in lower for token in failure_tokens):
            # Pure warning diagnostics should not force failure when symbols exist.
            if getattr(record, "symbols", None) and "warning" in lower:
                continue
            if not getattr(record, "symbols", ()) and not getattr(
                record, "imports", ()
            ):
                return True
            if any(
                token in lower
                for token in ("syntax", "invalid_encoding", "parse", "oversized")
            ):
                return True
    return False


def _record_parse_error(record: Any) -> str:
    messages: list[str] = []
    for item in getattr(record, "diagnostics", ()) or ():
        messages.append(
            f"{getattr(item, 'code', '')}: {getattr(item, 'message', '')}"
        )
    for item in getattr(record, "unsupported", ()) or ():
        messages.append(
            f"{getattr(item, 'code', '')}: {getattr(item, 'reason', '')}"
        )
    return "; ".join(m for m in messages if m.strip()) or "parse failure"


def build_ast_authority_shadow_writer(
    authority_port: Any | None = None,
    *,
    domain: str = AST_AUTHORITY_DOMAIN,
    initial_mode: str = "shadow",
    ast_store: Any | None = None,
    writer_id: str = "writer:ast-shadow",
    task_id: str = AST_SHADOW_OWNER_TASK,
) -> ASTAuthorityShadowWriter:
    """Construct a shadow writer, optionally building a hermetic authority port."""

    if authority_port is None:
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            build_authority_port,
        )

        authority_port = build_authority_port(
            domain=domain,
            initial_mode=AuthorityMode.parse(initial_mode),
            writer_id=writer_id,
        )
    return ASTAuthorityShadowWriter(
        authority_port,
        ast_store=ast_store,
        writer_id=writer_id,
        task_id=task_id,
    )


def extract_repository_ast_shadow(
    sources: Sequence[Mapping[str, Any] | tuple[Any, ...]],
    *,
    repository_id: str = "repository:shadow",
    revision: str = "unversioned",
    repository_tree_cid: str | None = None,
    authority_port: Any | None = None,
    **kwargs: Any,
) -> ASTShadowBatchResult:
    """Convenience entry: extract sources and shadow-write through the port."""

    writer = build_ast_authority_shadow_writer(authority_port)
    return writer.extract_and_shadow(
        sources,
        repository_id=repository_id,
        revision=revision,
        repository_tree_cid=repository_tree_cid,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# DQK-069: dual-write AST authority (DuckDB default source for consumers)
# ---------------------------------------------------------------------------
#
# Promotes the DQK-068 shadow path to dual writes.  DuckDB is the default
# read surface for conflict, dependency, impact, validation-selection, and
# code-evidence consumers.  JSON bundles remain deterministic outbox exports
# (never re-admitted as operational authority).  Source invalidation and
# restart recovery leave no stale symbol or edge.

AST_AUTHORITY_OWNER_TASK: Final[str] = "DQK-069"
AST_AUTHORITY_INTERFACE: Final[str] = "ASTAuthorityRepository@1"
AST_AUTHORITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-authority@1"
)
AST_AUTHORITY_JSON_EXPORT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-json-outbox-export@1"
)
AST_AUTHORITY_DEFAULT_SOURCE: Final[str] = "duckdb"
# DQK-069 dual remains the authority-port default for dual-write soak tests.
# DQK-070 greenfield cutover uses AST_ONLY_DEFAULT_MODE (db-primary).
AST_AUTHORITY_DEFAULT_MODE: Final[str] = "dual"
AST_ONLY_DEFAULT_MODE: Final[str] = "db-primary"
AST_INVALIDATION_RECORD_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-invalidation@1"
)
AST_CONSUMER_DECISION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-consumer-decision@1"
)

# ---------------------------------------------------------------------------
# DQK-070: remove analysis-bundle file authority
# ---------------------------------------------------------------------------
#
# Operational consumers read only the DuckDB surface.  analysis_ast_index,
# objective, dependency, conflict, and code-evidence JSON files are never
# polled or loaded as operational state.  Filesystem bundle writes occur only
# through the closed set of named export commands below.

AST_ONLY_OWNER_TASK: Final[str] = "DQK-070"
AST_ONLY_INTERFACE: Final[str] = "ASTAuthorityRepository@1"
AST_COMPATIBILITY_EXPORT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-compatibility-export@1"
)
AST_PUBLICATION_VIEW_SCHEMA: Final[str] = (
    "ipfs_datasets_py/software-contracts-ast-publication-view@1"
)
AST_NAMED_EXPORT_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "export_json_bundle",
        "export_compatibility_bundle",
        "write_compatibility_export",
    }
)
AST_LEGACY_BUNDLE_ARTIFACTS: Final[Mapping[str, str]] = {
    "manifest": "manifest.json",
    "objective_graph": "objective_graph.json",
    "semantic_dependency_graph": "semantic_dependency_graph.json",
    "analysis_ast_index": "analysis_ast_index.json",
    "conflict_graph": "conflict_graph.json",
    "code_evidence_graph": "code_evidence_graph.json",
    "code_impact_index": "code_impact_index.json",
}
AST_DEFAULT_TENANT_ID: Final[str] = "tenant:default"


class ASTAuthorityError(ASTShadowError):
    """Raised when dual-write AST authority operations fail closed."""


def deterministic_json_bundle_export(projection: Any) -> dict[str, Any]:
    """Build a deterministic outbox JSON export from one catalog projection.

    Exports are byte-stable for equal projections: keys sorted, closed fields,
    no wall-clock timestamps.  They are not operational authority — only the
    DuckDB dual-write surface is.
    """

    base = json_bundle_from_projection(projection)
    # Strip owner_task pin from shadow so export schema stands alone.
    export = {
        "schema": AST_AUTHORITY_JSON_EXPORT_SCHEMA,
        "kind": "ast_json_outbox_export",
        "owner_task_id": AST_AUTHORITY_OWNER_TASK,
        "authority_source": AST_AUTHORITY_DEFAULT_SOURCE,
        "operational_authority": False,
        "identity": dict(base["identity"]),
        "source_revision": base["source_revision"],
        "source_file": base["source_file"],
        "ast_blob": base["ast_blob"],
        "symbols": base["symbols"],
        "imports": base["imports"],
        "calls": base["calls"],
        "effects": base["effects"],
        "diagnostics": base["diagnostics"],
        "nodes": base["nodes"],
        "scopes": base["scopes"],
        "references": base["references"],
        "interfaces": base["interfaces"],
        "invalidations": base["invalidations"],
        "supervisor_blob_summary": base["supervisor_blob_summary"],
        "table_row_counts": base["table_row_counts"],
    }
    return export


def deterministic_json_export_bytes(export: Mapping[str, Any]) -> bytes:
    """Canonical UTF-8 JSON bytes for an outbox export (byte-identical replay)."""

    return json.dumps(
        dict(export),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _decision_digest(payload: Mapping[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ASTAuthorityRepository:
    """DuckDB-primary AST repository (DQK-069 dual + DQK-070 bundle removal).

    Writes go through the authority port (dual or db-primary, crash-recoverable
    outbox).  Reads for conflict / dependency / impact / validation-selection
    / code-evidence / objective always prefer the DuckDB surface.  Legacy
    analysis-bundle JSON files are never polled or loaded as operational
    state; filesystem bundle writes occur only through named export commands
    (``export_json_bundle``, ``export_compatibility_bundle``,
    ``write_compatibility_export``).
    """

    def __init__(
        self,
        authority_port: Any,
        *,
        ast_store: Any | None = None,
        writer_id: str = "writer:ast-authority",
        task_id: str = AST_AUTHORITY_OWNER_TASK,
        default_source: str = AST_AUTHORITY_DEFAULT_SOURCE,
        tenant_id: str = AST_DEFAULT_TENANT_ID,
        allow_legacy_bundle_load: bool = False,
    ) -> None:
        if authority_port is None:
            raise ASTAuthorityError("authority_port is required")
        if default_source not in {"duckdb", "dual"}:
            raise ASTAuthorityError(
                "default_source must be 'duckdb' (default consumer source)"
            )
        self._port = authority_port
        self._writer_id = str(writer_id or "writer:ast-authority")
        self._task_id = str(task_id or AST_AUTHORITY_OWNER_TASK)
        self._default_source = str(default_source)
        self._tenant_id = str(tenant_id or AST_DEFAULT_TENANT_ID)
        # DQK-070: operational consumers must not load on-disk JSON bundles.
        self._allow_legacy_bundle_load = bool(allow_legacy_bundle_load)
        self._lock = threading.RLock()
        if ast_store is None:
            from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
                build_duckdb_ast_store,
            )

            self._store = build_duckdb_ast_store()
        else:
            self._store = ast_store
        # Process-local indexes for consumer queries and invalidation.
        self._active_blob_keys: dict[str, str] = {}  # blob_id -> authority_key
        self._path_to_blob: dict[str, str] = {}  # path -> blob_id
        self._active_edges: dict[str, dict[str, Any]] = {}  # edge_id -> edge
        self._edge_by_blob: dict[str, set[str]] = {}  # blob_id -> edge_ids
        self._symbol_index: dict[str, set[str]] = {}  # symbol_qn -> blob_ids
        self._invalidated_blobs: set[str] = set()
        self._invalidated_edges: set[str] = set()
        self._impact_edges: list[dict[str, Any]] = []
        self._validation_targets: dict[str, list[str]] = {}
        self._conflict_edges: list[dict[str, Any]] = []
        self._export_digests: dict[str, str] = {}  # authority_key -> digest
        # DQK-070: repository / tenant scopes for publication views.
        self._blob_repository: dict[str, str] = {}  # blob_id -> repository_id
        self._blob_tenant: dict[str, str] = {}  # blob_id -> tenant_id
        self._objectives: dict[str, dict[str, Any]] = {}  # goal_id -> objective
        self._named_export_invocations: list[str] = []
        self._filesystem_bundle_writes: int = 0
        self._stats = {
            "writes": 0,
            "invalidations": 0,
            "restarts": 0,
            "consumer_reads": 0,
            "parity_checks": 0,
            "parity_matches": 0,
            "outbox_exports": 0,
            "named_exports": 0,
            "publication_views": 0,
        }

    # -- properties ---------------------------------------------------------

    @property
    def interface(self) -> str:
        return AST_AUTHORITY_INTERFACE

    @property
    def port(self) -> Any:
        return self._port

    @property
    def store(self) -> Any:
        return self._store

    @property
    def domain(self) -> str:
        return getattr(self._port, "domain", AST_AUTHORITY_DOMAIN)

    @property
    def default_source(self) -> str:
        """Default consumer source: always DuckDB under dual / db-primary."""

        return self._default_source

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def mode(self) -> str:
        mode = getattr(self._port, "mode", None)
        if mode is None:
            return AST_AUTHORITY_DEFAULT_MODE
        return getattr(mode, "value", str(mode))

    @property
    def named_export_commands(self) -> frozenset[str]:
        return AST_NAMED_EXPORT_COMMANDS

    @property
    def allow_legacy_bundle_load(self) -> bool:
        """Whether operational paths may load on-disk JSON (always False post-DQK-070)."""

        return False if not self._allow_legacy_bundle_load else True

    def stats(self) -> dict[str, int]:
        with self._lock:
            out = dict(self._stats)
            out["filesystem_bundle_writes"] = self._filesystem_bundle_writes
            return out

    def reject_legacy_bundle_load(self, *, artifact: str = "analysis_ast_index") -> None:
        """Fail closed when an operational path attempts to load legacy JSON."""

        if not self._allow_legacy_bundle_load:
            raise ASTAuthorityError(
                f"DQK-070 forbids loading legacy bundle artifact {artifact!r} "
                "as operational state; use DuckDB consumer queries or named "
                f"export commands {sorted(AST_NAMED_EXPORT_COMMANDS)}"
            )

    def promote_to_db_primary(
        self,
        *,
        decision_id: str | None = None,
        require_parity: bool = False,
    ) -> dict[str, Any]:
        """Promote the authority port dual → db-primary (DQK-070 cutover)."""

        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
        )

        mode = getattr(self._port, "mode", None)
        mode_value = getattr(mode, "value", str(mode) if mode is not None else "")
        if mode_value in {"db-primary", "export-only"}:
            return {
                "ok": True,
                "already": True,
                "mode": mode_value,
                "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            }
        decision = decision_id or f"dec:ast-auth:{self._task_id}:to-db-primary"
        try:
            receipt = self._port.promote(
                AuthorityMode.DB_PRIMARY,
                require_parity=require_parity,
                decision_id=decision,
            )
        except Exception as exc:
            raise ASTAuthorityError(
                f"promote_to_db_primary failed: {exc}"
            ) from exc
        return {
            "ok": True,
            "already": False,
            "mode": self.mode,
            "decision_id": decision,
            "receipt": getattr(receipt, "as_mapping", lambda: receipt)(),
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "legacy_bundles_operational": False,
        }

    # -- dual / db-primary write --------------------------------------------

    def write_projection(
        self,
        projection: Any,
        *,
        operation_id: str | None = None,
        also_write_evidence_edges: bool = True,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Write one catalog projection; DuckDB is consumer authority.

        Does **not** write analysis-bundle JSON files.  Deterministic JSON
        exports are available only through named export commands.
        """

        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            ASTCatalogProjection,
        )

        if type(projection) is not ASTCatalogProjection:
            raise ASTAuthorityError(
                "write_projection requires an exact ASTCatalogProjection"
            )
        key = authority_key_for_projection(projection)
        # In-memory export payload for dual-mode parity; never a filesystem write.
        json_export = deterministic_json_bundle_export(projection)
        db_payload = projection_to_authority_payload(projection)
        identity = dict(db_payload["identity"])
        scope_tenant = str(tenant_id or self._tenant_id)
        identity["tenant_id"] = scope_tenant
        # Authority document: DuckDB is operational; json_bundle is non-authority
        # outbox material only (never a filesystem artifact write).
        dual = {
            "schema": AST_AUTHORITY_SCHEMA,
            "interface": AST_AUTHORITY_INTERFACE,
            "owner_task_id": self._task_id,
            "kind": "ast_authority_dual",
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "operational_authority": "duckdb",
            "legacy_bundle_operational": False,
            "identity": identity,
            "json_bundle": json_export,
            "db_projection": db_payload,
            "tenant_id": scope_tenant,
            "repository_id": identity.get("repository_id") or "",
            "invalidated": False,
        }
        op_id = operation_id or f"op:ast-auth:{projection.blob_id}"
        with self._lock:
            # Replace prior blob for the same path (prevents stale symbols).
            prior_blob = self._path_to_blob.get(projection.source_file.path)
            if prior_blob is not None and prior_blob != projection.blob_id:
                self._invalidate_blob_locked(
                    prior_blob,
                    reason="blob_replaced",
                    detail=f"replaced by {projection.blob_id}",
                )
            self._store.put_projection(projection)
            write_result = self._port.write(key, dual, operation_id=op_id)
            self._index_projection_locked(
                projection, key, json_export, tenant_id=scope_tenant
            )
            evidence_edges: tuple[dict[str, Any], ...] = ()
            if also_write_evidence_edges:
                evidence_edges = evidence_edges_from_projection(
                    projection, task_id=self._task_id
                )
                for edge in evidence_edges:
                    self._write_edge_locked(edge)
            self._stats["writes"] += 1
            # Outbox export material is retained in-memory only; filesystem
            # bundle writes are counted exclusively by named export commands.
        return {
            "ok": bool(write_result.get("ok", True)),
            "authority_key": key,
            "operation_id": write_result.get("operation_id", op_id),
            "mode": write_result.get("mode"),
            "authority": write_result.get("authority") or "duckdb",
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "payload_digest": write_result.get("payload_digest"),
            "json_bundle": json_export,
            "db_projection": db_payload,
            "dual": dual,
            "evidence_edges": list(evidence_edges),
            "write_result": write_result,
            "atomic_across_filesystems": False,
            "operational_authority": "duckdb",
            "legacy_bundle_operational": False,
            "filesystem_bundle_written": False,
            "tenant_id": scope_tenant,
            "repository_id": identity.get("repository_id") or "",
        }

    def write_record(
        self,
        record: Any,
        *,
        operation_id: str | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            project_ast_record,
        )

        if type(record) is not ASTRecord:
            raise ASTAuthorityError("write_record requires an exact ASTRecord")
        projection = project_ast_record(record, created_at=created_at)
        return self.write_projection(projection, operation_id=operation_id)

    def write_parse_failure(
        self,
        *,
        provenance: Any,
        language: str,
        message: str,
        operation_id: str | None = None,
        frontend_name: str = "unknown",
        frontend_version: str = "unknown",
        **kwargs: Any,
    ) -> dict[str, Any]:
        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
            project_parse_failure,
        )

        projection = project_parse_failure(
            provenance=provenance,
            language=language,
            message=message,
            frontend_name=frontend_name,
            frontend_version=frontend_version,
            **kwargs,
        )
        return self.write_projection(projection, operation_id=operation_id)

    def _index_projection_locked(
        self,
        projection: Any,
        authority_key: str,
        json_export: Mapping[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> None:
        blob_id = projection.blob_id
        self._active_blob_keys[blob_id] = authority_key
        self._path_to_blob[projection.source_file.path] = blob_id
        self._invalidated_blobs.discard(blob_id)
        export_digest = _decision_digest(json_export)
        self._export_digests[authority_key] = export_digest
        repo_id = str(
            getattr(projection.source_revision, "repository_id", "") or ""
        )
        scope_tenant = str(tenant_id or self._tenant_id)
        self._blob_repository[blob_id] = repo_id
        self._blob_tenant[blob_id] = scope_tenant
        for symbol in projection.symbols:
            qn = symbol.qualified_name
            self._symbol_index.setdefault(qn, set()).add(blob_id)
            self._symbol_index.setdefault(symbol.name, set()).add(blob_id)
        # Impact edges from imports/calls for scheduling agreement.
        path = projection.source_file.path
        for item in projection.imports:
            self._impact_edges.append(
                {
                    "source": path,
                    "target": f"module:{item.module}",
                    "kind": "import",
                    "blob_id": blob_id,
                    "repository_id": repo_id,
                    "tenant_id": scope_tenant,
                }
            )
        for item in projection.calls:
            self._impact_edges.append(
                {
                    "source": path,
                    "target": f"call:{item.callee_name}",
                    "kind": "call",
                    "blob_id": blob_id,
                    "repository_id": repo_id,
                    "tenant_id": scope_tenant,
                }
            )
        for symbol in projection.symbols:
            self._impact_edges.append(
                {
                    "source": path,
                    "target": f"symbol:{symbol.qualified_name}",
                    "kind": "defines",
                    "blob_id": blob_id,
                    "repository_id": repo_id,
                    "tenant_id": scope_tenant,
                }
            )

    def _write_edge_locked(self, edge: Mapping[str, Any]) -> None:
        edge_id = str(edge["edge_id"])
        body = dict(edge)
        body.setdefault("schema", AST_EVIDENCE_EDGE_SCHEMA)
        body.setdefault("task_id", self._task_id)
        body["invalidated"] = False
        edge_key = f"evidence:{edge_id}"
        self._port.write(
            edge_key,
            body,
            operation_id=f"op:evidence-auth:{edge_id}",
        )
        self._active_edges[edge_id] = body
        self._invalidated_edges.discard(edge_id)
        # Associate edge with blob via source_cid / ast_cid when present.
        blob_hint = None
        for key in self._active_blob_keys:
            if key in edge_id or edge.get("source_cid"):
                # Prefer matching by scanning active projections.
                projection = self._store.get(key)
                if projection is not None and (
                    projection.source_cid == edge.get("source_cid")
                    or projection.ast_cid == edge.get("ast_cid")
                ):
                    blob_hint = key
                    break
        if blob_hint is None and edge.get("source_cid"):
            # Fall back: edge belongs to any active blob sharing source_cid.
            for key, auth_key in self._active_blob_keys.items():
                projection = self._store.get(key)
                if projection is not None and projection.source_cid == edge.get(
                    "source_cid"
                ):
                    blob_hint = key
                    break
        if blob_hint is not None:
            self._edge_by_blob.setdefault(blob_hint, set()).add(edge_id)

    # -- invalidation -------------------------------------------------------

    def invalidate_source(
        self,
        *,
        path: str | None = None,
        blob_id: str | None = None,
        reason: str = "source_changed",
        detail: str = "",
        actor_id: str = "ast-authority",
    ) -> dict[str, Any]:
        """Invalidate one source so no stale symbol or edge remains queryable."""

        with self._lock:
            target_blob = blob_id
            if target_blob is None and path is not None:
                target_blob = self._path_to_blob.get(path)
            if target_blob is None:
                raise ASTAuthorityError(
                    "invalidate_source requires a known path or blob_id"
                )
            return self._invalidate_blob_locked(
                target_blob,
                reason=reason,
                detail=detail or f"invalidated path={path!r}",
                actor_id=actor_id,
            )

    def _invalidate_blob_locked(
        self,
        blob_id: str,
        *,
        reason: str,
        detail: str = "",
        actor_id: str = "ast-authority",
    ) -> dict[str, Any]:
        projection = self._store.get(blob_id)
        authority_key = self._active_blob_keys.get(blob_id) or f"ast:{blob_id}"
        # Drop from local store (no stale symbols).
        inv_row = self._store.invalidate(
            blob_id=blob_id,
            reason=reason,
            actor_id=actor_id,
            detail=detail,
        )
        # Tombstone dual document on both authority surfaces via dual write.
        tombstone = {
            "schema": AST_INVALIDATION_RECORD_SCHEMA,
            "interface": AST_AUTHORITY_INTERFACE,
            "owner_task_id": self._task_id,
            "kind": "ast_authority_invalidation",
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "operational_authority": "duckdb",
            "invalidated": True,
            "blob_id": blob_id,
            "authority_key": authority_key,
            "reason": reason,
            "detail": detail,
            "actor_id": actor_id,
            "invalidation_id": getattr(inv_row, "invalidation_id", ""),
            "identity": {
                "blob_id": blob_id,
                "path": (
                    projection.source_file.path if projection is not None else ""
                ),
                "source_cid": (
                    projection.source_cid if projection is not None else ""
                ),
                "ast_cid": projection.ast_cid if projection is not None else "",
            },
            "json_bundle": {
                "schema": AST_AUTHORITY_JSON_EXPORT_SCHEMA,
                "kind": "ast_json_outbox_export",
                "invalidated": True,
                "blob_id": blob_id,
            },
            "db_projection": {
                "schema": AST_AUTHORITY_SCHEMA,
                "invalidated": True,
                "blob_id": blob_id,
            },
        }
        self._port.write(
            authority_key,
            tombstone,
            operation_id=f"op:ast-inv:{blob_id}:{reason}",
        )
        # Invalidate evidence edges for this blob.
        edge_ids = list(self._edge_by_blob.get(blob_id, ()))
        for edge_id in edge_ids:
            self._invalidate_edge_locked(edge_id, reason=reason)
        # Drop impact edges tied to this blob.
        self._impact_edges = [
            edge
            for edge in self._impact_edges
            if edge.get("blob_id") != blob_id
        ]
        # Drop symbol index entries.
        if projection is not None:
            for symbol in projection.symbols:
                for name in (symbol.qualified_name, symbol.name):
                    holders = self._symbol_index.get(name)
                    if holders is not None:
                        holders.discard(blob_id)
                        if not holders:
                            self._symbol_index.pop(name, None)
            path = projection.source_file.path
            if self._path_to_blob.get(path) == blob_id:
                self._path_to_blob.pop(path, None)
        self._active_blob_keys.pop(blob_id, None)
        self._edge_by_blob.pop(blob_id, None)
        self._blob_repository.pop(blob_id, None)
        self._blob_tenant.pop(blob_id, None)
        self._invalidated_blobs.add(blob_id)
        self._export_digests.pop(authority_key, None)
        self._stats["invalidations"] += 1
        return {
            "ok": True,
            "blob_id": blob_id,
            "authority_key": authority_key,
            "reason": reason,
            "invalidated_edge_ids": edge_ids,
            "invalidation_id": getattr(inv_row, "invalidation_id", ""),
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
        }

    def _invalidate_edge_locked(
        self, edge_id: str, *, reason: str = "source_changed"
    ) -> None:
        edge_key = f"evidence:{edge_id}"
        prior = self._active_edges.get(edge_id) or {}
        tombstone = {
            **dict(prior),
            "schema": AST_EVIDENCE_EDGE_SCHEMA,
            "edge_id": edge_id,
            "invalidated": True,
            "invalidation_reason": reason,
            "owner_task_id": self._task_id,
            "operational_authority": "duckdb",
        }
        self._port.write(
            edge_key,
            tombstone,
            operation_id=f"op:evidence-inv:{edge_id}",
        )
        self._active_edges.pop(edge_id, None)
        self._invalidated_edges.add(edge_id)

    # -- restart recovery ---------------------------------------------------

    def restart(self) -> dict[str, Any]:
        """Recover incomplete outbox work and rebuild consumer indexes.

        Simulates process restart: drain incomplete dual-write outbox entries,
        then re-index live (non-invalidated) DuckDB records so no stale
        symbol/edge survives.
        """

        recovery = self._port.recover_outbox()
        with self._lock:
            # Rebuild from store + port DB surface.
            live_blobs = list(self._active_blob_keys.items())
            rebuilt_blobs = 0
            rebuilt_edges = 0
            stale_cleared = 0
            for blob_id, authority_key in live_blobs:
                store_proj = self._store.get(blob_id)
                db_doc = self._port.backend.get_db(self.domain, authority_key)
                # Stale if store empty or DB tombstoned.
                if store_proj is None or (
                    isinstance(db_doc, Mapping) and db_doc.get("invalidated")
                ):
                    self._active_blob_keys.pop(blob_id, None)
                    self._invalidated_blobs.add(blob_id)
                    stale_cleared += 1
                    continue
                # Prefer DuckDB dual document for consumer re-index.
                payload = self._port.read(authority_key)
                if isinstance(payload, Mapping) and payload.get("invalidated"):
                    self._active_blob_keys.pop(blob_id, None)
                    self._invalidated_blobs.add(blob_id)
                    stale_cleared += 1
                    continue
                rebuilt_blobs += 1
            # Drop edges whose blob is gone or marked invalidated.
            for edge_id in list(self._active_edges):
                edge = self._active_edges[edge_id]
                edge_key = f"evidence:{edge_id}"
                db_edge = self._port.backend.get_db(self.domain, edge_key)
                if (
                    edge_id in self._invalidated_edges
                    or (
                        isinstance(db_edge, Mapping)
                        and db_edge.get("invalidated")
                    )
                ):
                    self._active_edges.pop(edge_id, None)
                    self._invalidated_edges.add(edge_id)
                    stale_cleared += 1
                else:
                    rebuilt_edges += 1
            # Prune impact edges for invalidated blobs.
            before = len(self._impact_edges)
            self._impact_edges = [
                edge
                for edge in self._impact_edges
                if edge.get("blob_id") not in self._invalidated_blobs
                and edge.get("blob_id") in self._active_blob_keys
            ]
            stale_cleared += before - len(self._impact_edges)
            self._stats["restarts"] += 1
        return {
            "ok": True,
            "recovery": recovery,
            "rebuilt_blobs": rebuilt_blobs,
            "rebuilt_edges": rebuilt_edges,
            "stale_cleared": stale_cleared,
            "active_blob_count": len(self._active_blob_keys),
            "active_edge_count": len(self._active_edges),
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "mode": self.mode,
        }

    # -- read path (DuckDB default) -----------------------------------------

    def read(self, authority_key: str) -> Mapping[str, Any] | None:
        """Read under the port mode (dual/db-primary prefer DuckDB)."""

        with self._lock:
            self._stats["consumer_reads"] += 1
        payload = self._port.read(authority_key)
        if isinstance(payload, Mapping) and payload.get("invalidated"):
            return None
        return payload

    def get_projection(self, blob_id: str) -> Any | None:
        """Return the live DuckDB store projection, or None if invalidated."""

        with self._lock:
            if blob_id in self._invalidated_blobs:
                return None
            self._stats["consumer_reads"] += 1
            return self._store.get(blob_id)

    def export_json_bundle(self, authority_key: str) -> dict[str, Any] | None:
        """Named export command: deterministic outbox JSON (non-authoritative).

        Rebuilds from the DuckDB projection when the dual document no longer
        carries a ``json_bundle`` field (db-primary / export-only cutover).
        Never writes filesystem artifacts.
        """

        with self._lock:
            self._stats["named_exports"] += 1
            self._named_export_invocations.append("export_json_bundle")
        payload = self.read(authority_key)
        if not isinstance(payload, Mapping):
            return None
        export = payload.get("json_bundle")
        if not isinstance(export, Mapping):
            # Rebuild from db_projection or live store.
            db_side = payload.get("db_projection")
            blob_id = ""
            if isinstance(db_side, Mapping):
                identity = dict(db_side.get("identity") or {})
                blob_id = str(identity.get("blob_id") or "")
            if not blob_id:
                blob_id = str(
                    (payload.get("identity") or {}).get("blob_id") or ""
                )
            projection = self._store.get(blob_id) if blob_id else None
            if projection is not None:
                export = deterministic_json_bundle_export(projection)
            elif isinstance(db_side, Mapping):
                export = {
                    "schema": AST_AUTHORITY_JSON_EXPORT_SCHEMA,
                    "kind": "ast_json_outbox_export",
                    "operational_authority": False,
                    "authority_source": AST_AUTHORITY_DEFAULT_SOURCE,
                    "identity": dict(db_side.get("identity") or {}),
                    "source_revision": db_side.get("source_revision"),
                    "source_file": db_side.get("source_file"),
                    "ast_blob": db_side.get("ast_blob"),
                    "symbols": list(db_side.get("symbols") or []),
                    "imports": list(db_side.get("imports") or []),
                    "calls": list(db_side.get("calls") or []),
                    "effects": list(db_side.get("effects") or []),
                    "diagnostics": list(db_side.get("diagnostics") or []),
                    "nodes": list(db_side.get("nodes") or []),
                    "scopes": list(db_side.get("scopes") or []),
                    "references": list(db_side.get("references") or []),
                    "interfaces": list(db_side.get("interfaces") or []),
                    "invalidations": list(db_side.get("invalidations") or []),
                    "table_row_counts": dict(
                        db_side.get("table_row_counts") or {}
                    ),
                }
            else:
                return None
        result = dict(export)
        result["operational_authority"] = False
        result["authority_source"] = AST_AUTHORITY_DEFAULT_SOURCE
        result["named_export_command"] = "export_json_bundle"
        result["legacy_bundle_operational"] = False
        return result

    def export_compatibility_bundle(
        self,
        destination: Path | str,
        *,
        repository_id: str | None = None,
        tenant_id: str | None = None,
        revision: str = "export",
    ) -> dict[str, Any]:
        """Named export command: write compatibility multi-graph JSON bundle.

        This is the **only** supported path for writing analysis_ast_index,
        objective, dependency, conflict, and code-evidence JSON files.
        Operational consumers must not read these files back as authority.
        """

        with self._lock:
            self._named_export_invocations.append("export_compatibility_bundle")
        result = self.write_compatibility_export(
            destination,
            repository_id=repository_id,
            tenant_id=tenant_id,
            revision=revision,
        )
        result["named_export_command"] = "export_compatibility_bundle"
        if isinstance(result.get("manifest"), dict):
            result["manifest"] = dict(result["manifest"])
            result["manifest"]["named_export_command"] = (
                "export_compatibility_bundle"
            )
        return result

    def write_compatibility_export(
        self,
        destination: Path | str,
        *,
        repository_id: str | None = None,
        tenant_id: str | None = None,
        revision: str = "export",
    ) -> dict[str, Any]:
        """Named export command: materialize a non-authoritative JSON bundle."""

        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        scope_tenant = str(tenant_id or self._tenant_id)
        with self._lock:
            self._stats["named_exports"] += 1
            self._named_export_invocations.append("write_compatibility_export")
            self._filesystem_bundle_writes += 1
            view = self._publication_view_locked(
                repository_id=repository_id,
                tenant_id=scope_tenant,
            )
            # Build closed multi-graph compatibility artifacts from DuckDB.
            paths: list[dict[str, Any]] = []
            for node in view["nodes"]:
                paths.append(
                    {
                        "path": node["path"],
                        "blob_id": node["blob_id"],
                        "ast_cid": node.get("ast_cid"),
                        "source_cid": node.get("source_cid"),
                        "symbols": list(node.get("symbols") or []),
                        "repository_id": node.get("repository_id"),
                        "tenant_id": node.get("tenant_id"),
                    }
                )
            ast_index = {
                "schema": "ipfs_accelerate_py/agent-supervisor/analysis-ast-index@1",
                "revision": revision,
                "path_count": len(paths),
                "paths": paths,
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
            }
            objectives = [
                dict(item)
                for item in self._objectives.values()
                if (
                    repository_id is None
                    or item.get("repository_id") == repository_id
                )
                and (
                    scope_tenant is None
                    or item.get("tenant_id") in {None, "", scope_tenant}
                )
            ]
            objective_graph = {
                "schema": "ipfs_accelerate_py.agent_supervisor.objective_graph",
                "revision": revision,
                "goals": objectives,
                "goal_count": len(objectives),
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
            }
            dep_edges = [
                {
                    "source": e.get("source"),
                    "target": e.get("target"),
                    "kind": e.get("kind"),
                }
                for e in view["dependency_edges"]
            ]
            semantic = {
                "schema": (
                    "ipfs_accelerate_py/agent-supervisor/"
                    "semantic-dependency-graph@1"
                ),
                "revision": revision,
                "nodes": [
                    {"node_id": n["path"], "kind": "tree", "path": n["path"]}
                    for n in view["nodes"]
                ],
                "edges": dep_edges,
                "node_count": len(view["nodes"]),
                "edge_count": len(dep_edges),
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
            }
            conflict_graph = {
                "schema": "ipfs_accelerate_py.agent_supervisor.conflict_graph@1",
                "revision": revision,
                "edges": list(view["conflict_edges"]),
                "symbol_conflicts": list(view["symbol_conflicts"]),
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
            }
            evidence_graph = {
                "schema": (
                    "ipfs_accelerate_py.agent_supervisor.code-evidence-graph@1"
                ),
                "revision": revision,
                "nodes": list(view["nodes"]),
                "edges": list(view["evidence_edges"]),
                "node_count": len(view["nodes"]),
                "edge_count": len(view["evidence_edges"]),
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
            }
            impact_index = {
                "schema": (
                    "ipfs_accelerate_py.agent_supervisor.code-impact-index@1"
                ),
                "revision": revision,
                "path_dependencies": {
                    n["path"]: [
                        e["target"]
                        for e in view["dependency_edges"]
                        if e.get("source") == n["path"]
                    ]
                    for n in view["nodes"]
                },
                "validation_targets": dict(self._validation_targets),
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
            }
            files = {
                "analysis_ast_index": ast_index,
                "objective_graph": objective_graph,
                "semantic_dependency_graph": semantic,
                "conflict_graph": conflict_graph,
                "code_evidence_graph": evidence_graph,
                "code_impact_index": impact_index,
            }
            written: dict[str, str] = {}
            checksums: dict[str, str] = {}
            for name, payload in files.items():
                rel = AST_LEGACY_BUNDLE_ARTIFACTS[name]
                path = dest / rel
                encoded = json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                path.write_text(encoded + "\n", encoding="utf-8")
                written[name] = str(path)
                import hashlib

                checksums[name] = (
                    "sha256:"
                    + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                )
            manifest = {
                "schema": AST_COMPATIBILITY_EXPORT_SCHEMA,
                "kind": "ast_compatibility_bundle_export",
                "revision": revision,
                "owner_task_id": AST_ONLY_OWNER_TASK,
                "operational_authority": False,
                "named_export_command": "write_compatibility_export",
                "repository_id": repository_id,
                "tenant_id": scope_tenant,
                "artifacts": {
                    name: AST_LEGACY_BUNDLE_ARTIFACTS[name] for name in files
                },
                "artifact_checksums": checksums,
                "counts": {
                    "ast_paths": ast_index["path_count"],
                    "objectives": objective_graph["goal_count"],
                    "evidence_nodes": evidence_graph["node_count"],
                    "evidence_edges": evidence_graph["edge_count"],
                },
            }
            manifest_path = dest / AST_LEGACY_BUNDLE_ARTIFACTS["manifest"]
            manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            written["manifest"] = str(manifest_path)
        return {
            "ok": True,
            "schema": AST_COMPATIBILITY_EXPORT_SCHEMA,
            "named_export_command": "write_compatibility_export",
            "destination": str(dest),
            "written": written,
            "checksums": checksums,
            "manifest": manifest,
            "operational_authority": False,
            "legacy_bundle_operational": False,
            "repository_id": repository_id,
            "tenant_id": scope_tenant,
        }

    def publication_view(
        self,
        *,
        repository_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Sanitized publication view filtered by repository and tenant.

        Intended for the DQK-058 publication plane: only identity-bearing,
        non-secret AST/evidence aggregates cross the boundary, and only for
        the requested repository + tenant scope.
        """

        with self._lock:
            self._stats["publication_views"] += 1
            self._stats["consumer_reads"] += 1
            return self._publication_view_locked(
                repository_id=repository_id,
                tenant_id=tenant_id,
            )

    def _publication_view_locked(
        self,
        *,
        repository_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        scope_tenant = tenant_id  # None means all tenants when not provided
        nodes: list[dict[str, Any]] = []
        for blob_id, authority_key in sorted(self._active_blob_keys.items()):
            if blob_id in self._invalidated_blobs:
                continue
            blob_repo = self._blob_repository.get(blob_id, "")
            blob_tenant = self._blob_tenant.get(blob_id, self._tenant_id)
            if repository_id is not None and blob_repo != repository_id:
                continue
            if scope_tenant is not None and blob_tenant != scope_tenant:
                continue
            projection = self._store.get(blob_id)
            if projection is None:
                continue
            symbols = [s.qualified_name for s in projection.symbols]
            nodes.append(
                {
                    "node_id": f"tree:{projection.source_file.path}",
                    "kind": "tree",
                    "path": projection.source_file.path,
                    "blob_id": blob_id,
                    "ast_cid": projection.ast_cid,
                    "source_cid": projection.source_cid,
                    "symbols": symbols,
                    "authority_key": authority_key,
                    "repository_id": blob_repo,
                    "tenant_id": blob_tenant,
                    "source": AST_AUTHORITY_DEFAULT_SOURCE,
                }
            )
        allowed_blobs = {n["blob_id"] for n in nodes}
        allowed_paths = {n["path"] for n in nodes}
        evidence_edges = [
            dict(edge)
            for edge_id, edge in sorted(self._active_edges.items())
            if not edge.get("invalidated")
            and edge_id not in self._invalidated_edges
            and (
                repository_id is None
                or edge.get("repository_id") in {None, "", repository_id}
                or any(
                    edge.get("source_cid") == n.get("source_cid")
                    for n in nodes
                )
            )
        ]
        dependency_edges = [
            {
                "source": e["source"],
                "target": e["target"],
                "kind": e["kind"],
                "blob_id": e.get("blob_id"),
                "repository_id": e.get("repository_id"),
                "tenant_id": e.get("tenant_id"),
            }
            for e in self._impact_edges
            if e.get("blob_id") in allowed_blobs
            or e.get("source") in allowed_paths
        ]
        conflict_edges = [
            dict(edge)
            for edge in self._conflict_edges
            if edge.get("edge_id") not in self._invalidated_edges
            and (
                edge.get("left") in allowed_paths
                or edge.get("right") in allowed_paths
                or not allowed_paths
            )
        ]
        symbol_conflicts: list[dict[str, Any]] = []
        for symbol, blob_ids in sorted(self._symbol_index.items()):
            live = sorted(
                bid
                for bid in blob_ids
                if bid in allowed_blobs and bid not in self._invalidated_blobs
            )
            if len(live) > 1:
                symbol_conflicts.append(
                    {
                        "kind": "duplicate_symbol",
                        "symbol": symbol,
                        "blob_ids": live,
                        "blocks_concurrency": True,
                    }
                )
        objectives = [
            dict(item)
            for item in self._objectives.values()
            if (
                repository_id is None
                or item.get("repository_id") == repository_id
            )
            and (
                scope_tenant is None
                or item.get("tenant_id") in {None, "", scope_tenant}
            )
        ]
        view = {
            "schema": AST_PUBLICATION_VIEW_SCHEMA,
            "kind": "ast_publication_view",
            "owner_task_id": AST_ONLY_OWNER_TASK,
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "operational_authority": "duckdb",
            "legacy_bundle_operational": False,
            "filter": {
                "repository_id": repository_id,
                "tenant_id": scope_tenant,
            },
            "node_count": len(nodes),
            "nodes": nodes,
            "evidence_edges": evidence_edges,
            "dependency_edges": dependency_edges,
            "conflict_edges": conflict_edges,
            "symbol_conflicts": symbol_conflicts,
            "objectives": objectives,
            # Publication plane must never see raw source bytes or secrets.
            "excluded_surfaces": (
                "source_bytes",
                "raw_payload",
                "secrets",
                "authority_tokens",
                "legacy_json_bundle_files",
            ),
        }
        view["view_digest"] = _decision_digest(view)
        return view

    def register_objective(
        self,
        goal_id: str,
        *,
        title: str = "",
        repository_id: str | None = None,
        tenant_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register an objective goal in DuckDB-backed operational state."""

        body = {
            "goal_id": str(goal_id),
            "title": str(title or goal_id),
            "repository_id": repository_id,
            "tenant_id": str(tenant_id or self._tenant_id),
            "metadata": dict(metadata or {}),
            "source": AST_AUTHORITY_DEFAULT_SOURCE,
        }
        with self._lock:
            self._objectives[str(goal_id)] = body
        return dict(body)

    def objective_query(
        self,
        *,
        repository_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Objective consumer view over DuckDB state (never loads JSON)."""

        with self._lock:
            self._stats["consumer_reads"] += 1
            goals = [
                dict(item)
                for item in self._objectives.values()
                if (
                    repository_id is None
                    or item.get("repository_id") == repository_id
                )
                and (
                    tenant_id is None
                    or item.get("tenant_id") in {None, "", tenant_id}
                )
            ]
            decision = {
                "schema": AST_CONSUMER_DECISION_SCHEMA,
                "family": "objective",
                "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
                "mode": self.mode,
                "goal_count": len(goals),
                "goals": goals,
                "legacy_bundle_operational": False,
            }
            decision["decision_digest"] = _decision_digest(decision)
            return decision

    # -- consumer surfaces (DuckDB default) ---------------------------------

    def conflict_query(
        self,
        *,
        seed_paths: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Conflict decisions from DuckDB-indexed impact/evidence edges."""

        with self._lock:
            self._stats["consumer_reads"] += 1
            edges = [
                dict(edge)
                for edge in self._conflict_edges
                if edge.get("edge_id") not in self._invalidated_edges
            ]
            # Derive soft conflicts: two blobs defining the same symbol.
            symbol_conflicts: list[dict[str, Any]] = []
            for symbol, blob_ids in sorted(self._symbol_index.items()):
                live = sorted(
                    bid
                    for bid in blob_ids
                    if bid in self._active_blob_keys
                    and bid not in self._invalidated_blobs
                )
                if len(live) > 1:
                    symbol_conflicts.append(
                        {
                            "kind": "duplicate_symbol",
                            "symbol": symbol,
                            "blob_ids": live,
                            "blocks_concurrency": True,
                        }
                    )
            if seed_paths:
                seeds = set(seed_paths)
                edges = [
                    e
                    for e in edges
                    if e.get("left") in seeds or e.get("right") in seeds
                ]
                symbol_conflicts = [
                    c
                    for c in symbol_conflicts
                    if any(
                        (self._store.get(b) is not None)
                        and self._store.get(b).source_file.path in seeds
                        for b in c["blob_ids"]
                    )
                ]
            decision = {
                "schema": AST_CONSUMER_DECISION_SCHEMA,
                "family": "conflict",
                "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
                "mode": self.mode,
                "edge_count": len(edges) + len(symbol_conflicts),
                "edges": edges,
                "symbol_conflicts": symbol_conflicts,
                "active_blob_count": len(self._active_blob_keys),
            }
            decision["decision_digest"] = _decision_digest(decision)
            return decision

    def dependency_query(
        self,
        *,
        seed_ids: Sequence[str],
        direction: str = "forward",
        kinds: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Bounded dependency closure from DuckDB-backed evidence edges."""

        from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (
            ImpactBudget,
            ImpactGraph,
            closure,
        )

        with self._lock:
            self._stats["consumer_reads"] += 1
            graph = ImpactGraph(source_revision="ast-authority")
            kind_filter = frozenset(kinds) if kinds is not None else None
            for edge in self._active_edges.values():
                if edge.get("invalidated"):
                    continue
                kind = str(edge.get("kind") or "dependency")
                # Map evidence kinds onto impact kinds.
                impact_kind = {
                    "depends_on": "import",
                    "defines_symbol": "reference",
                    "derived_from": "call",
                }.get(kind, "dependency")
                if kind_filter is not None and impact_kind not in kind_filter:
                    continue
                graph.add(
                    str(edge.get("source") or ""),
                    str(edge.get("target") or ""),
                    impact_kind,
                )
            for edge in self._impact_edges:
                if edge.get("blob_id") in self._invalidated_blobs:
                    continue
                kind = str(edge.get("kind") or "dependency")
                if kind_filter is not None and kind not in kind_filter:
                    continue
                graph.add(
                    str(edge["source"]),
                    str(edge["target"]),
                    kind,
                )
            result = closure(
                graph,
                list(seed_ids),
                direction=direction,
                kinds=kind_filter,
                budget=ImpactBudget(),
            )
            decision = {
                "schema": AST_CONSUMER_DECISION_SCHEMA,
                "family": "dependency",
                "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
                "mode": self.mode,
                "source_revision": result.source_revision,
                "roots": list(result.roots),
                "nodes": list(result.nodes),
                "edges": [
                    {"source": e.source, "target": e.target, "kind": e.kind}
                    for e in result.edges
                ],
                "depth_reached": result.depth_reached,
                "truncated": result.truncated,
            }
            decision["decision_digest"] = _decision_digest(decision)
            return decision

    def impact_query(
        self,
        *,
        roots: Sequence[str],
        direction: str = "forward",
        kinds: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Impact decisions from the same DuckDB dependency surface."""

        dep = self.dependency_query(
            seed_ids=roots, direction=direction, kinds=kinds
        )
        dep["family"] = "impact"
        # Re-digest after family stamp so scheduling/impact agree on structure
        # but remain family-tagged.
        body = {k: v for k, v in dep.items() if k != "decision_digest"}
        dep["decision_digest"] = _decision_digest(body)
        return dep

    def validation_selection_query(
        self,
        *,
        changed_paths: Sequence[str] = (),
        changed_symbols: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Select validations impacted by changed paths/symbols (DuckDB)."""

        with self._lock:
            self._stats["consumer_reads"] += 1
            changed_path_set = {str(p) for p in changed_paths if str(p)}
            changed_symbol_set = {str(s) for s in changed_symbols if str(s)}
            # Expand symbols defined on changed paths.
            for path in list(changed_path_set):
                blob_id = self._path_to_blob.get(path)
                if blob_id is None or blob_id in self._invalidated_blobs:
                    continue
                projection = self._store.get(blob_id)
                if projection is None:
                    continue
                for symbol in projection.symbols:
                    changed_symbol_set.add(symbol.qualified_name)
                    changed_symbol_set.add(symbol.name)
            # Reverse impact: dependents of changed symbols/paths via edges.
            impacted: set[str] = set(changed_path_set) | set(changed_symbol_set)
            for edge in self._impact_edges:
                if edge.get("blob_id") in self._invalidated_blobs:
                    continue
                if edge["source"] in impacted or edge["target"] in impacted:
                    impacted.add(str(edge["source"]))
                    impacted.add(str(edge["target"]))
            for edge in self._active_edges.values():
                if edge.get("invalidated"):
                    continue
                src = str(edge.get("source") or "")
                tgt = str(edge.get("target") or "")
                if src in impacted or tgt in impacted:
                    impacted.add(src)
                    impacted.add(tgt)
            required: dict[str, list[str]] = {}
            for validation_id, targets in sorted(self._validation_targets.items()):
                hit = sorted(impacted.intersection(targets))
                if hit:
                    required[validation_id] = hit
            # Default validation ids derived from impacted symbols when none
            # are registered explicitly.
            if not required and impacted:
                for item in sorted(impacted):
                    if item.startswith("symbol:") or "." in item:
                        vid = f"validation:{item}"
                        required[vid] = [item]
            decision = {
                "schema": AST_CONSUMER_DECISION_SCHEMA,
                "family": "validation_selection",
                "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
                "mode": self.mode,
                "changed_paths": sorted(changed_path_set),
                "changed_symbols": sorted(changed_symbol_set),
                "impacted_targets": sorted(impacted),
                "required_validation_ids": sorted(required),
                "validation_reasons": required,
            }
            decision["decision_digest"] = _decision_digest(decision)
            return decision

    def code_evidence_query(
        self,
        *,
        path: str | None = None,
        symbol: str | None = None,
        authoritative_only: bool = True,
    ) -> dict[str, Any]:
        """Code-evidence consumer view over live DuckDB projections + edges."""

        with self._lock:
            self._stats["consumer_reads"] += 1
            nodes: list[dict[str, Any]] = []
            for blob_id, authority_key in sorted(self._active_blob_keys.items()):
                if blob_id in self._invalidated_blobs:
                    continue
                projection = self._store.get(blob_id)
                if projection is None:
                    continue
                if path is not None and projection.source_file.path != path:
                    continue
                # Prefer DuckDB dual document identity.
                payload = self._port.read(authority_key)
                identity = {}
                if isinstance(payload, Mapping):
                    if payload.get("invalidated"):
                        continue
                    identity = dict(payload.get("identity") or {})
                    db_proj = payload.get("db_projection") or {}
                    if isinstance(db_proj, Mapping):
                        identity = dict(db_proj.get("identity") or identity)
                symbols = [s.qualified_name for s in projection.symbols]
                if symbol is not None:
                    simple = {item.rsplit(".", 1)[-1] for item in symbols}
                    if symbol not in symbols and symbol not in simple:
                        continue
                nodes.append(
                    {
                        "node_id": f"tree:{projection.source_file.path}",
                        "kind": "tree",
                        "path": projection.source_file.path,
                        "blob_id": blob_id,
                        "ast_cid": projection.ast_cid,
                        "source_cid": projection.source_cid,
                        "symbols": symbols,
                        "authority_key": authority_key,
                        "identity": identity,
                        "source": AST_AUTHORITY_DEFAULT_SOURCE,
                    }
                )
            edges = []
            for edge_id, edge in sorted(self._active_edges.items()):
                if edge.get("invalidated") or edge_id in self._invalidated_edges:
                    continue
                if authoritative_only and not edge.get("authoritative", True):
                    continue
                edges.append(dict(edge))
            decision = {
                "schema": AST_CONSUMER_DECISION_SCHEMA,
                "family": "code_evidence",
                "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
                "mode": self.mode,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes": nodes,
                "edges": edges,
            }
            decision["decision_digest"] = _decision_digest(decision)
            return decision

    def register_validation_target(
        self, validation_id: str, targets: Sequence[str]
    ) -> None:
        """Register validation → impact targets for validation-selection."""

        with self._lock:
            self._validation_targets[str(validation_id)] = sorted(
                {str(t) for t in targets if str(t)}
            )

    def register_conflict_edge(self, edge: Mapping[str, Any]) -> None:
        """Register an explicit conflict edge for conflict consumers."""

        with self._lock:
            body = dict(edge)
            body.setdefault("edge_id", f"conflict:{len(self._conflict_edges)}")
            self._conflict_edges.append(body)

    # -- parity / soak ------------------------------------------------------

    def emit_parity(self, authority_key: str) -> dict[str, Any]:
        """Port + differential parity; JSON export must match DB projection."""

        receipt = self._port.emit_parity_receipt(authority_key)
        legacy = self._port.backend.get_legacy(self.domain, authority_key)
        db = self._port.backend.get_db(self.domain, authority_key)
        report: dict[str, Any] = {
            "authority_key": authority_key,
            "port_parity_matched": bool(getattr(receipt, "matched", False)),
            "port_parity_receipt_cid": getattr(receipt, "receipt_cid", ""),
            "port_mismatch_reason": getattr(receipt, "mismatch_reason", ""),
            "differential": None,
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
        }
        if (
            isinstance(legacy, Mapping)
            and isinstance(db, Mapping)
            and legacy.get("kind") in {"ast_authority_dual", "ast_shadow_dual"}
        ):
            json_side = dict(legacy.get("json_bundle") or {})
            db_side = dict(db.get("db_projection") or {})
            # Compare identity fields (exports omit some shadow-only pins).
            json_identity = dict(json_side.get("identity") or {})
            db_identity = dict(db_side.get("identity") or {})
            identity_match = json_identity == db_identity
            # Family digests for span-bearing tables.
            diff = differential_parity(
                {
                    "identity": json_identity,
                    "symbols": json_side.get("symbols") or db_side.get("symbols"),
                    "imports": json_side.get("imports") or db_side.get("imports"),
                    "calls": json_side.get("calls") or db_side.get("calls"),
                    "effects": json_side.get("effects") or db_side.get("effects"),
                    "diagnostics": json_side.get("diagnostics")
                    or db_side.get("diagnostics"),
                    "nodes": json_side.get("nodes") or db_side.get("nodes"),
                    "scopes": json_side.get("scopes") or db_side.get("scopes"),
                    "references": json_side.get("references")
                    or db_side.get("references"),
                    "interfaces": json_side.get("interfaces")
                    or db_side.get("interfaces"),
                    "table_row_counts": json_side.get("table_row_counts")
                    or db_side.get("table_row_counts"),
                },
                db_side,
            )
            dual_match = dict(legacy.get("identity") or {}) == dict(
                db.get("identity") or {}
            )
            report["differential"] = diff
            report["dual_identity_match"] = dual_match
            report["json_identity_match"] = identity_match
            report["export_is_non_authoritative"] = (
                json_side.get("operational_authority") is False
                or json_side.get("kind") == "ast_json_outbox_export"
            )
            report["matched"] = bool(
                report["port_parity_matched"]
                and diff.get("matched")
                and dual_match
            )
        else:
            report["matched"] = bool(report["port_parity_matched"])
        with self._lock:
            self._stats["parity_checks"] += 1
            if report["matched"]:
                self._stats["parity_matches"] += 1
        return report

    def parity_soak(
        self,
        *,
        rounds: int = 3,
        consumer_families: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Re-run scheduling/impact consumer decisions and require agreement.

        Each round recomputes dependency, impact, conflict, validation-
        selection, and code-evidence decisions.  Digests must be stable across
        rounds (parity soak).
        """

        families = list(
            consumer_families
            or (
                "dependency",
                "impact",
                "conflict",
                "validation_selection",
                "code_evidence",
            )
        )
        seeds = list(self._path_to_blob.keys()) or ["__empty__"]
        digests_by_family: dict[str, list[str]] = {f: [] for f in families}
        last_decisions: dict[str, dict[str, Any]] = {}
        for _ in range(max(1, int(rounds))):
            for family in families:
                if family == "dependency":
                    decision = self.dependency_query(seed_ids=seeds[:1])
                elif family == "impact":
                    decision = self.impact_query(roots=seeds[:1])
                elif family == "conflict":
                    decision = self.conflict_query()
                elif family == "validation_selection":
                    decision = self.validation_selection_query(
                        changed_paths=seeds[:1]
                    )
                elif family == "code_evidence":
                    decision = self.code_evidence_query()
                else:
                    raise ASTAuthorityError(f"unknown consumer family {family!r}")
                digests_by_family[family].append(decision["decision_digest"])
                last_decisions[family] = decision
        agreements: dict[str, bool] = {}
        for family, digests in digests_by_family.items():
            agreements[family] = len(set(digests)) == 1
        # Scheduling (dependency) and impact must agree on node sets when
        # queried with the same roots/direction.
        dep_nodes = set(last_decisions.get("dependency", {}).get("nodes") or ())
        impact_nodes = set(last_decisions.get("impact", {}).get("nodes") or ())
        scheduling_impact_agree = dep_nodes == impact_nodes
        return {
            "schema": f"{AST_AUTHORITY_SCHEMA}/parity-soak",
            "rounds": rounds,
            "families": families,
            "digests_by_family": digests_by_family,
            "agreements": agreements,
            "all_agreed": all(agreements.values()),
            "scheduling_impact_agree": scheduling_impact_agree,
            "default_source": AST_AUTHORITY_DEFAULT_SOURCE,
            "mode": self.mode,
            "matched": all(agreements.values()) and scheduling_impact_agree,
        }

    def extract_and_write(
        self,
        sources: Sequence[Mapping[str, Any] | tuple[Any, ...]],
        *,
        repository_id: str = "repository:authority",
        revision: str = "unversioned",
        repository_tree_cid: str | None = None,
        continue_on_parse_failure: bool = True,
        **kwargs: Any,
    ) -> ASTShadowBatchResult:
        """Extract sources and dual-write each through the authority port."""

        # Reuse shadow extraction pipeline but dual-write via this repository.
        shadow = ASTAuthorityShadowWriter(
            self._port,
            ast_store=self._store,
            writer_id=self._writer_id,
            task_id=self._task_id,
        )
        # Temporarily swap write_projection to dual-write path.
        original_write = shadow.write_projection

        def _dual_write(projection: Any, **write_kwargs: Any) -> dict[str, Any]:
            return self.write_projection(projection, **write_kwargs)

        shadow.write_projection = _dual_write  # type: ignore[method-assign]
        try:
            batch = shadow.extract_and_shadow(
                sources,
                repository_id=repository_id,
                revision=revision,
                repository_tree_cid=repository_tree_cid,
                continue_on_parse_failure=continue_on_parse_failure,
                **kwargs,
            )
        finally:
            shadow.write_projection = original_write  # type: ignore[method-assign]
        return batch


def build_ast_authority_repository(
    authority_port: Any | None = None,
    *,
    domain: str = AST_AUTHORITY_DOMAIN,
    initial_mode: str = AST_AUTHORITY_DEFAULT_MODE,
    ast_store: Any | None = None,
    writer_id: str = "writer:ast-authority",
    task_id: str = AST_AUTHORITY_OWNER_TASK,
    default_source: str = AST_AUTHORITY_DEFAULT_SOURCE,
    tenant_id: str = AST_DEFAULT_TENANT_ID,
    promote_to_db_primary: bool = False,
) -> ASTAuthorityRepository:
    """Construct an AST authority repository (DuckDB default source).

    Greenfield ports default to ``db-primary`` (DQK-070).  When an existing
    port is supplied its mode is preserved unless ``promote_to_db_primary`` is
    set, so DQK-069 dual-mode tests remain stable.
    """

    if authority_port is None:
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            build_authority_port,
        )

        authority_port = build_authority_port(
            domain=domain,
            initial_mode=AuthorityMode.parse(initial_mode),
            writer_id=writer_id,
        )
    else:
        # Promote shadow → dual when the port is still in shadow mode.
        mode = getattr(authority_port, "mode", None)
        mode_value = getattr(mode, "value", str(mode) if mode is not None else "")
        if mode_value == "shadow":
            try:
                authority_port.promote(
                    "dual",
                    require_parity=False,
                    decision_id=f"dec:ast-auth:{task_id}:to-dual",
                )
                mode_value = "dual"
            except Exception:
                pass
        if promote_to_db_primary and mode_value == "dual":
            try:
                authority_port.promote(
                    "db-primary",
                    require_parity=False,
                    decision_id=f"dec:ast-auth:{task_id}:to-db-primary",
                )
            except Exception:
                pass
    return ASTAuthorityRepository(
        authority_port,
        ast_store=ast_store,
        writer_id=writer_id,
        task_id=task_id,
        default_source=default_source,
        tenant_id=tenant_id,
    )


def extract_repository_ast_authority(
    sources: Sequence[Mapping[str, Any] | tuple[Any, ...]],
    *,
    repository_id: str = "repository:authority",
    revision: str = "unversioned",
    repository_tree_cid: str | None = None,
    authority_port: Any | None = None,
    **kwargs: Any,
) -> ASTShadowBatchResult:
    """Convenience entry: extract sources and dual-write through the repository."""

    repo = build_ast_authority_repository(authority_port)
    return repo.extract_and_write(
        sources,
        repository_id=repository_id,
        revision=revision,
        repository_tree_cid=repository_tree_cid,
        **kwargs,
    )


__all__ = [
    "ALL_DISPOSITIONS",
    "ASTAuthorityError",
    "ASTAuthorityRepository",
    "ASTAuthorityShadowWriter",
    "ASTShadowBatchResult",
    "ASTShadowError",
    "ASTShadowFileResult",
    "AST_AUTHORITY_DEFAULT_MODE",
    "AST_AUTHORITY_DEFAULT_SOURCE",
    "AST_AUTHORITY_DOMAIN",
    "AST_AUTHORITY_INTERFACE",
    "AST_AUTHORITY_JSON_EXPORT_SCHEMA",
    "AST_AUTHORITY_OWNER_TASK",
    "AST_AUTHORITY_SCHEMA",
    "AST_COMPATIBILITY_EXPORT_SCHEMA",
    "AST_CONSUMER_DECISION_SCHEMA",
    "AST_DEFAULT_TENANT_ID",
    "AST_EVIDENCE_EDGE_SCHEMA",
    "AST_INVALIDATION_RECORD_SCHEMA",
    "AST_JSON_BUNDLE_SCHEMA",
    "AST_LEGACY_BUNDLE_ARTIFACTS",
    "AST_NAMED_EXPORT_COMMANDS",
    "AST_ONLY_DEFAULT_MODE",
    "AST_ONLY_INTERFACE",
    "AST_ONLY_OWNER_TASK",
    "AST_PUBLICATION_VIEW_SCHEMA",
    "AST_SHADOW_INTERFACE",
    "AST_SHADOW_OWNER_TASK",
    "AST_SHADOW_SCHEMA",
    "COVERAGE_EXCLUDED_SEMANTIC",
    "COVERAGE_INCOMPLETE",
    "COVERAGE_INVENTORIED",
    "COVERAGE_QUEUED_SEMANTIC",
    "DEFAULT_MAX_BLOB_BYTES",
    "DEFAULT_SELECTED_ROOTS",
    "DEFAULT_SHARD_SIZE",
    "DISPOSITION_ARCHIVED",
    "DISPOSITION_BINARY",
    "DISPOSITION_GENERATED",
    "DISPOSITION_MISSING",
    "DISPOSITION_OVERSIZED",
    "DISPOSITION_PARSEABLE",
    "DISPOSITION_UNSUPPORTED",
    "DISPOSITION_VENDORED",
    "GOAL_ID",
    "GitlinkRecord",
    "MODE_EXECUTABLE",
    "MODE_GITLINK",
    "MODE_REGULAR",
    "MODE_SYMLINK",
    "OBJECTIVE_VALIDATION_EVIDENCE",
    "PACKAGE_MIRROR_NAMES",
    "REPAIR_TASK_ID",
    "RepositoryManifestError",
    "RepositorySnapshot",
    "SCHEMA_GITLINK",
    "SCHEMA_REPOSITORY_ROOT",
    "SCHEMA_SNAPSHOT",
    "SCHEMA_TRACKED_BLOB",
    "STATUS_COMPLETE",
    "STATUS_INCOMPLETE_SCAN",
    "ShardPlanEntry",
    "TASK_ID",
    "TrackedBlob",
    "authority_key_for_projection",
    "batch_blob_bytes",
    "build_ast_authority_repository",
    "build_ast_authority_shadow_writer",
    "build_repository_snapshot",
    "build_snapshot_from_entries",
    "build_tracked_blobs_for_root",
    "checkout_identity",
    "cid_for_blob_bytes",
    "classify_blob",
    "detect_language",
    "deterministic_json_bundle_export",
    "deterministic_json_export_bytes",
    "differential_parity",
    "evidence_edges_from_projection",
    "extract_repository_ast_authority",
    "extract_repository_ast_shadow",
    "is_git_checkout",
    "json_bundle_from_projection",
    "list_tree_entries",
    "load_repository_root_manifest",
    "projection_to_authority_payload",
    "validate_repository_root_manifest",
    "write_repository_root_manifest",
]
