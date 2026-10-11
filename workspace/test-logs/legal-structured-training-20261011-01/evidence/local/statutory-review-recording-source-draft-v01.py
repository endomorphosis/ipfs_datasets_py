"""Record raw-section review declarations without authenticating legal labels.

This profile binds the immutable statutory physical-source/context packet. It
is not the authored empty-context review or signed alignment-handoff profile.
Source/evidence byte integrity, filled slots, exact agreement and declared
adjudication remain separate from human identity, independence and admission.
All supervision masks and authority flags remain zero/false. No model, encoder,
compiler, prover, network request or fitting is performed.

The bounded dictionary API reads only explicitly resolved packet/evidence
artifacts through the unchanged statutory packet owner. File callers must use
``parse_json_bytes`` or equivalently reject duplicate keys and strict UTF8 errors
before constructing dictionaries. Canonical-content hashes are not file hashes.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re

from . import statutory_source_review as sources

SUBMISSION_SCHEMA = "statutory-source-context-review-submission/v1"
SCHEMA = "statutory-source-context-review-recording/v1"
VALIDATION_SCHEMA = "statutory-source-context-review-recording-validation/v1"
GUIDE_SCHEMA = "statutory-source-context-review-submission-guide/v1"
ADJUDICATION_SCHEMA = "statutory-source-context-adjudication-declarations/v1"
ADJUDICATION_RECORDING_SCHEMA = "statutory-source-context-adjudication-recording/v1"
ADJUDICATION_VALIDATION_SCHEMA = "statutory-source-context-adjudication-recording-validation/v1"
DIGEST_RECIPE = sources.DIGEST_RECIPE
MAX_SUBMISSIONS = 20
MAX_RULES = 64
MAX_ANCHORS = 256
MAX_TEXT_BYTES = 4096
MAX_JSON_BYTES = sources.MAX_JSON_BYTES
MAX_EVIDENCE_BYTES = sources.MAX_METADATA_BYTES
MAX_EVIDENCE_ARTIFACTS = sources.MAX_METADATA_ARTIFACTS
FACETS = ("modality", *sources.SPAN_FIELDS)
QUALIFIERS = ("conditions", "exceptions", "temporal")
INTERPRETATIONS = ("normative", "no_normative_rule", "needs_context", "ambiguous", "unsupported")
ITEM_STATUSES = ("pending", "partial_declarations", "single_complete_declaration",
                 "exact_multiple_declaration_agreement", "disputed", "needs_context", "ambiguous", "unsupported")
ELIGIBILITY = ("eligible_normative", "not_normative", "needs_context", "ambiguous", "unsupported")
DEFINITIONS = ("definition_only", "mixed_definition_and_norm", "no_definition_declared", "undetermined")
MULTI_RULE = ("single_rule", "multiple_rules", "no_rule", "undetermined")
CONTEXT_SUFFICIENCY = ("sufficient_as_declared", "needs_external_context", "undetermined")
EVIDENCE_FIELDS = ("identity_evidence", "independence_evidence", "review_process_evidence")
EXPOSURE_FIELDS = ("candidate_or_reference_exposed", "organizer_metadata_exposed", "other_exposure")
ENVELOPE_FIELDS = ("item_id", "input_sha256", "physical_identity_sha256", "source_text_sha256",
                   "context_artifact", "selected_context_char_offsets")
SUBMISSION_FIELDS = {"schema", "packet_sha256", "submission_id", "items"}
ITEM_FIELDS = {*ENVELOPE_FIELDS, "review", "context_review", "evidence", "exposure_declaration"}
ANCHOR_FIELDS = {"anchor_id", "rule_index", "facet", "coordinate_space", "char_start", "char_end", "text"}
TRIGGER_FIELDS = {"coordinate_space", "char_start", "char_end", "text"}
BOUNDARY_FIELDS = {*TRIGGER_FIELDS, "context_artifact", "kind"}
ATTACHMENT_FIELDS = {"attachment_id", "rule_index", "facet", "anchor_ids", "affected_rule_indices",
                     "scope_kind", "scope_text"}
ADJUDICATION_FIELDS = {"item_id", "principal_id", "adjudicated_at_utc", "declaration_refs", "decision",
                       "accepted_declaration_refs", "unresolved_scope", "rationale", "evidence"}
DECISIONS = ("accept_unique", "accept_alternatives", "no_normative_rule", "needs_context", "unsupported",
             "abstain", "reject", "unresolved")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    sources._closed(value, fields, label)


def _wire(value):
    return sources._wire(value)


def digest(value):
    """Hash complete canonical content, not pretty-file bytes or a body seal."""
    return hashlib.sha256(_wire(value)).hexdigest()


def parse_json_bytes(raw):
    """Decode bounded strict UTF8 ordinary JSON and reject duplicate keys."""
    _require(type(raw) is bytes and len(raw) <= MAX_JSON_BYTES, "bounded exact JSON bytes required")
    return sources._parse(raw)


def _detach(value):
    return parse_json_bytes(_wire(value))


def _text(value, label, *, blank=False, maximum=MAX_TEXT_BYTES):
    if blank and value == "" and type(value) is str:
        return
    sources._text(value, label, maximum)


def _strings(value, label, maximum=128):
    _require(type(value) is list and len(value) <= maximum, "bounded " + label + " list required")
    for entry in value:
        _text(entry, label + " entry")


def _enum(value, choices, label):
    _require(type(value) is str and value in choices, "known declared " + label + " required")


def _time(value, label):
    _require(type(value) is str and _UTC.fullmatch(value), "explicit UTC " + label + " required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("valid UTC calendar " + label + " required") from error
    _require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
             "UTC " + label + " required")


def _seal(value):
    return {**value, "content_sha256": digest(value)}


def _false():
    return {**sources._false(), "human_review_authenticated": False,
            "independent_adjudication_completed": False, "signature_verification_executed": False,
            "completed_submissions_generated": False, "target_created": False,
            "reviewer_blindness_verified": False, "evidence_contents_interpreted": False,
            "file_bytes_verified_by_dictionary_api": False}


def _masks():
    return sources._masks()


def _envelope(item):
    return {**{field: deepcopy(item[field]) for field in ENVELOPE_FIELDS[:4]},
            "context_artifact": deepcopy(item["context"]["artifact"]),
            "selected_context_char_offsets": [item["context"]["selected_char_start"],
                                               item["context"]["selected_char_end"]]}


def _packet(packet, expected, resolver):
    snapshot = _detach(packet)
    validation = sources.validate_blank_packet(snapshot, expected_packet_sha256=expected,
                                               artifact_resolver=resolver)
    return snapshot, validation


def _evidence(value, label, evidence, resolver):
    if value is None:
        return
    ref = sources._artifact(value, MAX_EVIDENCE_BYTES, label)
    key = ref["sha256"]
    if key not in evidence:
        _require(len(evidence) < MAX_EVIDENCE_ARTIFACTS
                 and sum(entry["ref"]["bytes"] for entry in evidence.values()) + ref["bytes"] <= MAX_EVIDENCE_BYTES,
                 "aggregate review evidence budget exceeded")
        evidence[key] = {"ref": ref, "raw": sources._read(ref, resolver, MAX_EVIDENCE_BYTES)}
    _require(evidence[key]["ref"] == ref, "evidence SHA/size drift")


def _evidence_fields(value, evidence, resolver):
    _closed(value, EVIDENCE_FIELDS, "declared evidence references")
    for field in EVIDENCE_FIELDS:
        _evidence(value[field], field, evidence, resolver)


def _close_evidence(evidence, resolver):
    for entry in evidence.values():
        _require(sources._read(entry["ref"], resolver, MAX_EVIDENCE_BYTES) == entry["raw"],
                 "review evidence changed across recording")


def _literal(value, text, coordinate_space, fields, label):
    _closed(value, fields, label)
    _require(value["coordinate_space"] == coordinate_space, "explicit " + coordinate_space + " required")
    left, right = value["char_start"], value["char_end"]
    sources._integer(left, label + " char_start")
    sources._integer(right, label + " char_end")
    _text(value["text"], label + " literal", maximum=sources.MAX_CONTEXT_BYTES)
    _require(left < right <= len(text) and text[left:right] == value["text"],
             label + " source/context literal selector mismatch")


def _rules(value):
    _require(type(value) is list and len(value) <= MAX_RULES, "bounded ordered normative rules required")
    for rule in value:
        _closed(rule, FACETS, "declared normative rule")
        _enum(rule["modality"], ("O", "P", "F"), "modality")
        for facet in ("actor", "action"):
            _text(rule[facet], "rule " + facet)
        _text(rule["object"], "rule object", blank=True)
        for facet in QUALIFIERS:
            _strings(rule[facet], "rule " + facet, maximum=16)


def _annotation(row, item, contexts, evidence, resolver):
    review, context = row["review"], row["context_review"]
    _closed(review, sources.REVIEW_FIELDS, "review questions")
    _closed(context, sources.CONTEXT_REVIEW_FIELDS, "context questions")
    missing = ["review." + field for field, value in review.items() if value is None]
    missing += ["context_review." + field for field, value in context.items() if value is None]
    choices = {"normative_eligibility": ELIGIBILITY, "definition_status": DEFINITIONS,
               "multi_rule_status": MULTI_RULE, "interpretation_status": INTERPRETATIONS}
    for field, values in choices.items():
        if review[field] is not None:
            _enum(review[field], values, field)
    for field in ("ambiguity", "unsupported_meaning"):
        if review[field] is not None:
            _strings(review[field], field)
    for field in ("freeform_qualifier_scope", "notes"):
        if review[field] is not None:
            _text(review[field], field, blank=True)
    if review["reviewer_id"] is not None:
        _text(review["reviewer_id"], "declared reviewer_id", maximum=512)
    if review["reviewed_at_utc"] is not None:
        _time(review["reviewed_at_utc"], "reviewed_at_utc")
    rules = review["normative_rules"]
    if rules is not None:
        _rules(rules)
        if review["interpretation_status"] == "normative":
            _require(bool(rules), "normative declaration requires nonempty rules; null is unanswered")
        elif review["interpretation_status"] is not None:
            _require(not rules, "non-normative declaration must not provide normative rules")
        if review["multi_rule_status"] == "single_rule":
            _require(len(rules) == 1, "single_rule declaration requires exactly one rule")
        if review["multi_rule_status"] == "multiple_rules":
            _require(len(rules) >= 2, "multiple_rules declaration requires multiple rules")
        if review["multi_rule_status"] == "no_rule":
            _require(not rules, "no_rule declaration requires explicit absent rules")
    anchors = review["source_role_anchors"]
    by_anchor = {}
    if anchors is not None:
        _require(type(anchors) is list and len(anchors) <= MAX_ANCHORS, "bounded source-role anchor list required")
        for anchor in anchors:
            _literal(anchor, item["input"]["source_text"], "selected_source_unicode_characters",
                     ANCHOR_FIELDS, "source-role anchor")
            _text(anchor["anchor_id"], "anchor_id", maximum=256)
            _require(anchor["anchor_id"] not in by_anchor, "duplicate anchor_id")
            _enum(anchor["facet"], sources.SPAN_FIELDS, "anchor facet")
            index = anchor["rule_index"]
            sources._integer(index, "anchor rule_index")
            _require(rules is not None and index < len(rules), "anchor must reference a declared rule")
            by_anchor[anchor["anchor_id"]] = anchor
    attachments = review["qualifier_attachments"]
    if attachments is not None:
        _require(type(attachments) is list and len(attachments) <= MAX_ANCHORS, "bounded qualifier attachments required")
        seen = set()
        for attachment in attachments:
            _closed(attachment, ATTACHMENT_FIELDS, "qualifier attachment")
            _text(attachment["attachment_id"], "attachment_id", maximum=256)
            _require(attachment["attachment_id"] not in seen, "duplicate attachment_id")
            seen.add(attachment["attachment_id"])
            _enum(attachment["facet"], QUALIFIERS, "qualifier facet")
            index = attachment["rule_index"]
            sources._integer(index, "attachment rule_index")
            _require(rules is not None and index < len(rules), "attachment must reference a declared rule")
            _strings(attachment["anchor_ids"], "attachment anchor_ids", maximum=MAX_ANCHORS)
            _require(len(set(attachment["anchor_ids"])) == len(attachment["anchor_ids"]), "duplicate attachment anchor reference")
            for identity in attachment["anchor_ids"]:
                _require(identity in by_anchor and by_anchor[identity]["rule_index"] == index
                         and by_anchor[identity]["facet"] == attachment["facet"],
                         "attachment anchor reference must match rule/facet")
            affected = attachment["affected_rule_indices"]
            _require(type(affected) is list and 1 <= len(affected) <= MAX_RULES, "bounded nonempty affected rules required")
            for target in affected:
                sources._integer(target, "affected rule_index")
                _require(target < len(rules), "unknown affected rule_index")
            _require(len(set(affected)) == len(affected), "duplicate affected rule_index")
            _enum(attachment["scope_kind"], ("rule", "shared_rules", "undetermined"), "qualifier scope kind")
            if attachment["scope_kind"] == "rule":
                _require(affected == [index], "rule qualifier scope requires its single rule")
            if attachment["scope_kind"] == "shared_rules":
                _require(len(affected) >= 2, "shared_rules scope requires multiple rules")
            _text(attachment["scope_text"], "qualifier scope text")
    if review["trigger"] is not None:
        _require(type(review["trigger"]) is list and len(review["trigger"]) <= MAX_ANCHORS, "bounded trigger anchors required")
        for trigger in review["trigger"]:
            _literal(trigger, item["input"]["source_text"], "selected_source_unicode_characters", TRIGGER_FIELDS, "trigger")
    if context["context_required_for_interpretation"] is not None:
        _require(type(context["context_required_for_interpretation"]) is bool, "explicit context-required Boolean required")
    for field in ("governing_definitions", "cross_references", "unresolved_dependencies"):
        if context[field] is not None:
            _strings(context[field], field)
    if context["context_sufficiency"] is not None:
        _enum(context["context_sufficiency"], CONTEXT_SUFFICIENCY, "context sufficiency")
    boundaries = context["operative_versus_editorial_boundaries"]
    if boundaries is not None:
        _require(type(boundaries) is list and len(boundaries) <= MAX_ANCHORS, "bounded context boundaries required")
        for boundary in boundaries:
            _literal(boundary, contexts[item["context"]["artifact"]["sha256"]],
                     "complete_raw_section_unicode_characters", BOUNDARY_FIELDS, "context boundary")
            _require(boundary["context_artifact"] == item["context"]["artifact"], "context boundary artifact mismatch")
            _enum(boundary["kind"], ("operative", "editorial", "undetermined"), "context boundary kind")
    if context["source_authority_or_currentness_evidence"] is not None:
        refs = context["source_authority_or_currentness_evidence"]
        _require(type(refs) is list and len(refs) <= MAX_EVIDENCE_ARTIFACTS, "bounded source-authority evidence references required")
        seen = set()
        for ref in refs:
            _require(type(ref) is dict, "source-authority evidence reference required")
            _evidence(ref, "source-authority evidence", evidence, resolver)
            _require(ref["sha256"] not in seen, "duplicate source-authority evidence reference")
            seen.add(ref["sha256"])
    _evidence_fields(row["evidence"], evidence, resolver)
    _closed(row["exposure_declaration"], EXPOSURE_FIELDS, "declared review exposure")
    for field in EXPOSURE_FIELDS[:2]:
        value = row["exposure_declaration"][field]
        _require(value is None or type(value) is bool, "Boolean or unanswered review exposure required")
    value = row["exposure_declaration"]["other_exposure"]
    if value is not None:
        _text(value, "other declared exposure", blank=True)
    return sorted(missing)


def _meaning(row):
    # Include all interpretation/context answers, excluding free notes and identity/time.
    return digest({"review": {key: value for key, value in row["review"].items()
                              if key not in ("notes", "reviewer_id", "reviewed_at_utc")},
                   "context_review": {key: value for key, value in row["context_review"].items()
                                      if key != "source_authority_or_currentness_evidence"}})


def submission_guide(packet, *, expected_packet_sha256, artifact_resolver):
    """Return detached blank submission slots, never a completed declaration."""
    packet, validation = _packet(packet, expected_packet_sha256, artifact_resolver)
    return _seal({"schema": GUIDE_SCHEMA, "submission_schema": SUBMISSION_SCHEMA,
        "packet_sha256": expected_packet_sha256, "packet_validation": validation,
        "instructions": {
            "task": "Read the selected source and complete raw section. Supply your own source/context declarations in a separate submission.",
            "null": "Null is unanswered. Empty lists and strings where allowed express a declared absence.",
            "coordinates": "Role/trigger anchors use selected-source Unicode characters; section boundary anchors use complete-section Unicode characters and the exact context artifact.",
            "agreement": "Only exact complete interpretation/context declarations agree. Agreement does not establish identity, independence or meaning.",
            "evidence": "Evidence references identify checked bytes, without authenticating a reviewer or source authority. Do not assert admission flags.",
        },
        "items": [{**_envelope(item), "review": dict.fromkeys(sources.REVIEW_FIELDS),
                   "context_review": dict.fromkeys(sources.CONTEXT_REVIEW_FIELDS),
                   "evidence": dict.fromkeys(EVIDENCE_FIELDS), "exposure_declaration": dict.fromkeys(EXPOSURE_FIELDS)}
                  for item in packet["items"]],
        "completed_declarations": 0, "admission_masks": _masks(), **_false()})


def record_reviews(packet, reviewed_submissions, *, expected_packet_sha256, artifact_resolver):
    """Record bounded caller declarations and exact agreement; admit no labels."""
    packet, validation = _packet(packet, expected_packet_sha256, artifact_resolver)
    submissions = _detach(reviewed_submissions)
    _require(type(submissions) is list and len(submissions) <= MAX_SUBMISSIONS, "bounded review submission list required")
    by_id = {item["item_id"]: item for item in packet["items"]}
    contexts = {view["artifact"]["sha256"]: view["text"] for view in packet["context_views"]}
    received = {identity: [] for identity in by_id}
    seen_ids, seen_content, reviewer_items, evidence, manifest = set(), set(), set(), {}, []
    for index, submission in enumerate(submissions):
        _closed(submission, SUBMISSION_FIELDS, "statutory review submission")
        _require(submission["schema"] == SUBMISSION_SCHEMA and submission["packet_sha256"] == expected_packet_sha256,
                 "distinct statutory submission schema and selected packet join required")
        _text(submission["submission_id"], "declared submission_id", maximum=512)
        _require(submission["submission_id"] not in seen_ids, "duplicate submission_id")
        seen_ids.add(submission["submission_id"])
        rows = submission["items"]
        _require(type(rows) is list and 1 <= len(rows) <= sources.MAX_ROWS, "bounded nonempty submitted items required")
        content = digest(submission)
        # IDs are free declarations; renaming an otherwise identical payload is not a new review.
        body_content = digest({key: value for key, value in submission.items() if key != "submission_id"})
        _require(body_content not in seen_content, "duplicate submitted declaration content")
        seen_content.add(body_content)
        seen_items = set()
        for row in rows:
            _closed(row, ITEM_FIELDS, "submitted statutory item")
            identity = row["item_id"]
            _require(type(identity) is str and identity in by_id and identity not in seen_items,
                     "unknown or duplicate submitted physical item")
            seen_items.add(identity)
            item = by_id[identity]
            _require(_wire({key: row[key] for key in ENVELOPE_FIELDS}) == _wire(_envelope(item)),
                     "immutable physical/source/context envelope changed")
            missing = _annotation(row, item, contexts, evidence, artifact_resolver)
            reviewer = row["review"]["reviewer_id"]
            if reviewer is not None:
                _require((identity, reviewer) not in reviewer_items, "duplicate declared reviewer/item pair")
                reviewer_items.add((identity, reviewer))
            complete = not missing
            received[identity].append({"submission_index": index, "submission_id": submission["submission_id"],
                "submission_sha256": content, "declaration_sha256": digest(row), "complete": complete,
                "missing_fields": missing, "meaning_signature_sha256": _meaning(row) if complete else None,
                "declaration": deepcopy(row), "reviewer_identity_authenticated": False,
                "reviewer_independence_authenticated": False})
        manifest.append({"submission_index": index, "submission_id": submission["submission_id"],
                         "submission_sha256": content, "item_count": len(rows)})
    results = []
    for identity in sorted(by_id):
        entries = received[identity]
        complete = [entry for entry in entries if entry["complete"]]
        signatures = {entry["meaning_signature_sha256"] for entry in complete}
        status, consensus = "pending" if not entries else "partial_declarations", None
        if complete:
            if len(signatures) != 1:
                status = "disputed"
            else:
                consensus = complete[0]["declaration"]["review"]["interpretation_status"]
                status = (consensus if consensus in ("needs_context", "ambiguous", "unsupported") else
                          "exact_multiple_declaration_agreement" if len(complete) >= 2 else "single_complete_declaration")
        results.append({**_envelope(by_id[identity]), "status": status,
            "consensus_declared_interpretation_status": consensus, "complete_declaration_count": len(complete),
            "partial_declaration_count": len(entries) - len(complete), "meaning_signature_count": len(signatures),
            "received_declarations": entries, "external_adjudication_status": "pending",
            "admission_masks": _masks(), **_false()})
    _close_evidence(evidence, artifact_resolver)
    closing = sources.validate_blank_packet(packet, expected_packet_sha256=expected_packet_sha256,
                                            artifact_resolver=artifact_resolver)
    _require(_wire(closing) == _wire(validation), "packet validation changed across recording")
    counts = Counter(item["status"] for item in results)
    completed = sum(item["complete_declaration_count"] for item in results)
    return _seal({"schema": SCHEMA, "status": "caller_declarations_recorded" if submissions else "pending",
        "scope": "archived_physical_source_context_declaration_integrity_only", "digest_recipe": DIGEST_RECIPE,
        "packet_sha256": expected_packet_sha256, "packet_validation": validation,
        "item_count": len(results), "submission_count": len(submissions), "submissions": manifest,
        "items": results, "status_counts": {name: counts[name] for name in ITEM_STATUSES},
        "structurally_complete_declaration_count": completed, "human_reviews_authenticated": 0,
        "independent_reviews_authenticated": 0, "qualified_training_pairs": 0,
        "evidence_artifacts": [entry["ref"] for _, entry in sorted(evidence.items())],
        "evidence_integrity_checked": bool(evidence), "evidence_contents_authenticated": False,
        "agreement_scope": "exact_complete_declared_interpretation_and_context_not_legal_correctness",
        "external_adjudication_status": "pending", "admission_masks": _masks(),
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0, **_false()})


def validate_recording(receipt, packet, reviewed_submissions, *, expected_packet_sha256, artifact_resolver):
    """Replay every closed declaration, authority flag and receipt field."""
    expected = record_reviews(packet, reviewed_submissions, expected_packet_sha256=expected_packet_sha256,
                              artifact_resolver=artifact_resolver)
    _require(_wire(receipt) == _wire(expected), "statutory recording differs from exact submission replay")
    return _seal({"schema": VALIDATION_SCHEMA, "status": "validated_caller_declaration_recording_only",
        "recording_sha256": digest(expected), "recording_body_sha256": expected["content_sha256"],
        "packet_sha256": expected_packet_sha256, "item_count": expected["item_count"],
        "submission_count": expected["submission_count"], "admission_masks": _masks(), **_false()})


def _reference(ref, entries):
    _closed(ref, {"submission_sha256", "declaration_sha256"}, "adjudicated declaration reference")
    for key in ref:
        sources._sha(ref[key], key)
    matches = [entry for entry in entries if entry["submission_sha256"] == ref["submission_sha256"]
               and entry["declaration_sha256"] == ref["declaration_sha256"]]
    _require(len(matches) == 1 and matches[0]["complete"], "known complete declaration reference required")
    return matches[0]


def record_adjudications(packet, reviewed_submissions, declaration_package, *, expected_packet_sha256, artifact_resolver):
    """Bind caller-declared adjudication to reviews; keep actual adjudication pending."""
    recording = record_reviews(packet, reviewed_submissions, expected_packet_sha256=expected_packet_sha256,
                               artifact_resolver=artifact_resolver)
    package = _detach(declaration_package)
    _closed(package, {"schema", "packet_sha256", "recording_sha256", "items"}, "statutory adjudication declaration package")
    _require(package["schema"] == ADJUDICATION_SCHEMA and package["packet_sha256"] == expected_packet_sha256
             and package["recording_sha256"] == digest(recording), "adjudication packet/recording generation mismatch")
    rows = package["items"]
    _require(type(rows) is list and len(rows) <= sources.MAX_ROWS, "bounded adjudication declaration list required")
    by_id = {item["item_id"]: item for item in recording["items"]}
    seen, evidence, results = set(), {}, []
    for row in rows:
        _closed(row, ADJUDICATION_FIELDS, "declared adjudication")
        identity = row["item_id"]
        _require(type(identity) is str and identity in by_id and identity not in seen, "unknown or duplicate adjudication item")
        seen.add(identity)
        _text(row["principal_id"], "declared adjudicator principal_id", maximum=512)
        _time(row["adjudicated_at_utc"], "adjudicated_at_utc")
        _text(row["rationale"], "adjudication rationale")
        considered = row["declaration_refs"]
        accepted = row["accepted_declaration_refs"]
        _require(type(considered) is list and 1 <= len(considered) <= MAX_SUBMISSIONS, "bounded nonempty adjudicated references required")
        _require(type(accepted) is list and len(accepted) <= MAX_SUBMISSIONS, "bounded accepted declaration references required")
        entries = [_reference(ref, by_id[identity]["received_declarations"]) for ref in considered]
        keys = {digest(ref) for ref in considered}
        _require(len(keys) == len(considered), "duplicate adjudicated declaration reference")
        accepted_entries = [_reference(ref, by_id[identity]["received_declarations"]) for ref in accepted]
        accepted_keys = {digest(ref) for ref in accepted}
        _require(len(accepted_keys) == len(accepted) and accepted_keys <= keys, "accepted declarations must be unique considered references")
        reviewers = {entry["declaration"]["review"]["reviewer_id"]
                     for entry in by_id[identity]["received_declarations"] if entry["complete"]}
        _require(row["principal_id"] not in reviewers, "declared adjudicator overlaps a recorded reviewer ID")
        _enum(row["decision"], DECISIONS, "adjudication decision")
        decision = row["decision"]
        _require((decision == "accept_unique" and len(accepted) == 1)
                 or (decision == "accept_alternatives" and len(accepted) >= 2
                     and len({entry["meaning_signature_sha256"] for entry in accepted_entries}) >= 2)
                 or (decision not in ("accept_unique", "accept_alternatives") and not accepted),
                 "adjudication decision/accepted declaration cardinality mismatch")
        _strings(row["unresolved_scope"], "unresolved adjudication scope")
        if decision in ("accept_unique", "accept_alternatives"):
            _require(not row["unresolved_scope"], "declared acceptance cannot leave unresolved scope")
        _evidence_fields(row["evidence"], evidence, artifact_resolver)
        results.append({"item_id": identity, "declaration_sha256": digest(row), "declaration": deepcopy(row),
                        "status": "caller_declared_adjudication_recorded", "external_adjudication_status": "pending",
                        "admission_masks": _masks(), **_false()})
    _close_evidence(evidence, artifact_resolver)
    closing = record_reviews(packet, reviewed_submissions, expected_packet_sha256=expected_packet_sha256,
                             artifact_resolver=artifact_resolver)
    _require(_wire(closing) == _wire(recording), "review generation changed across adjudication recording")
    return _seal({"schema": ADJUDICATION_RECORDING_SCHEMA, "packet_sha256": expected_packet_sha256,
        "recording_sha256": digest(recording), "declaration_package_sha256": digest(package),
        "declared_adjudication_count": len(results), "items": results,
        "pending_item_ids": sorted(set(by_id) - seen), "external_adjudication_status": "pending",
        "evidence_artifacts": [entry["ref"] for _, entry in sorted(evidence.items())],
        "evidence_integrity_checked": bool(evidence), "evidence_contents_authenticated": False,
        "admission_masks": _masks(), **_false()})


def validate_adjudication_recording(receipt, packet, reviewed_submissions, declaration_package, *, expected_packet_sha256, artifact_resolver):
    """Replay declared adjudication references without promoting authority."""
    expected = record_adjudications(packet, reviewed_submissions, declaration_package,
        expected_packet_sha256=expected_packet_sha256, artifact_resolver=artifact_resolver)
    _require(_wire(receipt) == _wire(expected), "adjudication recording differs from exact declaration replay")
    return _seal({"schema": ADJUDICATION_VALIDATION_SCHEMA, "adjudication_recording_sha256": digest(expected),
                  "packet_sha256": expected_packet_sha256, "admission_masks": _masks(), **_false()})


def assess_declaration_geometry(packet, reviewed_submissions, *, submission_index, item_id, expected_packet_sha256, artifact_resolver):
    """Assess one explicitly supplied complete normative declaration, separately.

    Multiple/repeated/overlapping anchors remain recorded; the old flat copied
    profile reports their representability limitations without changing review,
    modality, source spans, target assignment or any supervision mask.
    """
    recording = record_reviews(packet, reviewed_submissions, expected_packet_sha256=expected_packet_sha256,
                               artifact_resolver=artifact_resolver)
    sources._integer(submission_index, "submitted geometry submission_index")
    _text(item_id, "submitted geometry item_id", maximum=512)
    entries = [entry for item in recording["items"] if item["item_id"] == item_id
               for entry in item["received_declarations"] if entry["submission_index"] == submission_index]
    _require(len(entries) == 1 and entries[0]["complete"], "one known complete declaration required for geometry")
    row = entries[0]["declaration"]
    review = row["review"]
    _require(review["interpretation_status"] == "normative", "explicit normative declaration required for geometry")
    evidence = row["evidence"]["review_process_evidence"]
    _require(evidence is not None, "explicit review-process evidence artifact required for geometry")
    rules = []
    for index, declared in enumerate(review["normative_rules"]):
        rules.append({"modality": declared["modality"], **{facet: [
            {key: anchor[key] for key in TRIGGER_FIELDS} for anchor in review["source_role_anchors"]
            if anchor["rule_index"] == index and anchor["facet"] == facet] for facet in sources.SPAN_FIELDS}})
    proposal = {"item_id": item_id, "packet_sha256": expected_packet_sha256,
        "review_declaration": {"status": "caller_declared_source_context_reviewed_proposal",
            "reviewer_id": review["reviewer_id"], "reviewed_at_utc": review["reviewed_at_utc"],
            "evidence_artifact": evidence, "source_text_sha256": row["source_text_sha256"],
            "context_artifact_sha256": row["context_artifact"]["sha256"]},
        "interpretation_status": "normative", "rules": rules}
    return sources.assess_representability(packet, [proposal], expected_packet_sha256=expected_packet_sha256,
                                           artifact_resolver=artifact_resolver)


__all__ = ["digest", "parse_json_bytes", "submission_guide", "record_reviews", "validate_recording",
           "record_adjudications", "validate_adjudication_recording", "assess_declaration_geometry"]
