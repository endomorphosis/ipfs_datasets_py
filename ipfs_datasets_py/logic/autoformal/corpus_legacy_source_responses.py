"""Typed legacy source responses and explicit pending disagreements.

Reuses the legacy source replay/signature owner and the typed-answer protocol
from the historical complete-parent response owner. The latter's lineage
profile is not imported or impersonated. No source decision, legal meaning,
training admission, signer, policy or reviewer is manufactured here.
"""
from __future__ import annotations

import hashlib
import json

from . import corpus_contracts as contracts
from . import corpus_legacy_source_review as source
from . import legal_graph_review as auth

PROFILE = "typed-legacy-source-context-responses/v1"
RESPONSE_SCHEMA = "legal-corpus-legacy-source-response/v1"
TEMPLATE_SCHEMA = "legal-corpus-legacy-source-response-template/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-response-assessment/v1"
RESULT_SCHEMA = "legal-corpus-legacy-source-response-result/v1"
VARIANT_SCHEMA = "legal-corpus-legacy-source-answer-variant/v1"
PENDING_SCHEMA = "legal-corpus-legacy-source-pending-question/v1"
FALSE_FLAGS = {**source.FALSE_FLAGS, **dict.fromkeys(("typed_source_decisions_applied",
    "adjudication_accepted", "answer_content_establishes_legal_truth", "reviewer_competence_verified",
    "accepted_view_eligible"), False)}
INPUT_FIELDS = {"review_id", "principal_id", "role", "issued_at_utc", "process_declaration",
                "exposure_declaration", "answers", "occurrence_proposal"}
DISPOSITIONS = {"unresolved": "open", "evidence_declared": "resolved_by_evidence",
                "not_applicable": "not_applicable"}
FINDINGS = {"unavailable": "unresolved", "ambiguous": "unresolved",
            "evidence_declared": "evidence_declared", "not_applicable": "not_applicable"}
_SOURCE_FIELDS = {"request_ordinal", "expected_preparation_manifest_sha256", "expected_registry_sha256",
    "expected_policy_sha256", "expected_reviews_sha256", "at_time_utc", "observed_artifact_sha256s",
    "observed_pins", "evidence_artifacts", "join_bytes", "paired_row_bytes", "expected_join_sha256",
    "expected_population", "producer_receipt_bytes", "expected_producer_receipt_sha256",
    "source_sections", "expected_source_sections"}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return auth.digest(value)


def _ref(record):
    return {"record_cid": record["record_cid"], "sha256": _digest(record), "schema": record["schema"]}


def _seal(schema, **values):
    return contracts.seal_record({"schema": schema, "profile": PROFILE, **values,
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED})


def _refs(values):
    if type(values) is not list or len(values) > 8:
        _fail("bounded ordered response evidence references required")
    seen = set()
    for item in values:
        contracts.require_keys(item, {"artifact_id", "sha256"}, "response evidence reference")
        auth._id(item["artifact_id"], "response evidence ID")
        contracts.require_sha256(item["sha256"], "response evidence SHA256")
        if item["artifact_id"] in seen:
            _fail("duplicate response evidence identity")
        seen.add(item["artifact_id"])


def _preparation(preparation, request_ordinal, expected_preparation_manifest_sha256, **join_inputs):
    detached = source._detach(preparation)
    contracts.require_sha256(expected_preparation_manifest_sha256, "preparation SHA256")
    if _digest(detached["manifest"]) != expected_preparation_manifest_sha256:
        _fail("independently pinned response preparation differs")
    contracts.require_int(request_ordinal, "request ordinal", maximum=len(detached["requests"]) - 1)
    return source.validate_legacy_source_review_requests(detached, **join_inputs)


