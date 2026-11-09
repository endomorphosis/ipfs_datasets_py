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


# Unsigned parent worksheets retain the complete physical candidate preparation.
def parent_content_materialize(fixtures, tmp_path):
    value = fixtures.parent_review_materialize(norm, tmp_path)
    preparation = value["preparation"]
    value["build_arguments"] = dict(expected_preparation_sha256=norm.norm_review_sha256(preparation),
                                    **value["arguments"])
    return value


def parent_content_build(owner, value):
    return owner.build_parent_norm_content_template_v1(value["preparation"], **value["build_arguments"])


def parent_content_validate(owner, value, report, *, expected_report_sha256=None):
    return owner.validate_parent_norm_content_template_v1(report, value["preparation"],
        expected_report_sha256=(owner.norm_content_sha256(report)
            if expected_report_sha256 is None else expected_report_sha256), **value["build_arguments"])


def test_parent_content_blank_worksheet_retains_all_fourteen_original_slots(owner, fixtures, tmp_path):
    value = parent_content_materialize(fixtures, tmp_path); before = deepcopy(value["build_arguments"])
    report = parent_content_build(owner, value); preparation = value["preparation"]
    assert report["schema"] == owner.PARENT_TEMPLATE_SCHEMA
    assert report["profile"] == owner.PARENT_TEMPLATE_PROFILE
    assert report["preparation"] == preparation
    assert report["source_identity"] == preparation["source_identity"]
    assert report["source_rows"] == preparation["source_rows"]
    assert report["typed_context_inventory"] == preparation["typed_context_inventory"]
    assert report["dependency_manifest"] == preparation["dependency_manifest"]
    assert report["obligations"] == preparation["obligations"]
    assert len(report["obligations"]) == 14
    assert all(report[key] is None for key in ("subject", "subject_sha256", "signature", "clock", "registry"))
    response = report["response"]
    assert all(response[key] is None for key in ("review_id", "principal_id", "role", "issued_at_utc"))
    assert all(item is None for item in response["exposure_declaration"].values())
    assert all(item == [] for item in response["process_declaration"].values())
    assert response["candidate_proposal"]["decision"] is response["candidate_proposal"]["rationale"] is None
    assert response["candidate_proposal"]["evidence_refs"] == []
    assert response["governing_definition_use"] is None
    answers = response["answers"]
    assert [a["slot_id"] for a in answers] == preparation["obligation_ids"]
    for answer, obligation in zip(answers, preparation["obligations"], strict=True):
        assert answer["kind"] == obligation["kind"]
        assert answer["obligation_sha256"] == norm.norm_review_sha256(obligation)
        assert answer["disposition"] is answer["rationale"] is answer["finding"]["statement"] is None
        assert answer["evidence_refs"] == []
        if obligation["kind"] == "original_parent_context":
            assert answer["finding"] == dict(family="original_parent_context", statement=None,
                original_sha256=norm.norm_review_sha256(obligation["original"]))
        if obligation.get("question") == "definition_applicability":
            assert answer["finding"]["status"] == "unresolved"
            assert answer["finding"]["governing_definition_use"] is None
    fixtures.assert_parent_review_unqualified(report)
    assert parent_content_validate(owner, value, report) == report
    assert value["build_arguments"] == before


@pytest.mark.parametrize("damage", ["answer_drop", "occurrence", "decision", "clock", "mask_alias"])
def test_parent_content_resealed_worksheet_cannot_prefill_meaning_or_change_identity(owner, fixtures, tmp_path, damage):
    value = parent_content_materialize(fixtures, tmp_path); report = parent_content_build(owner, value)
    if damage == "answer_drop": report["response"]["answers"].pop()
    elif damage == "occurrence": report["source_identity"]["source_occurrence_cid"] = report["source_identity"]["context_record_cid"]
    elif damage == "decision": report["response"]["candidate_proposal"]["decision"] = "support"
    elif damage == "clock": report["clock"] = fixtures.NOW
    else: report["training_mask"] = False
    with pytest.raises(ValueError):
        parent_content_validate(owner, value, report)


def test_parent_content_independent_preparation_pin_precedes_upstream_replay(owner, fixtures, tmp_path, monkeypatch):
    value = parent_content_materialize(fixtures, tmp_path); report = parent_content_build(owner, value)
    original_pin = value["build_arguments"]["expected_preparation_sha256"]
    value["build_arguments"]["expected_preparation_sha256"] = "0" * 64
    calls = []
    def denied(*args, **kwargs):
        calls.append("parent review validation"); raise AssertionError("wrong preparation pin reached replay")
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", denied)
    with pytest.raises(ValueError):
        parent_content_build(owner, value)
    value["build_arguments"]["expected_preparation_sha256"] = original_pin
    with pytest.raises(ValueError):
        parent_content_validate(owner, value, report, expected_report_sha256="0" * 64)
    assert calls == []


def test_parent_content_complete_replay_detects_late_physical_parent_change(owner, fixtures, tmp_path, monkeypatch):
    value = parent_content_materialize(fixtures, tmp_path); real = norm.validate_parent_norm_review_evidence_v1
    parquet = next(tmp_path.rglob("laws.parquet")); original = parquet.read_bytes(); observed = []
    def validated_then_change(*args, **kwargs):
        result = real(*args, **kwargs)
        if not observed:
            parquet.write_bytes(original + b"\nchanged after preparation replay\n")
            observed.append("genuine_parent_review_validated")
        return result
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", validated_then_change)
    with pytest.raises(ValueError):
        parent_content_build(owner, value)
    assert observed and parquet.read_bytes() != original


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_parent_content_late_candidate_inputs_are_fenced_after_genuine_validation(owner, fixtures, tmp_path, monkeypatch, target):
    value = parent_content_materialize(fixtures, tmp_path); real = norm.validate_parent_norm_review_evidence_v1; observed = []
    def validated_then_change(*args, **kwargs):
        result = real(*args, **kwargs)
        if not observed:
            supplied = args[1] if len(args) > 1 else kwargs["correspondence"]
            chosen = value["build_arguments"]["correspondence"] if target == "caller" else supplied
            chosen["alternative_id"] += ":late"
            observed.append("genuine_parent_review_validated")
        return result
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", validated_then_change)
    with pytest.raises(ValueError):
        parent_content_build(owner, value)
    assert observed == ["genuine_parent_review_validated"]


def test_parent_content_final_detached_worksheet_mutation_is_refused(owner, fixtures, tmp_path, monkeypatch):
    value = parent_content_materialize(fixtures, tmp_path); real_wire = norm._wire; observed = []; objects = set()
    def encoded_then_change(report):
        encoded = real_wire(report)
        if type(report) is dict and report.get("schema") == owner.PARENT_TEMPLATE_SCHEMA:
            objects.add(id(report))
            if len(objects) > 1 and not observed:
                report["response"]["candidate_proposal"]["decision"] = "support"
                observed.append("parent_worksheet_serialized")
        return encoded
    monkeypatch.setattr(norm, "_wire", encoded_then_change)
    with pytest.raises(ValueError):
        parent_content_build(owner, value)
    assert observed == ["parent_worksheet_serialized"]


