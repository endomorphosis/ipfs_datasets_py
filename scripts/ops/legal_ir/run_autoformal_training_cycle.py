#!/usr/bin/env python3
"""One real, source-verified autoencoder training and compiler-feedback cycle.

Consume an existing verified v6 or v8 corpus job with inline embeddings.
Validation/canary records never become repair prompts. Candidate checkpoints
stay private; completing a training job is not promoting a model or a proof.
Invoke in a fresh process after code changes so the compiler cannot stay stale.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from run_autoformal_supervisor import ROOT, code_identity, pin_accelerate


def schedule_published_todos(huggingface: dict, args, *, repo_root: Path, schedule=None) -> dict:
    """Register a cycle Hugging Face todo release on the accelerate queue."""

    pointer = Path(
        ((huggingface.get("pointer") or {}).get("pointer_path") or args.pointer or "")
    )
    if not pointer.is_file():
        raise ValueError("schedule-queue requires a Hugging Face pointer")
    if schedule is None:
        from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer

        schedule = schedule_from_pointer
    return schedule(
        pointer,
        repo_root=repo_root,
        board=args.board or pointer.with_name("cycle.todo.md"),
        queue_path=args.schedule_queue,
        package_root=args.huggingface_package,
        max_tokens=args.max_tokens,
        max_validation_seconds=args.max_validation_seconds,
    )


def write_record(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def descriptor(value):
    return {key: value[key] for key in ("sha256", "bytes")}


def training_configuration(original: dict, *, max_seconds: float,
                           max_update_families: int, max_line_search_attempts: int) -> dict:
    """Bound exploration without changing the objective or acceptance guards.

    Native update order is global IR logits, feature IR logits, family logits,
    decoded embeddings, then a combined update. A cap of one cannot train the
    family or embedding heads, even when more wall time is available.
    """
    if not 1 <= max_seconds <= 600:
        raise ValueError("training budget must be between 1 and 600 seconds")
    if type(max_update_families) is not int or not 1 <= max_update_families <= 5:
        raise ValueError("update family bound must be between 1 and 5")
    if type(max_line_search_attempts) is not int or not 1 <= max_line_search_attempts <= 6:
        raise ValueError("line search bound must be between 1 and 6")
    return {**original, "epochs": 1, "max_seconds": max_seconds,
            "max_line_search_attempts": max_line_search_attempts,
            "projection_max_update_families": max_update_families,
            "profile_projection": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--job-template", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--max-training-seconds", type=float, default=600)
    parser.add_argument("--max-update-families", type=int, choices=range(1, 6), default=5,
                        help="1 tests only global IR logits; 5 permits family, embedding and combined updates too.")
    parser.add_argument("--max-line-search-attempts", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--storage-limit-bytes", type=int, default=50_000_000_000)
    parser.add_argument("--base-version", default="", help="Private candidate version from a prior cycle in this runtime.")
    parser.add_argument("--cycle-id", default="", help="Optional journal-bound cycle identifier; must be new.")
    parser.add_argument("--huggingface-package", type=Path, default=None)
    parser.add_argument("--pointer", type=Path, default=None)
    parser.add_argument("--board", type=Path, default=None)
    parser.add_argument("--schedule-queue", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-validation-seconds", type=int, default=None)
    args = parser.parse_args(argv)
    if not 1 <= args.max_training_seconds <= 600:
        parser.error("training budget must be between 1 and 600 seconds")
    if not 1_000_000_000 <= args.storage_limit_bytes <= 50_000_000_000:
        parser.error("storage limit must be between 1 and 50 billion bytes")
    if args.cycle_id and not re.fullmatch(r"cycle-[0-9a-f]{32}", args.cycle_id):
        parser.error("cycle id must be cycle- followed by 32 lowercase hexadecimal characters")
    pin = pin_accelerate(args.accelerate_root)
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "OMP_NUM_THREADS": "1",
                       "OPENBLAS_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": ""})
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        TrainingJobSpec,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import (
        run_training_jobs, registered_checkpoint_inputs,
    )
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import agreement_census
    from ipfs_datasets_py.logic.autoformal.learned_feedback import observe_checkpoint, attach_guidance
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import enqueue_repairs, repair_packets
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

    if args.job_template.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("job template exceeds bounded input size")
    input_helper_hash = hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest()
    original = TrainingJobSpec.from_dict(json.loads(args.job_template.read_bytes()))
    cycle_inputs = training_cycle_inputs.verify_cycle_inputs(original)
    verified = cycle_inputs.verification
    training_record_ids = [record.record_id for record in cycle_inputs.training_records]
    if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
        raise RuntimeError("cycle input helper changed during verification")
    runtime = args.runtime_root.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    # Reserve a conservative per-cycle allowance; never remove older artifacts.
    used = sum(path.stat().st_size for path in runtime.rglob("*") if path.is_file())
    reserve = max(512 * 1024 * 1024, original.base_checkpoint.bytes * 8)
    if used + reserve > args.storage_limit_bytes or shutil.disk_usage(runtime).free < reserve:
        raise RuntimeError("storage reservation unavailable; retained artifacts are untouched")
    cycle_id = args.cycle_id or "cycle-" + uuid.uuid4().hex
    directory = runtime / cycle_id
    directory.mkdir()
    source_identity = code_identity()
    print(json.dumps({"cycle": cycle_id, "stage": "source_inputs_verified",
                      "training_samples": len(original.samples), "validation_samples": len(original.validation_samples)}), flush=True)
    started = time.monotonic()
    with AutoencoderRegistry(runtime / "training.duckdb", runtime / "artifacts") as registry:
        payload, variant = training_cycle_inputs.stage_cycle_job_inputs(registry, original)
        variant_id = "autoformal-" + hashlib.sha256(json.dumps(variant, sort_keys=True).encode()).hexdigest()[:20]
        registry.register_variant("variant-" + variant_id, variant_id, variant)
        base = descriptor(payload["base_checkpoint"])
        version = registry.register_version("base-" + variant_id, variant_id, base)["version_id"]
        if args.base_version:
            previous = registry.get_version(args.base_version)
            if previous["variant_id"] != variant_id:
                raise ValueError("previous candidate belongs to a different corpus/model variant")
            payload.update(registered_checkpoint_inputs(registry, args.base_version))
            version = args.base_version
            # The Arrow override is bound to the original base checkpoint.
            payload["arrow_feature_weights_artifact"] = None
        payload.update(job_id=cycle_id, run_id=cycle_id, base_version_id=version,
                       output_directory=str(directory / "training"), code_identity=source_identity)
        payload["training_config"] = training_configuration(
            payload["training_config"], max_seconds=args.max_training_seconds,
            max_update_families=args.max_update_families,
            max_line_search_attempts=args.max_line_search_attempts,
        )
        spec = TrainingJobSpec.from_dict(payload)
        job_file = directory / "job.json"
        write_record(job_file, spec.to_dict())
        job_artifact = registry.stage_artifact(job_file)
        registry.create_run("create-" + cycle_id, cycle_id, variant_id, version,
                            {"job_spec_artifact": job_artifact, "job_spec_sha256": spec.canonical_sha256})
        if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
            raise RuntimeError("cycle input helper changed before training dispatch")
        trained = run_training_jobs(registry, [spec], max_workers=1, lease_seconds=900)
        write_record(directory / "training-owner.json", trained)
        if trained["failed"] or len(trained["completed"]) != 1:
            print(json.dumps({"cycle": cycle_id, "stage": "training_failed", "receipt": str(directory / "training-owner.json")}), flush=True)
            return 1
        worker = json.loads((directory / "training" / "receipt.json").read_bytes())
        if worker["execution_mode"] != "native_training" or worker.get("promotion_performed"):
            raise RuntimeError("unexpected worker execution or promotion")
        candidate = trained["completed"][0]
        model_identity = "sha256:" + candidate["candidate"]["sha256"]
    if code_identity() != source_identity:
        raise RuntimeError("compiler changed during cycle; restart before producing repair tasks")
    if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
        raise RuntimeError("cycle input helper changed during training")
    worker_receipt = directory / "training" / "receipt.json"
    learned_feedback = observe_checkpoint(worker_receipt, hashlib.sha256(worker_receipt.read_bytes()).hexdigest())
    if code_identity() != source_identity:
        raise RuntimeError("compiler changed during learned feedback; no repair tasks were produced")
    if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
        raise RuntimeError("cycle input helper changed during learned feedback")
    write_record(directory / "learned-feedback.json", learned_feedback)
    # Only training members may feed the repair agent. Do not expose held-out
    # source text, capture features or validation labels in task prompts.
    # Refresh exact worker-staged membership after training; source tuple matches
    # are insufficient when distinct legal records carry the same text.
    refreshed_inputs = training_cycle_inputs.verify_cycle_inputs(spec, record_ids=training_record_ids)
    records = list(refreshed_inputs.training_records)
    if code_identity() != source_identity:
        raise RuntimeError("compiler changed during repair selection; no repair tasks were produced")
    if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
        raise RuntimeError("cycle input helper changed before repair selection")
    observations, receipts = [], []
    with DatabaseTaskSource(args.database.resolve()) as source:
        for start in range(0, len(records), 16):
            group = records[start:start + 16]
            samples = [{"id": row.record_id, "source_span_id": row.record_id,
                        "legal_id": row.source.document_id, "canonical_citation": row.source.citation,
                        "text": row.sample.text, "status": "operative"} for row in group]
            agreement = agreement_census(samples, {"captures": []})
            agreement = attach_guidance(agreement, learned_feedback, model_identity)
            if code_identity() != source_identity:
                raise RuntimeError("compiler changed during repair observation; no tasks for this group were produced")
            if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
                raise RuntimeError("cycle input helper changed during repair observation")
            observations.append(agreement)
            releases = sorted({row.source.release_id for row in group})
            items = repair_packets(agreement, release_id=";".join(releases), code_identity=source_identity,
                                   model_identity=model_identity)
            receipts.append(enqueue_repairs(source, items, packet_directory=runtime / "packets"))
    huggingface = None
    if args.huggingface_package is not None:
        from ipfs_datasets_py.huggingface.autoformal_todo import publish_observation_todos

        huggingface = publish_observation_todos(
            observations,
            args.huggingface_package,
            board_path=args.board,
            pointer_path=args.pointer,
            dry_run=True,
        )
        if args.schedule_queue is not None:
            huggingface["scheduled"] = schedule_published_todos(
                huggingface, args, repo_root=ROOT
            )
    summary = {**pin, "cycle_id": cycle_id, "stage": "native_training_and_repair_queue",
               "source_input_verification": verified, "code_identity": source_identity,
               "input_helper_source_sha256": input_helper_hash,
               "candidate_version_id": candidate["version_id"], "model_identity": model_identity,
               "optimizer_accepted_epochs": worker["optimizer_accepted_epochs"],
               "training_report": worker["training_report"], "queue_receipts": receipts,
               "learned_feedback": {"path": str(directory / "learned-feedback.json"),
                                    "sha256": hashlib.sha256((directory / "learned-feedback.json").read_bytes()).hexdigest(),
                                    "observation_count": learned_feedback["observation_count"],
                                    "counts_as_validation": False, "symbolic_decoder_output": False},
               "agreement": observations, "wall_seconds": time.monotonic() - started,
               "compiler_observation": "independent_source_replay_not_learned_semantic_equivalence",
               "admitted": False, "formalized": False, "production_promotion": False,
               "jsonl_written": False,
               "huggingface": None if huggingface is None else {
                   "jsonl_written": False,
                   "locator": (huggingface or {}).get("locator") or {},
                   "task_count": (huggingface or {}).get("task_count") or 0,
                   "board_path": (huggingface or {}).get("board_path") or "",
                   "scheduled": (huggingface or {}).get("scheduled") or {},
               }}
    write_record(directory / "cycle.json", summary)
    print(json.dumps({"cycle": cycle_id, "stage": "cycle_complete", "receipt": str(directory / "cycle.json"),
                      "accepted_epochs": worker["optimizer_accepted_epochs"],
                      "inserted_tasks": sum(row["task_count"] for row in receipts),
                      "candidate_version_id": candidate["version_id"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
