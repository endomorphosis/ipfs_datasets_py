#!/usr/bin/env python3
"""Train a source-copying IntentIR model with an explicit authored curriculum."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rich-target-descriptor", type=Path, required=True)
    parser.add_argument("--lexical-initializer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--max-seconds", type=int, default=600)
    parser.add_argument("--copy-dropout", type=float, default=0.20)
    args = parser.parse_args(argv)
    if not 1 <= args.epochs <= 500 or not 1 <= args.max_seconds <= 900:
        raise ValueError("development run limited to 500 epochs and 900 seconds")
    from ipfs_datasets_py.logic.intent_ir.formalize.compositional_curriculum import build_compositional_corpus
    from ipfs_datasets_py.logic.intent_ir.formalize.compositional_training import (
        train_compositional_intent, evaluate_compositional_intent)
    corpus = build_compositional_corpus(json.loads(args.rich_target_descriptor.read_bytes()))
    receipt = train_compositional_intent(corpus, args.output,
        lexical_initializer_path=args.lexical_initializer, epochs=args.epochs,
        max_seconds=args.max_seconds, hidden_size=96, embedding_dim=48,
        copy_dropout=args.copy_dropout)
    evaluations = {}
    for split in ("train", "validation", "test"):
        result = evaluate_compositional_intent(receipt["checkpoint"],
            [sample for sample in corpus["samples"] if sample["split"] == split])
        path = args.output / ("evaluation-" + split + ".json")
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        evaluations[split] = {"path": str(path), "metrics": result.get("metrics"),
                             "source_groups": result["source_groups"]}
    ablations = {}
    for mode in ("disable_copy", "zero_output_head"):
        result = evaluate_compositional_intent(receipt["checkpoint"],
            [sample for sample in corpus["samples"] if sample["split"] == "test"], weight_ablation=mode)
        path = args.output / ("evaluation-test-" + mode + ".json")
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        ablations[mode] = {"path": str(path), "metrics": result.get("metrics"),
                           "source_groups": result["source_groups"]}
    summary = {"schema": "intent-compositional-training-run/v1", "checkpoint": receipt["checkpoint"],
        "evaluations": evaluations, "ablations": ablations, "corpus_counts": corpus["counts"],
        "published": False, "default_checkpoint_changed": False,
        "authored_supplement_is_not_public_semantic_gold": True}
    (args.output / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
