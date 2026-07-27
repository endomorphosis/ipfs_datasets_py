"""Prepare and launch the semantic round-trip dynamic bundle scheduler.

The generic objective daemon creates a bundle index while deriving new tasks
from an objective heap.  The semantic round-trip board is deliberately
hand-authored, so this module provides the narrower missing projection:

``existing taskboard -> queryable bundle index -> DynamicBundleScheduler``.

It does not implement another scheduler.  Launches are delegated to
``ipfs_accelerate_py.agent_supervisor.bundle_supervisor`` so leases, conflict
checks, worktree isolation, provider admission, and recovery retain their
normal authority.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_dag_json
from ipfs_accelerate_py.agent_supervisor.artifact_store import (
    write_bundle_index_artifact,
)
from ipfs_accelerate_py.agent_supervisor.objective_graph import (
    materialize_task_planning_graph,
)
from ipfs_accelerate_py.agent_supervisor.resource_scheduler import (
    LEGACY_RESOURCE_CLASSES,
    PROOF_RESOURCE_CLASSES,
    ProofResourceClass,
    normalize_adaptive_stage,
    normalize_resource_class,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    PortalTask,
    parse_task_file,
    split_csv,
)


CONFIG_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.scheduler_config@1"
)
BUNDLE_INDEX_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.taskboard_bundle_index@1"
)
PROVIDER_CAPACITY_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.provider_capacity@1"
)
DEFAULT_TASK_PREFIX = "## SRT-"
DEFAULT_RUNTIME_ROOT = Path("/var/tmp/hssl-srt-dynamic-supervisor")
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "semantic_roundtrip_scheduler.json"
)
SUPPORTED_RESOURCE_CLASSES = frozenset(
    {*LEGACY_RESOURCE_CLASSES, *PROOF_RESOURCE_CLASSES}
)
TERMINAL_STATUSES = frozenset(
    {"complete", "completed", "done", "merged", "passed", "success", "succeeded"}
)
BLOCKED_STATUSES = frozenset({"blocked", "on_hold"})


class SchedulerPreparationError(ValueError):
    """Raised when scheduler inputs cannot fail closed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SchedulerPreparationError(f"invalid boolean value {value!r}")


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise SchedulerPreparationError(
            f"taskboard must be inside the repository: {path}"
        ) from exc


def load_scheduler_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the committed scheduler configuration."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchedulerPreparationError("scheduler config must be a JSON object")
    if payload.get("schema") != CONFIG_SCHEMA:
        raise SchedulerPreparationError(
            f"unsupported scheduler config schema {payload.get('schema')!r}"
        )
    provider = payload.get("provider")
    if not isinstance(provider, dict):
        raise SchedulerPreparationError("scheduler config requires provider")
    if str(provider.get("provider_id") or "").strip().lower() != "leanstral-local":
        raise SchedulerPreparationError(
            "semantic round-trip provider_id must be leanstral-local"
        )
    if int(provider.get("max_concurrency") or 0) != 1:
        raise SchedulerPreparationError(
            "Leanstral provider max_concurrency must be exactly one"
        )
    return payload


def resolve_taskboard(
    repo_root: Path,
    config: Mapping[str, Any],
    taskboard_path: Path | None = None,
) -> Path:
    raw = taskboard_path or Path(str(config.get("taskboard_path") or ""))
    path = raw if raw.is_absolute() else repo_root / raw
    path = path.resolve()
    if not path.is_file():
        raise SchedulerPreparationError(f"taskboard does not exist: {path}")
    _repo_relative(repo_root, path)
    return path


def _normalized_metadata(task: PortalTask) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        _canonical_field_name(key): value
        for key, value in task.metadata.items()
    }
    list_fields = {
        "allow_concurrent_with",
        "ast_symbols",
        "changed_paths",
        "effects",
        "generated_artifacts",
        "interfaces",
        "predicted_files",
        "required_capabilities",
        "required_tools",
        "submodules",
    }
    for field in list_fields:
        if field in metadata:
            metadata[field] = split_csv(str(metadata[field]))
    for field in (
        "estimated_context_tokens",
        "estimated_tokens",
        "gpu_memory_bytes",
        "memory_bytes",
        "process_slots",
        "required_context_tokens",
        "token_budget",
    ):
        if field in metadata:
            metadata[field] = _parse_int(metadata[field])
    for field in ("is_schedulable", "requires_provider", "review_only"):
        if field in metadata:
            metadata[field] = _parse_bool(metadata[field])
    return metadata