def test_parent_unsigned_evidence_does_not_enter_legacy_subject_signature_or_counted_routes(owner, fixtures, tmp_path):
    value = parent_content_materialize(fixtures, tmp_path); preparation = value["preparation"]
    worksheet = parent_content_build(owner, value); manifest = preparation["dependency_manifest"]
    legacy = dict(value["build_arguments"], expected_manifest_sha256=manifest["manifest_sha256"],
                  required_dependency_ids=preparation["required_dependency_ids"], context_inputs=None)
    with pytest.raises(ValueError):
        norm.build_norm_review_subject_v1(preparation, manifest, **legacy)
    with pytest.raises(ValueError):
        owner.build_norm_content_response_v1(preparation, manifest, worksheet["response"], **legacy)
    with pytest.raises(ValueError):
        norm.prepare_counted_norm_review_evidence_v1(**value["arguments"])
    assert all(worksheet[key] is None for key in ("subject", "signature", "clock", "registry"))
    fixtures.assert_parent_review_unqualified(worksheet)


@pytest.mark.parametrize("damage", [
    "last_producer_output", "last_producer_caller", "last_producer_detached", "final_encoder_input",
])
def test_parent_content_reuse_final_boundaries(owner, fixtures, tmp_path, monkeypatch, damage):
    """Guard the peer blank worksheet through its final genuine boundary."""
    value = parent_content_materialize(fixtures, tmp_path)
    preparation = deepcopy(value["preparation"])
    arguments = deepcopy(value["build_arguments"])
    actual_loads, actual_pins, actual_wire = owner.json.loads, owner._parent_content_pins, norm._wire
    actual_replay = norm.validate_parent_norm_review_evidence_v1
    captured, detached_replay, closing, changed = [], [], [], []

    def capture(*args, **kwargs):
        result = actual_loads(*args, **kwargs)
        if type(result) is dict and result.get("schema") == owner.PARENT_TEMPLATE_SCHEMA:
            captured.append(result)
        return result

    def genuine_replay(*args, **kwargs):
        result = actual_replay(*args, **kwargs)
        if not detached_replay:
            detached_replay.append(kwargs["correspondence_inputs"]["scope_replay_inputs"])
        return result

    def after_genuine_pins(*args, **kwargs):
        result = actual_pins(*args, **kwargs)
        if captured:
            closing.append("genuine closing worksheet producer check")
            if len(closing) == 3 and damage != "final_encoder_input":
                if damage == "last_producer_output":
                    captured[-1]["response"]["candidate_proposal"]["decision"] = "support"
                else:
                    replay = (arguments["correspondence_inputs"]["scope_replay_inputs"]
                              if damage == "last_producer_caller" else detached_replay[0])
                    replay["scope_request_raw"] += b" "
                changed.append(damage)
        return result

    def after_genuine_encoding(report):
        raw = actual_wire(report)
        if damage == "final_encoder_input" and captured and report is captured[-1] and not changed:
            arguments["correspondence_inputs"]["mapping_request_raw"] += b" "
            changed.append(damage)
        return raw

    monkeypatch.setattr(owner.json, "loads", capture)
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", genuine_replay)
    monkeypatch.setattr(owner, "_parent_content_pins", after_genuine_pins)
    monkeypatch.setattr(norm, "_wire", after_genuine_encoding)
    with pytest.raises(ValueError):
        owner.build_parent_norm_content_template_v1(preparation, **arguments)
    assert detached_replay and changed == [damage]


def test_parent_content_reuse_final_encoder_cannot_change_retained_opening(owner, fixtures, tmp_path, monkeypatch):
    value = parent_content_materialize(fixtures, tmp_path)
    preparation = deepcopy(value["preparation"])
    arguments = deepcopy(value["build_arguments"])
    actual_loads, actual_wire = owner.json.loads, norm._wire
    actual_replay = norm.validate_parent_norm_review_evidence_v1
    captured, retained, changed = [], [], []

    def capture(*args, **kwargs):
        result = actual_loads(*args, **kwargs)
        if type(result) is dict and result.get("schema") == owner.PARENT_TEMPLATE_SCHEMA:
            captured.append(result)
        return result

    def genuine_replay(*args, **kwargs):
        result = actual_replay(*args, **kwargs)
        retained.append(result)
        return result

    def after_genuine_encoding(report):
        raw = actual_wire(report)
        if captured and report is captured[-1] and not changed:
            assert len(retained) == 2
            retained[0]["training_mask"] = False
            changed.append("retained genuine opening preparation")
        return raw

    monkeypatch.setattr(owner.json, "loads", capture)
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", genuine_replay)
    monkeypatch.setattr(norm, "_wire", after_genuine_encoding)
    with pytest.raises(ValueError):
        owner.build_parent_norm_content_template_v1(preparation, **arguments)
    assert changed == ["retained genuine opening preparation"]


# Completed declarations retain the original parent occurrence.  These authored
# engineering answers supply no authenticated reviewer or accepted legal meaning.
@pytest.fixture(scope="module")
def parent_response_originals(owner, fixtures, tmp_path_factory):
    import tempfile
    directory = Path(tempfile.mkdtemp(prefix="parent-response-originals-", dir=tmp_path_factory.getbasetemp()))
    return parent_content_materialize(fixtures, directory)


