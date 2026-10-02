"""Live host and LLM-provider admission policy for supervisor lanes.

The objects in this module deliberately serialize without floating point
values.  Profile-G artifacts reject floats, and scheduler decisions often end
up embedded in those artifacts.  Percentages are therefore whole percentages
and all resource sizes, token counts, durations, and capacities are integers.

Provider telemetry is not owned by :mod:`llm_router`; different providers
expose it through different monitors.  :func:`normalize_provider_capacity`
accepts the common telemetry spellings and turns them into one conservative
model.  Unknown limits use ``-1`` (unbounded/not reported), while an explicit
zero is always treated as exhausted.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any


UNKNOWN_LIMIT = -1
ADAPTIVE_SCHEDULING_THROUGHPUT_REQUIREMENT_ID = (
    "122080003600146794820964010047426915846"
)
ADAPTIVE_THROUGHPUT_BENCHMARK_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.adaptive-throughput-benchmark@2"
)
PIPELINE_OVERLAP_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.pipeline-overlap-receipt@1"
)
BACKPRESSURE_FAIRNESS_OVERLAP_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.backpressure-fairness-overlap-receipt@1"
)
STAGE_ADMISSION_PROFILE_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.stage-admission-profile@1"
)
CAMPAIGN_RESOURCE_PROFILE_SCHEMA = (
    "ipfs_accelerate_py.agent_supervisor.campaign-resource-profile@1"
)
ADAPTIVE_STAGES = (
    "analysis",
    "inference",
    "proof",
    "validation",
    "merge",
    "persistence",
    "execution",
)
CANONICAL_ADAPTIVE_STAGES = ADAPTIVE_STAGES[:-1]


def normalize_adaptive_stage(value: Any) -> str:
    """Return a stable resource-admission stage name.

    Extensions are intentionally accepted because supervisor deployments can
    add independent stages. Empty legacy stage values map to ``execution``.
    """

    raw = str(getattr(value, "value", value) or "").strip().lower()
    raw = raw.replace(" ", "_").replace("-", "_").replace("/", "_")
    aliases = {
        "analyze": "analysis",
        "analysis_pipeline": "analysis",
        "model": "inference",
        "llm": "inference",
        "provider": "inference",
        "solve": "proof",
        "solver": "proof",
        "validate": "validation",
        "acceptance": "validation",
        "git": "merge",
        "git_merge": "merge",
        "gitmerge": "merge",
        "merging": "merge",
        "merge_train": "merge",
        "persist": "persistence",
        "artifact": "persistence",
        "storage": "persistence",
        "scheduler": "execution",
    }
    return aliases.get(raw, raw) if raw else "execution"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class AdaptiveStageProfile:
    """Canonical resource shape for one supervisor pipeline stage.

    These profiles describe pool ownership without imposing non-zero byte
    estimates on legacy callers. Deployments can add exact per-lane estimates
    through :class:`LaneResourceRequirements`.
    """

    stage: str
    pool: str
    resource_class: str
    requires_provider: bool = False
    cpu_sensitive: bool = True
    memory_sensitive: bool = True
    gpu_memory_sensitive: bool = False
    disk_sensitive: bool = False

    def __post_init__(self) -> None:
        normalized = normalize_adaptive_stage(self.stage)
        if normalized not in CANONICAL_ADAPTIVE_STAGES:
            raise ValueError(f"unsupported canonical adaptive stage: {self.stage!r}")
        object.__setattr__(self, "stage", normalized)
        if not str(self.pool).strip():
            raise ValueError("pool must be non-empty")
        if not str(self.resource_class).strip():
            raise ValueError("resource_class must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ADAPTIVE_STAGE_PROFILES = (
    AdaptiveStageProfile("analysis", "analysis", "cpu-medium"),
    AdaptiveStageProfile(
        "inference",
        "inference",
        "llm-proof-draft",
        requires_provider=True,
        gpu_memory_sensitive=True,
    ),
    AdaptiveStageProfile("proof", "proof", "cpu-proof-solver"),
    AdaptiveStageProfile("validation", "validation", "cpu-validation"),
    AdaptiveStageProfile(
        "merge",
        "git-merge",
        "git-merge",
        disk_sensitive=True,
    ),
    AdaptiveStageProfile(
        "persistence",
        "persistence",
        "io-artifact",
        disk_sensitive=True,
    ),
)
_ADAPTIVE_STAGE_PROFILE_BY_NAME = {
    item.stage: item for item in ADAPTIVE_STAGE_PROFILES
}


def adaptive_stage_profile(stage: Any) -> AdaptiveStageProfile:
    """Return the explicit canonical profile for ``stage``.

    ``execution`` is the compatibility stage for whole-lane work and maps to
    the analysis pool. Extension stages receive a conservative CPU profile.
    """

    name = normalize_adaptive_stage(stage)
    if name == "execution":
        return AdaptiveStageProfile(
            "analysis",
            "execution",
            "cpu-small",
            disk_sensitive=True,
        )
    profile = _ADAPTIVE_STAGE_PROFILE_BY_NAME.get(name)
    if profile is not None:
        return profile
    # Extensions remain schedulable but cannot silently acquire provider/GPU
    # capacity or bypass host CPU and memory pressure.
    return AdaptiveStageProfile("analysis", name, name)


# Compatibility-friendly singular/plural names used by integrations.
StageResourceProfile = AdaptiveStageProfile
STAGE_RESOURCE_PROFILES = ADAPTIVE_STAGE_PROFILES


class ProofResourceClass(str, Enum):
    """Canonical supervisor resource classes used by proof-plan work."""

    TRANSLATION = "cpu-proof-translate"
    SOLVER = "cpu-proof-solver"
    SOLVER_PORTFOLIO = "cpu-proof-solver"
    KERNEL = "cpu-proof-kernel"
    KERNEL_RECONSTRUCTION = "cpu-proof-kernel"
    VALIDATION = "cpu-validation"
    # Deterministic schema/type acceptance is separately backpressured from
    # general tests and static validation.
    TYPE_CHECK = "cpu-proof-type-check"
    DETERMINISTIC_TYPE_CHECK = "cpu-proof-type-check"
    MODEL_DRAFT = "llm-proof-draft"
    MODEL_DRAFTING = "llm-proof-draft"
    ARTIFACT = "io-artifact"

    @property
    def pool(self) -> str:
        if self is ProofResourceClass.MODEL_DRAFT:
            return "model"
        if self is ProofResourceClass.ARTIFACT:
            return "artifact"
        return "cpu-proof"


PROOF_RESOURCE_CLASSES = tuple(item.value for item in ProofResourceClass)
LEGACY_RESOURCE_CLASSES = (
    "cpu-small",
    "cpu-medium",
    "cpu-large",
)
# Prompt/objective plans use workload-oriented labels in addition to the
# proof scheduler's physical worker classes.  These labels still execute on a
# CPU host; provider, network, disk, and other specialized requirements are
# enforced independently through capabilities, provider admission, and stage
# headroom checks.  Without this compatibility set, a default host advertising
# the canonical proof classes rejects ordinary prompt-plan work even when it
# has idle CPU capacity.
GENERIC_BUNDLE_RESOURCE_CLASSES = (
    "coordinator",
    "crypto-small",
    "git-merge",
    "io-database",
    "io-medium",
    "io-network",
    "io-small",
    "network",
    "network-small",
    "process-control",
    "provider-io",
    "provider-llm",
)
# Default hosts advertise the architecture's distinct work classes.
# Generic bundle classes remain interoperable through the compatibility check
# in ``_host_reasons`` and can still be advertised explicitly by old workers.
DEFAULT_RESOURCE_CLASSES = PROOF_RESOURCE_CLASSES

_RESOURCE_CLASS_ALIASES = {
    "translate": ProofResourceClass.TRANSLATION.value,
    "translation": ProofResourceClass.TRANSLATION.value,
    "proof-translate": ProofResourceClass.TRANSLATION.value,
    "solve": ProofResourceClass.SOLVER.value,
    "solver": ProofResourceClass.SOLVER.value,
    "proof-solver": ProofResourceClass.SOLVER.value,
    "reconstruct": ProofResourceClass.KERNEL.value,
    "kernel": ProofResourceClass.KERNEL.value,
    "kernel_verify": ProofResourceClass.KERNEL.value,
    "kernel-verify": ProofResourceClass.KERNEL.value,
    "validate": ProofResourceClass.VALIDATION.value,
    "validation": ProofResourceClass.VALIDATION.value,
    "typecheck": ProofResourceClass.TYPE_CHECK.value,
    "type-check": ProofResourceClass.TYPE_CHECK.value,
    "type_check": ProofResourceClass.TYPE_CHECK.value,
    "deterministic-type-check": ProofResourceClass.TYPE_CHECK.value,
    "deterministic_type_check": ProofResourceClass.TYPE_CHECK.value,
    "model_draft": ProofResourceClass.MODEL_DRAFT.value,
    "model-draft": ProofResourceClass.MODEL_DRAFT.value,
    "persist": ProofResourceClass.ARTIFACT.value,
    "artifact": ProofResourceClass.ARTIFACT.value,
    "attest": ProofResourceClass.ARTIFACT.value,
}


class ProofWorkKind(str, Enum):
    """Closed work vocabulary for the goal-development proof runtime."""

    MODEL_DRAFT = "model_draft"
    MODEL_DRAFTING = "model_draft"
    TYPE_CHECK = "type_check"
    DETERMINISTIC_TYPE_CHECK = "type_check"
    SOLVER_PORTFOLIO = "solver_portfolio"
    KERNEL_RECONSTRUCTION = "kernel_reconstruction"

    @property
    def resource_class(self) -> ProofResourceClass:
        return {
            ProofWorkKind.MODEL_DRAFT: ProofResourceClass.MODEL_DRAFT,
            ProofWorkKind.TYPE_CHECK: ProofResourceClass.TYPE_CHECK,
            ProofWorkKind.SOLVER_PORTFOLIO: ProofResourceClass.SOLVER,
            ProofWorkKind.KERNEL_RECONSTRUCTION: ProofResourceClass.KERNEL,
        }[self]


_PROOF_WORK_KIND_ALIASES = {
    "draft": ProofWorkKind.MODEL_DRAFT,
    "leanstral": ProofWorkKind.MODEL_DRAFT,
    "model": ProofWorkKind.MODEL_DRAFT,
    "model-draft": ProofWorkKind.MODEL_DRAFT,
    "typecheck": ProofWorkKind.TYPE_CHECK,
    "type-check": ProofWorkKind.TYPE_CHECK,
    "deterministic-type-check": ProofWorkKind.TYPE_CHECK,
    "deterministic_type_check": ProofWorkKind.TYPE_CHECK,
    "solve": ProofWorkKind.SOLVER_PORTFOLIO,
    "solver": ProofWorkKind.SOLVER_PORTFOLIO,
    "solver-portfolio": ProofWorkKind.SOLVER_PORTFOLIO,
    "kernel": ProofWorkKind.KERNEL_RECONSTRUCTION,
    "kernel-reconstruct": ProofWorkKind.KERNEL_RECONSTRUCTION,
    "kernel-reconstruction": ProofWorkKind.KERNEL_RECONSTRUCTION,
}


def normalize_proof_work_kind(value: Any) -> ProofWorkKind:
    """Normalize a public work-kind spelling into the closed runtime enum."""

    if isinstance(value, ProofWorkKind):
        return value
    raw = str(getattr(value, "value", value) or "").strip().lower()
    raw = raw.replace(" ", "_")
    try:
        return ProofWorkKind(raw)
    except ValueError:
        alias = _PROOF_WORK_KIND_ALIASES.get(raw)
        if alias is None:
            alias = _PROOF_WORK_KIND_ALIASES.get(raw.replace("_", "-"))
        if alias is None:
            raise ValueError(f"unsupported proof work kind: {value!r}") from None
        return alias


def resource_class_for_work_kind(value: Any) -> str:
    """Return the canonical, independently limitable class for ``value``."""

    return normalize_proof_work_kind(value).resource_class.value


def normalize_resource_class(value: Any, *, stage: Any = "") -> str:
    """Return a canonical proof resource class while preserving extensions."""

    raw = str(value or "").strip().lower()
    stage_name = getattr(stage, "value", stage)
    stage_raw = str(stage_name or "").strip().lower()
    if raw in PROOF_RESOURCE_CLASSES:
        return raw
    if raw in _RESOURCE_CLASS_ALIASES:
        return _RESOURCE_CLASS_ALIASES[raw]
    if not raw and stage_raw:
        return _RESOURCE_CLASS_ALIASES.get(stage_raw, stage_raw)
    return raw


def resource_pool(resource_class: Any) -> str:
    """Classify a resource class into independently accounted capacity.

    Tight proof-solver/kernel/type-check classes share the
    ``cpu-proof`` pool (bounded by ``max_cpu_proof_concurrency``).
    Validation and ordinary bundle/legacy CPU classes use the general
    lane pool so residual install/cert work can scale with ``max_lanes``
    without being thrifted by proof-solver concurrency.
    """

    normalized = normalize_resource_class(resource_class)
    if normalized == ProofResourceClass.MODEL_DRAFT.value:
        return "model"
    if normalized == ProofResourceClass.ARTIFACT.value:
        return "artifact"
    if normalized in {
        ProofResourceClass.TRANSLATION.value,
        ProofResourceClass.SOLVER.value,
        ProofResourceClass.KERNEL.value,
        ProofResourceClass.TYPE_CHECK.value,
    } or str(normalized).startswith("cpu-proof"):
        return "cpu-proof"
    # Explicit validation class used by residual install/cert lanes.
    if normalized == ProofResourceClass.VALIDATION.value:
        return "cpu-general"
    # Legacy/generic labels historically share the proof pool for fairness
    # projection tests and mixed analysis/validation schedules.
    if (
        normalized in LEGACY_RESOURCE_CLASSES
        or normalized in GENERIC_BUNDLE_RESOURCE_CLASSES
        or not normalized
    ):
        return "cpu-proof"
    # Unregistered workload labels still execute on general CPU capacity
    # (see ``_host_reasons`` unregistered_cpu_workload_compatible).
    return "cpu-general"


def _integer(value: Any, default: int = 0, *, minimum: int | None = None) -> int:
    """Coerce telemetry to an integer without leaking floats into artifacts."""

    if value is None or isinstance(value, bool):
        result = default
    else:
        try:
            # Numeric strings such as ``"20.5"`` occur in psutil adapters.
            result = int(round(float(value)))
        except (TypeError, ValueError, OverflowError):
            result = default
    return max(minimum, result) if minimum is not None else result


def _boolean(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off", "down", "unhealthy", "failed"}:
            return False
        if normalized in {"1", "true", "yes", "on", "up", "healthy", "ready"}:
            return True
    return bool(value)


def _first(mapping: Mapping[str, Any], names: Sequence[str], default: Any = None) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        items = value
    else:
        items = (value,)
    return tuple(sorted({str(item).strip().lower() for item in items if str(item).strip()}))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class HostResourceSnapshot:
    """One measured view of the machine hosting a worker pool."""

    observed_at_ms: int = 0
    cpu_percent: int = 0
    memory_percent: int = 0
    disk_percent: int = 0
    memory_total_bytes: int = 0
    memory_available_bytes: int = 0
    disk_total_bytes: int = 0
    disk_available_bytes: int = 0
    active_phase: str = "scheduler"
    active_workers: int = 0
    worker_limit: int = 1
    available_worker_capacity: int = 1
    capabilities: tuple[str, ...] = ("cpu",)
    resource_classes: tuple[str, ...] = DEFAULT_RESOURCE_CLASSES
    gpu_memory_percent: int = 0
    gpu_memory_total_bytes: int = 0
    gpu_memory_available_bytes: int = 0

    def __post_init__(self) -> None:
        for name in (
            "cpu_percent",
            "memory_percent",
            "disk_percent",
            "gpu_memory_percent",
        ):
            value = int(getattr(self, name))
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be in [0, 100]")
        for name in (
            "observed_at_ms", "memory_total_bytes", "memory_available_bytes",
            "disk_total_bytes", "disk_available_bytes",
            "active_workers", "worker_limit", "available_worker_capacity",
            "gpu_memory_total_bytes", "gpu_memory_available_bytes",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def occupied_worker_capacity(self) -> int:
        return self.active_workers

    @property
    def cpu_millionths(self) -> int:
        return self.cpu_percent * 10_000

    @property
    def memory_used_bytes(self) -> int:
        return max(0, self.memory_total_bytes - self.memory_available_bytes)

    @property
    def disk_used_bytes(self) -> int:
        return max(0, self.disk_total_bytes - self.disk_available_bytes)

    @property
    def gpu_memory_used_bytes(self) -> int:
        return max(
            0,
            self.gpu_memory_total_bytes - self.gpu_memory_available_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        payload["resource_classes"] = list(self.resource_classes)
        payload["occupied_worker_capacity"] = self.occupied_worker_capacity
        payload["cpu_millionths"] = self.cpu_millionths
        payload["memory_used_bytes"] = self.memory_used_bytes
        payload["disk_used_bytes"] = self.disk_used_bytes
        payload["gpu_memory_used_bytes"] = self.gpu_memory_used_bytes
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HostResourceSnapshot":
        worker_limit = _integer(
            _first(value, ("worker_limit", "max_workers", "max_lanes", "capacity"), 1),
            1,
            minimum=0,
        )
        active = _integer(
            _first(value, ("active_workers", "occupied_worker_capacity", "running_workers"), 0),
            0,
            minimum=0,
        )
        available_value = _first(
            value,
            ("available_worker_capacity", "available_workers", "free_slots"),
            None,
        )
        available = (
            max(0, worker_limit - active)
            if available_value is None
            else _integer(available_value, 0, minimum=0)
        )
        return cls(
            observed_at_ms=_integer(
                _first(value, ("observed_at_ms", "measured_at_ms", "timestamp_ms"), 0),
                0,
                minimum=0,
            ),
            cpu_percent=_integer(_first(value, ("cpu_percent", "cpu_usage_percent", "cpu"), 0), 0, minimum=0),
            memory_percent=_integer(_first(value, ("memory_percent", "memory_usage_percent", "memory"), 0), 0, minimum=0),
            disk_percent=_integer(_first(value, ("disk_percent", "disk_usage_percent", "disk"), 0), 0, minimum=0),
            memory_available_bytes=_integer(
                _first(value, ("memory_available_bytes", "available_memory_bytes", "memory_free_bytes"), 0),
                0,
                minimum=0,
            ),
            memory_total_bytes=_integer(
                _first(value, ("memory_total_bytes", "total_memory_bytes"), 0),
                0,
                minimum=0,
            ),
            disk_available_bytes=_integer(
                _first(value, ("disk_available_bytes", "available_disk_bytes", "disk_free_bytes"), 0),
                0,
                minimum=0,
            ),
            disk_total_bytes=_integer(
                _first(value, ("disk_total_bytes", "total_disk_bytes"), 0),
                0,
                minimum=0,
            ),
            active_phase=str(_first(value, ("active_phase", "phase"), "scheduler") or "scheduler"),
            active_workers=active,
            worker_limit=worker_limit,
            available_worker_capacity=available,
            capabilities=_strings(value.get("capabilities")) or ("cpu",),
            resource_classes=_strings(value.get("resource_classes")) or DEFAULT_RESOURCE_CLASSES,
            gpu_memory_percent=_integer(
                _first(
                    value,
                    (
                        "gpu_memory_percent",
                        "gpu_memory_usage_percent",
                        "vram_percent",
                    ),
                    0,
                ),
                0,
                minimum=0,
            ),
            gpu_memory_total_bytes=_integer(
                _first(
                    value,
                    (
                        "gpu_memory_total_bytes",
                        "total_gpu_memory_bytes",
                        "vram_total_bytes",
                    ),
                    0,
                ),
                0,
                minimum=0,
            ),
            gpu_memory_available_bytes=_integer(
                _first(
                    value,
                    (
                        "gpu_memory_available_bytes",
                        "available_gpu_memory_bytes",
                        "gpu_memory_free_bytes",
                        "vram_available_bytes",
                        "vram_free_bytes",
                    ),
                    0,
                ),
                0,
                minimum=0,
            ),
        )


def sample_host_resources(
    path: Path | str = ".",
    *,
    active_workers: int = 0,
    worker_limit: int = 1,
    active_phase: str = "scheduler",
) -> HostResourceSnapshot:
    """Measure CPU, memory and disk without requiring psutil at import time."""

    active = max(0, int(active_workers))
    limit = max(0, int(worker_limit))
    target = Path(path)
    # disk_usage requires an existing path.  Walk up for new state roots.
    while not target.exists() and target != target.parent:
        target = target.parent

    cpu_percent = 0
    memory_percent = 0
    memory_available = 0
    memory_total = 0
    disk_percent = 0
    disk_available = 0
    disk_total = 0
    gpu_memory_percent = 0
    gpu_memory_available = 0
    gpu_memory_total = 0
    try:
        import psutil  # type: ignore[import-not-found]

        cpu_percent = _integer(psutil.cpu_percent(interval=None), 0, minimum=0)
        memory = psutil.virtual_memory()
        memory_percent = _integer(memory.percent, 0, minimum=0)
        memory_available = _integer(memory.available, 0, minimum=0)
        memory_total = _integer(memory.total, 0, minimum=0)
        disk = psutil.disk_usage(str(target))
        disk_percent = _integer(disk.percent, 0, minimum=0)
        disk_available = _integer(disk.free, 0, minimum=0)
        disk_total = _integer(disk.total, 0, minimum=0)
    except (ImportError, AttributeError, OSError):
        # Portable fallbacks retain useful byte headroom even on minimal hosts.
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            physical_pages = int(os.sysconf("SC_PHYS_PAGES"))
            memory_available = page_size * available_pages
            memory_total = page_size * physical_pages
            if memory_total > 0:
                memory_percent = max(0, min(100, 100 - (memory_available * 100 // memory_total)))
        except (AttributeError, OSError, TypeError, ValueError):
            pass
        try:
            stat = os.statvfs(target)
            disk_available = int(stat.f_bavail) * int(stat.f_frsize)
            disk_total = int(stat.f_blocks) * int(stat.f_frsize)
            if disk_total > 0:
                disk_percent = max(0, min(100, 100 - (disk_available * 100 // disk_total)))
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    # NVML is optional. Aggregate devices because provider/model work may be
    # routed to any local accelerator. Failure to inspect a driver means
    # "unreported", not "zero capacity", unless a lane explicitly requests
    # GPU memory.
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        try:
            for device_index in range(int(pynvml.nvmlDeviceGetCount())):
                handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpu_memory_total += _integer(getattr(info, "total", 0), 0, minimum=0)
                gpu_memory_available += _integer(
                    getattr(info, "free", 0), 0, minimum=0
                )
        finally:
            pynvml.nvmlShutdown()
        if gpu_memory_total:
            gpu_memory_percent = max(
                0,
                min(
                    100,
                    100
                    - gpu_memory_available * 100 // gpu_memory_total,
                ),
            )
    except Exception:
        # Driver/library-specific NVML exceptions do not share a stable
        # built-in base across pynvml releases. Optional accelerator telemetry
        # must never make host sampling fail.
        pass

    return HostResourceSnapshot(
        observed_at_ms=int(time.time() * 1000),
        cpu_percent=min(100, cpu_percent),
        memory_percent=min(100, memory_percent),
        disk_percent=min(100, disk_percent),
        memory_total_bytes=memory_total,
        memory_available_bytes=memory_available,
        disk_total_bytes=disk_total,
        disk_available_bytes=disk_available,
        active_phase=str(active_phase or "scheduler"),
        active_workers=active,
        worker_limit=limit,
        available_worker_capacity=max(0, limit - active),
        gpu_memory_percent=gpu_memory_percent,
        gpu_memory_total_bytes=gpu_memory_total,
        gpu_memory_available_bytes=gpu_memory_available,
    )


@dataclass(frozen=True)
class ProviderCapacity:
    """Normalized live capacity for one llm_router provider."""

    provider_id: str
    healthy: bool = True
    quota_remaining: int = UNKNOWN_LIMIT
    latency_ms: int = 0
    context_window_tokens: int = UNKNOWN_LIMIT
    token_budget_remaining: int = UNKNOWN_LIMIT
    max_concurrency: int = 1
    active_requests: int = 0
    capabilities: tuple[str, ...] = ()
    observed_at_ms: int = 0
    retry_after_ms: int = 0

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        object.__setattr__(self, "provider_id", self.provider_id.strip().lower())
        object.__setattr__(self, "capabilities", _strings(self.capabilities))
        for name in ("latency_ms", "max_concurrency", "active_requests", "observed_at_ms", "retry_after_ms"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("quota_remaining", "context_window_tokens", "token_budget_remaining"):
            if int(getattr(self, name)) < UNKNOWN_LIMIT:
                raise ValueError(f"{name} must be -1 or non-negative")

    @property
    def available_concurrency(self) -> int:
        return max(0, self.max_concurrency - self.active_requests)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        payload["available_concurrency"] = self.available_concurrency
        return payload

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        provider_id: str = "",
    ) -> "ProviderCapacity":
        health_data = _mapping(value.get("health"))
        quota_data = _mapping(value.get("quota"))
        latency_data = _mapping(value.get("latency"))
        context_data = _mapping(value.get("context"))
        token_data = _mapping(value.get("token_budget") or value.get("tokens"))
        concurrency_data = _mapping(value.get("concurrency"))

        def first_from(
            sources: Sequence[Mapping[str, Any]],
            names: Sequence[str],
            default: Any,
        ) -> Any:
            for source in sources:
                found = _first(source, names, None)
                if found is not None:
                    return found
            return default

        identity = str(
            provider_id
            or _first(value, ("provider_id", "provider", "name", "effective_provider_name"), "")
        ).strip().lower()
        status = first_from(
            (value, health_data),
            ("healthy", "available", "ready", "status", "state"),
            True,
        )
        if isinstance(status, str) and status.strip().lower() in {
            "down", "failed", "error", "disabled", "offline", "unhealthy",
            "quota_exhausted", "rate_limited",
        }:
            status = False
        max_concurrency = _integer(
            first_from(
                (value, concurrency_data),
                ("max_concurrency", "concurrency_limit", "max_workers", "capacity", "limit"),
                1,
            ),
            1,
            minimum=0,
        )
        active_requests = _integer(
            first_from(
                (value, concurrency_data),
                ("active_requests", "in_flight", "inflight", "occupied_capacity", "active", "used"),
                0,
            ),
            0,
            minimum=0,
        )
        # Some monitors expose only the number of free request slots.
        available = _first(value, ("available_concurrency", "available_capacity", "free_slots"), None)
        if available is not None and not any(
            key in value for key in ("max_concurrency", "concurrency_limit", "max_workers", "capacity")
        ):
            max_concurrency = active_requests + _integer(available, 0, minimum=0)
        return cls(
            provider_id=identity,
            healthy=_boolean(status, True),
            quota_remaining=_integer(
                first_from(
                    (value, quota_data),
                    ("quota_remaining", "remaining_quota", "requests_remaining", "rate_limit_remaining", "remaining"),
                    UNKNOWN_LIMIT,
                ),
                UNKNOWN_LIMIT,
            ),
            latency_ms=_integer(
                first_from(
                    (value, latency_data),
                    ("latency_ms", "p95_latency_ms", "average_latency_ms", "avg_latency_ms", "p95_ms", "average_ms"),
                    0,
                ),
                0,
                minimum=0,
            ),
            context_window_tokens=_integer(
                first_from(
                    (value, context_data),
                    ("context_window_tokens", "context_tokens", "max_context_tokens", "context_length", "max_tokens", "limit"),
                    UNKNOWN_LIMIT,
                ),
                UNKNOWN_LIMIT,
            ),
            token_budget_remaining=_integer(
                first_from(
                    (value, token_data),
                    ("token_budget_remaining", "remaining_tokens", "tokens_remaining", "token_quota_remaining", "remaining", "available"),
                    UNKNOWN_LIMIT,
                ),
                UNKNOWN_LIMIT,
            ),
            max_concurrency=max_concurrency,
            active_requests=active_requests,
            capabilities=_strings(_first(value, ("capabilities", "supported_capabilities", "features"), ())),
            observed_at_ms=_integer(_first(value, ("observed_at_ms", "measured_at_ms", "timestamp_ms"), 0), 0, minimum=0),
            retry_after_ms=_integer(_first(value, ("retry_after_ms", "backoff_ms", "cooldown_ms"), 0), 0, minimum=0),
        )


def normalize_provider_capacity(
    value: ProviderCapacity | Mapping[str, Any],
    *,
    provider_id: str = "",
) -> ProviderCapacity:
    if isinstance(value, ProviderCapacity):
        if provider_id and provider_id.strip().lower() != value.provider_id:
            return replace(value, provider_id=provider_id.strip().lower())
        return value
    return ProviderCapacity.from_mapping(value, provider_id=provider_id)


def normalize_provider_capacities(
    values: Mapping[str, Any] | Iterable[ProviderCapacity | Mapping[str, Any]] | None,
) -> tuple[ProviderCapacity, ...]:
    """Normalize provider-keyed or sequence telemetry in stable name order."""

    normalized: list[ProviderCapacity] = []
    if values is None:
        return ()
    if isinstance(values, Mapping):
        nested_providers = values.get("providers")
        if isinstance(nested_providers, Mapping):
            return normalize_provider_capacities(nested_providers)
        if isinstance(nested_providers, Iterable) and not isinstance(
            nested_providers, (str, bytes)
        ):
            return normalize_provider_capacities(nested_providers)
        # A mapping containing provider fields is one snapshot; otherwise it is
        # a provider-name -> snapshot collection.
        identity_keys = {"provider_id", "provider", "name", "effective_provider_name"}
        telemetry_keys = identity_keys | {"healthy", "status", "max_concurrency", "latency_ms"}
        if telemetry_keys.intersection(values):
            normalized.append(normalize_provider_capacity(values))
        else:
            for name, raw in values.items():
                if isinstance(raw, ProviderCapacity):
                    normalized.append(normalize_provider_capacity(raw, provider_id=str(name)))
                elif isinstance(raw, Mapping):
                    normalized.append(normalize_provider_capacity(raw, provider_id=str(name)))
    else:
        for raw in values:
            normalized.append(normalize_provider_capacity(raw))
    by_id = {item.provider_id: item for item in normalized}
    return tuple(by_id[name] for name in sorted(by_id))


@dataclass(frozen=True)
class LaneResourceRequirements:
    """Resources and provider features needed by one candidate lane."""

    lane_id: str = ""
    stage: str = "execution"
    resource_class: str = "cpu-small"
    required_capabilities: tuple[str, ...] = ()
    provider_id: str = ""
    requires_provider: bool = False
    context_tokens: int = 0
    token_budget: int = 0
    quota_units: int = 1
    memory_bytes: int = 0
    gpu_memory_bytes: int = 0
    disk_bytes: int = 0
    max_provider_latency_ms: int = 0
    process_slots: int = 1
    queue_age_ms: int = 0
    merge_age_ms: int = 0
    critical_path_length: int = 0
    downstream_unlock_value: int = 0
    enqueue_sequence: int = 0
    fairness_key: str = ""

    def __post_init__(self) -> None:
        for name in (
            "context_tokens",
            "token_budget",
            "quota_units",
            "memory_bytes",
            "gpu_memory_bytes",
            "disk_bytes",
            "max_provider_latency_ms",
            "queue_age_ms",
            "merge_age_ms",
            "critical_path_length",
            "downstream_unlock_value",
            "enqueue_sequence",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if isinstance(self.process_slots, bool) or int(self.process_slots) <= 0:
            raise ValueError("process_slots must be a positive integer")
        object.__setattr__(
            self,
            "resource_class",
            normalize_resource_class(self.resource_class),
        )
        object.__setattr__(self, "stage", normalize_adaptive_stage(self.stage))
        object.__setattr__(
            self,
            "provider_id",
            str(self.provider_id or "").strip().lower(),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _strings(self.required_capabilities),
        )
        object.__setattr__(
            self,
            "fairness_key",
            str(self.fairness_key or self.stage).strip().lower(),
        )

    @property
    def provider_required(self) -> bool:
        return bool(
            self.requires_provider
            or self.provider_id
            or self.context_tokens
            or self.token_budget
            or any(item.startswith("llm:") for item in self.required_capabilities)
        )

    @property
    def resource_pool(self) -> str:
        return resource_pool(self.resource_class)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_capabilities"] = list(self.required_capabilities)
        payload["provider_required"] = self.provider_required
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LaneResourceRequirements":
        # Planning payloads may retain resource hints in the selected task or
        # queue payload.  Top-level explicit fields win.
        queue = _mapping(value.get("queue_payload"))
        task = _mapping(_mapping(value.get("profile_g") or queue.get("profile_g")).get("task"))

        def first(*names: str, default: Any = None) -> Any:
            for source in (value, queue, task):
                found = _first(source, names, None)
                if found is not None:
                    return found
            return default

        provider = str(first("provider_id", "llm_provider", "provider", default="") or "").strip().lower()
        context = _integer(
            first("context_tokens", "required_context_tokens", "estimated_context_tokens", "context_length", default=0),
            0,
            minimum=0,
        )
        tokens = _integer(
            first("token_budget", "required_tokens", "estimated_tokens", "max_new_tokens", default=0),
            0,
            minimum=0,
        )
        return cls(
            lane_id=str(first("lane_id", "bundle_key", "parallel_lane", "task_cid", default="") or ""),
            stage=normalize_adaptive_stage(
                first("stage", "scheduler_stage", "pipeline_stage", default="execution")
            ),
            resource_class=str(first("resource_class", default="cpu-small") or "cpu-small").strip().lower(),
            required_capabilities=_strings(first("required_capabilities", "capabilities", default=())),
            provider_id=provider,
            requires_provider=_boolean(first("requires_provider", "requires_llm", default=False), False),
            context_tokens=context,
            token_budget=tokens,
            quota_units=_integer(first("quota_units", "quota_cost", "request_cost", default=1), 1, minimum=0),
            memory_bytes=_integer(first("memory_bytes", "required_memory_bytes", default=0), 0, minimum=0),
            gpu_memory_bytes=_integer(
                first(
                    "gpu_memory_bytes",
                    "required_gpu_memory_bytes",
                    "vram_bytes",
                    default=0,
                ),
                0,
                minimum=0,
            ),
            disk_bytes=_integer(first("disk_bytes", "required_disk_bytes", default=0), 0, minimum=0),
            max_provider_latency_ms=_integer(
                first("max_provider_latency_ms", "max_latency_ms", "latency_budget_ms", default=0),
                0,
                minimum=0,
            ),
            process_slots=_integer(
                first(
                    "process_slots",
                    "required_processes",
                    "processes",
                    "portfolio_width",
                    default=1,
                ),
                1,
                minimum=1,
            ),
            queue_age_ms=_integer(
                first("queue_age_ms", "wait_age_ms", default=0),
                0,
                minimum=0,
            )
            or _integer(
                first("age_seconds", "queue_age_seconds", default=0),
                0,
                minimum=0,
            )
            * 1000,
            merge_age_ms=_integer(
                first("merge_age_ms", "merge_wait_ms", default=0),
                0,
                minimum=0,
            ),
            critical_path_length=_integer(
                first(
                    "critical_path_length",
                    "critical_path_value",
                    "critical_path_score",
                    default=0,
                ),
                0,
                minimum=0,
            ),
            downstream_unlock_value=_integer(
                first(
                    "downstream_unlock_value",
                    "unlock_value",
                    default=0,
                ),
                0,
                minimum=0,
            ),
            enqueue_sequence=_integer(
                first(
                    "enqueue_sequence",
                    "queue_sequence",
                    "schedule_rank",
                    default=0,
                ),
                0,
                minimum=0,
            ),
            fairness_key=str(
                first(
                    "fairness_key",
                    "parallel_lane",
                    "goal_cid",
                    default="",
                )
                or ""
            ),
        )


@dataclass(frozen=True)
class ChildResourceLimits:
    """Hard limits passed from one supervisor lease to nested child pools."""

    max_processes: int
    portfolio_max_parallel: int
    kernel_max_parallel: int
    wall_time_ms: int = 0
    cpu_time_ms: int = 0
    memory_bytes: int = 0
    gpu_memory_bytes: int = 0
    disk_bytes: int = 0
    model_token_limit: int = 0
    provider_quota: int = 0
    context_tokens: int = 0
    maximum_provider_latency_ms: int = 0

    def __post_init__(self) -> None:
        for name in (
            "max_processes",
            "portfolio_max_parallel",
            "kernel_max_parallel",
            "wall_time_ms",
            "cpu_time_ms",
            "memory_bytes",
            "gpu_memory_bytes",
            "disk_bytes",
            "model_token_limit",
            "provider_quota",
            "context_tokens",
            "maximum_provider_latency_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceLeaseBudget:
    """One top-level budget shared by proof, model, validation and I/O work.

    Zero byte/time/token values mean that the corresponding plan did not
    declare a finite limit.  Concurrency values are always positive because a
    lease that cannot execute is represented by an admission rejection.
    """

    max_parallel: int = 1
    max_cpu_proof_concurrency: int = 1
    max_model_concurrency: int = 1
    max_artifact_concurrency: int = 1
    max_processes: int = 1
    wall_time_ms: int = 0
    cpu_time_ms: int = 0
    memory_bytes: int = 0
    gpu_memory_bytes: int = 0
    disk_bytes: int = 0
    model_token_limit: int = 0
    provider_quota: int = 0
    context_tokens: int = 0
    maximum_provider_latency_ms: int = 0

    def __post_init__(self) -> None:
        for name in (
            "max_parallel",
            "max_cpu_proof_concurrency",
            "max_model_concurrency",
            "max_artifact_concurrency",
            "max_processes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "wall_time_ms",
            "cpu_time_ms",
            "memory_bytes",
            "gpu_memory_bytes",
            "disk_bytes",
            "model_token_limit",
            "provider_quota",
            "context_tokens",
            "maximum_provider_latency_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @classmethod
    def from_resource_budget(
        cls,
        value: Any,
        *,
        max_parallel: int,
        max_cpu_proof_concurrency: int = 0,
        max_model_concurrency: int = 0,
        max_artifact_concurrency: int = 0,
        maximum_provider_latency_ms: int = 0,
        context_tokens: int = 0,
    ) -> "ResourceLeaseBudget":
        """Adapt a formal ``ResourceBudget`` without importing its module."""

        parallel = max(1, int(max_parallel))

        def budget_value(name: str) -> int:
            raw = (
                value.get(name, 0)
                if isinstance(value, Mapping)
                else getattr(value, name, 0)
            )
            return _integer(raw, 0, minimum=0)

        declared_processes = budget_value("max_processes")
        process_limit = min(parallel, declared_processes) if declared_processes else parallel
        return cls(
            max_parallel=process_limit,
            max_cpu_proof_concurrency=min(
                process_limit,
                max_cpu_proof_concurrency or process_limit,
            ),
            max_model_concurrency=min(
                process_limit,
                max_model_concurrency or process_limit,
            ),
            max_artifact_concurrency=min(
                process_limit,
                max_artifact_concurrency or process_limit,
            ),
            max_processes=process_limit,
            wall_time_ms=budget_value("wall_time_ms"),
            cpu_time_ms=budget_value("cpu_time_ms"),
            memory_bytes=budget_value("memory_bytes"),
            gpu_memory_bytes=budget_value("gpu_memory_bytes"),
            disk_bytes=budget_value("disk_bytes"),
            model_token_limit=budget_value("model_token_limit"),
            provider_quota=budget_value("provider_quota"),
            context_tokens=max(0, int(context_tokens)),
            maximum_provider_latency_ms=max(0, int(maximum_provider_latency_ms)),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResourceLeaseBudget":
        defaults = cls()
        names = tuple(asdict(defaults))
        return cls(
            **{
                name: _integer(
                    value.get(name),
                    getattr(defaults, name),
                    minimum=1
                    if name
                    in {
                        "max_parallel",
                        "max_cpu_proof_concurrency",
                        "max_model_concurrency",
                        "max_artifact_concurrency",
                        "max_processes",
                    }
                    else 0,
                )
                for name in names
            }
        )

    def child_limits(
        self,
        requirement: LaneResourceRequirements,
        *,
        granted_processes: int | None = None,
    ) -> ChildResourceLimits:
        """Derive nested portfolio/kernel limits from this exact lease."""

        processes = max(
            1,
            min(
                self.max_processes,
                requirement.process_slots,
                granted_processes if granted_processes is not None else requirement.process_slots,
            ),
        )
        is_solver = requirement.resource_class == ProofResourceClass.SOLVER.value
        is_kernel = requirement.resource_class == ProofResourceClass.KERNEL.value
        latency = self.maximum_provider_latency_ms
        if requirement.max_provider_latency_ms:
            latency = (
                min(latency, requirement.max_provider_latency_ms)
                if latency
                else requirement.max_provider_latency_ms
            )
        return ChildResourceLimits(
            max_processes=processes,
            portfolio_max_parallel=processes if is_solver else 1,
            kernel_max_parallel=processes if is_kernel else 1,
            wall_time_ms=self.wall_time_ms,
            cpu_time_ms=self.cpu_time_ms,
            memory_bytes=self.memory_bytes,
            gpu_memory_bytes=(
                min(self.gpu_memory_bytes, requirement.gpu_memory_bytes)
                if self.gpu_memory_bytes and requirement.gpu_memory_bytes
                else (self.gpu_memory_bytes or requirement.gpu_memory_bytes)
            ),
            disk_bytes=self.disk_bytes,
            model_token_limit=min(
                item
                for item in (self.model_token_limit, requirement.token_budget)
                if item > 0
            )
            if self.model_token_limit and requirement.token_budget
            else (self.model_token_limit or requirement.token_budget),
            provider_quota=min(
                item
                for item in (self.provider_quota, requirement.quota_units)
                if item > 0
            )
            if self.provider_quota and requirement.quota_units
            else (self.provider_quota or requirement.quota_units),
            context_tokens=requirement.context_tokens or self.context_tokens,
            maximum_provider_latency_ms=latency,
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


# Descriptive alias used by integrations which name the owning layer.
SupervisorResourceLeaseBudget = ResourceLeaseBudget


@dataclass(frozen=True)
class ResourcePolicy:
    """Configured hard bounds and pre-exhaustion high-watermarks."""

    max_lanes: int = 1
    cpu_high_watermark_percent: int = 90
    memory_high_watermark_percent: int = 90
    disk_high_watermark_percent: int = 95
    gpu_memory_high_watermark_percent: int = 95
    minimum_memory_available_bytes: int = 0
    minimum_gpu_memory_available_bytes: int = 0
    minimum_disk_available_bytes: int = 0
    maximum_provider_latency_ms: int = 120_000
    provider_quota_reserve: int = 0
    provider_token_reserve: int = 0
    require_provider_telemetry: bool = True
    max_cpu_proof_concurrency: int = 0
    max_model_concurrency: int = 0
    max_artifact_concurrency: int = 0
    resource_class_limits: Mapping[str, int] = field(default_factory=dict)
    adaptive_enabled: bool = False
    adaptive_target_utilization_percent: int = 75
    adaptive_hysteresis_percent: int = 10
    adaptive_recovery_samples: int = 2
    adaptive_queue_depth_per_slot: int = 1
    adaptive_merge_age_ms: int = 60_000
    adaptive_starvation_age_ms: int = 300_000
    adaptive_max_pending_tasks: int = 256
    adaptive_max_merge_debt: int = 8
    adaptive_artifact_pressure_high_watermark_percent: int = 90
    adaptive_minimum_throughput_multiplier: int = 3
    adaptive_max_duplicate_compute_percent: int = 5
    stage_concurrency_limits: Mapping[str, int] = field(default_factory=dict)
    stage_min_concurrency: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_lanes < 0:
            raise ValueError("max_lanes must be non-negative")
        for name in (
            "cpu_high_watermark_percent", "memory_high_watermark_percent",
            "disk_high_watermark_percent", "gpu_memory_high_watermark_percent",
        ):
            if not 0 <= int(getattr(self, name)) <= 100:
                raise ValueError(f"{name} must be in [0, 100]")
        for name in (
            "minimum_memory_available_bytes",
            "minimum_gpu_memory_available_bytes",
            "minimum_disk_available_bytes",
            "maximum_provider_latency_ms", "provider_quota_reserve", "provider_token_reserve",
            "max_cpu_proof_concurrency", "max_model_concurrency",
            "max_artifact_concurrency",
            "adaptive_merge_age_ms", "adaptive_starvation_age_ms",
            "adaptive_max_pending_tasks", "adaptive_max_merge_debt",
            "adaptive_minimum_throughput_multiplier",
            "adaptive_max_duplicate_compute_percent",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 1 <= int(self.adaptive_target_utilization_percent) <= 100:
            raise ValueError("adaptive_target_utilization_percent must be in [1, 100]")
        if not 0 <= int(self.adaptive_hysteresis_percent) <= 100:
            raise ValueError("adaptive_hysteresis_percent must be in [0, 100]")
        for name in (
            "adaptive_max_pending_tasks",
            "adaptive_max_merge_debt",
            "adaptive_artifact_pressure_high_watermark_percent",
            "adaptive_minimum_throughput_multiplier",
            "adaptive_max_duplicate_compute_percent",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if not 0 <= int(
            self.adaptive_artifact_pressure_high_watermark_percent
        ) <= 100:
            raise ValueError(
                "adaptive_artifact_pressure_high_watermark_percent "
                "must be in [0, 100]"
            )
        if self.adaptive_minimum_throughput_multiplier < 1:
            raise ValueError(
                "adaptive_minimum_throughput_multiplier must be positive"
            )
        if self.adaptive_max_duplicate_compute_percent > 100:
            raise ValueError(
                "adaptive_max_duplicate_compute_percent must be in [0, 100]"
            )
        if (
            isinstance(self.adaptive_recovery_samples, bool)
            or int(self.adaptive_recovery_samples) <= 0
        ):
            raise ValueError("adaptive_recovery_samples must be positive")
        if (
            isinstance(self.adaptive_queue_depth_per_slot, bool)
            or int(self.adaptive_queue_depth_per_slot) <= 0
        ):
            raise ValueError("adaptive_queue_depth_per_slot must be positive")
        normalized_limits: dict[str, int] = {}
        for raw_name, raw_limit in (self.resource_class_limits or {}).items():
            name = normalize_resource_class(raw_name)
            if not name:
                raise ValueError("resource class limit names must be non-empty")
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or raw_limit <= 0:
                raise ValueError("resource class limits must be positive integers")
            normalized_limits[name] = raw_limit
        object.__setattr__(self, "resource_class_limits", normalized_limits)
        stage_limits: dict[str, int] = {}
        for raw_name, raw_limit in (self.stage_concurrency_limits or {}).items():
            name = normalize_adaptive_stage(raw_name)
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or raw_limit <= 0:
                raise ValueError("stage concurrency limits must be positive integers")
            stage_limits[name] = min(raw_limit, self.max_lanes) if self.max_lanes else raw_limit
        stage_minimums: dict[str, int] = {}
        for raw_name, raw_limit in (self.stage_min_concurrency or {}).items():
            name = normalize_adaptive_stage(raw_name)
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or raw_limit < 0:
                raise ValueError("stage minimum concurrency must be non-negative integers")
            ceiling = stage_limits.get(name, self.max_lanes)
            if ceiling and raw_limit > ceiling:
                raise ValueError("stage minimum concurrency cannot exceed its stage limit")
            stage_minimums[name] = raw_limit
        object.__setattr__(self, "stage_concurrency_limits", stage_limits)
        object.__setattr__(self, "stage_min_concurrency", stage_minimums)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResourcePolicy":
        defaults = cls()
        return cls(
            max_lanes=_integer(_first(value, ("max_lanes", "worker_limit", "max_workers"), defaults.max_lanes), defaults.max_lanes, minimum=0),
            cpu_high_watermark_percent=_integer(_first(value, ("cpu_high_watermark_percent", "max_cpu_percent"), defaults.cpu_high_watermark_percent), defaults.cpu_high_watermark_percent, minimum=0),
            memory_high_watermark_percent=_integer(_first(value, ("memory_high_watermark_percent", "max_memory_percent"), defaults.memory_high_watermark_percent), defaults.memory_high_watermark_percent, minimum=0),
            disk_high_watermark_percent=_integer(_first(value, ("disk_high_watermark_percent", "max_disk_percent"), defaults.disk_high_watermark_percent), defaults.disk_high_watermark_percent, minimum=0),
            gpu_memory_high_watermark_percent=_integer(
                _first(
                    value,
                    (
                        "gpu_memory_high_watermark_percent",
                        "max_gpu_memory_percent",
                        "max_vram_percent",
                    ),
                    defaults.gpu_memory_high_watermark_percent,
                ),
                defaults.gpu_memory_high_watermark_percent,
                minimum=0,
            ),
            minimum_memory_available_bytes=_integer(_first(value, ("minimum_memory_available_bytes", "min_memory_available_bytes"), 0), 0, minimum=0),
            minimum_gpu_memory_available_bytes=_integer(
                _first(
                    value,
                    (
                        "minimum_gpu_memory_available_bytes",
                        "min_gpu_memory_available_bytes",
                        "minimum_vram_available_bytes",
                    ),
                    0,
                ),
                0,
                minimum=0,
            ),
            minimum_disk_available_bytes=_integer(_first(value, ("minimum_disk_available_bytes", "min_disk_available_bytes"), 0), 0, minimum=0),
            maximum_provider_latency_ms=_integer(_first(value, ("maximum_provider_latency_ms", "max_provider_latency_ms", "latency_limit_ms"), defaults.maximum_provider_latency_ms), defaults.maximum_provider_latency_ms, minimum=0),
            provider_quota_reserve=_integer(_first(value, ("provider_quota_reserve", "quota_reserve"), 0), 0, minimum=0),
            provider_token_reserve=_integer(_first(value, ("provider_token_reserve", "token_reserve"), 0), 0, minimum=0),
            require_provider_telemetry=_boolean(value.get("require_provider_telemetry"), True),
            max_cpu_proof_concurrency=_integer(
                _first(
                    value,
                    ("max_cpu_proof_concurrency", "cpu_proof_concurrency", "max_cpu_parallel"),
                    0,
                ),
                0,
                minimum=0,
            ),
            max_model_concurrency=_integer(
                _first(value, ("max_model_concurrency", "model_concurrency"), 0),
                0,
                minimum=0,
            ),
            max_artifact_concurrency=_integer(
                _first(value, ("max_artifact_concurrency", "artifact_concurrency"), 0),
                0,
                minimum=0,
            ),
            resource_class_limits=_mapping(
                _first(value, ("resource_class_limits", "resource_limits"), {})
            ),
            adaptive_enabled=_boolean(
                _first(value, ("adaptive_enabled", "adaptive_admission"), False),
                False,
            ),
            adaptive_target_utilization_percent=_integer(
                _first(
                    value,
                    (
                        "adaptive_target_utilization_percent",
                        "target_utilization_percent",
                    ),
                    defaults.adaptive_target_utilization_percent,
                ),
                defaults.adaptive_target_utilization_percent,
                minimum=1,
            ),
            adaptive_hysteresis_percent=_integer(
                _first(
                    value,
                    (
                        "adaptive_hysteresis_percent",
                        "hysteresis_percent",
                        "recovery_hysteresis_percent",
                    ),
                    defaults.adaptive_hysteresis_percent,
                ),
                defaults.adaptive_hysteresis_percent,
                minimum=0,
            ),
            adaptive_recovery_samples=_integer(
                _first(
                    value,
                    (
                        "adaptive_recovery_samples",
                        "recovery_samples",
                        "scale_up_samples",
                    ),
                    defaults.adaptive_recovery_samples,
                ),
                defaults.adaptive_recovery_samples,
                minimum=1,
            ),
            adaptive_queue_depth_per_slot=_integer(
                _first(
                    value,
                    (
                        "adaptive_queue_depth_per_slot",
                        "queue_depth_per_slot",
                    ),
                    defaults.adaptive_queue_depth_per_slot,
                ),
                defaults.adaptive_queue_depth_per_slot,
                minimum=1,
            ),
            adaptive_merge_age_ms=_integer(
                _first(
                    value,
                    (
                        "adaptive_merge_age_ms",
                        "merge_age_priority_ms",
                        "maximum_merge_wait_ms",
                    ),
                    defaults.adaptive_merge_age_ms,
                ),
                defaults.adaptive_merge_age_ms,
                minimum=0,
            ),
            adaptive_starvation_age_ms=_integer(
                _first(
                    value,
                    (
                        "adaptive_starvation_age_ms",
                        "starvation_age_ms",
                        "maximum_queue_wait_ms",
                    ),
                    defaults.adaptive_starvation_age_ms,
                ),
                defaults.adaptive_starvation_age_ms,
                minimum=0,
            ),
            adaptive_max_pending_tasks=_integer(
                _first(
                    value,
                    (
                        "adaptive_max_pending_tasks",
                        "max_pending_tasks",
                        "task_generation_queue_limit",
                    ),
                    defaults.adaptive_max_pending_tasks,
                ),
                defaults.adaptive_max_pending_tasks,
                minimum=0,
            ),
            adaptive_max_merge_debt=_integer(
                _first(
                    value,
                    (
                        "adaptive_max_merge_debt",
                        "max_merge_debt",
                        "merge_debt_limit",
                    ),
                    defaults.adaptive_max_merge_debt,
                ),
                defaults.adaptive_max_merge_debt,
                minimum=0,
            ),
            adaptive_artifact_pressure_high_watermark_percent=_integer(
                _first(
                    value,
                    (
                        "adaptive_artifact_pressure_high_watermark_percent",
                        "artifact_pressure_high_watermark_percent",
                        "max_artifact_pressure_percent",
                    ),
                    defaults.adaptive_artifact_pressure_high_watermark_percent,
                ),
                defaults.adaptive_artifact_pressure_high_watermark_percent,
                minimum=0,
            ),
            adaptive_minimum_throughput_multiplier=_integer(
                _first(
                    value,
                    (
                        "adaptive_minimum_throughput_multiplier",
                        "minimum_throughput_multiplier",
                    ),
                    defaults.adaptive_minimum_throughput_multiplier,
                ),
                defaults.adaptive_minimum_throughput_multiplier,
                minimum=1,
            ),
            adaptive_max_duplicate_compute_percent=_integer(
                _first(
                    value,
                    (
                        "adaptive_max_duplicate_compute_percent",
                        "max_duplicate_compute_percent",
                    ),
                    defaults.adaptive_max_duplicate_compute_percent,
                ),
                defaults.adaptive_max_duplicate_compute_percent,
                minimum=0,
            ),
            stage_concurrency_limits=_mapping(
                _first(value, ("stage_concurrency_limits", "stage_limits"), {})
            ),
            stage_min_concurrency=_mapping(
                _first(value, ("stage_min_concurrency", "stage_minimums"), {})
            ),
        )


@dataclass(frozen=True)
class AdaptiveStageCapacity:
    """Explainable live concurrency bound for one independently measured stage."""

    stage: str
    configured_limit: int
    effective_limit: int
    active: int
    queued: int
    available: int
    pressure_percent: int
    reason: str
    queue_depth: int = 0
    merge_age_ms: int = 0
    provider_available_slots: int = UNKNOWN_LIMIT
    active_leases: int = 0
    artifact_pressure_percent: int = 0
    merge_debt: int = 0
    recovery_samples: int = 0
    hysteresis_state: str = "stable"
    observed_at_ms: int = 0
    signal_limits: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signal_limits"] = {
            str(name): int(value)
            for name, value in sorted(self.signal_limits.items())
        }
        return payload


@dataclass(frozen=True)
class FairWorkStealDecision:
    """Deterministic selection for an idle stage worker.

    A worker consumes its home-stage queue while it has work.  It may steal
    from another independently limited stage when the home queue is empty, or
    when a foreign item has crossed the configured starvation bound.  The
    selected item remains subject to normal resource admission before it can
    execute.
    """

    worker_stage: str
    selected_lane_id: str = ""
    selected_stage: str = ""
    stolen: bool = False
    starvation_override: bool = False
    critical_path_length: int = 0
    queue_age_ms: int = 0
    considered_lane_ids: tuple[str, ...] = ()

    @property
    def selected(self) -> bool:
        return bool(self.selected_lane_id)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["considered_lane_ids"] = list(self.considered_lane_ids)
        payload["selected"] = self.selected
        return payload


@dataclass(frozen=True)
class TaskGenerationAdmission:
    """Backpressure decision for producers which create more scheduler work."""

    admitted: bool
    reasons: tuple[str, ...] = ()
    pending_tasks: int = 0
    effective_generation_limit: int = 0
    available_generation_slots: int = 0
    artifact_pressure_percent: int = 0
    merge_debt: int = 0
    disk_percent: int = 0
    recovery_samples: int = 0
    hysteresis_state: str = "stable"
    observed_at_ms: int = 0

    @property
    def allowed(self) -> bool:
        return self.admitted

    @property
    def reason(self) -> str:
        return self.reasons[0] if self.reasons else ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["allowed"] = self.allowed
        payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class AdaptiveStageMetrics:
    """Integer-only counters suitable for durable scheduler artifacts."""

    stage: str
    scheduled: int = 0
    admitted: int = 0
    backpressured: int = 0
    completed: int = 0
    accepted: int = 0
    cancelled: int = 0
    leases_acquired: int = 0
    leases_released: int = 0
    lease_transitions: int = 0
    recovery_events: int = 0
    contraction_events: int = 0
    active_leases: int = 0
    total_duration_ms: int = 0
    backpressure_reasons: Mapping[str, int] = field(default_factory=dict)

    @property
    def admission_ratio_millionths(self) -> int:
        return self.admitted * 1_000_000 // self.scheduled if self.scheduled else 0

    @property
    def acceptance_throughput_per_million_ms(self) -> int:
        return (
            self.accepted * 1_000_000 // self.total_duration_ms
            if self.total_duration_ms
            else 0
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["backpressure_reasons"] = {
            str(name): int(value)
            for name, value in sorted(self.backpressure_reasons.items())
        }
        payload["admission_ratio_millionths"] = self.admission_ratio_millionths
        payload["acceptance_throughput_per_million_ms"] = (
            self.acceptance_throughput_per_million_ms
        )
        return payload


@dataclass(frozen=True)
class AdaptiveResourceMetrics:
    """Point-in-time, separately benchmarkable adaptive-admission telemetry."""

    observed_at_ms: int
    stages: tuple[AdaptiveStageMetrics, ...]
    active_lease_count: int = 0
    backpressure_reasons: Mapping[str, int] = field(default_factory=dict)

    @property
    def by_stage(self) -> dict[str, AdaptiveStageMetrics]:
        return {item.stage: item for item in self.stages}

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at_ms": self.observed_at_ms,
            "stages": [item.to_dict() for item in self.stages],
            "active_lease_count": self.active_lease_count,
            "backpressure_reasons": {
                str(name): int(value)
                for name, value in sorted(self.backpressure_reasons.items())
            },
        }


@dataclass
class _MutableStageMetrics:
    scheduled: int = 0
    admitted: int = 0
    backpressured: int = 0
    completed: int = 0
    accepted: int = 0
    cancelled: int = 0
    leases_acquired: int = 0
    leases_released: int = 0
    lease_transitions: int = 0
    recovery_events: int = 0
    contraction_events: int = 0
    active_leases: int = 0
    total_duration_ms: int = 0
    backpressure_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class _AdaptiveStageState:
    effective_limit: int
    last_observed_at_ms: int
    recovery_samples: int = 0
    state: str = "stable"
    limit_reason: str = "configured_limit"


@dataclass
class _TaskGenerationState:
    backpressured: bool = False
    last_observed_at_ms: int = 0
    recovery_samples: int = 0


@dataclass(frozen=True)
class AdmissionDecision:
    lane_id: str
    admitted: bool
    provider_id: str = ""
    reasons: tuple[str, ...] = ()
    configured_max_lanes: int = 0
    host_available_slots: int = 0
    provider_available_slots: int = 0
    effective_slots: int = 0
    capability_fit_millionths: int = 0
    reserved_quota_units: int = 0
    reserved_tokens: int = 0
    resource_class: str = ""
    resource_pool: str = ""
    reserved_process_slots: int = 0
    reserved_memory_bytes: int = 0
    reserved_gpu_memory_bytes: int = 0
    reserved_disk_bytes: int = 0
    stage: str = "execution"
    pressure_percent: int = 0
    queue_depth: int = 0
    merge_age_ms: int = 0
    active_leases: int = 0
    critical_path_length: int = 0
    queue_age_ms: int = 0
    hysteresis_state: str = "stable"
    fairness_key: str = ""
    admission_rank: int = 0

    @property
    def allowed(self) -> bool:
        return self.admitted

    @property
    def reason(self) -> str:
        return self.reasons[0] if self.reasons else ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["allowed"] = self.allowed
        payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class ResourcePoolAdmissionSnapshot:
    """Expose fair evaluation and backpressure for one bounded pool."""

    resource_pool: str
    scheduled_count: int
    admitted_count: int
    backpressured_count: int
    fairness_order: tuple[str, ...] = ()
    fairness_keys: tuple[str, ...] = ()
    admitted_lane_ids: tuple[str, ...] = ()
    backpressure_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        counts = (
            self.scheduled_count,
            self.admitted_count,
            self.backpressured_count,
        )
        if any(isinstance(value, bool) or int(value) < 0 for value in counts):
            raise ValueError("resource pool admission counts must be non-negative")
        if self.admitted_count + self.backpressured_count != self.scheduled_count:
            raise ValueError(
                "resource pool admitted and backpressured counts must cover "
                "every scheduled lane"
            )
        if len(self.fairness_order) != self.scheduled_count:
            raise ValueError(
                "resource pool fairness order must identify every scheduled lane"
            )
        if len(self.fairness_keys) != self.scheduled_count:
            raise ValueError(
                "resource pool fairness keys must identify every scheduled lane"
            )
        if len(self.admitted_lane_ids) != self.admitted_count:
            raise ValueError(
                "resource pool admitted lane identities must match admitted_count"
            )
        if any(int(value) <= 0 for value in self.backpressure_counts.values()):
            raise ValueError("resource pool backpressure counts must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_pool": self.resource_pool,
            "scheduled_count": self.scheduled_count,
            "admitted_count": self.admitted_count,
            "backpressured_count": self.backpressured_count,
            "fairness_order": list(self.fairness_order),
            "fairness_keys": list(self.fairness_keys),
            "admitted_lane_ids": list(self.admitted_lane_ids),
            "backpressure_counts": {
                str(name): int(value)
                for name, value in sorted(self.backpressure_counts.items())
            },
        }


@dataclass(frozen=True)
class ResourceScheduleSnapshot:
    observed_at_ms: int
    host: HostResourceSnapshot
    providers: tuple[ProviderCapacity, ...]
    policy: ResourcePolicy
    decisions: tuple[AdmissionDecision, ...]
    configured_max_lanes: int
    effective_slots: int
    available_slots: int
    admitted_count: int
    backpressure_reasons: tuple[str, ...] = ()
    stage_capacities: tuple[AdaptiveStageCapacity, ...] = ()
    adaptive_metrics: AdaptiveResourceMetrics | None = None
    active_lease_count: int = 0
    backpressure_counts: Mapping[str, int] = field(default_factory=dict)
    signals: Mapping[str, Any] = field(default_factory=dict)
    pool_admissions: tuple[ResourcePoolAdmissionSnapshot, ...] = ()
    task_generation: TaskGenerationAdmission | None = None

    @property
    def admitted_lane_ids(self) -> tuple[str, ...]:
        return tuple(item.lane_id for item in self.decisions if item.admitted)

    @property
    def decision_by_lane_id(self) -> dict[str, AdmissionDecision]:
        return {item.lane_id: item for item in self.decisions}

    def decision_for(self, lane_id: str) -> AdmissionDecision | None:
        """Return the decision for a unique stable lane identity."""

        return self.decision_by_lane_id.get(str(lane_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at_ms": self.observed_at_ms,
            "host": self.host.to_dict(),
            "providers": [item.to_dict() for item in self.providers],
            "policy": self.policy.to_dict(),
            "decisions": [item.to_dict() for item in self.decisions],
            "configured_max_lanes": self.configured_max_lanes,
            "effective_slots": self.effective_slots,
            "available_slots": self.available_slots,
            "admitted_count": self.admitted_count,
            "admitted_lane_ids": list(self.admitted_lane_ids),
            "backpressure_reasons": list(self.backpressure_reasons),
            "stage_capacities": [item.to_dict() for item in self.stage_capacities],
            "adaptive_metrics": (
                self.adaptive_metrics.to_dict()
                if self.adaptive_metrics is not None
                else None
            ),
            "active_lease_count": self.active_lease_count,
            "backpressure_counts": {
                str(name): int(value)
                for name, value in sorted(self.backpressure_counts.items())
            },
            "pool_admissions": [
                item.to_dict() for item in self.pool_admissions
            ],
            "task_generation": (
                self.task_generation.to_dict()
                if self.task_generation is not None
                else None
            ),
            "signals": json.loads(
                json.dumps(dict(self.signals), sort_keys=True)
            ),
        }


@dataclass
class _ProviderReservation:
    requests: int = 0
    quota: int = 0
    tokens: int = 0


@dataclass(frozen=True)
class ResourceAdmissionLease:
    """A reclaimable grant from the supervisor-level resource budget."""

    lease_id: str
    requirement: LaneResourceRequirements
    decision: AdmissionDecision
    budget: ResourceLeaseBudget
    acquired_at_ms: int

    @property
    def lane_id(self) -> str:
        return self.requirement.lane_id

    @property
    def resource_class(self) -> str:
        return self.requirement.resource_class

    @property
    def resource_pool(self) -> str:
        return self.requirement.resource_pool

    @property
    def provider_id(self) -> str:
        return self.decision.provider_id

    @property
    def child_limits(self) -> ChildResourceLimits:
        return self.budget.child_limits(
            self.requirement,
            granted_processes=self.decision.reserved_process_slots,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "lane_id": self.lane_id,
            "resource_class": self.resource_class,
            "resource_pool": self.resource_pool,
            "provider_id": self.provider_id,
            "acquired_at_ms": self.acquired_at_ms,
            "requirement": self.requirement.to_dict(),
            "decision": self.decision.to_dict(),
            "budget": self.budget.to_dict(),
            "child_limits": self.child_limits.to_dict(),
        }


def _mirror_stage_completion(
    metric: Any, stage: str, *, accepted: bool, cancelled: bool
) -> Any:
    """Record a stage completion by stage name. Duration is not stored."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        if cancelled:
            disposition = "cancelled"
        elif accepted:
            disposition = "accepted"
        else:
            disposition = "rejected"
        record_ref = f"{stage}:{disposition}" if stage else disposition
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="stage_completion_record",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return metric


