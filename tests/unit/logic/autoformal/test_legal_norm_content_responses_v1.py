"""Fictional signed norm content remains evidence, never accepted legal meaning.

The dynamic helper chain supplies complete authored source/context replay. All
signers, declarations and findings here are engineering fixtures, not reviews
of laws. These tests exercise the original norm signing domain and typed body
binding without introducing a new signing or adjudication protocol.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def fixtures():
    spec = importlib.util.spec_from_file_location(
        "_authored_norm_content_full_replay_fixtures",
        Path(__file__).with_name("test_legal_norm_interpretation_review_v1.py"))
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_responses_v1

    return legal_norm_content_responses_v1


@pytest.fixture(scope="module")
def base(fixtures):
    return fixtures.materialize(norm, with_context=True)


def supporting_ref(data):
    artifact_id = "fixture:norm-context"
    return {"artifact_id": artifact_id,
            "sha256": sha(data["evidence_artifacts"][artifact_id])}


def typed_declaration(data, index=0, *, decision="support"):
    """Declare exact existing source/AST geometry; definition use stays open."""
    preparation = data["preparation"]
    candidate = preparation["correspondence"]
    source_rows = candidate["request"]["source_rows"]
    inverse = candidate["request"]["typed_rows"]
    role = next(row for row in inverse
                if row["target"]["kind"] == "variable" and row["source_paths"])
    scope = next(row for row in candidate["typed_context_inventory"]
                 if row["target"]["kind"] == "implies")
    scope_sources = [row for row in source_rows if scope["target"] in row["targets"]]
    evidence = [supporting_ref(data)]
    answers = []
    for obligation in preparation["obligations"]:
        kind = obligation["kind"]
        family = obligation.get("question", kind)
        finding = {"family": family,
                   "statement": "Fictional authored finding; statutory meaning remains unreviewed."}
        disposition = "evidence_declared"
        if kind in {"original_context", "original_unresolved_issue"}:
            disposition = "unresolved"
            finding["original_sha256"] = norm.norm_review_sha256(obligation["original"])
        elif family == "source_meaning":
            finding["source_assertions"] = [
                {"source_row": deepcopy(source_rows[0]), "assessment": "support"}]
        elif family == "participant_roles":
            finding["role_assertions"] = [{
                "target": deepcopy(role["target"]),
                "source_paths": deepcopy(role["source_paths"]),
                "declared_role": "fictional authored actor", "assessment": "support"}]
        elif family in {"condition_and_modal_scope", "exceptions_and_time"}:
            finding["scope_assertions"] = [{
                "typed_context": deepcopy(scope), "source_rows": deepcopy(scope_sources),
                "aspect": "condition" if family == "condition_and_modal_scope" else "exception",
                "assessment": "support", "statement": "Authored structural association only."}]
        elif family == "definition_applicability":
            disposition = "unresolved"
            finding.update(status="unresolved", governing_definition_use=None)
        elif family == "unsupported_grammar":
            finding.update(none_declared=True, constructs=[])
        elif family == "source_coverage":
            finding["coverage"] = [{"source_row": deepcopy(row), "status": "covered"}
                                   for row in source_rows]
        else:
            raise AssertionError("unaccounted fictional finding family: " + family)
        answers.append({"slot_id": obligation["slot_id"], "kind": kind,
            "obligation_sha256": norm.norm_review_sha256(obligation),
            "disposition": disposition,
            "rationale": "Engineering evidence declaration without accepted interpretation.",
            "evidence_refs": deepcopy(evidence), "finding": finding})
    signed = data["reviews"][index]
    return {"review_id": signed["review_id"], "principal_id": signed["principal_id"],
        "role": signed["role"], "issued_at_utc": signed["issued_at_utc"],
        "process_declaration": {key: deepcopy(evidence) for key in
            ("identity_evidence_refs", "independence_evidence_refs", "process_evidence_refs")},
        "exposure_declaration": {"candidate_interpretations_exposed": True,
            "organizer_source_metadata_exposed": True,
            "other_exposure": "Fictional engineering fixture; no human statutory review."},
        "candidate_proposal": {"decision": decision,
            "typed_expression_sha256": preparation["ast_sha256"],
            "native_ast_sha256": preparation["native_ast_sha256"],
            "rationale": "Proposes only the exact retained authored candidate.",
            "evidence_refs": deepcopy(evidence)},
        "answers": answers, "governing_definition_use": None}


def build_response(owner, data, declaration):
    return owner.build_norm_content_response_v1(
        data["preparation"], data["manifest"], declaration, **data["build_arguments"])


def answer_for(declaration, family):
    return next(answer for answer in declaration["answers"]
                if answer["finding"]["family"] == family)


def install_records(fixtures, data, records):
    """Sign original-domain claims that bind each entire exact body in every slot."""
    data["response_bindings"] = []
    for index, record in enumerate(records):
        artifact_id = "fixture:norm-content-body:" + str(index)
        raw = wire(record)
        data["evidence_artifacts"][artifact_id] = raw
        body_ref = {"artifact_id": artifact_id, "sha256": sha(raw)}
        data["response_bindings"].append({"review_id": data["reviews"][index]["review_id"],
            "artifact_id": artifact_id, "raw_sha256": sha(raw)})
        claim = data["reviews"][index]
        claim["interpretation"]["decision"] = record["candidate_proposal"]["decision"]
        unresolved = [answer["slot_id"] for answer in record["answers"]
                      if answer["disposition"] == "unresolved"]
        dispositions = {"unresolved": "open", "evidence_declared": "resolved_by_evidence",
                        "not_applicable": "not_applicable"}
        claim["context_closure"] = {
            "status": "open" if unresolved else "declared_complete", "unresolved": unresolved,
            "obligations": [{"slot_id": answer["slot_id"],
                "disposition": dispositions[answer["disposition"]],
                "evidence_refs": [deepcopy(body_ref)]} for answer in record["answers"]]}
    fixtures.refresh(data)
    return data


def signed_content(owner, fixtures, base, *, decisions=("support", "support")):
    data = fixtures.synthetic(norm, base)
    records = [build_response(owner, data, typed_declaration(data, index, decision=decision))
               for index, decision in enumerate(decisions)]
    return install_records(fixtures, data, records)


@pytest.fixture
def signed(owner, fixtures, base):
    return signed_content(owner, fixtures, base)


def assessment_arguments(owner, fixtures, data):
    args, kwargs = fixtures.assessment_arguments(norm, data)
    return args, {**kwargs, "response_bindings": data["response_bindings"],
        "expected_response_bindings_sha256": signatures.digest(data["response_bindings"])}


def assess(owner, fixtures, data):
    args, kwargs = assessment_arguments(owner, fixtures, data)
    return owner.assess_norm_content_responses_v1(*args, **kwargs)


def replace_raw(fixtures, data, index, raw):
    """Repin exact body bytes and sign new references, retaining claim meaning."""
    binding = data["response_bindings"][index]
    data["evidence_artifacts"][binding["artifact_id"]] = raw
    binding["raw_sha256"] = sha(raw)
    for obligation in data["reviews"][index]["context_closure"]["obligations"]:
        obligation["evidence_refs"] = [{"artifact_id": binding["artifact_id"], "sha256": sha(raw)}]
    fixtures.refresh(data)


def replace_record(fixtures, data, index, record):
    replace_raw(fixtures, data, index, wire(record))


def current_record(data, index=0):
    return json.loads(data["evidence_artifacts"][data["response_bindings"][index]["artifact_id"]])


def assert_pending(report, fixtures):
    fixtures.fixture.assert_no_authority(report)
    assert report["norm_interpretation_ready"] is False
    assert report["governing_definition_use"] is None
    assert report["response_content_adjudication_available"] is False
    assert report["counts"]["applied_meaning_decisions"] == 0
    assert report["counts"]["pending_adjudication_slots"] == len(report["original_obligations"])
    assert all(row["decision"] is row["adjudicator_declaration"] is None
               for row in report["pending_questions"])
    assert all("separate_content_adjudication_and_admission_required" in row["issues"]
               for row in report["pending_questions"])


def test_template_is_blank_complete_context_retaining_and_not_a_response(owner, fixtures, base):
    before = deepcopy(base)
    template = owner.build_norm_content_template_v1(
        base["preparation"], base["manifest"], **base["build_arguments"])
    response = template["response"]
    assert template["status"] == "blank_unsubmitted_template_not_a_response"
    assert template["subject"] == base["subject"]
    assert template["context_evidence"] == base["preparation"]["context_evidence"]
    assert template["context_evidence"] is not None
    assert template["obligations"] == base["preparation"]["obligations"]
    assert template["source_rows"] == base["preparation"]["correspondence"]["request"]["source_rows"]
    assert template["typed_context_inventory"] == base["preparation"]["correspondence"]["typed_context_inventory"]
    assert [row["slot_id"] for row in response["answers"]] == base["subject"]["context_slot_ids"]
    assert all(response[key] is None for key in ("review_id", "principal_id", "role", "issued_at_utc"))
    assert all(value is None for value in response["exposure_declaration"].values())
    assert response["candidate_proposal"]["decision"] is None
    assert all(answer["disposition"] is answer["rationale"] is answer["finding"]["statement"] is None
               for answer in response["answers"])
    fixtures.fixture.assert_no_authority(template)
    with pytest.raises(ValueError):
        build_response(owner, base, response)
    assert base == before
    template["source_rows"].clear()
    assert base == before


def test_empty_signed_population_has_one_pending_record_per_original_obligation(owner, fixtures, base):
    data = fixtures.pending(norm, base)
    data["response_bindings"] = []
    before = deepcopy(data)
    report = assess(owner, fixtures, data)
    assert data == before
    assert report["response_results"] == report["answer_variants"] == report["candidate_proposals"] == []
    assert report["counts"]["responses"] == report["counts"]["authenticated_typed_responses"] == 0
    assert report["original_obligations"] == base["preparation"]["obligations"]
    assert all("no_authenticated_typed_answer" in row["issues"] for row in report["pending_questions"])
    assert_pending(report, fixtures)


def test_original_domain_signatures_authenticate_typed_findings_without_accepting_meaning(owner, fixtures, signed):
    before = {key: deepcopy(value) for key, value in signed.items() if key != "signers"}
    report = assess(owner, fixtures, signed)
    assert {key: value for key, value in signed.items() if key != "signers"} == before
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["counts"]["authenticated_typed_responses"] == 2
    assert report["counts"]["rejected_content_responses"] == 0
    assert report["counts"]["incomplete_typed_responses"] == 2
    assert report["counts"]["answer_variants"] == len(signed["preparation"]["obligations"])
    for row in report["response_results"]:
        assert row["signature_authentication_status"] == "authenticated"
        assert row["content_status"] == "valid_declared_content"
        assert row["authenticated_typed_content"] is True
        assert row["typed_answer_declarations_complete"] is False
        assert row["response_record"]["context_evidence_sha256"] == owner.norm_content_sha256(
            signed["preparation"]["context_evidence"])
    definition = next(row for row in report["pending_questions"]
                      if row["slot_id"] == answer_for(current_record(signed), "definition_applicability")["slot_id"])
    assert "unresolved_typed_answer" in definition["issues"]
    assert report["context_evidence"] == signed["preparation"]["context_evidence"]
    assert_pending(report, fixtures)


@pytest.mark.parametrize("decision", ["support", "reject", "unresolved"])
def test_candidate_proposals_keep_exact_existing_asts_and_never_select(owner, fixtures, base, decision):
    data = signed_content(owner, fixtures, base, decisions=(decision, decision))
    report = assess(owner, fixtures, data)
    assert report["counts"]["authenticated_typed_responses"] == 2
    assert [row["proposal"]["decision"] for row in report["candidate_proposals"]] == [decision, decision]
    assert all(row["proposal"]["typed_expression_sha256"] == data["preparation"]["ast_sha256"]
               and row["proposal"]["native_ast_sha256"] == data["preparation"]["native_ast_sha256"]
               for row in report["candidate_proposals"])
    assert_pending(report, fixtures)


@pytest.mark.parametrize("damage", [
    "slot", "kind", "obligation_hash", "omission", "reorder", "original_record",
    "source_anchor", "role_inverse", "scope_ancestry", "scope_inverse",
    "coverage_omission", "coverage_order", "unsupported_anchor",
])
def test_answers_require_original_order_hashes_and_exact_source_typed_geometry(owner, fixtures, base, damage):
    data = fixtures.synthetic(norm, base)
    declaration = typed_declaration(data)
    if damage == "slot":
        declaration["answers"][0]["slot_id"] = "fixture:foreign-slot"
    elif damage == "kind":
        declaration["answers"][0]["kind"] = "interpretation_question"
    elif damage == "obligation_hash":
        declaration["answers"][0]["obligation_sha256"] = "0" * 64
    elif damage == "omission":
        declaration["answers"].pop()
    elif damage == "reorder":
        declaration["answers"].reverse()
    elif damage == "original_record":
        declaration["answers"][0]["finding"]["original_sha256"] = "0" * 64
    elif damage == "source_anchor":
        row = answer_for(declaration, "source_meaning")["finding"]["source_assertions"][0]["source_row"]
        row["anchor_mapping"]["declaration_path"] += "/foreign"
    elif damage == "role_inverse":
        answer_for(declaration, "participant_roles")["finding"]["role_assertions"][0]["source_paths"] = []
    elif damage == "scope_ancestry":
        row = answer_for(declaration, "condition_and_modal_scope")["finding"]["scope_assertions"][0]
        row["typed_context"]["ancestry"] = []
    elif damage == "scope_inverse":
        answer_for(declaration, "exceptions_and_time")["finding"]["scope_assertions"][0]["source_rows"] = []
    elif damage == "coverage_omission":
        answer_for(declaration, "source_coverage")["finding"]["coverage"].pop()
    elif damage == "coverage_order":
        answer_for(declaration, "source_coverage")["finding"]["coverage"].reverse()
    elif damage == "unsupported_anchor":
        finding = answer_for(declaration, "unsupported_grammar")["finding"]
        foreign = deepcopy(data["preparation"]["correspondence"]["request"]["source_rows"][0])
        foreign["anchor_mapping"]["declaration_path"] = "/foreign"
        finding.update(none_declared=False, constructs=[{"source_row": foreign, "construct": "fictional"}])
    with pytest.raises(ValueError):
        build_response(owner, data, declaration)


@pytest.mark.parametrize("damage", [
    "extra_field", "candidate_hash", "replacement_ast", "definition_resolved",
    "definition_selected", "exposure_integer", "empty_rationale", "missing_evidence",
])
def test_closed_explicit_declarations_cannot_select_definitions_or_replace_the_candidate(owner, fixtures, base, damage):
    data = fixtures.synthetic(norm, base)
    declaration = typed_declaration(data)
    if damage == "extra_field":
        declaration["accepted"] = True
    elif damage == "candidate_hash":
        declaration["candidate_proposal"]["native_ast_sha256"] = "0" * 64
    elif damage == "replacement_ast":
        declaration["candidate_proposal"]["typed_expression"] = {}
    elif damage == "definition_resolved":
        answer_for(declaration, "definition_applicability")["disposition"] = "evidence_declared"
    elif damage == "definition_selected":
        declaration["governing_definition_use"] = "fixture:proposed-definition"
    elif damage == "exposure_integer":
        declaration["exposure_declaration"]["candidate_interpretations_exposed"] = 1
    elif damage == "empty_rationale":
        declaration["candidate_proposal"]["rationale"] = " "
    elif damage == "missing_evidence":
        answer_for(declaration, "source_meaning")["evidence_refs"] = []
    with pytest.raises(ValueError):
        build_response(owner, data, declaration)


@pytest.mark.parametrize("damage", ["source_pin", "candidate", "omitted_answer", "definition"])
def test_rehashed_body_and_new_whole_body_signatures_cannot_bypass_exact_regeneration(owner, fixtures, signed, damage):
    record = current_record(signed)
    if damage == "source_pin":
        record["preparation_sha256"] = "0" * 64
    elif damage == "candidate":
        record["candidate_proposal"]["typed_expression_sha256"] = "0" * 64
    elif damage == "omitted_answer":
        record["answers"].pop()
    else:
        answer_for(record, "definition_applicability")["finding"]["governing_definition_use"] = "fixture:definition"
    replace_record(fixtures, signed, 0, record)
    report = assess(owner, fixtures, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["response_results"][0]["content_status"] == "rejected"
    assert report["response_results"][0]["authenticated_typed_content"] is False
    assert report["response_results"][0]["content_blockers"]
    assert report["counts"]["responses"] == 2
    assert report["counts"]["authenticated_typed_responses"] == 1
    assert_pending(report, fixtures)


def test_old_norm_signature_authentication_does_not_cover_unreferenced_typed_answers(owner, fixtures, base):
    old = fixtures.synthetic(norm, base)
    assert fixtures.assess(norm, old)["authenticated_evidence_count"] == 2
    old["response_bindings"] = []
    for index in range(2):
        record = build_response(owner, old, typed_declaration(old, index))
        artifact_id = "fixture:unsigned-norm-body:" + str(index)
        raw = wire(record)
        old["evidence_artifacts"][artifact_id] = raw
        old["response_bindings"].append({"review_id": old["reviews"][index]["review_id"],
            "artifact_id": artifact_id, "raw_sha256": sha(raw)})
    report = assess(owner, fixtures, old)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["counts"]["authenticated_typed_responses"] == 0
    assert report["counts"]["rejected_content_responses"] == 2
    assert all(row["content_blockers"] for row in report["response_results"])
    assert_pending(report, fixtures)


@pytest.mark.parametrize("damage", [
    "review_id", "principal_id", "role", "issued_at", "proposal",
    "disposition", "body_reference", "unresolved_order",
])
def test_authenticated_claim_and_typed_body_must_agree_on_identity_proposal_and_every_slot(owner, fixtures, signed, damage):
    if damage in {"review_id", "principal_id", "role", "issued_at", "proposal"}:
        record = current_record(signed)
        if damage == "review_id": record["review_id"] = "fixture:other-review"
        elif damage == "principal_id": record["principal_id"] = "fixture:other-principal"
        elif damage == "role": record["role"] = "formal_review"
        elif damage == "issued_at": record["issued_at_utc"] = "2026-10-15T10:59:00Z"
        else: record["candidate_proposal"]["decision"] = "reject"
        replace_record(fixtures, signed, 0, record)
    else:
        closure = signed["reviews"][0]["context_closure"]
        if damage == "disposition":
            closure["obligations"][0]["disposition"] = "not_applicable"
        elif damage == "body_reference":
            closure["obligations"][0]["evidence_refs"] = [supporting_ref(signed)]
        else:
            closure["unresolved"].reverse()
        fixtures.refresh(signed)
    report = assess(owner, fixtures, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["response_results"][0]["signature_authentication_status"] == "authenticated"
    assert report["response_results"][0]["content_status"] == "rejected"
    assert report["counts"]["authenticated_typed_responses"] == 1
    assert_pending(report, fixtures)


@pytest.mark.parametrize("damage", ["missing", "reorder", "duplicate_body", "extra"])
def test_independently_repinned_bindings_must_cover_exact_ordered_review_population(owner, fixtures, signed, damage):
    bindings = signed["response_bindings"]
    if damage == "missing": bindings.pop()
    elif damage == "reorder": bindings.reverse()
    elif damage == "duplicate_body": bindings[1]["artifact_id"] = bindings[0]["artifact_id"]
    else: bindings.append(deepcopy(bindings[0]))
    with pytest.raises(ValueError):
        assess(owner, fixtures, signed)


@pytest.mark.parametrize("pin", [None, "", "0" * 64])
def test_binding_pin_is_required_and_cannot_be_derived_from_an_untrusted_offer(owner, fixtures, signed, pin):
    args, kwargs = assessment_arguments(owner, fixtures, signed)
    kwargs["expected_response_bindings_sha256"] = pin
    with pytest.raises(ValueError):
        owner.assess_norm_content_responses_v1(*args, **kwargs)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_supporting_evidence_is_independent_of_authenticated_whole_body_bytes(owner, fixtures, signed, damage):
    if damage == "missing": del signed["evidence_artifacts"]["fixture:norm-context"]
    else: signed["evidence_artifacts"]["fixture:norm-context"] += b" changed after declaration"
    report = assess(owner, fixtures, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["counts"]["authenticated_typed_responses"] == 0
    assert report["counts"]["rejected_content_responses"] == 2
    assert_pending(report, fixtures)


def test_duplicate_raw_json_keys_are_rejected_after_repinning_and_signing_exact_bytes(owner, fixtures, signed):
    record = current_record(signed)
    canonical = wire(record)
    duplicate = b'{"schema":' + wire(record["schema"]) + b"," + canonical[1:]
    assert json.loads(duplicate) == record
    replace_raw(fixtures, signed, 0, duplicate)
    report = assess(owner, fixtures, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["response_results"][0]["content_status"] == "rejected"
    assert report["response_results"][0]["content_blockers"]
    assert report["counts"]["authenticated_typed_responses"] == 1
    assert_pending(report, fixtures)


@pytest.mark.parametrize("namespace,family", [
    ("other_body", "answer"), ("hash_alias", "process"), ("other_body", "proposal"),
])
def test_response_bodies_cannot_support_answers_process_or_candidate_proposals(owner, fixtures, signed, namespace, family):
    other = signed["response_bindings"][1]
    artifact_id = other["artifact_id"]
    if namespace == "hash_alias":
        artifact_id = "fixture:other-body-under-alias"
        signed["evidence_artifacts"][artifact_id] = signed["evidence_artifacts"][other["artifact_id"]]
    ref = {"artifact_id": artifact_id, "sha256": other["raw_sha256"]}
    record = current_record(signed)
    if family == "answer":
        answer_for(record, "source_meaning")["evidence_refs"] = [ref]
    elif family == "process":
        record["process_declaration"]["identity_evidence_refs"] = [ref]
    else:
        record["candidate_proposal"]["evidence_refs"] = [ref]
    replace_record(fixtures, signed, 0, record)
    report = assess(owner, fixtures, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["response_results"][0]["content_status"] == "rejected"
    assert report["counts"]["authenticated_typed_responses"] == 1
    assert_pending(report, fixtures)


@pytest.mark.parametrize("damage", ["artifact", "producer"])
def test_stale_observations_remain_blockers_even_with_authentic_typed_declarations(owner, fixtures, signed, damage):
    if damage == "artifact":
        signed["observed_artifact_sha256s"][signed["subject"]["graph_id"]] = "0" * 64
    else:
        policy = signed["observed_pins"]["policy"]
        assert policy
        policy[next(iter(policy))] = "0" * 64
    report = assess(owner, fixtures, signed)
    assert "required_dependency_closure_not_current" in report["raw_norm_assessment"]["blockers"]
    assert_pending(report, fixtures)


def test_expired_signed_review_does_not_supply_an_authenticated_typed_respondent(owner, fixtures, signed):
    signed["reviews"][0]["expires_at_utc"] = fixtures.NOW
    fixtures.refresh(signed)
    report = assess(owner, fixtures, signed)
    first = report["response_results"][0]
    assert "review_not_current" in report["raw_norm_assessment"]["reviews"][0]["blockers"]
    assert first["signature_authentication_status"] == "rejected"
    assert first["content_status"] == "valid_declared_content"
    assert first["authenticated_typed_content"] is False
    assert report["counts"]["authenticated_typed_responses"] == 1
    assert_pending(report, fixtures)


def test_distinct_supported_answer_declarations_are_preserved_as_pending_variants(owner, fixtures, signed):
    record = current_record(signed, 1)
    finding = answer_for(record, "source_meaning")["finding"]
    finding["source_assertions"][0]["assessment"] = "dispute"
    finding["statement"] = "A different fictional declaration, not an adjudicated interpretation."
    replace_record(fixtures, signed, 1, record)
    report = assess(owner, fixtures, signed)
    slot_id = answer_for(record, "source_meaning")["slot_id"]
    variants = [row for row in report["answer_variants"] if row["slot_id"] == slot_id]
    pending = next(row for row in report["pending_questions"] if row["slot_id"] == slot_id)
    assert report["counts"]["authenticated_typed_responses"] == 2
    assert len(variants) == 2
    assert {row["answer"]["finding"]["source_assertions"][0]["assessment"] for row in variants} == {"support", "dispute"}
    assert "distinct_exact_answer_variants" in pending["issues"]
    assert len(pending["authenticated_respondents"]) == 2
    assert_pending(report, fixtures)


def test_declared_roles_do_not_supply_independent_principals_or_human_identity(owner, fixtures, signed):
    principal = signed["reviews"][0]["principal_id"]
    signed["registry"]["keys"][1]["principal_id"] = principal
    signed["reviews"][1]["principal_id"] = principal
    record = current_record(signed, 1)
    record["principal_id"] = principal
    replace_record(fixtures, signed, 1, record)
    report = assess(owner, fixtures, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["counts"]["authenticated_typed_responses"] == 2
    assert "distinct_authorized_review_principals_missing" in report["raw_norm_assessment"]["blockers"]
    assert all("distinct_legal_and_formal_declared_principals_missing" in row["issues"]
               for row in report["pending_questions"])
    assert report["human_identity_verified"] is report["human_independence_verified"] is False
    assert_pending(report, fixtures)


def test_repinning_changed_raw_source_cannot_reuse_original_sampling_and_signed_preparation(owner, fixtures, signed):
    replay = signed["arguments"]["correspondence_inputs"]["scope_replay_inputs"]
    raw = replay["raw_html"].replace("Clérk".encode("utf-8"), b"Other")
    assert raw != replay["raw_html"]
    replay["raw_html"] = raw
    replay["expected_raw_sha256"] = sha(raw)
    replay["expected_raw_bytes"] = len(raw)
    replay["descriptor"]["raw_sha256"] = sha(raw)
    replay["descriptor"]["raw_bytes"] = len(raw)
    replay["expected_descriptor_sha256"] = fixtures.fixture.scope_fixture.custody.acquisition_descriptor_sha256(
        replay["descriptor"])
    with pytest.raises(ValueError):
        assess(owner, fixtures, signed)


def test_complete_report_pin_and_replay_accept_only_the_original_detached_assessment(owner, fixtures, signed):
    report = assess(owner, fixtures, signed)
    args, kwargs = assessment_arguments(owner, fixtures, signed)
    pin = owner.norm_content_sha256(report)
    assert pin == sha(wire(report))
    assert pin != report["assessment_sha256"]
    validated = owner.validate_norm_content_assessment_v1(
        report, *args, expected_report_sha256=pin, **kwargs)
    assert validated == report
    validated["pending_questions"].clear()
    assert report["pending_questions"]
    assert_pending(report, fixtures)
    with pytest.raises(ValueError):
        owner.validate_norm_content_assessment_v1(
            report, *args, expected_report_sha256="0" * 64, **kwargs)


@pytest.mark.parametrize("damage", ["authority", "variant"])
def test_rehashed_saved_report_cannot_grant_meaning_or_replace_authenticated_answers(owner, fixtures, signed, damage):
    report = assess(owner, fixtures, signed)
    if damage == "authority":
        report["norm_interpretation_ready"] = True
    else:
        report["answer_variants"][0]["answer"]["finding"]["statement"] += " edited after authentication"
    args, kwargs = assessment_arguments(owner, fixtures, signed)
    with pytest.raises(ValueError):
        owner.validate_norm_content_assessment_v1(report, *args,
            expected_report_sha256=owner.norm_content_sha256(report), **kwargs)


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_assessment_fences_original_and_working_trust_inputs_after_authentication(owner, fixtures, signed, monkeypatch, target):
    authenticate = norm.assess_norm_reviews_v1

    def mutating(*args, **kwargs):
        result = authenticate(*args, **kwargs)
        destination = signed["registry"] if target == "caller" else args[1]
        destination["generation"] += 1
        return result

    monkeypatch.setattr(norm, "assess_norm_reviews_v1", mutating)
    with pytest.raises(ValueError, match="inputs changed"):
        assess(owner, fixtures, signed)


@pytest.mark.parametrize("target", ["content", "norm", "json_reader"])
def test_live_direct_source_drift_refuses_retained_responses_without_editing_files(owner, fixtures, signed, monkeypatch, target):
    module = {"content": owner, "norm": norm, "json_reader": owner.json_reader}[target]
    selected = Path(module.__file__).resolve()
    read_bytes = Path.read_bytes
    original = read_bytes(selected)

    def changed(path):
        if path.resolve() == selected:
            return original + b"\n# Fictional observed source drift; file is never written.\n"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="changed"):
        assess(owner, fixtures, signed)
