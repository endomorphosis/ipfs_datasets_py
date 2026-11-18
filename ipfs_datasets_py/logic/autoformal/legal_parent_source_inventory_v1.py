"""Source-only metadata for an exact, sparse historical-parent selection.

The existing parent parser replays the complete pinned artifact and every
requested physical row before projection. This inventory is a selected-source
profile, not a release-format USCodeSourceInventory or SourcePartitions. It
contains no source text, cache targets, model identity or training permission.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import legal_parent_parquet_pages as pages

SCHEMA = "legal-parent-selected-source-inventory/v1"
PROFILE = "historical-parent-selected-source-metadata/v1"
SCOPE = "declared_physical_selection_only"
CONTENT_NORMALIZATION = "unicode-whitespace-casefold-v1"
MAX_SELECTED_ROWS = 32
MAX_INPUT_BYTES = 64 * 1024**2
MAX_REPORT_BYTES = 2 * 1024**2
MAX_STRING_BYTES = 8 * 1024**2
MAX_JSON_NODES = 262144
MAX_JSON_DEPTH = 16
MAX_COLLECTION_ITEMS = 65536
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = {"repository", "revision", "path_in_repo", "local_path",
    "sha256", "bytes", "row_count", "profile"}
_IDENTITY_FIELDS = ("ipfs_cid", "title_number", "section_number")
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_authority_authenticated",
    "official_edition_correspondence_verified", "original_producer_occurrence_attested",
    "source_equivalence_proven", "context_permission_verified", "context_closure_verified",
    "source_encoder_authenticated", "global_holdout_verified", "training_qualified",
    "evaluation_gold_qualified", "model_executed", "training_executed", "database_executed",
    "prover_executed", "Lean_admitted", "convergence_proved", "admitted"), False)


class SelectedParentSourceInventoryError(ValueError):
    """Source originals, selected coverage, finite bounds or projection differ."""


def _need(condition, message):
    if not condition:
        raise SelectedParentSourceInventoryError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
        "independent lowercase SHA256 required: " + label)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def _snapshot(value, label, maximum=MAX_INPUT_BYTES):
    """Refuse oversized shapes before serialization, then detach exact JSON.

    Character counts precede UTF-8 allocation. The aggregate string/node/depth
    guards bound traversal and copying; the final canonical bound includes all
    punctuation and escaped characters. No project decoder is invoked here.
    """
    nodes = string_bytes = 0
    active = set()

    def visit(item, depth):
        nonlocal nodes, string_bytes
        nodes += 1
        _need(nodes <= MAX_JSON_NODES and depth <= MAX_JSON_DEPTH,
            label + " exceeds JSON node or depth bounds")
        kind = type(item)
        if kind is str:
            _need(len(item) <= min(MAX_STRING_BYTES, maximum),
                label + " exceeds its string character bound")
            size = len(item.encode("utf-8"))
            string_bytes += size
            _need(size <= MAX_STRING_BYTES and string_bytes <= maximum,
                label + " exceeds string or aggregate byte bounds")
            return item
        if item is None or kind is bool:
            return item
        if kind is int:
            _need(-(2**63) <= item < 2**63, label + " integer exceeds signed64 bounds")
            return item
        _need(kind in (dict, list), label + " requires plain finite JSON types")
        _need(len(item) <= MAX_COLLECTION_ITEMS, label + " exceeds collection bounds")
        identity = id(item)
        _need(identity not in active, label + " contains a cyclic collection")
        active.add(identity)
        try:
            if kind is list:
                return [visit(child, depth + 1) for child in item]
            result = {}
            for key, child in item.items():
                _need(type(key) is str and len(key) <= 4096,
                    label + " requires bounded string keys")
                # Keys participate in the same byte budget as scalar strings.
                detached_key = visit(key, depth + 1)
                result[detached_key] = visit(child, depth + 1)
            return result
        finally:
            active.remove(identity)

    try:
        detached = visit(value, 0)
        raw = _wire(detached)
    except (TypeError, UnicodeError, RecursionError, OverflowError, RuntimeError) as exc:
        raise SelectedParentSourceInventoryError("invalid " + label + " JSON") from exc
    _need(len(raw) <= maximum, label + " exceeds canonical byte bound")
    return detached, raw


def _inputs(descriptor, row_report, preflight_report, row_ordinals, row_sha256s,
        descriptor_sha256, row_report_sha256, preflight_sha256):
    for value, label in ((descriptor_sha256, "parent descriptor"),
            (row_report_sha256, "selected row report"), (preflight_sha256, "page preflight")):
        _digest(value, label)
    _need(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_FIELDS,
        "closed complete parent descriptor required")
    _need(type(row_ordinals) is list and 0 < len(row_ordinals) <= MAX_SELECTED_ROWS
        and all(type(row) is int and 0 <= row < 100000 for row in row_ordinals)
        and row_ordinals == sorted(set(row_ordinals)),
        "bounded ordered distinct physical row ordinals required")
    _need(type(row_sha256s) is list and len(row_sha256s) == len(row_ordinals),
        "complete ordered independent row hash population required")
    for value in row_sha256s:
        _digest(value, "selected full raw row")
    _need(type(row_report) is dict and type(row_report.get("rows")) is list
        and len(row_report["rows"]) == len(row_ordinals),
        "complete bounded selected report rows required")
    _need(type(preflight_report) is dict, "plain complete preflight report required")
    originals = (descriptor, row_report, preflight_report, row_ordinals, row_sha256s)
    labels = ("parent descriptor", "selected row report", "page preflight", "row selection", "row commitments")
    captured = [_snapshot(value, label) for value, label in zip(originals, labels, strict=True)]
    bodies, raw = [row[0] for row in captured], [row[1] for row in captured]
    _need(_sha(raw[0]) == descriptor_sha256 and _sha(raw[1]) == row_report_sha256
        and _sha(raw[2]) == preflight_sha256, "independent complete source report pin differs")
    return originals, labels, bodies, raw


def _recheck(originals, labels, expected_raw):
    _need([_snapshot(value, label)[1] for value, label in zip(originals, labels, strict=True)]
        == expected_raw, "source originals changed during replay or projection")


def _project(descriptor, report, ordinals, row_hashes, descriptor_sha256,
        row_report_sha256, preflight_sha256):
    schema = report["source_schema"]
    _need(type(schema) is list and 0 < len(schema) <= 64,
        "bounded complete source schema required")
    fields = [field["name"] for field in schema]
    _need(len(set(fields)) == len(fields), "complete source fields must be distinct")
    rows = []
    for ordinal, pin, observed in zip(ordinals, row_hashes, report["rows"], strict=True):
        raw = observed["raw_row"]
        _need(observed["row_ordinal"] == ordinal and observed["raw_row_sha256"] == pin
            and type(raw) is dict and set(raw) == set(fields) and _sha(_wire(raw)) == pin,
            "exact full physical source row differs from its independent commitment")
        key = {"repository_id": descriptor["repository"], "revision": descriptor["revision"],
            "path_in_repo": descriptor["path_in_repo"], "artifact_sha256": descriptor["sha256"],
            "artifact_bytes": descriptor["bytes"], "parquet_row_index": ordinal}
        identities, statuses = {}, {}
        for name in _IDENTITY_FIELDS:
            value = raw.get(name)
            identities[name] = value if type(value) is str else None
            statuses[name] = ("observed_string" if type(value) is str
                else "missing" if value is None else "unsupported_type")
        text = raw.get("text")
        text_metadata = normalized_sha256 = None
        if type(text) is str:
            encoded = text.encode("utf-8")
            text_metadata = {"sha256": _sha(encoded), "utf8_bytes": len(encoded),
                "unicode_characters": len(text)}
            # Exact documented whitespace/casefold recipe; this is a grouping
            # observation only and establishes no semantic equivalence.
            normalized_sha256 = _sha(" ".join(text.split()).casefold().encode("utf-8"))
            disposition = "stored_text_available" if text else "empty_text"
        else:
            disposition = "missing_text" if text is None else "unsupported_text_type"
        rows.append({"physical_section_id": "sha256:" + _sha(_wire(key)),
            "physical_key": key, "full_raw_row_sha256": pin,
            "text": text_metadata, "normalized_content_sha256": normalized_sha256,
            "observed_identity": identities, "observed_identity_status": statuses,
            "disposition": disposition, "group_id": None, "split": None,
            "inference_view": None, "authority": dict(_AUTHORITY),
            "training_mask": 0, "evaluation_gold_mask": 0})
    selection = {"row_ordinals": ordinals, "expected_row_sha256s": row_hashes}
    selection["selection_sha256"] = _sha(_wire({"schema": "legal-parent-physical-row-selection/v1",
        "parent_descriptor_sha256": descriptor_sha256, **selection}))
    return {"schema": SCHEMA, "profile": PROFILE, "scope": SCOPE,
        "parent": descriptor, "parent_descriptor_sha256": descriptor_sha256,
        "row_report_sha256": row_report_sha256, "preflight_report_sha256": preflight_sha256,
        "selection": selection, "coverage": {"declared_parent_rows": descriptor["row_count"],
            "declared_selected_rows": len(ordinals), "replayed_selected_rows": len(rows),
            "whole_parent_inventoried": False}, "source_schema": schema,
        "source_schema_sha256": report["source_schema_sha256"],
        "content_normalization": CONTENT_NORMALIZATION, "rows": rows,
        "group_id": None, "split": None, "inference_view": None,
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}


def prepare_selected_parent_source_inventory_v1(descriptor, row_report, *,
        expected_descriptor_sha256, expected_row_report_sha256, preflight_report,
        expected_preflight_sha256, row_ordinals, expected_row_sha256s):
    """Replay exact parent bytes, then project all selected source rows.

    Expected hashes/ordinals are independent inputs, not extracted from the
    supplied reports. Current MAX32 selection bounds do not grant whole-parent
    coverage, grouping, train/evaluation assignment or context permission.
    """
    originals, labels, bodies, raw = _inputs(descriptor, row_report, preflight_report,
        row_ordinals, expected_row_sha256s, expected_descriptor_sha256,
        expected_row_report_sha256, expected_preflight_sha256)
    parent, selected, preflight, ordinals, row_hashes = bodies
    try:
        validation = pages.validate_selected_parent_rows(selected, parent,
            expected_report_sha256=expected_row_report_sha256,
            expected_descriptor_sha256=expected_descriptor_sha256,
            preflight_report=preflight, expected_preflight_sha256=expected_preflight_sha256,
            row_ordinals=ordinals, expected_row_sha256s=row_hashes)
        _need(validation == {"valid": True, "row_count": len(ordinals), "all_authority_false": True},
            "existing public parent row validation did not verify complete selection")
        _recheck(originals, labels, raw)
        _need([_snapshot(value, label)[1] for value, label in zip(bodies, labels, strict=True)] == raw,
            "delegated source owner mutated its input snapshot")
        result = _project(parent, selected, ordinals, row_hashes,
            expected_descriptor_sha256, expected_row_report_sha256, expected_preflight_sha256)
        _recheck(originals, labels, raw)
        return _snapshot(result, "selected source inventory", MAX_REPORT_BYTES)[0]
    except (pages.ParentParquetPagesError, KeyError, TypeError, UnicodeError, OSError) as exc:
        raise SelectedParentSourceInventoryError("selected parent source replay failed") from exc


def selected_parent_source_inventory_sha256(report):
    """Hash bounded canonical metadata; this alone does not validate originals."""
    return _sha(_snapshot(report, "selected source inventory", MAX_REPORT_BYTES)[1])


def validate_selected_parent_source_inventory_v1(report, descriptor, row_report, *,
        expected_report_sha256, expected_descriptor_sha256, expected_row_report_sha256,
        preflight_report, expected_preflight_sha256, row_ordinals, expected_row_sha256s):
    """Regenerate the entire report from all exact original inputs and pins."""
    _digest(expected_report_sha256, "selected source inventory")
    snapshot, raw = _snapshot(report, "selected source inventory", MAX_REPORT_BYTES)
    _need(_sha(raw) == expected_report_sha256, "independent inventory report pin differs")
    expected = prepare_selected_parent_source_inventory_v1(descriptor, row_report,
        expected_descriptor_sha256=expected_descriptor_sha256,
        expected_row_report_sha256=expected_row_report_sha256, preflight_report=preflight_report,
        expected_preflight_sha256=expected_preflight_sha256, row_ordinals=row_ordinals,
        expected_row_sha256s=expected_row_sha256s)
    _need(_snapshot(report, "selected source inventory", MAX_REPORT_BYTES)[1] == raw,
        "inventory report changed during original-bound validation")
    _need(_wire(expected) == raw, "inventory differs from exact selected source regeneration")
    return {"valid": True, "row_count": len(snapshot["rows"]),
        "whole_parent_inventoried": False, "all_authority_false": True}


__all__ = ["SCHEMA", "PROFILE", "SCOPE", "CONTENT_NORMALIZATION", "MAX_SELECTED_ROWS",
    "SelectedParentSourceInventoryError", "prepare_selected_parent_source_inventory_v1",
    "validate_selected_parent_source_inventory_v1", "selected_parent_source_inventory_sha256"]
