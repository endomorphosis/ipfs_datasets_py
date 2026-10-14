"""Pinned cache -> retained producer declaration -> physical parent-row witnesses.

Local byte/identity replay does not attest a historical invocation, original
character occurrence, official edition, legal meaning, training or Lean proof.
No source revision is expanded and no missing producer reference is invented.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zlib

from . import legal_span_cache_intake as intake
from . import legal_span_provenance as provenance

SCHEMA = "legal-producer-lineage-observations/v1"
MANIFEST_SCHEMA = "legal-producer-lineage-witness-manifest/v1"
PARENT_PROFILE = "legacy_laws_parquet/v1"
REPORT_PROFILE = "paired_original_receipt_json/v1"
MAX_RECORDS = 128
MAX_REPORTS = 8
MAX_PARENT_FILES = 4
MAX_SELECTED_ROWS = 32
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_PARENT_ROW_BYTES = 8 * 1024 * 1024
MAX_SELECTED_BYTES = 32 * 1024 * 1024
MAX_REPORT_ROWS = 256
MAX_SCAN_ROWS = 100_000
MAX_ARROW_BATCH_BYTES = 8 * 1024 * 1024
MAX_PARQUET_FOOTER_BYTES = 1024 * 1024
MAX_PARQUET_COLUMNS = 64
MAX_PARQUET_GROUPS = 1024
MAX_PARQUET_GROUP_LEAF_VALUES = 250_000
# Conservative supported decoder profile. A large compressed row group is
# refused before Arrow decoding; an incremental batch size alone is no bound
# on dictionary/page materialization. This is a parser input limit, not an OS
# memory quota or an assertion about arbitrary Parquet implementations.
MAX_PARQUET_GROUP_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_JSON_NODES = 2_000_000
MAX_JSON_DEPTH = 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
FILE_FIELDS = {"repository", "revision", "path_in_repo", "local_path", "sha256", "bytes"}
PARENT_FIELDS = FILE_FIELDS | {"row_count", "profile"}
REPORT_FIELDS = {"profile", "local_path", "sha256", "bytes", "origin"}
ORIGIN_FIELDS = {"container", "artifact_row_ordinal", "artifact_sha256"}
AUTHORITY = dict.fromkeys(("historical_job_lineage_verified", "model_invocation_verified",
    "original_character_occurrence_attested", "official_edition_correspondence_verified",
    "source_authority_authenticated", "source_semantics_verified", "context_closure_verified",
    "authenticated_review_verified", "training_qualified", "proof_authority",
    "Lean_kernel_admission", "admitted", "formalized"), False)


class ProducerLineageError(ValueError):
    """A bounded independent custody/population/profile contract differs."""


class _UnsupportedParentDecodedProfile(ProducerLineageError):
    """An otherwise pinned parent cannot be decoded within this profile."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def _need(ok, message):
    if not ok:
        raise ProducerLineageError(message)


def _wire(value, maximum=MAX_REPORT_BYTES):
    nodes = 0
    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        _need(depth <= MAX_JSON_DEPTH and nodes <= MAX_JSON_NODES, "lineage JSON depth/node bound exceeded")
        if type(item) is dict:
            _need(all(type(k) is str for k in item), "plain string JSON keys required")
            for child in item.values(): visit(child, depth + 1)
        elif type(item) is list:
            for child in item: visit(child, depth + 1)
        else:
            _need(item is None or type(item) in (str, int, bool, float), "plain JSON values required")
            if type(item) is float: _need(math.isfinite(item), "finite JSON values required")
    visit(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProducerLineageError("finite UTF-8 JSON required") from exc
    _need(len(raw) <= maximum, "lineage JSON byte bound exceeded; no truncation")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "independent lowercase SHA256 required")


def _preflight_json(raw):
    """Bound lexical values/keys and nesting before creating Python objects.

    This deliberately counts object keys too, a stricter ceiling than _wire.
    Full JSON grammar, UTF-8, duplicate-key and finite-number validation follows
    in the standard parser. Quoted/escaped delimiters never change nesting.
    """
    _need(type(raw) is bytes and len(raw) <= MAX_REPORT_BYTES, "bounded producer JSON bytes required")
    offset = 0; nodes = 0; stack = []
    while offset < len(raw):
        token = raw[offset]
        if token in b" \t\r\n,:": offset += 1; continue
        if token in (ord("}"), ord("]")):
            _need(stack and stack.pop() == token, "malformed producer JSON nesting")
            offset += 1; continue
        nodes += 1
        _need(nodes <= MAX_JSON_NODES, "producer JSON predecode node bound exceeded")
        if token in (ord("{"), ord("[")):
            stack.append(ord("}") if token == ord("{") else ord("]"))
            _need(len(stack) <= MAX_JSON_DEPTH, "producer JSON predecode depth bound exceeded")
            offset += 1
        elif token == ord('"'):
            offset += 1
            while offset < len(raw):
                token = raw[offset]; offset += 1
                if token == ord('"'): break
                if token == ord("\\"): offset += 1
            else: raise ProducerLineageError("malformed producer JSON string")
            _need(offset <= len(raw), "malformed producer JSON escape")
        else:
            while offset < len(raw) and raw[offset] not in b" \t\r\n,:{}[]\"": offset += 1
    _need(not stack, "malformed producer JSON nesting")


