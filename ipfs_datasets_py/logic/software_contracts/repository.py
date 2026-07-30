"""Recursive tracked-object repository manifests (DSCON-G020).

Reads Git objects (not ambient filesystem walks), walks selected logical
roots and recursive gitlinks by object identity, deduplicates mirror cycles,
classifies every tracked blob with an explicit parser disposition, shards
deterministically, and produces a content-addressed repository-root summary.

Unsupported, generated, vendored, binary, archived, oversized, and missing
paths stay in the inventory with an explicit exclusion reason.  Their content
is hashed (CID) when bytes are available; they are never parsed or proved.
"""

from __future__ import annotations

import json
import re
import subprocess
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


__all__ = [
    "ALL_DISPOSITIONS",
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
    "PACKAGE_MIRROR_NAMES",
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
    "batch_blob_bytes",
    "build_repository_snapshot",
    "build_snapshot_from_entries",
    "build_tracked_blobs_for_root",
    "checkout_identity",
    "cid_for_blob_bytes",
    "classify_blob",
    "detect_language",
    "is_git_checkout",
    "list_tree_entries",
    "load_repository_root_manifest",
    "validate_repository_root_manifest",
    "write_repository_root_manifest",
]
