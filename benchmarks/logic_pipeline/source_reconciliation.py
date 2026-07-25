"""Fail-closed source reconciliation for the HSSL reassessment baseline.

The original A0 manifest is historical evidence.  It must continue to describe
the source and runtime that produced the v1 result even after the repository or
one of its submodule gitlinks advances.  This module therefore creates a
separate, canonical reconciliation receipt for a fresh run.  The receipt binds
the detached source tree, recursive gitlinks, environment inventory, treatment
files, normalized A0 pilot behavior, and every mutable namespace.

No function in this module rewrites a predecessor artifact.  New manifests are
written with exclusive-create semantics, and reconciliation fails before
acceptance when source or normalized behavior drifts without an explanation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Sequence

from benchmarks.logic_pipeline import (
    BENCHMARK_ID,
    DEFAULT_BENCHMARK_ROOT,
    RunPaths,
)
from benchmarks.logic_pipeline.capabilities import (
    CapabilityInventory,
    WORKTREE_SAFETY_RECEIPT_NAME,
    WorktreeSafetyReceipt,
    canonical_worktree_safety_json,
    prepare_isolated_worktree,
)
from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline.runner import (
    CURRENT_ROUTE,
    DEFAULT_BASELINE_MANIFEST_PATH,
    FROZEN_BASELINE_MANIFEST_SHA256,
    SOURCE_SNAPSHOT_FILES,
    load_baseline_manifest,
)
from benchmarks.logic_pipeline.reassessment_namespace import (
    PUBLISHED_CAPABILITY_SNAPSHOT,
    PUBLISHED_FINAL_DECISION,
    PUBLISHED_HOLDOUT_SNAPSHOT,
    PUBLISHED_MATRIX_SNAPSHOT,
    PUBLISHED_PILOT_SNAPSHOT,
    PUBLISHED_PREDECESSOR_ARTIFACTS,
    PUBLISHED_REASSESSMENT_RUN_ID,
    PUBLISHED_REPORTS_SNAPSHOT,
    PUBLISHED_RUNBOOK,
    PUBLISHED_RUNTIME_LOCKS,
    ReassessmentNamespaceError,
    ReassessmentRunLayout,
    reject_published_write_targets,
    require_fresh_reassessment_run,
)

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]

SOURCE_RECONCILIATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.source-reconciled-baseline.v1"
)
FRESH_SOURCE_BASELINE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.repaired-source-baseline.v1"
)
FRESH_SOURCE_BASELINE_ID: Final = "a0-repaired-within-run-v1"
FRESH_NESTED_GITLINK_PARENT: Final = "ipfs_accelerate_py"
FRESH_MAX_GITLINK_DEPTH: Final = 2
OUTPUT_NORMALIZATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.a0-normalized-pilot-output.v1"
)
REASSESSMENT_RUN_ID: Final = PUBLISHED_REASSESSMENT_RUN_ID
REASSESSMENT_BASELINE_ID: Final = "a0-current-effective-v2"
DEFAULT_RECONCILED_MANIFEST_PATH: Final = (
    ReassessmentRunLayout.for_run(REASSESSMENT_RUN_ID).baseline_manifest
)
DEFAULT_IMMUTABLE_V1_ARTIFACT_PATHS: Final = (
    DEFAULT_BASELINE_MANIFEST_PATH,
    DEFAULT_BENCHMARK_ROOT / "results" / "frontend-overlap-v1.json",
    DEFAULT_BENCHMARK_ROOT / "results" / "holdout-evaluation-v1.json",
    DEFAULT_BENCHMARK_ROOT / "results" / "pilot-shortlist-v1.json",
    DEFAULT_BENCHMARK_ROOT / "results" / "proof-overlap-ordering-v1.json",
    Path("docs")
    / "performance_snapshots"
    / "2026-07-24_hammer_symai_spacy_leanstral_final_decision.json",
)
PROCESS_NAMESPACE_NAME: Final = "process"
FROZEN_NORMALIZED_A0_PILOT_SHA256: Final = (
    "599e85c5c19c87c370cdf28f8a156ff5af3fc6f6c186028c963c84f659319b22"
)
PUBLISHED_REASSESSMENT_BASELINE_SHA256: Final = (
    "6c7084db784022d81abc65148fb0d72a8046da881c4d4b448434b9b13af7e469"
)
PUBLISHED_REASSESSMENT_BASELINE_BYTES_SHA256: Final = (
    "efff421a0c0e23f9b8a53e427e86bcb4781e9a583e0a2aa94624b80e29bfb9d0"
)
DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS: Final = tuple(
    sorted(
        {
            DEFAULT_RECONCILED_MANIFEST_PATH,
            PUBLISHED_CAPABILITY_SNAPSHOT,
            PUBLISHED_MATRIX_SNAPSHOT,
            PUBLISHED_PILOT_SNAPSHOT,
            PUBLISHED_HOLDOUT_SNAPSHOT,
            PUBLISHED_REPORTS_SNAPSHOT,
            PUBLISHED_FINAL_DECISION,
            PUBLISHED_RUNBOOK,
            *PUBLISHED_RUNTIME_LOCKS,
            *PUBLISHED_PREDECESSOR_ARTIFACTS,
        },
        key=lambda path: path.as_posix(),
    )
)

_HEX_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|credential|password|private[_-]?key|secret|token)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|(?:ghp|hf)_[A-Za-z0-9_-]{20,}"
    r"|(?:glpat|sk-proj|sk)-[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}"
    r")"
)


class SourceReconciliationError(ValueError):
    """Raised when a fresh baseline cannot be reconciled safely."""


def HSSLEV1134D84() -> str:
    """Return the AST-verifiable source-freshness evidence marker."""

    return (
        "fresh detached source with exact recursive gitlinks, source-bound "
        "environment inventory, disjoint v2 namespaces, immutable v1 "
        "evidence, and fail-closed normalized A0 behavior equivalence"
    )


def HSSLEV1158F41() -> str:
    """Return the evidence marker for a repaired within-run source control."""

    return (
        "fresh detached repaired source with recursive local-only gitlinks, "
        "secret-safe generic capability inventory, immutable published "
        "predecessor snapshots, and matrix-deferred behavior comparison"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve(strict=False)
    right = right.resolve(strict=False)
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
    )


def _logical_absolute_path(path: str | Path, field: str) -> Path:
    """Return an absolute lexical path without following filesystem links."""

    candidate = Path(path)
    if ".." in candidate.parts:
        raise SourceReconciliationError(f"{field} may not contain '..'")
    return Path(os.path.abspath(os.fspath(candidate)))


def _reject_symlink_components(path: str | Path, field: str) -> Path:
    """Reject any symlink in the existing portion of a logical path."""

    logical = _logical_absolute_path(path, field)
    parts = logical.parts
    current = Path(parts[0])
    for index, component in enumerate(parts[1:], start=1):
        current /= component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise SourceReconciliationError(
                f"cannot inspect {field} path component: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SourceReconciliationError(
                f"{field} may not traverse a symlink: {current}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise SourceReconciliationError(
                f"{field} ancestor is not a directory: {current}"
            )
    return logical


def _validate_fresh_run_logical_paths(
    run_paths: RunPaths,
    *,
    manifest_path: str | Path | None = None,
) -> None:
    """Reject aliases before resolving any fresh external run path."""

    _reject_symlink_components(run_paths.benchmark_root, "benchmark_root")
    for directory in run_paths.directories():
        _reject_symlink_components(directory, "fresh run directory")
    if manifest_path is not None:
        _reject_symlink_components(manifest_path, "fresh baseline manifest")


def _read_bytes_nofollow(path: str | Path, field: str) -> bytes:
    """Read a regular file while rejecting logical links and a linked leaf."""

    logical = _reject_symlink_components(path, field)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(logical, flags)
    except OSError as exc:
        raise SourceReconciliationError(f"cannot read {field}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SourceReconciliationError(f"{field} must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _mkdir_without_following_symlinks(
    path: str | Path,
    *,
    mode: int = 0o700,
) -> Path:
    """Create a directory tree without following links at any component."""

    logical = _reject_symlink_components(path, "fresh state directory")
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    cloexec_flag = getattr(os, "O_CLOEXEC", 0)
    if os.name != "posix" or not directory_flag or not nofollow_flag:
        logical.mkdir(mode=mode, parents=True, exist_ok=True)
        _reject_symlink_components(logical, "fresh state directory")
        return logical
    flags = os.O_RDONLY | directory_flag | cloexec_flag
    parent_fd = os.open(logical.anchor, flags)
    try:
        for component in logical.parts[1:]:
            try:
                os.mkdir(component, mode=mode, dir_fd=parent_fd)
            except FileExistsError:
                pass
            try:
                child_fd = os.open(
                    component,
                    flags | nofollow_flag,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise SourceReconciliationError(
                    "fresh state directory contains a symlink or "
                    f"non-directory component: {logical}"
                ) from exc
            if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                os.close(child_fd)
                raise SourceReconciliationError(
                    f"fresh state path is not a directory: {logical}"
                )
            os.close(parent_fd)
            parent_fd = child_fd
    finally:
        os.close(parent_fd)
    return logical


def _write_bytes_exclusive_nofollow(
    path: str | Path,
    value: bytes,
) -> None:
    """Exclusively create a regular file without following its leaf."""

    logical = _reject_symlink_components(path, "fresh baseline manifest")
    _mkdir_without_following_symlinks(logical.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(logical, flags, 0o600)
    except FileExistsError:
        raise
    except OSError as exc:
        raise SourceReconciliationError(
            f"cannot exclusively create fresh source evidence: {exc}"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SourceReconciliationError(f"{field} must be a JSON object")
    return value


def _array(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise SourceReconciliationError(f"{field} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise SourceReconciliationError(
            f"{field} fields invalid: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _safe_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceReconciliationError(f"{field} must be a nonempty path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise SourceReconciliationError(
            f"{field} must be a normalized relative POSIX path"
        )
    return value


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                "PATH": os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceReconciliationError(
            f"Git command failed: {type(exc).__name__}"
        ) from exc
    if check and completed.returncode:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        summary = detail[0][:512] if detail else "no diagnostic"
        raise SourceReconciliationError(
            f"Git command {arguments[0]!r} failed: {summary}"
        )
    return completed


def _git_value(repository: Path, *arguments: str) -> str:
    return _git(repository, *arguments).stdout.strip()


def _resolve_commit(repository: Path, revision: str) -> str:
    if not isinstance(revision, str) or not revision.strip():
        raise SourceReconciliationError("revision must be nonempty")
    commit = _git_value(
        repository,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
    )
    if not _HEX_COMMIT.fullmatch(commit):
        raise SourceReconciliationError("revision is not a full Git commit")
    return commit


def _active_source_snapshot(repository: Path) -> tuple[str, str | None, str]:
    """Capture HEAD, branch, and exact porcelain state for mutation checks."""

    head = _git_value(repository, "rev-parse", "--verify", "HEAD^{commit}")
    branch_result = _git(
        repository,
        "symbolic-ref",
        "--quiet",
        "HEAD",
        check=False,
    )
    branch = (
        branch_result.stdout.strip()
        if branch_result.returncode == 0
        else None
    )
    status = _git_value(
        repository,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    return head, branch, _sha256_bytes(status.encode("utf-8"))


def _worktree_status(
    repository: Path,
    *,
    ignore_submodules: bool,
) -> str:
    return _git_value(
        repository,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        (
            "--ignore-submodules=all"
            if ignore_submodules
            else "--ignore-submodules=none"
        ),
    )


def _require_clean_source_checkout(repository: Path) -> None:
    if _worktree_status(repository, ignore_submodules=False):
        raise SourceReconciliationError(
            "source checkout must be clean before fresh source preparation"
        )


def _validate_live_detached_source(
    repository: Path,
    *,
    commit: str,
    gitlinks: Sequence[GitlinkIdentity],
) -> None:
    """Validate the exact clean detached tree used for live execution."""

    head = _git_value(repository, "rev-parse", "--verify", "HEAD^{commit}")
    if head != commit:
        raise SourceReconciliationError(
            "live repository HEAD does not match the fresh baseline commit"
        )
    if (
        _git(
            repository,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        ).returncode
        == 0
    ):
        raise SourceReconciliationError(
            "live repository HEAD must remain detached"
        )
    if _worktree_status(repository, ignore_submodules=True):
        raise SourceReconciliationError(
            "live detached source worktree must be clean"
        )

    materialized = (item for item in gitlinks if item.depth == 1)
    for item in sorted(
        materialized,
        key=lambda record: record.path,
    ):
        logical = _reject_symlink_components(
            repository / item.path,
            f"submodule {item.path!r}",
        )
        if not logical.is_dir():
            raise SourceReconciliationError(
                f"materialized submodule is missing: {item.path!r}"
            )
        top = Path(
            _git_value(logical, "rev-parse", "--show-toplevel")
        ).resolve()
        if top != logical:
            raise SourceReconciliationError(
                f"submodule is not an exact worktree root: {item.path!r}"
            )
        child_head = _git_value(
            logical,
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        )
        if child_head != item.commit:
            raise SourceReconciliationError(
                f"submodule HEAD drifted from its gitlink: {item.path!r}"
            )
        if (
            _git(
                logical,
                "symbolic-ref",
                "--quiet",
                "HEAD",
                check=False,
            ).returncode
            == 0
        ):
            raise SourceReconciliationError(
                f"submodule HEAD must remain detached: {item.path!r}"
            )
        if _worktree_status(logical, ignore_submodules=True):
            raise SourceReconciliationError(
                f"submodule worktree must be clean: {item.path!r}"
            )


def _direct_gitlinks(
    repository: Path,
    commit: str,
) -> tuple[tuple[str, str], ...]:
    output = _git_value(repository, "ls-tree", "-r", "-z", commit)
    result: list[tuple[str, str]] = []
    for entry in output.split("\0"):
        if not entry:
            continue
        header, separator, path = entry.partition("\t")
        fields = header.split()
        if not separator or len(fields) != 3:
            raise SourceReconciliationError("Git returned a malformed tree entry")
        mode, object_type, object_id = fields
        if mode != "160000":
            continue
        if object_type != "commit" or not _HEX_COMMIT.fullmatch(object_id):
            raise SourceReconciliationError("Git returned a malformed gitlink")
        _safe_relative_path(path, "gitlink path")
        result.append((path, object_id))
    return tuple(sorted(result))


def _exact_submodule_repository(parent: Path, path: str) -> Path | None:
    candidate = (parent / path).resolve()
    if not candidate.is_dir():
        return None
    probe = _git(candidate, "rev-parse", "--show-toplevel", check=False)
    if probe.returncode:
        return None
    try:
        top = Path(probe.stdout.strip()).resolve()
    except OSError:
        return None
    # An uninitialized submodule directory is inside the parent worktree; Git
    # will otherwise walk upward and incorrectly report the parent repository.
    return candidate if top == candidate else None


@dataclass(frozen=True, slots=True, order=True)
class GitlinkIdentity:
    """One exact submodule gitlink in a recursively pinned source tree."""

    path: str
    commit: str
    parent_path: str
    parent_commit: str
    depth: int

    def __post_init__(self) -> None:
        _safe_relative_path(self.path, "gitlink.path")
        if self.parent_path != ".":
            _safe_relative_path(self.parent_path, "gitlink.parent_path")
        if not isinstance(self.commit, str) or not _HEX_COMMIT.fullmatch(self.commit):
            raise SourceReconciliationError("gitlink.commit is not a full commit")
        if (
            not isinstance(self.parent_commit, str)
            or not _HEX_COMMIT.fullmatch(self.parent_commit)
        ):
            raise SourceReconciliationError(
                "gitlink.parent_commit is not a full commit"
            )
        # Depth is repository nesting, not filesystem component count.
        if (
            not isinstance(self.depth, int)
            or isinstance(self.depth, bool)
            or self.depth < 1
        ):
            raise SourceReconciliationError("gitlink.depth must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "commit": self.commit,
            "parent_path": self.parent_path,
            "parent_commit": self.parent_commit,
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, value: object) -> "GitlinkIdentity":
        payload = _mapping(value, "gitlink")
        _exact_keys(payload, set(cls.__dataclass_fields__), "gitlink")
        try:
            return cls(**payload)  # type: ignore[arg-type]
        except TypeError as exc:
            raise SourceReconciliationError("gitlink fields are invalid") from exc


def capture_recursive_gitlinks(
    repository: str | Path,
    revision: str,
    *,
    require_complete: bool = True,
) -> tuple[GitlinkIdentity, ...]:
    """Capture gitlinks recursively from pinned commit trees.

    A child is traversed only when its exact repository and pinned object are
    locally available.  This prevents an empty, uninitialized submodule path
    from silently resolving to its parent.  ``require_complete=True`` is used
    for acceptance and fails closed instead of returning a partial inventory.
    """

    root = Path(repository).resolve()
    if not root.is_dir():
        raise SourceReconciliationError("repository must be an existing directory")
    top = Path(_git_value(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise SourceReconciliationError("repository must name a Git worktree root")
    root_commit = _resolve_commit(root, revision)
    records: list[GitlinkIdentity] = []

    def visit(
        current_repository: Path,
        current_commit: str,
        prefix: str,
        depth: int,
        seen: frozenset[tuple[Path, str]],
    ) -> None:
        identity = (current_repository, current_commit)
        if identity in seen:
            raise SourceReconciliationError("recursive submodule cycle detected")
        next_seen = seen | {identity}
        for child_path, child_commit in _direct_gitlinks(
            current_repository, current_commit
        ):
            qualified = (
                f"{prefix}/{child_path}" if prefix else child_path
            )
            records.append(
                GitlinkIdentity(
                    path=qualified,
                    commit=child_commit,
                    parent_path=prefix or ".",
                    parent_commit=current_commit,
                    depth=depth,
                )
            )
            child_repository = _exact_submodule_repository(
                current_repository, child_path
            )
            if child_repository is None:
                if require_complete:
                    raise SourceReconciliationError(
                        "cannot inspect pinned submodule repository "
                        f"{qualified!r}; recursive inventory would be partial"
                    )
                continue
            object_probe = _git(
                child_repository,
                "cat-file",
                "-e",
                f"{child_commit}^{{commit}}",
                check=False,
            )
            if object_probe.returncode:
                if require_complete:
                    raise SourceReconciliationError(
                        f"pinned submodule commit unavailable for {qualified!r}"
                    )
                continue
            visit(
                child_repository,
                child_commit,
                qualified,
                depth + 1,
                next_seen,
            )

    visit(root, root_commit, "", 1, frozenset())
    paths = [item.path for item in records]
    if len(paths) != len(set(paths)):
        raise SourceReconciliationError("recursive gitlink paths are not unique")
    return tuple(sorted(records, key=lambda item: item.path))


def _capture_benchmark_bounded_gitlinks(
    repository: str | Path,
    revision: str,
) -> tuple[GitlinkIdentity, ...]:
    """Bind the finite source boundary used by benchmark baselines.

    Every top-level gitlink is recorded.  The only nested tree inspected is
    the pinned top-level ``ipfs_accelerate_py`` commit, whose direct gitlinks
    are recorded at depth two.  No depth-two repository is initialized or
    traversed, preventing the cyclic/overbroad tool-repository graph from
    becoming part of benchmark preparation.
    """

    root = Path(repository).resolve()
    if not root.is_dir():
        raise SourceReconciliationError(
            "repository must be an existing directory"
        )
    top = Path(_git_value(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise SourceReconciliationError(
            "repository must name a Git worktree root"
        )
    root_commit = _resolve_commit(root, revision)
    records: list[GitlinkIdentity] = []
    for path, commit in _direct_gitlinks(root, root_commit):
        records.append(
            GitlinkIdentity(
                path=path,
                commit=commit,
                parent_path=".",
                parent_commit=root_commit,
                depth=1,
            )
        )
        if path != FRESH_NESTED_GITLINK_PARENT:
            continue
        child_repository = _exact_submodule_repository(root, path)
        if child_repository is None:
            raise SourceReconciliationError(
                "cannot inspect pinned top-level ipfs_accelerate_py repository"
            )
        if (
            _git(
                child_repository,
                "cat-file",
                "-e",
                f"{commit}^{{commit}}",
                check=False,
            ).returncode
            != 0
        ):
            raise SourceReconciliationError(
                "pinned ipfs_accelerate_py commit is unavailable locally"
            )
        for nested_path, nested_commit in _direct_gitlinks(
            child_repository,
            commit,
        ):
            qualified = f"{path}/{nested_path}"
            records.append(
                GitlinkIdentity(
                    path=qualified,
                    commit=nested_commit,
                    parent_path=path,
                    parent_commit=commit,
                    depth=FRESH_MAX_GITLINK_DEPTH,
                )
            )
    paths = [item.path for item in records]
    if len(paths) != len(set(paths)):
        raise SourceReconciliationError(
            "fresh bounded gitlink paths are not unique"
        )
    return tuple(sorted(records, key=lambda item: item.path))


def _submodule_name_for_path(
    repository: Path,
    commit: str,
    path: str,
) -> str:
    completed = _git(
        repository,
        "config",
        "-z",
        "--blob",
        f"{commit}:.gitmodules",
        "--get-regexp",
        r"^submodule\..*\.path$",
        check=False,
    )
    if completed.returncode:
        raise SourceReconciliationError(
            f"cannot resolve local-only submodule configuration for {path!r}"
        )
    matches: list[str] = []
    for raw_record in completed.stdout.split("\0"):
        if not raw_record:
            continue
        key, separator, configured_path = raw_record.partition("\n")
        if not separator or configured_path != path:
            continue
        prefix = "submodule."
        suffix = ".path"
        if not key.startswith(prefix) or not key.endswith(suffix):
            continue
        name = key[len(prefix) : -len(suffix)]
        if not name or "\n" in name or "\0" in name:
            raise SourceReconciliationError("submodule name is unsafe")
        matches.append(name)
    if len(matches) != 1:
        raise SourceReconciliationError(
            f"gitlink {path!r} does not have exactly one submodule definition"
        )
    return matches[0]


def _materialize_recursive_local_gitlinks(
    source_repository: Path,
    worktree_repository: Path,
    gitlinks: Sequence[GitlinkIdentity],
) -> None:
    """Populate pinned submodules using only already-provisioned local repos."""

    for item in sorted(gitlinks, key=lambda record: (record.depth, record.path)):
        parent_relative = (
            Path() if item.parent_path == "." else Path(item.parent_path)
        )
        child_relative = Path(item.path).relative_to(parent_relative)
        source_parent = (source_repository / parent_relative).resolve()
        worktree_parent = (worktree_repository / parent_relative).resolve()
        local_child = (source_repository / item.path).resolve()
        if _exact_submodule_repository(source_parent, child_relative.as_posix()) != (
            local_child
        ):
            raise SourceReconciliationError(
                f"local submodule repository unavailable for {item.path!r}"
            )
        if (
            _git(
                local_child,
                "cat-file",
                "-e",
                f"{item.commit}^{{commit}}",
                check=False,
            ).returncode
            != 0
        ):
            raise SourceReconciliationError(
                f"local submodule commit unavailable for {item.path!r}"
            )
        name = _submodule_name_for_path(
            source_parent,
            item.parent_commit,
            child_relative.as_posix(),
        )
        _git(
            worktree_parent,
            "-c",
            "protocol.file.allow=always",
            "-c",
            f"submodule.{name}.url={local_child}",
            "submodule",
            "update",
            "--init",
            "--checkout",
            "--no-fetch",
            "--",
            child_relative.as_posix(),
            timeout=120,
        )
        materialized = _exact_submodule_repository(
            worktree_parent,
            child_relative.as_posix(),
        )
        if materialized is None:
            raise SourceReconciliationError(
                f"local submodule did not materialize for {item.path!r}"
            )
        actual_commit = _git_value(
            materialized,
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        )
        branch = _git(
            materialized,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        )
        if actual_commit != item.commit or branch.returncode == 0:
            raise SourceReconciliationError(
                f"local submodule identity drifted for {item.path!r}"
            )


def _redact_safe_inventory(value: object, field: str = "environment") -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in sorted(value.items()):
            if not isinstance(key, str):
                raise SourceReconciliationError(f"{field} keys must be strings")
            if _SECRET_KEY.search(key):
                # Capability probing records only whether a credential is
                # configured.  That boolean is useful missingness metadata,
                # not credential material; all other secret-shaped fields
                # remain forbidden regardless of their value.
                if key != "credential_configured" or not isinstance(item, bool):
                    raise SourceReconciliationError(
                        f"{field} contains forbidden credential field {key!r}"
                    )
            result[key] = _redact_safe_inventory(item, f"{field}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _redact_safe_inventory(item, f"{field}[]")
            for item in value
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SourceReconciliationError(f"{field} is not JSON serializable")


def environment_inventory_record(
    inventory: CapabilityInventory | Mapping[str, object],
    *,
    run_id: str,
    source_commit: str,
) -> dict[str, object]:
    """Return a secret-safe, source/run-bound environment record."""

    if isinstance(inventory, CapabilityInventory):
        payload = inventory.to_dict()
        if inventory.run_id != run_id:
            raise SourceReconciliationError(
                "capability inventory belongs to a different run"
            )
        if inventory.source_commit != source_commit:
            raise SourceReconciliationError(
                "capability inventory belongs to a different source commit"
            )
    else:
        payload = dict(_mapping(inventory, "environment inventory"))
    safe = _redact_safe_inventory(payload)
    if not isinstance(safe, dict):  # pragma: no cover - mapping above
        raise SourceReconciliationError("environment inventory must be an object")
    return {
        "run_id": run_id,
        "source_commit": source_commit,
        "inventory": safe,
        "sha256": _sha256_json(safe),
    }


def _reject_secret_values(value: object, field: str = "environment") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_secret_values(item, f"{field}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_values(item, f"{field}[]")
        return
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        raise SourceReconciliationError(
            f"{field} contains a credential-shaped value"
        )


def fresh_environment_inventory_record(
    inventory: CapabilityInventory | Mapping[str, object],
    *,
    run_id: str,
    source_commit: str,
) -> dict[str, object]:
    """Return a source-bound generic inventory with credential values rejected."""

    record = environment_inventory_record(
        inventory,
        run_id=run_id,
        source_commit=source_commit,
    )
    _reject_secret_values(record["inventory"])
    return record


def build_run_namespaces(
    run_paths: RunPaths,
    *,
    protocol_sha256: str,
) -> dict[str, object]:
    """Build all v2 mutable namespaces and prove pairwise separation."""

    if not isinstance(run_paths, RunPaths):
        raise TypeError("run_paths must be a RunPaths value")
    if not _SHA256.fullmatch(protocol_sha256):
        raise SourceReconciliationError("protocol_sha256 must be SHA-256")
    run_root = run_paths.run_root.as_posix()
    cache_prefix = (
        f"{BENCHMARK_ID}/protocol-v1/run/{run_paths.run_id}/"
        f"protocol/{protocol_sha256}/variant/A0/split/pilot/cache"
    )
    result = {
        "run_root": run_root,
        "state": run_paths.state.as_posix(),
        "results": run_paths.results.as_posix(),
        "receipts": run_paths.receipts.as_posix(),
        "worktree": (run_paths.worktrees / "source").as_posix(),
        "process": (run_paths.run_root / PROCESS_NAMESPACE_NAME).as_posix(),
        "cache": {
            "root": run_paths.cache.as_posix(),
            "cold": f"{cache_prefix}/cold",
            "warm": f"{cache_prefix}/warm",
        },
    }
    _validate_namespaces(result, run_paths.run_id)
    return result


def _validate_namespaces(value: object, run_id: str) -> None:
    namespaces = _mapping(value, "namespaces")
    _exact_keys(
        namespaces,
        {
            "run_root",
            "state",
            "results",
            "receipts",
            "worktree",
            "process",
            "cache",
        },
        "namespaces",
    )
    if not isinstance(run_id, str) or not _SAFE_ID.fullmatch(run_id):
        raise SourceReconciliationError("run_id is unsafe")
    cache = _mapping(namespaces["cache"], "namespaces.cache")
    _exact_keys(cache, {"root", "cold", "warm"}, "namespaces.cache")
    filesystem_names = (
        "run_root",
        "state",
        "results",
        "receipts",
        "worktree",
        "process",
    )
    filesystem_paths: dict[str, Path] = {}
    for name in filesystem_names:
        raw = namespaces[name]
        if not isinstance(raw, str) or run_id not in Path(raw).parts:
            raise SourceReconciliationError(
                f"namespace {name} is not scoped to run {run_id!r}"
            )
        filesystem_paths[name] = Path(raw)
    root = filesystem_paths["run_root"]
    for name, path in filesystem_paths.items():
        if name != "run_root" and not path.is_relative_to(root):
            raise SourceReconciliationError(
                f"namespace {name} escapes the run root"
            )
    nonroot = [filesystem_paths[name] for name in filesystem_names[1:]]
    if len(nonroot) != len(set(nonroot)):
        raise SourceReconciliationError("filesystem namespaces collide")
    for index, left in enumerate(nonroot):
        for right in nonroot[index + 1 :]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise SourceReconciliationError("filesystem namespaces overlap")
    cache_values = [cache[name] for name in ("root", "cold", "warm")]
    if any(not isinstance(item, str) or run_id not in item for item in cache_values):
        raise SourceReconciliationError("cache namespaces are not run-scoped")
    if len(cache_values) != len(set(cache_values)):
        raise SourceReconciliationError("cold and warm cache namespaces collide")
    if "a0-baseline-v1" in canonical_json(namespaces):
        raise SourceReconciliationError("v2 namespaces collide with the v1 run")


def _json_value(value: object, field: str) -> object:
    """Return a detached JSON value or reject an opaque runtime object."""

    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        value = serializer()
    try:
        # Canonical JSON is also the strictest inexpensive deep-copy boundary.
        return json.loads(canonical_json(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceReconciliationError(f"{field} is not canonical JSON") from exc


def normalize_a0_outputs(
    outputs: Iterable[object],
    *,
    expected_case_ids: Sequence[str],
) -> tuple[dict[str, object], ...]:
    """Normalize complete A0 pilot outputs while retaining semantic fields."""

    expected = tuple(expected_case_ids)
    if not expected or len(expected) != len(set(expected)):
        raise SourceReconciliationError("expected pilot case IDs are invalid")
    normalized: list[dict[str, object]] = []
    observed: list[str] = []
    for item in outputs:
        raw = item.to_dict() if callable(getattr(item, "to_dict", None)) else item
        payload = _mapping(raw, "A0 output")
        case_id = payload.get("case_id")
        if not isinstance(case_id, str):
            raise SourceReconciliationError("A0 output lacks a case_id")
        observed.append(case_id)
        stages = _array(payload.get("stages"), "A0 output.stages")
        normalized_stages: list[dict[str, object]] = []
        for index, stage_value in enumerate(stages):
            stage = _mapping(stage_value, f"A0 output.stages[{index}]")
            required_stage = {
                "stage",
                "status",
                "failure_code",
                "failure_detail",
                "kernel_accepted",
                "kernel_receipt_sha256",
                "output_sha256",
                "data",
                "provenance",
            }
            missing_stage = required_stage - set(stage)
            if missing_stage:
                raise SourceReconciliationError(
                    "A0 stage lacks behavior fields: "
                    f"{sorted(missing_stage)}"
                )
            normalized_stages.append(
                {
                    key: _json_value(stage[key], f"A0 stage.{key}")
                    for key in (
                        "stage",
                        "status",
                        "failure_code",
                        "failure_detail",
                        "kernel_accepted",
                        "kernel_receipt_sha256",
                        "output_sha256",
                        "data",
                        "provenance",
                    )
                }
            )
        required_result = {
            "split",
            "cache_mode",
            "variant_id",
            "status",
            "failure_code",
            "failure_detail",
            "kernel_accepted",
            "kernel_receipt_sha256",
            "verification_authority",
        }
        missing_result = required_result - set(payload)
        if missing_result:
            raise SourceReconciliationError(
                "A0 output lacks behavior fields: "
                f"{sorted(missing_result)}"
            )
        normalized.append(
            {
                "case_id": case_id,
                **{
                    key: _json_value(payload[key], f"A0 output.{key}")
                    for key in (
                        "split",
                        "cache_mode",
                        "variant_id",
                        "status",
                        "failure_code",
                        "failure_detail",
                        "kernel_accepted",
                        "kernel_receipt_sha256",
                        "verification_authority",
                    )
                },
                "stages": normalized_stages,
            }
        )
    # One or two complete cache passes are accepted.  Order and cardinality
    # stay part of the comparison; duplicates outside cold/warm parity fail.
    if tuple(observed) not in {expected, expected + expected}:
        raise SourceReconciliationError(
            "A0 outputs must contain one complete ordered pilot pass or "
            "ordered cold and warm passes"
        )
    return tuple(normalized)


def compare_a0_outputs(
    predecessor_outputs: Iterable[object],
    fresh_outputs: Iterable[object],
    *,
    expected_case_ids: Sequence[str],
) -> dict[str, object]:
    """Compare normalized old/fresh pilot behavior and reject any drift."""

    old = normalize_a0_outputs(
        predecessor_outputs, expected_case_ids=expected_case_ids
    )
    fresh = normalize_a0_outputs(
        fresh_outputs, expected_case_ids=expected_case_ids
    )
    old_digest = _sha256_json(old)
    fresh_digest = _sha256_json(fresh)
    if old != fresh or old_digest != fresh_digest:
        raise SourceReconciliationError(
            "unexplained normalized A0 pilot output drift"
        )
    return {
        "schema": OUTPUT_NORMALIZATION_SCHEMA,
        "coordinate_count": len(old),
        "case_ids": list(expected_case_ids),
        "predecessor_sha256": old_digest,
        "fresh_sha256": fresh_digest,
        "equivalent": True,
        "unexplained_drift": [],
    }


def _decode_json(text: str, context: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SourceReconciliationError(
                    f"{context} has duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except SourceReconciliationError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise SourceReconciliationError(
            f"{context} is not strict JSON: {exc}"
        ) from exc


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SourceReconciledBaselineManifest:
    """Deeply immutable, canonically serialized v2 reconciliation receipt."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        validate_reconciled_manifest_payload(self.payload)
        object.__setattr__(self, "payload", _freeze(self.payload))

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())

    @property
    def recursive_gitlinks(self) -> tuple[GitlinkIdentity, ...]:
        source = _mapping(self.payload["source"], "source")
        return tuple(
            GitlinkIdentity.from_dict(item)
            for item in _array(source["recursive_gitlinks"], "recursive_gitlinks")
        )

    def to_dict(self) -> dict[str, object]:
        result = _thaw(self.payload)
        if not isinstance(result, dict):  # pragma: no cover
            raise SourceReconciliationError("manifest is not an object")
        return result


