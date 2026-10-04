"""Private paired receiving for one admitted completed-scan operation.

Entry performs the ordinary full native target and completion replay. Closing
streams the bound CAS pages again and repeats every native source/model fence,
without reconstructing the same page targets. Only length/SHA/CID and bounded
structural metadata are retained; no page-body cache or public freshness token
exists. Numerical bytes remain advisory. These are sequential observations,
not an atomic filesystem/database snapshot or execution attestation.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import threading

from . import codebase_inventory_resume as scan
from . import codebase_source_training as training
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope

_MIB = 1024 * 1024
_MAX_METADATA_BYTES = 4 * _MIB


def _bytes_guard(raw, maximum):
    scan._require(type(raw) is bytes and len(raw) <= maximum, "bounded immutable receiving bytes required")
    return len(raw), hashlib.sha256(raw).hexdigest()


def _record_guard(record, maximum):
    return record.artifact_cid, *_bytes_guard(record._payload, maximum)


def _chain_guard(chain, remaining):
    """Hash complete canonical native snapshots; retain no duplicate bodies."""
    limits = training.CodebaseFeatureTrainingLimits()
    scan._require(type(chain) is list and 1 <= len(chain) <= limits.max_ancestry, "bounded native receiving ancestry required")
    guards, ancestry_bytes = [], 0
    for item in chain:
        remaining()
        scan._require(type(item) is tuple and len(item) == 7, "exact native receiving chain row required")
        row, saved, provenance, *batches = item
        scan._require(type(row) is dict and type(saved) is dict and type(provenance) is dict,
                      "native receiving candidate snapshots required")
        row_guard = _bytes_guard(training._wire(row), _MIB)
        saved_raw = training._wire(saved)
        saved_guard = _bytes_guard(saved_raw, limits.max_candidate_bytes)
        ancestry_bytes += len(saved_raw)
        scan._require(ancestry_bytes <= limits.max_ancestry_bytes, "receiving ancestry bytes exceed bound")
        del saved_raw
        provenance_guard = _bytes_guard(training._wire(provenance), limits.max_candidate_bytes)
        targets = []
        for batch in batches:
            scan._require(type(batch) is list and 1 <= len(batch) <= limits.max_targets,
                          "bounded native receiving target batch required")
            target_guards, batch_bytes = [], 0
            for target in batch:
                remaining()
                scan._require(type(target) is DomainTargetEnvelope, "exact validated native receiving target required")
                target_guard = _bytes_guard(target.canonical_bytes, limits.max_target_bytes)
                batch_bytes += target_guard[0]
                scan._require(batch_bytes <= limits.max_target_bytes, "receiving target batch bytes exceed bound")
                target_guards.append(target_guard)
            targets.append(tuple(target_guards))
        guards.append((row_guard, saved_guard, provenance_guard, tuple(targets)))
    scan._require(len(scan._wire(guards)) <= _MAX_METADATA_BYTES, "receiving chain guard metadata bound exceeded")
    return tuple(guards)


def _inode_guard(path, *, directory=False):
    value = Path(path).lstat()
    scan._require(stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode),
                  "paired receiving native owner path must retain its regular type")
    return value.st_dev, value.st_ino


def _owner_guard(index, registry, repository):
    """Fixed native object/path ownership, followed by native checks at close."""
    store = index.ingestor.store
    database = _inode_guard(registry.database_path)
    artifacts = _inode_guard(registry.artifact_root, directory=True)
    lock_path = registry.database_path.with_name(registry.database_path.name + ".owner.lock")
    lock = _inode_guard(lock_path)
    descriptor = os.fstat(registry._owner_file.fileno())
    scan._require(stat.S_ISREG(descriptor.st_mode) and lock == (descriptor.st_dev, descriptor.st_ino),
                  "paired receiving native model lock ownership differs")
    # Inodes bind the live native owner only. They never replace fresh SQL,
    # registry generation, artifact hashes, source or target verification.
    return (id(index), id(index.ingestor), id(index.catalog), id(store), id(store._connection), id(store._lock),
            id(index.artifacts), id(registry), id(registry._manager), id(registry._lock), id(registry._owner_file),
            (type(index.catalog._pid), index.catalog._pid), (type(registry._pid), registry._pid),
            (type(registry.owner_generation), registry.owner_generation), (type(registry._closed), registry._closed),
            str(index.artifacts.root), str(index.catalog._database_path),
            str(registry.database_path), str(registry.artifact_root), str(Path(repository).absolute()),
            database, artifacts, lock)


def _completion_walk(completion, index, root, remaining, check_page):
    scan._require(scan.load_codebase_scan_resume_completion(index.artifacts, completion.artifact_cid)._payload
                  == completion._payload, "durable paired completion bytes differ")
    c = completion.to_dict()
    scan._bind_completion(c, root)
    tail = c["pages"][-1]["page_cid"] if c["pages"] else None
    descriptors, offset, inferred, counts = scan._walk(index.artifacts, root, tail, remaining, check_page)
    expected = scan._completion_value(root, descriptors, offset, inferred, counts)
    scan._require(scan.canonical_dag_json_bytes(c) == scan.canonical_dag_json_bytes(expected),
                  "paired native completion ledger differs")
    return tuple(descriptors), offset, inferred, counts


@contextmanager
def _paired_current_codebase_scan_completion(completion, index, repository, *, root, registry,
        scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    """Yield one closing gate; normal exit requires that gate to succeed.

    A caller closes after its final owner callbacks, before transaction commit
    or native Popen. The closer is consumed once, invalid after manager exit,
    and never serialized, signed or accepted as an input to another operation.
    Cleanup performs no native replay after a process launch/source edit.
    The opt-out uses the original public validator at both observations.
    """
    scan._require(type(root) is scan.CodebaseScanResumeRoot
                  and type(completion) is scan.CodebaseScanResumeCompletion,
                  "exact native paired root and completion required")
    with scan._scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (lease, signal, remaining):
        # The ordinary scanner's 224 MiB phased serialized estimate plus
        # three <=4 MiB metadata ledgers remains below a quarter reservation.
        # This estimate bounds serialized retention, not Python/native RSS.
        scan._require(236 * _MIB <= memory_mb * _MIB // 4,
                      "paired serialized retention exceeds memory reservation")
        pid, thread = os.getpid(), threading.get_ident()
        root_guard = _record_guard(root, 4 * _MIB)
        completion_guard = _record_guard(completion, 4 * _MIB)
        owners = _owner_guard(index, registry, repository)
        optimized = root.to_dict()["optimized"]
        active, used, succeeded = True, False, False
        chain = before = before_guard = chain_guard = ledger = page_guards = None

        def inputs_current():
            remaining()
            scan._require(os.getpid() == pid and threading.get_ident() == thread and not lease.released,
                          "paired receiving native operation ownership expired")
            scan._require(_record_guard(root, 4 * _MIB) == root_guard
                          and _record_guard(completion, 4 * _MIB) == completion_guard,
                          "paired receiving input bytes changed")
            scan._require(_owner_guard(index, registry, repository) == owners,
                          "paired receiving native owners changed")
            if before_guard is not None:
                scan._require(_bytes_guard(before, 8 * _MIB) == before_guard,
                              "paired receiving registry baseline changed")

        def reference():
            inputs_current()
            actual = scan.validate_current_codebase_scan_completion(completion, index, repository,
                root=root, registry=registry, parent_lease=lease, cancel_event=signal,
                admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
                timeout_seconds=remaining(), memory_mb=memory_mb)
            scan._require(actual is completion, "paired reference selected another completion")
            inputs_current()

        if not optimized:
            reference()
        else:
            manifest, receipt, chain, before = scan._entry(index, repository, root, registry, remaining, memory_mb)
            before_guard = _bytes_guard(before, 8 * _MIB)
            page_guards = []
            def full_page(page, inferred):
                scan._replay_page(index, root, manifest, receipt, chain, page, inferred, remaining)
                page_guards.append(_record_guard(page, 16 * _MIB))
                scan._require(len(page_guards) <= 1024
                              and len(scan._wire(page_guards)) <= _MAX_METADATA_BYTES,
                              "paired page guard metadata exceeds bound")
            ledger = _completion_walk(completion, index, root, remaining, full_page)
            page_guards = tuple(page_guards)
            scan._require(len(scan._wire(ledger)) <= _MAX_METADATA_BYTES, "paired completion metadata exceeds bound")
            del manifest, receipt
            chain_guard = _chain_guard(chain, remaining)
            scan._close(index, repository, root, registry, chain, before, remaining, memory_mb)
            scan._require(_chain_guard(chain, remaining) == chain_guard,
                          "paired entry native chain changed during closing callbacks")
            inputs_current()

        def close_current():
            nonlocal used, succeeded
            scan._require(active and not used, "paired receiving closing gate is inactive or already used")
            used = True
            inputs_current()
            if not optimized:
                reference()
            else:
                scan._require(_chain_guard(chain, remaining) == chain_guard,
                              "paired receiving native chain changed")
                scan._require(scan.load_codebase_scan_resume_root(index.artifacts, root.artifact_cid)._payload
                              == root._payload, "durable paired root bytes differ")
                ordinal = 0
                def same_page(page, inferred):
                    nonlocal ordinal
                    scan._bind_page(page, root)
                    scan._require(ordinal < len(page_guards)
                                  and _record_guard(page, 16 * _MIB) == page_guards[ordinal],
                                  "paired receiving page bytes/order changed")
                    ordinal += 1
                current_ledger = _completion_walk(completion, index, root, remaining, same_page)
                scan._require(ordinal == len(page_guards)
                              and scan._wire(current_ledger) == scan._wire(ledger),
                              "paired receiving completion coverage changed")
                scan._close(index, repository, root, registry, chain, before, remaining, memory_mb)
                scan._require(_chain_guard(chain, remaining) == chain_guard,
                              "paired receiving native chain changed during closing callbacks")
                inputs_current()
            succeeded = True
            return completion

        try:
            yield close_current
        except BaseException:
            raise
        else:
            scan._require(succeeded, "paired receiving closing gate was not completed")
        finally:
            active = False
            # No replay on manager cleanup: launch/publication may follow the
            # consumed gate while an independent execution scope owns Popen.
            chain = before = before_guard = chain_guard = ledger = page_guards = None
