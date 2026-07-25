"""Fail-closed preflight contracts for the logic-pipeline benchmark.

This module owns two related safety boundaries:

* benchmark worktrees and mutable state are isolated from an operator's active
  checkout and are bound to an exact source commit; and
* every optional runtime used by a benchmark arm is inventoried before the arm
  can run.

Importing this module is deliberately inert.  It imports no optional backend,
reads no configuration, creates no directory, and executes no command.
Filesystem and process access occurs only through the explicit preparation and
probe functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from importlib import machinery, metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import stat
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import BENCHMARK_ID, RunPaths


CAPABILITY_INVENTORY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.capability-inventory.v1"
)
WORKTREE_SAFETY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.worktree-safety.v1"
)
WORKTREE_SAFETY_RECEIPT_NAME: Final = "worktree-safety.json"
RESOURCE_LEASE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.resource-lease.v1"
)
RESOURCE_POLICY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.resource-policy.v1"
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HEX_COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)"
    r"\s*[:=]\s*([^\s,;&]+)"
)
_REDACTED = "<redacted>"


class CapabilityContractError(ValueError):
    """Raised when capability or worktree evidence violates its schema."""


class CapabilityUnavailableError(RuntimeError):
    """Raised when a requested benchmark capability is not fully available."""


class CapabilityStatus(str, Enum):
    """The only states an optional benchmark capability may have."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class CapabilityKind(str, Enum):
    """The complete preregistered runtime inventory."""

    SPACY_PIPELINE = "spacy_pipeline"
    SYMAI = "symai"
    LLM_ROUTER = "llm_router"
    HAMMER = "hammer"
    LEANSTRAL_SERVICE = "leanstral_service"
    LEAN_TOOLCHAIN = "lean_toolchain"
    CACHE_BACKEND = "cache_backend"
    RESOURCE_SCHEDULER = "resource_scheduler"


REQUIRED_CAPABILITY_KINDS: Final = tuple(CapabilityKind)


class ResourceClass(str, Enum):
    """Operational lanes whose capacity must never be silently exchanged."""

    CPU = "cpu"
    MODEL = "model"
    SOLVER = "solver"
    KERNEL = "kernel"
    VALIDATION = "validation"


class ResourceLeaseError(RuntimeError):
    """Base class for bounded resource-scheduler failures."""


class ResourceLeaseTimeout(ResourceLeaseError):
    """Raised when a request cannot acquire capacity before its deadline."""


class ResourceLeaseCancelled(ResourceLeaseError):
    """Raised when a queued or active lease has been cancelled."""


