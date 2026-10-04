#!/usr/bin/env python3
"""Queue an exact v2 entity/relationship input pair; never a legal admit.

Offline by default. Queue rows and the physical input cursor commit together.
The v2 local snapshot and optional Hub key are separate from every v1 object.
No claims are implicitly released, and remote checkpoints never supply a local
physical cursor. Input files stay open from their initial full hash through the
final operation; per-batch identity guards and final full hashes detect drift.

``--stitch`` assembles a pinned sealed-span file onto prepared sections and
writes the stitch parquet tables, including one logic-occurrence row per role,
label, and lexicon mention. It does not claim work and does not admit a statute.
``--lookup`` reads those rows. A lookup-only run does not enqueue, prepare,
claim, or upload.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
REPO_ID = "justicedao/uscode-autoformal-entity-cache"
REPO_PREFIX = "autoformal/uscode/v2"
SNAPSHOT_NAME = "entity-resume-checkpoint-v2.parquet"
STITCH_FILES = (
    "section-neighborhoods.parquet",
    "term-index.parquet",
    "inconsistencies.parquet",
    "lean-units.parquet",
    "logic-occurrences.parquet",
)
_REFUSED_OUTPUTS = {
    "kg-logic-index.parquet",
    "kg-meta-ontology.parquet",
    "meta-ontology.parquet",
    "entity-resume-checkpoint.parquet",
    "entity-resume-checkpoint-v2.parquet",
    "resume-checkpoint.parquet",
    "sealed-spans.parquet",
}
AGENT_ID = "entity-control-plane-v2"
MAX_INPUT_BYTES = 512 * 1024**2
MAX_RESUME_FILE_BYTES = 128 * 1024**2
MAX_INPUT_ROWS = 2_000_000
MAX_UNCOMPRESSED_BYTES = 1024**3
MAX_BATCH_BYTES = 16 * 1024**2
MAX_BATCH = 512
_HASH = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class EntityIngestError(ValueError):
    """Invalid, changed or unbound ingestion input/progress."""


def _require(value, message):
    if not value:
        raise EntityIngestError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _path(value, *, exists=True):
    value = Path(value)
    _require(".." not in value.parts, "parent path components are forbidden")
    path = Path(os.path.abspath(value))
    _require(path.resolve(strict=exists) == path, "path aliases are forbidden")
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _batch(value):
    _require(type(value) is int and 1 <= value <= MAX_BATCH, "batch must be an integer from 1 through 512")
    return value


def _batch_argument(value):
    try:
        return _batch(int(value))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("batch must be an integer from 1 through 512") from exc


class _Input:
    def __init__(self, path, *, max_bytes=MAX_INPUT_BYTES):
        self.path = _path(path)
        self.stream = os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), "rb")
        try:
            self.signature = _identity(os.fstat(self.stream.fileno()))
            info = os.fstat(self.stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and 0 < info.st_size <= max_bytes, "input must be an exclusive bounded regular file")
            self.verify_current()
            self.sha256 = self._hash()
        except BaseException:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def verify_current(self):
        _require(not self.stream.closed and self.path.resolve(strict=True) == self.path
                 and _identity(os.fstat(self.stream.fileno())) == self.signature
                 and _identity(self.path.lstat()) == self.signature, "input identity changed")

    def _hash(self):
        self.verify_current()
        self.stream.seek(0)
        digest, count = hashlib.sha256(), 0
        while block := self.stream.read(1024**2):
            count += len(block)
            _require(count <= self.signature[3], "input grew while hashing")
            digest.update(block)
        self.verify_current()
        _require(count == self.signature[3], "input truncated while hashing")
        return digest.hexdigest()

    def verify_full(self):
        _require(self._hash() == self.sha256, "input bytes changed")

    def parquet(self, *, role):
        import pyarrow.parquet as pq
        self.verify_current()
        parquet = pq.ParquetFile(self.stream)
        count = parquet.metadata.num_rows
        _require(type(count) is int and 0 <= count <= MAX_INPUT_ROWS, "physical row count exceeds bound")
        _require(sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.num_row_groups))
                 <= MAX_UNCOMPRESSED_BYTES, "uncompressed Parquet bytes exceed bound")
        names = parquet.schema_arrow.names
        _require(len(names) == len(set(names)) and 1 <= len(names) <= 128, "ambiguous or oversized Parquet schema")
        if role == "entities":
            _require("label" in names and ("id" in names or "entity_id" in names), "entity columns missing")
        else:
            _require({"type", "source", "target"} <= set(names), "relationship columns missing")
        self.verify_current()
        return parquet, {"sha256": self.sha256, "bytes": self.signature[3], "row_count": count}


class _BoundInputs:
    """One operation's exact source descriptors and still-open readonly files."""
    def __init__(self, entities, relationships):
        self.entity_path, self.relationship_path = entities, relationships
        self._stack = None

    def __enter__(self):
        self._stack = ExitStack()
        try:
            self.entities = _Input(self.entity_path)
            self._stack.callback(self.entities.close)
            self.relationships = _Input(self.relationship_path)
            self._stack.callback(self.relationships.close)
            _require(self.entities.signature[:2] != self.relationships.signature[:2], "entity and relationship inputs alias")
            self.entity_file, entity_ref = self.entities.parquet(role="entities")
            self.relationship_file, relationship_ref = self.relationships.parquet(role="relationships")
            self.manifest = {"schema_version": "entity-cache-inputs/v2", "dataset_id": "justicedao/ipfs_uscode",
                "entity_identity_schema": "uscode-autoformal-entity-cache/v2",
                "entities": entity_ref, "relationships": relationship_ref}
            self.input_id = "sha256:" + hashlib.sha256(_json(self.manifest)).hexdigest()
            self.verify_full()
            return self
        except BaseException:
            self._stack.close()
            self._stack = None
            raise

    def __exit__(self, *args):
        self._stack.close()
        self._stack = None

    def verify_current(self):
        _require(self._stack is not None, "input binding is closed")
        self.entities.verify_current()
        self.relationships.verify_current()

    def verify_full(self):
        self.verify_current()
        self.entities.verify_full()
        self.relationships.verify_full()

    def batches(self, role, size):
        _batch(size)
        self.verify_current()
        parquet = self.entity_file if role == "entities" else self.relationship_file
        columns = ([name for name in ("id", "entity_id", "type", "entity_type", "label", "properties_json")
                    if name in parquet.schema_arrow.names] if role == "entities" else ["type", "source", "target"])
        seen = 0
        for arrow in parquet.iter_batches(batch_size=size, columns=columns, use_threads=False):
            self.verify_current()
            _require(arrow.nbytes <= MAX_BATCH_BYTES, "decoded batch exceeds byte bound")
            rows = arrow.to_pylist()
            _require(0 < len(rows) <= size, "invalid physical batch size")
            seen += len(rows)
            _require(seen <= self.manifest[role]["row_count"], "Parquet returned excess rows")
            yield rows
            self.verify_current()
        _require(seen == self.manifest[role]["row_count"], "Parquet physical row coverage differs")
        self.verify_current()