def _record(request, subject, response, preparation_sha256):
    """Called only with a fully replayed preparation, or after its assessment."""
    response = contracts.clone_json(response)
    contracts.require_keys(response, INPUT_FIELDS, "legacy source response input")
    for field in ("review_id", "principal_id"):
        auth._id(response[field], "response " + field)
    if response["role"] not in auth.ROLES:
        _fail("explicit legal or formal response role required")
    auth._time(response["issued_at_utc"])
    process = response["process_declaration"]
    contracts.require_keys(process, {"identity_evidence_refs", "independence_evidence_refs",
                                   "process_evidence_refs"}, "response process declaration")
    for values in process.values():
        _refs(values)
    exposure = response["exposure_declaration"]
    contracts.require_keys(exposure, {"candidate_interpretations_exposed", "organizer_source_metadata_exposed",
                                    "other_exposure"}, "response exposure declaration")
    for field in ("candidate_interpretations_exposed", "organizer_source_metadata_exposed"):
        if exposure[field] is not None and type(exposure[field]) is not bool:
            _fail("explicit boolean or unknown exposure required")
    if exposure["other_exposure"] is not None:
        contracts.require_text(exposure["other_exposure"], "other exposure", max_bytes=8192)
    active = [q for q in request["review_questions"]
              if q["assessment_scope"] == "source_context_evidence_declaration"]
    answers = response["answers"]
    if type(answers) is not list or len(answers) != 9 or len(active) != 9:
        _fail("complete ordered nine source answers required")
    for answer, question in zip(answers, active, strict=True):
        contracts.require_keys(answer, {"slot_id", "category", "kind", "disposition", "finding",
                                      "rationale", "evidence_refs"}, "typed source answer")
        if any(answer[key] != question[key] for key in ("slot_id", "category", "kind")):
            _fail("answer differs from exact ordered source question")
        finding = answer["finding"]
        contracts.require_keys(finding, {"status", "statement"}, "typed source finding")
        if (type(finding["status"]) is not str or type(answer["disposition"]) is not str
                or finding["status"] not in FINDINGS or answer["disposition"] not in DISPOSITIONS
                or FINDINGS[finding["status"]] != answer["disposition"]):
            _fail("unknown or ambiguous finding cannot be a resolved answer")
        contracts.require_text(finding["statement"], "source finding", max_bytes=8192)
        contracts.require_text(answer["rationale"], "answer rationale", max_bytes=8192)
        _refs(answer["evidence_refs"])
        if answer["disposition"] != "unresolved" and not answer["evidence_refs"]:
            _fail("resolved or not-applicable declaration needs evidence")
    proposal = response["occurrence_proposal"]
    contracts.require_keys(proposal, {"status", "candidate_occurrence_cid", "rationale", "evidence_refs"},
                           "present-day occurrence proposal")
    contracts.require_text(proposal["rationale"], "occurrence proposal rationale", max_bytes=8192)
    _refs(proposal["evidence_refs"])
    candidates = {item["source_occurrence"]["record_cid"]: item["source_occurrence"]
                  for item in request["original_row"]["candidates"]}
    selected = proposal["candidate_occurrence_cid"]
    if proposal["status"] == "unresolved":
        if selected is not None:
            _fail("unresolved proposal cannot name a selected candidate")
    elif proposal["status"] == "proposed_present_day":
        contracts.require_cid(selected, "proposed candidate occurrence", codecs=("dag-json",))
        if selected not in candidates or not proposal["evidence_refs"]:
            _fail("present-day proposal needs an original candidate and exact evidence")
    else:
        _fail("unsupported occurrence proposal status")
    return _seal(RESPONSE_SCHEMA, request_ref=_ref(request), subject_ref=_ref(subject),
        preparation_manifest_sha256=preparation_sha256,
        dependency_manifest_sha256=subject["dependency_manifest_sha256"],
        request_ordinal=request["queue_ordinal"], source_binding_sha256=request["source_binding_sha256"],
        questions_sha256=request["questions_sha256"], **response,
        proposed_occurrence_ref=None if selected is None else _ref(candidates[selected]),
        occurrence_proposal_scope="present_day_proposal_only_not_historical_producer_attestation",
        deferred_review_slot_ids=request["deferred_review_slot_ids"],
        status="declared_unauthenticated_source_response")


def record_legacy_source_response(preparation, response, *, request_ordinal,
        expected_preparation_manifest_sha256, **join_inputs):
    """Record explicit supplied answers; authoring authenticates no declaration."""
    response = contracts.clone_json(response)
    checked = _preparation(preparation, request_ordinal, expected_preparation_manifest_sha256, **join_inputs)
    return _record(checked["requests"][request_ordinal], checked["subjects"][request_ordinal],
                   response, expected_preparation_manifest_sha256)


def validate_legacy_source_response(record, *args, **kwargs):
    checked = contracts.clone_json(record)
    expected = record_legacy_source_response(*args, **kwargs)
    if auth.wire(checked) != auth.wire(expected):
        _fail("typed legacy response differs from exact original declarations")
    return checked


