"""Unit tests for the compositional TranslationPath planner."""

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
    PATH_RECEIPT_INTERFACE,
    PATH_RECEIPT_SCHEMA_VERSION,
    PLANNER_INTERFACE,
    FeatureSet,
    TranslationPathPlanner,
    TranslationPathPlannerError,
    TranslationPathReceipt,
    TranslationPathRequest,
    edge_feature_compatibility,
    path_is_feature_total,
    plan_translation_path,
)


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


def _contract(**overrides: object) -> TranslationContract:
    payload: dict[str, object] = {
        "contract_id": "fol_to_smt",
        "source": _endpoint("first_order"),
        "target": _endpoint("smt"),
        "preservation": PreservationRelation.EXACT_EQUIVALENCE,
        "identities": _identities(),
        "proof_safe": True,
        "counterexample_safe": True,
        "authority_ceiling": EvidenceAuthority.AUTHORITATIVE,
        "node_map": (
            _node("n_and", "t_and", disposition=NodeDisposition.PRESERVED),
            _node("n_forall", "t_forall", disposition=NodeDisposition.MAPPED),
        ),
        "symbol_map": (
            _symbol("p", "p_smt", disposition=NodeDisposition.PRESERVED),
        ),
        "required_source_node_ids": ("n_and", "n_forall"),
        "required_source_symbol_ids": ("p",),
        "feature_preconditions": ("feat_quantifiers", "feat_boolean"),
        "unsupported_constructs": (),
        "checker_route": "differential:fol-smt",
        "reconstruction_route": "kernel:none",
        "description": "Reviewed FOL fragment to SMT-LIB.",
    }
    payload.update(overrides)
    return TranslationContract(**payload)  # type: ignore[arg-type]


def _fol_to_smt(**overrides: object) -> TranslationContract:
    return _contract(**overrides)


def _smt_to_prop(**overrides: object) -> TranslationContract:
    payload: dict[str, object] = {
        "contract_id": "smt_to_propositional",
        "source": _endpoint("smt"),
        "target": _endpoint("propositional"),
        "preservation": PreservationRelation.BOUNDED,
        "authority_ceiling": EvidenceAuthority.BOUNDED,
        "proof_safe": True,
        "counterexample_safe": False,
        "assumptions": TranslationAssumptionSet(bounds=("bound:width_32",)),
        "feature_preconditions": ("feat_boolean",),
        "node_map": (
            _node("t_and", "b_and", disposition=NodeDisposition.MAPPED),
            _node(
                "t_forall",
                "b_expand",
                disposition=NodeDisposition.APPROXIMATED,
                reason="finite domain expansion",
            ),
        ),
        "symbol_map": (_symbol("p_smt", "p_b"),),
        "required_source_node_ids": ("t_and", "t_forall"),
        "required_source_symbol_ids": ("p_smt",),
        "identities": _identities(
            compiler_identity="compiler:smt-prop",
            profile_identity="profile:bv32",
            config_identity="config:prop",
        ),
        "checker_route": "bounded:smt-prop",
        "reconstruction_route": "replay:prop",
    }
    payload.update(overrides)
    return _contract(**payload)


def _modal_to_fol(**overrides: object) -> TranslationContract:
    payload: dict[str, object] = {
        "contract_id": "modal_to_fol",
        "source": _endpoint("modal"),
        "target": _endpoint("first_order"),
        "preservation": PreservationRelation.THEOREM_PRESERVING,
        "authority_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "proof_safe": True,
        "counterexample_safe": False,
        "feature_preconditions": ("feat_box", "feat_boolean"),
        "node_map": (
            _node("n_box", "n_forall", disposition=NodeDisposition.MAPPED),
            _node("n_and", "n_and", disposition=NodeDisposition.PRESERVED),
        ),
        "symbol_map": (_symbol("p", "p", disposition=NodeDisposition.PRESERVED),),
        "required_source_node_ids": ("n_box", "n_and"),
        "required_source_symbol_ids": ("p",),
        "identities": _identities(
            compiler_identity="compiler:modal-fol",
            profile_identity="profile:s5",
            config_identity="config:modal",
        ),
    }
    payload.update(overrides)
    return _contract(**payload)


