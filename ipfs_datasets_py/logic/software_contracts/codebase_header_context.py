"""Bounded header models over immutable captured modules, without a decoder.

Preparation and historical replay establish captured-byte correspondence only.
The selected native catalog head is checked, but the live source tree is not.
A consumer already owning fresh source observations can compose these operations
inside that boundary. Otherwise use ``validate_current_header_context``; no
caller-provided observation token is accepted as current-source authority.
All operations require an explicit reviewed protocol; its absence is rejected.
Even the current wrapper keeps ``current_source_verified=False``: observations
describe this call only and confer no durable source or proof authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path, PurePosixPath
import time

from ...duckdb_control.codebase_catalog import CodebaseHead, CodebaseCatalog
from ..security_ir import code_header_derivation as header
from ..security_ir import doctor_header_contracts as contracts
from .cache import ImmutableCAS
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources, codebase_admission_timeout
from .content import canonical_dag_json_bytes, cid_for_structured

SCHEMA = "codebase-captured-header-context@1"
RECEIPT_SCHEMA = "codebase-captured-header-receipt@1"
CURRENT_SCHEMA = "codebase-current-header-observation@1"
MAX_PATHS = 128
MAX_SOURCE_BYTES = 4 * 1024**2
MAX_REPORT_BYTES = 8 * 1024**2
FALSE = dict(proof_authority=False, execution_authority=False, mutation_authority=False,
    completion_authority=False, source_semantics_verified=False, whole_program_proved=False,
    current_source_verified=False, source_executed=False, training_executed=False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pins():
    from ..security_ir import formalization_adapter, model
    from ..backends.smt import compiler
    from ..ir_core import identity, claims, protocols
    from . import codebase_ir, cache, content
    from ...duckdb_control import codebase_catalog
    modules = (header, contracts, formalization_adapter, model, compiler,
               identity, claims, protocols, codebase_ir, cache, content, codebase_catalog)
    return {"owner": _sha(Path(__file__).read_bytes()),
        "dependencies": {m.__name__: _sha(Path(m.__file__).read_bytes()) for m in modules},
        "header_profile_cid": header.describe_header_semantics_profile()["profile_cid"]}


def _inputs(index, expected_head, paths, protocol):
    _require(type(index) is RepositoryCodebaseIndex and type(index.artifacts) is ImmutableCAS
             and type(index.catalog) is CodebaseCatalog,
             "native repository index, catalog and immutable artifact owner required")
    _require(type(expected_head) is CodebaseHead, "exact captured source head required")
    head = CodebaseHead.from_dict(expected_head.to_dict())
    _require(type(paths) in (tuple, list) and 1 <= len(paths) <= MAX_PATHS,
             "bounded explicit captured path selection required")
    for path in paths:
        _require(type(path) is str and 0 < len(path.encode()) <= 1024
            and PurePosixPath(path).as_posix() == path and not PurePosixPath(path).is_absolute()
            and '..' not in path.split('/') and '\\' not in path
            and not any(ord(c) < 32 for c in path), "canonical repository-relative path required")
    _require(len(set(paths)) == len(paths), "duplicate captured path selection")
    _require(type(protocol) is contracts.WsgiHeaderProtocolContract,
             "explicit reviewed WsgiHeaderProtocolContract required")
    value = asdict(protocol)
    _require(type(value['review_ref']) is str and type(value['callback_parameter']) is str,
             "exact protocol strings required")
    reviewed = contracts.WsgiHeaderProtocolContract(**value)
    return head, sorted(paths), reviewed


@contextmanager
def _operation(*, scheduler, parent_lease, cancel_event, timeout_seconds, memory_mb):
    from ...optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
    started = time.monotonic()
    _require(type(timeout_seconds) in (float, int) and math.isfinite(timeout_seconds)
             and 0 < timeout_seconds <= 300, "bounded positive header operation timeout required")
    _require(type(memory_mb) is int and 256 <= memory_mb <= 4096,
             "explicit bounded header memory reservation required")
    deadline = started + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=codebase_admission_timeout(remaining_seconds=max(0.,deadline-time.monotonic())), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("captured header operation cancelled")
            left = deadline - time.monotonic()
            if left <= 0:
                raise LeaseTimeoutError("captured header operation deadline exceeded")
            return left
        remaining()
        yield lease, signal, remaining
        remaining()


def _derive(index, head, paths, protocol, remaining):
    remaining()
    producer = _pins()
    _require(index.current(head.repository_id) == head, "selected catalog head changed")
    manifest = index.load(head.manifest_cid)
    _require(manifest.snapshot.repository_id == head.repository_id
        and manifest.snapshot.snapshot_cid == head.snapshot_cid
        and manifest.ast_revision_id == head.ast_revision_id, "captured head does not bind manifest")
    entries = {entry.path: entry for entry in manifest.snapshot.entries}
    _require(all(path in entries for path in paths), "selected path is outside captured inventory")
    rows = []
    total = 0
    reader = ImmutableCAS(index.artifacts.root,
        max_object_bytes=min(index.artifacts.max_object_bytes, header.MAX_SOURCE_BYTES))
    for path in paths:
        remaining()
        entry = entries[path]
        row = dict(path=path, entry_cid=entry.entry_cid, source_cid=entry.source_cid,
                   bytes=entry.size_bytes, disposition=None, source_sha256=None, derivation=None)
        rows.append(row)
        if entry.is_opaque:
            row['disposition'] = 'opaque:' + entry.opaque_reason
        elif not path.endswith('.py'):
            row['disposition'] = 'unsupported_language'
        elif not 0 < entry.size_bytes <= header.MAX_SOURCE_BYTES:
            row['disposition'] = 'unsupported_source_size'
        else:
            total += entry.size_bytes
            _require(total <= MAX_SOURCE_BYTES, "complete selected header source exceeds byte budget")
            body = reader.get_bytes(entry.source_cid)
            _require(len(body) == entry.size_bytes, "captured source byte count differs")
            row['source_sha256'] = _sha(body)
            try:
                body.decode('utf-8')
            except UnicodeError:
                row['disposition'] = 'unsupported_source_encoding'
            else:
                # This owner retains unsupported recognizer results. Unexpected
                # derivation, integrity and resource failures are not abstentions.
                row['derivation'] = header.derive_header_semantics(
                    source_bytes=body, source_path=path, protocol=protocol)
                row['disposition'] = row['derivation']['status']
            del body
        remaining()
    reports = [row['derivation'] for row in rows if row['derivation'] is not None]
    result = dict(schema=SCHEMA, source_head=head.to_dict(), paths=paths,
        protocol=asdict(protocol), producer=producer, modules=rows,
        scope='catalog_bound_captured_modules_under_explicit_protocol_premises',
        summary=dict(selected_paths=len(rows), modeled_modules=sum(row['disposition'] == 'modeled' for row in rows),
            unsupported_paths=sum(row['disposition'] != 'modeled' for row in rows),
            modeled_helpers=sum(len(report['modeled_symbols']) for report in reports),
            deterministic_formula_count=sum(report['formula_count'] for report in reports),
            smt_obligation_count=sum(report['smt_obligation_count'] for report in reports)),
        learned_formula_count=0, model_loads=0, provider_calls=0, solver_calls=0, **FALSE)
    _require(len(canonical_dag_json_bytes(result)) <= MAX_REPORT_BYTES, "captured header report exceeds bound")
    _require(producer == _pins(), "header producer changed during derivation")
    _require(index.current(head.repository_id) == head, "selected catalog head changed")
    remaining()
    return result


def _receipt(report, artifact_cid):
    return dict(schema=RECEIPT_SCHEMA, artifact_cid=artifact_cid,
        source_head=deepcopy(report['source_head']), paths=list(report['paths']),
        protocol=deepcopy(report['protocol']), producer=deepcopy(report['producer']),
        summary=deepcopy(report['summary']), learned_formula_count=0,
        model_loads=0, provider_calls=0, solver_calls=0, **FALSE)


def prepare_captured_header_context(index, *, expected_head, paths, protocol,
        scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=90., memory_mb=512):
    """Publish historical captured-module models; does not rescan a live tree."""
    with _operation(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (_, _, remaining):
        head, selected, reviewed = _inputs(index, expected_head, paths, protocol)
        report = _derive(index, head, selected, reviewed, remaining)
        artifact = index.artifacts.put(report)
        _require(artifact == cid_for_structured(report), "header artifact identity differs")
        _require(report['producer'] == _pins(), "header producer changed during publication")
        _require(index.current(head.repository_id) == head, "selected catalog head changed during publication")
        remaining()
        return _receipt(report, artifact)


def _validate(index, head, paths, protocol, receipt, remaining):
    _require(type(receipt) is dict and type(receipt.get('artifact_cid')) is str,
             "closed captured header receipt required")
    # The CAS performs bounded canonical/CID/schema validation. A smaller
    # report bound is also checked before any untrusted report is traversed.
    reader = ImmutableCAS(index.artifacts.root,
        max_object_bytes=min(index.artifacts.max_object_bytes, MAX_REPORT_BYTES))
    saved = reader.get(receipt['artifact_cid'], expected_schema=SCHEMA)
    _require(len(canonical_dag_json_bytes(saved)) <= MAX_REPORT_BYTES, "retained header report exceeds bound")
    remaining()
    actual = _derive(index, head, paths, protocol, remaining)
    _require(canonical_dag_json_bytes(saved) == canonical_dag_json_bytes(actual),
             "captured header source, protocol, producer or derivation differs")
    expected = _receipt(actual, receipt['artifact_cid'])
    _require(canonical_dag_json_bytes(receipt) == canonical_dag_json_bytes(expected),
             "captured header receipt identity or authority differs")
    remaining()
    return expected


def validate_captured_header_context(index, *, expected_head, paths, protocol, receipt,
        scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=90., memory_mb=512):
    """Pure historical replay, suitable inside a caller's fresh source boundary."""
    with _operation(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (_, _, remaining):
        head, selected, reviewed = _inputs(index, expected_head, paths, protocol)
        return _validate(index, head, selected, reviewed, receipt, remaining)


def validate_current_header_context(index, repository, *, expected_head, paths, protocol, receipt,
        scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=90., memory_mb=512):
    """Observe live source around replay without granting lasting currentness."""
    with _operation(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb) as (lease, signal, remaining):
        head, selected, reviewed = _inputs(index, expected_head, paths, protocol)
        def observe():
            index.observe_current(repository, expected_head=head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=remaining(), memory_mb=memory_mb)
            remaining()
        observe()
        checked = _validate(index, head, selected, reviewed, receipt, remaining)
        observe()
        _require(checked['producer'] == _pins(), "header producer changed during current observation")
        return dict(schema=CURRENT_SCHEMA, captured_receipt=checked,
            observation_scope='native_source_head_and_admitted_bytes_at_this_call',
            native_observer_calls=2, **FALSE)
