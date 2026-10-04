"""Private one-operation receiving of an explicitly selected successor scan.

Entry replays the complete native lineage and every completed page target.
Closing streams exact CAS bytes and repeats source/history/model/registry
fences without retaining page bodies or repeating page target construction.
The closer is private, consumed once and never serialized as currentness.
Checks are sequential observations; numerical bytes remain advisory.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import threading

from . import codebase_inventory_receiving as receiving
from . import codebase_inventory_resume as scan
from . import codebase_inventory_successor as delta
from . import codebase_inventory_successor_model as successor

_MIB = 1024 * 1024
_MAX_METADATA_BYTES = 4 * _MIB


def _pins():
    # Ordinary roots retain their original seventeen-file implementation.
    # This new private receiving algorithm closes its own additional bytes.
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _direct_cas_guards(artifacts, guards, remaining):
    """Read entry-validated bytes after callbacks without a CAS method hook.

    Every expected length/SHA/CID originates in this operation's typed native
    replay. Directory descriptors and regular single-link files prevent alias
    substitution; streaming hashes retain no page body. This is byte custody,
    never a replacement for the entry's native target or owner verification.
    """
    scan._cas(artifacts)
    descriptor = os.open(artifacts.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for source, expected in guards:
            remaining()
            wanted, length, digest = expected
            scan._cid(wanted, "raw" if source else "dag-json")
            codec = os.open("source" if source else "structured", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            try:
                partition = os.open(wanted[:4], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=codec)
                try:
                    fd = os.open(wanted, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=partition)
                    with os.fdopen(fd, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        scan._require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                                      and before.st_size == length and 0 < length <= 16 * _MIB,
                                      "successor retained CAS object type or length changed")
                        actual, amount = hashlib.sha256(), 0
                        while True:
                            remaining()
                            chunk = stream.read(min(65536, length + 1 - amount))
                            if not chunk:
                                break
                            amount += len(chunk)
                            scan._require(amount <= length, "successor retained CAS object grew")
                            actual.update(chunk)
                        after = os.fstat(stream.fileno())
                        path_after = os.stat(wanted, dir_fd=partition, follow_symlinks=False)
                        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_nlink")
                        scan._require(amount == length and actual.hexdigest() == digest
                                      and all(getattr(before, name) == getattr(after, name) == getattr(path_after, name)
                                              for name in fields), "successor retained CAS bytes changed after callbacks")
                finally:
                    os.close(partition)
            finally:
                os.close(codec)
    finally:
        os.close(descriptor)


def _models(chain, index, remaining):
    scan._require(len(chain) >= 2, "successor completion requires a registered direct child")
    return {"previous_training_record_cid": successor._published_training_record(index, chain[1], remaining),
        "training_record_cid": successor._published_training_record(index, chain[0], remaining),
        "previous_model": scan._model(chain[1:]), "model": scan._model(chain)}


def _selection_binding(selection, source_delta, root, chain, index, remaining):
    s, d = selection.to_dict(), source_delta.to_dict()
    scan._require(chain[0][0]["parent_version_id"] == s["previous_model"]["version_id"]
                  and chain[1][0]["version_id"] == s["previous_model"]["version_id"]
                  and scan._wire(chain[0][2]["head"]) == scan._wire(d["current_head"])
                  and scan._wire(chain[1][2]["head"]) == scan._wire(d["previous_head"]),
                  "successor completed scan parent or source heads differ")
    models = _models(chain, index, remaining)
    successor._root_binding(root, source_delta, models,
        scan.CodebaseScanResumeLimits.from_dict(s["scan_limits"]), s["optimized"])
    expected = successor._value(source_delta, models, root, s["optimized"], successor._implementation())
    scan._require(scan.canonical_dag_json_bytes(expected) == selection._payload,
                  "successor completion selection differs from native lineage")


def _history_not_covered_by_delta(index, chain, value, limits, remaining, optimized):
    """Avoid a duplicate replay only when the delta closes every history head.

    The following full native delta observation always replays both declared
    captures. An ancestry with any other replay/evaluation head retains the
    unchanged complete historical fence. This is operation-local coverage,
    never a persisted currentness token or a source/model bypass.
    """
    heads = scan.legacy._history_heads(chain)
    covered = (scan._head(value["previous_head"]), scan._head(value["current_head"]))
    remaining()
    if not all(head in covered for head in heads):
        scan._history_fence(index, chain, covered[1], limits, remaining, optimized=optimized)


def _entry_successor(index, repository, root, registry, remaining, memory_mb):
    """Native scan entry with complete history closure after page callbacks.

    Membership, current capture, full registered lineage and model bindings
    receive their unchanged native checks. The history phase runs in the final
    full delta/uncovered-history fence before this operation can yield. This
    avoids an earlier observation whose work must be repeated after pages.
    """
    scan._require(type(root) is scan.CodebaseScanResumeRoot, "exact native successor root required")
    scan._require(scan.load_codebase_scan_resume_root(index.artifacts, root.artifact_cid)._payload == root._payload,
                  "durable successor root bytes differ")
    r = root.to_dict()
    limits = scan.CodebaseScanResumeLimits.from_dict(r["limits"])
    scan._require(r["implementation"] == scan._implementation(), "successor resume implementation changed")
    before = scan.legacy._registry_inventory(registry, scan.legacy.CodebaseInventoryScanLimits(), remaining)
    manifest, receipt = scan._observe(index, repository, scan._head(r["head"]), limits, remaining, memory_mb,
                                     optimized=r["optimized"])
    scan._require(scan._wire(scan._members(manifest)) == scan._wire(r["members"]), "successor global membership differs")
    chain = scan._resume_lineage(index, registry, r["model"]["version_id"],
        scan.training.CodebaseFeatureTrainingLimits(), remaining, optimized=r["optimized"])
    remaining()
    scan._require(scan._wire(scan._model(chain)) == scan._wire(r["model"])
                  and scan._wire(chain[0][2]["head"]) == scan._wire(r["head"]),
                  "successor native model/head/basis differs")
    return manifest, receipt, chain, before


def _close_native(selection, source_delta, root, chain, before, index, repository, registry,
                  remaining, memory_mb, pins, cas_guards):
    """All callback-capable CAS observations precede final model/source fences."""
    s, d, r = selection.to_dict(), source_delta.to_dict(), root.to_dict()
    scan._require(successor.load_codebase_successor_scan(index.artifacts, selection.artifact_cid)._payload
                  == selection._payload, "durable successor selection bytes changed")
    scan._require(scan.load_codebase_scan_resume_root(index.artifacts, root.artifact_cid)._payload == root._payload,
                  "durable successor root bytes changed")
    scan._require(delta.load_codebase_source_delta(index.artifacts, source_delta.artifact_cid)._payload
                  == source_delta._payload, "durable successor source delta bytes changed")
    _selection_binding(selection, source_delta, root, chain, index, remaining)
    limits = scan.CodebaseScanResumeLimits.from_dict(r["limits"])
    _history_not_covered_by_delta(index, chain, d, limits, remaining, r["optimized"])
    # Replay both complete historical/current native captures, all relational
    # projections, source/AST CAS and the current checkout. No model is opened.
    observed = delta._observe(index, repository, scan._head(d["previous_head"]), scan._head(d["current_head"]),
        delta.CodebaseSourceDeltaLimits.from_dict(d["limits"]), remaining, memory_mb,
        d["optimized"], delta._implementation())
    scan._require(scan.canonical_dag_json_bytes(observed) == source_delta._payload,
                  "current successor structural source delta changed")
    del observed
    manifest = index.load(scan._head(d["current_head"]).manifest_cid)
    # A CAS callback can alter a checkpoint without changing the source head.
    # Recheck complete native checkpoint bytes and the registry after ALL CAS
    # reads, then directly replay SQL/current source without another CAS read.
    scan.legacy._model_fence(registry, chain, remaining)
    scan._require(scan.legacy._registry_inventory(registry, scan.legacy.CodebaseInventoryScanLimits(), remaining)
                  == before, "successor receiving registry namespace changed")
    scan._require(s["implementation"] == successor._implementation()
                  and r["implementation"] == scan._implementation() and _pins() == pins,
                  "successor receiving producer bytes changed")
    _direct_cas_guards(index.artifacts, cas_guards, remaining)
    successor._source_exit(index, repository, manifest, source_delta, remaining, r["optimized"])
    del manifest
    scan._owners(index, registry)
    remaining()


@contextmanager
def _paired_current_codebase_successor_completion(selection, completion, index, repository, *, root, registry,
        scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    """Yield a one-use closing gate for an exact complete selected successor.

    Full native entry precedes owner callbacks; the caller consumes the closer
    before transaction commit or Popen. Normal exit requires successful close.
    Cleanup does no native work after launch or a permitted source edit. The
    opt-out retains both unchanged public receiving calls at entry and close.
    """
    scan._require(type(selection) is successor.CodebaseSuccessorScanRecord
                  and type(root) is scan.CodebaseScanResumeRoot
                  and type(completion) is scan.CodebaseScanResumeCompletion,
                  "exact immutable successor, root and completion records required")
    with scan._scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (lease, signal, remaining):
        # Ordinary phased retention224MiB + three4MiB metadata ledgers + an
        # immutable8MiB delta + a256KiB selection stay below256MiB. Page bodies
        # are streamed; cache indexes disappear before history/source phases.
        # This serialized accounting is neither Python/native RSS containment
        # nor a claim about kernel resource enforcement.
        scan._require(248 * _MIB <= memory_mb * _MIB // 4,
                      "successor paired serialized retention exceeds memory reservation")
        pid, thread = os.getpid(), threading.get_ident()
        inputs = (receiving._record_guard(selection, successor.MAX_RECORD_BYTES),
                  receiving._record_guard(root, 4 * _MIB), receiving._record_guard(completion, 4 * _MIB))
        owners, pins = receiving._owner_guard(index, registry, repository), _pins()
        source_owner = receiving._inode_guard(index.artifacts.root, directory=True)
        s = selection.to_dict()
        scan._require(s["root_cid"] == root.artifact_cid
                      and scan._wire(s["model"]) == scan._wire(root.to_dict()["model"]),
                      "completed inventory belongs to another successor selection")
        source_delta = delta.load_codebase_source_delta(index.artifacts, s["source_delta_cid"])
        delta_guard = receiving._record_guard(source_delta, 8 * _MIB)
        active, used, succeeded = True, False, False
        chain = before = before_guard = chain_guard = ledger = page_guards = None

        def guarded():
            remaining()
            scan._require(os.getpid() == pid and threading.get_ident() == thread and not lease.released,
                          "successor paired native operation ownership expired")
            scan._require(inputs == (receiving._record_guard(selection, successor.MAX_RECORD_BYTES),
                          receiving._record_guard(root, 4 * _MIB), receiving._record_guard(completion, 4 * _MIB))
                          and receiving._record_guard(source_delta, 8 * _MIB) == delta_guard,
                          "successor paired immutable input bytes changed")
            scan._require(receiving._owner_guard(index, registry, repository) == owners and _pins() == pins,
                          "successor paired native owners or implementation changed")
            scan._require(receiving._inode_guard(index.artifacts.root, directory=True) == source_owner,
                          "successor paired source CAS directory changed")
            if before_guard is not None:
                scan._require(receiving._bytes_guard(before, 8 * _MIB) == before_guard,
                              "successor paired registry baseline changed")

        def reference():
            guarded()
            actual = successor.validate_current_codebase_successor_scan(selection, index, repository, registry=registry,
                parent_lease=lease, cancel_event=signal,
                admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
                timeout_seconds=remaining(), memory_mb=memory_mb)
            scan._require(actual is selection, "successor reference selected another model/source record")
            actual = scan.validate_current_codebase_scan_completion(completion, index, repository, root=root,
                registry=registry, parent_lease=lease, cancel_event=signal,
                admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
                timeout_seconds=remaining(), memory_mb=memory_mb)
            scan._require(actual is completion, "successor reference selected another completion")
            guarded()

        if not s["optimized"]:
            reference()
        else:
            manifest, receipt, chain, before = _entry_successor(index, repository, root, registry, remaining, memory_mb)
            before_guard = receiving._bytes_guard(before, 8 * _MIB)
            _selection_binding(selection, source_delta, root, chain, index, remaining)
            page_guards = []
            def full_page(page, inferred):
                scan._replay_page(index, root, manifest, receipt, chain, page, inferred, remaining)
                page_guards.append(receiving._record_guard(page, 16 * _MIB))
                scan._require(len(page_guards) <= 1024
                              and len(scan._wire(page_guards)) <= _MAX_METADATA_BYTES,
                              "successor page metadata exceeds bound")
            ledger = receiving._completion_walk(completion, index, root, remaining, full_page)
            page_guards = tuple(page_guards)
            scan._require(len(scan._wire(ledger)) <= _MAX_METADATA_BYTES,
                          "successor completion metadata exceeds bound")
            del manifest, receipt
            chain_guard = receiving._chain_guard(chain, remaining)
            # The complete old/current structural delta is replayed here,
            # after every page/CAS callback and before the gate is yielded.
            # Repeating the public delta receiver before the page walk would
            # add two earlier observations without closing later callbacks.
            _close_native(selection, source_delta, root, chain, before, index, repository, registry,
                          remaining, memory_mb, pins,
                          ((False, inputs[0]), (False, inputs[1]), (False, inputs[2]), (False, delta_guard),
                           *((True, guard) for guard in page_guards)))
            scan._require(receiving._chain_guard(chain, remaining) == chain_guard,
                          "successor paired entry native chain changed")
            guarded()

        def close_current():
            nonlocal used, succeeded
            scan._require(active and not used, "successor paired closing gate inactive or already used")
            used = True
            guarded()
            if not s["optimized"]:
                reference()
            else:
                scan._require(receiving._chain_guard(chain, remaining) == chain_guard,
                              "successor paired native lineage changed")
                ordinal = 0
                def same_page(page, inferred):
                    nonlocal ordinal
                    scan._bind_page(page, root)
                    scan._require(ordinal < len(page_guards)
                                  and receiving._record_guard(page, 16 * _MIB) == page_guards[ordinal],
                                  "successor paired page bytes or ordering changed")
                    ordinal += 1
                current = receiving._completion_walk(completion, index, root, remaining, same_page)
                scan._require(ordinal == len(page_guards) and scan._wire(current) == scan._wire(ledger),
                              "successor paired complete coverage changed")
                _close_native(selection, source_delta, root, chain, before, index, repository, registry,
                              remaining, memory_mb, pins,
                              ((False, inputs[0]), (False, inputs[1]), (False, inputs[2]), (False, delta_guard),
                               *((True, guard) for guard in page_guards)))
                scan._require(receiving._chain_guard(chain, remaining) == chain_guard,
                              "successor paired closing native chain changed")
                guarded()
            succeeded = True
            return completion

        try:
            yield close_current
        except BaseException:
            raise
        else:
            scan._require(succeeded, "successor paired closing gate was not completed")
        finally:
            active = False
            chain = before = before_guard = chain_guard = ledger = page_guards = None
    scan._require(inputs == (receiving._record_guard(selection, successor.MAX_RECORD_BYTES),
                  receiving._record_guard(root, 4 * _MIB), receiving._record_guard(completion, 4 * _MIB))
                  and receiving._record_guard(source_delta, 8 * _MIB) == delta_guard and _pins() == pins,
                  "successor receiving immutable inputs changed during resource closure")


__all__ = []
