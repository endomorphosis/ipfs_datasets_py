"""Inventory pinned local migration inputs without model imports or training.

The completion manifest binds this bounded preparation run to exact input and
output bytes. It does not qualify a teacher or authenticate embedding producers.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
CONFIG_SCHEMA = "gte-migration-preparation-config/v1"
MANIFEST_SCHEMA = "gte-migration-preparation-manifest/v1"
MAX_JSON_BYTES = 128 * 1024 * 1024


def _helper(name):
    """Load only the stdlib helper, avoiding optional package import hooks."""
    spec = importlib.util.spec_from_file_location(name, HELPERS / (name + ".py"))
    if spec is None or spec.loader is None:
        raise ValueError("missing preparation helper: " + name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def _local(root, name):
    if type(name) is not str or not name or "\\" in name:
        raise ValueError("relative input path required")
    candidate = Path(name)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError("relative input path without traversal required")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ValueError("input path escapes workspace")
    return path


def _read(path, expected=None):
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("input exceeds preparation byte limit")
    if expected is not None and (type(expected) is not str or len(expected) != 64
                                 or _sha(raw) != expected):
        raise ValueError("input SHA256 mismatch: " + str(path))
    return raw


def _fields(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError("closed " + label + " fields required")


def _adapt_rows(data, entry, *, max_rows):
    rows = data if entry["rows_key"] is None else data[entry["rows_key"]]
    if type(rows) is not list:
        raise ValueError("dataset row list required")
    if len(rows) > max_rows:
        raise ValueError("total row count exceeds configuration")
    output = []
    for row in rows:
        if type(row) is not dict:
            raise ValueError("dataset row object required")
        if "split" in row and row["split"] != entry["split"]:
            raise ValueError("declared split differs from archived row")
        text = row["source_text"]
        if type(text) is not str:
            raise ValueError("source text must be a string")
        if "source_sha256" in row and row["source_sha256"] != _sha(text.encode("utf-8")):
            raise ValueError("archived source SHA256 mismatch")
        target = row.get("target")
        output.append({
            "id": row["id"], "domain_id": entry["domain_id"],
            "document_id": row[entry["document_field"]],
            "group_id": row[entry["group_field"]], "split": entry["split"],
            "source_text": text, "embedding": row.get("embedding"),
            "reference_target": target,
            "target_origin": entry["target_origin"] if target is not None else "unlabeled",
            "source_language": entry["source_language"],
            "evaluation_role": entry["evaluation_role"],
        })
    return output


def run_preparation(config_path, output_directory, *, workspace_root=None):
    root = Path(workspace_root or REPOSITORY.parent.parent).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise ValueError("fresh output directory required")
    config_raw = _read(Path(config_path))
    config = _strict_json(config_raw)
    _fields(config, {"schema", "dimension", "vector_space_id", "max_rows",
                     "checkpoints", "datasets", "source_files"}, "configuration")
    if config["schema"] != CONFIG_SCHEMA:
        raise ValueError("unsupported configuration schema")
    if type(config["max_rows"]) is not int or not 1 <= config["max_rows"] <= 100000:
        raise ValueError("bounded total row count required")
    for name in ("checkpoints", "datasets", "source_files"):
        if type(config[name]) is not list or len(config[name]) > 128:
            raise ValueError("bounded input lists required")
    if not config["datasets"]:
        raise ValueError("at least one dataset required")
    tool_paths = [Path(__file__).resolve(), HELPERS / "gte_migration_inventory.py",
                  HELPERS / "gte_transfer_corpus.py"]
    executing_sources = []
    for path in tool_paths:
        if not path.resolve().is_relative_to(root):
            raise ValueError("preparation implementation must lie in workspace")
        raw = _read(path)
        executing_sources.append({"path": str(path.resolve().relative_to(root)),
                                  "bytes": len(raw), "sha256": _sha(raw)})
    inventory = _helper("gte_migration_inventory")
    corpus = _helper("gte_transfer_corpus")
    input_refs, checkpoint_reports, dataset_reports, rows = [], [], [], []
    input_ids = set()
    for entry in config["checkpoints"]:
        _fields(entry, {"id", "path", "sha256"}, "checkpoint entry")
        if type(entry["id"]) is not str or not entry["id"] or entry["id"] in input_ids:
            raise ValueError("unique input IDs required")
        input_ids.add(entry["id"])
        path = _local(root, entry["path"])
        raw = _read(path, entry["sha256"])
        report = inventory.inspect_checkpoint(path, max_bytes=MAX_JSON_BYTES)
        if report["sha256"] != _sha(raw):
            raise ValueError("checkpoint changed during inspection")
        checkpoint_reports.append({"id": entry["id"], "input_path": entry["path"], **report})
        input_refs.append({"path": entry["path"], "bytes": len(raw), "sha256": _sha(raw)})
    for entry in config["datasets"]:
        _fields(entry, {"id", "path", "sha256", "domain_id", "split", "rows_key",
                        "group_field", "document_field", "source_language", "target_origin",
                        "evaluation_role", "source_exposure", "document_identity_policy"}, "dataset entry")
        if type(entry["id"]) is not str or not entry["id"] or entry["id"] in input_ids:
            raise ValueError("unique input IDs required")
        input_ids.add(entry["id"])
        if entry["source_exposure"] not in {"archived_diagnostic_exposed", "fresh_sealed"}:
            raise ValueError("explicit source exposure required")
        if entry["evaluation_role"] == "sealed" and entry["source_exposure"] != "fresh_sealed":
            raise ValueError("exposed artifacts cannot be declared sealed")
        if type(entry["document_identity_policy"]) is not str or not entry["document_identity_policy"]:
            raise ValueError("document identity policy required")
        path = _local(root, entry["path"])
        raw = _read(path, entry["sha256"])
        data = _strict_json(raw)
        adapted = _adapt_rows(data, entry, max_rows=config["max_rows"] - len(rows))
        rows.extend(adapted)
        if len(rows) > config["max_rows"]:
            raise ValueError("total row count exceeds configuration")
        dataset_reports.append({"id": entry["id"], "path": entry["path"], "rows": len(adapted),
                                "domain_id": entry["domain_id"], "split": entry["split"],
                                "declared_target_origin": entry["target_origin"],
                                "evaluation_role": entry["evaluation_role"],
                                "source_exposure": entry["source_exposure"],
                                "source_exposure_verified": False,
                                "document_identity_policy": entry["document_identity_policy"],
                                "archived_embedding_metadata_sha256": _sha(_canonical(data["source_embeddings"]))
                                if type(data) is dict and "source_embeddings" in data else None})
        input_refs.append({"path": entry["path"], "bytes": len(raw), "sha256": _sha(raw)})
    sources = []
    for entry in config["source_files"]:
        _fields(entry, {"path", "sha256"}, "source entry")
        raw = _read(_local(root, entry["path"]), entry["sha256"])
        sources.append({"path": entry["path"], "bytes": len(raw), "sha256": _sha(raw)})
    audit = corpus.audit_transfer_rows(rows, dimension=config["dimension"],
                                      vector_space_id=config["vector_space_id"], max_rows=config["max_rows"])
    # Listed implementation bytes are captured before helper loading and
    # rechecked before publication; this is not runtime attestation.
    sources.extend(executing_sources)
    sources_by_path = {}
    for ref in sources:
        if ref["path"] in sources_by_path and sources_by_path[ref["path"]] != ref:
            raise ValueError("conflicting source bindings")
        sources_by_path[ref["path"]] = ref
    sources = [sources_by_path[name] for name in sorted(sources_by_path)]
    for ref in input_refs + sources:
        _read(_local(root, ref["path"]), ref["sha256"])
    summary = {"schema": "gte-migration-preparation-summary/v1",
               "status": "prepared_inventory_not_teacher_qualification",
               "checkpoints": len(checkpoint_reports), "dataset_files": len(dataset_reports),
               "input_rows": len(rows), "dimension": config["dimension"],
               "vector_space_id": config["vector_space_id"],
               "teacher_replay_executed": False, "teacher_qualified": False,
               "typed_targets_validated": False, "embedding_producer_verified": False,
               "training_executed": False, "download_executed": False,
               "sealed_evaluation_rows_declared": sum(row["evaluation_role"] == "sealed" for row in rows),
               "evaluation_seals_verified": False,
               "limitations": ["Input declarations and hashes do not authenticate target or embedding origins",
                               "This audit does not execute a decoder or establish source fidelity",
                               "Exposure and sealed roles are caller declarations; independent sealing is not verified",
                               "Archived test and canary inputs remain exposed development evidence"]}
    payloads = {"input-config.json": config_raw,
                "checkpoint-inventory.json": _canonical(checkpoint_reports) + b"\n",
                "dataset-inventory.json": _canonical(dataset_reports) + b"\n",
                "corpus-audit.json": _canonical(audit) + b"\n",
                "summary.json": _canonical(summary) + b"\n"}
    output.mkdir(parents=True, exist_ok=False)
    file_refs = []
    for name, raw in payloads.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
        file_refs.append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    manifest = {"schema": MANIFEST_SCHEMA, "completed": True,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "files": file_refs, "inputs": input_refs, "sources": sources,
                "identity_scope": "listed_inputs_outputs_and_preparation_code_only"}
    manifest_raw = _canonical(manifest) + b"\n"
    with (output / "manifest.json").open("xb") as stream:
        stream.write(manifest_raw)
    return {**summary, "manifest_sha256": _sha(manifest_raw)}


def verify_preparation(output_directory, *, expected_manifest_sha256, workspace_root=None):
    root = Path(workspace_root or REPOSITORY.parent.parent).resolve()
    output = Path(output_directory).resolve()
    manifest_raw = _read(output / "manifest.json", expected_manifest_sha256)
    manifest = _strict_json(manifest_raw)
    _fields(manifest, {"schema", "completed", "captured_at_utc", "files", "inputs",
                       "sources", "identity_scope"}, "completion manifest")
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["completed"] is not True:
        raise ValueError("complete preparation manifest required")
    for section in ("files", "inputs", "sources"):
        for ref in manifest[section]:
            _fields(ref, {"path", "bytes", "sha256"}, "file reference")
            path = _local(output if section == "files" else root, ref["path"])
            raw = _read(path, ref["sha256"])
            if len(raw) != ref["bytes"]:
                raise ValueError("file size mismatch")
    return {"schema": "gte-migration-preparation-verification/v1", "verified": True,
            "manifest_sha256": _sha(manifest_raw),
            "output_files": len(manifest["files"]), "input_files": len(manifest["inputs"]),
            "source_files": len(manifest["sources"]),
            "semantic_qualification": False, "scope": manifest["identity_scope"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="inspect pinned local inputs into a fresh directory")
    prepare.add_argument("--config", required=True, type=Path)
    prepare.add_argument("--output-directory", required=True, type=Path)
    prepare.add_argument("--workspace-root", type=Path)
    verify = commands.add_parser("verify", help="recheck recorded input, output and implementation bytes")
    verify.add_argument("--output-directory", required=True, type=Path)
    verify.add_argument("--expected-manifest-sha256", required=True)
    verify.add_argument("--workspace-root", type=Path)
    args = parser.parse_args()
    try:
        result = (run_preparation(args.config, args.output_directory, workspace_root=args.workspace_root)
                  if args.command == "prepare" else
                  verify_preparation(args.output_directory,
                                     expected_manifest_sha256=args.expected_manifest_sha256,
                                     workspace_root=args.workspace_root))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, "preparation failed: " + str(error) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
