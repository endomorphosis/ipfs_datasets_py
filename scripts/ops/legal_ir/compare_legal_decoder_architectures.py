#!/usr/bin/env python3
"""Compare saved LegalIR decoders and controlled warm-started fusion branches.

All references are authored diagnostics. The new challenge references are opened
only after every branch checkpoint is frozen. No deployment or legal admission
is inferred from exact reconstruction or successful Lean compilation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SCHEMA = "legal-decoder-architecture-comparison/v1"
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
ARMS = {"source_ce": (False, "token_ce"), "source_facets": (False, "facet_balanced"),
        "hybrid_ce": (True, "token_ce"), "hybrid_facets": (True, "facet_balanced")}
FALSE = {"admitted": False, "qualified": False, "semantic_correctness_verified": False,
         "production_ready": False, "independent_legal_evaluation": False,
         "test_used_for_selection": False, "promotion_performed": False}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, ensure_ascii=False).encode()).hexdigest()


def read(path):
    require(Path(path).stat().st_size <= 64 * 1024**2, "input exceeds 64MiB")
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid)


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(Path(path).resolve()), "sha256": sha(path)}


def target_rows(rows):
    return [{key: row[key] for key in ("id", "source_text", "canonical_ir")} for row in rows]


def training_rows(rows):
    return [{key: row[key] for key in ("id", "source_text", "latent", "canonical_ir")} for row in rows]


def score(predictions, inputs, references):
    """Score post-generation; reject mismatched source/count/provenance bindings."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as codec
    require(len(predictions) == len(inputs) == len(references), "evaluation row coverage differs")
    expected = {row["id"]: row for row in references}
    require(len(expected) == len(references) and set(expected) == {row["id"] for row in inputs},
            "reference identities differ")
    counts, facets, details = Counter(), Counter(), []
    for prediction, row in zip(predictions, inputs):
        require(prediction.get("source_sha256") == hashlib.sha256(row["source_text"].encode()).hexdigest(),
                "prediction source differs")
        require(prediction.get("target_access") is False and prediction.get("teacher_forcing") is False,
                "free generation evidence required")
        reference = expected[row["id"]]["canonical_ir"]
        status = prediction["status"]
        require(status in ("decoded", "abstained"), "unknown prediction status")
        counts[status] += 1
        candidate = prediction.get("canonical_ir")
        if status == "decoded":
            codec._rule(candidate)
        else:
            require(candidate is None, "abstention must not carry a candidate")
        exact = status == "decoded" and candidate == reference
        matches = {facet: bool(status == "decoded" and
            [r[facet] for r in candidate["rules"]] == [r[facet] for r in reference["rules"]]) for facet in FACETS}
        facets.update(key for key, value in matches.items() if value)
        counts["exact"] += int(exact)
        details.append({"id": row["id"], "family_group": row.get("family_group"),
                        "exact": exact, "facets": matches, "status": status,
                        "reason": prediction.get("reason"),
                        "candidate_sha256": None if candidate is None else digest(candidate),
                        "reference_sha256": digest(reference)})
    return {"count": len(inputs), "decoded": counts["decoded"], "abstained": counts["abstained"],
            "exact": counts["exact"], "exact_fraction": counts["exact"] / len(inputs),
            "facets": dict(facets), "rows": details, "label_origin": "authored_synthetic_not_legal_authority",
            "independent_semantic_validation": False, "valid_evaluation": True}


