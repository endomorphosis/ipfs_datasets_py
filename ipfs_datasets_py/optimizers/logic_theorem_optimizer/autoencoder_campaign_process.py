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
MAX_JOB_BYTES = 64 * 1024 * 1024
MAX_READY_BYTES = 8192
READY_SCHEMA = "autoencoder-campaign-process-ready-v1"
USAGE_CHECK_INTERVAL_SECONDS = 5.0


class CampaignProcessError(RuntimeError):
    """The worker did not complete under its recorded execution boundary."""


def _require(condition, message):
    if not condition:
        raise CampaignProcessError(message)


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
        _require(spec.run_id not in self._jobs and spec.run_id not in self._retired,
                 "job was already registered; retries require recovery")
        _require(isinstance(reservation, DaemonResourceReservation), "real resource reservation required")
        _require(usage_check is None or callable(usage_check), "invalid owner usage callback")
        artifact = reference(dict(job_artifact), MAX_JOB_BYTES, with_path=True)
        raw = verify(artifact, MAX_JOB_BYTES)
        _require(TrainingJobSpec.from_dict(parse_json(raw)).canonical_sha256 == spec.canonical_sha256,
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
            "stopped": False, "next_usage_at": 0.0,
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
            workers = str(spec.training_config.legal_ir_parallel_workers)
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
