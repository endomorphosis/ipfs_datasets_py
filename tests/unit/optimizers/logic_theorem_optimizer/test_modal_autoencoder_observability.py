"""Timing and evidence metadata must never become objective or admission signals.

Cache-path tests inject the expensive bridge boundary; supplied-target tests run
real model evaluation/training. These fixtures do not establish Lean admission.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer._autoencoder_prepared_targets import (
    _prepare_native_targets,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import ProjectionProfiler

BRIDGES = (
    "modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router",
)


@pytest.fixture(scope="module")
def sample():
    return build_us_code_sample(
        title="5", section="observability", text="The officer shall retain the file for at least 20 days.",
        embedding_vector=[1.0, 0.0, 0.5],
    )


def target_for(sample, losses=None):
    return LegalIRTrainingTarget(
        BRIDGES,
        LegalIRDocument(
            sample.sample_id, sample.text, sample.normalized_text,
            views={"deontic.ir": LogicIRView("deontic.ir", {"rules": []})},
            metadata={"created_at": "fixture"},
        ),
        {} if losses is None else losses,
        {}, {"deontic.ir": 0.75, "fol.ir": 0.25}, False,
    )


def evaluate(sample, target, *, profile):
    model = ma.AdaptiveModalAutoencoder(compute_device="python")
    before = model.state.to_json()
    result = model.evaluate(
        [sample], legal_ir_bridge_names=BRIDGES, legal_ir_evaluate_provers=False,
        legal_ir_targets={sample.sample_id: target}, legal_ir_parallel_workers=1,
        use_sample_memory=False, profile_evaluation=profile,
    )
    assert model.state.to_json() == before
    return result


def test_profile_separates_payload_model_and_capture_without_changing_scores(sample, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")
    target = target_for(sample, {"source_decompiled_text_token_loss": 0.0})
    plain = evaluate(sample, target, profile=False)
    measured = evaluate(sample, target, profile=True)
    serialized = measured.to_dict()
    profile = serialized.pop("evaluation_profile")
    assert serialized == plain.to_dict()
    assert "evaluation_profile" not in plain.to_dict()
    assert measured.legal_ir_target_count == 1
    assert profile["sample_count"] == 1
    stages = [profile[key] for key in (
        "target_payload_seconds", "model_metrics_seconds", "ontology_capture_seconds",
    )]
    assert all(value >= 0.0 for value in stages)
    assert profile["total_seconds"] >= sum(stages)
    observed = profile["target_observation"]
    assert observed["bridge_names"] == list(BRIDGES)
    assert observed["evaluate_provers"] is False
    assert observed["disk_cache_enabled"] is False
    assert observed["supplied_target_count"] == 1
    assert observed["native_evaluation_attempt_count"] == 0
    assert observed["representation_counts"] == {
        "native": 1, "prepared_native": 0, "cached_summary": 0, "other": 0,
    }
    assert observed["parallel_workers_requested"] == 1
    assert observed["parallel_workers_used"] == 0
    for key in ("target_items_seconds", "structural_target_seconds", "target_reduction_seconds"):
        assert 0 <= observed[key] <= profile["target_payload_seconds"]


@pytest.mark.parametrize("losses, specific, compatibility", [
    ({}, 0, 0),
    ({"source_decompiled_text_token_loss": 0.0}, 1, 0),
    ({"source_decompiled_text_embedding_cosine_similarity": 0.0}, 1, 0),
    ({"cosine_similarity": 1.0}, 0, 1),
    ({"raw_source_embedding_cosine_similarity": 0.5}, 0, 1),
    ({"source_decompiled_text_token_loss": None}, 0, 0),
    ({"source_decompiled_text_token_loss": float("nan")}, 0, 0),
    ({"source_decompiled_text_token_loss": float("inf")}, 0, 0),
    ({"source_decompiled_text_token_loss": True}, 0, 0),
])
def test_decompiler_evidence_distinguishes_absence_explicit_zero_and_generic_metrics(
    sample, losses, specific, compatibility,
):
    payload = ma._legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: target_for(sample, losses)})
    evidence = payload["decompiler_evidence"]
    assert evidence["source_decompiled_metric_sample_count"] == specific
    assert evidence["compatibility_metric_sample_count"] == compatibility
    assert evidence["observed"] is bool(specific)
    assert evidence["validation_authority"] is False
    assert evidence["structural_target_sample_count"] == len(payload["decompiler_structural_targets_by_sample"])
    assert evidence["structural_formula_target_count"] == sum(
        len(value["formula_targets"]) for value in payload["decompiler_structural_targets_by_sample"].values()
    )


def test_bridge_off_and_empty_targets_never_claim_observed_decompiler_metrics(sample):
    for kwargs in ({"legal_ir_bridge_names": ()}, {"legal_ir_targets": {}}):
        result = ma.AdaptiveModalAutoencoder(compute_device="python").evaluate(
            [sample], profile_evaluation=True, use_sample_memory=False, **kwargs,
        )
        assert result.legal_ir_target_count == 0
        assert result.decompiler_evidence["observed"] is False
        assert result.decompiler_evidence["source_decompiled_metric_sample_count"] == 0
        assert result.evaluation_profile["target_observation"]["target_count"] == 0
        assert result.evaluation_profile["target_observation"]["native_evaluation_attempt_count"] == 0
        # The legacy numeric default remains unchanged and is no evidence.
        assert ma._source_decompiled_text_losses_from_targets(result.legal_ir_losses)["source_decompiled_text_token_loss"] == 0.0
    empty = ma.AdaptiveModalAutoencoder(compute_device="python").evaluate([])
    assert empty.decompiler_evidence["observed"] is False


def test_prepared_targets_are_identified_without_claiming_native_rebuild(sample):
    targets, prepared = _prepare_native_targets({sample.sample_id: target_for(sample)})
    assert prepared["applied"] is True
    result = evaluate(sample, targets[sample.sample_id], profile=True)
    observed = result.evaluation_profile["target_observation"]
    assert observed["supplied_target_count"] == 1
    assert observed["representation_counts"]["prepared_native"] == 1
    assert observed["native_evaluation_attempt_count"] == 0


@pytest.fixture
def isolated_cache(monkeypatch):
    monkeypatch.setattr(ma, "_LEGAL_IR_TARGET_CACHE", {})
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")
    monkeypatch.setattr(ma, "_read_legal_ir_target_disk_cache", lambda key: None)
    monkeypatch.setattr(ma, "_write_legal_ir_target_disk_cache", lambda *args: None)


def acquire(samples, observation, workers=1):
    return ma._legal_ir_target_items(
        samples, bridge_names=BRIDGES, evaluate_provers=False, legal_ir_targets=None,
        parallel_workers=workers, observation=observation,
    )


def test_native_miss_then_memory_reuse_and_cache_clear_do_not_claim_process_coldness(
    sample, monkeypatch, isolated_cache,
):
    calls = []
    target = target_for(sample)
    def build(_evaluate, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(training_target=lambda: target)
    monkeypatch.setattr(ma, "_evaluate_legal_ir_multiview_with_timeout", build)
    cold, warm, cleared = {}, {}, {}
    assert acquire([sample], cold) == [(sample.sample_id, target)]
    assert acquire([sample], warm) == [(sample.sample_id, target)]
    ma._LEGAL_IR_TARGET_CACHE.clear()
    acquire([sample], cleared)
    assert len(calls) == 2
    assert calls[0]["bridge_names"] == BRIDGES
    assert calls[0]["evaluate_provers"] is False
    assert cold["target_cache_miss_count"] == cold["generated_target_count"] == 1
    assert cold["native_evaluation_seconds_sum"] > 0
    assert cold["training_target_seconds_sum"] > 0
    assert warm["memory_cache_hit_count"] == 1
    assert warm["native_evaluation_attempt_count"] == 0
    assert warm["native_evaluation_seconds_sum"] == 0.0
    assert cold["process_target_cache_entries_at_start"] == 0
    assert warm["process_target_cache_entries_at_start"] == 1
    assert cleared["process_target_cache_entries_at_start"] == 0
    assert cleared["bridge_module_preloaded_at_start"] is True
    assert cleared["cache_observation_scope"] == "this_evaluation_not_proof_of_process_coldness"


def test_disk_hit_is_counted_without_native_evaluation(sample, monkeypatch, isolated_cache):
    target = target_for(sample)
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "1")
    monkeypatch.setattr(ma, "_read_legal_ir_target_disk_cache", lambda key: target)
    def forbidden(*args, **kwargs):
        pytest.fail("a cache hit invoked the native evaluator")
    monkeypatch.setattr(ma, "_evaluate_legal_ir_multiview_with_timeout", forbidden)
    observation = {}
    assert acquire([sample], observation) == [(sample.sample_id, target)]
    assert observation["disk_cache_hit_count"] == 1
    assert observation["disk_cache_enabled"] is True
    assert observation["native_evaluation_attempt_count"] == 0


def test_timeout_is_failed_fallback_and_not_generated_native_target(sample, monkeypatch, isolated_cache):
    def timeout(*args, **kwargs):
        raise ma._LegalIRTargetTimeout("fixture timeout")
    monkeypatch.setattr(ma, "_evaluate_legal_ir_multiview_with_timeout", timeout)
    observation = {}
    result = acquire([sample], observation)
    assert result[0][1].accepted is False
    assert result[0][1].losses["legal_ir_target_timeout_loss"] == 1.0
    assert observation["timeout_fallback_count"] == 1
    assert observation["generated_target_count"] == 0
    assert observation["representation_counts"]["cached_summary"] == 1
    assert observation["native_evaluation_seconds_sum"] > 0
    assert observation["training_target_seconds_sum"] == 0


def test_parallel_counters_include_every_sample_once(sample, monkeypatch, isolated_cache):
    samples = [replace(sample, sample_id=f"sample-{index}", text=f"{sample.text} {index}", normalized_text=f"{sample.normalized_text} {index}") for index in range(8)]
    monkeypatch.setattr(ma, "_evaluate_legal_ir_multiview_with_timeout", lambda *a, **k: SimpleNamespace(
        training_target=lambda: target_for(next(row for row in samples if row.sample_id == k["document_id"])),
    ))
    observation = {}
    results = acquire(samples, observation, workers=4)
    assert [sample_id for sample_id, _ in results] == [row.sample_id for row in samples]
    assert observation["parallel_workers_used"] == 4
    assert observation["native_evaluation_attempt_count"] == observation["generated_target_count"] == 8
    assert observation["representation_counts"]["native"] == 8


@pytest.mark.parametrize("bounded", [False, True])
def test_profiled_projection_preserves_state_objective_and_records_each_evaluation(sample, bounded):
    reports, states = [], []
    for profiler in (None, ProjectionProfiler()):
        model = ma.AdaptiveModalAutoencoder(compute_device="python")
        reports.append(model.train_generalizable_projection(
            [sample], legal_ir_bridge_names=BRIDGES, legal_ir_evaluate_provers=False,
            legal_ir_targets={sample.sample_id: target_for(sample)}, legal_ir_parallel_workers=1,
            legal_ir_bridge_max_samples=1 if bounded else None,
            epochs=1, max_line_search_attempts=1, projection_max_update_families=1,
            projection_update_backend="python_sparse_batch", projection_profiler=profiler,
        ))
        states.append(model.state.to_json())
    plain, measured = reports
    assert states[0] == states[1]
    assert plain["evaluated_objective"] == measured["evaluated_objective"]
    assert plain["accepted_epochs"] == measured["accepted_epochs"]
    assert plain["after"]["legal_ir_target_count"] == measured["after"]["legal_ir_target_count"] == 1
    assert "evaluation_profile" in measured["before"]
    assert "evaluation_profile" in measured["after"]
    before_profile = measured["before"]["evaluation_profile"]
    if bounded:
        assert before_profile["bridge"]["target_observation"]["target_count"] == 1
        assert before_profile["base"]["target_observation"]["target_count"] == 0
    else:
        assert before_profile["target_observation"]["target_count"] == 1
    events = profiler.events
    evaluation_events = [event for event in events if "evaluation_profile" in event.metadata]
    assert evaluation_events
    assert evaluation_events[0].stage.startswith("before_holdout_evaluation")
    assert all(event.metadata["evaluation_profile"]["total_seconds"] >= 0 for event in evaluation_events)
