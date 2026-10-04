#!/usr/bin/env python3
"""Train an isolated IntentIR source-copying checkpoint using shared modules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rich-target-descriptor", type=Path, required=True)
    parser.add_argument("--include-authored", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lexical-initializer", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--hidden-size", type=int, default=96)
    parser.add_argument("--embedding-dim", type=int, default=48)
    parser.add_argument("--copy-dropout", type=float, default=0.20,
                        help="Train-only lexical type masking; never fit from held-out text")
    args = parser.parse_args(argv)
    if not 1 <= args.epochs <= 500 or not 1 <= args.max_seconds <= 900:
        raise ValueError("development run limited to 500 epochs and 900 training seconds")
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_span_training import build_rich_span_pairs
    from ipfs_datasets_py.logic.intent_ir.formalize.copy_training import train_intent_copy, evaluate_intent_copy
    corpus = build_rich_span_pairs(json.loads(args.rich_target_descriptor.read_bytes()),
                                  include_authored=args.include_authored)
    receipt = train_intent_copy(corpus, args.output, lexical_initializer_path=args.lexical_initializer,
        epochs=args.epochs, max_seconds=args.max_seconds, hidden_size=args.hidden_size,
        embedding_dim=args.embedding_dim, copy_dropout=args.copy_dropout)
    evaluations = {}
    for split in ("train", "validation", "test"):
        result = evaluate_intent_copy(receipt["checkpoint"], [r for r in corpus["samples"] if r["split"] == split])
        path = args.output / ("evaluation-" + split + ".json")
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        evaluations[split] = {"path": str(path), "metrics": result.get("metrics"), "groups": result["groups"]}
    ablations = {}
    for mode in ("zero_output_head", "disable_copy"):
        result = evaluate_intent_copy(receipt["checkpoint"], [r for r in corpus["samples"] if r["split"] == "test"],
                                      weight_ablation=mode)
        path = args.output / ("evaluation-test-" + mode + ".json")
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        ablations[mode] = {"path": str(path), "metrics": result.get("metrics"), "groups": result["groups"]}
    summary = {"checkpoint": receipt["checkpoint"], "evaluations": evaluations, "ablations": ablations,
               "published": False, "default_checkpoint_changed": False}
    (args.output / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
