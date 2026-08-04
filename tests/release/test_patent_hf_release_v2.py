"""Release tests: pinned Hub downloads and rollback for patent HF v2 (PATLAW-160).

Acceptance:

* Any missing/changed artifact, unpinned request, Viewer failure, or manifest
  mismatch blocks promotion.
* Successful receipt binds repository IDs, Hub SHA, release CID, all artifact
  hashes, and Viewer results.
* Rollback changes only the reviewed pointer and is itself pinned and
  verifiable.
* Default is dry-run; fake-live covers every gate offline without real tokens
  or network.

Validation:

    python -m pytest tests/release/test_patent_hf_release_v2.py -q
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    CANONICAL_REPOSITORY_NAMES,
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
    ArtifactChangedError,
    default_test_base_revisions,
    materialize_minimal_release_tree,
    new_ephemeral_operator_key,
    plan_stage_from_local_root,
    reject_credentials_in_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/verify_patent_hf_release_v2.py"
RUNBOOK = REPO_ROOT / "docs/operations/PATENT_HF_RELEASE_V2.md"
BASE_SHA = "0" * 40


def _load_verify_module():
    spec = importlib.util.spec_from_file_location(
        "verify_patent_hf_release_v2", VERIFY_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_mod = _load_verify_module()


@pytest.fixture
def release_tree(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "release"
    manifest = materialize_minimal_release_tree(root)
    return root, manifest


@pytest.fixture
def bases() -> dict[str, str]:
    return default_test_base_revisions(sha=BASE_SHA)


@pytest.fixture
def operator_key() -> bytes:
    return new_ephemeral_operator_key()


def _json_blob(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_credentials(payload: object) -> None:
    reject_credentials_in_payload(payload, label="test_receipt")
    text = _json_blob(payload)
    lowered = text.casefold()
    assert "bearer " not in lowered
    assert "password=" not in lowered
    assert "fake-operator-token" not in text
    assert not re.search(r"(?<![a-z0-9_-])hf_[A-Za-z0-9]{12,}", text)


# ---------------------------------------------------------------------------
# Declared outputs / policy identity
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert VERIFY_SCRIPT.is_file()
    assert RUNBOOK.is_file()
    assert Path(__file__).is_file()


def test_module_identity_and_gate_order() -> None:
    assert verify_mod.TASK_ID == "PATLAW-160"
    assert verify_mod.GOAL_ID == "PATLAW-G182"
    assert verify_mod.VERIFY_SCHEMA == "patent-legal-hf-verification-receipt/v2"
    assert verify_mod.POINTER_SCHEMA == "patent-legal-hf-runtime-pointer/v2"
    assert verify_mod.PINNED_SCHEMA == "patent-legal-hf-pinned-redownload/v2"
    assert verify_mod.ROLLBACK_SCHEMA == "patent-legal-hf-rollback-receipt/v2"
    assert "pinned_redownload" in verify_mod._GATE_ORDER
    assert "unpinned_request_blocked" in verify_mod._GATE_ORDER
    assert "viewer_contracts" in verify_mod._GATE_ORDER
    assert "rollback" in verify_mod._GATE_ORDER
    assert "rollback_verifiable" in verify_mod._GATE_ORDER
    # Pointer promotion must be gated after pin in the ordered sequence.
    assert verify_mod._GATE_ORDER.index("pointer_blocked_before_pin") < verify_mod._GATE_ORDER.index(
        "pinned_redownload"
    )
    assert verify_mod._GATE_ORDER.index("pinned_redownload") < verify_mod._GATE_ORDER.index(
        "canary_promotion"
    )
    assert verify_mod._GATE_ORDER.index("viewer_contracts") < verify_mod._GATE_ORDER.index(
        "canary_promotion"
    )


def test_runbook_documents_pin_and_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "PATLAW-160" in text
    assert "pinned" in text.casefold()
    assert "rollback" in text.casefold()
    assert "verify_patent_hf_release_v2" in text
    assert "viewer" in text.casefold()
    assert "canary" in text.casefold()
    assert "upload_file" in text


# ---------------------------------------------------------------------------
# Default dry-run
# ---------------------------------------------------------------------------


def test_default_is_dry_run(release_tree: tuple[Path, dict], bases: dict[str, str]) -> None:
    root, _ = release_tree
    sig = inspect.signature(verify_mod.verify_patent_hf_release_v2)
    assert sig.parameters["dry_run"].default is True
    assert sig.parameters["fake_live"].default is False

    result = verify_mod.verify_patent_hf_release_v2(
        local_root=root,
        base_revisions=bases,
    )
    assert result["status"] == "dry_run_only"
    assert result["dry_run"] is True
    assert result["fake_live"] is False
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert result["uses_hf_api_upload_file"] is False
    assert result["goal_id"] == "PATLAW-G182"
    assert result["task_id"] == "PATLAW-160"
    assert result["organization"] == ORGANIZATION
    assert result["release_root_cid"]
    assert result["plan_digest"]
    assert set(result["repository_ids"]) >= {
        f"{ORGANIZATION}/{name}" for name in CANONICAL_REPOSITORY_NAMES
    }
    assert result["receipt"]["schema_version"] == verify_mod.VERIFY_SCHEMA
    assert result["receipt"]["status"] == "dry_run_only"
    assert result["receipt"]["pointers_moved"] is False
    _assert_no_credentials(result)


def test_dry_run_never_contacts_api(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = release_tree
    for key in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
    ):
        monkeypatch.setenv(key, "should-never-be-read")

    result = verify_mod.verify_patent_hf_release_v2(
        local_root=root,
        base_revisions=bases,
    )
    assert result["status"] == "dry_run_only"
    assert result["tokens_used"] is False
    assert result["live_network"] is False
    _assert_no_credentials(result)


def test_cli_main_dry_run(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    code = verify_mod.main(
        [
            "--local-root",
            str(root),
            "--base-revisions-file",
            str(bases_path),
        ]
    )
    assert code == 0


# ---------------------------------------------------------------------------
# Fake-live happy path
# ---------------------------------------------------------------------------


def test_fake_live_covers_all_gates(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    cache = tmp_path / "verified-cache"
    result = verify_mod.verify_patent_hf_release_v2(
        local_root=root,
        base_revisions=bases,
        fake_live=True,
        dry_run=False,
        canary_percent=10,
        operator_key=operator_key,
        verified_cache_root=cache,
    )
    assert result["status"] == "fake_live_complete"
    assert result["fake_live"] is True
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert result["uses_hf_api_upload_file"] is False
    assert result["release_root_cid"]
    assert result["plan_digest"]
    assert result["repository_commits"]
    assert len(result["repository_commits"]) == len(CANONICAL_REPOSITORY_NAMES)

    gates = result["gates"]
    for name in verify_mod._GATE_ORDER:
        assert name in gates, f"missing gate {name}"
        assert gates[name].get("ok") is True, f"gate failed: {name} -> {gates[name]}"

    receipt = result["receipt"]
    assert receipt["schema_version"] == verify_mod.VERIFY_SCHEMA
    assert receipt["repository_ids"]
    assert receipt["repository_commits"] == result["repository_commits"]
    assert receipt["release_root_cid"] == result["release_root_cid"]
    assert receipt["artifact_hashes"]
    assert len(receipt["artifact_hashes"]) == len(receipt["artifact_pins"])
    assert receipt["pinned_redownload_digest"] == result["pinned_redownload_digest"]
    assert receipt["viewer"]["ok"] is True
    assert receipt["viewer"]["viewer_endpoints"]
    assert receipt["canary_pointer"]["canary_percent"] == 10
    assert receipt["rollback_receipt"]["only_pointer_changed"] is True
    assert receipt["rollback_receipt"]["failed_release_retained"] is True
    assert receipt["rollback_receipt"]["commits_deleted"] is False
    assert receipt["rollback_receipt"]["artifacts_deleted"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["rollback_receipt_digest"])
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["pinned_redownload_digest"])
    # Failed candidate retained as previous on restored pointer.
    assert (
        receipt["rollback_pointer"]["previous_release_id"]
        == receipt["canary_pointer"]["release_id"]
    )
    assert (
        receipt["rollback_pointer"]["release_id"]
        == receipt["canary_pointer"]["previous_release_id"]
    )
    _assert_no_credentials(result)
    summary = result.get("api_call_summary") or {}
    assert summary.get("upload_file", 0) == 0
    assert summary.get("delete_repo", 0) == 0
    assert summary.get("pinned_download", 0) > 0
    assert summary.get("pointer_write", 0) >= 1


def test_successful_receipt_binds_identities(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, manifest = release_tree
    result = verify_mod.verify_patent_hf_release_v2(
        local_root=root,
        base_revisions=bases,
        fake_live=True,
        operator_key=operator_key,
        verified_cache_root=tmp_path / "cache2",
    )
    receipt = result["receipt"]
    assert receipt["release_root_cid"] == manifest["release_root_cid"]
    for dataset_id, sha in receipt["repository_commits"].items():
        assert dataset_id.startswith(f"{ORGANIZATION}/")
        assert re.fullmatch(r"[0-9a-f]{40,64}", sha)
        assert sha != BASE_SHA  # advanced past audited base after promote
    for path, digest in receipt["artifact_hashes"].items():
        assert path
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
    for pin in receipt["artifact_pins"]:
        assert pin["commit_sha"] == receipt["repository_commits"][pin["dataset_id"]]
        assert pin["sha256"] == receipt["artifact_hashes"][pin["relative_path"]]
    assert "is-valid" in receipt["viewer"]["viewer_endpoints"]
    assert "splits" in receipt["viewer"]["viewer_endpoints"]


# ---------------------------------------------------------------------------
# Fail-closed: missing / changed / unpinned / viewer / manifest
# ---------------------------------------------------------------------------


def test_missing_local_artifact_blocks(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    victim = root.joinpath(*Path(plan.artifacts[0].relative_path).parts)
    victim.unlink()
    with pytest.raises((ArtifactChangedError, verify_mod.PatentHFReleaseVerifyV2Error)):
        verify_mod.assert_local_manifest_integrity(local_root=root, plan=plan)


def test_changed_local_artifact_blocks(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    victim = root.joinpath(*Path(plan.artifacts[0].relative_path).parts)
    victim.write_bytes(victim.read_bytes() + b"\xff-tampered")
    with pytest.raises(ArtifactChangedError):
        verify_mod.assert_local_manifest_integrity(local_root=root, plan=plan)


def test_changed_remote_artifact_blocks_pinned_redownload(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        PatentHFPublisherV2,
        create_operator_approval,
    )

    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-approval-corrupt",
    )
    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=operator_key,
        local_root=root,
    )
    commits = verify_mod.repository_commits_from_promotion(promoted)
    sample = plan.artifacts[0]
    api.corrupt_remote_file(
        dataset_id=sample.dataset_id,
        commit_sha=commits[sample.dataset_id],
        remote_path=sample.remote_path,
        body=b"CORRUPTED-REMOTE-BYTES",
    )
    with pytest.raises(verify_mod.PinnedRedownloadError):
        verify_mod.redownload_and_validate_pinned(
            plan=plan,
            repository_commits=commits,
            cache_root=tmp_path / "cache-corrupt",
            api=api,
            token=api.auth_token,
        )


def test_missing_remote_artifact_blocks_pinned_redownload(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        PatentHFPublisherV2,
        create_operator_approval,
    )

    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-approval-missing",
    )
    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=operator_key,
        local_root=root,
    )
    commits = verify_mod.repository_commits_from_promotion(promoted)
    sample = plan.artifacts[0]
    api.drop_remote_file(
        dataset_id=sample.dataset_id,
        commit_sha=commits[sample.dataset_id],
        remote_path=sample.remote_path,
    )
    with pytest.raises(verify_mod.PinnedRedownloadError):
        verify_mod.redownload_and_validate_pinned(
            plan=plan,
            repository_commits=commits,
            cache_root=tmp_path / "cache-missing",
            api=api,
            token=api.auth_token,
        )


def test_unpinned_revision_requests_are_blocked(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    # Seed a tree under main so a floating tip would otherwise find content.
    sample = plan.artifacts[0]
    api.ensure_repo(sample.dataset_id, head_sha=BASE_SHA)
    api._files[sample.dataset_id][BASE_SHA][sample.remote_path] = b"PAR1seed"
    for bad in ("main", "latest", "HEAD", ""):
        with pytest.raises(verify_mod.PinnedRedownloadError) as excinfo:
            api.hf_hub_download(
                repo_id=sample.dataset_id,
                filename=sample.remote_path,
                revision=bad,
                local_dir=tmp_path / f"bad-{bad or 'empty'}",
                token=api.auth_token,
            )
        assert "unpinned" in str(excinfo.value).casefold()


def test_pointer_promotion_blocked_without_pin(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        create_operator_approval,
    )

    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-approval-nopin",
    )
    commits = {ds: "a" * 40 for ds in plan.dataset_ids()}
    prev = verify_mod.previous_pointer_fixture(organization=ORGANIZATION)
    with pytest.raises(verify_mod.PointerPromotionError) as excinfo:
        verify_mod.canary_promote_pointer(
            plan=plan,
            repository_commits=commits,
            previous=prev,
            canary_percent=10,
            pinned=None,
            viewer_ok=True,
            approval=approval,
        )
    assert "pinned redownload" in str(excinfo.value)


def test_pointer_promotion_blocked_when_viewer_fails(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        PatentHFPublisherV2,
        create_operator_approval,
    )

    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-approval-viewer",
    )
    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=operator_key,
        local_root=root,
    )
    commits = verify_mod.repository_commits_from_promotion(promoted)
    pinned = verify_mod.redownload_and_validate_pinned(
        plan=plan,
        repository_commits=commits,
        cache_root=tmp_path / "cache-viewer",
        api=api,
        token=api.auth_token,
    )
    prev = verify_mod.previous_pointer_fixture(organization=ORGANIZATION)
    with pytest.raises(verify_mod.PointerPromotionError) as excinfo:
        verify_mod.canary_promote_pointer(
            plan=plan,
            repository_commits=commits,
            previous=prev,
            canary_percent=10,
            pinned=pinned,
            viewer_ok=False,
            approval=approval,
        )
    assert "Viewer" in str(excinfo.value)


def test_force_viewer_invalid_blocks_fake_live(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    with pytest.raises(verify_mod.ViewerVerifyError):
        verify_mod.verify_patent_hf_release_v2(
            local_root=root,
            base_revisions=bases,
            fake_live=True,
            operator_key=operator_key,
            verified_cache_root=tmp_path / "cache-force-viewer",
            force_viewer_invalid=True,
        )


def test_viewer_contracts_reject_invalid_service(
    release_tree: tuple[Path, dict],
) -> None:
    root, _ = release_tree
    with pytest.raises(verify_mod.ViewerVerifyError):
        verify_mod.verify_viewer_contracts(
            local_root=root, force_viewer_invalid=True
        )


def test_manifest_mismatch_blocks_plan(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    root, _ = release_tree
    manifest_path = root / "release-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Corrupt an artifact digest in the manifest while leaving file bytes alone.
    for entry in payload["artifacts"]:
        if entry["relative_path"].endswith(".parquet"):
            entry["sha256"] = "0" * 64
            break
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactChangedError):
        plan_stage_from_local_root(local_root=root, base_revisions=bases)


# ---------------------------------------------------------------------------
# Rollback invariants
# ---------------------------------------------------------------------------


def test_rollback_requires_previous_and_retains_evidence(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    result = verify_mod.verify_patent_hf_release_v2(
        local_root=root,
        base_revisions=bases,
        fake_live=True,
        operator_key=operator_key,
        verified_cache_root=tmp_path / "cache-rb",
    )
    canary = result["receipt"]["canary_pointer"]
    rolled = result["receipt"]["rollback_pointer"]
    rb = result["receipt"]["rollback_receipt"]

    assert rolled["release_id"] == canary["previous_release_id"]
    assert rolled["previous_release_id"] == canary["release_id"]
    assert rolled["repository_commits"] == canary["previous_repository_commits"]
    assert rb["only_pointer_changed"] is True
    assert rb["failed_release_retained"] is True
    assert rb["commits_deleted"] is False
    assert rb["artifacts_deleted"] is False
    # Rollback receipt is content-addressed (pinned/verifiable).
    from ipfs_datasets_py.huggingface.release import canonical_json_bytes

    digest = result["rollback_receipt_digest"]
    expected = sha256(canonical_json_bytes(rb)).hexdigest()
    assert digest == expected
    assert re.fullmatch(r"[0-9a-f]{64}", digest)

    # Explicit refuse delete-on-rollback.
    pointer = verify_mod.RuntimeReleasePointerV2(
        schema_version=verify_mod.POINTER_SCHEMA,
        pointer_path=verify_mod.DEFAULT_POINTER_PATH,
        organization=ORGANIZATION,
        release_id=canary["release_id"],
        release_root_cid=canary["release_root_cid"],
        repository_commits=canary["repository_commits"],
        canary_percent=10,
        previous_release_id=canary["previous_release_id"],
        previous_release_root_cid=canary["previous_release_root_cid"],
        previous_repository_commits=canary["previous_repository_commits"],
        pinned_redownload_digest=canary["pinned_redownload_digest"],
        viewer_ok=True,
        approval_id=canary["approval_id"],
        plan_digest=canary["plan_digest"],
    )
    with pytest.raises(verify_mod.RollbackError):
        verify_mod.rollback_pointer(
            current=pointer, failed_release_retained=False
        )


def test_rollback_without_previous_fails() -> None:
    pointer = verify_mod.RuntimeReleasePointerV2(
        schema_version=verify_mod.POINTER_SCHEMA,
        pointer_path=verify_mod.DEFAULT_POINTER_PATH,
        organization=ORGANIZATION,
        release_id="only-release",
        release_root_cid="bafyreionly",
        repository_commits={f"{ORGANIZATION}/patent-legal-corpus": "a" * 40},
        canary_percent=10,
    )
    with pytest.raises(verify_mod.RollbackError):
        verify_mod.rollback_pointer(current=pointer, failed_release_retained=True)


def test_non_empty_verified_cache_refused(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    root, _ = release_tree
    plan = plan_stage_from_local_root(local_root=root, base_revisions=bases)
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        PatentHFPublisherV2,
        create_operator_approval,
    )

    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=root)
    approval = create_operator_approval(
        plan=plan,
        operator_key=operator_key,
        approver="patent-legal-operator",
        approval_id="ops-approval-cache",
    )
    promoted = publisher.promote_approved(
        plan,
        staged=staged,
        approval=approval,
        operator_key=operator_key,
        local_root=root,
    )
    commits = verify_mod.repository_commits_from_promotion(promoted)
    dirty = tmp_path / "dirty-cache"
    dirty.mkdir()
    (dirty / "stale.bin").write_bytes(b"nope")
    with pytest.raises(verify_mod.PinnedRedownloadError) as excinfo:
        verify_mod.redownload_and_validate_pinned(
            plan=plan,
            repository_commits=commits,
            cache_root=dirty,
            api=api,
            token=api.auth_token,
        )
    assert "empty" in str(excinfo.value).casefold()


def test_publisher_still_refuses_pointer_promotion(
    release_tree: tuple[Path, dict],
    bases: dict[str, str],
) -> None:
    """PATLAW-159 publisher must not own pointer promotion (deferred to 160)."""

    from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
        FakeHubService,
        PatentHFPublisherV2,
        PatentHFPublisherV2Error,
    )

    api = FakeHubService(base_revisions=bases)
    publisher = PatentHFPublisherV2(api=api, token=api.auth_token)
    with pytest.raises(PatentHFPublisherV2Error) as excinfo:
        publisher.canary_promote_pointer()
    assert "PATLAW-160" in str(excinfo.value) or "verify_patent_hf_release_v2" in str(
        excinfo.value
    )
