"""Resumable qualification passes on immutable weights, without an optimizer.

This route opens no model registry, publishes no weights and does not enqueue
training. Its inference gate and full qualification checks are shared with the
candidate verifier. Capacity changes affect dispatch, never pass identities.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path

from . import autoencoder_incremental_training as inc


def _pass(candidate, version, sample, validation, directory, timeout):
    from .autoencoder_candidate_qualification import qualify_candidate
    from ...huggingface.autoencoder_span_attempts import _receipt
    from ...huggingface.autoencoder_incremental import _proofs, _qualified
    directory = Path(directory)
    receipt_path, seal_path = directory / "qualification.json", directory / "inference-seal.json"
    if seal_path.exists():
        seal = json.loads(seal_path.read_bytes())
        raw = receipt_path.read_bytes()
        if seal != {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}:
            raise ValueError("retained inference evidence changed")
        receipt = json.loads(raw)
    else:
        if directory.exists():
            raise ValueError("incomplete inference pass requires explicit recovery")
        qualify_candidate(candidate, version, [sample], directory,
            heldout_samples=validation, model_config={"compute_device": "python"},
            lake_timeout_seconds=timeout)
        raw = receipt_path.read_bytes()
        receipt = json.loads(raw)
        inc._write(seal_path, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    artifact = {key: candidate[key] for key in ("sha256", "bytes")}
    _receipt(receipt, version, artifact)
    if (receipt["sample_set_sha256"] != inc._sha({"training": [sample], "heldout": validation})
            or receipt["requested_model_config"] != {"compute_device": "python"}
            or receipt.get("execution_path") != "inference"
            or receipt.get("execution_gate_applied") is not True
            or receipt.get("training_executed") is not False):
        raise ValueError("inference evidence differs from requested route or samples")
    if ([row["source"] for row in receipt["rows"] if row["split"] == "training"] != [sample]
            or [row["source"] for row in receipt["rows"] if row["split"] == "heldout"] != validation):
        raise ValueError("inference rows differ from requested samples")
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != receipt["source_sha256"][key]
           for key, path in receipt["source_files"].items()):
        raise ValueError("inference producer source changed")
    if receipt["qualified"]:
        _qualified(receipt, {"version_id": version, "artifact": artifact})
        _proofs(receipt, read_local=True)
    return {"receipt": str(receipt_path), "qualification_sha256": hashlib.sha256(raw).hexdigest(),
            "qualified": receipt["qualified"], "gate_results": receipt["gate_results"],
            "execution_path": "inference", "training_executed": False,
            "admitted": False, "formalized": False}


def run_inference_cycle(config, cli, *, executor_factory=None, pass_function=_pass,
                        capacity_callback=None):
    """Local-only inference: never fall through to training or publication."""
    from .autoencoder_capacity import execution_capacity_plan
    if config.get("execution_mode") != "inference":
        raise ValueError("inference route requires the inference execution gate")
    if (not config.get("input_jsonl") or not config.get("validation_jsonl")
            or any(config.get(key) for key in ("repository_id", "publish_repository", "arrow_feature_weights", "shared_targets"))):
        raise ValueError("inference requires local input/validation and cannot publish or accept training artifacts")
    sources = {"native": cli._pin(), "orchestration": cli.orchestration_hashes()}
    records, validation = cli.local_records(config["input_jsonl"]), cli.local_records(config["validation_jsonl"])
    if not 1 <= len(validation) <= 32:
        raise ValueError("inference requires one to 32 disjoint tuning-validation rows")
    samples = [row["sample"] for row in records if int(row["record_id"].removeprefix("sha256:"), 16)
               % config.get("shard_count", 1) == config.get("shard_index", 0)]
    heldout = [row["sample"] for row in validation]
    checkpoint = Path(config["checkpoint"])
    if checkpoint.is_symlink() or not checkpoint.is_file():
        raise ValueError("inference requires a regular complete local checkpoint")
    candidate = {"path": str(checkpoint.resolve()), "sha256": cli._sha(checkpoint), "bytes": checkpoint.stat().st_size}
    if checkpoint.resolve() == cli.PINNED.resolve() and candidate["sha256"] != cli.PINNED_SHA:
        raise ValueError("protected restart12 checkpoint changed")
    version = "inference-" + candidate["sha256"]
    state = Path(config["state_directory"]) / "inference"
    state.mkdir(parents=True, exist_ok=True)
    binding = {"candidate": candidate, "sources": sources, "validation": heldout,
               "lake_timeout_seconds": config["lake_timeout_seconds"], "execution_path": "inference"}
    binding_path = state / "binding.json"
    if binding_path.exists() and json.loads(binding_path.read_bytes()) != binding:
        raise ValueError("inference checkpoint, source or validation policy changed; new state required")
    if not binding_path.exists():
        inc._write(binding_path, binding)
    rows, pending = [], []
    for sample in samples:
        directory = state / "passes" / inc._sha(sample)
        args = (candidate, version, sample, heldout, directory, config["lake_timeout_seconds"])
        if (directory / "inference-seal.json").exists():
            rows.append(pass_function(*args))
        else:
            pending.append(args)
    plans, dispatched = [], 0
    while pending and dispatched < config["max_batches"]:
        plan = (capacity_callback or (lambda **limits: execution_capacity_plan("inference", **limits)))(
            max_workers=config.get("max_parallel_workers", config["workers"]),
            memory_budget_mb=config["memory_mb"], cpu_budget=config.get("max_parallel_workers", config["workers"]),
            process_budget=config.get("reserved_child_process_slots"),
            pending_count=min(len(pending), config["max_batches"] - dispatched))
        plans.append(plan)
        if plan["workers"] == 0:
            break
        wave = pending[:plan["workers"]]
        factory = executor_factory or (lambda **kw: ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"), **kw))
        with factory(max_workers=len(wave)) as executor:
            futures = [executor.submit(pass_function, *args) for args in wave]
            rows.extend(future.result() for future in futures)
        pending = pending[len(wave):]
        dispatched += len(wave)
    if (cli._sha(checkpoint) != candidate["sha256"]
            or {"native": cli._pin(), "orchestration": cli.orchestration_hashes()} != sources):
        raise ValueError("inference weights or producer changed during execution")
    result = {"schema": "autoencoder-inference-cycle/v1", "execution_path": "inference",
              "training_executed": False, "training": None, "weight_publications": [],
              "input_count": len(samples), "inference": rows, "dispatched_pass_count": dispatched,
              "pending_pass_count": len(pending), "capacity_plans": plans, "source_hashes": sources,
              "candidate": candidate, "temperature": 0, "admitted": False, "formalized": False,
              "promotion_performed": False, "heldout_canary": False}
    cli._write(config["cycle_receipt"], result)
    return result
