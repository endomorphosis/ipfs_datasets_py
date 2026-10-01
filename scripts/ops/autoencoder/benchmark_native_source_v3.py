#!/usr/bin/env python3
"""Frozen paired comparison of grouped source-variant training.

All four domains share the same inherited 384D structured decoder. Baseline
uses two source styles; augmentation uses four. Model selection precedes test
generation. Source qualification evaluates predictions without gold access.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


BASE = Path(__file__).with_name("benchmark_source_training_v2.py")
FIXTURE = REPO / "tests/fixtures/logic/source_reconstruction_v3.py"
base = module("native_source_base", BASE)
panel = module("native_source_panel_v3", FIXTURE)
read = lambda path: json.loads(Path(path).read_bytes())


def pins():
    from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as recipe
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384 as security
    from ipfs_datasets_py.logic.intent_ir.formalize import rich_logic
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_grammar_decoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime
    from ipfs_datasets_py.logic.software_verification import source_adapters, syntax_bridge, program
    return dict(driver=base.sha(__file__), fixture=base.sha(FIXTURE), embedding_driver=base.sha(BASE),
        recipe=recipe._pins(), security_binding=base.sha(security.__file__),
        projection_helper=base.sha(Path(__file__).with_name("benchmark_source_projection_384.py")),
        intent_projection=base.sha(rich_logic.__file__), legal_grammar=base.sha(legal_ir_grammar_decoder.__file__),
        embedding_runtime=base.sha(autoencoder_embedding_runtime.__file__),
        security_native={name: base.sha(value.__file__) for name, value in
                         (("source_adapters", source_adapters), ("syntax_bridge", syntax_bridge), ("program", program))},
        pin_scope="named_producer_and_native_contract_modules_not_all_transitive_python_dependencies")


def grouped(rows):
    keys = ("id", "group_id", "split", "source_text", "embedding", "target")
    return [{key: row[key] for key in keys} for row in rows]


def native_qualification(domain, rows, predictions):
    from ipfs_datasets_py.logic.formalization.autoencoder import complete_training as api
    if any(set(row) != {"id", "source_text"} for row in rows):
        raise ValueError("qualification source rows cannot contain gold or embeddings")
    if any(set(row) & {"exact_target", "within_training_coverage", "target_coverage_reason", "target"}
           for row in predictions["rows"]):
        raise ValueError("qualification cannot consume evaluated predictions")
    if domain in ("security_ir", "ui_ux_ir"):
        result = api.qualify_source_candidates_384(predictions,
            [{"id": row["id"], "source_text": row["source_text"]} for row in rows])
        return [dict(id=row["id"], qualification=row.get("source_contract", {"status": "no_candidate"}))
                for row in result["rows"]]
    projector = module("native_projection_helpers", Path(__file__).with_name("benchmark_source_projection_384.py"))
    result = []
    for source, prediction in zip(rows, predictions["rows"]):
        candidate = prediction["candidate_ir"]
        try:
            value = (projector.intent_projection(candidate, source["source_text"]) if domain == "intent_ir"
                     else projector.legal_projection(candidate)) if candidate is not None else {"status": "no_candidate"}
        except (ValueError, TypeError, KeyError) as error:
            value = {"status": "unsupported", "reason": str(error)[:256]}
        result.append(dict(id=source["id"], qualification=value))
    return result


def guard(folder):
    preparation = read(folder / "preparation.json")
    if preparation["fixture_sha256"] != base.sha(FIXTURE):
        raise ValueError("fixture changed")
    if preparation["parent"]["sha256"] != base.sha(preparation["parent"]["path"]):
        raise ValueError("parent changed")
    for name, digest in preparation["files"].items():
        if base.sha(folder / name) != digest:
            raise ValueError("development input changed")
    return preparation


def prepare(folder, parent):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2 as shared
    from ipfs_datasets_py.logic.formalization.autoencoder import complete_training as api
    if folder.exists():
        raise ValueError("fresh experiment directory required")
    parts = {(domain, split): panel.rows(domain, split) for domain in panel.DOMAINS for split in ("train", "validation")}
    for (domain, _), rows in parts.items():
        for row in rows:
            shared.validate_target(domain, row["target"])
            if domain == "ui_ux_ir":
                api._check_ui_target(row["target"])
            if domain == "security_ir":
                from ipfs_datasets_py.logic.formalization.autoencoder.security.source_program_binding_384 import qualify_source_candidate
                checked = qualify_source_candidate(row["source_text"], row["target"])
                if checked["status"] != "qualified":
                    raise ValueError((row["id"], checked["reason"]))
    embedding = base.embed(parts, "cuda")
    files = {}
    for (domain, split), rows in parts.items():
        path = folder / domain / (split + ".json")
        base.save(path, {"rows": rows})
        files[str(path.relative_to(folder))] = base.sha(path)
    base.save(folder / "preparation.json", dict(schema="native-source-preparation/v3",
        fixture_sha256=base.sha(FIXTURE), parent={"path": str(parent), "sha256": base.sha(parent)},
        files=files, panel=panel.manifest(), embedding=embedding, heldouts_generated=False))
    print(json.dumps({"development_rows": embedding["rows"], "embedding_rows_per_second": embedding["encode_rows_per_second"]}), flush=True)


def fit(folder):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import complete_training as api
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as runtime
    prepared = guard(folder)
    if any((folder / name).exists() for name in ("plan.json", "freeze.json", "evaluation-started.json")):
        raise ValueError("fit requires a fresh prepared experiment")
    base.save(folder / "plan.json", dict(producer=pins(), arms={"baseline": [0, 1], "augmented": [0, 1, 2, 3]},
        repetitions=3, inference_repetitions=5, selection="tuning exact reconstruction then valid scalar accuracy",
        inference_timing_scope="warm raw decoder, native validation, no embedding/load/source qualification",
        source_qualification_uses_gold=False, configurations={"ridges": list(runtime.RIDGES)}))
    records = []
    for domain in panel.DOMAINS:
        training = read(folder / domain / "train.json")["rows"]
        tuning = read(folder / domain / "validation.json")["rows"]
        states = {}
        for repetition in range(3):
            arms = ("baseline", "augmented") if repetition % 2 == 0 else ("augmented", "baseline")
            for arm in arms:
                selected_rows = training if arm == "augmented" else [row for row in training if row["wording_style"] < 2]
                tick = time.perf_counter()
                result = api.train_grouped_source_decoder_384(domain, grouped(selected_rows), grouped(tuning),
                    parent_projection=prepared["parent"], config={"embedding_provenance": prepared["embedding"]})
                seconds = time.perf_counter() - tick
                checkpoint = result["checkpoint"]
                state = (checkpoint["head_sha256"], checkpoint["projection_sha256"], checkpoint["training"]["selected_ridge"])
                if states.setdefault(arm, state) != state:
                    raise ValueError("repeated deterministic fits differ")
                identity = base.save(folder / domain / f"{arm}-{repetition}-checkpoint.json", checkpoint)
                report = base.save(folder / domain / f"{arm}-{repetition}-recipe.json", result["report"])
                records.append(dict(domain=domain, arm=arm, repetition=repetition, checkpoint=identity,
                    recipe=report, full_fit_seconds=seconds, training_rows=len(selected_rows), training_groups=15,
                    tuning=result["metrics"]["selected_validation"]))
                print(json.dumps({"domain": domain, "arm": arm, "repetition": repetition,
                    "fit_seconds": seconds, "tuning_exact": result["metrics"]["selected_validation"]["exact_targets"]}), flush=True)
    guard(folder)
    if read(folder / "plan.json")["producer"] != pins():
        raise ValueError("producer changed during fitting")
    base.save(folder / "fits.json", records)
    frozen = base.save(folder / "freeze.json", {str(p.relative_to(folder)): base.sha(p) for p in folder.rglob("*.json")})
    print(json.dumps({"freeze": frozen}), flush=True)


def evaluate(folder, freeze_sha):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as runtime
    prepared = guard(folder)
    if (folder / "evaluation-started.json").exists():
        raise ValueError("evaluation is one-shot")
    if base.sha(folder / "freeze.json") != freeze_sha or read(folder / "plan.json")["producer"] != pins():
        raise ValueError("freeze or producer differs")
    for name, digest in read(folder / "freeze.json").items():
        if base.sha(folder / name) != digest:
            raise ValueError("frozen artifact differs")
    base.save(folder / "evaluation-started.json", {"all_fits_precede_holdout_generation": True})
    parts = {(domain, split): panel.rows(domain, split) for domain in panel.DOMAINS for split in ("test", "canary")}
    embedding = base.embed(parts, "cuda")
    for (domain, split), rows in parts.items():
        base.save(folder / domain / (split + ".json"), {"rows": rows})
    records = read(folder / "fits.json")
    summary = []
    for fit_record in [row for row in records if row["repetition"] == 0]:
        domain, arm = fit_record["domain"], fit_record["arm"]
        checkpoint = read(fit_record["checkpoint"]["path"])
        scores = {}
        for split in ("test", "canary"):
            rows = parts[domain, split]
            report = runtime.evaluate(checkpoint, base.model_rows(rows))
            # Qualification sees only source text and decoded output. Never gold.
            predictions = runtime.Runtime(checkpoint).infer(base.model_rows(rows, targets=False))
            if [row["candidate_ir"] for row in predictions["rows"]] != [row["candidate_ir"] for row in report["rows"]]:
                raise ValueError("target-free replay differs")
            qualifications = native_qualification(domain,
                [{"id": row["id"], "source_text": row["source_text"]} for row in rows], predictions)
            statuses = dict(Counter(x["qualification"]["status"] for x in qualifications))
            counts = {key: value for key, value in report.items() if key != "rows"}
            counts["native_qualification_statuses"] = statuses
            artifact = base.save(folder / domain / f"{arm}-{split}-evaluation.json",
                dict(reconstruction=report, qualifications=qualifications))
            scores[split] = dict(metrics=counts, artifact=artifact)
        rows = parts[domain, "test"]
        loaded = runtime.Runtime(checkpoint)
        inputs = base.model_rows(rows, targets=False)
        loaded.infer(inputs)
        times = []
        for _ in range(5):
            tick = time.perf_counter()
            loaded.infer(inputs)
            times.append(time.perf_counter() - tick)
        fits = [row["full_fit_seconds"] for row in records if row["domain"] == domain and row["arm"] == arm]
        median = statistics.median(fits)
        summary.append(dict(domain=domain, arm=arm, scores=scores, checkpoint=fit_record["checkpoint"],
            median_full_fit_seconds=median, fit_seconds=fits, training_variants=fit_record["training_rows"],
            training_variants_per_second=fit_record["training_rows"] / median, training_groups_per_second=15 / median,
            median_inference_rows_per_second=len(rows) / statistics.median(times), inference_seconds=times))
        print(json.dumps({"domain": domain, "arm": arm,
            "test_exact": scores["test"]["metrics"]["exact_targets"],
            "canary_exact": scores["canary"]["metrics"]["exact_targets"],
            "test_qualification": scores["test"]["metrics"]["native_qualification_statuses"]}), flush=True)
    base.save(folder / "report.json", dict(schema="native-source-comparison/v3", rows=summary,
        freeze_sha256=freeze_sha, producer=pins(), development_embedding=prepared["embedding"], test_embedding=embedding,
        corpus=panel.manifest(), canary_independent_groups=False, all_repeated_weights_identical=True,
        source_semantics_verified=False, proof_authority=False, models_promoted=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "fit", "evaluate"))
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--parent-checkpoint", type=Path)
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args()
    folder = args.output_directory.resolve()
    if args.phase == "prepare":
        prepare(folder, args.parent_checkpoint.resolve())
    elif args.phase == "fit":
        fit(folder)
    else:
        evaluate(folder, args.freeze_sha256)
