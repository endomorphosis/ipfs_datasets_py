"""Fresh detached-worktree replay orchestration.

Semantic replay comparison already lives in :mod:`benchmarks.logic_pipeline.report`.
This module owns the missing operational boundary: validate the source evidence,
allocate a genuinely new run/process/cache namespace, create a detached worktree
at the exact source commit, execute without a shell in a new process session,
and authenticate the resulting evidence before publishing a write-once receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
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
    _close_process_standard_streams,
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
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    validate_cid,
)
from .replay_gate import (
    G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2,
    G238_FAILURE_SAMPLE_PER_STRATUM,
    G238_GIT_COMMIT_IDENTITY_SCHEMA_V2,
    G238_REPLAY_GATE_SCHEMA_V2,
    G238_REPLAY_POLICY_SCHEMA_V2,
    G238_REPLAY_POLICY_V2_CID,
    G238_REPLAY_SOURCE_INDEX_SCHEMA_V2,
    G238_REPLAY_SOURCE_RECORD_SCHEMA_V2,
    G238DetachedReplayReceiptV2,
    G238ReplaySourceIndexV2,
    G238ReplaySourceRecordV2,
    FreshReplayGateError,
    HSSLEV2381F50,
    build_g238_detached_replay_gate_v2,
    g238_git_commit_cid,
    validate_g238_detached_replay_gate_v2,
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


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise ReplayError(f"duplicate replay JSON key: {key}")
        value[key] = member
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
    execution_request_cid: str | None,
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
        "execution_request_cid": execution_request_cid,
    }


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """Immutable request for one source-bound cold or warm replay."""

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
    execution_request_cid: str | None
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
        if self.execution_request_cid is not None:
            try:
                object.__setattr__(
                    self,
                    "execution_request_cid",
                    validate_cid(
                        self.execution_request_cid,
                        codecs=("dag-json",),
                    ),
                )
            except (TypeError, ValueError) as exc:
                raise ReplayError(
                    "execution_request_cid must be a canonical DAG-JSON CID"
                ) from exc
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
            or not self.replay_cache_namespace.endswith(
                ("/cache/cold", "/cache/warm")
            )
            or self.replay_cache_namespace in caches
        ):
            raise ReplayError(
                "replay cache must be a fresh replay-run cold/warm namespace"
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
            execution_request_cid=self.execution_request_cid,
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
        execution_request_cid: str | None = None,
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
            execution_request_cid=execution_request_cid,
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
    _process_observation: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _g240_private_execution_sources: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )

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
            or not self.cache_namespace.endswith(
                ("/cache/cold", "/cache/warm")
            )
        ):
            raise ReplayError(
                "receipt cache is not a replay-run cold/warm namespace"
            )
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
            if name
            not in {
                "receipt_sha256",
                "_process_observation",
                "_g240_private_execution_sources",
            }
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> "ReplayReceipt":
        data = _mapping(value, "replay receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__)
            - {
                "_process_observation",
                "_g240_private_execution_sources",
            },
            "replay receipt",
        )
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
            "--ignore-submodules=all",
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


def _write_private_canonical_json(
    path: Path,
    value: object,
    *,
    parent: Path,
) -> bytes:
    """Exclusively persist one private canonical process input."""

    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(parent.resolve(strict=True)):
        raise ReplayError("G240 private request path escaped its state namespace")
    payload = canonical_dag_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ReplayError(
            "cannot exclusively persist G240 private execution request"
        ) from exc
    return payload


def _validate_private_namespace_directory(
    path: Path,
    *,
    run_root: Path,
) -> None:
    """Require one extant private directory below the replay run root."""

    lexical = path.absolute()
    root = run_root.absolute()
    if not lexical.is_relative_to(root):
        raise ReplayError("G240 physical namespace escaped the run root")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ReplayError("G240 physical namespace disappeared") from exc
    if (
        stat.S_ISLNK(mode)
        or not stat.S_ISDIR(mode)
        or stat.S_IMODE(mode) & 0o077
    ):
        raise ReplayError(
            "G240 physical namespace is not a private real directory"
        )


def _coerce_g240_executor_contract_v2(
    value: object,
    *,
    source_policy: object,
):
    """Restore the exact source executor contract frozen by G240 policy."""

    from .namespace_provenance import G240NamespacePolicyV2
    from .source_bootstrap_contract import (
        G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2,
    )
    from .source_orchestration import (
        G240SourceExecutorContractV2,
        _g240_launch_arguments,
    )

    try:
        policy = (
            source_policy
            if isinstance(source_policy, G240NamespacePolicyV2)
            else G240NamespacePolicyV2.from_dict(source_policy)
        )
        contract = (
            value
            if isinstance(value, G240SourceExecutorContractV2)
            else G240SourceExecutorContractV2.from_dict(value)
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 replay executor contract failed typed validation"
        ) from exc
    if (
        contract.contract_cid
        != policy.runtime_orchestration_policy_cid
        or contract.environment_cid != policy.environment_cid
    ):
        raise ReplayError(
            "G240 replay executor contract differs from the frozen policy"
        )
    if (
        contract.entrypoint_kind != "repository-script"
        or contract.command_template
        != G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2
    ):
        raise ReplayError(
            "G240 replay requires the tracked production G240 source "
            "executor"
        )
    _g240_launch_arguments(contract)
    return G240SourceExecutorContractV2.from_dict(contract.to_dict())


def _g240_tracked_entrypoint_bytes(
    worktree: WorktreeSafetyReceipt,
    relative_path: str,
) -> bytes | None:
    """Read one regular entrypoint exactly as pinned by the worktree commit."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(worktree.worktree_root),
                "show",
                f"{worktree.worktree_commit}:{relative_path}",
            ],
            check=False,
            capture_output=True,
            timeout=20,
            env={
                "PATH": os.environ.get("PATH", ""),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReplayError(
            "cannot inspect the G240 replay executor Git object"
        ) from exc
    if result.returncode != 0:
        return None
    entrypoint = worktree.worktree_root / relative_path
    try:
        mode = entrypoint.lstat().st_mode
        observed = entrypoint.read_bytes()
    except OSError as exc:
        raise ReplayError(
            "G240 replay executor entrypoint is absent from the worktree"
        ) from exc
    if (
        stat.S_ISLNK(mode)
        or not stat.S_ISREG(mode)
        or observed != result.stdout
    ):
        raise ReplayError(
            "G240 replay executor entrypoint differs from its pinned Git object"
        )
    return observed


def _validate_g240_executor_entrypoint_v2(
    executor_contract: object,
    worktree: WorktreeSafetyReceipt,
) -> tuple[str, bytes]:
    """Authenticate the contract entrypoint in one live detached worktree."""

    from .source_bootstrap_contract import (
        G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2,
    )
    from .source_orchestration import (
        G240SourceExecutorContractV2,
        _g240_launch_arguments,
    )

    try:
        contract = (
            executor_contract
            if isinstance(
                executor_contract,
                G240SourceExecutorContractV2,
            )
            else G240SourceExecutorContractV2.from_dict(
                executor_contract
            )
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 replay executor contract failed typed validation"
        ) from exc
    if (
        contract.entrypoint_kind != "repository-script"
        or contract.command_template
        != G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2
    ):
        raise ReplayError(
            "G240 replay requires the tracked production G240 source "
            "executor"
        )
    _g240_launch_arguments(contract)
    relative_path = contract.command_template[1]
    payload = _g240_tracked_entrypoint_bytes(
        worktree,
        relative_path,
    )
    if payload is None:
        raise ReplayError(
            "G240 replay bootstrap entrypoint is absent from Git"
        )
    return relative_path, payload


_REPLAY_PROCESS_CAPABILITY_V2: Final = object()
_G240_REPLAY_LANDLOCK_TRANSPORT_CAPABILITY_V2: Final = object()
_G240_REPLAY_PRIVATE_EXECUTION_CAPABILITY_V2: Final = object()
_G240_MAX_LANDLOCK_RECEIPT_BYTES_V2: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class _ReplayProcessObservationV2:
    """Private, non-serializable witness emitted only by ``_run_process``."""

    arguments: tuple[str, ...]
    stdout: bytes
    stderr: bytes
    returncode: int
    process_group_started: bool
    process_group_reaped: bool
    active_process_count_after_reap: int
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._capability is not _REPLAY_PROCESS_CAPABILITY_V2
            or not self.arguments
            or not isinstance(self.stdout, bytes)
            or not isinstance(self.stderr, bytes)
            or self.returncode != 0
            or self.process_group_started is not True
            or self.process_group_reaped is not True
            or self.active_process_count_after_reap != 0
        ):
            raise ReplayError(
                "replay process observation lacks live successful authority"
            )


