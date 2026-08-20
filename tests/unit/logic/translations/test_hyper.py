"""Unit tests for HyperpropertyTranslationEdges@1 (LFP2-020)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import PreservationRelation
from ipfs_datasets_py.logic.translations.hyper import (
    DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES,
    FEAT_EQUALITY,
    FEAT_FINITE_BOUND,
    FEAT_HYPER_ALTERNATION,
    FEAT_HYPER_QUANTIFIER,
    FEAT_INFORMATION_FLOW,
    FEAT_MULTI_TRACE,
    FEAT_NONINTERFERENCE,
    FEAT_OBSERVATION_MAP,
    FEAT_OBSERVATIONAL_DETERMINISM,
    FEAT_SELF_COMPOSITION,
    FEAT_TEMPORAL_ALWAYS,
    FEAT_TRACE_VARIABLE,
    FEAT_UNBOUNDED_COMPOSITION,
    HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE,
    SOURCE_HYPERPROPERTY,
    TARGET_FOL,
    TARGET_PRODUCT_SYSTEM,
    TARGET_SELF_COMPOSITION,
    TARGET_SMT,
    HyperCompositionReceipt,
    HyperLoweringResult,
    HyperWitnessFixture,
    HyperpropertyObligation,
    HyperpropertyTranslationEdge,
    HyperpropertyTranslationEdges,
    HyperpropertyTranslationError,
    LoweringStatus,
    ObligationKind,
    QuantifierKind,
    QuantifierShape,
    RouteKind,
    WitnessContractKind,
    assert_witness_fixture_preserved,
    build_hyperproperty_translation_edges,
    build_witness_fixture,
    count_quantifier_alternations,
    hyperproperty_translation_contracts,
    lower_hyperproperty_obligation,
    metamorphic_rename_obligation,
    quantifier_shape_of,
    reject_authority_promotion,
    reject_unbounded_composition,
    require_composition_receipt,
    system_copies_for_prefix,
)
from ipfs_datasets_py.logic.translations.planner import (
    TranslationPathPlanner,
    TranslationPathRequest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ni_features() -> tuple[str, ...]:
    return (
        FEAT_NONINTERFERENCE,
        FEAT_HYPER_QUANTIFIER,
        FEAT_TRACE_VARIABLE,
        FEAT_INFORMATION_FLOW,
        FEAT_OBSERVATION_MAP,
        FEAT_FINITE_BOUND,
        FEAT_SELF_COMPOSITION,
        FEAT_EQUALITY,
    )


def _od_features() -> tuple[str, ...]:
    return (
        FEAT_OBSERVATIONAL_DETERMINISM,
        FEAT_HYPER_QUANTIFIER,
        FEAT_TRACE_VARIABLE,
        FEAT_OBSERVATION_MAP,
        FEAT_FINITE_BOUND,
        FEAT_SELF_COMPOSITION,
        FEAT_EQUALITY,
    )


def _hyperltl_ff_features() -> tuple[str, ...]:
    return (
        FEAT_HYPER_QUANTIFIER,
        FEAT_TRACE_VARIABLE,
        FEAT_MULTI_TRACE,
        FEAT_TEMPORAL_ALWAYS,
        FEAT_FINITE_BOUND,
        FEAT_EQUALITY,
    )


def _eahyper_features() -> tuple[str, ...]:
    return (
        FEAT_HYPER_QUANTIFIER,
        FEAT_TRACE_VARIABLE,
        FEAT_MULTI_TRACE,
        FEAT_FINITE_BOUND,
        FEAT_SELF_COMPOSITION,
        FEAT_HYPER_ALTERNATION,
    )


def _ni_obligation(**overrides: object) -> HyperpropertyObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:ni:password_check",
        "kind": ObligationKind.NONINTERFERENCE,
        "quantifier_prefix": ("forall", "forall"),
        "features": _ni_features(),
        "trace_variables": ("pi1", "pi2"),
        "observations": ("out_status",),
        "low_inputs": ("public_user",),
        "high_inputs": ("password",),
        "matrix_statement": "G (obs_eq out_status)",
        "max_traces": 8,
        "max_pairs": 16,
        "max_steps": 32,
    }
    payload.update(overrides)
    return HyperpropertyObligation(**payload)  # type: ignore[arg-type]


def _od_obligation(**overrides: object) -> HyperpropertyObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:od:public_log",
        "kind": ObligationKind.OBSERVATIONAL_DETERMINISM,
        "quantifier_prefix": ("forall", "forall"),
        "features": _od_features(),
        "trace_variables": ("pi1", "pi2"),
        "observations": ("log_line",),
        "low_inputs": ("public_cmd",),
        "high_inputs": ("secret_token",),
        "matrix_statement": "G (obs_eq log_line)",
        "max_traces": 8,
        "max_pairs": 16,
        "max_steps": 32,
    }
    payload.update(overrides)
    return HyperpropertyObligation(**payload)  # type: ignore[arg-type]


def _hyperltl_ff_obligation(**overrides: object) -> HyperpropertyObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:hyper:ff_safety",
        "kind": ObligationKind.HYPERLTL,
        "quantifier_prefix": ("forall", "forall"),
        "features": _hyperltl_ff_features(),
        "trace_variables": ("pi1", "pi2"),
        "observations": ("ready",),
        "matrix_statement": "G (ready_pi1 <-> ready_pi2)",
        "max_traces": 8,
        "max_pairs": 16,
        "max_steps": 32,
    }
    payload.update(overrides)
    return HyperpropertyObligation(**payload)  # type: ignore[arg-type]


def _eahyper_obligation(**overrides: object) -> HyperpropertyObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:hyper:ea_fragment",
        "kind": ObligationKind.HYPERLTL,
        "quantifier_prefix": ("exists", "forall"),
        "features": _eahyper_features(),
        "trace_variables": ("pi1", "pi2"),
        "observations": ("out",),
        "matrix_statement": "F (out_pi1 = out_pi2)",
        "max_traces": 8,
        "max_pairs": 16,
        "max_steps": 32,
    }
    payload.update(overrides)
    return HyperpropertyObligation(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Catalog surface
# ---------------------------------------------------------------------------


def test_reviewed_catalog_interface_and_identity() -> None:
    catalog = build_hyperproperty_translation_edges()
    assert catalog.INTERFACE == HYPERPROPERTY_TRANSLATION_EDGES_INTERFACE
    assert catalog.INTERFACE == "HyperpropertyTranslationEdges@1"
    assert catalog.catalog_content_id.startswith("bafkrei")
    assert catalog.content_id == catalog.catalog_content_id
    assert len(catalog) >= 6
    assert catalog.edge_ids() == tuple(sorted(catalog.edge_ids()))


def test_catalog_covers_self_composition_smt_fol_product() -> None:
    catalog = build_hyperproperty_translation_edges()
    kinds = {edge.receipt.route_kind for edge in catalog}
    assert RouteKind.SELF_COMPOSITION in kinds
    assert RouteKind.BOUNDED_SMT in kinds
    assert RouteKind.BOUNDED_FOL in kinds
    assert RouteKind.PRODUCT_SYSTEM in kinds

    edge_ids = set(catalog.edge_ids())
    assert "noninterference_to_self_composition" in edge_ids
    assert "observational_determinism_to_self_composition" in edge_ids
    assert "hyperltl_forall_forall_to_product_system" in edge_ids
    assert "hyperltl_eahyper_fragment_to_self_composition" in edge_ids
    assert "noninterference_to_bounded_smt" in edge_ids
    assert "hyperltl_forall_forall_to_bounded_fol" in edge_ids


def test_catalog_round_trip() -> None:
    catalog = build_hyperproperty_translation_edges()
    restored = HyperpropertyTranslationEdges.from_dict(catalog.to_dict())
    assert restored.catalog_content_id == catalog.catalog_content_id
    assert restored.edge_ids() == catalog.edge_ids()
    assert [e.edge_content_id for e in restored] == [
        e.edge_content_id for e in catalog
    ]


def test_catalog_is_immutable() -> None:
    catalog = build_hyperproperty_translation_edges()
    with pytest.raises(FrozenInstanceError):
        catalog.description = "mutated"  # type: ignore[misc]


def test_catalog_identity_is_deterministic() -> None:
    a = build_hyperproperty_translation_edges()
    b = HyperpropertyTranslationEdges.reviewed()
    assert a.catalog_content_id == b.catalog_content_id
    assert a.edge_ids() == b.edge_ids()


def test_contracts_are_planner_ready() -> None:
    contracts = hyperproperty_translation_contracts()
    catalog = build_hyperproperty_translation_edges()
    assert len(contracts) == len(catalog)
    assert {c.contract_id for c in contracts} == set(catalog.edge_ids())
    assert all(c.contract_content_id.startswith("bafkrei") for c in contracts)
    assert all(
        c.authority_ceiling is EvidenceAuthority.BOUNDED for c in contracts
    )
    assert all(c.preservation is PreservationRelation.BOUNDED for c in contracts)


def test_default_registry_matches_factory() -> None:
    assert len(DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES) == len(
        build_hyperproperty_translation_edges()
    )
    assert (
        DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES.edge_ids()
        == build_hyperproperty_translation_edges().edge_ids()
    )


def test_every_edge_has_finite_bounds_and_witness_contract() -> None:
    catalog = build_hyperproperty_translation_edges()
    for edge in catalog:
        receipt = edge.receipt
        assert receipt.max_alternations >= 0
        assert receipt.max_system_copies >= 1
        assert receipt.max_traces >= 1
        assert receipt.max_pairs >= 1
        assert receipt.max_steps >= 1
        assert receipt.authorizes_universal_proof is False
        assert receipt.unbounded_proof is False
        assert receipt.may_promote_to_unbounded_proof is False
        assert receipt.witness_contract is not WitnessContractKind.NONE
        assert edge.contract.checker_route.startswith("differential:")
        assert "witness" in edge.contract.reconstruction_route or edge.contract.reconstruction_route.startswith(
            "replay:"
        )
        assert "bound:max_traces_" in " ".join(receipt.bound_ids())


# ---------------------------------------------------------------------------
# Quantifier analysis
# ---------------------------------------------------------------------------


def test_count_quantifier_alternations() -> None:
    assert count_quantifier_alternations(()) == 0
    assert count_quantifier_alternations(("forall",)) == 0
    assert count_quantifier_alternations(("forall", "forall")) == 0
    assert count_quantifier_alternations(("exists", "forall")) == 1
    assert count_quantifier_alternations(("forall", "exists", "forall")) == 2
    assert count_quantifier_alternations(
        (QuantifierKind.EXISTS, QuantifierKind.EXISTS, QuantifierKind.FORALL)
    ) == 1


def test_quantifier_shape_classification() -> None:
    assert quantifier_shape_of(("forall", "forall")) is QuantifierShape.FORALL_FORALL
    assert quantifier_shape_of(("exists", "exists")) is QuantifierShape.EXISTS_EXISTS
    assert quantifier_shape_of(("forall", "exists")) is QuantifierShape.FORALL_EXISTS
    assert quantifier_shape_of(("exists", "forall")) is QuantifierShape.EXISTS_FORALL
    assert quantifier_shape_of(("forall", "forall", "forall")) is QuantifierShape.FORALL_STAR
    assert quantifier_shape_of(("forall", "exists", "forall")) is QuantifierShape.GENERAL
    assert quantifier_shape_of(("forall",)) is QuantifierShape.SINGLE_FORALL


def test_system_copies_for_prefix() -> None:
    assert system_copies_for_prefix(("forall", "forall")) == 2
    assert system_copies_for_prefix(("exists", "forall", "forall")) == 3


# ---------------------------------------------------------------------------
# Composition receipts
# ---------------------------------------------------------------------------


def test_composition_receipt_rejects_omitted_fields() -> None:
    payload: dict[str, object] = {
        "max_alternations": 0,
        "max_system_copies": 2,
        "max_traces": 8,
        "max_pairs": 16,
        "max_steps": 32,
        "quantifier_shape": QuantifierShape.FORALL_FORALL.value,
        "witness_contract": WitnessContractKind.COUNTEREXAMPLE.value,
        "route_kind": RouteKind.SELF_COMPOSITION.value,
    }
    for field_name in (
        "max_alternations",
        "max_system_copies",
        "max_traces",
        "max_pairs",
        "max_steps",
        "quantifier_shape",
        "witness_contract",
        "route_kind",
    ):
        broken = dict(payload)
        broken[field_name] = None
        with pytest.raises(
            HyperpropertyTranslationError, match="cannot be omitted"
        ):
            HyperCompositionReceipt.from_dict(broken)


def test_composition_receipt_rejects_universal_proof() -> None:
    with pytest.raises(
        HyperpropertyTranslationError, match="universal proof"
    ):
        HyperCompositionReceipt(
            max_alternations=0,
            max_system_copies=2,
            max_traces=8,
            max_pairs=16,
            max_steps=32,
            quantifier_shape=QuantifierShape.FORALL_FORALL,
            witness_contract=WitnessContractKind.COUNTEREXAMPLE,
            route_kind=RouteKind.SELF_COMPOSITION,
            authorizes_universal_proof=True,
        )


def test_composition_receipt_rejects_none_witness() -> None:
    with pytest.raises(HyperpropertyTranslationError, match="witness_contract"):
        HyperCompositionReceipt(
            max_alternations=0,
            max_system_copies=2,
            max_traces=8,
            max_pairs=16,
            max_steps=32,
            quantifier_shape=QuantifierShape.FORALL_FORALL,
            witness_contract=WitnessContractKind.NONE,
            route_kind=RouteKind.SELF_COMPOSITION,
        )


def test_require_composition_receipt_helper() -> None:
    receipt = require_composition_receipt(
        max_alternations=1,
        max_system_copies=4,
        max_traces=16,
        max_pairs=32,
        max_steps=64,
        quantifier_shape="exists_forall",
        witness_contract="counterexample_or_clean_sample",
        route_kind="self_composition",
    )
    assert receipt.max_alternations == 1
    assert receipt.quantifier_shape is QuantifierShape.EXISTS_FORALL


def test_receipt_admits_and_rejects_alternation() -> None:
    receipt = require_composition_receipt(
        max_alternations=0,
        max_system_copies=2,
        max_traces=8,
        max_pairs=16,
        max_steps=32,
        quantifier_shape="forall_forall",
        witness_contract="counterexample",
    )
    ok, reason = receipt.admits(alternations=0, system_copies=2)
    assert ok and reason == ""
    ok, reason = receipt.admits(alternations=1, system_copies=2)
    assert not ok
    assert "unsupported alternation" in reason


# ---------------------------------------------------------------------------
# Accepted transformations + witness fixtures
# ---------------------------------------------------------------------------


def test_noninterference_to_self_composition_supported() -> None:
    result = lower_hyperproperty_obligation(
        _ni_obligation(), TARGET_SELF_COMPOSITION
    )
    assert result.is_supported
    assert result.status is LoweringStatus.SUPPORTED
    assert result.edge_id == "noninterference_to_self_composition"
    assert result.authority_ceiling is EvidenceAuthority.BOUNDED
    assert result.authorizes_universal_proof is False
    assert result.receipt is not None
    assert result.receipt.max_system_copies == 2
    assert result.receipt.max_alternations == 0
    assert result.target_obligation["system_copies"] == 2
    assert result.target_obligation["alternations"] == 0
    assert result.target_obligation["authorizes_universal_proof"] is False
    assert result.witness_fixture is not None
    assert result.witness_fixture.checker_route.startswith("differential:")
    assert result.witness_fixture.system_copies == 2
    assert result.witness_fixture.quantifier_prefix == ("forall", "forall")
    assert result.witness_fixture.authorizes_universal_proof is False
    assert len(result.witness_fixture.differential_pairs) >= 1


def test_noninterference_to_bounded_smt_has_witness_fixture() -> None:
    result = lower_hyperproperty_obligation(_ni_obligation(), TARGET_SMT)
    assert result.is_supported
    assert result.edge_id == "noninterference_to_bounded_smt"
    assert result.target_obligation["encoding"] == "smt-self-composition-sketch/v1"
    assert result.witness_fixture is not None
    assert result.witness_fixture.edge_id == result.edge_id
    assert "bound:max_traces_" in " ".join(result.witness_fixture.bound_ids)


def test_hyperltl_ff_to_product_and_fol() -> None:
    product = lower_hyperproperty_obligation(
        _hyperltl_ff_obligation(), TARGET_PRODUCT_SYSTEM
    )
    fol = lower_hyperproperty_obligation(_hyperltl_ff_obligation(), TARGET_FOL)
    assert product.is_supported
    assert fol.is_supported
    assert product.edge_id == "hyperltl_forall_forall_to_product_system"
    assert fol.edge_id == "hyperltl_forall_forall_to_bounded_fol"
    assert product.witness_fixture is not None
    assert fol.witness_fixture is not None
    assert product.target_obligation["product_kind"] == "synchronous"
    assert fol.target_obligation["encoding"] == "fol-self-composition-sketch/v1"


def test_observational_determinism_route() -> None:
    result = lower_hyperproperty_obligation(
        _od_obligation(), TARGET_SELF_COMPOSITION
    )
    assert result.is_supported
    assert result.edge_id == "observational_determinism_to_self_composition"
    assert result.witness_fixture is not None
    assert result.witness_fixture.observations == ("log_line",)


def test_eahyper_single_alternation_supported() -> None:
    result = lower_hyperproperty_obligation(
        _eahyper_obligation(), TARGET_SELF_COMPOSITION
    )
    assert result.is_supported, result.reason
    assert result.edge_id == "hyperltl_eahyper_fragment_to_self_composition"
    assert result.receipt is not None
    assert result.receipt.max_alternations == 1
    assert result.target_obligation["alternations"] == 1
    assert result.target_obligation["quantifier_shape"] == "exists_forall"
    assert result.witness_fixture is not None


def test_supported_lowering_content_id_stable() -> None:
    a = lower_hyperproperty_obligation(
        _ni_obligation(), TARGET_SELF_COMPOSITION, plan=False
    )
    b = lower_hyperproperty_obligation(
        _ni_obligation(), TARGET_SELF_COMPOSITION, plan=False
    )
    assert a.is_supported and b.is_supported
    assert a.content_id == b.content_id
    assert a.content_id.startswith("bafkrei")


def test_build_witness_fixture_rejects_universal_proof() -> None:
    edge = DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES.get(
        "noninterference_to_self_composition"
    )
    fixture = build_witness_fixture(_ni_obligation(), edge)
    assert fixture.authorizes_universal_proof is False
    with pytest.raises(HyperpropertyTranslationError, match="universal proof"):
        HyperWitnessFixture(
            fixture_id="fixture:bad",
            edge_id=edge.edge_id,
            checker_route="differential:x",
            reconstruction_route="replay:x",
            witness_contract=WitnessContractKind.COUNTEREXAMPLE,
            system_copies=2,
            quantifier_prefix=("forall", "forall"),
            authorizes_universal_proof=True,
        )


# ---------------------------------------------------------------------------
# Fail-closed: unsupported alternation / unbounded composition
# ---------------------------------------------------------------------------


def test_unsupported_alternation_fails_on_noninterference_route() -> None:
    """∀∃ has one alternation; noninterference edges allow zero."""

    obligation = _ni_obligation(
        quantifier_prefix=("forall", "exists"),
        features=_ni_features() + (FEAT_HYPER_ALTERNATION,),
    )
    result = lower_hyperproperty_obligation(
        obligation, TARGET_SELF_COMPOSITION
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert "alternation" in result.reason.lower() or "shape" in result.reason.lower()
    assert result.witness_fixture is None
    assert not result.target_obligation


def test_nested_alternation_fails_eahyper_ceiling() -> None:
    """exists forall exists has two alternations; EAHyper ceiling is one."""

    obligation = _eahyper_obligation(
        quantifier_prefix=("exists", "forall", "exists"),
        trace_variables=("pi1", "pi2", "pi3"),
        features=_eahyper_features(),
    )
    result = lower_hyperproperty_obligation(
        obligation, TARGET_SELF_COMPOSITION
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert "alternation" in result.reason.lower()
    assert result.witness_fixture is None


def test_unbounded_composition_fails() -> None:
    obligation = _ni_obligation(
        max_traces=None,
        max_pairs=None,
        max_steps=None,
        unbounded=True,
    )
    result = lower_hyperproperty_obligation(
        obligation, TARGET_SELF_COMPOSITION
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert "unbounded" in result.reason.lower()
    assert FEAT_UNBOUNDED_COMPOSITION in result.unsupported_constructs


def test_missing_finite_bounds_fails() -> None:
    obligation = _ni_obligation(
        max_traces=None,
        max_pairs=16,
        max_steps=32,
        unbounded=False,
    )
    result = lower_hyperproperty_obligation(
        obligation, TARGET_SELF_COMPOSITION
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert "unbounded" in result.reason.lower() or "finite" in result.reason.lower()


def test_reject_unbounded_composition_helper() -> None:
    with pytest.raises(HyperpropertyTranslationError, match="unbounded"):
        reject_unbounded_composition(
            unbounded=True,
            max_traces=None,
            max_pairs=None,
            max_steps=None,
        )
    with pytest.raises(HyperpropertyTranslationError, match="unbounded"):
        reject_unbounded_composition(
            unbounded=False,
            max_traces=8,
            max_pairs=None,
            max_steps=32,
        )
    # Finite bounds accepted.
    reject_unbounded_composition(
        unbounded=False,
        max_traces=8,
        max_pairs=16,
        max_steps=32,
    )


def test_reject_authority_promotion() -> None:
    with pytest.raises(HyperpropertyTranslationError, match="universal proof"):
        reject_authority_promotion(
            authority=EvidenceAuthority.BOUNDED,
            authorizes_universal_proof=True,
        )
    with pytest.raises(HyperpropertyTranslationError, match="not permitted"):
        reject_authority_promotion(
            authority=EvidenceAuthority.AUTHORITATIVE,
            authorizes_universal_proof=False,
        )
    reject_authority_promotion(
        authority=EvidenceAuthority.BOUNDED,
        authorizes_universal_proof=False,
    )


def test_unbounded_construct_feature_fails() -> None:
    obligation = _ni_obligation(
        features=_ni_features() + (FEAT_UNBOUNDED_COMPOSITION,),
        constructs=("construct:unbounded_composition",),
    )
    result = lower_hyperproperty_obligation(
        obligation, TARGET_SELF_COMPOSITION
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert any("unbounded" in item for item in result.unsupported_constructs)


def test_excess_system_copies_fails() -> None:
    obligation = _ni_obligation(
        quantifier_prefix=("forall", "forall", "forall"),
        trace_variables=("pi1", "pi2", "pi3"),
        features=_ni_features() + (FEAT_MULTI_TRACE,),
    )
    result = lower_hyperproperty_obligation(
        obligation, TARGET_SELF_COMPOSITION
    )
    assert result.status is LoweringStatus.UNSUPPORTED
    assert (
        "system copies" in result.reason.lower()
        or "shape" in result.reason.lower()
        or "feature" in result.reason.lower()
    )


def test_obligation_cannot_mix_unbounded_flag_with_finite_bounds() -> None:
    with pytest.raises(HyperpropertyTranslationError, match="unbounded"):
        HyperpropertyObligation(
            obligation_id="obl:bad",
            kind=ObligationKind.NONINTERFERENCE,
            quantifier_prefix=("forall", "forall"),
            max_traces=8,
            max_pairs=16,
            max_steps=32,
            unbounded=True,
        )


# ---------------------------------------------------------------------------
# Planner integration
# ---------------------------------------------------------------------------


def test_register_with_planner_and_plan_path() -> None:
    catalog = build_hyperproperty_translation_edges()
    planner = catalog.register_with_planner()
    assert isinstance(planner, TranslationPathPlanner)
    receipt = catalog.plan(
        TranslationPathRequest(
            source_family_id=SOURCE_HYPERPROPERTY,
            target_family_id=TARGET_SELF_COMPOSITION,
            source_profile_id="noninterference",
            target_profile_id="finite_2_copies",
            features=_ni_features(),
            claimed_preservation=PreservationRelation.BOUNDED,
            claimed_authority=EvidenceAuthority.BOUNDED,
            require_counterexample_safe=True,
        )
    )
    assert receipt.edge_contract_ids
    assert "noninterference_to_self_composition" in receipt.edge_contract_ids
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED


def test_supported_lowering_with_plan_receipt() -> None:
    result = lower_hyperproperty_obligation(
        _ni_obligation(), TARGET_SELF_COMPOSITION, plan=True
    )
    assert result.is_supported
    assert result.path_receipt is not None
    assert result.path_receipt.path_content_id.startswith("bafkrei")


# ---------------------------------------------------------------------------
# Metamorphic / differential fixtures
# ---------------------------------------------------------------------------


def test_metamorphic_rename_preserves_witness_and_authority() -> None:
    original = _ni_obligation()
    renamed = metamorphic_rename_obligation(original, suffix="_m1")
    a = lower_hyperproperty_obligation(original, TARGET_SELF_COMPOSITION)
    b = lower_hyperproperty_obligation(renamed, TARGET_SELF_COMPOSITION)
    assert a.is_supported and b.is_supported
    assert_witness_fixture_preserved(a, b)
    assert a.edge_id == b.edge_id
    assert a.authority_ceiling is b.authority_ceiling
    assert a.receipt is not None and b.receipt is not None
    assert a.receipt.max_system_copies == b.receipt.max_system_copies


@pytest.mark.parametrize(
    "target",
    [TARGET_SELF_COMPOSITION, TARGET_SMT],
)
def test_metamorphic_feature_reorder_preserves_edge(target: str) -> None:
    features = list(_ni_features())
    forward = _ni_obligation(features=tuple(features))
    reverse = _ni_obligation(features=tuple(reversed(features)))
    a = lower_hyperproperty_obligation(forward, target)
    b = lower_hyperproperty_obligation(reverse, target)
    assert a.is_supported and b.is_supported
    assert a.edge_id == b.edge_id
    assert a.authority_ceiling is b.authority_ceiling
    assert a.witness_fixture is not None and b.witness_fixture is not None
    assert (
        a.witness_fixture.witness_contract
        is b.witness_fixture.witness_contract
    )


def test_metamorphic_dual_targets_keep_bounded_authority() -> None:
    sc = lower_hyperproperty_obligation(
        _ni_obligation(), TARGET_SELF_COMPOSITION
    )
    smt = lower_hyperproperty_obligation(_ni_obligation(), TARGET_SMT)
    assert sc.is_supported and smt.is_supported
    assert sc.authority_ceiling is EvidenceAuthority.BOUNDED
    assert smt.authority_ceiling is EvidenceAuthority.BOUNDED
    assert sc.authorizes_universal_proof is False
    assert smt.authorizes_universal_proof is False
    assert sc.witness_fixture is not None
    assert smt.witness_fixture is not None


def test_differential_pairs_are_compact_recipes() -> None:
    result = lower_hyperproperty_obligation(
        _ni_obligation(), TARGET_SELF_COMPOSITION
    )
    assert result.witness_fixture is not None
    pairs = result.witness_fixture.differential_pairs
    assert pairs
    for pair in pairs:
        assert "pair_id" in pair
        assert "role" in pair
        assert pair["role"] in {"counterexample_candidate", "clean_sample"}
        assert pair["observation_fields"] == ["out_status"]


# ---------------------------------------------------------------------------
# Serialization / edge integrity
# ---------------------------------------------------------------------------


def test_obligation_round_trip() -> None:
    obligation = _ni_obligation()
    restored = HyperpropertyObligation.from_dict(obligation.to_dict())
    assert restored == obligation
    assert restored.alternations == 0
    assert restored.system_copies == 2
    assert restored.quantifier_shape is QuantifierShape.FORALL_FORALL


def test_edge_round_trip() -> None:
    edge = DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES.get(
        "noninterference_to_self_composition"
    )
    restored = HyperpropertyTranslationEdge.from_dict(edge.to_dict())
    assert restored.edge_id == edge.edge_id
    assert restored.edge_content_id == edge.edge_content_id
    assert restored.receipt.max_system_copies == 2


def test_edge_rejects_authoritative_ceiling() -> None:
    good = DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES.get(
        "noninterference_to_self_composition"
    )
    # Rebuild contract with elevated authority via dict mutation attempt.
    payload = good.to_dict()
    contract = dict(payload["contract"])
    contract["authority_ceiling"] = EvidenceAuthority.AUTHORITATIVE.value
    # Also drop proof polarity constraints that may conflict.
    payload["contract"] = contract
    payload["edge_content_id"] = ""
    with pytest.raises(
        HyperpropertyTranslationError,
        match="independent or authoritative|BOUNDED authority|authority",
    ):
        HyperpropertyTranslationEdge.from_dict(payload)


def test_unknown_edge_id() -> None:
    with pytest.raises(HyperpropertyTranslationError, match="unknown"):
        DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES.get("not_an_edge")


def test_lowering_result_supported_requires_fixture() -> None:
    edge = DEFAULT_HYPERPROPERTY_TRANSLATION_EDGES.get(
        "noninterference_to_self_composition"
    )
    with pytest.raises(
        HyperpropertyTranslationError, match="witness fixture"
    ):
        HyperLoweringResult(
            status=LoweringStatus.SUPPORTED,
            edge_id=edge.edge_id,
            target_family_id=TARGET_SELF_COMPOSITION,
            authority_ceiling=EvidenceAuthority.BOUNDED,
            receipt=edge.receipt,
            target_obligation={"encoding": "x"},
            witness_fixture=None,
        )


def test_source_family_is_hyperproperty() -> None:
    catalog = build_hyperproperty_translation_edges()
    for edge in catalog:
        assert edge.source_family_id == SOURCE_HYPERPROPERTY
        assert edge.contract.source.family_id == SOURCE_HYPERPROPERTY
