"""Lossless literal-block alignment observations in two distinct source views.

Every supplied parent and official comparison document remains in the population.
Exact substrings connect coordinates only in the current literal Parquet field
and normalized markup view; they never authenticate a historical HTML occurrence,
governing edition, legal region, review, training input or Lean statement.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from html.parser import HTMLParser

from . import legal_cache_parent_occurrences as parent_custody
from . import legal_parent_text_views as parents
from . import legal_official_document_views as official
from . import legal_source_view_inventory as documents

SCHEMA = "legal-parent-official-source-alignment/v1"
PROFILE = "exact_literal_block_two_sided_observations/v1"
RENDER_PROFILE = "all_data_events_strip_each_join_ascii_space/v1"
DEFAULT_LIMITS = {"max_parent_views": 32, "max_documents": 10,
    "max_parent_characters": 65536, "max_total_parent_characters": 1024**2,
    "max_official_characters": 256 * 1024, "max_total_official_characters": 1024**2,
    "max_total_raw_HTML_bytes": 8 * 1024**2, "max_total_input_report_bytes": 12 * 1024**2,
    "max_blocks": 4096, "max_block_bytes": 64 * 1024, "max_alignments": 8192,
    "max_partition_pieces": 8192, "max_observation_bytes": 8 * 1024**2,
    "max_report_bytes": 16 * 1024**2, "max_render_events": 16384,
    "max_render_event_bytes": 64 * 1024, "max_rendered_field_bytes": 256 * 1024,
    "max_total_rendered_field_bytes": 1024**2}
DOCUMENT_FIELDS = {"descriptor", "raw_bytes", "expected_descriptor_sha256", "expected_raw_sha256",
    "expected_raw_bytes", "view_report", "expected_view_report_sha256"}
AUTHORITY = {**documents.AUTHORITY, **dict.fromkeys(("original_parent_HTML_correspondence_verified",
    "governing_body_selected", "markup_region_legal_role_verified", "context_packet_admitted",
    "autoformalization_eligible", "training_gold_qualified"), False)}


class ParentSourceAlignmentError(ValueError):
    """A complete independent source pin, exact population or bound differs."""


def _need(ok, message):
    if not ok:
        raise ParentSourceAlignmentError(message)


def _wire(value, maximum=DEFAULT_LIMITS["max_report_bytes"]):
    return parent_custody._wire(value, maximum)


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def parent_source_alignment_report_sha256(report):
    """FULL canonical report digest, including source_alignment_sha256."""
    return _digest(report)


def _limits(value):
    _need(value is None or type(value) is dict, "closed lower-only alignment limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key], "unknown or raised alignment bound")
        result[key] = bound
    return result


def _parent_snapshot(report, pin, inputs, bounds):
    return parent_custody._trusted_parent_views(report, pin, inputs, {
        "max_parent_views": bounds["max_parent_views"], "max_source_characters": bounds["max_parent_characters"],
        "max_total_source_characters": bounds["max_total_parent_characters"], "max_report_bytes": bounds["max_report_bytes"]})


class _RenderedField(HTMLParser):
    """A declared text transformation, never a browser or historical producer."""
    def __init__(self, bounds, budget):
        super().__init__(convert_charrefs=True)
        self.bounds = bounds; self.budget = budget; self.events = []; self.fragments = []; self.parts = []
        self.characters = 0; self.bytes = 0

    def handle_data(self, data):
        _need(self.budget["events"] < self.bounds["max_render_events"], "complete render data-event count bound exceeded before retention")
        raw = data.encode("utf-8")
        _need(len(raw) <= self.bounds["max_render_event_bytes"], "individual render data-event byte bound exceeded")
        text = data.strip(); fragment = None
        if text:
            rendered = text.encode("utf-8"); separator = 1 if self.parts else 0
            total = self.bytes + separator + len(rendered)
            _need(total <= self.bounds["max_rendered_field_bytes"]
                and self.characters + separator + len(text) <= self.bounds["max_official_characters"]
                and self.budget["rendered_bytes"] + separator + len(rendered) <= self.bounds["max_total_rendered_field_bytes"],
                "complete render field byte/character bound exceeded before retention")
            fragment = {"event_index": len(self.events), "char_start": self.characters + separator,
                "char_end": self.characters + separator + len(text), "utf8_byte_start": self.bytes + separator,
                "utf8_byte_end": total, "text_sha256": hashlib.sha256(rendered).hexdigest()}
            _charge(fragment, self.budget, self.bounds)
            self.fragments.append(fragment); self.parts.append(text)
            self.budget["rendered_bytes"] += separator + len(rendered)
            self.bytes = total; self.characters += separator + len(text)
        observation = {"event_index": len(self.events), "data_characters": len(data), "data_utf8_bytes": len(raw),
            "data_sha256": hashlib.sha256(raw).hexdigest(), "strip_prefix_characters": len(data) - len(data.lstrip()),
            "strip_suffix_characters": len(data) - len(data.rstrip()), "fragment_index": len(self.fragments) - 1 if fragment else None}
        _charge(observation, self.budget, self.bounds)
        self.events.append(observation); self.budget["events"] += 1


def _rendered_field(raw, report, pin, bounds, budget):
    if raw is None or report["document"] is None:
        return None
    parser = _RenderedField(bounds, budget)
    parser.feed(official.contexts._decode_source_html(raw)); parser.close()
    text = " ".join(parser.parts)
    _need(len(text) == parser.characters and len(text.encode()) == parser.bytes, "complete rendered field accounting differs")
    result = {"schema": "legal-official-data-event-rendered-field/v1", "profile": RENDER_PROFILE,
        "raw_sha256": report["raw_sha256"], "raw_bytes": report["raw_bytes"], "full_official_view_report_sha256": pin,
        "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "char_count": len(text), "utf8_bytes": parser.bytes,
        "events": parser.events, "fragments": parser.fragments,
        "coordinate_origin": {"characters": "Unicode code points in declared complete data-event rendered field; half-open",
            "bytes": "UTF8 bytes of declared complete data-event rendered field; half-open",
            "normalization": "strip_each_data_event_then_join_nonempty_fragments_with_one_ASCII_space_preserve_internal_whitespace",
            "raw_HTML_coordinate_mapping_verified": False, "official_normalized_view_coordinate_equivalence_verified": False},
        "historical_producer_operation_verified": False, "CSS_rendering_verified": False, "authority": dict(AUTHORITY)}
    result["rendered_field_sha256"] = _digest(result)
    return result


def _input_bounds(parent_report, parent_inputs, items, bounds):
    input_bytes = len(_wire(parent_report, bounds["max_total_input_report_bytes"]))
    input_bytes += len(_wire(parent_inputs, bounds["max_total_input_report_bytes"]))
    _need(input_bytes <= bounds["max_total_input_report_bytes"], "complete parent replay bundle byte bound exceeded before snapshot")
    _need(type(items) is list and len(items) <= bounds["max_documents"], "complete bounded official document population required")
    total_raw = 0
    for item in items:
        _need(type(item) is dict and set(item) == DOCUMENT_FIELDS, "closed complete official document replay input required")
        _need(type(item["expected_raw_bytes"]) is int and item["expected_raw_bytes"] > 0, "independent raw HTML byte count required")
        total_raw += item["expected_raw_bytes"]
        _need(total_raw <= bounds["max_total_raw_HTML_bytes"], "aggregate raw HTML population bound exceeded before retention")
        input_bytes += len(_wire(item["view_report"], bounds["max_total_input_report_bytes"]))
        input_bytes += len(_wire({key: value for key, value in item.items() if key not in ("view_report", "raw_bytes")},
            bounds["max_total_input_report_bytes"]))
        _need(input_bytes <= bounds["max_total_input_report_bytes"], "complete input report byte bound exceeded before snapshot")


def _document_snapshot(items, expected_population, bounds, budget):
    _need(documents.view_document_population_sha256(items) == expected_population,
        "independent complete official document population pin differs")
    result = []; characters = 0; blocks = 0
    for index, item in enumerate(items):
        trusted = {key: item[key] for key in ("descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes")}
        if "limits" in item["view_report"]:
            trusted["limits"] = item["view_report"]["limits"]
        checked = official.validate_official_document_view(item["view_report"], item["raw_bytes"],
            expected_report_sha256=item["expected_view_report_sha256"], **trusted)
        document = checked["document"]
        if document is not None:
            text = document["document_text"]; characters += len(text); blocks += len(document["blocks"])
            _need(len(text) <= bounds["max_official_characters"] and characters <= bounds["max_total_official_characters"],
                "complete official normalized text population bound exceeded")
            _need(blocks <= bounds["max_blocks"] and all(len(block["text"].encode()) <= bounds["max_block_bytes"] for block in document["blocks"]),
                "complete official block population/byte bound exceeded; no easier block selection")
        identity = {key: deepcopy(item[key]) for key in ("descriptor", "expected_descriptor_sha256", "expected_raw_sha256",
            "expected_raw_bytes", "expected_view_report_sha256")}
        identity["raw_body_supplied"] = item["raw_bytes"] is not None
        result.append({"document_index": index, "input_identity": identity, "view_report": checked,
            "rendered_field_view": _rendered_field(item["raw_bytes"], checked, item["expected_view_report_sha256"], bounds, budget)})
    return result


def _charge(value, budget, bounds):
    budget["bytes"] += len(_wire(value))
    _need(budget["bytes"] <= bounds["max_observation_bytes"], "complete alignment observation byte bound exceeded before retention")


def _partition(text, identity, intervals, dimension, budget, bounds):
    if text is None:
        return []
    starts = {}; ends = {}; positions = {0, len(text)}
    for alignment_id, lo, hi in intervals:
        _need(0 <= lo < hi <= len(text), "exact alignment coordinate range differs")
        starts.setdefault(lo, []).append(alignment_id); ends.setdefault(hi, []).append(alignment_id)
        positions.update((lo, hi))
    positions = sorted(positions); offsets = parents._byte_positions(text, positions)
    active = set(); result = []
    for lo, hi in zip(positions, positions[1:]):
        active.difference_update(ends.get(lo, ())); active.update(starts.get(lo, ()))
        _need(budget["pieces"] < bounds["max_partition_pieces"], "complete atomic partition population bound exceeded before retention")
        piece = {"coordinate_space": dimension, "char_start": lo, "char_end": hi,
            "utf8_byte_start": offsets[lo], "utf8_byte_end": offsets[hi],
            "text_sha256": hashlib.sha256(text[lo:hi].encode()).hexdigest(), "alignment_ids": sorted(active),
            "coverage_kind": "exact_literal_block_candidate_overlap" if active else "uncovered", "legal_role_verified": False}
        piece["partition_piece_id"] = _digest({"view_identity": identity, "piece": piece})
        _charge(piece, budget, bounds); budget["pieces"] += 1; result.append(piece)
    _need(not text or result and result[0]["char_start"] == 0 and result[-1]["char_end"] == len(text)
        and all(a["char_end"] == b["char_start"] for a, b in zip(result, result[1:])), "complete two-sided coordinate partition differs")
    return result


def _association(body, descriptor):
    checksum = body.get("source_checksum"); edition = body.get("edition")
    checksum_available = type(checksum) is str and bool(checksum)
    return {"parent_source_url_observation": deepcopy(body.get("source_url")), "official_source_url": descriptor["url"],
        "source_url_exact_match": type(body.get("source_url")) is str and body["source_url"] == descriptor["url"],
        "parent_literal_legal_id": parent_custody._literal_parent_legal_id(body), "official_literal_legal_id": descriptor["legal_id"],
        "literal_legal_id_exact_match": parent_custody._literal_parent_legal_id(body) == descriptor["legal_id"],
        "parent_edition_observation": {"field": "edition", "present": "edition" in body, "value": deepcopy(edition)},
        "official_selected_edition": descriptor["edition"],
        "explicit_edition_exact_match": type(edition) is type(descriptor["edition"]) and edition == descriptor["edition"],
        "parent_source_checksum_observation": {"field": "source_checksum", "present": "source_checksum" in body, "value": deepcopy(checksum)},
        "declared_checksum_matches_raw_HTML": checksum == descriptor["raw_sha256"] if checksum_available else None,
        "source_correspondence_verified": False, "historical_original_occurrence_verified": False,
        "association_scope": "literal_declarations_only_no_filter_alias_normalization_or_source_admission"}


def prepare_parent_source_alignment(parent_text_views_report, *, expected_parent_text_views_report_sha256,
        parent_text_views_inputs, document_inputs, expected_document_population_sha256, limits=None):
    """Replay both complete input populations and preserve every exact block match."""
    bounds = _limits(limits)
    _input_bounds(parent_text_views_report, parent_text_views_inputs, document_inputs, bounds)
    parent_report = _parent_snapshot(parent_text_views_report, expected_parent_text_views_report_sha256, parent_text_views_inputs, bounds)
    budget = {"bytes": 0, "pieces": 0, "alignments": 0, "events": 0, "rendered_bytes": 0}
    official_reports = _document_snapshot(document_inputs, expected_document_population_sha256, bounds, budget)
    rows = []; comparisons = 0
    raw_rows = parent_report["selected_rows_report"]["rows"]
    for envelope, raw in zip(parent_report["views"], raw_rows, strict=True):
        view = envelope["text_view"]
        row = {key: deepcopy(envelope[key]) for key in ("row_ordinal", "row_group", "row_group_ordinal", "raw_row_sha256")}
        row.update(view_sha256=None if view is None else view["view_sha256"], parent_view_disposition=envelope["disposition"],
            parent_view_issues=deepcopy(envelope["issues"]), comparisons=[], authority=dict(AUTHORITY))
        for item in official_reports:
            comparisons += 1; report = item["view_report"]; document = report["document"]
            anchors = []; parent_intervals = []; official_intervals = []; pending = []
            if view is not None and document is not None:
                for block in document["blocks"]:
                    found = parents._ranges(view["text"], block["text"], bounds["max_alignments"] - budget["alignments"])
                    _need(budget["alignments"] + len(found) <= bounds["max_alignments"], "complete literal alignment population bound exceeded")
                    budget["alignments"] += len(found)
                    for lo, hi in found:
                        pending.append((block, lo, hi))
                coordinates = parents._byte_positions(view["text"], [n for _, lo, hi in pending for n in (lo, hi)])
                for block, lo, hi in pending:
                    anchor = {"official_block_ref": {"document_index": item["document_index"],
                        "block_index": block["block_index"], "block_id": block["block_id"]},
                        "parent_selector": parents._selector(view, lo, hi, parent_report["limits"], coordinates),
                        "official_selector": official._selector(report, block["char_start"], block["char_end"]),
                        "markup_region_legal_role_verified": False, "authority": dict(AUTHORITY)}
                    anchor["alignment_id"] = _digest({"profile": PROFILE, "anchor": anchor})
                    _charge(anchor, budget, bounds); anchors.append(anchor)
                    parent_intervals.append((anchor["alignment_id"], lo, hi))
                    official_intervals.append((anchor["alignment_id"], block["char_start"], block["char_end"]))
            parent_parts = _partition(None if view is None else view["text"], None if view is None else view["view_sha256"],
                parent_intervals, "parent_literal_field", budget, bounds)
            official_parts = _partition(None if document is None else document["document_text"],
                None if document is None else report["normalized_view"]["view_id"], official_intervals,
                "official_normalized_view", budget, bounds)
            issues = [{"code": "literal_alignment_does_not_authenticate_original_source_or_legal_region"}]
            if view is None: issues.append({"code": "parent_text_view_unavailable"})
            if document is None: issues.append({"code": "official_comparison_view_unavailable", "status": report["status"]})
            rendered = item["rendered_field_view"]
            rendered_equal = None if view is None or rendered is None else view["text"] == rendered["text"]
            comparison = {"document_index": item["document_index"], "association_observations": _association(raw["raw_row"], item["input_identity"]["descriptor"]),
                "exact_block_alignments": anchors, "parent_partition": parent_parts, "official_partition": official_parts,
                "exact_rendered_field_equal": rendered_equal,
                "rendered_field_comparison": {"rendered_field_sha256": None if rendered is None else rendered["rendered_field_sha256"],
                    "parent_view_sha256": None if view is None else view["view_sha256"],
                    "parent_text_sha256": None if view is None else view["text_sha256"],
                    "rendered_text_sha256": None if rendered is None else rendered["text_sha256"],
                    "coordinate_origin": None if rendered is None else deepcopy(rendered["coordinate_origin"]),
                    "current_field_character_equality_observed": rendered_equal,
                    "original_source_correspondence_verified": False, "raw_HTML_coordinate_mapping_verified": False,
                    "historical_producer_operation_verified": False},
                "issues": issues, "authority": dict(AUTHORITY)}
            _charge({key: value for key, value in comparison.items() if key not in ("exact_block_alignments", "parent_partition", "official_partition")}, budget, bounds)
            row["comparisons"].append(comparison)
        rows.append(row)
    result = {"schema": SCHEMA, "profile": PROFILE, "limits": bounds,
        "parent_text_views_report_sha256": expected_parent_text_views_report_sha256,
        "document_population_sha256": expected_document_population_sha256,
        "parent_text_views_report": parent_report, "official_documents": official_reports, "rows": rows,
        "row_count": len(rows), "document_count": len(official_reports), "comparison_count": comparisons,
        "alignment_count": budget["alignments"], "partition_piece_count": budget["pieces"],
        "render_data_event_count": budget["events"], "total_rendered_field_utf8_bytes": budget["rendered_bytes"],
        "population_complete": True, "all_supplied_parent_document_pairs_compared": True,
        "both_coordinate_spaces_preserved": True, "raw_HTML_coordinate_mapping_verified": False,
        "all_source_correspondence_unverified": True, "coverage_scope": "all_independently_pinned_supplied_parent_fields_and_official_normalized_comparison_views_only",
        "authority": dict(AUTHORITY)}
    result["source_alignment_sha256"] = _digest(result)
    _wire(result, bounds["max_report_bytes"])
    return result


def validate_parent_source_alignment(report, parent_text_views_report, *, expected_report_sha256, **trusted_inputs):
    parent_custody._sha(expected_report_sha256)
    _need(parent_source_alignment_report_sha256(report) == expected_report_sha256, "independent FULL source alignment report pin differs")
    expected = prepare_parent_source_alignment(parent_text_views_report, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "source alignment differs from complete fixed-owner independent regeneration")
    return {"valid": True, "row_count": expected["row_count"], "comparison_count": expected["comparison_count"],
        "alignment_count": expected["alignment_count"], "all_source_correspondence_unverified": True, "legal_semantic_acceptance": False}


__all__ = ["ParentSourceAlignmentError", "prepare_parent_source_alignment",
    "parent_source_alignment_report_sha256", "validate_parent_source_alignment"]
