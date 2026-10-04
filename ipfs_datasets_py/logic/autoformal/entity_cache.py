"""Queue knowledge-graph entities for autoformalization.

This cache is separate from the sentence-span cache. An entity row is a
title, section, or document node prepared for a later autoformal worker.
A queued entity is not a legal admit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import threading
from contextlib import contextmanager
from functools import wraps
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "uscode-autoformal-entity-cache/v2"
DATASET_ID = "justicedao/ipfs_uscode"
MAX_LABEL = 2_000
MAX_PROPERTIES = 8_192
MAX_BATCH = 512

_DDL = """
CREATE TABLE IF NOT EXISTS entity_queue (
    entity_id VARCHAR PRIMARY KEY,
    entity_type VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    properties_json VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    claim_worker VARCHAR,
    claim_token VARCHAR,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL,
    context_json VARCHAR NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS agent_lease (
    agent_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    heartbeat VARCHAR NOT NULL,
    claimed_count INTEGER NOT NULL,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS task_board (
    task_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR,
    entity_type VARCHAR,
    label VARCHAR,
    status VARCHAR NOT NULL,
    work_kind VARCHAR NOT NULL,
    owner_agent VARCHAR,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS cache_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS inconsistency (
    inconsistency_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR,
    span_id VARCHAR,
    term_id VARCHAR,
    kind VARCHAR NOT NULL,
    evidence VARCHAR NOT NULL,
    admitted BOOLEAN NOT NULL,
    formalized BOOLEAN NOT NULL
);
"""


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def mentions_defined_term(text: str) -> bool:
    lowered = str(text or "").lower()
    return "as defined in" in lowered or "for purposes of this" in lowered


def _span_status(span: Mapping[str, Any]) -> str:
    """Legacy rows omit status and stay attachable. Pending and gap do not."""

    status = str(span.get("status") or "").strip().lower()
    if status in {"pending", "gap", "sealed", "unsealed"}:
        return status
    if span.get("sealed") is False:
        return "unsealed"
    return "sealed"


def _span_rule(span: Mapping[str, Any]) -> Mapping[str, Any] | None:
    rule = span.get("rule")
    if isinstance(rule, str):
        try:
            rule = json.loads(rule or "{}")
        except json.JSONDecodeError:
            return None
    if isinstance(rule, Mapping):
        return rule
    raw = span.get("rule_json")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, Mapping) else None


def _open_stitch_slots(span: Mapping[str, Any]) -> list[str]:
    rule = _span_rule(span)
    if rule is None:
        return []
    from .family_supervision import open_slots, stitch_symbol

    span_id = str(span.get("source_span_id") or span.get("id") or "")
    return [
        stitch_symbol(span_id, slot)
        for slot in open_slots(str(rule.get("actor") or ""), str(rule.get("action") or ""))
    ]


def _finding(context: Mapping[str, Any], *, kind: str, evidence: str, span_id: str = "", term_id: str = "") -> dict[str, str]:
    return {
        "entity_id": str(context.get("entity_id") or ""),
        "evidence": evidence,
        "kind": kind,
        "span_id": span_id,
        "term_id": term_id,
    }


def inconsistencies_for_section(
    context: Mapping[str, Any],
    spans: Sequence[Mapping[str, Any]],
    terms: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Compare one section neighborhood with its spans. Not an admit."""

    from .lean_units import MAX_CLAUSES, MAX_TERM_STATUTES

    legal_id = str(context.get("span_legal_id") or "")
    contained = {str(item) for item in context.get("contained_span_ids") or []}
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    matching = [
        span
        for span in spans
        if isinstance(span, Mapping) and str(span.get("legal_id") or "") == legal_id
    ]
    pending = [span for span in matching if _span_status(span) in {"pending", "unsealed"}]
    if pending:
        for span in pending:
            found.append(
                _finding(
                    context,
                    kind="section_not_ready",
                    evidence="span is still pending",
                    span_id=str(span.get("source_span_id") or span.get("id") or ""),
                )
            )
        return found
    sealed_clauses: list[Mapping[str, Any]] = []
    for span in matching:
        if _span_status(span) == "gap":
            continue
        span_id = str(span.get("source_span_id") or span.get("id") or "")
        seen.add(span_id)
        sealed_clauses.append(span)
        text = str(span.get("text") or "")
        decompiled = str(span.get("decompiled") or "")
        if span_id and span_id not in contained:
            found.append(
                _finding(
                    context,
                    kind="span_not_in_section",
                    evidence="span legal id is missing from the section neighborhood",
                    span_id=span_id,
                )
            )
        if mentions_defined_term(text) and not context.get("definition_targets") and "unresolved_citation" not in (
            context.get("reasons") or []
        ):
            found.append(
                _finding(
                    context,
                    kind="missing_definition_closure",
                    evidence="span uses a defined term and the section has no definition closure",
                    span_id=span_id,
                )
            )
        if mentions_defined_term(text) and decompiled and "defined" not in decompiled.lower():
            found.append(
                _finding(
                    context,
                    kind="capture_not_in_decompilation",
                    evidence="decompiler dropped a defined term",
                    span_id=span_id,
                )
            )
    for span_id in sorted(contained - seen):
        found.append(
            _finding(
                context,
                kind="missing_span_row",
                evidence="contained span has no span row",
                span_id=span_id,
            )
        )
    ordered = sorted(sealed_clauses, key=lambda span: str(span.get("source_span_id") or span.get("id") or ""))
    extra = ordered[MAX_CLAUSES:]
    if extra:
        overflow_ids = [str(span.get("source_span_id") or span.get("id") or "") for span in extra]
        found.append(
            _finding(
                context,
                kind="lean_unit_overflow",
                evidence="clauses exceed the render cap: " + ",".join(overflow_ids),
                span_id=overflow_ids[0],
            )
        )
    targets = {str(item) for item in context.get("definition_targets") or [] if str(item)}
    for term in terms or []:
        if not isinstance(term, Mapping):
            continue
        statute_ids = [str(item) for item in term.get("statute_ids") or [] if str(item)]
        if not statute_ids or (legal_id not in statute_ids and not (set(statute_ids) & targets)):
            continue
        overflow_ids = statute_ids[MAX_TERM_STATUTES:]
        if overflow_ids and statute_ids[0] == legal_id:
            found.append(
                _finding(
                    context,
                    kind="lean_unit_overflow",
                    evidence="statutes exceed the render cap: " + ",".join(overflow_ids),
                    term_id=str(term.get("term_id") or ""),
                )
            )
    return found


_INCONSISTENCY_REASONS = {
    "capture_not_in_decompilation": "capture_not_in_decompilation",
    "lean_fingerprint_mismatch": "strict_roundtrip_failed",
    "missing_definition_closure": "compiler_abstain:cross_references",
}


def propagation_tasks(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Turn inconsistency rows into edit and train todos. Does not claim."""

    from .supervisor_dispatch import classify_work

    tasks: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("kind") or "")
        reason = _INCONSISTENCY_REASONS.get(kind, kind)
        for work_kind in classify_work(reason):
            tasks.append(
                {
                    "admitted": False,
                    "entity_id": str(row.get("entity_id") or ""),
                    "evidence": str(row.get("evidence") or ""),
                    "formalized": False,
                    "reason": reason,
                    "span_id": str(row.get("span_id") or ""),
                    "term_id": str(row.get("term_id") or ""),
                    "work_kind": work_kind,
                }
            )
    return tasks


def proof_sources_for_section(
    context: Mapping[str, Any],
    spans: Sequence[Mapping[str, Any]],
    terms: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Statute Lean from sealed clauses. Term Lean from term groups inside the closure."""

    from .lean_units import statute_lean_unit, term_lean_unit

    legal_id = str(context.get("span_legal_id") or "")
    contained = {str(item) for item in context.get("contained_span_ids") or []}
    clauses = []
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        span_id = str(span.get("source_span_id") or span.get("id") or "")
        if span_id not in contained or _span_status(span) != "sealed":
            continue
        clauses.append(span)
    clauses.sort(key=lambda span: str(span.get("source_span_id") or span.get("id") or ""))
    statute = statute_lean_unit(legal_id, clauses)
    targets = [str(item) for item in context.get("definition_targets") or [] if str(item)]
    allowed = {legal_id, *targets}
    term_units: list[dict[str, Any]] = []
    for term in terms or []:
        if not isinstance(term, Mapping):
            continue
        statute_ids = [str(item) for item in term.get("statute_ids") or [] if str(item)]
        if legal_id not in statute_ids and not (set(statute_ids) & set(targets)):
            continue
        restricted = [item for item in statute_ids if item in allowed]
        unit = term_lean_unit(
            str(term.get("kind") or ""),
            str(term.get("value") or ""),
            statute_ids=restricted,
            term_id=str(term.get("term_id") or ""),
        )
        term_units.append(unit)
    overflows = []
    if statute["overflow_ids"]:
        overflows.append({"kind": "lean_unit_overflow", "overflow_ids": statute["overflow_ids"], "term_id": ""})
    for unit in term_units:
        if unit["overflow_ids"]:
            overflows.append(
                {
                    "kind": "lean_unit_overflow",
                    "overflow_ids": unit["overflow_ids"],
                    "term_id": unit["term_id"],
                }
            )
    return {
        "admitted": False,
        "formalized": False,
        "overflow": overflows,
        "statute_lean": statute["lean"],
        "term_lean": "".join(unit["lean"] for unit in term_units),
        "term_units": term_units,
    }


def term_category(kind: str, value: str) -> str:
    """Map a compiler term onto the meta-ontology. Lexicon wins when it matches."""

    from .meta_ontology import classify_surface

    found = classify_surface(value)
    key = str(kind or "")
    if key in {"conditions", "exceptions", "temporal", "qualifiers"}:
        return found if found == "state" else ""
    if found:
        return found
    return {"actor": "participant", "action": "act", "object": "object", "modality": "deontic"}.get(key, "")


def work_kind_for(entity_type: str) -> str:
    kind = str(entity_type or "").strip() or "entity"
    return {
        "usc_title": "title_entity",
        "section": "section_entity",
        "legal_document": "legal_document_entity",
        "document": "document_entity",
    }.get(kind, "kg_entity")



MAX_ENTITIES = 250_000
MAX_AGENTS = 4_096
MAX_INPUT_FILE_BYTES = 512 * 1024**2
MAX_INPUT_ROWS = 2_000_000
MAX_RESUME_FILE_BYTES = 128 * 1024**2
MAX_RESUME_ROWS = 2 * MAX_ENTITIES + MAX_AGENTS + 1
# Aggregate validation work, not resident memory. Measured v1 JSON was 260 MB.
MAX_RESUME_DECODED_BYTES = 512 * 1024**2
MAX_RESUME_BATCH_BYTES = 8 * 1024**2
MAX_RESUME_ROW_GROUP_BYTES = 32 * 1024**2
# Operational writer grouping only; v2 rows and reader limits remain unchanged.
MAX_RESUME_WRITE_GROUP_ROWS = 1024
INPUT_SCHEMA = 'entity-cache-inputs/v2'
BINDING_SCHEMA = 'entity-cache-binding/v2' 
MAX_CONTEXT_BYTES = 2 * 1024**2
MAX_DEFINITION_TARGETS = 4096
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")
_RESUME_FIELDS = (
    "schema_version", "record_kind", "dataset_id", "agent_id", "role", "heartbeat",
    "entities", "source_parquet", "entity_id", "entity_type", "label", "status",
    "work_kind", "claim_worker", "claim_token", "source_sha256", "properties_json",
    "context_json", "admitted", "formalized", "input_id", "input_manifest_json",
)


class EntityCacheError(ValueError):
    """Conflicting, unfenced or unverifiable entity-cache input."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EntityCacheError(message)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _string(value: Any, maximum: int, name: str, *, empty: bool = False) -> str:
    _require(type(value) is str and "\x00" not in value and len(value.encode("utf-8")) <= maximum
             and (empty or bool(value.strip())), "invalid " + name)
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _object(raw: str, maximum: int, name: str) -> dict:
    _string(raw, maximum, name, empty=True)
    try:
        value = json.loads(raw or "{}", object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(EntityCacheError("nonfinite JSON")))
    except (ValueError, TypeError, RecursionError) as error:
        raise EntityCacheError("invalid " + name) from error
    _require(type(value) is dict, "invalid " + name)
    return value


def _entity_record(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    _require(isinstance(row, Mapping), "entity must be an object")
    for left, right in (("id", "entity_id"), ("type", "entity_type")):
        _require(not (row.get(left) and row.get(right)) or row[left] == row[right], "conflicting entity aliases")
    eid = _string(row.get("id") or row.get("entity_id"), 1024, "entity id")
    _require(eid == eid.strip(), "entity id must be normalized")
    kind = _string(row.get("type") or row.get("entity_type") or "entity", 128, "entity type")
    label = _string(row.get("label"), MAX_LABEL, "entity label")
    properties = _string(row.get("properties_json", ""), MAX_PROPERTIES, "entity properties", empty=True)
    _object(properties, MAX_PROPERTIES, "entity properties")
    # This is a derived immutable record identity, not an official-source claim.
    payload = {"schema_version": SCHEMA, "dataset_id": DATASET_ID, "entity_id": eid,
               "entity_type": kind, "label": label, "properties_json": properties}
    return eid, kind, label, properties, _sha(_json(payload))


def _file_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _resume_digest(stream):
    digest, size = hashlib.sha256(), 0
    while chunk := stream.read(min(1024**2, MAX_RESUME_FILE_BYTES - size + 1)):
        size += len(chunk)
        _require(size <= MAX_RESUME_FILE_BYTES, "resume file grew beyond byte bound")
        digest.update(chunk)
    return digest.hexdigest()


def _resume_file(path: Path):
    path = Path(path).absolute()
    _require(path.resolve() == path, "resume file path is aliased")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_RESUME_FILE_BYTES,
                 "resume file exceeds regular-file bound")
        return path, os.fdopen(fd, "rb"), info
    except BaseException:
        os.close(fd)
        raise


def _resume_current(path: Path, expected) -> None:
    path, stream, before = _resume_file(path)
    with stream:
        digest = _resume_digest(stream)
        after = os.fstat(stream.fileno())
    _require((_file_identity(before), digest) == expected
             and _file_identity(before) == _file_identity(after) == _file_identity(path.lstat())
             and path.resolve() == path, "resume file changed during merge")



def _input_manifest(value):
    _require(type(value) is dict and set(value) == {
        "schema_version", "dataset_id", "entity_identity_schema", "entities", "relationships"}, "invalid input manifest")
    _require(value["schema_version"] == INPUT_SCHEMA and value["dataset_id"] == DATASET_ID
             and value["entity_identity_schema"] == SCHEMA, "foreign input manifest")
    for name in ("entities", "relationships"):
        ref = value[name]
        _require(type(ref) is dict and set(ref) == {"sha256", "bytes", "row_count"}, "invalid input descriptor")
        _require(type(ref["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]), "invalid input digest")
        _require(type(ref["bytes"]) is int and 0 < ref["bytes"] <= MAX_INPUT_FILE_BYTES, "input bytes exceed bound")
        _require(type(ref["row_count"]) is int and 0 <= ref["row_count"] <= MAX_INPUT_ROWS, "input rows exceed bound")
    return json.loads(_json(value))


def _resume_schema():
    import pyarrow as pa
    return pa.schema([pa.field(name, pa.int64() if name == "entities" else
                              pa.bool_() if name in {"admitted", "formalized"} else pa.string(), nullable=False)
                      for name in _RESUME_FIELDS])


def _blank_resume(kind, binding):
    result = {name: "" for name in _RESUME_FIELDS}
    result.update(schema_version=SCHEMA, record_kind=kind, entities=0, admitted=False,
                  formalized=False, input_id=binding["input_id"])
    return result


def _validate_resume_row(row, binding):
    _require(type(row) is dict and set(row) == set(_RESUME_FIELDS), "invalid resume fields")
    _require(row["schema_version"] == SCHEMA and row["input_id"] == binding["input_id"], "resume binding differs")
    _require(row["admitted"] is False and row["formalized"] is False, "resume claims authority")
    for name in _RESUME_FIELDS:
        if name not in {"entities", "admitted", "formalized"}:
            _string(row[name], MAX_CONTEXT_BYTES, "resume " + name, empty=True)
    _require(type(row["entities"]) is int and 0 <= row["entities"] <= MAX_INPUT_ROWS, "invalid resume count")
    kind = row["record_kind"]
    if kind == "meta":
        allowed = {"dataset_id", "entities", "input_manifest_json"}
        _require(row["dataset_id"] == DATASET_ID and row["input_manifest_json"] == _json(binding["input_manifest"]),
                 "resume manifest differs")
        _require(row["entities"] <= binding["input_manifest"]["entities"]["row_count"], "remote cursor exceeds source")
    elif kind == "entity":
        record = _entity_record(row)
        _require(row["source_sha256"] == record[4], "remote immutable entity differs")
        _require(row["status"] in {"pending", "claimed", "prepared"}, "invalid entity status")
        context = _object(row["context_json"], MAX_CONTEXT_BYTES, "entity context")
        _require(row["context_json"] == _json(context), "context must be canonical JSON")
        if row["status"] == "claimed":
            _string(row["claim_worker"], 256, "claim worker")
            _require(_TOKEN.fullmatch(row["claim_token"]), "invalid claim token")
        else:
            _require(row["claim_worker"] == row["claim_token"] == "", "unclaimed row retains claim")
        _require(row["agent_id"] == row["claim_worker"], "remote owner differs")
        allowed = {"agent_id", "entity_id", "entity_type", "label", "status", "claim_worker",
                   "claim_token", "source_sha256", "properties_json", "context_json"}
    elif kind == "agent":
        _string(row["agent_id"], 256, "agent id")
        _string(row["role"], 128, "agent role")
        _require(row["dataset_id"] == DATASET_ID and row["heartbeat"].isascii()
                 and row["heartbeat"].isdigit(), "invalid agent metadata")
        allowed = {"dataset_id", "agent_id", "role", "heartbeat", "entities"}
    elif kind == "board":
        _string(row["entity_id"], 1024, "board entity")
        allowed = {"agent_id", "entity_id", "entity_type", "label", "status", "work_kind", "claim_worker"}
    else:
        raise EntityCacheError("unknown resume record kind")
    for name in _RESUME_FIELDS:
        if name not in allowed | {"schema_version", "record_kind", "input_id", "admitted", "formalized"}:
            _require(row[name] == (0 if name == "entities" else ""), "unexpected resume field: " + name)
    return row


def _stage_resume(db, path, binding):
    """Validate a complete snapshot in bounded Arrow batches and SQL staging.

    The caller owns the transaction; no remote entity or owner is installed.
    The returned temp relation is only an observation, never lease authority.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    path, stream, before = _resume_file(Path(path))
    db.execute("DROP TABLE IF EXISTS _entity_resume_stage")
    columns = ','.join('"'+name+'" '+('BIGINT' if name == 'entities' else
                        'BOOLEAN' if name in {'admitted','formalized'} else 'VARCHAR')+' NOT NULL'
                       for name in _RESUME_FIELDS)
    db.execute("CREATE TEMP TABLE _entity_resume_stage (" + columns + ")")
    count = decoded = 0
    with stream:
        digest = _resume_digest(stream)
        stream.seek(0)
        parquet = pq.ParquetFile(stream)
        try:
            _require(parquet.schema_arrow.equals(_resume_schema(), check_metadata=False), "unsupported resume schema; regenerate v2")
            _require(1 <= parquet.metadata.num_rows <= 2 * MAX_ENTITIES + MAX_AGENTS + 1, "resume row count exceeds bound")
            expanded = 0
            for index in range(parquet.metadata.num_row_groups):
                size = parquet.metadata.row_group(index).total_byte_size
                _require(0 <= size <= MAX_RESUME_ROW_GROUP_BYTES, "resume row group exceeds bound")
                expanded += size
            _require(expanded <= MAX_RESUME_DECODED_BYTES, "resume expanded bytes exceed bound")
            for batch in parquet.iter_batches(batch_size=64, use_threads=False):
                _require(batch.nbytes <= MAX_RESUME_BATCH_BYTES, "resume Arrow batch exceeds bound")
                records = batch.to_pylist()
                batch_bytes = 0
                for row in records:
                    _validate_resume_row(row, binding)
                    batch_bytes += len(_json(row).encode("utf-8"))
                decoded += batch_bytes
                count += len(records)
                _require(batch_bytes <= MAX_RESUME_BATCH_BYTES and decoded <= MAX_RESUME_DECODED_BYTES,
                         "resume JSON bytes exceed bound")
                # Register only this bounded batch; do not execute other queries with
                # an active fetchmany cursor on the owner connection.
                table = pa.Table.from_pylist(records, schema=_resume_schema())
                db.register('_entity_resume_batch', table)
                try:
                    db.execute("INSERT INTO _entity_resume_stage SELECT * FROM _entity_resume_batch")
                finally:
                    db.unregister('_entity_resume_batch')
                del table, records, batch
            _require(count == parquet.metadata.num_rows, "resume physical count differs")
        finally:
            try:
                parquet.close()
            finally:
                del parquet
        after = os.fstat(stream.fileno())
    _require(_file_identity(before) == _file_identity(after) == _file_identity(path.lstat())
             and path.resolve() == path, "resume changed during validation")
    kinds = dict(db.execute("SELECT record_kind,count(*) FROM _entity_resume_stage GROUP BY 1").fetchall())
    _require(kinds.get('meta') == 1 and kinds.get('entity',0) == kinds.get('board',0)
             and kinds.get('entity',0) <= MAX_ENTITIES and kinds.get('agent',0) <= MAX_AGENTS,
             "resume logical count differs")
    for kind, key in (("entity","entity_id"),("board","entity_id"),("agent","agent_id")):
        duplicates = db.execute("SELECT count(*) FROM (SELECT " + key +
            " FROM _entity_resume_stage WHERE record_kind=? GROUP BY 1 HAVING count(*)<>1)", [kind]).fetchone()[0]
        _require(not duplicates, "duplicate resume row")
    mismatch = db.execute("""SELECT count(*) FROM
        (SELECT * FROM _entity_resume_stage WHERE record_kind='board') b FULL OUTER JOIN
        (SELECT * FROM _entity_resume_stage WHERE record_kind='entity') e USING(entity_id)
        WHERE b.entity_id IS NULL OR e.entity_id IS NULL OR
        b.entity_type<>e.entity_type OR b.label<>e.label OR b.status<>e.status OR
        b.agent_id<>e.agent_id OR b.claim_worker<>e.claim_worker OR b.work_kind <>
        CASE e.entity_type WHEN 'usc_title' THEN 'title_entity' WHEN 'section' THEN 'section_entity'
        WHEN 'legal_document' THEN 'legal_document_entity' WHEN 'document' THEN 'document_entity' ELSE 'kg_entity' END
        """).fetchone()[0]
    _require(not mismatch, "board closure differs")
    _require(not db.execute("""SELECT count(*) FROM _entity_resume_stage e WHERE e.record_kind='entity'
        AND e.status='claimed' AND NOT EXISTS (SELECT 1 FROM _entity_resume_stage a
        WHERE a.record_kind='agent' AND a.agent_id=e.claim_worker)""").fetchone()[0], "claim agent missing")
    _require(not db.execute("""SELECT count(*) FROM _entity_resume_stage a WHERE a.record_kind='agent'
        AND a.entities<>(SELECT count(*) FROM _entity_resume_stage e
        WHERE e.record_kind='entity' AND e.status='claimed' AND e.claim_worker=a.agent_id)""").fetchone()[0],
        "agent claim count differs")
    cursor = db.execute("SELECT entities FROM _entity_resume_stage WHERE record_kind='meta'").fetchone()[0]
    _require(kinds.get('entity',0) <= cursor, "resume entity count exceeds physical cursor")
    return path, (_file_identity(before), digest), kinds, cursor




def _owned_method(function):
    @wraps(function)
    def call(self,*args,**kwargs):
        self._check_owner()
        return function(self,*args,**kwargs)
    return call


def _atomic_method(function):
    @wraps(function)
    def call(self,*args,**kwargs):
        with self._transaction():
            return function(self,*args,**kwargs)
    return call


class EntityCache:
    """One DuckDB owner for the entity queue. Other agents claim, they do not share the lock."""

    def __init__(self, path: str | Path):
        import duckdb
        destination = Path(path).absolute()
        _require(destination.resolve() == destination, "cache path is aliased")
        self.path = destination
        self._owner = (os.getpid(), threading.get_ident())
        self._closed = False
        self._transaction_depth = 0
        self._transaction_failed = False
        if destination.exists():
            _require(destination.is_file(), "cache is not a regular file")
            identity = destination.stat()
            # No CREATE/ALTER/writer connection before exact v2 schema identity.
            reader = duckdb.connect(str(destination), read_only=True, config={"threads": 1})
            try:
                self._validate_schema(reader)
            finally:
                reader.close()
            _require((identity.st_dev,identity.st_ino) == (destination.stat().st_dev,destination.stat().st_ino),
                     "cache changed before owner open")
            self._db = duckdb.connect(str(destination), config={"threads": 1, "memory_limit": "256MB"})
            try:
                self._validate_schema(self._db)
            except BaseException:
                self._db.close()
                raise
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._db = duckdb.connect(str(destination), config={"threads": 1, "memory_limit": "256MB"})
            with self._transaction():
                for statement in _DDL.split(';'):
                    if statement.strip():
                        self._db.execute(statement)
                self._db.execute("CREATE INDEX entity_queue_status ON entity_queue(status)")
                columns = self._schema_columns(self._db)
                self._set_meta('schema_identity', _json({'schema_version':SCHEMA,'ddl_sha256':_sha(_DDL),'columns':columns}))

    @staticmethod
    def _schema_columns(db):
        return [list(row) for row in db.execute("SELECT table_name,column_name,data_type,is_nullable,ordinal_position "
            "FROM information_schema.columns WHERE table_schema='main' ORDER BY table_name,ordinal_position").fetchall()]

    @staticmethod
    def _expected_columns():
        result=[]
        for table,body in re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);',_DDL,re.S):
            for ordinal,definition in enumerate(body.split(','),1):
                parts=definition.strip().split()
                result.append([table,parts[0],parts[1],
                               'NO' if 'NOT NULL' in definition or 'PRIMARY KEY' in definition else 'YES',ordinal])
        return sorted(result,key=lambda row:(row[0],row[4]))

    @staticmethod
    def _schema_constraints(db):
        rows=db.execute("SELECT table_name,constraint_type,constraint_column_names FROM duckdb_constraints() "
                        "WHERE schema_name='main' AND constraint_type NOT IN ('NOT NULL','NOT_NULL')").fetchall()
        return sorted([[table,kind,list(columns)] for table,kind,columns in rows])

    @staticmethod
    def _expected_constraints():
        result=[]
        for table,body in re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);',_DDL,re.S):
            for definition in body.split(','):
                if 'PRIMARY KEY' in definition:
                    result.append([table,'PRIMARY KEY',[definition.strip().split()[0]]])
        return sorted(result)

    @classmethod
    def _validate_schema(cls, db):
        try:
            row = db.execute("SELECT value FROM cache_meta WHERE key='schema_identity'").fetchone()
            _require(row is not None, "cache has no v2 identity; create a separate v2 cache")
            record = _object(row[0], 65536, 'schema identity')
            _require(_json(record) == _json({'schema_version':SCHEMA,'ddl_sha256':_sha(_DDL),'columns':cls._expected_columns()})
                     and cls._schema_columns(db) == cls._expected_columns()
                     and cls._schema_constraints(db) == cls._expected_constraints(),
                     "cache schema differs; automatic migration is forbidden")
        except EntityCacheError:
            raise
        except Exception as error:
            raise EntityCacheError('cache is not a v2 cache; no migration performed') from error

    def _check_owner(self):
        _require(not self._closed and self._owner == (os.getpid(),threading.get_ident()), "foreign or closed cache owner")

    @contextmanager
    def _transaction(self):
        self._check_owner()
        if self._transaction_depth:
            try:
                yield
            except BaseException:
                self._transaction_failed=True
                raise
            return
        self._db.execute('BEGIN')
        self._transaction_depth=1
        self._transaction_failed=False
        try:
            yield
            _require(not self._transaction_failed,'nested operation failed; transaction cannot commit')
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise
        finally:
            self._transaction_depth=0
            self._transaction_failed=False

    def _require_bound_context(self):
        if not self._meta('input_binding'): return None
        binding=self._binding()
        _require(binding['next_ordinal']==binding['input_manifest']['entities']['row_count'],
                 'bound preparation requires complete sealed containment')
        raw=self._meta('containment_receipt')
        _require(bool(raw),'bound preparation requires complete sealed containment')
        seal=_object(raw,8192,'containment receipt')
        _require(set(seal)=={'input_id','result'} and seal['input_id']==binding['input_id'], 'containment seal binding differs')
        result=seal['result']
        _require(type(result) is dict and set(result)=={'admitted','formalized','prepared','containment'}
                 and result['admitted'] is False and result['formalized'] is False,'invalid containment result')
        counts=result['containment']
        _require(type(counts) is dict and set(counts)=={'section_spans','title_scope','provenance_excluded','definition_hops'}
                 and all(type(value) is int and value>=0 for value in counts.values())
                 and counts['definition_hops']==0,'invalid containment counts')
        logical=self._db.execute('SELECT count(*) FROM entity_queue').fetchone()[0]
        _require(sum(counts.values())==logical and type(result['prepared']) is int and 0<=result['prepared']<=logical,
                 'containment count differs')
        return result

    def _reject_section_claims(self):
        _require(not self._db.execute("SELECT count(*) FROM entity_queue WHERE entity_type='section' AND status='claimed'").fetchone()[0],
                 'active section claims prevent context changes')

    def _binding(self):
        raw = self._meta('input_binding')
        _require(bool(raw), 'cache inputs are not bound')
        value = _object(raw, 8192, 'input binding')
        _require(set(value) == {'schema_version','input_id','input_manifest','next_ordinal','admitted','formalized'},
                 'invalid input binding fields')
        manifest = _input_manifest(value['input_manifest'])
        _require(value['schema_version'] == BINDING_SCHEMA and value['input_id'] == 'sha256:'+_sha(_json(manifest))
                 and value['admitted'] is False and value['formalized'] is False, 'invalid input binding')
        _require(type(value['next_ordinal']) is int and 0 <= value['next_ordinal'] <= manifest['entities']['row_count'],
                 'invalid physical cursor')
        return value

    @_owned_method
    def bind_inputs(self, manifest, resume: bool):
        manifest = _input_manifest(manifest)
        _require(type(resume) is bool, 'resume must be a boolean')
        with self._transaction():
            if self._meta('input_binding'):
                binding = self._binding()
                _require(binding['input_manifest'] == manifest, 'input artifacts differ; use a separate cache')
                _require(resume or binding['next_ordinal'] == 0, 'existing progress requires explicit resume')
            else:
                _require(not self._db.execute('SELECT count(*) FROM entity_queue').fetchone()[0]
                         and not self._meta('entities_committed') and not self._meta('source_parquet'),
                         'unbound legacy progress cannot be adopted')
                binding = dict(schema_version=BINDING_SCHEMA,input_id='sha256:'+_sha(_json(manifest)),
                               input_manifest=manifest,next_ordinal=0,admitted=False,formalized=False)
                self._set_meta('input_binding',_json(binding))
        return binding

    @_owned_method
    def enqueue_source_batch(self, rows, start: int, end: int, *, verify_inputs):
        _require(callable(verify_inputs), 'source commit guard is required')
        _require(type(start) is int and type(end) is int and isinstance(rows,(list,tuple))
                 and 0 < end-start == len(rows) <= MAX_BATCH, 'invalid physical source batch')
        with self._transaction():
            binding = self._binding()
            _require(binding['next_ordinal'] == start and end <= binding['input_manifest']['entities']['row_count'],
                     'source cursor differs')
            added = self._enqueue_records(rows)
            binding['next_ordinal'] = end
            self._set_meta('input_binding',_json(binding))
            verify_inputs()
        return added

    def _enqueue_records(self, rows):
        import pyarrow as pa
        prepared={}
        for row in rows:
            item=_entity_record(row)
            _require(item[0] not in prepared or prepared[item[0]]==item,'conflicting duplicate entity')
            prepared[item[0]]=item
        if not prepared: return 0
        names=('entity_id','entity_type','label','properties_json','source_sha256')
        table=pa.Table.from_pylist([dict(zip(names,item)) for item in prepared.values()])
        self._db.register('_entity_incoming_batch',table)
        try:
            conflicts=self._db.execute("""SELECT count(*) FROM _entity_incoming_batch n JOIN entity_queue e USING(entity_id)
                WHERE n.entity_type<>e.entity_type OR n.label<>e.label OR n.properties_json<>e.properties_json
                OR n.source_sha256<>e.source_sha256""").fetchone()[0]
            _require(not conflicts,'existing immutable entity differs')
            fresh=self._db.execute('SELECT count(*) FROM _entity_incoming_batch n WHERE NOT EXISTS '
                '(SELECT 1 FROM entity_queue e WHERE e.entity_id=n.entity_id)').fetchone()[0]
            count=self._db.execute('SELECT count(*) FROM entity_queue').fetchone()[0]
            _require(count+fresh<=MAX_ENTITIES,'entity count exceeds bound')
            self._db.execute("INSERT INTO entity_queue (entity_id,entity_type,label,properties_json,source_sha256,status,"
                "claim_worker,claim_token,admitted,formalized,context_json) "
                "SELECT n.entity_id,n.entity_type,n.label,n.properties_json,n.source_sha256,'pending','','',FALSE,FALSE,'{}' "
                "FROM _entity_incoming_batch n WHERE NOT EXISTS (SELECT 1 FROM entity_queue e WHERE e.entity_id=n.entity_id)")
            return int(fresh)
        finally:
            self._db.unregister('_entity_incoming_batch')

    def close(self) -> None:
        if not self._closed:
            self._check_owner()
            self._db.close()
            self._closed = True

    def _meta(self, key: str) -> str:
        row = self._db.execute("SELECT value FROM cache_meta WHERE key = ?", [key]).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
            [key, value],
        )

    @_owned_method
    def checkpoint(self) -> dict[str, Any]:
        self._check_owner()
        binding = self._binding()
        return {**binding, 'entities':binding['next_ordinal'], 'dataset_id':DATASET_ID,
                **self.stats()}

    @_owned_method
    def save_checkpoint(self, *, entities: int, source: str) -> None:
        raise EntityCacheError('path-only checkpoints are forbidden; use enqueue_source_batch')

    @_owned_method
    def enqueue(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Unbound local helper; source-bound ingestion must advance its cursor atomically."""
        _require(isinstance(rows,(list,tuple)) and len(rows) <= MAX_BATCH, 'entity batch exceeds bound')
        with self._transaction():
            _require(not self._meta('input_binding'), 'bound source requires enqueue_source_batch')
            return self._enqueue_records(rows)

    @_owned_method
    def register_agent(self, agent_id: str, *, role: str = 'entity-prepare') -> None:
        self._check_owner()
        _string(agent_id,256,'agent id')
        _string(role,128,'agent role')
        old = self._db.execute('SELECT role FROM agent_lease WHERE agent_id=?',[agent_id]).fetchone()
        _require(old is None or old[0] == role, 'agent role differs')
        _require(old is not None or self._db.execute('SELECT count(*) FROM agent_lease').fetchone()[0] < MAX_AGENTS,
                 'agent count exceeds bound')
        claimed = self._db.execute("SELECT count(*) FROM entity_queue WHERE status='claimed' AND claim_worker=?",[agent_id]).fetchone()[0]
        self._db.execute('INSERT OR REPLACE INTO agent_lease VALUES (?,?,?,?,?,FALSE,FALSE)',
                         [agent_id,DATASET_ID,role,str(int(time.time())),claimed])

    @_owned_method
    def claim_batch(self, agent_id: str, *, limit: int = 128) -> list[dict[str, Any]]:
        _string(agent_id,256,'agent id')
        _require(type(limit) is int and 1 <= limit <= MAX_BATCH,'claim limit exceeds bound')
        self._require_bound_context()
        token=uuid.uuid4().hex
        with self._transaction():
            self.register_agent(agent_id)
            rows=self._db.execute("SELECT entity_id,entity_type,label,properties_json,source_sha256 "
                "FROM entity_queue WHERE status='pending' ORDER BY entity_id LIMIT ?",[limit]).fetchall()
            if rows:
                ids=[row[0] for row in rows]
                self._db.execute("UPDATE entity_queue SET status='claimed',claim_worker=?,claim_token=? "
                    "WHERE status='pending' AND entity_id IN ("+','.join('?' for _ in ids)+')',[agent_id,token,*ids])
            self.register_agent(agent_id)
        return [dict(zip(('entity_id','entity_type','label','properties_json','source_sha256'),row),
                     claim_worker=agent_id,claim_token=token) for row in rows]

    @_owned_method
    def assign_containment(self, relationships: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        raise EntityCacheError('use one complete prepare_containment_batches operation on bound inputs')

    @_owned_method
    def prepare_containment_batches(self, batches, *, verify_inputs):
        import pyarrow as pa
        _require(callable(verify_inputs), 'source guard is required')
        with self._transaction():
            binding = self._binding()
            _require(binding['next_ordinal'] == binding['input_manifest']['entities']['row_count'],
                     'entity source prefix is incomplete')
            sealed = self._meta('containment_receipt')
            if sealed:
                result=self._require_bound_context()
                verify_inputs()
                return result
            _require(not self._db.execute("SELECT count(*) FROM entity_queue WHERE status='claimed'").fetchone()[0],
                     'current claims prevent context preparation')
            self._db.execute('CREATE TEMP TABLE _entity_edges (ordinal BIGINT,kind VARCHAR,source VARCHAR,target VARCHAR)')
            self._db.execute('CREATE TEMP TABLE _entity_context_stage (entity_id VARCHAR PRIMARY KEY,context_json VARCHAR)')
            try:
                ordinal = 0
                for batch in batches:
                    _require(isinstance(batch,(list,tuple)) and 0 < len(batch) <= MAX_BATCH, 'relationship batch exceeds bound')
                    edges = []
                    for row in batch:
                        _require(isinstance(row,Mapping), 'relationship must be an object')
                        kind = _string(row.get('type',''),128,'relationship type',empty=True)
                        source = _string(row.get('source',''),1024,'relationship source',empty=True)
                        target = _string(row.get('target',''),1024,'relationship target',empty=True)
                        if source and target and kind in {'IN_TITLE','HAS_SECTION'}:
                            edges.append(dict(ordinal=ordinal,kind=kind,source=source,target=target))
                        ordinal += 1
                    _require(ordinal <= binding['input_manifest']['relationships']['row_count'], 'relationship source grew')
                    if edges:
                        table = pa.Table.from_pylist(edges)
                        self._db.register('_entity_edge_batch',table)
                        try:
                            self._db.execute('INSERT INTO _entity_edges SELECT * FROM _entity_edge_batch')
                        finally:
                            self._db.unregister('_entity_edge_batch')
                        del table
                _require(ordinal == binding['input_manifest']['relationships']['row_count'], 'relationship source is incomplete')
                # Exact duplicate edges are harmless; ambiguous containment is
                # rejected before any context/status mutation in either direction.
                for kind,key,value in (('IN_TITLE','source','target'),('HAS_SECTION','source','target'),
                                       ('HAS_SECTION','target','source')):
                    conflicts=self._db.execute('SELECT count(*) FROM (SELECT '+key+
                        ' FROM _entity_edges WHERE kind=? GROUP BY 1 HAVING count(DISTINCT '+value+')>1)',[kind]).fetchone()[0]
                    _require(not conflicts,'conflicting relationship containment')
                for name,kind,key in (('_title_edges','IN_TITLE','source'),('_section_edges','HAS_SECTION','source'),
                                      ('_parent_edges','HAS_SECTION','target')):
                    self._db.execute('CREATE TEMP TABLE '+name+' AS SELECT source,target FROM _entity_edges WHERE kind=? '
                        'QUALIFY row_number() OVER (PARTITION BY '+key+' ORDER BY ordinal DESC)=1',[kind])
                counts = dict(section_spans=0,title_scope=0,provenance_excluded=0,definition_hops=0)
                after = ''
                while True:
                    page = self._db.execute("""SELECT e.entity_id,e.entity_type,p.source,pt.target,s.target,t.target
                        FROM entity_queue e LEFT JOIN _parent_edges p ON p.target=e.entity_id
                        LEFT JOIN _title_edges pt ON pt.source=p.source
                        LEFT JOIN _section_edges s ON s.source=e.entity_id
                        LEFT JOIN _title_edges t ON t.source=e.entity_id
                        WHERE e.entity_id>? ORDER BY e.entity_id LIMIT 64""",[after]).fetchall()
                    if not page:
                        break
                    updates=[]
                    for eid,kind,parent,parent_title,section,title in page:
                        parent,parent_title,section,title = (str(x or '') for x in (parent,parent_title,section,title))
                        context=dict(contained_entity_ids=[],definition_hops=0,
                                     excluded_edge_types=['HAS_SOURCE','DERIVED_FROM','source_package'],
                                     reasons=['provenance_excluded'],scope_only_entity_ids=[],span_legal_id='')
                        if kind == 'section':
                            context.update(contained_entity_ids=[eid]+([parent] if parent else []),
                                reasons=['section_spans','has_section'],scope_only_entity_ids=[parent_title] if parent_title else [],
                                span_legal_id=('usc:us:'+parent_title.rsplit(':',1)[-1]+':'+eid.rsplit(':',1)[-1]) if parent_title else '')
                            counts['section_spans']+=1
                        elif kind == 'legal_document':
                            context.update(contained_entity_ids=[eid]+([section] if section else []),
                                           reasons=['has_section'],scope_only_entity_ids=[title] if title else [])
                            counts['section_spans']+=1
                        elif kind == 'usc_title':
                            size=self._db.execute('SELECT coalesce(sum(octet_length(encode(s.target))+3),0) '
                                'FROM _section_edges s JOIN _title_edges t ON s.source=t.source WHERE t.target=?',[eid]).fetchone()[0]
                            _require(size <= MAX_CONTEXT_BYTES-1024, 'title scope exceeds byte bound')
                            children=[r[0] for r in self._db.execute('SELECT s.target FROM _section_edges s '
                                'JOIN _title_edges t ON s.source=t.source WHERE t.target=? ORDER BY s.source',[eid]).fetchall()]
                            context.update(contained_entity_ids=[eid],reasons=['title_scope_not_formula'],scope_only_entity_ids=children)
                            counts['title_scope']+=1
                        else:
                            counts['provenance_excluded']+=1
                        raw=_json(context)
                        _string(raw,MAX_CONTEXT_BYTES,'entity context')
                        updates.append(dict(entity_id=eid,context_json=raw))
                    table=pa.Table.from_pylist(updates)
                    _require(table.nbytes <= MAX_RESUME_BATCH_BYTES,'context stage batch exceeds bound')
                    self._db.register('_entity_context_batch',table)
                    try:
                        self._db.execute('INSERT INTO _entity_context_stage SELECT * FROM _entity_context_batch')
                    finally:
                        self._db.unregister('_entity_context_batch')
                    after=page[-1][0]
                    del table,updates,page
                prepared=self._db.execute("SELECT count(*) FROM entity_queue WHERE status='pending'").fetchone()[0]
                self._db.execute("UPDATE entity_queue SET context_json=s.context_json FROM _entity_context_stage s "
                                 "WHERE entity_queue.entity_id=s.entity_id")
                self._db.execute("UPDATE entity_queue SET status='prepared',claim_worker='',claim_token='',"
                                 "admitted=FALSE,formalized=FALSE WHERE status='pending'")
                result=dict(admitted=False,formalized=False,prepared=prepared,containment=counts)
                self._set_meta('containment_receipt',_json(dict(input_id=binding['input_id'],result=result)))
                verify_inputs()
            finally:
                for name in ('_entity_edges','_entity_context_stage','_title_edges','_section_edges','_parent_edges'):
                    self._db.execute('DROP TABLE IF EXISTS '+name)
        return result

    def _section_pages(self, after: str = ""):
        return self._db.execute(
            "SELECT entity_id, context_json FROM entity_queue "
            "WHERE entity_type = 'section' AND entity_id > ? ORDER BY entity_id LIMIT ?",
            [after, MAX_BATCH],
        ).fetchall()

    @_owned_method
    @_atomic_method
    def assign_span_context(self, spans: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        """Attach sealed span ids to the section that owns their legal id. Titles stay scope-only."""

        self._reject_section_claims()
        sealed: dict[str, list[str]] = {}
        gaps: dict[str, list[str]] = {}
        pending: set[str] = set()
        slots: dict[str, list[str]] = {}
        seen: set[str] = set()
        for span in spans:
            if not isinstance(span, Mapping):
                continue
            legal_id = str(span.get("legal_id") or span.get("span_legal_id") or "")
            span_id = str(span.get("source_span_id") or span.get("id") or "")
            if not legal_id or not span_id:
                continue
            seen.add(legal_id)
            status = _span_status(span)
            if status in {"pending", "unsealed"}:
                pending.add(legal_id)
                continue
            if status == "gap":
                gaps.setdefault(legal_id, []).append(span_id)
                continue
            sealed.setdefault(legal_id, []).append(span_id)
            slots.setdefault(legal_id, []).extend(_open_stitch_slots(span))
        attached = 0
        sections = 0
        after = ""
        while True:
            page = self._section_pages(after)
            if not page:
                break
            updates: list[tuple[str, str]] = []
            for entity_id, raw in page:
                context = _object(raw or '', MAX_CONTEXT_BYTES, 'entity context')
                legal_id = str(context.get("span_legal_id") or "")
                span_ids = sorted(set(sealed.get(legal_id, [])))
                context["contained_span_ids"] = span_ids
                context["gap_span_ids"] = sorted(set(gaps.get(legal_id, [])))
                context["open_stitch_slots"] = sorted(set(slots.get(legal_id, [])))
                if legal_id in pending:
                    context["section_ready"] = False
                elif legal_id in seen:
                    context["section_ready"] = True
                if span_ids and "section_spans" not in context.get("reasons", []):
                    context.setdefault("reasons", []).append("section_spans")
                encoded = _json(context)
                _string(encoded, MAX_CONTEXT_BYTES, 'updated entity context')
                updates.append((encoded, str(entity_id)))
                attached += len(span_ids)
            if updates:
                self._db.executemany(
                    "UPDATE entity_queue SET context_json = ? WHERE entity_id = ?",
                    updates,
                )
            sections += len(updates)
            after = page[-1][0]
        return {"attached_spans": attached, "sections": sections, "admitted": False}

    @_owned_method
    @_atomic_method
    def record_inconsistencies(
        self,
        spans: Sequence[Mapping[str, Any]],
        terms: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """Persist section-versus-span mismatches. Does not admit."""

        found: list[dict[str, str]] = []
        after = ""
        while True:
            page = self._section_pages(after)
            if not page:
                break
            for entity_id, raw in page:
                context = _object(raw or '', MAX_CONTEXT_BYTES, 'entity context')
                context["entity_id"] = str(entity_id)
                found.extend(inconsistencies_for_section(context, spans, terms))
            after = page[-1][0]
        self._db.execute("DELETE FROM inconsistency")
        for index, row in enumerate(found):
            self._db.execute(
                """
                INSERT INTO inconsistency (
                    inconsistency_id, entity_id, span_id, term_id, kind, evidence,
                    admitted, formalized
                ) VALUES (?, ?, ?, ?, ?, ?, FALSE, FALSE)
                """,
                [
                    f"inc-{index}",
                    row["entity_id"],
                    row["span_id"],
                    row["term_id"],
                    row["kind"],
                    row["evidence"],
                ],
            )
        return found

    @_owned_method
    @_atomic_method
    def reopen_definition_targets(self, legal_ids: Sequence[str]) -> list[str]:
        """Reopen unclaimed dependent sections atomically; never release a lease."""
        wanted={str(item) for item in legal_ids if str(item)}
        if not wanted: return []
        rows=self._db.execute("SELECT entity_id,status,context_json FROM entity_queue WHERE entity_type='section'").fetchall()
        reopened=[]
        for eid,status,raw in rows:
            context=_object(raw or '',MAX_CONTEXT_BYTES,'entity context')
            if set(context.get('definition_targets',[])) & wanted or context.get('span_legal_id') in wanted:
                _require(status!='claimed','active section claim prevents reopening')
                reopened.append(eid)
        if reopened:
            self._db.executemany("UPDATE entity_queue SET status='pending',claim_worker='',claim_token='',admitted=FALSE,formalized=FALSE WHERE entity_id=?",
                                 [(eid,) for eid in reopened])
        return reopened

    @_owned_method
    @_atomic_method
    def assign_definition_closure(self, cites: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        """Retain every target reachable within two edges; never truncate breadth."""
        self._reject_section_claims()
        graph: dict[str, set[str]] = {}
        unresolved: set[str] = set()
        for cite in cites:
            _require(isinstance(cite, Mapping), "citation must be an object")
            source = _string(cite.get("source_legal_id") or cite.get("span_legal_id") or "",1024,"citation source",empty=True)
            target = _string(cite.get("target_legal_id") or "",1024,"citation target",empty=True)
            _require(type(cite.get('unresolved',False)) is bool,'citation unresolved flag must be boolean')
            if not source:
                continue
            if cite.get("unresolved") or not target:
                unresolved.add(source)
            else:
                graph.setdefault(source, set()).add(target)
        linked, gaps = 0, 0
        after = ""
        while True:
            page = self._section_pages(after)
            if not page:
                break
            updates = []
            for entity_id, raw in page:
                context = _object(raw or "", MAX_CONTEXT_BYTES, "entity context")
                legal_id = str(context.get("span_legal_id") or "")
                depths, frontier, expanded = {}, {legal_id}, set()
                for depth in (1, 2):
                    next_frontier = set()
                    for node in sorted(frontier):
                        expanded.add(node)
                        for target in sorted(graph.get(node, ())):
                            if target != legal_id and target not in depths:
                                depths[target] = depth
                                next_frontier.add(target)
                    _require(len(depths) <= MAX_DEFINITION_TARGETS, "definition closure exceeds explicit bound")
                    frontier = next_frontier
                targets = sorted(depths)
                context["definition_targets"] = targets
                context["definition_hops"] = max(depths.values(), default=0)
                reasons = [item for item in context.get("reasons", [])
                           if item not in {"definition_closure", "unresolved_citation"}]
                if expanded & unresolved:
                    reasons.append("unresolved_citation")
                    gaps += 1
                if targets:
                    reasons.append("definition_closure")
                    linked += 1
                context["reasons"] = reasons
                encoded = _json(context)
                _string(encoded, MAX_CONTEXT_BYTES, 'updated entity context')
                updates.append((encoded, str(entity_id)))
            if updates:
                self._db.executemany("UPDATE entity_queue SET context_json=? WHERE entity_id=?", updates)
            after = page[-1][0]
        return {"definition_sections": linked, "unresolved": gaps, "admitted": False}

    @_owned_method
    @_atomic_method
    def prepare_all(self) -> int:
        """Mark every pending entity ready. Does not take another agent's claim."""

        self._require_bound_context()
        row = self._db.execute("SELECT count(*) FROM entity_queue WHERE status = 'pending'").fetchone()
        count = int(row[0] if row else 0)
        if count:
            self._db.execute(
                """
                UPDATE entity_queue
                SET status = 'prepared', claim_worker = '', claim_token = '',
                    admitted = FALSE, formalized = FALSE
                WHERE status = 'pending'
                """
            )
        return count

    @_owned_method
    def prepare_claimed(self, entity_ids: Sequence[str], *, agent_id: str, claim_token: str) -> int:
        """Complete only the exact current claim; stale owner work cannot commit."""
        self._require_bound_context()
        _string(agent_id, 256, "agent id")
        _require(type(claim_token) is str and _TOKEN.fullmatch(claim_token), "invalid claim token")
        _require(isinstance(entity_ids, (list, tuple)) and len(entity_ids) <= MAX_BATCH, "claim batch exceeds bound")
        ids = sorted({_string(eid, 1024, "entity id") for eid in entity_ids})
        self._db.execute("BEGIN")
        try:
            matched = 0
            for eid in ids:
                row = self._db.execute("SELECT status,claim_worker,claim_token FROM entity_queue WHERE entity_id=?", [eid]).fetchone()
                if row is None or row[0] != "claimed":
                    continue
                _require(tuple(row[1:]) == (agent_id, claim_token), "stale or foreign entity claim")
                changed = self._db.execute(
                    "UPDATE entity_queue SET status='prepared',claim_worker='',claim_token='',admitted=FALSE,formalized=FALSE "
                    "WHERE entity_id=? AND status='claimed' AND claim_worker=? AND claim_token=? RETURNING entity_id",
                    [eid, agent_id, claim_token]).fetchall()
                matched += len(changed)
            self.register_agent(agent_id)
            self._db.execute("COMMIT")
            return matched
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @_owned_method
    @_atomic_method
    def release_stale_claims(self, agent_id: str | None = None) -> int:
        """Explicit owner action only; no caller gets implicit lease adoption."""
        where="status='claimed'"
        params=[]
        if agent_id is not None:
            _string(agent_id,256,'agent id')
            where+=' AND claim_worker=?'
            params=[agent_id]
        count=self._db.execute('SELECT count(*) FROM entity_queue WHERE '+where,params).fetchone()[0]
        self._db.execute("UPDATE entity_queue SET status='pending',claim_worker='',claim_token='' WHERE "+where,params)
        self._db.execute("UPDATE agent_lease SET claimed_count=(SELECT count(*) FROM entity_queue "
            "WHERE entity_queue.status='claimed' AND entity_queue.claim_worker=agent_lease.agent_id)")
        return int(count)

    @_owned_method
    @_atomic_method
    def refresh_task_board(self) -> int:
        self._db.execute("DELETE FROM task_board")
        self._db.execute(
            """
            INSERT INTO task_board (
                task_id, entity_id, entity_type, label, status, work_kind,
                owner_agent, admitted, formalized
            )
            SELECT
                'AFTD-E-' || sha256(entity_id),
                entity_id,
                entity_type,
                label,
                status,
                CASE entity_type
                    WHEN 'usc_title' THEN 'title_entity'
                    WHEN 'section' THEN 'section_entity'
                    WHEN 'legal_document' THEN 'legal_document_entity'
                    WHEN 'document' THEN 'document_entity'
                    ELSE 'kg_entity'
                END,
                coalesce(claim_worker, ''),
                FALSE,
                FALSE
            FROM entity_queue
            """
        )
        row = self._db.execute("SELECT count(*) FROM task_board").fetchone()
        return int(row[0] if row else 0)

    @_owned_method
    def section_context_pages(self):
        """Yield prepared section contexts one batch at a time."""

        after = ""
        while True:
            page = self._section_pages(after)
            if not page:
                return
            parsed = []
            for entity_id, raw in page:
                context = _object(raw or "", MAX_CONTEXT_BYTES, "entity context")
                context["entity_id"] = str(entity_id)
                parsed.append(context)
            yield parsed
            after = page[-1][0]

    @_owned_method
    def list_inconsistencies(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """
            SELECT inconsistency_id, entity_id, span_id, term_id, kind, evidence, admitted, formalized
            FROM inconsistency ORDER BY inconsistency_id
            """
        ).fetchall()
        return [
            {
                "admitted": False,
                "entity_id": str(row[1] or ""),
                "evidence": str(row[5] or ""),
                "formalized": False,
                "inconsistency_id": str(row[0]),
                "kind": str(row[4] or ""),
                "span_id": str(row[2] or ""),
                "term_id": str(row[3] or ""),
            }
            for row in rows
        ]

    @_owned_method
    def stats(self) -> dict[str, int]:
        self._check_owner()
        rows = dict(self._db.execute('SELECT status,count(*) FROM entity_queue GROUP BY 1').fetchall())
        return {name:int(rows.get(name,0)) for name in ('pending','claimed','prepared')}

    @_owned_method
    def write_resume_parquet(self, path: str | Path) -> dict[str, Any]:
        """Write a bounded, validated v2 observation; no snapshot imports a lease."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        destination=Path(path).absolute()
        _require(destination.resolve()==destination and destination.suffix=='.parquet','invalid resume destination')
        _require(destination!=self.path and not str(destination).startswith(str(self.path)+'.'), 'resume overlaps cache')
        if destination.exists():
            info=destination.lstat()
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not os.path.samefile(destination,self.path),
                     'resume destination is aliased or overlaps cache')
            old_identity=_file_identity(info)
        else:
            old_identity=None
        destination.parent.mkdir(parents=True,exist_ok=True)
        _require(destination.parent.resolve()==destination.parent,'resume parent is aliased')
        parent_fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        parent_identity=os.fstat(parent_fd)
        temp_name='.'+destination.name+'.'+uuid.uuid4().hex+'.tmp'
        temporary=destination.parent/temp_name
        published=False
        try:
            with self._transaction():
                binding=self._binding()
                logical=self._db.execute('SELECT count(*) FROM entity_queue').fetchone()[0]
                agents=self._db.execute('SELECT count(*) FROM agent_lease').fetchone()[0]
                _require(logical<=MAX_ENTITIES and agents<=MAX_AGENTS and logical<=binding['next_ordinal'], 'snapshot count exceeds bound')
                self._db.execute("UPDATE agent_lease SET claimed_count=(SELECT count(*) FROM entity_queue "
                    "WHERE entity_queue.status='claimed' AND entity_queue.claim_worker=agent_lease.agent_id)")
                self.refresh_task_board()
                fd=os.open(temp_name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent_fd)
                decoded=count=0
                with os.fdopen(fd,'wb') as stream:
                    writer=pq.ParquetWriter(stream,_resume_schema(),compression='zstd')
                    pending_tables=[]
                    pending_rows=pending_arrow_bytes=pending_json_bytes=0
                    try:
                        def flush_group():
                            nonlocal pending_rows,pending_arrow_bytes,pending_json_bytes
                            if not pending_tables:
                                return
                            # Concatenation retains the bounded Arrow buffers; it
                            # does not hydrate a second Python row graph.
                            table=pa.concat_tables(pending_tables)
                            _require(table.num_rows<=MAX_RESUME_WRITE_GROUP_ROWS
                                     and table.nbytes<=MAX_RESUME_BATCH_BYTES,
                                     'snapshot write group exceeds bound')
                            writer.write_table(table,row_group_size=MAX_RESUME_WRITE_GROUP_ROWS)
                            _require(stream.tell()<=MAX_RESUME_FILE_BYTES,'snapshot bytes exceed bound')
                            pending_tables.clear()
                            pending_rows=pending_arrow_bytes=pending_json_bytes=0

                        def write(rows):
                            nonlocal decoded,count,pending_rows,pending_arrow_bytes,pending_json_bytes
                            _require(0<len(rows)<=64,'snapshot validation page exceeds bound')
                            size=0
                            for row in rows:
                                _validate_resume_row(row,binding)
                                size+=len(_json(row).encode('utf-8'))
                            decoded+=size
                            count+=len(rows)
                            _require(size<=MAX_RESUME_BATCH_BYTES and decoded<=MAX_RESUME_DECODED_BYTES,
                                     'snapshot decoded bytes exceed bound')
                            table=pa.Table.from_pylist(rows,schema=_resume_schema())
                            _require(table.nbytes<=MAX_RESUME_BATCH_BYTES,'snapshot Arrow batch exceeds bound')
                            if pending_tables and (
                                pending_rows+len(rows)>MAX_RESUME_WRITE_GROUP_ROWS
                                or pending_arrow_bytes+table.nbytes>MAX_RESUME_BATCH_BYTES
                                or pending_json_bytes+size>MAX_RESUME_BATCH_BYTES
                            ):
                                flush_group()
                            pending_tables.append(table)
                            pending_rows+=len(rows)
                            pending_arrow_bytes+=table.nbytes
                            pending_json_bytes+=size
                            if pending_rows==MAX_RESUME_WRITE_GROUP_ROWS:
                                flush_group()
                        meta=_blank_resume('meta',binding)
                        meta.update(dataset_id=DATASET_ID,entities=binding['next_ordinal'],input_manifest_json=_json(binding['input_manifest']))
                        write([meta])
                        flush_group()
                        for table_name,key,kind,columns in (
                            ('agent_lease','agent_id','agent','agent_id,dataset_id,role,heartbeat,claimed_count,admitted,formalized'),
                            ('entity_queue','entity_id','entity','entity_id,entity_type,label,properties_json,source_sha256,status,claim_worker,claim_token,context_json,admitted,formalized'),
                            ('task_board','entity_id','board','entity_id,entity_type,label,status,work_kind,owner_agent,admitted,formalized')):
                            after=''
                            while True:
                                page=self._db.execute('SELECT '+columns+' FROM '+table_name+' WHERE '+key+'>? ORDER BY '+key+' LIMIT 64',[after]).fetchall()
                                if not page: break
                                records=[]
                                for values in page:
                                    raw=dict(zip(columns.split(','),values))
                                    row=_blank_resume(kind,binding)
                                    if kind=='agent':
                                        row.update(agent_id=raw['agent_id'],dataset_id=raw['dataset_id'],role=raw['role'],heartbeat=raw['heartbeat'],entities=raw['claimed_count'])
                                    elif kind=='entity':
                                        row.update({name:raw[name] for name in ('entity_id','entity_type','label','properties_json','source_sha256','status')})
                                        row.update(agent_id=raw['claim_worker'] or '',claim_worker=raw['claim_worker'] or '',claim_token=raw['claim_token'] or '',
                                                   context_json=_json(_object(raw['context_json'] or '',MAX_CONTEXT_BYTES,'local context')))
                                    else:
                                        row.update({name:raw[name] for name in ('entity_id','entity_type','label','status','work_kind')})
                                        row.update(agent_id=raw['owner_agent'] or '',claim_worker=raw['owner_agent'] or '')
                                    row.update(admitted=raw['admitted'],formalized=raw['formalized'])
                                    records.append(row)
                                write(records)
                                after=page[-1][0]
                                del records,page
                            # Keep original role/page boundaries even when a
                            # reader chooses to stop at a row-group boundary.
                            flush_group()
                    finally:
                        pending_tables.clear()
                        try:
                            writer.close()
                        finally:
                            # Closing alone retains the writer's per-column
                            # metadata until the Python owner is released.
                            del writer
                    stream.flush()
                    os.fsync(stream.fileno())
                _require(count==2*logical+agents+1,'snapshot physical closure differs')
                validated,fingerprint,kinds,cursor=_stage_resume(self._db,temporary,binding)
                _resume_current(validated,fingerprint)
                self._db.execute('DROP TABLE _entity_resume_stage')
                _require((parent_identity.st_dev,parent_identity.st_ino)==(destination.parent.stat().st_dev,destination.parent.stat().st_ino)
                         and destination.parent.resolve()==destination.parent,'resume parent changed')
                current=destination.lstat() if destination.exists() else None
                _require((None if current is None else _file_identity(current))==old_identity,'resume destination changed')
            # Publish only after the owner transaction COMMIT has succeeded.
            # A commit exception leaves the previous complete snapshot intact.
            _resume_current(validated,fingerprint)
            _require((parent_identity.st_dev,parent_identity.st_ino)==(destination.parent.stat().st_dev,destination.parent.stat().st_ino)
                     and destination.parent.resolve()==destination.parent,'resume parent changed')
            current=destination.lstat() if destination.exists() else None
            _require((None if current is None else _file_identity(current))==old_identity,'resume destination changed')
            os.replace(temp_name,destination.name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
            published=True
            os.fsync(parent_fd)
            return dict(admitted=False,formalized=False,jsonl_written=False,path=str(destination),task_count=logical,
                        physical_rows=count,input_id=binding['input_id'])
        finally:
            if not published:
                try: os.unlink(temp_name,dir_fd=parent_fd)
                except FileNotFoundError: pass
            os.close(parent_fd)

    @_owned_method
    def resume_summary(self, path: str | Path) -> dict[str, Any]:
        with self._transaction():
            binding=self._binding()
            try:
                path,fingerprint,kinds,cursor=_stage_resume(self._db,Path(path),binding)
                _resume_current(path,fingerprint)
                return dict(admitted=False,formalized=False,entities=cursor,kinds=kinds,input_id=binding['input_id'])
            finally:
                self._db.execute('DROP TABLE IF EXISTS _entity_resume_stage')

    @_owned_method
    def upsert_remote_resume(self, path: str | Path, *, agent_id: str) -> dict[str, Any]:
        """Import exact prepared observations, never remote agents or claim tokens."""
        _string(agent_id,256,'agent id')
        with self._transaction():
            binding=self._binding()
            self._require_bound_context()
            try:
                path,fingerprint,kinds,cursor=_stage_resume(self._db,Path(path),binding)
                after=''
                while True:
                    # Select only keys before constructing the rich join. Both
                    # sides are restricted to this same bounded local window.
                    keys=self._db.execute('SELECT entity_id FROM entity_queue WHERE entity_id>? '
                                          'ORDER BY entity_id LIMIT 64',[after]).fetchall()
                    if not keys: break
                    upper=keys[-1][0]
                    identifiers=[key[0] for key in keys]
                    page=self._db.execute("""SELECT e.entity_id,e.entity_type,e.label,e.properties_json,e.source_sha256,e.context_json,
                        r.entity_type,r.label,r.properties_json,r.source_sha256,r.context_json
                        FROM entity_queue e JOIN _entity_resume_stage r ON e.entity_id=r.entity_id AND r.record_kind='entity'
                        WHERE e.entity_id>? AND e.entity_id<=? AND r.entity_id>? AND r.entity_id<=?
                        AND r.entity_id IN ("""+','.join('?' for _ in identifiers)+""")
                        ORDER BY e.entity_id LIMIT 64""",[after,upper,after,upper,*identifiers]).fetchall()
                    for row in page:
                        _require(tuple(row[1:5])==tuple(row[6:10]),'remote immutable entity differs')
                        _require(_json(_object(row[5] or '',MAX_CONTEXT_BYTES,'local context'))==row[10],'remote context differs')
                    # An entire local window may have no remote observation.
                    # Its upper key still advances, preserving later matches.
                    after=upper
                    del keys,identifiers,page
                prepared=self._db.execute("""SELECT count(*) FROM entity_queue e JOIN _entity_resume_stage r
                    ON e.entity_id=r.entity_id AND r.record_kind='entity' WHERE e.status='pending' AND r.status='prepared'""").fetchone()[0]
                self._db.execute("""UPDATE entity_queue SET status='prepared',claim_worker='',claim_token='',admitted=FALSE,formalized=FALSE
                    FROM _entity_resume_stage r WHERE entity_queue.entity_id=r.entity_id AND r.record_kind='entity'
                    AND entity_queue.status='pending' AND r.status='prepared'""")
                self.refresh_task_board()
                _resume_current(path,fingerprint)
            finally:
                self._db.execute('DROP TABLE IF EXISTS _entity_resume_stage')
        return dict(admitted=False,formalized=False,claimed=0,prepared=prepared)
