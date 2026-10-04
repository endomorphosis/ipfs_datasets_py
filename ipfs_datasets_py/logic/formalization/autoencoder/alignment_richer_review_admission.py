"""Record submitted richer source/context annotations without adjudication.

The immutable source/context packet is the admission boundary. Exact ordered
reviewer-authored rules and freeform qualifier scope determine concordance;
the organizer's authored answers never select reviews or resolve disagreement.
Declared names and timestamps are not authenticated human identities or author
independence. Even matching complete submissions remain diagnostic, with no
independent source-fidelity, proof or production authority.

This bounded dictionary API performs no I/O, annotation generation, model call
or proof. Its sole lazy dependency validates the existing blank preparation.
File callers must reject duplicate JSON keys before supplying dictionaries.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime

SCHEMA = "alignment-richer-review-admission/v1"
VALIDATION_SCHEMA = "alignment-richer-review-admission-validation/v1"
GUIDE_SCHEMA = "alignment-richer-review-submission-guide/v1"
REVIEWER_SCHEMA = "alignment-richer-source-context-reviewer/v1"
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
INTERPRETATION_STATUSES = ("normative", "no_normative_rule", "ambiguous", "unsupported")
ITEM_STATUSES = ("pending", "single_review", "agreed_multiple_reviews", "disputed", "ambiguous", "unsupported")
MAX_ITEMS = 34
MAX_SUBMISSIONS = 20
MAX_RULES = 32
MAX_QUALIFIERS = 128
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ATOM_BYTES = 4096
MAX_FREEFORM_BYTES = 16384
_DIGEST_RECIPE = "sha256_sorted_compact_utf8_json_no_nan_no_newline"
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
_PAYLOAD_FIELDS = {"schema", "instructions", "items"}
_ITEM_FIELDS = {"item_id", "source_text", "source_sha256", "context", "input_sha256", "annotation"}
_ANNOTATION_FIELDS = ("interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules",
                      "freeform_qualifier_scope", "notes", "reviewer_id", "reviewed_at_utc")
_SIGNATURE_FIELDS = ("interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules",
                     "freeform_qualifier_scope")
_AUTHORITY = {"qualified": False, "production_admitted": False, "independent_fidelity_available": False,
              "source_fidelity_established": False, "source_semantics_verified": False, "proof_authority": False,
              "reviewer_identity_attestations_created": False, "reviewer_attestations_created": False,
              "reviewer_independence_authenticated": False, "source_author_independence_authenticated": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise ValueError("bounded finite ordinary UTF8 JSON required") from error
    _require(len(encoded) <= MAX_JSON_BYTES, "richer review admission exceeds JSON byte bound")
    return encoded


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _text(value, maximum, label, *, blank=False, trimmed=False):
    _require(type(value) is str and "\x00" not in value and (blank or bool(value.strip())),
             label + " must be bounded UTF8 text without NUL")
    try:
        count = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError(label + " must be valid UTF8") from error
    _require(count <= maximum, label + " exceeds UTF8 byte bound")
    if trimmed:
        _require(value == value.strip(), label + " must not have surrounding whitespace")


def _rules(value):
    """Check literal human slots; never coerce, normalize, reorder or deduplicate."""
    _require(type(value) is list and len(value) <= MAX_RULES, "bounded normative_rules list required")
    missing = []
    for index, rule in enumerate(value):
        _closed(rule, FACETS, "seven-facet normative rule")
        for facet in FACETS:
            atom = rule[facet]
            path = f"normative_rules[{index}].{facet}"
            if atom is None:
                missing.append(path)
            elif facet == "modality":
                _require(type(atom) is str and atom in ("O", "P", "F"), "review modality must be O, P, or F")
            elif facet in ("actor", "action", "object"):
                _text(atom, MAX_ATOM_BYTES, path, blank=facet == "object")
            else:
                _require(type(atom) is list and len(atom) <= MAX_QUALIFIERS, "bounded " + path + " list required")
                for position, qualifier in enumerate(atom):
                    _text(qualifier, MAX_ATOM_BYTES, f"{path}[{position}]")
    return missing


def _annotation(value):
    """Return unanswered slots; partial typed values stay pending, contradictions fail."""
    _closed(value, _ANNOTATION_FIELDS, "richer review annotation")
    status = value["interpretation_status"]
    _require(status is None or (type(status) is str and status in INTERPRETATION_STATUSES),
             "unknown review interpretation_status")
    for field in ("ambiguity", "unsupported_meaning"):
        _require(value[field] is None or type(value[field]) is bool, "explicit Boolean " + field + " required")
    rules = value["normative_rules"]
    nested_missing = _rules(rules) if rules is not None else []
    for field in ("freeform_qualifier_scope", "notes"):
        if value[field] is not None:
            _text(value[field], MAX_FREEFORM_BYTES, field, blank=True)
    reviewer = value["reviewer_id"]
    if reviewer is not None:
        _text(reviewer, 256, "declared reviewer_id", trimmed=True)
    timestamp = value["reviewed_at_utc"]
    if timestamp is not None:
        _text(timestamp, 64, "reviewed_at_utc", trimmed=True)
        _require(_UTC.fullmatch(timestamp), "reviewed_at_utc must be an explicit ISO UTC timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("invalid calendar UTC review timestamp") from error
        _require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
                 "review timestamp must have UTC offset")

    if status in ("normative", "no_normative_rule"):
        for field in ("ambiguity", "unsupported_meaning"):
            _require(value[field] is None or value[field] is False, status + " cannot assert " + field)
    if status == "normative":
        _require(rules is None or bool(rules), "normative interpretation requires at least one rule")
        qualifiers = rules is not None and any(rule[facet] for rule in rules
                                               for facet in ("conditions", "exceptions", "temporal"))
        scope = value["freeform_qualifier_scope"]
        _require(not qualifiers or scope is None or bool(scope.strip()),
                 "normative qualifiers require nonempty freeform_qualifier_scope")
    elif status == "no_normative_rule":
        _require(rules is None or rules == [], "no_normative_rule requires an explicit empty normative_rules list")
    elif status == "ambiguous":
        _require(value["ambiguity"] is None or value["ambiguity"] is True, "ambiguous interpretation requires ambiguity=True")
    elif status == "unsupported":
        _require(value["unsupported_meaning"] is None or value["unsupported_meaning"] is True,
                 "unsupported interpretation requires unsupported_meaning=True")

    needs_reason = status in ("no_normative_rule", "ambiguous", "unsupported")
    _require(not needs_reason or value["notes"] is None or bool(value["notes"].strip()),
             "nonempty notes rationale required for " + str(status))
    missing = [field for field in _ANNOTATION_FIELDS if field != "notes" and value[field] is None]
    missing.extend(nested_missing)
    if needs_reason and value["notes"] is None:
        missing.append("notes")
    return missing


def _meaning_signature(annotation):
    return _digest({field: annotation[field] for field in _SIGNATURE_FIELDS})


def _blank_bundle(bundle):
    _require(type(bundle) is dict, "richer blank review bundle required")
    _raw(bundle)
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review import (
        validate_richer_review_bundle,
    )

    validation = validate_richer_review_bundle(bundle)
    _require(type(validation["item_count"]) is int and 1 <= validation["item_count"] <= MAX_ITEMS,
             "richer blank review item budget exceeded")
    original = bundle["reviewer_payload"]
    _closed(original, _PAYLOAD_FIELDS, "prepared richer reviewer payload")
    _require(original["schema"] == REVIEWER_SCHEMA, "richer source/context reviewer schema required")
    items = {item["item_id"]: item for item in original["items"]}
    _require(len(items) == len(original["items"]) and len({item["input_sha256"] for item in items.values()}) == len(items),
             "unique prepared source/context input identities required")
    return original, items


def _payload(value, original, items):
    _closed(value, _PAYLOAD_FIELDS, "submitted richer reviewer payload")
    _raw(value)
    _require(_raw({name: value[name] for name in _PAYLOAD_FIELDS - {"items"}}) ==
             _raw({name: original[name] for name in _PAYLOAD_FIELDS - {"items"}}),
             "immutable richer reviewer metadata changed")
    submitted = value["items"]
    _require(type(submitted) is list and 1 <= len(submitted) <= MAX_ITEMS, "bounded nonempty submitted items required")
    seen, checked = set(), []
    for item in submitted:
        _closed(item, _ITEM_FIELDS, "submitted richer item")
        identity = item["item_id"]
        _require(type(identity) is str and identity in items, "unknown reviewed item")
        _require(identity not in seen, "duplicate item in review submission")
        seen.add(identity)
        immutable = {name: item[name] for name in _ITEM_FIELDS - {"annotation"}}
        expected = {name: items[identity][name] for name in _ITEM_FIELDS - {"annotation"}}
        _require(_raw(immutable) == _raw(expected), "immutable source/context/input envelope changed")
        missing = _annotation(item["annotation"])
        checked.append((item, missing))
    return checked


def admit_richer_reviews(bundle: dict, reviewed_payloads: list[dict]) -> dict:
    """Record literal source/context submissions and conservative concordance.

    Source-only and explicit-context rows use their complete prepared envelopes.
    Item subsets and reordering are allowed; duplicate payloads or declarations
    by the same reviewer for the same input are refused. Completeness is a typed
    submission property, not evidence that a person independently reviewed it.
    Meaning signatures include ordered rules, duplicates and exact scope text.
    Distinct wording of scope can therefore require external adjudication even
    if an eventual reviewer regards the formulations as equivalent.
    """
    original, items = _blank_bundle(bundle)
    _require(type(reviewed_payloads) is list and len(reviewed_payloads) <= MAX_SUBMISSIONS,
             "bounded richer review submissions required")
    _raw(reviewed_payloads)
    received = {identity: [] for identity in items}
    submissions, seen_payloads, reviewer_inputs = [], set(), set()
    for index, payload in enumerate(reviewed_payloads):
        checked = _payload(payload, original, items)
        submission_digest = _digest(payload)
        _require(submission_digest not in seen_payloads, "duplicate review submission")
        seen_payloads.add(submission_digest)
        declared_reviewers = set()
        for item, missing in checked:
            annotation = item["annotation"]
            identity, reviewer = item["item_id"], annotation["reviewer_id"]
            if reviewer is not None:
                declaration = (item["input_sha256"], reviewer)
                _require(declaration not in reviewer_inputs, "duplicate reviewer for the same input")
                reviewer_inputs.add(declaration)
                declared_reviewers.add(reviewer)
            complete = not missing
            received[identity].append({"submission_index": index, "submission_sha256": submission_digest,
                                       "annotation": deepcopy(annotation), "complete": complete,
                                       "missing_fields": missing,
                                       "semantic_signature_sha256": _meaning_signature(annotation) if complete else None})
        submissions.append({"submission_index": index, "payload_sha256": submission_digest,
                            "item_count": len(checked), "declared_reviewer_ids": sorted(declared_reviewers),
                            "identity_authenticated": False, "source_author_independence_authenticated": False,
                            "reviewer_attestation_created": False})

    results = []
    for identity in sorted(items):
        complete = [entry for entry in received[identity] if entry["complete"]]
        signatures = {entry["semantic_signature_sha256"] for entry in complete}
        status, consensus = "pending", None
        if complete:
            if len(signatures) != 1:
                status = "disputed"
            else:
                consensus = complete[0]["annotation"]["interpretation_status"]
                status = (consensus if consensus in ("ambiguous", "unsupported") else
                          "agreed_multiple_reviews" if len(complete) >= 2 else "single_review")
        prepared = items[identity]
        envelope = {name: deepcopy(prepared[name]) for name in _ITEM_FIELDS - {"annotation"}}
        results.append({**envelope, "review_input_envelope_sha256": _digest(envelope), "status": status,
                        "consensus_interpretation_status": consensus,
                        "complete_distinct_reviewer_count": len(complete),
                        "pending_submission_count": len(received[identity]) - len(complete),
                        "semantic_signature_count": len(signatures), "received_submissions": received[identity],
                        "external_adjudication_status": "pending", "independent_adjudication_completed": False,
                        **_AUTHORITY})
    counts = Counter(item["status"] for item in results)
    interpretations = Counter(item["consensus_interpretation_status"] for item in results
                              if item["consensus_interpretation_status"] is not None)
    completed = sum(item["complete_distinct_reviewer_count"] for item in results)
    receipt = {"schema": SCHEMA, "status": "submitted_reviews_recorded" if completed else "pending",
               "evaluation_role": "exposed_development", "organizer_private": True,
               "review_bundle_sha256": _digest(bundle), "prepared_bundle_payload_sha256": bundle["bundle_sha256"],
               "reviewer_payload_sha256": _digest(original), "organizer_payload_sha256": _digest(bundle["organizer_payload"]),
               "reviewer_manifest_sha256": _digest(bundle["reviewer_manifest"]),
               "organizer_manifest_sha256": _digest(bundle["organizer_manifest"]),
               "source_bindings_sha256": bundle["organizer_payload"]["source_bindings_sha256"],
               "input_manifest_sha256": bundle["organizer_payload"]["input_manifest_sha256"],
               "digest_recipe": _DIGEST_RECIPE, "item_count": len(items), "submission_count": len(submissions),
               "submissions": submissions, "items": results,
               "status_counts": {name: counts[name] for name in ITEM_STATUSES},
               "interpretation_status_counts": {name: interpretations[name] for name in INTERPRETATION_STATUSES},
               "declared_completed_annotation_count": completed, "human_reviews_authenticated": 0,
               "independent_reviews_authenticated": 0, "reference_used_to_resolve_disputes": False,
               "authored_reference_scoring_executed": False, "candidate_aware_computation": False,
               "automatic_adjudication": False,
               "reviewer_identity_evidence": {"status": "unavailable", "authenticated": False},
               "source_author_independence_evidence": {"status": "unavailable", "authenticated": False},
               "reviewer_attestation_evidence": {"status": "unavailable", "authenticated": False},
               "primary_independently_adjudicated_fidelity": {"status": "unavailable", "value": None},
               "native_useful_proof_coverage": {"status": "unrun", "value": None},
               "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
               "training_executed": False, "submissions_created": False, **_AUTHORITY}
    receipt["receipt_sha256"] = _digest(receipt)
    _raw(receipt)
    return receipt


def validate_richer_review_admission(receipt: dict, bundle: dict, payloads: list[dict]) -> dict:
    """Recompute exact diagnostic admission, refusing tamper and numeric aliases."""
    _require(type(receipt) is dict, "richer admission receipt object required")
    supplied = _raw(receipt)
    expected = admit_richer_reviews(bundle, payloads)
    _require(supplied == _raw(expected), "richer admission receipt differs from exact submission replay")
    return {"schema": VALIDATION_SCHEMA, "status": "validated_diagnostic_admission_only",
            "receipt_sha256": expected["receipt_sha256"], "review_bundle_sha256": expected["review_bundle_sha256"],
            "item_count": expected["item_count"], "submission_count": expected["submission_count"],
            "status_counts": deepcopy(expected["status_counts"]),
            "declared_completed_annotation_count": expected["declared_completed_annotation_count"],
            "human_reviews_authenticated": 0, "independent_reviews_authenticated": 0,
            "source_meaning_adjudicated": False, "automatic_adjudication": False, **_AUTHORITY}


def richer_review_submission_guide() -> dict:
    """Return instructions without suggested answers, identities or timestamps."""
    return {"schema": GUIDE_SCHEMA, "reviewer_payload_schema": REVIEWER_SCHEMA,
            "submission_format": "Copy the reviewer payload, retain instructions and exact item envelopes, and fill annotation slots only.",
            "allowed_changes": "Fill annotations; optionally submit a nonempty subset or reorder items. Never edit source, context, hashes, or item IDs.",
            "annotation_fields": list(_ANNOTATION_FIELDS),
            "interpretation_statuses": {
                "normative": "At least one proposed normative rule, ambiguity=false and unsupported_meaning=false.",
                "no_normative_rule": "Explicit normative_rules=[], both flags false, and nonempty notes explaining the absence of a normative rule.",
                "ambiguous": "ambiguity=true and nonempty notes describing competing interpretations or needed clarification; proposed rules may be tentative or [].",
                "unsupported": "unsupported_meaning=true and nonempty notes explaining meaning not expressible in the flat facets; proposed rules may be tentative or []."},
            "rule_contract": {"fields": list(FACETS), "modality": "O, P, or F",
                              "actor_action": "Nonempty UTF8 strings.",
                              "object": "A UTF8 string; empty string explicitly records no object.",
                              "qualifiers": "conditions, exceptions and temporal are lists of nonempty UTF8 strings; order and duplicates are retained.",
                              "partial": "Null annotation fields or null whole rule facets remain unanswered. Null qualifier-list members are invalid."},
            "freeform_qualifier_scope": "An explicit string is required for completion. Empty string means no additional scope; normative rules with qualifiers need nonempty scope explaining connectives, attachment, binding and timing.",
            "notes": "Optional for normative interpretations; required nonempty rationale for the other interpretation statuses.",
            "declared_identity": "Supply a trimmed nonempty reviewer_id and a calendar-valid ISO UTC timestamp using Z or +00:00. This records declarations, not identity or independence authentication.",
            "agreement_recipe": "Exact interpretation status, flags, ordered rules and scope text; notes, identity and time do not determine concordance. Disagreements need external adjudication.",
            "prohibited_hints": "Do not add candidate outputs, authored references, expectations, split labels, original IDs, qualification or authentication claims.",
            "bounds": {"items_per_payload": MAX_ITEMS, "submissions": MAX_SUBMISSIONS,
                       "rules_per_annotation": MAX_RULES, "qualifiers_per_facet": MAX_QUALIFIERS,
                       "atom_utf8_bytes": MAX_ATOM_BYTES, "scope_notes_utf8_bytes": MAX_FREEFORM_BYTES,
                       "aggregate_json_bytes": MAX_JSON_BYTES},
            "digest_recipe": _DIGEST_RECIPE, "generated_reviews": 0, "automatic_adjudication": False,
            "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0, **_AUTHORITY}


__all__ = ["admit_richer_reviews", "validate_richer_review_admission", "richer_review_submission_guide"]
