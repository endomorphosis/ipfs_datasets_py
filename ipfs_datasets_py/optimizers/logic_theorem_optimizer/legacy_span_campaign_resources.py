"""Owned resource bounds for continuous legacy span inference.

There is no campaign deadline here. Disk and host admission use the existing
ledger without releasing other owners' claims. CUDA admission is a separate,
cooperative check of actual device memory; it does not claim that the host
scheduler or this campaign's lock controls unrelated GPU applications.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

from . import autoencoder_daemon_resources as host

GIB = 1024 ** 3


class LegacySpanResourceError(host.DaemonResourceError):
    """A resource observation or the declared envelope could not be verified."""


def _positive(value, name):
    if type(value) is not int or value <= 0:
        raise LegacySpanResourceError(f"{name} must be a positive integer")
    return value


def cuda_memory_snapshot(device=0, *, torch_module=None):
    """Read CUDA in its owning process; unknown device telemetry fails closed."""
    if type(device) is not int or device < 0:
        raise LegacySpanResourceError("invalid CUDA device")
    try:
        if torch_module is None:
            import torch
        else:
            torch = torch_module
        if not torch.cuda.is_available() or torch.cuda.device_count() <= device:
            raise LegacySpanResourceError("CUDA device unavailable")
        free, total = torch.cuda.mem_get_info(device)
        result = {
            "device": device, "device_name": torch.cuda.get_device_name(device),
            "free_bytes": free, "total_bytes": total,
            "allocated_bytes": torch.cuda.memory_allocated(device),
            "reserved_bytes": torch.cuda.memory_reserved(device),
            "torch_version": str(torch.__version__),
            "cuda_version": str(torch.version.cuda),
            "observed_at": time.time(),
        }
    except LegacySpanResourceError:
        raise
    except Exception as exc:
        raise LegacySpanResourceError("CUDA memory telemetry unavailable") from exc
    _validate_cuda_snapshot(result)
    return result


def admit_cuda_device(cuda_device=0, *, budget_bytes=2 * GIB, safety_bytes=2 * GIB,
                      torch_module=None):
    """Probe and constrain the resident worker's PyTorch allocator before loading.

    Invoke only inside the process that will own CUDA. ``torch_module`` permits
    using its already imported torch module; callers must supply actual torch
    in production. Unavailable or inconsistent telemetry never admits work.
    The fraction limits PyTorch's caching allocator, not other CUDA libraries.
    """
    _positive(budget_bytes, "CUDA budget")
    _positive(safety_bytes, "CUDA safety reserve")
    if torch_module is None:
        try:
            import torch as torch_module
        except Exception as exc:
            raise LegacySpanResourceError("CUDA runtime unavailable") from exc
    observed = cuda_memory_snapshot(cuda_device, torch_module=torch_module)
    if observed["reserved_bytes"] > budget_bytes:
        raise LegacySpanResourceError("CUDA allocator budget exceeded before admission")
    if observed["free_bytes"] < max(0, budget_bytes - observed["reserved_bytes"]) + safety_bytes:
        raise LegacySpanResourceError("insufficient observed CUDA memory headroom")
    fraction = budget_bytes / observed["total_bytes"]
    if not 0 < fraction <= 1:
        raise LegacySpanResourceError("CUDA budget exceeds observed device capacity")
    try:
        torch_module.cuda.set_per_process_memory_fraction(fraction, device=cuda_device)
    except Exception as exc:
        raise LegacySpanResourceError("CUDA allocator fraction could not be configured") from exc
    return {**observed, "budget_bytes": budget_bytes, "safety_bytes": safety_bytes,
            "allocator_fraction": fraction, "allocator_fraction_set": True,
            "scope": "resident_worker_pytorch_allocator_and_observed_device_memory",
            "host_global_gpu_reservation": False,
            "other_cuda_allocators_limited": False}


def _validate_cuda_snapshot(value):
    for key in ("free_bytes", "total_bytes", "allocated_bytes", "reserved_bytes"):
        if type(value.get(key)) is not int or value[key] < 0:
            raise LegacySpanResourceError("invalid CUDA memory telemetry")
    if (not value["total_bytes"] or value["free_bytes"] > value["total_bytes"]
            or value["allocated_bytes"] > value["reserved_bytes"]
            or value["reserved_bytes"] > value["total_bytes"]):
        raise LegacySpanResourceError("inconsistent CUDA memory telemetry")


class CudaDeviceBudget:
    """One resident CUDA owner per campaign, with a monitored allocator budget.

    Enter this in the process that performs CUDA operations, before loading its
    tensors. The flock is deliberately campaign-local. Memory is shared with
    unrelated processes and can change immediately after a successful probe.
    This is polled admission, not a device quota or global GPU reservation.
    """

    def __init__(self, runtime_directory, *, device=0, budget_bytes=2 * GIB,
                 safety_bytes=2 * GIB):
        self.directory = host._safe_path(runtime_directory, directory=True)
        self.identity = host._root_identity(self.directory)
        if type(device) is not int or device < 0:
            raise LegacySpanResourceError("invalid CUDA device")
        self.device = device
        self.budget_bytes = _positive(budget_bytes, "CUDA budget")
        self.safety_bytes = _positive(safety_bytes, "CUDA safety reserve")
        self.lock_path = self.directory / f".legacy-cuda-{device}.lock"
        self._fd = None
        self._pid = None
        self.last_observation = None

    def __enter__(self):
        if self._fd is not None:
            raise LegacySpanResourceError("CUDA budget is already open")
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                             | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077):
                raise LegacySpanResourceError("invalid campaign CUDA lock")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LegacySpanResourceError("campaign CUDA owner already active") from exc
            self._fd, self._pid = descriptor, os.getpid()
            self.check(admission=True)
        except BaseException:
            self._fd = self._pid = None
            os.close(descriptor)
            raise
        return self

    def check(self, *, admission=False):
        if self._fd is None or self._pid != os.getpid():
            raise LegacySpanResourceError("CUDA budget is not owned by this process")
        if host._root_identity(self.directory) != self.identity:
            raise LegacySpanResourceError("campaign directory identity changed")
        current, opened = self.lock_path.lstat(), os.fstat(self._fd)
        if (current.st_dev, current.st_ino, current.st_nlink) != (opened.st_dev, opened.st_ino, 1):
            raise LegacySpanResourceError("campaign CUDA lock identity changed")
        observed = cuda_memory_snapshot(self.device)
        _validate_cuda_snapshot(observed)
        if observed["reserved_bytes"] > self.budget_bytes:
            raise LegacySpanResourceError("CUDA allocator budget exceeded")
        required = self.safety_bytes
        if admission:
            required += max(0, self.budget_bytes - observed["reserved_bytes"])
        if observed["free_bytes"] < required:
            raise LegacySpanResourceError("insufficient observed CUDA memory headroom")
        self.last_observation = {
            **observed, "budget_bytes": self.budget_bytes,
            "safety_bytes": self.safety_bytes, "admission": admission,
            "scope": "campaign_owner_allocator_and_observed_device_free_memory",
            "host_global_gpu_reservation": False,
            "enforcement": "cooperative_lock_and_polled_telemetry_not_device_quota",
        }
        return dict(self.last_observation)

    def close(self):
        if self._fd is not None:
            descriptor, self._fd = self._fd, None
            # A forked child must not unlock the parent's shared open description.
            if self._pid == os.getpid():
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            self._pid = None

    def __exit__(self, *unused):
        self.close()
        return False


class LegacySpanCampaignResources:
    """Host/disk reservation with cheap local checks and periodic exact census.

    The caller owns worker lifecycle. Attach an isolated direct child immediately
    after Popen(start_new_session=True); stop and reap its group before close.
    Full ledger checks can be slow and should not replace a separate process/RSS
    watchdog. Context exit without explicit durable close retains the claim.
    """

    def __init__(self, runtime_directory, resource_ledger, *, storage_bytes=750_000_000,
                 memory_mb=12288, cpu_slots=4, child_process_slots=6,
                 full_check_interval_seconds=300):
        self.directory = host._safe_path(runtime_directory, directory=True)
        self.identity = host._root_identity(self.directory)
        ledger = host._safe_path(resource_ledger)
        descriptor = os.open(ledger, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > host.MAX_LEDGER_BYTES:
                raise LegacySpanResourceError("invalid resource ledger")
            raw = stream.read(host.MAX_LEDGER_BYTES + 1)
        try:
            state = json.loads(raw, object_pairs_hook=host._json_pairs)
            roots = [row["path"] for row in state["roots"]]
        except (ValueError, TypeError, KeyError) as exc:
            raise LegacySpanResourceError("invalid resource ledger roots") from exc
        if not any(self.directory == Path(root) or Path(root) in self.directory.parents for root in roots):
            raise LegacySpanResourceError("runtime directory is outside the resource ledger roots")
        self.memory_mb = _positive(memory_mb, "memory_mb")
        self.storage_bytes = _positive(storage_bytes, "storage_bytes")
        _positive(cpu_slots, "cpu_slots")
        _positive(child_process_slots, "child_process_slots")
        if (type(full_check_interval_seconds) not in (int, float)
                or not math.isfinite(full_check_interval_seconds) or full_check_interval_seconds <= 0):
            raise LegacySpanResourceError("invalid full ledger check interval")
        self.interval = float(full_check_interval_seconds)
        self.reservation = host.DaemonResourceReservation(
            ledger, roots=roots, storage_bytes=self.storage_bytes, memory_mb=self.memory_mb,
            cpu_slots=cpu_slots, child_process_slots=child_process_slots,
            timeout_seconds=0, ledger_lock_timeout_seconds=60)
        self._opened = False
        self._next_full = 0.0

    def open(self):
        if self._opened:
            raise LegacySpanResourceError("campaign resources are already open")
        self.reservation.__enter__()
        self._opened = True
        try:
            self.check_limits(full=True)
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    __enter__ = open

    def attach_child(self, child_pid):
        if not self._opened:
            raise LegacySpanResourceError("campaign resource reservation is not open")
        value = self.reservation.check_usage(self.directory, child_pid=child_pid)
        self._next_full = time.monotonic() + self.interval
        return value

    def check_limits(self, *, full=False):
        if not self._opened:
            raise LegacySpanResourceError("campaign resource reservation is not open")
        if host._root_identity(self.directory) != self.identity:
            raise LegacySpanResourceError("campaign directory identity changed")
        group = host._group_usage(self.reservation._child)
        owner = host._process(os.getpid())
        if owner is None:
            raise LegacySpanResourceError("owner process telemetry unavailable")
        rss = group["rss_bytes"] + owner["rss_bytes"]
        if rss > self.memory_mb * 1024 * 1024:
            raise LegacySpanResourceError("campaign owner and child RSS limit exceeded")
        if group["live_processes"] > self.reservation.child_process_slots:
            raise LegacySpanResourceError("campaign child process limit exceeded")
        attempt = host._inventory([self.directory], strict=True)
        external = sum(host._external_charges(self.reservation._record).values())
        if attempt["apparent_bytes"] + external > self.storage_bytes:
            raise LegacySpanResourceError("campaign storage limit exceeded")
        result = {
            "scope": "owned_runtime_and_process_group", "attempt_bytes": attempt["apparent_bytes"],
            "external_charged_bytes": external, "owner_and_child_rss_bytes": rss,
            "group_rss": group, "checked_at": time.time(), "full_ledger_check": False,
            "host_global_gpu_reservation": False,
        }
        if full or time.monotonic() >= self._next_full:
            result["ledger_usage"] = self.reservation.check_usage(self.directory)
            self._next_full = time.monotonic() + self.interval
            result["full_ledger_check"] = True
        return result

    def close(self, *, artifacts_durable=False):
        if not self._opened:
            raise LegacySpanResourceError("campaign resource reservation is not open")
        value = self.reservation.finalize(self.directory, artifacts_durable=artifacts_durable)
        self._opened = False
        return value

    def __exit__(self, exc_type, exc, traceback):
        if self._opened:
            try:
                self.reservation.__exit__(exc_type, exc, traceback)
            finally:
                self._opened = False
        return False


__all__ = ["LegacySpanResourceError", "LegacySpanCampaignResources", "CudaDeviceBudget",
           "cuda_memory_snapshot", "admit_cuda_device"]
