"""Resumable bounded structural staging over a sealed committed inventory.

This additive lane never publishes a CodebaseHead. Each staged unit retains
source/AST references and a disposition; completing the inventory does not
establish global graph resolution, inferred contracts or proof eligibility.
The native structural owner supplies its dedicated DuckDB connection and CAS.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time

from .ast_ir import ASTRecord
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
)
from .duckdb_ast_store import classify_parse_status
from .python_frontend import PythonASTExtractor
from .semantic_index import chunked_snapshot as chunks
from .semantic_index.committed_snapshot import _fence, preflight_committed_repository
from .semantic_index.paged_snapshot import (
    parse_chunked_snapshot_manifest,
)
from .semantic_index.snapshot import _malformed_raw
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError,
    LeaseTimeoutError,
)

PARSED_AST_CACHE_BYTES = 32 * 1024 * 1024
PARSED_AST_CACHE_ENTRIES = 512

SCHEMA = "codebase-paged-staging@1"
REQUEST_SCHEMA = "codebase-paged-staging-request@1"
SHARD_SCHEMA = "codebase-paged-staging-shard@1"
FALSE = {
    "current_head_published": False,
    "global_graph_resolved": False,
    "source_semantics_verified": False,
    "proof_authority": False,
    "training_executed": False,
    "inference_executed": False,
    "execution_authority": False,
    "completion_authority": False,
}
_DDL = (
    "CREATE SCHEMA codebase_staging_control",
    "CREATE TABLE codebase_staging_control.generations (generation_cid VARCHAR PRIMARY KEY, request_cid VARCHAR NOT NULL, cursor BIGINT NOT NULL, receipt_cid VARCHAR)",
    "CREATE TABLE codebase_staging_control.shards (generation_cid VARCHAR NOT NULL, start_ordinal BIGINT NOT NULL, stop_ordinal BIGINT NOT NULL, receipt_cid VARCHAR UNIQUE NOT NULL, PRIMARY KEY(generation_cid,start_ordinal))",
)


class CodebaseStagingError(ValueError):
    """Staging identity, state, input or artifact is incomplete or has changed."""


def _require(value, reason):
    if not value:
        raise CodebaseStagingError(reason)


@dataclass(frozen=True, slots=True)
class CodebaseStagingLimits:
    max_entries: int = 2048
    max_stream_bytes: int = 64 * 1024 * 1024
    max_metadata_bytes: int = 8 * 1024 * 1024
    max_file_bytes: int = 64 * 1024
    max_batch_entries: int = 16

    def __post_init__(self):
        for name, ceiling in zip(
            self.__dataclass_fields__,
            (20000, 128 * 1024 * 1024, 16 * 1024 * 1024, 64 * 1024, 32),
        ):
            _require(
                type(getattr(self, name)) is int and 0 < getattr(self, name) <= ceiling,
                "staging limit is outside its bounded profile: " + name,
            )

    def chunk_limits(self):
        return chunks.ChunkedSnapshotLimits(
            max_entries=self.max_entries,
            max_stream_bytes=self.max_stream_bytes,
            max_metadata_bytes=self.max_metadata_bytes,
        )


def _implementation():
    from . import ast_ir, content, duckdb_ast_store, python_frontend
    from .semantic_index import committed_snapshot, paged_snapshot, snapshot

    return {
        module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (
            ast_ir,
            content,
            duckdb_ast_store,
            python_frontend,
            chunks,
            committed_snapshot,
            paged_snapshot,
            snapshot,
        )
    } | {__name__: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _static_disposition(entry, limits):
    if entry.object_type != "blob":
        return "opaque_gitlink"
    if entry.git_mode == "120000":
        return "opaque_symlink"
    if _malformed_raw(bytes.fromhex(entry.raw_path_hex)):
        return "opaque_path"
    if entry.size_bytes > limits.max_file_bytes:
        return "deferred_large_file"
    return "captured_ast" if entry.path.endswith(".py") else "captured_unindexed"


class CodebasePagedStager:
    """Single native owner; workers receive immutable references, never SQL handles."""

    def __init__(self, index: RepositoryCodebaseIndex):
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog

        _require(
            type(index) is RepositoryCodebaseIndex
            and type(index.catalog) is CodebaseCatalog,
            "catalog-owned native codebase index required",
        )
        self.index, self.owner, self.artifacts = index, index.catalog, index.artifacts
        self.cx = self.owner._cx
        self._request_cache = None
        self._ast_cache = OrderedDict()
        self._ast_cache_bytes = 0
        self._cache_stats = {
            "manifest_parses": 0,
            "manifest_hits": 0,
            "ast_parses": 0,
            "ast_hits": 0,
            "ast_evictions": 0,
        }
        with self.owner.store._lock, self.owner.store._transaction():
            self.owner._ensure_owner()
            present = self.cx.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE catalog_name=current_database() AND schema_name='codebase_staging_control'"
            ).fetchall()
            if not present:
                for sql in _DDL:
                    self.cx.execute(sql)
            self._schema()

    def _schema(self):
        self.owner._ensure_owner()
        _require(self.cx is self.owner._cx, "staging owner connection changed")
        rows = self.cx.execute(
            "SELECT table_name, table_type FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema='codebase_staging_control' LIMIT 3"
        ).fetchall()
        _require(
            set(rows) == {("generations", "BASE TABLE"), ("shards", "BASE TABLE")},
            "staging schema differs",
        )
        expected = {
            "generations": [
                ("generation_cid", "VARCHAR"),
                ("request_cid", "VARCHAR"),
                ("cursor", "BIGINT"),
                ("receipt_cid", "VARCHAR"),
            ],
            "shards": [
                ("generation_cid", "VARCHAR"),
                ("start_ordinal", "BIGINT"),
                ("stop_ordinal", "BIGINT"),
                ("receipt_cid", "VARCHAR"),
            ],
        }
        for table, columns in expected.items():
            actual = self.cx.execute(
                "SELECT column_name,data_type FROM information_schema.columns WHERE table_catalog=current_database() AND table_schema='codebase_staging_control' AND table_name=? ORDER BY ordinal_position",
                [table],
            ).fetchall()
            _require(actual == columns, "staging columns differ")
        _require(
            self.cx.execute(
                "SELECT count(*) FROM codebase_staging_control.generations"
            ).fetchone()[0]
            <= 128,
            "staging generation bound exceeded",
        )
        _require(
            self.cx.execute(
                "SELECT count(*) FROM codebase_staging_control.shards"
            ).fetchone()[0]
            <= 65536,
            "staging shard bound exceeded",
        )

    @staticmethod
    def _same_bytes(path, expected):
        # A cache saves decoding, not I/O or artifact integrity checks. Each
        # lookup reads bounded current bytes; even same-size corruption fails.
        with path.open("rb") as stream:
            actual = stream.read(len(expected) + 1)
        _require(actual == expected, "cached artifact bytes changed")

    def replay_cache_stats(self):
        """Diagnostic counters only; no cached pass flag supplies authority."""
        return {
            **self._cache_stats,
            "ast_entries": len(self._ast_cache),
            "ast_bytes": self._ast_cache_bytes,
            "ast_limit_bytes": PARSED_AST_CACHE_BYTES,
            "ast_limit_entries": PARSED_AST_CACHE_ENTRIES,
        }

    def _ast_binding(self, cid):
        cached = self._ast_cache.get(cid)
        if cached is not None:
            path, raw, binding = cached
            self._same_bytes(path, raw)
            self._ast_cache.move_to_end(cid)
            self._cache_stats["ast_hits"] += 1
            return binding
        value = self.artifacts.get(cid)
        ast = ASTRecord.from_dict(value)
        binding = (
            ast.cid,
            ast.provenance.source_cid,
            ast.provenance.repository_id,
            ast.provenance.path,
            ast.provenance.revision,
            classify_parse_status(ast),
        )
        raw = canonical_dag_json_bytes(value)
        path = self.artifacts.path_for(cid)
        self._same_bytes(path, raw)
        self._cache_stats["ast_parses"] += 1
        if len(raw) <= PARSED_AST_CACHE_BYTES:
            while self._ast_cache and (
                len(self._ast_cache) >= PARSED_AST_CACHE_ENTRIES
                or self._ast_cache_bytes + len(raw) > PARSED_AST_CACHE_BYTES
            ):
                _, (_, previous, _) = self._ast_cache.popitem(last=False)
                self._ast_cache_bytes -= len(previous)
                self._cache_stats["ast_evictions"] += 1
            self._ast_cache[cid] = (path, raw, binding)
            self._ast_cache_bytes += len(raw)
        return binding

    def _request(self, generation_cid):
        validate_cid(generation_cid, codecs={"dag-json"})
        cached = self._request_cache
        if cached is not None and cached[0] == generation_cid:
            _, request_raw, snapshot, blocks, limits, reads = cached
            for path, raw in reads:
                self._same_bytes(path, raw)
            request = json.loads(request_raw)
            _require(
                request["implementation"] == _implementation(),
                "staging implementation changed",
            )
            self._cache_stats["manifest_hits"] += 1
            return request, snapshot, dict(blocks), limits
        request = self.artifacts.get(generation_cid)
        _require(
            type(request) is dict
            and set(request)
            == {
                "schema",
                "repository_id",
                "git_commit",
                "git_tree",
                "population_cid",
                "snapshot_cid",
                "blocks",
                "limits",
                "implementation",
                "scope",
                *FALSE,
            },
            "closed staging request required",
        )
        _require(
            request["schema"] == REQUEST_SCHEMA
            and request["scope"] == "complete-committed"
            and all(request[k] is False for k in FALSE),
            "staging request scope differs",
        )
        _require(
            request["implementation"] == _implementation(),
            "staging implementation changed",
        )
        limits = CodebaseStagingLimits(**request["limits"])
        refs = request["blocks"]
        _require(
            type(refs) is list
            and refs == sorted(set(refs))
            and 1 <= len(refs) <= 3 * limits.max_entries + 1,
            "bounded canonical inventory references required",
        )
        blocks = {}
        total = 0
        for cid in refs:
            value = self.artifacts.get(cid)
            raw = canonical_dag_json_bytes(value)
            total += len(raw)
            _require(
                total <= limits.max_metadata_bytes, "inventory metadata exceeds bound"
            )
            blocks[cid] = raw
        snapshot = parse_chunked_snapshot_manifest(
            request["snapshot_cid"],
            blocks,
            repository_id=request["repository_id"],
            expected_commit=request["git_commit"],
            expected_tree=request["git_tree"],
            expected_population_cid=request["population_cid"],
            limits=limits.chunk_limits(),
        )
        request_raw = canonical_dag_json_bytes(request)
        reads = (
            (self.artifacts.path_for(generation_cid), request_raw),
            *((self.artifacts.path_for(cid), raw) for cid, raw in blocks.items()),
        )
        for path, raw in reads:
            self._same_bytes(path, raw)
        # Exactly one bounded generation is retained. Frozen native snapshot
        # records and immutable bytes are reconstructed on every cold reopen.
        self._request_cache = (
            generation_cid,
            request_raw,
            snapshot,
            dict(blocks),
            limits,
            reads,
        )
        self._cache_stats["manifest_parses"] += 1
        return request, snapshot, blocks, limits

    @staticmethod
    def _deadline(seconds, signal):
        _require(
            type(seconds) in {int, float}
            and math.isfinite(seconds)
            and 0 < seconds <= 300,
            "bounded positive execution deadline required",
        )
        end = time.monotonic() + seconds

        def check():
            if signal.is_set():
                raise LeaseCancelledError("codebase staging cancelled")
            if time.monotonic() >= end:
                raise LeaseTimeoutError("codebase staging deadline exceeded")

        return check

    def prepare(
        self,
        repository,
        *,
        repository_id,
        expected_commit,
        expected_tree,
        limits=None,
        scheduler=None,
        parent_lease=None,
        cancel_event=None,
        timeout_seconds=120,
    ):
        limits = limits or CodebaseStagingLimits()
        _require(
            type(limits) is CodebaseStagingLimits, "native staging limits required"
        )
        with acquire_codebase_resources(
            scheduler=scheduler,
            parent_lease=parent_lease,
            cancel_event=cancel_event,
            memory_mb=512,
        ) as lease:
            check = self._deadline(
                timeout_seconds, lease.combined_cancellation_signal(cancel_event)
            )
            check()
            snapshot = chunks.snapshot_chunked_repository(
                repository,
                repository_id=repository_id,
                expected_commit=expected_commit,
                expected_tree=expected_tree,
                limits=limits.chunk_limits(),
            )
            check()
            root, blocks = snapshot.manifest_blocks()
            for cid, raw in blocks.items():
                check()
                _require(
                    self.artifacts.put(json.loads(raw)) == cid,
                    "inventory block changed",
                )
            request = dict(
                schema=REQUEST_SCHEMA,
                repository_id=repository_id,
                git_commit=expected_commit,
                git_tree=expected_tree,
                population_cid=snapshot.population_cid,
                snapshot_cid=root,
                blocks=sorted(blocks),
                limits=asdict(limits),
                implementation=_implementation(),
                scope="complete-committed",
                **FALSE,
            )
            generation = self.artifacts.put(request)
            _fence(
                Path(repository).resolve(strict=True),
                expected_commit,
                expected_tree,
                limits.max_metadata_bytes,
            )
            check()
            with self.owner.store._lock, self.owner.store._transaction():
                self._schema()
                existing = self.cx.execute(
                    "SELECT generation_cid FROM codebase_staging_control.generations WHERE generation_cid=?",
                    [generation],
                ).fetchall()
                if not existing:
                    _require(
                        self.cx.execute(
                            "SELECT count(*) FROM codebase_staging_control.generations"
                        ).fetchone()[0]
                        < 128,
                        "staging generation bound reached",
                    )
                    self.cx.execute(
                        "INSERT INTO codebase_staging_control.generations VALUES (?, ?, 0, NULL)",
                        [generation, generation],
                    )
                check()
            _fence(
                Path(repository).resolve(strict=True),
                expected_commit,
                expected_tree,
                limits.max_metadata_bytes,
            )
            check()
            return self.status(generation)

    def status(self, generation_cid):
        """Replay bounded immutable history; no live scan, fitting or publication."""
        with self.owner.store._lock:
            self._schema()
            request, snapshot, _, limits = self._request(generation_cid)
            states = self.cx.execute(
                "SELECT request_cid,cursor,receipt_cid FROM codebase_staging_control.generations WHERE generation_cid=?",
                [generation_cid],
            ).fetchall()
            _require(
                len(states) == 1 and states[0][0] == generation_cid,
                "staging generation missing or substituted",
            )
            _, cursor, tail = states[0]
            _require(
                type(cursor) is int and 0 <= cursor <= len(snapshot.entries),
                "invalid staging cursor",
            )
            shards = self.cx.execute(
                "SELECT start_ordinal,stop_ordinal,receipt_cid FROM codebase_staging_control.shards WHERE generation_cid=? ORDER BY start_ordinal LIMIT ?",
                [generation_cid, limits.max_entries + 1],
            ).fetchall()
            start, previous, counts = 0, None, {}
            blobs = {item.git_object_oid: item for item in snapshot.blobs}
            for first, stop, receipt_cid in shards:
                _require(
                    first == start
                    and first
                    < stop
                    <= min(first + limits.max_batch_entries, len(snapshot.entries)),
                    "staging shard sequence differs",
                )
                receipt = self.artifacts.get(receipt_cid)
                _require(
                    type(receipt) is dict
                    and set(receipt)
                    == {
                        "schema",
                        "generation_cid",
                        "snapshot_cid",
                        "start",
                        "stop",
                        "previous_receipt_cid",
                        "units",
                        *FALSE,
                    },
                    "closed shard receipt required",
                )
                _require(
                    receipt["schema"] == SHARD_SCHEMA
                    and receipt["generation_cid"] == generation_cid
                    and receipt["snapshot_cid"] == request["snapshot_cid"]
                    and receipt["start"] == first
                    and receipt["stop"] == stop
                    and receipt["previous_receipt_cid"] == previous
                    and len(receipt["units"]) == stop - first
                    and all(receipt[k] is False for k in FALSE),
                    "staging receipt binding differs",
                )
                for entry, unit in zip(snapshot.entries[first:stop], receipt["units"]):
                    _require(
                        set(unit) == {"entry", "disposition", "source_cid", "ast_cid"}
                        and unit["entry"] == entry.to_dict(),
                        "staged unit differs from complete inventory",
                    )
                    disposition = unit["disposition"]
                    expected = _static_disposition(entry, limits)
                    _require(
                        type(disposition) is str
                        and (
                            disposition
                            in {
                                "captured_ast_ok",
                                "captured_ast_partial",
                                "captured_ast_failed",
                            }
                            if expected == "captured_ast"
                            else disposition == expected
                        ),
                        "staged disposition differs",
                    )
                    _require(
                        (unit["source_cid"] is not None)
                        == expected.startswith("captured_")
                        and (unit["ast_cid"] is not None)
                        == (expected == "captured_ast"),
                        "staged disposition lacks its exact source or AST artifact",
                    )
                    if unit["source_cid"] is not None:
                        raw = self.artifacts.get_bytes(unit["source_cid"])
                        claim = blobs[entry.git_object_oid]
                        _require(
                            claim.source_cid == unit["source_cid"]
                            and len(raw) == entry.size_bytes,
                            "staged source binding differs",
                        )
                    if unit["ast_cid"] is not None:
                        binding = self._ast_binding(unit["ast_cid"])
                        _require(
                            binding
                            == (
                                unit["ast_cid"],
                                unit["source_cid"],
                                request["repository_id"],
                                entry.path,
                                "snapshot:" + request["snapshot_cid"],
                                disposition.removeprefix("captured_ast_"),
                            ),
                            "staged AST binding differs",
                        )
                    counts[disposition] = counts.get(disposition, 0) + 1
                start, previous = stop, receipt_cid
            _require(
                start == cursor and previous == tail,
                "staging cursor differs from sealed history",
            )
            return dict(
                schema=SCHEMA,
                generation_cid=generation_cid,
                snapshot_cid=request["snapshot_cid"],
                population_cid=snapshot.population_cid,
                cursor=cursor,
                entry_count=len(snapshot.entries),
                complete_inventory_staged=cursor == len(snapshot.entries),
                pending_entries=len(snapshot.entries) - cursor,
                deferred_entries=counts.get("deferred_large_file", 0),
                disposition_counts=counts,
                last_receipt_cid=tail,
                source_observed_live=False,
                **FALSE,
            )

    def _write_shard(self, generation_cid, start, stop, receipt_cid):
        self.cx.execute(
            "INSERT INTO codebase_staging_control.shards VALUES (?,?,?,?)",
            [generation_cid, start, stop, receipt_cid],
        )
        self.cx.execute(
            "UPDATE codebase_staging_control.generations SET cursor=?,receipt_cid=? WHERE generation_cid=?",
            [stop, receipt_cid, generation_cid],
        )

    def advance(
        self,
        repository,
        *,
        generation_cid,
        expected_cursor,
        scheduler=None,
        parent_lease=None,
        cancel_event=None,
        timeout_seconds=120,
    ):
        """One bounded deterministic shard; exact old cursor retries are read-only."""
        _require(
            type(expected_cursor) is int and expected_cursor >= 0,
            "exact nonnegative cursor required",
        )
        with acquire_codebase_resources(
            scheduler=scheduler,
            parent_lease=parent_lease,
            cancel_event=cancel_event,
            memory_mb=512,
        ) as lease:
            check = self._deadline(
                timeout_seconds, lease.combined_cancellation_signal(cancel_event)
            )
            check()
            state = self.status(generation_cid)
            request, snapshot, blocks, limits = self._request(generation_cid)
            root = Path(repository).resolve(strict=True)
            # _request already replays the closed metadata DAG, including exact
            # byte checks on a parsed-cache hit. Recheck the live population
            # without redundantly parsing that same immutable DAG a second time.
            plan = preflight_committed_repository(
                root,
                repository_id=request["repository_id"],
                expected_commit=request["git_commit"],
                expected_tree=request["git_tree"],
                max_entries=limits.max_entries,
                max_metadata_bytes=limits.max_metadata_bytes,
            )
            _require(
                plan.population_cid == snapshot.population_cid
                and plan.entries == snapshot.entries,
                "staging inventory differs from current committed population",
            )
            _require(expected_cursor <= state["cursor"], "future staging cursor")
            if expected_cursor < state["cursor"]:
                with self.owner.store._lock:
                    _require(
                        bool(
                            self.cx.execute(
                                "SELECT receipt_cid FROM codebase_staging_control.shards WHERE generation_cid=? AND start_ordinal=?",
                                [generation_cid, expected_cursor],
                            ).fetchall()
                        ),
                        "cursor is not a sealed shard boundary",
                    )
                check()
                return dict(state, source_observed_live=True, replayed=True)
            if state["complete_inventory_staged"]:
                check()
                return dict(state, source_observed_live=True, replayed=True)
            stop = min(
                expected_cursor + limits.max_batch_entries, len(snapshot.entries)
            )
            units = []
            blobs = {blob.git_object_oid: blob for blob in snapshot.blobs}
            frontend = PythonASTExtractor(max_source_bytes=limits.max_file_bytes)
            for entry in snapshot.entries[expected_cursor:stop]:
                check()
                source_cid = ast_cid = None
                disposition = _static_disposition(entry, limits)
                if disposition.startswith("captured_"):
                    claim, raw = chunks._hash_blob(
                        root,
                        entry.git_object_oid,
                        entry.size_bytes,
                        snapshot.limits.frame_bytes,
                        capture=True,
                    )
                    _require(
                        claim == blobs[entry.git_object_oid] and raw is not None,
                        "captured blob differs from sealed inventory",
                    )
                    source_cid = self.artifacts.put_bytes(raw)
                    disposition = "captured_unindexed"
                    if entry.path.endswith(".py"):
                        ast = frontend.extract_from_source(
                            raw,
                            path=entry.path,
                            repository_id=request["repository_id"],
                            revision="snapshot:" + request["snapshot_cid"],
                            repository_tree_cid=request["snapshot_cid"],
                        )
                        ast_cid = self.artifacts.put(ast.to_dict())
                        disposition = "captured_ast_" + classify_parse_status(ast)
                units.append(
                    dict(
                        entry=entry.to_dict(),
                        disposition=disposition,
                        source_cid=source_cid,
                        ast_cid=ast_cid,
                    )
                )
            receipt = dict(
                schema=SHARD_SCHEMA,
                generation_cid=generation_cid,
                snapshot_cid=request["snapshot_cid"],
                start=expected_cursor,
                stop=stop,
                previous_receipt_cid=state["last_receipt_cid"],
                units=units,
                **FALSE,
            )
            receipt_cid = self.artifacts.put(receipt)
            _fence(
                root,
                request["git_commit"],
                request["git_tree"],
                limits.max_metadata_bytes,
            )
            check()
            with self.owner.store._lock, self.owner.store._transaction():
                self._schema()
                current = self.status(generation_cid)
                _require(
                    current == state, "staging cursor changed during shard preparation"
                )
                _require(
                    self.cx.execute(
                        "SELECT count(*) FROM codebase_staging_control.shards"
                    ).fetchone()[0]
                    < 65536,
                    "staging shard bound reached",
                )
                self._write_shard(generation_cid, expected_cursor, stop, receipt_cid)
                check()
            _fence(
                root,
                request["git_commit"],
                request["git_tree"],
                limits.max_metadata_bytes,
            )
            check()
            return dict(
                self.status(generation_cid), source_observed_live=True, replayed=False
            )


__all__ = ["CodebasePagedStager", "CodebaseStagingLimits", "CodebaseStagingError"]
