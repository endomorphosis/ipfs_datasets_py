#!/usr/bin/env python3
"""Frozen comparison of source-style augmentation and a shared fast ridge path.

Authored development data only. Parent, producers and all fits are frozen
before generating test compositions. Every test row is retained in scoring.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = Path(__file__).with_name("benchmark_source_training_v2.py")
FIXTURE = REPO / "tests/fixtures/logic/source_security_styles_v4.py"
base = _module("security_styles_base", BASE)
panel = _module("security_styles_panel", FIXTURE)
read = lambda path: json.loads(Path(path).read_bytes())
ARMS = ("baseline_reference", "baseline_ridge_path", "style_augmented_reference", "style_augmented_ridge_path")


def _pins():
    from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as grouped
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as fast
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_style_augmentation_384 as augmentation
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384_v2 as binding
    return dict(driver=base.sha(__file__), fixture=base.sha(FIXTURE), embedding_driver=base.sha(BASE),
        fast_trainer=base.sha(fast.__file__), augmentation=base.sha(augmentation.__file__),
        source_binding=base.sha(binding.__file__), grouped_recipe=grouped._pins(),
        scope="named producers and their declared native/numerical dependencies")


def _grouped(rows):
    keys = ("id", "group_id", "split", "source_text", "embedding", "target")
    return [{key: row[key] for key in keys} for row in rows]


def _guard(folder):
    prepared = read(folder / "preparation.json")
    if prepared["producer"] != _pins() or base.sha(prepared["parent"]["path"]) != prepared["parent"]["sha256"]:
        raise ValueError("producer or Legal parent changed")
    for name, expected in prepared["files"].items():
        if base.sha(folder / name) != expected:
            raise ValueError("development artifact changed")
    return prepared


def prepare(folder, parent):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_style_augmentation_384 as augmentation
    from ipfs_datasets_py.logic.formalization.autoencoder.security.source_program_binding_384_v2 import qualify_source_candidate
    if folder.exists():
        raise ValueError("fresh experiment directory required")
    producer = _pins()
    training = panel.rows("train", styles=(0, 1, 2, 3))
    seeds = [{key: row[key] for key in augmentation.FIELDS} for row in panel.rows("train", styles=(0,))]
    expanded = augmentation.augment_training_sources(seeds)
    by_id = {row["id"]: row for row in expanded["report"]["bindings"]}
    for row in expanded["rows"]:
        training.append({**row, "wording_style": by_id[row["id"]]["style"]})
    tuning = panel.rows("validation")
    for row in training + tuning:
        if qualify_source_candidate(row["source_text"], row["target"])["status"] != "qualified":
            raise ValueError("authored source/target is not independently source-qualified: " + row["id"])
    embedding = base.embed({"training": training, "tuning": tuning}, "cuda")
    base.save(folder / "train.json", {"rows": training})
    base.save(folder / "validation.json", {"rows": tuning})
    base.save(folder / "augmentation.json", expanded["report"])
    if producer != _pins():
        raise ValueError("producer changed during preparation")
    files = {name: base.sha(folder / name) for name in ("train.json", "validation.json", "augmentation.json")}
    prepared = dict(schema="security-source-style-preparation/v4", producer=producer,
        parent={"path": str(parent), "sha256": base.sha(parent)}, files=files,
        corpus=panel.manifest(), embedding=embedding, heldouts_generated=False,
        training_rows=len(training), baseline_rows=sum(row["wording_style"] < 4 for row in training),
        validation_rows=len(tuning), old_canaries_used_for_fitting=False)
    base.save(folder / "preparation.json", prepared)
    print(json.dumps({key: prepared[key] for key in ("training_rows", "baseline_rows", "validation_rows")}), flush=True)


def fit(folder):
    import torch
    import numpy as np
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as reference
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as fast
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as runtime
    prepared = _guard(folder)
    if any((folder / name).exists() for name in ("plan.json", "freeze.json", "evaluation-started.json")):
        raise ValueError("fresh prepared experiment required")
    base.save(folder / "plan.json", dict(schema="security-source-style-plan/v4", producer=_pins(), arms=list(ARMS),
        repetitions=3, inference_repetitions=5, ridges=list(runtime.RIDGES),
        selection="validation exact then valid leaf accuracy; smallest ridge on ties",
        validation_styles=panel.manifest()["validation_styles"],
        historical_test_data_used_for_fitting=False, fresh_holdout_generated_after_freeze=True,
        promoted_checkpoint=False, real_world_corpus=False))
    training = read(folder / "train.json")["rows"]
    tuning = _grouped(read(folder / "validation.json")["rows"])
    records, states, selected = [], {}, {}
    for repetition in range(3):
        for arm in ARMS[repetition:] + ARMS[:repetition]:
            rows = training if arm.startswith("style_augmented") else [row for row in training if row["wording_style"] < 4]
            trainer = reference if arm.endswith("reference") else fast
            start = time.perf_counter()
            result = trainer.train_grouped_source_decoder_384("security_ir", _grouped(rows), tuning,
                parent_projection=prepared["parent"], config={"embedding_provenance": prepared["embedding"]})
            elapsed = time.perf_counter() - start
            checkpoint = result["checkpoint"]
            state = (checkpoint["head_sha256"], checkpoint["projection_sha256"], checkpoint["training"]["selected_ridge"])
            if states.setdefault(arm, state) != state:
                raise ValueError("repeated fit weights differ")
            if repetition == 0:
                selected[arm] = checkpoint
            record = dict(arm=arm, repetition=repetition, full_fit_seconds=elapsed, training_rows=len(rows),
                training_groups=len({row["group_id"] for row in rows}),
                checkpoint=base.save(folder / f"{arm}-{repetition}-checkpoint.json", checkpoint),
                recipe=base.save(folder / f"{arm}-{repetition}-recipe.json", result["report"]),
                metrics=result["metrics"])
            records.append(record)
            print(json.dumps({"arm": arm, "repetition": repetition, "full_fit_seconds": elapsed,
                "validation_exact": checkpoint["training"]["selected_validation"]["exact_targets"]}), flush=True)
    equivalence = {}
    for prefix in ("baseline", "style_augmented"):
        a, b = selected[prefix + "_reference"], selected[prefix + "_ridge_path"]
        aw, bw = np.asarray(a["head_state"]["weights"]), np.asarray(b["head_state"]["weights"])
        if not np.allclose(aw, bw, rtol=1e-6, atol=1e-8):
            raise ValueError("fast fit is not numerically equivalent to reference: " + prefix)
        equivalence[prefix] = dict(max_abs_weight_difference=float(np.abs(aw-bw).max()),
            relative_tolerance=1e-6, absolute_tolerance=1e-8,
            tuning_metrics_equal=a["training"]["selected_validation"] == b["training"]["selected_validation"],
            inherited_projection_equal=a["projection_state"] == b["projection_state"])
        if not equivalence[prefix]["tuning_metrics_equal"] or not equivalence[prefix]["inherited_projection_equal"]:
            raise ValueError("reference tuning or inherited projection differs")
    base.save(folder / "reference-equivalence.json", equivalence)
    base.save(folder / "fits.json", records)
    _guard(folder)
    frozen = base.save(folder / "freeze.json", {str(path.relative_to(folder)): base.sha(path) for path in folder.glob("*.json")})
    print(json.dumps({"freeze": frozen}), flush=True)


def _score(checkpoint, rows):
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as runtime
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import SourceProgramDecoder384
    scored = runtime.evaluate(checkpoint, base.model_rows(rows))
    # Qualification receives a separate target-free replay, never scored rows.
    decoded = SourceProgramDecoder384(runtime.Runtime(checkpoint), checkpoint_sha256=runtime.digest(checkpoint)).infer(
        base.model_rows(rows, targets=False))
    if [row["candidate_ir"] for row in decoded["rows"]] != [row["candidate_ir"] for row in scored["rows"]]:
        raise ValueError("target-free replay differs")
    styles = defaultdict(lambda: dict(count=0, exact=0, source_qualified=0))
    field_errors = Counter()
    operator_type_conflicts = 0
    for source, evaluation, candidate in zip(rows, scored["rows"], decoded["rows"]):
        row = styles[str(source["wording_style"])]
        row["count"] += 1
        row["exact"] += int(evaluation["exact_target"])
        row["source_qualified"] += int(candidate.get("source_contract", {}).get("status") == "qualified")
        predicted = candidate.get("candidate_ir")
        if predicted is not None:
            actual_leaves = runtime._scalar_leaves(predicted)
            for path, value in runtime._scalar_leaves(source["target"]).items():
                if actual_leaves.get(path) != value:
                    field_errors["/".join(map(str, path))] += 1
            doc = predicted["document"]
            expected_type = "integer" if doc["operator"] in ("+", "-", "*") else "boolean"
            operator_type_conflicts += int(doc["type_ref"] != expected_type)
    summary = dict(count=len(rows), exact=scored["exact_targets"], by_style=dict(styles),
        field_errors=dict(field_errors), operator_type_conflicts=operator_type_conflicts,
        source_status_counts=dict(Counter(row.get("source_contract", {}).get("status", "no_candidate") for row in decoded["rows"])),
        worst_style_exact_rate=min(value["exact"] / value["count"] for value in styles.values()))
    return summary, decoded, scored


def evaluate(folder, freeze_sha, lake_executable):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as runtime
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import build_decoded_source_program_lake
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_lake_384 import verify_source_program_lake
    prepared = _guard(folder)
    if (folder / "evaluation-started.json").exists():
        raise ValueError("evaluation is one-shot")
    if base.sha(folder / "freeze.json") != freeze_sha:
        raise ValueError("freeze identity differs")
    for name, digest in read(folder / "freeze.json").items():
        if base.sha(folder / name) != digest:
            raise ValueError("frozen artifact changed")
    base.save(folder / "evaluation-started.json", dict(all_fits_frozen_before_generation=True, freeze_sha256=freeze_sha))
    partitions = {split: panel.rows(split) for split in ("test", "canary")}
    embedding = base.embed(partitions, "cuda")
    for name, rows in partitions.items():
        base.save(folder / (name + ".json"), {"rows": rows})
    # New partitions must exclude every declared development group, exact and
    # normalized source, numerical vector, and row ID before they are scored.
    from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as audit
    development = read(folder / "train.json")["rows"] + read(folder / "validation.json")["rows"]
    _, _, known = audit._prepare("security_ir", [{**row, "split": "train"} for row in _grouped(development)], "train")
    for rows in partitions.values():
        _, _, unseen = audit._prepare("security_ir", [{**row, "split": "validation"} for row in _grouped(rows)], "validation")
        audit._exclude(known, unseen)
    fit_records = read(folder / "fits.json")
    summaries = []
    for arm in ARMS:
        checkpoint_path = folder / (arm + "-0-checkpoint.json")
        checkpoint = read(checkpoint_path)
        timings = [row["full_fit_seconds"] for row in fit_records if row["arm"] == arm]
        size = next(row["training_rows"] for row in fit_records if row["arm"] == arm)
        entry = dict(arm=arm, checkpoint={"path": str(checkpoint_path), "sha256": base.sha(checkpoint_path)},
            full_fit_seconds=timings, median_full_fit_seconds=statistics.median(timings), training_rows=size,
            training_rows_per_second=size / statistics.median(timings),
            training_groups_per_second=21 / statistics.median(timings), partitions={})
        decoder = runtime.Runtime(checkpoint)
        inference_inputs = base.model_rows(partitions["test"], targets=False)
        decoder.infer(inference_inputs)
        inference_seconds = []
        for _ in range(5):
            tick = time.perf_counter()
            decoder.infer(inference_inputs)
            inference_seconds.append(time.perf_counter() - tick)
        entry.update(inference_seconds=inference_seconds,
            median_inference_rows_per_second=len(inference_inputs) / statistics.median(inference_seconds),
            inference_timing_scope="warm target-free decoder and native candidate validation; excludes embedding, source qualification, loading and Lake")
        for split, rows in partitions.items():
            scores, decoded, evaluated = _score(checkpoint, rows)
            scores["artifact"] = base.save(folder / f"{arm}-{split}-evaluation.json", dict(reconstruction=evaluated, decoded=decoded))
            if arm == "style_augmented_ridge_path":
                receipts = []
                for start in range(0, len(rows), 64):
                    subset = rows[start:start+64]
                    predictions = {**decoded, "rows": decoded["rows"][start:start+64]}
                    sources = [{key: row[key] for key in ("id", "source_text")} for row in subset]
                    out = folder / f"{arm}-{split}-lake-{start // 64}"
                    handle = build_decoded_source_program_lake(predictions, sources, lake_executable=lake_executable, output_directory=out)
                    inputs = [dict(id=source["id"], source_text=source["source_text"], candidate_ir=prediction["candidate_ir"])
                        for source, prediction in zip(sources, predictions["rows"])]
                    checked = verify_source_program_lake(handle, inputs)
                    receipts.append(dict(path=str(out / "receipt.json"), sha256=base.sha(out / "receipt.json"),
                        count=checked["count"], status=checked["status"], backend_executed=checked["backend_executed"],
                        passed=sum(row["lake_status"] == "passed" for row in checked["rows"]),
                        blocked=sum(row["lake_status"] == "blocked" for row in checked["rows"]),
                        lake_status_counts=dict(Counter(row["lake_status"] for row in checked["rows"]))))
                all_statuses = Counter()
                for batch in receipts:
                    all_statuses.update(batch["lake_status_counts"])
                if sum(all_statuses.values()) != len(rows):
                    raise ValueError("Lake accounting lost rows")
                scores["lake"] = dict(batches=receipts, passed=sum(row["passed"] for row in receipts),
                    blocked=sum(row["blocked"] for row in receipts), lake_status_counts=dict(all_statuses),
                    actual_builds=sum(row["backend_executed"] for row in receipts))
            entry["partitions"][split] = scores
            print(json.dumps(dict(arm=arm, partition=split, count=scores["count"], exact=scores["exact"],
                source_status_counts=scores["source_status_counts"], lake=scores.get("lake"))), flush=True)
        summaries.append(entry)
    _guard(folder)
    base.save(folder / "report.json", dict(schema="security-source-style-comparison/v4", rows=summaries,
        producer=_pins(), freeze_sha256=freeze_sha, development_embedding=prepared["embedding"], test_embedding=embedding,
        corpus=panel.manifest(), old_canaries_used_for_training=False, source_semantics_verified=False,
        proof_authority=False, checkpoint_promoted=False, test_used_for_selection=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "fit", "evaluate"))
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--freeze-sha256")
    parser.add_argument("--lake-executable")
    args = parser.parse_args()
    folder = args.output_directory.resolve()
    if args.phase == "prepare":
        if args.parent is None:
            parser.error("prepare requires --parent")
        prepare(folder, args.parent.resolve())
    elif args.phase == "fit":
        fit(folder)
    else:
        if not args.freeze_sha256 or not args.lake_executable:
            parser.error("evaluate requires --freeze-sha256 and --lake-executable")
        evaluate(folder, args.freeze_sha256, args.lake_executable)