def parent_response_case(originals):
    value = dict(preparation=deepcopy(originals["preparation"]),
                 build_arguments=deepcopy(originals["build_arguments"]))
    preparation = value["preparation"]
    correspondence = preparation["correspondence"]
    source_rows = correspondence["request"]["source_rows"]
    typed_rows = correspondence["request"]["typed_rows"]
    role = next(row for row in typed_rows
                if row["target"]["kind"] == "variable" and row["source_paths"])
    context = next(row for row in correspondence["typed_context_inventory"]
                   if row["target"]["kind"] == "implies")
    scope_rows = [row for row in source_rows if context["target"] in row["targets"]]
    bodies = {"fixture:parent-response-evidence": "Authored annotation: café, 雪; no accepted law.\n".encode(),
              "fixture:parent-unused-evidence": b"\x00independently committed unused bytes\xff"}
    reference = {"artifact_id": "fixture:parent-response-evidence",
                 "sha256": sha(bodies["fixture:parent-response-evidence"])}
    answers = []
    for obligation in preparation["obligations"]:
        family = obligation.get("question", obligation["kind"])
        finding = {"family": family, "statement": "Fictional declared finding; legal meaning remains unreviewed."}
        disposition = "evidence_declared"
        if family in {"original_parent_context", "original_unresolved_issue"}:
            disposition = "unresolved"
            finding["original_sha256"] = norm.norm_review_sha256(obligation["original"])
        elif family == "source_meaning":
            finding["source_assertions"] = [{"source_row": deepcopy(source_rows[0]), "assessment": "support"}]
        elif family == "participant_roles":
            finding["role_assertions"] = [{"target": deepcopy(role["target"]),
                "source_paths": deepcopy(role["source_paths"]), "declared_role": "authored actor",
                "assessment": "support"}]
        elif family in {"condition_and_modal_scope", "exceptions_and_time"}:
            finding["scope_assertions"] = [{"typed_context": deepcopy(context),
                "source_rows": deepcopy(scope_rows),
                "aspect": "condition" if family == "condition_and_modal_scope" else "exception",
                "assessment": "support", "statement": "Authored structural association only."}]
        elif family == "source_coverage":
            finding["coverage"] = [{"source_row": deepcopy(row), "status": "covered"} for row in source_rows]
        elif family == "unsupported_grammar":
            finding.update(none_declared=True, constructs=[])
        elif family == "definition_applicability":
            disposition = "unresolved"
            finding.update(status="unresolved", governing_definition_use=None)
        else:
            raise AssertionError("unaccounted fictional parent finding: " + family)
        answers.append({"slot_id": obligation["slot_id"], "kind": obligation["kind"],
            "obligation_sha256": norm.norm_review_sha256(obligation), "disposition": disposition,
            "rationale": "Engineering declaration, not a meaning decision.",
            "evidence_refs": [deepcopy(reference)], "finding": finding})
    value["response"] = {"review_id": "fixture:parent-declaration", "principal_id": "fixture:declared-reviewer",
        "role": "legal_review", "issued_at_utc": "2026-10-24T00:00:00Z",
        "process_declaration": {key: [deepcopy(reference)] for key in
            ("identity_evidence_refs", "independence_evidence_refs", "process_evidence_refs")},
        "exposure_declaration": {"candidate_interpretations_exposed": True,
            "organizer_source_metadata_exposed": True,
            "other_exposure": "Authored engineering fixture without human review."},
        "candidate_proposal": {"decision": "support", "typed_expression_sha256": preparation["ast_sha256"],
            "native_ast_sha256": preparation["native_ast_sha256"],
            "rationale": "Declares support only for the exact retained authored candidate.",
            "evidence_refs": [deepcopy(reference)]},
        "answers": answers, "governing_definition_use": None}
    value["evidence_artifacts"] = bodies
    value["evidence_manifest"] = {"schema": "legal-parent-norm-response-evidence/v1", "artifacts": [
        {"artifact_id": identity, "bytes": len(raw), "sha256": sha(raw)} for identity, raw in bodies.items()]}
    return value


def parent_response_arguments(owner, value):
    return dict(value["build_arguments"], expected_response_sha256=owner.norm_content_sha256(value["response"]),
        evidence_manifest=value["evidence_manifest"],
        expected_evidence_manifest_sha256=owner.norm_content_sha256(value["evidence_manifest"]),
        evidence_artifacts=value["evidence_artifacts"])


def parent_response_build(owner, value, **overrides):
    arguments = parent_response_arguments(owner, value); arguments.update(overrides)
    return owner.build_parent_norm_content_response_v1(value["preparation"], value["response"], **arguments)


def parent_response_validate(owner, value, report, **overrides):
    arguments = parent_response_arguments(owner, value)
    arguments["expected_report_sha256"] = owner.norm_content_sha256(report)
    arguments.update(overrides)
    return owner.validate_parent_norm_content_response_v1(report, value["preparation"], value["response"], **arguments)


