"""Source-free phase and resource telemetry for LegalIR optimizer runtimes.

The optimizer handles statutory source material, so this module deliberately
uses an allow-list for span attributes.  Phase names, stable identifiers,
counts, timings, resource measurements, and hashes are observable; arbitrary
payloads, prompts, source/decompiled text, and exception messages are not.

The schema is intentionally independent of OpenTelemetry.  The JSON records
can be persisted in daemon summaries today and adapted to an OTLP exporter
later without changing the runtime's instrumentation contract.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Final, Optional


RUNTIME_TELEMETRY_SCHEMA_VERSION: Final = "legal-ir-runtime-telemetry-v1"
RUNTIME_PHASE_TELEMETRY_SCHEMA_VERSION: Final = RUNTIME_TELEMETRY_SCHEMA_VERSION
RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION: Final = "legal-ir-runtime-resources-v1"

LEGAL_IR_VIEW_PHASES: Final = (
    "legal_ir_view.deontic",
    "legal_ir_view.frame_logic",
    "legal_ir_view.tdfol",
    "legal_ir_view.kg",
    "legal_ir_view.cec",
    "legal_ir_view.external_provers",
    "legal_ir_view.decompiler",
)

RUNTIME_PHASES: Final = (
    "sampling",
    "compilation",
    "decoding",
    "embeddings",
    "projection_training",
    *LEGAL_IR_VIEW_PHASES,
    "bridge_evaluation",
    "premise_selection",
    "solver_execution",
    "lean_reconstruction",
    "leanstral_queue",
    "leanstral_inference",
    "disagreement_export",
    "codex_queue_wait",
    "validation",
    "merge",
    "cache_lookup",
    "state_persistence",
)
REQUIRED_RUNTIME_PHASES: Final = frozenset(RUNTIME_PHASES)

_PHASE_ALIASES: Final = {
    "sampling": "sampling",
    "compiler_ir_train": "compilation",
    "compiler_ir_validation": "validation",
    "compiler_ir_guided_train": "compilation",
    "compiler_ir_guided_validation": "validation",
    "before_train_eval": "embeddings",
    "after_train_eval": "embeddings",
    "before_validation_eval": "validation",
    "after_validation_eval": "validation",
    "sample_memory_probe": "embeddings",
    "projection_training": "projection_training",
    "bridge_ir_train": "bridge_evaluation",
    "bridge_ir_validation": "bridge_evaluation",
    "todo_supervisor_optimize": "leanstral_queue",
    "todo_supervisor_queue_flush": "state_persistence",
    "pre_todo_introspection_disagreement_export": "disagreement_export",
    "introspection_disagreement_export": "disagreement_export",
    "hammer_guidance_cycle": "solver_execution",
    "queue_merge": "merge",
    "leanstral_rule_gap_projection": "leanstral_queue",
    "leanstral_direct_guidance_projection": "leanstral_inference",
    "state_save": "state_persistence",
    "tests": "validation",
}

_SENSITIVE_KEY_PARTS: Final = (
    "text",
    "prompt",
    "content",
    "statement",
    "proof_script",
    "stdout",
    "stderr",
    "exception_message",
    "raw_payload",
)
_SAFE_ATTRIBUTE_KEYS: Final = frozenset(
    {
        "adapter_count",
        "adapter_name",
        "audit_sample_count",
        "backend",
        "block",
        "cache_enabled",
        "cache_kind",
        "dataset",
        "enabled",
        "epoch_count",
        "error_type",
        "evaluated_count",
        "failure_count",
        "formula_count",
        "frame_candidate_count",
        "max_inner_iterations",
        "max_items",
        "metric_sample_id",
        "mode",
        "obligation_count",
        "parallel_workers",
        "phase_alias",
        "reason",
        "sample_count",
        "sample_index",
        "sample_timeout_seconds",
        "scope",
        "stage",
        "status",
        "train_sample_count",
        "validation_mode",
        "validation_sample_count",
        "view",
        "worker_id",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def canonical_runtime_phase(phase: str) -> str:
    """Return the stable phase name for a runner-specific phase label."""

    value = str(phase or "unknown").strip().lower().replace(" ", "_")
    if value in REQUIRED_RUNTIME_PHASES:
        return value
    if value.startswith("legal_ir_view."):
        return value if value in REQUIRED_RUNTIME_PHASES else "legal_ir_view.unknown"
    return _PHASE_ALIASES.get(value, value)


def _safe_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if (
        len(text) <= 256
        and "\n" not in text
        and "\r" not in text
        and len(text.split()) <= 4
    ):
        return text
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _attribute_key_allowed(key: str) -> bool:
    normalized = str(key).strip().lower()
    if not normalized or any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return False
    return (
        normalized in _SAFE_ATTRIBUTE_KEYS
        or normalized.endswith(("_count", "_seconds", "_rate", "_percent"))
        or normalized.endswith(("_id", "_version", "_status", "_mode", "_kind"))
    )


def _safe_attribute_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 9) if math.isfinite(value) else None
    if isinstance(value, str):
        # Statuses and identifiers should be atoms.  Hash prose defensively even
        # when a caller assigns it to an apparently safe key such as ``reason``.
        compact = " ".join(value.split())
        if len(compact) > 96 or len(compact.split()) > 1:
            return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
        return compact
    if isinstance(value, Mapping):
        return sanitize_telemetry_attributes(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        safe = []
        for item in list(value)[:32]:
            if isinstance(item, (str, int, float, bool)) or item is None:
                safe.append(_safe_attribute_value(item))
        return safe
    return _safe_identifier(type(value).__name__)


def sanitize_telemetry_attributes(attributes: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Return source-free, bounded span attributes.

    Unknown keys are omitted instead of guessed safe.  This makes the privacy
    boundary hold even if an upstream progress callback later gains a field
    containing legal wording.
    """

    result: dict[str, Any] = {}
    for raw_key, value in dict(attributes or {}).items():
        key = str(raw_key).strip()
        if not _attribute_key_allowed(key):
            continue
        result[key] = _safe_attribute_value(value)
    return result


