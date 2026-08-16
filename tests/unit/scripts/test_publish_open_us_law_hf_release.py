"""Unit tests for the authorized Open US Law public Dataset/Bucket release (OUL-044).

Acceptance:

* After immediate gate revalidation, the exact staged bytes are committed
  to justicedao/open-us-law-sparse-graphrag.
* Those bytes are copied additively under releases/<manifest_sha256>/ in
  justicedao/open-us-law-bucket.
* A tiny pointer is updated last.
* No root raw object is overwritten and no deletion occurs.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    BUCKET_POINTER_PATH,
    PublicationGateDeniedError,
    evaluate_publication_gate,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "publish_open_us_law_hf_release.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "publication_receipt.json"
)
_SEAL_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "prepublication_seal.json"
)
_STAGING_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_upload.json"
)
_CANDIDATE_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "release_candidate.json"
)
_PRODUCER_PATHS = (
    _SEAL_PATH,
    _STAGING_PATH,
    _CANDIDATE_PATH,
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "bucket_snapshot.json",
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "processors"
    / "legal_data"
    / "open_us_law_publication_gate.py",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing publish CLI: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "publish_open_us_law_hf_release_oul044",
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


def _inputs(cli: ModuleType) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        cli.load_prepublication_seal(),
        cli.load_staging_receipt(),
        cli.load_candidate_receipt(),
    )


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(cli: ModuleType) -> None:
    assert cli.main(["--help"]) == 0


def test_fixture_receipt_acceptance(receipt: dict[str, Any], cli: ModuleType) -> None:
    result = cli.check_publication_receipt(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-044"
    assert result["goal_id"] == "OUL-G080"
    assert result["publication_authorized"] is True
    assert result["live_network"] is False
    assert result["mismatches"] == []
    assert result["raw_bucket_root_untouched"] is True
    assert result["pointer_updated_last"] is True
    assert result["deletion_occurred"] is False
    assert result["root_raw_object_overwritten"] is False
    assert len(result["dataset_revision"]) == 40
    assert result["bucket_release_prefix"].startswith("releases/")
    assert result["bucket_release_prefix"].endswith("/")
    assert result["remote_object_count"] > 0
    assert result["manifest_digest"]
    assert len(result["manifest_digest"]) == 64

    acceptance = receipt["acceptance"]
    assert acceptance["exact_staged_bytes_committed"] is True
    assert acceptance["additive_dataset_commit"] is True
    assert acceptance["additive_bucket_prefix_copy"] is True
    assert acceptance["bucket_prefix_is_releases_manifest_sha256"] is True
    assert acceptance["pointer_updated_last"] is True
    assert acceptance["no_root_raw_object_overwritten"] is True
    assert acceptance["no_deletion"] is True
    assert acceptance["immediate_gate_revalidation_before_each_callback"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == cli.ACCEPTANCE_CRITERIA


def test_exact_staged_bytes_committed(receipt: dict[str, Any], cli: ModuleType) -> None:
    staging = cli.load_staging_receipt()
    candidate = cli.load_candidate_receipt()
    inventory = dict((candidate.get("artifact_digests") or {}).get("inventory") or {})
    published = {row["relative_path"]: row["sha256"] for row in receipt["remote_objects"]}
    staged = {row["relative_path"]: row["sha256"] for row in staging["remote_objects"]}
    assert receipt["manifest_digest"] == staging["manifest_digest"]
    assert receipt["manifest_digest"] == candidate["candidate"]["manifest_digest"]
    assert set(inventory) <= set(published)
    assert published == staged
    for path, digest in inventory.items():
        assert published[path] == digest
        assert staged[path] == digest


def test_dataset_commit_to_authorized_repo(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    revision = receipt["dataset_revision"]
    assert cli._GIT_SHA_RE.fullmatch(revision)
    assert receipt["target_repo"] == AUTHORIZED_DATASET_REPO_ID
    assert receipt["authorized_dataset"] == AUTHORIZED_DATASET_REPO_ID
    assert receipt["dataset_created"] is True
    assert revision != receipt["staging_revision"]
    for row in receipt["remote_objects"]:
        dataset_obj = row["dataset_object"]
        assert dataset_obj["repo_id"] == AUTHORIZED_DATASET_REPO_ID
        assert dataset_obj["revision"] == revision
        assert dataset_obj["operation"] == "dataset_additive_commit"
        assert dataset_obj["sha256"] == row["sha256"]


def test_bucket_prefix_is_releases_manifest_sha256(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    prefix = receipt["bucket_release_prefix"]
    assert prefix == f"releases/{receipt['manifest_digest']}/"
    assert prefix == cli.release_prefix_for(receipt["manifest_digest"])
    for row in receipt["remote_objects"]:
        bucket_path = row["bucket_object"]["path"]
        assert bucket_path.startswith(prefix)
        assert bucket_path != BUCKET_POINTER_PATH
        assert not cli.is_protected_raw_root_path(bucket_path)
        assert row["bucket_object"]["bucket_id"] == AUTHORIZED_BUCKET_ID
        assert row["bucket_object"]["operation"] == "bucket_release_prefix_write"


def test_pointer_updated_last(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert receipt["pointer_updated"] is True
    assert receipt["pointer_updated_last"] is True
    assert receipt["bucket_pointer_updated"] is True
    assert receipt["prefix_complete"] is True
    assert receipt["prefix_redownload_verified"] is True
    pointer = receipt["pointer"]
    assert pointer["dataset_repo_id"] == AUTHORIZED_DATASET_REPO_ID
    assert pointer["source_bucket"] == AUTHORIZED_BUCKET_ID
    assert pointer["dataset_revision"] == receipt["dataset_revision"]
    assert pointer["bucket_prefix"] == receipt["bucket_release_prefix"]
    assert pointer["manifest_sha256"] == receipt["manifest_digest"]
    assert receipt["pointer_size_bytes"] <= cli.MAX_POINTER_BYTES
    assert receipt["pointer_object"]["path"] == BUCKET_POINTER_PATH
    assert receipt["pointer_object"]["operation"] == "bucket_pointer_update_last"

    revalidations = receipt["gate_revalidations"]
    assert revalidations
    assert revalidations[-1]["operation"] == "bucket_pointer_update_last"
    assert revalidations[-1]["revalidated"] is True
    assert revalidations[-1]["prefix_complete"] is True
    assert revalidations[-1]["prefix_redownload_verified"] is True
    assert revalidations[-1]["pointer_updated_last"] is True
    assert all(
        row["operation"] != "bucket_pointer_update_last" for row in revalidations[:-1]
    )
    ops = [row["operation"] for row in revalidations]
    assert ops[0] == "dataset_create"
    assert ops[1] == "dataset_additive_commit"
    assert "bucket_release_prefix_write" in ops


def test_no_root_raw_object_overwritten(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    raw_root = cli.load_raw_root_snapshot()
    assert raw_root
    assert receipt["raw_bucket_root_untouched"] is True
    assert receipt["root_raw_object_overwritten"] is False
    assert receipt["raw_bucket_root_object_count"] == len(raw_root)
    published_bucket_paths = {
        row["bucket_object"]["path"] for row in receipt["remote_objects"]
    }
    assert published_bucket_paths.isdisjoint(set(raw_root))
    assert "README.md" in raw_root
    assert "SHA256SUMS.json" in raw_root
    assert BUCKET_POINTER_PATH not in published_bucket_paths
    assert receipt["pointer_object"]["path"] == BUCKET_POINTER_PATH


def test_no_deletion(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert receipt["deletion_occurred"] is False
    store = cli.IsolatedPublicReleaseStore({"README.md": "aa" * 32})
    with pytest.raises(cli.PublishSafetyError):
        store.delete("README.md")
    assert store.deletion_occurred is True
    for op in ("delete", "delete_file", "sync_delete", "force_push"):
        with pytest.raises(cli.PublishSafetyError):
            cli._assert_operations_authorized([op])


def test_immediate_gate_revalidation_before_each_callback(
    receipt: dict[str, Any],
) -> None:
    revalidations = receipt["gate_revalidations"]
    expected = len(receipt["remote_objects"]) + 3
    assert receipt["gate_revalidation_count"] == expected
    assert len(revalidations) == expected
    for index, row in enumerate(revalidations, start=1):
        assert row["revalidated"] is True
        assert row["authorized"] is True
        assert row["phase"] == "public"
        assert row["sequence"] == index
        assert row["seal_sha256"] == receipt["seal_sha256"]


def test_every_remote_object_identity_is_recorded(receipt: dict[str, Any]) -> None:
    objects = receipt["remote_objects"]
    assert objects
    assert receipt["remote_object_count"] == len(objects) * 2 + 1
    seen_dataset: set[str] = set()
    seen_bucket: set[str] = set()
    for row in objects:
        dataset_id = row["dataset_object"]["object_id"]
        bucket_id = row["bucket_object"]["object_id"]
        assert dataset_id.startswith("dataset:")
        assert bucket_id.startswith("bucket:")
        assert row["sha256"] in dataset_id
        assert row["sha256"] in bucket_id
        assert dataset_id not in seen_dataset
        assert bucket_id not in seen_bucket
        seen_dataset.add(dataset_id)
        seen_bucket.add(bucket_id)
    pointer_id = receipt["pointer_object"]["object_id"]
    assert pointer_id.startswith("bucket:")
    assert BUCKET_POINTER_PATH in pointer_id
    assert pointer_id not in seen_bucket


def test_apply_requires_reviewed_plan_digest(cli: ModuleType) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(
        seal=seal, staging=staging, candidate=candidate, dry_run=False
    )
    raw_root = cli.load_raw_root_snapshot()
    other = "0" * 64
    with pytest.raises(cli.PublishPlanReviewError):
        cli.apply_publish_plan(
            plan,
            seal=seal,
            reviewed_plan_digest=other,
            raw_root_objects=raw_root,
        )


def test_dry_run_does_not_mutate(cli: ModuleType) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(
        seal=seal, staging=staging, candidate=candidate, dry_run=True
    )
    receipt = cli.build_dry_run_receipt(plan)
    assert receipt["dry_run"] is True
    assert receipt["mutation_executed"] is False
    assert receipt["remote_write_contacted"] is False
    assert receipt["pointer_updated"] is False
    assert receipt["plan_digest"] == plan["plan_digest"]
    assert receipt["dataset_revision"] == plan["dataset_revision"]


def test_plan_then_apply_is_deterministic(cli: ModuleType) -> None:
    first = cli.build_default_publication_receipt()
    second = cli.build_default_publication_receipt()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["plan_digest"] == second["plan_digest"]
    assert first["dataset_revision"] == second["dataset_revision"]
    assert first["identities_digest"] == second["identities_digest"]
    assert first["remote_objects"] == second["remote_objects"]
    assert first["pointer"] == second["pointer"]


def test_pointer_before_prefix_complete_refused(cli: ModuleType) -> None:
    store = cli.IsolatedPublicReleaseStore({"README.md": "aa" * 32})
    digest = "ab" * 32
    with pytest.raises(cli.PublishSafetyError):
        store.update_pointer(
            bucket_id=AUTHORIZED_BUCKET_ID,
            pointer={"schema": "x"},
            sha256=digest,
            size_bytes=32,
            content_cid=f"sha256:{digest}",
        )
    prefix = f"releases/{'ef' * 32}/corpus/root"
    store.add_bucket(
        bucket_id=AUTHORIZED_BUCKET_ID,
        path=prefix,
        sha256=digest,
        size_bytes=4,
        content_cid=f"sha256:{digest}",
    )
    store.mark_prefix_complete(expected_paths=[prefix])
    with pytest.raises(cli.PublishSafetyError):
        store.update_pointer(
            bucket_id=AUTHORIZED_BUCKET_ID,
            pointer={"schema": "x"},
            sha256=digest,
            size_bytes=32,
            content_cid=f"sha256:{digest}",
        )


def test_isolated_store_refuses_raw_root_and_early_pointer(cli: ModuleType) -> None:
    store = cli.IsolatedPublicReleaseStore(
        {"README.md": "aa" * 32, "us_ak_statutes.parquet": "bb" * 32}
    )
    digest = "ab" * 32
    with pytest.raises(cli.PublishSafetyError):
        store.add_bucket(
            bucket_id=AUTHORIZED_BUCKET_ID,
            path="README.md",
            sha256=digest,
            size_bytes=1,
            content_cid=f"sha256:{digest}",
        )
    with pytest.raises(cli.PublishSafetyError):
        store.add_bucket(
            bucket_id=AUTHORIZED_BUCKET_ID,
            path=BUCKET_POINTER_PATH,
            sha256=digest,
            size_bytes=1,
            content_cid=f"sha256:{digest}",
        )
    with pytest.raises(cli.PublishSafetyError):
        store.add_bucket(
            bucket_id=AUTHORIZED_BUCKET_ID,
            path="us_ak_statutes.parquet",
            sha256=digest,
            size_bytes=1,
            content_cid=f"sha256:{digest}",
        )


def test_isolated_store_is_additive_and_pointer_is_last(cli: ModuleType) -> None:
    store = cli.IsolatedPublicReleaseStore({"README.md": "aa" * 32})
    digest = "ab" * 32
    other = "cd" * 32
    prefix = f"releases/{'ef' * 32}/corpus/root"
    first = store.add_bucket(
        bucket_id=AUTHORIZED_BUCKET_ID,
        path=prefix,
        sha256=digest,
        size_bytes=4,
        content_cid=f"sha256:{digest}",
    )
    again = store.add_bucket(
        bucket_id=AUTHORIZED_BUCKET_ID,
        path=prefix,
        sha256=digest,
        size_bytes=4,
        content_cid=f"sha256:{digest}",
    )
    assert first["object_id"] == again["object_id"]
    with pytest.raises(cli.PublishSafetyError):
        store.add_bucket(
            bucket_id=AUTHORIZED_BUCKET_ID,
            path=prefix,
            sha256=other,
            size_bytes=4,
            content_cid=f"sha256:{other}",
        )
    store.mark_prefix_complete(expected_paths=[prefix])
    store.redownload_verify_prefix(
        expected=[
            {
                "bucket_id": AUTHORIZED_BUCKET_ID,
                "path": prefix,
                "sha256": digest,
            }
        ]
    )
    pointer = store.update_pointer(
        bucket_id=AUTHORIZED_BUCKET_ID,
        pointer={"schema": "tiny"},
        sha256=digest,
        size_bytes=32,
        content_cid=f"sha256:{digest}",
    )
    assert pointer["path"] == BUCKET_POINTER_PATH
    assert store.pointer_is_last() is True
    with pytest.raises(cli.PublishSafetyError):
        store.add_bucket(
            bucket_id=AUTHORIZED_BUCKET_ID,
            path=f"releases/{'ef' * 32}/extra",
            sha256=digest,
            size_bytes=4,
            content_cid=f"sha256:{digest}",
        )
    assert store.raw_root_untouched() is True


def test_publication_gate_authorizes_public_and_pointer_last(
    cli: ModuleType,
) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    create = evaluate_publication_gate(cli.dataset_create_request(plan))
    assert create.authorized is True
    assert create.operation == "dataset_create"
    assert create.phase == "public"
    commit = evaluate_publication_gate(cli.dataset_commit_request(plan))
    assert commit.authorized is True
    prefix = plan["bucket_release_prefix"]
    bucket = evaluate_publication_gate(
        cli.bucket_prefix_request(plan, f"{prefix}{plan['artifacts'][0]['relative_path']}")
    )
    assert bucket.authorized is True
    early_pointer = cli.pointer_update_request(plan)
    early_pointer["prefix_complete"] = False
    early_pointer["prefix_redownload_verified"] = False
    refused = evaluate_publication_gate(early_pointer)
    assert refused.authorized is False
    pointer = evaluate_publication_gate(cli.pointer_update_request(plan))
    assert pointer.authorized is True
    assert pointer.operation == "bucket_pointer_update_last"


def test_missing_or_stale_seal_refused(cli: ModuleType) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    request = cli.dataset_commit_request(plan)
    request["prepublication_seal"] = None
    request["sealed"] = False
    decision = evaluate_publication_gate(request)
    assert decision.authorized is False

    stale = copy.deepcopy(dict(seal))
    stale["manifest_digest"] = "0" * 64
    stale["final_manifest_digest"] = "0" * 64
    stale["gate_seal"]["final_manifest_digest"] = "0" * 64
    stale["gate_seal"]["manifest_digest"] = "0" * 64
    stale.pop("seal_sha256", None)
    stale["seal_sha256"] = cli.digest_mapping(
        {key: value for key, value in stale.items() if key != "seal_sha256"}
    )
    with pytest.raises(cli.PublishSealError):
        cli.revalidate_prepublication_seal(
            stale, expected_manifest=plan["manifest_digest"]
        )


def test_expired_seal_refused(cli: ModuleType) -> None:
    seal = cli.load_prepublication_seal()
    expired = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(cli.PublishSealError):
        cli.revalidate_prepublication_seal(seal, now=expired)


def test_post_hoc_seal_refused(cli: ModuleType) -> None:
    seal = dict(cli.load_prepublication_seal())
    seal["created_after_mutation"] = True
    seal["post_hoc"] = True
    with pytest.raises(cli.PublishSealError):
        cli.revalidate_prepublication_seal(seal)


def test_forbidden_operations_rejected(cli: ModuleType) -> None:
    for op in (
        "delete",
        "force_push",
        "force-push",
        "visibility_change",
        "root_overwrite",
        "sync_delete",
        "copy",
    ):
        with pytest.raises(cli.PublishSafetyError):
            cli._assert_operations_authorized([op])


def test_plan_rejects_delete_and_visibility(cli: ModuleType) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    plan["artifacts"][0] = dict(plan["artifacts"][0])
    plan["artifacts"][0]["operation"] = "delete"
    with pytest.raises(cli.PublishSafetyError):
        cli.assert_safe_publish_plan(plan)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    plan["visibility_change_allowed"] = True
    with pytest.raises(cli.PublishSafetyError):
        cli.assert_safe_publish_plan(plan)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    plan["legacy_files_deleted"] = True
    with pytest.raises(cli.PublishSafetyError):
        cli.assert_safe_publish_plan(plan)


def test_plan_requires_pointer_last(cli: ModuleType) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    plan["operations"] = [
        "dataset_create",
        "bucket_pointer_update_last",
        "dataset_additive_commit",
        "bucket_release_prefix_write",
    ]
    with pytest.raises(cli.PublishSafetyError):
        cli.assert_safe_publish_plan(plan)
    plan = cli.build_publish_plan(seal=seal, staging=staging, candidate=candidate)
    plan["pointer_updated_last"] = False
    with pytest.raises(cli.PublishSafetyError):
        cli.assert_safe_publish_plan(plan)


def test_mid_flight_seal_tamper_blocks_later_callback(cli: ModuleType) -> None:
    seal, staging, candidate = _inputs(cli)
    plan = cli.build_publish_plan(
        seal=seal, staging=staging, candidate=candidate, dry_run=False
    )
    store = cli.IsolatedPublicReleaseStore(cli.load_raw_root_snapshot())
    tampered = copy.deepcopy(dict(seal))
    tampered["publication_authorized"] = False

    def _callback(_decision: Any) -> str:
        return "should-not-run"

    summary, _result = cli.revalidate_gate_and_mutate(
        plan,
        cli.dataset_create_request(plan),
        lambda _decision: store.create_dataset(repo_id=plan["target_repo"]),
        seal=seal,
    )
    assert summary["revalidated"] is True
    with pytest.raises((cli.PublishSealError, PublicationGateDeniedError)):
        cli.revalidate_gate_and_mutate(
            plan,
            cli.dataset_commit_request(plan),
            _callback,
            seal=tampered,
        )


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
    with pytest.raises(cli.PublishAuthorizationError):
        cli.assert_mutation_authorized(authorize_mutation=True)
    result = cli.refuse_live_mutation_without_authorization(authorize_mutation=True)
    assert result["mutation_authorized"] is False
    assert result["mutation_executed"] is False


def test_authorized_live_mutation_still_does_not_execute(
    cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.AUTHORIZATION_ENV, "operator-publication-auth-fixture")
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


def test_pointer_is_tiny(receipt: dict[str, Any], cli: ModuleType) -> None:
    encoded = json.dumps(
        receipt["pointer"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded) == receipt["pointer_size_bytes"]
    assert len(encoded) <= cli.MAX_POINTER_BYTES
    assert len(json.dumps(receipt["pointer"])) < 1024


def test_main_check_receipt(cli: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    cli.materialize_default_receipt()
    rc = cli.main(["--check-receipt"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "OUL-044"
    assert payload["mismatches"] == []
    assert payload["raw_bucket_root_untouched"] is True
    assert payload["pointer_updated_last"] is True
    assert payload["deletion_occurred"] is False


def test_main_dry_run(cli: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run_reviewed"
    assert payload["dry_run"] is True
    assert payload["mutation_executed"] is False
    assert payload["pointer_updated"] is False
    assert payload["plan_digest"]
    assert payload["dataset_revision"]
    assert payload["bucket_release_prefix"].startswith("releases/")


def test_main_apply_requires_reviewed_digest(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["--apply"])
    assert rc == 2
    err = capsys.readouterr().err.casefold()
    assert "reviewed" in err or "plan" in err


def test_receipt_file_exists_after_materialize(receipt: dict[str, Any]) -> None:
    assert _RECEIPT_PATH.is_file()
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert on_disk["receipt_sha256"] == receipt["receipt_sha256"]
    assert on_disk["task_id"] == "OUL-044"
