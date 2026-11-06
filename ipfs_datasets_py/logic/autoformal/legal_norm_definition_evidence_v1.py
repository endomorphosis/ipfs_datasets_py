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


# The decoded-parent companion has its own request and replay domain. The
# original HTML/contextual profile above is intentionally unchanged.
PARENT_SCHEMA = "legal-parent-norm-definition-evidence/v1"
PARENT_REQUEST_SCHEMA = "legal-parent-norm-definition-evidence-request/v1"
PARENT_PROFILE = "unsigned-parent-literal-term-definition-nominations/v1"
PARENT_MAX_INPUT_NODES = 1_500_000
_PARENT_DEFINITION_PINS = None
_PARENT_NORM_FIELDS = {"correspondence", "expected_correspondence_sha256", "correspondence_inputs"}
_PARENT_ENDPOINT_FIELDS = {"alternative_id", "preparation", "expected_preparation_sha256", "preparation_inputs"}
_PARENT_PREPARATION_INPUT_FIELDS = {
    "candidate_inputs", "expected_candidate_pin", "parent_inputs", "context_inputs", "expected_context_population",
}


def _parent_definition_snapshot(value):
    """Use the existing parent snapshot/fingerprint's matching finite profile."""
    return norm._snapshot(value, max_nodes=PARENT_MAX_INPUT_NODES)


def _parent_definition_parse(raw, expected_sha256):
    _sha(expected_sha256, "parent definition nomination request")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          "bounded exact parent nomination request bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256,
          "independent parent nomination request pin differs")

    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate parent nomination request key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("finite parent nomination JSON required")

    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded duplicate-free parent nomination request required") from error
    _keys(request, {"schema", "profile", "interpretation_status", "norm_preparation_sha256", "links"},
          "parent definition nomination request")
    _need(request["schema"] == PARENT_REQUEST_SCHEMA and request["profile"] == PARENT_PROFILE
          and request["interpretation_status"] == "authored_unreviewed_definition_nomination",
          "distinct unsigned parent nomination request required")
    _sha(request["norm_preparation_sha256"], "request parent norm preparation")
    _need(type(request["links"]) is list and 0 < len(request["links"]) <= MAX_LINKS,
          "bounded nonempty parent term-use nominations required")
    seen = set()
    for row in request["links"]:
        _keys(row, {"alternative_id", "target", "source_paths", "definition_term_ref", "definition_ast_ref", "rationale"},
              "parent exact term-use nomination")
        _identifier(row["alternative_id"])
        _need(type(row["target"]) is dict, "complete exact typed parent target required")
        _need(type(row["source_paths"]) is list and 0 < len(row["source_paths"]) <= 2048
              and all(type(path) is str for path in row["source_paths"]),
              "complete ordered parent inverse source paths required")
        for key in ("definition_term_ref", "definition_ast_ref"):
            _keys(row[key], {"record_cid", "sha256"}, "whole definition companion reference")
            _need(type(row[key]["record_cid"]) is str and bool(row[key]["record_cid"]),
                  "explicit whole definition companion CID required")
            _sha(row[key]["sha256"], "whole definition companion")
        _need(type(row["rationale"]) is str and 0 < len(row["rationale"]) <= 8192,
              "bounded authored parent nomination rationale required")
        identity = norm_definition_evidence_sha256({key: value for key, value in row.items() if key != "rationale"})
        _need(identity not in seen, "duplicate exact parent definition nomination forbidden")
        seen.add(identity)
    _wire(request)
    return request


