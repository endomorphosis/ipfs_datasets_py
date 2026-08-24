"""Unit tests for the OUL-040 Open US Law release-candidate seal.

Acceptance:

* The candidate root binds the exact clean commit, full task and goal
  closure, source and rights receipts, bucket inventory root, build
  manifest, evaluation, all artifact digests, target IDs, and an
  expiry-bound prepublication policy.
* The receipt contains no secret or absolute path leak.
* The receipt never authorizes publication.
* A valid fixture candidate is independently reproducible.
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

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "seal_open_us_law_candidate.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "release_candidate.json"
)
_PRODUCER_PATHS = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "bucket_snapshot.json",
    _REPO_ROOT / "data" / "legal" / "open_us_law" / "source_admission.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "full_build.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "evaluation.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "reproducibility.json",
    _REPO_ROOT / "data" / "legal" / "open_us_law" / "publication_policy.schema.json",
    _REPO_ROOT / "docs" / "architecture" / "open_us_law_reindex.todo.md",
    _REPO_ROOT / "docs" / "architecture" / "open_us_law_reindex.objectives.md",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing sealer script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "seal_open_us_law_candidate_oul040",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seal() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def receipt(seal: ModuleType) -> dict[str, Any]:
    """Deterministic fixture receipt (also materializes the sealed report)."""

    payload, path = seal.materialize_default_receipt()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["receipt_sha256"] == payload["receipt_sha256"]
    assert on_disk["candidate"]["manifest_digest"] == payload["candidate"]["manifest_digest"]
    return payload


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(seal: ModuleType) -> None:
    assert seal.main(["--help"]) == 0


def test_fixture_receipt_acceptance(receipt: dict[str, Any], seal: ModuleType) -> None:
    result = seal.check_candidate_receipt(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-040"
    assert result["goal_id"] == "OUL-G070"
    assert result["publication_authorized"] is False
    assert result["network_required"] is False
    assert result["mismatches"] == []
    assert result["closure_complete"] is True
    assert result["clean_commit"] == seal.CLEAN_COMMIT
    assert len(result["clean_commit"]) == 40
    assert result["manifest_digest"]
    assert len(result["manifest_digest"]) == 64
    assert result["expires_at"] == seal.compute_expiry()
    assert result["dataset_repo_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert result["source_bucket"] == "justicedao/open-us-law-bucket"
    assert result["artifact_count"] > 0

    acceptance = receipt["acceptance"]
    assert acceptance["binds_clean_commit"] is True
    assert acceptance["binds_task_and_goal_closure"] is True
    assert acceptance["binds_source_and_rights_receipts"] is True
    assert acceptance["binds_bucket_inventory_root"] is True
    assert acceptance["binds_build_manifest"] is True
    assert acceptance["binds_evaluation"] is True
    assert acceptance["binds_all_artifact_digests"] is True
    assert acceptance["binds_target_ids"] is True
    assert acceptance["binds_expiry_bound_prepublication_policy"] is True
    assert acceptance["publication_not_authorized"] is True
    assert acceptance["independently_reproducible"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == seal.ACCEPTANCE_CRITERIA


def test_receipt_binds_required_surfaces(receipt: dict[str, Any], seal: ModuleType) -> None:
    assert receipt["schema"] == "ipfs_datasets_py/open-us-law-release-candidate@1"
    assert receipt["schema_version"] == "open-us-law-release-candidate/v1"
    assert receipt["task_id"] == "OUL-040"
    assert receipt["goal_id"] == "OUL-G070"
    assert receipt["program_id"] == "open-us-law-reindex-v1"
    assert receipt["producer"] == "seal_open_us_law_candidate.py"
    assert receipt["publication_authorized"] is False
    assert receipt["authorizing_for_publication"] is False
    assert receipt["network_required"] is False
    assert receipt["currentness_disclaimer"]
    assert receipt["depends_on"] == ["OUL-039"]
    assert receipt["jurisdiction_count"] == 51
    assert receipt["jurisdiction_codes"] == list(seal.EXACT_51_JURISDICTION_CODES)

    commit = receipt["clean_commit"]
    assert commit["sha"] == seal.CLEAN_COMMIT
    assert commit["kind"] == "exact_40_hex"
    assert commit["clean"] is True
    assert len(commit["sha"]) == 40

    candidate = receipt["candidate"]
    assert candidate["kind"] == "fixture_local"
    assert candidate["dataset_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert candidate["default_config"] == "state_statutes_exact_51"
    assert candidate["staging_branch"] == "stage/open-us-law-sparse-graphrag-v1"
    assert candidate["staging_branch"] not in {"main", "master"}
    assert len(candidate["manifest_digest"]) == 64
    assert candidate["release_root_cid"]
    assert candidate["vector_space_id"].startswith("gte-small@")

    closure = receipt["closure"]
    assert closure["complete"] is True
    task_ids = [row["task_id"] for row in closure["tasks"]["predecessors"]]
    assert task_ids == [f"OUL-{index:03d}" for index in range(0, 40)]
    assert all(row["status"] == "completed" for row in closure["tasks"]["predecessors"])
    assert all(row["sha256"] and len(row["sha256"]) == 64 for row in closure["tasks"]["predecessors"])
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
    ):
        assert required in goal_ids
    assert closure["goals"]["parent_goal"]["goal_id"] == "OUL-G070"

    source = receipt["source_receipts"]
    assert source["task_id"] == "OUL-002"
    assert source["jurisdiction_count"] == 51
    assert source["ok"] is True
    assert len(source["matrix_digest_sha256"]) == 64

    rights = receipt["rights_receipts"]
    assert rights["task_id"] == "OUL-002"
    assert rights["attribution_required"] is True
    assert rights["ok"] is True
    assert "government_edicts_doctrine" in rights["legal_bases"]

    bucket = receipt["bucket_inventory"]
    assert bucket["bucket_id"] == "justicedao/open-us-law-bucket"
    assert bucket["root"] == bucket["inventory_digest_sha256"]
    assert len(bucket["root"]) == 64
    assert bucket["object_count"] == 107
    assert bucket["bucket_is_mutable"] is True

    build = receipt["build_manifest"]
    assert build["task_id"] == "OUL-039"
    assert build["ok"] is True
    assert build["key_parity_ok"] is True
    assert build["release_manifest_digest"] == candidate["manifest_digest"]

    evaluation = receipt["evaluation"]
    assert evaluation["task_id"] == "OUL-037"
    assert evaluation["ok"] is True
    assert evaluation["evaluation_cid"]
    assert evaluation["production_searchable"] is False

    artifacts = receipt["artifact_digests"]
    assert artifacts["count"] == len(artifacts["inventory"])
    assert artifacts["count"] >= len(artifacts["release_artifacts"])
    assert artifacts["ok"] is True
    assert "corpus/root" in artifacts["inventory"]
    assert "bm25/index_root" in artifacts["inventory"]
    assert "vectors/root" in artifacts["inventory"]
    assert "graph/projection" in artifacts["inventory"]
    for path, digest in artifacts["inventory"].items():
        assert path
        assert len(digest) == 64

    targets = receipt["target_ids"]
    assert targets["dataset_repo_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert targets["source_bucket"] == "justicedao/open-us-law-bucket"
    assert targets["default_configuration"] == "state_statutes_exact_51"
    assert targets["bucket_release_prefix"].startswith("releases/")
    assert targets["dataset_query_identity"] == "exact_40_hex_commit"

    policy = receipt["prepublication_policy"]
    assert policy["publication_authorized"] is False
    assert policy["public_mutation_authorized"] is False
    assert policy["staging_upload_authorized"] is False
    assert policy["requires_reissue_after_expiry"] is True
    assert policy["ttl_seconds"] == seal.PREPUBLICATION_TTL_SECONDS
    assert policy["expires_at"] == seal.compute_expiry()
    assert policy["bound_clean_commit"] == seal.CLEAN_COMMIT
    assert policy["bound_manifest_digest"] == candidate["manifest_digest"]
    assert policy["bound_target_ids"]["dataset_repo_id"] == targets["dataset_repo_id"]
    assert policy["publication_policy"]["prepublication_seal_required_for_public"] is True
    assert policy["publication_policy"]["deletion_allowed"] is False


def test_sealed_receipt_on_disk_matches_fixture(
    receipt: dict[str, Any], seal: ModuleType
) -> None:
    assert _RECEIPT_PATH.is_file()
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    mismatches = seal.compare_receipts(receipt, on_disk)
    assert mismatches == []


def test_fixture_receipt_independently_reproducible(seal: ModuleType) -> None:
    first = seal.build_candidate_receipt()
    second = seal.build_candidate_receipt()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["candidate"]["manifest_digest"] == second["candidate"]["manifest_digest"]
    assert first["candidate"]["release_root_cid"] == second["candidate"]["release_root_cid"]
    assert first["digests"] == second["digests"]
    assert first["artifact_digests"]["inventory"] == second["artifact_digests"]["inventory"]
    assert first["prepublication_policy"]["expires_at"] == second["prepublication_policy"]["expires_at"]
    assert first["clean_commit"] == second["clean_commit"]


def test_check_cli_validates_frozen_receipt(seal: ModuleType, receipt: dict[str, Any]) -> None:
    assert _RECEIPT_PATH.is_file()
    assert seal.main(["--check"]) == 0


def test_missing_receipt_fails_check(seal: ModuleType, tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert seal.main(["--check", "--receipt", str(missing)]) == 1


def test_stale_receipt_fails_check(
    seal: ModuleType, receipt: dict[str, Any], tmp_path: Path
) -> None:
    stale = copy.deepcopy(receipt)
    stale["clean_commit"] = dict(stale["clean_commit"])
    stale["clean_commit"]["sha"] = "0" * 40
    stale["receipt_sha256"] = seal.digest_mapping(
        {key: value for key, value in stale.items() if key != "receipt_sha256"}
    )
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(stale, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert seal.main(["--check", "--receipt", str(path)]) == 1


def test_missing_evidence_fails_closed(seal: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(seal.MissingInputError):
        seal.build_candidate_receipt(repo_root=tmp_path)


def test_incomplete_predecessor_closure_fails(
    seal: ModuleType, receipt: dict[str, Any]
) -> None:
    broken = copy.deepcopy(receipt)
    broken["closure"]["complete"] = False
    broken["acceptance"]["binds_task_and_goal_closure"] = False
    with pytest.raises(seal.CandidateSealError):
        seal.check_receipt_structure(broken)


def test_publication_authorization_is_rejected(
    seal: ModuleType, receipt: dict[str, Any]
) -> None:
    broken = copy.deepcopy(receipt)
    broken["publication_authorized"] = True
    with pytest.raises(seal.MismatchError):
        seal.check_receipt_structure(broken)


def test_prepublication_policy_must_expire_after_seal(seal: ModuleType) -> None:
    expires = seal.compute_expiry(
        sealed_at=seal.SEALED_AT,
        ttl_seconds=seal.PREPUBLICATION_TTL_SECONDS,
    )
    assert expires > seal.SEALED_AT
    assert expires == "2026-09-15T00:00:00Z"


def test_argv_secrets_are_rejected(seal: ModuleType) -> None:
    assert seal.main(["--check", "--receipt", "hf_token=hf_notarealtokenvalue"]) == 2


def test_receipt_has_no_secret_or_path_leak(
    receipt: dict[str, Any], seal: ModuleType
) -> None:
    seal.reject_credentials_in_payload(receipt, label="test")
    seal.reject_path_leaks(receipt, label="test")
    seal.reject_identity_contamination(receipt, label="test")
    dumped = json.dumps(receipt)
    assert "/home/" not in dumped
    assert "hf_" not in dumped
    assert "HF_TOKEN" not in dumped
