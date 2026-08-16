"""Unit tests for isolated Open US Law Dataset/Bucket staging (OUL-041).

Acceptance:

* The identical candidate is uploaded additively to an explicit non-default
  dataset revision and a unique bucket staging prefix after a reviewed
  dry-run plan.
* Raw bucket-root objects are untouched.
* Every remote object identity is recorded.
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
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "stage_open_us_law_hf_release.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_upload.json"
)
_CANDIDATE_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "release_candidate.json"
)
_PRODUCER_PATHS = (
    _CANDIDATE_PATH,
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "bucket_snapshot.json",
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "processors"
    / "legal_data"
    / "open_us_law_publication_gate.py",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing staging CLI: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "stage_open_us_law_hf_release_oul041",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def receipt(cli: ModuleType) -> dict[str, Any]:
    payload, path = cli.materialize_default_receipt()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["receipt_sha256"] == payload["receipt_sha256"]
    assert on_disk["manifest_digest"] == payload["manifest_digest"]
    return payload


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(cli: ModuleType) -> None:
    assert cli.main(["--help"]) == 0


def test_fixture_receipt_acceptance(receipt: dict[str, Any], cli: ModuleType) -> None:
    result = cli.check_staging_receipt(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-041"
    assert result["goal_id"] == "OUL-G070"
    assert result["publication_authorized"] is False
    assert result["live_network"] is False
    assert result["mismatches"] == []
    assert result["raw_bucket_root_untouched"] is True
    assert len(result["dataset_revision"]) == 40
    assert result["bucket_staging_prefix"].startswith("releases/")
    assert result["bucket_staging_prefix"].endswith("/")
    assert result["remote_object_count"] > 0
    assert result["manifest_digest"]
    assert len(result["manifest_digest"]) == 64

    acceptance = receipt["acceptance"]
    assert acceptance["identical_candidate_uploaded"] is True
    assert acceptance["additive_upload"] is True
    assert acceptance["explicit_non_default_dataset_revision"] is True
    assert acceptance["unique_bucket_staging_prefix"] is True
    assert acceptance["reviewed_dry_run_plan"] is True
    assert acceptance["raw_bucket_root_untouched"] is True
    assert acceptance["every_remote_object_identity_recorded"] is True
    assert acceptance["pointer_not_updated"] is True
    assert acceptance["public_mutation_not_authorized"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == cli.ACCEPTANCE_CRITERIA


def test_identical_candidate_bytes(receipt: dict[str, Any], cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    inventory = dict((candidate.get("artifact_digests") or {}).get("inventory") or {})
    assert receipt["manifest_digest"] == candidate["candidate"]["manifest_digest"]
    assert receipt["candidate"]["receipt_sha256"] == candidate["receipt_sha256"]
    assert receipt["candidate"]["release_root_cid"] == candidate["candidate"][
        "release_root_cid"
    ]
    uploaded = {row["relative_path"]: row["sha256"] for row in receipt["remote_objects"]}
    assert set(inventory) <= set(uploaded)
    for path, digest in inventory.items():
        assert uploaded[path] == digest


def test_dataset_revision_is_explicit_non_default(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    revision = receipt["dataset_revision"]
    assert cli._GIT_SHA_RE.fullmatch(revision)
    assert revision.casefold() not in cli.PRODUCTION_REFS
    assert receipt["staging_branch"] == "stage/open-us-law-sparse-graphrag-v1"
    assert receipt["staging_branch"] not in {"main", "master", "latest"}
    assert receipt["target_repo"] == "justicedao/open-us-law-sparse-graphrag"


def test_bucket_prefix_is_unique_and_isolated(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    prefix = receipt["bucket_staging_prefix"]
    assert prefix == f"releases/{receipt['manifest_digest']}/"
    assert prefix != "LATEST.json"
    assert not prefix.startswith("us_")
    assert receipt["pointer_updated"] is False
    assert receipt["bucket_pointer_updated"] is False
    for row in receipt["remote_objects"]:
        bucket_path = row["bucket_object"]["path"]
        assert bucket_path.startswith(prefix)
        assert bucket_path != "LATEST.json"
        assert "/" in bucket_path
        assert not cli.is_protected_raw_root_path(bucket_path)


def test_every_remote_object_identity_is_recorded(receipt: dict[str, Any]) -> None:
    objects = receipt["remote_objects"]
    assert objects
    assert receipt["remote_object_count"] == len(objects) * 2
    seen_dataset: set[str] = set()
    seen_bucket: set[str] = set()
    for row in objects:
        dataset_id = row["dataset_object"]["object_id"]
        bucket_id = row["bucket_object"]["object_id"]
        assert dataset_id.startswith("dataset:")
        assert bucket_id.startswith("bucket:")
        assert row["sha256"] in dataset_id
        assert row["sha256"] in bucket_id
        assert row["dataset_object"]["revision"] == receipt["dataset_revision"]
        assert row["dataset_object"]["sha256"] == row["sha256"]
        assert row["bucket_object"]["sha256"] == row["sha256"]
        assert dataset_id not in seen_dataset
        assert bucket_id not in seen_bucket
        seen_dataset.add(dataset_id)
        seen_bucket.add(bucket_id)


def test_raw_bucket_root_objects_untouched(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    raw_root = cli.load_raw_root_snapshot()
    assert raw_root
    assert receipt["raw_bucket_root_untouched"] is True
    assert receipt["raw_bucket_root_object_count"] == len(raw_root)
    staged_bucket_paths = {
        row["bucket_object"]["path"] for row in receipt["remote_objects"]
    }
    assert staged_bucket_paths.isdisjoint(set(raw_root))
    assert "README.md" in raw_root
    assert "SHA256SUMS.json" in raw_root
    assert "LATEST.json" not in staged_bucket_paths


def test_apply_requires_reviewed_plan_digest(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate, dry_run=False)
    raw_root = cli.load_raw_root_snapshot()
    other = "0" * 64
    with pytest.raises(cli.StagePlanReviewError):
        cli.apply_stage_plan(
            plan, reviewed_plan_digest=other, raw_root_objects=raw_root
        )


def test_dry_run_does_not_mutate(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate, dry_run=True)
    receipt = cli.build_dry_run_receipt(plan)
    assert receipt["dry_run"] is True
    assert receipt["mutation_executed"] is False
    assert receipt["remote_write_contacted"] is False
    assert receipt["plan_digest"] == plan["plan_digest"]
    assert receipt["dataset_revision"] == plan["dataset_revision"]


def test_plan_then_apply_is_deterministic(cli: ModuleType) -> None:
    first = cli.build_default_staging_receipt()
    second = cli.build_default_staging_receipt()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["plan_digest"] == second["plan_digest"]
    assert first["dataset_revision"] == second["dataset_revision"]
    assert first["identities_digest"] == second["identities_digest"]
    assert first["remote_objects"] == second["remote_objects"]


def test_production_staging_branch_rejected(cli: ModuleType) -> None:
    for branch in ("main", "master", "refs/heads/main", "production", "live"):
        with pytest.raises(cli.StageProductionTargetError):
            cli.assert_non_production_staging_branch(branch)


def test_plan_rejects_main_without_seal(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    with pytest.raises(cli.StageProductionTargetError):
        cli.build_stage_plan(candidate, staging_branch="main")


def test_forbidden_operations_rejected(cli: ModuleType) -> None:
    for op in (
        "delete",
        "force_push",
        "force-push",
        "visibility_change",
        "make_private",
        "root_overwrite",
    ):
        with pytest.raises(cli.StageSafetyError):
            cli._assert_operations_add_only([op])


def test_plan_rejects_delete_operation_on_artifact(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate)
    plan["artifacts"][0] = dict(plan["artifacts"][0])
    plan["artifacts"][0]["operation"] = "delete"
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)


def test_visibility_change_rejected(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate)
    plan["visibility_change_allowed"] = True
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)
    plan = cli.build_stage_plan(candidate)
    plan["visibility"] = "private"
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)


def test_pointer_update_rejected_on_plan(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate)
    plan["pointer_updated"] = True
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)


def test_isolated_store_refuses_raw_root_and_pointer(cli: ModuleType) -> None:
    store = cli.IsolatedStagingStore({"README.md": "aa" * 32, "us_ak_statutes.parquet": "bb" * 32})
    with pytest.raises(cli.StageSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path="README.md",
            sha256="ab" * 32,
            size_bytes=1,
            content_cid="sha256:" + "ab" * 32,
        )
    with pytest.raises(cli.StageSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path="LATEST.json",
            sha256="ab" * 32,
            size_bytes=1,
            content_cid="sha256:" + "ab" * 32,
        )
    with pytest.raises(cli.StageSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path="us_ak_statutes.parquet",
            sha256="ab" * 32,
            size_bytes=1,
            content_cid="sha256:" + "ab" * 32,
        )


def test_isolated_store_is_additive(cli: ModuleType) -> None:
    store = cli.IsolatedStagingStore({"README.md": "aa" * 32})
    digest = "ab" * 32
    other = "cd" * 32
    prefix = f"releases/{'ef' * 32}/corpus/root"
    first = store.add_bucket(
        bucket_id="justicedao/open-us-law-bucket",
        path=prefix,
        sha256=digest,
        size_bytes=4,
        content_cid=f"sha256:{digest}",
    )
    again = store.add_bucket(
        bucket_id="justicedao/open-us-law-bucket",
        path=prefix,
        sha256=digest,
        size_bytes=4,
        content_cid=f"sha256:{digest}",
    )
    assert first["object_id"] == again["object_id"]
    with pytest.raises(cli.StageSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path=prefix,
            sha256=other,
            size_bytes=4,
            content_cid=f"sha256:{other}",
        )
    assert store.raw_root_untouched() is True


def test_publication_gate_authorizes_staging_and_refuses_pointer(
    cli: ModuleType,
) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate)
    decisions = cli.authorize_staging_operations(plan)
    assert decisions
    assert decisions[0]["operation"] == "dataset_additive_commit"
    assert decisions[0]["authorized"] is True
    assert decisions[0]["phase"] == "staging"
    bucket_ops = [row for row in decisions if row["operation"] == "bucket_release_prefix_write"]
    assert bucket_ops
    assert all(row["authorized"] is True for row in bucket_ops)
    pointer = [row for row in decisions if row["operation"] == "bucket_pointer_update_last"]
    assert pointer
    assert pointer[0]["authorized"] is False


def test_secrets_on_argv_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.SecretLeakError):
        cli.reject_secrets_in_argv(
            ["--hf_token=hf_secretvalue1234567890", "--dry-run"]
        )
    with pytest.raises(cli.SecretLeakError):
        cli.reject_secrets_in_argv(["Authorization: Bearer abc", "--apply"])


def test_credentials_in_payload_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.SecretLeakError):
        cli.reject_credentials_in_payload(
            {"plan_digest": "x", "hf_token": "hf_should_not_appear_here_12345"},
            label="test",
        )


def test_live_mutation_without_authorization_refused(cli: ModuleType) -> None:
    result = cli.refuse_live_mutation_without_authorization(authorize_mutation=False)
    assert result["mutation_authorized"] is False
    assert result["mutation_executed"] is False
    assert result["remote_write_contacted"] is False
    assert result["status"] == "mutation_refused"


def test_live_mutation_requires_env_authorization(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(cli.AUTHORIZATION_ENV, raising=False)
    with pytest.raises(cli.StageAuthorizationError):
        cli.assert_mutation_authorized(authorize_mutation=True)
    result = cli.refuse_live_mutation_without_authorization(authorize_mutation=True)
    assert result["mutation_authorized"] is False
    assert result["mutation_executed"] is False


def test_authorized_live_mutation_still_does_not_execute(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.AUTHORIZATION_ENV, "operator-staging-auth-fixture")
    result = cli.refuse_live_mutation_without_authorization(authorize_mutation=True)
    assert result["mutation_authorized"] is True
    assert result["mutation_executed"] is False
    assert result["remote_write_contacted"] is False
    assert result["status"] == "authorized_but_not_executed"


def test_receipt_has_no_absolute_local_paths_or_secrets(
    receipt: dict[str, Any], cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = json.dumps(receipt)
    assert "/home/" not in rendered
    assert "file://" not in rendered
    assert "hf_token" not in rendered.casefold()
    assert "bearer " not in rendered.casefold()
    monkeypatch.setenv(cli.AUTHORIZATION_ENV, "super-secret-auth-value-xyz")
    cli.reject_credentials_in_payload(receipt, label="receipt")
    assert "super-secret-auth-value-xyz" not in rendered


def test_main_check_receipt(cli: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    cli.materialize_default_receipt()
    rc = cli.main(["--check-receipt"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "OUL-041"
    assert payload["mismatches"] == []
    assert payload["raw_bucket_root_untouched"] is True


def test_main_dry_run(cli: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run_reviewed"
    assert payload["dry_run"] is True
    assert payload["mutation_executed"] is False
    assert payload["plan_digest"]
    assert payload["dataset_revision"]
    assert payload["bucket_staging_prefix"].startswith("releases/")


def test_main_apply_requires_reviewed_digest(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["--apply"])
    assert rc == 2
    err = capsys.readouterr().err.casefold()
    assert "reviewed" in err or "plan" in err


def test_main_apply_after_reviewed_plan(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate, dry_run=False)
    rc = cli.main(["--apply", "--reviewed-plan-digest", plan["plan_digest"]])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "staged_isolated"
    assert payload["mutation_executed"] is True
    assert payload["live_network"] is False
    assert payload["plan_digest"] == plan["plan_digest"]
    assert payload["raw_bucket_root_untouched"] is True


def test_main_rejects_production_branch(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["--dry-run", "--staging-branch", "main"])
    assert rc == 2
    err = capsys.readouterr().err.casefold()
    assert "production" in err or "main" in err


def test_check_receipt_detects_drift(cli: ModuleType, receipt: dict[str, Any]) -> None:
    tampered = copy.deepcopy(receipt)
    tampered["dataset_revision"] = "0" * 40
    tampered["receipt_sha256"] = cli.digest_mapping(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    with pytest.raises((cli.StaleInputError, cli.MismatchError)):
        cli.check_staging_receipt(tampered)


def test_plan_digest_binds_manifest_and_target(cli: ModuleType) -> None:
    candidate = cli.load_candidate_receipt()
    plan = cli.build_stage_plan(candidate)
    other = cli.build_stage_plan(
        candidate, staging_branch="stage/open-us-law-sparse-graphrag-alt"
    )
    assert plan["plan_digest"] != other["plan_digest"]
    assert plan["manifest_digest"] == other["manifest_digest"]
    assert plan["dataset_revision"] != other["dataset_revision"]
