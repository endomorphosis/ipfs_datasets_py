"""Unsigned contextual source declarations beside an unchanged review subject.

The existing contextual binding and single-source review-correspondence owners
perform their complete replay. This companion preserves their distinct domains;
it neither interprets declarations nor extends what the original subject signs.
Full context and response payloads remain external required replay inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import legal_source_sampling_definition_review_v2 as base
from . import legal_source_sampling_context_definition_binding_v2 as context_binding


SCHEMA = "legal-source-sampling-context-definition-review-correspondence/v1"
METADATA_SCHEMA = "legal-source-sampling-context-definition-review-metadata/v1"
PROFILE = "unsigned-contextual-source-review-subject-link/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 4 * MAX_RECORD_BYTES
MAX_INPUT_BYTES = 384 * MAX_RECORD_BYTES
_REPLAY_FIELDS = {
    "request_raw", "context", "responses", "sources", "attachments",
    "expected_request_sha256", "expected_definition_bundle_sha256",
    "expected_context_sha256", "expected_response_sha256s",
    "expected_attachments_sha256",
}
_PIN_FIELDS = {
    "expected_request_sha256", "expected_definition_bundle_sha256",
    "expected_context_sha256", "expected_response_sha256s",
    "expected_attachments_sha256",
}
_BINDING_FIELDS = {
    "schema", "base_binding", "contextual_binding", "contextual_population",
}
_OUTPUT_FIELDS = {"schema", "definition_correspondence", "contextual_correspondence"}
_SELF_PATH = Path(__file__).resolve()
_OPERATION_PINS = None


def _pure_pins():
    modules = (base, context_binding, context_binding.base)
    paths = [_SELF_PATH, *(Path(module.__file__).resolve() for module in modules)]
    return {str(path): base._raw_sha(path.read_bytes()) for path in paths}


_IMPORTED_PURE_PINS = _pure_pins()


def _footprint(value):
    """Charge detached JSON syntax plus original byte bodies, without encoding bytes."""
    remaining = MAX_INPUT_BYTES

    def visit(item):
        nonlocal remaining
        if type(item) is bytes:
            remaining -= len(item)
        elif type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                visit(key)
                visit(child)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child)
        else:
            remaining -= len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        base._need(remaining >= 0, "complete contextual correspondence input budget exceeded")

    visit(value)


def _preflight(
    binding_result, review_subject, *, expected_binding_sha256,
    expected_subject_sha256, contextual_replay_inputs, candidate_inputs,
    expected_candidate_pin, context_inputs, expected_context_population,
    dependency_manifest, expected_manifest_sha256, required_dependency_ids,
):
    """Bound and detach every original input before any operation owner loads."""
    base._need(_pure_pins() == _IMPORTED_PURE_PINS, "contextual correspondence pure owners changed since import")
    base._sha(expected_binding_sha256, "complete contextual definition binding")
    base._keys(binding_result, _BINDING_FIELDS, "complete contextual definition binding")
    raw_binding = base._wire(binding_result, MAX_OUTPUT_BYTES)
    base._need(base._raw_sha(raw_binding) == expected_binding_sha256,
               "independent complete contextual binding pin differs")
    offered = json.loads(raw_binding)
    base._need(offered["schema"] == context_binding.SCHEMA,
               "distinct contextual definition binding required")
    base._wire(review_subject, MAX_RECORD_BYTES, review_json=True)
    for field in ("contextual_binding", "contextual_population"):
        base._wire(offered[field], MAX_RECORD_BYTES)
    base._keys(contextual_replay_inputs, _REPLAY_FIELDS, "contextual binding replay inputs")
    args = contextual_replay_inputs
    packet, responses, sources, attachments = context_binding._preflight(**args)
    replay = {
        "request_raw": args["request_raw"], "context": packet,
        "responses": responses, "sources": sources, "attachments": attachments,
        **{key: list(args[key]) if key == "expected_response_sha256s" else args[key]
           for key in _PIN_FIELDS},
    }
    source_matches = [entry for entry in sources
                      if entry["expected_bundle_sha256"] == replay["expected_definition_bundle_sha256"]]
    base._need(len(source_matches) == 1, "one exact definition source replay required")
    source = source_matches[0]
    base_replay = {
        "request_raw": replay["request_raw"], "bundle": source["bundle"],
        "responses": [], "raw_html": source["raw"],
        "expected_request_sha256": replay["expected_request_sha256"],
        "expected_bundle_sha256": source["expected_bundle_sha256"],
        "expected_response_sha256s": [], "sampling_replay_inputs": source["replay_inputs"],
    }
    base_pin = base._digest(offered["base_binding"], base.MAX_BINDING_BYTES)
    originals = base._preflight(
        offered["base_binding"], review_subject, base_pin, expected_subject_sha256,
        base_replay, candidate_inputs, expected_candidate_pin, context_inputs,
        expected_context_population, dependency_manifest, expected_manifest_sha256,
        required_dependency_ids,
    )
    snapshot = {"binding_result": offered, "contextual_replay_inputs": replay,
                "base_expected_binding_sha256": base_pin, "originals": originals}
    _footprint(snapshot)
    base._need(_pure_pins() == _IMPORTED_PURE_PINS, "contextual correspondence pure owners changed during preflight")
    return snapshot


def _owners():
    from . import legal_source_sampling_definition_binding_v2 as binding
    from . import corpus_contracts as contracts

    return binding, contracts


def _pins(owners):
    global _OPERATION_PINS
    result = _pure_pins()
    base._need(result == _IMPORTED_PURE_PINS, "contextual correspondence pure owners changed since import")
    for module in owners:
        path = Path(module.__file__).resolve()
        result[str(path)] = base._raw_sha(path.read_bytes())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(result)
    base._need(result == _OPERATION_PINS, "contextual correspondence operation owners changed since first use")
    return result


def _same(left, right, maximum=MAX_RECORD_BYTES):
    return base._wire(left, maximum) == base._wire(right, maximum)


def _declarations(responses, metadata):
    direct = {row["sha256"] for row in metadata["direct_response_refs"]}
    related = {row["response_ref"]["sha256"] for row in metadata["related_target_responses"]}
    base._need(not direct & related, "direct and related contextual declarations must remain disjoint")
    rows = []
    for response in responses:
        ref = base._record_ref(response)
        base._need((ref["sha256"] in direct) != (ref["sha256"] in related),
                   "each complete contextual response needs one exact direct or related role")
        declaration = response["declaration"]
        rows.append({
            "response_ref": ref, "declaration_sha256": response["declaration_sha256"],
            "bundle_sha256": declaration["bundle_sha256"],
            "subject_ref": declaration["subject_ref"],
            "response_role": "direct" if ref["sha256"] in direct else "related",
            "reviewer_declaration_ref": {"sha256": base._digest(declaration["reviewer_declaration"])},
            "exposure_declaration_ref": {"sha256": base._digest(declaration["exposure_declaration"])},
            "exposure_declaration": declaration["exposure_declaration"],
        })
    base._need(len(rows) == len(direct) + len(related),
               "complete ordered contextual declaration population required")
    return rows


def prepare(
    binding_result, review_subject, *, expected_binding_sha256,
    expected_subject_sha256, contextual_replay_inputs, candidate_inputs,
    expected_candidate_pin, context_inputs, expected_context_population,
    dependency_manifest, expected_manifest_sha256, required_dependency_ids,
):
    """Preserve the existing correspondence beside independently replayed context."""
    snapshot = _preflight(
        binding_result, review_subject, expected_binding_sha256=expected_binding_sha256,
        expected_subject_sha256=expected_subject_sha256,
        contextual_replay_inputs=contextual_replay_inputs,
        candidate_inputs=candidate_inputs, expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs, expected_context_population=expected_context_population,
        dependency_manifest=dependency_manifest, expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=required_dependency_ids,
    )
    token = base._snapshot_pin(snapshot)
    owners = _owners()
    binding, contracts = owners
    producers = _pins(owners)

    def fence():
        base._need(base._snapshot_pin(snapshot) == token,
                   "detached contextual correspondence inputs changed during replay")
        base._need(_pins(owners) == producers,
                   "contextual correspondence producers changed during replay")

    fence()
    replay = snapshot["contextual_replay_inputs"]
    checked = binding.validate_contextual_definition_binding_v2(
        snapshot["binding_result"], replay["request_raw"], replay["context"],
        replay["responses"], replay["sources"], replay["attachments"],
        expected_binding_sha256=expected_binding_sha256,
        **{key: replay[key] for key in _PIN_FIELDS},
    )
    fence()
    base._need(_same(checked, snapshot["binding_result"], MAX_OUTPUT_BYTES),
               "complete contextual owner result differs from independently pinned input")
    original = snapshot["originals"]
    correspondence = base.prepare_definition_review_correspondence_v2(
        checked["base_binding"], original["review_subject"],
        expected_binding_sha256=snapshot["base_expected_binding_sha256"],
        expected_subject_sha256=expected_subject_sha256,
        binding_replay_inputs=original["binding_replay_inputs"],
        **{key: original[key] for key in (
            "candidate_inputs", "expected_candidate_pin", "context_inputs",
            "expected_context_population", "dependency_manifest", "required_dependency_ids",
        )},
        expected_manifest_sha256=expected_manifest_sha256,
    )
    fence()
    base._need(_same(checked, snapshot["binding_result"], MAX_OUTPUT_BYTES),
               "contextual binding changed during definition correspondence replay")
    metadata, population = checked["contextual_binding"], checked["contextual_population"]
    base._need(correspondence["response_count"] == 0
               and correspondence["binding_input_pins"]["response_full_canonical_sha256s"] == [],
               "base correspondence must retain the explicitly empty v1 response population")
    all_producers = dict(producers)
    for observed in (correspondence["producer_pins"], metadata["producer_pins"]):
        for path, digest in observed.items():
            base._need(path not in all_producers or all_producers[path] == digest,
                       "contextual correspondence producer observations disagree")
            all_producers[path] = digest

    def producer_fence():
        fence()
        for path, digest in all_producers.items():
            base._need(base._raw_sha(Path(path).read_bytes()) == digest,
                       "observed contextual correspondence producer changed")

    producer_fence()
    authority = dict.fromkeys({*correspondence["authority"],
        "contextual_binding_authenticated", "contextual_responses_authenticated",
        "contextual_exposure_authenticated", "contextual_exposure_correspondence_verified",
        "contextual_semantic_agreement_verified", "signed_subject_contextual_coverage_verified",
    }, False)
    companion = contracts.seal_record({
        "schema": METADATA_SCHEMA, "profile": PROFILE, "view": "candidate",
        "status": "unsigned_contextual_correspondence_only", "unsigned": True,
        "assessment_created": False,
        "source_declaration_status": metadata["status"],
        "contextual_binding_ref": {"schema": checked["schema"], "sha256": expected_binding_sha256,
            "binding_record_cid": metadata["record_cid"]},
        "definition_correspondence_ref": base._record_ref(correspondence),
        "subject_ref": correspondence["subject_ref"],
        "dependency_manifest_ref": correspondence["dependency_manifest_ref"],
        "input_pins": metadata["input_pins"], "source_identity": metadata["source_identity"],
        **{key: metadata[key] for key in (
            "required_subjects", "required_subject_count", "required_support_nominations",
            "required_support_nomination_count", "direct_response_refs", "direct_response_count",
            "related_target_responses", "related_target_response_count", "response_count",
            "all_required_subjects_have_direct_declarations", "context_counts", "contextual_population_ref",
        )},
        "contextual_population_counts": population["counts"],
        "contextual_population_subject_count": population["subject_count"],
        "contextual_population_response_count": population["response_count"],
        "response_declarations": _declarations(replay["responses"], metadata),
        "original_subject_covers_contextual_companion": False,
        "original_subject_covers_contextual_responses": False,
        "original_subject_unchanged": True, "original_dependency_manifest_unchanged": True,
        "external_contextual_inputs_required": True, "response_payloads_embedded": False,
        "context_packet_embedded": False, "contextual_population_complete": True,
        "response_schema_converted": False, "related_declarations_close_definition_review": False,
        "declaration_prose_interpreted": False, "caller_ast_rewritten": False,
        "producer_pins": all_producers, "authority": authority,
        "training_mask": 0, "evaluation_gold_mask": 0,
    })
    result = json.loads(base._wire({
        "schema": SCHEMA, "definition_correspondence": correspondence,
        "contextual_correspondence": companion,
    }, MAX_OUTPUT_BYTES))
    producer_fence()
    return result


def correspondence_sha256(correspondence):
    """Commit the entire closed envelope including both separate sealed records."""
    base._keys(correspondence, _OUTPUT_FIELDS, "complete contextual correspondence envelope")
    base._need(correspondence["schema"] == SCHEMA, "distinct contextual correspondence schema required")
    original = correspondence["definition_correspondence"]
    base.definition_review_correspondence_sha256(original)
    companion = correspondence["contextual_correspondence"]
    base._need(type(companion) is dict and companion.get("schema") == METADATA_SCHEMA,
               "distinct contextual correspondence metadata required")
    base._wire(companion, MAX_RECORD_BYTES)
    return base._digest(correspondence, MAX_OUTPUT_BYTES)


def validate(correspondence, *args, expected_correspondence_sha256, **kwargs):
    """Regenerate the whole contextual envelope under its independent commitment."""
    base._sha(expected_correspondence_sha256, "complete contextual correspondence")
    offered = base._wire(correspondence, MAX_OUTPUT_BYTES)
    base._need(correspondence_sha256(correspondence) == expected_correspondence_sha256,
               "independent complete contextual correspondence pin differs")
    expected = prepare(*args, **kwargs)
    base._need(offered == base._wire(expected, MAX_OUTPUT_BYTES),
               "contextual correspondence differs from complete independent regeneration")
    return expected
