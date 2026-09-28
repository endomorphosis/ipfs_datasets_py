#!/usr/bin/env python3
"""Publish retained census/goal bundles; never rerun training or enqueue a supervisor."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import stat
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
MAX_INPUT_BYTES = 64 * 1024 * 1024


def _snapshot(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INPUT_BYTES:
            raise ValueError("input must be a bounded regular file")
        raw = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != before.st_size or len(raw) > MAX_INPUT_BYTES
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError("input changed or exceeds 64 MiB")
    return raw


def retained_exchange_inputs(parquet_path: Path, provenance_path: Path):
    """Bind complete historical outputs to their producer receipt before export."""
    import pyarrow.parquet as pq

    raw, proof_raw = _snapshot(parquet_path), _snapshot(provenance_path)
    proof = json.loads(proof_raw)
    parquet = pq.ParquetFile(io.BytesIO(raw))
    binding = proof.get("parquet") or {}
    if (binding.get("sha256") != hashlib.sha256(raw).hexdigest()
            or binding.get("bytes") != len(raw)
            or binding.get("row_count") != parquet.metadata.num_rows):
        raise ValueError("retained evidence does not match its producer receipt")
    if not 1 <= parquet.metadata.num_rows <= 64:
        raise ValueError("retained batch requires 1..64 rows")
    if sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.num_row_groups)) > MAX_INPUT_BYTES:
        raise ValueError("decoded evidence exceeds 64 MiB")
    if proof.get("admitted") is not False or proof.get("formalized") is not False:
        raise ValueError("retained output cannot grant admission")
    if proof.get("source_backed") is not True:
        raise ValueError("retained publication requires a source-backed producer receipt")
    if proof.get("learned_autoencoder_execution") is not False or proof.get("codec_kind") != "DeterministicModalLogicCodec":
        raise ValueError("this retained-evidence adapter requires the explicitly identified deterministic codec")
    hashes = proof.get("compiler_path_hashes")
    if (not isinstance(hashes, dict) or not hashes
            or any(not isinstance(value, str) or len(value) != 64
                   or any(ch not in "0123456789abcdef" for ch in value) for value in hashes.values())):
        raise ValueError("retained evidence requires compiler source provenance")
    rows = parquet.read(use_threads=False).to_pylist()
    ids = [row.get("source_span_id") for row in rows]
    if len(set(ids)) != len(ids) or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("retained source identities are missing or duplicated")
    for key in ("compiler_inputs", "codec_observations"):
        captured = proof.get(key)
        if not isinstance(captured, list) or len(captured) != len(ids) or {row.get("source_span_id") for row in captured} != set(ids):
            raise ValueError("retained capture does not cover every source row")
    for row in rows:
        source = str(row.get("source_text") or "")
        observed = next(item for item in proof["compiler_inputs"] if item["source_span_id"] == row["source_span_id"])
        codec = next(item for item in proof["codec_observations"] if item["source_span_id"] == row["source_span_id"])
        if codec.get("injected_capture") is not False:
            raise ValueError("retained publication requires actual codec observations")
        if observed.get("original_source_text") != source or observed.get("original_source_sha256") != hashlib.sha256(source.encode()).hexdigest():
            raise ValueError("retained compiler observation is bound to different source text")
        if codec.get("codec_input_sha256") != hashlib.sha256(source.encode()).hexdigest():
            raise ValueError("retained codec observation is bound to different source text")
        compiler_input = observed.get("compiler_input")
        if (not isinstance(compiler_input, str)
                or observed.get("compiler_input_sha256") != hashlib.sha256(compiler_input.encode()).hexdigest()):
            raise ValueError("retained compiler input hash mismatch")
    spec = importlib.util.spec_from_file_location("_span_evidence_exchange_adapter", ROOT / "scripts/ops/legal_ir/publish_span_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = module._exchange_inputs(rows, proof, hashes)
    binding = {"evidence_sha256": hashlib.sha256(raw).hexdigest(),
               "provenance_sha256": hashlib.sha256(proof_raw).hexdigest(),
               "historical_producer": True, "codec_rerun": False, "training_executed": False}
    for item in inputs:
        item["retained_producer_binding"] = binding
    from ipfs_datasets_py.logic.autoformal.span_cache import compiler_identity
    return inputs, compiler_identity(hashes), binding


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-parquet", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--agent-id", default="retained-census-export")
    parser.add_argument("--release-id", default="ipfs-uscode-5016b86a")
    parser.add_argument("--retry-pending", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.receipt.exists() or args.receipt.is_symlink():
        parser.error("receipt must be new")
    if args.retry_pending == bool(args.input_parquet or args.provenance):
        parser.error("choose --retry-pending or both --input-parquet and --provenance")
    if not args.retry_pending and not (args.input_parquet and args.provenance):
        parser.error("both retained input files are required")
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import (
        pending_exchange_manifests, publish_compiled_exchange, publish_exchange_manifest,
    )
    pin = require_workspace_logic_tree()
    result = {"schema": "uscode-census-exchange-publication/v1", "admitted": False,
              "formalized": False, "enqueued": False, "training_executed": False,
              "tree_pin": pin, "upload_requested": args.upload, "bundles": [], "error": None}
    code = 0
    try:
        if args.retry_pending:
            for path in pending_exchange_manifests(args.outbox):
                result["bundles"].append(publish_exchange_manifest(path, upload=args.upload))
        else:
            inputs, identity, binding = retained_exchange_inputs(args.input_parquet, args.provenance)
            result["retained_producer_binding"] = binding
            result["bundles"].append(publish_compiled_exchange(
                inputs, args.outbox, upload=args.upload, agent_id=args.agent_id,
                release_id=args.release_id, code_identity=identity,
                model_identity="deterministic-modal-codec:no-learned-checkpoint",
            ))
        if any(row.get("error") for row in result["bundles"]):
            code = 1
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)[:1500]}
        code = 1
    result["passed"] = code == 0
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"passed": result["passed"], "receipt": str(args.receipt),
                      "bundle_count": len(result["bundles"]), "admitted": False}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