def _parent_definition_preflight(original):
    """Check every independent report/raw pin before discovering replay owners."""
    _pure_pins()
    detached, commitment = _parent_definition_snapshot(original)
    _sha(detached["expected_norm_preparation_sha256"], "complete parent norm preparation")
    preparation = detached["norm_preparation"]
    _need(type(preparation) is dict and preparation.get("schema") == norm.PARENT_PREPARATION_SCHEMA
          and preparation.get("profile") == norm.PARENT_REVIEW_PROFILE,
          "explicit parent norm review preparation required")
    _need(norm_definition_evidence_sha256(preparation) == detached["expected_norm_preparation_sha256"],
          "independent complete parent norm preparation pin differs")
    request = _parent_definition_parse(detached["request_raw"], detached["expected_request_sha256"])
    _need(request["norm_preparation_sha256"] == detached["expected_norm_preparation_sha256"],
          "parent request names another norm preparation")
    _keys(detached["norm_inputs"], _PARENT_NORM_FIELDS, "complete parent norm review inputs")
    inputs = detached["norm_inputs"]
    _sha(inputs["expected_correspondence_sha256"], "parent norm correspondence")
    _need(norm.norm_review_sha256(inputs["correspondence"]) == inputs["expected_correspondence_sha256"],
          "independent parent norm correspondence pin differs")
    alternatives = detached["definitions"]
    _need(type(alternatives) is list and 0 < len(alternatives) <= MAX_ALTERNATIVES,
          "bounded nonempty parent definition alternatives required")
    ids = []
    for endpoint in alternatives:
        _keys(endpoint, _PARENT_ENDPOINT_FIELDS, "complete parent definition endpoint")
        _identifier(endpoint["alternative_id"])
        ids.append(endpoint["alternative_id"])
        _sha(endpoint["expected_preparation_sha256"], "complete parent definition preparation")
        _need(norm_definition_evidence_sha256(endpoint["preparation"]) == endpoint["expected_preparation_sha256"],
              "independent complete parent definition preparation pin differs")
        replay = endpoint["preparation_inputs"]
        _need(type(replay) is dict and set(replay) in
              (_PARENT_PREPARATION_INPUT_FIELDS, _PARENT_PREPARATION_INPUT_FIELDS | {"parent_limits"}),
              "complete closed parent definition preparation inputs required")
        raw_inputs, pins = replay["candidate_inputs"], replay["expected_candidate_pin"]
        _keys(raw_inputs, {"candidate_raw", "report_raw", "request_raw"}, "original parent definition bytes")
        _need(type(pins) is dict, "independent parent candidate pin population required")
        for name, raw in raw_inputs.items():
            key = name.removesuffix("_raw") + "_sha256"
            _sha(pins.get(key), "original parent definition " + key)
            _need(type(raw) is bytes and 0 < len(raw) <= MAX_OUTPUT_BYTES
                  and hashlib.sha256(raw).hexdigest() == pins[key],
                  "independent original parent definition byte pin differs")
    _need(len(ids) == len(set(ids)), "duplicate parent definition alternative identities forbidden")
    _need(set(ids) == {row["alternative_id"] for row in request["links"]},
          "every supplied parent definition alternative must be referenced")
    if detached["validating"]:
        _sha(detached["expected_report_sha256"], "complete parent nomination report")
        _need(norm_definition_evidence_sha256(detached["offered"]) == detached["expected_report_sha256"],
              "independent complete parent nomination report pin differs")
        _need(type(detached["offered"]) is dict and detached["offered"].get("schema") == PARENT_SCHEMA
              and detached["offered"].get("profile") == PARENT_PROFILE,
              "explicit parent nomination report profile required")
    # Existing pure endpoint parsers bound original transport before physical
    # replay. They never substitute a saved success flag for genuine replay.
    from . import corpus_definition_review_v2 as review
    parsed = {"request": request,
        "norm": norm._parent_review_preflight(inputs["correspondence"], inputs["correspondence_inputs"]),
        "definitions": []}
    for endpoint in alternatives:
        replay = endpoint["preparation_inputs"]
        _need(endpoint["preparation"].get("schema") == review.PARENT_PREPARATION_SCHEMA
              and endpoint["preparation"].get("review_profile") == review.PARENT_PROFILE,
              "explicit parent definition review preparation required")
        review._parent_preflight(**replay, **({"parent_limits": None} if "parent_limits" not in replay else {}))
        candidate = review.contracts.load_record_bytes(replay["candidate_inputs"]["candidate_raw"],
            expected_sha256=replay["expected_candidate_pin"]["candidate_sha256"])
        parsed["definitions"].append(candidate)
    _pure_pins()
    return detached, commitment, parsed


def _parent_definition_owners():
    from . import corpus_definition_review_v2, legal_producer_lineage, legal_source_norm_scope_v1
    return corpus_definition_review_v2, legal_producer_lineage, legal_source_norm_scope_v1


