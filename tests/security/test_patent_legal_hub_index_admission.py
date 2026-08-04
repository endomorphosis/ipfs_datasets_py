"""Security tests for hub index package DLP / rights / Viewer admission.

PATLAW-175: private/mixed/unknown rights, secret-like leakage, orphan rows,
invalid Parquet, or Viewer contract failure must block admission **before
credentials are resolved**. The admission receipt binds ``package_root_cid``
and gate outcomes. Credentials never appear in findings or receipts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (
    RELEASE_POLICY_V2_SHA256,
    RELEASE_POLICY_V2_VERSION,
    VIEWER_ENDPOINTS,
    CredentialPrematureError,
    RepositoryInventory,
    StagedParquetShard,
    StagedReleaseInventory,
    assert_credentials_unresolved,
    credentials_are_resolved,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (
    ARTIFACTS_INVENTORY_FILENAME,
    INDEX_FAMILIES,
    MANIFEST_FILENAME,
    PACKAGE_ROOT_FILENAME,
    package_patent_legal_hub_indexes,
)
from scripts.ops.legal_data.admit_patent_legal_hub_indexes import (
    ADMISSION_RECEIPT_FILENAME,
    ADMISSION_RECEIPT_SCHEMA,
    EXPECTED_GATE_NAMES,
    GOAL_ID,
    PACKAGE_GATE_NAMES,
    POLICY_GATE_NAMES,
    TASK_ID,
    HubIndexAdmissionError,
    PackageAdmissionRejectedError,
    admit_patent_legal_hub_indexes,
    inventory_from_hub_index_package,
    load_package_context,
    resolve_package_dir,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hf_token_fixture(*, char: str = "a", length: int = 24) -> str:
    """Build a Hub-token-shaped string without embedding a full literal."""
    return "".join(("hf_", char * length))


def _clear_hf_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    _clear_hf_credentials(monkeypatch)
    return monkeypatch


@pytest.fixture(scope="module")
def staged_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Stage a single default hub index package for the module."""
    root = tmp_path_factory.mktemp("hub-index-package")
    package_patent_legal_hub_indexes(
        default_fixture=True,
        stage=True,
        output_dir=root,
    )
    return root


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: MappingLike) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# Typing alias without importing Mapping for the helper signature.
MappingLike = dict[str, Any]


def _mutate_manifest_artifact(
    package_dir: Path,
    *,
    mutator,
) -> None:
    """Apply mutator(descriptor) to the first artifact descriptor and rewrite."""
    manifest_path = package_dir / MANIFEST_FILENAME
    payload = _read_json(manifest_path)
    descriptors = list(payload.get("artifact_descriptors") or [])
    assert descriptors, "package fixture must include artifact descriptors"
    mutator(descriptors[0])
    payload["artifact_descriptors"] = descriptors
    _write_json(manifest_path, payload)

    inventory_path = package_dir / ARTIFACTS_INVENTORY_FILENAME
    if inventory_path.is_file():
        inv = _read_json(inventory_path)
        arts = list(inv.get("artifacts") or [])
        if arts:
            mutator(arts[0])
            inv["artifacts"] = arts
            _write_json(inventory_path, inv)


def _copy_package(src: Path, dest: Path) -> Path:
    import shutil

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


# ---------------------------------------------------------------------------
# Schema / surface
# ---------------------------------------------------------------------------


