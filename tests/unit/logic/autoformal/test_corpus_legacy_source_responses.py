"""Typed source declarations remain pending evidence, never source decisions.

Every source, principal, key, finding and evidence body in this module is an
engineering fixture. No case represents a human source or meaning review.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as joins
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as source_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_legacy_source_authentication_for_typed_responses",
        Path(__file__).with_name("test_corpus_legacy_source_review_auth.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_responses

    return corpus_legacy_source_responses


def record_arguments(data):
    return {
        **data["arguments"],
        "request_ordinal": 0,
        "expected_preparation_manifest_sha256": sha(wire(data["preparation"]["manifest"])),
    }


def declaration(data, index=0, *, disposition="evidence_declared"):
    signed = data["reviews"][index]
    refs = [{"artifact_id": name, "sha256": sha(raw)}
            for name, raw in data["evidence_artifacts"].items()]
    finding_status = "unavailable" if disposition == "unresolved" else disposition
    active = [question for question in data["preparation"]["requests"][0]["review_questions"]
              if question["assessment_scope"] == "source_context_evidence_declaration"]
    return {
        "review_id": signed["review_id"],
        "principal_id": signed["principal_id"],
        "role": signed["role"],
        "issued_at_utc": signed["issued_at_utc"],
        "process_declaration": {
            "identity_evidence_refs": [],
            "independence_evidence_refs": [],
            "process_evidence_refs": [],
        },
        "exposure_declaration": {
            "candidate_interpretations_exposed": None,
            "organizer_source_metadata_exposed": True,
            "other_exposure": "Fictional engineering fixture; no human review.",
        },
        "answers": [{
            "slot_id": question["slot_id"],
            "category": question["category"],
            "kind": question["kind"],
            "disposition": disposition,
            "finding": {"status": finding_status,
                        "statement": "Fictional source declaration for interface testing."},
            "rationale": "Fixture evidence declares this answer without establishing legal truth.",
            "evidence_refs": [] if disposition == "unresolved" else deepcopy(refs),
        } for question in active],
        "occurrence_proposal": {
            "status": "unresolved",
            "candidate_occurrence_cid": None,
            "rationale": "Both fictional occurrences remain unselected.",
            "evidence_refs": [],
        },
    }


def record(owner, data, response):
    return owner.record_legacy_source_response(
        data["preparation"], response, **record_arguments(data))


def install_record(data, index, response_record):
    raw = wire(response_record)
    identity = response_record["record_cid"]
    data["evidence_artifacts"][identity] = raw
    binding = {"review_id": data["reviews"][index]["review_id"],
               "artifact_id": identity, "raw_sha256": sha(raw)}
    data["response_bindings"][index] = binding
    unresolved = [answer["slot_id"] for answer in response_record["answers"]
                  if answer["disposition"] == "unresolved"]
    disposition_map = {"unresolved": "open", "evidence_declared": "resolved_by_evidence",
                       "not_applicable": "not_applicable"}
    data["reviews"][index]["context_closure"] = {
        "status": "open" if unresolved else "declared_complete",
        "unresolved": unresolved,
        "obligations": [{
            "slot_id": answer["slot_id"],
            "disposition": disposition_map[answer["disposition"]],
            "evidence_refs": [{"artifact_id": identity, "sha256": sha(raw)}],
        } for answer in response_record["answers"]],
    }
    helper().refresh_signatures(data)


def response_case(owner, *, disposition="evidence_declared"):
    data = helper().signed_case(source_owner, trust_mode="external_pinned_trust")
    # Build declarations before installing response bodies, so the authored
    # evidence refs cannot accidentally include another reviewer's response.
    responses = [declaration(data, index, disposition=disposition)
                 for index in range(len(data["reviews"]))]
    data["response_bindings"] = [None] * len(responses)
    data["responses"] = responses
    data["response_records"] = [record(owner, data, response) for response in responses]
    for index, body in enumerate(data["response_records"]):
        install_record(data, index, body)
    return data


def assessment_arguments(data):
    return {
        **record_arguments(data),
        "expected_registry_sha256": sha(wire(data["registry"])),
        "expected_policy_sha256": sha(wire(data["policy"])),
        "expected_reviews_sha256": sha(wire(data["reviews"])),
        "at_time_utc": helper().NOW,
        "observed_artifact_sha256s": data["observed_artifact_sha256s"],
        "observed_pins": data["observed_pins"],
        "evidence_artifacts": data["evidence_artifacts"],
        "response_bindings": data["response_bindings"],
        "expected_response_bindings_sha256": sha(wire(data["response_bindings"])),
    }


def assess(owner, data, **overrides):
    return owner.assess_legacy_source_responses(
        data["preparation"], data["registry"], data["policy"], data["reviews"],
        **{**assessment_arguments(data), **overrides})


def no_decision(result):
    assert result["selected_occurrence"] is None
    assert result["counts"]["applied_source_decisions"] == 0
    for flag in trust_owner.FALSE_AUTHORITY:
        assert result[flag] is False
    assert len(result["pending_questions"]) == 9
    assert result["counts"]["pending_adjudication_slots"] == 9
    assert all(row["status"] == "pending_adjudication_not_a_decision"
               for row in result["pending_questions"])


def test_response_round_trip_replays_source_without_mutation(owner):
    data = helper().signed_case(source_owner)
    response = declaration(data)
    before = deepcopy((data["preparation"], response))
    body = record(owner, data, response)
    assert owner.validate_legacy_source_response(
        body, data["preparation"], response, **record_arguments(data)) == body
    assert (data["preparation"], response) == before
    assert body["answers"] == response["answers"]
    assert body["selected_occurrence"] is None
    assert body["original_producer_occurrence_attested"] is False


def test_blank_template_retains_source_binding_and_deferred_questions_without_being_submittable(owner):
    data = helper().signed_case(source_owner)
    template = owner.prepare_legacy_source_response_template(
        data["preparation"], **record_arguments(data))
    response = template["response"]
    assert template["request_ref"]["record_cid"] == data["preparation"]["requests"][0]["record_cid"]
    assert template["subject_ref"]["record_cid"] == data["preparation"]["subjects"][0]["record_cid"]
    assert template["preparation_manifest_sha256"] == sha(wire(data["preparation"]["manifest"]))
    assert len(response["answers"]) == 9
    assert len(template["deferred_review_slot_ids"]) == 7
    assert all(response[field] is None for field in ("review_id", "principal_id", "role", "issued_at_utc"))
    assert all(answer["disposition"] is None and answer["finding"]["status"] is None
               for answer in response["answers"])
    assert template["selected_occurrence"] is None
    assert template["status"] == "blank_unsubmitted_template_not_a_response"
    with pytest.raises(ValueError):
        record(owner, data, response)


def test_agreeing_typed_answers_remain_pending_even_with_valid_signatures(owner):
    data = response_case(owner)
    result = assess(owner, data)
    assert result["raw_source_assessment"]["authenticated_evidence_count"] == 2
    assert result["counts"]["authenticated_typed_responses"] == 2
    assert result["counts"]["different_answer_slots"] == 0
    assert all(row["authenticated_typed_content"] for row in result["response_results"])
    assert all(row["typed_answer_declarations_complete"] for row in result["response_results"])
    # Different signed response bodies must not erase the old verifier's
    # exact-evidence disagreement, even when the typed answer values agree.
    assert "authenticated_context_declarations_disagree" in result["raw_source_assessment"]["blockers"]
    no_decision(result)
    assert owner.validate_legacy_source_responses(
        result, data["preparation"], data["registry"], data["policy"], data["reviews"],
        **assessment_arguments(data)) == result


def test_signed_unresolved_answers_remain_authenticated_and_open(owner):
    data = response_case(owner, disposition="unresolved")
    result = assess(owner, data)
    assert result["counts"]["authenticated_typed_responses"] == 2
    assert result["counts"]["unresolved_answer_slots"] == 9
    assert not any(row["typed_answer_declarations_complete"] for row in result["response_results"])
    assert all(row["content_status"] == "valid_declared_content" for row in result["response_results"])
    no_decision(result)


def test_empty_response_population_preserves_all_missing_questions(owner):
    data = response_case(owner)
    data["reviews"] = []
    data["response_bindings"] = []
    result = assess(owner, data)
    assert result["counts"]["responses"] == 0
    assert result["counts"]["authenticated_typed_responses"] == 0
    assert result["counts"]["missing_authenticated_answer_slots"] == 9
    no_decision(result)


def test_bad_signature_does_not_become_authenticated_through_a_valid_body(owner):
    data = response_case(owner)
    signature = data["reviews"][0]["signature"]
    data["reviews"][0]["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    result = assess(owner, data)
    assert result["raw_source_assessment"]["authenticated_evidence_count"] == 1
    assert result["response_results"][0]["authenticated_typed_content"] is False
    assert result["counts"]["authenticated_typed_responses"] == 1
    no_decision(result)


def test_different_findings_are_retained_without_choosing_a_winner(owner):
    data = response_case(owner)
    data["responses"][1]["answers"][0]["finding"]["statement"] = "A different fictional declaration."
    install_record(data, 1, record(owner, data, data["responses"][1]))
    result = assess(owner, data)
    assert result["counts"]["different_answer_slots"] == 1
    assert result["counts"]["authenticated_typed_responses"] == 2
    assert len(result["pending_questions"][0]["answer_variant_refs"]) == 2
    no_decision(result)


@pytest.mark.parametrize("disposition", ["evidence_declared", "not_applicable"])
def test_resolved_or_not_applicable_answers_need_evidence(owner, disposition):
    data = helper().signed_case(source_owner)
    response = declaration(data, disposition=disposition)
    response["answers"][0]["evidence_refs"] = []
    with pytest.raises(ValueError):
        record(owner, data, response)


@pytest.mark.parametrize("damage", ["unknown_finding", "unavailable_resolved", "ambiguous_resolved",
                                    "extra_answer", "missing_answer", "reordered_answers",
                                    "deferred_slot", "category", "kind", "unknown_field"])
def test_invalid_or_contradictory_answer_contracts_are_refused(owner, damage):
    data = helper().signed_case(source_owner)
    response = declaration(data)
    answer = response["answers"][0]
    if damage == "unknown_finding":
        answer["finding"]["status"] = "proven"
    elif damage == "unavailable_resolved":
        answer["finding"]["status"] = "unavailable"
    elif damage == "ambiguous_resolved":
        answer["finding"]["status"] = "ambiguous"
    elif damage == "extra_answer":
        response["answers"].append(deepcopy(answer))
    elif damage == "missing_answer":
        response["answers"].pop()
    elif damage == "reordered_answers":
        response["answers"][:2] = reversed(response["answers"][:2])
    elif damage == "deferred_slot":
        answer["slot_id"] = data["preparation"]["subjects"][0]["deferred_review_slot_ids"][0]
    elif damage in {"category", "kind"}:
        answer[damage] = "unsupported"
    else:
        response["original_producer_occurrence_attested"] = True
    with pytest.raises(ValueError):
        record(owner, data, response)


@pytest.mark.parametrize("damage", ["wrong_pin", "missing_binding", "duplicate_binding", "reordered_binding"])
def test_binding_population_is_independently_pinned_and_complete(owner, damage):
    data = response_case(owner)
    arguments = assessment_arguments(data)
    if damage == "wrong_pin":
        arguments["expected_response_bindings_sha256"] = "0" * 64
    else:
        if damage == "missing_binding":
            data["response_bindings"].pop()
        elif damage == "duplicate_binding":
            data["response_bindings"][1] = deepcopy(data["response_bindings"][0])
        else:
            data["response_bindings"].reverse()
        arguments = assessment_arguments(data)
    with pytest.raises(ValueError):
        assess(owner, data, **arguments)


@pytest.mark.parametrize("damage", ["status", "unresolved", "disposition", "wrong_ref", "extra_ref"])
def test_signed_closure_must_exactly_match_typed_response(owner, damage):
    data = response_case(owner)
    closure = data["reviews"][0]["context_closure"]
    if damage == "status":
        closure["status"] = "open"
    elif damage == "unresolved":
        closure["unresolved"] = [closure["obligations"][0]["slot_id"]]
    elif damage == "disposition":
        closure["obligations"][0]["disposition"] = "not_applicable"
    else:
        original = {"artifact_id": "fixture:legacy-source-declaration",
                    "sha256": sha(data["evidence_artifacts"]["fixture:legacy-source-declaration"])}
        if damage == "wrong_ref":
            closure["obligations"][0]["evidence_refs"] = [original]
        else:
            closure["obligations"][0]["evidence_refs"].append(original)
    helper().refresh_signatures(data)
    result = assess(owner, data)
    assert result["raw_source_assessment"]["authenticated_evidence_count"] == 2
    assert result["response_results"][0]["content_status"] == "rejected"
    assert result["response_results"][0]["content_blockers"]
    assert result["counts"]["authenticated_typed_responses"] == 1
    assert result["counts"]["rejected_content_responses"] == 1
    no_decision(result)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_changed_response_body_never_supplies_typed_answers(owner, damage):
    data = response_case(owner)
    identity = data["response_bindings"][0]["artifact_id"]
    if damage == "missing":
        del data["evidence_artifacts"][identity]
    else:
        data["evidence_artifacts"][identity] += b" "
    result = assess(owner, data)
    assert result["response_results"][0]["content_status"] == "rejected"
    assert result["counts"]["authenticated_typed_responses"] == 1
    no_decision(result)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_typed_supporting_evidence_is_checked_beyond_signed_body_custody(owner, damage):
    data = response_case(owner)
    identity = "fixture:legacy-source-declaration"
    if damage == "missing":
        del data["evidence_artifacts"][identity]
    else:
        data["evidence_artifacts"][identity] += b" changed support"
    result = assess(owner, data)
    assert result["raw_source_assessment"]["authenticated_evidence_count"] == 2
    assert all(row["signed_context_declaration_complete"]
               for row in result["raw_source_assessment"]["reviews"])
    assert result["counts"]["authenticated_typed_responses"] == 0
    assert result["counts"]["rejected_content_responses"] == 2
    assert result["counts"]["missing_authenticated_answer_slots"] == 9
    no_decision(result)


def test_noncanonical_response_formatting_requires_its_actual_raw_hash(owner):
    data = response_case(owner)
    binding = data["response_bindings"][0]
    raw = json.dumps(data["response_records"][0], ensure_ascii=False, indent=2).encode()
    assert raw != wire(data["response_records"][0])
    data["evidence_artifacts"][binding["artifact_id"]] = raw
    binding["raw_sha256"] = sha(raw)
    for obligation in data["reviews"][0]["context_closure"]["obligations"]:
        obligation["evidence_refs"][0]["sha256"] = sha(raw)
    helper().refresh_signatures(data)
    result = assess(owner, data)
    assert result["counts"]["authenticated_typed_responses"] == 2
    assert result["response_results"][0]["response_artifact_ref"]["sha256"] == sha(raw)
    no_decision(result)


@pytest.mark.parametrize("field", ["review_id", "principal_id", "role", "issued_at_utc"])
def test_valid_response_body_must_match_the_signed_reviewer(owner, field):
    data = response_case(owner)
    response = deepcopy(data["responses"][0])
    replacements = {"review_id": "fixture:another-review", "principal_id": "fixture:another-person",
                    "role": "formal_review", "issued_at_utc": "2026-10-14T07:00:00Z"}
    response[field] = replacements[field]
    install_record(data, 0, record(owner, data, response))
    result = assess(owner, data)
    assert result["response_results"][0]["content_status"] == "rejected"
    assert result["counts"]["authenticated_typed_responses"] == 1
    no_decision(result)


def test_present_day_candidate_proposals_are_preserved_without_historical_attestation(owner):
    data = response_case(owner)
    for index, response in enumerate(data["responses"]):
        response["occurrence_proposal"] = {
            "status": "proposed_present_day",
            "candidate_occurrence_cid": data["joined"]["rows"][0]["candidates"][index]["source_occurrence"]["record_cid"],
            "rationale": "Fictional present-day proposal; no historical selection evidence.",
            "evidence_refs": deepcopy(response["answers"][0]["evidence_refs"]),
        }
        install_record(data, index, record(owner, data, response))
    result = assess(owner, data)
    assert result["counts"]["authenticated_typed_responses"] == 2
    assert result["counts"]["differing_occurrence_proposals"] > 0
    assert len(result["occurrence_proposals"]) == 2
    assert data["joined"]["rows"][0]["selected_occurrence"] is None
    assert result["original_producer_occurrence_attested"] is False
    no_decision(result)


@pytest.mark.parametrize("damage", ["unbound", "missing_evidence", "historical_status", "unresolved_with_cid"])
def test_occurrence_proposals_cannot_escape_candidate_or_present_day_scope(owner, damage):
    data = helper().signed_case(source_owner)
    response = declaration(data)
    proposal = response["occurrence_proposal"]
    proposal.update(status="proposed_present_day",
                    candidate_occurrence_cid=data["joined"]["rows"][0]["candidates"][0]["source_occurrence"]["record_cid"],
                    evidence_refs=deepcopy(response["answers"][0]["evidence_refs"]))
    if damage == "unbound":
        proposal["candidate_occurrence_cid"] = data["preparation"]["requests"][0]["record_cid"]
    elif damage == "missing_evidence":
        proposal["evidence_refs"] = []
    elif damage == "historical_status":
        proposal["status"] = "original_producer_occurrence_attested"
    else:
        proposal["status"] = "unresolved"
    with pytest.raises(ValueError):
        record(owner, data, response)


@pytest.mark.parametrize("change", ["complete_context", "source_revision"])
def test_response_cannot_be_rebound_to_changed_source(owner, change):
    data = helper().signed_case(source_owner)
    response = declaration(data)
    body = record(owner, data, response)
    args = data["arguments"]
    if change == "complete_context":
        args["source_sections"][0]["text"] += " Different fictional surrounding context."
        new_hash = sha(args["source_sections"][0]["text"].encode())
        args["source_sections"][0]["text_sha256"] = new_hash
        args["expected_source_sections"][0]["text_sha256"] = new_hash
    else:
        args["source_sections"][0]["revision"] = "c" * 40
        args["expected_source_sections"][0]["revision"] = "c" * 40
        receipt = json.loads(args["producer_receipt_bytes"])
        receipt["rows"][0]["source_parent"]["revision"] = "c" * 40
        args["producer_receipt_bytes"] = wire(receipt)
        args["expected_producer_receipt_sha256"] = sha(wire(receipt))
        paired = json.loads(args["paired_row_bytes"][0])
        paired["source_target_artifact_sha256"] = sha(wire(receipt))
        args["paired_row_bytes"][0] = wire(paired)
        args["expected_population"][0]["row_sha256"] = sha(wire(paired))
    join_inputs = {key: value for key, value in args.items()
                   if key not in {"join_bytes", "paired_row_bytes", "expected_join_sha256"}}
    joined = joins.build_legacy_source_join(args["paired_row_bytes"], **join_inputs)
    args["join_bytes"] = wire(joined)
    args["expected_join_sha256"] = sha(args["join_bytes"])
    data["preparation"] = source_owner.prepare_legacy_source_review_requests(**args)
    # Supply a valid new-domain answer population; refusal must also cover the
    # old response record's source binding, not only outdated question IDs.
    for answer, question in zip(response["answers"],
                                [item for item in data["preparation"]["requests"][0]["review_questions"]
                                 if item["assessment_scope"] == "source_context_evidence_declaration"],
                                strict=True):
        answer["slot_id"] = question["slot_id"]
    with pytest.raises(ValueError):
        owner.validate_legacy_source_response(
            body, data["preparation"], response, **record_arguments(data))


def test_response_record_cannot_move_to_another_paired_observation(owner):
    data = helper().signed_case(source_owner)
    args = data["arguments"]
    second = json.loads(args["paired_row_bytes"][0])
    second["observation_id"] = "fictional-second-paired-observation"
    raw = wire(second)
    args["paired_row_bytes"].append(raw)
    pin = deepcopy(args["expected_population"][0])
    pin["row_sha256"] = sha(raw)
    args["expected_population"].append(pin)
    join_inputs = {key: value for key, value in args.items()
                   if key not in {"join_bytes", "paired_row_bytes", "expected_join_sha256"}}
    joined = joins.build_legacy_source_join(args["paired_row_bytes"], **join_inputs)
    args["join_bytes"] = wire(joined)
    args["expected_join_sha256"] = sha(args["join_bytes"])
    data["preparation"] = source_owner.prepare_legacy_source_review_requests(**args)
    response = declaration(data)
    body = record(owner, data, response)
    active = [item for item in data["preparation"]["requests"][1]["review_questions"]
              if item["assessment_scope"] == "source_context_evidence_declaration"]
    for answer, question in zip(response["answers"], active, strict=True):
        answer["slot_id"] = question["slot_id"]
    with pytest.raises(ValueError):
        owner.validate_legacy_source_response(
            body, data["preparation"], response,
            **{**record_arguments(data), "request_ordinal": 1})


def test_resealed_or_modified_assessment_requires_exact_regeneration(owner):
    data = response_case(owner)
    result = assess(owner, data)
    result["counts"]["applied_source_decisions"] = 1
    with pytest.raises(ValueError):
        owner.validate_legacy_source_responses(
            result, data["preparation"], data["registry"], data["policy"], data["reviews"],
            **assessment_arguments(data))


@pytest.mark.parametrize(("field", "replacement"), [("admitted", 0), ("request_ordinal", False)])
def test_signed_response_numeric_boolean_aliases_cannot_retain_a_record_cid(owner, field, replacement):
    data = response_case(owner)
    body = deepcopy(data["response_records"][0])
    original_cid = body["record_cid"]
    body[field] = replacement
    assert body["record_cid"] == original_cid
    # Rebind and sign the changed raw bytes. Valid outer custody must not hide
    # JSON types that compare equal under Python's 0 == False semantics.
    install_record(data, 0, body)
    result = assess(owner, data)
    assert result["raw_source_assessment"]["authenticated_evidence_count"] == 2
    assert result["response_results"][0]["content_status"] == "rejected"
    assert result["response_results"][0]["content_blockers"]
    assert result["counts"]["authenticated_typed_responses"] == 1
    no_decision(result)


@pytest.mark.parametrize("flag", ["admitted", "source_semantics_verified"])
def test_response_validation_refuses_numeric_aliases_for_false_flags(owner, flag):
    data = helper().signed_case(source_owner)
    response = declaration(data)
    body = record(owner, data, response)
    assert body[flag] is False
    body[flag] = 0
    with pytest.raises(ValueError):
        owner.validate_legacy_source_response(
            body, data["preparation"], response, **record_arguments(data))


def test_assessment_validation_refuses_numeric_alias_for_false_authority(owner):
    data = response_case(owner)
    result = assess(owner, data)
    assert result["admitted"] is False
    result["admitted"] = 0
    with pytest.raises(ValueError):
        owner.validate_legacy_source_responses(
            result, data["preparation"], data["registry"], data["policy"], data["reviews"],
            **assessment_arguments(data))


def test_preparation_numeric_boolean_alias_is_refused_before_authentication(owner, monkeypatch):
    data = response_case(owner)
    request = data["preparation"]["requests"][0]
    original_cid = request["record_cid"]
    assert request["admitted"] is False
    request["admitted"] = 0
    assert request["record_cid"] == original_cid

    def forbidden_assessment(*args, **kwargs):
        raise AssertionError("A type-changed preparation must not reach signature assessment.")

    monkeypatch.setattr(trust_owner, "_assess_reviews", forbidden_assessment)
    with pytest.raises(ValueError):
        assess(owner, data)
