#!/usr/bin/env python3
"""Train and evaluate a bounded instruction -> IntentIR -> instruction model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--corpus-descriptor", type=Path,
                        help="Pinned SkillCenter source corpus descriptor (legacy line pairs)")
    source.add_argument("--span-corpus-descriptor", type=Path,
                        help="Pinned SkillCenter span corpus descriptor")
    source.add_argument("--rich-target-descriptor", type=Path,
                        help="Pinned richer span targets; only codec-compatible single actions enter training")
    parser.add_argument("--include-authored", action="store_true",
                        help="Add explicit authored development controls to a span or richer target corpus")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lexical-initializer", type=Path, required=True,
                        help="Read-only compatible LegalIR lexical fork; original law heads are never modified")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--hidden-size", type=int, default=96)
    parser.add_argument("--embedding-dim", type=int, default=48)
    args = parser.parse_args(argv)
    if not 1 <= args.epochs <= 500 or not 1 <= args.max_seconds <= 900:
        raise ValueError("development run limited to 500 epochs and 900 training seconds")
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_corpus import build_intent_roundtrip_corpus
    from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip_training import train_intent_roundtrip, evaluate_intent_roundtrip
    if args.rich_target_descriptor:
        from ipfs_datasets_py.logic.intent_ir.formalize.rich_span_training import build_rich_span_pairs
        descriptor = json.loads(args.rich_target_descriptor.read_bytes())
        corpus = build_rich_span_pairs(descriptor, include_authored=args.include_authored)
    elif args.span_corpus_descriptor:
        from ipfs_datasets_py.logic.intent_ir.formalize.span_training import build_skillcenter_span_pairs
        descriptor = json.loads(args.span_corpus_descriptor.read_bytes())
        corpus = build_skillcenter_span_pairs(descriptor, include_authored=args.include_authored)
    else:
        if args.include_authored:
            parser.error("--include-authored applies only to span or rich targets; legacy controls are already included")
        descriptor = json.loads(args.corpus_descriptor.read_bytes())
        corpus = build_intent_roundtrip_corpus(descriptor)
    receipt = train_intent_roundtrip(corpus, args.output, lexical_initializer_path=args.lexical_initializer,
        epochs=args.epochs, max_seconds=args.max_seconds, hidden_size=args.hidden_size, embedding_dim=args.embedding_dim)
    evaluations = {}
    for split in ("train", "validation", "test"):
        samples = [r for r in corpus["samples"] if r["split"] == split]
        report = evaluate_intent_roundtrip(receipt["checkpoint"], samples)
        path = args.output / ("evaluation-" + split + ".json")
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        evaluations[split] = {"path": str(path), "metrics": report.get("metrics"), "groups": report["groups"]}
    ablated = evaluate_intent_roundtrip(receipt["checkpoint"], [r for r in corpus["samples"] if r["split"] == "test"],
                                      weight_ablation="zero_output_head")
    (args.output / "evaluation-test-zero-head.json").write_text(json.dumps(ablated, indent=2, sort_keys=True) + "\n")
    summary = {"checkpoint": receipt["checkpoint"], "evaluations": evaluations,
               "zero_head_test": ablated.get("metrics"), "published": False}
    (args.output / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
