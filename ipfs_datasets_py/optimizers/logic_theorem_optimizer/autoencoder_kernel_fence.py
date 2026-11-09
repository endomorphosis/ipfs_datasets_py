"""Keep an actual native child charged until its held worker scope drains.

The caller acquires the child in a surviving guardian before releasing any
worker barrier. Native cancellation revokes work but leaves that live child
charged. This object does not acquire leases, authenticate public receipts,
reconcile disk claims, or qualify simultaneous guardian death. The caller owns
the source lease, startup protocol and lifecycle of the guardian itself.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from . import existing_resource_scheduler as existing
from . import resource_scheduler as native
from .autoencoder_kernel_custody import BoundCgroup, KernelCustodyError


_ENVELOPE = ("lease_id", "parent_lease_id", "owner_pid", "owner_birth_marker",
             "owner_boot_id", "lane", "cpu_slots", "memory_mb", "child_process_slots",
             "gpu_memory_mb", "unified_memory_mb", "requires_gpu", "acquired_at")


def _need(value, message):
    if not value:
        raise KernelCustodyError(message)


def _envelope(record):
    return {name: record.get(name) for name in _ENVELOPE}


class KernelDrainFence:
    """An owned native child capability and an original held cgroup binding.

    There is deliberately no context-manager exit or destructor that releases
    the child. Failure to establish exact quiescence leaves capacity charged
    while the guardian lives, even after the root owner dies or is cancelled.
    Never put the guardian inside the worker scope it will kill.
    """

    def __init__(self, lease, scope, *, scheduler_state_path,
                 expected_scheduler_policy_sha256):
        _need(type(lease) is native.ResourceLease and not lease.released,
              "actual unreleased native child capability required")
        _need(type(scope) is BoundCgroup and scope._allow_drain,
              "live held worker binding with drain authorization required")
        scheduler = lease._scheduler
        _need(type(scheduler) is existing._PinnedGlobalResourceScheduler,
              "explicit existing pinned native scheduler required")
        _need(Path(scheduler_state_path).is_absolute()
              and Path(scheduler_state_path) == scheduler.state_path
              and scheduler._policy_sha256 == expected_scheduler_policy_sha256,
              "fence scheduler identity or exact policy differs")
        _need(lease.owner_pid == os.getpid() and lease.parent_lease_id is not None,
              "fence must be a child owned by this surviving guardian")
        self._lease, self._scope, self._scheduler = lease, scope, scheduler
        self._owner_pid = os.getpid()
        self._policy = expected_scheduler_policy_sha256
        self._released = False
        self._chain = None
        self._drain_report = None
        _need(lease.renew() and not lease.cancelled,
              "live uncancelled native ancestry required before worker startup")
        self._authority(require_work=True)
        observation = scope.observe()
        _need(self._owner_pid not in observation["process_ids"],
              "guardian must stay outside the scope it drains")
        _need(observation["boot_id"].replace("-", "")
              == native._owner_boot_id().replace("-", ""),
              "worker binding belongs to another boot")
        self._authority(require_work=True)

    @property
    def released(self):
        return self._released

    def _authority(self, *, require_work):
        _need(os.getpid() == self._owner_pid and not self._released
              and not self._lease.released, "fence guardian changed or lease released")
        with self._scheduler._locked_state(persist=False) as state:
            _need(existing.policy_sha256(state["config"]) == self._policy,
                  "native fence policy changed")
            row = state["leases"].get(self._lease.lease_id)
            _need(row is not None and row.get("lease_key") == self._lease.lease_key
                  and row.get("owner_pid") == self._owner_pid
                  and row.get("owner_birth_marker") == native._owner_birth_marker(self._owner_pid)
                  and str(row.get("owner_boot_id", "")).replace("-", "")
                      == native._owner_boot_id().replace("-", "")
                  and not row.get("release_requested"),
                  "actual guardian-owned native fence no longer charged")
            _need(not any(record.get("parent_lease_id") == self._lease.lease_id
                          for record in state["leases"].values()),
                  "native fence must not have independent consumers")
            chain, seen = [], set()
            current = row
            while current is not None:
                identifier = current["lease_id"]
                _need(identifier not in seen and len(chain) < 64,
                      "invalid native fence ancestry")
                seen.add(identifier)
                chain.append(_envelope(current))
                parent_id = current.get("parent_lease_id")
                if not parent_id:
                    break
                current = state["leases"].get(parent_id)
                _need(current is not None, "native fence ancestor disappeared")
            _need(len(chain) >= 2, "native fence needs a retained root ancestor")
            if self._chain is None:
                self._chain = copy.deepcopy(chain)
            _need(chain == self._chain, "native fence or ancestor envelope changed")
            observation = dict(child_lease_id=self._lease.lease_id,
                root_lease_id=chain[-1]["lease_id"],
                root_owner_pid=chain[-1]["owner_pid"], guardian_pid=self._owner_pid,
                guardian_distinct_from_root_owner=(chain[-1]["owner_pid"] != self._owner_pid),
                root_capacity_still_charged=True,
                root_release_requested=bool(current.get("release_requested")),
                child_cancelled=bool(row.get("cancelled")))
        if require_work:
            _need(not self._lease.cancelled,
                  "native fence ancestry revoked; cleanup only")
        return observation

    def guard_work(self):
        """Guard actual authority around a fresh observation before work."""
        _need(self._lease.renew(), "native fence heartbeat failed")
        authority = self._authority(require_work=True)
        observation = self._scope.observe()
        _need(self._owner_pid not in observation["process_ids"],
              "guardian entered its kill scope")
        self._authority(require_work=True)
        return dict(schema="autoencoder-kernel-drain-fence/v1", **authority,
            worker=observation, native_admission=False, admitted=False,
            Lean_admitted=False, guardian_death_qualified=False)

    def drain_and_release(self, *, timeout_seconds=5, before_release=None):
        """Drain the original scope, run caller reap/guards, then release.

        Cancellation is expected after root-owner death and never prevents
        stopped cleanup. A failed drain, callback or fresh quiescence check
        cannot reach native release. The callback must not start new workers.
        Disk-claim closeout remains a separate explicit operation.
        """
        _need(before_release is None or callable(before_release),
              "before_release must be a callable or None")
        authority = self._authority(require_work=False)
        guardian = self._scope._backend.process(self._owner_pid)
        member = self._scope._membership(self._scope._path)
        _need(guardian is not None and guardian["membership"] != member
              and not guardian["membership"].startswith(member + "/"),
              "guardian entered its kill scope; cleanup needs a separate custodian")
        # Do not require productive observe() here: a changed worker topology
        # still needs cleanup through the original hierarchical kill FD.
        drained = self._scope.drain(timeout_seconds=timeout_seconds)
        _need(drained["populated"] is False, "worker drain unresolved")
        if before_release is not None:
            before_release()
        guardian = self._scope._backend.process(self._owner_pid)
        _need(guardian is not None and guardian["membership"] != member
              and not guardian["membership"].startswith(member + "/"),
              "guardian entered its kill scope before final drain")
        fresh = self._scope.drain(timeout_seconds=timeout_seconds)
        _need(fresh["populated"] is False, "worker repopulated before release")
        self._authority(require_work=False)
        _need(self._lease.release(), "native fence release not acknowledged")
        self._released = True
        with self._scheduler._locked_state(persist=False) as state:
            _need(self._lease.lease_id not in state["leases"],
                  "native fence still has consumers after release")
            root_remains = authority["root_lease_id"] in state["leases"]
        self._drain_report = dict(schema="autoencoder-kernel-drain-fence-closeout/v1",
            **authority, worker_drain=drained, worker_final_drain=fresh,
            child_release_acknowledged=True, root_lease_remains=root_remains,
            disk_claim_reconciled=False, native_admission=False, admitted=False,
            Lean_admitted=False, guardian_death_qualified=False)
        self._drain_report["root_capacity_still_charged_before_drain"] = (
            self._drain_report.pop("root_capacity_still_charged"))
        return copy.deepcopy(self._drain_report)
