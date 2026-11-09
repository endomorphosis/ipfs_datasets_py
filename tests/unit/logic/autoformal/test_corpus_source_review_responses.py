"""Typed source review fixtures authenticate custody and preserve disagreement."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_source_review as source_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_source_review_for_typed_response_tests",
        Path(__file__).with_name("test_corpus_source_review.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ref(record):
    return {
        "record_cid": record["record_cid"],
        "sha256": sha(canonical_dag_json_bytes(record)),
        "schema": record["schema"],
    }


def reseal(record):
    return contracts.seal_record(
        {
            key: deepcopy(value)
            for key, value in record.items()
            if key not in {"record_cid", "cid_scope"}
        }
    )


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses

    return corpus_source_review_responses


@pytest.fixture(scope="module")
def fixture_data(tmp_path_factory):
    """Real signatures over small authored sources; no actual reviewers or law gold."""
    data = helper().signed_case(
        source_owner, tmp_path_factory.mktemp("typed-source-response-inputs")
    )
    return data


def refuse_replay(*_args, **_kwargs):
    pytest.fail("Untrusted boundary input reached complete source replay or authentication")


def clone_case(data):
    # Cryptography private keys are immutable fixture actors, not caller data.
    return {key: value[:] if key == "signers" else deepcopy(value) for key, value in data.items()}


def response_input(request, review, evidence, *, disposition="evidence_declared", exposure=None):
    evidence_ref = {
        "artifact_id": "fixture:source-declaration",
        "sha256": sha(evidence["fixture:source-declaration"]),
    }
    finding_status = "unavailable" if disposition == "unresolved" else disposition
    return {
        "review_id": review["review_id"],
        "principal_id": review["principal_id"],
        "role": review["role"],
        "issued_at_utc": review["issued_at_utc"],
        "process_declaration": {
            key: [deepcopy(evidence_ref)]
            for key in (
                "identity_evidence_refs",
                "independence_evidence_refs",
                "process_evidence_refs",
            )
        },
        "exposure_declaration": deepcopy(exposure)
        if exposure is not None
        else {
            "candidate_interpretations_exposed": None,
            "organizer_source_metadata_exposed": True,
            "other_exposure": None,
        },
        "answers": [
            {
                **{key: question[key] for key in ("slot_id", "category", "kind")},
                "disposition": disposition,
                "finding": {
                    "status": finding_status,
                    "statement": "Authored fixture declaration; no law or human identity is verified.",
                },
                "rationale": "Fixture evidence establishes only byte custody, not statutory or semantic authority.",
                "evidence_refs": [] if disposition == "unresolved" else [deepcopy(evidence_ref)],
            }
            for question in request["review_questions"]
            if question["assessment_scope"] == "source_context_evidence_declaration"
        ],
    }


def author_pins(data, ordinal=0):
    return {
        "expected_request_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["requests"][ordinal])
        ),
        "expected_subject_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["subjects"][ordinal])
        ),
        "expected_preparation_manifest_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["manifest"])
        ),
    }


def author(owner, data, value, ordinal=0, **options):
    return owner.record_source_review_response(
        data["preparation"]["requests"][ordinal],
        data["preparation"]["subjects"][ordinal],
        value,
        **author_pins(data, ordinal),
        **options,
    )


def signed_typed_case(
    owner,
    fixture_data,
    *,
    disposition="evidence_declared",
    trust_mode="synthetic_fixture",
    exposure=None,
):
    data = clone_case(fixture_data)
    data["registry"]["mode"] = data["policy"]["mode"] = trust_mode
    helper().refresh_signatures(data)
    data["response_bindings"], data["response_inputs"] = [], []
    for ordinal, (request, group) in enumerate(
        zip(data["preparation"]["requests"], data["groups"], strict=True)
    ):
        entries, inputs = [], []
        for index, review in enumerate(group["reviews"]):
            value = response_input(
                request,
                review,
                group["evidence_artifacts"],
                disposition=disposition,
                exposure=exposure,
            )
            record = author(owner, data, value, ordinal)
            raw = canonical_dag_json_bytes(record)
            artifact = f"fixture:typed-response:{ordinal}:{index}"
            group["evidence_artifacts"][artifact] = raw
            entries.append(
                {"review_id": review["review_id"], "artifact_id": artifact, "raw_sha256": sha(raw)}
            )
            inputs.append(value)
            review["context_closure"] = {
                "status": "open" if disposition == "unresolved" else "declared_complete",
                "unresolved": request["context_slot_ids"][:] if disposition == "unresolved" else [],
                "obligations": [
                    {
                        "slot_id": answer["slot_id"],
                        "disposition": {
                            "unresolved": "open",
                            "evidence_declared": "resolved_by_evidence",
                            "not_applicable": "not_applicable",
                        }[answer["disposition"]],
                        "evidence_refs": [{"artifact_id": artifact, "sha256": sha(raw)}],
                    }
                    for answer in record["answers"]
                ],
            }
        data["response_bindings"].append(
            {"request_cid": request["record_cid"], "responses": entries}
        )
        data["response_inputs"].append(inputs)
    helper().refresh_signatures(data)
    return data


def assessment_arguments(data, **options):
    group_pins = options.pop("expected_review_group_pins", None)
    return {
        **data["data"]["arguments"],
        "expected_preparation_manifest_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["manifest"])
        ),
        "expected_registry_sha256": sha(canonical(data["registry"])),
        "expected_policy_sha256": sha(canonical(data["policy"])),
        "expected_review_group_pins": helper().group_pins(data["groups"])
        if group_pins is None
        else group_pins,
        "at_time_utc": data["at_time_utc"],
        "response_bindings": data["response_bindings"],
        "expected_response_bindings_sha256": sha(canonical(data["response_bindings"])),
        **options,
    }


def assess(owner, data, **options):
    return owner.assess_source_review_responses(
        data["preparation"],
        data["registry"],
        data["policy"],
        data["groups"],
        **assessment_arguments(data, **options),
    )


def validate(owner, report, data, **options):
    return owner.validate_source_review_responses(
        report,
        data["preparation"],
        data["registry"],
        data["policy"],
        data["groups"],
        **assessment_arguments(data, **options),
    )


def set_raw_response(data, raw, *, ordinal=0, index=0, resign=True):
    entry = data["response_bindings"][ordinal]["responses"][index]
    group = data["groups"][ordinal]
    group["evidence_artifacts"][entry["artifact_id"]] = raw
    entry["raw_sha256"] = sha(raw)
    if resign:
        for obligation in group["reviews"][index]["context_closure"]["obligations"]:
            obligation["evidence_refs"] = [
                {"artifact_id": entry["artifact_id"], "sha256": entry["raw_sha256"]}
            ]
        helper().refresh_signatures(data)


def mutate_response(data, mutate, *, ordinal=0, index=0, resign=True):
    entry = data["response_bindings"][ordinal]["responses"][index]
    record = json.loads(data["groups"][ordinal]["evidence_artifacts"][entry["artifact_id"]])
    mutate(record)
    set_raw_response(
        data, canonical_dag_json_bytes(reseal(record)), ordinal=ordinal, index=index, resign=resign
    )


def all_records(report):
    for component, values in report.items():
        yield from [values] if component == "manifest" else values


def assert_no_authority(owner, report):
    for record in all_records(report):
        for field in owner.FALSE_FLAGS:
            assert record[field] is False
        assert record["view"] == "candidate"
        assert record["selected_occurrence"] is record["governing_source_binding"] is None
        assert len(canonical_dag_json_bytes(record)) <= contracts.MAX_RECORD_BYTES
        assert reseal(record) == record
    assert report["manifest"]["counts"]["accepted_adjudications"] == 0
    assert report["manifest"]["counts"]["applied_source_decisions"] == 0
    for row in report["adjudication_requests"]:
        assert row["decision"] is row["rationale"] is None
        assert row["evidence_refs"] == []
        assert row["adjudicator_declaration"] == {
            "principal_id": None,
            "role": None,
            "issued_at_utc": None,
        }
        assert row["status"] == "pending_adjudication_not_a_decision"
        assert "separate_adjudication_and_decision_authority_required" in row["issues"]


@pytest.fixture(scope="module")
def baseline_data(fixture_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses

    return signed_typed_case(corpus_source_review_responses, fixture_data)


@pytest.fixture(scope="module")
def baseline_report(baseline_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses

    return assess(corpus_source_review_responses, baseline_data)


def test_author_records_exact_nine_answers_and_seven_deferred_slots_without_authentication(
    owner, baseline_data
):
    data = baseline_data
    request, subject = data["preparation"]["requests"][0], data["preparation"]["subjects"][0]
    value = data["response_inputs"][0][0]
    result = author(owner, data, value)
    assert result["request_ref"] == ref(request)
    assert result["subject_ref"] == ref(subject)
    assert result["dependency_manifest_sha256"] == subject["dependency_manifest_sha256"]
    assert result["questions_sha256"] == request["questions_sha256"]
    assert result["source_binding_sha256"] == request["source_binding_sha256"]
    assert (
        result["preparation_manifest_sha256"]
        == author_pins(data)["expected_preparation_manifest_sha256"]
    )
    assert [row["slot_id"] for row in result["answers"]] == request["context_slot_ids"]
    assert len(result["answers"]) == 9 and len(result["deferred_review_slot_ids"]) == 7
    assert result["deferred_review_slot_ids"] == request["deferred_review_slot_ids"]
    assert result["status"] == "declared_unauthenticated_source_response"
    assert all(result[field] is False for field in owner.FALSE_FLAGS)
    assert (
        owner.validate_source_review_response(result, request, subject, value, **author_pins(data))
        == result
    )


def test_complete_groups_retain_original_authentication_and_equal_typed_answers_without_clearing_raw_disagreement(
    owner, baseline_data, baseline_report
):
    data, report = baseline_data, baseline_report
    raw = source_owner.assess_source_review_groups(
        data["preparation"],
        data["registry"],
        data["policy"],
        data["groups"],
        **helper().assess_arguments(data),
    )
    assert set(report) == set(owner.COMPONENTS)
    assert len(report["records"]) == len(data["preparation"]["requests"])
    assert [row["raw_source_assessment_record"] for row in report["records"]] == raw["records"]
    assert report["manifest"]["raw_source_assessment_ref"] == ref(raw["manifest"])
    first = report["records"][0]["raw_source_assessment_record"]["assessment"]
    assert first["authenticated_evidence_count"] == 2
    assert "authenticated_context_declarations_disagree" in first["blockers"]
    assert "production_trust_registry_unavailable" in first["blockers"]
    assert first["review_prerequisites_satisfied_under_selected_trust"] is False
    assert all(
        row["content_status"] == "valid_declared_content" and row["authenticated_typed_content"]
        for row in report["response_results"]
    )
    assert all(row["typed_answer_declarations_complete"] for row in report["response_results"])
    assert len(report["answer_variants"]) == 9
    assert all(len(row["respondents"]) == 2 for row in report["answer_variants"])
    assert all(
        row["exact_answer_comparison"] == "one_exact_answer_variant"
        for row in report["adjudication_requests"][:9]
    )
    assert all(
        row["exact_answer_comparison"] == "no_authenticated_answers"
        for row in report["adjudication_requests"][9:]
    )
    assert_no_authority(owner, report)
    assert validate(owner, report, data) == report


def test_blank_groups_never_create_trust_reviews_or_typed_answers(owner, baseline_data):
    data = clone_case(baseline_data)
    data["registry"]["mode"] = data["policy"]["mode"] = "unavailable"
    data["registry"]["keys"] = []
    data["policy"]["registry_sha256"] = sha(canonical(data["registry"]))
    for group, binding in zip(data["groups"], data["response_bindings"], strict=True):
        group["reviews"], group["evidence_artifacts"], binding["responses"] = [], {}, []
    report = assess(owner, data)
    assert report["response_results"] == report["answer_variants"] == []
    assert (
        report["manifest"]["counts"]["responses"]
        == report["manifest"]["counts"]["authenticated_typed_responses"]
        == 0
    )
    assert len(report["adjudication_requests"]) == 9 * len(data["preparation"]["requests"])
    assert all(
        "trust_registry_unavailable"
        in row["raw_source_assessment_record"]["assessment"]["blockers"]
        for row in report["records"]
    )
    assert all(
        "no_authenticated_typed_answer" in row["issues"] for row in report["adjudication_requests"]
    )
    assert_no_authority(owner, report)


@pytest.mark.parametrize("disposition", ["evidence_declared", "not_applicable", "unresolved"])
def test_three_typed_dispositions_map_exactly_to_signed_source_obligations(
    owner, fixture_data, disposition
):
    data = signed_typed_case(owner, fixture_data, disposition=disposition)
    report = assess(owner, data)
    assert all(
        row["content_status"] == "valid_declared_content" and row["authenticated_typed_content"]
        for row in report["response_results"]
    )
    assert all(
        row["typed_answer_declarations_complete"] is (disposition != "unresolved")
        for row in report["response_results"]
    )
    assert all(row["answer"]["disposition"] == disposition for row in report["answer_variants"])
    assert report["manifest"]["counts"]["unresolved_answer_slots"] == (
        9 if disposition == "unresolved" else 0
    )
    assert_no_authority(owner, report)


def test_conservatively_open_complete_signed_claim_remains_open_and_never_gets_repaired(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    for review in data["groups"][0]["reviews"]:
        review["context_closure"]["status"] = "open"
    helper().refresh_signatures(data)
    report = assess(owner, data)
    assert all(
        row["content_status"] == "valid_declared_content"
        and row["typed_answer_declarations_complete"]
        for row in report["response_results"]
    )
    assessment = report["records"][0]["raw_source_assessment_record"]["assessment"]
    assert all("context_declared_open" in row["context_blockers"] for row in assessment["reviews"])
    assert "authenticated_complete_context_declarations_missing" in assessment["blockers"]
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage",
    ["resolved_unknown", "complete_unknown", "missing_unresolved_slots", "wrong_unresolved_order"],
)
def test_valid_signature_over_unknown_content_cannot_supply_complete_source_evidence(
    owner, fixture_data, damage
):
    data = signed_typed_case(owner, fixture_data, disposition="unresolved")
    review = data["groups"][0]["reviews"][0]
    if damage == "resolved_unknown":
        for obligation in review["context_closure"]["obligations"]:
            obligation["disposition"] = "resolved_by_evidence"
        review["context_closure"]["status"], review["context_closure"]["unresolved"] = (
            "declared_complete",
            [],
        )
    elif damage == "complete_unknown":
        review["context_closure"]["status"], review["context_closure"]["unresolved"] = (
            "declared_complete",
            [],
        )
    elif damage == "missing_unresolved_slots":
        review["context_closure"]["unresolved"] = []
    else:
        review["context_closure"]["unresolved"].reverse()
    helper().refresh_signatures(data)
    report = assess(owner, data)
    assert (
        report["records"][0]["raw_source_assessment_record"]["assessment"]["reviews"][0]["status"]
        == "authenticated"
    )
    assert report["response_results"][0]["content_status"] == "rejected"
    assert report["response_results"][0]["authenticated_typed_content"] is False
    assert report["response_results"][0]["response_record_ref"] is None
    assert all(
        row["respondents"][0]["review_id"] == data["groups"][0]["reviews"][1]["review_id"]
        for row in report["answer_variants"]
    )
    assert_no_authority(owner, report)


@pytest.mark.parametrize("changed", ["finding", "rationale", "evidence_order"])
def test_distinct_exact_answer_contents_keep_all_variants_and_declared_respondents(
    owner, baseline_data, changed
):
    data = clone_case(baseline_data)
    if changed == "evidence_order":
        data["groups"][0]["evidence_artifacts"]["fixture:second-source"] = (
            b"Second authored fixture evidence body."
        )
        additional = {
            "artifact_id": "fixture:second-source",
            "sha256": sha(b"Second authored fixture evidence body."),
        }
        mutate_response(
            data,
            lambda record: record["answers"][0]["evidence_refs"].append(deepcopy(additional)),
            index=0,
        )
        mutate_response(
            data,
            lambda record: record["answers"][0]["evidence_refs"].insert(0, deepcopy(additional)),
            index=1,
        )
    elif changed == "finding":
        mutate_response(
            data,
            lambda record: record["answers"][0]["finding"].update(
                statement="Different source statement retained, not resolved."
            ),
            index=1,
        )
    else:
        mutate_response(
            data,
            lambda record: record["answers"][0].update(
                rationale="A different fixture rationale is a distinct exact content variant."
            ),
            index=1,
        )
    report = assess(owner, data)
    variants = [
        row
        for row in report["answer_variants"]
        if row["slot_id"] == data["preparation"]["requests"][0]["context_slot_ids"][0]
    ]
    assert len(variants) == 2
    assert {row["respondents"][0]["principal_id"] for row in variants} == {
        review["principal_id"] for review in data["groups"][0]["reviews"]
    }
    adjudication = report["adjudication_requests"][0]
    assert adjudication["exact_answer_comparison"] == "different_exact_answer_variants"
    assert "distinct_exact_answer_variants" in adjudication["issues"]
    assert {row["record_cid"] for row in adjudication["answer_variant_refs"]} == {
        row["record_cid"] for row in variants
    }
    assert report["manifest"]["counts"]["different_answer_slots"] == 1
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "exposure",
    [
        {
            "candidate_interpretations_exposed": None,
            "organizer_source_metadata_exposed": None,
            "other_exposure": None,
        },
        {
            "candidate_interpretations_exposed": True,
            "organizer_source_metadata_exposed": True,
            "other_exposure": "Explicit prior fixture exposure.",
        },
        {
            "candidate_interpretations_exposed": False,
            "organizer_source_metadata_exposed": False,
            "other_exposure": "Declared fixture source-first reading.",
        },
    ],
)
def test_explicit_exposure_is_retained_without_inferred_unexposure_or_changed_signature_authenticity(
    owner, fixture_data, exposure
):
    data = signed_typed_case(owner, fixture_data, exposure=exposure)
    report = assess(owner, data)
    assert all(row["authenticated_typed_content"] for row in report["response_results"])
    assert all(
        row["exposure_status"]
        == ("unknown" if any(value is None for value in exposure.values()) else "declared")
        for row in report["response_results"]
    )
    for entry in data["response_bindings"][0]["responses"]:
        record = json.loads(data["groups"][0]["evidence_artifacts"][entry["artifact_id"]])
        assert record["exposure_declaration"] == exposure
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_input",
        "missing_input",
        "role",
        "principal",
        "time",
        "exposure_missing",
        "exposure_extra",
        "exposure_bool_alias",
        "exposure_empty_text",
        "process_missing",
        "process_extra",
        "process_oversized",
        "process_duplicate",
        "process_bad_sha",
        "answer_missing",
        "answer_extra",
        "answer_order",
        "answer_duplicate",
        "answer_unknown_field",
        "slot",
        "category",
        "kind",
        "finding_unknown",
        "finding_unknown_field",
        "finding_missing",
        "finding_empty",
        "finding_disposition",
        "rationale_empty",
        "answer_no_evidence",
        "answer_duplicate_evidence",
        "answer_bad_evidence_sha",
        "answer_extra_evidence",
        "answer_deferred",
    ],
)
def test_closed_authoring_input_preserves_exact_question_exposure_and_evidence_declarations(
    owner, baseline_data, damage
):
    data = baseline_data
    value = deepcopy(data["response_inputs"][0][0])
    if damage == "unknown_input":
        value["decision"] = "accept"
    elif damage == "missing_input":
        del value["review_id"]
    elif damage == "role":
        value["role"] = "adjudicator"
    elif damage == "principal":
        value["principal_id"] = "principal with spaces"
    elif damage == "time":
        value["issued_at_utc"] = "2026-10-14"
    elif damage == "exposure_missing":
        del value["exposure_declaration"]["other_exposure"]
    elif damage == "exposure_extra":
        value["exposure_declaration"]["source_first"] = True
    elif damage == "exposure_bool_alias":
        value["exposure_declaration"]["candidate_interpretations_exposed"] = 0
    elif damage == "exposure_empty_text":
        value["exposure_declaration"]["other_exposure"] = " "
    elif damage == "process_missing":
        del value["process_declaration"]["identity_evidence_refs"]
    elif damage == "process_extra":
        value["process_declaration"]["human_identity_verified"] = True
    elif damage == "process_oversized":
        value["process_declaration"]["identity_evidence_refs"] *= 9
    elif damage == "process_duplicate":
        value["process_declaration"]["identity_evidence_refs"] *= 2
    elif damage == "process_bad_sha":
        value["process_declaration"]["identity_evidence_refs"][0]["sha256"] = "bad"
    elif damage == "answer_missing":
        value["answers"].pop()
    elif damage == "answer_extra":
        value["answers"].append(deepcopy(value["answers"][0]))
    elif damage == "answer_order":
        value["answers"].reverse()
    elif damage == "answer_duplicate":
        value["answers"][1] = deepcopy(value["answers"][0])
    elif damage == "answer_unknown_field":
        value["answers"][0]["resolved"] = True
    elif damage == "slot":
        value["answers"][0]["slot_id"] = "fixture:unknown-slot"
    elif damage == "category":
        value["answers"][0]["category"] = "semantic"
    elif damage == "kind":
        value["answers"][0]["kind"] = "Lean4_kernel_check"
    elif damage == "finding_unknown":
        value["answers"][0]["finding"]["status"] = "unknown"
    elif damage == "finding_unknown_field":
        value["answers"][0]["finding"]["semantic_truth"] = True
    elif damage == "finding_missing":
        del value["answers"][0]["finding"]["statement"]
    elif damage == "finding_empty":
        value["answers"][0]["finding"]["statement"] = " "
    elif damage == "finding_disposition":
        value["answers"][0]["finding"]["status"] = "unavailable"
    elif damage == "rationale_empty":
        value["answers"][0]["rationale"] = " "
    elif damage == "answer_no_evidence":
        value["answers"][0]["evidence_refs"] = []
    elif damage == "answer_duplicate_evidence":
        value["answers"][0]["evidence_refs"] *= 2
    elif damage == "answer_bad_evidence_sha":
        value["answers"][0]["evidence_refs"][0]["sha256"] = True
    elif damage == "answer_extra_evidence":
        value["answers"][0]["evidence_refs"][0]["trusted"] = True
    else:
        value["answers"][0]["slot_id"] = data["preparation"]["requests"][0][
            "deferred_review_slot_ids"
        ][0]
    with pytest.raises(ValueError):
        author(owner, data, value)


@pytest.mark.parametrize("damage", ["cycle", "nan", "infinity", "callback", "oversized"])
def test_nonfinite_cyclic_and_oversized_untrusted_declarations_are_refused(
    owner, baseline_data, damage
):
    value = deepcopy(baseline_data["response_inputs"][0][0])
    if damage == "cycle":
        value["answers"].append(value)
    elif damage == "nan":
        value["exposure_declaration"]["other_exposure"] = float("nan")
    elif damage == "infinity":
        value["exposure_declaration"]["other_exposure"] = float("inf")
    elif damage == "callback":
        value["answers"][0]["rationale"] = lambda: "authority"
    else:
        value["answers"][0]["rationale"] = "x" * (contracts.MAX_RECORD_BYTES + 1)
    with pytest.raises((ValueError, TypeError, RecursionError)):
        author(owner, baseline_data, value)


@pytest.mark.parametrize(
    "pin",
    ["expected_request_sha256", "expected_subject_sha256", "expected_preparation_manifest_sha256"],
)
def test_authoring_requires_independent_source_pin_format_and_exact_request_subject_bytes(
    owner, baseline_data, pin
):
    data = baseline_data
    pins = author_pins(data)
    pins[pin] = "0" * 64 if pin != "expected_preparation_manifest_sha256" else "not-a-hash"
    with pytest.raises(ValueError):
        owner.record_source_review_response(
            data["preparation"]["requests"][0],
            data["preparation"]["subjects"][0],
            data["response_inputs"][0][0],
            **pins,
        )


@pytest.mark.parametrize(
    "damage",
    [
        "subject_request",
        "subject_source",
        "subject_questions",
        "subject_slots",
        "subject_deferred",
        "questions",
        "scope_slots",
    ],
)
def test_resealed_author_request_and_subject_must_keep_their_exact_link_and_original_questions(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    request, subject = data["preparation"]["requests"][0], data["preparation"]["subjects"][0]
    if damage == "subject_request":
        subject["review_request_cid"] = data["preparation"]["requests"][1]["record_cid"]
    elif damage == "subject_source":
        subject["source_binding_sha256"] = "0" * 64
    elif damage == "subject_questions":
        subject["ast_sha256"] = "0" * 64
    elif damage == "subject_slots":
        subject["context_slot_ids"].reverse()
    elif damage == "subject_deferred":
        subject["deferred_review_slot_ids"].reverse()
    elif damage == "questions":
        request["review_questions"][0]["kind"] = "invented_source_question"
    else:
        request["context_slot_ids"].reverse()
    data["preparation"]["requests"][0] = reseal(request)
    data["preparation"]["subjects"][0] = reseal(subject)
    with pytest.raises(ValueError):
        author(owner, data, data["response_inputs"][0][0])


@pytest.mark.parametrize(
    "damage",
    [
        "review_id",
        "principal_id",
        "role",
        "issued_at_utc",
        "request_ref",
        "subject_ref",
        "preparation",
        "dependency",
        "source_binding",
        "questions",
        "deferred",
        "authority",
        "selection",
        "status",
    ],
)
def test_signed_resealed_response_cannot_move_to_another_review_or_source_binding(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)

    def change(record):
        if damage == "review_id":
            record["review_id"] = "fixture:different-review"
        elif damage == "principal_id":
            record["principal_id"] = "fixture:different-principal"
        elif damage == "role":
            record["role"] = "formal_review"
        elif damage == "issued_at_utc":
            record["issued_at_utc"] = "2026-10-14T08:01:00Z"
        elif damage == "request_ref":
            record["request_ref"] = ref(data["preparation"]["requests"][1])
        elif damage == "subject_ref":
            record["subject_ref"] = ref(data["preparation"]["subjects"][1])
        elif damage == "preparation":
            record["preparation_manifest_sha256"] = "0" * 64
        elif damage == "dependency":
            record["dependency_manifest_sha256"] = "0" * 64
        elif damage == "source_binding":
            record["source_binding_sha256"] = "0" * 64
        elif damage == "questions":
            record["questions_sha256"] = "0" * 64
        elif damage == "deferred":
            record["deferred_review_slot_ids"].reverse()
        elif damage == "authority":
            record["human_identity_verified"] = True
        elif damage == "selection":
            record["selected_occurrence"] = data["preparation"]["requests"][0][
                "source_occurrence_cid"
            ]
        else:
            record["status"] = "accepted_review"

    mutate_response(data, change)
    report = assess(owner, data)
    first = report["response_results"][0]
    assert first["signature_authentication_status"] == "authenticated"
    assert first["content_status"] == "rejected" and first["authenticated_typed_content"] is False
    assert first["response_record_ref"] is None and first["content_blockers"]
    assert len(report["answer_variants"]) == 9
    assert all(len(row["respondents"]) == 1 for row in report["answer_variants"])
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage", ["missing", "changed", "duplicate", "self", "process_missing", "process_changed"]
)
def test_nested_answer_and_reviewer_evidence_must_resolve_to_exact_independently_pinned_bytes(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    entry = data["response_bindings"][0]["responses"][0]

    def change(record):
        refs = (
            record["process_declaration"]["identity_evidence_refs"]
            if damage.startswith("process_")
            else record["answers"][0]["evidence_refs"]
        )
        if damage in ("missing", "process_missing"):
            refs[0]["artifact_id"] = "fixture:absent-evidence"
        elif damage in ("changed", "process_changed"):
            refs[0]["sha256"] = "0" * 64
        elif damage == "duplicate":
            refs.append(deepcopy(refs[0]))
        else:
            refs[0] = {"artifact_id": entry["artifact_id"], "sha256": entry["raw_sha256"]}

    mutate_response(data, change)
    report = assess(owner, data)
    assert report["response_results"][0]["signature_authentication_status"] == "authenticated"
    assert report["response_results"][0]["content_status"] == "rejected"
    assert report["response_results"][1]["content_status"] == "valid_declared_content"
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage",
    ["slot_order", "obligation_missing", "wrong_disposition", "additional_body", "wrong_body"],
)
def test_typed_answers_require_exact_signed_slot_disposition_and_single_response_reference(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    review = data["groups"][0]["reviews"][0]
    if damage == "slot_order":
        review["context_closure"]["obligations"].reverse()
    elif damage == "obligation_missing":
        review["context_closure"]["obligations"].pop()
    elif damage == "wrong_disposition":
        review["context_closure"]["obligations"][0]["disposition"] = "not_applicable"
    elif damage == "additional_body":
        review["context_closure"]["obligations"][0]["evidence_refs"].append(
            {
                "artifact_id": "fixture:source-declaration",
                "sha256": sha(
                    data["groups"][0]["evidence_artifacts"]["fixture:source-declaration"]
                ),
            }
        )
    else:
        review["context_closure"]["obligations"][0]["evidence_refs"] = deepcopy(
            data["groups"][0]["reviews"][1]["context_closure"]["obligations"][0]["evidence_refs"]
        )
    helper().refresh_signatures(data)
    report = assess(owner, data)
    assert report["response_results"][0]["signature_authentication_status"] == "authenticated"
    assert report["response_results"][0]["content_status"] == "rejected"
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage", ["duplicate_key", "nan", "broken_json", "unknown_schema", "unknown_field", "unsealed"]
)
def test_structurally_invalid_but_correctly_hashed_and_signed_response_bodies_are_retained_as_rejected(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    entry = data["response_bindings"][0]["responses"][0]
    raw = data["groups"][0]["evidence_artifacts"][entry["artifact_id"]]
    record = json.loads(raw)
    if damage == "duplicate_key":
        raw = b'{"review_id":"extra",' + raw[1:]
    elif damage == "nan":
        raw = raw.replace(b'"other_exposure":null', b'"other_exposure":NaN')
    elif damage == "broken_json":
        raw = raw[:-1]
    elif damage == "unknown_schema":
        record["schema"] = "legal-semantic-review/v1"
        raw = canonical_dag_json_bytes(reseal(record))
    elif damage == "unknown_field":
        record["adjudication"] = {"accepted": True}
        raw = canonical_dag_json_bytes(reseal(record))
    else:
        del record["record_cid"]
        raw = canonical(record)
    set_raw_response(data, raw)
    report = assess(owner, data)
    result = report["response_results"][0]
    assert result["content_status"] == "rejected" and result["response_record_ref"] is None
    assert result["signature_authentication_status"] == "authenticated"
    assert result["response_artifact_ref"] == {
        "artifact_id": entry["artifact_id"],
        "sha256": sha(raw),
    }
    assert result["content_blockers"]
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "signature",
        "signed_subject",
        "expired",
        "unauthorized_role",
        "scope",
        "revoked",
        "unknown_key",
    ],
)
def test_raw_signature_and_authorization_failures_stay_rejected_without_promoting_valid_typed_content(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    review = data["groups"][0]["reviews"][0]
    if damage == "signature":
        review["signature"] = ("B" if review["signature"][0] == "A" else "A") + review["signature"][
            1:
        ]
    elif damage == "signed_subject":
        review["subject"] = deepcopy(data["preparation"]["subjects"][1])
        helper().refresh_signatures(data)
    elif damage == "expired":
        data["at_time_utc"] = "2026-10-15T09:00:00Z"
    elif damage == "unauthorized_role":
        data["registry"]["keys"][0]["roles"] = ["formal_review"]
        helper().refresh_signatures(data)
    elif damage == "scope":
        data["registry"]["keys"][0]["scope_ids"] = ["fixture:different-scope"]
        helper().refresh_signatures(data)
    elif damage == "revoked":
        data["registry"]["keys"][0]["revoked_at_utc"] = "2026-10-14T07:00:00Z"
        helper().refresh_signatures(data)
    else:
        review["key_id"] = "fixture:unknown-key"
        helper().refresh_signatures(data)
    report = assess(owner, data)
    first = report["response_results"][0]
    assert first["content_status"] == "valid_declared_content"
    assert first["signature_authentication_status"] == "rejected"
    assert first["authenticated_typed_content"] is False
    assert report["records"][0]["raw_source_assessment_record"]["assessment"]["reviews"][0][
        "blockers"
    ]
    assert all(
        all(row["review_id"] != review["review_id"] for row in variant["respondents"])
        for variant in report["answer_variants"]
    )
    assert_no_authority(owner, report)


def test_two_keys_for_one_declared_principal_do_not_create_independence_or_adjudication(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    principal = data["registry"]["keys"][0]["principal_id"]
    data["registry"]["keys"][1]["principal_id"] = principal
    data["groups"][0]["reviews"][1]["principal_id"] = principal
    mutate_response(data, lambda record: record.update(principal_id=principal), index=1)
    helper().refresh_signatures(data)
    report = assess(owner, data)
    assert all(row["authenticated_typed_content"] for row in report["response_results"])
    assert (
        "distinct_authorized_review_principals_missing"
        in report["records"][0]["raw_source_assessment_record"]["assessment"]["blockers"]
    )
    assert all(
        "distinct_legal_and_formal_declared_principals_missing" in row["issues"]
        for row in report["adjudication_requests"][:9]
    )
    assert_no_authority(owner, report)


def test_external_shaped_synthetic_trust_does_not_remove_raw_closure_disagreement_or_verify_humans(
    owner, fixture_data
):
    data = signed_typed_case(owner, fixture_data, trust_mode="external_pinned_trust")
    report = assess(owner, data)
    assessment = report["records"][0]["raw_source_assessment_record"]["assessment"]
    assert assessment["trust_mode"] == "external_pinned_trust"
    assert "production_trust_registry_unavailable" not in assessment["blockers"]
    assert "authenticated_context_declarations_disagree" in assessment["blockers"]
    assert assessment["review_prerequisites_satisfied_under_selected_trust"] is False
    assert assessment["registry_identity_authenticated_by_this_api"] is False
    assert assessment["evaluation_clock_authenticated"] is False
    assert_no_authority(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "groups_subset",
        "groups_order",
        "groups_duplicate",
        "groups_unknown",
        "response_omitted",
        "response_order",
        "response_duplicate",
        "response_extra",
        "response_unknown",
        "request",
        "review",
        "raw_pin",
        "body_missing",
        "artifact_duplicate",
        "binding_root_pin",
    ],
)
def test_complete_independently_pinned_binding_population_refuses_subsets_aliases_and_stale_bytes_before_replay(
    owner, baseline_data, monkeypatch, damage
):
    data = clone_case(baseline_data)
    if damage == "groups_subset":
        data["response_bindings"].pop()
    elif damage == "groups_order":
        data["response_bindings"].reverse()
    elif damage == "groups_duplicate":
        data["response_bindings"][1] = deepcopy(data["response_bindings"][0])
    elif damage == "groups_unknown":
        data["response_bindings"][0]["adjudication"] = None
    elif damage == "response_omitted":
        data["response_bindings"][0]["responses"].pop()
    elif damage == "response_order":
        data["response_bindings"][0]["responses"].reverse()
    elif damage == "response_duplicate":
        data["response_bindings"][0]["responses"][1] = deepcopy(
            data["response_bindings"][0]["responses"][0]
        )
    elif damage == "response_extra":
        data["response_bindings"][0]["responses"].append(
            deepcopy(data["response_bindings"][0]["responses"][0])
        )
    elif damage == "response_unknown":
        data["response_bindings"][0]["responses"][0]["body"] = "unexpected"
    elif damage == "request":
        data["response_bindings"][0]["request_cid"] = data["preparation"]["requests"][1][
            "record_cid"
        ]
    elif damage == "review":
        data["response_bindings"][0]["responses"][0]["review_id"] = "fixture:different-review"
    elif damage == "raw_pin":
        data["response_bindings"][0]["responses"][0]["raw_sha256"] = "0" * 64
    elif damage == "body_missing":
        del data["groups"][0]["evidence_artifacts"][
            data["response_bindings"][0]["responses"][0]["artifact_id"]
        ]
    elif damage == "artifact_duplicate":
        data["response_bindings"][0]["responses"][1]["artifact_id"] = data["response_bindings"][0][
            "responses"
        ][0]["artifact_id"]
        data["response_bindings"][0]["responses"][1]["raw_sha256"] = data["response_bindings"][0][
            "responses"
        ][0]["raw_sha256"]
    monkeypatch.setattr(source_owner, "assess_source_review_groups", refuse_replay)
    with pytest.raises((ValueError, TypeError)):
        assess(
            owner,
            data,
            **(
                {"expected_response_bindings_sha256": "0" * 64}
                if damage == "binding_root_pin"
                else {}
            ),
        )


@pytest.mark.parametrize(
    "damage",
    [
        "groups_subset",
        "groups_order",
        "groups_duplicate",
        "too_many_reviews",
        "too_many_evidence",
        "bad_evidence_type",
        "group_pin",
        "group_body_hash",
    ],
)
def test_complete_source_group_custody_is_preflighted_before_source_authentication(
    owner, baseline_data, monkeypatch, damage
):
    data = clone_case(baseline_data)
    options = {}
    if damage == "groups_subset":
        data["groups"].pop()
    elif damage == "groups_order":
        data["groups"].reverse()
    elif damage == "groups_duplicate":
        data["groups"][1] = deepcopy(data["groups"][0])
    elif damage == "too_many_reviews":
        data["groups"][0]["reviews"] *= 17
    elif damage == "too_many_evidence":
        data["groups"][0]["evidence_artifacts"].update(
            {f"fixture:extra:{index}": b"x" for index in range(256)}
        )
    elif damage == "bad_evidence_type":
        data["groups"][0]["evidence_artifacts"]["fixture:source-declaration"] = "not exact bytes"
        options["expected_review_group_pins"] = helper().group_pins(baseline_data["groups"])
    elif damage == "group_pin":
        options["expected_review_group_pins"] = helper().group_pins(data["groups"])
        options["expected_review_group_pins"][0]["reviews_sha256"] = "0" * 64
    else:
        options["expected_review_group_pins"] = helper().group_pins(data["groups"])
        options["expected_review_group_pins"][0]["evidence_sha256s"][
            "fixture:source-declaration"
        ] = "0" * 64
    monkeypatch.setattr(source_owner, "assess_source_review_groups", refuse_replay)
    with pytest.raises((ValueError, TypeError)):
        assess(owner, data, **options)


@pytest.mark.parametrize(
    "limits",
    [
        {"unknown": 1},
        {"max_responses": True},
        {"max_groups": 0},
        {"max_response_bytes": 1048577},
        {"max_groups_per_page": 65},
    ],
)
def test_new_limits_are_closed_positive_integers_and_can_only_lower_profiles(
    owner, baseline_data, monkeypatch, limits
):
    monkeypatch.setattr(source_owner, "assess_source_review_groups", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, baseline_data, limits=limits)


@pytest.mark.parametrize(
    "cap",
    [
        "max_response_bytes",
        "max_binding_bytes",
        "max_responses",
        "max_groups",
        "max_adjudication_requests",
    ],
)
def test_known_complete_input_and_adjudication_caps_refuse_before_replay_without_selecting_a_prefix(
    owner, baseline_data, monkeypatch, cap
):
    limit = 1 if cap != "max_groups" else len(baseline_data["preparation"]["requests"]) - 1
    monkeypatch.setattr(source_owner, "assess_source_review_groups", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, baseline_data, limits={cap: limit})


def test_oversized_response_is_refused_before_hashing_that_body_or_importing_operation_owners(
    owner, baseline_data, monkeypatch
):
    data = clone_case(baseline_data)
    entry = data["response_bindings"][0]["responses"][0]
    oversized = b"x" * (contracts.MAX_RECORD_BYTES + 1)
    data["groups"][0]["evidence_artifacts"][entry["artifact_id"]] = oversized
    actual_sha = owner._sha

    def refuse_oversized_hash(raw):
        if raw is oversized:
            pytest.fail("oversized response reached hash operation")
        return actual_sha(raw)

    arguments = assessment_arguments(baseline_data)
    arguments["response_bindings"] = data["response_bindings"]
    arguments["expected_response_bindings_sha256"] = sha(canonical(data["response_bindings"]))
    monkeypatch.setattr(owner, "_sha", refuse_oversized_hash)
    monkeypatch.setattr(source_owner, "_owners", refuse_replay)
    with pytest.raises(ValueError):
        owner.assess_source_review_responses(
            data["preparation"], data["registry"], data["policy"], data["groups"], **arguments
        )


@pytest.mark.parametrize(
    "damage", ["request", "subject", "answer", "deferred", "authority", "exposure"]
)
def test_resealed_authored_response_requires_exact_independent_regeneration(
    owner, baseline_data, damage
):
    value = baseline_data["response_inputs"][0][0]
    record = author(owner, baseline_data, value)
    if damage == "request":
        record["request_ref"] = ref(baseline_data["preparation"]["requests"][1])
    elif damage == "subject":
        record["subject_ref"] = ref(baseline_data["preparation"]["subjects"][1])
    elif damage == "answer":
        record["answers"][0]["finding"]["statement"] += " Added selection."
    elif damage == "deferred":
        record["deferred_review_slot_ids"].reverse()
    elif damage == "authority":
        record["adjudication_accepted"] = True
    else:
        record["exposure_declaration"]["candidate_interpretations_exposed"] = False
    record = reseal(record)
    with pytest.raises(ValueError):
        owner.validate_source_review_response(
            record,
            baseline_data["preparation"]["requests"][0],
            baseline_data["preparation"]["subjects"][0],
            value,
            **author_pins(baseline_data),
        )


def test_exact_group_paging_keeps_original_order_and_every_pending_adjudication(
    owner, baseline_data
):
    report = assess(owner, baseline_data, limits={"max_groups_per_page": 1})
    assert len(report["pages"]) == len(baseline_data["preparation"]["requests"])
    entries = [row for page in report["pages"] for row in page["entries"]]
    assert [row["ordinal"] for row in entries] == list(range(len(entries)))
    assert [row["request_cid"] for row in entries] == [
        request["record_cid"] for request in baseline_data["preparation"]["requests"]
    ]
    assert [row["group_record_ref"] for row in entries] == [
        ref(record) for record in report["records"]
    ]
    assert len(report["adjudication_requests"]) == 9 * len(entries)
    assert_no_authority(owner, report)


def test_existing_source_authentication_replays_once_for_complete_population(
    owner, baseline_data, monkeypatch
):
    calls, original = [], source_owner.assess_source_review_groups

    def count(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(source_owner, "assess_source_review_groups", count)
    report = assess(owner, baseline_data)
    assert len(calls) == 1
    assert len(report["records"]) == len(baseline_data["preparation"]["requests"])


def test_producer_drift_during_real_source_signature_verification_refuses_all_new_results(
    owner, baseline_data, monkeypatch
):
    original, calls = owner._pins, []

    def changed():
        value = original()
        calls.append(value)
        if len(calls) > 1:
            value["fixture:changed-producer"] = "0" * 64
        return value

    monkeypatch.setattr(owner, "_pins", changed)
    with pytest.raises(ValueError):
        assess(owner, baseline_data)


def test_outputs_and_original_declarations_never_alias_caller_owned_containers(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    report = assess(owner, data)
    original_bytes = canonical(report)
    data["groups"][0]["reviews"][0]["interpretation"]["rationale"] = "Caller edit."
    data["response_bindings"][0]["responses"][0]["raw_sha256"] = "0" * 64
    data["preparation"]["requests"][0]["review_questions"][0]["kind"] = "caller_edit"
    assert canonical(report) == original_bytes
    value = deepcopy(baseline_data["response_inputs"][0][0])
    authored = author(owner, baseline_data, value)
    authored_bytes = canonical(authored)
    value["answers"][0]["finding"]["statement"] = "Another caller edit."
    assert canonical(authored) == authored_bytes


@pytest.mark.parametrize(
    "damage", ["later_group_budget", "unindexed_group_budget", "later_batch_budget"]
)
def test_all_group_body_sizes_pass_before_first_indexed_body_hash_or_operation_owner_import(
    owner, baseline_data, monkeypatch, damage
):
    data = clone_case(baseline_data)
    arguments = assessment_arguments(baseline_data)
    earlier = data["groups"][0]["evidence_artifacts"][
        data["response_bindings"][0]["responses"][0]["artifact_id"]
    ]
    if damage == "later_group_budget":
        data["groups"][1]["evidence_artifacts"]["fixture:later-oversized"] = b"x" * (
            8 * 1024**2 + 1
        )
    elif damage == "unindexed_group_budget":
        data["groups"][0]["evidence_artifacts"]["fixture:unindexed-oversized"] = b"x" * (
            8 * 1024**2 + 1
        )
    else:
        earlier_total = sum(len(raw) for raw in data["groups"][0]["evidence_artifacts"].values())
        data["groups"][1]["evidence_artifacts"]["fixture:later-budget"] = b"eightbyt"
        arguments["source_review_limits"] = {"max_batch_review_bytes": earlier_total + 7}
    actual_sha = owner._sha

    def require_complete_budget(raw):
        if raw is earlier:
            pytest.fail("earlier indexed response hashed before later complete body budget refusal")
        return actual_sha(raw)

    monkeypatch.setattr(owner, "_sha", require_complete_budget)
    monkeypatch.setattr(source_owner, "_owners", refuse_replay)
    with pytest.raises(ValueError):
        owner.assess_source_review_responses(
            data["preparation"], data["registry"], data["policy"], data["groups"], **arguments
        )


def rebind_report(report):
    """Repair shared references after tampering; full original regeneration still wins."""
    replacements = {}

    def replace(value):
        if type(value) is list:
            return [replace(item) for item in value]
        if type(value) is dict:
            result = {key: replace(item) for key, item in value.items()}
            original = (
                replacements.get(result.get("record_cid"))
                if type(result.get("record_cid")) is str
                else None
            )
            if original is not None and "sha256" in result:
                result.update(original)
            return result
        return value

    for component in (
        "response_results",
        "answer_variants",
        "adjudication_requests",
        "records",
        "pages",
    ):
        for index, record in enumerate(report[component]):
            old_cid = record["record_cid"]
            updated = reseal(replace(record))
            report[component][index] = updated
            replacements[old_cid] = ref(updated)
    report["manifest"] = reseal(replace(report["manifest"]))
    return report


@pytest.mark.parametrize(
    "damage",
    [
        "subset",
        "order",
        "duplicate",
        "answer",
        "respondent",
        "content_status",
        "raw_blocker",
        "deferred",
        "decision",
        "adjudicator",
        "issues",
        "authority",
        "count",
        "page_offset",
    ],
)
def test_resealed_and_rebound_assessment_cannot_erase_disagreement_apply_decisions_or_change_complete_population(
    owner, baseline_data, baseline_report, damage
):
    report = deepcopy(baseline_report)
    if damage == "subset":
        report["records"].pop()
    elif damage == "order":
        report["records"].reverse()
    elif damage == "duplicate":
        report["records"][1] = deepcopy(report["records"][0])
    elif damage == "answer":
        report["answer_variants"][0]["answer"]["rationale"] = "Substituted resolution."
    elif damage == "respondent":
        report["answer_variants"][0]["respondents"].pop()
    elif damage == "content_status":
        report["response_results"][0]["content_status"] = "accepted"
    elif damage == "raw_blocker":
        record = report["records"][0]["raw_source_assessment_record"]
        record["assessment"]["blockers"].remove("authenticated_context_declarations_disagree")
        record["assessment"]["assessment_sha256"] = trust_owner.digest(
            {
                key: value
                for key, value in record["assessment"].items()
                if key != "assessment_sha256"
            }
        )
        report["records"][0]["raw_source_assessment_record"] = reseal(record)
    elif damage == "deferred":
        report["records"][0]["deferred_questions_remain_pending"] = False
    elif damage == "decision":
        report["adjudication_requests"][0]["decision"] = "accept"
    elif damage == "adjudicator":
        report["adjudication_requests"][0]["adjudicator_declaration"]["principal_id"] = (
            "fixture:invented-adjudicator"
        )
    elif damage == "issues":
        report["adjudication_requests"][0]["issues"] = []
    elif damage == "authority":
        report["manifest"]["adjudication_accepted"] = True
    elif damage == "count":
        report["manifest"]["counts"]["accepted_adjudications"] = 1
    else:
        report["pages"][0]["first_group_ordinal"] = 1
    rebind_report(report)
    with pytest.raises(ValueError):
        validate(owner, report, baseline_data)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_component",
        "unknown_component",
        "too_many_records",
        "oversized_record",
        "nonfinite",
        "cycle",
    ],
)
def test_malformed_or_oversized_offered_output_is_refused_before_source_regeneration(
    owner, baseline_data, baseline_report, monkeypatch, damage
):
    report = deepcopy(baseline_report)
    if damage == "missing_component":
        del report["answer_variants"]
    elif damage == "unknown_component":
        report["adjudication_decisions"] = []
    elif damage == "too_many_records":
        report["records"] = [report["records"][0]] * (owner.DEFAULT_LIMITS["max_groups"] + 1)
    elif damage == "oversized_record":
        report["adjudication_requests"][0]["rationale"] = "x" * (contracts.MAX_RECORD_BYTES + 1)
    elif damage == "nonfinite":
        report["manifest"]["counts"]["responses"] = float("nan")
    else:
        report["records"][0]["response_result_refs"].append(report["records"][0])
    monkeypatch.setattr(owner, "assess_source_review_responses", refuse_replay)
    with pytest.raises((ValueError, TypeError, RecursionError)):
        validate(owner, report, baseline_data)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_variants": 1},
        {"max_pages": 1, "max_groups_per_page": 1},
        {"max_page_bytes": 1},
        {"max_collection_bytes": 1},
    ],
)
def test_complete_output_caps_refuse_instead_of_returning_a_selected_prefix(
    owner, baseline_data, limits
):
    with pytest.raises(ValueError):
        assess(owner, baseline_data, limits=limits)


def test_public_import_does_not_load_models_source_decoders_crypto_or_clocks():
    program = r"""