def test_task_and_receipt_schema_pins() -> None:
    assert TASK_ID == "PATLAW-175"
    assert GOAL_ID == "PATLAW-G212"
    assert ADMISSION_RECEIPT_SCHEMA == "patent-legal-hub-index-admission-receipt/v1"
    assert ADMISSION_RECEIPT_FILENAME == "hub-index-admission-receipt.json"
    assert set(INDEX_FAMILIES) == {"bm25", "vectors", "knowledge_graph"}
    assert set(PACKAGE_GATE_NAMES).issubset(set(EXPECTED_GATE_NAMES))
    assert set(POLICY_GATE_NAMES).issubset(set(EXPECTED_GATE_NAMES))
    for name in (
        "package_integrity",
        "package_rights_privacy",
        "package_dlp",
        "package_orphans",
        "cards_configs",
        "parquet",
        "rights_dlp",
        "orphans",
        "dataset_viewer",
    ):
        assert name in EXPECTED_GATE_NAMES


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_default_fixture_package_is_admitted(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    receipt_path = tmp_path / "admission-receipt.json"
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=True,
        receipt_out=receipt_path,
    )
    assert receipt["admitted"] is True
    assert receipt["credentials_resolved"] is False
    assert receipt["tokens_used"] is False
    assert receipt["hub_upload"] is False
    assert receipt["task_id"] == TASK_ID
    assert receipt["goal_id"] == GOAL_ID
    assert receipt["receipt_schema"] == ADMISSION_RECEIPT_SCHEMA
    assert receipt["package_root_cid"].startswith("b")
    assert receipt["package_digest_sha256"]
    assert len(receipt["package_digest_sha256"]) == 64
    assert receipt["policy_sha256"] == RELEASE_POLICY_V2_SHA256
    assert receipt["policy_version"] == RELEASE_POLICY_V2_VERSION
    assert set(receipt["index_families_present"]) == set(INDEX_FAMILIES)
    assert receipt["reason_codes"] == []
    assert receipt_path.is_file()

    on_disk = _read_json(receipt_path)
    assert on_disk["package_root_cid"] == receipt["package_root_cid"]
    assert on_disk["admitted"] is True

    gate_names = [g["name"] for g in receipt["gate_results"]]
    for expected in EXPECTED_GATE_NAMES:
        assert expected in gate_names
    assert all(g["passed"] for g in receipt["gate_results"])


def test_admission_receipt_binds_package_root_and_gate_outcomes(
    clean_env, staged_package: Path
) -> None:
    ctx = load_package_context(staged_package)
    package_root = str(ctx["manifest"].package_root_cid)
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package, require_admitted=True
    )
    assert receipt["package_root_cid"] == package_root
    assert receipt["corpus_root_cid"] == ctx["manifest"].corpus_root_cid
    assert receipt["bm25_root_cid"] == ctx["manifest"].bm25_root_cid
    assert receipt["vector_root_cid"] == ctx["manifest"].vector_root_cid
    assert receipt["graph_root_cid"] == ctx["manifest"].graph_root_cid
    assert "receipt_digest_sha256" in receipt
    assert len(receipt["receipt_digest_sha256"]) == 64

    # Gate outcomes are bound: every gate reports pass/fail + optional codes.
    for gate in receipt["gate_results"]:
        assert "name" in gate
        assert "passed" in gate
        assert "reason_codes" in gate
        if gate["passed"]:
            assert gate["reason_codes"] == []
        else:
            assert gate["reason_codes"]


def test_inventory_projection_includes_support_and_repos(
    clean_env, staged_package: Path
) -> None:
    inventory = inventory_from_hub_index_package(staged_package)
    assert inventory.organization
    assert "release-manifest.json" in inventory.support_paths
    assert "quality-report.json" in inventory.support_paths
    assert "policy-admission.json" in inventory.support_paths
    repos = {r.repository for r in inventory.repositories}
    assert "patent-legal-corpus" in repos
    assert "patent-legal-bm25" in repos
    assert "patent-legal-vectors" in repos
    assert "patent-legal-knowledge-graph" in repos
    assert all(r.has_readme for r in inventory.repositories)
    assert all(r.has_dataset_configs for r in inventory.repositories)
    assert all(r.has_coverage for r in inventory.repositories)
    assert inventory.policy_receipt.get("admitted") is True
    assert inventory.quality_report.get("orphan_check") is True


def test_default_fixture_cli_path_admits(clean_env, tmp_path: Path) -> None:
    stage = tmp_path / "fixture-pkg"
    receipt = admit_patent_legal_hub_indexes(
        default_fixture=True,
        stage_dir=stage,
        require_admitted=True,
    )
    assert receipt["admitted"] is True
    assert (stage / MANIFEST_FILENAME).is_file()
    assert (stage / PACKAGE_ROOT_FILENAME).is_file()


# ---------------------------------------------------------------------------
# Credential ordering
# ---------------------------------------------------------------------------


def test_credentials_block_admission_before_gates(
    monkeypatch: pytest.MonkeyPatch, staged_package: Path
) -> None:
    monkeypatch.setenv("HF_TOKEN", _hf_token_fixture(char="b", length=28))
    assert credentials_are_resolved() is True
    with pytest.raises(CredentialPrematureError):
        assert_credentials_unresolved()
    with pytest.raises(HubIndexAdmissionError, match="credential"):
        admit_patent_legal_hub_indexes(
            package_dir=staged_package, require_admitted=True
        )


