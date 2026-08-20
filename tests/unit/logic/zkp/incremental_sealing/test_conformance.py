"""IPS-017 public invalidation API freeze and conformance matrix."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing import (
    CONFORMANCE_SUBSET,
    PUBLIC_API_SUBSET,
    build_proof_dependency_graph,
    build_repository_state,
    build_verification_requirement_manifest,
    compute_invalidation_closure,
    compute_proof_cache_key,
    diff_repository_states,
    explain_invalidation,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.cache_key import (
    sample_proof_cache_key,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.dependency_graph import (
    DependencyNodeKind,
    sample_dependency_graph,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.discovery import (
    sample_candidates,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    ABSENCE_TOKEN,
    canonical_cid,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.invalidation import (
    FULL_FALLBACK_CHANGE_CLASSES,
    PRESERVE_CHANGE_CLASSES,
    UNIT_DISPOSITION_KINDS,
    classify_full_fallback,
    known_vectors as invalidation_vectors,
    sample_invalidation_policy,
    sample_path_to_node_ids,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.repository_diff import (
    ChangeClass,
    sample_artifact,
    sample_classification_policy,
    sample_repository_state,
)


_PUBLIC_FREEZE = (
    "build_repository_state",
    "build_verification_requirement_manifest",
    "build_proof_dependency_graph",
    "compute_proof_cache_key",
    "diff_repository_states",
    "compute_invalidation_closure",
    "explain_invalidation",
)


def _cid(label: str) -> str:
    return canonical_cid({"ips_conformance": label, "v": 1})


def test_conformance_subset_and_public_freeze() -> None:
    assert CONFORMANCE_SUBSET == "ips/datasets-conformance@1"
    assert PUBLIC_API_SUBSET == "ips/datasets-public-api@1"
    package = importlib.import_module(
        "ipfs_datasets_py.logic.zkp.incremental_sealing"
    )
    for name in _PUBLIC_FREEZE:
        assert hasattr(package, name)
        assert callable(getattr(package, name))
    assert package.compute_proof_cache_key is compute_proof_cache_key
    assert package.build_repository_state is build_repository_state


def test_cold_public_api_import_is_hermetic() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "assert 'multiformats' not in sys.modules; "
                "mod = importlib.import_module("
                "'ipfs_datasets_py.logic.zkp.incremental_sealing'"
                "); "
                "assert mod.CONFORMANCE_SUBSET == 'ips/datasets-conformance@1'; "
                "assert 'multiformats' not in sys.modules; "
                "assert 'ipfs_datasets_py.logic.software_contracts.content' "
                "not in sys.modules; "
                "assert 'provekit' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_byte_identical_states_share_identities_and_cache_keys() -> None:
    left = build_repository_state(
        repository_id="repo/datasets",
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_cid=_cid("tree"),
    )
    right = build_repository_state(
        repository_id="repo/datasets",
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_cid=_cid("tree"),
    )
    assert left.identity_cid() == right.identity_cid()
    first = sample_proof_cache_key()
    second = compute_proof_cache_key(payload=first.to_canonical())
    assert first.key_cid() == second.key_cid()


def test_relevant_source_root_mutation_changes_cache_key() -> None:
    base = sample_proof_cache_key()
    mutated = sample_proof_cache_key(source_root_cid=_cid("other-source-root"))
    assert base.key_cid() != mutated.key_cid()
    assert base.source_root_cid != mutated.source_root_cid


def test_unrelated_documentation_permits_reuse() -> None:
    old = sample_repository_state(tree_label="tree-docs-a")
    new = sample_repository_state(
        tree_label="tree-docs-b",
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    old_artifacts = (sample_artifact("docs/guide.md", label="docs-v1"),)
    new_artifacts = (sample_artifact("docs/guide.md", label="docs-v2"),)
    diff = diff_repository_states(
        old,
        new,
        old_artifacts=old_artifacts,
        new_artifacts=new_artifacts,
        policy=sample_classification_policy(),
    )
    classes = {item.change_class.value for item in diff.changed_artifacts}
    assert classes <= PRESERVE_CHANGE_CLASSES | {ChangeClass.ORDINARY_DOCUMENTATION.value}
    graph = sample_dependency_graph()
    known = (
        "unit/static",
        "unit/test",
        "unit/formal",
        "unit/unrelated",
        "aggregate/receipt",
        "aggregate/unrelated",
    )
    closure = compute_invalidation_closure(
        graph,
        changed_node_ids=(),
        known_unit_ids=known,
        policy=sample_invalidation_policy(),
        repository_diff=diff,
        path_to_node_ids=sample_path_to_node_ids(),
    )
    preserved = {
        item.unit_id
        for item in closure.dispositions
        if item.kind.value == "preserve"
    }
    assert "unit/unrelated" in preserved
    assert "unit/formal" in preserved


def test_source_implementation_invalidates_dependents_not_unrelated() -> None:
    graph = sample_dependency_graph()
    known = (
        "unit/static",
        "unit/test",
        "unit/formal",
        "unit/unrelated",
        "aggregate/receipt",
        "aggregate/unrelated",
    )
    first = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
        policy=sample_invalidation_policy(),
    )
    second = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
        policy=sample_invalidation_policy(),
    )
    assert first.closure_cid() == second.closure_cid()
    invalidated = {
        item.unit_id
        for item in first.dispositions
        if item.kind.value == "invalidate"
    }
    preserved = {
        item.unit_id
        for item in first.dispositions
        if item.kind.value == "preserve"
    }
    assert "unit/formal" in invalidated or "unit/static" in invalidated
    assert "unit/unrelated" in preserved
    explanation = explain_invalidation(graph, "unit/formal", first)
    replay = explain_invalidation(graph, "unit/formal", first)
    assert explanation.to_canonical() == replay.to_canonical()
    assert explanation.invalidated is True


def test_full_fallback_classes_never_narrow_reuse() -> None:
    for change_class in sorted(FULL_FALLBACK_CHANGE_CLASSES):
        decision = classify_full_fallback(
            policy=sample_invalidation_policy(),
            change_classes=(change_class,),
        )
        assert decision.required is True, change_class


def test_added_and_deleted_tests_are_explicit_dispositions() -> None:
    assert "prove_new" in UNIT_DISPOSITION_KINDS
    assert "remove_requires_authorization" in UNIT_DISPOSITION_KINDS
    assert "remove_authorized" in UNIT_DISPOSITION_KINDS
    vectors = invalidation_vectors()
    kinds = set(vectors["closed_disposition_kinds"])
    assert "invalidate" in kinds
    assert "preserve" in kinds
    assert "prove_new" in kinds
    assert vectors["source_invalidated"]
    assert "unit/unrelated" in vectors["source_preserved"]


def test_manifest_and_graph_builders_are_deterministic() -> None:
    candidates = sample_candidates()
    first = build_proof_dependency_graph(units=candidates)
    second = build_proof_dependency_graph(units=tuple(reversed(candidates)))
    assert first.graph_cid() == second.graph_cid()
    assert first.has_node(candidates[0].proof_unit_id)
    assert first.get_node(candidates[0].proof_unit_id).kind is DependencyNodeKind.UNIT
    from ipfs_datasets_py.logic.zkp.incremental_sealing.manifest import (
        sample_verification_requirement_manifest,
    )

    left = sample_verification_requirement_manifest()
    right = sample_verification_requirement_manifest()
    assert left.manifest_cid() == right.manifest_cid()
    rebuilt = build_verification_requirement_manifest(
        repository_id=left.repository_id,
        revision=left.revision,
        repository_state_cid=left.repository_state_cid,
        source_root_cid=left.source_root_cid,
        required_units=left.required_units,
        policy=left.policy_cid,
        test_selector_cid=left.test_selector_cid,
        environment_cid=left.environment_cid,
        dependency_lock_cid=left.dependency_lock_cid,
        configuration_cid=left.configuration_cid,
        network_policy_cid=left.network_policy_cid,
        proof_schema_version=left.proof_schema_version,
        canonicalization_version=left.canonicalization_version,
        dependency_graph_schema_version=left.dependency_graph_schema_version,
        permitted_removals=left.permitted_removals,
        logical_epoch=left.logical_epoch,
    )
    assert rebuilt.manifest_cid() == left.manifest_cid()


def test_diff_between_identical_inventories_is_empty() -> None:
    state = sample_repository_state()
    artifacts = (sample_artifact("pkg/main.py", label="main-v1"),)
    diff = diff_repository_states(
        state,
        state,
        old_artifacts=artifacts,
        new_artifacts=artifacts,
    )
    assert tuple(diff.changed_artifacts) == ()
    assert diff.old_repository_state_cid == state.identity_cid()
    assert diff.new_repository_state_cid == state.identity_cid()
