"""Shared512 streamed numerical chunks with independent native closing.

This additive profile shares native manifest bytes within each request and
streams one restored input target into bounded feature rows. Existing scan
profiles retain their separate interpretation. Stored numerical values and lifecycle records
are advisory bytes, never proof or authenticated execution. Freshness checks
are sequential observations, not an atomic filesystem/database snapshot.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
import sysconfig
import threading
import time
import uuid

from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner, ToolRunLimits, OwnedToolCleanupError, run_bounded_stdin_tool,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as numerical
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane,
)
from . import codebase_inventory_resume as resume
from . import codebase_inventory_shared_chunks as records
from . import codebase_resume_shared_targets as transport
from . import codebase_ir_targets as targets
from . import codebase_source_training as training
from .codebase_inventory_targets import _member_disposition
from .codebase_resources import acquire_codebase_resources
from .content import cid_for_bytes, cid_for_structured

_wire = resume._wire
_require = resume._require
_MIB = 1024 * 1024
_QUARANTINES = {}
_QUARANTINE_LOCK = threading.Lock()


class _CleanupOwner:
    """Hold only this operation's reservations until actual cleanup succeeds."""

    def __init__(self, context, parent, pending):
        self.identifier = uuid.uuid4().hex
        self.context, self.parent, self.pending = context, parent, pending
        self.last_error = None
        self.lock = threading.Lock()
        self.context_exited = False

    def retry(self):
        with self.lock:
            accounting_errors = []
            for owned in [self.parent] + [child for child, _ in self.pending]:
                try:
                    if not owned.renew():
                        accounting_errors.append("owned reservation renewal refused")
                except Exception as error:
                    accounting_errors.append("owned reservation renewal failed: " + type(error).__name__)
            if accounting_errors:
                self.last_error = "; ".join(accounting_errors)
            remaining = []
            for child, handle in self.pending:
                observation = handle.retry_cleanup()
                if not observation.cleanup_confirmed:
                    remaining.append((child, handle))
                else:
                    child.release()
            self.pending = remaining
            if remaining:
                return False
            if not self.context_exited:
                # Preserve the explicit lease even if generator-context exit
                # itself fails while acknowledging release.
                self.context_exited = True
                self.context.__exit__(None, None, None)
            if not self.parent.released:
                self.parent.release()
            return self.parent.released

    def run(self):
        while True:
            try:
                if self.retry():
                    with _QUARANTINE_LOCK:
                        _QUARANTINES.pop(self.identifier, None)
                    return
            except BaseException as error:
                # A failed cleanup or state-file write cannot free capacity.
                self.last_error = type(error).__name__ + ": " + str(error)
            time.sleep(0.25)


def quarantined_codebase_shared_operations():
    """Source-free status; this function never releases a reservation."""
    with _QUARANTINE_LOCK:
        return [{"identifier": owner.identifier, "pending_children": len(owner.pending),
                 "parent_released": owner.parent.released, "error": owner.last_error}
                for owner in _QUARANTINES.values()]


@contextmanager
def _scope(index, registry, *, scheduler, parent_lease, cancel_event,
           admission_timeout_seconds, timeout_seconds, memory_mb):
    resume._owners(index, registry)
    _require(type(timeout_seconds) in {int, float} and math.isfinite(timeout_seconds)
             and 0 < timeout_seconds <= 600, "finite bounded chunk operation deadline required")
    _require(type(admission_timeout_seconds) in {int, float} and math.isfinite(admission_timeout_seconds)
             and 0 <= admission_timeout_seconds <= 600, "finite bounded chunk admission timeout required")
    resume._int(memory_mb, 64 * 1024, 1024)
    _require(224 * _MIB <= memory_mb * _MIB // 4, "serialized retention exceeds chunk memory reservation")
    deadline = time.monotonic() + timeout_seconds
    context = acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
        cancel_event=cancel_event, timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb)
    lease = context.__enter__()
    signal = lease.combined_cancellation_signal(cancel_event)
    pending = []

    def remaining():
        if signal.is_set():
            raise LeaseCancelledError("chunked inventory cancelled")
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise LeaseTimeoutError("chunked inventory deadline exceeded")
        return seconds

    try:
        remaining()
        yield lease, signal, remaining, pending
        remaining()
    finally:
        if pending:
            owner = _CleanupOwner(context, lease, pending)
            with _QUARANTINE_LOCK:
                _QUARANTINES[owner.identifier] = owner
            # Retain the context/leases even if thread startup raises. A failed
            # operation never starts another numerical child.
            thread = threading.Thread(target=owner.run, daemon=True,
                name="codebase-chunk-cleanup-" + owner.identifier[:8])
            thread.start()
        else:
            context.__exit__(None, None, None)


