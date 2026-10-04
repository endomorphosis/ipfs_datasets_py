#!/usr/bin/env python3
"""Matched warm-start span decoders conditioned on real frozen LegalIR vectors."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import hashlib
import math
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.compare_legal_decoder_architectures import read, write, sha, require, score
from scripts.ops.legal_ir.run_legal_span_retrieval_experiment import digest, fitting_rows, generate
from scripts.ops.legal_ir.run_legal_structured_retrieval_experiment import select_stage

ARMS = {"source_only": (False, "raw384"), "raw384": (True, "raw384"),
        "core384": (True, "core384"), "trained384": (True, "trained384")}
FALSE = {"qualified": False, "admitted": False, "semantic_correctness_verified": False,
         "production_ready": False, "test_used_for_selection": False}


def fit_branch(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as continuation
    outer = continuation.load_checkpoint(job["parent"]["path"], expected_sha256=job["parent"]["sha256"])
    parent = outer["base_checkpoint"]
    train, tune = fitting_rows(job["train"], job["train_context"]), fitting_rows(job["tuning"], job["tuning_context"])
    checkpoint = continuation.build_checkpoint(parent, train, tune, latent_enabled=job["enabled"],
        seed=job["seed"], context_contract=job["contract"], learning_rate=.001, batch_size=12)
    initial = continuation.initial_model_digest(checkpoint)
    folder = Path(job["directory"])
    stages = []
    for ordinal in (1, 2):
        result = continuation.train_decoder(checkpoint, train, tune, max_steps=job["stage_steps"], max_seconds=300)
        checkpoint = result["checkpoint"]
        steps = continuation.optimizer_steps(checkpoint)
        require(steps == ordinal * job["stage_steps"], "equal complete stage budgets required")
        checkpoint_ref = continuation.save_checkpoint(checkpoint, folder / f"checkpoint-{steps}.json")
        report_ref = write(folder / f"training-{steps}.json", result["report"])
        generation = generate(continuation.SpanContinuationDecoder(checkpoint), job["tuning"], job["tuning_context"])
        metric = score(generation["rows"], job["tuning"], job["tuning"])
        tuning_ref = write(folder / f"tuning-{steps}.json", {"generation": generation, "metrics": metric})
        stages.append({"new_optimizer_steps": steps, "checkpoint": checkpoint_ref,
                       "training_report": report_ref, "tuning_evaluation": tuning_ref,
                       "tuning_exact": metric["exact"], "tuning_count": metric["count"]})
    selected = select_stage(stages)
    selection = {"name": folder.name, "arm": job["arm"], "seed": job["seed"],
        "context_mode": job["mode"], "latent_enabled": job["enabled"], "context_contract": job["contract"],
        "source_parent_wrapper": job["parent"], "source_parent_base_sha256": digest(parent),
        "historical_parent_optimizer_updates": outer["source_parent_optimizer_steps"] + parent["progress"]["optimizer_steps"],
        "initial_model_sha256": initial, "stages": stages, "total_new_training_steps": 2 * job["stage_steps"],
        "selected_new_steps": selected["new_optimizer_steps"], "checkpoint": selected["checkpoint"],
        "selection_tuning_exact": selected["tuning_exact"], **FALSE}
    write(folder / "selection.json", selection)
    return selection


def verify_source_inputs(corpus, *, expected_counts=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    splits = corpus["splits"]
    require({k: len(v) for k, v in splits.items()} == (expected_counts or {"train": 1152, "tuning": 96, "challenge": 192, "oov": 45}),
            "frozen expanded input counts required")
    ids, source_splits, group_splits = set(), {}, {}
    for split, rows in splits.items():
        for row in rows:
            require(row["id"] not in ids, "duplicate input identity")
            ids.add(row["id"])
            require(hashlib.sha256(row["source_text"].encode()).hexdigest() == row["source_sha256"], "source hash differs")
            require(type(row["embedding"]) is list and len(row["embedding"]) == 384 and
                    all(type(v) in (int, float) and math.isfinite(v) for v in row["embedding"]),
                    "finite native384 input required")
            if split in ("challenge", "oov"):
                require("canonical_ir" not in row and "source_spans" not in row, "evaluation input contains target fields")
            if split != "oov":
                for value, seen, label in ((row["source_sha256"], source_splits, "source"),
                                           (row["family_group"], group_splits, "family")):
                    require(value not in seen or seen[value] == split, label + " overlaps splits")
                    seen[value] = split
    for split in ("train", "tuning"):
        require(span.audit_examples(splits[split])["all_supported"], "training/tuning target cannot be copied losslessly")


def native_cross_family_contexts(queries, contexts):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as permutations
    swapped = permutations.permute_contexts_across_families(queries, contexts)
    for row in swapped:
        row["donor_native_stage_receipt"] = row.pop("native_stage_receipt")
        row["context_provenance"] = "donor_source_native_stage; receiving_source_remains_original"
        require(row["donor_native_stage_receipt"]["source_sha256"] == row["donor_source_sha256"],
                "donor native receipt source differs")
    return swapped


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as continuation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as permutations
    require(args.stage_steps in (400, 800) and 1 <= args.workers <= 3, "declared bounded training budget required")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus = read(args.corpus)
    verify_source_inputs(corpus)
    preparation_ref = corpus["frozen_plan"]
    require(sha(preparation_ref["path"]) == preparation_ref["sha256"], "frozen preparation plan differs")
    preparation = read(preparation_ref["path"])
    for ref in (preparation["preparer"], preparation["rendering"]):
        require(sha(ref["path"]) == ref["sha256"], "preparation producer differs")
    splits = corpus["splits"]
    require(sha(args.challenge_targets) == corpus["sealed_targets"]["sha256"], "sealed target bytes differ")
    producer_pins = {str(Path(module.__file__).resolve()): sha(module.__file__)
                     for module in (native, span, continuation, permutations)}
    for function in (read, write, score, generate, fitting_rows, select_stage):
        path = Path(sys.modules[function.__module__].__file__).resolve()
        producer_pins[str(path)] = sha(path)
    producer_pins[str(Path(__file__).resolve())] = sha(__file__)
    parents, previous = {}, read(Path(args.parent_run) / "summary.json")
    for seed in (1729, 1730, 1731):
        selected = [r for r in previous["runs"] if r["name"] == f"source_only-{seed}"]
        require(len(selected) == 1, "one prior source-only checkpoint per seed required")
        ref = selected[0]["checkpoint"]
        cp = continuation.load_checkpoint(ref["path"], expected_sha256=ref["sha256"])
        require(not cp["base_checkpoint"]["config"]["latent_enabled"], "source-only parent required")
        parents[str(seed)] = ref
    plan = {"schema": "legal-native-conditioning-experiment/v1", "corpus": {"path": args.corpus, "sha256": sha(args.corpus)},
        "targets": {"path": args.challenge_targets, "sha256": sha(args.challenge_targets)},
        "preparation": preparation_ref,
        "package": {"path": args.package, "sha256": args.package_sha256}, "parents": parents,
        "parent_run": {"path": str(Path(args.parent_run) / "summary.json"), "sha256": sha(Path(args.parent_run) / "summary.json")},
        "producer_pins": producer_pins, "arms": ARMS, "seeds": [1729, 1730, 1731],
        "counts": {k: len(v) for k, v in splits.items()}, "stage_steps": args.stage_steps, "stages": 2,
        "selection": "maximum tuning exact, earliest stage on tie; no seed selected", "workers": args.workers,
        "input_scope": "raw native GTE384 versus parser/core raw projection versus frozen learned residual projection",
        "training_index_hash_field_scope": "legacy wrapper field binds the training input membership; no retrieval index exists",
        "label_scope": "Authored synthetic source-copy rules; independently reviewed statutory gold unavailable", **FALSE}
    write(output / "plan.json", plan)
    receipts = [{k: r[k] for k in ("path", "sha256", "bytes")} for r in corpus["embedding_receipts"]]
    def resolver(ref):
        import hashlib
        path = Path(corpus["source_paths"][ref["sha256"]])
        require(hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"], "native source artifact differs")
        return path
    contexts = {mode: {} for mode in ("raw384", "core384", "trained384")}
    all_sources = [{k: row[k] for k in ("id", "source_text", "embedding")} for rows in splits.values() for row in rows]
    vectors = native.vectorize(all_sources, package_path=args.package, package_sha256=args.package_sha256,
                               embedding_receipts=receipts, source_resolver=resolver)
    for mode in contexts:
        native.stage_rows(vectors, stage=mode, sources=[{k: r[k] for k in ("id", "source_text")} for r in all_sources])
    native_refs = {"all": write(output / "native-vectors-all.json", vectors)}
    vectors_by_id = {r["id"]: r for r in vectors["rows"]}
    for split, rows in splits.items():
        for mode in contexts:
            contexts[mode][split] = []
        for row in rows:
            vector = vectors_by_id[row["id"]]
            require(row["id"] == vector["id"] and row["source_sha256"] == vector["source_sha256"], "native source binding differs")
            for mode in contexts:
                data = vector["stages"][mode]
                contexts[mode][split].append({"id": row["id"], "source_sha256": row["source_sha256"],
                    "context": data["vector"], "context_sha256": digest(data["vector"]),
                    "native_stage_receipt": data["receipt"]})
        print(json.dumps({"phase": "native_vectors", "split": split, "rows": len(rows)}), flush=True)
    write(output / "native-vector-manifest.json", native_refs)
    train_hash = digest([{k: r[k] for k in ("id", "source_sha256")} for r in splits["train"]])
    contracts = {mode: {"dimension": 384, "representation_id": "actual_frozen_legal_ir/" + mode + "/v1",
                       "producer_sha256": digest({"native": sha(native.__file__), "package": args.package_sha256, "stage": mode}),
                       "training_index_sha256": train_hash} for mode in contexts}
    for mode, panels in contexts.items():
        write(output / f"contexts-{mode}.json", panels)
    write(output / "prepared-inputs.json", {split: [{k: r[k] for k in
        ("id", "source_text", "source_sha256", "family_group") if k in r} for r in rows] for split, rows in splits.items()})
    jobs = []
    for seed in (1729, 1730, 1731):
        for arm, (enabled, mode) in ARMS.items():
            folder = output / f"{arm}-{seed}"
            folder.mkdir()
            jobs.append({"directory": str(folder), "seed": seed, "parent": parents[str(seed)], "arm": arm,
                "enabled": enabled, "mode": mode, "contract": contracts[mode], "train": splits["train"],
                "tuning": splits["tuning"], "train_context": contexts[mode]["train"],
                "tuning_context": contexts[mode]["tuning"], "stage_steps": args.stage_steps})
    heads = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(fit_branch, job) for job in jobs]):
            item = future.result()
            heads.append(item)
            print(json.dumps({"phase": "selected", "name": item["name"], "steps": item["selected_new_steps"],
                              "tuning_exact": item["selection_tuning_exact"]}), flush=True)
    heads.sort(key=lambda r: (r["seed"], list(ARMS).index(r["arm"])))
    for seed in (1729, 1730, 1731):
        require(len({r["initial_model_sha256"] for r in heads if r["seed"] == seed}) == 1, "same-seed starting weights differ")
    head_ref = write(output / "frozen-heads.json", heads)
    items = heads + [{"name": f"parent_source-{seed}", "arm": "parent_source", "seed": seed,
        "checkpoint": parents[str(seed)], "context_mode": "raw384", "latent_enabled": False} for seed in (1729, 1730, 1731)]
    generated = {}
    for item in items:
        folder = output / item["name"]
        folder.mkdir(exist_ok=True)
        decoder = continuation.SpanContinuationDecoder(continuation.load_checkpoint(item["checkpoint"]["path"],
                                                      expected_sha256=item["checkpoint"]["sha256"]))
        mode = item["context_mode"]
        panels = {split: generate(decoder, splits[split], contexts[mode][split]) for split in ("tuning", "challenge", "oov")}
        if item["latent_enabled"]:
            panels["challenge_disabled_context"] = generate(decoder, splits["challenge"], contexts[mode]["challenge"], "disabled_context")
            queries = [{k: r[k] for k in ("id", "source_text", "embedding", "family_group")} for r in splits["challenge"]]
            swapped = native_cross_family_contexts(queries, contexts[mode]["challenge"])
            panels["challenge_cross_family_context"] = generate(decoder, splits["challenge"], swapped)
            panels["challenge_cross_family_context"]["control"] = "cross_family_context"
            write(folder / "cross-family-contexts.json", swapped)
        generated[item["name"]] = panels
        for panel, result in panels.items():
            write(folder / (panel + "-generation.json"), result)
        print(json.dumps({"phase": "generated", "name": item["name"]}), flush=True)
    generation_ref = write(output / "generation-frozen.json", {name: {p: digest(v) for p, v in panels.items()} for name, panels in generated.items()})
    require(sha(args.challenge_targets) == plan["targets"]["sha256"], "sealed reference changed")
    reference_payload = read(args.challenge_targets)
    by_id = {r["id"]: r for r in reference_payload["targets"]}
    require(len(by_id) == len(reference_payload["targets"]) == len(splits["challenge"]), "reference coverage differs")
    references = []
    for row in splits["challenge"]:
        target = by_id[row["id"]]
        require(row["source_sha256"] == target["source_sha256"] and
                digest(target["canonical_ir"]) == target["canonical_target_sha256"] == row["canonical_target_sha256"], "reference binding differs")
        references.append({"id": row["id"], "source_text": row["source_text"], "canonical_ir": target["canonical_ir"]})
    runs = []
    for item in items:
        scores = {}
        for panel, gen in generated[item["name"]].items():
            if panel == "oov":
                counts = Counter(r["status"] for r in gen["rows"])
                metric = {"count": len(gen["rows"]), "decoded": counts["decoded"], "abstained": counts["abstained"], "semantic_accuracy": None}
                name = "dataset-transfer"
            else:
                challenge = panel.startswith("challenge")
                metric = score(gen["rows"], splits["challenge" if challenge else "tuning"], references if challenge else splits["tuning"])
                name = panel
            write(output / item["name"] / (name + ".json"), {"generation": gen, "metrics": metric})
            scores["dataset_transfer" if panel == "oov" else panel] = {k: v for k, v in metric.items() if k != "rows"}
        runs.append({**item, "scores": scores, **FALSE})
        print(json.dumps({"phase": "scored", "name": item["name"], "challenge_exact": scores["challenge"]["exact"]}), flush=True)
    require(all(sha(path) == wanted for path, wanted in producer_pins.items()), "producer changed during experiment")
    require(sha(args.corpus) == plan["corpus"]["sha256"], "corpus changed")
    report = {"schema": plan["schema"], "plan_sha256": sha(output / "plan.json"), "frozen_heads": head_ref,
        "generation_frozen": generation_ref, "native_vectors": native_refs, "runs": runs,
        "challenge_targets_read_after_all_training_selection_and_generation": True,
        "representation_is_native_source_not_retrieved_profile": True, **FALSE}
    write(output / "summary.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("corpus", "challenge-targets", "parent-run", "output", "package", "package-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--stage-steps", type=int, default=400)
    parser.add_argument("--workers", type=int, default=3)
    run(parser.parse_args())