# ---------------------------------------------------------------------------
# Feature set / request basics
# ---------------------------------------------------------------------------


def test_feature_set_is_sorted_and_deduplicated() -> None:
    features = FeatureSet.from_features(("feat_z", "feat_a", "feat_m"))
    assert features.features == ("feat_a", "feat_m", "feat_z")
    assert "feat_a" in features
    assert features.to_dict()["schema_version"]


def test_feature_set_rejects_duplicates() -> None:
    with pytest.raises(TranslationPathPlannerError, match="duplicates"):
        FeatureSet.from_features(("feat_a", "feat_a"))


def test_request_round_trip() -> None:
    request = TranslationPathRequest(
        source_family_id="first_order",
        target_family_id="smt",
        features=("feat_boolean", "feat_quantifiers"),
        require_proof_safe=True,
        claimed_preservation=PreservationRelation.EXACT_EQUIVALENCE,
        claimed_authority=EvidenceAuthority.AUTHORITATIVE,
    )
    restored = TranslationPathRequest.from_dict(request.to_dict())
    assert restored == request


# ---------------------------------------------------------------------------
# Feature compatibility
# ---------------------------------------------------------------------------


def test_edge_rejects_unsupported_features() -> None:
    edge = _fol_to_smt(
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        unsupported_constructs=("feat_modal_box",),
    )
    compatible, missing, hits = edge_feature_compatibility(
        edge, ("feat_quantifiers", "feat_boolean", "feat_modal_box")
    )
    assert compatible is False
    assert hits == ("feat_modal_box",)
    assert missing == ()


def test_edge_requires_feature_preconditions() -> None:
    edge = _fol_to_smt()
    compatible, missing, hits = edge_feature_compatibility(
        edge, ("feat_boolean",)
    )
    assert compatible is False
    assert "feat_quantifiers" in missing
    assert hits == ()


def test_path_feature_total_requires_coverage() -> None:
    path = (_fol_to_smt(), _smt_to_prop())
    total, unhandled, unsupported = path_is_feature_total(
        path, ("feat_quantifiers", "feat_boolean")
    )
    assert total is True
    assert unhandled == ()
    assert unsupported == ()

    total, unhandled, unsupported = path_is_feature_total(
        path, ("feat_quantifiers", "feat_boolean", "feat_temporal")
    )
    assert total is False
    assert "feat_temporal" in unhandled


# ---------------------------------------------------------------------------
# Happy-path planning
# ---------------------------------------------------------------------------


def test_planner_selects_direct_edge() -> None:
    planner = TranslationPathPlanner([_fol_to_smt()])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
        )
    )
    assert receipt.interface == PATH_RECEIPT_INTERFACE == "TranslationPathReceipt@1"
    assert receipt.schema_version == PATH_RECEIPT_SCHEMA_VERSION
    assert planner.interface == PLANNER_INTERFACE == "TranslationPathPlanner@1"
    assert receipt.edge_contract_ids == ("fol_to_smt",)
    assert receipt.hop_count == 1
    assert receipt.preservation is PreservationRelation.EXACT_EQUIVALENCE
    assert receipt.authority_ceiling is EvidenceAuthority.AUTHORITATIVE
    assert receipt.proof_safe is True
    assert receipt.counterexample_safe is True
    assert receipt.path_content_id.startswith("bafkrei")
    assert receipt.content_id == receipt.path_content_id
    assert set(receipt.covered_features) >= {"feat_boolean", "feat_quantifiers"}


