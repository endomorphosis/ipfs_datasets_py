"""Qualify a persistent HOL rebuild from a retained official archive.

The production controller rebuilds unpublished staging under the unchanged
shared scheduler, publishes it, and performs fresh fixed smoke checks. A warm
call then checks the persistent result without another build. This benchmark
uses a verified cache hardlink and disables archive downloads; it is not a
network capture or a proof of repository behavior.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import stat
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse

DATASETS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATASETS))

from ipfs_datasets_py.logic.backends.installers import isabelle_installation as installer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources

WARM_RESERVE_SECONDS = 60
SOURCE_MODULES = (
    "ipfs_datasets_py.logic.backends.installers.isabelle_installation",
    "ipfs_datasets_py.logic.backends.installers.isabelle_install_worker",
    "ipfs_datasets_py.logic.backends.installers.isabelle_hol_build",
    "ipfs_datasets_py.logic.backends.installers.isabelle",
    "ipfs_datasets_py.logic.backends.installers.isabelle_profile",
    "ipfs_datasets_py.logic.backends.installers.isabelle_preparation",
    "ipfs_datasets_py.logic.backends.process",
    "ipfs_datasets_py.logic.backends.kernel.isabelle",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety",
)


def _timeout(value):
    number = float(value)
    if not math.isfinite(number) or not WARM_RESERVE_SECONDS < number <= 3600:
        raise argparse.ArgumentTypeError("timeout must be finite in (60, 3600]")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--archive", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--timeout", type=_timeout, default=3600.0,
        help="Overall seconds including admission and hashing; reserve 60 seconds after the cold call")
    return result


def digest(path, checkpoint=lambda: None, max_bytes=16 * 1024**2):
    value, total = hashlib.sha256(), 0
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


def atomic_json(path, value):
    """A reader observes either the previous complete record or the next one."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".json-",
                dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ProgressArtifact:
    """Small independent progress records; no concurrent mutation of results."""
    def __init__(self, path, started):
        self.path, self.started = Path(path), started
        self._lock = threading.Lock()
        self.events = []

    def phase(self, call, phase, message):
        with self._lock:
            if len(self.events) >= 256:
                raise RuntimeError("benchmark phase event bound exceeded")
            self.events.append({"call": call, "phase": phase, "message": str(message)[:4096],
                                "elapsed_seconds": time.monotonic() - self.started})

    def write(self, *, status="running", sample=None):
        with self._lock:
            value = {"schema": "isabelle-hol-build-progress@1", "status": status,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": time.monotonic() - self.started,
                "event_count": len(self.events), "active_phase": self.events[-1].copy() if self.events else None,
                "observation": sample or {},
                "native_output_scope": "Native output is bounded and retained in final receipts; no live output stream."}
            atomic_json(self.path, value)


def seed_archive_cache(archive, target, pin, checkpoint):
    """Verify before linking; fail on cross-filesystem links instead of copying."""
    observed = digest(archive, checkpoint, installer.legacy.MAX_DOWNLOAD_BYTES)
    if observed != pin.sha256:
        raise RuntimeError("retained archive differs from reviewed official pin")
    checkpoint()
    downloads = Path(target) / "downloads"
    downloads.mkdir(mode=0o700, parents=True)
    cache = downloads / Path(urlparse(pin.artifact_url).path).name
    os.link(archive, cache)
    checkpoint()
    if not os.path.samefile(archive, cache):
        raise RuntimeError("cache seed did not retain the exact reviewed archive inode")
    return {"path": str(cache), "method": "hardlink", "observed_sha256": observed,
            "size_bytes": cache.stat().st_size}


