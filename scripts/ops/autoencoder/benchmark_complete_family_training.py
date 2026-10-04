"""Prepare, freeze and once-only evaluate complete-family structural training."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import sys
REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURES = REPOSITORY / "tests/fixtures/logic/complete_family_panel_v1"
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(FIXTURES))
import full_family_panel as panel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_training as trainer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_features as features

ROOT = FIXTURES
RUN = None


def raw(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream: stream.write(raw(value))


def pins():
    helpers = (panel.fixtures, panel.fixtures.fixtures, panel.fixtures.fixtures._security,
               panel.fixtures.protocol_fixtures, panel.fixtures.concurrency_fixtures)
    return {str(path): sha(path) for path in (Path(__file__).resolve(), ROOT / "fresh_panel.py",
        ROOT / "full_family_panel.py", Path(trainer.__file__), Path(features.__file__),
        *(Path(module.__file__) for module in helpers))}


def guard():
    plan = json.loads((RUN / "plan.json").read_bytes())
    assert plan["pins"] == pins(), "comparison source changed"
    return plan


def prepare():
    assert not RUN.exists(), "fresh run required"
    save(RUN / "plan.json", {"pins": pins(), "seeds": [1729, 1730, 1731], "epochs": 24,
        "latent_width": 8, "minibatch_size": 6, "selection_on_test": False,
        "corpus": "new authored actor/action compositions with explicit supplemental models",
        "source_model_correspondence_proved": False, "supplemental_fixture_structures_reused": True,
        "independent_test_groups": 7, "training_rows": 84, "tuning_rows": 14, "test_rows": 14})
    for domain in panel.base.DOMAINS:
        data = {split: panel.prepare_partition(domain, split) for split in ("train", "validation")}
        coverage = {split: panel.coverage(rows) for split, rows in data.items()}
        for split, counts in coverage.items():
            assert set(counts) == panel.EXPECTED[domain], (domain, split, sorted(set(counts)), sorted(panel.EXPECTED[domain]))
        prepared = features.prepare(data["train"], data["validation"])
        save(RUN / domain / "development.json", data)
        save(RUN / domain / "coverage.json", {"families": coverage,
            "feature_count": len(prepared["space"]["columns"]),
            "training_coverage": prepared["training_coverage"], "validation_coverage": prepared["validation_coverage"],
            "training_atoms_pruned": 0,
            "distinct_payloads_per_family": {split: {family: len({hashlib.sha256(raw(target["payload"])).hexdigest()
                for row in rows for target in row["projections"] if target["ready_for_training"] and target["logic_family"] == family})
                for family in panel.EXPECTED[domain]} for split, rows in data.items()}})
        print(json.dumps({"domain": domain, "features": len(prepared["space"]["columns"]), "families": len(coverage["train"])}), flush=True)


def fit():
    plan = guard()
    save(RUN / "fit-started.json", {"once": True})
    fits = []
    for domain in panel.base.DOMAINS:
        data = json.loads((RUN / domain / "development.json").read_bytes())
        for strategy in ("adam", "ridge_path"):
            trainer.train_complete_family_autoencoder(data["train"], data["validation"],
                output_dir=RUN / domain / ("warmup-" + strategy), strategy=strategy, epochs=1,
                required_families=sorted(panel.EXPECTED[domain]))
        for index, seed in enumerate(plan["seeds"]):
            for strategy in (("adam", "ridge_path") if index % 2 == 0 else ("ridge_path", "adam")):
                started = time.perf_counter()
                fitted = trainer.train_complete_family_autoencoder(data["train"], data["validation"],
                    output_dir=RUN / domain / f"{strategy}-{seed}", strategy=strategy, epochs=plan["epochs"],
                    latent_width=plan["latent_width"], minibatch_size=plan["minibatch_size"], seed=seed,
                    required_families=sorted(panel.EXPECTED[domain]))
                elapsed = time.perf_counter() - started
                fits.append({"domain": domain, "strategy": strategy, "seed": seed, "result": fitted,
                             "full_fit_seconds": elapsed, "unique_train_rows_per_second": len(data["train"]) / elapsed})
                print(json.dumps({"domain": domain, "strategy": strategy, "seed": seed, "seconds": elapsed}), flush=True)
    guard()
    save(RUN / "fits.json", fits)
    save(RUN / "freeze.json", {str(path.relative_to(RUN)): sha(path) for path in sorted(RUN.rglob("*")) if path.is_file()})
    print(json.dumps({"freeze_sha256": sha(RUN / "freeze.json")}), flush=True)


def evaluate(digest):
    plan = guard()
    assert digest == sha(RUN / "freeze.json"), "explicit full freeze SHA required"
    for name, value in json.loads((RUN / "freeze.json").read_bytes()).items():
        assert sha(RUN / name) == value, "frozen input changed"
    save(RUN / "evaluation-started.json", {"heldout_now_exposed": True})
    fits = json.loads((RUN / "fits.json").read_bytes())
    output = {}
    for domain in panel.base.DOMAINS:
        heldout = panel.prepare_partition(domain, "test")
        counts = panel.coverage(heldout)
        assert set(counts) == panel.EXPECTED[domain], "heldout native family floor incomplete"
        save(RUN / domain / "heldout.json", heldout)
        summary = {}
        feature_spaces = set()
        for strategy in ("adam", "ridge_path"):
            selected = [row for row in fits if row["domain"] == domain and row["strategy"] == strategy]
            scores = []
            for row in selected:
                saved, _ = trainer.load_complete_family_checkpoint(row["result"]["descriptor"])
                feature_spaces.add(hashlib.sha256(raw(saved["space"])).hexdigest())
                result = trainer.infer_complete_family_autoencoder(row["result"]["descriptor"], heldout)
                save(RUN / domain / f"{strategy}-{row['seed']}-heldout.json", result)
                scores.append(result)
            summary[strategy] = {"heldout_objective_mean": statistics.mean(row["objective"] for row in scores),
                "heldout_family_means": {family: statistics.mean(row["families"][family] for row in scores)
                    for family in scores[0]["families"]},
                "full_fit_seconds_median": statistics.median(row["full_fit_seconds"] for row in selected),
                "unique_train_rows_per_second_median": statistics.median(row["unique_train_rows_per_second"] for row in selected),
                "effective_heldout_features": scores[0]["effective_feature_panel"],
                "heldout_coverage": scores[0]["coverage"]}
        assert len(feature_spaces) == 1, "compared strategies used different feature spaces"
        baseline, candidate = summary["adam"], summary["ridge_path"]
        summary["heldout_relative_reduction"] = 1 - candidate["heldout_objective_mean"] / baseline["heldout_objective_mean"]
        summary["full_fit_speedup"] = baseline["full_fit_seconds_median"] / candidate["full_fit_seconds_median"]
        summary["regressed_families"] = sorted(family for family, value in candidate["heldout_family_means"].items()
            if value > baseline["heldout_family_means"][family] + 1e-12)
        summary["trained_family_ids"] = sorted(counts)
        summary["training_atoms_pruned"] = 0
        output[domain] = summary
    report = {"domains": output, "same_feature_basis_per_comparison": True,
        "source_decoder_trained": False, "source_model_correspondence_proved": False,
        "supplemental_model_structures_reused": True, "selection_on_test": False,
        "models_promoted": False, "all_catalog_40_families_supported": False,
        "coverage": "all 15/9/8/6 existing domain training routes exercised by explicit native evidence",
        "heldout_now_exposed": True, "proof_authority": False}
    save(RUN / "report.json", report)
    print(json.dumps({"domains": {domain: {key: row[key] for key in (
        "heldout_relative_reduction", "full_fit_speedup", "regressed_families", "trained_family_ids")}
        for domain, row in output.items()}}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "fit", "evaluate"))
    parser.add_argument("--freeze-sha256")
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    RUN = args.output_directory.resolve()
    if args.phase == "prepare": prepare()
    elif args.phase == "fit": fit()
    else: evaluate(args.freeze_sha256)