def _checkpoint(cache, inputs):
    checkpoint = cache.checkpoint()
    _require(type(checkpoint) is dict and checkpoint.get("input_id") == inputs.input_id
             and _json(checkpoint.get("input_manifest")) == _json(inputs.manifest), "checkpoint input binding differs")
    cursor = checkpoint.get("next_ordinal")
    _require(type(cursor) is int and 0 <= cursor <= inputs.manifest["entities"]["row_count"], "corrupt physical cursor")
    return cursor


def enqueue_entities(cache, inputs, *, batch):
    """Skip only a verified physical prefix; commit rows and cursor atomically."""
    _batch(batch)
    inputs.verify_full()
    skip = _checkpoint(cache, inputs)
    seen, added = 0, 0
    for rows in inputs.batches("entities", batch):
        start, seen = seen, seen + len(rows)
        if seen <= skip:
            continue
        if start < skip:
            rows, start = rows[skip - start:], skip
        added += cache.enqueue_source_batch(rows, start, seen, verify_inputs=inputs.verify_current)
    _require(seen == inputs.manifest["entities"]["row_count"] and _checkpoint(cache, inputs) == seen,
             "entity cursor does not cover the exact physical input")
    inputs.verify_full()
    return {"admitted": False, "formalized": False, "entities": seen,
            "new": added, "resumed_from": skip, "input_id": inputs.input_id}


def prepare_pending(cache, inputs, *, batch):
    inputs.verify_full()
    _require(_checkpoint(cache, inputs) == inputs.manifest["entities"]["row_count"], "cannot prepare an incomplete input")
    # One core operation consumes all batches; it must not reset maps per batch.
    result = cache.prepare_containment_batches(inputs.batches("relationships", _batch(batch)),
                                               verify_inputs=inputs.verify_current)
    inputs.verify_full()
    return result


def _remote_key(cache):
    identifier = cache.checkpoint().get("input_id", "")
    _require(type(identifier) is str and identifier.startswith("sha256:")
             and _HASH.fullmatch(identifier[7:]), "remote checkpoint requires exact v2 input binding")
    return REPO_PREFIX + "/" + identifier[7:] + "/" + SNAPSHOT_NAME


