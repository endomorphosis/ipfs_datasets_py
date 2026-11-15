"""Owner-thread supervision for original campaign workers, without replay.

The owner admits resources and durably records both callbacks. Only this exact
executor launches the fixed offline bootstrap; test executors are separate.
Reservation release and original worker-receipt validation belong to the owner.
"""
from __future__ import annotations

from concurrent.futures import Future
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .autoencoder_daemon_invocation import _terminate
from .autoencoder_daemon_invocation_contracts import (
    canonical, describe, execution_environment, parse_json, read_json, reference,
    safe_path, verify,
)
from .autoencoder_daemon_resources import DaemonResourceReservation, _group_usage, _process
from .autoencoder_training_worker import CAMPAIGN_SCHEMA_VERSION, TrainingJobSpec

WORKER_SCRIPT = Path(__file__).with_name("autoencoder_campaign_process_worker.py")
NETWORK_SCRIPT = Path(__file__).with_name("autoencoder_daemon_invocation_worker.py")
F18_SCRIPT = Path(__file__).with_name("autoencoder_campaign_f18_conditions_v1.py")
MAX_JOB_BYTES = 64 * 1024 * 1024
MAX_READY_BYTES = 8192
READY_SCHEMA = "autoencoder-campaign-process-ready-v1"
USAGE_CHECK_INTERVAL_SECONDS = 5.0


class CampaignProcessError(RuntimeError):
    """The worker did not complete under its recorded execution boundary."""


def _require(condition, message):
    if not condition:
        raise CampaignProcessError(message)


def _f18_owner():
    # A closed fixed owner, never a caller-selected module or callback. The
    # parent may parse the job without importing its numerical implementation.
    source = describe(F18_SCRIPT, 1024 * 1024)
    from . import autoencoder_campaign_f18_conditions_v1 as owner
    _require(Path(owner.__file__).resolve() == F18_SCRIPT.resolve(),
             "fixed F18 owner origin differs")
    _require(describe(F18_SCRIPT, 1024 * 1024) == source,
             "fixed F18 owner changed during import")
    return owner, source


