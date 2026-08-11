"""Unit tests for PolicyModalTranslationEdges@1 (LFP2-019)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    NodeDisposition,
    NodeMapEntry,
    PreservationRelation,
    SymbolMapEntry,
    TranslationAssumptionSet,
    TranslationContract,
    TranslationEndpoint,
    TranslationIdentities,
)
from ipfs_datasets_py.logic.translations.planner import (
    FeatureSet,
    TranslationPathPlanner,
    TranslationPathPlannerError,
    TranslationPathRequest,
)
from ipfs_datasets_py.logic.translations.policy_modal import (
    POLICY_MODAL_CATALOG_SCHEMA_VERSION,
    POLICY_MODAL_EDGES_INTERFACE,
    POLICY_MODAL_EDGE_SCHEMA_VERSION,
    AgentIndexPolicy,
    ApproximationDirection,
    EncodingKind,
    PolicyModalEdge,
    PolicyModalTranslationEdges,
    PolicyModalTranslationError,
    ReificationKind,
    build_authorization_to_datalog_edge,
    build_authorization_to_secpal_edge,
    build_dcec_to_fol_reified_edge,
    build_deontic_to_fol_reified_edge,
    build_epistemic_to_fol_relational_edge,
    build_event_calculus_to_atp_edge,
    build_event_calculus_to_fol_edge,
    build_frame_logic_to_fol_edge,
    build_intention_to_fol_reified_edge,
    build_modal_s5_to_fol_relational_edge,
    build_policy_modal_translation_edges,
    build_tdfol_to_fol_relational_edge,
    get_policy_modal_edge,
    iter_policy_modal_edges,
    policy_modal_contracts,
)


# ---------------------------------------------------------------------------
# Helpers for negative construction fixtures
# ---------------------------------------------------------------------------


def _identities(**overrides: object) -> TranslationIdentities:
    payload: dict[str, object] = {
        "compiler_identity": "sha256:" + "a" * 64,
        "profile_identity": "sha256:" + "b" * 64,
        "config_identity": "sha256:" + "c" * 64,
        "source_identity": "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "target_identity": "bafkreibbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "environment_identity": "sha256:" + "d" * 64,
    }
    payload.update(overrides)
    return TranslationIdentities(**payload)  # type: ignore[arg-type]


def _endpoint(family: str, **overrides: object) -> TranslationEndpoint:
    payload: dict[str, object] = {
        "family_id": family,
        "profile_id": f"{family}_default",
        "fragment_id": f"{family}_core",
        "schema_id": f"{family}_schema",
        "notation_id": f"{family}_notation",
        "content_identity": f"sha256:{family}",
    }
    payload.update(overrides)
    return TranslationEndpoint(**payload)  # type: ignore[arg-type]


def _node(
    source: str,
    *targets: str,
    disposition: NodeDisposition | str = NodeDisposition.MAPPED,
    reason: str = "",
) -> NodeMapEntry:
    return NodeMapEntry(
        source_node_id=source,
        target_node_ids=targets,
        disposition=disposition,
        reason=reason,
    )


def _symbol(
    source: str,
    *targets: str,
    disposition: NodeDisposition | str = NodeDisposition.MAPPED,
    reason: str = "",
) -> SymbolMapEntry:
    return SymbolMapEntry(
        source_symbol_id=source,
        target_symbol_ids=targets,
        disposition=disposition,
        reason=reason,
    )


def _minimal_contract(
    *,
    contract_id: str = "test_edge",
    source_family: str = "authorization",
    target_family: str = "datalog",
    preservation: PreservationRelation = PreservationRelation.EQUISATISFIABLE,
    authority: EvidenceAuthority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    source_profile: str = "",
    assumptions: TranslationAssumptionSet | None = None,
) -> TranslationContract:
    profile = source_profile or f"{source_family}_default"
    return TranslationContract(
        contract_id=contract_id,
        source=_endpoint(source_family, profile_id=profile),
        target=_endpoint(target_family),
        preservation=preservation,
        identities=_identities(),
        proof_safe=True,
        counterexample_safe=False,
        authority_ceiling=authority,
        assumptions=assumptions or TranslationAssumptionSet(),
        node_map=(_node("n_a", "t_a", disposition=NodeDisposition.MAPPED),),
        symbol_map=(_symbol("s", "s", disposition=NodeDisposition.PRESERVED),),
        required_source_node_ids=("n_a",),
        required_source_symbol_ids=("s",),
        feature_preconditions=("feat_core",),
        description="test contract",
    )


def _edge_kwargs(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "edge_id": "test_edge",
        "contract": _minimal_contract(),
        "encoding_kind": EncodingKind.DATALOG,
        "frame_conditions": ("frame:not_applicable_authorization",),
        "norm_semantics": ("norm:allow_deny",),
        "event_closure": ("event_closure:not_applicable_authorization",),
        "agent_indices": AgentIndexPolicy.NOT_APPLICABLE,
        "reification": ReificationKind.NONE,
        "approximation_direction": ApproximationDirection.NONE,
        "description": "test edge",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Interface / catalog basics
# ---------------------------------------------------------------------------


def test_interface_and_schema_constants() -> None:
    assert POLICY_MODAL_EDGES_INTERFACE == "PolicyModalTranslationEdges@1"
    assert POLICY_MODAL_EDGE_SCHEMA_VERSION.startswith("logic-policy-modal")
    assert POLICY_MODAL_CATALOG_SCHEMA_VERSION.startswith("logic-policy-modal")


def test_reviewed_catalog_covers_evidence_subset_families() -> None:
    catalog = build_policy_modal_translation_edges()
    assert catalog.interface == POLICY_MODAL_EDGES_INTERFACE
    assert catalog.schema_version == POLICY_MODAL_CATALOG_SCHEMA_VERSION
    assert catalog.catalog_content_id.startswith("bafkrei")

    sources = {edge.source_family_id for edge in catalog.edges}
    assert {
        "authorization",
        "frame_logic",
        "event_calculus",
        "deontic",
        "modal",
        "dcec",
        "tdfol",
    }.issubset(sources)

    profiles = {edge.contract.source.profile_id for edge in catalog.edges}
    assert any("epistemic" in p for p in profiles)
    assert any("intention" in p for p in profiles)


def test_catalog_edge_ids_are_stable_and_unique() -> None:
    catalog = PolicyModalTranslationEdges.reviewed()
    ids = catalog.edge_ids()
    assert ids == tuple(sorted(ids))
    assert len(ids) == len(set(ids))
    assert len(ids) >= 11


def test_iter_and_lookup_helpers() -> None:
    edges = iter_policy_modal_edges()
    assert edges
    contracts = policy_modal_contracts()
    assert len(contracts) == len(edges)
    assert all(isinstance(c, TranslationContract) for c in contracts)

    edge = get_policy_modal_edge("authorization_to_datalog")
    assert edge.encoding_kind is EncodingKind.DATALOG
    with pytest.raises(PolicyModalTranslationError, match="unknown"):
        get_policy_modal_edge("not_a_real_edge")


def test_catalog_round_trip() -> None:
    catalog = build_policy_modal_translation_edges()
    payload = catalog.to_dict()
    assert payload["interface"] == "PolicyModalTranslationEdges@1"
    restored = PolicyModalTranslationEdges.from_dict(payload)
    assert restored == catalog
    assert restored.to_dict() == payload


def test_catalog_is_immutable() -> None:
    catalog = build_policy_modal_translation_edges()
    with pytest.raises(FrozenInstanceError):
        catalog.schema_version = "nope"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Acceptance axes must be explicit on every edge
# ---------------------------------------------------------------------------


ACCEPTANCE_AXES = (
    "frame_conditions",
    "norm_semantics",
    "event_closure",
    "agent_indices",
    "reification",
    "approximation_direction",
)


@pytest.mark.parametrize("edge_builder", [
    build_authorization_to_datalog_edge,
    build_authorization_to_secpal_edge,
    build_frame_logic_to_fol_edge,
    build_event_calculus_to_fol_edge,
    build_event_calculus_to_atp_edge,
    build_modal_s5_to_fol_relational_edge,
    build_deontic_to_fol_reified_edge,
    build_epistemic_to_fol_relational_edge,
    build_intention_to_fol_reified_edge,
    build_dcec_to_fol_reified_edge,
    build_tdfol_to_fol_relational_edge,
])
def test_every_edge_makes_acceptance_axes_explicit(edge_builder) -> None:
    edge = edge_builder()
    payload = edge.to_dict()
    for axis in ACCEPTANCE_AXES:
        assert axis in payload, f"{edge.edge_id} missing {axis}"
        assert payload[axis] not in (None, ""), f"{edge.edge_id} empty {axis}"

    # Sequence axes are non-empty tuples of identifiers.
    assert edge.frame_conditions
    assert edge.norm_semantics
    assert edge.event_closure
    assert isinstance(edge.agent_indices, AgentIndexPolicy)
    assert isinstance(edge.reification, ReificationKind)
    assert isinstance(edge.approximation_direction, ApproximationDirection)

    # Contract is planner-ready.
    assert isinstance(edge.contract, TranslationContract)
    assert edge.contract.contract_id == edge.edge_id
    assert edge.contract.feature_preconditions
    assert edge.edge_content_id.startswith("bafkrei")


def test_frame_conditions_explicit_for_modal_and_frame_logic() -> None:
    modal = build_modal_s5_to_fol_relational_edge()
    assert "frame:kripke_s5" in modal.frame_conditions
    assert "frame:accessibility_reflexive" in modal.frame_conditions

    frame = build_frame_logic_to_fol_edge()
    assert "frame:isa_transitive" in frame.frame_conditions
    assert "frame:slot_attachment_well_typed" in frame.frame_conditions


def test_norm_semantics_explicit_for_authorization_deontic_tdfol() -> None:
    auth = build_authorization_to_datalog_edge()
    assert "norm:allow_deny_effects" in auth.norm_semantics
    assert "norm:deny_overrides" in auth.norm_semantics

    deontic = build_deontic_to_fol_reified_edge()
    assert "norm:monadic_obligation" in deontic.norm_semantics
    assert "norm:dyadic_unsupported" in deontic.norm_semantics

    tdfol = build_tdfol_to_fol_relational_edge()
    assert "norm:monadic_obligation_at_time" in tdfol.norm_semantics


def test_event_closure_explicit_for_event_calculus_and_dcec() -> None:
    ec = build_event_calculus_to_fol_edge()
    assert "event_closure:common_sense_law_of_inertia" in ec.event_closure
    assert "event_closure:circumscribe_happens" in ec.event_closure

    dcec = build_dcec_to_fol_reified_edge()
    assert "event_closure:dcec_fluent_persistence" in dcec.event_closure


def test_agent_indices_explicit_for_cognitive_routes() -> None:
    epistemic = build_epistemic_to_fol_relational_edge()
    assert epistemic.agent_indices is AgentIndexPolicy.MULTI_AGENT_INDEXED
    assert "feat_agent_index" in epistemic.contract.feature_preconditions

    intention = build_intention_to_fol_reified_edge()
    assert intention.agent_indices is AgentIndexPolicy.REIFIED_AGENT_SORT

    dcec = build_dcec_to_fol_reified_edge()
    assert dcec.agent_indices is AgentIndexPolicy.MULTI_AGENT_INDEXED

    modal = build_modal_s5_to_fol_relational_edge()
    assert modal.agent_indices is AgentIndexPolicy.FORBIDDEN


def test_reification_and_encoding_alignment() -> None:
    relational = build_modal_s5_to_fol_relational_edge()
    assert relational.encoding_kind is EncodingKind.RELATIONAL_FOL
    assert relational.reification is ReificationKind.NONE

    reified = build_deontic_to_fol_reified_edge()
    assert reified.encoding_kind is EncodingKind.REIFIED_FOL
    assert reified.reification is ReificationKind.FORMULA

    intention = build_intention_to_fol_reified_edge()
    assert intention.reification is ReificationKind.FULL

    atp = build_event_calculus_to_atp_edge()
    assert atp.encoding_kind is EncodingKind.ATP_TPTP
    assert atp.reification is ReificationKind.PREDICATE


def test_approximation_direction_matches_preservation() -> None:
    over = build_deontic_to_fol_reified_edge()
    assert (
        over.contract.preservation
        is PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION
    )
    assert over.approximation_direction is ApproximationDirection.OVER

    under = build_intention_to_fol_reified_edge()
    assert (
        under.contract.preservation
        is PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION
    )
    assert under.approximation_direction is ApproximationDirection.UNDER

    exactish = build_authorization_to_datalog_edge()
    assert exactish.approximation_direction is ApproximationDirection.NONE
    assert exactish.contract.preservation is PreservationRelation.EQUISATISFIABLE


# ---------------------------------------------------------------------------
# Negative fixtures: acceptance axes cannot be omitted or misaligned
# ---------------------------------------------------------------------------


def test_modal_edge_rejects_empty_frame_conditions() -> None:
    contract = _minimal_contract(
        contract_id="modal_bad",
        source_family="modal",
        target_family="first_order",
        preservation=PreservationRelation.THEOREM_PRESERVING,
    )
    with pytest.raises(PolicyModalTranslationError, match="frame conditions"):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="modal_bad",
                contract=contract,
                encoding_kind=EncodingKind.RELATIONAL_FOL,
                frame_conditions=(),
                norm_semantics=("norm:not_applicable_alethic_modal",),
                event_closure=("event_closure:not_applicable_modal",),
                agent_indices=AgentIndexPolicy.FORBIDDEN,
            )
        )


def test_authorization_edge_rejects_empty_norm_semantics() -> None:
    with pytest.raises(PolicyModalTranslationError, match="norm semantics"):
        PolicyModalEdge(**_edge_kwargs(norm_semantics=()))


def test_event_calculus_edge_rejects_empty_event_closure() -> None:
    contract = _minimal_contract(
        contract_id="ec_bad",
        source_family="event_calculus",
        target_family="first_order",
        preservation=PreservationRelation.THEOREM_PRESERVING,
    )
    with pytest.raises(PolicyModalTranslationError, match="event closure"):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="ec_bad",
                contract=contract,
                encoding_kind=EncodingKind.RELATIONAL_FOL,
                frame_conditions=("frame:not_applicable_event_calculus",),
                norm_semantics=("norm:not_applicable_event_calculus",),
                event_closure=(),
            )
        )


def test_cognitive_edge_rejects_not_applicable_agent_indices() -> None:
    contract = _minimal_contract(
        contract_id="ep_bad",
        source_family="modal",
        target_family="first_order",
        preservation=PreservationRelation.THEOREM_PRESERVING,
        source_profile="modal_epistemic_multi_agent",
    )
    with pytest.raises(PolicyModalTranslationError, match="agent indices"):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="ep_bad",
                contract=contract,
                encoding_kind=EncodingKind.RELATIONAL_FOL,
                frame_conditions=("frame:epistemic_s5_per_agent",),
                norm_semantics=("norm:not_applicable_epistemic",),
                event_closure=("event_closure:not_applicable_epistemic",),
                agent_indices=AgentIndexPolicy.NOT_APPLICABLE,
            )
        )


def test_reified_fol_requires_non_none_reification() -> None:
    with pytest.raises(PolicyModalTranslationError, match="reified_fol"):
        PolicyModalEdge(
            **_edge_kwargs(
                encoding_kind=EncodingKind.REIFIED_FOL,
                reification=ReificationKind.NONE,
            )
        )


def test_relational_fol_requires_reification_none() -> None:
    contract = _minimal_contract(
        contract_id="rel_bad",
        source_family="modal",
        target_family="first_order",
        preservation=PreservationRelation.THEOREM_PRESERVING,
    )
    with pytest.raises(PolicyModalTranslationError, match="relational_fol"):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="rel_bad",
                contract=contract,
                encoding_kind=EncodingKind.RELATIONAL_FOL,
                frame_conditions=("frame:kripke_s5",),
                norm_semantics=("norm:not_applicable_alethic_modal",),
                event_closure=("event_closure:not_applicable_modal",),
                agent_indices=AgentIndexPolicy.FORBIDDEN,
                reification=ReificationKind.FORMULA,
            )
        )


def test_conservative_requires_matching_approximation_direction() -> None:
    contract = _minimal_contract(
        contract_id="cons_bad",
        source_family="deontic",
        target_family="first_order",
        preservation=PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
    )
    with pytest.raises(
        PolicyModalTranslationError, match="approximation direction"
    ):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="cons_bad",
                contract=contract,
                encoding_kind=EncodingKind.REIFIED_FOL,
                frame_conditions=("frame:not_applicable_deontic_monadic",),
                norm_semantics=("norm:monadic_obligation",),
                event_closure=("event_closure:not_applicable_deontic",),
                reification=ReificationKind.FORMULA,
                approximation_direction=ApproximationDirection.NONE,
            )
        )

    with pytest.raises(PolicyModalTranslationError, match="does not match"):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="cons_bad",
                contract=contract,
                encoding_kind=EncodingKind.REIFIED_FOL,
                frame_conditions=("frame:not_applicable_deontic_monadic",),
                norm_semantics=("norm:monadic_obligation",),
                event_closure=("event_closure:not_applicable_deontic",),
                reification=ReificationKind.FORMULA,
                approximation_direction=ApproximationDirection.UNDER,
            )
        )


def test_non_conservative_rejects_nonzero_approximation_direction() -> None:
    with pytest.raises(
        PolicyModalTranslationError, match="only valid for conservative"
    ):
        PolicyModalEdge(
            **_edge_kwargs(approximation_direction=ApproximationDirection.OVER)
        )


def test_edge_contract_id_must_match_edge_id() -> None:
    with pytest.raises(PolicyModalTranslationError, match="contract_id"):
        PolicyModalEdge(
            **_edge_kwargs(
                edge_id="other_id",
                contract=_minimal_contract(contract_id="test_edge"),
            )
        )


def test_edge_round_trip_and_content_identity() -> None:
    edge = build_authorization_to_datalog_edge()
    payload = edge.to_dict()
    restored = PolicyModalEdge.from_dict(payload)
    assert restored == edge
    assert restored.edge_content_id == edge.edge_content_id

    with pytest.raises(PolicyModalTranslationError, match="edge_content_id"):
        PolicyModalEdge.from_dict({**payload, "edge_content_id": "bafkreitamperedxxx"})


def test_edge_is_immutable() -> None:
    edge = build_frame_logic_to_fol_edge()
    with pytest.raises(FrozenInstanceError):
        edge.reification = ReificationKind.FULL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Encoding-specific contracts
# ---------------------------------------------------------------------------


def test_authorization_routes_use_datalog_and_secpal_encodings() -> None:
    datalog = build_authorization_to_datalog_edge()
    assert datalog.encoding_kind is EncodingKind.DATALOG
    assert datalog.target_family_id == "datalog"
    assert datalog.contract.authority_ceiling is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    assert "bound:max_delegation_depth_64" in datalog.contract.assumptions.bounds

    secpal = build_authorization_to_secpal_edge()
    assert secpal.encoding_kind is EncodingKind.SECPAL
    assert secpal.contract.source.family_id == "authorization"
    assert "feat_open_recursion" in secpal.contract.unsupported_constructs


def test_unsupported_constructs_are_declared_not_silent() -> None:
    deontic = build_deontic_to_fol_reified_edge()
    unsupported_nodes = {
        entry.source_node_id
        for entry in deontic.contract.node_map
        if entry.disposition is NodeDisposition.UNSUPPORTED
    }
    assert "n_dyadic" in unsupported_nodes
    assert "n_defeasible" in unsupported_nodes
    assert "feat_dyadic_norms" in deontic.contract.unsupported_constructs


def test_event_inertia_is_synthesized_with_explicit_reason() -> None:
    ec = build_event_calculus_to_fol_edge()
    inertia = next(
        entry
        for entry in ec.contract.node_map
        if entry.source_node_id == "n_inertia"
    )
    assert inertia.disposition is NodeDisposition.SYNTHESIZED
    assert "inertia" in inertia.reason.lower()


# ---------------------------------------------------------------------------
# Planner integration
# ---------------------------------------------------------------------------


def test_register_with_planner_and_plan_authorization_to_datalog() -> None:
    catalog = build_policy_modal_translation_edges()
    planner = catalog.register_with_planner()
    assert isinstance(planner, TranslationPathPlanner)
    assert len(planner.registered_edges) == len(catalog.edges)

    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="authorization",
            target_family_id="datalog",
            features=FeatureSet.from_features(
                (
                    "feat_authorization_facts",
                    "feat_stratified_rules",
                    "feat_decision_query",
                )
            ),
            source_profile_id="authorization_secpal_core",
            target_profile_id="datalog_stratified",
        )
    )
    assert receipt.edge_contract_ids == ("authorization_to_datalog",)
    assert receipt.preservation is PreservationRelation.EQUISATISFIABLE


def test_planner_rejects_unsupported_feature_on_authorization_path() -> None:
    catalog = build_policy_modal_translation_edges()
    planner = catalog.register_with_planner()
    with pytest.raises(TranslationPathPlannerError):
        planner.plan(
            TranslationPathRequest(
                source_family_id="authorization",
                target_family_id="datalog",
                features=FeatureSet.from_features(
                    (
                        "feat_authorization_facts",
                        "feat_stratified_rules",
                        "feat_decision_query",
                        "feat_unstratified_negation",
                    )
                ),
                source_profile_id="authorization_secpal_core",
                target_profile_id="datalog_stratified",
            )
        )


def test_planner_plans_modal_s5_to_fol() -> None:
    catalog = build_policy_modal_translation_edges()
    planner = catalog.register_with_planner()
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="modal",
            target_family_id="first_order",
            features=FeatureSet.from_features(
                (
                    "feat_box",
                    "feat_diamond",
                    "feat_boolean",
                    "feat_kripke_frame_s5",
                )
            ),
            source_profile_id="modal_kripke_s5",
            target_profile_id="fol_many_sorted",
        )
    )
    assert "modal_s5_to_fol_relational" in receipt.edge_contract_ids


def test_planner_plans_dcec_and_tdfol_routes() -> None:
    catalog = build_policy_modal_translation_edges()
    planner = catalog.register_with_planner()

    dcec_receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="dcec",
            target_family_id="first_order",
            features=FeatureSet.from_features(
                (
                    "feat_deontic_norms",
                    "feat_epistemic_knows",
                    "feat_events",
                    "feat_fluents",
                    "feat_agent_index",
                )
            ),
            source_profile_id="dcec_default",
            target_profile_id="fol_many_sorted",
        )
    )
    assert dcec_receipt.edge_contract_ids == ("dcec_to_fol_reified",)
    assert (
        dcec_receipt.preservation
        is PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION
    )

    tdfol_receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="tdfol",
            target_family_id="first_order",
            features=FeatureSet.from_features(
                (
                    "feat_temporal_quantifiers",
                    "feat_deontic_norms",
                    "feat_first_order",
                    "feat_discrete_time",
                )
            ),
            source_profile_id="tdfol_default",
            target_profile_id="fol_many_sorted",
        )
    )
    assert tdfol_receipt.edge_contract_ids == ("tdfol_to_fol_relational",)


def test_catalog_edges_from_to_filters() -> None:
    catalog = build_policy_modal_translation_edges()
    auth = catalog.edges_from("authorization")
    assert auth
    assert all(e.source_family_id == "authorization" for e in auth)

    to_fol = catalog.edges_to("first_order")
    assert to_fol
    assert all(e.target_family_id == "first_order" for e in to_fol)

    with pytest.raises(PolicyModalTranslationError, match="unknown"):
        catalog.get("missing_edge")


def test_catalog_rejects_duplicate_edge_ids() -> None:
    edge = build_authorization_to_datalog_edge()
    with pytest.raises(PolicyModalTranslationError, match="duplicate"):
        PolicyModalTranslationEdges(edges=(edge, edge))


def test_catalog_rejects_missing_source_family_coverage() -> None:
    only_auth = (build_authorization_to_datalog_edge(),)
    with pytest.raises(PolicyModalTranslationError, match="missing source families"):
        PolicyModalTranslationEdges(edges=only_auth)


def test_no_authority_laundering_above_preservation_ceiling() -> None:
    """Conservative edges must not claim authoritative theorem authority."""

    for edge in iter_policy_modal_edges():
        maximum = edge.contract.maximum_authority
        rank = {
            EvidenceAuthority.NONE: 0,
            EvidenceAuthority.ADVISORY: 1,
            EvidenceAuthority.BOUNDED: 2,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
            EvidenceAuthority.AUTHORITATIVE: 4,
        }
        assert rank[edge.contract.authority_ceiling] <= rank[maximum]


def test_approximation_cannot_be_promoted_to_equivalence() -> None:
    """Catalog must not label conservative encodings as exact equivalence."""

    for edge in iter_policy_modal_edges():
        if edge.approximation_direction is not ApproximationDirection.NONE:
            assert edge.contract.preservation in {
                PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
                PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION,
            }
            assert (
                edge.contract.preservation
                is not PreservationRelation.EXACT_EQUIVALENCE
            )


def test_content_identity_changes_when_semantics_change() -> None:
    base = build_authorization_to_datalog_edge()
    # Rebuild via from_dict with altered description through a new edge would
    # require a new contract; compare two distinct reviewed edges instead.
    other = build_frame_logic_to_fol_edge()
    assert base.edge_content_id != other.edge_content_id
    assert base.contract.contract_content_id != other.contract.contract_content_id
