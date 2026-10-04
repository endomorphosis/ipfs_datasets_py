"""Qualify the production shared-owner Isabelle installer using official bytes.

Serve a retained pinned archive over fresh loopback HTTP, call the production
controller directly for cold and warm installation, and retain its fresh fixed
smoke receipts. This does not download from a remote release server. No outer
legacy-transaction worker or scheduler-policy replacement is used.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import stat
import sys
import threading
import time

DATASETS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATASETS))

from ipfs_datasets_py.logic.backends.installers import isabelle_installation as installer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources

SOURCE_MODULES = (
    "ipfs_datasets_py.logic.backends.installers.isabelle_installation",
    "ipfs_datasets_py.logic.backends.installers.isabelle_install_worker",
    "ipfs_datasets_py.logic.backends.installers.isabelle",
    "ipfs_datasets_py.logic.backends.installers.isabelle_profile",
    "ipfs_datasets_py.logic.backends.installers.isabelle_preparation",
    "ipfs_datasets_py.logic.backends.process",
    "ipfs_datasets_py.logic.backends.kernel.isabelle",
    "ipfs_datasets_py.logic.external_provers.isabelle_runtime",
    "ipfs_datasets_py.logic.external_provers.isabelle_setup",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety",
)


def _timeout(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 3600:
        raise argparse.ArgumentTypeError("timeout must be finite in (0, 3600]")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--archive", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--timeout", type=_timeout, default=900.0,
                        help="Overall seconds including parent admission, hashing, cold and warm calls")
    return result


def digest(path, checkpoint=lambda: None, max_bytes=16 * 1024**2):
    value = hashlib.sha256()
    total = 0
    with installer.legacy._open_regular(Path(path), max_bytes) as stream:
        while True:
            checkpoint()
            block = stream.read(min(1024**2, max_bytes - total + 1))
            checkpoint()
            total += len(block)
            if total > max_bytes:
                raise ValueError("retained artifact exceeds its byte bound")
            if not block:
                return value.hexdigest()
            value.update(block)


def source_hashes():
    paths = [Path(__file__).resolve()]
    for name in SOURCE_MODULES:
        path = Path(importlib.import_module(name).__file__).resolve()
        if not path.is_relative_to(DATASETS):
            raise RuntimeError(f"wrong implementation: {path}")
        paths.append(path)
    return {str(path): digest(path) for path in paths}


def shared_wait_total_delta(before, after):
    """Compare cumulative seconds, not the scheduler's wait-summary objects."""
    return after["wait_time_seconds"]["total"] - before["wait_time_seconds"]["total"]


@contextmanager
def mirrored_pin(pin, url):
    """Change only transport URL; retain the actual reviewed pin selection."""
    original = installer.legacy.select_strict_pin
    mirror = replace(pin, artifact_url=url)
    def selected(tool_id, *, platform_key=None):
        if tool_id != pin.tool_id or platform_key != pin.platform:
            raise ValueError("benchmark attempted a different pin selection")
        return mirror
    installer.legacy.select_strict_pin = selected
    try:
        yield
    finally:
        installer.legacy.select_strict_pin = original


