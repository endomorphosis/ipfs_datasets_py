#!/usr/bin/env python3
"""Bounded waves of existing, preconfigured distributed autoencoder workers.

The fleet plans capacity, preserves worker state and owns child lifecycles. The
existing worker remains responsible for reservations, source pins, qualifications
and publication. Synchronization is explicit; it is not inference or admission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUNNER = ROOT / "scripts/ops/legal_ir/run_distributed_autoencoders.py"
DEFAULT_LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"
SCHEMA = "autoencoder-fleet/v1"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class FleetError(ValueError):
    pass


def _path(value):
    path = Path(os.path.abspath(os.fspath(value)))
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise FleetError("fleet paths cannot contain symlinks")
    return path


def _read(path, maximum=MAX_JSON_BYTES):
    path = _path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise FleetError("expected bounded regular JSON file")
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise FleetError("JSON byte limit exceeded")
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise FleetError("duplicate JSON field")
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(FleetError("nonfinite JSON")))
    if not isinstance(result, dict):
        raise FleetError("JSON object required")
    return result


def _write(path, value):
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(raw) > MAX_JSON_BYTES:
        raise FleetError("fleet receipt exceeds bound")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".fleet-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def connections(paths, state_directory):
    rows, ids, tokens, campaigns = [], set(), set(), set()
    for path in paths:
        path = _path(path)
        value = _read(path, 64 * 1024)
        worker, campaign = value.get("worker_id"), value.get("campaign_id")
        if not isinstance(worker, str) or not SAFE_ID.fullmatch(worker) or not isinstance(campaign, str) or not SAFE_ID.fullmatch(campaign):
            raise FleetError("connection requires safe existing worker and campaign IDs")
        token = _path(value["token_file"])
        info = token.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or not 0 < info.st_size <= 1024:
            raise FleetError("connection token must be a private bounded regular file")
        if worker in ids or token in tokens:
            raise FleetError("duplicate worker identity or token file")
        ids.add(worker); tokens.add(token); campaigns.add(campaign)
        rows.append({"worker_id": worker, "campaign_id": campaign, "connection_file": str(path),
                     "state_directory": str(_path(state_directory) / "workers" / worker)})
    if not 1 <= len(rows) <= 32 or len(campaigns) != 1:
        raise FleetError("configure one to 32 unique identities from one existing campaign")
    return sorted(rows, key=lambda row: row["worker_id"])


def read_campaign(row):
    """Read the preconfigured owner; do not initialize a journal or claim work."""
    from ipfs_datasets_py.duckdb_control.autoencoder_span_campaign import SpanCampaignTransportClient
    value = _read(row["connection_file"], 64 * 1024)
    if any(value.get(key) != row[key] for key in ("worker_id", "campaign_id")):
        raise FleetError("connection identity changed")
    token_path = _path(value["token_file"])
    info = token_path.stat()
    if info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024:
        raise FleetError("connection token must remain a private bounded regular file")
    try:
        with SpanCampaignTransportClient(value["endpoint"], token_path.read_text().strip()) as client:
            result = client.request("ReadCampaign", {}, uuid.uuid4().hex, timeout=30)
    except Exception as exc:
        raise FleetError("owner read failed (" + type(exc).__name__ + ")") from None
    if result.get("campaign_id") != row["campaign_id"] or row["worker_id"] not in result.get("known_workers", []):
        raise FleetError("worker is not preconfigured in this campaign")
    return result


def storage_capacity(ledger_path, state_directory):
    """Observe existing shared roots and retained claims without modifying them."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    raw = _read(ledger_path)
    roots = [row["path"] for row in raw["roots"]]
    state = _path(state_directory)
    if not any(state == _path(root) or _path(root) in state.parents for root in roots):
        raise FleetError("fleet state must be under an existing shared resource root")
    observer = resources.DaemonResourceReservation(ledger_path, roots=roots, storage_bytes=1, memory_mb=1)
    ledger = observer._read()
    observed = resources._inventory(observer.roots)["apparent_bytes"]
    outstanding = sum(row["storage_bytes"] for row in ledger["reservations"].values() if row["status"] != "released")
    free = min(shutil.disk_usage(root).free for root in observer.roots)
    return {"headroom_bytes": max(0, min(ledger["limit_bytes"] - observed - outstanding, free - outstanding)),
            "observed_apparent_bytes": observed, "outstanding_reservations_bytes": outstanding,
            "minimum_filesystem_free_bytes": free, "limit_bytes": ledger["limit_bytes"],
            "ledger_modified": False, "reservation_acquired": False}


