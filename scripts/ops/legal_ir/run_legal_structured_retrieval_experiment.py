#!/usr/bin/env python3
"""Warm-started source-span decoding with explicit retrieved rule profiles.

All stages receive equal training budgets. Per-arm checkpoint selection uses
free-generation tuning accuracy only, before any final target file is parsed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.compare_legal_decoder_architectures import read, write, sha, require, score
from scripts.ops.legal_ir.run_legal_span_retrieval_experiment import (
    digest, queries, index_rows, fitting_rows, generate, retrieval_metrics)

SCHEMA = "legal-structured-retrieval-experiment/v1"
ARMS = {"source_only": (False, "dense_joint"), "dense_joint": (True, "dense_joint"),
        "profile_joint": (True, "profile_joint"), "profile_random": (True, "profile_random")}
FALSE = {"qualified": False, "admitted": False, "semantic_correctness_verified": False,
         "production_ready": False, "test_used_for_selection": False}


def select_stage(stages):
    """Predeclared selector: best tuning exact count, earliest update on ties."""
    require(bool(stages), "at least one trained stage required")
    require(len({stage["new_optimizer_steps"] for stage in stages}) == len(stages), "duplicate stage")
    return max(stages, key=lambda stage: (stage["tuning_exact"], -stage["new_optimizer_steps"]))


def cyclic_context_rows(rows, structured):
    """Record a deliberate counterfactual without retaining stale descriptors."""
    result = []
    for row in rows:
        vector = structured.cyclic_modality_context(row["context"])
        result.append({"id": row["id"], "source_sha256": row["source_sha256"],
            "context": vector, "context_sha256": digest(vector),
            "profile_distribution": [4 * vector[16 * index] for index in range(24)],
            "intervention": "cyclic_modality_context", "original_context_receipt": row,
            "original_context_sha256": digest(row["context"])})
    return result


def fit_branch(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as continuation
    parent = span.load_checkpoint(job["parent"]["path"], expected_sha256=job["parent"]["sha256"])
    train, tune = fitting_rows(job["train"], job["train_context"]), fitting_rows(job["tuning"], job["tuning_context"])
    checkpoint = continuation.build_checkpoint(parent, train, tune, latent_enabled=job["enabled"],
        seed=job["seed"], context_contract=job["context_contract"], learning_rate=.001, batch_size=12)
    directory = Path(job["directory"])
    initial = continuation.initial_model_digest(checkpoint)
    stages = []
    for ordinal in (1, 2):
        trained = continuation.train_decoder(checkpoint, train, tune,
            max_steps=job["stage_steps"], max_seconds=job["seconds"])
        checkpoint = trained["checkpoint"]
        steps = continuation.optimizer_steps(checkpoint)
        require(steps == ordinal * job["stage_steps"], "equal complete stage budgets required")
        head = continuation.save_checkpoint(checkpoint, directory / f"checkpoint-{steps}.json")
        write(directory / f"training-{steps}.json", trained["report"])
        generated = generate(continuation.SpanContinuationDecoder(checkpoint), job["tuning"], job["tuning_context"])
        metric = score(generated["rows"], job["tuning"], job["tuning"])
        write(directory / f"tuning-{steps}.json", {"generation": generated, "metrics": metric})
        stages.append({"new_optimizer_steps": steps, "checkpoint": head,
                       "tuning_exact": metric["exact"], "tuning_count": metric["count"]})
    selected = select_stage(stages)
    result = {"name": directory.name, "arm": job["arm"], "seed": job["seed"],
        "context_mode": job["mode"], "latent_enabled": job["enabled"], "context_contract": job["context_contract"],
        "source_parent": job["parent"], "initial_model_sha256": initial, "stages": stages,
        "total_new_training_steps": 2 * job["stage_steps"], "selected_new_steps": selected["new_optimizer_steps"],
        "checkpoint": selected["checkpoint"], "selection_tuning_exact": selected["tuning_exact"],
        "selection_policy": "maximum tuning exact, earlier step on tie", **FALSE}
    write(directory / "selection.json", result)
    return result


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as continuation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_joint_retrieval as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    from scripts.ops.legal_ir import prepare_legal_structured_retrieval_experiment as preparation
    from scripts.ops.legal_ir import run_legal_span_retrieval_experiment as previous_runner
    from scripts.ops.legal_ir import compare_legal_decoder_architectures as scoring
    require(1 <= args.stage_steps <= 1600 and 0 < args.seconds <= 300 and 1 <= args.workers <= 3,
            "bounded stage budget and worker count required")
    require(args.seeds == [1729, 1730, 1731], "declared parent-seed comparison required")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus = read(args.corpus)
    write(output / "input-validation.json", preparation.validate_inputs(corpus, args.challenge_targets))
    splits = corpus["splits"]
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in
            (span, continuation, joint, structured, preparation, previous_runner, scoring)}
    pins[str(Path(__file__).resolve())] = sha(__file__)
    previous_summary_path = Path(args.parent_run) / "summary.json"
    previous_summary = read(previous_summary_path)
    parents = {}
    for seed in args.seeds:
        path = Path(args.parent_run) / f"source_only-{seed}" / "checkpoint.json"
        ref = {"path": str(path.resolve()), "sha256": sha(path)}
        old = [item for item in previous_summary["runs"] if item["name"] == f"source_only-{seed}"]
        require(len(old) == 1 and old[0]["checkpoint"]["sha256"] == ref["sha256"],
                "source parent differs from previous completed experiment")
        parent = span.load_checkpoint(path, expected_sha256=ref["sha256"])
        require(parent["config"]["seed"] == seed and parent["config"]["latent_enabled"] is False
                and parent["progress"]["optimizer_steps"] == 800, "expected trained source-only parent required")
        parents[str(seed)] = ref
    plan = {"schema": SCHEMA, "corpus": {"path": args.corpus, "sha256": sha(args.corpus)},
        "challenge_targets": {"path": args.challenge_targets, "sha256": sha(args.challenge_targets)},
        "parents": parents, "parent_run_summary": {"path": str(previous_summary_path), "sha256": sha(previous_summary_path)},
        "arms": ARMS, "seeds": args.seeds,
        "counts": {split: len(rows) for split, rows in splits.items()},
        "stage_steps": args.stage_steps, "stage_count": 2, "total_updates_per_branch": 2 * args.stage_steps,
        "seconds_per_stage": args.seconds, "workers": args.workers,
        "warm_start": "all saved source-parent model tensors; new Adam at0.001; parent has800 historical updates",
        "selection": "per arm and seed: maximum free-generation tuning exact at two fixed stages; earlier on ties",
        "retriever": {"steps": 600, "seed": 2718, "dimension": 64, "native_input_dimension": 384},
        "retrieval_index": "training only; self/source/query-family excluded",
        "explicit_structure": "24 modality/qualifier-presence probabilities expanded into384 deterministic descriptor coordinates; no target value copies",
        "descriptor_is_trained_autoencoder": False,
        "descriptor_geometry": "profile-histogram norm preserves consensus; dense and explicit descriptors have different geometries",
        "interventions": ["disabled_context", "cross_family_context", "cyclic_modality_context"],
        "holdout_scope": "new entities and values; grammar was already exposed in prior experiments",
        "producer_pins": pins, **FALSE}
    write(output / "plan.json", plan)
    train_index = index_rows(splits["train"])
    trained_retriever = joint.train_retriever(train_index, steps=600, seed=2718, learning_rate=.003,
        joint_dimension=64, temperature=.1)
    path = output / "retriever-checkpoint.json"
    retriever_ref = {"path": str(path), "sha256": joint.save_checkpoint(trained_retriever["checkpoint"], path)}
    write(output / "retriever-training.json", trained_retriever["report"])
    retriever = joint.LegalJointRetriever(train_index, trained_retriever["checkpoint"])
    dense, random, contexts = {}, {}, {mode: {} for mode in ("dense_joint", "profile_joint", "profile_random")}
    for split, rows in splits.items():
        query = queries(rows)
        dense[split] = retriever.retrieve(query, mode="joint", top_k=3, exclude_same_family=True)["rows"]
        random[split] = retriever.retrieve(query, mode="random", top_k=3, exclude_same_family=True)["rows"]
        contexts["dense_joint"][split] = dense[split]
        contexts["profile_joint"][split] = structured.build_contexts(train_index, query, dense[split])["rows"]
        contexts["profile_random"][split] = structured.build_contexts(train_index, query, random[split])["rows"]
    for mode, panels in contexts.items():
        write(output / f"contexts-{mode}.json", panels)
    write(output / "retrieval-random.json", random)
    index_sha = retriever.index_sha256
    contracts = {mode: {"dimension": 384, "representation_id": "train_retrieval/" + mode + "/v1",
        "producer_sha256": digest({"retriever": retriever_ref["sha256"], "structured": sha(structured.__file__), "mode": mode}),
        "training_index_sha256": index_sha} for mode in contexts}
    write(output / "prepared-inputs.json", {split: [{key: row[key] for key in
        ("id", "source_text", "source_sha256", "family_group") if key in row} for row in rows]
        for split, rows in splits.items()})
    jobs = []
    for seed in args.seeds:
        for arm, (enabled, mode) in ARMS.items():
            directory = output / f"{arm}-{seed}"
            directory.mkdir()
            jobs.append({"directory": str(directory), "parent": parents[str(seed)], "seed": seed,
                "arm": arm, "enabled": enabled, "mode": mode, "context_contract": contracts[mode],
                "train": splits["train"], "tuning": splits["tuning"],
                "train_context": contexts[mode]["train"], "tuning_context": contexts[mode]["tuning"],
                "stage_steps": args.stage_steps, "seconds": args.seconds})
    frozen = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(fit_branch, job) for job in jobs]):
            item = future.result()
            frozen.append(item)
            print(json.dumps({"phase": "trained_selected", "name": item["name"],
                "selected_steps": item["selected_new_steps"], "tuning_exact": item["selection_tuning_exact"]}), flush=True)
    frozen.sort(key=lambda item: (args.seeds.index(item["seed"]), list(ARMS).index(item["arm"])))
    for seed in args.seeds:
        require(len({item["initial_model_sha256"] for item in frozen if item["seed"] == seed}) == 1,
                "same-seed arms must share initial tensors")
    frozen_ref = write(output / "frozen-heads.json", frozen)
    generated, items = {}, list(frozen)
    for seed in args.seeds:
        items.append({"name": f"parent_source-{seed}", "arm": "parent_source", "seed": seed,
            "checkpoint": parents[str(seed)], "context_mode": "dense_joint", "latent_enabled": False})
    for item in items:
        name, mode = item["name"], item["context_mode"]
        directory = output / name
        directory.mkdir(exist_ok=True)
        if item["arm"] == "parent_source":
            decoder = span.SpanLegalFormulaDecoder(span.load_checkpoint(item["checkpoint"]["path"],
                expected_sha256=item["checkpoint"]["sha256"]))
        else:
            decoder = continuation.SpanContinuationDecoder(continuation.load_checkpoint(item["checkpoint"]["path"],
                expected_sha256=item["checkpoint"]["sha256"]))
        generated[name] = {}
        for split in ("tuning", "challenge", "oov"):
            generated[name][split] = generate(decoder, splits[split], contexts[mode][split])
        if item["latent_enabled"]:
            generated[name]["challenge_disabled_context"] = generate(decoder, splits["challenge"],
                contexts[mode]["challenge"], "disabled_context")
            swapped = structured.permute_contexts_across_families(queries(splits["challenge"]), contexts[mode]["challenge"])
            generated[name]["challenge_cross_family_context"] = generate(decoder, splits["challenge"], swapped)
            generated[name]["challenge_cross_family_context"]["control"] = "cross_family_context"
            write(directory / "cross-family-contexts.json", swapped)
            if mode.startswith("profile"):
                cycled = cyclic_context_rows(contexts[mode]["challenge"], structured)
                generated[name]["challenge_cyclic_modality_context"] = generate(decoder, splits["challenge"], cycled)
                generated[name]["challenge_cyclic_modality_context"]["control"] = "cyclic_modality_context"
                write(directory / "cyclic-modality-contexts.json", cycled)
        for panel, result in generated[name].items():
            write(directory / (panel + "-generation.json"), result)
        print(json.dumps({"phase": "generated", "name": name}), flush=True)
    generation_ref = write(output / "generation-frozen.json", {name: {panel: digest(result)
        for panel, result in panels.items()} for name, panels in generated.items()})
    require(sha(args.challenge_targets) == plan["challenge_targets"]["sha256"], "sealed targets changed")
    target_payload = read(args.challenge_targets)
    by_id = {row["id"]: row for row in target_payload["targets"]}
    require(len(by_id) == len(target_payload["targets"]) == len(splits["challenge"]), "challenge reference coverage differs")
    references = []
    for row in splits["challenge"]:
        target = by_id[row["id"]]
        require(target["source_sha256"] == row["source_sha256"] and
            digest(target["canonical_ir"]) == target["canonical_target_sha256"] == row["canonical_target_sha256"],
            "challenge reference binding differs")
        references.append({"id": row["id"], "source_text": row["source_text"], "canonical_ir": target["canonical_ir"]})
    runs = []
    for item in items:
        scores = {}
        for panel, generation in generated[item["name"]].items():
            if panel == "oov":
                statuses = Counter(row["status"] for row in generation["rows"])
                reasons = Counter(row.get("reason") for row in generation["rows"] if row["status"] == "abstained")
                metric = {"count": len(generation["rows"]), "decoded": statuses["decoded"],
                    "abstained": statuses["abstained"], "abstention_reasons": dict(reasons), "semantic_accuracy": None}
                write(output / item["name"] / "dataset-transfer.json", {"generation": generation, "metrics": metric})
                scores["dataset_transfer"] = metric
                continue
            challenge = panel.startswith("challenge")
            metric = score(generation["rows"], splits["challenge" if challenge else "tuning"],
                references if challenge else splits["tuning"])
            write(output / item["name"] / (panel + ".json"), {"generation": generation, "metrics": metric})
            scores[panel] = {key: value for key, value in metric.items() if key != "rows"}
        runs.append({**item, "scores": scores, **FALSE})
        print(json.dumps({"phase": "scored", "name": item["name"], "challenge_exact": scores["challenge"]["exact"]}), flush=True)
    require(all(sha(path) == expected for path, expected in pins.items()), "implementation changed during experiment")
    require(sha(args.corpus) == plan["corpus"]["sha256"], "corpus changed")
    report = {"schema": SCHEMA, "plan_sha256": sha(output / "plan.json"), "frozen_heads": frozen_ref,
        "generation_frozen": generation_ref, "retriever_checkpoint": retriever_ref, "runs": runs,
        "retrieval_relevance": {"joint": retrieval_metrics(splits["challenge"], references, dense["challenge"], splits["train"]),
            "random": retrieval_metrics(splits["challenge"], references, random["challenge"], splits["train"])},
        "challenge_targets_read_after_all_training_selection_and_generation": True,
        "all_stages_trained_equal_budgets": True, "selected_stages_can_differ": True,
        "label_scope": "authored synthetic source-span rules; not reviewed statutory semantics", **FALSE}
    write(output / "summary.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--challenge-targets", required=True)
    parser.add_argument("--parent-run", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage-steps", type=int, default=800)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1729, 1730, 1731])
    run(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
