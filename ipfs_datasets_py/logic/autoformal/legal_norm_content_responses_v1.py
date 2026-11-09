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


# This is a manual unsigned worksheet, not an input to the existing signing,
# response authentication or adjudication domains.
PARENT_TEMPLATE_SCHEMA = "legal-parent-norm-content-template/v1"
PARENT_TEMPLATE_PROFILE = "unsigned-parent-literal-content-worksheet/v1"
_PARENT_CONTENT_PINS = None


def _parent_content_pins():
    global _PARENT_CONTENT_PINS
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "parent worksheet producer changed since import")
    _need(hashlib.sha256(Path(norm.__file__).read_bytes()).hexdigest() == _NORM_PIN,
          "parent review producer changed since worksheet import")
    _need(hashlib.sha256(Path(json_reader.__file__).read_bytes()).hexdigest() == _READER_PIN,
          "existing response transport producer changed since worksheet import")
    pins = norm._parent_review_pins(norm._parent_review_owners())
    for module, expected in ((json_reader, _READER_PIN),):
        path = str(Path(module.__file__).resolve())
        _need(path not in pins or pins[path] == expected,
              "shared parent worksheet producer identities differ")
        pins[path] = expected
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _PARENT_CONTENT_PINS is None:
        _PARENT_CONTENT_PINS = dict(pins)
    _need(pins == _PARENT_CONTENT_PINS,
          "parent worksheet producers changed since first use")
    return dict(pins)


def _parent_content_render(preparation, expected_preparation_sha256, pins):
    correspondence = preparation["correspondence"]
    answers = []
    for obligation in preparation["obligations"]:
        if obligation["kind"] == "original_parent_context":
            finding = {"family": "original_parent_context", "statement": None,
                       "original_sha256": norm_content_sha256(obligation["original"])}
        else:
            finding = _blank_finding(obligation, correspondence)
        answers.append({"slot_id": obligation["slot_id"], "kind": obligation["kind"],
            "obligation_sha256": norm_content_sha256(obligation), "disposition": None,
            "rationale": None, "evidence_refs": [], "finding": finding})
    response = {"review_id": None, "principal_id": None, "role": None, "issued_at_utc": None,
        "process_declaration": {key: [] for key in sorted(_PROCESS_FIELDS)},
        "exposure_declaration": {key: None for key in
            ("candidate_interpretations_exposed", "organizer_source_metadata_exposed", "other_exposure")},
        "candidate_proposal": {"decision": None,
            "typed_expression_sha256": preparation["ast_sha256"],
            "native_ast_sha256": preparation["native_ast_sha256"], "rationale": None, "evidence_refs": []},
        "answers": answers, "governing_definition_use": None}
    return {"schema": PARENT_TEMPLATE_SCHEMA, "profile": PARENT_TEMPLATE_PROFILE,
        "status": "blank_unsigned_parent_worksheet_not_a_response",
        "preparation": preparation, "preparation_sha256": expected_preparation_sha256,
        "correspondence_sha256": preparation["correspondence_sha256"],
        "source_identity": preparation["source_identity"],
        "source_identity_sha256": preparation["source_identity_sha256"],
        "original_parent_context": preparation["original_parent_context"],
        "obligations": preparation["obligations"], "obligation_ids": preparation["obligation_ids"],
        "source_rows": preparation["source_rows"],
        "typed_context_inventory": preparation["typed_context_inventory"],
        "dependency_manifest": preparation["dependency_manifest"],
        "required_dependency_ids": preparation["required_dependency_ids"],
        "response": response, "subject": None, "subject_sha256": None,
        "signature": None, "clock": None, "registry": None, "policy": None,
        "unsigned_only": True, "response_submission_allowed": False,
        "original_signatures_cover_parent_template": False,
        "external_context_nominations_applied": False,
        "selected_interpretation": None, "accepted_interpretation": None, "governing_definition_use": None,
        "norm_interpretation_ready": False, "authority": dict(FALSE_FLAGS),
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "model_calls": 0, "training_calls": 0, "native_processes": 0, "producer_pins": pins,
        "limitations": [
            "This blank unsigned manual worksheet is not a submitted response, signing subject, credential, review or content adjudication.",
            "All six parent-context obligations, caller issues and existing semantic questions remain open. Blank answers and evidence lists resolve nothing.",
            "Exact source/occurrence custody and authored typed correspondence do not establish a whole paragraph, governing edition, complete legal meaning or definition applicability.",
            "The original response, declaration-binding, signing and adjudication APIs retain their closed profiles and reject this parent worksheet.",
            "No interpretation, governing definition use, learned target, graph admission, model, training, solver or Lean process is supplied.",
        ]}


