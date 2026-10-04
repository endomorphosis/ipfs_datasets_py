#!/usr/bin/env python3
"""Add a frozen structured decoder arm before exposing a source-v2 holdout.

The baseline experiment remains immutable. This script seals additional models
against its development artifacts, then opens the shared test exactly once.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
BASELINE = Path(__file__).with_name("benchmark_source_training_v2.py")
spec = importlib.util.spec_from_file_location("source_v2_benchmark", BASELINE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def read(path):
    return json.loads(Path(path).read_bytes())


def guard_baseline(folder, expected):
    prepared = base.guard_preparation(folder)
    if base.sha(folder / "freeze.json") != expected:
        raise ValueError("baseline freeze SHA differs")
    for name, digest in read(folder / "freeze.json").items():
        if base.sha(folder / name) != digest:
            raise ValueError("frozen baseline artifact changed: " + name)
    from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2
    if read(folder / "plan.json")["producer"] != base.pins(source_training_v2):
        raise ValueError("baseline producer changed")
    return prepared


def producer(trainer):
    return {"driver_sha256": base.sha(Path(__file__).resolve()),
            "baseline_driver_sha256": base.sha(BASELINE),
            "runtime": trainer._implementation()}


def fit(folder, output, baseline_sha):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as trainer
    prepared = guard_baseline(folder, baseline_sha)
    if output.exists() or (folder / "evaluation-started.json").exists():
        raise ValueError("fresh structured directory and unopened baseline holdout required")
    settings = {"ridges": list(trainer.RIDGES), "embedding_provenance": prepared["source_embeddings"]}
    base.save(output / "plan.json", dict(schema="structured-source-composition-plan/v1",
        baseline_directory=str(folder), baseline_freeze_sha256=baseline_sha,
        producer=producer(trainer), config=settings, test_used_for_selection=False,
        scope="fixed typed tree, training scalar vocabulary; new field combinations",
        source_input_contract="same genuine GTE384 vectors as all baseline arms",
        timing_repetitions=5, timing_scope="warm target-free inference, includes native validation",
        ablations=["zero_head", "zero_projection", "shuffle_embeddings"]))
    fits = []
    for domain in base.DOMAINS:
        training, tuning = [base.model_rows(base.inputs(folder, domain, part))
                            for part in ("train", "validation")]
        tick = time.perf_counter()
        result = trainer.train(domain, training, tuning,
            parent_projection=prepared["parent"], config=settings)
        seconds = time.perf_counter() - tick
        checkpoint = base.save(output / domain / "checkpoint.json", result["checkpoint"])
        development = base.save(output / domain / "development.json", {
            part: trainer.evaluate(result["checkpoint"], rows)
            for part, rows in (("train", training), ("validation", tuning))})
        fit = dict(domain=domain, arm="structured", checkpoint=checkpoint,
            full_fit_seconds=seconds, unique_training_rows=len(training),
            full_fit_unique_rows_per_second=len(training) / seconds,
            metrics=result["metrics"], development=development)
        fits.append(fit)
        print(json.dumps({"domain": domain, "full_fit_seconds": seconds,
                          "tuning": result["metrics"]["selected_validation"]}), flush=True)
    guard_baseline(folder, baseline_sha)
    base.save(output / "fits.json", fits)
    frozen = base.save(output / "freeze.json", {
        str(path.relative_to(output)): base.sha(path) for path in output.rglob("*.json")})
    print(json.dumps({"structured_freeze": frozen}), flush=True)


def timed_inference(module, checkpoint, rows, repeats):
    runtime = module.Runtime(checkpoint)
    inputs = base.model_rows(rows, targets=False)
    runtime.infer(inputs)
    samples = []
    for _ in range(repeats):
        tick = time.perf_counter()
        runtime.infer(inputs)
        samples.append(time.perf_counter() - tick)
    median = statistics.median(samples)
    return dict(samples_seconds=samples, median_seconds=median,
                rows_per_second=len(inputs) / median, count=len(inputs),
                includes_embedding=False, includes_loading=False, includes_validation=True)


def evaluate(output, expected):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as structured
    from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2 as sequence
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as previous
    if base.sha(output / "freeze.json") != expected:
        raise ValueError("structured freeze SHA differs")
    for name, digest in read(output / "freeze.json").items():
        if base.sha(output / name) != digest:
            raise ValueError("structured artifact changed: " + name)
    plan = read(output / "plan.json")
    if plan["producer"] != producer(structured):
        raise ValueError("structured producer changed")
    folder = Path(plan["baseline_directory"])
    guard_baseline(folder, plan["baseline_freeze_sha256"])
    base.save(output / "evaluation-started.json", {"all_candidates_frozen": True})
    # The baseline driver creates and embeds heldouts only after both freezes.
    base.evaluate(folder, plan["baseline_freeze_sha256"])
    comparisons = []
    for fit in read(output / "fits.json"):
        domain = fit["domain"]
        checkpoint = read(fit["checkpoint"]["path"])
        results = {}
        for partition in ("test", "canary"):
            rows = base.model_rows(base.inputs(folder, domain, partition))
            results[partition] = structured.evaluate(checkpoint, rows)
        rows = base.inputs(folder, domain, "test")
        ablations = {name: structured.evaluate(checkpoint, base.model_rows(rows), weight_ablation=name)
                     for name in plan["ablations"]}
        inference = timed_inference(structured, checkpoint, rows, plan["timing_repetitions"])
        artifact = base.save(output / domain / "evaluation.json", dict(results=results,
            ablations=ablations, inference=inference))
        comparisons.append(dict(domain=domain, arm="structured", full_fit_seconds=fit["full_fit_seconds"],
            full_fit_unique_rows_per_second=fit["full_fit_unique_rows_per_second"], inference=inference,
            results={part: {key: value for key, value in report.items() if key != "rows"}
                     for part, report in results.items()},
            ablations={name: {key: value for key, value in report.items() if key != "rows"}
                       for name, report in ablations.items()}, artifact=artifact))
        print(json.dumps({"domain": domain, "arm": "structured", "test_exact": results["test"]["exact_targets"],
                          "canary_exact": results["canary"]["exact_targets"]}), flush=True)
    baseline_results = {(row["domain"], row["arm"], row["seed"]): row
                        for row in read(folder / "evaluation.json")["rows"]}
    for fit in read(folder / "fits.json"):
        module = previous if fit["arm"] == "native_v1" else sequence
        checkpoint = read(fit["checkpoint"]["path"])
        rows = base.inputs(folder, fit["domain"], "test")
        results = baseline_results[fit["domain"], fit["arm"], fit["seed"]]["results"]
        comparisons.append(dict(domain=fit["domain"], arm=fit["arm"], seed=fit["seed"],
            full_fit_seconds=fit["full_fit_seconds"], full_fit_unique_rows_per_second=180 / fit["full_fit_seconds"],
            inference=timed_inference(module, checkpoint, rows, plan["timing_repetitions"]),
            results={part: {key: value for key, value in report.items() if key != "rows"}
                     for part, report in results.items()}))
    base.save(output / "report.json", dict(schema="source-composition-comparison/v3", comparisons=comparisons,
        baseline_freeze_sha256=plan["baseline_freeze_sha256"], structured_freeze_sha256=expected,
        source_input_contract=plan["source_input_contract"], heldout_groups_per_domain=5,
        canary_groups_shared_with_test=True, source_semantics_verified=False, proof_authority=False,
        checkpoints_promoted=False, embedding=read(folder / "preparation.json")["source_embeddings"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("fit", "evaluate"))
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--baseline-directory", type=Path)
    parser.add_argument("--baseline-freeze-sha256")
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args()
    if args.phase == "fit":
        fit(args.baseline_directory.resolve(), args.output_directory.resolve(), args.baseline_freeze_sha256)
    else:
        evaluate(args.output_directory.resolve(), args.freeze_sha256)
