#!/usr/bin/env python3
"""Prepare authored LegalIR targets with source-bound offline GTE-small inputs.

This is a diagnostic corpus, not reviewed statutory supervision. The embedding
producer receives source text only; canonical targets are copied unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SPLITS = ("train", "tuning", "heldout", "regression")
FIXTURE = ROOT / "tests/fixtures/legal_formula_learning/v1.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(path, value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with Path(path).open("xb") as stream:
        stream.write(payload)
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def prepare(output_directory, *, fixture=FIXTURE):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan

    fixture = Path(fixture).resolve(strict=True)
    fixture_sha = _sha(fixture)
    supplied = json.loads(fixture.read_bytes())
    if supplied.get("provenance") != "authored_synthetic_not_legal_authority":
        raise ValueError("this diagnostic preparer requires explicit authored target provenance")
    rows = [(split, row) for split in SPLITS for row in supplied[split]]
    if not 1 <= len(rows) <= 128:
        raise ValueError("pilot requires 1..128 total sources")
    identifiers = [row["id"] for _, row in rows]
    if len(set(identifiers)) != len(rows):
        raise ValueError("pilot source identifiers must be unique across partitions")
    for _, row in rows:
        legal_formula_codec._rule(row["canonical_ir"])

    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = output / "sources"
    sources.mkdir()
    inputs, source_paths, bindings = [], {}, []
    for ordinal, (split, row) in enumerate(rows):
        raw = row["source_text"].encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        path = sources / (digest + ".txt")
        if digest not in source_paths:
            with path.open("xb") as stream:
                stream.write(raw)
            source_paths[digest] = path
        citation = "Authored diagnostic: " + row["id"]
        span = SourceSpan(SourceArtifact(digest, len(raw)), "diagnostic", fixture_sha,
                          row["id"], "en", citation, 0, len(raw), "identity")
        item = codec.EmbeddingInput(span, "diagnostic", str(ordinal), row["source_text"], citation)
        inputs.append(item)
        bindings.append({"split": split, "id": row["id"], "input_id": item.input_id,
                         "source_sha256": digest, "source_path": str(path)})

    def resolver(ref):
        path = source_paths[ref["sha256"]]
        if path.stat().st_size != ref["bytes"]:
            raise ValueError("source bytes changed")
        return path

    started = time.monotonic()
    receipt = producer.produce_native_embedding_receipt(inputs, resolver=resolver, batch_size=16)
    seconds = time.monotonic() - started
    if receipt.status_counts != {"embedded": len(rows), "token_limit_exceeded": 0, "missing_input": 0}:
        raise ValueError("every diagnostic input must have a complete native embedding")
    receipt_ref = receipt.save(output / "embedding-production.json", resolver=resolver)
    loaded = codec.load_embedding_production_receipt(receipt_ref["path"],
        expected_sha256=receipt_ref["sha256"], expected_size_bytes=receipt_ref["bytes"], resolver=resolver)
    if loaded.to_bytes() != receipt.to_bytes():
        raise ValueError("reopened production receipt differs")
    data = loaded.to_dict()
    vectors = {row["input_id"]: list(struct.unpack(">384f", bytes.fromhex(row["vector"]["bits"])))
               for row in data["results"]}
    splits = {split: [] for split in SPLITS}
    for (split, row), item in zip(rows, inputs):
        splits[split].append({"id": row["id"], "source_text": row["source_text"],
                              "canonical_ir": row["canonical_ir"], "embedding": vectors[item.input_id]})
    if _sha(fixture) != fixture_sha:
        raise ValueError("fixture changed during preparation")
    binding_ref = _save(output / "source-bindings.json", bindings)
    corpus = {"schema": "legal-decoder-pilot-corpus/v1", "label_origin": supplied["provenance"],
        "fixture": {"path": str(fixture), "sha256": fixture_sha},
        "embedding_receipt": receipt_ref, "model": data["model"], "splits": splits,
        "source_bindings": binding_ref, "source_paths": {key: str(value) for key, value in source_paths.items()},
        "model_assets": data["model_assets"],
        "producer": data["producer"], "producer_execution": data["execution"],
        "preparer": {"path": str(Path(__file__).resolve()), "sha256": _sha(__file__)},
        "partition_policy": supplied["partition_policy"], "preparation_seconds": seconds,
        "independently_reviewed": False, "natural_legal_corpus": False,
        "training_executed": False, "qualified": False, "admitted": False}
    corpus_ref = _save(output / "corpus.json", corpus)
    return {"corpus": corpus_ref, "embedding_receipt": receipt_ref,
            "split_counts": {split: len(splits[split]) for split in SPLITS},
            "receipt_verification": loaded.verification_summary()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.output_directory, fixture=args.fixture), sort_keys=True))


if __name__ == "__main__":
    main()