def HSSLEV0724C07() -> str:
    """Return AST-verifiable evidence for the bounded resource boundary."""

    return (
        "identity-shared model leases, isolated solver and kernel lanes, "
        "measured queue delay, enforced caps, and reaped process groups"
    )


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Immutable capacity policy shared by every benchmark execution lane."""

    schema: str = RESOURCE_POLICY_SCHEMA
    max_workers: int = 1
    max_memory_bytes: int = 8 * 1024 * 1024 * 1024
    max_model_instances: int = 1
    max_model_workers: int = 1
    max_solver_processes: int = 1
    max_kernel_workers: int = 1
    max_validation_workers: int = 1
    queue_timeout_seconds: float = 120.0
    cancellation_grace_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.schema != RESOURCE_POLICY_SCHEMA:
            raise CapabilityContractError("unsupported resource-policy schema")
        integer_fields = {
            "max_workers": (1, 32),
            "max_memory_bytes": (1, 1 << 40),
            "max_model_instances": (1, 32),
            "max_model_workers": (1, 32),
            "max_solver_processes": (0, 1_000),
            "max_kernel_workers": (1, 32),
            "max_validation_workers": (1, 32),
        }
        for name, (minimum, maximum) in integer_fields.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise CapabilityContractError(
                    f"{name} must be an integer from {minimum} to {maximum}"
                )
        for name in ("queue_timeout_seconds", "cancellation_grace_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 < float(value) <= 86_400
            ):
                raise CapabilityContractError(
                    f"{name} must be finite and from 0 to 86400"
                )

    @classmethod
    def from_resource_limits(cls, limits: object) -> "ResourcePolicy":
        """Build a policy from the runner's structural ``ResourceLimits``.

        Structural access avoids a capabilities-to-runner import cycle and
        deliberately fails closed if a caller supplies an incomplete object.
        """

        required = (
            "max_workers",
            "max_memory_bytes",
            "max_solver_processes_per_case",
            "case_timeout_seconds",
        )
        if any(not hasattr(limits, name) for name in required):
            raise CapabilityContractError(
                "limits do not provide the required resource ceilings"
            )
        workers = getattr(limits, "max_workers")
        return cls(
            max_workers=workers,
            max_memory_bytes=getattr(limits, "max_memory_bytes"),
            max_model_instances=1,
            max_model_workers=workers,
            max_solver_processes=getattr(
                limits, "max_solver_processes_per_case"
            ),
            max_kernel_workers=workers,
            max_validation_workers=workers,
            queue_timeout_seconds=getattr(limits, "case_timeout_seconds"),
            cancellation_grace_seconds=min(
                2.0, float(getattr(limits, "case_timeout_seconds"))
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            name: (
                getattr(self, name).value
                if isinstance(getattr(self, name), Enum)
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResourcePolicy":
        data = _mapping(value, "resource_policy")
        _exact_keys(data, set(cls.__dataclass_fields__), "resource_policy")
        try:
            return cls(**data)  # type: ignore[arg-type]
        except TypeError as exc:
            raise CapabilityContractError(
                "invalid resource-policy fields"
            ) from exc


@dataclass(frozen=True, slots=True)
class ResourceLeaseRequest:
    """One bounded request for an operational resource lane."""

    owner_id: str
    resource_class: ResourceClass
    units: int = 1
    memory_bytes: int = 0
    model_identity: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        _safe_id(self.owner_id, "owner_id")
        if not isinstance(self.resource_class, ResourceClass):
            raise CapabilityContractError(
                "resource_class must be a ResourceClass"
            )
        if (
            isinstance(self.units, bool)
            or not isinstance(self.units, int)
            or not 1 <= self.units <= 1_000
        ):
            raise CapabilityContractError("units must be an integer from 1 to 1000")
        if (
            isinstance(self.memory_bytes, bool)
            or not isinstance(self.memory_bytes, int)
            or not 0 <= self.memory_bytes <= 1 << 40
        ):
            raise CapabilityContractError(
                "memory_bytes must be an integer from 0 to 2^40"
            )
        if self.resource_class is ResourceClass.MODEL:
            _safe_id(self.model_identity, "model_identity")
        elif self.model_identity is not None:
            raise CapabilityContractError(
                "model_identity is valid only for the model resource class"
            )
        if self.timeout_seconds is not None and (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 0 < float(self.timeout_seconds) <= 86_400
        ):
            raise CapabilityContractError(
                "timeout_seconds must be finite and from 0 to 86400"
            )


@dataclass(frozen=True, slots=True)
class ResourceLeaseReceipt:
    """Canonical, duration-only evidence for one completed lease."""

    schema: str
    sequence: int
    owner_id: str
    resource_class: ResourceClass
    units: int
    memory_bytes: int
    model_identity: str | None
    queue_delay_ms: float
    held_ms: float
    shared_model_instance: bool
    outcome: str
    detail: str | None

    def __post_init__(self) -> None:
        if self.schema != RESOURCE_LEASE_SCHEMA:
            raise CapabilityContractError("unsupported resource-lease schema")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise CapabilityContractError(
                "resource lease sequence must be nonnegative"
            )
        # Reuse the request validator for identities, counts, and lane rules.
        ResourceLeaseRequest(
            self.owner_id,
            self.resource_class,
            self.units,
            self.memory_bytes,
            self.model_identity,
        )
        for name in ("queue_delay_ms", "held_ms"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 86_400_000
            ):
                raise CapabilityContractError(
                    f"{name} must be finite and from 0 to 86400000"
                )
        if type(self.shared_model_instance) is not bool:
            raise CapabilityContractError(
                "shared_model_instance must be a boolean"
            )
        if self.outcome not in {"released", "cancelled"}:
            raise CapabilityContractError(
                "resource lease outcome must be released or cancelled"
            )
        if self.detail is not None and (
            not isinstance(self.detail, str)
            or not self.detail.strip()
            or len(self.detail) > 512
        ):
            raise CapabilityContractError(
                "resource lease detail must be 1-512 characters"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            name: (
                getattr(self, name).value
                if isinstance(getattr(self, name), Enum)
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResourceLeaseReceipt":
        data = _mapping(value, "resource_lease")
        _exact_keys(data, set(cls.__dataclass_fields__), "resource_lease")
        try:
            resource_class = ResourceClass(data["resource_class"])
        except (TypeError, ValueError) as exc:
            raise CapabilityContractError(
                "resource_lease.resource_class is invalid"
            ) from exc
        try:
            return cls(
                schema=data["schema"],  # type: ignore[arg-type]
                sequence=data["sequence"],  # type: ignore[arg-type]
                owner_id=data["owner_id"],  # type: ignore[arg-type]
                resource_class=resource_class,
                units=data["units"],  # type: ignore[arg-type]
                memory_bytes=data["memory_bytes"],  # type: ignore[arg-type]
                model_identity=data["model_identity"],  # type: ignore[arg-type]
                queue_delay_ms=data["queue_delay_ms"],  # type: ignore[arg-type]
                held_ms=data["held_ms"],  # type: ignore[arg-type]
                shared_model_instance=data["shared_model_instance"],  # type: ignore[arg-type]
                outcome=data["outcome"],  # type: ignore[arg-type]
                detail=data["detail"],  # type: ignore[arg-type]
            )
        except TypeError as exc:
            raise CapabilityContractError(
                "invalid resource-lease fields"
            ) from exc


class ResourceLease:
    """Owned scheduler capacity that must be released exactly once."""

    __slots__ = (
        "_scheduler",
        "request",
        "sequence",
        "queue_delay_ms",
        "shared_model_instance",
        "_acquired_at",
        "_released",
    )

    def __init__(
        self,
        scheduler: "ResourceScheduler",
        request: ResourceLeaseRequest,
        sequence: int,
        queue_delay_ms: float,
        shared_model_instance: bool,
        acquired_at: float,
    ) -> None:
        self._scheduler = scheduler
        self.request = request
        self.sequence = sequence
        self.queue_delay_ms = queue_delay_ms
        self.shared_model_instance = shared_model_instance
        self._acquired_at = acquired_at
        self._released = False

    @property
    def cancelled(self) -> bool:
        return self._scheduler.is_cancelled(self.request.owner_id)

    def assert_active(self) -> None:
        if self._released:
            raise ResourceLeaseError("resource lease is already released")
        if self.cancelled:
            raise ResourceLeaseCancelled(
                f"resource lease cancelled for {self.request.owner_id}"
            )

    def release(self, *, detail: str | None = None) -> ResourceLeaseReceipt:
        if self._released:
            raise ResourceLeaseError("resource lease cannot be released twice")
        self._released = True
        return self._scheduler._release(self, detail=detail)

    def __enter__(self) -> "ResourceLease":
        self.assert_active()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        detail = None
        if exc is not None:
            detail = f"{type(exc).__name__}: lease scope failed"[:512]
        self.release(detail=detail)


class ResourceScheduler:
    """Thread-safe, bounded lease arbiter for benchmark resource classes.

    Model leases are identity-aware: concurrent SyMAI and Leanstral requests
    for the same pinned model share one instance, while a second identity
    waits rather than instantiating another large model.  Solver, kernel, and
    validation capacity remain distinct and are never borrowed across lanes.
    """

    def __init__(self, policy: ResourcePolicy = ResourcePolicy()) -> None:
        if not isinstance(policy, ResourcePolicy):
            raise CapabilityContractError("policy must be a ResourcePolicy")
        self.policy = policy
        self._condition = threading.Condition()
        self._active_workers = 0
        self._active_memory = 0
        self._active_by_class = {item: 0 for item in ResourceClass}
        self._model_references: dict[str, int] = {}
        self._loaded_model_identities: set[str] = set()
        self._cancelled_owners: set[str] = set()
        self._sequence = 0
        self._receipts: list[ResourceLeaseReceipt] = []

    @property
    def receipts(self) -> tuple[ResourceLeaseReceipt, ...]:
        with self._condition:
            return tuple(self._receipts)

    @property
    def active_model_identities(self) -> tuple[str, ...]:
        with self._condition:
            return tuple(sorted(self._model_references))

    @property
    def loaded_model_identities(self) -> tuple[str, ...]:
        """Pinned model instances admitted during this scheduler's lifetime."""

        with self._condition:
            return tuple(sorted(self._loaded_model_identities))

    def is_cancelled(self, owner_id: str) -> bool:
        _safe_id(owner_id, "owner_id")
        with self._condition:
            return owner_id in self._cancelled_owners

    def cancel(self, owner_id: str) -> None:
        """Cancel queued/acquired work cooperatively and wake all waiters."""

        _safe_id(owner_id, "owner_id")
        with self._condition:
            self._cancelled_owners.add(owner_id)
            self._condition.notify_all()

    def _class_limit(self, resource_class: ResourceClass) -> int:
        return {
            ResourceClass.CPU: self.policy.max_workers,
            ResourceClass.MODEL: self.policy.max_model_workers,
            ResourceClass.SOLVER: self.policy.max_solver_processes,
            ResourceClass.KERNEL: self.policy.max_kernel_workers,
            ResourceClass.VALIDATION: self.policy.max_validation_workers,
        }[resource_class]

    def _can_acquire(self, request: ResourceLeaseRequest) -> bool:
        if self._active_workers + request.units > self.policy.max_workers:
            return False
        if (
            self._active_memory + request.memory_bytes
            > self.policy.max_memory_bytes
        ):
            return False
        if (
            self._active_by_class[request.resource_class] + request.units
            > self._class_limit(request.resource_class)
        ):
            return False
        if request.resource_class is ResourceClass.MODEL:
            assert request.model_identity is not None
            identities = set(self._loaded_model_identities)
            identities.add(request.model_identity)
            if len(identities) > self.policy.max_model_instances:
                return False
        return True

    def acquire(self, request: ResourceLeaseRequest) -> ResourceLease:
        if not isinstance(request, ResourceLeaseRequest):
            raise CapabilityContractError(
                "request must be a ResourceLeaseRequest"
            )
        if (
            request.units > self.policy.max_workers
            or request.units > self._class_limit(request.resource_class)
            or request.memory_bytes > self.policy.max_memory_bytes
        ):
            raise ResourceLeaseError(
                f"resource request can never fit policy for {request.owner_id}"
            )
        timeout = (
            self.policy.queue_timeout_seconds
            if request.timeout_seconds is None
            else float(request.timeout_seconds)
        )
        queued_at = time.monotonic()
        deadline = queued_at + timeout
        with self._condition:
            while not self._can_acquire(request):
                if request.owner_id in self._cancelled_owners:
                    raise ResourceLeaseCancelled(
                        f"resource request cancelled for {request.owner_id}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ResourceLeaseTimeout(
                        f"resource queue timeout for {request.owner_id}"
                    )
                self._condition.wait(remaining)
            if request.owner_id in self._cancelled_owners:
                raise ResourceLeaseCancelled(
                    f"resource request cancelled for {request.owner_id}"
                )
            acquired_at = time.monotonic()
            shared = bool(
                request.resource_class is ResourceClass.MODEL
                and request.model_identity in self._loaded_model_identities
            )
            self._active_workers += request.units
            self._active_memory += request.memory_bytes
            self._active_by_class[request.resource_class] += request.units
            if request.resource_class is ResourceClass.MODEL:
                assert request.model_identity is not None
                self._loaded_model_identities.add(request.model_identity)
                self._model_references[request.model_identity] = (
                    self._model_references.get(request.model_identity, 0) + 1
                )
            sequence = self._sequence
            self._sequence += 1
            return ResourceLease(
                self,
                request,
                sequence,
                round((acquired_at - queued_at) * 1_000, 6),
                shared,
                acquired_at,
            )

    def _release(
        self, lease: ResourceLease, *, detail: str | None
    ) -> ResourceLeaseReceipt:
        if lease._scheduler is not self:
            raise ResourceLeaseError("resource lease belongs to another scheduler")
        request = lease.request
        released_at = time.monotonic()
        with self._condition:
            self._active_workers -= request.units
            self._active_memory -= request.memory_bytes
            self._active_by_class[request.resource_class] -= request.units
            if request.resource_class is ResourceClass.MODEL:
                assert request.model_identity is not None
                references = self._model_references[request.model_identity] - 1
                if references:
                    self._model_references[request.model_identity] = references
                else:
                    del self._model_references[request.model_identity]
            cancelled = request.owner_id in self._cancelled_owners
            receipt = ResourceLeaseReceipt(
                schema=RESOURCE_LEASE_SCHEMA,
                sequence=lease.sequence,
                owner_id=request.owner_id,
                resource_class=request.resource_class,
                units=request.units,
                memory_bytes=request.memory_bytes,
                model_identity=request.model_identity,
                queue_delay_ms=lease.queue_delay_ms,
                held_ms=round((released_at - lease._acquired_at) * 1_000, 6),
                shared_model_instance=lease.shared_model_instance,
                outcome="cancelled" if cancelled or detail else "released",
                detail=detail,
            )
            self._receipts.append(receipt)
            self._condition.notify_all()
            return receipt


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """Result of a command whose complete process group was reaped."""

    arguments: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    process_group_reaped: bool
    termination_reason: str = "completed"