def _task_resource_binding(
    task: PortalTask,
    *,
    provider_id: str,
) -> tuple[str, str, str, bool]:
    metadata = _normalized_metadata(task)
    resource_class = normalize_resource_class(metadata.get("resource_class"))
    resource_stage = normalize_adaptive_stage(
        metadata.get("resource_stage") or "analysis"
    )
    task_provider = str(
        metadata.get("provider_id")
        or metadata.get("llm_provider")
        or ""
    ).strip().lower()
    requires_provider = _parse_bool(
        metadata.get("requires_provider"),
        bool(task_provider),
    )

    if resource_class not in SUPPORTED_RESOURCE_CLASSES:
        raise SchedulerPreparationError(
            f"{task.task_id}: unsupported resource class {resource_class!r}; "
            f"choose one of {', '.join(sorted(SUPPORTED_RESOURCE_CLASSES))}"
        )
    is_model_lane = (
        resource_class == ProofResourceClass.MODEL_DRAFT.value
        or task_provider
        or requires_provider
    )
    if is_model_lane:
        if resource_class != ProofResourceClass.MODEL_DRAFT.value:
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must use "
                f"{ProofResourceClass.MODEL_DRAFT.value!r}"
            )
        if resource_stage != "inference":
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must use resource stage 'inference'"
            )
        if task_provider != provider_id:
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must bind {provider_id!r}"
            )
        if not requires_provider:
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must declare Requires provider: true"
            )
    elif resource_stage == "inference":
        raise SchedulerPreparationError(
            f"{task.task_id}: inference work must bind a provider"
        )
    return resource_class, resource_stage, task_provider, requires_provider


def validate_taskboard_for_dynamic_scheduler(
    tasks: Sequence[PortalTask],
    *,
    provider_id: str = "leanstral-local",
) -> None:
    """Fail closed on metadata that would bypass scheduler admission."""

    if not tasks:
        raise SchedulerPreparationError("taskboard contains no tasks")
    bundle_bindings: dict[str, set[tuple[str, str, str, bool]]] = defaultdict(set)
    bundle_lanes: dict[str, set[str]] = defaultdict(set)
    seen_ids: set[str] = set()
    for task in tasks:
        if task.task_id in seen_ids:
            raise SchedulerPreparationError(f"duplicate task ID {task.task_id}")
        seen_ids.add(task.task_id)
        metadata = _normalized_metadata(task)
        bundle_key = str(metadata.get("bundle") or "").strip()
        parallel_lane = str(metadata.get("parallel_lane") or "").strip()
        if not bundle_key:
            raise SchedulerPreparationError(f"{task.task_id}: Bundle is required")
        if not parallel_lane:
            raise SchedulerPreparationError(
                f"{task.task_id}: Parallel lane is required"
            )
        binding = _task_resource_binding(task, provider_id=provider_id)
        bundle_bindings[bundle_key].add(binding)
        bundle_lanes[bundle_key].add(parallel_lane)

    unknown_dependencies = {
        dependency
        for task in tasks
        for dependency in task.depends_on
        if dependency not in seen_ids
    }
    if unknown_dependencies:
        raise SchedulerPreparationError(
            "unknown task dependencies: " + ", ".join(sorted(unknown_dependencies))
        )
    for bundle_key, lanes in sorted(bundle_lanes.items()):
        if len(lanes) != 1:
            raise SchedulerPreparationError(
                f"bundle {bundle_key!r} spans multiple parallel lanes: "
                + ", ".join(sorted(lanes))
            )
        if len(bundle_bindings[bundle_key]) != 1:
            raise SchedulerPreparationError(
                f"bundle {bundle_key!r} mixes resource/provider bindings; "
                "split independently schedulable work into distinct bundles"
            )