def _parent_content_operation(preparation, expected_preparation_sha256, correspondence,
                              expected_correspondence_sha256, correspondence_inputs,
                              *, offered=None, expected_report_sha256=None, validating=False):
    _sha(expected_preparation_sha256, "complete unsigned parent preparation")
    _sha(expected_correspondence_sha256, "complete parent correspondence")
    original = dict(preparation=preparation, expected_preparation_sha256=expected_preparation_sha256,
        correspondence=correspondence, expected_correspondence_sha256=expected_correspondence_sha256,
        correspondence_inputs=correspondence_inputs, offered=offered,
        expected_report_sha256=expected_report_sha256)
    detached, commitment = norm._snapshot(original)
    preparation_raw = norm._wire(detached["preparation"])
    _need(hashlib.sha256(preparation_raw).hexdigest() == expected_preparation_sha256,
          "independently pinned complete parent review preparation differs")
    _need(type(detached["preparation"]) is dict
          and detached["preparation"].get("schema") == norm.PARENT_PREPARATION_SCHEMA
          and detached["preparation"].get("profile") == norm.PARENT_REVIEW_PROFILE,
          "explicit unsigned parent review preparation required")
    _need(norm.norm_review_sha256(detached["correspondence"]) == expected_correspondence_sha256,
          "independently pinned complete parent correspondence differs")
    if validating:
        _sha(expected_report_sha256, "complete unsigned parent worksheet")
        offered_raw = norm._wire(detached["offered"])
        _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
              "independently pinned complete parent worksheet differs")
        _need(type(detached["offered"]) is dict
              and detached["offered"].get("schema") == PARENT_TEMPLATE_SCHEMA
              and detached["offered"].get("profile") == PARENT_TEMPLATE_PROFILE,
              "explicit unsigned parent worksheet profile required")
    else:
        offered_raw = None
    parsed = norm._parent_review_preflight(detached["correspondence"], detached["correspondence_inputs"])
    parsed_raw = norm._wire(parsed)
    pins = _parent_content_pins()
    trusted = norm._parent_review_pins(norm._parent_review_owners())
    _need(norm._same(detached["preparation"].get("producer_pins"), trusted),
          "parent review producer commitments differ from trusted owners")
    source = norm._parent_review_owners()[2]
    opening = checked = result = serialized = opening_raw = None
    closing_returns = []
    replay_started = False
    primary = None
    encoder = lambda value, maximum: norm._wire(value)  # Existing fixed8MiB recipe.

    def input_fence():
        _need(norm._parent_review_fingerprint(original) == commitment
              and norm._parent_review_fingerprint(detached) == commitment,
              "parent worksheet caller or detached inputs changed during operation")
        _need(norm._parent_review_pure_wire(parsed) == parsed_raw,
              "parent worksheet parsed requests changed during operation")

    def fence():
        _need(_parent_content_pins() == pins, "parent worksheet producers changed during operation")
        input_fence()

    def pure_returned_fence():
        if opening_raw is not None:
            _need(norm._parent_review_pure_wire(opening) == opening_raw
                  and norm._parent_review_pure_wire(checked) == opening_raw,
                  "parent worksheet returned preparation changed during operation")
        for value, raw in closing_returns:
            _need(norm._parent_review_pure_wire(value) == raw,
                  "parent worksheet retained closing return changed during operation")

    def returned_fence():
        if opening_raw is not None:
            source._parent_serialized_fence(opening, opening_raw, norm.MAX_BYTES, encoder)
            source._parent_serialized_fence(checked, opening_raw, norm.MAX_BYTES, encoder)

    def replay():
        return norm.validate_parent_norm_review_evidence_v1(detached["preparation"],
            detached["correspondence"], expected_report_sha256=expected_preparation_sha256,
            expected_correspondence_sha256=expected_correspondence_sha256,
            correspondence_inputs=detached["correspondence_inputs"])

    def closing_replay():
        if replay_started:
            closing = replay()
            source._parent_serialized_fence(closing, preparation_raw, norm.MAX_BYTES, encoder)
            closing_returns.append((closing, preparation_raw))

    def output_fence():
        if serialized is not None:
            def final_encoder(value, maximum):
                raw = encoder(value, maximum)
                input_fence()
                pure_returned_fence()
                return raw
            source._parent_serialized_fence(result, serialized, norm.MAX_BYTES, final_encoder)

    try:
        fence()
        replay_started = True
        opening = replay()
        opening_raw = norm._wire(opening)
        _need(opening_raw == preparation_raw, "validated parent review preparation changed after return")
        checked = json.loads(opening_raw)
        fence()
        result = _parent_content_render(checked, expected_preparation_sha256, pins)
        serialized = norm._wire(result)
        _need(not validating or serialized == offered_raw,
              "parent worksheet differs from complete original regeneration")
        result = json.loads(serialized)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        source._parent_finish((fence, returned_fence, closing_replay, fence,
                               returned_fence, fence, output_fence), primary)


def build_parent_norm_content_template_v1(preparation, *, expected_preparation_sha256,
        correspondence, expected_correspondence_sha256, correspondence_inputs):
    """Build a blank manual worksheet after exact original parent replay."""
    return _parent_content_operation(preparation, expected_preparation_sha256, correspondence,
        expected_correspondence_sha256, correspondence_inputs)


def validate_parent_norm_content_template_v1(report, preparation, *, expected_report_sha256,
        expected_preparation_sha256, correspondence, expected_correspondence_sha256, correspondence_inputs):
    """Regenerate the exact unsigned worksheet, accepting no completed answers."""
    return _parent_content_operation(preparation, expected_preparation_sha256, correspondence,
        expected_correspondence_sha256, correspondence_inputs, offered=report,
        expected_report_sha256=expected_report_sha256, validating=True)


__all__ += ["build_parent_norm_content_template_v1", "validate_parent_norm_content_template_v1"]


# Explicit filled-but-unsigned parent response. Existing template, signing and
# adjudication profiles remain closed and retain their exact public behavior.
from datetime import datetime as _ParentResponseDateTime
import re as _parent_response_re

PARENT_RESPONSE_SCHEMA = "legal-parent-norm-content-response/v1"
PARENT_RESPONSE_PROFILE = "unsigned-parent-literal-content-response/v1"
PARENT_EVIDENCE_SCHEMA = "legal-parent-norm-response-evidence/v1"
PARENT_MAX_EVIDENCE_ARTIFACTS = 256
PARENT_MAX_EVIDENCE_BYTES = 8 * 1024**2
_PARENT_RESPONSE_ID = _parent_response_re.compile(r"[a-z0-9][a-z0-9_.:@/-]{0,255}\Z")
_PARENT_RESPONSE_UTC = _parent_response_re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_PARENT_RESPONSE_ROLES = frozenset(("legal_review", "formal_review"))


def _parent_response_id(value, label):
    _need(type(value) is str and _PARENT_RESPONSE_ID.fullmatch(value),
          "canonical declared parent response " + label + " required")


def _parent_response_time(value):
    _need(type(value) is str and _PARENT_RESPONSE_UTC.fullmatch(value),
          "explicit declared parent response UTC seconds required")
    try:
        _ParentResponseDateTime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("valid declared parent response UTC calendar required") from error


def _parent_response_refs(values, evidence):
    _need(type(values) is list and len(values) <= 8,
          "bounded ordered parent response evidence references required")
    seen = set()
    for ref in values:
        _keys(ref, {"artifact_id", "sha256"}, "parent response evidence reference")
        _parent_response_id(ref["artifact_id"], "evidence artifact ID")
        _sha(ref["sha256"], "parent response raw evidence")
        _need(ref["artifact_id"] not in seen, "duplicate parent response evidence reference")
        seen.add(ref["artifact_id"])
        _need(evidence.get(ref["artifact_id"]) == ref["sha256"],
              "parent response evidence reference is absent or has another exact raw hash")


