#!/usr/bin/env python3
"""Export pinned SkillCenter sources or train an isolated Intent feature model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _json(path: Path):
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("descriptor exceeds 2 MiB")
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("descriptor exceeds 2 MiB")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _preflight(samples, prepare_full, prepare_features):
    """Keep original splits and record rejected inputs without echoing bodies."""
    targets = {split: [] for split in ("train", "validation", "test")}
    selected = {split: [] for split in targets}
    observations = []
    for row in samples:
        observation = {"source_id": row["id"], "split": row["split"]}
        try:
            full = prepare_full(row["instruction"]).to_dict()
            scoped = prepare_features(row["instruction"])
            payload = scoped.to_dict()
            observation.update(
                original_native_ready_for_training=full["ready_for_training"],
                original_native_unsupported_count=len(full["unsupported"]),
                original_native_qualification_gaps=full["qualification_gaps"],
                scoped_qualification_gaps=payload["qualification_gaps"],
                selected_projection_ids=[p["projection_id"] for p in payload["projections"]])
            if not scoped.ready_for_training:
                observation["status"] = "excluded_incomplete_structural_targets"
            elif row["split"] == "test":
                observation["status"] = "held_out_not_used"
                selected["test"].append(row)
            else:
                targets[row["split"]].append(scoped)
                selected[row["split"]].append(row)
                observation["status"] = "structural_features_ready"
        except (ValueError, TypeError, KeyError) as exc:
            observation.update(status="excluded_prompt_adapter_or_feature_validation", error_type=type(exc).__name__)
        observations.append(observation)
    return targets, selected, observations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="verify local pinned Parquet release inputs")
    export.add_argument("--release-root", type=Path, required=True)
    export.add_argument("--release-revision", required=True)
    export.add_argument("--manifest-sha256", required=True)
    export.add_argument("--shard", action="append", required=True)
    export.add_argument("--max-examples", type=int, default=32)
    export.add_argument("--output", type=Path, required=True)
    train = commands.add_parser("train", help="train structural features; does not train an NL logic decoder")
    train.add_argument("--corpus-descriptor", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--epochs", type=int, default=3)
    train.add_argument("--latent-width", type=int, default=4)
    train.add_argument("--max-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training import (
        export_skillcenter_training_corpus, load_skillcenter_training_corpus)
    if args.command == "export":
        descriptor = export_skillcenter_training_corpus(
            release_root=args.release_root, release_revision=args.release_revision,
            expected_manifest_sha256=args.manifest_sha256, shards=args.shard,
            output=args.output, max_examples=args.max_examples)
        print(json.dumps(descriptor, sort_keys=True))
        return 0
    if not 1 <= args.epochs <= 8 or not 1 <= args.max_seconds <= 60:
        raise ValueError("development training is limited to 8 epochs and 60 seconds")
    descriptor, descriptor_hash = _json(args.corpus_descriptor)
    corpus = load_skillcenter_training_corpus(descriptor)
    if len(corpus["samples"]) > 32:
        raise ValueError("development training is limited to 32 source examples")
    from ipfs_datasets_py.logic.intent_ir.formalize import preplanning
    from ipfs_datasets_py.logic.intent_ir.source_adapters import prompt
    from ipfs_datasets_py.logic.formalization.autoencoder import domain_targets
    targets, selected, observations = _preflight(corpus["samples"],
        preplanning.prepare_instruction_targets, preplanning.prepare_instruction_feature_targets)
    if not selected["train"] or not selected["validation"]:
        print(json.dumps({"status": "insufficient_source_separated_training_and_validation_examples",
                          "preflight": observations, "trained": False}, sort_keys=True))
        return 2
    checkpoint = preplanning.train_intent_feature_checkpoint(
        targets["train"], targets["validation"], args.output, epochs=args.epochs,
        latent_width=args.latent_width, max_seconds=args.max_seconds)
    if _json(args.corpus_descriptor)[1] != descriptor_hash:
        raise ValueError("source descriptor changed during training")
    receipt = {"schema": "skillcenter-intent-feature-training/v1", "checkpoint": checkpoint,
               "corpus": descriptor, "corpus_descriptor_sha256": descriptor_hash,
               "release_revision": corpus["release_revision"],
               "selected_source_ids": {k: [r["id"] for r in v] for k, v in selected.items()},
               "selected_split_counts": {k: len(v) for k, v in selected.items()},
               "original_selected_split_counts": corpus["selected_split_counts"],
               "feature_preflight": observations,
               "test_used_for_training_or_tuning": False,
               "supervision": "native_prompt_structural_projection_features_only",
               "initialization": "seeded_scratch_in_distinct_intent_feature_space_no_legal_or_security_heads",
               "gold_instruction_to_logic_pairs": 0, "natural_language_logic_decoder_trained": False,
               "holdout_status": "development_validation_used_for_tuning_not_independent_semantic_evaluation",
               "source_producer_sha256": corpus["producer_sha256"],
               "inference_feature_producer_sha256": {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                    for m in (preplanning, prompt, domain_targets)}, "published": False}
    receipt_path = args.output / "skillcenter-training.json"
    if receipt_path.exists():
        raise ValueError("training receipt already exists")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
