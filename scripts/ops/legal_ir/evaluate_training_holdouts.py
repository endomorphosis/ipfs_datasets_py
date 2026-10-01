#!/usr/bin/env python3
"""Predeclared fresh action-disjoint formula reconstruction experiment.

Fit all six fixed-budget heads before embedding or compiling sealed sources.
Compiler targets remain weak labels, and no checkpoint is promoted.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import compare_formula_training_augmentation as prior
from scripts.ops.legal_ir import evaluate_actor_composition_curriculum as shared
require, sha, raw, write = shared.require, shared.sha, shared.raw, shared.write
BASE = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
PANEL = ROOT / "tests/fixtures/logic/action_disjoint_holdout_curriculum.json"
SEEDS = (1729, 1730, 1731)
ARMS = ("original32", "augmented64")
STEPS = 1000
FALSE = dict(prior.FALSE, independent_legal_gold=False)
_IMPORTED_SHA = sha(__file__)


def sources():
    require(sha(__file__) == _IMPORTED_SHA, "runner changed since import")
    paths = [Path(__file__), PANEL, BASE / "formula_holdout_curriculum.py",
             BASE / "modal_latent_formula_prepared.py"]
    return {**prior.sources(), **{str(p): sha(p) for p in paths}}


def panel():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import formula_holdout_curriculum as curriculum
    excluded = []
    for path in (shared.PANEL, prior.AUGMENTATION, shared.shared.FIXTURE):
        excluded.extend(row["text"] for row in json.loads(path.read_text())["rows"])
    return curriculum.load_curriculum(PANEL, expected_file_sha256=sha(PANEL),
                                      excluded_source_texts=excluded,
                                      expected_manifest_sha256=curriculum.manifest_digest(curriculum.build_authored_panel()))


def settings():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile
    profile = get_training_profile("raw_gain10_v1")
    return dict(seeds=list(SEEDS), arms=list(ARMS), optimizer_steps=STEPS,
                epochs=1000, max_seconds=120, batch_size=8,
                row_presentations_per_arm=8000, profile=profile,
                config_overrides={"batch_size": 8, "seed": "per declared seed"})


def guard(directory):
    plan = json.loads((directory / "plan.json").read_text())
    require(plan["source_hashes"] == sources(), "producer source changed")
    require(plan["panel_manifest_sha256"] == panel().manifest_sha256, "curriculum changed")
    require(plan["settings"] == settings(), "settings changed")
    return plan


def fixture_rows(prepared_panel, split):
    if split == "development":
        return prepared_panel.development_rows(include_must=True)
    require(split == "sealed_evaluation", "unsupported preparation partition")
    return prepared_panel.rows("sealed_evaluation")


def prepare_partition(directory, split):
    # Caller must establish the frozen-head barrier before requesting evaluation.
    rows = fixture_rows(panel(), split)
    folder = directory / split
    folder.mkdir(exist_ok=False)
    fixture = dict(schema="action-disjoint-embedding-inputs/v1", rows=rows, **FALSE)
    write(folder / "source-fixture.json", fixture)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--phase", "embeddings",
                    "--output-directory", str(folder)], cwd=ROOT, check=True, timeout=300)
    production = json.loads((folder / "embedding-production.json").read_text())
    samples = prior.native_samples(folder, fixture, production)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import LinguisticAutoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
    observer = LegacyLinguisticTeacher(LinguisticAutoencoder())
    evidence, targets = {}, {}
    started = time.perf_counter()
    for row in rows:
        observer._require_sources()
        value = observer._prepare(samples[row["id"]], "authored_fixture")
        require(value["candidate"], "compiler screening rejected " + row["id"])
        evidence[row["id"]] = value
        sample = samples[row["id"]]
        targets[row["id"]] = dict(id=sample.sample_id, source_text=sample.text,
                                 canonical_ir={"rules": value["compiler"]["rules"]})
    if split == "development":
        for row in panel().training_variants():
            prior.require_equivalent_labels(evidence[row["parent_id"]], evidence[row["id"]])
    observer._require_sources()
    elapsed = time.perf_counter() - started
    refs = dict(fixture=shared.reference(folder / "source-fixture.json"),
                embeddings=shared.reference(folder / "embedding-production.json"),
                samples=write(folder / "samples.json", [s.to_dict() for s in samples.values()]),
                targets=write(folder / "targets.json", targets),
                compiler=write(folder / "compiler.json", evidence))
    write(folder / "prepared.json", dict(files=refs, sample_count=len(rows),
          compiler_seconds=elapsed, compiler_seconds_per_span=elapsed / len(rows),
          compiler_weak_labels=True, **FALSE))
    return samples, targets


def inputs(directory, split):
    folder = directory / split
    prepared = json.loads((folder / "prepared.json").read_text())
    refs = prepared["files"]
    fixture = shared.read_reference(refs["fixture"])
    require(fixture["rows"] == fixture_rows(panel(), split), "partition source mismatch")
    samples = prior.native_samples(folder, fixture, shared.read_reference(refs["embeddings"]))
    require([s.to_dict() for s in samples.values()] == shared.read_reference(refs["samples"]), "samples changed")
    targets, evidence = shared.read_reference(refs["targets"]), shared.read_reference(refs["compiler"])
    require(set(targets) == set(samples) == set(evidence), "target coverage mismatch")
    for row in fixture["rows"]:
        sample = samples[row["id"]]
        require(evidence[row["id"]]["candidate"], "target compiler screening incomplete")
        require(targets[row["id"]] == dict(id=sample.sample_id, source_text=sample.text,
                canonical_ir={"rules": evidence[row["id"]]["compiler"]["rules"]}), "target differs from source/compiler")
    if split == "development":
        for row in panel().training_variants():
            prior.require_equivalent_labels(evidence[row["parent_id"]], evidence[row["id"]])
    return samples, targets


def prepare(directory):
    started = time.perf_counter()
    directory.mkdir(parents=True, exist_ok=False)
    curriculum = panel()
    write(directory / "plan.json", dict(schema="fresh-action-disjoint-formula-plan/v1", source_hashes=sources(),
        panel_manifest_sha256=curriculum.manifest_sha256, curriculum=curriculum.receipt, settings=settings(),
        holdout_protocol="all six scored heads frozen before sealed embeddings or compiler labels are produced",
        checkpoint_selection_performed=False, bridge_names=[], legal_ir_target_count=0,
        legal_ir_evaluate_provers=False, metric_disk_cache=False, legal_ir_parallel_workers=1,
        sample_memory=False, temperature=0, **FALSE))
    prepare_partition(directory, "development")
    guard(directory)
    write(directory / "prepared.json", dict(plan=shared.reference(directory / "plan.json"),
        development=shared.reference(directory / "development/prepared.json"),
        preparation_seconds=time.perf_counter()-started, evaluation_sources_processed=False, **FALSE))


def development_inputs(directory):
    plan = guard(directory)
    prepared = json.loads((directory / "prepared.json").read_text())
    require(shared.read_reference(prepared["plan"]) == plan, "prepared plan differs")
    shared.read_reference(prepared["development"])
    samples, targets = inputs(directory, "development")
    return plan, prepared, samples, targets


def fit(directory):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_prepared as fast
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas
    plan, prepared, samples, targets = development_inputs(directory)
    require(not (directory / "frozen.json").exists() and not (directory / "sealed_evaluation").exists(),
            "scored or exposed campaign cannot be refitted; start a new declared experiment")
    # Exclusive attempt marker preserves partial failures and prevents two fit writers.
    with (directory / "fit-started.json").open("x") as stream:
        json.dump(dict(plan_sha256=sha(directory / "plan.json"), evaluation_targets_opened=False), stream)
    curriculum, results = panel(), {}
    partitions = {"original_training": curriculum.rows("training"), "added_wording": curriculum.training_variants(),
                  "tuning": curriculum.rows("tuning")}
    tuning = [samples[row["id"]] for row in partitions["tuning"]]
    tune_targets = [targets[row["id"]] for row in partitions["tuning"]]
    started = time.perf_counter()
    for seed in SEEDS:
        identity = None
        for arm in ARMS:
            development_inputs(directory)
            rows = curriculum.training_rows(include_must=arm == "augmented64")
            training, labels = [samples[r["id"]] for r in rows], [targets[r["id"]] for r in rows]
            runtime = runtimes.open_runtime("legal_ir", "current_v2", **plan["settings"]["profile"]["core_options"])
            original_core = raw(runtime.model.state.to_dict())
            train_rows, tune_rows = joint._rows(runtime.model, training, labels), joint._rows(runtime.model, tuning, tune_targets)
            checkpoint = learning.build_checkpoint(joint._core_binding(runtime.model), train_rows, tune_rows,
                **dict(plan["settings"]["profile"]["formula_options"], batch_size=8, seed=seed))
            candidate = {k:learning.checkpoint_digest(checkpoint[k]) for k in ("binding","config","codec","model_state")}
            require(identity is None or identity == candidate, "paired initialization differs")
            identity = candidate
            trained = fast.train(checkpoint, train_rows, tune_rows, epochs=1000, max_seconds=120, max_optimizer_steps=STEPS)
            try:
                prior.require_completed_training(trained["report"])
            except Exception:
                write(directory / f"{seed}-{arm}-incomplete.json", trained)
                raise
            runtime.model.attach_formula_checkpoint(trained["checkpoint"])
            require(raw(runtime.model.state.to_dict()) == original_core, "sparse core changed")
            tick = time.perf_counter()
            outputs = {name:runtime.infer([samples[r["id"]] for r in rows]) for name,rows in partitions.items()}
            inference_seconds = time.perf_counter()-tick
            generation = {name:compare_free_running_formulas(outputs[name], [targets[r["id"]] for r in rows],
                          partition=name) for name,rows in partitions.items()}
            require(all(v["valid_evaluation"] and v["operational_complete"] for v in generation.values()), "incomplete generation evidence")
            head = runtime.model.save_formula_checkpoint(directory / f"{seed}-{arm}-head.json")
            require(head["sha256"] == trained["report"]["checkpoint_sha256"], "head differs from scored training result")
            reloaded = runtimes.open_runtime("legal_ir", "current_v2", **plan["settings"]["profile"]["core_options"],
                formula_checkpoint=head["path"], formula_sha256=head["sha256"])
            require(reloaded.infer(tuning) == outputs["tuning"], "reload changed generation")
            resume = dict(epochs=1,max_optimizer_steps=1,max_seconds=60)
            continued = fast.train(trained["checkpoint"], train_rows, tune_rows, **resume)
            restored = fast.train(learning.load_checkpoint(head["path"],expected_sha256=head["sha256"]),train_rows,tune_rows,**resume)
            require(continued["report"]["optimizer_steps"] == restored["report"]["optimizer_steps"] == 1,
                    "resume probe did not execute its update")
            require(continued["checkpoint"] == restored["checkpoint"], "resume differs")
            result = dict(seed=seed,arm=arm,head=head,training_report=trained["report"],initial_identity=identity,
                outputs=outputs,generation=generation,training_rows=len(training),row_presentations=8000,
                inference_seconds=inference_seconds,inference_seconds_per_span=inference_seconds/72,
                reload_prediction_exact=True,resume_checkpoint_exact=True,probe_step_excluded=True,
                evaluation_targets_used=False,**FALSE)
            results[f"{seed}/{arm}"] = write(directory / f"{seed}-{arm}-fit.json",result)
            print(json.dumps(dict(phase="fit",seed=seed,arm=arm,tuning=generation["tuning"]["exact_reconstruction"])),flush=True)
    guard(directory)
    write(directory / "frozen.json",dict(schema="fresh-action-disjoint-frozen/v1",plan=shared.reference(directory/"plan.json"),
        preparation=shared.reference(directory/"prepared.json"),fits=results,evaluation_targets_opened=False,
        training_phase_seconds=time.perf_counter()-started,**FALSE))


def frozen_fits(directory):
    plan = guard(directory)
    development_inputs(directory)  # Recheck every retained development artifact before opening holdout.
    frozen = json.loads((directory/"frozen.json").read_text())
    require(shared.read_reference(frozen["plan"]) == plan and frozen["evaluation_targets_opened"] is False, "frozen plan differs")
    prepared = shared.read_reference(frozen["preparation"])
    require(shared.read_reference(prepared["plan"]) == plan, "preparation differs")
    shared.read_reference(prepared["development"])
    require(set(frozen["fits"]) == {f"{s}/{a}" for s in SEEDS for a in ARMS}, "all six fits must be frozen")
    results = {}
    identities = {}
    for key,ref in frozen["fits"].items():
        result = shared.read_reference(ref)
        require(key == f"{result['seed']}/{result['arm']}","fit identity differs")
        head = shared.read_reference(result["head"])
        prior.require_completed_training(result["training_report"])
        require(result["head"]["sha256"] == result["training_report"]["checkpoint_sha256"], "head/report mismatch")
        require(head["progress"]["optimizer_steps"] == STEPS, "head not at scored step")
        options = dict(plan["settings"]["profile"]["formula_options"],batch_size=8,seed=result["seed"])
        require(all(head["config"][k] == v for k,v in options.items()), "head configuration differs")
        previous = identities.setdefault(result["seed"], result["initial_identity"])
        require(previous == result["initial_identity"], "paired identity differs")
        results[key] = result
    return plan,frozen,results


def validate_frozen_runtimes(plan, fits):
    """Attach every scored head before any sealed target or prediction access."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    for fit_report in fits.values():
        head = fit_report["head"]
        runtime = runtimes.open_runtime("legal_ir", "current_v2", **plan["settings"]["profile"]["core_options"],
            formula_checkpoint=head["path"], formula_sha256=head["sha256"])
        del runtime