def _worker(request, lease, signal, remaining, memory_mb, limits, pending):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_shared_worker as worker
    executable, script = Path(sys.executable).resolve(), Path(worker.__file__).resolve()
    spec = importlib.util.find_spec("torch")
    _require(spec is not None and spec.origin is not None, "installed numerical dependency required")
    libraries = list(dict.fromkeys((str(Path(sysconfig.get_path("purelib")).resolve()),
                                   str(Path(spec.origin).resolve().parent.parent))))
    _require(all(Path(path).is_dir() for path in libraries), "installed numerical library roots required")
    executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    script_sha = hashlib.sha256(script.read_bytes()).hexdigest()
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
    child = lease.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=1, memory_mb=memory_mb,
        child_process_slots=1, timeout=remaining(), cancel_event=signal,
        request_id="codebase-inventory-chunk:inference")
    held = False
    try:
        request["max_seconds"] = min(600.0, remaining())
        raw = _wire(request)
        _require(len(raw) <= limits.max_input_bytes, "chunk worker input byte bound exceeded")
        bounds = ToolRunLimits(timeout_seconds=remaining(), resident_memory_bytes=memory_mb * _MIB,
            max_output_bytes=limits.max_output_bytes, max_input_bytes=limits.max_input_bytes,
            max_workspace_bytes=limits.max_input_bytes + limits.max_output_bytes)
        process = run_bounded_stdin_tool([str(executable), "-I", "-B", str(script), json.dumps(libraries)], raw,
            runner=runner, limits=bounds, cancellation=child.combined_cancellation_signal(signal),
            owned_process_observation=True)
        lifecycle = process.native_lifecycle
        _require(lifecycle is not None and lifecycle.cleanup_confirmed,
                 "actual numerical child lifecycle observation required")
    except OwnedToolCleanupError as error:
        held = True
        pending.append((child, error.cleanup_handle))
        raise
    finally:
        if not held:
            child.release()
    remaining()
    _require(process.returncode == 0 and not any((process.timed_out, process.cancelled, process.unavailable,
        process.output_truncated, process.resource_exhausted)) and process.workspace_cleaned,
        "chunk numerical child failed: " + str(process.termination_reason or process.error or "execution error")
        + ": " + process.stderr[-2048:])
    _require(hashlib.sha256(executable.read_bytes()).hexdigest() == executable_sha
             and hashlib.sha256(script.read_bytes()).hexdigest() == script_sha, "chunk numerical producer changed")
    response = json.loads(process.stdout, object_pairs_hook=worker._json_pairs, parse_constant=worker._json_constant)
    resume._closed(response, {"schema", "optimized", "inference", "counters", "worker"}, "chunk numerical response")
    _require(response["schema"] == worker.SCHEMA and response["optimized"] is request["optimized"],
             "chunk numerical worker profile differs")
    receipt = {"executable_sha256": executable_sha, "worker_sha256": script_sha,
        "input_sha256": hashlib.sha256(raw).hexdigest(), "output_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
        "input_bytes": len(raw), "output_bytes": len(process.stdout.encode()), "elapsed_ms": process.elapsed_ms,
        "returncode": process.returncode, "workspace_cleaned": process.workspace_cleaned,
        "limits": {"resident_memory_bytes": bounds.resident_memory_bytes, "max_input_bytes": bounds.max_input_bytes,
                   "max_output_bytes": bounds.max_output_bytes},
        "memory_enforcement": "sampled_process_tree_rss_with_possible_overshoot", "source_execution_attested": False}
    return response, receipt, lifecycle.to_dict()


