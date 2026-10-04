#!/usr/bin/env python3
"""Controlled source-span decoding with training-only cross-modal retrieval.

This is a small LegalIR experiment inspired by ProofBridge, not a reproduction
of its proof-DAG encoders, language model, or verifier-guided repair pipeline.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.compare_legal_decoder_architectures import read, write, sha, require, score

ARMS = {"source_only": (False, "raw"), "raw_retrieval": (True, "raw"),
        "joint_retrieval": (True, "joint"), "random_retrieval": (True, "random")}
SCHEMA = "legal-span-retrieval-experiment/v1"
FALSE = {"qualified": False, "admitted": False, "semantic_correctness_verified": False,
         "production_ready": False, "test_used_for_selection": False}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def queries(rows):
    return [{"id": row["id"], "source_text": row["source_text"], "embedding": row["embedding"],
             "family_group": row.get("family_group", "oov-" + row["id"])} for row in rows]


def index_rows(rows):
    fields = ("id", "source_text", "source_sha256", "family_group", "embedding",
              "canonical_ir", "formal_embedding")
    return [{field: row[field] for field in fields} for row in rows]


def fitting_rows(rows, context):
    require(len(rows) == len(context), "training context coverage differs")
    result = []
    for row, retrieved in zip(rows, context):
        require(row["id"] == retrieved["id"] and row["source_sha256"] == retrieved["source_sha256"],
                "training retrieval identity differs")
        result.append({"id": row["id"], "source_text": row["source_text"],
                       "canonical_ir": row["canonical_ir"], "latent": retrieved["context"]})
    return result


def generate(decoder, rows, context, control="normal"):
    """No canonical references or source-span annotations enter inference."""
    require(len(rows) == len(context), "generation context coverage differs")
    vectors = []
    for row, retrieved in zip(rows, context):
        require(row["id"] == retrieved["id"] and row["source_sha256"] == retrieved["source_sha256"],
                "inference retrieval identity differs")
        vectors.append(retrieved["context"])
    if control == "zero_context":
        vectors = [[0.] * 384 for _ in vectors]
    elif control == "rotated_context":
        require(len(vectors) > 1, "rotation needs multiple inputs")
        vectors = vectors[1:] + vectors[:1]
    else:
        require(control in ("normal", "disabled_context"), "unknown inference intervention")
    reports, predictions = [], []
    for start in range(0, len(rows), 128):
        report = decoder.decode_formal_logic([row["source_text"] for row in rows[start:start + 128]],
            vectors[start:start + 128], latent_ablation="disabled" if control == "disabled_context" else "none")
        require(report["target_access"] is False and report["teacher_forcing"] is False,
                "generation must not access query targets")
        reports.append(report)
        predictions.extend(report["rows"])
    require(len(predictions) == len(rows), "generation coverage differs")
    return {"reports": reports, "rows": predictions, "control": control,
            "generation_inputs_contained_references": False}


def profile(ir):
    rule = ir["rules"][0]
    return [rule["modality"], *[bool(rule[field]) for field in ("conditions", "exceptions", "temporal")]]


def retrieval_metrics(rows, references, retrieved, training):
    """Post-freeze structural relevance, not identity Recall@K or equivalence."""
    gold = {row["id"]: row["canonical_ir"] for row in references}
    known = {row["id"]: row for row in training}
    require(len(rows) == len(references) == len(retrieved) == len(gold)
            and set(gold) == {row["id"] for row in rows}, "retrieval metric coverage differs")
    require(len(known) == len(training), "duplicate retrieval index identity")
    counts = Counter()
    for source, result in zip(rows, retrieved):
        require(source["id"] == result["id"], "retrieval score source differs")
        wanted = profile(gold[source["id"]])
        matches = [profile(known[identifier]["canonical_ir"]) == wanted for identifier in result["retrieved_ids"]]
        counts["top1_profile_match"] += bool(matches and matches[0])
        counts["top3_any_profile_match"] += any(matches)
        counts["top1_modality_match"] += bool(result["retrieved_ids"] and
            known[result["retrieved_ids"][0]]["canonical_ir"]["rules"][0]["modality"] == wanted[0])
    return {"count": len(rows), **counts,
            "metric_scope": "same modality and qualifier-presence pattern; values differ; not semantic equivalence or paper Recall@K"}


def fit_branch(job):
    """An isolated CPU process owns one checkpoint and its fresh optimizer."""
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    directory = Path(job["directory"])
    train, tune = job["train"], job["tune"]
    checkpoint = span.build_checkpoint(train, tune, latent_dimension=384, latent_enabled=job["enabled"],
        learning_rate=.003, batch_size=12, seed=job["seed"], hidden_size=32,
        embedding_dim=16, projection_width=16, residual_scale=.25)
    initial_sha = digest(checkpoint["model_state"])
    trained = span.train_decoder(checkpoint, train, tune, max_steps=job["steps"], max_seconds=job["seconds"])
    head = span.save_checkpoint(trained["checkpoint"], directory / "checkpoint.json")
    write(directory / "training.json", trained["report"])
    steps = trained["checkpoint"]["progress"]["optimizer_steps"]
    require(steps == job["steps"], "all comparison branches must finish equal step budgets")
    return {"name": directory.name, "arm": job["arm"], "seed": job["seed"], "context_mode": job["mode"],
            "latent_enabled": job["enabled"], "optimizer_steps": steps, "checkpoint": head,
            "initial_model_sha256": initial_sha}


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_joint_retrieval as joint
    from scripts.ops.legal_ir import prepare_legal_span_experiment as preparation
    from scripts.ops.legal_ir import compare_legal_decoder_architectures as scoring
    require(1 <= args.steps <= 1600 and 1 <= args.retrieval_steps <= 2000, "bounded step budget required")
    require(0 < args.seconds <= 300, "bounded decoder deadline required")
    require(1 <= args.workers <= 3, "one to three isolated CPU workers required")
    require(1 <= len(args.seeds) <= 3 and len(set(args.seeds)) == len(args.seeds), "one to three distinct seeds required")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus = read(args.corpus)
    validation = preparation.validate_inputs(corpus, args.challenge_targets)
    write(output / "input-validation.json", validation)
    splits = corpus["splits"]
    require(set(splits) >= {"train", "tuning", "challenge", "oov"}, "required partitions missing")
    require(all("canonical_ir" not in row and "formal_embedding" not in row for row in splits["challenge"]),
            "challenge input must exclude canonical targets and formal target embeddings")
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in (span, joint, preparation, scoring)}
    pins[str(Path(__file__).resolve())] = sha(__file__)
    plan = {"schema": SCHEMA, "corpus": {"path": args.corpus, "sha256": sha(args.corpus)},
        "challenge_targets": {"path": args.challenge_targets, "sha256": sha(args.challenge_targets)},
        "counts": {name: len(rows) for name, rows in splits.items()}, "arms": ARMS, "seeds": args.seeds,
        "decoder_steps": args.steps, "decoder_seconds": args.seconds,
        "training_workers": args.workers, "training_process_start_method": "spawn",
        "retriever_steps": args.retrieval_steps, "retriever_seed": 2718,
        "input_dimension": 384, "joint_embedding_dimension": 64, "top_k": 3,
        "retrieval_index": "training split only; entire query family excluded, including for training queries",
        "decoder_initialization": "new byte-informed span architecture from scratch; same initial tensors per seed in all arms",
        "context_adapter": "bounded zero-initialized feature-wise scale and shift; context can change relative pointer scores",
        "selection": "fixed final update count; all declared arms reported, no test-based selection",
        "interventions": ["zero_context", "rotated_context", "disabled_context"],
        "representation": "one canonical deontic rule; exact source-span copies, at most one qualifier per field",
        "paper": "https://arxiv.org/html/2510.15681v3",
        "paper_scope": "inspired contrastive retrieval experiment; no proof DAG encoder, 1.7B generator or iterative repair",
        "retriever_seed_variance_evaluated": False, "torch_version": str(torch.__version__),
        "producer_pins": pins, **FALSE}
    write(output / "plan.json", plan)
    training_index = index_rows(splits["train"])
    trained_retriever = joint.train_retriever(training_index, steps=args.retrieval_steps, seed=2718,
        learning_rate=.003, joint_dimension=64, temperature=.1)
    retriever_path = output / "retriever-checkpoint.json"
    retriever_ref = {"path": str(retriever_path), "sha256": joint.save_checkpoint(
        trained_retriever["checkpoint"], retriever_path)}
    write(output / "retriever-training.json", trained_retriever["report"])
    retriever = joint.LegalJointRetriever(training_index, trained_retriever["checkpoint"])
    contexts = {}
    for mode in ("raw", "joint", "random"):
        contexts[mode] = {}
        for split, rows in splits.items():
            report = retriever.retrieve(queries(rows), mode=mode, top_k=3, exclude_same_family=True)
            require(report["target_access"] is False and report["teacher_forcing"] is False,
                    "retrieval must not receive query target")
            contexts[mode][split] = report["rows"]
        write(output / ("retrieval-" + mode + ".json"), contexts[mode])
    write(output / "prepared-inputs.json", {name: [{key: row[key] for key in (
        "id", "source_text", "source_sha256", "family_group") if key in row} for row in rows]
        for name, rows in splits.items()})
    jobs = []
    for seed in args.seeds:
        for arm, (enabled, mode) in ARMS.items():
            directory = output / f"{arm}-{seed}"
            directory.mkdir()
            train = fitting_rows(splits["train"], contexts[mode]["train"])
            tune = fitting_rows(splits["tuning"], contexts[mode]["tuning"])
            jobs.append({"directory": str(directory), "train": train, "tune": tune, "enabled": enabled,
                "seed": seed, "arm": arm, "mode": mode, "steps": args.steps, "seconds": args.seconds})
    frozen = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(fit_branch, job) for job in jobs]
        for future in as_completed(futures):
            item = future.result()
            frozen.append(item)
            print(json.dumps({"phase": "trained", "name": item["name"], "steps": item["optimizer_steps"]}), flush=True)
    frozen.sort(key=lambda item: (args.seeds.index(item["seed"]), list(ARMS).index(item["arm"])))
    for seed in args.seeds:
        require(len({item["initial_model_sha256"] for item in frozen if item["seed"] == seed}) == 1,
                "matched branches differ at initialization")
    frozen_ref = write(output / "frozen-heads.json", frozen)
    # Generate every ordinary and intervention prediction before target access.
    generated = {}
    for item in frozen:
        decoder = span.SpanLegalFormulaDecoder(span.load_checkpoint(item["checkpoint"]["path"],
            expected_sha256=item["checkpoint"]["sha256"]))
        name, mode = item["name"], item["context_mode"]
        generated[name] = {}
        for split in ("tuning", "challenge", "oov"):
            result = generate(decoder, splits[split], contexts[mode][split])
            generated[name][split] = result
            write(output / name / (split + "-generation.json"), result)
        if item["latent_enabled"]:
            for control in plan["interventions"]:
                result = generate(decoder, splits["challenge"], contexts[mode]["challenge"], control)
                generated[name]["challenge_" + control] = result
                write(output / name / ("challenge-" + control + "-generation.json"), result)
        print(json.dumps({"phase": "generated", "name": name}), flush=True)
    generation_ref = write(output / "generation-frozen.json", {name: {panel: digest(result)
        for panel, result in panels.items()} for name, panels in generated.items()})
    require(sha(args.challenge_targets) == plan["challenge_targets"]["sha256"], "sealed targets changed")
    target_payload = read(args.challenge_targets)
    by_id = {row["id"]: row for row in target_payload["targets"]}
    require(len(by_id) == len(target_payload["targets"]) == len(splits["challenge"]), "challenge target coverage differs")
    challenge_refs = []
    for row in splits["challenge"]:
        ref = by_id[row["id"]]
        require(ref["source_sha256"] == row["source_sha256"], "challenge source binding differs")
        require(digest(ref["canonical_ir"]) == ref["canonical_target_sha256"] == row["canonical_target_sha256"],
                "challenge canonical target differs from commitment")
        challenge_refs.append({"id": row["id"], "source_text": row["source_text"], "canonical_ir": ref["canonical_ir"]})
    runs = []
    for item in frozen:
        name = item["name"]
        scores = {}
        for panel, generation in generated[name].items():
            if panel == "oov":
                rows = generation["rows"]
                statuses = Counter(row["status"] for row in rows)
                reasons = Counter(row.get("reason") for row in rows if row["status"] == "abstained")
                scores["dataset_transfer"] = {"count": len(rows), "decoded": statuses["decoded"],
                    "abstained": statuses["abstained"], "abstention_reasons": dict(reasons),
                    "semantic_accuracy": None, "qualified": False,
                    "scope": "unreviewed observed statutory spans; outputs are candidates only"}
                write(output / name / "dataset-transfer.json", {"generation": generation,
                      "metrics": scores["dataset_transfer"]})
                continue
            is_challenge = panel.startswith("challenge")
            inputs = splits["challenge" if is_challenge else "tuning"]
            references = challenge_refs if is_challenge else splits["tuning"]
            metric = score(generation["rows"], inputs, references)
            scores[panel] = {key: value for key, value in metric.items() if key != "rows"}
            write(output / name / (panel + ".json"), {"generation": generation, "metrics": metric})
        runs.append({**item, "kind": "source_span", "scores": scores, **FALSE})
        print(json.dumps({"phase": "scored", "name": name, "challenge_exact": scores["challenge"]["exact"],
                         "tuning_exact": scores["tuning"]["exact"]}), flush=True)
    retrieval_scores = {mode: retrieval_metrics(splits["challenge"], challenge_refs,
        contexts[mode]["challenge"], splits["train"]) for mode in contexts}
    require(all(sha(path) == expected for path, expected in pins.items()), "implementation changed during experiment")
    require(sha(args.corpus) == plan["corpus"]["sha256"], "corpus changed")
    report = {"schema": SCHEMA, "plan_sha256": sha(output / "plan.json"), "frozen_heads": frozen_ref,
        "generation_frozen": generation_ref, "retriever_checkpoint": retriever_ref, "runs": runs,
        "retrieval_relevance": retrieval_scores, "challenge_targets_read_after_all_training_and_generation": True,
        "label_scope": "authored source-span compositions; not reviewed statutory semantics",
        "dimensions_executed": {"source_and_formal_embeddings": 384, "learned_joint_projection": 64}, **FALSE}
    write(output / "summary.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--challenge-targets", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--retrieval-steps", type=int, default=600)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1729, 1730, 1731])
    run(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
