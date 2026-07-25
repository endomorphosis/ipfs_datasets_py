"""Fresh detached-worktree replay orchestration.

Semantic replay comparison already lives in :mod:`benchmarks.logic_pipeline.report`.
This module owns the missing operational boundary: validate the source evidence,
allocate a genuinely new run/process/cache namespace, create a detached worktree
at the exact source commit, execute without a shell in a new process session,
and authenticate the resulting evidence before publishing a write-once receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
from typing import Final, Mapping, Sequence

from . import RunPaths
from .capabilities import (
    WorktreeSafetyReceipt,
    _active_process_group_members,
    _reap_bounded_process_group,
    prepare_isolated_worktree,
)
from .contracts import (
    CacheMode,
    CaseResultRecord,
    RunContract,
    canonical_json,
)
from .holdout_execution import (
    HSSLEV1167A17,
    HoldoutExecutionReceipt,
)
from .report import ReplayValidationRecord, validate_replay
from .source_reconciliation import (
    GitlinkIdentity,
    SourceReconciliationError,
    _capture_benchmark_bounded_gitlinks,
    _materialize_recursive_local_gitlinks,
    _validate_live_detached_source,
)


REPLAY_REQUEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.detached-replay-request.v1"
)
REPLAY_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.detached-replay-receipt.v1"
)
REPLAY_RECEIPT_FILE: Final = "detached-replay-receipt.json"
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DIGEST: Final = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_MAX_OUTPUT_BYTES: Final = 1024 * 1024


class ReplayError(ValueError):
    """Raised when replay provenance or isolation fails closed."""


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ReplayError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _commit(value: object, field: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ReplayError(f"{field} must be a full lowercase Git commit id")
    return value


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ReplayError(f"{field} must be a safe nonempty identifier")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ReplayError(f"{field} must be an object with string keys")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    if set(value) != expected:
        raise ReplayError(f"{field} fields changed")


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _relative_path(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ReplayError(f"{field} must be a relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReplayError(f"{field} must not be absolute or traverse")
    return path.as_posix()


def _request_payload(
    *,
    schema: str,
    source_run_id: str,
    replay_run_id: str,
    source_commit: str,
    environment_sha256: str,
    source_execution_receipt_sha256: str,
    source_worktree_receipt_sha256: str,
    source_process_namespace: str,
    replay_process_namespace: str,
    source_cache_namespaces: tuple[str, ...],
    replay_cache_namespace: str,
    command: tuple[str, ...],
    evidence_relative_path: str,
    timeout_seconds: float,
) -> dict[str, object]:
    return {
        "schema": schema,
        "source_run_id": source_run_id,
        "replay_run_id": replay_run_id,
        "source_commit": source_commit,
        "environment_sha256": environment_sha256,
        "source_execution_receipt_sha256": source_execution_receipt_sha256,
        "source_worktree_receipt_sha256": source_worktree_receipt_sha256,
        "source_process_namespace": source_process_namespace,
        "replay_process_namespace": replay_process_namespace,
        "source_cache_namespaces": list(source_cache_namespaces),
        "replay_cache_namespace": replay_cache_namespace,
        "command": list(command),
        "evidence_relative_path": evidence_relative_path,
        "timeout_seconds": timeout_seconds,
    }


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """Immutable request for one source-bound cold replay."""

    schema: str
    source_run_id: str
    replay_run_id: str
    source_commit: str
    environment_sha256: str
    source_execution_receipt_sha256: str
    source_worktree_receipt_sha256: str
    source_process_namespace: str
    replay_process_namespace: str
    source_cache_namespaces: tuple[str, ...]
    replay_cache_namespace: str
    command: tuple[str, ...]
    evidence_relative_path: str
    timeout_seconds: float
    request_sha256: str

    def __post_init__(self) -> None:
        if self.schema != REPLAY_REQUEST_SCHEMA:
            raise ReplayError("unsupported replay request schema")
        _safe_id(self.source_run_id, "source_run_id")
        _safe_id(self.replay_run_id, "replay_run_id")
        if self.source_run_id == self.replay_run_id:
            raise ReplayError("replay must use a fresh run id")
        _commit(self.source_commit, "source_commit")
        for name in (
            "environment_sha256",
            "source_execution_receipt_sha256",
            "source_worktree_receipt_sha256",
            "request_sha256",
        ):
            _digest(getattr(self, name), name)
        _safe_id(self.source_process_namespace, "source_process_namespace")
        _safe_id(self.replay_process_namespace, "replay_process_namespace")
        if self.source_process_namespace == self.replay_process_namespace:
            raise ReplayError("replay must use a fresh process namespace")
        caches = tuple(self.source_cache_namespaces)
        if (
            not caches
            or len(caches) != len(set(caches))
            or any(not isinstance(item, str) or not item for item in caches)
        ):
            raise ReplayError(
                "source_cache_namespaces must be distinct and nonempty"
            )
        object.__setattr__(self, "source_cache_namespaces", caches)
        if (
            not isinstance(self.replay_cache_namespace, str)
            or f"/run/{self.replay_run_id}/" not in self.replay_cache_namespace
            or not self.replay_cache_namespace.endswith("/cache/cold")
            or self.replay_cache_namespace in caches
        ):
            raise ReplayError(
                "replay cache must be a fresh replay-run cold namespace"
            )
        command = tuple(self.command)
        if (
            not command
            or any(
                not isinstance(item, str) or not item or "\0" in item
                for item in command
            )
        ):
            raise ReplayError("command must contain nonempty NUL-free arguments")
        object.__setattr__(self, "command", command)
        object.__setattr__(
            self,
            "evidence_relative_path",
            _relative_path(
                self.evidence_relative_path, "evidence_relative_path"
            ),
        )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < float(self.timeout_seconds) <= 86_400
        ):
            raise ReplayError("timeout_seconds must be from 0 to 86400")
        if self.request_sha256 != _sha(self.identity_payload()):
            raise ReplayError("request_sha256 does not match replay request")

    def identity_payload(self) -> dict[str, object]:
        return _request_payload(
            schema=self.schema,
            source_run_id=self.source_run_id,
            replay_run_id=self.replay_run_id,
            source_commit=self.source_commit,
            environment_sha256=self.environment_sha256,
            source_execution_receipt_sha256=(
                self.source_execution_receipt_sha256
            ),
            source_worktree_receipt_sha256=(
                self.source_worktree_receipt_sha256
            ),
            source_process_namespace=self.source_process_namespace,
            replay_process_namespace=self.replay_process_namespace,
            source_cache_namespaces=self.source_cache_namespaces,
            replay_cache_namespace=self.replay_cache_namespace,
            command=self.command,
            evidence_relative_path=self.evidence_relative_path,
            timeout_seconds=float(self.timeout_seconds),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "request_sha256": self.request_sha256}

    @classmethod
    def create(
        cls,
        *,
        source_run_id: str,
        replay_run_id: str,
        source_commit: str,
        environment_sha256: str,
        source_execution_receipt_sha256: str,
        source_worktree_receipt_sha256: str,
        source_process_namespace: str,
        replay_process_namespace: str,
        source_cache_namespaces: Sequence[str],
        replay_cache_namespace: str,
        command: Sequence[str],
        evidence_relative_path: str = "results/replay-evidence.json",
        timeout_seconds: float = 300.0,
    ) -> "ReplayRequest":
        payload = _request_payload(
            schema=REPLAY_REQUEST_SCHEMA,
            source_run_id=source_run_id,
            replay_run_id=replay_run_id,
            source_commit=source_commit,
            environment_sha256=environment_sha256,
            source_execution_receipt_sha256=(
                source_execution_receipt_sha256
            ),
            source_worktree_receipt_sha256=source_worktree_receipt_sha256,
            source_process_namespace=source_process_namespace,
            replay_process_namespace=replay_process_namespace,
            source_cache_namespaces=tuple(source_cache_namespaces),
            replay_cache_namespace=replay_cache_namespace,
            command=tuple(command),
            evidence_relative_path=evidence_relative_path,
            timeout_seconds=float(timeout_seconds),
        )
        return cls(**payload, request_sha256=_sha(payload))  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, value: object) -> "ReplayRequest":
        data = _mapping(value, "replay request")
        _exact(data, set(cls.__dataclass_fields__), "replay request")
        for name in ("source_cache_namespaces", "command"):
            if not isinstance(data[name], list):
                raise ReplayError(f"{name} must be an array")
        return cls(
            **{
                name: (
                    tuple(data[name]) if isinstance(data[name], list) else data[name]
                )
                for name in cls.__dataclass_fields__
            }  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ReplayReceipt:
    """Write-once proof of one successful isolated replay process."""

    schema: str
    evidence: str
    request_sha256: str
    source_execution_receipt_sha256: str
    source_worktree_receipt_sha256: str
    replay_worktree_receipt_sha256: str
    source_run_id: str
    replay_run_id: str
    source_commit: str
    environment_sha256: str
    process_namespace: str
    cache_namespace: str
    evidence_sha256: str
    stdout_sha256: str
    stderr_sha256: str
    exit_code: int
    detached: bool
    auto_merge: bool
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.schema != REPLAY_RECEIPT_SCHEMA:
            raise ReplayError("unsupported replay receipt schema")
        if self.evidence != HSSLEV1167A17():
            raise ReplayError("replay evidence marker changed")
        _safe_id(self.source_run_id, "source_run_id")
        _safe_id(self.replay_run_id, "replay_run_id")
        if self.source_run_id == self.replay_run_id:
            raise ReplayError("replay receipt reused the source run")
        _commit(self.source_commit, "source_commit")
        _safe_id(self.process_namespace, "process_namespace")
        for name in (
            "request_sha256",
            "source_execution_receipt_sha256",
            "source_worktree_receipt_sha256",
            "replay_worktree_receipt_sha256",
            "environment_sha256",
            "evidence_sha256",
            "stdout_sha256",
            "stderr_sha256",
            "receipt_sha256",
        ):
            _digest(getattr(self, name), name)
        if (
            not isinstance(self.cache_namespace, str)
            or f"/run/{self.replay_run_id}/" not in self.cache_namespace
            or not self.cache_namespace.endswith("/cache/cold")
        ):
            raise ReplayError("receipt cache is not a replay-run cold namespace")
        if self.exit_code != 0:
            raise ReplayError("successful replay receipt requires exit_code zero")
        if self.detached is not True or self.auto_merge is not False:
            raise ReplayError("replay must remain detached with auto-merge disabled")
        if self.receipt_sha256 != _sha(self.identity_payload()):
            raise ReplayError("replay receipt digest changed")

    def identity_payload(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "receipt_sha256"
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> "ReplayReceipt":
        data = _mapping(value, "replay receipt")
        _exact(data, set(cls.__dataclass_fields__), "replay receipt")
        return cls(**data)  # type: ignore[arg-type]


def _git_value(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env={
                "PATH": os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReplayError("cannot validate replay worktree") from exc
    return result.stdout.strip()


def _validate_live_worktree(
    receipt: WorktreeSafetyReceipt,
    expected_commit: str,
    expected_gitlinks: Sequence[GitlinkIdentity],
) -> None:
    expected = tuple(expected_gitlinks)
    expected_top_level = {
        item.path: item.commit for item in expected if item.depth == 1
    }
    if dict(receipt.submodule_commits) != expected_top_level:
        raise ReplayError(
            "replay worktree receipt gitlinks differ from the pinned inventory"
        )
    try:
        actual = _capture_benchmark_bounded_gitlinks(
            receipt.worktree_root,
            expected_commit,
        )
        if actual != expected:
            raise ReplayError(
                "replay worktree recursive gitlink inventory drifted"
            )
        _validate_live_detached_source(
            receipt.worktree_root,
            commit=expected_commit,
            gitlinks=expected,
        )
        porcelain = _git_value(
            receipt.worktree_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
    except SourceReconciliationError as exc:
        raise ReplayError(
            "replay worktree or a pinned submodule is stale or dirty"
        ) from exc
    if porcelain:
        raise ReplayError(
            "replay worktree or a pinned submodule is not clean"
        )


def _evidence_path(run_paths: RunPaths, relative_path: str) -> Path:
    path = run_paths.run_root.joinpath(*PurePosixPath(relative_path).parts)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(run_paths.run_root.resolve(strict=False)):
        raise ReplayError("replay evidence path escaped the run namespace")
    return path


def _read_evidence(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ReplayError("replay evidence must be a regular non-symlink file")
        data = path.read_bytes()
    except OSError as exc:
        raise ReplayError("replay command did not produce evidence") from exc
    if not data or len(data) > 64 * 1024 * 1024:
        raise ReplayError("replay evidence size is outside the safe bound")
    return data


def _run_process(
    request: ReplayRequest,
    *,
    worktree: Path,
    run_paths: RunPaths,
    evidence_path: Path,
    environment: Mapping[str, str] | None,
) -> tuple[bytes, bytes]:
    extra = {} if environment is None else dict(environment)
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\0" in key
        or "\0" in value
        for key, value in extra.items()
    ):
        raise ReplayError("replay environment must contain NUL-free strings")
    process_environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        **extra,
        "HSSL_REPLAY": "1",
        "HSSL_RUN_ID": request.replay_run_id,
        "HSSL_RUN_ROOT": run_paths.run_root.as_posix(),
        "HSSL_PROCESS_NAMESPACE": request.replay_process_namespace,
        "HSSL_CACHE_NAMESPACE": request.replay_cache_namespace,
        "HSSL_REPLAY_EVIDENCE_PATH": evidence_path.as_posix(),
    }
    try:
        process = subprocess.Popen(
            list(request.command),
            cwd=worktree,
            env=process_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise ReplayError("cannot start detached replay process") from exc

    timed_out: subprocess.TimeoutExpired | None = None
    communication_error: OSError | None = None
    stdout = b""
    stderr = b""
    try:
        try:
            stdout, stderr = process.communicate(
                timeout=request.timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = exc
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (AttributeError, ProcessLookupError, PermissionError):
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (
                    AttributeError,
                    ProcessLookupError,
                    PermissionError,
                ):
                    process.kill()
                stdout, stderr = process.communicate()
    except OSError as exc:
        communication_error = exc
    finally:
        surviving_descendants = bool(
            _active_process_group_members(process.pid)
        )
        process_group_reaped = _reap_bounded_process_group(
            process.pid,
            cancellation_grace_seconds=2.0,
        )
        if process.poll() is None:
            process.kill()
            process.communicate()
        process_group_reaped = (
            process_group_reaped
            and _reap_bounded_process_group(
                process.pid,
                cancellation_grace_seconds=2.0,
            )
        )
    if not process_group_reaped:
        raise ReplayError(
            "detached replay process group could not be fully reaped"
        )
    if communication_error is not None:
        raise ReplayError(
            "detached replay process communication failed"
        ) from communication_error
    if timed_out is not None:
        raise ReplayError("detached replay exceeded its timeout") from timed_out
    if surviving_descendants:
        raise ReplayError(
            "detached replay left a lingering process-group member"
        )
    if len(stdout) > _MAX_OUTPUT_BYTES or len(stderr) > _MAX_OUTPUT_BYTES:
        raise ReplayError("detached replay output exceeded the retained bound")
    if process.returncode != 0:
        raise ReplayError(
            f"detached replay command failed with exit code {process.returncode}"
        )
    return stdout, stderr


def run_detached_replay(
    source_checkout: str | Path,
    source_execution_receipt: HoldoutExecutionReceipt,
    source_worktree_receipt: WorktreeSafetyReceipt,
    request: ReplayRequest,
    *,
    benchmark_root: str | Path,
    actual_environment_sha256: str,
    environment: Mapping[str, str] | None = None,
) -> tuple[ReplayReceipt, WorktreeSafetyReceipt]:
    """Run one authenticated replay in a fresh pinned detached worktree."""

    try:
        source_execution = HoldoutExecutionReceipt.from_dict(
            source_execution_receipt.to_dict()
        )
        source_worktree = WorktreeSafetyReceipt.from_dict(
            source_worktree_receipt.to_dict()
        )
        request = ReplayRequest.from_dict(request.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReplayError("source replay evidence is invalid or tampered") from exc
    if (
        request.source_execution_receipt_sha256
        != source_execution.receipt_sha256
        or request.source_worktree_receipt_sha256 != source_worktree.sha256
        or request.source_run_id != source_execution.run_id
        or request.source_run_id != source_worktree.run_id
        or request.source_commit != source_execution.source_commit
        or request.source_commit != source_worktree.worktree_commit
        or request.environment_sha256 != source_execution.environment_sha256
        or _digest(
            actual_environment_sha256, "actual_environment_sha256"
        )
        != request.environment_sha256
        or set(request.source_cache_namespaces)
        != set(source_execution.cache_namespaces)
    ):
        raise ReplayError(
            "source receipt, commit, environment, or cache identity is stale"
        )
    requested_source = Path(source_checkout).resolve()
    if source_worktree.source_checkout != requested_source:
        raise ReplayError("source worktree receipt belongs to another checkout")
    try:
        expected_gitlinks = _capture_benchmark_bounded_gitlinks(
            requested_source,
            request.source_commit,
        )
    except SourceReconciliationError as exc:
        raise ReplayError(
            "cannot bind the pinned local recursive gitlink inventory"
        ) from exc
    _validate_live_worktree(
        source_worktree,
        request.source_commit,
        expected_gitlinks,
    )
    run_paths = RunPaths.for_run(
        request.replay_run_id, benchmark_root=benchmark_root
    )
    if run_paths.run_root.exists() or run_paths.run_root.is_symlink():
        raise ReplayError("replay run namespace already exists")
    evidence_path = _evidence_path(
        run_paths, request.evidence_relative_path
    )

    # Every validation above is deliberately complete before this first write.
    replay_worktree = prepare_isolated_worktree(
        source_checkout,
        run_paths=run_paths,
        base_revision=request.source_commit,
    )
    try:
        _materialize_recursive_local_gitlinks(
            requested_source,
            replay_worktree.worktree_root,
            tuple(
                item for item in expected_gitlinks if item.depth == 1
            ),
        )
    except SourceReconciliationError as exc:
        raise ReplayError(
            "cannot materialize pinned submodules from local repositories"
        ) from exc
    _validate_live_worktree(
        replay_worktree,
        request.source_commit,
        expected_gitlinks,
    )
    evidence_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        stdout, stderr = _run_process(
            request,
            worktree=replay_worktree.worktree_root,
            run_paths=run_paths,
            evidence_path=evidence_path,
            environment=environment,
        )
    finally:
        _validate_live_worktree(
            replay_worktree,
            request.source_commit,
            expected_gitlinks,
        )
    evidence = _read_evidence(evidence_path)
    payload = {
        "schema": REPLAY_RECEIPT_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "request_sha256": request.request_sha256,
        "source_execution_receipt_sha256": (
            source_execution.receipt_sha256
        ),
        "source_worktree_receipt_sha256": source_worktree.sha256,
        "replay_worktree_receipt_sha256": replay_worktree.sha256,
        "source_run_id": request.source_run_id,
        "replay_run_id": request.replay_run_id,
        "source_commit": request.source_commit,
        "environment_sha256": request.environment_sha256,
        "process_namespace": request.replay_process_namespace,
        "cache_namespace": request.replay_cache_namespace,
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "exit_code": 0,
        "detached": replay_worktree.detached,
        "auto_merge": replay_worktree.auto_merge,
    }
    receipt = ReplayReceipt(
        **payload,  # type: ignore[arg-type]
        receipt_sha256=_sha(payload),
    )
    receipt_path = run_paths.receipts / REPLAY_RECEIPT_FILE
    try:
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(receipt.to_dict()))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ReplayError("refusing to overwrite detached replay receipt") from exc
    return receipt, replay_worktree


def validate_detached_replay_pair(
    original: CaseResultRecord,
    replayed: CaseResultRecord,
    *,
    original_contract: RunContract,
    replay_contract: RunContract,
    replay_receipt: ReplayReceipt,
    worktree_receipt: WorktreeSafetyReceipt,
) -> ReplayValidationRecord:
    """Compose orchestration proof with the existing semantic replay validator."""

    receipt = ReplayReceipt.from_dict(replay_receipt.to_dict())
    worktree = WorktreeSafetyReceipt.from_dict(worktree_receipt.to_dict())
    if (
        receipt.replay_run_id != replayed.run_id
        or receipt.replay_worktree_receipt_sha256 != worktree.sha256
        or receipt.cache_namespace != replay_contract.cache_namespace
        or replay_contract.cache_mode is not CacheMode.COLD
    ):
        raise ReplayError(
            "semantic replay records do not match orchestration receipt"
        )
    return validate_replay(
        original,
        replayed,
        original_contract=original_contract,
        replay_contract=replay_contract,
        expected_environment_sha256=receipt.environment_sha256,
        worktree_receipt=worktree,
        expected_source_commit=receipt.source_commit,
    )


__all__ = [
    "REPLAY_RECEIPT_FILE",
    "REPLAY_RECEIPT_SCHEMA",
    "REPLAY_REQUEST_SCHEMA",
    "ReplayError",
    "ReplayReceipt",
    "ReplayRequest",
    "run_detached_replay",
    "validate_detached_replay_pair",
]
