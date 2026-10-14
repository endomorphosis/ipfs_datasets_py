"""Complete, unselected occurrence inventories in versioned comparison views.

Every physical cache record and independently selected comparison document is
retained. A literal legal-ID association, unique match, expanded visible region
or publisher snapshot never establishes the producer's original source/version.
New view selectors cannot serve as legacy statutory source-binding selectors.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import re

from . import legal_official_source_custody as acquisitions
from . import legal_span_provenance as provenance

SCHEMA = "legal-source-versioned-view-occurrence-inventory/v1"
MAX_DOCUMENTS = 10
MAX_ROWS = 128
MAX_OCCURRENCES = 4096
MAX_TEXT_BYTES = 64 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DOCUMENT_FIELDS = {"descriptor", "raw_bytes", "expected_descriptor_sha256", "expected_raw_sha256",
    "expected_raw_bytes", "view_report", "expected_view_report_sha256"}
AUTHORITY = dict.fromkeys(("publisher_authenticity_verified", "legal_currentness_verified",
    "producer_original_edition_verified", "producer_original_revision_verified",
    "producer_original_occurrence_verified", "source_correspondence_verified",
    "governing_source_binding_verified", "source_occurrence_selected", "source_semantics_verified",
    "context_closure_verified", "legal_review_verified", "global_consistency_verified", "formalized",
    "training_qualified", "Lean_kernel_admission", "legacy_source_binding_compatible",
    "raw_html_coordinate_mapping_verified"), False)


class SourceViewInventoryError(ValueError):
    """Independent complete input pins or a finite view-inventory bound differ."""


def _need(ok, message):
    if not ok:
        raise SourceViewInventoryError(message)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise SourceViewInventoryError("finite UTF8 view inventory JSON required") from error
    _need(len(raw) <= MAX_REPORT_BYTES, "complete view inventory byte bound exceeded; truncation refused")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value, name):
    _need(type(value) is str and _SHA.fullmatch(value), "exact independent " + name + " SHA256 required")


def _document_pins(document_inputs):
    _need(type(document_inputs) is list and len(document_inputs) <= MAX_DOCUMENTS,
          "bounded complete comparison document population required")
    pins, seen, total = [], set(), 0
    for item in document_inputs:
        _need(type(item) is dict and set(item) == _DOCUMENT_FIELDS, "closed versioned document input required")
        descriptor = item["descriptor"]
        for key in ("expected_descriptor_sha256", "expected_raw_sha256", "expected_view_report_sha256"):
            _sha(item[key], key)
        _need(acquisitions.acquisition_descriptor_sha256(descriptor) == item["expected_descriptor_sha256"],
              "independent closed acquisition descriptor pin differs")
        _need(type(item["expected_raw_bytes"]) is int and 0 < item["expected_raw_bytes"] <= acquisitions.MAX_HTML_BYTES,
              "independent bounded raw body size required")
        _need((descriptor["raw_sha256"], descriptor["raw_bytes"]) == (item["expected_raw_sha256"], item["expected_raw_bytes"]),
              "descriptor and independent raw content pins differ")
        _need(item["raw_bytes"] is None or type(item["raw_bytes"]) is bytes, "exact raw bytes or explicit missing body required")
        _need(type(item["view_report"]) is dict and _digest(item["view_report"]) == item["expected_view_report_sha256"],
              "independent FULL view report pin differs")
        _need(item["expected_descriptor_sha256"] not in seen, "duplicate exact acquisition descriptor in complete view population")
        seen.add(item["expected_descriptor_sha256"])
        total += item["expected_raw_bytes"]
        _need(total <= MAX_DOCUMENTS * acquisitions.MAX_HTML_BYTES, "complete comparison raw byte bound exceeded")
        pins.append({"descriptor": deepcopy(descriptor), "expected_descriptor_sha256": item["expected_descriptor_sha256"],
            "expected_raw_sha256": item["expected_raw_sha256"], "expected_raw_bytes": item["expected_raw_bytes"],
            "expected_view_report_sha256": item["expected_view_report_sha256"],
            "raw_body_supplied": item["raw_bytes"] is not None})
    return pins


def view_document_population_sha256(document_inputs):
    """Commit the full closed descriptor population and independently pinned views.

    Each view pin hashes its entire canonical report including its internal seal.
    This helper never substitutes a report's self-seal for external authorization.
    """
    return _digest(_document_pins(document_inputs))


def _view_inputs(item):
    arguments = {key: item[key] for key in ("descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes")}
    # Limits are part of the independently FULL-pinned report. If the view owner
    # records them, replay that exact contract instead of silently using defaults.
    if "limits" in item["view_report"]:
        arguments["limits"] = deepcopy(item["view_report"]["limits"])
    return arguments


def prepare_source_view_inventory(provenance_report, rows, *, provenance_inputs,
        expected_provenance_report_sha256, document_inputs, expected_document_population_sha256,
        max_occurrences=MAX_OCCURRENCES):
    """Regenerate provenance/views and retain every exact overlapping comparison.

    All headers, tables, notes and body regions remain the view owner's declared
    observations. No occurrence is selected, including a single exact match.
    """
    from . import legal_official_document_views as views

    _need(type(rows) is list and 0 < len(rows) <= MAX_ROWS, "bounded complete physical raw row population required")
    _need(type(provenance_inputs) is dict and "expected_report_sha256" not in provenance_inputs,
          "independent complete provenance replay inputs required")
    checked = provenance.validate_span_provenance(provenance_report, rows,
        expected_report_sha256=expected_provenance_report_sha256, **provenance_inputs)
    _sha(expected_document_population_sha256, "complete view document population")
    _need(type(document_inputs) is list and len(document_inputs) <= MAX_DOCUMENTS,
          "bounded complete view document population required")
    # Check the aggregate report population before copying retained nested
    # inputs. Per-document limits alone permit many large reports at once.
    input_bytes = 0
    for item in document_inputs:
        _need(type(item) is dict and set(item) == _DOCUMENT_FIELDS, "closed versioned document input required")
        input_bytes += len(_wire(item["view_report"])) + len(_wire(item["descriptor"])) + 1
        _need(input_bytes <= MAX_REPORT_BYTES, "complete view input byte bound exceeded before snapshot")
    document_inputs = deepcopy(document_inputs)
    document_pins = _document_pins(document_inputs)
    _need(_digest(document_pins) == expected_document_population_sha256,
          "independently pinned complete view document population differs")
    _need(type(max_occurrences) is int and 0 < max_occurrences <= MAX_OCCURRENCES,
          "bounded complete cross-document occurrence limit required")
    record_pins = [r["record_sha256"] for r in checked["rows"]]
    budget_bytes = len(_wire({"document_population": document_pins, "expected_record_sha256s": record_pins}))
    def budget(value):
        _need(value <= MAX_REPORT_BYTES, "complete view inventory byte bound exceeded; truncation refused")
    documents, arguments = [], []
    for item in document_inputs:
        trusted = _view_inputs(item)
        report = views.validate_official_document_view(item["view_report"], item["raw_bytes"],
            expected_report_sha256=item["expected_view_report_sha256"], **trusted)
        budget_bytes += len(_wire(report)) + 1
        budget(budget_bytes)
        documents.append(report); arguments.append(trusted)
    result_rows = []
    for original in checked["rows"]:
        row_budget_start = budget_bytes
        identity = original["source_identity"]
        legal_id, text = identity.get("legal_id"), identity.get("source_text")
        valid_text = type(text) is str and bool(text) and len(text.encode("utf-8")) <= MAX_TEXT_BYTES
        candidates, total = [], 0
        for number, report in enumerate(documents):
            if report["descriptor"]["legal_id"] != legal_id:
                continue
            available = type(report.get("document")) is dict and type(report.get("normalized_view")) is dict
            occurrences = []
            if available and valid_text:
                selectors = views.exact_view_occurrences(report, document_inputs[number]["raw_bytes"],
                    expected_report_sha256=document_inputs[number]["expected_view_report_sha256"],
                    text=text, max_occurrences=max_occurrences, **arguments[number])
                for selector in selectors:
                    occurrence = {"selector": selector,
                        "region_intersections": views.occurrence_region_intersections(report, selector)}
                    budget_bytes += len(_wire(occurrence)) + 1
                    budget(budget_bytes)
                    occurrences.append(occurrence)
            total += len(occurrences)
            _need(total <= max_occurrences, "complete cross-document view occurrence bound exceeded; truncation refused")
            normalized = report.get("normalized_view") or {}
            candidates.append({"document_index": number,
                "descriptor_sha256": document_inputs[number]["expected_descriptor_sha256"],
                "view_report_sha256": document_inputs[number]["expected_view_report_sha256"],
                "document_report_schema": report["schema"], "normalized_view_schema": normalized.get("schema"),
                "document_status": report["status"], "view_available": available,
                "occurrences": occurrences, "occurrence_count": len(occurrences),
                "issues": deepcopy(report["issues"]),
                "association_scope": "literal_legal_id_comparison_only_not_producer_original_source_correspondence"})
        if not valid_text: status = "unsupported_or_missing_exact_source_text"
        elif not candidates: status = "comparison_view_document_missing"
        elif any(c["view_available"] is not True for c in candidates): status = "comparison_view_inventory_incomplete_document_unavailable"
        elif total == 0: status = "zero_exact_comparison_view_occurrences"
        elif total == 1: status = "single_exact_comparison_view_occurrence_unselected"
        else: status = "multiple_exact_comparison_view_occurrences_unselected"
        row = {"row_ordinal": original["row_ordinal"], "raw_row_sha256": original["raw_row_sha256"],
            "record_sha256": original["record_sha256"], "record_id": original["record_id"],
            "source_identity": deepcopy(identity), "provenance_classification": deepcopy(original["classification"]),
            "comparison_documents": candidates, "exact_occurrence_count": total, "status": status,
            "selected_occurrence": None, "governing_source_binding": None, "authority": dict(AUTHORITY)}
        budget_bytes = row_budget_start + len(_wire(row)) + 1
        budget(budget_bytes)
        result_rows.append(row)
    report = {"schema": SCHEMA, "provenance_report_sha256": expected_provenance_report_sha256,
        "document_population_sha256": expected_document_population_sha256, "document_population": document_pins,
        "documents": documents, "row_count": len(result_rows), "rows": result_rows,
        "expected_row_sha256s": [r["raw_row_sha256"] for r in checked["rows"]], "expected_record_sha256s": record_pins,
        "status_counts": dict(Counter(r["status"] for r in result_rows)), "population_complete": True,
        "max_occurrences_per_row_across_all_comparison_documents": max_occurrences,
        "coverage_scope": "complete_supplied_physical_rows_and_independently_selected_versioned_comparison_views_only",
        "legacy_selector_conversion_performed": False, "producer_source_correspondence_inferred": False,
        "authority": dict(AUTHORITY)}
    report["inventory_sha256"] = _digest(report)
    return report


def source_view_inventory_sha256(report):
    """Full canonical inventory digest including its internal inventory seal."""
    return _digest(report)


def validate_source_view_inventory(report, provenance_report, rows, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256, "source view inventory")
    _need(source_view_inventory_sha256(report) == expected_report_sha256,
          "independent FULL source view inventory pin differs")
    expected = prepare_source_view_inventory(provenance_report, rows, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "source view inventory differs from complete independent regeneration")
    return expected


__all__ = ["SourceViewInventoryError", "view_document_population_sha256", "prepare_source_view_inventory",
           "source_view_inventory_sha256", "validate_source_view_inventory"]
