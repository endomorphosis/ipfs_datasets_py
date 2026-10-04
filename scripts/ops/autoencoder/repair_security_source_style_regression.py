#!/usr/bin/env python3
"""Train a bounded successor for the exposed Security style regression panel.

Only archived training/validation groups enter fitting. The historical primary
and canary partitions are development regressions, never fresh quality evidence.
Freeze the new model and development data before reopening those partitions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
BASE = Path(__file__).with_name("benchmark_source_training_v2.py")
spec = importlib.util.spec_from_file_location("legacy_regression_embedding_driver", BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
read = lambda path: json.loads(Path(path).read_bytes())
SCHEMA = "security-source-style-development-regression/v1"


def preparation_pins():
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_style_augmentation_384 as augmentation
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384 as original
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384_v2 as binding
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embeddings
    return {str(Path(module.__file__).resolve()): base.sha(module.__file__)
        for module in (augmentation, original, binding, embeddings)} | {
            str(Path(__file__).resolve()): base.sha(__file__), str(BASE): base.sha(BASE)}


def training_pins():
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as trainer
    return dict(preparation=preparation_pins(), training=trainer._pins())


def historical_guard(root, expected_freeze):
    if base.sha(root / "freeze.json") != expected_freeze:
        raise ValueError("historical checkpoint/development freeze differs")
    for name, digest in read(root / "freeze.json").items():
        path = (root / name).resolve()
        if root not in path.parents or base.sha(path) != digest:
            raise ValueError("historical frozen development artifact changed: " + name)


def model_rows(rows, *, groups=False):
    keys = ("id", "group_id", "split", "source_text", "embedding", "target") if groups else (
        "id", "source_text", "embedding", "target")
    return [{key: row[key] for key in keys} for row in rows]


def guard(folder):
    prepared = read(folder / "preparation.json")
    if prepared["producer"] != preparation_pins():
        raise ValueError("development preparation producer changed")
    historical_guard(Path(prepared["historical_directory"]), prepared["historical_freeze_sha256"])
    if base.sha(prepared["parent"]["path"]) != prepared["parent"]["sha256"]:
        raise ValueError("trained Legal parent changed")
    for name, digest in prepared["files"].items():
        if base.sha(folder / name) != digest:
            raise ValueError("prepared training/validation artifact changed")
    return prepared


def prepare(root, folder, historical_freeze):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_style_augmentation_384 as augmentation
    from ipfs_datasets_py.logic.formalization.autoencoder.security.source_program_binding_384_v2 import qualify_source_candidate
    if folder.exists():
        raise ValueError("fresh development-regression directory required")
    historical_guard(root, historical_freeze)
    producer = preparation_pins()
    archived = read(root / "preparation.json")
    original_train = read(root / "security_ir/train.json")["rows"]
    original_validation = read(root / "security_ir/validation.json")["rows"]
    seeds = [{key: row[key] for key in augmentation.FIELDS} for row in original_train if row["wording_style"] == 0]
    expanded = augmentation.augment_training_sources(seeds)
    bindings = {row["id"]: row for row in expanded["report"]["bindings"]}
    training = deepcopy(original_train)
    for row in expanded["rows"]:
        training.append({**row, "wording_style": bindings[row["id"]]["style"],
            "nuisance_variant": bindings[row["id"]]["nuisance_variant"]})
    validation, validation_bindings = deepcopy(original_validation), []
    for parent in original_validation:
        if parent["wording_style"] != 0:
            continue
        if parent["split"] != "validation":
            raise ValueError("validation lineage changed")
        for style in augmentation.TRAINING_STYLES:
            for variant in augmentation.NUISANCE_VARIANTS:
                text = augmentation.render_source_style(parent["source_text"], style, variant)
                identity = parent["id"] + f":validation-style-{style}:nuisance-{variant}"
                row = {key: deepcopy(parent[key]) for key in augmentation.FIELDS}
                row.update(id=identity, source_text=text, wording_style=style, nuisance_variant=variant)
                validation.append(row)
                validation_bindings.append(dict(id=identity, parent_id=parent["id"], group_id=parent["group_id"],
                    split="validation", style=style, nuisance_variant=variant))
    if (len(seeds), len(training), len(validation)) != (90, 1440, 480):
        raise ValueError("declared historical development counts differ")
    for rows in (training, validation):
        if len({row["id"] for row in rows}) != len(rows) or len({row["source_text"] for row in rows}) != len(rows):
            raise ValueError("duplicate source or row identity in development")
        for row in rows:
            if qualify_source_candidate(row["source_text"], row["target"])["status"] != "qualified":
                raise ValueError("development source does not preserve its exact typed target")
    embedding = base.embed({"train": training, "validation": validation}, "cuda")
    from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as grouped
    _, _, train_inventory = grouped._prepare("security_ir", model_rows(training, groups=True), "train")
    _, _, validation_inventory = grouped._prepare("security_ir", model_rows(validation, groups=True), "validation")
    grouped._exclude(train_inventory, validation_inventory)
    base.save(folder / "train.json", {"rows": training})
    base.save(folder / "validation.json", {"rows": validation})
    base.save(folder / "training-augmentation.json", expanded["report"])
    base.save(folder / "validation-variants.json", dict(rows=validation_bindings,
        training_only_augmentation_api_used=False, used_for_parameter_selection=True,
        historical_test_or_canary_groups_used=False))
    if producer != preparation_pins():
        raise ValueError("producer changed during development preparation")
    base.save(folder / "preparation.json", dict(schema=SCHEMA, producer=producer,
        historical_directory=str(root), historical_freeze_sha256=historical_freeze,
        parent=archived["parent"], embedding=embedding,
        files={path.name: base.sha(path) for path in folder.glob("*.json")},
        training_rows=len(training), validation_rows=len(validation), training_groups=len(train_inventory["group_id"]),
        validation_groups=len(validation_inventory["group_id"]), historical_test_and_canary_reopened=False,
        fresh_holdout_claimed=False))
    print(json.dumps({"prepared": str(folder), "training": len(training), "validation": len(validation)}), flush=True)


def fit(folder):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as trainer
    prepared = guard(folder)
    if any((folder / name).exists() for name in ("plan.json", "freeze.json", "evaluation-started.json")):
        raise ValueError("fresh prepared fitting directory required")
    pins = training_pins()
    base.save(folder / "plan.json", dict(schema=SCHEMA, producer=pins,
        ridges=list(trainer.structured.RIDGES), parent=prepared["parent"],
        objective="exposed_historical_style_regression_successor", fresh_holdout_claimed=False,
        historical_test_or_canary_used_for_selection=False, same_recipe_as_fresh_v4_comparison=True))
    started = time.perf_counter()
    result = trainer.train_grouped_source_decoder_384("security_ir",
        model_rows(read(folder / "train.json")["rows"], groups=True),
        model_rows(read(folder / "validation.json")["rows"], groups=True),
        parent_projection=prepared["parent"], config={"embedding_provenance": prepared["embedding"]})
    elapsed = time.perf_counter() - started
    checkpoint = base.save(folder / "checkpoint.json", result["checkpoint"])
    base.save(folder / "fit.json", dict(checkpoint=checkpoint, metrics=result["metrics"],
        recipe=result["report"], full_fit_seconds=elapsed))
    guard(folder)
    if pins != training_pins():
        raise ValueError("fitting producer changed")
    frozen = base.save(folder / "freeze.json", {path.name: base.sha(path) for path in folder.glob("*.json")})
    print(json.dumps({"checkpoint": checkpoint, "freeze": frozen,
        "validation": result["metrics"]["selected_validation"], "full_fit_seconds": elapsed}), flush=True)


def evaluate(folder, freeze_sha, lake_executable):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as numerical
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_runtime_384 as consumer
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as gate
    prepared = guard(folder)
    if (folder / "evaluation-started.json").exists():
        raise ValueError("development regression evaluation is one-shot")
    if base.sha(folder / "freeze.json") != freeze_sha or read(folder / "plan.json")["producer"] != training_pins():
        raise ValueError("candidate freeze or fitting producer changed")
    for name, digest in read(folder / "freeze.json").items():
        if base.sha(folder / name) != digest:
            raise ValueError("frozen candidate artifact changed")
    base.save(folder / "evaluation-started.json", dict(candidate_frozen_before_historical_partition_reopen=True,
        purpose="development_regression_only", fresh_holdout_claimed=False))
    checkpoint_path = folder / "checkpoint.json"
    checkpoint = read(checkpoint_path)
    runtime = consumer.load_source_program_decoder_384(checkpoint_path, expected_sha256=base.sha(checkpoint_path))
    root = Path(prepared["historical_directory"])
    results, inputs = {}, {}
    for partition in ("test", "canary"):
        path = root / ("security_ir/" + partition + ".json")
        inputs[str(path)] = base.sha(path)
        rows = read(path)["rows"]
        decoded = runtime.infer(base.model_rows(rows, targets=False))
        scored = numerical.evaluate(checkpoint, model_rows(rows))
        if [row["candidate_ir"] for row in decoded["rows"]] != [row["candidate_ir"] for row in scored["rows"]]:
            raise ValueError("target-free candidate replay changed")
        receipts = []
        for start in range(0, len(rows), 64):
            subset = rows[start:start+64]
            predictions = {**decoded, "rows": decoded["rows"][start:start+64]}
            sources = [{key: row[key] for key in ("id", "source_text")} for row in subset]
            directory = folder / (partition + "-lake-" + str(start // 64))
            handle = consumer.build_decoded_source_program_lake(predictions, sources,
                lake_executable=lake_executable, output_directory=directory)
            gate_rows = [dict(id=p["id"], source_text=s["source_text"], candidate_ir=p["candidate_ir"])
                for s, p in zip(sources, predictions["rows"])]
            receipt = gate.verify_source_program_lake(handle, gate_rows)
            receipts.append(dict(path=str(directory / "receipt.json"), sha256=base.sha(directory / "receipt.json"),
                count=receipt["count"], status=receipt["status"], backend_executed=receipt["backend_executed"],
                lake_status_counts=dict(Counter(row["lake_status"] for row in receipt["rows"]))))
        by_style = {}
        for original, predicted in zip(rows, scored["rows"]):
            count = by_style.setdefault(str(original["wording_style"]), dict(count=0, exact=0))
            count["count"] += 1; count["exact"] += int(predicted["exact_target"])
        statuses = Counter()
        for receipt in receipts:
            statuses.update(receipt["lake_status_counts"])
        artifact = base.save(folder / (partition + "-evaluation.json"), dict(reconstruction=scored, decoded=decoded))
        results[partition] = dict(count=len(rows), exact=scored["exact_targets"], by_style=by_style,
            source_status_counts=dict(Counter(row.get("source_contract", {}).get("status", "no_candidate") for row in decoded["rows"])),
            lake_status_counts=dict(statuses), actual_lake_builds=sum(row["backend_executed"] for row in receipts),
            lake_receipts=receipts, artifact=artifact, purpose="exposed_development_regression_only")
        print(json.dumps({"partition": partition, **{key: results[partition][key]
            for key in ("count", "exact", "by_style", "source_status_counts", "lake_status_counts")}}), flush=True)
    guard(folder)
    for path, digest in inputs.items():
        if base.sha(path) != digest:
            raise ValueError("historical regression partition changed during replay")
    base.save(folder / "report.json", dict(schema=SCHEMA, checkpoint={"path": str(checkpoint_path),
        "sha256": base.sha(checkpoint_path)}, candidate_freeze_sha256=freeze_sha,
        producer=training_pins(), historical_partition_sha256=inputs, results=results,
        fresh_holdout_claimed=False, historical_test_or_canary_used_for_fitting=False,
        historical_canary_failures_informed_experiment_design=True, proof_authority=False,
        source_semantics_verified=False, checkpoint_promoted=False, publication_performed=False,
        scope="development regression successor; fresh v4 compositions supply separate independent quality evidence"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "fit", "evaluate"))
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--historical-directory", type=Path)
    parser.add_argument("--historical-freeze-sha256")
    parser.add_argument("--freeze-sha256")
    parser.add_argument("--lake-executable", type=Path)
    args = parser.parse_args()
    folder = args.output_directory.resolve()
    if args.phase == "prepare":
        if args.historical_directory is None or not args.historical_freeze_sha256:
            parser.error("prepare needs historical directory and freeze SHA")
        prepare(args.historical_directory.resolve(), folder, args.historical_freeze_sha256)
    elif args.phase == "fit":
        fit(folder)
    else:
        if not args.freeze_sha256 or args.lake_executable is None:
            parser.error("evaluate needs candidate freeze SHA and native Lake executable")
        evaluate(folder, args.freeze_sha256, args.lake_executable.resolve())