def _parent_response_preflight(preparation, response, evidence_manifest, evidence_artifacts,
        expected_response_sha256, expected_evidence_manifest_sha256,
        expected_preparation_sha256, expected_correspondence_sha256,
        *, expected_report_sha256=None):
    """Validate bounded ordinary declarations and every supplied body, before replay.

    The offered preparation is not trusted here. Rejection during this cheap
    pass never substitutes for genuine original-input replay on acceptance.
    """
    _sha(expected_response_sha256, "complete declared parent response input")
    _sha(expected_evidence_manifest_sha256, "complete parent evidence manifest")
    _need(norm_content_sha256(response) == expected_response_sha256,
          "independently pinned complete parent response input differs")
    _need(norm_content_sha256(evidence_manifest) == expected_evidence_manifest_sha256,
          "independently pinned complete parent evidence manifest differs")
    _keys(evidence_manifest, {"schema", "artifacts"}, "parent response evidence manifest")
    _need(evidence_manifest["schema"] == PARENT_EVIDENCE_SCHEMA,
          "explicit unsigned parent response evidence manifest required")
    rows = evidence_manifest["artifacts"]
    _need(type(rows) is list and len(rows) <= PARENT_MAX_EVIDENCE_ARTIFACTS,
          "bounded complete parent response evidence population required")
    _need(type(evidence_artifacts) is dict,
          "explicit exact parent response raw evidence mapping required")
    forbidden = {expected_preparation_sha256, expected_correspondence_sha256, expected_response_sha256}
    if expected_report_sha256 is not None:
        forbidden.add(expected_report_sha256)
    evidence, observations, total = {}, [], 0
    for row in rows:
        _keys(row, {"artifact_id", "bytes", "sha256"}, "parent raw evidence manifest artifact")
        identity = row["artifact_id"]
        _parent_response_id(identity, "evidence artifact ID")
        _sha(row["sha256"], "parent raw evidence artifact")
        _need(identity not in evidence, "duplicate parent evidence manifest identity")
        _need(type(row["bytes"]) is int and 0 < row["bytes"] <= PARENT_MAX_EVIDENCE_BYTES,
              "positive exact integer parent evidence byte count required")
        raw = evidence_artifacts.get(identity)
        _need(type(raw) is bytes and len(raw) == row["bytes"],
              "complete exact parent evidence body is missing or has another byte count")
        total += len(raw)
        _need(total <= PARENT_MAX_EVIDENCE_BYTES,
              "complete parent evidence aggregate byte bound exceeded; no truncation")
        raw_sha = hashlib.sha256(raw).hexdigest()
        _need(raw_sha == row["sha256"], "parent evidence exact raw body SHA256 differs")
        _need(raw_sha not in forbidden,
              "parent response, preparation or correspondence cannot supply direct self-support")
        evidence[identity] = raw_sha
        observations.append({"artifact_id": identity, "bytes": len(raw), "sha256": raw_sha})
    _need(set(evidence_artifacts) == set(evidence),
          "parent raw evidence and manifest must have the exact same complete ID population")
    _keys(response, INPUT_FIELDS, "declared unsigned parent response input")
    for field in ("review_id", "principal_id"):
        _parent_response_id(response[field], field)
    _need(type(response["role"]) is str and response["role"] in _PARENT_RESPONSE_ROLES,
          "declared legal_review or formal_review role required")
    _parent_response_time(response["issued_at_utc"])
    _keys(response["process_declaration"], _PROCESS_FIELDS, "declared parent response process")
    for values in response["process_declaration"].values():
        _parent_response_refs(values, evidence)
    exposure = response["exposure_declaration"]
    _keys(exposure, {"candidate_interpretations_exposed", "organizer_source_metadata_exposed", "other_exposure"},
          "declared parent response exposure")
    for field in ("candidate_interpretations_exposed", "organizer_source_metadata_exposed"):
        _need(exposure[field] is None or type(exposure[field]) is bool,
              "explicit boolean or unknown parent response exposure required")
    if exposure["other_exposure"] is not None:
        _text(exposure["other_exposure"], "declared parent response other exposure")
    _need(response["governing_definition_use"] is None,
          "parent response cannot select governing definition use")
    proposal = response["candidate_proposal"]
    _keys(proposal, {"decision", "typed_expression_sha256", "native_ast_sha256", "rationale", "evidence_refs"},
          "exact existing parent candidate proposal")
    _need(type(proposal["decision"]) is str and proposal["decision"] in {"support", "reject", "unresolved"},
          "explicit parent candidate proposal declaration required")
    _need(proposal["typed_expression_sha256"] == preparation["ast_sha256"]
          and proposal["native_ast_sha256"] == preparation["native_ast_sha256"],
          "parent response candidate differs from exact original typed/native ASTs")
    _text(proposal["rationale"], "declared parent candidate rationale")
    _parent_response_refs(proposal["evidence_refs"], evidence)
    _need(proposal["decision"] == "unresolved" or bool(proposal["evidence_refs"]),
          "parent support or rejection requires supplied raw evidence references")
    obligations = preparation["obligations"]
    _need(type(obligations) is list and 0 < len(obligations) <= norm.MAX_OBLIGATIONS,
          "bounded complete parent review obligation population required")
    answers = response["answers"]
    _need(type(answers) is list and len(answers) == len(obligations),
          "complete ordered parent response answers required")
    unresolved = []
    for answer, obligation in zip(answers, obligations, strict=True):
        _keys(answer, {"slot_id", "kind", "obligation_sha256", "disposition", "rationale", "evidence_refs", "finding"},
              "typed unsigned parent answer")
        _need(answer["slot_id"] == obligation["slot_id"]
              and answer["kind"] == obligation["kind"]
              and answer["obligation_sha256"] == norm_content_sha256(obligation),
              "parent answer differs from exact ordered original obligation")
        _need(type(answer["disposition"]) is str and answer["disposition"] in DISPOSITIONS,
              "explicit parent answer disposition required")
        _text(answer["rationale"], "declared parent answer rationale")
        _parent_response_refs(answer["evidence_refs"], evidence)
        _need(answer["disposition"] == "unresolved" or bool(answer["evidence_refs"]),
              "parent non-unresolved answer requires supplied raw evidence references")
        if obligation["kind"] == "original_parent_context":
            finding = answer["finding"]
            _keys(finding, {"family", "statement", "original_sha256"}, "original parent context finding")
            _need(finding["family"] == "original_parent_context"
                  and finding["original_sha256"] == norm_content_sha256(obligation["original"]),
                  "parent context finding names another original provenance requirement")
            _text(finding["statement"], "declared parent context finding")
            _need(answer["disposition"] == "unresolved",
                  "all original required-unavailable parent context obligations must remain unresolved")
        else:
            # This existing checker is pure: it checks exact existing source,
            # typed/context inventories and unresolved definition applicability.
            _finding(answer["finding"], answer, obligation, preparation["correspondence"])
        if answer["disposition"] == "unresolved":
            unresolved.append(answer["slot_id"])
    return {"evidence_artifact_observations": observations,
            "evidence_bytes": total, "unresolved_obligation_ids": unresolved}