def main(argv=None):
    import psutil
    args = parser().parse_args(argv)
    archive, output = args.archive.resolve(strict=True), args.output.absolute()
    info = archive.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= installer.legacy.MAX_DOWNLOAD_BYTES:
        raise ValueError("retained archive must be a regular file within the download bound")
    if output.exists():
        raise RuntimeError("Choose a new output directory; prior attempts are retained")
    output.mkdir(parents=True)
    target = output / "runtime"
    pin = installer.legacy.select_strict_pin("isabelle", platform_key=installer.legacy.detect_platform_key())
    owner = get_global_resource_scheduler()
    if not owner.config.proof_safety_enabled:
        raise RuntimeError("default shared pressure safety must remain enabled")
    started = time.monotonic()
    deadline = started + args.timeout
    cancellation = threading.Event()
    phases, requests, snapshots, monitor_errors = [], [], [], []
    result = {"schema": "isabelle-shared-installation-qualification@1", "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256_before": source_hashes(),
        "archive": {"path": str(archive), "size_bytes": info.st_size, "expected_sha256": pin.sha256},
        "environment": {"platform": platform.platform(), "python_executable": sys.executable,
            "host": asdict(collect_proof_host_resources()), "scheduler": owner.config.persisted_dict()},
        "scope": {"production_controller_direct": True, "fresh_local_http_download": True,
            "fresh_remote_download": False, "requires_reviewed_official_archive": True,
            "outer_legacy_worker": False, "pressure_policy_replaced": False,
            "pressure_injected": False, "cancellation_control": "pre-cancelled request only",
            "grants_repository_or_proof_authority": False,
            "source_scope": "Selected implementation hashes, not a full dependency/toolchain attestation",
            "telemetry_scope": "Scheduler snapshots include other clients; wait deltas are not solely attributable to this run"},
        "limits": {"overall_timeout_seconds": args.timeout, "cpu_slots": 3,
            "process_slots": 12, "reservation_memory_mb": 2304},
        "checks": {}, "errors": [], "phases": phases, "scheduler_observations": snapshots}
    path = output / "result.json"
    def save():
        temporary = output / ".result.json.new"
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    save()

    def remaining():
        if cancellation.is_set():
            raise TimeoutError("benchmark cancellation requested")
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("benchmark overall deadline exceeded")
        return seconds

    def snapshot(phase):
        observed = owner.snapshot()
        snapshots.append({"phase": phase, "elapsed_seconds": time.monotonic() - started,
                          "snapshot": observed})
        return observed

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(archive.parent), **kw)
        def do_GET(self):
            if self.path != "/" + archive.name:
                self.send_error(404)
                return
            requests.append({"path": self.path, "elapsed_seconds": time.monotonic() - started})
            super().do_GET()
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    stop = threading.Event()
    peak = {"descendant_rss_bytes": 0, "descendant_processes": 0, "descendant_threads": 0,
            "controller_rss_bytes": 0, "controller_threads": 0}
    pressure_metrics = {"samples": 0, "backoff_reason_samples": {}, "max_shared_waiting_requests": 0,
                        "scope": "Sampled shared scheduler state; includes other clients and retained cooldown reasons"}
    sampled = set()
    def monitor():
        controller = psutil.Process()
        next_scheduler_sample = 0
        while not stop.is_set():
            try:
                peak["controller_rss_bytes"] = max(peak["controller_rss_bytes"], controller.memory_info().rss)
                peak["controller_threads"] = max(peak["controller_threads"], controller.num_threads())
                children = controller.children(recursive=True)
            except psutil.Error as exc:
                monitor_errors.append(f"{type(exc).__name__}: {exc}")
                return
            rss = threads = processes = 0
            for child in children:
                try:
                    sampled.add((child.pid, child.create_time()))
                    rss += child.memory_info().rss
                    threads += child.num_threads()
                    processes += 1
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied as exc:
                    monitor_errors.append(str(exc))
            for key, value in (("descendant_rss_bytes", rss), ("descendant_processes", processes),
                               ("descendant_threads", threads)):
                peak[key] = max(peak[key], value)
            if time.monotonic() >= next_scheduler_sample:
                try:
                    state = owner.snapshot()
                    pressure_metrics["samples"] += 1
                    pressure_metrics["max_shared_waiting_requests"] = max(
                        pressure_metrics["max_shared_waiting_requests"], state["waiting_request_count"])
                    reason = state.get("proof_backoff", {}).get("reason")
                    if reason:
                        counts = pressure_metrics["backoff_reason_samples"]
                        counts[reason] = counts.get(reason, 0) + 1
                except Exception as exc:
                    monitor_errors.append(f"scheduler sampling: {type(exc).__name__}: {exc}")
                next_scheduler_sample = time.monotonic() + .25
            stop.wait(.05)
    monitoring = threading.Thread(target=monitor, daemon=True)
    prior_handlers = {}
    def interrupt(_number, _frame):
        cancellation.set()
    try:
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGINT, signal.SIGTERM):
                prior_handlers[number] = signal.signal(number, interrupt)
        monitoring.start()
        before = snapshot("before_parent_admission")
        with owner.acquire("orchestration", cpu_slots=3, memory_mb=2304, child_process_slots=12,
                timeout=remaining(), cancel_event=cancellation,
                request_id="isabelle:production-installation-benchmark") as parent:
            remaining()
            result["parent_lease_id"] = parent.lease_id
            result["parent_admission_seconds"] = time.monotonic() - started
            result["parent_wait_seconds"] = parent.wait_seconds
            hashed = time.monotonic()
            observed = digest(archive, remaining, installer.legacy.MAX_DOWNLOAD_BYTES)
            result["archive"].update(observed_sha256=observed, hash_seconds=time.monotonic() - hashed)
            result["checks"]["archive_matches_reviewed_pin"] = observed == pin.sha256
            if observed != pin.sha256:
                raise RuntimeError("retained archive differs from reviewed official pin")
            serving.start()
            url = f"http://127.0.0.1:{server.server_port}/{archive.name}"
            with mirrored_pin(pin, url):
                for name in ("cold", "warm"):
                    phase_started = time.monotonic()
                    def progress(phase, message):
                        phases.append({"call": name, "phase": phase,
                            "elapsed_seconds": time.monotonic() - started, "message": message})
                    try:
                        receipt = installer.ensure_isabelle_installation(yes=True, strict=True,
                            install_root=target, parent_lease=parent, cancellation=cancellation,
                            timeout_seconds=min(3600, remaining()), on_progress=progress)
                    except installer.IsabelleInstallationError as exc:
                        result[name] = exc.receipt.to_dict()
                        raise
                    result[name] = receipt.to_dict()
                    result[name + "_seconds"] = time.monotonic() - phase_started
                    snapshot(name + "_completed")
                    save()
                    if not receipt.usable:
                        raise RuntimeError(name + " installation did not become usable")
                # This control never starts native work; active-worker and
                # pressure-injection tests remain separate qualification.
                pre_cancelled = threading.Event()
                pre_cancelled.set()
                before_control = len(requests)
                control_started = time.monotonic()
                control = installer.ensure_isabelle_installation(yes=True, strict=False,
                    install_root=target, parent_lease=parent, cancellation=pre_cancelled,
                    timeout_seconds=min(3600, remaining()))
                result["pre_cancelled_control"] = {"elapsed_seconds": time.monotonic() - control_started,
                                                   "receipt": control.to_dict()}
                result["checks"]["pre_cancelled_no_work"] = (
                    control.status == "failed" and "cancelled" in control.reason_codes
                    and not control.resource_lease_id and not control.worker
                    and not control.preparation and len(requests) == before_control)
            cold, warm = result["cold"], result["warm"]
            result["checks"].update(
                cold_installed=cold["installed"] and not cold["already_present"] and cold["checksum_verified"],
                warm_reused=warm["already_present"] and not warm["download_attempted"] and not warm["installed"],
                fresh_smokes=all(row["preparation"].get("smoke_accepted") is True for row in (cold, warm)),
                distinct_call_envelopes=cold["resource_lease_id"] != warm["resource_lease_id"],
                exactly_one_download=len(requests) == 1,
                cleanup_complete=not cold["cleanup_pending"] and not warm["cleanup_pending"],
                no_partial_files=not list((target / "downloads").glob("*.partial")),
                no_staging_directories=not list(target.glob(".bounded-isabelle-*")),
                no_owned_children=all(row["lease_id"] == parent.lease_id for row in owner.active_leases()
                    if row["owner_pid"] == os.getpid()))
            runtime = Path(warm["preparation"]["native_runtime"]["runtime_root"])
            files = [runtime / "bin/isabelle", runtime / "etc/settings",
                     *runtime.glob("heaps/*/HOL"), *runtime.glob("heaps/*/Pure")]
            result["runtime_sha256"] = {str(file.relative_to(runtime)): digest(file, remaining, 4 * 1024**3)
                                        for file in files}
            result["checks"]["hol_and_pure_heaps_recorded"] = (
                any(name.endswith("/HOL") for name in result["runtime_sha256"])
                and any(name.endswith("/Pure") for name in result["runtime_sha256"]))
            remaining()
        after = snapshot("after_parent_release")
        result["shared_wait_time_seconds_delta"] = shared_wait_total_delta(before, after)
        if not all(result["checks"].values()):
            raise RuntimeError("qualification checks failed")
        result["status"] = "completed"
    except Exception as exc:
        result["status"] = "failed"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        stop.set()
        if monitoring.ident is not None:
            monitoring.join(3)
        if serving.ident is not None:
            server.shutdown()
            serving.join(3)
        server.server_close()
        for number, handler in prior_handlers.items():
            signal.signal(number, handler)
        result["cancellation_requested"] = cancellation.is_set()
        result["monitor_errors"] = monitor_errors
        result["sampled_peak"] = peak
        result["pressure_backoff_metrics"] = pressure_metrics
        result["http_requests"] = requests
        result["sampled_descendants_live"] = []
        for pid, birth in sampled:
            try:
                process = psutil.Process(pid)
                if process.create_time() == birth and process.status() != psutil.STATUS_ZOMBIE:
                    result["sampled_descendants_live"].append(pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                result["errors"].append(f"descendant cleanup observation: {exc}")
        try:
            result["checks"]["owned_leases_drained"] = not any(
                row["owner_pid"] == os.getpid() for row in owner.active_leases())
            result["scheduler_final"] = owner.snapshot()
        except Exception as exc:
            result["checks"]["owned_leases_drained"] = False
            result["errors"].append(f"final scheduler observation: {exc}")
        result["checks"].update(monitor_drained=not monitoring.is_alive() and not monitor_errors,
            http_server_drained=not serving.is_alive(),
            sampled_descendants_drained=not result["sampled_descendants_live"],
            cancellation_not_requested=not cancellation.is_set())
        try:
            result["source_sha256_after"] = source_hashes()
            result["checks"]["selected_sources_unchanged"] = result["source_sha256_before"] == result["source_sha256_after"]
        except Exception as exc:
            result["checks"]["selected_sources_unchanged"] = False
            result["errors"].append(f"final source recording: {exc}")
        if result["errors"] or not all(result["checks"].values()):
            result["status"] = "failed"
        result["elapsed_seconds"] = time.monotonic() - started
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({"status": result["status"], "checks": result["checks"], "errors": result["errors"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