def _mirror_resource_admission(result: Any) -> Any:
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(
            getattr(result, "decision_id", "")
            or getattr(result, "lane_id", "")
            or getattr(result, "provider_id", "")
            or getattr(result, "reason", "")
            or "resource-admission"
        )
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="resource_scheduler_admission",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return result


class ResourceScheduler:
    """Evaluate and reserve host/provider capacity for a reconciliation cycle."""

    def __init__(
        self,
        policy: ResourcePolicy | Mapping[str, Any] | None = None,
        *,
        host_sampler: Callable[..., HostResourceSnapshot] = sample_host_resources,
    ) -> None:
        self.policy = (
            policy
            if isinstance(policy, ResourcePolicy)
            else ResourcePolicy.from_mapping(policy or {})
        )
        self.host_sampler = host_sampler
        self._lease_lock = threading.RLock()
        self._leases: dict[str, ResourceAdmissionLease] = {}
        self._metrics_lock = threading.RLock()
        self._stage_metrics: dict[str, _MutableStageMetrics] = {}
        self._adaptive_state: dict[str, _AdaptiveStageState] = {}
        self._task_generation_state = _TaskGenerationState()
        self._cancelled_lanes: dict[str, str] = {}
        self._known_lanes: set[str] = set()

    def adaptive_stage_capacity(
        self,
        stage: Any,
        *,
        host: HostResourceSnapshot | Mapping[str, Any],
        active: int = 0,
        queued: int = 0,
        merge_age_ms: int = 0,
        provider_available_slots: int = UNKNOWN_LIMIT,
        memory_available_slots: int = UNKNOWN_LIMIT,
        gpu_memory_available_slots: int = UNKNOWN_LIMIT,
        disk_available_slots: int = UNKNOWN_LIMIT,
        artifact_pressure_percent: int = 0,
        merge_debt: int = 0,
        active_leases: int = 0,
    ) -> AdaptiveStageCapacity:
        """Calculate a stage bound from configured limits and live pressure.

        The high-watermark gates in :meth:`evaluate` remain hard stops.
        Below them, adaptive mode contracts concurrency gradually rather than
        admitting a full wave immediately before exhaustion.
        """

        name = normalize_adaptive_stage(stage)
        snapshot = (
            host
            if isinstance(host, HostResourceSnapshot)
            else HostResourceSnapshot.from_mapping(host)
        )
        configured = min(
            self.policy.max_lanes,
            self.policy.stage_concurrency_limits.get(name, self.policy.max_lanes),
        )
        signal_limits = {
            "configured": configured,
            "workers": min(
                configured,
                snapshot.worker_limit,
                snapshot.active_workers + snapshot.available_worker_capacity,
            ),
        }
        for signal_name, raw_value in (
            ("memory", memory_available_slots),
            ("gpu_memory", gpu_memory_available_slots),
            ("disk", disk_available_slots),
            ("provider", provider_available_slots),
        ):
            value = int(raw_value)
            if value >= 0:
                signal_limits[signal_name] = max(0, value)
        resource_limit = min(signal_limits.values(), default=configured)
        profile = adaptive_stage_profile(name)
        active_count = max(0, int(active))
        queued_count = max(0, int(queued))
        merge_age = max(0, int(merge_age_ms))
        artifact_pressure = min(
            100, max(0, int(artifact_pressure_percent))
        )
        current_merge_debt = max(0, int(merge_debt))
        # Merge and persistence are drain stages.  Pressure in their queues
        # contracts upstream generation while preserving capacity to pay down
        # the debt itself.
        if name not in {"merge", "persistence"}:
            artifact_limit = (
                self.policy.adaptive_artifact_pressure_high_watermark_percent
            )
            artifact_target = min(
                artifact_limit,
                self.policy.adaptive_target_utilization_percent,
            )
            if artifact_limit and artifact_pressure > artifact_target:
                artifact_slots = max(
                    0,
                    resource_limit
                    * max(0, artifact_limit - artifact_pressure)
                    // max(1, artifact_limit - artifact_target),
                )
                signal_limits["artifact_pressure"] = artifact_slots
            merge_limit = self.policy.adaptive_max_merge_debt
            if merge_limit and current_merge_debt:
                signal_limits["merge_debt"] = max(
                    0,
                    resource_limit
                    * max(0, merge_limit - current_merge_debt)
                    // merge_limit,
                )
        resource_limit = min(signal_limits.values(), default=configured)
        minimum = min(
            resource_limit,
            self.policy.stage_min_concurrency.get(name, 1),
        )
        pressure_values = [
            snapshot.cpu_percent,
            snapshot.memory_percent,
        ]
        if profile.disk_sensitive:
            pressure_values.append(snapshot.disk_percent)
        if name != "persistence":
            pressure_values.append(artifact_pressure)
        if (
            profile.gpu_memory_sensitive
            and snapshot.gpu_memory_total_bytes > 0
        ):
            pressure_values.append(snapshot.gpu_memory_percent)
        pressure = max(
            pressure_values,
            default=0,
        )
        candidate = resource_limit
        reason = "configured_limit"
        if self.policy.adaptive_enabled and resource_limit:
            target = self.policy.adaptive_target_utilization_percent
            if pressure > target:
                remaining = max(0, 100 - pressure)
                span = max(1, 100 - target)
                candidate = minimum + (
                    max(0, resource_limit - minimum) * remaining // span
                )
                candidate = max(minimum, min(resource_limit, candidate))
                reason = "live_pressure_backoff"
            else:
                reason = "live_headroom"
        elif resource_limit < configured:
            reason = "resource_signal_limit"

        merge_age_priority = (
            name == "merge"
            and self.policy.adaptive_merge_age_ms
            and merge_age >= self.policy.adaptive_merge_age_ms
        )
        if self.policy.adaptive_enabled and not merge_age_priority:
            # Queue depth represents work waiting in addition to ``active``.
            # One slot is opened for each configured chunk of queued work,
            # avoiding a full fan-out for a shallow queue while retaining the
            # stage minimum.  Integer arithmetic keeps admission artifacts
            # deterministic across hosts.
            queued_slots = (
                queued_count + self.policy.adaptive_queue_depth_per_slot - 1
            ) // self.policy.adaptive_queue_depth_per_slot
            demand_limit = min(
                resource_limit,
                max(minimum, active_count + queued_slots),
            )
            if demand_limit < candidate:
                candidate = demand_limit
                reason = "queue_depth_demand"

        observed_at_ms = max(0, int(snapshot.observed_at_ms))
        hysteresis_state = "stable"
        recovery_samples = 0
        effective = candidate
        if self.policy.adaptive_enabled:
            with self._metrics_lock:
                state = self._adaptive_state.get(name)
                metric = self._stage_metrics.setdefault(
                    name, _MutableStageMetrics()
                )
                if state is None:
                    state = _AdaptiveStageState(
                        effective_limit=candidate,
                        last_observed_at_ms=observed_at_ms,
                        limit_reason=reason,
                    )
                    self._adaptive_state[name] = state
                elif candidate < state.effective_limit:
                    state.effective_limit = candidate
                    state.last_observed_at_ms = max(
                        state.last_observed_at_ms, observed_at_ms
                    )
                    state.recovery_samples = 0
                    state.state = "contracted"
                    state.limit_reason = reason
                    metric.contraction_events += 1
                elif candidate > state.effective_limit:
                    if state.limit_reason == "queue_depth_demand":
                        # Demand changed, resources did not recover. Queue
                        # growth must be actionable in the current scheduling
                        # wave and therefore does not consume recovery samples.
                        state.effective_limit = candidate
                        state.recovery_samples = 0
                        state.state = "stable"
                        state.limit_reason = reason
                        effective = min(resource_limit, state.effective_limit)
                        hysteresis_state = state.state
                        recovery_samples = state.recovery_samples
                        continue_recovery = False
                    else:
                        continue_recovery = True
                    recovery_pressure = max(
                        0,
                        self.policy.adaptive_target_utilization_percent
                        - self.policy.adaptive_hysteresis_percent,
                    )
                    fresh_sample = observed_at_ms > state.last_observed_at_ms
                    below_recovery_watermark = pressure <= recovery_pressure
                    # Capacity which was lost solely to a provider/worker/byte
                    # signal can recover under normal target pressure. A
                    # utilization contraction requires the lower watermark.
                    pressure_recovery = (
                        state.state != "contracted"
                        or below_recovery_watermark
                        or reason == "resource_signal_limit"
                    )
                    if continue_recovery and fresh_sample and pressure_recovery:
                        state.recovery_samples += 1
                        state.last_observed_at_ms = observed_at_ms
                    if (
                        continue_recovery
                        and state.recovery_samples
                        >= self.policy.adaptive_recovery_samples
                    ):
                        state.effective_limit = candidate
                        state.recovery_samples = 0
                        state.state = "recovered"
                        state.limit_reason = reason
                        metric.recovery_events += 1
                    elif continue_recovery:
                        state.state = "recovering"
                else:
                    if observed_at_ms > state.last_observed_at_ms:
                        state.last_observed_at_ms = observed_at_ms
                    if state.state not in {"contracted", "recovering"}:
                        state.state = "stable"
                    state.recovery_samples = (
                        state.recovery_samples
                        if state.state == "recovering"
                        else 0
                    )
                effective = min(resource_limit, state.effective_limit)
                hysteresis_state = state.state
                recovery_samples = state.recovery_samples
        if merge_age_priority and effective:
            reason = "merge_age_priority"
        return AdaptiveStageCapacity(
            stage=name,
            configured_limit=configured,
            effective_limit=effective,
            active=active_count,
            queued=queued_count,
            available=max(0, effective - active_count),
            pressure_percent=pressure,
            reason=reason,
            queue_depth=queued_count,
            merge_age_ms=merge_age,
            provider_available_slots=int(provider_available_slots),
            active_leases=max(0, int(active_leases)),
            artifact_pressure_percent=artifact_pressure,
            merge_debt=current_merge_debt,
            recovery_samples=recovery_samples,
            hysteresis_state=hysteresis_state,
            observed_at_ms=observed_at_ms,
            signal_limits=signal_limits,
        )

    def record_stage_completion(
        self,
        stage: Any,
        *,
        duration_ms: int,
        accepted: bool,
        cancelled: bool = False,
    ) -> AdaptiveStageMetrics:
        """Record one terminal result and return that stage's new metrics."""

        name = normalize_adaptive_stage(stage)
        duration = max(0, int(duration_ms))
        with self._metrics_lock:
            mutable = self._stage_metrics.setdefault(name, _MutableStageMetrics())
            mutable.completed += 1
            mutable.total_duration_ms += duration
            if accepted:
                mutable.accepted += 1
            if cancelled:
                mutable.cancelled += 1
            metric = self._stage_metric(name, mutable)
        return _mirror_stage_completion(
            metric, name, accepted=accepted, cancelled=cancelled
        )

    def _stage_metric(
        self,
        stage: str,
        value: _MutableStageMetrics,
    ) -> AdaptiveStageMetrics:
        payload = asdict(value)
        payload["backpressure_reasons"] = dict(value.backpressure_reasons)
        return AdaptiveStageMetrics(stage=stage, **payload)

    def metrics_snapshot(self, *, observed_at_ms: int | None = None) -> AdaptiveResourceMetrics:
        """Return immutable per-stage admission and acceptance telemetry."""

        # Keep the global lock order lease -> metrics. Admission writes a lease
        # before updating counters, so taking these in the opposite order here
        # could deadlock a concurrent metrics scrape.
        lease_stages: dict[str, int] = {}
        with self._lease_lock:
            active_lease_count = len(self._leases)
            for lease in self._leases.values():
                stage = lease.requirement.stage
                lease_stages[stage] = lease_stages.get(stage, 0) + 1
        with self._metrics_lock:
            for stage, count in lease_stages.items():
                self._stage_metrics.setdefault(
                    stage, _MutableStageMetrics()
                ).active_leases = count
            for stage, metric in self._stage_metrics.items():
                if stage not in lease_stages:
                    metric.active_leases = 0
            stages = tuple(
                self._stage_metric(name, self._stage_metrics[name])
                for name in sorted(self._stage_metrics)
            )
            backpressure: dict[str, int] = {}
            for metric in self._stage_metrics.values():
                for reason, count in metric.backpressure_reasons.items():
                    backpressure[reason] = backpressure.get(reason, 0) + count
        return AdaptiveResourceMetrics(
            observed_at_ms=(
                max(0, int(observed_at_ms))
                if observed_at_ms is not None
                else int(time.time() * 1000)
            ),
            stages=stages,
            active_lease_count=active_lease_count,
            backpressure_reasons=backpressure,
        )

    def reset_metrics(self) -> AdaptiveResourceMetrics:
        """Atomically clear benchmark counters and return the prior snapshot."""

        with self._lease_lock:
            active_lease_count = len(self._leases)
        with self._metrics_lock:
            previous = AdaptiveResourceMetrics(
                observed_at_ms=int(time.time() * 1000),
                stages=tuple(
                    self._stage_metric(name, self._stage_metrics[name])
                    for name in sorted(self._stage_metrics)
                ),
                active_lease_count=active_lease_count,
                backpressure_reasons={
                    reason: sum(
                        metric.backpressure_reasons.get(reason, 0)
                        for metric in self._stage_metrics.values()
                    )
                    for reason in sorted(
                        {
                            reason
                            for metric in self._stage_metrics.values()
                            for reason in metric.backpressure_reasons
                        }
                    )
                },
            )
            self._stage_metrics.clear()
        return previous

    def task_generation_backpressure(
        self,
        *,
        host: HostResourceSnapshot | Mapping[str, Any],
        pending_tasks: int,
        artifact_pressure_percent: int = 0,
        merge_debt: int = 0,
        observed_at_ms: int | None = None,
    ) -> TaskGenerationAdmission:
        """Decide whether task producers may add more pending work.

        Execution drain stages remain independently schedulable when this
        gate closes.  Recovery requires fresh low-watermark samples so a queue
        hovering around a limit cannot repeatedly fan task generation in and
        out.
        """

        snapshot = (
            host
            if isinstance(host, HostResourceSnapshot)
            else HostResourceSnapshot.from_mapping(host)
        )
        pending = max(0, int(pending_tasks))
        artifact_pressure = min(
            100, max(0, int(artifact_pressure_percent))
        )
        debt = max(0, int(merge_debt))
        observed = (
            max(0, int(observed_at_ms))
            if observed_at_ms is not None
            else snapshot.observed_at_ms or int(time.time() * 1000)
        )
        queue_limit = self.policy.adaptive_max_pending_tasks
        merge_limit = self.policy.adaptive_max_merge_debt
        artifact_limit = (
            self.policy.adaptive_artifact_pressure_high_watermark_percent
        )
        if not self.policy.adaptive_enabled:
            available = max(0, self.policy.max_lanes)
            return TaskGenerationAdmission(
                admitted=available > 0,
                reasons=() if available else ("execution_capacity",),
                pending_tasks=pending,
                effective_generation_limit=pending + available,
                available_generation_slots=available,
                artifact_pressure_percent=artifact_pressure,
                merge_debt=debt,
                disk_percent=snapshot.disk_percent,
                observed_at_ms=observed,
            )
        reasons: list[str] = []
        if queue_limit and pending >= queue_limit:
            reasons.append("pending_task_capacity")
        if merge_limit and debt >= merge_limit:
            reasons.append("merge_debt")
        if artifact_limit and artifact_pressure >= artifact_limit:
            reasons.append("artifact_pressure")
        if snapshot.disk_percent >= self.policy.disk_high_watermark_percent:
            reasons.append("host_disk_high_watermark")

        effective_limit = queue_limit or max(
            pending + self.policy.max_lanes,
            self.policy.max_lanes,
        )
        available = max(0, effective_limit - pending)
        if not available and "pending_task_capacity" not in reasons:
            reasons.append("pending_task_capacity")
        hysteresis_state = "stable"
        recovery_samples = 0
        with self._metrics_lock:
            state = self._task_generation_state
            if reasons:
                state.backpressured = True
                state.recovery_samples = 0
                state.last_observed_at_ms = max(
                    state.last_observed_at_ms, observed
                )
                hysteresis_state = "contracted"
            elif state.backpressured:
                hysteresis = self.policy.adaptive_hysteresis_percent
                queue_margin = (
                    max(1, queue_limit * hysteresis // 100)
                    if queue_limit
                    else 0
                )
                merge_margin = (
                    max(1, merge_limit * hysteresis // 100)
                    if merge_limit
                    else 0
                )
                recovered_low = (
                    (
                        not queue_limit
                        or pending <= max(0, queue_limit - queue_margin)
                    )
                    and (
                        not merge_limit
                        or debt <= max(0, merge_limit - merge_margin)
                    )
                    and (
                        not artifact_limit
                        or artifact_pressure
                        <= max(0, artifact_limit - hysteresis)
                    )
                    and snapshot.disk_percent
                    <= max(
                        0,
                        self.policy.disk_high_watermark_percent - hysteresis,
                    )
                )
                if observed > state.last_observed_at_ms and recovered_low:
                    state.recovery_samples += 1
                    state.last_observed_at_ms = observed
                if (
                    state.recovery_samples
                    >= self.policy.adaptive_recovery_samples
                ):
                    state.backpressured = False
                    state.recovery_samples = 0
                    hysteresis_state = "recovered"
                else:
                    hysteresis_state = "recovering"
                    reasons.append("hysteresis_recovery")
            recovery_samples = state.recovery_samples
            admitted = not state.backpressured and not reasons and available > 0
        return TaskGenerationAdmission(
            admitted=admitted,
            reasons=tuple(dict.fromkeys(reasons)),
            pending_tasks=pending,
            effective_generation_limit=effective_limit,
            available_generation_slots=available,
            artifact_pressure_percent=artifact_pressure,
            merge_debt=debt,
            disk_percent=snapshot.disk_percent,
            recovery_samples=recovery_samples,
            hysteresis_state=hysteresis_state,
            observed_at_ms=observed,
        )

    evaluate_task_generation = task_generation_backpressure

    def fair_work_order(
        self,
        requirements: Iterable[
            LaneResourceRequirements | Mapping[str, Any]
        ],
    ) -> tuple[LaneResourceRequirements, ...]:
        """Return critical-path, starvation-bounded round-robin order."""

        normalized = tuple(
            item
            if isinstance(item, LaneResourceRequirements)
            else LaneResourceRequirements.from_mapping(item)
            for item in requirements
        )
        return self._fair_requirements(normalized)

    def select_stealable_work(
        self,
        requirements: Iterable[
            LaneResourceRequirements | Mapping[str, Any]
        ],
        *,
        worker_stage: Any,
    ) -> FairWorkStealDecision:
        """Select home work or one fair foreign item for an idle stage worker."""

        home = normalize_adaptive_stage(worker_stage)
        ordered = tuple(
            item
            for item in self.fair_work_order(requirements)
            if item.lane_id not in self._cancelled_lanes
        )
        starvation_age = self.policy.adaptive_starvation_age_ms
        starved = tuple(
            item
            for item in ordered
            if starvation_age and item.queue_age_ms >= starvation_age
        )
        local = tuple(item for item in ordered if item.stage == home)
        selected = starved[0] if starved else (local[0] if local else None)
        if selected is None and ordered:
            selected = ordered[0]
        if selected is None:
            return FairWorkStealDecision(worker_stage=home)
        starvation_override = bool(
            starved
            and selected is starved[0]
            and selected.stage != home
            and local
        )
        return FairWorkStealDecision(
            worker_stage=home,
            selected_lane_id=selected.lane_id,
            selected_stage=selected.stage,
            stolen=selected.stage != home,
            starvation_override=starvation_override,
            critical_path_length=selected.critical_path_length,
            queue_age_ms=selected.queue_age_ms,
            considered_lane_ids=tuple(item.lane_id for item in ordered),
        )

    select_work = select_stealable_work

    def _fair_requirements(
        self,
        requirements: tuple[LaneResourceRequirements, ...],
    ) -> tuple[LaneResourceRequirements, ...]:
        if not self.policy.adaptive_enabled or len(requirements) < 2:
            return requirements
        grouped: dict[str, deque[LaneResourceRequirements]] = {}
        for item in requirements:
            grouped.setdefault(item.fairness_key or item.stage, deque()).append(
                item
            )
        starvation_age = self.policy.adaptive_starvation_age_ms
        merge_priority_age = self.policy.adaptive_merge_age_ms

        def priority(item: LaneResourceRequirements) -> tuple[Any, ...]:
            starved = bool(
                starvation_age and item.queue_age_ms >= starvation_age
            )
            overdue_merge = bool(
                item.stage == "merge"
                and merge_priority_age
                and item.merge_age_ms >= merge_priority_age
            )
            return (
                -int(starved),
                -int(overdue_merge),
                -item.critical_path_length,
                -item.downstream_unlock_value,
                -item.merge_age_ms,
                -item.queue_age_ms,
                item.enqueue_sequence,
                item.lane_id,
            )

        for key, items in tuple(grouped.items()):
            grouped[key] = deque(sorted(items, key=priority))
        stages = sorted(
            grouped,
            key=lambda key: (priority(grouped[key][0]), key),
        )
        if len(stages) < 2:
            return tuple(grouped[stages[0]]) if stages else ()
        ordered: list[LaneResourceRequirements] = []
        while any(grouped.values()):
            for stage in stages:
                if grouped[stage]:
                    ordered.append(grouped[stage].popleft())
        return tuple(ordered)

    def _pool_limit(self, pool: str) -> int:
        if pool == "model":
            return self.policy.max_model_concurrency or self.policy.max_lanes
        if pool == "artifact":
            return self.policy.max_artifact_concurrency or self.policy.max_lanes
        if pool == "cpu-general":
            # Residual/validation/bundle work should fill available lanes.
            return self.policy.max_lanes or self.policy.max_cpu_proof_concurrency or 1
        return self.policy.max_cpu_proof_concurrency or self.policy.max_lanes

    def _host_reasons(self, host: HostResourceSnapshot, requirement: LaneResourceRequirements) -> list[str]:
        reasons: list[str] = []
        policy = self.policy
        if host.cpu_percent >= policy.cpu_high_watermark_percent:
            reasons.append("host_cpu_high_watermark")
        if host.memory_percent >= policy.memory_high_watermark_percent:
            reasons.append("host_memory_high_watermark")
        stage_profile = adaptive_stage_profile(requirement.stage)
        if (
            (stage_profile.disk_sensitive or requirement.disk_bytes)
            and host.disk_percent >= policy.disk_high_watermark_percent
        ):
            reasons.append("host_disk_high_watermark")
        if (
            requirement.gpu_memory_bytes
            and host.gpu_memory_percent
            >= policy.gpu_memory_high_watermark_percent
        ):
            reasons.append("host_gpu_memory_high_watermark")
        required_memory = max(policy.minimum_memory_available_bytes, requirement.memory_bytes)
        required_gpu_memory = (
            max(
                policy.minimum_gpu_memory_available_bytes,
                requirement.gpu_memory_bytes,
            )
            if stage_profile.gpu_memory_sensitive
            or requirement.gpu_memory_bytes
            else 0
        )
        required_disk = (
            max(
                policy.minimum_disk_available_bytes,
                requirement.disk_bytes,
            )
            if stage_profile.disk_sensitive or requirement.disk_bytes
            else 0
        )
        if required_memory and host.memory_available_bytes < required_memory:
            reasons.append("host_memory_headroom")
        if required_disk and host.disk_available_bytes < required_disk:
            reasons.append("host_disk_headroom")
        if (
            required_gpu_memory
            and host.gpu_memory_available_bytes < required_gpu_memory
        ):
            reasons.append("host_gpu_memory_headroom")
        if (
            requirement.resource_class
            and host.resource_classes
            and requirement.resource_class not in host.resource_classes
        ):
            legacy_compatible = (
                requirement.resource_class in LEGACY_RESOURCE_CLASSES
                and bool(set(host.resource_classes).intersection(PROOF_RESOURCE_CLASSES))
            ) or (
                requirement.resource_class in PROOF_RESOURCE_CLASSES
                and bool(set(host.resource_classes).intersection(LEGACY_RESOURCE_CLASSES))
            )
            generic_bundle_compatible = (
                requirement.resource_class in GENERIC_BUNDLE_RESOURCE_CLASSES
                and "cpu" in host.capabilities
            )
            # Objective plans often label work with workload-oriented classes
            # (e.g. exclusive-jvm-toolchain) that are not physical host classes.
            # Those still execute on general CPU capacity; provider/capability
            # and stage headroom checks enforce specialization separately.
            # Keep model-pool and GPU-prefixed classes fail-closed so they do
            # not silently admit without matching host resources.
            unregistered_cpu_workload_compatible = (
                "cpu" in host.capabilities
                and resource_pool(requirement.resource_class)
                in {"cpu-proof", "cpu-general"}
                and not str(requirement.resource_class).startswith("gpu")
            )
            if not (
                legacy_compatible
                or generic_bundle_compatible
                or unregistered_cpu_workload_compatible
            ):
                reasons.append("resource_class_mismatch")
        if requirement.provider_required:
            host_required = {
                item.removeprefix("host:")
                for item in requirement.required_capabilities
                if item.startswith("host:")
            }
        else:
            host_required = {
                item.removeprefix("host:")
                for item in requirement.required_capabilities
                if not item.startswith("llm:")
            }
        if host_required.difference(host.capabilities):
            reasons.append("host_capability_mismatch")
        return reasons

    def _provider_reasons(
        self,
        provider: ProviderCapacity,
        requirement: LaneResourceRequirements,
        reservation: _ProviderReservation,
    ) -> list[str]:
        policy = self.policy
        reasons: list[str] = []
        if not provider.healthy:
            reasons.append("provider_unhealthy")
        if provider.retry_after_ms > 0:
            reasons.append("provider_backoff")
        latency_limit = policy.maximum_provider_latency_ms
        if requirement.max_provider_latency_ms:
            latency_limit = min(latency_limit, requirement.max_provider_latency_ms)
        if provider.latency_ms > latency_limit:
            reasons.append("provider_latency")
        if provider.available_concurrency - reservation.requests <= 0:
            reasons.append("provider_concurrency")
        if provider.quota_remaining >= 0 and (
            provider.quota_remaining - reservation.quota - requirement.quota_units
            < policy.provider_quota_reserve
        ):
            reasons.append("provider_quota")
        if provider.context_window_tokens >= 0 and requirement.context_tokens > provider.context_window_tokens:
            reasons.append("provider_context")
        if provider.token_budget_remaining >= 0 and (
            provider.token_budget_remaining - reservation.tokens - requirement.token_budget
            < policy.provider_token_reserve
        ):
            reasons.append("provider_token_budget")
        required = {
            item.removeprefix("llm:")
            for item in requirement.required_capabilities
            if not item.startswith("host:")
        }
        if required.difference(provider.capabilities):
            reasons.append("provider_capability_mismatch")
        return reasons

    @staticmethod
    def _provider_sort_key(provider: ProviderCapacity) -> tuple[int, str]:
        # A measured zero is valid and sorts ahead of higher latency. Provider
        # identity makes otherwise equal selection deterministic.
        return (provider.latency_ms, provider.provider_id)

    def evaluate(
        self,
        requirement: LaneResourceRequirements | Mapping[str, Any],
        *,
        host: HostResourceSnapshot | Mapping[str, Any],
        providers: Mapping[str, Any] | Iterable[ProviderCapacity | Mapping[str, Any]] | None = None,
        admitted_workers: int = 0,
        reservations: Mapping[str, _ProviderReservation] | None = None,
        active_requirements: Iterable[LaneResourceRequirements] = (),
        queue_depth: int = 1,
        merge_age_ms: int | None = None,
        artifact_pressure_percent: int = 0,
        merge_debt: int = 0,
    ) -> AdmissionDecision:
        """Evaluate one lane without mutating caller-owned reservation state."""

        req = requirement if isinstance(requirement, LaneResourceRequirements) else LaneResourceRequirements.from_mapping(requirement)
        host_snapshot = host if isinstance(host, HostResourceSnapshot) else HostResourceSnapshot.from_mapping(host)
        normalized = normalize_provider_capacities(providers)
        configured = self.policy.max_lanes
        active_items = tuple(active_requirements)
        cancellation_reason = self._cancelled_lanes.get(req.lane_id, "")
        active_lease_count = sum(
            1 for item in active_items if item.stage == req.stage
        )
        decision_signals = {
            "queue_depth": max(0, int(queue_depth)),
            "merge_age_ms": max(
                0,
                int(req.merge_age_ms if merge_age_ms is None else merge_age_ms),
            ),
            "active_leases": active_lease_count,
            "critical_path_length": req.critical_path_length,
            "queue_age_ms": req.queue_age_ms,
            "fairness_key": req.fairness_key,
        }
        if cancellation_reason:
            return _mirror_resource_admission(AdmissionDecision(
                lane_id=req.lane_id,
                admitted=False,
                stage=req.stage,
                reasons=("cancelled", cancellation_reason),
                configured_max_lanes=configured,
                resource_class=req.resource_class,
                resource_pool=req.resource_pool,
                **decision_signals,
            ))
        occupied_processes = sum(item.process_slots for item in active_items)
        host_slots = max(
            0,
            min(configured, host_snapshot.worker_limit, host_snapshot.active_workers + host_snapshot.available_worker_capacity)
            - host_snapshot.active_workers
            - max(0, int(admitted_workers))
            - occupied_processes,
        )
        host_reasons = self._host_reasons(host_snapshot, req)
        reserved_memory = sum(item.memory_bytes for item in active_items)
        reserved_gpu_memory = sum(
            item.gpu_memory_bytes for item in active_items
        )
        reserved_disk = sum(item.disk_bytes for item in active_items)
        required_memory = max(
            self.policy.minimum_memory_available_bytes,
            req.memory_bytes,
        )
        stage_profile = adaptive_stage_profile(req.stage)
        required_disk = (
            max(
                self.policy.minimum_disk_available_bytes,
                req.disk_bytes,
            )
            if stage_profile.disk_sensitive or req.disk_bytes
            else 0
        )
        required_gpu_memory = (
            max(
                self.policy.minimum_gpu_memory_available_bytes,
                req.gpu_memory_bytes,
            )
            if stage_profile.gpu_memory_sensitive
            or req.gpu_memory_bytes
            else 0
        )
        if (
            required_memory
            and host_snapshot.memory_available_bytes - reserved_memory < required_memory
            and "host_memory_headroom" not in host_reasons
        ):
            host_reasons.append("host_memory_headroom")
        if (
            required_disk
            and host_snapshot.disk_available_bytes - reserved_disk < required_disk
            and "host_disk_headroom" not in host_reasons
        ):
            host_reasons.append("host_disk_headroom")
        if (
            required_gpu_memory
            and host_snapshot.gpu_memory_available_bytes
            - reserved_gpu_memory
            < required_gpu_memory
            and "host_gpu_memory_headroom" not in host_reasons
        ):
            host_reasons.append("host_gpu_memory_headroom")
        if host_slots < req.process_slots:
            host_reasons.append("host_worker_capacity")
        pool_occupied = sum(
            item.process_slots
            for item in active_items
            if item.resource_pool == req.resource_pool
        )
        if pool_occupied + req.process_slots > self._pool_limit(req.resource_pool):
            host_reasons.append(f"{req.resource_pool.replace('-', '_')}_concurrency")
        class_limit = self.policy.resource_class_limits.get(req.resource_class)
        class_occupied = sum(
            item.process_slots
            for item in active_items
            if item.resource_class == req.resource_class
        )
        if class_limit is not None and class_occupied + req.process_slots > class_limit:
            host_reasons.append("resource_class_concurrency")
        stage_occupied = sum(
            item.process_slots for item in active_items if item.stage == req.stage
        )
        if self.policy.adaptive_enabled or req.stage in self.policy.stage_concurrency_limits:
            memory_slots = (
                max(
                    0,
                    (
                        host_snapshot.memory_available_bytes
                        - reserved_memory
                    )
                    // req.memory_bytes,
                )
                if req.memory_bytes
                else UNKNOWN_LIMIT
            )
            gpu_slots = (
                max(
                    0,
                    (
                        host_snapshot.gpu_memory_available_bytes
                        - reserved_gpu_memory
                    )
                    // req.gpu_memory_bytes,
                )
                if req.gpu_memory_bytes
                else UNKNOWN_LIMIT
            )
            disk_slots = (
                max(
                    0,
                    (
                        host_snapshot.disk_available_bytes
                        - reserved_disk
                    )
                    // req.disk_bytes,
                )
                if req.disk_bytes
                else UNKNOWN_LIMIT
            )
            capacity = self.adaptive_stage_capacity(
                req.stage,
                host=host_snapshot,
                active=stage_occupied,
                queued=max(0, int(queue_depth)),
                merge_age_ms=decision_signals["merge_age_ms"],
                # Stage occupancy includes provider-free analysis/implementation
                # work which happens to report the ``inference`` phase.  Do
                # not compare that aggregate with a model provider's request
                # slots. Provider-required lanes are bounded independently by
                # ``_provider_reasons`` and the per-provider reservations
                # below.
                provider_available_slots=UNKNOWN_LIMIT,
                memory_available_slots=memory_slots,
                gpu_memory_available_slots=gpu_slots,
                disk_available_slots=disk_slots,
                artifact_pressure_percent=artifact_pressure_percent,
                merge_debt=merge_debt,
                active_leases=active_lease_count,
            )
            decision_signals["pressure_percent"] = capacity.pressure_percent
            decision_signals["hysteresis_state"] = capacity.hysteresis_state
            if stage_occupied + req.process_slots > capacity.effective_limit:
                host_reasons.append("stage_concurrency")
        if host_reasons:
            return _mirror_resource_admission(AdmissionDecision(
                lane_id=req.lane_id,
                admitted=False,
                stage=req.stage,
                reasons=tuple(dict.fromkeys(host_reasons)),
                configured_max_lanes=configured,
                host_available_slots=host_slots,
                effective_slots=0,
                resource_class=req.resource_class,
                resource_pool=req.resource_pool,
                **decision_signals,
            ))

        # Backwards compatibility: non-LLM lanes do not require provider
        # telemetry, even when a provider monitor is temporarily unavailable.
        if not req.provider_required:
            return _mirror_resource_admission(AdmissionDecision(
                lane_id=req.lane_id,
                admitted=True,
                stage=req.stage,
                configured_max_lanes=configured,
                host_available_slots=host_slots,
                provider_available_slots=host_slots,
                effective_slots=host_slots,
                capability_fit_millionths=1_000_000,
                resource_class=req.resource_class,
                resource_pool=req.resource_pool,
                reserved_process_slots=req.process_slots,
                reserved_memory_bytes=req.memory_bytes,
                reserved_gpu_memory_bytes=req.gpu_memory_bytes,
                reserved_disk_bytes=req.disk_bytes,
                **decision_signals,
            ))

        candidates = [item for item in normalized if not req.provider_id or item.provider_id == req.provider_id]
        if not candidates:
            reason = "provider_telemetry_unavailable" if self.policy.require_provider_telemetry else "provider_unavailable"
            return _mirror_resource_admission(AdmissionDecision(
                lane_id=req.lane_id,
                admitted=not self.policy.require_provider_telemetry,
                stage=req.stage,
                provider_id=req.provider_id,
                reasons=(reason,),
                configured_max_lanes=configured,
                host_available_slots=host_slots,
                provider_available_slots=0,
                effective_slots=host_slots if not self.policy.require_provider_telemetry else 0,
                capability_fit_millionths=1_000_000 if not self.policy.require_provider_telemetry else 0,
                resource_class=req.resource_class,
                resource_pool=req.resource_pool,
                reserved_process_slots=req.process_slots if not self.policy.require_provider_telemetry else 0,
                reserved_memory_bytes=req.memory_bytes if not self.policy.require_provider_telemetry else 0,
                reserved_gpu_memory_bytes=(
                    req.gpu_memory_bytes
                    if not self.policy.require_provider_telemetry
                    else 0
                ),
                reserved_disk_bytes=req.disk_bytes if not self.policy.require_provider_telemetry else 0,
                **decision_signals,
            ))

        reserved = reservations or {}
        rejected: list[tuple[ProviderCapacity, list[str]]] = []
        for provider in sorted(candidates, key=self._provider_sort_key):
            reservation = reserved.get(provider.provider_id, _ProviderReservation())
            reasons = self._provider_reasons(provider, req, reservation)
            if reasons:
                rejected.append((provider, reasons))
                continue
            provider_slots = max(0, provider.available_concurrency - reservation.requests)
            return _mirror_resource_admission(AdmissionDecision(
                lane_id=req.lane_id,
                admitted=True,
                stage=req.stage,
                provider_id=provider.provider_id,
                configured_max_lanes=configured,
                host_available_slots=host_slots,
                provider_available_slots=provider_slots,
                effective_slots=min(host_slots, provider_slots),
                capability_fit_millionths=1_000_000,
                reserved_quota_units=req.quota_units,
                reserved_tokens=req.token_budget,
                resource_class=req.resource_class,
                resource_pool=req.resource_pool,
                reserved_process_slots=req.process_slots,
                reserved_memory_bytes=req.memory_bytes,
                reserved_gpu_memory_bytes=req.gpu_memory_bytes,
                reserved_disk_bytes=req.disk_bytes,
                **decision_signals,
            ))

        # Preserve all distinct constraint failures. This makes backpressure
        # explainable when multiple providers are unsuitable for different reasons.
        reasons = tuple(dict.fromkeys(reason for _provider, items in rejected for reason in items))
        selected = min((provider for provider, _items in rejected), key=self._provider_sort_key)
        return _mirror_resource_admission(AdmissionDecision(
            lane_id=req.lane_id,
            admitted=False,
            stage=req.stage,
            provider_id=selected.provider_id,
            reasons=reasons or ("provider_unavailable",),
            configured_max_lanes=configured,
            host_available_slots=host_slots,
            provider_available_slots=0,
            effective_slots=0,
            resource_class=req.resource_class,
            resource_pool=req.resource_pool,
            **decision_signals,
        ))

    def acquire(
        self,
        requirement: LaneResourceRequirements | Mapping[str, Any],
        *,
        budget: ResourceLeaseBudget | None = None,
        host: HostResourceSnapshot | Mapping[str, Any] | None = None,
        providers: Mapping[str, Any] | Iterable[ProviderCapacity | Mapping[str, Any]] | None = None,
        path: Path | str = ".",
    ) -> tuple[AdmissionDecision, ResourceAdmissionLease | None]:
        """Atomically reserve a reclaimable local supervisor lease.

        Live host/provider telemetry remains authoritative on every attempt.
        Released leases disappear from all pool and provider reservations, so
        capacity can immediately be reused without waiting for a new sample.
        """

        req = (
            requirement
            if isinstance(requirement, LaneResourceRequirements)
            else LaneResourceRequirements.from_mapping(requirement)
        )
        lease_budget = budget or ResourceLeaseBudget.from_resource_budget(
            {},
            max_parallel=max(1, self.policy.max_lanes),
            max_cpu_proof_concurrency=self._pool_limit("cpu-proof"),
            max_model_concurrency=self._pool_limit("model"),
            max_artifact_concurrency=self._pool_limit("artifact"),
            maximum_provider_latency_ms=self.policy.maximum_provider_latency_ms,
        )
        if lease_budget.maximum_provider_latency_ms:
            effective_latency = (
                min(
                    lease_budget.maximum_provider_latency_ms,
                    req.max_provider_latency_ms,
                )
                if req.max_provider_latency_ms
                else lease_budget.maximum_provider_latency_ms
            )
            req = replace(req, max_provider_latency_ms=effective_latency)
        with self._lease_lock:
            active = tuple(item.requirement for item in self._leases.values())
            if host is None:
                host_snapshot = self.host_sampler(
                    path,
                    active_workers=0,
                    worker_limit=min(self.policy.max_lanes, lease_budget.max_processes),
                    active_phase="proof_scheduler",
                )
            elif isinstance(host, HostResourceSnapshot):
                host_snapshot = host
            else:
                host_snapshot = HostResourceSnapshot.from_mapping(host)
            host_snapshot = self._host_excluding_accounted_requirements(
                host_snapshot,
                active,
            )
            provider_reservations: dict[str, _ProviderReservation] = {}
            provider_lease_counts: dict[str, int] = {}
            for lease in self._leases.values():
                if not lease.provider_id:
                    continue
                provider_lease_counts[lease.provider_id] = (
                    provider_lease_counts.get(lease.provider_id, 0) + 1
                )
                reservation = provider_reservations.setdefault(
                    lease.provider_id, _ProviderReservation()
                )
                reservation.requests += 1
                reservation.quota += lease.requirement.quota_units
                reservation.tokens += lease.requirement.token_budget
            adjusted_providers = tuple(
                replace(
                    provider,
                    active_requests=max(
                        0,
                        provider.active_requests
                        - provider_lease_counts.get(provider.provider_id, 0),
                    ),
                )
                for provider in normalize_provider_capacities(providers)
            )
            decision = self.evaluate(
                req,
                host=host_snapshot,
                providers=adjusted_providers,
                reservations=provider_reservations,
                active_requirements=active,
            )
            if decision.admitted:
                pool_limit = self._pool_limit(req.resource_pool)
                pool_used = sum(
                    item.process_slots
                    for item in active
                    if item.resource_pool == req.resource_pool
                )
                total_used = sum(item.process_slots for item in active)
                memory_used = sum(item.memory_bytes for item in active)
                disk_used = sum(item.disk_bytes for item in active)
                gpu_memory_used = sum(
                    item.gpu_memory_bytes for item in active
                )
                tokens_used = sum(
                    item.token_budget for item in active if item.provider_required
                )
                quota_used = sum(
                    item.quota_units for item in active if item.provider_required
                )
                extra_reasons: list[str] = []
                if total_used + req.process_slots > lease_budget.max_processes:
                    extra_reasons.append("lease_process_capacity")
                if pool_used + req.process_slots > pool_limit:
                    extra_reasons.append(
                        f"lease_{req.resource_pool.replace('-', '_')}_concurrency"
                    )
                if (
                    lease_budget.memory_bytes
                    and memory_used + req.memory_bytes > lease_budget.memory_bytes
                ):
                    extra_reasons.append("lease_memory_budget")
                if (
                    lease_budget.disk_bytes
                    and disk_used + req.disk_bytes > lease_budget.disk_bytes
                ):
                    extra_reasons.append("lease_disk_budget")
                if (
                    lease_budget.gpu_memory_bytes
                    and gpu_memory_used + req.gpu_memory_bytes
                    > lease_budget.gpu_memory_bytes
                ):
                    extra_reasons.append("lease_gpu_memory_budget")
                if (
                    lease_budget.model_token_limit
                    and tokens_used + req.token_budget
                    > lease_budget.model_token_limit
                ):
                    extra_reasons.append("lease_token_budget")
                if (
                    lease_budget.provider_quota
                    and req.provider_required
                    and quota_used + req.quota_units > lease_budget.provider_quota
                ):
                    extra_reasons.append("lease_provider_quota")
                if extra_reasons:
                    decision = replace(
                        decision,
                        admitted=False,
                        reasons=tuple(extra_reasons),
                        effective_slots=0,
                        reserved_process_slots=0,
                        reserved_quota_units=0,
                        reserved_tokens=0,
                        reserved_memory_bytes=0,
                        reserved_gpu_memory_bytes=0,
                        reserved_disk_bytes=0,
                    )
            if not decision.admitted:
                return decision, None
            lease = ResourceAdmissionLease(
                lease_id=f"resource-lease:{uuid.uuid4().hex}",
                requirement=req,
                decision=decision,
                budget=lease_budget,
                acquired_at_ms=host_snapshot.observed_at_ms or int(time.time() * 1000),
            )
            self._leases[lease.lease_id] = lease
            self._known_lanes.add(req.lane_id)
            with self._metrics_lock:
                metric = self._stage_metrics.setdefault(
                    req.stage, _MutableStageMetrics()
                )
                metric.leases_acquired += 1
                metric.active_leases += 1
            return decision, lease

    @staticmethod
    def _host_excluding_accounted_requirements(
        host: HostResourceSnapshot,
        requirements: Iterable[LaneResourceRequirements],
    ) -> HostResourceSnapshot:
        """Avoid counting leases twice when host telemetry includes workers.

        Resource byte reservations are still subtracted explicitly by
        :meth:`evaluate`; this adjustment applies only to process occupancy.
        """

        accounted = sum(item.process_slots for item in requirements)
        if not accounted or not host.active_workers:
            return host
        external_active = max(0, host.active_workers - accounted)
        reported_capacity = min(
            host.worker_limit,
            host.active_workers + host.available_worker_capacity,
        )
        return replace(
            host,
            active_workers=external_active,
            available_worker_capacity=max(
                0, reported_capacity - external_active
            ),
        )

    def release(
        self,
        lease: ResourceAdmissionLease | str,
        *,
        reason: str = "released",
    ) -> bool:
        """Release a lease and make all of its capacity immediately reusable."""

        lease_id = lease.lease_id if isinstance(lease, ResourceAdmissionLease) else str(lease)
        with self._lease_lock:
            released = self._leases.pop(lease_id, None)
        if released is None:
            return False
        with self._metrics_lock:
            metric = self._stage_metrics.setdefault(
                released.requirement.stage, _MutableStageMetrics()
            )
            metric.leases_released += 1
            metric.active_leases = max(0, metric.active_leases - 1)
            if str(reason).strip().lower().startswith("cancel"):
                metric.cancelled += 1
        return True

    def cancel(
        self,
        lease: ResourceAdmissionLease | str,
        reason: str = "cancelled",
    ) -> bool:
        """Atomically cancel a queued lane or active resource lease."""

        identity = (
            lease.lease_id
            if isinstance(lease, ResourceAdmissionLease)
            else str(lease)
        )
        normalized_reason = str(reason or "cancelled").strip() or "cancelled"
        with self._lease_lock:
            matched = self._leases.get(identity)
            matching_ids: list[str]
            if matched is not None:
                matching_ids = [identity]
            else:
                matching_ids = [
                    lease_id
                    for lease_id, item in self._leases.items()
                    if item.lane_id == identity
                ]
            if not matching_ids and identity in self._cancelled_lanes:
                return False
            known = identity in self._known_lanes or bool(matching_ids)
            if not known:
                return False
            released = [
                self._leases.pop(lease_id)
                for lease_id in matching_ids
            ]
            lane_id = (
                released[0].lane_id
                if released
                else identity
            )
            if lane_id in self._cancelled_lanes:
                return False
            self._cancelled_lanes[lane_id] = normalized_reason
        stages = (
            {item.requirement.stage for item in released}
            or {"execution"}
        )
        with self._metrics_lock:
            for stage in stages:
                metric = self._stage_metrics.setdefault(
                    stage, _MutableStageMetrics()
                )
                metric.cancelled += 1
                metric.leases_released += sum(
                    1
                    for item in released
                    if item.requirement.stage == stage
                )
                metric.active_leases = max(
                    0,
                    metric.active_leases
                    - sum(
                        1
                        for item in released
                        if item.requirement.stage == stage
                    ),
                )
        return True

    cancel_lease = cancel

    def clear_cancellation(self, lane_id: str) -> bool:
        """Allow an explicitly retried lane to participate in admission."""

        with self._lease_lock:
            return self._cancelled_lanes.pop(str(lane_id), None) is not None

    def transition(
        self,
        lease: ResourceAdmissionLease | str,
        new_requirement: LaneResourceRequirements | Mapping[str, Any],
        *,
        host: HostResourceSnapshot | Mapping[str, Any] | None = None,
        providers: Mapping[str, Any] | Iterable[ProviderCapacity | Mapping[str, Any]] | None = None,
        path: Path | str = ".",
    ) -> tuple[AdmissionDecision, ResourceAdmissionLease | None]:
        """Atomically move a lease between stage/resource reservations.

        The original lease and reservation remain authoritative when the new
        stage cannot be admitted. A successful transition retains the lease
        identity and acquisition timestamp.
        """

        lease_id = (
            lease.lease_id
            if isinstance(lease, ResourceAdmissionLease)
            else str(lease)
        )
        req = (
            new_requirement
            if isinstance(new_requirement, LaneResourceRequirements)
            else LaneResourceRequirements.from_mapping(new_requirement)
        )
        with self._lease_lock:
            current = self._leases.get(lease_id)
            if current is None:
                return (
                    AdmissionDecision(
                        lane_id=req.lane_id,
                        admitted=False,
                        stage=req.stage,
                        reasons=("lease_not_found",),
                        resource_class=req.resource_class,
                        resource_pool=req.resource_pool,
                    ),
                    None,
                )
            if req.lane_id and req.lane_id != current.lane_id:
                return (
                    AdmissionDecision(
                        lane_id=req.lane_id,
                        admitted=False,
                        stage=req.stage,
                        reasons=("lease_lane_mismatch",),
                        resource_class=req.resource_class,
                        resource_pool=req.resource_pool,
                    ),
                    None,
                )
            req = replace(req, lane_id=current.lane_id)
            others = tuple(
                item.requirement
                for other_id, item in self._leases.items()
                if other_id != lease_id
            )
            all_current = (*others, current.requirement)
            if host is None:
                host_snapshot = self.host_sampler(
                    path,
                    active_workers=len(self._leases),
                    worker_limit=min(
                        self.policy.max_lanes,
                        current.budget.max_processes,
                    ),
                    active_phase=req.stage,
                )
            elif isinstance(host, HostResourceSnapshot):
                host_snapshot = host
            else:
                host_snapshot = HostResourceSnapshot.from_mapping(host)
            host_snapshot = self._host_excluding_accounted_requirements(
                host_snapshot,
                all_current,
            )
            reservations: dict[str, _ProviderReservation] = {}
            current_provider_counts: dict[str, int] = {}
            for other_id, item in self._leases.items():
                if item.provider_id:
                    current_provider_counts[item.provider_id] = (
                        current_provider_counts.get(item.provider_id, 0) + 1
                    )
                if other_id == lease_id or not item.provider_id:
                    continue
                reservation = reservations.setdefault(
                    item.provider_id, _ProviderReservation()
                )
                reservation.requests += 1
                reservation.quota += item.requirement.quota_units
                reservation.tokens += item.requirement.token_budget
            adjusted_providers = tuple(
                replace(
                    provider,
                    active_requests=max(
                        0,
                        provider.active_requests
                        - current_provider_counts.get(provider.provider_id, 0),
                    ),
                )
                for provider in normalize_provider_capacities(providers)
            )
            decision = self.evaluate(
                req,
                host=host_snapshot,
                providers=adjusted_providers,
                reservations=reservations,
                active_requirements=others,
            )
            if decision.admitted:
                budget = current.budget
                total_processes = sum(
                    item.process_slots for item in others
                ) + req.process_slots
                memory = sum(item.memory_bytes for item in others) + req.memory_bytes
                gpu_memory = sum(
                    item.gpu_memory_bytes for item in others
                ) + req.gpu_memory_bytes
                disk = sum(item.disk_bytes for item in others) + req.disk_bytes
                budget_reasons: list[str] = []
                if total_processes > budget.max_processes:
                    budget_reasons.append("lease_process_capacity")
                if budget.memory_bytes and memory > budget.memory_bytes:
                    budget_reasons.append("lease_memory_budget")
                if (
                    budget.gpu_memory_bytes
                    and gpu_memory > budget.gpu_memory_bytes
                ):
                    budget_reasons.append("lease_gpu_memory_budget")
                if budget.disk_bytes and disk > budget.disk_bytes:
                    budget_reasons.append("lease_disk_budget")
                if budget_reasons:
                    decision = replace(
                        decision,
                        admitted=False,
                        reasons=tuple(budget_reasons),
                        effective_slots=0,
                        reserved_process_slots=0,
                        reserved_memory_bytes=0,
                        reserved_gpu_memory_bytes=0,
                        reserved_disk_bytes=0,
                    )
            if not decision.admitted:
                return decision, None
            transitioned = replace(
                current,
                requirement=req,
                decision=decision,
            )
            self._leases[lease_id] = transitioned
        with self._metrics_lock:
            old_metric = self._stage_metrics.setdefault(
                current.requirement.stage, _MutableStageMetrics()
            )
            new_metric = self._stage_metrics.setdefault(
                req.stage, _MutableStageMetrics()
            )
            old_metric.active_leases = max(
                0, old_metric.active_leases - 1
            )
            new_metric.active_leases += 1
            new_metric.lease_transitions += 1
        return decision, transitioned

    transition_lease = transition

    @property
    def active_leases(self) -> tuple[ResourceAdmissionLease, ...]:
        with self._lease_lock:
            return tuple(
                self._leases[key]
                for key in sorted(self._leases)
            )

    def release_lane(self, lane_id: str) -> int:
        """Release all local resource grants owned by ``lane_id``."""

        with self._lease_lock:
            matching = [
                lease_id
                for lease_id, lease in self._leases.items()
                if lease.lane_id == lane_id
            ]
            released = [self._leases.pop(lease_id) for lease_id in matching]
        with self._metrics_lock:
            for item in released:
                metric = self._stage_metrics.setdefault(
                    item.requirement.stage, _MutableStageMetrics()
                )
                metric.leases_released += 1
                metric.active_leases = max(0, metric.active_leases - 1)
        return len(matching)

    def schedule(
        self,
        lanes: Iterable[LaneResourceRequirements | Mapping[str, Any]],
        *,
        host: HostResourceSnapshot | Mapping[str, Any] | None = None,
        providers: Mapping[str, Any] | Iterable[ProviderCapacity | Mapping[str, Any]] | None = None,
        path: Path | str = ".",
        active_workers: int = 0,
        active_requirements: Iterable[
            LaneResourceRequirements | Mapping[str, Any]
        ] = (),
        signals: Mapping[str, Any] | None = None,
        record_metrics: bool = True,
    ) -> ResourceScheduleSnapshot:
        """Admit a unique candidate batch against all active reservations.

        Active local leases are included automatically. ``active_requirements``
        represents externally leased work which shares this scheduler's host.
        Host/provider telemetry that already counts those leases is normalized
        before explicit reservations are applied, preventing double counting.
        """

        requirements = tuple(
            item if isinstance(item, LaneResourceRequirements) else LaneResourceRequirements.from_mapping(item)
            for item in lanes
        )
        lane_ids = [item.lane_id for item in requirements]
        if any(not item for item in lane_ids):
            raise ValueError("scheduled lanes must have non-empty lane_id values")
        duplicates = sorted(
            {
                lane_id
                for lane_id in lane_ids
                if lane_ids.count(lane_id) > 1
            }
        )
        if duplicates:
            raise ValueError(
                "duplicate lane_id values are not schedulable: "
                + ", ".join(duplicates)
            )
        with self._lease_lock:
            leases = tuple(self._leases[key] for key in sorted(self._leases))
            lease_requirements = tuple(item.requirement for item in leases)
            self._known_lanes.update(lane_ids)
        external_requirements = tuple(
            item
            if isinstance(item, LaneResourceRequirements)
            else LaneResourceRequirements.from_mapping(item)
            for item in active_requirements
        )
        # A supervisor may expose the same active work both through its local
        # lease and its durable lane projection. Count each lane exactly once.
        active_by_id: dict[str, LaneResourceRequirements] = {
            item.lane_id: item for item in external_requirements
        }
        for item in lease_requirements:
            active_by_id[item.lane_id] = item
        baseline_active = tuple(
            active_by_id[key] for key in sorted(active_by_id)
        )
        requirements = self._fair_requirements(requirements)
        if host is None:
            host_snapshot = self.host_sampler(
                path,
                active_workers=active_workers,
                worker_limit=self.policy.max_lanes,
                active_phase="scheduler",
            )
        elif isinstance(host, HostResourceSnapshot):
            host_snapshot = host
        else:
            host_snapshot = HostResourceSnapshot.from_mapping(host)
        host_snapshot = self._host_excluding_accounted_requirements(
            host_snapshot,
            baseline_active,
        )
        normalized_raw = normalize_provider_capacities(providers)
        lease_provider_counts: dict[str, int] = {}
        for lease in leases:
            if lease.provider_id:
                lease_provider_counts[lease.provider_id] = (
                    lease_provider_counts.get(lease.provider_id, 0) + 1
                )
        normalized = tuple(
            replace(
                provider,
                active_requests=max(
                    0,
                    provider.active_requests
                    - lease_provider_counts.get(provider.provider_id, 0),
                ),
            )
            for provider in normalized_raw
        )
        reservations: dict[str, _ProviderReservation] = {
            item.provider_id: _ProviderReservation() for item in normalized
        }
        for item in baseline_active:
            if not item.provider_required:
                continue
            provider_id = item.provider_id
            if not provider_id:
                matching = [
                    provider.provider_id
                    for provider in normalized
                    if provider.healthy
                ]
                provider_id = matching[0] if len(matching) == 1 else ""
            if provider_id:
                reservation = reservations.setdefault(
                    provider_id, _ProviderReservation()
                )
                reservation.requests += 1
                reservation.quota += item.quota_units
                reservation.tokens += item.token_budget
        decisions: list[AdmissionDecision] = []
        admitted = 0
        admitted_requirements: list[LaneResourceRequirements] = list(
            baseline_active
        )
        signal_map = dict(signals or {})
        queue_counts: dict[str, int] = {}
        for item in requirements:
            queue_counts[item.stage] = queue_counts.get(item.stage, 0) + 1

        def stage_signal(
            names: Sequence[str],
            stage: str,
            default: int,
        ) -> int:
            for name in names:
                value = signal_map.get(name)
                if isinstance(value, Mapping):
                    if stage in value:
                        return _integer(value.get(stage), default, minimum=0)
                elif value is not None:
                    return _integer(value, default, minimum=0)
            return default

        for admission_rank, requirement in enumerate(requirements, start=1):
            decision = self.evaluate(
                requirement,
                host=host_snapshot,
                providers=normalized,
                reservations=reservations,
                active_requirements=admitted_requirements,
                queue_depth=stage_signal(
                    ("queue_depth_by_stage", "queue_depth"),
                    requirement.stage,
                    queue_counts.get(requirement.stage, 1),
                ),
                merge_age_ms=max(
                    requirement.merge_age_ms,
                    stage_signal(
                        ("merge_age_ms_by_stage", "merge_age_ms"),
                        requirement.stage,
                        0,
                    ),
                ),
                artifact_pressure_percent=stage_signal(
                    (
                        "artifact_pressure_percent_by_stage",
                        "artifact_pressure_percent",
                        "artifact_pressure",
                    ),
                    requirement.stage,
                    0,
                ),
                merge_debt=stage_signal(
                    ("merge_debt_by_stage", "merge_debt"),
                    requirement.stage,
                    0,
                ),
            )
            decision = replace(decision, admission_rank=admission_rank)
            decisions.append(decision)
            if not decision.admitted:
                continue
            admitted += 1
            admitted_requirements.append(requirement)
            if decision.provider_id:
                reservation = reservations.setdefault(decision.provider_id, _ProviderReservation())
                reservation.requests += 1
                reservation.quota += requirement.quota_units
                reservation.tokens += requirement.token_budget
        if record_metrics:
            with self._metrics_lock:
                for decision in decisions:
                    metric = self._stage_metrics.setdefault(
                        decision.stage, _MutableStageMetrics()
                    )
                    metric.scheduled += 1
                    if decision.admitted:
                        metric.admitted += 1
                    else:
                        metric.backpressured += 1
                        for reason in decision.reasons:
                            metric.backpressure_reasons[reason] = (
                                metric.backpressure_reasons.get(reason, 0) + 1
                            )

        configured = self.policy.max_lanes
        total_host_capacity = min(
            configured,
            host_snapshot.worker_limit,
            host_snapshot.active_workers + host_snapshot.available_worker_capacity,
        )
        baseline_processes = sum(
            item.process_slots for item in baseline_active
        )
        host_blocked = any(
            reason
            in {
                "host_cpu_high_watermark",
                "host_memory_high_watermark",
                "host_memory_headroom",
            }
            for reason in self._host_reasons(
                host_snapshot,
                LaneResourceRequirements(stage="analysis"),
            )
        )
        host_free = max(
            0,
            total_host_capacity
            - host_snapshot.active_workers
            - baseline_processes,
        )
        effective = 0 if host_blocked else host_free
        # If every candidate needs an LLM, provider capacity is a pool-wide
        # upper bound. Mixed work can fill host slots without a provider.
        if requirements and all(item.provider_required for item in requirements):
            provider_free = 0
            for provider in normalized:
                reservation = reservations.get(
                    provider.provider_id, _ProviderReservation()
                )
                if (
                    provider.healthy
                    and provider.retry_after_ms == 0
                    and provider.latency_ms <= self.policy.maximum_provider_latency_ms
                    and provider.quota_remaining != 0
                    and provider.token_budget_remaining != 0
                ):
                    # ``reservations`` includes newly admitted candidates.
                    # Add those back when reporting the pre-admission bound.
                    provider_free += max(
                        0,
                        provider.available_concurrency
                        - reservation.requests,
                    )
            effective = min(effective, provider_free + admitted)
        available = max(0, effective - admitted)
        backpressure = tuple(
            dict.fromkeys(
                reason
                for decision in decisions
                if not decision.admitted
                for reason in decision.reasons
            )
        )
        backpressure_counts = {
            reason: sum(
                1
                for decision in decisions
                if not decision.admitted and reason in decision.reasons
            )
            for reason in backpressure
        }
        pool_admissions: list[ResourcePoolAdmissionSnapshot] = []
        for pool_name in sorted({item.resource_pool for item in requirements}):
            pool_items = [
                (requirement, decision)
                for requirement, decision in zip(requirements, decisions)
                if requirement.resource_pool == pool_name
            ]
            pool_backpressure: dict[str, int] = {}
            for _requirement, decision in pool_items:
                if decision.admitted:
                    continue
                for reason in decision.reasons:
                    pool_backpressure[reason] = (
                        pool_backpressure.get(reason, 0) + 1
                    )
            admitted_pool_lane_ids = tuple(
                decision.lane_id
                for _requirement, decision in pool_items
                if decision.admitted
            )
            pool_admissions.append(
                ResourcePoolAdmissionSnapshot(
                    resource_pool=pool_name,
                    scheduled_count=len(pool_items),
                    admitted_count=len(admitted_pool_lane_ids),
                    backpressured_count=(
                        len(pool_items) - len(admitted_pool_lane_ids)
                    ),
                    fairness_order=tuple(
                        decision.lane_id
                        for _requirement, decision in pool_items
                    ),
                    fairness_keys=tuple(
                        requirement.fairness_key
                        for requirement, _decision in pool_items
                    ),
                    admitted_lane_ids=admitted_pool_lane_ids,
                    backpressure_counts=pool_backpressure,
                )
            )
        active_by_stage: dict[str, int] = {}
        active_lease_by_stage: dict[str, int] = {}
        for item in baseline_active:
            active_by_stage[item.stage] = (
                active_by_stage.get(item.stage, 0) + item.process_slots
            )
        for lease in leases:
            stage = lease.requirement.stage
            active_lease_by_stage[stage] = (
                active_lease_by_stage.get(stage, 0) + 1
            )
        for requirement, decision in zip(requirements, decisions):
            if decision.admitted:
                active_by_stage[requirement.stage] = (
                    active_by_stage.get(requirement.stage, 0)
                    + requirement.process_slots
                )
        stages = sorted(
            set(queue_counts)
            | {item.stage for item in baseline_active}
        )
        capacity_members = (*baseline_active, *requirements)
        stage_capacities = tuple(
            self.adaptive_stage_capacity(
                stage,
                host=host_snapshot,
                active=active_by_stage.get(stage, 0),
                queued=stage_signal(
                    ("queue_depth_by_stage", "queue_depth"),
                    stage,
                    queue_counts.get(stage, 0),
                ),
                merge_age_ms=max(
                    (
                        item.merge_age_ms
                        for item in requirements
                        if item.stage == stage
                    ),
                    default=stage_signal(
                        ("merge_age_ms_by_stage", "merge_age_ms"),
                        stage,
                        0,
                    ),
                ),
                provider_available_slots=(
                    sum(
                        item.available_concurrency
                        for item in normalized
                        if item.healthy and item.retry_after_ms == 0
                    )
                    if (
                        stage == "inference"
                        and any(
                            item.stage == stage
                            for item in capacity_members
                        )
                        and all(
                            item.provider_required
                            for item in capacity_members
                            if item.stage == stage
                        )
                    )
                    else UNKNOWN_LIMIT
                ),
                artifact_pressure_percent=stage_signal(
                    (
                        "artifact_pressure_percent_by_stage",
                        "artifact_pressure_percent",
                        "artifact_pressure",
                    ),
                    stage,
                    0,
                ),
                merge_debt=stage_signal(
                    ("merge_debt_by_stage", "merge_debt"),
                    stage,
                    0,
                ),
                active_leases=active_lease_by_stage.get(stage, 0),
            )
            for stage in stages
        )
        if len(stage_capacities) == 1:
            baseline_stage_active = sum(
                item.process_slots for item in baseline_active
            )
            effective = min(
                effective,
                max(
                    0,
                    stage_capacities[0].effective_limit
                    - baseline_stage_active,
                ),
            )
            available = max(0, effective - admitted)
        metrics = self.metrics_snapshot(
            observed_at_ms=host_snapshot.observed_at_ms or int(time.time() * 1000)
        )
        signal_payload = {
            "queue_depth_by_stage": {
                stage: stage_signal(
                    ("queue_depth_by_stage", "queue_depth"),
                    stage,
                    queue_counts.get(stage, 0),
                )
                for stage in stages
            },
            "merge_age_ms_by_stage": {
                stage: max(
                    (
                        item.merge_age_ms
                        for item in requirements
                        if item.stage == stage
                    ),
                    default=stage_signal(
                        ("merge_age_ms_by_stage", "merge_age_ms"),
                        stage,
                        0,
                    ),
                )
                for stage in stages
            },
            "active_process_slots": baseline_processes,
            "active_lease_count": len(leases),
            "artifact_pressure_percent": stage_signal(
                ("artifact_pressure_percent", "artifact_pressure"),
                "persistence",
                0,
            ),
            "merge_debt": stage_signal(
                ("merge_debt",),
                "merge",
                0,
            ),
        }
        pending_tasks = stage_signal(
            (
                "pending_tasks",
                "pending_task_count",
                "task_generation_queue_depth",
            ),
            "analysis",
            sum(queue_counts.values()),
        )
        generation = self.task_generation_backpressure(
            host=host_snapshot,
            pending_tasks=pending_tasks,
            artifact_pressure_percent=signal_payload[
                "artifact_pressure_percent"
            ],
            merge_debt=signal_payload["merge_debt"],
            observed_at_ms=(
                host_snapshot.observed_at_ms or int(time.time() * 1000)
            ),
        )
        signal_payload["pending_tasks"] = pending_tasks
        signal_payload["task_generation_admitted"] = generation.admitted
        return ResourceScheduleSnapshot(
            observed_at_ms=host_snapshot.observed_at_ms or int(time.time() * 1000),
            host=host_snapshot,
            providers=normalized_raw,
            policy=self.policy,
            decisions=tuple(decisions),
            configured_max_lanes=configured,
            effective_slots=effective,
            available_slots=available,
            admitted_count=admitted,
            backpressure_reasons=backpressure,
            stage_capacities=stage_capacities,
            adaptive_metrics=metrics,
            active_lease_count=len(leases),
            backpressure_counts=backpressure_counts,
            signals=signal_payload,
            pool_admissions=tuple(pool_admissions),
            task_generation=generation,
        )

    # Descriptive aliases used by scheduler integrations and callers.
    evaluate_lane = evaluate
    schedule_lanes = schedule


@dataclass(frozen=True)
class AdaptiveThroughputRun:
    """Measured execution of the same independent fixture set."""

    fixture_ids: tuple[str, ...]
    executed_fixture_ids: tuple[str, ...]
    accepted_fixture_ids: tuple[str, ...]
    duration_ms: int
    peak_concurrency: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_ids", tuple(str(item) for item in self.fixture_ids)
        )
        object.__setattr__(
            self,
            "executed_fixture_ids",
            tuple(str(item) for item in self.executed_fixture_ids),
        )
        object.__setattr__(
            self,
            "accepted_fixture_ids",
            tuple(str(item) for item in self.accepted_fixture_ids),
        )
        if self.duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        if self.peak_concurrency <= 0:
            raise ValueError("peak_concurrency must be positive")

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_fixture_ids)

    @property
    def throughput_per_million_ms(self) -> int:
        return self.accepted_count * 1_000_000 // self.duration_ms

    @property
    def duplicate_execution_count(self) -> int:
        return max(
            0,
            len(self.executed_fixture_ids)
            - len(set(self.executed_fixture_ids)),
        )

    @property
    def duplicate_compute_percent_millionths(self) -> int:
        if not self.executed_fixture_ids:
            return 0
        return (
            self.duplicate_execution_count
            * 100_000_000
            // len(self.executed_fixture_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_ids": list(self.fixture_ids),
            "executed_fixture_ids": list(self.executed_fixture_ids),
            "accepted_fixture_ids": list(self.accepted_fixture_ids),
            "duration_ms": self.duration_ms,
            "peak_concurrency": self.peak_concurrency,
            "accepted_count": self.accepted_count,
            "throughput_per_million_ms": self.throughput_per_million_ms,
            "duplicate_execution_count": self.duplicate_execution_count,
            "duplicate_compute_percent_millionths": (
                self.duplicate_compute_percent_millionths
            ),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AdaptiveThroughputRun":
        return cls(
            fixture_ids=tuple(str(item) for item in value.get("fixture_ids", ())),
            executed_fixture_ids=tuple(
                str(item) for item in value.get("executed_fixture_ids", ())
            ),
            accepted_fixture_ids=tuple(
                str(item) for item in value.get("accepted_fixture_ids", ())
            ),
            duration_ms=_integer(value.get("duration_ms"), 0, minimum=0),
            peak_concurrency=_integer(
                value.get("peak_concurrency"), 0, minimum=0
            ),
        )


def _adaptive_benchmark_failure_codes(
    baseline: AdaptiveThroughputRun,
    adaptive: AdaptiveThroughputRun,
    *,
    policy: ResourcePolicy,
    repository_tree_id: str,
) -> tuple[str, ...]:
    failures: list[str] = []
    expected = baseline.fixture_ids
    expected_set = set(expected)
    if not repository_tree_id.strip():
        failures.append("repository_tree_unbound")
    if not policy.adaptive_enabled:
        failures.append("adaptive_policy_disabled")
    throughput_multiplier = policy.adaptive_minimum_throughput_multiplier
    if policy.max_lanes < throughput_multiplier:
        failures.append("insufficient_parallel_capacity")
    if len(expected) < 2 or len(expected_set) != len(expected):
        failures.append("invalid_fixture_identity")
    if adaptive.fixture_ids != expected:
        failures.append("fixture_set_mismatch")
    for name, run in (("baseline", baseline), ("adaptive", adaptive)):
        executed = run.executed_fixture_ids
        duplicate_count = run.duplicate_execution_count
        duplicate_limit = policy.adaptive_max_duplicate_compute_percent
        if (
            duplicate_count
            and (
                duplicate_limit == 0
                or duplicate_count * 100
                >= duplicate_limit * len(executed)
            )
        ):
            failures.append(f"{name}_duplicate_execution")
        if set(executed) != expected_set:
            failures.append(f"{name}_execution_incomplete")
        if (
            set(run.accepted_fixture_ids) != expected_set
            or len(run.accepted_fixture_ids) != len(expected)
        ):
            failures.append(f"{name}_acceptance_incomplete")
    if baseline.peak_concurrency != 1:
        failures.append("baseline_not_single_lane")
    if adaptive.peak_concurrency < min(
        throughput_multiplier, policy.max_lanes
    ):
        failures.append("adaptive_parallelism_unobserved")
    if adaptive.peak_concurrency > policy.max_lanes:
        failures.append("adaptive_resource_overcommit")
    # Cross multiplication avoids float precision and serialization.
    if (
        adaptive.accepted_count * baseline.duration_ms
        < throughput_multiplier
        * baseline.accepted_count
        * adaptive.duration_ms
    ):
        failures.append(
            "throughput_below_three_x"
            if throughput_multiplier == 3
            else "throughput_below_required_multiplier"
        )
    return tuple(dict.fromkeys(failures))


@dataclass(frozen=True)
class AdaptiveThroughputBenchmarkReceipt:
    """Fail-closed objective evidence for adaptive acceptance throughput."""

    repository_tree_id: str
    policy_digest: str
    baseline: AdaptiveThroughputRun
    adaptive: AdaptiveThroughputRun
    passed: bool
    failure_codes: tuple[str, ...]
    content_id: str
    schema: str = ADAPTIVE_THROUGHPUT_BENCHMARK_SCHEMA
    requirement_id: str = ADAPTIVE_SCHEDULING_THROUGHPUT_REQUIREMENT_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_tree_id", str(self.repository_tree_id).strip()
        )
        object.__setattr__(
            self, "failure_codes", tuple(str(item) for item in self.failure_codes)
        )

    def _content_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "requirement_id": self.requirement_id,
            "repository_tree_id": self.repository_tree_id,
            "policy_digest": self.policy_digest,
            "baseline": self.baseline.to_dict(),
            "adaptive": self.adaptive.to_dict(),
            "passed": self.passed,
            "failure_codes": list(self.failure_codes),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_payload(), "content_id": self.content_id}

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "AdaptiveThroughputBenchmarkReceipt":
        return cls(
            schema=str(value.get("schema", "")),
            requirement_id=str(value.get("requirement_id", "")),
            repository_tree_id=str(value.get("repository_tree_id", "")),
            policy_digest=str(value.get("policy_digest", "")),
            baseline=AdaptiveThroughputRun.from_mapping(
                _mapping(value.get("baseline"))
            ),
            adaptive=AdaptiveThroughputRun.from_mapping(
                _mapping(value.get("adaptive"))
            ),
            passed=_boolean(value.get("passed"), False),
            failure_codes=tuple(
                str(item) for item in value.get("failure_codes", ())
            ),
            content_id=str(value.get("content_id", "")),
        )

    def proved_requirement_ids_for(
        self,
        *,
        policy: ResourcePolicy | Mapping[str, Any],
        repository_tree_id: str,
    ) -> tuple[str, ...]:
        """Rebind and revalidate this receipt before exposing evidence."""

        current_policy = (
            policy
            if isinstance(policy, ResourcePolicy)
            else ResourcePolicy.from_mapping(policy)
        )
        current_failures = _adaptive_benchmark_failure_codes(
            self.baseline,
            self.adaptive,
            policy=current_policy,
            repository_tree_id=repository_tree_id,
        )
        valid = (
            self.schema == ADAPTIVE_THROUGHPUT_BENCHMARK_SCHEMA
            and self.requirement_id
            == ADAPTIVE_SCHEDULING_THROUGHPUT_REQUIREMENT_ID
            and self.repository_tree_id == str(repository_tree_id).strip()
            and self.policy_digest == _canonical_digest(current_policy.to_dict())
            and self.passed
            and not self.failure_codes
            and not current_failures
            and self.content_id == _canonical_digest(self._content_payload())
        )
        return (self.requirement_id,) if valid else ()


