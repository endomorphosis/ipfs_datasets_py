"""Observe separate stable admission and confined execution scopes.

This numerical guard reads live held cgroup bindings. It never grants native
resources, reconstructs authority from JSON, changes a limit, or releases a
lease. The caller must guard its actual native owner before and after use.
The controller's kernel capacity ceiling is not the admitted memory budget.
"""
from __future__ import annotations

from pathlib import Path

from .autoencoder_kernel_custody import BoundCgroup, KernelCustodyError

SCHEMA = "autoencoder-controller-worker-observation/v1"


def _need(condition, message):
    if not condition:
        raise KernelCustodyError(message)


def observe_controller_worker(controller_scope, worker_scope, *, owner_pid,
                              native_memory_bytes, native_child_process_slots):
    """Check aggregate usage against caller-supplied native budget numbers.

    Numbers are constraints, never evidence of native admission. Both bindings
    must remain alive; receipts/dictionaries cannot substitute for them. The
    native owner stays outside the worker, and performs every native scheduler
    operation from its stable controller scope. Productive barrier release,
    durable sealing, process reaping and native release remain caller duties.

    Hierarchical controller memory already includes the worker and cache; it
    is not added to worker memory or owner RSS. Optional lifetime peaks and
    kernel OOM/max events fail closed rather than hiding between-sample damage.
    A successful observation provides no whole-controller memory hard cap at
    the native budget and no model or Lean admission.
    """
    _need(type(controller_scope) is BoundCgroup and type(worker_scope) is BoundCgroup
          and controller_scope is not worker_scope, "two live held cgroup bindings required")
    _need(type(owner_pid) is int and owner_pid > 0, "positive native owner PID required")
    _need(type(native_memory_bytes) is int and 0 < native_memory_bytes < 2**63,
          "positive native memory budget required")
    _need(type(native_child_process_slots) is int and 0 < native_child_process_slots < 2**31,
          "positive native child process budget required")
    controller = controller_scope.observe()
    worker = worker_scope.observe()
    controller = controller_scope.observe()
    root, leaf = Path(controller["path"]), Path(worker["path"])
    _need(root in leaf.parents, "worker must be a strict descendant of its controller")
    _need(worker["expected_root"] == controller["path"]
          and worker["root_identity"] == controller["directory_identity"],
          "worker ancestry anchor differs from exact controller")
    _need(controller["boot_id"] == worker["boot_id"]
          and controller["mount"] == worker["mount"]
          and controller["simulation"] is worker["simulation"], "controller/worker kernel identity differs")
    processes, workers = set(controller["process_ids"]), set(worker["process_ids"])
    _need(owner_pid in processes and owner_pid not in workers,
          "native owner must remain in controller outside confined worker")
    _need(workers <= processes, "worker process inventory is outside controller")
    _need(len(processes - {owner_pid}) <= native_child_process_slots,
          "controller descendants exceed native process budget")
    _need(controller["memory_max_bytes"] >= native_memory_bytes,
          "controller capacity ceiling is below native budget")
    _need(worker["memory_max_bytes"] <= native_memory_bytes,
          "worker kernel ceiling exceeds native memory budget")
    _need(worker["memory_current_bytes"] <= controller["memory_current_bytes"],
          "hierarchical memory observations disagree")
    _need(controller["memory_current_bytes"] <= native_memory_bytes,
          "aggregate controller charge exceeds native memory budget")
    for label, observation in (("controller", controller), ("worker", worker)):
        peak = observation["memory_peak_bytes"]
        _need(peak is None or peak <= native_memory_bytes,
              label + " lifetime memory peak exceeds native budget")
        events = observation["memory_events"]
        _need(all(events.get(name, 0) == 0 for name in ("max", "oom", "oom_kill", "oom_group_kill")),
              label + " recorded memory limit or OOM event")
    return {
        "schema": SCHEMA, "controller": controller, "worker": worker,
        "native_memory_budget_bytes": native_memory_bytes,
        "native_child_process_slots": native_child_process_slots,
        "aggregate_charged_memory_bytes": controller["memory_current_bytes"],
        "controller_capacity_ceiling_is_reservation": False,
        "whole_controller_kernel_cap_at_native_budget": False,
        "simulation": controller["simulation"], "native_admission": False,
        "observation_only": True, "admitted": False, "Lean_admitted": False,
        "observation_atomic": False, "controller_refreshed_after_worker": True,
    }


__all__ = ["observe_controller_worker", "SCHEMA"]