def _poll(cache, inputs):
    """Explicit remote observation; defaults never enter this function."""
    inputs.verify_full()
    key = _remote_key(cache)
    from huggingface_hub import HfApi, hf_hub_download
    try:
        api = HfApi()
        revision = str(api.repo_info(REPO_ID, repo_type="dataset").sha)
        _require(_COMMIT.fullmatch(revision), "remote revision is not immutable")
        info = api.get_paths_info(REPO_ID, [key], repo_type="dataset", revision=revision)
        if not info:
            return {"changed": False, "admitted": False, "formalized": False}
        _require(len(info) == 1 and type(info[0].size) is int and 0 < info[0].size <= MAX_RESUME_FILE_BYTES,
                 "remote checkpoint exceeds byte bound")
        downloaded = Path(hf_hub_download(REPO_ID, key, repo_type="dataset", revision=revision)).resolve(strict=True)
        inputs.verify_full()
        _require(downloaded.stat().st_size == info[0].size, "remote checkpoint size differs")
        result = cache.upsert_remote_resume(downloaded, agent_id=AGENT_ID)
        inputs.verify_full()
        return {**result, "changed": True, "revision": revision, "admitted": False, "formalized": False}
    except (OSError, ValueError) as exc:
        inputs.verify_full()
        return {"changed": False, "error": type(exc).__name__, "admitted": False, "formalized": False}


def _flush(cache, destination, *, upload, inputs):
    inputs.verify_full()
    key = _remote_key(cache)
    root = _path(destination, exists=False) / inputs.input_id[7:]
    root.mkdir(parents=True, exist_ok=True)
    _require(root.resolve(strict=True) == root, "checkpoint directory aliases another path")
    path = root / SNAPSHOT_NAME
    if os.path.lexists(path):
        _require(not path.is_symlink(), "checkpoint destination is not an exclusive regular file")
        _require(path.resolve(strict=True) == path and stat.S_ISREG(path.lstat().st_mode)
                 and path.lstat().st_nlink == 1, "checkpoint destination is not an exclusive regular file")
    _require(path not in (inputs.entities.path, inputs.relationships.path), "checkpoint output overlaps an input")
    cache_path = _path(cache.path, exists=True)
    protected = (cache_path, Path(str(cache_path) + ".wal"))
    _require(path not in protected, "checkpoint output overlaps the cache or its WAL")
    if path.exists():
        for value in protected:
            if value.exists():
                _require(not os.path.samefile(path, value), "checkpoint output aliases the cache or its WAL")
    cache.register_agent(AGENT_ID)
    written = cache.write_resume_parquet(path)
    inputs.verify_full()
    receipt = {"admitted": False, "formalized": False, "jsonl_written": False,
        "input_id": inputs.input_id, "local_path": str(path), "task_count": written.get("task_count"),
        "uploaded": False, "remote_verified": False}
    if not upload:
        return receipt
    from huggingface_hub import HfApi
    with ExitStack() as stack:
        snapshot = _Input(path, max_bytes=MAX_RESUME_FILE_BYTES)
        stack.callback(snapshot.close)
        api = HfApi()
        inputs.verify_full()
        snapshot.verify_full()
        api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True)
        parent = str(api.repo_info(REPO_ID, repo_type="dataset").sha)
        _require(_COMMIT.fullmatch(parent), "remote parent is not immutable")
        # Last complete input check immediately before the explicit remote write.
        inputs.verify_full()
        snapshot.verify_full()
        snapshot.stream.seek(0)
        result = api.upload_file(path_or_fileobj=snapshot.stream, path_in_repo=key,
            repo_id=REPO_ID, repo_type="dataset", parent_commit=parent,
            commit_message="autoformal entity v2 source-bound resume checkpoint")
        snapshot.verify_current()
        inputs.verify_full()
        receipt.update(uploaded=True, repo_id=REPO_ID, repo_path=key,
                       revision=str(getattr(result, "oid", "") or ""))
    return receipt


