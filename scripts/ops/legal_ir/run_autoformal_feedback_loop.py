#!/usr/bin/env python3
"""Alternate native DuckDB repair passes with fresh-process training/replay.

One owner, a clean private candidate repository, no automatic production merge
or model promotion. STOP in the runtime directory requests a bounded shutdown.
Live operation requires a compatible native claim/effect/validation dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from run_autoformal_supervisor import (
    ROOT, PROTECTED, code_identity, pin_accelerate, require_native_transition_contract,
    preflight_next_repair, require_validation_preflight,
    validated_task_id,
)


def huggingface_child_flags(args) -> list[str]:
    """Forward Hugging Face todo publication/schedule flags to a train child."""

    flags: list[str] = []
    mapping = (
        ("huggingface_package", "--huggingface-package"),
        ("pointer", "--pointer"),
        ("board", "--board"),
        ("schedule_queue", "--schedule-queue"),
        ("max_tokens", "--max-tokens"),
        ("max_validation_seconds", "--max-validation-seconds"),
    )
    for attribute, flag in mapping:
        value = getattr(args, attribute, None)
        if value is not None:
            flags.extend([flag, str(value)])
    return flags


def repository_preflight(repository: Path) -> None:
    from ipfs_datasets_py.logic.autoformal.validator_profile import require_deployment, SEALED_FILES
    require_deployment(repository)
    top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repository, text=True).strip()
    if Path(top).resolve() != repository:
        raise ValueError("candidate repository must be a Git root")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repository):
        raise ValueError("candidate repository is dirty; reconcile it before automated execution")
    # Keep source freshness and the deployed seal aligned, including files
    # (such as the clause splitter) previously listed only in SEALED_FILES.
    for relative in dict.fromkeys((*PROTECTED, *SEALED_FILES)):
        actual, expected = repository / relative, ROOT / relative
        if actual.is_symlink() or not actual.is_file() or actual.read_bytes() != expected.read_bytes():
            raise ValueError("candidate snapshot lacks current protected harness: " + relative)


def cycle_result(receipt: Path, expected_cycle: str, expected_code: str) -> dict:
    # The full metrics and source observations stay in the generated receipt.
    # The journal stores only lineage and measured aggregate outcomes.
    with receipt.open("rb") as stream:
        raw = stream.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("cycle receipt exceeds bounded evidence size")
    report = json.loads(raw)
    if report.get("cycle_id") != expected_cycle or report.get("code_identity") != expected_code:
        raise ValueError("cycle receipt is bound to another execution or compiler")
    if report.get("stage") != "native_training_and_repair_queue" or any(
        report.get(key) is not False for key in ("admitted", "formalized", "production_promotion")
    ):
        raise ValueError("unexpected cycle stage or trust promotion")
    if not report.get("candidate_version_id") or not report.get("model_identity"):
        raise ValueError("cycle has no registered private candidate identity")
    rows = [row for batch in report["agreement"] for row in batch["rows"]]
    if not rows:
        raise ValueError("empty compiler replay cannot qualify a training cycle")
    return {"receipt_path": str(receipt), "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "candidate_version_id": report["candidate_version_id"], "model_identity": report["model_identity"],
            "optimizer_accepted_epochs": report["optimizer_accepted_epochs"],
            "discrepancies": sum(row.get("agrees") is not True or bool(row.get("skipped")) for row in rows),
            "compiler_records": len(rows), "admitted": False, "formalized": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--job-template", type=Path, required=True)
    parser.add_argument("--task-id", type=validated_task_id, default=None,
                        help="Bound supervisor work to one native-ready task; never train or fall back to other tasks.")
    parser.add_argument("--merge-target-branch", default="autoformal-candidate")
    parser.add_argument("--max-training-seconds", type=float, default=600)
    parser.add_argument("--max-update-families", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--max-line-search-attempts", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--implementation-timeout", type=float, default=1800)
    parser.add_argument("--phase-wall-timeout", type=float, default=3600)
    parser.add_argument("--storage-limit-bytes", type=int, default=50_000_000_000)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--max-phases", type=int, default=0, help="0 means continue; positive values bound a pilot.")
    parser.add_argument("--implement", action="store_true")
    parser.add_argument("--huggingface-package", type=Path, default=None)
    parser.add_argument("--pointer", type=Path, default=None)
    parser.add_argument("--board", type=Path, default=None)
    parser.add_argument("--schedule-queue", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-validation-seconds", type=int, default=None)
    args = parser.parse_args(argv)
    args.task_id = args.task_id or ""
    if not 1 <= args.max_training_seconds <= 600 or not 30 <= args.implementation_timeout <= 3600:
        parser.error("invalid training or implementation budget")
    if not args.implementation_timeout <= args.phase_wall_timeout <= 7200 or not 1 <= args.interval <= 60:
        parser.error("invalid phase or idle time bounds")
    if args.max_phases < 0 or not 3_000_000_000 <= args.storage_limit_bytes <= 50_000_000_000:
        parser.error("invalid phase count or retained storage limit")
    binding = pin_accelerate(args.accelerate_root)
    require_native_transition_contract()  # No phase journal or claim stores before this guard.
    repository = args.repository_root.resolve(strict=True)
    runtime = args.runtime_root.resolve()
    database = args.database.resolve()
    template = args.job_template.resolve(strict=True)
    if repository == ROOT or not repository.is_relative_to(runtime):
        parser.error("repairs must target a private candidate repository inside the owned runtime")
    if database.is_symlink() or not database.is_relative_to(runtime):
        parser.error("task database must be inside the dedicated runtime")
    repository_preflight(repository)
    if not args.implement:
        print(json.dumps({**binding, "execution_enabled": False, "tasks_claimed": False,
                          "repository": str(repository), "runtime": str(runtime)}))
        return 0
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.feedback_cycle import (
        FeedbackCycleError, PhaseJournal, check_storage, exclusive_loop, next_phase,
        phase_id, queue_observation, run_phase,
    )
    from ipfs_datasets_py.logic.autoformal.repair_intake import route_intake_reviews
    with exclusive_loop(runtime):
        journal = PhaseJournal(runtime / "feedback-loop.duckdb")
        try:
            journal.require_no_interrupted_phase()
            phases = 0
            while not (runtime / "STOP").exists():
                check_storage(runtime, args.storage_limit_bytes)
                repository_preflight(repository)
                code = code_identity(repository)
                revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
                if template.stat().st_size > 64 * 1024 * 1024:
                    raise FeedbackCycleError("job template exceeds bounded input size")
                job_hash = hashlib.sha256(template.read_bytes()).hexdigest()
                identity = hashlib.sha256(json.dumps([
                    revision, code, job_hash, args.max_training_seconds,
                    args.max_update_families, args.max_line_search_attempts,
                ]).encode()).hexdigest()
                # Existing queues were initialized by their native owner;
                # observation/selection must not rerun schema initialization.
                with DatabaseTaskSource(database, install_schema=not database.exists()) as source:
                    intake = route_intake_reviews(source, apply=True)
                    if intake["review_required"]:
                        intake_path = runtime / (phase_id() + "-intake-review.json")
                        with intake_path.open("x") as stream:
                            json.dump(intake, stream, sort_keys=True, indent=2, allow_nan=False)
                            stream.write("\n")
                        print(json.dumps({"stage": "intake_review", "receipt": str(intake_path),
                                          "blocked_for_review": intake["review_required"],
                                          "repairs_completed": 0}), flush=True)
                    before = queue_observation(source)
                previous = journal.previous_training()
                phase = next_phase(before, identity, previous)
                if args.task_id and phase != "supervise":
                    print(json.dumps({"stage": "selected_task_not_eligible", "task_id": args.task_id,
                                      "queue": before, "tasks_claimed": False, "production_promotion": False}), flush=True)
                    return 0
                if phase in {"idle", "waiting"}:
                    if args.max_phases:
                        # A bounded pilot must not turn into an unbounded wait
                        # when it has no phase left to execute.
                        print(json.dumps({"stage": phase, "phases_executed": phases, "queue": before,
                                          "production_promotion": False}), flush=True)
                        return 0
                    time.sleep(args.interval)
                    continue
                identifier = phase_id()
                if phase == "supervise":
                    with DatabaseTaskSource(database, install_schema=False) as source:
                        preflight = preflight_next_repair(source, repository, task_id=args.task_id)
                    receipt = runtime / (identifier + "-launch-preflight.json")
                    with receipt.open("x") as stream:
                        json.dump(preflight, stream, sort_keys=True, indent=2, allow_nan=False)
                        stream.write("\n")
                    require_validation_preflight(preflight)
                    if args.task_id and not preflight["eligible"]:
                        print(json.dumps({"stage": "selected_task_not_eligible", "task_id": args.task_id,
                                          "queue": before, "tasks_claimed": False,
                                          "production_promotion": False}), flush=True)
                        return 0
                command = [sys.executable, str(repository / "scripts/ops/legal_ir" /
                           ("run_autoformal_training_cycle.py" if phase == "train" else "run_autoformal_supervisor.py")),
                           "--accelerate-root", str(args.accelerate_root.resolve()),
                           "--database", str(database), "--runtime-root", str(runtime)]
                if phase == "train":
                    command += ["--job-template", str(template), "--cycle-id", identifier,
                                "--max-training-seconds", str(args.max_training_seconds),
                                "--max-update-families", str(args.max_update_families),
                                "--max-line-search-attempts", str(args.max_line_search_attempts),
                                "--storage-limit-bytes", str(args.storage_limit_bytes)]
                    if previous:
                        command += ["--base-version", previous["candidate_version_id"]]
                    command += huggingface_child_flags(args)
                else:
                    if args.task_id:
                        command += ["--task-id", args.task_id]
                    command += ["supervise", "--implement", "--once", "--repository-root", str(repository),
                                "--merge-target-branch", args.merge_target_branch,
                                "--implementation-timeout", str(args.implementation_timeout)]
                log = runtime / (identifier + "-" + phase + ".log")
                journal.start(phase, identity, command, log, phase_id=identifier)
                print(json.dumps({"phase": phase, "id": identifier, "log": str(log), "stage": "started"}), flush=True)
                try:
                    result = run_phase(command, cwd=repository, log=log, runtime=runtime,
                                       storage_limit=args.storage_limit_bytes, wall_timeout=args.phase_wall_timeout)
                    if result["stop_reason"] or result["returncode"] != 0:
                        journal.finish(identifier, "stopped" if result["stop_reason"] else "failed", result)
                        print(json.dumps({"phase": phase, "id": identifier, **result}), flush=True)
                        return 2
                    if phase == "train":
                        if hashlib.sha256(template.read_bytes()).hexdigest() != job_hash or code_identity(repository) != code:
                            raise FeedbackCycleError("compiler or job template changed during training")
                        result.update(cycle_result(runtime / identifier / "cycle.json", identifier, code))
                    else:
                        with DatabaseTaskSource(database, install_schema=False) as source:
                            result["queue_after"] = queue_observation(source)
                        result["compiler_changed"] = code_identity(repository) != code
                        if result["queue_after"]["counts"] == before["counts"] and not result["compiler_changed"]:
                            raise FeedbackCycleError("native pass produced no observable task/code progress; inspect its log before retry")
                    journal.finish(identifier, "finished", result)
                except BaseException as exc:
                    journal.finish(identifier, "failed", {"error_type": type(exc).__name__, "error": str(exc), "log_path": str(log)})
                    raise
                print(json.dumps({"phase": phase, "id": identifier, "stage": "finished", **result}), flush=True)
                phases += 1
                if args.max_phases and phases >= args.max_phases:
                    return 0
        finally:
            journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