def _json(raw):
    _preflight_json(raw)
    def pairs(values):
        result = {}
        for k, v in values:
            _need(k not in result, "duplicate JSON key in producer report")
            result[k] = v
        return result
    def constant(value):
        raise ProducerLineageError("nonfinite JSON constant in producer report")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ProducerLineageError): raise
        raise ProducerLineageError("malformed producer JSON") from exc
    _wire(value)
    return value


def _file_descriptor(value, *, parent=False):
    _need(type(value) is dict and set(value) == (PARENT_FIELDS if parent else FILE_FIELDS), "closed source file descriptor required")
    _sha(value["sha256"])
    _need(type(value["revision"]) is str and _REVISION.fullmatch(value["revision"]), "literal full repository revision required; no expansion")
    _need(type(value["repository"]) is str and bool(value["repository"].strip()) and len(value["repository"]) <= 256, "literal repository required")
    rel = value["path_in_repo"]
    _need(type(rel) is str and 0 < len(rel) <= 2048 and "\\" not in rel and not PurePosixPath(rel).is_absolute()
          and all(part not in {"", ".", ".."} for part in rel.split("/")), "literal safe repository path required")
    _need(type(value["local_path"]) is str and Path(value["local_path"]).is_absolute(), "explicit absolute local file required")
    _need(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_FILE_BYTES, "bounded exact source file byte count required")
    if parent:
        _need(value["profile"] == PARENT_PROFILE and type(value["row_count"]) is int
              and 0 < value["row_count"] <= MAX_SCAN_ROWS, "supported bounded complete parent footer population required")
    return deepcopy(value)


def descriptor_sha256(descriptor):
    """Digest the complete descriptor, including its explicitly supplied path."""
    return _digest(descriptor)


@contextmanager
def _opened(descriptor, maximum):
    path = Path(descriptor["local_path"])
    _need(path.resolve(strict=True) == path, "source file path is aliased")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        _need(stat.S_ISREG(before.st_mode) and before.st_size == descriptor["bytes"] <= maximum,
              "source regularity/declared byte bound differs")
        def check():
            _need(identity(before) == identity(os.fstat(stream.fileno())) == identity(path.lstat())
                  and path.resolve(strict=True) == path, "source file FD/path changed")
        def digest():
            stream.seek(0); h = hashlib.sha256(); count = 0
            while True:
                block = stream.read(min(1024 * 1024, descriptor["bytes"] - count + 1))
                if not block: break
                count += len(block)
                _need(count <= descriptor["bytes"], "source grew beyond independent byte bound")
                h.update(block)
            _need(count == descriptor["bytes"] and h.hexdigest() == descriptor["sha256"], "independent source file SHA256 differs")
            check(); stream.seek(0)
        check(); digest()
        try:
            yield stream
        finally:
            check(); digest()


