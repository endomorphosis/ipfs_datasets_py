"""Quiet random U.S. Code modal daemon runner for workspace experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

sys.path.insert(0, str(Path.cwd()))

import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalTodoQueue,
    ModalTodoSupervisor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyModalCodec,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration-seconds", type=float, default=3600.0)
    parser.add_argument("--train-count", type=int, default=4)
    parser.add_argument("--validation-count", type=int, default=4)
    parser.add_argument("--max-inner-iterations", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.35)
    parser.add_argument("--test-every-cycles", type=int, default=24)
    args = parser.parse_args()

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
    queue = ModalTodoQueue.load_jsonl(queue_path)
    autoencoder = AdaptiveModalAutoencoder(
        state=state,
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        ),
    )
    supervisor = ModalTodoSupervisor(queue=queue)
    rng = random.Random(int(summary.get("seed", 0)) + int(summary.get("cycles", 0)) + 1)

    append_event(log_path, args.run_id, {"event": "detached_runner_started"})
    laws_table = load_laws_table()
    append_event(
        log_path,
        args.run_id,
        {"event": "detached_dataset_loaded", "row_count": laws_table.num_rows},
    )

    try:
        while time.time() + 8.0 < end_at:
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            indices = rng.sample(
                range(laws_table.num_rows),
                args.train_count + args.validation_count,
            )
            selected = laws_table.take(indices).to_pylist()
            train_samples = [row_to_sample(row) for row in selected[: args.train_count]]
            validation_samples = [row_to_sample(row) for row in selected[args.train_count :]]
            before_train = autoencoder.evaluate(train_samples)
            before_validation = autoencoder.evaluate(validation_samples)
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
            after_validation = run.validation_final_evaluation or autoencoder.evaluate(validation_samples)
            queue.save_jsonl(queue_path)
            state.save_json(state_path)
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
                    "stopped_reason": run.stopped_reason,
                    "train_cosine_delta": round(train_cos_delta, 9),
                    "train_cross_entropy_delta": round(train_ce_delta, 9),
                    "train_indices": indices[: args.train_count],
                    "validation_cosine_delta": round(validation_cos_delta, 9),
                    "validation_cross_entropy_delta": round(validation_ce_delta, 9),
                    "validation_indices": indices[args.train_count :],
                },
            )
            save_summary(summary_path, summary)

            if cycle % args.test_every_cycles == 0:
                test_result = run_tests(root, report_dir, cycle)
                summary["test_failures"] = int(summary.get("test_failures", 0)) + int(test_result["exit_code"] != 0)
                append_event(log_path, args.run_id, test_result)
                save_summary(summary_path, summary)
    finally:
        summary["applied_todo_ids"] = len(state.applied_todo_ids)
        summary["decoded_embedding_entries"] = len(state.decoded_embeddings)
        summary["elapsed_seconds"] = round(time.time() - started_at, 3)
        summary["family_logit_entries"] = len(state.family_logits)
        summary["feature_embedding_weight_entries"] = len(state.feature_embedding_weights)
        summary["feature_family_logit_entries"] = len(state.feature_family_logits)
        summary["finished_at"] = utc_now()
        summary["latest_queue_counts"] = supervisor.queue.status_counts()
        save_summary(summary_path, summary, final=True)
        append_event(log_path, args.run_id, {"event": "run_finished", **summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
