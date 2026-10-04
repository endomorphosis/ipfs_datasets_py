"""Reuse archived embeddings and list only missing multilingual inputs.

This operation authenticates existing rows, their complete audit, tasks and
cached receipts. It loads no encoder or model assets and never regenerates an
embedding. Original 384D vectors retain their profile and serve as targets.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
SCHEMA = "gte-embedding-reuse-config/v1"
REFERENCES = ("rows_384", "corpus_audit", "tasks", "receipts_768")
HELPER_NAMES = ("gte_worker_contract", "gte_transfer_corpus", "gte_multilingual_corpus", "gte_embedding_reuse")
MAX_BYTES = 128 * 1024 * 1024
MAX_ROWS = 4096


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_reuse_cli_" + name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def _file(reader, path):
    _, receipt, _ = reader._read_stable(path, max_bytes=MAX_BYTES)
    return receipt


def _recheck(reader, receipts):
    for ref in receipts:
        _require(_file(reader, ref["path"]) == ref, "input or implementation changed during reuse")


def _configuration(path, expected_sha256, reader):
    config, captured = reader.read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "mode", "expected_asset_manifest_sha256", *REFERENCES}
    _require(type(config) is dict and set(config) == fields and config["schema"] == SCHEMA
             and config["mode"] == "reuse", "closed reuse-only configuration required")
    asset_pin = config["expected_asset_manifest_sha256"]
    _require(type(asset_pin) is str and re.fullmatch("[0-9a-f]{64}", asset_pin),
             "explicit selected asset manifest SHA256 required")
    _require(type(config["workspace_root"]) is str, "workspace root must be an absolute directory")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "workspace root must be an absolute directory")
    root = root.resolve()
    payloads, receipts = {}, [captured]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}
                 and type(ref["path"]) is str and bool(ref["path"]), "closed workspace input reference required")
        relative = Path(ref["path"])
        _require(not relative.is_absolute() and ".." not in relative.parts, "workspace-relative input required")
        resolved = (root / relative).resolve()
        _require(resolved.is_relative_to(root), "input is outside the workspace")
        payloads[name], receipt = reader.read_pinned_json(resolved,
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        receipts.append(receipt)
    return config, payloads, receipts


def _output_directory(path, inputs):
    requested = Path(path).absolute()
    _require(not any(part.is_symlink() for part in (*requested.parents, requested)),
             "output namespace cannot contain symlinks")
    output = requested.resolve()
    _require(not output.exists(), "fresh output directory required")
    for namespace in (REPOSITORY, *(Path(ref["path"]).parent for ref in inputs)):
        _require(not output.is_relative_to(namespace) and not namespace.is_relative_to(output),
                 "output aliases an input or implementation namespace")
    return output


def _write(directory, name, value):
    raw = _raw(value)
    with (directory / name).open("xb") as stream:
        stream.write(raw)
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def prepare_embedding_reuse(config_path, *, expected_config_sha256, output_directory):
    reader = _helper("gte_worker_contract")
    tools = [_file(reader, Path(__file__)), *[_file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    config, payloads, inputs = _configuration(config_path, expected_config_sha256, reader)
    rows = payloads["rows_384"]
    _require(type(rows) is list and len(rows) <= MAX_ROWS, "archived rows exceed the 4096 row limit")
    corpus = _helper("gte_multilingual_corpus")
    tasks = corpus.prepare_embedding_tasks(rows, payloads["corpus_audit"], max_rows=MAX_ROWS)
    _require(_raw(tasks) == _raw(payloads["tasks"]), "tasks do not reproduce from the archived vectors and audit")
    reuse = _helper("gte_embedding_reuse").prepare_cached_embedding_reuse(tasks, payloads["receipts_768"],
        expected_asset_manifest_sha256=config["expected_asset_manifest_sha256"], max_rows=MAX_ROWS)
    output = _output_directory(output_directory, inputs)
    summary = {"schema": "gte-embedding-reuse-summary/v1", "operation": "reuse-archived-embeddings",
        "status": reuse["status"], "archive_384_row_count": len(rows),
        "archive_384_vector_count": sum(type(row) is dict and type(row.get("embedding")) is list for row in rows),
        "task_count": reuse["task_count"], "cached_receipt_count": reuse["cached_receipt_count"],
        "missing_task_count": reuse["missing_task_count"], "profile_id": reuse["profile_id"],
        "asset_manifest_sha256": reuse["asset_manifest_sha256"], "archive_384_embeddings_regenerated": False,
        "cached_vectors_unchanged": True, "source_vectors_relabelled": False,
        "encoder_inference_executed": False, "embeddings_generated": False, "training_executed": False,
        "distillation_executed": False, "download_executed": False,
        "producer_execution_authenticated": False, "source_fidelity_qualified": False, "proof_authority": False}
    _recheck(reader, [*inputs, *tools])
    output.mkdir(parents=True, exist_ok=False)
    outputs = [_write(output, name, value) for name, value in (
        ("receipts.json", reuse["reused_receipts"]), ("missing-tasks.json", reuse["missing_tasks"]),
        ("binding.json", reuse["binding"]), ("reuse.json", reuse), ("summary.json", summary))]
    _recheck(reader, [*inputs, *tools])
    for ref in outputs:
        current = _file(reader, output / ref["path"])
        _require(current["bytes"] == ref["bytes"] and current["sha256"] == ref["sha256"],
                 "reuse output changed before completion")
    manifest = {"schema": "gte-embedding-reuse-manifest/v1", "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "status": summary["status"],
        "inputs": inputs, "implementation_files": tools, "outputs": outputs,
        "embeddings_generated": False, "encoder_inference_executed": False, "training_executed": False,
        "distillation_executed": False, "download_executed": False, "proof_authority": False}
    completion = _write(output, "manifest.json", manifest)
    return {**summary, "output_directory": str(output), "manifest_sha256": completion["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_embedding_reuse(args.config, expected_config_sha256=args.expected_config_sha256,
                                         output_directory=args.output_directory)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] == "ready" else 1
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