def _payload(root, saved, shared_value):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_shared_worker as worker
    value = resume._payload(root, saved)
    value["schema"] = worker.SCHEMA
    value["shared_inventory"] = shared_value
    value["limits"].update(max_feature_cells=worker.MAX_FEATURE_CELLS,
                           max_retained_restored_targets=1)
    return value


def _transport_accounting(request, restored_bytes):
    return {"shared": len(_wire(request["shared_inventory"])),
        "compact_targets": sum(len(_wire(value)) for value in request["targets"]),
        "restored_targets": restored_bytes,
        "feature_cells": len(request["targets"]) * request["root"]["model"]["feature_columns"],
        "maximum_restored_targets": 1}


def _prepare_chunks(index, root, manifest, receipt, chain, start, inferred_before, remaining, consume):
    """Deterministic packing; consume flushes one request before its successor."""
    r, saved, provenance = root.to_dict(), chain[0][1], chain[0][2]
    limits = resume.CodebaseScanResumeLimits.from_dict(r["limits"])
    end = min(start + limits.page_entries, len(r["members"]))
    units = {unit.source_key: unit for unit in manifest.units}
    selected = {item.path: item for item in [training.CodebaseTrainingSelection.from_dict(value)
                                           for value in provenance["selections"]]}
    vocabulary = numerical.prepare_inventory_vocabulary(saved["feature_space"])
    shared_value = transport.create_resume_shared_inventory(resume._head(r["head"]), manifest, receipt)
    shared = transport.validate_resume_shared_inventory(shared_value)
    request, entries, chunk_rows = _payload(root, saved, shared_value), [], []
    inferred, ordinal, restored_bytes = inferred_before, 0, 0
    request_bytes = len(_wire(request))
    target_limits = targets.CodebaseTargetLimits(max_source_bytes=limits.max_file_bytes,
                                                  max_target_bytes=limits.max_target_bytes)
    known_errors = {
        "source or contract AST exceeds the bounded target profile": ("unsupported_target", "native_ast_shape_profile_bound"),
        "function inventory exceeds the target profile": ("unsupported_target", "native_function_count_profile_bound"),
        "contract identity or condition inventory exceeds the profile": ("unsupported_target", "authored_contract_inventory_profile_bound"),
        "captured source exceeds the target profile": ("deferred_budget", "native_source_byte_profile_bound"),
        "CodebaseIR target exceeds its byte bound": ("deferred_budget", "native_serialization_byte_profile_bound")}

    def flush():
        nonlocal request, request_bytes, chunk_rows, ordinal, restored_bytes
        if not request["targets"]:
            return
        remaining()
        _require(len(_wire(request)) == request_bytes, "exact chunk worker byte charge differs")
        consume(request, chunk_rows, ordinal, start, end,
                _transport_accounting(request, restored_bytes))
        remaining()
        ordinal += 1
        _require(ordinal <= limits.page_entries, "chunk population exceeds admitted page rows")
        request, chunk_rows = _payload(root, saved, shared_value), []
        request_bytes = len(_wire(request))
        restored_bytes = 0

    for member_index in range(start, end):
        remaining()
        entry = manifest.snapshot.entries[member_index]
        unit = units[entry.source_key]
        raw, record = resume._member_native(index, manifest, entry, unit, limits, remaining,
            snapshot_cid=r["head"]["snapshot_cid"] if r["optimized"] else None)
        disposition, frontiers = _member_disposition(entry, unit, record)
        if disposition == "unsupported_extension":
            disposition = "unsupported_target"
        row = {"member_index": member_index, "source_key": entry.source_key, "entry_cid": entry.entry_cid,
            "disposition": disposition, "reason": None if not frontiers else frontiers[0]["reason"],
            "target_sha256": None, "source_digest": None, "coverage": [], "chunk_ordinal": None, "row_index": None}
        if disposition == "captured_python":
            selection = selected.get(entry.path)
            specs = targets._specs(selection.contracts if selection else (), target_limits)
            try:
                target = targets._prepare_bound(binding=targets._binding(resume._head(r["head"]), manifest, entry, unit, raw),
                    manifest=manifest, receipt=receipt, ast_record=record, raw=raw, specs=specs, limits=target_limits)
            except targets.CodebaseTargetError as error:
                if type(error) is not targets.CodebaseTargetError or str(error) not in known_errors:
                    raise
                row["disposition"], row["reason"] = known_errors[str(error)]
            else:
                value = target.to_dict()
                row["target_sha256"] = hashlib.sha256(target.canonical_bytes).hexdigest()
                row["source_digest"] = value["source_digest"]
                if value["ready_for_training"] is not True:
                    row["disposition"], row["reason"] = "unsupported_target", "native_target_not_complete"
                else:
                    coverage = numerical.inventory_target_coverage(vocabulary, target)
                    row["coverage"] = coverage["coverage"]
                    if not coverage["compatible"]:
                        row["disposition"], row["reason"] = "feature_incompatible", "projection_has_no_known_atoms"
                    elif inferred >= limits.max_inferred_rows:
                        row["disposition"], row["reason"] = "deferred_budget", "global_inferred_row_budget"
                    else:
                        compact = transport.compact_resume_target(target, shared)
                        compact_bytes = len(_wire(compact))
                        full_bytes = len(target.canonical_bytes)
                        def fits():
                            charge = compact_bytes + len(str(member_index)) + (2 if request["targets"] else 0)
                            if (len(request["targets"]) + 1) * r["model"]["feature_columns"] > 262144:
                                return False, charge
                            if compact_bytes > limits.max_target_bytes or full_bytes > limits.max_target_bytes:
                                return False, charge
                            if r["optimized"]:
                                return request_bytes + charge + 64 <= limits.max_input_bytes, charge
                            candidate = {**request, "targets": request["targets"] + [compact],
                                         "member_indices": request["member_indices"] + [member_index]}
                            return len(_wire(candidate)) + 64 <= limits.max_input_bytes, charge
                        accepted, charge = fits()
                        if not accepted and request["targets"]:
                            flush()
                            accepted, charge = fits()
                        if not accepted:
                            row["disposition"], row["reason"] = "deferred_budget", "single_target_worker_input_byte_budget"
                        else:
                            row["disposition"], row["reason"] = "inferred", None
                            row["chunk_ordinal"], row["row_index"] = ordinal, len(chunk_rows)
                            request["targets"].append(compact)
                            restored_bytes += full_bytes
                            request["member_indices"].append(member_index)
                            request_bytes += charge
                            chunk_rows.append(row)
                            inferred += 1
                        del compact
                del value, target
        entries.append(row)
        del raw, record
    flush()
    remaining()
    _require(manifest.cid == r["head"]["manifest_cid"]
             and manifest.snapshot.snapshot_cid == r["head"]["snapshot_cid"], "chunk native manifest changed during replay")
    return entries