def _task_payload(
    task: PortalTask,
    *,
    provider_id: str,
) -> dict[str, Any]:
    metadata = _normalized_metadata(task)
    resource_class, resource_stage, task_provider, requires_provider = (
        _task_resource_binding(task, provider_id=provider_id)
    )
    status = str(task.status or "todo").strip().lower()
    is_schedulable = (
        _parse_bool(metadata.get("is_schedulable"), True)
        and status not in TERMINAL_STATUSES
        and status not in BLOCKED_STATUSES
    )
    review_only = _parse_bool(metadata.get("review_only"), False)
    return {
        **metadata,
        "task_id": task.task_id,
        "title": task.title,
        "status": status,
        "completion": task.completion,
        "priority": task.priority,
        "track": task.track,
        "depends_on": list(task.depends_on),
        "dependency_task_ids": list(task.depends_on),
        "outputs": list(task.outputs),
        "validation": list(task.validation),
        "acceptance": task.acceptance,
        "source_line": task.source_line,
        "board_namespace": task.board_namespace,
        "canonical_task_key": task.canonical_task_key,
        "canonical_task_cid": task.canonical_task_cid,
        "resource_class": resource_class,
        "resource_stage": resource_stage,
        "provider_id": task_provider,
        "llm_provider": task_provider,
        "requires_provider": requires_provider,
        "is_schedulable": is_schedulable,
        "review_only": review_only,
        "execution_authority": "agent-supervisor/v1",
    }


