#!/usr/bin/env python3
"""Predeclared 12-proposal legacy continuation diagnostic, using fresh weights.

Compare uninterrupted training, an intentionally incorrect LR-reset restart,
and source-bound session resume. All inputs are already exposed authored
development fixtures. No independent formula/reconstruction claim is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import compare_legacy_active_training as prior

require, raw, sha, write = prior.require, prior.raw, prior.sha, prior.write
ARMS = ("uninterrupted", "manual_restart_with_rate_reset", "persisted_session_resume")
PROPOSALS = 12
CHUNK = 6
SECONDS = 60


def sources():
    return {**prior.source_hashes(), str(Path(__file__).resolve()): sha(Path(__file__))}


def compact(report):
    return {key: report[key] for key in ("sample_count", "cross_entropy_loss", "cross_entropy_excess_loss",
            "cross_entropy_entropy_loss", "embedding_cosine_similarity", "reconstruction_loss", "legal_ir_target_count")}


def active_history(report, offset=0):
    return [dict(proposal_index=offset + index + 1, learning_rate=row["learning_rate"],
                 accepted=row["accepted"], reason=row["reason"],
                 objective_delta=row.get("objective_delta"), update_norm=row["update_norms"]["update_norm"],
                 cross_entropy_after=row.get("after", {}).get("cross_entropy_loss"))
            for index, row in enumerate(report["epoch_reports"])]


def run(directory):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import active_training as active
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import feature_training_session as sessions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import (
        ViewReuseHistoricalDaemonAutoencoder as Model, load_training_checkpoint,
    )
    pinned = require_workspace_logic_tree()
    source_hashes = sources()
    directory.mkdir(parents=True, exist_ok=False)
    plan = dict(schema="legacy-feature-resume-comparison-plan/v1", source_hashes=source_hashes,
        resolved_logic_tree=pinned, arms=list(ARMS), lifetime_proposals=PROPOSALS, restart_after_proposals=CHUNK,
        max_training_seconds_per_arm=SECONDS, sources=prior.TEXTS,
        initial_learning_rate=.01, max_learning_rate=.35, growth_factor=1.5, shrink_factor=.5,
        max_consecutive_rejections=4, max_line_search_attempts=1,
        comparison_scope="development-only continuation; manual-reset arm intentionally loses scheduler state",
        formula_decoder_unchanged=True, bridge_names=[], legal_ir_target_count=0,
        legal_ir_evaluate_provers=False, metric_disk_cache=False, legal_ir_parallel_workers=1,
        sample_memory=False, temperature=0, independent_evaluation=False, **prior.FALSE)
    write(directory / "plan.json", plan)
    results, initial_identity, initial_inputs, linguistic_before, uninterrupted_state = {}, None, None, None, None
    for arm in ARMS:
        model = Model(compute_device="cpu")
        splits = {split: [model.build_sample(title="authored-feature-diagnostic", section=f"{split}-{index}",
                          text=text, citation=f"authored feature diagnostic:{split}-{index}")
                         for index, text in enumerate(texts)] for split, texts in prior.TEXTS.items()}
        training, tuning = splits["training"], splits["tuning"]
        all_samples = training + tuning
        inputs = [sample.to_dict() for sample in all_samples]
        identity = model.state.state_identity()
        observations = [model.linguistic_observation(sample) for sample in all_samples]
        require(initial_identity is None or identity == initial_identity, "arm initialization differs")
        require(initial_inputs is None or inputs == initial_inputs, "arm source inputs differ")
        require(linguistic_before is None or observations == linguistic_before, "arm codec output differs")
        initial_identity, initial_inputs, linguistic_before = identity, inputs, observations
        raw_before = prior.reconstruction_observation(model, tuning)
        training_seconds = save_seconds = load_seconds = 0.0
        checkpoint = None
        histories = []
        reports = []
        kwargs = dict(validation_samples=tuning, learning_rate=.01, growth_factor=1.5,
                      max_line_search_attempts=1)
        if arm == "uninterrupted":
            tick = time.perf_counter()
            first = active.train_active_family_features(model, training, epochs=PROPOSALS,
                                                        max_seconds=SECONDS, **kwargs)
            training_seconds += time.perf_counter() - tick
            reports.append(first)
            histories.extend(active_history(first))
            next_rate = first["next_learning_rate"]
            terminal = "proposal_budget" if first["proposal_count"] == PROPOSALS else first["stopped_reason"]
        elif arm == "manual_restart_with_rate_reset":
            tick = time.perf_counter()
            first = active.train_active_family_features(model, training, epochs=CHUNK,
                                                        max_seconds=SECONDS, **kwargs)
            training_seconds += time.perf_counter() - tick
            reports.append(first)
            histories.extend(active_history(first))
            tick = time.perf_counter()
            saved = model.save_training_checkpoint(directory / "manual-model-checkpoint")
            save_seconds = time.perf_counter() - tick
            checkpoint = dict(path=str(directory / "manual-model-checkpoint"), core_bytes=saved["core_bytes"],
                              core_sha256=saved["core_sha256"], saved_next_rate_ignored=first["next_learning_rate"])
            tick = time.perf_counter()
            model = load_training_checkpoint(directory / "manual-model-checkpoint", profile="historical_daemon")
            load_seconds = time.perf_counter() - tick
            require(training_seconds < SECONDS, "manual arm exhausted training deadline before continuation")
            tick = time.perf_counter()
            second = active.train_active_family_features(model, training, epochs=CHUNK,
                max_seconds=SECONDS-training_seconds, **kwargs)
            training_seconds += time.perf_counter() - tick
            reports.append(second)
            histories.extend(active_history(second, CHUNK))
            next_rate = second["next_learning_rate"]
            terminal = "proposal_budget" if len(histories) == PROPOSALS else second["stopped_reason"]
        else:
            session = sessions.FeatureTrainingSession(model, training, validation_samples=tuning,
                                                       proposal_budget=PROPOSALS)
            tick = time.perf_counter()
            first = session.advance(max_proposals=CHUNK, max_seconds=SECONDS)
            training_seconds += time.perf_counter() - tick
            reports.append(first)
            histories.extend(first["proposal_reports"])
            tick = time.perf_counter()
            checkpoint = session.save(directory / "feature-session-checkpoint")
            save_seconds = time.perf_counter() - tick
            tick = time.perf_counter()
            restored = sessions.load_training_session(checkpoint["path"], expected_sha256=checkpoint["sha256"],
                                                       samples=training, validation_samples=tuning)
            load_seconds = time.perf_counter() - tick
            require(restored.state == session.state, "checkpoint lost scheduler state")
            require(training_seconds < SECONDS, "session exhausted training deadline before continuation")
            tick = time.perf_counter()
            second = restored.advance(max_proposals=CHUNK, max_seconds=SECONDS-training_seconds)
            training_seconds += time.perf_counter() - tick
            reports.append(second)
            histories.extend(second["proposal_reports"])
            model = restored.model
            next_rate = restored.state["progress"]["next_learning_rate"]
            terminal = restored.state["progress"]["terminal_reason"]
            exhausted = restored.advance(max_proposals=1, max_seconds=1)
            require(exhausted["proposal_count"] == 0 and exhausted["stopped_reason"] == "proposal_budget",
                    "resumed lifetime budget was replenished")
        require(len(histories) == PROPOSALS, "arm did not complete the predeclared 12-proposal comparison")
        require([model.linguistic_observation(sample) for sample in all_samples] == observations,
                "numerical training changed linguistic IR/features")
        require(not model.state.family_logits and not model.state.decoded_embeddings and model.formula_checkpoint is None,
                "sample memory or formula head unexpectedly used")
        raw_after = prior.reconstruction_observation(model, tuning)
        tick = time.perf_counter()
        live = model.evaluate(tuning, **active._EVALUATE).to_dict()
        evaluate_seconds = time.perf_counter() - tick
        require(live == reports[-1]["after"], "saved accepted metric disagrees with live model")
        state_bytes = raw(model.state.to_dict())
        if arm == "uninterrupted":
            uninterrupted_state = state_bytes
        if arm == "persisted_session_resume":
            require(state_bytes == uninterrupted_state, "session resume differs from uninterrupted complete weights")
            require(compact(live) == results["uninterrupted"]["after"], "session resume metrics differ")
        result = dict(before=compact(reports[0]["before"]), after=compact(live), proposal_history=histories,
            proposals=len(histories), accepted_updates=sum(row["accepted"] for row in histories),
            next_learning_rate=next_rate, terminal_reason=terminal,
            training_seconds=training_seconds, training_seconds_per_distinct_training_span=training_seconds/len(training),
            checkpoint_save_seconds=save_seconds, checkpoint_load_seconds=load_seconds, checkpoint=checkpoint,
            bridge_off_evaluate_seconds=evaluate_seconds, bridge_off_evaluate_seconds_per_span=evaluate_seconds/len(tuning),
            complete_weights_sha256=hashlib.sha256(state_bytes).hexdigest(),
            initial_state_identity=initial_identity, final_state_identity=model.state.state_identity(),
            raw_reconstruction_before=raw_before, raw_reconstruction_after=raw_after,
            linguistic_observations_exact=True, sample_memory_empty=True,
            raw_reconstruction_unchanged=raw_before == raw_after,
            current_rss_bytes=prior.resident_bytes(), **prior.FALSE)
        results[arm] = result
        write(directory / (arm + ".json"), result)
        print(json.dumps(dict(arm=arm, proposals=result["proposals"], accepted=result["accepted_updates"],
                             ce=result["after"]["cross_entropy_loss"], training_seconds=training_seconds)), flush=True)
    require(sources() == source_hashes, "producer sources changed during comparison")
    input_reference = write(directory / "inputs.json", initial_inputs)
    linguistic_reference = write(directory / "linguistic-observations.json", linguistic_before)
    summary = dict(schema="legacy-feature-resume-comparison/v1", plan=plan, results=results,
        inputs=input_reference, linguistic_observations=linguistic_reference,
        resumed_weights_and_metrics_equal_uninterrupted=True, persisted_lifetime_budget_enforced=True,
        learned_formula_or_raw_reconstruction_improvement_claimed=False,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        bridge_on_evaluate=None, legal_ir_target_count=0, **prior.FALSE)
    write(directory / "report.json", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"] = "0"
    run(args.output_directory.resolve())


if __name__ == "__main__":
    main()
