#!/usr/bin/env python3
"""Exercise durable v5 split bindings on previously audited local US Code data.

This is owner preflight and independent-process input verification only. The
published vectors remain diagnostic and training-ineligible. No model is loaded,
no training or bridge evaluation runs, and no head or publication is created.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
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


def _checked_json(reference):
    path = Path(reference["path"])
    if path.stat().st_size != reference["bytes"] or _sha(path) != reference["sha256"]:
        raise ValueError("prior audited artifact changed")
    return json.loads(path.read_bytes())


def _verify_process(payload, connection):
    try:
        sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
            TrainingJobSpec, verify_corpus_job_inputs,
        )
        require_workspace_logic_tree()
        started = time.perf_counter()
        spec = TrainingJobSpec.from_dict(payload)
        summary = verify_corpus_job_inputs(spec)
        connection.send({"passed": True, "pid": os.getpid(), "run_id": spec.run_id,
                         "elapsed_seconds": time.perf_counter() - started, "verification": summary,
                         "training_performed": False, "control_database_opened": False})
    except Exception as exc:
        connection.send({"passed": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
    finally:
        connection.close()


def _archived_identities():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
    unique, schemas = {}, {}
    for path in sorted(PRIOR.parent.glob("*.json")):
        pending = [json.loads(path.read_bytes())]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, dict):
                if "job_spec" in value and "job_spec_canonical_sha256" in value:
                    raw = value["job_spec"]
                    if raw.get("schema_version") == "autoencoder-training-job-v5":
                        continue
                    spec = TrainingJobSpec.from_dict(raw)
                    if spec.canonical_sha256 != value["job_spec_canonical_sha256"] or spec.to_dict() != raw:
                        raise ValueError("archived job identity changed")
                    unique[spec.canonical_sha256] = {"schema": spec.schema_version, "receipt": str(path.relative_to(ROOT))}
                pending.extend(value.values())
    for value in unique.values():
        schemas[value["schema"]] = schemas.get(value["schema"], 0) + 1
    if set(schemas) != {f"autoencoder-training-job-v{i}" for i in range(1, 5)}:
        raise ValueError("archived v1-v4 coverage missing")
    return {"unique_count": len(unique), "schema_counts": schemas, "identities": unique, "unchanged": True}


def _run(args, receipt):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        TrainingJobSpec, verify_corpus_job_inputs,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import _validate_runs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        load_corpus_manifest, build_corpus_manifest,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import (
        load_corpus_index, build_corpus_index, SplitPolicy,
    )

    if _sha(PRIOR) != PRIOR_SHA or _sha(PINNED) != PINNED_SHA or PINNED.stat().st_size != 25895338:
        raise ValueError("pinned prior receipt or checkpoint changed")
    prior = json.loads(PRIOR.read_bytes())
    if not prior["passed"] or prior["training_eligible_count"] != 0:
        raise ValueError("unexpected prior input qualification")
    index_ref, batch_ref = prior["index_artifact"], prior["batch_artifact"]
    index = load_corpus_index(index_ref["path"], expected_sha256=index_ref["sha256"],
                              expected_size_bytes=index_ref["bytes"])
    batch = load_corpus_manifest(batch_ref["path"], expected_sha256=batch_ref["sha256"],
                                 expected_size_bytes=batch_ref["bytes"])
    index.verify_batch(batch)
    selection = Path(index_ref["path"]).parent / "selection.json"
    if _sha(selection) != index.scope.selection_sha256:
        raise ValueError("selected-source receipt changed")
    imported = _checked_json(prior["import_artifact"])
    source_paths = {}
    for ordinal, row in enumerate(imported["rows"]):
        path = Path(prior["import_artifact"]["path"]).parent / f"source-{ordinal:06d}.txt"
        reference = row["extracted_text"]
        if _sha(path) != reference["sha256"] or path.stat().st_size != reference["bytes"]:
            raise ValueError("extracted source changed")
        source_paths[reference["sha256"]] = path
    batch.validate_sources(lambda ref: source_paths[ref["sha256"]])
    split = batch.to_dict()["split"]
    train, validation = split["training_record_ids"], split["validation_record_ids"]
    if len(train) != 54 or len(validation) != 3 or index.partition_counts != {
            "train": 54, "validation": 3, "canary": 1, "holdout": 6}:
        raise ValueError("prior indexed selection membership changed")
    records = {row.record_id: row for row in batch.records}
    database, artifacts = args.directory / "control.duckdb", args.directory / "artifacts"
    variant_id = "indexed-uscode-diagnostic-input-audit"
    variant = {"source_language": "en", "target_formal_language": "typed_deontic_ir",
               "jurisdiction": "us", "model_variant": "indexed-input-audit"}
    specs, rejection_results = [], {}
    with AutoencoderRegistry(database, artifacts) as registry:
        base = registry.stage_artifact(PINNED, PINNED_SHA)
        staged_index = registry.stage_artifact(index_ref["path"], index_ref["sha256"])
        binding = {"selection_sha256": index.scope.selection_sha256, "artifact": staged_index}
        registry.register_variant("variant", variant_id, {**variant, "corpus_index_binding": binding})
        version = registry.register_version("base", variant_id, base)["version_id"]
        staged_sources = {ref["sha256"]: registry.stage_artifact(source_paths[ref["sha256"]], ref["sha256"])
                          for ref in batch.source_refs}

        def job(name, training, validating, **overrides):
            membership = list(dict.fromkeys([*training, *validating]))
            manifest = build_corpus_manifest([records[key] for key in membership],
                training_record_ids=training, validation_record_ids=validating, mode="diagnostic")
            saved = manifest.save(args.directory / f"{name}.batch.json", resolver=lambda ref: source_paths[ref["sha256"]])
            staged = registry.stage_artifact(saved["path"], saved["sha256"])
            payload = {"schema_version": "autoencoder-training-job-v5", "job_id": name, "run_id": name,
                "base_version_id": version, "base_checkpoint": {**base, "path": str(registry.artifact_path(base))},
                "output_directory": str(args.directory / f"attempt-{name}"), "code_identity": "input-audit-no-training",
                "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
                "samples": [asdict(records[key].sample) for key in training],
                "validation_samples": [asdict(records[key].sample) for key in validating], "variant": variant,
                "corpus_manifest_artifact": {**staged, "path": str(registry.artifact_path(staged))},
                "corpus_source_artifacts": [{**staged_sources[ref["sha256"]],
                    "path": str(registry.artifact_path(staged_sources[ref["sha256"]]))} for ref in manifest.source_refs],
                "corpus_index_artifact": {**staged_index, "path": str(registry.artifact_path(staged_index))},
                "corpus_selection_sha256": index.scope.selection_sha256}
            payload.update(overrides)
            spec = TrainingJobSpec.from_dict(payload)
            path = args.directory / f"{name}.job.json"
            _write(path, spec.to_dict())
            registry.create_run(f"create-{name}", name, variant_id, version,
                {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(path)})
            return spec

        specs = [job("batch-0", train[:27], validation), job("batch-1", train[27:], validation)]
        started = time.perf_counter()
        owner_checks = _validate_runs(registry, specs)
        receipt["owner_preflight_seconds"] = time.perf_counter() - started
        receipt["owner_checks"] = owner_checks

        replacement = build_corpus_index(list(batch.records), scope=index.scope,
                                         policy=SplitPolicy(seed="intentional-conflicting-index"))
        replacement_path = args.directory / "conflicting-index.json"
        replacement.save(replacement_path)
        replacement_ref = registry.stage_artifact(replacement_path, replacement.sha256)
        invalid = {
            "selection_mismatch": job("bad-selection", train[:27], validation, corpus_selection_sha256="0" * 64),
            "index_substitution": job("bad-index", train[:27], validation,
                corpus_index_artifact={**replacement_ref, "path": str(registry.artifact_path(replacement_ref))}),
            "unstaged_index_path": job("bad-path", train[:27], validation,
                corpus_index_artifact={**staged_index, "path": index_ref["path"]}),
            "legacy_downgrade": job("bad-downgrade", train[:27], validation,
                schema_version="autoencoder-training-job-v4", corpus_index_artifact=None, corpus_selection_sha256=""),
            "validation_in_training": job("bad-training", [*train[:27], validation[0]], validation),
            "training_in_validation": job("bad-validation", train[:27], [*validation, train[0]]),
        }
        for name, spec in invalid.items():
            try:
                _validate_runs(registry, [spec])
            except ValueError as exc:
                rejection_results[name] = {"rejected": True, "error": str(exc),
                    "run_still_queued": registry.get_run(spec.run_id)["status"] == "queued",
                    "output_absent": not Path(spec.output_directory).exists()}
            else:
                raise ValueError(f"owner accepted {name}")
        for name in ("selection_mismatch", "validation_in_training", "training_in_validation"):
            try:
                verify_corpus_job_inputs(invalid[name])
            except ValueError:
                rejection_results[name]["worker_independently_rejected"] = True
            else:
                raise ValueError(f"worker accepted {name}")
        receipt["rejections"] = rejection_results

        context = multiprocessing.get_context("spawn")
        children = []
        started = time.perf_counter()
        try:
            for spec in specs:
                parent, child = context.Pipe(duplex=False)
                process = context.Process(target=_verify_process, args=(spec.to_dict(), child))
                process.start()
                child.close()
                children.append((process, parent))
            verified = []
            for process, channel in children:
                if not channel.poll(60):
                    raise RuntimeError("spawned input verifier exceeded 60 seconds")
                result = channel.recv()
                process.join(5)
                if process.exitcode != 0 or not result["passed"]:
                    raise RuntimeError(f"spawned verifier failed: {result}")
                if result["verification"] != owner_checks[result["run_id"]]:
                    raise ValueError("owner and worker input verification differ")
                verified.append(result)
        finally:
            for process, channel in children:
                channel.close()
                if process.is_alive():
                    process.terminate()
                process.join(5)
        receipt["parallel_verification_seconds"] = time.perf_counter() - started
        receipt["worker_verifications"] = verified
        receipt["two_independent_verifier_processes"] = len({row["pid"] for row in verified}) == 2
        receipt["no_worker_output_directories"] = all(not Path(spec.output_directory).exists() for spec in specs)

    with AutoencoderRegistry(database, artifacts) as registry:
        receipt["binding_survives_restart"] = registry.get_variant(variant_id)["manifest"]["corpus_index_binding"] == binding
        receipt["preflight_identical_after_restart"] = _validate_runs(registry, specs) == owner_checks
        try:
            registry.register_variant("replace-binding", variant_id,
                {**variant, "corpus_index_binding": {**binding, "artifact": replacement_ref}})
        except ValueError:
            receipt["variant_rebinding_rejected"] = True
        else:
            raise ValueError("registered variant allowed index replacement")
        try:
            _validate_runs(registry, [invalid["index_substitution"]])
        except ValueError:
            receipt["index_substitution_rejected_after_restart"] = True
        else:
            raise ValueError("restarted owner accepted index substitution")
        receipt["runs_remain_queued_without_leases"] = all(
            registry.get_run(spec.run_id)["status"] == "queued" and registry.get_run(spec.run_id)["lease"] is None
            for spec in [*specs, *invalid.values()])
    receipt.update(index_artifact=index_ref, index_partition_counts=index.partition_counts,
        indexed_record_count=64, distinct_training_records=54, validation_records=3,
        worker_count=2, samples_per_worker=27, validation_samples_per_worker=3,
        training_eligible_count=0, archived_job_compatibility=_archived_identities(),
        prior_receipt={"path": str(PRIOR), "sha256": PRIOR_SHA},
        retained_artifact_bytes=sum(path.stat().st_size for path in args.directory.rglob("*") if path.is_file()))


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
        "autoencoder_training_worker.py", "autoencoder_training_coordinator.py", "autoencoder_corpus_manifest.py",
        "autoencoder_corpus_index.py")]
    paths.append(str(ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_registry.py"))
    receipt = {"schema": "indexed-training-input-audit-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "training_performed": False, "model_loaded": False, "bridge_evaluation_performed": False,
        "publication_performed": False, "promotion_performed": False, "weights_downloaded": False,
        "admitted": False, "formalized": False, "heldout_canary_qualified": False,
        "timing_scope": "owner preflight and spawned source/index verification only; no training or bridge evaluation; OS cache uncontrolled",
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in paths}}
    started = time.perf_counter()
    try:
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / name) == digest for name, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
        receipt["passed"] = all(receipt[key] for key in (
            "binding_survives_restart", "preflight_identical_after_restart", "variant_rebinding_rejected",
            "index_substitution_rejected_after_restart", "runs_remain_queued_without_leases",
            "two_independent_verifier_processes", "no_worker_output_directories", "source_unchanged",
            "pinned_checkpoint_unchanged")) and all(
                item["rejected"] and item["run_still_queued"] and item["output_absent"]
                for item in receipt["rejections"].values())
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "training_performed": False}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