@dataclass(frozen=True, slots=True)
class _G240ReplayLandlockTransportObservationV2:
    """Private join between one replay process and its receipt pipe."""

    process_observation: _ReplayProcessObservationV2
    policy_sources: object
    receipt: object
    receipt_payload: bytes
    close_fds: bool
    passed_descriptor_count: int
    one_shot_atomic_frame: bool
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        from .runtime_confinement import (
            G240LandlockPrivatePolicySourcesV1,
            G240LandlockReceiptV1,
            validate_g240_landlock_receipt_v1,
        )

        if (
            self._capability
            is not _G240_REPLAY_LANDLOCK_TRANSPORT_CAPABILITY_V2
            or not isinstance(
                self.process_observation,
                _ReplayProcessObservationV2,
            )
            or self.process_observation._capability
            is not _REPLAY_PROCESS_CAPABILITY_V2
            or not isinstance(
                self.policy_sources,
                G240LandlockPrivatePolicySourcesV1,
            )
            or not isinstance(self.receipt, G240LandlockReceiptV1)
            or not isinstance(self.receipt_payload, bytes)
            or self.close_fds is not True
            or self.passed_descriptor_count != 1
            or self.one_shot_atomic_frame is not True
        ):
            raise ReplayError(
                "G240 replay Landlock transport lacks live process authority"
            )
        receipt = validate_g240_landlock_receipt_v1(
            self.receipt,
            expected_policy=self.policy_sources.policy,
        )
        if self.receipt_payload != (
            canonical_dag_json_bytes(receipt.to_dict()) + b"\n"
        ):
            raise ReplayError(
                "G240 replay Landlock receipt differs from its pipe bytes"
            )


@dataclass(frozen=True, slots=True)
class _G240ReplayPrivateExecutionSourcesV2:
    """Capability-bearing inputs retained only by the live replay receipt."""

    execution_request: object
    execution_request_payload: bytes
    runtime_preflight_payload: bytes
    landlock_transport_observation: (
        _G240ReplayLandlockTransportObservationV2 | None
    )
    synthetic_test_only: bool
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._capability
            is not _G240_REPLAY_PRIVATE_EXECUTION_CAPABILITY_V2
            or not isinstance(self.execution_request_payload, bytes)
            or not isinstance(self.runtime_preflight_payload, bytes)
            or type(self.synthetic_test_only) is not bool
            or (
                self.synthetic_test_only
                and self.landlock_transport_observation is not None
            )
            or (
                not self.synthetic_test_only
                and not isinstance(
                    self.landlock_transport_observation,
                    _G240ReplayLandlockTransportObservationV2,
                )
            )
        ):
            raise ReplayError(
                "G240 replay private execution sources are incomplete"
            )