def _active_process_group_members(process_group_id: int) -> tuple[int, ...]:
    """Return live members of a POSIX process group.

    ``Popen.poll()`` only observes the group leader.  On Linux, inspect every
    process' kernel-reported group and exclude zombies, which no longer
    execute and can only be collected by their current parent.  The fallback
    is conservative on other POSIX systems because ``killpg(..., 0)`` cannot
    distinguish a live member from a zombie.
    """

    if os.name != "posix" or process_group_id <= 0:
        return ()
    proc_root = Path("/proc")
    if proc_root.is_dir():
        members: list[int] = []
        try:
            process_entries = tuple(proc_root.iterdir())
        except OSError:
            process_entries = ()
        for entry in process_entries:
            if not entry.name.isdigit():
                continue
            try:
                raw_stat = (entry / "stat").read_text(encoding="utf-8")
                closing_parenthesis = raw_stat.rfind(")")
                if closing_parenthesis < 0:
                    continue
                fields = raw_stat[closing_parenthesis + 2 :].split()
                state = fields[0]
                member_group_id = int(fields[2])
            except (OSError, IndexError, ValueError):
                continue
            if member_group_id == process_group_id and state != "Z":
                members.append(int(entry.name))
        return tuple(sorted(members))
    try:  # pragma: no cover - Linux provides the stronger branch above.
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return ()
    except PermissionError:
        return (process_group_id,)
    else:
        return (process_group_id,)


def _wait_for_process_group_exit(
    process_group_id: int,
    timeout_seconds: float,
) -> bool:
    """Wait a bounded interval for every executable group member to exit."""

    deadline = time.monotonic() + timeout_seconds
    while _active_process_group_members(process_group_id):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
    return True


def _reap_bounded_process_group(
    process_group_id: int,
    *,
    cancellation_grace_seconds: float,
) -> bool:
    """Terminate surviving descendants and prove that the group is quiescent."""

    if os.name != "posix":
        return True
    if not _active_process_group_members(process_group_id):
        return True
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    if _wait_for_process_group_exit(
        process_group_id,
        cancellation_grace_seconds,
    ):
        return True
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    return _wait_for_process_group_exit(
        process_group_id,
        cancellation_grace_seconds,
    )


def run_bounded_process_group(
    arguments: Sequence[str],
    *,
    timeout_seconds: float,
    cancellation_grace_seconds: float = 2.0,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
    max_output_bytes: int = 64 * 1024,
) -> BoundedProcessResult:
    """Run without a shell and reap the entire child process group on timeout."""

    command = tuple(arguments)
    if (
        not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        raise CapabilityContractError(
            "arguments must be a nonempty sequence of strings"
        )
    for name, value in {
        "timeout_seconds": timeout_seconds,
        "cancellation_grace_seconds": cancellation_grace_seconds,
    }.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 < float(value) <= 86_400
        ):
            raise CapabilityContractError(
                f"{name} must be finite and from 0 to 86400"
            )
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or not 1 <= max_output_bytes <= 16 * 1024 * 1024
    ):
        raise CapabilityContractError(
            "max_output_bytes must be from 1 to 16777216"
        )
    if input_bytes is not None and not isinstance(input_bytes, bytes):
        raise CapabilityContractError("input_bytes must be bytes or None")
    if input_bytes is not None and len(input_bytes) > 16 * 1024 * 1024:
        raise CapabilityContractError(
            "input_bytes must not exceed 16777216 bytes"
        )
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=None if env is None else dict(env),
            stdin=(
                subprocess.DEVNULL
                if input_bytes is None
                else subprocess.PIPE
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise ResourceLeaseError(
            f"cannot start bounded process: {type(exc).__name__}"
        ) from exc
    timed_out = False
    try:
        stdout, stderr = process.communicate(
            input=input_bytes,
            timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name != "posix":
                raise AttributeError
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, ProcessLookupError, PermissionError):
            process.terminate()
        try:
            stdout, stderr = process.communicate(
                timeout=float(cancellation_grace_seconds)
            )
        except subprocess.TimeoutExpired:
            try:
                if os.name != "posix":
                    raise AttributeError
                os.killpg(process.pid, signal.SIGKILL)
            except (AttributeError, ProcessLookupError, PermissionError):
                process.kill()
            stdout, stderr = process.communicate()
    surviving_descendants = bool(
        _active_process_group_members(process.pid)
    )
    process_group_reaped = (
        _reap_bounded_process_group(
            process.pid,
            cancellation_grace_seconds=float(cancellation_grace_seconds),
        )
        if os.name == "posix"
        else process.poll() is not None
    )
    if not process_group_reaped:
        termination_reason = "orphaned_process_group"
    elif timed_out:
        termination_reason = "wall_clock_deadline"
    elif process.returncode is None:
        termination_reason = "process_error"
    elif process.returncode < 0:
        termination_reason = "signal_exit"
    elif process.returncode > 0:
        termination_reason = "nonzero_exit"
    elif surviving_descendants:
        termination_reason = "completed_with_descendant_cleanup"
    else:
        termination_reason = "completed"
    return BoundedProcessResult(
        arguments=command,
        returncode=process.returncode,
        stdout=stdout[:max_output_bytes].decode("utf-8", errors="replace"),
        stderr=stderr[:max_output_bytes].decode("utf-8", errors="replace"),
        timed_out=timed_out,
        process_group_reaped=process_group_reaped,
        termination_reason=termination_reason,
    )


def HSSLEV0118D14() -> str:
    """Return AST-verifiable evidence for HSSL-G011."""

    return "isolated worktree and state-root safety"


def HSSLEV0125F83() -> str:
    """Return AST-verifiable evidence for HSSL-G012."""

    return "runtime capabilities and identities"


def _safe_id(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise CapabilityContractError(
            f"{field_name} must be a safe 1-128 character identifier"
        )
    return value


def _is_run_paths(value: object) -> bool:
    """Recognize RunPaths across a deliberate package-module reload.

    The package smoke test reloads :mod:`benchmarks.logic_pipeline` to prove
    import inertness.  Reloading recreates the dataclass while this submodule
    remains cached, so a nominal ``isinstance`` check would reject an otherwise
    genuine value solely because its class object predates the reload.
    """

    value_type = type(value)
    return (
        value_type.__module__ == "benchmarks.logic_pipeline"
        and value_type.__name__ == "RunPaths"
        and all(
            hasattr(value, attribute)
            for attribute in (
                "run_id",
                "run_root",
                "cache",
                "receipts",
                "state",
                "worktrees",
                "directories",
                "materialize",
            )
        )
    )


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if not missing and not unknown:
        return
    details: list[str] = []
    if missing:
        details.append(f"missing {sorted(missing)}")
    if unknown:
        details.append(f"unknown {sorted(unknown)}")
    raise CapabilityContractError(f"{field_name} has " + " and ".join(details))


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CapabilityContractError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise CapabilityContractError(f"{field_name} keys must be strings")
    return value


def _sanitize_url(value: str) -> str:
    """Remove endpoint credentials and secret query values."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return _SECRET_TEXT.sub(r"\1=<redacted>", value)
    if not parsed.scheme or not parsed.netloc:
        return _SECRET_TEXT.sub(r"\1=<redacted>", value)

    try:
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return _SECRET_TEXT.sub(r"\1=<redacted>", value.split("@")[-1])
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if port is not None:
        hostname = f"{hostname}:{port}"
    query = [
        (key, _REDACTED if _SECRET_KEY.search(key) else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, hostname, parsed.path, urlencode(query), "")
    )


def redact_secrets(value: object, *, _key: str | None = None) -> object:
    """Return a JSON-like value with credentials recursively removed.

    Secret-bearing fields retain only a redaction marker, which proves that a
    configuration value was present without persisting it.  URLs retain their
    scheme, host, path, and non-secret query identity while dropping userinfo,
    fragments, and secret query values.
    """

    if _key is not None and _SECRET_KEY.search(_key):
        return _REDACTED if value not in (None, "", False) else value
    if isinstance(value, Mapping):
        return {
            str(key): redact_secrets(item, _key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        if _key is not None and (
            "endpoint" in _key.lower() or _key.lower().endswith("url")
        ):
            return _sanitize_url(value)
        return _SECRET_TEXT.sub(r"\1=<redacted>", value)
    return value


def _freeze_json(value: object, field_name: str) -> object:
    """Validate, canonicalize, and deeply freeze a JSON-compatible value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CapabilityContractError(
                f"{field_name} must contain finite canonical JSON values"
            )
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CapabilityContractError(
                f"{field_name} must contain only string object keys"
            )
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{field_name}.{key}")
                for key in sorted(value)
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{field_name}[]") for item in value
        )
    raise CapabilityContractError(
        f"{field_name} must contain only canonical JSON values"
    )


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One optional runtime's status, identity, and probe provenance."""

    kind: CapabilityKind
    status: CapabilityStatus
    identity: Mapping[str, object] = field(default_factory=dict)
    provenance: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        try:
            kind = (
                self.kind
                if isinstance(self.kind, CapabilityKind)
                else CapabilityKind(self.kind)
            )
        except (TypeError, ValueError) as exc:
            raise CapabilityContractError(
                f"unsupported capability kind: {self.kind!r}"
            ) from exc
        try:
            status = (
                self.status
                if isinstance(self.status, CapabilityStatus)
                else CapabilityStatus(self.status)
            )
        except (TypeError, ValueError) as exc:
            raise CapabilityContractError(
                f"unsupported capability status: {self.status!r}"
            ) from exc

        identity = _mapping(self.identity, "identity")
        sanitized = redact_secrets(identity)
        frozen_identity = _freeze_json(sanitized, "identity")
        provenance = tuple(self.provenance)
        if not provenance or any(
            not isinstance(item, str) or not item.strip()
            for item in provenance
        ):
            raise CapabilityContractError(
                "provenance must contain at least one nonempty source"
            )
        if len(provenance) != len(set(provenance)):
            raise CapabilityContractError("provenance must not contain duplicates")

        reason = self.reason
        if status is CapabilityStatus.AVAILABLE and not identity:
            raise CapabilityContractError(
                "an available capability requires a nonempty identity"
            )
        if status is not CapabilityStatus.AVAILABLE and (
            not isinstance(reason, str) or not reason.strip()
        ):
            raise CapabilityContractError(
                "a degraded or unavailable capability requires a reason"
            )
        if reason is not None:
            reason = str(redact_secrets(reason)).strip()

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "identity", frozen_identity)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "reason", reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "status": self.status.value,
            "identity": _thaw_json(self.identity),
            "provenance": list(self.provenance),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CapabilityRecord":
        payload = _mapping(value, "capability")
        _exact_keys(
            payload,
            {"kind", "status", "identity", "provenance", "reason"},
            "capability",
        )
        provenance = payload["provenance"]
        if not isinstance(provenance, (list, tuple)):
            raise CapabilityContractError("capability.provenance must be an array")
        return cls(
            kind=payload["kind"],  # type: ignore[arg-type]
            status=payload["status"],  # type: ignore[arg-type]
            identity=_mapping(payload["identity"], "capability.identity"),
            provenance=tuple(provenance),  # type: ignore[arg-type]
            reason=payload["reason"],  # type: ignore[arg-type]
        )


