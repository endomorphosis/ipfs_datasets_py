"""UNAPPLIED, UNQUALIFIED candidate for one paired shared successor receive.

An ordinary root@1 and selected direct child/delta remain unchanged. Shared
completion/page@3 and numerical chunk@2 bytes use their original RAW CIDs.
Entry replays native targets; optimized close only rebinds saved numerical
bytes before fresh native successor/source/model observations. Reference
retains both genuine public receiving calls and the composite closing fence.
The one-use closer belongs to this admitted operation and cannot be persisted.
Numerical bytes remain advisory; observations are sequential, never atomic.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import threading

from . import codebase_inventory_receiving as ordinary
from . import codebase_inventory_resume as resume
from . import codebase_inventory_shared_chunks as records
from . import codebase_inventory_shared_scan as shared
from . import codebase_inventory_successor as delta
from . import codebase_inventory_successor_model as successor
from . import codebase_inventory_successor_receiving as legacy_successor
from . import codebase_resume_shared_targets as transport

_MIB = 1024 * 1024
_MAX_METADATA_BYTES = 4 * _MIB
_MAX_GUARDS = 2 + 1024 + transport.MAX_INVENTORY_ENTRIES


def _pins():
    """Add local helper custody to the ordinary root's unchanged source pins."""
    paths = (Path(__file__), *(Path(module.__file__) for module in (
        shared, records, ordinary, legacy_successor, successor, delta, resume, transport)))
    result = []
    for path in paths:
        raw = path.read_bytes()
        resume._require(0 < len(raw) <= _MAX_METADATA_BYTES, "bounded shared receiver source required")
        result.append((path.name, len(raw), hashlib.sha256(raw).hexdigest()))
    return tuple(result)


def _bounded_metadata(value, label):
    size = len(resume._wire(value))
    resume._require(size <= _MAX_METADATA_BYTES, label + " exceeds retained metadata bound")
    return size


def _retention_charge(memory_mb, inputs, delta_guard, before, chain_guard, ledger, guards):
    """Charge actual retained serialized bytes beside the native phase ceiling.

    Four copies cover immutable input bodies and bounded metadata decoding/
    hashing transients. The native chain stays in the existing 224 MiB phased
    estimate. This is serialized accounting, not Python/native RSS containment.
    Legal large records may need a larger existing reservation or be refused;
    this candidate widens no record, deadline, scheduler or memory limit.
    """
    resume._require(type(memory_mb) is int, "exact shared receiver memory reservation required")
    immutable_bytes = sum(guard[1] for guard in inputs) + delta_guard[1]
    metadata_bytes = 0
    for label, value in (("native chain guards", chain_guard), ("completion ledger", ledger),
                         ("saved RAW/root guards", guards)):
        if value is not None:
            metadata_bytes += _bounded_metadata(value, label)
    baseline_bytes = ordinary._bytes_guard(before, 8 * _MIB)[0] if before is not None else 0
    charged = 224 * _MIB + 4 * (immutable_bytes + baseline_bytes + metadata_bytes)
    resume._require(charged <= memory_mb * _MIB // 4,
                    "shared successor retained serialized bytes exceed reservation")
    return charged


def _bounded_guards(guards):
    resume._require(len(guards) <= _MAX_GUARDS, "shared successor saved object population exceeds bound")
    _bounded_metadata(guards, "shared successor saved object guards")
    return tuple(guards)


def _completion_value(root, descriptors, coverage):
    r = root.to_dict()
    return {"schema": records.COMPLETION_SCHEMA, "profile": records.PROFILE,
        "root_cid": root.artifact_cid, "head_cid": r["head_cid"],
        "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"],
        "pages": descriptors, "coverage": coverage, "authority": dict(resume._FALSE)}