def _validate_g240_replay_runtime_preflight_v2(
    payload: bytes,
    *,
    execution_request: object,
    contract: object,
    worktree: WorktreeSafetyReceipt,
    landlock_transport_observation: object | None,
    process_observation: _ReplayProcessObservationV2,
) -> tuple[str, str | None, str | None, str | None, bool]:
    """Authenticate exact preflight bytes against the live bootstrap pipe."""

    from .source_executor import (
        G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
        validate_g240_execution_request_v2,
    )
    from .source_orchestration import (
        _validate_runtime_preflight,
    )

    if (
        not isinstance(payload, bytes)
        or not isinstance(worktree, WorktreeSafetyReceipt)
        or not isinstance(
            process_observation,
            _ReplayProcessObservationV2,
        )
        or process_observation._capability
        is not _REPLAY_PROCESS_CAPABILITY_V2
    ):
        raise ReplayError(
            "G240 replay preflight lacks exact bytes or process authority"
        )
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReplayError(
            "G240 replay runtime preflight is not strict JSON"
        ) from exc
    if payload != canonical_dag_json_bytes(value) + b"\n":
        raise ReplayError(
            "G240 replay runtime preflight is not canonical newline DAG-JSON"
        )
    try:
        request = validate_g240_execution_request_v2(
            execution_request
        )
    except (TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 replay execution request failed typed validation"
        ) from exc
    synthetic = (
        request.adapter_factory_id
        == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
    )
    landlock_sources = None
    landlock_receipt = None
    landlock_payload = None
    if synthetic:
        if landlock_transport_observation is not None:
            raise ReplayError(
                "synthetic G240 replay may not claim Landlock transport"
            )
    else:
        transport = landlock_transport_observation
        if (
            not isinstance(
                transport,
                _G240ReplayLandlockTransportObservationV2,
            )
            or transport._capability
            is not _G240_REPLAY_LANDLOCK_TRANSPORT_CAPABILITY_V2
            or transport.process_observation is not process_observation
        ):
            raise ReplayError(
                "production G240 replay lacks live Landlock transport"
            )
        landlock_sources = transport.policy_sources
        landlock_receipt = transport.receipt
        landlock_payload = transport.receipt_payload
    try:
        preflight_cid, _bootstrap_receipt = (
            _validate_runtime_preflight(
                value,
                request=request,
                contract=contract,
                landlock_sources=landlock_sources,
                landlock_receipt=landlock_receipt,
                expected_gitlink_commit=(
                    worktree.submodule_commits.get(
                        "ipfs_accelerate_py"
                    )
                ),
            )
        )
    except (TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 replay runtime preflight failed source validation"
        ) from exc
    return (
        preflight_cid,
        (
            None
            if landlock_sources is None
            else str(landlock_sources.policy.policy_cid)
        ),
        (
            None
            if landlock_receipt is None
            else str(landlock_receipt.receipt_cid)
        ),
        (
            None
            if landlock_payload is None
            else cid_for_bytes(landlock_payload)
        ),
        synthetic,
    )


def _validate_live_replay_process_observation_v2(
    replay_receipt: ReplayReceipt,
    request: ReplayRequest,
    *,
    expected_arguments: Sequence[str],
) -> _ReplayProcessObservationV2:
    """Authenticate the private process witness attached by the runner."""

    observation = replay_receipt._process_observation
    command = tuple(expected_arguments)
    if (
        not isinstance(observation, _ReplayProcessObservationV2)
        or observation._capability is not _REPLAY_PROCESS_CAPABILITY_V2
        or observation.arguments != command
        or observation.returncode != replay_receipt.exit_code
        or hashlib.sha256(observation.stdout).hexdigest()
        != replay_receipt.stdout_sha256
        or hashlib.sha256(observation.stderr).hexdigest()
        != replay_receipt.stderr_sha256
        or replay_receipt.request_sha256 != request.request_sha256
    ):
        raise ReplayError(
            "G240 replay receipt lacks a privately observed live process"
        )
    return observation