def evaluate(directory):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_decoded_schema as schemas
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas
    plan,frozen,fits = frozen_fits(directory)  # Required before any held-out preparation.
    validate_frozen_runtimes(plan, fits)
    frozen_ref = shared.reference(directory/"frozen.json")
    samples,targets = prepare_partition(directory,"sealed_evaluation")
    heldout_prepared_ref = shared.reference(directory/"sealed_evaluation/prepared.json")
    rows = panel().rows("sealed_evaluation")
    heldout, labels = [samples[r["id"]] for r in rows],[targets[r["id"]] for r in rows]
    results = {}
    for key,fit_report in fits.items():
        require(shared.read_reference(frozen_ref) == frozen, "frozen heads changed during evaluation")
        runtime = runtimes.open_runtime("legal_ir","current_v2",**plan["settings"]["profile"]["core_options"],
            formula_checkpoint=fit_report["head"]["path"],formula_sha256=fit_report["head"]["sha256"])
        started = time.perf_counter(); output = runtime.infer(heldout); elapsed=time.perf_counter()-started
        metric = compare_free_running_formulas(output,labels,partition="sealed_evaluation")
        require(metric["valid_evaluation"] and metric["operational_complete"], "heldout evidence incomplete")
        head = shared.read_reference(fit_report["head"])
        _,model,_ = learning._restore(head)
        losses = learning._metrics(model,joint._rows(runtime.model,heldout,labels),head["codec"],head["config"],time.monotonic()+60)
        require(losses["complete"],"heldout loss incomplete")
        results[key] = dict(output=output,generation=metric,teacher_forced_loss=losses,
                            inference_seconds=elapsed,inference_seconds_per_span=elapsed/8,**FALSE)
    # Predeclared seed and all eight sealed rows; no outcome-based selection.
    schema_reports = {}
    for arm in ARMS:
        fit_report=fits[f"1729/{arm}"]
        runtime=runtimes.open_runtime("legal_ir","current_v2",**plan["settings"]["profile"]["core_options"],
            formula_checkpoint=fit_report["head"]["path"],formula_sha256=fit_report["head"]["sha256"])
        schema_reports[arm]=schemas.validate_decoded_outputs(runtime,heldout,output_directory=directory/(arm+"-holdout-schemas"),timeout_seconds=60)
    schema_ok=all(shared.schema_checks_passed(value,8) for value in schema_reports.values())
    frozen_fits(directory)
    shared.read_reference(heldout_prepared_ref)
    inputs(directory,"sealed_evaluation")
    write(directory/"report.json",dict(schema="fresh-action-disjoint-formula-results/v1",plan=plan,frozen=frozen,
        fits=fits,heldout=results,schemas=schema_reports,operational_ok=schema_ok,
        heldout_sample_count=8,holdout_opened_after_all_heads_frozen=True,independent_legal_gold=False,
        full_logic_floor_coverage=False,temporal_kind_sidecars_encoded_by_head=False,
        checkpoint_selection_performed=False,peak_parent_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        **{k:v for k,v in FALSE.items() if k != "independent_legal_gold"}))
    require(schema_ok,"fixed schema checks incomplete; inspect retained report")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory",required=True,type=Path)
    parser.add_argument("--phase",required=True,choices=("prepare","embeddings","fit","evaluate"))
    args=parser.parse_args(); directory=args.output_directory.resolve()
    os.environ["CUDA_VISIBLE_DEVICES"]=""
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"]="0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"]="0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"]="0"
    if args.phase=="embeddings": shared.shared.produce_embeddings(directory,fixture_path=directory/"source-fixture.json")
    else: {"prepare":prepare,"fit":fit,"evaluate":evaluate}[args.phase](directory)


if __name__=="__main__": main()
