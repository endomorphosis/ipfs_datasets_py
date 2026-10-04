"""Independent exact-source and embedding-contract checks; no model downloads."""
import json
import math

import pytest

from ipfs_datasets_py.ml.embeddings.semantic_boundaries import (
    SemanticBoundaryError, group_semantic_atoms,
)


def group(text, atoms, embedder, **kwargs):
    return group_semantic_atoms(text, atoms, embedder=embedder,
        max_chars=kwargs.pop("max_chars", 100), min_chars=kwargs.pop("min_chars", 0),
        **kwargs)


def test_real_vector_directions_change_groups_without_changing_source():
    text = "First.  Second.\nThird."
    atoms = [(0, 8), (8, 16), (16, len(text))]
    seen = []
    def embed(texts):
        seen.extend(texts)
        return [[3, 0], [2, 0], [0, 7]]
    report = group(text, atoms, embed)
    assert seen == [text[a:b] for a, b in atoms]
    assert [g["atom_indexes"] for g in report["groups"]] == [[0, 1], [2]]
    assert report["boundaries"][0]["cosine_similarity"] == 1
    assert report["boundaries"][1]["cosine_similarity"] == 0
    changed = group(text, atoms, lambda _: [[1, 0], [0, 1], [0, 1]])
    assert [g["atom_indexes"] for g in changed["groups"]] == [[0], [1, 2]]
    assert changed["source_sha256"] == report["source_sha256"]
    assert report["embeddings_used"] and not report["semantic_correctness_verified"]
    assert report["config"]["token_budget_checked"] is False


def test_unicode_and_whitespace_reconstruct_exactly():
    text = "é α\r\nβ\t  γ"
    atoms = [(0, 2), (2, 6), (6, len(text))]
    report = group(text, atoms, lambda _: [[1, 0]] * 3)
    assert "".join(text[g["start_char"]:g["end_char"]] for g in report["groups"]) == text
    assert report["groups"][0]["end_char"] == len(text)


def test_retained_atom_selectors_replay_after_grouping_and_json_round_trip():
    text = "é one.  β two.\nγ three."
    atoms = [(0, 8), (8, 15), (15, len(text))]
    report = group(text, atoms, lambda _: [[3, 0], [5, 0], [0, 2]])
    receipt = json.loads(json.dumps(report))
    retained = [(row["start_char"], row["end_char"]) for row in receipt["atoms"]]
    assert retained == atoms
    assert len(receipt["atoms"]) > len(receipt["groups"])
    assert "".join(text[start:end] for start, end in retained) == text
    replay = group(text, retained, lambda _: receipt["normalized_vectors"])
    assert replay["boundaries"] == receipt["boundaries"]
    assert replay["groups"] == receipt["groups"]
    assert replay["embedding_input_sha256"] == receipt["embedding_input_sha256"]


def test_barriers_and_size_limits_win_over_similarity_and_minimum():
    text = "aaaabbbbccccdddd"
    atoms = [(i, i + 4) for i in range(0, 16, 4)]
    report = group(text, atoms, lambda _: [[1, 0]] * 4,
                   max_chars=8, min_chars=8, barriers=[1])
    assert [g["atom_indexes"] for g in report["groups"]] == [[0], [1, 2], [3]]
    assert [b["reason"] for b in report["boundaries"]] == ["structural_barrier", "adjacent_similarity", "max_chars"]


def test_minimum_join_is_explicit_even_with_opposed_vectors():
    report = group("aaaabbbb", [(0, 4), (4, 8)], lambda _: [[1, 0], [-1, 0]], min_chars=6)
    assert len(report["groups"]) == 1
    assert report["boundaries"][0]["reason"] == "minimum_size_join"
    assert report["boundaries"][0]["cosine_similarity"] == -1


def test_oversize_and_token_overflow_atoms_are_not_embedded():
    seen = []
    text = "ok" + "z" * 12 + "tokenheavy" + "ok"
    atoms = [(0, 2), (2, 14), (14, 24), (24, 26)]
    def embed(values):
        seen.extend(values)
        return [[1, 0]] * len(values)
    report = group(text, atoms, embed, max_chars=11, max_embedding_chars=11,
                   embedding_eligible=lambda text: text != "tokenheavy")
    assert seen == ["ok", "ok"]
    assert report["config"]["token_budget_checked"] is True
    assert [g["atom_indexes"] for g in report["groups"]] == [[0], [1], [2], [3]]
    assert report["groups"][1]["exceeds_max_chars"]
    assert [a["reason"] for a in report["opaque_atoms"]] == ["atom_exceeds_max_chars", "atom_exceeds_embedding_token_budget"]


@pytest.mark.parametrize("vectors", [[], [[0, 0]], [[math.nan, 1]], [[math.inf, 0]],
    [[True, 1]], [["1", 0]], [[1], [1, 2]], [[1, 0], [1, 0]]])
def test_invalid_vectors_fail_explicitly(vectors):
    with pytest.raises(SemanticBoundaryError, match="embedding_failed"):
        group("text", [(0, 4)], lambda _: vectors)


def test_bad_batch_dimensions_fail_even_when_count_matches():
    with pytest.raises(SemanticBoundaryError, match="embedding_failed"):
        group("aabb", [(0, 2), (2, 4)], lambda _: [[1], [1, 2]])


def test_provider_failure_is_structural_only_when_explicit():
    def broken(_):
        raise RuntimeError("private runtime detail must not enter report")
    with pytest.raises(SemanticBoundaryError, match="embedding_failed:RuntimeError"):
        group("aabb", [(0, 2), (2, 4)], broken)
    report = group("aabb", [(0, 2), (2, 4)], broken, on_embedding_error="structural")
    assert report["embedding_status"] == "structural_fallback"
    assert report["embedding_error_type"] == "RuntimeError"
    assert report["embeddings_used"] is False and report["normalized_vectors"] == []
    assert report["boundaries"][0]["reason"] == "explicit_structural_fallback"


def test_all_opaque_or_empty_never_calls_provider():
    def unused(_):
        pytest.fail("unexpected embedding call")
    opaque = group("opaque", [(0, 6)], unused, max_embedding_chars=2)
    empty = group("", [], unused)
    assert opaque["embedding_status"] == empty["embedding_status"] == "not_required"
    assert not opaque["embeddings_used"] and empty["groups"] == []


@pytest.mark.parametrize("atoms", [[(1, 4)], [(0, 2), (3, 4)], [(0, 3), (2, 4)],
    [(0, 5)], [(0, 0), (0, 4)], [(False, 4)], []])
def test_non_partitions_rejected_before_inference(atoms):
    with pytest.raises(SemanticBoundaryError, match="partition"):
        group("text", atoms, lambda _: pytest.fail("invalid input reached provider"))


@pytest.mark.parametrize("options", [dict(max_chars=True), dict(min_chars=-1),
    dict(min_chars=101), dict(similarity_threshold=math.nan), dict(similarity_threshold=2),
    dict(on_embedding_error="silent"), dict(barriers=[0]), dict(barriers=[1]),
    dict(embedding_eligible=lambda _: "yes")])
def test_invalid_policy_rejected(options):
    with pytest.raises(SemanticBoundaryError):
        group("text", [(0, 4)], lambda _: [[1, 0]], **options)
