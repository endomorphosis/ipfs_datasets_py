"""Regression tests for invalidation closure, full-fallback, and explanations (IPS-016)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.dependency_graph import (
    DependencyEdgeType,
    DependencyNodeKind,
    ProofDependencyGraph,
    mint_reason_cid,
    sample_dependency_graph,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    ABSENCE_TOKEN,
    canonical_cid,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.invalidation import (
    BROAD_INVALIDATION_CHANGE_CLASSES,
    CHANGE_CLASS_KEY_FIELDS,
    FULL_FALLBACK_CHANGE_CLASSES,
    FULL_FALLBACK_REASONS,
    INVALIDATION_SUBSET,
    INVALIDATION_TRIGGERS,
    LOCAL_INVALIDATION_CHANGE_CLASSES,
    PRESERVE_CHANGE_CLASSES,
    UNIT_DISPOSITION_KINDS,
    FullFallbackDecision,
    FullFallbackReason,
    InvalidationClosure,
    InvalidationError,
    InvalidationPolicy,
    InvalidationTrigger,
    ProofInvalidationExplanation,
    UnitDisposition,
    UnitDispositionKind,
    classify_full_fallback,
    closed_full_fallback_reasons,
    closed_invalidation_triggers,
    closed_unit_disposition_kinds,
    compute_invalidation_closure,
    explain_invalidation,
    known_vectors,
    parse_full_fallback_reason,
    parse_invalidation_trigger,
    parse_unit_disposition_kind,
    resolve_seed_nodes,
    sample_invalidation_closure,
    sample_invalidation_policy,
    sample_path_to_node_ids,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.repository_diff import (
    ChangeAction,
    ChangeClass,
    ChangedArtifact,
    diff_repository_states,
    sample_artifact,
    sample_classification_policy,
    sample_repository_state,
)


def _cid(label: str) -> str:
    return canonical_cid({"ips_invalidation_test": label, "v": 1})


def _reason(label: str) -> str:
    return mint_reason_cid({"test_reason": label, "v": 1})


def _known_units() -> tuple[str, ...]:
    return (
        "aggregate/receipt",
        "aggregate/unrelated",
        "unit/formal",
        "unit/static",
        "unit/test",
        "unit/unrelated",
    )


def _changed(
    path: str,
    change_class: ChangeClass,
    *,
    action: ChangeAction = ChangeAction.MODIFIED,
) -> ChangedArtifact:
    if action is ChangeAction.ADDED:
        return ChangedArtifact(
            path=path,
            change_action=ChangeAction.ADDED,
            change_class=change_class,
            old_content_cid=ABSENCE_TOKEN,
            new_content_cid=_cid(f"{path}:new"),
            old_byte_length=ABSENCE_TOKEN,
            new_byte_length=4,
        )
    if action is ChangeAction.DELETED:
        return ChangedArtifact(
            path=path,
            change_action=ChangeAction.DELETED,
            change_class=change_class,
            old_content_cid=_cid(f"{path}:old"),
            new_content_cid=ABSENCE_TOKEN,
            old_byte_length=4,
            new_byte_length=ABSENCE_TOKEN,
        )
    return ChangedArtifact(
        path=path,
        change_action=ChangeAction.MODIFIED,
        change_class=change_class,
        old_content_cid=_cid(f"{path}:old"),
        new_content_cid=_cid(f"{path}:new"),
        old_byte_length=4,
        new_byte_length=5,
    )


# ---------------------------------------------------------------------------
# Closed surface
# ---------------------------------------------------------------------------


def test_subset_and_closed_sets() -> None:
    assert INVALIDATION_SUBSET == "ips/invalidation-engine@1"
    assert closed_unit_disposition_kinds() == frozenset(UNIT_DISPOSITION_KINDS)
    assert closed_full_fallback_reasons() == frozenset(FULL_FALLBACK_REASONS)
    assert closed_invalidation_triggers() == frozenset(INVALIDATION_TRIGGERS)
    assert len(UnitDispositionKind) == len(UNIT_DISPOSITION_KINDS)
    assert len(FullFallbackReason) == len(FULL_FALLBACK_REASONS)
    assert len(InvalidationTrigger) == len(INVALIDATION_TRIGGERS)
    for name in UNIT_DISPOSITION_KINDS:
        assert parse_unit_disposition_kind(name).value == name
    for name in FULL_FALLBACK_REASONS:
        assert parse_full_fallback_reason(name).value == name
    for name in INVALIDATION_TRIGGERS:
        assert parse_invalidation_trigger(name).value == name
    with pytest.raises(InvalidationError, match="unknown UnitDispositionKind"):
        parse_unit_disposition_kind("maybe")
    with pytest.raises(InvalidationError, match="unknown FullFallbackReason"):
        parse_full_fallback_reason("maybe")
    with pytest.raises(InvalidationError, match="unknown InvalidationTrigger"):
        parse_invalidation_trigger("maybe")


def test_preserve_local_and_fallback_class_sets() -> None:
    assert PRESERVE_CHANGE_CLASSES == frozenset({"ordinary_documentation"})
    assert LOCAL_INVALIDATION_CHANGE_CLASSES <= frozenset(
        c.value for c in ChangeClass
    )
    assert FULL_FALLBACK_CHANGE_CLASSES <= frozenset(c.value for c in ChangeClass)
    assert BROAD_INVALIDATION_CHANGE_CLASSES <= frozenset(
        c.value for c in ChangeClass
    )
    assert "ordinary_documentation" not in FULL_FALLBACK_CHANGE_CLASSES
    assert "ordinary_documentation" not in BROAD_INVALIDATION_CHANGE_CLASSES
    # Every non-docs change class has at least one key-field binding for
    # explanations (unknown is the fail-closed broad set).
    for change_class in ChangeClass:
        assert change_class.value in CHANGE_CLASS_KEY_FIELDS


# ---------------------------------------------------------------------------
# Seed resolution
# ---------------------------------------------------------------------------


def test_resolve_seed_nodes_maps_paths_and_skips_docs() -> None:
    graph = sample_dependency_graph()
    path_map = sample_path_to_node_ids()
    seeds, classes, unmapped, triggers = resolve_seed_nodes(
        graph,
        changed_artifacts=(
            _changed("pkg/mod.py", ChangeClass.SOURCE_IMPLEMENTATION),
            _changed("docs/guide.md", ChangeClass.ORDINARY_DOCUMENTATION),
        ),
        path_to_node_ids=path_map,
    )
    assert seeds == ("artifact/mod.py",)
    assert "source_implementation" in classes
    assert "ordinary_documentation" in classes
    assert unmapped is False
    assert "ordinary_documentation" in triggers
    assert "source_implementation" in triggers


def test_unmapped_relevant_change_is_flagged() -> None:
    graph = sample_dependency_graph()
    seeds, classes, unmapped, _triggers = resolve_seed_nodes(
        graph,
        changed_artifacts=(
            _changed("pkg/never_seen.py", ChangeClass.SOURCE_IMPLEMENTATION),
        ),
        path_to_node_ids={},
    )
    assert seeds == ()
    assert classes == ("source_implementation",)
    assert unmapped is True


# ---------------------------------------------------------------------------
# Acceptance: relevant changes invalidate correctly
# ---------------------------------------------------------------------------


def test_source_implementation_invalidates_bound_chain_only() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    result = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
    )
    assert "unit/static" in result.invalidated_unit_ids
    assert "unit/test" in result.invalidated_unit_ids
    assert "unit/formal" in result.invalidated_unit_ids
    assert "aggregate/receipt" in result.invalidated_unit_ids
    assert "aggregate/receipt" in result.affected_aggregate_ids
    # Unrelated island is preserved.
    assert "unit/unrelated" in result.preserved_unit_ids
    assert "aggregate/unrelated" in result.preserved_unit_ids
    assert "unit/unrelated" not in result.invalidated_unit_ids
    assert result.full_fallback.required is False
    assert result.docs_only is False
    assert result.complete is True


def test_source_interface_and_fixture_and_config_invalidate() -> None:
    graph = sample_dependency_graph()
    known = _known_units()

    schema = compute_invalidation_closure(
        graph,
        changed_node_ids=("schema/api",),
        known_unit_ids=known,
    )
    assert "unit/static" in schema.invalidated_unit_ids
    assert "unit/formal" in schema.invalidated_unit_ids
    assert "aggregate/receipt" in schema.invalidated_unit_ids
    assert "unit/unrelated" in schema.preserved_unit_ids

    fixture = compute_invalidation_closure(
        graph,
        changed_node_ids=("fixture/data",),
        known_unit_ids=known,
    )
    assert "unit/test" in fixture.invalidated_unit_ids
    assert "unit/formal" in fixture.invalidated_unit_ids
    assert "aggregate/receipt" in fixture.invalidated_unit_ids
    assert "unit/static" not in fixture.invalidated_unit_ids
    assert "unit/unrelated" in fixture.preserved_unit_ids

    config = compute_invalidation_closure(
        graph,
        changed_node_ids=("config/env",),
        known_unit_ids=known,
    )
    assert "unit/test" in config.invalidated_unit_ids
    assert "aggregate/receipt" in config.invalidated_unit_ids
    assert "unit/unrelated" in config.preserved_unit_ids


def test_changed_artifacts_via_path_map_drive_invalidation() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    result = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            _changed("pkg/mod.py", ChangeClass.SOURCE_IMPLEMENTATION),
        ),
        path_to_node_ids=sample_path_to_node_ids(),
        known_unit_ids=known,
    )
    assert "unit/formal" in result.invalidated_unit_ids
    assert "source_implementation" in result.change_classes
    assert result.seed_node_ids == ("artifact/mod.py",)


def test_lock_policy_environment_circuit_key_classes() -> None:
    # Circuit / keys / environment force full fallback under default policy.
    for change_class, reason in (
        (ChangeClass.CIRCUIT, "circuit_changed"),
        (ChangeClass.PROVING_KEY, "proving_key_changed"),
        (ChangeClass.VERIFICATION_KEY, "verification_key_changed"),
        (ChangeClass.ENVIRONMENT, "environment_changed"),
        (ChangeClass.CANONICALIZATION, "canonicalization_changed"),
        (ChangeClass.UNKNOWN, "unknown_change_class"),
    ):
        decision = classify_full_fallback(
            change_classes=(change_class.value,),
            policy=sample_invalidation_policy(),
        )
        assert decision.required is True, change_class
        assert reason in decision.reasons, change_class

    # Dependency lock alone does not force full fallback unless policy says so.
    lock_default = classify_full_fallback(
        change_classes=(ChangeClass.DEPENDENCY_LOCK.value,),
        policy=sample_invalidation_policy(),
    )
    assert lock_default.required is False
    assert lock_default.broadens_invalidation is True

    lock_forced = classify_full_fallback(
        change_classes=(ChangeClass.DEPENDENCY_LOCK.value,),
        policy=sample_invalidation_policy(
            treat_dependency_lock_as_full_fallback=True
        ),
    )
    assert lock_forced.required is True
    assert "dependency_lock_policy" in lock_forced.reasons

    # Policy / network / selector / interface / checked-spec broaden.
    for change_class in (
        ChangeClass.POLICY,
        ChangeClass.NETWORK_POLICY,
        ChangeClass.TEST_SELECTOR,
        ChangeClass.SOURCE_INTERFACE,
        ChangeClass.CHECKED_SPECIFICATION,
        ChangeClass.GENERATED_INPUT,
    ):
        decision = classify_full_fallback(
            change_classes=(change_class.value,),
            policy=sample_invalidation_policy(),
        )
        assert decision.required is False, change_class
        assert decision.broadens_invalidation is True, change_class


# ---------------------------------------------------------------------------
# Acceptance: docs / unrelated edits preserve valid units
# ---------------------------------------------------------------------------


def test_ordinary_documentation_preserves_all_known_units() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    result = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            _changed("docs/guide.md", ChangeClass.ORDINARY_DOCUMENTATION),
        ),
        known_unit_ids=known,
        path_to_node_ids=sample_path_to_node_ids(),
    )
    assert result.docs_only is True
    assert result.invalidated_unit_ids == ()
    assert set(result.preserved_unit_ids) == set(known)
    assert result.full_fallback.required is False
    assert result.seed_node_ids == ()
    assert "ordinary_documentation" in result.change_classes

    for unit_id in ("unit/formal", "unit/unrelated", "aggregate/receipt"):
        explanation = explain_invalidation(graph, unit_id, result)
        assert explanation.invalidated is False
        assert explanation.disposition is UnitDispositionKind.PRESERVE
        assert "ordinary documentation" in explanation.summary


def test_unrelated_module_edit_preserves_unrelated_island() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    # Edit only the unrelated unit island.
    result = compute_invalidation_closure(
        graph,
        changed_node_ids=("unit/unrelated",),
        known_unit_ids=known,
    )
    assert "unit/unrelated" in result.invalidated_unit_ids
    assert "aggregate/unrelated" in result.invalidated_unit_ids
    assert "unit/formal" in result.preserved_unit_ids
    assert "unit/static" in result.preserved_unit_ids
    assert "unit/test" in result.preserved_unit_ids
    assert "aggregate/receipt" in result.preserved_unit_ids


# ---------------------------------------------------------------------------
# Acceptance: add/delete rules are explicit
# ---------------------------------------------------------------------------


def test_added_selected_test_is_prove_new() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    result = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            _changed(
                "tests/test_new.py",
                ChangeClass.TEST_SOURCE,
                action=ChangeAction.ADDED,
            ),
        ),
        known_unit_ids=known,
        added_unit_ids=("unit/new-test",),
        path_to_node_ids={},
    )
    assert "unit/new-test" in result.added_unit_ids
    assert result.disposition_for("unit/new-test").kind is UnitDispositionKind.PROVE_NEW
    assert "test_added" in result.triggers
    # Unmapped new test source broadens/falls back; either way the add is explicit.
    explanation = explain_invalidation(graph, "unit/new-test", result)
    assert explanation.disposition is UnitDispositionKind.PROVE_NEW
    assert "must be proven" in explanation.summary


def test_deleted_test_requires_authorization() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    unauthorized = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            _changed(
                "tests/test_main.py",
                ChangeClass.TEST_SOURCE,
                action=ChangeAction.DELETED,
            ),
        ),
        known_unit_ids=known,
        removed_unit_ids=("unit/test",),
        authorized_removal_unit_ids=(),
        path_to_node_ids={"tests/test_main.py": ("unit/test",)},
    )
    assert "unit/test" in unauthorized.removed_unit_ids
    assert "unit/test" in unauthorized.unauthorized_removal_unit_ids
    assert (
        unauthorized.disposition_for("unit/test").kind
        is UnitDispositionKind.REMOVE_REQUIRES_AUTHORIZATION
    )
    assert unauthorized.complete is False

    authorized = compute_invalidation_closure(
        graph,
        removed_unit_ids=("unit/test",),
        authorized_removal_unit_ids=("unit/test",),
        known_unit_ids=known,
    )
    assert authorized.unauthorized_removal_unit_ids == ()
    assert (
        authorized.disposition_for("unit/test").kind
        is UnitDispositionKind.REMOVE_AUTHORIZED
    )
    explanation = explain_invalidation(graph, "unit/test", unauthorized)
    assert "requires current-policy authorization" in explanation.summary


def test_authorized_removals_must_be_subset_of_removed() -> None:
    graph = sample_dependency_graph()
    with pytest.raises(InvalidationError, match="subset of removed_unit_ids"):
        compute_invalidation_closure(
            graph,
            removed_unit_ids=("unit/test",),
            authorized_removal_unit_ids=("unit/formal",),
        )


# ---------------------------------------------------------------------------
# Full-fallback classification
# ---------------------------------------------------------------------------


def test_classify_full_fallback_policy_triggers() -> None:
    genesis = classify_full_fallback(
        policy=sample_invalidation_policy(is_genesis=True)
    )
    assert genesis.required is True
    assert "genesis" in genesis.reasons

    cache = classify_full_fallback(
        policy=sample_invalidation_policy(uncertain_cache_integrity=True)
    )
    assert "uncertain_cache_integrity" in cache.reasons

    release = classify_full_fallback(
        policy=sample_invalidation_policy(release_qualification=True)
    )
    assert "release_qualification" in release.reasons

    explicit = classify_full_fallback(
        policy=sample_invalidation_policy(force_full_fallback=True)
    )
    assert "explicit_policy" in explicit.reasons

    schema = classify_full_fallback(
        policy=sample_invalidation_policy(
            dependency_graph_schema_changed=True,
            proof_schema_changed=True,
            canonicalization_changed=True,
        )
    )
    assert {
        "dependency_graph_schema_changed",
        "proof_schema_changed",
        "canonicalization_changed",
    } <= set(schema.reasons)

    # Admitted schema migration suppresses schema/canon triggers only.
    migrated = classify_full_fallback(
        change_classes=(ChangeClass.CANONICALIZATION.value,),
        policy=sample_invalidation_policy(
            canonicalization_changed=True,
            admit_schema_migration_proof=True,
        ),
    )
    assert migrated.required is False

    # Admitted key migration suppresses circuit/key class triggers.
    key_migrated = classify_full_fallback(
        change_classes=(ChangeClass.CIRCUIT.value, ChangeClass.PROVING_KEY.value),
        policy=sample_invalidation_policy(admit_key_migration_proof=True),
    )
    assert key_migrated.required is False

    truncated = classify_full_fallback(
        closure_complete=False,
        policy=sample_invalidation_policy(),
    )
    assert "truncated_closure" in truncated.reasons

    unmapped = classify_full_fallback(
        unmapped_relevant_changes=True,
        policy=sample_invalidation_policy(),
    )
    assert "unmapped_relevant_change" in unmapped.reasons

    depth = classify_full_fallback(
        policy=sample_invalidation_policy(
            max_delta_chain_depth=3,
            current_delta_chain_depth=3,
        )
    )
    assert "excessive_delta_chain_depth" in depth.reasons

    ratio = classify_full_fallback(
        policy=sample_invalidation_policy(
            min_reuse_ratio_bps=5000,
            estimated_reuse_ratio_bps=1000,
        )
    )
    assert "low_reuse_ratio" in ratio.reasons

    unjustified = classify_full_fallback(incremental_reuse_justified=False)
    assert "incremental_reuse_unjustified" in unjustified.reasons


def test_classify_full_fallback_from_repository_diff() -> None:
    policy = sample_classification_policy()
    old_state = sample_repository_state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-old",
    )
    new_state = sample_repository_state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="tree-new",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    # Circuit change in the inventory forces full fallback on the diff.
    circuit_diff = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("circuits/prove.circom", label="c1"),),
        new_artifacts=(sample_artifact("circuits/prove.circom", label="c2"),),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert circuit_diff.full_fallback_required is True
    decision = classify_full_fallback(
        repository_diff=circuit_diff,
        policy=sample_invalidation_policy(),
    )
    assert decision.required is True
    assert "circuit_changed" in decision.reasons

    # Ordinary docs alone do not force full fallback.
    docs_diff = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("docs/guide.md", label="d1"),),
        new_artifacts=(sample_artifact("docs/guide.md", label="d2"),),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    docs_decision = classify_full_fallback(
        repository_diff=docs_diff,
        policy=sample_invalidation_policy(),
    )
    assert docs_decision.required is False


def test_full_fallback_invalidates_all_known_units() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    result = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            _changed("circuits/prove.circom", ChangeClass.CIRCUIT),
        ),
        known_unit_ids=known,
        path_to_node_ids={},
        policy=sample_invalidation_policy(),
    )
    assert result.full_fallback.required is True
    # Every known unit is invalidated under full fallback (no silent reuse).
    assert set(result.invalidated_unit_ids) == set(known)
    assert result.preserved_unit_ids == ()
    assert "full_fallback" in result.triggers


def test_truncated_graph_forces_full_fallback() -> None:
    graph = sample_dependency_graph()
    graph.mark_truncated("artifact/mod.py")
    known = _known_units()
    result = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
        policy=sample_invalidation_policy(truncated_forces_full_fallback=True),
    )
    assert result.full_fallback.required is True
    assert "truncated_closure" in result.full_fallback.reasons
    assert "truncated_frontier" in result.triggers
    assert set(result.invalidated_unit_ids) == set(known)


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------


def test_explain_invalidation_reports_paths_fields_and_aggregates() -> None:
    graph = sample_dependency_graph()
    known = _known_units()
    closure = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
    )
    explanation = explain_invalidation(graph, "unit/formal", closure)
    assert explanation.invalidated is True
    assert explanation.disposition is UnitDispositionKind.INVALIDATE
    assert explanation.seed_node_ids == ("artifact/mod.py",)
    assert explanation.paths  # at least one path artifact -> formal
    assert explanation.paths[0].edge_from_ids[0] == "artifact/mod.py"
    assert explanation.paths[0].edge_to_ids[-1] == "unit/formal"
    # Seed-only change still may have empty change_classes; ensure summary is
    # substantive and never "file unchanged".
    assert "file unchanged" not in explanation.summary.lower()
    assert "invalidated" in explanation.summary
    assert "aggregate/receipt" in explanation.affected_aggregate_ids

    # When change classes are present, key fields are bound.
    with_classes = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            _changed("pkg/mod.py", ChangeClass.SOURCE_IMPLEMENTATION),
        ),
        path_to_node_ids=sample_path_to_node_ids(),
        known_unit_ids=known,
    )
    explained = explain_invalidation(graph, "unit/formal", with_classes)
    field_names = {item.field_name for item in explained.changed_key_fields}
    assert "source_root_cid" in field_names
    assert "source_artifact_cids" in field_names

    # Preserved unit explanation.
    preserved = explain_invalidation(graph, "unit/unrelated", with_classes)
    assert preserved.invalidated is False
    assert preserved.disposition is UnitDispositionKind.PRESERVE
    assert "outside forward invalidation" in preserved.summary


def test_explanation_and_closure_round_trip_are_deterministic() -> None:
    first = sample_invalidation_closure()
    second = sample_invalidation_closure()
    assert first.closure_cid() == second.closure_cid()
    assert first.to_canonical_json() == second.to_canonical_json()

    restored = InvalidationClosure.from_canonical(first.to_canonical())
    assert restored.closure_cid() == first.closure_cid()
    assert restored.invalidated_unit_ids == first.invalidated_unit_ids

    graph = sample_dependency_graph()
    explanation = explain_invalidation(graph, "unit/formal", first)
    again = explain_invalidation(graph, "unit/formal", first)
    assert explanation.explanation_cid() == again.explanation_cid()
    restored_expl = ProofInvalidationExplanation.from_canonical(
        explanation.to_canonical()
    )
    assert restored_expl.explanation_cid() == explanation.explanation_cid()


def test_policy_and_decision_round_trip() -> None:
    policy = sample_invalidation_policy(
        treat_dependency_lock_as_full_fallback=True,
        max_delta_chain_depth=10,
        current_delta_chain_depth=2,
        min_reuse_ratio_bps=2500,
        estimated_reuse_ratio_bps=8000,
    )
    restored = InvalidationPolicy.from_canonical(policy.to_canonical())
    assert restored.policy_cid() == policy.policy_cid()

    decision = classify_full_fallback(
        change_classes=(ChangeClass.ENVIRONMENT.value,),
        policy=policy,
    )
    restored_decision = FullFallbackDecision.from_canonical(decision.to_canonical())
    assert restored_decision.decision_cid() == decision.decision_cid()
    assert restored_decision.required is True


def test_disposition_partition_rejects_overlap() -> None:
    decision = classify_full_fallback(policy=sample_invalidation_policy())
    with pytest.raises(InvalidationError, match="both invalidated and preserved"):
        InvalidationClosure(
            invalidated_unit_ids=("unit/a",),
            preserved_unit_ids=("unit/a",),
            added_unit_ids=(),
            removed_unit_ids=(),
            unauthorized_removal_unit_ids=(),
            affected_aggregate_ids=(),
            seed_node_ids=(),
            closure_node_ids=(),
            change_classes=(),
            triggers=(),
            dispositions=(
                UnitDisposition(
                    unit_id="unit/a",
                    kind=UnitDispositionKind.INVALIDATE,
                    triggers=("seed_node",),
                    seed_node_ids=(),
                ),
            ),
            full_fallback=decision,
            complete=True,
            docs_only=False,
        )


# ---------------------------------------------------------------------------
# Insertion-order independence and known vectors
# ---------------------------------------------------------------------------


def test_insertion_order_cannot_affect_closure_cid() -> None:
    graph_a = sample_dependency_graph()
    graph_b = ProofDependencyGraph()
    for node in reversed(graph_a.nodes()):
        graph_b.add_node(
            node.node_id, node.kind, label=node.label, truncated=node.truncated
        )
    for edge in reversed(graph_a.edges()):
        graph_b.add_edge(edge.from_id, edge.to_id, edge.edge_type, edge.reason_cid)

    known = _known_units()
    left = compute_invalidation_closure(
        graph_a, changed_node_ids=("artifact/mod.py",), known_unit_ids=known
    )
    right = compute_invalidation_closure(
        graph_b, changed_node_ids=("artifact/mod.py",), known_unit_ids=known
    )
    assert left.closure_cid() == right.closure_cid()
    assert left.invalidated_unit_ids == right.invalidated_unit_ids
    assert left.preserved_unit_ids == right.preserved_unit_ids


def test_known_vectors_are_deterministic() -> None:
    first = known_vectors()
    second = known_vectors()
    assert first == second
    assert first["subset"] == INVALIDATION_SUBSET
    assert "unit/formal" in first["source_invalidated"]
    assert "unit/unrelated" in first["source_preserved"]
    assert first["docs_only"] is True
    assert first["docs_invalidated"] == []
    assert first["circuit_full_fallback"] is True
    assert "circuit_changed" in first["circuit_reasons"]
    assert first["formal_invalidated"] is True
    assert first["source_closure_cid"] == canonical_cid(
        sample_invalidation_closure().to_canonical()
    )


def test_multi_edge_custom_graph_invalidation() -> None:
    """Custom graph covering lock -> unit and interface-style broadening seed."""

    graph = ProofDependencyGraph()
    graph.add_node("lock/poetry", DependencyNodeKind.CONFIG, label="poetry.lock")
    graph.add_node("iface/api", DependencyNodeKind.SYMBOL, label="pkg/api.py")
    graph.add_node("unit/a", DependencyNodeKind.UNIT, label="a")
    graph.add_node("unit/b", DependencyNodeKind.UNIT, label="b")
    graph.add_node("agg", DependencyNodeKind.AGGREGATE, label="agg")
    graph.add_edge(
        "lock/poetry", "unit/a", DependencyEdgeType.CONFIG_DEPENDS_ON, _reason("lock-a")
    )
    graph.add_edge(
        "iface/api", "unit/b", DependencyEdgeType.SOURCE_DEPENDS_ON, _reason("iface-b")
    )
    graph.add_edge(
        "unit/a", "agg", DependencyEdgeType.AGGREGATE_CONTAINS, _reason("a-agg")
    )
    graph.add_edge(
        "unit/b", "agg", DependencyEdgeType.AGGREGATE_CONTAINS, _reason("b-agg")
    )

    known = ("agg", "unit/a", "unit/b")
    lock_result = compute_invalidation_closure(
        graph,
        changed_node_ids=("lock/poetry",),
        known_unit_ids=known,
    )
    assert set(lock_result.invalidated_unit_ids) == {"unit/a", "agg"}
    assert "unit/b" in lock_result.preserved_unit_ids

    iface_result = compute_invalidation_closure(
        graph,
        changed_node_ids=("iface/api",),
        known_unit_ids=known,
    )
    assert set(iface_result.invalidated_unit_ids) == {"unit/b", "agg"}
    assert "unit/a" in iface_result.preserved_unit_ids