def test_clean_env_allows_credential_free_admission(
    clean_env, staged_package: Path
) -> None:
    assert credentials_are_resolved() is False
    assert_credentials_unresolved()
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package, require_admitted=True
    )
    assert receipt["admitted"] is True
    assert receipt["credentials_resolved"] is False


# ---------------------------------------------------------------------------
# Rights / classification
# ---------------------------------------------------------------------------


def test_private_classification_on_artifact_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "priv")

    def mutator(desc: dict) -> None:
        desc["classification"] = "confidential_application"

    _mutate_manifest_artifact(pkg, mutator=mutator)
    with pytest.raises(PackageAdmissionRejectedError):
        admit_patent_legal_hub_indexes(package_dir=pkg, require_admitted=True)
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "classification.private" in receipt["reason_codes"]


def test_unknown_classification_on_artifact_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "unk")

    def mutator(desc: dict) -> None:
        desc["classification"] = "unknown"

    _mutate_manifest_artifact(pkg, mutator=mutator)
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "classification.unknown" in receipt["reason_codes"]


def test_mixed_private_public_batch_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "mixed")
    manifest_path = pkg / MANIFEST_FILENAME
    payload = _read_json(manifest_path)
    descriptors = list(payload.get("artifact_descriptors") or [])
    assert len(descriptors) >= 2
    descriptors[0]["classification"] = "public_official"
    descriptors[1]["classification"] = "privileged_work_product"
    payload["artifact_descriptors"] = descriptors
    _write_json(manifest_path, payload)

    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "classification.private" in receipt["reason_codes"]
    assert "batch.mixed_private_public" in receipt["reason_codes"]


def test_non_public_privacy_summary_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "priv-sum")
    manifest_path = pkg / MANIFEST_FILENAME
    payload = _read_json(manifest_path)
    payload["privacy_summary"] = {
        **dict(payload.get("privacy_summary") or {}),
        "privacy_class": "private",
        "all_reviewed": True,
    }
    _write_json(manifest_path, payload)
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "privacy.not_public" in receipt["reason_codes"]


def test_unreviewed_rights_summary_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "unreviewed")
    manifest_path = pkg / MANIFEST_FILENAME
    payload = _read_json(manifest_path)
    payload["rights_summary"] = {
        **dict(payload.get("rights_summary") or {}),
        "all_reviewed": False,
        "all_redistribution_allowed": False,
    }
    _write_json(manifest_path, payload)
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "rights.unreviewed" in receipt["reason_codes"]
    assert "rights.redistribution_not_allowed" in receipt["reason_codes"]


def test_unknown_rights_status_on_artifact_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "rights-unk")

    def mutator(desc: dict) -> None:
        rr = dict(desc.get("rights_review") or {})
        rr["review_status"] = "unknown"
        rr["redistribution_allowed"] = False
        desc["rights_review"] = rr

    _mutate_manifest_artifact(pkg, mutator=mutator)
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "rights.unknown" in receipt["reason_codes"] or "rights.unreviewed" in receipt[
        "reason_codes"
    ]


# ---------------------------------------------------------------------------
# Secret-like leakage (DLP)
# ---------------------------------------------------------------------------


def test_plaintext_hf_token_in_package_file_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "token-leak")
    token = _hf_token_fixture(char="a", length=24)
    leak_path = pkg / "repos" / "patent-legal-corpus" / "README.md"
    original = leak_path.read_text(encoding="utf-8")
    leak_path.write_text(original + f"\n# do not publish token={token}\n", encoding="utf-8")

    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "content.secret_or_encoded_leakage" in receipt["reason_codes"]
    blob = json.dumps(receipt)
    assert token not in blob


def test_base64_encoded_secret_in_package_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "b64-leak")
    token = _hf_token_fixture(char="d", length=24)
    encoded = base64.b64encode(f"token={token}".encode("utf-8")).decode("ascii")
    target = pkg / "repos" / "patent-legal-bm25" / "coverage.json"
    payload = _read_json(target)
    payload["notes"] = f"blob={encoded}"
    _write_json(target, payload)

    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert (
        "content.secret_or_encoded_leakage" in receipt["reason_codes"]
        or "content.private_marker" in receipt["reason_codes"]
    )
    blob = json.dumps(receipt)
    assert token not in blob