def _cell(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _graph_cites(path):
    """Use the ontology script's edge read. Do not republish the index."""
    import pyarrow.parquet as pq
    publish_path = Path(__file__).with_name("publish_kg_meta_ontology.py")
    spec = importlib.util.spec_from_file_location("_kg_graph_cites", publish_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _require(Path(path).name == "kg-logic-index.parquet", "citation closure reads the logic index")
    return module.read_graph_cites(pq.read_table(path))


def _stitch_table(rows, schema):
    import pyarrow as pa
    if rows:
        return pa.Table.from_pylist(rows, schema=schema)
    return pa.table({field.name: pa.array([], type=field.type) for field in schema}, schema=schema)


def _write_stitch_parquet(directory, name, rows, schema):
    import pyarrow.parquet as pq
    _require(name in STITCH_FILES and name not in _REFUSED_OUTPUTS, "refusing to replace " + name)
    path = directory / name
    _require(path.name == name, "refusing to replace " + name)
    temporary = directory / ("." + name + ".tmp")
    _require(not temporary.exists() or (temporary.is_file() and not temporary.is_symlink()), "stitch output is aliased")
    if temporary.exists():
        temporary.unlink()
    pq.write_table(_stitch_table(rows, schema), temporary)
    os.replace(temporary, path)
    return path


def _publish_stitch_files(paths, *, fingerprint):
    """Upload the stitch tables. The logic index is not a destination."""
    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True)
    parent = str(api.repo_info(REPO_ID, repo_type="dataset").sha)
    _require(_COMMIT.fullmatch(parent), "remote parent is not immutable")
    for path in paths:
        _require(path.name in STITCH_FILES and path.name not in _REFUSED_OUTPUTS, "refusing to replace " + path.name)
        key = "autoformal/uscode/" + path.name
        result = api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=key,
            repo_id=REPO_ID,
            repo_type="dataset",
            parent_commit=parent,
            commit_message="autoformal entity stitch " + path.name,
        )
        parent = str(getattr(result, "oid", "") or parent)
    return {"uploaded": True, "fingerprint": fingerprint, "revision": parent}


def _document_id(context):
    entity_id = str(context.get("entity_id") or "")
    contained = [str(item) for item in (context.get("contained_entity_ids") or []) if str(item or "")]
    if len(contained) >= 2 and contained[0] == entity_id:
        return contained[1]
    for item in contained:
        if item != entity_id:
            return item
    return ""


def _labels_for(cache, entity_ids):
    """Labels for this page's entity ids. Does not load the entity table."""
    wanted = [str(item) for item in dict.fromkeys(entity_ids) if str(item)]
    if not wanted:
        return {}
    marks = ", ".join(["?"] * len(wanted))
    rows = cache._db.execute(
        "SELECT entity_id, label FROM entity_queue WHERE entity_id IN (" + marks + ")",
        wanted,
    ).fetchall()
    return {str(entity_id): str(label or "") for entity_id, label in rows}


def _occurrence_record(row):
    def cell(key):
        value = row.get(key, "")
        if isinstance(value, str):
            return value
        return _cell(list(value or []))

    return {
        "admitted": False,
        "formalized": False,
        "surface": str(row.get("surface") or ""),
        "normalized": str(row.get("normalized") or ""),
        "category": str(row.get("category") or ""),
        "kind": str(row.get("kind") or ""),
        "term_id": str(row.get("term_id") or ""),
        "modality": str(row.get("modality") or ""),
        "formula": str(row.get("formula") or ""),
        "participant": str(row.get("participant") or ""),
        "act": str(row.get("act") or ""),
        "object": str(row.get("object") or ""),
        "state": str(row.get("state") or ""),
        "span_id": str(row.get("span_id") or ""),
        "legal_id": str(row.get("legal_id") or ""),
        "entity_id": str(row.get("entity_id") or ""),
        "section_label": str(row.get("section_label") or ""),
        "document_id": str(row.get("document_id") or ""),
        "document_label": str(row.get("document_label") or ""),
        "definition_targets": cell("definition_targets"),
        "gap_span_ids": cell("gap_span_ids"),
        "open_stitch_slots": cell("open_stitch_slots"),
        "reasons": cell("reasons"),
        "hit_kind": str(row.get("hit_kind") or ""),
    }


def _stamp_occurrence(row, *, entity_id, section_label, document_id, document_label,
                      definition_targets, gap_span_ids, open_stitch_slots, reasons):
    stamped = dict(row)
    stamped.update(
        admitted=False,
        formalized=False,
        entity_id=entity_id,
        section_label=section_label,
        document_id=document_id,
        document_label=document_label,
        definition_targets=list(definition_targets),
        gap_span_ids=list(gap_span_ids),
        open_stitch_slots=list(open_stitch_slots),
        reasons=list(reasons),
    )
    return _occurrence_record(stamped)


