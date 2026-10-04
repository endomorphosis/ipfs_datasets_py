#!/usr/bin/env python3
"""Train a bounded 384D diagnostic and independently build generated candidates.

Explicit authored targets are not reviewed statutes. The historical fixture's
heldout split is a regression panel, not a new blind legal evaluation. Every
seed is frozen before that panel is scored; no seed is selected or promoted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SCHEMA = "legal-decoder-diagnostic-pilot/v1"
LABEL_ORIGIN = "authored_synthetic_not_legal_authority"
FALSE = dict(admitted=False, qualified=False, semantic_correctness_verified=False,
             production_ready=False, independent_legal_evaluation=False,
             checkpoint_promotion_performed=False)


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(Path(path).resolve()), "sha256": file_sha(path)}


def read(path):
    require(Path(path).stat().st_size <= 32 * 1024 * 1024, "input exceeds 32 MiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid)


def validate_corpus(corpus):
    require(type(corpus) is dict and corpus.get("label_origin") == LABEL_ORIGIN,
            "pilot requires explicitly authored synthetic targets")
    splits = corpus.get("splits")
    require(type(splits) is dict and set(splits) == {"train", "tuning", "heldout", "regression"},
            "four explicit fixture partitions required")
    ids, sources, targets = set(), set(), set()
    for split, rows in splits.items():
        require(type(rows) is list and 1 <= len(rows) <= 128, "bounded nonempty partitions required")
        for row in rows:
            require(type(row) is dict and set(row) == {"id", "source_text", "canonical_ir", "embedding"},
                    "closed source/target/embedding row required")
            require(type(row["id"]) is str and row["id"] and row["id"] not in ids,
                    "duplicate or missing row ID")
            require(type(row["source_text"]) is str and 0 < len(row["source_text"]) <= 16384,
                    "bounded source required")
            key = " ".join(row["source_text"].casefold().split())
            require(key and key not in sources, "source overlap between or within partitions")
            signature = digest(row["canonical_ir"])
            require(signature not in targets, "complete target overlap between or within partitions")
            vector = row["embedding"]
            require(type(vector) is list and len(vector) == 384 and all(
                type(x) in (int, float) and math.isfinite(x) for x in vector), "finite native 384D vector required")
            ids.add(row["id"]); sources.add(key); targets.add(signature)
    return splits


def inference_inputs(rows, control="normal"):
    require(control in {"normal", "zero_latent", "rotated_latent"}, "unknown control")
    require(len(rows) > 1 or control != "rotated_latent", "rotation requires at least two rows")
    result = []
    for index, row in enumerate(rows):
        vector = row["latent"] if control == "normal" else (
            [0.] * len(row["latent"]) if control == "zero_latent" else rows[(index + 1) % len(rows)]["latent"])
        result.append({"id": row["id"], "source_text": row["source_text"], "latent": list(vector)})
    return result


def metrics(predictions, rows, partition):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas
    targets = [{key: row[key] for key in ("id", "source_text", "canonical_ir")} for row in rows]
    result = compare_free_running_formulas(predictions, targets, partition=partition)
    # The generic scorer's historical default calls all caller targets weak
    # compiler labels. This runner binds them to explicit authored fixture bytes.
    result["metric_default_target_origin"] = result["target_origin"]
    result["target_origin"] = LABEL_ORIGIN
    result["target_origin_verified"] = False
    result["fixture_binding_checked_by_runner"] = True
    return result


def build_candidates(report, source_rows, seed):
    by_id = {row["id"]: row for row in source_rows}
    eligible, excluded = [], []
    for row in report["rows"]:
        source = by_id[row["id"]]
        if row["status"] != "decoded":
            excluded.append({"id": row["id"], "reason": "decoder_abstained"})
            continue
        rules = row["canonical_ir"]["rules"]
        if any(rule[facet] for rule in rules for facet in ("conditions", "exceptions", "temporal")):
            excluded.append({"id": row["id"], "reason": "qualified_rule_lowering_unsupported"})
            continue
        eligible.append({"candidate_id": f"seed-{seed}-" + row["id"],
                         "source_text": source["source_text"],
                         "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(),
                         "canonical_ir": copy.deepcopy(row["canonical_ir"])})
    return eligible, excluded


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as embedding_codec

    require(1 <= args.steps <= 2000 and 1 <= args.seconds <= 120, "bounded training budget required")
    require(1 <= len(args.seeds) <= 3 and len(set(args.seeds)) == len(args.seeds), "one to three unique seeds required")
    corpus = read(args.corpus)
    splits = validate_corpus(corpus)
    fixture_ref, receipt_ref = corpus["fixture"], corpus["embedding_receipt"]
    require(file_sha(fixture_ref["path"]) == fixture_ref["sha256"], "authored fixture changed")
    require(file_sha(receipt_ref["path"]) == receipt_ref["sha256"], "embedding receipt changed")
    fixture = read(fixture_ref["path"])
    # Validate the producer receipt and compare actual vectors/source identities.
    receipt = embedding_codec.load_embedding_production_receipt(
        receipt_ref["path"], expected_sha256=receipt_ref["sha256"],
        expected_size_bytes=Path(receipt_ref["path"]).stat().st_size,
        resolver=lambda ref: corpus["source_paths"][ref["sha256"]]).to_dict()
    require(receipt["execution"]["kind"] == "native", "native embedding execution required")
    vectors = {item["text"]: list(embedding_codec._decode_vector(result["vector"]))
               for item, result in zip(receipt["inputs"], receipt["results"])}
    for split, rows in splits.items():
        require([{key: row[key] for key in ("id", "source_text", "canonical_ir")} for row in rows] == fixture[split],
                "corpus differs from original authored partition")
        require(all(vectors.get(row["source_text"]) == row["embedding"] for row in rows),
                "corpus vector differs from verified producer receipt")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    core = current_v2.Autoencoder(compute_device="cpu")
    binding = joint._core_binding(core)
    core_before = digest(core.state.to_dict())
    code_pins = {str(Path(module.__file__).resolve()): file_sha(module.__file__)
                 for module in (learning, joint, current_v2, embedding_codec)}
    code_pins[str(Path(__file__).resolve())] = file_sha(__file__)
    plan = dict(schema=SCHEMA, corpus_sha256=file_sha(args.corpus), dimension=384,
        seeds=args.seeds, optimizer_steps_per_seed=args.steps, seconds_per_seed=args.seconds,
        binding=binding, code_pins=code_pins, fixture=fixture_ref, embedding_receipt=receipt_ref,
        label_origin=LABEL_ORIGIN, historical_fixture_previously_exposed=True,
        split_role="authored regression; not a newly blind legal test", seed_selection_performed=False,
        scope="fresh frozen sparse core with parser-derived features; train residual projection and GRU",
        embedding_model=receipt["model"], counts={key: len(value) for key, value in splits.items()}, **FALSE)
    write(output / "plan.json", plan)
    prepared = {}
    for split, rows in splits.items():
        samples = [current_v2.build_sample(title="authored-pilot", section=row["id"], text=row["source_text"],
                    embedding_model=receipt["model"]["model_id"] + "@" + receipt["model"]["revision"],
                    embedding_vector=row["embedding"], top_k_frames=0) for row in rows]
        # Retain fixture IDs, while obtaining the real current_v2 raw input.
        prepared[split] = [{**row, "latent": joint.raw_projection(core, sample)}
                           for row, sample in zip(rows, samples)]
    write(output / "raw-inputs.json", prepared)
    fitting = lambda rows: [{key: row[key] for key in ("id", "source_text", "latent", "embedding", "canonical_ir")}
                            for row in rows]
    train, tune = fitting(prepared["train"]), fitting(prepared["tuning"])
    frozen = []
    for seed in args.seeds:
        directory = output / f"seed-{seed}"
        directory.mkdir()
        checkpoint = learning.build_checkpoint(binding, train, tune, seed=seed,
            learning_rate=.005, batch_size=8, hidden_size=32, token_embedding_dim=16, projection_width=8)
        initial = learning.save_checkpoint(checkpoint, directory / "initial.json")
        trained = learning.train(checkpoint, train, tune, epochs=1000,
                                 max_optimizer_steps=args.steps, max_seconds=args.seconds)
        head = learning.save_checkpoint(trained["checkpoint"], directory / "trained.json")
        write(directory / "training.json", trained["report"])
        frozen.append({"seed": seed, "initial": initial, "trained": head,
                       "optimizer_steps": trained["report"]["optimizer_steps"]})
        print(json.dumps({"phase": "trained", "seed": seed,
                          "optimizer_steps": trained["report"]["optimizer_steps"]}), flush=True)
    write(output / "frozen-heads.json", frozen)
    summaries = []
    for item in frozen:
        seed, directory = item["seed"], output / f"seed-{item['seed']}"
        initial = learning.load_checkpoint(item["initial"]["path"], expected_sha256=item["initial"]["sha256"], expected_binding=binding)
        trained = learning.load_checkpoint(item["trained"]["path"], expected_sha256=item["trained"]["sha256"], expected_binding=binding)
        scores = {}
        actual = None
        for arm, checkpoint, split, control in (
                ("untrained_heldout", initial, "heldout", "normal"),
                ("trained_train", trained, "train", "normal"),
                ("trained_tuning", trained, "tuning", "normal"),
                ("trained_heldout", trained, "heldout", "normal"),
                ("zero_latent_heldout", trained, "heldout", "zero_latent"),
                ("rotated_latent_heldout", trained, "heldout", "rotated_latent"),
                ("trained_regression", trained, "regression", "normal")):
            predictions = learning.infer(checkpoint, inference_inputs(prepared[split], control), expected_binding=binding)
            score = metrics(predictions, prepared[split], split)
            write(directory / (arm + ".json"), {"predictions": predictions, "metrics": score, "control": control})
            scores[arm] = {"exact": score["exact_reconstruction"], "counts": score["counts"], "facets": score["facets"]}
            if arm == "trained_heldout":
                actual = predictions
        candidates, excluded = build_candidates(actual, prepared["heldout"], seed)
        write(directory / "lake-candidates.json", {"rows": candidates, "excluded": excluded,
              "selection": "generated unqualified rules only; no reference-based candidate selection",
              "full_panel_build_coverage": not excluded})
        build = {"status": "not_run", "eligible_count": len(candidates), "excluded": excluded}
        if candidates:
            from ipfs_datasets_py.logic.autoformal.legal_pilot_lake import build_legal_pilot
            receipt = build_legal_pilot(candidates, toolchain=args.toolchain,
                lake_executable=args.lake, timeout_seconds=60, output_directory=directory / "lean")
            build["receipt"] = receipt.to_dict()
            build["status"] = "executed_see_receipt"
        summaries.append({**item, "scores": scores, "lake": build, **FALSE})
        print(json.dumps({"phase": "evaluated", "seed": seed, "heldout": scores["trained_heldout"]["exact"]}), flush=True)
    require(digest(core.state.to_dict()) == core_before, "frozen sparse core changed")
    require(file_sha(args.corpus) == plan["corpus_sha256"] and all(file_sha(path) == value for path, value in code_pins.items()),
            "input or producer changed during pilot")
    result = dict(schema=SCHEMA, plan_sha256=file_sha(output / "plan.json"), runs=summaries,
                  sparse_core_unchanged=True, trained_dimensions=[384],
                  deferred_dimensions={"8": "separate matched representation experiment required",
                                       "768": "separate native interface training required"}, **FALSE)
    write(output / "summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1729, 1730, 1731])
    parser.add_argument("--lake", required=True, help="absolute installed native lake executable")
    parser.add_argument("--toolchain", required=True)
    args = parser.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
