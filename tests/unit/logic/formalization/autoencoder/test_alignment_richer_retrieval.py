"""Hermetic fixture vectors test retrieval boundaries, never encoder inference."""
from __future__ import annotations

import builtins
import hashlib
import json
import math
from copy import deepcopy

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_retrieval as subject
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR, CanonicalRule


def _target(**changes):
    fields = {"modality": "O", "actor": "clerk", "action": "retain", "object": "filing",
              "conditions": ("application_complete",), "exceptions": ("court_order",), "temporal": ("within_48_hours",)}
    fields.update(changes)
    return CanonicalRoundTripIR((CanonicalRule(**fields),)).to_dict()


def _basis(index, width=8):
    return [float(column == index) for column in range(width)]


def _rows(width=8):
    return [{"id": "train:a", "group_id": "group:a", "source_vector": _basis(0, width), "target": _target()},
            {"id": "train:b", "group_id": "group:b", "source_vector": _basis(1, width), "target": _target(conditions=("fees_paid",))}]


def _query(width=8, index=0):
    return {"id": "development:q", "group_id": "development:group", "source_vector": _basis(index, width)}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _reseal(value, field):
    value[field] = _digest({key: item for key, item in value.items() if key != field})
    return value


@pytest.mark.parametrize("width", [8, 384, 768])
def test_native_source_lanes_preserve_width_and_restore_json_head(width):
    rows, query = _rows(width), _query(width)
    original = deepcopy(rows)
    head = subject.fit_structural_ridge(rows)
    restored = json.loads(json.dumps(head))
    ranking = subject.rank_richer_candidates(query, rows, restored)
    assert restored == head
    assert head["source_width"] == width
    assert len(head["source_units"][0]) == width
    assert len(head["target_units"][0]) == 2048
    assert head["intercept"] is False
    for policy in ("source_cosine", "structural_ridge"):
        assert ranking[policy]["ranked"][0]["candidate_id"] == "train:a"
        assert len(ranking[policy]["full_pool_ranking"]) == 2
    assert rows == original
    assert ranking["query_reference_consumed"] is False
    assert head["qualified"] is False
    assert head["autoencoder_training_executed"] is False
    assert head["encoder_execution_authenticated"] is False


def test_head_records_actual_training_pairs_and_is_invariant_to_row_order():
    rows = _rows()
    left = subject.fit_structural_ridge(rows)
    right = subject.fit_structural_ridge(list(reversed(rows)))
    assert left == right
    assert [entry["id"] for entry in left["training_manifest"]] == ["train:a", "train:b"]
    for entry, row in zip(left["training_manifest"], rows, strict=True):
        assert entry["target_sha256"] == _digest(row["target"])
    assert "dev" not in left["fit_scope"]


def test_unintercepted_dual_ridge_matches_closed_form_for_orthogonal_sources():
    rows = _rows()
    head = subject.fit_structural_ridge(rows, alpha=1.0)
    assert head["kernel_inverse"] == [[0.5, 0.0], [0.0, 0.5]]
    assert head["fit_recipe"].startswith("uncentered_dual_ridge")
    assert all(math.isclose(sum(v*v for v in vector), 1.0, abs_tol=1e-12) for vector in head["target_units"])


@pytest.mark.parametrize("dimension,seed", [(2048, 0), (4096, 0), (2048, 1)])
def test_declared_formal_coordinates_remain_separate_from_native_source_width(dimension, seed):
    rows = _rows(384)
    head = subject.fit_structural_ridge(rows, dimension=dimension, seed=seed)
    ranking = subject.rank_richer_candidates(_query(384), rows, head)
    assert len(head["target_units"][0]) == dimension
    assert ranking["formal_dimension"] == dimension
    assert ranking["source_width"] == 384
    assert head["seed"] == seed


@pytest.mark.parametrize("extra", ["target", "reference", "expectation", "compiler_outcome", "predicted_facets", "context"])
def test_query_boundary_rejects_gold_and_context_channels(extra):
    rows = _rows()
    query = {**_query(), extra: _target()}
    head = subject.fit_structural_ridge(rows)
    with pytest.raises(ValueError, match="target-free"):
        subject.rank_richer_candidates(query, rows, head)