def _default_environment_identity() -> dict[str, object]:
    return {
        "benchmark_id": BENCHMARK_ID,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
    }


@dataclass(frozen=True, slots=True)
class CapabilityInventory:
    """A complete, deterministic preflight inventory for one run."""

    schema: str
    run_id: str
    environment: Mapping[str, object]
    source_commit: str | None
    capabilities: tuple[CapabilityRecord, ...]

    def __post_init__(self) -> None:
        if self.schema != CAPABILITY_INVENTORY_SCHEMA:
            raise CapabilityContractError(
                f"unsupported capability inventory schema: {self.schema!r}"
            )
        _safe_id(self.run_id, "run_id")
        environment = _freeze_json(
            redact_secrets(_mapping(self.environment, "environment")),
            "environment",
        )
        if self.source_commit is not None and (
            not isinstance(self.source_commit, str)
            or not _HEX_COMMIT.fullmatch(self.source_commit)
        ):
            raise CapabilityContractError(
                "source_commit must be a full lowercase Git commit id"
            )

        records = tuple(self.capabilities)
        if not all(isinstance(record, CapabilityRecord) for record in records):
            raise CapabilityContractError(
                "capabilities must contain CapabilityRecord values"
            )
        actual = [record.kind for record in records]
        duplicates = sorted(
            kind.value for kind in set(actual) if actual.count(kind) > 1
        )
        if duplicates:
            raise CapabilityContractError(
                f"capabilities contain duplicate kinds: {duplicates}"
            )
        missing = set(REQUIRED_CAPABILITY_KINDS) - set(actual)
        unknown = set(actual) - set(REQUIRED_CAPABILITY_KINDS)
        if missing or unknown or len(records) != len(REQUIRED_CAPABILITY_KINDS):
            raise CapabilityContractError(
                "capabilities must contain exactly the required kinds; "
                f"missing={sorted(kind.value for kind in missing)}, "
                f"unknown={sorted(kind.value for kind in unknown)}"
            )
        order = {kind: index for index, kind in enumerate(REQUIRED_CAPABILITY_KINDS)}
        records = tuple(sorted(records, key=lambda record: order[record.kind]))
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "capabilities", records)

    @classmethod
    def create(
        cls,
        run_id: str,
        capabilities: Sequence[CapabilityRecord],
        *,
        environment: Mapping[str, object] | None = None,
        source_commit: str | None = None,
    ) -> "CapabilityInventory":
        return cls(
            schema=CAPABILITY_INVENTORY_SCHEMA,
            run_id=run_id,
            environment=environment or _default_environment_identity(),
            source_commit=source_commit,
            capabilities=tuple(capabilities),
        )

    @property
    def by_kind(self) -> Mapping[CapabilityKind, CapabilityRecord]:
        return MappingProxyType(
            {record.kind: record for record in self.capabilities}
        )

    @property
    def sha256(self) -> str:
        return capability_inventory_sha256(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "environment": _thaw_json(self.environment),
            "source_commit": self.source_commit,
            "capabilities": [
                record.to_dict() for record in self.capabilities
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> "CapabilityInventory":
        payload = _mapping(value, "capability inventory")
        _exact_keys(
            payload,
            {
                "schema",
                "run_id",
                "environment",
                "source_commit",
                "capabilities",
            },
            "capability inventory",
        )
        raw_records = payload["capabilities"]
        if not isinstance(raw_records, (list, tuple)):
            raise CapabilityContractError(
                "capability inventory.capabilities must be an array"
            )
        return cls(
            schema=payload["schema"],  # type: ignore[arg-type]
            run_id=payload["run_id"],  # type: ignore[arg-type]
            environment=_mapping(
                payload["environment"],
                "capability inventory.environment",
            ),
            source_commit=payload["source_commit"],  # type: ignore[arg-type]
            capabilities=tuple(
                CapabilityRecord.from_dict(record) for record in raw_records
            ),
        )


def canonical_capability_inventory_json(
    inventory: CapabilityInventory,
) -> str:
    if not isinstance(inventory, CapabilityInventory):
        raise TypeError("inventory must be a CapabilityInventory")
    return _canonical_json(inventory.to_dict())


def capability_inventory_sha256(inventory: CapabilityInventory) -> str:
    return hashlib.sha256(
        canonical_capability_inventory_json(inventory).encode("utf-8")
    ).hexdigest()


FindSpec = Callable[[str], object | None]
DistributionVersion = Callable[[str], str]
ExecutableFinder = Callable[[str], str | None]
CommandRunner = Callable[[Sequence[str]], str]
CapabilityProbe = Callable[["ProbeContext"], CapabilityRecord]


def _find_spec_without_import(name: str) -> object | None:
    """Find a module path without importing a package parent.

    ``importlib.util.find_spec("package.child")`` imports ``package`` to obtain
    its search path.  Capability discovery must not execute production package
    initializers, so nested names are resolved by inspecting package locations.
    """

    root, separator, remainder = name.partition(".")
    root_spec = machinery.PathFinder.find_spec(root)
    if not separator or root_spec is None:
        return root_spec
    locations = root_spec.submodule_search_locations
    if not locations:
        return None
    relative = Path(*remainder.split("."))
    for location in locations:
        base = Path(location) / relative
        if base.with_suffix(".py").is_file() or (
            base.is_dir() and (base / "__init__.py").is_file()
        ):
            # Only truthiness is part of ProbeContext's contract.
            return base
    return None


def _run_version_command(arguments: Sequence[str]) -> str:
    if not arguments:
        raise ValueError("version command must not be empty")
    completed = subprocess.run(
        list(arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )
    output = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0:
        raise RuntimeError(
            f"version command exited with status {completed.returncode}"
        )
    return output[0][:512] if output else "version not reported"


@dataclass(frozen=True, slots=True)
class ProbeContext:
    """Injected read-only inputs available to capability probes."""

    run_paths: RunPaths
    environ: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(dict(os.environ))
    )
    find_spec: FindSpec = _find_spec_without_import
    distribution_version: DistributionVersion = metadata.version
    which: ExecutableFinder = shutil.which
    run_command: CommandRunner = _run_version_command

    def __post_init__(self) -> None:
        if not _is_run_paths(self.run_paths):
            raise CapabilityContractError("run_paths must be a RunPaths value")
        if not isinstance(self.environ, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.environ.items()
        ):
            raise CapabilityContractError(
                "probe environment must map strings to strings"
            )
        object.__setattr__(
            self, "environ", MappingProxyType(dict(self.environ))
        )


def _version(context: ProbeContext, *distributions: str) -> str | None:
    for distribution in distributions:
        try:
            return context.distribution_version(distribution)
        except metadata.PackageNotFoundError:
            continue
        except Exception:
            continue
    return None


def _command_identity(
    context: ProbeContext,
    command: str,
    *version_arguments: str,
) -> dict[str, str] | None:
    executable = context.which(command)
    if not executable:
        return None
    path = str(Path(executable).resolve())
    try:
        version = context.run_command((path, *version_arguments))
    except Exception as exc:
        version = f"unverified ({type(exc).__name__})"
    return {"path": path, "version": version}


def _spacy_probe(context: ProbeContext) -> CapabilityRecord:
    version = _version(context, "spacy")
    requested = context.environ.get("HSSL_SPACY_MODEL", "en_core_web_sm")
    installed_pipelines: list[str] = []
    try:
        entry_points = metadata.entry_points()
        candidates = (
            entry_points.select(group="spacy_models")
            if hasattr(entry_points, "select")
            else entry_points.get("spacy_models", ())
        )
        installed_pipelines = sorted(
            {
                str(entry_point.name)
                for entry_point in candidates
                if getattr(entry_point, "name", None)
            }
        )
    except Exception:
        # Distribution metadata differs across supported Python/package
        # versions. Failure to enumerate never implies a model is available.
        installed_pipelines = []
    if version is None:
        return CapabilityRecord(
            CapabilityKind.SPACY_PIPELINE,
            CapabilityStatus.UNAVAILABLE,
            {
                "requested_model": requested,
                "installed_pipelines": installed_pipelines,
            },
            ("python-distribution-metadata", "environment:HSSL_SPACY_MODEL"),
            "spaCy distribution is not installed",
        )
    model_version = _version(context, requested)
    if model_version is not None or requested in installed_pipelines:
        return CapabilityRecord(
            CapabilityKind.SPACY_PIPELINE,
            CapabilityStatus.AVAILABLE,
            {
                "spacy_version": version,
                "requested_model": requested,
                "effective_model": requested,
                "model_version": model_version,
                "installed_pipelines": installed_pipelines,
                "fallback": False,
            },
            ("python-distribution-metadata", "environment:HSSL_SPACY_MODEL"),
        )
    fallback = context.environ.get("HSSL_SPACY_FALLBACK")
    if fallback:
        return CapabilityRecord(
            CapabilityKind.SPACY_PIPELINE,
            CapabilityStatus.DEGRADED,
            {
                "spacy_version": version,
                "requested_model": requested,
                "effective_model": fallback,
                "installed_pipelines": installed_pipelines,
                "fallback": True,
            },
            (
                "python-distribution-metadata",
                "environment:HSSL_SPACY_MODEL",
                "environment:HSSL_SPACY_FALLBACK",
            ),
            "requested spaCy pipeline is absent; explicit fallback recorded",
        )
    return CapabilityRecord(
        CapabilityKind.SPACY_PIPELINE,
        CapabilityStatus.UNAVAILABLE,
        {
            "spacy_version": version,
            "requested_model": requested,
            "installed_pipelines": installed_pipelines,
        },
        ("python-distribution-metadata", "environment:HSSL_SPACY_MODEL"),
        "requested spaCy pipeline is not installed",
    )


def _symai_probe(context: ProbeContext) -> CapabilityRecord:
    version = _version(context, "symbolicai", "symai")
    provider = context.environ.get("HSSL_SYMAI_PROVIDER")
    model = context.environ.get("HSSL_SYMAI_MODEL")
    identity = {
        "package_version": version,
        "requested_provider": provider,
        "requested_model": model,
        "credential_configured": any(
            bool(value)
            for key, value in context.environ.items()
            if key.startswith("HSSL_SYMAI_") and _SECRET_KEY.search(key)
        ),
    }
    provenance = (
        "python-distribution-metadata",
        "environment:HSSL_SYMAI_PROVIDER",
        "environment:HSSL_SYMAI_MODEL",
        "credential-presence-only",
    )
    if version is None:
        return CapabilityRecord(
            CapabilityKind.SYMAI,
            CapabilityStatus.UNAVAILABLE,
            identity,
            provenance,
            "SyMAI/SymbolicAI distribution is not installed",
        )
    if not provider or not model:
        return CapabilityRecord(
            CapabilityKind.SYMAI,
            CapabilityStatus.DEGRADED,
            identity,
            provenance,
            "SyMAI package is present but provider/model identity is incomplete",
        )
    return CapabilityRecord(
        CapabilityKind.SYMAI,
        CapabilityStatus.AVAILABLE,
        {
            **identity,
            "effective_provider": provider,
            "effective_model": model,
        },
        provenance,
    )


def _llm_router_probe(context: ProbeContext) -> CapabilityRecord:
    provider = context.environ.get("HSSL_LLM_ROUTER_PROVIDER")
    model = context.environ.get("HSSL_LLM_ROUTER_MODEL")
    configured_providers = sorted(
        {
            item.strip()
            for item in context.environ.get(
                "HSSL_LLM_ROUTER_PROVIDERS", ""
            ).split(",")
            if item.strip()
        }
        | ({provider} if provider else set())
    )
    try:
        installed = context.find_spec("ipfs_datasets_py.llm_router") is not None
    except Exception:
        installed = False
    identity = {
        "router_module_present": installed,
        "requested_provider": provider,
        "requested_model": model,
        "configured_providers": configured_providers,
    }
    provenance = (
        "python-module-spec",
        "environment:HSSL_LLM_ROUTER_PROVIDER",
        "environment:HSSL_LLM_ROUTER_PROVIDERS",
        "environment:HSSL_LLM_ROUTER_MODEL",
    )
    if not installed:
        return CapabilityRecord(
            CapabilityKind.LLM_ROUTER,
            CapabilityStatus.UNAVAILABLE,
            identity,
            provenance,
            "llm_router module is not installed",
        )
    if not provider or not model:
        return CapabilityRecord(
            CapabilityKind.LLM_ROUTER,
            CapabilityStatus.DEGRADED,
            identity,
            provenance,
            "llm_router is present but provider/model identity is incomplete",
        )
    return CapabilityRecord(
        CapabilityKind.LLM_ROUTER,
        CapabilityStatus.AVAILABLE,
        {
            **identity,
            "effective_provider": provider,
            "effective_model": model,
        },
        provenance,
    )


def _hammer_probe(context: ProbeContext) -> CapabilityRecord:
    solvers: dict[str, object] = {}
    for command, arguments in (
        ("z3", ("--version",)),
        ("cvc5", ("--version",)),
        ("eprover", ("--version",)),
        ("vampire", ("--version",)),
    ):
        identity = _command_identity(context, command, *arguments)
        if identity is not None:
            solvers[command] = identity
    hammer_version = _version(context, "ipfs-datasets-py")
    identity = {"hammer_package_version": hammer_version, "solvers": solvers}
    provenance = ("executable-path-and-version", "python-distribution-metadata")
    if not solvers:
        return CapabilityRecord(
            CapabilityKind.HAMMER,
            CapabilityStatus.UNAVAILABLE,
            identity,
            provenance,
            "no allowlisted Hammer solver executable was found",
        )
    return CapabilityRecord(
        CapabilityKind.HAMMER,
        CapabilityStatus.AVAILABLE,
        identity,
        provenance,
    )


def _leanstral_probe(context: ProbeContext) -> CapabilityRecord:
    endpoint = context.environ.get("HSSL_LEANSTRAL_ENDPOINT")
    model = context.environ.get("HSSL_LEANSTRAL_MODEL")
    health_verified = context.environ.get(
        "HSSL_LEANSTRAL_HEALTH_VERIFIED", ""
    ).lower() in {"1", "true", "yes"}
    identity = {
        "endpoint": endpoint,
        "requested_model": model,
        "effective_model": model if health_verified else None,
        "health_verified": health_verified,
    }
    provenance = (
        "environment:HSSL_LEANSTRAL_ENDPOINT",
        "environment:HSSL_LEANSTRAL_MODEL",
        "environment:HSSL_LEANSTRAL_HEALTH_VERIFIED",
        "no-inference-preflight",
    )
    if not endpoint or not model:
        return CapabilityRecord(
            CapabilityKind.LEANSTRAL_SERVICE,
            CapabilityStatus.UNAVAILABLE,
            identity,
            provenance,
            "Leanstral endpoint and model identity are required",
        )
    if not health_verified:
        return CapabilityRecord(
            CapabilityKind.LEANSTRAL_SERVICE,
            CapabilityStatus.DEGRADED,
            identity,
            provenance,
            "Leanstral is configured but no bounded health receipt was supplied",
        )
    return CapabilityRecord(
        CapabilityKind.LEANSTRAL_SERVICE,
        CapabilityStatus.AVAILABLE,
        identity,
        provenance,
    )


def _lean_toolchain_probe(context: ProbeContext) -> CapabilityRecord:
    lean = _command_identity(context, "lean", "--version")
    lake = _command_identity(context, "lake", "--version")
    identity = {"lean": lean, "lake": lake}
    provenance = ("executable-path-and-version",)
    if lean is None:
        return CapabilityRecord(
            CapabilityKind.LEAN_TOOLCHAIN,
            CapabilityStatus.UNAVAILABLE,
            identity,
            provenance,
            "Lean executable was not found",
        )
    if lake is None:
        return CapabilityRecord(
            CapabilityKind.LEAN_TOOLCHAIN,
            CapabilityStatus.DEGRADED,
            identity,
            provenance,
            "Lean is present but the Lake build tool was not found",
        )
    return CapabilityRecord(
        CapabilityKind.LEAN_TOOLCHAIN,
        CapabilityStatus.AVAILABLE,
        identity,
        provenance,
    )


def _cache_probe(context: ProbeContext) -> CapabilityRecord:
    return CapabilityRecord(
        CapabilityKind.CACHE_BACKEND,
        CapabilityStatus.AVAILABLE,
        {
            "implementation": "run-scoped-filesystem",
            "root": (context.run_paths.cache / "capabilities").as_posix(),
            "namespace": f"{BENCHMARK_ID}/{context.run_paths.run_id}",
        },
        ("RunPaths.cache",),
    )


def _scheduler_probe(context: ProbeContext) -> CapabilityRecord:
    configured = context.environ.get(
        "HSSL_RESOURCE_SCHEDULER", "run-scoped-file-lock"
    )
    verified = context.environ.get(
        "HSSL_RESOURCE_SCHEDULER_VERIFIED", ""
    ).lower() in {"1", "true", "yes"}
    identity = {
        "implementation": configured,
        "schema": "logic-pipeline-resource-scheduler.v1",
        "state_path": (
            context.run_paths.state / "resource-scheduler.json"
        ).as_posix(),
        "policy_schema": RESOURCE_POLICY_SCHEMA,
        "lease_schema": RESOURCE_LEASE_SCHEMA,
        "resource_classes": [item.value for item in ResourceClass],
        "shared_model_identity_required": True,
        "process_group_cleanup": "term-kill-reap",
        "queue_delay_measured": True,
        "verified": verified,
    }
    provenance = (
        "RunPaths.state",
        "environment:HSSL_RESOURCE_SCHEDULER",
        "environment:HSSL_RESOURCE_SCHEDULER_VERIFIED",
    )
    if not verified:
        return CapabilityRecord(
            CapabilityKind.RESOURCE_SCHEDULER,
            CapabilityStatus.DEGRADED,
            identity,
            provenance,
            "scheduler identity is configured but implementation is not verified",
        )
    return CapabilityRecord(
        CapabilityKind.RESOURCE_SCHEDULER,
        CapabilityStatus.AVAILABLE,
        identity,
        provenance,
    )


DEFAULT_CAPABILITY_PROBES: Final[Mapping[CapabilityKind, CapabilityProbe]] = (
    MappingProxyType(
        {
            CapabilityKind.SPACY_PIPELINE: _spacy_probe,
            CapabilityKind.SYMAI: _symai_probe,
            CapabilityKind.LLM_ROUTER: _llm_router_probe,
            CapabilityKind.HAMMER: _hammer_probe,
            CapabilityKind.LEANSTRAL_SERVICE: _leanstral_probe,
            CapabilityKind.LEAN_TOOLCHAIN: _lean_toolchain_probe,
            CapabilityKind.CACHE_BACKEND: _cache_probe,
            CapabilityKind.RESOURCE_SCHEDULER: _scheduler_probe,
        }
    )
)


def _resolved_within(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return (
        resolved_path == resolved_root
        or resolved_path.is_relative_to(resolved_root)
    )


def _validate_scoped_capability(
    record: CapabilityRecord,
    run_paths: RunPaths,
) -> None:
    if record.kind is CapabilityKind.CACHE_BACKEND:
        root = record.identity.get("root")
        if not isinstance(root, str) or not _resolved_within(
            Path(root), run_paths.cache
        ):
            raise CapabilityContractError(
                "cache backend root must be scoped below this run cache"
            )
    if record.kind is CapabilityKind.RESOURCE_SCHEDULER:
        state_path = record.identity.get("state_path")
        if not isinstance(state_path, str) or not _resolved_within(
            Path(state_path), run_paths.state
        ):
            raise CapabilityContractError(
                "resource scheduler state must be scoped below this run state"
            )


def _bind_scoped_capability(
    record: CapabilityRecord,
    run_paths: RunPaths,
) -> CapabilityRecord:
    """Add protocol-owned run paths when an injected probe omits them.

    Probes identify implementations; the benchmark protocol owns mutable path
    allocation.  This keeps injected/custom probes from choosing a global path
    by default while still rejecting any explicit path outside the run root.
    """

    identity = dict(_thaw_json(record.identity))  # type: ignore[arg-type]
    provenance = record.provenance
    if record.kind is CapabilityKind.CACHE_BACKEND and "root" not in identity:
        identity["root"] = (run_paths.cache / "capabilities").as_posix()
        provenance = (*provenance, "RunPaths.cache")
    if (
        record.kind is CapabilityKind.RESOURCE_SCHEDULER
        and "state_path" not in identity
    ):
        identity["state_path"] = (
            run_paths.state / "resource-scheduler.json"
        ).as_posix()
        provenance = (*provenance, "RunPaths.state")
    if identity == _thaw_json(record.identity):
        return record
    return CapabilityRecord(
        kind=record.kind,
        status=record.status,
        identity=identity,
        provenance=provenance,
        reason=record.reason,
    )


def probe_runtime_capabilities(
    run_id: str,
    run_paths: RunPaths,
    *,
    probes: Mapping[CapabilityKind, CapabilityProbe] | None = None,
    environ: Mapping[str, str] | None = None,
    find_spec: FindSpec = _find_spec_without_import,
    distribution_version: DistributionVersion = metadata.version,
    which: ExecutableFinder = shutil.which,
    run_command: CommandRunner = _run_version_command,
    source_commit: str | None = None,
    environment_identity: Mapping[str, object] | None = None,
) -> CapabilityInventory:
    """Probe every runtime explicitly without silently substituting a tool.

    A missing probe or a probe exception is retained as an ``unavailable``
    record.  A probe that returns the wrong capability kind is likewise
    rejected into the requested slot.  Contract violations in returned
    records, including production cache/scheduler paths, fail the entire
    preflight rather than manufacturing a plausible inventory.
    """

    _safe_id(run_id, "run_id")
    if not _is_run_paths(run_paths) or run_paths.run_id != run_id:
        raise CapabilityContractError(
            "run_paths must belong to the inventory run_id"
        )
    selected = DEFAULT_CAPABILITY_PROBES if probes is None else probes
    context = ProbeContext(
        run_paths=run_paths,
        environ=MappingProxyType(
            dict(os.environ if environ is None else environ)
        ),
        find_spec=find_spec,
        distribution_version=distribution_version,
        which=which,
        run_command=run_command,
    )
    records: list[CapabilityRecord] = []
    for kind in REQUIRED_CAPABILITY_KINDS:
        probe = selected.get(kind)
        if probe is None:
            records.append(
                CapabilityRecord(
                    kind,
                    CapabilityStatus.UNAVAILABLE,
                    {},
                    ("probe-registry",),
                    f"no probe registered for {kind.value}",
                )
            )
            continue
        try:
            record = probe(context)
            if not isinstance(record, CapabilityRecord):
                raise CapabilityContractError(
                    "probe did not return a CapabilityRecord"
                )
            if record.kind is not kind:
                raise CapabilityContractError(
                    f"probe for {kind.value} returned {record.kind.value}"
                )
            record = _bind_scoped_capability(record, run_paths)
            _validate_scoped_capability(record, run_paths)
        except CapabilityContractError:
            raise
        except Exception as exc:
            records.append(
                CapabilityRecord(
                    kind,
                    CapabilityStatus.UNAVAILABLE,
                    {},
                    ("probe-exception",),
                    f"probe raised {type(exc).__name__}",
                )
            )
        else:
            records.append(record)
    return CapabilityInventory.create(
        run_id,
        records,
        environment=environment_identity or _default_environment_identity(),
        source_commit=source_commit,
    )


def require_capabilities(
    inventory: CapabilityInventory,
    required: Sequence[CapabilityKind],
) -> tuple[CapabilityRecord, ...]:
    """Return fully available requested records or reject the exact request."""

    if not isinstance(inventory, CapabilityInventory):
        raise TypeError("inventory must be a CapabilityInventory")
    result: list[CapabilityRecord] = []
    seen: set[CapabilityKind] = set()
    for raw_kind in required:
        try:
            kind = (
                raw_kind
                if isinstance(raw_kind, CapabilityKind)
                else CapabilityKind(raw_kind)
            )
        except (TypeError, ValueError) as exc:
            raise CapabilityUnavailableError(
                f"unsupported required capability: {raw_kind!r}"
            ) from exc
        if kind in seen:
            raise CapabilityUnavailableError(
                f"duplicate required capability: {kind.value}"
            )
        seen.add(kind)
        record = inventory.by_kind[kind]
        if record.status is not CapabilityStatus.AVAILABLE:
            raise CapabilityUnavailableError(
                f"{kind.value} is {record.status.value}: {record.reason}"
            )
        result.append(record)
    return tuple(result)


def write_capability_inventory(
    inventory: CapabilityInventory,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write canonical inventory evidence without accidental replacement."""

    path = Path(destination)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_capability_inventory_json(inventory))
        handle.write("\n")
    return path


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(repository), *arguments]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CapabilityContractError(
            f"Git command failed: {type(exc).__name__}"
        ) from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        summary = detail[0][:512] if detail else "no diagnostic"
        raise CapabilityContractError(
            f"Git command {arguments[0]!r} failed: {summary}"
        )
    return completed


def _git_value(repository: Path, *arguments: str) -> str:
    return _git(repository, *arguments).stdout.strip()


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve(strict=False)
    right = right.resolve(strict=False)
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
    )


def _logical_absolute_path(path: Path, field: str) -> Path:
    """Return an absolute lexical path without following filesystem links."""

    candidate = Path(path)
    if ".." in candidate.parts:
        raise CapabilityContractError(f"{field} may not contain '..'")
    return Path(os.path.abspath(os.fspath(candidate)))


def _reject_symlink_components(path: Path, field: str) -> Path:
    """Reject a link in any existing component of one logical path."""

    logical = _logical_absolute_path(path, field)
    parts = logical.parts
    current = Path(parts[0])
    for index, component in enumerate(parts[1:], start=1):
        current /= component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            # No deeper component can exist until this parent is created.
            break
        except OSError as exc:
            raise CapabilityContractError(
                f"cannot inspect {field} path component: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CapabilityContractError(
                f"{field} may not traverse a symlink: {current}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise CapabilityContractError(
                f"{field} ancestor is not a directory: {current}"
            )
    return logical


def _mkdir_without_following_symlinks(path: Path, *, mode: int = 0o700) -> Path:
    """Create a directory tree with no-follow checks at every component."""

    logical = _reject_symlink_components(path, "benchmark directory")
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    cloexec_flag = getattr(os, "O_CLOEXEC", 0)
    if (
        os.name != "posix"
        or not directory_flag
        or not nofollow_flag
        or not os.supports_dir_fd
    ):
        logical.mkdir(mode=mode, parents=True, exist_ok=True)
        _reject_symlink_components(logical, "benchmark directory")
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
                raise CapabilityContractError(
                    "benchmark directory path contains a symlink or "
                    f"non-directory component: {logical}"
                ) from exc
            metadata = os.fstat(child_fd)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child_fd)
                raise CapabilityContractError(
                    f"benchmark directory component is not a directory: {logical}"
                )
            os.close(parent_fd)
            parent_fd = child_fd
    finally:
        os.close(parent_fd)
    return logical


def _submodule_gitlinks(
    repository: Path,
    commit: str,
) -> Mapping[str, str]:
    output = _git_value(repository, "ls-tree", "-r", "-z", commit)
    commits: dict[str, str] = {}
    for raw_entry in output.split("\0"):
        if not raw_entry:
            continue
        header, separator, path = raw_entry.partition("\t")
        fields = header.split()
        if not separator or len(fields) != 3:
            raise CapabilityContractError("Git returned a malformed tree entry")
        mode, object_type, object_id = fields
        if mode == "160000":
            if object_type != "commit" or not _HEX_COMMIT.fullmatch(object_id):
                raise CapabilityContractError(
                    "Git returned a malformed submodule gitlink"
                )
            commits[path] = object_id
    return MappingProxyType(dict(sorted(commits.items())))


def _source_snapshot(repository: Path) -> tuple[str, str | None, str]:
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
    status_sha256 = hashlib.sha256(status.encode("utf-8")).hexdigest()
    return head, branch, status_sha256


@dataclass(frozen=True, slots=True)
class WorktreeSafetyReceipt:
    """Machine-readable proof of one isolated, pinned worktree."""

    schema: str
    run_id: str
    evidence: str
    source_checkout: Path
    source_git_common_dir: Path
    source_head: str
    source_branch: str | None
    source_status_sha256: str
    base_revision: str
    base_commit: str
    worktree_root: Path
    worktree_commit: str
    state_root: Path
    submodule_commits: Mapping[str, str]
    detached: bool
    auto_merge: bool
    source_unchanged: bool

    def __post_init__(self) -> None:
        if self.schema != WORKTREE_SAFETY_SCHEMA:
            raise CapabilityContractError(
                f"unsupported worktree safety schema: {self.schema!r}"
            )
        _safe_id(self.run_id, "run_id")
        if self.evidence != HSSLEV0118D14():
            raise CapabilityContractError("worktree evidence marker is invalid")
        for field_name in ("source_head", "base_commit", "worktree_commit"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _HEX_COMMIT.fullmatch(value):
                raise CapabilityContractError(
                    f"{field_name} must be a full lowercase Git commit id"
                )
        if (
            not isinstance(self.source_status_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.source_status_sha256)
        ):
            raise CapabilityContractError(
                "source_status_sha256 must be a lowercase SHA-256 digest"
            )
        if not isinstance(self.base_revision, str) or not self.base_revision:
            raise CapabilityContractError("base_revision must be nonempty")
        if self.base_commit != self.worktree_commit:
            raise CapabilityContractError(
                "worktree commit must equal the pinned base commit"
            )
        if self.detached is not True:
            raise CapabilityContractError("benchmark worktree must be detached")
        if self.auto_merge is not False:
            raise CapabilityContractError("automatic merge is permanently forbidden")
        if self.source_unchanged is not True:
            raise CapabilityContractError("active source checkout changed")

        source = Path(self.source_checkout).resolve()
        common = Path(self.source_git_common_dir).resolve()
        worktree = Path(self.worktree_root).resolve()
        state = Path(self.state_root).resolve()
        if not worktree.is_relative_to(state):
            raise CapabilityContractError(
                "worktree root must be below the run state root"
            )
        if _paths_overlap(source, state) or _paths_overlap(common, state):
            raise CapabilityContractError(
                "run state root overlaps the active checkout or Git state"
            )
        submodules = _mapping(self.submodule_commits, "submodule_commits")
        for path, commit in submodules.items():
            if (
                not path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                or not isinstance(commit, str)
                or not _HEX_COMMIT.fullmatch(commit)
            ):
                raise CapabilityContractError(
                    "submodule commits must map safe relative paths to commits"
                )
        object.__setattr__(self, "source_checkout", source)
        object.__setattr__(self, "source_git_common_dir", common)
        object.__setattr__(self, "worktree_root", worktree)
        object.__setattr__(self, "state_root", state)
        object.__setattr__(
            self,
            "submodule_commits",
            MappingProxyType(dict(sorted(submodules.items()))),
        )

    @property
    def sha256(self) -> str:
        return worktree_safety_sha256(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "evidence": self.evidence,
            "source_checkout": self.source_checkout.as_posix(),
            "source_git_common_dir": self.source_git_common_dir.as_posix(),
            "source_head": self.source_head,
            "source_branch": self.source_branch,
            "source_status_sha256": self.source_status_sha256,
            "base_revision": self.base_revision,
            "base_commit": self.base_commit,
            "worktree_root": self.worktree_root.as_posix(),
            "worktree_commit": self.worktree_commit,
            "state_root": self.state_root.as_posix(),
            "submodule_commits": dict(self.submodule_commits),
            "detached": self.detached,
            "auto_merge": self.auto_merge,
            "source_unchanged": self.source_unchanged,
        }

    @classmethod
    def from_dict(cls, value: object) -> "WorktreeSafetyReceipt":
        payload = _mapping(value, "worktree safety receipt")
        expected = {
            "schema",
            "run_id",
            "evidence",
            "source_checkout",
            "source_git_common_dir",
            "source_head",
            "source_branch",
            "source_status_sha256",
            "base_revision",
            "base_commit",
            "worktree_root",
            "worktree_commit",
            "state_root",
            "submodule_commits",
            "detached",
            "auto_merge",
            "source_unchanged",
        }
        _exact_keys(payload, expected, "worktree safety receipt")
        return cls(
            schema=payload["schema"],  # type: ignore[arg-type]
            run_id=payload["run_id"],  # type: ignore[arg-type]
            evidence=payload["evidence"],  # type: ignore[arg-type]
            source_checkout=Path(payload["source_checkout"]),  # type: ignore[arg-type]
            source_git_common_dir=Path(  # type: ignore[arg-type]
                payload["source_git_common_dir"]
            ),
            source_head=payload["source_head"],  # type: ignore[arg-type]
            source_branch=payload["source_branch"],  # type: ignore[arg-type]
            source_status_sha256=payload["source_status_sha256"],  # type: ignore[arg-type]
            base_revision=payload["base_revision"],  # type: ignore[arg-type]
            base_commit=payload["base_commit"],  # type: ignore[arg-type]
            worktree_root=Path(payload["worktree_root"]),  # type: ignore[arg-type]
            worktree_commit=payload["worktree_commit"],  # type: ignore[arg-type]
            state_root=Path(payload["state_root"]),  # type: ignore[arg-type]
            submodule_commits=_mapping(
                payload["submodule_commits"],
                "worktree safety receipt.submodule_commits",
            ),
            detached=payload["detached"],  # type: ignore[arg-type]
            auto_merge=payload["auto_merge"],  # type: ignore[arg-type]
            source_unchanged=payload["source_unchanged"],  # type: ignore[arg-type]
        )


def canonical_worktree_safety_json(receipt: WorktreeSafetyReceipt) -> str:
    if not isinstance(receipt, WorktreeSafetyReceipt):
        raise TypeError("receipt must be a WorktreeSafetyReceipt")
    return _canonical_json(receipt.to_dict())


def worktree_safety_sha256(receipt: WorktreeSafetyReceipt) -> str:
    return hashlib.sha256(
        canonical_worktree_safety_json(receipt).encode("utf-8")
    ).hexdigest()


def _validate_isolation_paths(
    source_checkout: Path,
    source_git_common_dir: Path,
    run_paths: RunPaths,
) -> tuple[Path, Path]:
    _reject_symlink_components(
        run_paths.benchmark_root,
        "benchmark_root",
    )
    for directory in run_paths.directories():
        _reject_symlink_components(directory, "fresh run directory")
    _reject_symlink_components(
        run_paths.worktrees / "source",
        "isolated worktree target",
    )
    state_root = run_paths.run_root.resolve(strict=False)
    worktree_root = (run_paths.worktrees / "source").resolve(strict=False)
    if _paths_overlap(source_checkout, state_root) or _paths_overlap(
        source_git_common_dir, state_root
    ):
        raise ValueError(
            "benchmark state root must not overlap the active checkout or Git state"
        )
    if _paths_overlap(source_checkout, worktree_root) or _paths_overlap(
        source_git_common_dir, worktree_root
    ):
        raise ValueError(
            "benchmark worktree must not overlap the active checkout or Git state"
        )
    for directory in run_paths.directories():
        if not _resolved_within(directory, state_root):
            raise ValueError(
                "every mutable benchmark path must be scoped below the state root"
            )
    if not _resolved_within(worktree_root, run_paths.worktrees):
        raise ValueError(
            "worktree target escapes the run-scoped worktree directory"
        )
    if worktree_root.exists() or worktree_root.is_symlink():
        raise FileExistsError(
            f"isolated worktree target already exists: {worktree_root}"
        )
    return state_root, worktree_root


def prepare_isolated_worktree(
    source_checkout: str | Path,
    *,
    run_paths: RunPaths,
    base_revision: str,
) -> WorktreeSafetyReceipt:
    """Create one detached worktree and emit its canonical safety receipt.

    The base revision is resolved to a full commit before any run directory is
    created.  The active checkout is observed before and after ``git worktree
    add``; a changed HEAD, branch, or porcelain status aborts receipt creation.
    This function never creates a branch and contains no clean, reset, stash,
    switch, checkout, merge, or worktree-removal operation.
    """

    if not _is_run_paths(run_paths):
        raise TypeError("run_paths must be a RunPaths value")
    if not isinstance(base_revision, str) or not base_revision.strip():
        raise CapabilityContractError("base_revision must be nonempty")
    requested_source = Path(source_checkout).resolve()
    if not requested_source.is_dir():
        raise CapabilityContractError(
            "source checkout must be an existing Git working tree"
        )
    source = Path(
        _git_value(requested_source, "rev-parse", "--show-toplevel")
    ).resolve()
    if source != requested_source:
        raise CapabilityContractError(
            "source checkout must name the active working-tree root"
        )
    common_raw = _git_value(
        source,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    common = Path(common_raw).resolve()
    base_commit = _git_value(
        source,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{base_revision}^{{commit}}",
    )
    if not _HEX_COMMIT.fullmatch(base_commit):
        raise CapabilityContractError(
            "base_revision did not resolve to a full Git commit"
        )
    source_before = _source_snapshot(source)
    submodule_commits = _submodule_gitlinks(source, base_commit)
    state_root, worktree_root = _validate_isolation_paths(
        source,
        common,
        run_paths,
    )

    for directory in run_paths.directories():
        _mkdir_without_following_symlinks(directory)
    _git(
        source,
        "worktree",
        "add",
        "--detach",
        str(worktree_root),
        base_commit,
    )
    worktree_commit = _git_value(
        worktree_root, "rev-parse", "--verify", "HEAD^{commit}"
    )
    detached = (
        _git(
            worktree_root,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        ).returncode
        != 0
    )
    source_after = _source_snapshot(source)
    source_unchanged = source_after == source_before
    if not source_unchanged:
        raise CapabilityContractError(
            "active source checkout changed during worktree preparation"
        )

    receipt = WorktreeSafetyReceipt(
        schema=WORKTREE_SAFETY_SCHEMA,
        run_id=run_paths.run_id,
        evidence=HSSLEV0118D14(),
        source_checkout=source,
        source_git_common_dir=common,
        source_head=source_before[0],
        source_branch=source_before[1],
        source_status_sha256=source_before[2],
        base_revision=base_revision,
        base_commit=base_commit,
        worktree_root=worktree_root,
        worktree_commit=worktree_commit,
        state_root=state_root,
        submodule_commits=submodule_commits,
        detached=detached,
        auto_merge=False,
        source_unchanged=source_unchanged,
    )
    receipt_path = run_paths.receipts / WORKTREE_SAFETY_RECEIPT_NAME
    with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_worktree_safety_json(receipt))
        handle.write("\n")
    return receipt


__all__ = [
    "CAPABILITY_INVENTORY_SCHEMA",
    "DEFAULT_CAPABILITY_PROBES",
    "RESOURCE_LEASE_SCHEMA",
    "RESOURCE_POLICY_SCHEMA",
    "BoundedProcessResult",
    "CapabilityContractError",
    "CapabilityInventory",
    "CapabilityKind",
    "CapabilityRecord",
    "CapabilityStatus",
    "CapabilityUnavailableError",
    "HSSLEV0118D14",
    "HSSLEV0125F83",
    "HSSLEV0724C07",
    "ProbeContext",
    "REQUIRED_CAPABILITY_KINDS",
    "ResourceClass",
    "ResourceLease",
    "ResourceLeaseCancelled",
    "ResourceLeaseError",
    "ResourceLeaseReceipt",
    "ResourceLeaseRequest",
    "ResourceLeaseTimeout",
    "ResourcePolicy",
    "ResourceScheduler",
    "WORKTREE_SAFETY_RECEIPT_NAME",
    "WORKTREE_SAFETY_SCHEMA",
    "WorktreeSafetyReceipt",
    "canonical_capability_inventory_json",
    "canonical_worktree_safety_json",
    "capability_inventory_sha256",
    "prepare_isolated_worktree",
    "probe_runtime_capabilities",
    "redact_secrets",
    "require_capabilities",
    "run_bounded_process_group",
    "worktree_safety_sha256",
    "write_capability_inventory",
]