def _load(artifacts, identity, cls):
    resume._cas(artifacts)
    resume._cid(identity, "raw")
    resume._artifact_size(artifacts, identity, records.MAX_ARTIFACT_BYTES, source=True)
    return cls(identity, artifacts.get_bytes(identity))


def load_codebase_scan_shared_numerical_chunk(artifacts, identity):
    return _load(artifacts, identity, records.CodebaseScanNumericalChunk)


def load_codebase_scan_shared_page(artifacts, identity):
    return _load(artifacts, identity, records.CodebaseScanChunkedPage)


def load_codebase_scan_shared_completion(artifacts, identity):
    return _load(artifacts, identity, records.CodebaseScanChunkedCompletion)


def _check_chunk(index, root, page, descriptor, previous, remaining):
    p = page.to_dict()
    chunk = load_codebase_scan_shared_numerical_chunk(index.artifacts, descriptor["chunk_cid"])
    value = records.bind_codebase_scan_chunk(chunk, root)
    _require(records.chunk_descriptor(chunk) == descriptor
             and value["page_start"] == p["start"] and value["page_end"] == p["end"]
             and value["previous_chunk_cid"] == previous, "saved chunk descriptor/prefix/page binding differs")
    width = len(root.to_dict()["model"]["projection_ids"])
    for row_index, member_index in enumerate(value["member_indices"]):
        remaining()
        entry = p["entries"][member_index - p["start"]]
        _require(entry["disposition"] == "inferred" and entry["chunk_ordinal"] == value["chunk_ordinal"]
                 and entry["row_index"] == row_index
                 and entry["target_sha256"] == value["target_sha256s"][row_index]
                 and entry["source_digest"] == value["source_digests"][row_index]
                 and _wire(entry["coverage"]) == _wire(value["inference"]["coverage"][row_index * width:(row_index + 1) * width]),
                 "saved chunk target/source/coverage mapping differs")
    return chunk


