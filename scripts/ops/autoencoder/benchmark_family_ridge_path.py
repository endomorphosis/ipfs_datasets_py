#!/usr/bin/env python3
"""Freeze four-domain training before evaluating fresh authored holdouts.

Runs the existing prepared Adam trainer and the regularization-path candidate
on identical native targets/vocabularies. Rates count unique training rows per
complete fit second, never fictitious optimizer steps for a closed-form fit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as old_panel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_prepared as baseline
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_ridge_path as candidate


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw(value))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_panel(directory):
    path = directory / "authored_panel.py"
    spec = importlib.util.spec_from_file_location(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer._ridge_comparison_panel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(directory):
    if directory.exists():
        raise ValueError("fresh experiment directory required")
    directory.mkdir(parents=True)
    # Preserve the exact existing native builders in a separately pinned fixture
    # module. Only the source vocabulary, panel ID and panel size differ.
    source = Path(old_panel.__file__).read_text()
    replacements = {
        'authored-domain-reconstruction-panel/v1': 'authored-domain-ridge-holdout/v1',
        'ACTORS = ("custodian", "registrar", "inspector", "operator")':
            'ACTORS = ("archivist", "curator", "librarian", "steward", "reviewer", "examiner")',
        'ACTIONS = ("archive", "inspect", "publish", "verify", "transmit")':
            'ACTIONS = ("index", "classify", "retain", "catalog", "sign", "recover", "audit")',
        'OBJECTS = ("ledger", "manifest", "dossier", "register")':
            'OBJECTS = ("receipt", "certificate", "directory", "schedule", "journal", "inventory")',
        'range(4)': 'range(6)', 'range(5)': 'range(7)',
        '"independent_test_groups_per_domain": 4': '"independent_test_groups_per_domain": 6',
    }
    for before, after in replacements.items():
        if before not in source:
            raise ValueError("native fixture source changed: " + before)
        source = source.replace(before, after)
    (directory / "authored_panel.py").write_text(source)
    panel = load_panel(directory)
    save(directory / "plan.json", {
        "schema": "family-ridge-path-comparison/v1", "domains": list(panel.DOMAINS),
        "seeds": [1729, 1730, 1731], "epochs": 24, "patience": 24,
        "latent_width": 8, "minibatch_size": 6,
        "ridges": [.0001, .001, .01, .1], "shrinkages": [.25, .5, 1.],
        "heldout_used_for_selection": False, "authored_known_vocabulary_compositions": True,
        "independent_real_corpus": False,
        "source_hashes": {str(Path(module.__file__).resolve()): digest(Path(module.__file__))
            for module in (baseline, candidate, old_panel)},
        "fixture_sha256": digest(directory / "authored_panel.py")})
    for domain in panel.DOMAINS:
        save(directory / domain / "development.json", {
            "training": panel.prepare_partition(domain, "train"),
            "validation": panel.prepare_partition(domain, "validation")})


def guard(directory):
    plan = json.loads((directory / "plan.json").read_bytes())
    if any(digest(Path(name)) != sha for name, sha in plan["source_hashes"].items()):
        raise ValueError("training implementation changed")
    if digest(directory / "authored_panel.py") != plan["fixture_sha256"]:
        raise ValueError("fixture changed")
    return plan


def fit(directory):
    plan = guard(directory)
    save(directory / "fit-started.json", {"one_attempt": True})
    fits = []
    for domain in plan["domains"]:
        data = json.loads((directory / domain / "development.json").read_bytes())
        # Warm both execution paths before the alternating timed comparison.
        baseline.train_family_projection_autoencoder_prepared(data["training"], data["validation"],
            output_dir=directory / domain / "warmup", epochs=1, patience=1, latent_width=8)
        candidate.train_family_ridge_path(data["training"], data["validation"],
            output_dir=directory / domain / "warmup-ridge", latent_width=8)
        for index, seed in enumerate(plan["seeds"]):
            for arm in (("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")):
                started = time.perf_counter()
                destination = directory / domain / f"{arm}-{seed}"
                if arm == "baseline":
                    result = baseline.train_family_projection_autoencoder_prepared(data["training"], data["validation"],
                        output_dir=destination, epochs=plan["epochs"], patience=plan["patience"],
                        latent_width=8, minibatch_size=6, seed=seed)
                else:
                    result = candidate.train_family_ridge_path(data["training"], data["validation"],
                        output_dir=destination, latent_width=8, ridges=plan["ridges"], shrinkages=plan["shrinkages"])
                seconds = time.perf_counter() - started
                fits.append({"domain": domain, "arm": arm, "seed": seed, "result": result,
                    "full_fit_seconds": seconds, "unique_training_rows_per_second": len(data["training"]) / seconds})
                print(json.dumps({"domain": domain, "arm": arm, "seed": seed, "seconds": seconds}), flush=True)
    guard(directory)
    save(directory / "fits.json", fits)
    save(directory / "freeze.json", {str(path.relative_to(directory)): digest(path)
        for path in sorted(directory.rglob("*")) if path.is_file() and "__pycache__" not in path.parts})
    print(json.dumps({"freeze_sha256": digest(directory / "freeze.json")}), flush=True)


def evaluate(directory, freeze_sha256):
    plan = guard(directory)
    if digest(directory / "freeze.json") != freeze_sha256:
        raise ValueError("explicit frozen-model digest required")
    freeze = json.loads((directory / "freeze.json").read_bytes())
    if any(digest(directory / name) != sha for name, sha in freeze.items()):
        raise ValueError("frozen experiment changed")
    save(directory / "evaluation-started.json", {"heldout_now_exposed": True})
    panel = load_panel(directory)
    fits = json.loads((directory / "fits.json").read_bytes())
    results = {}
    for domain in plan["domains"]:
        heldout = panel.prepare_partition(domain, "test")
        save(directory / domain / "heldout.json", heldout)
        arms = {}
        for arm in ("baseline", "candidate"):
            selected = [row for row in fits if row["domain"] == domain and row["arm"] == arm]
            scores = []
            for row in selected:
                infer = baseline.infer_family_projection_autoencoder_prepared if arm == "baseline" else candidate.infer_family_ridge_path
                score = infer(row["result"]["descriptor"], heldout)
                save(directory / domain / f"{arm}-{row['seed']}-heldout.json", score)
                scores.append(score)
            arms[arm] = {"heldout_objective_mean": statistics.mean(s["objective"] for s in scores),
                "heldout_family_means": {family: statistics.mean(s["families"][family] for s in scores)
                    for family in scores[0]["families"]},
                "full_fit_seconds_median": statistics.median(r["full_fit_seconds"] for r in selected),
                "unique_training_rows_per_second_median": statistics.median(r["unique_training_rows_per_second"] for r in selected)}
        before, after = arms["baseline"], arms["candidate"]
        regressions = sorted(f for f, value in after["heldout_family_means"].items()
            if value > before["heldout_family_means"][f] + 1e-12)
        results[domain] = {**arms,
            "heldout_relative_reduction": 1 - after["heldout_objective_mean"] / before["heldout_objective_mean"],
            "full_fit_speedup": before["full_fit_seconds_median"] / after["full_fit_seconds_median"],
            "regressed_families": regressions,
            "eligible_on_this_panel": not regressions and after["heldout_objective_mean"] < before["heldout_objective_mean"],
            "promoted": False, "test_groups": 6, "test_rows": len(heldout)}
    guard(directory)
    report = {"domains": results, "source_decoder_trained": False, "heldout_used_for_selection": False,
              "proof_authority": False, "weights_promoted": False, "holdout_now_exposed": True,
              "scope": "authored structural reconstruction comparison, not source text decoding"}
    save(directory / "report.json", report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "fit", "evaluate"))
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    if args.phase == "prepare": prepare(directory)
    elif args.phase == "fit": fit(directory)
    else: evaluate(directory, args.freeze_sha256)


if __name__ == "__main__":
    main()