@dataclass(frozen=True)
class ResourceSnapshot:
    """Non-blocking host/process resource measurements at a span boundary."""

    captured_at: str = ""
    cpu_percent: Optional[float] = None
    process_cpu_percent: Optional[float] = None
    memory_used_bytes: Optional[int] = None
    memory_percent: Optional[float] = None
    process_memory_bytes: Optional[int] = None
    swap_used_bytes: Optional[int] = None
    swap_percent: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None
    gpu_memory_used_bytes: Optional[int] = None
    gpu_memory_total_bytes: Optional[int] = None
    gpu_memory_percent: Optional[float] = None
    gpu_device_count: int = 0
    gpu_telemetry_available: bool = False
    cuda_available: Optional[bool] = None
    process_gpu_memory_used_bytes: Optional[int] = None
    children_gpu_memory_used_bytes: Optional[int] = None
    trainer_gpu_memory_used_bytes: Optional[int] = None
    leanstral_gpu_memory_used_bytes: Optional[int] = None
    unified_memory_used_bytes: Optional[int] = None
    unified_memory_percent: Optional[float] = None
    process_unified_memory_used_bytes: Optional[int] = None
    children_unified_memory_used_bytes: Optional[int] = None
    trainer_unified_memory_used_bytes: Optional[int] = None
    leanstral_unified_memory_used_bytes: Optional[int] = None
    gpu_processes: Sequence[Mapping[str, Any]] = ()
    child_process_count: int = 0
    queue_depth: int = 0
    collector_status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION,
            "captured_at": self.captured_at,
            "cpu_percent": self.cpu_percent,
            "process_cpu_percent": self.process_cpu_percent,
            "memory_used_bytes": self.memory_used_bytes,
            "memory_percent": self.memory_percent,
            "process_memory_bytes": self.process_memory_bytes,
            "swap_used_bytes": self.swap_used_bytes,
            "swap_percent": self.swap_percent,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "gpu_memory_used_bytes": self.gpu_memory_used_bytes,
            "gpu_memory_total_bytes": self.gpu_memory_total_bytes,
            "gpu_memory_percent": self.gpu_memory_percent,
            "gpu_device_count": self.gpu_device_count,
            "gpu_telemetry_available": self.gpu_telemetry_available,
            "cuda_available": self.cuda_available,
            "process_gpu_memory_used_bytes": self.process_gpu_memory_used_bytes,
            "children_gpu_memory_used_bytes": self.children_gpu_memory_used_bytes,
            "trainer_gpu_memory_used_bytes": self.trainer_gpu_memory_used_bytes,
            "leanstral_gpu_memory_used_bytes": self.leanstral_gpu_memory_used_bytes,
            "unified_memory_used_bytes": self.unified_memory_used_bytes,
            "unified_memory_percent": self.unified_memory_percent,
            "process_unified_memory_used_bytes": self.process_unified_memory_used_bytes,
            "children_unified_memory_used_bytes": self.children_unified_memory_used_bytes,
            "trainer_unified_memory_used_bytes": self.trainer_unified_memory_used_bytes,
            "leanstral_unified_memory_used_bytes": self.leanstral_unified_memory_used_bytes,
            "gpu_processes": [dict(item) for item in self.gpu_processes],
            "child_process_count": self.child_process_count,
            "queue_depth": self.queue_depth,
            "collector_status": self.collector_status,
        }


def _bounded_percent(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * numerator / denominator)), 3)


def _process_details(pid: int, current_pid: int) -> tuple[str, Optional[int]]:
    role = ""
    rss: Optional[int] = None
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(pid)
        try:
            rss = int(process.memory_info().rss)
        except Exception:
            rss = None
        command = " ".join(process.cmdline()).lower()
        name = process.name().lower()
        marker = f"{name} {command}"
        if "leanstral" in marker:
            role = "leanstral"
        elif any(
            item in marker
            for item in (
                "projection_training",
                "trusted_feedback_trainer",
                "trainer",
                "train",
                "autoencoder",
            )
        ):
            role = "trainer"
        elif pid == current_pid:
            role = "current"
        else:
            try:
                parents = {parent.pid for parent in process.parents()}
            except Exception:
                parents = set()
            role = "child" if current_pid in parents else "external"
    except Exception:
        role = "current" if pid == current_pid else "external"
    configured_role = os.environ.get("IPFS_DATASETS_LEGAL_IR_PROCESS_ROLE", "").strip().lower()
    if configured_role and pid == current_pid:
        role = configured_role[:64]
    return role, rss


def _process_record(
    *,
    pid: int,
    gpu_memory_used_bytes: Optional[int],
    source: str,
    current_pid: int,
) -> dict[str, Any]:
    role, rss = _process_details(pid, current_pid)
    unified = None
    if rss is not None or gpu_memory_used_bytes is not None:
        unified = int(rss or 0) + int(gpu_memory_used_bytes or 0)
    return {
        "pid": int(pid),
        "role": role,
        "gpu_memory_used_bytes": gpu_memory_used_bytes,
        "unified_memory_used_bytes": unified,
        "source": source,
    }


