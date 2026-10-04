"""Internal staged HOL build and read-only publication verification.

The installation controller supplies a verified, privately owned archive tree.
One admitted outer BoundedToolRunner owns the worker and all native descendants.
The worker never publishes a runtime or grants proof authority. Disk limits are
sampled, not filesystem quotas; filesystem I/O can delay a sample.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from . import isabelle as legacy, isabelle_profile as profile
from . import isabelle_install_worker as archive_worker
from ..process import BoundedToolRunner, ToolRunLimits, ToolRunRequest
from ....optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLease

SCHEMA = "isabelle-staged-hol-build@1"
VERIFY_SCHEMA = "isabelle-published-hol-verification@1"
REQUEST_SCHEMA = "isabelle-hol-worker-request@1"
RESULT_SCHEMA = "isabelle-hol-worker-result@1"
CPU_SLOTS = 4
PROCESS_SLOTS = 12
MAX_HEAP_BYTES = 4 * 1024**3
MAX_WORKSPACE_BYTES = 64 * 1024**2
MAX_NODES = 8192
MAX_DEPTH = 16
MIN_FREE_BYTES = 1024**3
MAX_RECEIPT_BYTES = archive_worker.MAX_MESSAGE_BYTES
POLL_SECONDS = .1
BUILD_ARGS = ("build", "-b", "-j", "1", "-o", "system_heaps=true", "-o", "threads=2",
              "-o", "parallel_proofs=0", "-o", "quick_and_dirty=false", "HOL")
_FILES = ("Pure", "HOL", "log/Pure.db", "log/Pure.gz", "log/HOL.db", "log/HOL.gz")
_REMOVE = ("HOL", "log/HOL.db", "log/HOL", "log/HOL.gz")
_PLATFORMS = {"linux-aarch64": "polyml-5.9.2_arm64_32-linux",
              "linux-x86_64": "polyml-5.9.2_x86_64_32-linux"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _settings(memory_mb):
    java_mb = min(2048, max(256, memory_mb // 3))
    ml_mb = memory_mb - java_mb - 1024
    return ('ISABELLE_JAVA_SYSTEM_OPTIONS="-server -Dfile.encoding=UTF-8 '
            '-Disabelle.threads=1 -XX:+UseSerialGC -XX:ActiveProcessorCount=1"\n'
            f'ISABELLE_TOOL_JAVA_OPTIONS="-Djava.awt.headless=true -Xms64m -Xmx{java_mb}m -Xss2m"\n'
            f'ML_OPTIONS="--minheap 256 --maxheap {ml_mb} --gcthreads 1 --stackspace 256"\n'
            'ISABELLE_TMP_PREFIX="$TMPDIR/isabelle"\n')


def _java_options(memory_mb):
    java_mb = min(2048, max(256, memory_mb // 3))
    return profile.BOOTSTRAP_JAVA_OPTIONS.replace("-Xmx256m", f"-Xmx{java_mb}m")


def _root(path, *, staging):
    root = archive_worker._absolute_path(str(path), "install_root")
    if not stat.S_ISDIR(root.lstat().st_mode) or root.name != legacy.ISABELLE_VERSION:
        raise ValueError("HOL runtime must be the exact version directory")
    if staging:
        owner = root.parent.parent
        info = owner.lstat()
        if (root.parent.name != "extracted" or not owner.name.startswith(".bounded-isabelle-")
                or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid()):
            raise ValueError("HOL build requires controller-owned private staging")
    return root


def _scan(root, cap, checkpoint, *, max_nodes=MAX_NODES, max_depth=MAX_DEPTH):
    """Bounded descriptor-relative scan: never follow links or special files."""
    checkpoint()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    total = nodes = 0
    started = time.monotonic()

    def walk(descriptor, depth):
        nonlocal total, nodes
        if depth > max_depth:
            raise ValueError("disk_guard_depth_limit")
        with os.scandir(descriptor) as entries:
            for entry in entries:
                checkpoint()
                if time.monotonic() - started > .20:
                    raise ValueError("disk_guard_scan_deadline")
                nodes += 1
                if nodes > max_nodes or len(entry.name.encode()) > 4096:
                    raise ValueError("disk_guard_node_limit")
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue  # A disappeared temporary file consumes no space.
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if total > cap:
                        raise ValueError("disk_guard_byte_limit")
                elif stat.S_ISDIR(info.st_mode):
                    try:
                        child = os.open(entry.name, flags, dir_fd=descriptor)
                    except FileNotFoundError:
                        continue
                    try:
                        found = os.fstat(child)
                        if (found.st_dev, found.st_ino) != (info.st_dev, info.st_ino):
                            raise ValueError("disk_guard_directory_changed")
                        walk(child, depth + 1)
                    finally:
                        os.close(child)
                else:
                    raise ValueError("disk_guard_nonregular_entry")
    descriptor = os.open(root, flags)
    try:
        walk(descriptor, 0)
    finally:
        os.close(descriptor)
    if shutil.disk_usage(root).free < MIN_FREE_BYTES:
        raise ValueError("disk_guard_free_space_floor")
    checkpoint()
    return {"bytes": total, "nodes": nodes}


def _digest_file(path, checkpoint, *, heap=False):
    checkpoint()
    cap = MAX_HEAP_BYTES if heap else 256 * 1024**2
    with legacy._open_regular(path, cap) as stream:
        before = os.fstat(stream.fileno())
        sha256, sha1, tail, total = hashlib.sha256(), hashlib.sha1(), b"", 0
        while True:
            checkpoint()
            block = stream.read(min(64 * 1024, cap - total + 1))
            total += len(block)
            if total > cap:
                raise ValueError("heap artifact exceeds cumulative cap")
            if not block:
                break
            sha256.update(block)
            if heap:
                combined = tail + block
                if len(combined) > 45:
                    sha1.update(combined[:-45])
                tail = combined[-45:]
        after = os.fstat(stream.fileno())
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or total != after.st_size):
        raise ValueError("heap artifact changed while reading")
    result = {"size_bytes": total, "sha256": sha256.hexdigest()}
    if heap:
        if tail != b"SHA1:" + sha1.hexdigest().encode():
            raise ValueError("invalid Isabelle heap SHA1 trailer")
        result["heap_sha1"] = sha1.hexdigest()
    checkpoint()
    return result


def _session_metadata(path, checkpoint):
    checkpoint()
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA cache_size=-2048")
        db.set_progress_handler(lambda: (checkpoint(), 0)[1], 1000)
        names = ("sources", "input_heaps", "output_heap", "uuid")
        sizes = db.execute("SELECT " + ",".join("length(CAST(" + key + " AS BLOB))" for key in names)
                           + " FROM isabelle_session_info WHERE session_name='HOL' LIMIT 2").fetchall()
        if (len(sizes) != 1 or any(type(n) is not int or not 1 <= n <= bound
                for n, bound in zip(sizes[0], (256 * 1024, 1024, 1024, 64)))):
            raise ValueError("invalid bounded HOL build metadata")
        sources, input_heaps, output_heap, build_uuid, code = db.execute(
            "SELECT sources,input_heaps,output_heap,uuid,return_code FROM isabelle_session_info "
            "WHERE session_name='HOL' LIMIT 1").fetchone()
    if (any(type(x) is not str for x in (sources, input_heaps, output_heap, build_uuid))
            or type(code) is not int or code != 0 or str(uuid.UUID(build_uuid)) != build_uuid):
        raise ValueError("unsuccessful HOL database record")
    checkpoint()
    return {"uuid": build_uuid, "return_code": code, "sources_sha256": hashlib.sha256(sources.encode()).hexdigest(),
            "input_heaps": input_heaps, "output_heap": output_heap}


def _heap_manifest(root, checkpoint):
    heaps = root / "heaps"
    inventory = _scan(heaps, MAX_HEAP_BYTES, checkpoint)
    identifier = _PLATFORMS.get(legacy.detect_platform_key())
    if identifier is None:
        raise ValueError("unsupported HOL heap platform")
    with os.scandir(heaps) as entries:
        names = [entry.name for entry in entries]
    if names != [identifier]:
        raise ValueError("unexpected Isabelle heap layout")
    directory = heaps / identifier
    files = {}
    for name in _FILES:
        path = directory / name
        if os.path.lexists(path):
            files[name] = _digest_file(path, checkpoint, heap=name in ("Pure", "HOL"))
    if not {"Pure", "HOL", "log/Pure.db", "log/HOL.db"} <= files.keys():
        raise ValueError("HOL build requires complete Pure and HOL heap/database artifacts")
    metadata = _session_metadata(directory / "log/HOL.db", checkpoint)
    if (metadata["input_heaps"] != files["Pure"]["heap_sha1"] + " Pure\n"
            or metadata["output_heap"] != files["HOL"]["heap_sha1"] + " HOL\n"):
        raise ValueError("HOL database heap digest binding mismatch")
    return {"ml_identifier": identifier, "files": files, "session": metadata,
            "inventory": inventory}


def _parse_request(request):
    fields = {"schema", "mode", "install_root", "timeout_seconds", "memory_mb", "guard_path", "expected_heap_after"}
    if type(request) is not dict or set(request) != fields or request["schema"] != REQUEST_SCHEMA:
        raise ValueError("invalid HOL worker request")
    if request["mode"] not in ("build", "verify"):
        raise ValueError("invalid HOL worker mode")
    if type(request["memory_mb"]) is not int or not 2048 <= request["memory_mb"] <= 8192:
        raise ValueError("invalid HOL build memory")
    value = request["timeout_seconds"]
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
        raise ValueError("invalid HOL worker timeout")
    if len(_canonical(request)) > archive_worker.MAX_MESSAGE_BYTES:
        raise ValueError("HOL worker request exceeds cap")
    building = request["mode"] == "build"
    root = _root(request["install_root"], staging=building)
    if building:
        guard = archive_worker._absolute_path(request["guard_path"], "guard_path")
        if guard.parent != root.parent.parent or not guard.name.startswith(".hol-guard-") or os.path.lexists(guard):
            raise ValueError("invalid HOL guard marker")
        if request["expected_heap_after"] is not None:
            raise ValueError("build request cannot supply expected output")
    elif request["guard_path"] is not None or type(request["expected_heap_after"]) is not dict:
        raise ValueError("invalid read-only verification request")
    return root


def _worker(request):
    root = _parse_request(request)
    deadline = time.monotonic() + request["timeout_seconds"]
    checkpoint = lambda: legacy._check_running(deadline, None)
    workspace = Path.cwd().resolve()
    if (os.environ.get("HOME") != str(workspace) or os.environ.get("TMPDIR") != str(workspace)
            or os.environ.get("USER_HOME") not in (None, str(workspace))):
        raise ValueError("HOL worker requires an isolated HOME and TMPDIR")
    launcher, runtime = profile.resolve_runtime(install_root=root, checkpoint=checkpoint)
    before = _heap_manifest(root, checkpoint)
    result = {"schema": RESULT_SCHEMA, "mode": request["mode"], "request_sha256": _sha(request),
              "build_succeeded": False, "verified": False, "command": [], "native_returncode": None,
              "heap_before": before, "heap_after": {}, "runtime_selected_sha256": runtime["selected_file_sha256"]}
    if request["mode"] == "verify":
        if _canonical(before) != _canonical(request["expected_heap_after"]):
            raise ValueError("published HOL heap manifest differs from staged build")
        result.update(verified=True, heap_after=before)
        return result
    if os.getpgrp() != os.getpid():
        raise ValueError("build worker must be owned by an outer isolated process group")
    settings = _settings(request["memory_mb"]).encode()
    for relative in (".isabelle/etc/settings", f".isabelle/{legacy.ISABELLE_VERSION}/etc/settings"):
        if profile.regular_bytes(workspace / relative, profile.MAX_INPUT_BYTES, checkpoint) != settings:
            raise ValueError("HOL worker private settings mismatch")
    _scan(workspace, MAX_WORKSPACE_BYTES, checkpoint)
    directory = root / "heaps" / before["ml_identifier"]
    for name in _REMOVE:
        checkpoint()
        path = directory / name
        if os.path.lexists(path):
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("refusing nonregular staged HOL removal")
            path.unlink()
    command = (launcher, *BUILD_ARGS)
    result["command"] = list(command)
    marker_fd, marker_temporary = tempfile.mkstemp(prefix=".hol-guard-slot-", dir=Path(request["guard_path"]).parent)
    # Allocate the complete small notification slot before native writes start.
    # The first byte commits a failure; the controller reads only that byte.
    with os.fdopen(os.dup(marker_fd), "wb") as notification:
        notification.write(b"0" + b"\0" * (MAX_RECEIPT_BYTES - 1))
        notification.flush()
    Path(marker_temporary).replace(request["guard_path"])
    # No new session or process group: the existing outer runner owns the full
    # process tree and all cancellation/timeout/RSS teardown.
    native = subprocess.Popen(command, stdin=subprocess.DEVNULL, shell=False)
    try:
        while True:
            checkpoint()
            _scan(root / "heaps", MAX_HEAP_BYTES, checkpoint)
            _scan(workspace, MAX_WORKSPACE_BYTES, checkpoint)
            if native.poll() is not None:
                break
            time.sleep(POLL_SECONDS)
    except BaseException as exc:
        # Preserve the live ancestry until the outer cancellation callback
        # observes this marker and invokes its existing process-tree teardown.
        payload = _canonical({"schema": "isabelle-hol-disk-guard@1", "request_sha256": _sha(request),
            "reason": type(exc).__name__, "message": str(exc)[:1024], "worker_receipt": result})
        try:
            if len(payload) >= MAX_RECEIPT_BYTES:
                raise ValueError("guard notification overflow")
            os.pwrite(marker_fd, payload, 1)
            os.pwrite(marker_fd, b"1", 0)
        except BaseException:
            # Metadata fallback also fails closed in the controller. Even an
            # unresponsive filesystem cannot make us abandon the live ancestry;
            # the outer wall/RSS guard remains the final teardown authority.
            try:
                os.fchmod(marker_fd, 0)
            except OSError:
                pass
        while True:
            time.sleep(.1)
    os.close(marker_fd)
    result["native_returncode"] = native.wait()
    if result["native_returncode"] != 0:
        raise ValueError("native HOL build returned failure")
    after = _heap_manifest(root, checkpoint)
    if after["session"]["uuid"] == before["session"]["uuid"]:
        raise ValueError("HOL build did not produce a fresh database UUID")
    if after["session"]["sources_sha256"] != before["session"]["sources_sha256"]:
        raise ValueError("HOL build unexpectedly changed its source binding")
    for name in ("Pure", "log/Pure.db", "log/Pure.gz"):
        if before["files"].get(name) != after["files"].get(name):
            raise ValueError("HOL build unexpectedly changed its Pure dependency")
    _, latest = profile.resolve_runtime(install_root=root, checkpoint=checkpoint)
    if latest["selected_file_sha256"] != runtime["selected_file_sha256"]:
        raise ValueError("HOL runtime identity changed during build")
    result.update(build_succeeded=True, heap_after=after)
    return result


class _GuardCancellation:
    def __init__(self, signal, marker):
        self.signal, self.marker = signal, marker

    def is_set(self):
        if self.signal.is_set():
            return True
        if self.marker is None or not os.path.lexists(self.marker):
            return False
        try:
            with legacy._open_regular(self.marker, MAX_RECEIPT_BYTES) as stream:
                info = os.fstat(stream.fileno())
                return info.st_size != MAX_RECEIPT_BYTES or stat.S_IMODE(info.st_mode) != 0o600 or stream.read(1) != b"0"
        except Exception:
            return True


def _run(*, install_root, parent_lease, cancellation, remaining, memory_mb, on_progress, expected_build=None):
    building = expected_build is None
    if not isinstance(parent_lease, ResourceLease) or not callable(remaining):
        raise TypeError("HOL helper requires actual parent lease and remaining callback")
    if type(memory_mb) is not int or not 2048 <= memory_mb <= 8192:
        raise ValueError("HOL memory_mb must be an integer in [2048, 8192]")
    if cancellation is not None and not callable(getattr(cancellation, "is_set", None)):
        raise TypeError("cancellation must supply is_set")
    cpu, processes, ram = (CPU_SLOTS, PROCESS_SLOTS, memory_mb) if building else (1, 1, 512)
    if (parent_lease.owner_pid != os.getpid() or parent_lease.released or parent_lease.cancelled
            or parent_lease.cpu_slots < cpu or parent_lease.child_process_slots < processes
            or parent_lease.memory_mb < ram + profile.OVERHEAD_MB or not parent_lease._scheduler.config.proof_safety_enabled):
        raise ValueError("inactive, unsafe, or underfunded HOL parent lease")
    if not sys.platform.startswith("linux"):
        raise ValueError("HOL helper requires Linux process guards")
    root = _root(install_root, staging=building)
    marker = root.parent.parent / (".hol-guard-" + uuid.uuid4().hex + ".json") if building else None
    expected = None
    if not building:
        if (type(expected_build) is not dict or expected_build.get("schema") != SCHEMA
                or expected_build.get("build_succeeded") is not True or type(expected_build.get("heap_after")) is not dict):
            raise ValueError("verified staged HOL build receipt required")
        expected = expected_build["heap_after"]
    receipt = {"schema": SCHEMA if building else VERIFY_SCHEMA, "status": "failed", "build_succeeded": False,
               "verified": False, "observation": {}, "worker_receipt": {}, "child_lease_id": "", "command": [],
               "limits": {}, "heap_before": {}, "heap_after": {}, "persistent_heap_published": False,
               "grants_proof_authority": False, "grants_repository_authority": False, "reason": "", "guard_failure": None}
    if on_progress is not None:
        on_progress("hol_build" if building else "hol_verify", "Checking bounded persistent HOL artifacts")
    with parent_lease.acquire_child(lane="validation", cpu_slots=cpu, memory_mb=ram,
            child_process_slots=processes, timeout=remaining(), cancel_event=cancellation,
            request_id="isabelle:hol-build" if building else "isabelle:hol-verify") as child:
        wall = min(3600, remaining())
        request = {"schema": REQUEST_SCHEMA, "mode": "build" if building else "verify", "install_root": str(root),
                   "timeout_seconds": wall, "memory_mb": memory_mb, "guard_path": str(marker) if marker else None,
                   "expected_heap_after": expected}
        inputs = {"request.json": _canonical(request)}
        if building:
            settings = _settings(memory_mb)
            inputs.update({".isabelle/etc/settings": settings, f".isabelle/{legacy.ISABELLE_VERSION}/etc/settings": settings})
        argv = (sys.executable, "-P", "-m", __name__, "{workspace}/request.json", "{workspace}/result.json")
        limits = ToolRunLimits(timeout_seconds=wall, cpu_seconds=wall, resident_memory_bytes=ram * 1024**2,
            memory_bytes=profile.ADDRESS_SPACE_BYTES if building else 2 * 1024**3,
            max_input_bytes=profile.MAX_INPUT_BYTES, max_output_bytes=MAX_RECEIPT_BYTES,
            max_workspace_bytes=MAX_WORKSPACE_BYTES, max_file_bytes=MAX_HEAP_BYTES)
        receipt["limits"] = {"cpu_slots": cpu, "process_slots": processes, "resident_memory_bytes": limits.resident_memory_bytes,
            "address_space_bytes": limits.memory_bytes, "timeout_seconds": wall, "max_file_bytes": MAX_HEAP_BYTES,
            "max_workspace_bytes": MAX_WORKSPACE_BYTES, "max_heap_bytes": MAX_HEAP_BYTES, "max_nodes": MAX_NODES,
            "max_depth": MAX_DEPTH, "min_free_bytes": MIN_FREE_BYTES, "disk_guard_poll_seconds": POLL_SECONDS,
            "java_max_heap_mb": min(2048, max(256, memory_mb // 3)) if building else None,
            "ml_max_heap_mb": memory_mb - min(2048, max(256, memory_mb // 3)) - 1024 if building else None,
            "disk_scope": "sampled stat-byte caps, not filesystem quotas; I/O can delay samples"}
        receipt["child_lease_id"] = child.lease_id
        runner = BoundedToolRunner(base_environment={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
            "PYTHONPATH": str(Path(__file__).resolve().parents[4]), "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0"})
        observed = runner.run(ToolRunRequest(argv=argv, limits=limits, input_files=inputs, output_paths=("result.json",),
            environment={"JDK_JAVA_OPTIONS": _java_options(memory_mb) if building else profile.BOOTSTRAP_JAVA_OPTIONS}),
            cancellation=_GuardCancellation(child.combined_cancellation_signal(cancellation), marker))
        receipt["observation"] = observed.to_dict()
        if marker is not None and os.path.lexists(marker):
            try:
                raw_marker = profile.regular_bytes(marker, MAX_RECEIPT_BYTES, lambda: None)
                if raw_marker[:1] != b"0":
                    receipt["reason"] = "disk_guard_triggered"
                    receipt["guard_failure"] = json.loads(raw_marker[1:].rstrip(b"\0"))
                    receipt["worker_receipt"] = receipt["guard_failure"].get("worker_receipt", {})
                    receipt["heap_before"] = receipt["worker_receipt"].get("heap_before", {})
                    return receipt
            except Exception as exc:
                receipt["reason"] = "disk_guard_notification_failed"
                receipt["guard_failure"] = {"reason": type(exc).__name__}
                return receipt
        if observed.cancelled or observed.timed_out:
            receipt["reason"] = "cancelled" if observed.cancelled else "deadline_exceeded"
            return receipt
        try:
            remaining()
        except Exception as exc:
            receipt["reason"] = type(exc).__name__
            return receipt
        if (observed.command != argv or not observed.ok or observed.error or observed.output_truncated
                or observed.workspace_limit_exceeded or not observed.workspace_cleaned):
            receipt["reason"] = "bounded_hol_worker_incomplete"
            return receipt
        raw = observed.output_files.get("result.json", b"")
        if not raw or len(raw) > MAX_RECEIPT_BYTES:
            raise ValueError("HOL worker receipt exceeds cap or is missing")
        result = json.loads(raw, object_pairs_hook=archive_worker._pairs)
        keys = {"schema", "mode", "request_sha256", "build_succeeded", "verified", "command", "native_returncode",
                "heap_before", "heap_after", "runtime_selected_sha256"}
        if (type(result) is not dict or set(result) != keys or result["schema"] != RESULT_SCHEMA
                or result["request_sha256"] != _sha(request) or result["mode"] != request["mode"]
                or result["build_succeeded"] is not building or result["verified"] is not (not building)):
            raise ValueError("HOL worker receipt binding mismatch")
        if building:
            if result["command"] != [str(root / "bin/isabelle"), *BUILD_ARGS] or type(result["native_returncode"]) is not int or result["native_returncode"] != 0:
                raise ValueError("HOL native command receipt mismatch")
        elif result["command"] != [] or result["native_returncode"] is not None or _canonical(result["heap_after"]) != _canonical(expected):
            raise ValueError("HOL read-only verification receipt mismatch")
        receipt.update(status="built" if building else "verified", build_succeeded=building, verified=not building,
            worker_receipt=result, heap_before=result["heap_before"], heap_after=result["heap_after"], command=result["command"])
        return receipt


def build_staged_hol(*, install_root, parent_lease, cancellation, remaining, memory_mb=6144, on_progress=None):
    return _run(install_root=install_root, parent_lease=parent_lease, cancellation=cancellation,
                remaining=remaining, memory_mb=memory_mb, on_progress=on_progress)


def verify_published_hol(*, install_root, expected_build, parent_lease, cancellation, remaining):
    return _run(install_root=install_root, parent_lease=parent_lease, cancellation=cancellation,
                remaining=remaining, memory_mb=6144, on_progress=None, expected_build=expected_build)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 2
    try:
        result = _worker(archive_worker._read_request(Path(args[0])))
        archive_worker._write_result(Path(args[1]), result)
    except Exception as exc:
        print(f"HOL worker failed: {type(exc).__name__}: {str(exc)[:1024]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