def validate_fresh_source_baseline_payload(
    value: object,
    *,
    expected_run_id: str | None = None,
) -> None:
    """Validate a repaired within-run baseline without historical equivalence."""

    payload = _mapping(value, "fresh source baseline")
    _exact_keys(
        payload,
        {
            "schema",
            "benchmark_id",
            "baseline_id",
            "run_id",
            "evidence",
            "frozen",
            "predecessor",
            "source",
            "environment",
            "namespaces",
            "control",
            "behavior_comparison",
            "safety",
        },
        "fresh source baseline",
    )
    run_id = payload["run_id"]
    if not isinstance(run_id, str):
        raise SourceReconciliationError("fresh source run_id is invalid")
    try:
        ReassessmentRunLayout.for_run(run_id)
    except ValueError as exc:
        raise SourceReconciliationError("fresh source run_id is invalid") from exc
    if run_id == PUBLISHED_REASSESSMENT_RUN_ID:
        raise SourceReconciliationError(
            "published reassessment-v2 cannot use the fresh source schema"
        )
    if (
        payload["schema"] != FRESH_SOURCE_BASELINE_SCHEMA
        or payload["benchmark_id"] != BENCHMARK_ID
        or payload["baseline_id"] != FRESH_SOURCE_BASELINE_ID
        or payload["evidence"] != HSSLEV1158F41()
        or payload["frozen"] is not True
        or (expected_run_id is not None and run_id != expected_run_id)
    ):
        raise SourceReconciliationError("fresh source baseline identity drifted")

    predecessor = _mapping(payload["predecessor"], "predecessor")
    _exact_keys(
        predecessor,
        {
            "run_id",
            "manifest_path",
            "manifest_sha256",
            "manifest_bytes_sha256",
            "source_commit",
            "immutable",
            "artifacts",
            "artifacts_sha256",
        },
        "predecessor",
    )
    if (
        predecessor["run_id"] != PUBLISHED_REASSESSMENT_RUN_ID
        or predecessor["manifest_path"]
        != DEFAULT_RECONCILED_MANIFEST_PATH.as_posix()
        or predecessor["manifest_sha256"]
        != PUBLISHED_REASSESSMENT_BASELINE_SHA256
        or predecessor["manifest_bytes_sha256"]
        != PUBLISHED_REASSESSMENT_BASELINE_BYTES_SHA256
        or predecessor["immutable"] is not True
        or not isinstance(predecessor["source_commit"], str)
        or not _HEX_COMMIT.fullmatch(predecessor["source_commit"])
    ):
        raise SourceReconciliationError(
            "immutable published predecessor identity drifted"
        )
    artifacts = _array(predecessor["artifacts"], "predecessor.artifacts")
    expected_artifact_paths = tuple(
        path.as_posix() for path in DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS
    )
    normalized_artifacts: list[dict[str, object]] = []
    observed_artifact_paths: list[str] = []
    for value in artifacts:
        record = _mapping(value, "predecessor artifact")
        _exact_keys(record, {"path", "bytes_sha256"}, "predecessor artifact")
        path = _safe_relative_path(record["path"], "predecessor artifact.path")
        digest = record["bytes_sha256"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise SourceReconciliationError(
                "predecessor artifact digest is invalid"
            )
        observed_artifact_paths.append(path)
        normalized_artifacts.append({"path": path, "bytes_sha256": digest})
    if tuple(observed_artifact_paths) != expected_artifact_paths:
        raise SourceReconciliationError(
            "published predecessor artifact coverage drifted"
        )
    if predecessor["artifacts_sha256"] != _sha256_json(normalized_artifacts):
        raise SourceReconciliationError(
            "published predecessor artifact snapshot digest drifted"
        )
    manifest_artifact = next(
        (
            record
            for record in normalized_artifacts
            if record["path"] == predecessor["manifest_path"]
        ),
        None,
    )
    if (
        manifest_artifact is None
        or manifest_artifact["bytes_sha256"]
        != predecessor["manifest_bytes_sha256"]
    ):
        raise SourceReconciliationError(
            "published predecessor manifest snapshot is inconsistent"
        )

    source = _mapping(payload["source"], "source")
    _exact_keys(
        source,
        {
            "repository_commit",
            "worktree_commit",
            "detached",
            "active_checkout_unchanged",
            "worktree_receipt_sha256",
            "recursive_gitlinks",
            "recursive_gitlinks_sha256",
            "local_only_gitlinks",
        },
        "source",
    )
    for name in ("repository_commit", "worktree_commit"):
        if not isinstance(source[name], str) or not _HEX_COMMIT.fullmatch(
            source[name]
        ):
            raise SourceReconciliationError(f"source.{name} is invalid")
    if (
        source["repository_commit"] != source["worktree_commit"]
        or source["repository_commit"] == predecessor["source_commit"]
        or source["detached"] is not True
        or source["active_checkout_unchanged"] is not True
        or source["local_only_gitlinks"] is not True
        or not isinstance(source["worktree_receipt_sha256"], str)
        or not _SHA256.fullmatch(source["worktree_receipt_sha256"])
    ):
        raise SourceReconciliationError(
            "fresh detached source evidence is invalid"
        )
    gitlinks = tuple(
        GitlinkIdentity.from_dict(item)
        for item in _array(source["recursive_gitlinks"], "recursive_gitlinks")
    )
    if not gitlinks or tuple(item.path for item in gitlinks) != tuple(
        sorted(item.path for item in gitlinks)
    ):
        raise SourceReconciliationError(
            "recursive local-only gitlinks must be nonempty and sorted"
        )
    if len({item.path for item in gitlinks}) != len(gitlinks):
        raise SourceReconciliationError("recursive gitlink paths are duplicated")
    by_path = {item.path: item for item in gitlinks}
    for item in gitlinks:
        if item.parent_path == ".":
            if (
                item.parent_commit != source["repository_commit"]
                or item.depth != 1
            ):
                raise SourceReconciliationError(
                    "root gitlink is not bound to the repaired source commit"
                )
            continue
        parent = by_path.get(item.parent_path)
        if (
            parent is None
            or parent.commit != item.parent_commit
            or item.depth != parent.depth + 1
            or not Path(item.path).is_relative_to(Path(item.parent_path))
        ):
            raise SourceReconciliationError(
                "recursive gitlink parent chain is invalid"
            )
    if source["recursive_gitlinks_sha256"] != _sha256_json(
        [item.to_dict() for item in gitlinks]
    ):
        raise SourceReconciliationError("recursive gitlink digest is invalid")

    environment = _mapping(payload["environment"], "environment")
    _exact_keys(
        environment,
        {"run_id", "source_commit", "inventory", "sha256"},
        "environment",
    )
    if (
        environment["run_id"] != run_id
        or environment["source_commit"] != source["repository_commit"]
        or environment["sha256"] != _sha256_json(environment["inventory"])
    ):
        raise SourceReconciliationError(
            "generic capability inventory is not source-bound"
        )
    _redact_safe_inventory(environment["inventory"])
    _reject_secret_values(environment["inventory"])

    _validate_namespaces(payload["namespaces"], run_id)
    control = _mapping(payload["control"], "control")
    _exact_keys(
        control,
        {
            "variant_id",
            "definition",
            "historical_a0_equivalence_claimed",
            "reason",
        },
        "control",
    )
    if dict(control) != {
        "variant_id": "A0",
        "definition": "repaired_source_within_run_control",
        "historical_a0_equivalence_claimed": False,
        "reason": (
            "repaired_environment_and_code_define_a_new_within_run_A0_control"
        ),
    }:
        raise SourceReconciliationError(
            "fresh A0 control must not claim historical equivalence"
        )
    comparison = _mapping(
        payload["behavior_comparison"],
        "behavior_comparison",
    )
    _exact_keys(
        comparison,
        {
            "status",
            "authority",
            "scope",
            "source_commit",
        },
        "behavior_comparison",
    )
    if dict(comparison) != {
        "status": "deferred",
        "authority": "complete_source_bound_matrix",
        "scope": "all_frozen_non_holdout_coordinates",
        "source_commit": source["repository_commit"],
    }:
        raise SourceReconciliationError(
            "behavior comparison is not deferred to the complete matrix"
        )
    safety = _mapping(payload["safety"], "safety")
    _exact_keys(
        safety,
        {
            "shadow_only",
            "auto_merge",
            "production_routing_changes",
            "predecessor_artifacts_immutable",
            "exclusive_create",
            "external_run_root_only",
            "network_fetch",
        },
        "safety",
    )
    if dict(safety) != {
        "shadow_only": True,
        "auto_merge": False,
        "production_routing_changes": False,
        "predecessor_artifacts_immutable": True,
        "exclusive_create": True,
        "external_run_root_only": True,
        "network_fetch": False,
    }:
        raise SourceReconciliationError("fresh source safety boundary drifted")


@dataclass(frozen=True, slots=True)
class FreshSourceBaselineManifest:
    """Deeply immutable baseline for a repaired source-bound within-run A0."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        validate_fresh_source_baseline_payload(self.payload)
        object.__setattr__(self, "payload", _freeze(self.payload))

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())

    @property
    def recursive_gitlinks(self) -> tuple[GitlinkIdentity, ...]:
        source = _mapping(self.payload["source"], "source")
        return tuple(
            GitlinkIdentity.from_dict(item)
            for item in _array(source["recursive_gitlinks"], "recursive_gitlinks")
        )

    def to_dict(self) -> dict[str, object]:
        result = _thaw(self.payload)
        if not isinstance(result, dict):  # pragma: no cover
            raise SourceReconciliationError("fresh source manifest is not an object")
        return result


SourceBaselineManifest = (
    SourceReconciledBaselineManifest | FreshSourceBaselineManifest
)


def canonical_reconciled_baseline_json(
    manifest: SourceReconciledBaselineManifest,
) -> str:
    """Return the canonical JSON representation of a validated v2 receipt."""

    if not isinstance(manifest, SourceReconciledBaselineManifest):
        raise TypeError("manifest must be a SourceReconciledBaselineManifest")
    return canonical_json(manifest.to_dict())


def reconciled_baseline_sha256(
    manifest: SourceReconciledBaselineManifest,
) -> str:
    """Return the semantic SHA-256 identity of a validated v2 receipt."""

    return _sha256_bytes(
        canonical_reconciled_baseline_json(manifest).encode("utf-8")
    )


def _validate_digest_record(value: object, field: str) -> None:
    record = _mapping(value, field)
    if "sha256" not in record or not isinstance(record["sha256"], str):
        raise SourceReconciliationError(f"{field} lacks a digest")
    if not _SHA256.fullmatch(record["sha256"]):
        raise SourceReconciliationError(f"{field}.sha256 is invalid")


def validate_reconciled_manifest_payload(
    value: object,
    *,
    expected_run_id: str | None = None,
) -> None:
    """Validate all internal reconciliation invariants without mutation."""

    payload = _mapping(value, "reconciled baseline manifest")
    _exact_keys(
        payload,
        {
            "schema",
            "benchmark_id",
            "baseline_id",
            "run_id",
            "evidence",
            "frozen",
            "predecessor",
            "source",
            "environment",
            "protocol",
            "corpus",
            "configuration",
            "run_contracts",
            "namespaces",
            "reconciliation",
            "safety",
        },
        "reconciled baseline manifest",
    )
    if payload["schema"] != SOURCE_RECONCILIATION_SCHEMA:
        raise SourceReconciliationError("unsupported reconciliation schema")
    run_id = payload["run_id"]
    if not isinstance(run_id, str):
        raise SourceReconciliationError("reconciliation run_id is invalid")
    try:
        ReassessmentRunLayout.for_run(run_id)
    except ValueError as exc:
        raise SourceReconciliationError(
            "reconciliation run_id is invalid"
        ) from exc
    if (
        payload["benchmark_id"] != BENCHMARK_ID
        or payload["baseline_id"] != REASSESSMENT_BASELINE_ID
        or (
            expected_run_id is not None
            and run_id != expected_run_id
        )
    ):
        raise SourceReconciliationError("reassessment baseline identity drifted")
    if payload["evidence"] != HSSLEV1134D84() or payload["frozen"] is not True:
        raise SourceReconciliationError("source reconciliation is not frozen")

    predecessor = _mapping(payload["predecessor"], "predecessor")
    _exact_keys(
        predecessor,
        {
            "run_id",
            "manifest_path",
            "manifest_sha256",
            "manifest_bytes_sha256",
            "source_commit",
            "immutable",
        },
        "predecessor",
    )
    if (
        predecessor["run_id"] != "a0-baseline-v1"
        or predecessor["manifest_sha256"] != FROZEN_BASELINE_MANIFEST_SHA256
        or predecessor["immutable"] is not True
        or not isinstance(predecessor["source_commit"], str)
        or not _HEX_COMMIT.fullmatch(predecessor["source_commit"])
        or not isinstance(predecessor["manifest_bytes_sha256"], str)
        or not _SHA256.fullmatch(predecessor["manifest_bytes_sha256"])
    ):
        raise SourceReconciliationError("predecessor identity is invalid")

    source = _mapping(payload["source"], "source")
    _exact_keys(
        source,
        {
            "repository_commit",
            "worktree_commit",
            "detached",
            "active_checkout_unchanged",
            "worktree_receipt_sha256",
            "recursive_gitlinks",
            "recursive_gitlinks_sha256",
            "treatment_files",
        },
        "source",
    )
    for name in ("repository_commit", "worktree_commit"):
        if not isinstance(source[name], str) or not _HEX_COMMIT.fullmatch(
            source[name]
        ):
            raise SourceReconciliationError(f"source.{name} is invalid")
    if source["repository_commit"] != source["worktree_commit"]:
        raise SourceReconciliationError("fresh worktree commit is not source-bound")
    if source["repository_commit"] == predecessor["source_commit"]:
        raise SourceReconciliationError("fresh source did not advance from v1")
    if (
        source["detached"] is not True
        or source["active_checkout_unchanged"] is not True
        or not isinstance(source["worktree_receipt_sha256"], str)
        or not _SHA256.fullmatch(source["worktree_receipt_sha256"])
    ):
        raise SourceReconciliationError("detached worktree evidence is invalid")
    gitlinks = tuple(
        GitlinkIdentity.from_dict(item)
        for item in _array(source["recursive_gitlinks"], "recursive_gitlinks")
    )
    if not gitlinks or tuple(item.path for item in gitlinks) != tuple(
        sorted(item.path for item in gitlinks)
    ):
        raise SourceReconciliationError(
            "recursive gitlinks must be nonempty and sorted"
        )
    if len({item.path for item in gitlinks}) != len(gitlinks):
        raise SourceReconciliationError("recursive gitlink paths are duplicated")
    by_path = {item.path: item for item in gitlinks}
    for item in gitlinks:
        if item.parent_path == ".":
            if (
                item.parent_commit != source["repository_commit"]
                or item.depth != 1
            ):
                raise SourceReconciliationError(
                    "root gitlink is not bound to the fresh commit"
                )
            continue
        parent = by_path.get(item.parent_path)
        if (
            parent is None
            or parent.commit != item.parent_commit
            or item.depth != parent.depth + 1
            or not Path(item.path).is_relative_to(Path(item.parent_path))
        ):
            raise SourceReconciliationError(
                "recursive gitlink parent chain is invalid"
            )
    if source["recursive_gitlinks_sha256"] != _sha256_json(
        [item.to_dict() for item in gitlinks]
    ):
        raise SourceReconciliationError("recursive gitlink digest is invalid")

    treatment = _array(source["treatment_files"], "source.treatment_files")
    if len(treatment) != len(SOURCE_SNAPSHOT_FILES):
        raise SourceReconciliationError("A0 treatment file coverage is incomplete")
    treatment_paths: list[str] = []
    for item in treatment:
        record = _mapping(item, "treatment file")
        _exact_keys(
            record,
            {"path", "predecessor_sha256", "fresh_sha256", "equivalent"},
            "treatment file",
        )
        treatment_paths.append(_safe_relative_path(record["path"], "treatment.path"))
        if (
            record["equivalent"] is not True
            or record["predecessor_sha256"] != record["fresh_sha256"]
            or not isinstance(record["fresh_sha256"], str)
            or not _SHA256.fullmatch(record["fresh_sha256"])
        ):
            raise SourceReconciliationError("A0 treatment code drifted")
    if tuple(treatment_paths) != SOURCE_SNAPSHOT_FILES:
        raise SourceReconciliationError("A0 treatment paths drifted")

    environment = _mapping(payload["environment"], "environment")
    _exact_keys(
        environment,
        {"run_id", "source_commit", "inventory", "sha256"},
        "environment",
    )
    if (
        environment["run_id"] != run_id
        or environment["source_commit"] != source["repository_commit"]
        or environment["sha256"] != _sha256_json(environment["inventory"])
    ):
        raise SourceReconciliationError("environment is not bound to fresh source")
    _redact_safe_inventory(environment["inventory"])

    for name in ("protocol", "corpus", "configuration"):
        _validate_digest_record(payload[name], name)

    contracts = _array(payload["run_contracts"], "run_contracts")
    if len(contracts) != 2:
        raise SourceReconciliationError("v2 requires cold and warm run contracts")
    modes: list[str] = []
    contract_namespaces: list[str] = []
    for item in contracts:
        record = _mapping(item, "run contract")
        _exact_keys(
            record,
            {"run_id", "variant_id", "split", "cache_mode", "cache_namespace"},
            "run contract",
        )
        if (
            record["run_id"] != run_id
            or record["variant_id"] != "A0"
            or record["split"] != "pilot"
        ):
            raise SourceReconciliationError("reassessment run contract drifted")
        if not isinstance(record["cache_mode"], str):
            raise SourceReconciliationError("cache mode is invalid")
        if not isinstance(record["cache_namespace"], str):
            raise SourceReconciliationError("cache namespace is invalid")
        modes.append(record["cache_mode"])
        contract_namespaces.append(record["cache_namespace"])
    if modes != ["cold", "warm"] or len(set(contract_namespaces)) != 2:
        raise SourceReconciliationError("cold/warm contracts are not isolated")

    _validate_namespaces(payload["namespaces"], run_id)
    namespace_cache = _mapping(
        _mapping(payload["namespaces"], "namespaces")["cache"],
        "namespaces.cache",
    )
    if contract_namespaces != [namespace_cache["cold"], namespace_cache["warm"]]:
        raise SourceReconciliationError(
            "run-contract caches disagree with namespace receipt"
        )

    reconciliation = _mapping(payload["reconciliation"], "reconciliation")
    _exact_keys(
        reconciliation,
        {
            "schema",
            "coordinate_count",
            "case_ids",
            "predecessor_sha256",
            "fresh_sha256",
            "equivalent",
            "unexplained_drift",
            "explained_source_deltas",
        },
        "reconciliation",
    )
    case_ids = _array(reconciliation["case_ids"], "reconciliation.case_ids")
    if (
        reconciliation["schema"] != OUTPUT_NORMALIZATION_SCHEMA
        or reconciliation["coordinate_count"] not in {
            len(case_ids),
            len(case_ids) * 2,
        }
        or reconciliation["predecessor_sha256"]
        != reconciliation["fresh_sha256"]
        or reconciliation["predecessor_sha256"]
        != FROZEN_NORMALIZED_A0_PILOT_SHA256
        or not isinstance(reconciliation["fresh_sha256"], str)
        or not _SHA256.fullmatch(reconciliation["fresh_sha256"])
        or reconciliation["equivalent"] is not True
        or reconciliation["unexplained_drift"] != []
    ):
        raise SourceReconciliationError("normalized A0 equivalence is invalid")
    deltas = _array(
        reconciliation["explained_source_deltas"],
        "reconciliation.explained_source_deltas",
    )
    if not deltas or any(not isinstance(item, str) or not item for item in deltas):
        raise SourceReconciliationError("source advance is not explained")

    safety = _mapping(payload["safety"], "safety")
    _exact_keys(
        safety,
        {
            "shadow_only",
            "auto_merge",
            "production_routing_changes",
            "predecessor_artifacts_immutable",
            "exclusive_create",
        },
        "safety",
    )
    if dict(safety) != {
        "shadow_only": True,
        "auto_merge": False,
        "production_routing_changes": False,
        "predecessor_artifacts_immutable": True,
        "exclusive_create": True,
    }:
        raise SourceReconciliationError("v2 safety boundary drifted")


def load_reconciled_baseline_manifest(
    path: str | Path = DEFAULT_RECONCILED_MANIFEST_PATH,
    *,
    expected_run_id: str = REASSESSMENT_RUN_ID,
) -> SourceReconciledBaselineManifest:
    """Strictly load a canonical reconciliation manifest for one run.

    The published v2 identity remains the read-only default.  Callers loading
    evidence for a new run must name that run explicitly.
    """

    manifest_path = Path(path)
    try:
        ReassessmentRunLayout.for_run(expected_run_id)
    except ValueError as exc:
        raise SourceReconciliationError("expected run_id is invalid") from exc
    try:
        raw = manifest_path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceReconciliationError(
            f"cannot read reconciled baseline manifest: {exc}"
        ) from exc
    if not text or not text.endswith("\n"):
        raise SourceReconciliationError(
            "reconciled manifest must be nonempty and newline-terminated"
        )
    payload = _mapping(_decode_json(text, "reconciled manifest"), "manifest")
    manifest = SourceReconciledBaselineManifest(payload)
    if manifest.to_dict().get("run_id") != expected_run_id:
        raise SourceReconciliationError(
            f"reconciled manifest is not bound to run {expected_run_id!r}"
        )
    expected = (canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
    if raw != expected:
        raise SourceReconciliationError(
            "reconciled manifest is not canonical JSON"
        )
    _validate_checked_source_evidence(manifest)
    return manifest


def _validate_checked_source_evidence(
    manifest: SourceReconciledBaselineManifest,
) -> None:
    """Recompute checked-in Git and predecessor identities from source."""

    payload = manifest.to_dict()
    predecessor = _mapping(payload["predecessor"], "predecessor")
    source = _mapping(payload["source"], "source")
    predecessor_path = Path(str(predecessor["manifest_path"]))
    if not predecessor_path.is_absolute():
        predecessor_path = REPOSITORY_ROOT / predecessor_path
    try:
        predecessor_bytes = predecessor_path.read_bytes()
    except OSError as exc:
        raise SourceReconciliationError(
            f"cannot read immutable predecessor manifest: {exc}"
        ) from exc
    if _sha256_bytes(predecessor_bytes) != predecessor["manifest_bytes_sha256"]:
        raise SourceReconciliationError("immutable predecessor manifest drifted")
    frozen = load_baseline_manifest(predecessor_path)
    frozen_payload = frozen.to_dict()
    frozen_source = _mapping(frozen.payload["source"], "predecessor.source")
    if (
        frozen.digest != predecessor["manifest_sha256"]
        or frozen_source["repository_commit"] != predecessor["source_commit"]
    ):
        raise SourceReconciliationError("predecessor source identity drifted")

    protocol = _mapping(payload["protocol"], "protocol")
    corpus = _mapping(payload["corpus"], "corpus")
    configuration = _mapping(payload["configuration"], "configuration")
    frozen_protocol = _mapping(frozen_payload["protocol"], "predecessor.protocol")
    frozen_corpus = _mapping(frozen_payload["corpus"], "predecessor.corpus")
    frozen_configuration = _mapping(
        frozen_payload["configuration"], "predecessor.configuration"
    )
    reconciliation = _mapping(payload["reconciliation"], "reconciliation")
    if dict(protocol) != {
        "protocol_id": frozen_protocol["protocol_id"],
        "sha256": frozen_protocol["sha256"],
    }:
        raise SourceReconciliationError("v2 protocol drifted from v1")
    if dict(corpus) != {
        "corpus_id": frozen_corpus["corpus_id"],
        "sha256": frozen_corpus["manifest_sha256"],
    }:
        raise SourceReconciliationError("v2 corpus drifted from v1")
    if dict(configuration) != {
        "route": list(CURRENT_ROUTE),
        "sha256": frozen_configuration["configuration_sha256"],
    }:
        raise SourceReconciliationError("v2 A0 configuration drifted from v1")
    if tuple(_array(reconciliation["case_ids"], "reconciliation.case_ids")) != (
        frozen.pilot_case_ids
    ):
        raise SourceReconciliationError("v2 pilot case identities drifted from v1")

    commit = str(source["repository_commit"])
    actual_gitlinks = _capture_benchmark_bounded_gitlinks(
        REPOSITORY_ROOT,
        commit,
    )
    recorded_gitlinks = manifest.recursive_gitlinks
    if actual_gitlinks != recorded_gitlinks:
        raise SourceReconciliationError(
            "recorded recursive gitlinks drifted from the fresh commit trees"
        )
    treatment = _array(source["treatment_files"], "source.treatment_files")
    for item in treatment:
        record = _mapping(item, "treatment file")
        path = str(record["path"])
        if (
            _blob_sha256(REPOSITORY_ROOT, str(predecessor["source_commit"]), path)
            != record["predecessor_sha256"]
            or _blob_sha256(REPOSITORY_ROOT, commit, path)
            != record["fresh_sha256"]
        ):
            raise SourceReconciliationError(
                f"recorded A0 treatment identity drifted: {path}"
            )


def _fresh_predecessor_artifact_records(
    repository: Path,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for relative in DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS:
        candidate = (repository / relative).resolve()
        if not candidate.is_relative_to(repository):
            raise SourceReconciliationError(
                f"published predecessor artifact escapes repository: {relative}"
            )
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            raise SourceReconciliationError(
                f"cannot snapshot published predecessor artifact {relative}: {exc}"
            ) from exc
        records.append(
            {
                "path": relative.as_posix(),
                "bytes_sha256": _sha256_bytes(raw),
            }
        )
    return records


def _load_worktree_safety_receipt(path: Path) -> WorktreeSafetyReceipt:
    try:
        raw = _read_bytes_nofollow(path, "worktree safety receipt")
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceReconciliationError(
            f"cannot read worktree safety receipt: {exc}"
        ) from exc
    if not text or not text.endswith("\n"):
        raise SourceReconciliationError(
            "worktree safety receipt must be newline-terminated"
        )
    payload = _mapping(
        _decode_json(text, "worktree safety receipt"),
        "worktree safety receipt",
    )
    try:
        receipt = WorktreeSafetyReceipt.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise SourceReconciliationError(
            "worktree safety receipt is invalid"
        ) from exc
    expected = (canonical_worktree_safety_json(receipt) + "\n").encode("utf-8")
    if raw != expected:
        raise SourceReconciliationError(
            "worktree safety receipt is not canonical JSON"
        )
    return receipt


def _validate_checked_fresh_source_evidence(
    manifest: FreshSourceBaselineManifest,
    *,
    repository_root: str | Path,
    benchmark_root: str | Path,
) -> None:
    payload = manifest.to_dict()
    run_id = str(payload["run_id"])
    try:
        layout = require_fresh_reassessment_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    _validate_fresh_run_logical_paths(layout.run_paths)
    predecessor = _mapping(payload["predecessor"], "predecessor")
    source = _mapping(payload["source"], "source")
    commit = str(source["worktree_commit"])

    receipt_path = (
        layout.run_paths.receipts / WORKTREE_SAFETY_RECEIPT_NAME
    )
    receipt = _load_worktree_safety_receipt(receipt_path)
    expected_worktree = _logical_absolute_path(
        layout.run_paths.worktrees / "source",
        "expected detached worktree",
    )
    expected_state = _logical_absolute_path(
        layout.run_paths.run_root,
        "expected fresh run root",
    )
    requested_repository = _reject_symlink_components(
        repository_root,
        "repository_root",
    )
    if requested_repository != receipt.worktree_root:
        raise SourceReconciliationError(
            "repository_root must exactly name the receipt detached worktree_root"
        )
    if (
        receipt.run_id != run_id
        or receipt.worktree_commit != commit
        or receipt.base_commit != commit
        or receipt.worktree_root != expected_worktree
        or receipt.state_root != expected_state
        or receipt.sha256 != source["worktree_receipt_sha256"]
        or dict(receipt.submodule_commits)
        != {
            item.path: item.commit
            for item in manifest.recursive_gitlinks
            if item.depth == 1
        }
    ):
        raise SourceReconciliationError(
            "worktree receipt is not bound to the repaired source baseline"
        )

    repository = requested_repository
    if not repository.is_dir():
        raise SourceReconciliationError("repository_root must be a directory")
    top = Path(_git_value(repository, "rev-parse", "--show-toplevel")).resolve()
    if top != repository:
        raise SourceReconciliationError(
            "repository_root must name a Git worktree root"
        )
    _validate_live_detached_source(
        repository,
        commit=commit,
        gitlinks=manifest.recursive_gitlinks,
    )

    artifact_records = _fresh_predecessor_artifact_records(repository)
    if artifact_records != predecessor["artifacts"]:
        raise SourceReconciliationError(
            "immutable published predecessor artifact bytes drifted"
        )
    predecessor_path = (
        repository / str(predecessor["manifest_path"])
    )
    try:
        predecessor_raw = _read_bytes_nofollow(
            predecessor_path,
            "published predecessor manifest",
        )
        predecessor_payload = _mapping(
            _decode_json(
                predecessor_raw.decode("utf-8"),
                "published predecessor manifest",
            ),
            "published predecessor manifest",
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceReconciliationError(
            f"cannot read published predecessor manifest: {exc}"
        ) from exc
    predecessor_manifest = SourceReconciledBaselineManifest(
        predecessor_payload
    )
    if (
        predecessor_manifest.digest
        != PUBLISHED_REASSESSMENT_BASELINE_SHA256
        or _sha256_bytes(predecessor_raw)
        != PUBLISHED_REASSESSMENT_BASELINE_BYTES_SHA256
        or predecessor_manifest.to_dict()["run_id"]
        != PUBLISHED_REASSESSMENT_RUN_ID
    ):
        raise SourceReconciliationError(
            "published predecessor manifest identity drifted"
        )
    predecessor_source = _mapping(
        predecessor_manifest.to_dict()["source"],
        "published predecessor source",
    )
    if predecessor["source_commit"] != predecessor_source["worktree_commit"]:
        raise SourceReconciliationError(
            "published predecessor source commit drifted"
        )

    actual_gitlinks = _capture_benchmark_bounded_gitlinks(
        repository,
        commit,
    )
    if actual_gitlinks != manifest.recursive_gitlinks:
        raise SourceReconciliationError(
            "fresh recursive gitlinks drifted from the repaired source trees"
        )


def load_fresh_source_baseline_manifest(
    path: str | Path,
    *,
    expected_run_id: str,
    repository_root: str | Path = REPOSITORY_ROOT,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> FreshSourceBaselineManifest:
    """Load and independently revalidate one fresh external source baseline."""

    try:
        layout = require_fresh_reassessment_run(
            expected_run_id,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    _validate_fresh_run_logical_paths(
        layout.run_paths,
        manifest_path=path,
    )
    manifest_path = _logical_absolute_path(path, "fresh baseline manifest")
    expected_path = _logical_absolute_path(
        layout.baseline_manifest,
        "expected fresh baseline manifest",
    )
    if manifest_path != expected_path:
        raise SourceReconciliationError(
            "fresh source baseline must be loaded from its external run root"
        )
    try:
        raw = _read_bytes_nofollow(
            manifest_path,
            "fresh source baseline manifest",
        )
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceReconciliationError(
            f"cannot read fresh source baseline manifest: {exc}"
        ) from exc
    if not text or not text.endswith("\n"):
        raise SourceReconciliationError(
            "fresh source manifest must be nonempty and newline-terminated"
        )
    payload = _mapping(_decode_json(text, "fresh source manifest"), "manifest")
    validate_fresh_source_baseline_payload(
        payload,
        expected_run_id=expected_run_id,
    )
    manifest = FreshSourceBaselineManifest(payload)
    expected = (canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
    if raw != expected:
        raise SourceReconciliationError(
            "fresh source manifest is not canonical JSON"
        )
    _validate_checked_fresh_source_evidence(
        manifest,
        repository_root=repository_root,
        benchmark_root=benchmark_root,
    )
    return manifest


def load_source_baseline_manifest(
    path: str | Path = DEFAULT_RECONCILED_MANIFEST_PATH,
    *,
    expected_run_id: str = REASSESSMENT_RUN_ID,
    repository_root: str | Path = REPOSITORY_ROOT,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> SourceBaselineManifest:
    """Dispatch published compatibility and fresh repaired-source baselines."""

    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceReconciliationError(
            f"cannot read source baseline manifest: {exc}"
        ) from exc
    payload = _mapping(_decode_json(text, "source baseline manifest"), "manifest")
    schema = payload.get("schema")
    if schema == SOURCE_RECONCILIATION_SCHEMA:
        if expected_run_id != PUBLISHED_REASSESSMENT_RUN_ID:
            raise SourceReconciliationError(
                "fresh runs require the repaired-source baseline schema; "
                "historical A0 equivalence cannot authorize a new run"
            )
        return load_reconciled_baseline_manifest(
            path,
            expected_run_id=expected_run_id,
        )
    if schema == FRESH_SOURCE_BASELINE_SCHEMA:
        return load_fresh_source_baseline_manifest(
            path,
            expected_run_id=expected_run_id,
            repository_root=repository_root,
            benchmark_root=benchmark_root,
        )
    raise SourceReconciliationError("unsupported source baseline schema")


def write_reconciled_baseline_manifest(
    manifest: SourceReconciledBaselineManifest,
    path: str | Path = DEFAULT_RECONCILED_MANIFEST_PATH,
    *,
    run_id: str,
    repository_root: str | Path = REPOSITORY_ROOT,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> Path:
    """Write one fresh manifest without mutating published v2 evidence."""

    if not isinstance(manifest, SourceReconciledBaselineManifest):
        raise TypeError("manifest must be a SourceReconciledBaselineManifest")
    destination = Path(path)
    manifest_run_id = manifest.to_dict().get("run_id")
    if manifest_run_id != run_id:
        raise SourceReconciliationError(
            "manifest run_id does not match the requested write namespace"
        )
    try:
        reject_published_write_targets(
            repository_root=repository_root,
            run_id=run_id,
            targets=(destination,),
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(manifest.to_dict()))
            handle.write("\n")
    except FileExistsError as exc:
        raise SourceReconciliationError(
            f"refusing to overwrite reconciliation evidence: {destination}"
        ) from exc
    return destination


def write_fresh_source_baseline_manifest(
    manifest: FreshSourceBaselineManifest,
    path: str | Path,
    *,
    run_id: str,
    repository_root: str | Path = REPOSITORY_ROOT,
    benchmark_root: str | Path,
) -> Path:
    """Exclusively write a fresh baseline to its external run state path."""

    if not isinstance(manifest, FreshSourceBaselineManifest):
        raise TypeError("manifest must be a FreshSourceBaselineManifest")
    try:
        layout = require_fresh_reassessment_run(
            run_id,
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    _validate_fresh_run_logical_paths(
        layout.run_paths,
        manifest_path=path,
    )
    payload = manifest.to_dict()
    if payload["run_id"] != run_id:
        raise SourceReconciliationError(
            "fresh source manifest belongs to a different run"
        )
    repository = Path(repository_root).resolve()
    run_root = _logical_absolute_path(
        layout.run_paths.run_root,
        "fresh run root",
    )
    destination = _logical_absolute_path(path, "fresh baseline manifest")
    expected = _logical_absolute_path(
        layout.baseline_manifest,
        "expected fresh baseline manifest",
    )
    try:
        common = Path(
            _git_value(
                repository,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
        ).resolve()
    except (OSError, SourceReconciliationError) as exc:
        raise SourceReconciliationError(
            "cannot resolve repository Git state"
        ) from exc
    if (
        destination != expected
        or not destination.is_relative_to(run_root)
        or _paths_overlap(repository, run_root)
        or _paths_overlap(common, run_root)
    ):
        raise SourceReconciliationError(
            "fresh source baseline writes require the canonical external run root"
        )
    try:
        reject_published_write_targets(
            repository_root=repository,
            run_id=run_id,
            targets=(destination,),
            benchmark_root=benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    try:
        _write_bytes_exclusive_nofollow(
            destination,
            (canonical_json(payload) + "\n").encode("utf-8"),
        )
    except FileExistsError as exc:
        raise SourceReconciliationError(
            f"refusing to overwrite fresh source evidence: {destination}"
        ) from exc
    return destination


def _blob_sha256(repository: Path, commit: str, path: str) -> str:
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-C",
                str(repository),
                "show",
                f"{commit}:{path}",
            ],
            check=False,
            capture_output=True,
            timeout=30,
            env={
                "PATH": os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceReconciliationError(
            f"cannot read treatment file {path!r}: {type(exc).__name__}"
        ) from exc
    if completed.returncode:
        raise SourceReconciliationError(
            f"cannot read treatment file {path!r} at {commit}"
        )
    return _sha256_bytes(completed.stdout)


def _artifact_snapshot(paths: Iterable[Path]) -> dict[Path, str]:
    result: dict[Path, str] = {}
    for path in paths:
        try:
            result[path.resolve()] = _sha256_bytes(path.read_bytes())
        except OSError as exc:
            raise SourceReconciliationError(
                f"cannot snapshot predecessor artifact {path}: {exc}"
            ) from exc
    return result


def create_fresh_source_baseline(
    source_checkout: str | Path,
    *,
    base_revision: str,
    run_paths: RunPaths,
    capability_inventory: CapabilityInventory | Mapping[str, object],
) -> FreshSourceBaselineManifest:
    """Create the repaired source control without claiming historical parity.

    The active checkout and every immutable published predecessor artifact are
    observed before and after preparation.  Submodules are materialized from
    already-provisioned local repositories only; no fetch or remote URL is
    permitted.  The sole output is the canonical baseline path in a fresh,
    non-overlapping external run root.
    """

    _validate_fresh_run_logical_paths(
        run_paths,
        manifest_path=run_paths.state / "baseline-manifest.json",
    )
    source = Path(source_checkout).resolve()
    if not source.is_dir():
        raise SourceReconciliationError(
            "source_checkout must be an existing Git worktree root"
        )
    top = Path(_git_value(source, "rev-parse", "--show-toplevel")).resolve()
    if top != source:
        raise SourceReconciliationError(
            "source_checkout must name the Git worktree root"
        )
    _require_clean_source_checkout(source)
    try:
        layout = require_fresh_reassessment_run(
            run_paths.run_id,
            benchmark_root=run_paths.benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    if layout.run_paths != run_paths:
        raise SourceReconciliationError(
            "run_paths are not the canonical fresh reassessment layout"
        )
    common = Path(
        _git_value(
            source,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
    ).resolve()
    external_root = run_paths.run_root.resolve(strict=False)
    if _paths_overlap(source, external_root) or _paths_overlap(
        common,
        external_root,
    ):
        raise SourceReconciliationError(
            "fresh source baseline requires an external run root"
        )
    base_commit = _resolve_commit(source, base_revision)
    predecessor_paths = tuple(
        (source / path).resolve()
        for path in DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS
    )
    before_artifacts = _artifact_snapshot(predecessor_paths)
    source_before = _active_source_snapshot(source)
    predecessor_path = source / DEFAULT_RECONCILED_MANIFEST_PATH
    predecessor = load_reconciled_baseline_manifest(
        predecessor_path,
        expected_run_id=PUBLISHED_REASSESSMENT_RUN_ID,
    )
    if (
        predecessor.digest != PUBLISHED_REASSESSMENT_BASELINE_SHA256
        or _sha256_bytes(predecessor_path.read_bytes())
        != PUBLISHED_REASSESSMENT_BASELINE_BYTES_SHA256
    ):
        raise SourceReconciliationError(
            "immutable published predecessor manifest drifted"
        )
    expected_gitlinks = _capture_benchmark_bounded_gitlinks(
        source,
        base_commit,
    )
    receipt = prepare_isolated_worktree(
        source,
        run_paths=run_paths,
        base_revision=base_commit,
    )
    _materialize_recursive_local_gitlinks(
        source,
        receipt.worktree_root,
        tuple(item for item in expected_gitlinks if item.depth == 1),
    )
    actual_gitlinks = _capture_benchmark_bounded_gitlinks(
        receipt.worktree_root,
        receipt.worktree_commit,
    )
    if actual_gitlinks != expected_gitlinks:
        raise SourceReconciliationError(
            "materialized local-only gitlinks drifted from the repaired source"
        )
    predecessor_payload = predecessor.to_dict()
    predecessor_source = _mapping(
        predecessor_payload["source"],
        "published predecessor source",
    )
    predecessor_protocol = _mapping(
        predecessor_payload["protocol"],
        "published predecessor protocol",
    )
    artifact_records = _fresh_predecessor_artifact_records(source)
    namespaces = build_run_namespaces(
        run_paths,
        protocol_sha256=str(predecessor_protocol["sha256"]),
    )
    environment = fresh_environment_inventory_record(
        capability_inventory,
        run_id=run_paths.run_id,
        source_commit=receipt.worktree_commit,
    )
    gitlink_records = [item.to_dict() for item in actual_gitlinks]
    payload = {
        "schema": FRESH_SOURCE_BASELINE_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "baseline_id": FRESH_SOURCE_BASELINE_ID,
        "run_id": run_paths.run_id,
        "evidence": HSSLEV1158F41(),
        "frozen": True,
        "predecessor": {
            "run_id": PUBLISHED_REASSESSMENT_RUN_ID,
            "manifest_path": DEFAULT_RECONCILED_MANIFEST_PATH.as_posix(),
            "manifest_sha256": predecessor.digest,
            "manifest_bytes_sha256": _sha256_bytes(
                predecessor_path.read_bytes()
            ),
            "source_commit": predecessor_source["worktree_commit"],
            "immutable": True,
            "artifacts": artifact_records,
            "artifacts_sha256": _sha256_json(artifact_records),
        },
        "source": {
            "repository_commit": receipt.base_commit,
            "worktree_commit": receipt.worktree_commit,
            "detached": receipt.detached,
            "active_checkout_unchanged": receipt.source_unchanged,
            "worktree_receipt_sha256": receipt.sha256,
            "recursive_gitlinks": gitlink_records,
            "recursive_gitlinks_sha256": _sha256_json(gitlink_records),
            "local_only_gitlinks": True,
        },
        "environment": environment,
        "namespaces": namespaces,
        "control": {
            "variant_id": "A0",
            "definition": "repaired_source_within_run_control",
            "historical_a0_equivalence_claimed": False,
            "reason": (
                "repaired_environment_and_code_define_a_new_within_run_A0_control"
            ),
        },
        "behavior_comparison": {
            "status": "deferred",
            "authority": "complete_source_bound_matrix",
            "scope": "all_frozen_non_holdout_coordinates",
            "source_commit": receipt.worktree_commit,
        },
        "safety": {
            "shadow_only": True,
            "auto_merge": False,
            "production_routing_changes": False,
            "predecessor_artifacts_immutable": True,
            "exclusive_create": True,
            "external_run_root_only": True,
            "network_fetch": False,
        },
    }
    manifest = FreshSourceBaselineManifest(payload)
    if _active_source_snapshot(source) != source_before:
        raise SourceReconciliationError(
            "active source checkout changed during fresh source preparation"
        )
    if _artifact_snapshot(predecessor_paths) != before_artifacts:
        raise SourceReconciliationError(
            "a published predecessor artifact changed during preparation"
        )
    write_fresh_source_baseline_manifest(
        manifest,
        layout.baseline_manifest,
        run_id=run_paths.run_id,
        repository_root=source,
        benchmark_root=run_paths.benchmark_root,
    )
    if _artifact_snapshot(predecessor_paths) != before_artifacts:
        raise SourceReconciliationError(
            "a published predecessor artifact changed during baseline write"
        )
    return manifest


def reconcile_source(
    source_checkout: str | Path,
    *,
    base_revision: str,
    run_paths: RunPaths,
    environment_inventory: CapabilityInventory | Mapping[str, object],
    predecessor_outputs: Iterable[object],
    fresh_outputs: Iterable[object],
    predecessor_manifest_path: str | Path = DEFAULT_BASELINE_MANIFEST_PATH,
    predecessor_artifacts: Iterable[str | Path] | None = None,
    output_path: str | Path | None = None,
) -> SourceReconciledBaselineManifest:
    """Create a detached, behavior-equivalent fresh baseline receipt.

    Submodule initialization is local-only (``--no-fetch``).  Missing objects
    fail rather than opening the network or accepting a partial recursive
    inventory.
    """

    source = Path(source_checkout).resolve()
    try:
        require_fresh_reassessment_run(
            run_paths.run_id,
            benchmark_root=run_paths.benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    predecessor_path = Path(predecessor_manifest_path)
    if not predecessor_path.is_absolute():
        predecessor_path = source / predecessor_path
    immutable_artifact_values = (
        DEFAULT_IMMUTABLE_V1_ARTIFACT_PATHS
        if predecessor_artifacts is None
        else tuple(Path(item) for item in predecessor_artifacts)
    )
    immutable_artifacts = tuple(
        path if path.is_absolute() else source / path
        for path in immutable_artifact_values
    )
    frozen_paths = (
        predecessor_path,
        *(
            path
            for path in immutable_artifacts
            if path.resolve() != predecessor_path.resolve()
        ),
    )
    before = _artifact_snapshot(frozen_paths)
    source_before = _active_source_snapshot(source)
    predecessor = load_baseline_manifest(predecessor_path)
    predecessor_payload = predecessor.to_dict()
    predecessor_source = _mapping(predecessor_payload["source"], "source")
    old_commit = str(predecessor_source["repository_commit"])
    receipt = prepare_isolated_worktree(
        source,
        run_paths=run_paths,
        base_revision=base_revision,
    )
    # Never fetch here: the operator must provision exact objects before the
    # reconciliation boundary, making source preparation reproducible/offline.
    _git(
        receipt.worktree_root,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "update",
        "--init",
        "--recursive",
        "--checkout",
        "--no-fetch",
        timeout=120,
    )
    gitlinks = capture_recursive_gitlinks(
        receipt.worktree_root,
        receipt.worktree_commit,
        require_complete=True,
    )
    expected_case_ids = predecessor.pilot_case_ids
    comparison = compare_a0_outputs(
        predecessor_outputs,
        fresh_outputs,
        expected_case_ids=expected_case_ids,
    )
    comparison["explained_source_deltas"] = [
        f"repository commit advanced from {old_commit} "
        f"to {receipt.worktree_commit}",
        "recursive submodule gitlinks rebound to the fresh source tree",
    ]
    treatment_files: list[dict[str, object]] = []
    for path in SOURCE_SNAPSHOT_FILES:
        old_sha = _blob_sha256(source, old_commit, path)
        fresh_sha = _blob_sha256(source, receipt.worktree_commit, path)
        if old_sha != fresh_sha:
            raise SourceReconciliationError(
                f"unexplained A0 treatment code drift: {path}"
            )
        treatment_files.append(
            {
                "path": path,
                "predecessor_sha256": old_sha,
                "fresh_sha256": fresh_sha,
                "equivalent": True,
            }
        )
    protocol = _mapping(predecessor_payload["protocol"], "protocol")
    corpus = _mapping(predecessor_payload["corpus"], "corpus")
    configuration = _mapping(
        predecessor_payload["configuration"], "configuration"
    )
    namespaces = build_run_namespaces(
        run_paths, protocol_sha256=str(protocol["sha256"])
    )
    cache = _mapping(namespaces["cache"], "namespaces.cache")
    environment = environment_inventory_record(
        environment_inventory,
        run_id=run_paths.run_id,
        source_commit=receipt.worktree_commit,
    )
    payload = {
        "schema": SOURCE_RECONCILIATION_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "baseline_id": REASSESSMENT_BASELINE_ID,
        "run_id": run_paths.run_id,
        "evidence": HSSLEV1134D84(),
        "frozen": True,
        "predecessor": {
            "run_id": "a0-baseline-v1",
            "manifest_path": predecessor_path.as_posix(),
            "manifest_sha256": predecessor.digest,
            "manifest_bytes_sha256": _sha256_bytes(predecessor_path.read_bytes()),
            "source_commit": old_commit,
            "immutable": True,
        },
        "source": {
            "repository_commit": receipt.base_commit,
            "worktree_commit": receipt.worktree_commit,
            "detached": receipt.detached,
            "active_checkout_unchanged": receipt.source_unchanged,
            "worktree_receipt_sha256": receipt.sha256,
            "recursive_gitlinks": [item.to_dict() for item in gitlinks],
            "recursive_gitlinks_sha256": _sha256_json(
                [item.to_dict() for item in gitlinks]
            ),
            "treatment_files": treatment_files,
        },
        "environment": environment,
        "protocol": {
            "protocol_id": protocol["protocol_id"],
            "sha256": protocol["sha256"],
        },
        "corpus": {
            "corpus_id": corpus["corpus_id"],
            "sha256": corpus["manifest_sha256"],
        },
        "configuration": {
            "route": list(CURRENT_ROUTE),
            "sha256": configuration["configuration_sha256"],
        },
        "run_contracts": [
            {
                "run_id": run_paths.run_id,
                "variant_id": "A0",
                "split": "pilot",
                "cache_mode": mode,
                "cache_namespace": cache[mode],
            }
            for mode in ("cold", "warm")
        ],
        "namespaces": namespaces,
        "reconciliation": comparison,
        "safety": {
            "shadow_only": True,
            "auto_merge": False,
            "production_routing_changes": False,
            "predecessor_artifacts_immutable": True,
            "exclusive_create": True,
        },
    }
    manifest = SourceReconciledBaselineManifest(payload)
    if _active_source_snapshot(source) != source_before:
        raise SourceReconciliationError(
            "active source checkout changed during reconciliation"
        )
    if _artifact_snapshot(frozen_paths) != before:
        raise SourceReconciliationError(
            "a predecessor v1 artifact changed during reconciliation"
        )
    (run_paths.run_root / PROCESS_NAMESPACE_NAME).mkdir(
        mode=0o700, parents=True, exist_ok=True
    )
    destination = (
        run_paths.state / "baseline-manifest.json"
        if output_path is None
        else Path(output_path)
    )
    if not destination.is_absolute():
        destination = source / destination
    try:
        reject_published_write_targets(
            repository_root=source,
            run_id=run_paths.run_id,
            targets=(destination,),
            benchmark_root=run_paths.benchmark_root,
        )
    except ReassessmentNamespaceError as exc:
        raise SourceReconciliationError(str(exc)) from exc
    write_reconciled_baseline_manifest(
        manifest,
        destination,
        run_id=run_paths.run_id,
        repository_root=source,
        benchmark_root=run_paths.benchmark_root,
    )
    after = _artifact_snapshot(frozen_paths)
    if after != before:
        raise SourceReconciliationError(
            "a predecessor v1 artifact changed during reconciliation"
        )
    return manifest


__all__ = [
    "DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS",
    "DEFAULT_RECONCILED_MANIFEST_PATH",
    "DEFAULT_IMMUTABLE_V1_ARTIFACT_PATHS",
    "FRESH_SOURCE_BASELINE_ID",
    "FRESH_SOURCE_BASELINE_SCHEMA",
    "FROZEN_NORMALIZED_A0_PILOT_SHA256",
    "FreshSourceBaselineManifest",
    "GitlinkIdentity",
    "HSSLEV1134D84",
    "HSSLEV1158F41",
    "OUTPUT_NORMALIZATION_SCHEMA",
    "PUBLISHED_REASSESSMENT_BASELINE_BYTES_SHA256",
    "PUBLISHED_REASSESSMENT_BASELINE_SHA256",
    "REASSESSMENT_BASELINE_ID",
    "REASSESSMENT_RUN_ID",
    "SOURCE_RECONCILIATION_SCHEMA",
    "SourceBaselineManifest",
    "SourceReconciledBaselineManifest",
    "SourceReconciliationError",
    "build_run_namespaces",
    "canonical_reconciled_baseline_json",
    "capture_recursive_gitlinks",
    "compare_a0_outputs",
    "create_fresh_source_baseline",
    "environment_inventory_record",
    "fresh_environment_inventory_record",
    "load_fresh_source_baseline_manifest",
    "load_reconciled_baseline_manifest",
    "load_source_baseline_manifest",
    "normalize_a0_outputs",
    "reconciled_baseline_sha256",
    "reconcile_source",
    "validate_fresh_source_baseline_payload",
    "validate_reconciled_manifest_payload",
    "write_fresh_source_baseline_manifest",
    "write_reconciled_baseline_manifest",
]
