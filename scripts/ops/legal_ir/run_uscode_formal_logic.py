#!/usr/bin/env python3
"""Process formal-logic U.S. Code spans from the Hugging Face laws parquet.

A sentence is in scope when it carries a deontic, temporal, conditional, or
definition cue. Inference uses the pinned autoencoder without rewriting it.
A failed batch may train a new state file. Compiler gaps become supervisor
todos. Nothing here is a Lake admit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")

DEFAULT_PARQUET = Path(
    "/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/"
    "snapshots/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/uscode_parquet/laws.parquet"
)
DEFAULT_STATE = (
    REPO_ROOT
    / "workspace"
    / "todo-queues"
    / "legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
)
BRIDGE_NAMES = (
    "modal_frame_logic",
    "deontic_norms",
    "fol_tdfol",
    "cec_dcec",
    "external_prover_router",
)


def iter_sections(parquet_path: Path, *, start_row: int = 0) -> Iterator[tuple[int, dict[str, Any]]]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(parquet_path)
    seen = 0
    for batch in parquet.iter_batches(
        batch_size=64,
        columns=["ipfs_cid", "title_number", "section_number", "text"],
    ):
        rows = batch.to_pylist()
        for row in rows:
            if seen >= start_row:
                yield seen, row
            seen += 1


def formal_sentences(row: dict[str, Any]) -> list[str]:
    from ipfs_datasets_py.logic.autoformal.constitution_inventory import _sentences
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import is_formal_logic

    text = " ".join(str(row.get("text") or "").split())
    if not text:
        return []
    sentences = _sentences(text) or [text]
    return [sentence for sentence in sentences if is_formal_logic(sentence) and len(sentence) <= 8000]


def _record_strict(span: dict[str, Any], outcome: dict[str, Any], fresh: list[Any]) -> None:
    if outcome.get("compiler_status") == "repeal":
        span["strict_status"] = "repeal"
        span["strict_reason"] = "repeal_fixture"
        return
    if fresh and all(getattr(row, "status", "") == "roundtrip_ok" for row in fresh):
        span["strict_status"] = "roundtrip_ok"
        span["strict_reason"] = ""
        return
    fields = [str(item) for item in outcome.get("fields") or [] if str(item)]
    span["strict_status"] = "gap"
    if fresh and any(getattr(row, "status", "") == "compiled" for row in fresh):
        span["strict_reason"] = "strict_roundtrip_failed"
    elif fields:
        span["strict_reason"] = "compiler_abstain:" + ",".join(fields)
    else:
        span["strict_reason"] = "compiler_abstain"


def compile_formal(session: Any, row_index: int, row: dict[str, Any], sentence: str, ordinal: int) -> dict[str, Any]:
    from ipfs_datasets_py.logic.autoformal import compile_span
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import normalize_uscode_hit

    document = normalize_uscode_hit(row)
    span_id = f"uscode-{row_index}-{ordinal}"
    span = {
        "canonical_citation": document["canonical_citation"],
        "entry_cid": document["entry_cid"],
        "id": span_id,
        "legal_id": document["legal_id"] or document["entry_cid"],
        "source_span_id": span_id,
        "status": "uncompiled",
        "text": sentence,
        "title": document["title"],
    }
    before = len(session.rows)
    outcome = compile_span(session, sentence, span_id)
    fresh = [
        item for item in session.rows[before:]
        if "-partial" not in str(getattr(item, "document_id", ""))
    ]
    _record_strict(span, outcome, fresh)
    span["compiler_status"] = outcome.get("compiler_status")
    span["decompiled"] = outcome.get("decompiled") or ""
    span["fields"] = list(outcome.get("fields") or [])
    span["rules"] = [
        {
            "action": str(row.rule.get("action") or ""),
            "actor": str(row.rule.get("actor") or ""),
            "modality": str(row.rule.get("modality") or ""),
            "object": str(row.rule.get("object") or ""),
        }
        for row in fresh
        if getattr(row, "status", "") in {"compiled", "roundtrip_ok"} and isinstance(getattr(row, "rule", None), dict)
    ]
    span["admitted"] = False
    span["formalized"] = False
    return span


def evaluate_batch(autoencoder: Any, spans: list[dict[str, Any]]) -> dict[str, Any]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    samples = [
        build_us_code_sample(
            title=str(span.get("title") or "USC"),
            section=str(span.get("source_span_id") or "span"),
            text=str(span.get("text") or ""),
        )
        for span in spans
        if str(span.get("text") or "").strip()
    ]
    if not samples:
        return {"ok": False, "legal_ir_target_count": 0, "sample_count": 0}
    evaluation = autoencoder.evaluate(
        samples,
        legal_ir_bridge_names=BRIDGE_NAMES,
        legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1,
        use_sample_memory=False,
    )
    targets = int(evaluation.legal_ir_target_count or 0)
    views = {
        str(name): float(weight)
        for name, weight in dict(getattr(evaluation, "legal_ir_view_distribution", {}) or {}).items()
    }
    required = ("deontic", "frame_logic", "tdfol", "cec")
    missing = [name for name in required if float(views.get(name) or 0) <= 0]
    rejections = dict(getattr(evaluation, "legal_ir_grammar_rejection_reasons", {}) or {})
    return {
        "admitted": False,
        "formalized": False,
        "grammar_rejections": bool(rejections),
        "legal_ir_target_count": targets,
        "missing_families": missing,
        "ok": targets == len(samples) and targets > 0 and not missing and not rejections,
        "sample_count": len(samples),
        "view_distribution": views,
    }


def train_batch(autoencoder: Any, spans: list[dict[str, Any]], *, max_seconds: float) -> dict[str, Any]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

    samples = [
        build_us_code_sample(
            title=str(span.get("title") or "USC"),
            section=str(span.get("source_span_id") or "span"),
            text=str(span.get("text") or ""),
        )
        for span in spans
        if str(span.get("text") or "").strip()
    ]
    report = autoencoder.train_generalizable_projection(
        samples,
        legal_ir_bridge_names=BRIDGE_NAMES,
        legal_ir_evaluate_provers=False,
        epochs=1,
        max_seconds=max_seconds,
        projection_max_update_families=4,
    )
    accepted = int(getattr(report, "accepted_epochs", 0) or (report.get("accepted_epochs") if isinstance(report, dict) else 0) or 0)
    return {"accepted_epochs": accepted, "trained": True, "admitted": False, "formalized": False}


def note_autoencoder_gaps(batch: list[dict[str, Any]], inferred: dict[str, Any]) -> list[dict[str, Any]]:
    """Mark spans the autoencoder did not convert into the required families.

    A round-trip that the autoencoder does not share becomes a new supervisor
    gap. An already-open gap keeps a training or decompiler reason. Nothing
    here is an admit.
    """

    from ipfs_datasets_py.logic.autoformal.family_supervision import disagreement_reason

    if not batch or inferred.get("ok") is True:
        return []
    projection = {
        "compiler_status": "compiled" if any(item.get("rules") for item in batch) else "abstain",
        "missing_families": [],
    }
    reason = disagreement_reason(projection, inferred, None)
    if reason not in {"inference_still_failing", "capture_not_in_decompilation"}:
        return []
    fresh: list[dict[str, Any]] = []
    for item in batch:
        was_roundtrip = item.get("strict_status") == "roundtrip_ok"
        item["admitted"] = False
        item["formalized"] = False
        if reason == "inference_still_failing":
            if was_roundtrip:
                continue
            item["strict_reason"] = reason
            continue
        if not was_roundtrip:
            continue
        item["strict_status"] = "gap"
        item["strict_reason"] = reason
        fresh.append(item)
    return fresh


def enqueue_gaps(spans: list[dict[str, Any]], *, queue_path: Path, release_id: str) -> dict[str, Any]:
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import attach_goal_tree
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import agreement_from_strict_spans, submit_discrepancies
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import native_agreement_batches, submit_native_discrepancies

    agreement = agreement_from_strict_spans(spans)
    board = queue_path.with_name(queue_path.stem + ".todo.md")
    if not board.exists():
        submit_discrepancies(
            agreement,
            release_id=release_id,
            query="US Code formal logic",
            board_path=board,
        )
    inserted = 0
    with DatabaseTaskSource(queue_path) as source:
        for batch in native_agreement_batches(agreement):
            receipt = submit_native_discrepancies(
                source,
                batch,
                packet_directory=queue_path.parent / (queue_path.stem + "-packets"),
                release_id=release_id,
                code_identity="uscode-formal-compiler",
                model_identity="router-not-yet-called",
                query="US Code formal logic",
            )
            inserted += int(receipt.get("task_count") or 0)
        goals = attach_goal_tree(
            source,
            agreement,
            release_id=release_id,
            campaign_title="US Code formal-logic autoformal campaign",
        )
    return {
        "admitted": False,
        "formalized": False,
        "goal_count": int(goals.get("goal_count") or 0),
        "linked_tasks": int(goals.get("linked_tasks") or 0),
        "router_called": False,
        "subgoal_count": int(goals.get("subgoal_count") or 0),
        "task_count": inserted,
        "wrote_compiler": False,
    }


def load_progress(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"next_row": 0, "formal_sentences": 0, "roundtrip_ok": 0, "gaps": 0, "trained_steps": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path, progress: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(progress, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--train-state", type=Path, default=None)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--spans", type=Path, required=True)
    parser.add_argument("--native-queue", type=Path, default=None)
    parser.add_argument("--release-id", default="uscode-formal-logic")
    parser.add_argument("--limit-rows", type=int, default=0)
    parser.add_argument("--enqueue-every", type=int, default=64)
    parser.add_argument("--train-seconds", type=float, default=30.0)
    parser.add_argument("--skip-autoencoder", action="store_true")
    args = parser.parse_args(argv)
    if not args.parquet.is_file():
        print(f"laws parquet is missing: {args.parquet}")
        return 2
    if args.train_state is not None and args.train_state.resolve() == args.state.resolve():
        print("refusing to overwrite the pinned autoencoder state")
        return 2
    progress = load_progress(args.progress)
    start_row = int(progress.get("next_row") or 0)
    from ipfs_datasets_py.logic.autoformal import AutoformalSession
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        AdaptiveModalAutoencoder,
        ModalAutoencoderTrainingState,
    )

    session = AutoformalSession()
    autoencoder = None
    if not args.skip_autoencoder:
        if not args.state.is_file():
            print(f"autoencoder state is missing: {args.state}")
            return 2
        autoencoder = AdaptiveModalAutoencoder(state=ModalAutoencoderTrainingState.load_json(args.state))
    pending_gaps: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []
    ordinal = int(progress.get("formal_sentences") or 0)
    started = time.monotonic()
    args.spans.parent.mkdir(parents=True, exist_ok=True)
    with args.spans.open("a", encoding="utf-8") as sink:
        for row_index, row in iter_sections(args.parquet, start_row=start_row):
            if args.limit_rows and row_index >= start_row + args.limit_rows:
                break
            for sentence in formal_sentences(row):
                span = compile_formal(session, row_index, row, sentence, ordinal)
                ordinal += 1
                progress["formal_sentences"] = ordinal
                if span.get("strict_status") == "roundtrip_ok":
                    progress["roundtrip_ok"] = int(progress.get("roundtrip_ok") or 0) + 1
                else:
                    progress["gaps"] = int(progress.get("gaps") or 0) + 1
                    pending_gaps.append(span)
                sink.write(json.dumps({
                    "admitted": False,
                    "formalized": False,
                    "source_span_id": span["source_span_id"],
                    "strict_reason": span.get("strict_reason") or "",
                    "strict_status": span.get("strict_status") or "",
                    "text": sentence[:240],
                }, sort_keys=True) + "\n")
                batch.append(span)
                if autoencoder is not None and len(batch) >= 16:
                    inferred = evaluate_batch(autoencoder, batch)
                    progress["last_inference_ok"] = bool(inferred.get("ok"))
                    if not inferred.get("ok") and args.train_state is not None:
                        trained = train_batch(autoencoder, batch, max_seconds=args.train_seconds)
                        progress["trained_steps"] = int(progress.get("trained_steps") or 0) + 1
                        progress["last_training"] = trained
                        autoencoder.state.save_json(args.train_state)
                        inferred = evaluate_batch(autoencoder, batch)
                        progress["last_inference_ok"] = bool(inferred.get("ok"))
                    if not inferred.get("ok"):
                        for item in note_autoencoder_gaps(batch, inferred):
                            progress["roundtrip_ok"] = max(0, int(progress.get("roundtrip_ok") or 0) - 1)
                            progress["gaps"] = int(progress.get("gaps") or 0) + 1
                            pending_gaps.append(item)
                    from ipfs_datasets_py.logic.autoformal.family_supervision import demote_failed_lake
                    from ipfs_datasets_py.logic.autoformal.lake_probe import probe_census_rules

                    rules = [rule for item in batch for rule in item.get("rules") or []]
                    lake = probe_census_rules(rules)
                    progress["last_lake_ok"] = lake.get("lake_ok") is True
                    progress["last_lake_error"] = str(lake.get("error") or "")
                    for item in demote_failed_lake(batch, lake):
                        progress["roundtrip_ok"] = max(0, int(progress.get("roundtrip_ok") or 0) - 1)
                        progress["gaps"] = int(progress.get("gaps") or 0) + 1
                        pending_gaps.append(item)
                    batch.clear()
            progress["next_row"] = row_index + 1
            if row_index % 100 == 0:
                save_progress(args.progress, progress)
                print(
                    f"row {row_index} formal {progress['formal_sentences']} "
                    f"roundtrip {progress.get('roundtrip_ok', 0)} gaps {progress.get('gaps', 0)} "
                    f"elapsed {time.monotonic() - started:.1f}s",
                    flush=True,
                )
        if autoencoder is not None and batch:
            inferred = evaluate_batch(autoencoder, batch)
            progress["last_inference_ok"] = bool(inferred.get("ok"))
        if args.native_queue is not None and pending_gaps:
            progress["supervisor"] = enqueue_gaps(
                pending_gaps, queue_path=args.native_queue, release_id=args.release_id,
            )
    progress["admitted"] = False
    progress["formalized"] = False
    progress["pinned_state_rewritten"] = False
    save_progress(args.progress, progress)
    print(json.dumps({k: progress[k] for k in ("next_row", "formal_sentences", "roundtrip_ok", "gaps", "trained_steps", "admitted", "formalized")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
