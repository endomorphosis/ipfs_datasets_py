"""Unsigned exact-use nominations beside independently replayed definitions.

This companion does not extend an existing signature, select an interpretation,
substitute a predicate, resolve a definition, or grant semantic authority. The
complete norm, definition and optional review inputs remain required for replay.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_interpretation_review_v1 as norm

SCHEMA = "legal-norm-definition-evidence/v1"
REQUEST_SCHEMA = "legal-norm-definition-evidence-request/v1"
PROFILE = "unsigned-source-linked-term-definition-nominations/v1"
MAX_ALTERNATIVES = 16
MAX_LINKS = 128
MAX_REQUEST_BYTES = 1024**2
MAX_INPUT_BYTES = norm.MAX_INPUT_BYTES
# Full norm inputs plus independent definition endpoints repeat their shared
# context. This explicit aggregate profile keeps every copy and its fences;
# it does not expand the unchanged endpoint, byte, depth or authority limits.
MAX_INPUT_NODES = 4_000_000
MAX_OUTPUT_BYTES = norm.MAX_BYTES
FALSE_FLAGS = dict(norm.FALSE_FLAGS, definition_applicability_verified=False,
                  definition_substitution_verified=False,
                  original_signatures_cover_companion=False,
                  external_definition_resolution_verified=False)
_NORM_FIELDS = {"correspondence", "expected_correspondence_sha256",
                "correspondence_inputs", "context_inputs"}
_ENDPOINT_FIELDS = {"alternative_id", "correspondence", "expected_correspondence_sha256",
                    "correspondence_inputs", "review_evidence"}
_CORRESPONDENCE_FIELDS = {
    "binding_result", "review_subject", "expected_binding_sha256", "expected_subject_sha256",
    "contextual_replay_inputs", "candidate_inputs", "expected_candidate_pin", "context_inputs",
    "expected_context_population", "dependency_manifest", "expected_manifest_sha256",
    "required_dependency_ids",
}
_ASSESSMENT_FIELDS = {
    "subject", "registry", "policy", "reviews", "dependency_manifest", "candidate_inputs",
    "expected_candidate_pin", "context_inputs", "expected_context_population",
    "expected_subject_sha256", "expected_registry_sha256", "expected_policy_sha256",
    "expected_reviews_sha256", "expected_manifest_sha256", "at_time_utc",
    "observed_artifact_sha256s", "observed_pins", "evidence_artifacts",
}
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_NORM_PATH = Path(norm.__file__).resolve()
_NORM_PIN = hashlib.sha256(_NORM_PATH.read_bytes()).hexdigest()
_OPERATION_PINS = None
_need, _keys, _sha = norm._need, norm._keys, norm._sha


def _wire(value):
    return norm.correspondence_owner._wire(value, MAX_OUTPUT_BYTES)


def norm_definition_evidence_sha256(value):
    """Hash full canonical companion bytes, not an embedded assessment hash."""
    return hashlib.sha256(_wire(value)).hexdigest()


def _same(left, right):
    return _wire(left) == _wire(right)


def _same_inputs(left, right):
    return norm._snapshot(left)[1] == norm._snapshot(right)[1]


def _snapshot(value):
    return norm._snapshot(value, max_nodes=MAX_INPUT_NODES)


def _pure_pins():
    actual = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (_SELF_PATH, _NORM_PATH)}
    _need(actual == {str(_SELF_PATH): _SELF_PIN, str(_NORM_PATH): _NORM_PIN},
          "norm definition evidence pure owners changed since import")
    return actual


def _parse(raw, expected_sha256):
    _sha(expected_sha256, "definition nomination request")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          "bounded exact definition nomination request bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256,
          "independent definition nomination request pin differs")

    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate definition nomination request key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("finite definition nomination request JSON required")

    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                             parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free definition nomination request required") from error
    _keys(request, {"schema", "interpretation_status", "norm_preparation_sha256", "links"},
          "definition nomination request")
    _need(request["schema"] == REQUEST_SCHEMA and request["interpretation_status"]
          == "authored_unreviewed_definition_nomination", "distinct unsigned nomination request required")
    _sha(request["norm_preparation_sha256"], "request norm preparation")
    links = request["links"]
    _need(type(links) is list and 0 < len(links) <= MAX_LINKS,
          "bounded nonempty exact term-use nominations required")
    seen = set()
    for row in links:
        _keys(row, {"alternative_id", "target", "source_paths", "nomination_sha256", "rationale"},
              "exact term-use nomination")
        _identifier(row["alternative_id"])
        _need(type(row["target"]) is dict, "exact typed target required")
        _need(type(row["source_paths"]) is list and 0 < len(row["source_paths"]) <= 2048
              and all(type(path) is str for path in row["source_paths"]),
              "nonempty complete typed source paths required")
        _sha(row["nomination_sha256"], "whole context nomination row")
        _need(type(row["rationale"]) is str and 0 < len(row["rationale"]) <= 8192,
              "bounded explicit nomination rationale required")
        identity = norm_definition_evidence_sha256({key: value for key, value in row.items()
                                                  if key != "rationale"})
        _need(identity not in seen, "duplicate exact definition nomination forbidden")
        seen.add(identity)
    _wire(request)
    return request


def _identifier(value):
    _need(type(value) is str and 0 < len(value) <= 256 and "\x00" not in value,
          "bounded explicit definition alternative identity required")


def _preflight(original, expected_norm_preparation_sha256, expected_request_sha256):
    _pure_pins()
    _sha(expected_norm_preparation_sha256, "norm preparation")
    detached, commitment = _snapshot(original)
    _need(norm.norm_review_sha256(detached["norm_preparation"]) == expected_norm_preparation_sha256,
          "independent complete norm preparation pin differs")
    request = _parse(detached["request_raw"], expected_request_sha256)
    _need(request["norm_preparation_sha256"] == expected_norm_preparation_sha256,
          "request names another norm preparation")
    inputs = detached["norm_inputs"]
    _keys(inputs, _NORM_FIELDS, "complete original norm review inputs")
    _keys(inputs["correspondence_inputs"], norm._REPLAY_FIELDS, "complete norm correspondence inputs")
    _need(type(inputs["context_inputs"]) is dict, "shared full contextual evidence required")
    _keys(inputs["context_inputs"], {"packet", "sources", "attachments", "expected_context_sha256",
                                    "expected_attachments_sha256", "limits"}, "norm context replay")
    norm._preflight_correspondence(inputs["correspondence_inputs"])
    _need(norm.norm_review_sha256(inputs["correspondence"]) == inputs["expected_correspondence_sha256"],
          "independent norm correspondence pin differs before operation imports")
    alternatives = detached["definitions"]
    _need(type(alternatives) is list and 0 < len(alternatives) <= MAX_ALTERNATIVES,
          "bounded nonempty definition alternative population required")
    ids = []
    # These two modules contain pure transport checks. Their operation owners
    # remain unloaded until every complete endpoint has passed preflight.
    from . import legal_source_sampling_context_definition_review_v2 as contextual
    for endpoint in alternatives:
        _keys(endpoint, _ENDPOINT_FIELDS, "complete definition endpoint")
        _identifier(endpoint["alternative_id"])
        ids.append(endpoint["alternative_id"])
        _sha(endpoint["expected_correspondence_sha256"], "definition correspondence")
        _need(contextual.correspondence_sha256(endpoint["correspondence"])
              == endpoint["expected_correspondence_sha256"], "independent definition correspondence pin differs")
        replay = endpoint["correspondence_inputs"]
        _keys(replay, _CORRESPONDENCE_FIELDS, "complete contextual correspondence replay")
        contextual._preflight(**replay)
        shared = replay["contextual_replay_inputs"]
        for left, right in (("context", "packet"), ("sources", "sources"), ("attachments", "attachments"),
                            ("expected_context_sha256", "expected_context_sha256"),
                            ("expected_attachments_sha256", "expected_attachments_sha256")):
            _need(_same_inputs(shared[left], inputs["context_inputs"][right]),
                  "definition and norm require the exact same complete context inputs")
        evidence = endpoint["review_evidence"]
        if evidence is not None:
            _keys(evidence, {"assessment", "expected_assessment_sha256", "assessment_inputs"},
                  "independently replayed definition assessment")
            _sha(evidence["expected_assessment_sha256"], "definition assessment")
            _need(norm_definition_evidence_sha256(evidence["assessment"]) == evidence["expected_assessment_sha256"],
                  "independent complete definition assessment pin differs")
            assessment = evidence["assessment_inputs"]
            _keys(assessment, _ASSESSMENT_FIELDS, "complete definition assessment replay")
            for key in ("candidate_inputs", "expected_candidate_pin", "context_inputs",
                        "expected_context_population", "dependency_manifest", "expected_manifest_sha256",
                        "expected_subject_sha256"):
                _need(_same_inputs(assessment[key], replay[key]), "assessment names another definition endpoint")
            _need(_same_inputs(assessment["subject"], replay["review_subject"]),
                  "assessment names another exact definition subject")
    _need(len(ids) == len(set(ids)), "duplicate definition alternative identities forbidden")
    _need(set(ids) == {row["alternative_id"] for row in request["links"]},
          "every supplied definition alternative must be referenced exactly by identity")
    _pure_pins()
    return detached, commitment, request


def _owners():
    from . import legal_source_sampling_context_definition_review_v2 as contextual
    from . import corpus_definition_review_v2 as definition_review
    return contextual, definition_review


def _merge(result, pins):
    for path, pin in pins.items():
        _need(path not in result or result[path] == pin, "definition evidence producer observations disagree")
        result[path] = pin


def _pins(owners):
    global _OPERATION_PINS
    contextual, definition_review = owners
    result = _pure_pins()
    for pins in (
        norm._pins(norm._owners()),
        contextual._pins(contextual._owners()),
        contextual.base._pins(contextual.base._owners()),
        contextual.context_binding._pins(contextual.context_binding._owners()),
        definition_review._pins(definition_review._owners()),
    ):
        _merge(result, pins)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(result)
    _need(result == _OPERATION_PINS, "definition evidence producers changed since first use")
    return result


def _observe(pins, observed):
    # Only paths obtained from actual loaded owners above can be accepted. No
    # caller-provided producer path is ever opened by this companion.
    _need(type(observed) is dict and all(path in pins and pins[path] == pin
                                      for path, pin in observed.items()),
          "replayed definition evidence producer outside known exact owner closure")


def _at(value, path):
    return norm.correspondence_owner._at(value, path)


def _endpoint_summary(endpoint, checked, review_status):
    replay = endpoint["correspondence_inputs"]
    candidate = replay["binding_result"]["base_binding"]["candidate"]
    companion = checked["contextual_correspondence"]
    return {
        "alternative_id": endpoint["alternative_id"],
        "correspondence_sha256": endpoint["expected_correspondence_sha256"],
        "binding_sha256": replay["expected_binding_sha256"],
        "subject_sha256": replay["expected_subject_sha256"],
        "candidate_pin": replay["expected_candidate_pin"],
        "candidate_cid": candidate["record_cid"], "family": candidate["family"],
        "source_identity": checked["definition_correspondence"]["source_identity"],
        "source_version": candidate["source_version"], "scope_record": candidate["scope_record"],
        "definition_record": candidate["definition_record"], "term_record": candidate["term_record"],
        "ast_record": candidate["ast_record"], "source_bindings": candidate["source_bindings"],
        "source_occurrences": candidate["source_occurrences"],
        "required_subjects": companion["required_subjects"],
        "required_support_nominations": companion["required_support_nominations"],
        "direct_response_refs": companion["direct_response_refs"],
        "related_target_responses": companion["related_target_responses"],
        "response_declarations": companion["response_declarations"],
        "context_slot_ids": checked["definition_correspondence"]["context_slot_ids"],
        "contextual_population_ref": companion["contextual_population_ref"],
        "contextual_population_counts": companion["contextual_population_counts"],
        "contextual_population_subject_count": companion["contextual_population_subject_count"],
        "contextual_population_response_count": companion["contextual_population_response_count"],
        "review_evidence": review_status,
    }


def _link(row, preparation, endpoint):
    correspondence = preparation["correspondence"]
    target = row["target"]
    matches = [item for item in correspondence["request"]["typed_rows"] if _same(item["target"], target)]
    _need(len(matches) == 1 and matches[0]["disposition"] == "source_linked"
          and target.get("kind") in {"variable", "predicate"},
          "exact source-linked variable or predicate target required")
    typed_row = matches[0]
    _need(_same(row["source_paths"], typed_row["source_paths"]),
          "complete ordered inverse source paths required for selected term use")
    source_rows = [source for source in correspondence["request"]["source_rows"]
                   if source["anchor_mapping"]["declaration_path"] in row["source_paths"]]
    _need([source["anchor_mapping"]["declaration_path"] for source in source_rows] == row["source_paths"]
          and all(any(_same(target, offered) for offered in source["targets"]) for source in source_rows),
          "selected term-use source anchors differ from exact proposed correspondence")
    typed_contexts = [item for item in correspondence["typed_context_inventory"] if _same(item["target"], target)]
    _need(len(typed_contexts) == 1, "exact binder and ancestry inventory required for term use")
    nominations = [item for item in preparation["context_evidence"]["nominations"]
                   if norm_definition_evidence_sha256(item) == row["nomination_sha256"]]
    _need(len(nominations) == 1, "whole selected norm context nomination row required")
    nomination_row = nominations[0]
    nomination = nomination_row["nomination"]
    target_source = preparation["context_evidence"]["target"]
    _need(nomination["target_bundle_sha256"] == target_source["bundle_sha256"]
          and _same(nomination["target_subject_ref"], target_source["subject_ref"]),
          "nomination targets another exact norm source occurrence")
    required = [item for item in endpoint["required_subjects"]
                if item["bundle_sha256"] == nomination["supporting_bundle_sha256"]
                and _same(item["subject_ref"], nomination["supporting_subject_ref"])]
    _need(len(required) == 1, "support must be an exact required definition subject")
    supports = [item for item in endpoint["required_support_nominations"]
                if _same(item["nomination"], nomination)]
    _need(len(supports) == 1 and supports[0]["nomination_sha256"] == nomination_row["nomination_sha256"],
          "exact definition-to-norm supporting nomination required")
    _need(_same(supports[0]["required_definition_roles"], required[0]["roles"]),
          "required definition support role population differs")
    return {"request_link": row, "typed_row": typed_row,
            "typed_node": _at(correspondence["relational_fragment"]["typed_expression"], target["typed_path"]),
            "typed_context": typed_contexts[0], "source_rows": source_rows,
            "norm_source_target": target_source, "nomination": nomination_row,
            "required_definition_subject": required[0], "definition_support": supports[0],
            "definition_term_ref": {"record_cid": endpoint["term_record"]["record_cid"],
                                    "sha256": norm_definition_evidence_sha256(endpoint["term_record"])},
            "definition_ast_ref": {"record_cid": endpoint["ast_record"]["record_cid"],
                                   "sha256": norm_definition_evidence_sha256(endpoint["ast_record"])},
            "status": "source_linked_definition_nomination_unreviewed",
            "governing_definition_use": None, "authority": dict(FALSE_FLAGS)}


def prepare_norm_definition_evidence_v1(norm_preparation, request_raw, *,
        expected_norm_preparation_sha256, expected_request_sha256, norm_inputs, definitions):
    """Replay existing owners and preserve unsigned exact-use alternatives."""
    original = dict(norm_preparation=norm_preparation, request_raw=request_raw,
                    norm_inputs=norm_inputs, definitions=definitions)
    detached, commitment, request = _preflight(original, expected_norm_preparation_sha256,
                                              expected_request_sha256)
    owners = _owners()
    pins = _pins(owners)

    def fence():
        _need(_snapshot(original)[1] == commitment and _snapshot(detached)[1] == commitment,
              "norm definition evidence inputs changed during replay")
        _need(_pins(owners) == pins, "norm definition evidence producers changed during replay")

    fence()
    preparation = norm.prepare_norm_review_evidence_v1(**detached["norm_inputs"])
    _need(_same(preparation, detached["norm_preparation"]), "norm preparation differs from complete regeneration")
    _observe(pins, preparation["producer_pins"])
    fence()
    endpoints = []
    for endpoint in detached["definitions"]:
        checked = owners[0].validate(endpoint["correspondence"],
            expected_correspondence_sha256=endpoint["expected_correspondence_sha256"],
            **endpoint["correspondence_inputs"])
        for item in (checked["definition_correspondence"], checked["contextual_correspondence"]):
            _observe(pins, item["producer_pins"])
        fence()
        evidence = endpoint["review_evidence"]
        review_status = {"status": "not_supplied", "assessment": None, "assessment_sha256": None,
                         "covers_new_companion": False, "covers_contextual_companion": False}
        if evidence is not None:
            assessment = owners[1].validate_definition_review_assessment_v2(
                evidence["assessment"], **evidence["assessment_inputs"])
            _need(norm_definition_evidence_sha256(assessment) == evidence["expected_assessment_sha256"],
                  "replayed complete definition assessment pin differs")
            review_status.update(status="independently_replayed_existing_assessment", assessment=assessment,
                                 assessment_sha256=evidence["expected_assessment_sha256"])
            fence()
        endpoints.append(_endpoint_summary(endpoint, checked, review_status))
    by_id = {endpoint["alternative_id"]: endpoint for endpoint in endpoints}
    links = [_link(row, preparation, by_id[row["alternative_id"]]) for row in request["links"]]
    report = {
        "schema": SCHEMA, "profile": PROFILE, "status": "unsigned_exact_term_use_evidence",
        "request": request, "request_raw_sha256": expected_request_sha256,
        "norm_preparation_sha256": expected_norm_preparation_sha256,
        "norm_correspondence_sha256": preparation["correspondence_sha256"],
        "norm_scope_id": preparation["scope_id"], "norm_ast_sha256": preparation["ast_sha256"],
        "norm_native_ast_sha256": preparation["native_ast_sha256"],
        "source_context": preparation["context_evidence"],
        "original_unresolved": preparation["correspondence"]["retained_unresolved"],
        "original_context_slots": preparation["correspondence"]["source_scope"]["source_context_packet"]["dependency_slots"],
        "norm_obligations": preparation["obligations"],
        "definitions": endpoints, "links": links,
        "counts": {"alternatives": len(endpoints), "links": len(links),
                   "distinct_typed_uses": len({link["request_link"]["target"]["typed_path"] for link in links}),
                   "supplied_definition_assessments": sum(item["review_evidence"]["assessment"] is not None for item in endpoints)},
        "external_complete_inputs_required": True, "original_norm_preparation_unchanged": True,
        "original_definition_subjects_unchanged": True, "original_signatures_cover_companion": False,
        "all_norm_term_uses_enumerated": False, "selected_interpretation": None,
        "governing_definition_use": None, "native_ast_rewritten": False,
        "producer_pins": pins, "authority": dict(FALSE_FLAGS),
        "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": [
            "Exact source and syntax nominations do not establish a governing definition or legal meaning.",
            "A source context nomination can identify required scope evidence without proving applicability.",
            "Definition assessment authentication remains scoped to its unchanged original subject.",
            "Alternative definitions and repeated term occurrences remain distinct; this is not an exhaustive term resolver.",
            "No predicate alias, substitution, new signature, solver, Lean build, training or admission is performed.",
        ],
    }
    raw = _wire(report)
    fence()
    return json.loads(raw)


def validate_norm_definition_evidence_v1(report, *args, expected_report_sha256, **kwargs):
    """Require an independent complete commitment and exact owner regeneration."""
    _sha(expected_report_sha256, "complete norm definition evidence")
    offered = _wire(report)
    _need(hashlib.sha256(offered).hexdigest() == expected_report_sha256,
          "independent complete norm definition evidence pin differs")
    expected = prepare_norm_definition_evidence_v1(*args, **kwargs)
    _need(offered == _wire(expected), "norm definition evidence differs from complete regeneration")
    return expected
