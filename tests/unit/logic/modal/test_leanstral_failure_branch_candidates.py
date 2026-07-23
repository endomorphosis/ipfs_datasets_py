"""Failure-subtree prompting and strict Leanstral candidate boundary tests."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.modal.leanstral import (
    LEANSTRAL_FAILURE_BRANCH_PROMPT_SCHEMA_VERSION,
    LEANSTRAL_FAILURE_BRANCH_RESPONSE_SCHEMA_VERSION,
    LegalIRLeanTask,
    build_leanstral_failure_branch_prompt,
    sanitize_leanstral_failure_branch_candidates,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    stable_mock_embedding,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _task() -> LegalIRLeanTask:
    text = "The agency shall provide notice unless emergency conditions exist."
    document = ModalIRDocument(
        document_id="failure-doc",
        source="us_code",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="deontic", system="KD", symbol="shall", label="shall"
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["agency", "notice"],
                    role="obligation",
                ),
                provenance=ModalIRProvenance(
                    source_id="failure-doc", start_char=0, end_char=len(text)
                ),
                exceptions=["emergency conditions exist"],
            )
        ],
    )
    sample = LegalSample(
        sample_id="failure-sample",
        source="us_code",
        title="5",
        section="552",
        citation="5 U.S.C. 552",
        text=text,
        normalized_text=text,
        embedding_model="mock:stable-sha256",
        embedding_vector=stable_mock_embedding(text),
        modal_ir=document,
    )
    return LegalIRLeanTask.from_sample(
        sample,
        autoencoder_guidance={
            "legal_ir_view_gap_distribution": {"deontic.ir": 0.4},
            "legal_ir_view_metrics": {"compiler_ir_cross_entropy_loss": 0.5},
            "ranked_guidance_features": [{"feature": "modal:deontic", "score": 1.0}],
            "synthesis_focus": ["legal_ir_multiview"],
        },
    )


def _contract_obligations(task: LegalIRLeanTask) -> list[dict]:
    return [
        dict(item)
        for item in task.proof_obligations
        if dict(item).get("metadata", {}).get("contract_id")
    ]


def _failures(task: LegalIRLeanTask) -> list[dict]:
    first, second = _contract_obligations(task)[:2]
    return [
        {
            "obligation_id": first["obligation_id"],
            "trusted": False,
            "proved": False,
            "failure_reason": "unproved",
        },
        {
            "obligation_id": second["obligation_id"],
            "trusted": True,
            "proved": True,
        },
    ]


def _response_from_prompt(task: LegalIRLeanTask, failures: list[dict]) -> dict:
    prompt = json.loads(build_leanstral_failure_branch_prompt(task, failures))
    response = prompt["response_shape"]
    branch = prompt["failed_obligation_subtrees"][0]
    response["candidates"][0]["candidate"] = branch["candidate_language"][
        "grounded_candidate_seed"
    ]
    response["candidates"][0]["confidence"] = 0.82
    return response


def test_prompt_contains_only_failed_subtree_and_registry_contract_id() -> None:
    task = _task()
    failures = _failures(task)

    first = json.loads(build_leanstral_failure_branch_prompt(task, failures))
    second = json.loads(build_leanstral_failure_branch_prompt(task, failures))

    assert first == second
    assert first["schema_version"] == LEANSTRAL_FAILURE_BRANCH_PROMPT_SCHEMA_VERSION
    assert len(first["failed_obligation_subtrees"]) == 1
    branch = first["failed_obligation_subtrees"][0]
    obligation = next(
        item for item in task.proof_obligations if item["obligation_id"] == branch["obligation_id"]
    )
    assert branch["contract_id"] == obligation["metadata"]["contract_id"]
    assert branch["premise_hints"] == obligation["premise_hints"]
    assert branch["candidate_language"]["allowed_predicate_heads"]
    assert branch["candidate_language"]["must_differ_from_obligation"] is True
    assert first["candidate_shape"]["candidate"] == branch[
        "candidate_language"
    ]["grounded_candidate_seed"]
    assert branch["candidate_language"]["minimum_distinct_grounding_symbols"] == 2
    assert task.source_span not in json.dumps(first)
    assert failures[1]["obligation_id"] not in json.dumps(first)


def test_strict_sanitizer_accepts_typed_failed_branch_candidate() -> None:
    task = _task()
    failures = _failures(task)
    response = _response_from_prompt(task, failures)

    result = sanitize_leanstral_failure_branch_candidates(
        task, json.dumps(response, sort_keys=True), failures
    )

    assert result.accepted is True
    assert result.reasons == ()
    assert result.candidates[0]["contract_id"] == response["candidates"][0]["contract_id"]
    assert result.candidates[0]["proof_obligation_ids"] == [
        response["candidates"][0]["proof_obligation_id"]
    ]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda candidate: candidate.update(proof_obligation_id="", proof_obligation_ids=[]), "missing_obligation_id"),
        (lambda candidate: candidate.update(contract_id="legal-ir-view/invented/v99"), "unknown_contract_id"),
        (lambda candidate: candidate.update(candidate="by simp [wellFormed]"), "freeform_proof_text"),
        (lambda candidate: candidate.update(candidate="Please try a stronger premise next time."), "untyped_logic"),
        (
            lambda candidate: candidate.update(
                candidate=(
                    f"{candidate['candidate']} and "
                    "invented_predicate(subject:s1)"
                )
            ),
            "unknown_candidate_predicate",
        ),
    ],
)
def test_strict_sanitizer_rejects_unsafe_candidate_mutations(mutation, reason: str) -> None:
    task = _task()
    failures = _failures(task)
    response = _response_from_prompt(task, failures)
    mutation(response["candidates"][0])

    result = sanitize_leanstral_failure_branch_candidates(task, response, failures)

    assert result.accepted is False
    assert result.candidates == ()
    assert reason in result.reasons


def test_strict_sanitizer_rejects_full_source_copy_even_when_metadata_claims_safe() -> None:
    task = _task()
    failures = _failures(task)
    response = _response_from_prompt(task, failures)
    response["candidates"][0]["candidate"] = task.source_span
    response["candidates"][0]["source_copy_rejected"] = False

    result = sanitize_leanstral_failure_branch_candidates(task, response, failures)

    assert result.accepted is False
    assert "source_copy" in result.reasons


def test_strict_sanitizer_rejects_obligation_restatement() -> None:
    task = _task()
    failures = _failures(task)
    prompt = json.loads(build_leanstral_failure_branch_prompt(task, failures))
    response = _response_from_prompt(task, failures)
    response["candidates"][0]["candidate"] = (
        prompt["failed_obligation_subtrees"][0]["statement"]
    )

    result = sanitize_leanstral_failure_branch_candidates(
        task,
        response,
        failures,
    )

    assert result.accepted is False
    assert "candidate_copies_obligation" in result.reasons


def test_strict_sanitizer_rejects_generic_shape_template() -> None:
    task = _task()
    failures = _failures(task)
    prompt = json.loads(build_leanstral_failure_branch_prompt(task, failures))
    response = _response_from_prompt(task, failures)
    response["candidates"][0]["candidate"] = prompt[
        "failed_obligation_subtrees"
    ][0]["candidate_language"]["shape_example"]

    result = sanitize_leanstral_failure_branch_candidates(
        task,
        response,
        failures,
    )

    assert result.accepted is False
    assert "candidate_copies_shape_template" in result.reasons
    assert "candidate_insufficient_grounding" in result.reasons


def test_strict_sanitizer_rejects_successful_obligation_and_markdown_wrapper() -> None:
    task = _task()
    failures = _failures(task)
    response = _response_from_prompt(task, failures)
    successful = _contract_obligations(task)[1]
    candidate = response["candidates"][0]
    candidate["proof_obligation_id"] = successful["obligation_id"]
    candidate["proof_obligation_ids"] = [successful["obligation_id"]]

    wrong_scope = sanitize_leanstral_failure_branch_candidates(task, response, failures)
    fenced = sanitize_leanstral_failure_branch_candidates(
        task, f"```json\n{json.dumps(response)}\n```", failures
    )

    assert "unknown_or_nonfailed_obligation_id" in wrong_scope.reasons
    assert fenced.reasons == ("response_must_be_strict_json",)


def test_response_schema_is_explicit_and_stable() -> None:
    task = _task()
    response = _response_from_prompt(task, _failures(task))

    assert response["schema_version"] == LEANSTRAL_FAILURE_BRANCH_RESPONSE_SCHEMA_VERSION
    assert response["task_id"] == task.task_id
    assert response["target_modal_ir_hash"] == task.modal_ir_hash


def test_strict_sanitizer_rejects_duplicate_json_keys() -> None:
    task = _task()
    failures = _failures(task)
    encoded = json.dumps(_response_from_prompt(task, failures))
    encoded = encoded[:-1] + f', "task_id": {json.dumps(task.task_id)}}}'

    result = sanitize_leanstral_failure_branch_candidates(task, encoded, failures)

    assert result.accepted is False
    assert result.reasons == ("response_must_be_strict_json",)