class _CampaignProcessExecutor:
    """Private exact-type native boundary; all methods run on the owner thread.

    ``record_start(spec, lease, artifact)`` must persist start intent before
    spawn. ``record_child(spec, lease, artifact, identity)`` must persist the
    observed isolated process and bootstrap evidence before compute release.
    Neither callback may launch work or alter the original job. No callback or
    factory replaces the fixed child entry point.
    """

    def __init__(self, *, record_start, record_child, timeout_seconds,
                 defer_target_hydration_gc=False, reduce_native_targets=False,
                 max_workers=4):
        _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
                 and 0 < timeout_seconds <= 86400, "invalid supervision timeout")
        _require(type(max_workers) is int and 1 <= max_workers <= 4, "invalid worker capacity")
        _require(type(defer_target_hydration_gc) is bool and type(reduce_native_targets) is bool,
                 "invalid native execution policy")
        _require(callable(record_start) and callable(record_child), "durable callbacks are required")
        self.defer_target_hydration_gc = defer_target_hydration_gc
        self.reduce_native_targets = reduce_native_targets
        self.max_workers = max_workers
        self._record_start, self._record_child = record_start, record_child
        self._owner_pid, self._owner_thread = os.getpid(), threading.get_ident()
        self._deadline = time.monotonic() + timeout_seconds
        self._sources = tuple(describe(path, 1024 * 1024) for path in
                              (Path(__file__), WORKER_SCRIPT, NETWORK_SCRIPT))
        self._jobs = {}
        self._retired = {}
        self._closed = False

    def _owner(self):
        _require(os.getpid() == self._owner_pid and threading.get_ident() == self._owner_thread,
                 "supervision must remain on its creating owner thread")

    def _sources_current(self):
        for item in self._sources:
            verify(item, 1024 * 1024)

    def _remaining(self):
        remaining = self._deadline - time.monotonic()
        _require(remaining > 0, "campaign execution exceeded its wall deadline")
        return remaining

    def register(self, spec, *, reservation, attempt_directory, job_artifact, usage_check=None):
        self._owner()
        _require(not self._closed, "executor is closed")
        self._remaining()
        _require(isinstance(spec, TrainingJobSpec) and spec.schema_version == CAMPAIGN_SCHEMA_VERSION,
                 "owned process execution requires an original v8 job")
        self._register_validated(spec, reservation=reservation, attempt_directory=attempt_directory,
                                 job_artifact=job_artifact, usage_check=usage_check, f18=False)

    def register_f18(self, spec, *, reservation, attempt_directory, job_artifact, usage_check=None):
        """Register only the fixed F18 profile with the original process owner.

        This validates plumbing, not native admission. The creating controller
        retains the real reservation, durable callbacks and final accounting.
        """
        self._owner()
        _require(not self._closed, "executor is closed")
        self._remaining()
        owner, source = _f18_owner()
        _require(type(spec) is owner.F18JobSpec and spec.to_dict()["schema_version"] == owner.SCHEMA_VERSION,
                 "owned F18 process requires the fixed F18 job")
        _require(spec.legal_ir_parallel_workers == 1 and self.max_workers == 1,
                 "fixed F18 execution requires one worker")
        _require(not self.defer_target_hydration_gc and not self.reduce_native_targets,
                 "v8 execution flags are unsupported for F18")
        _require(type(reservation) is DaemonResourceReservation,
                 "literal original resource reservation required for F18")
        self._register_validated(spec, reservation=reservation, attempt_directory=attempt_directory,
                                 job_artifact=job_artifact, usage_check=usage_check, f18=True)
        verify(source, 1024 * 1024)
        if source not in self._sources:
            self._sources += (source,)

    def _register_validated(self, spec, *, reservation, attempt_directory, job_artifact, usage_check, f18):
        _require(spec.run_id not in self._jobs and spec.run_id not in self._retired,
                 "job was already registered; retries require recovery")
        _require(isinstance(reservation, DaemonResourceReservation), "real resource reservation required")
        _require(usage_check is None or callable(usage_check), "invalid owner usage callback")
        artifact = reference(dict(job_artifact), MAX_JOB_BYTES, with_path=True)
        raw = verify(artifact, MAX_JOB_BYTES)
        parsed = (_f18_owner()[0].F18JobSpec.from_dict(parse_json(raw)) if f18
                  else TrainingJobSpec.from_dict(parse_json(raw)))
        _require(parsed.canonical_sha256 == spec.canonical_sha256,
                 "registered job bytes differ from original spec")
        attempt = safe_path(attempt_directory)
        _require(attempt.is_dir() and not any(attempt.iterdir()), "control attempt must be exclusive and empty")
        output = safe_path(spec.output_directory, exists=False)
        _require(not os.path.lexists(output), "original worker output already exists")
        _require(attempt != output and attempt not in output.parents and output not in attempt.parents,
                 "worker output and control attempt must be disjoint")
        for existing in self._jobs.values():
            other = existing["attempt"]
            _require(attempt != other and attempt not in other.parents and other not in attempt.parents,
                     "control attempts overlap")
        self._sources_current()
        item = {
            "spec": spec, "digest": spec.canonical_sha256, "artifact": artifact,
            "reservation": reservation, "attempt": attempt, "usage_check": usage_check,
            "future": None, "process": None, "identity": None, "reader": None,
            "release": None, "log": None, "ready": b"", "released": False,
            "stopped": False, "next_usage_at": 0.0, "f18": f18,
        }
        self._usage(item, force=True)
        self._jobs[spec.run_id] = item

    def _job(self, spec):
        item = self._jobs.get(spec.run_id)
        _require(item is not None and item["digest"] == spec.canonical_sha256,
                 "job is not registered with these exact bytes")
        return item

    def _usage(self, item, *, force=False, child_pid=None):
        if not force and time.monotonic() < item["next_usage_at"]:
            return
        item["reservation"].check_usage(item["attempt"], child_pid=child_pid)
        if item["usage_check"] is not None:
            item["usage_check"]()
        # Global storage census is intentionally not repeated at every short
        # future/lease poll. Boundary checks bypass this routine cadence.
        item["next_usage_at"] = time.monotonic() + USAGE_CHECK_INTERVAL_SECONDS

    def submit(self, spec, *, lease, job_artifact):
        self._owner()
        _require(not self._closed, "executor is closed")
        remaining = self._remaining()
        item = self._job(spec)
        _require(item["future"] is None, "recorded start cannot be retried")
        _require(sum(x["future"] is not None and not x["future"].done()
                     for x in self._jobs.values()) < self.max_workers, "worker capacity exceeded")
        _require(dict(job_artifact) == item["artifact"], "submitted job artifact differs")
        _require(type(lease) is dict and lease.get("run_id") == spec.run_id,
                 "claimed lease differs from job")
        self._sources_current()
        verify(item["artifact"], MAX_JOB_BYTES)
        safe_path(spec.output_directory, exists=False)
        _require(not os.path.lexists(spec.output_directory), "original worker output already exists")
        self._usage(item, force=True)
        item["lease"] = parse_json(canonical(lease))
        item["future"] = Future()
        item["future"].set_running_or_notify_cancel()
        # A callback failure is still a consumed start: never silently respawn.
        self._record_start(spec, item["lease"], dict(item["artifact"]))
        ready_write = release_read = None
        try:
            item["reader"], ready_write = os.pipe()
            release_read, item["release"] = os.pipe()
            os.set_blocking(item["reader"], False)
            item["log"] = (item["attempt"] / "worker.log").open("xb")
            environment = execution_environment()
            workers = str(spec.legal_ir_parallel_workers if item["f18"]
                          else spec.training_config.legal_ir_parallel_workers)
            environment["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] = workers
            environment["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] = workers
            argv = [sys.executable, "-I", "-S", str(WORKER_SCRIPT),
                    item["artifact"]["path"], item["artifact"]["sha256"], str(item["artifact"]["bytes"]),
                    spec.canonical_sha256, str(ready_write), str(release_read), str(self._owner_pid),
                    str(min(30.0, remaining)), self._sources[2]["sha256"],
                    str(int(self.defer_target_hydration_gc)), str(int(self.reduce_native_targets))]
            item["process"] = subprocess.Popen(argv, cwd=item["attempt"], env=environment,
                stdin=subprocess.DEVNULL, stdout=item["log"], stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, pass_fds=(ready_write, release_read))
            observed = _process(item["process"].pid)
            _require(observed is not None and observed["parent_pid"] == self._owner_pid
                     and observed["group_pid"] == observed["pid"], "child identity was not observed")
            item["identity"] = {key: observed[key] for key in ("pid", "group_pid", "birth")}
            self._usage(item, force=True, child_pid=observed["pid"])
        finally:
            if ready_write is not None:
                os.close(ready_write)
            if release_read is not None:
                os.close(release_read)
        return item["future"]

    def _ready(self, item):
        try:
            chunk = os.read(item["reader"], MAX_READY_BYTES + 1 - len(item["ready"]))
        except BlockingIOError:
            return
        _require(bool(chunk), "child closed its ready pipe before release")
        item["ready"] += chunk
        _require(len(item["ready"]) <= MAX_READY_BYTES, "child ready message exceeds bound")
        if b"\n" not in item["ready"]:
            return
        _require(item["ready"].count(b"\n") == 1 and item["ready"].endswith(b"\n"),
                 "unexpected child ready framing")
        ready = parse_json(item["ready"])
        _require(type(ready) is dict and set(ready) == {
            "schema", "identity", "owner_pid", "job_sha256", "canonical_root", "network_guard",
        }, "unexpected child ready fields")
        observed = _process(item["process"].pid)
        _require(observed is not None and observed["parent_pid"] == self._owner_pid
                 and {key: observed[key] for key in ("pid", "group_pid", "birth")} == item["identity"]
                 and ready["identity"] == item["identity"], "child ready process identity differs")
        guard = ready["network_guard"]
        _require(ready["schema"] == READY_SCHEMA and ready["owner_pid"] == self._owner_pid
                 and ready["job_sha256"] == item["artifact"]["sha256"]
                 and ready["canonical_root"] == str(WORKER_SCRIPT.resolve().parents[3])
                 and guard == {"mechanism": "linux_seccomp", "denied_syscalls": [
                     "socket", "connect", "sendto", "sendmsg", "sendmmsg"], "socket_denial_verified": True},
                 "child bootstrap evidence differs")
        self._sources_current()
        verify(item["artifact"], MAX_JOB_BYTES)
        self._usage(item, force=True)
        self._remaining()
        evidence = {**item["identity"], "bootstrap": ready}
        self._record_child(item["spec"], item["lease"], dict(item["artifact"]), evidence)
        self._sources_current()
        verify(item["artifact"], MAX_JOB_BYTES)
        self._remaining()
        _require(os.write(item["release"], b"RUN\n") == 4, "compute release token was not fully written")
        item["released"] = True
        os.close(item["reader"])
        item["reader"] = None

    def poll(self):
        self._owner()
        _require(not self._closed, "executor is closed")
        self._remaining()
        for item in self._jobs.values():
            future, process = item["future"], item["process"]
            if future is None or future.done() or process is None:
                # A finished child still owns replay/staging costs until the
                # owner explicitly retires its confirmed-dead context.
                self._sources_current()
                self._usage(item)
                continue
            try:
                self._sources_current()
                self._usage(item)
                if not item["released"]:
                    self._ready(item)
                code = process.poll()
                if code is None:
                    continue
                _require(item["released"], "child exited before compute release")
                _require(code == 0, f"original worker exited with status {code}")
                _require(not _group_usage(item["identity"])["live_processes"],
                         "worker returned with live descendants")
                process.wait(timeout=1)
                result = read_json(Path(item["spec"].output_directory) / "receipt.json", MAX_JOB_BYTES)
                if item["f18"]:
                    result = _f18_owner()[0].validate_receipt(
                        item["spec"], result, job_file_sha256=item["artifact"]["sha256"])
                self._sources_current()
                verify(item["artifact"], MAX_JOB_BYTES)
                self._usage(item, force=True)
                self._remaining()
                self._finish_handles(item)
                item["stopped"] = True
                future.set_result(result)
            except BaseException as exc:
                # Uncertain group cleanup propagates; it never becomes a clean
                # worker failure or authorizes reservation release.
                self.stop(item["spec"], _error=exc)

    @staticmethod
    def _finish_handles(item):
        for name in ("reader", "release"):
            if item[name] is not None:
                os.close(item[name])
                item[name] = None
        if item["log"] is not None:
            item["log"].flush()
            os.fsync(item["log"].fileno())
            item["log"].close()
            item["log"] = None

    def stop(self, spec, *, _error=None):
        self._owner()
        if spec.run_id in self._retired:
            _require(self._retired[spec.run_id] == spec.canonical_sha256,
                     "retired job identity differs")
            return
        item = self._job(spec)
        if item["stopped"]:
            return
        # EOF also terminates a waiting or released child through its own guard.
        if item["release"] is not None:
            os.close(item["release"])
            item["release"] = None
        process = item["process"]
        if process is not None:
            _require(item["identity"] is not None, "spawned child identity is unconfirmed; recovery required")
            _terminate(process, item["identity"])
            process.wait(timeout=1)
            _require(not _group_usage(item["identity"])["live_processes"],
                     "worker group death is unconfirmed")
        self._finish_handles(item)
        item["stopped"] = True
        future = item["future"]
        if future is not None and not future.done():
            future.set_exception(_error or CampaignProcessError("original worker was stopped"))

    def retire(self, spec):
        """Stop monitoring a dead context after the owner's terminal accounting.

        This does not release a reservation. A tombstone forbids registering
        the same run again through this executor even after its context closes.
        """
        self._owner()
        if spec.run_id in self._retired:
            _require(self._retired[spec.run_id] == spec.canonical_sha256,
                     "retired job identity differs")
            return
        item = self._job(spec)
        _require(item["stopped"] and (item["future"] is None or item["future"].done()),
                 "only a confirmed-dead terminal context can retire")
        _require(not _group_usage(item["identity"])["live_processes"], "retired group is still alive")
        self._sources_current()
        self._usage(item, force=True)
        self._retired[spec.run_id] = item["digest"]
        del self._jobs[spec.run_id]

    def close(self):
        self._owner()
        failures = []
        for item in self._jobs.values():
            try:
                self.stop(item["spec"])
            except BaseException as exc:
                failures.append(exc)
        if failures:
            raise CampaignProcessError("one or more worker groups require explicit recovery") from failures[0]
        self._closed = True
import json


class _ReviewedParentCallbackServer:
    """Relay this parent's existing checks; never acquire or release custody.

    The caller transfers ownership of one socketpair endpoint on successful
    construction. poll() is nonblocking and handles at most one bounded request
    or pending acknowledgement. The original caller retains RUN and reaps its
    original Popen. Observations here do not authenticate synthetic callers.
    """

    def __init__(self, fd, *, owner, child_identity, owner_identity, request_sha256,
                 deadline, source_guard, asset_policy_guard, current_admission_provider,
                 current_training_admission_provider=None, context_policy_guard=None):
        import stat
        from . import autoencoder_campaign_process_worker as protocol
        _require(type(fd) is int and fd >= 3, "private reviewed parent callback descriptor required")
        info = os.fstat(fd)
        _require(stat.S_ISSOCK(info.st_mode), "reviewed callback server requires an inherited socket endpoint")
        _require(isinstance(owner, DaemonResourceReservation), "original live daemon reservation required")
        _require(all(callable(callback) for callback in
            (source_guard, asset_policy_guard, current_admission_provider)), "original live callback policies required")
        context_callbacks = (current_training_admission_provider, context_policy_guard)
        rich_context = any(callback is not None for callback in context_callbacks)
        _require(not rich_context or all(map(callable, context_callbacks)), "original live TRAIN context callbacks required")
        self._owner_identity = protocol._reviewed_callback_identity(owner_identity)
        self._child_identity = protocol._reviewed_callback_identity(child_identity)
        self._request = protocol._reviewed_callback_digest(request_sha256)
        _require(self._owner_identity["pid"] == os.getpid()
                 and getattr(owner, "_owner_pid", None) == os.getpid()
                 and getattr(owner, "_entered", False) is True
                 and type(getattr(owner, "_record", None)) is dict
                 and owner._record.get("status") == "active"
                 and owner._record.get("owner_pid") == os.getpid()
                 and getattr(owner, "_lease", None) is not None
                 and getattr(owner, "_child", None) == self._child_identity
                 and owner._record.get("child") == self._child_identity,
                 "original reservation/recorded child is not live for this parent")
        _require(type(deadline) in (int, float) and math.isfinite(deadline)
                 and 0 < deadline - time.monotonic() <= 86400,
                 "original absolute parent callback deadline required")
        self._fd, self._fd_identity = fd, (info.st_dev, info.st_ino, info.st_mode)
        self._owner, self._original_lease = owner, owner._lease
        self._reservation_id = owner.reservation_id
        self._storage_bytes = owner.storage_bytes
        lane, workload = owner._scheduler_identity()
        self._lane, self._workload = lane.value, workload
        self._native_identity = None
        self._native_binding()
        self._creator = (os.getpid(), threading.get_ident())
        self._deadline = deadline
        self._source_guard, self._asset_policy = source_guard, asset_policy_guard
        self._admission_provider = current_admission_provider
        self._training_admission_provider, self._context_policy = context_callbacks
        self._protocol = protocol
        self._next_heartbeat = 0.0
        self._sequence = 0
        self._buffer, self._pending = b"", None
        self._closed = False
        self._finished = False
        self._record = {"schema": "reviewed-parent-callback-server-observation/v1",
            "received_requests": 0, "acknowledged_requests": 0,
            "operations": {"GUARD": 0, "ASSET": 0, "ADMISSION": 0, "FINISH": 0},
            "last_error": None, "resource_authority_granted": False,
            "storage_release_authorized": False, "reservation_entered_or_released": False}
        if rich_context:
            self._record["operations"].update(TRAIN_ADMISSION=0, CONTEXT=0)
        os.set_blocking(fd, False)
        os.set_inheritable(fd, False)

    def _channel_current(self):
        _require(not self._closed and self._creator == (os.getpid(), threading.get_ident()),
                 "reviewed callback server moved from its original owner thread or closed")
        _require(time.monotonic() < self._deadline, "original parent callback deadline expired")
        info = os.fstat(self._fd)
        _require((info.st_dev, info.st_ino, info.st_mode) == self._fd_identity,
                 "reviewed parent callback descriptor changed")

    def _native_binding(self):
        owner, lease = self._owner, self._owner._lease
        _require(lease is self._original_lease and type(getattr(lease, "lease_id", None)) is str
                 and 0 < len(lease.lease_id) <= 128 and lease.lane == self._lane
                 and type(lease.owner_pid) is int and lease.owner_pid == self._owner_identity["pid"]
                 and lease.parent_lease_id is None and lease.requires_gpu is False
                 and getattr(lease, "_released", None) is False,
                 "original native root lease identity differs")
        values = [lease.lease_id, lease.lane, lease.owner_pid, lease.parent_lease_id, lease.requires_gpu]
        for name in ("cpu_slots", "memory_mb", "child_process_slots"):
            expected = getattr(owner, name)
            _require(type(expected) is int and expected > 0
                     and type(getattr(lease, name)) is int and getattr(lease, name) == expected
                     and type(owner._record.get(name)) is int and owner._record[name] == expected,
                     "original native/recorded resource budget differs")
            values.append(expected)
        _require(owner._record.get("reservation_id") == self._reservation_id
                 and type(owner.storage_bytes) is int and owner.storage_bytes == self._storage_bytes
                 and type(owner._record.get("storage_bytes")) is int
                 and owner._record["storage_bytes"] == self._storage_bytes and self._storage_bytes > 0
                 and owner._record.get("scheduler_lane") == self._lane
                 and owner._record.get("workload") == self._workload
                 and ("native_lease_id" not in owner._record
                      or owner._record["native_lease_id"] == lease.lease_id),
                 "original native lease/ledger purpose binding differs")
        identity = tuple(values)
        _require(self._native_identity is None or identity == self._native_identity,
                 "original native callback lease was replaced or rearmed")
        self._native_identity = identity

    def _guard_parent(self):
        """Original live checks, also usable after FINISH and genuine child reap."""
        _require(self._creator == (os.getpid(), threading.get_ident())
                 and time.monotonic() < self._deadline, "original parent callback owner/deadline changed")
        self._source_guard()
        owner = self._owner
        _require(owner._owner_pid == self._owner_identity["pid"] and owner._entered is True
                 and owner._lease is self._original_lease and owner.reservation_id == self._reservation_id
                 and type(owner._record) is dict and owner._record.get("status") == "active"
                 and owner._record.get("owner_pid") == self._owner_identity["pid"]
                 and owner._child == self._child_identity and owner._record.get("child") == self._child_identity,
                 "original reviewed callback reservation or child binding changed")
        self._native_binding()
        parent = _process(self._owner_identity["pid"])
        _require(parent is not None and type(parent.get("state")) is str
                 and parent["state"] not in ("Z", "X", "x")
                 and {key: parent[key] for key in self._owner_identity} == self._owner_identity,
                 "original reviewed callback parent birth changed")
        original_guard = getattr(owner, "guard", None)
        if callable(original_guard):
            original_guard()
        else:
            owner._verify_owner_roots()
        _require(not owner.cancelled, "original reviewed callback native custody cancelled")
        if time.monotonic() >= self._next_heartbeat:
            _require(owner.heartbeat(), "original reviewed callback heartbeat lost")
            self._next_heartbeat = time.monotonic() + 1.0
        _require(not owner.cancelled, "original reviewed callback native custody cancelled after heartbeat")
        local_check = getattr(owner, "check_limits", None)
        if callable(local_check):
            local_check(full=False)
        else:
            group = _group_usage(self._child_identity)
            _require(group.get("available") is True
                     and type(group.get("rss_bytes")) is int and 0 <= group["rss_bytes"] <= owner.memory_mb * 1024**2
                     and type(group.get("live_processes")) is int
                     and 0 <= group["live_processes"] <= owner.child_process_slots,
                     "original reviewed callback local group resource bound exceeded")
        self._source_guard()
        parent = _process(self._owner_identity["pid"])
        _require(self._creator == (os.getpid(), threading.get_ident()) and time.monotonic() < self._deadline
                 and owner._entered is True and owner._lease is self._original_lease
                 and owner.reservation_id == self._reservation_id and owner._record.get("status") == "active"
                 and owner._child == self._child_identity and owner._record.get("child") == self._child_identity
                 and not owner.cancelled and parent is not None and type(parent.get("state")) is str
                 and parent["state"] not in ("Z", "X", "x")
                 and {key: parent[key] for key in self._owner_identity} == self._owner_identity,
                 "original reviewed callback parent custody changed after local checks")
        self._native_binding()

    def _original_current(self):
        self._channel_current()
        self._guard_parent()
        child = _process(self._child_identity["pid"])
        _require(child is not None and type(child.get("state")) is str and child["state"] not in ("Z", "X", "x")
                 and {key: child[key] for key in self._child_identity} == self._child_identity
                 and child["parent_pid"] == self._owner_identity["pid"]
                 and child["group_pid"] == self._child_identity["pid"],
                 "original recorded Popen child identity changed")
        self._channel_current()

    def _flush(self, *, checked=False):
        if not checked:
            self._original_current()
        pending = self._pending
        try:
            count = os.write(self._fd, pending["raw"][pending["offset"]:])
        except BlockingIOError:
            return False
        _require(count > 0, "reviewed callback acknowledgement endpoint closed")
        pending["offset"] += count
        if pending["offset"] != len(pending["raw"]):
            return False
        self._sequence = pending["sequence"]
        self._record["acknowledged_requests"] += 1
        self._record["operations"][pending["operation"]] += 1
        finish = pending["operation"] == "FINISH"
        self._pending = None
        if finish:
            self._finished = True
            self.close()
        return True

    def poll(self):
        """Process one available frame; return False while idle or incomplete."""
        try:
            self._channel_current()
            if self._pending is not None:
                return self._flush()
            try:
                chunk = os.read(self._fd, self._protocol._REVIEWED_CALLBACK_MAX_REQUEST + 1 - len(self._buffer))
            except BlockingIOError:
                return False
            if not chunk:
                raise EOFError("reviewed child callback endpoint closed")
            self._buffer += chunk
            _require(len(self._buffer) <= self._protocol._REVIEWED_CALLBACK_MAX_REQUEST,
                     "reviewed child callback request exceeds bound")
            if b"\n" not in self._buffer:
                return False
            frame = self._protocol._reviewed_callback_decode(self._buffer,
                self._protocol._REVIEWED_CALLBACK_MAX_REQUEST)
            self._buffer = b""
            _require(type(frame) is dict and set(frame) == {"schema", "request_sha256", "sequence",
                "operation", "owner_identity", "child_identity", "payload"}
                and frame["schema"] == self._protocol._REVIEWED_CALLBACK_REQUEST
                and frame["request_sha256"] == self._request
                and type(frame["sequence"]) is int and frame["sequence"] == self._sequence + 1
                and frame["sequence"] <= 2**31 - 1
                and self._protocol._reviewed_callback_identity(frame["owner_identity"]) == self._owner_identity
                and self._protocol._reviewed_callback_identity(frame["child_identity"]) == self._child_identity
                and type(frame["operation"]) is str and frame["operation"] in self._record["operations"],
                "closed reviewed callback request binding/sequence differs")
            operation, payload = frame["operation"], frame["payload"]
            if operation in ("GUARD", "FINISH"):
                _require(payload is None, "GUARD/FINISH callback accepts no payload")
            elif operation in ("ASSET", "CONTEXT"):
                _require(type(payload) is dict, operation + " callback requires an ordinary policy mapping")
            else:
                _require(type(payload) is dict and set(payload) == {"expected_sha256"},
                         operation + " callback accepts only its expected digest")
                self._protocol._reviewed_callback_digest(payload["expected_sha256"])
            self._record["received_requests"] += 1
            self._original_current()
            admission_sha256 = None
            if operation == "ASSET":
                self._asset_policy(json.loads(self._protocol._reviewed_callback_encode(payload,
                    self._protocol._REVIEWED_CALLBACK_MAX_REQUEST)))
            elif operation == "CONTEXT":
                _require(self._context_policy(payload) is None, "original TRAIN context policy must return None or raise")
            elif operation in ("ADMISSION", "TRAIN_ADMISSION"):
                from .legal_span_consumer_binding import reviewed_admission_inputs_sha256
                provider = self._training_admission_provider if operation == "TRAIN_ADMISSION" else self._admission_provider
                admission_sha256 = reviewed_admission_inputs_sha256(provider())
                _require(admission_sha256 == payload["expected_sha256"],
                         "parent current admission digest differs from child expectation" if operation == "ADMISSION"
                         else "parent current TRAIN admission digest differs from child expectation")
            self._original_current()
            reply = {"schema": self._protocol._REVIEWED_CALLBACK_REPLY,
                "request_sha256": self._request, "sequence": frame["sequence"], "operation": operation,
                "owner_identity": self._owner_identity, "child_identity": self._child_identity,
                "admission_sha256": admission_sha256}
            self._pending = {"raw": self._protocol._reviewed_callback_encode(reply,
                self._protocol._REVIEWED_CALLBACK_MAX_REPLY), "offset": 0,
                "sequence": frame["sequence"], "operation": operation}
            return self._flush(checked=True)
        except BaseException as error:
            self._record["last_error"] = {"type": type(error).__name__, "message": str(error)[:512]}
            self.close()
            raise

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                info = os.fstat(self._fd)
            except OSError:
                self._record["rpc_descriptor_closed_elsewhere"] = True
                return
            if (info.st_dev, info.st_ino, info.st_mode) != self._fd_identity:
                self._record["rpc_descriptor_identity_changed"] = True
                return
            os.close(self._fd)

    @property
    def finished(self):
        return self._finished

    def observation(self):
        return json.loads(json.dumps({**self._record, "closed": self._closed,
            "finished": self._finished,
            "request_sha256": self._request, "last_sequence": self._sequence,
            "owner_identity": self._owner_identity, "child_identity": self._child_identity,
            "pending_acknowledgement": self._pending is not None,
            "original_deadline_monotonic": self._deadline}, sort_keys=True, allow_nan=False))
