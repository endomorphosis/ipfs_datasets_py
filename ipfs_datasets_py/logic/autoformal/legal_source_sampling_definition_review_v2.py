"""Unsigned custody correspondence to the existing V2 interpretation subject.

Existing public owners regenerate the sampled-source binding, candidate and
review subject. This module neither interprets reviewer prose nor creates a
review, signature, assessment, context closure or admission. Original transport
bytes remain distinct from full canonical JSON commitments. In particular,
reserializing a report changes the existing candidate's transport dependency;
equal decoded reports cannot authorize that different candidate here.

Public import loads only the standard library. All caller inputs are bounded,
independently pinned and detached before operation owners are imported.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


SCHEMA = "legal-source-sampling-definition-review-correspondence/v1"
PROFILE = "unsigned-exact-v2-definition-source-review-subject-link/v1"
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_BINDING_BYTES = 4 * MAX_RECORD_BYTES
MAX_BUNDLE_BYTES = 64 * MAX_RECORD_BYTES
MAX_RESPONSE_POPULATION_BYTES = 64 * MAX_RECORD_BYTES
MAX_SAMPLING_BYTES = 32 * MAX_RECORD_BYTES
MAX_RAW_BYTES = 8_000_000
MAX_MANIFEST_BYTES = 8 * MAX_RECORD_BYTES
MAX_REVIEW_INPUT_BYTES = 48 * MAX_RECORD_BYTES
MAX_RESPONSES = 8192
MAX_SUBJECTS = 4096
MAX_CONTEXT_OCCURRENCES = 256
MAX_CONTEXT_OBLIGATIONS = 1536
MAX_JSON_NODES = 2_000_000
MAX_JSON_DEPTH = 64

_BINDING_FIELDS = {"schema", "binding", "definition_report", "candidate", "population"}
_REPLAY_FIELDS = {
    "request_raw", "bundle", "responses", "raw_html", "expected_request_sha256",
    "expected_bundle_sha256", "expected_response_sha256s", "sampling_replay_inputs",
}
_SAMPLING_FIELDS = {
    "expected_sampling_report_sha256", "descriptor", "expected_descriptor_sha256",
    "expected_raw_sha256", "expected_raw_bytes",
}
_OPTIONAL_SAMPLING_FIELDS = {"view_limits", "sampling_limits"}
_CANDIDATE_FIELDS = {
    "candidate_raw", "report_raw", "request_raw", "raw_html",
    "sampling_report_raw", "descriptor_raw",
}
_TRANSPORT_PINS = {
    "candidate_raw": "candidate_sha256", "report_raw": "report_sha256",
    "request_raw": "request_sha256", "raw_html": "raw_sha256",
    "sampling_report_raw": "sampling_report_sha256", "descriptor_raw": "descriptor_sha256",
}
_CANDIDATE_PIN_FIELDS = {
    *_TRANSPORT_PINS.values(), "candidate_cid", "graph_cid", "raw_bytes",
    "extracted_sha256", "sampling_report_full_canonical_sha256",
    "descriptor_full_canonical_sha256",
}
_SUBJECT_FIELDS = {
    "schema", "graph_id", "graph_sha256", "ast_sha256", "scope_id",
    "context_slot_ids", "dependency_manifest_sha256", "required_dependency_ids",
    "dependency_artifacts", "graph_declared_dependency_refs", "native_binding",
}
_CONTEXT_FIELDS = {"source_occurrence_cid", "packet_raw", "dependency_requests"}
_CONTEXT_PIN_FIELDS = {"source_occurrence_cid", "packet_sha256"}
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_OPERATION_PINS = None


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value, label):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
          "independent lowercase SHA256 required: " + label)


def _raw_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _wire(value, maximum, *, review_json=False):
    remaining, nodes = maximum, 0

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes += 1
        _need(depth <= (40 if review_json else MAX_JSON_DEPTH)
              and nodes <= (262144 if review_json else MAX_JSON_NODES),
              "complete correspondence JSON depth/node bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining,
                  "bounded complete UTF8 correspondence strings required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid correspondence UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= ((1 << 53) - 1 if review_json else (1 << 63) - 1),
                  "bounded ordinary correspondence integer required")
            remaining -= len(str(item))
        elif type(item) is float and not review_json:
            _need(math.isfinite(item), "finite correspondence JSON required")
            remaining -= len(repr(item))
        else:
            raise ValueError("ordinary bounded correspondence JSON required")
        _need(remaining >= 0, "complete correspondence JSON byte bound exceeded")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded complete correspondence JSON required") from error
    _need(len(raw) <= maximum, "complete correspondence JSON byte bound exceeded")
    return raw


def _digest(value, maximum=MAX_RECORD_BYTES, *, review_json=False):
    return _raw_sha(_wire(value, maximum, review_json=review_json))


def _decode(raw, maximum):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate original JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("finite original JSON required")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("duplicate-free bounded original UTF8 JSON required") from error
    _need(type(value) is dict, "complete original JSON object required")
    _wire(value, maximum)
    return value


def _snapshot_pin(value):
    """Private mutation fence over detached ordinary JSON and immutable bytes."""
    digest = hashlib.sha256()

    def add(item):
        if type(item) is bytes:
            digest.update(b"bytes:" + str(len(item)).encode() + b":" + item)
        elif type(item) is dict:
            digest.update(b"dict:")
            for key in sorted(item):
                add(key)
                add(item[key])
            digest.update(b"end-dict:")
        elif type(item) is list:
            digest.update(b"list:")
            for child in item:
                add(child)
            digest.update(b"end-list:")
        else:
            raw = json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")
            digest.update(b"json:" + str(len(raw)).encode() + b":" + raw)

    add(value)
    return digest.hexdigest()


def _preflight(binding_result, review_subject, expected_binding_sha256,
               expected_subject_sha256, binding_replay_inputs, candidate_inputs,
               expected_candidate_pin, context_inputs, expected_context_population,
               dependency_manifest, expected_manifest_sha256, required_dependency_ids):
    used = 0

    def charge(size):
        nonlocal used
        used += size
        _need(used <= MAX_INPUT_BYTES, "complete correspondence input budget exceeded")

    def copy(value, maximum, *, review_json=False):
        raw = _wire(value, maximum, review_json=review_json)
        charge(len(raw))
        return json.loads(raw)

    def raw(value, maximum, label):
        _need(type(value) is bytes and 1 <= len(value) <= maximum,
              "bounded nonempty original bytes required: " + label)
        charge(len(value))
        return value

    for value, label in ((expected_binding_sha256, "complete binding envelope"),
                         (expected_subject_sha256, "existing review subject"),
                         (expected_manifest_sha256, "existing dependency manifest")):
        _sha(value, label)
        charge(len(value))
    _keys(binding_result, _BINDING_FIELDS, "complete binding envelope")
    checked_binding = copy(binding_result, MAX_BINDING_BYTES)
    _need(checked_binding["schema"] == "legal-source-sampling-definition-binding/v2"
          and _digest(checked_binding, MAX_BINDING_BYTES) == expected_binding_sha256,
          "independent complete binding envelope pin or schema differs")
    for field in _BINDING_FIELDS - {"schema"}:
        _wire(checked_binding[field], MAX_RECORD_BYTES)
    _keys(review_subject, _SUBJECT_FIELDS, "existing plain V2 review subject")
    checked_subject = copy(review_subject, MAX_RECORD_BYTES, review_json=True)
    _need(checked_subject["schema"] == "legal-corpus-v2-definition-review-subject/v1"
          and _digest(checked_subject, review_json=True) == expected_subject_sha256,
          "independent existing review subject pin or schema differs")

    _keys(binding_replay_inputs, _REPLAY_FIELDS, "binding replay inputs")
    replay = {}
    for key in ("expected_request_sha256", "expected_bundle_sha256"):
        _sha(binding_replay_inputs[key], key)
        replay[key] = binding_replay_inputs[key]
        charge(len(replay[key]))
    replay["request_raw"] = raw(binding_replay_inputs["request_raw"], MAX_RECORD_BYTES, "request")
    _need(_raw_sha(replay["request_raw"]) == replay["expected_request_sha256"],
          "independent original binding request pin differs")
    request = _decode(replay["request_raw"], MAX_RECORD_BYTES)
    replay["raw_html"] = raw(binding_replay_inputs["raw_html"], MAX_RAW_BYTES, "HTML")
    replay["bundle"] = copy(binding_replay_inputs["bundle"], MAX_BUNDLE_BYTES)
    _need(_digest(replay["bundle"], MAX_BUNDLE_BYTES) == replay["expected_bundle_sha256"],
          "independent complete review bundle pin differs")
    _need(type(replay["bundle"].get("guides")) is list
          and len(replay["bundle"]["guides"]) <= MAX_SUBJECTS,
          "bounded complete sampled-source guide population required")
    responses = binding_replay_inputs["responses"]
    response_pins = binding_replay_inputs["expected_response_sha256s"]
    _need(type(responses) is list and len(responses) <= MAX_RESPONSES
          and type(response_pins) is list and len(response_pins) == len(responses),
          "one ordered independent pin per bounded supplied response required")
    replay["expected_response_sha256s"] = copy(response_pins, MAX_RECORD_BYTES)
    replay["responses"], response_bytes = [], 0
    for response, expected in zip(responses, replay["expected_response_sha256s"], strict=True):
        _sha(expected, "complete response")
        offered = copy(response, MAX_RECORD_BYTES)
        encoded = _wire(offered, MAX_RECORD_BYTES)
        response_bytes += len(encoded)
        _need(response_bytes <= MAX_RESPONSE_POPULATION_BYTES and _raw_sha(encoded) == expected,
              "complete response population bound or independent pin differs")
        replay["responses"].append(offered)
    _need(len(set(replay["expected_response_sha256s"])) == len(replay["responses"]),
          "duplicate exact responses cannot inflate correspondence")
    sampling = binding_replay_inputs["sampling_replay_inputs"]
    _need(type(sampling) is dict and _SAMPLING_FIELDS <= set(sampling)
          <= _SAMPLING_FIELDS | _OPTIONAL_SAMPLING_FIELDS,
          "closed existing sampling replay inputs required")
    replay["sampling_replay_inputs"] = copy(sampling, MAX_RECORD_BYTES)
    sampling = replay["sampling_replay_inputs"]
    for key in ("expected_sampling_report_sha256", "expected_descriptor_sha256", "expected_raw_sha256"):
        _sha(sampling[key], key)
    count = sampling["expected_raw_bytes"]
    _need(type(count) is int and 1 <= count <= MAX_RAW_BYTES
          and len(replay["raw_html"]) == count
          and _raw_sha(replay["raw_html"]) == sampling["expected_raw_sha256"],
          "exact original HTML bytes and integer length required")
    _need(_digest(replay["bundle"].get("sampling_report"), MAX_SAMPLING_BYTES)
          == sampling["expected_sampling_report_sha256"]
          and _digest(sampling["descriptor"]) == sampling["expected_descriptor_sha256"],
          "independent complete sampling or descriptor canonical pin differs")

    _keys(candidate_inputs, _CANDIDATE_FIELDS, "six original candidate byte inputs")
    _keys(expected_candidate_pin, _CANDIDATE_PIN_FIELDS, "twelve independent candidate pins")
    pins = copy(expected_candidate_pin, MAX_RECORD_BYTES)
    for key in _CANDIDATE_PIN_FIELDS - {"candidate_cid", "graph_cid", "raw_bytes"}:
        _sha(pins[key], key)
    _need(type(pins["raw_bytes"]) is int and 1 <= pins["raw_bytes"] <= MAX_RAW_BYTES,
          "bounded independent raw byte length required")
    for key in ("candidate_cid", "graph_cid"):
        _need(type(pins[key]) is str and 1 <= len(pins[key]) <= 2048,
              "bounded independent candidate/graph CID required")
    originals, decoded, review_bytes = {}, {}, 0
    for key in sorted(_CANDIDATE_FIELDS):
        maximum = MAX_RAW_BYTES if key == "raw_html" else MAX_SAMPLING_BYTES if key == "sampling_report_raw" else MAX_RECORD_BYTES
        originals[key] = raw(candidate_inputs[key], maximum, key)
        review_bytes += len(originals[key])
        _need(_raw_sha(originals[key]) == pins[_TRANSPORT_PINS[key]],
              "independent original candidate transport pin differs: " + key)
        if key != "raw_html":
            decoded[key] = _decode(originals[key], maximum)
    _need(originals["request_raw"] == replay["request_raw"]
          and originals["raw_html"] == replay["raw_html"]
          and len(originals["raw_html"]) == pins["raw_bytes"]
          and decoded["request_raw"] == request,
          "candidate and binding require exactly the same original request/HTML bytes")
    _need(decoded["sampling_report_raw"] == replay["bundle"]["sampling_report"]
          and decoded["descriptor_raw"] == sampling["descriptor"]
          and _digest(decoded["sampling_report_raw"], MAX_SAMPLING_BYTES)
          == pins["sampling_report_full_canonical_sha256"] == sampling["expected_sampling_report_sha256"]
          and _digest(decoded["descriptor_raw"]) == pins["descriptor_full_canonical_sha256"]
          == sampling["expected_descriptor_sha256"],
          "complete decoded source sampling/descriptor correspondence differs")
    _need(decoded["candidate_raw"] == checked_binding["candidate"]
          and decoded["report_raw"] == checked_binding["definition_report"],
          "complete decoded candidate/report differs from the independently pinned binding")

    _need(type(context_inputs) is list and type(expected_context_population) is list
          and 1 <= len(context_inputs) <= MAX_CONTEXT_OCCURRENCES
          and len(context_inputs) == len(expected_context_population),
          "complete bounded ordered physical context population required")
    contexts, population = [], []
    for inputs, expected in zip(context_inputs, expected_context_population, strict=True):
        _keys(inputs, _CONTEXT_FIELDS, "original context byte inputs")
        _keys(expected, _CONTEXT_PIN_FIELDS, "independent context population row")
        pin = copy(expected, MAX_RECORD_BYTES)
        _sha(pin["packet_sha256"], "original context packet")
        identity = inputs["source_occurrence_cid"]
        _need(type(identity) is str and 1 <= len(identity) <= 2048
              and identity == pin["source_occurrence_cid"],
              "independent ordered physical occurrence identity differs")
        packet_raw = raw(inputs["packet_raw"], MAX_RECORD_BYTES, "context packet")
        _need(_raw_sha(packet_raw) == pin["packet_sha256"], "independent context packet pin differs")
        _decode(packet_raw, MAX_RECORD_BYTES)
        requests = copy(inputs["dependency_requests"], MAX_RECORD_BYTES)
        review_bytes += len(packet_raw) + len(_wire(requests, MAX_RECORD_BYTES))
        contexts.append({"source_occurrence_cid": identity, "packet_raw": packet_raw,
                         "dependency_requests": requests})
        population.append(pin)
    _need(review_bytes <= MAX_REVIEW_INPUT_BYTES, "complete existing V2 review input budget exceeded")
    manifest = copy(dependency_manifest, MAX_MANIFEST_BYTES)
    required = copy(required_dependency_ids, MAX_MANIFEST_BYTES)
    _need(type(required) is list and 1 <= len(required) <= 4096
          and all(type(item) is str and 1 <= len(item) <= 2048 for item in required)
          and len(set(required)) == len(required),
          "complete distinct ordered required dependency identities required")
    _need(manifest.get("manifest_sha256") == expected_manifest_sha256,
          "independent existing manifest pin differs")
    return {
        "binding_result": checked_binding, "review_subject": checked_subject,
        "binding_replay_inputs": replay, "candidate_inputs": originals,
        "expected_candidate_pin": pins, "context_inputs": contexts,
        "expected_context_population": population, "dependency_manifest": manifest,
        "required_dependency_ids": required,
    }


def _owners():
    from . import legal_source_sampling_definition_binding_v2 as binding
    from . import corpus_definition_review_v2 as review
    from . import corpus_contracts as contracts

    return binding, review, contracts


def _pins(owners):
    global _OPERATION_PINS
    _need(_raw_sha(_SELF_PATH.read_bytes()) == _SELF_PIN, "correspondence owner changed since import")
    pins = {str(_SELF_PATH): _SELF_PIN}
    pins.update({str(Path(module.__file__).resolve()): _raw_sha(Path(module.__file__).read_bytes())
                 for module in owners})
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "correspondence operation owners changed since first use")
    return pins


def _record_ref(record):
    return {"schema": record["schema"], "record_cid": record["record_cid"], "sha256": _digest(record)}


def prepare_definition_review_correspondence_v2(
    binding_result, review_subject, *, expected_binding_sha256, expected_subject_sha256,
    binding_replay_inputs, candidate_inputs, expected_candidate_pin, context_inputs,
    expected_context_population, dependency_manifest, expected_manifest_sha256,
    required_dependency_ids,
):
    """Replay an unsigned exact-identity link, preserving all open declarations.

    Expected pins are independently supplied commitments, not authenticated by
    this function. Report transport must remain the transport captured by the
    existing candidate. No original bytes, manifest or subject are rewritten.
    """
    snapshot = _preflight(
        binding_result, review_subject, expected_binding_sha256, expected_subject_sha256,
        binding_replay_inputs, candidate_inputs, expected_candidate_pin, context_inputs,
        expected_context_population, dependency_manifest, expected_manifest_sha256,
        required_dependency_ids,
    )
    token = _snapshot_pin(snapshot)
    owners = _owners()
    binding, review, contracts = owners
    producers = _pins(owners)

    def fence():
        _need(_snapshot_pin(snapshot) == token, "detached correspondence inputs changed during replay")
        _need(_pins(owners) == producers, "correspondence producers changed during replay")

    fence()
    replay = snapshot["binding_replay_inputs"]
    checked = binding.validate_definition_binding_v2(
        snapshot["binding_result"], replay["request_raw"], replay["bundle"],
        replay["responses"], replay["raw_html"], expected_binding_sha256=expected_binding_sha256,
        expected_request_sha256=replay["expected_request_sha256"],
        expected_bundle_sha256=replay["expected_bundle_sha256"],
        expected_response_sha256s=replay["expected_response_sha256s"],
        **replay["sampling_replay_inputs"],
    )
    fence()
    _need(_decode(snapshot["candidate_inputs"]["candidate_raw"], MAX_RECORD_BYTES) == checked["candidate"]
          and _decode(snapshot["candidate_inputs"]["report_raw"], MAX_RECORD_BYTES) == checked["definition_report"],
          "complete original candidate/report differs from regenerated binding companions")
    evidence = {key: snapshot[key] for key in (
        "candidate_inputs", "expected_candidate_pin", "context_inputs", "expected_context_population",
    )}
    preparation = review.prepare_definition_review_evidence_v2(**evidence)
    fence()
    subject = review.build_definition_review_subject_v2(
        preparation, snapshot["dependency_manifest"], **evidence,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=snapshot["required_dependency_ids"],
    )
    fence()
    _need(_wire(subject, MAX_RECORD_BYTES, review_json=True)
          == _wire(snapshot["review_subject"], MAX_RECORD_BYTES, review_json=True)
          and _digest(subject, review_json=True) == expected_subject_sha256,
          "existing subject differs from exact independent regeneration")
    metadata, population = checked["binding"], checked["population"]
    source_roles = metadata["source_role_bindings"]
    report = checked["definition_report"]
    _need(preparation["source_occurrences"] == checked["candidate"]["source_occurrences"]
          == report["source_occurrences"]
          and preparation["source_bindings"] == checked["candidate"]["source_bindings"]
          == report["source_bindings"]
          and [{key: value for key, value in row.items() if key != "subject_refs"}
               for row in source_roles] == report["source_bindings"],
          "complete original role/occurrence correspondence differs")
    occurrence_ids = [row["record_cid"] for row in preparation["source_occurrences"]]
    _need(len(occurrence_ids) == len(set(occurrence_ids))
          and {row["source_occurrence_cid"] for row in source_roles} == set(occurrence_ids)
          and [row["source_occurrence_cid"] for row in preparation["contexts"]] == occurrence_ids,
          "every exact physical occurrence needs its complete roles and context")
    links = []
    for occurrence, context in zip(preparation["source_occurrences"], preparation["contexts"], strict=True):
        links.append({
            "occurrence_ref": _record_ref(occurrence), "packet_id": context["packet_id"],
            "packet_sha256": context["packet_sha256"],
            "packet_canonical_sha256": context["packet_canonical_sha256"],
            "source_role_bindings": [row for row in source_roles
                                     if row["source_occurrence_cid"] == occurrence["record_cid"]],
        })
    _need(len(preparation["context_slot_ids"]) <= MAX_CONTEXT_OBLIGATIONS,
          "complete existing context obligation bound exceeded")
    all_producers = dict(producers)
    for pins in (metadata["producer_pins"], preparation["producer_pins"], preparation["native_producer_pins"]):
        for path, digest in pins.items():
            _need(path not in all_producers or all_producers[path] == digest,
                  "existing producer observations disagree")
            all_producers[path] = digest

    def producer_fence():
        fence()
        for path, digest in all_producers.items():
            _need(_raw_sha(Path(path).read_bytes()) == digest, "existing observed producer changed")

    producer_fence()
    authority = dict.fromkeys({*binding.FALSE_FLAGS, *review.FALSE_FLAGS,
        "binding_authenticated", "review_subject_authenticated", "exposure_authenticated",
        "exposure_correspondence_verified", "semantic_agreement_verified",
        "actual_legal_review_performed", "assessment_performed", "accepted_view_eligible",
    }, False)
    record = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "view": "candidate",
        "status": "unsigned_correspondence_only", "unsigned": True,
        "assessment_created": False, "source_declaration_status": metadata["status"],
        "binding_ref": {"schema": checked["schema"], "sha256": expected_binding_sha256,
                        "binding_record_cid": metadata["record_cid"]},
        "subject_ref": {"schema": subject["schema"], "sha256": expected_subject_sha256},
        "dependency_manifest_ref": {"schema": snapshot["dependency_manifest"]["schema"],
            "manifest_sha256": expected_manifest_sha256,
            "full_canonical_sha256": _digest(snapshot["dependency_manifest"], MAX_MANIFEST_BYTES)},
        "candidate_ref": metadata["candidate_ref"],
        "definition_report_ref": metadata["definition_report_ref"],
        "source_identity": metadata["source_identity"],
        "binding_input_pins": metadata["input_pins"],
        "original_input_pins": snapshot["expected_candidate_pin"],
        "expected_context_population": snapshot["expected_context_population"],
        "context_slot_ids": subject["context_slot_ids"],
        "population_ref": metadata["population_ref"],
        "population_subjects": population["subjects"], "population_counts": population["counts"],
        "population_subject_count": population["subject_count"],
        "response_count": population["response_count"],
        "selected_unit_roles": metadata["selected_unit_roles"],
        "required_subjects": metadata["required_subjects"],
        "source_role_bindings": source_roles,
        "occurrence_context_links": links, "source_correspondence_replayed": True,
        "producer_pins": all_producers,
        "hash_recipes": {
            "binding_envelope": "SHA256 of full compact canonical JSON including all companions",
            "review_subject": "existing legal_graph_review.digest of the complete unchanged plain subject",
            "original_inputs_and_contexts": "SHA256 of independently supplied exact original file bytes",
            "canonical_refs": "SHA256 of full canonical records including internal digests and CIDs",
            "report_transport_boundary": "exact transport captured by the existing candidate; reserialization is not normalized",
            "manifest": "existing internal manifest_sha256 plus full canonical commitment; original manifest unchanged",
            "correspondence": "SHA256 of the complete sealed correspondence including record_cid",
        },
        "authority": authority, "training_mask": 0, "evaluation_gold_mask": 0,
    })
    result = json.loads(_wire(record, MAX_RECORD_BYTES))
    producer_fence()
    return result


def definition_review_correspondence_sha256(correspondence):
    """Commit the complete sealed record; a self-computed pin grants no trust."""
    _need(type(correspondence) is dict and correspondence.get("schema") == SCHEMA,
          "complete correspondence schema required")
    return _digest(correspondence)


def validate_definition_review_correspondence_v2(
    correspondence, *args, expected_correspondence_sha256, **kwargs,
):
    """Check an independent whole-record pin, then regenerate the entire link."""
    _sha(expected_correspondence_sha256, "complete sealed correspondence")
    offered = _wire(correspondence, MAX_RECORD_BYTES)
    _need(_raw_sha(offered) == expected_correspondence_sha256,
          "independent complete correspondence pin differs")
    expected = prepare_definition_review_correspondence_v2(*args, **kwargs)
    _need(offered == _wire(expected, MAX_RECORD_BYTES),
          "correspondence differs from complete independent regeneration")
    return expected


def prepare_contextual_definition_review_correspondence_v2(
    binding_result, review_subject, *, expected_binding_sha256,
    expected_subject_sha256, contextual_replay_inputs, candidate_inputs,
    expected_candidate_pin, context_inputs, expected_context_population,
    dependency_manifest, expected_manifest_sha256, required_dependency_ids,
):
    """Link distinct contextual declarations without changing the review domain."""
    from . import legal_source_sampling_context_definition_review_v2 as contextual

    return contextual.prepare(
        binding_result, review_subject, expected_binding_sha256=expected_binding_sha256,
        expected_subject_sha256=expected_subject_sha256,
        contextual_replay_inputs=contextual_replay_inputs,
        candidate_inputs=candidate_inputs, expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs, expected_context_population=expected_context_population,
        dependency_manifest=dependency_manifest, expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=required_dependency_ids,
    )


def contextual_definition_review_correspondence_sha256(correspondence):
    """Hash the complete distinct contextual envelope, granting no authority."""
    from . import legal_source_sampling_context_definition_review_v2 as contextual

    return contextual.correspondence_sha256(correspondence)


def validate_contextual_definition_review_correspondence_v2(
    correspondence, *args, expected_correspondence_sha256, **kwargs,
):
    """Independently pin and regenerate the complete contextual correspondence."""
    from . import legal_source_sampling_context_definition_review_v2 as contextual

    return contextual.validate(
        correspondence, *args,
        expected_correspondence_sha256=expected_correspondence_sha256, **kwargs,
    )


__all__ = [
    "prepare_definition_review_correspondence_v2",
    "validate_definition_review_correspondence_v2",
    "definition_review_correspondence_sha256",
    "prepare_contextual_definition_review_correspondence_v2",
    "contextual_definition_review_correspondence_sha256",
    "validate_contextual_definition_review_correspondence_v2",
]
