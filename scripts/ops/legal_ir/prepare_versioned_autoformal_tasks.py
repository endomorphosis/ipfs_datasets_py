#!/usr/bin/env python3
"""Append explicitly versioned native tasks; never replace existing evidence.

Run inside the qualified candidate repository. Expected extension IR is an
operator-reviewed JSON fixture, not a model answer. Dry run is the default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--parent-task-id", required=True)
    parser.add_argument("--extension-family", choices=("policy", "definition"), required=True)
    parser.add_argument("--expected-ir", type=Path, required=True)
    parser.add_argument("--preserve-family", action="append", choices=("policy", "definition"), default=[])
    parser.add_argument("--include-baseline-repairs", action="store_true")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--huggingface-package", type=Path, default=None)
    parser.add_argument("--pointer", type=Path, default=None)
    parser.add_argument("--board", type=Path, default=None)
    parser.add_argument("--schedule-queue", type=Path, default=None)
    args = parser.parse_args(argv)
    from run_autoformal_supervisor import pin_accelerate, validated_task_id, require_native_transition_contract
    from run_autoformal_feedback_loop import repository_preflight
    validated_task_id(args.parent_task_id)
    binding = pin_accelerate(args.accelerate_root)
    require_native_transition_contract()
    repository_preflight(ROOT)
    runtime = args.runtime_root.resolve(strict=True)
    database = args.database.resolve(strict=True)
    if not ROOT.is_relative_to(runtime) or not database.is_relative_to(runtime) or args.database.is_symlink():
        parser.error("use the owned runtime and a qualified private candidate")
    if args.receipt.exists() or args.receipt.is_symlink() or not args.receipt.resolve().is_relative_to(runtime):
        parser.error("receipt must be a new file inside the retained runtime")
    if (args.expected_ir.is_symlink() or not args.expected_ir.is_file()
            or args.expected_ir.absolute() != args.expected_ir.resolve(strict=True)
            or args.expected_ir.stat().st_size > 512 * 1024):
        parser.error("expected IR must be bounded regular evidence")
    expected_bytes = args.expected_ir.read_bytes()
    expected = json.loads(expected_bytes)
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.feedback_cycle import exclusive_loop, check_storage, queue_observation, PhaseJournal
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import read_packet, canonical_bytes, enqueue_repairs, NAMESPACE
    from ipfs_datasets_py.logic.autoformal.extended_repair import extension_packet, baseline_packet
    from ipfs_datasets_py.logic.autoformal.autoencoder_router import agreement_census
    from ipfs_datasets_py.logic.autoformal.repair_intake import review_flags
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    with exclusive_loop(runtime):
        check_storage(runtime, 50_000_000_000, reserve=1_000_000_000)
        journal = PhaseJournal(runtime / "feedback-loop.duckdb")
        try:
            journal.require_no_interrupted_phase()
        finally:
            journal.close()
        with DatabaseTaskSource(database, install_schema=False) as source:
            before = queue_observation(source)
            records, cursor = [], ""
            while True:
                page = source.list_tasks(cursor=cursor, limit=100)
                records.extend(page.tasks)
                if page.revision != before["revision"] or len(records) > 1000:
                    raise ValueError("queue inventory changed or exceeds bound")
                cursor = page.next_cursor
                if not cursor:
                    break
            selected = [row for row in records if row.task_alias == args.parent_task_id]
            if len(selected) != 1 or selected[0].body.get("board_namespace") != NAMESPACE:
                raise ValueError("parent is missing, ambiguous, or outside the repair namespace")
            parent = selected[0]
            parent_packet = read_packet(Path(parent.body["packet_path"]), parent.body["packet_sha256"])
            if review_flags(parent_packet):
                raise ValueError("parent source requires review/hydration before extension")
            items = [extension_packet(parent_packet, parent.body["packet_sha256"], code_identity=head,
                                      family=args.extension_family, expected_ir=expected,
                                      preserve_families=tuple(args.preserve_family))]
            baseline_origins, seen = [], set()
            if args.include_baseline_repairs:
                ready = source.ready_tasks(limit=1000)
                for record in sorted(ready.tasks, key=lambda row: row.task_cid):
                    packet = read_packet(Path(record.body["packet_path"]), record.body["packet_sha256"])
                    if "extension" in packet or "revision" in packet or review_flags(packet):
                        continue
                    old = [packet["row"], *packet["preserve_rows"]]
                    census = agreement_census([{**row, "id": row["source_span_id"], "status": "operative"} for row in old],
                        {"ok": True, "captures": [{**row["capture"], "sample_id": row["source_span_id"]} for row in old]})
                    for index, row in enumerate(census["rows"]):
                        # Unsupported top-level families need their own reviewed
                        # extension fixture. Baseline losses and renderer-only
                        # failures may receive joint compiler/decompiler scopes.
                        if row["agrees"] or row["skipped"] or (index == 0 and row["reason"].startswith("compiler_abstain")):
                            continue
                        identity = hashlib.sha256(canonical_bytes([old[index]["text_sha256"], old[index]["capture"]])).hexdigest()
                        baseline_origins.append({"source_span_id": row["id"], "parent_task_cid": record.task_cid,
                                                 "observation_identity": identity, "duplicate": identity in seen})
                        if identity in seen:
                            continue
                        seen.add(identity)
                        items.append(baseline_packet(packet, record.body["packet_sha256"], census=census,
                                                     source_span_id=row["id"], code_identity=head))
            if source.snapshot().revision != before["revision"]:
                raise ValueError("queue changed while preparing new scopes")
            if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != head:
                raise ValueError("candidate changed during task preparation")
            if args.expected_ir.read_bytes() != expected_bytes:
                raise ValueError("operator expected IR changed during task preparation")
            prepared = [{"task_id": item["task"]["task_id"], "packet_sha256": item["sha256"],
                         "reason": item["packet"]["row"]["reason"], "source_span_id": item["packet"]["row"]["source_span_id"],
                         "preserve_row_count": len(item["packet"]["preserve_rows"])} for item in items]
            result = enqueue_repairs(source, items, packet_directory=runtime / "packets") if args.apply else None
            for record in records:
                if source.get(record.task_cid) != record:
                    raise ValueError("existing task changed; do not continue dispatch")
            after = queue_observation(source)
            report = {"schema": "autoformal-versioned-task-preparation/v2", **binding, "apply": args.apply,
                      "candidate_head": head, "queue_before": before, "queue_after": after,
                      "expected_ir_sha256": hashlib.sha256(expected_bytes).hexdigest(),
                      "prepared": prepared, "baseline_origins": baseline_origins, "enqueue": result,
                      "existing_tasks_unchanged": True, "parent_tasks_completed": False,
                      "provider_dispatched": False, "admitted": False, "formalized": False,
                      "published": False, "huggingface_packaged": False, "jsonl_written": False}
            if args.huggingface_package is not None:
                from ipfs_datasets_py.huggingface.autoformal_todo import publish_repair_item_todos
                from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer

                huggingface = publish_repair_item_todos(
                    items,
                    args.huggingface_package,
                    board_path=args.board,
                    pointer_path=args.pointer,
                    release_id=args.parent_task_id,
                    dry_run=True,
                )
                report["huggingface_packaged"] = True
                report["huggingface"] = {
                    "dry_run": True,
                    "jsonl_written": False,
                    "locator": huggingface.get("locator") or {},
                    "task_count": huggingface.get("task_count") or 0,
                    "board_path": huggingface.get("board_path") or "",
                }
                if args.schedule_queue is not None:
                    pointer = Path(
                        ((huggingface.get("pointer") or {}).get("pointer_path") or args.pointer or "")
                    )
                    report["huggingface"]["scheduled"] = schedule_from_pointer(
                        pointer,
                        repo_root=ROOT,
                        board=args.board or pointer.with_name("versioned.todo.md"),
                        queue_path=args.schedule_queue,
                        package_root=args.huggingface_package,
                    )
            with args.receipt.open("x") as stream:
                json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write("\n")
    print(json.dumps({"apply": args.apply, "prepared_count": len(prepared), "extension_task": prepared[0]["task_id"],
                      "queue_after": after, "existing_tasks_unchanged": True, "receipt": str(args.receipt)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