def _run_process(
    request: ReplayRequest,
    *,
    worktree: Path,
    run_paths: RunPaths,
    evidence_path: Path,
    environment: Mapping[str, str] | None,
    launch_command: Sequence[str] | None = None,
    _controlled_environment: Mapping[str, str] | None = None,
    _controlled_input_bytes: bytes | None = None,
    _controlled_pass_fds: Sequence[int] = (),
) -> _ReplayProcessObservationV2:
    extra = {} if environment is None else dict(environment)
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\0" in key
        or "\0" in value
        for key, value in extra.items()
    ):
        raise ReplayError("replay environment must contain NUL-free strings")
    sensitive = sorted(
        key
        for key in extra
        if (
            key == "PATH"
            or key.startswith("PYTHON")
            or key in {"VIRTUAL_ENV", "CONDA_PREFIX"}
        )
    )
    if sensitive:
        raise ReplayError(
            "replay environment may not override interpreter search state: "
            + ", ".join(sensitive)
        )
    controlled = (
        {}
        if _controlled_environment is None
        else dict(_controlled_environment)
    )
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\0" in key
        or "\0" in value
        for key, value in controlled.items()
    ):
        raise ReplayError(
            "controlled replay environment must contain NUL-free strings"
        )
    if (
        _controlled_input_bytes is not None
        and (
            not isinstance(_controlled_input_bytes, bytes)
            or len(_controlled_input_bytes) > 16 * 1024 * 1024
        )
    ):
        raise ReplayError(
            "controlled replay stdin must be at most 16777216 bytes"
        )
    inherited_descriptors = tuple(_controlled_pass_fds)
    if (
        any(
            type(descriptor) is not int or descriptor <= 2
            for descriptor in inherited_descriptors
        )
        or len(inherited_descriptors) != len(set(inherited_descriptors))
        or (inherited_descriptors and os.name != "posix")
    ):
        raise ReplayError(
            "controlled replay descriptors must be unique POSIX FDs above 2"
        )
    process_environment = {
        "PATH": os.defpath,
        "PYTHONPATH": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        **extra,
        **controlled,
        "HSSL_REPLAY": "1",
        "HSSL_RUN_ID": request.replay_run_id,
        "HSSL_RUN_ROOT": run_paths.run_root.as_posix(),
        "HSSL_PROCESS_NAMESPACE": request.replay_process_namespace,
        "HSSL_CACHE_NAMESPACE": request.replay_cache_namespace,
        "HSSL_REPLAY_EVIDENCE_PATH": evidence_path.as_posix(),
    }
    command = (
        tuple(request.command)
        if launch_command is None
        else tuple(launch_command)
    )
    if (
        not command
        or any(
            not isinstance(item, str) or not item or "\0" in item
            for item in command
        )
    ):
        raise ReplayError("replay launch command is invalid")
    try:
        process = subprocess.Popen(
            list(command),
            cwd=worktree,
            env=process_environment,
            stdin=(
                subprocess.DEVNULL
                if _controlled_input_bytes is None
                else subprocess.PIPE
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
            pass_fds=inherited_descriptors,
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
                input=_controlled_input_bytes,
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
        try:
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
        finally:
            _close_process_standard_streams(process)
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
            "detached replay command failed with exit code "
            f"{process.returncode}"
        )
    active_after = len(_active_process_group_members(process.pid))
    if active_after:
        raise ReplayError(
            "detached replay retained active process-group members"
        )
    return _ReplayProcessObservationV2(
        arguments=command,
        stdout=stdout,
        stderr=stderr,
        returncode=process.returncode,
        process_group_started=True,
        process_group_reaped=process_group_reaped,
        active_process_count_after_reap=active_after,
        _capability=_REPLAY_PROCESS_CAPABILITY_V2,
    )


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
        process_observation = _run_process(
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
        "stdout_sha256": hashlib.sha256(
            process_observation.stdout
        ).hexdigest(),
        "stderr_sha256": hashlib.sha256(
            process_observation.stderr
        ).hexdigest(),
        "exit_code": 0,
        "detached": replay_worktree.detached,
        "auto_merge": replay_worktree.auto_merge,
    }
    receipt = ReplayReceipt(
        **payload,  # type: ignore[arg-type]
        receipt_sha256=_sha(payload),
        _process_observation=process_observation,
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


def run_g240_detached_replay_v2(
    source_checkout: str | Path,
    source_worktree_receipt: WorktreeSafetyReceipt,
    source_policy: object,
    source_namespace_receipt: object,
    source_runtime_evidence: object,
    *,
    source_execution_request: object,
    replay_execution_request: object,
    replay_run_id: str,
    executor_contract: object,
    benchmark_root: str | Path,
    replay_executor_identity_cid: str,
    replay_namespace_observer_identity_cid: str,
    orchestration_observer_identity_cid: str,
    environment: Mapping[str, str] | None = None,
    evidence_relative_path: str = "replay-evidence.json",
    timeout_seconds: float = 300.0,
    _test_only_synthetic_capability: object | None = None,
) -> tuple[
    object,
    object,
    object,
    ReplayRequest,
    ReplayReceipt,
    WorktreeSafetyReceipt,
]:
    """Execute one G238 target and bind it to G240 OS/Git observations.

    The exact source executor contract already frozen into ``source_policy``
    must write one canonical ``CausalRuntimeEvidenceV2`` JSON document.  All
    launch namespaces are derived before the first write; the returned
    namespace and orchestration receipts are recomputed from the actual
    detached worktree, process result, tracked entrypoint, and exact bytes.
    """

    from .causal_runtime import validate_causal_runtime_evidence_v2
    from .content_addressing import canonical_dag_json_bytes
    from .source_executor import (
        G240_EXECUTION_REQUEST_FILE_V2,
        G240_RUNTIME_PREFLIGHT_FILE_V2,
        G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
        G240SourceExecutorError,
        _G240_SYNTHETIC_TEST_CAPABILITY_V2,
        _G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2,
        validate_g240_execution_request_v2,
        validate_g240_runtime_for_execution_request_v2,
    )
    from .source_bootstrap_contract import (
        G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2,
        g240_private_landlock_policy_payload_v2,
    )
    from .namespace_provenance import (
        G240NamespacePolicyV2,
        G240ReplayNamespaceReceiptV2,
        G240RuntimeNamespaceReceiptV2,
        _build_g240_replay_orchestration_receipt_v2,
        g240_cache_namespace_set_cid,
        g240_recursive_gitlinks_cid,
        g240_replay_namespace_request_v2,
        g240_worktree_safety_projection_cid,
        validate_g240_runtime_namespace_receipt_from_policy_v2,
    )
    from .source_orchestration import (
        _g240_landlock_sources_for_job,
        _g240_launch_arguments,
        _read_g240_landlock_receipt_pipe,
    )

    try:
        source_worktree = WorktreeSafetyReceipt.from_dict(
            source_worktree_receipt.to_dict()
        )
        policy = (
            source_policy
            if isinstance(source_policy, G240NamespacePolicyV2)
            else G240NamespacePolicyV2.from_dict(source_policy)
        )
        source_namespace = (
            source_namespace_receipt
            if isinstance(
                source_namespace_receipt,
                G240RuntimeNamespaceReceiptV2,
            )
            else G240RuntimeNamespaceReceiptV2.from_dict(
                source_namespace_receipt
            )
        )
        source_runtime = validate_causal_runtime_evidence_v2(
            source_runtime_evidence.to_dict()
        )
        source_namespace = (
            validate_g240_runtime_namespace_receipt_from_policy_v2(
                source_namespace,
                policy=policy,
                evidence=source_runtime,
            )
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 source worktree/namespace/runtime evidence is invalid"
        ) from exc
    contract = _coerce_g240_executor_contract_v2(
        executor_contract,
        source_policy=policy,
    )
    try:
        source_request = validate_g240_execution_request_v2(
            source_execution_request
        )
        replay_execution = validate_g240_execution_request_v2(
            replay_execution_request
        )
        validate_g240_runtime_for_execution_request_v2(
            source_runtime, source_request
        )
    except (G240SourceExecutorError, TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 source/replay execution requests failed typed validation"
        ) from exc
    replay_id = _safe_id(replay_run_id, "replay_run_id")
    if replay_id == policy.run_id:
        raise ReplayError("G240 replay must use a fresh run id")
    requested_source = Path(source_checkout).resolve()
    if (
        source_worktree.source_checkout != requested_source
        or source_worktree.run_id != policy.run_id
        or source_worktree.worktree_commit
        != source_worktree.base_commit
        or g238_git_commit_cid(source_worktree.worktree_commit)
        != policy.source_commit_cid
    ):
        raise ReplayError(
            "G240 source worktree differs from the frozen namespace policy"
        )
    stage_environments = {
        stage.provenance.environment_sha256
        for stage in (
            *source_runtime.semantic_frontend,
            *source_runtime.case_result.stages,
        )
    }
    if (
        stage_environments != {contract.environment_sha256}
        or source_namespace.executor_identity_cid
        != contract.executor_identity_cid
    ):
        raise ReplayError(
            "G240 source runtime/executor differs from the frozen contract"
        )
    environment_sha256 = contract.environment_sha256
    try:
        expected_gitlinks = _capture_benchmark_bounded_gitlinks(
            requested_source,
            source_worktree.worktree_commit,
        )
    except SourceReconciliationError as exc:
        raise ReplayError(
            "cannot bind the G240 recursive Git source inventory"
        ) from exc
    if (
        g240_recursive_gitlinks_cid(expected_gitlinks)
        != policy.recursive_gitlinks_cid
    ):
        raise ReplayError(
            "G240 namespace policy differs from the actual Gitlink inventory"
        )
    _validate_live_worktree(
        source_worktree,
        source_worktree.worktree_commit,
        expected_gitlinks,
    )
    source_entrypoint = _validate_g240_executor_entrypoint_v2(
        contract,
        source_worktree,
    )
    launch = g240_replay_namespace_request_v2(
        source_policy=policy,
        source_receipt=source_namespace,
        replay_run_id=replay_id,
    )
    source_cache_set_cid = g240_cache_namespace_set_cid(
        source_namespace.cache_namespace_cids
    )
    replay_cache_set_cid = str(
        launch["replay_cache_namespace_set_cid"]
    )
    source_coordinate = policy.job_map.get(
        (source_namespace.plan_cid, source_namespace.job_id)
    )
    if source_coordinate is None:
        raise ReplayError(
            "G240 source namespace coordinate is absent from its policy"
        )
    raw_cache_map = launch["replay_cache_namespace_cids"]
    if not isinstance(raw_cache_map, Mapping):
        raise ReplayError("G240 replay cache namespace map changed")
    stable_request_fields = (
        "schema",
        "source_run_id",
        "source_commit",
        "policy_cid",
        "runtime_orchestration_policy_cid",
        "plan_cid",
        "job_cid",
        "coordinate_cid",
        "environment_cid",
        "environment_sha256",
        "source_text",
        "source_cid",
        "proof_context_cid",
        "adapter_factory_id",
        "adapter_configuration_cid",
    )
    if (
        source_request.execution_mode != "source"
        or source_request.execution_run_id != policy.run_id
        or source_request.source_run_id != policy.run_id
        or source_request.source_commit
        != source_worktree.worktree_commit
        or source_request.policy_cid != policy.policy_cid
        or source_request.runtime_orchestration_policy_cid
        != contract.contract_cid
        or source_request.plan_cid != source_namespace.plan_cid
        or source_request.typed_job.job_id != source_namespace.job_id
        or source_request.coordinate_cid
        != source_namespace.coordinate_cid
        or source_request.process_namespace_cid
        != source_namespace.process_namespace_cid
        or source_request.state_namespace_cid
        != source_namespace.state_namespace_cid
        or source_request.output_namespace_cid
        != source_namespace.output_namespace_cid
        or dict(source_request.cache_namespace_cids)
        != dict(source_namespace.cache_namespace_cids)
        or replay_execution.execution_mode != "replay"
        or replay_execution.execution_run_id != replay_id
        or replay_execution.source_execution_request_cid
        != source_request.request_cid
        or replay_execution.source_runtime_evidence_cid
        != source_runtime.receipt_cid
        or any(
            getattr(replay_execution, field)
            != getattr(source_request, field)
            for field in stable_request_fields
        )
        or replay_execution.typed_plan != source_request.typed_plan
        or replay_execution.typed_job != source_request.typed_job
        or replay_execution.process_namespace_cid
        != launch["replay_process_namespace_cid"]
        or replay_execution.state_namespace_cid
        != launch["replay_state_namespace_cid"]
        or replay_execution.output_namespace_cid
        != launch["replay_output_namespace_cid"]
        or dict(replay_execution.cache_namespace_cids)
        != dict(raw_cache_map)
        or dict(replay_execution.proof_context)
        != dict(source_request.proof_context)
    ):
        raise ReplayError(
            "G240 source/replay execution request differs from its exact "
            "policy/coordinate/environment/namespace preimage"
        )
    synthetic = (
        source_request.adapter_factory_id
        == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
    )
    if (
        synthetic
        and _test_only_synthetic_capability
        is not _G240_SYNTHETIC_TEST_CAPABILITY_V2
    ):
        raise ReplayError(
            "synthetic G240 replay requires the private test-only capability"
        )
    if (
        not synthetic
        and _test_only_synthetic_capability is not None
    ):
        raise ReplayError(
            "test-only synthetic capability cannot authorize live replay"
        )
    launch_arguments = _g240_launch_arguments(contract)
    cache_mode = source_coordinate.cache_mode
    requested_evidence_path = _relative_path(
        evidence_relative_path,
        "evidence_relative_path",
    )
    output_namespace_cid = str(
        launch["replay_output_namespace_cid"]
    )
    replay_evidence_relative_path = PurePosixPath(
        "results",
        output_namespace_cid,
        *PurePosixPath(requested_evidence_path).parts,
    ).as_posix()
    source_logical_cache = (
        "hssl-g240/"
        f"run/{policy.run_id}/physical/{source_cache_set_cid}/"
        f"cache/{cache_mode}"
    )
    replay_logical_cache = (
        "hssl-g240/"
        f"run/{replay_id}/physical/{replay_cache_set_cid}/"
        f"cache/{cache_mode}"
    )
    source_namespace_sha256 = hashlib.sha256(
        canonical_json(source_namespace.to_dict()).encode("utf-8")
    ).hexdigest()
    request = ReplayRequest.create(
        source_run_id=policy.run_id,
        replay_run_id=replay_id,
        source_commit=source_worktree.worktree_commit,
        environment_sha256=environment_sha256,
        source_execution_receipt_sha256=source_namespace_sha256,
        source_worktree_receipt_sha256=source_worktree.sha256,
        source_process_namespace=source_namespace.process_namespace_cid,
        replay_process_namespace=str(
            launch["replay_process_namespace_cid"]
        ),
        source_cache_namespaces=(source_logical_cache,),
        replay_cache_namespace=replay_logical_cache,
        command=contract.command_template,
        evidence_relative_path=replay_evidence_relative_path,
        timeout_seconds=timeout_seconds,
        execution_request_cid=str(replay_execution.request_cid),
    )
    extra_environment = {} if environment is None else dict(environment)
    reserved = {
        key
        for key in extra_environment
        if key.startswith("HSSL_G240_")
        or key.startswith("PYTHON")
        or key.startswith("GIT_")
        or key.startswith("LD_")
        or key.startswith("DYLD_")
        or key
        in {
            "PATH",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_TERMINAL_PROMPT",
            "LC_ALL",
            "HSSL_REPLAY",
            "HSSL_RUN_ID",
            "HSSL_RUN_ROOT",
            "HSSL_PROCESS_NAMESPACE",
            "HSSL_CACHE_NAMESPACE",
            "HSSL_REPLAY_EVIDENCE_PATH",
            "BASH_ENV",
            "CDPATH",
            "ENV",
            "GCONV_PATH",
            "HOME",
            "IFS",
            "LOCPATH",
            "NLSPATH",
            "SHELLOPTS",
        }
    }
    if reserved or extra_environment:
        raise ReplayError(
            "caller environment cannot override G240 replay namespaces"
        )
    run_paths = RunPaths.for_run(
        replay_id, benchmark_root=benchmark_root
    )
    if run_paths.run_root.exists() or run_paths.run_root.is_symlink():
        raise ReplayError("G240 replay run namespace already exists")
    evidence_path = _evidence_path(
        run_paths, request.evidence_relative_path
    )

    # All source and launch checks above finish before the first write.
    replay_worktree = prepare_isolated_worktree(
        requested_source,
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
            "cannot materialize G240 pinned submodules"
        ) from exc
    _validate_live_worktree(
        replay_worktree,
        request.source_commit,
        expected_gitlinks,
    )
    replay_entrypoint = _validate_g240_executor_entrypoint_v2(
        contract,
        replay_worktree,
    )
    if replay_entrypoint != source_entrypoint:
        raise ReplayError(
            "G240 source and replay executor entrypoints differ"
        )
    state_path = (
        run_paths.state / str(launch["replay_state_namespace_cid"])
    )
    output_path = run_paths.results / output_namespace_cid
    state_path.mkdir(mode=0o700, exist_ok=False)
    output_path.mkdir(mode=0o700, exist_ok=False)
    cache_paths: dict[str, str] = {}
    for stage, namespace_cid in raw_cache_map.items():
        cache_path = run_paths.cache / str(stage) / str(namespace_cid)
        cache_path.mkdir(mode=0o700, parents=True, exist_ok=False)
        cache_paths[str(stage)] = cache_path.as_posix()
    evidence_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    execution_request_path = (
        state_path / G240_EXECUTION_REQUEST_FILE_V2
    )
    execution_request_payload = _write_private_canonical_json(
        execution_request_path,
        replay_execution.to_dict(),
        parent=state_path,
    )
    landlock_sources = (
        None
        if synthetic
        else _g240_landlock_sources_for_job(
            worktree=replay_worktree,
            contract=contract,
            request=replay_execution,
            state_path=state_path,
            output_path=output_path,
            cache_paths=tuple(
                Path(value) for value in cache_paths.values()
            ),
        )
    )
    private_policy_input = (
        None
        if landlock_sources is None
        else canonical_dag_json_bytes(
            g240_private_landlock_policy_payload_v2(
                landlock_sources
            )
        )
        + b"\n"
    )
    receipt_read_descriptor: int | None = None
    receipt_write_descriptor: int | None = None
    g240_environment = {
        **extra_environment,
        "PYTHONPATH": replay_worktree.worktree_root.as_posix(),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HSSL_G240_RUN_ID": replay_id,
        "HSSL_G240_PLAN_CID": source_namespace.plan_cid,
        "HSSL_G240_JOB_ID": source_namespace.job_id,
        "HSSL_G240_COORDINATE_CID": source_namespace.coordinate_cid,
        "HSSL_G240_PROCESS_NAMESPACE_CID": str(
            launch["replay_process_namespace_cid"]
        ),
        "HSSL_G240_STATE_DIR": state_path.as_posix(),
        "HSSL_G240_OUTPUT_DIR": output_path.as_posix(),
        "HSSL_G240_EVIDENCE_PATH": evidence_path.as_posix(),
        "HSSL_G240_EXECUTION_REQUEST_PATH": (
            execution_request_path.as_posix()
        ),
        "HSSL_G240_EXECUTION_REQUEST_CID": str(
            replay_execution.request_cid
        ),
        "HSSL_G240_ENVIRONMENT_CID": contract.environment_cid,
        "HSSL_G240_ENVIRONMENT_SHA256": contract.environment_sha256,
        "HSSL_G240_CACHE_ROOTS_JSON": (
            canonical_dag_json_bytes(cache_paths).decode("utf-8")
        ),
        "HSSL_G240_CACHE_NAMESPACE_CIDS_JSON": (
            canonical_dag_json_bytes(dict(raw_cache_map)).decode("utf-8")
        ),
        "HSSL_G240_GIT_EXECUTABLE_PATH": (
            contract.git_executable_path
        ),
        "HSSL_G240_GIT_EXECUTABLE_CID": contract.git_executable_cid,
        "HSSL_G240_CONFINEMENT_PROFILE_CID": (
            G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
        ),
        "HSSL_G240_EXPECTED_SOURCE_COMMIT": request.source_commit,
        "HSSL_G240_REPLAY_CONTEXT_CID": str(
            launch["replay_context_cid"]
        ),
        "HSSL_G240_STATE_NAMESPACE_CID": str(
            launch["replay_state_namespace_cid"]
        ),
        "HSSL_G240_OUTPUT_NAMESPACE_CID": str(
            launch["replay_output_namespace_cid"]
        ),
        "HSSL_G240_STATE_PATH": state_path.as_posix(),
        "HSSL_G240_OUTPUT_PATH": output_path.as_posix(),
        "HSSL_G240_CACHE_NAMESPACE_SET_CID": replay_cache_set_cid,
        "HSSL_G240_CACHE_PATHS_JSON": canonical_json(cache_paths),
    }
    landlock_transport_observation: (
        _G240ReplayLandlockTransportObservationV2 | None
    ) = None
    try:
        if synthetic:
            g240_environment[
                _G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2
            ] = str(replay_execution.request_cid)
        else:
            try:
                (
                    receipt_read_descriptor,
                    receipt_write_descriptor,
                ) = os.pipe2(os.O_CLOEXEC)
            except OSError as exc:
                raise ReplayError(
                    "cannot create the G240 replay Landlock receipt pipe"
                ) from exc
            g240_environment["HSSL_G240_LANDLOCK_RECEIPT_FD"] = str(
                receipt_write_descriptor
            )
        try:
            process_observation = _run_process(
                request,
                worktree=replay_worktree.worktree_root,
                run_paths=run_paths,
                evidence_path=evidence_path,
                environment=None,
                launch_command=launch_arguments,
                _controlled_environment=g240_environment,
                _controlled_input_bytes=private_policy_input,
                _controlled_pass_fds=(
                    ()
                    if receipt_write_descriptor is None
                    else (receipt_write_descriptor,)
                ),
            )
        finally:
            if receipt_write_descriptor is not None:
                os.close(receipt_write_descriptor)
                receipt_write_descriptor = None
        if landlock_sources is not None:
            assert receipt_read_descriptor is not None
            owned_read_descriptor = receipt_read_descriptor
            receipt_read_descriptor = None
            landlock_receipt, landlock_receipt_payload = (
                _read_g240_landlock_receipt_pipe(
                    owned_read_descriptor,
                    expected_policy=landlock_sources.policy,
                )
            )
            landlock_transport_observation = (
                _G240ReplayLandlockTransportObservationV2(
                    process_observation=process_observation,
                    policy_sources=landlock_sources,
                    receipt=landlock_receipt,
                    receipt_payload=landlock_receipt_payload,
                    close_fds=True,
                    passed_descriptor_count=1,
                    one_shot_atomic_frame=True,
                    _capability=(
                        _G240_REPLAY_LANDLOCK_TRANSPORT_CAPABILITY_V2
                    ),
                )
            )
        elif receipt_read_descriptor is not None:
            raise ReplayError(
                "synthetic G240 replay unexpectedly created a receipt pipe"
            )
    finally:
        if receipt_write_descriptor is not None:
            os.close(receipt_write_descriptor)
        if receipt_read_descriptor is not None:
            os.close(receipt_read_descriptor)
        try:
            _validate_live_worktree(
                replay_worktree,
                request.source_commit,
                expected_gitlinks,
            )
        finally:
            for namespace_path in (
                state_path,
                output_path,
                *(Path(value) for value in cache_paths.values()),
            ):
                _validate_private_namespace_directory(
                    namespace_path,
                    run_root=run_paths.run_root,
                )
    runtime_preflight_path = (
        state_path / G240_RUNTIME_PREFLIGHT_FILE_V2
    )
    runtime_preflight_payload = _read_evidence(
        runtime_preflight_path
    )
    (
        _runtime_preflight_cid,
        _landlock_policy_cid,
        _landlock_receipt_cid,
        _landlock_receipt_payload_cid,
        _preflight_synthetic,
    ) = _validate_g240_replay_runtime_preflight_v2(
        runtime_preflight_payload,
        execution_request=replay_execution,
        contract=contract,
        worktree=replay_worktree,
        landlock_transport_observation=(
            landlock_transport_observation
        ),
        process_observation=process_observation,
    )
    private_execution_sources = _G240ReplayPrivateExecutionSourcesV2(
        execution_request=replay_execution,
        execution_request_payload=execution_request_payload,
        runtime_preflight_payload=runtime_preflight_payload,
        landlock_transport_observation=(
            landlock_transport_observation
        ),
        synthetic_test_only=synthetic,
        _capability=_G240_REPLAY_PRIVATE_EXECUTION_CAPABILITY_V2,
    )
    evidence_payload = _read_evidence(evidence_path)
    try:
        decoded = json.loads(evidence_payload.decode("utf-8"))
        replay_runtime = validate_causal_runtime_evidence_v2(decoded)
        replay_runtime = validate_g240_runtime_for_execution_request_v2(
            replay_runtime,
            replay_execution,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReplayError(
            "G240 replay command did not emit full canonical runtime evidence"
        ) from exc
    if evidence_payload != (
        canonical_dag_json_bytes(replay_runtime.to_dict()) + b"\n"
    ):
        raise ReplayError(
            "G240 replay runtime evidence is not canonical newline DAG-JSON"
        )
    replay_stage_environments = {
        stage.provenance.environment_sha256
        for stage in (
            *replay_runtime.semantic_frontend,
            *replay_runtime.case_result.stages,
        )
    }
    if replay_stage_environments != {
        contract.environment_sha256
    } or replay_stage_environments != {request.environment_sha256}:
        raise ReplayError(
            "G240 replay runtime environment differs from the contract/request"
        )
    worktree_projection_cid = g240_worktree_safety_projection_cid(
        replay_worktree
    )
    namespace_receipt = G240ReplayNamespaceReceiptV2.create(
        source_policy=policy,
        source_receipt=source_namespace,
        replay_run_id=replay_id,
        replay_worktree_cid=worktree_projection_cid,
        replay_runtime_evidence=replay_runtime,
        replay_executor_identity_cid=replay_executor_identity_cid,
        replay_observer_identity_cid=(
            replay_namespace_observer_identity_cid
        ),
        process_group_started=(
            process_observation.process_group_started
        ),
        process_group_reaped=(
            process_observation.process_group_reaped
        ),
        active_process_count_after_reap=(
            process_observation.active_process_count_after_reap
        ),
        state_namespace_created_exclusive=True,
        state_namespace_finalized=True,
        output_namespace_created_exclusive=True,
        output_namespace_finalized=True,
        cache_namespaces_mounted=True,
    )
    payload = {
        "schema": REPLAY_RECEIPT_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "request_sha256": request.request_sha256,
        "source_execution_receipt_sha256": source_namespace_sha256,
        "source_worktree_receipt_sha256": source_worktree.sha256,
        "replay_worktree_receipt_sha256": replay_worktree.sha256,
        "source_run_id": request.source_run_id,
        "replay_run_id": request.replay_run_id,
        "source_commit": request.source_commit,
        "environment_sha256": request.environment_sha256,
        "process_namespace": request.replay_process_namespace,
        "cache_namespace": request.replay_cache_namespace,
        "evidence_sha256": hashlib.sha256(evidence_payload).hexdigest(),
        "stdout_sha256": hashlib.sha256(
            process_observation.stdout
        ).hexdigest(),
        "stderr_sha256": hashlib.sha256(
            process_observation.stderr
        ).hexdigest(),
        "exit_code": 0,
        "detached": replay_worktree.detached,
        "auto_merge": replay_worktree.auto_merge,
    }
    replay_receipt = ReplayReceipt(
        **payload,  # type: ignore[arg-type]
        receipt_sha256=_sha(payload),
        _process_observation=process_observation,
        _g240_private_execution_sources=private_execution_sources,
    )
    receipt_path = run_paths.receipts / REPLAY_RECEIPT_FILE
    try:
        with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(replay_receipt.to_dict()))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ReplayError(
            "refusing to overwrite G240 detached replay receipt"
        ) from exc
    orchestration_receipt = (
        _build_g240_replay_orchestration_receipt_v2(
            source_policy=policy,
            source_namespace_receipt=source_namespace,
            namespace_receipt=namespace_receipt,
            source_runtime_evidence=source_runtime,
            replay_runtime_evidence=replay_runtime,
            executor_contract=contract,
            replay_request=request,
            replay_receipt=replay_receipt,
            worktree_safety_receipt=replay_worktree,
            replay_execution_request=replay_execution,
            execution_request_payload=execution_request_payload,
            runtime_preflight_payload=runtime_preflight_payload,
            landlock_transport_observation=(
                landlock_transport_observation
            ),
            evidence_payload=evidence_payload,
            process_observation=process_observation,
            orchestration_observer_identity_cid=(
                orchestration_observer_identity_cid
            ),
        )
    )
    return (
        replay_runtime,
        namespace_receipt,
        orchestration_receipt,
        request,
        replay_receipt,
        replay_worktree,
    )


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
    "G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2",
    "G238_FAILURE_SAMPLE_PER_STRATUM",
    "G238_GIT_COMMIT_IDENTITY_SCHEMA_V2",
    "G238_REPLAY_GATE_SCHEMA_V2",
    "G238_REPLAY_POLICY_SCHEMA_V2",
    "G238_REPLAY_POLICY_V2_CID",
    "G238_REPLAY_SOURCE_INDEX_SCHEMA_V2",
    "G238_REPLAY_SOURCE_RECORD_SCHEMA_V2",
    "G238DetachedReplayReceiptV2",
    "G238ReplaySourceIndexV2",
    "G238ReplaySourceRecordV2",
    "FreshReplayGateError",
    "HSSLEV2381F50",
    "REPLAY_RECEIPT_FILE",
    "REPLAY_RECEIPT_SCHEMA",
    "REPLAY_REQUEST_SCHEMA",
    "ReplayError",
    "ReplayReceipt",
    "ReplayRequest",
    "build_g238_detached_replay_gate_v2",
    "g238_git_commit_cid",
    "run_detached_replay",
    "run_g240_detached_replay_v2",
    "validate_detached_replay_pair",
    "validate_g238_detached_replay_gate_v2",
]
