"""Contract vectors for signed campaign/promotion receipts (AAE-012)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.receipt_contracts import (
    ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE,
    ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
    ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA,
    ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE,
    EXISTING_SIGNATURE_ALGORITHM,
    EXISTING_SIGNATURE_AUTHORITY,
    AdversarialAssuranceArtifacts,
    AssuranceCampaignReceipt,
    AssurancePolicyPromotionReceipt,
    HeldOutResult,
    ReceiptAction,
    ReceiptContractError,
    ReceiptSignatureBinding,
    SealAvailabilityStatus,
    SealScopeItem,
    SignatureVerificationStatus,
    adversarial_assurance_artifact_catalog,
    held_out_results,
    require_verified_signature_before_persistence,
    seal_scope_items,
    signature_verification_statuses,
    verify_campaign_receipt_identity,
    verify_promotion_receipt_identity,
)

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_DIR = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "adversarial_assurance"
    / "schemas"
)
RECEIPT_SCHEMA_PATH = SCHEMA_DIR / "receipt.schema.json"
BASE_SCHEMA_PATH = SCHEMA_DIR / "base.schema.json"

# Valid-looking Ed25519 did:key and base64url signature material (opaque bytes).
_SIGNER = "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
_SIGNATURE = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "campaign_sealer",
        "generator_version": "1.0.0",
        "interface_id": "seal_campaign@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _versions(**overrides: object) -> VersionBinding:
    fields = {
        "operator_id": "campaign_operator",
        "operator_version": "1",
        "campaign_policy_id": "default_campaign",
        "campaign_policy_version": "1.0.0",
        "generator": _generator(),
    }
    fields.update(overrides)
    return VersionBinding(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "adversarial_assurance",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.RECEIPT,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("campaign.sealer.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(artifact_kind: str, **overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": artifact_kind,
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "target_symbol_ids": ("mod.fn",),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("dependency-lock"),
        "versions": _versions(),
        "provenance": _provenance(),
        "terminal_status": AssuranceTerminalStatus.COMPLETE,
        "receipt_cids": (),
        "proof_cids": (),
        "metadata": {},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


def _signature(**overrides: object) -> ReceiptSignatureBinding:
    fields = {
        "signer_identity": _SIGNER,
        "key_identity": _SIGNER,
        "audience": "adversarial_assurance.store",
        "action": ReceiptAction.COMPLETE_CAMPAIGN,
        "signature": _SIGNATURE,
        "signature_verification_status": SignatureVerificationStatus.VERIFIED,
        "signature_algorithm": EXISTING_SIGNATURE_ALGORITHM,
        "signature_authority": EXISTING_SIGNATURE_AUTHORITY,
    }
    fields.update(overrides)
    return ReceiptSignatureBinding(**fields)  # type: ignore[arg-type]


def _campaign_scope() -> tuple[str, ...]:
    return (
        SealScopeItem.OPERATOR_VERSIONS.value,
        SealScopeItem.CAMPAIGN_POLICY.value,
        SealScopeItem.ADMITTED_SET.value,
        SealScopeItem.EXPECTED_DETECTION_SETS.value,
        SealScopeItem.OUTCOMES.value,
        SealScopeItem.SURVIVOR_REPORTS.value,
        SealScopeItem.VACUITY_FINDINGS.value,
        SealScopeItem.HELD_OUT_EVALUATIONS.value,
        SealScopeItem.CAMPAIGN_ARTIFACTS.value,
        SealScopeItem.DECLARED_RESULT_COMPLETENESS.value,
        SealScopeItem.CAMPAIGN_RECEIPT.value,
    )


def _campaign(**overrides: object) -> AssuranceCampaignReceipt:
    fields = {
        "header": _header("assurance_campaign_receipt"),
        "receipt_id": "campaign_receipt_1",
        "campaign_plan_cid": _cid("plan"),
        "campaign_policy_cid": _cid("campaign-policy"),
        "campaign_policy_version": "1.0.0",
        "admitted_set_cid": _cid("admitted"),
        "expected_detection_sets_cid": _cid("expected-detection"),
        "outcomes_cid": _cid("outcomes"),
        "survivor_reports_cid": _cid("survivors"),
        "vacuity_findings_cid": _cid("vacuity"),
        "held_out_evaluation_cid": _cid("held-out-eval"),
        "held_out_result": HeldOutResult.PASSED,
        "authorization_cid": _cid("external-authorization"),
        "expected_old_revision": "0.9.0",
        "seal_scope": _campaign_scope(),
        "seal_status": SealAvailabilityStatus.BOUND,
        "seal_evidence_cid": _cid("seal-evidence"),
        "gap_reports_cid": _cid("gaps"),
        "input_artifact_cids": (_cid("input-plan"), _cid("input-policy")),
        "signature": _signature(action=ReceiptAction.COMPLETE_CAMPAIGN),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return AssuranceCampaignReceipt(**fields)  # type: ignore[arg-type]


def _promotion_scope() -> tuple[str, ...]:
    return (
        SealScopeItem.FINAL_POLICY_REVISION.value,
        SealScopeItem.EVALUATION_TO_PROMOTION_BINDING.value,
        SealScopeItem.HELD_OUT_EVALUATIONS.value,
        SealScopeItem.STATUS_POLICY_SATISFACTION.value,
        SealScopeItem.PROMOTION_RECEIPT.value,
    )


def _promotion(**overrides: object) -> AssurancePolicyPromotionReceipt:
    fields = {
        "header": _header("assurance_policy_promotion_receipt"),
        "receipt_id": "promotion_receipt_1",
        "campaign_receipt_cid": _cid("campaign-receipt"),
        "candidate_cid": _cid("candidate"),
        "evaluation_report_cid": _cid("evaluation"),
        "held_out_evaluation_cid": _cid("held-out-eval"),
        "held_out_result": HeldOutResult.PASSED,
        "authorization_cid": _cid("external-authorization"),
        "expected_old_policy_cid": _cid("old-policy"),
        "expected_old_policy_version": "1.0.0",
        "previous_policy_cid": _cid("old-policy"),
        "previous_policy_version": "1.0.0",
        "promoted_policy_cid": _cid("new-policy"),
        "promoted_policy_version": "1.0.1",
        "rollback_policy_cid": _cid("old-policy"),
        "cas_expected_version": "1.0.0",
        "seal_scope": _promotion_scope(),
        "seal_status": SealAvailabilityStatus.BOUND,
        "seal_evidence_cid": _cid("seal-evidence"),
        "signature": _signature(action=ReceiptAction.PROMOTE_POLICY),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return AssurancePolicyPromotionReceipt(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Signature binding
# ---------------------------------------------------------------------------


def test_signature_binding_round_trip_and_identity() -> None:
    binding = _signature()
    assert binding.signature_algorithm == "EdDSA"
    assert binding.signature_authority == EXISTING_SIGNATURE_AUTHORITY
    assert binding.signature_verification_status == "verified"
    sealed = ReceiptSignatureBinding.from_dict(binding.to_dict())
    assert sealed.binding_cid == binding.binding_cid
    assert sealed.binding_cid == cid_for_structured(binding.identity_payload())


def test_signature_binding_rejects_new_algorithm_or_authority() -> None:
    with pytest.raises(ReceiptContractError, match="EdDSA"):
        _signature(signature_algorithm="ECDSA")
    with pytest.raises(ReceiptContractError, match="existing"):
        _signature(signature_authority="custom-authority@1")


def test_signature_binding_requires_bytes_when_verified() -> None:
    with pytest.raises(ReceiptContractError, match="signature"):
        _signature(signature="")


def test_signature_binding_allows_empty_only_when_unavailable() -> None:
    binding = _signature(
        signature="",
        signature_verification_status=SignatureVerificationStatus.UNAVAILABLE,
    )
    assert binding.signature == ""
    assert binding.signature_verification_status == "unavailable"


# ---------------------------------------------------------------------------
# Campaign receipt
# ---------------------------------------------------------------------------


def test_campaign_receipt_binds_required_fields_and_round_trips() -> None:
    receipt = _campaign()
    assert receipt.header.terminal_status == "complete"
    assert receipt.held_out_result == "passed"
    assert receipt.signature.signer_identity == _SIGNER
    assert receipt.signature.signature_verification_status == "verified"
    assert "campaign_policy" in receipt.seal_scope
    sealed = AssuranceCampaignReceipt.from_dict(receipt.to_dict())
    assert sealed.receipt_cid == receipt.receipt_cid
    assert verify_campaign_receipt_identity(sealed) == sealed.receipt_cid
    assert sealed.to_dict()["schema"] == ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA
    assert sealed.to_dict()["interface_id"] == ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE


def test_campaign_receipt_rejects_unverified_complete() -> None:
    with pytest.raises(ReceiptContractError, match="verified"):
        _campaign(
            signature=_signature(
                signature_verification_status=SignatureVerificationStatus.UNVERIFIED
            )
        )


def test_campaign_receipt_rejects_self_authorization() -> None:
    with pytest.raises(ReceiptContractError, match="authorization"):
        _campaign(authorization_cid=_cid("plan"))


def test_campaign_receipt_rejects_unknown_fields() -> None:
    payload = _campaign().to_dict()
    payload["extra_field"] = "nope"
    with pytest.raises(ReceiptContractError, match="fields must be exactly"):
        AssuranceCampaignReceipt.from_dict(payload)


def test_campaign_receipt_rejects_identity_tamper() -> None:
    payload = _campaign().to_dict()
    payload["receipt_cid"] = _cid("forged")
    with pytest.raises(ReceiptContractError, match="identity mismatch"):
        AssuranceCampaignReceipt.from_dict(payload)


def test_campaign_receipt_rejects_wrong_artifact_kind() -> None:
    with pytest.raises(ReceiptContractError, match="artifact_kind"):
        _campaign(header=_header("mutation_execution_receipt"))


def test_campaign_receipt_bound_seal_requires_evidence() -> None:
    with pytest.raises(ReceiptContractError, match="seal_evidence_cid"):
        _campaign(seal_status=SealAvailabilityStatus.BOUND, seal_evidence_cid=None)


def test_campaign_receipt_unavailable_seal_forbids_evidence() -> None:
    with pytest.raises(ReceiptContractError, match="forbids seal_evidence_cid"):
        _campaign(
            seal_status=SealAvailabilityStatus.UNAVAILABLE,
            seal_evidence_cid=_cid("seal"),
        )


def test_campaign_receipt_complete_rejects_failed_held_out() -> None:
    with pytest.raises(ReceiptContractError, match="held_out_result"):
        _campaign(held_out_result=HeldOutResult.FAILED)


def test_campaign_receipt_rejected_status_allows_unverified() -> None:
    receipt = _campaign(
        header=_header(
            "assurance_campaign_receipt",
            terminal_status=AssuranceTerminalStatus.REJECTED,
        ),
        held_out_result=HeldOutResult.FAILED,
        signature=_signature(
            signature_verification_status=SignatureVerificationStatus.REJECTED,
            action=ReceiptAction.COMPLETE_CAMPAIGN,
        ),
    )
    assert receipt.header.terminal_status == "rejected"
    assert receipt.signature.signature_verification_status == "rejected"


# ---------------------------------------------------------------------------
# Promotion receipt
# ---------------------------------------------------------------------------


def test_promotion_receipt_binds_expected_old_and_round_trips() -> None:
    receipt = _promotion()
    assert receipt.expected_old_policy_version == receipt.cas_expected_version
    assert receipt.previous_policy_cid == receipt.expected_old_policy_cid
    assert receipt.held_out_result == "passed"
    assert SealScopeItem.FINAL_POLICY_REVISION.value in receipt.seal_scope
    sealed = AssurancePolicyPromotionReceipt.from_dict(receipt.to_dict())
    assert sealed.receipt_cid == receipt.receipt_cid
    assert verify_promotion_receipt_identity(sealed) == sealed.receipt_cid
    assert sealed.to_dict()["interface_id"] == ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE


def test_promotion_receipt_rejects_self_authorization() -> None:
    with pytest.raises(ReceiptContractError, match="self-authorize"):
        _promotion(authorization_cid=_cid("candidate"))


def test_promotion_receipt_rejects_cas_mismatch() -> None:
    with pytest.raises(ReceiptContractError, match="cas_expected_version"):
        _promotion(cas_expected_version="9.9.9")


def test_promotion_receipt_rejects_same_promoted_policy() -> None:
    with pytest.raises(ReceiptContractError, match="promoted_policy_cid"):
        _promotion(
            promoted_policy_cid=_cid("old-policy"),
            promoted_policy_version="1.0.1",
        )


def test_promotion_receipt_requires_held_out_pass_when_complete() -> None:
    with pytest.raises(ReceiptContractError, match="held_out_result"):
        _promotion(held_out_result=HeldOutResult.FAILED)


def test_promotion_receipt_requires_promote_action_when_complete() -> None:
    with pytest.raises(ReceiptContractError, match="promote_policy"):
        _promotion(signature=_signature(action=ReceiptAction.SEAL_CAMPAIGN))


def test_promotion_receipt_requires_seal_scope_items() -> None:
    with pytest.raises(ReceiptContractError, match="final_policy_revision"):
        _promotion(seal_scope=(SealScopeItem.CAMPAIGN_ARTIFACTS.value,))


def test_promotion_receipt_rejects_unknown_fields_and_tamper() -> None:
    payload = _promotion().to_dict()
    payload["unknown"] = True
    with pytest.raises(ReceiptContractError, match="fields must be exactly"):
        AssurancePolicyPromotionReceipt.from_dict(payload)
    payload = _promotion().to_dict()
    payload["receipt_cid"] = _cid("forged")
    with pytest.raises(ReceiptContractError, match="identity mismatch"):
        AssurancePolicyPromotionReceipt.from_dict(payload)


# ---------------------------------------------------------------------------
# Persistence gate
# ---------------------------------------------------------------------------


def test_require_verified_signature_before_persistence() -> None:
    campaign = _campaign()
    assert require_verified_signature_before_persistence(campaign) == campaign.receipt_cid
    promotion = _promotion()
    assert (
        require_verified_signature_before_persistence(promotion) == promotion.receipt_cid
    )


def test_require_verified_signature_rejects_unverified_mapping() -> None:
    receipt = _campaign(
        header=_header(
            "assurance_campaign_receipt",
            terminal_status=AssuranceTerminalStatus.REJECTED,
        ),
        held_out_result=HeldOutResult.FAILED,
        signature=_signature(
            signature_verification_status=SignatureVerificationStatus.UNVERIFIED
        ),
    )
    with pytest.raises(ReceiptContractError, match="signature verification must pass"):
        require_verified_signature_before_persistence(receipt.to_dict())


# ---------------------------------------------------------------------------
# Package catalog
# ---------------------------------------------------------------------------


def test_adversarial_assurance_artifacts_freeze_contains_receipts() -> None:
    catalog = AdversarialAssuranceArtifacts.freeze_default()
    assert catalog.to_dict()["interface_id"] == ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE
    names = {item["name"] for item in catalog.artifacts}
    assert "AssuranceCampaignReceipt" in names
    assert "AssurancePolicyPromotionReceipt" in names
    assert "AdversarialAssuranceArtifacts" in names
    assert "MutationCampaignPlan" in names
    assert "RemediationEvaluationReport" in names
    sealed = AdversarialAssuranceArtifacts.from_dict(catalog.to_dict())
    assert sealed.catalog_cid == catalog.catalog_cid
    assert sealed.signature_algorithm == "EdDSA"
    assert sealed.signature_authority == EXISTING_SIGNATURE_AUTHORITY


def test_artifact_catalog_helper_matches_freeze() -> None:
    rows = adversarial_assurance_artifact_catalog()
    freeze = AdversarialAssuranceArtifacts.freeze_default()
    assert {row["interface_id"] for row in rows} == {
        row["interface_id"] for row in freeze.artifacts
    }


def test_closed_vocabularies_are_nonempty() -> None:
    assert "verified" in signature_verification_statuses()
    assert "passed" in held_out_results()
    assert "final_policy_revision" in seal_scope_items()


# ---------------------------------------------------------------------------
# JSON Schema packaging
# ---------------------------------------------------------------------------


def test_receipt_schema_accepts_sealed_campaign_and_promotion() -> None:
    schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(_campaign().to_dict())
    validator.validate(_promotion().to_dict())
    validator.validate(_signature().to_dict())
    validator.validate(AdversarialAssuranceArtifacts.freeze_default().to_dict())


def test_receipt_schema_rejects_unknown_fields() -> None:
    schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    payload = _campaign().to_dict()
    payload["extra"] = 1
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_base_schema_file_is_packaged() -> None:
    assert BASE_SCHEMA_PATH.is_file()
    schema = json.loads(BASE_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(_header("assurance_campaign_receipt").to_dict())


def test_schema_files_live_beside_package() -> None:
    assert RECEIPT_SCHEMA_PATH.is_file()
    assert RECEIPT_SCHEMA_PATH.name == "receipt.schema.json"
    assert BASE_SCHEMA_PATH.name == "base.schema.json"
