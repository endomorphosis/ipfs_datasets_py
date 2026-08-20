"""Regression tests for deterministic proof-forest commitment codec (IPS-011)."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.forest_codec import (
    DOMAIN_BINARY,
    DOMAIN_CATEGORY,
    DOMAIN_EMPTY,
    DOMAIN_LEAF,
    DOMAIN_REPOSITORY,
    DOMAIN_UNARY,
    FOREST_CATEGORIES,
    FOREST_CODEC_SUBSET,
    FOREST_CODEC_VECTORS_SUBSET,
    GENESIS_PARENT_SEAL,
    CategoryRoot,
    ForestCodecError,
    ProofForestLeaf,
    RepositoryProofRoot,
    category_root_field_name,
    closed_forest_categories,
    compute_category_root,
    compute_repository_root,
    encode_binary_node,
    encode_empty_node,
    encode_leaf_node,
    encode_unary_node,
    known_vectors,
    parse_forest_category,
    render_forest_vectors_json,
    sample_category_leaves,
    sample_leaf,
    sample_repository_proof_root,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import canonical_cid

FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "incremental_proof_sealer"
    / "forest_vectors.json"
)


def _cid(label: str) -> str:
    return canonical_cid({"ips_forest_test": label, "v": 1})


# ---------------------------------------------------------------------------
# Closed surface
# ---------------------------------------------------------------------------


def test_forest_codec_subset_and_closed_categories() -> None:
    assert FOREST_CODEC_SUBSET == "ips/forest-codec@1"
    assert FOREST_CODEC_VECTORS_SUBSET == "ips/forest-codec-vectors@1"
    assert closed_forest_categories() == frozenset(FOREST_CATEGORIES)
    assert list(FOREST_CATEGORIES) == [
        "source_integrity",
        "static_analysis",
        "type_check",
        "unit_test",
        "integration_test",
        "property_test",
        "formal_obligation",
        "direct_zk",
        "receipt_aggregation",
        "release_invariant",
    ]
    assert parse_forest_category("direct_zk_computation") == "direct_zk"
    assert category_root_field_name("unit_test") == "unit_test_root"
    with pytest.raises(ForestCodecError, match="unknown forest category"):
        parse_forest_category("mystery_category")


def test_domain_separators_are_distinct() -> None:
    domains = {
        DOMAIN_EMPTY,
        DOMAIN_LEAF,
        DOMAIN_UNARY,
        DOMAIN_BINARY,
        DOMAIN_CATEGORY,
        DOMAIN_REPOSITORY,
    }
    assert len(domains) == 6
    empty_a = encode_empty_node(category="unit_test")
    empty_b = encode_empty_node(category="static_analysis")
    assert empty_a != empty_b
    leaf = encode_leaf_node(
        category="unit_test",
        proof_unit_id="unit/a",
        proof_object_cid=_cid("proof-a"),
        position=0,
    )
    unary = encode_unary_node(child_cid=leaf)
    binary = encode_binary_node(left_cid=leaf, right_cid=empty_a)
    assert len({empty_a, leaf, unary, binary}) == 4


# ---------------------------------------------------------------------------
# Determinism and category roots
# ---------------------------------------------------------------------------


def test_repeated_runs_match() -> None:
    leaves = sample_category_leaves("unit_test")
    first = compute_category_root("unit_test", leaves)
    second = compute_category_root("unit_test", leaves)
    assert first.root_cid == second.root_cid
    assert first.merkle_root == second.merkle_root
    assert first.to_canonical_json() == second.to_canonical_json()

    repo_a = sample_repository_proof_root()
    repo_b = sample_repository_proof_root()
    assert repo_a.root_cid == repo_b.root_cid
    assert repo_a.to_canonical_json() == repo_b.to_canonical_json()

    vectors_a = known_vectors()
    vectors_b = known_vectors()
    assert vectors_a["base"]["root_cid"] == vectors_b["base"]["root_cid"]
    assert vectors_a == vectors_b


def test_empty_unary_binary_node_shapes() -> None:
    empty = compute_category_root("property_test", ())
    assert empty.leaf_count == 0
    assert empty.merkle_root == encode_empty_node(category="property_test")
    assert empty.root_cid != empty.merkle_root

    one = (
        sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
    )
    unary = compute_category_root("unit_test", one)
    assert unary.merkle_root == one[0].leaf_cid()

    two = sample_category_leaves("unit_test")
    binary = compute_category_root("unit_test", two)
    assert binary.merkle_root == encode_binary_node(
        left_cid=two[0].leaf_cid(), right_cid=two[1].leaf_cid()
    )

    three = (
        sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
        sample_leaf(proof_unit_id="unit/b", category="unit_test", position=1),
        sample_leaf(proof_unit_id="unit/c", category="unit_test", position=2),
    )
    mixed = compute_category_root("unit_test", three)
    pair = encode_binary_node(
        left_cid=three[0].leaf_cid(), right_cid=three[1].leaf_cid()
    )
    leftover = encode_unary_node(child_cid=three[2].leaf_cid())
    assert mixed.merkle_root == encode_binary_node(left_cid=pair, right_cid=leftover)

    # Distinct shapes yield distinct roots.
    assert len({empty.root_cid, unary.root_cid, binary.root_cid, mixed.root_cid}) == 4


def test_one_bit_leaf_change_propagates() -> None:
    base_leaves = sample_category_leaves("unit_test")
    base = compute_category_root("unit_test", base_leaves)
    flipped = (
        base_leaves[0],
        sample_leaf(
            proof_unit_id="unit/b",
            category="unit_test",
            position=1,
            proof_object_cid=_cid("proof-unit-b-flipped"),
        ),
    )
    mutated = compute_category_root("unit_test", flipped)
    assert mutated.root_cid != base.root_cid
    assert mutated.merkle_root != base.merkle_root

    base_repo = sample_repository_proof_root()
    flipped_repo = sample_repository_proof_root(
        category_leaves={
            "unit_test": flipped,
            "static_analysis": (
                sample_leaf(
                    proof_unit_id="unit/static-a",
                    category="static_analysis",
                    position=0,
                ),
            ),
        }
    )
    assert flipped_repo.root_cid != base_repo.root_cid


# ---------------------------------------------------------------------------
# Fail-closed inputs
# ---------------------------------------------------------------------------


def test_duplicate_reordered_unknown_category_fail() -> None:
    with pytest.raises(ForestCodecError, match="duplicate proof_unit_id"):
        compute_category_root(
            "unit_test",
            (
                sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
                sample_leaf(proof_unit_id="unit/a", category="unit_test", position=1),
            ),
        )

    with pytest.raises(ForestCodecError, match="canonical proof-unit ID byte order"):
        compute_category_root(
            "unit_test",
            (
                sample_leaf(proof_unit_id="unit/b", category="unit_test", position=0),
                sample_leaf(proof_unit_id="unit/a", category="unit_test", position=1),
            ),
        )

    with pytest.raises(ForestCodecError, match="duplicate leaf positions"):
        compute_category_root(
            "unit_test",
            (
                sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
                sample_leaf(proof_unit_id="unit/b", category="unit_test", position=0),
            ),
        )

    with pytest.raises(ForestCodecError, match="contiguous 0..n-1"):
        compute_category_root(
            "unit_test",
            (
                sample_leaf(proof_unit_id="unit/a", category="unit_test", position=1),
                sample_leaf(proof_unit_id="unit/b", category="unit_test", position=2),
            ),
        )

    with pytest.raises(ForestCodecError, match="unknown forest category"):
        compute_category_root("mystery_category", ())

    with pytest.raises(ForestCodecError, match="unknown forest category"):
        compute_repository_root(
            repository_id="repo/datasets",
            revision="rev-1",
            source_root_cid=_cid("source"),
            manifest_root_cid=_cid("manifest"),
            environment_cid=_cid("env"),
            policy_cid=_cid("policy"),
            category_leaves={"mystery_category": ()},
        )

    with pytest.raises(ForestCodecError, match="missing category roots"):
        compute_repository_root(
            repository_id="repo/datasets",
            revision="rev-1",
            source_root_cid=_cid("source"),
            manifest_root_cid=_cid("manifest"),
            environment_cid=_cid("env"),
            policy_cid=_cid("policy"),
            category_roots={"unit_test": _cid("only-one")},
        )

    # Vectors document the same fail-closed cases.
    vectors = known_vectors()
    with pytest.raises(ForestCodecError, match="duplicate proof_unit_id"):
        compute_category_root(
            "unit_test", vectors["fail_closed"]["duplicate_unit_ids"]
        )
    with pytest.raises(ForestCodecError, match="canonical proof-unit ID byte order"):
        compute_category_root(
            "unit_test", vectors["fail_closed"]["reordered_leaves"]
        )
    with pytest.raises(ForestCodecError, match="duplicate leaf positions"):
        compute_category_root(
            "unit_test", vectors["fail_closed"]["duplicate_positions"]
        )
    with pytest.raises(ForestCodecError, match="unknown forest category"):
        parse_forest_category(vectors["fail_closed"]["unknown_category"])


# ---------------------------------------------------------------------------
# Repository root context binding
# ---------------------------------------------------------------------------


def test_parent_revision_environment_schema_affect_root() -> None:
    base = sample_repository_proof_root()
    base_root = base.root_cid

    parent_mutated = sample_repository_proof_root(
        parent_seal_cid=_cid("parent-seal-alt")
    )
    revision_mutated = sample_repository_proof_root(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    environment_mutated = sample_repository_proof_root(
        environment_cid=_cid("environment-alt")
    )
    schema_mutated = sample_repository_proof_root(proof_schema_version="2")
    canon_mutated = sample_repository_proof_root(
        canonicalization_version="ips/canonicalization@2"
    )
    graph_mutated = sample_repository_proof_root(
        dependency_graph_schema_version="graph@2"
    )
    parents_mutated = sample_repository_proof_root(
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)
    )

    for mutated in (
        parent_mutated,
        revision_mutated,
        environment_mutated,
        schema_mutated,
        canon_mutated,
        graph_mutated,
        parents_mutated,
    ):
        assert mutated.root_cid != base_root

    vectors = known_vectors()
    for field in (
        "parent_seal_cid",
        "revision",
        "environment_cid",
        "proof_schema_version",
        "canonicalization_version",
        "dependency_graph_schema_version",
        "parent_revision_ids",
    ):
        assert field in vectors["context_mutations"]
        assert vectors["context_mutations"][field] != vectors["base"]["root_cid"]


def test_repository_root_round_trip_and_all_category_fields() -> None:
    root = sample_repository_proof_root()
    payload = root.to_canonical()
    for cat in FOREST_CATEGORIES:
        field = category_root_field_name(cat)
        assert field in payload
        assert payload[field] == root.category_roots[cat]
    restored = RepositoryProofRoot.from_canonical(json.loads(root.to_canonical_json()))
    assert restored == root
    assert restored.repository_root() == root.root_cid
    assert restored.parent_seal_cid == GENESIS_PARENT_SEAL

    # Recompute from category root CIDs alone.
    recomputed = compute_repository_root(
        repository_id=root.repository_id,
        revision=root.revision,
        source_root_cid=root.source_root_cid,
        manifest_root_cid=root.manifest_root_cid,
        environment_cid=root.environment_cid,
        policy_cid=root.policy_cid,
        category_roots=root.category_roots,
        proof_schema_version=root.proof_schema_version,
        canonicalization_version=root.canonicalization_version,
        dependency_graph_schema_version=root.dependency_graph_schema_version,
        parent_seal_cid=root.parent_seal_cid,
        parent_revision_ids=root.parent_revision_ids,
    )
    assert recomputed.root_cid == root.root_cid


def test_category_root_round_trip() -> None:
    leaves = sample_category_leaves("formal_obligation")
    # Leaves were built for unit_test by default helper; rebuild for category.
    leaves = (
        sample_leaf(
            proof_unit_id="unit/a", category="formal_obligation", position=0
        ),
        sample_leaf(
            proof_unit_id="unit/b", category="formal_obligation", position=1
        ),
    )
    category = compute_category_root("formal_obligation", leaves)
    restored = CategoryRoot.from_canonical(json.loads(category.to_canonical_json()))
    assert restored == category
    assert restored.leaves[0] == ProofForestLeaf.from_canonical(
        leaves[0].to_canonical()
    )


def test_leaf_category_mismatch_fails() -> None:
    with pytest.raises(ForestCodecError, match="does not match"):
        compute_category_root(
            "unit_test",
            (
                sample_leaf(
                    proof_unit_id="unit/a",
                    category="static_analysis",
                    position=0,
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Portable fixture vectors
# ---------------------------------------------------------------------------


def test_known_vectors_cover_every_category_and_match_fixture() -> None:
    vectors = known_vectors()
    assert vectors["forest_codec_subset"] == FOREST_CODEC_SUBSET
    assert vectors["forest_codec_vectors_subset"] == FOREST_CODEC_VECTORS_SUBSET
    assert vectors["categories"] == list(FOREST_CATEGORIES)
    assert set(vectors["empty_category_roots"]) == set(FOREST_CATEGORIES)
    for cat in FOREST_CATEGORIES:
        empty = vectors["empty_category_roots"][cat]
        recomputed = compute_category_root(cat, ())
        assert empty["root_cid"] == recomputed.root_cid
        assert empty["merkle_root"] == recomputed.merkle_root

    # Node shapes recompute.
    for shape_name in ("unary", "binary", "binary_plus_unary"):
        shape = vectors["node_shapes"][shape_name]
        recomputed = compute_category_root("unit_test", shape["leaves"])
        assert recomputed.root_cid == shape["root_cid"]
        assert recomputed.merkle_root == shape["merkle_root"]

    # Base repository root recomputes.
    base_payload = vectors["base"]["payload"]
    restored = RepositoryProofRoot.from_canonical(base_payload)
    assert restored.root_cid == vectors["base"]["root_cid"]
    recomputed = compute_repository_root(
        repository_id=restored.repository_id,
        revision=restored.revision,
        source_root_cid=restored.source_root_cid,
        manifest_root_cid=restored.manifest_root_cid,
        environment_cid=restored.environment_cid,
        policy_cid=restored.policy_cid,
        category_roots=restored.category_roots,
        proof_schema_version=restored.proof_schema_version,
        canonicalization_version=restored.canonicalization_version,
        dependency_graph_schema_version=restored.dependency_graph_schema_version,
        parent_seal_cid=restored.parent_seal_cid,
        parent_revision_ids=restored.parent_revision_ids,
    )
    assert recomputed.root_cid == vectors["base"]["root_cid"]

    # One-bit mutation vector differs from base.
    assert (
        vectors["one_bit_leaf_mutation"]["root_cid"]
        != vectors["one_bit_leaf_mutation"]["base_root_cid"]
    )

    assert FIXTURE_PATH.is_file(), f"missing portable fixture at {FIXTURE_PATH}"
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Compact recipe fixture freezes categories, domains, and mutation fields.
    assert fixture["forest_codec_subset"] == FOREST_CODEC_SUBSET
    assert fixture["forest_codec_vectors_subset"] == FOREST_CODEC_VECTORS_SUBSET
    assert fixture["categories"] == list(FOREST_CATEGORIES)
    assert fixture["genesis_parent_seal"] == GENESIS_PARENT_SEAL
    assert fixture["domains"] == vectors["domains"]
    assert set(fixture["recipes"]["context_mutation_fields"]) == set(
        vectors["context_mutations"]
    )
    assert fixture["fail_closed"]["unknown_category"] == (
        vectors["fail_closed"]["unknown_category"]
    )

    # Recipe node shapes expand to the same digests as known_vectors().
    for shape_name, recipe in fixture["recipes"]["node_shapes"].items():
        category = recipe["category"]
        leaf_ids = recipe["leaf_ids"]
        leaves = tuple(
            sample_leaf(
                proof_unit_id=unit_id,
                category=category,
                position=index,
            )
            for index, unit_id in enumerate(leaf_ids)
        )
        expanded = compute_category_root(category, leaves)
        if shape_name == "empty":
            assert expanded.root_cid == (
                vectors["empty_category_roots"][category]["root_cid"]
            )
        else:
            assert expanded.root_cid == vectors["node_shapes"][shape_name]["root_cid"]

    # Live generator remains deterministic and covers every category root field.
    rendered = json.loads(render_forest_vectors_json())
    assert rendered["base"]["root_cid"] == vectors["base"]["root_cid"]
    for cat in FOREST_CATEGORIES:
        field = category_root_field_name(cat)
        assert field in rendered["base"]["payload"]
        assert field in vectors["base"]["payload"]


def test_import_has_no_side_effects() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                "assert 'multiformats' not in sys.modules; "
                "mod = importlib.import_module("
                "'ipfs_datasets_py.logic.zkp.incremental_sealing.forest_codec'"
                "); "
                "assert mod.FOREST_CODEC_SUBSET == 'ips/forest-codec@1'; "
                "assert 'multiformats' not in sys.modules; "
                "assert 'ipfs_datasets_py.logic.software_contracts.content' "
                "not in sys.modules; "
                "assert 'provekit' not in sys.modules; "
                "assert 'py_ecc' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    # Keep importlib available for hermetic reloads in other tests.
    importlib.import_module(
        "ipfs_datasets_py.logic.zkp.incremental_sealing.forest_codec"
    )