def _mirror_adaptive_throughput(
    receipt: AdaptiveThroughputBenchmarkReceipt,
) -> AdaptiveThroughputBenchmarkReceipt:
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(receipt.content_id or receipt.repository_tree_id or "adaptive-throughput-benchmark")
        tree_id = str(receipt.repository_tree_id or "")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="adaptive_throughput_benchmark",
            record_ref=record_ref,
            tree_id=tree_id,
            subject_kind="tree_id" if tree_id else "record_cid",
            subject_ref=tree_id or record_ref,
        )
    except Exception:
        pass
    return receipt


def evaluate_adaptive_throughput_benchmark(
    baseline: AdaptiveThroughputRun,
    adaptive: AdaptiveThroughputRun,
    *,
    policy: ResourcePolicy | Mapping[str, Any],
    repository_tree_id: str,
) -> AdaptiveThroughputBenchmarkReceipt:
    """Create a content-addressed receipt from paired benchmark measurements."""

    normalized_policy = (
        policy
        if isinstance(policy, ResourcePolicy)
        else ResourcePolicy.from_mapping(policy)
    )
    failures = _adaptive_benchmark_failure_codes(
        baseline,
        adaptive,
        policy=normalized_policy,
        repository_tree_id=repository_tree_id,
    )
    values = {
        "repository_tree_id": str(repository_tree_id).strip(),
        "policy_digest": _canonical_digest(normalized_policy.to_dict()),
        "baseline": baseline,
        "adaptive": adaptive,
        "passed": not failures,
        "failure_codes": failures,
    }
    provisional = AdaptiveThroughputBenchmarkReceipt(content_id="", **values)
    return _mirror_adaptive_throughput(
        replace(
            provisional,
            content_id=_canonical_digest(provisional._content_payload()),
        )
    )


