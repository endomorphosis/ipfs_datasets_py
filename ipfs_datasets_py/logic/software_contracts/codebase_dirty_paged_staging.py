"""Resumable dirty-source extraction on the existing native staging owner.

The initial bounded capture seals all source bytes but parses none. Per-page
AST and local semantic facts remain historical until the complete inventory is
globally resolved and the existing catalog atomically publishes its one head.
Whole-source capture/fences and final graph assembly remain bounded batch work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import time
from types import SimpleNamespace

from . import codebase_dirty_semantics as semantics
from .ast_ir import ASTRecord
from .codebase_ir import CodebaseIRManifest, CodebaseUnit
from .codebase_paged_staging import CodebasePagedStager, _require
from .codebase_resources import acquire_codebase_resources
from .codebase_git_operation import GitScanOperation
from . import codebase_scan_policy as policy_owner
from .content import canonical_dag_json_bytes, cid_for_bytes, validate_cid
from .duckdb_ast_store import classify_parse_status, project_ast_record
from .python_frontend import PythonASTExtractor
from .repository import detect_language
from .semantic_index import snapshot as snapshots

PROFILE = "codebase-dirty-paged-extraction@1"
REQUEST_SCHEMA = "codebase-dirty-paged-request@1"
SHARD_SCHEMA = "codebase-dirty-paged-shard@1"
FALSE = dict(current_head_published=False, global_graph_resolved=False,
    source_semantics_verified=False, proof_authority=False, training_executed=False,
    inference_executed=False, execution_authority=False, completion_authority=False)
MAX_OBJECT_BYTES = 8 * 1024 * 1024
MAX_ANALYSIS_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DirtyStagingLimits:
    max_entries: int = 512
    max_file_bytes: int = 64 * 1024
    max_batch_entries: int = 16

    def __post_init__(self):
        for name, maximum in zip(self.__dataclass_fields__, (512, 64 * 1024, 16)):
            _require(type(getattr(self, name)) is int and 0 < getattr(self, name) <= maximum,
                     "dirty staging limit outside bounded profile: " + name)


def _implementation():
    from . import codebase_paged_staging, codebase_resources, repository, schema_versions
    from .semantic_index import identity, pytest_analysis
    return {**policy_owner._implementation(), **{
        module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (sys.modules[__name__], semantics, codebase_paged_staging,
                       codebase_resources, repository, schema_versions, identity, pytest_analysis)}}


def _runtime():
    return dict(python_version=sys.version, implementation=sys.implementation.name,
                cache_tag=sys.implementation.cache_tag)


def _disposition(entry):
    if entry.is_opaque:
        return "deferred_large_file" if entry.opaque_reason == "oversized" else "opaque_unanalyzed"
    return "captured_ast" if detect_language(entry.path) == "python" else "captured_unindexed"


class CodebaseDirtyPagedStager(CodebasePagedStager):
    """One additive request schema in the existing native staging tables.

    No AST store mutation occurs during prepare/advance. Finalization uses the
    existing CodebaseCatalog source/AST transaction, not a new promotion owner.
    """

    @contextmanager
    def _git_operation(self, root, check, deadline, signal, max_file_bytes):
        def remaining():
            check()
            duration = deadline - time.monotonic()
            if duration <= 0:
                from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseTimeoutError
                raise LeaseTimeoutError("dirty staging Git deadline expired")
            return duration
        with GitScanOperation(root, checkpoint=remaining, cancellation=signal,
                              max_file_bytes=max_file_bytes, memory_mb=512):
            yield remaining

    def _object(self, cid, *, source=False, maximum=MAX_OBJECT_BYTES):
        validate_cid(cid, codecs={"raw" if source else "dag-json"})
        _require(self.artifacts.path_for(cid, source=source).stat().st_size <= maximum,
                 "dirty staging artifact exceeds its read bound")
        return self.artifacts.get_bytes(cid) if source else self.artifacts.get(cid)

    def _put(self, value):
        _require(len(canonical_dag_json_bytes(value)) <= MAX_OBJECT_BYTES,
                 "dirty staging artifact exceeds its write bound")
        return self.artifacts.put(value)

    def _request(self, generation_cid):
        request = self._object(generation_cid)
        _require(type(request) is dict and set(request) == {
            "schema", "profile", "repository", "snapshot_artifact_cid", "snapshot_cid",
            "limits", "external_ignores", "repository_ignore_rules", "implementation", "runtime", *FALSE
        } and request["schema"] == REQUEST_SCHEMA and request["profile"] == PROFILE
            and all(request[k] is False for k in FALSE), "closed dirty staging request required")
        _require(request["implementation"] == _implementation(), "dirty staging producer changed")
        _require(request["runtime"] == _runtime(), "dirty staging parser runtime changed")
        limits = DirtyStagingLimits(**request["limits"])
        snapshot = snapshots.RepositorySnapshot.from_dict(self._object(request["snapshot_artifact_cid"]))
        _require(snapshot.mode in {"git-clean", "git-working"}
            and snapshot.snapshot_cid == request["snapshot_cid"]
            and snapshot.max_entries == limits.max_entries and snapshot.max_file_bytes == limits.max_file_bytes,
            "dirty staging snapshot scope differs")
        root = Path(request["repository"])
        _require(root.is_absolute() and str(root) == request["repository"], "canonical source root required")
        policy_owner._validate_external_scope(self.index, request["external_ignores"])
        rules = sorted(e.path for e in snapshot.entries if PurePosixPath(e.path).name == ".gitignore")
        _require(request["repository_ignore_rules"] == rules and all(
            not e.is_opaque for e in snapshot.entries if e.path in rules), "all ignore rules must be captured")
        return request, snapshot, limits

    def _fence(self, request, snapshot, check):
        check()
        root = Path(request["repository"])
        identities = SimpleNamespace(artifacts=SimpleNamespace(put_bytes=cid_for_bytes))
        scope = SimpleNamespace(exclusions=snapshot.exclusions, max_entries=snapshot.max_entries)
        def rules():
            check()
            _require(policy_owner._external_ignore_scope(identities, root) == request["external_ignores"]
                and policy_owner._repository_rule_paths(root, scope) == request["repository_ignore_rules"],
                "dirty staging ignore scope changed")
        rules()
        current = snapshots.snapshot_repository(root, repository_id=snapshot.repository_id,
            max_entries=snapshot.max_entries, max_file_bytes=snapshot.max_file_bytes, exclusions=snapshot.exclusions)
        _require(current.snapshot_cid == snapshot.snapshot_cid, "dirty source differs from sealed generation")
        rules(); check()
        final = snapshots.snapshot_repository(root, repository_id=snapshot.repository_id,
            max_entries=snapshot.max_entries, max_file_bytes=snapshot.max_file_bytes,
            exclusions=snapshot.exclusions)
        _require(final.snapshot_cid == snapshot.snapshot_cid, "dirty source changed during final scope fence")
        check()

    def prepare(self, repository, *, repository_id, limits=None, exclusions=(),
                scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=120):
        limits = limits or DirtyStagingLimits()
        _require(type(limits) is DirtyStagingLimits, "exact dirty staging limits required")
        _require(type(repository_id) is str and 0 < len(repository_id.encode()) <= 512,
                 "explicit bounded repository identity required")
        exclusions = policy_owner._paths(exclusions, "exclusions")
        root = Path(repository).resolve(strict=True)
        _require(not self.artifacts.root.resolve().is_relative_to(root)
                 and not self.owner._database_path.is_relative_to(root), "native owners must remain outside source")
        with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, memory_mb=512) as lease:
            signal = lease.combined_cancellation_signal(cancel_event)
            deadline = time.monotonic() + timeout_seconds
            check = self._deadline(timeout_seconds, signal)
            with self._git_operation(root, check, deadline, signal, limits.max_file_bytes) as check:
                check()
                _require(snapshots._git_root(root) == root, "one committed Git root required")
                external = policy_owner._external_ignore_scope(self.index, root)
                scope = SimpleNamespace(exclusions=exclusions, max_entries=limits.max_entries)
                rules = policy_owner._repository_rule_paths(root, scope)
                snapshot = snapshots.snapshot_repository(root, repository_id=repository_id,
                    max_entries=limits.max_entries, max_file_bytes=limits.max_file_bytes, exclusions=exclusions)
                _require(snapshot.mode in {"git-clean", "git-working"}, "committed dirty or clean Git scope required")
                check()
                for entry in snapshot.entries:
                    check()
                    if not entry.is_opaque:
                        _require(type(entry.captured_bytes) is bytes and len(entry.captured_bytes) <= limits.max_file_bytes
                            and self.artifacts.put_bytes(entry.captured_bytes) == entry.source_cid, "captured bytes differ")
                request = dict(schema=REQUEST_SCHEMA, profile=PROFILE, repository=str(root),
                    snapshot_artifact_cid=self._put(snapshot.to_dict()), snapshot_cid=snapshot.snapshot_cid,
                    limits=asdict(limits), external_ignores=external, repository_ignore_rules=rules,
                    implementation=_implementation(), runtime=_runtime(), **FALSE)
                generation = self._put(request)
                request, snapshot, _ = self._request(generation)
                self._fence(request, snapshot, check)
                with self.owner.store._lock, self.owner.store._transaction():
                    self._schema()
                    existing = self.cx.execute("SELECT generation_cid FROM codebase_staging_control.generations WHERE generation_cid=?",
                                               [generation]).fetchone()
                    if existing is None:
                        _require(self.cx.execute("SELECT count(*) FROM codebase_staging_control.generations").fetchone()[0] < 128,
                                 "staging generation bound reached")
                        self.cx.execute("INSERT INTO codebase_staging_control.generations VALUES (?,?,0,NULL)",
                                        [generation, generation])
                    check()
                self._fence(request, snapshot, check)
                result = self.status(generation)
                check()
                return result
    def _replay(self, generation_cid):
        self._schema()
        request, snapshot, limits = self._request(generation_cid)
        snapshot_cid = request["snapshot_cid"]  # Independently checked once by _request.
        row = self.cx.execute("SELECT request_cid,cursor,receipt_cid FROM codebase_staging_control.generations WHERE generation_cid=?",
                              [generation_cid]).fetchone()
        _require(row is not None and row[0] == generation_cid and type(row[1]) is int
            and 0 <= row[1] <= len(snapshot.entries), "dirty staging cursor missing or invalid")
        shards = self.cx.execute("SELECT start_ordinal,stop_ordinal,receipt_cid FROM codebase_staging_control.shards WHERE generation_cid=? ORDER BY start_ordinal LIMIT ?",
                                 [generation_cid, limits.max_entries + 1]).fetchall()
        start, previous, total, units, counts = 0, None, 0, [], {}
        for first, stop, cid in shards:
            _require(first == start and first < stop <= min(first + limits.max_batch_entries, len(snapshot.entries)),
                     "dirty shard sequence is incomplete or duplicated")
            receipt = self._object(cid)
            _require(type(receipt) is dict and set(receipt) == {
                "schema", "generation_cid", "snapshot_cid", "start", "stop", "previous_receipt_cid", "units", *FALSE
            } and receipt["schema"] == SHARD_SCHEMA and receipt["generation_cid"] == generation_cid
                and receipt["snapshot_cid"] == snapshot_cid and receipt["start"] == first
                and receipt["stop"] == stop and receipt["previous_receipt_cid"] == previous
                and type(receipt["units"]) is list and len(receipt["units"]) == stop - first
                and all(receipt[k] is False for k in FALSE), "dirty shard receipt binding differs")
            for entry, unit in zip(snapshot.entries[first:stop], receipt["units"]):
                _require(type(unit) is dict and set(unit) == {"source_key", "entry_cid", "source_cid", "ast_cid", "semantic_cid", "disposition"}
                    and unit["source_key"] == entry.source_key and unit["entry_cid"] == entry.entry_cid
                    and unit["source_cid"] == entry.source_cid, "dirty unit is not its sealed inventory entry")
                expected = _disposition(entry)
                _require(unit["disposition"] in {"captured_ast_ok", "captured_ast_partial", "captured_ast_failed"}
                    if expected == "captured_ast" else unit["disposition"] == expected, "dirty unit disposition differs")
                _require((unit["ast_cid"] is not None) == (expected == "captured_ast")
                    and (unit["semantic_cid"] is not None) == (not entry.is_opaque), "dirty unit artifact population differs")
                if not entry.is_opaque:
                    raw = self._object(entry.source_cid, source=True, maximum=limits.max_file_bytes)
                    _require(len(raw) == entry.size_bytes, "dirty source length differs")
                    value = self._object(unit["semantic_cid"])
                    semantics.restore(snapshot, entry, value)
                    total += len(canonical_dag_json_bytes(value))
                if unit["ast_cid"] is not None:
                    total += self.artifacts.path_for(unit["ast_cid"]).stat().st_size
                    _require(total <= MAX_ANALYSIS_BYTES, "complete staged analysis exceeds memory profile")
                    _require(self.artifacts.path_for(unit["ast_cid"]).stat().st_size <= MAX_OBJECT_BYTES,
                             "staged AST exceeds its read bound")
                    # The inherited cache verifies current exact CAS bytes on
                    # every hit and reconstructs the native AST on a miss.
                    # Decoding it again here defeats bounded parsed reuse.
                    binding = self._ast_binding(unit["ast_cid"])
                    _require(binding == (unit["ast_cid"], entry.source_cid, snapshot.repository_id, entry.path,
                        "snapshot:" + snapshot_cid, unit["disposition"].removeprefix("captured_ast_")),
                        "staged AST source/revision/parser binding differs")
                _require(total <= MAX_ANALYSIS_BYTES, "complete staged analysis exceeds memory profile")
                units.append(unit)
                counts[unit["disposition"]] = counts.get(unit["disposition"], 0) + 1
            start, previous = stop, cid
        _require(start == row[1] and previous == row[2], "dirty cursor does not replay from complete shard history")
        state = dict(schema=PROFILE, generation_cid=generation_cid, snapshot_cid=snapshot_cid,
            cursor=start, entry_count=len(snapshot.entries), complete_inventory_staged=start == len(snapshot.entries),
            pending_entries=len(snapshot.entries) - start, disposition_counts=counts,
            deferred_entries=counts.get("deferred_large_file", 0), last_receipt_cid=previous,
            source_observed_live=False, **FALSE)
        return state, request, snapshot, limits, units

    def status(self, generation_cid):
        with self.owner.store._lock:
            return self._replay(generation_cid)[0]

    def advance(self, repository, *, generation_cid, expected_cursor, scheduler=None,
                parent_lease=None, cancel_event=None, timeout_seconds=120):
        _require(type(expected_cursor) is int and expected_cursor >= 0, "exact nonnegative dirty cursor required")
        with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, memory_mb=512) as lease:
            deadline = time.monotonic() + timeout_seconds
            check = self._deadline(timeout_seconds, lease.combined_cancellation_signal(cancel_event))
            with self.owner.store._lock:
                state, request, snapshot, limits, _ = self._replay(generation_cid)
            snapshot_cid = request["snapshot_cid"]
            _require(Path(repository).resolve(strict=True) == Path(request["repository"]), "dirty source root differs")
            signal = lease.combined_cancellation_signal(cancel_event)
            with self._git_operation(Path(request["repository"]), check, deadline, signal,
                                     snapshot.max_file_bytes) as check:
                self._fence(request, snapshot, check)
                _require(expected_cursor <= state["cursor"], "future dirty staging cursor")
                if expected_cursor < state["cursor"]:
                    with self.owner.store._lock:
                        _require(self.cx.execute("SELECT 1 FROM codebase_staging_control.shards WHERE generation_cid=? AND start_ordinal=?",
                            [generation_cid, expected_cursor]).fetchone() is not None, "cursor is not a sealed dirty page boundary")
                    check()
                    return dict(state, replayed=True, source_observed_live=True)
                if state["complete_inventory_staged"]:
                    check()
                    return dict(state, replayed=True, source_observed_live=True)
                stop = min(expected_cursor + limits.max_batch_entries, len(snapshot.entries))
                units = []
                for entry in snapshot.entries[expected_cursor:stop]:
                    check()
                    disposition = _disposition(entry)
                    ast_cid = semantic_cid = None
                    if not entry.is_opaque:
                        raw = self._object(entry.source_cid, source=True, maximum=limits.max_file_bytes)
                        semantic_cid = self._put(semantics.extract(snapshot, entry, raw))
                        if disposition == "captured_ast":
                            ast = PythonASTExtractor().extract_from_source(raw, path=entry.path,
                                repository_id=snapshot.repository_id, revision="snapshot:" + snapshot_cid,
                                repository_tree_cid=snapshot_cid)
                            ast_cid = self._put(ast.to_dict())
                            disposition += "_" + classify_parse_status(ast)
                    units.append(dict(source_key=entry.source_key, entry_cid=entry.entry_cid, source_cid=entry.source_cid,
                        ast_cid=ast_cid, semantic_cid=semantic_cid, disposition=disposition))
                receipt = dict(schema=SHARD_SCHEMA, generation_cid=generation_cid, snapshot_cid=snapshot_cid,
                    start=expected_cursor, stop=stop, previous_receipt_cid=state["last_receipt_cid"], units=units, **FALSE)
                cid = self._put(receipt)
                self._fence(request, snapshot, check)
                with self.owner.store._lock, self.owner.store._transaction():
                    _require(self._replay(generation_cid)[0] == state, "dirty cursor changed during extraction")
                    _require(self.cx.execute("SELECT count(*) FROM codebase_staging_control.shards").fetchone()[0] < 65536,
                             "native staging shard bound reached")
                    self._write_shard(generation_cid, expected_cursor, stop, cid)
                    self._replay(generation_cid)
                    check()
                self._fence(request, snapshot, check)
                result = dict(self.status(generation_cid), replayed=False, source_observed_live=True)
                check()
                return result
    def finalize(self, repository, *, generation_cid, operation_id, expected_head,
                 scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=120):
        """Publish only the complete globally resolved inventory through its owner."""
        with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event, memory_mb=512) as lease:
            deadline = time.monotonic() + timeout_seconds
            check = self._deadline(timeout_seconds, lease.combined_cancellation_signal(cancel_event))
            with self.owner.store._lock:
                state, request, snapshot, _, units = self._replay(generation_cid)
            snapshot_cid = request["snapshot_cid"]
            _require(state["complete_inventory_staged"], "partial dirty inventory cannot publish a head")
            _require(Path(repository).resolve(strict=True) == Path(request["repository"]), "dirty source root differs")
            signal = lease.combined_cancellation_signal(cancel_event)
            with self._git_operation(Path(request["repository"]), check, deadline, signal,
                                     snapshot.max_file_bytes) as check:
                self._fence(request, snapshot, check)
                facts, projections, native_units = {}, [], []
                for entry, unit in zip(snapshot.entries, units):
                    check()
                    ast = None if unit["ast_cid"] is None else ASTRecord.from_dict(self._object(unit["ast_cid"]))
                    if ast is not None:
                        projections.append(project_ast_record(ast, created_at=0))
                    if unit["semantic_cid"] is not None:
                        facts[entry.source_key] = self._object(unit["semantic_cid"])
                    native_units.append(CodebaseUnit(entry.source_key, entry.entry_cid, unit["ast_cid"],
                        "opaque" if entry.is_opaque else "unindexed" if ast is None else classify_parse_status(ast)))
                semantic_state = semantics.assemble(snapshot, facts)
                manifest = CodebaseIRManifest(snapshot, semantic_state,
                    f"rev:{snapshot.repository_id}:snapshot:{snapshot_cid}", tuple(native_units))
                self._put(manifest.to_dict())
                self._fence(request, snapshot, check)
                receipt = self.owner.publish(operation_id=operation_id, expected_head=expected_head,
                    manifest=manifest, projections=projections,
                    checkpoint=check,
                    publication_checkpoint=lambda: self._fence(request, snapshot, check))
                self._fence(request, snapshot, check)
                return receipt

__all__ = ["CodebaseDirtyPagedStager", "DirtyStagingLimits"]