def _merge_process_records(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    by_pid: dict[int, dict[str, Any]] = {}
    role_rank = {"trainer": 5, "leanstral": 5, "current": 4, "child": 3, "external": 1}
    for raw in records:
        try:
            pid = int(raw["pid"])
        except Exception:
            continue
        merged = by_pid.setdefault(
            pid,
            {
                "pid": pid,
                "role": str(raw.get("role") or "external"),
                "gpu_memory_used_bytes": None,
                "unified_memory_used_bytes": None,
                "source": "",
            },
        )
        role = str(raw.get("role") or "external")
        if role_rank.get(role, 0) > role_rank.get(str(merged.get("role")), 0):
            merged["role"] = role
        for field in ("gpu_memory_used_bytes", "unified_memory_used_bytes"):
            value = raw.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[field] = max(int(value), int(merged[field] or 0))
        sources = {item for item in str(merged.get("source") or "").split("+") if item}
        source = str(raw.get("source") or "")
        if source:
            sources.add(source)
        merged["source"] = "+".join(sorted(sources))
    return tuple(dict(item) for item in sorted(by_pid.values(), key=lambda item: item["pid"]))


def _aggregate_process_field(
    records: Sequence[Mapping[str, Any]],
    *,
    field: str,
    role: Optional[str] = None,
) -> Optional[int]:
    if not records:
        return None
    values = []
    for record in records:
        if role is not None and record.get("role") != role:
            continue
        value = record.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(int(value))
    return sum(values) if values else 0


def _torch_gpu_snapshot(current_pid: int) -> dict[str, Any]:
    status = "torch_unavailable"
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return {"statuses": [status]}

    try:
        cuda = getattr(torch, "cuda", None)
        available = bool(cuda is not None and cuda.is_available())
        count = int(cuda.device_count()) if available else 0
        if not available or count <= 0:
            return {
                "statuses": ["torch_cuda_unavailable"],
                "cuda_available": False,
                "gpu_device_count": 0,
            }
        memory_used = 0
        memory_reserved = 0
        memory_total = 0
        for index in range(count):
            try:
                memory_used += int(cuda.memory_allocated(index))
            except Exception:
                pass
            try:
                memory_reserved += int(cuda.memory_reserved(index))
            except Exception:
                pass
            try:
                properties = cuda.get_device_properties(index)
                memory_total += int(getattr(properties, "total_memory", 0) or 0)
            except Exception:
                pass
        process_memory = memory_reserved if memory_reserved else memory_used
        records = []
        if process_memory:
            records.append(
                _process_record(
                    pid=current_pid,
                    gpu_memory_used_bytes=process_memory,
                    source="torch",
                    current_pid=current_pid,
                )
            )
        return {
            "statuses": ["torch_cuda_ok"],
            "cuda_available": True,
            "gpu_device_count": count,
            "gpu_memory_used_bytes": process_memory,
            "gpu_memory_total_bytes": memory_total or None,
            "processes": records,
        }
    except Exception:
        return {"statuses": ["torch_collector_error"]}


def _nvml_processes(pynvml: Any, handle: Any, current_pid: int) -> list[dict[str, Any]]:
    for method_name in (
        "nvmlDeviceGetComputeRunningProcesses_v3",
        "nvmlDeviceGetComputeRunningProcesses_v2",
        "nvmlDeviceGetComputeRunningProcesses",
    ):
        method = getattr(pynvml, method_name, None)
        if method is None:
            continue
        try:
            raw_processes = method(handle)
        except Exception:
            continue
        result = []
        for process in raw_processes or ():
            pid = int(getattr(process, "pid", 0) or 0)
            if pid <= 0:
                continue
            used = getattr(process, "usedGpuMemory", None)
            if used is None:
                used = getattr(process, "usedGpuCcProtectedMemory", None)
            used_bytes = None if used is None else max(0, int(used))
            result.append(
                _process_record(
                    pid=pid,
                    gpu_memory_used_bytes=used_bytes,
                    source="nvml",
                    current_pid=current_pid,
                )
            )
        return result
    return []


def _nvml_gpu_snapshot(current_pid: int) -> dict[str, Any]:
    """Read NVML if available."""

    pynvml: Any = None
    initialized = False
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        initialized = True
        count = int(pynvml.nvmlDeviceGetCount())
        utilizations: list[float] = []
        memory_used = 0
        memory_total = 0
        processes: list[dict[str, Any]] = []
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            utilizations.append(float(utilization.gpu))
            memory_used += int(memory.used)
            memory_total += int(memory.total)
            processes.extend(_nvml_processes(pynvml, handle, current_pid))
        result = {
            "statuses": ["nvml_ok" if count else "nvml_no_devices"],
            "cuda_available": True if count else None,
            "gpu_device_count": count,
            "gpu_utilization_percent": (
                round(sum(utilizations) / len(utilizations), 3) if utilizations else None
            ),
            "gpu_memory_used_bytes": memory_used if count else None,
            "gpu_memory_total_bytes": memory_total if memory_total else None,
            "processes": processes,
        }
    except Exception:
        result = {"statuses": ["nvml_unavailable"]}
    finally:
        if initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
    return result


def _nvidia_smi_gpu_snapshot(current_pid: int) -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"statuses": ["nvidia_smi_unavailable"]}
    statuses: list[str] = []
    result: dict[str, Any] = {}
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=0.75,
        )
        utilizations: list[float] = []
        memory_used = 0
        memory_total = 0
        count = 0
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            utilizations.append(float(parts[0]))
            memory_used += int(float(parts[1]) * 1024 * 1024)
            memory_total += int(float(parts[2]) * 1024 * 1024)
            count += 1
        statuses.append("nvidia_smi_ok" if count else "nvidia_smi_no_devices")
        result.update(
            {
                "cuda_available": True if count else None,
                "gpu_device_count": count,
                "gpu_utilization_percent": (
                    round(sum(utilizations) / len(utilizations), 3) if utilizations else None
                ),
                "gpu_memory_used_bytes": memory_used if count else None,
                "gpu_memory_total_bytes": memory_total if memory_total else None,
            }
        )
    except Exception:
        statuses.append("nvidia_smi_gpu_query_error")

    try:
        completed = subprocess.run(
            [
                executable,
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=0.75,
        )
        processes = []
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 2 or not parts[0]:
                continue
            processes.append(
                _process_record(
                    pid=int(parts[0]),
                    gpu_memory_used_bytes=int(float(parts[1]) * 1024 * 1024),
                    source="nvidia-smi",
                    current_pid=current_pid,
                )
            )
        result["processes"] = processes
        statuses.append("nvidia_smi_process_ok")
    except Exception:
        statuses.append("nvidia_smi_process_query_unavailable")
    result["statuses"] = statuses
    return result


def _gpu_snapshot(
    *,
    host_memory_used_bytes: Optional[int],
    host_memory_total_bytes: Optional[int],
    current_pid: Optional[int] = None,
) -> dict[str, Any]:
    """Collect CUDA/GPU facts from independent collectors and merge known values."""

    pid = int(current_pid if current_pid is not None else os.getpid())
    collector_results = (
        _torch_gpu_snapshot(pid),
        _nvml_gpu_snapshot(pid),
        _nvidia_smi_gpu_snapshot(pid),
    )
    statuses: list[str] = []
    processes: list[Mapping[str, Any]] = []
    device_count = 0
    cuda_available: Optional[bool] = None
    gpu_utilization: list[float] = []
    memory_used_values: list[int] = []
    memory_total_values: list[int] = []
    for result in collector_results:
        statuses.extend(str(item) for item in result.get("statuses", ()) if item)
        if result.get("cuda_available") is True:
            cuda_available = True
        elif cuda_available is None and result.get("cuda_available") is False:
            cuda_available = False
        if isinstance(result.get("gpu_device_count"), int):
            device_count = max(device_count, int(result["gpu_device_count"]))
        if isinstance(result.get("gpu_utilization_percent"), (int, float)):
            gpu_utilization.append(float(result["gpu_utilization_percent"]))
        if isinstance(result.get("gpu_memory_used_bytes"), int):
            memory_used_values.append(int(result["gpu_memory_used_bytes"]))
        if isinstance(result.get("gpu_memory_total_bytes"), int):
            memory_total_values.append(int(result["gpu_memory_total_bytes"]))
        if isinstance(result.get("processes"), Sequence):
            processes.extend(result["processes"])

    merged_processes = _merge_process_records(processes)
    gpu_memory_used = max(memory_used_values) if memory_used_values else None
    gpu_memory_total = max(memory_total_values) if memory_total_values else None
    if gpu_memory_used is None:
        process_gpu_values = [
            int(record["gpu_memory_used_bytes"])
            for record in merged_processes
            if isinstance(record.get("gpu_memory_used_bytes"), int)
        ]
        gpu_memory_used = sum(process_gpu_values) if process_gpu_values else None
    gpu_available = bool(
        device_count > 0
        or cuda_available is True
        or gpu_utilization
        or memory_used_values
        or memory_total_values
        or merged_processes
    )
    if cuda_available is None and gpu_available:
        cuda_available = True

    unified_used = host_memory_used_bytes
    if unified_used is None:
        unified_values = [
            int(record["unified_memory_used_bytes"])
            for record in merged_processes
            if isinstance(record.get("unified_memory_used_bytes"), int)
        ]
        unified_used = sum(unified_values) if unified_values else None

    status = ",".join(dict.fromkeys(statuses))
    if not gpu_available and cuda_available is not True:
        status = f"{status},gpu_unavailable" if status else "gpu_unavailable"
    return {
        "gpu_utilization_percent": (
            round(sum(gpu_utilization) / len(gpu_utilization), 3)
            if gpu_utilization
            else None
        ),
        "gpu_memory_used_bytes": gpu_memory_used,
        "gpu_memory_total_bytes": gpu_memory_total,
        "gpu_memory_percent": _bounded_percent(gpu_memory_used, gpu_memory_total),
        "gpu_device_count": device_count,
        "gpu_telemetry_available": gpu_available,
        "cuda_available": cuda_available,
        "process_gpu_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="gpu_memory_used_bytes", role="current"
        ),
        "children_gpu_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="gpu_memory_used_bytes", role="child"
        ),
        "trainer_gpu_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="gpu_memory_used_bytes", role="trainer"
        ),
        "leanstral_gpu_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="gpu_memory_used_bytes", role="leanstral"
        ),
        "unified_memory_used_bytes": unified_used,
        "unified_memory_percent": _bounded_percent(unified_used, host_memory_total_bytes),
        "process_unified_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="unified_memory_used_bytes", role="current"
        ),
        "children_unified_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="unified_memory_used_bytes", role="child"
        ),
        "trainer_unified_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="unified_memory_used_bytes", role="trainer"
        ),
        "leanstral_unified_memory_used_bytes": _aggregate_process_field(
            merged_processes, field="unified_memory_used_bytes", role="leanstral"
        ),
        "gpu_processes": merged_processes,
        "collector_status": status or "ok",
    }


