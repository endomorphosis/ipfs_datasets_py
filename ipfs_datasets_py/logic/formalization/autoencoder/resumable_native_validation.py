"""Bounded local retries for observed pre-execution native lease timeouts.

Existing native owners retain parsing, Lake, live handles and resource safety.
Saved successes remain archived evidence; they never become live observations.
Interrupted in-flight rounds are ambiguous and are deliberately not replayed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType

from . import family_training as core
from ....optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ....optimizers.logic_theorem_optimizer import proof_resource_safety as safety

SCHEMA = "resumable-native-validation/v1"
FALSE = dict(admitted=False, qualified=False, formalized=False, proof_authority=False,
    execution_authority=False, source_semantics_verified=False, training_executed=False,
    model_inference_executed=False, checkpoint_promoted=False)
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_MAX_JSON = 128 * 1024 * 1024


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _guard():
    _require(_file_sha(Path(__file__)) == _SOURCE_SHA, "resume wrapper changed after import")


@dataclass(frozen=True)
class NativeValidationOwner:
    """Explicit versioned module contract; no arbitrary callback namespace."""
    module_name: str
    source_sha256: str
    schema: str
    native_schema: str
    validation_schema: str
    policy_sha256: str
    producer_sha256: tuple

    @classmethod
    def from_module(cls, module):
        _guard()
        _require(type(module) is ModuleType and module.__name__ in {
            "ipfs_datasets_py.logic.formalization.autoencoder.parallel_projection_checks_v2",
            "ipfs_datasets_py.logic.formalization.autoencoder.parallel_projection_checks_v3"},
            "explicit versioned native parallel owner module required")
        _require(importlib.import_module(module.__name__) is module,
            "selected native owner is not its imported module")
        root = Path(__file__).resolve().parents[4]
        _require(root in Path(module.__file__).resolve().parents,
            "native owner resolved outside selected workspace tree")
        from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
        digest = _pin_imported_module(module)
        module._guard()
        _require(module.resources is resources, "native owner uses a different scheduler module")
        policies = {domain: module.validation.domain_projection_policy(domain)
                    for domain in core.DOMAINS}
        return cls(module.__name__, digest, module.SCHEMA, module.native.SCHEMA,
            module.validation.SCHEMA, _digest(policies), tuple(sorted(module._PINS.items())))


def _resolve_owner(owner):
    _require(type(owner) is NativeValidationOwner, "typed immutable NativeValidationOwner required")
    module = importlib.import_module(owner.module_name)
    _require(NativeValidationOwner.from_module(module) == owner, "native owner or fixed policy drift")
    return module


def _read(path):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= _MAX_JSON,
            "bounded regular durable validation artifact required")
    return json.loads(path.read_bytes())


def _write(path, value):
    content = _raw(value) + b"\n"
    _require(len(content) <= _MAX_JSON, "durable validation artifact exceeds bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".native-resume-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _save_manifest(root, manifest):
    value = {key: item for key, item in manifest.items() if key != "manifest_sha256"}
    value["manifest_sha256"] = _digest(value)
    _write(root / "manifest.json", value)
    # The returned receipt must carry the same seal as the durable file, also
    # after a resumed invocation updates usage and live-handle availability.
    manifest.clear()
    manifest.update(value)


def _configuration(scheduler):
    _require(isinstance(scheduler, resources.GlobalResourceScheduler)
        and scheduler.config.proof_safety_enabled is True,
        "shared scheduler with unchanged proof safety required")
    return {"state_path": str(scheduler.state_path.resolve()),
        "policy": scheduler.config.persisted_dict(),
        "lease_ttl_seconds": scheduler.config.lease_ttl_seconds,
        "auto_renew_leases": scheduler.config.auto_renew_leases}


def _telemetry(scheduler):
    value = {"scheduler": scheduler.snapshot(),
        "sampling_scope": "observational_host_sample_not_a_substitute_for_scheduler_admission"}
    try:
        value["host_pressure"] = asdict(safety.collect_proof_host_resources())
    except Exception as error:
        value["host_pressure_error"] = {"type": type(error).__name__, "reason": str(error)[:512]}
    return value


class AdmissionBudgetExpired(RuntimeError):
    """No new resource admission started after the wrapper budget expired."""


class _ObservedScheduler(resources.GlobalResourceScheduler):
    """Delegate every admission to the same real scheduler and record stages."""
    def __init__(self, actual, events_path, allowed, deadline):
        self._actual = actual
        self.config, self.state_path = actual.config, actual.state_path
        self._config = _configuration(actual)
        self._sampler = actual.config.proof_resource_sampler
        self._events_path, self._allowed, self._deadline = events_path, set(allowed), deadline
        self._lock = threading.Lock()
        self.events = []

    def _check(self):
        _require(self.config is self._actual.config and _configuration(self._actual) == self._config
            and self._sampler is self.config.proof_resource_sampler, "scheduler safety/configuration changed")

    def snapshot(self):
        self._check()
        return self._actual.snapshot()

    def _record(self, identity, phase, **values):
        with self._lock:
            row = {"job_id": identity, "phase": phase, "monotonic_seconds": time.monotonic(),
                "telemetry": _telemetry(self._actual), **values}
            self.events.append(row)
            with self._events_path.open("ab") as handle:
                handle.write(_raw(row) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())

    def acquire(self, lane, **options):
        self._check()
        request = options.get("request_id", "")
        _require(type(request) is str and request.startswith("native:")
            and request[7:] in self._allowed and lane == resources.ResourceLane.VALIDATION,
            "only selected native validation lease requests are allowed")
        identity = request[7:]
        if self._deadline is not None:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                self._record(identity, "admission_budget_expired", lease_granted=False)
                raise AdmissionBudgetExpired("new native admission budget expired")
            options["timeout"] = min(options["timeout"], remaining)
        self._record(identity, "lease_wait_started", timeout_seconds=options["timeout"])
        try:
            lease = self._actual.acquire(lane, **options)
        except resources.LeaseTimeoutError as error:
            self._record(identity, "lease_wait_timeout", exception_type=type(error).__name__,
                exact_scheduler_timeout_type=type(error) is resources.LeaseTimeoutError, lease_granted=False)
            raise
        except Exception as error:
            self._record(identity, "lease_admission_failed", exception_type=type(error).__name__, lease_granted=False)
            raise
        try:
            self._check()
            self._record(identity, "lease_granted", lease_granted=True)
        except BaseException:
            lease.release()
            raise
        return lease


def _retryable(identity, receipt, events, batch_directory):
    phases = [row for row in events if row["job_id"] == identity]
    return (receipt.get("status") == "failed" and receipt.get("error_type") == "LeaseTimeoutError"
        and receipt.get("scope") != "owner_call_failed_no_retry"
        and [row["phase"] for row in phases] == ["lease_wait_started", "lease_wait_timeout"]
        and phases[-1].get("exact_scheduler_timeout_type") is True
        and phases[-1].get("lease_granted") is False
        and not any(row.get("lease_granted") is True for row in phases)
        and "native" not in receipt and "projection_validation" not in receipt
        and not (batch_directory / identity).exists())


def _deferred(identity, receipt, events, batch_directory):
    """Known unstarted admission; never equivalent to an uncertain execution."""
    phases = [row for row in events if row["job_id"] == identity]
    return (receipt.get("status") == "failed" and receipt.get("error_type") == "AdmissionBudgetExpired"
        and receipt.get("scope") != "owner_call_failed_no_retry"
        and [row["phase"] for row in phases] == ["admission_budget_expired"]
        and phases[0].get("lease_granted") is False
        and "native" not in receipt and "projection_validation" not in receipt
        and not (batch_directory / identity).exists())


def _binding(job, owner):
    _require(type(job) is owner.NativeProjectionJob, "selected owner's exact NativeProjectionJob required")
    identity = owner._identifier(job.job_id)
    encoded = {"report": _raw(job.report), "source_inputs": _raw(core._json(job.source_inputs)),
               "applicability_review": _raw(core._json(job.applicability_review))}
    _require(all(len(value) <= owner.MAX_ITEM_BYTES for value in encoded.values()), "bounded complete native inputs required")
    return {"job_id": identity, "domain_id": job.report["domain_id"],
        "source_digest": job.report["source_digest"],
        **{key + "_sha256": hashlib.sha256(value).hexdigest() for key, value in encoded.items()},
        "input_bytes": sum(map(len, encoded.values()))}


def _load_rounds(root, manifest, identities, max_attempts):
    states, attempts = {}, {}
    _require(type(manifest["rounds"]) is list and len(manifest["rounds"]) <= max_attempts,
        "bounded durable round inventory required")
    for index, descriptor in enumerate(manifest["rounds"]):
        expected = f"round-{index:04d}/result.json"
        _require(descriptor["path"] == expected, "durable round order/path differs")
        path = root / expected
        _require(not path.parent.is_symlink(), "durable round directory cannot be a symlink")
        _require(_file_sha(path) == descriptor["sha256"], "durable round receipt changed")
        value = _read(path)
        for artifact in value["artifacts"]:
            relative = Path(artifact["path"])
            _require(not relative.is_absolute() and ".." not in relative.parts,
                "unsafe durable native artifact path")
            _require(_file_sha(root / relative) == artifact["sha256"], "durable native artifact changed")
        events_path = root / f"round-{index:04d}/lease-events.jsonl"
        _require(events_path.is_file() and not events_path.is_symlink() and events_path.stat().st_size <= _MAX_JSON,
            "bounded regular lease phase evidence required")
        events = [json.loads(line) for line in events_path.read_bytes().splitlines()]
        _require(events == value["lease_events"], "recorded lease phase evidence differs")
        row_ids = [row["job_id"] for row in value["jobs"]]
        _require(row_ids and len(set(row_ids)) == len(row_ids) and set(row_ids) <= identities,
            "durable round job identities differ")
        for row in value["jobs"]:
            identity = row["job_id"]
            _require(row["receipt"].get("job_id") == identity and row["round"] == index
                and row["attempt"] == attempts.get(identity, 0) + 1
                and (identity not in states or states[identity]["retryable_lease_timeout"] is True
                    or states[identity]["deferred_before_admission"] is True),
                "durable attempt order or previous retry disposition differs")
            actual_retry = _retryable(identity, row["receipt"], events, root / f"round-{index:04d}/batch")
            _require(row["retryable_lease_timeout"] is actual_retry, "durable retry classification differs")
            actual_deferred = _deferred(identity, row["receipt"], events, root / f"round-{index:04d}/batch")
            _require(row["deferred_before_admission"] is actual_deferred, "durable deferral classification differs")
            states[identity] = row
            attempts[identity] = attempts.get(identity, 0) + 1
    return states, attempts


def run_resumable_native_validation(native_jobs, *, owner, output_directory,
        resume=False, scheduler=None, max_attempts_per_job=3, max_admission_seconds=120,
        retry_backoff_seconds=1, max_workers=2, native_memory_mb=1024, native_cpu_slots=2,
        native_child_process_slots=2, lease_wait_timeout_seconds=30, native_step_timeout_seconds=60,
        lake_executable, java_executable=None, tla2tools_jar=None):
    """Resume only recorded pre-execution lease failures; never reload authority.

    The cumulative wall budget stops new admissions and backoff, including the
    first round. Already admitted native steps retain their existing bounds and
    may finish after this budget. No model inference or portfolio jobs run here.
    Resume with identical owners, typed inputs, scheduler policy and settings.
    """
    checks = _resolve_owner(owner)
    _require(type(resume) is bool and type(native_jobs) in (list, tuple) and 1 <= len(native_jobs) <= 384,
        "bounded typed native job sequence and Boolean resume required")
    _require(type(max_attempts_per_job) is int and 1 <= max_attempts_per_job <= 8,
        "one to eight total attempts per job required")
    checks._seconds(max_admission_seconds, "max_admission_seconds", 3600)
    _require(type(retry_backoff_seconds) in (int, float) and math.isfinite(retry_backoff_seconds)
        and 0 <= retry_backoff_seconds <= 60, "zero to sixty seconds bounded backoff required")
    bindings = [_binding(job, checks) for job in native_jobs]
    _require(len({row["job_id"] for row in bindings}) == len(bindings)
        and sum(row["input_bytes"] for row in bindings) <= checks.MAX_BATCH_BYTES,
        "unique job identities and bounded full native batch required")
    scheduler = scheduler or resources.get_global_resource_scheduler()
    config = _configuration(scheduler)
    options = dict(max_workers=max_workers, native_memory_mb=native_memory_mb, native_cpu_slots=native_cpu_slots,
        native_child_process_slots=native_child_process_slots, lease_wait_timeout_seconds=lease_wait_timeout_seconds,
        native_step_timeout_seconds=native_step_timeout_seconds, lake_executable=str(lake_executable),
        java_executable=None if java_executable is None else str(java_executable),
        tla2tools_jar=None if tla2tools_jar is None else str(tla2tools_jar))
    plan = {"schema": SCHEMA, "owner": asdict(owner), "wrapper_sha256": _SOURCE_SHA,
        "jobs": bindings, "scheduler": config, "native_options": options,
        "max_attempts_per_job": max_attempts_per_job, "max_admission_seconds": max_admission_seconds,
        "retry_backoff_seconds": retry_backoff_seconds, **FALSE}
    root = Path(output_directory).absolute()
    _require(not root.is_symlink(), "regular local validation directory required")
    if not resume:
        root.mkdir(parents=True, exist_ok=False)
    else:
        _require(root.is_dir(), "existing durable validation directory required for resume")
    lock_fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if resume:
            saved = _read(root / "plan.json")
            _require(_raw(saved) == _raw(plan), "durable source, report, owner, settings or scheduler policy drift")
            manifest = _read(root / "manifest.json")
            _require(manifest.get("manifest_sha256") == _digest({key: value for key, value in manifest.items()
                if key != "manifest_sha256"}) and manifest["plan_sha256"] == _digest(plan), "durable manifest corrupt")
        else:
            _write(root / "plan.json", plan)
            manifest = {"schema": SCHEMA, "plan_sha256": _digest(plan), "rounds": [], "inflight": None,
                "consumed_admission_seconds": 0, "status": "incomplete", "stopped_reason": "not_started", **FALSE}
            _save_manifest(root, manifest)
        states, attempts = _load_rounds(root, manifest, {row["job_id"] for row in bindings}, max_attempts_per_job)
        live = {}
        invocation_start = time.monotonic()
        consumed_before = manifest["consumed_admission_seconds"]
        _require(type(consumed_before) in (int, float) and math.isfinite(consumed_before) and consumed_before >= 0,
            "durable admission usage must be finite and nonnegative")
        deadline = invocation_start + max(0, max_admission_seconds - consumed_before)
        by_id = {job.job_id: job for job in native_jobs}
        if manifest["inflight"] is not None:
            manifest.update(status="incomplete", stopped_reason="interrupted_inflight_execution_unknown",
                live_validation_complete=False, archived_receipts_are_live_authority=False)
            _save_manifest(root, manifest)
            return {"live_jobs": [], "archived_jobs": list(states.values()),
                "receipt": manifest}
        while True:
            checks = _resolve_owner(owner)
            _require(_configuration(scheduler) == config, "scheduler safety/configuration changed")
            _require([_binding(job, checks) for job in native_jobs] == bindings, "native source or report changed during retry")
            pending = [identity for identity in by_id if identity not in states
                or states[identity]["retryable_lease_timeout"] or states[identity]["deferred_before_admission"]]
            eligible = [identity for identity in pending if attempts.get(identity, 0) < max_attempts_per_job]
            if not pending:
                manifest["stopped_reason"] = "all_jobs_settled"
                break
            if not eligible:
                manifest["stopped_reason"] = "attempt_budget_exhausted"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                manifest["stopped_reason"] = "admission_budget_exhausted"
                break
            if manifest["rounds"] and retry_backoff_seconds:
                if retry_backoff_seconds >= remaining:
                    manifest["stopped_reason"] = "backoff_exceeds_remaining_budget"
                    break
                time.sleep(retry_backoff_seconds)
            index = len(manifest["rounds"])
            folder = root / f"round-{index:04d}"
            folder.mkdir()
            events_path = folder / "lease-events.jsonl"
            events_path.touch()
            manifest["inflight"] = {"round": index, "job_ids": eligible}
            _save_manifest(root, manifest)
            observer = _ObservedScheduler(scheduler, events_path, eligible, deadline)
            outcome = None
            try:
                outcome = checks.run_parallel_projection_checks([by_id[identity] for identity in eligible],
                    scheduler=observer, output_directory=folder / "batch", **options)
                rows = outcome["jobs"]
                _require([row["job_id"] for row in rows] == eligible, "native owner omitted or reordered jobs")
            except Exception as error:
                rows = [{"job_id": identity, "receipt": {"job_id": identity, "status": "failed",
                    "error_type": type(error).__name__, "reason": str(error)[:2000],
                    "scope": "owner_call_failed_no_retry", **FALSE}} for identity in eligible]
            selected = []
            for row in rows:
                identity, receipt = row["job_id"], row["receipt"]
                retry = outcome is not None and _retryable(identity, receipt, observer.events, folder / "batch")
                deferred = outcome is not None and _deferred(identity, receipt, observer.events, folder / "batch")
                state = {"job_id": identity, "receipt": receipt, "retryable_lease_timeout": retry,
                    "deferred_before_admission": deferred,
                    "attempt": attempts.get(identity, 0) + 1, "round": index, **FALSE}
                selected.append(state)
                states[identity], attempts[identity] = state, state["attempt"]
                if "native_execution" in row and "observation" in row:
                    live[identity] = row
            observer._check()
            artifacts = []
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    _require(not path.is_symlink(), "native evidence symlinks cannot be resumed")
                    artifacts.append({"path": path.relative_to(root).as_posix(), "sha256": _file_sha(path)})
            result = {"schema": SCHEMA, "round": index, "jobs": selected, "lease_events": observer.events,
                "artifacts": artifacts, "scheduler_after": _telemetry(scheduler), **FALSE}
            _write(folder / "result.json", result)
            manifest["rounds"].append({"path": (folder / "result.json").relative_to(root).as_posix(),
                "sha256": _file_sha(folder / "result.json")})
            manifest["inflight"] = None
            manifest["consumed_admission_seconds"] = consumed_before + time.monotonic() - invocation_start
            _save_manifest(root, manifest)
        complete = len(states) == len(by_id) and all(row["receipt"].get("status") == "completed" for row in states.values())
        manifest.update(status="completed" if complete else "incomplete",
            consumed_admission_seconds=consumed_before + time.monotonic() - invocation_start,
            archived_receipts_are_live_authority=False,
            budget_scope="cumulative_new_admission_and_backoff_window_not_a_hard_deadline_for_admitted_native_steps",
            live_validation_complete=complete and len(live) == len(by_id))
        _save_manifest(root, manifest)
        return {"live_jobs": [live[identity] for identity in by_id if identity in live],
            "archived_jobs": [states[identity] for identity in by_id if identity in states and identity not in live],
            "receipt": manifest}
    finally:
        os.close(lock_fd)


__all__ = ["NativeValidationOwner", "run_resumable_native_validation", "SCHEMA"]