def _page_chunks(index, root, page, remaining):
    records.bind_codebase_scan_chunked_page_root(page, root)
    previous = None
    for descriptor in page.to_dict()["chunks"]:
        remaining()
        chunk = _check_chunk(index, root, page, descriptor, previous, remaining)
        previous = chunk.artifact_cid
        del chunk


def _guard(artifacts, guards, remaining):
    for identity, size, digest, source in guards:
        remaining()
        resume._artifact_size(artifacts, identity, size, source=source)
        raw = artifacts.get_bytes(identity) if source else resume.canonical_dag_json_bytes(artifacts.get(identity))
        _require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
                 "durable chunk/page/root bytes changed during native observation")
        del raw
    remaining()


def _remember(record, guards):
    guards.append((record.artifact_cid, len(record._payload), hashlib.sha256(record._payload).hexdigest(),
                   type(record) is not resume.CodebaseScanResumeRoot))


def _guard_direct(artifacts, guards, remaining):
    """Final bounded ordinary-byte check without calling CAS extension hooks."""
    from .cache import ImmutableCAS
    for identity, size, digest, source in guards:
        remaining()
        path = ImmutableCAS.path_for(artifacts, identity, source=source)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            _require(stat.S_ISREG(before.st_mode) and before.st_size == size,
                     "closing chunk/root ordinary file bounds differ")
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                raw = stream.read(size + 1)
            after = os.fstat(descriptor)
            named = path.lstat()
            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                     and (named.st_dev, named.st_ino) == (after.st_dev, after.st_ino)
                     and stat.S_ISREG(named.st_mode)
                     and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
                     "closing numerical/root ordinary bytes changed")
        finally:
            os.close(descriptor)
        del raw
    remaining()