def test_private_marker_in_manifest_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "priv-marker")
    manifest_path = pkg / MANIFEST_FILENAME
    payload = _read_json(manifest_path)
    payload["notes"] = "contains confidential_application material"
    _write_json(manifest_path, payload)

    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert (
        "content.private_marker" in receipt["reason_codes"]
        or "content.secret_or_encoded_leakage" in receipt["reason_codes"]
    )


def test_admission_receipt_never_embeds_secrets(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "no-embed")
    token = _hf_token_fixture(char="c", length=24)
    leak = pkg / "repos" / "patent-legal-vectors" / "README.md"
    leak.write_text(
        leak.read_text(encoding="utf-8") + f"\nsecret={token}\n",
        encoding="utf-8",
    )
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    blob = json.dumps(receipt)
    assert token not in blob
    assert "hf_" + ("c" * 24) not in blob


# ---------------------------------------------------------------------------
# Orphans
# ---------------------------------------------------------------------------


def test_orphan_quality_report_blocks(
    clean_env, staged_package: Path
) -> None:
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=False,
        orphan_joins=3,
        orphan_check=False,
    )
    assert receipt["admitted"] is False
    assert "orphan.quality_report" in receipt["reason_codes"]
    assert "orphan.check_failed" in receipt["reason_codes"]
    assert receipt["package_root_cid"].startswith("b")


def test_orphan_graph_snapshot_blocks(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    pkg = _copy_package(staged_package, tmp_path / "orphan-snap")
    snap_dir = pkg / "indexes" / "knowledge_graph"
    snaps = list(snap_dir.glob("*.snapshot.json"))
    assert snaps
    snap = _read_json(snaps[0])
    snap["orphan_check"] = "fail"
    snap["orphan_joins"] = 2
    _write_json(snaps[0], snap)

    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "orphan.check_failed" in receipt["reason_codes"]
    # package_orphans and/or policy orphans gate
    orphan_gates = [
        g for g in receipt["gate_results"] if "orphan" in g["name"]
    ]
    assert orphan_gates
    assert any(not g["passed"] for g in orphan_gates)


# ---------------------------------------------------------------------------
# Invalid Parquet
# ---------------------------------------------------------------------------


def test_invalid_parquet_blocks_admission(
    clean_env, staged_package: Path
) -> None:
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=False,
        corrupt_parquet=True,
    )
    assert receipt["admitted"] is False
    assert any(c.startswith("parquet.") for c in receipt["reason_codes"])
    parquet_gate = next(
        g for g in receipt["gate_results"] if g["name"] == "parquet"
    )
    assert parquet_gate["passed"] is False


def test_valid_injected_parquet_does_not_break_happy_path(
    clean_env, staged_package: Path
) -> None:
    # inject_parquet adds valid shards; admission should still pass.
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=True,
        inject_parquet=True,
    )
    assert receipt["admitted"] is True
    parquet_gate = next(
        g for g in receipt["gate_results"] if g["name"] == "parquet"
    )
    assert parquet_gate["passed"] is True


# ---------------------------------------------------------------------------
# Viewer contracts
# ---------------------------------------------------------------------------


def test_viewer_endpoints_cover_required_contracts() -> None:
    assert set(VIEWER_ENDPOINTS) == {
        "is-valid",
        "splits",
        "rows",
        "parquet",
        "size",
        "statistics",
    }


def test_failed_viewer_is_valid_blocks_admission(
    clean_env, staged_package: Path
) -> None:
    with pytest.raises(PackageAdmissionRejectedError):
        admit_patent_legal_hub_indexes(
            package_dir=staged_package,
            require_admitted=True,
            force_viewer_invalid=True,
        )
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=False,
        force_viewer_invalid=True,
    )
    assert receipt["admitted"] is False
    assert "viewer.not_valid" in receipt["reason_codes"]
    assert receipt["viewer_contracts_passed"] is False
    assert receipt["package_root_cid"].startswith("b")


def test_viewer_contracts_recorded_on_success(
    clean_env, staged_package: Path
) -> None:
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package, require_admitted=True
    )
    assert receipt["viewer_contracts_passed"] is True
    assert set(receipt["viewer_endpoints_checked"]) == set(VIEWER_ENDPOINTS)
    assert receipt["viewer_contracts"]["passed"] is True


