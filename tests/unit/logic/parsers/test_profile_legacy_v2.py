"""Unit tests for LogicProfileCatalog@2 and LegacyLogicBoundary@2 (LFP2-015).

Acceptance:

* Every registered parser emits shared ParseArtifact@2 / ElaborationArtifact@2
* Overloaded operators require a declared profile
* Legacy approximations require a declared profile and loss receipt
* Modal, temporal, resource, TDFOL, and CEC/DCEC import through the boundary
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.frontend_contract import (
    SharedFrontendConformance,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers.legacy_import_v2 import (
    CODE_OPF_AMBIGUITY,
    CODE_PROFILE_REQUIRED,
    CODE_UNKNOWN_SORT,
    ELABORATION_ARTIFACT_V2_INTERFACE,
    LEGACY_BOUNDARY_DESCRIPTOR_ID,
    LEGACY_LOGIC_BOUNDARY_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    LegacyImportFamily,
    LegacyLogicBoundary,
    LossKindV2,
    build_legacy_boundary_descriptor,
    import_legacy_dcec_v2,
    import_legacy_tdfol_v2,
    import_legacy_v2,
    import_modal_v2,
    import_resource_v2,
    import_temporal_v2,
    register_legacy_boundary,
)
from ipfs_datasets_py.logic.parsers.profile_catalog_v2 import (
    LOGIC_PROFILE_CATALOG_V2_INTERFACE,
    LossReceiptRequiredError,
    LogicProfileCatalog,
    ProfileFamilyKind,
    ProfileRequiredError,
    ProfileSourceKind,
    UnknownProfileError,
    default_profile_catalog,
    register_profile_catalog,
)
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import ParseStatus


# ---------------------------------------------------------------------------
# Catalog identity and seed coverage
# ---------------------------------------------------------------------------


def test_profile_catalog_interface_and_seed() -> None:
    catalog = default_profile_catalog()
    assert catalog.interface == LOGIC_PROFILE_CATALOG_V2_INTERFACE
    assert LOGIC_PROFILE_CATALOG_V2_INTERFACE == "LogicProfileCatalog@2"
    assert len(catalog) >= 15
    assert catalog.every_entry_emits_shared_artifacts()
    assert catalog.every_legacy_entry_requires_loss_receipt()
    assert catalog.every_overloaded_operator_requires_profile()


def test_catalog_publishes_temporal_modal_resource_tdfol_dcec() -> None:
    catalog = default_profile_catalog()
    families = {entry.family for entry in catalog}
    assert ProfileFamilyKind.TEMPORAL in families
    assert ProfileFamilyKind.MODAL in families
    assert ProfileFamilyKind.DEONTIC in families
    assert ProfileFamilyKind.RESOURCE in families  # separation_logic
    assert ProfileFamilyKind.TDFOL in families
    assert ProfileFamilyKind.DCEC in families
    assert ProfileFamilyKind.CEC in families  # event_calculus

    # Stable seed ids used by the importer defaults.
    for profile_id in (
        "ltl_infinite_discrete",
        "kripke_k",
        "deontic_monadic_strong",
        "separation_classical",
        "tdfol_default",
        "dcec_default",
        "cec_classical_import",
    ):
        entry = catalog.get(profile_id)
        assert entry.emits_shared_artifacts
        assert PARSE_ARTIFACT_V2_INTERFACE in entry.shared_artifact_interfaces
        assert ELABORATION_ARTIFACT_V2_INTERFACE in entry.shared_artifact_interfaces


def test_unknown_profile_fails_closed() -> None:
    catalog = default_profile_catalog()
    with pytest.raises(UnknownProfileError):
        catalog.get("not_a_real_profile")
    with pytest.raises(ProfileRequiredError):
        catalog.require(None)
    with pytest.raises(ProfileRequiredError):
        catalog.require("")


def test_overloaded_operator_requires_declared_profile() -> None:
    catalog = default_profile_catalog()
    with pytest.raises(ProfileRequiredError):
        catalog.require_profile_for_operator("O", None)
    with pytest.raises(ProfileRequiredError):
        catalog.require_profile_for_operator("F", "")
    entry = catalog.require_profile_for_operator("O", "deontic_monadic_strong")
    assert entry.profile_id == "deontic_monadic_strong"
    assert entry.requires_profile_for_operator("O")


def test_legacy_loss_receipt_gate() -> None:
    catalog = default_profile_catalog()
    with pytest.raises(LossReceiptRequiredError):
        catalog.require_loss_receipt(
            "tdfol_default",
            has_loss_receipt=False,
            is_legacy_approximation=True,
        )
    entry = catalog.require_loss_receipt(
        "tdfol_default",
        has_loss_receipt=True,
        is_legacy_approximation=True,
    )
    assert entry.source_kind is ProfileSourceKind.LEGACY_IMPORT


def test_catalog_registers_under_shared_frontend_conformance() -> None:
    catalog = default_profile_catalog()
    registry, admitted = catalog.register_all()
    assert isinstance(registry, SharedFrontendConformance)
    assert len(admitted) == len(catalog)
    for descriptor in admitted:
        validate_frontend_descriptor(descriptor)
        interfaces = descriptor.artifact_interfaces()
        assert PARSE_ARTIFACT_V2_INTERFACE in interfaces
        assert ELABORATION_ARTIFACT_V2_INTERFACE in interfaces
    # Every registered parser emits shared artifacts.
    assert all(
        PARSE_ARTIFACT_V2_INTERFACE in item.artifact_interfaces()
        for item in registry.descriptors()
    )


def test_register_profile_catalog_helper() -> None:
    registry, catalog = register_profile_catalog()
    assert len(registry) == len(catalog)
    assert catalog.interface == LOGIC_PROFILE_CATALOG_V2_INTERFACE


def test_catalog_round_trip_dict() -> None:
    catalog = default_profile_catalog()
    restored = LogicProfileCatalog.from_dict(catalog.to_dict())
    assert restored.profile_ids() == catalog.profile_ids()
    assert restored.every_entry_emits_shared_artifacts()


# ---------------------------------------------------------------------------
# Legacy boundary identity and gates
# ---------------------------------------------------------------------------


def test_legacy_boundary_interface() -> None:
    boundary = LegacyLogicBoundary()
    assert boundary.interface == LEGACY_LOGIC_BOUNDARY_V2_INTERFACE
    assert LEGACY_LOGIC_BOUNDARY_V2_INTERFACE == "LegacyLogicBoundary@2"
    descriptor = build_legacy_boundary_descriptor()
    assert descriptor.descriptor_id == LEGACY_BOUNDARY_DESCRIPTOR_ID
    validate_frontend_descriptor(descriptor)
    registry, admitted = register_legacy_boundary()
    assert admitted.descriptor_id == LEGACY_BOUNDARY_DESCRIPTOR_ID
    assert LEGACY_BOUNDARY_DESCRIPTOR_ID in registry


def test_import_without_profile_fails_closed() -> None:
    result = import_legacy_v2("O(report)", family=LegacyImportFamily.TDFOL)
    assert not result.ok
    assert result.status is ParseStatus.FAILED
    assert any(d.code == CODE_PROFILE_REQUIRED for d in result.diagnostics)
    # Shared artifacts are still emitted on failure.
    assert result.emits_shared_artifacts
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.has_loss_receipt


# ---------------------------------------------------------------------------
# Family import paths
# ---------------------------------------------------------------------------


def test_import_tdfol_with_profile_and_loss_receipt() -> None:
    result = import_legacy_tdfol_v2("O(report)")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.family == "tdfol"
    assert result.profile_id == "tdfol_default"
    assert result.emits_shared_artifacts
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.parse_artifact.interface == PARSE_ARTIFACT_V2_INTERFACE
    assert result.elaboration_artifact.interface == ELABORATION_ARTIFACT_V2_INTERFACE
    assert result.has_loss_receipt
    assert result.loss_receipts
    assert any(
        item.loss_kind is LossKindV2.LEGACY_APPROXIMATION
        or item.loss_kind is LossKindV2.AMBIGUITY_RESOLUTION
        or item.has_loss
        for item in result.loss_receipts
    )
    # O/P/F ambiguity is explicit under the declared profile.
    assert any(a.code == CODE_OPF_AMBIGUITY for a in result.ambiguities)


def test_import_tdfol_implies_right_assoc() -> None:
    result = import_legacy_tdfol_v2("p -> q -> r")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.IMPLIES
    assert result.root.arguments[1].kind is NodeKind.IMPLIES


def test_import_tdfol_unknown_sort_loss_receipt() -> None:
    result = import_legacy_tdfol_v2("forall x:Widget. P(x)")
    assert not result.ok
    assert any(d.code == CODE_UNKNOWN_SORT for d in result.diagnostics)
    assert result.emits_shared_artifacts
    assert result.has_loss_receipt


def test_import_dcec_with_profile() -> None:
    result = import_legacy_dcec_v2(
        "happens(turn_on, 1) and holds_at(light_on, 2)"
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.family == "dcec"
    assert result.profile_id == "dcec_default"
    assert result.emits_shared_artifacts
    assert result.has_loss_receipt


def test_import_dcec_sexpr_obligation() -> None:
    result = import_legacy_dcec_v2("(O report)")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.has_loss_receipt
    assert result.emits_shared_artifacts


def test_import_cec_event_calculus() -> None:
    result = import_legacy_v2(
        "initiates(turn_on, light_on, t)",
        family=LegacyImportFamily.EVENT_CALCULUS,
        profile_id="cec_classical_import",
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.emits_shared_artifacts
    assert result.has_loss_receipt


def test_import_temporal_under_declared_profile() -> None:
    result = import_temporal_v2("eventually p")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.family == "temporal"
    assert result.profile_id == "ltl_infinite_discrete"
    assert result.emits_shared_artifacts
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.loss_receipts


def test_import_modal_under_declared_profile() -> None:
    result = import_modal_v2("box p implies diamond p")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.family == "modal"
    assert result.profile_id == "kripke_k"
    assert result.emits_shared_artifacts
    assert result.loss_receipts


def test_import_deontic_modal_profile() -> None:
    result = import_legacy_v2(
        "obligated p",
        family=LegacyImportFamily.MODAL,
        profile_id="deontic_monadic_strong",
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.profile_id == "deontic_monadic_strong"
    assert result.emits_shared_artifacts


def test_import_resource_under_declared_profile() -> None:
    result = import_resource_v2("emp")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.family == "resource"
    assert result.profile_id == "separation_classical"
    assert result.emits_shared_artifacts
    assert result.loss_receipts


def test_family_profile_mismatch_fails_closed() -> None:
    result = import_legacy_v2(
        "eventually p",
        family=LegacyImportFamily.TEMPORAL,
        profile_id="tdfol_default",
    )
    assert not result.ok
    assert result.emits_shared_artifacts


def test_boundary_with_optional_default_profile() -> None:
    boundary = LegacyLogicBoundary(require_explicit_profile=False)
    result = boundary.import_text(
        "O(report)",
        family=LegacyImportFamily.TDFOL,
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.profile_id == "tdfol_default"
    assert result.emits_shared_artifacts
    assert result.has_loss_receipt


def test_joint_registration_catalog_and_boundary() -> None:
    registry, catalog = register_profile_catalog()
    registry, boundary_descriptor = register_legacy_boundary(registry)
    assert len(registry) == len(catalog) + 1
    assert boundary_descriptor.descriptor_id == LEGACY_BOUNDARY_DESCRIPTOR_ID
    for descriptor in registry.descriptors():
        assert PARSE_ARTIFACT_V2_INTERFACE in descriptor.artifact_interfaces()