def collect_resource_snapshot(*, queue_depth: int = 0) -> ResourceSnapshot:
    """Collect CPU, memory, swap, GPU, process, child, and queue measurements."""

    cpu_percent: Optional[float] = None
    process_cpu_percent: Optional[float] = None
    memory_used_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    memory_percent: Optional[float] = None
    process_memory_bytes: Optional[int] = None
    swap_used_bytes: Optional[int] = None
    swap_percent: Optional[float] = None
    child_process_count = 0
    status_parts: list[str] = []
    try:
        import psutil  # type: ignore[import-not-found]

        process = psutil.Process(os.getpid())
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        cpu_percent = round(float(psutil.cpu_percent(interval=None)), 3)
        process_cpu_percent = round(float(process.cpu_percent(interval=None)), 3)
        memory_used_bytes = int(memory.used)
        memory_total_bytes = int(memory.total)
        memory_percent = round(float(memory.percent), 3)
        process_memory_bytes = int(process.memory_info().rss)
        swap_used_bytes = int(swap.used)
        swap_percent = round(float(swap.percent), 3)
        child_process_count = len(process.children(recursive=True))
    except Exception:
        status_parts.append("psutil_unavailable")

    gpu = _gpu_snapshot(
        host_memory_used_bytes=memory_used_bytes,
        host_memory_total_bytes=memory_total_bytes,
    )
    gpu_status = str(gpu.pop("collector_status", ""))
    if gpu_status and gpu_status != "ok":
        status_parts.append(gpu_status)
    return ResourceSnapshot(
        captured_at=_utc_now(),
        cpu_percent=cpu_percent,
        process_cpu_percent=process_cpu_percent,
        memory_used_bytes=memory_used_bytes,
        memory_percent=memory_percent,
        process_memory_bytes=process_memory_bytes,
        swap_used_bytes=swap_used_bytes,
        swap_percent=swap_percent,
        **gpu,
        child_process_count=child_process_count,
        queue_depth=max(0, int(queue_depth or 0)),
        collector_status=",".join(status_parts) if status_parts else "ok",
    )


