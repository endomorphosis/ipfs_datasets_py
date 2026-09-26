#!/usr/bin/env python3
"""Run the Constitution text through the compiler and one daemon checkpoint.

Writes a receipt. Does not mark a span roundtrip_ok, does not set the
ledger formalized, and does not admit Lean. A compiled row is only a
deontic compile, not a proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")

CONSTITUTION = (
    Path("/home/barberb/lift_coding/JevOps/.improve-watch/us-constitution/constitution.txt")
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


def enqueue_native_gaps(agreement: dict[str, Any], *, queue_path: Path, release_id: str) -> dict[str, Any]:
    """Insert strict gaps into the accelerate DuckDB queue. Does not call llm_router."""

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import (
        native_agreement_batches,
        submit_native_discrepancies,
    )

    batches = native_agreement_batches(agreement)
    inserted = 0
    receipts = []
    with DatabaseTaskSource(queue_path) as source:
        for batch in batches:
            receipt = submit_native_discrepancies(
                source,
                batch,
                packet_directory=queue_path.parent / (queue_path.stem + "-packets"),
                release_id=release_id,
                code_identity="constitution-strict-compiler",
                model_identity="router-not-yet-called",
                query="US Constitution",
            )
            inserted += int(receipt.get("task_count") or 0)
            receipts.append({
                "task_count": int(receipt.get("task_count") or 0),
                "authority": receipt.get("authority") or "",
                "jsonl_written": False,
                "wrote_compiler": False,
                "admitted": False,
                "formalized": False,
                "router_called": False,
            })
        from ipfs_datasets_py.logic.autoformal.supervisor_loop import attach_goal_tree

        goals = attach_goal_tree(
            source,
            agreement,
            release_id=release_id,
            campaign_title="US Constitution autoformal campaign",
        )
    return {
        "admitted": False,
        "authority": "accelerate-duckdb",
        "batches": receipts,
        "formalized": False,
        "jsonl_written": False,
        "goal_count": int(goals.get("goal_count") or 0),
        "linked_tasks": int(goals.get("linked_tasks") or 0),
        "router_called": False,
        "subgoal_count": int(goals.get("subgoal_count") or 0),
        "task_count": inserted,
        "wrote_compiler": False,
    }


def schedule_packaged_todos(pointer: Path, **kwargs: Any) -> dict[str, Any]:
    """Register a packaged Hugging Face todo release on the accelerate queue."""

    from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer

    return schedule_from_pointer(pointer, **kwargs)


def _record_strict_status(span: dict[str, Any], outcome: dict[str, Any], fresh: list[Any]) -> None:
    """Record compiler observations without granting a Constitution success status."""

    span["compiler_roundtrip_observed"] = False
    if outcome.get("compiler_status") == "repeal":
        span["strict_status"] = "repeal"
        span["strict_reason"] = "repeal_fixture"
        return
    if fresh and all(getattr(row, "status", "") == "roundtrip_ok" for row in fresh):
        span["strict_status"] = "compiled"
        span["strict_reason"] = "compiler_roundtrip_observation_only"
        span["compiler_roundtrip_observed"] = True
        return
    fields = [str(item) for item in outcome.get("fields") or [] if str(item)]
    if fresh and any(getattr(row, "status", "") == "compiled" for row in fresh):
        span["strict_status"] = "gap"
        span["strict_reason"] = "strict_roundtrip_failed"
        return
    span["strict_status"] = "gap"
    span["strict_reason"] = ("compiler_abstain:" + ",".join(fields)) if fields else "compiler_abstain"


def summarize_spans(spans: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(str(span.get("status") or "") for span in spans)
    return {
        "span_count": len(spans),
        "status_counts": dict(status),
        "compiled_count": int(status.get("compiled", 0)),
        # Legacy labels remain visible in the raw status census, but cannot
        # grant Constitution success through either compatibility counter.
        "roundtrip_ok_count": 0,
        "strict_roundtrip_ok_count": 0,
        "compiler_roundtrip_observed_count": sum(
            1 for span in spans if span.get("compiler_roundtrip_observed") is True
        ),
        "formalized": False,
        "admitted": False,
    }


def compile_constitution(text: str) -> dict[str, Any]:
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.constitution_inventory import (
        census_ledger,
        inventory_constitution,
        tag_facets,
    )

    ledger = inventory_constitution(text)
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ledger["source_sha256"] = source_sha256
    ledger["span_identity_schema"] = "constitution-source-span-v1"
    for ordinal, span in enumerate(ledger["spans"]):
        identity = {
            "schema_version": ledger["span_identity_schema"],
            "source_sha256": source_sha256,
            "structural_span_id": span["id"],
            "ordinal": ordinal,
            "text_sha256": hashlib.sha256(str(span["text"]).encode("utf-8")).hexdigest(),
        }
        digest = hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")).hexdigest()
        span["source_span_id"] = f"constitution-span-{digest}"
        span["span_text_sha256"] = identity["text_sha256"]
    pending = iter(span for span in ledger["spans"] if span["status"] == "uncompiled")
    session = AutoformalSession()

    def one(span_text: str) -> dict[str, Any]:
        # census_ledger invokes this callback once for each uncompiled span in
        # ledger order. Include source identity and ordinal even when text is
        # repeated, so the session cannot reuse another span's atom vocabulary.
        span = next(pending)
        if span_text != span["text"]:
            raise ValueError("Constitution census callback order changed")
        span["compiler_document_id"] = span["source_span_id"]
        before = len(session.rows)
        outcome = compile_span(session, span_text, span["compiler_document_id"])
        fresh = [
            row for row in session.rows[before:]
            if "-partial" not in str(getattr(row, "document_id", ""))
        ]
        _record_strict_status(span, outcome, fresh)
        return outcome

    census = census_ledger(ledger, one)
    tag_facets(census["ledger"])
    for span in census["ledger"]["spans"]:
        if span.get("status") == "roundtrip_ok":
            span["status"] = "compiled"
    return census


def _samples(spans: list[dict[str, Any]]) -> list[Any]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
        build_us_code_sample,
    )

    samples = []
    for span in spans:
        text = str(span.get("text") or "").strip()
        if not text:
            continue
        samples.append(
            build_us_code_sample(
                title="US-CONST",
                section=str(span.get("id") or "span"),
                text=text,
            )
        )
    return samples


def evaluate_spans(state_path: Path, spans: list[dict[str, Any]], *, batch_size: int) -> dict[str, Any]:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        AdaptiveModalAutoencoder,
        ModalAutoencoderTrainingState,
    )

    state = ModalAutoencoderTrainingState.load_json(state_path)
    autoencoder = AdaptiveModalAutoencoder(state=state)
    samples = _samples(spans)
    target_count = 0
    losses: dict[str, float] = {}
    batches = 0
    for start in range(0, len(samples), batch_size):
        batch = samples[start : start + batch_size]
        evaluation = autoencoder.evaluate(
            batch,
            legal_ir_bridge_names=BRIDGE_NAMES,
            legal_ir_evaluate_provers=False,
            legal_ir_parallel_workers=1,
            use_sample_memory=False,
        )
        target_count += int(evaluation.legal_ir_target_count or 0)
        for name, value in dict(evaluation.legal_ir_losses or {}).items():
            losses[str(name)] = losses.get(str(name), 0.0) + float(value)
        batches += 1
        print(
            f"batch {batches} samples {start + len(batch)}/{len(samples)} "
            f"targets {target_count}",
            flush=True,
        )
    return {
        "batch_size": batch_size,
        "batches": batches,
        "bridge_names": list(BRIDGE_NAMES),
        "legal_ir_losses_sum": losses,
        "legal_ir_target_count": target_count,
        "sample_count": len(samples),
        "state_path": str(state_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constitution", type=Path, default=CONSTITUTION)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "constitution-on-restart12.json",
    )
    parser.add_argument("--compiler-only", action="store_true")
    parser.add_argument(
        "--evaluate-autoencoder",
        action="store_true",
        help="Run the autoencoder checkpoint. Discrepancies still go to the supervisor, not a compiler patch.",
    )
    parser.add_argument("--skip-supervisor", action="store_true")
    parser.add_argument("--board", type=Path, default=None)
    parser.add_argument("--huggingface-package", type=Path, default=None)
    parser.add_argument("--pointer", type=Path, default=None)
    parser.add_argument("--release-id", default="us-constitution")
    parser.add_argument("--schedule-queue", type=Path, default=None)
    parser.add_argument(
        "--native-queue",
        type=Path,
        default=None,
        help="DuckDB task queue for the accelerate supervisor. Does not call llm_router.",
    )
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-validation-seconds", type=int, default=None)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        print(f"receipt already exists; choose a new --output path: {args.output}")
        return 2
    source = args.constitution
    if not source.is_file():
        print(f"constitution text is missing: {source}")
        return 2
    evaluate_autoencoder = bool(args.evaluate_autoencoder) and not args.compiler_only
    state_path = args.state.resolve()
    if evaluate_autoencoder and (not state_path.is_file() or state_path.stat().st_size <= 0):
        print(f"daemon state is missing: {state_path}")
        return 2
    board_path = args.board
    if board_path is None and not args.skip_supervisor:
        board_path = args.output.with_name(args.output.stem + ".todo.md")
    if board_path is not None and (board_path.exists() or board_path.is_symlink()):
        print(f"board already exists; choose a new --board path: {board_path}")
        return 2
    started = time.monotonic()
    # Decode exact UTF-8 bytes without universal-newline rewriting; the source
    # digest identifies these bytes, including the original line endings.
    census = compile_constitution(source.read_bytes().decode("utf-8"))
    ledger = census["ledger"]
    summary = summarize_spans(ledger["spans"])
    print(
        f"compiler spans {summary['span_count']} compiled {summary['compiled_count']} "
        f"elapsed {time.monotonic() - started:.1f}s",
        flush=True,
    )
    bridge: dict[str, Any] = {}
    if evaluate_autoencoder:
        bridge = evaluate_spans(state_path, ledger["spans"], batch_size=max(1, args.batch_size))
    supervisor: dict[str, Any] = {}
    if not args.skip_supervisor:
        from ipfs_datasets_py.logic.autoformal.supervisor_todo import (
            agreement_from_strict_spans,
            submit_discrepancies,
        )

        agreement = agreement_from_strict_spans(ledger["spans"])
        upload = None
        if args.huggingface_package is not None and not agreement.get("agrees"):
            from ipfs_datasets_py.huggingface.autoformal_todo import upload_autoformal_todos

            def upload(tasks, _root=args.huggingface_package, _pointer=args.pointer):
                return upload_autoformal_todos(tasks, _root, pointer_path=_pointer, dry_run=True)

        supervisor = submit_discrepancies(
            agreement,
            board_path=None if agreement.get("agrees") else board_path,
            query="US Constitution",
            release_id=args.release_id,
            upload=upload,
        )
        if args.schedule_queue is not None:
            pointer = Path(
                ((supervisor.get("huggingface") or {}).get("pointer") or {}).get("pointer_path")
                or args.pointer
                or ""
            )
            if args.huggingface_package is None or not pointer.is_file():
                print("schedule-queue requires a Hugging Face pointer; pass --huggingface-package")
                return 2
            supervisor["scheduled"] = schedule_packaged_todos(
                pointer,
                repo_root=REPO_ROOT,
                board=board_path or pointer.with_name("constitution.todo.md"),
                queue_path=args.schedule_queue,
                package_root=args.huggingface_package,
                max_tokens=args.max_tokens,
                max_validation_seconds=args.max_validation_seconds,
            )
        if args.native_queue is not None and not agreement.get("agrees"):
            supervisor["native_queue"] = enqueue_native_gaps(
                agreement,
                queue_path=args.native_queue,
                release_id=args.release_id,
            )
    receipt = {
        "admitted": False,
        "bridge": bridge,
        "census_stopped": bool(census.get("stopped")),
        "census_error": str(census.get("error") or ""),
        "formalized": False,
        "optimizer_step": False,
        "roundtrip_ok_count": summary["roundtrip_ok_count"],
        "strict_roundtrip_ok_count": summary["strict_roundtrip_ok_count"],
        "compiler_roundtrip_observed_count": summary["compiler_roundtrip_observed_count"],
        "source": str(source),
        "source_sha256": ledger["source_sha256"],
        "span_identity_schema": ledger["span_identity_schema"],
        "summary": summary,
        "facet_counts": dict(ledger.get("facet_counts") or {}),
        "jsonl_written": False,
        "supervisor": {
            "task_count": int(supervisor.get("task_count") or 0),
            "board_path": supervisor.get("board_path") or "",
            "wrote_compiler": False,
            "jsonl_written": False,
            "router_called": False,
            "native_task_count": int((supervisor.get("native_queue") or {}).get("task_count") or 0),
            "scheduled": supervisor.get("scheduled") or {},
        },
    }
    # Keep span rows, but do not call any of them a proof.
    receipt["spans"] = [
        {
            "id": span.get("id"),
            "source_span_id": span.get("source_span_id"),
            "span_text_sha256": span.get("span_text_sha256"),
            "compiler_document_id": span.get("compiler_document_id"),
            "status": span.get("status"),
            "strict_status": span.get("strict_status") or "",
            "strict_reason": span.get("strict_reason") or "",
            "compiler_roundtrip_observed": span.get("compiler_roundtrip_observed") is True,
            "reason": span.get("reason"),
            "facet": span.get("facet"),
            "decompiled": span.get("decompiled") or "",
        }
        for span in ledger["spans"]
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        f"formalized=false compiled={summary['compiled_count']} "
        f"targets={bridge.get('legal_ir_target_count', 'compiler_only')} "
        f"supervisor_tasks={int(supervisor.get('task_count') or 0)} "
        f"jsonl_written=false output={args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