def generate(kind, decoder, rows, control="normal"):
    """Only source text and explicit vectors cross the inference boundary."""
    vectors = [row["latent"] for row in rows]
    raw_vectors = [row["raw_latent"] for row in rows]
    if control == "rotated_latent":
        require(len(rows) > 1, "rotation requires multiple inputs")
        vectors, raw_vectors = vectors[1:] + vectors[:1], raw_vectors[1:] + raw_vectors[:1]
    elif control == "zero_latent":
        vectors = [[0.] * len(vector) for vector in vectors]
        raw_vectors = [[0.] * len(vector) for vector in raw_vectors]
    elif control == "unprojected_latent":
        require(kind == "hybrid", "unprojected intervention requires hybrid")
        vectors = raw_vectors
    elif control == "raw_embedding":
        require(kind == "hybrid", "embedding intervention requires hybrid")
        vectors = [row["embedding"] for row in rows]
    else:
        require(control in ("normal", "disabled_latent"), "unknown inference control")
    reports, predictions = [], []
    for start in range(0, len(rows), 128):
        part = rows[start:start + 128]
        texts = [row["source_text"] for row in part]
        if kind == "source":
            report = decoder.decode_formal_logic(texts)
        elif kind == "latent":
            report = decoder.infer([{"id": row["id"], "source_text": row["source_text"], "latent": vector}
                                    for row, vector in zip(part, raw_vectors[start:start + 128])])
        else:
            report = decoder.decode_formal_logic(texts, vectors[start:start + 128],
                latent_ablation="disabled" if control == "disabled_latent" else "none")
        require(report["target_access"] is False and report["teacher_forcing"] is False,
                "inference used target access")
        reports.append(report)
        predictions.extend(report["rows"])
    return {"reports": reports, "rows": predictions, "control": control,
            "generation_inputs_contained_references": False}


