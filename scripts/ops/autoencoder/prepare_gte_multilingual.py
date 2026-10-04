"""Prepare and explicitly embed pinned source-only 768D tasks offline.

Preparation and asset inspection import only standard-library helpers. Model
execution occurs only through the explicit ``embed`` command. Completion
manifests bind input, implementation and output bytes without qualifying IRs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
MANIFEST_SCHEMA = "gte-multilingual-preparation-manifest/v1"
MAX_ROWS = 4096
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 65536
MAX_PER_SOURCE_BYTES = 262144
MAX_JSON_BYTES = 128 * 1024 * 1024
MAX_TOOL_BYTES = 8 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(value):
    return Path(value).resolve()


def _asset_path(value):
    # Preserve symlinks for the inspector's component-by-component rejection.
    path = Path(os.path.abspath(os.fspath(value)))
    _require(".." not in Path(value).parts, "asset path traversal is unsupported")
    return path


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _tool_receipt(path):
    path = _path(path)
    before = path.stat()
    _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_TOOL_BYTES,
             "bounded regular implementation file required")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        _require(_identity(os.fstat(stream.fileno())) == _identity(before),
                 "implementation file changed before reading")
        raw = stream.read(MAX_TOOL_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) == before.st_size and len(raw) <= MAX_TOOL_BYTES
             and _identity(before) == _identity(after) == _identity(path.stat()),
             "implementation file changed while reading")
    return {"path": str(path), "bytes": len(raw), "sha256": _sha(raw)}


def _tool_snapshot(names):
    paths = [Path(__file__), *(HELPERS / (name + ".py") for name in names)]
    return [_tool_receipt(path) for path in paths]


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_multilingual_cli_" + name,
                                                HELPERS / (name + ".py"))
    _require(spec is not None and spec.loader is not None, "cannot load helper: " + name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _recheck_tools(receipts):
    for receipt in receipts:
        _require(_tool_receipt(receipt["path"]) == receipt,
                 "implementation SHA256 changed during operation")


def _read(reader, path, pin):
    _require(type(pin) is str and len(pin) == 64, "expected input SHA256 required")
    return reader.read_pinned_json(_path(path), expected_sha256=pin,
                                   max_bytes=MAX_JSON_BYTES)


def _recheck_inputs(reader, receipts):
    for receipt in receipts:
        _, current = _read(reader, receipt["path"], receipt["sha256"])
        _require(current == receipt, "input changed during operation")


def _fresh_directory(output_directory, inputs, *, protected_directories=()):
    output = _path(output_directory)
    _require(not output.exists(), "output directory must be fresh")
    for receipt in inputs:
        path = Path(receipt["path"])
        _require(output != path and not path.is_relative_to(output),
                 "output directory aliases an input namespace")
    for directory in (HELPERS, REPOSITORY / "scripts/ops/autoencoder", *protected_directories):
        directory = _path(directory)
        _require(output != directory and not output.is_relative_to(directory)
                 and not directory.is_relative_to(output),
                 "output directory aliases an implementation or asset namespace")
    return output


def _write(path, payload):
    raw = _canonical(payload)
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": path.name, "bytes": len(raw), "sha256": _sha(raw)}


def _publish(output, payloads, summary, *, inputs, tools, reader, asset_check=None):
    _recheck_inputs(reader, inputs)
    _recheck_tools(tools)
    if asset_check is not None:
        asset_check()
    output.mkdir(parents=True, exist_ok=False)
    outputs = [_write(output / name, payload) for name, payload in payloads.items()]
    outputs.append(_write(output / "summary.json", summary))
    _recheck_inputs(reader, inputs)
    _recheck_tools(tools)
    manifest = {"schema": MANIFEST_SCHEMA, "operation": summary["operation"],
                "completed": True, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "inputs": inputs, "implementation_files": tools, "outputs": outputs,
                "status": summary["status"], "proof_authority": False,
                "target_semantics_verified": False}
    receipt = _write(output / "manifest.json", manifest)
    return {**summary, "output_directory": str(output),
            "manifest_sha256": receipt["sha256"]}


def _source_budget(tasks):
    _require(type(tasks) is list and len(tasks) <= MAX_ROWS,
             "tasks exceed the 4096 row limit")
    total = 0
    for task in tasks:
        source = task["source_text"]
        _require(0 < len(source) <= MAX_SOURCE_CHARACTERS and "\0" not in source,
                 "each source must be within 65536 characters and contain no NUL")
        raw = source.encode("utf-8")
        _require(len(raw) <= MAX_PER_SOURCE_BYTES, "source exceeds the 262144 byte UTF8 limit")
        total += len(raw)
    _require(total <= MAX_SOURCE_BYTES, "sources exceed the 16 MiB UTF8 limit")
    return total


def prepare_tasks(rows_path, *, expected_rows_sha256, corpus_audit_path,
                  expected_audit_sha256, output_directory):
    tools = _tool_snapshot(("gte_worker_contract", "gte_multilingual_corpus", "gte_transfer_corpus"))
    reader = _helper("gte_worker_contract")
    rows, rows_receipt = _read(reader, rows_path, expected_rows_sha256)
    audit, audit_receipt = _read(reader, corpus_audit_path, expected_audit_sha256)
    _require(type(rows) is list and len(rows) <= MAX_ROWS, "rows must be a list of at most 4096 records")
    inputs = [rows_receipt, audit_receipt]
    output = _fresh_directory(output_directory, inputs)
    corpus = _helper("gte_multilingual_corpus")
    tasks = corpus.prepare_embedding_tasks(rows, audit, max_rows=MAX_ROWS)
    source_bytes = _source_budget(tasks["tasks"])
    binding = corpus.bind_embedding_receipts(tasks, [])
    summary = {"schema": "gte-multilingual-preparation-summary/v1", "operation": "prepare",
               "status": "prepared", "input_rows": len(rows), "task_count": tasks["task_count"],
               "rejected_row_count": tasks["rejected_row_count"], "source_bytes": source_bytes,
               "coverage_status": binding["status"], "model_execution_attempted": False,
               "embeddings_generated": False, "target_semantics_verified": False,
               "proof_authority": False}
    return _publish(output, {"tasks.json": tasks, "binding.json": binding}, summary,
                    inputs=inputs, tools=tools, reader=reader)


def _asset_inputs(reader, manifest_path, expected_manifest_sha256):
    path = _asset_path(manifest_path)
    if not path.exists():
        return []
    _, receipt = _read(reader, path, expected_manifest_sha256)
    return [receipt]


def inspect_assets(*, manifest_path, expected_manifest_sha256, model_directory,
                   code_directory, report_file):
    tools = _tool_snapshot(("gte_worker_contract", "gte_multilingual_profile"))
    reader = _helper("gte_worker_contract")
    inspector = _helper("gte_multilingual_profile")
    manifest_path, model_directory, code_directory = map(
        _asset_path, (manifest_path, model_directory, code_directory))
    report = _path(report_file)
    _require(not report.exists(), "report file must be fresh")
    _require(report != _path(manifest_path), "report aliases the asset manifest input")
    for directory in (HELPERS, REPOSITORY / "scripts/ops/autoencoder", model_directory, code_directory):
        _require(not report.is_relative_to(_path(directory)),
                 "report aliases an implementation or asset namespace")
    result = inspector.inspect_local_assets(manifest_path, expected_sha256=expected_manifest_sha256,
                                            model_directory=model_directory, code_directory=code_directory)
    inputs = _asset_inputs(reader, manifest_path, expected_manifest_sha256)
    _recheck_inputs(reader, inputs)
    _recheck_tools(tools)
    report.parent.mkdir(parents=True, exist_ok=True)
    _write(report, {**result, "implementation_files": tools, "completed": True,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat()})
    return {"status": result["status"], "report_file": str(report),
            "model_execution_attempted": False, "unavailable_reasons": result["unavailable_reasons"]}


def embed_tasks(tasks_path, *, expected_tasks_sha256, manifest_path,
                expected_manifest_sha256, model_directory, code_directory,
                output_directory, batch_size=1):
    _require(type(batch_size) is int and 1 <= batch_size <= 16, "batch_size must be between 1 and 16")
    tools = _tool_snapshot(("gte_worker_contract", "gte_multilingual_corpus", "gte_transfer_corpus",
                            "gte_multilingual_profile", "source_embeddings_768"))
    reader = _helper("gte_worker_contract")
    tasks, tasks_receipt = _read(reader, tasks_path, expected_tasks_sha256)
    corpus = _helper("gte_multilingual_corpus")
    empty_binding = corpus.bind_embedding_receipts(tasks, [])
    data = tasks["tasks"] if type(tasks) is dict else tasks
    source_bytes = _source_budget(data)
    manifest_path, model_directory, code_directory = map(
        _asset_path, (manifest_path, model_directory, code_directory))
    inputs = [tasks_receipt, *_asset_inputs(reader, manifest_path, expected_manifest_sha256)]
    inputs_for_namespace = [*inputs, {"path": str(_path(manifest_path))}]
    output = _fresh_directory(output_directory, inputs_for_namespace,
                              protected_directories=(model_directory, code_directory))
    producer = _helper("source_embeddings_768")
    result = producer.embed_rows([{"id": task["id"], "source_text": task["source_text"]} for task in data],
                                 manifest_path=manifest_path,
                                 expected_manifest_sha256=expected_manifest_sha256,
                                 model_directory=model_directory, code_directory=code_directory,
                                 batch_size=batch_size)
    _require(type(result) is dict and result.get("status") in ("completed", "unavailable")
             and type(result.get("receipts")) is list, "producer returned an unsupported report")
    _require(result["status"] != "unavailable" or not result["receipts"],
             "unavailable producer cannot return embeddings")
    binding = corpus.bind_embedding_receipts(tasks, result["receipts"])
    status = "unavailable" if result["status"] == "unavailable" else binding["status"]
    summary = {"schema": "gte-multilingual-preparation-summary/v1", "operation": "embed",
               "status": status, "task_count": empty_binding["task_count"],
               "accepted_count": binding["accepted_count"], "source_bytes": source_bytes,
               "coverage_status": binding["status"], "batch_size": batch_size,
               "model_execution_attempted": result["model_inference_executed"],
               "embeddings_generated": bool(result["receipts"]),
               "asset_selection": {"manifest_path": str(manifest_path),
                                   "expected_manifest_sha256": expected_manifest_sha256,
                                   "model_directory": str(model_directory),
                                   "code_directory": str(code_directory)},
               "target_semantics_verified": False, "proof_authority": False}
    inspector = _helper("gte_multilingual_profile")

    def asset_check():
        checked = inspector.inspect_local_assets(manifest_path, expected_sha256=expected_manifest_sha256,
                                                  model_directory=model_directory,
                                                  code_directory=code_directory)
        expected_status = "available" if result["status"] == "completed" else "unavailable"
        _require(checked["status"] == expected_status, "asset availability changed before publication")
        _require(type(result.get("assets")) is dict and _canonical(checked) == _canonical(result["assets"]),
                 "asset admission receipt changed before publication")
        if result["receipts"]:
            _require(binding["asset_manifest_sha256"] == checked["manifest_sha256"],
                     "producer receipts differ from the pinned asset manifest")

    return _publish(output, {"receipts.json": result["receipts"], "binding.json": binding,
                              "producer-report.json": result}, summary,
                    inputs=inputs, tools=tools, reader=reader, asset_check=asset_check)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--rows-file", required=True)
    prepare.add_argument("--expected-rows-sha256", required=True)
    prepare.add_argument("--corpus-audit-file", required=True)
    prepare.add_argument("--expected-audit-sha256", required=True)
    prepare.add_argument("--output-directory", required=True)
    inspect = subcommands.add_parser("inspect-assets")
    embed = subcommands.add_parser("embed")
    for command in (inspect, embed):
        command.add_argument("--asset-manifest", required=True)
        command.add_argument("--expected-asset-manifest-sha256")
        command.add_argument("--model-directory", required=True)
        command.add_argument("--code-directory", required=True)
    inspect.add_argument("--report-file", required=True)
    embed.add_argument("--tasks-file", required=True)
    embed.add_argument("--expected-tasks-sha256", required=True)
    embed.add_argument("--output-directory", required=True)
    embed.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_tasks(args.rows_file, expected_rows_sha256=args.expected_rows_sha256,
                                   corpus_audit_path=args.corpus_audit_file,
                                   expected_audit_sha256=args.expected_audit_sha256,
                                   output_directory=args.output_directory)
        else:
            asset_args = {"manifest_path": args.asset_manifest,
                          "expected_manifest_sha256": args.expected_asset_manifest_sha256,
                          "model_directory": args.model_directory, "code_directory": args.code_directory}
            if args.command == "inspect-assets":
                result = inspect_assets(**asset_args, report_file=args.report_file)
            else:
                result = embed_tasks(args.tasks_file, expected_tasks_sha256=args.expected_tasks_sha256,
                                     **asset_args, output_directory=args.output_directory,
                                     batch_size=args.batch_size)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 1 if result["status"] in ("unavailable", "incomplete") else 0
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
