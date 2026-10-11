"""Diagnose caller-declared statutory consistency without admitting targets.

The unchanged recorder owns physical/source/context joins and declaration
storage. This separate boundary replays it before examining declarations,
preserves their order and contents, and reports only mechanical contradictions
or unresolved answers. Consistency, agreement and declared interval roles do
not establish source meaning, reviewer identity or training eligibility.

No alias, connective, modality cue, reference resolution or formal target is
inferred. Lossless statement-scope transport has a separate existing owner;
this preflight neither synthesizes that schema nor lowers its declarations.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from . import statutory_review_recording as recorder
from . import statutory_source_review as sources

SCHEMA = "statutory-declaration-consistency-preflight/v1"
VALIDATION_SCHEMA = "statutory-declaration-consistency-preflight-validation/v1"
STATUSES = ("partial", "non_normative", "unresolved", "inconsistent", "consistent_declared_normative")
MAX_DIAGNOSTICS_PER_DECLARATION = 1024
MAX_DIAGNOSTICS = 4096
MAX_JSON_BYTES = sources.MAX_JSON_BYTES
DIGEST_RECIPE = sources.DIGEST_RECIPE


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    # The source-only owner bounds bytes, depth and nodes and rejects all
    # floating scores, nonfinite values and nonordinary Python objects.
    return sources._wire(value)


def digest(value):
    """Complete canonical content digest, distinct from a file-byte digest."""
    return recorder.digest(value)


def parse_json_bytes(raw):
    """Read bounded strict ordinary UTF8 JSON, refusing duplicate keys."""
    return recorder.parse_json_bytes(raw)


def _detach(value):
    return parse_json_bytes(_wire(value))


def _false():
    return {**recorder._false(), "target_eligibility": False,
            "declared_consistency_is_legal_correctness": False,
            "symbolic_aliases_inferred": False, "cross_references_resolved": False,
            "Boolean_scope_inferred": False, "modality_cues_inferred": False,
            "statement_scope_synthesized": False, "scope_transport_assessed": False,
            "legacy_copied_span_geometry_assessed": False, "formal_output_lowered": False}


def _masks():
    return sources._masks()


def _seal(value):
    return {**value, "content_sha256": digest(value)}


def _overlap(left, right):
    return max(left[0], right[0]) < min(left[1], right[1])


def _declaration(entry, item):
    original = entry["declaration"]
    review, context = original["review"], original["context_review"]
    issues = []

    def issue(code, field_path, category, related_paths=()):
        _require(len(issues) < MAX_DIAGNOSTICS_PER_DECLARATION,
                 "declaration preflight diagnostic budget exceeded; no truncation")
        issues.append({"code": code, "field_path": field_path, "category": category,
                       "related_paths": list(related_paths)})

    rules = review["normative_rules"]
    normative = review["interpretation_status"] == "normative"
    eligibility = review["normative_eligibility"]
    if normative and eligibility == "not_normative":
        issue("normative_interpretation_with_not_normative_eligibility",
              "/review/normative_eligibility", "inconsistency", ("/review/interpretation_status",))
    if review["interpretation_status"] == "no_normative_rule" and eligibility == "eligible_normative":
        issue("no_normative_rule_with_eligible_normative_declaration",
              "/review/normative_eligibility", "inconsistency", ("/review/interpretation_status",))
    if review["definition_status"] == "definition_only" and rules:
        issue("definition_only_with_normative_rules", "/review/definition_status", "inconsistency",
              ("/review/normative_rules",))
    if review["definition_status"] == "mixed_definition_and_norm" and rules == []:
        issue("mixed_definition_and_norm_with_explicitly_absent_rules", "/review/definition_status",
              "inconsistency", ("/review/normative_rules",))
    if rules is not None:
        if review["multi_rule_status"] == "no_rule" and rules:
            issue("no_rule_with_declared_rules", "/review/multi_rule_status", "inconsistency")
        if not normative and review["interpretation_status"] is not None and rules:
            issue("non_normative_interpretation_with_rules", "/review/normative_rules", "inconsistency")
    for field in ("normative_eligibility", "interpretation_status"):
        if review[field] in ("needs_context", "ambiguous", "unsupported"):
            issue("declared_" + review[field], "/review/" + field, "unresolved")
    if normative:
        if review["definition_status"] == "undetermined":
            issue("definition_status_undetermined", "/review/definition_status", "unresolved")
        if review["multi_rule_status"] == "undetermined":
            issue("rule_cardinality_undetermined", "/review/multi_rule_status", "unresolved")
        for field in ("ambiguity", "unsupported_meaning"):
            if review[field]:
                issue("declared_" + field + "_remains", "/review/" + field, "unresolved")
        if context["context_sufficiency"] in ("needs_external_context", "undetermined"):
            issue("declared_context_not_sufficient", "/context_review/context_sufficiency", "unresolved")
        if context["unresolved_dependencies"]:
            issue("declared_unresolved_dependencies", "/context_review/unresolved_dependencies", "unresolved")

    anchors = review["source_role_anchors"]
    attachments = review["qualifier_attachments"]
    source = item["input"]["source_text"]
    shift = item["context"]["selected_char_start"]
    boundaries = context["operative_versus_editorial_boundaries"]
    boundaries = boundaries if boundaries is not None else []
    translated = []
    for index, anchor in enumerate(anchors or []):
        # Recorder replay established the literal selected-source join and
        # the full-section selector. Translation changes only the coordinates.
        selected = [anchor["char_start"], anchor["char_end"]]
        absolute = [shift + selected[0], shift + selected[1]]
        _require(source[selected[0]:selected[1]] == anchor["text"], "replayed source anchor differs")
        matches = [i for i, boundary in enumerate(boundaries)
                   if _overlap(absolute, [boundary["char_start"], boundary["char_end"]])]
        translated.append({"anchor_id": anchor["anchor_id"], "rule_index": anchor["rule_index"],
                           "facet": anchor["facet"], "text": anchor["text"],
                           "selected_source_char_interval": selected,
                           "complete_context_char_interval": absolute,
                           "overlapping_declared_boundary_indices": matches})
        kinds = {boundaries[i]["kind"] for i in matches}
        if "editorial" in kinds:
            issue("source_anchor_overlaps_declared_editorial_interval",
                  f"/review/source_role_anchors/{index}", "declared_interval",
                  (f"/context_review/operative_versus_editorial_boundaries/{i}" for i in matches
                   if boundaries[i]["kind"] == "editorial"))
        if "undetermined" in kinds:
            issue("source_anchor_overlaps_declared_undetermined_interval",
                  f"/review/source_role_anchors/{index}", "declared_interval")
        if rules is not None:
            rule = rules[anchor["rule_index"]]
            facet = anchor["facet"]
            if facet in ("object", *recorder.QUALIFIERS) and not rule[facet]:
                issue("source_anchor_on_declared_absent_facet", f"/review/source_role_anchors/{index}",
                      "inconsistency", (f"/review/normative_rules/{anchor['rule_index']}/{facet}",))
    # Contrary role intervals remain the caller's declarations. Their overlap
    # is a geometry diagnostic, never a prohibition inferred from source law.
    for left, boundary in enumerate(boundaries):
        for right in range(left + 1, len(boundaries)):
            other = boundaries[right]
            if {boundary["kind"], other["kind"]} == {"operative", "editorial"} and _overlap(
                    [boundary["char_start"], boundary["char_end"]],
                    [other["char_start"], other["char_end"]]):
                issue("contrary_declared_operative_editorial_intervals_overlap",
                      f"/context_review/operative_versus_editorial_boundaries/{left}", "declared_interval",
                      (f"/context_review/operative_versus_editorial_boundaries/{right}",))
    for index, attachment in enumerate(attachments or []):
        if attachment["rule_index"] not in attachment["affected_rule_indices"]:
            issue("attachment_owner_rule_not_in_affected_rules", f"/review/qualifier_attachments/{index}",
                  "inconsistency")
        if attachment["scope_kind"] == "undetermined":
            issue("qualifier_attachment_scope_undetermined", f"/review/qualifier_attachments/{index}",
                  "unresolved")

    # Missing anchors describe incomplete source-role coverage, not an alias
    # error. Literal and symbolic strings are deliberately never compared.
    anchor_counts = []
    for index, rule in enumerate(rules or []):
        counts = {facet: sum(anchor["rule_index"] == index and anchor["facet"] == facet
                             for anchor in anchors or []) for facet in sources.SPAN_FIELDS}
        anchor_counts.append({"rule_index": index, "facet_anchor_counts": counts,
                              "qualifier_occurrence_counts": {facet: len(rule[facet]) for facet in recorder.QUALIFIERS}})
        if normative and anchors is not None:
            for facet in sources.SPAN_FIELDS:
                if rule[facet] and counts[facet] == 0:
                    issue("declared_facet_without_source_role_anchor",
                          f"/review/normative_rules/{index}/{facet}", "unresolved")

    if not entry["complete"]:
        status = "partial"
    elif any(row["category"] == "inconsistency" for row in issues):
        status = "inconsistent"
    elif any(row["category"] == "unresolved" for row in issues):
        status = "unresolved"
    elif normative:
        status = "consistent_declared_normative"
    else:
        status = "non_normative"
    return {**{field: deepcopy(entry[field]) for field in
               ("submission_index", "submission_id", "submission_sha256", "declaration_sha256",
                "complete", "missing_fields", "meaning_signature_sha256")},
            "status": status, "declared_normative_eligibility": eligibility,
            "declaration": deepcopy(original), "diagnostics": issues,
            "translated_source_role_anchors": translated, "declared_rule_shape": anchor_counts,
            "interval_diagnostic_scope": "only_explicit_caller_declared_roles_and_exact_character_selectors",
            "admission_masks": _masks(), **_false()}


def preflight_declarations(packet, reviewed_submissions, *, expected_packet_sha256, artifact_resolver, recording=None):
    """Replay all declarations and diagnose consistency; create no targets.

    A supplied recording is replay-validated before any field is used. Partial,
    disputed and non-normative declarations are retained. The input is ordinary
    score-free bounded JSON; file callers should use ``parse_json_bytes``.
    """
    packet = _detach(packet)
    submissions = _detach(reviewed_submissions)
    options = {"expected_packet_sha256": expected_packet_sha256, "artifact_resolver": artifact_resolver}
    if recording is None:
        recording = recorder.record_reviews(packet, submissions, **options)
    else:
        recording = _detach(recording)
    validation = recorder.validate_recording(recording, packet, submissions, **options)
    recorded = {item["item_id"]: item for item in recording["items"]}
    results, status_counts, diagnostic_count = [], Counter(), 0
    for item in packet["items"]:
        received = recorded[item["item_id"]]
        declarations = [_declaration(entry, item) for entry in received["received_declarations"]]
        counts = Counter(row["status"] for row in declarations)
        status_counts.update(counts)
        diagnostic_count += sum(len(row["diagnostics"]) for row in declarations)
        _require(diagnostic_count <= MAX_DIAGNOSTICS, "preflight total diagnostic budget exceeded; no truncation")
        results.append({**recorder._envelope(item), "source_input": deepcopy(item["input"]),
                        "recording_status": received["status"],
                        "declared_dispute_present": received["status"] == "disputed",
                        "received_declarations": declarations, "declaration_count": len(declarations),
                        "status_counts": {status: counts[status] for status in STATUSES},
                        "admission_masks": _masks(), **_false()})
    closing = recorder.validate_recording(recording, packet, submissions, **options)
    _require(_wire(closing) == _wire(validation), "recording/source closure changed across preflight")
    return _seal({"schema": SCHEMA, "status": "pending" if not submissions else "declarations_preflighted_only",
                  "scope": "caller_declared_consistency_and_interval_geometry_only",
                  "digest_recipe": DIGEST_RECIPE, "packet_sha256": expected_packet_sha256,
                  "recording_sha256": digest(recording), "submissions_sha256": digest(submissions),
                  "recording_validation": validation, "item_count": len(results),
                  "submission_count": len(submissions), "declaration_count": sum(status_counts.values()),
                  "status_counts": {status: status_counts[status] for status in STATUSES},
                  "declared_disputed_item_count": sum(item["declared_dispute_present"] for item in results),
                  "diagnostic_count": diagnostic_count, "items": results,
                  "human_reviews_authenticated": 0, "independent_reviews_authenticated": 0,
                  "qualified_training_pairs": 0, "gold_labels_created": 0, "formal_targets_created": 0,
                  "statement_scope_owner": "ipfs_datasets_py.logic.legal_ir.canonical_statement_scope",
                  "statement_scope_integration": "deferred_requires_explicit_caller_declaration_and_exact_profile_joins",
                  "consistent_status_meaning": "mechanical_declaration_consistency_not_meaning_completeness_or_eligibility",
                  "admission_masks": _masks(), "model_calls": 0, "encoder_calls": 0,
                  "provider_calls": 0, "prover_calls": 0, **_false()})


def validate_preflight(receipt, packet, reviewed_submissions, *, expected_packet_sha256, artifact_resolver, recording=None):
    """Rebuild all closed diagnostics and refuse receipt or authority tampering."""
    supplied = _detach(receipt)
    expected = preflight_declarations(packet, reviewed_submissions, expected_packet_sha256=expected_packet_sha256,
                                      artifact_resolver=artifact_resolver, recording=recording)
    _require(_wire(supplied) == _wire(expected), "preflight differs from exact declaration replay")
    return _seal({"schema": VALIDATION_SCHEMA, "status": "validated_declared_preflight_only",
                  "packet_sha256": expected_packet_sha256, "preflight_sha256": digest(expected),
                  "declaration_count": expected["declaration_count"], "admission_masks": _masks(), **_false()})


__all__ = ["digest", "parse_json_bytes", "preflight_declarations", "validate_preflight"]