def test_planner_composes_multi_hop_path() -> None:
    planner = TranslationPathPlanner([_fol_to_smt(), _smt_to_prop()])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="propositional",
            features=("feat_boolean", "feat_quantifiers"),
        )
    )
    assert receipt.edge_contract_ids == ("fol_to_smt", "smt_to_propositional")
    assert receipt.hop_count == 2
    # Weakest-link composition.
    assert receipt.preservation is PreservationRelation.BOUNDED
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED
    assert receipt.proof_safe is True
    assert receipt.counterexample_safe is False
    assert "bound:width_32" in receipt.assumptions.all_assumption_ids
    assert receipt.composition.component_contract_ids == receipt.edge_contract_ids
    assert "bound:width_32" in receipt.composition.assumptions.bounds
    assert receipt.reconstruction_route
    assert receipt.checker_route


def test_planner_composes_three_hop_modal_route() -> None:
    planner = TranslationPathPlanner(
        [_modal_to_fol(), _fol_to_smt(), _smt_to_prop()]
    )
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="modal",
            target_family_id="propositional",
            features=("feat_box", "feat_boolean", "feat_quantifiers"),
        )
    )
    assert receipt.edge_contract_ids == (
        "modal_to_fol",
        "fol_to_smt",
        "smt_to_propositional",
    )
    assert receipt.preservation is PreservationRelation.BOUNDED
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED
    assert receipt.proof_safe is True
    assert receipt.counterexample_safe is False


def test_receipt_round_trip() -> None:
    receipt = plan_translation_path(
        [_fol_to_smt(), _smt_to_prop()],
        {
            "source_family_id": "first_order",
            "target_family_id": "propositional",
            "features": ["feat_boolean", "feat_quantifiers"],
        },
    )
    restored = TranslationPathReceipt.from_dict(receipt.to_dict())
    assert restored == receipt
    assert restored.to_dict() == receipt.to_dict()


def test_receipt_is_immutable() -> None:
    receipt = plan_translation_path(
        [_fol_to_smt()],
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
        ),
    )
    with pytest.raises(FrozenInstanceError):
        receipt.proof_safe = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Deterministic path identity
# ---------------------------------------------------------------------------


def test_path_identity_is_deterministic() -> None:
    edges = [_fol_to_smt(), _smt_to_prop()]
    request = TranslationPathRequest(
        source_family_id="first_order",
        target_family_id="propositional",
        features=("feat_quantifiers", "feat_boolean"),  # reverse order
    )
    first = plan_translation_path(edges, request)
    second = plan_translation_path(edges, request)
    assert first.path_content_id == second.path_content_id
    assert first.edge_contract_ids == second.edge_contract_ids
    assert first.to_dict() == second.to_dict()


def test_path_identity_ignores_feature_order() -> None:
    edges = [_fol_to_smt()]
    a = plan_translation_path(
        edges,
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
        ),
    )
    b = plan_translation_path(
        edges,
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_quantifiers", "feat_boolean"),
        ),
    )
    assert a.path_content_id == b.path_content_id


def test_path_identity_changes_with_edge_content() -> None:
    base = _fol_to_smt()
    altered = _fol_to_smt(
        identities=_identities(compiler_identity="sha256:" + "e" * 64),
        contract_content_id="",
    )
    request = TranslationPathRequest(
        source_family_id="first_order",
        target_family_id="smt",
        features=("feat_boolean", "feat_quantifiers"),
    )
    a = plan_translation_path([base], request)
    b = plan_translation_path([altered], request)
    assert a.path_content_id != b.path_content_id