def _parent_definition_pins(owners):
    global _PARENT_DEFINITION_PINS
    result = _pure_pins()
    review, _, _ = owners
    for observed in (norm._parent_review_pins(norm._parent_review_owners()), review._parent_pins(review._owners())):
        _merge(result, observed)
    if _PARENT_DEFINITION_PINS is None:
        _PARENT_DEFINITION_PINS = dict(result)
    _need(result == _PARENT_DEFINITION_PINS, "parent nomination producers changed since first use")
    return result


def _parent_definition_file_plan(replay, lineage):
    """Project witnesses only after genuine original-parent replay succeeds."""
    manifest = replay["lineage_inputs"]["witness_manifest"]
    sources = [(replay["parent_text_views_inputs"]["parent_descriptor"], lineage.MAX_FILE_BYTES)]
    sources += [(row["descriptor"], lineage.MAX_FILE_BYTES) for row in manifest["parents"]]
    for report in manifest["reports"]:
        sources.extend(((report, lineage.MAX_REPORT_BYTES), (report["origin"]["container"], lineage.MAX_REPORT_BYTES)))
    for report in replay["provenance_reports"]:
        for pin in report["catalog_source_pins"]:
            sources.append(({"local_path": pin["path"], "sha256": pin["source_sha256"],
                             "bytes": Path(pin["path"]).lstat().st_size}, lineage.provenance.MAX_SOURCE_BYTES))
    result = {}
    for source, maximum in sources:
        descriptor = {key: source[key] for key in ("local_path", "sha256", "bytes")}
        previous = result.get(descriptor["local_path"])
        _need(previous is None or _same(previous["descriptor"], descriptor),
              "parent nomination physical file descriptors disagree")
        result[descriptor["local_path"]] = {"descriptor": descriptor,
            "maximum": maximum if previous is None else min(maximum, previous["maximum"])}
    _need(bool(result) and len(result) <= 1 + lineage.MAX_PARENT_FILES
          + 2 * lineage.MAX_REPORTS + lineage.MAX_RECORDS * lineage.provenance.MAX_SOURCES,
          "complete bounded parent nomination physical file population required")
    return [result[path] for path in sorted(result)]


def _parent_definition_file_witness(plan, lineage):
    result = []
    for item in plan:
        with lineage._opened(item["descriptor"], item["maximum"]) as stream:
            value = lineage.os.fstat(stream.fileno())
            result.append([value.st_dev, value.st_ino, value.st_mode, value.st_size,
                           value.st_mtime_ns, value.st_ctime_ns])
    return result