def _parent_response_pins():
    # Reuse the already trusted parent producer closure, not legacy signing or
    # HTML-context owners. A response adds no new product dependency owner.
    return _parent_content_pins()


def _parent_response_render(preparation, response, evidence_manifest, preflight,
        expected_preparation_sha256, expected_response_sha256,
        expected_evidence_manifest_sha256, pins):
    return {"schema": PARENT_RESPONSE_SCHEMA, "profile": PARENT_RESPONSE_PROFILE,
        "status": "declared_unsigned_parent_response_not_authenticated",
        "preparation": preparation, "preparation_sha256": expected_preparation_sha256,
        "correspondence_sha256": preparation["correspondence_sha256"],
        "source_identity": preparation["source_identity"],
        "source_identity_sha256": preparation["source_identity_sha256"],
        "original_parent_context": preparation["original_parent_context"],
        "obligations": preparation["obligations"], "obligation_ids": preparation["obligation_ids"],
        "source_rows": preparation["source_rows"],
        "typed_context_inventory": preparation["typed_context_inventory"],
        "dependency_manifest": preparation["dependency_manifest"],
        "required_dependency_ids": preparation["required_dependency_ids"],
        "response": response, "response_sha256": expected_response_sha256,
        "evidence_manifest": evidence_manifest,
        "evidence_manifest_sha256": expected_evidence_manifest_sha256,
        "evidence_artifact_observations": preflight["evidence_artifact_observations"],
        "evidence_bytes": preflight["evidence_bytes"],
        "unresolved_obligation_ids": preflight["unresolved_obligation_ids"],
        "evidence_references_raw_bytes_matched": True,
        "subject": None, "subject_sha256": None,
        "signature": None, "clock": None, "registry": None, "policy": None,
        "unsigned_only": True, "legacy_signing_or_adjudication_submission_allowed": False,
        "original_signatures_cover_parent_response": False,
        "evidence_identity_verified": False, "evidence_independence_verified": False,
        "evidence_truth_verified": False, "reviewer_declarations_verified": False,
        "external_context_nominations_applied": False,
        "selected_interpretation": None, "accepted_interpretation": None,
        "governing_definition_use": None, "norm_interpretation_ready": False,
        "authority": dict(FALSE_FLAGS),
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "model_calls": 0, "training_calls": 0, "native_processes": 0,
        "producer_pins": pins,
        "limitations": [
            "This is a structurally checked unsigned declaration, not an authenticated human review, accepted interpretation, signing subject or content adjudication.",
            "Every supplied raw evidence body is present and byte-hash bound to the complete independent manifest. Matching bytes do not establish evidence identity, independence, truth or relevance.",
            "Direct exact response/preparation/correspondence body hashes cannot supply self-support; alternate encodings or substantively circular documents are not adjudicated by this structural check.",
            "All six original required-unavailable parent context requirements and definition applicability remain unresolved; declarations cannot change the original occurrence, context or undeclared edition.",
            "Candidate support/rejection and non-unresolved non-context answers remain caller proposals only. Source/typed assertions do not resolve legal meaning, exhaustiveness or every-use definition applicability.",
            "The whole selected literal may be an interior fragment or unclassified region. No source authenticity, governing choice, graph admission, model/training target, solver or Lean process is supplied.",
            "Existing template, signed response, declaration-binding and adjudication consumers retain their closed profiles and do not accept this response as authority.",
        ]}


