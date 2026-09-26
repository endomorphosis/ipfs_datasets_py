#!/usr/bin/env python3
"""Audit a bounded pinned US Code source/vector selection without training.

All inputs are local, descriptor-checked files. This records diagnostic joins
and frozen index membership; it never downloads models, starts training,
publishes data, changes corpus admission status or admits Lean.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
REVISION = "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
MANIFEST_SHA = "0c6c05582fda19f36c75b166c5c1afecdab156241ce73728f564802b52eacac6"
CORPUS_PATH = "data/corpus/part-000015.parquet"
VECTOR_PATH = "data/vectors/centroid-000-part-000015.parquet"


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _run(args, receipt):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import CheckpointArtifact
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_import import (
        load_uscode_release, read_corpus_shard, extract_uscode_rows,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_embeddings import (
        audit_uscode_embedding_join, USCodeEmbeddingJoinError,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        build_corpus_manifest, load_corpus_manifest,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import (
        build_corpus_index, load_corpus_index, IndexScope, SplitPolicy, CorpusIndexError,
    )

    root = args.input_root.resolve()
    manifest_path = root / "manifest.json"
    if _sha(manifest_path) != MANIFEST_SHA:
        raise ValueError("input manifest differs from the pinned audited bytes")
    references = {}
    for relative in ("manifest.json", CORPUS_PATH, VECTOR_PATH):
        path = (root / relative).resolve()
        references[_sha(path)] = path

    def resolver(ref):
        path = references[ref["sha256"]]
        if path.stat().st_size != ref["bytes"]:
            raise ValueError("resolver byte length mismatch")
        return path

    started = time.perf_counter()
    release = load_uscode_release(CheckpointArtifact(str(manifest_path), MANIFEST_SHA, manifest_path.stat().st_size),
                                 repo_id="justicedao/ipfs_uscode", revision=REVISION)
    receipt["release_load_seconds"] = time.perf_counter() - started
    receipt["publisher_manifest_digest"] = release.manifest_digest
    receipt["publisher_release_point"] = release.release_point
    receipt["publisher_source_revision"] = release.source_revision
    receipt["declared_corpus_shards"] = len(release.corpus_shards)
    receipt["declared_corpus_rows"] = sum(shard.row_count for shard in release.corpus_shards)
    started = time.perf_counter()
    corpus = read_corpus_shard(release, CORPUS_PATH, resolver=resolver, max_rows=2048, batch_size=64)
    receipt["corpus_read_seconds"] = time.perf_counter() - started
    if not corpus.complete or len(corpus.records) < args.sample_limit:
        raise ValueError("selected corpus shard is incomplete or has too few usable records")
    receipt["corpus"] = {"rows_scanned": corpus.rows_scanned, "usable_rows": len(corpus.records),
                         "status_counts": corpus.status_counts,
                         "dispositions": [asdict(item) for item in corpus.dispositions],
                         "selected_shard_complete": corpus.complete}
    started = time.perf_counter()
    joined = audit_uscode_embedding_join(release, corpus.records, vector_shards=[VECTOR_PATH], resolver=resolver)
    receipt["embedding_audit_seconds"] = time.perf_counter() - started
    receipt["embedding_audit_artifact"] = joined.save(args.artifacts_directory / "embedding-audit.json")
    receipt["embedding_status_counts"] = joined.status_counts
    receipt["training_eligible_count"] = joined.training_eligible_count
    try:
        joined.require_training_embeddings()
    except USCodeEmbeddingJoinError:
        receipt["unqualified_training_embeddings_rejected"] = True
    else:
        raise ValueError("this published profile unexpectedly qualified for corpus training")

    selected_rows = corpus.records[:args.sample_limit]
    started = time.perf_counter()
    extracted = extract_uscode_rows(selected_rows, args.artifacts_directory / "source-text",
                                   release=release, resolver=resolver)
    receipt["import_artifact"] = extracted.receipt_artifact
    vectors = joined.diagnostic_vectors()
    records = extracted.source_records(
        embedding_vectors={row.entry_cid: vectors[row.entry_cid] for row in selected_rows},
        embedding_model=release.model_id, mode="diagnostic")
    receipt["text_extraction_seconds"] = time.perf_counter() - started
    selection = {"schema": "pinned-uscode-diagnostic-selection-v1", "repo_id": "justicedao/ipfs_uscode",
                 "revision": REVISION, "manifest_sha256": MANIFEST_SHA,
                 "corpus_relative_path": CORPUS_PATH, "vector_relative_path": VECTOR_PATH,
                 "record_ids": [record.record_id for record in records],
                 "selection_rule": "first usable corpus rows in physical shard order, before model evaluation",
                 "sample_limit": args.sample_limit, "training_eligible": False}
    selection_path = args.artifacts_directory / "selection.json"
    _write(selection_path, selection)
    started = time.perf_counter()
    index = build_corpus_index(records, scope=IndexScope(_sha(selection_path), (MANIFEST_SHA,)),
                              policy=SplitPolicy(seed="uscode-selected-shard-v1"))
    index_artifact = index.save(args.artifacts_directory / "corpus-index.json")
    receipt["index_build_seconds"] = time.perf_counter() - started
    receipt["index"] = index.verification_summary()
    receipt["index_artifact"] = index_artifact
    train_ids, validation_ids = index.record_ids_for("train"), index.record_ids_for("validation")
    by_id = {record.record_id: record for record in records}
    selected_ids = (*train_ids, *validation_ids)
    manifest = build_corpus_manifest([by_id[key] for key in selected_ids], training_record_ids=train_ids,
                                     validation_record_ids=validation_ids, mode="diagnostic")
    source_paths = {source.artifact.sha256: Path(source.path).resolve() for source in extracted.sources}

    def source_resolver(ref):
        path = source_paths[ref["sha256"]]
        if path.stat().st_size != ref["bytes"]:
            raise ValueError("extracted source byte length mismatch")
        return path

    batch_artifact = manifest.save(args.artifacts_directory / "diagnostic-batch.json", resolver=source_resolver)
    receipt["batch_artifact"] = batch_artifact
    receipt["batch_index_verification"] = index.verify_batch(manifest)
    protected = (*index.record_ids_for("canary", require_nonempty=False),
                 *index.record_ids_for("holdout", require_nonempty=False))
    if protected:
        try:
            index.authorize("training", protected)
        except CorpusIndexError:
            receipt["protected_partition_training_rejected"] = True
        else:
            raise ValueError("protected records were accepted for training")
    else:
        receipt["protected_partition_training_rejected"] = None
    try:
        build_corpus_manifest([by_id[key] for key in selected_ids], training_record_ids=train_ids,
                              validation_record_ids=validation_ids, mode="corpus")
    except ValueError:
        receipt["diagnostic_vectors_rejected_by_corpus_manifest"] = True
    else:
        raise ValueError("unqualified diagnostic vectors entered corpus mode")
    loaded_index = load_corpus_index(index_artifact["path"], expected_sha256=index_artifact["sha256"],
                                     expected_size_bytes=index_artifact["bytes"])
    loaded_batch = load_corpus_manifest(batch_artifact["path"], expected_sha256=batch_artifact["sha256"],
                                        expected_size_bytes=batch_artifact["bytes"])
    loaded_batch.validate_sources(source_resolver)
    receipt["reopened_batch_index_verification"] = loaded_index.verify_batch(loaded_batch)
    receipt["reopen_identical"] = receipt["reopened_batch_index_verification"] == receipt["batch_index_verification"]
    receipt["input_artifacts"] = [{"path": str(path), "sha256": digest, "bytes": path.stat().st_size}
                                   for digest, path in sorted(references.items())]
    receipt["input_artifacts_unchanged"] = all(_sha(path) == digest for digest, path in references.items())
    receipt["retained_output_bytes"] = sum(path.stat().st_size for path in args.artifacts_directory.rglob("*") if path.is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "workspace/test-logs/federal-corpus-inputs" / REVISION)
    parser.add_argument("--artifacts-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-limit", type=int, default=64)
    args = parser.parse_args()
    if args.output.exists() or args.artifacts_directory.exists() or not 32 <= args.sample_limit <= 128:
        parser.error("use new output paths and a sample limit from 32 to 128")
    args.artifacts_directory = args.artifacts_directory.resolve()
    args.artifacts_directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                       "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "CUDA_VISIBLE_DEVICES": ""})
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    paths = list(require_workspace_logic_tree().values()) + [str(Path(__file__).resolve())]
    paths += [str(ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / name) for name in (
        "autoencoder_uscode_import.py", "autoencoder_uscode_embeddings.py", "autoencoder_corpus_index.py",
        "autoencoder_corpus_manifest.py", "autoencoder_training_worker.py", "legal_ir_eval_splits.py")]
    paths += [str(ROOT / "ipfs_datasets_py/processors/legal_data" / name) for name in (
        "uscode_identity.py", "uscode_release_schema.py")]
    receipt = {"schema": "pinned-uscode-training-input-audit-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "repo_id": "justicedao/ipfs_uscode", "revision": REVISION, "manifest_sha256": MANIFEST_SHA,
        "training_performed": False, "bridge_evaluation_performed": False, "weights_downloaded": False,
        "model_inference_performed": False, "publication_performed": False, "formalized": False, "admitted": False,
        "entire_release_closure_verified": False, "heldout_canary_qualified": False,
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in paths}}
    started = time.perf_counter()
    try:
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / name) == digest for name, digest in receipt["source_hashes"].items())
        receipt["passed"] = all(receipt[key] for key in (
            "unqualified_training_embeddings_rejected", "diagnostic_vectors_rejected_by_corpus_manifest",
            "reopen_identical", "input_artifacts_unchanged", "source_unchanged")) and receipt["training_eligible_count"] == 0
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "training_performed": False,
                      "admitted": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