import sys
from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses as owner
assert owner.__all__ == ['record_source_review_response', 'validate_source_review_response', 'assess_source_review_responses', 'validate_source_review_responses']
for prefix in ('torch', 'transformers', 'pyarrow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.autoformal.legal_source_review_handoff' not in sys.modules
assert 'ipfs_datasets_py.logic.profile_g' not in sys.modules
print('inert typed source response import verified')
"""
    repo = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=repo,
        env=dict(
            os.environ,
            IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
            IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
            PYTHONPATH=str(repo),
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "inert typed source response import verified"


@pytest.mark.parametrize("finding", [None, [], {}, 1, True])
def test_untrusted_finding_status_types_refuse_as_contract_errors(owner, baseline_data, finding):
    value = deepcopy(baseline_data["response_inputs"][0][0])
    value["answers"][0]["finding"]["status"] = finding
    with pytest.raises(ValueError):
        author(owner, baseline_data, value)


def test_ambiguous_signed_open_answer_preserves_uncertainty_and_never_becomes_complete(
    owner, fixture_data
):
    data = signed_typed_case(owner, fixture_data, disposition="unresolved")
    for index in range(2):
        mutate_response(
            data,
            lambda record: record["answers"][0]["finding"].update(status="ambiguous"),
            index=index,
        )
    report = assess(owner, data)
    assert all(
        row["authenticated_typed_content"] and not row["typed_answer_declarations_complete"]
        for row in report["response_results"]
    )
    assert report["answer_variants"][0]["answer"]["finding"]["status"] == "ambiguous"
    assert "unresolved_typed_answer" in report["adjudication_requests"][0]["issues"]
    assert_no_authority(owner, report)


def test_raw_response_byte_pin_remains_distinct_from_full_canonical_record_pin(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    entry = data["response_bindings"][0]["responses"][0]
    record = json.loads(data["groups"][0]["evidence_artifacts"][entry["artifact_id"]])
    raw = (
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    assert sha(raw) != ref(record)["sha256"]
    set_raw_response(data, raw)
    report = assess(owner, data)
    result = report["response_results"][0]
    assert (
        result["content_status"] == "valid_declared_content"
        and result["authenticated_typed_content"]
    )
    assert result["response_artifact_ref"]["sha256"] == sha(raw)
    assert result["response_record_ref"] == ref(record)
    assert len(report["answer_variants"]) == 9
    assert_no_authority(owner, report)


def test_unreferenced_evidence_is_retained_as_custody_without_inventing_answer_or_review(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    raw = b"Extra authored custody body, not part of any typed answer."
    data["groups"][0]["evidence_artifacts"]["fixture:unreferenced-custody"] = raw
    report = assess(owner, data)
    assessment = report["records"][0]["raw_source_assessment_record"]["assessment"]
    assert assessment["evidence_artifact_sha256s"]["fixture:unreferenced-custody"] == sha(raw)
    assert len(report["response_results"]) == 2 and len(report["answer_variants"]) == 9
    assert all(
        all(
            ref["artifact_id"] != "fixture:unreferenced-custody"
            for ref in row["answer"]["evidence_refs"]
        )
        for row in report["answer_variants"]
    )
    assert_no_authority(owner, report)