def test_prefers_shorter_path_deterministically() -> None:
    # Direct FOL -> propositional (bounded) and multi-hop via SMT.
    direct = _contract(
        contract_id="fol_to_propositional",
        source=_endpoint("first_order"),
        target=_endpoint("propositional"),
        preservation=PreservationRelation.BOUNDED,
        authority_ceiling=EvidenceAuthority.BOUNDED,
        proof_safe=True,
        counterexample_safe=False,
        assumptions=TranslationAssumptionSet(bounds=("bound:direct",)),
        feature_preconditions=("feat_boolean", "feat_quantifiers"),
        node_map=(
            _node("n_and", "b_and"),
            _node(
                "n_forall",
                "b_expand",
                disposition=NodeDisposition.APPROXIMATED,
                reason="direct expansion",
            ),
        ),
        symbol_map=(_symbol("p", "p_b"),),
        required_source_node_ids=("n_and", "n_forall"),
        required_source_symbol_ids=("p",),
        identities=_identities(compiler_identity="compiler:fol-prop"),
    )
    planner = TranslationPathPlanner([_fol_to_smt(), _smt_to_prop(), direct])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="propositional",
            features=("feat_boolean", "feat_quantifiers"),
        )
    )
    assert receipt.edge_contract_ids == ("fol_to_propositional",)
    assert receipt.hop_count == 1


def test_tie_break_is_lexicographic_on_contract_ids() -> None:
    # Two single-hop edges with same endpoints; lower contract_id wins.
    edge_b = _contract(
        contract_id="zzz_fol_to_smt",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        feature_preconditions=("feat_boolean", "feat_quantifiers"),
        identities=_identities(compiler_identity="compiler:zzz"),
    )
    edge_a = _contract(
        contract_id="aaa_fol_to_smt",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        feature_preconditions=("feat_boolean", "feat_quantifiers"),
        identities=_identities(compiler_identity="compiler:aaa"),
    )
    # Register in reverse order; selection must still pick aaa.
    planner = TranslationPathPlanner([edge_b, edge_a])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
        )
    )
    assert receipt.edge_contract_ids == ("aaa_fol_to_smt",)


# ---------------------------------------------------------------------------
# Unsupported features fail before compilation
# ---------------------------------------------------------------------------


def test_unsupported_features_fail_before_compilation() -> None:
    edge = _fol_to_smt(
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        unsupported_constructs=("feat_modal_box",),
    )
    planner = TranslationPathPlanner([edge])
    with pytest.raises(
        TranslationPathPlannerError, match="unsupported features fail before compilation"
    ):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="smt",
                features=(
                    "feat_boolean",
                    "feat_quantifiers",
                    "feat_modal_box",
                ),
            )
        )


def test_uncovered_features_fail_before_compilation() -> None:
    planner = TranslationPathPlanner([_fol_to_smt()])
    with pytest.raises(TranslationPathPlannerError, match="fail before compilation|not covered|no feature-total"):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="smt",
                features=(
                    "feat_boolean",
                    "feat_quantifiers",
                    "feat_temporal_until",
                ),
            )
        )


def test_missing_path_fails() -> None:
    planner = TranslationPathPlanner([_fol_to_smt()])
    with pytest.raises(TranslationPathPlannerError, match="no translation path"):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="modal",
                features=("feat_boolean", "feat_quantifiers"),
            )
        )


# ---------------------------------------------------------------------------
# Authority / approximation laundering fails before compilation
# ---------------------------------------------------------------------------


def test_claimed_preservation_stronger_than_composed_is_laundering() -> None:
    planner = TranslationPathPlanner([_fol_to_smt(), _smt_to_prop()])
    with pytest.raises(
        TranslationPathPlannerError,
        match="approximation laundering|laundering fails before compilation",
    ):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="propositional",
                features=("feat_boolean", "feat_quantifiers"),
                # Multi-hop is BOUNDED; claiming exact is laundering.
                claimed_preservation=PreservationRelation.EXACT_EQUIVALENCE,
            )
        )


def test_claimed_authority_stronger_than_composed_is_laundering() -> None:
    planner = TranslationPathPlanner([_fol_to_smt(), _smt_to_prop()])
    with pytest.raises(
        TranslationPathPlannerError,
        match="authority laundering|laundering fails before compilation",
    ):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="propositional",
                features=("feat_boolean", "feat_quantifiers"),
                claimed_authority=EvidenceAuthority.AUTHORITATIVE,
            )
        )