def _walk(index, root, tail, manifest, receipt, chain, remaining, guards):
    limits = resume.CodebaseScanResumeLimits.from_dict(root.to_dict()["limits"])
    reversed_ids, seen, expected_start = [], set(), None
    while tail is not None:
        remaining()
        _require(tail not in seen and len(seen) < limits.max_pages, "duplicate or oversized chunked page chain")
        seen.add(tail)
        page = load_codebase_scan_shared_page(index.artifacts, tail)
        records.bind_codebase_scan_chunked_page_root(page, root)
        p = page.to_dict()
        if expected_start is not None:
            _require(p["end"] == expected_start, "chunked page omission/overlap")
        expected_start = p["start"]
        reversed_ids.append(tail)
        tail = p["previous_page_cid"]
    _require(not reversed_ids or expected_start == 0, "chunked prefix must begin at zero")
    descriptors, counts, offset, inferred, projections, chunk_count = [], Counter(), 0, 0, 0, 0
    for identity in reversed(reversed_ids):
        page = load_codebase_scan_shared_page(index.artifacts, identity)
        p = page.to_dict()
        _require(p["start"] == offset, "chunked page chain gap")
        records.bind_codebase_scan_chunked_page_root(page, root)
        _remember(page, guards)
        replayed = 0
        def replay(request, entries, ordinal, start, end, accounting):
            nonlocal replayed
            _require(ordinal < len(p["chunks"]), "missing saved numerical chunk")
            descriptor = p["chunks"][ordinal]
            previous = p["chunks"][ordinal - 1]["chunk_cid"] if ordinal else None
            chunk = _check_chunk(index, root, page, descriptor, previous, remaining)
            _remember(chunk, guards)
            saved = chunk.to_dict()
            _require(saved["member_indices"] == request["member_indices"]
                     and saved["target_sha256s"] == [row["target_sha256"] for row in entries]
                     and saved["source_digests"] == [row["source_digest"] for row in entries]
                     and saved["shared_inventory_sha256"] == request["shared_inventory"]["shared_sha256"]
                     and _wire(saved["transport_bytes"]) == _wire(accounting),
                     "native saved chunk target/source/order/shared transport differs")
            replayed += 1
        expected = _prepare_chunks(index, root, manifest, receipt, chain, offset, inferred, remaining, replay)
        _require(_wire(expected) == _wire(p["entries"]) and replayed == len(p["chunks"]),
                 "native chunked dispositions/coverage/mapping differ")
        inferred += p["coverage"]["inferred_rows"]
        _require(inferred <= limits.max_inferred_rows, "global chunked inference budget exceeded")
        projections += p["coverage"]["projection_records"]
        chunk_count += len(p["chunks"])
        counts.update(p["coverage"]["dispositions"])
        offset = p["end"]
        descriptors.append(records.page_descriptor(page))
        del page, p, expected
    return descriptors, {"inventory_entries": offset, "inferred_rows": inferred,
        "projection_records": projections, "chunks": chunk_count, "pages": len(descriptors),
        "dispositions": dict(sorted(counts.items()))}


def _close(index, repository, root, registry, chain, before, remaining, memory_mb, guards):
    _guard(index.artifacts, guards, remaining)
    resume._close(index, repository, root, registry, chain, before, remaining, memory_mb)
    # Final native byte reads bypass optional CAS callbacks, so they cannot
    # mutate live source/model owners after their closing observation.
    # Concurrent external writes remain detectable sequential observations,
    # not an atomic multi-owner snapshot.
    _guard_direct(index.artifacts, guards, remaining)


def start_current_codebase_shared_scan(*args, **kwargs):
    """Create a fresh ordinary root bound to the complete current implementation."""
    limits = kwargs.get("limits")
    if limits is None:
        limits = resume.CodebaseScanResumeLimits(max_inventory_entries=512)
    _require(type(limits) is resume.CodebaseScanResumeLimits and limits.max_inventory_entries <= 512,
             "shared512 root inventory limit required")
    kwargs["limits"] = limits
    return resume.start_current_codebase_scan(*args, **kwargs)


