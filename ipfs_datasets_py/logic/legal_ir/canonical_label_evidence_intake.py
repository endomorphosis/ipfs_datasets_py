"""Bind declared review evidence without authenticating or admitting labels.

This dictionary boundary performs no I/O. ``recording`` contains the original
receipt and submission payloads, so the unchanged recorder can replay it.
Expected bindings are selected outside the package. Their content digests are
checked where values are supplied; file metadata and human provenance require
separate verification. This version handles the canonical normative packet,
not a general annotation schema for all catalog families.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime

from . import canonical_binding_review as recorder

SCHEMA = "canonical-binding-label-evidence/v1"
RECEIPT_SCHEMA = "canonical-binding-label-evidence-intake/v1"
MAX_INTERPRETATIONS = 32
MAX_PROVENANCE = 64
MAX_TEXT_BYTES = 16384
BINDING_FIELDS = {"content_sha256", "file_sha256", "file_bytes"}
EXPECTED_FIELDS = {"packet", "receipt", "submissions", "organizer", "process", "cohort"}
PACKAGE_FIELDS = {
    "schema", "packet_binding", "recording_binding", "organizer_binding",
    "review_process_binding", "cohort_policy_binding", "supersedes_package_sha256",
    "items", "content_sha256",
}
ITEM_FIELDS = {
    "item_id", "source_sha256", "input_sha256", "declaration_refs",
    "provenance_refs", "interpretations", "adjudication_ref",
}
DECLARATION_FIELDS = {
    "submission_binding", "item_id", "annotation_content_sha256", "meaning_signature_sha256",
}
PROVENANCE_FIELDS = {
    "process_id", "responsible_organizer", "principal_id", "role", "identity_method",
    "author_model_relationship", "independence_assessment", "inputs_exposed",
    "annotation_binding", "assessed_at_utc", "rationale", "limitations",
}
INTERPRETATION_FIELDS = {
    "interpretation_id", "family", "profile", "ordered_rules", "qualifier_scope",
    "coverage_assessment", "unrepresented_meaning", "formal_target_binding", "derivation_refs",
}
ADJUDICATION_FIELDS = {
    "principal_id", "declaration_refs", "interpretation_refs", "decision",
    "accepted_interpretation_ids", "unresolved_scope", "rationale",
    "adjudicated_at_utc", "provenance_ref",
}
DECISIONS = {
    "accept_unique", "accept_alternatives", "no_normative_rule", "needs_context",
    "unsupported", "abstain", "reject", "unresolved",
}
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    recorder._closed(value, fields, label)


def _text(value, label, *, blank=False, maximum=MAX_TEXT_BYTES):
    if blank and type(value) is str and value == "":
        return
    recorder._text(value, maximum, label)


def _strings(value, label, *, maximum=128):
    _require(type(value) is list and len(value) <= maximum, "bounded " + label + " list required")
    for entry in value:
        _text(entry, label + " entry", maximum=4096)


def _timestamp(value, label):
    _require(type(value) is str and _UTC.fullmatch(value), "explicit ISO UTC " + label + " required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid calendar UTC " + label) from error
    _require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
             "UTC " + label + " required")


def _binding(value, label):
    _closed(value, BINDING_FIELDS, label + " binding")
    for field in ("content_sha256", "file_sha256"):
        recorder._sha(value[field], label + " " + field)
    _require(type(value["file_bytes"]) is int and 0 < value["file_bytes"] <= recorder.MAX_JSON_BYTES,
             "bounded integer " + label + " file_bytes required")


def _content_binding(value, binding, label):
    _binding(binding, label)
    _require(recorder._digest(value) == binding["content_sha256"], label + " content binding mismatch")


def _declaration(ref, item, *, allowed=None):
    _closed(ref, DECLARATION_FIELDS, "declaration reference")
    _require(ref["item_id"] == item["item_id"], "declaration belongs to another item")
    submission = ref["submission_binding"]
    _closed(submission, {"submission_index", "submission_sha256"}, "declaration submission binding")
    index = submission["submission_index"]
    _require(type(index) is int and 0 <= index < recorder.MAX_SUBMISSIONS,
             "bounded integer submission_index required")
    recorder._sha(submission["submission_sha256"], "submission_sha256")
    recorder._sha(ref["annotation_content_sha256"], "annotation_content_sha256")
    recorder._sha(ref["meaning_signature_sha256"], "meaning_signature_sha256")
    matches = [entry for entry in item["received_declarations"]
               if entry["submission_index"] == index
               and entry["submission_sha256"] == submission["submission_sha256"]]
    _require(len(matches) == 1, "declaration is not recorded for this item/submission")
    entry = matches[0]
    _require(entry["complete"] is True and entry["missing_fields"] == [],
             "referenced declaration must be complete")
    _require(recorder._digest(entry["annotation"]) == ref["annotation_content_sha256"],
             "full annotation binding mismatch")
    _require(entry["meaning_signature_sha256"] == ref["meaning_signature_sha256"],
             "meaning signature binding mismatch")
    key = recorder._digest(ref)
    if allowed is not None:
        _require(key in allowed, "reference is absent from this item's declaration_refs")
    return key, entry


def _provenance(value, item, declarations, process):
    _closed(value, PROVENANCE_FIELDS, "declared provenance")
    for field in ("process_id", "responsible_organizer", "principal_id", "identity_method",
                  "author_model_relationship", "independence_assessment", "rationale", "limitations"):
        _text(value[field], "provenance " + field)
    _require(value["process_id"] == process["process_id"]
             and value["responsible_organizer"] == process["organizer_id"],
             "provenance does not match externally selected process/organizer")
    _require(type(value["role"]) is str and value["role"] in {"reviewer", "adjudicator"},
             "declared reviewer/adjudicator role required")
    key, entry = _declaration(value["annotation_binding"], item, allowed=declarations)
    if value["role"] == "reviewer":
        _require(value["principal_id"] == entry["annotation"]["reviewer_id"],
                 "reviewer provenance principal differs from annotation declaration")
    exposure = value["inputs_exposed"]
    _closed(exposure, {"source_input_sha256", "candidate_or_reference_exposed",
                       "organizer_metadata_exposed", "other_exposure"}, "declared exposure")
    _require(exposure["source_input_sha256"] == item["input_sha256"],
             "exposure belongs to another source/context input")
    for field in ("candidate_or_reference_exposed", "organizer_metadata_exposed"):
        _require(type(exposure[field]) is bool, "explicit Boolean exposure declaration required")
    _text(exposure["other_exposure"], "other_exposure", blank=True)
    _timestamp(value["assessed_at_utc"], "assessed_at_utc")
    return key


def _interpretation(value):
    _closed(value, INTERPRETATION_FIELDS, "declared interpretation")
    for field in ("interpretation_id", "family", "profile"):
        _text(value[field], field, maximum=256)
    _require(value["family"] == "deontic", "v1 interpretation schema supports canonical deontic facets only")
    # A named profile remains a declaration; this boundary qualifies no profile.
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review_admission import (
        _rules,
    )

    _require(type(value["ordered_rules"]) is list and not _rules(value["ordered_rules"]),
             "complete ordered seven-facet rules required")
    _text(value["qualifier_scope"], "qualifier_scope", blank=True)
    if any(rule[facet] for rule in value["ordered_rules"]
           for facet in ("conditions", "exceptions", "temporal")):
        _require(bool(value["qualifier_scope"].strip()), "qualifiers require explicit scope wording")
    coverage = value["coverage_assessment"]
    _closed(coverage, {"status", "omitted_meaning", "rationale"}, "declared coverage")
    _require(type(coverage["status"]) is str and coverage["status"] in {"complete", "partial", "unassessed"},
             "known declared coverage status required")
    _strings(coverage["omitted_meaning"], "omitted_meaning")
    _text(coverage["rationale"], "coverage rationale")
    _strings(value["unrepresented_meaning"], "unrepresented_meaning")
    if coverage["status"] == "complete":
        _require(not coverage["omitted_meaning"] and not value["unrepresented_meaning"],
                 "declared complete coverage cannot list omitted/unrepresented meaning")
    _require(value["formal_target_binding"] is None and type(value["derivation_refs"]) is list
             and value["derivation_refs"] == [],
             "v1 has no target derivation owner; formal_target_binding must remain null and derivation_refs empty")


def _adjudication(value, item, declarations, interpretations, provenance):
    _closed(value, ADJUDICATION_FIELDS, "declared adjudication")
    _text(value["principal_id"], "adjudicator principal_id", maximum=256)
    _text(value["rationale"], "adjudication rationale")
    _timestamp(value["adjudicated_at_utc"], "adjudicated_at_utc")
    refs = value["declaration_refs"]
    _require(type(refs) is list and 1 <= len(refs) <= recorder.MAX_SUBMISSIONS,
             "bounded nonempty adjudication declaration_refs required")
    keys = [_declaration(ref, item, allowed=declarations)[0] for ref in refs]
    _require(len(keys) == len(set(keys)), "duplicate adjudication declaration reference")
    for field in ("interpretation_refs", "accepted_interpretation_ids"):
        _strings(value[field], field, maximum=MAX_INTERPRETATIONS)
        _require(len(value[field]) == len(set(value[field])), "unique " + field + " required")
        _require(set(value[field]) <= interpretations, "unknown " + field)
    _require(set(value["accepted_interpretation_ids"]) <= set(value["interpretation_refs"]),
             "accepted interpretations must be referenced")
    decision = value["decision"]
    _require(type(decision) is str and decision in DECISIONS, "known declared adjudication decision required")
    accepted = len(value["accepted_interpretation_ids"])
    _require((decision == "accept_unique" and accepted == 1)
             or (decision == "accept_alternatives" and accepted >= 2)
             or (decision not in {"accept_unique", "accept_alternatives"} and accepted == 0),
             "adjudication decision/accepted interpretation count mismatch")
    _strings(value["unresolved_scope"], "unresolved_scope")
    if decision in {"accept_unique", "accept_alternatives"}:
        _require(not value["unresolved_scope"], "declared acceptance cannot leave unresolved scope")
    index = value["provenance_ref"]
    _require(type(index) is int and 0 <= index < len(provenance), "known integer adjudication provenance_ref required")
    selected = provenance[index]
    _require(selected["role"] == "adjudicator" and selected["principal_id"] == value["principal_id"],
             "adjudication requires matching declared adjudicator provenance")
    reviewers = {entry["annotation"]["reviewer_id"] for entry in item["received_declarations"] if entry["complete"]}
    _require(value["principal_id"] not in reviewers, "declared adjudicator overlaps a declared reviewer")
    _require(recorder._digest(selected["annotation_binding"]) in keys,
             "adjudicator provenance must bind an adjudicated declaration")


def validate_label_evidence_intake(packet, recording, package, *, expected_bindings, selected_process_binding):
    """Return detached diagnostic evidence; authentication/admission stay pending.

    ``expected_bindings`` has packet/receipt/submissions/organizer/process/cohort
    pins. Each pin has content_sha256, file_sha256 and file_bytes. Submissions
    retain original order. The selected process is null or a separate object
    with process_id, organizer_id and content_sha256. File metadata is external
    input, not observed by this dictionary function. No callback or verifier is
    selected from a submitted package.
    """
    recorder._raw([packet, recording, package, expected_bindings, selected_process_binding])
    _closed(recording, {"receipt", "reviewed_payloads"}, "recording replay envelope")
    _closed(expected_bindings, EXPECTED_FIELDS, "externally expected bindings")
    _closed(package, PACKAGE_FIELDS, "label evidence package")
    _require(package["schema"] == SCHEMA, "label evidence package schema required")
    recorder._sha(package["content_sha256"], "package content_sha256")
    body = {key: value for key, value in package.items() if key != "content_sha256"}
    _require(recorder._digest(body) == package["content_sha256"], "package content checksum mismatch")
    _require(package["supersedes_package_sha256"] is None,
             "v1 revision chains require a separate externally pinned revision owner")
    _content_binding(packet, expected_bindings["packet"], "packet")
    _content_binding(recording["receipt"], expected_bindings["receipt"], "recording receipt")
    for package_field, expected_field in (("packet_binding", "packet"), ("recording_binding", "receipt"),
                                           ("organizer_binding", "organizer"), ("review_process_binding", "process"),
                                           ("cohort_policy_binding", "cohort")):
        _require(recorder._raw(package[package_field]) == recorder._raw(expected_bindings[expected_field]),
                 "externally expected " + expected_field + " binding mismatch")
    payloads, pins = recording["reviewed_payloads"], expected_bindings["submissions"]
    _require(type(payloads) is list and type(pins) is list and len(payloads) == len(pins)
             and len(payloads) <= recorder.MAX_SUBMISSIONS, "ordered original submission bindings required")
    for payload, pin in zip(payloads, pins, strict=True):
        _content_binding(payload, pin, "submission")
    replay = recorder.validate_recording(recording["receipt"], packet, payloads,
                                        expected_packet_sha256=expected_bindings["packet"]["content_sha256"])
    rows = package["items"]
    _require(type(rows) is list and len(rows) <= recorder.MAX_ITEMS, "bounded package items required")
    if not rows:
        _require(selected_process_binding is None and all(expected_bindings[field] is None
                 for field in ("organizer", "process", "cohort")),
                 "empty readiness intake requires an explicitly unselected process and null metadata bindings")
    else:
        for field in ("organizer", "process", "cohort"):
            _binding(expected_bindings[field], field)
        _closed(selected_process_binding, {"process_id", "organizer_id", "content_sha256"}, "externally selected process")
        for field in ("process_id", "organizer_id"):
            _text(selected_process_binding[field], field, maximum=256)
        _require(selected_process_binding["content_sha256"] == expected_bindings["process"]["content_sha256"],
                 "unknown externally selected review process")
    original = {row["item_id"]: row for row in recording["receipt"]["items"]}
    evidence = {}
    for row in rows:
        _closed(row, ITEM_FIELDS, "evidence item")
        identity = row["item_id"]
        _require(type(identity) is str and identity in original, "unknown evidence item")
        _require(identity not in evidence, "duplicate evidence item")
        item = original[identity]
        for field in ("source_sha256", "input_sha256"):
            _require(row[field] == item[field], "evidence source/context input binding mismatch")
        refs = row["declaration_refs"]
        _require(type(refs) is list and 1 <= len(refs) <= recorder.MAX_SUBMISSIONS,
                 "nonempty bounded item declaration_refs required")
        declarations = [_declaration(ref, item)[0] for ref in refs]
        _require(len(declarations) == len(set(declarations)), "duplicate item declaration reference")
        allowed = set(declarations)
        provenance = row["provenance_refs"]
        _require(type(provenance) is list and 1 <= len(provenance) <= MAX_PROVENANCE,
                 "bounded nonempty declared provenance required")
        covered, seen = set(), set()
        for entry in provenance:
            key = _provenance(entry, item, allowed, selected_process_binding)
            entry_key = (entry["role"], entry["principal_id"], key)
            _require(entry_key not in seen, "duplicate declared provenance association")
            seen.add(entry_key)
            if entry["role"] == "reviewer":
                covered.add(key)
        _require(covered == allowed, "every declaration requires its own declared reviewer provenance/exposure")
        interpretations = row["interpretations"]
        _require(type(interpretations) is list and len(interpretations) <= MAX_INTERPRETATIONS,
                 "bounded declared interpretations required")
        ids = set()
        for interpretation in interpretations:
            _interpretation(interpretation)
            _require(interpretation["interpretation_id"] not in ids, "duplicate interpretation_id")
            ids.add(interpretation["interpretation_id"])
        if row["adjudication_ref"] is not None:
            _adjudication(row["adjudication_ref"], item, allowed, ids, provenance)
        evidence[identity] = row
    results = []
    for identity in sorted(original):
        item = original[identity]
        results.append({
            "item_id": identity, "source_sha256": item["source_sha256"], "input_sha256": item["input_sha256"],
            "recording_status": item["status"], "declared_evidence": deepcopy(evidence.get(identity)),
            "evidence_status": "declared_unverified" if identity in evidence else "pending",
            "verification_status": "pending", "admission_status": "pending",
            "external_adjudication_status": "pending", "independent_adjudication_completed": False,
            "masks": dict.fromkeys(recorder.MASK_FIELDS, 0), **recorder._AUTHORITY,
        })
    receipt = {
        "schema": RECEIPT_SCHEMA, "status": "declared_evidence_intake_only" if rows else "pending",
        "organizer_private": True, "intake_scope": "canonical_normative_packet_declaration_integrity_only",
        "expected_bindings": deepcopy(expected_bindings), "selected_process_binding": deepcopy(selected_process_binding),
        "package_content_sha256": package["content_sha256"], "recording_receipt_sha256": replay["receipt_sha256"],
        "item_count": len(results), "declared_package_item_count": len(rows), "items": results,
        "verification_status": "pending", "admission_status": "pending", "file_bindings_verified": False,
        "metadata_content_verified": False, "semantic_profile_validated": False,
        "formal_targets_admitted": 0, "human_reviews_authenticated": 0, "independent_reviews_authenticated": 0,
        "masks": dict.fromkeys(recorder.MASK_FIELDS, 0), "training_executed": False,
        "automatic_adjudication": False, "submissions_created": False,
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
        **recorder._AUTHORITY,
    }
    receipt["content_sha256"] = recorder._digest(receipt)
    recorder._raw(receipt)
    return receipt


__all__ = ["validate_label_evidence_intake"]