@pytest.mark.parametrize("field,value", [("id", "train:a"), ("group_id", "group:a")])
def test_source_query_cannot_retrieve_training_identity_or_siblings(field, value):
    rows = _rows()
    query = {**_query(), field: value}
    with pytest.raises(ValueError, match="leaks"):
        subject.rank_richer_candidates(query, rows, subject.fit_structural_ridge(rows))


def test_zero_formal_prediction_is_unavailable_without_fake_fallback():
    rows = _rows()
    ranking = subject.rank_richer_candidates(_query(index=2), rows, subject.fit_structural_ridge(rows))
    assert [item["candidate_id"] for item in ranking["source_cosine"]["ranked"]] == ["train:a", "train:b"]
    assert ranking["structural_ridge"]["status"] == "unavailable"
    assert ranking["structural_ridge"]["reason"] == "zero_prediction_vector"
    assert ranking["structural_ridge"]["ranked"] == []
    score = subject.score_richer_rankings(ranking, _target(), rows)
    assert score["policies"]["structural_ridge"]["authored_metrics"] is None


def test_reference_mutation_changes_posthoc_scores_without_changing_rankings_or_head():
    rows = _rows()
    head = subject.fit_structural_ridge(rows)
    ranking = subject.rank_richer_candidates(_query(), rows, head)
    original_head, original_ranking = deepcopy(head), deepcopy(ranking)
    same = subject.score_richer_rankings(ranking, _target(), rows)
    changed = subject.score_richer_rankings(ranking, _target(actor="officer", conditions=("identity_verified",)), rows)
    assert same != changed
    assert ranking == original_ranking and head == original_head
    assert same["policies"]["source_cosine"]["authored_metrics"]["exact_ir_counterpart_recall"] == {"available": True, "value": 1.0, "reason": None}
    counterpart = changed["policies"]["source_cosine"]["authored_metrics"]["exact_ir_counterpart_recall"]
    assert counterpart == {"available": False, "value": None, "reason": "no_reference_target_in_training_pool"}
    for key in ("qualified", "independent_fidelity_available", "proof_authority", "source_fidelity_established"):
        assert changed[key] is False


def test_seven_facet_grade_penalizes_unknown_qualifier_identity_despite_same_length():
    rows = _rows()
    ranking = subject.rank_richer_candidates(_query(), rows, subject.fit_structural_ridge(rows))
    result = subject.score_richer_rankings(ranking, _target(conditions=("identity_verified",)), rows)
    metrics = result["policies"]["source_cosine"]["authored_metrics"]
    assert metrics["nearest_weighted_fraction"] == pytest.approx(6/7)
    assert result["pool_coverage_ceiling"]["unscoped_qualifier_identity"]["conditions"]["reference_identity_recall"] == 0
    assert metrics["selected_coverage"]["unscoped_qualifier_identity"]["exceptions"]["reference_identity_recall"] == 1
    assert metrics["graded_facet_ndcg"] == pytest.approx(1)


def test_ndcg_is_normalized_to_attainable_pool_and_declared_rank_position():
    rows = _rows()
    ranking = subject.rank_richer_candidates(_query(index=1), rows, subject.fit_structural_ridge(rows), top_k=1)
    result = subject.score_richer_rankings(ranking, _target(), rows)
    metrics = result["policies"]["source_cosine"]["authored_metrics"]
    assert metrics["graded_facet_ndcg"] == pytest.approx(6/7)
    assert metrics["attainable_pool_best_weighted_fraction"] == 1
    assert metrics["exact_ir_counterpart_recall"]["value"] == 0


def test_unscoped_atoms_do_not_imply_core_scope_or_full_rule_match():
    rows = _rows()
    reference = _target(actor="officer")
    ranking = subject.rank_richer_candidates(_query(), rows, subject.fit_structural_ridge(rows))
    result = subject.score_richer_rankings(ranking, reference, rows)
    ceiling = result["pool_coverage_ceiling"]
    assert all(item["reference_identity_recall"] == 1 for item in ceiling["unscoped_qualifier_identity"].values())
    assert ceiling["core_scoped_typed_qualifier_counts"]["reference_recall"] == 0
    assert ceiling["full_rule_counts"]["reference_recall"] == 0


