"""Release tests: pinned Hub redownload of hub index projections (PATLAW-177).

Acceptance:

* Any missing/changed artifact, unpinned request, or manifest mismatch blocks.
* Successful receipt binds repository IDs, revision SHAs, package root CID, and
  every artifact digest by projection (corpus / BM25 / vector / graph).
* Default is dry-run; fake-service covers every gate offline without real
  tokens or network.
* Unpinned main/latest selection is forbidden.

Validation:

    python -m pytest tests/release/test_verify_patent_legal_hub_indexes.py -q
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    BM25_REPOSITORY,
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
    ArtifactChangedError,
    PatentHFPublisherV2,
    create_operator_approval,
    default_test_base_revisions,
    new_ephemeral_operator_key,
    reject_credentials_in_payload,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (
    INDEX_FAMILIES,
    package_patent_legal_hub_indexes,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/verify_patent_legal_hub_indexes.py"
STAGE_SCRIPT = REPO_ROOT / "scripts/ops/legal_data/stage_patent_legal_hub_indexes.py"
BASE_SHA = "0" * 40


def _load_verify_module():
    spec = importlib.util.spec_from_file_location(
        "verify_patent_legal_hub_indexes", VERIFY_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_mod = _load_verify_module()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def staged_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("hub-index-package")
    package_patent_legal_hub_indexes(
        default_fixture=True,
        stage=True,
        output_dir=root,
    )
    return root


@pytest.fixture
def package_copy(staged_package: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "package"
    shutil.copytree(staged_package, dest)
    return dest


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
    assert STAGE_SCRIPT.is_file()
    assert Path(__file__).is_file()


def test_module_identity_and_gate_order() -> None:
    assert verify_mod.TASK_ID == "PATLAW-177"
    assert verify_mod.GOAL_ID == "PATLAW-G213"
    assert (
        verify_mod.VERIFY_SCHEMA
        == "patent-legal-hub-index-verification-receipt/v1"
    )
    assert (
        verify_mod.PINNED_SCHEMA
        == "patent-legal-hub-index-pinned-redownload/v1"
    )
    assert tuple(verify_mod.PROJECTION_FAMILIES) == (
        "corpus",
        "bm25",
        "vectors",
        "knowledge_graph",
    )
    assert set(INDEX_FAMILIES) == {"bm25", "vectors", "knowledge_graph"}
    for name in (
        "dry_run_plan",
        "stage_and_promote",
        "pinned_redownload",
        "unpinned_request_blocked",
        "projection_coverage",
    ):
        assert name in verify_mod._GATE_ORDER
    assert verify_mod._GATE_ORDER.index("dry_run_plan") < verify_mod._GATE_ORDER.index(
        "pinned_redownload"
    )
    assert verify_mod._GATE_ORDER.index(
        "pinned_redownload"
    ) < verify_mod._GATE_ORDER.index("unpinned_request_blocked")
    assert verify_mod._GATE_ORDER.index(
        "unpinned_request_blocked"
    ) < verify_mod._GATE_ORDER.index("projection_coverage")


def test_list_projection_families_cli() -> None:
    code = verify_mod.main(["--list-projection-families"])
    assert code == 0


# ---------------------------------------------------------------------------
# Default dry-run
# ---------------------------------------------------------------------------


def test_default_is_dry_run(package_copy: Path, bases: dict[str, str]) -> None:
    sig = inspect.signature(verify_mod.verify_patent_legal_hub_indexes)
    assert sig.parameters["dry_run"].default is True
    assert sig.parameters["fake_live"].default is False
    assert sig.parameters["live"].default is False

    result = verify_mod.verify_patent_legal_hub_indexes(
        package_dir=package_copy,
        base_revisions=bases,
    )
    assert result["status"] == "dry_run_only"
    assert result["dry_run"] is True
    assert result["fake_live"] is False
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert result["uses_hf_api_upload_file"] is False
    assert result["goal_id"] == "PATLAW-G213"
    assert result["task_id"] == "PATLAW-177"
    assert result["organization"] == ORGANIZATION
    assert result["package_root_cid"]
    assert result["release_root_cid"]
    assert result["plan_digest"]
    assert set(result["repository_ids"]) >= {
        f"{ORGANIZATION}/{name}" for name in CANONICAL_REPOSITORY_NAMES
    }
    counts = result["projection_artifact_counts"]
    for family in verify_mod.PROJECTION_FAMILIES:
        assert counts.get(family, 0) >= 1, family
    digests = result["projection_digests"]
    for family in verify_mod.PROJECTION_FAMILIES:
        assert digests.get(family), family
        for path, digest in digests[family].items():
            assert path
            assert re.fullmatch(r"[0-9a-f]{64}", digest)
    receipt = result["receipt"]
    assert receipt["schema_version"] == verify_mod.VERIFY_SCHEMA
    assert receipt["status"] == "dry_run_only"
    assert receipt["main_published"] is False
    assert receipt["pointers_moved"] is False
    assert set(receipt["index_families_present"]) == set(INDEX_FAMILIES)
    _assert_no_credentials(result)


def test_dry_run_never_contacts_api(
    package_copy: Path,
    bases: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
    ):
        monkeypatch.setenv(key, "should-never-be-read")

    result = verify_mod.verify_patent_legal_hub_indexes(
        package_dir=package_copy,
        base_revisions=bases,
    )
    assert result["status"] == "dry_run_only"
    assert result["tokens_used"] is False
    assert result["live_network"] is False
    _assert_no_credentials(result)


def test_cli_main_dry_run(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    receipt_out = tmp_path / "receipt.json"
    code = verify_mod.main(
        [
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--receipt-out",
            str(receipt_out),
        ]
    )
    assert code == 0
    assert receipt_out.is_file()
    payload = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run_only"
    assert payload["task_id"] == "PATLAW-177"
    _assert_no_credentials(payload)


# ---------------------------------------------------------------------------
# Fake-live happy path
# ---------------------------------------------------------------------------


def test_fake_live_covers_all_gates(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    cache = tmp_path / "verified-cache"
    result = verify_mod.verify_patent_legal_hub_indexes(
        package_dir=package_copy,
        base_revisions=bases,
        fake_live=True,
        dry_run=False,
        operator_key=operator_key,
        verified_cache_root=cache,
    )
    assert result["status"] == "fake_live_complete"
    assert result["fake_live"] is True
    assert result["live_network"] is False
    assert result["tokens_used"] is False
    assert result["uses_hf_api_upload_file"] is False
    assert result["package_root_cid"]
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
    assert receipt["package_root_cid"] == result["package_root_cid"]
    assert receipt["release_root_cid"] == result["release_root_cid"]
    assert receipt["artifact_hashes"]
    assert len(receipt["artifact_hashes"]) == len(receipt["artifact_pins"])
    assert receipt["pinned_redownload_digest"] == result["pinned_redownload_digest"]
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["pinned_redownload_digest"])

    # Multi-projection binding: every family has digests + counts.
    for family in verify_mod.PROJECTION_FAMILIES:
        assert receipt["projection_artifact_counts"].get(family, 0) >= 1, family
        assert receipt["projection_digests"].get(family), family
    for pin in receipt["artifact_pins"]:
        assert pin["family"] in verify_mod.PROJECTION_FAMILIES
        assert pin["commit_sha"] == receipt["repository_commits"][pin["dataset_id"]]
        assert pin["sha256"] == receipt["artifact_hashes"][pin["relative_path"]]
        assert (
            receipt["projection_digests"][pin["family"]][pin["relative_path"]]
            == pin["sha256"]
        )

    # Canonical repos all present.
    repos_seen = {pin["repository"] for pin in receipt["artifact_pins"]}
    for repo in (
        CORPUS_REPOSITORY,
        BM25_REPOSITORY,
        VECTORS_REPOSITORY,
        KNOWLEDGE_GRAPH_REPOSITORY,
    ):
        assert repo in repos_seen, repo

    _assert_no_credentials(result)
    summary = result.get("api_call_summary") or {}
    assert summary.get("upload_file", 0) == 0
    assert summary.get("delete_repo", 0) == 0
    assert summary.get("pinned_download", 0) > 0


def test_successful_receipt_binds_identities(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    result = verify_mod.verify_patent_legal_hub_indexes(
        package_dir=package_copy,
        base_revisions=bases,
        fake_live=True,
        operator_key=operator_key,
        verified_cache_root=tmp_path / "cache2",
    )
    receipt = result["receipt"]
    assert receipt["package_root_cid"] == result["package_root_cid"]
    assert receipt["release_root_cid"] == result["release_root_cid"]
    for dataset_id, sha in receipt["repository_commits"].items():
        assert dataset_id.startswith(f"{ORGANIZATION}/")
        assert re.fullmatch(r"[0-9a-f]{40,64}", sha)
        assert sha != BASE_SHA  # advanced past audited base after promote
    for path, digest in receipt["artifact_hashes"].items():
        assert path
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
    # Projection digests cover every artifact hash entry by family.
    flat = {
        path: digest
        for family_map in receipt["projection_digests"].values()
        for path, digest in family_map.items()
    }
    assert flat == receipt["artifact_hashes"]


def test_cli_main_fake_live(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    bases_path = tmp_path / "bases.json"
    bases_path.write_text(json.dumps(bases), encoding="utf-8")
    cache = tmp_path / "cli-cache"
    receipt_out = tmp_path / "fake-receipt.json"
    code = verify_mod.main(
        [
            "--package-dir",
            str(package_copy),
            "--base-revisions-file",
            str(bases_path),
            "--fake-service",
            "--verified-cache-root",
            str(cache),
            "--receipt-out",
            str(receipt_out),
        ]
    )
    assert code == 0
    payload = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert payload["status"] == "fake_live_complete"
    assert payload["pinned_redownload_digest"]
    _assert_no_credentials(payload)


# ---------------------------------------------------------------------------
# Fail-closed: missing / changed / unpinned / live
# ---------------------------------------------------------------------------


def test_missing_local_artifact_blocks(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    plan, _, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    victim = package_copy.joinpath(*Path(plan.artifacts[0].relative_path).parts)
    victim.unlink()
    with pytest.raises((ArtifactChangedError, verify_mod.HubIndexVerifyError)):
        verify_mod.assert_local_manifest_integrity(
            local_root=package_copy, plan=plan
        )


def test_changed_local_artifact_blocks(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    plan, _, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    victim = package_copy.joinpath(*Path(plan.artifacts[0].relative_path).parts)
    victim.write_bytes(victim.read_bytes() + b"\xff-tampered")
    with pytest.raises(ArtifactChangedError):
        verify_mod.assert_local_manifest_integrity(
            local_root=package_copy, plan=plan
        )


def test_changed_remote_artifact_blocks_pinned_redownload(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    plan, release_manifest, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)
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
        local_root=package_copy,
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
            package_root_cid=str(release_manifest["package_root_cid"]),
        )


def test_missing_remote_artifact_blocks_pinned_redownload(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    plan, release_manifest, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)
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
        local_root=package_copy,
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
            package_root_cid=str(release_manifest["package_root_cid"]),
        )


def test_unpinned_revision_requests_are_blocked(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    plan, _, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
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


def test_assert_unpinned_requests_blocked_helper(
    package_copy: Path,
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    plan, _, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    result = verify_mod.assert_unpinned_requests_blocked(
        api=api,
        plan=plan,
        repository_commits={ds: BASE_SHA for ds in plan.dataset_ids()},
        cache_root=tmp_path / "unpinned-probe",
        token=api.auth_token,
    )
    assert result["ok"] is True
    assert "main" in result["blocked_revisions"] or "<empty>" in result["blocked_revisions"]
    assert "latest" in result["blocked_revisions"]


def test_live_mode_refused_without_injected_api(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    with pytest.raises(verify_mod.LiveNetworkRefusedError):
        verify_mod.verify_patent_legal_hub_indexes(
            package_dir=package_copy,
            base_revisions=bases,
            live=True,
        )


def test_non_empty_verified_cache_blocks(
    package_copy: Path,
    bases: dict[str, str],
    operator_key: bytes,
    tmp_path: Path,
) -> None:
    plan, release_manifest, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    api = verify_mod.DownloadCapableFakeHub(base_revisions=bases)
    publisher = PatentHFPublisherV2(
        api=api, token=api.auth_token, organization=ORGANIZATION
    )
    staged = publisher.stage_pull_request(plan, local_root=package_copy)
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
        local_root=package_copy,
    )
    commits = verify_mod.repository_commits_from_promotion(promoted)
    dirty = tmp_path / "dirty-cache"
    dirty.mkdir()
    (dirty / "stale.bin").write_bytes(b"not-empty")
    with pytest.raises(verify_mod.PinnedRedownloadError):
        verify_mod.redownload_and_validate_pinned(
            plan=plan,
            repository_commits=commits,
            cache_root=dirty,
            api=api,
            token=api.auth_token,
            package_root_cid=str(release_manifest["package_root_cid"]),
        )


def test_plan_enumerates_all_projections(
    package_copy: Path,
    bases: dict[str, str],
) -> None:
    plan, release_manifest, _ = verify_mod.build_plan_from_package(
        package_dir=package_copy, base_revisions=bases
    )
    assert set(release_manifest["index_families_present"]) == set(INDEX_FAMILIES)
    counts = release_manifest["projection_artifact_counts"]
    for family in verify_mod.PROJECTION_FAMILIES:
        assert counts.get(family, 0) >= 1, family
    repos_seen = {item.repository for item in plan.artifacts}
    for repo in CANONICAL_REPOSITORY_NAMES:
        assert repo in repos_seen, repo
    rels = {item.relative_path for item in plan.artifacts}
    assert any(r.startswith("indexes/bm25/") for r in rels)
    assert any(r.startswith("indexes/vectors/") for r in rels)
    assert any(r.startswith("indexes/knowledge_graph/") for r in rels)
    assert any(r.startswith("indexes/corpus/") for r in rels)


def test_default_fixture_materializes(
    bases: dict[str, str],
    tmp_path: Path,
) -> None:
    result = verify_mod.verify_patent_legal_hub_indexes(
        default_fixture=True,
        stage_dir=tmp_path / "fixture-pkg",
        base_revisions=bases,
    )
    assert result["status"] == "dry_run_only"
    assert result["package_root_cid"]
    for family in verify_mod.PROJECTION_FAMILIES:
        assert result["projection_artifact_counts"].get(family, 0) >= 1
    _assert_no_credentials(result)