def build_taskboard_bundle_index(
    *,
    repo_root: Path,
    taskboard_path: Path,
    bundle_index_path: Path,
    task_prefix: str = DEFAULT_TASK_PREFIX,
    provider_id: str = "leanstral-local",
) -> dict[str, Any]:
    """Write the supervisor's queryable JSON/DuckDB bundle-index artifact."""

    repo_root = repo_root.resolve()
    taskboard_path = taskboard_path.resolve()
    tasks = parse_task_file(taskboard_path, task_prefix)
    validate_taskboard_for_dynamic_scheduler(tasks, provider_id=provider_id)
    source_todo = _repo_relative(repo_root, taskboard_path)
    source_todo_raw_cid = cid_for_bytes(taskboard_path.read_bytes())
    task_payloads = [
        _task_payload(task, provider_id=provider_id)
        for task in tasks
    ]
    task_cids_by_id = {
        str(task["task_id"]): str(task["canonical_task_cid"])
        for task in task_payloads
    }
    for task in task_payloads:
        task["dependency_task_cids"] = [
            task_cids_by_id[dependency_id]
            for dependency_id in task["depends_on"]
        ]
    planning_graph = materialize_task_planning_graph(
        task_payloads,
        repo_root=repo_root,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in task_payloads:
        grouped[str(task["bundle"])].append(task)

    bundles: dict[str, Any] = {}
    for bundle_key, members in sorted(grouped.items()):
        first = members[0]
        schedulable = [
            member
            for member in members
            if member["is_schedulable"] and not member["review_only"]
        ]
        bundles[bundle_key] = {
            "bundle_key": bundle_key,
            # Each lane receives an immutable runtime copy and an authorized
            # execution slice, so all bundles may safely reference the same
            # protected source board.
            "shard_path": source_todo,
            "parallel_lane": first["parallel_lane"],
            "conflict_policy": first.get("conflict_policy", ""),
            "bundle_strategy": "taskboard-declared",
            "execution_authority": "agent-supervisor/v1",
            "resource_class": first["resource_class"],
            "resource_stage": first["resource_stage"],
            "provider_id": first["provider_id"],
            "llm_provider": first["llm_provider"],
            "requires_provider": first["requires_provider"],
            "is_schedulable": bool(schedulable),
            "review_only": bool(members)
            and all(bool(member["review_only"]) for member in members),
            "tasks": members,
        }

    payload = {
        "schema": BUNDLE_INDEX_SCHEMA,
        "generated_at": _utc_now(),
        "source_todo": source_todo,
        "source_todo_raw_cid": source_todo_raw_cid,
        "source_todo_cid_codec": "raw",
        "task_prefix": task_prefix,
        "execution_authority": "agent-supervisor/v1",
        "bundles": bundles,
        "task_dependency_graph": planning_graph.dependency_graph.to_dict(),
        "dependency_dag": planning_graph.dependency_graph.to_dict(),
        "task_conflict_graph": planning_graph.conflict_graph.to_dict(),
        "conflict_graph": planning_graph.conflict_graph.to_dict(),
        "task_planning_graph": planning_graph.to_dict(),
    }
    bundle_index_path.parent.mkdir(parents=True, exist_ok=True)
    write_bundle_index_artifact(bundle_index_path, payload)
    return payload


def _http_json(url: str, timeout_seconds: float) -> tuple[object, int]:
    started = time.monotonic_ns()
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        status = int(getattr(response, "status", 200))
        body = response.read()
    elapsed_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
    payload = json.loads(body.decode("utf-8"))
    if status < 200 or status >= 300:
        raise SchedulerPreparationError(f"{url} returned HTTP {status}")
    return payload, elapsed_ms


def _probe_mapping(value: object, endpoint: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchedulerPreparationError(
            f"{endpoint} returned non-object JSON"
        )
    return value


def _slot_rows(value: object) -> list[Mapping[str, Any]]:
    """Return a strict llama.cpp ``/slots`` observation.

    Current llama.cpp exposes a top-level array.  A mapping containing a
    ``slots`` array is accepted for compatible reverse proxies, but every
    slot must expose the authoritative boolean ``is_processing`` field.
    Guessing from a task identifier would incorrectly reserve idle
    prompt-cache slots.
    """

    raw_slots: object
    if isinstance(value, list):
        raw_slots = value
    elif isinstance(value, Mapping):
        raw_slots = value.get("slots")
    else:
        raw_slots = None
    if not isinstance(raw_slots, list) or not raw_slots:
        raise SchedulerPreparationError(
            "slots probe must return a nonempty slot array"
        )
    slots: list[Mapping[str, Any]] = []
    for index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, Mapping):
            raise SchedulerPreparationError(
                f"slots[{index}] must be an object"
            )
        if type(raw_slot.get("is_processing")) is not bool:
            raise SchedulerPreparationError(
                f"slots[{index}].is_processing must be boolean"
            )
        slots.append(raw_slot)
    return slots


def probe_provider_capacity(
    provider_config: Mapping[str, Any],
    *,
    http_json: Callable[[str, float], tuple[object, int]] = _http_json,
) -> dict[str, Any]:
    """Probe the exact local Leanstral identity and emit fail-closed telemetry."""

    provider_id = str(provider_config.get("provider_id") or "").strip().lower()
    base_url = str(provider_config.get("base_url") or "").rstrip("/")
    expected_model = str(provider_config.get("model_id") or "").strip()
    timeout_seconds = float(provider_config.get("timeout_seconds") or 5)
    max_concurrency = int(provider_config.get("max_concurrency") or 0)
    if provider_id != "leanstral-local" or max_concurrency != 1:
        raise SchedulerPreparationError(
            "provider capacity must bind leanstral-local at max_concurrency one"
        )
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 10
    ):
        raise SchedulerPreparationError(
            "provider probe timeout_seconds must be in the bounded range (0, 10]"
        )
    errors: list[str] = []
    healthy = False
    latency_ms = 0
    model_ids: list[str] = []
    capabilities: list[str] = []
    context_window_tokens = -1
    reported_total_slots = -1
    observed_slot_count = -1
    active_requests = max_concurrency
    slot_ids: list[int] = []
    model_alias = ""
    build_info = ""
    try:
        health_value, health_latency = http_json(
            base_url + str(provider_config.get("health_path") or "/health"),
            timeout_seconds,
        )
        health = _probe_mapping(health_value, "health probe")
        latency_ms = max(latency_ms, health_latency)
        if str(health.get("status") or "").strip().lower() not in {
            "ok",
            "ready",
            "healthy",
            "up",
        }:
            errors.append("health_status_not_ready")
    except Exception as exc:  # The artifact records the exact failed preflight.
        errors.append(f"health_probe:{type(exc).__name__}:{exc}")

    try:
        models_value, model_latency = http_json(
            base_url + str(provider_config.get("models_path") or "/v1/models"),
            timeout_seconds,
        )
        models = _probe_mapping(models_value, "model probe")
        latency_ms = max(latency_ms, model_latency)
        raw_models = models.get("data") or models.get("models") or []
        for item in raw_models if isinstance(raw_models, list) else []:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "")
            if model_id:
                model_ids.append(model_id)
            for capability in item.get("capabilities") or ():
                value = str(capability).strip().lower()
                if value and value not in capabilities:
                    capabilities.append(value)
            meta = item.get("meta") if isinstance(item.get("meta"), Mapping) else {}
            context_window_tokens = max(
                context_window_tokens,
                _parse_int(
                    meta.get("n_ctx")
                    or item.get("context_window_tokens")
                    or item.get("context_length"),
                    0,
                ),
            )
        if expected_model not in model_ids:
            errors.append("configured_model_not_served")
    except Exception as exc:
        errors.append(f"model_probe:{type(exc).__name__}:{exc}")

    try:
        props_value, props_latency = http_json(
            base_url + str(provider_config.get("props_path") or "/props"),
            timeout_seconds,
        )
        props = _probe_mapping(props_value, "props probe")
        latency_ms = max(latency_ms, props_latency)
        reported_total_slots = _parse_int(props.get("total_slots"), 0)
        model_alias = str(props.get("model_alias") or "").strip()
        build_info = str(props.get("build_info") or "").strip()
        defaults = (
            props.get("default_generation_settings")
            if isinstance(props.get("default_generation_settings"), Mapping)
            else {}
        )
        props_context = _parse_int(defaults.get("n_ctx"), 0)
        if props_context:
            context_window_tokens = props_context
        if reported_total_slots != max_concurrency:
            errors.append("configured_capacity_mismatch")
        if model_alias != expected_model:
            errors.append("props_model_alias_mismatch")
        if context_window_tokens <= 0:
            errors.append("props_context_window_missing")
    except Exception as exc:
        errors.append(f"props_probe:{type(exc).__name__}:{exc}")

    try:
        slots_value, slots_latency = http_json(
            base_url + str(provider_config.get("slots_path") or "/slots"),
            timeout_seconds,
        )
        latency_ms = max(latency_ms, slots_latency)
        slots = _slot_rows(slots_value)
        observed_slot_count = len(slots)
        active_requests = sum(
            1 for slot in slots if bool(slot["is_processing"])
        )
        if observed_slot_count != max_concurrency:
            errors.append("observed_slot_count_mismatch")
        if active_requests > max_concurrency:
            errors.append("active_request_count_exceeds_capacity")
        for index, slot in enumerate(slots):
            raw_id = slot.get("id", index)
            if (
                not isinstance(raw_id, int)
                or isinstance(raw_id, bool)
                or raw_id < 0
            ):
                raise SchedulerPreparationError(
                    f"slots[{index}].id must be a nonnegative integer"
                )
            slot_ids.append(raw_id)
        if len(slot_ids) != len(set(slot_ids)):
            errors.append("duplicate_slot_ids")
    except Exception as exc:
        # Unknown occupancy must reserve the whole configured capacity even
        # though ``healthy`` also fails closed.  This prevents a downstream
        # scheduler that inspects capacity before health from admitting work.
        active_requests = max_concurrency
        observed_slot_count = -1
        slot_ids = []
        errors.append(f"slots_probe:{type(exc).__name__}:{exc}")

    healthy = not errors
    observed_at_ms = int(time.time() * 1_000)
    cid_payload = {
        "schema": PROVIDER_CAPACITY_SCHEMA,
        "generated_at": _utc_now(),
        "provider_endpoint": base_url,
        "configured_model_id": expected_model,
        "probe_errors": errors,
        "providers": {
            provider_id: {
                "provider_id": provider_id,
                "healthy": healthy,
                "max_concurrency": max_concurrency,
                "active_requests": active_requests,
                "available_concurrency": max(
                    0, max_concurrency - active_requests
                ),
                "observed_slot_count": observed_slot_count,
                "slot_ids": slot_ids,
                "latency_ms": latency_ms,
                "context_window_tokens": context_window_tokens,
                "capabilities": capabilities,
                "observed_at_ms": observed_at_ms,
                "model_ids": sorted(set(model_ids)),
                "model_alias": model_alias,
                "reported_total_slots": reported_total_slots,
                "backend_build_info": build_info,
            }
        },
    }
    return {
        **cid_payload,
        "provider_capacity_cid": cid_for_dag_json(cid_payload),
        "provider_capacity_cid_codec": "dag-json",
        "provider_capacity_cid_scope": "payload_without_cid_fields",
    }