def _parent_response_operation(preparation, response, expected_preparation_sha256,
        expected_response_sha256, evidence_manifest, expected_evidence_manifest_sha256,
        evidence_artifacts, correspondence, expected_correspondence_sha256, correspondence_inputs,
        *, offered=None, expected_report_sha256=None, validating=False):
    _sha(expected_preparation_sha256, "complete unsigned parent preparation")
    _sha(expected_correspondence_sha256, "complete parent correspondence")
    original = dict(preparation=preparation, response=response,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_response_sha256=expected_response_sha256,
        evidence_manifest=evidence_manifest,
        expected_evidence_manifest_sha256=expected_evidence_manifest_sha256,
        evidence_artifacts=evidence_artifacts, correspondence=correspondence,
        expected_correspondence_sha256=expected_correspondence_sha256,
        correspondence_inputs=correspondence_inputs, offered=offered,
        expected_report_sha256=expected_report_sha256)
    detached, commitment = norm._snapshot(original)
    preparation_raw = norm._wire(detached["preparation"])
    _need(hashlib.sha256(preparation_raw).hexdigest() == expected_preparation_sha256,
          "independently pinned complete parent preparation differs")
    _need(type(detached["preparation"]) is dict
          and detached["preparation"].get("schema") == norm.PARENT_PREPARATION_SCHEMA
          and detached["preparation"].get("profile") == norm.PARENT_REVIEW_PROFILE,
          "explicit unsigned parent review preparation required")
    _need(norm.norm_review_sha256(detached["correspondence"]) == expected_correspondence_sha256,
          "independently pinned complete parent correspondence differs")
    if validating:
        _sha(expected_report_sha256, "complete declared unsigned parent response report")
        offered_raw = norm._wire(detached["offered"])
        _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
              "independently pinned complete parent response report differs")
        _need(type(detached["offered"]) is dict
              and detached["offered"].get("schema") == PARENT_RESPONSE_SCHEMA
              and detached["offered"].get("profile") == PARENT_RESPONSE_PROFILE,
              "explicit unsigned parent response profile required")
    else:
        offered_raw = None
    parsed_correspondence = norm._parent_review_preflight(detached["correspondence"],
        detached["correspondence_inputs"])
    try:
        parsed_response = _parent_response_preflight(detached["preparation"], detached["response"],
            detached["evidence_manifest"], detached["evidence_artifacts"],
            expected_response_sha256, expected_evidence_manifest_sha256,
            expected_preparation_sha256, expected_correspondence_sha256,
            expected_report_sha256=expected_report_sha256 if validating else None)
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("closed original parent response input inventories required") from error
    parsed = {"correspondence": parsed_correspondence, "response": parsed_response}
    parsed_raw = norm._wire(parsed)
    pins = _parent_response_pins()
    trusted = norm._parent_review_pins(norm._parent_review_owners())
    _need(norm._same(detached["preparation"].get("producer_pins"), trusted),
          "parent preparation producer commitments differ from trusted owners")
    source = norm._parent_review_owners()[2]
    opening = checked = result = serialized = opening_raw = None
    closing_returns = []
    replay_started = False
    primary = None
    encoder = lambda value, maximum: norm._wire(value)

    def input_fence():
        _need(norm._parent_review_fingerprint(original) == commitment
              and norm._parent_review_fingerprint(detached) == commitment,
              "parent response caller or detached inputs changed during operation")
        _need(norm._parent_review_pure_wire(parsed) == parsed_raw,
              "parent response parsed declarations changed during operation")

    def fence():
        _need(_parent_response_pins() == pins, "parent response producers changed during operation")
        input_fence()

    def pure_returned_fence():
        if opening_raw is not None:
            _need(norm._parent_review_pure_wire(opening) == opening_raw
                  and norm._parent_review_pure_wire(checked) == opening_raw,
                  "parent response returned preparation changed during operation")
        for value, raw in closing_returns:
            _need(norm._parent_review_pure_wire(value) == raw,
                  "parent response retained closing return changed during operation")

    def returned_fence():
        if opening_raw is not None:
            source._parent_serialized_fence(opening, opening_raw, norm.MAX_BYTES, encoder)
            source._parent_serialized_fence(checked, opening_raw, norm.MAX_BYTES, encoder)

    def replay():
        return norm.validate_parent_norm_review_evidence_v1(detached["preparation"],
            detached["correspondence"], expected_report_sha256=expected_preparation_sha256,
            expected_correspondence_sha256=expected_correspondence_sha256,
            correspondence_inputs=detached["correspondence_inputs"])

    def closing_replay():
        if replay_started:
            closing = replay()
            source._parent_serialized_fence(closing, preparation_raw, norm.MAX_BYTES, encoder)
            closing_returns.append((closing, preparation_raw))

    def output_fence():
        if serialized is not None:
            def final_encoder(value, maximum):
                raw = encoder(value, maximum)
                _need(_parent_response_pins() == pins,
                      "parent response producers changed after final encoding")
                input_fence()
                pure_returned_fence()
                return raw
            source._parent_serialized_fence(result, serialized, norm.MAX_BYTES, final_encoder)

    try:
        fence()
        replay_started = True
        opening = replay()
        opening_raw = norm._wire(opening)
        _need(opening_raw == preparation_raw, "validated parent preparation changed after return")
        checked = json.loads(opening_raw)
        fence()
        result = _parent_response_render(checked, detached["response"], detached["evidence_manifest"],
            parsed["response"], expected_preparation_sha256, expected_response_sha256,
            expected_evidence_manifest_sha256, pins)
        serialized = norm._wire(result)
        _need(not validating or serialized == offered_raw,
              "unsigned parent response report differs from complete original regeneration")
        result = json.loads(serialized)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        source._parent_finish((fence, returned_fence, closing_replay, fence,
                               returned_fence, fence, output_fence), primary)


def build_parent_norm_content_response_v1(preparation, response, *, expected_preparation_sha256,
        expected_response_sha256, evidence_manifest, expected_evidence_manifest_sha256,
        evidence_artifacts, correspondence, expected_correspondence_sha256, correspondence_inputs):
    """Bind supplied typed declarations and raw evidence; authenticate no review."""
    return _parent_response_operation(preparation, response, expected_preparation_sha256,
        expected_response_sha256, evidence_manifest, expected_evidence_manifest_sha256,
        evidence_artifacts, correspondence, expected_correspondence_sha256, correspondence_inputs)


def validate_parent_norm_content_response_v1(report, preparation, response, *, expected_report_sha256,
        expected_preparation_sha256, expected_response_sha256, evidence_manifest,
        expected_evidence_manifest_sha256, evidence_artifacts, correspondence,
        expected_correspondence_sha256, correspondence_inputs):
    """Regenerate the entire unsigned parent declaration from all original inputs."""
    return _parent_response_operation(preparation, response, expected_preparation_sha256,
        expected_response_sha256, evidence_manifest, expected_evidence_manifest_sha256,
        evidence_artifacts, correspondence, expected_correspondence_sha256, correspondence_inputs,
        offered=report, expected_report_sha256=expected_report_sha256, validating=True)


__all__ += ["build_parent_norm_content_response_v1", "validate_parent_norm_content_response_v1"]


# A bounded inventory of supplied unsigned parent declarations.  This is not
# the legacy signed assessment, a quorum, a selected view or content adjudication.
PARENT_COLLECTION_SCHEMA = "legal-parent-norm-content-collection/v1"
PARENT_COLLECTION_PROFILE = "unsigned-parent-literal-response-collection/v1"
PARENT_POPULATION_SCHEMA = "legal-parent-norm-response-population/v1"
PARENT_COLLECTION_VARIANT_SCHEMA = "legal-parent-norm-content-answer-variant/v1"
PARENT_COLLECTION_PENDING_SCHEMA = "legal-parent-norm-content-pending-question/v1"
PARENT_MAX_COLLECTION_RESPONSES = 32


