"""Lossless observations and bounded census of the materialized entity index.

This is not the EntityCache queue/resume schema. Rows, legacy booleans and
ontology mappings are observations only. No row becomes a source-grounded
semantic assertion, and equal labels never merge physical records.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from . import meta_ontology

SCHEMA = "legal-materialized-entity-index-census/v1"
DETAILED_SCHEMA = "legal-materialized-entity-index-census/v2"
ROW_SCHEMA = "legal-materialized-entity-index-observation/v1"
FIELDS = ("record_kind", "meta_category", "graph_kind", "label", "legal_id", "node_id",
          "src", "dst", "logic_role", "in_formula", "admitted", "formalized")
BOOLEAN_FIELDS = ("in_formula", "admitted", "formalized")
KNOWN_KINDS = ("node", "edge", "category", "logical_relation", "classification_rule", "term", "link")
MAX_ROWS = 3_000_000
MAX_BATCH_SIZE = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_DECODED_BYTES = 1024 * 1024 * 1024
MAX_ROW_GROUP_BYTES = 128 * 1024 * 1024
MAX_BATCH_BYTES = 16 * 1024 * 1024
MAX_ROW_BYTES = 128 * 1024
MAX_SCRATCH_BYTES = 1024 * 1024 * 1024
MAX_DISTINCT_VALUES = 512
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = dict.fromkeys(("admitted", "formalized", "source_semantics_verified", "semantic_review_verified",
    "source_occurrences_bound", "globally_consistent", "proof_authority", "training_qualified",
    "typed_graph_assertions_generated", "surface_labels_merged"), False)
_CENSUS_KEYS = {"schema", "source", "limits", "status", "coverage_scope", "rows", "arrow_decoded_bytes",
    "ordered_stream_sha256", "ordered_stream_encoding", "value_counts", "legacy_boolean_observations",
    "null_field_counts", "empty_string_field_counts", "disposition_counts", "classification_observations",
    "duplicate_raw_row_groups", "duplicate_raw_row_extra_instances", "duplicate_node_identities",
    "duplicate_node_identity_extra_instances", "edge_source_endpoint_missing_rows", "edge_target_endpoint_missing_rows",
    "population_complete", "lossless_rows_retained_in_immutable_source", "complete_section_coverage_verified",
    "original_task_acceptance", "authority", "census_sha256"}


class EntityIndexIntakeError(ValueError):
    """Immutable custody, supported schema or a finite intake bound disagrees."""


def _need(condition, message):
    if not condition:
        raise EntityIndexIntakeError(message)


def _wire(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise EntityIndexIntakeError("finite canonical UTF8 observation JSON required") from error


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _bound(value, ceiling, label, *, zero=False):
    _need(type(value) is int and (0 if zero else 1) <= value <= ceiling, "bounded " + label + " required")


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash_file(stream, max_bytes):
    stream.seek(0)
    digest, total = hashlib.sha256(), 0
    while chunk := stream.read(min(1024 * 1024, max_bytes - total + 1)):
        total += len(chunk)
        _need(total <= max_bytes, "source file grew beyond byte bound")
        digest.update(chunk)
    return digest.hexdigest()


def _options(expected_file_sha256, expected_rows, max_rows, batch_size, revision,
             max_file_bytes, max_decoded_bytes, max_row_group_bytes, max_batch_bytes,
             max_row_bytes, max_scratch_bytes):
    _need(type(expected_file_sha256) is str and _SHA.fullmatch(expected_file_sha256), "independent file SHA256 required")
    for value, ceiling, name in ((max_rows, MAX_ROWS, "max_rows"), (batch_size, MAX_BATCH_SIZE, "batch_size"),
        (max_file_bytes, MAX_FILE_BYTES, "max_file_bytes"), (max_decoded_bytes, MAX_DECODED_BYTES, "max_decoded_bytes"),
        (max_row_group_bytes, MAX_ROW_GROUP_BYTES, "max_row_group_bytes"), (max_batch_bytes, MAX_BATCH_BYTES, "max_batch_bytes"),
        (max_row_bytes, MAX_ROW_BYTES, "max_row_bytes"), (max_scratch_bytes, MAX_SCRATCH_BYTES, "max_scratch_bytes")):
        _bound(value, ceiling, name)
    _bound(expected_rows, max_rows, "expected_rows", zero=True)
    _need(max_scratch_bytes >= 4 * 4096, "scratch bound must allow four SQLite pages")
    _need(revision is None or type(revision) is str and revision.strip() and len(revision.encode("utf-8")) <= 256,
          "explicit bounded source revision or missing null required")
    return dict(max_rows=max_rows, batch_size=batch_size, max_file_bytes=max_file_bytes,
        max_decoded_bytes=max_decoded_bytes, max_row_group_bytes=max_row_group_bytes,
        max_batch_bytes=max_batch_bytes, max_row_bytes=max_row_bytes, max_scratch_bytes=max_scratch_bytes)


@contextmanager
def _source(path, expected_file_sha256, expected_rows, revision, limits):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = Path(path).absolute()
    _need(path.resolve() == path, "source file path is aliased")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise EntityIndexIntakeError("source is not an accessible regular file") from error
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limits["max_file_bytes"],
              "source exceeds regular-file byte bound")
        _need(_hash_file(stream, limits["max_file_bytes"]) == expected_file_sha256,
              "source file differs from independently pinned SHA256")
        _need(_identity(before) == _identity(os.fstat(stream.fileno())), "source changed during initial hash")
        stream.seek(0)
        try:
            parquet = pq.ParquetFile(stream, pre_buffer=False, thrift_string_size_limit=1024 * 1024,
                                     thrift_container_size_limit=100_000)
            schema = parquet.schema_arrow
            _need(tuple(schema.names) == FIELDS, "exact ordered twelve-field materialized-index schema required")
            for field in schema:
                wanted = pa.bool_() if field.name in BOOLEAN_FIELDS else pa.string()
                _need(field.type == wanted, "unsupported materialized-index field type: " + field.name)
            metadata = parquet.metadata
            _need(metadata.num_rows == expected_rows <= limits["max_rows"], "footer row count differs from expected population")
            _need(0 <= metadata.num_row_groups <= 4096, "row group inventory exceeds bound")
            groups, expanded, group_rows = [], 0, 0
            for index in range(metadata.num_row_groups):
                group = metadata.row_group(index)
                size = sum(group.column(column).total_uncompressed_size for column in range(group.num_columns))
                _need(all(group.column(column).total_uncompressed_size >= 0 for column in range(group.num_columns))
                      and size <= limits["max_row_group_bytes"], "footer row group exceeds decoded byte bound")
                expanded += size
                group_rows += group.num_rows
                groups.append({"row_group": index, "start_ordinal": group_rows - group.num_rows,
                               "rows": group.num_rows, "footer_uncompressed_bytes": size})
            _need(group_rows == expected_rows and expanded <= limits["max_decoded_bytes"],
                  "footer population or cumulative decoded byte bound differs")
            source = {"path": str(path), "file_sha256": expected_file_sha256, "file_bytes": before.st_size,
                      "revision": revision, "revision_supplied": revision is not None,
                      "arrow_schema_sha256": hashlib.sha256(schema.serialize().to_pybytes()).hexdigest(),
                      "fields": [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in schema],
                      "row_groups": groups, "expected_rows": expected_rows,
                      "raw_row_file_byte_mapping_verified": False}
            yield parquet, source
        except EntityIndexIntakeError:
            raise
        except (pa.ArrowException, OSError, ValueError) as error:
            raise EntityIndexIntakeError("materialized parquet cannot be decoded safely") from error
        finally:
            try:
                _need(_identity(before) == _identity(os.fstat(stream.fileno())) == _identity(path.lstat())
                      and path.resolve() == path, "source file changed or was replaced during traversal")
                _need(_hash_file(stream, limits["max_file_bytes"]) == expected_file_sha256,
                      "source bytes changed during traversal")
                _need(_identity(before) == _identity(os.fstat(stream.fileno())) == _identity(path.lstat()),
                      "source changed during final hash")
            except OSError as error:
                raise EntityIndexIntakeError("source file became unavailable during traversal") from error


def _rows(parquet, source, limits, telemetry):
    ordinal, decoded = 0, 0
    for group in source["row_groups"]:
        local = 0
        for batch in parquet.iter_batches(batch_size=limits["batch_size"], row_groups=[group["row_group"]], use_threads=False):
            _need(batch.num_rows <= limits["batch_size"] and batch.nbytes <= limits["max_batch_bytes"],
                  "Arrow batch exceeds row or decoded byte bound")
            decoded += batch.nbytes
            _need(decoded <= limits["max_decoded_bytes"], "cumulative Arrow expansion exceeds byte bound")
            for row in batch.to_pylist():
                _need(ordinal < source["expected_rows"], "decoded rows exceed expected population")
                _need(type(row) is dict and tuple(row) == FIELDS, "decoded raw row schema differs")
                raw = _wire(row)
                _need(len(raw) <= limits["max_row_bytes"], "raw row exceeds canonical byte bound")
                yield ordinal, group["row_group"], local, row, raw
                ordinal += 1
                local += 1
        _need(local == group["rows"], "decoded row group count differs from footer")
    _need(ordinal == source["expected_rows"], "decoded population differs from expected rows")
    telemetry.update(rows=ordinal, arrow_decoded_bytes=decoded)


def _hint(row):
    kind, graph_kind = row["record_kind"], row["graph_kind"]
    if kind == "node" and graph_kind in meta_ontology.GRAPH_NODE_CATEGORY:
        return {"meta_category": meta_ontology.GRAPH_NODE_CATEGORY[graph_kind], "basis": "declared_node_mapping_only"}
    if kind in ("edge", "logical_relation") and graph_kind in meta_ontology.LOGICAL_RELATIONS:
        relation = meta_ontology.LOGICAL_RELATIONS[graph_kind]
        return {key: relation[key] for key in ("meta_category", "logic_role", "in_formula")} | {"basis": "declared_edge_mapping_only"}
    return None


def iter_observed_rows(path, *, expected_file_sha256, expected_rows, max_rows, batch_size,
                       revision=None, max_file_bytes=MAX_FILE_BYTES, max_decoded_bytes=MAX_DECODED_BYTES,
                       max_row_group_bytes=MAX_ROW_GROUP_BYTES, max_batch_bytes=MAX_BATCH_BYTES,
                       max_row_bytes=MAX_ROW_BYTES, max_scratch_bytes=MAX_SCRATCH_BYTES):
    """Yield every raw row with physical custody; exhaust for a completed traversal.

    No standalone yielded row attests completion of the file. Use census_parquet
    for a final full-population report. Early termination cannot grant coverage.
    The original immutable file retains the physical Parquet bytes; canonical
    raw-row bytes have a separate digest and are not offsets into that file.
    """
    limits = _options(expected_file_sha256, expected_rows, max_rows, batch_size, revision,
        max_file_bytes, max_decoded_bytes, max_row_group_bytes, max_batch_bytes, max_row_bytes, max_scratch_bytes)
    with _source(path, expected_file_sha256, expected_rows, revision, limits) as (parquet, source):
        for ordinal, group, local, row, raw in _rows(parquet, source, limits, {}):
            body = {"schema": ROW_SCHEMA, "ordinal": ordinal, "row_group": group, "row_group_ordinal": local,
                "source": source, "raw_row": row, "raw_row_sha256": hashlib.sha256(raw).hexdigest(),
                "canonical_raw_row_bytes": len(raw), "declared_classification_hint": _hint(row),
                "status": "unreviewed_materialized_index_observation", "authority": dict(_FALSE)}
            body = json.loads(_wire(body))  # A consumer cannot mutate the live scan's custody.
            body["observation_sha256"] = _digest(body)
            yield body


def _increment(counter, value):
    _need(value in counter or len(counter) < MAX_DISTINCT_VALUES, "distinct observation values exceed bound; no partial census")
    counter[value] += 1


def _counts(counter):
    return [{"value": value, "rows": count} for value, count in sorted(counter.items(), key=lambda item: _wire(item[0]))]


def _endpoint_integrity(db):
    """Distinguish absent values from dangling references, without guessing IDs.

    Edges retain physical multiplicity. Null/empty values both denote missing
    IDs in this diagnostic; all other strings match exactly, including spaces.
    Per-endpoint counts can overlap. The four dispositions partition edge rows.
    Logical-relation metadata is deliberately absent from the edges table.
    """
    counts = db.execute("""SELECT coalesce(sum(e.n),0),
        coalesce(sum(CASE WHEN e.src='' THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN e.dst='' THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN e.src='' AND e.dst='' THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN e.src='' OR e.dst='' THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN e.src<>'' AND s.id IS NULL THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN e.dst<>'' AND d.id IS NULL THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN (e.src<>'' AND s.id IS NULL) OR
                              (e.dst<>'' AND d.id IS NULL) THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN s.n>1 THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN d.n>1 THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN s.n>1 OR d.n>1 THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN e.src<>'' AND e.dst<>'' AND
                              (s.id IS NULL OR d.id IS NULL) THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN s.id IS NOT NULL AND d.id IS NOT NULL AND
                              (s.n>1 OR d.n>1) THEN e.n ELSE 0 END),0),
        coalesce(sum(CASE WHEN s.n=1 AND d.n=1 THEN e.n ELSE 0 END),0)
        FROM edges e LEFT JOIN nodes s ON s.id=e.src LEFT JOIN nodes d ON d.id=e.dst""").fetchone()
    return {
        "schema": "legal-materialized-entity-endpoint-integrity/v1",
        "matching_policy": "exact_nonempty_node_id_equality_no_normalization",
        "record_kind": "edge", "edge_rows": counts[0],
        "missing_endpoint_values": dict(zip(("source", "target", "both", "either"), counts[1:5])),
        "nonempty_dangling_references": dict(zip(("source", "target", "either"), counts[5:8])),
        "ambiguous_declared_references": dict(zip(("source", "target", "either"), counts[8:11])),
        "exclusive_edge_dispositions": dict(zip(("missing_endpoint_value", "nonempty_dangling_endpoint",
            "ambiguous_declared_endpoint", "unique_declared_endpoints"), (counts[4], *counts[11:14]))),
        "endpoint_counts_may_overlap": True,
        "semantic_identity_verified": False,
    }


def _check_endpoint_integrity(report):
    """Check accounting identities; only a pinned replay establishes the counts."""
    details = report.get("endpoint_integrity")
    shapes = {
        "missing_endpoint_values": {"source", "target", "both", "either"},
        "nonempty_dangling_references": {"source", "target", "either"},
        "ambiguous_declared_references": {"source", "target", "either"},
        "exclusive_edge_dispositions": {"missing_endpoint_value", "nonempty_dangling_endpoint",
                                        "ambiguous_declared_endpoint", "unique_declared_endpoints"},
    }
    keys = {"schema", "matching_policy", "record_kind", "edge_rows", "endpoint_counts_may_overlap",
            "semantic_identity_verified", *shapes}
    _need(type(details) is dict and set(details) == keys, "closed endpoint integrity details required")
    _need(details["schema"] == "legal-materialized-entity-endpoint-integrity/v1"
          and details["matching_policy"] == "exact_nonempty_node_id_equality_no_normalization"
          and details["record_kind"] == "edge" and details["endpoint_counts_may_overlap"] is True
          and details["semantic_identity_verified"] is False, "endpoint detail semantics or authority differs")
    _bound(details["edge_rows"], MAX_ROWS, "edge_rows", zero=True)
    for key, fields in shapes.items():
        _need(type(details[key]) is dict and set(details[key]) == fields, "closed endpoint counter fields required")
        _need(all(type(value) is int and 0 <= value <= details["edge_rows"]
                  for value in details[key].values()), "bounded nonnegative endpoint counts required")
    _need(details["edge_rows"] <= report["rows"], "edge count exceeds census population")
    missing = details["missing_endpoint_values"]
    _need(missing["both"] <= min(missing["source"], missing["target"])
          and missing["source"] + missing["target"] - missing["both"] == missing["either"],
          "missing endpoint union counts disagree")
    for key in ("nonempty_dangling_references", "ambiguous_declared_references"):
        counts = details[key]
        _need(max(counts["source"], counts["target"]) <= counts["either"] <= counts["source"] + counts["target"],
              "endpoint reference union counts disagree")
    dispositions = details["exclusive_edge_dispositions"]
    _need(dispositions["missing_endpoint_value"] == missing["either"], "missing endpoint disposition differs")
    _need(sum(dispositions.values()) == details["edge_rows"], "endpoint dispositions do not cover edge population")
    _need(dispositions["missing_endpoint_value"] + dispositions["nonempty_dangling_endpoint"] ==
          report["disposition_counts"]["edge_observation_unresolved_endpoint"], "unresolved endpoint counts disagree")
    for key, old in (("ambiguous_declared_endpoint", "edge_observation_ambiguous_endpoint"),
                     ("unique_declared_endpoints", "edge_observation_unique_declared_endpoints")):
        _need(dispositions[key] == report["disposition_counts"][old], "declared endpoint counts disagree")
    for side in ("source", "target"):
        _need(details["missing_endpoint_values"][side] + details["nonempty_dangling_references"][side] ==
              report["edge_" + side + "_endpoint_missing_rows"], "per-endpoint missing counts disagree")


def census_parquet(path, *, expected_file_sha256, expected_rows, max_rows, batch_size,
                   revision=None, max_file_bytes=MAX_FILE_BYTES, max_decoded_bytes=MAX_DECODED_BYTES,
                   max_row_group_bytes=MAX_ROW_GROUP_BYTES, max_batch_bytes=MAX_BATCH_BYTES,
                   max_row_bytes=MAX_ROW_BYTES, max_scratch_bytes=MAX_SCRATCH_BYTES,
                   endpoint_details=False):
    """Return a complete, bounded observation census; no row population in RAM.

    Temporary on-disk SQLite accounts for duplicate raw rows/declared node IDs
    and endpoint populations. Unknown kinds, nulls and duplicate observations
    are retained in counts and stream custody, never silently filtered.

    endpoint_details=True opts into v2, separating absent ID values from
    nonempty dangling references. Default v1 reports and their pins stay intact.
    """
    _need(type(endpoint_details) is bool, "explicit boolean endpoint_details required")
    limits = _options(expected_file_sha256, expected_rows, max_rows, batch_size, revision,
        max_file_bytes, max_decoded_bytes, max_row_group_bytes, max_batch_bytes, max_row_bytes, max_scratch_bytes)
    counters = {key: Counter() for key in ("record_kind", "graph_kind", "meta_category", "logic_role")}
    flags = {key: Counter() for key in BOOLEAN_FIELDS}
    nulls, empty, dispositions, hints, telemetry = Counter(), Counter(), Counter(), Counter(), {}
    with tempfile.TemporaryDirectory(prefix="legal-entity-index-") as temporary:
        db = sqlite3.connect(str(Path(temporary) / "observations.sqlite"))
        try:
            db.execute("PRAGMA page_size=4096")
            db.execute("PRAGMA max_page_count=" + str(max(1, limits["max_scratch_bytes"] // 4096)))
            db.execute("PRAGMA cache_size=-8192")
            db.execute("PRAGMA temp_store=FILE")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("CREATE TABLE raw_rows (sha BLOB PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID")
            db.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID")
            db.execute("CREATE TABLE edges (src TEXT NOT NULL, dst TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(src,dst)) WITHOUT ROWID")
            with _source(path, expected_file_sha256, expected_rows, revision, limits) as (parquet, source):
                stream = hashlib.sha256(b"legal-materialized-entity-index-ordered-stream/v1\x00" + _wire(source))
                for ordinal, group, local, row, raw in _rows(parquet, source, limits, telemetry):
                    stream.update(ordinal.to_bytes(8, "big") + len(raw).to_bytes(8, "big") + raw)
                    db.execute("INSERT INTO raw_rows VALUES (?,1) ON CONFLICT(sha) DO UPDATE SET n=n+1",
                               (hashlib.sha256(raw).digest(),))
                    for key, counter in counters.items(): _increment(counter, row[key])
                    for key, counter in flags.items(): counter[row[key]] += 1
                    for key, value in row.items():
                        if value is None: nulls[key] += 1
                        elif value == "": empty[key] += 1
                    kind = row["record_kind"]
                    hint = _hint(row)
                    hints["known_declared_mapping" if hint else "no_declared_mapping"] += 1
                    if hint and any(row[key] != value for key, value in hint.items() if key != "basis"):
                        hints["observed_fields_disagree_with_declared_mapping"] += 1
                    if kind == "node":
                        if row["node_id"]:
                            db.execute("INSERT INTO nodes VALUES (?,1) ON CONFLICT(id) DO UPDATE SET n=n+1", (row["node_id"],))
                            dispositions["node_observation"] += 1
                        else: dispositions["node_observation_missing_identity"] += 1
                    elif kind == "edge":
                        db.execute("INSERT INTO edges VALUES (?,?,1) ON CONFLICT(src,dst) DO UPDATE SET n=n+1",
                                   (row["src"] or "", row["dst"] or ""))
                    else:
                        dispositions[kind + "_observation" if kind in KNOWN_KINDS else "unknown_record_kind_observation"] += 1
                endpoint = db.execute("""SELECT
                    coalesce(sum(CASE WHEN s.id IS NULL OR d.id IS NULL THEN e.n ELSE 0 END),0),
                    coalesce(sum(CASE WHEN s.id IS NOT NULL AND d.id IS NOT NULL AND (s.n>1 OR d.n>1) THEN e.n ELSE 0 END),0),
                    coalesce(sum(CASE WHEN s.n=1 AND d.n=1 THEN e.n ELSE 0 END),0),
                    coalesce(sum(CASE WHEN s.id IS NULL THEN e.n ELSE 0 END),0),
                    coalesce(sum(CASE WHEN d.id IS NULL THEN e.n ELSE 0 END),0)
                    FROM edges e LEFT JOIN nodes s ON s.id=e.src LEFT JOIN nodes d ON d.id=e.dst""").fetchone()
                for name, count in zip(("edge_observation_unresolved_endpoint", "edge_observation_ambiguous_endpoint",
                                       "edge_observation_unique_declared_endpoints"), endpoint):
                    dispositions[name] = count
                raw_duplicates = db.execute("SELECT count(*),coalesce(sum(n-1),0) FROM raw_rows WHERE n>1").fetchone()
                node_duplicates = db.execute("SELECT count(*),coalesce(sum(n-1),0) FROM nodes WHERE n>1").fetchone()
                _need(sum(dispositions.values()) == telemetry["rows"] == expected_rows,
                      "exclusive record dispositions do not cover exact population")
                report = {"schema": SCHEMA, "source": source, "limits": limits,
                    "status": "complete_observation_census", "coverage_scope": "exact_pinned_parquet_rows_only",
                    "rows": telemetry["rows"], "arrow_decoded_bytes": telemetry["arrow_decoded_bytes"],
                    "ordered_stream_sha256": stream.hexdigest(),
                    "ordered_stream_encoding": "domain+canonical_source+ordinal_u64be+length_u64be+canonical_raw_row",
                    "value_counts": {key: _counts(counter) for key, counter in counters.items()},
                    "legacy_boolean_observations": {key: _counts(counter) for key, counter in flags.items()},
                    "null_field_counts": {key: nulls[key] for key in FIELDS},
                    "empty_string_field_counts": {key: empty[key] for key in FIELDS},
                    "disposition_counts": dict(sorted(dispositions.items())), "classification_observations": dict(hints),
                    "duplicate_raw_row_groups": raw_duplicates[0], "duplicate_raw_row_extra_instances": raw_duplicates[1],
                    "duplicate_node_identities": node_duplicates[0], "duplicate_node_identity_extra_instances": node_duplicates[1],
                    "edge_source_endpoint_missing_rows": endpoint[3], "edge_target_endpoint_missing_rows": endpoint[4],
                    "population_complete": True, "lossless_rows_retained_in_immutable_source": True,
                    "complete_section_coverage_verified": False, "original_task_acceptance": "preparatory_subset_only",
                    "authority": dict(_FALSE)}
                if endpoint_details:
                    report["schema"] = DETAILED_SCHEMA
                    report["endpoint_integrity"] = _endpoint_integrity(db)
                    _check_endpoint_integrity(report)
            report["census_sha256"] = _digest(report)
            return report
        except sqlite3.Error as error:
            raise EntityIndexIntakeError("bounded on-disk observation index failed; no partial census") from error
        finally:
            db.close()


def validate_census(report, path, **trusted_inputs):
    """Replay every row under independently supplied file/population/revision pins."""
    expected = census_parquet(path, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "entity-index census differs from trusted full replay")
    return expected


def validate_census_bindings(report, path, *, expected_census_sha256, expected_file_sha256, expected_rows,
                            max_rows, batch_size, revision=None, max_file_bytes=MAX_FILE_BYTES,
                            max_decoded_bytes=MAX_DECODED_BYTES, max_row_group_bytes=MAX_ROW_GROUP_BYTES,
                            max_batch_bytes=MAX_BATCH_BYTES, max_row_bytes=MAX_ROW_BYTES,
                            max_scratch_bytes=MAX_SCRATCH_BYTES, endpoint_details=False):
    """Verify a separately pinned prior census and current immutable file custody.

    This rehashes the whole file and checks schema/footer/limits, without decoding
    rows again. An independent expected_census_sha256 is mandatory; a summary's
    self-reported hash cannot substitute for prior full-population replay.
    """
    _need(type(endpoint_details) is bool, "explicit boolean endpoint_details required")
    limits = _options(expected_file_sha256, expected_rows, max_rows, batch_size, revision,
        max_file_bytes, max_decoded_bytes, max_row_group_bytes, max_batch_bytes, max_row_bytes, max_scratch_bytes)
    _need(type(expected_census_sha256) is str and _SHA.fullmatch(expected_census_sha256),
          "independently retained census SHA256 required")
    keys = _CENSUS_KEYS | {"endpoint_integrity"} if endpoint_details else _CENSUS_KEYS
    _need(type(report) is dict and set(report) == keys, "closed prior census required")
    _need(report["census_sha256"] == expected_census_sha256 == _digest(
        {key: value for key, value in report.items() if key != "census_sha256"}),
        "prior census differs from independently pinned identity")
    _need(report["schema"] == (DETAILED_SCHEMA if endpoint_details else SCHEMA)
          and report["status"] == "complete_observation_census"
          and report["coverage_scope"] == "exact_pinned_parquet_rows_only"
          and report["population_complete"] is True and report["lossless_rows_retained_in_immutable_source"] is True
          and report["complete_section_coverage_verified"] is False
          and report["original_task_acceptance"] == "preparatory_subset_only"
          and _wire(report["authority"]) == _wire(_FALSE), "prior census coverage or authority differs")
    _need(type(report["rows"]) is int and report["rows"] == expected_rows
          and _wire(report["limits"]) == _wire(limits), "prior census population or limits differ")
    _need(type(report["disposition_counts"]) is dict and all(type(value) is int and value >= 0
          for value in report["disposition_counts"].values())
          and sum(report["disposition_counts"].values()) == expected_rows, "prior census dispositions do not cover population")
    if endpoint_details:
        _check_endpoint_integrity(report)
    with _source(path, expected_file_sha256, expected_rows, revision, limits) as (_, source):
        _need(_wire(report["source"]) == _wire(source), "prior census source custody differs")
    return {"schema": "legal-materialized-entity-index-bindings-validation/v1",
        "census_sha256": expected_census_sha256, "file_sha256": expected_file_sha256,
        "status": "pinned_prior_census_custody_verified", "fresh_row_replay_performed": False,
        "coverage_scope": "immutable_file_and_independently_pinned_prior_census_only", "authority": dict(_FALSE)}


__all__ = ["EntityIndexIntakeError", "iter_observed_rows", "census_parquet", "validate_census", "validate_census_bindings"]