def test_claimed_authority_within_ceiling_is_allowed() -> None:
    planner = TranslationPathPlanner([_fol_to_smt(), _smt_to_prop()])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="propositional",
            features=("feat_boolean", "feat_quantifiers"),
            claimed_preservation=PreservationRelation.BOUNDED,
            claimed_authority=EvidenceAuthority.BOUNDED,
        )
    )
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED


def test_require_counterexample_safe_rejects_lossy_path() -> None:
    planner = TranslationPathPlanner([_fol_to_smt(), _smt_to_prop()])
    with pytest.raises(
        TranslationPathPlannerError,
        match="polarity laundering|laundering fails before compilation",
    ):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="propositional",
                features=("feat_boolean", "feat_quantifiers"),
                require_counterexample_safe=True,
            )
        )


def test_require_proof_safe_selects_only_safe_paths() -> None:
    planner = TranslationPathPlanner([_fol_to_smt()])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
            require_proof_safe=True,
            require_counterexample_safe=True,
        )
    )
    assert receipt.proof_safe is True
    assert receipt.counterexample_safe is True


def test_composed_path_never_upgrades_authority_above_weakest_edge() -> None:
    # Exact FOL->SMT then approximate SMT->prop: composed must be approximate
    # and authority must drop.
    approx = _smt_to_prop(
        contract_id="smt_to_prop_approx",
        preservation=PreservationRelation.APPROXIMATE,
        authority_ceiling=EvidenceAuthority.ADVISORY,
        proof_safe=False,
        counterexample_safe=False,
        assumptions=TranslationAssumptionSet(),
        feature_preconditions=("feat_boolean",),
    )
    planner = TranslationPathPlanner([_fol_to_smt(), approx])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="propositional",
            features=("feat_boolean", "feat_quantifiers"),
        )
    )
    assert receipt.preservation is PreservationRelation.APPROXIMATE
    assert receipt.authority_ceiling is EvidenceAuthority.ADVISORY
    # Claiming independently_checkable would launder.
    with pytest.raises(TranslationPathPlannerError, match="authority laundering"):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="propositional",
                features=("feat_boolean", "feat_quantifiers"),
                claimed_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            )
        )


def test_mismatched_path_content_id_is_rejected() -> None:
    receipt = plan_translation_path(
        [_fol_to_smt()],
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
        ),
    )
    payload = receipt.to_dict()
    payload["path_content_id"] = "bafkreinot-the-real-path-content-identity-xxxxxx"
    with pytest.raises(TranslationPathPlannerError, match="path_content_id"):
        TranslationPathReceipt.from_dict(payload)


def test_duplicate_contract_id_with_different_content_is_rejected() -> None:
    planner = TranslationPathPlanner([_fol_to_smt()])
    altered = _fol_to_smt(
        identities=_identities(compiler_identity="sha256:" + "f" * 64),
        contract_content_id="",
    )
    with pytest.raises(TranslationPathPlannerError, match="duplicate contract_id"):
        planner.register_edge(altered)


def test_open_edges_without_preconditions_cover_all_non_unsupported() -> None:
    open_edge = _contract(
        contract_id="fol_to_smt_open",
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        feature_preconditions=(),
        unsupported_constructs=("feat_modal_box",),
    )
    planner = TranslationPathPlanner([open_edge])
    receipt = planner.plan(
        TranslationPathRequest(
            source_family_id="first_order",
            target_family_id="smt",
            features=("feat_boolean", "feat_quantifiers"),
        )
    )
    assert set(receipt.covered_features) == {"feat_boolean", "feat_quantifiers"}
    with pytest.raises(TranslationPathPlannerError, match="unsupported features"):
        planner.plan(
            TranslationPathRequest(
                source_family_id="first_order",
                target_family_id="smt",
                features=("feat_boolean", "feat_modal_box"),
            )
        )
