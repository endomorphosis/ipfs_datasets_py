"""Unit tests for additive Dataset and Bucket publication authority (OUL-007).

Acceptance: only justicedao/open-us-law-sparse-graphrag dataset creation or
additive commits and justicedao/open-us-law-bucket
releases/<manifest_sha256>/ writes are authorized; root overwrite, delete,
force push, history rewrite, visibility change, mutable query pins, and
pre-seal writes fail before any callback.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable

import pytest
from jsonschema import Draft202012Validator

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    AUTHORIZED_OPERATIONS,
    BUCKET_POINTER_PATH,
    BUCKET_QUERY_IDENTITY,
    BUCKET_RELEASE_PREFIX_TEMPLATE,
    DATASET_QUERY_IDENTITY,
    FORBIDDEN_OPERATIONS,
    GATE_SCHEMA,
    GENERATED_WORK_GUARD,
    GENERATED_WORK_TASK_NUMBER_FLOOR,
    GOAL_ID,
    PROGRAM_ID,
    PROTECTED_RAW_ROOT_GLOBS,
    QUERY_OPERATIONS,
    REQUIRED_PUBLICATION_GATES,
    SCHEMA_VERSION,
    TASK_ID,
    MutableQueryPinError,
    OperationForbiddenError,
    PublicationGateDeniedError,
    PublicationOperation,
    PublicationPhase,
    PublicationRequest,
    apply_denial_mutator,
    authorize_and_mutate,
    clear_policy_schema_cache,
    credentials_scope_for,
    evaluate_publication_gate,
    example_authorized_request,
    find_publication_blocking_generated_work,
    is_protected_raw_root_path,
    load_publication_policy_schema,
    parse_release_prefix_path,
    publication_policy_schema_path,
    release_prefix_for,
    require_immutable_revision,
    require_publication_gate,
    sealed_publication_policy,
    validate_publication_policy,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_policy_schema_cache()
    yield
    clear_policy_schema_cache()


def _callback_tracker() -> tuple[list[Any], Callable[..., Any]]:
    calls: list[Any] = []

    def _upload(decision: Any) -> str:
        calls.append(decision)
        return "mutated"

    return calls, _upload


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


# ---------------------------------------------------------------------------
# Schema / sealed policy identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-publication-policy-v1"
    assert GATE_SCHEMA == "ipfs_datasets_py/open-us-law-publication-policy@1"
    assert TASK_ID == "OUL-007"
    assert GOAL_ID == "OUL-G010"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert AUTHORIZED_DATASET_REPO_ID == "justicedao/open-us-law-sparse-graphrag"
    assert AUTHORIZED_BUCKET_ID == "justicedao/open-us-law-bucket"
    assert BUCKET_RELEASE_PREFIX_TEMPLATE == "releases/<manifest_sha256>/"
    assert BUCKET_POINTER_PATH == "LATEST.json"
    assert DATASET_QUERY_IDENTITY == "exact_40_hex_commit"
    assert BUCKET_QUERY_IDENTITY == BUCKET_RELEASE_PREFIX_TEMPLATE
    assert AUTHORIZED_OPERATIONS == frozenset(
        {
            "dataset_create",
            "dataset_additive_commit",
            "bucket_release_prefix_write",
            "bucket_pointer_update_last",
        }
    )
    assert QUERY_OPERATIONS == frozenset({"dataset_query", "bucket_query"})
    assert REQUIRED_PUBLICATION_GATES == (
        "target_authority",
        "operation_authority",
        "bucket_path",
        "query_pin",
        "prepublication_seal",
        "root_preservation",
        "destructive_ops",
        "generated_work_guard",
    )
    assert GENERATED_WORK_TASK_NUMBER_FLOOR == 49
    assert GENERATED_WORK_GUARD["deny_nonterminal_generated_work"] is True
    assert GENERATED_WORK_GUARD["unscoped_or_unknown_goal_lineage_denies"] is True
    assert "*.parquet" in PROTECTED_RAW_ROOT_GLOBS


def test_publication_policy_schema_is_valid_draft_2020_12() -> None:
    path = publication_policy_schema_path()
    assert path.is_file(), f"missing schema: {path}"
    schema = load_publication_policy_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == (
        "Open US Law additive Dataset and Bucket publication policy"
    )
    Draft202012Validator.check_schema(schema)


def test_sealed_policy_validates_against_schema() -> None:
    policy = sealed_publication_policy()
    validate_publication_policy(policy)
    Draft202012Validator(load_publication_policy_schema()).validate(policy)
    assert policy["authorized_dataset"] == AUTHORIZED_DATASET_REPO_ID
    assert policy["authorized_bucket"] == AUTHORIZED_BUCKET_ID
    assert policy["dataset_creation_authorized"] is True
    assert policy["dataset_additive_commits_authorized"] is True
    assert policy["bucket_release_prefix_writes_authorized"] is True
    assert policy["bucket_raw_root_overwrite_allowed"] is False
    assert policy["deletion_allowed"] is False
    assert policy["force_push_allowed"] is False
    assert policy["history_rewrite_allowed"] is False
    assert policy["visibility_change_allowed"] is False
    assert policy["mutable_query_pins_allowed"] is False
    assert policy["pre_seal_writes_allowed"] is False
    assert policy["callback_requires_authorization"] is True
    assert policy["prepublication_seal_required_for_public"] is True
    assert policy["staging_does_not_require_public_seal"] is True


def test_sealed_policy_refuses_weakened_flags() -> None:
    policy = sealed_publication_policy()
    policy["deletion_allowed"] = True
    with pytest.raises(Exception):
        validate_publication_policy(policy)
    policy = sealed_publication_policy()
    policy["authorized_dataset"] = "evil/other-dataset"
    with pytest.raises(Exception):
        validate_publication_policy(policy)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase,operation",
    [
        (PublicationPhase.STAGING.value, PublicationOperation.DATASET_CREATE.value),
        (PublicationPhase.STAGING.value, PublicationOperation.DATASET_ADDITIVE_COMMIT.value),
        (
            PublicationPhase.STAGING.value,
            PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE.value,
        ),
        (PublicationPhase.PUBLIC.value, PublicationOperation.DATASET_CREATE.value),
        (PublicationPhase.PUBLIC.value, PublicationOperation.DATASET_ADDITIVE_COMMIT.value),
        (
            PublicationPhase.PUBLIC.value,
            PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE.value,
        ),
        (
            PublicationPhase.PUBLIC.value,
            PublicationOperation.BUCKET_POINTER_UPDATE_LAST.value,
        ),
    ],
)
def test_authorized_additive_mutations_pass_all_gates(
    phase: str, operation: str
) -> None:
    payload = example_authorized_request(phase, operation)
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is True, decision.message
    assert decision.network_mutation_permitted is True
    assert set(decision.passed_gates) == set(REQUIRED_PUBLICATION_GATES)
    assert decision.reason_codes == ()
    assert decision.dataset_repo_id == AUTHORIZED_DATASET_REPO_ID
    assert decision.bucket_id == AUTHORIZED_BUCKET_ID
    require_publication_gate(payload)


def test_staging_does_not_require_public_prepublication_seal() -> None:
    payload = example_authorized_request(
        "staging", "dataset_additive_commit"
    )
    payload.pop("prepublication_seal", None)
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is True
    assert decision.details["prepublication_seal_required"] is False


def test_authorized_immutable_query_pins_do_not_mutate() -> None:
    dataset = example_authorized_request("query", "dataset_query")
    dataset_decision = evaluate_publication_gate(dataset)
    assert dataset_decision.authorized is True
    assert dataset_decision.network_mutation_permitted is False
    assert dataset_decision.operation == "dataset_query"

    bucket = example_authorized_request("query", "bucket_query")
    bucket_decision = evaluate_publication_gate(bucket)
    assert bucket_decision.authorized is True
    assert bucket_decision.network_mutation_permitted is False
    assert bucket["query_bucket_prefix"].startswith("releases/")


def test_authorize_and_mutate_invokes_callback_only_when_authorized() -> None:
    calls, upload = _callback_tracker()
    payload = example_authorized_request("public", "dataset_create")
    result = authorize_and_mutate(payload, upload)
    assert result == "mutated"
    assert len(calls) == 1
    assert calls[0].authorized is True
    assert calls[0].network_mutation_permitted is True


def test_query_authorization_does_not_invoke_mutation_callback() -> None:
    calls, upload = _callback_tracker()
    payload = example_authorized_request("query", "dataset_query")
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate(payload, upload)
    assert calls == []


def test_request_round_trip() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    req = PublicationRequest.from_mapping(payload)
    again = PublicationRequest.from_mapping(req.to_dict())
    assert again.operation == PublicationOperation.BUCKET_RELEASE_PREFIX_WRITE.value
    assert again.bucket_id == AUTHORIZED_BUCKET_ID
    assert again.object_path == req.object_path
    assert again.final_manifest_digest == req.final_manifest_digest


def test_release_prefix_helpers_bind_manifest_digest() -> None:
    digest = "ab" * 32
    assert release_prefix_for(digest) == f"releases/{digest}/"
    parsed_digest, suffix = parse_release_prefix_path(
        f"releases/{digest}/manifest.json"
    )
    assert parsed_digest == digest
    assert suffix == "manifest.json"


# ---------------------------------------------------------------------------
# Denial paths — callback never invoked
# ---------------------------------------------------------------------------


def test_wrong_dataset_target_denies() -> None:
    payload = example_authorized_request("public", "dataset_create")
    payload["dataset_repo_id"] = "justicedao/ipfs_state_laws"
    payload["credentials_scope"] = credentials_scope_for(
        dataset_repo_id="justicedao/ipfs_state_laws"
    )
    payload["credential_identity"] = "env:justicedao/ipfs_state_laws"
    _assert_denied(payload, reason_fragment="target_authority")


def test_wrong_bucket_target_denies() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["bucket_id"] = "justicedao/other-bucket"
    payload["credentials_scope"] = credentials_scope_for(
        bucket_id="justicedao/other-bucket"
    )
    payload["credential_identity"] = "env:justicedao/other-bucket"
    _assert_denied(payload, reason_fragment="target_authority")


def test_root_overwrite_of_raw_parquet_denies() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["object_path"] = "ga-statutes.parquet"
    _assert_denied(payload, reason_fragment="bucket_path")


def test_overwrite_raw_root_flag_denies() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["overwrite_raw_root"] = True
    _assert_denied(payload, reason_fragment="root_preservation")


def test_overwrite_existing_release_prefix_denies() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["overwrite_existing_prefix"] = True
    _assert_denied(payload, reason_fragment="root_preservation")


def test_protected_checksum_and_readme_paths_are_raw_root() -> None:
    assert is_protected_raw_root_path("SHA256SUMS.json")
    assert is_protected_raw_root_path("README.md")
    assert is_protected_raw_root_path("or-statutes.parquet")
    assert not is_protected_raw_root_path("releases/" + ("ab" * 32) + "/manifest.json")


@pytest.mark.parametrize(
    "operation",
    ["delete", "force_push", "history_rewrite", "visibility_change", "sync_delete"],
)
def test_forbidden_operations_deny_before_callback(operation: str) -> None:
    payload = example_authorized_request("staging", "dataset_additive_commit")
    payload["operation"] = operation
    calls, upload = _callback_tracker()
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is False
    assert decision.network_mutation_permitted is False
    assert decision.reason_codes
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate(payload, upload)
    assert calls == []
    assert (
        operation.replace("-", "_") in FORBIDDEN_OPERATIONS
        or "force" in operation
        or "delete" in operation
        or "visibility" in operation
        or "history" in operation
    )


def test_delete_flag_on_authorized_operation_denies() -> None:
    payload = example_authorized_request("public", "dataset_additive_commit")
    payload["delete_requested"] = True
    _assert_denied(payload, reason_fragment="destructive_ops")


def test_force_push_flag_denies() -> None:
    payload = example_authorized_request("public", "dataset_additive_commit")
    payload["force_push"] = True
    _assert_denied(payload, reason_fragment="destructive_ops")


def test_history_rewrite_flag_denies() -> None:
    payload = example_authorized_request("public", "dataset_additive_commit")
    payload["history_rewrite"] = True
    _assert_denied(payload, reason_fragment="destructive_ops")


def test_visibility_change_flag_denies() -> None:
    payload = example_authorized_request("public", "dataset_create")
    payload["visibility_change"] = True
    _assert_denied(payload, reason_fragment="destructive_ops")


def test_visibility_to_private_denies() -> None:
    payload = example_authorized_request("public", "dataset_create")
    payload["visibility"] = "private"
    _assert_denied(payload, reason_fragment="destructive_ops")


@pytest.mark.parametrize("pin", ["latest", "main", "master", "HEAD", "refs/heads/main"])
def test_mutable_dataset_query_pin_denies(pin: str) -> None:
    payload = example_authorized_request("query", "dataset_query")
    payload["query_revision"] = pin
    _assert_denied(payload, reason_fragment="query_pin")


@pytest.mark.parametrize(
    "prefix",
    ["LATEST.json", "latest", "releases/latest/", "releases/main/manifest.json"],
)
def test_mutable_bucket_query_pin_denies(prefix: str) -> None:
    payload = example_authorized_request("query", "bucket_query")
    payload["query_bucket_prefix"] = prefix
    payload["object_path"] = prefix
    calls, upload = _callback_tracker()
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is False
    assert decision.network_mutation_permitted is False
    joined = " ".join(decision.reason_codes)
    assert "query_pin" in joined or "bucket_path" in joined or "request.invalid" in joined, (
        decision.reason_codes
    )
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate(payload, upload)
    assert calls == []


def test_require_immutable_revision_rejects_latest() -> None:
    with pytest.raises(MutableQueryPinError):
        require_immutable_revision("latest")
    with pytest.raises(MutableQueryPinError):
        require_immutable_revision("LATEST.json")


def test_public_pre_seal_write_denies() -> None:
    payload = example_authorized_request("public", "dataset_additive_commit")
    payload["prepublication_seal"] = None
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_unsealed_candidate_write_denies() -> None:
    payload = example_authorized_request("staging", "bucket_release_prefix_write")
    payload["sealed"] = False
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_public_seal_absent_timing_denies() -> None:
    payload = example_authorized_request("public", "dataset_create")
    payload["prepublication_seal"] = {"present": False, "timing": "absent"}
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_public_seal_future_denies() -> None:
    payload = example_authorized_request("public", "dataset_additive_commit")
    payload["prepublication_seal"]["timing"] = "future"
    payload["prepublication_seal"]["future"] = True
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_public_seal_post_hoc_denies() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["prepublication_seal"]["timing"] = "post_hoc"
    payload["prepublication_seal"]["post_hoc"] = True
    payload["prepublication_seal"]["created_after_mutation"] = True
    _assert_denied(payload, reason_fragment="prepublication_seal")


def test_authorize_mutation_false_denies() -> None:
    payload = example_authorized_request("staging", "dataset_create")
    payload["authorize_mutation"] = False
    _assert_denied(payload, reason_fragment="operation_authority")


def test_bucket_path_outside_release_prefix_denies() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["object_path"] = "staging/not-a-release/manifest.json"
    _assert_denied(payload, reason_fragment="bucket_path")


def test_bucket_path_digest_must_match_manifest() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["object_path"] = "releases/" + ("cd" * 32) + "/manifest.json"
    _assert_denied(payload, reason_fragment="bucket_path")


def test_path_traversal_denies_before_callback() -> None:
    payload = example_authorized_request("public", "bucket_release_prefix_write")
    payload["object_path"] = "releases/" + ("ab" * 32) + "/../ga-statutes.parquet"
    calls, upload = _callback_tracker()
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is False
    assert decision.network_mutation_permitted is False
    with pytest.raises(PublicationGateDeniedError):
        authorize_and_mutate(payload, upload)
    assert calls == []


def test_pointer_update_without_verified_prefix_denies() -> None:
    payload = example_authorized_request("public", "bucket_pointer_update_last")
    payload["prefix_complete"] = False
    _assert_denied(payload, reason_fragment="operation_authority")


def test_pointer_update_wrong_path_denies() -> None:
    payload = example_authorized_request("public", "bucket_pointer_update_last")
    payload["object_path"] = "README.md"
    _assert_denied(payload, reason_fragment="bucket_path")


def test_staging_pointer_update_denies() -> None:
    payload = example_authorized_request("public", "bucket_pointer_update_last")
    payload["phase"] = "staging"
    _assert_denied(payload, reason_fragment="operation_authority")


def test_credential_scope_mismatch_denies() -> None:
    payload = example_authorized_request("staging", "dataset_additive_commit")
    payload["credentials_scope"] = credentials_scope_for(
        dataset_repo_id="justicedao/ipfs_state_laws"
    )
    _assert_denied(payload, reason_fragment="operation_authority")


def test_secret_material_in_payload_denies() -> None:
    payload = example_authorized_request("staging", "dataset_create")
    payload["payload"] = {"hf_token": "hf_abcdefghijklmnopqrstuvwxyz0123456789"}
    _assert_denied(payload, reason_fragment="operation_authority")


def test_nonterminal_generated_work_denies() -> None:
    payload = example_authorized_request("public", "dataset_additive_commit")
    payload["task_statuses"] = {"OUL-049": "todo"}
    payload["task_goal_ids"] = {"OUL-049": "OUL-G080"}
    payload["goal_parents"] = {
        "OUL-G080": ["OUL-G000"],
        "OUL-G000": [],
    }
    _assert_denied(payload, reason_fragment="generated_work_guard")


def test_unscoped_generated_lineage_denies() -> None:
    payload = example_authorized_request("staging", "bucket_release_prefix_write")
    payload["task_statuses"] = {"OUL-099": "in_progress"}
    payload["task_goal_ids"] = {"OUL-099": "OUL-G999"}
    payload["goal_parents"] = {"OUL-G999": []}
    _assert_denied(payload, reason_fragment="generated_work_guard")


def test_completed_generated_work_does_not_block() -> None:
    payload = example_authorized_request("public", "dataset_create")
    payload["task_statuses"] = {"OUL-049": "completed"}
    payload["task_goal_ids"] = {"OUL-049": "OUL-G080"}
    decision = evaluate_publication_gate(payload)
    assert decision.authorized is True


def test_find_publication_blocking_generated_work_scoped() -> None:
    blockers = find_publication_blocking_generated_work(
        task_statuses={
            "OUL-049": "todo",
            "OUL-007": "todo",
            "OUL-050": "completed",
        },
        task_goal_ids={
            "OUL-049": "OUL-G080",
            "OUL-007": "OUL-G010",
            "OUL-050": "OUL-G080",
        },
        goal_parents={"OUL-G080": ("OUL-G000",), "OUL-G010": ("OUL-G000",), "OUL-G000": ()},
    )
    assert blockers == ("OUL-049",)


def test_normalize_operation_rejects_forbidden() -> None:
    with pytest.raises(OperationForbiddenError):
        PublicationOperation.coerce("delete")
    with pytest.raises(OperationForbiddenError):
        PublicationOperation.coerce("force-push")
    with pytest.raises(OperationForbiddenError):
        PublicationOperation.coerce("visibility_change")


def test_decision_payload_is_secret_clean() -> None:
    decision = evaluate_publication_gate(
        example_authorized_request("public", "dataset_additive_commit")
    )
    dumped = json.dumps(decision.to_dict())
    assert "hf_" not in dumped
    assert "Bearer " not in dumped
    assert decision.to_dict()["task_id"] == TASK_ID


def test_deepcopy_example_requests_are_independent() -> None:
    a = deepcopy(example_authorized_request("staging", "dataset_create"))
    b = example_authorized_request("staging", "dataset_create")
    a["authorize_mutation"] = False
    assert b["authorize_mutation"] is True


def test_compact_denial_mutators_all_refuse_and_skip_upload() -> None:
    cases = [
        {
            "phase": "public",
            "operation": "dataset_additive_commit",
            "mutator": {"dataset_repo_id": "evil/other"},
            "reason_fragment": "target_authority",
        },
        {
            "phase": "public",
            "operation": "bucket_release_prefix_write",
            "mutator": {"object_path": "SHA256SUMS.json"},
            "reason_fragment": "bucket_path",
        },
        {
            "phase": "public",
            "operation": "dataset_create",
            "mutator": {"operation": "delete"},
            "reason_fragment": "request.invalid",
        },
        {
            "phase": "query",
            "operation": "dataset_query",
            "mutator": {"query_revision": "latest"},
            "reason_fragment": "query_pin",
        },
        {
            "phase": "public",
            "operation": "dataset_additive_commit",
            "mutator": {"sealed": False},
            "reason_fragment": "prepublication_seal",
        },
        {
            "phase": "public",
            "operation": "dataset_additive_commit",
            "mutator": {"visibility_change": True},
            "reason_fragment": "destructive_ops",
        },
    ]
    for case in cases:
        base = example_authorized_request(case["phase"], case["operation"])
        payload = apply_denial_mutator(base, case["mutator"])
        _assert_denied(payload, reason_fragment=case["reason_fragment"])
