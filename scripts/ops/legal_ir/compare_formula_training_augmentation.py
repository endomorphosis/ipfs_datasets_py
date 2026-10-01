#!/usr/bin/env python3
"""Paired fixed-budget train-only paraphrase ablation for the current 384D head.

Six fresh runs share 54 verified local embeddings and screened compiler weak
targets. Evaluation partitions are never embedded or compiled by this script.
Tuning is development evidence; no checkpoint is selected or promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import evaluate_actor_composition_curriculum as shared

BASE = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
AUGMENTATION = ROOT / "tests/fixtures/logic/actor_composition_must_training.json"
SEEDS = (1729, 1730, 1731)
ARMS = ("original24", "augmented48")
STEPS = 1000
MAX_SECONDS = 120
PARTITIONS = ("original_training", "added_wording", "tuning")
SCHEMA_TEMPLATES = ("report", "prohibition", "minimum", "deadline")
FALSE = dict(shared.FALSE, independent_generalization_verified=False,
             checkpoint_promotion_performed=False, teacher_weights_loaded=False,
             proof_authority=False, publication_performed=False)
require, sha, raw, write = shared.require, shared.sha, shared.raw, shared.write
_IMPORTED_RUNNER_SHA256 = sha(__file__)


def sources():
    require(sha(__file__) == _IMPORTED_RUNNER_SHA256, "runner source changed since import")
    files = (Path(__file__), AUGMENTATION, BASE / "formula_training_augmentation.py",
             BASE / "formula_training_profiles.py")
    return {**shared.sources(), **{str(path): sha(path) for path in files}}


def source_fixture():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_augmentation import load_must_augmentation
    curriculum = shared.panel()
    augmented = load_must_augmentation(AUGMENTATION, curriculum,
        expected_file_sha256=sha(AUGMENTATION), expected_curriculum_manifest_sha256=curriculum.manifest_sha256)
    rows = curriculum.rows("training") + curriculum.rows("tuning") + augmented.rows()
    require(len(rows) == len({row["id"] for row in rows}) == 54, "exactly 54 distinct source inputs required")
    require(all(row["split"] in ("training", "tuning") for row in rows), "evaluation source in development fixture")
    return dict(schema="authored-training-augmentation-inputs/v1", rows=rows,
        curriculum_manifest_sha256=curriculum.manifest_sha256,
        augmentation_manifest_sha256=augmented.manifest_sha256,
        augmentation_receipt=augmented.receipt, **FALSE)


def partition_rows(fixture, partition):
    require(partition in PARTITIONS, "only declared development partitions may be read")
    rows = fixture["rows"]
    if partition == "original_training":
        return [row for row in rows if row["split"] == "training" and "parent_id" not in row]
    if partition == "added_wording":
        return [row for row in rows if row["split"] == "training" and "parent_id" in row]
    return [row for row in rows if row["split"] == "tuning"]


def require_equivalent_labels(parent, variant):
    require(parent["candidate"] is True and variant["candidate"] is True,
            "parent and paraphrase must pass unchanged compiler screening")
    for field in ("rules", "temporal_records"):
        require(raw(parent["compiler"][field]) == raw(variant["compiler"][field]),
                "paraphrase compiler " + field + " differs from its parent")


def plan_guard(directory, plan, plan_sha):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile
    require(sha(directory / "plan.json") == plan_sha, "experiment plan changed")
    require(plan["source_hashes"] == sources(), "producer source changed after plan was sealed")
    require(plan["seeds"] == list(SEEDS) and plan["arms"] == list(ARMS)
            and plan["optimizer_steps_per_arm"] == STEPS
            and plan["max_seconds_per_arm"] == MAX_SECONDS, "experiment settings changed")
    require(plan["profile"] == get_training_profile("raw_gain10_v1"), "declared conditioning profile changed")
    fixture = shared.read_reference(plan["source_fixture"])
    require(fixture == source_fixture(), "source fixture differs from declared augmentation")


def native_samples(directory, fixture, production):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as embeddings
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    require(production["fixture_sha256"] == sha(directory / "source-fixture.json"), "embedding fixture differs")
    ref = production["artifact"]
    receipt = embeddings.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"],
        expected_size_bytes=ref["bytes"], resolver=lambda value: production["source_paths"][value["sha256"]])
    data = receipt.to_dict()
    require(data["execution"]["kind"] == "native", "verified native local semantic embeddings required")
    require(data["producer"]["code_sha256"] == sha(BASE / "autoencoder_embedding_runtime.py"),
            "embedding producer differs")
    shared.shared.verify_fixture_inputs(data, fixture["rows"])
    vectors = {item["section"]: embeddings._decode_vector(value["vector"])
               for item, value in zip(data["inputs"], data["results"])}
    return {row["id"]: current_v2.build_sample(title="diagnostic", section=row["id"], text=row["text"],
        citation="authored diagnostic:" + row["id"], embedding_vector=vectors[row["id"]],
        embedding_model=data["model"]["model_id"] + "@" + data["model"]["revision"])
        for row in fixture["rows"]}


def prepare(directory):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import LinguisticAutoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
    started = time.perf_counter()
    producer, fixture = sources(), source_fixture()
    directory.mkdir(parents=True, exist_ok=False)
    fixture_ref = write(directory / "source-fixture.json", fixture)
    plan = dict(schema="formula-training-augmentation-plan/v1", source_hashes=producer,
        source_fixture=fixture_ref, seeds=list(SEEDS), arms=list(ARMS), optimizer_steps_per_arm=STEPS,
        max_seconds_per_arm=MAX_SECONDS, profile=get_training_profile("raw_gain10_v1"),
        batch_size=6, row_presentations_per_arm=6000, original_epochs=250, augmented_epochs=125,
        comparison="same initial head/core/codec per seed; only training wording diversity differs",
        embedding_source_count=54, evaluation_sources_processed=False, evaluation_targets_used=False,
        fixed_schema_templates=list(SCHEMA_TEMPLATES), schema_seed=SEEDS[0],
        checkpoint_selection_performed=False, bridge_names=[], legal_ir_target_count=0,
        legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1, metric_disk_cache=False,
        sample_memory=False, temperature=0, **FALSE)
    plan_sha = write(directory / "plan.json", plan)["sha256"]
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--phase", "embeddings",
                    "--output-directory", str(directory)], cwd=ROOT, check=True, timeout=300)
    plan_guard(directory, plan, plan_sha)
    production = json.loads((directory / "embedding-production.json").read_text())
    samples = native_samples(directory, fixture, production)
    observer = LegacyLinguisticTeacher(LinguisticAutoencoder())
    evidence, targets = {}, {}
    tick = time.perf_counter()
    for row in fixture["rows"]:
        observer._require_sources()
        observed = observer._prepare(samples[row["id"]], "authored_fixture")
        require(observed["candidate"], "compiler screening rejected " + row["id"])
        evidence[row["id"]] = observed
        sample = samples[row["id"]]
        targets[row["id"]] = dict(id=sample.sample_id, source_text=sample.text,
                                 canonical_ir={"rules": observed["compiler"]["rules"]})
    for row in partition_rows(fixture, "added_wording"):
        require_equivalent_labels(evidence[row["parent_id"]], evidence[row["id"]])
    observer._require_sources()
    elapsed = time.perf_counter() - tick
    files = {part: write(directory / ("targets-" + part + ".json"),
                         [targets[row["id"]] for row in partition_rows(fixture, part)]) for part in PARTITIONS}
    files.update(samples=write(directory / "student-samples.json", [s.to_dict() for s in samples.values()]),
        compiler_observations=write(directory / "compiler-observations.json", evidence),
        embedding_production=shared.reference(directory / "embedding-production.json"))
    plan_guard(directory, plan, plan_sha)
    write(directory / "prepared.json", dict(schema="formula-training-augmentation-preparation/v1",
        plan_sha256=plan_sha, files=files, compiler_weak_target_count=54,
        augmentation_rules_and_temporal_sidecars_exact=True, compiler_seconds=elapsed,
        compiler_wall_seconds_per_span=elapsed/54, source_count=54,
        preparation_seconds=time.perf_counter()-started, legacy_teacher_prediction_executed=False,
        shared_targets_prepared_once=True, **FALSE))


def prepared_inputs(directory):
    plan = json.loads((directory / "plan.json").read_text())
    prepared = json.loads((directory / "prepared.json").read_text())
    plan_guard(directory, plan, prepared["plan_sha256"])
    fixture = shared.read_reference(plan["source_fixture"])
    production = shared.read_reference(prepared["files"]["embedding_production"])
    samples = native_samples(directory, fixture, production)
    require([s.to_dict() for s in samples.values()] == shared.read_reference(prepared["files"]["samples"]),
            "rebuilt samples differ from the preparation artifact")
    targets = {part: shared.read_reference(prepared["files"][part]) for part in PARTITIONS}
    evidence = shared.read_reference(prepared["files"]["compiler_observations"])
    for row in partition_rows(fixture, "added_wording"):
        require_equivalent_labels(evidence[row["parent_id"]], evidence[row["id"]])
    for part in PARTITIONS:
        rows = partition_rows(fixture, part)
        require(len(rows) == len(targets[part]) == (6 if part == "tuning" else 24), "target partition coverage differs")
        for row, target in zip(rows, targets[part]):
            require(target["id"] == samples[row["id"]].sample_id and target["source_text"] == row["text"],
                    "formula target differs from its exact source")
            require(target["canonical_ir"] == {"rules": evidence[row["id"]]["compiler"]["rules"]},
                    "formula target differs from its compiler observation")
    return plan, prepared, fixture, samples, targets


def data_guard(directory, plan, prepared, prepared_sha):
    plan_guard(directory, plan, prepared["plan_sha256"])
    require(sha(directory / "prepared.json") == prepared_sha, "preparation receipt changed")
    for ref in prepared["files"].values():
        path = Path(ref["path"])
        require(path.stat().st_size == ref["bytes"] and sha(path) == ref["sha256"], "prepared artifact changed")


def require_completed_training(report):
    require(report["optimizer_steps"] == STEPS, "arm did not complete its fixed update budget")
    require(report["stopped_reason"] in ("optimizer_step_budget", "epoch_limit"), "arm stopped on a deadline")
    for name in ("training_after", "tuning"):
        metric = report[name]
        require(metric["complete"] and all(type(metric[field]) in (int,float) and math.isfinite(metric[field])
            for field in ("token_cross_entropy", "reconstruction_mse")), "loss observations incomplete or nonfinite")
    for group in ("projection", "decoder"):
        evidence = report["parameter_evidence"][group]
        require(evidence["parameter_update_l2"] > 0 and math.isfinite(evidence["parameter_update_l2"]),
                "parameter group did not receive a finite update")


def require_initial_pair(expected, candidate):
    require(expected == candidate, "paired initial core, model weights, config or vocabulary differ")


def train(directory):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas
    started = time.perf_counter()
    plan, prepared, fixture, samples, targets = prepared_inputs(directory)
    prepared_sha = sha(directory / "prepared.json")
    partition_samples = {p: [samples[row["id"]] for row in partition_rows(fixture,p)] for p in PARTITIONS}
    results = {}
    for seed in SEEDS:
        pair_identity = None
        results[str(seed)] = {}
        for arm in ARMS:
            data_guard(directory, plan, prepared, prepared_sha)
            fit = partition_samples["original_training"] + (partition_samples["added_wording"] if arm == "augmented48" else [])
            fit_targets = targets["original_training"] + (targets["added_wording"] if arm == "augmented48" else [])
            tune, tune_targets = partition_samples["tuning"], targets["tuning"]
            runtime = runtimes.open_runtime("legal_ir", "current_v2", **plan["profile"]["core_options"])
            original_core = raw(runtime.model.state.to_dict())
            checkpoint = learning.build_checkpoint(joint._core_binding(runtime.model),
                joint._rows(runtime.model, fit, fit_targets), joint._rows(runtime.model,tune,tune_targets),
                **dict(plan["profile"]["formula_options"], seed=seed))
            identity = {key: learning.checkpoint_digest(checkpoint[key]) for key in ("model_state","codec","binding","config")}
            if pair_identity is None:
                pair_identity = identity
            require_initial_pair(pair_identity, identity)
            runtime.model.attach_formula_checkpoint(checkpoint)
            trained = runtime.train(fit, validation_samples=tune, formula_targets=fit_targets,
                validation_formula_targets=tune_targets, epochs=1000, max_optimizer_steps=STEPS, max_seconds=MAX_SECONDS)
            try:
                require_completed_training(trained["report"])
            except Exception:
                write(directory / f"seed-{seed}-{arm}-incomplete-training.json", trained)
                raise
            require(raw(runtime.model.state.to_dict()) == original_core, "sparse core mutated")
            observations = dict(partition_samples, all_fit=fit)
            labels = dict(targets, all_fit=fit_targets)
            tick = time.perf_counter()
            outputs = {name: runtime.infer(values) for name, values in observations.items()}
            inference_seconds = time.perf_counter() - tick
            generation = {name: compare_free_running_formulas(outputs[name], labels[name],
                partition=name) for name in observations}
            require(all(m["valid_evaluation"] and m["operational_complete"] for m in generation.values()),
                    "free generation evidence incomplete")
            prefix = f"seed-{seed}-{arm}"
            head = runtime.model.save_formula_checkpoint(directory / (prefix + "-head.json"))
            require(head["sha256"] == trained["report"]["checkpoint_sha256"] and
                    all(value["checkpoint_sha256"] == head["sha256"] for value in outputs.values()), "checkpoint identity differs")
            reloaded = runtimes.open_runtime("legal_ir", "current_v2", **plan["profile"]["core_options"],
                formula_checkpoint=head["path"], formula_sha256=head["sha256"])
            require(reloaded.infer(tune) == outputs["tuning"], "reload changed predictions")
            resume = dict(validation_samples=tune, formula_targets=fit_targets, validation_formula_targets=tune_targets,
                          epochs=1, max_optimizer_steps=1, max_seconds=60)
            left, right = runtime.train(fit, **resume), reloaded.train(fit, **resume)
            require(left["report"]["optimizer_steps"] == right["report"]["optimizer_steps"] == 1,
                    "resume probe did not execute its update")
            require(left["checkpoint"] == right["checkpoint"], "resumed update differs from uninterrupted update")
            resumed_head = runtime.model.save_formula_checkpoint(directory / (prefix + "-resume-probe-head.json"))
            result = dict(seed=seed, arm=arm, initial_identity=identity, head=head, resume_probe_head=resumed_head,
                training_report=trained["report"], outputs=outputs, generation=generation,
                sample_counts={name:len(values) for name,values in observations.items()},
                added_wording_scope="trained paraphrases" if arm == "augmented48" else "unseen wording of trained actor-template pairs",
                original_training_scope="same 24 original training sources in both arms",
                tuning_scope="six development actor-template pairs; not independent qualification",
                row_presentations=STEPS*6, reload_prediction_exact=True, resume_checkpoint_exact=True,
                extra_resume_step_excluded_from_scored_head=True, core_sparse_state_unchanged=True,
                inference_seconds=inference_seconds,
                inference_wall_seconds_per_span=inference_seconds/sum(map(len,observations.values())), **FALSE)
            results[str(seed)][arm] = result
            write(directory / (prefix + "-result.json"), result)
            data_guard(directory,plan,prepared,prepared_sha)
            print(json.dumps(dict(seed=seed,arm=arm,training=generation["original_training"]["exact_reconstruction"],
                                  tuning=generation["tuning"]["exact_reconstruction"])),flush=True)
    frozen = write(directory / "frozen.json", dict(plan_sha256=prepared["plan_sha256"],
        candidate_reports={f"{seed}/{arm}": shared.reference(directory / f"seed-{seed}-{arm}-result.json")
                           for seed in SEEDS for arm in ARMS}, checkpoint_selection_performed=False, **FALSE))
    # Fixed original training panel, chosen before any fitting. Build outcomes
    # cannot select the arm or seed, and resumed probe heads are never used.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_decoded_schema as schemas
    original_rows = partition_rows(fixture,"original_training")
    schema_samples = [samples[next(row["id"] for row in original_rows if row["norm_template_id"] == name)]
                      for name in SCHEMA_TEMPLATES]
    schema_reports = {}
    for arm in ARMS:
        chosen = results[str(SEEDS[0])][arm]
        runtime = runtimes.open_runtime("legal_ir","current_v2",**plan["profile"]["core_options"],
            formula_checkpoint=chosen["head"]["path"],formula_sha256=chosen["head"]["sha256"])
        observation = schemas.validate_decoded_outputs(runtime,schema_samples,
            output_directory=directory/(arm+"-fixed-schema"),timeout_seconds=60)
        require(observation["checkpoint_sha256"] == chosen["head"]["sha256"], "schema used another checkpoint")
        schema_reports[arm] = observation
    schema_ok = all(shared.schema_checks_passed(value,4) for value in schema_reports.values())
    data_guard(directory,plan,prepared,prepared_sha)
    paired = {str(seed): {part: results[str(seed)]["augmented48"]["generation"][part]["exact_reconstruction"]["matched"]
                                  -results[str(seed)]["original24"]["generation"][part]["exact_reconstruction"]["matched"]
                         for part in ("original_training","added_wording","tuning")} for seed in SEEDS}
    write(directory / "report.json", dict(schema="formula-training-augmentation-comparison/v1",plan=plan,
        prepared=prepared, frozen=frozen, results=results, paired_exact_count_deltas=paired, schemas=schema_reports,
        operational_ok=schema_ok, seed_count=len(SEEDS), evaluation_targets_used=False,
        independent_heldout_evaluation=False, checkpoint_selection_performed=False,
        full_logic_floor_coverage=False, temporal_kind_sidecars_encoded_by_head=False,
        legal_ir_target_count=0, bridge_on_evaluate=None, elapsed_seconds=time.perf_counter()-started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024, **FALSE))
    require(schema_ok,"fixed schema execution incomplete; inspect retained report")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory",required=True,type=Path)
    parser.add_argument("--phase",choices=("all","prepare","embeddings","train"),default="all")
    args=parser.parse_args()
    directory=args.output_directory.resolve()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"]="0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"]="0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"]="0"
    if args.phase == "embeddings":
        shared.shared.produce_embeddings(directory,fixture_path=directory/"source-fixture.json")
    else:
        if args.phase in ("all","prepare"):
            prepare(directory)
        if args.phase in ("all","train"):
            train(directory)


if __name__ == "__main__":
    main()