def _parent_collection_preflight(preparation, population_manifest, reports, evidence_artifacts,
        expected_preparation_sha256, expected_correspondence_sha256, *, expected_report_sha256=None):
    """Check the full ordered JSON population and all raw bodies before replay."""
    _keys(population_manifest, {"schema", "responses"}, "parent response population manifest")
    _need(population_manifest["schema"] == PARENT_POPULATION_SCHEMA,
          "explicit unsigned parent response population required")
    rows = population_manifest["responses"]
    _need(type(rows) is list and len(rows) <= PARENT_MAX_COLLECTION_RESPONSES,
          "bounded complete parent response population required")
    _need(type(reports) is list and type(evidence_artifacts) is list
          and len(reports) == len(rows) == len(evidence_artifacts),
          "one ordered report and raw evidence mapping per population row required")
    forbidden = {expected_preparation_sha256, expected_correspondence_sha256,
                 norm_content_sha256(population_manifest)}
    if expected_report_sha256 is not None:
        forbidden.add(expected_report_sha256)
    seen = set()
    for row, report in zip(rows, reports, strict=True):
        _keys(row, {"review_id", "report_sha256"}, "parent response population row")
        _parent_response_id(row["review_id"], "population review_id")
        _sha(row["report_sha256"], "complete population member report")
        _need(row["review_id"] not in seen, "duplicate population review_id is not deduplicated")
        seen.add(row["review_id"])
        _need(norm_content_sha256(report) == row["report_sha256"],
              "independently pinned complete population member report differs")
        _need(type(report) is dict and report.get("schema") == PARENT_RESPONSE_SCHEMA
              and report.get("profile") == PARENT_RESPONSE_PROFILE,
              "explicit current raw-evidence unsigned parent response report required")
        _need(report["preparation_sha256"] == expected_preparation_sha256
              and report["correspondence_sha256"] == expected_correspondence_sha256,
              "collection member belongs to another exact parent preparation or correspondence")
        _need(type(report["response"]) is dict and report["response"]["review_id"] == row["review_id"],
              "population review identity differs from exact response declaration")
        _sha(report["response_sha256"], "complete member input response")
        forbidden.add(row["report_sha256"])
        forbidden.add(report["response_sha256"])
    members, total = [], 0
    for row, report, evidence in zip(rows, reports, evidence_artifacts, strict=True):
        checked = _parent_response_preflight(preparation, report["response"], report["evidence_manifest"],
            evidence, report["response_sha256"], report["evidence_manifest_sha256"],
            expected_preparation_sha256, expected_correspondence_sha256,
            expected_report_sha256=row["report_sha256"])
        _need(norm._same(report["evidence_artifact_observations"], checked["evidence_artifact_observations"])
              and type(report["evidence_bytes"]) is int and report["evidence_bytes"] == checked["evidence_bytes"]
              and norm._same(report["unresolved_obligation_ids"], checked["unresolved_obligation_ids"]),
              "member retained raw-evidence custody inventory differs from complete original declarations")
        total += checked["evidence_bytes"]
        _need(total <= PARENT_MAX_EVIDENCE_BYTES,
              "whole collection raw evidence byte bound exceeded; no truncation")
        _need(all(item["sha256"] not in forbidden
                  for item in checked["evidence_artifact_observations"]),
              "collection member, population or shared preparation bodies cannot supply cohort support")
        members.append({"review_id": row["review_id"], "report_sha256": row["report_sha256"],
            "response_sha256": report["response_sha256"],
            "evidence_manifest_sha256": report["evidence_manifest_sha256"],
            "evidence_artifact_observations": checked["evidence_artifact_observations"],
            "evidence_bytes": checked["evidence_bytes"]})
    return {"members": members, "evidence_bytes": total}


def _parent_collection_pins():
    return _parent_response_pins()


