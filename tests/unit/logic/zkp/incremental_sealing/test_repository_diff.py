"""Regression tests for complete repository diff and change classification (IPS-015)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    ABSENCE_TOKEN,
    RepositoryState,
    canonical_cid,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.repository_diff import (
    ARTIFACT_LAYERS,
    BROAD_INVALIDATION_CHANGE_CLASSES,
    CHANGE_ACTIONS,
    CHANGE_CLASSES,
    DIFF_ALGORITHM,
    DIFF_ALGORITHM_VERSION,
    FULL_FALLBACK_CHANGE_CLASSES,
    REPOSITORY_DIFF_SUBSET,
    ArtifactLayer,
    ArtifactSnapshot,
    ChangeAction,
    ChangeClass,
    ChangedArtifact,
    PathClassificationPolicy,
    RepositoryDiff,
    RepositoryDiffError,
    classify_path,
    closed_artifact_layers,
    closed_change_actions,
    closed_change_classes,
    commit_changed_artifacts,
    diff_artifact_inventories,
    diff_repository_states,
    known_vectors,
    parse_artifact_layer,
    parse_change_action,
    parse_change_class,
    sample_artifact,
    sample_changed_artifacts,
    sample_classification_policy,
    sample_repository_diff,
    sample_repository_state,
)


def _cid(label: str) -> str:
    return canonical_cid({"ips_repository_diff_test": label, "v": 1})


def _state(
    *,
    revision: str = "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    tree_label: str = "tree",
    dirty_overlay_cid: str = ABSENCE_TOKEN,
    parent_revision_ids: tuple[str, ...] = (),
    repository_id: str = "repo/datasets",
) -> RepositoryState:
    return sample_repository_state(
        repository_id=repository_id,
        revision=revision,
        tree_label=tree_label,
        dirty_overlay_cid=dirty_overlay_cid,
        parent_revision_ids=parent_revision_ids,
    )


# ---------------------------------------------------------------------------
# Closed surface
# ---------------------------------------------------------------------------


def test_subset_and_closed_sets() -> None:
    assert REPOSITORY_DIFF_SUBSET == "ips/repository-diff@1"
    assert DIFF_ALGORITHM_VERSION == "1"
    assert DIFF_ALGORITHM.endswith("/algorithm@1")
    assert closed_change_classes() == frozenset(CHANGE_CLASSES)
    assert closed_change_actions() == frozenset(CHANGE_ACTIONS)
    assert closed_artifact_layers() == frozenset(ARTIFACT_LAYERS)
    assert len(CHANGE_CLASSES) == 18
    assert len(ChangeClass) == 18
    for name in CHANGE_CLASSES:
        assert parse_change_class(name).value == name
    for name in CHANGE_ACTIONS:
        assert parse_change_action(name).value == name
    for name in ARTIFACT_LAYERS:
        assert parse_artifact_layer(name).value == name
    with pytest.raises(RepositoryDiffError, match="unknown ChangeClass"):
        parse_change_class("maybe_source")
    with pytest.raises(RepositoryDiffError, match="unknown ChangeAction"):
        parse_change_action("renamed")
    with pytest.raises(RepositoryDiffError, match="unknown ArtifactLayer"):
        parse_artifact_layer("index")


def test_full_fallback_and_broad_class_sets_are_closed_subsets() -> None:
    assert FULL_FALLBACK_CHANGE_CLASSES <= closed_change_classes()
    assert BROAD_INVALIDATION_CHANGE_CLASSES <= closed_change_classes()
    assert "unknown" in FULL_FALLBACK_CHANGE_CLASSES
    assert "circuit" in FULL_FALLBACK_CHANGE_CLASSES
    assert "ordinary_documentation" not in FULL_FALLBACK_CHANGE_CLASSES
    assert "ordinary_documentation" not in BROAD_INVALIDATION_CHANGE_CLASSES


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------


def test_classify_path_covers_normative_axes() -> None:
    policy = sample_classification_policy()
    cases = {
        "pkg/main.py": ChangeClass.SOURCE_IMPLEMENTATION,
        "pkg/api.py": ChangeClass.SOURCE_INTERFACE,
        "tests/test_main.py": ChangeClass.TEST_SOURCE,
        "tests/fixtures/data.json": ChangeClass.FIXTURE,
        "poetry.lock": ChangeClass.DEPENDENCY_LOCK,
        "config/app.toml": ChangeClass.CONFIGURATION,
        "circuits/prove.circom": ChangeClass.CIRCUIT,
        "keys/pk_main.pkey": ChangeClass.PROVING_KEY,
        "keys/vk_main.vkey": ChangeClass.VERIFICATION_KEY,
        "selectors/unit.json": ChangeClass.TEST_SELECTOR,
        "policy/verification_policy.json": ChangeClass.POLICY,
        "policy/network_policy.json": ChangeClass.NETWORK_POLICY,
        "meta/canonicalization.json": ChangeClass.CANONICALIZATION,
        "environment/trust_policy.json": ChangeClass.ENVIRONMENT,
        "docs/guide.md": ChangeClass.ORDINARY_DOCUMENTATION,
        "docs/checked/soundness.md": ChangeClass.CHECKED_SPECIFICATION,
        "generated/inputs/case-a.json": ChangeClass.GENERATED_INPUT,
        "blob.bin": ChangeClass.UNKNOWN,
    }
    for path, expected in cases.items():
        assert classify_path(path, policy) is expected, path


def test_ordinary_docs_distinct_from_checked_specs_and_generated_inputs() -> None:
    policy = sample_classification_policy()
    ordinary = classify_path("docs/architecture/overview.md", policy)
    checked = classify_path("docs/checked/soundness.md", policy)
    generated = classify_path("generated/inputs/case-a.json", policy)
    heuristic_checked = classify_path("specs/checked_spec/invariant.md", policy)
    heuristic_generated = classify_path("build/generated/out.json", policy)

    assert ordinary is ChangeClass.ORDINARY_DOCUMENTATION
    assert checked is ChangeClass.CHECKED_SPECIFICATION
    assert generated is ChangeClass.GENERATED_INPUT
    assert heuristic_checked is ChangeClass.CHECKED_SPECIFICATION
    assert heuristic_generated is ChangeClass.GENERATED_INPUT
    assert ordinary != checked
    assert ordinary != generated
    assert checked != generated


def test_class_overrides_win_over_heuristics() -> None:
    policy = PathClassificationPolicy(
        class_overrides=(("docs/guide.md", "checked_specification"),),
    )
    assert classify_path("docs/guide.md", policy) is ChangeClass.CHECKED_SPECIFICATION
    # Without override, ordinary docs remain ordinary.
    assert (
        classify_path("docs/guide.md", PathClassificationPolicy())
        is ChangeClass.ORDINARY_DOCUMENTATION
    )


# ---------------------------------------------------------------------------
# Acceptance: changed-artifact commitment is complete/deterministic
# ---------------------------------------------------------------------------


def test_changed_artifact_commitment_is_complete_and_deterministic() -> None:
    policy = sample_classification_policy()
    changes = sample_changed_artifacts(policy)
    assert changes
    # Commitment is order-invariant and deterministic across recomputation.
    left = commit_changed_artifacts(changes)
    right = commit_changed_artifacts(tuple(reversed(changes)))
    again = commit_changed_artifacts(changes)
    assert left == right == again

    # Commitment changes when any artifact content changes.
    mutated = list(changes)
    victim = mutated[0]
    if victim.change_action is ChangeAction.DELETED:
        mutated[0] = ChangedArtifact(
            path=victim.path,
            change_action=ChangeAction.DELETED,
            change_class=victim.change_class,
            old_content_cid=_cid("mutated-old"),
            new_content_cid=ABSENCE_TOKEN,
            old_byte_length=3,
            new_byte_length=ABSENCE_TOKEN,
            layer=victim.layer,
            from_dirty_overlay=victim.from_dirty_overlay,
        )
    elif victim.change_action is ChangeAction.ADDED:
        mutated[0] = ChangedArtifact(
            path=victim.path,
            change_action=ChangeAction.ADDED,
            change_class=victim.change_class,
            old_content_cid=ABSENCE_TOKEN,
            new_content_cid=_cid("mutated-new"),
            old_byte_length=ABSENCE_TOKEN,
            new_byte_length=5,
            layer=victim.layer,
            from_dirty_overlay=victim.from_dirty_overlay,
        )
    else:
        mutated[0] = ChangedArtifact(
            path=victim.path,
            change_action=ChangeAction.MODIFIED,
            change_class=victim.change_class,
            old_content_cid=victim.old_content_cid,
            new_content_cid=_cid("mutated-content"),
            old_byte_length=victim.old_byte_length,
            new_byte_length=victim.new_byte_length,
            layer=victim.layer,
            from_dirty_overlay=victim.from_dirty_overlay,
        )
    assert commit_changed_artifacts(tuple(mutated)) != left

    # Duplicate path/layer/action fails closed.
    with pytest.raises(RepositoryDiffError, match="duplicate changed artifact"):
        commit_changed_artifacts((changes[0], changes[0]))


def test_diff_inventory_add_modify_delete_are_explicit() -> None:
    old = (
        sample_artifact("pkg/main.py", label="main-v1"),
        sample_artifact("tests/test_old.py", label="old-test"),
        sample_artifact("docs/guide.md", label="docs-v1"),
    )
    new = (
        sample_artifact("pkg/main.py", label="main-v2"),
        sample_artifact("tests/test_new.py", label="new-test"),
        sample_artifact("docs/guide.md", label="docs-v1"),
    )
    changes = diff_artifact_inventories(old, new)
    by_path = {item.path: item for item in changes}
    assert set(by_path) == {"pkg/main.py", "tests/test_old.py", "tests/test_new.py"}
    assert by_path["pkg/main.py"].change_action is ChangeAction.MODIFIED
    assert by_path["tests/test_old.py"].change_action is ChangeAction.DELETED
    assert by_path["tests/test_new.py"].change_action is ChangeAction.ADDED
    assert by_path["pkg/main.py"].change_class is ChangeClass.SOURCE_IMPLEMENTATION
    assert by_path["tests/test_old.py"].change_class is ChangeClass.TEST_SOURCE
    assert by_path["tests/test_new.py"].change_class is ChangeClass.TEST_SOURCE
    # Unchanged docs path is absent from the changed set.
    assert "docs/guide.md" not in by_path


def test_diff_repository_states_binds_algorithm_and_commitment() -> None:
    old_state = _state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-old",
    )
    new_state = _state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="tree-new",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    old_artifacts = (
        sample_artifact("pkg/main.py", label="main-v1"),
        sample_artifact("docs/guide.md", label="docs-v1"),
    )
    new_artifacts = (
        sample_artifact("pkg/main.py", label="main-v2"),
        sample_artifact("docs/guide.md", label="docs-v2"),
    )
    result = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=old_artifacts,
        new_artifacts=new_artifacts,
        policy=sample_classification_policy(),
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert result.diff_algorithm == DIFF_ALGORITHM
    assert result.diff_algorithm_version == DIFF_ALGORITHM_VERSION
    assert result.changed_artifact_commitment == commit_changed_artifacts(
        result.changed_artifacts
    )
    assert result.complete is True
    assert result.ambiguous is False
    assert result.full_fallback_required is False
    assert result.has_class(ChangeClass.SOURCE_IMPLEMENTATION)
    assert result.has_class(ChangeClass.ORDINARY_DOCUMENTATION)
    assert set(result.change_classes_present) == {
        "source_implementation",
        "ordinary_documentation",
    }
    # Deterministic identity.
    again = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=old_artifacts,
        new_artifacts=new_artifacts,
        policy=sample_classification_policy(),
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert again.identity_cid() == result.identity_cid()
    assert again.to_canonical_json() == result.to_canonical_json()


def test_multi_class_sample_covers_required_classifications() -> None:
    changes = sample_changed_artifacts()
    present = {item.change_class.value for item in changes}
    required = {
        "source_implementation",
        "source_interface",
        "test_source",
        "fixture",
        "dependency_lock",
        "configuration",
        "circuit",
        "proving_key",
        "verification_key",
        "test_selector",
        "policy",
        "network_policy",
        "canonicalization",
        "environment",
        "ordinary_documentation",
        "checked_specification",
        "generated_input",
    }
    assert required <= present
    actions = {item.change_action for item in changes}
    assert ChangeAction.ADDED in actions
    assert ChangeAction.MODIFIED in actions
    assert ChangeAction.DELETED in actions


# ---------------------------------------------------------------------------
# Acceptance: merges and dirty overlays are explicit
# ---------------------------------------------------------------------------


def test_merge_parents_are_bound_and_unresolved_forces_full_fallback() -> None:
    parent_a = "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    parent_b = "rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    old_state = _state(revision=parent_a, tree_label="tree-a")
    new_state = _state(
        revision="rev-cccccccccccccccccccccccccccccccccccccccc",
        tree_label="tree-merge",
        parent_revision_ids=tuple(sorted((parent_a, parent_b))),
    )
    artifacts_old = (sample_artifact("pkg/main.py", label="a"),)
    artifacts_new = (sample_artifact("pkg/main.py", label="c"),)

    resolved = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=artifacts_old,
        new_artifacts=artifacts_new,
        inventory_complete=True,
        selected_parent_revision=parent_a,
        merge_resolved=True,
    )
    assert resolved.is_merge is True
    assert resolved.parent_revision_ids == tuple(sorted((parent_a, parent_b)))
    assert resolved.selected_parent_revision == parent_a
    assert resolved.merge_resolved is True
    assert resolved.complete is True
    assert resolved.full_fallback_required is False

    unresolved = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=artifacts_old,
        new_artifacts=artifacts_new,
        inventory_complete=True,
        selected_parent_revision=parent_a,
        merge_resolved=False,
    )
    assert unresolved.is_merge is True
    assert unresolved.merge_resolved is False
    assert unresolved.ambiguous is True
    assert unresolved.complete is False
    assert unresolved.full_fallback_required is True

    # Default merge_resolved for merges is false (requires explicit True).
    default_merge = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=artifacts_old,
        new_artifacts=artifacts_new,
        inventory_complete=True,
        selected_parent_revision=parent_a,
    )
    assert default_merge.merge_resolved is False
    assert default_merge.full_fallback_required is True


def test_dirty_overlay_is_explicit_and_never_folded_into_tree() -> None:
    dirty_cid = _cid("dirty-overlay")
    clean = _state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-shared",
        dirty_overlay_cid=ABSENCE_TOKEN,
    )
    dirty = _state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-shared",
        dirty_overlay_cid=dirty_cid,
    )
    old_artifacts = (
        sample_artifact("pkg/main.py", label="clean", layer=ArtifactLayer.TREE),
    )
    new_artifacts = (
        sample_artifact("pkg/main.py", label="clean", layer=ArtifactLayer.TREE),
        sample_artifact(
            "pkg/main.py", label="dirty", layer=ArtifactLayer.DIRTY_OVERLAY
        ),
    )
    result = diff_repository_states(
        clean,
        dirty,
        old_artifacts=old_artifacts,
        new_artifacts=new_artifacts,
        inventory_complete=True,
        selected_parent_revision=clean.revision,
        merge_resolved=True,
    )
    assert result.dirty_overlay_present is True
    assert result.dirty_overlay_changed is True
    assert result.old_dirty_overlay_cid == ABSENCE_TOKEN
    assert result.new_dirty_overlay_cid == dirty_cid
    assert len(result.changed_artifacts) == 1
    change = result.changed_artifacts[0]
    assert change.path == "pkg/main.py"
    assert change.layer is ArtifactLayer.DIRTY_OVERLAY
    assert change.from_dirty_overlay is True
    assert change.change_action is ChangeAction.ADDED

    # Tree-layer and dirty-overlay layer for the same path are distinct keys.
    both_old = (
        sample_artifact("pkg/main.py", label="tree-v1", layer=ArtifactLayer.TREE),
        sample_artifact(
            "pkg/main.py", label="dirty-v1", layer=ArtifactLayer.DIRTY_OVERLAY
        ),
    )
    both_new = (
        sample_artifact("pkg/main.py", label="tree-v2", layer=ArtifactLayer.TREE),
        sample_artifact(
            "pkg/main.py", label="dirty-v2", layer=ArtifactLayer.DIRTY_OVERLAY
        ),
    )
    layered = diff_artifact_inventories(both_old, both_new)
    assert len(layered) == 2
    assert {item.layer for item in layered} == {
        ArtifactLayer.TREE,
        ArtifactLayer.DIRTY_OVERLAY,
    }


# ---------------------------------------------------------------------------
# Acceptance: ordinary docs distinct; unknown/incomplete force fallback
# ---------------------------------------------------------------------------


def test_ordinary_docs_do_not_force_full_fallback() -> None:
    old_state = _state(tree_label="t1")
    new_state = _state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="t2",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    result = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("docs/guide.md", label="d1"),),
        new_artifacts=(sample_artifact("docs/guide.md", label="d2"),),
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert result.change_classes_present == ("ordinary_documentation",)
    assert result.full_fallback_required is False
    assert result.requires_broad_invalidation is False
    assert result.complete is True


def test_checked_specification_broadens_without_being_ordinary_docs() -> None:
    policy = sample_classification_policy()
    old_state = _state(tree_label="t1")
    new_state = _state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="t2",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    result = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(
            sample_artifact("docs/checked/soundness.md", label="c1"),
            sample_artifact("docs/guide.md", label="g1"),
        ),
        new_artifacts=(
            sample_artifact("docs/checked/soundness.md", label="c2"),
            sample_artifact("docs/guide.md", label="g1"),
        ),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert result.change_classes_present == ("checked_specification",)
    assert result.has_class(ChangeClass.CHECKED_SPECIFICATION)
    assert not result.has_class(ChangeClass.ORDINARY_DOCUMENTATION)
    assert result.requires_broad_invalidation is True
    assert result.full_fallback_required is False


def test_unknown_and_incomplete_inventory_force_full_fallback() -> None:
    old_state = _state(tree_label="t1")
    new_state = _state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="t2",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    unknown = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("blob.bin", label="b1"),),
        new_artifacts=(sample_artifact("blob.bin", label="b2"),),
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert unknown.has_class(ChangeClass.UNKNOWN)
    assert unknown.ambiguous is True
    assert unknown.complete is False
    assert unknown.full_fallback_required is True

    incomplete = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("pkg/main.py", label="m1"),),
        new_artifacts=(sample_artifact("pkg/main.py", label="m2"),),
        inventory_complete=False,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert incomplete.inventory_complete is False
    assert incomplete.ambiguous is True
    assert incomplete.complete is False
    assert incomplete.full_fallback_required is True


def test_circuit_and_key_changes_force_full_fallback() -> None:
    old_state = _state(tree_label="t1")
    new_state = _state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="t2",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    for path, label in (
        ("circuits/prove.circom", "circuit"),
        ("keys/pk_main.pkey", "pk"),
        ("keys/vk_main.vkey", "vk"),
        ("meta/canonicalization.json", "canon"),
        ("environment/trust_policy.json", "env"),
    ):
        result = diff_repository_states(
            old_state,
            new_state,
            old_artifacts=(sample_artifact(path, label=f"{label}-1"),),
            new_artifacts=(sample_artifact(path, label=f"{label}-2"),),
            inventory_complete=True,
            selected_parent_revision=old_state.revision,
            merge_resolved=True,
        )
        assert result.full_fallback_required is True, path


# ---------------------------------------------------------------------------
# Fail-closed records and round-trip
# ---------------------------------------------------------------------------


def test_changed_artifact_rejects_invalid_add_delete_shapes() -> None:
    with pytest.raises(RepositoryDiffError, match="typed absence for old_content_cid"):
        ChangedArtifact(
            path="pkg/main.py",
            change_action=ChangeAction.ADDED,
            change_class=ChangeClass.SOURCE_IMPLEMENTATION,
            old_content_cid=_cid("not-absent"),
            new_content_cid=_cid("new"),
            old_byte_length=ABSENCE_TOKEN,
            new_byte_length=1,
        )
    with pytest.raises(RepositoryDiffError, match="typed absence for new_content_cid"):
        ChangedArtifact(
            path="pkg/main.py",
            change_action=ChangeAction.DELETED,
            change_class=ChangeClass.SOURCE_IMPLEMENTATION,
            old_content_cid=_cid("old"),
            new_content_cid=_cid("not-absent"),
            old_byte_length=1,
            new_byte_length=ABSENCE_TOKEN,
        )
    with pytest.raises(RepositoryDiffError, match="distinct old/new content"):
        ChangedArtifact(
            path="pkg/main.py",
            change_action=ChangeAction.MODIFIED,
            change_class=ChangeClass.SOURCE_IMPLEMENTATION,
            old_content_cid=_cid("same"),
            new_content_cid=_cid("same"),
            old_byte_length=1,
            new_byte_length=1,
        )
    with pytest.raises(RepositoryDiffError, match="from_dirty_overlay must match"):
        ChangedArtifact(
            path="pkg/main.py",
            change_action=ChangeAction.ADDED,
            change_class=ChangeClass.SOURCE_IMPLEMENTATION,
            old_content_cid=ABSENCE_TOKEN,
            new_content_cid=_cid("new"),
            old_byte_length=ABSENCE_TOKEN,
            new_byte_length=1,
            layer=ArtifactLayer.TREE,
            from_dirty_overlay=True,
        )


def test_duplicate_inventory_paths_fail_closed() -> None:
    dup = (
        sample_artifact("pkg/main.py", label="a"),
        sample_artifact("pkg/main.py", label="b"),
    )
    with pytest.raises(RepositoryDiffError, match="duplicate path/layer"):
        diff_artifact_inventories(dup, ())


def test_repository_diff_round_trip_and_commitment_mismatch() -> None:
    sample = sample_repository_diff()
    restored = RepositoryDiff.from_canonical(json.loads(sample.to_canonical_json()))
    assert restored == sample
    assert restored.identity_cid() == sample.identity_cid()
    assert restored.changed_artifact_commitment == sample.changed_artifact_commitment

    payload = sample.to_canonical()
    payload["changed_artifact_commitment"] = _cid("wrong-commitment")
    with pytest.raises(RepositoryDiffError, match="changed_artifact_commitment"):
        RepositoryDiff.from_canonical(payload)


def test_policy_cid_is_content_addressed() -> None:
    left = sample_classification_policy(interface_paths=("pkg/api.py",))
    right = sample_classification_policy(interface_paths=("pkg/api.py",))
    other = sample_classification_policy(interface_paths=("pkg/other.py",))
    assert left.policy_cid() == right.policy_cid()
    assert left.policy_cid() != other.policy_cid()
    restored = PathClassificationPolicy.from_canonical(left.to_canonical())
    assert restored.policy_cid() == left.policy_cid()


def test_artifact_snapshot_round_trip() -> None:
    snap = ArtifactSnapshot(
        path="pkg/main.py",
        content_cid=_cid("content"),
        byte_length=12,
        layer=ArtifactLayer.DIRTY_OVERLAY,
    )
    restored = ArtifactSnapshot.from_canonical(snap.to_canonical())
    assert restored == snap


def test_known_vectors_are_deterministic() -> None:
    first = known_vectors()
    second = known_vectors()
    assert first == second
    assert first["diff_subset"] == REPOSITORY_DIFF_SUBSET
    assert first["commitment_order_invariant"] is True
    docs = first["documentation_distinction"]
    assert docs["docs/guide.md"] == "ordinary_documentation"
    assert docs["docs/checked/soundness.md"] == "checked_specification"
    assert docs["generated/inputs/case-a.json"] == "generated_input"
    assert first["dirty_overlay_diff"]["dirty_overlay_present"] is True
    assert first["dirty_overlay_diff"]["from_dirty_overlay_paths"] == ["pkg/main.py"]
    assert first["merge_resolved"]["is_merge"] is True
    assert first["merge_resolved"]["full_fallback_required"] is False
    assert first["merge_unresolved"]["full_fallback_required"] is True
    assert first["unknown_forces_fallback"]["full_fallback_required"] is True
    required_classes = {
        "source_implementation",
        "source_interface",
        "test_source",
        "fixture",
        "dependency_lock",
        "ordinary_documentation",
        "checked_specification",
        "generated_input",
    }
    assert required_classes <= set(first["multi_class_change_classes"])


def test_mismatched_repository_ids_force_full_fallback() -> None:
    old_state = _state(repository_id="repo/a", tree_label="t1")
    new_state = _state(
        repository_id="repo/b",
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="t2",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    result = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("pkg/main.py", label="m1"),),
        new_artifacts=(sample_artifact("pkg/main.py", label="m2"),),
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert result.repository_id == "repo/b"
    assert result.ambiguous is True
    assert result.full_fallback_required is True


def test_dependency_lock_policy_can_require_full_fallback() -> None:
    policy = sample_classification_policy(
        treat_dependency_lock_as_full_fallback=True
    )
    old_state = _state(tree_label="t1")
    new_state = _state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="t2",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    result = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=(sample_artifact("poetry.lock", label="l1"),),
        new_artifacts=(sample_artifact("poetry.lock", label="l2"),),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    assert result.has_class(ChangeClass.DEPENDENCY_LOCK)
    assert result.full_fallback_required is True
    assert result.requires_broad_invalidation is True
