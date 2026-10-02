"""Isolated CPU worker for the additive source-conditioned CodebaseIR profile."""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile


def execute(request):
    from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as owner
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
    from ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_384 import embed_texts
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import SourceProgramDecoder384
    from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import numerics
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embedding
    owner._require(request["producer"] == owner._pins(), "worker producer differs")
    _, assets = embedding._snapshot_assets(request["embedding_snapshot"])
    if request["action"] == "infer":
        owner._require(all(set(r) == {"id", "source_text"} for r in request["rows"]), "target-free inference rows required")
        vectors = embed_texts([r["source_text"] for r in request["rows"]], snapshot_path=request["embedding_snapshot"])
        rows = [dict(**row, embedding=vector) for row, vector in zip(request["rows"], vectors)]
        runtime = SourceProgramDecoder384(decoder.Runtime(request["checkpoint"]),
            checkpoint_sha256=owner._sha(owner._raw(request["checkpoint"])))
        result = runtime.infer(rows, weight_ablation=request["weight_ablation"])
        _, final_assets = embedding._snapshot_assets(request["embedding_snapshot"])
        owner._require(assets == final_assets and request["producer"] == owner._pins(), "inference assets/producer changed")
        return dict(producer=owner._pins(), embedding_assets=assets, inference=result, training_executed=False)
    owner._require(request["action"] == "train", "unknown worker action")
    corpus = request["corpus"]
    vectors = embed_texts([r["source_text"] for r in corpus["rows"]], snapshot_path=request["embedding_snapshot"])
    grouped = {key: [] for key in ("train", "validation", "holdout")}
    for row, vector in zip(corpus["rows"], vectors):
        grouped[row["role"]].append(dict(id=row["id"], source_text=row["source_text"],
            embedding=vector, target=row["target"], split=row["role"], group_id=row["group_id"]))
    # Numeric duplicate exclusion also covers the untouched holdout.
    from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as audit
    inventories = []
    for role, rows in grouped.items():
        mapped = [dict(row, split="validation" if role == "holdout" else role) for row in rows]
        _, _, inventory = audit._prepare("security_ir", mapped, "validation" if role == "holdout" else role)
        for prior in inventories:
            audit._exclude(prior, inventory)
        inventories.append(inventory)
    with tempfile.TemporaryDirectory(prefix="source384-numerics-") as directory:
        path = Path(directory) / "base.json"
        parent = request["parent"]
        if parent["kind"] == "shared_parent":
            # Preserve the original artifact and the already reviewed explicit
            # compatibility delta. Only the detached numerical view is used.
            original = Path(directory) / "original.json"
            original.write_text(parent["original_checkpoint_utf8"], encoding="utf-8")
            from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384_v2 import _read_view
            _, _, checkpoint, receipt = _read_view(original, parent["original_checkpoint_sha256"])
            owner._require(owner._raw(receipt) == owner._raw(parent["compatibility"]),
                           "shared parent compatibility changed")
        else:
            checkpoint = parent["checkpoint"]
        path.write_bytes(owner._raw(checkpoint))
        plan = numerics.make_plan(path, grouped["train"], grouped["validation"], shard_size=16,
            source_descriptor={"schema": "ir384-corpus-source/v1", "description": "captured repository source; AST labels",
                "corpus_sha256": owner._sha(owner._raw(corpus)), "head": corpus["head"]})
        updates = [numerics.compute_update(plan, checkpoint,
            numerics.shard_rows(plan, grouped["train"], shard["shard_id"]), shard["shard_id"]) for shard in plan["shards"]]
        merged = numerics.merge_updates(plan, checkpoint, updates, grouped["validation"])
    def evaluate(model, rows, control=None):
        clean = [{k: r[k] for k in ("id", "source_text", "embedding", "target")} for r in rows]
        report = decoder.evaluate(model, clean, weight_ablation=control)
        return {k: report[k] for k in ("count", "exact_targets", "semantic_leaf_correct", "semantic_leaf_count",
                                     "valid_candidates", "within_training_coverage", "outside_training_coverage")}
    evaluation = {"holdout_used_for_selection": False, "scope": "fixed_schema_source_target_reconstruction",
        "parent_holdout": evaluate(checkpoint, grouped["holdout"]),
        "child_holdout": evaluate(merged["checkpoint"], grouped["holdout"]),
        "zero_head_holdout": evaluate(merged["checkpoint"], grouped["holdout"], "zero_head")}
    _, final_assets = embedding._snapshot_assets(request["embedding_snapshot"])
    owner._require(assets == final_assets and request["producer"] == owner._pins(), "worker assets/producer changed")
    return dict(producer=owner._pins(), corpus_sha256=owner._sha(owner._raw(corpus)),
        checkpoint=merged["checkpoint"], fit=merged["report"], evaluation=evaluation, embedding_assets=assets)


def main():
    # -I excludes target repositories and ambient PYTHONPATH. The parent supplies
    # only its installed package roots; no source under test is imported.
    sys.path[:0] = json.loads(sys.argv[1])
    # Imported optional backends may print diagnostics. Keep the protocol's
    # stdout a single closed JSON value, while retaining those diagnostics.
    with redirect_stdout(sys.stderr):
        from ipfs_datasets_py.logic.software_contracts.codebase_source_384 import MAX_BYTES, _raw
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("worker input exceeds bound")
        output = _raw(execute(json.loads(data)))
        if len(output) > MAX_BYTES:
            raise ValueError("worker output exceeds bound")
    sys.stdout.buffer.write(output)


if __name__ == "__main__":
    main()