def scan_current_codebase_page_shared(index, repository, *, root, registry, cursor=None, scheduler=None,
        parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    _require(cursor is None or type(cursor) is records.CodebaseScanChunkedCursor, "exact chunked cursor required")
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (lease, signal, remaining, pending):
        manifest, receipt, chain, before = resume._entry(index, repository, root, registry, remaining, memory_mb)
        r = root.to_dict()
        limits = resume.CodebaseScanResumeLimits.from_dict(r["limits"])
        guards = []
        _remember(root, guards)
        if cursor is None:
            start, previous, inferred = 0, None, 0
        else:
            _require(cursor.root_cid == root.artifact_cid, "chunked cursor belongs to another root")
            descriptors, coverage = _walk(index, root, cursor.previous_page_cid,
                manifest, receipt, chain, remaining, guards)
            start, inferred = coverage["inventory_entries"], coverage["inferred_rows"]
            _require(start == cursor.next_offset and len(descriptors) < limits.max_pages, "chunked cursor prefix differs")
            previous = cursor.previous_page_cid
        _require(start < len(r["members"]), "no members remain; complete the chunked chain")
        chunk_descriptors = []
        def consume(request, rows, ordinal, page_start, page_end, accounting):
            response, worker_receipt, lifecycle = _worker(request, lease, signal, remaining, memory_mb, limits, pending)
            value = {"schema": records.CHUNK_SCHEMA, "profile": records.PROFILE,
                "root_cid": root.artifact_cid, "head_cid": r["head_cid"], "membership_cid": r["membership_cid"],
                "model_artifact_cid": r["model"]["artifact_cid"], "model_state_sha256": r["model"]["state_sha256"],
                "optimized": r["optimized"], "page_start": page_start, "page_end": page_end,
                "chunk_ordinal": ordinal, "previous_chunk_cid": chunk_descriptors[-1]["chunk_cid"] if ordinal else None,
                "member_indices": list(request["member_indices"]),
                "target_sha256s": [row["target_sha256"] for row in rows], "source_digests": [row["source_digest"] for row in rows],
                "inference": response["inference"], "worker_receipt": worker_receipt,
                "worker_counters": response["counters"], "worker_profile": response["worker"],
                "lifecycle_receipt": lifecycle, "authority": dict(resume._FALSE),
                "shared_inventory_sha256": request["shared_inventory"]["shared_sha256"],
                "transport_bytes": accounting}
            metadata = {**value, "inference": None}
            inference_raw = _wire(value["inference"])
            _require(len(_wire(metadata)) + len(inference_raw) - 4 <= limits.max_output_bytes,
                     "numerical chunk plus provenance framing exceeds artifact byte bound")
            remaining()
            raw = _wire(value)
            chunk = records.CodebaseScanNumericalChunk(cid_for_bytes(raw), raw)
            records.bind_codebase_scan_chunk(chunk, root)
            remaining()
            _require(index.artifacts.put_bytes(raw) == chunk.artifact_cid, "durable numerical chunk publication differs")
            chunk_descriptors.append(records.chunk_descriptor(chunk))
            _remember(chunk, guards)
            remaining()
        entries = _prepare_chunks(index, root, manifest, receipt, chain, start, inferred, remaining, consume)
        del manifest, receipt
        end = start + len(entries)
        counts = dict(sorted(Counter(row["disposition"] for row in entries).items()))
        value = {"schema": records.PAGE_SCHEMA, "profile": records.PROFILE,
            "root_cid": root.artifact_cid, "head_cid": r["head_cid"], "membership_cid": r["membership_cid"],
            "model_artifact_cid": r["model"]["artifact_cid"], "start": start, "end": end,
            "total_entries": len(r["members"]), "page_membership_cid": cid_for_structured(r["members"][start:end]),
            "previous_page_cid": previous, "entries": entries, "chunks": chunk_descriptors,
            "coverage": {"inventory_entries": len(entries), "inferred_rows": counts.get("inferred", 0),
                "projection_records": sum(len(row["coverage"]) for row in entries if row["disposition"] == "inferred"),
                "chunks": len(chunk_descriptors), "dispositions": counts}, "authority": dict(resume._FALSE)}
        raw = _wire(value)
        page = records.CodebaseScanChunkedPage(cid_for_bytes(raw), raw)
        _page_chunks(index, root, page, remaining)
        remaining()
        _require(index.artifacts.put_bytes(raw) == page.artifact_cid, "durable chunked page publication differs")
        _remember(page, guards)
        _close(index, repository, root, registry, chain, before, remaining, memory_mb, guards)
        return page


def _receive(index, repository, *, root, registry, tail, completion, scheduler, parent_lease,
             cancel_event, admission_timeout_seconds, timeout_seconds, memory_mb, page=None):
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (_, _, remaining, _):
        manifest, receipt, chain, before = resume._entry(index, repository, root, registry, remaining, memory_mb)
        guards = []
        _remember(root, guards)
        if page is not None:
            _require(load_codebase_scan_shared_page(index.artifacts, page.artifact_cid) == page,
                     "durable chunked page differs")
        if completion is not None:
            _require(load_codebase_scan_shared_completion(index.artifacts, completion.artifact_cid) == completion,
                     "durable chunked completion differs")
            value = records.bind_codebase_scan_chunked_completion_root(completion, root)
            tail = value["pages"][-1]["page_cid"] if value["pages"] else None
            _remember(completion, guards)
        descriptors, coverage = _walk(index, root, tail, manifest, receipt, chain, remaining, guards)
        del manifest, receipt
        value = {"schema": records.COMPLETION_SCHEMA, "profile": records.PROFILE,
            "root_cid": root.artifact_cid, "head_cid": root.to_dict()["head_cid"],
            "membership_cid": root.to_dict()["membership_cid"],
            "model_artifact_cid": root.to_dict()["model"]["artifact_cid"],
            "pages": descriptors, "coverage": coverage, "authority": dict(resume._FALSE)}
        if completion is not None:
            _require(_wire(value) == completion._payload, "native chunked completion ledger differs")
        _close(index, repository, root, registry, chain, before, remaining, memory_mb, guards)
        return value


def validate_current_codebase_shared_scan_page(page, index, repository, *, root, registry, scheduler=None,
        parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    _require(type(page) is records.CodebaseScanChunkedPage, "exact chunked page required")
    _receive(index, repository, root=root, registry=registry, tail=page.artifact_cid, completion=None,
        scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
        admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb, page=page)
    return page


def complete_current_codebase_shared_scan(index, repository, *, root, registry, tail_page_cid=None, scheduler=None,
        parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    # Completion publication is a callback too; keep this entire operation in
    # one admitted scope and close after publishing the candidate record.
    with _scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (_, _, remaining, _):
        manifest, receipt, chain, before = resume._entry(index, repository, root, registry, remaining, memory_mb)
        guards = []
        _remember(root, guards)
        descriptors, coverage = _walk(index, root, tail_page_cid, manifest, receipt, chain, remaining, guards)
        del manifest, receipt
        r = root.to_dict()
        _require(coverage["inventory_entries"] == len(r["members"]), "incomplete inventory cannot become completion")
        value = {"schema": records.COMPLETION_SCHEMA, "profile": records.PROFILE, "root_cid": root.artifact_cid,
            "head_cid": r["head_cid"], "membership_cid": r["membership_cid"],
            "model_artifact_cid": r["model"]["artifact_cid"], "pages": descriptors, "coverage": coverage,
            "authority": dict(resume._FALSE)}
        raw = _wire(value)
        completion = records.CodebaseScanChunkedCompletion(cid_for_bytes(raw), raw)
        records.bind_codebase_scan_chunked_completion_root(completion, root)
        remaining()
        _require(index.artifacts.put_bytes(raw) == completion.artifact_cid, "durable chunked completion publication differs")
        _remember(completion, guards)
        _close(index, repository, root, registry, chain, before, remaining, memory_mb, guards)
        return completion


def validate_current_codebase_shared_scan_completion(completion, index, repository, *, root, registry,
        scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    _require(type(completion) is records.CodebaseScanChunkedCompletion, "exact chunked completion required")
    _receive(index, repository, root=root, registry=registry, tail=None, completion=completion,
        scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
        admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb)
    return completion


__all__ = ["start_current_codebase_shared_scan", "scan_current_codebase_page_shared",
    "complete_current_codebase_shared_scan", "validate_current_codebase_shared_scan_page",
    "validate_current_codebase_shared_scan_completion", "load_codebase_scan_shared_numerical_chunk",
    "load_codebase_scan_shared_page", "load_codebase_scan_shared_completion",
    "quarantined_codebase_shared_operations"]
