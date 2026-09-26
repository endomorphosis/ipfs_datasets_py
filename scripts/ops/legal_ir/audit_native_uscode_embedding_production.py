#!/usr/bin/env python3
"""Produce bounded, source-bound local embeddings and qualify v6 job inputs.

This dedicated audit process denies network syscalls before loading the cached
model. It never trains the autoencoder, publishes data or admits Lean. Oversized
whole-row inputs remain explicit exclusions; no context increase or truncation.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
from dataclasses import asdict
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
REVISION = "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
MANIFEST_SHA = "0c6c05582fda19f36c75b166c5c1afecdab156241ce73728f564802b52eacac6"
PRIOR = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/uscode-source-index-20260925.json"
PRIOR_SHA = "15e462331c69286de4918d5a8ef0da11bbd0dbe65b2a7646b23527b2376ef9d0"
PINNED = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _deny_network():
    """Install an irreversible filter only in this dedicated audit executable."""
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise RuntimeError("native audit requires libseccomp network denial")
    lib = ctypes.CDLL(library, use_errno=True)
    lib.seccomp_init.argtypes, lib.seccomp_init.restype = [ctypes.c_uint32], ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes, lib.seccomp_syscall_resolve_name.restype = [ctypes.c_char_p], ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes, lib.seccomp_load.restype = [ctypes.c_void_p], ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("seccomp context creation failed")
    names = ("socket", "connect", "sendto", "sendmsg", "sendmmsg")
    try:
        for name in names:
            number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0 or lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError(f"cannot deny {name}")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("seccomp load failed")
    finally:
        lib.seccomp_release(context)
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        return {"mechanism": "linux_seccomp", "denied_syscalls": list(names), "socket_denial_verified": True}
    else:
        connection.close()
        raise RuntimeError("network denial was ineffective")


def _run(args, receipt):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_import import (
        load_uscode_release, read_corpus_shard,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        CheckpointArtifact, TrainingJobSpec, verify_corpus_job_inputs,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        SourceArtifact, SourceSpan, build_corpus_manifest,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import (
        IndexScope, build_corpus_index, load_corpus_index,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import (
        EmbeddingInput, load_embedding_production_receipt,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime import produce_native_embedding_receipt
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import _validate_runs

    if _sha(PRIOR) != PRIOR_SHA or _sha(PINNED) != PINNED_SHA:
        raise ValueError("pinned prior input audit or checkpoint changed")
    prior = json.loads(PRIOR.read_bytes())
    source_root = ROOT / "workspace/test-logs/federal-corpus-inputs" / REVISION
    manifest_path, corpus_path = source_root / "manifest.json", source_root / "data/corpus/part-000015.parquet"
    references = {_sha(path): path for path in (manifest_path, corpus_path)}

    def release_resolver(ref):
        path = references[ref["sha256"]]
        if path.stat().st_size != ref["bytes"]:
            raise ValueError("release artifact size changed")
        return path

    release = load_uscode_release(CheckpointArtifact(str(manifest_path), MANIFEST_SHA, manifest_path.stat().st_size),
                                 repo_id="justicedao/ipfs_uscode", revision=REVISION)
    corpus = read_corpus_shard(release, "data/corpus/part-000015.parquet", resolver=release_resolver)
    if not corpus.complete or len(corpus.records) != 1491:
        raise ValueError("source shard membership changed")
    imported_ref = prior["import_artifact"]
    if _sha(imported_ref["path"]) != imported_ref["sha256"]:
        raise ValueError("prior exact text import receipt changed")
    imported = json.loads(Path(imported_ref["path"]).read_bytes())
    inputs, source_paths = [], {}
    for ordinal, row in enumerate(corpus.records[:64]):
        old = imported["rows"][ordinal]
        if (old["entry_cid"], old["record_sha256"], old["row_index"]) != (row.entry_cid, row.record_sha256, row.row_index):
            raise ValueError("selected source row differs from prior physical membership")
        path = Path(imported_ref["path"]).parent / f"source-{ordinal:06d}.txt"
        source_ref = old["extracted_text"]
        if _sha(path) != source_ref["sha256"] or path.read_bytes() != row.text.encode("utf-8"):
            raise ValueError("extracted source differs from published exact text")
        source_paths[source_ref["sha256"]] = path
        inputs.append(EmbeddingInput(
            source=SourceSpan(SourceArtifact(**source_ref), "us_code", row.release_id, row.document_id, "en",
                              row.canonical_citation, 0, source_ref["bytes"], "identity"),
            title=row.title, section=row.section, text=row.text, citation=row.canonical_citation))

    def resolver(ref):
        path = source_paths[ref["sha256"]]
        if path.stat().st_size != ref["bytes"]:
            raise ValueError("source artifact size changed")
        return path

    started = time.perf_counter()
    production = produce_native_embedding_receipt(inputs, resolver=resolver, batch_size=16)
    receipt["production_seconds"] = time.perf_counter() - started
    production_ref = production.save(args.directory / "embedding-production.json", resolver=resolver)
    receipt["embedding_production_artifact"] = production_ref
    receipt["production_status_counts"] = production.status_counts
    generated = production.to_corpus_records(resolver=resolver)
    loaded = load_embedding_production_receipt(production_ref["path"], expected_sha256=production_ref["sha256"],
                                              expected_size_bytes=production_ref["bytes"])
    receipt["reopened_production_verification"] = loaded.verify_records(generated, resolver=resolver)
    if [row.to_dict() for row in loaded.to_corpus_records(resolver=resolver)] != [row.to_dict() for row in generated]:
        raise ValueError("production reopen changed exact vectors")
    receipt["production_reopen_identical"] = True

    old_ref = prior["index_artifact"]
    old_index = load_corpus_index(old_ref["path"], expected_sha256=old_ref["sha256"], expected_size_bytes=old_ref["bytes"])
    selection_path = args.directory / "selection.json"
    _write(selection_path, {"schema": "native-embedding-source-selection-v1", "parent_selection_sha256": old_index.scope.selection_sha256,
        "embedding_production_sha256": production.sha256, "record_ids": [row.record_id for row in generated],
        "input_count": len(inputs), "statuses": production.status_counts,
        "selection_rule": "same first 64 published rows; exact tokenizer length eligibility; no model evaluation or split reseeding"})
    index = build_corpus_index(generated, scope=IndexScope(_sha(selection_path), (MANIFEST_SHA,)), policy=old_index.policy)
    new_index_ref = index.save(args.directory / "corpus-index.json")
    old_source_ids = {json.dumps(row["source"], sort_keys=True): row["record_id"] for row in old_index.to_dict()["records"]}
    if any(index.assignments[row.record_id] != old_index.assignments[old_source_ids[json.dumps(asdict(row.source), sort_keys=True)]]
           for row in generated):
        raise ValueError("unchanged source groups moved between frozen partitions")
    receipt.update(input_count=len(inputs), generated_record_count=len(generated), index_artifact=new_index_ref,
                   index_partition_counts=index.partition_counts, source_group_assignments_preserved=True)
    training, validation = index.record_ids_for("train"), index.record_ids_for("validation")
    by_id = {row.record_id: row for row in generated}
    batch = build_corpus_manifest([by_id[key] for key in (*training, *validation)],
        training_record_ids=training, validation_record_ids=validation, mode="corpus")
    batch_ref = batch.save(args.directory / "corpus-batch.json", resolver=resolver)
    index.verify_batch(batch)
    receipt["batch_artifact"] = batch_ref

    database, artifacts = args.directory / "control.duckdb", args.directory / "artifacts"
    variant = {"source_language": "en", "target_formal_language": "typed_deontic_ir", "jurisdiction": "us",
               "model_variant": "native-embedding-input-audit"}
    with AutoencoderRegistry(database, artifacts) as registry:
        base = registry.stage_artifact(PINNED, PINNED_SHA)
        staged_index = registry.stage_artifact(new_index_ref["path"], new_index_ref["sha256"])
        staged_production = registry.stage_artifact(production_ref["path"], production_ref["sha256"])
        staged_batch = registry.stage_artifact(batch_ref["path"], batch_ref["sha256"])
        variant_manifest = {**variant,
            "corpus_index_binding": {"selection_sha256": index.scope.selection_sha256, "artifact": staged_index},
            "embedding_production_binding": {"artifact": staged_production}}
        registry.register_variant("variant", "native-embedding-input-audit", variant_manifest)
        version = registry.register_version("base", "native-embedding-input-audit", base)["version_id"]
        staged_sources = [registry.stage_artifact(resolver(ref), ref["sha256"]) for ref in batch.source_refs]
        spec = TrainingJobSpec.from_dict({"schema_version": "autoencoder-training-job-v6",
            "job_id": "native-inputs", "run_id": "native-inputs", "base_version_id": version,
            "base_checkpoint": {**base, "path": str(registry.artifact_path(base))},
            "output_directory": str(args.directory / "unused-training-attempt"), "code_identity": "native-production-preflight-only",
            "variant": variant, "dataset_snapshot_id": batch.dataset_snapshot_id, "split_snapshot_id": batch.split_snapshot_id,
            "samples": [asdict(by_id[key].sample) for key in training],
            "validation_samples": [asdict(by_id[key].sample) for key in validation],
            "corpus_manifest_artifact": {**staged_batch, "path": str(registry.artifact_path(staged_batch))},
            "corpus_source_artifacts": [{**ref, "path": str(registry.artifact_path(ref))} for ref in staged_sources],
            "corpus_index_artifact": {**staged_index, "path": str(registry.artifact_path(staged_index))},
            "corpus_selection_sha256": index.scope.selection_sha256,
            "embedding_production_artifact": {**staged_production, "path": str(registry.artifact_path(staged_production))}})
        job_path = args.directory / "job.json"
        _write(job_path, spec.to_dict())
        registry.create_run("create", spec.run_id, "native-embedding-input-audit", version,
            {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(job_path)})
        receipt["owner_preflight"] = _validate_runs(registry, [spec])[spec.run_id]
        receipt["worker_preflight"] = verify_corpus_job_inputs(spec)
        if receipt["owner_preflight"] != receipt["worker_preflight"]:
            raise ValueError("owner and worker producer verification differ")
    with AutoencoderRegistry(database, artifacts) as registry:
        receipt["preflight_identical_after_restart"] = _validate_runs(registry, [spec])[spec.run_id] == receipt["owner_preflight"]
        receipt["variant_binding_survives_restart"] = registry.get_variant("native-embedding-input-audit")["manifest"] == variant_manifest
        receipt["run_unleased_without_training"] = registry.get_run(spec.run_id)["status"] == "queued" and registry.get_run(spec.run_id)["lease"] is None
    receipt["no_training_output"] = not Path(spec.output_directory).exists()
    receipt["retained_artifact_bytes"] = sum(path.stat().st_size for path in args.directory.rglob("*") if path.is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists():
        parser.error("use new directory and receipt paths")
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    paths = list(require_workspace_logic_tree().values()) + [str(Path(__file__).resolve())]
    paths += [str(ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / name) for name in (
        "autoencoder_embedding_production.py", "autoencoder_embedding_runtime.py", "autoencoder_training_worker.py",
        "autoencoder_training_coordinator.py", "autoencoder_corpus_manifest.py", "autoencoder_corpus_index.py",
        "autoencoder_uscode_import.py")]
    paths.append(str(ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_registry.py"))
    receipt = {"schema": "native-uscode-embedding-production-audit-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "autoencoder_training_performed": False, "bridge_evaluation_performed": False,
        "model_weights_downloaded": False, "publication_performed": False, "promotion_performed": False,
        "admitted": False, "formalized": False, "heldout_canary_qualified": False,
        "timing_scope": "cached-model input embedding production and owner/worker input verification; no legal-IR speed measurement",
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in paths}}
    started = time.perf_counter()
    try:
        receipt["network_enforcement"] = _deny_network()
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / name) == digest for name, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
        receipt["passed"] = all(receipt[key] for key in (
            "production_reopen_identical", "source_group_assignments_preserved", "preflight_identical_after_restart",
            "variant_binding_survives_restart", "run_unleased_without_training", "no_training_output",
            "source_unchanged", "pinned_checkpoint_unchanged"))
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "autoencoder_training_performed": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