def _parquet_preflight(stream, *, parent):
    """Reject oversized footer/schema/groups before iter_batches is invoked."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    error = _UnsupportedParentDecodedProfile if parent else ProducerLineageError
    def require(ok, message, details=None):
        if not ok:
            if parent: raise error(message, details)
            raise error(message)
    stream.seek(0, os.SEEK_END); size = stream.tell()
    require(size >= 12, "Parquet footer profile missing")
    stream.seek(0); require(stream.read(4) == b"PAR1", "Parquet magic profile unsupported")
    stream.seek(-8, os.SEEK_END); tail = stream.read(8)
    footer_bytes = int.from_bytes(tail[:4], "little")
    require(tail[4:] == b"PAR1" and 0 < footer_bytes <= MAX_PARQUET_FOOTER_BYTES
            and footer_bytes <= size - 12, "Parquet predecode footer byte bound exceeded")
    stream.seek(0); parquet = pq.ParquetFile(stream)
    metadata = parquet.metadata; schema = parquet.schema_arrow
    require(0 < metadata.num_columns <= MAX_PARQUET_COLUMNS
            and 0 < metadata.num_row_groups <= MAX_PARQUET_GROUPS,
            "Parquet predecode column/group bound exceeded")
    require(len(schema.names) == len(set(schema.names)), "duplicate Parquet top-level columns unsupported")
    if parent:
        def supported(t):
            return (pa.types.is_null(t) or pa.types.is_string(t) or pa.types.is_boolean(t)
                or pa.types.is_integer(t) or pa.types.is_floating(t)
                or (pa.types.is_list(t) and (pa.types.is_string(t.value_type) or pa.types.is_null(t.value_type))))
        require(all(supported(field.type) for field in schema), "parent predecode Arrow type profile unsupported")
    else:
        require(schema.names == ["artifact_sha256", "kind", "encoding", "decoded_bytes", "payload"]
            and [field.type for field in schema] == [pa.string(), pa.string(), pa.string(), pa.int64(), pa.binary()],
            "artifact predecode Arrow type/column profile unsupported")
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        sizes = [group.column(i).total_uncompressed_size for i in range(group.num_columns)]
        values = [group.column(i).num_values for i in range(group.num_columns)]
        require(all(type(n) is int and 0 <= n <= MAX_PARQUET_GROUP_LEAF_VALUES for n in values),
            "Parquet predecode row-group leaf-value bound exceeded",
            {"row_group": index, "max_declared_leaf_values": max(values, default=0),
                "max_leaf_values": MAX_PARQUET_GROUP_LEAF_VALUES})
        require(group.num_columns == metadata.num_columns and 0 < group.num_rows <= MAX_SCAN_ROWS
            and all(type(n) is int and n >= 0 for n in sizes)
            and sum(sizes) <= MAX_PARQUET_GROUP_UNCOMPRESSED_BYTES,
            "Parquet predecode row-group uncompressed byte bound exceeded",
            {"row_group": index, "row_group_rows": group.num_rows,
                "leaf_columns": group.num_columns, "declared_uncompressed_bytes": sum(sizes),
                "max_declared_uncompressed_bytes": MAX_PARQUET_GROUP_UNCOMPRESSED_BYTES})
    return parquet


def read_parent_row_witnesses(parent_descriptor, *, expected_descriptor_sha256, row_ordinals):
    """Replay exact requested physical rows, retaining every column and value.

    Reads are incremental and stop after the last requested ordinal. The full
    file digest/footer are checked; this does not inventory every parent row.
    Actual Parquet scans belong inside the caller's native validation lease.
    """
    descriptor = _file_descriptor(parent_descriptor, parent=True)
    _sha(expected_descriptor_sha256)
    _need(descriptor_sha256(descriptor) == expected_descriptor_sha256, "independent parent descriptor differs")
    _need(type(row_ordinals) is list and 0 < len(row_ordinals) <= MAX_SELECTED_ROWS
          and all(type(n) is int and 0 <= n < descriptor["row_count"] for n in row_ordinals)
          and row_ordinals == sorted(set(row_ordinals)), "exact ordered distinct bounded parent row requests required")
    wanted = set(row_ordinals); rows = []; retained = 0; ordinal = 0
    with _opened(descriptor, MAX_FILE_BYTES) as stream:
        parquet = _parquet_preflight(stream, parent=True)
        _need(parquet.metadata.num_rows == descriptor["row_count"], "independent parent footer row count differs")
        _need(len(parquet.schema_arrow.names) == len(set(parquet.schema_arrow.names)), "duplicate parent column names unsupported")
        row_group = 0; group_start = 0
        for batch in parquet.iter_batches(batch_size=32, use_threads=False):
            _need(batch.nbytes <= MAX_ARROW_BATCH_BYTES, "parent decoded Arrow batch bound exceeded")
            for raw_row in batch.to_pylist():
                while row_group + 1 < parquet.metadata.num_row_groups and ordinal >= group_start + parquet.metadata.row_group(row_group).num_rows:
                    group_start += parquet.metadata.row_group(row_group).num_rows; row_group += 1
                if ordinal in wanted:
                    payload = _wire(raw_row, MAX_PARENT_ROW_BYTES); retained += len(payload)
                    _need(retained <= MAX_SELECTED_BYTES, "complete selected parent decoded-byte bound exceeded")
                    rows.append({"row_ordinal": ordinal, "row_group": row_group,
                        "row_group_ordinal": ordinal - group_start, "raw_row": raw_row,
                        "raw_row_sha256": hashlib.sha256(payload).hexdigest()})
                ordinal += 1
                _need(ordinal <= MAX_SCAN_ROWS, "parent scanned-row bound exceeded")
                if ordinal > row_ordinals[-1]: break
            if ordinal > row_ordinals[-1]: break
    _need([r["row_ordinal"] for r in rows] == row_ordinals, "requested physical parent rows missing")
    report = {"schema": "legal-producer-parent-row-witnesses/v1", "descriptor": descriptor,
        "descriptor_sha256": expected_descriptor_sha256, "requested_row_ordinals": row_ordinals,
        "rows": rows, "scanned_prefix_rows": ordinal, "selected_decoded_bytes": retained,
        "complete_requested_population": True, "whole_parent_population_inventoried": False,
        "authority": dict(AUTHORITY)}
    report["inventory_sha256"] = _digest(report)
    return report


def witness_manifest_sha256(manifest):
    return _digest(manifest)


def lineage_report_sha256(report):
    """Hash the entire report, including its internal lineage_sha256 seal."""
    return _digest(report)


def _report_descriptor(value):
    _need(type(value) is dict and set(value) == REPORT_FIELDS and value["profile"] == REPORT_PROFILE,
          "closed supported producer report descriptor required")
    _sha(value["sha256"])
    _need(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_REPORT_BYTES, "bounded complete producer report bytes required")
    _need(type(value["local_path"]) is str and Path(value["local_path"]).is_absolute(), "explicit decoded report file required")
    origin = value["origin"]
    _need(type(origin) is dict and set(origin) == ORIGIN_FIELDS, "closed exact artifact origin required")
    _file_descriptor(origin["container"]); _sha(origin["artifact_sha256"])
    _need(origin["artifact_sha256"] == value["sha256"] and type(origin["artifact_row_ordinal"]) is int
          and 0 <= origin["artifact_row_ordinal"] < MAX_SELECTED_ROWS, "exact bounded original artifact identity/ordinal required")
    return deepcopy(value)


def _load_report(descriptor):
    """Replay complete container/header/zlib bytes and the retained raw JSON."""
    origin = descriptor["origin"]; candidates = []; ordinal = 0
    with _opened(origin["container"], MAX_REPORT_BYTES) as stream:
        parquet = _parquet_preflight(stream, parent=False)
        _need(parquet.metadata.num_rows <= MAX_SELECTED_ROWS
              and set(parquet.schema_arrow.names) == {"artifact_sha256", "kind", "encoding", "decoded_bytes", "payload"}
              and len(parquet.schema_arrow.names) == 5, "bounded exact artifact table profile required")
        for batch in parquet.iter_batches(batch_size=1, use_threads=False):
            _need(batch.nbytes <= MAX_ARROW_BATCH_BYTES, "artifact decoded Arrow batch bound exceeded")
            for row in batch.to_pylist():
                if row["artifact_sha256"] == descriptor["sha256"]: candidates.append((ordinal, row))
                ordinal += 1
    if not candidates: return None, [{"code": "original_receipt_artifact_missing"}]
    if len(candidates) != 1: return None, [{"code": "multiple_original_receipt_artifacts", "count": len(candidates)}]
    artifact_ordinal, artifact = candidates[0]
    _need(artifact_ordinal == origin["artifact_row_ordinal"], "independent artifact row ordinal differs")
    _need(artifact["kind"] == "original_producer_receipt" and artifact["encoding"] == "zlib-json/v1"
          and type(artifact["decoded_bytes"]) is int and artifact["decoded_bytes"] == descriptor["bytes"], "original producer artifact declaration differs")
    payload = artifact["payload"]
    _need(type(payload) is bytes and len(payload) <= MAX_REPORT_BYTES, "bounded original compressed payload required")
    decoder = zlib.decompressobj()
    try: raw = decoder.decompress(payload, descriptor["bytes"] + 1)
    except zlib.error as exc: raise ProducerLineageError("corrupt original producer zlib stream") from exc
    _need(len(raw) == descriptor["bytes"] and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
          and hashlib.sha256(raw).hexdigest() == descriptor["sha256"], "complete original producer decoded stream/hash differs")
    decoded = {"local_path": descriptor["local_path"], "sha256": descriptor["sha256"], "bytes": descriptor["bytes"]}
    with _opened(decoded, MAX_REPORT_BYTES) as stream:
        retained = stream.read(descriptor["bytes"] + 1)
        _need(retained == raw, "retained decoded report differs from source artifact")
    report = _json(raw)
    if type(report) is not dict or report.get("schema_version") != "legacy-span-cuda-diagnostic/v1":
        return None, [{"code": "unsupported_producer_report_schema"}]
    _need(type(report.get("rows")) is list and len(report["rows"]) <= MAX_REPORT_ROWS
          and all(type(row) is dict for row in report["rows"]), "bounded complete producer report row population required")
    return report, []


def _manifest(value, expected, record_ids):
    _sha(expected)
    _need(witness_manifest_sha256(value) == expected, "independent complete witness manifest differs")
    _need(type(value) is dict and set(value) == {"schema", "reports", "parents", "records"}
          and value["schema"] == MANIFEST_SCHEMA, "closed supported witness manifest required")
    _need(type(value["reports"]) is list and len(value["reports"]) <= MAX_REPORTS, "bounded producer report population required")
    for report in value["reports"]: _report_descriptor(report)
    report_ids = [r["sha256"] for r in value["reports"]]
    _need(len(report_ids) == len(set(report_ids)), "duplicate producer report identities")
    _need(sum(r["bytes"] for r in value["reports"]) <= 2 * MAX_REPORT_BYTES, "aggregate producer decoded-byte bound exceeded")
    _need(type(value["parents"]) is list and len(value["parents"]) <= MAX_PARENT_FILES, "bounded parent file population required")
    parent_ids = []
    for parent in value["parents"]:
        _need(type(parent) is dict and set(parent) == {"descriptor", "row_ordinals", "expected_row_sha256s"}, "closed parent-row witness request required")
        descriptor = _file_descriptor(parent["descriptor"], parent=True); parent_ids.append(descriptor["sha256"])
        ordinals, hashes = parent["row_ordinals"], parent["expected_row_sha256s"]
        _need(type(ordinals) is list and 0 < len(ordinals) <= MAX_SELECTED_ROWS
              and all(type(n) is int and 0 <= n < descriptor["row_count"] for n in ordinals)
              and ordinals == sorted(set(ordinals))
              and type(hashes) is list and len(hashes) == len(ordinals), "complete ordered parent row/hash requests required")
        for h in hashes: _sha(h)
    _need(len(parent_ids) == len(set(parent_ids)) and sum(len(p["row_ordinals"]) for p in value["parents"]) <= MAX_SELECTED_ROWS,
          "duplicate parent identities or aggregate selected-row bound exceeded")
    records = value["records"]
    _need(type(records) is list and [r.get("record_sha256") if type(r) is dict else None for r in records] == record_ids,
          "independent ordered physical record witness population differs")
    for record in records:
        _need(set(record) == {"record_sha256", "report_sha256s"} and type(record["report_sha256s"]) is list
              and len(record["report_sha256s"]) <= MAX_REPORTS
              and all(type(h) is str and _SHA.fullmatch(h) for h in record["report_sha256s"])
              and len(record["report_sha256s"]) == len(set(record["report_sha256s"]))
              and all(h in report_ids for h in record["report_sha256s"]), "closed bounded explicit report candidates required")
    return deepcopy(value)


def _verified_page_parent(request, item):
    """Use the fixed page owner and regenerate independently pinned whole reports.

    This path belongs only to the additive v2 wrapper. A caller cannot supply an
    arbitrary reader, projected rows, or a self-seal in place of external pins.
    """
    from . import legal_parent_parquet_pages as pages
    fields = {"descriptor_sha256", "preflight_report", "expected_preflight_sha256",
              "row_report", "expected_row_report_sha256"}
    _need(type(item) is dict and set(item) == fields, "closed page-parent replay input required")
    descriptor = request["descriptor"]
    for field in ("descriptor_sha256", "expected_preflight_sha256", "expected_row_report_sha256"):
        _sha(item[field])
    _need(item["descriptor_sha256"] == descriptor_sha256(descriptor), "independent page-parent descriptor pin differs")
    _need(type(item["preflight_report"]) is dict and type(item["row_report"]) is dict,
          "complete externally pinned page and selected-row reports required")
    _need(pages.parent_page_report_sha256(item["preflight_report"]) == item["expected_preflight_sha256"],
          "independent FULL page preflight pin differs")
    _need(pages.parent_row_report_sha256(item["row_report"]) == item["expected_row_report_sha256"],
          "independent FULL page-selected-row pin differs")
    limits = item["preflight_report"].get("limits")
    checked = pages.read_selected_parent_rows(descriptor,
        expected_descriptor_sha256=item["descriptor_sha256"],
        preflight_report=item["preflight_report"],
        expected_preflight_sha256=item["expected_preflight_sha256"],
        row_ordinals=request["row_ordinals"], expected_row_sha256s=request["expected_row_sha256s"],
        limits=limits)
    _need(_wire(checked) == _wire(item["row_report"]), "complete page-selected rows differ from fixed-owner regeneration")
    _need([r["raw_row_sha256"] for r in checked["rows"]] == request["expected_row_sha256s"],
          "independent page-selected row hash population differs")
    return checked


def _reconcile_producer_lineage(provenance_reports, *, expected_provenance_report_sha256s,
        expected_record_sha256s, witness_manifest, expected_witness_manifest_sha256,
        parent_profile="legacy_v1", parent_page_inputs=None,
        expected_parent_page_inputs_sha256=None):
    """Common declaration checks with a closed, owner-fixed parent profile."""
    _need(parent_profile in ("legacy_v1", "pagewise_v2"), "closed parent decoder profile required")
    if parent_profile == "legacy_v1":
        _need(parent_page_inputs is None and expected_parent_page_inputs_sha256 is None,
              "legacy parent profile cannot accept alternate page witnesses")
    else:
        _sha(expected_parent_page_inputs_sha256)
        _need(type(parent_page_inputs) is list and len(parent_page_inputs) <= MAX_PARENT_FILES,
              "bounded complete page-parent input population required")
        payload = _wire(parent_page_inputs, 32 * 1024 * 1024)
        _need(hashlib.sha256(payload).hexdigest() == expected_parent_page_inputs_sha256,
              "independent complete page-parent input population pin differs")
    _need(type(provenance_reports) is list and 0 < len(provenance_reports) <= 8
          and type(expected_provenance_report_sha256s) is list
          and len(provenance_reports) == len(expected_provenance_report_sha256s), "complete bounded provenance batch pins required")
    physical = []
    for report, pin in zip(provenance_reports, expected_provenance_report_sha256s, strict=True):
        _sha(pin)
        _need(provenance.provenance_report_sha256(report) == pin and report.get("schema") == provenance.SCHEMA
              and report.get("population_complete") is True and all(v is False for v in report["authority"].values()), "independently pinned inert provenance report differs")
        rows = report["rows"]
        _need(type(rows) is list and len(rows) == report["row_count"] and 0 < len(rows) <= MAX_RECORDS
              and len(physical) + len(rows) <= MAX_RECORDS, "complete bounded provenance row population required")
        for i, row in enumerate(rows):
            raw = row["raw_row"]; ordinal = report["start_ordinal"] + i
            _need(row["row_ordinal"] == ordinal and row["raw_row_sha256"] == intake.row_sha256(raw)
                  and row["record_sha256"] == intake.record_sha256(raw, ordinal=ordinal, cache_identity=report["cache_identity"]), "raw cache membership/ordinal/hash differs")
            identity, _issues = provenance._source_identity(raw)
            _need(_wire(identity) == _wire(row["source_identity"]), "source projection differs from raw cache row")
            physical.append((row, report["cache_identity"]))
    ids = [r["record_sha256"] for r, cache in physical]
    _need(0 < len(physical) <= MAX_RECORDS and type(expected_record_sha256s) is list
          and ids == expected_record_sha256s and len(ids) == len(set(ids)), "independent complete ordered physical record population differs")
    manifest = _manifest(witness_manifest, expected_witness_manifest_sha256, ids)
    if parent_profile == "pagewise_v2":
        _need(len(parent_page_inputs) == len(manifest["parents"]), "complete page-parent input population differs")
        _need([p.get("descriptor_sha256") if type(p) is dict else None for p in parent_page_inputs]
              == [descriptor_sha256(p["descriptor"]) for p in manifest["parents"]],
              "ordered page-parent descriptor population differs")
    reports = {}; report_issues = {}; inventories = {}; file_issues = []
    for descriptor in manifest["reports"]:
        try: report, issues = _load_report(descriptor)
        except FileNotFoundError: report, issues = None, [{"code": "producer_report_or_container_file_unavailable"}]
        reports[descriptor["sha256"]] = report; report_issues[descriptor["sha256"]] = issues
    for parent_index, request in enumerate(manifest["parents"]):
        descriptor = request["descriptor"]
        try:
            if parent_profile == "legacy_v1":
                inventory = read_parent_row_witnesses(descriptor, expected_descriptor_sha256=descriptor_sha256(descriptor), row_ordinals=request["row_ordinals"])
            else:
                inventory = _verified_page_parent(request, parent_page_inputs[parent_index])
        except FileNotFoundError:
            inventory = None; file_issues.append({"code": "source_parent_file_unavailable", "sha256": descriptor["sha256"]})
        except _UnsupportedParentDecodedProfile as exc:
            inventory = None; file_issues.append({"code": "source_parent_decoded_profile_unsupported",
                "sha256": descriptor["sha256"], "reason": str(exc), "decoded_profile": exc.details,
                "requested_row_ordinals": deepcopy(request["row_ordinals"]),
                "expected_row_sha256s": deepcopy(request["expected_row_sha256s"])})
        if inventory is not None:
            _need([r["raw_row_sha256"] for r in inventory["rows"]] == request["expected_row_sha256s"], "independent selected parent row hashes differ")
        inventories[descriptor["sha256"]] = inventory
    observations = []
    for (source_row, cache), mapping in zip(physical, manifest["records"], strict=True):
        raw = source_row["raw_row"]; source = source_row["source_identity"]; candidates = mapping["report_sha256s"]
        row = {"row_ordinal": source_row["row_ordinal"], "cache_identity": cache,
            "raw_row": deepcopy(raw), "raw_row_sha256": source_row["raw_row_sha256"],
            "record_sha256": source_row["record_sha256"], "source_identity": deepcopy(source),
            "prior_provenance_classification": source_row["classification"], "report_candidates": deepcopy(candidates),
            "status": "unresolved", "issues": [], "local_declaration_checks": {}, "producer_row_witness": None,
            "parent_row_witness": None, "selected_original_occurrence": None, "governing_source_binding": None,
            "revision_equivalence_inferred": False, "authority": dict(AUTHORITY)}
        issues = row["issues"]
        if source_row["classification"] == "exact_authored_projection_match":
            issues.append({"code": "authored_projection_not_historical_execution"})
        if not candidates: issues.append({"code": "producer_report_witness_not_supplied"})
        elif len(candidates) != 1: issues.append({"code": "multiple_producer_report_candidates", "count": len(candidates)})
        else:
            report_sha = candidates[0]; report = reports[report_sha]
            if report is None: issues.extend(deepcopy(report_issues[report_sha]))
            else:
                pointer = raw.get("source_target_artifact_pointer")
                match = re.fullmatch(r"/rows/(0|[1-9][0-9]*)/logic_target_observation", pointer) if type(pointer) is str else None
                if raw.get("source_target_artifact_sha256") != report_sha or match is None:
                    issues.append({"code": "exact_cache_to_producer_reference_missing_or_mismatched"})
                else:
                    position = int(match.group(1)); matching_rows = [i for i, r in enumerate(report["rows"]) if r.get("source_span_id") == source["source_span_id"]]
                    if len(matching_rows) > 1: issues.append({"code": "multiple_producer_rows_for_source_identity", "ordinals": matching_rows})
                    elif position >= len(report["rows"]): issues.append({"code": "producer_pointer_row_missing"})
                    else:
                        producer = report["rows"][position]
                        campaign = report.get("campaign"); cache_provenance = raw.get("provenance")
                        checks = {"source_projection_complete": all(type(source.get(k)) is str and bool(source[k].strip())
                                for k in ("source_span_id", "legal_id", "source_text"))
                                and type(source.get("source_sha256_observation")) is str
                                and bool(_SHA.fullmatch(source["source_sha256_observation"])),
                            "source_span_id": producer.get("source_span_id") == source["source_span_id"],
                            "source_text": producer.get("text") == source["source_text"],
                            "source_sha256": producer.get("source_sha256") == source["source_sha256_observation"]
                                == hashlib.sha256(str(source["source_text"]).encode()).hexdigest(),
                            "legal_id": producer.get("legal_id") == source["legal_id"],
                            "batch_id": type(campaign) is dict and type(cache_provenance) is dict
                                and type(cache_provenance.get("batch_id")) is str and bool(cache_provenance["batch_id"].strip())
                                and campaign.get("batch_id") == cache_provenance["batch_id"]}
                        row["local_declaration_checks"].update(checks)
                        row["producer_row_witness"] = {"report_sha256": report_sha, "row_ordinal": position,
                            "json_pointer": "/rows/" + str(position), "complete_row_sha256": _digest(producer),
                            "unknown_fields_retained_in_complete_pinned_report": True}
                        if not all(checks.values()): issues.append({"code": "producer_source_declaration_mismatch"})
                        parent = producer.get("source_parent"); ordinal = producer.get("source_section_offset")
                        if type(parent) is not dict or type(ordinal) is not int or ordinal < 0:
                            issues.append({"code": "producer_parent_identity_or_physical_row_missing"})
                        else:
                            descriptor_matches = [p["descriptor"] for p in manifest["parents"] if p["descriptor"]["sha256"] == parent.get("sha256")]
                            if len(descriptor_matches) != 1: issues.append({"code": "independent_parent_descriptor_missing_or_multiple"})
                            else:
                                descriptor = descriptor_matches[0]; inventory = inventories[descriptor["sha256"]]
                                parent_checks = {"parent_" + k: parent.get(pk) == descriptor[k] for k, pk in
                                    (("repository", "repository_id"), ("revision", "revision"), ("path_in_repo", "path_in_repo"), ("bytes", "bytes"), ("sha256", "sha256"))}
                                row["local_declaration_checks"].update(parent_checks)
                                if not all(parent_checks.values()): issues.append({"code": "producer_parent_descriptor_mismatch"})
                                if inventory is None:
                                    issues.extend(deepcopy([issue for issue in file_issues if issue["sha256"] == descriptor["sha256"]]))
                                selected = [r for r in inventory["rows"] if r["row_ordinal"] == ordinal] if inventory is not None else []
                                if len(selected) != 1: issues.append({"code": "independent_physical_parent_row_missing_or_multiple"})
                                else:
                                    selected = selected[0]; body = selected["raw_row"]
                                    title, section = body.get("title_number"), body.get("section_number")
                                    title_ok = (type(title) is int and title > 0) or (type(title) is str and re.fullmatch(r"[1-9][0-9]*", title))
                                    section_ok = (type(section) is int and section > 0) or (type(section) is str and bool(section.strip()))
                                    legal_id = f"usc:us:{title}:{section}" if title_ok and section_ok else None
                                    identity_checks = {"parent_entry_cid": type(producer.get("entry_cid")) is str and bool(producer["entry_cid"])
                                        and body.get("ipfs_cid") == producer["entry_cid"],
                                        "parent_literal_legal_id": legal_id is not None and legal_id == source["legal_id"],
                                        "parent_raw_text_present": type(body.get("text")) is str and bool(body["text"])}
                                    row["local_declaration_checks"].update(identity_checks)
                                    row["parent_row_witness"] = {"parent_sha256": descriptor["sha256"], "parent_revision": descriptor["revision"],
                                        "row_ordinal": ordinal, "complete_row_sha256": selected["raw_row_sha256"],
                                        "entry_cid": body.get("ipfs_cid"), "literal_legal_id": legal_id,
                                        "text_sha256": hashlib.sha256(body["text"].encode()).hexdigest() if identity_checks["parent_raw_text_present"] else None}
                                    if not all(identity_checks.values()): issues.append({"code": "physical_parent_row_identity_mismatch"})
                        if not issues and all(row["local_declaration_checks"].values()):
                            row["status"] = "verified_local_report_parent_declarations_only"
        observations.append(row)
    report = {"schema": SCHEMA, "provenance_report_sha256s": deepcopy(expected_provenance_report_sha256s),
        "expected_record_sha256s": deepcopy(ids), "witness_manifest": manifest,
        "witness_manifest_sha256": expected_witness_manifest_sha256,
        "producer_report_observations": [{"descriptor": d, "issues": report_issues[d["sha256"]]} for d in manifest["reports"]],
        "parent_row_inventories": list(inventories.values()), "parent_file_issues": file_issues,
        "row_count": len(observations), "rows": observations,
        "status_counts": dict(Counter(r["status"] for r in observations)), "population_complete": True,
        "coverage_scope": "exact_independently_pinned_supplied_physical_cache_rows_and_declared_witnesses_only",
        "whole_cache_coverage_verified": False, "authority": dict(AUTHORITY)}
    report["lineage_sha256"] = _digest(report)
    _wire(report)
    return report


def reconcile_producer_lineage(provenance_reports, *, expected_provenance_report_sha256s,
        expected_record_sha256s, witness_manifest, expected_witness_manifest_sha256):
    """Replay the original v1 declaration contract with its original decoder."""
    return _reconcile_producer_lineage(provenance_reports,
        expected_provenance_report_sha256s=expected_provenance_report_sha256s,
        expected_record_sha256s=expected_record_sha256s, witness_manifest=witness_manifest,
        expected_witness_manifest_sha256=expected_witness_manifest_sha256)


def validate_producer_lineage(report, provenance_reports, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(lineage_report_sha256(report) == expected_report_sha256, "independent complete lineage report pin differs")
    expected = reconcile_producer_lineage(provenance_reports, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "lineage report differs from independent full regeneration")
    return {"valid": True, "row_count": report["row_count"], "all_legal_and_execution_authority_false": True}


__all__ = ["ProducerLineageError", "descriptor_sha256", "read_parent_row_witnesses",
    "witness_manifest_sha256", "lineage_report_sha256", "reconcile_producer_lineage", "validate_producer_lineage"]
