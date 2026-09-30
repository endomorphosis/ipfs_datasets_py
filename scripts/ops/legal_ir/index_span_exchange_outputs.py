#!/usr/bin/env python3
"""Expose retained AE/compiler observations without running models or supervisor work.

Read one bounded, verified exchange at a time. Append content-addressed derived
tables; never replace the source census, goals, progress ledger, or weights.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = "justicedao/uscode-autoformal-span-cache"
SCHEMA = "uscode-autoformal-output-index/v1"
MAX_BYTES = 64 * 1024 * 1024
REVISION = re.compile(r"[0-9a-f]{40}\Z")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _importer():
    spec = importlib.util.spec_from_file_location(
        "_output_index_exchange_reader", ROOT / "scripts/ops/legal_ir/import_span_cache_exchange.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _field_json(row, key, fallback):
    value = row.get(key)
    return json.loads(value) if isinstance(value, str) and value else fallback


def _rules(compiler, depth=0):
    """Expose retained component rules without claiming missing ones were recovered."""
    if depth > 32:
        raise ValueError("compiler component nesting exceeds bound")
    if not isinstance(compiler, Mapping):
        return []
    if isinstance(compiler.get("rules"), list):
        return compiler["rules"]
    for key in ("components", "parts", "component_results"):
        if isinstance(compiler.get(key), list):
            return [rule for part in compiler[key] for rule in _rules(part, depth + 1)]
    return [compiler["rule"]] if isinstance(compiler.get("rule"), Mapping) else []


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _vector(decoder):
    value = _mapping(decoder).get("embedding")
    if value is None:
        return None
    if not isinstance(value, list) or any(_number(item) is None for item in value):
        raise ValueError("retained decoder embedding is not a finite numeric vector")
    return [float(item) for item in value]


def derive_rows(bundle, *, revision):
    """Accept a validated bundle; retain exact evidence and expose useful columns."""
    if not REVISION.fullmatch(revision):
        raise ValueError("index requires an immutable 40-character source revision")
    manifest = bundle["manifest"]
    goals = {}
    for goal in bundle["goal_rows"]:
        goals.setdefault(goal["census_sha256"], []).append({
            key: goal[key] for key in ("record_kind", "task_id", "packet_sha256", "task_sha256")
        })
    for row in bundle["census_rows"]:
        original = json.loads(row["input_json"])
        ae = _mapping(original.get("autoencoder_observation"))
        compiler = _mapping(original.get("compiler_result") or ae.get("compiler"))
        raw = _field_json(row, "autoencoder_raw_decoder_json", ae.get("raw_decoder"))
        projected = _field_json(row, "autoencoder_safety_projected_decoder_json", ae.get("safety_projected_decoder"))
        rules = _field_json(row, "compiler_rules_json", _rules(compiler))
        target = _field_json(row, "logic_target_observation_json", original.get("logic_target_observation", ae.get("logic_target_observation")))
        bridge_names = _field_json(row, "bridge_names_json", _mapping(original.get("batch_observation")).get("bridges", {}).get("evaluation_invoked", []))
        evidence = {
            "schema_version": SCHEMA,
            "repository_id": manifest["repository_id"],
            "source_revision": revision,
            "source_manifest_path": manifest["path_in_repo"],
            "source_manifest_sha256": bundle["manifest_sha256"],
            "source_census_path": manifest["census"]["path_in_repo"],
            "source_census_sha256": manifest["census"]["sha256"],
            "source_goals_path": manifest["goals"]["path_in_repo"],
            "source_goals_sha256": manifest["goals"]["sha256"],
            "source_census_schema": row["schema_version"],
            "source_span_id": row["source_span_id"],
            "legal_id": row["legal_id"],
            "source_text": row["source_text"],
            "source_text_sha256": row["source_text_sha256"],
            "census_sha256": row["census_sha256"],
            "code_identity": row["code_identity"],
            "model_identity": row["model_identity"],
            "metric_scope": row["metric_scope"],
            "autoencoder_output_kind": row.get("autoencoder_output_kind") or ("legacy_vector_diagnostic" if raw else "retained_text" if row["autoencoder_text"] else "unavailable"),
            "autoencoder_output_status": row.get("autoencoder_output_status") or str(ae.get("status") or "not_recorded"),
            "autoencoder_text": row["autoencoder_text"],
            "autoencoder_compiled": row["autoencoder_compiled"],
            "autoencoder_raw_embedding": _vector(raw),
            "autoencoder_raw_cosine_similarity": _number(_mapping(raw).get("cosine_similarity")),
            "autoencoder_raw_reconstruction_loss": _number(_mapping(raw).get("reconstruction_loss")),
            "autoencoder_safety_projected_embedding": _vector(projected),
            "autoencoder_safety_projected_decoder_json": _json(projected),
            "embedding_representation_json": _json(_field_json(row, "embedding_representation_json", ae.get("embedding_representation"))),
            "compiler_status": row.get("compiler_status") or str(compiler.get("compiler_status") or compiler.get("status") or "not_recorded"),
            "compiler_reason": row.get("compiler_reason") or str(compiler.get("reason") or compiler.get("error_code") or ""),
            "compiler_rule_count": len(rules),
            "compiler_rules_json": _json(rules),
            "compiler_result_json": _json(compiler),
            "compiler_decompiled": row["compiler_decompiled"],
            "logic_target_observation_json": _json(target),
            "logic_target_availability": "retained" if target else "not_recorded_in_source",
            "bridge_names_json": _json(bridge_names),
            "goal_references_json": _json(sorted(goals.get(row["census_sha256"], []), key=lambda value: value["task_id"])),
            "input_json": row["input_json"],
            "comparison_provenance_json": row["comparison_provenance_json"],
            "admitted": False, "formalized": False, "enqueued": False,
            "inference_executed": False, "training_executed": False,
        }
        evidence["output_sha256"] = _sha(_json(evidence).encode())
        yield evidence


def _schema(rows):
    import pyarrow as pa

    vectors = {"autoencoder_raw_embedding", "autoencoder_safety_projected_embedding"}
    floats = {"autoencoder_raw_cosine_similarity", "autoencoder_raw_reconstruction_loss"}
    bools = {"admitted", "formalized", "enqueued", "inference_executed", "training_executed"}
    return pa.schema([
        (key, pa.list_(pa.float64()) if key in vectors else pa.float64() if key in floats
         else pa.bool_() if key in bools else pa.int64() if key == "compiler_rule_count" else pa.string())
        for key in rows[0]
    ])


def _remote_descriptor(path, raw):
    return {"path_in_repo": path, "bytes": len(raw), "sha256": _sha(raw),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def build_index(manifest_path, output_directory, *, revision, agent_id="retained-output-index",
                max_bytes=MAX_BYTES, max_rows=1000, max_decoded_bytes=MAX_BYTES,
                remaining_output_bytes=MAX_BYTES):
    """Validate before deriving; memory is bounded to one exchange, never the corpus."""
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import (
        load_exchange_bundle, _read_regular_snapshot, _immutable_write,
    )
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", agent_id):
        raise ValueError("agent_id must contain 1..48 letters, digits, hyphens or underscores")
    bundle = load_exchange_bundle(manifest_path, max_bytes=max_bytes, max_rows=max_rows,
                                  max_decoded_bytes=max_decoded_bytes)
    if bundle["manifest"]["repository_id"] != REPOSITORY:
        raise ValueError("output index requires the US Code span-cache repository")
    rows = list(derive_rows(bundle, revision=revision))
    if not rows:
        raise ValueError("cannot index an empty census")
    output_size = sum(len(_json(row).encode()) for row in rows)
    if output_size > max_decoded_bytes:
        raise ValueError("derived row expansion exceeds decoded byte bound")
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows, schema=_schema(rows)), sink, compression="zstd")
    raw = sink.getvalue().to_pybytes()
    filename = "outputs-" + _sha(raw) + ".parquet"
    prefix = "autoformal/uscode/outputs/" + agent_id + "/"
    sources = []
    for kind, path in (("manifest", Path(manifest_path)), ("census", Path(bundle["census_path"])), ("goals", Path(bundle["goals_path"]))):
        source_raw = _read_regular_snapshot(path, max_bytes=max_bytes)
        expected = bundle["manifest_sha256"] if kind == "manifest" else bundle["manifest"][kind]["sha256"]
        if _sha(source_raw) != expected:
            raise ValueError("source artifact changed during indexing")
        remote = bundle["manifest"]["path_in_repo"] if kind == "manifest" else bundle["manifest"][kind]["path_in_repo"]
        sources.append({"kind": kind, **_remote_descriptor(remote, source_raw)})
    descriptor = {"schema": SCHEMA, "repository_id": REPOSITORY,
                  "source_revision": revision, "source_files": sources,
                  "output": {**_remote_descriptor(prefix + filename, raw), "row_count": len(rows)},
                  "inference_executed": False, "training_executed": False,
                  "admitted": False, "formalized": False, "enqueued": False}
    manifest_raw = _json(descriptor).encode()
    manifest_name = "outputs-" + _sha(manifest_raw) + ".manifest.json"
    if len(raw) + len(manifest_raw) > remaining_output_bytes:
        raise ValueError("derived artifacts exceed cumulative output byte bound")
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    _immutable_write(output_directory / filename, raw)
    _immutable_write(output_directory / manifest_name, manifest_raw)
    return {"manifest": descriptor, "manifest_path": str(output_directory / manifest_name),
            "manifest_path_in_repo": prefix + manifest_name,
            "output_path": str(output_directory / filename),
            "output_bytes": len(raw) + len(manifest_raw), "row_count": len(rows)}


def _value(value, key):
    return value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)


def _verify_remote(api, descriptors, revision, *, require_all):
    expected = {item["path_in_repo"]: item for item in descriptors}
    found = set()
    for remote in api.get_paths_info(repo_id=REPOSITORY, paths=list(expected), repo_type="dataset", revision=revision):
        path = _value(remote, "path") or _value(remote, "rfilename")
        if path not in expected or path in found:
            raise ValueError("unexpected or duplicate remote output artifact")
        wanted = expected[path]
        lfs_sha = _value(_value(remote, "lfs"), "sha256")
        if (_value(remote, "size") != wanted["bytes"] or
                (lfs_sha or _value(remote, "blob_id")) != wanted["sha256" if lfs_sha else "git_blob_sha1"]):
            raise ValueError("remote immutable artifact digest or size differs")
        found.add(path)
    if require_all and found != set(expected):
        raise ValueError("pinned source commit is missing required evidence")
    return found


def publish_index(index, *, api=None):
    """Verify immutable source closure, then append using a Hub parent-commit CAS."""
    from huggingface_hub import HfApi, CommitOperationAdd
    from ipfs_datasets_py.logic.autoformal.span_cache_exchange import _read_regular_snapshot

    api = api or HfApi()
    descriptor = index["manifest"]
    _verify_remote(api, descriptor["source_files"], descriptor["source_revision"], require_all=True)
    output_raw = _read_regular_snapshot(index["output_path"], max_bytes=MAX_BYTES)
    manifest_raw = _read_regular_snapshot(index["manifest_path"], max_bytes=MAX_BYTES)
    if manifest_raw != _json(descriptor).encode() or _remote_descriptor(descriptor["output"]["path_in_repo"], output_raw) != {key: descriptor["output"][key] for key in ("path_in_repo", "bytes", "sha256", "git_blob_sha1")}:
        raise ValueError("index changed before upload")
    parent = str(_value(api.repo_info(repo_id=REPOSITORY, repo_type="dataset"), "sha"))
    if not REVISION.fullmatch(parent):
        raise ValueError("Hub returned no immutable parent commit")
    payloads = {descriptor["output"]["path_in_repo"]: output_raw, index["manifest_path_in_repo"]: manifest_raw}
    present = _verify_remote(api, [_remote_descriptor(path, raw) for path, raw in payloads.items()], parent, require_all=False)
    operations = [CommitOperationAdd(path_in_repo=path, path_or_fileobj=raw) for path, raw in payloads.items() if path not in present]
    commit = parent
    if operations:
        committed = api.create_commit(repo_id=REPOSITORY, repo_type="dataset", parent_commit=parent,
                                      operations=operations, commit_message="Append queryable retained autoencoder and compiler outputs")
        commit = str(_value(committed, "oid"))
    if not REVISION.fullmatch(commit):
        raise ValueError("Hub returned no immutable commit")
    _verify_remote(api, [_remote_descriptor(path, raw) for path, raw in payloads.items()], commit, require_all=True)
    return {"uploaded": True, "commit_sha": commit, "parent_commit": parent,
            "admitted": False, "formalized": False, "enqueued": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--manifest", type=Path, action="append")
    inputs.add_argument("--manifest-in-repo", action="append")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--agent-id", default="retained-output-index")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--max-decoded-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--max-output-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args(argv)
    entries = args.manifest or args.manifest_in_repo
    if not REVISION.fullmatch(args.revision) or not 1 <= len(entries) <= 64:
        parser.error("require a full commit revision and 1..64 explicit manifests")
    if any(value < 1 or value > MAX_BYTES for value in (args.max_bytes, args.max_decoded_bytes, args.max_output_bytes)) or not 1 <= args.max_rows <= 10000:
        parser.error("byte bounds must be 1..64 MiB and max rows 1..10000")
    importer = _importer()
    importer._pin_logic()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    used = 0
    for entry in entries:
        with tempfile.TemporaryDirectory(prefix=".index-download-", dir=args.output_dir) as temporary:
            path = Path(entry) if args.manifest else importer.download_bundle(
                repository_id=REPOSITORY, revision=args.revision, manifest_in_repo=entry,
                staging_directory=Path(temporary), max_bytes=args.max_bytes)
            result = build_index(path, args.output_dir, revision=args.revision, agent_id=args.agent_id,
                                 max_bytes=args.max_bytes, max_rows=args.max_rows,
                                 max_decoded_bytes=args.max_decoded_bytes,
                                 remaining_output_bytes=args.max_output_bytes - used)
            used += result["output_bytes"]
            if args.upload:
                result["publication"] = publish_index(result)
            print(_json(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
