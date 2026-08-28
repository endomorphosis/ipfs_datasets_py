"""Audit protected Hugging Face mutation paths without touching the Hub.

The audit is deliberately callsite based. Importing a guard is not authority,
constructing ``HfApi`` is not a write, and a protected-repository literal in an
unrelated function does not taint the rest of a module. For each actual Hub
write, the analyser follows simple aliases, repository-value aliases, local
function calls, and nested callbacks.

Canonical-callback ancestry is context, not authority.  The only accepted
canonical path is the exact two-stage State Laws preflight and prepared
executor.  Within that prepared executor, a same-target/same-method,
payload-bound ``require_unprotected_or_runtime`` call must dominate the exact
fixed transport primitive, including its token and mutation arguments, and
the individual call must be enclosed by the real one-shot ``guarded_write``
helper with the identical binding.  Legacy fail-closed paths remain
inventoryable through a dominating guard.  A caller-provided
``runtime_authorized`` value is never accepted.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    CANONICAL_RUNTIME,
    PROTECTED_REPOS,
    PROTECTED_WRITE_METHODS,
)

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_legal_corpora_hugging_face_mutation_paths.py"
SCHEMA = "ipfs_datasets_py/legal-corpora-hugging-face-mutation-path-audit@2"
REPORT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/hugging_face_mutation_path_audit.json"
)
SCHEMA_RELPATH = Path(
    "data/legal/legal_corpora_hugging_face_mutation_path_audit.schema.json"
)
_EXPLICIT_SCAN_SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    "workspace",
    "external",
}
_PATH_DIGEST_ALGORITHM = "sha256-canonical-json-string-array-v1"
_TRACKED_PYTHON_EXCLUSION_POLICY = (
    {
        "category": "archive",
        "path_components": ("archive", "archives"),
        "reason": "retired archive trees are not runtime code",
    },
    {
        "category": "vendor",
        "path_components": (
            "external",
            "third-party",
            "third_party",
            "vendor",
            "vendors",
        ),
        "reason": "vendored or externally maintained trees are not repository runtime code",
    },
    {
        "category": "generated",
        "path_components": ("build", "dist", "generated"),
        "reason": "generated build outputs are not maintained runtime sources",
    },
    {
        "category": "tests",
        "path_components": ("test", "testing", "tests"),
        "reason": "test-only trees are not production runtime code",
    },
)
_REPOSITORY_KEYWORDS = (
    "repo_id",
    "repository_id",
    "dataset_id",
    "target_repo_id",
    "from_id",
    "to_id",
)
_REPOSITORY_BEARING_NAMES = frozenset(
    {
        *_REPOSITORY_KEYWORDS,
        "dataset_repo_id",
        "hf_dataset_id",
    }
)
_CANONICAL_FUNCTION = "authorize_and_mutate_canonical"
_LEGACY_GUARD_FUNCTION = "require_unprotected_or_runtime"
_GUARDED_WRITE_FUNCTION = "guarded_write"
_PROTECTED_PROBE_FUNCTION = "is_protected_repo"
_PUBLISHER_RELPATH = "ipfs_datasets_py/huggingface/publisher.py"
_RUNTIME_RELPATH = (
    "ipfs_datasets_py/processors/legal_data/"
    "legal_corpora_publication_runtime.py"
)
_GUARD_RELPATH = "ipfs_datasets_py/huggingface/protected_repo_guard.py"
_PREFLIGHT_CLASS = "_StateLawsCanonicalCommitPreflight"
_PREPARED_EXECUTOR_CLASS = "_PreparedStateLawsCanonicalCommitExecutor"
_PREPARED_CALL_FACTORY = "_build_state_laws_prepared_commit_call"
_PREPARED_CALL_FACTORY_BINDINGS = {
    "require_guard": "require_unprotected_or_runtime",
    "rehash_files": "_rehash_prepared_snapshot_files",
    "protected_write": "guarded_write",
    "create_commit": "_canonical_hf_api_create_commit",
}
_EXACT_BINDING_KEYWORDS = (
    "expected_phase",
    "expected_operation",
    "expected_manifest_digest",
    "expected_payload_digest",
)
_API_METHOD_RESOLVERS = {"_require_api_method", "_require_method"}
_ATTESTED_API_WRITE_FUNCTIONS = {
    "_canonical_hf_api_create_commit": "create_commit",
}
_PREPARED_WRITE_KEYWORDS = {
    "repo_id": "self.mutation_binding.repository_id",
    "repo_type": "self.mutation_binding.repository_type",
    "operations": "self.operations_payload",
    "commit_message": "self.canonical_message",
    "revision": "self.mutation_binding.revision",
    "parent_commit": "self.mutation_binding.parent_commit",
}
_GUARD_CLOSURE_PRIVATE_NAMES = frozenset(
    {
        "active_authority",
        "anchor_lock",
        "authority_seal",
        "runtime_anchor",
        "_require_runtime_anchor",
    }
)
_GUARD_RUNTIME_PRIVATE_NAMES = frozenset(
    {
        "_assert_canonical_runtime_authorization_consumed",
        "_canonical_runtime_authorization",
        "_register_canonical_runtime_trust_anchor",
    }
)
_GUARD_MODULE_PRIVATE_NAMES = frozenset(
    {
        "_attest_canonical_prepared_write_edge",
    }
)
_GUARD_PUBLISHER_PRIVATE_NAMES = frozenset(
    {
        "_register_canonical_publisher_trust_anchor",
    }
)
_READ_ONLY_METHODS = {
    "repo_info",
    "list_repo_files",
    "list_models",
    "list_datasets",
    "get_paths_info",
    "whoami",
}


class MutationPathAuditError(RuntimeError):
    pass


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise MutationPathAuditError(
                f"mutation-path audit JSON contains duplicate key {key!r}"
            )
        payload[key] = value
    return payload


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Load one strict UTF-8 JSON object and reject duplicate keys."""

    try:
        serialized = path.read_bytes()
    except OSError as exc:
        raise MutationPathAuditError(f"{label} is unreadable: {path}") from exc
    try:
        payload = json.loads(
            serialized.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except MutationPathAuditError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MutationPathAuditError(
            f"{label} is not strict UTF-8 JSON: {path}"
        ) from exc
    if type(payload) is not dict:
        raise MutationPathAuditError(f"{label} root must be a JSON object: {path}")
    return payload


def _schema_validate(
    payload: Mapping[str, Any],
    *,
    repository_root: Path = REPOSITORY_ROOT,
    label: str,
) -> None:
    """Validate an audit payload against the committed Draft 2020-12 schema."""

    schema = _load_json_object(
        repository_root / SCHEMA_RELPATH,
        label="mutation-path audit schema",
    )
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
    except ImportError as exc:
        raise MutationPathAuditError(
            "jsonschema is required for mutation-path audit verification"
        ) from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise MutationPathAuditError(
            "mutation-path audit schema is not valid Draft 2020-12"
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(payload)),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise MutationPathAuditError(
            f"{label} fails schema at {location}: {first.message}"
        )


def _canonical_report_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"


def _write_canonical_report(
    payload: Mapping[str, Any],
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> None:
    target = repository_root / REPORT_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(_canonical_report_text(payload), encoding="utf-8")
    except OSError as exc:
        raise MutationPathAuditError(
            f"frozen mutation-path audit report could not be written: {target}"
        ) from exc


def _check_frozen_report(
    measured: Mapping[str, Any],
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> None:
    """Require the tracked receipt to equal the current inventory exactly."""

    target = repository_root / REPORT_RELPATH
    frozen = _load_json_object(target, label="frozen mutation-path audit report")
    _schema_validate(
        frozen,
        repository_root=repository_root,
        label="frozen mutation-path audit report",
    )
    if _canonical_report_text(frozen) != _canonical_report_text(measured):
        raise MutationPathAuditError(
            "frozen mutation-path audit report does not exactly match the "
            "current source inventory; rerun with --check --write"
        )


def _iter_python_files(root: Path, *, repository_root: Path) -> list[Path]:
    """Enumerate a caller-selected tree for focused tests and diagnostics."""

    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*.py"):
        try:
            rel_parts = path.relative_to(repository_root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in _EXPLICIT_SCAN_SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        files.append(path)
    return sorted(files)


@dataclass(frozen=True)
class _CapturedPythonSource:
    path: str
    payload: bytes
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class _PythonSourceCapture:
    sources: tuple[_CapturedPythonSource, ...]
    source_scope: dict[str, Any]


@dataclass(frozen=True)
class MutationAuditCapture:
    """One report/projection pair derived from one immutable source capture."""

    report: dict[str, Any]
    source_projection: tuple[dict[str, Any], ...]


def _canonical_path_digest(paths: Iterable[str]) -> str:
    """Hash a sorted repository-relative path array using canonical JSON."""

    canonical = json.dumps(
        sorted(str(path) for path in paths),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _run_git(
    repository_root: Path,
    *arguments: str,
    label: str,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise MutationPathAuditError(
            f"could not invoke Git while {label}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise MutationPathAuditError(f"Git failed while {label}{suffix}")
    return completed.stdout


def _open_capture_root(repository_root: Path) -> int:
    """Open the repository root once without following its final component."""

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        raise MutationPathAuditError(
            "componentwise no-follow source capture is unavailable"
        )
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(repository_root, flags)
    except OSError as exc:
        raise MutationPathAuditError(
            f"mutation inventory repository root is unreadable: {repository_root}"
        ) from exc
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise MutationPathAuditError(
                f"mutation inventory repository root is not a directory: {repository_root}"
            )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _validated_source_parts(relpath: str) -> tuple[str, ...]:
    pure_path = PurePosixPath(relpath)
    if (
        pure_path.is_absolute()
        or not pure_path.parts
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise MutationPathAuditError(
            f"Git reported an unsafe tracked Python path: {relpath!r}"
        )
    return pure_path.parts


def _read_componentwise_regular_source(
    root_descriptor: int,
    relpath: str,
) -> bytes:
    """Read one regular source through no-follow ``openat`` components."""

    parts = _validated_source_parts(relpath)
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        parent_descriptor = os.dup(root_descriptor)
    except OSError as exc:
        raise MutationPathAuditError(
            f"mutation inventory source parent is unreadable: {relpath}"
        ) from exc
    source_descriptor: int | None = None
    try:
        for component in parts[:-1]:
            try:
                component_stat = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise MutationPathAuditError(
                    f"tracked Python parent is missing or unreadable: {relpath}"
                ) from exc
            if stat.S_ISLNK(component_stat.st_mode):
                raise MutationPathAuditError(
                    f"tracked Python parent must not be a symlink: {relpath}"
                )
            if not stat.S_ISDIR(component_stat.st_mode):
                raise MutationPathAuditError(
                    f"tracked Python parent is not a directory: {relpath}"
                )
            try:
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=parent_descriptor,
                )
            except OSError as exc:
                raise MutationPathAuditError(
                    "tracked Python parent changed, is unreadable, or is a "
                    f"symlink: {relpath}"
                ) from exc
            os.close(parent_descriptor)
            parent_descriptor = next_descriptor

        leaf = parts[-1]
        try:
            source_stat = os.stat(
                leaf,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise MutationPathAuditError(
                f"tracked Python source is missing or unreadable: {relpath}"
            ) from exc
        if stat.S_ISLNK(source_stat.st_mode):
            raise MutationPathAuditError(
                f"tracked Python source must not be a symlink: {relpath}"
            )
        if not stat.S_ISREG(source_stat.st_mode):
            raise MutationPathAuditError(
                f"tracked Python source is not a regular file: {relpath}"
            )
        try:
            source_descriptor = os.open(
                leaf,
                file_flags,
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            raise MutationPathAuditError(
                f"tracked Python source changed or is unreadable: {relpath}"
            ) from exc
        opened_stat = os.fstat(source_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise MutationPathAuditError(
                f"tracked Python source is not a regular file: {relpath}"
            )
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(source_descriptor, 1024 * 1024)
            except OSError as exc:
                raise MutationPathAuditError(
                    f"tracked Python source is unreadable: {relpath}"
                ) from exc
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
        os.close(parent_descriptor)


def _captured_source(relpath: str, payload: bytes) -> _CapturedPythonSource:
    return _CapturedPythonSource(
        path=relpath,
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def _capture_sources(
    repository_root: Path,
    relpaths: Iterable[str],
) -> tuple[_CapturedPythonSource, ...]:
    """Capture each repository-relative path once from one root descriptor."""

    root_descriptor = _open_capture_root(repository_root)
    captured: list[_CapturedPythonSource] = []
    seen: set[str] = set()
    try:
        for relpath in relpaths:
            if relpath in seen:
                raise MutationPathAuditError(
                    f"duplicate mutation inventory source path: {relpath}"
                )
            seen.add(relpath)
            captured.append(
                _captured_source(
                    relpath,
                    _read_componentwise_regular_source(
                        root_descriptor,
                        relpath,
                    ),
                )
            )
    finally:
        os.close(root_descriptor)
    return tuple(captured)


def _tracked_exclusion_category(relpath: str) -> str | None:
    directory_components = set(PurePosixPath(relpath).parts[:-1])
    for rule in _TRACKED_PYTHON_EXCLUSION_POLICY:
        if directory_components.intersection(rule["path_components"]):
            return str(rule["category"])
    return None


def _git_tracked_python_capture(repository_root: Path) -> _PythonSourceCapture:
    reported_root = _run_git(
        repository_root,
        "rev-parse",
        "--show-toplevel",
        label="resolving the repository root",
    )
    try:
        git_root = Path(reported_root.decode("utf-8", errors="strict").strip()).resolve()
    except (UnicodeError, OSError) as exc:
        raise MutationPathAuditError("Git reported an invalid repository root") from exc
    if git_root != repository_root:
        raise MutationPathAuditError(
            "repository_root must be the Git worktree root for a tracked-source audit"
        )

    serialized_paths = _run_git(
        repository_root,
        "ls-files",
        "--cached",
        "-z",
        "--",
        "*.py",
        label="enumerating tracked Python sources",
    )
    try:
        tracked_paths = [
            item.decode("utf-8", errors="strict")
            for item in serialized_paths.split(b"\0")
            if item
        ]
    except UnicodeError as exc:
        raise MutationPathAuditError(
            "Git reported a tracked Python path that is not valid UTF-8"
        ) from exc
    if len(tracked_paths) != len(set(tracked_paths)):
        raise MutationPathAuditError("Git reported duplicate tracked Python paths")
    tracked_paths.sort()

    excluded_by_category: dict[str, list[str]] = {
        str(rule["category"]): [] for rule in _TRACKED_PYTHON_EXCLUSION_POLICY
    }
    scanned: list[_CapturedPythonSource] = []
    root_descriptor = _open_capture_root(repository_root)
    try:
        for relpath in tracked_paths:
            payload = _read_componentwise_regular_source(
                root_descriptor,
                relpath,
            )
            category = _tracked_exclusion_category(relpath)
            if category is None:
                scanned.append(_captured_source(relpath, payload))
            else:
                excluded_by_category[category].append(relpath)
    finally:
        os.close(root_descriptor)

    scanned_paths = [source.path for source in scanned]
    excluded_paths = sorted(
        relpath
        for paths in excluded_by_category.values()
        for relpath in paths
    )
    policy_report = []
    for rule in _TRACKED_PYTHON_EXCLUSION_POLICY:
        category = str(rule["category"])
        category_paths = excluded_by_category[category]
        policy_report.append(
            {
                "category": category,
                "path_components": sorted(str(item) for item in rule["path_components"]),
                "reason": str(rule["reason"]),
                "excluded_python_count": len(category_paths),
                "excluded_python_paths_sha256": _canonical_path_digest(category_paths),
            }
        )
    return _PythonSourceCapture(
        sources=tuple(scanned),
        source_scope={
            "mode": "git_tracked_production_python",
            "path_digest_algorithm": _PATH_DIGEST_ALGORITHM,
            "scan_roots": [],
            "tracked_python_count": len(tracked_paths),
            "tracked_python_paths_sha256": _canonical_path_digest(tracked_paths),
            "scanned_python_count": len(scanned_paths),
            "scanned_python_paths_sha256": _canonical_path_digest(scanned_paths),
            "excluded_python_count": len(excluded_paths),
            "excluded_python_paths_sha256": _canonical_path_digest(excluded_paths),
            "exclusion_policy": policy_report,
        },
    )


def _explicit_python_capture(
    repository_root: Path,
    scan_roots: Sequence[Path | str],
) -> _PythonSourceCapture:
    paths: set[str] = set()
    normalized_roots: set[str] = set()
    for scan_root in scan_roots:
        candidate = Path(scan_root)
        if not candidate.is_absolute():
            candidate = repository_root / candidate
        try:
            resolved_candidate = candidate.resolve()
            root_relpath = resolved_candidate.relative_to(repository_root).as_posix()
        except (OSError, ValueError) as exc:
            raise MutationPathAuditError(
                f"explicit mutation scan root escapes repository: {scan_root}"
            ) from exc
        normalized_roots.add(root_relpath or ".")
        for path in _iter_python_files(
            resolved_candidate,
            repository_root=repository_root,
        ):
            try:
                relpath = path.relative_to(repository_root).as_posix()
            except ValueError as exc:
                raise MutationPathAuditError(
                    f"mutation inventory source escapes repository: {path}"
                ) from exc
            paths.add(relpath)
    ordered_paths = sorted(paths)
    sources = _capture_sources(repository_root, ordered_paths)
    return _PythonSourceCapture(
        sources=sources,
        source_scope={
            "mode": "explicit_scan_roots",
            "path_digest_algorithm": _PATH_DIGEST_ALGORITHM,
            "scan_roots": sorted(normalized_roots),
            "scanned_python_count": len(ordered_paths),
            "scanned_python_paths_sha256": _canonical_path_digest(ordered_paths),
            "exclusion_policy": [],
        },
    )


def _capture_python_sources(
    *,
    repository_root: Path,
    scan_roots: Sequence[Path | str] | None,
) -> _PythonSourceCapture:
    root = repository_root.resolve()
    if scan_roots is None:
        return _git_tracked_python_capture(root)
    return _explicit_python_capture(root, scan_roots)


def _source_projection_from_capture(
    source_capture: _PythonSourceCapture,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "path": source.path,
            "sha256": source.sha256,
            "size_bytes": source.size_bytes,
        }
        for source in source_capture.sources
    )


def mutation_source_projection(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    scan_roots: Sequence[Path | str] | None = None,
) -> list[dict[str, Any]]:
    """Capture and return the exact byte identity of every inventory source.

    Compatibility callers that need only a projection may retain this API.
    Authority paths that bind both AST semantics and bytes must instead use
    :func:`capture_mutation_audit` or
    :func:`validate_frozen_mutation_capture` so both derive from one capture.
    """

    source_capture = _capture_python_sources(
        repository_root=repository_root,
        scan_roots=scan_roots,
    )
    return [dict(item) for item in _source_projection_from_capture(source_capture)]


def _source(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001  # pragma: no cover
        return type(node).__name__


def _root_key(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _root_key(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return f"{_root_key(node.value)}[{_source(node.slice)}]"
    return _source(node)


def _literal_text(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_repository_bearing_name(name: str) -> bool:
    """Return whether an unknown value may designate a Hub repository.

    Public helpers frequently accept ``repo_id`` (or a prefixed spelling such
    as ``target_repo_id``) and are independently callable even when every
    in-tree caller currently supplies an unprotected literal.  Treat those
    unresolved inputs conservatively; this is target-flow inference, not
    module-wide taint from an unrelated protected literal.
    """

    normalized = str(name or "").strip().casefold()
    return bool(
        normalized in _REPOSITORY_BEARING_NAMES
        or normalized.endswith(("_repo_id", "_repository_id"))
    )


@dataclass(frozen=True)
class _Guard:
    roots: frozenset[str]
    protected: frozenset[str]
    potential_protected: bool
    method: str
    line: int
    runtime_override: str
    binding: tuple[tuple[str, tuple[str, ...]], ...] = ()
    exact_binding: bool = False


@dataclass(frozen=True)
class _GuardedWriteBoundary:
    """Static identity of one recognized one-shot guarded-write callback."""

    identifier: str
    roots: frozenset[str]
    protected: frozenset[str]
    potential_protected: bool
    method: str
    line: int
    binding: tuple[tuple[str, tuple[str, ...]], ...]
    exact_binding: bool
    callback_identifier: str = ""


@dataclass(frozen=True)
class _Value:
    protected: frozenset[str] = frozenset()
    roots: frozenset[str] = frozenset()
    methods: frozenset[str] = frozenset()
    symbols: frozenset[str] = frozenset()
    potential_protected: bool = False
    api_bound: bool = False
    api_attested: bool = False
    api_guards: tuple[_Guard, ...] = ()

    @staticmethod
    def merge(*values: _Value) -> _Value:
        present = [value for value in values if value is not None]
        if not present:
            return _Value()
        api_values = [value for value in present if value.api_bound]
        guards = list(api_values[0].api_guards) if api_values else []
        # An alias can have more than one possible API/method origin after a
        # branch. Only guards common to every origin dominate construction.
        for value in api_values[1:]:
            guards = [guard for guard in guards if guard in value.api_guards]
        return _Value(
            protected=frozenset().union(*(value.protected for value in present)),
            roots=frozenset().union(*(value.roots for value in present)),
            methods=frozenset().union(*(value.methods for value in present)),
            symbols=frozenset().union(*(value.symbols for value in present)),
            potential_protected=any(value.potential_protected for value in present),
            api_bound=any(value.api_bound for value in present),
            api_attested=bool(api_values) and all(
                value.api_attested for value in api_values
            ),
            api_guards=tuple(guards),
        )


@dataclass
class _FunctionDescriptor:
    identifier: str
    display_name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    closure_env: dict[str, _Value]
    closure_guards: tuple[_Guard, ...] = ()
    nested: bool = False


@dataclass
class _FunctionContext:
    descriptor: _FunctionDescriptor
    incoming: dict[str, _Value] = field(default_factory=dict)
    canonical: bool = False
    attested_executor: bool = False
    hard_rejected: bool = False
    unprotected_roots: frozenset[str] = frozenset()
    guarded_write_boundary: _GuardedWriteBoundary | None = None


def _specific_roots(roots: Iterable[str]) -> frozenset[str]:
    """Keep expression roots that identify the value, not merely its owner.

    ``self.repository_id`` is evaluated from both ``self`` and
    ``self.repository_id``.  Treating the broad ``self`` root as repository
    identity would let a guard for one attribute authorize a different
    attribute on the same object.
    """

    values = {str(root) for root in roots if str(root)}
    return frozenset(
        root
        for root in values
        if not any(
            other != root
            and other.startswith((f"{root}.", f"{root}["))
            for other in values
        )
    )


def _guard_matches(guard: _Guard, repo: _Value, method: str) -> bool:
    if guard.method != method:
        return False
    if _specific_roots(guard.roots) & _specific_roots(repo.roots):
        return True
    # Two unresolved, repository-shaped values are not evidence that they are
    # the same target.  A legacy guard is accepted only for a shared value-flow
    # root or an identical protected literal.
    return bool(guard.protected & repo.protected)


def _boundary_matches(
    boundary: _GuardedWriteBoundary,
    repo: _Value,
    method: str,
) -> bool:
    return _guard_matches(
        _Guard(
            roots=boundary.roots,
            protected=boundary.protected,
            potential_protected=boundary.potential_protected,
            method=boundary.method,
            line=boundary.line,
            runtime_override="absent",
            binding=boundary.binding,
            exact_binding=boundary.exact_binding,
        ),
        repo,
        method,
    )


def _dedupe_guards(guards: Iterable[_Guard]) -> tuple[_Guard, ...]:
    result: list[_Guard] = []
    for guard in guards:
        if guard not in result:
            result.append(guard)
    return tuple(result)


def _merge_branch_values(*values: _Value) -> _Value:
    """Merge possible values while retaining only definitely bound symbols."""

    merged = _Value.merge(*values)
    common_symbols = set(values[0].symbols) if values else set()
    for value in values[1:]:
        common_symbols.intersection_update(value.symbols)
    return _Value(
        protected=merged.protected,
        roots=merged.roots,
        methods=merged.methods,
        symbols=frozenset(common_symbols),
        potential_protected=merged.potential_protected,
        api_bound=merged.api_bound,
        api_attested=merged.api_attested,
        api_guards=merged.api_guards,
    )


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in target.elts))
    return set()


def _target_roots(target: ast.AST) -> set[str]:
    if isinstance(target, (ast.Name, ast.Attribute, ast.Subscript)):
        return {_root_key(target)}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_roots(item) for item in target.elts))
    return set()


def _block_definitely_terminates(statements: Sequence[ast.stmt]) -> bool:
    """Recognize the small fail-closed forms used before mutation branches."""

    if not statements:
        return False
    final = statements[-1]
    if isinstance(final, (ast.Return, ast.Raise)):
        return True
    if isinstance(final, ast.If):
        return bool(final.orelse) and _block_definitely_terminates(
            final.body
        ) and _block_definitely_terminates(final.orelse)
    return False


def _simple_condition_selector(node: ast.AST) -> tuple[str, bool] | None:
    """Return ``(selector, positive)`` for a simple truthiness condition."""

    if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
        return _root_key(node), True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(
        node.operand, (ast.Name, ast.Attribute, ast.Subscript)
    ):
        return _root_key(node.operand), False
    return None


def _is_attested_create_commit_primitive(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Recognize the fixed token-owning HfApi primitive and nothing else."""

    if isinstance(node, ast.AsyncFunctionDef):
        return False
    if (
        [argument.arg for argument in node.args.posonlyargs] != ["runtime_token"]
        or node.args.args
        or node.args.vararg is not None
        or node.args.kwonlyargs
        or node.args.defaults
        or node.args.kw_defaults
        or node.args.kwarg is None
        or node.args.kwarg.arg != "kwargs"
    ):
        return False
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 7:
        return False
    (
        identity_check,
        token_gate,
        client_assignment,
        client_gate,
        session_assignment,
        session_gate,
        invocation,
    ) = body
    if not (
        isinstance(identity_check, ast.Expr)
        and isinstance(identity_check.value, ast.Call)
        and isinstance(identity_check.value.func, ast.Name)
        and identity_check.value.func.id
        == "_assert_canonical_hf_api_executables_current"
        and not identity_check.value.args
        and not identity_check.value.keywords
    ):
        return False
    if not (
        isinstance(token_gate, ast.If)
        and isinstance(token_gate.test, ast.Compare)
        and isinstance(token_gate.test.left, ast.Constant)
        and token_gate.test.left.value == "token"
        and len(token_gate.test.ops) == 1
        and isinstance(token_gate.test.ops[0], ast.In)
        and len(token_gate.test.comparators) == 1
        and isinstance(token_gate.test.comparators[0], ast.Name)
        and token_gate.test.comparators[0].id == "kwargs"
        and not token_gate.orelse
        and len(token_gate.body) == 1
        and isinstance(token_gate.body[0], ast.Raise)
    ):
        return False
    if not (
        isinstance(client_assignment, ast.Assign)
        and len(client_assignment.targets) == 1
        and isinstance(client_assignment.targets[0], ast.Name)
        and client_assignment.targets[0].id == "api"
        and isinstance(client_assignment.value, ast.Call)
        and isinstance(client_assignment.value.func, ast.Name)
        and client_assignment.value.func.id == "_new_canonical_hf_api"
        and len(client_assignment.value.args) == 1
        and isinstance(client_assignment.value.args[0], ast.Name)
        and client_assignment.value.args[0].id == "runtime_token"
        and not client_assignment.value.keywords
    ):
        return False
    expected_client_test = ast.parse(
        'object.__getattribute__(api, "__dict__").get("token") != runtime_token',
        mode="eval",
    ).body
    if not (
        isinstance(client_gate, ast.If)
        and ast.dump(client_gate.test, include_attributes=False)
        == ast.dump(expected_client_test, include_attributes=False)
        and not client_gate.orelse
        and len(client_gate.body) == 1
        and isinstance(client_gate.body[0], ast.Raise)
    ):
        return False
    if not (
        isinstance(session_assignment, ast.Assign)
        and len(session_assignment.targets) == 1
        and isinstance(session_assignment.targets[0], ast.Name)
        and session_assignment.targets[0].id == "session"
        and (session_call := _named_call(
            session_assignment.value,
            "_fresh_canonical_hf_session",
        ))
        is not None
        and not session_call.args
        and not session_call.keywords
    ):
        return False
    expected_session_test = ast.parse(
        "_CANONICAL_HF_GET_SESSION() is not session",
        mode="eval",
    ).body
    if not (
        isinstance(session_gate, ast.If)
        and ast.dump(session_gate.test, include_attributes=False)
        == ast.dump(expected_session_test, include_attributes=False)
        and not session_gate.orelse
        and len(session_gate.body) == 1
        and isinstance(session_gate.body[0], ast.Raise)
    ):
        return False
    if not isinstance(invocation, ast.Return) or not isinstance(
        invocation.value,
        ast.Call,
    ):
        return False
    call = invocation.value
    return bool(
        isinstance(call.func, ast.Subscript)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "_CANONICAL_HF_API_METHODS"
        and _literal_text(call.func.slice) == "create_commit"
        and len(call.args) == 1
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "api"
        and len(call.keywords) == 2
        and call.keywords[0].arg == "token"
        and isinstance(call.keywords[0].value, ast.Name)
        and call.keywords[0].value.id == "runtime_token"
        and call.keywords[1].arg is None
        and isinstance(call.keywords[1].value, ast.Name)
        and call.keywords[1].value.id == "kwargs"
    )


def _is_attested_fresh_session_boundary(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Require the fixed cached-session reset and pristine-config boundary."""

    if isinstance(node, ast.AsyncFunctionDef):
        return False
    if (
        node.args.posonlyargs
        or node.args.args
        or node.args.vararg is not None
        or node.args.kwonlyargs
        or node.args.kwarg is not None
    ):
        return False

    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 18:
        return False

    def expression(source: str) -> ast.AST:
        return ast.parse(source, mode="eval").body

    def same(left: ast.AST, right: ast.AST) -> bool:
        return ast.dump(left, include_attributes=False) == ast.dump(
            right,
            include_attributes=False,
        )

    def exact_expression_statement(statement: ast.stmt, source: str) -> bool:
        return isinstance(statement, ast.Expr) and same(
            statement.value,
            expression(source),
        )

    def exact_name_assignment(statement: ast.stmt, name: str, source: str) -> bool:
        return bool(
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
            and same(statement.value, expression(source))
        )

    def fail_closed_if(statement: ast.stmt, test: str) -> bool:
        return bool(
            isinstance(statement, ast.If)
            and same(statement.test, expression(test))
            and not statement.orelse
            and len(statement.body) == 1
            and isinstance(statement.body[0], ast.Raise)
        )

    (
        identity_check,
        configured_assignment,
        configured_gate,
        cache_reset,
        session_assignment,
        session_gate,
        state_assignment,
        state_surface_gate,
        headers_assignment,
        hooks_assignment,
        cookies_assignment,
        adapters_assignment,
        header_items_assignment,
        config_gate,
        adapter_loop,
        trust_env_assignment,
        final_session_gate,
        session_return,
    ) = body

    if not exact_expression_statement(
        identity_check,
        "_assert_canonical_hf_api_executables_current()",
    ):
        return False
    if not exact_name_assignment(
        configured_assignment,
        "configured",
        "tuple(name for name in _PROTECTED_TRANSPORT_ENV_NAMES "
        "if str(os.environ.get(name) or '').strip())",
    ):
        return False
    if not fail_closed_if(configured_gate, "configured"):
        return False
    if not exact_expression_statement(cache_reset, "_CANONICAL_HF_RESET_SESSIONS()"):
        return False
    if not exact_name_assignment(
        session_assignment,
        "session",
        "_CANONICAL_HF_GET_SESSION()",
    ):
        return False
    if not fail_closed_if(
        session_gate,
        "type(session) is not _CANONICAL_REQUESTS_SESSION_TYPE "
        "or _CANONICAL_HF_GET_SESSION() is not session",
    ):
        return False
    if not exact_name_assignment(
        state_assignment,
        "state",
        "object.__getattribute__(session, '__dict__')",
    ):
        return False
    if not fail_closed_if(
        state_surface_gate,
        "type(state) is not dict or set(state) != {"
        "'adapters', 'auth', 'cert', 'cookies', 'headers', 'hooks', "
        "'max_redirects', 'params', 'proxies', 'stream', 'trust_env', 'verify'}",
    ):
        return False
    for statement, name, source in (
        (headers_assignment, "headers", "state['headers']"),
        (hooks_assignment, "hooks", "state['hooks']"),
        (cookies_assignment, "cookies", "state['cookies']"),
        (adapters_assignment, "adapters", "state['adapters']"),
    ):
        if not exact_name_assignment(statement, name, source):
            return False
    if not exact_name_assignment(
        header_items_assignment,
        "header_items",
        "tuple(sorted((str(key).casefold(), str(value)) "
        "for key, value in headers.items())) "
        "if type(headers) is _CANONICAL_HEADER_DICT_TYPE else ()",
    ):
        return False
    if not fail_closed_if(
        config_gate,
        "header_items != _CANONICAL_REQUESTS_DEFAULT_HEADERS "
        "or state['auth'] is not None "
        "or type(state['proxies']) is not dict or state['proxies'] "
        "or type(hooks) is not dict or set(hooks) != {'response'} "
        "or type(hooks['response']) is not list or hooks['response'] "
        "or type(state['params']) is not dict or state['params'] "
        "or state['stream'] is not False or state['verify'] is not True "
        "or state['cert'] is not None "
        "or type(state['max_redirects']) is not int "
        "or isinstance(state['max_redirects'], bool) "
        "or state['max_redirects'] != 30 or state['trust_env'] is not True "
        "or type(cookies) is not _CANONICAL_COOKIE_JAR_TYPE or len(cookies) != 0 "
        "or type(adapters) is not OrderedDict "
        "or tuple(adapters) != ('https://', 'http://')",
    ):
        return False
    if not (
        isinstance(adapter_loop, ast.For)
        and isinstance(adapter_loop.target, ast.Name)
        and adapter_loop.target.id == "adapter"
        and same(adapter_loop.iter, expression("adapters.values()"))
        and not adapter_loop.orelse
        and len(adapter_loop.body) == 3
        and exact_name_assignment(
            adapter_loop.body[0],
            "adapter_state",
            "object.__getattribute__(adapter, '__dict__')",
        )
        and exact_name_assignment(
            adapter_loop.body[1],
            "retries",
            "adapter_state.get('max_retries') "
            "if type(adapter_state) is dict else None",
        )
        and fail_closed_if(
            adapter_loop.body[2],
            "type(adapter) is not _CANONICAL_HF_ADAPTER_TYPE "
            "or type(adapter_state) is not dict "
            "or set(adapter_state) != {"
            "'_pool_block', '_pool_connections', '_pool_maxsize', 'config', "
            "'max_retries', 'poolmanager', 'proxy_manager'} "
            "or adapter_state['config'] != {} "
            "or adapter_state['proxy_manager'] != {} "
            "or adapter_state['_pool_connections'] != 10 "
            "or adapter_state['_pool_maxsize'] != 10 "
            "or adapter_state['_pool_block'] is not False "
            "or getattr(retries, 'total', None) != 0 "
            "or getattr(retries, 'read', None) is not False",
        )
    ):
        return False
    if not (
        isinstance(trust_env_assignment, ast.Assign)
        and len(trust_env_assignment.targets) == 1
        and isinstance(trust_env_assignment.targets[0], ast.Subscript)
        and isinstance(trust_env_assignment.targets[0].value, ast.Name)
        and trust_env_assignment.targets[0].value.id == "state"
        and _literal_text(trust_env_assignment.targets[0].slice) == "trust_env"
        and isinstance(trust_env_assignment.value, ast.Constant)
        and trust_env_assignment.value.value is False
    ):
        return False
    if not fail_closed_if(
        final_session_gate,
        "_CANONICAL_HF_GET_SESSION() is not session "
        "or object.__getattribute__(session, '__dict__').get('trust_env') is not False",
    ):
        return False
    return bool(
        isinstance(session_return, ast.Return)
        and isinstance(session_return.value, ast.Name)
        and session_return.value.id == "session"
    )


def _is_attested_preflight_prepare(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Require the preflight to return the exact inert prepared capsule."""

    if isinstance(node, ast.AsyncFunctionDef):
        return False
    positional = list(node.args.posonlyargs) + list(node.args.args)
    if (
        [argument.arg for argument in positional]
        != ["self", "decision", "runtime_token"]
        or node.args.vararg is not None
        or node.args.kwarg is not None
        or node.args.kwonlyargs
    ):
        return False
    returns = [item for item in ast.walk(node) if isinstance(item, ast.Return)]
    if len(returns) != 1 or not isinstance(returns[0].value, ast.Call):
        return False
    constructor = returns[0].value
    if not (
        isinstance(constructor.func, ast.Name)
        and constructor.func.id == _PREPARED_EXECUTOR_CLASS
        and not constructor.args
        and len(constructor.keywords) == 5
        and all(keyword.arg is not None for keyword in constructor.keywords)
    ):
        return False
    keywords = {
        keyword.arg: _source(keyword.value)
        for keyword in constructor.keywords
        if keyword.arg is not None
    }
    return keywords == {
        "canonical_candidate_digest": "canonical_candidate_digest",
        "canonical_message": "self.canonical_message",
        "mutation_binding": "self.mutation_binding",
        "operations_payload": "self.operations_payload",
        "runtime_token": "runtime_token",
    }


def _is_attested_prepared_call(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if isinstance(node, ast.AsyncFunctionDef):
        return False
    positional = list(node.args.posonlyargs) + list(node.args.args)
    return bool(
        [argument.arg for argument in positional] == ["self"]
        and node.args.vararg is None
        and node.args.kwarg is None
        and not node.args.kwonlyargs
    )


def _simple_name_assignment_source(
    statements: Sequence[ast.stmt],
    target_name: str,
) -> str | None:
    matches = [
        statement.value
        for statement in statements
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == target_name
        )
    ]
    return _source(matches[0]) if len(matches) == 1 else None


def _exact_named_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == name
        )
    ]


def _attested_prepared_factory_call(
    tree: ast.Module,
) -> tuple[ast.FunctionDef, ast.Call] | None:
    """Return the exact closure-prepared call and its class assignment."""

    prepared_classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == _PREPARED_EXECUTOR_CLASS
    ]
    factories = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == _PREPARED_CALL_FACTORY
    ]
    class_call_assignments = [
        (statement, target)
        for statement in tree.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else (statement.target,)
        )
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == _PREPARED_EXECUTOR_CLASS
        and target.attr == "__call__"
    ]
    if (
        len(prepared_classes) != 1
        or any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == "__call__"
            for member in prepared_classes[0].body
        )
        or len(factories) != 1
        or len(class_call_assignments) != 1
    ):
        return None
    factory = factories[0]
    assignment, assignment_target = class_call_assignments[0]
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and assignment.targets[0] is assignment_target
        and isinstance(assignment.value, ast.Call)
    ):
        return None
    assignment_call = assignment.value
    if not (
        not factory.args.posonlyargs
        and not factory.args.args
        and factory.args.vararg is None
        and factory.args.kwarg is None
        and [argument.arg for argument in factory.args.kwonlyargs]
        == list(_PREPARED_CALL_FACTORY_BINDINGS)
        and factory.args.kw_defaults == [None] * len(_PREPARED_CALL_FACTORY_BINDINGS)
        and isinstance(assignment_call.func, ast.Name)
        and assignment_call.func.id == _PREPARED_CALL_FACTORY
        and not assignment_call.args
        and _has_exact_keyword_sources(
            assignment_call,
            _PREPARED_CALL_FACTORY_BINDINGS,
        )
    ):
        return None

    prepared_calls = [
        statement
        for statement in factory.body
        if isinstance(statement, ast.FunctionDef)
        and statement.name == "prepared_call"
    ]
    factory_returns = [
        statement
        for statement in factory.body
        if isinstance(statement, ast.Return)
    ]
    if (
        len(prepared_calls) != 1
        or len(factory_returns) != 1
        or not isinstance(factory_returns[0].value, ast.Name)
        or factory_returns[0].value.id != "prepared_call"
    ):
        return None
    prepared = prepared_calls[0]
    if not _is_attested_prepared_call(prepared):
        return None
    expected_aliases = {
        "require_guard_local": "require_guard",
        "rehash_files_local": "rehash_files",
        "protected_write_local": "protected_write",
        "create_commit_local": "create_commit",
        "payload_digest": "self.mutation_binding.payload_digest",
    }
    if any(
        _simple_name_assignment_source(prepared.body, target) != source
        for target, source in expected_aliases.items()
    ):
        return None

    commit_once = [
        statement
        for statement in prepared.body
        if isinstance(statement, ast.FunctionDef)
        and statement.name == "commit_once"
    ]
    if len(commit_once) != 1:
        return None
    commit = commit_once[0]
    if not (
        not commit.args.posonlyargs
        and not commit.args.args
        and not commit.args.kwonlyargs
        and commit.args.vararg is None
        and commit.args.kwarg is None
    ):
        return None
    transport_calls = _exact_named_calls(commit, "create_commit_local")
    if len(transport_calls) != 1:
        return None
    transport = transport_calls[0]
    if not (
        [_source(argument) for argument in transport.args]
        == ["self.runtime_token"]
        and _has_exact_keyword_sources(transport, _PREPARED_WRITE_KEYWORDS)
    ):
        return None

    guard_calls = _exact_named_calls(prepared, "require_guard_local")
    protected_calls = _exact_named_calls(prepared, "protected_write_local")
    rehash_calls = _exact_named_calls(prepared, "rehash_files_local")
    if not (
        len(guard_calls) == 1
        and [_source(item) for item in guard_calls[0].args]
        == ["self.mutation_binding.repository_id"]
        and _has_exact_keyword_sources(
            guard_calls[0],
            {
                "method": "'create_commit'",
                "expected_phase": "'state_main'",
                "expected_operation": "'additive_main_upload'",
                "expected_manifest_digest": "self.canonical_candidate_digest",
                "expected_payload_digest": "payload_digest",
            },
        )
        and len(rehash_calls) == 1
        and [_source(item) for item in rehash_calls[0].args]
        == ["self.operations_payload", "self.mutation_binding.files"]
        and not rehash_calls[0].keywords
        and len(protected_calls) == 1
        and [_source(item) for item in protected_calls[0].args]
        == [
            "self.mutation_binding.repository_id",
            "'create_commit'",
            "commit_once",
        ]
        and _has_exact_keyword_sources(
            protected_calls[0],
            {
                "expected_phase": "'state_main'",
                "expected_operation": "'additive_main_upload'",
                "expected_manifest_digest": "self.canonical_candidate_digest",
                "expected_payload_digest": "payload_digest",
            },
        )
    ):
        return None
    return prepared, assignment_call


def _named_call(node: ast.AST, name: str) -> ast.Call | None:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ):
        return node
    return None


def _has_exact_keyword_sources(
    call: ast.Call,
    expected: Mapping[str, str],
) -> bool:
    return bool(
        len(call.keywords) == len(expected)
        and all(keyword.arg is not None for keyword in call.keywords)
        and {
            keyword.arg: _source(keyword.value)
            for keyword in call.keywords
            if keyword.arg is not None
        }
        == dict(expected)
    )


def _assignment_call(
    statements: Sequence[ast.stmt],
    target_name: str,
    function_name: str,
) -> ast.Call | None:
    matches: list[ast.Call] = []
    for statement in statements:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == target_name
        ):
            continue
        call = _named_call(statement.value, function_name)
        if call is not None:
            matches.append(call)
    return matches[0] if len(matches) == 1 else None


def _runtime_authority_boundary_is_exact(tree: ast.Module) -> bool:
    """Attest that authority encloses only the prepared capsule invocation."""

    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == _CANONICAL_FUNCTION
    ]
    if len(functions) != 1 or isinstance(functions[0], ast.AsyncFunctionDef):
        return False
    function = functions[0]
    prepared_executor_call = _assignment_call(
        function.body,
        "prepared_executor",
        "prepare_method",
    )
    prepared_call_attestation = _assignment_call(
        function.body,
        "prepared_call",
        "_require_attested_prepared_executor",
    )
    final_prepared_call_attestation = _assignment_call(
        function.body,
        "final_prepared_call",
        "_require_attested_prepared_executor",
    )
    final_executor_assignments = [
        statement
        for statement in function.body
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Tuple)
            and [_source(item) for item in statement.targets[0].elts]
            == ["final_executor_binding", "final_prepare_method"]
            and _named_call(
                statement.value,
                "_require_attested_mutation_executor",
            )
            is not None
        )
    ]
    if (
        prepared_executor_call is None
        or prepared_call_attestation is None
        or final_prepared_call_attestation is None
        or len(final_executor_assignments) != 1
    ):
        return False
    final_executor_attestation = final_executor_assignments[0].value
    if not isinstance(final_executor_attestation, ast.Call):  # narrowed above
        return False
    if not (
        [_source(item) for item in prepared_executor_call.args]
        == ["mutation_executor", "bound", "runtime_token"]
        and not prepared_executor_call.keywords
        and [_source(item) for item in prepared_call_attestation.args]
        == ["prepared_executor"]
        and _has_exact_keyword_sources(
            prepared_call_attestation,
            {
                "expected_binding": "executor_binding",
                "expected_candidate_digest": "bound.final_manifest_digest",
                "runtime_token": "runtime_token",
            },
        )
        and [_source(item) for item in final_executor_attestation.args]
        == ["mutation_executor"]
        and not final_executor_attestation.keywords
        and [_source(item) for item in final_prepared_call_attestation.args]
        == ["prepared_executor"]
        and _has_exact_keyword_sources(
            final_prepared_call_attestation,
            {
                "expected_binding": "executor_binding",
                "expected_candidate_digest": "bound.final_manifest_digest",
                "runtime_token": "runtime_token",
            },
        )
    ):
        return False
    authority_scopes = [
        node
        for node in function.body
        if isinstance(node, ast.With)
        and len(node.items) == 1
        and _named_call(
            node.items[0].context_expr,
            "_canonical_runtime_authorization",
        )
        is not None
    ]
    if len(authority_scopes) != 1:
        return False
    scope = authority_scopes[0]
    item = scope.items[0]
    authority_call = item.context_expr
    if not isinstance(authority_call, ast.Call):  # narrowed above
        return False
    if not (
        isinstance(item.optional_vars, ast.Name)
        and item.optional_vars.id == "authorization"
        and not authority_call.args
        and _has_exact_keyword_sources(
            authority_call,
            {
                "repository_id": "bound.dataset_repo_id",
                "phase": "bound.phase",
                "operation": "bound.operation",
                "final_manifest_digest": "bound.final_manifest_digest",
                "mutation_binding": "executor_binding",
                "preflight_executor": "mutation_executor",
                "prepare_method": "prepare_method",
                "prepared_executor": "prepared_executor",
                "prepared_call": "prepared_call",
                "principal": "final_snapshot['principal']",
                "principal_authority_digest": (
                    "final_snapshot['principal_authority_digest']"
                ),
                "principal_probe": "req.principal_probe",
                "credential_identity": "final_snapshot['credential_identity']",
                "credentials_scope": "final_snapshot['credentials_scope']",
                "token_env": "final_snapshot['token_env']",
            },
        )
        and len(scope.body) == 3
    ):
        return False
    result_assignment, consumption_assertion, result_return = scope.body
    if not (
        isinstance(result_assignment, ast.Assign)
        and len(result_assignment.targets) == 1
        and isinstance(result_assignment.targets[0], ast.Name)
        and result_assignment.targets[0].id == "result"
        and (prepared_invocation := _named_call(
            result_assignment.value,
            "prepared_call",
        ))
        is not None
        and [_source(item) for item in prepared_invocation.args]
        == ["prepared_executor"]
        and not prepared_invocation.keywords
        and isinstance(consumption_assertion, ast.Expr)
        and (
            consumption_call := _named_call(
                consumption_assertion.value,
                "_assert_canonical_runtime_authorization_consumed",
            )
        )
        is not None
        and [_source(item) for item in consumption_call.args] == ["authorization"]
        and not consumption_call.keywords
        and isinstance(result_return, ast.Return)
        and isinstance(result_return.value, ast.Name)
        and result_return.value.id == "result"
    ):
        return False
    authority_calls = [
        item
        for item in ast.walk(function)
        if _named_call(item, "_canonical_runtime_authorization") is not None
    ]
    prepared_calls = [
        item
        for item in ast.walk(function)
        if _named_call(item, "prepared_call") is not None
    ]
    consumption_calls = [
        item
        for item in ast.walk(function)
        if _named_call(
            item,
            "_assert_canonical_runtime_authorization_consumed",
        )
        is not None
    ]
    registration_calls = [
        item
        for item in ast.walk(tree)
        if _named_call(item, "_register_canonical_runtime_trust_anchor")
        is not None
    ]
    if len(registration_calls) != 1:
        return False
    registration = registration_calls[0]
    registration_is_top_level = any(
        isinstance(statement, ast.Expr) and statement.value is registration
        for statement in tree.body
    )
    registration_deleted = any(
        isinstance(statement, ast.Delete)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id
        == "_register_canonical_runtime_trust_anchor"
        for statement in tree.body
    )
    return bool(
        len(authority_calls) == 1
        and len(prepared_calls) == 1
        and len(consumption_calls) == 1
        and registration_is_top_level
        and registration_deleted
        and not registration.args
        and _has_exact_keyword_sources(
            registration,
            {
                "runtime_module": "sys.modules[__name__]",
                "authorizer": _CANONICAL_FUNCTION,
                "runtime_executable": "_CanonicalPublicationRuntimeExecutable",
            },
        )
    )


class _PrivateGuardReferenceCollector(ast.NodeVisitor):
    def __init__(self, relpath: str) -> None:
        self.relpath = relpath
        self.function_stack: list[str] = []
        self.violations: list[dict[str, Any]] = []

    def _allowed(self, name: str) -> bool:
        if name in _GUARD_CLOSURE_PRIVATE_NAMES:
            return bool(
                self.relpath == _GUARD_RELPATH
                and "_build_authority_manager" in self.function_stack
            )
        if name in _GUARD_RUNTIME_PRIVATE_NAMES:
            return self.relpath in {_GUARD_RELPATH, _RUNTIME_RELPATH}
        if name in _GUARD_MODULE_PRIVATE_NAMES:
            return self.relpath == _GUARD_RELPATH
        if name in _GUARD_PUBLISHER_PRIVATE_NAMES:
            return self.relpath == _GUARD_RELPATH or (
                self.relpath == _PUBLISHER_RELPATH and not self.function_stack
            )
        return True

    def _record(self, name: str, node: ast.AST) -> None:
        if self._allowed(name):
            return
        self.violations.append(
            {
                "path": self.relpath,
                "line": int(getattr(node, "lineno", 0)),
                "symbol": name,
                "error": "guard_private_authority_reference_outside_owner",
            }
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Name(self, node: ast.Name) -> None:
        self._record(node.id, node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._record(node.attr, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self._record(alias.name, node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            self._record(node.args[1].value, node.args[1])
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.slice, ast.Constant) and isinstance(
            node.slice.value,
            str,
        ):
            self._record(node.slice.value, node.slice)
        self.generic_visit(node)


def _authority_boundary_violations(
    tree: ast.Module,
    *,
    relpath: str,
) -> list[dict[str, Any]]:
    collector = _PrivateGuardReferenceCollector(relpath)
    collector.visit(tree)
    violations = list(collector.violations)
    if relpath == _RUNTIME_RELPATH and not _runtime_authority_boundary_is_exact(tree):
        function = next(
            (
                item
                for item in tree.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == _CANONICAL_FUNCTION
            ),
            tree,
        )
        violations.append(
            {
                "path": relpath,
                "line": int(getattr(function, "lineno", 0)),
                "symbol": _CANONICAL_FUNCTION,
                "error": "canonical_authority_does_not_wrap_exact_prepared_call",
            }
        )
    if relpath == _PUBLISHER_RELPATH and _attested_prepared_factory_call(tree) is None:
        factory = next(
            (
                item
                for item in tree.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == _PREPARED_CALL_FACTORY
            ),
            tree,
        )
        violations.append(
            {
                "path": relpath,
                "line": int(getattr(factory, "lineno", 0)),
                "symbol": _PREPARED_CALL_FACTORY,
                "error": "prepared_executor_factory_or_assignment_not_exact",
            }
        )
    return [
        dict(item)
        for _, item in sorted(
            {
                (item["path"], item["line"], item["symbol"], item["error"]): item
                for item in violations
            }.items()
        )
    ]


class _FileAnalyzer:
    """Small, conservative, flow-sensitive analyser for one Python module."""

    def __init__(
        self,
        *,
        path: Path,
        relpath: str,
        source_text: str,
        tree: ast.Module,
        protected_repos: set[str],
        required_runtime: str,
    ) -> None:
        self.path = path
        self.relpath = relpath
        self.source_text = source_text
        self.tree = tree
        self.protected_repos = protected_repos
        self.required_runtime = required_runtime
        self.base_env: dict[str, _Value] = {}
        self.functions: dict[str, _FunctionDescriptor] = {}
        self.name_to_functions: dict[str, list[str]] = {}
        self.preflight_prepare: str | None = None
        self.prepared_executor_call: str | None = None
        self.fresh_session_boundary_attested = False
        self.queue: list[_FunctionContext] = []
        self.seen_contexts: set[tuple[Any, ...]] = set()
        self.raw_writes: list[dict[str, Any]] = []
        self.hard_rejections: list[dict[str, Any]] = []
        self.module_descriptor: _FunctionDescriptor | None = None
        self._index_module()

    def _protected_literal(self, text: str) -> frozenset[str]:
        normalized = str(text).strip().casefold()
        return frozenset({normalized}) if normalized in self.protected_repos else frozenset()

    def _import_value(self, original: str) -> _Value:
        symbol = original.rsplit(".", 1)[-1]
        methods = frozenset({symbol}) if symbol in PROTECTED_WRITE_METHODS else frozenset()
        return _Value(methods=methods, symbols=frozenset({symbol, original}))

    def _bind_import(self, stmt: ast.Import | ast.ImportFrom, env: dict[str, _Value]) -> None:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                env[local] = self._import_value(alias.name)
            return
        module = stmt.module or ""
        for alias in stmt.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            original = f"{module}.{alias.name}" if module else alias.name
            env[local] = self._import_value(original)

    def _index_module(self) -> None:
        session_boundaries = [
            stmt
            for stmt in self.tree.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            and stmt.name == "_fresh_canonical_hf_session"
            and _is_attested_fresh_session_boundary(stmt)
        ]
        self.fresh_session_boundary_attested = len(session_boundaries) == 1
        for stmt in self.tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                self._bind_import(stmt, self.base_env)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                value = self._eval_static_value(stmt.value, self.base_env)
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    self._bind_target(target, value, self.base_env)

        for stmt in self.tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                descriptor = self._register_function(stmt, stmt.name, nested=False)
                if (
                    self.relpath == _PUBLISHER_RELPATH
                    and stmt.name in _ATTESTED_API_WRITE_FUNCTIONS
                ):
                    method = _ATTESTED_API_WRITE_FUNCTIONS[stmt.name]
                    symbols = {
                        stmt.name,
                        f"function:{descriptor.identifier}",
                        f"api-write:{method}",
                    }
                    if (
                        self.fresh_session_boundary_attested
                        and _is_attested_create_commit_primitive(stmt)
                    ):
                        symbols.add(f"attested-api-write:{method}")
                    self.base_env[stmt.name] = _Value(
                        methods=frozenset({method}),
                        symbols=frozenset(symbols),
                        roots=frozenset({stmt.name}),
                    )
            elif isinstance(stmt, ast.ClassDef):
                for member in stmt.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        descriptor = self._register_function(
                            member,
                            f"{stmt.name}.{member.name}",
                            nested=False,
                        )
                        if (
                            self.relpath == _PUBLISHER_RELPATH
                            and stmt.name == _PREFLIGHT_CLASS
                            and member.name == "prepare"
                            and _is_attested_preflight_prepare(member)
                        ):
                            self.preflight_prepare = descriptor.identifier
                        elif (
                            self.relpath == _PUBLISHER_RELPATH
                            and stmt.name == _PREPARED_EXECUTOR_CLASS
                            and member.name == "__call__"
                            and _is_attested_prepared_call(member)
                        ):
                            self.prepared_executor_call = descriptor.identifier
        for name, identifiers in self.name_to_functions.items():
            if len(identifiers) == 1:
                self.base_env[name] = _Value.merge(
                    self.base_env.get(name, _Value()),
                    _Value(
                        symbols=frozenset({f"function:{identifiers[0]}"}),
                        roots=frozenset({name}),
                    ),
                )

        if (
            self.relpath == _PUBLISHER_RELPATH
            and self.prepared_executor_call is None
        ):
            factory_attestation = _attested_prepared_factory_call(self.tree)
            if factory_attestation is not None:
                prepared_call, _assignment_call = factory_attestation
                factory_identifiers = self.name_to_functions.get(
                    _PREPARED_CALL_FACTORY,
                    [],
                )
                rehash_identifiers = self.name_to_functions.get(
                    "_rehash_prepared_snapshot_files",
                    [],
                )
                primitive_identifiers = self.name_to_functions.get(
                    "_canonical_hf_api_create_commit",
                    [],
                )
                require_guard = self.base_env.get(
                    "require_unprotected_or_runtime",
                    _Value(),
                )
                protected_write = self.base_env.get("guarded_write", _Value())
                rehash_files = self.base_env.get(
                    "_rehash_prepared_snapshot_files",
                    _Value(),
                )
                create_commit = self.base_env.get(
                    "_canonical_hf_api_create_commit",
                    _Value(),
                )
                guard_module = (
                    "ipfs_datasets_py.huggingface.protected_repo_guard."
                )
                expected_guard_symbols = {
                    frozenset(
                        {
                            "require_unprotected_or_runtime",
                            prefix + "require_unprotected_or_runtime",
                        }
                    )
                    for prefix in (guard_module, "protected_repo_guard.")
                }
                expected_write_symbols = {
                    frozenset(
                        {
                            "guarded_write",
                            prefix + "guarded_write",
                        }
                    )
                    for prefix in (guard_module, "protected_repo_guard.")
                }
                exact_factory_bindings = bool(
                    len(factory_identifiers) == 1
                    and len(rehash_identifiers) == 1
                    and len(primitive_identifiers) == 1
                    and require_guard.symbols in expected_guard_symbols
                    and protected_write.symbols in expected_write_symbols
                    and rehash_files.symbols
                    == frozenset({f"function:{rehash_identifiers[0]}"})
                    and rehash_files.roots
                    == frozenset({"_rehash_prepared_snapshot_files"})
                    and create_commit.methods == frozenset({"create_commit"})
                    and create_commit.roots
                    == frozenset({"_canonical_hf_api_create_commit"})
                    and create_commit.symbols
                    == frozenset(
                        {
                            "_canonical_hf_api_create_commit",
                            f"function:{primitive_identifiers[0]}",
                            "api-write:create_commit",
                            "attested-api-write:create_commit",
                        }
                    )
                )
                if exact_factory_bindings:
                    closure_env = dict(self.base_env)
                    closure_env.update(
                        {
                            "require_guard": require_guard,
                            "rehash_files": rehash_files,
                            "protected_write": protected_write,
                            "create_commit": create_commit,
                        }
                    )
                    descriptor = self._register_function(
                        prepared_call,
                        f"{_PREPARED_EXECUTOR_CLASS}.__call__",
                        nested=True,
                        closure_env=closure_env,
                        owner=(
                            "attested-prepared-factory:"
                            f"{factory_identifiers[0]}"
                        ),
                    )
                    self.prepared_executor_call = descriptor.identifier

        if self.preflight_prepare is not None and self.prepared_executor_call is not None:
            preflight_class = _Value(
                symbols=frozenset(
                    {
                        _PREFLIGHT_CLASS,
                        f"attested-preflight-class:{self.preflight_prepare}",
                    }
                ),
                roots=frozenset({_PREFLIGHT_CLASS}),
            )
            self.base_env[_PREFLIGHT_CLASS] = preflight_class
            # Class methods registered before the module-level ``__call__``
            # assignment captured an earlier immutable view of module names.
            # Propagate only this newly proven class identity into those
            # descriptors so their constructor calls can resolve the capsule.
            for registered in self.functions.values():
                registered.closure_env[_PREFLIGHT_CLASS] = preflight_class
        module_node = ast.FunctionDef(
            name="<module>",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[
                stmt
                for stmt in self.tree.body
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ],
            decorator_list=[],
        )
        self.module_descriptor = _FunctionDescriptor(
            identifier="<module>@1",
            display_name="<module>",
            node=module_node,
            closure_env=dict(self.base_env),
            nested=False,
        )

    def _register_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        display_name: str,
        *,
        nested: bool,
        closure_env: Mapping[str, _Value] | None = None,
        closure_guards: Sequence[_Guard] = (),
        owner: str = "",
    ) -> _FunctionDescriptor:
        identifier = (
            f"{owner}.<locals>.{node.name}@{node.lineno}"
            if nested
            else f"{display_name}@{node.lineno}"
        )
        descriptor = _FunctionDescriptor(
            identifier=identifier,
            display_name=display_name,
            node=node,
            closure_env=dict(closure_env or self.base_env),
            closure_guards=tuple(closure_guards),
            nested=nested,
        )
        self.functions[identifier] = descriptor
        self.name_to_functions.setdefault(node.name, []).append(identifier)
        return descriptor

    def _bind_target(self, target: ast.AST, value: _Value, env: dict[str, _Value]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind_target(item, _Value(), env)

    def _eval_static_value(self, node: ast.AST, env: Mapping[str, _Value]) -> _Value:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                protected = self._protected_literal(node.value)
                roots = (
                    frozenset({f"literal:{node.value.strip().casefold()}"})
                    if protected
                    else frozenset()
                )
                methods = (
                    frozenset({node.value})
                    if node.value in PROTECTED_WRITE_METHODS
                    else frozenset()
                )
                return _Value(protected=protected, roots=roots, methods=methods)
            return _Value()
        if isinstance(node, ast.Name):
            return env.get(node.id, _Value(roots=frozenset({node.id})))
        if isinstance(node, ast.Attribute):
            base = self._eval_static_value(node.value, env)
            methods = (
                frozenset({node.attr})
                if node.attr in PROTECTED_WRITE_METHODS
                else frozenset()
            )
            attribute_symbols = {node.attr}
            attribute_symbols.update(
                f"{symbol}.{node.attr}" for symbol in base.symbols
            )
            return _Value.merge(
                base,
                _Value(
                    roots=frozenset({_root_key(node)}),
                    methods=methods,
                    symbols=frozenset(attribute_symbols),
                    potential_protected=(
                        base.potential_protected
                        or _is_repository_bearing_name(node.attr)
                    ),
                ),
            )
        if isinstance(node, ast.Subscript):
            base = self._eval_static_value(node.value, env)
            return _Value.merge(base, _Value(roots=frozenset({_root_key(node)})))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return _Value.merge(*(self._eval_static_value(item, env) for item in node.elts))
        if isinstance(node, ast.Dict):
            return _Value.merge(
                *(self._eval_static_value(item, env) for item in node.values if item is not None)
            )
        if isinstance(node, (ast.BoolOp, ast.BinOp)):
            values = node.values if isinstance(node, ast.BoolOp) else (node.left, node.right)
            return _Value.merge(*(self._eval_static_value(item, env) for item in values))
        if isinstance(node, ast.IfExp):
            return _Value.merge(
                self._eval_static_value(node.body, env),
                self._eval_static_value(node.orelse, env),
            )
        if isinstance(node, ast.UnaryOp):
            return self._eval_static_value(node.operand, env)
        if isinstance(node, ast.Call):
            symbol = self._call_symbol(node.func, env)
            constructor = self._eval_static_value(node.func, env)
            preflight = next(
                (
                    item.split(":", 1)[1]
                    for item in constructor.symbols
                    if item.startswith("attested-preflight-class:")
                ),
                None,
            )
            if preflight is not None:
                return _Value(
                    symbols=frozenset(
                        {f"attested-preflight-instance:{preflight}"}
                    ),
                    roots=frozenset({_source(node)}),
                )
            if symbol in {"str", "Path", "PurePath"} and node.args:
                return self._eval_static_value(node.args[0], env)
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "strip", "casefold", "lower", "upper", "resolve", "expanduser"
            }:
                return self._eval_static_value(node.func.value, env)
        return _Value()

    def _call_symbol(self, func: ast.AST, env: Mapping[str, _Value]) -> str:
        if isinstance(func, ast.Name):
            value = env.get(func.id)
            if value and value.symbols:
                for candidate in (
                    _CANONICAL_FUNCTION,
                    _LEGACY_GUARD_FUNCTION,
                    _GUARDED_WRITE_FUNCTION,
                    _PROTECTED_PROBE_FUNCTION,
                    *_ATTESTED_API_WRITE_FUNCTIONS,
                    "HfApi",
                    "partial",
                    "getattr",
                    "str",
                    "Path",
                    "PurePath",
                ):
                    if candidate in value.symbols:
                        return candidate
                function_symbol = next(
                    (item for item in value.symbols if item.startswith("function:")), None
                )
                if function_symbol:
                    return function_symbol
                if value.methods:
                    return min(value.methods)
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return ""

    def _is_special_call(
        self,
        func: ast.AST,
        env: Mapping[str, _Value],
        expected: str,
    ) -> bool:
        """Require import provenance for authority-bearing helper names."""

        if isinstance(func, ast.Name):
            value = env.get(func.id)
            if value is None or expected not in value.symbols:
                return False
            provenance = value.symbols
        elif isinstance(func, ast.Attribute) and func.attr == expected:
            provenance = self._eval_static_value(func.value, env).symbols
        else:
            return False
        if expected == _CANONICAL_FUNCTION:
            runtime_name = self.required_runtime.rsplit(".", 1)[-1]
            return any(
                self.required_runtime in item
                or runtime_name in item
                or "legal_corpora_publication_runtime" in item
                for item in provenance
            )
        if expected in {
            _LEGACY_GUARD_FUNCTION,
            _GUARDED_WRITE_FUNCTION,
            _PROTECTED_PROBE_FUNCTION,
        }:
            return any("protected_repo_guard" in item for item in provenance)
        return expected in provenance

    def _parameter_defaults(self, descriptor: _FunctionDescriptor) -> dict[str, _Value]:
        node = descriptor.node
        positional = list(node.args.posonlyargs) + list(node.args.args)
        result = {
            arg.arg: _Value(
                roots=frozenset({arg.arg}),
                potential_protected=_is_repository_bearing_name(arg.arg),
            )
            for arg in positional
        }
        result.update(
            {
                arg.arg: _Value(
                    roots=frozenset({arg.arg}),
                    potential_protected=_is_repository_bearing_name(arg.arg),
                )
                for arg in node.args.kwonlyargs
            }
        )
        if node.args.vararg:
            result[node.args.vararg.arg] = _Value(
                roots=frozenset({node.args.vararg.arg}),
                potential_protected=_is_repository_bearing_name(
                    node.args.vararg.arg
                ),
            )
        if node.args.kwarg:
            result[node.args.kwarg.arg] = _Value(
                roots=frozenset({node.args.kwarg.arg}),
                potential_protected=_is_repository_bearing_name(
                    node.args.kwarg.arg
                ),
            )
        offset = len(positional) - len(node.args.defaults)
        for arg, default in zip(positional[offset:], node.args.defaults):
            default_value = self._eval_static_value(default, descriptor.closure_env)
            result[arg.arg] = _Value(
                protected=default_value.protected,
                roots=frozenset({arg.arg}),
                methods=default_value.methods,
                symbols=default_value.symbols,
                potential_protected=(
                    default_value.potential_protected
                    or _is_repository_bearing_name(arg.arg)
                ),
                api_bound=default_value.api_bound,
                api_attested=default_value.api_attested,
                api_guards=default_value.api_guards,
            )
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                default_value = self._eval_static_value(default, descriptor.closure_env)
                result[arg.arg] = _Value(
                    protected=default_value.protected,
                    roots=frozenset({arg.arg}),
                    methods=default_value.methods,
                    symbols=default_value.symbols,
                    potential_protected=(
                        default_value.potential_protected
                        or _is_repository_bearing_name(arg.arg)
                    ),
                    api_bound=default_value.api_bound,
                    api_attested=default_value.api_attested,
                    api_guards=default_value.api_guards,
                )
        return result

    def _context_key(self, context: _FunctionContext) -> tuple[Any, ...]:
        incoming = tuple(
            sorted(
                (
                    name,
                    tuple(sorted(value.protected)),
                    tuple(sorted(value.roots)),
                    tuple(sorted(value.methods)),
                    value.potential_protected,
                    value.api_bound,
                    value.api_attested,
                    value.api_guards,
                )
                for name, value in context.incoming.items()
            )
        )
        return (
            context.descriptor.identifier,
            incoming,
            context.canonical,
            context.attested_executor,
            context.hard_rejected,
            tuple(sorted(context.unprotected_roots)),
            context.guarded_write_boundary,
        )

    def enqueue(
        self,
        descriptor: _FunctionDescriptor,
        *,
        incoming: Mapping[str, _Value] | None = None,
        canonical: bool = False,
        attested_executor: bool = False,
        hard_rejected: bool = False,
        unprotected_roots: Iterable[str] = (),
        guarded_write_boundary: _GuardedWriteBoundary | None = None,
    ) -> None:
        context = _FunctionContext(
            descriptor=descriptor,
            incoming=dict(incoming or {}),
            canonical=canonical,
            attested_executor=attested_executor,
            hard_rejected=hard_rejected,
            unprotected_roots=frozenset(unprotected_roots),
            guarded_write_boundary=guarded_write_boundary,
        )
        key = self._context_key(context)
        if key not in self.seen_contexts:
            self.seen_contexts.add(key)
            self.queue.append(context)

    def analyze(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        for descriptor in list(self.functions.values()):
            if not descriptor.nested:
                self.enqueue(descriptor)
        if self.module_descriptor is not None:
            self.enqueue(self.module_descriptor)
        while self.queue:
            _FunctionRun(self, self.queue.pop(0)).run()
        return self.raw_writes, self.hard_rejections


class _FunctionRun:
    def __init__(self, owner: _FileAnalyzer, context: _FunctionContext) -> None:
        self.owner = owner
        self.context = context
        self.descriptor = context.descriptor
        self.node = self.descriptor.node
        self.env = dict(self.descriptor.closure_env)
        for name, value in owner._parameter_defaults(self.descriptor).items():
            self.env[name] = context.incoming.get(name, value)
        self.active_guards: tuple[_Guard, ...] = self.descriptor.closure_guards
        self.protected_probe_roots: set[str] = set()
        self.protected_probe_values: list[_Value] = []
        self.conditional_guard_history: dict[str, tuple[_Guard, ...]] = {}
        self.conditional_guard_dependencies: dict[str, set[str]] = {}
        self.unprotected_when_false: dict[str, frozenset[str]] = {}
        self.repeat_depth = 0
        self.refresh_hard_rejection = self._detect_refresh_hard_rejection()

    def _detect_refresh_hard_rejection(self) -> dict[str, Any] | None:
        assignments: dict[str, str] = {}
        for index, stmt in enumerate(self.node.body):
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = _source(stmt.value)
            if not isinstance(stmt, ast.If):
                continue
            test_names = {item.id for item in ast.walk(stmt.test) if isinstance(item, ast.Name)}
            rejected_name = next(
                (
                    name
                    for name in test_names
                    if "publish" in assignments.get(name, "")
                    and "create_repo" in assignments.get(name, "")
                ),
                None,
            )
            if rejected_name is None or not stmt.body:
                continue
            if not isinstance(stmt.body[0], (ast.Return, ast.Raise)):
                continue
            prefix = ast.Module(body=self.node.body[:index], type_ignores=[])
            if any(
                isinstance(item, ast.Call)
                and (
                    self.owner._call_symbol(item.func, self.env) == "HfApi"
                    or self.owner._call_symbol(item.func, self.env) in PROTECTED_WRITE_METHODS
                )
                for item in ast.walk(prefix)
            ):
                continue
            return {
                "path": self.owner.relpath,
                "function": self.descriptor.display_name,
                "line": stmt.lineno,
                "selector": rejected_name,
                "selector_expression": assignments[rejected_name],
                "mechanism": "refresh_hard_rejection",
            }
        return None

    def run(self) -> None:
        if self.refresh_hard_rejection is not None:
            self.owner.hard_rejections.append(self.refresh_hard_rejection)
        self._analyze_block(
            self.node.body,
            self.env,
            self.active_guards,
            self.context.unprotected_roots,
        )

    def _invalidate_conditional_guards(self, targets: Iterable[ast.AST]) -> None:
        names = set().union(*(_target_names(target) for target in targets))
        if not names:
            return
        for condition, dependencies in list(self.conditional_guard_dependencies.items()):
            if names & dependencies:
                self.conditional_guard_dependencies.pop(condition, None)
                self.conditional_guard_history.pop(condition, None)

    def _invalidate_unprotected_implications(
        self,
        targets: Iterable[ast.AST],
    ) -> None:
        roots = set().union(*(_target_roots(target) for target in targets))
        if not roots:
            return
        for selector, repo_roots in list(self.unprotected_when_false.items()):
            if selector in roots or _specific_roots(repo_roots) & roots:
                self.unprotected_when_false.pop(selector, None)

    def _fail_closed_unprotected_implication(
        self,
        stmt: ast.If,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[str, frozenset[str]] | None:
        """Prove ``not selector -> repository is unprotected`` after a gate.

        Only the exact, fail-closed shape is accepted::

            if is_protected_repo(repository) and not selector:
                raise ...

        The proof is later applied solely to the false branch of the same
        unchanged selector.  It is not mutation authority and cannot make the
        selector's true branch safe.
        """

        if not _block_definitely_terminates(stmt.body):
            return None
        if not isinstance(stmt.test, ast.BoolOp) or not isinstance(
            stmt.test.op, ast.And
        ):
            return None
        if len(stmt.test.values) != 2:
            return None
        probe_calls = [
            value
            for value in stmt.test.values
            if isinstance(value, ast.Call)
            and self.owner._is_special_call(
                value.func,
                env,
                _PROTECTED_PROBE_FUNCTION,
            )
        ]
        negated = [
            value
            for value in stmt.test.values
            if isinstance(value, ast.UnaryOp)
            and isinstance(value.op, ast.Not)
            and isinstance(value.operand, (ast.Name, ast.Attribute, ast.Subscript))
        ]
        if len(probe_calls) != 1 or len(negated) != 1:
            return None
        repo, _ = self._repo_value(probe_calls[0], env, active_guards)
        repo_roots = _specific_roots(repo.roots)
        if not repo_roots:
            return None
        return _root_key(negated[0].operand), repo_roots

    def _repo_value(
        self,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[_Value, ast.AST | None]:
        repository_nodes = [
            keyword.value
            for keyword in call.keywords
            if keyword.arg in _REPOSITORY_KEYWORDS
        ]
        if repository_nodes:
            return (
                _Value.merge(
                    *(
                        self._eval_value(node, env, active_guards)
                        for node in repository_nodes
                    )
                ),
                repository_nodes[0],
            )
        if call.args:
            return self._eval_value(call.args[0], env, active_guards), call.args[0]
        return _Value(), None

    def _eval_value(
        self,
        node: ast.AST,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> _Value:
        if isinstance(node, ast.Call):
            symbol = self.owner._call_symbol(node.func, env)
            if symbol == "HfApi":
                return _Value(
                    symbols=frozenset({"HfApi-instance"}),
                    api_bound=True,
                    api_guards=tuple(active_guards),
                )
            if symbol in _API_METHOD_RESOLVERS:
                method = _literal_text(node.args[0]) if node.args else None
                if method in PROTECTED_WRITE_METHODS:
                    return _Value(
                        methods=frozenset({method}),
                        api_bound=True,
                        api_guards=tuple(active_guards),
                    )
            if symbol == "getattr" and len(node.args) >= 2:
                method = _literal_text(node.args[1])
                if method is None:
                    method_value = self._eval_value(node.args[1], env, active_guards)
                    if len(method_value.methods) == 1:
                        method = next(iter(method_value.methods))
                if method in PROTECTED_WRITE_METHODS:
                    receiver = self._eval_value(node.args[0], env, active_guards)
                    return _Value.merge(receiver, _Value(methods=frozenset({method})))
            if symbol == "partial" and node.args:
                bound = self._eval_value(node.args[0], env, active_guards)
                repo_values = [
                    self._eval_value(keyword.value, env, active_guards)
                    for keyword in node.keywords
                    if keyword.arg in _REPOSITORY_KEYWORDS
                ]
                return _Value.merge(bound, *repo_values)
            if symbol in {"str", "Path", "PurePath"} and node.args:
                return self._eval_value(node.args[0], env, active_guards)
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "strip", "casefold", "lower", "upper", "resolve", "expanduser"
            }:
                return self._eval_value(node.func.value, env, active_guards)
        value = self.owner._eval_static_value(node, env)
        attested_methods = {
            symbol.split(":", 1)[1]
            for symbol in value.symbols
            if symbol.startswith("attested-api-write:")
        }
        if len(attested_methods) == 1:
            return _Value.merge(
                value,
                _Value(
                    methods=frozenset(attested_methods),
                    api_bound=True,
                    api_attested=True,
                    api_guards=tuple(active_guards),
                ),
            )
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            return _Value.merge(value, self._eval_value(node.value, env, active_guards))
        if isinstance(node, (ast.BoolOp, ast.BinOp)):
            values = node.values if isinstance(node, ast.BoolOp) else (node.left, node.right)
            return _Value.merge(*(self._eval_value(item, env, active_guards) for item in values))
        if isinstance(node, ast.IfExp):
            return _Value.merge(
                self._eval_value(node.body, env, active_guards),
                self._eval_value(node.orelse, env, active_guards),
            )
        return value

    def _binding_token(
        self,
        node: ast.AST,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[str, ...]:
        """Return a conservative value-flow identity for an exact binding."""

        if isinstance(node, ast.Constant):
            if node.value is None:
                return ()
            if isinstance(node.value, str):
                text = node.value.strip()
                return (f"literal:{text}",) if text else ()
            return (f"literal:{node.value!r}",)
        value = self._eval_value(node, env, active_guards)
        roots = tuple(sorted(_specific_roots(value.roots)))
        if roots:
            return roots
        expression = _source(node).strip()
        return (f"expression:{expression}",) if expression else ()

    def _exact_binding_from_call(
        self,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], bool]:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        binding: list[tuple[str, tuple[str, ...]]] = []
        complete = True
        for name in _EXACT_BINDING_KEYWORDS:
            node = keywords.get(name)
            token = (
                self._binding_token(node, env, active_guards)
                if node is not None
                else ()
            )
            if not token:
                complete = False
            binding.append((name, token))
        return tuple(binding), complete

    def _guard_from_call(
        self,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> _Guard | None:
        if not self.owner._is_special_call(
            call.func,
            env,
            _LEGACY_GUARD_FUNCTION,
        ):
            return None
        repo, _ = self._repo_value(call, env, active_guards)
        method = _literal_text(
            next((kw.value for kw in call.keywords if kw.arg == "method"), None)
        )
        if method not in PROTECTED_WRITE_METHODS:
            return None
        override_node = next(
            (kw.value for kw in call.keywords if kw.arg == "runtime_authorized"), None
        )
        if override_node is None:
            override = "absent"
        elif isinstance(override_node, ast.Constant) and override_node.value is False:
            override = "literal_false"
        else:
            return None
        binding, exact_binding = self._exact_binding_from_call(
            call,
            env,
            active_guards,
        )
        return _Guard(
            roots=repo.roots,
            protected=repo.protected,
            potential_protected=repo.potential_protected,
            method=method,
            line=call.lineno,
            runtime_override=override,
            binding=binding,
            exact_binding=exact_binding,
        )

    def _guarded_write_boundary_from_call(
        self,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[_GuardedWriteBoundary | None, ast.AST | None]:
        if not self.owner._is_special_call(
            call.func,
            env,
            _GUARDED_WRITE_FUNCTION,
        ):
            return None, None
        repo, _ = self._repo_value(call, env, active_guards)
        method_node = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "method"),
            call.args[1] if len(call.args) > 1 else None,
        )
        method = _literal_text(method_node)
        callback = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "callback"),
            call.args[2] if len(call.args) > 2 else None,
        )
        if method not in PROTECTED_WRITE_METHODS or callback is None:
            return None, callback
        override_node = next(
            (kw.value for kw in call.keywords if kw.arg == "runtime_authorized"),
            None,
        )
        if override_node is not None and not (
            isinstance(override_node, ast.Constant) and override_node.value is False
        ):
            return None, callback
        binding, exact_binding = self._exact_binding_from_call(
            call,
            env,
            active_guards,
        )
        return (
            _GuardedWriteBoundary(
                identifier=(
                    f"{self.owner.relpath}:{call.lineno}:"
                    f"{getattr(call, 'col_offset', 0)}"
                ),
                roots=repo.roots,
                protected=repo.protected,
                potential_protected=repo.potential_protected,
                method=method,
                line=call.lineno,
                binding=binding,
                exact_binding=exact_binding,
            ),
            callback,
        )

    def _target_is_protected(
        self,
        repo: _Value,
        unprotected_roots: Iterable[str],
    ) -> bool:
        repo_roots = _specific_roots(repo.roots)
        proven_unprotected = _specific_roots(unprotected_roots)
        if repo_roots and repo_roots.issubset(proven_unprotected):
            return False
        if repo.protected or repo.potential_protected:
            return True
        if _specific_roots(self.protected_probe_roots) & repo_roots:
            return True
        return any(
            bool(
                _specific_roots(value.roots) & repo_roots
                or value.protected & repo.protected
            )
            for value in self.protected_probe_values
        )

    @staticmethod
    def _prepared_binding_is_exact(
        binding: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> bool:
        return dict(binding) == {
            "expected_phase": ("literal:state_main",),
            "expected_operation": ("literal:additive_main_upload",),
            "expected_manifest_digest": ("self.canonical_candidate_digest",),
            "expected_payload_digest": (
                "self.mutation_binding.payload_digest",
            ),
        }

    def _prepared_primitive_call_is_exact(
        self,
        call: ast.Call,
        callee_value: _Value,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> bool:
        if not (
            callee_value.api_attested
            and isinstance(call.func, ast.Name)
            and call.func.id
            in {"_canonical_hf_api_create_commit", "create_commit_local"}
            and len(call.args) == 1
            and self._binding_token(call.args[0], env, active_guards)
            == ("self.runtime_token",)
            and all(keyword.arg is not None for keyword in call.keywords)
        ):
            return False
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        if set(keywords) != set(_PREPARED_WRITE_KEYWORDS):
            return False
        return all(
            self._binding_token(keywords[name], env, active_guards)
            == (expected_root,)
            for name, expected_root in _PREPARED_WRITE_KEYWORDS.items()
        )

    def _record_write(
        self,
        call: ast.Call,
        *,
        method: str,
        callee_value: _Value,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str],
        canonical_override: bool = False,
        attested_executor_override: bool = False,
        hard_rejected_override: bool = False,
        guarded_write_boundary: _GuardedWriteBoundary | None = None,
    ) -> None:
        repo, repo_node = self._repo_value(call, env, active_guards)
        if repo_node is None and callee_value.methods:
            # A statically resolved partial may bind repo_id before the final
            # method invocation.
            repo = _Value(
                protected=callee_value.protected,
                roots=callee_value.roots,
                potential_protected=callee_value.potential_protected,
            )
        canonical = self.context.canonical or canonical_override
        in_prepared_executor = bool(
            self.owner.relpath == _PUBLISHER_RELPATH
            and (
                self.descriptor.display_name
                == f"{_PREPARED_EXECUTOR_CLASS}.__call__"
                or self.descriptor.display_name.startswith(
                    f"{_PREPARED_EXECUTOR_CLASS}.__call__.<locals>."
                )
            )
        )
        attested_executor = bool(
            (self.context.attested_executor or attested_executor_override)
            and in_prepared_executor
        )
        # A structurally delegated canonical callback is itself the protected
        # mutation boundary. Its repository may be closure-bound and only
        # proven by the runtime request in the caller, so retain it as a
        # protected path even when the local expression is otherwise generic.
        protected_target = self._target_is_protected(
            repo,
            unprotected_roots,
        ) or canonical
        matching = [guard for guard in active_guards if _guard_matches(guard, repo, method)]
        boundary = guarded_write_boundary or self.context.guarded_write_boundary
        boundary_matches = bool(
            boundary is not None and _boundary_matches(boundary, repo, method)
        )
        individual_boundary = bool(
            boundary is not None
            and boundary.callback_identifier == self.descriptor.identifier
            and self.repeat_depth == 0
        )
        exact_matching = [
            guard
            for guard in matching
            if (
                guard.exact_binding
                and boundary is not None
                and boundary.exact_binding
                and guard.binding == boundary.binding
            )
        ]
        construction_safe = not callee_value.api_bound or any(
            _guard_matches(guard, repo, method)
            for guard in callee_value.api_guards
        )
        canonical_construction_safe = not callee_value.api_bound or any(
            guard in callee_value.api_guards for guard in exact_matching
        )
        prepared_binding_exact = bool(
            boundary is not None
            and self._prepared_binding_is_exact(boundary.binding)
            and any(self._prepared_binding_is_exact(guard.binding) for guard in exact_matching)
            and _specific_roots(repo.roots)
            == frozenset({"self.mutation_binding.repository_id"})
        )
        primitive_exact_call = self._prepared_primitive_call_is_exact(
            call,
            callee_value,
            env,
            active_guards,
        )
        hard_rejected = (
            self.context.hard_rejected
            or hard_rejected_override
        )
        if not protected_target:
            protection = "not_a_proven_protected_target"
        elif (
            canonical
            and attested_executor
            and boundary_matches
            and individual_boundary
            and boundary is not None
            and boundary.exact_binding
            and exact_matching
            and prepared_binding_exact
            and canonical_construction_safe
            and callee_value.api_attested
            and primitive_exact_call
        ):
            protection = "canonical_runtime"
        elif canonical:
            protection = "unprotected"
        elif hard_rejected:
            protection = "refresh_hard_rejection"
        elif matching and construction_safe:
            protection = "legacy_dominating_guard"
        else:
            protection = "unprotected"
        reason = ""
        if protected_target and protection == "unprotected":
            if canonical:
                if boundary is None:
                    reason = (
                        "canonical callback ancestry has no recognized one-shot "
                        "guarded_write boundary"
                    )
                elif not boundary_matches:
                    reason = "guarded_write target or method does not match the mutation"
                elif not individual_boundary:
                    reason = (
                        "guarded_write callback delegates beyond its individual "
                        "network mutation boundary"
                    )
                elif not boundary.exact_binding:
                    reason = "guarded_write is missing an exact payload binding"
                elif not exact_matching:
                    reason = (
                        "no same-target, same-method dominating guard has the "
                        "identical exact payload binding"
                    )
                elif not attested_executor:
                    reason = (
                        "canonical runtime rejects this callback: it is not the "
                        "source-attested prepared State Laws mutation executor"
                    )
                elif not prepared_binding_exact:
                    reason = (
                        "canonical guard/write binding is not the exact prepared "
                        "State Laws target, phase, operation, manifest, and payload"
                    )
                elif not canonical_construction_safe:
                    reason = (
                        "exact payload-bound guard does not dominate "
                        "API/write-method construction"
                    )
                elif not callee_value.api_attested:
                    reason = (
                        "canonical mutation uses an injected or unattested Hub "
                        "API primitive"
                    )
                elif not primitive_exact_call:
                    reason = (
                        "canonical mutation does not call the fixed transport "
                        "primitive with its exact prepared token and binding"
                    )
            else:
                reason = (
                    "guard does not dominate API/write-method construction"
                    if matching and not construction_safe
                    else "no same-target, same-method dominating legacy guard"
                )
        self.owner.raw_writes.append(
            {
                "path": self.owner.relpath,
                "function": self.descriptor.display_name,
                "line": int(getattr(call, "lineno", 0)),
                "column": int(getattr(call, "col_offset", 0)),
                "write_method": method,
                "call_expression": _source(call),
                "repo_expression": _source(repo_node),
                "repo_roots": sorted(repo.roots),
                "protected_repos": sorted(repo.protected),
                "potential_protected_target": bool(repo.potential_protected),
                "protected_target": protected_target,
                "protection": protection,
                "guard_lines": sorted(guard.line for guard in matching),
                "api_or_method_constructed_after_guard": construction_safe,
                "api_primitive_attested": callee_value.api_attested,
                "api_primitive_exact_call": primitive_exact_call,
                "canonical_callback": canonical,
                "attested_executor": attested_executor,
                "prepared_binding_exact": prepared_binding_exact,
                "exact_binding_guard_lines": sorted(
                    guard.line for guard in exact_matching
                ),
                "guarded_write_id": boundary.identifier if boundary else "",
                "guarded_write_line": boundary.line if boundary else 0,
                "guarded_write_exact_binding": bool(
                    boundary and boundary.exact_binding
                ),
                "guarded_write_individual": individual_boundary,
                "reason": reason,
            }
        )

    def _bind_call_arguments(
        self,
        descriptor: _FunctionDescriptor,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> dict[str, _Value]:
        positional = list(descriptor.node.args.posonlyargs) + list(descriptor.node.args.args)
        incoming: dict[str, _Value] = {}
        for argument, parameter in zip(call.args, positional):
            incoming[parameter.arg] = self._eval_value(argument, env, active_guards)
        valid_names = {arg.arg for arg in positional + list(descriptor.node.args.kwonlyargs)}
        for keyword in call.keywords:
            if keyword.arg and keyword.arg in valid_names:
                incoming[keyword.arg] = self._eval_value(keyword.value, env, active_guards)
        return incoming

    def _resolve_function(self, value: _Value) -> _FunctionDescriptor | None:
        identifiers = [
            symbol.split(":", 1)[1]
            for symbol in value.symbols
            if symbol.startswith("function:")
        ]
        return self.owner.functions.get(identifiers[0]) if len(identifiers) == 1 else None

    def _enqueue_callback(
        self,
        callback: ast.AST,
        *,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str],
    ) -> None:
        if isinstance(callback, ast.Lambda):
            self._visit_expr(
                callback.body,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=True,
            )
            return
        if (
            isinstance(callback, ast.Call)
            and self.owner._call_symbol(callback.func, env) == "partial"
            and callback.args
        ):
            target = callback.args[0]
            descriptor = self._resolve_function(self._eval_value(target, env, active_guards))
            if descriptor is not None:
                synthetic = ast.Call(
                    func=target,
                    args=list(callback.args[1:]),
                    keywords=list(callback.keywords),
                )
                ast.copy_location(synthetic, callback)
                incoming = self._bind_call_arguments(descriptor, synthetic, env, active_guards)
                self.owner.enqueue(
                    descriptor,
                    incoming=incoming,
                    canonical=True,
                    attested_executor=False,
                    unprotected_roots=unprotected_roots,
                )
            return
        callback_value = self._eval_value(callback, env, active_guards)
        preflight_identifiers = {
            symbol.split(":", 1)[1]
            for symbol in callback_value.symbols
            if symbol.startswith("attested-preflight-instance:")
        }
        if (
            preflight_identifiers == {self.owner.preflight_prepare}
            and self.owner.prepared_executor_call is not None
        ):
            prepared = self.owner.functions.get(self.owner.prepared_executor_call)
            if prepared is not None:
                self.owner.enqueue(
                    prepared,
                    canonical=True,
                    attested_executor=True,
                    unprotected_roots=unprotected_roots,
                )
            return
        descriptor = self._resolve_function(callback_value)
        if descriptor is not None:
            self.owner.enqueue(
                descriptor,
                canonical=True,
                attested_executor=False,
                unprotected_roots=unprotected_roots,
            )

    def _enqueue_guarded_write_callback(
        self,
        callback: ast.AST,
        *,
        boundary: _GuardedWriteBoundary,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str],
        canonical: bool,
        attested_executor: bool,
    ) -> None:
        """Follow only the callback owned by one recognized guarded write."""

        if isinstance(callback, ast.Lambda):
            callback_boundary = replace(
                boundary,
                callback_identifier=self.descriptor.identifier,
            )
            self._visit_expr(
                callback.body,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical,
                attested_executor_override=attested_executor,
                guarded_write_boundary=callback_boundary,
            )
            return
        if (
            isinstance(callback, ast.Call)
            and self.owner._call_symbol(callback.func, env) == "partial"
            and callback.args
        ):
            callback_boundary = replace(
                boundary,
                callback_identifier=self.descriptor.identifier,
            )
            synthetic = ast.Call(
                func=callback.args[0],
                args=list(callback.args[1:]),
                keywords=list(callback.keywords),
            )
            ast.copy_location(synthetic, callback)
            self._visit_expr(
                synthetic,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical,
                attested_executor_override=attested_executor,
                guarded_write_boundary=callback_boundary,
            )
            return
        callback_value = self._eval_value(callback, env, active_guards)
        descriptor = self._resolve_function(callback_value)
        if descriptor is not None:
            callback_boundary = replace(
                boundary,
                callback_identifier=descriptor.identifier,
            )
            self.owner.enqueue(
                descriptor,
                canonical=canonical,
                attested_executor=attested_executor,
                unprotected_roots=unprotected_roots,
                guarded_write_boundary=callback_boundary,
            )
            return
        if callback_value.methods:
            callback_boundary = replace(
                boundary,
                callback_identifier=self.descriptor.identifier,
            )
            synthetic = ast.Call(func=callback, args=[], keywords=[])
            ast.copy_location(synthetic, callback)
            self._visit_expr(
                synthetic,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical,
                attested_executor_override=attested_executor,
                guarded_write_boundary=callback_boundary,
            )
            return
        # Unknown callback construction is not granted the boundary.  Visit
        # eager subexpressions so a mutation hidden while constructing the
        # callback is still reported as unprotected.
        self._visit_expr(
            callback,
            env,
            active_guards,
            unprotected_roots,
            canonical_override=canonical,
            attested_executor_override=attested_executor,
        )

    def _visit_expr(
        self,
        node: ast.AST | None,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str] = (),
        *,
        canonical_override: bool = False,
        attested_executor_override: bool = False,
        hard_rejected_override: bool = False,
        guarded_write_boundary: _GuardedWriteBoundary | None = None,
    ) -> None:
        if node is None:
            return
        if not isinstance(node, ast.Call):
            repeated = isinstance(
                node,
                (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
            )
            if repeated:
                self.repeat_depth += 1
            try:
                for child in ast.iter_child_nodes(node):
                    if not isinstance(child, ast.Lambda):
                        self._visit_expr(
                            child,
                            env,
                            active_guards,
                            unprotected_roots,
                            canonical_override=canonical_override,
                            attested_executor_override=attested_executor_override,
                            hard_rejected_override=hard_rejected_override,
                            guarded_write_boundary=guarded_write_boundary,
                        )
            finally:
                if repeated:
                    self.repeat_depth -= 1
            return

        symbol = self.owner._call_symbol(node.func, env)
        callee_value = self._eval_value(node.func, env, active_guards)

        boundary, guarded_callback = self._guarded_write_boundary_from_call(
            node,
            env,
            active_guards,
        )
        if boundary is not None:
            canonical = self.context.canonical or canonical_override
            attested_executor = (
                self.context.attested_executor or attested_executor_override
            )
            callback = guarded_callback
            for index, argument in enumerate(node.args):
                if index != 2:
                    self._visit_expr(
                        argument,
                        env,
                        active_guards,
                        unprotected_roots,
                        canonical_override=canonical_override,
                        attested_executor_override=attested_executor_override,
                        hard_rejected_override=hard_rejected_override,
                        guarded_write_boundary=guarded_write_boundary,
                    )
            for keyword in node.keywords:
                if keyword.value is not callback:
                    self._visit_expr(
                        keyword.value,
                        env,
                        active_guards,
                        unprotected_roots,
                        canonical_override=canonical_override,
                        attested_executor_override=attested_executor_override,
                        hard_rejected_override=hard_rejected_override,
                        guarded_write_boundary=guarded_write_boundary,
                    )
            if callback is not None:
                self._enqueue_guarded_write_callback(
                    callback,
                    boundary=boundary,
                    env=env,
                    active_guards=active_guards,
                    unprotected_roots=unprotected_roots,
                    canonical=canonical,
                    attested_executor=attested_executor,
                )
            return

        if self.owner._is_special_call(
            node.func,
            env,
            _PROTECTED_PROBE_FUNCTION,
        ):
            repo, _ = self._repo_value(node, env, active_guards)
            self.protected_probe_roots.update(repo.roots)
            self.protected_probe_values.append(repo)

        if self.owner._is_special_call(
            node.func,
            env,
            _CANONICAL_FUNCTION,
        ):
            callback = next(
                (kw.value for kw in node.keywords if kw.arg in {"upload_callback", "callback"}),
                node.args[1] if len(node.args) > 1 else None,
            )
            for index, argument in enumerate(node.args):
                if index != 1:
                    self._visit_expr(
                        argument,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
            for keyword in node.keywords:
                if keyword.value is not callback:
                    self._visit_expr(
                        keyword.value,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
            if callback is not None:
                self._enqueue_callback(
                    callback,
                    env=env,
                    active_guards=active_guards,
                    unprotected_roots=unprotected_roots,
                )
            return

        methods = set(callee_value.methods)
        if symbol in PROTECTED_WRITE_METHODS:
            methods.add(symbol)
        if isinstance(node.func, ast.Attribute) and node.func.attr in PROTECTED_WRITE_METHODS:
            methods.add(node.func.attr)
        for method in sorted(methods):
            self._record_write(
                node,
                method=method,
                callee_value=callee_value,
                env=env,
                active_guards=active_guards,
                unprotected_roots=unprotected_roots,
                canonical_override=canonical_override,
                attested_executor_override=attested_executor_override,
                hard_rejected_override=hard_rejected_override,
                guarded_write_boundary=(
                    guarded_write_boundary or self.context.guarded_write_boundary
                ),
            )

        descriptor = self._resolve_function(callee_value)
        if descriptor is not None:
            incoming = self._bind_call_arguments(descriptor, node, env, active_guards)
            self.owner.enqueue(
                descriptor,
                incoming=incoming,
                canonical=self.context.canonical or canonical_override,
                attested_executor=(
                    self.context.attested_executor or attested_executor_override
                ),
                hard_rejected=(
                    self.context.hard_rejected
                    or hard_rejected_override
                ),
                unprotected_roots=unprotected_roots,
                guarded_write_boundary=(
                    guarded_write_boundary or self.context.guarded_write_boundary
                ),
            )

        self._visit_expr(
            node.func,
            env,
            active_guards,
            unprotected_roots,
            canonical_override=canonical_override,
            attested_executor_override=attested_executor_override,
            hard_rejected_override=hard_rejected_override,
            guarded_write_boundary=guarded_write_boundary,
        )
        for argument in node.args:
            self._visit_expr(
                argument,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical_override,
                attested_executor_override=attested_executor_override,
                hard_rejected_override=hard_rejected_override,
                guarded_write_boundary=guarded_write_boundary,
            )
        for keyword in node.keywords:
            self._visit_expr(
                keyword.value,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical_override,
                attested_executor_override=attested_executor_override,
                hard_rejected_override=hard_rejected_override,
                guarded_write_boundary=guarded_write_boundary,
            )

    def _analyze_block(
        self,
        statements: Sequence[ast.stmt],
        initial_env: Mapping[str, _Value],
        initial_guards: Sequence[_Guard],
        initial_unprotected_roots: Iterable[str] = (),
    ) -> tuple[dict[str, _Value], tuple[_Guard, ...]]:
        env = dict(initial_env)
        active_guards = tuple(initial_guards)
        unprotected_roots = frozenset(initial_unprotected_roots)
        for stmt in statements:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                self.owner._bind_import(stmt, env)
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                descriptor = self.owner._register_function(
                    stmt,
                    f"{self.descriptor.display_name}.<locals>.{stmt.name}",
                    nested=True,
                    closure_env=env,
                    closure_guards=active_guards,
                    owner=self.descriptor.identifier,
                )
                env[stmt.name] = _Value(
                    symbols=frozenset({f"function:{descriptor.identifier}"}),
                    roots=frozenset({stmt.name}),
                )
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                if isinstance(stmt.value, ast.Lambda):
                    self._invalidate_conditional_guards(targets)
                    self._invalidate_unprotected_implications(targets)
                    for target in targets:
                        if not isinstance(target, ast.Name):
                            self.owner._bind_target(target, _Value(), env)
                            continue
                        return_node = ast.Return(value=stmt.value.body)
                        ast.copy_location(return_node, stmt.value.body)
                        synthetic = ast.FunctionDef(
                            name=target.id,
                            args=stmt.value.args,
                            body=[return_node],
                            decorator_list=[],
                        )
                        ast.copy_location(synthetic, stmt.value)
                        descriptor = self.owner._register_function(
                            synthetic,
                            (
                                f"{self.descriptor.display_name}.<locals>."
                                f"{target.id}"
                            ),
                            nested=True,
                            closure_env=env,
                            closure_guards=active_guards,
                            owner=self.descriptor.identifier,
                        )
                        env[target.id] = _Value(
                            symbols=frozenset(
                                {f"function:{descriptor.identifier}"}
                            ),
                            roots=frozenset({target.id}),
                        )
                    continue
                self._visit_expr(
                    stmt.value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                value = self._eval_value(stmt.value, env, active_guards)
                self._invalidate_conditional_guards(targets)
                self._invalidate_unprotected_implications(targets)
                for target in targets:
                    self.owner._bind_target(target, value, env)
                continue
            if isinstance(stmt, ast.AugAssign):
                self._visit_expr(
                    stmt.value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                value = _Value.merge(
                    self._eval_value(stmt.target, env, active_guards),
                    self._eval_value(stmt.value, env, active_guards),
                )
                self._invalidate_conditional_guards([stmt.target])
                self._invalidate_unprotected_implications([stmt.target])
                self.owner._bind_target(stmt.target, value, env)
                continue
            if isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Call):
                    guard = self._guard_from_call(stmt.value, env, active_guards)
                    if guard is not None:
                        active_guards = _dedupe_guards((*active_guards, guard))
                        continue
                self._visit_expr(
                    stmt.value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.If):
                self._visit_expr(
                    stmt.test,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                implication = self._fail_closed_unprotected_implication(
                    stmt,
                    env,
                    active_guards,
                )
                condition = ast.dump(stmt.test, include_attributes=False)
                remembered = self.conditional_guard_history.get(condition, ())
                branch_start = _dedupe_guards((*active_guards, *remembered))
                body_unprotected = set(unprotected_roots)
                else_unprotected = set(unprotected_roots)
                selector = _simple_condition_selector(stmt.test)
                if selector is not None:
                    selector_name, positive = selector
                    false_proof = self.unprotected_when_false.get(
                        selector_name,
                        frozenset(),
                    )
                    if positive:
                        else_unprotected.update(false_proof)
                    else:
                        body_unprotected.update(false_proof)
                implications_before = dict(self.unprotected_when_false)
                body_env, body_guards = self._analyze_block(
                    stmt.body,
                    env,
                    branch_start,
                    body_unprotected,
                )
                implications_body = dict(self.unprotected_when_false)
                self.unprotected_when_false = dict(implications_before)
                else_env, _ = self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    else_unprotected,
                )
                implications_else = dict(self.unprotected_when_false)
                self.unprotected_when_false = {
                    name: roots
                    for name, roots in implications_body.items()
                    if implications_else.get(name) == roots
                }
                if implication is not None:
                    proof_selector, proof_roots = implication
                    self.unprotected_when_false[proof_selector] = proof_roots
                for name in set(env) | set(body_env) | set(else_env):
                    before = env.get(name, _Value())
                    body_value = body_env.get(name, before)
                    else_value = else_env.get(name, before)
                    if body_value != before or else_value != before:
                        env[name] = _merge_branch_values(body_value, else_value)
                newly_established = tuple(
                    guard for guard in body_guards if guard not in branch_start
                )
                if newly_established:
                    self.conditional_guard_history[condition] = _dedupe_guards(
                        (*remembered, *newly_established)
                    )
                    self.conditional_guard_dependencies[condition] = {
                        item.id for item in ast.walk(stmt.test) if isinstance(item, ast.Name)
                    }
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor)):
                self._visit_expr(
                    stmt.iter,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                body_env = dict(env)
                self.owner._bind_target(
                    stmt.target,
                    self._eval_value(stmt.iter, env, active_guards),
                    body_env,
                )
                self.repeat_depth += 1
                try:
                    self._analyze_block(
                        stmt.body,
                        body_env,
                        active_guards,
                        unprotected_roots,
                    )
                finally:
                    self.repeat_depth -= 1
                self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.While):
                self._visit_expr(
                    stmt.test,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                self.repeat_depth += 1
                try:
                    self._analyze_block(
                        stmt.body,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                finally:
                    self.repeat_depth -= 1
                self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                body_env = dict(env)
                for item in stmt.items:
                    self._visit_expr(
                        item.context_expr,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                    if item.optional_vars is not None:
                        self.owner._bind_target(
                            item.optional_vars,
                            self._eval_value(item.context_expr, env, active_guards),
                            body_env,
                        )
                self._analyze_block(
                    stmt.body,
                    body_env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.Try):
                self._analyze_block(
                    stmt.body,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                for handler in stmt.handlers:
                    self._analyze_block(
                        handler.body,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                self._analyze_block(
                    stmt.finalbody,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.Match):
                self._visit_expr(
                    stmt.subject,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                for case in stmt.cases:
                    self._analyze_block(
                        case.body,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                continue
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Assert)):
                value = getattr(stmt, "value", None) or getattr(stmt, "exc", None)
                self._visit_expr(
                    value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.expr):
                    self._visit_expr(
                        child,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
        return env, active_guards


def _merge_write_contexts(raw: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    boundary_callsites: dict[str, set[tuple[Any, ...]]] = {}
    for item in raw:
        boundary_id = str(item.get("guarded_write_id") or "")
        if not boundary_id:
            continue
        boundary_callsites.setdefault(boundary_id, set()).add(
            (
                item["path"],
                item["function"],
                item["line"],
                item["column"],
                item["write_method"],
            )
        )
    normalized: list[dict[str, Any]] = []
    for original in raw:
        item = dict(original)
        boundary_id = str(item.get("guarded_write_id") or "")
        if boundary_id and len(boundary_callsites.get(boundary_id, ())) != 1:
            item["guarded_write_individual"] = False
            if item.get("canonical_callback") and item.get("protected_target"):
                item["protection"] = "unprotected"
                item["reason"] = (
                    "one guarded_write callback reaches more than one network mutation"
                )
        normalized.append(item)

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in normalized:
        key = (
            item["path"], item["function"], item["line"], item["column"], item["write_method"]
        )
        grouped.setdefault(key, []).append(item)
    merged: list[dict[str, Any]] = []
    for key in sorted(grouped):
        variants = grouped[key]
        protected_variants = [item for item in variants if item["protected_target"]]
        record = dict(variants[0])
        record["protected_target"] = bool(protected_variants)
        record["protected_repos"] = sorted(
            {repo for item in variants for repo in item["protected_repos"]}
        )
        record["repo_roots"] = sorted({root for item in variants for root in item["repo_roots"]})
        record["analysis_context_count"] = len(variants)
        record["canonical_callback"] = any(
            bool(item.get("canonical_callback")) for item in variants
        )
        record["attested_executor"] = any(
            bool(item.get("attested_executor")) for item in variants
        )
        record["api_primitive_attested"] = any(
            bool(item.get("api_primitive_attested")) for item in variants
        )
        record["api_primitive_exact_call"] = any(
            bool(item.get("api_primitive_exact_call")) for item in variants
        )
        record["prepared_binding_exact"] = any(
            bool(item.get("prepared_binding_exact")) for item in variants
        )
        record["guarded_write_exact_binding"] = any(
            bool(item.get("guarded_write_exact_binding")) for item in variants
        )
        record["guarded_write_individual"] = all(
            bool(item.get("guarded_write_individual"))
            for item in variants
            if item.get("guarded_write_id")
        ) if any(item.get("guarded_write_id") for item in variants) else False
        record["guarded_write_lines"] = sorted(
            {
                int(item.get("guarded_write_line") or 0)
                for item in variants
                if item.get("guarded_write_line")
            }
        )
        record["exact_binding_guard_lines"] = sorted(
            {
                int(line)
                for item in variants
                for line in item.get("exact_binding_guard_lines", [])
            }
        )
        mechanisms = sorted({item["protection"] for item in protected_variants})
        prepared_write_without_authority = bool(
            protected_variants
            and record["path"] == _PUBLISHER_RELPATH
            and str(record["function"]).startswith(
                f"{_PREPARED_EXECUTOR_CLASS}.__call__"
            )
            and not any(
                bool(item.get("canonical_callback"))
                and bool(item.get("attested_executor"))
                for item in protected_variants
            )
        )
        if prepared_write_without_authority:
            mechanisms = sorted({*mechanisms, "unprotected"})
        record["protection_variants"] = mechanisms
        if not protected_variants:
            record["protection"] = "not_a_proven_protected_target"
            record["reason"] = ""
        elif prepared_write_without_authority:
            record["protection"] = "unprotected"
            record["reason"] = (
                "prepared State Laws writer is not reached through the exact "
                "attested preflight-to-prepared authority transition"
            )
        elif "unprotected" in mechanisms:
            record["protection"] = "unprotected"
            record["reason"] = "; ".join(
                sorted({item["reason"] for item in protected_variants if item["reason"]})
            )
        elif len(mechanisms) == 1:
            record["protection"] = mechanisms[0]
            record["reason"] = ""
        else:
            record["protection"] = "+".join(mechanisms)
            record["reason"] = ""
        merged.append(record)
    return merged


def _inventory_from_source_capture(
    source_capture: _PythonSourceCapture,
    *,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
) -> dict[str, Any]:
    protected = {str(item).strip().casefold() for item in protected_repos if str(item).strip()}
    raw_writes: list[dict[str, Any]] = []
    hard_rejections: list[dict[str, Any]] = []
    authority_boundary_violations: list[dict[str, Any]] = []
    syntax_errors: list[dict[str, Any]] = []
    non_executable_sources: list[dict[str, Any]] = []
    for captured_source in source_capture.sources:
        rel = captured_source.path
        payload = captured_source.payload
        try:
            source = payload.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            syntax_errors.append({"path": rel, "error": f"read_error:{type(exc).__name__}"})
            continue
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            non_executable_sources.append(
                {
                    "path": rel,
                    "sha256": captured_source.sha256,
                    "size_bytes": captured_source.size_bytes,
                    "error_type": "SyntaxError",
                    "line": int(exc.lineno or 1),
                    "column": int(exc.offset or 1),
                    "message": str(exc.msg),
                }
            )
            continue
        authority_boundary_violations.extend(
            _authority_boundary_violations(tree, relpath=rel)
        )
        analyzer = _FileAnalyzer(
            path=Path(rel),
            relpath=rel,
            source_text=source,
            tree=tree,
            protected_repos=protected,
            required_runtime=required_runtime,
        )
        if (
            rel == _PUBLISHER_RELPATH
            and _attested_prepared_factory_call(tree) is not None
            and (
                analyzer.preflight_prepare is None
                or analyzer.prepared_executor_call is None
            )
        ):
            authority_boundary_violations.append(
                {
                    "path": rel,
                    "line": int(
                        getattr(
                            next(
                                (
                                    item
                                    for item in tree.body
                                    if isinstance(item, ast.FunctionDef)
                                    and item.name == _PREPARED_CALL_FACTORY
                                ),
                                tree,
                            ),
                            "lineno",
                            0,
                        )
                    ),
                    "symbol": _PREPARED_CALL_FACTORY,
                    "error": "prepared_executor_factory_helpers_not_exact",
                }
            )
        writes, rejections = analyzer.analyze()
        raw_writes.extend(writes)
        hard_rejections.extend(rejections)

    callsites = _merge_write_contexts(raw_writes)
    protected_callsites = [item for item in callsites if item["protected_target"]]
    unprotected = [item for item in protected_callsites if item["protection"] == "unprotected"]
    hard_rejections = [
        dict(item)
        for _, item in sorted(
            {
                (item["path"], item["function"], item["line"]): item
                for item in hard_rejections
            }.items()
        )
    ]
    authority_boundary_violations = [
        dict(item)
        for _, item in sorted(
            {
                (
                    item["path"],
                    item["line"],
                    item["symbol"],
                    item["error"],
                ): item
                for item in authority_boundary_violations
            }.items()
        )
    ]
    reasons = [
        f"{item['path']}:{item['line']} {item['function']} may mutate a protected "
        f"repository via {item['write_method']}: {item['reason']}"
        for item in unprotected
    ]
    if syntax_errors:
        reasons.extend(f"{item['path']} was not audited: {item['error']}" for item in syntax_errors)
    reasons.extend(
        f"{item['path']}:{item['line']} references {item['symbol']}: {item['error']}"
        for item in authority_boundary_violations
    )
    blocked = bool(unprotected or syntax_errors or authority_boundary_violations)
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "source_scope": source_capture.source_scope,
        "required_runtime": required_runtime,
        "protected_repos": sorted(protected),
        "write_methods": sorted(PROTECTED_WRITE_METHODS),
        "read_only_methods_ignored": sorted(_READ_ONLY_METHODS),
        "callsite_count": len(callsites),
        "protected_callsite_count": len(protected_callsites),
        "unprotected_count": len(unprotected),
        "callsites": callsites,
        "unprotected_callsites": unprotected,
        "hard_rejected_functions": hard_rejections,
        "authority_boundary_violations": authority_boundary_violations,
        "non_executable_sources": non_executable_sources,
        "syntax_errors": syntax_errors,
        "authorizing_hub_upload": False,
        "status": "blocked" if blocked else "passed",
        "reasons": reasons,
    }


def capture_mutation_audit(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
    scan_roots: Sequence[Path | str] | None = None,
) -> MutationAuditCapture:
    """Capture source bytes once and derive the report and projection together."""

    source_capture = _capture_python_sources(
        repository_root=repository_root,
        scan_roots=scan_roots,
    )
    report = _inventory_from_source_capture(
        source_capture,
        protected_repos=protected_repos,
        required_runtime=required_runtime,
    )
    return MutationAuditCapture(
        report=report,
        source_projection=_source_projection_from_capture(source_capture),
    )


def inventory_mutation_paths(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
    scan_roots: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    """Compatibility API returning the report from one captured source set."""

    return capture_mutation_audit(
        repository_root=repository_root,
        protected_repos=protected_repos,
        required_runtime=required_runtime,
        scan_roots=scan_roots,
    ).report


def _validate_frozen_mutation_capture(
    capture: MutationAuditCapture,
    *,
    repository_root: Path,
) -> MutationAuditCapture:
    measured = capture.report
    _schema_validate(
        measured,
        repository_root=repository_root,
        label="measured mutation-path audit",
    )
    _check_frozen_report(measured, repository_root=repository_root)
    if (
        measured.get("status") != "passed"
        or measured.get("unprotected_count") != 0
        or measured.get("syntax_errors") != []
        or measured.get("authority_boundary_violations") != []
        or measured.get("authorizing_hub_upload") is not False
    ):
        raise MutationPathAuditError(
            "frozen mutation-path audit is not a non-authorizing, fully "
            "protected passing inventory"
        )
    return capture


def validate_frozen_mutation_capture(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
    scan_roots: Sequence[Path | str] | None = None,
) -> MutationAuditCapture:
    """Return one frozen-validated report/projection source capture."""

    capture = capture_mutation_audit(
        repository_root=repository_root,
        protected_repos=protected_repos,
        required_runtime=required_runtime,
        scan_roots=scan_roots,
    )
    return _validate_frozen_mutation_capture(
        capture,
        repository_root=repository_root,
    )


def validate_frozen_mutation_inventory(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
    scan_roots: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    """Remeasure and exact-compare the protected-write inventory.

    This is the strict, non-writing verifier shared by the release-candidate
    builder and the final publication boundary.  Passing requires both schema
    validity and byte-canonical equality with the committed frozen report.
    """

    capture = validate_frozen_mutation_capture(
        repository_root=repository_root,
        protected_repos=protected_repos,
        required_runtime=required_runtime,
        scan_roots=scan_roots,
    )
    return capture.report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory Hugging Face mutation paths for protected LCR repos"
    )
    parser.add_argument("--protected-repo", action="append", dest="protected_repos", default=[])
    parser.add_argument("--require-runtime", default=CANONICAL_RUNTIME)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--write", action="store_true", help="Write the audit receipt (never a Hub mutation)."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "audit_legal_corpora_hugging_face_mutation_paths: FAILED: --check is required\n"
        )
        return 2
    repos = tuple(args.protected_repos) or tuple(sorted(PROTECTED_REPOS))
    report = inventory_mutation_paths(
        protected_repos=repos, required_runtime=str(args.require_runtime)
    )
    try:
        _schema_validate(
            report,
            repository_root=REPOSITORY_ROOT,
            label="measured mutation-path audit",
        )
        if args.write:
            _write_canonical_report(report, repository_root=REPOSITORY_ROOT)
        _check_frozen_report(report, repository_root=REPOSITORY_ROOT)
    except MutationPathAuditError as exc:
        sys.stderr.write(
            "audit_legal_corpora_hugging_face_mutation_paths: "
            f"FAILED: {exc}\n"
        )
        return 2
    if args.json:
        sys.stdout.write(_canonical_report_text(report))
    else:
        sys.stdout.write(
            "audit_legal_corpora_hugging_face_mutation_paths: "
            f"{report['status'].upper()} unprotected={report['unprotected_count']} "
            f"callsites={report['callsite_count']}\n"
        )
        for reason in report["reasons"][:12]:
            sys.stderr.write(f"  {reason}\n")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
