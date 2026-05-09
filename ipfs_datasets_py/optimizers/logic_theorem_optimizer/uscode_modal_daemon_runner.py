"""Guarded U.S. Code modal TODO daemon runner.

This module owns the production runner used by the optimizer experiments.  It
keeps validation clean by ignoring sample-specific memorization, rolling back
failed validation updates through ``ModalTodoSupervisor``, and avoiding
validation rows that already have sample-memory entries in the current state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalTodoQueue,
    ModalTodoSupervisor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
    HF_USCODE_DATASET_ID,
    USCODE_LAWS_PARQUET,
    USCodeParquetRecord,
)

LAW_COLUMNS = [
    "ipfs_cid",
    "title_number",
    "title_name",
    "section_number",
    "law_name",
    "source_url",
    "text",
    "citation_text",
    "normalized_citation",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def load_laws_table():
    fs = HfFileSystem()
    path = f"datasets/{HF_USCODE_DATASET_ID}/{USCODE_LAWS_PARQUET}"
    with fs.open(path, "rb") as laws_file:
        return pq.ParquetFile(laws_file).read(columns=LAW_COLUMNS)


def row_to_sample(row: Mapping[str, Any]):
    return USCodeParquetRecord.from_row(row).to_sample()


def sample_train_validation_rows(
    laws_table,
    rng: random.Random,
    *,
    train_count: int,
    validation_count: int,
    blocked_validation_sample_ids: set[str],
):
    train_indices = rng.sample(range(laws_table.num_rows), train_count)
    train_rows = laws_table.take(train_indices).to_pylist()
    train_samples = [row_to_sample(row) for row in train_rows]
    selected_indices = set(train_indices)
    validation_indices = []
    validation_samples = []
    attempts = 0
    max_attempts = max(1000, validation_count * 100)
    while len(validation_samples) < validation_count and attempts < max_attempts:
        attempts += 1
        index = rng.randrange(laws_table.num_rows)
        if index in selected_indices:
            continue
        sample = row_to_sample(laws_table.take([index]).to_pylist()[0])
        if sample.sample_id in blocked_validation_sample_ids:
            continue
        selected_indices.add(index)
        validation_indices.append(index)
        validation_samples.append(sample)
    if len(validation_samples) < validation_count:
        raise RuntimeError(
            "Unable to sample enough validation rows without prior sample-memory exposure"
        )
    return train_indices, train_samples, validation_indices, validation_samples, attempts


def metric_block(evaluation) -> Dict[str, Any]:
    return {
        "cosine_loss": round(evaluation.cosine_loss, 9),
        "cosine_similarity": round(evaluation.embedding_cosine_similarity, 9),
        "cross_entropy_loss": round(evaluation.cross_entropy_loss, 9),
        "reconstruction_loss": round(evaluation.reconstruction_loss, 9),
        "sample_count": evaluation.sample_count,
        "symbolic_validity_penalty": round(evaluation.symbolic_validity_penalty, 9),
    }


def run_tests(root: Path, report_dir: Path, cycle: int) -> Dict[str, Any]:
    xml_path = report_dir / f"cycle-{cycle}.xml"
    cmd = [
        "pytest",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_uscode_dataset.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
        "-q",
        "--junitxml",
        str(xml_path),
    ]
    started = time.time()
    result = subprocess.run(cmd, cwd=root, text=True, capture_output=True)
    return {
        "cycle": cycle,
        "duration_seconds": round(time.time() - started, 3),
        "event": "tests",
        "exit_code": result.returncode,
        "junitxml": str(xml_path),
        "stderr_tail": result.stderr[-500:],
        "stdout_tail": result.stdout[-500:],
    }


def append_event(path: Path, run_id: str, event: Mapping[str, Any]) -> None:
    payload = {"created_at": utc_now(), "run_id": run_id, **dict(event)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def save_summary(summary_path: Path, summary: Dict[str, Any], *, final: bool = False) -> None:
    summary["final"] = final
    summary["updated_at"] = utc_now()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def initial_summary(args: argparse.Namespace, *, log_path: Path, queue_path: Path, state_path: Path) -> Dict[str, Any]:
    seed = int(hashlib.sha256(args.run_id.encode("utf-8")).hexdigest()[:12], 16)
    return {
        "best_validation_ce": 1.0e12,
        "best_validation_cosine": -1.0,
        "best_validation_reconstruction": 1.0e12,
        "cycles": 0,
        "dataset_id": HF_USCODE_DATASET_ID,
        "final": False,
        "laws_path": USCODE_LAWS_PARQUET,
        "log_path": str(log_path),
        "metric_failures": 0,
        "optimizer_policy": "autoencoder_sgd_with_codex_program_synthesis_backlog",
        "program_synthesis_pending": 0,
        "program_synthesis_seeded": 0,
        "queue_path": str(queue_path),
        "run_id": args.run_id,
        "seed": seed,
        "started_at": utc_now(),
        "state_path": str(state_path),
        "test_failures": 0,
        "train_ce_improved_cycles": 0,
        "train_cosine_improved_cycles": 0,
        "validation_ce_improved_cycles": 0,
        "validation_cosine_improved_cycles": 0,
    }


def build_uscode_modal_daemon_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-seconds", type=float, default=3600.0)
    parser.add_argument("--train-count", type=int, default=4)
    parser.add_argument("--validation-count", type=int, default=4)
    parser.add_argument("--max-inner-iterations", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.35)
    parser.add_argument("--test-every-cycles", type=int, default=24)
    parser.add_argument(
        "--warm-start-run-id",
        action="append",
        default=[],
        help="Import feature-level state from a prior run id without sample-specific memory.",
    )
    parser.add_argument(
        "--warm-start-state",
        action="append",
        default=[],
        help="Import feature-level state from a prior state JSON path.",
    )
    return parser


def resolve_warm_start_state_paths(args: argparse.Namespace, queue_dir: Path) -> List[Path]:
    """Resolve explicit warm-start state paths and prior run ids."""
    paths = [Path(path) for path in getattr(args, "warm_start_state", [])]
    paths.extend(
        queue_dir / f"{run_id}.state.json"
        for run_id in getattr(args, "warm_start_run_id", [])
    )
    return paths


def load_warm_start_state(paths: Sequence[Path]) -> tuple[ModalAutoencoderTrainingState, Dict[str, Any]]:
    """Load and average generalizable state from previous runs."""
    loaded_states: List[ModalAutoencoderTrainingState] = []
    loaded_paths: List[str] = []
    missing_paths: List[str] = []
    for path in paths:
        if not path.exists():
            missing_paths.append(str(path))
            continue
        loaded_states.append(ModalAutoencoderTrainingState.load_json(path).generalizable_copy())
        loaded_paths.append(str(path))

    averaged = ModalAutoencoderTrainingState.average_generalizable(loaded_states)
    return averaged, {
        "feature_embedding_weight_entries": len(averaged.feature_embedding_weights),
        "feature_family_logit_entries": len(averaged.feature_family_logits),
        "loaded_paths": loaded_paths,
        "missing_paths": missing_paths,
        "source_count": len(loaded_states),
    }


def run_guarded_uscode_modal_daemon(args: argparse.Namespace) -> int:
    """Run the guarded modal TODO daemon using parsed CLI-style arguments."""

    root = Path.cwd()
    log_dir = root / "workspace" / "test-logs"
    queue_dir = root / "workspace" / "todo-queues"
    report_dir = root / "workspace" / "test-reports" / args.run_id
    log_path = log_dir / f"{args.run_id}.jsonl"
    summary_path = log_dir / f"{args.run_id}.summary"
    queue_path = queue_dir / f"{args.run_id}.jsonl"
    state_path = queue_dir / f"{args.run_id}.state.json"
    run_json_path = queue_dir / f"{args.run_id}.last-run.json"
    log_dir.mkdir(parents=True, exist_ok=True)
    queue_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    stop_requested = False
    stop_signal: int | None = None
    previous_signal_handlers: Dict[int, Any] = {}

    def request_stop(signum: int, frame: Any) -> None:
        nonlocal stop_requested, stop_signal
        stop_requested = True
        stop_signal = signum

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = initial_summary(
            args,
            log_path=log_path,
            queue_path=queue_path,
            state_path=state_path,
        )
        save_summary(summary_path, summary)
    started_at = parse_utc(summary["started_at"])
    end_at = started_at + args.duration_seconds
    state = ModalAutoencoderTrainingState.load_json(state_path)
    warm_start_paths = resolve_warm_start_state_paths(args, queue_dir)
    if warm_start_paths:
        existing_warm_start = dict(summary.get("warm_start", {}))
        if existing_warm_start.get("applied") is True:
            append_event(
                log_path,
                args.run_id,
                {
                    "event": "warm_start_skipped",
                    "reason": "already_applied",
                    "warm_start": existing_warm_start,
                },
            )
        else:
            warm_state, warm_start = load_warm_start_state(warm_start_paths)
            state.merge_generalizable_from(warm_state)
            warm_start["applied"] = True
            summary["warm_start"] = warm_start
            state.save_json(state_path)
            save_summary(summary_path, summary)
            append_event(
                log_path,
                args.run_id,
                {"event": "warm_start_loaded", "warm_start": warm_start},
            )
    queue = ModalTodoQueue.load_jsonl(queue_path)
    autoencoder = AdaptiveModalAutoencoder(
        state=state,
        feature_codec=DeterministicModalLogicCodec(
            ModalLogicCodecConfig(
                parser_backend="spacy",
                spacy_model_name="definitely_missing_legal_model",
                use_flogic=True,
            )
        ),
    )
    supervisor = ModalTodoSupervisor(queue=queue)
    rng = random.Random(int(summary.get("seed", 0)) + int(summary.get("cycles", 0)) + 1)
    blocked_validation_sample_ids = set(state.decoded_embeddings) | set(state.family_logits)

    append_event(log_path, args.run_id, {"event": "detached_runner_started"})
    laws_table = load_laws_table()
    append_event(
        log_path,
        args.run_id,
        {"event": "detached_dataset_loaded", "row_count": laws_table.num_rows},
    )

    try:
        while not stop_requested and time.time() + 8.0 < end_at:
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            (
                train_indices,
                train_samples,
                validation_indices,
                validation_samples,
                validation_sampling_attempts,
            ) = sample_train_validation_rows(
                laws_table,
                rng,
                train_count=args.train_count,
                validation_count=args.validation_count,
                blocked_validation_sample_ids=blocked_validation_sample_ids,
            )
            before_train = autoencoder.evaluate(train_samples)
            before_validation = autoencoder.evaluate(
                validation_samples,
                use_sample_memory=False,
            )
            run = supervisor.optimize(
                train_samples,
                validation_samples=validation_samples,
                autoencoder=autoencoder,
                worker_id="random-uscode-daemon-detached",
                max_items=args.max_items,
                learning_rate=args.learning_rate,
                max_iterations=args.max_inner_iterations,
                target_cross_entropy_loss=0.001,
                target_cosine_similarity=0.999999,
            )
            after_train = run.final_evaluation
            after_validation = run.validation_final_evaluation or autoencoder.evaluate(
                validation_samples,
                use_sample_memory=False,
            )
            blocked_validation_sample_ids.update(sample.sample_id for sample in train_samples)
            queue.save_jsonl(queue_path)
            autoencoder.state.save_json(state_path)
            run.save_json(run_json_path)

            train_ce_delta = before_train.cross_entropy_loss - after_train.cross_entropy_loss
            validation_ce_delta = before_validation.cross_entropy_loss - after_validation.cross_entropy_loss
            train_cos_delta = after_train.embedding_cosine_similarity - before_train.embedding_cosine_similarity
            validation_cos_delta = (
                after_validation.embedding_cosine_similarity
                - before_validation.embedding_cosine_similarity
            )
            summary["cycles"] = cycle
            summary["latest_stop_reason"] = run.stopped_reason
            summary["latest_queue_counts"] = supervisor.queue.status_counts()
            summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
            summary["program_synthesis_pending"] = len(
                supervisor.queue.pending(optimizer_role=supervisor.policy.program_synthesis_role)
            )
            summary["program_synthesis_seeded"] = int(
                summary.get("program_synthesis_seeded", 0)
            ) + sum(step.program_synthesis_seeded_count for step in run.steps)
            summary["train_ce_improved_cycles"] = int(summary.get("train_ce_improved_cycles", 0)) + int(train_ce_delta > 0.0)
            summary["validation_ce_improved_cycles"] = int(summary.get("validation_ce_improved_cycles", 0)) + int(validation_ce_delta > 0.0)
            summary["train_cosine_improved_cycles"] = int(summary.get("train_cosine_improved_cycles", 0)) + int(train_cos_delta > 0.0)
            summary["validation_cosine_improved_cycles"] = int(summary.get("validation_cosine_improved_cycles", 0)) + int(validation_cos_delta > 0.0)
            summary["best_validation_ce"] = min(summary.get("best_validation_ce"), after_validation.cross_entropy_loss)
            summary["best_validation_cosine"] = max(
                summary.get("best_validation_cosine"),
                after_validation.embedding_cosine_similarity,
            )
            summary["best_validation_reconstruction"] = min(
                summary.get("best_validation_reconstruction"),
                after_validation.reconstruction_loss,
            )
            append_event(
                log_path,
                args.run_id,
                {
                    "after_train": metric_block(after_train),
                    "after_validation": metric_block(after_validation),
                    "applied_count": sum(step.applied_count for step in run.steps),
                    "before_train": metric_block(before_train),
                    "before_validation": metric_block(before_validation),
                    "completed_count": sum(step.completed_count for step in run.steps),
                    "cycle": cycle,
                    "duration_seconds": round(time.time() - cycle_started, 3),
                    "event": "cycle",
                    "failed_validation_count": sum(step.failed_validation_count for step in run.steps),
                    "queue_counts": supervisor.queue.status_counts(),
                    "role_queue_counts": supervisor.queue.role_status_counts(),
                    "stopped_reason": run.stopped_reason,
                    "program_synthesis_pending_count": len(
                        supervisor.queue.pending(
                            optimizer_role=supervisor.policy.program_synthesis_role
                        )
                    ),
                    "program_synthesis_seeded_count": sum(
                        step.program_synthesis_seeded_count for step in run.steps
                    ),
                    "train_cosine_delta": round(train_cos_delta, 9),
                    "train_cross_entropy_delta": round(train_ce_delta, 9),
                    "train_indices": train_indices,
                    "validation_sampling_attempts": validation_sampling_attempts,
                    "validation_cosine_delta": round(validation_cos_delta, 9),
                    "validation_cross_entropy_delta": round(validation_ce_delta, 9),
                    "validation_indices": validation_indices,
                },
            )
            save_summary(summary_path, summary)

            if cycle % args.test_every_cycles == 0:
                test_result = run_tests(root, report_dir, cycle)
                summary["test_failures"] = int(summary.get("test_failures", 0)) + int(test_result["exit_code"] != 0)
                append_event(log_path, args.run_id, test_result)
                save_summary(summary_path, summary)
    finally:
        if stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_signal}"
            summary["stopped_by_signal"] = stop_signal
        summary["applied_todo_ids"] = len(autoencoder.state.applied_todo_ids)
        summary["decoded_embedding_entries"] = len(autoencoder.state.decoded_embeddings)
        summary["elapsed_seconds"] = round(time.time() - started_at, 3)
        summary["family_logit_entries"] = len(autoencoder.state.family_logits)
        summary["feature_embedding_weight_entries"] = len(autoencoder.state.feature_embedding_weights)
        summary["feature_family_logit_entries"] = len(autoencoder.state.feature_family_logits)
        summary["finished_at"] = utc_now()
        summary["latest_queue_counts"] = supervisor.queue.status_counts()
        summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
        summary["program_synthesis_pending"] = len(
            supervisor.queue.pending(optimizer_role=supervisor.policy.program_synthesis_role)
        )
        save_summary(summary_path, summary, final=True)
        append_event(log_path, args.run_id, {"event": "run_finished", **summary})
        for signum, handler in previous_signal_handlers.items():
            signal.signal(signum, handler)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_uscode_modal_daemon_arg_parser()
    return run_guarded_uscode_modal_daemon(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
