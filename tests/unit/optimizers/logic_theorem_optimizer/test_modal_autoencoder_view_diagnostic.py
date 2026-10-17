"""Controlled numeric diagnostics and rollback tests; no semantic admissions."""
import math
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_view_diagnostic import (
    FixedViewVocabulary, score_fixed_view_vocabulary,
)


def profile(n=6, **kwargs):
    return FixedViewVocabulary(**(dict(profile_id="controlled-v1", modality_id="test",
        schema_id="controlled-raw-views-v1", lineage_id="controlled-two-dimensional",
        embedding_dimensions=2, view_ids=tuple(f"view{i}" for i in range(n))) | kwargs))


def configured(monkeypatch):
    model = ma.AdaptiveModalAutoencoder(compute_device="python")
    rows = [SimpleNamespace(sample_id=name, embedding_vector=[1., -.5], normalized_text=name)
            for name in ("four", "six")]
    monkeypatch.setattr(model, "_legal_ir_view_feature_keys_for", lambda row: [])
    monkeypatch.setattr(model, "_semantic_slot_distribution_for", lambda row: {})
    monkeypatch.setattr(model, "_learned_feature_activity_count", lambda *args: 0)
    targets = {row.sample_id: {f"view{i}": 1/n for i in range(n)}
               for row, n in zip(rows, (4, 6))}
    return model, rows, targets


def test_fixed_denominator_exposes_historical_support_change_without_changing_it(monkeypatch):
    model, rows, targets = configured(monkeypatch)
    native_before = [model._legal_ir_view_distribution(row, targets[row.sample_id], use_sample_memory=False)
                     for row in rows]
    before_state = model.state.to_json()
    fixed = score_fixed_view_vocabulary(model, rows, targets, profile())
    assert fixed["cross_entropy_loss"] == pytest.approx(math.log(6))
    assert len(native_before[0]) == 4 and len(native_before[1]) == 6
    assert model.state.to_json() == before_state
    model.state.legal_ir_view_logits.update({f"view{i}": 0. for i in range(6)})
    model._invalidate_state_dependent_evaluator_caches()
    expanded = model._legal_ir_view_distribution(rows[0], targets["four"], use_sample_memory=False)
    assert len(expanded) == 6
    assert ma.cross_entropy_distribution_loss(expanded, targets["four"]) > math.log(4)
    assert score_fixed_view_vocabulary(model, rows, targets, profile()) == fixed


def test_unknown_sparse_heads_and_warm_candidate_cache_do_not_expand_declared_support(monkeypatch):
    model, rows, targets = configured(monkeypatch)
    before = score_fixed_view_vocabulary(model, rows, targets, profile())
    model._legal_ir_view_family_candidates()
    model.state.legal_ir_view_logits["unrelated-schema"] = 10.
    model.state.family_logits["four"] = {"view0": 100.}
    model.state.legal_ir_view_embedding_weights["new-inactive-key"] = [0., 0.]
    after = score_fixed_view_vocabulary(model, rows, targets, profile())
    assert before == after
    assert after["undeclared_head_policy"] == "excluded_by_declared_support_not_coverage_certified"


def test_numeric_heads_respond_continuously_to_small_update_and_rank_correct_direction(monkeypatch):
    model, rows, _ = configured(monkeypatch)
    targets = {"four": {"view0": 1.}}
    def loss(value):
        model.state.legal_ir_view_logits["view0"] = value
        return score_fixed_view_vocabulary(model, rows[:1], targets, profile())["cross_entropy_loss"]
    base = loss(0.)
    assert 0 < base - loss(1e-8) < 1e-7
    assert loss(1.) < base < loss(-1.)


@pytest.mark.parametrize("targets", [
    {}, {"four": {}}, {"four": {"unknown": 1.}}, {"four": {"view0": 1., "unknown": 0.}},
    {"four": {"view0": .5}}, {"four": {"view0": -1., "view1": 2.}},
    {"four": {"view0": float("nan")}}, {"four": {"view0": float("inf")}},
    {"four": {"view0": True}},
    {"four": {"view0": 1e308, "view1": 1e308}}, None,
])
def test_invalid_targets_fail_before_numeric_head_evaluation(monkeypatch, targets):
    model, rows, _ = configured(monkeypatch)
    monkeypatch.setattr(model, "_legal_ir_view_logits_for", lambda *a, **kw: pytest.fail("head ran"))
    with pytest.raises(ValueError):
        score_fixed_view_vocabulary(model, rows[:1], targets, profile())


@pytest.mark.parametrize("change", [
    {"view_ids": ()}, {"view_ids": ["view0"]}, {"view_ids": ("view0", "view0")},
    {"view_ids": (" view0",)}, {"modality_id": ""}, {"embedding_dimensions": True},
])
def test_invalid_profile_refuses(change):
    with pytest.raises(ValueError):
        profile(**change)


def test_profile_order_dimensions_sample_identity_and_modal_collisions(monkeypatch):
    model, rows, targets = configured(monkeypatch)
    assert profile().sha256 != profile(view_ids=tuple(reversed(profile().view_ids))).sha256
    reversed_profile = profile(view_ids=tuple(reversed(profile().view_ids)))
    scored = score_fixed_view_vocabulary(model, rows, targets, reversed_profile)
    assert tuple(scored["rows"][0]["probabilities"]) == reversed_profile.view_ids
    for vocabulary in (profile(embedding_dimensions=8), profile(view_ids=(model.modal_families[0],))):
        with pytest.raises(ValueError):
            score_fixed_view_vocabulary(model, rows, targets, vocabulary)
    with pytest.raises(ValueError, match="duplicate"):
        score_fixed_view_vocabulary(model, [rows[0], rows[0]], {"four": targets["four"]}, profile())


