"""Unit tests for additive HF publication and credential-safety policy (LCR-008).

Acceptance: Policy refuses any live mutation before exact-51 coverage, final
manifest authorization, staging canary, and secret-redaction checks.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    AUTHORIZATION_SCHEMA,
    AUTHORIZED_ON,
    AUTHORIZED_OPERATIONS,
    CANONICAL_JURISDICTIONS,
    DEFAULT_CREDENTIALS_SCOPE,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_STAGING_BRANCH,
    EXPECTED_JURISDICTION_COUNT,
    FORBIDDEN_OPERATIONS,
    GOAL_ID,
    JurisdictionCoverageError,
    LiveMutationDeniedError,
    LiveMutationRequest,
    ManifestAuthorizationError,
    MutationPhase,
    OperationForbiddenError,
    PREVIOUS_PUBLIC_PIN,
    PublicationAuthorization,
    PublicationOperation,
    REQUIRED_LIVE_MUTATION_GATES,
    SCHEMA_VERSION,
    SECRET_ENV_NAMES,
    SecretRedactionError,
    StagingCanaryError,
    StagingFirstError,
    TASK_ID,
    TargetUnauthorizedError,
    assert_environment_only_credentials,
    assert_operation_authorized,
    assert_rollback_pin_preserved,
    assert_target_authorized,
    clear_authorization_cache,
    default_authorization_fixture_path,
    evaluate_live_mutation,
    example_authorized_main_request,
    example_authorized_staging_request,
    get_publication_authorization,
    load_publication_authorization,
    normalize_operation,
    redact_secrets,
    reject_credentials_in_payload,
    reject_secrets_in_argv,
    require_live_mutation,
    sealed_authorization_fixture_payload,
    validate_exact_51_coverage,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_authorization_cache()
    yield
    clear_authorization_cache()


@pytest.fixture(scope="module")
def sealed_authorization() -> PublicationAuthorization:
    return load_publication_authorization()


def _subset_jurisdictions() -> list[str]:
    return ["OR", "WA", "CA"]


def _extra_jurisdictions() -> list[str]:
    return sorted(CANONICAL_JURISDICTIONS) + ["PR"]


# ---------------------------------------------------------------------------
# Schema / sealed authorization fixture
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-publication-policy-v1"
    assert AUTHORIZATION_SCHEMA == (
        "ipfs_datasets_py/state-laws-publication-authorization@1"
    )
    assert TASK_ID == "LCR-008"
    assert GOAL_ID == "LCR-G010"
    assert EXPECTED_JURISDICTION_COUNT == 51
    assert DEFAULT_DATASET_REPO_ID == "justicedao/ipfs_state_laws"
    assert PREVIOUS_PUBLIC_PIN == "42f0546acc7c6cd55627eaf51fb820d5613b9021"
    assert AUTHORIZED_ON == "2026-08-10"
    assert REQUIRED_LIVE_MUTATION_GATES == (
        "exact_51_coverage",
        "final_manifest_authorization",
        "staging_canary",
        "secret_redaction",
    )


def test_canonical_jurisdiction_set_is_exact_51_including_dc() -> None:
    assert len(CANONICAL_JURISDICTIONS) == 51
    assert "DC" in CANONICAL_JURISDICTIONS
    assert "PR" not in CANONICAL_JURISDICTIONS
    validate_exact_51_coverage(sorted(CANONICAL_JURISDICTIONS))


def test_default_authorization_fixture_path_exists() -> None:
    path = default_authorization_fixture_path()
    assert path.is_file()
    assert path.as_posix().endswith(
        "tests/fixtures/legal_ir/state_laws_publication_authorization.json"
    )


def test_sealed_authorization_fixture_matches_policy_contract(
    sealed_authorization: PublicationAuthorization,
) -> None:
    assert sealed_authorization.task_id == TASK_ID
    assert sealed_authorization.dataset_repo_id == DEFAULT_DATASET_REPO_ID
    assert sealed_authorization.previous_public_pin == PREVIOUS_PUBLIC_PIN
    assert sealed_authorization.recorded_on == AUTHORIZED_ON
    assert sealed_authorization.status == "recorded"
    assert frozenset(sealed_authorization.authorized_operations) == AUTHORIZED_OPERATIONS
    assert sealed_authorization.release_mode == "additive"
    assert sealed_authorization.credentials_environment_only is True
    assert sealed_authorization.secret_redaction_required is True
    assert sealed_authorization.staging_first_required is True
    assert sealed_authorization.exact_51_coverage_required is True
    assert sealed_authorization.final_manifest_authorization_required is True
    assert sealed_authorization.staging_canary_required is True
    assert sealed_authorization.immutable_redownload_required is True
    assert sealed_authorization.rollback_pin_must_be_preserved is True
    assert sealed_authorization.deletion_allowed is False
    assert sealed_authorization.force_push_allowed is False
    assert sealed_authorization.history_rewrite_allowed is False
    assert sealed_authorization.visibility_change_allowed is False
    assert sealed_authorization.alternate_dataset_targets_allowed is False
    assert sealed_authorization.required_gates == REQUIRED_LIVE_MUTATION_GATES


def test_sealed_fixture_payload_is_secret_clean() -> None:
    path = default_authorization_fixture_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    reject_credentials_in_payload(payload, label="authorization_fixture")
    # Generator helper stays aligned with the on-disk fixture.
    generated = sealed_authorization_fixture_payload()
    assert generated["dataset_repo_id"] == payload["dataset_repo_id"]
    assert generated["previous_public_pin"] == payload["previous_public_pin"]
    assert generated["required_gates"] == payload["required_gates"]


def test_get_publication_authorization_caches(
    sealed_authorization: PublicationAuthorization,
) -> None:
    again = get_publication_authorization()
    assert again == sealed_authorization
    assert again is get_publication_authorization()


# ---------------------------------------------------------------------------
# Structural authorization
# ---------------------------------------------------------------------------


def test_target_must_be_justicedao_ipfs_state_laws(
    sealed_authorization: PublicationAuthorization,
) -> None:
    assert_target_authorized(
        DEFAULT_DATASET_REPO_ID, authorization=sealed_authorization
    )
    with pytest.raises(TargetUnauthorizedError):
        assert_target_authorized(
            "justicedao/ipfs_federal_register",
            authorization=sealed_authorization,
        )
    with pytest.raises(TargetUnauthorizedError):
        assert_target_authorized(
            "evil/other-dataset", authorization=sealed_authorization
        )


def test_only_additive_operations_authorized(
    sealed_authorization: PublicationAuthorization,
) -> None:
    for op in AUTHORIZED_OPERATIONS:
        assert_operation_authorized(op, authorization=sealed_authorization)
    for forbidden in sorted(FORBIDDEN_OPERATIONS):
        with pytest.raises(OperationForbiddenError):
            normalize_operation(forbidden)
    with pytest.raises(OperationForbiddenError):
        assert_operation_authorized(
            "delete_file", authorization=sealed_authorization
        )


def test_rollback_pin_must_be_preserved(
    sealed_authorization: PublicationAuthorization,
) -> None:
    assert_rollback_pin_preserved(
        PREVIOUS_PUBLIC_PIN, authorization=sealed_authorization
    )
    with pytest.raises(Exception):
        assert_rollback_pin_preserved(
            "a" * 40, authorization=sealed_authorization
        )


# ---------------------------------------------------------------------------
# Happy paths: staging and main
# ---------------------------------------------------------------------------


def test_authorized_staging_mutation_passes_all_gates() -> None:
    decision = evaluate_live_mutation(example_authorized_staging_request())
    assert decision.authorized is True
    assert decision.operation == PublicationOperation.ADDITIVE_STAGING_UPLOAD.value
    assert decision.phase == MutationPhase.STAGING.value
    assert set(decision.passed_gates) == set(REQUIRED_LIVE_MUTATION_GATES)
    assert decision.reason_codes == ()
    require_live_mutation(example_authorized_staging_request())


def test_authorized_main_mutation_requires_staging_canary() -> None:
    decision = evaluate_live_mutation(example_authorized_main_request())
    assert decision.authorized is True
    assert decision.operation == PublicationOperation.ADDITIVE_MAIN_UPLOAD.value
    assert decision.phase == MutationPhase.MAIN.value
    assert set(decision.passed_gates) == set(REQUIRED_LIVE_MUTATION_GATES)
    require_live_mutation(example_authorized_main_request())


def test_live_mutation_request_round_trip() -> None:
    payload = example_authorized_main_request()
    req = LiveMutationRequest.from_mapping(payload)
    again = LiveMutationRequest.from_mapping(req.to_dict())
    assert again.operation == req.operation
    assert again.final_manifest_digest == req.final_manifest_digest
    assert again.staging_revision == req.staging_revision
    assert list(again.jurisdictions) == sorted(CANONICAL_JURISDICTIONS)


# ---------------------------------------------------------------------------
# Gate: exact-51 coverage / subset rejection
# ---------------------------------------------------------------------------


def test_refuses_live_mutation_when_jurisdiction_subset() -> None:
    payload = example_authorized_staging_request()
    payload["jurisdictions"] = _subset_jurisdictions()
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("exact_51" in code or "jurisdiction" in code for code in decision.reason_codes)
    with pytest.raises(LiveMutationDeniedError):
        require_live_mutation(payload)


def test_refuses_live_mutation_when_jurisdiction_superset() -> None:
    payload = example_authorized_staging_request()
    payload["jurisdictions"] = _extra_jurisdictions()
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert decision.reason_codes


def test_validate_exact_51_coverage_rejects_missing_extra_and_duplicates() -> None:
    codes = sorted(CANONICAL_JURISDICTIONS)
    with pytest.raises(JurisdictionCoverageError):
        validate_exact_51_coverage(codes[:-1])
    with pytest.raises(JurisdictionCoverageError):
        validate_exact_51_coverage(codes + ["PR"])
    with pytest.raises(JurisdictionCoverageError):
        validate_exact_51_coverage(codes + ["AL"])


# ---------------------------------------------------------------------------
# Gate: final manifest authorization
# ---------------------------------------------------------------------------


def test_refuses_without_authorize_mutation_flag() -> None:
    payload = example_authorized_staging_request()
    payload["authorize_mutation"] = False
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("final_manifest_authorization" in c for c in decision.reason_codes)
    assert "exact_51_coverage" in decision.passed_gates


def test_refuses_without_authorization_receipt_id() -> None:
    payload = example_authorized_staging_request()
    payload["authorization_receipt_id"] = None
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("final_manifest_authorization" in c for c in decision.reason_codes)


def test_refuses_invalid_manifest_digest() -> None:
    payload = example_authorized_staging_request()
    payload["final_manifest_digest"] = "not-a-digest"
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert decision.reason_codes


def test_manifest_authorization_check_raises() -> None:
    payload = example_authorized_staging_request()
    payload["authorize_mutation"] = False
    req = LiveMutationRequest.from_mapping(
        {**payload, "authorize_mutation": True, "authorization_receipt_id": "x"}
    )
    denied = replace(req, authorize_mutation=False)
    with pytest.raises(ManifestAuthorizationError):
        from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
            check_final_manifest_authorization,
        )

        check_final_manifest_authorization(denied)


# ---------------------------------------------------------------------------
# Gate: staging canary / staging-first
# ---------------------------------------------------------------------------


def test_staging_upload_requires_explicit_non_production_branch() -> None:
    payload = example_authorized_staging_request()
    payload["staging_branch"] = None
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("staging_canary" in c for c in decision.reason_codes)


def test_staging_upload_rejects_main_branch() -> None:
    payload = example_authorized_staging_request()
    payload["staging_branch"] = "main"
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False


def test_main_upload_refused_without_staging_canary() -> None:
    payload = example_authorized_main_request()
    payload["staging_canary_passed"] = False
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("staging_canary" in c for c in decision.reason_codes)
    with pytest.raises(LiveMutationDeniedError) as exc_info:
        require_live_mutation(payload)
    assert exc_info.value.reason_codes


def test_main_upload_requires_immutable_staging_revision_and_redownload() -> None:
    payload = example_authorized_main_request()
    payload["staging_revision"] = "latest"
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False

    payload = example_authorized_main_request()
    payload["staging_redownload_verified"] = False
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("staging_canary" in c for c in decision.reason_codes)


def test_main_upload_requires_manifest_identity_with_canary() -> None:
    payload = example_authorized_main_request()
    payload["staging_canary_manifest_digest"] = "d" * 64
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("staging_canary" in c for c in decision.reason_codes)


def test_staging_canary_check_raises_on_main_without_pass() -> None:
    from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
        check_staging_canary,
    )

    req = LiveMutationRequest.from_mapping(example_authorized_main_request())
    denied = replace(req, staging_canary_passed=False)
    with pytest.raises((StagingFirstError, StagingCanaryError)):
        check_staging_canary(denied)


# ---------------------------------------------------------------------------
# Gate: secret redaction / environment-only credentials
# ---------------------------------------------------------------------------


def test_refuses_when_secret_redacted_false() -> None:
    payload = example_authorized_staging_request()
    payload["secret_redacted"] = False
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("secret_redaction" in c for c in decision.reason_codes)


def test_refuses_when_credentials_not_environment_only() -> None:
    payload = example_authorized_staging_request()
    payload["credentials_environment_only"] = False
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("secret_redaction" in c for c in decision.reason_codes)


def test_refuses_credential_material_in_payload() -> None:
    payload = example_authorized_staging_request()
    payload["payload"] = {"hf_token": "hf_abcdefghijklmnopqrstuvwxyz0123456789"}
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("secret_redaction" in c for c in decision.reason_codes)


def test_refuses_secrets_on_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_supersecrettokenvalue0001")
    with pytest.raises(Exception):
        reject_secrets_in_argv(
            ["tool", "--hf-token=hf_supersecrettokenvalue0001"],
            environ={"HF_TOKEN": "hf_supersecrettokenvalue0001"},
        )
    payload = example_authorized_staging_request()
    payload["argv"] = ["tool", "--token", "hf_supersecrettokenvalue0001"]
    decision = evaluate_live_mutation(
        payload, environ={"HF_TOKEN": "hf_supersecrettokenvalue0001"}
    )
    assert decision.authorized is False


def test_reject_credentials_in_payload_allows_policy_booleans() -> None:
    reject_credentials_in_payload(
        {
            "mutation_requires_authorization": True,
            "credentials_environment_only": True,
            "secret_redacted": True,
            "credentials_scope": DEFAULT_CREDENTIALS_SCOPE,
        },
        label="policy_flags",
    )


def test_redact_secrets_masks_token_like_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_redactme_value_1234567890")
    redacted = redact_secrets(
        {
            "note": "token=hf_redactme_value_1234567890",
            "hf_token": "hf_redactme_value_1234567890",
            "ok": True,
        },
        environ={"HF_TOKEN": "hf_redactme_value_1234567890"},
    )
    assert "hf_redactme_value_1234567890" not in json.dumps(redacted)
    assert redacted["hf_token"] == "[REDACTED]"
    assert redacted["ok"] is True


def test_assert_environment_only_credentials_scope() -> None:
    assert (
        assert_environment_only_credentials(
            credentials_scope=DEFAULT_CREDENTIALS_SCOPE
        )
        == DEFAULT_CREDENTIALS_SCOPE
    )
    with pytest.raises(Exception):
        assert_environment_only_credentials(
            credentials_scope="dataset:write:evil/other"
        )
    with pytest.raises(Exception):
        assert_environment_only_credentials(
            credentials_present_in_argv=True
        )


def test_secret_env_names_cover_hub_tokens() -> None:
    assert "HF_TOKEN" in SECRET_ENV_NAMES
    assert "HUGGING_FACE_HUB_TOKEN" in SECRET_ENV_NAMES


# ---------------------------------------------------------------------------
# Combined refusal: any missing gate blocks live mutation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutator,gate_fragment",
    [
        (
            lambda p: p.update(jurisdictions=_subset_jurisdictions()) or p,
            "jurisdiction",
        ),
        (
            lambda p: p.update(authorize_mutation=False) or p,
            "final_manifest_authorization",
        ),
        (
            lambda p: p.update(staging_canary_passed=False) or p,
            "staging_canary",
        ),
        (
            lambda p: p.update(secret_redacted=False) or p,
            "secret_redaction",
        ),
    ],
)
def test_main_mutation_refused_when_any_required_gate_fails(
    mutator, gate_fragment: str
) -> None:
    payload = example_authorized_main_request()
    mutator(payload)
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    joined = " ".join(decision.reason_codes).lower()
    assert gate_fragment in joined
    with pytest.raises(LiveMutationDeniedError):
        require_live_mutation(payload)


def test_wrong_dataset_target_refused_even_with_passing_gates() -> None:
    payload = example_authorized_staging_request()
    payload["dataset_repo_id"] = "justicedao/other_dataset"
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False
    assert any("target" in c for c in decision.reason_codes)


def test_forbidden_operation_refused() -> None:
    payload = example_authorized_staging_request()
    payload["operation"] = "delete"
    decision = evaluate_live_mutation(payload)
    assert decision.authorized is False


def test_decision_payload_is_secret_clean() -> None:
    decision = evaluate_live_mutation(example_authorized_main_request())
    reject_credentials_in_payload(decision.to_dict(), label="decision")
    denied = evaluate_live_mutation(
        {
            **example_authorized_main_request(),
            "secret_redacted": False,
        }
    )
    reject_credentials_in_payload(denied.to_dict(), label="denied_decision")


def test_authorization_record_round_trip(
    sealed_authorization: PublicationAuthorization,
) -> None:
    again = PublicationAuthorization.from_mapping(sealed_authorization.to_dict())
    assert again.dataset_repo_id == sealed_authorization.dataset_repo_id
    assert again.previous_public_pin == sealed_authorization.previous_public_pin
    assert again.required_gates == sealed_authorization.required_gates


def test_staging_default_branch_constant() -> None:
    assert DEFAULT_STAGING_BRANCH.startswith("stage/")
    assert "main" not in DEFAULT_STAGING_BRANCH.casefold().split("/")


def test_deepcopy_example_requests_are_independent() -> None:
    a = deepcopy(example_authorized_staging_request())
    b = example_authorized_staging_request()
    a["authorize_mutation"] = False
    assert b["authorize_mutation"] is True