def benchmark_adaptive_execution(
    fixtures: (
        Mapping[str, Callable[[], bool]]
        | Iterable[tuple[str, Callable[[], bool]]]
    ),
    *,
    policy: ResourcePolicy | Mapping[str, Any],
    repository_tree_id: str,
) -> AdaptiveThroughputBenchmarkReceipt:
    """Run paired single-lane/adaptive fixtures and issue objective evidence.

    Fixture functions must be independent and safe to invoke once in each
    paired run. Exceptions are measured as rejected fixtures; they do not
    cancel siblings.
    """

    normalized_policy = (
        policy
        if isinstance(policy, ResourcePolicy)
        else ResourcePolicy.from_mapping(policy)
    )
    items = (
        tuple((str(name), callback) for name, callback in fixtures.items())
        if isinstance(fixtures, Mapping)
        else tuple((str(name), callback) for name, callback in fixtures)
    )
    fixture_ids = tuple(name for name, _callback in items)
    if not items:
        raise ValueError("at least one benchmark fixture is required")

    def run(max_workers: int) -> AdaptiveThroughputRun:
        active = 0
        peak = 0
        lock = threading.Lock()

        def invoke(
            fixture_id: str, callback: Callable[[], bool]
        ) -> tuple[str, bool]:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                return fixture_id, bool(callback())
            except Exception:
                return fixture_id, False
            finally:
                with lock:
                    active -= 1

        started_ns = time.monotonic_ns()
        executed: list[str] = []
        accepted: list[str] = []
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="adaptive-resource-benchmark",
        ) as executor:
            futures = [
                executor.submit(invoke, fixture_id, callback)
                for fixture_id, callback in items
            ]
            for future in as_completed(futures):
                fixture_id, was_accepted = future.result()
                executed.append(fixture_id)
                if was_accepted:
                    accepted.append(fixture_id)
        elapsed_ns = max(1, time.monotonic_ns() - started_ns)
        return AdaptiveThroughputRun(
            fixture_ids=fixture_ids,
            executed_fixture_ids=tuple(executed),
            accepted_fixture_ids=tuple(accepted),
            duration_ms=max(1, (elapsed_ns + 999_999) // 1_000_000),
            peak_concurrency=max(1, peak),
        )

    baseline = run(1)
    adaptive = run(max(1, normalized_policy.max_lanes))
    return evaluate_adaptive_throughput_benchmark(
        baseline,
        adaptive,
        policy=normalized_policy,
        repository_tree_id=repository_tree_id,
    )


class ProofWorkStatus(str, Enum):
    """Observable terminal states of one goal-runtime work request."""

    SUCCEEDED = "succeeded"
    FALLBACK = "fallback"
    CANCELLED = "cancelled"
    BACKPRESSURED = "backpressured"
    FAILED = "failed"


class ProofWorkCancellationToken:
    """Thread-safe cooperative cancellation with a stable first reason."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""
        self._cancelled_at_ms = 0

    def cancel(self, reason: str = "cancelled") -> bool:
        """Request cancellation; the first request wins and is retained."""

        normalized = str(reason or "cancelled").strip() or "cancelled"
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized
            self._cancelled_at_ms = int(time.time() * 1000)
            self._event.set()
            return True

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def cancelled_at_ms(self) -> int:
        with self._lock:
            return self._cancelled_at_ms

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until cancellation, matching :class:`threading.Event`."""

        return self._event.wait(timeout)

    def is_cancelled(self) -> bool:
        """Common token spelling used by verifier and subprocess adapters."""

        return self.cancelled


@dataclass(frozen=True)
class ProofWorkRequest:
    """A bounded unit of model, type-check, solver, or kernel work."""

    work_id: str
    work_kind: ProofWorkKind
    provider_id: str = ""
    required_capabilities: tuple[str, ...] = ()
    context_tokens: int = 0
    token_budget: int = 0
    quota_units: int = 1
    memory_bytes: int = 0
    disk_bytes: int = 0
    max_provider_latency_ms: int = 0
    process_slots: int = 1
    max_queue_wait_ms: int = 0

    def __post_init__(self) -> None:
        work_id = str(self.work_id or "").strip()
        if not work_id:
            raise ValueError("work_id must be non-empty")
        if "\x00" in work_id:
            raise ValueError("work_id must not contain NUL bytes")
        object.__setattr__(self, "work_id", work_id)
        object.__setattr__(
            self, "work_kind", normalize_proof_work_kind(self.work_kind)
        )
        object.__setattr__(
            self, "provider_id", str(self.provider_id or "").strip().lower()
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _strings(self.required_capabilities),
        )
        for name in (
            "context_tokens",
            "token_budget",
            "quota_units",
            "memory_bytes",
            "disk_bytes",
            "max_provider_latency_ms",
            "max_queue_wait_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            isinstance(self.process_slots, bool)
            or not isinstance(self.process_slots, int)
            or self.process_slots <= 0
        ):
            raise ValueError("process_slots must be a positive integer")

    @property
    def resource_class(self) -> str:
        return resource_class_for_work_kind(self.work_kind)

    @property
    def requires_provider(self) -> bool:
        return self.work_kind is ProofWorkKind.MODEL_DRAFT

    def to_requirement(self) -> LaneResourceRequirements:
        capabilities = self.required_capabilities
        if self.requires_provider:
            capabilities = tuple(
                f"llm:{item.removeprefix('llm:')}"
                if not item.startswith("host:")
                else item
                for item in capabilities
            )
        return LaneResourceRequirements(
            lane_id=self.work_id,
            stage={
                ProofWorkKind.MODEL_DRAFT: "inference",
                ProofWorkKind.TYPE_CHECK: "validation",
                ProofWorkKind.SOLVER_PORTFOLIO: "proof",
                ProofWorkKind.KERNEL_RECONSTRUCTION: "proof",
            }[self.work_kind],
            resource_class=self.resource_class,
            required_capabilities=capabilities,
            provider_id=self.provider_id,
            requires_provider=self.requires_provider,
            context_tokens=self.context_tokens,
            token_budget=self.token_budget,
            quota_units=self.quota_units,
            memory_bytes=self.memory_bytes,
            disk_bytes=self.disk_bytes,
            max_provider_latency_ms=self.max_provider_latency_ms,
            process_slots=self.process_slots,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "work_kind": self.work_kind.value,
            "resource_class": self.resource_class,
            "provider_id": self.provider_id,
            "required_capabilities": list(self.required_capabilities),
            "context_tokens": self.context_tokens,
            "token_budget": self.token_budget,
            "quota_units": self.quota_units,
            "memory_bytes": self.memory_bytes,
            "disk_bytes": self.disk_bytes,
            "max_provider_latency_ms": self.max_provider_latency_ms,
            "process_slots": self.process_slots,
            "max_queue_wait_ms": self.max_queue_wait_ms,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProofWorkRequest":
        return cls(
            work_id=str(
                _first(value, ("work_id", "task_id", "lane_id", "request_id"), "")
                or ""
            ),
            work_kind=normalize_proof_work_kind(
                _first(value, ("work_kind", "kind", "stage"), "")
            ),
            provider_id=str(
                _first(value, ("provider_id", "route_id", "provider"), "") or ""
            ),
            required_capabilities=_strings(
                _first(value, ("required_capabilities", "capabilities"), ())
            ),
            context_tokens=_integer(
                _first(value, ("context_tokens", "required_context_tokens"), 0),
                0,
                minimum=0,
            ),
            token_budget=_integer(
                _first(value, ("token_budget", "max_new_tokens"), 0),
                0,
                minimum=0,
            ),
            quota_units=_integer(value.get("quota_units"), 1, minimum=0),
            memory_bytes=_integer(value.get("memory_bytes"), 0, minimum=0),
            disk_bytes=_integer(value.get("disk_bytes"), 0, minimum=0),
            max_provider_latency_ms=_integer(
                _first(
                    value,
                    ("max_provider_latency_ms", "maximum_provider_latency_ms"),
                    0,
                ),
                0,
                minimum=0,
            ),
            process_slots=_integer(
                _first(value, ("process_slots", "portfolio_width"), 1),
                1,
                minimum=1,
            ),
            max_queue_wait_ms=_integer(
                _first(value, ("max_queue_wait_ms", "queue_timeout_ms"), 0),
                0,
                minimum=0,
            ),
        )


@dataclass(frozen=True)
class ProofWorkContext:
    """Execution context shared with primary and deterministic fallback work."""

    request: ProofWorkRequest
    cancellation_token: ProofWorkCancellationToken
    admission: AdmissionDecision | None = None
    lease: ResourceAdmissionLease | None = None
    fallback_reason: str = ""
    reason_codes: tuple[str, ...] = ()

    @property
    def child_limits(self) -> ChildResourceLimits | None:
        return self.lease.child_limits if self.lease is not None else None


@dataclass(frozen=True)
class ProofWorkResult:
    """Structured outcome that never confuses fallback with primary success."""

    request: ProofWorkRequest
    status: ProofWorkStatus
    queued_at_ms: int
    started_at_ms: int
    completed_at_ms: int
    value: Any = None
    admission: AdmissionDecision | None = None
    used_fallback: bool = False
    fallback_reason: str = ""
    reason_codes: tuple[str, ...] = ()
    error: str = ""

    @property
    def successful(self) -> bool:
        """Whether the request returned a usable primary or fallback value.

        This property retains the scheduler's compatibility semantics.  It is
        not a proof-completion signal; trust-sensitive callers must use
        :attr:`primary_succeeded`.
        """

        return self.status in (ProofWorkStatus.SUCCEEDED, ProofWorkStatus.FALLBACK)

    @property
    def primary_succeeded(self) -> bool:
        """Whether the resource-leased primary operation itself succeeded."""

        return self.status is ProofWorkStatus.SUCCEEDED

    @property
    def fallback_succeeded(self) -> bool:
        """Whether a bounded deterministic fallback produced the value."""

        return self.status is ProofWorkStatus.FALLBACK and self.used_fallback

    @property
    def queue_latency_ms(self) -> int:
        boundary = self.started_at_ms or self.completed_at_ms
        return max(0, boundary - self.queued_at_ms)

    @property
    def execution_latency_ms(self) -> int:
        if not self.started_at_ms:
            return 0
        return max(0, self.completed_at_ms - self.started_at_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "status": self.status.value,
            "successful": self.successful,
            "primary_succeeded": self.primary_succeeded,
            "fallback_succeeded": self.fallback_succeeded,
            "queued_at_ms": self.queued_at_ms,
            "started_at_ms": self.started_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "queue_latency_ms": self.queue_latency_ms,
            "execution_latency_ms": self.execution_latency_ms,
            "value": self.value,
            "admission": self.admission.to_dict() if self.admission else None,
            "used_fallback": self.used_fallback,
            "fallback_reason": self.fallback_reason,
            "reason_codes": list(self.reason_codes),
            "error": self.error,
        }


ProofWorkCallable = Callable[[ProofWorkContext], Any]


class GoalRuntimeResourceScheduler:
    """Bounded execution facade for route-aware goal-development proof work.

    Execution is synchronous in the caller's thread, making ownership and
    shutdown explicit.  Multiple callers may enter concurrently.  Waiting
    requests are FIFO within each resource class, while different classes can
    progress independently.  The underlying :class:`ResourceScheduler`
    atomically accounts all running work.
    """

    def __init__(
        self,
        resource_scheduler: ResourceScheduler | None = None,
        *,
        policy: ResourcePolicy | Mapping[str, Any] | None = None,
        budget: ResourceLeaseBudget | None = None,
        max_queued_tasks: int = 64,
        max_fallback_concurrency: int = 1,
        queue_retry_ms: int = 25,
        host_resource_source: (
            HostResourceSnapshot
            | Mapping[str, Any]
            | Callable[[], HostResourceSnapshot | Mapping[str, Any]]
            | None
        ) = None,
        provider_capacity_source: (
            Mapping[str, Any]
            | Iterable[ProviderCapacity | Mapping[str, Any]]
            | Callable[
                [],
                Mapping[str, Any]
                | Iterable[ProviderCapacity | Mapping[str, Any]]
                | None,
            ]
            | None
        ) = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if resource_scheduler is not None and policy is not None:
            raise ValueError("pass resource_scheduler or policy, not both")
        if (
            isinstance(max_queued_tasks, bool)
            or not isinstance(max_queued_tasks, int)
            or max_queued_tasks <= 0
        ):
            raise ValueError("max_queued_tasks must be a positive integer")
        if (
            isinstance(queue_retry_ms, bool)
            or not isinstance(queue_retry_ms, int)
            or queue_retry_ms <= 0
        ):
            raise ValueError("queue_retry_ms must be a positive integer")
        if (
            isinstance(max_fallback_concurrency, bool)
            or not isinstance(max_fallback_concurrency, int)
            or max_fallback_concurrency <= 0
        ):
            raise ValueError(
                "max_fallback_concurrency must be a positive integer"
            )
        self.resource_scheduler = resource_scheduler or ResourceScheduler(policy)
        self.budget = budget
        self.max_queued_tasks = max_queued_tasks
        self.max_fallback_concurrency = max_fallback_concurrency
        self.queue_retry_ms = queue_retry_ms
        self.host_resource_source = host_resource_source
        self.provider_capacity_source = provider_capacity_source
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._state_lock = threading.RLock()
        self._queues: dict[str, deque[str]] = {}
        self._tokens: dict[str, ProofWorkCancellationToken] = {}
        self._running: set[str] = set()
        self._fallback_running: set[str] = set()

    @staticmethod
    def _sample(source: Any) -> Any:
        return source() if callable(source) else source

    @property
    def queued_count(self) -> int:
        with self._state_lock:
            return sum(len(queue) for queue in self._queues.values())

    @property
    def running_count(self) -> int:
        with self._state_lock:
            return len(self._running)

    @property
    def fallback_running_count(self) -> int:
        with self._state_lock:
            return len(self._fallback_running)

    @property
    def queued_work_ids(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(
                work_id
                for resource_class in sorted(self._queues)
                for work_id in self._queues[resource_class]
            )

    @property
    def running_work_ids(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(sorted(self._running))

    def cancel(self, work_id: str, reason: str = "operator_cancelled") -> bool:
        """Cooperatively cancel queued or running work by stable identity."""

        with self._state_lock:
            token = self._tokens.get(str(work_id))
        return token.cancel(reason) if token is not None else False

    def _enqueue(
        self,
        request: ProofWorkRequest,
        token: ProofWorkCancellationToken,
    ) -> bool:
        with self._state_lock:
            if request.work_id in self._tokens:
                raise ValueError(f"work_id is already scheduled: {request.work_id}")
            queued = sum(len(queue) for queue in self._queues.values())
            if queued >= self.max_queued_tasks:
                return False
            self._tokens[request.work_id] = token
            self._queues.setdefault(request.resource_class, deque()).append(
                request.work_id
            )
            return True

    def _is_head(self, request: ProofWorkRequest) -> bool:
        with self._state_lock:
            queue = self._queues.get(request.resource_class)
            return bool(queue and queue[0] == request.work_id)

    def _mark_running(self, request: ProofWorkRequest) -> None:
        with self._state_lock:
            queue = self._queues.get(request.resource_class)
            if not queue or queue[0] != request.work_id:
                raise RuntimeError("resource queue ownership changed unexpectedly")
            queue.popleft()
            if not queue:
                self._queues.pop(request.resource_class, None)
            self._running.add(request.work_id)

    def _forget(self, request: ProofWorkRequest) -> None:
        with self._state_lock:
            queue = self._queues.get(request.resource_class)
            if queue:
                try:
                    queue.remove(request.work_id)
                except ValueError:
                    pass
                if not queue:
                    self._queues.pop(request.resource_class, None)
            self._running.discard(request.work_id)
            self._fallback_running.discard(request.work_id)
            self._tokens.pop(request.work_id, None)

    def _begin_fallback(
        self,
        request: ProofWorkRequest,
        token: ProofWorkCancellationToken,
    ) -> bool:
        """Atomically move a queued/primary request into bounded fallback."""

        with self._state_lock:
            existing = self._tokens.get(request.work_id)
            if existing is not None and existing is not token:
                raise ValueError(
                    f"work_id is already scheduled: {request.work_id}"
                )
            queue = self._queues.get(request.resource_class)
            if queue:
                try:
                    queue.remove(request.work_id)
                except ValueError:
                    pass
                if not queue:
                    self._queues.pop(request.resource_class, None)
            if len(self._fallback_running) >= self.max_fallback_concurrency:
                return False
            self._tokens[request.work_id] = token
            self._running.add(request.work_id)
            self._fallback_running.add(request.work_id)
            return True

    def _result(
        self,
        request: ProofWorkRequest,
        status: ProofWorkStatus,
        *,
        queued_at_ms: int,
        started_at_ms: int = 0,
        value: Any = None,
        admission: AdmissionDecision | None = None,
        used_fallback: bool = False,
        fallback_reason: str = "",
        reason_codes: Iterable[str] = (),
        error: str = "",
    ) -> ProofWorkResult:
        return ProofWorkResult(
            request=request,
            status=status,
            queued_at_ms=queued_at_ms,
            started_at_ms=started_at_ms,
            completed_at_ms=max(queued_at_ms, self._clock_ms()),
            value=value,
            admission=admission,
            used_fallback=used_fallback,
            fallback_reason=fallback_reason,
            reason_codes=tuple(dict.fromkeys(str(item) for item in reason_codes)),
            error=str(error)[:4_096],
        )

    def _run_fallback(
        self,
        request: ProofWorkRequest,
        token: ProofWorkCancellationToken,
        fallback: ProofWorkCallable | None,
        *,
        queued_at_ms: int,
        reason_codes: tuple[str, ...],
        admission: AdmissionDecision | None = None,
        primary_error: str = "",
    ) -> ProofWorkResult:
        if token.cancelled:
            self._forget(request)
            return self._result(
                request,
                ProofWorkStatus.CANCELLED,
                queued_at_ms=queued_at_ms,
                admission=admission,
                fallback_reason=token.reason,
                reason_codes=("cancelled",),
            )
        fallback_reason = reason_codes[0] if reason_codes else "primary_failed"
        if fallback is None:
            self._forget(request)
            status = (
                ProofWorkStatus.FAILED
                if primary_error
                else ProofWorkStatus.BACKPRESSURED
            )
            return self._result(
                request,
                status,
                queued_at_ms=queued_at_ms,
                admission=admission,
                fallback_reason=fallback_reason,
                reason_codes=reason_codes,
                error=primary_error,
            )
        if not self._begin_fallback(request, token):
            self._forget(request)
            return self._result(
                request,
                ProofWorkStatus.BACKPRESSURED,
                queued_at_ms=queued_at_ms,
                admission=admission,
                fallback_reason=fallback_reason,
                reason_codes=reason_codes + ("fallback_capacity",),
                error=primary_error,
            )
        started_at_ms = max(queued_at_ms, self._clock_ms())
        context = ProofWorkContext(
            request=request,
            cancellation_token=token,
            admission=admission,
            fallback_reason=fallback_reason,
            reason_codes=reason_codes,
        )
        try:
            try:
                value = fallback(context)
            except Exception as exc:
                result = self._result(
                    request,
                    ProofWorkStatus.FAILED,
                    queued_at_ms=queued_at_ms,
                    started_at_ms=started_at_ms,
                    admission=admission,
                    fallback_reason=fallback_reason,
                    reason_codes=reason_codes + ("fallback_failed",),
                    error=f"{type(exc).__name__}: {exc}",
                )
            else:
                if token.cancelled:
                    result = self._result(
                        request,
                        ProofWorkStatus.CANCELLED,
                        queued_at_ms=queued_at_ms,
                        started_at_ms=started_at_ms,
                        admission=admission,
                        fallback_reason=token.reason,
                        reason_codes=("cancelled",),
                    )
                else:
                    result = self._result(
                        request,
                        ProofWorkStatus.FALLBACK,
                        queued_at_ms=queued_at_ms,
                        started_at_ms=started_at_ms,
                        value=value,
                        admission=admission,
                        used_fallback=True,
                        fallback_reason=fallback_reason,
                        reason_codes=reason_codes,
                        error=primary_error,
                    )
        finally:
            self._forget(request)
        return result

    def execute(
        self,
        request: ProofWorkRequest | Mapping[str, Any],
        operation: ProofWorkCallable,
        *,
        fallback: ProofWorkCallable | None = None,
        cancellation_token: ProofWorkCancellationToken | None = None,
    ) -> ProofWorkResult:
        """Execute one request under bounded admission and deterministic fallback.

        ``max_queue_wait_ms=0`` performs exactly one admission attempt.  A
        positive limit retries transient live-capacity failures until the
        bound expires.  Cancellation never invokes fallback.
        """

        if not callable(operation):
            raise TypeError("operation must be callable")
        if fallback is not None and not callable(fallback):
            raise TypeError("fallback must be callable")
        work = (
            request
            if isinstance(request, ProofWorkRequest)
            else ProofWorkRequest.from_mapping(request)
        )
        token = cancellation_token or ProofWorkCancellationToken()
        queued_at_ms = self._clock_ms()
        if token.cancelled:
            return self._result(
                work,
                ProofWorkStatus.CANCELLED,
                queued_at_ms=queued_at_ms,
                fallback_reason=token.reason,
                reason_codes=("cancelled",),
            )
        if not self._enqueue(work, token):
            return self._run_fallback(
                work,
                token,
                fallback,
                queued_at_ms=queued_at_ms,
                reason_codes=("queue_capacity",),
            )

        deadline_ms = queued_at_ms + work.max_queue_wait_ms
        last_decision: AdmissionDecision | None = None
        while True:
            if token.cancelled:
                self._forget(work)
                return self._result(
                    work,
                    ProofWorkStatus.CANCELLED,
                    queued_at_ms=queued_at_ms,
                    admission=last_decision,
                    fallback_reason=token.reason,
                    reason_codes=("cancelled",),
                )
            now_ms = self._clock_ms()
            if self._is_head(work):
                try:
                    host = self._sample(self.host_resource_source)
                    providers = self._sample(self.provider_capacity_source)
                    last_decision, lease = self.resource_scheduler.acquire(
                        work.to_requirement(),
                        budget=self.budget,
                        host=host,
                        providers=providers,
                    )
                except Exception as exc:
                    return self._run_fallback(
                        work,
                        token,
                        fallback,
                        queued_at_ms=queued_at_ms,
                        reason_codes=("resource_telemetry_error",),
                        primary_error=f"{type(exc).__name__}: {exc}",
                    )
                if lease is not None:
                    self._mark_running(work)
                    started_at_ms = max(queued_at_ms, self._clock_ms())
                    context = ProofWorkContext(
                        request=work,
                        cancellation_token=token,
                        admission=last_decision,
                        lease=lease,
                    )
                    try:
                        value = operation(context)
                    except Exception as exc:
                        primary_error = f"{type(exc).__name__}: {exc}"
                        self.resource_scheduler.release(lease)
                        return self._run_fallback(
                            work,
                            token,
                            fallback,
                            queued_at_ms=queued_at_ms,
                            reason_codes=("primary_execution_failed",),
                            admission=last_decision,
                            primary_error=primary_error,
                        )
                    finally:
                        # ``release`` is idempotent for the exception path.
                        self.resource_scheduler.release(lease)
                    self._forget(work)
                    if token.cancelled:
                        return self._result(
                            work,
                            ProofWorkStatus.CANCELLED,
                            queued_at_ms=queued_at_ms,
                            started_at_ms=started_at_ms,
                            admission=last_decision,
                            fallback_reason=token.reason,
                            reason_codes=("cancelled",),
                        )
                    return self._result(
                        work,
                        ProofWorkStatus.SUCCEEDED,
                        queued_at_ms=queued_at_ms,
                        started_at_ms=started_at_ms,
                        value=value,
                        admission=last_decision,
                    )

            if work.max_queue_wait_ms == 0 or now_ms >= deadline_ms:
                reasons = (
                    last_decision.reasons
                    if last_decision is not None and last_decision.reasons
                    else ("queue_wait_timeout",)
                )
                return self._run_fallback(
                    work,
                    token,
                    fallback,
                    queued_at_ms=queued_at_ms,
                    reason_codes=tuple(reasons),
                    admission=last_decision,
                )
            remaining_ms = max(0, deadline_ms - now_ms)
            token.wait(min(self.queue_retry_ms, remaining_ms) / 1000)

    # Compatibility-friendly verb used by orchestration callers.
    run = execute
    execute_work = execute


# Descriptive aliases used by goal-development integrations.
RouteAwareResourceScheduler = GoalRuntimeResourceScheduler
FormalVerificationResourceScheduler = GoalRuntimeResourceScheduler
ResourceCancellationToken = ProofWorkCancellationToken
ScheduledProofWorkRequest = ProofWorkRequest
ScheduledProofWorkResult = ProofWorkResult


# ---------------------------------------------------------------------------
# Capacity-drift gate for compiled parallel execution plans (PDR-033)
# ---------------------------------------------------------------------------
#
# The parallel plan compiler freezes a capacity snapshot.  Live dispatch must
# re-observe host/provider capacity and either proceed at the planned width,
# degrade to a safe width, or wait — never overcommit beyond live headroom.


CAPACITY_DRIFT_DECISION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/capacity-drift-decision@1"
)
COMPILED_RESOURCE_ADMISSION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/compiled-resource-admission@1"
)


class CapacityDriftAction(str, Enum):
    """How live capacity compares to the compiled plan's frozen snapshot."""

    PROCEED = "proceed"
    DEGRADE = "degrade"
    WAIT = "wait"


@dataclass(frozen=True)
class CapacityDriftDecision:
    """Fail-closed decision when live capacity drifts from the plan snapshot."""

    action: CapacityDriftAction
    planned_width: int
    live_width: int
    admitted_width: int
    planned_capacity_snapshot_id: str = ""
    live_capacity_snapshot_id: str = ""
    reasons: tuple[str, ...] = ()
    overcommit_prevented: bool = False
    wait_recommended: bool = False
    degraded_task_ids: tuple[str, ...] = ()
    admitted_task_ids: tuple[str, ...] = ()
    resource_headroom: Mapping[str, int] = field(default_factory=dict)
    provider_headroom: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        action = self.action
        if not isinstance(action, CapacityDriftAction):
            object.__setattr__(
                self, "action", CapacityDriftAction(str(action).strip().lower())
            )
        for name in ("planned_width", "live_width", "admitted_width"):
            value = max(0, int(getattr(self, name) or 0))
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "reasons",
            tuple(dict.fromkeys(str(item) for item in self.reasons if str(item))),
        )
        object.__setattr__(
            self,
            "degraded_task_ids",
            tuple(str(item) for item in self.degraded_task_ids if str(item)),
        )
        object.__setattr__(
            self,
            "admitted_task_ids",
            tuple(str(item) for item in self.admitted_task_ids if str(item)),
        )
        object.__setattr__(
            self,
            "resource_headroom",
            {
                str(key): int(value)
                for key, value in dict(self.resource_headroom or {}).items()
            },
        )
        object.__setattr__(
            self,
            "provider_headroom",
            {
                str(key): int(value)
                for key, value in dict(self.provider_headroom or {}).items()
            },
        )
        # Never report an admitted width larger than live headroom.
        if self.admitted_width > self.live_width:
            object.__setattr__(self, "admitted_width", self.live_width)
            object.__setattr__(self, "overcommit_prevented", True)

    @property
    def may_dispatch(self) -> bool:
        return self.action in {
            CapacityDriftAction.PROCEED,
            CapacityDriftAction.DEGRADE,
        } and self.admitted_width > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CAPACITY_DRIFT_DECISION_SCHEMA,
            "action": self.action.value,
            "planned_width": self.planned_width,
            "live_width": self.live_width,
            "admitted_width": self.admitted_width,
            "planned_capacity_snapshot_id": self.planned_capacity_snapshot_id,
            "live_capacity_snapshot_id": self.live_capacity_snapshot_id,
            "reasons": list(self.reasons),
            "overcommit_prevented": self.overcommit_prevented,
            "wait_recommended": self.wait_recommended,
            "degraded_task_ids": list(self.degraded_task_ids),
            "admitted_task_ids": list(self.admitted_task_ids),
            "resource_headroom": dict(self.resource_headroom),
            "provider_headroom": dict(self.provider_headroom),
            "may_dispatch": self.may_dispatch,
        }


def _capacity_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, default)


