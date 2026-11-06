"""Typed reviewer proposals bound by the existing norm evidence-review domain.

This companion authenticates no new legal authority. A signed obligation must
reference the complete exact response body; its typed assertions remain reviewer
declarations pending separate content adjudication. Definition applicability is
explicitly unresolved. No signer, registry, policy, clock or decision is supplied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_interpretation_review_v1 as norm
from . import legal_paired_manifest_inventory_v1 as json_reader

PROFILE = "typed-existing-candidate-norm-content-responses/v1"
TEMPLATE_SCHEMA = "legal-norm-content-response-template/v1"
RESPONSE_SCHEMA = "legal-norm-content-response/v1"
ASSESSMENT_SCHEMA = "legal-norm-content-response-assessment/v1"
RESULT_SCHEMA = "legal-norm-content-response-result/v1"
VARIANT_SCHEMA = "legal-norm-content-answer-variant/v1"
PENDING_SCHEMA = "legal-norm-content-pending-question/v1"
MAX_ASSERTIONS = 128
FALSE_FLAGS = dict(norm.FALSE_FLAGS, typed_meaning_decisions_applied=False,
    response_content_adjudication_available=False, adjudication_accepted=False,
    answer_content_establishes_legal_truth=False, reviewer_competence_verified=False,
    process_declarations_verified=False, exposure_declarations_verified=False,
    accepted_view_eligible=False)
INPUT_FIELDS = {"review_id", "principal_id", "role", "issued_at_utc", "process_declaration",
                "exposure_declaration", "candidate_proposal", "answers", "governing_definition_use"}
DISPOSITIONS = {"unresolved": "open", "evidence_declared": "resolved_by_evidence",
                "not_applicable": "not_applicable"}
_PROCESS_FIELDS = {"identity_evidence_refs", "independence_evidence_refs", "process_evidence_refs"}
_ASSESS_FIELDS = {"preparation", "expected_preparation_sha256", "correspondence",
    "expected_correspondence_sha256", "correspondence_inputs", "context_inputs",
    "expected_subject_sha256", "expected_registry_sha256", "expected_policy_sha256",
    "expected_reviews_sha256", "expected_manifest_sha256", "at_time_utc",
    "observed_artifact_sha256s", "observed_pins", "evidence_artifacts"}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_NORM_PIN = hashlib.sha256(Path(norm.__file__).read_bytes()).hexdigest()
_READER_PIN = hashlib.sha256(Path(json_reader.__file__).read_bytes()).hexdigest()
_need, _keys, _sha = norm._need, norm._keys, norm._sha


def norm_content_sha256(value):
    """SHA256 of the existing bounded norm canonical UTF8 JSON recipe.

    This hashes the complete offered value, including any embedded digest.
    Raw response evidence uses SHA256 of its exact bytes. Signing subjects,
    registry/policy/reviews retain the existing graph-review digest recipe.
    """
    return norm.norm_review_sha256(value)


def _pins():
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "norm content producer changed since import")
    _need(hashlib.sha256(Path(norm.__file__).read_bytes()).hexdigest() == _NORM_PIN,
          "norm review producer changed since content import")
    _need(hashlib.sha256(Path(json_reader.__file__).read_bytes()).hexdigest() == _READER_PIN,
          "response JSON reader changed since content import")
    pins = dict(norm._pins(norm._owners()))
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    pins[str(Path(json_reader.__file__).resolve())] = _READER_PIN
    return pins


def _finish(original, detached, commitment, pins, report):
    raw = norm._wire(report)
    _need(norm._snapshot(original)[1] == commitment and norm._snapshot(detached)[1] == commitment,
          "norm content inputs changed during preparation or assessment")
    _need(_pins() == pins, "norm content producers changed during operation")
    return json.loads(raw)


def _seal(schema, **values):
    return {"schema": schema, "profile": PROFILE, **values, **FALSE_FLAGS,
            "authority": dict(FALSE_FLAGS), "norm_interpretation_ready": False,
            "governing_definition_use": None, "training_mask": 0, "evaluation_gold_mask": 0}


def _text(value, label, maximum=8192):
    _need(type(value) is str and bool(value.strip()) and "\x00" not in value,
          "explicit nonempty text required: " + label)
    _need(len(value.encode("utf-8")) <= maximum, "bounded UTF8 text required: " + label)


def _refs(values):
    auth = norm._owners()[1]
    _need(type(values) is list and len(values) <= 8, "bounded ordered evidence references required")
    seen = set()
    for ref in values:
        _keys(ref, {"artifact_id", "sha256"}, "norm content evidence reference")
        auth._id(ref["artifact_id"], "norm content evidence ID")
        _sha(ref["sha256"], "norm content evidence")
        _need(ref["artifact_id"] not in seen, "duplicate evidence identity")
        seen.add(ref["artifact_id"])


def _family(obligation):
    return obligation["question"] if obligation["kind"] == "interpretation_question" else obligation["kind"]


def _members(values, population, label):
    """An exact duplicate-free subsequence of an existing ordered inventory."""
    _need(type(values) is list and len(values) <= MAX_ASSERTIONS, "bounded " + label + " required")
    position = -1
    for value in values:
        matches = [index for index, item in enumerate(population) if norm._same(value, item)]
        _need(len(matches) == 1 and matches[0] > position, "exact ordered existing " + label + " required")
        position = matches[0]


def _assessment(value):
    _need(type(value) is str and value in {"support", "dispute", "unresolved"},
          "explicit typed assertion assessment required")


def _typed_row(target, correspondence):
    matches = [row for row in correspondence["request"]["typed_rows"]
               if norm._same(row["target"], target)]
    _need(len(matches) == 1 and matches[0]["disposition"] == "source_linked",
          "exact existing source-linked typed target required")
    return matches[0]


def _source_rows(typed_row, correspondence):
    rows = correspondence["request"]["source_rows"]
    selected = [row for row in rows
                if row["anchor_mapping"]["declaration_path"] in typed_row["source_paths"]]
    _need([row["anchor_mapping"]["declaration_path"] for row in selected] == typed_row["source_paths"],
          "complete ordered inverse source anchors required")
    return selected


def _finding(finding, answer, obligation, correspondence):
    family = _family(obligation)
    extras = {"original_context": {"original_sha256"},
        "original_unresolved_issue": {"original_sha256"},
        "source_meaning": {"source_assertions"}, "participant_roles": {"role_assertions"},
        "condition_and_modal_scope": {"scope_assertions"}, "exceptions_and_time": {"scope_assertions"},
        "source_coverage": {"coverage"}, "unsupported_grammar": {"none_declared", "constructs"},
        "definition_applicability": {"status", "governing_definition_use"}}
    _need(family in extras, "unsupported norm obligation family")
    _keys(finding, {"family", "statement"} | extras[family], "typed " + family + " finding")
    _need(finding["family"] == family, "finding family differs from exact obligation")
    _text(finding["statement"], "finding statement")
    unresolved = answer["disposition"] == "unresolved"
    source_rows = correspondence["request"]["source_rows"]
    if family in {"original_context", "original_unresolved_issue"}:
        _need(finding["original_sha256"] == norm_content_sha256(obligation["original"]),
              "finding names another original obligation record")
    elif family == "definition_applicability":
        _need(unresolved and finding["status"] == "unresolved" and finding["governing_definition_use"] is None,
              "definition applicability must remain explicitly unresolved")
    elif family == "source_meaning":
        assertions = finding["source_assertions"]
        _need(type(assertions) is list and len(assertions) <= MAX_ASSERTIONS, "bounded source assertions required")
        for row in assertions:
            _keys(row, {"source_row", "assessment"}, "source meaning assertion")
            _assessment(row["assessment"])
        _members([row["source_row"] for row in assertions], source_rows, "source assertions")
        _need(unresolved or bool(assertions), "non-unresolved source meaning needs exact assertions")
    elif family == "participant_roles":
        assertions = finding["role_assertions"]
        _need(type(assertions) is list and len(assertions) <= MAX_ASSERTIONS, "bounded role assertions required")
        targets = []
        for row in assertions:
            _keys(row, {"target", "source_paths", "declared_role", "assessment"}, "participant role assertion")
            typed = _typed_row(row["target"], correspondence)
            _need(row["target"]["kind"] in {"variable", "binder", "predicate"},
                  "participant role needs an existing variable, binder or predicate")
            _need(norm._same(row["source_paths"], typed["source_paths"]), "role inverse source paths differ")
            _text(row["declared_role"], "declared participant role", 128)
            _assessment(row["assessment"])
            targets.append(row["target"])
        _members(targets, [row["target"] for row in correspondence["request"]["typed_rows"]], "role targets")
        _need(unresolved or bool(assertions), "non-unresolved roles need exact assertions")
    elif family in {"condition_and_modal_scope", "exceptions_and_time"}:
        assertions = finding["scope_assertions"]
        _need(type(assertions) is list and len(assertions) <= MAX_ASSERTIONS, "bounded scope assertions required")
        contexts = []
        aspects = {"condition", "modality", "quantifier_scope"} if family == "condition_and_modal_scope" else {"exception", "time"}
        for row in assertions:
            _keys(row, {"typed_context", "source_rows", "aspect", "assessment", "statement"}, "scope assertion")
            context = row["typed_context"]
            _need(type(context) is dict and "target" in context, "exact typed context required")
            typed = _typed_row(context["target"], correspondence)
            _need(norm._same(row["source_rows"], _source_rows(typed, correspondence)),
                  "scope assertion inverse source anchors differ")
            _need(type(row["aspect"]) is str and row["aspect"] in aspects, "scope aspect differs from question")
            _assessment(row["assessment"])
            _text(row["statement"], "declared scope")
            contexts.append(context)
        _members(contexts, correspondence["typed_context_inventory"], "typed contexts and ancestry")
        _need(unresolved or bool(assertions), "non-unresolved scope needs exact assertions")
    elif family == "source_coverage":
        coverage = finding["coverage"]
        _need(type(coverage) is list and len(coverage) == len(source_rows), "complete ordered source coverage required")
        for row, original in zip(coverage, source_rows, strict=True):
            _keys(row, {"source_row", "status"}, "source coverage declaration")
            _need(norm._same(row["source_row"], original), "source coverage population or order differs")
            _need(type(row["status"]) is str and row["status"] in {"covered", "missing", "uncertain"},
                  "explicit source coverage status required")
            _need(not unresolved or row["status"] == "uncertain", "unresolved coverage cannot declare coverage decided")
    elif family == "unsupported_grammar":
        constructs = finding["constructs"]
        _need(type(finding["none_declared"]) is bool and type(constructs) is list and len(constructs) <= MAX_ASSERTIONS,
              "explicit unsupported construct inventory required")
        for row in constructs:
            _keys(row, {"source_row", "construct"}, "unsupported source construct")
            _text(row["construct"], "cited unsupported construct")
        _members([row["source_row"] for row in constructs], source_rows, "unsupported source anchors")
        _need(not finding["none_declared"] or not constructs, "none-declared grammar cannot list constructs")
        _need((not finding["none_declared"] and not constructs) if unresolved else
              (finding["none_declared"] or bool(constructs)), "unsupported grammar declaration differs from disposition")


def _blank_finding(obligation, correspondence):
    family = _family(obligation)
    finding = {"family": family, "statement": None}
    if family in {"original_context", "original_unresolved_issue"}:
        finding["original_sha256"] = norm_content_sha256(obligation["original"])
    elif family == "definition_applicability":
        finding.update(status="unresolved", governing_definition_use=None)
    elif family == "source_coverage":
        finding["coverage"] = [{"source_row": row, "status": None} for row in correspondence["request"]["source_rows"]]
    elif family == "unsupported_grammar":
        finding.update(none_declared=None, constructs=[])
    else:
        key = "source_assertions" if family == "source_meaning" else "role_assertions" if family == "participant_roles" else "scope_assertions"
        finding[key] = []
    return finding


def _record(preparation, subject, response):
    auth = norm._owners()[1]
    _keys(response, INPUT_FIELDS, "norm content response input")
    for field in ("review_id", "principal_id"):
        auth._id(response[field], "response " + field)
    _need(type(response["role"]) is str and response["role"] in auth.ROLES, "explicit legal or formal response role required")
    auth._time(response["issued_at_utc"])
    _keys(response["process_declaration"], _PROCESS_FIELDS, "explicit response process declaration")
    for values in response["process_declaration"].values():
        _refs(values)
    exposure = response["exposure_declaration"]
    _keys(exposure, {"candidate_interpretations_exposed", "organizer_source_metadata_exposed", "other_exposure"},
          "explicit response exposure declaration")
    for field in ("candidate_interpretations_exposed", "organizer_source_metadata_exposed"):
        _need(exposure[field] is None or type(exposure[field]) is bool, "explicit boolean or unknown exposure required")
    if exposure["other_exposure"] is not None:
        _text(exposure["other_exposure"], "other exposure")
    _need(response["governing_definition_use"] is None, "governing definition use cannot be selected")
    proposal = response["candidate_proposal"]
    _keys(proposal, {"decision", "typed_expression_sha256", "native_ast_sha256", "rationale", "evidence_refs"}, "exact existing candidate proposal")
    _need(type(proposal["decision"]) is str and proposal["decision"] in {"support", "reject", "unresolved"}, "explicit candidate proposal decision required")
    _need(proposal["typed_expression_sha256"] == preparation["ast_sha256"] and
          proposal["native_ast_sha256"] == preparation["native_ast_sha256"], "candidate proposal differs from exact original ASTs")
    _text(proposal["rationale"], "candidate proposal rationale")
    _refs(proposal["evidence_refs"])
    _need(proposal["decision"] == "unresolved" or bool(proposal["evidence_refs"]), "support or rejection needs independent evidence")
    answers = response["answers"]
    _need(type(answers) is list and len(answers) == len(preparation["obligations"]), "complete ordered norm answers required")
    for answer, obligation in zip(answers, preparation["obligations"], strict=True):
        _keys(answer, {"slot_id", "kind", "obligation_sha256", "disposition", "rationale", "evidence_refs", "finding"}, "typed norm answer")
        _need(answer["slot_id"] == obligation["slot_id"] and answer["kind"] == obligation["kind"] and
              answer["obligation_sha256"] == norm_content_sha256(obligation), "answer differs from exact ordered obligation")
        _need(type(answer["disposition"]) is str and answer["disposition"] in DISPOSITIONS, "explicit norm answer disposition required")
        _text(answer["rationale"], "answer rationale")
        _refs(answer["evidence_refs"])
        _need(answer["disposition"] == "unresolved" or bool(answer["evidence_refs"]), "non-unresolved answer needs independent evidence")
        _finding(answer["finding"], answer, obligation, preparation["correspondence"])
    record = _seal(RESPONSE_SCHEMA, preparation_sha256=norm_content_sha256(preparation),
        subject_sha256=auth.digest(subject), obligations_sha256=norm_content_sha256(preparation["obligations"]),
        context_evidence_sha256=norm_content_sha256(preparation["context_evidence"]),
        dependency_manifest_sha256=subject["dependency_manifest_sha256"], **response,
        status="declared_unauthenticated_norm_content_response")
    # Compact typed bodies fit the existing strict integer signing vocabulary
    # and duplicate-free reader profile. Large upstream evidence stays separate.
    auth.wire(record)
    json_reader._wire(record, norm.MAX_BYTES)
    return record


def build_norm_content_template_v1(preparation, dependency_manifest, **build_inputs):
    """Return blank unsubmitted fields; nulls are not valid review answers."""
    original = dict(preparation=preparation, dependency_manifest=dependency_manifest, build_inputs=build_inputs)
    detached, commitment = norm._snapshot(original)
    pins = _pins()
    subject = norm.build_norm_review_subject_v1(detached["preparation"], detached["dependency_manifest"], **detached["build_inputs"])
    prep = detached["preparation"]
    response = {"review_id": None, "principal_id": None, "role": None, "issued_at_utc": None,
        "process_declaration": {key: [] for key in sorted(_PROCESS_FIELDS)},
        "exposure_declaration": {key: None for key in ("candidate_interpretations_exposed", "organizer_source_metadata_exposed", "other_exposure")},
        "candidate_proposal": {"decision": None, "typed_expression_sha256": prep["ast_sha256"],
            "native_ast_sha256": prep["native_ast_sha256"], "rationale": None, "evidence_refs": []},
        "governing_definition_use": None,
        "answers": [{"slot_id": row["slot_id"], "kind": row["kind"], "obligation_sha256": norm_content_sha256(row),
            "disposition": None, "rationale": None, "evidence_refs": [],
            "finding": _blank_finding(row, prep["correspondence"])} for row in prep["obligations"]]}
    report = _seal(TEMPLATE_SCHEMA, preparation_sha256=norm_content_sha256(prep), subject=subject,
        subject_sha256=norm._owners()[1].digest(subject), obligations=prep["obligations"],
        source_rows=prep["correspondence"]["request"]["source_rows"],
        typed_context_inventory=prep["correspondence"]["typed_context_inventory"],
        context_evidence=prep["context_evidence"], response=response,
        status="blank_unsubmitted_template_not_a_response", producer_pins=pins)
    return _finish(original, detached, commitment, pins, report)


def build_norm_content_response_v1(preparation, dependency_manifest, response, **build_inputs):
    """Record supplied typed declarations after exact complete upstream replay."""
    original = dict(preparation=preparation, dependency_manifest=dependency_manifest, response=response, build_inputs=build_inputs)
    detached, commitment = norm._snapshot(original)
    pins = _pins()
    subject = norm.build_norm_review_subject_v1(detached["preparation"], detached["dependency_manifest"], **detached["build_inputs"])
    report = _record(detached["preparation"], subject, detached["response"])
    return _finish(original, detached, commitment, pins, report)


def _bindings(bindings, expected_sha256, reviews):
    auth = norm._owners()[1]
    _sha(expected_sha256, "complete ordered response bindings")
    _need(auth.digest(bindings) == expected_sha256, "independently pinned response binding population differs")
    _need(type(bindings) is list and len(bindings) == len(reviews) <= auth.MAX_REVIEWS,
          "one ordered response binding per supplied review required")
    seen = set()
    for entry, signed in zip(bindings, reviews, strict=True):
        _keys(entry, {"review_id", "artifact_id", "raw_sha256"}, "response body binding")
        auth._id(entry["review_id"], "bound review ID")
        auth._id(entry["artifact_id"], "response body ID")
        _sha(entry["raw_sha256"], "raw response body")
        _need(entry["review_id"] == signed["review_id"] and entry["artifact_id"] not in seen,
              "response binding review order or unique body identity differs")
        seen.add(entry["artifact_id"])


def _load_body(raw, expected_sha256):
    _need(type(raw) is bytes and 0 < len(raw) <= norm.MAX_BYTES, "bounded exact response body bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256, "raw response body SHA256 differs")

    record = json_reader._read_json(raw, norm.MAX_BYTES, "norm content response")
    norm._owners()[1].wire(record)
    return record


def _content(entry, signed, preparation, subject, evidence, response_body_ids, response_body_sha256s):
    try:
        record = _load_body(evidence.get(entry["artifact_id"]), entry["raw_sha256"])
        _need(type(record) is dict, "typed response record mapping required")
        response = {key: record[key] for key in INPUT_FIELDS}
        _need(norm._same(record, _record(preparation, subject, response)), "typed response differs from full exact regeneration")
        _need(all(record[key] == signed[key] for key in ("review_id", "principal_id", "role", "issued_at_utc")),
              "typed response differs from signed reviewer identity, role or time")
        interpretation = signed["interpretation"]
        _need(record["candidate_proposal"]["decision"] == interpretation["decision"] and
              interpretation["reviewed_graph_sha256"] == subject["graph_sha256"] and
              interpretation["reviewed_ast_sha256"] == subject["ast_sha256"], "typed candidate proposal differs from signed interpretation")
        closure = signed["context_closure"]
        _need(len(closure["obligations"]) == len(record["answers"]), "signed obligation population differs")
        body_ref = {"artifact_id": entry["artifact_id"], "sha256": entry["raw_sha256"]}
        for answer, obligation in zip(record["answers"], closure["obligations"], strict=True):
            _need(obligation["slot_id"] == answer["slot_id"] and obligation["evidence_refs"] == [body_ref] and
                  obligation["disposition"] == DISPOSITIONS[answer["disposition"]], "signed answer disposition or complete body reference differs")
        unresolved = [row["slot_id"] for row in record["answers"] if row["disposition"] == "unresolved"]
        _need(closure["unresolved"] == unresolved and closure["status"] == ("open" if unresolved else "declared_complete"),
              "signed unresolved population, order or closure status differs")
        refs = [ref for row in record["answers"] for ref in row["evidence_refs"]]
        refs.extend(ref for values in record["process_declaration"].values() for ref in values)
        refs.extend(record["candidate_proposal"]["evidence_refs"])
        for ref in refs:
            raw = evidence.get(ref["artifact_id"])
            _need(ref["artifact_id"] not in response_body_ids and ref["sha256"] not in response_body_sha256s and type(raw) is bytes and
                  hashlib.sha256(raw).hexdigest() == ref["sha256"], "supporting evidence missing, changed or self-referential")
        return record, not unresolved, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, False, [str(error) or "typed norm response content invalid"]


def assess_norm_content_responses_v1(subject, registry, policy, reviews, dependency_manifest, *,
        response_bindings, expected_response_bindings_sha256, **assessment_inputs):
    """Replay original authentication and retain typed proposals, never apply them."""
    _keys(assessment_inputs, _ASSESS_FIELDS, "complete existing norm assessment inputs")
    original = dict(subject=subject, registry=registry, policy=policy, reviews=reviews,
        dependency_manifest=dependency_manifest, response_bindings=response_bindings,
        expected_response_bindings_sha256=expected_response_bindings_sha256, assessment_inputs=assessment_inputs)
    detached, commitment = norm._snapshot(original)
    pins = _pins()
    subject, reviews, bindings = detached["subject"], detached["reviews"], detached["response_bindings"]
    inputs = detached["assessment_inputs"]
    _bindings(bindings, expected_response_bindings_sha256, reviews)
    raw_assessment = norm.assess_norm_reviews_v1(subject, detached["registry"], detached["policy"], reviews,
        detached["dependency_manifest"], **inputs)
    preparation, evidence = inputs["preparation"], inputs["evidence_artifacts"]
    response_body_ids = {entry["artifact_id"] for entry in bindings}
    response_body_sha256s = {entry["raw_sha256"] for entry in bindings}
    results, valid, variants, pending = [], [], [], []
    for entry, signed, raw_row in zip(bindings, reviews, raw_assessment["reviews"], strict=True):
        record, complete, blockers = _content(entry, signed, preparation, subject, evidence,
                                              response_body_ids, response_body_sha256s)
        authenticated = raw_row["status"] == "authenticated" and not blockers
        result = _seal(RESULT_SCHEMA, review_id=signed["review_id"], principal_id=signed["principal_id"],
            role=signed["role"], review_sha256=raw_row["review_sha256"],
            response_artifact_ref={"artifact_id": entry["artifact_id"], "sha256": entry["raw_sha256"]},
            response_record=record, signature_authentication_status=raw_row["status"],
            content_status="rejected" if blockers else "valid_declared_content", content_blockers=blockers,
            authenticated_typed_content=authenticated, typed_answer_declarations_complete=complete)
        results.append(result)
        if authenticated:
            valid.append((record, len(results) - 1))
    for index, obligation in enumerate(preparation["obligations"]):
        buckets = {}
        for record, result_index in valid:
            answer = record["answers"][index]
            key = norm_content_sha256(answer)
            bucket = buckets.setdefault(key, {"answer": answer, "respondents": []})
            bucket["respondents"].append({"response_result_index": result_index, "review_id": record["review_id"],
                "principal_id": record["principal_id"], "role": record["role"]})
        refs, respondents = [], []
        for digest, bucket in buckets.items():
            variant = _seal(VARIANT_SCHEMA, slot_id=obligation["slot_id"], answer_sha256=digest,
                answer=bucket["answer"], respondents=bucket["respondents"])
            variants.append(variant)
            refs.append({"variant_index": len(variants) - 1, "sha256": norm_content_sha256(variant)})
            respondents.extend(bucket["respondents"])
        issues = ["separate_content_adjudication_and_admission_required"]
        if not respondents:
            issues.append("no_authenticated_typed_answer")
        if any(bucket["answer"]["disposition"] == "unresolved" for bucket in buckets.values()):
            issues.append("unresolved_typed_answer")
        if len(buckets) > 1:
            issues.append("distinct_exact_answer_variants")
        legal = [row for row in respondents if row["role"] == "legal_review"]
        formal = [row for row in respondents if row["role"] == "formal_review"]
        if not any(a["principal_id"] != b["principal_id"] for a in legal for b in formal):
            issues.append("distinct_legal_and_formal_declared_principals_missing")
        pending.append(_seal(PENDING_SCHEMA, slot_id=obligation["slot_id"], kind=obligation["kind"],
            obligation_sha256=norm_content_sha256(obligation), answer_variant_refs=refs,
            authenticated_respondents=respondents, issues=issues, decision=None,
            adjudicator_declaration=None, status="pending_content_adjudication_not_a_decision"))
    report = _seal(ASSESSMENT_SCHEMA, subject=subject, subject_sha256=inputs["expected_subject_sha256"],
        preparation_sha256=inputs["expected_preparation_sha256"],
        context_evidence=preparation["context_evidence"], original_obligations=preparation["obligations"],
        response_bindings=bindings, response_bindings_sha256=expected_response_bindings_sha256,
        raw_norm_assessment=raw_assessment, response_results=results, answer_variants=variants,
        pending_questions=pending, candidate_proposals=[{"review_id": record["review_id"],
            "response_result_index": result_index, "proposal": record["candidate_proposal"]} for record, result_index in valid],
        typed_response_validation_available=True, population_complete=True,
        coverage_scope="one_exact_candidate_all_original_obligations_and_all_supplied_reviews",
        counts={"responses": len(results), "authenticated_typed_responses": len(valid),
            "rejected_content_responses": sum(row["content_status"] == "rejected" for row in results),
            "incomplete_typed_responses": sum(not row["typed_answer_declarations_complete"] for row in results),
            "answer_variants": len(variants), "pending_adjudication_slots": len(pending),
            "applied_meaning_decisions": 0}, producer_pins=pins)
    report["assessment_sha256"] = norm_content_sha256(report)
    return _finish(original, detached, commitment, pins, report)


def validate_norm_content_assessment_v1(report, *args, expected_report_sha256, **kwargs):
    """Check an independent complete-report pin and regenerate every original input."""
    original = dict(report=report, args=list(args), kwargs=kwargs,
                    expected_report_sha256=expected_report_sha256)
    detached, commitment = norm._snapshot(original)
    pins = _pins()
    _sha(expected_report_sha256, "complete norm content assessment")
    _need(norm_content_sha256(detached["report"]) == expected_report_sha256, "independently pinned norm content report differs")
    regenerated = assess_norm_content_responses_v1(*detached["args"], **detached["kwargs"])
    _need(norm._same(detached["report"], regenerated), "norm content assessment differs from exact full replay")
    return _finish(original, detached, commitment, pins, regenerated)


__all__ = ["build_norm_content_template_v1", "build_norm_content_response_v1",
           "assess_norm_content_responses_v1", "validate_norm_content_assessment_v1", "norm_content_sha256"]
