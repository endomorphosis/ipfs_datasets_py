"""Unit tests for ProviderCapabilityMatrix@2 (LFP2-009).

Acceptance:

* provider names, syntaxes, properties, and lanes cannot masquerade as families
* matrix is generated from one reviewed source (baseline provider catalog)
* cells are evidence-specific with typed provider / lane / family identities
* presence never claims availability or proof authority
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
    EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, SupportLevel
from ipfs_datasets_py.logic.families.namespaces import (
    NamespaceKind,
    family_id,
    lane_id,
    provider_id,
)
from ipfs_datasets_py.logic.families.provider_matrix_v2 import (
    BASELINE_PROVIDER_CAPABILITY_MATRIX_V2,
    GENERATION_SOURCE,
    GENERATION_TASK,
    MATRIX_V2_INTERFACE,
    MATRIX_V2_MODULE_VERSION,
    MATRIX_V2_SCHEMA_VERSION,
    CapabilityLifecycle,
    FamilyMasqueradeError,
    ProviderCapabilityCellV2,
    ProviderCapabilityFeatureV2,
    ProviderCapabilityMatrixV2,
    ProviderMatrixDriftError,
    ProviderMatrixV2Error,
    generate_provider_capability_matrix_v2,
    reject_family_masquerade,
    resolve_lane_for_matrix_family,
)
from ipfs_datasets_py.logic.families.providers import (
    BASELINE_PROVIDER_CATALOG,
    CATALOG_INTERFACE,
)
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    NON_FAMILY_PROFILE_LABELS,
)


# ---------------------------------------------------------------------------
# Interface / generation
# ---------------------------------------------------------------------------


def test_matrix_interface_and_generation_source() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    assert matrix.interface == MATRIX_V2_INTERFACE
    assert matrix.interface == "ProviderCapabilityMatrix@2"
    assert matrix.schema_version == MATRIX_V2_SCHEMA_VERSION
    assert matrix.version == MATRIX_V2_MODULE_VERSION
    assert matrix.generation_source == GENERATION_SOURCE
    assert matrix.generation_task == GENERATION_TASK
    assert matrix.catalog_interface == CATALOG_INTERFACE
    assert matrix.executable_matrix_interface == EXECUTABLE_PROVIDER_MATRIX_INTERFACE
    assert len(matrix) > 0
    assert matrix.frozen


def test_generated_from_baseline_catalog_only() -> None:
    matrix = generate_provider_capability_matrix_v2(frozen=True, validate=True)
    # Every matrix provider must come from the sealed catalog.
    for provider in matrix.provider_ids:
        assert provider in BASELINE_PROVIDER_CATALOG
    # Every executable-matrix provider with family support is present.
    for entry in EXECUTABLE_PROVIDER_MATRIX:
        catalog_entry = BASELINE_PROVIDER_CATALOG.get(entry.provider_id)
        if catalog_entry.family_support:
            assert entry.provider_id in matrix.provider_ids


def test_cells_are_evidence_specific() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    z3_cells = matrix.cells_for_provider("z3")
    assert z3_cells
    evidence_kinds = {cell.evidence_kind for cell in z3_cells}
    assert evidence_kinds  # at least one evidence kind
    # Multiple evidence kinds produce multiple cells for the same family.
    by_family_evidence = {
        (cell.family_id, cell.evidence_kind) for cell in z3_cells
    }
    assert len(by_family_evidence) == len(z3_cells)
    for cell in z3_cells:
        assert cell.provider.namespace is NamespaceKind.PROVIDER
        assert cell.lane.namespace is NamespaceKind.LANE
        assert cell.family.namespace is NamespaceKind.FAMILY
        assert cell.authority_ceiling in EvidenceAuthority
        assert cell.support_level in SupportLevel


def test_lane_mapped_from_executable_matrix_not_as_family() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    z3_cells = matrix.cells_for_provider("z3")
    assert all(cell.lane_id == "smt" for cell in z3_cells)
    # Lane label "smt" never appears as a family_id.
    assert "smt" not in matrix.family_ids
    assert all(cell.family_id in BASELINE_FAMILY_IDS for cell in matrix)

    lean_cells = matrix.cells_for_provider("lean")
    assert lean_cells
    assert all(cell.lane_id == "itp_kernel" for cell in lean_cells)
    assert "kernel" not in matrix.family_ids
    assert "lean" not in matrix.family_ids  # provider name is not a family


def test_resolve_lane_for_matrix_family() -> None:
    assert resolve_lane_for_matrix_family("smt").value == "smt"
    assert resolve_lane_for_matrix_family("runtime").value == "runtime_monitor"
    assert resolve_lane_for_matrix_family("kernel").value == "itp_kernel"
    with pytest.raises(ProviderMatrixDriftError):
        resolve_lane_for_matrix_family("not_a_lane")


# ---------------------------------------------------------------------------
# Masquerade rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "z3",
        "cvc5",
        "lean",
        "rocq",
        "vampire",
        "hammer",
        "proverif",
        "tamarin",
    ],
)
def test_provider_names_cannot_masquerade_as_families(label: str) -> None:
    with pytest.raises(FamilyMasqueradeError, match="provider"):
        reject_family_masquerade(label)
    with pytest.raises(FamilyMasqueradeError):
        BASELINE_PROVIDER_CAPABILITY_MATRIX_V2.cells_for_family(label)


@pytest.mark.parametrize(
    "label",
    ["smt", "smtlib2", "smt_lib2", "tptp", "spthy", "canonical_text"],
)
def test_syntaxes_cannot_masquerade_as_families(label: str) -> None:
    with pytest.raises(FamilyMasqueradeError, match="notation|syntax|lane"):
        reject_family_masquerade(label)


@pytest.mark.parametrize(
    "label",
    ["safety", "liveness", "satisfiability", "validity", "noninterference"],
)
def test_properties_cannot_masquerade_as_families(label: str) -> None:
    with pytest.raises(FamilyMasqueradeError, match="property"):
        reject_family_masquerade(label)


@pytest.mark.parametrize(
    "label",
    ["smt", "state_model", "runtime", "runtime_monitor", "atp", "advisor", "itp_kernel"],
)
def test_lanes_cannot_masquerade_as_families(label: str) -> None:
    with pytest.raises(FamilyMasqueradeError, match="lane|notation|syntax"):
        reject_family_masquerade(label)


@pytest.mark.parametrize("label", sorted(NON_FAMILY_PROFILE_LABELS))
def test_non_family_profile_labels_rejected(label: str) -> None:
    with pytest.raises(FamilyMasqueradeError, match="profile"):
        reject_family_masquerade(label)


def test_baseline_families_are_admitted() -> None:
    for family in ("first_order", "temporal", "hyperproperty", "program", "authorization"):
        reject_family_masquerade(family)  # does not raise
        assert family in BASELINE_FAMILY_IDS


def test_cell_rejects_cross_namespace_family_field() -> None:
    with pytest.raises(FamilyMasqueradeError, match="family namespace"):
        ProviderCapabilityCellV2(
            cell_id="bad.cell",
            provider=provider_id("z3"),
            lane=lane_id("smt"),
            family=provider_id("z3"),  # provider masquerading as family
            evidence_kind="model",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            support_level=SupportLevel.NATIVE,
        )


def test_cell_rejects_provider_family_collapse() -> None:
    # Construct a cell where provider value equals a real family — still reject
    # at validate_no_masquerades if they collapse (providers aren't families).
    matrix = ProviderCapabilityMatrixV2(frozen=False)
    cell = ProviderCapabilityCellV2(
        cell_id="z3.smt.first_order.model",
        provider=provider_id("z3"),
        lane=lane_id("smt"),
        family=family_id("first_order"),
        evidence_kind="model",
        authority_ceiling=EvidenceAuthority.BOUNDED,
        support_level=SupportLevel.NATIVE,
    )
    matrix.register(cell)
    matrix.validate_no_masquerades()


# ---------------------------------------------------------------------------
# Authority / availability posture
# ---------------------------------------------------------------------------


def test_presence_never_claims_availability_or_proof() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    assert matrix.is_available("z3") is False
    assert matrix.claims_proof("z3") is False
    with pytest.raises(ProviderMatrixV2Error):
        matrix.is_available("not_a_provider")


def test_advisory_cells_cannot_overclaim_authority() -> None:
    with pytest.raises(Exception, match="advisory|authority"):
        ProviderCapabilityCellV2(
            cell_id="ergoai.advisor.frame_logic.candidate",
            provider=provider_id("ergoai"),
            lane=lane_id("advisor"),
            family=family_id("frame_logic"),
            evidence_kind="candidate",
            authority_ceiling=EvidenceAuthority.AUTHORITATIVE,
            support_level=SupportLevel.NATIVE,
            advisory=True,
        )


def test_round_trip_serialization() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    payload = matrix.to_dict()
    assert payload["interface"] == "ProviderCapabilityMatrix@2"
    restored = ProviderCapabilityMatrixV2.from_dict(payload, frozen=True)
    assert restored.cell_ids == matrix.cell_ids
    assert restored.provider_ids == matrix.provider_ids
    assert restored.family_ids == matrix.family_ids
    assert json.loads(restored.to_json())["interface"] == MATRIX_V2_INTERFACE


def test_feature_round_trip() -> None:
    feature = ProviderCapabilityFeatureV2(
        feature_id="quantifiers",
        support_level=SupportLevel.NATIVE,
    )
    restored = ProviderCapabilityFeatureV2.from_dict(feature.to_dict())
    assert restored.feature_id == "quantifiers"
    assert restored.support_level is SupportLevel.NATIVE


def test_frozen_matrix_rejects_registration() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    cell = ProviderCapabilityCellV2(
        cell_id="extra.smt.first_order.model",
        provider=provider_id("z3"),
        lane=lane_id("smt"),
        family=family_id("first_order"),
        evidence_kind="model",
        authority_ceiling=EvidenceAuthority.BOUNDED,
        support_level=SupportLevel.NATIVE,
    )
    with pytest.raises(ProviderMatrixV2Error, match="frozen"):
        matrix.register(cell)


def test_lifecycle_values_are_closed() -> None:
    values = {item.value for item in CapabilityLifecycle}
    assert "declared" in values
    assert "executable" in values
    assert "advisory" in values
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    for cell in matrix:
        assert cell.lifecycle in CapabilityLifecycle


def test_executable_matrix_ids_covered() -> None:
    matrix = BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    covered = set(matrix.provider_ids)
    for provider_id_value in EXECUTABLE_PROVIDER_IDS:
        entry = BASELINE_PROVIDER_CATALOG.get(provider_id_value)
        if entry.family_support:
            assert provider_id_value in covered
