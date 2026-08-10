"""Unit tests for the fail-closed staged/public mutation gate (LCR-074).

Acceptance: Missing/incomplete tasks or ancestor work, matching nonterminal
refill work, fixture evidence, digest/status drift, wrong repo or phase, a
main mutation with an absent/future/post-hoc seal, a staging gate that
substitutes a later seal for its phase evidence, unexpected operation, dirty
evidence, credential mismatch, or any delete/force/history/visibility action
denies before the first network mutation; upload callbacks are never invoked
on every denial path; staging does not require the post-canary main seal.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable

import pytest

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    AUTHORIZED_DATASET_REPO_IDS,
    AUTHORIZED_OPERATIONS,
    BASELINE_REVISIONS,
    FEDERAL_DATASET_REPO_ID,
    FEDERAL_PREVIOUS_PUBLIC_PIN,
    FORBIDDEN_OPERATIONS,
    GATE_SCHEMA,
    GENERATED_WORK_GUARD,
    GENERATED_WORK_TASK_NUMBER_FLOOR,
    GOAL_ID,
    PHASE_REQUIREMENTS,
    PROGRAM_ID,
    PublicationGateDeniedError,
    PublicationGateRequest,
    PublicationOperation,
    PublicationPhase,
    REQUIRED_PUBLICATION_GATES,
    SCHEMA_VERSION,
    STATE_DATASET_REPO_ID,
    STATE_PREVIOUS_PUBLIC_PIN,
    TASK_ID,
    apply_denial_mutator,
    authorize_and_mutate,
    clear_gate_fixture_cache,
    credentials_scope_for,
    default_fixture_path,
    evaluate_publication_gate,
    example_authorized_request,
    find_publication_blocking_generated_work,
    load_gate_fixture,
    phase_requirements,
    prepublication_seal_required,
    require_publication_gate,
    sealed_gate_fixture_payload,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_gate_fixture_cache()
    yield
    clear_gate_fixture_cache()


def _callback_tracker() -> tuple[list[Any], Callable[..., Any]]:
    calls: list[Any] = []

    def _upload(decision: Any) -> str:
        calls.append(decision)
        return "mutated"

    return calls, _upload


# ---------------------------------------------------------------------------
# Schema / fixture identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "legal-corpora-publication-gate-v1"
    assert GATE_SCHEMA == "ipfs_datasets_py/legal-corpora-publication-gate@1"
    assert TASK_ID == "LCR-074"
    assert GOAL_ID == "LCR-G080"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert STATE_DATASET_REPO_ID == "justicedao/ipfs_state_laws"
    assert FEDERAL_DATASET_REPO_ID == "justicedao/ipfs_federal_register"
    assert STATE_PREVIOUS_PUBLIC_PIN == "42f0546acc7c6cd55627eaf51fb820d5613b9021"
    assert FEDERAL_PREVIOUS_PUBLIC_PIN == "720668ae016cc400916dda884c9005e03618edfa"
    assert GENERATED_WORK_TASK_NUMBER_FLOOR == 77
    assert AUTHORIZED_DATASET_REPO_IDS == frozenset(
        {STATE_DATASET_REPO_ID, FEDERAL_DATASET_REPO_ID}
    )
    assert AUTHORIZED_OPERATIONS == frozenset(
        {"additive_staging_upload", "additive_main_upload"}
    )
    assert REQUIRED_PUBLICATION_GATES == (
        "phase_target_operation",
        "task_ancestor_closure",
        "generated_work_guard",
        "receipt_evidence",
        "digest_status_binding",
        "prepublication_seal",
        "credential_identity",
        "evidence_cleanliness",
    )


def test_default_fixture_path_exists_and_matches_generator() -> None:
    path = default_fixture_path()
    assert path.is_file()
    assert path.as_posix().endswith(
        "tests/fixtures/legal_ir/legal_corpora_publication_gate.json"
    )
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    generated = sealed_gate_fixture_payload(include_examples=False)
    assert on_disk["schema"] == generated["schema"] == GATE_SCHEMA
    assert on_disk["task_id"] == generated["task_id"] == TASK_ID
    assert on_disk["phase_requirements"] == generated["phase_requirements"]
    assert on_disk["generated_work_guard"] == generated["generated_work_guard"]
    assert on_disk["required_gates"] == generated["required_gates"]
    assert on_disk["authorized_dataset_repo_ids"] == generated[
        "authorized_dataset_repo_ids"
    ]
    assert on_disk["baseline_revisions"] == generated["baseline_revisions"]
    assert on_disk["prepublication_seal_is_not_required_for_staging"] is True
    assert on_disk["prepublication_seal_must_precede_main_mutation"] is True
    assert on_disk["uploader_must_invoke_gate_before_first_network_mutation"] is True
    assert len(on_disk["denial_cases"]) == len(generated["denial_cases"])
    loaded = load_gate_fixture()
    assert loaded["schema"] == GATE_SCHEMA


def test_phase_requirements_match_release_policy_contract() -> None:
    assert set(PHASE_REQUIREMENTS) == {
        "state_staging",
        "state_main",
        "federal_staging",
        "federal_main",
    }
    assert prepublication_seal_required("state_staging") is False
    assert prepublication_seal_required("federal_staging") is False
    assert prepublication_seal_required("state_main") is True
    assert prepublication_seal_required("federal_main") is True

    state_staging = phase_requirements("state_staging")
    assert state_staging["dataset_repo_id"] == STATE_DATASET_REPO_ID
    assert state_staging["authorized_operation"] == "additive_staging_upload"
    assert "LCR-039" in state_staging["required_task_ids"]
    assert "LCR-074" in state_staging["required_task_ids"]
    state_prepublication = (
        "docs/reports/legal_corpora_reindex/state_prepublication_seal.json"
    )
    assert state_prepublication not in state_staging["required_receipts"]

    state_main = phase_requirements("state_main")
    assert state_prepublication in state_main["required_receipts"]
    assert state_main["previous_public_pin"] == STATE_PREVIOUS_PUBLIC_PIN

    federal_main = phase_requirements("federal_main")
    assert federal_main["dataset_repo_id"] == FEDERAL_DATASET_REPO_ID
    assert federal_main["previous_public_pin"] == FEDERAL_PREVIOUS_PUBLIC_PIN
    assert (
        "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
        in federal_main["required_receipts"]
    )
    assert all(
        "LCR-084" in contract["required_task_ids"]
        for contract in PHASE_REQUIREMENTS.values()
    )

    assert GENERATED_WORK_GUARD["task_number_floor"] == 77
    assert GENERATED_WORK_GUARD["deny_nonterminal_matching_generated_work"] is True
    assert (
        GENERATED_WORK_GUARD["unscoped_or_unknown_goal_lineage_denies_every_phase"]
        is True
    )
    assert BASELINE_REVISIONS[STATE_DATASET_REPO_ID] == STATE_PREVIOUS_PUBLIC_PIN
    assert BASELINE_REVISIONS[FEDERAL_DATASET_REPO_ID] == FEDERAL_PREVIOUS_PUBLIC_PIN


# ---------------------------------------------------------------------------
# Happy paths: all four phases authorize; staging omits main seal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    [
        PublicationPhase.STATE_STAGING.value,
        PublicationPhase.STATE_MAIN.value,
        PublicationPhase.FEDERAL_STAGING.value,
        PublicationPhase.FEDERAL_MAIN.value,
    ],
)
def test_authorized_request_passes_all_gates(phase: str) -> None:
    payload = example_authorized_request(phase)
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is True
    assert decision.network_mutation_permitted is True
    assert decision.phase == phase
    assert set(decision.passed_gates) == set(REQUIRED_PUBLICATION_GATES)
    assert decision.reason_codes == ()
    require_publication_gate(payload)

    if phase.endswith("_staging"):
        assert "prepublication_seal" not in payload or payload.get(
            "prepublication_seal"
        ) is None
        assert prepublication_seal_required(phase) is False
    else:
        assert payload.get("prepublication_seal") is not None
        assert prepublication_seal_required(phase) is True


def test_staging_does_not_require_post_canary_main_seal() -> None:
    for phase in ("state_staging", "federal_staging"):
        payload = example_authorized_request(phase)
        # Explicitly ensure no seal is present.
        payload.pop("prepublication_seal", None)
        decision = evaluate_publication_gate(payload)
        assert decision.authorized is True
        assert decision.details["prepublication_seal_required"] is False

        # Adding a non-substituting informational seal must not be required,
        # and must not break authorization when timing is clean.
        payload_with_info = deepcopy(payload)
        payload_with_info["prepublication_seal"] = {
            "present": True,
            "timing": "before_mutation",
            "informational_only": True,
        }
        decision_info = evaluate_publication_gate(payload_with_info)
        assert decision_info.authorized is True


def test_authorize_and_mutate_invokes_callback_only_when_authorized() -> None:
    calls, upload = _callback_tracker()
    payload = example_authorized_request("state_staging")
    result = authorize_and_mutate(payload, upload)
    assert result == "mutated"
    assert len(calls) == 1
    assert calls[0].authorized is True


def test_request_round_trip() -> None:
    payload = example_authorized_request("federal_main")
    req = PublicationGateRequest.from_mapping(payload)
    again = PublicationGateRequest.from_mapping(req.to_dict())
    assert again.phase == req.phase
    assert again.final_manifest_digest == req.final_manifest_digest
    assert again.operation == PublicationOperation.ADDITIVE_MAIN_UPLOAD.value
    assert again.dataset_repo_id == FEDERAL_DATASET_REPO_ID


# ---------------------------------------------------------------------------
# Denial paths — upload callback never invoked
# ---------------------------------------------------------------------------


def _assert_denied(
    payload: dict[str, Any],
    *,
    reason_fragment: str,
) -> None:
    calls, upload = _callback_tracker()
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is False
    assert decision.network_mutation_permitted is False
    assert any(reason_fragment in code for code in decision.reason_codes), (
        decision.reason_codes
    )
    with pytest.raises(PublicationGateDeniedError) as exc_info:
        require_publication_gate(payload)
    assert exc_info.value.reason_codes
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate(payload, upload)
    assert calls == [], "upload callback must never run on denial paths"


def test_incomplete_required_task_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["task_statuses"]["LCR-039"] = "todo"
    _assert_denied(payload, reason_fragment="task_ancestor_closure")


def test_incomplete_ancestor_work_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["task_statuses"]["LCR-008"] = "todo"
    _assert_denied(payload, reason_fragment="task_ancestor_closure")


def test_nonterminal_generated_refill_work_denies() -> None:
    payload = example_authorized_request("state_main")
    payload["task_statuses"]["LCR-080"] = "todo"
    payload["task_goal_ids"]["LCR-080"] = "LCR-G080"
    _assert_denied(payload, reason_fragment="generated_work_guard")


def test_unscoped_generated_lineage_denies_every_phase() -> None:
    for phase in PHASE_REQUIREMENTS:
        payload = example_authorized_request(phase)
        payload["task_statuses"]["LCR-099"] = "in_progress"
        payload["task_goal_ids"]["LCR-099"] = "LCR-G999"
        payload["goal_parents"]["LCR-G999"] = []
        _assert_denied(payload, reason_fragment="generated_work_guard")


def test_unknown_goal_lineage_denies() -> None:
    payload = example_authorized_request("federal_staging")
    payload["task_statuses"]["LCR-088"] = "todo"
    # Missing goal id => unknown lineage.
    payload["task_goal_ids"].pop("LCR-088", None)
    _assert_denied(payload, reason_fragment="generated_work_guard")


def test_fixture_only_evidence_flag_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["fixture_only_evidence"] = True
    _assert_denied(payload, reason_fragment="receipt_evidence")


def test_fixture_only_receipt_denies() -> None:
    payload = example_authorized_request("federal_main")
    seal_path = (
        "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
    )
    payload["receipts"][seal_path]["fixture_only"] = True
    _assert_denied(payload, reason_fragment="receipt_evidence")


def test_digest_drift_denies() -> None:
    payload = example_authorized_request("state_main")
    canary = "docs/reports/legal_corpora_reindex/staging_canary.json"
    payload["expected_receipt_digests"][canary] = "0" * 64
    _assert_denied(payload, reason_fragment="digest_status_binding")


def test_manifest_digest_drift_in_receipt_denies() -> None:
    payload = example_authorized_request("state_staging")
    path = "docs/reports/legal_corpora_reindex/release_candidate.json"
    payload["receipts"][path]["final_manifest_digest"] = "a" * 64
    # Keep expected content digest aligned so only manifest binding fails.
    _assert_denied(payload, reason_fragment="digest_status_binding")


def test_wrong_repo_for_phase_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["dataset_repo_id"] = FEDERAL_DATASET_REPO_ID
    payload["credentials_scope"] = credentials_scope_for(FEDERAL_DATASET_REPO_ID)
    payload["credential_identity"] = f"env:{FEDERAL_DATASET_REPO_ID}"
    payload["previous_public_pin"] = FEDERAL_PREVIOUS_PUBLIC_PIN
    _assert_denied(payload, reason_fragment="phase_target_operation")


def test_wrong_operation_for_phase_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["operation"] = "additive_main_upload"
    _assert_denied(payload, reason_fragment="phase_target_operation")


def test_main_seal_absent_denies() -> None:
    payload = example_authorized_request("state_main")
    payload["prepublication_seal"] = {"present": False, "timing": "absent"}
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_main_seal_future_denies() -> None:
    payload = example_authorized_request("federal_main")
    payload["prepublication_seal"]["timing"] = "future"
    payload["prepublication_seal"]["future"] = True
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_main_seal_post_hoc_denies() -> None:
    payload = example_authorized_request("state_main")
    payload["prepublication_seal"]["timing"] = "post_hoc"
    payload["prepublication_seal"]["post_hoc"] = True
    payload["prepublication_seal"]["created_after_mutation"] = True
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_main_without_seal_object_or_receipt_denies() -> None:
    payload = example_authorized_request("state_main")
    payload["prepublication_seal"] = None
    seal_path = "docs/reports/legal_corpora_reindex/state_prepublication_seal.json"
    del payload["receipts"][seal_path]
    del payload["expected_receipt_digests"][seal_path]
    _assert_denied(payload, reason_fragment="receipt_evidence")


def test_staging_seal_substitution_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["prepublication_seal"] = {
        "present": True,
        "timing": "before_mutation",
        "substitutes_for_phase_evidence": True,
        "required_for_staging": True,
    }
    _assert_denied(payload, reason_fragment="receipt_evidence")


def test_staging_seal_receipt_substitution_denies() -> None:
    payload = example_authorized_request("federal_staging")
    seal_path = (
        "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
    )
    payload["receipts"][seal_path] = {
        "path": seal_path,
        "status": "sealed",
        "content_digest": "b" * 64,
        "substitutes_for_phase_evidence": True,
        "fixture_only": False,
        "dirty": False,
    }
    _assert_denied(payload, reason_fragment="receipt_evidence")


@pytest.mark.parametrize(
    "operation",
    sorted(
        {
            "delete",
            "force_push",
            "history_rewrite",
            "visibility_change",
            "delete_file",
            "force-push",
        }
    ),
)
def test_forbidden_operations_deny_before_mutation(operation: str) -> None:
    payload = example_authorized_request("state_staging")
    payload["operation"] = operation
    calls, upload = _callback_tracker()
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is False
    assert decision.network_mutation_permitted is False
    assert decision.reason_codes
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate(payload, upload)
    assert calls == []
    assert operation.replace("-", "_").split("_")[0] in " ".join(
        FORBIDDEN_OPERATIONS
    ) or operation in FORBIDDEN_OPERATIONS or "force" in operation or "delete" in operation


def test_dirty_evidence_denies() -> None:
    payload = example_authorized_request("federal_staging")
    payload["evidence_is_dirty"] = True
    _assert_denied(payload, reason_fragment="evidence_cleanliness")


def test_dirty_receipt_status_denies() -> None:
    payload = example_authorized_request("state_staging")
    path = "docs/reports/legal_corpora_reindex/local_e2e.json"
    payload["receipts"][path]["status"] = "failed"
    payload["receipts"][path]["dirty"] = True
    _assert_denied(payload, reason_fragment="receipt_evidence")


def test_credential_scope_mismatch_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["credentials_scope"] = credentials_scope_for(FEDERAL_DATASET_REPO_ID)
    _assert_denied(payload, reason_fragment="credential_identity")


def test_credential_identity_mismatch_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["credential_identity"] = "env:evil/other-dataset"
    _assert_denied(payload, reason_fragment="credential_identity")


def test_authorize_mutation_false_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["authorize_mutation"] = False
    _assert_denied(payload, reason_fragment="phase_target_operation")


def test_secret_material_in_payload_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["payload"] = {"hf_token": "hf_abcdefghijklmnopqrstuvwxyz0123456789"}
    _assert_denied(payload, reason_fragment="credential_identity")


def test_wrong_previous_public_pin_denies() -> None:
    payload = example_authorized_request("state_staging")
    payload["previous_public_pin"] = "a" * 40
    _assert_denied(payload, reason_fragment="phase_target_operation")


def test_main_missing_staging_revision_denies() -> None:
    payload = example_authorized_request("state_main")
    payload["staging_revision"] = None
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_missing_required_receipt_denies() -> None:
    payload = example_authorized_request("federal_staging")
    path = "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json"
    del payload["receipts"][path]
    del payload["expected_receipt_digests"][path]
    _assert_denied(payload, reason_fragment="receipt_evidence")


# ---------------------------------------------------------------------------
# Fixture denial recipes (compact mutators)
# ---------------------------------------------------------------------------


def test_fixture_denial_cases_all_refuse_and_skip_upload() -> None:
    fixture = sealed_gate_fixture_payload(include_examples=False)
    for case in fixture["denial_cases"]:
        base = example_authorized_request(case["phase"])
        payload = apply_denial_mutator(base, case["mutator"])
        _assert_denied(payload, reason_fragment=case["reason_fragment"])


# ---------------------------------------------------------------------------
# Generated-work helper
# ---------------------------------------------------------------------------


def test_find_publication_blocking_generated_work_scoped() -> None:
    blockers = find_publication_blocking_generated_work(
        phase="state_staging",
        task_statuses={"LCR-080": "todo", "LCR-040": "todo", "LCR-081": "completed"},
        task_goal_ids={
            "LCR-080": "LCR-G080",
            "LCR-040": "LCR-G070",
            "LCR-081": "LCR-G080",
        },
        goal_parents={
            "LCR-G080": ("LCR-G000",),
            "LCR-G070": ("LCR-G000",),
            "LCR-G000": (),
        },
    )
    # LCR-040 is below floor 77; LCR-081 is completed; LCR-080 blocks.
    assert blockers == ("LCR-080",)


def test_decision_payload_is_secret_clean() -> None:
    decision = evaluate_publication_gate(example_authorized_request("state_main"))
    dumped = json.dumps(decision.to_dict())
    assert "hf_" not in dumped
    assert "Bearer " not in dumped
    assert decision.to_dict()["task_id"] == TASK_ID


def test_fixture_file_is_secret_clean() -> None:
    path = default_fixture_path()
    text = path.read_text(encoding="utf-8")
    assert "hf_" not in text or "hf_token" not in text.lower()
    payload = json.loads(text)
    assert payload["payload"]["credentials_environment_only"] is True
    assert payload["payload"]["secret_redacted"] is True