def plan_wave(args, rows, *, campaign_reader=read_campaign, storage_reader=storage_capacity,
              capacity=None, scheduler_reader=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_capacity as sizing
    capacity = capacity or sizing.capacity_plan
    campaigns = [campaign_reader(row) for row in rows]
    binding = campaigns[0]["binding_sha256"]
    if any(value.get("binding_sha256") != binding for value in campaigns):
        raise FleetError("worker connections do not share one campaign binding")
    policy = campaigns[0]["policy"]
    inner_storage = policy.get("worker_storage_bytes", 750_000_000)
    inner_memory = policy.get("memory_mb", 8192)
    if type(inner_storage) is not int or not 1 <= inner_storage <= 50_000_000_000 or type(inner_memory) is not int or inner_memory < 8192:
        raise FleetError("unsupported owner worker resource policy")
    if args.training_storage_bytes < inner_storage and not args.sync_only:
        raise FleetError("configured training storage understates the owner policy")
    storage = storage_reader(args.resource_ledger, args.state_directory)
    scheduler = scheduler_reader() if scheduler_reader is not None else sizing.scheduler_snapshot()
    available = sizing.scheduler_capacity(scheduler)
    memory = 1024 if args.sync_only else 1024 + inner_memory
    cpu = 1 if args.sync_only else 1 + sizing.execution_envelope("training", 1)["cpu_slots"]
    # The outer control process and inner coordinator reserve independently.
    # The inner envelope includes its model pool and serial Lake/Lean work.
    processes = 1 if args.sync_only else 1 + sizing.execution_envelope("training", 1)["child_process_slots"]
    per_storage = args.worker_storage_bytes + (0 if args.sync_only else args.training_storage_bytes)
    limit = min(len(rows), args.max_workers or 32)
    planned = capacity(max_workers=limit, memory_budget_mb=args.memory_budget_mb,
        pending_count=limit if args.sync_only or args.pending_jobs is None else args.pending_jobs, cpu_budget=args.cpu_budget,
        per_worker_memory_mb=memory, per_worker_cpu=cpu, reserve_mb=0,
        storage_headroom_bytes=storage["headroom_bytes"], per_worker_storage_bytes=per_storage,
        scheduler_available_cpu=available["cpu_slots"], scheduler_available_memory_mb=available["memory_mb"],
        scheduler_available_process_slots=available["child_process_slots"], per_worker_process_slots=processes)
    return {"schema": SCHEMA, "intent": "synchronize_weights" if args.sync_only else "train_one_span_per_worker",
            "campaign_id": rows[0]["campaign_id"], "campaign_binding_sha256": binding,
            "configured_worker_ids": [row["worker_id"] for row in rows], "capacity": planned,
            "per_worker": {"memory_mb": memory, "cpu_slots": cpu, "child_process_slots": processes,
                           "storage_bytes": per_storage},
            "storage": storage, "scheduler_available": available, "owner_generation": campaigns[0]["weights"]["generation"],
            "admitted": False, "formalized": False, "reservation_acquired": False}


@contextmanager
def exclusive(path):
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FleetError("lock must be an unaliased regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield descriptor
    finally:
        os.close(descriptor)


def worker_command(args, row):
    command = [sys.executable, str(RUNNER), "worker", "--connection-file", row["connection_file"],
               "--state-directory", row["state_directory"], "--resource-ledger", str(args.resource_ledger),
               "--storage-bytes", str(args.worker_storage_bytes), "--polls", "1", "--max-jobs", "1",
               "--lease-seconds", str(args.lease_seconds)]
    if args.sync_only:
        command.append("--sync-only")
    return command


def process_snapshot():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import _process
    entries = list(Path("/proc").iterdir())
    if len(entries) > 100_000:
        raise FleetError("process inventory exceeds bound")
    return {int(path.name): value for path in entries if path.name.isdecimal()
            if (value := _process(int(path.name))) is not None}


def collect_owned(known, snapshot):
    live = {pid for pid, birth in known.items() if pid in snapshot and snapshot[pid]["birth"] == birth}
    while True:
        extra = {pid for pid, row in snapshot.items() if row["parent_pid"] in live}
        if extra <= live:
            break
        live.update(extra)
    known.update({pid: snapshot[pid]["birth"] for pid in live})
    return {pid: snapshot[pid] for pid in live if snapshot[pid]["state"] != "Z"}


def stop_owned(process, known, *, grace_seconds=5):
    """Signal verified PID births only; descendants may own separate sessions."""
    for sig, deadline in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, 5)):
        live = collect_owned(known, process_snapshot())
        for pid in sorted(live, reverse=True):
            current = process_snapshot().get(pid)
            if current is not None and current["birth"] == known[pid]:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            process.poll()
            for pid in known:
                if pid != process.pid:
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
            if not collect_owned(known, process_snapshot()):
                break
            time.sleep(0.05)
    process.wait(timeout=5)
    if collect_owned(known, process_snapshot()):
        raise FleetError("owned descendants remain live after bounded shutdown")


