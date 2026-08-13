"""Regression tests for deterministic requirement discovery (IPS-014)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.dependency_graph import (
    DependencyEdgeType,
    DependencyNodeKind,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.discovery import (
    DISCOVERY_SUBSET,
    FRONTIER_KINDS,
    LOCATOR_KINDS,
    LOGICAL_UNIT_IDENTITY_SCHEMA,
    DiscoveredCandidate,
    DiscoveryDependencyEdge,
    DiscoveryError,
    DiscoveryFrontier,
    FrontierKind,
    LocatorKind,
    LogicalProofUnitIdentity,
    ProofUnitSelector,
    RequirementDiscoveryResult,
    assert_unknown_frontiers_do_not_narrow,
    build_manifest_from_discovery,
    build_proof_dependency_graph,
    build_verification_requirement_manifest,
    candidate_for_direct_computation,
    candidate_for_receipt_aggregate,
    candidate_for_release_invariant,
    candidate_from_property,
    candidate_from_symbol,
    candidate_from_test,
    classify_rename_or_delete,
    closed_discovery_selection_sources,
    closed_frontier_kinds,
    closed_locator_kinds,
    diff_discovered_unit_ids,
    discover_requirements,
    known_vectors,
    mint_logical_proof_unit_id,
    parse_frontier_kind,
    parse_locator_kind,
    sample_candidates,
    sample_discovery_result,
    sample_selector,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import ProofUnitKind
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    ABSENCE_TOKEN,
    PropertyIdentity,
    SourceSymbolIdentity,
    TestSelectorIdentity,
    canonical_cid,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.manifest import (
    sample_verification_policy,
)


def _cid(label: str) -> str:
    return canonical_cid({"ips_discovery_test": label, "v": 1})


def _symbol(
    *,
    qualified_name: str = "pkg.main:entry",
    module_path: str = "pkg/main.py",
    repository_id: str = "repo/datasets",
) -> SourceSymbolIdentity:
    return SourceSymbolIdentity(
        repository_id=repository_id,
        module_path=module_path,
        qualified_name=qualified_name,
        symbol_kind="function",
        source_artifact_id=_cid(f"artifact:{module_path}"),
    )


def _test(
    *,
    node_id: str = "tests/test_main.py::test_entry",
    module_path: str = "tests/test_main.py",
    function_name: str = "test_entry",
    parameter_case: str = ABSENCE_TOKEN,
    repository_id: str = "repo/datasets",
) -> TestSelectorIdentity:
    return TestSelectorIdentity(
        repository_id=repository_id,
        node_id=node_id,
        module_path=module_path,
        function_name=function_name,
        parameter_case=parameter_case,
    )


def _property(
    *,
    name: str = "prop/output-soundness",
    repository_id: str = "repo/datasets",
) -> PropertyIdentity:
    return PropertyIdentity(
        repository_id=repository_id,
        property_name=name,
        statement_cid=_cid(f"statement:{name}"),
        obligation_kind="formal_obligation",
    )


# ---------------------------------------------------------------------------
# Closed surface
# ---------------------------------------------------------------------------


def test_subset_and_closed_sets() -> None:
    assert DISCOVERY_SUBSET == "ips/requirement-discovery@1"
    assert closed_frontier_kinds() == frozenset(FRONTIER_KINDS)
    assert closed_locator_kinds() == frozenset(LOCATOR_KINDS)
    assert "selected_test" in closed_discovery_selection_sources()
    assert "discovery_selected" in closed_discovery_selection_sources()
    for name in FRONTIER_KINDS:
        assert parse_frontier_kind(name).value == name
    for name in LOCATOR_KINDS:
        assert parse_locator_kind(name).value == name
    with pytest.raises(DiscoveryError, match="unknown FrontierKind"):
        parse_frontier_kind("maybe_covered")
    with pytest.raises(DiscoveryError, match="unknown LocatorKind"):
        parse_locator_kind("blob")


def test_build_verification_requirement_manifest_is_reexported() -> None:
    assert callable(build_verification_requirement_manifest)


# ---------------------------------------------------------------------------
# Acceptance: stable logical IDs survive context changes
# ---------------------------------------------------------------------------


def test_stable_logical_ids_survive_context_changes() -> None:
    source_a = _cid("source-a")
    source_b = _cid("source-b")
    state_a = _cid("state-a")
    state_b = _cid("state-b")

    left = candidate_from_test(
        _test(),
        source_root_cid=source_a,
        repository_state_cid=state_a,
    )
    right = candidate_from_test(
        _test(),
        source_root_cid=source_b,
        repository_state_cid=state_b,
    )
    assert left.proof_unit_id == right.proof_unit_id
    assert left.logical_identity().logical_id() == right.logical_identity().logical_id()

    # Descriptor (context) changes while logical ID is stable.
    assert left.unit_descriptor_cid() != right.unit_descriptor_cid()
    assert left.source_root_cid != right.source_root_cid

    # with_context preserves logical ID.
    mutated = left.with_context(
        source_root_cid=source_b, repository_state_cid=state_b
    )
    assert mutated.proof_unit_id == left.proof_unit_id
    assert mutated.unit_descriptor_cid() == right.unit_descriptor_cid()

    # Full multi-granularity sample is context-stable.
    a = sample_candidates(source_root_cid=source_a, repository_state_cid=state_a)
    b = sample_candidates(source_root_cid=source_b, repository_state_cid=state_b)
    assert [c.proof_unit_id for c in a] == [c.proof_unit_id for c in b]
    # But descriptor CIDs must differ when context changes.
    assert [c.unit_descriptor_cid() for c in a] != [
        c.unit_descriptor_cid() for c in b
    ]


def test_logical_identity_excludes_status_epoch_and_proof_object() -> None:
    identity = LogicalProofUnitIdentity(
        repository_id="repo/datasets",
        proof_unit_kind=ProofUnitKind.UNIT_TEST,
        locator_kind=LocatorKind.PYTEST_NODE,
        locator_id=_cid("locator"),
    )
    payload = identity.to_canonical()
    assert payload["schema"] == LOGICAL_UNIT_IDENTITY_SCHEMA
    for forbidden in (
        "source_root_cid",
        "repository_state_cid",
        "proof_object_cid",
        "terminal_status",
        "logical_epoch",
        "status",
    ):
        assert forbidden not in payload
    assert identity.logical_id() == mint_logical_proof_unit_id(
        repository_id="repo/datasets",
        proof_unit_kind=ProofUnitKind.UNIT_TEST,
        locator_kind=LocatorKind.PYTEST_NODE,
        locator_id=_cid("locator"),
    )


# ---------------------------------------------------------------------------
# Acceptance: renamed/deleted nodes become remove/add
# ---------------------------------------------------------------------------


def test_renamed_and_deleted_nodes_become_remove_and_add() -> None:
    original = candidate_from_test(_test())
    # Rename: new node_id / locator at same kind.
    renamed_selector = _test(
        node_id="tests/test_main.py::test_entry_renamed",
        function_name="test_entry_renamed",
    )
    renamed = candidate_from_test(renamed_selector)
    assert original.proof_unit_id != renamed.proof_unit_id

    other = candidate_from_symbol(_symbol())
    previous_ids = sorted([original.proof_unit_id, other.proof_unit_id])
    current_ids = sorted([renamed.proof_unit_id, other.proof_unit_id])
    diff = diff_discovered_unit_ids(previous_ids, current_ids)
    assert original.proof_unit_id in diff.removed_unit_ids
    assert renamed.proof_unit_id in diff.added_unit_ids
    assert other.proof_unit_id in diff.retained_unit_ids
    assert classify_rename_or_delete(
        previous=original,
        current_candidates=(renamed, other),
        previous_candidates=(original, other),
    ) == "renamed"

    # Delete: unit vanishes with no same-kind replacement.
    deleted_diff = diff_discovered_unit_ids(
        previous_ids, [other.proof_unit_id]
    )
    assert original.proof_unit_id in deleted_diff.removed_unit_ids
    assert deleted_diff.added_unit_ids == ()
    assert classify_rename_or_delete(
        previous=original,
        current_candidates=(other,),
        previous_candidates=(original, other),
    ) == "deleted"

    # Full discovery path for rename.
    selector = sample_selector(selector_id="selector/rename")
    before = discover_requirements(
        repository_id="repo/datasets",
        candidates=(original, other),
        selector=selector,
    )
    after = discover_requirements(
        repository_id="repo/datasets",
        candidates=(renamed, other),
        selector=selector,
    )
    rename_diff = diff_discovered_unit_ids(
        before.required_unit_ids, after.required_unit_ids
    )
    assert original.proof_unit_id in rename_diff.removed_unit_ids
    assert renamed.proof_unit_id in rename_diff.added_unit_ids
    assert other.proof_unit_id in rename_diff.retained_unit_ids


# ---------------------------------------------------------------------------
# Acceptance: selector policy determines required units
# ---------------------------------------------------------------------------


def test_selector_policy_determines_required_units() -> None:
    candidates = sample_candidates()
    all_ids = {c.proof_unit_id for c in candidates}
    assert len(all_ids) >= 5

    selector_all = sample_selector(selector_id="selector/all")
    discovery_all = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=selector_all,
    )
    assert set(discovery_all.required_unit_ids) == all_ids
    assert discovery_all.complete is True
    assert discovery_all.selector_cid == selector_all.selector_cid()

    selector_tests = sample_selector(
        selector_id="selector/tests",
        included_kinds=sorted(
            [
                ProofUnitKind.UNIT_TEST.value,
                ProofUnitKind.INTEGRATION_TEST.value,
                ProofUnitKind.PROPERTY_TEST.value,
            ]
        ),
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    discovery_tests = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=selector_tests,
    )
    kinds = {u.proof_unit_kind for u in discovery_tests.required_units}
    assert kinds <= {
        ProofUnitKind.UNIT_TEST,
        ProofUnitKind.INTEGRATION_TEST,
        ProofUnitKind.PROPERTY_TEST,
    }
    assert ProofUnitKind.STATIC_ANALYSIS not in kinds
    assert ProofUnitKind.FORMAL_OBLIGATION not in kinds
    assert ProofUnitKind.RELEASE_INVARIANT not in kinds
    assert set(discovery_tests.required_unit_ids) < all_ids

    # Explicit exclude wins.
    victim = discovery_tests.required_unit_ids[0]
    selector_exclude = sample_selector(
        selector_id="selector/exclude",
        included_kinds=sorted(
            [
                ProofUnitKind.UNIT_TEST.value,
                ProofUnitKind.INTEGRATION_TEST.value,
                ProofUnitKind.PROPERTY_TEST.value,
            ]
        ),
        exclude_unit_ids=[victim],
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    discovery_exclude = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=selector_exclude,
    )
    assert victim not in discovery_exclude.required_unit_ids

    # Path prefix selection.
    selector_pkg = sample_selector(
        selector_id="selector/pkg",
        include_path_prefixes=["pkg"],
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    discovery_pkg = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=selector_pkg,
    )
    assert discovery_pkg.required_units
    assert all(
        u.label == "pkg/main.py" or u.label.startswith("pkg/")
        for u in discovery_pkg.required_units
    )

    # Selector CID is content-addressed and order-stable.
    again = sample_selector(
        selector_id="selector/tests",
        included_kinds=sorted(
            [
                ProofUnitKind.UNIT_TEST.value,
                ProofUnitKind.INTEGRATION_TEST.value,
                ProofUnitKind.PROPERTY_TEST.value,
            ]
        ),
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    assert again.selector_cid() == selector_tests.selector_cid()
    restored = ProofUnitSelector.from_canonical(
        json.loads(selector_tests.to_canonical_json())
    )
    assert restored == selector_tests
    assert restored.selector_cid() == selector_tests.selector_cid()


def test_parametrized_tests_are_independent_units() -> None:
    base = candidate_from_test(_test())
    param = candidate_from_test(
        _test(
            node_id="tests/test_main.py::test_entry[case-a]",
            parameter_case="case-a",
        )
    )
    assert base.proof_unit_id != param.proof_unit_id
    assert base.locator_kind == LocatorKind.PYTEST_NODE
    assert param.locator_kind == LocatorKind.PYTEST_NODE


def test_all_granularities_are_selectable() -> None:
    candidates = (
        candidate_from_symbol(_symbol(), proof_unit_kind=ProofUnitKind.TYPE_CHECK),
        candidate_from_test(
            _test(node_id="tests/test_int.py::test_flow", module_path="tests/test_int.py"),
            proof_unit_kind=ProofUnitKind.INTEGRATION_TEST,
        ),
        candidate_from_test(
            _test(
                node_id="tests/test_prop.py::test_prop",
                module_path="tests/test_prop.py",
                function_name="test_prop",
            ),
            proof_unit_kind=ProofUnitKind.PROPERTY_TEST,
        ),
        candidate_from_property(_property()),
        candidate_for_direct_computation(
            repository_id="repo/datasets",
            program_profile_id="circuit/profile-v1",
        ),
        candidate_for_release_invariant(
            repository_id="repo/datasets",
            invariant_id="release/inv-1",
        ),
        candidate_for_receipt_aggregate(
            repository_id="repo/datasets",
            aggregate_id="aggregate/r-1",
        ),
    )
    discovery = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=sample_selector(selector_id="selector/granularity"),
    )
    kinds = {u.proof_unit_kind for u in discovery.required_units}
    assert ProofUnitKind.TYPE_CHECK in kinds
    assert ProofUnitKind.INTEGRATION_TEST in kinds
    assert ProofUnitKind.PROPERTY_TEST in kinds
    assert ProofUnitKind.FORMAL_OBLIGATION in kinds
    assert ProofUnitKind.DIRECT_ZK_COMPUTATION in kinds
    assert ProofUnitKind.RELEASE_INVARIANT in kinds
    assert ProofUnitKind.RECEIPT_AGGREGATION in kinds


# ---------------------------------------------------------------------------
# Acceptance: unknown frontiers cannot narrow requirements
# ---------------------------------------------------------------------------


def test_unknown_frontiers_cannot_narrow_requirements() -> None:
    candidates = sample_candidates()
    selector_all = sample_selector(selector_id="selector/all")
    full = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=selector_all,
    )
    assert full.complete is True

    narrow = sample_selector(
        selector_id="selector/static-only",
        included_kinds=[ProofUnitKind.STATIC_ANALYSIS.value],
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    # Complete frontier: narrow selector may drop units.
    complete_frontier = DiscoveryFrontier(
        frontier_id="frontier/import-complete",
        kind=FrontierKind.IMPORT,
        complete=True,
        scope_path="pkg",
    )
    complete_narrow = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=narrow,
        frontiers=(complete_frontier,),
        previous_required_unit_ids=full.required_unit_ids,
    )
    assert complete_narrow.complete is True
    assert set(complete_narrow.required_unit_ids) < set(full.required_unit_ids)
    assert all(
        u.proof_unit_kind == ProofUnitKind.STATIC_ANALYSIS
        for u in complete_narrow.required_units
    )

    # Incomplete frontier: must retain every previous unit still in catalog.
    incomplete = DiscoveryFrontier(
        frontier_id="frontier/import-truncated",
        kind=FrontierKind.IMPORT,
        complete=False,
        scope_path="pkg",
        reason="truncated import graph",
    )
    incomplete_result = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=narrow,
        frontiers=(incomplete,),
        previous_required_unit_ids=full.required_unit_ids,
    )
    assert incomplete_result.complete is False
    assert set(full.required_unit_ids) <= set(incomplete_result.required_unit_ids)
    assert_unknown_frontiers_do_not_narrow(
        previous_required_unit_ids=full.required_unit_ids,
        current=incomplete_result,
        catalog_unit_ids=[c.proof_unit_id for c in candidates],
    )

    # Reporting complete=true with an incomplete frontier fails closed.
    with pytest.raises(DiscoveryError, match="cannot report complete=true"):
        RequirementDiscoveryResult(
            repository_id="repo/datasets",
            selector_cid=narrow.selector_cid(),
            required_units=incomplete_result.required_units,
            frontiers=(incomplete,),
            complete=True,
        )

    # Coverage frontier likewise broadens.
    coverage = DiscoveryFrontier(
        frontier_id="frontier/coverage",
        kind=FrontierKind.COVERAGE,
        complete=False,
        reason="coverage map unavailable",
    )
    coverage_result = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=narrow,
        frontiers=(coverage,),
        previous_required_unit_ids=full.required_unit_ids,
    )
    assert coverage_result.complete is False
    assert set(full.required_unit_ids) <= set(coverage_result.required_unit_ids)

    # True delete still removes even under incomplete frontier (not in catalog).
    remaining = tuple(
        c
        for c in candidates
        if c.proof_unit_kind != ProofUnitKind.UNIT_TEST
    )
    deleted_ids = [
        c.proof_unit_id
        for c in candidates
        if c.proof_unit_kind == ProofUnitKind.UNIT_TEST
    ]
    after_delete = discover_requirements(
        repository_id="repo/datasets",
        candidates=remaining,
        selector=selector_all,
        frontiers=(incomplete,),
        previous_required_unit_ids=full.required_unit_ids,
    )
    for unit_id in deleted_ids:
        assert unit_id not in after_delete.required_unit_ids
    # Still-catalogued previous units must remain.
    remaining_ids = {c.proof_unit_id for c in remaining}
    assert remaining_ids <= set(after_delete.required_unit_ids)


def test_assert_unknown_frontiers_detects_illegal_narrowing() -> None:
    candidates = sample_candidates()
    full_ids = [c.proof_unit_id for c in candidates]
    narrow_only = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=sample_selector(
            selector_id="selector/static",
            included_kinds=[ProofUnitKind.STATIC_ANALYSIS.value],
            include_release_invariants=False,
            include_receipt_aggregates=False,
        ),
        # No previous_required_unit_ids: intentionally narrows.
    )
    # Fabricate an incomplete result that dropped catalogued units.
    incomplete_frontier = DiscoveryFrontier(
        frontier_id="frontier/x",
        kind=FrontierKind.SYMBOL_RESOLUTION,
        complete=False,
    )
    illegal = RequirementDiscoveryResult(
        repository_id="repo/datasets",
        selector_cid=_cid("selector"),
        required_units=narrow_only.required_units,
        frontiers=(incomplete_frontier,),
        complete=False,
    )
    with pytest.raises(DiscoveryError, match="cannot narrow requirements"):
        assert_unknown_frontiers_do_not_narrow(
            previous_required_unit_ids=full_ids,
            current=illegal,
            catalog_unit_ids=full_ids,
        )


# ---------------------------------------------------------------------------
# Graph and manifest builders
# ---------------------------------------------------------------------------


def test_build_proof_dependency_graph_is_order_invariant() -> None:
    candidates = sample_candidates()
    discovery = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=sample_selector(selector_id="selector/graph"),
    )
    units = list(discovery.required_units)
    assert len(units) >= 3
    edges = [
        DiscoveryDependencyEdge(
            from_id=units[0].proof_unit_id,
            to_id=units[1].proof_unit_id,
            edge_type=DependencyEdgeType.PROOF_DEPENDS_ON,
            reason_label="u0-u1",
        ),
        DiscoveryDependencyEdge(
            from_id=units[1].proof_unit_id,
            to_id=units[2].proof_unit_id,
            edge_type=DependencyEdgeType.AGGREGATE_CONTAINS,
            reason_label="u1-u2",
        ),
    ]
    forward = build_proof_dependency_graph(units=units, edges=edges)
    reverse = build_proof_dependency_graph(
        units=list(reversed(units)), edges=list(reversed(edges))
    )
    assert forward.graph_cid() == reverse.graph_cid()
    assert forward.node_count() >= len(units)
    assert forward.get_node(units[0].proof_unit_id).kind == DependencyNodeKind.UNIT


def test_build_manifest_from_discovery() -> None:
    discovery = sample_discovery_result()
    policy = sample_verification_policy()
    manifest = build_manifest_from_discovery(
        discovery=discovery,
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        repository_state_cid=_cid("state"),
        source_root_cid=_cid("source"),
        policy=policy,
        environment_cid=_cid("env"),
        dependency_lock_cid=_cid("lock"),
        configuration_cid=_cid("config"),
        logical_epoch=3,
    )
    assert list(manifest.required_unit_ids) == list(discovery.required_unit_ids)
    assert manifest.test_selector_cid == discovery.selector_cid
    assert all(unit.required_for_seal for unit in manifest.required_units)
    assert manifest.logical_epoch == 3
    # Selected units must be present.
    manifest.assert_selected_units_required(discovery.required_unit_ids)


def test_discovery_result_round_trip_and_determinism() -> None:
    first = sample_discovery_result()
    second = sample_discovery_result()
    assert first.result_cid() == second.result_cid()
    assert first.to_canonical_json() == second.to_canonical_json()
    restored = RequirementDiscoveryResult.from_canonical(
        json.loads(first.to_canonical_json())
    )
    assert restored.required_unit_ids == first.required_unit_ids
    assert restored.selector_cid == first.selector_cid
    assert restored.complete is first.complete


def test_candidate_round_trip() -> None:
    candidate = candidate_from_property(_property())
    restored = DiscoveredCandidate.from_canonical(
        json.loads(candidate.to_canonical_json())
    )
    assert restored.proof_unit_id == candidate.proof_unit_id
    assert restored.to_canonical() == candidate.to_canonical()


def test_known_vectors_are_deterministic() -> None:
    first = known_vectors()
    second = known_vectors()
    assert first == second
    assert first["discovery_subset"] == DISCOVERY_SUBSET
    assert first["logical_ids_survive_context_change"] is True
    assert first["logical_ids_context_a"] == first["logical_ids_context_b"]
    assert first["rename_classification"] == "renamed"
    assert first["rename_diff"]["removed_unit_ids"]
    assert first["rename_diff"]["added_unit_ids"]
    assert first["incomplete_frontier"]["complete"] is False
    # Incomplete frontier retained the full previous required set.
    assert set(first["selector_all"]["required_unit_ids"]) <= set(
        first["incomplete_frontier"]["required_unit_ids"]
    )
    assert first["selector_tests"]["required_kinds"] == ["unit_test"]
    assert first["manifest_root"]
    assert first["graph_cid"]


def test_fail_closed_on_bad_inputs() -> None:
    with pytest.raises(DiscoveryError, match="selection_source"):
        DiscoveredCandidate(
            repository_id="repo/datasets",
            proof_unit_kind=ProofUnitKind.UNIT_TEST,
            locator_kind=LocatorKind.PYTEST_NODE,
            locator_id=_cid("loc"),
            selection_source="not_a_source",
        )
    with pytest.raises(DiscoveryError, match="symbol candidates admit only"):
        candidate_from_symbol(_symbol(), proof_unit_kind=ProofUnitKind.UNIT_TEST)
    with pytest.raises(DiscoveryError, match="test candidates admit only"):
        candidate_from_test(_test(), proof_unit_kind=ProofUnitKind.STATIC_ANALYSIS)
    with pytest.raises(DiscoveryError, match="must be a ProofUnitSelector"):
        discover_requirements(
            repository_id="repo/datasets",
            candidates=sample_candidates(),
            selector="not-a-selector",  # type: ignore[arg-type]
        )
    with pytest.raises(DiscoveryError, match="does not match"):
        discover_requirements(
            repository_id="repo/other",
            candidates=sample_candidates(),
            selector=sample_selector(),
        )
    # Unsorted required units in result fail closed.
    unit = candidate_from_test(_test())
    other = candidate_from_symbol(_symbol())
    unordered = tuple(
        sorted([unit, other], key=lambda item: item.proof_unit_id, reverse=True)
    )
    with pytest.raises(DiscoveryError, match="canonically sorted"):
        RequirementDiscoveryResult(
            repository_id="repo/datasets",
            selector_cid=_cid("sel"),
            required_units=unordered,
            frontiers=(),
            complete=True,
        )
