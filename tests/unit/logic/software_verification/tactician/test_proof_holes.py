"""Unit tests for TypedProofHoleEmitter@1 (FVT-012 / FVT-G030).

Acceptance:

* Removing a loop invariant, callee contract/frame, fairness premise, or
  bridge lemma yields the matching typed hole with source span, rationale,
  dependencies, expected authority, and validation recipe.
* Unsupported semantics remain different from missing proof.
* The emitter never invents default invariants or contracts.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    HoleKind,
    HoleStatus,
    PropertyClass,
    SourceSpanBinding,
)
from ipfs_datasets_py.logic.software_verification.tactician.proof_holes import (
    TYPED_PROOF_HOLE_EMITTER_INTERFACE,
    AnnotationRole,
    AnnotationSite,
    CompilationSurface,
    ProofHoleEmission,
    ProofHoleEmissionError,
    SiteKind,
    TypedProofHoleEmitter,
    bridge_lemma_site,
    callee_site,
    default_validation_recipe,
    emit_typed_proof_holes,
    fairness_site,
    hole_status_for_role,
    is_missing_proof_role,
    loop_site,
    unavailable_tool_site,
    unsupported_semantics_site,
)


def _source(**overrides: Any) -> SourceSpanBinding:
    payload = {
        "tree_id": "tree:repo@abc",
        "source_ref_ids": ("source:lease.py",),
        "span_ids": ("span:claim",),
        "ast_scope_ids": ("symbol:claim_lease",),
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return SourceSpanBinding(**payload)


def _complete_surface() -> CompilationSurface:
    """Surface with all key annotations present (no holes expected)."""

    return CompilationSurface(
        surface_id="surface:lease-ready",
        formal_goal_id="formal:lease-ready",
        tree_id="tree:repo@abc",
        sites=(
            loop_site(
                "site:loop-claim",
                source=_source(
                    source_ref_ids=("source:lease.py",),
                    span_ids=("span:loop-claim",),
                    ast_scope_ids=("symbol:claim_loop",),
                ),
                has_invariant=True,
                has_variant=True,
                require_variant=True,
                dependency_ids=("site:pre",),
            ),
            callee_site(
                "site:call-release",
                source=_source(
                    source_ref_ids=("source:lease.py",),
                    span_ids=("span:call-release",),
                    ast_scope_ids=("symbol:release",),
                ),
                has_precondition=True,
                has_postcondition=True,
                has_frame=True,
                dependency_ids=("site:loop-claim",),
            ),
            fairness_site(
                "site:fair-scheduler",
                source=_source(
                    source_ref_ids=("source:scheduler.md",),
                    span_ids=("span:fairness",),
                ),
                has_fairness_premise=True,
            ),
            bridge_lemma_site(
                "site:bridge-smt-lean",
                source=_source(
                    source_ref_ids=("source:bridge.lean",),
                    span_ids=("span:bridge",),
                ),
                has_bridge_lemma=True,
                dependency_ids=("site:call-release",),
            ),
        ),
        provider_ids=("provider:z3", "provider:lean"),
    )


# ---------------------------------------------------------------------------
# Interface and empty emission
# ---------------------------------------------------------------------------


def test_emitter_interface_constant() -> None:
    assert TypedProofHoleEmitter.INTERFACE == TYPED_PROOF_HOLE_EMITTER_INTERFACE
    assert TYPED_PROOF_HOLE_EMITTER_INTERFACE == "TypedProofHoleEmitter@1"


def test_complete_surface_emits_no_holes() -> None:
    emission = TypedProofHoleEmitter().emit(_complete_surface())
    assert emission.holes == ()
    assert emission.missing_proof_hole_ids == ()
    assert emission.non_proof_hole_ids == ()
    assert emission.invented_defaults is False
    assert emission.INTERFACE == TYPED_PROOF_HOLE_EMITTER_INTERFACE
    assert emission.to_dict()["interface"] == TYPED_PROOF_HOLE_EMITTER_INTERFACE


# ---------------------------------------------------------------------------
# Acceptance: remove loop invariant / callee frame / fairness / bridge
# ---------------------------------------------------------------------------


def test_removing_loop_invariant_yields_typed_hole() -> None:
    surface = _complete_surface()
    emission = TypedProofHoleEmitter().emit_for_removed_annotation(
        surface, "site:loop-claim", AnnotationRole.LOOP_INVARIANT
    )
    holes = emission.holes_of_kind(HoleKind.LOOP_INVARIANT)
    assert len(holes) == 1
    hole = holes[0]
    assert hole.status is HoleStatus.OPEN
    assert hole.source.span_ids == ("span:loop-claim",)
    assert hole.source.tree_id == "tree:repo@abc"
    assert "invariant" in hole.reason.lower() or "missing" in hole.reason.lower()
    assert hole.expected_authority is AuthorityCeiling.SATISFIABILITY
    assert hole.validation_recipe is not None
    assert hole.validation_recipe.checker_kind == "smt_invariant_check"
    assert hole.validation_recipe.steps
    assert hole.formal_goal_id == "formal:lease-ready"
    assert hole.property_class is PropertyClass.INVARIANCE
    assert hole.proof_claimed is False
    assert hole.completion_claimed is False
    assert hole.hole_id in emission.missing_proof_hole_ids
    assert hole.hole_id not in emission.non_proof_hole_ids
    # Peer missing variant is not required once invariant present removed only.
    # Dependency list may include peer missing roles when both missing.


def test_removing_callee_frame_yields_frame_hole() -> None:
    surface = _complete_surface()
    emission = TypedProofHoleEmitter().emit_for_removed_annotation(
        surface, "site:call-release", AnnotationRole.FRAME
    )
    holes = emission.holes_of_kind(HoleKind.FRAME)
    assert len(holes) == 1
    hole = holes[0]
    assert hole.status is HoleStatus.OPEN
    assert hole.source.span_ids == ("span:call-release",)
    assert hole.expected_authority is AuthorityCeiling.SATISFIABILITY
    assert hole.validation_recipe is not None
    assert hole.validation_recipe.checker_kind == "smt_frame_check"
    assert "frame" in hole.reason.lower() or "missing" in hole.reason.lower()
    assert hole.dependency_ids  # includes site dependency
    assert "site:loop-claim" in hole.dependency_ids
    assert hole.hole_id in emission.missing_proof_hole_ids


def test_removing_callee_precondition_yields_contract_hole() -> None:
    emission = TypedProofHoleEmitter().emit_for_removed_annotation(
        _complete_surface(),
        "site:call-release",
        AnnotationRole.CALLEE_PRECONDITION,
    )
    holes = emission.holes_of_kind(HoleKind.CALLEE_PRECONDITION)
    assert len(holes) == 1
    hole = holes[0]
    assert hole.kind is HoleKind.CALLEE_PRECONDITION
    assert hole.validation_recipe is not None
    assert hole.validation_recipe.required_authority is AuthorityCeiling.SATISFIABILITY
    assert hole.source.source_ref_ids == ("source:lease.py",)


def test_removing_fairness_premise_yields_temporal_hole() -> None:
    emission = TypedProofHoleEmitter().emit_for_removed_annotation(
        _complete_surface(),
        "site:fair-scheduler",
        AnnotationRole.TEMPORAL_FAIRNESS,
    )
    holes = emission.holes_of_kind(HoleKind.TEMPORAL_FAIRNESS)
    assert len(holes) == 1
    hole = holes[0]
    assert hole.status is HoleStatus.OPEN
    assert hole.property_class is PropertyClass.LIVENESS
    assert hole.expected_authority is AuthorityCeiling.MODEL_CHECK
    assert hole.validation_recipe is not None
    assert hole.validation_recipe.checker_kind == "temporal_fairness_check"
    assert hole.source.span_ids == ("span:fairness",)
    assert hole.hole_id in emission.missing_proof_hole_ids


def test_removing_bridge_lemma_yields_bridge_hole() -> None:
    emission = TypedProofHoleEmitter().emit_for_removed_annotation(
        _complete_surface(),
        "site:bridge-smt-lean",
        AnnotationRole.BRIDGE_LEMMA,
    )
    holes = emission.holes_of_kind(HoleKind.BRIDGE_LEMMA)
    assert len(holes) == 1
    hole = holes[0]
    assert hole.status is HoleStatus.OPEN
    assert hole.property_class is PropertyClass.THEOREM
    assert hole.expected_authority is AuthorityCeiling.THEOREM
    assert hole.validation_recipe is not None
    assert hole.validation_recipe.checker_kind == "kernel_bridge_lemma_check"
    assert "bridge" in hole.reason.lower() or "missing" in hole.reason.lower()
    assert "site:call-release" in hole.dependency_ids
    assert hole.hole_id in emission.missing_proof_hole_ids


def test_removing_multiple_annotations_emits_all_matching_holes() -> None:
    surface = (
        _complete_surface()
        .without_annotation("site:loop-claim", AnnotationRole.LOOP_INVARIANT)
        .without_annotation("site:call-release", AnnotationRole.FRAME)
        .without_annotation("site:fair-scheduler", AnnotationRole.TEMPORAL_FAIRNESS)
        .without_annotation("site:bridge-smt-lean", AnnotationRole.BRIDGE_LEMMA)
    )
    emission = TypedProofHoleEmitter().emit(surface)
    kinds = {hole.kind for hole in emission.holes}
    assert kinds == {
        HoleKind.LOOP_INVARIANT,
        HoleKind.FRAME,
        HoleKind.TEMPORAL_FAIRNESS,
        HoleKind.BRIDGE_LEMMA,
    }
    assert len(emission.missing_proof_hole_ids) == 4
    assert emission.non_proof_hole_ids == ()
    for hole in emission.holes:
        assert hole.validation_recipe is not None
        assert hole.source.span_ids
        assert hole.reason
        assert hole.proof_claimed is False


# ---------------------------------------------------------------------------
# Unsupported semantics ≠ missing proof
# ---------------------------------------------------------------------------


def test_unsupported_semantics_distinct_from_missing_proof() -> None:
    surface = CompilationSurface(
        surface_id="surface:mixed",
        formal_goal_id="formal:mixed",
        sites=(
            loop_site(
                "site:loop",
                source=_source(span_ids=("span:loop",)),
                has_invariant=False,
            ),
            unsupported_semantics_site(
                "site:ffi",
                source=_source(
                    source_ref_ids=("source:ffi.c",),
                    span_ids=("span:ffi",),
                ),
                description="inline assembly is outside the supported semantic profile",
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    missing = emission.missing_proof_holes
    non_proof = emission.non_proof_holes
    assert len(missing) == 1
    assert missing[0].kind is HoleKind.LOOP_INVARIANT
    assert missing[0].status is HoleStatus.OPEN
    assert len(non_proof) == 1
    assert non_proof[0].kind is HoleKind.UNSUPPORTED_SEMANTICS
    assert non_proof[0].status is HoleStatus.UNSUPPORTED
    assert non_proof[0].expected_authority is AuthorityCeiling.NONE
    assert non_proof[0].validation_recipe is not None
    assert "do_not_discharge" in non_proof[0].validation_recipe.steps
    # Partition is disjoint and complete.
    assert set(emission.missing_proof_hole_ids).isdisjoint(
        set(emission.non_proof_hole_ids)
    )
    assert set(emission.missing_proof_hole_ids) | set(
        emission.non_proof_hole_ids
    ) == {hole.hole_id for hole in emission.holes}


def test_unavailable_tool_is_non_proof_unavailable() -> None:
    surface = CompilationSurface(
        surface_id="surface:tools",
        sites=(
            unavailable_tool_site(
                "site:tool-cvc5",
                source=_source(span_ids=("span:tool",)),
                tool_id="cvc5",
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    assert len(emission.holes) == 1
    hole = emission.holes[0]
    assert hole.kind is HoleKind.UNAVAILABLE_TOOL
    assert hole.status is HoleStatus.UNAVAILABLE
    assert hole.hole_id in emission.non_proof_hole_ids
    assert emission.missing_proof_hole_ids == ()
    assert not is_missing_proof_role(AnnotationRole.UNAVAILABLE_TOOL)


def test_hole_status_for_role_partition() -> None:
    assert hole_status_for_role(AnnotationRole.LOOP_INVARIANT) is HoleStatus.OPEN
    assert hole_status_for_role(AnnotationRole.UNSUPPORTED_SEMANTICS) is (
        HoleStatus.UNSUPPORTED
    )
    assert hole_status_for_role(AnnotationRole.UNAVAILABLE_TOOL) is (
        HoleStatus.UNAVAILABLE
    )
    assert hole_status_for_role(AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE) is (
        HoleStatus.FALSE
    )
    assert is_missing_proof_role(AnnotationRole.BRIDGE_LEMMA)
    assert not is_missing_proof_role(AnnotationRole.UNSUPPORTED_SEMANTICS)


# ---------------------------------------------------------------------------
# Fail-closed: no invented defaults; source spans required
# ---------------------------------------------------------------------------


def test_emitter_never_invents_default_invariants() -> None:
    surface = CompilationSurface(
        surface_id="surface:bare-loop",
        sites=(
            loop_site(
                "site:loop",
                source=_source(span_ids=("span:loop",)),
                has_invariant=False,
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    assert len(emission.holes) == 1
    assert emission.invented_defaults is False
    # Re-emitting does not fill the invariant.
    again = TypedProofHoleEmitter().emit(surface)
    assert again.holes[0].kind is HoleKind.LOOP_INVARIANT
    assert again.holes[0].status is HoleStatus.OPEN


def test_require_source_spans_fail_closed() -> None:
    bare = SourceSpanBinding(tree_id="tree:x")
    surface = CompilationSurface(
        surface_id="surface:no-span",
        sites=(
            AnnotationSite(
                site_id="site:x",
                site_kind=SiteKind.LOOP,
                source=bare,
                required_roles=frozenset({AnnotationRole.LOOP_INVARIANT}),
                present_roles=frozenset(),
            ),
        ),
    )
    with pytest.raises(ProofHoleEmissionError, match="source span"):
        TypedProofHoleEmitter(require_source_spans=True).emit(surface)
    # Opt-out still emits.
    emission = TypedProofHoleEmitter(require_source_spans=False).emit(surface)
    assert len(emission.holes) == 1


def test_without_annotation_unknown_site_fails() -> None:
    with pytest.raises(ProofHoleEmissionError, match="unknown site"):
        _complete_surface().without_annotation(
            "site:missing", AnnotationRole.LOOP_INVARIANT
        )


def test_duplicate_site_ids_rejected() -> None:
    site = loop_site(
        "site:dup",
        source=_source(span_ids=("span:a",)),
        has_invariant=True,
    )
    with pytest.raises(ProofHoleEmissionError, match="duplicate"):
        CompilationSurface(surface_id="s", sites=(site, site))


def test_emission_rejects_invented_defaults_flag() -> None:
    with pytest.raises(ProofHoleEmissionError, match="never invent"):
        ProofHoleEmission(
            emission_id="e1",
            surface_id="s1",
            formal_goal_id="",
            holes=(),
            missing_proof_hole_ids=(),
            non_proof_hole_ids=(),
            invented_defaults=True,
        )


# ---------------------------------------------------------------------------
# Loop variant under total-correctness policy
# ---------------------------------------------------------------------------


def test_missing_loop_variant_under_require_variant() -> None:
    surface = CompilationSurface(
        surface_id="surface:total",
        sites=(
            loop_site(
                "site:loop",
                source=_source(span_ids=("span:loop",)),
                has_invariant=True,
                has_variant=False,
                require_variant=True,
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    assert [hole.kind for hole in emission.holes] == [HoleKind.LOOP_VARIANT]
    hole = emission.holes[0]
    assert hole.property_class is PropertyClass.TERMINATION
    assert hole.validation_recipe is not None
    assert "check_decrease" in hole.validation_recipe.steps


def test_missing_both_invariant_and_variant() -> None:
    surface = CompilationSurface(
        surface_id="surface:total-bare",
        sites=(
            loop_site(
                "site:loop",
                source=_source(span_ids=("span:loop",)),
                has_invariant=False,
                has_variant=False,
                require_variant=True,
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    kinds = {hole.kind for hole in emission.holes}
    assert kinds == {HoleKind.LOOP_INVARIANT, HoleKind.LOOP_VARIANT}
    # Cross-dependencies among peer missing roles at the same site.
    inv = emission.holes_of_kind(HoleKind.LOOP_INVARIANT)[0]
    var = emission.holes_of_kind(HoleKind.LOOP_VARIANT)[0]
    assert var.hole_id in inv.dependency_ids
    assert inv.hole_id in var.dependency_ids


# ---------------------------------------------------------------------------
# Serialization and convenience API
# ---------------------------------------------------------------------------


def test_surface_and_emission_round_trip() -> None:
    surface = _complete_surface().without_annotation(
        "site:loop-claim", AnnotationRole.LOOP_INVARIANT
    )
    restored_surface = CompilationSurface.from_dict(surface.to_dict())
    assert restored_surface.surface_id == surface.surface_id
    assert restored_surface.site("site:loop-claim").missing_roles == frozenset(
        {AnnotationRole.LOOP_INVARIANT}
    )

    emission = emit_typed_proof_holes(surface)
    restored = ProofHoleEmission.from_dict(emission.to_dict())
    assert restored.content_id == emission.content_id
    assert len(restored.holes) == 1
    assert restored.holes[0].kind is HoleKind.LOOP_INVARIANT
    record = emission.to_record()
    assert record["interface"] == TYPED_PROOF_HOLE_EMITTER_INTERFACE
    assert "content_id" in record


def test_annotation_site_from_dict() -> None:
    site = loop_site(
        "site:x",
        source=_source(span_ids=("span:x",)),
        has_invariant=False,
    )
    restored = AnnotationSite.from_dict(site.to_dict())
    assert restored.site_id == site.site_id
    assert restored.missing_roles == frozenset({AnnotationRole.LOOP_INVARIANT})
    assert restored.site_kind is SiteKind.LOOP


def test_default_validation_recipe_covers_roles() -> None:
    recipe = default_validation_recipe(AnnotationRole.FRAME, site_id="s1")
    assert recipe.checker_kind == "smt_frame_check"
    assert recipe.required_authority is AuthorityCeiling.SATISFIABILITY
    assert recipe.steps


def test_emit_from_mapping_surface() -> None:
    surface = CompilationSurface(
        surface_id="surface:map",
        sites=(
            fairness_site(
                "site:f",
                source=_source(span_ids=("span:f",)),
                has_fairness_premise=False,
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface.to_dict())
    assert len(emission.holes) == 1
    assert emission.holes[0].kind is HoleKind.TEMPORAL_FAIRNESS


def test_identity_stable_for_same_surface() -> None:
    surface = _complete_surface().without_annotation(
        "site:bridge-smt-lean", AnnotationRole.BRIDGE_LEMMA
    )
    a = TypedProofHoleEmitter().emit(surface)
    b = TypedProofHoleEmitter().emit(surface)
    assert a.emission_id == b.emission_id
    assert a.content_id == b.content_id
    assert a.holes[0].content_id == b.holes[0].content_id


def test_hole_for_site_role_lookup() -> None:
    emission = TypedProofHoleEmitter().emit_for_removed_annotation(
        _complete_surface(),
        "site:loop-claim",
        AnnotationRole.LOOP_INVARIANT,
    )
    hole = emission.hole_for_site_role("site:loop-claim", AnnotationRole.LOOP_INVARIANT)
    assert hole is not None
    assert hole.kind is HoleKind.LOOP_INVARIANT
    assert emission.hole_for_site_role("site:loop-claim", AnnotationRole.FRAME) is None


def test_callee_site_multiple_missing_roles() -> None:
    surface = CompilationSurface(
        surface_id="surface:call",
        sites=(
            callee_site(
                "site:call",
                source=_source(span_ids=("span:call",)),
                has_precondition=False,
                has_postcondition=False,
                has_frame=False,
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    kinds = {hole.kind for hole in emission.holes}
    assert kinds == {
        HoleKind.CALLEE_PRECONDITION,
        HoleKind.CALLEE_POSTCONDITION,
        HoleKind.FRAME,
    }
    for hole in emission.holes:
        assert hole.status is HoleStatus.OPEN
        assert hole.validation_recipe is not None
        assert hole.source.span_ids == ("span:call",)


def test_required_implementation_change_is_false_status() -> None:
    surface = CompilationSurface(
        surface_id="surface:impl",
        sites=(
            AnnotationSite(
                site_id="site:impl",
                site_kind=SiteKind.IMPLEMENTATION,
                source=_source(span_ids=("span:impl",)),
                required_roles=frozenset(
                    {AnnotationRole.REQUIRED_IMPLEMENTATION_CHANGE}
                ),
                present_roles=frozenset(),
                statement="goal is false of the current program",
                rationale="A proof cannot close a false goal of the implementation.",
            ),
        ),
    )
    emission = TypedProofHoleEmitter().emit(surface)
    hole = emission.holes[0]
    assert hole.kind is HoleKind.REQUIRED_IMPLEMENTATION_CHANGE
    assert hole.status is HoleStatus.FALSE
    assert hole.hole_id in emission.non_proof_hole_ids