def preparation(args, output, source, package, joint, latent_module):
    corpus = read(args.corpus)
    from scripts.ops.legal_ir.validate_legal_decoder_comparison_inputs import validate_inputs
    write(output / "input-validation.json", validate_inputs(corpus, args.challenge_targets))
    splits = corpus["splits"]
    require(set(splits) >= {"train", "tuning", "heldout", "regression", "development", "challenge"},
            "comparison partitions missing")
    require(all("canonical_ir" not in row for row in splits["challenge"]), "challenge references must be separate")
    source_ids = [row["id"] for key in ("train", "tuning", "heldout", "regression", "development", "challenge")
                  for row in splits[key]]
    require(len(set(source_ids)) == len(source_ids), "duplicate source identities")
    ids = {row["id"] for row in splits["train"] + splits["development"]}
    require(not ids.intersection(row["id"] for row in splits["challenge"]), "fitting overlaps challenge")
    latent_decoder = latent_module.LatentFormulaDecoder(package._payload["formula_checkpoint"],
                                                       expected_binding=package._payload["core_binding"])
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package
    before = joint._core_binding(package.model)
    prepared = {}
    for split in ("train", "tuning", "heldout", "regression", "development", "challenge", "oov"):
        rows = splits[split]
        prepared[split] = []
        for start in range(0, len(rows), 128):
            part = rows[start:start + 128]
            inputs = [{key: row[key] for key in ("id", "source_text", "embedding")} for row in part]
            samples = legal_384_package._rows(inputs, package._payload["embedding_contract"])
            raw_latents = [joint.raw_projection(package.model, sample) for sample in samples]
            vectors = latent_decoder.project(raw_latents)
            prepared[split].extend({**row, "raw_latent": raw, "latent": vector}
                                  for row, raw, vector in zip(part, raw_latents, vectors))
    require(joint._core_binding(package.model) == before, "published core changed during input production")
    # Test only the training/tuning codec here. The new challenge target file is
    # not opened or encoded until the frozen checkpoint manifest exists.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    for split in ("train", "development", "tuning"):
        for row in prepared[split]:
            legal_formula_codec.encode_source(source["codec"], row["source_text"])
            legal_formula_codec.encode_target(source["codec"], row["canonical_ir"])
    write(output / "prepared-inputs.json", prepared)
    return corpus, prepared, latent_decoder


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning as source_module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as latent_module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_hybrid_formula as hybrid
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package as package_module
    from scripts.ops.legal_ir import validate_legal_decoder_comparison_inputs as validation

    require(1 <= args.steps <= 1000 and 0 < args.seconds <= 180, "bounded training budget required")
    require(1 <= len(args.seeds) <= 3 and len(set(args.seeds)) == len(args.seeds), "one to three seeds required")
    source = source_module.load_checkpoint(args.source_checkpoint, expected_sha256=args.source_sha256)
    package = package_module.load_package(args.latent_package, expected_sha256=args.latent_sha256)
    source_decoder = source_module.LearnedLegalFormulaDecoder(source)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus, prepared, latent_decoder = preparation(args, output, source, package, joint, latent_module)
    contract = {"dimension": 384, "representation_id": "published_legal384_learned_projection/v1",
                "encoder_sha256": args.latent_sha256}
    pins = {str(Path(m.__file__).resolve()): sha(m.__file__) for m in
            (source_module, latent_module, joint, hybrid, package_module, validation)}
    pins[str(Path(__file__).resolve())] = sha(__file__)
    options = {"learning_rate": .001, "batch_size": 12, "projection_width": 16}
    plan = {"schema": SCHEMA, "source_checkpoint": {"path": args.source_checkpoint, "sha256": args.source_sha256},
            "latent_package": {"path": args.latent_package, "sha256": args.latent_sha256},
            "source_parent_optimizer_steps": source["progress"]["optimizer_steps"],
            "latent_parent_optimizer_steps": package._payload["formula_checkpoint"]["progress"]["optimizer_steps"],
            "corpus_sha256": sha(args.corpus), "challenge_targets_sha256": sha(args.challenge_targets),
            "challenge_targets_read_for_fit": False, "latent_contract": contract,
            "counts": {key: len(rows) for key, rows in prepared.items()}, "arms": ARMS,
            "seeds": args.seeds, "new_steps_per_arm": args.steps, "options": options,
            "seconds_per_arm": args.seconds,
            "optimizer_state": "new Adam per branch; shared parent model weights retained",
            "hybrid_controls": ["zero_latent", "rotated_latent", "disabled_latent",
                                "unprojected_latent", "raw_embedding"],
            "intervention_scope": "Inference sensitivity only; raw-input controls are distribution shifts, not retrained architecture comparisons",
            "data_replay": "original train plus new development; original tuning for observations only",
            "selection": "none; all predeclared arms reported", "torch_version": str(torch.__version__),
            "producer_pins": pins, **FALSE}
    write(output / "plan.json", plan)
    train = training_rows(prepared["train"] + prepared["development"])
    tune = training_rows(prepared["tuning"])
    frozen = []
    for seed in args.seeds:
        initial_source_sha = None
        for arm, (enabled, loss) in ARMS.items():
            directory = output / f"{arm}-{seed}"
            directory.mkdir()
            checkpoint = hybrid.build_checkpoint(source, contract, train, tune, seed=seed,
                latent_enabled=enabled, loss_mode=loss, **options)
            initial_sha = digest(checkpoint["model_state"])
            require(initial_source_sha is None or initial_source_sha == initial_sha,
                    "matched branches have different initial tensors")
            initial_source_sha = initial_sha
            trained = hybrid.train_decoder(checkpoint, train, tune, max_steps=args.steps, max_seconds=args.seconds)
            head = hybrid.save_checkpoint(trained["checkpoint"], directory / "checkpoint.json")
            write(directory / "training.json", trained["report"])
            progress = trained["checkpoint"]["progress"]
            require(progress["optimizer_steps"] == args.steps,
                    "matched comparison requires every arm to complete the same step budget")
            frozen.append({"arm": arm, "seed": seed, "checkpoint": head,
                           "optimizer_steps": progress["optimizer_steps"], "initial_model_sha256": initial_sha})
            print(json.dumps({"phase": "trained", "arm": arm, "seed": seed,
                              "steps": progress["optimizer_steps"]}), flush=True)
    frozen_ref = write(output / "frozen-heads.json", frozen)
    require(sha(args.challenge_targets) == plan["challenge_targets_sha256"], "sealed targets changed")
    targets = read(args.challenge_targets)["targets"]
    by_id = {row["id"]: row for row in targets}
    require(len(by_id) == len(targets) == len(prepared["challenge"]), "challenge target coverage differs")
    challenge_refs = []
    for row in prepared["challenge"]:
        ref = by_id[row["id"]]
        require(ref["source_sha256"] == row["source_sha256"], "challenge source binding differs")
        require(ref["canonical_target_sha256"] == row["canonical_target_sha256"], "challenge target binding differs")
        require(validation.canonical_digest(ref["canonical_ir"]) == ref["canonical_target_sha256"],
                "challenge canonical payload differs from commitment")
        challenge_refs.append({"id": row["id"], "source_text": row["source_text"], "canonical_ir": ref["canonical_ir"]})
    panels = {"heldout": target_rows(prepared["heldout"]), "regression": target_rows(prepared["regression"]),
              "challenge": challenge_refs, "tuning": target_rows(prepared["tuning"])}
    summaries = []

    def evaluate(name, kind, decoder, *, item=None):
        directory = output / name
        directory.mkdir(exist_ok=True)
        scores = {}
        for panel, refs in panels.items():
            generated = generate(kind, decoder, prepared[panel])
            metric = score(generated["rows"], prepared[panel], refs)
            write(directory / (panel + ".json"), {"generation": generated, "metrics": metric})
            scores[panel] = {key: value for key, value in metric.items() if key != "rows"}
        if kind == "latent" or (kind == "hybrid" and item and item["arm"].startswith("hybrid")):
            controls = ("zero_latent", "rotated_latent") if kind == "latent" else (
                "zero_latent", "rotated_latent", "disabled_latent", "unprojected_latent", "raw_embedding")
            for control in controls:
                generated = generate(kind, decoder, prepared["challenge"], control)
                metric = score(generated["rows"], prepared["challenge"], challenge_refs)
                write(directory / ("challenge-" + control + ".json"), {"generation": generated, "metrics": metric})
                scores["challenge_" + control] = {key: value for key, value in metric.items() if key != "rows"}
        oov = generate(kind, decoder, prepared["oov"])
        statuses = Counter(row["status"] for row in oov["rows"])
        reasons = Counter(row.get("reason") for row in oov["rows"] if row["status"] == "abstained")
        require(len(oov["rows"]) == len(prepared["oov"]), "OOV row coverage differs")
        scores["dataset_transfer"] = {"count": len(oov["rows"]), "decoded": statuses["decoded"],
            "abstained": statuses["abstained"], "abstention_reasons": dict(reasons),
            "semantic_accuracy": None, "reason": "no independently reviewed statutory references"}
        write(directory / "dataset-transfer.json", {"generation": oov, "metrics": scores["dataset_transfer"]})
        result = {"name": name, "kind": kind, "scores": scores, **({} if item is None else item), **FALSE}
        summaries.append(result)
        print(json.dumps({"phase": "evaluated", "name": name, "challenge_exact": scores["challenge"]["exact"],
                          "heldout_exact": scores["heldout"]["exact"]}), flush=True)

    evaluate("existing_source", "source", source_decoder)
    evaluate("existing_latent", "latent", latent_decoder)
    for item in frozen:
        checkpoint = hybrid.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"])
        evaluate(f"{item['arm']}-{item['seed']}", "hybrid", hybrid.HybridLegalFormulaDecoder(checkpoint), item=item)
    require(all(sha(path) == value for path, value in pins.items()), "comparison implementation changed")
    require(sha(args.corpus) == plan["corpus_sha256"], "corpus changed")
    require(source_module.checkpoint_digest(source_decoder.checkpoint) == args.source_sha256, "source baseline changed")
    require(joint._core_binding(package.model) == package._payload["core_binding"], "published core changed")
    result = {"schema": SCHEMA, "plan_sha256": sha(output / "plan.json"), "frozen_heads": frozen_ref,
              "runs": summaries, "existing_parent_checkpoints_preserved": True,
              "label_scope": "authored synthetic compositions, not statutory semantic qualification",
              "dimensions_executed": [384], "new_challenge_target_access_after_all_training": True, **FALSE}
    write(output / "summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--challenge-targets", required=True)
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--latent-package", required=True)
    parser.add_argument("--latent-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1729, 1730, 1731])
    run(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