def prepare_legacy_source_response_template(preparation, *, request_ordinal,
        expected_preparation_manifest_sha256, **join_inputs):
    """Prepare an explicitly blank, unsubmitted template; nulls are not answers."""
    checked = _preparation(preparation, request_ordinal, expected_preparation_manifest_sha256, **join_inputs)
    request, subject = checked["requests"][request_ordinal], checked["subjects"][request_ordinal]
    response = {"review_id": None, "principal_id": None, "role": None, "issued_at_utc": None,
        "process_declaration": {key: [] for key in ("identity_evidence_refs", "independence_evidence_refs", "process_evidence_refs")},
        "exposure_declaration": {key: None for key in ("candidate_interpretations_exposed", "organizer_source_metadata_exposed", "other_exposure")},
        "answers": [{**{key: q[key] for key in ("slot_id", "category", "kind")},
            "disposition": None, "finding": {"status": None, "statement": None},
            "rationale": None, "evidence_refs": []} for q in request["review_questions"]
            if q["assessment_scope"] == "source_context_evidence_declaration"],
        "occurrence_proposal": {"status": None, "candidate_occurrence_cid": None,
                                "rationale": None, "evidence_refs": []}}
    return _seal(TEMPLATE_SCHEMA, request_ref=_ref(request), subject_ref=_ref(subject),
        preparation_manifest_sha256=expected_preparation_manifest_sha256,
        request_ordinal=request_ordinal, response=response,
        deferred_review_slot_ids=request["deferred_review_slot_ids"],
        status="blank_unsubmitted_template_not_a_response")


def _bindings(bindings, expected_sha256, reviews):
    contracts.require_sha256(expected_sha256, "response bindings SHA256")
    bindings = contracts.clone_json(bindings)
    if _digest(bindings) != expected_sha256:
        _fail("independent response binding population differs")
    if type(bindings) is not list or len(bindings) != len(reviews) or len(bindings) > auth.MAX_REVIEWS:
        _fail("one ordered response binding per signed review required")
    seen = set()
    for entry, signed in zip(bindings, reviews, strict=True):
        contracts.require_keys(entry, {"review_id", "artifact_id", "raw_sha256"}, "response binding")
        auth._id(entry["review_id"], "bound review ID")
        auth._id(entry["artifact_id"], "response body identity")
        contracts.require_sha256(entry["raw_sha256"], "response body SHA256")
        if entry["review_id"] != signed.get("review_id") or entry["artifact_id"] in seen:
            _fail("response bindings differ in review order or repeat a body identity")
        seen.add(entry["artifact_id"])
    return bindings


def _content(entry, signed, request, subject, preparation_sha256, evidence):
    try:
        raw = evidence.get(entry["artifact_id"])
        record = contracts.load_record_bytes(raw, expected_sha256=entry["raw_sha256"])
        response = {key: record[key] for key in INPUT_FIELDS}
        if auth.wire(record) != auth.wire(_record(request, subject, response, preparation_sha256)):
            _fail("typed_response_exact_source_binding_differs")
        if any(record[key] != signed[key] for key in ("review_id", "principal_id", "role", "issued_at_utc")):
            _fail("typed_response_signed_reviewer_binding_differs")
        closure = signed["context_closure"]
        if len(closure["obligations"]) != 9:
            _fail("typed_response_signed_obligation_population_differs")
        body_ref = {"artifact_id": entry["artifact_id"], "sha256": entry["raw_sha256"]}
        for answer, obligation in zip(record["answers"], closure["obligations"], strict=True):
            if (obligation["slot_id"] != answer["slot_id"] or obligation["evidence_refs"] != [body_ref]
                    or obligation["disposition"] != DISPOSITIONS[answer["disposition"]]):
                _fail("typed_answer_signed_disposition_or_body_binding_differs")
        unresolved = [answer["slot_id"] for answer in record["answers"] if answer["disposition"] == "unresolved"]
        if (closure["unresolved"] != unresolved
                or closure["status"] != ("open" if unresolved else "declared_complete")):
            _fail("typed_unresolved_answers_differ_from_signed_closure")
        refs = [ref for answer in record["answers"] for ref in answer["evidence_refs"]]
        refs.extend(ref for values in record["process_declaration"].values() for ref in values)
        refs.extend(record["occurrence_proposal"]["evidence_refs"])
        for ref in refs:
            body = evidence.get(ref["artifact_id"])
            if ref["artifact_id"] == entry["artifact_id"] or body is None or _sha(body) != ref["sha256"]:
                _fail("typed_supporting_evidence_missing_changed_or_self_referential")
        return record, not unresolved, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        # Retain malformed/missing response bindings and authenticated claims.
        return None, False, [str(error)[:512] or "typed_response_content_invalid"]