class RuntimeSpan:
    """Mutable in-flight span. Use :meth:`RuntimeTelemetry.finish_span`."""

    __slots__ = (
        "attributes",
        "cache_hit",
        "cycle",
        "parent_span_id",
        "phase",
        "queue_depth",
        "resource_start",
        "sample_id",
        "scope",
        "span_id",
        "started_at",
        "started_monotonic",
        "unit_count",
    )

    def __init__(
        self,
        *,
        phase: str,
        cycle: Optional[int],
        sample_id: str,
        unit_count: float,
        cache_hit: Optional[bool],
        attributes: Mapping[str, Any],
        queue_depth: int,
        parent_span_id: str,
        resource_start: ResourceSnapshot,
        clock: Callable[[], float],
    ) -> None:
        self.phase = canonical_runtime_phase(phase)
        self.cycle = cycle
        self.sample_id = _safe_identifier(sample_id)
        self.scope = "sample" if self.sample_id else "cycle"
        self.unit_count = max(0.0, _finite_float(unit_count))
        self.cache_hit = cache_hit
        self.attributes = sanitize_telemetry_attributes(attributes)
        self.queue_depth = max(0, int(queue_depth or 0))
        self.parent_span_id = parent_span_id
        self.resource_start = resource_start
        self.span_id = uuid.uuid4().hex
        self.started_at = _utc_now()
        self.started_monotonic = clock()


ResourceSampler = Callable[..., ResourceSnapshot | Mapping[str, Any]]


