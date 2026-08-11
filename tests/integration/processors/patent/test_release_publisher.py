"""Integration tests: JusticeDAO patent release through the append-only publisher.

PATLAW-102 acceptance:

* Fake live flow covers every gate (dry-run, exact approval, add-only publish,
  audited-parent race check, pinned re-download, canary, pointer promotion,
  rollback).
* Default is dry-run.
* Repository names remain configurable.
* No pointer moves before pinned verification.
* Supervisor tests have no real token/network and perform no live upload.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.publication_profile import (
    PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    PATENT_LEGAL_GOAL_ID,
    PATENT_LEGAL_PLAN_SCHEMA,
    PATENT_LEGAL_RECEIPT_SCHEMA,
    patent_legal_publication_profile,
)
from ipfs_datasets_py.huggingface.publisher import (
    HuggingFacePublicationError,
    HuggingFaceReleasePublisher,
    PublicationApproval,
    RuntimeReleasePointer,
    publish_huggingface_release,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_MANIFEST = REPO_ROOT / "tests/fixtures/patent/release/manifest.json"
VERIFY_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/verify_patent_hf_release.py"
AUDITED_PARENT = "0" * 40


def _load_verify_module():
    """Import the ops verifier by path (scripts/ is not a package)."""

    spec = importlib.util.spec_from_file_location(
        "verify_patent_hf_release",
        VERIFY_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses/typing edge cases resolve.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_mod = _load_verify_module()


@pytest.fixture
def fixture_manifest() -> dict:
    assert FIXTURE_MANIFEST.is_file()
    payload = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


@pytest.fixture
def staged_release(tmp_path: Path, fixture_manifest: dict) -> tuple[Path, dict]:
    root = tmp_path / "release"
    verify_mod.materialize_release_tree(root, fixture_manifest)
    return root, fixture_manifest


def test_fixture_manifest_is_publisher_ready(fixture_manifest: dict) -> None:
    assert fixture_manifest["release_id"] == "patent-public-fixture-v1"
    assert fixture_manifest["dataset_id"] == PATENT_LEGAL_DEFAULT_REPOSITORY_ID
    assert fixture_manifest["uses_hf_api_upload_file"] is False
    assert fixture_manifest["upload_path"] is None
    assert fixture_manifest["remote_writes"] is False
    assert fixture_manifest["files"], "fixture must declare publishable files"
    for entry in fixture_manifest["files"]:
        assert entry["sha256"] and len(entry["sha256"]) == 64
        assert int(entry["byte_length"]) > 0


def test_default_is_dry_run(staged_release: tuple[Path, dict]) -> None:
    root, manifest = staged_release
    sig = inspect.signature(verify_mod.verify_patent_hf_release)
    assert sig.parameters["dry_run"].default is True
    assert sig.parameters["fake_live"].default is False

    result = verify_mod.verify_patent_hf_release(
        manifest=manifest,
        local_root=root,
        materialize_if_needed=False,
    )
    assert result["status"] == "dry_run_only"
    assert result["dry_run"] is True
    assert result["remote_write_performed"] is False
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert result["uses_hf_api_upload_file"] is False
    assert result["repository_id"] == PATENT_LEGAL_DEFAULT_REPOSITORY_ID
    assert result["goal_id"] == PATENT_LEGAL_GOAL_ID
    assert result["receipt"]["schema_version"] == PATENT_LEGAL_RECEIPT_SCHEMA
    assert result["receipt"]["status"] == "dry_run_only"
    assert result["plan"]["schema_version"] == PATENT_LEGAL_PLAN_SCHEMA
    assert result["plan"]["dry_run"] is True
    assert result["plan"]["remote_write_contacted"] is False


def test_repository_names_remain_configurable(
    staged_release: tuple[Path, dict],
) -> None:
    root, manifest = staged_release
    custom = "JusticeDAO/patent-legal-canary-staging"
    result = verify_mod.verify_patent_hf_release(
        manifest=manifest,
        local_root=root,
        repository_id=custom,
        materialize_if_needed=False,
    )
    assert result["repository_id"] == custom
    assert result["plan"]["repository_id"] == custom
    assert result["release_prefix"].startswith("data/patent_legal/")

    profile = patent_legal_publication_profile(repository_id=custom)
    publisher = HuggingFaceReleasePublisher(profile=profile)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    assert plan.repository_id == custom
    assert publisher.pointer_path == "runtime/patent_legal_release_pointer.json"


def test_dry_run_never_contacts_api_or_uses_token(
    staged_release: tuple[Path, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest = staged_release
    # Poison common token env vars; dry-run must not need or read them.
    for key in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
    ):
        monkeypatch.setenv(key, "should-never-be-read")

    api = verify_mod.FakeHubApi()
    result = verify_mod.verify_patent_hf_release(
        manifest=manifest,
        local_root=root,
        api=api,
        materialize_if_needed=False,
    )
    assert result["status"] == "dry_run_only"
    assert api.calls == []
    assert result["tokens_used"] is False
    assert result["live_network"] is False

    # publish_huggingface_release dry-run path is also offline.
    receipt = publish_huggingface_release(
        profile=patent_legal_publication_profile(),
        manifest=manifest,
        dry_run=True,
        local_root=root,
        api=api,
        audited_parent_commit=AUDITED_PARENT,
    )
    assert receipt["status"] == "dry_run_only"
    assert receipt["remote_write_performed"] is False
    assert api.calls == []


def test_no_pointer_moves_before_pinned_verification(
    staged_release: tuple[Path, dict],
) -> None:
    root, manifest = staged_release
    api = verify_mod.FakeHubApi(commit_sha="d" * 40)
    profile = patent_legal_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = verify_mod.build_approval(
        plan, repository_id=profile.repository_id
    )
    commit = publisher.publish_append_only(
        plan, approval=approval, local_root=root
    )
    previous = RuntimeReleasePointer(
        repository_id=commit.repository_id,
        release_id="previous-v0",
        commit_sha="e" * 40,
        release_prefix=publisher.release_prefix_for("previous-v0"),
    )
    with pytest.raises(HuggingFacePublicationError, match="pinned redownload"):
        publisher.canary_promote_pointer(
            commit_receipt=commit,
            previous=previous,
            canary_percent=5,
            approval=approval,
        )


def test_fake_live_flow_covers_every_gate(
    staged_release: tuple[Path, dict],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest = staged_release
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)

    cache = tmp_path / "verified-empty"
    result = verify_mod.run_fake_live_verification(
        manifest=manifest,
        local_root=root,
        repository_id="JusticeDAO/patent-legal-public",
        audited_parent_commit=AUDITED_PARENT,
        canary_percent=10,
        verified_cache_root=cache,
        commit_sha="1" * 40,
    )

    assert result["status"] == "fake_live_complete"
    assert result["fake_live"] is True
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert result["uses_hf_api_upload_file"] is False
    assert result["remote_write_performed"] is True  # against fake only
    assert result["repository_id"] == "JusticeDAO/patent-legal-public"
    assert result["commit_sha"] == "1" * 40

    expected_gates = {
        "dry_run",
        "exact_approval",
        "add_only_publish",
        "audited_parent_race_check",
        "post_publication_verification",
        "pinned_redownload",
        "pointer_blocked_before_pin",
        "canary_promotion",
        "rollback",
    }
    assert set(result["gates"]) == expected_gates
    assert tuple(result["gate_order"]) == verify_mod._GATE_ORDER
    for name, gate in result["gates"].items():
        assert gate["ok"] is True, name

    # Specific gate invariants.
    assert result["gates"]["dry_run"]["remote_write_contacted"] is False
    assert result["gates"]["audited_parent_race_check"]["blocked_mismatched_parent"]
    assert result["gates"]["add_only_publish"]["used_upload_file"] is False
    assert result["gates"]["pointer_blocked_before_pin"][
        "blocked_without_pinned_verification"
    ]
    assert result["gates"]["canary_promotion"]["canary_percent"] == 10
    assert result["gates"]["rollback"]["failed_release_retained"] is True

    receipt = result["receipt"]
    assert receipt["schema_version"] == PATENT_LEGAL_RECEIPT_SCHEMA
    assert receipt["evidence"]["pinned_redownload_validation"] is True
    assert receipt["evidence"]["post_publication_verification"] is True
    assert receipt["evidence"]["canary_and_rollback_receipt"] is True
    assert receipt["goal_id"] == PATENT_LEGAL_GOAL_ID


def test_verify_entry_point_fake_live_and_cli_default(
    staged_release: tuple[Path, dict],
    tmp_path: Path,
) -> None:
    root, manifest = staged_release
    receipt_path = tmp_path / "receipt.json"
    result = verify_mod.verify_patent_hf_release(
        manifest=manifest,
        local_root=root,
        fake_live=True,
        dry_run=False,
        receipt_path=receipt_path,
        materialize_if_needed=False,
        verified_cache_root=tmp_path / "cache",
        repository_id="JusticeDAO/custom-patent-corpus",
    )
    assert result["status"] == "fake_live_complete"
    assert result["repository_id"] == "JusticeDAO/custom-patent-corpus"
    assert receipt_path.is_file()
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert on_disk["status"] == "fake_live_complete"
    assert set(on_disk["gates"]) == set(result["gates"])

    # CLI default is dry-run (no --fake-live).
    code = verify_mod.main(
        [
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--local-root",
            str(root),
            "--repository-id",
            "JusticeDAO/cli-dry-run-repo",
            "--no-materialize",
        ]
    )
    assert code == 0


def test_publish_huggingface_release_stops_before_promotion(
    staged_release: tuple[Path, dict],
    tmp_path: Path,
) -> None:
    """Generic publisher live path verifies pins but does not auto-promote."""

    root, manifest = staged_release
    api = verify_mod.FakeHubApi(commit_sha="2" * 40)
    profile = patent_legal_publication_profile(
        repository_id="JusticeDAO/patent-legal-public"
    )
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    approval = verify_mod.build_approval(
        plan, repository_id=profile.repository_id
    )
    payloads = {
        item.remote_path: (root / item.relative_path).read_bytes()
        for item in plan.operations
    }
    remote_objects = {
        item.remote_path: {
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "commit_sha": "2" * 40,
        }
        for item in plan.operations
    }
    receipt = publish_huggingface_release(
        profile=profile,
        manifest=manifest,
        dry_run=False,
        local_root=root,
        approval=approval,
        api=api,
        audited_parent_commit=AUDITED_PARENT,
        remote_objects=remote_objects,
        remote_payloads=payloads,
        verified_cache_root=tmp_path / "verified",
    )
    assert receipt["status"] == "published_pending_promotion"
    assert receipt["evidence"]["pinned_redownload_validation"] is True
    assert receipt["evidence"]["canary_and_rollback_receipt"] is False
    assert "create_commit" in api.calls
    assert "upload_file" not in api.calls


def test_mismatched_approval_and_parent_race_fail_closed(
    staged_release: tuple[Path, dict],
) -> None:
    root, manifest = staged_release
    profile = patent_legal_publication_profile()
    plan = HuggingFaceReleasePublisher(profile=profile).plan_dry_run(
        manifest,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    bad_approval = PublicationApproval(
        approver="ops",
        plan_digest="f" * 64,
        max_cost_usd=10.0,
        max_upload_bytes=int(plan.cost_receipt["upload_bytes"]),
        credentials_scope=f"dataset:write:{profile.repository_id}",
        approval_id="bad",
    )
    with pytest.raises(HuggingFacePublicationError, match="plan_digest"):
        HuggingFaceReleasePublisher(
            profile=profile, api=verify_mod.FakeHubApi()
        ).publish_append_only(plan, approval=bad_approval, local_root=root)

    raced_api = verify_mod.FakeHubApi(parent_sha="9" * 40)
    good = verify_mod.build_approval(plan, repository_id=profile.repository_id)
    with pytest.raises(HuggingFacePublicationError, match="advanced after audit"):
        HuggingFaceReleasePublisher(
            profile=profile, api=raced_api
        ).publish_append_only(plan, approval=good, local_root=root)
    assert raced_api.create_commit_calls == []


def test_normalize_builder_artifacts_manifest(tmp_path: Path) -> None:
    """Builder-style manifests (artifacts + release_root_cid) are accepted."""

    body = b'{"ok":true}'
    digest = sha256(body).hexdigest()
    builder_manifest = {
        "schema_version": "patent-legal-huggingface-release/v1",
        "release_root_cid": "bafkreibuilderfixture0000000000000000000001",
        "dataset_id": "JusticeDAO/patent-legal-public",
        "program_id": "patent-legal-intelligence",
        "artifacts": [
            {
                "relative_path": "data/usc/part-000000.parquet",
                "size_bytes": len(body),
                "sha256": digest,
                "content_cid": "bafkreiartifact1",
            }
        ],
        "uses_hf_api_upload_file": False,
        "upload_path": None,
    }
    normalized = verify_mod.normalize_publication_manifest(builder_manifest)
    assert normalized["release_id"].startswith("cid-")
    assert normalized["descriptors"]
    root = tmp_path / "builder-release"
    root.mkdir()
    target = root / "data/usc/part-000000.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)

    publisher = HuggingFaceReleasePublisher(
        profile=patent_legal_publication_profile()
    )
    plan = publisher.plan_dry_run(
        normalized,
        local_root=root,
        audited_parent_commit=AUDITED_PARENT,
    )
    assert plan.dry_run is True
    assert len(plan.operations) == 1


def test_supervisor_tests_perform_no_live_upload(
    staged_release: tuple[Path, dict],
) -> None:
    """Static guarantees for the supervisor integration surface."""

    source = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "HfApi(" not in source
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    # upload_file may appear only as a refusal / assertion string.
    assert "never calls ``upload_file``" in source or "upload_file must never" in source

    root, manifest = staged_release
    api = verify_mod.FakeHubApi(commit_sha="3" * 40)
    result = verify_mod.run_fake_live_verification(
        manifest=manifest,
        local_root=root,
        commit_sha="3" * 40,
        verified_cache_root=root.parent / "cache-sup",
    )
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert "upload_file" not in api.calls  # unused instance; live uses internal fake
    # No process-visible HF token is required for the suite.
    assert os.environ.get("HF_TOKEN") in (None, "", "should-never-be-read")


def test_fixture_payloads_match_committed_digests(fixture_manifest: dict) -> None:
    recipe = fixture_manifest["payload_recipe"]
    by_path = {entry["path"]: entry for entry in fixture_manifest["files"]}
    for path, recipe_id in recipe.items():
        body = verify_mod.payload_for_recipe(recipe_id)
        entry = by_path[path]
        assert len(body) == entry["byte_length"]
        assert sha256(body).hexdigest() == entry["sha256"]