def run_wave(args, selected, directory, stop, *, popen=subprocess.Popen):
    # Detached grandchildren reparent here when an owned coordinator exits.
    # This dedicated launcher reaps only descendants whose PID birth it recorded.
    import ctypes
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise FleetError("Linux child-subreaper setup failed")
    directory.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": SCHEMA, "workers": [], "started_at": time.time(), "admitted": False}
    active = []
    try:
        for row in selected:
            if stop[0]:
                break
            key = hashlib.sha256((row["campaign_id"] + ":" + row["worker_id"]).encode()).hexdigest()
            guard = exclusive(args.resource_ledger.parent / "fleet-identity-locks" / (key + ".lock"))
            try:
                descriptor = guard.__enter__()
            except BlockingIOError:
                receipt["workers"].append({"worker_id": row["worker_id"], "status": "identity_busy"})
                continue
            log_path = directory / (row["worker_id"] + ".log")
            handle = None
            status_path = Path(row["state_directory"]) / "worker-status.json"
            before_status = status_path.stat() if status_path.exists() else None
            try:
                handle = open(log_path, "xb", opener=lambda path, flags: os.open(path, flags, 0o600))
                process = popen(worker_command(args, row), stdin=subprocess.DEVNULL, stdout=handle,
                    stderr=subprocess.STDOUT, shell=False, start_new_session=True, pass_fds=(descriptor,))
            except BaseException:
                if handle is not None:
                    handle.close()
                guard.__exit__(None, None, None)
                raise
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import _process
            identity = _process(process.pid)
            if identity is None:
                process.wait(timeout=5)
                known = {}
            else:
                known = {process.pid: identity["birth"]}
            entry = {"worker_id": row["worker_id"], "pid": process.pid, "status": "running",
                     "log_path": str(log_path), "owned_processes": known,
                     "status_inode_before": None if before_status is None else [before_status.st_ino, before_status.st_mtime_ns]}
            receipt["workers"].append(entry)
            active.append((process, known, handle, guard, entry, row))
            _write(directory / "wave.json", receipt)
        started = time.monotonic()
        while active:
            snapshot = process_snapshot()
            for process, known, handle, guard, entry, row in list(active):
                collect_owned(known, snapshot)
                reason = "interrupted" if stop[0] else "timeout" if time.monotonic() - started >= args.wave_timeout else "log_limit" if Path(entry["log_path"]).stat().st_size > MAX_LOG_BYTES else None
                result = process.poll()
                if reason is not None or result is not None:
                    if reason is not None or collect_owned(known, process_snapshot()):
                        stop_owned(process, known)
                    result = process.wait(timeout=5)
                    entry.update(status=reason or ("completed" if result == 0 else "failed"), returncode=result)
                    status_path = Path(row["state_directory"]) / "worker-status.json"
                    if status_path.is_file():
                        after_status = status_path.stat()
                        fresh = [after_status.st_ino, after_status.st_mtime_ns] != entry["status_inode_before"]
                        entry["worker_status_observed_this_invocation"] = fresh
                        entry["worker_status" if fresh else "previous_worker_status"] = _read(status_path, 64 * 1024)
                    handle.close(); guard.__exit__(None, None, None)
                    active.remove((process, known, handle, guard, entry, row))
            _write(directory / "wave.json", receipt)
            if active:
                time.sleep(0.1)
    finally:
        cleanup_errors = []
        for process, known, handle, guard, entry, row in active:
            try:
                stop_owned(process, known)
                entry.update(status="launcher_cleanup", returncode=process.returncode)
            except BaseException as exc:
                cleanup_errors.append(type(exc).__name__)
                entry.update(status="cleanup_failed", error_type=type(exc).__name__)
            finally:
                handle.close(); guard.__exit__(None, None, None)
        receipt["finished_at"] = time.time()
        _write(directory / "wave.json", receipt)
        if cleanup_errors:
            raise FleetError("bounded cleanup failed for owned workers: " + ",".join(cleanup_errors))
    return receipt