class RuntimeTelemetry:
    """Thread-safe bounded collector for per-cycle and per-sample spans."""

    def __init__(
        self,
        run_id: str,
        *,
        max_spans: int = 4096,
        resource_sampler: Optional[ResourceSampler] = None,
        resource_sample_interval_seconds: float = 0.1,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.run_id = _safe_identifier(run_id)
        self.max_spans = max(1, int(max_spans))
        self._resource_sampler = resource_sampler or collect_resource_snapshot
        self._resource_sample_interval_seconds = max(
            0.0, float(resource_sample_interval_seconds)
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._spans: list[dict[str, Any]] = []
        self._dropped_span_count = 0
        self._phase_totals: dict[str, float] = defaultdict(float)
        self._phase_units: dict[str, float] = defaultdict(float)
        self._phase_counts: Counter[str] = Counter()
        self._cache_hits: Counter[str] = Counter()
        self._cache_misses: Counter[str] = Counter()
        self._cycle_span: Optional[RuntimeSpan] = None
        self._active_phase_span: Optional[RuntimeSpan] = None
        self._active_sample_spans: dict[tuple[str, str], RuntimeSpan] = {}
        self._last_resource_snapshot: Optional[ResourceSnapshot] = None
        self._last_resource_sample_monotonic = 0.0

    def _snapshot(self, queue_depth: int) -> ResourceSnapshot:
        sample_now = time.monotonic()
        with self._lock:
            if (
                self._last_resource_snapshot is not None
                and sample_now - self._last_resource_sample_monotonic
                < self._resource_sample_interval_seconds
            ):
                return replace(
                    self._last_resource_snapshot,
                    queue_depth=max(0, int(queue_depth)),
                )
        try:
            try:
                value = self._resource_sampler(queue_depth=queue_depth)
            except TypeError:
                value = self._resource_sampler()
            if isinstance(value, ResourceSnapshot):
                snapshot = value
            else:
                payload = dict(value)
                allowed = {name for name in ResourceSnapshot.__dataclass_fields__}
                payload = {key: item for key, item in payload.items() if key in allowed}
                payload.setdefault("captured_at", _utc_now())
                payload.setdefault("queue_depth", max(0, int(queue_depth)))
                snapshot = ResourceSnapshot(**payload)
        except Exception:
            snapshot = ResourceSnapshot(
                captured_at=_utc_now(),
                cpu_percent=None,
                process_cpu_percent=None,
                memory_used_bytes=None,
                memory_percent=None,
                process_memory_bytes=None,
                swap_used_bytes=None,
                swap_percent=None,
                gpu_utilization_percent=None,
                gpu_memory_used_bytes=None,
                gpu_memory_total_bytes=None,
                gpu_memory_percent=None,
                gpu_device_count=0,
                gpu_telemetry_available=False,
                cuda_available=None,
                child_process_count=0,
                queue_depth=max(0, int(queue_depth)),
                collector_status="collector_error",
            )
        with self._lock:
            self._last_resource_snapshot = snapshot
            self._last_resource_sample_monotonic = sample_now
        return replace(snapshot, queue_depth=max(0, int(queue_depth)))

    def start_span(
        self,
        phase: str,
        *,
        cycle: Optional[int] = None,
        sample_id: str = "",
        unit_count: float = 0.0,
        cache_hit: Optional[bool] = None,
        attributes: Optional[Mapping[str, Any]] = None,
        queue_depth: int = 0,
        parent_span_id: str = "",
    ) -> RuntimeSpan:
        return RuntimeSpan(
            phase=phase,
            cycle=cycle,
            sample_id=sample_id,
            unit_count=unit_count,
            cache_hit=cache_hit,
            attributes=attributes or {},
            queue_depth=queue_depth,
            parent_span_id=parent_span_id,
            resource_start=self._snapshot(queue_depth),
            clock=self._clock,
        )

    def finish_span(
        self,
        span: RuntimeSpan,
        *,
        status: str = "ok",
        error_type: str = "",
        unit_count: Optional[float] = None,
        cache_hit: Optional[bool] = None,
        attributes: Optional[Mapping[str, Any]] = None,
        queue_depth: Optional[int] = None,
    ) -> dict[str, Any]:
        ended_monotonic = self._clock()
        duration = max(0.0, ended_monotonic - span.started_monotonic)
        units = span.unit_count if unit_count is None else max(0.0, _finite_float(unit_count))
        observed_cache_hit = span.cache_hit if cache_hit is None else cache_hit
        final_queue_depth = span.queue_depth if queue_depth is None else max(0, int(queue_depth))
        combined_attributes = dict(span.attributes)
        combined_attributes.update(sanitize_telemetry_attributes(attributes))
        if error_type:
            combined_attributes["error_type"] = _safe_identifier(error_type)
        resource_end = self._snapshot(final_queue_depth)
        record = {
            "schema_version": RUNTIME_TELEMETRY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "span_id": span.span_id,
            "parent_span_id": span.parent_span_id or None,
            "phase": span.phase,
            "scope": span.scope,
            "cycle": span.cycle,
            "sample_id": span.sample_id or None,
            "started_at": span.started_at,
            "ended_at": _utc_now(),
            "duration_seconds": round(duration, 9),
            "status": str(status or "unknown")[:64],
            "unit_count": round(units, 6),
            "throughput_per_second": round(units / duration, 9) if duration > 0 else 0.0,
            "cache_hit": observed_cache_hit,
            "resources_start": span.resource_start.to_dict(),
            "resources_end": resource_end.to_dict(),
            "attributes": combined_attributes,
        }
        with self._lock:
            self._phase_totals[span.phase] += duration
            self._phase_units[span.phase] += units
            self._phase_counts[span.phase] += 1
            if observed_cache_hit is True:
                self._cache_hits[span.phase] += 1
            elif observed_cache_hit is False:
                self._cache_misses[span.phase] += 1
            if len(self._spans) >= self.max_spans:
                self._spans.pop(0)
                self._dropped_span_count += 1
            self._spans.append(record)
        return record

    @contextmanager
    def span(self, phase: str, **kwargs: Any) -> Iterator[RuntimeSpan]:
        active = self.start_span(phase, **kwargs)
        try:
            yield active
        except BaseException as exc:
            self.finish_span(active, status="error", error_type=type(exc).__name__)
            raise
        else:
            self.finish_span(active)

    def record_instant(self, phase: str, **kwargs: Any) -> dict[str, Any]:
        span = self.start_span(phase, **kwargs)
        return self.finish_span(span)

    def record_cache_lookup(
        self,
        *,
        hit: bool,
        cycle: Optional[int] = None,
        sample_id: str = "",
        cache_kind: str = "",
        queue_depth: int = 0,
    ) -> dict[str, Any]:
        return self.record_instant(
            "cache_lookup",
            cycle=cycle,
            sample_id=sample_id,
            cache_hit=bool(hit),
            queue_depth=queue_depth,
            attributes={"cache_kind": cache_kind},
        )

    def start_cycle(self, cycle: int, *, queue_depth: int = 0) -> RuntimeSpan:
        with self._lock:
            if self._cycle_span is not None:
                self.end_cycle(status="superseded", queue_depth=queue_depth)
            self._cycle_span = self.start_span(
                "cycle",
                cycle=int(cycle),
                queue_depth=queue_depth,
                attributes={"phase_alias": "cycle"},
            )
            return self._cycle_span

    def transition_cycle_phase(
        self,
        phase: str,
        *,
        cycle: int,
        queue_depth: int = 0,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> RuntimeSpan:
        with self._lock:
            if self._cycle_span is None:
                self.start_cycle(cycle, queue_depth=queue_depth)
            if self._active_phase_span is not None:
                self.finish_span(self._active_phase_span, queue_depth=queue_depth)
            canonical = canonical_runtime_phase(phase)
            payload = {"phase_alias": str(phase)}
            payload.update(dict(attributes or {}))
            unit_count = _finite_float(payload.get("sample_count"), -1.0)
            if unit_count < 0.0:
                unit_count = max(
                    0.0,
                    _finite_float(payload.get("train_sample_count"))
                    + _finite_float(payload.get("validation_sample_count")),
                )
            if unit_count <= 0.0:
                unit_count = max(0.0, _finite_float(payload.get("epoch_count")))
            self._active_phase_span = self.start_span(
                canonical,
                cycle=cycle,
                unit_count=unit_count,
                queue_depth=queue_depth,
                attributes=payload,
                parent_span_id=self._cycle_span.span_id if self._cycle_span else "",
            )
            return self._active_phase_span

    def end_cycle(
        self,
        *,
        status: str = "ok",
        unit_count: float = 1.0,
        queue_depth: int = 0,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            if self._active_phase_span is not None:
                self.finish_span(self._active_phase_span, queue_depth=queue_depth)
                self._active_phase_span = None
            if self._cycle_span is None:
                return None
            record = self.finish_span(
                self._cycle_span,
                status=status,
                unit_count=unit_count,
                queue_depth=queue_depth,
            )
            self._cycle_span = None
            return record

    def observe_progress(
        self,
        progress: Mapping[str, Any],
        *,
        cycle: int,
        dataset: str = "",
        queue_depth: int = 0,
    ) -> None:
        """Convert existing compiler/bridge callbacks into sample/cache spans."""

        event = dict(progress)
        stage = str(event.get("stage") or "")
        block = str(event.get("block") or "")
        sample_id = _safe_identifier(event.get("sample_id") or event.get("metric_sample_id"))
        attributes = sanitize_telemetry_attributes(
            {**event, "dataset": dataset, "block": block, "stage": stage}
        )
        if "cache_hit" in stage:
            self.record_cache_lookup(
                hit=True,
                cycle=cycle,
                sample_id=sample_id,
                cache_kind=block,
                queue_depth=queue_depth,
            )
        elif "cache_miss" in stage:
            self.record_cache_lookup(
                hit=False,
                cycle=cycle,
                sample_id=sample_id,
                cache_kind=block,
                queue_depth=queue_depth,
            )

        if stage == "sample_start" and sample_id:
            phase = "bridge_evaluation" if block == "bridge_ir" else "compilation"
            key = (dataset, sample_id)
            with self._lock:
                stale = self._active_sample_spans.pop(key, None)
                if stale is not None:
                    self.finish_span(stale, status="superseded", queue_depth=queue_depth)
                self._active_sample_spans[key] = self.start_span(
                    phase,
                    cycle=cycle,
                    sample_id=sample_id,
                    unit_count=1,
                    queue_depth=queue_depth,
                    attributes=attributes,
                    parent_span_id=self._cycle_span.span_id if self._cycle_span else "",
                )
        elif stage in {
            "sample_done",
            "sample_cache_hit",
            "sample_failed",
            "sample_skipped",
            "sample_timeout",
        } and sample_id:
            key = (dataset, sample_id)
            with self._lock:
                active = self._active_sample_spans.pop(key, None)
            if active is not None:
                self.finish_span(
                    active,
                    status=(
                        "ok"
                        if stage in {"sample_done", "sample_cache_hit"}
                        else stage.removeprefix("sample_")
                    ),
                    queue_depth=queue_depth,
                    attributes=attributes,
                )
            if block == "compiler_ir":
                # These are explicit structural observations produced by the
                # compiler result; their zero-duration markers avoid inventing
                # sub-phase timing that the codec does not currently expose.
                for phase in ("decoding", "embeddings", *LEGAL_IR_VIEW_PHASES):
                    self.record_instant(
                        phase,
                        cycle=cycle,
                        sample_id=sample_id,
                        unit_count=1,
                        queue_depth=queue_depth,
                        attributes=attributes,
                        parent_span_id=self._cycle_span.span_id if self._cycle_span else "",
                    )
                if "validation" in dataset:
                    self.record_instant(
                        "validation",
                        cycle=cycle,
                        sample_id=sample_id,
                        unit_count=1,
                        queue_depth=queue_depth,
                        attributes=attributes,
                        parent_span_id=self._cycle_span.span_id if self._cycle_span else "",
                    )

    def close_open_spans(self, *, status: str = "cancelled", queue_depth: int = 0) -> None:
        with self._lock:
            sample_spans = list(self._active_sample_spans.values())
            self._active_sample_spans.clear()
        for span in sample_spans:
            self.finish_span(span, status=status, queue_depth=queue_depth)
        self.end_cycle(status=status, queue_depth=queue_depth)

    def to_dict(
        self,
        *,
        latest_cycle: Optional[int] = None,
        max_spans: Optional[int] = None,
    ) -> dict[str, Any]:
        with self._lock:
            matching_spans = [
                dict(record)
                for record in self._spans
                if latest_cycle is None or record.get("cycle") == latest_cycle
            ]
            phase_totals = dict(self._phase_totals)
            phase_units = dict(self._phase_units)
            phase_counts = dict(self._phase_counts)
            cache_hits = dict(self._cache_hits)
            cache_misses = dict(self._cache_misses)
            dropped = self._dropped_span_count

        retained_limit = None if max_spans is None else max(0, int(max_spans))
        spans = (
            matching_spans
            if retained_limit is None
            else matching_spans[-retained_limit:] if retained_limit else []
        )

        phase_metrics: dict[str, Any] = {}
        all_phases = sorted(set(phase_totals) | set(cache_hits) | set(cache_misses))
        for phase in all_phases:
            seconds = phase_totals.get(phase, 0.0)
            units = phase_units.get(phase, 0.0)
            hits = cache_hits.get(phase, 0)
            misses = cache_misses.get(phase, 0)
            lookups = hits + misses
            phase_metrics[phase] = {
                "span_count": phase_counts.get(phase, 0),
                "duration_seconds": round(seconds, 9),
                "unit_count": round(units, 6),
                "throughput_per_second": round(units / seconds, 9) if seconds else 0.0,
                "cache_hits": hits,
                "cache_misses": misses,
                "cache_hit_rate": round(hits / lookups, 9) if lookups else None,
            }

        # Headline resource statistics must continue to cover every matching
        # span even when the summary retains only a bounded diagnostic tail.
        resource_records = [
            record[boundary]
            for record in matching_spans
            for boundary in ("resources_start", "resources_end")
            if isinstance(record.get(boundary), Mapping)
        ]
        resources = _summarize_resources(resource_records)
        total_hits = sum(cache_hits.values())
        total_misses = sum(cache_misses.values())
        total_lookups = total_hits + total_misses
        return {
            "schema_version": RUNTIME_TELEMETRY_SCHEMA_VERSION,
            "resource_schema_version": RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "phase_catalog": list(RUNTIME_PHASES),
            "span_count": len(matching_spans),
            "retained_span_count": len(spans),
            "omitted_span_count": len(matching_spans) - len(spans),
            "dropped_span_count": dropped,
            "spans": spans,
            "phase_metrics": phase_metrics,
            "resources": resources,
            "cache_hits": total_hits,
            "cache_misses": total_misses,
            "cache_hit_rate": round(total_hits / total_lookups, 9) if total_lookups else None,
        }

    summary = to_dict


def _summarize_resources(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    numeric_fields = (
        "cpu_percent",
        "process_cpu_percent",
        "memory_used_bytes",
        "memory_percent",
        "process_memory_bytes",
        "swap_used_bytes",
        "swap_percent",
        "gpu_utilization_percent",
        "gpu_memory_used_bytes",
        "gpu_memory_total_bytes",
        "gpu_memory_percent",
        "gpu_device_count",
        "process_gpu_memory_used_bytes",
        "children_gpu_memory_used_bytes",
        "trainer_gpu_memory_used_bytes",
        "leanstral_gpu_memory_used_bytes",
        "unified_memory_used_bytes",
        "unified_memory_percent",
        "process_unified_memory_used_bytes",
        "children_unified_memory_used_bytes",
        "trainer_unified_memory_used_bytes",
        "leanstral_unified_memory_used_bytes",
        "child_process_count",
        "queue_depth",
    )
    summary: dict[str, Any] = {"snapshot_count": len(records)}
    for field in numeric_fields:
        values = [
            float(record[field])
            for record in records
            if isinstance(record.get(field), (int, float))
        ]
        summary[f"{field}_average"] = round(sum(values) / len(values), 3) if values else None
        summary[f"{field}_peak"] = round(max(values), 3) if values else None
    summary["gpu_telemetry_available"] = any(
        record.get("gpu_telemetry_available") is True for record in records
    )
    summary["cuda_available"] = (
        True
        if any(record.get("cuda_available") is True for record in records)
        else False
        if records and all(record.get("cuda_available") is False for record in records)
        else None
    )
    summary["collector_statuses"] = sorted(
        {
            status
            for record in records
            for status in str(record.get("collector_status") or "").split(",")
            if status
        }
    )
    summary["latest"] = dict(records[-1]) if records else None
    return summary


def attach_runtime_telemetry(
    summary: dict[str, Any],
    telemetry: RuntimeTelemetry,
    *,
    cycle: Optional[int] = None,
) -> dict[str, Any]:
    """Attach the stable telemetry block and convenient headline metrics."""

    # Metric progress events already live in the append-only run log. Keeping
    # every resource-rich span in each frequently rewritten summary caused
    # multi-gigabyte write amplification on short smoke runs.
    block = telemetry.to_dict(latest_cycle=cycle, max_spans=64)
    summary["runtime_telemetry_schema_version"] = RUNTIME_TELEMETRY_SCHEMA_VERSION
    summary["runtime_resource_telemetry_schema_version"] = (
        RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION
    )
    summary["runtime_phase_catalog"] = list(RUNTIME_PHASES)
    summary["runtime_telemetry"] = block
    latest_block = dict(block)
    latest_block["spans"] = list(block["spans"][-8:])
    latest_block["retained_span_count"] = len(latest_block["spans"])
    latest_block["omitted_span_count"] = max(
        0,
        int(block["span_count"]) - latest_block["retained_span_count"],
    )
    summary["latest_runtime_phase_telemetry"] = latest_block
    summary["latest_runtime_resources"] = block["resources"]
    summary["runtime_cache_hit_rate"] = block["cache_hit_rate"]
    return block


PhaseTelemetry = RuntimeTelemetry
RuntimePhaseTelemetry = RuntimeTelemetry


__all__ = [
    "LEGAL_IR_VIEW_PHASES",
    "PhaseTelemetry",
    "REQUIRED_RUNTIME_PHASES",
    "RUNTIME_PHASES",
    "RUNTIME_PHASE_TELEMETRY_SCHEMA_VERSION",
    "RUNTIME_RESOURCE_TELEMETRY_SCHEMA_VERSION",
    "RUNTIME_TELEMETRY_SCHEMA_VERSION",
    "ResourceSnapshot",
    "RuntimePhaseTelemetry",
    "RuntimeSpan",
    "RuntimeTelemetry",
    "attach_runtime_telemetry",
    "canonical_runtime_phase",
    "collect_resource_snapshot",
    "sanitize_telemetry_attributes",
]
