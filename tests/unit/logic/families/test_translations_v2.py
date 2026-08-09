"""Contract tests for TranslationContract@2 and TranslationCompositionReceipt@1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority, TranslationKind
from ipfs_datasets_py.logic.families.translations import (
    COMPOSITION_INTERFACE,
    COMPOSITION_SCHEMA_VERSION,
    CONTRACT_INTERFACE,
    CONTRACT_SCHEMA_VERSION,
    NodeDisposition,
    NodeMapEntry,
    OpaqueDisposition,
    PreservationRelation,
    SymbolMapEntry,
    TranslationAssumptionSet,
    TranslationCompositionReceipt,
    TranslationContract,
    TranslationContractError,
    TranslationEndpoint,
    TranslationIdentities,
    authority_at_most,
    compose_translations,
    maximum_authority_for,
    preservation_rank,
    taxonomy_translation_kind,
    weaker_authority,
    weaker_disposition,
    weaker_preservation,
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
        "checker_route": "differential:fol-smt",
        "reconstruction_route": "kernel:none",
        "description": "Reviewed FOL fragment to SMT-LIB.",
    }
    payload.update(overrides)
    return TranslationContract(**payload)  # type: ignore[arg-type]


def test_contract_interface_schema_and_round_trip() -> None:
    contract = _contract()
    assert contract.interface == CONTRACT_INTERFACE == "TranslationContract@2"
    assert contract.schema_version == CONTRACT_SCHEMA_VERSION
    assert contract.contract_content_id.startswith("bafkrei")
    assert contract.content_id == contract.contract_content_id

    payload = contract.to_dict()
    assert payload["interface"] == "TranslationContract@2"
    assert payload["preservation"] == "exact_equivalence"
    assert payload["proof_safe"] is True
    assert payload["counterexample_safe"] is True
    assert payload["authority_ceiling"] == "authoritative"
    assert payload["identities"]["compiler_identity"].startswith("sha256:")
    assert payload["identities"]["profile_identity"].startswith("sha256:")
    assert payload["identities"]["config_identity"].startswith("sha256:")

    restored = TranslationContract.from_dict(payload)
    assert restored == contract
    assert restored.to_dict() == payload


def test_contract_is_immutable() -> None:
    contract = _contract()
    with pytest.raises(FrozenInstanceError):
        contract.proof_safe = False  # type: ignore[misc]


def test_content_identity_binds_compiler_profile_config() -> None:
    base = _contract()
    changed_compiler = _contract(
        identities=_identities(compiler_identity="sha256:" + "e" * 64),
        contract_content_id="",
    )
    changed_profile = _contract(
        identities=_identities(profile_identity="sha256:" + "f" * 64),
        contract_content_id="",
    )
    changed_config = _contract(
        identities=_identities(config_identity="sha256:" + "9" * 64),
        contract_content_id="",
    )
    assert changed_compiler.contract_content_id != base.contract_content_id
    assert changed_profile.contract_content_id != base.contract_content_id
    assert changed_config.contract_content_id != base.contract_content_id


def test_mismatched_contract_content_id_is_rejected() -> None:
    with pytest.raises(TranslationContractError, match="contract_content_id"):
        _contract(contract_content_id="bafkreinot-the-real-content-identity-value-xxxxxx")


@pytest.mark.parametrize(
    ("relation", "maximum", "taxonomy"),
    [
        (
            PreservationRelation.EXACT_EQUIVALENCE,
            EvidenceAuthority.AUTHORITATIVE,
            TranslationKind.LOSSLESS,
        ),
        (
            PreservationRelation.EQUISATISFIABLE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.EQUISATISFIABLE,
        ),
        (
            PreservationRelation.THEOREM_PRESERVING,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.LOSSLESS,
        ),
        (
            PreservationRelation.MODEL_PRESERVING,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.EQUISATISFIABLE,
        ),
        (
            PreservationRelation.TRACE_PRESERVING,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.EQUISATISFIABLE,
        ),
        (
            PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.SOUND_OVER_APPROXIMATION,
        ),
        (
            PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.SOUND_UNDER_APPROXIMATION,
        ),
        (
            PreservationRelation.BOUNDED,
            EvidenceAuthority.BOUNDED,
            TranslationKind.SOUND_OVER_APPROXIMATION,
        ),
        (
            PreservationRelation.APPROXIMATE,
            EvidenceAuthority.ADVISORY,
            TranslationKind.SOUND_OVER_APPROXIMATION,
        ),
        (
            PreservationRelation.HEURISTIC,
            EvidenceAuthority.NONE,
            TranslationKind.HEURISTIC,
        ),
    ],
)
def test_preservation_authority_ceilings(
    relation: PreservationRelation,
    maximum: EvidenceAuthority,
    taxonomy: TranslationKind,
) -> None:
    assert maximum_authority_for(relation) is maximum
    assert taxonomy_translation_kind(relation) is taxonomy
    kwargs: dict[str, object] = {
        "preservation": relation,
        "authority_ceiling": maximum,
        "proof_safe": relation
        not in {
            PreservationRelation.HEURISTIC,
            PreservationRelation.APPROXIMATE,
        },
        "counterexample_safe": relation
        in {
            PreservationRelation.EXACT_EQUIVALENCE,
            PreservationRelation.EQUISATISFIABLE,
            PreservationRelation.MODEL_PRESERVING,
            PreservationRelation.TRACE_PRESERVING,
            PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION,
            PreservationRelation.BOUNDED,
        },
    }
    if relation is PreservationRelation.EXACT_EQUIVALENCE:
        kwargs["proof_safe"] = True
        kwargs["counterexample_safe"] = True
    if relation is PreservationRelation.HEURISTIC:
        kwargs["proof_safe"] = False
        kwargs["counterexample_safe"] = False
    if relation is PreservationRelation.BOUNDED:
        kwargs["assumptions"] = TranslationAssumptionSet(bounds=("bound:k",))
        kwargs["node_map"] = (
            _node(
                "n_and",
                "t_and",
                disposition=NodeDisposition.APPROXIMATED,
                reason="step bound",
            ),
            _node(
                "n_forall",
                "t_forall",
                disposition=NodeDisposition.MAPPED,
            ),
        )
    if relation is not PreservationRelation.EXACT_EQUIVALENCE:
        kwargs.setdefault(
            "node_map",
            (
                _node("n_and", "t_and"),
                _node("n_forall", "t_forall"),
            ),
        )
    contract = _contract(**kwargs)
    assert contract.maximum_authority is maximum
    assert contract.taxonomy_kind is taxonomy


def test_authority_cannot_exceed_preservation_ceiling() -> None:
    with pytest.raises(TranslationContractError, match="authority"):
        _contract(
            preservation=PreservationRelation.HEURISTIC,
            authority_ceiling=EvidenceAuthority.ADVISORY,
            proof_safe=False,
            counterexample_safe=False,
            node_map=(
                _node("n_and", "t_and", disposition=NodeDisposition.APPROXIMATED),
                _node("n_forall", disposition=NodeDisposition.UNKNOWN, reason="opaque"),
            ),
        )


def test_proof_safe_and_counterexample_safe_are_independent() -> None:
    theorem = _contract(
        contract_id="modal_to_fol_theorem",
        source=_endpoint("modal"),
        target=_endpoint("first_order"),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(
            _node("n_box", "t_forall", disposition=NodeDisposition.MAPPED),
            _node("n_prop", "t_prop", disposition=NodeDisposition.PRESERVED),
        ),
        required_source_node_ids=("n_box", "n_prop"),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    model = _contract(
        contract_id="modal_to_fol_model",
        source=_endpoint("modal"),
        target=_endpoint("first_order"),
        preservation=PreservationRelation.MODEL_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=False,
        counterexample_safe=True,
        node_map=(
            _node("n_box", "t_forall", disposition=NodeDisposition.MAPPED),
            _node("n_prop", "t_prop", disposition=NodeDisposition.PRESERVED),
        ),
        required_source_node_ids=("n_box", "n_prop"),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    assert theorem.proof_safe is True
    assert theorem.counterexample_safe is False
    assert model.proof_safe is False
    assert model.counterexample_safe is True


def test_silent_node_drop_is_rejected() -> None:
    with pytest.raises(TranslationContractError, match="silent node drop"):
        _contract(
            node_map=(_node("n_and", "t_and"),),
            required_source_node_ids=("n_and", "n_forall"),
        )


def test_silent_symbol_drop_is_rejected() -> None:
    with pytest.raises(TranslationContractError, match="silent symbol drop"):
        _contract(
            symbol_map=(),
            required_source_symbol_ids=("p", "q"),
        )


def test_dropped_nodes_require_explicit_reason() -> None:
    with pytest.raises(TranslationContractError, match="dropped"):
        NodeMapEntry(
            source_node_id="n_x",
            disposition=NodeDisposition.DROPPED,
        )


def test_explicit_drop_is_allowed_when_declared() -> None:
    contract = _contract(
        preservation=PreservationRelation.APPROXIMATE,
        authority_ceiling=EvidenceAuthority.ADVISORY,
        proof_safe=False,
        counterexample_safe=False,
        node_map=(
            _node("n_and", "t_and"),
            _node(
                "n_forall",
                disposition=NodeDisposition.DROPPED,
                reason="target fragment is quantifier-free",
            ),
        ),
    )
    assert contract.dropped_node_ids == ("n_forall",)


def test_unknown_nodes_require_reason_and_cannot_claim_targets() -> None:
    with pytest.raises(TranslationContractError, match="unknown"):
        NodeMapEntry(
            source_node_id="n_x",
            disposition=NodeDisposition.UNKNOWN,
        )
    with pytest.raises(TranslationContractError, match="cannot declare target"):
        NodeMapEntry(
            source_node_id="n_x",
            target_node_ids=("t_x",),
            disposition=NodeDisposition.UNKNOWN,
            reason="opaque",
        )


def test_composed_translations_inherit_weakest_guarantee_and_lowest_authority() -> None:
    first = _contract(
        contract_id="fol_to_smt",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=(
            _node("n_and", "m_and", disposition=NodeDisposition.PRESERVED),
            _node("n_forall", "m_forall", disposition=NodeDisposition.MAPPED),
        ),
        symbol_map=(_symbol("p", "p_m"),),
        required_source_node_ids=("n_and", "n_forall"),
        required_source_symbol_ids=("p",),
        assumptions=TranslationAssumptionSet(axioms=("axiom:choice",)),
        identities=_identities(
            compiler_identity="compiler:fol-smt",
            profile_identity="profile:classical",
            config_identity="config:a",
        ),
    )
    second = _contract(
        contract_id="smt_to_bitvector",
        source=_endpoint("smt"),
        target=_endpoint("propositional"),
        preservation=PreservationRelation.BOUNDED,
        authority_ceiling=EvidenceAuthority.BOUNDED,
        proof_safe=True,
        counterexample_safe=False,
        assumptions=TranslationAssumptionSet(
            bounds=("bound:width_32",),
            domain_changes=("domain:int_to_bv",),
        ),
        node_map=(
            _node("m_and", "b_and", disposition=NodeDisposition.MAPPED),
            _node(
                "m_forall",
                "b_expand",
                disposition=NodeDisposition.APPROXIMATED,
                reason="finite domain expansion",
            ),
        ),
        symbol_map=(_symbol("p_m", "p_b"),),
        required_source_node_ids=("m_and", "m_forall"),
        required_source_symbol_ids=("p_m",),
        identities=_identities(
            compiler_identity="compiler:smt-bv",
            profile_identity="profile:bv32",
            config_identity="config:b",
            source_identity="bafkreiccccccccccccccccccccccccccccccccccccccccccccccccccc",
            target_identity="bafkreidddddddddddddddddddddddddddddddddddddddddddddddddd",
        ),
    )

    receipt = compose_translations(first, second)
    assert receipt.interface == COMPOSITION_INTERFACE == "TranslationCompositionReceipt@1"
    assert receipt.schema_version == COMPOSITION_SCHEMA_VERSION
    assert receipt.preservation is PreservationRelation.BOUNDED
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED
    assert receipt.proof_safe is True
    assert receipt.counterexample_safe is False
    assert receipt.source.family_id == "first_order"
    assert receipt.target.family_id == "propositional"
    assert receipt.component_contract_ids == ("fol_to_smt", "smt_to_bitvector")
    assert len(receipt.component_content_ids) == 2
    assert "axiom:choice" in receipt.assumptions.all_assumption_ids
    assert "bound:width_32" in receipt.assumptions.all_assumption_ids
    assert "domain:int_to_bv" in receipt.assumptions.all_assumption_ids

    # Assumptions from both edges are retained (cannot disappear).
    assert receipt.assumptions.issuperset(first.assumptions)
    assert receipt.assumptions.issuperset(second.assumptions)

    # Node maps compose transitively with the weaker disposition.
    lookup = {entry.source_node_id: entry for entry in receipt.node_map}
    assert lookup["n_and"].target_node_ids == ("b_and",)
    assert lookup["n_and"].disposition is NodeDisposition.MAPPED
    assert lookup["n_forall"].target_node_ids == ("b_expand",)
    assert lookup["n_forall"].disposition is NodeDisposition.APPROXIMATED

    # Content identities bind the composed compiler/profile/config chain.
    assert "compiler:fol-smt" in receipt.identities.compiler_identity
    assert "compiler:smt-bv" in receipt.identities.compiler_identity
    assert "profile:classical" in receipt.identities.profile_identity
    assert "config:a" in receipt.identities.config_identity
    assert receipt.composition_content_id.startswith("bafkrei")

    restored = TranslationCompositionReceipt.from_dict(receipt.to_dict())
    assert restored == receipt


def test_composition_unknown_nodes_cannot_disappear() -> None:
    first = _contract(
        contract_id="a_to_b",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        preservation=PreservationRelation.APPROXIMATE,
        authority_ceiling=EvidenceAuthority.ADVISORY,
        proof_safe=False,
        counterexample_safe=False,
        node_map=(
            _node("n_known", "m_known"),
            _node(
                "n_opaque",
                disposition=NodeDisposition.UNKNOWN,
                reason="opaque quantifier pattern",
            ),
        ),
        required_source_node_ids=("n_known", "n_opaque"),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    second = _contract(
        contract_id="b_to_c",
        source=_endpoint("smt"),
        target=_endpoint("propositional"),
        preservation=PreservationRelation.HEURISTIC,
        authority_ceiling=EvidenceAuthority.NONE,
        proof_safe=False,
        counterexample_safe=False,
        node_map=(_node("m_known", "c_known"),),
        required_source_node_ids=("m_known",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    receipt = compose_translations(first, second)
    lookup = {entry.source_node_id: entry for entry in receipt.node_map}
    assert "n_opaque" in lookup
    assert lookup["n_opaque"].disposition is NodeDisposition.UNKNOWN
    assert lookup["n_opaque"].reason
    assert receipt.preservation is PreservationRelation.HEURISTIC
    assert receipt.authority_ceiling is EvidenceAuthority.NONE


def test_composition_unresolved_intermediate_becomes_unknown() -> None:
    first = _contract(
        contract_id="a_to_b",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=(_node("n1", "m_missing"),),
        required_source_node_ids=("n1",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    second = _contract(
        contract_id="b_to_c",
        source=_endpoint("smt"),
        target=_endpoint("propositional"),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=True,
        node_map=(_node("m_other", "c1"),),
        required_source_node_ids=("m_other",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    receipt = compose_translations(first, second)
    entry = receipt.node_map[0]
    assert entry.source_node_id == "n1"
    assert entry.disposition is NodeDisposition.UNKNOWN
    assert entry.target_node_ids == ()
    assert "unknown intermediate" in entry.reason


def test_composition_rejects_family_mismatch() -> None:
    first = _contract(
        contract_id="a_to_b",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        node_map=(_node("n1", "m1"),),
        required_source_node_ids=("n1",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    second = _contract(
        contract_id="c_to_d",
        source=_endpoint("modal"),
        target=_endpoint("first_order"),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_safe=True,
        counterexample_safe=False,
        node_map=(_node("x1", "y1"),),
        required_source_node_ids=("x1",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    with pytest.raises(TranslationContractError, match="intermediate family"):
        compose_translations(first, second)


def test_weakest_link_helpers() -> None:
    assert (
        weaker_preservation(
            PreservationRelation.EXACT_EQUIVALENCE,
            PreservationRelation.HEURISTIC,
        )
        is PreservationRelation.HEURISTIC
    )
    assert (
        weaker_authority(
            EvidenceAuthority.AUTHORITATIVE,
            EvidenceAuthority.BOUNDED,
        )
        is EvidenceAuthority.BOUNDED
    )
    assert (
        weaker_disposition(
            NodeDisposition.PRESERVED,
            NodeDisposition.UNKNOWN,
        )
        is NodeDisposition.UNKNOWN
    )
    assert preservation_rank(PreservationRelation.EXACT_EQUIVALENCE) > preservation_rank(
        PreservationRelation.BOUNDED
    )
    assert authority_at_most(
        EvidenceAuthority.BOUNDED, EvidenceAuthority.AUTHORITATIVE
    )


def test_exact_equivalence_rejects_assumptions_and_lossy_maps() -> None:
    with pytest.raises(TranslationContractError, match="assumptions"):
        _contract(assumptions=TranslationAssumptionSet(axioms=("axiom:x",)))
    with pytest.raises(TranslationContractError, match="lossy"):
        _contract(
            node_map=(
                _node("n_and", "t_and"),
                _node(
                    "n_forall",
                    disposition=NodeDisposition.DROPPED,
                    reason="no",
                ),
            )
        )


def test_bounded_requires_bounds_assumptions() -> None:
    with pytest.raises(TranslationContractError, match="bounds"):
        _contract(
            preservation=PreservationRelation.BOUNDED,
            authority_ceiling=EvidenceAuthority.BOUNDED,
            proof_safe=True,
            counterexample_safe=False,
            node_map=(
                _node("n_and", "t_and"),
                _node("n_forall", "t_forall"),
            ),
        )


def test_opaque_disposition_never_implies_success() -> None:
    for disposition in OpaqueDisposition:
        contract = _contract(
            preservation=PreservationRelation.APPROXIMATE,
            authority_ceiling=EvidenceAuthority.ADVISORY,
            proof_safe=False,
            counterexample_safe=False,
            opaque_disposition=disposition,
            node_map=(
                _node("n_and", "t_and"),
                _node("n_forall", "t_forall"),
            ),
        )
        assert contract.opaque_disposition is disposition
        assert contract.opaque_disposition.value in {
            "unsupported",
            "inconclusive",
            "approval_required",
        }


def test_three_way_composition_accumulates_assumptions() -> None:
    a = _contract(
        contract_id="step_a",
        source=_endpoint("first_order"),
        target=_endpoint("smt"),
        preservation=PreservationRelation.EQUISATISFIABLE,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        assumptions=TranslationAssumptionSet(axioms=("ax_a",)),
        node_map=(_node("n1", "m1"),),
        required_source_node_ids=("n1",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    b = _contract(
        contract_id="step_b",
        source=_endpoint("smt"),
        target=_endpoint("propositional"),
        preservation=PreservationRelation.BOUNDED,
        authority_ceiling=EvidenceAuthority.BOUNDED,
        proof_safe=True,
        counterexample_safe=False,
        assumptions=TranslationAssumptionSet(bounds=("k_b",)),
        node_map=(_node("m1", "p1"),),
        required_source_node_ids=("m1",),
        required_source_symbol_ids=(),
        symbol_map=(),
    )
    c = _contract(
        contract_id="step_c",
        source=_endpoint("propositional"),
        target=_endpoint("authorization"),
        preservation=PreservationRelation.HEURISTIC,
        authority_ceiling=EvidenceAuthority.NONE,
        proof_safe=False,
        counterexample_safe=False,
        assumptions=TranslationAssumptionSet(other=("hint_c",)),
        node_map=(_node("p1", "a1"),),
        required_source_node_ids=("p1",),
        required_source_symbol_ids=(),
        symbol_map=(),
        unsupported_constructs=("construct:modal",),
    )
    receipt = compose_translations(a, b, c)
    assert receipt.preservation is PreservationRelation.HEURISTIC
    assert receipt.authority_ceiling is EvidenceAuthority.NONE
    assert set(receipt.assumptions.all_assumption_ids) == {"ax_a", "hint_c", "k_b"}
    assert receipt.unsupported_constructs == ("construct:modal",)
    assert receipt.node_map[0].target_node_ids == ("a1",)
    assert receipt.proof_safe is False
    assert receipt.counterexample_safe is False
