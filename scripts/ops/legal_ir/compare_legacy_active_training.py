#!/usr/bin/env python3
"""Bounded numerical-feature experiment on fresh historical 8D models.

No archived teacher is loaded, changed or downloaded. Every arm shares the old
linguistic codec and strict objective. Reconstruction is target-aware; family
loss improvements are not independent text/formula reconstruction evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
BASE = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
EPOCHS = 6
RATE = .01
ARMS = ("original_cap1", "original_cap3", "active_fixed", "active_adaptive")
TEXTS = {
    "training": ("The agency shall submit reports.",
                 "The agency shall not disclose records.",
                 "The officer shall retain the file for at least 20 days."),
    "tuning": ("The board shall submit notices.",
               "The board shall not disclose documents.",
               "The clerk shall retain records for at least 20 days."),
}
FALSE = dict(admitted=False, formalized=False, roundtrip_ok=False, qualified=False,
             proof_authority=False, semantic_correctness_verified=False,
             independent_generalization_verified=False, formula_training_executed=False,
             lake_executed=False, teacher_weights_loaded=False, promotion_performed=False,
             publication_performed=False)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(raw(value))
    return {"path": str(Path(path).resolve()), "sha256": sha(path), "bytes": Path(path).stat().st_size}


def source_hashes():
    paths = [Path(__file__), BASE / "modal_joint_formula.py", BASE / "autoencoder_lineages/_contract.py"]
    paths.extend((BASE / "autoencoder_lineages/legacy_v1").rglob("*.py"))
    paths.extend((BASE / "autoencoder_lineages/legacy_v1").rglob("MANIFEST.json"))
    paths.extend(ROOT / "ipfs_datasets_py" / name for name in (
        "logic/deontic/utils/deontic_parser.py", "logic/legal_ir/canonical_compiler.py",
        "logic/legal_ir/canonical_decompiler.py", "logic/autoformal/__init__.py"))
    return {str(path.resolve()): sha(path) for path in sorted(set(paths))}


def resident_bytes():
    fields = Path("/proc/self/statm").read_text().split()
    return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")


def reconstruction_observation(model, samples):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_joint_formula import raw_projection
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1._snapshot import modal_autoencoder as numerical
    before = model.state.state_identity()
    rows = []
    for sample in samples:
        vector = raw_projection(model, sample)
        rows.append(dict(sample_id=sample.sample_id, raw_vector=vector,
                         raw_mse=numerical.mse_loss(sample.embedding_vector, vector),
                         raw_cosine=numerical.cosine_similarity(sample.embedding_vector, vector)))
    require(model.state.state_identity() == before, "read-only reconstruction observation mutated weights")
    return dict(rows=rows, mean_raw_mse=sum(row["raw_mse"] for row in rows) / len(rows),
                mean_raw_cosine=sum(row["raw_cosine"] for row in rows) / len(rows),
                scope="pre-safety additive vector versus deterministic linguistic hash; not independent semantic embedding")


def run(directory):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import active_training as active
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import (
        ViewReuseHistoricalDaemonAutoencoder as Model, load_training_checkpoint,
    )
    pinned = require_workspace_logic_tree()
    sources = source_hashes()
    directory.mkdir(parents=True, exist_ok=False)
    plan = dict(schema="legacy-active-feature-comparison-plan/v1", source_hashes=sources,
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        resolved_logic_tree=pinned, sources=TEXTS, arms=list(ARMS), epochs=EPOCHS,
        initial_learning_rate=RATE, max_seconds_per_arm=60, max_line_search_attempts=1,
        adaptive_growth_factor=1.5, max_learning_rate=.35,
        objective="unchanged historical strict family CE plus target-aware reconstruction",
        model="fresh historical daemon 8D, blank English, original defaults, CPU",
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
        metric_disk_cache=False, legal_ir_parallel_workers=1, sample_memory=False,
        temperature=0, no_weight_downloads=True, **FALSE)
    write(directory / "plan.json", plan)
    results, states = {}, {}
    initial_identity = source_samples = observations = None
    last = None
    for arm in ARMS:
        model = Model(compute_device="cpu")
        splits = {split: [model.build_sample(title="authored-feature-diagnostic", section=f"{split}-{index}",
                     text=text, citation=f"authored feature diagnostic:{split}-{index}")
                         for index, text in enumerate(texts)] for split, texts in TEXTS.items()}
        all_samples = splits["training"] + splits["tuning"]
        identity = model.state.state_identity()
        inputs = [sample.to_dict() for sample in all_samples]
        linguistic = [model.linguistic_observation(sample) for sample in all_samples]
        require(initial_identity is None or identity == initial_identity, "arm initialization differs")
        require(source_samples is None or inputs == source_samples, "arm inputs differ")
        require(observations is None or linguistic == observations, "arm linguistic profile differs")
        initial_identity, source_samples, observations = identity, inputs, linguistic
        raw_before = reconstruction_observation(model, splits["tuning"])
        memory_before = resident_bytes()
        tick = time.perf_counter()
        if arm.startswith("original"):
            report = model.train_generalizable_projection(splits["training"], validation_samples=splits["tuning"],
                epochs=EPOCHS, learning_rate=RATE, max_seconds=60, max_line_search_attempts=1,
                projection_max_update_families=1 if arm == "original_cap1" else 3,
                projection_update_backend="python_sparse_batch", legal_ir_bridge_names=(),
                legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
            proposals = sum(row["line_search_attempt_count"] for epoch in report["epoch_reports"]
                            for row in epoch["candidate_reports"])
        else:
            report = active.train_active_family_features(model, splits["training"], validation_samples=splits["tuning"],
                epochs=EPOCHS, learning_rate=RATE, growth_factor=1.5 if arm == "active_adaptive" else 1.0,
                max_seconds=60, max_line_search_attempts=1)
            proposals = report["proposal_count"]
        seconds = time.perf_counter() - tick
        after_observations = [model.linguistic_observation(sample) for sample in all_samples]
        require(after_observations == linguistic, "training changed deterministic linguistic IR/features")
        require(not model.state.family_logits and not model.state.decoded_embeddings, "sample memory was updated")
        require(model.formula_checkpoint is None, "formula head was attached to historical profile")
        raw_after = reconstruction_observation(model, splits["tuning"])
        tick = time.perf_counter()
        evaluation = model.evaluate(splits["tuning"], **active._EVALUATE)
        evaluate_seconds = time.perf_counter() - tick
        require(evaluation.to_dict() == report["after"], "returned accepted evaluation differs from live weights")
        result = dict(report=report, proposals=proposals, training_wall_seconds=seconds,
            training_wall_seconds_per_training_span=seconds / len(splits["training"]),
            bridge_off_evaluate_wall_seconds=evaluate_seconds,
            bridge_off_evaluate_wall_seconds_per_span=evaluate_seconds / len(splits["tuning"]),
            resident_bytes_before_training=memory_before, resident_bytes_after_training=resident_bytes(),
            initial_state_identity=identity, final_state_identity=model.state.state_identity(),
            linguistic_observations_exact=True, sample_memory_empty=True,
            raw_reconstruction_before=raw_before, raw_reconstruction_after=raw_after,
            raw_reconstruction_unchanged=raw_before == raw_after,
            family_cross_entropy_delta=report["before"]["cross_entropy_loss"]-report["after"]["cross_entropy_loss"],
            numeric_sparse_weights_changed=model.state.state_identity() != identity,
            **FALSE)
        write(directory / (arm + ".json"), result)
        results[arm], states[arm] = result, model.state.to_dict()
        print(json.dumps(dict(arm=arm, accepted_epochs=report["accepted_epochs"], proposals=proposals,
                             seconds=seconds, family_ce_delta=result["family_cross_entropy_delta"])), flush=True)
        last = model, splits
    require(states["original_cap3"] == states["active_fixed"],
            "fixed active schedule differs from the old accepted family-update state")
    require(results["original_cap1"]["report"]["accepted_epochs"] == 0,
            "cap-one starvation was not reproduced; inspect observed result")
    model, splits = last
    checkpoint = directory / "active-adaptive-training-checkpoint"
    model.save_training_checkpoint(checkpoint)
    first = load_training_checkpoint(checkpoint, profile="historical_daemon")
    second = load_training_checkpoint(checkpoint, profile="historical_daemon")
    require(first.encode(splits["tuning"][0]) == second.encode(splits["tuning"][0]), "reload predictions differ")
    rate = results["active_adaptive"]["report"]["next_learning_rate"]
    resume = dict(epochs=1, learning_rate=rate, max_seconds=60, max_line_search_attempts=1)
    a = active.train_active_family_features(first, splits["training"], validation_samples=splits["tuning"], **resume)
    b = active.train_active_family_features(second, splits["training"], validation_samples=splits["tuning"], **resume)
    require(first.state.to_dict() == second.state.to_dict() and a["after"] == b["after"]
            and a["next_learning_rate"] == b["next_learning_rate"], "resumed helper diverged")
    require(source_hashes() == sources, "producer source changed during comparison")
    summary = dict(schema="legacy-active-feature-comparison/v1", plan=plan, results=results,
        inputs=source_samples, linguistic_observations=observations,
        active_fixed_matches_original_cap3_complete_weights=True,
        historical_checkpoint_format_preserved=True, independent_reload_resume_exact=True,
        explicit_resume_learning_rate=rate, resume_checks_excluded_from_arm_metrics=True,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        bridge_on_evaluate=None, legal_ir_target_count=0,
        scope="authored in-development feature diagnostic; tuning selects updates; no independent evaluation",
        **FALSE)
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
