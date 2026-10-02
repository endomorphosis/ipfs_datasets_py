#!/usr/bin/env python3
"""Train explicit effect-bearing native Intent targets with the shared 384D head.

This is a bounded authored composition experiment, not corpus extraction or a
claim of unseen-language understanding. Legal projection tensors are inherited
unchanged. Test compositions cannot fit or select the head; every output and
ablation is retained. All artifact writes require a fresh output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def save(directory, name, value):
    data = raw(value)
    with (directory / name).open("xb") as handle:
        handle.write(data)
    return {"path": str(directory / name), "sha256": hashlib.sha256(data).hexdigest()}


def specifications():
    """Disjoint combinations, with deliberately shared lexical values."""
    combinations = list(itertools.product(("agent", "worker", "service", "operator", "runner", "calculator"),
        (("left", "right"), ("right", "left")), (-1, 0, 1, 2), ("+", "-", "*")))
    random.Random(42017).shuffle(combinations)
    return {"train": combinations[:96], "validation": combinations[96:120],
            "test": combinations[120:]}


def source(spec):
    actor, (left, right), threshold, operator = spec
    return (f"the {actor} must compute result; requires left > {threshold}; "
        f"ensures result = old({left}) {operator} old({right}) and returned.")


def materialize(specs, split, snapshot_path):
    from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts as codec
    from ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_384 import embed_texts
    texts = [source(spec) for spec in specs]
    vectors = embed_texts(texts, snapshot_path=snapshot_path)
    return [{"id": f"action-contract:{split}:{index}",
        "group_id": hashlib.sha256(text.encode()).hexdigest(), "split": split,
        "source_text": text, "embedding": vector, "target": codec.source_to_target(text)}
        for index, (text, vector) in enumerate(zip(texts, vectors))]


def run(output, parent, parent_sha256, snapshot_path=None):
    from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts as codec
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as reader
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as fitting
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    originals = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in (Path(__file__), Path(codec.__file__), Path(parent))}
    if originals[str(Path(parent))] != parent_sha256:
        raise ValueError("parent checkpoint bytes differ")
    snapshot, assets = producer._snapshot_assets(snapshot_path or producer.DEFAULT_SNAPSHOT_PATH)
    provenance = {"model_id": "thenlper/gte-small", "revision": producer.PINNED_REVISION,
        "dimension": 384, "asset_manifest": assets, "actual_embeddings": True}
    plan = {"schema": "intent-action-training-experiment/v1", "seed": 42017,
        "split_counts": {"train": 96, "validation": 24, "test": 24},
        "split_scope": "disjoint_authored_combinations_shared_lexical_values_and_grammar",
        "label_origin": "explicit_controlled_source_contract_grammar",
        "parent_path": str(parent), "parent_sha256": parent_sha256,
        "source_pins": originals, "embedding_provenance": provenance,
        "ridges": [0.0001, 0.001, 0.01, 0.1], "test_used_for_selection": False,
        "new_corpus_holdout": False, "unseen_vocabulary_evaluation": False}
    save(output, "plan.json", plan)
    specs = specifications()
    training = materialize(specs["train"], "train", snapshot)
    tuning = materialize(specs["validation"], "validation", snapshot)
    save(output, "training-rows.json", training)
    save(output, "validation-rows.json", tuning)
    tick = time.monotonic()
    trained = fitting.train_grouped_source_decoder_384("intent_ir", training, tuning,
        parent_projection={"path": str(parent), "sha256": parent_sha256},
        config={"ridges": plan["ridges"], "embedding_provenance": provenance})
    fit_seconds = time.monotonic() - tick
    checkpoint = trained.pop("checkpoint")
    descriptor = save(output, "checkpoint.json", checkpoint)
    save(output, "training-report.json", trained)
    save(output, "fit-seal.json", {"checkpoint": descriptor,
        "test_materialized": False, "test_used_for_selection": False,
        "parent_unchanged": hashlib.sha256(Path(parent).read_bytes()).hexdigest() == parent_sha256})
    # First access to test texts, labels and embeddings follows checkpoint seal.
    testing = materialize(specs["test"], "test", snapshot)
    save(output, "test-rows.json", testing)
    def decoder_rows(rows):
        return [{key: row[key] for key in ("id", "source_text", "embedding", "target")} for row in rows]
    reports = {}
    for name, ablation in (("actual", None), ("zero_head", "zero_head"),
                           ("shuffle_embeddings", "shuffle_embeddings")):
        observed = reader.evaluate(checkpoint, decoder_rows(testing), weight_ablation=ablation)
        save(output, "test-" + name + ".json", observed)
        reports[name] = {key: observed[key] for key in ("count", "exact_targets", "semantic_leaf_accuracy")}
    # Preserve independent post-generation source audits and provenance binding.
    runtime = reader.load_checkpoint(descriptor["path"], expected_sha256=descriptor["sha256"], expected_domain="intent_ir")
    generated = runtime.infer([{key: row[key] for key in ("id", "source_text", "embedding")} for row in testing])
    audits = [codec.bind_candidate_source(row["source_text"], predicted["candidate_ir"])
              for row, predicted in zip(testing, generated["rows"])]
    save(output, "test-bindings.json", audits)
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha for path, sha in originals.items()):
        raise ValueError("training source or parent changed during experiment")
    if producer._snapshot_assets(snapshot)[1] != assets:
        raise ValueError("embedding assets changed during experiment")
    summary = {"schema": plan["schema"], "checkpoint": descriptor, "test": reports,
        "source_agreement_count": sum(row["status"] == "source_agreement" for row in audits),
        "split_counts": plan["split_counts"], "split_scope": plan["split_scope"],
        "fit_seconds": fit_seconds, "total_seconds": time.monotonic()-start,
        "parent_unchanged": True, "frozen_inherited_projection": True,
        "embedding_reconstruction_trained": False, "unseen_vocabulary_evaluation": False,
        "test_used_for_selection": False, "model_promoted": False,
        "lake_executed": False, "source_semantics_verified": False,
        "scope": "native_effect_target_readout_and_bounded_source_agreement_not_task_completion"}
    save(output, "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--parent-sha256", required=True)
    parser.add_argument("--snapshot-path")
    options = parser.parse_args()
    print(json.dumps(run(options.output, options.parent, options.parent_sha256, options.snapshot_path)))
