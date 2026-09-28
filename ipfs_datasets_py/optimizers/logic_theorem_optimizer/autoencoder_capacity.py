"""Read-only dispatch estimates; resource leases remain the admission authority.

Logical lanes and immutable optimizer settings are deliberately absent. This
planner limits concurrent independent passes, never epochs, context, or backend.
Callers inside a reserved envelope must omit scheduler-available limits: that
envelope has already been charged to the host scheduler.
"""
from __future__ import annotations

import math
import json
import os
from pathlib import Path
from typing import Mapping

MIB = 1024 * 1024


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("invalid " + name)
    return value


def _read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def _unescape_mount(value):
    for encoded, decoded in ((r"\040", " "), (r"\011", "\t"), (r"\012", "\n"), (r"\134", "\\")):
        value = value.replace(encoded, decoded)
    return value


def _cgroup_paths(proc_root, *, mount_prefix=None):
    """Find this process's v1/v2 groups and their visible ancestors."""
    groups, result = {}, []
    for line in (_read(Path(proc_root) / "self/cgroup") or "").splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3:
            groups[fields[1]] = fields[2]
    for line in (_read(Path(proc_root) / "self/mountinfo") or "").splitlines():
        left, separator, right = line.partition(" - ")
        before, after = left.split(), right.split()
        if not separator or len(before) < 5 or len(after) < 3 or after[0] not in {"cgroup", "cgroup2"}:
            continue
        controllers = set(after[2].split(","))
        for key, group in groups.items():
            if (after[0] == "cgroup2" and key) or (after[0] == "cgroup" and not controllers.intersection(key.split(","))):
                continue
            root = Path(_unescape_mount(before[3]))
            mount = Path(_unescape_mount(before[4]))
            # In a cgroup namespace, '/' is relative to the mounted group.
            try:
                relative = Path(group).relative_to(root)
            except ValueError:
                if group != "/":
                    continue
                relative = Path(".")
            if mount_prefix is not None:
                mount = Path(mount_prefix) / str(mount).lstrip("/")
            current = mount / relative
            while True:
                result.append((after[0], key, current))
                if current == mount:
                    break
                current = current.parent
    return result