def stitch_entities(cache, inputs, *, spans, logic_index, destination, revision="", upload=False, verify_lake=False, check=None):
    """Assemble ready sealed spans onto prepared sections. Does not claim or admit."""
    import pyarrow as pa
    from ipfs_datasets_py.logic.autoformal.entity_cache import proof_sources_for_section, term_category
    from ipfs_datasets_py.logic.autoformal.lean_units import lake_receipt
    from ipfs_datasets_py.logic.autoformal.meta_ontology import normalize_lookup, occurrences_for_span
    from ipfs_datasets_py.logic.autoformal.span_cache import span_groups_from_parquet

    inputs.verify_full()
    spans = _path(spans)
    logic_index = _path(logic_index)
    _require(spans.name == "sealed-spans.parquet", "span grouping reads sealed-spans.parquet only")
    _require(logic_index.name == "kg-logic-index.parquet", "citation closure reads the logic index")
    index_bytes = logic_index.read_bytes()
    grouped = span_groups_from_parquet(spans, revision=revision or None)
    cites = _graph_cites(logic_index)
    _require(logic_index.read_bytes() == index_bytes, "logic index bytes changed")
    cache.assign_span_context(grouped["rows"])
    cache.assign_definition_closure(cites)
    cache.record_inconsistencies(grouped["rows"], grouped["terms"])
    findings = cache.list_inconsistencies()
    directory = _path(destination, exists=False) / "autoformal" / "uscode"
    directory.mkdir(parents=True, exist_ok=True)
    _require(directory.resolve(strict=True) == directory, "stitch directory is aliased")
    for refused in _REFUSED_OUTPUTS:
        _require(refused not in STITCH_FILES, "refusing to replace " + refused)
    previous = {}
    lean_path = directory / "lean-units.parquet"
    if lean_path.is_file() and not lean_path.is_symlink():
        import pyarrow.parquet as pq
        for row in pq.read_table(lean_path).to_pylist():
            previous[(str(row.get("unit_kind") or ""), str(row.get("unit_id") or ""))] = row
    ready = set(grouped["ready"])
    neighborhoods, statutes, terms_out, occurrences = [], [], {}, []
    checked_terms = 0
    for page in cache.section_context_pages():
        pending = []
        wanted = []
        for context in page:
            entity_id = str(context.get("entity_id") or "")
            document_id = _document_id(context)
            pending.append((context, entity_id, document_id))
            if entity_id:
                wanted.append(entity_id)
            if document_id:
                wanted.append(document_id)
        labels = _labels_for(cache, wanted)
        for context, entity_id, document_id in pending:
            legal_id = str(context.get("span_legal_id") or "")
            section_label = labels.get(entity_id, "")
            document_label = labels.get(document_id, "")
            targets = list(context.get("definition_targets") or [])
            slots = list(context.get("open_stitch_slots") or [])
            reasons = list(context.get("reasons") or [])
            if legal_id in ready:
                clauses = grouped["statutes"].get(legal_id, [])
                gaps = [item["source_span_id"] for item in grouped["gaps"].get(legal_id, [])]
                proof = proof_sources_for_section(context, grouped["rows"], grouped["terms"])
                neighborhoods.append({
                    "admitted": False,
                    "definition_targets": _cell(targets),
                    "entity_id": entity_id,
                    "formalized": False,
                    "gap_span_ids": _cell(gaps),
                    "open_stitch_slots": _cell(slots),
                    "reasons": _cell(reasons),
                    "sealed_span_ids": _cell([clause["source_span_id"] for clause in clauses]),
                    "source_hashes": _cell([clause["source_sha256"] for clause in clauses]),
                    "span_legal_id": legal_id,
                })
                statute_overflow = []
                for item in proof["overflow"]:
                    if not item.get("term_id"):
                        statute_overflow = list(item.get("overflow_ids") or [])
                verify = bool(verify_lake)
                receipt = lake_receipt(proof["statute_lean"], previous.get(("statute", legal_id)), verify=verify, check=check)
                statutes.append({
                    "admitted": False,
                    "count": min(len(clauses), 24),
                    "formalized": False,
                    "lake_error": receipt["lake_error"],
                    "lake_ok": receipt["lake_ok"],
                    "lean_source": proof["statute_lean"],
                    "overflow_ids": _cell(statute_overflow),
                    "source_sha256": receipt["source_sha256"],
                    "unit_id": legal_id,
                    "unit_kind": "statute",
                })
                for unit in proof["term_units"]:
                    current = terms_out.get(unit["term_id"])
                    if current is not None and len(current["statute_ids"]) >= len(unit["statute_ids"]):
                        continue
                    terms_out[unit["term_id"]] = unit
                for clause in clauses:
                    for occurrence in occurrences_for_span(clause):
                        occurrences.append(_stamp_occurrence(
                            occurrence,
                            entity_id=entity_id,
                            section_label=section_label,
                            document_id=document_id,
                            document_label=document_label,
                            definition_targets=targets,
                            gap_span_ids=gaps,
                            open_stitch_slots=slots,
                            reasons=reasons,
                        ))
                label_reasons = reasons
            else:
                gaps = list(context.get("gap_span_ids") or [])
                label_reasons = list(reasons)
                if "section_not_ready" not in label_reasons:
                    label_reasons.append("section_not_ready")
            occurrences.append(_stamp_occurrence(
                {
                    "act": "",
                    "category": "",
                    "formula": "",
                    "hit_kind": "label",
                    "kind": "",
                    "legal_id": legal_id,
                    "modality": "",
                    "normalized": normalize_lookup(section_label),
                    "object": "",
                    "participant": "",
                    "span_id": "",
                    "state": "",
                    "surface": section_label,
                    "term_id": "",
                },
                entity_id=entity_id,
                section_label=section_label,
                document_id=document_id,
                document_label=document_label,
                definition_targets=targets,
                gap_span_ids=gaps,
                open_stitch_slots=slots,
                reasons=label_reasons,
            ))
    term_index = []
    for term in grouped["terms"]:
        term_index.append({
            "admitted": False,
            "category": term_category(term["kind"], term["value"]),
            "formalized": False,
            "kind": term["kind"],
            "overflow": len(term["statute_ids"]) > 16,
            "statute_ids": _cell(term["statute_ids"]),
            "term_id": term["term_id"],
            "value": term["value"],
        })
    lean_rows = list(statutes)
    for term_id, unit in sorted(terms_out.items()):
        verify = bool(verify_lake) and checked_terms < 8
        if verify:
            checked_terms += 1
        receipt = lake_receipt(unit["lean"], previous.get(("term", term_id)), verify=verify, check=check)
        lean_rows.append({
            "admitted": False,
            "count": unit["count"],
            "formalized": False,
            "lake_error": receipt["lake_error"],
            "lake_ok": receipt["lake_ok"],
            "lean_source": unit["lean"],
            "overflow_ids": _cell(unit["overflow_ids"]),
            "source_sha256": receipt["source_sha256"],
            "unit_id": term_id,
            "unit_kind": "term",
        })
    neighborhoods.sort(key=lambda row: row["entity_id"])
    term_index.sort(key=lambda row: row["term_id"])
    findings = sorted(findings, key=lambda row: row["inconsistency_id"])
    inconsistency_rows = []
    for row in findings:
        overflow_ids = []
        if row["kind"] == "lean_unit_overflow" and ": " in row["evidence"]:
            overflow_ids = [item for item in row["evidence"].split(": ", 1)[1].split(",") if item]
        inconsistency_rows.append({
            "admitted": False,
            "entity_id": row["entity_id"],
            "evidence": row["evidence"],
            "formalized": False,
            "inconsistency_id": row["inconsistency_id"],
            "kind": row["kind"],
            "overflow_ids": _cell(overflow_ids),
            "span_id": row["span_id"],
            "term_id": row["term_id"],
        })
    lean_rows.sort(key=lambda row: (row["unit_kind"], row["unit_id"]))
    occurrences.sort(key=lambda row: (
        row["hit_kind"], row["normalized"], row["span_id"], row["kind"], row["term_id"],
        row["entity_id"], row["legal_id"], row["surface"],
    ))
    tables = {
        "inconsistencies.parquet": inconsistency_rows,
        "lean-units.parquet": lean_rows,
        "logic-occurrences.parquet": occurrences,
        "section-neighborhoods.parquet": neighborhoods,
        "term-index.parquet": term_index,
    }
    fingerprint = hashlib.sha256(_cell(tables).encode("utf-8")).hexdigest()
    schemas = {
        "section-neighborhoods.parquet": pa.schema([
            ("admitted", pa.bool_()), ("definition_targets", pa.string()), ("entity_id", pa.string()),
            ("formalized", pa.bool_()), ("gap_span_ids", pa.string()), ("open_stitch_slots", pa.string()),
            ("reasons", pa.string()), ("sealed_span_ids", pa.string()), ("source_hashes", pa.string()),
            ("span_legal_id", pa.string()),
        ]),
        "term-index.parquet": pa.schema([
            ("admitted", pa.bool_()), ("category", pa.string()), ("formalized", pa.bool_()),
            ("kind", pa.string()), ("overflow", pa.bool_()), ("statute_ids", pa.string()),
            ("term_id", pa.string()), ("value", pa.string()),
        ]),
        "inconsistencies.parquet": pa.schema([
            ("admitted", pa.bool_()), ("entity_id", pa.string()), ("evidence", pa.string()),
            ("formalized", pa.bool_()), ("inconsistency_id", pa.string()), ("kind", pa.string()),
            ("overflow_ids", pa.string()), ("span_id", pa.string()), ("term_id", pa.string()),
        ]),
        "lean-units.parquet": pa.schema([
            ("admitted", pa.bool_()), ("count", pa.int64()), ("formalized", pa.bool_()),
            ("lake_error", pa.string()), ("lake_ok", pa.bool_()), ("lean_source", pa.string()),
            ("overflow_ids", pa.string()), ("source_sha256", pa.string()), ("unit_id", pa.string()),
            ("unit_kind", pa.string()),
        ]),
        "logic-occurrences.parquet": pa.schema([
            ("admitted", pa.bool_()), ("formalized", pa.bool_()), ("surface", pa.string()),
            ("normalized", pa.string()), ("category", pa.string()), ("kind", pa.string()),
            ("term_id", pa.string()), ("modality", pa.string()), ("formula", pa.string()),
            ("participant", pa.string()), ("act", pa.string()), ("object", pa.string()),
            ("state", pa.string()), ("span_id", pa.string()), ("legal_id", pa.string()),
            ("entity_id", pa.string()), ("section_label", pa.string()), ("document_id", pa.string()),
            ("document_label", pa.string()), ("definition_targets", pa.string()),
            ("gap_span_ids", pa.string()), ("open_stitch_slots", pa.string()),
            ("reasons", pa.string()), ("hit_kind", pa.string()),
        ]),
    }
    written = [_write_stitch_parquet(directory, name, tables[name], schemas[name]) for name in STITCH_FILES]
    _require(logic_index.read_bytes() == index_bytes, "logic index bytes changed")
    inputs.verify_full()
    receipt = {
        "admitted": False, "files": [path.name for path in written], "fingerprint": fingerprint,
        "formalized": False, "not_ready": list(grouped["not_ready"]), "performed": True,
        "ready": list(grouped["ready"]), "revision": revision, "skipped": False, "uploaded": False,
    }
    if upload:
        if cache._meta("stitch_fingerprint") == fingerprint:
            receipt["skipped"] = True
        else:
            published = _publish_stitch_files(written, fingerprint=fingerprint)
            if published.get("uploaded"):
                cache._set_meta("stitch_fingerprint", fingerprint)
            receipt["uploaded"] = bool(published.get("uploaded"))
            receipt["revision"] = str(published.get("revision") or revision)
    return receipt