def _pure_walk(completion, index, root, remaining):
    """Rebind one saved page/chunk at a time without reconstructing targets.

    The exact entry guard vector is compared by the caller. Full entry replay
    supplies the target/source/transport meaning of these RAW bytes; hashing
    or this pure walk alone never grants currentness or formal authority.
    """
    remaining()
    resume._require(shared.load_codebase_scan_shared_completion(index.artifacts, completion.artifact_cid)._payload
                    == completion._payload, "durable shared successor completion bytes differ")
    c = records.bind_codebase_scan_chunked_completion_root(completion, root)
    limits = resume.CodebaseScanResumeLimits.from_dict(root.to_dict()["limits"])
    resume._require(len(c["pages"]) <= limits.max_pages, "shared successor page population exceeds root bound")
    guards = []
    shared._remember(root, guards)
    shared._remember(completion, guards)
    descriptors, counts, offset, inferred, projections, chunk_count = [], Counter(), 0, 0, 0, 0
    previous_page = None
    for descriptor in c["pages"]:
        remaining()
        page = shared.load_codebase_scan_shared_page(index.artifacts, descriptor["page_cid"])
        p = records.bind_codebase_scan_chunked_page_root(page, root)
        resume._require(records.page_descriptor(page) == descriptor and p["start"] == offset
                        and p["previous_page_cid"] == previous_page,
                        "shared successor page descriptor/order/prefix differs")
        shared._remember(page, guards)
        previous_chunk = None
        for chunk_descriptor in p["chunks"]:
            remaining()
            chunk = shared._check_chunk(index, root, page, chunk_descriptor, previous_chunk, remaining)
            shared._remember(chunk, guards)
            _bounded_guards(guards)
            previous_chunk = chunk.artifact_cid
            del chunk
        # The typed page shape already requires exact one-to-one descriptor
        # membership. Every descriptor above is joined to its actual chunk;
        # no complete list of numerical chunk bodies is retained.
        inferred += p["coverage"]["inferred_rows"]
        projections += p["coverage"]["projection_records"]
        chunk_count += len(p["chunks"])
        resume._require(inferred <= limits.max_inferred_rows, "shared successor global inference budget differs")
        counts.update(p["coverage"]["dispositions"])
        offset, previous_page = p["end"], page.artifact_cid
        descriptors.append(records.page_descriptor(page))
        _bounded_metadata(descriptors, "shared successor page descriptors")
        _bounded_guards(guards)
        del page, p
    coverage = {"inventory_entries": offset, "inferred_rows": inferred, "projection_records": projections,
        "chunks": chunk_count, "pages": len(descriptors), "dispositions": dict(sorted(counts.items()))}
    resume._require(offset == len(root.to_dict()["members"])
                    and resume._wire(_completion_value(root, descriptors, coverage)) == completion._payload,
                    "shared successor complete coverage differs")
    ledger = (tuple(descriptors), coverage)
    _bounded_metadata(ledger, "shared successor completion ledger")
    return ledger, _bounded_guards(guards)


