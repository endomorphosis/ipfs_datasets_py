"""Bind explicit V2 definition candidates to complete sampled-source review.

Source extraction, reviewer declarations, native encoding and corpus envelopes
retain their existing owners. This adapter records which exact review subjects
support each declared source role; it does not interpret reviewer prose, resolve
legal context, authenticate a person or admit a statutory meaning. Public import
uses only the standard library. Native operation owners load after input bounds
and independent transport/canonical commitments have been checked.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

SCHEMA = "legal-source-sampling-definition-binding/v2"
BINDING_SCHEMA = "legal-source-sampling-definition-binding-metadata/v1"
PROFILE = "sampled-source-explicit-unary-definition-candidate/v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = MAX_RECORD_BYTES
MAX_RESPONSE_BYTES = MAX_RECORD_BYTES
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_POPULATION_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_RAW_BYTES = 8_000_000
MAX_RESPONSES = 8192
MAX_SUBJECTS = 4096
MAX_SAMPLING_BYTES = 32 * 1024 * 1024
MAX_JSON_NODES = 2_000_000
MAX_JSON_DEPTH = 64
_INPUT_FIELDS = {
    "expected_sampling_report_sha256", "descriptor",
    "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes",
}
_OPTIONAL_INPUT_FIELDS = {"view_limits", "sampling_limits"}
FALSE_FLAGS = dict.fromkeys(
    (
        "reviewer_identity_authenticated", "reviewer_independence_verified",
        "source_findings_verified", "source_context_resolved",
        "source_authenticity_verified", "publisher_authenticity_verified",
        "legal_currentness_verified", "source_semantics_verified",
        "legal_roles_verified", "governing_source_binding_verified",
        "applicability_semantics_verified", "applicability_verified",
        "context_closure_verified", "definition_operator_interpreted",
        "independently_reviewed", "meaning_admitted", "admitted", "formalized",
        "semantic_graph_admitted", "training_qualified", "training_gold_qualified",
        "evaluation_gold_qualified", "Lean_admitted", "lean_compilation_verified",
        "backend_executed", "proof_authority", "signature_verified",
        "cross_family_equivalence_verified", "learned_translation",
        "external_definition_resolution_verified",
    ),
    False,
)
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OPERATION_PINS = None


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value, label):
    _need(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "independent lowercase SHA256 required: " + label,
    )


def _digest_raw(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value, maximum):
    """Bound ordinary finite JSON before serialization or operation imports."""
    remaining, nodes = maximum, MAX_JSON_NODES

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(
            nodes >= 0 and depth <= MAX_JSON_DEPTH,
            "definition binding JSON node/depth bound exceeded",
        )
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON object keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need(
                "\x00" not in item and len(item) <= remaining,
                "definition binding JSON string/byte bound exceeded",
            )
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid definition binding UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite definition binding JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary definition binding JSON values required")
        _need(remaining >= 0, "complete definition binding JSON byte bound exceeded")

    visit(value, 0)
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded finite definition binding JSON required") from error
    _need(len(raw) <= maximum, "complete definition binding JSON byte bound exceeded")
    return raw


def _digest(value, maximum=MAX_RECORD_BYTES):
    return _digest_raw(_wire(value, maximum))


def _parse_request(raw, expected_sha256):
    _sha(expected_sha256, "original definition request bytes")
    _need(
        type(raw) is bytes and 1 <= len(raw) <= MAX_REQUEST_BYTES,
        "bounded nonempty original definition request bytes required",
    )
    _need(_digest_raw(raw) == expected_sha256, "original definition request pin differs")

    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate definition request JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("finite definition request JSON required")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free finite definition request JSON required") from error
    _need(type(value) is dict, "definition request JSON object required")
    return json.loads(_wire(value, MAX_REQUEST_BYTES))


def _preflight(
    request_raw, bundle, responses, raw_html, expected_request_sha256,
    expected_bundle_sha256, expected_response_sha256s, replay_inputs,
):
    request = _parse_request(request_raw, expected_request_sha256)
    _sha(expected_bundle_sha256, "complete sampled-source review bundle")
    _need(type(bundle) is dict, "complete sampled-source review bundle required")
    bundle_raw = _wire(bundle, MAX_BUNDLE_BYTES)
    _need(
        _digest_raw(bundle_raw) == expected_bundle_sha256,
        "independent complete sampled-source review bundle pin differs",
    )
    offered_bundle = json.loads(bundle_raw)
    _need(
        type(offered_bundle.get("guides")) is list
        and len(offered_bundle["guides"]) <= MAX_SUBJECTS,
        "bounded complete sampled-source guide population required",
    )
    _need(
        type(responses) is list and len(responses) <= MAX_RESPONSES
        and type(expected_response_sha256s) is list
        and len(expected_response_sha256s) == len(responses),
        "one independent ordered pin per bounded supplied response required",
    )
    detached_responses, used = [], 0
    for response, expected in zip(responses, expected_response_sha256s, strict=True):
        _sha(expected, "complete sampled-source response")
        raw = _wire(response, MAX_RESPONSE_BYTES)
        used += len(raw)
        _need(
            used <= MAX_RESPONSE_POPULATION_BYTES,
            "complete response population byte bound exceeded before source replay",
        )
        _need(_digest_raw(raw) == expected, "independent complete response pin differs")
        detached_responses.append(json.loads(raw))
    _need(
        len(set(expected_response_sha256s)) == len(detached_responses),
        "duplicate exact responses cannot inflate review population",
    )
    _need(
        _INPUT_FIELDS <= set(replay_inputs)
        <= _INPUT_FIELDS | _OPTIONAL_INPUT_FIELDS,
        "closed existing sampling replay inputs required",
    )
    detached_inputs = json.loads(_wire(replay_inputs, MAX_RECORD_BYTES))
    for key in (
        "expected_sampling_report_sha256", "expected_descriptor_sha256",
        "expected_raw_sha256",
    ):
        _sha(detached_inputs[key], key)
    # These are full canonical commitments to the supplied values. Their
    # schemas and source correspondence are still replayed by the existing
    # owners; checking bytes here grants no custody or interpretation authority.
    _need(
        _digest(offered_bundle.get("sampling_report"), MAX_SAMPLING_BYTES)
        == detached_inputs["expected_sampling_report_sha256"],
        "independent complete sampling report pin differs",
    )
    _need(
        _digest(detached_inputs["descriptor"])
        == detached_inputs["expected_descriptor_sha256"],
        "independent complete acquisition descriptor pin differs",
    )
    count = detached_inputs["expected_raw_bytes"]
    _need(
        type(count) is int and 1 <= count <= MAX_RAW_BYTES
        and type(raw_html) is bytes and len(raw_html) == count,
        "independently bounded exact raw source bytes required",
    )
    _need(
        _digest_raw(raw_html) == detached_inputs["expected_raw_sha256"],
        "independent raw source pin differs",
    )
    return request, offered_bundle, detached_responses, detached_inputs


def _owners():
    from . import (
        legal_source_sampling_review as review,
        legal_source_definition_bridge_v2 as bridge,
        corpus_definition_adapter_v2 as adapter,
        corpus_contracts as contracts,
        legal_source_sampling as sampler,
    )

    return review, bridge, adapter, contracts, sampler


def _pins(owners):
    global _OPERATION_PINS
    _, bridge, adapter, _, _ = owners
    own_path = Path(__file__).resolve()
    _need(_digest_raw(own_path.read_bytes()) == _SELF_PIN, "definition binding source changed since import")
    result = {
        str(Path(module.__file__).resolve()): _digest_raw(Path(module.__file__).read_bytes())
        for module in owners
    }
    result[str(own_path)] = _SELF_PIN
    result.update(bridge.producer_pins())
    result.update(adapter.producer_pins())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(result)
    _need(result == _OPERATION_PINS, "definition binding operation owners changed since first use")
    return result


def _record_ref(record):
    return {
        "schema": record["schema"], "record_cid": record["record_cid"],
        "sha256": _digest(record),
    }


def _subject_key(subject):
    return subject["kind"], subject["index"], subject["sha256"]


def _subject_bindings(request, bundle, report, population, sampler):
    """Preserve original role multiplicity and complete affected subject closure."""
    sampling = bundle["sampling_report"]
    units = [r for r in sampling["records"] if r["schema"] == sampler.UNIT_SCHEMA]
    by_cid = {unit["record_cid"]: unit for unit in units}
    by_ordinal = {unit["ordinal"]: unit for unit in units}
    guides = {_subject_key(guide["subject_ref"]): guide for guide in bundle["guides"]}
    _need(len(guides) == len(bundle["guides"]), "distinct complete guide subjects required")
    required_roles, selected_units = {}, []

    def add(subject, role):
        key = _subject_key(subject)
        _need(key in guides, "exact affected source-review subject required")
        roles = required_roles.setdefault(key, [])
        if role not in roles:
            roles.append(role)

    def unit_subject(unit):
        return {"kind": "unit", "index": unit["ordinal"], "sha256": _digest(unit)}

    declared = request["declaration"]
    offered_units = [("scope_unit", declared["scope_unit_ref"])] + [
        (f"definition_contributor/{index:04d}", ref)
        for index, ref in enumerate(declared["contributor_unit_refs"])
    ]
    selected_ordinals = set()
    for role, ref in offered_units:
        unit = by_cid.get(ref["record_cid"])
        _need(unit is not None and ref == _record_ref(unit), "exact original selected sampler unit required")
        subject = unit_subject(unit)
        add(subject, role)
        selected_ordinals.add(unit["ordinal"])
        selected_units.append({"role": role, "unit_ref": ref, "subject_ref": subject})

    blocks = sampling["document_view_report"]["document"]["blocks"]
    occurrences = {r["record_cid"]: r for r in report["source_occurrences"]}
    roles = []
    for binding in report["source_bindings"]:
        occurrence = occurrences[binding["source_occurrence_cid"]]
        touched = [
            block["block_index"] for block in blocks
            if block["char_start"] < occurrence["end_char"]
            and occurrence["start_char"] < block["char_end"]
        ]
        _need(
            touched and touched == binding["block_indices"]
            and set(touched) <= selected_ordinals,
            "complete authoritative role geometry must map to declared source units",
        )
        subjects = []
        for ordinal in touched:
            _need(ordinal in by_ordinal, "every intersected role block needs its original sampler unit")
            subject = unit_subject(by_ordinal[ordinal])
            add(subject, binding["role"])
            subjects.append(subject)
        # A split/nested physical paragraph has an additional retained parent
        # subject. Its context is required evidence, never silently discarded.
        for index, parent in enumerate(sampling["withheld_paragraph_contexts"]):
            if set(touched).intersection(parent["block_indices"]):
                subject = {"kind": "withheld_context", "index": index, "sha256": _digest(parent)}
                add(subject, binding["role"])
                subjects.append(subject)
        roles.append({**binding, "subject_refs": subjects})

    by_subject = {_subject_key(row["subject_ref"]): row for row in population["subjects"]}
    _need(
        list(by_subject) == list(guides),
        "whole population must preserve every original ordered guide subject",
    )
    required = []
    for key, guide in guides.items():
        if key in required_roles:
            row = by_subject[key]
            required.append({
                "subject_ref": row["subject_ref"], "guide_ref": _record_ref(guide),
                "roles": required_roles[key], "response_refs": row["response_refs"],
                "state": row["state"], "reasons": row["reasons"],
            })
    _need(bool(required), "nonempty selected definition source-review subject population required")
    return selected_units, roles, required


def prepare_definition_binding_v2(
    request_raw, bundle, responses, raw_html, *, expected_request_sha256,
    expected_bundle_sha256, expected_response_sha256s, **sampling_replay_inputs,
):
    """Replay exact source/declarations and encode only the explicit request.

    An empty response population is valid and remains pending. No response is
    inferred from a blank guide, reviewer prose or a caller's formal AST. Every
    supplied response must concern a selected source role or affected parent.
    Full unselected population state remains in the returned companion.
    """
    request, offered_bundle, offered_responses, replay_inputs = _preflight(
        request_raw, bundle, responses, raw_html, expected_request_sha256,
        expected_bundle_sha256, expected_response_sha256s, sampling_replay_inputs,
    )
    owners = _owners()
    review, bridge, adapter, contracts, sampler = owners
    pins = _pins(owners)
    # This public owner regenerates the *complete* offered bundle before it
    # validates every response and creates the full population. Only after its
    # success may the detached, independently pinned bundle be reused below.
    population = review.summarize_sampling_review_population(
        offered_bundle, offered_responses, raw_html,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_response_sha256s=expected_response_sha256s,
        **replay_inputs,
    )
    checked_bundle = offered_bundle
    sampling = checked_bundle["sampling_report"]
    _need(
        _digest(sampling, MAX_SAMPLING_BYTES)
        == replay_inputs["expected_sampling_report_sha256"],
        "definition and reviewed bundle must retain the same complete sampling report",
    )
    definition_inputs = {
        "sampling_report": sampling, "raw_html": raw_html, **replay_inputs,
    }
    report = bridge.prepare_definition_v2(request, **definition_inputs)
    report_raw = _wire(report, MAX_RECORD_BYTES)
    candidate = adapter.adapt_definition_only_bytes_v2(
        report_raw, expected_report_sha256=_digest_raw(report_raw),
        request_raw=request_raw, expected_request_sha256=expected_request_sha256,
        **definition_inputs,
    )
    document = sampling["document_view_report"]["document"]
    view_id = sampling["document_view_report"]["normalized_view"]["view_id"]
    source_versions = [
        row for row in sampling["records"]
        if row["schema"] == "legal-corpus-source-version/v1"
    ]
    _need(
        len(source_versions) == 1
        and report["source_version"] == source_versions[0]
        and candidate["source_version"] == source_versions[0]
        and request["declaration"]["source_version_ref"] == _record_ref(source_versions[0])
        and report["normalized_view_id"] == view_id
        and request["declaration"]["normalized_view_id"] == view_id
        and report["document_id"] == document["document_id"]
        and report["document_text_sha256"] == document["document_text_sha256"],
        "exact definition/bundle source version, normalized view and document identity required",
    )
    selected_units, source_roles, required = _subject_bindings(
        request, checked_bundle, report, population, sampler,
    )
    required_keys = {_subject_key(row["subject_ref"]) for row in required}
    _need(
        all(_subject_key(response["subject_ref"]) in required_keys for response in offered_responses),
        "supplied response is outside the complete selected definition subject population",
    )
    states = {row["state"] for row in required}
    status = next(
        (state for state in ("disputed", "unsupported", "pending") if state in states),
        "declarations_recorded",
    )
    _need(_pins(owners) == pins, "definition binding producers changed during preparation")
    binding = contracts.seal_record({
        "schema": BINDING_SCHEMA, "profile": PROFILE, "view": "candidate",
        "status": status,
        "input_pins": {
            "request_sha256": expected_request_sha256,
            "request_full_canonical_sha256": _digest(request),
            "bundle_full_canonical_sha256": expected_bundle_sha256,
            "response_full_canonical_sha256s": list(expected_response_sha256s),
            "sampling_report_full_canonical_sha256": replay_inputs["expected_sampling_report_sha256"],
            "descriptor_full_canonical_sha256": replay_inputs["expected_descriptor_sha256"],
            "raw_sha256": replay_inputs["expected_raw_sha256"],
            "raw_bytes": replay_inputs["expected_raw_bytes"],
        },
        "source_identity": {
            "source_version_ref": _record_ref(source_versions[0]),
            "normalized_view_id": view_id, "document_id": document["document_id"],
            "document_text_sha256": document["document_text_sha256"],
        },
        "definition_report_ref": {
            "schema": report["schema"], "sha256": _digest_raw(report_raw),
            "producer_report_sha256": report["report_sha256"],
        },
        "candidate_ref": _record_ref(candidate),
        "population_ref": _record_ref(population),
        "selected_unit_roles": selected_units,
        "source_role_bindings": source_roles,
        "required_subjects": required,
        "selected_subject_count": len(required),
        "response_count": len(offered_responses),
        "response_refs": [_record_ref(response) for response in offered_responses],
        "producer_pins": pins,
        "source_role_population_complete": True,
        "selected_subject_population_complete": True,
        "all_selected_subjects_have_declarations": all(row["response_refs"] for row in required),
        "interpretation_status": "unreviewed_caller_declaration",
        "authority": dict(FALSE_FLAGS), "training_mask": 0, "evaluation_gold_mask": 0,
    })
    for record in (binding, report, candidate, population):
        _wire(record, MAX_RECORD_BYTES)
    result = {
        "schema": SCHEMA, "binding": binding, "definition_report": report,
        "candidate": candidate, "population": population,
    }
    _need(_pins(owners) == pins, "definition binding producers changed before final output")
    return json.loads(_wire(result, MAX_OUTPUT_BYTES))


def definition_binding_sha256(result):
    """Canonical FULL envelope commitment, including all four companions."""
    _need(
        type(result) is dict
        and set(result) == {"schema", "binding", "definition_report", "candidate", "population"}
        and result["schema"] == SCHEMA,
        "complete sampled-source definition binding envelope required",
    )
    for key in ("binding", "definition_report", "candidate", "population"):
        _wire(result[key], MAX_RECORD_BYTES)
    return _digest(result, MAX_OUTPUT_BYTES)


def validate_definition_binding_v2(
    result, request_raw, bundle, responses, raw_html, *, expected_binding_sha256,
    expected_request_sha256, expected_bundle_sha256, expected_response_sha256s,
    **sampling_replay_inputs,
):
    """Check the full independent envelope pin and regenerate every companion."""
    _sha(expected_binding_sha256, "complete definition binding envelope")
    _need(
        definition_binding_sha256(result) == expected_binding_sha256,
        "independent complete definition binding pin differs",
    )
    offered = _wire(result, MAX_OUTPUT_BYTES)
    expected = prepare_definition_binding_v2(
        request_raw, bundle, responses, raw_html,
        expected_request_sha256=expected_request_sha256,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_response_sha256s=expected_response_sha256s,
        **sampling_replay_inputs,
    )
    _need(
        offered == _wire(expected, MAX_OUTPUT_BYTES),
        "definition binding differs from complete independent authoritative regeneration",
    )
    return expected


def prepare_contextual_definition_binding_v2(
    request_raw, context, responses, sources, attachments, *,
    expected_request_sha256, expected_definition_bundle_sha256,
    expected_context_sha256, expected_response_sha256s,
    expected_attachments_sha256,
):
    """Retain context declarations beside an unchanged explicit V2 candidate.

    Supporting-subject citations are related declarations, never reviews of the
    supporting definition. The complete context packet remains an independently
    pinned replay dependency instead of being duplicated inside the envelope.
    """
    from . import legal_source_sampling_context_definition_binding_v2 as context_owner

    return context_owner.prepare(
        request_raw, context, responses, sources, attachments,
        expected_request_sha256=expected_request_sha256,
        expected_definition_bundle_sha256=expected_definition_bundle_sha256,
        expected_context_sha256=expected_context_sha256,
        expected_response_sha256s=expected_response_sha256s,
        expected_attachments_sha256=expected_attachments_sha256,
    )


def contextual_definition_binding_sha256(result):
    """Hash the complete distinct contextual binding envelope."""
    from . import legal_source_sampling_context_definition_binding_v2 as context_owner

    return context_owner.binding_sha256(result)


def validate_contextual_definition_binding_v2(
    result, request_raw, context, responses, sources, attachments, *,
    expected_binding_sha256, expected_request_sha256,
    expected_definition_bundle_sha256, expected_context_sha256,
    expected_response_sha256s, expected_attachments_sha256,
):
    """Replay the candidate, whole source population and distinct declarations."""
    from . import legal_source_sampling_context_definition_binding_v2 as context_owner

    return context_owner.validate(
        result, request_raw, context, responses, sources, attachments,
        expected_binding_sha256=expected_binding_sha256,
        expected_request_sha256=expected_request_sha256,
        expected_definition_bundle_sha256=expected_definition_bundle_sha256,
        expected_context_sha256=expected_context_sha256,
        expected_response_sha256s=expected_response_sha256s,
        expected_attachments_sha256=expected_attachments_sha256,
    )


__all__ = [
    "prepare_definition_binding_v2", "definition_binding_sha256",
    "validate_definition_binding_v2",
    "prepare_contextual_definition_binding_v2", "contextual_definition_binding_sha256",
    "validate_contextual_definition_binding_v2",
]
