#!/usr/bin/env python3
"""Expose exact formula strings from already published legacy logic reports.

This is a lossless text index, not a formula renderer, validator or model run.
Every row points to its original decoded bridge document and immutable report.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import importlib.util
import io
import json
from pathlib import Path
import re

_HELPER = Path(__file__).with_name("publish_legacy_logic_reports.py")
_spec = importlib.util.spec_from_file_location("_formula_report_source", _HELPER)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

SCHEMA = "uscode-report-formula-text/v1"
FIELDS = frozenset({"formula", "proof_input", "event_calculus_formula", "formula_text", "fol_formula", "frame_formula"})
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
_VALIDATION = re.compile(r"(?:valid|parse|syntax|proof|support|loss|error|warning|reason|admit|formaliz|qualif|status|fallback|sanitize|authorit|fidelity|blocker|omitted|missing|coverage)")
_REFERENCE = re.compile(r"(?:sha256|hash|source_id|source_component|target_logic|logic_family|compiler_guidance_source)$")


def _pointer(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _matching(raw, descriptor):
    if len(raw) != descriptor.get("bytes") or report._sha(raw) != descriptor.get("sha256"):
        raise ValueError("report hash or byte count differs from publication")


def load_publication(path):
    """Verify both immutable compressed bytes and complete original report bytes."""
    publication = report._load(report._snapshot(path, 1024 * 1024))
    if publication.get("repository_id") != report.REPOSITORY:
        raise ValueError("publication repository differs from the required dataset")
    if (publication.get("schema") != "uscode-full-logic-report-publication/v1"
            or publication.get("uploaded") is not True or publication.get("dry_run") is not False
            or not re.fullmatch(r"[0-9a-f]{40}", str(publication.get("commit_sha", "")))):
        raise ValueError("a completed immutable full-report publication is required")
    manifest_raw = report._snapshot(publication["manifest"]["path"], 4 * 1024 * 1024)
    _matching(manifest_raw, publication["manifest"])
    manifest = report._load(manifest_raw)
    if manifest.get("repository_id") != report.REPOSITORY:
        raise ValueError("manifest repository differs from the required dataset")
    if manifest.get("schema") != report.SCHEMA or manifest.get("original") != publication.get("original"):
        raise ValueError("publication and report manifest differ")
    for key in ("sha256", "bytes", "path_in_repo"):
        if manifest["report"].get(key) != publication["report"].get(key):
            raise ValueError("publication and report descriptor differ")
    packed = report._snapshot(publication["report"]["path"], report.MAX_GZIP_BYTES)
    _matching(packed, publication["report"])
    with gzip.GzipFile(fileobj=io.BytesIO(packed), mode="rb") as stream:
        raw = stream.read(report.MAX_BYTES + 1)
    if len(raw) > report.MAX_BYTES:
        raise ValueError("report exceeds decompressed byte bound")
    _matching(raw, publication["original"])
    receipt = report._load(raw)
    if receipt.get("schema_version") != "legacy-span-cuda-diagnostic/v1" or not isinstance(receipt.get("rows"), list):
        raise ValueError("expected original legacy diagnostic receipt")
    return publication, receipt


def _walk(value, pointer, ancestors=()):
    if isinstance(value, dict):
        validation = {key: item for key, item in value.items()
                      if key not in FIELDS and _VALIDATION.search(key.lower())}
        references = {key: item for key, item in value.items()
                      if key not in FIELDS and _REFERENCE.search(key.lower())}
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            reported = {key: item for key, item in metadata.items()
                        if _VALIDATION.search(key.lower()) or _REFERENCE.search(key.lower())}
            if reported:
                validation["metadata"] = reported
        if validation or references:
            ancestors += ({"pointer": pointer, "reported_validation": validation,
                           "reported_references": references},)
        for key in sorted(value):
            item = value[key]
            child = pointer + "/" + _pointer(key)
            if key in FIELDS and isinstance(item, str) and item.strip():
                yield key, item, child, ancestors
            elif isinstance(item, (dict, list)):
                yield from _walk(item, child, ancestors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, pointer + "/" + str(index), ancestors)


def formula_rows(publication, receipt, counts):
    for source in receipt["rows"]:
        counts["source_span_observations"] += 1
        text = source.get("text")
        if not isinstance(text, str) or source.get("source_sha256") != report._sha(text.encode()):
            raise ValueError("source span text hash differs")
        target = source.get("logic_target_observation") or {}
        if not isinstance(target.get("document"), dict):
            counts["unavailable_document_count"] += 1
            continue
        document, verification = report._document(target)
        counts["available_document_count"] += 1
        counts["identity_verified_document_count"] += verification["status"] == "verified"
        views = document.get("views", {})
        if not isinstance(views, dict):
            raise ValueError("captured document views must be an object")
        for view_name in sorted(views):
            view = views[view_name]
            if not isinstance(view, dict):
                continue
            for field, text, pointer, metadata in _walk(view, "/views/" + _pointer(view_name)):
                counts["formula_row_count"] += 1
                source_id = next((item["reported_references"]["source_id"] for item in reversed(metadata)
                                  if isinstance(item["reported_references"].get("source_id"), str)), None)
                fallback = True if source_id and source_id.startswith(("tdfol:text:", "dcec:fallback:")) else None
                yield {"source_text": source.get("text"), "formula_text": text,
                    "view_name": view_name, "producer_origin": "source_bridge_target",
                    "fallback_origin": fallback, "producer_record_source_id": source_id,
                    "source_span_id": source.get("source_span_id"), "legal_id": source.get("legal_id"),
                    "format": str(view.get("format", "")), "formula_field": field,
                    "formula_sha256": report._sha(text.encode()), "learned_formula_generation": False,
                    "reported_validation_json": report._json(metadata).decode(),
                    "independent_validation": False, "admitted": False, "training_qualified": False,
                    "source_report_path_in_repo": publication["report"]["path_in_repo"],
                    "source_report_revision": publication["commit_sha"],
                    "source_report_sha256": publication["report"]["sha256"],
                    "source_receipt_sha256": publication["original"]["sha256"],
                    "source_document_sha256": verification["observed_compact_sha256"],
                    "recorded_document_sha256": target.get("document_sha256"),
                    "recorded_document_identity_status": verification["status"],
                    "decoded_document_json_pointer": pointer}


def export(publications, output_dir, *, max_rows=MAX_ROWS, max_bytes=MAX_OUTPUT_BYTES):
    if not 0 < max_rows <= MAX_ROWS or not 0 < max_bytes <= MAX_OUTPUT_BYTES:
        raise ValueError("output bounds exceed fixed export limits")
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows, encoded, bindings, seen, counts = [], [], [], set(), Counter()
    total = 0
    for path in sorted(map(Path, publications)):
        publication, receipt = load_publication(path)
        identity = publication["report"]["sha256"]
        if identity in seen:
            continue
        seen.add(identity)
        bindings.append({"revision": publication["commit_sha"],
            "report": {key: publication["report"][key] for key in ("path_in_repo", "sha256", "bytes")},
            "original": publication["original"]})
        for row in formula_rows(publication, receipt, counts):
            raw = json.dumps(row, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            total += len(raw)
            if len(rows) >= max_rows or total > max_bytes:
                raise ValueError("formula export exceeds row or byte bound; nothing was written")
            counts["fallback_formula_occurrence_count"] += row["fallback_origin"] is True
            rows.append(row); encoded.append(raw)
    if not rows:
        raise ValueError("no actual emitted formula strings found")
    jsonl = b"".join(encoded)
    schema = pa.schema([(key, pa.bool_() if isinstance(value, bool) or key == "fallback_origin" else pa.string()) for key, value in rows[0].items()])
    table = pa.Table.from_pylist(rows, schema=schema)
    parquet_buffer = io.BytesIO()
    pq.write_table(table, parquet_buffer, compression="zstd", version="2.6")
    parquet = parquet_buffer.getvalue()
    if len(parquet) > max_bytes or len(parquet) + len(jsonl) > max_bytes:
        raise ValueError("combined formula export exceeds byte bound; nothing was written")
    digest = report._sha(jsonl)
    output = Path(output_dir).absolute()
    files = {}
    for kind, raw, suffix in (("jsonl", jsonl, ".jsonl"), ("parquet", parquet, ".parquet")):
        path = output / (digest + suffix)
        files[kind] = {"path": str(path), "filename": path.name, "sha256": report._sha(raw), "bytes": len(raw)}
    manifest = {"schema": SCHEMA, "counts": dict(sorted(counts.items())), "source_reports": bindings,
        "formula_fields": sorted(FIELDS), "files": files,
        "producer_origin": "source_bridge_target", "learned_formula_generation": False,
        "independent_validation": False, "admitted": False, "training_qualified": False,
        "notes": "Exact captured strings; repeated occurrences retained by document pointer. Reported syntax or validity flags are provenance, not independent checks or Lake admission."}
    manifest_raw = report._json(manifest)
    if len(manifest_raw) + len(parquet) + len(jsonl) > max_bytes:
        raise ValueError("combined formula export exceeds byte bound; nothing was written")
    report._write(files["jsonl"]["path"], jsonl)
    report._write(files["parquet"]["path"], parquet)
    manifest_path = output / (digest + ".manifest.json")
    report._write(manifest_path, manifest_raw)
    return {"manifest_path": str(manifest_path), **manifest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = export(args.publication, args.output_dir)
    print(json.dumps({"manifest_path": result["manifest_path"], "counts": result["counts"], "files": result["files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