def hardware_probe(*, proc_root="/proc", mount_prefix=None):
    """Observe affinity, inherited cgroup limits and currently available RAM.

    Missing host memory telemetry fails closed in ``capacity_plan``. Unlimited
    or absent cgroup limits are ``None``; malformed visible limits are errors
    and prevent dispatch. CPU load is reported, not treated as a hard quota.
    """
    errors = []
    available = None
    for line in (_read(Path(proc_root) / "meminfo") or "").splitlines():
        if line.startswith("MemAvailable:"):
            try:
                available = int(line.split()[1]) // 1024
            except (ValueError, IndexError):
                errors.append("invalid_mem_available")
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):
        load = None
    cpu_limits, memory_limits = [], []
    for version, controllers, path in _cgroup_paths(proc_root, mount_prefix=mount_prefix):
        if version == "cgroup2":
            raw = _read(path / "cpu.max")
            if raw is not None:
                try:
                    quota, period = raw.split()
                    if quota != "max":
                        if int(quota) <= 0 or int(period) <= 0:
                            raise ValueError
                        cpu_limits.append(int(quota) / int(period))
                except (ValueError, ZeroDivisionError):
                    errors.append("invalid_cgroup_cpu_limit")
            limit, used = _read(path / "memory.max"), _read(path / "memory.current")
        else:
            if "cpu" in controllers.split(","):
                quota, period = _read(path / "cpu.cfs_quota_us"), _read(path / "cpu.cfs_period_us")
                if quota is not None:
                    try:
                        if int(quota) != -1:
                            if int(quota) <= 0 or int(period) <= 0:
                                raise ValueError
                            cpu_limits.append(int(quota) / int(period))
                    except (ValueError, TypeError, ZeroDivisionError):
                        errors.append("invalid_cgroup_cpu_limit")
            if "memory" not in controllers.split(","):
                continue
            limit, used = _read(path / "memory.limit_in_bytes"), _read(path / "memory.usage_in_bytes")
        if limit not in (None, "max"):
            try:
                limit_int, used_int = int(limit), int(used)
                if limit_int < 0 or used_int < 0:
                    raise ValueError
                memory_limits.append(max(0, limit_int - used_int) // MIB)
            except (ValueError, TypeError):
                errors.append("invalid_cgroup_memory_limit")
    return {"hardware_cpu_count": os.cpu_count(), "affinity_cpu_count": affinity,
            "cgroup_cpu_count": min(cpu_limits) if cpu_limits else None,
            "available_memory_mb": available,
            "cgroup_memory_remaining_mb": min(memory_limits) if memory_limits else None,
            "load_average": load, "probe_errors": sorted(set(errors))}


def scheduler_capacity(snapshot: Mapping, lane="hammer_lean"):
    """Return unreserved root capacity, preserving other lanes' reservations.

    This consumes an existing snapshot; it neither opens nor recovers scheduler
    state. It is advisory and cannot replace atomic scheduler acquisition.
    """
    lane = getattr(lane, "value", lane)
    available = snapshot["available"]
    cpu = _integer(available["cpu_slots"], "scheduler CPU")
    memory = _integer(available["memory_mb"], "scheduler memory")
    for name, item in snapshot["lanes"].items():
        if name == lane:
            continue
        for resource in ("cpu_slots", "memory_mb"):
            protected = max(0, _integer(item["reservation"].get(resource, 0), resource)
                            - _integer(item["allocated"].get(resource, 0), resource))
            if resource == "cpu_slots":
                cpu -= protected
            else:
                memory -= protected
    return {"cpu_slots": max(0, cpu), "memory_mb": max(0, memory),
            "child_process_slots": _integer(available["child_process_slots"], "scheduler child slots")}


def scheduler_snapshot(config=None):
    """Observe the host scheduler without creating files or recovering leases.

    Atomic state replacement permits a consistent single-file read. Stale root
    leases remain charged, making this conservative until the actual scheduler
    performs recovery. A changed/corrupt configuration fails closed.
    """
    from .resource_scheduler import ResourceSchedulerConfig, RESOURCE_SCHEDULER_SCHEMA_VERSION
    config = ResourceSchedulerConfig() if config is None else config
    config.validate()
    path, expected = Path(config.state_path), config.persisted_dict()
    try:
        with path.open("rb") as handle:
            raw = handle.read(8 * 1024 * 1024 + 1)
    except FileNotFoundError:
        state = {"leases": {}, "config": expected}
    else:
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise ValueError("invalid scheduler state size")
        state = json.loads(raw)
        if state.get("schema_version") != RESOURCE_SCHEDULER_SCHEMA_VERSION:
            raise ValueError("unsupported scheduler state schema")
        stored = dict(state.get("config") or {})
        stored.setdefault("total_unified_memory_mb", None)
        stored.setdefault("total_child_process_slots", 64)
        if stored != expected:
            raise ValueError("scheduler configuration changed")
    lanes = {name: {"reservation": reservation.to_dict(),
                    "allocated": {"cpu_slots": 0, "memory_mb": 0, "child_process_slots": 0}}
             for name, reservation in config.reservations().items()}
    used = {"cpu_slots": 0, "memory_mb": 0, "child_process_slots": 0}
    leases = state.get("leases")
    if type(leases) is not dict:
        raise ValueError("invalid scheduler leases")
    for lease in leases.values():
        if type(lease) is not dict:
            raise ValueError("invalid scheduler lease")
        if lease.get("parent_lease_id"):
            if lease["parent_lease_id"] not in leases:
                raise ValueError("scheduler child has no parent")
            continue
        name = lease["lane"]
        if type(name) is not str or not name:
            raise ValueError("invalid scheduler lane")
        usage = lanes.setdefault(name, {"reservation": {}, "allocated": dict.fromkeys(used, 0)})["allocated"]
        for field in used:
            value = _integer(lease.get(field, 0), "scheduler lease " + field)
            used[field] += value
            usage[field] += value
    totals = {"cpu_slots": config.total_cpu_slots,
              "memory_mb": config.total_memory_mb - config.reserved_memory_mb,
              "child_process_slots": config.total_child_process_slots}
    return {"state_path": str(path), "read_only": True, "stale_leases_charged": True,
            "available": {name: max(0, totals[name] - used[name]) for name in used},
            "allocated": used, "lanes": lanes}


def capacity_plan(*, max_workers, memory_budget_mb, pending_count, cpu_budget=None,
                  per_worker_memory_mb=1024, per_worker_cpu=1, reserve_mb=512,
                  storage_headroom_bytes=None, per_worker_storage_bytes=0,
                  scheduler_available_cpu=None, scheduler_available_memory_mb=None,
                  scheduler_available_process_slots=None, per_worker_process_slots=1,
                  probe=None):
    """Bound parallel passes by hardware, the caller's envelope, and headroom.

    ``memory_budget_mb`` is the whole group's existing reservation. For a fleet
    it is the maximum aggregate envelope. Scheduler limits are supplied only
    before acquiring root reservations; a nested caller supplies its parent's
    CPU/memory envelope instead. Zero capacity is a normal deferral.
    """
    for name, value, minimum in (("max_workers", max_workers, 1),
            ("memory_budget_mb", memory_budget_mb, 0), ("pending_count", pending_count, 0),
            ("per_worker_memory_mb", per_worker_memory_mb, 1), ("per_worker_cpu", per_worker_cpu, 1),
            ("reserve_mb", reserve_mb, 0), ("per_worker_storage_bytes", per_worker_storage_bytes, 0),
            ("per_worker_process_slots", per_worker_process_slots, 1)):
        _integer(value, name, minimum)
    if max_workers > 32:
        raise ValueError("max_workers exceeds 32")
    for name, value in (("cpu_budget", cpu_budget), ("storage_headroom_bytes", storage_headroom_bytes),
            ("scheduler_available_cpu", scheduler_available_cpu),
            ("scheduler_available_memory_mb", scheduler_available_memory_mb),
            ("scheduler_available_process_slots", scheduler_available_process_slots)):
        if value is not None:
            _integer(value, name)
    observed = dict(hardware_probe() if probe is None else probe)
    limits = {"requested_workers": max_workers, "pending_passes": pending_count,
              "reservation_memory": max(0, memory_budget_mb - reserve_mb) // per_worker_memory_mb}
    reasons = []
    for name in ("hardware_cpu_count", "affinity_cpu_count", "cgroup_cpu_count"):
        value = observed.get(name)
        if value is None:
            if name == "hardware_cpu_count":
                limits[name] = 0
                reasons.append("unknown_cpu_capacity")
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid hardware probe " + name)
        limits[name] = math.floor(value / per_worker_cpu)
    for name in ("available_memory_mb", "cgroup_memory_remaining_mb"):
        value = observed.get(name)
        if value is None:
            if name == "available_memory_mb":
                limits[name] = 0
                reasons.append("unknown_available_memory")
            continue
        _integer(value, name)
        limits[name] = max(0, value - reserve_mb) // per_worker_memory_mb
    if observed.get("probe_errors"):
        limits["probe_health"] = 0
        reasons.append("hardware_probe_error")
    for name, value, cost in (("reservation_cpu", cpu_budget, per_worker_cpu),
            ("scheduler_cpu", scheduler_available_cpu, per_worker_cpu),
            ("scheduler_memory", scheduler_available_memory_mb, per_worker_memory_mb),
            ("scheduler_process_slots", scheduler_available_process_slots, per_worker_process_slots)):
        if value is not None:
            limits[name] = max(0, value - (reserve_mb if name == "scheduler_memory" else 0)) // cost
    if per_worker_storage_bytes:
        limits["storage_headroom"] = 0 if storage_headroom_bytes is None else storage_headroom_bytes // per_worker_storage_bytes
        if storage_headroom_bytes is None:
            reasons.append("unknown_storage_headroom")
    workers = min(limits.values())
    if workers == 0:
        reasons.extend("insufficient_" + key for key, value in limits.items() if value == 0 and key != "pending_passes")
        if not pending_count:
            reasons.append("no_pending_passes")
    return {"schema_version": "autoencoder-dispatch-capacity/v1", "workers": workers,
            "limits": limits, "telemetry": observed, "reasons": sorted(set(reasons)),
            "scope": "concurrent_independent_passes", "admitted": False}
