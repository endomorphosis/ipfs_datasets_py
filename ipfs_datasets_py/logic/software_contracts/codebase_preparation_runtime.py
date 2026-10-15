"""Owned live capture and resumable AST extraction before index publication.

Pages are historical staging artifacts. Callers must retain their root and
page CIDs independently, and admit the preceding page CID separately when
receiving a cursor. Page APIs leave active revisions unchanged. Completion
assembles the whole inventory and publishes one durable catalog operation.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

from . import codebase_preparation as protocol
from . import codebase_preparation_projection as projection_codec
from . import duckdb_ingest as ingestion
from .ast_ir import ASTRecord, SourceProvenance
from .cache import ImmutableCAS
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from .duckdb_ast_store import ASTCatalogProjection
from .semantic_index.snapshot import RepositorySnapshot, snapshot_repository

CONTEXT_SCHEMA = "codebase-preparation-extraction-context@1"
AST_PAYLOAD_SCHEMA = "codebase-preparation-native-ast@1"
MAX_COLLECTED_PROJECTION_BYTES = 32 * 1024 * 1024


class CodebasePreparationRuntimeError(protocol.CodebasePreparationError):
    """Live source, parser context, owner admission or preparation differs."""


class CodebasePreparationCommittedError(CodebasePreparationRuntimeError):
    """Completion committed, but its resource cleanup raised afterward.

    ``receipt`` identifies the durable operation; retrying that operation must
    resolve its historical receipt rather than treating this as rollback.
    """

    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__("catalog operation committed; preparation cleanup failed")


def _require(condition, message):
    if not condition:
        raise CodebasePreparationRuntimeError(message)


def _clock(value):
    _require(type(value) in (int, float), "clock requires an exact native number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise CodebasePreparationRuntimeError("clock must be finite") from exc
    _require(math.isfinite(result), "clock must be finite")
    return result


def _source_identity(module):
    """Hash bounded implementation bytes; no Python-state attestation."""
    path = Path(module.__file__)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns",
                "st_mode", "st_uid", "st_nlink")
        stamp = lambda info: tuple(getattr(info, key) for key in keys)
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= 4 * 1024 * 1024,
                 "bounded ordinary implementation source required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        _require(len(raw) == before.st_size and stamp(before) == stamp(os.fstat(descriptor))
                 == stamp(os.stat(path, follow_symlinks=False)), "implementation source changed")
        return cid_for_bytes(raw)
    finally:
        os.close(descriptor)


class RepositoryCodebasePreparation:
    """Stage roots and AST pages, then publish the complete inventory once.

    Page operations leave the active index unchanged.

    ``optimized_resume`` defaults on. Its explicit False opt-out re-extracts
    completed AST pages and compares them with the admitted saved projections.
    Parser shard caching remains the ingestor's independent policy.

    ``optimized_wrapper_decode`` also defaults on. Within each operation it
    reuses bounded, detached decoded AST wrappers after full byte rereads.
    False retains fresh JSON and canonical CID reconstruction on every use.

    ``optimized_projection_byte_counts`` defaults on. After context callbacks,
    it compares every projection field with the bytes verified by its decoder
    to count bytes without another AST rebuild. False uses the full encoder.
    """

    def __init__(self, *, artifacts, ingestor, catalog=None, optimized_resume=True,
                 optimized_wrapper_decode=True, optimized_projection_byte_counts=True):
        _require(type(artifacts) is ImmutableCAS, "exact immutable filesystem CAS required")
        _require(type(ingestor) is ingestion.DuckDBASTIngestor, "exact AST ingestor required")
        _require(type(optimized_resume) is bool, "optimized_resume must be an exact boolean")
        _require(type(optimized_wrapper_decode) is bool,
                 "optimized_wrapper_decode must be an exact boolean")
        _require(type(optimized_projection_byte_counts) is bool,
                 "optimized_projection_byte_counts must be an exact boolean")
        if catalog is not None:
            from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
            _require(type(catalog) is CodebaseCatalog, "exact durable catalog owner required")
        self.artifacts, self.ingestor, self.catalog = artifacts, ingestor, catalog
        self.optimized_resume = optimized_resume
        self.optimized_wrapper_decode = optimized_wrapper_decode
        self.optimized_projection_byte_counts = optimized_projection_byte_counts

    @contextmanager
    def _operation(self, limits, *, scheduler=None, parent_lease=None, cancel_event=None,
                   timeout_seconds=120.0, admission_timeout_seconds=30.0, memory_mb=1024,
                   commit_state=None):
        from .codebase_resources import acquire_codebase_resources
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            LeaseCancelledError, LeaseTimeoutError,
        )
        _require(type(self.optimized_resume) is bool, "optimized_resume must be an exact boolean")
        _require(type(self.optimized_wrapper_decode) is bool,
                 "optimized_wrapper_decode must be an exact boolean")
        _require(type(self.optimized_projection_byte_counts) is bool,
                 "optimized_projection_byte_counts must be an exact boolean")
        _require(limits is None or type(limits) is protocol.CodebasePreparationLimits,
                 "exact preparation limits required")
        _require(type(memory_mb) is int and memory_mb >= 256, "bounded exact memory reservation required")
        if limits is not None:
            self._check_memory(limits, memory_mb)
        for value, allow_zero in ((timeout_seconds, False), (admission_timeout_seconds, True)):
            _require(type(value) in (int, float) and math.isfinite(value)
                     and (value >= 0 if allow_zero else value > 0), "finite operation deadline required")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(timeout_seconds, admission_timeout_seconds),
            memory_mb=memory_mb, cpu_slots=1, child_process_slots=1,
        ) as lease:
            cancellation = lease.combined_cancellation_signal(cancel_event)

            def checkpoint():
                if cancellation.is_set():
                    raise LeaseCancelledError("live codebase preparation cancelled")
                if time.monotonic() >= deadline:
                    raise LeaseTimeoutError("live codebase preparation deadline exceeded")

            checkpoint()
            yield checkpoint
            if commit_state is None or commit_state["receipt"] is None:
                checkpoint()

    @staticmethod
    def _check_memory(limits, memory_mb):
        _require(limits.max_entries * limits.max_file_bytes * 16 <= memory_mb * 1024 * 1024,
                 "source bounds exceed preparation memory envelope")

    def _outside_repository(self, repository):
        root = self._storage_fence()
        _require(not root.is_relative_to(Path(repository).resolve()),
                 "preparation artifacts must be outside the repository under test")

    def _storage_fence(self):
        root = self.artifacts.root.absolute()
        _require(root.resolve(strict=True) == root, "canonical preparation storage root required")
        for namespace, source in ((self.artifacts.structured_root, False),
                                  (self.artifacts.source_root, True)):
            expected = root / ("source" if source else "structured")
            _require(namespace.absolute() == expected and namespace.resolve(strict=True) == expected,
                     "preparation namespace must be an ordinary directory below storage root")
            probe = cid_for_bytes(b"") if source else cid_for_structured({})
            shard = namespace / probe[:4]
            _require(not shard.is_symlink() and shard.resolve() == expected / probe[:4],
                     "preparation shard must remain below its namespace")
        return root

    def _persist(self, reader, value, *, source=False, maximum):
        raw = value if source else protocol._wire(value, maximum)
        _require(type(raw) is bytes and len(raw) <= maximum
                 and reader.read_bytes + len(raw) <= reader.limits.max_prefix_read_bytes,
                 "artifact publication exceeds operation bound")
        cid = cid_for_bytes(raw) if source else cid_for_structured(value)
        reader.check()
        self._storage_fence()
        self.artifacts._publish(self.artifacts.path_for(cid, source=source), raw)
        self._storage_fence()
        actual, _ = reader.read(cid, source=source, maximum=len(raw))
        _require(actual == value, "published artifact differs")
        reader.check()
        return cid

    def _head_fence(self, repository_id, expected):
        if self.catalog is None:
            _require(expected is None, "expected head requires its durable catalog owner")
            return
        current = self.catalog.current(repository_id)
        observed = current.to_dict() if current is not None else None
        _require(observed == expected, "catalog head changed during preparation")

    def _context(self, snapshot, created_at):
        from . import ast_ir, cache, content, duckdb_ast_store, python_frontend, repository, schema_versions
        from . import codebase_ir
        from .semantic_index import identity, models, python_analysis, pytest_analysis, scanner, symbol_graph
        from ipfs_datasets_py.duckdb_control import codebase_catalog
        from .semantic_index import snapshot as snapshot_module
        inventory = self.ingestor._publication_context_inventory(snapshot)
        _require(inventory is not None, "unqualified frontend cannot receive durable preparation admission")
        modules = (sys.modules[__name__], protocol, projection_codec, ingestion,
                   ast_ir, cache, content, duckdb_ast_store, python_frontend,
                   repository, schema_versions, snapshot_module, codebase_ir,
                   identity, models, python_analysis, pytest_analysis, scanner,
                   symbol_graph, codebase_catalog)
        implementation = {module.__name__: _source_identity(module) for module in modules}
        return {
            "parser_cid": {"schema": CONTEXT_SCHEMA, "kind": "parser",
                           "languages": sorted(self.ingestor._languages), "inventory": inventory},
            "scanner_cid": {"schema": CONTEXT_SCHEMA, "kind": "ast_staging_only",
                            "semantic_assembly": "deferred",
                            "completion_scanner": scanner.SCANNER_NAME,
                            "completion_scanner_version": scanner.SCANNER_VERSION,
                            "completion_manifest_schema": codebase_ir.CODEBASE_IR_SCHEMA},
            "ast_schema_cid": {"schema": CONTEXT_SCHEMA, "kind": "ast_schema",
                               "identifier": ast_ir.AST_IR_SCHEMA_VERSION.identifier},
            "semantic_schema_cid": {"schema": CONTEXT_SCHEMA, "kind": "semantic_schema",
                                    "status": "not_assembled", "identifier": models.SEMANTIC_INDEX_SCHEMA},
            "options_cid": {"schema": CONTEXT_SCHEMA, "kind": "options",
                            "created_at_hex": created_at.hex(),
                            "max_collected_projection_bytes": MAX_COLLECTED_PROJECTION_BYTES},
            "implementation_cid": {"schema": CONTEXT_SCHEMA, "kind": "implementation",
                                   "files": implementation},
        }

    def _read_context(self, root, reader):
        bodies = {}
        for name, cid in root["context"].items():
            value, _ = reader.read(cid)
            bodies[name] = value
        options = bodies["options_cid"]
        protocol._closed(options, {"schema", "kind", "created_at_hex", "max_collected_projection_bytes"},
                         "extraction options")
        _require(options["schema"] == CONTEXT_SCHEMA and options["kind"] == "options"
                 and type(options["max_collected_projection_bytes"]) is int
                 and options["max_collected_projection_bytes"] == MAX_COLLECTED_PROJECTION_BYTES,
                 "preparation options differ")
        protocol._clock(options["created_at_hex"])
        created_at = float.fromhex(options["created_at_hex"])
        snapshot = RepositorySnapshot.from_dict(root["snapshot"])
        current = self._context(snapshot, created_at)
        _require(canonical_dag_json_bytes(current) == canonical_dag_json_bytes(bodies),
                 "preparation extraction context changed")
        return snapshot, created_at, bodies

    def _source_fence(self, repository, snapshot, expected_head, checkpoint):
        checkpoint()
        self._outside_repository(repository)
        self._head_fence(snapshot.repository_id, expected_head)
        observed = snapshot_repository(
            repository, repository_id=snapshot.repository_id, max_entries=snapshot.max_entries,
            max_file_bytes=snapshot.max_file_bytes, exclusions=snapshot.exclusions,
        )
        checkpoint()
        _require(canonical_dag_json_bytes(observed.to_dict()) == canonical_dag_json_bytes(snapshot.to_dict()),
                 "repository source or membership changed during preparation")
        self._head_fence(snapshot.repository_id, expected_head)
        self._outside_repository(repository)

    @staticmethod
    def _admit_cursor(root_cid, cursor, admitted_page_cid):
        if cursor is None:
            cursor = protocol.PreparationCursor(root_cid, 0, None)
        _require(type(cursor) is protocol.PreparationCursor, "exact preparation cursor required")
        cursor = protocol.PreparationCursor.from_dict(cursor.to_dict())
        _require(cursor.root_cid == root_cid, "cursor belongs to another root")
        if cursor.next_offset:
            protocol._cid(admitted_page_cid)
            _require(admitted_page_cid == cursor.previous_page_cid,
                     "cursor does not match independently admitted preceding page")
        else:
            _require(admitted_page_cid is None, "empty prefix cannot receive a page admission")
        return cursor

    def _root(self, root_cid, checkpoint, *, memory_mb=1024):
        _require(type(self.optimized_wrapper_decode) is bool,
                 "optimized_wrapper_decode must be an exact boolean")
        _require(type(self.optimized_projection_byte_counts) is bool,
                 "optimized_projection_byte_counts must be an exact boolean")
        opening = protocol._Reader(self.artifacts, protocol.CodebasePreparationLimits(), checkpoint)
        body, size = opening.read(root_cid)
        root = protocol.PreparationRoot.from_dict(root_cid, body)
        limits = protocol.CodebasePreparationLimits.from_dict(body["limits"])
        self._check_memory(limits, memory_mb)
        spare = memory_mb * 1024 * 1024 - limits.max_entries * limits.max_file_bytes * 16
        # Reserve space for both the retained seed and its detached return.
        cache_bytes = min(protocol.MAX_DECODE_CACHE_BYTES, spare // 4)
        cache_heap = min(protocol.MAX_DECODE_CACHE_HEAP_BYTES, max(0, spare // 2 - cache_bytes))
        reader = protocol._Reader(self.artifacts, limits, checkpoint,
            optimized_decode=self.optimized_wrapper_decode, max_cache_bytes=cache_bytes,
            max_cache_heap_bytes=cache_heap)
        reader.read_bytes = size
        _require(size <= limits.max_prefix_read_bytes, "root exceeds operation budget")
        return root, limits, reader

    def start_current(self, repository, *, repository_id, expected_head=None, limits=None,
                      created_at=None, scheduler=None, parent_lease=None, cancel_event=None,
                      timeout_seconds=120.0, admission_timeout_seconds=30.0, memory_mb=1024):
        """Capture and seal a complete root; no partial head or AST revision."""
        limits = protocol.CodebasePreparationLimits() if limits is None else limits
        protocol._text(repository_id)
        clock = _clock(time.time() if created_at is None else created_at)
        expected = expected_head.to_dict() if expected_head is not None else None
        protocol._head(expected, repository_id)
        with self._operation(limits, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=timeout_seconds,
                admission_timeout_seconds=admission_timeout_seconds, memory_mb=memory_mb) as checkpoint:
            self._head_fence(repository_id, expected)
            self._outside_repository(repository)
            reader = protocol._Reader(self.artifacts, limits, checkpoint)
            snapshot = snapshot_repository(repository, repository_id=repository_id,
                max_entries=limits.max_entries, max_file_bytes=limits.max_file_bytes)
            checkpoint()
            bodies = self._context(snapshot, clock)
            # Source storage is outside the scanned repository. Otherwise CAS
            # writes would change the captured inventory during preparation.
            for entry in snapshot.entries:
                checkpoint()
                if not entry.is_opaque:
                    _require(type(entry.captured_bytes) is bytes,
                             "capture omitted an ordinary source body")
                    _require(self._persist(reader, entry.captured_bytes, source=True,
                             maximum=limits.max_file_bytes) == entry.source_cid,
                             "stored source identity differs")
            context = {}
            for name, body in bodies.items():
                checkpoint()
                protocol._wire(body, limits.max_record_bytes)
                context[name] = self._persist(reader, body, maximum=limits.max_record_bytes)
            self._source_fence(repository, snapshot, expected, checkpoint)
            _require(canonical_dag_json_bytes(self._context(snapshot, clock)) == canonical_dag_json_bytes(bodies),
                     "extraction context changed before root sealing")
            value = {"schema": protocol.ROOT_SCHEMA, "snapshot": snapshot.to_dict(),
                "expected_head": expected, "context": context, "context_cid": cid_for_structured(context),
                "membership_cid": cid_for_structured(snapshot.to_dict()["entries"]),
                "limits": limits.to_dict(), "authority": dict(protocol._AUTHORITY)}
            root = protocol.PreparationRoot.from_dict(cid_for_structured(value), value)
            protocol._captured_sources(reader, root.to_dict())
            protocol._persist_record(reader, root)
            self._source_fence(repository, snapshot, expected, checkpoint)
            _require(self._context(snapshot, clock) == bodies, "extraction context changed before root return")
            return root

    def _verify_projection(self, outcome, entry, root, created_at, reader):
        opaque = entry["opaque_reason"] is not None
        language = ingestion._language_for_path(entry["path"])
        eligible = not opaque and language in self.ingestor._languages and language in self.ingestor._frontends
        _require((outcome["ast_artifact"] is not None) == eligible,
                 "saved AST presence differs from qualified source eligibility")
        _require(outcome["facts_artifact"] is None and outcome["diagnostic_artifact"] is None
                 and outcome["semantic_disposition"] ==
                     ("opaque" if opaque else "deferred_budget" if eligible else "unsupported")
                 and outcome["reason"] ==
                     (entry["opaque_reason"] if opaque else "global_semantic_assembly_pending" if eligible
                      else "no_frontend_for_language:" + language),
                 "saved AST staging disposition differs")
        if outcome["ast_artifact"] is None:
            return None, None
        wrapper, _ = reader.read(outcome["ast_artifact"]["cid"], maximum=reader.limits.max_artifact_bytes)
        payload = wrapper["payload"]
        protocol._closed(payload, {"schema", "projection", "decision", "parser_context"}, "native AST staging")
        _require(payload["schema"] == AST_PAYLOAD_SCHEMA, "unsupported native AST staging payload")
        optimized_byte_counts = self.optimized_projection_byte_counts
        _require(type(optimized_byte_counts) is bool,
                 "optimized_projection_byte_counts must be an exact boolean")
        if optimized_byte_counts:
            projection, verified_raw = projection_codec._decode_preparation_projection_with_raw(payload["projection"])
        else:
            projection = projection_codec.decode_preparation_projection(payload["projection"])
            verified_raw = None
        record = ASTRecord.from_json(projection.ast_blob.payload_json)
        context = ingestion._restart_context(payload["parser_context"])
        context.verify(record, entry["source_cid"])
        expected_context = ingestion._frontend_cache_context(
            self.ingestor._frontends.get(context.language), language=context.language, path=entry["path"])
        _require(context == expected_context, "saved AST parser context differs")
        expected_provenance = SourceProvenance(source_cid=entry["source_cid"], path=entry["path"],
            repository_id=root["snapshot"]["repository_id"],
            revision="snapshot:" + root["snapshot"]["snapshot_cid"],
            repository_tree_cid=root["snapshot"]["snapshot_cid"])
        _require(record.provenance == expected_provenance
                 and projection.ast_cid == record.cid
                 and projection.ast_blob.parse_status == outcome["parse_status"]
                 and projection.ast_blob.created_at.hex() == outcome["created_at_hex"] == created_at.hex(),
                 "saved AST source, provenance, disposition or clock differs")
        decision = payload["decision"]
        fields = set(ingestion.FileIngestDecision("x", "", "", "skipped", "").to_dict())
        protocol._closed(decision, fields, "saved extraction decision")
        _require(decision["path"] == entry["path"] and decision["source_cid"] == entry["source_cid"]
                 and decision["language"] == context.language and decision["git_oid"] == ""
                 and decision["blob_id"] == projection.blob_id and decision["ast_cid"] == projection.ast_cid
                 and type(decision["parse_count"]) is int
                 and decision["action"] in {"parsed", "reused", "parse_failed"}
                 and decision["parse_count"] == (1 if decision["action"] == "parsed" else 0)
                 and decision["detail"] == ("parse_failed" if decision["action"] == "parse_failed" else "")
                 and (decision["action"] == "reused" or
                      (projection.ast_blob.parse_status == "failed") == (decision["action"] == "parse_failed")),
                 "saved extraction decision differs")
        return projection, verified_raw

    def _collect(self, prefix, created_at, reader, *, ast_bytes_limit=None):
        root = prefix.root.to_dict()
        snapshot = RepositorySnapshot.from_dict(root["snapshot"])
        result, total, ast_total = [], 0, 0
        for page in prefix.pages:
            body = page.to_dict()
            for outcome in body["entries"]:
                reader.check()
                entry = root["snapshot"]["entries"][outcome["member_index"]]
                projection, verified_raw = self._verify_projection(outcome, entry, root, created_at, reader)
                if projection is not None:
                    ast_total += len(projection.ast_blob.payload_json.encode("utf-8"))
                    _require(ast_bytes_limit is None or ast_total <= ast_bytes_limit,
                             "complete AST inventory exceeds catalog byte bound")
                    total += (projection_codec._verified_preparation_projection_size(projection, verified_raw)
                              if verified_raw is not None else
                              len(canonical_dag_json_bytes(projection_codec.encode_preparation_projection(projection))))
                    _require(total <= MAX_COLLECTED_PROJECTION_BYTES, "collected projection budget exceeded")
                    verified_raw = None
                    result.append(projection)
            if not self.optimized_resume:
                source_bytes = {entry.source_key: reader.read(entry.source_cid, source=True,
                                maximum=reader.limits.max_file_bytes)[0]
                                for entry in snapshot.entries[body["start"]:body["end"]] if not entry.is_opaque}
                checked = self.ingestor.prepare_snapshot_subset(snapshot, source_bytes,
                    start_index=body["start"], end_index=body["end"], created_at=created_at,
                    checkpoint=reader.check)
                expected = [projection_codec.encode_preparation_projection(member.projection)
                            for member in checked if member.projection is not None]
                actual = [projection_codec.encode_preparation_projection(item)
                          for item in result if item.source_file.path in
                          {entry.path for entry in snapshot.entries[body["start"]:body["end"]]}]
                _require(expected == actual, "reference extraction differs from admitted saved AST page")
        return tuple(result)

    def _validated(self, root_record, cursor, admitted_page_cid, reader, checkpoint, *, repository=None,
                   ast_bytes_limit=None):
        root_cid = root_record.artifact_cid
        cursor = self._admit_cursor(root_cid, cursor, admitted_page_cid)
        prefix, reader = protocol._validate_prefix_with_reader(self.artifacts, root_cid, cursor, checkpoint,
                                                              root=root_record, reader=reader)
        snapshot, created_at, bodies = self._read_context(prefix.root.to_dict(), reader)
        if repository is not None:
            self._source_fence(repository, snapshot, prefix.root.to_dict()["expected_head"], checkpoint)
        projections = self._collect(prefix, created_at, reader, ast_bytes_limit=ast_bytes_limit)
        return prefix, reader, snapshot, created_at, bodies, projections

    def load_projections(self, root_cid, cursor, *, admitted_page_cid, scheduler=None,
                         parent_lease=None, cancel_event=None, timeout_seconds=120.0,
                         admission_timeout_seconds=30.0, memory_mb=1024):
        """Restore an admitted historical prefix; this performs no live capture."""
        with self._operation(None, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=timeout_seconds,
                admission_timeout_seconds=admission_timeout_seconds, memory_mb=memory_mb) as checkpoint:
            root_record, limits, reader = self._root(root_cid, checkpoint, memory_mb=memory_mb)
            self._check_memory(limits, memory_mb)
            prefix, reader, snapshot, clock, bodies, projections = self._validated(
                root_record, cursor, admitted_page_cid, reader, checkpoint)
            _require(self._context(snapshot, clock) == bodies, "extraction context changed before restore return")
            return projections

    def validate_current(self, repository, root_cid, cursor=None, *, admitted_page_cid=None,
                         scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=120.0,
                         admission_timeout_seconds=30.0, memory_mb=1024):
        """Reobserve live source/head and verify an independently admitted prefix."""
        with self._operation(None, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=timeout_seconds,
                admission_timeout_seconds=admission_timeout_seconds, memory_mb=memory_mb) as checkpoint:
            self._outside_repository(repository)
            root_record, limits, reader = self._root(root_cid, checkpoint, memory_mb=memory_mb)
            self._check_memory(limits, memory_mb)
            prefix, reader, snapshot, clock, bodies, projections = self._validated(
                root_record, cursor, admitted_page_cid, reader, checkpoint, repository=repository)
            self._source_fence(repository, snapshot, prefix.root.to_dict()["expected_head"], checkpoint)
            _require(self._context(snapshot, clock) == bodies, "extraction context changed before prefix return")
            return prefix

    def prepare_page(self, repository, root_cid, cursor=None, *, admitted_page_cid=None,
                     scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=120.0,
                     admission_timeout_seconds=30.0, memory_mb=1024):
        """Extract exactly the next page off-store, with entry/closing fences."""
        with self._operation(None, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, timeout_seconds=timeout_seconds,
                admission_timeout_seconds=admission_timeout_seconds, memory_mb=memory_mb) as checkpoint:
            self._outside_repository(repository)
            root_record, limits, reader = self._root(root_cid, checkpoint, memory_mb=memory_mb)
            self._check_memory(limits, memory_mb)
            prefix, reader, snapshot, clock, bodies, previous = self._validated(
                root_record, cursor, admitted_page_cid, reader, checkpoint, repository=repository)
            _require(not prefix.inventory_complete, "preparation inventory already complete")
            expected_head = prefix.root.to_dict()["expected_head"]
            start = prefix.next_offset
            end = min(start + limits.page_entries, len(snapshot.entries))
            sources = {entry.source_key: reader.read(entry.source_cid, source=True,
                        maximum=limits.max_file_bytes)[0]
                       for entry in snapshot.entries[start:end] if not entry.is_opaque}
            prepared = self.ingestor.prepare_snapshot_subset(snapshot, sources,
                start_index=start, end_index=end, created_at=clock, checkpoint=checkpoint)
            root = prefix.root.to_dict()
            outcomes = []
            collected_bytes = sum(len(canonical_dag_json_bytes(projection_codec.encode_preparation_projection(item)))
                                  for item in previous)
            for index, member in enumerate(prepared, start):
                checkpoint()
                entry = root["snapshot"]["entries"][index]
                projection = member.projection
                descriptor = None
                if projection is not None:
                    _require(member.context is not None, "unqualified parser cannot seal a reusable AST page")
                    encoded = projection_codec.encode_preparation_projection(projection)
                    collected_bytes += len(canonical_dag_json_bytes(encoded))
                    _require(collected_bytes <= MAX_COLLECTED_PROJECTION_BYTES,
                             "collected projection budget exceeded before page publication")
                    payload = {"schema": AST_PAYLOAD_SCHEMA,
                        "projection": encoded,
                        "decision": member.decision.to_dict(),
                        "parser_context": ingestion._source_shard_context_payload(member.context)}
                    wrapper = protocol.build_preparation_artifact(entry, root["context_cid"], "ast", payload)
                    raw = protocol._wire(wrapper, limits.max_artifact_bytes)
                    cid = self._persist(reader, wrapper, maximum=limits.max_artifact_bytes)
                    descriptor = {"cid": cid, "bytes": len(raw)}
                opaque = entry["opaque_reason"] is not None
                outcomes.append({"member_index": index, "source_key": member.source_key,
                    "entry_cid": entry["entry_cid"], "source_cid": entry["source_cid"],
                    "parse_status": "opaque" if opaque else "unindexed" if projection is None
                                    else projection.ast_blob.parse_status,
                    "semantic_disposition": "opaque" if opaque else "unsupported" if projection is None
                                            else "deferred_budget",
                    "ast_artifact": descriptor, "facts_artifact": None, "diagnostic_artifact": None,
                    "created_at_hex": None if projection is None else projection.ast_blob.created_at.hex(),
                    "reason": entry["opaque_reason"] if opaque else member.decision.detail if projection is None
                              else "global_semantic_assembly_pending"})
            self._source_fence(repository, snapshot, expected_head, checkpoint)
            _require(self._context(snapshot, clock) == bodies, "extraction context changed before page sealing")
            page = protocol._append_page_to_prefix(prefix, reader, outcomes)
            self._source_fence(repository, snapshot, expected_head, checkpoint)
            _require(self._context(snapshot, clock) == bodies, "extraction context changed before page return")
            return page

    def complete_current(self, repository, root_cid, cursor, *, operation_id,
                         admitted_page_cid, optimized_frontend_reuse=True,
                         scheduler=None, parent_lease=None, cancel_event=None,
                         timeout_seconds=120.0, admission_timeout_seconds=30.0,
                         memory_mb=1024):
        """Assemble the whole admitted inventory and publish one operation.

        Qualified frontend reuse defaults on; semantic Python/pytest syntax
        parsing remains explicit. Exact retries return the catalog's historical
        receipt, even after source or head successors, without currentness or
        proof authority. New operations require live closing observations.
        Cancellation after a returned commit does not turn success into rollback.
        """
        from .codebase_ir import CodebaseIRManifest, CodebaseScanLimits, CodebaseUnit
        from .semantic_index.scanner import RepositoryScanner, _artifact_path
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead, _text

        _require(type(optimized_frontend_reuse) is bool,
                 "optimized_frontend_reuse must be an exact boolean")
        _text(operation_id, "operation_id", 256)
        catalog = self.catalog
        _require(type(catalog) is CodebaseCatalog, "completion requires its exact durable catalog owner")

        def owner_fence():
            _require(self.catalog is catalog and catalog.store is self.ingestor.store
                     and catalog.artifacts is self.artifacts,
                     "completion catalog, AST store and artifact owners must match")

        owner_fence()
        committed = {"receipt": None}
        try:
            with self._operation(None, scheduler=scheduler, parent_lease=parent_lease,
                    cancel_event=cancel_event, timeout_seconds=timeout_seconds,
                    admission_timeout_seconds=admission_timeout_seconds,
                    memory_mb=memory_mb, commit_state=committed) as checkpoint:
                self._outside_repository(repository)
                root_record, limits, reader = self._root(root_cid, checkpoint, memory_mb=memory_mb)
                self._check_memory(limits, memory_mb)
                inventory = RepositorySnapshot.from_dict(root_record.to_dict()["snapshot"])
                _require(len(inventory.entries) <= catalog.limits.max_entries,
                         "complete inventory exceeds catalog entry bound")
                declared_source_bytes = sum(entry.size_bytes for entry in inventory.entries if not entry.is_opaque)
                _require(declared_source_bytes <= catalog.limits.max_source_bytes,
                         "complete source inventory exceeds catalog byte bound")
                # Historical validation permits an already committed operation
                # to resolve before its former expected-head observation.
                prefix, reader, snapshot, clock, bodies, projections = self._validated(
                    root_record, cursor, admitted_page_cid, reader, checkpoint,
                    ast_bytes_limit=catalog.limits.max_ast_bytes)
                _require(prefix.inventory_complete, "completion requires the entire admitted inventory")
                bounds = CodebaseScanLimits(limits.max_entries, limits.max_file_bytes)
                bounds.validate_reservation(memory_mb)
                sources, source_total = {}, 0
                for entry in snapshot.entries:
                    checkpoint()
                    if not entry.is_opaque:
                        raw, _ = reader.read(entry.source_cid, source=True,
                                             maximum=limits.max_file_bytes)
                        source_total += len(raw)
                        _require(source_total <= catalog.limits.max_source_bytes,
                                 "complete source inventory exceeds catalog byte bound")
                        sources[entry.source_key] = raw
                ast_total = sum(len(item.ast_blob.payload_json.encode("utf-8")) for item in projections)
                _require(ast_total <= catalog.limits.max_ast_bytes,
                         "complete AST inventory exceeds catalog byte bound")
                by_path = {item.source_file.path: item for item in projections}
                records, contexts = {}, {}
                for entry in snapshot.entries:
                    if entry.is_opaque or entry.kind != "python" or _artifact_path(entry) != entry.path:
                        continue
                    projection = by_path.get(entry.path)
                    if projection is not None:
                        record = ASTRecord.from_json(projection.ast_blob.payload_json)
                        context = ingestion._frontend_cache_context(
                            self.ingestor._frontends.get("python"), language="python", path=entry.path)
                        _require(context is not None, "qualified completion frontend context required")
                        context.verify(record, entry.source_cid)
                        records[entry.source_key], contexts[entry.source_key] = record, context
                    elif optimized_frontend_reuse:
                        raise CodebasePreparationRuntimeError("complete Python frontend inventory required for reuse")
                # The scanner checks whole-input bindings and recomputes pytest
                # identity unification and graph resolution across every page.
                scanner = RepositoryScanner(repository_id=snapshot.repository_id)
                state = scanner.scan_snapshot(snapshot, sources,
                    prepared_ast_records=(records if optimized_frontend_reuse else None),
                    prepared_ast_contexts=(contexts if optimized_frontend_reuse else None),
                    optimized_frontend_reuse=optimized_frontend_reuse, checkpoint=checkpoint)
                units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid,
                    None if entry.path not in by_path else by_path[entry.path].ast_cid,
                    "opaque" if entry.is_opaque else "unindexed" if entry.path not in by_path
                    else by_path[entry.path].ast_blob.parse_status) for entry in snapshot.entries)
                manifest = CodebaseIRManifest(snapshot, state,
                    f"rev:{snapshot.repository_id}:snapshot:{snapshot.snapshot_cid}", units)
                maximum = min(limits.max_record_bytes, catalog.limits.max_manifest_bytes)
                protocol._wire(manifest.to_dict(), maximum)
                root = root_record.to_dict()
                expected = None if root["expected_head"] is None else CodebaseHead.from_dict(root["expected_head"])
                owner_fence()
                checkpoint()
                _require(self._context(snapshot, clock) == bodies,
                         "completion extraction context changed during assembly")
                request = catalog.request_identity(manifest, expected)
                replay = catalog.resolve_operation(operation_id, request)
                if replay is not None:
                    committed["receipt"] = replay
                    return replay
                self._source_fence(repository, snapshot, root["expected_head"], checkpoint)
                for projection in projections:
                    checkpoint()
                    body = json.loads(projection.ast_blob.payload_json)
                    _require(self._persist(reader, body, maximum=min(limits.max_artifact_bytes,
                             catalog.limits.max_ast_bytes)) == projection.ast_cid,
                             "sealed bare AST identity differs from staged projection")
                _require(self._persist(reader, manifest.to_dict(), maximum=maximum) == manifest.cid,
                         "sealed completion manifest identity differs")
                self._source_fence(repository, snapshot, root["expected_head"], checkpoint)
                _require(self._context(snapshot, clock) == bodies,
                         "completion extraction context changed before publication")
                owner_fence()
                # Inside SQL, this hook checks only cancellation/deadline. A
                # source/head observation would open a nested catalog transaction.
                receipt = catalog.publish(operation_id=operation_id, manifest=manifest,
                    expected_head=expected, projections=projections, checkpoint=checkpoint)
                committed["receipt"] = receipt
                return receipt
        except BaseException as exc:
            if committed["receipt"] is not None:
                raise CodebasePreparationCommittedError(committed["receipt"]) from exc
            raise


__all__ = ["CodebasePreparationRuntimeError", "CodebasePreparationCommittedError",
           "RepositoryCodebasePreparation"]
