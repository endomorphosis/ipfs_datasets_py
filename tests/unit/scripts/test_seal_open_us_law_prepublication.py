"""Unit tests for the OUL-043 Open US Law prepublication authorization seal.

Acceptance:

* The seal is created before mutation.
* It binds the exact candidate, staging revision, bucket prefix, current
  principal and write scope, task and goal closure including refill work,
  target IDs, operation set, and expiration.
* The receipt contains no secret or absolute path leak.
* A valid fixture seal is independently reproducible.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    AUTHORIZED_OPERATIONS,
    credentials_scope_for,
    evaluate_publication_gate,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "seal_open_us_law_prepublication.py"
)
_SEAL_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "prepublication_seal.json"
)
_PRODUCER_PATHS = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "release_candidate.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_upload.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_canary.json",
    _REPO_ROOT / "data" / "legal" / "open_us_law" / "source_admission.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "evaluation.json",
    _REPO_ROOT / "data" / "legal" / "open_us_law" / "publication_policy.schema.json",
    _REPO_ROOT / "docs" / "architecture" / "open_us_law_reindex.todo.md",
    _REPO_ROOT / "docs" / "architecture" / "open_us_law_reindex.objectives.md",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing sealer script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "seal_open_us_law_prepublication_oul043",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seal_mod() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def seal(seal_mod: ModuleType) -> dict[str, Any]:
    """Deterministic fixture seal (also materializes the sealed report)."""

    payload, path = seal_mod.materialize_default_seal()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["seal_sha256"] == payload["seal_sha256"]
    assert on_disk["manifest_digest"] == payload["manifest_digest"]
    return payload


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(seal_mod: ModuleType) -> None:
    assert seal_mod.main(["--help"]) == 0


def test_fixture_seal_acceptance(seal: dict[str, Any], seal_mod: ModuleType) -> None:
    result = seal_mod.check_prepublication_seal(seal)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-043"
    assert result["goal_id"] == "OUL-G080"
    assert result["publication_authorized"] is True
    assert result["mutation_executed"] is False
    assert result["network_required"] is False
    assert result["require_live_staging"] is True
    assert result["mismatches"] == []
    assert result["closure_complete"] is True
    assert result["refill_bound"] is True
    assert result["timing"] == "before_mutation"
    assert len(result["staging_revision"]) == 40
    assert result["bucket_prefix"].startswith("releases/")
    assert result["bucket_prefix"].endswith("/")
    assert result["manifest_digest"]
    assert len(result["manifest_digest"]) == 64
    assert result["expires_at"] == seal_mod.compute_expiry()
    assert result["dataset_repo_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert result["source_bucket"] == "justicedao/open-us-law-bucket"
    assert result["principal"] == "env:justicedao/open-us-law-sparse-graphrag"

    acceptance = seal["acceptance"]
    assert acceptance["created_before_mutation"] is True
    assert acceptance["binds_exact_candidate"] is True
    assert acceptance["binds_staging_revision"] is True
    assert acceptance["binds_bucket_prefix"] is True
    assert acceptance["binds_principal_and_write_scope"] is True
    assert acceptance["binds_task_and_goal_closure_including_refill_work"] is True
    assert acceptance["binds_target_ids"] is True
    assert acceptance["binds_operation_set"] is True
    assert acceptance["binds_expiration"] is True
    assert acceptance["public_mutation_not_executed"] is True
    assert acceptance["independently_reproducible"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == seal_mod.ACCEPTANCE_CRITERIA


def test_seal_binds_required_surfaces(seal: dict[str, Any], seal_mod: ModuleType) -> None:
    assert seal["schema"] == "ipfs_datasets_py/open-us-law-prepublication-seal@1"
    assert seal["schema_version"] == "open-us-law-prepublication-seal/v1"
    assert seal["task_id"] == "OUL-043"
    assert seal["goal_id"] == "OUL-G080"
    assert seal["program_id"] == "open-us-law-reindex-v1"
    assert seal["producer"] == "seal_open_us_law_prepublication.py"
    assert seal["publication_authorized"] is True
    assert seal["authorizing_for_publication"] is True
    assert seal["mutation_executed"] is False
    assert seal["public_mutation_executed"] is False
    assert seal["created_before_mutation"] is True
    assert seal["created_after_mutation"] is False
    assert seal["post_hoc"] is False
    assert seal["timing"] == "before_mutation"
    assert seal["seal_timing"] == "before_mutation"
    assert seal["present"] is True
    assert seal["required_for_staging"] is False
    assert seal["network_required"] is False
    assert seal["live_network"] is False
    assert seal["currentness_disclaimer"]
    assert seal["depends_on"] == ["OUL-007", "OUL-042"]

    commit = seal["clean_commit"]
    assert commit["kind"] == "exact_40_hex"
    assert commit["clean"] is True
    assert len(commit["sha"]) == 40
    assert seal_mod._GIT_SHA_RE.fullmatch(commit["sha"])

    candidate = seal["candidate"]
    assert candidate["task_id"] == "OUL-040"
    assert candidate["dataset_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert candidate["staging_branch"] == "stage/open-us-law-sparse-graphrag-v1"
    assert candidate["staging_branch"] not in {"main", "master"}
    assert len(candidate["manifest_digest"]) == 64
    assert candidate["release_root_cid"]
    assert candidate["receipt_sha256"]
    assert len(candidate["receipt_sha256"]) == 64


def test_seal_binds_live_staging_coordinates(
    seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    staging = seal_mod.load_staging_receipt()
    canary = seal_mod.load_canary_receipt()
    candidate = seal_mod.load_candidate_receipt()
    assert seal["staging_revision"] == staging["dataset_revision"]
    assert seal["staging_revision"] == canary["dataset_revision"]
    assert seal["bucket_prefix"] == staging["bucket_staging_prefix"]
    assert seal["bucket_prefix"] == canary["bucket_staging_prefix"]
    assert seal["manifest_digest"] == staging["manifest_digest"]
    assert seal["manifest_digest"] == candidate["candidate"]["manifest_digest"]
    assert seal_mod._GIT_SHA_RE.fullmatch(seal["staging_revision"])
    assert seal["staging_revision"].casefold() not in seal_mod.PRODUCTION_REFS
    assert seal["bucket_prefix"] == f"releases/{seal['manifest_digest']}/"
    assert seal["staging"]["staging_receipt_sha256"] == staging["receipt_sha256"]
    assert seal["staging"]["canary_receipt_sha256"] == canary["receipt_sha256"]
    assert seal["staging"]["require_live_staging"] is True
    assert seal["dataset_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert seal["bucket_id"] == "justicedao/open-us-law-bucket"


def test_seal_binds_principal_and_write_scope(seal: dict[str, Any]) -> None:
    principal = seal["principal"]
    assert principal["kind"] == "environment_credential"
    assert principal["identity"] == "env:justicedao/open-us-law-sparse-graphrag"
    assert principal["dataset_identity"] == "env:justicedao/open-us-law-sparse-graphrag"
    assert principal["bucket_identity"] == "env:justicedao/open-us-law-bucket"
    assert principal["credentials_environment_only"] is True
    assert principal["secret_redacted"] is True

    write_scope = seal["write_scope"]
    assert write_scope["dataset"] == credentials_scope_for(
        dataset_repo_id=AUTHORIZED_DATASET_REPO_ID
    )
    assert write_scope["bucket"] == credentials_scope_for(bucket_id=AUTHORIZED_BUCKET_ID)
    assert write_scope["dataset"] == "dataset:write:justicedao/open-us-law-sparse-graphrag"
    assert write_scope["bucket"] == "bucket:write:justicedao/open-us-law-bucket"
    assert set(write_scope["scopes"]) == {write_scope["dataset"], write_scope["bucket"]}


def test_seal_binds_task_and_goal_closure_including_refill(
    seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    closure = seal["closure"]
    assert closure["complete"] is True
    assert closure["includes_refill_work"] is True
    assert closure["refill_bound"] is True
    assert closure["generated_work_blocks_publication"] is False

    task_ids = [row["task_id"] for row in closure["tasks"]["predecessors"]]
    assert task_ids == [f"OUL-{index:03d}" for index in range(0, 43)]
    assert all(row["status"] == "completed" for row in closure["tasks"]["predecessors"])
    assert all(
        row["sha256"] and len(row["sha256"]) == 64
        for row in closure["tasks"]["predecessors"]
    )
    assert "OUL-007" in task_ids
    assert "OUL-040" in task_ids
    assert "OUL-041" in task_ids
    assert "OUL-042" in task_ids

    refill = closure["tasks"]["refill_work"]
    assert refill
    refill_ids = [row["task_id"] for row in refill]
    assert "OUL-049" in refill_ids
    assert all(row["task_id"].startswith("OUL-") for row in refill)
    assert all(int(row["task_id"].split("-")[1]) >= 49 for row in refill)
    publication_blockers = [
        row["task_id"]
        for row in refill
        if row["status"] != "completed" and not row.get("post_publication")
    ]
    assert publication_blockers == []

    goal_ids = [row["goal_id"] for row in closure["goals"]["predecessors"]]
    for required in (
        "OUL-G000",
        "OUL-G010",
        "OUL-G020",
        "OUL-G021",
        "OUL-G024",
        "OUL-G030",
        "OUL-G040",
        "OUL-G050",
        "OUL-G060",
        "OUL-G070",
    ):
        assert required in goal_ids
    assert closure["goals"]["parent_goal"]["goal_id"] == "OUL-G080"


def test_seal_binds_target_ids_and_operation_set(seal: dict[str, Any]) -> None:
    targets = seal["target_ids"]
    assert targets["dataset_repo_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert targets["source_bucket"] == "justicedao/open-us-law-bucket"
    assert targets["default_configuration"] == "state_statutes_exact_51"
    assert targets["bucket_release_prefix"] == seal["bucket_prefix"]
    assert targets["dataset_revision"] == seal["staging_revision"]
    assert targets["dataset_query_identity"] == "exact_40_hex_commit"
    assert targets["bucket_query_identity"] == "releases/<manifest_sha256>/"
    assert targets["staging_branch"] not in {"main", "master"}

    ops = seal["operation_set"]
    assert set(ops["authorized"]) == set(AUTHORIZED_OPERATIONS)
    assert "dataset_create" in ops["authorized"]
    assert "dataset_additive_commit" in ops["authorized"]
    assert "bucket_release_prefix_write" in ops["authorized"]
    assert "bucket_pointer_update_last" in ops["authorized"]
    assert "delete" in ops["forbidden"]
    assert "force_push" in ops["forbidden"]
    assert "history_rewrite" in ops["forbidden"]
    assert "visibility_change" in ops["forbidden"]
    assert "root_overwrite" in ops["forbidden"]
    assert set(ops["query"]) == {"dataset_query", "bucket_query"}


def test_seal_binds_expiration(seal: dict[str, Any], seal_mod: ModuleType) -> None:
    expiration = seal["expiration"]
    assert expiration["sealed_at"] == seal_mod.SEALED_AT
    assert expiration["ttl_seconds"] == seal_mod.PREPUBLICATION_TTL_SECONDS
    assert expiration["expires_at"] == seal_mod.compute_expiry()
    assert expiration["requires_reissue_after_expiry"] is True
    assert seal["expires_at"] == expiration["expires_at"]
    assert seal["ttl_seconds"] == expiration["ttl_seconds"]
    assert expiration["expires_at"] > seal_mod.SEALED_AT
    assert expiration["expires_at"] == "2026-09-15T00:00:00Z"


def test_source_rights_and_evaluation_are_bound(
    seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    source = seal["source_receipts"]
    assert source["task_id"] == "OUL-002"
    assert source["ok"] is True
    assert len(source["sha256"]) == 64
    rights = seal["rights_receipts"]
    assert rights["task_id"] == "OUL-002"
    assert rights["attribution_required"] is True
    assert rights["ok"] is True
    evaluation = seal["evaluation"]
    assert evaluation["task_id"] == "OUL-037"
    assert evaluation["ok"] is True
    assert evaluation["evaluation_cid"]
    policy = seal["publication_policy"]
    assert policy["prepublication_seal_required_for_public"] is True
    assert policy["pre_seal_writes_allowed"] is False
    assert policy["authorized_dataset"] == AUTHORIZED_DATASET_REPO_ID
    assert policy["authorized_bucket"] == AUTHORIZED_BUCKET_ID
    assert seal["publication_policy_digest"] == seal_mod.digest_mapping(policy)


def test_gate_seal_authorizes_public_mutation(
    seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    gate = seal_mod.as_gate_seal(seal)
    assert gate["present"] is True
    assert gate["timing"] == "before_mutation"
    assert gate["created_after_mutation"] is False
    assert gate["final_manifest_digest"] == seal["manifest_digest"]
    seal_mod.assert_gate_accepts_seal(seal)

    decision = evaluate_publication_gate(
        {
            "authorize_mutation": True,
            "argv": ["publish-open-us-law", "--phase", "public"],
            "bucket_id": AUTHORIZED_BUCKET_ID,
            "credential_identity": "env:justicedao/open-us-law-sparse-graphrag",
            "credentials_environment_only": True,
            "credentials_scope": credentials_scope_for(
                dataset_repo_id=AUTHORIZED_DATASET_REPO_ID
            ),
            "dataset_repo_id": AUTHORIZED_DATASET_REPO_ID,
            "final_manifest_digest": seal["manifest_digest"],
            "operation": "dataset_additive_commit",
            "payload": {
                "credentials_environment_only": True,
                "release_mode": "additive",
                "secret_redacted": True,
            },
            "phase": "public",
            "prepublication_seal": gate,
            "sealed": True,
            "secret_redacted": True,
        }
    )
    assert decision.authorized is True
    assert decision.network_mutation_permitted is True


def test_sealed_document_on_disk_matches_fixture(
    seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    assert _SEAL_PATH.is_file()
    on_disk = json.loads(_SEAL_PATH.read_text(encoding="utf-8"))
    mismatches = seal_mod.compare_seals(seal, on_disk)
    assert mismatches == []


def test_fixture_seal_independently_reproducible(seal_mod: ModuleType) -> None:
    first = seal_mod.build_prepublication_seal()
    second = seal_mod.build_prepublication_seal()
    assert first["seal_sha256"] == second["seal_sha256"]
    assert first["manifest_digest"] == second["manifest_digest"]
    assert first["staging_revision"] == second["staging_revision"]
    assert first["bucket_prefix"] == second["bucket_prefix"]
    assert first["expires_at"] == second["expires_at"]
    assert first["digests"] == second["digests"]
    assert first["principal"] == second["principal"]
    assert first["write_scope"] == second["write_scope"]
    assert first["operation_set"] == second["operation_set"]


def test_check_cli_validates_frozen_seal(seal_mod: ModuleType, seal: dict[str, Any]) -> None:
    assert _SEAL_PATH.is_file()
    assert seal_mod.main(["--require-live-staging", "--no-mutate", "--check"]) == 0


def test_no_mutate_rejects_write(seal_mod: ModuleType) -> None:
    assert seal_mod.main(["--write", "--no-mutate"]) == 2


def test_live_mutation_is_refused(seal_mod: ModuleType) -> None:
    assert seal_mod.main(["--live"]) == 2


def test_missing_seal_fails_check(seal_mod: ModuleType, tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert (
        seal_mod.main(
            ["--require-live-staging", "--no-mutate", "--check", "--seal", str(missing)]
        )
        == 1
    )


def test_stale_seal_fails_check(
    seal_mod: ModuleType, seal: dict[str, Any], tmp_path: Path
) -> None:
    stale = copy.deepcopy(seal)
    stale["staging_revision"] = "0" * 40
    stale["target_ids"] = dict(stale["target_ids"])
    stale["target_ids"]["dataset_revision"] = "0" * 40
    stale["gate_seal"] = dict(stale["gate_seal"])
    stale["gate_seal"]["dataset_revision"] = "0" * 40
    stale["seal_sha256"] = seal_mod.digest_mapping(
        {key: value for key, value in stale.items() if key != "seal_sha256"}
    )
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(stale, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert (
        seal_mod.main(
            ["--require-live-staging", "--no-mutate", "--check", "--seal", str(path)]
        )
        == 1
    )


def test_missing_evidence_fails_closed(seal_mod: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(seal_mod.MissingInputError):
        seal_mod.build_prepublication_seal(repo_root=tmp_path)


def test_incomplete_predecessor_closure_fails(
    seal_mod: ModuleType, seal: dict[str, Any]
) -> None:
    broken = copy.deepcopy(seal)
    broken["closure"]["complete"] = False
    broken["acceptance"]["binds_task_and_goal_closure_including_refill_work"] = False
    with pytest.raises(seal_mod.PrepublicationSealError):
        seal_mod.check_seal_structure(broken)


def test_missing_refill_work_fails(seal_mod: ModuleType, seal: dict[str, Any]) -> None:
    broken = copy.deepcopy(seal)
    broken["closure"]["includes_refill_work"] = False
    broken["closure"]["tasks"]["refill_work"] = []
    broken["closure"]["tasks"]["generated_tasks"] = []
    with pytest.raises(seal_mod.ClosureError):
        seal_mod.check_seal_structure(broken)


def test_post_hoc_seal_is_rejected(seal_mod: ModuleType, seal: dict[str, Any]) -> None:
    broken = copy.deepcopy(seal)
    broken["created_before_mutation"] = False
    broken["created_after_mutation"] = True
    broken["post_hoc"] = True
    broken["timing"] = "after_mutation"
    with pytest.raises(seal_mod.MismatchError):
        seal_mod.check_seal_structure(broken)


def test_executed_mutation_is_rejected(
    seal_mod: ModuleType, seal: dict[str, Any]
) -> None:
    broken = copy.deepcopy(seal)
    broken["mutation_executed"] = True
    with pytest.raises(seal_mod.MismatchError):
        seal_mod.check_seal_structure(broken)


def test_expiry_must_follow_sealed_at(seal_mod: ModuleType) -> None:
    expires = seal_mod.compute_expiry(
        sealed_at=seal_mod.SEALED_AT,
        ttl_seconds=seal_mod.PREPUBLICATION_TTL_SECONDS,
    )
    assert expires > seal_mod.SEALED_AT
    assert expires == "2026-09-15T00:00:00Z"


def test_argv_secrets_are_rejected(seal_mod: ModuleType) -> None:
    assert (
        seal_mod.main(
            [
                "--require-live-staging",
                "--no-mutate",
                "--check",
                "--seal",
                "hf_token=hf_notarealtokenvalue",
            ]
        )
        == 2
    )


def test_seal_has_no_secret_or_path_leak(
    seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    seal_mod.reject_credentials_in_payload(seal, label="test")
    seal_mod.reject_path_leaks(seal, label="test")
    seal_mod.reject_identity_contamination(seal, label="test")
    dumped = json.dumps(seal)
    assert "/home/" not in dumped
    assert "hf_" not in dumped
    assert "HF_TOKEN" not in dumped
    assert "OPEN_US_LAW_PUBLICATION_AUTHORIZATION" not in dumped
