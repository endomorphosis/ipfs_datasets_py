"""Distinct contextual declarations beside an explicit sampled V2 definition.

The original binding, compiler and corpus adapter keep ownership of the
candidate. Context review owns complete source replay and declaration checks.
This companion joins exact references without interpreting prose, changing an
AST, authenticating a reviewer or giving supporting citations review credit.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import legal_source_sampling_definition_binding_v2 as base

SCHEMA = "legal-source-sampling-context-definition-binding/v2"
BINDING_SCHEMA = "legal-source-sampling-context-definition-binding-metadata/v1"
PROFILE = "explicit-definition-with-distinct-contextual-declarations/v1"
MAX_CONTEXT_BYTES = 96 * 1024 * 1024
MAX_SOURCE_INPUT_BYTES = 96 * 1024 * 1024
MAX_RESPONSE_POPULATION_BYTES = 96 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_SOURCES = 4
MAX_SUBJECTS = 8192
MAX_ATTACHMENTS = 128
MAX_RESPONSES = 256
_CONTEXT_LIMITS = {
    "max_sources": MAX_SOURCES, "max_attachments": MAX_ATTACHMENTS,
    "max_subjects": MAX_SUBJECTS, "max_bundle_bytes": base.MAX_BUNDLE_BYTES,
    "max_input_bytes": MAX_SOURCE_INPUT_BYTES, "max_packet_bytes": MAX_CONTEXT_BYTES,
    "max_responses": MAX_RESPONSES, "max_response_bytes": base.MAX_RESPONSE_BYTES,
    "max_response_input_bytes": MAX_RESPONSE_POPULATION_BYTES,
    "max_population_bytes": base.MAX_RECORD_BYTES,
}
_PACKET_FIELDS = {
    "schema", "limits", "sources", "attachments", "attachments_sha256",
    "counts", "status", "authority", "training_mask", "evaluation_gold_mask",
}
_RESPONSE_FIELDS = {
    "schema", "context_sha256", "declaration_sha256", "declaration", "status",
    "authority", "training_mask", "evaluation_gold_mask", "record_cid", "cid_scope",
}
_ATTACHMENT_FIELDS = {
    "target_bundle_sha256", "target_subject_ref", "supporting_bundle_sha256",
    "supporting_subject_ref", "role",
}
_SELF_PIN = base._digest_raw(Path(__file__).read_bytes())
_OPERATION_PINS = None


def _keys(value, fields, label):
    base._need(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _subject(value):
    _keys(value, {"kind", "index", "sha256"}, "contextual subject")
    base._need(
        type(value["kind"]) is str and value["kind"] in ("unit", "withheld_context")
        and type(value["index"]) is int and value["index"] >= 0,
        "typed contextual subject kind/index required",
    )
    base._sha(value["sha256"], "contextual subject")


def _snapshot(value, maximum, pin, label):
    base._sha(pin, label)
    raw = base._wire(value, maximum)
    base._need(base._digest_raw(raw) == pin, "independent " + label + " pin differs")
    return json.loads(raw), len(raw)


def _preflight(
    request_raw, context, responses, sources, attachments, *,
    expected_request_sha256, expected_definition_bundle_sha256,
    expected_context_sha256, expected_response_sha256s, expected_attachments_sha256,
):
    """Finish transport/type/population bounds before importing operation owners."""
    base._parse_request(request_raw, expected_request_sha256)
    base._sha(expected_definition_bundle_sha256, "definition source bundle")
    _keys(context, _PACKET_FIELDS, "complete context packet")
    packet, _ = _snapshot(context, MAX_CONTEXT_BYTES, expected_context_sha256, "complete context")
    base._need(packet["schema"] == "legal-source-sampling-review-context/v1", "distinct context packet required")
    _keys(packet["limits"], set(_CONTEXT_LIMITS), "complete context limits")
    base._need(all(type(v) is int and 0 < v <= _CONTEXT_LIMITS[k] for k, v in packet["limits"].items()), "positive lowered typed context limits required")
    base._need(type(sources) is list and 2 <= len(sources) <= MAX_SOURCES, "bounded complete context sources required")
    detached_sources, used, subjects = [], 0, 0
    for entry in sources:
        _keys(entry, {"bundle", "raw", "expected_bundle_sha256", "replay_inputs"}, "context source")
        bundle, size = _snapshot(entry["bundle"], base.MAX_BUNDLE_BYTES, entry["expected_bundle_sha256"], "context source bundle")
        _keys(bundle, {"schema", "limits", "manifest", "sampling_report", "question_catalog", "guides"}, "complete source bundle")
        base._need(bundle["schema"] == "legal-source-sampling-review-bundle/v1" and type(bundle["guides"]) is list, "original complete review bundle required")
        subjects += len(bundle["guides"])
        base._need(subjects <= MAX_SUBJECTS, "complete contextual subject bound exceeded")
        replay = entry["replay_inputs"]
        base._need(type(replay) is dict and base._INPUT_FIELDS <= set(replay) <= base._INPUT_FIELDS | base._OPTIONAL_INPUT_FIELDS, "closed context replay inputs required")
        replay_raw = base._wire(replay, base.MAX_RECORD_BYTES)
        replay = json.loads(replay_raw)
        for key in ("expected_sampling_report_sha256", "expected_descriptor_sha256", "expected_raw_sha256"):
            base._sha(replay[key], key)
        base._need(base._digest(bundle["sampling_report"], base.MAX_SAMPLING_BYTES) == replay["expected_sampling_report_sha256"], "independent complete context sampling report pin differs")
        base._need(base._digest(replay["descriptor"]) == replay["expected_descriptor_sha256"], "independent context descriptor pin differs")
        raw, count = entry["raw"], replay["expected_raw_bytes"]
        base._need(type(count) is int and 0 < count <= base.MAX_RAW_BYTES, "bounded context raw count required")
        base._need(raw is None or type(raw) is bytes and len(raw) == count and base._digest_raw(raw) == replay["expected_raw_sha256"], "independent immutable context raw bytes or explicit missing source required")
        used += size + len(replay_raw) + (0 if raw is None else len(raw))
        base._need(used <= MAX_SOURCE_INPUT_BYTES, "complete context source byte bound exceeded before replay")
        detached_sources.append(dict(bundle=bundle, raw=raw, expected_bundle_sha256=entry["expected_bundle_sha256"], replay_inputs=replay))
    source_pins = [entry["expected_bundle_sha256"] for entry in detached_sources]
    base._need(len(set(source_pins)) == len(source_pins), "duplicate context source bundles forbidden")
    base._need(expected_definition_bundle_sha256 in source_pins, "exact independently pinned definition bundle must be in the context")
    base._need(type(attachments) is list and 0 < len(attachments) <= MAX_ATTACHMENTS, "bounded nonempty context attachments required")
    nominations, size = _snapshot(attachments, MAX_SOURCE_INPUT_BYTES - used, expected_attachments_sha256, "ordered context attachments")
    for row in nominations:
        _keys(row, _ATTACHMENT_FIELDS, "context attachment")
        for side in ("target", "supporting"):
            base._sha(row[side + "_bundle_sha256"], "attachment source bundle")
            _subject(row[side + "_subject_ref"])
        base._need(type(row["role"]) is str and 0 < len(row["role"]) <= 128, "bounded explicit nomination role required")
    base._need(type(responses) is list and len(responses) <= MAX_RESPONSES and type(expected_response_sha256s) is list and len(expected_response_sha256s) == len(responses), "one ordered independent pin per bounded context response required")
    detached_responses, used = [], 0
    for row, pin in zip(responses, expected_response_sha256s, strict=True):
        _keys(row, _RESPONSE_FIELDS, "distinct context response")
        value, size = _snapshot(row, base.MAX_RESPONSE_BYTES, pin, "context response")
        base._need(value["schema"] == "legal-source-sampling-context-declaration/v1", "distinct context response schema required, no v1 conversion")
        base._need(value["context_sha256"] == expected_context_sha256, "context response binds another complete context")
        base._need(type(value["declaration"]) is dict, "explicit contextual declaration required")
        base._sha(value["declaration_sha256"], "contextual declaration")
        base._need(base._digest(value["declaration"]) == value["declaration_sha256"], "independent original contextual declaration pin differs")
        used += size
        base._need(used <= MAX_RESPONSE_POPULATION_BYTES, "complete contextual response byte bound exceeded before replay")
        detached_responses.append(value)
    base._need(len(set(expected_response_sha256s)) == len(detached_responses), "duplicate exact contextual responses forbidden")
    return packet, detached_responses, detached_sources, nominations


def _owners():
    from . import legal_source_sampling_review_context as context_owner

    return base._owners(), context_owner


def _pins(owners):
    global _OPERATION_PINS
    base_owners, context_owner = owners
    result = dict(base._pins(base_owners))
    own_path = Path(__file__).resolve()
    base._need(base._digest_raw(own_path.read_bytes()) == _SELF_PIN, "contextual definition binding source changed since import")
    result[str(own_path)] = _SELF_PIN
    path = Path(context_owner.__file__).resolve()
    result[str(path)] = base._digest_raw(path.read_bytes())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(result)
    base._need(result == _OPERATION_PINS, "contextual definition operation owners changed since first use")
    return result


def _required_and_related(candidate, population, responses, packet, definition_pin):
    required = candidate["binding"]["required_subjects"]
    required_by_key = {base._subject_key(row["subject_ref"]): row for row in required}
    population_by_key = {
        (row["bundle_sha256"], base._subject_key(row["subject_ref"])): row
        for row in population["subjects"]
    }
    support_nominations, linked_attachments = [], []
    for attached in packet["attachments"]:
        nomination = attached["nomination"]
        support_key = base._subject_key(nomination["supporting_subject_ref"])
        if nomination["supporting_bundle_sha256"] == definition_pin and support_key in required_by_key:
            support_nominations.append(dict(
                nomination_sha256=attached["nomination_sha256"], nomination=nomination,
                required_definition_roles=required_by_key[support_key]["roles"],
                available_attached_evidence_sha256s=[base._digest(e) for e in attached["evidence_refs"]],
                available_attached_evidence_count=len(attached["evidence_refs"]),
                applicability_verified=False, direct_definition_review_credit=False,
            ))
            linked_attachments.append(attached)
    bound_required = []
    for row in required:
        observed = population_by_key[(definition_pin, base._subject_key(row["subject_ref"]))]
        base._need(base._wire(row["guide_ref"], base.MAX_RECORD_BYTES) == base._wire(observed["guide_ref"], base.MAX_RECORD_BYTES), "exact contextual definition guide identity required")
        bound_required.append(dict(
            bundle_sha256=definition_pin, subject_ref=row["subject_ref"], guide_ref=row["guide_ref"],
            roles=row["roles"], direct_response_refs=observed["response_refs"],
            supporting_nomination_sha256s=[n["nomination_sha256"] for n in support_nominations if base._subject_key(n["nomination"]["supporting_subject_ref"]) == base._subject_key(row["subject_ref"])],
            state=observed["state"], reasons=observed["reasons"],
        ))
    direct, related = [], []
    for response in responses:
        declaration = response["declaration"]
        subject = declaration["subject_ref"]
        target_pin = declaration["bundle_sha256"]
        ref = base._record_ref(response)
        if target_pin == definition_pin and base._subject_key(subject) in required_by_key:
            direct.append(ref)
            continue
        citations = {
            base._digest(evidence): evidence
            for field in ("source_answers", "meaning_proposals")
            for answer in declaration[field]
            for evidence in answer["evidence_refs"]
        }
        links = []
        for attached in linked_attachments:
            nomination = attached["nomination"]
            support_key = base._subject_key(nomination["supporting_subject_ref"])
            if not (
                nomination["target_bundle_sha256"] == target_pin
                and base._subject_key(nomination["target_subject_ref"]) == base._subject_key(subject)
            ):
                continue
            cited = [evidence for evidence in attached["evidence_refs"] if base._digest(evidence) in citations]
            links.append(dict(
                nomination_sha256=attached["nomination_sha256"], nomination=nomination,
                required_definition_roles=required_by_key[support_key]["roles"],
                cited_evidence_refs=cited, cited_evidence_count=len(cited),
            ))
        base._need(bool(links) and any(link["cited_evidence_refs"] for link in links), "related response must cite exact attached evidence supporting a required definition subject")
        row = population_by_key[(target_pin, base._subject_key(subject))]
        related.append(dict(
            response_ref=ref, bundle_sha256=target_pin, subject_ref=subject,
            required_support_links=links,
            target_population_state=row["state"], target_population_reasons=row["reasons"],
            direct_definition_review_credit=False,
        ))
    return bound_required, support_nominations, direct, related


def prepare(
    request_raw, context, responses, sources, attachments, *,
    expected_request_sha256, expected_definition_bundle_sha256,
    expected_context_sha256, expected_response_sha256s, expected_attachments_sha256,
):
    packet, offered_responses, source_inputs, nominations = _preflight(
        request_raw, context, responses, sources, attachments,
        expected_request_sha256=expected_request_sha256,
        expected_definition_bundle_sha256=expected_definition_bundle_sha256,
        expected_context_sha256=expected_context_sha256,
        expected_response_sha256s=expected_response_sha256s,
        expected_attachments_sha256=expected_attachments_sha256,
    )
    owners = _owners()
    pins = _pins(owners)
    review, _, _, contracts, _ = owners[0]
    population = review.summarize_sampling_review_context_population(
        packet, offered_responses, source_inputs, nominations,
        expected_context_sha256=expected_context_sha256,
        expected_response_sha256s=expected_response_sha256s,
        expected_attachments_sha256=expected_attachments_sha256,
    )
    # The summarizer regenerates the whole pinned packet with canonical-byte
    # equality. Select the source only after that full authoritative replay.
    matches = [s for s in packet["sources"] if s["bundle_sha256"] == expected_definition_bundle_sha256]
    raw_matches = [s for s in source_inputs if s["expected_bundle_sha256"] == expected_definition_bundle_sha256]
    base._need(len(matches) == len(raw_matches) == 1, "one exact replayed definition source required")
    definition_source, definition_raw = matches[0], raw_matches[0]["raw"]
    candidate = base.prepare_definition_binding_v2(
        request_raw, definition_source["bundle"], [], definition_raw,
        expected_request_sha256=expected_request_sha256,
        expected_bundle_sha256=expected_definition_bundle_sha256,
        expected_response_sha256s=[], **definition_source["replay_inputs"],
    )
    required, support_nominations, direct, related = _required_and_related(candidate, population, offered_responses, packet, expected_definition_bundle_sha256)
    states = {row["state"] for row in required}
    status = next((state for state in ("disputed", "unsupported", "pending") if state in states), "declarations_recorded")
    metadata = contracts.seal_record(dict(
        schema=BINDING_SCHEMA, profile=PROFILE, view="candidate", status=status,
        input_pins=dict(
            request_sha256=expected_request_sha256,
            definition_bundle_full_canonical_sha256=expected_definition_bundle_sha256,
            context_full_canonical_sha256=expected_context_sha256,
            attachments_full_canonical_sha256=expected_attachments_sha256,
            response_full_canonical_sha256s=list(expected_response_sha256s),
        ),
        base_binding_sha256=base.definition_binding_sha256(candidate),
        base_binding_response_scope="empty_v1_response_population_only",
        contextual_population_ref=base._record_ref(population),
        context_counts=packet["counts"], source_identity=candidate["binding"]["source_identity"],
        required_subjects=required, required_subject_count=len(required),
        required_support_nominations=support_nominations,
        required_support_nomination_count=len(support_nominations),
        direct_response_refs=direct, direct_response_count=len(direct),
        related_target_responses=related, related_target_response_count=len(related),
        response_count=len(offered_responses),
        all_required_subjects_have_direct_declarations=all(row["direct_response_refs"] for row in required),
        contextual_population_complete=True, external_complete_context_required=True,
        context_packet_embedded=False, response_payloads_embedded=False,
        related_declarations_close_definition_review=False,
        declaration_prose_interpreted=False, caller_ast_rewritten=False,
        interpretation_status="unreviewed_caller_declaration",
        producer_pins=pins, authority=dict(base.FALSE_FLAGS), training_mask=0, evaluation_gold_mask=0,
    ))
    base._wire(metadata, base.MAX_RECORD_BYTES)
    base._wire(population, base.MAX_RECORD_BYTES)
    base._need(_pins(owners) == pins, "contextual definition producers changed during preparation")
    return json.loads(base._wire(dict(
        schema=SCHEMA, base_binding=candidate, contextual_binding=metadata,
        contextual_population=population,
    ), MAX_OUTPUT_BYTES))


def binding_sha256(result):
    _keys(result, {"schema", "base_binding", "contextual_binding", "contextual_population"}, "complete contextual definition envelope")
    base._need(result["schema"] == SCHEMA, "distinct contextual definition binding schema required")
    base.definition_binding_sha256(result["base_binding"])
    for key in ("contextual_binding", "contextual_population"):
        base._wire(result[key], base.MAX_RECORD_BYTES)
    return base._digest(result, MAX_OUTPUT_BYTES)


def validate(
    result, request_raw, context, responses, sources, attachments, *,
    expected_binding_sha256, expected_request_sha256,
    expected_definition_bundle_sha256, expected_context_sha256,
    expected_response_sha256s, expected_attachments_sha256,
):
    base._sha(expected_binding_sha256, "complete contextual definition binding")
    base._need(binding_sha256(result) == expected_binding_sha256, "independent complete contextual definition binding pin differs")
    offered = base._wire(result, MAX_OUTPUT_BYTES)
    expected = prepare(
        request_raw, context, responses, sources, attachments,
        expected_request_sha256=expected_request_sha256,
        expected_definition_bundle_sha256=expected_definition_bundle_sha256,
        expected_context_sha256=expected_context_sha256,
        expected_response_sha256s=expected_response_sha256s,
        expected_attachments_sha256=expected_attachments_sha256,
    )
    base._need(offered == base._wire(expected, MAX_OUTPUT_BYTES), "contextual definition binding differs from complete authoritative regeneration")
    return expected