def _scan_sealed_mentions(path, query, occurrences):
    """Read sealed span text for one missed phrase. Does not write the span cache."""
    import pyarrow.parquet as pq
    from ipfs_datasets_py.logic.autoformal.meta_ontology import mention_for_span
    from ipfs_datasets_py.logic.autoformal.span_cache import export_status

    path = _path(path)
    _require(path.name == "sealed-spans.parquet", "span scan reads sealed-spans.parquet only")
    stamps = {}
    for row in occurrences:
        legal_id = str(row.get("legal_id") or "")
        if legal_id and legal_id not in stamps:
            stamps[legal_id] = row
    found = []
    for raw in pq.read_table(path).to_pylist():
        if export_status(raw) != "sealed":
            continue
        mention = mention_for_span(raw, query)
        if mention is None:
            continue
        stamp = stamps.get(str(mention.get("legal_id") or ""))
        if stamp:
            for key in (
                "entity_id", "section_label", "document_id", "document_label",
                "definition_targets", "gap_span_ids", "open_stitch_slots", "reasons",
            ):
                if stamp.get(key) not in (None, ""):
                    mention[key] = stamp[key]
        found.append(mention)
    return found


def lookup_from_stitch(query, stitch_dir, spans=None):
    """Read logic-occurrences.parquet. Scan sealed span text only when nothing hits."""
    import pyarrow.parquet as pq
    from ipfs_datasets_py.logic.autoformal.meta_ontology import lookup_logic

    directory = _path(stitch_dir) / "autoformal" / "uscode"
    path = directory / "logic-occurrences.parquet"
    _require(path.is_file() and not path.is_symlink(), "lookup reads logic-occurrences.parquet")
    rows = pq.read_table(path).to_pylist()
    try:
        result = lookup_logic(rows, query)
    except ValueError as exc:
        raise EntityIngestError(str(exc)) from exc
    if result["rows"] or spans is None:
        return result
    mentions = _scan_sealed_mentions(spans, query, rows)
    if not mentions:
        return result
    return lookup_logic(list(rows) + mentions, query)