def _source_response_inputs(preparation, reviews, response_bindings,
        expected_response_bindings_sha256, evidence_artifacts):
    """Unchanged typed-response preflight, before source authentication/replay."""
    detached = source._detach(preparation)
    reviews = json.loads(auth.wire(reviews))
    if type(reviews) is not list or len(reviews) > auth.MAX_REVIEWS or any(type(row) is not dict for row in reviews):
        _fail("bounded signed review list required")
    bindings = _bindings(response_bindings, expected_response_bindings_sha256, reviews)
    evidence = evidence_artifacts
    if (type(evidence) is not dict or len(evidence) > auth.MAX_EVIDENCE
            or any(type(key) is not str or type(raw) is not bytes for key, raw in evidence.items())
            or sum(map(len, evidence.values())) > auth.MAX_BYTES):
        _fail("bounded immutable source response evidence required")
    return detached, reviews, bindings, dict(evidence)


def _assess_source_responses_prepared(capability, auth_inputs, *, response_bindings,
        expected_response_bindings_sha256, capability_registry, mint_token):
    """Private complete-preparation gate plus fresh auth and exact typed content.

    No caller assessment/cache flag is accepted. The fixed legacy source owner
    authenticates freshly inside this call before the unchanged content loop.
    The public wrapper or fixed batch must first replay original source banks
    and perform the unchanged response and source preflights.
    """
    checked = source._source_review_preparation(capability,
        registry=capability_registry, mint_token=mint_token)
    reviews = auth_inputs["reviews"]
    bindings = _bindings(response_bindings, expected_response_bindings_sha256, reviews)
    evidence = auth_inputs["evidence_artifacts"]
    raw_assessment = source._assess_source_review_prepared(capability, auth_inputs,
        capability_registry=capability_registry, mint_token=mint_token)
    ordinal = auth_inputs["request_ordinal"]
    request, subject = checked["requests"][ordinal], checked["subjects"][ordinal]
    results, valid, variants, pending = [], [], [], []
    preparation_sha = auth_inputs["expected_preparation_manifest_sha256"]
    for entry, signed, raw_row in zip(bindings, reviews, raw_assessment["reviews"], strict=True):
        record, complete, blockers = _content(entry, signed, request, subject, preparation_sha, evidence)
        authenticated = raw_row["status"] == "authenticated" and not blockers
        result = _seal(RESULT_SCHEMA, request_ordinal=ordinal, request_cid=request["record_cid"],
            review_id=signed["review_id"], review_sha256=raw_row["review_sha256"],
            response_artifact_ref={"artifact_id": entry["artifact_id"], "sha256": entry["raw_sha256"]},
            response_record=record, principal_id=signed["principal_id"], role=signed["role"],
            signature_authentication_status=raw_row["status"],
            content_status="rejected" if blockers else "valid_declared_content", content_blockers=blockers,
            authenticated_typed_content=authenticated, typed_answer_declarations_complete=complete,
            exposure_status="unknown" if record is None or any(value is None for value in record["exposure_declaration"].values()) else "declared")
        results.append(result)
        if authenticated:
            valid.append((record, result))
    for index, question in enumerate(q for q in request["review_questions"]
            if q["assessment_scope"] == "source_context_evidence_declaration"):
        buckets = {}
        for record, result in valid:
            answer = record["answers"][index]
            bucket = buckets.setdefault(_digest(answer), {"answer": answer, "respondents": []})
            bucket["respondents"].append({"response_result_ref": _ref(result), "review_id": record["review_id"],
                "principal_id": record["principal_id"], "role": record["role"]})
        refs, respondents = [], []
        for digest, bucket in buckets.items():
            variant = _seal(VARIANT_SCHEMA, request_cid=request["record_cid"], slot_id=question["slot_id"],
                answer=bucket["answer"], answer_sha256=digest, respondents=bucket["respondents"])
            variants.append(variant)
            refs.append(_ref(variant))
            respondents.extend(bucket["respondents"])
        issues = ["separate_adjudication_and_decision_authority_required"]
        if not respondents:
            issues.append("no_authenticated_typed_answer")
        if any(bucket["answer"]["disposition"] == "unresolved" for bucket in buckets.values()):
            issues.append("unresolved_typed_answer")
        if len(buckets) > 1:
            issues.append("distinct_exact_answer_variants")
        legal = [r for r in respondents if r["role"] == "legal_review"]
        formal = [r for r in respondents if r["role"] == "formal_review"]
        if not any(a["principal_id"] != b["principal_id"] for a in legal for b in formal):
            issues.append("distinct_legal_and_formal_declared_principals_missing")
        pending.append(_seal(PENDING_SCHEMA, request_cid=request["record_cid"],
            **{key: question[key] for key in ("slot_id", "category", "kind")},
            answer_variant_refs=refs, authenticated_respondents=respondents, issues=issues,
            exact_answer_comparison="no_authenticated_answers" if not buckets else
                "one_exact_answer_variant" if len(buckets) == 1 else "different_exact_answer_variants",
            decision=None, adjudicator_declaration=None, status="pending_adjudication_not_a_decision"))
    proposals = [{"review_id": record["review_id"], "response_ref": _ref(record),
        "proposal": record["occurrence_proposal"], "proposed_occurrence_ref": record["proposed_occurrence_ref"]}
        for record, _ in valid]
    report = {"schema": ASSESSMENT_SCHEMA, "profile": PROFILE, "request_ordinal": ordinal,
        "request_ref": _ref(request), "subject_ref": _ref(subject),
        "preparation_manifest_sha256": preparation_sha,
        "response_bindings_sha256": expected_response_bindings_sha256,
        "raw_source_assessment": raw_assessment, "response_results": results,
        "answer_variants": variants, "pending_questions": pending, "occurrence_proposals": proposals,
        "deferred_review_slot_ids": request["deferred_review_slot_ids"], "deferred_questions_remain_pending": True,
        "typed_response_validation_available": True, "response_content_adjudication_available": False,
        "population_complete": True, "coverage_scope": "one_exact_request_all_supplied_signed_reviews_and_nine_active_answers",
        "counts": {"responses": len(results), "authenticated_typed_responses": len(valid),
            "rejected_content_responses": sum(row["content_status"] == "rejected" for row in results),
            "incomplete_typed_responses": sum(not row["typed_answer_declarations_complete"] for row in results),
            "answer_variants": len(variants), "pending_adjudication_slots": len(pending),
            "different_answer_slots": sum("distinct_exact_answer_variants" in row["issues"] for row in pending),
            "unresolved_answer_slots": sum("unresolved_typed_answer" in row["issues"] for row in pending),
            "missing_authenticated_answer_slots": sum("no_authenticated_typed_answer" in row["issues"] for row in pending),
            "differing_occurrence_proposals": int(len({_digest(row["proposal"]) for row in proposals}) > 1),
            "applied_source_decisions": 0}, "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = _digest(report)
    return json.loads(auth.wire(report))


def assess_legacy_source_responses(preparation, registry, policy, reviews, *, response_bindings,
        expected_response_bindings_sha256, **source_inputs):
    """Authenticate original claims, validate typed bodies, retain pending variants.

    The complete ordered binding list has exactly one entry for every supplied
    signed review, including invalid content. Evidence hashes and signature
    checks are custody checks; exact-answer comparison is not legal adjudication.
    The original public guard order and full original source replay remain.
    """
    contracts.require_keys(source_inputs, _SOURCE_FIELDS, "complete source assessment inputs")
    detached, reviews, bindings, evidence = _source_response_inputs(preparation, reviews,
        response_bindings, expected_response_bindings_sha256, source_inputs["evidence_artifacts"])
    source_inputs = {**source_inputs, "evidence_artifacts": evidence}
    join_fields = {"join_bytes", "paired_row_bytes", "expected_join_sha256", "expected_population",
        "producer_receipt_bytes", "expected_producer_receipt_sha256", "source_sections", "expected_source_sections"}
    detached, auth_inputs = source._source_review_auth_inputs(detached, registry, policy, reviews,
        **{key: source_inputs[key] for key in _SOURCE_FIELDS - join_fields})
    checked = source.validate_legacy_source_review_requests(detached, source_inputs["join_bytes"],
        source_inputs["paired_row_bytes"],
        **{key: source_inputs[key] for key in join_fields - {"join_bytes", "paired_row_bytes"}})
    capabilities, token = {}, object()
    capability = source._mint_source_review_preparation(checked,
        generation_sha256=_digest(checked["manifest"]), registry=capabilities, mint_token=token)
    return _assess_source_responses_prepared(capability, auth_inputs, response_bindings=bindings,
        expected_response_bindings_sha256=expected_response_bindings_sha256,
        capability_registry=capabilities, mint_token=token)


def validate_legacy_source_responses(report, *args, **kwargs):
    checked = json.loads(auth.wire(report))
    expected = assess_legacy_source_responses(*args, **kwargs)
    if auth.wire(checked) != auth.wire(expected):
        _fail("typed legacy response assessment differs from exact regeneration")
    return checked


__all__ = ["record_legacy_source_response", "validate_legacy_source_response",
           "prepare_legacy_source_response_template", "assess_legacy_source_responses",
           "validate_legacy_source_responses"]
