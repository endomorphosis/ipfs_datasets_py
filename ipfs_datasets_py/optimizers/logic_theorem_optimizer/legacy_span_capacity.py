"""Plan bounded census dispatch inside an already reserved resource envelope.

One model owner is retained. The caller supplies measured/conservative legacy
resident and per-span working-set estimates; another checkpoint's generic
inference estimate is not silently substituted. This module acquires no lease.
"""
from __future__ import annotations

from .autoencoder_capacity import capacity_plan, hardware_probe


def legacy_span_capacity_plan(*, requested_compiler_workers: int,
        requested_batch_size: int, memory_budget_mb: int, cpu_budget: int,
        process_budget: int, fixed_resident_mb: int,
        pending_span_count: int = 32, bridge_workers: int = 1,
        per_compiler_memory_mb: int = 128, per_span_working_set_mb: int = 64,
        safety_mb: int = 512, already_resident_mb: int = 0, probe=None) -> dict:
    """Prefer the requested batch, shrinking it until a compiler slot fits.

    ``fixed_resident_mb`` covers the coordinator, sole model and tracker, but
    excludes compiler processes and the batch's target/artifact working set.
    ``already_resident_mb`` is observed memory already charged to that fixed
    allowance. It avoids subtracting live owners twice from hardware headroom;
    it never increases the reservation or ignores its full fixed allowance.
    The legacy process is not thread-safe; parallelism belongs in CPU tasks.
    """
    bounds = ((requested_compiler_workers, "requested_compiler_workers", 1, 8),
              (requested_batch_size, "requested_batch_size", 1, 32),
              (bridge_workers, "bridge_workers", 1, 8),
              (memory_budget_mb, "memory_budget_mb", 0, None),
              (cpu_budget, "cpu_budget", 0, None),
              (process_budget, "process_budget", 0, None),
              (fixed_resident_mb, "fixed_resident_mb", 1, None),
              (pending_span_count, "pending_span_count", 0, None),
              (per_compiler_memory_mb, "per_compiler_memory_mb", 1, None),
              (per_span_working_set_mb, "per_span_working_set_mb", 1, None),
              (safety_mb, "safety_mb", 0, None),
              (already_resident_mb, "already_resident_mb", 0, fixed_resident_mb))
    for value, name, minimum, maximum in bounds:
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            raise ValueError("invalid " + name)
    observed = dict(hardware_probe() if probe is None else probe)
    adjusted = dict(observed)
    for name in ("available_memory_mb", "cgroup_memory_remaining_mb"):
        value = adjusted.get(name)
        if type(value) is int and value >= 0:
            adjusted[name] = value + already_resident_mb
    attempts = []
    batch_size = min(requested_batch_size, pending_span_count) or 1
    while True:
        overhead = fixed_resident_mb + safety_mb + batch_size * per_span_working_set_mb
        plan = capacity_plan(max_workers=requested_compiler_workers,
            pending_count=pending_span_count, memory_budget_mb=memory_budget_mb,
            cpu_budget=cpu_budget, per_worker_memory_mb=per_compiler_memory_mb,
            reserve_mb=overhead, reserve_cpu_slots=bridge_workers + 1,
            process_budget=process_budget, reserve_process_slots=3, probe=adjusted)
        attempts.append({"batch_size": batch_size, "compiler_workers": plan["workers"],
                         "limits": plan["limits"], "reasons": plan["reasons"]})
        if plan["workers"] or batch_size == 1:
            break
        batch_size = max(1, batch_size // 2)
    workers = plan["workers"]
    return {"schema": "legacy-span-dispatch-capacity/v1",
        "compiler_workers": workers, "batch_size": batch_size if workers else 0,
        "model_owners": 1 if workers else 0,
        "max_inflight_batches": 2 if workers else 0,
        "compiler_chunk_size": min(8, max(1, (batch_size + workers - 1) // workers)) if workers else 0,
        "max_submitted_compiler_tasks": 2 * workers,
        "estimated_group_memory_mb": overhead + workers * per_compiler_memory_mb if workers else 0,
        "estimates": {"fixed_resident_mb": fixed_resident_mb,
                      "per_compiler_memory_mb": per_compiler_memory_mb,
                      "per_span_working_set_mb": per_span_working_set_mb,
                      "safety_mb": safety_mb, "already_resident_mb": already_resident_mb},
        "telemetry": observed, "attempts": attempts, "reasons": plan["reasons"],
        "scope": "dispatch_inside_existing_reservation", "reservation_acquired": False,
        "admitted": False}