def test_multirule_qualifier_bag_agreement_keeps_full_rule_coassociation_failure():
    first = _target()["rules"][0]
    second = _target(conditions=("fees_paid",), exceptions=("legal_hold",))["rules"][0]
    original = CanonicalRoundTripIR.from_dict({"rules": [first, second]}).to_dict()
    swapped = CanonicalRoundTripIR.from_dict({"rules": [{**first, "exceptions": second["exceptions"]},
                                                      {**second, "exceptions": first["exceptions"]}]}).to_dict()
    rows = [{"id": "train:a", "group_id": "group:a", "source_vector": _basis(0), "target": swapped}]
    ranking = subject.rank_richer_candidates(_query(), rows, subject.fit_structural_ridge(rows))
    result = subject.score_richer_rankings(ranking, original, rows)
    metrics = result["policies"]["source_cosine"]["authored_metrics"]
    assert metrics["nearest_weighted_fraction"] == 1
    assert metrics["selected_coverage"]["core_scoped_typed_qualifier_counts"]["reference_recall"] == 1
    assert metrics["selected_coverage"]["full_rule_counts"]["reference_recall"] == 0
    assert metrics["exact_ir_counterpart_recall"]["available"] is False


@pytest.mark.parametrize("width", [0, 7, 9, 383, 512, 769, 2048])
def test_padding_or_truncation_into_a_native_lane_is_rejected(width):
    rows = _rows()
    rows[0]["source_vector"] = [1.0] * width
    with pytest.raises(ValueError):
        subject.fit_structural_ridge(rows)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, "1", None, 10**1000])
def test_source_vector_finiteness_and_numeric_types_are_strict(bad):
    rows = _rows()
    rows[0]["source_vector"][0] = bad
    with pytest.raises(ValueError):
        subject.fit_structural_ridge(rows)


def test_zero_and_mixed_width_training_sources_fail_and_large_finite_sources_are_stable():
    rows = _rows()
    rows[0]["source_vector"] = [0.0] * 8
    with pytest.raises(ValueError, match="zero"):
        subject.fit_structural_ridge(rows)
    rows = _rows()
    rows[1]["source_vector"] = _basis(1, 384)
    with pytest.raises(ValueError):
        subject.fit_structural_ridge(rows)
    rows = _rows()
    rows[0]["source_vector"][0] = 1e308
    assert subject.fit_structural_ridge(rows)["source_units"][0] == _basis(0)


@pytest.mark.parametrize("dimension,seed,alpha", [(8, 0, 1), (2048.0, 0, 1), (2048, True, 1),
    (2048, -1, 1), (2048, 0, 0), (2048, 0, True), (2048, 0, float("nan"))])
def test_fit_recipe_parameters_have_strict_types_and_ranges(dimension, seed, alpha):
    with pytest.raises(ValueError):
        subject.fit_structural_ridge(_rows(), dimension=dimension, seed=seed, alpha=alpha)


@pytest.mark.parametrize("mutation", ["extra", "manifest", "target", "source", "inverse", "authority", "intercept", "boolean_inverse"])
def test_resealed_head_cannot_change_training_geometry_or_solution(mutation):
    rows = _rows()
    head = subject.fit_structural_ridge(rows)
    if mutation == "extra":
        head["development_targets"] = [_target()]
    elif mutation == "manifest":
        head["training_manifest"][0]["id"] = "development:q"
    elif mutation == "target":
        head["target_units"][0][0] += .1
    elif mutation == "source":
        head["source_units"][0][0] = .5
    elif mutation == "inverse":
        head["kernel_inverse"][0][0] += .1
    elif mutation == "authority":
        head["qualified"] = True
    elif mutation == "boolean_inverse":
        head["kernel_inverse"][0][1] = False
    else:
        head["intercept"] = True
    _reseal(head, "head_sha256")
    with pytest.raises(ValueError):
        subject.rank_richer_candidates(_query(), rows, head)


