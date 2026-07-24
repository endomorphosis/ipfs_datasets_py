"""Robustness, failure-isolation, and receipt-replay evidence.

The benchmark runner deliberately retains every terminal case outcome.  This
module is the stricter reporting boundary used before any of those outcomes
may be treated as robust evidence.  It:

* classifies the preregistered failure-injection matrix;
* proves that an injected failure stayed local and within its time bound;
* runs external validation commands in a killable process group;
* compares a source result with a fresh-run replay under pinned identities; and
* emits one canonical, content-addressed robustness report.

It does not invoke production routing, promote a benchmark arm, or weaken the
frozen protocol's stop policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Final, Mapping, Protocol, Sequence, Self

from .capabilities import WorktreeSafetyReceipt
from .contracts import (
    DEFAULT_PROTOCOL,
    CacheMode,
    CaseResultRecord,
    FailureCode,
    OutcomeStatus,
    ProtocolContractError,
    RunContract,
    canonical_json,
)
from .metrics import MetricsContractError, validate_kernel_bound_result


FAILURE_ISOLATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.failure-isolation.v1"
)
REPLAY_VALIDATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.receipt-replay.v1"
)
ROBUSTNESS_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.robustness-report.v1"
)
BOUNDED_PROCESS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.bounded-process.v1"
)
_SHA256 = frozenset("0123456789abcdef")
_MAX_DETAIL = 512


class RobustnessValidationError(ValueError):
    """Raised when robustness evidence is incomplete, stale, or inconsistent."""


class FailureInjectionKind(str, Enum):
    """Complete failure-injection matrix required by HSSL-G070."""

    MISSING_TOOL = "missing_tool"
    MALFORMED_OUTPUT = "malformed_output"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    CACHE_CORRUPTION = "cache_corruption"
    BACKEND_DRIFT = "backend_drift"


class ReplayStatus(str, Enum):
    PASSED = "passed"


_EXPECTED_CODES: Final[Mapping[FailureInjectionKind, frozenset[FailureCode]]] = {
    FailureInjectionKind.MISSING_TOOL: frozenset(
        {FailureCode.CAPABILITY_UNAVAILABLE}
    ),
    FailureInjectionKind.MALFORMED_OUTPUT: frozenset(
        {
            FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE,
            FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        }
    ),
    FailureInjectionKind.TIMEOUT: frozenset(
        {
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
            FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        }
    ),
    FailureInjectionKind.CANCELLATION: frozenset(
        {FailureCode.RESOURCE_LEASE_CANCELLATION}
    ),
    FailureInjectionKind.CACHE_CORRUPTION: frozenset(
        {FailureCode.CACHE_CONTAMINATION}
    ),
    FailureInjectionKind.BACKEND_DRIFT: frozenset(
        {FailureCode.RECEIPT_OR_PROVENANCE_FAILURE}
    ),
}


def HSSLEV0702E85() -> str:
    """Return the stable AST evidence marker for the robustness objective."""

    return "failure injection, bounded isolation, and pinned fresh-worktree receipt replay"


def _digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256 for character in value)
    ):
        raise RobustnessValidationError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _identifier(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value in {".", ".."}
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "._-") for character in value)
    ):
        raise RobustnessValidationError(f"{field} is not a safe identifier")
    return value


def _exact(data: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(data) != expected:
        raise RobustnessValidationError(
            f"{field} fields changed; expected {sorted(expected)}, got {sorted(data)}"
        )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise RobustnessValidationError(f"{field} must be an object")
    return value


def _number(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RobustnessValidationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise RobustnessValidationError(f"{field} is outside its allowed bound")
    return result


def _enum(enum_type: type[Enum], value: object, field: str) -> Enum:
    if not isinstance(value, str):
        raise RobustnessValidationError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise RobustnessValidationError(f"unsupported {field}: {value!r}") from exc


def _case_identity(record: CaseResultRecord) -> tuple[object, ...]:
    return (
        record.protocol_sha256,
        record.run_id,
        record.case_id,
        record.case_manifest_sha256,
        record.variant_id,
        record.split,
        record.cache_mode,
    )


def _contract_identity(contract: RunContract) -> tuple[object, ...]:
    return (
        contract.protocol_sha256,
        contract.run_id,
        contract.case_manifest_sha256,
        contract.requested_variant_id,
        contract.split,
        contract.cache_mode,
    )


def _validate_contract_result(
    contract: RunContract, result: CaseResultRecord
) -> None:
    expected = (
        result.protocol_sha256,
        result.run_id,
        result.case_manifest_sha256,
        result.variant_id,
        result.split,
        result.cache_mode,
    )
    if _contract_identity(contract) != expected:
        raise RobustnessValidationError(
            "run contract and case-result identities do not match"
        )


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """Terminal evidence for one command executed in an isolated process group."""

    schema: str
    argv: tuple[str, ...]
    pid: int | None
    process_group_id: int | None
    returncode: int | None
    elapsed_seconds: float
    limit_seconds: float
    failure_code: FailureCode | None
    timed_out: bool
    cancelled: bool
    stdout: str
    stderr: str
    output_truncated: bool
    orphaned_child_count: int

    def __post_init__(self) -> None:
        if self.schema != BOUNDED_PROCESS_SCHEMA:
            raise RobustnessValidationError("unsupported bounded-process schema")
        if not isinstance(self.argv, tuple) or not self.argv:
            raise RobustnessValidationError("argv must be a nonempty tuple")
        if any(not isinstance(item, str) or not item for item in self.argv):
            raise RobustnessValidationError("argv contains an invalid argument")
        for field in ("pid", "process_group_id"):
            value = getattr(self, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise RobustnessValidationError(f"{field} must be a positive integer")
        if (self.pid is None) != (self.process_group_id is None):
            raise RobustnessValidationError(
                "pid and process_group_id must both be present or absent"
            )
        if self.returncode is not None and (
            isinstance(self.returncode, bool) or not isinstance(self.returncode, int)
        ):
            raise RobustnessValidationError("returncode must be an integer or null")
        _number(self.elapsed_seconds, "elapsed_seconds")
        _number(self.limit_seconds, "limit_seconds", positive=True)
        if self.failure_code is not None and not isinstance(
            self.failure_code, FailureCode
        ):
            raise RobustnessValidationError("failure_code must use FailureCode")
        if type(self.timed_out) is not bool or type(self.cancelled) is not bool:
            raise RobustnessValidationError("process flags must be booleans")
        if self.timed_out and self.cancelled:
            raise RobustnessValidationError(
                "a process cannot be both timed out and explicitly cancelled"
            )
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise RobustnessValidationError("process output must be text")
        if any(
            len(value.encode("utf-8")) > 16 * 1024 * 1024
            for value in (self.stdout, self.stderr)
        ):
            raise RobustnessValidationError("retained process output is too large")
        if type(self.output_truncated) is not bool:
            raise RobustnessValidationError("output_truncated must be a boolean")
        if (
            isinstance(self.orphaned_child_count, bool)
            or not isinstance(self.orphaned_child_count, int)
            or self.orphaned_child_count < 0
        ):
            raise RobustnessValidationError(
                "orphaned_child_count must be a nonnegative integer"
            )
        if self.orphaned_child_count:
            if self.failure_code is not FailureCode.ORPHANED_CHILD:
                raise RobustnessValidationError(
                    "unexpected or surviving children require orphaned_child classification"
                )
        elif self.timed_out or self.cancelled:
            if self.failure_code is not FailureCode.RESOURCE_LEASE_CANCELLATION:
                raise RobustnessValidationError(
                    "timeout/cancellation requires resource-lease classification"
                )

    @property
    def bounded(self) -> bool:
        return self.elapsed_seconds <= self.limit_seconds

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "argv": list(self.argv),
            "pid": self.pid,
            "process_group_id": self.process_group_id,
            "returncode": self.returncode,
            "elapsed_seconds": self.elapsed_seconds,
            "limit_seconds": self.limit_seconds,
            "failure_code": (
                None if self.failure_code is None else self.failure_code.value
            ),
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output_truncated": self.output_truncated,
            "orphaned_child_count": self.orphaned_child_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "bounded process")
        _exact(data, set(cls.__dataclass_fields__), "bounded process")
        argv = data["argv"]
        if not isinstance(argv, list):
            raise RobustnessValidationError("argv must be an array")
        code = data["failure_code"]
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            argv=tuple(argv),  # type: ignore[arg-type]
            pid=data["pid"],  # type: ignore[arg-type]
            process_group_id=data["process_group_id"],  # type: ignore[arg-type]
            returncode=data["returncode"],  # type: ignore[arg-type]
            elapsed_seconds=data["elapsed_seconds"],  # type: ignore[arg-type]
            limit_seconds=data["limit_seconds"],  # type: ignore[arg-type]
            failure_code=(  # type: ignore[arg-type]
                None
                if code is None
                else _enum(FailureCode, code, "failure_code")
            ),
            timed_out=data["timed_out"],  # type: ignore[arg-type]
            cancelled=data["cancelled"],  # type: ignore[arg-type]
            stdout=data["stdout"],  # type: ignore[arg-type]
            stderr=data["stderr"],  # type: ignore[arg-type]
            output_truncated=data["output_truncated"],  # type: ignore[arg-type]
            orphaned_child_count=data["orphaned_child_count"],  # type: ignore[arg-type]
        )


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


def _active_process_group_members(process_group_id: int) -> tuple[int, ...]:
    """Return live (non-zombie) Linux processes in a process group."""

    proc = Path("/proc")
    if not proc.is_dir():
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return ()
        except PermissionError:
            return (process_group_id,)
        return (process_group_id,)
    members: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="utf-8").split()
            # /proc/<pid>/stat: state is field 3, process group is field 5.
            if len(fields) > 4 and int(fields[4]) == process_group_id:
                if fields[2] != "Z":
                    members.append(int(entry.name))
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            continue
    return tuple(sorted(members))


def _terminate_process_group(
    process: subprocess.Popen[bytes], *, grace_seconds: float
) -> tuple[int, ...]:
    process_group_id = process.pid
    if process.poll() is None or _active_process_group_members(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process.poll() is None:
            try:
                process.wait(timeout=min(0.02, max(0.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
        if not _active_process_group_members(process_group_id):
            break
        time.sleep(0.005)
    members = _active_process_group_members(process_group_id)
    if members:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        kill_deadline = time.monotonic() + grace_seconds
        while time.monotonic() < kill_deadline:
            if process.poll() is None:
                try:
                    process.wait(timeout=0.02)
                except subprocess.TimeoutExpired:
                    pass
            members = _active_process_group_members(process_group_id)
            if not members:
                break
            time.sleep(0.005)
    if process.poll() is None:
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass
    return _active_process_group_members(process_group_id)


def _read_bounded(stream: object, maximum: int) -> tuple[str, bool]:
    stream.seek(0)  # type: ignore[attr-defined]
    raw = stream.read(maximum + 1)  # type: ignore[attr-defined]
    truncated = len(raw) > maximum
    return raw[:maximum].decode("utf-8", errors="replace"), truncated


def run_bounded_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cancellation: CancellationSignal | None = None,
    termination_grace_seconds: float = 0.25,
    maximum_output_bytes: int = 64 * 1024,
) -> BoundedProcessResult:
    """Run ``argv`` without a shell and kill/reap its whole process group.

    Output is redirected to temporary files so an untrusted child cannot grow
    the supervisor's memory.  Only ``maximum_output_bytes`` from each stream is
    retained in the returned record.
    """

    command = tuple(argv)
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise RobustnessValidationError("argv must be a nonempty string sequence")
    limit = _number(timeout_seconds, "timeout_seconds", positive=True)
    grace = _number(
        termination_grace_seconds, "termination_grace_seconds", positive=True
    )
    if (
        isinstance(maximum_output_bytes, bool)
        or not isinstance(maximum_output_bytes, int)
        or maximum_output_bytes < 1
        or maximum_output_bytes > 16 * 1024 * 1024
    ):
        raise RobustnessValidationError(
            "maximum_output_bytes must be from 1 through 16777216"
        )
    if cwd is not None and not Path(cwd).is_dir():
        raise RobustnessValidationError("cwd must be an existing directory")
    if env is not None and (
        not isinstance(env, Mapping)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items())
    ):
        raise RobustnessValidationError("env must map strings to strings")

    start = time.monotonic()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=None if env is None else dict(env),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                shell=False,
            )
        except FileNotFoundError:
            elapsed = time.monotonic() - start
            return BoundedProcessResult(
                BOUNDED_PROCESS_SCHEMA,
                command,
                None,
                None,
                None,
                elapsed,
                limit + grace * 2,
                FailureCode.CAPABILITY_UNAVAILABLE,
                False,
                False,
                "",
                "",
                False,
                0,
            )
        except OSError as exc:
            raise RobustnessValidationError(
                f"could not start bounded process: {type(exc).__name__}"
            ) from exc

        timed_out = False
        cancelled = False
        deadline = start + limit
        try:
            while process.poll() is None:
                if cancellation is not None and cancellation.is_set():
                    cancelled = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(min(0.01, max(0.001, deadline - time.monotonic())))
        except BaseException:
            # Even supervisor cancellation/interrupt must not leak the child
            # group. Preserve the original exception after best-effort reap.
            _terminate_process_group(process, grace_seconds=grace)
            raise

        survivors: tuple[int, ...] = ()
        unexpected_children: tuple[int, ...] = ()
        if timed_out or cancelled:
            survivors = _terminate_process_group(process, grace_seconds=grace)
        else:
            # A parent can exit while leaving a same-group child holding no
            # output descriptor. Treat that as an orphan and clean it too.
            unexpected_children = tuple(
                pid
                for pid in _active_process_group_members(process.pid)
                if pid != process.pid
            )
            if unexpected_children:
                survivors = _terminate_process_group(process, grace_seconds=grace)
        returncode = process.poll()
        stdout, stdout_truncated = _read_bounded(stdout_file, maximum_output_bytes)
        stderr, stderr_truncated = _read_bounded(stderr_file, maximum_output_bytes)
        elapsed = time.monotonic() - start
        if survivors or unexpected_children:
            failure_code = FailureCode.ORPHANED_CHILD
        elif timed_out or cancelled:
            failure_code = FailureCode.RESOURCE_LEASE_CANCELLATION
        elif returncode == 0:
            failure_code = None
        else:
            failure_code = FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
        return BoundedProcessResult(
            BOUNDED_PROCESS_SCHEMA,
            command,
            process.pid,
            process.pid,
            returncode,
            elapsed,
            limit + grace * 2,
            failure_code,
            timed_out,
            cancelled,
            stdout,
            stderr,
            stdout_truncated or stderr_truncated,
            len(set(survivors) | set(unexpected_children)),
        )


@dataclass(frozen=True, slots=True)
class FailureIsolationRecord:
    """Validated evidence that one injected failure was bounded and local."""

    schema: str
    injection_id: str
    kind: FailureInjectionKind
    case_id: str
    result_sha256: str
    observed_failure_code: FailureCode
    elapsed_seconds: float
    limit_seconds: float
    affected_case_ids: tuple[str, ...]
    child_process_ids: tuple[int, ...] = ()
    reaped_process_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != FAILURE_ISOLATION_SCHEMA:
            raise RobustnessValidationError("unsupported failure-isolation schema")
        _identifier(self.injection_id, "injection_id")
        if not isinstance(self.kind, FailureInjectionKind):
            raise RobustnessValidationError("kind must use FailureInjectionKind")
        _identifier(self.case_id, "case_id")
        _digest(self.result_sha256, "result_sha256")
        if not isinstance(self.observed_failure_code, FailureCode):
            raise RobustnessValidationError(
                "observed_failure_code must use FailureCode"
            )
        if self.observed_failure_code not in _EXPECTED_CODES[self.kind]:
            raise RobustnessValidationError(
                f"{self.kind.value} was misclassified as "
                f"{self.observed_failure_code.value}"
            )
        elapsed = _number(self.elapsed_seconds, "elapsed_seconds")
        limit = _number(self.limit_seconds, "limit_seconds", positive=True)
        if elapsed > limit:
            raise RobustnessValidationError(
                f"{self.kind.value} exceeded its recorded time bound"
            )
        if (
            not isinstance(self.affected_case_ids, tuple)
            or self.affected_case_ids != (self.case_id,)
        ):
            raise RobustnessValidationError(
                "an injected failure must affect exactly its own case"
            )
        for field in ("child_process_ids", "reaped_process_ids"):
            values = getattr(self, field)
            if (
                not isinstance(values, tuple)
                or len(values) != len(set(values))
                or any(
                    isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
                    for pid in values
                )
            ):
                raise RobustnessValidationError(
                    f"{field} must contain unique positive process ids"
                )
        if not set(self.child_process_ids).issubset(self.reaped_process_ids):
            raise RobustnessValidationError(
                "every child process must be terminated and reaped"
            )
        if DEFAULT_PROTOCOL.stop_required(self.observed_failure_code) != (
            self.kind
            in {
                FailureInjectionKind.CACHE_CORRUPTION,
                FailureInjectionKind.BACKEND_DRIFT,
            }
        ):
            raise RobustnessValidationError(
                "injected failure disagrees with the frozen immediate-stop policy"
            )

    @classmethod
    def classify(
        cls,
        injection_id: str,
        kind: FailureInjectionKind,
        result: CaseResultRecord,
        *,
        elapsed_seconds: float,
        limit_seconds: float,
        affected_case_ids: Sequence[str],
        child_process_ids: Sequence[int] = (),
        reaped_process_ids: Sequence[int] = (),
    ) -> Self:
        if not isinstance(result, CaseResultRecord) or result.failure_code is None:
            raise RobustnessValidationError(
                "injected failure requires a failed CaseResultRecord"
            )
        try:
            validate_kernel_bound_result(result)
        except MetricsContractError as exc:
            raise RobustnessValidationError(
                "injected result failed provenance validation"
            ) from exc
        return cls(
            FAILURE_ISOLATION_SCHEMA,
            injection_id,
            kind,
            result.case_id,
            result.digest,
            result.failure_code,
            elapsed_seconds,
            limit_seconds,
            tuple(affected_case_ids),
            tuple(child_process_ids),
            tuple(reaped_process_ids),
        )

    @property
    def stop_required(self) -> bool:
        return DEFAULT_PROTOCOL.stop_required(self.observed_failure_code)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "injection_id": self.injection_id,
            "kind": self.kind.value,
            "case_id": self.case_id,
            "result_sha256": self.result_sha256,
            "observed_failure_code": self.observed_failure_code.value,
            "elapsed_seconds": self.elapsed_seconds,
            "limit_seconds": self.limit_seconds,
            "affected_case_ids": list(self.affected_case_ids),
            "child_process_ids": list(self.child_process_ids),
            "reaped_process_ids": list(self.reaped_process_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "failure isolation")
        _exact(data, set(cls.__dataclass_fields__), "failure isolation")
        arrays = {}
        for field in (
            "affected_case_ids",
            "child_process_ids",
            "reaped_process_ids",
        ):
            member = data[field]
            if not isinstance(member, list):
                raise RobustnessValidationError(f"{field} must be an array")
            arrays[field] = member
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            injection_id=data["injection_id"],  # type: ignore[arg-type]
            kind=_enum(  # type: ignore[arg-type]
                FailureInjectionKind, data["kind"], "kind"
            ),
            case_id=data["case_id"],  # type: ignore[arg-type]
            result_sha256=data["result_sha256"],  # type: ignore[arg-type]
            observed_failure_code=_enum(  # type: ignore[arg-type]
                FailureCode, data["observed_failure_code"], "observed_failure_code"
            ),
            elapsed_seconds=data["elapsed_seconds"],  # type: ignore[arg-type]
            limit_seconds=data["limit_seconds"],  # type: ignore[arg-type]
            affected_case_ids=tuple(arrays["affected_case_ids"]),  # type: ignore[arg-type]
            child_process_ids=tuple(arrays["child_process_ids"]),  # type: ignore[arg-type]
            reaped_process_ids=tuple(arrays["reaped_process_ids"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ReplayValidationRecord:
    """Content-addressed proof of one source/fresh-run receipt comparison."""

    schema: str
    status: ReplayStatus
    case_id: str
    original_run_id: str
    replay_run_id: str
    original_result_sha256: str
    replay_result_sha256: str
    original_receipt_sha256: str
    replay_receipt_sha256: str
    environment_sha256: str
    source_commit: str
    worktree_receipt_sha256: str
    original_cache_namespace: str
    replay_cache_namespace: str

    def __post_init__(self) -> None:
        if self.schema != REPLAY_VALIDATION_SCHEMA:
            raise RobustnessValidationError("unsupported replay-validation schema")
        if self.status is not ReplayStatus.PASSED:
            raise RobustnessValidationError("only passed replay evidence is durable")
        for field in ("case_id", "original_run_id", "replay_run_id"):
            _identifier(getattr(self, field), field)
        if self.original_run_id == self.replay_run_id:
            raise RobustnessValidationError("receipt replay requires a fresh run id")
        for field in (
            "original_result_sha256",
            "replay_result_sha256",
            "original_receipt_sha256",
            "replay_receipt_sha256",
            "environment_sha256",
            "worktree_receipt_sha256",
        ):
            _digest(getattr(self, field), field)
        if (
            not isinstance(self.source_commit, str)
            or len(self.source_commit) != 40
            or any(character not in _SHA256 for character in self.source_commit)
        ):
            raise RobustnessValidationError(
                "source_commit must be a full lowercase Git commit"
            )
        for field in ("original_cache_namespace", "replay_cache_namespace"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise RobustnessValidationError(f"{field} must be nonempty")
        if self.original_cache_namespace == self.replay_cache_namespace:
            raise RobustnessValidationError(
                "receipt replay requires a fresh cache namespace"
            )

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            field: (
                getattr(self, field).value
                if isinstance(getattr(self, field), Enum)
                else getattr(self, field)
            )
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "replay validation")
        _exact(data, set(cls.__dataclass_fields__), "replay validation")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            status=_enum(ReplayStatus, data["status"], "status"),  # type: ignore[arg-type]
            case_id=data["case_id"],  # type: ignore[arg-type]
            original_run_id=data["original_run_id"],  # type: ignore[arg-type]
            replay_run_id=data["replay_run_id"],  # type: ignore[arg-type]
            original_result_sha256=data["original_result_sha256"],  # type: ignore[arg-type]
            replay_result_sha256=data["replay_result_sha256"],  # type: ignore[arg-type]
            original_receipt_sha256=data["original_receipt_sha256"],  # type: ignore[arg-type]
            replay_receipt_sha256=data["replay_receipt_sha256"],  # type: ignore[arg-type]
            environment_sha256=data["environment_sha256"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            worktree_receipt_sha256=data["worktree_receipt_sha256"],  # type: ignore[arg-type]
            original_cache_namespace=data["original_cache_namespace"],  # type: ignore[arg-type]
            replay_cache_namespace=data["replay_cache_namespace"],  # type: ignore[arg-type]
        )


def validate_replay(
    original: CaseResultRecord,
    replayed: CaseResultRecord,
    *,
    original_contract: RunContract,
    replay_contract: RunContract,
    expected_environment_sha256: str,
    worktree_receipt: WorktreeSafetyReceipt,
    expected_source_commit: str,
) -> ReplayValidationRecord:
    """Validate semantic receipt replay in a fresh worktree and cache namespace."""

    if not isinstance(original, CaseResultRecord) or not isinstance(
        replayed, CaseResultRecord
    ):
        raise RobustnessValidationError("replay requires case-result records")
    if not isinstance(original_contract, RunContract) or not isinstance(
        replay_contract, RunContract
    ):
        raise RobustnessValidationError("replay requires source and replay contracts")
    if not isinstance(worktree_receipt, WorktreeSafetyReceipt):
        raise RobustnessValidationError(
            "replay requires a validated worktree safety receipt"
        )
    expected_environment = _digest(
        expected_environment_sha256, "expected_environment_sha256"
    )
    try:
        # Round-trip first so corrupt embedded receipts fail before comparison.
        original = CaseResultRecord.from_dict(original.to_dict())
        replayed = CaseResultRecord.from_dict(replayed.to_dict())
        original_contract = RunContract.from_dict(original_contract.to_dict())
        replay_contract = RunContract.from_dict(replay_contract.to_dict())
        worktree_receipt = WorktreeSafetyReceipt.from_dict(
            worktree_receipt.to_dict()
        )
        validate_kernel_bound_result(original, expected_environment)
        validate_kernel_bound_result(replayed, expected_environment)
    except (
        ProtocolContractError,
        MetricsContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise RobustnessValidationError(
            "corrupt or stale receipt failed replay validation"
        ) from exc
    _validate_contract_result(original_contract, original)
    _validate_contract_result(replay_contract, replayed)
    if original.run_id == replayed.run_id:
        raise RobustnessValidationError("replay must use a fresh run id")
    if original_contract.cache_namespace == replay_contract.cache_namespace:
        raise RobustnessValidationError("replay must use a fresh cache namespace")
    if replay_contract.cache_mode is not CacheMode.COLD:
        raise RobustnessValidationError("receipt replay must start from a cold cache")
    if worktree_receipt.run_id != replayed.run_id:
        raise RobustnessValidationError(
            "worktree receipt is not scoped to the replay run"
        )
    if (
        worktree_receipt.base_commit != expected_source_commit
        or worktree_receipt.worktree_commit != expected_source_commit
    ):
        raise RobustnessValidationError("fresh worktree uses a stale source commit")
    if original_contract.configuration_sha256 != replay_contract.configuration_sha256:
        raise RobustnessValidationError("backend configuration drifted during replay")
    stable_identity = (
        original.protocol_sha256,
        original.case_id,
        original.case_manifest_sha256,
        original.variant_id,
        original.split,
    )
    replay_identity = (
        replayed.protocol_sha256,
        replayed.case_id,
        replayed.case_manifest_sha256,
        replayed.variant_id,
        replayed.split,
    )
    if stable_identity != replay_identity:
        raise RobustnessValidationError("replay changed the stable case identity")
    if (
        original.status is not replayed.status
        or original.failure_code is not replayed.failure_code
        or original.kernel_accepted != replayed.kernel_accepted
        or original.kernel_receipt_sha256 != replayed.kernel_receipt_sha256
    ):
        raise RobustnessValidationError("replay changed the terminal outcome")
    if len(original.stages) != len(replayed.stages):
        raise RobustnessValidationError("replay changed the stage route")
    for source_stage, replay_stage in zip(original.stages, replayed.stages):
        if (
            source_stage.stage is not replay_stage.stage
            or source_stage.status is not replay_stage.status
            or source_stage.adapter_version != replay_stage.adapter_version
            or source_stage.output_sha256 != replay_stage.output_sha256
            or source_stage.failure_code is not replay_stage.failure_code
            or source_stage.provenance.input_sha256
            != replay_stage.provenance.input_sha256
            or source_stage.provenance.requested_identity
            != replay_stage.provenance.requested_identity
            or source_stage.provenance.effective_identity
            != replay_stage.provenance.effective_identity
        ):
            raise RobustnessValidationError(
                f"backend or output drift at {source_stage.stage.value}"
            )
    if original.receipt is None or replayed.receipt is None:  # pragma: no cover
        raise RobustnessValidationError("case result is missing its receipt")
    if (
        original.receipt.reconstruction_sha256
        != replayed.receipt.reconstruction_sha256
    ):
        raise RobustnessValidationError("reconstruction receipt changed on replay")
    return ReplayValidationRecord(
        REPLAY_VALIDATION_SCHEMA,
        ReplayStatus.PASSED,
        original.case_id,
        original.run_id,
        replayed.run_id,
        original.digest,
        replayed.digest,
        original.provenance_receipt_sha256,
        replayed.provenance_receipt_sha256,
        expected_environment,
        expected_source_commit,
        worktree_receipt.sha256,
        original_contract.cache_namespace,
        replay_contract.cache_namespace,
    )


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    """Canonical aggregate requiring the full injection matrix and replay."""

    schema: str
    evidence: str
    failure_isolation: tuple[FailureIsolationRecord, ...]
    receipt_replays: tuple[ReplayValidationRecord, ...]

    def __post_init__(self) -> None:
        if self.schema != ROBUSTNESS_REPORT_SCHEMA:
            raise RobustnessValidationError("unsupported robustness-report schema")
        if self.evidence != HSSLEV0702E85():
            raise RobustnessValidationError("robustness evidence marker changed")
        if not isinstance(self.failure_isolation, tuple) or not isinstance(
            self.receipt_replays, tuple
        ):
            raise RobustnessValidationError("report members must be tuples")
        if any(
            not isinstance(item, FailureIsolationRecord)
            for item in self.failure_isolation
        ) or any(
            not isinstance(item, ReplayValidationRecord)
            for item in self.receipt_replays
        ):
            raise RobustnessValidationError("report contains an invalid record")
        kinds = tuple(item.kind for item in self.failure_isolation)
        if len(kinds) != len(set(kinds)) or set(kinds) != set(FailureInjectionKind):
            raise RobustnessValidationError(
                "report must cover each preregistered failure injection exactly once"
            )
        if not self.receipt_replays:
            raise RobustnessValidationError(
                "report requires at least one fresh-worktree receipt replay"
            )
        replay_cases = tuple(item.case_id for item in self.receipt_replays)
        if len(replay_cases) != len(set(replay_cases)):
            raise RobustnessValidationError("receipt replays contain duplicate cases")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    @property
    def stop_required(self) -> bool:
        return any(item.stop_required for item in self.failure_isolation)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "evidence": self.evidence,
            "failure_isolation": [
                item.to_dict() for item in self.failure_isolation
            ],
            "receipt_replays": [item.to_dict() for item in self.receipt_replays],
        }

    @classmethod
    def create(
        cls,
        failure_isolation: Sequence[FailureIsolationRecord],
        receipt_replays: Sequence[ReplayValidationRecord],
    ) -> Self:
        return cls(
            ROBUSTNESS_REPORT_SCHEMA,
            HSSLEV0702E85(),
            tuple(failure_isolation),
            tuple(receipt_replays),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "robustness report")
        _exact(data, set(cls.__dataclass_fields__), "robustness report")
        failures = data["failure_isolation"]
        replays = data["receipt_replays"]
        if not isinstance(failures, list) or not isinstance(replays, list):
            raise RobustnessValidationError("report members must be arrays")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            evidence=data["evidence"],  # type: ignore[arg-type]
            failure_isolation=tuple(
                FailureIsolationRecord.from_dict(item) for item in failures
            ),
            receipt_replays=tuple(
                ReplayValidationRecord.from_dict(item) for item in replays
            ),
        )


def canonical_robustness_report_json(report: RobustnessReport) -> str:
    if not isinstance(report, RobustnessReport):
        raise TypeError("report must be a RobustnessReport")
    return canonical_json(report.to_dict())


def write_robustness_report(
    robustness_report: RobustnessReport,
    destination: str | Path,
) -> Path:
    """Persist a canonical report once, refusing accidental replacement."""

    if not isinstance(robustness_report, RobustnessReport):
        raise TypeError("robustness_report must be a RobustnessReport")
    path = Path(destination)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_robustness_report_json(robustness_report))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RobustnessValidationError(
            f"refusing to overwrite immutable robustness report: {path}"
        ) from exc
    return path


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RobustnessValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_robustness_report(source: str | Path) -> RobustnessReport:
    """Load only strict, canonical, newline-terminated report evidence."""

    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RobustnessValidationError(
            f"cannot read robustness report: {path}"
        ) from exc
    if not text.endswith("\n"):
        raise RobustnessValidationError(
            "robustness report is not canonical newline JSON"
        )
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, RobustnessValidationError) as exc:
        raise RobustnessValidationError(
            "robustness report is not strict JSON"
        ) from exc
    loaded = RobustnessReport.from_dict(payload)
    if canonical_robustness_report_json(loaded) + "\n" != text:
        raise RobustnessValidationError("robustness report is not canonical JSON")
    return loaded


__all__ = [
    "BOUNDED_PROCESS_SCHEMA",
    "FAILURE_ISOLATION_SCHEMA",
    "REPLAY_VALIDATION_SCHEMA",
    "ROBUSTNESS_REPORT_SCHEMA",
    "BoundedProcessResult",
    "FailureInjectionKind",
    "FailureIsolationRecord",
    "HSSLEV0702E85",
    "ReplayStatus",
    "ReplayValidationRecord",
    "RobustnessReport",
    "RobustnessValidationError",
    "canonical_robustness_report_json",
    "load_robustness_report",
    "run_bounded_process",
    "validate_replay",
    "write_robustness_report",
]
