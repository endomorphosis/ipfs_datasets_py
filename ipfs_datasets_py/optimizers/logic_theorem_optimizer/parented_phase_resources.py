"""Durable phase storage beneath an existing, authenticated native phase.

This owner acquires a real same-lane child, never another host root or a
borrowed/fake lease. The original bridge remains the sole owner of its phase
and root. Limits are cooperative sampling, not a filesystem quota or sandbox.
"""
from __future__ import annotations

import copy
import hashlib
import os
import sys
from pathlib import Path
import time

from . import autoencoder_daemon_resources as host
from .autoencoder_daemon_resources import DaemonResourceError, DaemonResourceReservation
from .existing_resource_scheduler import open_existing_scheduler
from .resource_scheduler import ResourceLane, ResourceLease


def _need(value, message):
    if not value:
        raise DaemonResourceError(message)


_ENVELOPE = ("lease_id", "parent_lease_id", "owner_pid", "lane", "cpu_slots",
             "memory_mb", "child_process_slots", "requires_gpu", "gpu_memory_mb",
             "unified_memory_mb")


class ParentedPhaseResourceReservation(DaemonResourceReservation):
    """One disk claim and one actual native child beneath an existing phase.

    Only actual in-process ResourceLease capabilities are accepted. The state,
    policy, attempt and producer sources remain pinned. timeout_seconds is an
    absolute lifetime from construction; renewing a native lease cannot extend
    it. Productive finalization requires live ancestry. Explicit release is
    stopped cleanup and may run after revocation, without acquiring a new grant.
    External precharges retain the base API's declared-byte semantics; they do
    not measure mutable external files or establish a sandbox.
    """

    def __init__(self, ledger_path, *, roots, attempt_directory, parent_lease,
                 storage_bytes, memory_mb, cpu_slots=1, child_process_slots=1,
                 scheduler_state_path, expected_scheduler_policy_sha256,
                 timeout_seconds=0, ledger_lock_timeout_seconds=None):
        _need(type(parent_lease) is ResourceLease, "exact native phase parent lease required")
        _need(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 3600,
              "positive finite parented phase deadline required")
        self._deadline = time.monotonic() + timeout_seconds
        self._parent = parent_lease
        _need(parent_lease.parent_lease_id is not None,
              "an existing native phase beneath a root is required")
        self._phase_lane = ResourceLane(parent_lease.lane)
        parent_public = parent_lease.to_dict()
        self._parent_envelope = {k: parent_public[k] for k in _ENVELOPE}
        self._admission = open_existing_scheduler(scheduler_state_path, expected_scheduler_policy_sha256)
        _need(Path(parent_lease.token.state_path) == self._admission.state_path,
              "phase parent belongs to another scheduler")
        _need(parent_lease.owner_pid == os.getpid(), "phase parent belongs to another owner process")
        _need(not parent_lease.requires_gpu and not parent_lease.gpu_memory_mb
              and not parent_lease.unified_memory_mb, "only CPU phase parents are supported")
        super().__init__(ledger_path, roots=roots, storage_bytes=storage_bytes,
            memory_mb=memory_mb, cpu_slots=cpu_slots, child_process_slots=child_process_slots,
            timeout_seconds=timeout_seconds, ledger_lock_timeout_seconds=ledger_lock_timeout_seconds,
            scheduler_state_path=scheduler_state_path,
            expected_scheduler_policy_sha256=expected_scheduler_policy_sha256,
            require_existing_ledger=True)
        self.directory = host._safe_path(attempt_directory, directory=True)
        _need(any(root in self.directory.parents for root in self.roots),
              "phase attempt must be a strict descendant of a named storage root")
        self._attempt = host._root_identity(self.directory)
        owner = host._process(self._owner_pid)
        _need(owner is not None, "phase owner identity unavailable")
        self._owner_birth = owner["birth"]
        self._sources = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (Path(__file__), Path(host.__file__))}
        self._last_local_usage = None
        self._closing_mode = None
        self._guard_authority(full=True)
        with self._locked():
            self._read()

    def _scheduler_identity(self):
        return self._phase_lane, "canonical_parented_phase"

    def _verify_owner_roots(self):
        super()._verify_owner_roots()
        if hasattr(self, "_owner_birth"):
            owner = host._process(self._owner_pid)
            _need(owner is not None and owner["birth"] == self._owner_birth,
                  "phase owner process identity changed")
            _need(host._root_identity(self.directory) == self._attempt,
                  "phase attempt directory identity changed")
            _need(all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in self._sources.items()),
                  "parented phase producer source changed")

    def _read(self):
        value = super()._read()
        if self._record is not None:
            _need(value["reservations"].get(self.reservation_id) == self._record,
                  "owned phase disk record changed")
        return value

    def _guard_authority(self, *, full=False):
        _need(time.monotonic() < self._deadline, "parented phase deadline expired")
        parent_public = self._parent.to_dict()
        _need({k: parent_public[k] for k in _ENVELOPE} == self._parent_envelope,
              "phase parent envelope changed")
        _need(not self._parent.released and not self._admission.is_cancelled(
            self._parent.lease_id, missing_is_cancelled=True), "phase parent authority was revoked")
        if self._lease is not None:
            _need(not self._lease.released and not self._admission.is_cancelled(
                self._lease.lease_id, missing_is_cancelled=True), "owned phase authority was revoked")
        if full:
            active = {r["lease_id"]: r for r in self._admission.active_leases()}
            parent = active.get(self._parent.lease_id)
            _need(parent is not None and {k: parent.get(k) for k in _ENVELOPE} == self._parent_envelope,
                  "native phase parent envelope differs")
            if self._lease is not None:
                owned = active.get(self._lease.lease_id)
                expected = {"lease_id": self._lease.lease_id,
                    "parent_lease_id": self._parent.lease_id, "owner_pid": self._owner_pid,
                    "lane": self._phase_lane.value, "cpu_slots": self.cpu_slots,
                    "memory_mb": self.memory_mb, "child_process_slots": self.child_process_slots,
                    "requires_gpu": False, "gpu_memory_mb": 0, "unified_memory_mb": 0}
                _need(owned is not None and {k: owned.get(k) for k in _ENVELOPE} == expected,
                      "owned native phase envelope differs")

    def _validate_new_reservation(self, ledger):
        self._guard_authority(full=True)
        for row in ledger["reservations"].values():
            other = row.get("attempt_directory")
            if row["status"] != "released" and other is not None:
                path = Path(other["path"])
                _need(not (path == self.directory or path in self.directory.parents
                           or self.directory in path.parents), "phase attempt overlaps an outstanding owner")

    def _acquire_native_lease(self, scheduler, lane):
        self._guard_authority(full=True)
        _need(scheduler is not None and scheduler.state_path == self._admission.state_path,
              "strict phase scheduler identity differs")
        remaining = self._deadline - time.monotonic()
        operation = host.native_deadlines.resource_operation_deadline()
        if operation is not None:
            remaining = min(remaining, host.native_deadlines._operation_clock(operation)-time.monotonic())
        _need(remaining > 0, "parented phase admission deadline expired")
        return scheduler.acquire(lane, cpu_slots=self.cpu_slots, memory_mb=self.memory_mb,
            child_process_slots=self.child_process_slots, requires_gpu=False,
            parent_lease=self._parent, timeout=remaining, request_id=self._scheduler_request_id())

    def __enter__(self):
        super().__enter__()
        try:
            self._guard_authority(full=True)
            self._update(parent_lease_id=self._parent.lease_id,
                         native_lease_id=self._lease.lease_id,
                         scheduler_state_path=str(self._admission.state_path),
                         scheduler_policy_sha256=self._expected_scheduler_policy_sha256)
            self.check_usage(self.directory)
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    @property
    def native_lease(self):
        self._verify_owner_roots()
        _need(self._entered and self._record["status"] == "active", "phase owner is not active")
        self._guard_authority(full=True)
        return self._lease

    def _native_consumers(self):
        if self._lease is None:
            return []
        return [r for r in self._admission.active_leases()
                if r.get("parent_lease_id") == self._lease.lease_id]

    def heartbeat(self):
        self._verify_owner_roots()
        self._guard_authority()
        return super().heartbeat()

    def check_usage(self, attempt_directory, child_pid=None, *, full=False):
        """Cheap local aggregate/group sample; full=True adds a fresh census."""
        _need(type(full) is bool, "full must be a Boolean")
        self._verify_owner_roots()
        _need(self._entered and self._record["status"] == "active", "phase owner is not active")
        _need(host._safe_path(attempt_directory, directory=True) == self.directory,
              "phase attempt directory differs")
        if child_pid is None:
            self._guard_authority(full=full)
        if child_pid is not None:
            # Preserve actual child identity even if authority is revoked just
            # after Popen; cleanup must still be able to reap the real group.
            host._integer(child_pid, "child_pid")
            if self._child is None or child_pid != self._child["pid"]:
                if self._child is not None:
                    _need(not host._group_usage(self._child)["live_processes"],
                          "previous child process group is still alive")
                    _need(len(self._child_history) < host.MAX_CHILDREN_PER_RESERVATION - 1,
                          "reservation child history bound exceeded")
                child = host._process(child_pid)
                _need(child is not None and child["parent_pid"] == self._owner_pid
                      and child["group_pid"] == child_pid,
                      "child must be an owned isolated process-group leader")
                if self._child is not None:
                    self._child_history.append({**self._child, "group_observed_dead_at": time.time()})
                self._child = {k: child[k] for k in ("pid", "birth")}
                self._update(child=self._child, prior_children=copy.deepcopy(self._child_history))
        group = host._group_usage(self._child)
        size = host._inventory([self.directory], strict=True)["apparent_bytes"]
        external = sum(host._external_charges(self._record).values())
        usage = dict(scope="owned_attempt_and_original_process_group", attempt_bytes=size,
            external_charged_bytes=external, total_attempt_charged_bytes=size + external,
            attempt_limit_bytes=self.storage_bytes, group_rss=group,
            memory_limit_bytes=self.memory_mb * 1024 * 1024,
            reserved_child_process_slots=self.child_process_slots,
            process_slot_estimate_exceeded=group["live_processes"] > self.child_process_slots,
            checked_at=time.time(), full_ledger_check=False)
        self._last_local_usage = copy.deepcopy(usage)
        _need(size + external <= self.storage_bytes, "attempt storage byte limit exceeded")
        _need(group["rss_bytes"] <= self.memory_mb * 1024 * 1024, "child group RSS limit exceeded")
        _need(not usage["process_slot_estimate_exceeded"], "child group process-slot limit exceeded")
        if full:
            usage = super().check_usage(self.directory)
            usage["full_ledger_check"] = True
        self._guard_authority()
        return usage

    def account_external_bytes(self, *args, **kwargs):
        self._guard_authority(full=True)
        return super().account_external_bytes(*args, **kwargs)

    def _write(self, value):
        if self._closing_mode is not None:
            _need(not self._native_consumers(), "native consumers must finish and release before finalization")
            _need(not host._group_usage(self._child)["live_processes"], "child process group is still alive")
            if self._closing_mode == "productive":
                self._guard_authority(full=True)
        super()._write(value)

    def finalize(self, attempt_directory, *, artifacts_durable=False):
        if self._record is not None and self._record["status"] == "released":
            return self.to_dict()
        self._guard_authority(full=True)
        _need(not self._native_consumers(), "native consumers must finish and release before finalization")
        _need(not host._group_usage(self._child)["live_processes"], "child process group is still alive")
        self._closing_mode = "productive"
        try:
            return super().finalize(attempt_directory, artifacts_durable=artifacts_durable)
        finally:
            self._closing_mode = None

    def release(self, *, artifacts_durable=False):
        """Explicit stopped cleanup, also usable after ancestry is revoked.

        Use the same fresh-census, owned-attempt finalizer; no compatibility
        bypass or weaker base release is used. This does not release ancestors.
        """
        self._verify_owner_roots()
        _need(not self._native_consumers(), "native consumers must finish and release before finalization")
        _need(not host._group_usage(self._child)["live_processes"], "child process group is still alive")
        self._closing_mode = "cleanup"
        try:
            return super().finalize(self.directory, artifacts_durable=artifacts_durable)
        finally:
            self._closing_mode = None

    close = release

    def __exit__(self, exc_type, exc, traceback):
        if self._record is not None and self._record["status"] != "released":
            try:
                try:
                    self._retain("context_failed" if exc_type else "explicit_release_required")
                finally:
                    if (self._lease is not None and not self._native_consumers()
                            and not host._group_usage(self._child)["live_processes"]):
                        self._lease.release()
            except BaseException as cleanup:
                self._cleanup_error = type(cleanup).__name__
                if exc_type is None:
                    raise
        return False

    def to_dict(self):
        result = super().to_dict()
        result.update(profile="parented-phase-sampled/v1",
                      last_local_usage=copy.deepcopy(self._last_local_usage),
                      authority="one_actual_child_of_existing_phase_no_additional_host_root",
                      external_file_growth_monitored=False)
        return result


__all__ = ["ParentedPhaseResourceReservation"]
