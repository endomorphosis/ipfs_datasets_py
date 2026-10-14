"""Complete source-local cache/parent comparisons, with no selected occurrence.

An exact literal match in a verified parent string is a coordinate candidate.
Even one match, or a locally verified producer declaration chain, does not
attest which original character occurrence produced a diagnostic cache row.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib

from . import legal_producer_lineage as legacy
from . import legal_producer_page_lineage as lineage

SCHEMA = "legal-cache-parent-exact-occurrence-inventory/v1"
LINEAGE_FIELDS = {"expected_provenance_report_sha256s", "expected_record_sha256s", "witness_manifest",
    "expected_witness_manifest_sha256", "parent_page_inputs", "expected_parent_page_inputs_sha256"}
VIEW_FIELDS = {"expected_selected_rows_report_sha256", "parent_descriptor", "expected_parent_descriptor_sha256",
    "preflight_report", "expected_preflight_sha256", "row_ordinals", "expected_row_sha256s"}
DEFAULT_LIMITS = {"max_records": 128, "max_parent_views": 32, "max_source_characters": 65_536,
    "max_total_source_characters": 1024**2, "max_occurrences": 4096, "max_report_bytes": 8 * 1024**2}
AUTHORITY = {**legacy.AUTHORITY, **dict.fromkeys(("producer_original_character_mapping_verified",
    "governing_body_selected", "source_region_roles_verified", "autoformalization_eligible",
    "training_gold_qualified", "accepted_graph_view_enabled"), False)}


class CacheParentOccurrencesError(ValueError):
    """A complete external population/custody pin or finite comparison bound differs."""


def _need(ok, message):
    if not ok: raise CacheParentOccurrencesError(message)


def _wire(value, maximum=DEFAULT_LIMITS["max_report_bytes"]):
    return legacy._wire(value, maximum)


def _digest(value): return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _need(type(value) is str and legacy._SHA.fullmatch(value), "independent lowercase FULL SHA256 required")


def _limits(value):
    _need(value is None or type(value) is dict, "closed lower-only occurrence limits required")
    bounds = dict(DEFAULT_LIMITS)
    for key, limit in (value or {}).items():
        _need(key in bounds and type(limit) is int and 0 < limit <= bounds[key], "unknown or raised occurrence bound")
        bounds[key] = limit
    return bounds


def cache_parent_occurrences_report_sha256(report):
    """FULL canonical digest, including the internal occurrences_sha256 seal."""
    return _digest(report)


def _trusted_parent_views(report, pin, inputs, bounds):
    """Fixed owner replay once for the complete independently pinned population."""
    from . import legal_parent_text_views as views
    _sha(pin)
    _need(type(inputs) is dict and VIEW_FIELDS <= set(inputs)
        and set(inputs) <= VIEW_FIELDS | {"page_limits", "limits"}, "closed complete parent text-view replay inputs required")
    _need(type(report) is dict, "complete parent text-view report required")
    _wire(report, bounds["max_report_bytes"])
    _need(views.parent_text_views_report_sha256(report) == pin, "independent FULL parent text-view report differs")
    snapshot = deepcopy(report)
    views.validate_parent_text_views(snapshot, snapshot["selected_rows_report"], expected_report_sha256=pin, **inputs)
    _need(type(snapshot.get("views")) is list and len(snapshot["views"]) <= bounds["max_parent_views"],
        "complete bounded parent-view population required")
    characters = 0
    for envelope in snapshot["views"]:
        view = envelope["text_view"]
        if view is None: continue
        text = view["text"]
        _need(type(text) is str and len(text) <= bounds["max_source_characters"], "complete source-local text bound exceeded")
        characters += len(text)
        _need(characters <= bounds["max_total_source_characters"], "complete parent-text population character bound exceeded")
    return snapshot


def _intersections(view, selector):
    lo, hi = selector["char_start"], selector["char_end"]
    def overlap(item): return max(lo, item["char_start"]) < min(hi, item["char_end"])
    return {"regions": [deepcopy(region) for region in view["regions"] if overlap(region)],
        "marker_observations": [deepcopy(marker) for marker in view["marker_observations"] if overlap(marker)],
        "source_region_roles_verified": False}


def _literal_parent_legal_id(raw_row):
    title, section = raw_row.get("title_number"), raw_row.get("section_number")
    title_ok = (type(title) is int and title > 0) or (type(title) is str and bool(legacy.re.fullmatch(r"[1-9][0-9]*", title)))
    section_ok = (type(section) is int and section > 0) or (type(section) is str and bool(section.strip()))
    return f"usc:us:{title}:{section}" if title_ok and section_ok else None


def prepare_cache_parent_occurrences(provenance_reports, lineage_report, parent_text_views_report, *,
        expected_provenance_report_sha256s, expected_record_sha256s, expected_lineage_report_sha256,
        lineage_inputs, expected_parent_text_views_report_sha256, parent_text_views_inputs, limits=None):
    """Replay custody and retain all literal overlapping candidates for every row.

    Every valid cache text is compared against every supplied parent view.
    Legal-ID equality is an observation, never a filter or a historical character
    mapping. Local producer chain statuses are retained without reinterpretation.
    """
    from . import legal_parent_text_views as views
    bounds = _limits(limits); _sha(expected_lineage_report_sha256)
    _need(type(lineage_inputs) is dict and set(lineage_inputs) == LINEAGE_FIELDS,
        "closed independently pinned complete v2 lineage replay inputs required")
    _need(type(expected_record_sha256s) is list and 0 < len(expected_record_sha256s) <= bounds["max_records"]
        and type(expected_provenance_report_sha256s) is list
        and lineage_inputs["expected_record_sha256s"] == expected_record_sha256s
        and lineage_inputs["expected_provenance_report_sha256s"] == expected_provenance_report_sha256s,
        "independent original record/provenance populations differ")
    for pin in expected_record_sha256s + expected_provenance_report_sha256s: _sha(pin)
    _wire(lineage_report, bounds["max_report_bytes"])
    _need(lineage.producer_page_lineage_report_sha256(lineage_report) == expected_lineage_report_sha256,
        "independent FULL producer page-lineage report differs")
    checked_lineage = deepcopy(lineage_report)
    lineage.validate_producer_page_lineage(checked_lineage, provenance_reports,
        expected_report_sha256=expected_lineage_report_sha256, **lineage_inputs)
    _need([row["record_sha256"] for row in checked_lineage["rows"]] == expected_record_sha256s,
        "complete physical cache-row order differs")
    parent_views = _trusted_parent_views(parent_text_views_report, expected_parent_text_views_report_sha256,
        parent_text_views_inputs, bounds)
    parent_rows = parent_views["selected_rows_report"]["rows"]
    _need([row["row_ordinal"] for row in parent_rows] == [view["row_ordinal"] for view in parent_views["views"]],
        "complete physical parent/view order differs")
    comparisons = []
    for number, (envelope, raw_row) in enumerate(zip(parent_views["views"], parent_rows, strict=True)):
        comparisons.append({"view_index": number, "row_ordinal": envelope["row_ordinal"],
            "raw_row_sha256": envelope["raw_row_sha256"],
            "literal_legal_id": _literal_parent_legal_id(raw_row["raw_row"]),
            "text_view": deepcopy(envelope["text_view"]), "issues": deepcopy(envelope["issues"]),
            "association_scope": "literal_parent_title_section_fields_only_no_alias_or_revision_equivalence",
            "authority": dict(AUTHORITY)})
    retained_bytes = len(_wire(comparisons)); count = 0; rows = []
    for original in checked_lineage["rows"]:
        raw = original["raw_row"]; identity = original["source_identity"]
        text = identity.get("source_text"); declared_sha = identity.get("source_sha256_observation")
        valid_text = type(text) is str and bool(text) and len(text) <= bounds["max_source_characters"]
        actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest() if valid_text else None
        source_hash_matches = valid_text and type(declared_sha) is str and declared_sha == actual_sha
        candidate_views = []; reference_views = []; total = 0; issues = []
        reference = original["parent_row_witness"]
        for comparison in comparisons:
            view = comparison["text_view"]
            if view is not None and reference is not None:
                source = view["source_identity"]
                if (source["file_sha256"] == reference["parent_sha256"]
                    and source["revision"] == reference["parent_revision"]
                    and source["row_ordinal"] == reference["row_ordinal"]
                    and source["raw_row_sha256"] == reference["complete_row_sha256"]):
                    reference_views.append(comparison["view_index"])
            occurrences = []
            # Complete physical raw-row pins authenticate the observed string.
            # A wrong legacy text-hash declaration blocks admission, not the
            # retention of source-local literal comparison observations.
            if view is not None and valid_text:
                ranges = views._ranges(view["text"], text, bounds["max_occurrences"] - count)
                coordinates = views._byte_positions(view["text"], [n for pair in ranges for n in pair])
                for lo, hi in ranges:
                    selector = views._selector(view, lo, hi, parent_views["limits"], coordinates)
                    candidate = {"selector": selector, "region_intersections": _intersections(view, selector),
                        "selected": False, "historical_original_mapping_verified": False}
                    retained_bytes += len(_wire(candidate)) + 1
                    _need(retained_bytes <= bounds["max_report_bytes"], "complete occurrence report byte bound exceeded; no truncation")
                    occurrences.append(candidate); count += 1; total += 1
            candidate_views.append({"view_index": comparison["view_index"], "view_available": view is not None,
                "literal_parent_legal_id": comparison["literal_legal_id"],
                "literal_cache_legal_id": identity.get("legal_id"),
                "literal_legal_id_matches": comparison["literal_legal_id"] is not None
                    and comparison["literal_legal_id"] == identity.get("legal_id"),
                "occurrences": occurrences, "occurrence_count": len(occurrences),
                "association_scope": "all_supplied_parent_literal_fields_compared_no_legal_id_filter_or_historical_span_mapping"})
        if not valid_text:
            status = "unsupported_or_missing_source_text"; issues.append({"code": "source_text_missing_empty_or_over_bound"})
        elif not source_hash_matches:
            status = "source_text_hash_mismatch"; issues.append({"code": "raw_cache_source_text_sha256_mismatch"})
        elif not candidate_views: status = "comparison_parent_view_not_supplied"
        elif any(not c["view_available"] for c in candidate_views): status = "comparison_parent_view_unavailable"
        elif total == 0: status = "zero_exact_parent_occurrences"
        elif total == 1: status = "single_exact_parent_occurrence_unselected"
        else: status = "multiple_exact_parent_occurrences_unselected"
        if original["status"] == "verified_local_report_parent_declarations_only" and len(reference_views) != 1:
            issues.append({"code": "verified_local_parent_reference_comparison_view_missing_or_multiple"})
        row = {"row_ordinal": original["row_ordinal"], "cache_identity": deepcopy(original["cache_identity"]),
            "raw_row": deepcopy(raw), "raw_row_sha256": original["raw_row_sha256"], "record_sha256": original["record_sha256"],
            "source_identity": deepcopy(identity), "prior_provenance_classification": original["prior_provenance_classification"],
            "prior_lineage_status": original["status"], "prior_lineage_issues": deepcopy(original["issues"]),
            "producer_row_witness": deepcopy(original["producer_row_witness"]), "parent_row_witness": deepcopy(reference),
            "local_parent_reference_view_indices": reference_views,
            "source_text_sha256_matches_raw_declaration": bool(source_hash_matches),
            "comparison_views": candidate_views, "exact_occurrence_count": total, "status": status, "issues": issues,
            "selected_occurrence": None, "governing_source_binding": None,
            "legacy_mock_and_target_conditioning_preserved_as_raw_observations": True, "authority": dict(AUTHORITY)}
        retained_bytes += len(_wire({k: v for k, v in row.items() if k != "comparison_views"})) + 1
        _need(retained_bytes <= bounds["max_report_bytes"], "complete physical-row report byte bound exceeded; no truncation")
        rows.append(row)
    report = {"schema": SCHEMA, "limits": bounds,
        "provenance_report_sha256s": deepcopy(expected_provenance_report_sha256s),
        "expected_record_sha256s": deepcopy(expected_record_sha256s), "lineage_report_sha256": expected_lineage_report_sha256,
        "parent_text_views_report_sha256": expected_parent_text_views_report_sha256,
        "parent_views": comparisons, "rows": rows, "row_count": len(rows), "exact_occurrence_count": count,
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "prior_lineage_status_counts": dict(Counter(row["prior_lineage_status"] for row in rows)),
        "population_complete": True, "all_occurrences_unselected": True,
        "coverage_scope": "all_independently_pinned_supplied_cache_rows_bounded_observed_raw_text_against_all_supplied_parent_literal_fields_no_legal_id_or_legacy_hash_filter",
        "original_source_character_mapping_attested": False, "whole_cache_coverage_verified": False,
        "authority": dict(AUTHORITY)}
    report["occurrences_sha256"] = _digest(report); _wire(report, bounds["max_report_bytes"])
    return report


def validate_cache_parent_occurrences(report, provenance_reports, lineage_report, parent_text_views_report, *,
        expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(cache_parent_occurrences_report_sha256(report) == expected_report_sha256, "independent FULL cache occurrence report differs")
    expected = prepare_cache_parent_occurrences(provenance_reports, lineage_report, parent_text_views_report, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "cache occurrence report differs from fixed complete regeneration")
    return {"valid": True, "row_count": report["row_count"], "all_occurrences_unselected": True, "all_authority_false": True}


__all__ = ["CacheParentOccurrencesError", "prepare_cache_parent_occurrences",
    "validate_cache_parent_occurrences", "cache_parent_occurrences_report_sha256"]