def _host_live_width(
    host: HostResourceSnapshot | Mapping[str, Any] | None,
    *,
    process_slots_per_task: int = 1,
) -> int:
    if host is None:
        return 0
    slots = max(1, int(process_slots_per_task or 1))
    mapping = host if isinstance(host, Mapping) else {}
    # Compiler-style snapshots publish cpu_slots/process_slots directly.
    # An explicit zero is exhausted headroom, not "fall back to worker_limit".
    if isinstance(mapping, Mapping) and (
        "cpu_slots" in mapping or "process_slots" in mapping
    ):
        cpu_slots = _capacity_int(mapping.get("cpu_slots", 0), 0)
        process_slots = _capacity_int(mapping.get("process_slots", 0), 0)
        if "cpu_slots" not in mapping:
            cpu_slots = process_slots
        if "process_slots" not in mapping:
            process_slots = cpu_slots
        if cpu_slots <= 0 and process_slots <= 0:
            return 0
        positive = [item for item in (cpu_slots, process_slots) if item > 0]
        return max(0, min(positive) // slots)

    snapshot = (
        host
        if isinstance(host, HostResourceSnapshot)
        else HostResourceSnapshot.from_mapping(host)
    )
    worker_capacity = _capacity_int(
        getattr(snapshot, "available_worker_capacity", 0),
        0,
    )
    if worker_capacity > 0:
        return max(0, worker_capacity // slots)
    active = _capacity_int(getattr(snapshot, "active_workers", 0), 0)
    limit = _capacity_int(getattr(snapshot, "worker_limit", 0), 0)
    if limit > 0:
        return max(0, (limit - active) // slots)
    return 0


def _provider_live_slots(
    providers: Mapping[str, Any]
    | Iterable[ProviderCapacity | Mapping[str, Any]]
    | None,
    provider_id: str = "",
) -> int:
    if providers is None:
        return UNKNOWN_LIMIT if UNKNOWN_LIMIT < 0 else 0

    def _raw_slots(item: Any) -> int | None:
        if isinstance(item, Mapping):
            for key in (
                "available_slots",
                "available_concurrency",
                "max_concurrency",
            ):
                if key in item and item.get(key) is not None:
                    return max(0, int(item.get(key) or 0))
        return None

    # Prefer raw mapping fields from compiler-style provider snapshots.
    if isinstance(providers, Mapping) and not any(
        isinstance(providers.get(key), (Mapping, ProviderCapacity))
        for key in providers
        if key not in {"provider_id", "snapshot_id"}
    ):
        # Single provider mapping.
        raw = _raw_slots(providers)
        if raw is not None:
            if provider_id and str(providers.get("provider_id") or "").strip():
                if str(providers.get("provider_id") or "").strip().lower() != provider_id.lower():
                    return 0
            return raw

    if isinstance(providers, Mapping):
        iterable: Iterable[Any] = providers.values()
    else:
        iterable = providers

    total = 0
    matched = False
    for item in iterable:
        if isinstance(item, Mapping):
            item_id = str(item.get("provider_id") or "").strip().lower()
            raw = _raw_slots(item)
            if provider_id and item_id and item_id != provider_id.lower():
                continue
            if provider_id and not item_id and raw is None:
                continue
            if raw is not None:
                matched = True
                total += raw
                if provider_id:
                    return raw
            continue
        # Fall through to normalized ProviderCapacity objects below.

    if matched and not provider_id:
        return total
    if matched and provider_id:
        return total

    normalized = normalize_provider_capacities(providers)
    if not normalized:
        return 0
    if provider_id:
        for item in normalized:
            if item.provider_id == provider_id:
                return max(0, int(item.available_concurrency))
        return 0
    return sum(max(0, int(item.available_concurrency)) for item in normalized)


def _mirror_capacity_drift(decision: CapacityDriftDecision) -> CapacityDriftDecision:
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        snapshot_id = str(
            decision.live_capacity_snapshot_id or decision.planned_capacity_snapshot_id or ""
        )
        record_ref = str(
            snapshot_id
            or getattr(decision.action, "value", "")
            or "capacity-drift"
        )
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="capacity_drift_decision",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return decision


def evaluate_capacity_drift(
    *,
    planned_width: int,
    planned_capacity_snapshot_id: str = "",
    planned_capacity: Mapping[str, Any] | HostResourceSnapshot | None = None,
    live_host: Mapping[str, Any] | HostResourceSnapshot | None = None,
    live_providers: Mapping[str, Any]
    | Iterable[ProviderCapacity | Mapping[str, Any]]
    | None = None,
    live_capacity_snapshot_id: str = "",
    candidate_task_ids: Sequence[str] = (),
    process_slots_per_task: int = 1,
    provider_id: str = "",
    require_provider: bool = False,
    stale_capacity: bool = False,
    current_time_ms: int = 0,
    capacity_fresh_until_ms: int = 0,
) -> CapacityDriftDecision:
    """Compare live capacity to the plan snapshot and never overcommit.

    * ``proceed`` — live width still covers the planned concurrent width
    * ``degrade`` — some headroom remains; admit a reduced concurrent set
    * ``wait`` — no safe headroom, stale capacity, or overcommit would occur
    """

    planned = max(0, int(planned_width or 0))
    reasons: list[str] = []
    if stale_capacity:
        reasons.append("stale_capacity")
    if (
        current_time_ms
        and capacity_fresh_until_ms
        and int(current_time_ms) > int(capacity_fresh_until_ms)
    ):
        reasons.append("capacity_expired")
        stale_capacity = True

    planned_host_width = planned
    if planned_capacity is not None:
        planned_host_width = max(
            planned_host_width,
            _host_live_width(
                planned_capacity,
                process_slots_per_task=process_slots_per_task,
            ),
        )

    live_host_width = _host_live_width(
        live_host,
        process_slots_per_task=process_slots_per_task,
    )
    provider_slots = _provider_live_slots(live_providers, provider_id=provider_id)
    live_width = live_host_width
    if require_provider or provider_id:
        if provider_slots == 0:
            reasons.append("provider_capacity_exhausted")
            live_width = 0
        elif provider_slots > 0:
            live_width = (
                min(live_width, provider_slots)
                if live_width > 0
                else provider_slots
            )
        # provider_slots < 0 means unbounded / not reported: leave host width.

    if live_host is None and live_providers is None:
        reasons.append("live_capacity_unavailable")
        live_width = 0

    candidates = [str(item).strip() for item in candidate_task_ids if str(item).strip()]
    target_width = planned if planned > 0 else len(candidates) or 1
    overcommit_prevented = False

    if stale_capacity or live_width <= 0:
        return _mirror_capacity_drift(
            CapacityDriftDecision(
                action=CapacityDriftAction.WAIT,
                planned_width=target_width,
                live_width=max(0, live_width),
                admitted_width=0,
                planned_capacity_snapshot_id=str(planned_capacity_snapshot_id or ""),
                live_capacity_snapshot_id=str(live_capacity_snapshot_id or ""),
                reasons=tuple(dict.fromkeys(reasons or ["insufficient_live_capacity"])),
                overcommit_prevented=True,
                wait_recommended=True,
                degraded_task_ids=tuple(candidates),
                admitted_task_ids=(),
                resource_headroom={
                    "host_task_slots": max(0, live_host_width),
                    "planned_width": target_width,
                },
                provider_headroom={
                    "provider_slots": max(0, provider_slots if provider_slots > 0 else 0),
                },
            )
        )

    if live_width >= target_width:
        admitted = candidates[:target_width] if candidates else ()
        return _mirror_capacity_drift(
            CapacityDriftDecision(
                action=CapacityDriftAction.PROCEED,
                planned_width=target_width,
                live_width=live_width,
                admitted_width=target_width,
                planned_capacity_snapshot_id=str(planned_capacity_snapshot_id or ""),
                live_capacity_snapshot_id=str(live_capacity_snapshot_id or ""),
                reasons=tuple(reasons),
                overcommit_prevented=False,
                wait_recommended=False,
                degraded_task_ids=tuple(candidates[target_width:]) if candidates else (),
                admitted_task_ids=tuple(admitted) if admitted else tuple(candidates[:target_width]),
                resource_headroom={
                    "host_task_slots": live_host_width,
                    "planned_width": target_width,
                },
                provider_headroom={
                    "provider_slots": max(0, provider_slots if provider_slots > 0 else 0),
                },
            )
        )

    # Live capacity shrank: degrade to live width rather than overcommit.
    overcommit_prevented = True
    reasons.append("capacity_drift")
    reasons.append("degraded_width")
    admitted_n = min(live_width, len(candidates) if candidates else live_width)
    if admitted_n <= 0:
        return _mirror_capacity_drift(
            CapacityDriftDecision(
                action=CapacityDriftAction.WAIT,
                planned_width=target_width,
                live_width=live_width,
                admitted_width=0,
                planned_capacity_snapshot_id=str(planned_capacity_snapshot_id or ""),
                live_capacity_snapshot_id=str(live_capacity_snapshot_id or ""),
                reasons=tuple(dict.fromkeys([*reasons, "no_safe_width"])),
                overcommit_prevented=True,
                wait_recommended=True,
                degraded_task_ids=tuple(candidates),
                admitted_task_ids=(),
                resource_headroom={
                    "host_task_slots": live_host_width,
                    "planned_width": target_width,
                },
                provider_headroom={
                    "provider_slots": max(0, provider_slots if provider_slots > 0 else 0),
                },
            )
        )

    admitted_ids = tuple(candidates[:admitted_n]) if candidates else ()
    degraded_ids = tuple(candidates[admitted_n:]) if candidates else ()
    return _mirror_capacity_drift(
        CapacityDriftDecision(
            action=CapacityDriftAction.DEGRADE,
            planned_width=target_width,
            live_width=live_width,
            admitted_width=admitted_n,
            planned_capacity_snapshot_id=str(planned_capacity_snapshot_id or ""),
            live_capacity_snapshot_id=str(live_capacity_snapshot_id or ""),
            reasons=tuple(dict.fromkeys(reasons)),
            overcommit_prevented=overcommit_prevented,
            wait_recommended=False,
            degraded_task_ids=degraded_ids,
            admitted_task_ids=admitted_ids,
            resource_headroom={
                "host_task_slots": live_host_width,
                "planned_width": target_width,
            },
            provider_headroom={
                "provider_slots": max(0, provider_slots if provider_slots > 0 else 0),
            },
        )
    )


@dataclass(frozen=True)
class CompiledResourceAdmission:
    """Resource/provider admission for one compiled assignment before claim."""

    task_id: str
    admitted: bool
    reason: str
    capacity_drift: CapacityDriftDecision
    resource_class: str = ""
    provider_id: str = ""
    fairness_key: str = ""
    critical_path_rank: int = 0
    merge_train_id: str = ""
    post_merge_validation: tuple[str, ...] = ()
    lease_id: str = ""
    worktree_id: str = ""
    fence_token: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPILED_RESOURCE_ADMISSION_SCHEMA,
            "task_id": self.task_id,
            "admitted": self.admitted,
            "reason": self.reason,
            "capacity_drift": self.capacity_drift.to_dict(),
            "resource_class": self.resource_class,
            "provider_id": self.provider_id,
            "fairness_key": self.fairness_key,
            "critical_path_rank": self.critical_path_rank,
            "merge_train_id": self.merge_train_id,
            "post_merge_validation": list(self.post_merge_validation),
            "lease_id": self.lease_id,
            "worktree_id": self.worktree_id,
            "fence_token": self.fence_token,
        }


def admit_compiled_execution_assignments(
    *,
    assignments: Sequence[Mapping[str, Any]],
    planned_width: int,
    planned_capacity_snapshot_id: str = "",
    planned_capacity: Mapping[str, Any] | HostResourceSnapshot | None = None,
    live_host: Mapping[str, Any] | HostResourceSnapshot | None = None,
    live_providers: Mapping[str, Any]
    | Iterable[ProviderCapacity | Mapping[str, Any]]
    | None = None,
    live_capacity_snapshot_id: str = "",
    critical_path: Sequence[str] = (),
    fairness_order: Sequence[str] = (),
    merge_steps: Mapping[str, Mapping[str, Any]] | None = None,
    require_provider: bool = False,
    stale_capacity: bool = False,
    current_time_ms: int = 0,
    capacity_fresh_until_ms: int = 0,
    scheduler: ResourceScheduler | None = None,
    active_requirements: Iterable[LaneResourceRequirements] = (),
) -> tuple[CapacityDriftDecision, tuple[CompiledResourceAdmission, ...]]:
    """Admit compiled assignments with fairness/critical-path order and no overcommit.

    Callers must still acquire the compiled lease/worktree/fence names before
    publishing a claim.  This function only decides which assignments may
    proceed under live capacity.
    """

    records = [dict(item) for item in assignments if dict(item).get("task_id")]
    critical_rank = {
        str(task_id).strip(): index
        for index, task_id in enumerate(critical_path)
        if str(task_id).strip()
    }
    fairness_rank = {
        str(task_id).strip(): index
        for index, task_id in enumerate(fairness_order)
        if str(task_id).strip()
    }

    def sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        task_id = str(item.get("task_id") or "").strip()
        affinity = str(item.get("affinity_key") or item.get("shard_id") or task_id)
        return (
            critical_rank.get(task_id, len(critical_rank)),
            fairness_rank.get(task_id, len(fairness_rank)),
            affinity,
            task_id,
        )

    ordered = sorted(records, key=sort_key)
    candidate_ids = [str(item.get("task_id") or "").strip() for item in ordered]
    drift = evaluate_capacity_drift(
        planned_width=planned_width or len(candidate_ids),
        planned_capacity_snapshot_id=planned_capacity_snapshot_id,
        planned_capacity=planned_capacity,
        live_host=live_host,
        live_providers=live_providers,
        live_capacity_snapshot_id=live_capacity_snapshot_id,
        candidate_task_ids=candidate_ids,
        require_provider=require_provider,
        stale_capacity=stale_capacity,
        current_time_ms=current_time_ms,
        capacity_fresh_until_ms=capacity_fresh_until_ms,
        provider_id=str((ordered[0] if ordered else {}).get("provider_id") or ""),
    )
    admitted_set = set(drift.admitted_task_ids)
    merge_map = {
        str(key).strip(): dict(value)
        for key, value in dict(merge_steps or {}).items()
        if str(key).strip()
    }
    admissions: list[CompiledResourceAdmission] = []
    active = list(active_requirements)
    for item in ordered:
        task_id = str(item.get("task_id") or "").strip()
        merge = merge_map.get(task_id) or {}
        resource_class = str(item.get("resource_class") or "").strip()
        provider_id = str(item.get("provider_id") or "").strip()
        fairness_key = str(
            item.get("affinity_key") or item.get("shard_id") or task_id
        ).strip()
        lease_id = str(item.get("lease_id") or "").strip()
        worktree_id = str(item.get("worktree_id") or "").strip()
        fence_token = str(item.get("fence_token") or "").strip()
        if task_id not in admitted_set or not drift.may_dispatch:
            admissions.append(
                CompiledResourceAdmission(
                    task_id=task_id,
                    admitted=False,
                    reason=drift.action.value if not drift.may_dispatch else "capacity_degraded",
                    capacity_drift=drift,
                    resource_class=resource_class,
                    provider_id=provider_id,
                    fairness_key=fairness_key,
                    critical_path_rank=critical_rank.get(task_id, len(critical_rank)),
                    merge_train_id=str(
                        merge.get("merge_train_id") or item.get("merge_target") or ""
                    ),
                    post_merge_validation=tuple(
                        str(v)
                        for v in (merge.get("post_merge_validation") or ())
                        if str(v)
                    ),
                    lease_id=lease_id,
                    worktree_id=worktree_id,
                    fence_token=fence_token,
                )
            )
            continue
        if scheduler is not None and live_host is not None:
            requirement = LaneResourceRequirements.from_mapping(
                {
                    "lane_id": task_id,
                    "resource_class": resource_class or "cpu-small",
                    "stage": "implementation",
                    "process_slots": 1,
                    "provider_required": bool(require_provider or provider_id),
                    "provider_id": provider_id,
                    "critical_path_length": max(
                        0, len(critical_path) - critical_rank.get(task_id, 0)
                    ),
                    "fairness_key": fairness_key,
                }
            )
            decision = scheduler.evaluate(
                requirement,
                host=live_host,
                providers=live_providers,
                active_requirements=active,
            )
            if not decision.admitted:
                admissions.append(
                    CompiledResourceAdmission(
                        task_id=task_id,
                        admitted=False,
                        reason=",".join(decision.reasons) or "resource_denied",
                        capacity_drift=drift,
                        resource_class=resource_class,
                        provider_id=provider_id,
                        fairness_key=fairness_key,
                        critical_path_rank=critical_rank.get(
                            task_id, len(critical_rank)
                        ),
                        merge_train_id=str(
                            merge.get("merge_train_id")
                            or item.get("merge_target")
                            or ""
                        ),
                        post_merge_validation=tuple(
                            str(v)
                            for v in (merge.get("post_merge_validation") or ())
                            if str(v)
                        ),
                        lease_id=lease_id,
                        worktree_id=worktree_id,
                        fence_token=fence_token,
                    )
                )
                continue
            active.append(requirement)
        admissions.append(
            CompiledResourceAdmission(
                task_id=task_id,
                admitted=True,
                reason="admitted",
                capacity_drift=drift,
                resource_class=resource_class,
                provider_id=provider_id,
                fairness_key=fairness_key,
                critical_path_rank=critical_rank.get(task_id, len(critical_rank)),
                merge_train_id=str(
                    merge.get("merge_train_id") or item.get("merge_target") or ""
                ),
                post_merge_validation=tuple(
                    str(v)
                    for v in (merge.get("post_merge_validation") or ())
                    if str(v)
                ),
                lease_id=lease_id,
                worktree_id=worktree_id,
                fence_token=fence_token,
            )
        )
    admissions_tuple = tuple(admissions)
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        snapshot_id = str(planned_capacity_snapshot_id or live_capacity_snapshot_id or "")
        task_id = str(admissions_tuple[0].task_id if admissions_tuple else "")
        record_ref = str(task_id or snapshot_id or "compiled-execution-admission")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="compiled_execution_admission",
            record_ref=record_ref,
            subject_kind="task_id" if task_id else "record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return drift, admissions_tuple



LGSWF_RESOURCE_VECTOR = (
    "cpu_ms",
    "cpu_concurrency",
    "ram_mib",
    "gpu_memory_mib",
    "disk_mib",
    "network",
    "subprocesses",
    "worktrees",
    "model_input_tokens",
    "model_output_tokens",
    "provider_quota_units",
    "provider_concurrency",
)


class LgswfReservationError(ValueError):
    """Leased reservation was refused."""


def lgswf_reserve_vector(available, demand, *, owner):
    reserved = {}
    for key in LGSWF_RESOURCE_VECTOR:
        need = int(demand.get(key, 0) or 0)
        have = int(available.get(key, 0) or 0)
        if need < 0 or have < 0:
            raise LgswfReservationError(f"{key} must be non-negative")
        if need > have:
            raise LgswfReservationError(f"insufficient {key}")
        reserved[key] = need
    return {
        "owner": owner,
        "reserved": reserved,
        "leased": True,
        "released": False,
    }


def lgswf_release_vector(lease):
    if not lease.get("leased"):
        raise LgswfReservationError("lease is not active")
    released = dict(lease)
    released["leased"] = False
    released["released"] = True
    return released

__all__ = [
    "ADAPTIVE_SCHEDULING_THROUGHPUT_REQUIREMENT_ID",
    "ADAPTIVE_STAGE_PROFILES",
    "ADAPTIVE_STAGES",
    "ADAPTIVE_THROUGHPUT_BENCHMARK_SCHEMA",
    "AdmissionDecision",
    "AdaptiveResourceMetrics",
    "AdaptiveStageCapacity",
    "AdaptiveStageMetrics",
    "AdaptiveStageProfile",
    "AdaptiveThroughputBenchmarkReceipt",
    "AdaptiveThroughputRun",
    "CANONICAL_ADAPTIVE_STAGES",
    "CAPACITY_DRIFT_DECISION_SCHEMA",
    "COMPILED_RESOURCE_ADMISSION_SCHEMA",
    "CapacityDriftAction",
    "CapacityDriftDecision",
    "ChildResourceLimits",
    "CompiledResourceAdmission",
    "DEFAULT_RESOURCE_CLASSES",
    "FormalVerificationResourceScheduler",
    "FairWorkStealDecision",
    "GoalRuntimeResourceScheduler",
    "HostResourceSnapshot",
    "LaneResourceRequirements",
    "LEGACY_RESOURCE_CLASSES",
    "PROOF_RESOURCE_CLASSES",
    "ProofWorkCancellationToken",
    "ProofWorkContext",
    "ProofWorkKind",
    "ProofWorkRequest",
    "ProofWorkResult",
    "ProofWorkStatus",
    "ProofResourceClass",
    "ProviderCapacity",
    "ResourceCancellationToken",
    "ResourceAdmissionLease",
    "ResourceLeaseBudget",
    "ResourcePolicy",
    "ResourcePoolAdmissionSnapshot",
    "ResourceScheduleSnapshot",
    "ResourceScheduler",
    "RouteAwareResourceScheduler",
    "ScheduledProofWorkRequest",
    "ScheduledProofWorkResult",
    "STAGE_RESOURCE_PROFILES",
    "StageResourceProfile",
    "SupervisorResourceLeaseBudget",
    "TaskGenerationAdmission",
    "adaptive_stage_profile",
    "admit_compiled_execution_assignments",
    "benchmark_adaptive_execution",
    "evaluate_adaptive_throughput_benchmark",
    "evaluate_capacity_drift",
    "normalize_adaptive_stage",
    "normalize_provider_capacities",
    "normalize_provider_capacity",
    "normalize_proof_work_kind",
    "normalize_resource_class",
    "resource_class_for_work_kind",
    "resource_pool",
    "sample_host_resources",
    "LGSWF_RESOURCE_VECTOR",
    "LgswfReservationError",
    "lgswf_release_vector",
    "lgswf_reserve_vector",
]

class CampaignResourceKind(str, Enum):
    """Independently accounted campaign resource kinds for PGIR admission."""

    CPU = "cpu"
    GPU = "gpu"
    PROVER = "prover"
    IO = "io"
    TOKEN = "token"
    PROVIDER = "provider"
    NETWORK = "network"


class ExclusiveAuthority(str, Enum):
    """Shared mutable authorities that must be serialized by lease key."""

    TOKENIZER = "tokenizer"
    CHECKPOINT = "checkpoint"
    CORPUS = "corpus"
    SPLIT = "split"
    COMPILER_CONTRACT = "compiler-contract"
    LOSS_CONFIG = "loss-config"
    PROOF_SHARD = "proof-shard"
    EVALUATION_SHARD = "evaluation-shard"
    PROMOTION_POINTER = "promotion-pointer"
    PUBLICATION = "publication"


class PipelineHazard(str, Enum):
    """Fail-closed overlap and admission hazards for campaign pipelines."""

    UNSEALED_DATA = "unsealed_data"
    STALE_TRACE = "stale_trace"
    CHECKPOINT_COLLISION = "checkpoint_collision"
    INCOMPATIBLE_TOKENIZER_MUTATION = "incompatible_tokenizer_mutation"
    EXCLUSIVE_AUTHORITY_COLLISION = "exclusive_authority_collision"
    PROHIBITED_STAGE_OVERLAP = "prohibited_stage_overlap"
    NETWORK_DENIED = "network_denied"
    NETWORK_NOT_ALLOWLISTED = "network_not_allowlisted"
    GPU_TELEMETRY_MISSING = "gpu_telemetry_missing"
    PROVER_NOT_ADMITTED = "prover_not_admitted"
    TIMED_OUT = "timed_out"


def normalize_campaign_resource_kind(value: Any) -> str:
    """Return one of the seven campaign resource kinds, or an empty string."""

    raw = str(getattr(value, "value", value) or "").strip().lower()
    raw = raw.replace(" ", "_").replace("-", "_")
    aliases = {
        "cpu": CampaignResourceKind.CPU.value,
        "host_cpu": CampaignResourceKind.CPU.value,
        "gpu": CampaignResourceKind.GPU.value,
        "vram": CampaignResourceKind.GPU.value,
        "gpu_memory": CampaignResourceKind.GPU.value,
        "accelerator": CampaignResourceKind.GPU.value,
        "prover": CampaignResourceKind.PROVER.value,
        "solver": CampaignResourceKind.PROVER.value,
        "atp": CampaignResourceKind.PROVER.value,
        "smt": CampaignResourceKind.PROVER.value,
        "io": CampaignResourceKind.IO.value,
        "disk": CampaignResourceKind.IO.value,
        "artifact": CampaignResourceKind.IO.value,
        "token": CampaignResourceKind.TOKEN.value,
        "tokens": CampaignResourceKind.TOKEN.value,
        "token_budget": CampaignResourceKind.TOKEN.value,
        "provider": CampaignResourceKind.PROVIDER.value,
        "llm": CampaignResourceKind.PROVIDER.value,
        "model": CampaignResourceKind.PROVIDER.value,
        "network": CampaignResourceKind.NETWORK.value,
        "https": CampaignResourceKind.NETWORK.value,
        "hub": CampaignResourceKind.NETWORK.value,
    }
    if raw in aliases:
        return aliases[raw]
    if raw.startswith("cpu"):
        return CampaignResourceKind.CPU.value
    if raw.startswith("gpu"):
        return CampaignResourceKind.GPU.value
    if raw.startswith("io") or raw.startswith("disk"):
        return CampaignResourceKind.IO.value
    if raw.startswith("llm") or raw.startswith("provider"):
        return CampaignResourceKind.PROVIDER.value
    if raw.startswith("token"):
        return CampaignResourceKind.TOKEN.value
    if raw.startswith("network") or raw.startswith("https"):
        return CampaignResourceKind.NETWORK.value
    if "prover" in raw or "solver" in raw or raw.startswith("cpu_proof"):
        return CampaignResourceKind.PROVER.value
    return ""


def normalize_exclusive_authority(value: Any) -> str:
    raw = str(getattr(value, "value", value) or "").strip().lower()
    raw = raw.replace(" ", "_").replace("/", "-")
    aliases = {
        "tokenizer": ExclusiveAuthority.TOKENIZER.value,
        "vocab": ExclusiveAuthority.TOKENIZER.value,
        "vocabulary": ExclusiveAuthority.TOKENIZER.value,
        "checkpoint": ExclusiveAuthority.CHECKPOINT.value,
        "ckpt": ExclusiveAuthority.CHECKPOINT.value,
        "corpus": ExclusiveAuthority.CORPUS.value,
        "split": ExclusiveAuthority.SPLIT.value,
        "compiler": ExclusiveAuthority.COMPILER_CONTRACT.value,
        "compiler_contract": ExclusiveAuthority.COMPILER_CONTRACT.value,
        "compiler-contract": ExclusiveAuthority.COMPILER_CONTRACT.value,
        "loss": ExclusiveAuthority.LOSS_CONFIG.value,
        "loss_config": ExclusiveAuthority.LOSS_CONFIG.value,
        "loss-config": ExclusiveAuthority.LOSS_CONFIG.value,
        "proof": ExclusiveAuthority.PROOF_SHARD.value,
        "proof_shard": ExclusiveAuthority.PROOF_SHARD.value,
        "proof-shard": ExclusiveAuthority.PROOF_SHARD.value,
        "evaluation": ExclusiveAuthority.EVALUATION_SHARD.value,
        "evaluation_shard": ExclusiveAuthority.EVALUATION_SHARD.value,
        "evaluation-shard": ExclusiveAuthority.EVALUATION_SHARD.value,
        "promotion": ExclusiveAuthority.PROMOTION_POINTER.value,
        "promotion_pointer": ExclusiveAuthority.PROMOTION_POINTER.value,
        "promotion-pointer": ExclusiveAuthority.PROMOTION_POINTER.value,
        "publication": ExclusiveAuthority.PUBLICATION.value,
    }
    compact = raw.replace("_", "-")
    return aliases.get(raw) or aliases.get(compact) or compact


def campaign_stages_may_overlap(left: Any, right: Any) -> bool:
    """Return whether two pipeline stages may share a host when otherwise safe."""

    first = normalize_adaptive_stage(left)
    second = normalize_adaptive_stage(right)
    if first == second:
        return first not in _SERIAL_STAGES
    pair = frozenset((first, second))
    if pair in _SAFE_STAGE_OVERLAPS:
        return True
    if first in _SERIAL_STAGES or second in _SERIAL_STAGES:
        return False
    left_kinds = set(_STAGE_RESOURCE_KINDS.get(first, (CampaignResourceKind.CPU.value,)))
    right_kinds = set(_STAGE_RESOURCE_KINDS.get(second, (CampaignResourceKind.CPU.value,)))
    contended = left_kinds.intersection(right_kinds)
    contended.discard(CampaignResourceKind.CPU.value)
    return not contended


@dataclass(frozen=True)
class StageAdmissionProfile:
    """Explainable admission profile for one campaign or supervisor stage."""

    stage: str
    resource_kinds: tuple[str, ...]
    exclusive_authorities: tuple[str, ...] = ()
    overlap_safe_stages: tuple[str, ...] = ()
    requires_sealed_inputs: bool = False
    mutates_tokenizer: bool = False
    mutates_checkpoint: bool = False
    requires_network: bool = False
    requires_gpu: bool = False
    requires_prover: bool = False
    requires_provider: bool = False
    resource_class: str = "cpu-medium"
    pool: str = "cpu-proof"
    schema: str = STAGE_ADMISSION_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", normalize_adaptive_stage(self.stage))
        kinds = tuple(
            dict.fromkeys(
                kind
                for kind in (
                    normalize_campaign_resource_kind(item) for item in self.resource_kinds
                )
                if kind
            )
        )
        if not kinds:
            raise ValueError("stage admission profile must declare resource kinds")
        object.__setattr__(self, "resource_kinds", kinds)
        authorities = tuple(
            dict.fromkeys(
                normalize_exclusive_authority(item)
                for item in self.exclusive_authorities
                if str(item).strip()
            )
        )
        object.__setattr__(self, "exclusive_authorities", authorities)
        object.__setattr__(
            self,
            "overlap_safe_stages",
            tuple(
                dict.fromkeys(
                    normalize_adaptive_stage(item) for item in self.overlap_safe_stages
                )
            ),
        )
        if not str(self.resource_class).strip():
            raise ValueError("resource_class must be non-empty")
        if not str(self.pool).strip():
            raise ValueError("pool must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_kinds"] = list(self.resource_kinds)
        payload["exclusive_authorities"] = list(self.exclusive_authorities)
        payload["overlap_safe_stages"] = list(self.overlap_safe_stages)
        return payload


def stage_admission_profile(stage: Any) -> StageAdmissionProfile:
    """Return the campaign admission profile for ``stage``."""

    name = normalize_adaptive_stage(stage)
    adaptive = adaptive_stage_profile(name)
    authorities = _STAGE_EXCLUSIVE_AUTHORITIES.get(name, ())
    kinds = _STAGE_RESOURCE_KINDS.get(
        name,
        (CampaignResourceKind.CPU.value,),
    )
    companions = tuple(
        other
        for other in (*CANONICAL_ADAPTIVE_STAGES, *CAMPAIGN_PIPELINE_STAGES)
        if other != name and campaign_stages_may_overlap(name, other)
    )
    return StageAdmissionProfile(
        stage=name,
        resource_kinds=kinds,
        exclusive_authorities=authorities,
        overlap_safe_stages=companions,
        requires_sealed_inputs=name in _SEALED_INPUT_STAGES,
        mutates_tokenizer=name == "tokenizer",
        mutates_checkpoint=name == "checkpoint",
        requires_network=CampaignResourceKind.NETWORK.value in kinds,
        requires_gpu=CampaignResourceKind.GPU.value in kinds,
        requires_prover=CampaignResourceKind.PROVER.value in kinds,
        requires_provider=bool(adaptive.requires_provider),
        resource_class=adaptive.resource_class,
        pool=adaptive.pool,
    )


@dataclass(frozen=True)
class CampaignResourceProfileSpec:
    """Integer ceilings for one board resource profile."""

    profile: str
    cpu_count: int
    memory_bytes: int
    disk_bytes: int
    gpu_memory_bytes: int = 0
    wall_time_ms: int = 0
    allows_gpu: bool = False
    allows_provider: bool = False
    allows_prover: bool = False
    allows_network: bool = False
    deny_missing_gpu_telemetry: bool = False
    network_allowlist: tuple[str, ...] = ()
    resource_kinds: tuple[str, ...] = (CampaignResourceKind.CPU.value,)
    resource_class: str = "cpu-medium"
    process_slots: int = 1
    schema: str = CAMPAIGN_RESOURCE_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        if not str(self.profile).strip():
            raise ValueError("resource profile must be non-empty")
        object.__setattr__(self, "profile", str(self.profile).strip().upper())
        for name in (
            "cpu_count",
            "memory_bytes",
            "disk_bytes",
            "gpu_memory_bytes",
            "wall_time_ms",
            "process_slots",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.process_slots <= 0:
            raise ValueError("process_slots must be a positive integer")
        object.__setattr__(
            self,
            "resource_kinds",
            tuple(
                dict.fromkeys(
                    kind
                    for kind in (
                        normalize_campaign_resource_kind(item)
                        for item in self.resource_kinds
                    )
                    if kind
                )
            )
            or (CampaignResourceKind.CPU.value,),
        )
        object.__setattr__(
            self,
            "network_allowlist",
            tuple(
                dict.fromkeys(
                    str(item).strip() for item in self.network_allowlist if str(item).strip()
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_kinds"] = list(self.resource_kinds)
        payload["network_allowlist"] = list(self.network_allowlist)
        return payload

    def to_requirement(
        self,
        lane_id: str,
        *,
        stage: Any = "execution",
        **overrides: Any,
    ) -> "LaneResourceRequirements":
        """Materialize a lane claim that cannot exceed this profile's ceiling."""

        values: dict[str, Any] = {
            "lane_id": lane_id,
            "stage": stage,
            "resource_class": self.resource_class,
            "memory_bytes": self.memory_bytes,
            "disk_bytes": self.disk_bytes,
            "gpu_memory_bytes": self.gpu_memory_bytes,
            "process_slots": self.process_slots,
            "timeout_ms": self.wall_time_ms,
            "resource_profile": self.profile,
            "requires_gpu": self.allows_gpu and self.deny_missing_gpu_telemetry,
            "requires_prover": self.allows_prover,
            "requires_network": self.allows_network,
            "requires_provider": self.allows_provider,
            "network_allowlist": self.network_allowlist,
            "claimed_resource_kinds": self.resource_kinds,
        }
        values.update(overrides)
        return LaneResourceRequirements.from_mapping(values)


def campaign_resource_profile_spec(profile: Any) -> CampaignResourceProfileSpec:
    """Return the closed board profile for ``profile``."""

    raw = str(getattr(profile, "value", profile) or "").strip().upper()
    spec = CAMPAIGN_RESOURCE_PROFILE_SPECS.get(raw)
    if spec is None:
        raise ValueError(f"unsupported campaign resource profile: {profile!r}")
    return spec


def lane_requirements_for_resource_profile(
    lane_id: str,
    profile: Any,
    *,
    stage: Any = "execution",
    **overrides: Any,
) -> "LaneResourceRequirements":
    """Build a lane claim from a board resource profile."""

    return campaign_resource_profile_spec(profile).to_requirement(
        lane_id,
        stage=stage,
        **overrides,
    )


@dataclass(frozen=True)
class PipelineOverlapReceipt:
    """Content-addressed decision for one lane against live overlapping work."""

    lane_id: str
    stage: str
    admitted: bool
    resource_kinds: tuple[str, ...]
    overlapping_lane_ids: tuple[str, ...] = ()
    overlapping_stages: tuple[str, ...] = ()
    exclusive_authorities: tuple[str, ...] = ()
    hazards: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    fairness_key: str = ""
    observed_at_ms: int = 0
    schema: str = PIPELINE_OVERLAP_RECEIPT_SCHEMA
    content_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", normalize_adaptive_stage(self.stage))
        object.__setattr__(
            self,
            "resource_kinds",
            tuple(
                dict.fromkeys(
                    kind
                    for kind in (
                        normalize_campaign_resource_kind(item)
                        for item in self.resource_kinds
                    )
                    if kind
                )
            ),
        )
        for name in (
            "overlapping_lane_ids",
            "overlapping_stages",
            "exclusive_authorities",
            "hazards",
            "reasons",
        ):
            object.__setattr__(
                self,
                name,
                tuple(dict.fromkeys(str(item) for item in getattr(self, name) if str(item))),
            )
        expected = _canonical_digest(self._unsigned_dict())
        if self.content_digest and self.content_digest != expected:
            raise ValueError("pipeline overlap receipt content digest mismatch")
        object.__setattr__(self, "content_digest", expected)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lane_id": self.lane_id,
            "stage": self.stage,
            "admitted": self.admitted,
            "resource_kinds": list(self.resource_kinds),
            "overlapping_lane_ids": list(self.overlapping_lane_ids),
            "overlapping_stages": list(self.overlapping_stages),
            "exclusive_authorities": list(self.exclusive_authorities),
            "hazards": list(self.hazards),
            "reasons": list(self.reasons),
            "fairness_key": self.fairness_key,
            "observed_at_ms": self.observed_at_ms,
        }

    @property
    def allowed(self) -> bool:
        return self.admitted

    @property
    def reason(self) -> str:
        return self.reasons[0] if self.reasons else ""

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["content_digest"] = self.content_digest
        payload["allowed"] = self.allowed
        payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class BackpressureFairnessOverlapReceipt:
    """Batch receipt covering fairness order, hazards, and overlap outcomes."""

    observed_at_ms: int
    fairness_order: tuple[str, ...]
    admitted_lane_ids: tuple[str, ...]
    backpressured_lane_ids: tuple[str, ...]
    cancelled_lane_ids: tuple[str, ...] = ()
    timed_out_lane_ids: tuple[str, ...] = ()
    hazard_counts: Mapping[str, int] = field(default_factory=dict)
    backpressure_counts: Mapping[str, int] = field(default_factory=dict)
    overlap_receipts: tuple[PipelineOverlapReceipt, ...] = ()
    stage_admission_profiles: tuple[StageAdmissionProfile, ...] = ()
    schema: str = BACKPRESSURE_FAIRNESS_OVERLAP_RECEIPT_SCHEMA
    content_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "fairness_order", tuple(self.fairness_order))
        object.__setattr__(self, "admitted_lane_ids", tuple(self.admitted_lane_ids))
        object.__setattr__(
            self, "backpressured_lane_ids", tuple(self.backpressured_lane_ids)
        )
        object.__setattr__(self, "cancelled_lane_ids", tuple(self.cancelled_lane_ids))
        object.__setattr__(self, "timed_out_lane_ids", tuple(self.timed_out_lane_ids))
        object.__setattr__(
            self,
            "hazard_counts",
            {
                str(name): int(value)
                for name, value in sorted(self.hazard_counts.items())
                if int(value) > 0
            },
        )
        object.__setattr__(
            self,
            "backpressure_counts",
            {
                str(name): int(value)
                for name, value in sorted(self.backpressure_counts.items())
                if int(value) > 0
            },
        )
        expected = _canonical_digest(self._unsigned_dict())
        if self.content_digest and self.content_digest != expected:
            raise ValueError("fairness overlap receipt content digest mismatch")
        object.__setattr__(self, "content_digest", expected)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "observed_at_ms": self.observed_at_ms,
            "fairness_order": list(self.fairness_order),
            "admitted_lane_ids": list(self.admitted_lane_ids),
            "backpressured_lane_ids": list(self.backpressured_lane_ids),
            "cancelled_lane_ids": list(self.cancelled_lane_ids),
            "timed_out_lane_ids": list(self.timed_out_lane_ids),
            "hazard_counts": dict(self.hazard_counts),
            "backpressure_counts": dict(self.backpressure_counts),
            "overlap_receipts": [item.to_dict() for item in self.overlap_receipts],
            "stage_admission_profiles": [
                item.to_dict() for item in self.stage_admission_profiles
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["content_digest"] = self.content_digest
        return payload