def test_existing_active_zero_feature_normalization_is_visible_and_preserved(monkeypatch):
    model, rows, _ = configured(monkeypatch)
    monkeypatch.setattr(model, "_learned_feature_activity_count",
                        ma.AdaptiveModalAutoencoder._learned_feature_activity_count.__get__(model))
    monkeypatch.setattr(model, "_fallback_feature_keys_for", lambda row: [])
    monkeypatch.setattr(model, "_sample_cache_for", lambda row: {})
    monkeypatch.setattr(model, "_legal_ir_view_feature_keys_for", lambda row: ["codec:a", "codec:b"])
    model.feature_activity_reference = 1.
    model.state.feature_legal_ir_view_logits["codec:a"] = {"view0": 1.}
    targets = {"four": {"view0": 1.}}
    before = score_fixed_view_vocabulary(model, rows[:1], targets, profile())
    model.state.feature_legal_ir_view_logits["codec:b"] = {"view0": 0.}
    after = score_fixed_view_vocabulary(model, rows[:1], targets, profile())
    assert after["cross_entropy_loss"] > before["cross_entropy_loss"]


def run_controlled_training(monkeypatch, diagnostic, *, rejected, invalid_proposal=False, mutate_targets=False):
    model, rows, _ = configured(monkeypatch)
    evaluations = []
    monkeypatch.setattr(model, "_select_hard_examples_for_projection", lambda rows, **kw: list(rows))
    def evaluate(rows, **kwargs):
        evaluations.append(tuple(row.sample_id for row in rows))
        value = model.state.legal_ir_view_logits.get("view0", 0.)
        loss = 1 + value if rejected else 1 - value
        return ma.AutoencoderEvaluation(len(rows), 1., 0., loss, 1., 0., 0., {}, cross_entropy_excess_loss=1.)
    monkeypatch.setattr(model, "evaluate", evaluate)
    def nudge(rows, **kwargs):
        model.state.legal_ir_view_logits["view0"] = .2
        return {key: {} for key in ("gradient_norms_by_family", "gradient_norms_by_head",
            "head_family_gradient_norms", "head_family_update_norms", "update_norms_by_family", "update_norms_by_head")}
    monkeypatch.setattr(model, "_apply_projection_update_batch", nudge)
    explicit_targets = {"six": {"view0": 1.}}
    opts = dict(projection_view_vocabulary_diagnostic=profile(2),
                projection_view_diagnostic_targets=explicit_targets) if diagnostic else {}
    if invalid_proposal:
        native_logits = model._legal_ir_view_logits_for
        def logits(*args, **kwargs):
            result = native_logits(*args, **kwargs)
            if model.state.legal_ir_view_logits.get("view0", 0.):
                result["view0"] = float("nan")
            return result
        monkeypatch.setattr(model, "_legal_ir_view_logits_for", logits)
    if mutate_targets:
        opts["progress_callback"] = lambda payload: explicit_targets.clear()
    report = model.train_generalizable_projection(rows[:1], validation_samples=rows[1:],
        epochs=1, max_seconds=30, max_line_search_attempts=1, projection_max_update_families=1,
        projection_update_backend="python_sparse_batch", **opts)
    return model, report, evaluations


@pytest.mark.parametrize("rejected", [False, True])
def test_training_sidecar_captures_proposal_before_rollback_and_keeps_native_decision(monkeypatch, rejected):
    plain, default, base_calls = run_controlled_training(monkeypatch, False, rejected=rejected)
    model, report, calls = run_controlled_training(monkeypatch, True, rejected=rejected)
    assert default["accepted_epochs"] == report["accepted_epochs"] == (0 if rejected else 1)
    assert plain.state.to_json() == model.state.to_json()
    assert default["before"] == report["before"] and default["after"] == report["after"]
    assert calls == base_calls
    assert "fixed_view_diagnostic" not in default
    diagnostic = report["fixed_view_diagnostic"]
    candidate = report["epoch_reports"][0]["candidate_reports"][0]["fixed_view_diagnostic"]
    assert candidate["cross_entropy_loss"] < diagnostic["before"]["cross_entropy_loss"]
    if rejected:
        assert diagnostic["after"] == diagnostic["before"]
    else:
        assert diagnostic["after"] == candidate


def test_training_rejects_missing_targets_before_evaluation_or_weight_mutation(monkeypatch):
    model, rows, _ = configured(monkeypatch)
    before = model.state.to_json()
    monkeypatch.setattr(model, "evaluate", lambda *a, **kw: pytest.fail("native evaluate ran"))
    with pytest.raises(ValueError, match="explicit target"):
        model.train_generalizable_projection(rows, projection_view_vocabulary_diagnostic=profile())
    assert model.state.to_json() == before


def test_invalid_proposal_diagnostic_keeps_native_rejection_and_rollback(monkeypatch):
    model, report, _ = run_controlled_training(monkeypatch, True, rejected=True, invalid_proposal=True)
    candidate = report["epoch_reports"][0]["candidate_reports"][0]
    assert candidate["fixed_view_diagnostic"]["status"] == "invalid"
    assert report["accepted_epochs"] == 0 and not model.state.legal_ir_view_logits
    assert report["fixed_view_diagnostic"]["after"] == report["fixed_view_diagnostic"]["before"]


def test_training_freezes_explicit_targets_against_caller_mutation(monkeypatch):
    _, baseline, _ = run_controlled_training(monkeypatch, True, rejected=True)
    _, mutated, _ = run_controlled_training(monkeypatch, True, rejected=True, mutate_targets=True)
    assert mutated["fixed_view_diagnostic"] == baseline["fixed_view_diagnostic"]