def write_provider_capacity(
    path: Path,
    provider_config: Mapping[str, Any],
    *,
    http_json: Callable[[str, float], tuple[object, int]] = _http_json,
) -> dict[str, Any]:
    payload = probe_provider_capacity(provider_config, http_json=http_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def prepare_scheduler_inputs(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    taskboard_path: Path | None = None,
    http_json: Callable[[str, float], tuple[object, int]] = _http_json,
) -> dict[str, Any]:
    """Build fresh index and provider telemetry without starting workers."""

    repo_root = repo_root.resolve()
    config = load_scheduler_config(config_path.resolve())
    taskboard = resolve_taskboard(repo_root, config, taskboard_path)
    runtime_root = runtime_root.resolve()
    bundle_index_path = runtime_root / "bundles" / "index.json"
    provider_capacity_path = runtime_root / "provider_capacity.json"
    provider_config = config["provider"]
    index = build_taskboard_bundle_index(
        repo_root=repo_root,
        taskboard_path=taskboard,
        bundle_index_path=bundle_index_path,
        task_prefix=str(config.get("task_prefix") or DEFAULT_TASK_PREFIX),
        provider_id=str(provider_config["provider_id"]).strip().lower(),
    )
    capacity = write_provider_capacity(
        provider_capacity_path,
        provider_config,
        http_json=http_json,
    )
    return {
        "schema": "ipfs_datasets_py.benchmarks.semantic_roundtrip.scheduler_preparation@1",
        "generated_at": _utc_now(),
        "repo_root": str(repo_root),
        "taskboard_path": str(taskboard),
        "taskboard_raw_cid": cid_for_bytes(taskboard.read_bytes()),
        "taskboard_cid_codec": "raw",
        "runtime_root": str(runtime_root),
        "bundle_index_path": str(bundle_index_path),
        "bundle_index_duckdb_path": str(bundle_index_path.with_suffix(".duckdb")),
        "provider_capacity_path": str(provider_capacity_path),
        "provider_capacity_cid": str(capacity["provider_capacity_cid"]),
        "provider_capacity_cid_codec": "dag-json",
        "bundle_count": len(index["bundles"]),
        "task_count": sum(
            len(bundle["tasks"]) for bundle in index["bundles"].values()
        ),
        "provider_healthy": bool(
            capacity["providers"][provider_config["provider_id"]]["healthy"]
        ),
        "provider_max_concurrency": int(
            capacity["providers"][provider_config["provider_id"]][
                "max_concurrency"
            ]
        ),
        "provider_probe_errors": list(capacity["probe_errors"]),
    }


def _current_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        raise SchedulerPreparationError(
            "scheduler launch requires a named merge-target branch"
        )
    return branch


def build_bundle_supervisor_command(
    preparation: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    implement: bool = True,
    max_lanes: int | None = None,
    start: bool = True,
) -> list[str]:
    """Return the supported bundle-supervisor CLI invocation."""

    repo_root = Path(str(preparation["repo_root"])).resolve()
    runtime_root = Path(str(preparation["runtime_root"])).resolve()
    lanes = int(max_lanes or config.get("max_lanes") or 1)
    if lanes < 1:
        raise SchedulerPreparationError("max_lanes must be positive")
    command = [
        sys.executable,
        "-m",
        "ipfs_accelerate_py.agent_supervisor.bundle_supervisor",
        "--bundle-index-path",
        str(preparation["bundle_index_path"]),
        "--repo-root",
        str(repo_root),
        "--state-root",
        str(runtime_root / "state"),
        "--worktree-root",
        str(runtime_root / "worktrees"),
        "--log-dir",
        str(runtime_root / "logs"),
        "--manifest-path",
        str(runtime_root / "bundle_lanes.json"),
        "--metrics-path",
        str(runtime_root / "scheduler_metrics.json"),
        "--coordination-path",
        str(runtime_root / "coordination.duckdb"),
        "--provider-capacity-path",
        str(preparation["provider_capacity_path"]),
        "--task-prefix",
        str(config.get("task_prefix") or DEFAULT_TASK_PREFIX),
        "--max-lanes",
        str(lanes),
        "--poll-interval",
        str(config.get("poll_interval_seconds") or 5),
        "--daemon-interval",
        str(config.get("daemon_interval_seconds") or 300),
        "--stale-seconds",
        str(config.get("stale_seconds") or 1800),
        "--check-interval",
        str(config.get("check_interval_seconds") or 60),
        "--max-restarts",
        str(config.get("max_restarts") or 0),
        "--max-task-attempts",
        str(config.get("max_task_attempts") or 0),
        "--implementation-timeout",
        str(config.get("implementation_timeout_seconds") or 1800),
        "--merge-target-branch",
        _current_branch(repo_root),
    ]
    for submodule_path in config.get("worktree_submodule_paths") or ():
        command.extend(["--worktree-submodule-path", str(submodule_path)])
    command.append("--implement" if implement else "--no-implement")
    if start:
        command.append("--start")
    return command


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the semantic round-trip taskboard into a bundle index and "
            "delegate execution to DynamicBundleScheduler"
        )
    )
    parser.add_argument(
        "action",
        choices=("validate", "prepare", "plan", "launch"),
        nargs="?",
        default="prepare",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--taskboard-path", type=Path, default=None)
    parser.add_argument("--max-lanes", type=int, default=None)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="For launch, replace this process with the persistent scheduler",
    )
    parser.add_argument(
        "--no-implement",
        dest="implement",
        action="store_false",
        help="Plan/start reconciliation supervisors without implementation agents",
    )
    parser.set_defaults(implement=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    config = load_scheduler_config(args.config_path.resolve())
    taskboard = resolve_taskboard(repo_root, config, args.taskboard_path)
    if args.action == "validate":
        tasks = parse_task_file(
            taskboard,
            str(config.get("task_prefix") or DEFAULT_TASK_PREFIX),
        )
        validate_taskboard_for_dynamic_scheduler(
            tasks,
            provider_id=str(config["provider"]["provider_id"]),
        )
        print(
            json.dumps(
                {
                    "valid": True,
                    "task_count": len(tasks),
                    "taskboard_path": str(taskboard),
                },
                sort_keys=True,
            )
        )
        return 0

    preparation = prepare_scheduler_inputs(
        repo_root=repo_root,
        config_path=args.config_path,
        runtime_root=args.runtime_root,
        taskboard_path=taskboard,
    )
    if args.action == "prepare":
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return 0

    command = build_bundle_supervisor_command(
        preparation,
        config,
        implement=args.implement,
        max_lanes=args.max_lanes,
        start=args.action == "launch",
    )
    if args.action == "plan":
        # Omitting --start uses the supervisor's side-effect-free lane planner.
        completed = subprocess.run(command, cwd=repo_root, check=False)
        return int(completed.returncode)

    if not args.execute:
        print(shlex.join(command))
        return 0
    os.execvpe(command[0], command, os.environ.copy())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