def test_head_rejects_changed_training_reference_source_group_and_duplicate_ids():
    rows = _rows()
    head = subject.fit_structural_ridge(rows)
    for field, value in (("target", _target(modality="F")), ("source_vector", _basis(3)), ("group_id", "other")):
        changed = deepcopy(rows)
        changed[0][field] = value
        with pytest.raises(ValueError):
            subject.rank_richer_candidates(_query(), changed, head)
    duplicated = [rows[0], rows[0]]
    with pytest.raises(ValueError, match="duplicate"):
        subject.fit_structural_ridge(duplicated)
    with pytest.raises(ValueError, match="sixteen"):
        subject.fit_structural_ridge([rows[0]] * 17)


def test_fit_and_ranking_use_no_encoder_provider_solver_or_optimizer_imports(monkeypatch):
    original = builtins.__import__
    calls = []
    forbidden = ("torch", "transformers", "sentence_transformers", "openai", "z3", "lean", "spacy")
    def guarded(name, *args, **kwargs):
        calls.append(name)
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
            raise AssertionError("optional model/prover import: " + name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    rows = _rows()
    head = subject.fit_structural_ridge(rows)
    subject.rank_richer_candidates(_query(), rows, head)
    assert "numpy" in calls


def test_actual_authored_panel_pool_ceilings_are_explicit_without_source_embedding_claims():
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_panel import (
        build_alignment_richer_panel,
    )

    panel = build_alignment_richer_panel()
    training = [row for row in panel["rows"] if row["split"] == "train" and row["row_kind"] == "positive"]
    development = [row for row in panel["rows"] if row["split"] == "validation" and row["row_kind"] == "positive"]
    # These unit test inputs are declared fixture vectors, not spaCy/GTE/model outputs.
    rows = [{"id": row["id"], "group_id": row["group_id"], "source_vector": _basis(index % 8), "target": row["target"]}
            for index, row in enumerate(training)]
    head = subject.fit_structural_ridge(rows)
    available_atoms = required_atoms = 0
    for row in development:
        query = {"id": row["id"], "group_id": row["group_id"], "source_vector": _basis(0)}
        result = subject.score_richer_rankings(subject.rank_richer_candidates(query, rows, head), row["target"], rows)
        ceiling = result["pool_coverage_ceiling"]
        condition = ceiling["unscoped_qualifier_identity"]["conditions"]
        available_atoms += len(condition["matched_atoms"])
        required_atoms += condition["reference_atoms"]
        assert ceiling["core_scoped_typed_qualifier_counts"]["reference_recall"] == 0
        assert ceiling["full_rule_counts"]["reference_recall"] == 0
        assert result["reference_target_present_in_pool"] is False
    assert (len(rows), len(development), available_atoms, required_atoms) == (16, 8, 8, 10)


def test_ranking_checksum_and_candidate_accounting_fail_closed_before_scoring():
    rows = _rows()
    ranking = subject.rank_richer_candidates(_query(), rows, subject.fit_structural_ridge(rows))
    changed = deepcopy(ranking)
    changed["source_cosine"]["ranked"][0]["cosine_similarity"] = .5
    with pytest.raises(ValueError, match="digest"):
        subject.score_richer_rankings(changed, _target(), rows)
    changed = deepcopy(ranking)
    changed["source_cosine"]["full_pool_ranking"][1] = deepcopy(changed["source_cosine"]["full_pool_ranking"][0])
    _reseal(changed, "ranking_sha256")
    with pytest.raises(ValueError):
        subject.score_richer_rankings(changed, _target(), rows)


def test_reference_and_training_targets_require_canonical_seven_facet_owner():
    rows = _rows()
    rows[0]["target"]["rules"][0]["conditions"].append("application_complete")
    with pytest.raises(ValueError, match="canonical"):
        subject.fit_structural_ridge(rows)
    rows = _rows()
    ranking = subject.rank_richer_candidates(_query(), rows, subject.fit_structural_ridge(rows))
    with pytest.raises(ValueError):
        subject.score_richer_rankings(ranking, None, rows)
    wrong = _target()
    wrong["rules"][0]["binders"] = ["x"]
    with pytest.raises(ValueError):
        subject.score_richer_rankings(ranking, wrong, rows)