def _parent_definition_callbacks(owners):
    review, lineage, source = owners
    base = norm.correspondence_owner
    functions = (norm.validate_parent_norm_review_evidence_v1, norm.prepare_parent_norm_review_evidence_v1,
        norm._parent_review_operation, norm._parent_review_preflight, norm._parent_review_pins,
        norm._parent_review_fingerprint, norm._parent_review_pure_wire, norm._snapshot,
        base.validate_norm_scope_correspondence_v2, base.prepare_norm_scope_correspondence_v2,
        base._parent_correspondence_pins, base._parent_correspondence_snapshot, base._parse, base._wire, base._scalar_wire,
        review.validate_parent_definition_review_evidence_v1, review.prepare_parent_definition_review_evidence_v1,
        review._parent_preflight, review._parent_pins, review._owners,
        review.adapter.validate_parent_definition_only_candidate_v1,
        review.contracts.load_record_bytes, review.contracts.validate_record, review.contracts.seal_record,
        source._parent_finish, source._parent_serialized_fence,
        lineage._opened, lineage._opened.__wrapped__, lineage._need,
        lineage.os.open, lineage.os.fdopen, lineage.os.fstat,
        _parent_definition_snapshot, _parent_definition_parse, _parent_definition_preflight,
        _parent_definition_owners, _parent_definition_pins, _parent_definition_file_plan,
        _parent_definition_file_witness, _parent_definition_callbacks, _parent_definition_runtime,
        _parent_definition_link, _parent_definition_serialized_fence, _parent_definition_operation,
        prepare_parent_norm_definition_evidence_v1, validate_parent_norm_definition_evidence_v1,
        _wire, _same, _pure_pins, norm_definition_evidence_sha256, _identifier, _observe, _at, _merge,
        json.loads, json.dumps)
    return tuple((function, getattr(function, "__code__", None),
                  id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
                 for function in functions)


def _parent_definition_runtime(owners):
    review, lineage, _ = owners
    return {"schema": PARENT_SCHEMA, "request_schema": PARENT_REQUEST_SCHEMA, "profile": PARENT_PROFILE,
        "authority": dict(FALSE_FLAGS), "norm_authority": dict(norm.FALSE_FLAGS),
        "definition_authority": dict(review.PARENT_FALSE_FLAGS),
        "limits": [MAX_ALTERNATIVES, MAX_LINKS, MAX_REQUEST_BYTES, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES,
                   PARENT_MAX_INPUT_NODES, norm.MAX_INPUT_BYTES, norm.MAX_BYTES],
        "norm_fields": sorted(_PARENT_NORM_FIELDS), "endpoint_fields": sorted(_PARENT_ENDPOINT_FIELDS),
        "preparation_fields": sorted(_PARENT_PREPARATION_INPUT_FIELDS),
        "parent_schema": norm.PARENT_PREPARATION_SCHEMA, "parent_profile": norm.PARENT_REVIEW_PROFILE,
        "definition_schema": review.PARENT_PREPARATION_SCHEMA, "definition_profile": review.PARENT_PROFILE,
        "definition_limits": [review.MAX_INPUT_BYTES, review.MAX_CONTEXT_OCCURRENCES, review.MAX_CONTEXT_OBLIGATIONS],
        "physical_limits": [lineage.MAX_FILE_BYTES, lineage.MAX_REPORT_BYTES, lineage.MAX_PARENT_FILES,
                            lineage.MAX_REPORTS, lineage.MAX_RECORDS, lineage.provenance.MAX_SOURCE_BYTES,
                            lineage.provenance.MAX_SOURCES]}


def _parent_definition_link(row, preparation, endpoint):
    correspondence, target = preparation["correspondence"], row["target"]
    matches = [item for item in correspondence["request"]["typed_rows"] if _same(item["target"], target)]
    _need(len(matches) == 1 and matches[0]["disposition"] == "source_linked"
          and target.get("kind") in {"variable", "predicate"},
          "exact source-linked parent variable or predicate target required")
    typed_row = matches[0]
    _need(_same(row["source_paths"], typed_row["source_paths"]),
          "complete ordered parent inverse source paths required")
    source_rows = [item for item in correspondence["request"]["source_rows"]
                   if item["anchor_mapping"]["declaration_path"] in row["source_paths"]]
    _need([item["anchor_mapping"]["declaration_path"] for item in source_rows] == row["source_paths"]
          and all(any(_same(target, item) for item in source["targets"]) for source in source_rows),
          "parent term-use source anchors differ from exact correspondence")
    contexts = [item for item in correspondence["typed_context_inventory"] if _same(item["target"], target)]
    _need(len(contexts) == 1, "complete parent binder, role and modal ancestry required")
    for key in ("definition_term_ref", "definition_ast_ref"):
        _need(_same(row[key], endpoint[key]), "whole parent definition term or AST reference differs")
    candidate = endpoint["candidate"]
    return {"request_link": row, "typed_row": typed_row,
        "typed_node": _at(correspondence["relational_fragment"]["typed_expression"], target["typed_path"]),
        "typed_context": contexts[0], "source_rows": source_rows,
        "definition_candidate_ref": {"record_cid": candidate["record_cid"],
                                     "sha256": norm_definition_evidence_sha256(candidate)},
        "definition_term_ref": endpoint["definition_term_ref"], "definition_ast_ref": endpoint["definition_ast_ref"],
        "status": "parent_source_linked_definition_nomination_unreviewed",
        "governing_definition_use": None, "authority": dict(FALSE_FLAGS)}


def _parent_definition_serialized_fence(report, expected_wire):
    _need(norm._parent_review_pure_wire(report) == expected_wire,
          "parent nomination report changed after final serialization")


def _parent_definition_operation(original):
    detached, commitment, parsed = _parent_definition_preflight(original)
    owners = _parent_definition_owners()
    review, lineage, source = owners
    pins = _parent_definition_pins(owners)
    callbacks = _parent_definition_callbacks(owners)
    runtime = norm._parent_review_pure_wire(_parent_definition_runtime(owners))
    parsed_commitment = norm._parent_review_fingerprint(parsed)
    held, physical = [], []
    norm_started = False
    endpoint_started = []
    result = serialized = None
    primary = None

    def hold(value):
        raw = _wire(value)
        held.append((value, raw))
        return raw

    def fence():
        _need(_parent_definition_callbacks(owners) == callbacks,
              "parent nomination replay or custody callbacks changed")
        _need(norm._parent_review_pure_wire(_parent_definition_runtime(owners)) == runtime,
              "parent nomination policy or bounds changed")
        _need(_parent_definition_pins(owners) == pins, "parent nomination producers changed")
        for value, raw in held:
            _need(norm._parent_review_pure_wire(value) == raw, "parent nomination actual replay return changed")
        for plan, witness, frozen in physical:
            _need(norm._parent_review_fingerprint(plan) == frozen,
                  "parent nomination physical file plan changed")
            _need(_parent_definition_file_witness(plan, lineage) == witness,
                  "parent nomination physical files changed")
        _need(norm._parent_review_fingerprint(original) == commitment
              and norm._parent_review_fingerprint(detached) == commitment,
              "parent nomination caller or detached inputs changed")
        _need(norm._parent_review_fingerprint(parsed) == parsed_commitment,
              "parent nomination parsed request or original candidate changed")
        for value, raw in held:
            _need(norm._parent_review_pure_wire(value) == raw,
                  "parent nomination actual return changed after closing callbacks")

    def bind_files(replay):
        fence()  # Never let a late parsed/caller mutation nominate another file.
        plan = _parent_definition_file_plan(replay, lineage)
        frozen = norm._parent_review_fingerprint(plan)
        witness = _parent_definition_file_witness(plan, lineage)
        physical.append((plan, witness, frozen))
        fence()

    def norm_replay():
        checked = norm.validate_parent_norm_review_evidence_v1(detached["norm_preparation"],
            expected_report_sha256=detached["expected_norm_preparation_sha256"], **detached["norm_inputs"])
        raw = hold(checked)
        _need(raw == _wire(detached["norm_preparation"]), "complete parent norm review regeneration differs")
        _observe(pins, checked["producer_pins"])
        return checked

    def definition_replay(endpoint):
        checked = review.validate_parent_definition_review_evidence_v1(endpoint["preparation"],
            **endpoint["preparation_inputs"])
        raw = hold(checked)
        _need(hashlib.sha256(raw).hexdigest() == endpoint["expected_preparation_sha256"],
              "complete parent definition review regeneration differs")
        _observe(pins, checked["producer_pins"])
        return checked

    def close_norm():
        if norm_started:
            fence()
            norm_replay()

    def close_definition(endpoint):
        fence()
        definition_replay(endpoint)

    def output_fence():
        if serialized is not None:
            _parent_definition_serialized_fence(result, serialized)
            fence()
            _parent_definition_serialized_fence(result, serialized)

    def terminal_fence():
        fence()
        if serialized is not None:
            _need(norm._parent_review_pure_wire(result) == serialized,
                  "parent nomination output changed after final custody callback")
            _need(json.dumps(result, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8") == serialized,
                  "parent nomination output changed after final direct encoding")

    try:
        fence()
        norm_started = True
        norm_preparation = norm_replay()
        bind_files(detached["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"])
        endpoints = []
        for endpoint, candidate in zip(detached["definitions"], parsed["definitions"], strict=True):
            endpoint_started.append(endpoint)
            checked = definition_replay(endpoint)
            bind_files(endpoint["preparation_inputs"]["parent_inputs"]["replay_inputs"])
            _need(candidate["record_cid"] == checked["candidate_pin"]["candidate_cid"]
                  and _same(candidate["ast_record"]["native_ast"], checked["native_ast"]),
                  "complete parent candidate differs from replayed definition preparation")
            for key in ("term_record", "ast_record", "definition_record"):
                _need(candidate[key]["record_cid"] == checked["companion_cids"][key],
                      "parent definition companion identity differs")
            endpoints.append({"alternative_id": endpoint["alternative_id"],
                "preparation_sha256": endpoint["expected_preparation_sha256"], "preparation": checked,
                "candidate": candidate,
                "definition_term_ref": {"record_cid": candidate["term_record"]["record_cid"],
                    "sha256": norm_definition_evidence_sha256(candidate["term_record"])},
                "definition_ast_ref": {"record_cid": candidate["ast_record"]["record_cid"],
                    "sha256": norm_definition_evidence_sha256(candidate["ast_record"])}})
        by_id = {endpoint["alternative_id"]: endpoint for endpoint in endpoints}
        links = [_parent_definition_link(row, norm_preparation, by_id[row["alternative_id"]])
                 for row in parsed["request"]["links"]]
        result = {"schema": PARENT_SCHEMA, "profile": PARENT_PROFILE,
            "status": "unsigned_parent_exact_term_use_evidence", "request": parsed["request"],
            "request_raw_sha256": detached["expected_request_sha256"],
            "norm_preparation_sha256": detached["expected_norm_preparation_sha256"],
            "norm_preparation": norm_preparation, "definitions": endpoints, "links": links,
            "counts": {"alternatives": len(endpoints), "links": len(links),
                "distinct_typed_uses": len({row["request_link"]["target"]["typed_path"] for row in links})},
            "external_complete_inputs_required": True, "original_norm_preparation_unchanged": True,
            "original_definition_preparations_unchanged": True, "original_signatures_cover_companion": False,
            "external_context_nominations_applied": False, "shared_context_inferred": False,
            "all_norm_term_uses_enumerated": False, "selected_interpretation": None,
            "governing_definition_use": None, "native_ast_rewritten": False,
            "producer_pins": pins, "authority": dict(FALSE_FLAGS),
            "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "limitations": [
                "These authored exact term-use nominations establish no governing definition, legal meaning or applicability.",
                "Both original parent source bindings and all context populations remain separate and unresolved; shared context or edition is not inferred.",
                "Every supplied alternative is retained; this is not an exhaustive inventory of statutory terms or interpretations.",
                "Relational source binding, authored ASTs and original review subjects remain unchanged; no new signature covers this companion.",
                "No alias, predicate substitution, bound instance, graph admission, Lean process, model or training is supplied.",
            ]}
        serialized = _wire(result)
        if detached["validating"]:
            _need(serialized == _wire(detached["offered"]),
                  "parent nomination report differs from complete original regeneration")
        result = json.loads(serialized)
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        closers = [lambda endpoint=endpoint: close_definition(endpoint) for endpoint in endpoint_started]
        source._parent_finish((fence, close_norm, *closers, fence, output_fence, terminal_fence), primary)


def prepare_parent_norm_definition_evidence_v1(norm_preparation, request_raw, *,
        expected_norm_preparation_sha256, expected_request_sha256, norm_inputs, definitions):
    """Replay complete parent endpoints and retain unsigned exact-use nominations."""
    return _parent_definition_operation(dict(norm_preparation=norm_preparation, request_raw=request_raw,
        expected_norm_preparation_sha256=expected_norm_preparation_sha256,
        expected_request_sha256=expected_request_sha256, norm_inputs=norm_inputs, definitions=definitions,
        offered=None, expected_report_sha256=None, validating=False))


def validate_parent_norm_definition_evidence_v1(report, norm_preparation, request_raw, *,
        expected_report_sha256, expected_norm_preparation_sha256, expected_request_sha256,
        norm_inputs, definitions):
    """Require the complete independent commitment and original endpoint replay."""
    return _parent_definition_operation(dict(norm_preparation=norm_preparation, request_raw=request_raw,
        expected_norm_preparation_sha256=expected_norm_preparation_sha256,
        expected_request_sha256=expected_request_sha256, norm_inputs=norm_inputs, definitions=definitions,
        offered=report, expected_report_sha256=expected_report_sha256, validating=True))
