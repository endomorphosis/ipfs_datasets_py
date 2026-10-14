"""Literal parent-field views with independently regenerated physical custody.

Offsets address the exact decoded Parquet string field, without normalization.
They never address Parquet file bytes or original HTML. Flattened strings and
producer-supplied subsection fields cannot recover governing statutory regions.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from . import legal_parent_parquet_pages as pages

SCHEMA = "legal-parent-text-view-population/v1"
VIEW_SCHEMA = "legal-parent-literal-field-view/v1"
SELECTOR_SCHEMA = "legal-parent-literal-field-occurrence/v1"
PROFILE = "exact_parquet_text_field_unclassified_regions/v1"
COORDINATE_ORIGIN = {
    "field": "text", "normalization": "none",
    "characters": "Unicode code points in exact decoded original Parquet field; half-open",
    "bytes": "UTF8 encoding of exact decoded original Parquet field; half-open",
    "parquet_file_byte_mapping_verified": False, "raw_html_byte_mapping_verified": False,
}
NOTE_MARKERS = ("Historical and Revision Notes", "Statutory Notes and Related Subsidiaries",
    "Editorial Notes", "Prior Provisions", "Amendments", "Effective Date",
    "Short Title", "References in Text", "Codification")
DEFAULT_LIMITS = {"max_views": 32, "max_text_bytes": 8 * 1024**2,
    "max_total_text_bytes": 32 * 1024**2, "max_markers": 4096,
    "max_occurrences": 4096, "max_selector_bytes": 1024**2,
    "max_report_bytes": 64 * 1024**2, "max_observation_bytes": 8 * 1024**2}
AUTHORITY = {**pages.AUTHORITY, **dict.fromkeys(("source_region_roles_verified",
    "governing_body_selected", "source_text_html_bound", "formalization_eligible",
    "accepted_graph_view_enabled", "training_gold_qualified"), False)}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class ParentTextViewsError(ValueError):
    """A complete independent custody pin, exact coordinate or bound differs."""


def _need(ok, message):
    if not ok:
        raise ParentTextViewsError(message)


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "independent lowercase SHA256 required")


def _wire(value, maximum=DEFAULT_LIMITS["max_report_bytes"]):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ParentTextViewsError("finite canonical UTF8 observations required") from exc
    _need(len(raw) <= maximum, "complete observation byte bound exceeded; no truncation")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _limits(value):
    _need(value is None or type(value) is dict, "lower-only view limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key],
            "unknown or raised parent text-view limit: " + str(key))
        result[key] = bound
    return result


def parent_text_views_report_sha256(report):
    """FULL canonical report SHA256, including its text_views_sha256 seal."""
    return _digest(report)


def _ranges(text, literal, maximum):
    start = 0; ranges = []
    while True:
        at = text.find(literal, start)
        if at < 0:
            return ranges
        _need(len(ranges) < maximum, "complete overlapping occurrence bound exceeded; no selection")
        ranges.append((at, at + len(literal)))
        start = at + 1


def _byte_positions(text, positions):
    # Only bounded requested boundaries are retained; no per-character prefix
    # array and no repeated full-prefix UTF8 copies for many overlapping matches.
    result = {}; previous = 0; count = 0
    for position in sorted(set(positions)):
        count += len(text[previous:position].encode("utf-8"))
        result[position] = count; previous = position
    return result


def _markers(text, law_name, bounds, budget):
    literals = [("literal_note_header_candidate", marker, "fixed_literal_marker_profile") for marker in NOTE_MARKERS]
    if type(law_name) is str and law_name:
        _need(len(law_name.encode("utf-8")) <= bounds["max_selector_bytes"], "declared heading literal exceeds bound")
        literals.insert(0, ("declared_law_name_literal", law_name, "raw_row.law_name"))
    pending = []
    for kind, literal, origin in literals:
        found = _ranges(text, literal, bounds["max_markers"])
        _need(budget["markers"] + len(found) <= bounds["max_markers"], "complete population marker bound exceeded")
        budget["markers"] += len(found)
        for start, end in found:
            pending.append((start, end, kind, literal, origin))
    offsets = _byte_positions(text, [position for item in pending for position in item[:2]])
    result = []
    for start, end, kind, literal, origin in sorted(pending):
        observation = {"marker_kind": kind, "marker_text": literal, "marker_origin": origin,
            "char_start": start, "char_end": end, "utf8byte_start": offsets[start], "utf8byte_end": offsets[end],
            "text_sha256": hashlib.sha256(literal.encode("utf-8")).hexdigest(), "legal_role_verified": False}
        observation["marker_sha256"] = _digest(observation)
        budget["observation_bytes"] += len(_wire(observation))
        _need(budget["observation_bytes"] <= bounds["max_observation_bytes"], "aggregate marker byte bound exceeded before retention")
        result.append(observation)
    return result


def _view(row, descriptor, bounds, budget):
    body = row["raw_row"]; text = body.get("text")
    envelope = {"row_ordinal": row["row_ordinal"], "row_group": row["row_group"],
        "row_group_ordinal": row["row_group_ordinal"], "raw_row_sha256": row["raw_row_sha256"],
        "text_view": None, "issues": [], "authority": dict(AUTHORITY)}
    if type(text) is not str or not text:
        envelope["disposition"] = "unresolved_missing_empty_or_nontext_original_field"
        envelope["issues"].append({"code": "original_text_field_missing_empty_or_nontext"})
        return envelope
    raw = text.encode("utf-8")
    _need(len(raw) <= bounds["max_text_bytes"], "literal original text-field byte bound exceeded")
    budget["text_bytes"] += len(raw)
    _need(budget["text_bytes"] <= bounds["max_total_text_bytes"], "complete text population byte bound exceeded before retention")
    identity = {"repository": descriptor["repository"], "revision": descriptor["revision"],
        "path_in_repo": descriptor["path_in_repo"], "file_sha256": descriptor["sha256"],
        "file_bytes": descriptor["bytes"], "file_row_count": descriptor["row_count"],
        "row_ordinal": row["row_ordinal"], "row_group": row["row_group"],
        "row_group_ordinal": row["row_group_ordinal"], "raw_row_sha256": row["raw_row_sha256"], "field": "text"}
    region = {"region_kind": "entire_text_unclassified", "char_start": 0, "char_end": len(text),
        "utf8byte_start": 0, "utf8byte_end": len(raw), "legal_role_verified": False}
    region["region_id"] = _digest({"source_identity": identity, "region": region})
    view = {"schema": VIEW_SCHEMA, "profile": PROFILE, "source_identity": identity,
        "source_identity_sha256": _digest(identity), "coordinate_origin": deepcopy(COORDINATE_ORIGIN),
        "text": text, "text_sha256": hashlib.sha256(raw).hexdigest(), "char_count": len(text), "utf8_bytes": len(raw),
        "regions": [region], "marker_observations": _markers(text, body.get("law_name"), bounds, budget),
        "producer_segmentation_fields_are_observations_only": True,
        "original_source_markup_recovered": False, "authority": dict(AUTHORITY)}
    view["view_sha256"] = _digest(view)
    envelope["text_view"] = view
    envelope["disposition"] = "available_literal_field_unclassified_regions"
    envelope["issues"].append({"code": "flattened_source_region_roles_unresolved"})
    return envelope


def prepare_parent_text_views(selected_rows_report, *, expected_selected_rows_report_sha256,
        parent_descriptor, expected_parent_descriptor_sha256, preflight_report, expected_preflight_sha256,
        row_ordinals, expected_row_sha256s, page_limits=None, limits=None):
    """Replay every requested physical row before retaining literal field views."""
    bounds = _limits(limits)
    _sha(expected_selected_rows_report_sha256)
    _wire(selected_rows_report, bounds["max_report_bytes"])
    _need(type(selected_rows_report) is dict and type(selected_rows_report.get("rows")) is list
        and 0 < len(selected_rows_report["rows"]) <= bounds["max_views"], "bounded complete selected-row view population required")
    pages.validate_selected_parent_rows(selected_rows_report, parent_descriptor,
        expected_report_sha256=expected_selected_rows_report_sha256,
        expected_descriptor_sha256=expected_parent_descriptor_sha256, preflight_report=preflight_report,
        expected_preflight_sha256=expected_preflight_sha256, row_ordinals=row_ordinals,
        expected_row_sha256s=expected_row_sha256s, limits=page_limits)
    budget = {"text_bytes": 0, "markers": 0, "observation_bytes": 0}
    views = [_view(row, parent_descriptor, bounds, budget) for row in selected_rows_report["rows"]]
    report = {"schema": SCHEMA, "profile": PROFILE, "limits": bounds,
        "expected_selected_rows_report_sha256": expected_selected_rows_report_sha256,
        "expected_parent_descriptor_sha256": expected_parent_descriptor_sha256,
        "expected_preflight_sha256": expected_preflight_sha256,
        "requested_row_ordinals": deepcopy(row_ordinals), "expected_row_sha256s": deepcopy(expected_row_sha256s),
        "selected_rows_report": deepcopy(selected_rows_report), "row_count": len(views), "views": views,
        "population_complete": True, "complete_requested_physical_rows_replayed": True,
        "all_original_row_fields_retained": True, "total_text_utf8_bytes": budget["text_bytes"],
        "marker_count": budget["markers"], "whole_parent_population_covered": False,
        "coordinate_origin": deepcopy(COORDINATE_ORIGIN), "authority": dict(AUTHORITY)}
    report["text_views_sha256"] = _digest(report)
    _wire(report, bounds["max_report_bytes"])
    return report


def validate_parent_text_views(report, selected_rows_report, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(parent_text_views_report_sha256(report) == expected_report_sha256, "independent FULL text-view report pin differs")
    expected = prepare_parent_text_views(selected_rows_report, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "text views differ from complete fixed-parent regeneration")
    return {"valid": True, "row_count": expected["row_count"], "source_region_roles_verified": False,
        "legal_semantic_acceptance": False}


def _selector(view, char_start, char_end, bounds, byte_positions=None):
    """Internal geometry owner for an already fully replayed population only."""
    _need(type(char_start) is int and type(char_end) is int
        and 0 <= char_start < char_end <= view["char_count"], "exact nonempty field coordinate range required")
    text = view["text"][char_start:char_end]
    raw = text.encode("utf-8")
    _need(len(raw) <= bounds["max_selector_bytes"], "bounded exact selected UTF8 bytes required")
    offsets = _byte_positions(view["text"], [char_start, char_end]) if byte_positions is None else byte_positions
    selector = {"schema": SELECTOR_SCHEMA, "view_sha256": view["view_sha256"],
        "source_identity": deepcopy(view["source_identity"]), "row_ordinal": view["source_identity"]["row_ordinal"],
        "coordinate_origin": deepcopy(COORDINATE_ORIGIN), "char_start": char_start, "char_end": char_end,
        "utf8byte_start": offsets[char_start], "utf8byte_end": offsets[char_end], "text": text,
        "text_sha256": hashlib.sha256(raw).hexdigest(), "authority": dict(AUTHORITY)}
    selector["selector_sha256"] = _digest(selector)
    return selector


def _exact_occurrences(view, text, bounds):
    """Internal enumeration for an already fully replayed population only."""
    _need(type(text) is str and bool(text) and len(text.encode("utf-8")) <= bounds["max_selector_bytes"],
        "bounded nonempty exact literal required")
    ranges = _ranges(view["text"], text, bounds["max_occurrences"])
    offsets = _byte_positions(view["text"], [position for pair in ranges for position in pair])
    results = []; retained = 0
    for start, end in ranges:
        selector = _selector(view, start, end, bounds, offsets)
        retained += len(_wire(selector))
        _need(retained <= bounds["max_observation_bytes"], "complete selector byte bound exceeded before retention")
        results.append(selector)
    return results


def exact_parent_text_occurrences(report, selected_rows_report, *, expected_report_sha256, row_ordinal, text, **trusted_inputs):
    """Return all overlapping selectors after FULL independent population replay."""
    validate_parent_text_views(report, selected_rows_report, expected_report_sha256=expected_report_sha256, **trusted_inputs)
    _need(type(row_ordinal) is int, "literal physical row ordinal required")
    _need(type(text) is str and bool(text) and len(text.encode("utf-8")) <= report["limits"]["max_selector_bytes"],
        "bounded nonempty exact literal required")
    matching = [row for row in report["views"] if row["row_ordinal"] == row_ordinal]
    _need(len(matching) == 1, "exact requested physical row missing")
    return [] if matching[0]["text_view"] is None else _exact_occurrences(matching[0]["text_view"], text, report["limits"])


__all__ = ["ParentTextViewsError", "parent_text_views_report_sha256", "prepare_parent_text_views",
    "validate_parent_text_views", "exact_parent_text_occurrences"]
