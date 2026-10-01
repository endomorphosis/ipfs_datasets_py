#!/usr/bin/env python3
"""Prepared legacy throughput and separately sealed feature-loss evaluation.

Performance uses the already exposed 3+3 authored fixture. Fit uses only the
new panel's 32 training and eight tuning sources. Evaluation is a separate
explicit command after the caller's global candidate-freeze barrier. No raw
linguistic reconstruction or independent formula fidelity is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import compare_legacy_active_training as prior
from scripts.ops.legal_ir import evaluate_training_holdouts as current

require, raw, sha, write = prior.require, prior.raw, prior.sha, prior.write
ARMS = ("fixed_rate", "adaptive_rate")
PROPOSALS = 12
REPETITIONS = 3
SECONDS = 300
FALSE = dict(prior.FALSE, independent_generalization_verified=False,
             independent_formula_reconstruction_verified=False)
_IMPORTED_SHA = sha(__file__)


def sources():
    require(sha(__file__) == _IMPORTED_SHA, "legacy prepared runner changed since import")
    return {**prior.source_hashes(), **current.sources(), str(Path(__file__).resolve()): sha(__file__)}


def runtimes():
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import active_training as active
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import feature_training_session as reference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import prepared_feature_training as prepared
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import linguistic_view_reuse as profiles
    require_workspace_logic_tree()
    return active, reference, prepared, profiles


def compact(value):
    return {key: value[key] for key in ("sample_count", "cross_entropy_loss", "cross_entropy_excess_loss",
            "cross_entropy_entropy_loss", "embedding_cosine_similarity", "reconstruction_loss", "legal_ir_target_count")}


def build(model, rows):
    return [model.build_sample(title="authored-action-disjoint-feature-diagnostic", section=row["id"],
                              text=row["text"], citation="authored fixture:"+row["id"]) for row in rows]


def weights_digest(model):
    return hashlib.sha256(raw(model.state.to_dict())).hexdigest()


def measured(session, count, *, max_seconds):
    """Count evaluations with a temporary timer probe in this private process."""
    active = runtimes()[0]
    evaluate = active._evaluation
    calls = 0
    def counted(model, rows):
        nonlocal calls
        calls += 1
        return evaluate(model, rows)
    active._evaluation = counted
    try:
        start = time.perf_counter()
        result = session.advance(max_proposals=count, max_seconds=max_seconds)
        seconds = time.perf_counter() - start
    finally:
        active._evaluation = evaluate
    return result, seconds, calls


def performance(directory):
    active, reference, prepared, profiles = runtimes()
    source_hashes = sources()
    directory.mkdir(parents=True, exist_ok=False)
    plan = dict(schema="legacy-prepared-throughput-plan/v1", source_hashes=source_hashes,
        repetitions=REPETITIONS, proposals=PROPOSALS, training_samples=3, tuning_samples=3,
        order=[["reference", "prepared"], ["prepared", "reference"], ["reference", "prepared"]],
        cache_scope="warm imported producer; per-model linguistic observations primed; no metric disk cache",
        warmup="one unscored proposal for each engine on private fresh weights",
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
        metric_disk_cache=False, legal_ir_parallel_workers=1, sample_memory=False, temperature=0, **FALSE)
    write(directory / "plan.json", plan)
    engines = {"reference": reference.FeatureTrainingSession, "prepared": prepared.PreparedFeatureTrainingSession}
    results, expected = [], None
    for repetition, order in enumerate([["reference", "prepared"]] + plan["order"]):
        for engine in order:
            model = profiles.ViewReuseHistoricalDaemonAutoencoder(compute_device="cpu")
            splits = {split: [model.build_sample(title="authored-feature-diagnostic", section=f"{split}-{index}",
                        text=text, citation=f"authored feature diagnostic:{split}-{index}")
                       for index, text in enumerate(texts)] for split, texts in prior.TEXTS.items()}
            training, tuning = splits["training"], splits["tuning"]
            observations = [model.linguistic_observation(row) for row in training+tuning]
            session = engines[engine](model, training, validation_samples=tuning, proposal_budget=PROPOSALS)
            result, elapsed, calls = measured(session, 1 if repetition == 0 else PROPOSALS, max_seconds=120)
            if repetition == 0:
                continue
            require(result["accepted_updates"] == PROPOSALS, "throughput arm did not accept all proposals")
            signature = dict(weights=weights_digest(model), state=session.state,
                             proposals=result["proposal_reports"], before=result["before"], after=result["after"])
            require(expected is None or signature == expected, "throughput engine changed numerical trajectory")
            expected = signature
            require([model.linguistic_observation(row) for row in training+tuning] == observations,
                    "training changed linguistic observations")
            results.append(dict(repetition=repetition, engine=engine, elapsed_seconds=elapsed,
                seconds_per_distinct_training_span=elapsed/len(training), proposals_per_second=PROPOSALS/elapsed,
                training_row_presentations_per_second=PROPOSALS*len(training)/elapsed,
                evaluation_calls=calls, complete_weights_sha256=signature["weights"],
                accepted_updates=PROPOSALS, metrics=compact(result["after"])))
            print(json.dumps(results[-1]), flush=True)
    require(source_hashes == sources(), "producer source changed during benchmark")
    medians = {engine: statistics.median(row["elapsed_seconds"] for row in results if row["engine"] == engine)
               for engine in engines}
    write(directory / "report.json", dict(schema="legacy-prepared-throughput/v1", plan=plan, results=results,
        median_seconds=medians, reference_over_prepared_ratio=medians["reference"]/medians["prepared"],
        paired_reference_over_prepared_ratios=[next(row["elapsed_seconds"] for row in results
             if row["repetition"] == rep and row["engine"] == "reference")/next(row["elapsed_seconds"]
             for row in results if row["repetition"] == rep and row["engine"] == "prepared") for rep in (1,2,3)],
        exact_complete_weight_metric_rate_trajectory=True, trajectory=expected,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024, **FALSE))


def settings():
    return dict(arms=list(ARMS), proposals=PROPOSALS, training_samples=32, tuning_samples=8,
                sealed_evaluation_samples=8, max_training_seconds_per_arm=SECONDS,
                learning_rate=.01, min_learning_rate=.0001, max_learning_rate=.35,
                growth_factors={"fixed_rate": 1.0, "adaptive_rate": 1.5}, shrink_factor=.5,
                max_consecutive_rejections=4, checkpoint_scope="fresh private 8D linguistic core and scheduler")


def guard(directory):
    plan = json.loads((directory / "plan.json").read_text())
    require(plan["source_hashes"] == sources(), "legacy holdout producers changed")
    require(plan["settings"] == settings(), "legacy holdout settings changed")
    require(plan["panel_manifest_sha256"] == current.panel().manifest_sha256, "legacy source panel changed")
    return plan


def fit(directory):
    active, _, prepared, profiles = runtimes()
    source_hashes = sources()
    panel = current.panel()
    directory.mkdir(parents=True, exist_ok=False)
    plan = dict(schema="legacy-prepared-holdout-plan/v1", source_hashes=source_hashes,
        panel_manifest_sha256=panel.manifest_sha256, settings=settings(),
        target_origin="preserved linguistic IR feature-family targets; not independent formula labels",
        evaluation_boundary="sealed sources are not parsed or predicted before all checkpoints freeze",
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
        metric_disk_cache=False, legal_ir_parallel_workers=1, sample_memory=False, temperature=0, **FALSE)
    write(directory / "plan.json", plan)
    initial = profiles.ViewReuseHistoricalDaemonAutoencoder(compute_device="cpu")
    started = time.perf_counter()
    training = build(initial, panel.rows("training"))
    tuning = build(initial, panel.rows("tuning"))
    require(len(training) == 32 and len(tuning) == 8, "legacy development sample count differs")
    observations = [initial.linguistic_observation(row) for row in training+tuning]
    preparation_seconds = time.perf_counter()-started
    initial_state = weights_digest(initial)
    initial.save_training_checkpoint(directory / "untrained")
    development = write(directory / "development-inputs.json", dict(training=[row.to_dict() for row in training],
        tuning=[row.to_dict() for row in tuning], linguistic_observations=observations,
        preparation_seconds=preparation_seconds, **FALSE))
    results = {}
    for arm in ARMS:
        model = profiles.load_training_checkpoint(directory / "untrained", profile="historical_daemon")
        require(weights_digest(model) == initial_state, "legacy arm initialization differs")
        raw_before = prior.reconstruction_observation(model, tuning)
        session = prepared.PreparedFeatureTrainingSession(model, training, validation_samples=tuning,
            proposal_budget=PROPOSALS, growth_factor=plan["settings"]["growth_factors"][arm])
        result, elapsed, calls = measured(session, PROPOSALS, max_seconds=SECONDS)
        require(result["proposal_count"] == PROPOSALS, "legacy arm exhausted bounds before fixed proposal budget")
        require([model.linguistic_observation(row) for row in training+tuning] == observations,
                "legacy training changed linguistic features/IR")
        require(not model.state.family_logits and not model.state.decoded_embeddings and model.formula_checkpoint is None,
                "unexpected sample memory or independent formula head")
        raw_after = prior.reconstruction_observation(model, tuning)
        checkpoint = session.save(directory / (arm+"-session"))
        restored = prepared.load_training_session(checkpoint["path"], expected_sha256=checkpoint["sha256"],
                                                  samples=training, validation_samples=tuning)
        require(restored.state == session.state and weights_digest(restored.model) == weights_digest(model),
                "fitted legacy checkpoint does not restore exact scheduler and complete weights")
        results[arm] = dict(training_seconds=elapsed, seconds_per_distinct_training_span=elapsed/len(training),
            proposals_per_second=PROPOSALS/elapsed, training_row_presentations_per_second=PROPOSALS*len(training)/elapsed,
            evaluation_calls=calls, checkpoint=checkpoint, weights_sha256=weights_digest(model),
            before=compact(result["before"]), after=compact(result["after"]),
            proposal_reports=result["proposal_reports"], accepted_updates=result["accepted_updates"],
            raw_before=raw_before, raw_after=raw_after, raw_reconstruction_unchanged=raw_before == raw_after,
            linguistic_observations_exact=True, scheduler=session.state, **FALSE)
        write(directory / (arm+"-fit.json"), results[arm])
        print(json.dumps(dict(arm=arm, training_seconds=elapsed, accepted_updates=result["accepted_updates"],
                              tuning_cross_entropy=result["after"]["cross_entropy_loss"])), flush=True)
    guard(directory)
    # Pin every saved model/scheduler file before any sealed sample is built.
    files = {str(path.relative_to(directory)): sha(path) for path in directory.rglob("*") if path.is_file()}
    write(directory / "frozen-fits.json", dict(schema="legacy-prepared-frozen-fits/v1", source_hashes=source_hashes,
        files=files, initial_weights_sha256=initial_state, results=results, development_inputs=development,
        candidates_frozen_before_sealed_labels_or_predictions=True, **FALSE))


def frozen(directory):
    guard(directory)
    value = json.loads((directory / "frozen-fits.json").read_text())
    require(value["source_hashes"] == sources() and set(value["results"]) == set(ARMS), "incomplete legacy fit barrier")
    require(value["candidates_frozen_before_sealed_labels_or_predictions"] is True, "legacy candidates not frozen")
    require(all(sha(directory / name) == digest for name, digest in value["files"].items()), "frozen legacy artifact changed")
    return value


def evaluate(directory, *, expected_freeze_sha256):
    require(type(expected_freeze_sha256) is str and sha(directory / "frozen-fits.json") == expected_freeze_sha256,
            "explicit frozen-fit SHA-256 differs")
    require(not (directory / "evaluation-started.json").exists(), "legacy evaluation already started")
    active, _, prepared, profiles = runtimes()
    fits = frozen(directory)
    panel = current.panel()
    initial = profiles.load_training_checkpoint(directory / "untrained", profile="historical_daemon")
    require(weights_digest(initial) == fits["initial_weights_sha256"], "untrained baseline changed")
    development = json.loads((directory / "development-inputs.json").read_text())
    training = build(initial, panel.rows("training"))
    tuning = build(initial, panel.rows("tuning"))
    require([row.to_dict() for row in training] == development["training"]
            and [row.to_dict() for row in tuning] == development["tuning"], "development inputs changed")
    # Validate every source-bound model bundle before generating even the first
    # sealed linguistic target or prediction. All selection choices are frozen.
    models = {"untrained": initial}
    for arm in ARMS:
        restored = prepared.load_training_session(
            directory / (arm+"-session"), expected_sha256=fits["results"][arm]["checkpoint"]["sha256"],
            samples=training, validation_samples=tuning)
        require(restored.state == fits["results"][arm]["scheduler"]
                and weights_digest(restored.model) == fits["results"][arm]["weights_sha256"],
                "frozen legacy model/scheduler differs")
        models[arm] = restored.model
    frozen(directory)
    write(directory / "evaluation-started.json", dict(schema="legacy-prepared-evaluation-started/v1",
        frozen_fit_sha256=expected_freeze_sha256,
        all_checkpoint_bundles_validated_before_sealed_targets=True, **FALSE))
    started = time.perf_counter()
    sealed = build(initial, panel.rows("sealed_evaluation"))
    require(len(sealed) == 8, "sealed legacy count differs")
    observations = [initial.linguistic_observation(row) for row in sealed]
    preparation_seconds = time.perf_counter()-started
    results = {}
    for arm in ("untrained", *ARMS):
        model = models[arm]
        require([model.linguistic_observation(row) for row in sealed] == observations,
                "legacy linguistic observations differ after training")
        before_identity = model.state.state_identity()
        tick = time.perf_counter()
        metrics = active._evaluation(model, sealed).to_dict()
        seconds = time.perf_counter()-tick
        raw_observation = prior.reconstruction_observation(model, sealed)
        require(model.state.state_identity() == before_identity, "sealed evaluation mutated weights")
        results[arm] = dict(metrics=compact(metrics), raw_reconstruction=raw_observation,
            bridge_off_evaluate_seconds=seconds, wall_seconds_per_span=seconds/len(sealed),
            sample_count=len(sealed), linguistic_observations_exact=True, **FALSE)
    frozen(directory)
    write(directory / "sealed-inputs.json", dict(samples=[sample.to_dict() for sample in sealed],
          linguistic_observations=observations, preparation_seconds=preparation_seconds, **FALSE))
    write(directory / "evaluation.json", dict(schema="legacy-prepared-holdout-evaluation/v1",
        frozen_fit_sha256=expected_freeze_sha256, results=results,
        target_origin="preserved linguistic IR feature-family targets; not independent formula labels",
        no_independent_formula_fidelity_claim=True, after_exposure_scope="diagnostic for future tuning",
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
        metric_disk_cache=False, legal_ir_parallel_workers=1, sample_memory=False,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024, **FALSE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("performance", "fit", "evaluate"))
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--expected-freeze-sha256")
    args = parser.parse_args()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"] = "0"
    if args.phase == "evaluate":
        evaluate(args.output_directory.resolve(), expected_freeze_sha256=args.expected_freeze_sha256)
    else:
        globals()[args.phase](args.output_directory.resolve())


if __name__ == "__main__":
    main()