def main(argv=None):
    import psutil
    args = parser().parse_args(argv)
    archive, output = args.archive.resolve(strict=True), args.output.absolute()
    info = archive.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= installer.legacy.MAX_DOWNLOAD_BYTES:
        raise ValueError("retained archive must be a regular file within the archive bound")
    if output.exists():
        raise RuntimeError("Choose a new output directory; previous attempts are retained")
    output.mkdir(parents=True)
    target = output / "runtime"
    pin = installer.legacy.select_strict_pin("isabelle", platform_key=installer.legacy.detect_platform_key())
    owner = get_global_resource_scheduler()
    if not owner.config.proof_safety_enabled:
        raise RuntimeError("default shared pressure safety must remain enabled")
    started = time.monotonic()
    deadline = started + args.timeout
    cancellation = threading.Event()
    combined_signal = cancellation
    stop = threading.Event()
    progress = ProgressArtifact(output / "progress.json", started)
    progress.phase("benchmark", "parent_admission", "Waiting for shared CPU4/process12/RAM6400 envelope")
    progress.write()
    result = {"schema": "isabelle-hol-build-qualification@1", "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive": {"path": str(archive), "size_bytes": info.st_size, "expected_sha256": pin.sha256},
        "environment": {"platform": platform.platform(), "python_executable": sys.executable,
            "host": asdict(collect_proof_host_resources()), "scheduler": owner.config.persisted_dict()},
        "scope": {"production_controller_direct": True, "force_persistent_hol_rebuild": True,
            "allow_archive_download": False, "archive_transport": "Retained reviewed cache hardlink; no HTTP server",
            "network_scope": "Archive download disabled by production API; no independent network packet capture",
            "outer_legacy_worker": False, "pressure_policy_replaced": False, "pressure_injected": False,
            "cancellation_control": "No injected cancellation during the expensive build; SIGINT/SIGTERM cancel cooperatively",
            "grants_repository_or_proof_authority": False,
            "source_scope": "Selected implementation hashes, not a complete dependency/toolchain attestation",
            "telemetry_scope": "Shared scheduler includes other clients; process-tree RSS is sampled and may double-count shared pages"},
        "limits": {"overall_timeout_seconds": args.timeout, "cold_call_reserve_seconds": WARM_RESERVE_SECONDS,
            "cpu_slots": 4, "process_slots": 12, "reservation_memory_mb": 6400,
            "native_build_memory_mb": 6144, "progress_interval_seconds": 5},
        "checks": {}, "errors": [], "scheduler_observations": []}
    result_path = output / "result.json"
    atomic_json(result_path, result)
    peak = {"descendant_rss_bytes": 0, "descendant_processes": 0, "descendant_threads": 0,
            "controller_rss_bytes": 0, "controller_threads": 0}
    pressure = {"samples": 0, "backoff_reason_samples": {}, "max_shared_waiting_requests": 0}
    sampled, monitor_errors = set(), []
    latest_sample = {}

    def remaining():
        if combined_signal.is_set():
            raise TimeoutError("benchmark cancellation requested")
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("benchmark overall deadline exceeded")
        return value

    def snapshot(phase):
        observed = owner.snapshot()
        result["scheduler_observations"].append({"phase": phase,
            "elapsed_seconds": time.monotonic() - started, "snapshot": observed})
        return observed

    def monitor():
        nonlocal latest_sample
        controller = psutil.Process()
        next_state = next_progress = 0
        while not stop.is_set():
            try:
                peak["controller_rss_bytes"] = max(peak["controller_rss_bytes"], controller.memory_info().rss)
                peak["controller_threads"] = max(peak["controller_threads"], controller.num_threads())
                rss = threads = processes = 0
                for child in controller.children(recursive=True):
                    try:
                        sampled.add((child.pid, child.create_time()))
                        rss += child.memory_info().rss
                        threads += child.num_threads()
                        processes += 1
                    except psutil.NoSuchProcess:
                        pass
                for key, value in (("descendant_rss_bytes", rss), ("descendant_processes", processes),
                                   ("descendant_threads", threads)):
                    peak[key] = max(peak[key], value)
                now = time.monotonic()
                if now >= next_state:
                    state = owner.snapshot()
                    pressure["samples"] += 1
                    pressure["max_shared_waiting_requests"] = max(pressure["max_shared_waiting_requests"], state["waiting_request_count"])
                    reason = state.get("proof_backoff", {}).get("reason")
                    if reason:
                        counts = pressure["backoff_reason_samples"]
                        counts[reason] = counts.get(reason, 0) + 1
                    latest_sample = {"descendant_rss_bytes": rss, "descendant_processes": processes,
                        "descendant_threads": threads, "peak": peak.copy(), "scheduler": state,
                        "owned_leases": [row for row in owner.active_leases() if row["owner_pid"] == os.getpid()]}
                    next_state = now + 1
                if now >= next_progress:
                    progress.write(sample=latest_sample)
                    next_progress = now + 5
            except Exception as exc:
                monitor_errors.append(f"{type(exc).__name__}: {exc}")
                cancellation.set()
                return
            stop.wait(.1)

    monitoring = threading.Thread(target=monitor, daemon=True)
    prior_handlers = {}
    try:
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGINT, signal.SIGTERM):
                prior_handlers[number] = signal.signal(number, lambda *_: cancellation.set())
        result["source_sha256_before"] = source_hashes()
        monitoring.start()
        before = snapshot("before_parent_admission")
        with owner.acquire("orchestration", cpu_slots=4, memory_mb=6400, child_process_slots=12,
                timeout=remaining(), cancel_event=cancellation,
                request_id="isabelle:persistent-hol-build-benchmark") as parent:
            combined_signal = parent.combined_cancellation_signal(cancellation)
            remaining()
            result["parent_lease_id"] = parent.lease_id
            result["parent_lease"] = {"lease_id": parent.lease_id, "parent_lease_id": parent.parent_lease_id,
                "owner_pid": parent.owner_pid, "cpu_slots": parent.cpu_slots, "memory_mb": parent.memory_mb,
                "child_process_slots": parent.child_process_slots, "scheduler_state_path": str(owner.state_path)}
            result["checks"]["actual_parent_envelope"] = (
                parent.cpu_slots == 4 and parent.memory_mb == 6400 and parent.child_process_slots == 12
                and parent.owner_pid == os.getpid() and parent.parent_lease_id is None)
            result["parent_admission_seconds"] = time.monotonic() - started
            result["parent_wait_seconds"] = parent.wait_seconds
            progress.phase("benchmark", "archive_verification", "Verifying reviewed archive before hardlinking the local cache")
            result["archive"]["cache_seed"] = seed_archive_cache(archive, target, pin, remaining)
            result["checks"]["archive_matches_reviewed_pin"] = True
            for name, build in (("cold", True), ("warm", False)):
                budget = remaining() - (WARM_RESERVE_SECONDS if build else 0)
                if budget <= 0:
                    raise TimeoutError("insufficient time for cold build plus reserved warm verification")
                phase_started = time.monotonic()
                progress.phase(name, "begin", "Cold staged HOL rebuild" if build else "Fresh warm smoke without rebuilding HOL")
                def on_progress(phase, message):
                    progress.phase(name, phase, message)
                try:
                    receipt = installer.ensure_isabelle_installation(yes=True, strict=True,
                        install_root=target, parent_lease=parent, cancellation=cancellation,
                        timeout_seconds=min(3600, budget), on_progress=on_progress,
                        build_hol=build, allow_download=False, build_memory_mb=6144)
                except installer.IsabelleInstallationError as exc:
                    result[name] = exc.receipt.to_dict()
                    raise
                result[name] = receipt.to_dict()
                result[name + "_seconds"] = time.monotonic() - phase_started
                snapshot(name + "_completed")
                atomic_json(result_path, result)
                if not receipt.usable:
                    raise RuntimeError(name + " installation did not become usable")
            cold, warm = result["cold"], result["warm"]
            build = cold["hol_build"]
            result["checks"].update(
                cold_installed=cold["installed"] and not cold["already_present"] and cold["checksum_verified"],
                warm_reused_without_build=warm["already_present"] and not warm["installed"]
                    and not warm["build_hol_requested"] and not warm["hol_build"],
                archive_downloads_disabled=all(not row["download_attempted"] and row["limits"]["allow_download"] is False for row in (cold, warm)),
                fresh_smokes=all(row["preparation"].get("smoke_accepted") is True for row in (cold, warm)),
                staged_smoke_accepted=cold["staged_preparation"].get("smoke_accepted") is True,
                persistent_build_published=build.get("build_succeeded") is True and build.get("persistent_heap_published") is True,
                published_heap_verified=build.get("publication_verification", {}).get("verified") is True,
                hol_build_uuid_changed=(bool(build.get("heap_before", {}).get("session", {}).get("uuid"))
                    and bool(build.get("heap_after", {}).get("session", {}).get("uuid"))
                    and build["heap_before"]["session"]["uuid"] != build["heap_after"]["session"]["uuid"]),
                published_heap_matches_rebuilt=(bool(build.get("heap_after")) and
                    build.get("publication_verification", {}).get("heap_after") == build["heap_after"]),
                pure_artifacts_preserved=all(build.get("heap_before", {}).get("files", {}).get(name)
                    == build.get("heap_after", {}).get("files", {}).get(name)
                    for name in ("Pure", "log/Pure.db", "log/Pure.gz")),
                no_proof_or_repository_authority=all(row["grants_proof_authority"] is False and row["grants_repository_authority"] is False for row in (cold, warm)),
                distinct_call_envelopes=cold["resource_lease_id"] != warm["resource_lease_id"],
                cleanup_complete=not cold["cleanup_pending"] and not warm["cleanup_pending"],
                no_partial_files=not list((target / "downloads").glob("*.partial")),
                no_staging_directories=not list(target.glob(".bounded-isabelle-*")),
                no_owned_children=all(row["lease_id"] == parent.lease_id for row in owner.active_leases() if row["owner_pid"] == os.getpid()))
            progress.phase("benchmark", "final_hashes", "Recording published heaps and unchanged retained archive")
            runtime = Path(warm["preparation"]["native_runtime"]["runtime_root"])
            files = [runtime / "bin/isabelle", runtime / "etc/settings", *runtime.glob("heaps/*/HOL"), *runtime.glob("heaps/*/Pure")]
            result["runtime_sha256"] = {str(file.relative_to(runtime)): digest(file, remaining, 4 * 1024**3) for file in files}
            result["archive"]["sha256_after"] = digest(archive, remaining, installer.legacy.MAX_DOWNLOAD_BYTES)
            result["checks"]["retained_archive_unchanged"] = result["archive"]["sha256_after"] == pin.sha256 and archive.stat().st_size == info.st_size
            result["checks"]["hol_and_pure_heaps_recorded"] = all(any(name.endswith("/" + heap) for name in result["runtime_sha256"]) for heap in ("HOL", "Pure"))
            remaining()
        combined_signal = cancellation
        after = snapshot("after_parent_release")
        result["shared_wait_time_seconds_delta"] = after["wait_time_seconds"]["total"] - before["wait_time_seconds"]["total"]
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
        for number, handler in prior_handlers.items():
            signal.signal(number, handler)
        result["cancellation_requested"] = cancellation.is_set()
        result["monitor_errors"], result["sampled_peak"], result["pressure_backoff_metrics"] = monitor_errors, peak, pressure
        result["phases"] = progress.events.copy()
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
            result["checks"]["owned_leases_drained"] = not any(row["owner_pid"] == os.getpid() for row in owner.active_leases())
            result["scheduler_final"] = owner.snapshot()
        except Exception as exc:
            result["checks"]["owned_leases_drained"] = False
            result["errors"].append(f"final scheduler observation: {exc}")
        result["checks"].update(monitor_drained=not monitoring.is_alive() and not monitor_errors,
            sampled_descendants_drained=not result["sampled_descendants_live"], cancellation_not_requested=not cancellation.is_set())
        result["checks"].setdefault("retained_archive_unchanged", False)
        try:
            result["source_sha256_after"] = source_hashes()
            result["checks"]["selected_sources_unchanged"] = result.get("source_sha256_before") == result["source_sha256_after"]
        except Exception as exc:
            result["checks"]["selected_sources_unchanged"] = False
            result["errors"].append(f"final source recording: {exc}")
        result["checks"]["finished_within_overall_deadline"] = time.monotonic() <= deadline
        if result["errors"] or not all(result["checks"].values()):
            result["status"] = "failed"
        result["elapsed_seconds"] = time.monotonic() - started
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        progress.write(status=result["status"], sample={"peak": peak, "checks": result["checks"], "errors": result["errors"]})
        atomic_json(result_path, result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "errors": result["errors"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