def _parent_collection_render(preparation, population_manifest, validated, preflight,
        expected_preparation_sha256, expected_population_manifest_sha256, pins):
    results, proposals, variants, pending = [], [], [], []
    principal_counts = {}
    for index, (report, member) in enumerate(zip(validated, preflight["members"], strict=True)):
        response = report["response"]
        principal_counts[response["principal_id"]] = principal_counts.get(response["principal_id"], 0) + 1
        results.append({"response_index": index, "review_id": response["review_id"],
            "principal_id": response["principal_id"], "role": response["role"],
            "report_sha256": member["report_sha256"], "response_sha256": member["response_sha256"],
            "evidence_manifest_sha256": member["evidence_manifest_sha256"],
            "response_record": response, "authenticated": False})
        proposals.append({"response_result_index": index, "review_id": response["review_id"],
            "principal_id": response["principal_id"], "role": response["role"],
            "report_sha256": member["report_sha256"], "proposal": response["candidate_proposal"]})
    legal = [row for row in results if row["role"] == "legal_review"]
    formal = [row for row in results if row["role"] == "formal_review"]
    pair = any(left["principal_id"] != right["principal_id"] for left in legal for right in formal)
    repeated = [identity for identity, count in principal_counts.items() if count > 1]
    for index, obligation in enumerate(preparation["obligations"]):
        buckets = {}
        for row in results:
            answer = row["response_record"]["answers"][index]
            digest = norm_content_sha256(answer)
            bucket = buckets.setdefault(digest, {"answer": answer, "respondents": []})
            bucket["respondents"].append({"response_result_index": row["response_index"],
                "review_id": row["review_id"], "principal_id": row["principal_id"],
                "role": row["role"], "report_sha256": row["report_sha256"]})
        refs, respondents = [], []
        for digest, bucket in buckets.items():
            variant = {"schema": PARENT_COLLECTION_VARIANT_SCHEMA, "profile": PARENT_COLLECTION_PROFILE,
                "slot_id": obligation["slot_id"], "answer_sha256": digest,
                "answer": bucket["answer"], "respondents": bucket["respondents"]}
            variants.append(variant)
            refs.append({"variant_index": len(variants) - 1, "sha256": norm_content_sha256(variant)})
            respondents.extend(bucket["respondents"])
        issues = ["unsigned_declarations_not_authenticated", "separate_review_and_adjudication_required"]
        if not respondents:
            issues.append("no_supplied_declared_answer")
        if any(bucket["answer"]["disposition"] == "unresolved" for bucket in buckets.values()):
            issues.append("unresolved_typed_answer")
        if len(buckets) > 1:
            issues.append("distinct_exact_answer_variants")
        if not legal:
            issues.append("declared_legal_role_missing")
        if not formal:
            issues.append("declared_formal_role_missing")
        if not pair:
            issues.append("distinct_declared_role_principal_pair_missing")
        if repeated:
            issues.append("repeated_declared_principal_id")
        if obligation["kind"] == "original_parent_context":
            issues.append("original_parent_context_required_unavailable")
        if obligation["kind"] == "original_unresolved_issue":
            issues.append("original_unresolved_issue_retained")
        if obligation.get("question") == "definition_applicability":
            issues.append("definition_applicability_unresolved")
        pending.append({"schema": PARENT_COLLECTION_PENDING_SCHEMA, "profile": PARENT_COLLECTION_PROFILE,
            "slot_id": obligation["slot_id"], "kind": obligation["kind"],
            "obligation_sha256": norm_content_sha256(obligation), "answer_variant_refs": refs,
            "declared_respondents": respondents, "issues": issues, "decision": None,
            "adjudicator_declaration": None, "status": "pending_unsigned_declarations_not_a_decision"})
    return {"schema": PARENT_COLLECTION_SCHEMA, "profile": PARENT_COLLECTION_PROFILE,
        "status": "all_supplied_unsigned_parent_declarations_retained_no_decision",
        "preparation": preparation, "preparation_sha256": expected_preparation_sha256,
        "correspondence_sha256": preparation["correspondence_sha256"],
        "source_identity": preparation["source_identity"],
        "source_identity_sha256": preparation["source_identity_sha256"],
        "original_parent_context": preparation["original_parent_context"],
        "original_obligations": preparation["obligations"], "obligation_ids": preparation["obligation_ids"],
        "source_rows": preparation["source_rows"], "typed_context_inventory": preparation["typed_context_inventory"],
        "dependency_manifest": preparation["dependency_manifest"],
        "required_dependency_ids": preparation["required_dependency_ids"],
        "population_manifest": population_manifest,
        "population_manifest_sha256": expected_population_manifest_sha256,
        "response_results": results, "candidate_proposals": proposals, "answer_variants": variants,
        "pending_questions": pending, "member_evidence_observations": preflight["members"],
        "evidence_bytes": preflight["evidence_bytes"],
        "repeated_declared_principal_ids": repeated,
        "distinct_declared_role_principal_pair_present": pair,
        "supplied_population_fully_replayed": True,
        "coverage_scope": "one_exact_parent_candidate_all_original_obligations_and_all_supplied_declarations",
        "subject": None, "subject_sha256": None, "signature": None,
        "clock": None, "registry": None, "policy": None,
        "unsigned_only": True, "legacy_signing_or_adjudication_submission_allowed": False,
        "declared_roles_authenticated": False, "reviewer_declarations_verified": False,
        "evidence_identity_verified": False, "evidence_independence_verified": False,
        "evidence_truth_verified": False, "quorum_established": False,
        "source_context_closed": False, "external_context_nominations_applied": False,
        "selected_interpretation": None, "accepted_interpretation": None,
        "governing_definition_use": None, "norm_interpretation_ready": False,
        "authority": dict(FALSE_FLAGS), "producer_pins": pins,
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "model_calls": 0, "training_calls": 0, "native_processes": 0,
        "counts": {"responses": len(results), "answer_variants": len(variants),
            "pending_questions": len(pending), "declared_legal_role": len(legal),
            "declared_formal_role": len(formal), "authenticated_responses": 0,
            "applied_meaning_decisions": 0},
        "limitations": [
            "This inventory retains exactly the supplied ordered population, not all existing reviews, a legal census or an authenticated cohort.",
            "Full exact answer bytes, including rationale, findings and evidence references, define variants in first-seen order. Different variants are not a semantic inconsistency proof or a vote.",
            "Repeated principal declarations are retained, not deduplicated or treated as independent humans. Different principal strings across roles do not establish identity, independence, competence, authentication or quorum.",
            "All unavailable parent-context requirements, source issues and definition applicability remain unresolved. No governing edition, accepted meaning or adjudicator decision is supplied.",
            "Exact cohort response/report/population body hashes cannot supply supporting evidence. Alternate encodings, substantive circularity, evidence relevance, truth and actual independence are not adjudicated.",
            "Full member reports must be freshly rebuilt under the selected producer generation from complete original response/evidence/replay inputs. Historical source-pinned reports are never normalized or re-labelled as current.",
            "Existing signed assessment and adjudication profiles remain closed; this unsigned collection supplies no graph, model, training/gold, solver or Lean admission.",
        ]}