@contextmanager
def _paired_current_codebase_shared_successor_completion(selection, completion, index, repository, *, root, registry,
        scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    """Yield one private close; consume it after callbacks and before action.

    This unapplied candidate performs no fitting, inference, signed admission,
    context decoding, supervisor dispatch or store activation. Normal exit
    requires a successful close. After close, scope release checks immutable
    inputs/pins only and performs no late source replay after a caller action.
    """
    resume._require(type(selection) is successor.CodebaseSuccessorScanRecord
                    and type(root) is resume.CodebaseScanResumeRoot
                    and type(completion) is records.CodebaseScanChunkedCompletion,
                    "exact selected successor/root/shared completion records required")
    limits = resume.CodebaseScanResumeLimits.from_dict(root.to_dict()["limits"])
    resume._require(limits.max_inventory_entries <= transport.MAX_INVENTORY_ENTRIES,
                    "shared successor requires inventory limit at most 512")
    records.bind_codebase_scan_chunked_completion_root(completion, root)
    with shared._scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (lease, signal, remaining, pending):
        pid, thread, thread_owner = os.getpid(), threading.get_ident(), threading.current_thread()
        inputs = (ordinary._record_guard(selection, successor.MAX_RECORD_BYTES),
            ordinary._record_guard(root, 4 * _MIB), ordinary._record_guard(completion, records.MAX_ARTIFACT_BYTES))
        owners, pins = ordinary._owner_guard(index, registry, repository), _pins()
        old_pins = legacy_successor._pins()
        source_owner = ordinary._inode_guard(index.artifacts.root, directory=True)
        s = selection.to_dict()
        optimized = s["optimized"]
        resume._require(s["root_cid"] == root.artifact_cid
                        and resume._wire(s["model"]) == resume._wire(root.to_dict()["model"])
                        and optimized is root.to_dict()["optimized"],
                        "shared completion belongs to another selected successor")
        source_delta = delta.load_codebase_source_delta(index.artifacts, s["source_delta_cid"])
        delta_guard = ordinary._record_guard(source_delta, 8 * _MIB)
        del s
        active, used, succeeded = True, False, False
        gate_lock = threading.Lock()
        chain = before = before_guard = chain_guard = ledger = guards = None
        _retention_charge(memory_mb, inputs, delta_guard, before, chain_guard, ledger, guards)

        def guarded():
            remaining()
            resume._require(os.getpid() == pid and threading.get_ident() == thread
                            and threading.current_thread() is thread_owner and not lease.released
                            and not pending, "shared successor paired operation ownership expired")
            resume._require(inputs == (ordinary._record_guard(selection, successor.MAX_RECORD_BYTES),
                ordinary._record_guard(root, 4 * _MIB),
                ordinary._record_guard(completion, records.MAX_ARTIFACT_BYTES))
                and ordinary._record_guard(source_delta, 8 * _MIB) == delta_guard,
                "shared successor paired immutable input bytes changed")
            resume._require(ordinary._owner_guard(index, registry, repository) == owners
                            and _pins() == pins and legacy_successor._pins() == old_pins,
                            "shared successor paired owners or implementation changed")
            resume._require(ordinary._inode_guard(index.artifacts.root, directory=True) == source_owner,
                            "shared successor paired source CAS directory changed")
            if before_guard is not None:
                resume._require(ordinary._bytes_guard(before, 8 * _MIB) == before_guard,
                                "shared successor paired registry baseline changed")
            _retention_charge(memory_mb, inputs, delta_guard, before, chain_guard, ledger, guards)

        def reference():
            guarded()
            actual = successor.validate_current_codebase_successor_scan(selection, index, repository,
                registry=registry, parent_lease=lease, cancel_event=signal,
                admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
                timeout_seconds=remaining(), memory_mb=memory_mb)
            resume._require(actual is selection, "shared successor reference changed selection")
            actual = shared.validate_current_codebase_shared_scan_completion(completion, index, repository,
                root=root, registry=registry, parent_lease=lease, cancel_event=signal,
                admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
                timeout_seconds=remaining(), memory_mb=memory_mb)
            resume._require(actual is completion, "shared successor reference changed completion")
            guarded()

        def close_native():
            # The old helper expects its OWN producer pin. The new closure is
            # separately fenced above. Root/selection/delta are DAG-JSON;
            # every completion/page/chunk guard is RAW with original identity.
            cas_guards = ((False, inputs[0]), (False, delta_guard),
                *((source, (identity, size, digest)) for identity, size, digest, source in guards))
            legacy_successor._close_native(selection, source_delta, root, chain, before, index, repository,
                registry, remaining, memory_mb, old_pins, cas_guards)
            resume._require(ordinary._chain_guard(chain, remaining) == chain_guard,
                            "shared successor paired native chain changed")
            guarded()

        # Both profiles retain an operation-owned exact native child/parent
        # lineage and registry baseline for the composite final closing fence.
        manifest, receipt, chain, before = legacy_successor._entry_successor(
            index, repository, root, registry, remaining, memory_mb)
        before_guard = ordinary._bytes_guard(before, 8 * _MIB)
        legacy_successor._selection_binding(selection, source_delta, root, chain, index, remaining)
        if optimized:
            saved = records.bind_codebase_scan_chunked_completion_root(completion, root)
            resume._require(shared.load_codebase_scan_shared_completion(index.artifacts, completion.artifact_cid)._payload
                            == completion._payload, "durable shared completion differs at entry")
            initial_guards = []
            shared._remember(root, initial_guards)
            shared._remember(completion, initial_guards)
            tail = saved["pages"][-1]["page_cid"] if saved["pages"] else None
            del saved
            descriptors, coverage = shared._walk(index, root, tail, manifest, receipt, chain, remaining, initial_guards)
            resume._require(coverage["inventory_entries"] == len(root.to_dict()["members"])
                            and resume._wire(_completion_value(root, descriptors, coverage)) == completion._payload,
                            "native shared successor completion ledger differs")
            ledger, guards = (tuple(descriptors), coverage), _bounded_guards(initial_guards)
            del initial_guards, descriptors, coverage
        else:
            ledger, guards = _pure_walk(completion, index, root, remaining)
        del manifest, receipt
        chain_guard = ordinary._chain_guard(chain, remaining)
        guarded()
        if not optimized:
            reference()
        # Public shared callbacks can edit a previously observed selection or
        # delta. The composite close is required after BOTH public receives.
        close_native()

        def close_current():
            nonlocal used, succeeded
            with gate_lock:
                resume._require(active and not used, "shared successor paired close inactive or already consumed")
                used = True
            guarded()
            resume._require(ordinary._chain_guard(chain, remaining) == chain_guard,
                            "shared successor paired native lineage changed")
            if not optimized:
                reference()
            current_ledger, current_guards = _pure_walk(completion, index, root, remaining)
            resume._require(current_guards == guards and resume._wire(current_ledger) == resume._wire(ledger),
                            "shared successor paired saved RAW objects or coverage changed")
            del current_ledger, current_guards
            close_native()
            succeeded = True
            return completion

        try:
            yield close_current
        except BaseException:
            raise
        else:
            resume._require(succeeded, "shared successor paired closing gate was not completed")
        finally:
            with gate_lock:
                active = False
            chain = before = before_guard = chain_guard = ledger = guards = None
    resume._require(inputs == (ordinary._record_guard(selection, successor.MAX_RECORD_BYTES),
        ordinary._record_guard(root, 4 * _MIB), ordinary._record_guard(completion, records.MAX_ARTIFACT_BYTES))
        and ordinary._record_guard(source_delta, 8 * _MIB) == delta_guard
        and _pins() == pins and legacy_successor._pins() == old_pins,
        "shared successor immutable inputs or helper bytes changed during resource closure")


__all__ = []