def _cache_type():
    # Existing imported HACC modules must fail; changing sys.path cannot repair a
    # process that already selected a different compiler/parser tree.
    if str(ROOT) in sys.path:
        sys.path.remove(str(ROOT))
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    pin = importlib.import_module("ipfs_datasets_py.logic.autoformal.tree_pin")
    module = importlib.import_module("ipfs_datasets_py.logic.autoformal.entity_cache")
    for value, filename in ((pin, "tree_pin.py"), (module, "entity_cache.py")):
        _require(Path(value.__file__).resolve() == ROOT / "ipfs_datasets_py/logic/autoformal" / filename,
                 "entity ingestion requires the canonical workspace tree")
    pin.require_workspace_logic_tree()
    _require(module.SCHEMA == "uscode-autoformal-entity-cache/v2", "entity ingestion requires the v2 cache")
    _require(module.MAX_RESUME_FILE_BYTES == MAX_RESUME_FILE_BYTES, "entity resume size policies differ")
    return module.EntityCache


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path)
    parser.add_argument("--relationships", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--upload-dir", type=Path)
    parser.add_argument("--batch", type=_batch_argument, default=512)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--poll", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--upload", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--prepare", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stitch", action="store_true")
    parser.add_argument("--spans", type=Path)
    parser.add_argument("--logic-index", type=Path)
    parser.add_argument("--span-revision", default="")
    parser.add_argument("--stitch-dir", type=Path)
    parser.add_argument("--stitch-upload", action="store_true")
    parser.add_argument("--stitch-lake", action="store_true")
    parser.add_argument("--lookup", default="")
    args = parser.parse_args(argv)
    query = str(args.lookup or "")
    if query.strip() and not args.stitch:
        _require(args.stitch_dir is not None, "lookup reads a stitch directory")
        print(json.dumps(lookup_from_stitch(query, args.stitch_dir, spans=args.spans), sort_keys=True), flush=True)
        return 0
    _require(args.parquet is not None, "entity ingestion reads an entity parquet")
    _require(args.relationships is not None, "entity ingestion reads a relationship parquet")
    _require(args.cache is not None, "entity ingestion reads a cache path")
    if args.stitch:
        _require(args.spans is not None, "stitch reads sealed-spans.parquet")
        _require(args.logic_index is not None, "stitch reads kg-logic-index.parquet")
        _require(args.stitch_dir is not None, "stitch writes an output directory")
        _require(Path(args.spans).name == "sealed-spans.parquet", "span grouping reads sealed-spans.parquet only")
        _require(Path(args.logic_index).name == "kg-logic-index.parquet", "citation closure reads the logic index")
        _path(args.spans)
        _path(args.logic_index)
    cache_path = _path(args.cache, exists=False)
    upload_dir = args.upload_dir or cache_path.parent / "entity-hf-checkpoint-v2"
    with _BoundInputs(args.parquet, args.relationships) as inputs:
        cache_files = (cache_path, Path(str(cache_path) + ".wal"))
        _require(not set(cache_files).intersection((inputs.entities.path, inputs.relationships.path)),
                 "cache or its WAL overlaps an input")
        cache = _cache_type()(cache_path)
        try:
            inputs.verify_full()
            cache.bind_inputs(inputs.manifest, resume=args.resume)
            inputs.verify_full()
            polled = _poll(cache, inputs) if args.poll else {"changed": False, "poll_performed": False}
            enqueued = enqueue_entities(cache, inputs, batch=args.batch)
            prepared = prepare_pending(cache, inputs, batch=args.batch) if args.prepare else {
                "prepared": 0, "admitted": False, "formalized": False}
            stitch = {"admitted": False, "formalized": False, "performed": False, "uploaded": False}
            if args.stitch:
                stitch = stitch_entities(
                    cache,
                    inputs,
                    spans=args.spans,
                    logic_index=args.logic_index,
                    destination=args.stitch_dir,
                    revision=args.span_revision,
                    upload=args.stitch_upload,
                    verify_lake=args.stitch_lake,
                )
            flushed = _flush(cache, upload_dir, upload=args.upload, inputs=inputs)
            inputs.verify_full()
            report = {"admitted": False, "formalized": False,
                "stage": "entities_prepared" if args.prepare else "entities_queued", "enqueued": enqueued,
                "prepared": prepared, "poll": polled, "hf": flushed, "stats": cache.stats(),
                "stitch": stitch}
            if query.strip():
                report["lookup"] = lookup_from_stitch(query, args.stitch_dir, spans=args.spans)
            print(json.dumps(report, sort_keys=True), flush=True)
        finally:
            cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
