"""Bounded process reuse for native training, without retaining model state.

Only loaded Python code is reused across jobs. Each job still verifies and
loads its own checkpoint, emits a private sparse candidate, and undergoes the
ordinary owner qualification. No executor or trainer injection is accepted.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import gc
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat
import time

MAX_RETAINED_WORKERS = 2
MAX_POOL_JOBS = 8
_PROCESS_MANIFEST = None
_PROCESS_JOBS = 0
_WORKER_RUNTIME = None


def _source_entries(root):
    """Read every source on every call; never trust cached filesystem metadata.

    Directory descriptors avoid resolving every ancestor of every file. They
    also let the open refuse a symlink substituted after enumeration. Preserve
    pathlib's exclusion of directory aliases; matching ``*.py`` aliases still
    fail. The portable path keeps the previous traversal where fd walking is
    unavailable.
    """
    entries = {}
    if hasattr(os, "fwalk") and hasattr(os, "O_NOFOLLOW"):
        def fail(error):
            raise error

        for directory, directories, files, directory_fd in os.fwalk(
                root, follow_symlinks=False, onerror=fail):
            relative = os.path.relpath(directory, root)
            prefix = "" if relative == "." else relative.replace(os.sep, "/") + "/"
            for name in files + directories:
                if not name.endswith(".py"):
                    continue
                observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(observed.st_mode):
                    raise ValueError("native pool producer source aliases another tree")
                if stat.S_ISDIR(observed.st_mode):
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
                with os.fdopen(fd, "rb") as handle:
                    before = os.fstat(handle.fileno())
                    if (not stat.S_ISREG(before.st_mode)
                            or (before.st_dev, before.st_ino) != (observed.st_dev, observed.st_ino)):
                        raise ValueError("native pool producer file changed or is not regular")
                    entries[prefix + name] = hashlib.sha256(handle.read()).hexdigest()
                    after = os.fstat(handle.fileno())
                    if any(getattr(before, key) != getattr(after, key) for key in
                           ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
                        raise ValueError("native pool producer source changed during read")
        return entries
    for path in sorted(root.rglob("*.py")):
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("native pool producer source aliases another tree")
        if path.is_dir():
            continue
        entries[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def _package_manifest():
    """Content binding, including bridges outside the six core worker files."""
    entries = _source_entries(Path(__file__).resolve().parents[2])
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "file_count": len(entries)}


def worker_runtime():
    """Observation for the ordinary immutable worker receipt; never a gate."""
    return dict(_WORKER_RUNTIME) if _WORKER_RUNTIME is not None else None


def _execute_pool_job(spec, manifest):
    global _PROCESS_MANIFEST, _PROCESS_JOBS, _WORKER_RUNTIME
    from .autoencoder_training_worker import execute_training_job
    started = time.perf_counter()
    observed = _package_manifest()
    if observed != manifest or (_PROCESS_MANIFEST is not None and observed != _PROCESS_MANIFEST):
        raise ValueError("native pool producer source changed; start a fresh cycle")
    _PROCESS_MANIFEST = observed
    from . import modal_autoencoder
    # Do not reuse target values across jobs or retain their large object graphs.
    # First-use imports may be warm even when this cache is empty.
    cleared = len(modal_autoencoder._LEGAL_IR_TARGET_CACHE)
    modal_autoencoder._LEGAL_IR_TARGET_CACHE.clear()
    gc.collect()
    _WORKER_RUNTIME = {
        "schema_version": "native-training-pool-observation/v1",
        "pid": os.getpid(), "process_job_index": _PROCESS_JOBS,
        "process_reused": _PROCESS_JOBS > 0,
        "target_cache_cleared_entries": cleared,
        "producer_manifest": observed,
        "pre_job_guard_seconds": time.perf_counter() - started,
        "retained_model_state": False,
        "source_scope": "package Python contents before/after every job; preloaded bytecode not attested",
    }
    try:
        result = execute_training_job(spec)
        if _package_manifest() != manifest:
            raise ValueError("native pool producer changed during job; candidate is unregistered")
        return result
    finally:
        _PROCESS_JOBS += 1
        _WORKER_RUNTIME = None
        modal_autoencoder._LEGAL_IR_TARGET_CACHE.clear()
        gc.collect()


class _NativeTrainingPool:
    """Exact-type cycle-owned pool. Idle workers still consume reserved RAM.

    A pool is recycled between waves after at most eight total jobs; it never
    grows beyond two retained workers. Wider hardware-admitted waves use the
    existing fresh executor. This bounds retained imports/allocator arenas.
    """

    def __init__(self, max_workers, *, expected_manifest=None):
        if type(max_workers) is not int or not 1 <= max_workers <= MAX_RETAINED_WORKERS:
            raise ValueError("native retained pool must contain one or two workers")
        self.max_workers = max_workers
        self.manifest = _package_manifest()
        if expected_manifest is not None and self.manifest != expected_manifest:
            raise ValueError("native pool producer source changed from cycle manifest")
        self.submitted_jobs = 0
        self.closed = False
        self.executor = ProcessPoolExecutor(max_workers=max_workers,
                                            mp_context=multiprocessing.get_context("spawn"))

    def validate_dispatch(self, max_workers, job_count):
        if self.closed or max_workers != self.max_workers:
            raise ValueError("native pool width differs from admitted dispatch")
        if job_count < 1 or self.submitted_jobs + job_count > MAX_POOL_JOBS:
            raise ValueError("native pool job lifetime exceeded")
        if _package_manifest() != self.manifest:
            raise ValueError("native pool producer source changed before dispatch")

    def submit(self, spec):
        if self.closed or self.submitted_jobs >= MAX_POOL_JOBS:
            raise ValueError("native pool is closed or exhausted")
        self.submitted_jobs += 1
        return self.executor.submit(_execute_pool_job, spec, self.manifest)

    def close(self):
        if not self.closed:
            self.closed = True
            self.executor.shutdown(wait=True, cancel_futures=True)

    def observation(self):
        return {"enabled": True, "max_workers": self.max_workers,
                "submitted_jobs": self.submitted_jobs, "max_pool_jobs": MAX_POOL_JOBS,
                "producer_manifest": self.manifest, "retained_model_state": False}
