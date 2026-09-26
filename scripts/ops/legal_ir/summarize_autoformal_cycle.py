#!/usr/bin/env python3
"""Generate a compact, source-free diagnostic from a completed native cycle.

Reads evidence and verifies checkpoint bytes; never schedules work, certifies
legal equivalence, completes a task, or promotes a model. Full receipts stay on
disk. Profiling stage durations are inclusive and must not be added together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


METRICS = ("cross_entropy_loss", "cross_entropy_excess_loss", "cosine_loss",
           "embedding_cosine_similarity", "reconstruction_loss")


def read_receipt(path: Path) -> tuple[dict, str]:
    with path.open("rb") as stream:
        raw = stream.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("receipt exceeds 64 MiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("receipt must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def count(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid nonnegative integer: " + name)
    return value


def metric(value) -> float:
    if type(value) not in {float, int} or not math.isfinite(value):
        raise ValueError("metric must be a finite number")
    return float(value)


def checkpoint_digest(descriptor: dict, root: Path) -> str:
    path = Path(descriptor["path"])
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("checkpoint is outside its evidence root or is a symlink")
    size = count(descriptor["bytes"], "checkpoint bytes")
    if size > 256 * 1024 * 1024 or path.stat().st_size != size:
        raise ValueError("checkpoint size mismatch or exceeds 256 MiB")
    digest, observed = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            observed += len(chunk)
            if observed > size:
                raise ValueError("checkpoint grew while reading")
            digest.update(chunk)
    if observed != size or digest.hexdigest() != descriptor["sha256"]:
        raise ValueError("checkpoint bytes differ from receipt")
    return digest.hexdigest()


def summarize(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    cycle, cycle_hash = read_receipt(directory / "cycle.json")
    worker, worker_hash = read_receipt(directory / "training/receipt.json")
    if (cycle["stage"] != "native_training_and_repair_queue"
            or worker["execution_mode"] != "native_training"
            or cycle["cycle_id"] != worker["job_id"]
            or worker["job_id"] != worker["job_spec"]["job_id"]
            or cycle["code_identity"] != worker["job_spec"]["code_identity"]
            or worker["training_report"] != cycle["training_report"]):
        raise ValueError("cycle and worker receipts do not bind the same native execution")
    if any(cycle.get(key) is not False for key in ("admitted", "formalized", "production_promotion")):
        raise ValueError("unexpected cycle trust promotion")
    if worker.get("admitted") is not False or worker.get("promotion_performed") is not False:
        raise ValueError("unexpected worker trust promotion")
    report = worker["training_report"]
    if report.get("sample_memory_used") is not False:
        raise ValueError("sample-memory policy is not explicit")
    accepted = count(worker["optimizer_accepted_epochs"], "accepted epochs")
    if accepted != cycle["optimizer_accepted_epochs"] or accepted != report["accepted_epochs"]:
        raise ValueError("accepted epoch counts disagree")
    epochs = report["epoch_reports"]
    selected = [epoch["selected_update"] for epoch in epochs if epoch.get("accepted") is True]
    if len(selected) != accepted or any(not isinstance(name, str) or not name for name in selected):
        raise ValueError("committed epoch selections disagree with acceptance count")
    attempts = count(report["rejection_summary"]["attempted_count"], "attempted updates")
    if attempts < accepted:
        raise ValueError("accepted more epochs than attempted updates")
    base = checkpoint_digest(worker["base_checkpoint"], directory.parent / "artifacts")
    candidate = checkpoint_digest(worker["candidate"], directory / "training")
    if cycle["model_identity"] != "sha256:" + candidate:
        raise ValueError("cycle model identity differs from candidate bytes")
    losses = {}
    for name in METRICS:
        before, after = metric(report["before"][name]), metric(report["after"][name])
        losses[name] = {"before": before, "after": after, "after_minus_before": after - before}
    stages = report.get("projection_profile", {}).get("by_stage", {})
    top_stages = sorted(
        ({"stage": name, "inclusive_seconds": metric(value["seconds"])} for name, value in stages.items()),
        key=lambda row: (-row["inclusive_seconds"], row["stage"]),
    )[:8]
    state_changed = worker["base_state_identity"]["digest"] != worker["candidate_state_identity"]["digest"]
    rows = [row for batch in cycle["agreement"] for row in batch["rows"]]
    return {
        "schema": "uscode-autoformal-cycle-summary/v1", "cycle_id": cycle["cycle_id"],
        "evidence": {"cycle_sha256": cycle_hash, "worker_sha256": worker_hash,
                     "base_checkpoint_sha256": base, "candidate_checkpoint_sha256": candidate},
        "diagnostic_only": True, "candidate_version_id": cycle["candidate_version_id"],
        "training_samples": count(worker["sample_count"], "training samples"),
        "validation_samples": count(worker["validation_sample_count"], "validation samples"),
        "attempted_updates": attempts, "accepted_epochs": accepted,
        "selected_update_families": selected, "artifact_bytes_changed": base != candidate,
        "reported_model_state_changed": state_changed,
        "native_stop_reason": report.get("stopped_reason"), "losses": losses,
        "wall_seconds": metric(cycle["wall_seconds"]),
        "guard_rejection_counts": report["rejection_summary"].get("pareto_regression_counts", {}),
        "top_profile_stages": top_stages, "profile_durations_overlap": True,
        "compiler_records": len(rows),
        "compiler_discrepancies": sum(row.get("agrees") is not True or bool(row.get("skipped")) for row in rows),
        "new_tasks": sum(count(item["task_count"], "new tasks") for item in cycle["queue_receipts"]),
        "admitted": False, "formalized": False, "production_promotion": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle_directory", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; existing evidence is never overwritten.")
    args = parser.parse_args(argv)
    result = summarize(args.cycle_directory)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in (
        "cycle_id", "attempted_updates", "accepted_epochs", "artifact_bytes_changed",
        "compiler_discrepancies", "new_tasks", "production_promotion",
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
