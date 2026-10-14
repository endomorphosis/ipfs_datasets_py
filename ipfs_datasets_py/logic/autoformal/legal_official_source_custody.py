"""Independent GovInfo byte custody and unselected exact occurrence inventories.

An independently selected comparison edition never establishes the edition or
revision of a cached span. HTTP observations are retained acquisition metadata,
separate from verified content bytes. Existing statutory extraction/view owners
define all text coordinates; no HTML offset mapping or legal truth is inferred.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from urllib.parse import urlsplit

from . import legal_statutory_context as contexts

DESCRIPTOR_SCHEMA = "legal-official-source-acquisition/v1"
DOCUMENT_SCHEMA = "legal-official-source-custody-document/v1"
INVENTORY_SCHEMA = "legal-official-source-occurrence-inventory/v1"
MAX_HTML_BYTES = 8_000_000
MAX_DOCUMENTS = 10
MAX_ROWS = 128
MAX_REPORT_BYTES = 64 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LEGAL = re.compile(r"usc:us:([1-9][0-9]*):([0-9]+[A-Za-z0-9-]*)\Z")
_SUPPORTED_LEGAL = re.compile(r"usc:us:([0-9]+):([0-9]+[A-Za-z]*)\Z")
_DESCRIPTOR_FIELDS = {"schema", "legal_id", "url", "edition", "package_id", "granule_id",
    "retrieved_at", "raw_sha256", "raw_bytes", "http_provenance"}
_HTTP_FIELDS = {"requested_url", "final_url", "status_code", "content_type", "etag", "last_modified"}
_DOCUMENT_FIELDS = {"descriptor", "raw_bytes", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes"}
AUTHORITY = dict.fromkeys(("publisher_authenticity_verified", "legal_currentness_verified",
    "producer_edition_correspondence_verified", "producer_revision_correspondence_verified",
    "governing_source_binding_verified", "source_occurrence_selected", "source_semantics_verified",
    "context_closure_verified", "formalized", "legal_review_verified", "global_consistency_verified",
    "training_qualified", "Lean_kernel_admission", "raw_html_coordinate_mapping_verified"), False)


class OfficialSourceCustodyError(ValueError):
    """Independent custody, complete population or finite bounds disagree."""


def _need(ok, message):
    if not ok:
        raise OfficialSourceCustodyError(message)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise OfficialSourceCustodyError("finite UTF8 custody JSON required") from error
    _need(len(raw) <= MAX_REPORT_BYTES, "complete custody report byte bound exceeded; truncation refused")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value, name):
    _need(type(value) is str and _SHA.fullmatch(value), "exact independent " + name + " SHA256 required")


def _text(value, name, maximum=4096):
    _need(type(value) is str and value and len(value.encode("utf-8")) <= maximum and "\x00" not in value,
          "bounded " + name + " required")


def _descriptor(value):
    _need(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS, "closed acquisition descriptor required")
    _need(value["schema"] == DESCRIPTOR_SCHEMA, "supported acquisition descriptor required")
    _text(value["legal_id"], "literal legal identity", 256)
    identity = _LEGAL.fullmatch(value["legal_id"])
    _need(identity is not None, "literal section identity required; no citation normalization")
    title, section = identity.groups()
    edition = value["edition"]
    _need(type(edition) is int and 1800 <= edition <= 9999, "explicit bounded historical edition required")
    package = f"USCODE-{edition}-title{title}"
    _need(value["package_id"] == package, "package/edition/title identity differs")
    granule = value["granule_id"]
    _text(granule, "granule", 1024)
    _need(re.fullmatch(re.escape(package) + r"(?:-[A-Za-z0-9]+)*-sec" + re.escape(section) + r"(?:-[0-9]+)?", granule),
          "literal granule/section identity differs")
    expected_url = f"https://www.govinfo.gov/content/pkg/{package}/html/{granule}.htm"
    _need(value["url"] == expected_url, "exact clean official GovInfo HTML URL required")
    _text(value["retrieved_at"], "retrieved timestamp", 128)
    try:
        timestamp = datetime.fromisoformat(value["retrieved_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise OfficialSourceCustodyError("explicit timezone-aware acquisition timestamp required") from error
    _need(timestamp.utcoffset() is not None, "explicit timezone-aware acquisition timestamp required")
    _sha(value["raw_sha256"], "declared raw body")
    _need(type(value["raw_bytes"]) is int and 0 < value["raw_bytes"] <= MAX_HTML_BYTES, "bounded raw body size required")
    http = value["http_provenance"]
    _need(type(http) is dict and set(http) == _HTTP_FIELDS, "closed HTTP acquisition observation required")
    _need(type(http["status_code"]) is int and http["status_code"] == 200, "successful HTTP acquisition observation required")
    _need(http["final_url"] == expected_url, "HTTP final URL differs from exact content URL")
    request = http["requested_url"]
    _text(request, "requested official URL")
    parsed = urlsplit(request)
    direct = request == expected_url
    link = (parsed.scheme == "https" and parsed.netloc == "www.govinfo.gov"
            and parsed.path == f"/link/uscode/{title}/{section}" and parsed.query == "year=" + str(edition)
            and not parsed.fragment)
    _need(direct or link, "unsupported official request URL or edition identity")
    _text(http["content_type"], "HTTP content type", 1024)
    _need(http["content_type"].split(";", 1)[0].strip().lower() == "text/html", "HTML content-type observation required")
    for field in ("etag", "last_modified"):
        if http[field] is not None:
            _text(http[field], "HTTP " + field)
    return deepcopy(value)


def acquisition_descriptor_sha256(descriptor):
    """Canonical descriptor digest; authority requires a separately retained pin."""
    return _digest(_descriptor(descriptor))


def prepare_official_document(raw, *, descriptor, expected_descriptor_sha256,
                              expected_raw_sha256, expected_raw_bytes):
    """Verify exact externally pinned bytes and replay existing extraction/view.

    A missing body or unsupported v1 section grammar is an explicit observation.
    Corrupt, oversized or incorrectly pinned supplied bytes raise without partial
    success. The caller retains immutable raw bytes separately from this report.
    """
    descriptor = _descriptor(descriptor)
    _sha(expected_descriptor_sha256, "descriptor"); _sha(expected_raw_sha256, "raw body")
    _need(acquisition_descriptor_sha256(descriptor) == expected_descriptor_sha256, "independent acquisition descriptor pin differs")
    _need(type(expected_raw_bytes) is int and 0 < expected_raw_bytes <= MAX_HTML_BYTES,
          "independent bounded expected raw byte count required")
    _need((descriptor["raw_sha256"], descriptor["raw_bytes"]) == (expected_raw_sha256, expected_raw_bytes),
          "descriptor and independently retained content pins differ")
    _need(raw is None or type(raw) is bytes, "exact raw bytes or explicit missing body required")
    if raw is not None:
        _need(len(raw) == expected_raw_bytes and hashlib.sha256(raw).hexdigest() == expected_raw_sha256,
              "complete independent raw body SHA256/bytes differ")
    document = view = None
    issues = []
    if raw is None:
        status = "raw_comparison_document_missing"
        issues.append({"code": "independently_pinned_raw_body_not_supplied"})
    elif _SUPPORTED_LEGAL.fullmatch(descriptor["legal_id"]) is None:
        status = "unsupported_section_identity_profile"
        issues.append({"code": "current_GovInfo_extractor_section_identity_grammar_unsupported",
                       "legal_id": descriptor["legal_id"]})
    else:
        try:
            document = contexts.extract_document(raw, url=descriptor["url"], edition=descriptor["edition"],
                                                 legal_id=descriptor["legal_id"])
            view = contexts.normalized_document_view(document, raw)
            status = "comparison_document_extracted"
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            document = view = None
            status = "comparison_extraction_rejected"
            issues.append({"code": "existing_GovInfo_extraction_contract_rejected", "message": str(error)[:512]})
    report = {"schema": DOCUMENT_SCHEMA, "descriptor": descriptor,
        "descriptor_sha256": expected_descriptor_sha256, "raw_sha256": expected_raw_sha256,
        "raw_bytes": expected_raw_bytes, "raw_body_verified": raw is not None,
        "raw_payload_location": "independently_pinned_caller_retained_raw_bytes",
        "document": document, "normalized_view": view, "status": status, "issues": issues,
        "acquisition_provenance_scope": "recorded_HTTP_and_retrieval_observations_separate_from_content_hash",
        "edition_scope": "independently_selected_comparison_only_not_producer_edition_correspondence",
        "authority": dict(AUTHORITY)}
    report["document_report_sha256"] = _digest(report)
    return report


def document_report_sha256(report):
    """Full canonical report digest including its internal document seal."""
    return _digest(report)


def validate_official_document(report, raw, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256, "document report")
    _need(document_report_sha256(report) == expected_report_sha256, "independent document report pin differs")
    expected = prepare_official_document(raw, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "document custody differs from complete independent extraction replay")
    return expected


def _documents(value):
    _need(type(value) is list and len(value) <= MAX_DOCUMENTS, "bounded complete document input population required")
    pins, seen, total = [], set(), 0
    for item in value:
        _need(type(item) is dict and set(item) == _DOCUMENT_FIELDS, "closed document input required")
        descriptor = _descriptor(item["descriptor"])
        expected_descriptor = item["expected_descriptor_sha256"]
        _sha(expected_descriptor, "document population descriptor"); _sha(item["expected_raw_sha256"], "document population raw body")
        _need(expected_descriptor == acquisition_descriptor_sha256(descriptor), "document population descriptor pin differs")
        _need(expected_descriptor not in seen, "duplicate exact acquisition descriptor in complete population")
        seen.add(expected_descriptor)
        _need(type(item["expected_raw_bytes"]) is int and 0 < item["expected_raw_bytes"] <= MAX_HTML_BYTES,
              "bounded independent document population byte pin required")
        _need((descriptor["raw_sha256"], descriptor["raw_bytes"]) == (item["expected_raw_sha256"], item["expected_raw_bytes"]),
              "document population independent content pins differ")
        _need(item["raw_bytes"] is None or type(item["raw_bytes"]) is bytes, "exact body or explicit missing input required")
        total += item["expected_raw_bytes"]
        _need(total <= MAX_DOCUMENTS * MAX_HTML_BYTES, "complete document population byte bound exceeded")
        pins.append({"descriptor": descriptor, "expected_descriptor_sha256": expected_descriptor,
            "expected_raw_sha256": item["expected_raw_sha256"], "expected_raw_bytes": item["expected_raw_bytes"],
            "raw_body_supplied": item["raw_bytes"] is not None})
    return pins


def document_population_sha256(document_inputs):
    """Commit every independently supplied descriptor/pin and missing-body state."""
    return _digest(_documents(document_inputs))


def _coverage(document, selector):
    left, right = selector["char_start"], selector["char_end"]
    paragraphs = []
    covered = 0
    for paragraph in document["paragraphs"]:
        start, end = max(left, paragraph["char_start"]), min(right, paragraph["char_end"])
        if start < end:
            covered += end - start
            paragraphs.append({"paragraph_index": paragraph["paragraph_index"], "kind": paragraph["kind"],
                "char_start": start, "char_end": end, "paragraph_text_sha256": paragraph["text_sha256"],
                "subsection_path": paragraph["subsection_path"], "note_headings": deepcopy(paragraph["note_headings"])})
    return {"paragraphs": paragraphs, "paragraph_kind_counts": dict(Counter(p["kind"] for p in paragraphs)),
        "interparagraph_separator_codepoints": right - left - covered,
        "coverage_scope": "normalized_view_paragraph_intersections_only_no_legal_role_inference"}


def prepare_source_occurrence_inventory(provenance_report, rows, *, provenance_inputs,
        expected_provenance_report_sha256, document_inputs, expected_document_population_sha256,
        max_occurrences=contexts.MAX_OCCURRENCES):
    """Replay complete provenance and enumerate unselected comparison occurrences.

    Every input physical row survives. Literal legal-ID equality only identifies
    comparison documents; it is not a cache-to-official-source correspondence.
    All exact overlapping matches are retained or a finite bound is refused.
    """
    from . import legal_span_provenance as provenance

    _need(type(rows) in (list, tuple) and 0 < len(rows) <= MAX_ROWS, "bounded complete raw row population required")
    _need(type(provenance_inputs) is dict and "expected_report_sha256" not in provenance_inputs,
          "independent provenance replay inputs required")
    checked = provenance.validate_span_provenance(provenance_report, rows,
        expected_report_sha256=expected_provenance_report_sha256, **provenance_inputs)
    _sha(expected_document_population_sha256, "complete document population")
    _need(type(document_inputs) is list and len(document_inputs) <= MAX_DOCUMENTS,
          "bounded complete document input population required")
    document_inputs = deepcopy(document_inputs)
    document_pins = _documents(document_inputs)
    _need(_digest(document_pins) == expected_document_population_sha256, "independent complete document population pin differs")
    _need(type(max_occurrences) is int and 0 < max_occurrences <= contexts.MAX_OCCURRENCES,
          "bounded complete occurrence population limit required")
    budget_bytes = len(_wire({"document_population": document_pins,
        "expected_record_sha256s": [r["record_sha256"] for r in checked["rows"]]}))
    def budget(amount):
        _need(amount <= MAX_REPORT_BYTES, "complete custody inventory byte bound exceeded; truncation refused")
    documents = []
    for item in document_inputs:
        arguments = {key:value for key,value in item.items() if key != "raw_bytes"}
        document = prepare_official_document(item["raw_bytes"], **arguments)
        budget_bytes += len(_wire(document)) + 1
        budget(budget_bytes)
        documents.append(document)
    result_rows = []
    for original in checked["rows"]:
        row_budget_start = budget_bytes
        identity = original["source_identity"]
        legal_id, text = identity.get("legal_id"), identity.get("source_text")
        valid_text = type(text) is str and bool(text) and len(text.encode("utf-8")) <= contexts.MAX_SELECTOR_BYTES
        candidates, total = [], 0
        for number, doc in enumerate(documents):
            if doc["descriptor"]["legal_id"] != legal_id:
                continue
            occurrences = []
            if doc["status"] == "comparison_document_extracted" and valid_text:
                selectors = contexts.exact_view_occurrences(doc["document"], document_inputs[number]["raw_bytes"],
                                                           text=text, max_occurrences=max_occurrences)
                for selector in selectors:
                    occurrence = {"selector": selector, "paragraph_coverage": _coverage(doc["document"], selector)}
                    budget_bytes += len(_wire(occurrence)) + 1
                    budget(budget_bytes)
                    occurrences.append(occurrence)
            total += len(occurrences)
            _need(total <= max_occurrences, "complete cross-document occurrence bound exceeded; truncation refused")
            candidates.append({"document_index": number, "document_report_sha256": doc["document_report_sha256"],
                "descriptor_sha256": doc["descriptor_sha256"], "document_status": doc["status"],
                "issues": deepcopy(doc["issues"]), "occurrences": occurrences, "occurrence_count": len(occurrences),
                "association_scope": "literal_legal_id_comparison_only_not_producer_source_correspondence"})
        unavailable = any(c["document_status"] != "comparison_document_extracted" for c in candidates)
        if not valid_text: status = "unsupported_or_missing_exact_source_text"
        elif not candidates: status = "comparison_document_missing"
        elif unavailable: status = "comparison_inventory_incomplete_document_unavailable_or_unsupported"
        elif total == 0: status = "zero_exact_comparison_occurrences"
        elif total == 1: status = "single_exact_comparison_occurrence_unselected"
        else: status = "multiple_exact_comparison_occurrences_unselected"
        result_row = {"row_ordinal": original["row_ordinal"], "raw_row_sha256": original["raw_row_sha256"],
            "record_sha256": original["record_sha256"], "record_id": original["record_id"],
            "source_identity": deepcopy(identity), "provenance_classification": deepcopy(original["classification"]),
            "comparison_documents": candidates, "exact_occurrence_count": total, "status": status,
            "selected_occurrence": None, "governing_source_binding": None, "authority": dict(AUTHORITY)}
        budget_bytes = row_budget_start + len(_wire(result_row)) + 1
        budget(budget_bytes)
        result_rows.append(result_row)
    report = {"schema": INVENTORY_SCHEMA, "provenance_report_sha256": expected_provenance_report_sha256,
        "document_population_sha256": expected_document_population_sha256, "document_population": document_pins,
        "documents": documents, "row_count": len(result_rows), "rows": result_rows,
        "expected_record_sha256s": [r["record_sha256"] for r in checked["rows"]],
        "status_counts": dict(Counter(r["status"] for r in result_rows)), "population_complete": True,
        "coverage_scope": "every_supplied_physical_record_and_independently_selected_comparison_document_only",
        "max_occurrences_per_row_across_all_comparison_documents": max_occurrences,
        "producer_edition_or_revision_mapping_inferred": False, "authority": dict(AUTHORITY)}
    report["inventory_sha256"] = _digest(report)
    return report


def source_occurrence_inventory_sha256(report):
    """Full canonical inventory digest including its internal inventory seal."""
    return _digest(report)


def validate_source_occurrence_inventory(report, provenance_report, rows, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256, "source occurrence inventory")
    _need(source_occurrence_inventory_sha256(report) == expected_report_sha256, "independent complete source inventory pin differs")
    expected = prepare_source_occurrence_inventory(provenance_report, rows, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "source occurrence inventory differs from complete independent replay")
    return expected


__all__ = ["OfficialSourceCustodyError", "acquisition_descriptor_sha256", "prepare_official_document",
    "document_report_sha256", "validate_official_document", "document_population_sha256",
    "prepare_source_occurrence_inventory", "source_occurrence_inventory_sha256", "validate_source_occurrence_inventory"]
