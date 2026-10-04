#!/usr/bin/env python3
"""Once-only, source-gated comparison on newly authored native compositions.

This experiment tests structural feature optimization. It does not train a
source-language decoder, prove source meaning, or establish global convergence.
Test native targets are constructed only after every compared fit is sealed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PANEL_PATH = ROOT / "tests/fixtures/logic/complete_feature_convergence_v2/panel.py"
SEEDS = (1729, 1730)
STRATEGIES = ("budgeted_decoder", "complete_fixed", "complete_adaptive")
SETTINGS = {"epochs": 24, "patience": 24, "latent_width": 4, "minibatch_size": 2,
    "learning_rate": .001, "denoising": .05, "ridge": .001, "max_seconds": 120}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw(value))


def load_panel():
    spec = importlib.util.spec_from_file_location("family_safe_convergence_panel_v1", PANEL_PATH)
    panel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(panel)
    return panel


def encode_source(value):
    if hasattr(value, "to_dict"):
        return encode_source(value.to_dict())
    if type(value) is bytes:
        return {"encoding": "utf8", "text": value.decode(), "sha256": hashlib.sha256(value).hexdigest()}
    if type(value) in (tuple, list):
        return [encode_source(item) for item in value]
    if type(value) is dict:
        return {key: encode_source(item) for key, item in value.items()}
    # Typed evidence wrappers have exact owners with no public serializer.
    if hasattr(value, "document") and hasattr(value, "source"):
        return {"typed_owner": type(value.document).__name__, "document": encode_source(value.document),
            "source": encode_source(value.source)}
    if hasattr(value, "formula") and hasattr(value, "source_ref"):
        return {"requirement_id": value.requirement_id, "formula": value.formula, "source_ref": encode_source(value.source_ref)}
    return value


def source_pins():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_complete_v6 as complete_trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_vocab as complete
    return {str(path): sha(path) for path in (Path(__file__).resolve(), PANEL_PATH,
        Path(trainer.__file__).resolve(), Path(complete_trainer.__file__).resolve(), Path(complete.__file__).resolve())}


def require_unchanged(pins):
    if source_pins() != pins:
        raise ValueError("benchmark, panel or numerical producer changed during comparison")


def check_native(result, cases):
    if not result["receipt"]["all_jobs_completed"]:
        raise ValueError("native job failure; retained receipt has exact blockers")
    outputs = {item["job_id"]: item for item in result["jobs"]}
    if set(outputs) != set(cases):
        raise ValueError("native result identities differ")
    projections = builds = 0
    for identity, item in outputs.items():
        receipt = item["receipt"]["native"]
        expected = {p["projection_id"] for p in cases[identity]["report"]["projections"]}
        actual = receipt["per_projection"]
        if {p["projection_id"] for p in actual} != expected or any(
                p["parser_status"] != "passed" or p["lake_status"] != "passed" for p in actual):
            raise ValueError("every emitted projection requires actual passing native checks")
        if receipt["execution"]["returncode"] != 0 or receipt["execution"]["command"][-2:] != ["build", receipt["library"]]:
            raise ValueError("matching actual Lake build required")
        projections += len(expected)
        builds += 1
    return outputs, {"actual_lake_builds": builds, "emitted_projection_checks": projections}


def run(output, *, lake, java_executable, tla2tools_jar, workers=4):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks as parallel
    from ipfs_datasets_py.logic.formalization.autoencoder import training_readiness as readiness
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_complete_v6 as complete_trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_complete_vocab as complete
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler

    started = time.monotonic()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    panel = load_panel()
    pins = source_pins()
    tool_pins = {str(Path(p).resolve()): sha(Path(p).resolve()) for p in (lake, java_executable, tla2tools_jar)}
    plan = {"schema": "complete-feature-convergence-plan/v1", "source_tree": str(ROOT),
        "source_pins": pins, "logic_tree_pin": require_workspace_logic_tree(), "tools": tool_pins,
        "manifest": panel.manifest(), "settings": SETTINGS, "seeds": SEEDS, "strategies": STRATEGIES,
        "training_rows_per_domain": 6, "tuning_rows_per_domain": 2, "heldout_rows_per_domain": 2,
        "selection_on_test": False, "heldout_targets_prepared_before_freeze": False,
        "source_decoder_trained": False, "natural_source_generalization_claimed": False,
        "feature_vocabulary_scope": "budgeted_4096_control_vs_all_original_training_atoms_with_explicit_capacity",
        "learned_8d_or_384d_lineages_modified": False, "weights_downloaded": False}
    write(output / "plan.json", plan)
    scheduler = get_global_resource_scheduler()

    def prepare_and_check(splits, phase):
        cases, jobs, specs, portfolio_jobs = {}, [], {}, []
        prepare_started = time.monotonic()
        for domain in panel.DOMAINS:
            for split in splits:
                for index, row in enumerate(panel.rows(domain, split)):
                    identity = f"{domain}-{split}-{index}"
                    case = panel.prepare_case(row)
                    cases[identity], specs[identity] = case, row
                    write(output / phase / "inputs" / identity / "targets.json", case["report"])
                    write(output / phase / "inputs" / identity / "fixture.json", case["fixture"])
                    write(output / phase / "inputs" / identity / "source-inputs.json", encode_source(case["source_inputs"]))
                    jobs.append(parallel.NativeProjectionJob(identity, case["report"], case["source_inputs"],
                        applicability_review=panel.reviews(case["report"], row)))
                    if phase == "development" and split == "train" and index == 0:
                        portfolio_jobs.append(parallel.PortfolioDiagnosticJob("portfolio-" + domain, identity,
                            domain + "/native_formula/propositional/v3", solver_names=("z3", "cvc5")))
        preparation = time.monotonic() - prepare_started
        validation_started = time.monotonic()
        checked = parallel.run_parallel_projection_checks(jobs, portfolio_jobs=portfolio_jobs, scheduler=scheduler, max_workers=workers,
            lake_executable=lake, output_directory=output / phase / "native", java_executable=java_executable,
            tla2tools_jar=tla2tools_jar)
        write(output / phase / "parallel-receipt.json", checked["receipt"])
        results, counts = check_native(checked, cases)
        attempts = []
        for item in checked["portfolio_jobs"]:
            record = item["receipt"]["portfolio"]
            if record["denied"] or record["cancelled_attempt_ids"] or len(record["attempts"]) != 2:
                raise ValueError("both supported diagnostic solvers must actually execute")
            if {attempt["solver_name"] for attempt in record["attempts"]} != {"z3", "cvc5"}:
                raise ValueError("supplemental solver names differ")
            for attempt in record["attempts"]:
                if attempt["exit_code"] != 0 or attempt["verdict"] not in {"sat", "unsat"}:
                    raise ValueError("supported diagnostic solver failed to finish")
                if not record["evidence"][attempt["attempt_id"]]["command"]:
                    raise ValueError("actual diagnostic command evidence is missing")
                attempts.append(attempt)
        if len(attempts) != (4 if phase == "development" else 0):
            raise ValueError("wrong number of diagnostic solver attempts")
        counts.update(preparation_seconds=preparation, native_validation_seconds=time.monotonic() - validation_started,
            portfolio_diagnostics={"scope": "propositional satisfiability only; not source proof",
                "requested_logic_family": "propositional" if portfolio_jobs else None,
                "solver_names": ["z3", "cvc5"] if portfolio_jobs else [],
                "actual_attempts": len(attempts), "attempts": attempts,
                "verdict_counts": {verdict: sum(item["verdict"] == verdict for item in attempts)
                    for verdict in sorted({item["verdict"] for item in attempts})},
                "solver_attempt_counts": {name: sum(item["solver_name"] == name for item in attempts)
                    for name in sorted({item["solver_name"] for item in attempts})},
                "qualification_granted": False})
        require_unchanged(pins)
        return cases, specs, results, counts

    cases, specs, native, development_counts = prepare_and_check(("train", "validation"), "development")
    fits, training_observations = [], {}
    for domain in panel.DOMAINS:
        rows = [{"id": identity, "document_id": row["source_id"], "group_id": row["group_id"],
            "split": row["split"], "source_inputs": cases[identity]["source_inputs"],
            "observation": native[identity]["observation"]}
            for identity, row in specs.items() if row["domain_id"] == domain]
        training_observations[domain] = [row["observation"] for row in rows if row["split"] == "train"]
        corpus = readiness.prepare_validated_projection_corpus(domain, rows)
        write(output / domain / "corpus.json", corpus.to_dict())
        for offset, seed in enumerate(SEEDS):
            for strategy in STRATEGIES if offset % 2 == 0 else STRATEGIES[::-1]:
                fit_started = time.monotonic()
                if strategy == "budgeted_decoder":
                    trained = readiness.train_prepared_projection_corpus(corpus,
                        output_dir=output / domain / f"{strategy}-{seed}" / "checkpoint",
                        refinement_strategy="decoder_blocks", seed=seed, **SETTINGS)
                else:
                    trained = complete_trainer.train_complete_prepared_projection_corpus(corpus,
                        output_dir=output / domain / f"{strategy}-{seed}" / "checkpoint",
                        adaptive_learning_rate=strategy == "complete_adaptive", seed=seed, **SETTINGS)
                elapsed = time.monotonic() - fit_started
                write(output / domain / f"{strategy}-{seed}" / "training.json", trained)
                fits.append({"domain_id": domain, "strategy": strategy, "seed": seed,
                    "descriptor": trained["descriptor"], "report": trained["report"],
                    "fit_wall_seconds": elapsed, "unique_training_rows_per_second": 6 / elapsed})
                print(json.dumps({"phase": "fit", "domain": domain, "strategy": strategy,
                    "seed": seed, "seconds": elapsed, "selected_epoch": trained["report"]["selected_epoch"]}), flush=True)
    require_unchanged(pins)
    write(output / "fits.json", fits)
    sealed = {str(path.relative_to(output)): sha(path) for path in sorted(output.rglob("*"))
        if path.is_file() and ".lake" not in path.parts}
    write(output / "freeze.json", {"files": sealed, "settings": SETTINGS, "source_pins": pins,
        "heldout_targets_prepared": False, "selection_on_test": False})
    freeze_sha = sha(output / "freeze.json")
    # This is the first request for test source bodies or native projection targets.
    write(output / "heldout-exposure.json", {"freeze_sha256": freeze_sha, "all_compared_fits_frozen": True,
        "heldout_now_exposed": True, "test_selection_allowed": False})
    test_cases, test_specs, test_native, test_counts = prepare_and_check(("test",), "heldout")
    summaries = {}
    for domain in panel.DOMAINS:
        observations = [test_native[identity]["observation"] for identity, row in test_specs.items() if row["domain_id"] == domain]
        scores = []
        full_fit = next(item for item in fits if item["domain_id"] == domain and item["strategy"] == "complete_fixed")
        reference, _ = complete_trainer._read(full_fit["descriptor"])
        reference_space = reference["space"]
        reports, _ = trainer._panel(observations, domain)
        rows = trainer._reports(reports, atoms=trainer.prepared._atom_encoder()[0])
        for fit in [item for item in fits if item["domain_id"] == domain]:
            owner = trainer if fit["strategy"] == "budgeted_decoder" else complete_trainer
            infer = owner.infer_validated_family_projection_autoencoder if owner is trainer else owner.infer_complete_family_projection_autoencoder
            infer_started = time.monotonic()
            score = infer(fit["descriptor"], observations)
            infer_seconds = time.monotonic() - infer_started
            saved, _ = owner._read(fit["descriptor"])
            common = complete.common_support_metrics(saved["space"], score["reconstructed_features"], rows,
                reference_space=reference_space)
            write(output / domain / f"{fit['strategy']}-{fit['seed']}" / "heldout.json", score)
            write(output / domain / f"{fit['strategy']}-{fit['seed']}" / "common-heldout.json", common)
            scores.append({"strategy": fit["strategy"], "seed": fit["seed"], "score": common,
                "retained_feature_score": score["objective"], "coverage": score["coverage"],
                "inference_seconds": infer_seconds, "fit_wall_seconds": fit["fit_wall_seconds"],
                "optimization_seconds": fit["report"]["prepared_execution"]["optimization_seconds"],
                "optimizer_steps": fit["report"]["optimizer_steps"],
                "selected_epoch": fit["report"]["selected_epoch"],
                "feature_selection": fit["report"]["feature_selection"],
                "all_emitted_projections_have_loss": score["loss_coverage"]["all_emitted_projections_have_loss"]})
        by_strategy = {}
        for strategy in STRATEGIES:
            selected = [row for row in scores if row["strategy"] == strategy]
            by_strategy[strategy] = {"heldout_objective_mean": statistics.mean(row["score"]["objective"] for row in selected),
                "heldout_family_means": {family: statistics.mean(row["score"]["families"][family] for row in selected)
                    for family in selected[0]["score"]["families"]},
                "fit_wall_seconds_median": statistics.median(row["fit_wall_seconds"] for row in selected),
                "optimization_seconds_median": statistics.median(row["optimization_seconds"] for row in selected),
                "selected_epochs": [row["selected_epoch"] for row in selected],
                "optimizer_steps": [row["optimizer_steps"] for row in selected]}
        baseline = by_strategy[STRATEGIES[0]]
        comparisons = {}
        for strategy in STRATEGIES[1:]:
            candidate = by_strategy[strategy]
            per_seed = []
            for seed in SEEDS:
                left = next(row for row in scores if row["strategy"] == STRATEGIES[0] and row["seed"] == seed)
                right = next(row for row in scores if row["strategy"] == strategy and row["seed"] == seed)
                per_seed.append({"seed": seed, "relative_reduction": 1 - right["score"]["objective"] / left["score"]["objective"],
                    "regressed_families": sorted(family for family, value in right["score"]["families"].items()
                        if value > left["score"]["families"][family] + trainer.EPS)})
            comparisons[strategy] = {"mean_relative_reduction": 1 - candidate["heldout_objective_mean"] / baseline["heldout_objective_mean"],
                "per_seed": per_seed}
        summaries[domain] = {"strategies": by_strategy, "comparisons_vs_budgeted": comparisons,
            "feature_selection": {row["strategy"]: row["feature_selection"] for row in scores},
            "retained_coverage": {row["strategy"]: row["coverage"] for row in scores},
            "all_emitted_projections_have_loss": all(row["all_emitted_projections_have_loss"] for row in scores),
            "metric_scope": "identical full training-reference plus heldout-only atom support; unchanged raw predictions; OOV predicted zero",
            "paired_scores": [{key: value for key, value in row.items() if key != "coverage"} for row in scores]}
        write(output / domain / "heldout-comparison.json", summaries[domain])
    if any(sha(output / name) != value for name, value in sealed.items()):
        raise ValueError("frozen development artifact changed after test exposure")
    require_unchanged(pins)
    if any(sha(path) != value for path, value in tool_pins.items()):
        raise ValueError("native tool changed during experiment")
    result = {"schema": "complete-feature-convergence-comparison/v1", "domains": summaries,
        "development": development_counts, "heldout": test_counts, "freeze_sha256": freeze_sha,
        "wall_seconds": time.monotonic() - started,
        "actual_lake_builds": development_counts["actual_lake_builds"] + test_counts["actual_lake_builds"],
        "emitted_projection_checks": development_counts["emitted_projection_checks"] + test_counts["emitted_projection_checks"],
        "independent_heldout_groups_per_domain": 2, "heldout_now_exposed": True, "selection_on_test": False,
        "scope": "fresh authored native structural feature reconstruction; not natural-source decoding",
        "models_promoted": False, "source_semantics_verified": False, "global_convergence_established": False,
        "qualified": False, "admitted": False, "constitution_formalized": False,
        "source_decoder_trained": False, "weights_downloaded": False}
    write(output / "summary.json", result)
    print(json.dumps({"wall_seconds": result["wall_seconds"], "actual_lake_builds": result["actual_lake_builds"],
        "emitted_projection_checks": result["emitted_projection_checks"], "domains": {domain: row["comparisons_vs_budgeted"]
            for domain, row in summaries.items()}}, indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    parser.add_argument("--java-executable", required=True)
    parser.add_argument("--tla2tools-jar", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    run(args.output, lake=args.lake, java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar, workers=args.workers)