def run(args, *, planner=plan_wave, wave_runner=run_wave):
    rows = connections(args.connection_file, args.state_directory)
    if args.plan:
        return {"plan_only": True, **planner(args, rows)}
    args.state_directory.mkdir(parents=True, exist_ok=True)
    stop = [False]
    def halt(*unused): stop[0] = True
    previous = {sig: signal.signal(sig, halt) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with exclusive(args.state_directory / "fleet.lock"):
            state_path = args.state_directory / "fleet.json"
            state = _read(state_path) if state_path.exists() else {"schema": SCHEMA, "next_wave": 0, "next_worker": 0}
            if (state.get("schema") != SCHEMA or type(state.get("next_wave")) is not int
                    or type(state.get("next_worker")) is not int
                    or state["next_wave"] < 0 or state["next_worker"] < 0):
                raise FleetError("invalid persisted fleet state")
            if state.get("active_wave_directory"):
                prior = _path(state["active_wave_directory"]) / "wave.json"
                if args.state_directory not in prior.parents:
                    raise FleetError("prior wave is outside this fleet")
                if prior.exists():
                    snapshot = process_snapshot()
                    for worker in _read(prior).get("workers", []):
                        known = {int(pid): birth for pid, birth in worker.get("owned_processes", {}).items()}
                        if collect_owned(known, snapshot):
                            raise FleetError("a prior owned wave is still alive; resume after it exits")
                state.pop("active_wave_directory", None)
            reports, ordinal, failed = [], 0, 0
            while not stop[0] and (args.cycles == 0 or ordinal < args.cycles):
                current_rows = connections(args.connection_file, args.state_directory)
                if current_rows != rows:
                    raise FleetError("fleet connection topology changed")
                plan = planner(args, rows)
                if stop[0]:
                    break
                topology = {"workers": rows, "resource_ledger": str(args.resource_ledger),
                            "campaign_binding_sha256": plan["campaign_binding_sha256"]}
                if "topology" in state and state["topology"] != topology:
                    raise FleetError("persisted fleet topology or campaign binding changed")
                state["topology"] = topology
                count = plan["capacity"]["workers"]
                start = state["next_worker"] % len(rows)
                selected = [rows[(start + offset) % len(rows)] for offset in range(count)]
                wave_number = state["next_wave"]
                directory = args.state_directory / "waves" / (str(wave_number).zfill(8) + "-" + uuid.uuid4().hex)
                directory.parent.mkdir(exist_ok=True)
                state.update(next_wave=wave_number + 1, next_worker=(start + count) % len(rows),
                             active_wave_directory=str(directory))
                _write(state_path, state)
                wave = wave_runner(args, selected, directory, stop) if selected else {"workers": [], "reason": "no_capacity"}
                report = {"wave": wave_number, "plan": plan, "result": wave, "admitted": False}
                _write(args.state_directory / "last-wave.json", report)
                state.pop("active_wave_directory", None)
                _write(state_path, state)
                reports.append({"wave": wave_number, "workers": len(selected),
                                "statuses": [row["status"] for row in wave["workers"]]})
                reports = reports[-32:]
                ordinal += 1
                failed += sum(row["status"] not in {"completed", "identity_busy"} for row in wave["workers"])
                if failed:
                    break
                until = time.monotonic() + args.wave_interval
                while not stop[0] and (args.cycles == 0 or ordinal < args.cycles) and time.monotonic() < until:
                    time.sleep(min(0.1, max(0, until - time.monotonic())))
            return {"schema": SCHEMA, "waves_this_invocation": ordinal, "recent_waves": reports,
                    "interrupted": stop[0], "failed_workers": failed, "admitted": False, "formalized": False}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-directory", type=Path, required=True)
    p.add_argument("--connection-file", type=Path, action="append", required=True)
    p.add_argument("--resource-ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--cycles", type=int, default=1, help="0 explicitly runs continuous bounded waves")
    p.add_argument("--max-workers", type=int, default=0, help="0 sizes automatically, at most the 32 configured identities")
    p.add_argument("--pending-jobs", type=int, help="optional work-count ceiling for each training wave")
    p.add_argument("--memory-budget-mb", type=int, default=2_147_483_647, help="optional total fleet ceiling; hardware and scheduler capacity still apply")
    p.add_argument("--cpu-budget", type=int)
    p.add_argument("--worker-storage-bytes", type=int, default=750_000_000)
    p.add_argument("--training-storage-bytes", type=int, default=750_000_000)
    p.add_argument("--wave-timeout", type=float, default=1200)
    p.add_argument("--wave-interval", type=float, default=30)
    p.add_argument("--lease-seconds", type=float, default=300)
    p.add_argument("--sync-only", action="store_true")
    p.add_argument("--plan", action="store_true", help="read-only capacity and owner-policy observation; no downloads or launch")
    return p


def main(argv=None):
    p = parser(); args = p.parse_args(argv)
    if args.cycles < 0 or args.cycles > 10000 or not 0 <= args.max_workers <= 32 or args.pending_jobs is not None and args.pending_jobs < 0:
        p.error("invalid bounded cycle, worker or pending-job count")
    if args.memory_budget_mb < 0 or args.cpu_budget is not None and args.cpu_budget < 0:
        p.error("resource budgets must be nonnegative")
    if not all(1 <= value <= 50_000_000_000 for value in (args.worker_storage_bytes, args.training_storage_bytes)):
        p.error("each storage allowance must be in (0,50GB]")
    if not math.isfinite(args.wave_timeout) or not 1 <= args.wave_timeout <= 86400 or not math.isfinite(args.wave_interval) or not 0 <= args.wave_interval <= 3600 or not math.isfinite(args.lease_seconds) or not 120 <= args.lease_seconds <= 86400:
        p.error("invalid finite timeout, interval or lease bound")
    args.state_directory, args.resource_ledger = _path(args.state_directory), _path(args.resource_ledger)
    try:
        result = run(args)
    except (FleetError, BlockingIOError) as exc:
        p.error(str(exc) if isinstance(exc, FleetError) else "fleet or worker identity is already active")
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 130 if result.get("interrupted") else 1 if result.get("failed_workers") else 0


if __name__ == "__main__":
    raise SystemExit(main())
