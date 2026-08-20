"""Public package export freeze checks for adversarial_assurance (AAE-012)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ipfs_datasets_py.logic.software_contracts.adversarial_assurance as aae
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance import (
    ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE,
    ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
    ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE,
    BASE_SCHEMA_PATH,
    EXISTING_SIGNATURE_ALGORITHM,
    EXISTING_SIGNATURE_AUTHORITY,
    PACKAGE_INTERFACE,
    RECEIPT_SCHEMA_PATH,
    SCHEMA_DIRECTORY,
    AdversarialAssuranceArtifacts,
    AssuranceArtifactHeader,
    AssuranceCampaignReceipt,
    AssurancePolicyPromotionReceipt,
    MutationCampaignPlan,
    MutationExecutionReceipt,
    RemediationEvaluationReport,
    freeze_adversarial_assurance_artifacts,
    package_schema_paths,
    require_verified_signature_before_persistence,
)


def test_package_interface_pins_are_stable() -> None:
    assert PACKAGE_INTERFACE == "AdversarialAssuranceArtifacts@1"
    assert ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE == PACKAGE_INTERFACE
    assert ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE == "AssuranceCampaignReceipt@1"
    assert (
        ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE
        == "AssurancePolicyPromotionReceipt@1"
    )
    assert EXISTING_SIGNATURE_ALGORITHM == "EdDSA"
    assert EXISTING_SIGNATURE_AUTHORITY == (
        "ipfs-datasets.profile-g.ed25519-did-key@1"
    )


def test_package_exports_core_artifact_types() -> None:
    for name in (
        "AssuranceArtifactHeader",
        "MutationOperatorDefinition",
        "MutationCampaignPlan",
        "ExpectedDetectionSet",
        "MutationExecutionReceipt",
        "MutationOutcome",
        "SurvivingMutantReport",
        "AssuranceGap",
        "VacuityFinding",
        "CandidateTestSpecification",
        "RemediationEvaluationReport",
        "AssuranceCampaignReceipt",
        "AssurancePolicyPromotionReceipt",
        "AdversarialAssuranceArtifacts",
        "ReceiptSignatureBinding",
        "require_verified_signature_before_persistence",
        "freeze_adversarial_assurance_artifacts",
        "package_schema_paths",
    ):
        assert hasattr(aae, name), f"missing public export {name}"
        assert name in aae.__all__, f"{name} missing from __all__"


def test_freeze_matches_helper_and_catalog_cid() -> None:
    frozen = freeze_adversarial_assurance_artifacts()
    direct = AdversarialAssuranceArtifacts.freeze_default()
    assert frozen.catalog_cid == direct.catalog_cid
    assert frozen.package == (
        "ipfs_datasets_py.logic.software_contracts.adversarial_assurance"
    )
    names = {item["name"] for item in frozen.artifacts}
    assert "AssuranceCampaignReceipt" in names
    assert "AssurancePolicyPromotionReceipt" in names
    # Catalog is deterministic across calls.
    assert freeze_adversarial_assurance_artifacts().catalog_cid == frozen.catalog_cid


def test_schema_paths_are_real_files_under_package() -> None:
    paths = package_schema_paths()
    assert paths == (BASE_SCHEMA_PATH, RECEIPT_SCHEMA_PATH)
    assert SCHEMA_DIRECTORY.is_dir()
    for path in paths:
        assert path.is_file()
        assert path.parent == SCHEMA_DIRECTORY
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"].endswith("draft/2020-12/schema")


def test_importing_package_has_no_side_effects_and_exports_are_callable() -> None:
    # Type objects remain importable and class-like.
    assert issubclass(AssuranceCampaignReceipt, object)
    assert issubclass(AssurancePolicyPromotionReceipt, object)
    assert issubclass(AssuranceArtifactHeader, object)
    assert issubclass(MutationCampaignPlan, object)
    assert issubclass(MutationExecutionReceipt, object)
    assert issubclass(RemediationEvaluationReport, object)
    assert callable(require_verified_signature_before_persistence)
    assert callable(freeze_adversarial_assurance_artifacts)


def test_public_api_rejects_new_signature_authority_on_catalog() -> None:
    with pytest.raises(Exception):
        AdversarialAssuranceArtifacts(
            signature_authority="invented-authority@1",
            artifacts=list(AdversarialAssuranceArtifacts.freeze_default().artifacts),
        )


def test_schema_directory_relative_path_documented_in_catalog() -> None:
    catalog = freeze_adversarial_assurance_artifacts()
    assert catalog.schema_directory.endswith(
        "software_contracts/adversarial_assurance/schemas"
    )
    # On-disk directory matches the frozen relative suffix.
    assert SCHEMA_DIRECTORY.as_posix().endswith(catalog.schema_directory.split("/", 1)[-1]) or (
        Path(catalog.schema_directory).name == "schemas"
    )
