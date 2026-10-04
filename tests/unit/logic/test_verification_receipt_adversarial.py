"""Adversarial fail-closed tests for VerifiedReceiptDispatch@2 (FVT-G006 / FVT-003).

Acceptance subset covered here:

* Empty, unknown, forged-kernel, stale, wrong-tree, wrong-property,
  wrong-assumption, wrong-bound, wrong-tool, and cross-authority inputs are
  rejected.
* Valid typed receipts round-trip without authority loss.
* Prepared/simulated attestation cannot report proof success (unit surface).
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.bridge.proof_receipt_attestation import (
    AttestationBackendMode,
    AttestationBackendPolicy,
    TrustedProofReceipt,
    build_trusted_receipt_from_backend_result,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.receipts import (
    LogicTranslationReceipt,
    TranslationReceiptExpectation,
)
from ipfs_datasets_py.logic.software_verification.translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
)
from ipfs_datasets_py.logic.verification_api import (
    ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE,
    CLOSED_RECEIPT_SCHEMAS,
    LOGIC_TRANSLATION_RECEIPT_SCHEMA,
    TRUSTED_PROOF_RECEIPT_SCHEMA,
    VERIFIED_RECEIPT_DISPATCH_INTERFACE,
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationStatus,
)

TREE = "tree:repo@abc123"
PROPERTY = "property:functional-correctness"
ASSUMPTIONS = ("assumption:int",)
BOUNDS = {"timeout_ms": 1000, "max_steps": 100}
TOOL = "solver.lean"
NOW = "2026-07-23T12:00:00Z"
EXPIRES = "2026-07-23T12:05:00Z"
STALE_NOW = "2026-07-23T12:06:00Z"


def _api() -> LogicVerificationAPI:
    return LogicVerificationAPI()


def _theorem(**changes: Any) -> TheoremResult:
    fields: dict[str, Any] = {
        "result_id": "result:theorem-fvt003",
        "backend_id": TOOL,
        "backend_version": "4.19.0",
        "authority": ResultAuthority.THEOREM,
        "status": ResultStatus.PROVED,
        "assumptions": ASSUMPTIONS,
        "bounds": ExecutionBounds(timeout_ms=1000, max_steps=100),
        "translation_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "metadata": FrozenMap({"bounds": dict(BOUNDS), "expires_at": EXPIRES, "issued_at": NOW}),
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _trusted(**changes: Any) -> TrustedProofReceipt:
    result_changes = {
        key: changes.pop(key)
        for key in list(changes)
        if key
        in {
            "authority",
            "status",
            "assumptions",
            "backend_id",
            "backend_version",
            "translation_ceiling",
            "metadata",
        }
    }
    source = _theorem(**result_changes)
    return build_trusted_receipt_from_backend_result(
        source,
        theorem_id=changes.pop("theorem_id", "theorem:sort-correct"),
        property_id=changes.pop("property_id", PROPERTY),
        translation_receipt_id=changes.pop(
            "translation_receipt_id", "translation:fol-to-lean:v1"
        ),
        tree_id=changes.pop("tree_id", TREE),
        policy_id=changes.pop("policy_id", "policy:formal@1"),
        receipt_id=changes.pop("receipt_id", ""),
    )


def _compiler() -> CompilerBinding:
    return CompilerBinding(
        compiler_id="compiler:fol-to-smt",
        compiler_version="1.0.0",
        implementation_identity="sha256:" + "c" * 64,
        configuration_identity="sha256:" + "d" * 64,
        stage="lower",
    )


def _translation(**overrides: Any) -> LogicTranslationReceipt:
    values: dict[str, Any] = {
        "source_identity": "src:identity:a",
        "target_identity": "tgt:identity:b",
        "source_family_id": "first_order",
        "source_family_version": "1.0.0",
        "target_family_id": "smt",
        "target_family_version": "2.6",
        "compilers": (_compiler(),),
        "preservation_claim": PreservationClaim(
            kind=PreservationKind.EXACT,
            preserved_property_ids=(PROPERTY,),
            permitted_result_classes=("proved", "disproved"),
            description="Reviewed fragment is structurally preserved.",
        ),
        "authority_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "assumptions": ASSUMPTIONS,
    }
    values.update(overrides)
    return LogicTranslationReceipt(**values)


def _policy(
    *,
    backend_mode: AttestationBackendMode = AttestationBackendMode.SIMULATED,
) -> AttestationBackendPolicy:
    return AttestationBackendPolicy(
        backend_id="backend:provekit",
        backend_version="0.2.0",
        circuit_id="circuit:receipt-binding",
        circuit_version="2.1.0",
        ceremony_id="ceremony:mpc-2026-07",
        crs_id="crs:powers-of-tau:28",
        proving_key_id="pk:receipt-binding:sha256-cafe",
        verification_key_id="vk:receipt-binding:sha256-beef",
        revocation_policy_id="revocation:production@1",
        backend_mode=backend_mode,
        verification_key_expires_at="2030-01-01T00:00:00Z",
    )


def _binding(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tree_id": TREE,
        "property_id": PROPERTY,
        "assumptions": list(ASSUMPTIONS),
        "bounds": dict(BOUNDS),
        "backend_id": TOOL,
        "authority": "theorem",
        "now": NOW,
    }
    payload.update(overrides)
    return payload


# ── Empty / unknown / forged ──────────────────────────────────────────────────


def test_empty_receipt_rejected() -> None:
    api = _api()
    for empty in (None, {}):
        response = api.verify_receipt(empty)
        assert response.status is VerificationStatus.INVALID
        assert response.authority is VerificationAuthority.NONE
        assert response.result["valid"] is False
        assert response.result["reason"] == "empty"
        assert response.result["dispatch"] == VERIFIED_RECEIPT_DISPATCH_INTERFACE


def test_unknown_schema_rejected() -> None:
    api = _api()
    response = api.verify_receipt(
        {
            "schema_version": "not-a-receipt/v0",
            "receipt_id": "rcpt:1",
            "authority": "bounded",
            "digest": "a" * 64,
        }
    )
    assert response.status is VerificationStatus.INVALID
    assert response.authority is VerificationAuthority.NONE
    assert response.result["reason"] == "unknown"
    assert "closed dispatch" in response.diagnostics[0]


def test_legacy_permissive_mapping_rejected() -> None:
    """Regression: bare receipt_id+authority must no longer succeed."""

    api = _api()
    response = api.verify_receipt(
        {
            "receipt_id": "rcpt:1",
            "authority": "bounded",
            "digest": "a" * 64,
            "kind": "proof_receipt",
        }
    )
    assert response.status is VerificationStatus.INVALID
    assert response.result["valid"] is False


def test_forged_kernel_authority_claim_rejected() -> None:
    api = _api()
    response = api.verify_receipt(
        {
            "receipt_id": "forged",
            "authority": "theorem",
            "kind": "kernel_receipt",
            "digest": "deadbeef",
        }
    )
    assert response.status is VerificationStatus.INVALID
    assert response.authority is VerificationAuthority.NONE
    assert response.result["reason"] == "forged-kernel"


def test_forged_content_id_on_trusted_receipt_rejected() -> None:
    api = _api()
    receipt = _trusted()
    payload = receipt.to_dict()
    payload["content_id"] = "0" * 64
    response = api.verify_receipt(payload)
    assert response.status is VerificationStatus.INVALID
    assert response.result["valid"] is False


# ── Binding mismatches ────────────────────────────────────────────────────────


def test_wrong_tree_property_assumption_bound_tool_rejected() -> None:
    api = _api()
    receipt = _trusted()

    cases = {
        "wrong-tree": _binding(tree_id="tree:other@zzz"),
        "wrong-property": _binding(property_id="property:other"),
        "wrong-assumption": _binding(assumptions=["assumption:other"]),
        "wrong-bound": _binding(bounds={"timeout_ms": 1, "max_steps": 1}),
        "wrong-tool": _binding(backend_id="solver.z3"),
    }
    for label, expectation in cases.items():
        response = api.verify_receipt(receipt, expectation)
        assert response.status is VerificationStatus.INVALID, label
        assert response.authority is VerificationAuthority.NONE, label
        assert response.result["valid"] is False, label
        assert any(label in item for item in response.diagnostics), (
            label,
            response.diagnostics,
        )


def test_cross_authority_rejected() -> None:
    api = _api()
    receipt = _trusted()
    response = api.verify_receipt(receipt, _binding(authority="satisfiability"))
    assert response.status is VerificationStatus.INVALID
    assert any("cross-authority" in item for item in response.diagnostics)


def test_stale_digest_and_expiry_rejected() -> None:
    api = _api()
    receipt = _trusted()

    stale_digest = api.verify_receipt(
        receipt, _binding(source_result_digest="stale-digest-value")
    )
    assert stale_digest.status is VerificationStatus.INVALID
    assert any("stale" in item for item in stale_digest.diagnostics)

    stale_window = api.verify_receipt(receipt, _binding(now=STALE_NOW))
    assert stale_window.status is VerificationStatus.INVALID
    assert any("stale" in item for item in stale_window.diagnostics)

    wrong_receipt_id = api.verify_receipt(
        receipt, _binding(receipt_id="receipt:not-this-one")
    )
    assert wrong_receipt_id.status is VerificationStatus.INVALID
    assert any("stale" in item for item in wrong_receipt_id.diagnostics)


# ── Valid round-trips ─────────────────────────────────────────────────────────


def test_valid_trusted_receipt_round_trips_without_authority_loss() -> None:
    api = _api()
    receipt = _trusted()
    response = api.verify_receipt(receipt, _binding(content_id=receipt.content_id))
    assert response.status is VerificationStatus.SUCCEEDED
    assert response.authority is VerificationAuthority.THEOREM
    assert response.result["valid"] is True
    assert response.result["dispatch"] == VERIFIED_RECEIPT_DISPATCH_INTERFACE
    assert response.result["schema_version"] == TRUSTED_PROOF_RECEIPT_SCHEMA
    assert response.result["round_trip"]["receipt_id"] == receipt.receipt_id
    assert response.result["round_trip"]["underlying_authority"] == "theorem"
    assert response.assumptions == ASSUMPTIONS
    assert response.property_id == PROPERTY
    assert response.provider_id == TOOL

    # Mapping form also works.
    mapped = api.verify_receipt(receipt.to_dict())
    assert mapped.status is VerificationStatus.SUCCEEDED
    assert mapped.authority is VerificationAuthority.THEOREM
    assert mapped.result["content_id"] == receipt.content_id


def test_valid_translation_receipt_round_trips() -> None:
    api = _api()
    receipt = _translation()
    response = api.verify_receipt(receipt)
    assert response.status is VerificationStatus.SUCCEEDED
    assert response.authority is VerificationAuthority.BOUNDED
    assert response.result["kind"] == "translation_receipt"
    assert response.result["schema_version"] == LOGIC_TRANSLATION_RECEIPT_SCHEMA
    assert response.result["round_trip"]["receipt_id"] == receipt.receipt_id
    assert TRUSTED_PROOF_RECEIPT_SCHEMA in CLOSED_RECEIPT_SCHEMAS
    assert LOGIC_TRANSLATION_RECEIPT_SCHEMA in CLOSED_RECEIPT_SCHEMAS

    expectation = TranslationReceiptExpectation.from_receipt(receipt)
    matched = api.verify_receipt(receipt.to_dict(), expectation.to_dict())
    assert matched.status is VerificationStatus.SUCCEEDED
    assert matched.result["valid"] is True

    mismatched = api.verify_receipt(
        receipt,
        TranslationReceiptExpectation.from_dict(
            {
                **expectation.to_dict(),
                "source_identity": "src:identity:mutated",
            }
        ),
    )
    assert mismatched.status is VerificationStatus.INVALID
    assert mismatched.authority is VerificationAuthority.NONE


# ── Attestation boundary (unit surface) ───────────────────────────────────────


def test_simulated_attestation_cannot_report_proof_success() -> None:
    api = _api()
    receipt = _trusted()
    response = api.attest_receipt(
        receipt,
        backend_mode="simulated",
        backend_policy=_policy(backend_mode=AttestationBackendMode.SIMULATED),
        issued_at=NOW,
        expires_at=EXPIRES,
        request_id="req:sim",
    )
    assert response.status is VerificationStatus.PARTIAL
    assert response.authority is VerificationAuthority.ATTESTATION
    assert response.result["proof_success"] is False
    assert response.result["authoritative"] is False
    assert response.result["simulated"] is True
    assert response.result["prepared"] is True
    assert response.result["boundary"] == ATTESTATION_AUTHORITY_BOUNDARY_INTERFACE
    assert response.result["underlying_authority"] == "theorem"
    assert "cannot report proof success" in response.diagnostics[0]


def test_cryptographic_preparation_is_not_proof_success() -> None:
    api = _api()
    receipt = _trusted()
    response = api.attest_receipt(
        receipt.to_dict(),
        backend_mode=AttestationBackendMode.CRYPTOGRAPHIC,
        backend_policy=_policy(backend_mode=AttestationBackendMode.CRYPTOGRAPHIC),
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    assert response.status is VerificationStatus.SUCCEEDED
    assert response.authority is VerificationAuthority.ATTESTATION
    assert response.result["proof_success"] is False
    assert response.result["authoritative"] is False
    assert response.result["underlying_status"] == "proved"


def test_disabled_attestation_stays_unavailable() -> None:
    api = _api()
    response = api.attest_receipt({"receipt_id": "r"}, backend_mode="disabled")
    assert response.status is VerificationStatus.UNAVAILABLE
    assert response.result["proof_success"] is False
    assert "attestation_backend" in response.unsupported_features


@pytest.mark.parametrize(
    "bad_receipt",
    [
        None,
        {},
        {"schema_version": TRUSTED_PROOF_RECEIPT_SCHEMA, "receipt_id": "incomplete"},
    ],
)
def test_attestation_rejects_non_trusted_receipts(bad_receipt: Any) -> None:
    api = _api()
    response = api.attest_receipt(
        bad_receipt,
        backend_mode="simulated",
        backend_policy=_policy(),
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    assert response.status in {
        VerificationStatus.INVALID,
        VerificationStatus.ERROR,
    }
    assert response.result.get("proof_success") is False
