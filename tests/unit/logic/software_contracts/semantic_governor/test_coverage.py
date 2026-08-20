"""Unit tests for ContextCoverageManifest builder (SCG-011).

Acceptance criteria enforced here:

* Critical heuristic exclusion rejects.
* Sufficient exact contexts remain unexpanded.
* Identical inputs yield deterministic manifest identities.
"""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    ContextCoverageManifest,
    CoveredArtifactKind,
    ExclusionReason,
    GraphPath,
    InclusionKind,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.coverage import (
    BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE,
    AnalysisConfidenceRank,
    CoverageBuilderError,
    CoverageExclusionView,
    CoverageGapView,
    CoverageInclusionView,
    VerifiedCoverageView,
    admitted_exclusion_reasons,
    assert_exclusion_admissible,
    build_context_coverage_manifest,
    coverage_builder_interface_id,
    heuristic_exclusion_labels,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _path(*nodes: str) -> GraphPath:
    return GraphPath(nodes=nodes or ("target_fn", "helper_fn"), edge_relation="calls")


def _span(path: str = "pkg/module.py", start: int = 1, end: int = 10) -> SourceSpan:
    return SourceSpan(path=path, start_line=start, end_line=end, start_col=1, end_col=1)


def _inclusion(**overrides: object) -> CoverageInclusionView:
    fields: dict[str, object] = {
        "artifact_id": "inc_target",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "inclusion_kind": InclusionKind.RAW_SOURCE,
        "token_cost": 100,
        "confidence": AnalysisConfidenceRank.EXACT.value,
        "symbol_id": "target_fn",
        "path": "pkg/module.py",
        "artifact_cid": _cid("inc-target"),
        "dependency_path": _path("target_fn"),
        "source_span": _span(),
        "exact_required": True,
        "notes": None,
    }
    fields.update(overrides)
    return CoverageInclusionView(**fields)  # type: ignore[arg-type]


def _exclusion(**overrides: object) -> CoverageExclusionView:
    fields: dict[str, object] = {
        "artifact_id": "exc_helper",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "exclusion_reason": ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value,
        "token_cost": 40,
        "confidence": AnalysisConfidenceRank.EXACT.value,
        "confidence_bp": 10_000,
        "symbol_id": "helper_fn",
        "path": "pkg/helper.py",
        "artifact_cid": _cid("exc-helper"),
        "dependency_path": _path("target_fn", "helper_fn"),
        "source_span": _span("pkg/helper.py", 1, 5),
        "repository_state_cid": _cid("repo-state"),
        "substituted_by_artifact_id": "inc_capsule_helper",
        "critical": False,
        "notes": None,
    }
    fields.update(overrides)
    return CoverageExclusionView(**fields)  # type: ignore[arg-type]


def _view(**overrides: object) -> VerifiedCoverageView:
    inclusions = overrides.pop("inclusions", None)
    exclusions = overrides.pop("exclusions", None)
    if inclusions is None:
        inclusions = (
            _inclusion(),
            _inclusion(
                artifact_id="inc_capsule_helper",
                inclusion_kind=InclusionKind.EXACT_CAPSULE,
                token_cost=20,
                symbol_id="helper_fn",
                path="pkg/helper.py",
                artifact_cid=_cid("capsule-helper"),
                exact_required=False,
                dependency_path=_path("target_fn", "helper_fn"),
                source_span=_span("pkg/helper.py", 1, 5),
            ),
        )
    if exclusions is None:
        exclusions = (_exclusion(),)
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "context_pack_cid": _cid("context-pack"),
        "verification_bundle_cid": _cid("verification-bundle"),
        "target_symbol_ids": ("target_fn",),
        "inclusions": inclusions,
        "exclusions": exclusions,
        "context_budget_tokens": 500,
        "minimum_safe_tokens": None,
        "known_gaps": (),
        "opaque_dependency_ids": (),
        "dependency_paths": (_path("target_fn", "helper_fn"),),
        "policy_cid": _cid("policy"),
        "assumption_statements": (),
        "notes": None,
        "metadata": {},
        "require_target_inclusions": True,
    }
    fields.update(overrides)
    return VerifiedCoverageView(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface surface
# ---------------------------------------------------------------------------


def test_interface_pin() -> None:
    assert coverage_builder_interface_id() == BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE
    assert BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE.endswith("@1")
    assert "exact_capsule_substituted" in admitted_exclusion_reasons()
    assert "heuristic_irrelevance" in heuristic_exclusion_labels()


# ---------------------------------------------------------------------------
# Acceptance: critical heuristic exclusion rejects
# ---------------------------------------------------------------------------


def test_critical_heuristic_irrelevance_rejects() -> None:
    exclusion = _exclusion(
        artifact_id="exc_critical",
        exclusion_reason="heuristic_irrelevance",
        critical=True,
        substituted_by_artifact_id=None,
        confidence=AnalysisConfidenceRank.HEURISTIC.value,
    )
    with pytest.raises(CoverageBuilderError, match="critical heuristic exclusion"):
        assert_exclusion_admissible(exclusion)
    with pytest.raises(CoverageBuilderError, match="critical heuristic exclusion"):
        build_context_coverage_manifest(_view(exclusions=(exclusion,)))


def test_critical_looks_irrelevant_rejects() -> None:
    exclusion = _exclusion(
        artifact_id="exc_critical_looks",
        exclusion_reason="looks_irrelevant",
        critical=True,
        substituted_by_artifact_id=None,
        confidence=AnalysisConfidenceRank.HEURISTIC.value,
    )
    with pytest.raises(CoverageBuilderError, match="heuristic"):
        build_context_coverage_manifest(_view(exclusions=(exclusion,)))


def test_critical_exclusion_under_heuristic_confidence_rejects() -> None:
    """Closed reason does not admit critical exclusion under heuristic confidence."""
    exclusion = _exclusion(
        artifact_id="exc_critical_heur",
        exclusion_reason=ExclusionReason.PROVEN_UNRELATED_BY_DEPENDENCY_GRAPH.value,
        critical=True,
        confidence=AnalysisConfidenceRank.HEURISTIC.value,
        confidence_bp=5_000,
        substituted_by_artifact_id=None,
    )
    with pytest.raises(CoverageBuilderError, match="critical heuristic exclusion"):
        build_context_coverage_manifest(_view(exclusions=(exclusion,)))


def test_critical_proof_style_requires_exact_confidence() -> None:
    exclusion = _exclusion(
        artifact_id="exc_critical_proof",
        exclusion_reason=ExclusionReason.OUTSIDE_AFFECTED_INVALIDATION_CONE.value,
        critical=True,
        confidence=AnalysisConfidenceRank.CONSERVATIVE.value,
        confidence_bp=8_000,
        substituted_by_artifact_id=None,
    )
    with pytest.raises(CoverageBuilderError, match="critical heuristic exclusion"):
        assert_exclusion_admissible(exclusion)


def test_non_critical_closed_exclusion_under_heuristic_confidence_ok() -> None:
    """Non-critical artifacts may use closed reasons with lower confidence."""
    exclusion = _exclusion(
        artifact_id="exc_noncritical",
        exclusion_reason=ExclusionReason.DUPLICATE_REPRESENTATION.value,
        critical=False,
        confidence=AnalysisConfidenceRank.HEURISTIC.value,
        confidence_bp=5_000,
        substituted_by_artifact_id=None,
    )
    manifest = build_context_coverage_manifest(_view(exclusions=(exclusion,)))
    assert manifest.exclusion_count == 1
    assert manifest.exclusions[0].exclusion_reason == (
        ExclusionReason.DUPLICATE_REPRESENTATION.value
    )


def test_critical_exact_capsule_substitution_admitted() -> None:
    exclusion = _exclusion(
        artifact_id="exc_critical_sub",
        exclusion_reason=ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value,
        critical=True,
        confidence=AnalysisConfidenceRank.EXACT.value,
        confidence_bp=10_000,
        substituted_by_artifact_id="inc_capsule_helper",
    )
    manifest = build_context_coverage_manifest(_view(exclusions=(exclusion,)))
    assert manifest.exclusions[0].critical is True
    assert manifest.exclusions[0].exclusion_reason == (
        ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value
    )


def test_unknown_exclusion_reason_rejects() -> None:
    exclusion = _exclusion(
        exclusion_reason="not_a_real_reason",
        substituted_by_artifact_id=None,
    )
    with pytest.raises(CoverageBuilderError, match="exclusion_reason"):
        build_context_coverage_manifest(_view(exclusions=(exclusion,)))


def test_exclusion_requires_graph_or_state_binding() -> None:
    exclusion = _exclusion(
        dependency_path=None,
        repository_state_cid=None,
        substituted_by_artifact_id=None,
        exclusion_reason=ExclusionReason.DUPLICATE_REPRESENTATION.value,
    )
    with pytest.raises(CoverageBuilderError, match="graph/state bound"):
        build_context_coverage_manifest(_view(exclusions=(exclusion,)))


# ---------------------------------------------------------------------------
# Acceptance: sufficient exact contexts remain unexpanded
# ---------------------------------------------------------------------------


def test_exact_required_raw_source_preserved() -> None:
    view = _view(
        exclusions=(),
        inclusions=(
            _inclusion(exact_required=True, inclusion_kind=InclusionKind.RAW_SOURCE),
        ),
    )
    manifest = build_context_coverage_manifest(view)
    assert manifest.raw_inclusion_count == 1
    assert manifest.capsule_inclusion_count == 0
    assert manifest.inclusions[0].inclusion_kind == InclusionKind.RAW_SOURCE.value
    assert manifest.metadata["exact_required_count"] == 1
    # No expansion: excluded nothing, no invented raw additions.
    assert manifest.exclusion_count == 0
    assert len(manifest.inclusions) == 1


def test_exact_capsule_not_force_expanded_to_raw() -> None:
    """Exact capsule substitutions stay as capsules; builder does not expand them."""
    inclusions = (
        _inclusion(exact_required=True),
        _inclusion(
            artifact_id="inc_capsule_helper",
            inclusion_kind=InclusionKind.EXACT_CAPSULE,
            token_cost=20,
            symbol_id="helper_fn",
            path="pkg/helper.py",
            artifact_cid=_cid("capsule-helper"),
            exact_required=False,
            confidence=AnalysisConfidenceRank.EXACT.value,
            dependency_path=_path("target_fn", "helper_fn"),
            source_span=_span("pkg/helper.py", 1, 5),
        ),
    )
    exclusions = (
        _exclusion(
            exclusion_reason=ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value,
            substituted_by_artifact_id="inc_capsule_helper",
            confidence=AnalysisConfidenceRank.EXACT.value,
        ),
    )
    manifest = build_context_coverage_manifest(
        _view(inclusions=inclusions, exclusions=exclusions)
    )
    kinds = {item.artifact_id: item.inclusion_kind for item in manifest.inclusions}
    assert kinds["inc_target"] == InclusionKind.RAW_SOURCE.value
    assert kinds["inc_capsule_helper"] == InclusionKind.EXACT_CAPSULE.value
    # Sufficient exact context: minimum_safe equals exact inclusion costs only.
    assert manifest.minimum_safe_tokens == 120
    assert manifest.total_included_tokens == 120
    assert manifest.capsule_inclusion_count == 1
    assert manifest.raw_inclusion_count == 1


def test_exact_required_rejects_non_raw_inclusion() -> None:
    with pytest.raises(CoverageBuilderError, match="exact_required"):
        _inclusion(
            exact_required=True,
            inclusion_kind=InclusionKind.EXACT_CAPSULE,
            confidence=AnalysisConfidenceRank.EXACT.value,
        )


def test_sufficient_exact_context_does_not_add_opaque_expansion() -> None:
    """Without opaque deps, a complete exact view has no expansion gaps."""
    manifest = build_context_coverage_manifest(
        _view(opaque_dependency_ids=(), known_gaps=())
    )
    assert manifest.known_gaps == ()
    assert manifest.opaque_dependency_ids == ()


def test_opaque_dependencies_surface_as_gaps_not_silent_drop() -> None:
    manifest = build_context_coverage_manifest(
        _view(opaque_dependency_ids=("dyn_import_x",))
    )
    assert "dyn_import_x" in manifest.opaque_dependency_ids
    assert any(
        gap.gap_kind == "opaque_dependency" and gap.critical
        for gap in manifest.known_gaps
    )


# ---------------------------------------------------------------------------
# Acceptance: identical inputs yield deterministic manifest identities
# ---------------------------------------------------------------------------


def test_identical_inputs_yield_identical_manifest_cid() -> None:
    view = _view()
    first = build_context_coverage_manifest(view)
    second = build_context_coverage_manifest(view)
    assert first.manifest_cid == second.manifest_cid
    assert first.to_dict() == second.to_dict()
    restored = ContextCoverageManifest.from_dict(first.to_dict())
    assert restored.manifest_cid == first.manifest_cid


def test_input_order_does_not_affect_identity() -> None:
    """Shuffled inclusion/exclusion order must not change manifest_cid."""
    inc_a = _inclusion(artifact_id="inc_a", symbol_id="target_fn", exact_required=True)
    inc_b = _inclusion(
        artifact_id="inc_b",
        inclusion_kind=InclusionKind.EXACT_CAPSULE,
        token_cost=15,
        symbol_id="helper_fn",
        path="pkg/helper.py",
        artifact_cid=_cid("cap-b"),
        exact_required=False,
    )
    exc_a = _exclusion(
        artifact_id="exc_a",
        symbol_id="helper_fn",
        substituted_by_artifact_id="inc_b",
    )
    exc_b = _exclusion(
        artifact_id="exc_b",
        exclusion_reason=ExclusionReason.DUPLICATE_REPRESENTATION.value,
        symbol_id="helper_fn_dup",
        path="pkg/helper_dup.py",
        substituted_by_artifact_id=None,
        artifact_cid=_cid("exc-b"),
    )
    view_fwd = _view(
        inclusions=(inc_a, inc_b),
        exclusions=(exc_a, exc_b),
        dependency_paths=(
            _path("target_fn", "helper_fn"),
            _path("target_fn", "helper_fn_dup"),
        ),
    )
    view_rev = _view(
        inclusions=(inc_b, inc_a),
        exclusions=(exc_b, exc_a),
        dependency_paths=(
            _path("target_fn", "helper_fn_dup"),
            _path("target_fn", "helper_fn"),
        ),
    )
    m1 = build_context_coverage_manifest(view_fwd)
    m2 = build_context_coverage_manifest(view_rev)
    assert m1.manifest_cid == m2.manifest_cid
    assert [item.artifact_id for item in m1.inclusions] == [
        item.artifact_id for item in m2.inclusions
    ]
    assert [item.artifact_id for item in m1.exclusions] == [
        item.artifact_id for item in m2.exclusions
    ]


def test_mapping_input_matches_dataclass_input() -> None:
    view = _view()
    from_obj = build_context_coverage_manifest(view)
    from_map = build_context_coverage_manifest(view.to_dict())
    assert from_obj.manifest_cid == from_map.manifest_cid


def test_view_cid_stable_under_deepcopy() -> None:
    view = _view()
    payload = copy.deepcopy(view.to_dict())
    payload.pop("view_cid", None)
    payload.pop("schema", None)
    clone = VerifiedCoverageView(**payload)  # type: ignore[arg-type]
    assert clone.view_cid == view.view_cid
    assert build_context_coverage_manifest(clone).manifest_cid == (
        build_context_coverage_manifest(view).manifest_cid
    )


# ---------------------------------------------------------------------------
# Completeness: attribution, totals, budget, assumptions
# ---------------------------------------------------------------------------


def test_manifest_attributes_inclusions_exclusions_paths_and_costs() -> None:
    manifest = build_context_coverage_manifest(_view())
    assert manifest.header.artifact_kind == "context_coverage_manifest"
    assert (
        manifest.header.generator.interface_id
        == BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE
    )
    assert manifest.target_symbol_ids == ("target_fn",)
    assert manifest.total_included_tokens == sum(
        item.token_cost for item in manifest.inclusions
    )
    assert manifest.total_excluded_tokens == sum(
        item.token_cost for item in manifest.exclusions
    )
    assert manifest.exclusion_count == len(manifest.exclusions)
    assert manifest.raw_inclusion_count == 1
    assert manifest.capsule_inclusion_count == 1
    assert manifest.dependency_paths
    assert any(
        assumption.assumption_id == "coverage_closed"
        for assumption in manifest.header.assumptions
    )
    assert any(
        assumption.assumption_id == "exact_contexts_unexpanded"
        for assumption in manifest.header.assumptions
    )


def test_budget_overflow_rejects() -> None:
    with pytest.raises(CoverageBuilderError, match="context_budget_tokens"):
        build_context_coverage_manifest(
            _view(
                context_budget_tokens=50,
                inclusions=(
                    _inclusion(token_cost=100, exact_required=True),
                ),
                exclusions=(),
            )
        )


def test_budget_exclusion_derives_gap() -> None:
    exclusion = _exclusion(
        artifact_id="exc_budget",
        exclusion_reason=ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value,
        substituted_by_artifact_id=None,
        critical=False,
        confidence=AnalysisConfidenceRank.EXACT.value,
    )
    manifest = build_context_coverage_manifest(_view(exclusions=(exclusion,)))
    assert any(gap.gap_kind == "budget_truncation" for gap in manifest.known_gaps)


def test_known_gap_view_preserved() -> None:
    gap = CoverageGapView(
        gap_id="gap_missing_fixture",
        gap_kind="missing_fixture",
        description="Fixture not represented in pack",
        artifact_id="fix_a",
        path="tests/test_a.py",
        critical=False,
        supporting_cids=(_cid("fixture-evidence"),),
    )
    manifest = build_context_coverage_manifest(_view(known_gaps=(gap,)))
    assert manifest.known_gaps[0].gap_id == "gap_missing_fixture"
    assert manifest.known_gaps[0].gap_kind == "missing_fixture"


def test_missing_target_inclusion_rejects() -> None:
    with pytest.raises(CoverageBuilderError, match="target_symbol_id"):
        _view(
            target_symbol_ids=("target_fn", "other_fn"),
            inclusions=(_inclusion(symbol_id="target_fn"),),
            exclusions=(),
        )


def test_duplicate_inclusion_ids_reject() -> None:
    with pytest.raises(CoverageBuilderError, match="duplicate artifact_id"):
        _view(
            inclusions=(
                _inclusion(artifact_id="inc_same"),
                _inclusion(
                    artifact_id="inc_same",
                    exact_required=False,
                    inclusion_kind=InclusionKind.TEST,
                    symbol_id="target_fn",
                ),
            ),
            exclusions=(),
        )


def test_overlap_include_exclude_rejects() -> None:
    with pytest.raises(CoverageBuilderError, match="both included and excluded"):
        _view(
            inclusions=(_inclusion(artifact_id="shared_id"),),
            exclusions=(_exclusion(artifact_id="shared_id"),),
        )


def test_explicit_manifest_id() -> None:
    manifest = build_context_coverage_manifest(
        _view(),
        manifest_id="manifest_custom_id",
    )
    assert manifest.manifest_id == "manifest_custom_id"


def test_substitution_requires_substitute_id() -> None:
    exclusion = _exclusion(
        exclusion_reason=ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value,
        substituted_by_artifact_id=None,
        confidence=AnalysisConfidenceRank.CONSERVATIVE.value,
    )
    with pytest.raises(CoverageBuilderError, match="substituted_by_artifact_id"):
        build_context_coverage_manifest(_view(exclusions=(exclusion,)))


def test_minimum_safe_tokens_declared_honored() -> None:
    manifest = build_context_coverage_manifest(
        _view(minimum_safe_tokens=90, exclusions=())
    )
    assert manifest.minimum_safe_tokens == 90


def test_header_binds_repository_and_context_pack() -> None:
    view = _view()
    manifest = build_context_coverage_manifest(view)
    assert manifest.header.repository_state_cid == view.repository_state_cid
    assert manifest.header.context_pack_cid == view.context_pack_cid
    assert manifest.header.verification_bundle_cid == view.verification_bundle_cid
    assert view.view_cid in manifest.header.provenance.input_cids
