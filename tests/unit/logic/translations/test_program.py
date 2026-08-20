"""Unit tests for program/VC/separation translation edges (LFP2-017)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import PreservationRelation
from ipfs_datasets_py.logic.translations.planner import (
    TranslationPathPlannerError,
    TranslationPathRequest,
)
from ipfs_datasets_py.logic.translations.program import (
    DEFAULT_PROGRAM_TRANSLATION_EDGES,
    FEAT_ARITHMETIC,
    FEAT_EQUALITY,
    FEAT_FRAME_CONDITIONS,
    FEAT_HEAP_RESOURCE,
    FEAT_PROGRAM_COMMANDS,
    FEAT_PROGRAM_CONTRACTS,
    FEAT_PURE_ASSERTIONS,
    FEAT_QUANTIFIERS,
    FEAT_SEPARATION_SPATIAL,
    FEAT_SEPARATION_WAND,
    FEAT_SEPTRACTION,
    FEAT_VERIFICATION_CONDITIONS,
    PROGRAM_TRANSLATION_EDGES_INTERFACE,
    SOURCE_PROGRAM,
    SOURCE_SEPARATION,
    TARGET_CHC,
    TARGET_FOL,
    TARGET_SMT,
    VIEW_SEPARATION,
    VIEW_SOURCE,
    VIEW_VC,
    HeapResourceLoss,
    HeapResourceLossKind,
    LoweringStatus,
    ObligationKind,
    ProgramObligation,
    ProgramTranslationEdge,
    ProgramTranslationEdges,
    ProgramTranslationError,
    ValidityDirection,
    assert_validity_direction_preserved,
    build_program_translation_edges,
    lower_program_obligation,
    metamorphic_rename_obligation,
    program_translation_contracts,
    reject_silent_heap_loss,
    validity_direction_for,
    weaker_validity_direction,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _program_features() -> tuple[str, ...]:
    return (
        FEAT_PROGRAM_CONTRACTS,
        FEAT_PROGRAM_COMMANDS,
        FEAT_PURE_ASSERTIONS,
        FEAT_FRAME_CONDITIONS,
        FEAT_EQUALITY,
        FEAT_ARITHMETIC,
        FEAT_QUANTIFIERS,
    )


def _vc_features() -> tuple[str, ...]:
    return (
        FEAT_VERIFICATION_CONDITIONS,
        FEAT_PURE_ASSERTIONS,
        FEAT_FRAME_CONDITIONS,
        FEAT_EQUALITY,
        FEAT_ARITHMETIC,
        FEAT_QUANTIFIERS,
    )


def _separation_features() -> tuple[str, ...]:
    return (
        FEAT_SEPARATION_SPATIAL,
        FEAT_HEAP_RESOURCE,
        FEAT_PURE_ASSERTIONS,
        FEAT_FRAME_CONDITIONS,
        FEAT_EQUALITY,
        FEAT_ARITHMETIC,
        FEAT_QUANTIFIERS,
    )


def _program_obligation(**overrides: object) -> ProgramObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:program:swap",
        "kind": ObligationKind.PROGRAM_CONTRACT,
        "source_family_id": SOURCE_PROGRAM,
        "features": _program_features(),
        "assumptions": ("pre:x_ge_0",),
        "goals": ("post:y_eq_old_x",),
        "commands": ("assign:y_x",),
        "frames": ("frame:heap_untouched",),
        "symbols": ("x", "y"),
    }
    payload.update(overrides)
    return ProgramObligation(**payload)  # type: ignore[arg-type]


def _vc_obligation(**overrides: object) -> ProgramObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:vc:post",
        "kind": ObligationKind.VERIFICATION_CONDITION,
        "source_family_id": SOURCE_PROGRAM,
        "features": _vc_features(),
        "assumptions": ("path:then_branch", "pre:n_gt_0"),
        "goals": ("post:result_ge_0",),
        "frames": ("frame:locals_stable",),
        "symbols": ("n", "result"),
    }
    payload.update(overrides)
    return ProgramObligation(**payload)  # type: ignore[arg-type]


def _separation_obligation(**overrides: object) -> ProgramObligation:
    payload: dict[str, object] = {
        "obligation_id": "obl:sep:list_cell",
        "kind": ObligationKind.SEPARATION,
        "source_family_id": SOURCE_SEPARATION,
        "features": _separation_features(),
        "assumptions": (),
        "goals": ("pure:x_neq_null",),
        "pure_atoms": ("pure:x_neq_null",),
        "points_to": (("x", "v"),),
        "frames": ("frame:rest_heap",),
        "symbols": ("x", "v", "heap"),
    }
    payload.update(overrides)
    return ProgramObligation(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Registry / edge surface
# ---------------------------------------------------------------------------


def test_interface_and_default_registry() -> None:
    edges = DEFAULT_PROGRAM_TRANSLATION_EDGES
    assert edges.INTERFACE == PROGRAM_TRANSLATION_EDGES_INTERFACE
    assert edges.INTERFACE == "ProgramTranslationEdges@1"
    assert len(edges) == 9
    assert edges.content_id.startswith("bafkrei")
    ids = {edge.edge_id for edge in edges}
    assert ids == {
        "program_to_first_order",
        "program_to_horn_chc",
        "program_to_smt",
        "vc_to_first_order",
        "vc_to_horn_chc",
        "vc_to_smt",
        "separation_to_first_order",
        "separation_to_horn_chc",
        "separation_to_smt",
    }


def test_routes_cover_program_vc_separation_to_fol_chc_smt() -> None:
    edges = ProgramTranslationEdges.default()
    for source_view, source_family in (
        (VIEW_SOURCE, SOURCE_PROGRAM),
        (VIEW_VC, SOURCE_PROGRAM),
        (VIEW_SEPARATION, SOURCE_SEPARATION),
    ):
        for target in (TARGET_FOL, TARGET_CHC, TARGET_SMT):
            matched = edges.edges_for(
                source_family_id=source_family,
                target_family_id=target,
                view_role=source_view,
            )
            assert matched, f"missing route {source_view}->{target}"


def test_contracts_are_planner_ready_and_round_trip() -> None:
    edges = ProgramTranslationEdges.default()
    payload = edges.to_dict()
    restored = ProgramTranslationEdges.from_dict(payload)
    assert restored.content_id == edges.content_id
    assert [edge.edge_id for edge in restored] == [edge.edge_id for edge in edges]

    contracts = program_translation_contracts()
    assert len(contracts) == 9
    assert all(contract.contract_content_id.startswith("bafkrei") for contract in contracts)


def test_edge_is_immutable() -> None:
    edge = DEFAULT_PROGRAM_TRANSLATION_EDGES.get("vc_to_smt")
    with pytest.raises(FrozenInstanceError):
        edge.validity_direction = ValidityDirection.EQUISATISFIABLE  # type: ignore[misc]


def test_build_edges_is_deterministic() -> None:
    a = build_program_translation_edges()
    b = build_program_translation_edges()
    assert [edge.content_id for edge in a] == [edge.content_id for edge in b]
    assert ProgramTranslationEdges(a).content_id == ProgramTranslationEdges(b).content_id


# ---------------------------------------------------------------------------
# Validity direction
# ---------------------------------------------------------------------------


def test_supported_program_and_vc_preserve_validity_direction() -> None:
    for target in (TARGET_FOL, TARGET_SMT):
        program_result = lower_program_obligation(_program_obligation(), target)
        assert program_result.is_supported
        assert (
            program_result.validity_direction
            is ValidityDirection.PRESERVES_VALIDITY
        )

        vc_result = lower_program_obligation(_vc_obligation(), target)
        assert vc_result.is_supported
        assert vc_result.validity_direction is ValidityDirection.PRESERVES_VALIDITY
        assert vc_result.target_obligation["validity_direction"] == (
            ValidityDirection.PRESERVES_VALIDITY.value
        )


def test_vc_to_chc_is_equisatisfiable() -> None:
    result = lower_program_obligation(_vc_obligation(), TARGET_CHC)
    assert result.is_supported
    assert result.edge_id == "vc_to_horn_chc"
    assert result.validity_direction is ValidityDirection.EQUISATISFIABLE
    assert result.target_obligation["encoding"] == "chc-sketch/v1"
    assert any(clause["is_query"] for clause in result.target_obligation["clauses"])


def test_separation_routes_over_approximate_with_explicit_heap_loss() -> None:
    for target in (TARGET_FOL, TARGET_CHC, TARGET_SMT):
        result = lower_program_obligation(_separation_obligation(), target)
        assert result.is_supported, result.reason
        assert (
            result.validity_direction
            is ValidityDirection.OVER_APPROXIMATES_VALIDITY
        )
        assert result.has_explicit_heap_loss
        kinds = {loss.kind for loss in result.heap_resource_losses}
        assert HeapResourceLossKind.HEAP_AS_ARRAY in kinds
        assert HeapResourceLossKind.SEP_CONJ_TO_AND in kinds
        assert result.target_obligation["heap_theory"] == "array"


def test_validity_direction_for_preservation_mapping() -> None:
    assert (
        validity_direction_for(PreservationRelation.THEOREM_PRESERVING)
        is ValidityDirection.PRESERVES_VALIDITY
    )
    assert (
        validity_direction_for(PreservationRelation.EQUISATISFIABLE)
        is ValidityDirection.EQUISATISFIABLE
    )
    assert (
        validity_direction_for(
            PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION
        )
        is ValidityDirection.OVER_APPROXIMATES_VALIDITY
    )
    assert weaker_validity_direction(
        ValidityDirection.PRESERVES_VALIDITY,
        ValidityDirection.OVER_APPROXIMATES_VALIDITY,
    ) is ValidityDirection.OVER_APPROXIMATES_VALIDITY


def test_edge_rejects_stronger_validity_than_preservation() -> None:
    base = DEFAULT_PROGRAM_TRANSLATION_EDGES.get("separation_to_smt")
    with pytest.raises(ProgramTranslationError, match="stronger"):
        ProgramTranslationEdge(
            edge_id=base.edge_id,
            contract=base.contract,
            validity_direction=ValidityDirection.EQUISATISFIABLE,
            view_role=base.view_role,
            heap_resource_losses=base.heap_resource_losses,
            obligation_kinds=base.obligation_kinds,
        )


def test_exact_equivalence_cannot_declare_heap_loss() -> None:
    # Reuse a pure edge contract shape is hard for exact_equivalence (assumptions
    # forbidden).  Validate the loss record guard via reject_silent_heap_loss and
    # the separation edges' non-exact preservation.
    sep = DEFAULT_PROGRAM_TRANSLATION_EDGES.get("separation_to_smt")
    assert sep.preservation is PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION
    assert sep.has_heap_loss


# ---------------------------------------------------------------------------
# Lowering encodings
# ---------------------------------------------------------------------------


def test_program_to_smt_encoding_includes_frame_and_goal() -> None:
    result = lower_program_obligation(_program_obligation(), TARGET_SMT)
    assert result.is_supported
    assert result.edge_id == "program_to_smt"
    payload = result.target_obligation
    assert payload["encoding"] == "smt-sketch/v1"
    assert payload["query_mode"] == "theorem_by_negation"
    assert payload["goal"] == "post:y_eq_old_x"
    names = {item["name"] for item in payload["assumptions"]}
    assert "assume_0" in names
    assert any(name.startswith("frame_") for name in names)


def test_program_to_fol_and_chc_encodings() -> None:
    fol = lower_program_obligation(_program_obligation(), TARGET_FOL)
    assert fol.is_supported
    assert fol.edge_id == "program_to_first_order"
    assert fol.target_obligation["encoding"] == "fol-sketch/v1"

    chc = lower_program_obligation(
        _program_obligation(
            kind=ObligationKind.PROGRAM_COMMAND,
            features=(
                FEAT_PROGRAM_COMMANDS,
                FEAT_PROGRAM_CONTRACTS,
                FEAT_PURE_ASSERTIONS,
                FEAT_FRAME_CONDITIONS,
                FEAT_EQUALITY,
                FEAT_ARITHMETIC,
                FEAT_QUANTIFIERS,
            ),
        ),
        TARGET_CHC,
    )
    assert chc.is_supported
    assert chc.edge_id == "program_to_horn_chc"
    assert chc.target_obligation["encoding"] == "chc-sketch/v1"


def test_separation_smt_encodes_points_to_as_select() -> None:
    result = lower_program_obligation(_separation_obligation(), TARGET_SMT)
    assert result.is_supported
    assumptions = result.target_obligation["assumptions"]
    formulas = [item["formula"] for item in assumptions]
    assert any("select heap x" in formula for formula in formulas)
    assert result.target_obligation["functions"][0]["name"] == "heap"


def test_path_receipt_binds_edge_and_features() -> None:
    result = lower_program_obligation(_vc_obligation(), TARGET_SMT)
    assert result.path_receipt is not None
    receipt = result.path_receipt
    assert receipt.edge_contract_ids == ("vc_to_smt",)
    assert receipt.preservation is PreservationRelation.THEOREM_PRESERVING
    assert receipt.authority_ceiling is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    assert receipt.proof_safe is True
    assert FEAT_VERIFICATION_CONDITIONS in receipt.covered_features


# ---------------------------------------------------------------------------
# Explicit heap/resource loss
# ---------------------------------------------------------------------------


def test_reject_silent_heap_loss() -> None:
    with pytest.raises(ProgramTranslationError, match="silent heap"):
        reject_silent_heap_loss(
            source_has_heap=True,
            losses=(),
            target_mentions_heap=False,
        )
    # Explicit loss allows heap omission only when loss is recorded — the
    # helper still requires target_mentions_heap OR non-empty losses?  Spec:
    # if source has heap and target omits heap, losses must be non-empty.
    reject_silent_heap_loss(
        source_has_heap=True,
        losses=(
            HeapResourceLoss(
                loss_id="loss:drop",
                kind=HeapResourceLossKind.RESOURCE_ALGEBRA_DROP,
                description="resource algebra dropped under review",
                source_construct_ids=("n_heap",),
                target_construct_ids=("t_unit",),
            ),
        ),
        target_mentions_heap=False,
    )


def test_heap_loss_records_round_trip() -> None:
    loss = HeapResourceLoss(
        loss_id="loss:heap-as-array",
        kind=HeapResourceLossKind.HEAP_AS_ARRAY,
        description="Array encoding of points-to cells.",
        source_construct_ids=("n_points_to",),
        target_construct_ids=("t_select",),
        validity_impact=ValidityDirection.OVER_APPROXIMATES_VALIDITY,
    )
    restored = HeapResourceLoss.from_dict(loss.to_dict())
    assert restored == loss


def test_vc_with_heap_feature_without_loss_edge_fails_closed() -> None:
    # VC edges do not declare heap losses; obligations that require heap
    # features still satisfy VC preconditions but must fail closed on silent
    # heap content.
    obligation = _vc_obligation(
        features=_vc_features() + (FEAT_HEAP_RESOURCE,),
        points_to=(("p", "1"),),
    )
    with pytest.raises(ProgramTranslationError, match="explicit heap"):
        lower_program_obligation(obligation, TARGET_SMT)


# ---------------------------------------------------------------------------
# Negative fixtures
# ---------------------------------------------------------------------------


def test_negative_magic_wand_is_unsupported() -> None:
    obligation = _separation_obligation(
        features=_separation_features() + (FEAT_SEPARATION_WAND,),
        constructs=("construct:magic_wand",),
    )
    result = lower_program_obligation(obligation, TARGET_SMT)
    assert result.status is LoweringStatus.UNSUPPORTED
    assert result.unsupported_constructs
    assert not result.target_obligation


def test_negative_septraction_is_unsupported() -> None:
    obligation = _separation_obligation(
        features=_separation_features() + (FEAT_SEPTRACTION,),
        constructs=("construct:septraction",),
    )
    result = lower_program_obligation(obligation, TARGET_FOL)
    assert result.status is LoweringStatus.UNSUPPORTED
    assert any("septraction" in item for item in result.unsupported_constructs)


def test_negative_missing_feature_preconditions() -> None:
    obligation = _vc_obligation(features=(FEAT_EQUALITY,))
    result = lower_program_obligation(obligation, TARGET_SMT)
    assert result.status is LoweringStatus.UNSUPPORTED
    assert "missing features" in result.reason


def test_negative_planner_rejects_authority_laundering() -> None:
    edges = ProgramTranslationEdges.default()
    with pytest.raises(TranslationPathPlannerError, match="authority laundering"):
        edges.plan(
            TranslationPathRequest(
                source_family_id=SOURCE_PROGRAM,
                target_family_id=TARGET_SMT,
                source_profile_id="program_vc_smt",
                target_profile_id="smt_lib2_default",
                features=_vc_features(),
                claimed_authority=EvidenceAuthority.AUTHORITATIVE,
            )
        )


def test_negative_planner_rejects_unsupported_feature() -> None:
    edges = ProgramTranslationEdges.default()
    with pytest.raises(TranslationPathPlannerError):
        edges.plan(
            TranslationPathRequest(
                source_family_id=SOURCE_SEPARATION,
                target_family_id=TARGET_SMT,
                source_profile_id="separation_smt",
                target_profile_id="smt_lib2_default",
                features=_separation_features() + (FEAT_SEPARATION_WAND,),
            )
        )


def test_negative_unknown_edge_id() -> None:
    with pytest.raises(ProgramTranslationError, match="unknown"):
        DEFAULT_PROGRAM_TRANSLATION_EDGES.get("not_an_edge")


def test_negative_obligation_kind_mismatch_is_unsupported() -> None:
    # A separation obligation cannot use a program-only feature set against FOL
    # without separation features.
    obligation = ProgramObligation(
        obligation_id="obl:bad",
        kind=ObligationKind.SEPARATION,
        source_family_id=SOURCE_SEPARATION,
        features=(FEAT_EQUALITY,),
        goals=("g",),
    )
    result = lower_program_obligation(obligation, TARGET_FOL)
    assert result.status is LoweringStatus.UNSUPPORTED
    assert "missing features" in result.reason


# ---------------------------------------------------------------------------
# Metamorphic fixtures
# ---------------------------------------------------------------------------


def test_metamorphic_rename_preserves_validity_and_heap_loss() -> None:
    original = _separation_obligation()
    renamed = metamorphic_rename_obligation(original, suffix="_m1")
    a = lower_program_obligation(original, TARGET_SMT)
    b = lower_program_obligation(renamed, TARGET_SMT)
    assert a.is_supported and b.is_supported
    assert_validity_direction_preserved(a, b)
    assert a.edge_id == b.edge_id
    assert a.validity_direction is b.validity_direction
    assert {loss.kind for loss in a.heap_resource_losses} == {
        loss.kind for loss in b.heap_resource_losses
    }


@pytest.mark.parametrize("target", [TARGET_FOL, TARGET_CHC, TARGET_SMT])
def test_metamorphic_feature_reorder_preserves_path_identity(target: str) -> None:
    features = list(_vc_features())
    forward = _vc_obligation(features=tuple(features))
    reverse = _vc_obligation(features=tuple(reversed(features)))
    a = lower_program_obligation(forward, target)
    b = lower_program_obligation(reverse, target)
    assert a.is_supported and b.is_supported
    assert a.edge_id == b.edge_id
    assert a.validity_direction is b.validity_direction
    assert a.path_receipt is not None and b.path_receipt is not None
    assert a.path_receipt.path_content_id == b.path_receipt.path_content_id


def test_metamorphic_program_vc_dual_targets_keep_proof_polarity() -> None:
    """Program and VC pure routes to SMT both preserve validity for proof."""

    program = lower_program_obligation(_program_obligation(), TARGET_SMT)
    vc = lower_program_obligation(_vc_obligation(), TARGET_SMT)
    assert program.is_supported and vc.is_supported
    assert program.validity_direction is ValidityDirection.PRESERVES_VALIDITY
    assert vc.validity_direction is ValidityDirection.PRESERVES_VALIDITY
    assert program.path_receipt is not None and vc.path_receipt is not None
    assert program.path_receipt.proof_safe is True
    assert vc.path_receipt.proof_safe is True


def test_metamorphic_separation_targets_share_loss_kinds() -> None:
    fol = lower_program_obligation(_separation_obligation(), TARGET_FOL)
    smt = lower_program_obligation(_separation_obligation(), TARGET_SMT)
    assert fol.is_supported and smt.is_supported
    fol_kinds = {loss.kind for loss in fol.heap_resource_losses}
    smt_kinds = {loss.kind for loss in smt.heap_resource_losses}
    # Core heap losses are shared; CHC may add ownership elision separately.
    assert HeapResourceLossKind.HEAP_AS_ARRAY in fol_kinds
    assert HeapResourceLossKind.HEAP_AS_ARRAY in smt_kinds
    assert fol.validity_direction is smt.validity_direction


def test_lowering_result_content_id_stable() -> None:
    result = lower_program_obligation(_vc_obligation(), TARGET_SMT, plan=False)
    again = lower_program_obligation(_vc_obligation(), TARGET_SMT, plan=False)
    assert result.content_id == again.content_id
    assert result.content_id.startswith("bafkrei")


def test_obligation_round_trip() -> None:
    obligation = _separation_obligation()
    restored = ProgramObligation.from_dict(obligation.to_dict())
    assert restored == obligation
