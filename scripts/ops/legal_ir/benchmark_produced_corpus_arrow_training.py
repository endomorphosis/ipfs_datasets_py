#!/usr/bin/env python3
"""Qualify real source-bound corpus jobs, shared targets, sparse updates and Arrow.

Uses a fixed prefix of a previously frozen training split and all three of its
validation rows. No split reseeding, embedding production, model download,
promotion, publication, Constitution training or Lean admission occurs here.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

from benchmark_shared_autoencoder_training import ROOT, PINNED, PINNED_SHA, _sha, _write, _numbers, _prepare_arrow
from benchmark_sparse_checkpoint_training import _compare

PRIOR = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/native-embeddings-20260925-r2.json"
PRODUCTION_SHA = "0ec481a6f3a51041d72c95c3ee7f7971463404cba22ee48a3c6ed1d201c9e0fa"
INDEX_SHA = "f604e8fe35ed044dd88423839ca21c4045021f08aeb754fc0ec61a0adffd33cc"


def _prepare(training, validation, path):
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    return prepare_training_targets([SampleRecord.from_dict(row) for row in training], path,
        validation_records=[SampleRecord.from_dict(row) for row in validation], artifact_format="bundle")


def _run(args, receipt):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import load_corpus_manifest, build_corpus_manifest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import load_corpus_index
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import load_embedding_production_receipt
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_arrow_inputs import write_embedding_inputs_ipc
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import (
        registered_checkpoint_inputs, run_training_jobs,
    )
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry

    prior = json.loads(PRIOR.read_bytes())
    prior_dir = Path(prior["embedding_production_artifact"]["path"]).parent
    prior_job_path = prior_dir / "job.json"
    prior_job = TrainingJobSpec.from_dict(json.loads(prior_job_path.read_bytes()))
    if (prior_job.embedding_production_artifact.sha256 != PRODUCTION_SHA
            or prior_job.corpus_index_artifact.sha256 != INDEX_SHA
            or prior_job.base_checkpoint.sha256 != PINNED_SHA):
        raise ValueError("prior source/index/producer/checkpoint binding changed")
    verify_corpus_job_inputs(prior_job)
    receipt["parent_input_audit"] = {"path": str(PRIOR), "sha256": _sha(PRIOR)}
    receipt["parent_job"] = {"path": str(prior_job_path), "sha256": _sha(prior_job_path)}
    artifact = prior_job.corpus_manifest_artifact
    parent_batch = load_corpus_manifest(artifact.path, expected_sha256=artifact.sha256, expected_size_bytes=artifact.bytes)
    artifact = prior_job.corpus_index_artifact
    index = load_corpus_index(artifact.path, expected_sha256=artifact.sha256, expected_size_bytes=artifact.bytes)
    artifact = prior_job.embedding_production_artifact
    production = load_embedding_production_receipt(artifact.path, expected_sha256=artifact.sha256, expected_size_bytes=artifact.bytes)
    sources = {ref.sha256: ref for ref in prior_job.corpus_source_artifacts}

    def resolver(ref):
        bound = sources[ref["sha256"]]
        if bound.bytes != ref["bytes"]:
            raise ValueError("source size differs from prior binding")
        return Path(bound.path)

    # Freeze this rule before any target generation or evaluation. A length or
    # semantic failure is evidence, not permission to select easier records.
    train_ids = index.record_ids_for("train")[:3]
    validation_ids = index.record_ids_for("validation")
    if len(train_ids) != 3 or len(validation_ids) != 3:
        raise ValueError("qualification requires the pinned 3+3 selection")
    by_id = {row.record_id: row for row in parent_batch.records}
    batch = build_corpus_manifest([by_id[key] for key in (*train_ids, *validation_ids)],
        training_record_ids=train_ids, validation_record_ids=validation_ids, mode="corpus")
    index.verify_batch(batch)
    receipt["selection"] = {"rule": "first three frozen training IDs; all three frozen validation IDs; no reseeding or post-evaluation substitution",
        "training_record_ids": list(train_ids), "validation_record_ids": list(validation_ids),
        "training_citations": [by_id[key].source.citation for key in train_ids],
        "validation_citations": [by_id[key].source.citation for key in validation_ids],
        "parent_index_sha256": INDEX_SHA, "producer_receipt_sha256": PRODUCTION_SHA}
    _write(args.directory / "selection.json", receipt["selection"])
    saved_batch = batch.save(args.directory / "batch.json", resolver=resolver)
    materialize_started = time.perf_counter()
    arrow = write_embedding_inputs_ipc(batch.records, args.directory / "embeddings.arrow", production=production, resolver=resolver)
    receipt["arrow_materialization"] = {"artifact": arrow, "elapsed_seconds": time.perf_counter() - materialize_started}
    training = [asdict(by_id[key].sample) for key in train_ids]
    validation = [asdict(by_id[key].sample) for key in validation_ids]
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
        prepared = executor.submit(_prepare, training, validation, str(args.directory / "targets.bundle")).result()
        feature_weights = executor.submit(_prepare_arrow, str(args.directory / "feature-weights.arrow")).result()
    receipt["target_preparation"] = prepared
    receipt["arrow_feature_weight_materialization"] = feature_weights
    _write(args.directory / "target-preparation.json", prepared)
    if prepared["sample_count"] != 6 or len(prepared["statuses"]) != 6 or set(prepared["statuses"].values()) != {"ready"}:
        raise ValueError("six complete ready targets required for equivalent reuse qualification; preserve dispositions")

    database, artifacts = args.directory / "control.duckdb", args.directory / "artifacts"
    preparation_seconds = {}
    variant_id = "native-corpus-arrow-benchmark"

    with AutoencoderRegistry(database, artifacts) as registry:
        base = registry.stage_artifact(PINNED, PINNED_SHA)
        staged_batch = registry.stage_artifact(saved_batch["path"], saved_batch["sha256"])
        staged_index = registry.stage_artifact(prior_job.corpus_index_artifact.path, INDEX_SHA)
        staged_production = registry.stage_artifact(prior_job.embedding_production_artifact.path, PRODUCTION_SHA)
        staged_arrow = registry.stage_artifact(arrow["path"], arrow["sha256"])
        staged_feature_weights = registry.stage_artifact(feature_weights["path"], feature_weights["descriptor"]["sha256"])
        staged_targets = registry.stage_artifact(prepared["artifact"]["path"], prepared["artifact"]["sha256"])
        staged_sources = [registry.stage_artifact(resolver(ref), ref["sha256"]) for ref in batch.source_refs]
        variant = {"source_language": "en", "target_formal_language": "typed_deontic_ir", "jurisdiction": "us", "model_variant": variant_id}
        registry.register_variant("variant", variant_id, {**variant,
            "corpus_index_binding": {"selection_sha256": index.scope.selection_sha256, "artifact": staged_index},
            "embedding_production_binding": {"artifact": staged_production}})
        version = registry.register_version("base", variant_id, base)["version_id"]
        registry.initialize_head("head", variant_id, "benchmark", version)

        def bound(ref):
            return {**ref, "path": str(registry.artifact_path(ref))}

        def job(run_id, *, mapped, shared, mapped_weights=False):
            started = time.perf_counter()
            payload = {"schema_version": "autoencoder-training-job-v7" if mapped else "autoencoder-training-job-v6",
                "job_id": run_id, "run_id": run_id, "base_version_id": version,
                **registered_checkpoint_inputs(registry, version),
                "output_directory": str(args.directory / run_id), "code_identity": "receipt-binds-current-workspace-source-files",
                "variant": variant, "dataset_snapshot_id": batch.dataset_snapshot_id, "split_snapshot_id": batch.split_snapshot_id,
                "samples": training, "validation_samples": validation,
                "corpus_manifest_artifact": bound(staged_batch), "corpus_source_artifacts": [bound(ref) for ref in staged_sources],
                "corpus_index_artifact": bound(staged_index), "corpus_selection_sha256": index.scope.selection_sha256,
                "embedding_production_artifact": bound(staged_production),
                "capture_sparse_patches": True, "candidate_storage": "sparse", "training_config": {"profile_projection": True}}
            if shared:
                payload.update(target_snapshot_id=prepared["target_snapshot_id"], target_snapshot_artifact=bound(staged_targets))
            if mapped:
                payload["arrow_embedding_inputs_artifact"] = bound(staged_arrow)
            if mapped_weights:
                payload["arrow_feature_weights_artifact"] = bound(staged_feature_weights)
            spec = TrainingJobSpec.from_dict(payload)
            path = args.directory / (run_id + ".job.json")
            _write(path, spec.to_dict())
            registry.create_run("create-" + run_id, run_id, variant_id, version,
                {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(path)})
            preparation_seconds[run_id] = time.perf_counter() - started
            return spec

        def execute(specs, *, workers=1):
            started = time.perf_counter()
            result = run_training_jobs(registry, specs, max_workers=workers)
            elapsed = time.perf_counter() - started
            if result["failed"]:
                receipt["failed_owner_result"] = result
                raise ValueError("native candidate job failed")
            rows = []
            for spec in specs:
                worker = json.loads((Path(spec.output_directory) / "receipt.json").read_bytes())
                completed = next(row for row in result["completed"] if row["run_id"] == spec.run_id)
                if any(worker["training_report"][stage]["legal_ir_target_count"] != 3 for stage in ("before", "after")):
                    raise ValueError("bridge-on validation target coverage differs from 3/3")
                if any(not worker["training_report"][stage]["legal_ir_losses"]
                       or "deontic" not in worker["training_report"][stage]["legal_ir_view_family_metrics"]
                       for stage in ("before", "after")):
                    raise ValueError("bridge-on validation lacks losses or deontic view metrics")
                if spec.target_snapshot_artifact and worker["shared_target_status_counts"] != {"ready": 6}:
                    raise ValueError("shared target union differs from six ready rows")
                if (Path(spec.output_directory) / "candidate.state.json").exists():
                    raise ValueError("sparse worker unexpectedly wrote full candidate state")
                rows.append({"worker": worker, "completed": completed,
                    "input_mode": "arrow" if spec.schema_version.endswith("v7") else "json",
                    "targets": "shared" if spec.target_snapshot_artifact else "fresh"})
            batch_result = {"elapsed_seconds": elapsed, "seconds_per_training_span": elapsed / (3 * len(specs)),
                "training_workers": workers, "job_preparation_seconds": sum(preparation_seconds[spec.run_id] for spec in specs),
                "jobs": rows, "timing_scope": "dispatch through owner durable completion; excludes one-time targets/Arrow/base staging and reports job preparation separately"}
            print(json.dumps({"runs": [spec.run_id for spec in specs], "elapsed_seconds": elapsed,
                "accepted_epochs": [row["worker"]["optimizer_accepted_epochs"] for row in rows], "admitted": False}), flush=True)
            return batch_result

        receipt["fresh_reference"] = execute([job("fresh-json", mapped=False, shared=False)])
        for pair in range(args.pairs):
            for mapped in ((False, True) if pair % 2 == 0 else (True, False)):
                receipt["paired_runs"].append(execute([job(f"pair-{pair}-{'arrow' if mapped else 'json'}", mapped=mapped, shared=True)]))
        reference = receipt["paired_runs"][0]["jobs"][0]["worker"]
        for batch_result in receipt["paired_runs"]:
            worker = batch_result["jobs"][0]["worker"]
            parity = _compare(reference, worker)
            receipt["parity"].append({"run_id": worker["run_id"], **parity})
            if not all(parity.values()):
                raise ValueError("shared JSON and Arrow training outcomes differ")
        fresh = receipt["fresh_reference"]["jobs"][0]["worker"]
        receipt["fresh_numeric_parity"] = {
            "candidate_materialized_checkpoint": fresh["candidate_materialized_checkpoint"] == reference["candidate_materialized_checkpoint"],
            "accepted_epochs": fresh["optimizer_accepted_epochs"] == reference["optimizer_accepted_epochs"],
            **{stage: _numbers(fresh["training_report"][stage]) == _numbers(reference["training_report"][stage]) for stage in ("before", "after")},
            **{stage + "_excluding_target_hashes":
                {key: value for key, value in fresh["training_report"][stage].items() if key != "legal_ir_target_hashes"}
                == {key: value for key, value in reference["training_report"][stage].items() if key != "legal_ir_target_hashes"}
                for stage in ("before", "after")}}
        receipt["fresh_target_hashes_identical"] = {stage:
            fresh["training_report"][stage]["legal_ir_target_hashes"] == reference["training_report"][stage]["legal_ir_target_hashes"]
            for stage in ("before", "after")}
        receipt["fresh_parity_scope"] = "all evaluation fields except target hashes, which include generated graph timestamps; shared modes compare full dictionaries and exact candidate state"
        if not all(receipt["fresh_numeric_parity"].values()):
            raise ValueError("fresh and shared numeric outcomes differ; no speed equivalence claim")
        receipt["combined_arrow_inputs_and_feature_weights"] = execute([
            job("combined-arrow", mapped=True, shared=True, mapped_weights=True)])
        combined = receipt["combined_arrow_inputs_and_feature_weights"]["jobs"][0]["worker"]
        parity = _compare(reference, combined)
        receipt["parity"].append({"run_id": combined["run_id"], **parity})
        if not all(parity.values()) or combined["weight_storage"] != "arrow_cow_feature_embeddings":
            raise ValueError("combined mapped-input/mapped-weight candidate differs")
        receipt["parallel"] = execute([job(f"parallel-arrow-{i}", mapped=True, shared=True) for i in range(2)], workers=2)
        for row in receipt["parallel"]["jobs"]:
            parity = _compare(reference, row["worker"])
            receipt["parity"].append({"run_id": row["worker"]["run_id"], **parity})
            if not all(parity.values()):
                raise ValueError("parallel candidate outcome differs")
        receipt["head_unchanged"] = registry.resolve_head(variant_id, "benchmark")["version_id"] == version
    with AutoencoderRegistry(database, artifacts) as registry:
        rows = receipt["fresh_reference"]["jobs"] + [row for batch_result in receipt["paired_runs"] for row in batch_result["jobs"]] + receipt["combined_arrow_inputs_and_feature_weights"]["jobs"] + receipt["parallel"]["jobs"]
        receipt["all_runs_durable_after_restart"] = all(registry.get_run(row["worker"]["run_id"])["status"] == "completed" for row in rows)
        receipt["head_unchanged_after_restart"] = registry.resolve_head(variant_id, "benchmark")["version_id"] == version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=2)
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists() or not 1 <= args.pairs <= 3:
        parser.error("use new artifact/receipt paths and 1–3 paired comparisons")
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import BRIDGE_NAMES
    paths = list(require_workspace_logic_tree().values()) + [str(Path(__file__).resolve())]
    paths += [str(Path(__file__).with_name(name)) for name in ("benchmark_shared_autoencoder_training.py", "benchmark_sparse_checkpoint_training.py")]
    paths += [str(ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / name) for name in (
        "autoencoder_arrow_inputs.py", "autoencoder_embedding_production.py", "autoencoder_training_worker.py", "autoencoder_training_coordinator.py",
        "autoencoder_corpus_manifest.py", "autoencoder_corpus_index.py", "autoencoder_target_preparation.py", "legal_samples.py",
        "legal_ir_target_bundle.py", "legal_ir_target_snapshot.py", "modal_autoencoder.py", "modal_autoencoder_patch_codec.py",
        "modal_autoencoder_sparse_checkpoint.py", "modal_autoencoder_arrow_weights.py", "modal_autoencoder_state_transaction.py", "modal_autoencoder_state_version.py")]
    paths.append(str(ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_registry.py"))
    paths += [str(ROOT / "ipfs_datasets_py/logic" / name) for name in (
        "bridge/multiview.py", "modal/decompiler.py", "modal/codec.py",
        "autoformal/ontology_capture.py", "autoformal/autoencoder_router.py",
        "autoformal/recipient_reference.py", "autoformal/procedure_slot.py")]
    receipt = {"schema": "produced-corpus-arrow-training-benchmark-v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": False, "admitted": False, "formalized": False, "heldout_canary_qualified": False,
        "promotion_performed": False, "publication_performed": False, "weights_downloaded": False,
        "sample_count_per_job": 3, "validation_sample_count_per_job": 3, "shared_target_union_count": 6,
        "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1,
        "metric_disk_cache": 0, "use_sample_memory": False, "projection_update_backend": "python_sparse_batch",
        "temperature": 0, "epochs": 1, "max_seconds": 180, "max_line_search_attempts": 1, "projection_max_update_families": 1,
        "native_threads": 1, "cache_policy": "fresh process per job; shared modes reuse complete sealed targets; disk metric cache disabled; OS cache uncontrolled",
        "source_hashes": {str(Path(path).relative_to(ROOT)): _sha(path) for path in paths}, "paired_runs": [], "parity": []}
    started = time.perf_counter()
    try:
        if _sha(PINNED) != PINNED_SHA:
            raise ValueError("pinned checkpoint changed")
        _run(args, receipt)
        receipt["source_unchanged"] = all(_sha(ROOT / path) == digest for path, digest in receipt["source_hashes"].items())
        receipt["pinned_checkpoint_unchanged"] = _sha(PINNED) == PINNED_SHA
        receipt["passed"] = all(receipt[key] for key in (
            "head_unchanged", "head_unchanged_after_restart", "all_runs_durable_after_restart", "source_unchanged", "pinned_checkpoint_unchanged"))
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    receipt["retained_artifact_bytes"] = sum(path.stat().st_size for path in args.directory.rglob("*") if path.is_file())
    receipt["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "error": receipt.get("error")}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