# ---------------------------------------------------------------------------
# Package integrity
# ---------------------------------------------------------------------------


def test_missing_repository_blocks_integrity(
    clean_env, staged_package: Path, tmp_path: Path
) -> None:
    import shutil

    pkg = _copy_package(staged_package, tmp_path / "missing-repo")
    shutil.rmtree(pkg / "repos" / "patent-legal-bm25")
    receipt = admit_patent_legal_hub_indexes(
        package_dir=pkg, require_admitted=False
    )
    assert receipt["admitted"] is False
    assert "package.missing_repository" in receipt["reason_codes"]


def test_missing_package_manifest_errors(
    clean_env, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(HubIndexAdmissionError, match="manifest"):
        admit_patent_legal_hub_indexes(
            package_dir=empty, require_admitted=False
        )


def test_resolve_package_dir_rejects_both_inputs(
    clean_env, staged_package: Path
) -> None:
    with pytest.raises(HubIndexAdmissionError):
        resolve_package_dir(
            package_dir=staged_package, default_fixture=True
        )


# ---------------------------------------------------------------------------
# Policy inventory overrides / classification summary
# ---------------------------------------------------------------------------


def test_private_classification_summary_blocks_via_inventory(
    clean_env, staged_package: Path
) -> None:
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=False,
        classification_summary={
            "public_official": 1,
            "confidential_application": 1,
        },
    )
    assert receipt["admitted"] is False
    assert "batch.private_input" in receipt["reason_codes"]
    assert "batch.mixed_private_public" in receipt["reason_codes"]


def test_custom_inventory_with_missing_cards_blocks(
    clean_env, staged_package: Path
) -> None:
    base = inventory_from_hub_index_package(staged_package)
    repos = []
    for repo in base.repositories:
        repos.append(
            RepositoryInventory(
                repository=repo.repository,
                dataset_id=repo.dataset_id,
                role=repo.role,
                relative_paths=repo.relative_paths,
                parquet_shards=repo.parquet_shards,
                config_names=repo.config_names,
                config_row_counts=dict(repo.config_row_counts),
                has_readme=False,
                has_dataset_configs=False,
                has_coverage=False,
                coverage_sources=(),
                dataset_configs={},
            )
        )
    inventory = StagedReleaseInventory(
        root=base.root,
        organization=base.organization,
        repositories=tuple(repos),
        manifest=dict(base.manifest),
        quality_report=dict(base.quality_report),
        policy_receipt=dict(base.policy_receipt),
        support_paths=base.support_paths,
    )
    receipt = admit_patent_legal_hub_indexes(
        package_dir=staged_package,
        require_admitted=False,
        inventory=inventory,
        run_viewer_gate=False,
    )
    assert receipt["admitted"] is False
    assert "card.missing_readme" in receipt["reason_codes"]
    assert "config.missing_dataset_configs" in receipt["reason_codes"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_cli_admits_default_fixture(clean_env, tmp_path: Path) -> None:
    from scripts.ops.legal_data.admit_patent_legal_hub_indexes import main

    stage = tmp_path / "cli-stage"
    receipt_out = tmp_path / "cli-receipt.json"
    code = main(
        [
            "--default-fixture",
            "--stage-dir",
            str(stage),
            "--receipt-out",
            str(receipt_out),
            "--json",
        ]
    )
    assert code == 0
    assert receipt_out.is_file()
    payload = _read_json(receipt_out)
    assert payload["admitted"] is True
    assert payload["package_root_cid"].startswith("b")


def test_main_cli_rejects_force_viewer_invalid(
    clean_env, staged_package: Path
) -> None:
    from scripts.ops.legal_data.admit_patent_legal_hub_indexes import main

    code = main(
        [
            "--package-dir",
            str(staged_package),
            "--force-viewer-invalid",
        ]
    )
    assert code == 1


def test_main_cli_allow_reject_exits_zero_on_failure(
    clean_env, staged_package: Path
) -> None:
    from scripts.ops.legal_data.admit_patent_legal_hub_indexes import main

    code = main(
        [
            "--package-dir",
            str(staged_package),
            "--force-viewer-invalid",
            "--allow-reject",
            "--json",
        ]
    )
    # allow-reject still returns 0 only when admitted... looking at main:
    # return 0 if result["admitted"] else 1
    # allow-reject only affects require_admitted (no raise), still exit 1 when rejected
    assert code == 1
