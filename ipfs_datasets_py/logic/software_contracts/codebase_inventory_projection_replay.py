"""Bounded operation-local native AST projection replay for inventory scans.

Each fresh batch independently reads every relational row used by the native
DuckDBASTStore._load and calls that owner's canonical _rebuild. This is SQL
transport reuse, not a projection cache or a source/model trust token. Complete
CAS and live checkout observations remain with the scanner. Aggregate row and
serialized-byte preflight happens in the same native transaction before body
fetches; oversized batches split, oversized individual projections fail closed.
Bounds cover serialized transport, not Python or DuckDB RSS. Head observations
before and after batches are sequential, not an atomic repository snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from .cache import ImmutableCAS
from .codebase_ir import CodebaseIRManifest, RepositoryCodebaseIndex, StaleCodebaseError
from .duckdb_ast_store import (
    ASTS_CATALOG_DDL, ASTS_CATALOG_TABLES, DuckDBASTStore, DuckDBASTStoreIntegrityError,
    ParseStatus, MAX_QUERY_ROWS, _json_dumps, _row_id,
)

SCHEMA = "codebase-native-inventory-projection-replay@1"
_MIB = 1024 * 1024
_RELATIONS = (("ast_nodes", "nodes"), ("scopes", "scopes"), ("symbols", "symbols"),
              ("imports", "imports"), ("references", "references"), ("calls", "calls"),
              ("effects", "effects"), ("interfaces", "interfaces"),
              ("diagnostics", "diagnostics"), ("invalidations", "invalidations"))
_COLUMNS = {match.group(1): tuple((column.group(1), column.group(2))
    for column in re.finditer(r'^\s*([a-z_]+)\s+(VARCHAR|DOUBLE|BOOLEAN|BIGINT|INTEGER)\b', match.group(2), re.M))
    for match in re.finditer(r'CREATE TABLE IF NOT EXISTS "?([a-z_]+)"?\s*\((.*?)\);', ASTS_CATALOG_DDL, re.S)}


class CodebaseProjectionReplayError(DuckDBASTStoreIntegrityError):
    """A bounded current projection, native row replay or ownership check failed."""


def _require(value, message):
    if not value:
        raise CodebaseProjectionReplayError(message)


@dataclass(frozen=True, slots=True)
class CodebaseProjectionReplayLimits:
    max_blobs: int = 16
    max_rows: int = 100_000
    max_serialized_bytes: int = 32 * _MIB

    def __post_init__(self):
        for name, maximum in zip(self.__dataclass_fields__, (16, MAX_QUERY_ROWS, 32 * _MIB)):
            value = getattr(self, name)
            _require(type(value) is int and 0 < value <= maximum, "bounded exact projection replay limit required")

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ProjectionReplayReceipt:
    selected_blobs: int
    replayed_blobs: int
    batches: int
    preflights: int
    metadata_queries: int
    schema_queries: int
    body_queries: int
    fetched_rows: int
    serialized_bytes: int
    largest_batch_rows: int
    largest_batch_bytes: int

    def __post_init__(self):
        for field in self.__dataclass_fields__:
            _require(type(getattr(self, field)) is int and getattr(self, field) >= 0,
                     "exact nonnegative native replay counter required")
        _require(self.selected_blobs == self.replayed_blobs <= 1024
                 and self.body_queries == self.batches * len(ASTS_CATALOG_TABLES)
                 and self.schema_queries == 2 * self.preflights
                 and self.metadata_queries == 2 * self.preflights,
                 "complete native projection replay accounting required")

    def to_dict(self):
        return {"schema": SCHEMA, **{name: getattr(self, name) for name in self.__dataclass_fields__},
            "counter_scope": "batch_lookup_schema_preflights_and_body_reads_excludes_native_owner_head_queries",
            "proof_authority": False, "source_execution_attested": False}


def _owners(index):
    import duckdb
    _require(type(index) is RepositoryCodebaseIndex and type(index.catalog) is CodebaseCatalog
             and type(index.ingestor.store) is DuckDBASTStore and type(index.artifacts) is ImmutableCAS
             and index.catalog.store is index.ingestor.store and index.catalog.artifacts is index.artifacts
             and type(index.ingestor.store._connection) is duckdb.DuckDBPyConnection,
             "exact native structural SQL/store/CAS owner required")
    index.catalog._ensure_owner()
    return index.ingestor.store


def _inside_head(index, head):
    if index.catalog._current(head.repository_id) != head:
        raise StaleCodebaseError("projection replay catalog head changed")


def _outside_head(index, head):
    if index.current(head.repository_id) != head:
        raise StaleCodebaseError("projection replay catalog head changed between native batches")


def _in(column, values):
    return ("FALSE", []) if not values else (column + " IN (" + ",".join("?" for _ in values) + ")", list(values))


def _predicates(metadata):
    blobs = [row["blob_id"] for row in metadata]
    result = {"ast_blobs": _in("blob_id", blobs),
              "source_revisions": _in("revision_id", sorted({row["revision_id"] for row in metadata})),
              "source_files": _in("file_id", sorted({row["file_id"] for row in metadata}))}
    for table, _ in _RELATIONS:
        result[table] = _in("blob_id", blobs)
    result["invalidations"] = _in("invalidation_id", [
        _row_id(row["blob_id"], "invalidation", "parse_failure")
        for row in metadata if row["parse_status"] == ParseStatus.FAILED.value])
    return result


def _schema(connection):
    placeholders = ",".join("?" for _ in ASTS_CATALOG_TABLES)
    tables = connection.execute("SELECT table_name,table_type FROM information_schema.tables WHERE "
        "table_catalog=current_database() AND table_schema=current_schema() AND table_name IN ("
        + placeholders + ") ORDER BY table_name LIMIT 14", list(ASTS_CATALOG_TABLES)).fetchall()
    _require(tables == [(name, "BASE TABLE") for name in sorted(ASTS_CATALOG_TABLES)],
             "complete exact native projection table family required")
    rows = connection.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE "
        "table_catalog=current_database() AND table_schema=current_schema() AND table_name IN ("
        + placeholders + ") ORDER BY table_name,ordinal_position LIMIT 512", list(ASTS_CATALOG_TABLES)).fetchall()
    _require(set(_COLUMNS) == set(ASTS_CATALOG_TABLES)
             and rows == [(name, column, kind) for name in sorted(_COLUMNS) for column, kind in _COLUMNS[name]],
             "native projection columns differ from owning DDL")


def _metadata(connection, ast_cids, counters, checkpoint):
    where, arguments = _in("ast_cid", ast_cids)
    checkpoint()
    counters["metadata_queries"] += 1
    count, charge = connection.execute(
        'SELECT count(*),coalesce(sum(bit_length(blob_id)//8+bit_length(ast_cid)//8+'
        'bit_length(file_id)//8+bit_length(revision_id)//8+'
        'bit_length(parse_status)//8),0) FROM ast_blobs WHERE ' + where, arguments).fetchone()
    _require(type(count) is int and count == len(ast_cids)
             and type(charge) is int and 0 <= charge <= 64 * 1024,
             "missing, ambiguous or oversized native AST lookup metadata")
    checkpoint()
    counters["metadata_queries"] += 1
    cursor = connection.execute('SELECT blob_id,ast_cid,file_id,revision_id,parse_status FROM ast_blobs WHERE '
                                + where + ' LIMIT 17', arguments)
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    _require(len(rows) == count and {row["ast_cid"] for row in rows} == set(ast_cids)
             and len({row["blob_id"] for row in rows}) == len(rows),
             "duplicate or omitted native lookup blob binding")
    for row in rows:
        _require(all(type(value) is str and 0 < len(value.encode()) <= 1024 for value in row.values()),
                 "bounded native AST lookup identity required")
    return rows


def _preflight(connection, predicates, limits, counters, checkpoint):
    statements, arguments = [], []
    for ordinal, table in enumerate(ASTS_CATALOG_TABLES):
        where, parameters = predicates[table]
        # Exact owner-DDL columns were checked before this read. DuckDB's
        # bit_length(VARCHAR) measures UTF-8 bytes without copying/JSON-building
        # a hostile large field. Six output bytes per input byte bounds every
        # JSON string escape; numeric/boolean/null scalars fit 128 bytes. These
        # conservative serialized charges include keys and list separators.
        fields = []
        fixed = 3
        for column, kind in _COLUMNS[table]:
            fixed += len(_json_dumps(column).encode()) + 2
            quoted = '"' + column + '"'
            fields.append("CASE WHEN " + quoted + " IS NULL THEN 4 ELSE "
                + ("6*(bit_length(" + quoted + ")//8)+2" if kind == "VARCHAR" else "128") + " END")
        statements.append("SELECT " + str(ordinal) + " AS ordinal,'" + table + "' AS name,count(*) AS row_count,"
            "coalesce(sum(" + str(fixed) + "+" + "+".join(fields) + "),0) AS byte_count FROM \""
            + table + "\" t WHERE " + where)
        arguments.extend(parameters)
    checkpoint()
    counters["preflights"] += 1
    rows = connection.execute("SELECT name,row_count,byte_count FROM (" + " UNION ALL ".join(statements)
                              + ") ORDER BY ordinal", arguments).fetchall()
    _require(len(rows) == len(ASTS_CATALOG_TABLES)
             and [row[0] for row in rows] == list(ASTS_CATALOG_TABLES), "complete native row preflight required")
    sizes, count, charge = {}, 0, 1024
    for table, row_count, byte_count in rows:
        _require(type(row_count) is int and row_count >= 0 and type(byte_count) is int and byte_count >= 0,
                 "finite exact native preflight accounting required")
        sizes[table] = row_count
        count += row_count
        charge += byte_count
    return sizes, count, charge, count <= limits.max_rows and charge <= limits.max_serialized_bytes


def _bodies(connection, predicates, sizes, predicted, limits, counters, checkpoint):
    result, count, charge = {}, 0, 0
    for table in ASTS_CATALOG_TABLES:
        checkpoint()
        where, arguments = predicates[table]
        counters["body_queries"] += 1
        cursor = connection.execute('SELECT * FROM "' + table + '" WHERE ' + where
                                    + ' LIMIT ' + str(limits.max_rows + 1), arguments)
        names = [column[0] for column in cursor.description]
        rows = []
        while True:
            batch = cursor.fetchmany(64)
            if not batch:
                break
            checkpoint()
            count += len(batch)
            _require(count <= limits.max_rows, "native batch rows exceeded preflight bound")
            rows.extend(dict(zip(names, row)) for row in batch)
        _require(len(rows) == sizes[table], "native batch population changed after preflight")
        charge += len(_json_dumps(rows).encode("utf-8"))
        _require(charge <= predicted and charge <= limits.max_serialized_bytes,
                 "native serialized batch exceeded preflight byte bound")
        result[table] = rows
    counters["fetched_rows"] += count
    counters["serialized_bytes"] += charge
    counters["largest_batch_rows"] = max(counters["largest_batch_rows"], count)
    counters["largest_batch_bytes"] = max(counters["largest_batch_bytes"], charge)
    return result


def _replay(store, rows, metadata, expected_members, manifest):
    by_blob = {table: {} for table, _ in _RELATIONS}
    for table, _ in _RELATIONS:
        for row in rows[table]:
            by_blob[table].setdefault(row["blob_id"], []).append(row)
    blobs, revisions, files = {}, {}, {}
    for table, key, destination in (("ast_blobs", "blob_id", blobs),
            ("source_revisions", "revision_id", revisions), ("source_files", "file_id", files)):
        for row in rows[table]:
            destination.setdefault(row[key], []).append(row)
    for meta in metadata:
        blob_id = meta["blob_id"]
        blob = store._one(blobs.get(blob_id, []), "AST blob")
        revision = store._one(revisions.get(blob["revision_id"], []), "revision")
        source_file = store._one(files.get(blob["file_id"], []), "source file")
        diagnostics = by_blob["diagnostics"].get(blob_id, [])
        intrinsic = [row for row in rows["invalidations"] if row["invalidation_id"]
                     == _row_id(blob_id, "invalidation", "parse_failure")] if blob["parse_status"] == ParseStatus.FAILED.value else []
        expected = store._rebuild(blob, revision, diagnostics, intrinsic)
        _require(expected.ast_blob.to_dict() == blob and expected.source_file.to_dict() == source_file,
                 "stored AST/source identity or payload mismatch")
        _require({key: value for key, value in expected.source_revision.to_dict().items() if key != "created_at"}
                 == {key: value for key, value in revision.items() if key != "created_at"},
                 "stored revision identity mismatch")
        _require(type(revision["created_at"]) in {int, float} and math.isfinite(revision["created_at"]),
                 "invalid revision timestamp")
        for table, attribute in _RELATIONS:
            actual = intrinsic if table == "invalidations" else by_blob[table].get(blob_id, [])
            wanted = [row.to_dict() for row in getattr(expected, attribute)]
            _require(sorted(map(_json_dumps, actual)) == sorted(map(_json_dumps, wanted)),
                     "stored " + table + " rows differ from canonical AST payload")
        entry, unit = expected_members[meta["ast_cid"]]
        _require(expected.ast_blob.ast_cid == unit.ast_cid and expected.source_cid == entry.source_cid
                 and expected.source_file.path == entry.path
                 and expected.source_revision.revision_id == manifest.ast_revision_id
                 and expected.ast_blob.parse_status == unit.parse_status,
                 "native projection does not match exact captured source/unit")


def replay_current_inventory_projections(index, manifest, *, expected_head, limits=None, checkpoint=None):
    """Rebuild every captured active projection through bounded fresh SQL batches.

    No owner databases or projections are mutated. Source CAS/live Git/model
    checks are deliberately left to the caller. Returned counters are body-free
    transport accounting and never attest source execution or proof semantics.
    """
    _require(type(manifest) is CodebaseIRManifest and type(expected_head) is CodebaseHead,
             "exact native manifest and head required")
    _require(manifest.cid == expected_head.manifest_cid
             and manifest.snapshot.repository_id == expected_head.repository_id
             and manifest.snapshot.snapshot_cid == expected_head.snapshot_cid
             and manifest.ast_revision_id == expected_head.ast_revision_id
             and len(manifest.snapshot.entries) <= 1024, "head does not bind bounded complete native manifest")
    limits = CodebaseProjectionReplayLimits() if limits is None else limits
    _require(type(limits) is CodebaseProjectionReplayLimits, "exact native projection limits required")
    _require(checkpoint is None or callable(checkpoint), "native replay checkpoint callback required")
    check = (lambda: None) if checkpoint is None else checkpoint
    store = _owners(index)
    check()
    _outside_head(index, expected_head)
    entries = {entry.source_key: entry for entry in manifest.snapshot.entries}
    members = {}
    for unit in manifest.units:
        if unit.ast_cid is not None:
            _require(unit.ast_cid not in members, "duplicate captured AST projection binding")
            members[unit.ast_cid] = (entries[unit.source_key], unit)
    selected = list(members)
    counters = {field: 0 for field in ProjectionReplayReceipt.__dataclass_fields__}
    counters["selected_blobs"] = len(selected)

    def batch(ast_cids):
        check()
        split = False
        with store._lock:
            _require(_owners(index) is store, "native projection owner changed")
            with store._transaction():
                index.catalog._check_schema()
                counters["schema_queries"] += 2
                _schema(store._connection)
                _inside_head(index, expected_head)
                metadata = _metadata(store._connection, ast_cids, counters, check)
                predicates = _predicates(metadata)
                sizes, count, predicted, admitted = _preflight(store._connection, predicates, limits, counters, check)
                if not admitted:
                    _require(len(ast_cids) > 1, "individual native projection exceeds serialized/row replay bound")
                    split = True
                else:
                    rows = _bodies(store._connection, predicates, sizes, predicted, limits, counters, check)
                    check()
                    _replay(store, rows, metadata, members, manifest)
                    counters["replayed_blobs"] += len(ast_cids)
                    counters["batches"] += 1
                    del rows
                _inside_head(index, expected_head)
            _outside_head(index, expected_head)
        check()
        if split:
            middle = len(ast_cids) // 2
            batch(ast_cids[:middle])
            batch(ast_cids[middle:])

    for offset in range(0, len(selected), limits.max_blobs):
        batch(selected[offset:offset + limits.max_blobs])
    check()
    _require(_owners(index) is store, "native projection owner changed at completion")
    _outside_head(index, expected_head)
    return ProjectionReplayReceipt(**counters)


__all__ = ["CodebaseProjectionReplayError", "CodebaseProjectionReplayLimits", "ProjectionReplayReceipt",
           "replay_current_inventory_projections"]