def _parent_collection_operation(preparation, population_manifest, reports, expected_preparation_sha256,
        expected_population_manifest_sha256, evidence_artifacts, correspondence,
        expected_correspondence_sha256, correspondence_inputs, *, offered=None,
        expected_report_sha256=None, validating=False):
    _sha(expected_preparation_sha256, "complete unsigned parent preparation")
    _sha(expected_correspondence_sha256, "complete parent correspondence")
    _sha(expected_population_manifest_sha256, "complete ordered parent response population")
    original = dict(preparation=preparation, population_manifest=population_manifest, reports=reports,
        expected_preparation_sha256=expected_preparation_sha256,
        expected_population_manifest_sha256=expected_population_manifest_sha256,
        evidence_artifacts=evidence_artifacts, correspondence=correspondence,
        expected_correspondence_sha256=expected_correspondence_sha256,
        correspondence_inputs=correspondence_inputs, offered=offered,
        expected_report_sha256=expected_report_sha256)
    detached, commitment = norm._snapshot(original)
    preparation_raw = norm._wire(detached["preparation"])
    _need(hashlib.sha256(preparation_raw).hexdigest() == expected_preparation_sha256,
          "independently pinned complete parent preparation differs")
    _need(type(detached["preparation"]) is dict
          and detached["preparation"].get("schema") == norm.PARENT_PREPARATION_SCHEMA
          and detached["preparation"].get("profile") == norm.PARENT_REVIEW_PROFILE,
          "explicit unsigned parent review preparation required")
    _need(norm_content_sha256(detached["correspondence"]) == expected_correspondence_sha256,
          "independently pinned complete parent correspondence differs")
    _need(norm_content_sha256(detached["population_manifest"]) == expected_population_manifest_sha256,
          "independently pinned complete ordered parent response population differs")
    if validating:
        _sha(expected_report_sha256, "complete unsigned parent response collection")
        offered_raw = norm._wire(detached["offered"])
        _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
              "independently pinned complete parent response collection differs")
        _need(type(detached["offered"]) is dict
              and detached["offered"].get("schema") == PARENT_COLLECTION_SCHEMA
              and detached["offered"].get("profile") == PARENT_COLLECTION_PROFILE,
              "explicit unsigned parent response collection profile required")
    else:
        offered_raw = None
    parsed_correspondence = norm._parent_review_preflight(detached["correspondence"],
        detached["correspondence_inputs"])
    try:
        parsed_population = _parent_collection_preflight(detached["preparation"],
            detached["population_manifest"], detached["reports"], detached["evidence_artifacts"],
            expected_preparation_sha256, expected_correspondence_sha256,
            expected_report_sha256=expected_report_sha256 if validating else None)
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("closed original parent response population inventories required") from error
    parsed = {"correspondence": parsed_correspondence, "population": parsed_population}
    parsed_raw = norm._wire(parsed)
    pins = _parent_collection_pins()
    trusted = norm._parent_review_pins(norm._parent_review_owners())
    _need(norm._same(detached["preparation"].get("producer_pins"), trusted),
          "parent preparation producer commitments differ from trusted owners")
    _need(all(norm._same(report.get("producer_pins"), pins) for report in detached["reports"]),
          "member reports require fresh complete regeneration under selected producer generation")
    source = norm._parent_review_owners()[2]
    opening = checked = result = serialized = opening_raw = None
    retained, validated = [], []
    replay_started = False
    primary = None
    encoder = lambda value, maximum: norm._wire(value)

    def input_fence():
        _need(norm._parent_review_fingerprint(original) == commitment
              and norm._parent_review_fingerprint(detached) == commitment,
              "parent collection caller or detached population inputs changed during operation")
        _need(norm._parent_review_pure_wire(parsed) == parsed_raw,
              "parent collection parsed population changed during operation")

    def fence():
        _need(_parent_collection_pins() == pins, "parent collection producers changed during operation")
        input_fence()

    def pure_returned_fence():
        if opening_raw is not None:
            _need(norm._parent_review_pure_wire(opening) == opening_raw
                  and norm._parent_review_pure_wire(checked) == opening_raw,
                  "parent collection returned shared preparation changed during operation")
        for value, raw in retained:
            _need(norm._parent_review_pure_wire(value) == raw,
                  "parent collection retained genuine member or closing return changed during operation")

    def returned_fence():
        if opening_raw is not None:
            source._parent_serialized_fence(opening, opening_raw, norm.MAX_BYTES, encoder)
            source._parent_serialized_fence(checked, opening_raw, norm.MAX_BYTES, encoder)
        for value, raw in retained:
            source._parent_serialized_fence(value, raw, norm.MAX_BYTES, encoder)

    def replay_preparation():
        return norm.validate_parent_norm_review_evidence_v1(detached["preparation"],
            detached["correspondence"], expected_report_sha256=expected_preparation_sha256,
            expected_correspondence_sha256=expected_correspondence_sha256,
            correspondence_inputs=detached["correspondence_inputs"])

    def closing_replay():
        if replay_started:
            closing = replay_preparation()
            source._parent_serialized_fence(closing, preparation_raw, norm.MAX_BYTES, encoder)
            retained.append((closing, preparation_raw))

    def output_fence():
        if serialized is not None:
            def final_encoder(value, maximum):
                raw = encoder(value, maximum)
                _need(_parent_collection_pins() == pins,
                      "parent collection producers changed after final encoding")
                input_fence()
                pure_returned_fence()
                return raw
            source._parent_serialized_fence(result, serialized, norm.MAX_BYTES, final_encoder)

    try:
        fence()
        replay_started = True
        if not detached["reports"]:
            opening = replay_preparation()
            opening_raw = norm._wire(opening)
            _need(opening_raw == preparation_raw, "validated empty-population preparation changed after return")
            checked = json.loads(opening_raw)
            fence()
        for report, member, raw_evidence in zip(detached["reports"], parsed_population["members"],
                                                detached["evidence_artifacts"], strict=True):
            value = validate_parent_norm_content_response_v1(report, detached["preparation"], report["response"],
                expected_report_sha256=member["report_sha256"],
                expected_preparation_sha256=expected_preparation_sha256,
                expected_response_sha256=report["response_sha256"],
                evidence_manifest=report["evidence_manifest"],
                expected_evidence_manifest_sha256=report["evidence_manifest_sha256"],
                evidence_artifacts=raw_evidence, correspondence=detached["correspondence"],
                expected_correspondence_sha256=expected_correspondence_sha256,
                correspondence_inputs=detached["correspondence_inputs"])
            raw = norm._wire(value)
            _need(hashlib.sha256(raw).hexdigest() == member["report_sha256"],
                  "genuine member report changed after complete original validation")
            retained.append((value, raw))
            member_preparation_raw = norm._wire(value["preparation"])
            _need(member_preparation_raw == preparation_raw,
                  "genuine member contains another complete shared parent preparation")
            if opening_raw is None:
                opening = value["preparation"]
                opening_raw = member_preparation_raw
                checked = json.loads(opening_raw)
            detached_value = json.loads(raw)
            retained.append((detached_value, raw))
            validated.append(detached_value)
            fence()
        result = _parent_collection_render(checked, detached["population_manifest"], validated,
            parsed_population, expected_preparation_sha256, expected_population_manifest_sha256, pins)
        serialized = norm._wire(result)
        _need(not validating or serialized == offered_raw,
              "unsigned collection differs from complete original population regeneration")
        result = json.loads(serialized)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        source._parent_finish((fence, returned_fence, closing_replay, fence,
                               returned_fence, fence, output_fence), primary)


def collect_parent_norm_content_responses_v1(preparation, population_manifest, reports, *,
        expected_preparation_sha256, expected_population_manifest_sha256, evidence_artifacts,
        correspondence, expected_correspondence_sha256, correspondence_inputs):
    """Retain all supplied current declarations and exact variants, choosing none."""
    return _parent_collection_operation(preparation, population_manifest, reports,
        expected_preparation_sha256, expected_population_manifest_sha256, evidence_artifacts,
        correspondence, expected_correspondence_sha256, correspondence_inputs)


def validate_parent_norm_content_collection_v1(report, preparation, population_manifest, reports, *,
        expected_report_sha256, expected_preparation_sha256, expected_population_manifest_sha256,
        evidence_artifacts, correspondence, expected_correspondence_sha256, correspondence_inputs):
    """Regenerate the whole unsigned collection from the complete original population."""
    return _parent_collection_operation(preparation, population_manifest, reports,
        expected_preparation_sha256, expected_population_manifest_sha256, evidence_artifacts,
        correspondence, expected_correspondence_sha256, correspondence_inputs,
        offered=report, expected_report_sha256=expected_report_sha256, validating=True)


__all__ += ["collect_parent_norm_content_responses_v1", "validate_parent_norm_content_collection_v1"]
