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

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]

SOURCE_RECONCILIATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.source-reconciled-baseline.v1"
)
OUTPUT_NORMALIZATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.a0-normalized-pilot-output.v1"
)
REASSESSMENT_RUN_ID: Final = "reassessment-v2"
REASSESSMENT_BASELINE_ID: Final = "a0-current-effective-v2"
DEFAULT_RECONCILED_MANIFEST_PATH: Final = (
    DEFAULT_BENCHMARK_ROOT
    / REASSESSMENT_RUN_ID
    / "state"
    / "baseline-manifest.json"
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

_HEX_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|credential|password|private[_-]?key|secret|token)"
    r"(?:$|[_-])",
    re.IGNORECASE,
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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


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
    )
    return head, branch, _sha256_bytes(status.encode("utf-8"))


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


def _redact_safe_inventory(value: object, field: str = "environment") -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in sorted(value.items()):
            if not isinstance(key, str):
                raise SourceReconciliationError(f"{field} keys must be strings")
            if _SECRET_KEY.search(key):
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


def validate_reconciled_manifest_payload(value: object) -> None:
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
    if (
        payload["benchmark_id"] != BENCHMARK_ID
        or payload["baseline_id"] != REASSESSMENT_BASELINE_ID
        or payload["run_id"] != REASSESSMENT_RUN_ID
    ):
        raise SourceReconciliationError("v2 baseline identity drifted")
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
        environment["run_id"] != REASSESSMENT_RUN_ID
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
            record["run_id"] != REASSESSMENT_RUN_ID
            or record["variant_id"] != "A0"
            or record["split"] != "pilot"
        ):
            raise SourceReconciliationError("v2 run contract drifted")
        if not isinstance(record["cache_mode"], str):
            raise SourceReconciliationError("cache mode is invalid")
        if not isinstance(record["cache_namespace"], str):
            raise SourceReconciliationError("cache namespace is invalid")
        modes.append(record["cache_mode"])
        contract_namespaces.append(record["cache_namespace"])
    if modes != ["cold", "warm"] or len(set(contract_namespaces)) != 2:
        raise SourceReconciliationError("cold/warm contracts are not isolated")

    _validate_namespaces(payload["namespaces"], REASSESSMENT_RUN_ID)
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
) -> SourceReconciledBaselineManifest:
    """Strictly load a canonical v2 reconciliation manifest."""

    manifest_path = Path(path)
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
    actual_gitlinks = capture_recursive_gitlinks(
        REPOSITORY_ROOT,
        commit,
        require_complete=False,
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


def write_reconciled_baseline_manifest(
    manifest: SourceReconciledBaselineManifest,
    path: str | Path = DEFAULT_RECONCILED_MANIFEST_PATH,
) -> Path:
    """Write a v2 manifest once, without overwriting any existing evidence."""

    if not isinstance(manifest, SourceReconciledBaselineManifest):
        raise TypeError("manifest must be a SourceReconciledBaselineManifest")
    destination = Path(path)
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
    output_path: str | Path = DEFAULT_RECONCILED_MANIFEST_PATH,
) -> SourceReconciledBaselineManifest:
    """Create a detached, behavior-equivalent v2 baseline receipt.

    Submodule initialization is local-only (``--no-fetch``).  Missing objects
    fail rather than opening the network or accepting a partial recursive
    inventory.
    """

    source = Path(source_checkout).resolve()
    if run_paths.run_id != REASSESSMENT_RUN_ID:
        raise SourceReconciliationError(
            f"reconciliation run_id must be {REASSESSMENT_RUN_ID!r}"
        )
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
    destination = Path(output_path)
    if not destination.is_absolute():
        destination = source / destination
    write_reconciled_baseline_manifest(manifest, destination)
    after = _artifact_snapshot(frozen_paths)
    if after != before:
        raise SourceReconciliationError(
            "a predecessor v1 artifact changed during reconciliation"
        )
    return manifest


__all__ = [
    "DEFAULT_RECONCILED_MANIFEST_PATH",
    "DEFAULT_IMMUTABLE_V1_ARTIFACT_PATHS",
    "FROZEN_NORMALIZED_A0_PILOT_SHA256",
    "GitlinkIdentity",
    "HSSLEV1134D84",
    "OUTPUT_NORMALIZATION_SCHEMA",
    "REASSESSMENT_BASELINE_ID",
    "REASSESSMENT_RUN_ID",
    "SOURCE_RECONCILIATION_SCHEMA",
    "SourceReconciledBaselineManifest",
    "SourceReconciliationError",
    "build_run_namespaces",
    "canonical_reconciled_baseline_json",
    "capture_recursive_gitlinks",
    "compare_a0_outputs",
    "environment_inventory_record",
    "load_reconciled_baseline_manifest",
    "normalize_a0_outputs",
    "reconciled_baseline_sha256",
    "reconcile_source",
    "validate_reconciled_manifest_payload",
    "write_reconciled_baseline_manifest",
]