def parent_response_no_replay(monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append("unexpected genuine parent validation")
        raise AssertionError("malformed completed response reached upstream replay")
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", denied)
    return calls


def test_parent_response_genuine_completed_declaration_validates_without_authority(owner, fixtures, parent_response_originals):
    value = parent_response_case(parent_response_originals); before = deepcopy(value)
    report = parent_response_build(owner, value)
    assert report["schema"] == "legal-parent-norm-content-response/v1"
    assert report["profile"] == "unsigned-parent-literal-content-response/v1"
    assert report["response"] == value["response"]
    assert report["response_sha256"] == owner.norm_content_sha256(value["response"])
    assert report["preparation"] == value["preparation"]
    for key in ("source_identity", "source_identity_sha256", "original_parent_context", "obligations",
                "obligation_ids", "source_rows", "typed_context_inventory", "dependency_manifest"):
        assert report[key] == value["preparation"][key]
    assert report["evidence_manifest"] == value["evidence_manifest"]
    assert report["evidence_manifest_sha256"] == owner.norm_content_sha256(value["evidence_manifest"])
    assert report["evidence_artifact_observations"] == value["evidence_manifest"]["artifacts"]
    assert report["unresolved_obligation_ids"] == [answer["slot_id"] for answer in value["response"]["answers"]
                                                if answer["disposition"] == "unresolved"]
    assert len(report["obligations"]) == 14
    assert report["original_parent_context"]["availability"] == "required_unavailable"
    assert "Clérk" in str(report["source_rows"]) and "café" in str(report["source_rows"])
    assert all(report[key] is None for key in ("subject", "signature", "clock", "registry", "policy"))
    assert report["evidence_references_raw_bytes_matched"] is True
    assert all(report[key] is False for key in ("evidence_identity_verified", "evidence_independence_verified",
        "evidence_truth_verified", "reviewer_declarations_verified", "legacy_signing_or_adjudication_submission_allowed"))
    assert all(report[key] == 0 for key in ("human_reviews", "signatures_constructed", "admissions", "model_calls", "training_calls", "native_processes"))
    fixtures.assert_parent_review_unqualified(report)
    for key in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0
    assert parent_response_validate(owner, value, report) == report
    assert value == before


def test_parent_response_answers_keep_exact_complete_ordered_obligation_population(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for damage in ("drop", "duplicate", "swap", "slot", "kind", "hash"):
        value = parent_response_case(parent_response_originals); answers = value["response"]["answers"]
        if damage == "drop": answers.pop()
        elif damage == "duplicate": answers[-1] = deepcopy(answers[-2])
        elif damage == "swap": answers[0], answers[1] = answers[1], answers[0]
        elif damage == "slot": answers[0]["slot_id"] = answers[1]["slot_id"]
        elif damage == "kind": answers[0]["kind"] = "original_context"
        else: answers[0]["obligation_sha256"] = "0" * 64
        with pytest.raises(ValueError): parent_response_build(owner, value)

    assert calls == []

def test_parent_response_typed_findings_preserve_original_coverage_inverse_and_candidate(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for damage in ("source_order", "source_drop", "role_inverse", "typed_context", "candidate", "native"):
        value = parent_response_case(parent_response_originals); response = value["response"]
        if damage.startswith("source_"):
            coverage = answer_for(response, "source_coverage")["finding"]["coverage"]
            if damage == "source_order": coverage[0], coverage[-1] = coverage[-1], coverage[0]
            else: coverage.pop()
        elif damage == "role_inverse":
            answer_for(response, "participant_roles")["finding"]["role_assertions"][0]["source_paths"] = []
        elif damage == "typed_context":
            answer_for(response, "condition_and_modal_scope")["finding"]["scope_assertions"][0]["typed_context"]["target"]["typed_path"] += "/foreign"
        else:
            response["candidate_proposal"]["typed_expression_sha256" if damage == "candidate" else "native_ast_sha256"] = "0" * 64
        with pytest.raises(ValueError): parent_response_build(owner, value)

    assert calls == []

def test_parent_response_missing_context_and_definition_use_cannot_be_declared_closed(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for ordinal in range(6):
        value = parent_response_case(parent_response_originals)
        answer = value["response"]["answers"][ordinal]
        assert answer["finding"]["family"] == "original_parent_context"
        answer["disposition"] = "evidence_declared"
        with pytest.raises(ValueError): parent_response_build(owner, value)
    for damage in ("context_original", "definition_status", "definition_selected", "governing"):
        value = parent_response_case(parent_response_originals)
        if damage == "context_original": value["response"]["answers"][0]["finding"]["original_sha256"] = "0" * 64
        elif damage == "governing": value["response"]["governing_definition_use"] = {"chosen": True}
        else:
            finding = answer_for(value["response"], "definition_applicability")["finding"]
            if damage == "definition_status": finding["status"] = "applicable"
            else: finding["governing_definition_use"] = {"chosen": True}
        with pytest.raises(ValueError): parent_response_build(owner, value)

    assert calls == []

def test_parent_response_evidence_commitments_fail_before_genuine_replay(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for damage in ("manifest_pin", "raw_hash", "unused_raw_hash", "raw_count", "raw_type"):
        value = parent_response_case(parent_response_originals); overrides = {}
        if damage == "manifest_pin": overrides["expected_evidence_manifest_sha256"] = "0" * 64
        elif damage == "raw_count": value["evidence_manifest"]["artifacts"][0]["bytes"] += 1
        elif damage == "raw_type": value["evidence_artifacts"]["fixture:parent-response-evidence"] = bytearray(b"offered bytearray")
        else:
            identity = "fixture:parent-unused-evidence" if damage == "unused_raw_hash" else "fixture:parent-response-evidence"
            value["evidence_artifacts"][identity] += b"changed"
        with pytest.raises(ValueError): parent_response_build(owner, value, **overrides)
    assert calls == []


def test_parent_response_evidence_population_is_closed_unique_and_fully_committed(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for damage in ("duplicate", "missing_body", "extra_body", "missing_row", "schema", "extra_field", "boolean_size", "foreign_id"):
        value = parent_response_case(parent_response_originals); manifest = value["evidence_manifest"]; rows = manifest["artifacts"]
        if damage == "duplicate": rows.append(deepcopy(rows[0]))
        elif damage == "missing_body": value["evidence_artifacts"].pop(rows[-1]["artifact_id"])
        elif damage == "extra_body": value["evidence_artifacts"]["fixture:extra"] = b"uncommitted"
        elif damage == "missing_row": rows.pop()
        elif damage == "schema": manifest["schema"] = "legal-parent-norm-content-template/v1"
        elif damage == "extra_field": manifest["accepted"] = True
        elif damage == "boolean_size": rows[0]["bytes"] = True
        else:
            raw = value["evidence_artifacts"].pop(rows[0]["artifact_id"])
            rows[0]["artifact_id"] = "../untrusted"; value["evidence_artifacts"]["../untrusted"] = raw
        with pytest.raises(ValueError): parent_response_build(owner, value)
    assert calls == []


def test_parent_response_every_process_proposal_and_answer_reference_matches_original_bytes(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for location in ("process", "proposal", "answer"):
        for damage in ("missing", "wrong_hash", "duplicate"):
            value = parent_response_case(parent_response_originals); response = value["response"]
            references = (response["process_declaration"]["process_evidence_refs"] if location == "process" else
                          response["candidate_proposal"]["evidence_refs"] if location == "proposal" else
                          answer_for(response, "source_meaning")["evidence_refs"])
            if damage == "missing": references[0]["artifact_id"] = "fixture:not-supplied"
            elif damage == "wrong_hash": references[0]["sha256"] = "0" * 64
            else: references.append(deepcopy(references[0]))
            with pytest.raises(ValueError): parent_response_build(owner, value)
    assert calls == []


def test_parent_response_exact_self_bodies_are_not_supporting_evidence(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    for key in ("preparation", "response", "correspondence"):
        value = parent_response_case(parent_response_originals)
        body = value["build_arguments"]["correspondence"] if key == "correspondence" else value[key]
        raw = wire(body); identity = "fixture:self-body"
        value["evidence_artifacts"][identity] = raw
        value["evidence_manifest"]["artifacts"].append(dict(artifact_id=identity, bytes=len(raw), sha256=sha(raw)))
        with pytest.raises(ValueError): parent_response_build(owner, value)
    assert calls == []


def test_parent_response_independent_input_and_saved_report_pins_precede_replay(owner, parent_response_originals, tmp_path, monkeypatch):
    value = parent_response_case(parent_response_originals)
    calls = parent_response_no_replay(monkeypatch)
    for name in ("expected_preparation_sha256", "expected_response_sha256", "expected_correspondence_sha256"):
        with pytest.raises(ValueError): parent_response_build(owner, value, **{name: "0" * 64})
    with pytest.raises(ValueError):
        parent_response_validate(owner, value, {"schema": "not-a-response"}, expected_report_sha256="0" * 64)
    foreign = tmp_path / "foreign-producer.py"
    foreign.write_bytes(b"raise RuntimeError('offered producer must never be read')\n")
    actual_read, reads = Path.read_bytes, []
    def read(path):
        if path.resolve() == foreign.resolve():
            reads.append(str(path)); raise AssertionError("offered producer marker opened")
        return actual_read(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    value = parent_response_case(parent_response_originals)
    value["preparation"]["producer_pins"][str(foreign.resolve())] = "0" * 64
    value["build_arguments"]["expected_preparation_sha256"] = owner.norm_content_sha256(value["preparation"])
    with pytest.raises(ValueError): parent_response_build(owner, value)
    assert calls == [] and reads == []


def test_parent_response_explicit_closed_declarations_reject_blank_or_invented_metadata(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    pin_calls = []
    def no_pins():
        pin_calls.append("unexpected operation producer discovery")
        raise AssertionError("malformed completed declaration reached operation producer discovery")
    monkeypatch.setattr(owner, "_parent_response_pins", no_pins)
    for damage in ("blank_id", "role", "time", "calendar", "signature", "exposure_bool", "blank_statement", "no_support", "no_answer_evidence", "preparation_missing_ast"):
        value = parent_response_case(parent_response_originals); response = value["response"]
        if damage == "blank_id": response["review_id"] = None
        elif damage == "role": response["role"] = "governing_authority"
        elif damage == "time": response["issued_at_utc"] = "2026-10-24"
        elif damage == "calendar": response["issued_at_utc"] = "2026-02-30T00:00:00Z"
        elif damage == "signature": response["signature"] = {"verified": True}
        elif damage == "exposure_bool": response["exposure_declaration"]["candidate_interpretations_exposed"] = 1
        elif damage == "blank_statement": response["answers"][0]["finding"]["statement"] = None
        elif damage == "no_support": response["candidate_proposal"]["evidence_refs"] = []
        elif damage == "preparation_missing_ast":
            value["preparation"].pop("ast_sha256")
            value["build_arguments"]["expected_preparation_sha256"] = owner.norm_content_sha256(value["preparation"])
        else: answer_for(response, "source_meaning")["evidence_refs"] = []
        with pytest.raises(ValueError): parent_response_build(owner, value)
    assert calls == [] and pin_calls == []


def test_parent_response_resealed_saved_declarations_still_require_complete_regeneration(owner, parent_response_originals):
    value = parent_response_case(parent_response_originals); report = parent_response_build(owner, value)
    for damage in ("response", "occurrence", "context", "evidence", "authority", "mask_alias"):
        changed = deepcopy(report)
        if damage == "response": changed["response"]["answers"][0]["rationale"] += " replaced"
        elif damage == "occurrence": changed["source_identity"]["source_occurrence_cid"] = changed["source_identity"]["context_record_cid"]
        elif damage == "context": changed["original_parent_context"]["availability"] = "provided"
        elif damage == "evidence": changed["evidence_artifact_observations"][0]["sha256"] = "0" * 64
        elif damage == "authority": changed["norm_interpretation_ready"] = True
        else: changed["training_mask"] = False
        with pytest.raises(ValueError): parent_response_validate(owner, value, changed)


@pytest.mark.parametrize("damage", ["caller", "detached", "retained_opening", "retained_closing", "output"])
def test_parent_response_last_encoder_preserves_inputs_and_all_genuine_returns(owner, parent_response_originals, monkeypatch, damage):
    value = parent_response_case(parent_response_originals)
    actual_preflight, actual_replay, actual_wire = owner._parent_response_preflight, norm.validate_parent_norm_review_evidence_v1, norm._wire
    detached, retained, seen, changed = [], [], set(), []
    def preflight(*args, **kwargs):
        result = actual_preflight(*args, **kwargs)
        detached.append(args[1])
        return result
    def replay(*args, **kwargs):
        result = actual_replay(*args, **kwargs); retained.append(result); return result
    def encoder(report):
        raw = actual_wire(report)
        if type(report) is dict and report.get("schema") == "legal-parent-norm-content-response/v1":
            seen.add(id(report))
            if len(seen) > 1 and not changed:
                assert len(retained) == 2 and detached
                if damage == "caller": value["response"]["answers"][0]["rationale"] += " changed at final encoding"
                elif damage == "detached": detached[0]["answers"][0]["rationale"] += " changed at final encoding"
                elif damage == "retained_opening": retained[0]["training_mask"] = False
                elif damage == "retained_closing": retained[-1]["training_mask"] = False
                else: report["training_mask"] = False
                changed.append(damage)
        return raw
    monkeypatch.setattr(owner, "_parent_response_preflight", preflight)
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", replay)
    monkeypatch.setattr(norm, "_wire", encoder)
    with pytest.raises(ValueError): parent_response_build(owner, value)
    assert changed == [damage]


def test_parent_response_closing_replay_refuses_changed_original_physical_source(owner, fixtures, tmp_path, monkeypatch):
    value = parent_response_case(parent_content_materialize(fixtures, tmp_path))
    actual = norm.validate_parent_norm_review_evidence_v1
    path = next(tmp_path.rglob("laws.parquet")); original = path.read_bytes(); changed = []
    def replay(*args, **kwargs):
        result = actual(*args, **kwargs)
        if not changed:
            path.write_bytes(original + b"\nchanged after genuine response preparation replay\n")
            changed.append("actual original Parquet source")
        return result
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", replay)
    with pytest.raises(ValueError): parent_response_build(owner, value)
    assert changed == ["actual original Parquet source"]


def test_parent_response_primary_error_preserves_secondary_closing_notes(owner, parent_response_originals, monkeypatch):
    value = parent_response_case(parent_response_originals)
    actual = norm.validate_parent_norm_review_evidence_v1; calls = []
    def replay(*args, **kwargs):
        result = actual(*args, **kwargs); calls.append(result)
        value["response"]["answers"][0]["rationale"] += " changed after genuine replay"
        raise ValueError("primary authored unsigned parent response failure")
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", replay)
    with pytest.raises(ValueError) as caught: parent_response_build(owner, value)
    assert str(caught.value) == "primary authored unsigned parent response failure"
    assert calls and any("secondary" in note for note in getattr(caught.value, "__notes__", []))


def test_parent_response_unsigned_profile_stays_outside_legacy_signing_and_blank_validation(owner, parent_response_originals):
    value = parent_response_case(parent_response_originals); report = parent_response_build(owner, value)
    manifest = value["preparation"]["dependency_manifest"]
    legacy = dict(value["build_arguments"], expected_manifest_sha256=manifest["manifest_sha256"],
                  required_dependency_ids=value["preparation"]["required_dependency_ids"], context_inputs=None)
    with pytest.raises(ValueError):
        owner.build_norm_content_response_v1(value["preparation"], manifest, value["response"], **legacy)
    with pytest.raises(ValueError):
        parent_content_validate(owner, value, report)
    with pytest.raises(ValueError):
        parent_response_validate(owner, value, {"schema": owner.PARENT_TEMPLATE_SCHEMA, "profile": owner.PARENT_TEMPLATE_PROFILE})
    assert all(report[key] is None for key in ("subject", "signature", "clock", "registry", "policy"))
    assert report["governing_definition_use"] is None


def test_parent_response_lowered_snapshot_and_finite_evidence_bounds_refuse_before_replay(owner, parent_response_originals, monkeypatch):
    calls = parent_response_no_replay(monkeypatch)
    value = parent_response_case(parent_response_originals)
    for index in range(255):
        identity = "fixture:bounded-extra:" + str(index); raw = b"x"
        value["evidence_artifacts"][identity] = raw
        value["evidence_manifest"]["artifacts"].append(dict(artifact_id=identity, bytes=1, sha256=sha(raw)))
    assert len(value["evidence_manifest"]["artifacts"]) == 257
    with pytest.raises(ValueError): parent_response_build(owner, value)
    value = parent_response_case(parent_response_originals)
    with monkeypatch.context() as local:
        local.setattr(owner, "PARENT_MAX_EVIDENCE_BYTES", max(map(len, value["evidence_artifacts"].values())))
        with pytest.raises(ValueError): parent_response_build(owner, value)
    value = parent_response_case(parent_response_originals)
    references = []
    for index in range(9):
        identity = "fixture:bounded-reference:" + str(index); raw = str(index).encode()
        value["evidence_artifacts"][identity] = raw
        value["evidence_manifest"]["artifacts"].append(dict(artifact_id=identity, bytes=len(raw), sha256=sha(raw)))
        references.append(dict(artifact_id=identity, sha256=sha(raw)))
    value["response"]["process_declaration"]["process_evidence_refs"] = references
    with pytest.raises(ValueError): parent_response_build(owner, value)
    value = parent_response_case(parent_response_originals)
    with monkeypatch.context() as local:
        local.setattr(norm, "MAX_INPUT_BYTES", 64)
        with pytest.raises(ValueError): parent_response_build(owner, value)
    assert calls == []


# A collection inventories supplied unsigned declarations.  Repeated labels,
# matching answers and exact evidence bytes supply no human review or quorum.
@pytest.fixture(scope="module")
def parent_collection_seed(owner, parent_response_originals):
    first = parent_response_case(parent_response_originals)
    second = parent_response_case(parent_response_originals)
    second["response"]["review_id"] = "fixture:parent-second-declaration"
    second["response"]["role"] = "formal_review"
    # Keep the same declared principal deliberately: two roles are not identity
    # verification or evidence of independent people.
    assert second["response"]["principal_id"] == first["response"]["principal_id"]
    second["response"]["candidate_proposal"]["decision"] = "reject"
    source = answer_for(second["response"], "source_meaning")["finding"]
    source["source_assertions"][0]["assessment"] = "dispute"
    issue = answer_for(second["response"], "original_unresolved_issue")
    issue["rationale"] += " A separately supplied rationale remains an exact variant."
    second["response"]["answers"][0]["evidence_refs"] = []
    reports = [parent_response_build(owner, value) for value in (first, second)]
    # These reports are built with this newly imported owner generation.  No
    # historical 7bc report is relabelled after the owner gains collection APIs.
    return dict(cases=[first, second], reports=reports)


def parent_collection_case(seed, *, count=1):
    first = seed["cases"][0]
    value = dict(preparation=deepcopy(first["preparation"]),
        build_arguments=deepcopy(first["build_arguments"]),
        reports=deepcopy(seed["reports"][:count]),
        evidence_artifacts=[deepcopy(row["evidence_artifacts"]) for row in seed["cases"][:count]])
    parent_collection_manifest(value)
    return value


def parent_collection_manifest(value):
    value["population_manifest"] = {"schema": "legal-parent-norm-response-population/v1", "responses": [
        {"review_id": report["response"]["review_id"], "report_sha256": norm.norm_review_sha256(report)}
        for report in value["reports"]]}


def parent_collection_arguments(owner, value):
    return dict(value["build_arguments"],
        expected_population_manifest_sha256=owner.norm_content_sha256(value["population_manifest"]),
        evidence_artifacts=value["evidence_artifacts"])


def parent_collection_collect(owner, value, **overrides):
    arguments = parent_collection_arguments(owner, value); arguments.update(overrides)
    return owner.collect_parent_norm_content_responses_v1(value["preparation"],
        value["population_manifest"], value["reports"], **arguments)


def parent_collection_validate(owner, value, report, **overrides):
    arguments = parent_collection_arguments(owner, value)
    arguments["expected_report_sha256"] = owner.norm_content_sha256(report)
    arguments.update(overrides)
    return owner.validate_parent_norm_content_collection_v1(report, value["preparation"],
        value["population_manifest"], value["reports"], **arguments)


def parent_collection_no_replay(owner, monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append("unexpected genuine collection dependency replay")
        raise AssertionError("malformed collection reached genuine dependency replay")
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", denied)
    monkeypatch.setattr(owner, "validate_parent_norm_content_response_v1", denied)
    return calls


def assert_parent_collection_unsigned(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert report["norm_interpretation_ready"] is False
    assert report["selected_interpretation"] is report["accepted_interpretation"] is None
    assert report["governing_definition_use"] is None
    for key in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0
    assert all(report[key] is None for key in ("subject", "signature", "clock", "registry", "policy"))
    assert report["counts"]["authenticated_responses"] == report["counts"]["applied_meaning_decisions"] == 0
    assert all(row["decision"] is row["adjudicator_declaration"] is None for row in report["pending_questions"])
    assert all(row["authenticated"] is False for row in report["response_results"])
    assert all(report[key] is False for key in ("declared_roles_authenticated", "reviewer_declarations_verified",
        "evidence_identity_verified", "evidence_independence_verified", "evidence_truth_verified",
        "quorum_established", "source_context_closed", "legacy_signing_or_adjudication_submission_allowed"))


def test_parent_collection_two_declared_roles_keep_exact_variants_without_quorum(owner, parent_collection_seed):
    value = parent_collection_case(parent_collection_seed, count=2); before = deepcopy(value)
    report = parent_collection_collect(owner, value)
    assert report["schema"] == "legal-parent-norm-content-collection/v1"
    assert report["profile"] == "unsigned-parent-literal-response-collection/v1"
    assert report["preparation"] == value["preparation"]
    assert report["source_identity"] == value["preparation"]["source_identity"]
    assert report["original_parent_context"] == value["preparation"]["original_parent_context"]
    assert report["source_rows"] == value["preparation"]["source_rows"]
    assert report["typed_context_inventory"] == value["preparation"]["typed_context_inventory"]
    assert report["population_manifest"] == value["population_manifest"]
    results = report["response_results"]
    assert len(results) == 2
    assert [row["response_record"] for row in results] == [row["response"] for row in value["reports"]]
    assert [row["report_sha256"] for row in results] == [row["report_sha256"] for row in value["population_manifest"]["responses"]]
    assert [row["role"] for row in results] == ["legal_review", "formal_review"]
    assert len({row["principal_id"] for row in results}) == 1
    assert report["counts"]["responses"] == 2
    assert report["counts"]["declared_legal_role"] == report["counts"]["declared_formal_role"] == 1
    assert [row["proposal"]["decision"] for row in report["candidate_proposals"]] == ["support", "reject"]
    obligations = value["preparation"]["obligations"]
    assert len(obligations) == len(report["pending_questions"]) == report["counts"]["pending_questions"] == 14
    assert len(report["answer_variants"]) == report["counts"]["answer_variants"] == 17
    changed_slots = {value["reports"][0]["response"]["answers"][0]["slot_id"],
                     answer_for(value["reports"][0]["response"], "source_meaning")["slot_id"],
                     answer_for(value["reports"][0]["response"], "original_unresolved_issue")["slot_id"]}
    expected_variant_order = []
    for ordinal, (pending, obligation) in enumerate(zip(report["pending_questions"], obligations, strict=True)):
        assert pending["slot_id"] == obligation["slot_id"]
        assert pending["obligation_sha256"] == owner.norm_content_sha256(obligation)
        assert pending["answer_variant_refs"] == [dict(variant_index=index, sha256=owner.norm_content_sha256(variant))
            for index, variant in enumerate(report["answer_variants"]) if variant["slot_id"] == pending["slot_id"]]
        variants = [row for row in report["answer_variants"] if row["slot_id"] == pending["slot_id"]]
        assert len(variants) == (2 if pending["slot_id"] in changed_slots else 1)
        expected_hashes = list(dict.fromkeys(owner.norm_content_sha256(row["response"]["answers"][ordinal])
                                          for row in value["reports"]))
        assert [row["answer_sha256"] for row in variants] == expected_hashes
        expected_variant_order.extend(expected_hashes)
        for variant in variants:
            assert owner.norm_content_sha256(variant["answer"]) == variant["answer_sha256"]
            expected_indices = [index for index, supplied in enumerate(value["reports"])
                                if supplied["response"]["answers"][ordinal] == variant["answer"]]
            assert [row["response_result_index"] for row in variant["respondents"]] == expected_indices
            assert [row["report_sha256"] for row in variant["respondents"]] == [results[index]["report_sha256"] for index in expected_indices]
        assert "repeated_declared_principal_id" in pending["issues"]
        assert "distinct_declared_role_principal_pair_missing" in pending["issues"]
        if pending["slot_id"] in changed_slots: assert "distinct_exact_answer_variants" in pending["issues"]
        if ordinal < 6 or obligation.get("question") == "definition_applicability":
            assert "unresolved_typed_answer" in pending["issues"]
    assert [row["answer_sha256"] for row in report["answer_variants"]] == expected_variant_order
    assert_parent_collection_unsigned(report)
    assert parent_collection_validate(owner, value, report) == report
    assert value == before


def test_parent_collection_empty_population_still_replays_original_preparation_and_keeps_every_slot(owner, parent_collection_seed, monkeypatch):
    value = parent_collection_case(parent_collection_seed, count=0)
    actual = norm.validate_parent_norm_review_evidence_v1; seen = []
    def replay(*args, **kwargs):
        result = actual(*args, **kwargs); seen.append(result); return result
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", replay)
    report = parent_collection_collect(owner, value)
    assert len(seen) >= 2
    assert report["response_results"] == report["answer_variants"] == report["candidate_proposals"] == []
    assert len(report["pending_questions"]) == len(value["preparation"]["obligations"]) == 14
    assert report["counts"]["responses"] == report["counts"]["answer_variants"] == 0
    assert all(row["answer_variant_refs"] == row["declared_respondents"] == [] for row in report["pending_questions"])
    assert_parent_collection_unsigned(report)


def test_parent_collection_population_commitment_order_and_unique_review_ids_precede_replay(owner, parent_collection_seed, monkeypatch):
    calls = parent_collection_no_replay(owner, monkeypatch)
    for damage in ("pin", "drop_report", "swap_reports", "duplicate_id", "drop_row", "row_hash", "extra_manifest_field", "wrong_schema"):
        value = parent_collection_case(parent_collection_seed, count=2); rows = value["population_manifest"]["responses"]; overrides = {}
        if damage == "pin": overrides["expected_population_manifest_sha256"] = "0" * 64
        elif damage == "drop_report": value["reports"].pop()
        elif damage == "swap_reports": value["reports"].reverse()
        elif damage == "duplicate_id": rows[1]["review_id"] = rows[0]["review_id"]
        elif damage == "drop_row": rows.pop()
        elif damage == "row_hash": rows[0]["report_sha256"] = "0" * 64
        elif damage == "extra_manifest_field": value["population_manifest"]["accepted"] = True
        else: value["population_manifest"]["schema"] = "legal-parent-norm-response-evidence/v1"
        with pytest.raises(ValueError): parent_collection_collect(owner, value, **overrides)
    assert calls == []


def test_parent_collection_rawless_same_schema_and_every_supplied_evidence_body_are_checked(owner, parent_collection_seed, monkeypatch):
    calls = parent_collection_no_replay(owner, monkeypatch)
    for damage in ("references_only", "missing_manifest", "changed_unused_body", "missing_body", "extra_body", "foreign_preparation"):
        value = parent_collection_case(parent_collection_seed); report = value["reports"][0]
        if damage == "references_only":
            report.pop("evidence_manifest"); report.pop("evidence_manifest_sha256")
            report["evidence_bytes_supplied"] = False
        elif damage == "missing_manifest": report.pop("evidence_manifest_sha256")
        elif damage == "changed_unused_body": value["evidence_artifacts"][0]["fixture:parent-unused-evidence"] += b"changed"
        elif damage == "missing_body": value["evidence_artifacts"][0].pop("fixture:parent-unused-evidence")
        elif damage == "extra_body": value["evidence_artifacts"][0]["fixture:extra"] = b"uncommitted"
        else: report["preparation_sha256"] = "0" * 64
        parent_collection_manifest(value)
        with pytest.raises(ValueError): parent_collection_collect(owner, value)
    assert calls == []


def test_parent_collection_rejects_genuine_individual_cross_response_support(owner, parent_collection_seed, monkeypatch):
    peer_report = parent_collection_seed["reports"][1]
    for source in (peer_report, peer_report["response"]):
        first = deepcopy(parent_collection_seed["cases"][0]); raw = wire(source)
        identity = "fixture:other-population-body"
        first["evidence_artifacts"][identity] = raw
        first["evidence_manifest"]["artifacts"].append(dict(artifact_id=identity, bytes=len(raw), sha256=sha(raw)))
        answer_for(first["response"], "source_meaning")["evidence_refs"] = [dict(artifact_id=identity, sha256=sha(raw))]
        genuine_first = parent_response_build(owner, first)
        assert genuine_first["response"] == first["response"]
        value = parent_collection_case(parent_collection_seed, count=2)
        value["reports"][0] = genuine_first; value["evidence_artifacts"][0] = first["evidence_artifacts"]
        parent_collection_manifest(value)
        # The individual's complete original replay accepted the bytes above.
        # Only the complete collection population exposes their circular role.
        with monkeypatch.context() as local:
            calls = parent_collection_no_replay(owner, local)
            with pytest.raises(ValueError): parent_collection_collect(owner, value)
            assert calls == []


def test_parent_collection_independent_pins_and_bounded_malformed_preparation_refuse_before_owners(owner, parent_collection_seed, monkeypatch):
    calls = parent_collection_no_replay(owner, monkeypatch); pinner_calls = []
    def pinner():
        pinner_calls.append("unexpected collection producer discovery")
        raise AssertionError("malformed collection reached producer discovery")
    monkeypatch.setattr(owner, "_parent_collection_pins", pinner)
    value = parent_collection_case(parent_collection_seed)
    for field in ("expected_preparation_sha256", "expected_correspondence_sha256"):
        with pytest.raises(ValueError): parent_collection_collect(owner, value, **{field: "0" * 64})
    malformed = parent_collection_case(parent_collection_seed); malformed["preparation"].pop("ast_sha256")
    malformed["build_arguments"]["expected_preparation_sha256"] = owner.norm_content_sha256(malformed["preparation"])
    with pytest.raises(ValueError): parent_collection_collect(owner, malformed)
    with pytest.raises(ValueError):
        parent_collection_validate(owner, value, {"schema": "not-a-collection"}, expected_report_sha256="0" * 64)
    assert calls == [] and pinner_calls == []


def test_parent_collection_resealed_inventory_cannot_move_variants_drop_respondents_or_promote(owner, parent_collection_seed):
    value = parent_collection_case(parent_collection_seed); report = parent_collection_collect(owner, value)
    for damage in ("respondent", "slot", "mask"):
        changed = deepcopy(report)
        if damage == "respondent": changed["answer_variants"][0]["respondents"].clear()
        elif damage == "slot": changed["pending_questions"][0]["answer_variant_refs"] = deepcopy(changed["pending_questions"][1]["answer_variant_refs"])
        else: changed["training_mask"] = False
        with pytest.raises(ValueError): parent_collection_validate(owner, value, changed)


@pytest.mark.parametrize("damage", ["caller_evidence", "detached_population", "retained_member", "retained_closing", "output"])
def test_parent_collection_final_encoder_preserves_original_inputs_and_genuine_member_returns(owner, parent_collection_seed, monkeypatch, damage):
    value = parent_collection_case(parent_collection_seed)
    actual_preflight, actual_member, actual_wire = owner._parent_collection_preflight, owner.validate_parent_norm_content_response_v1, norm._wire
    actual_preparation = norm.validate_parent_norm_review_evidence_v1
    detached, retained, preparations, member_preparation_counts, seen, changed = [], [], [], [], set(), []
    def preflight(*args, **kwargs):
        result = actual_preflight(*args, **kwargs); detached.append(args[1]); return result
    def preparation(*args, **kwargs):
        result = actual_preparation(*args, **kwargs); preparations.append(result); return result
    def member(*args, **kwargs):
        result = actual_member(*args, **kwargs); retained.append(result)
        member_preparation_counts.append(len(preparations)); return result
    def encoder(report):
        raw = actual_wire(report)
        if type(report) is dict and report.get("schema") == "legal-parent-norm-content-collection/v1":
            seen.add(id(report))
            if len(seen) > 1 and not changed:
                assert retained and detached
                if damage == "caller_evidence": value["evidence_artifacts"][0]["fixture:parent-unused-evidence"] += b"late bytes"
                elif damage == "detached_population": detached[0]["responses"][0]["review_id"] += ":late"
                elif damage == "retained_member": retained[0]["training_mask"] = False
                elif damage == "retained_closing":
                    assert member_preparation_counts and len(preparations) > member_preparation_counts[-1]
                    preparations[-1]["training_mask"] = False
                else: report["training_mask"] = False
                changed.append(damage)
        return raw
    monkeypatch.setattr(owner, "_parent_collection_preflight", preflight)
    monkeypatch.setattr(owner, "validate_parent_norm_content_response_v1", member)
    monkeypatch.setattr(norm, "validate_parent_norm_review_evidence_v1", preparation)
    monkeypatch.setattr(norm, "_wire", encoder)
    with pytest.raises(ValueError): parent_collection_collect(owner, value)
    assert changed == [damage]


def test_parent_collection_closing_original_replay_refuses_physical_source_drift(owner, fixtures, tmp_path, monkeypatch):
    first = parent_response_case(parent_content_materialize(fixtures, tmp_path)); seed = dict(cases=[first], reports=[parent_response_build(owner, first)])
    value = parent_collection_case(seed); actual = owner.validate_parent_norm_content_response_v1
    path = next(tmp_path.rglob("laws.parquet")); original = path.read_bytes(); changed = []
    def member(*args, **kwargs):
        result = actual(*args, **kwargs)
        if not changed:
            path.write_bytes(original + b"\nchanged after a genuine collection member replay\n")
            changed.append("actual original physical source")
        return result
    monkeypatch.setattr(owner, "validate_parent_norm_content_response_v1", member)
    with pytest.raises(ValueError): parent_collection_collect(owner, value)
    assert changed == ["actual original physical source"]


def test_parent_collection_primary_error_keeps_secondary_closing_note(owner, parent_collection_seed, monkeypatch):
    value = parent_collection_case(parent_collection_seed); actual = owner.validate_parent_norm_content_response_v1; seen = []
    def member(*args, **kwargs):
        result = actual(*args, **kwargs); seen.append(result)
        value["population_manifest"]["responses"][0]["review_id"] += ":late"
        raise ValueError("primary authored unsigned collection failure")
    monkeypatch.setattr(owner, "validate_parent_norm_content_response_v1", member)
    with pytest.raises(ValueError) as caught: parent_collection_collect(owner, value)
    assert str(caught.value) == "primary authored unsigned collection failure"
    assert seen and any("secondary" in note for note in getattr(caught.value, "__notes__", []))


def test_parent_collection_legacy_assessment_profiles_are_not_unsigned_collection_inputs(owner, parent_collection_seed, monkeypatch):
    value = parent_collection_case(parent_collection_seed)
    calls = parent_collection_no_replay(owner, monkeypatch)
    for schema, profile in ((owner.ASSESSMENT_SCHEMA, owner.PROFILE),
                            ("legal-norm-content-adjudication-assessment/v1", "unapplied-common-norm-answer-adjudication/v1")):
        offered = dict(schema=schema, profile=profile)
        with pytest.raises(ValueError): parent_collection_validate(owner, value, offered)
    assert calls == []


def test_parent_collection_finite_population_and_aggregate_evidence_bounds_refuse_without_truncation(owner, parent_collection_seed, monkeypatch):
    calls = parent_collection_no_replay(owner, monkeypatch)
    value = parent_collection_case(parent_collection_seed)
    row = value["population_manifest"]["responses"][0]
    value["population_manifest"]["responses"] = [dict(row, review_id="fixture:bounded:" + str(index)) for index in range(33)]
    value["reports"] *= 33; value["evidence_artifacts"] *= 33
    with pytest.raises(ValueError): parent_collection_collect(owner, value)
    value = parent_collection_case(parent_collection_seed, count=2)
    per_member_totals = [sum(map(len, bodies.values())) for bodies in value["evidence_artifacts"]]
    assert sum(per_member_totals) > max(per_member_totals)
    with monkeypatch.context() as local:
        local.setattr(owner, "PARENT_MAX_EVIDENCE_BYTES", max(per_member_totals))
        with pytest.raises(ValueError): parent_collection_collect(owner, value)
    value = parent_collection_case(parent_collection_seed)
    with monkeypatch.context() as local:
        local.setattr(norm, "MAX_INPUT_BYTES", 64)
        with pytest.raises(ValueError): parent_collection_collect(owner, value)
    assert calls == []


def test_parent_collection_distinct_declared_principal_agreement_never_establishes_consensus(owner, parent_collection_seed):
    second = deepcopy(parent_collection_seed["cases"][0])
    second["response"]["review_id"] = "fixture:other-formal-declaration"
    second["response"]["principal_id"] = "fixture:other-declared-principal"
    second["response"]["role"] = "formal_review"
    second_report = parent_response_build(owner, second)
    value = parent_collection_case(parent_collection_seed)
    value["reports"].append(second_report)
    value["evidence_artifacts"].append(second["evidence_artifacts"])
    parent_collection_manifest(value)
    report = parent_collection_collect(owner, value)
    assert report["distinct_declared_role_principal_pair_present"] is True
    assert report["repeated_declared_principal_ids"] == []
    assert report["counts"]["responses"] == 2
    assert report["counts"]["answer_variants"] == report["counts"]["pending_questions"] == 14
    assert report["counts"]["declared_legal_role"] == report["counts"]["declared_formal_role"] == 1
    assert all(len(variant["respondents"]) == 2 for variant in report["answer_variants"])
    assert all("unsigned_declarations_not_authenticated" in row["issues"]
               and "separate_review_and_adjudication_required" in row["issues"]
               for row in report["pending_questions"])
    assert all("distinct_declared_role_principal_pair_missing" not in row["issues"]
               for row in report["pending_questions"])
    assert_parent_collection_unsigned(report)
