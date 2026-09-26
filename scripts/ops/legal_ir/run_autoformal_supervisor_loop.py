#!/usr/bin/env python3
"""Run autoformal, ingest errors as supervisor todos/goals, recurse on new gaps.

A compiled round-trip is not a legal proof. JSONL is not written. Compiler
patches are not imported.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hits", type=Path, default=None)
    parser.add_argument("--query", default="")
    parser.add_argument("--release-id", default="loop-v1")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument(
        "--board",
        type=Path,
        default=REPO_ROOT / "workspace" / "todo-queues" / "uscode-autoformal-loop.todo.md",
    )
    parser.add_argument(
        "--huggingface-package",
        type=Path,
        default=None,
    )
    parser.add_argument("--pointer", type=Path, default=None)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--accelerate-root", type=Path, default=None)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--population-out", type=Path, default=None)
    parser.add_argument("--population-in", type=Path, default=None)
    parser.add_argument("--schedule-queue", type=Path, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument(
        "--recensus",
        action="store_true",
        help="Re-run the compiler on open todos from --population-in. Does not claim.",
    )
    parser.add_argument("--job-template", type=Path, default=None)
    parser.add_argument("--model-identity", default="sha256:loop-census-unbound")
    args = parser.parse_args(argv)
    if args.recensus:
        if args.population_in is None:
            print("recensus requires --population-in")
            return 2
    elif args.hits is None:
        print("provide --hits, or --recensus with --population-in")
        return 2
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
        census_snapshot_path,
        load_population_receipt,
        loop_progress_report,
        progress_log_path,
        run_supervisor_loop,
        write_census_snapshot,
        write_population_receipt,
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_uscode_on_sparse_graphrag",
        Path(__file__).with_name("run_uscode_on_sparse_graphrag.py"),
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    retrieve_count = {"n": 0}

    def autoformal():
        retrieve_count["n"] += 1
        if args.recensus:
            if prior is None:
                raise SystemExit("recensus requires --population-in")
            from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
            from ipfs_datasets_py.logic.autoformal.supervisor_loop import recensus_open_todos

            session = AutoformalSession()
            tick = recensus_open_todos(
                prior,
                lambda text, _session=session: compile_span(_session, text, "recensus"),
            )
            return {"rows": tick["agreement"]["rows"]}
        if retrieve_count["n"] > 1:
            return {"spans": []}
        receipt = runner.run_uscode_autoformal(
            hits_path=args.hits,
            query=args.query,
            release_id=args.release_id,
            skip_upload=True,
        )
        return {"spans": list(receipt.get("spans") or [])}

    upload = None
    if not args.skip_upload and args.huggingface_package is not None:
        from ipfs_datasets_py.huggingface.autoformal_todo import upload_autoformal_todos

        def upload(tasks, _root=args.huggingface_package, _pointer=args.pointer):
            return upload_autoformal_todos(tasks, _root, pointer_path=_pointer, dry_run=True)

    if args.population_in is None and (args.board.exists() or args.board.is_symlink()):
        print(f"board already exists; choose a new --board path: {args.board}")
        return 2
    prior = None
    if args.population_in is not None:
        prior = load_population_receipt(args.population_in)
    source = None
    if args.database is not None:
        if args.accelerate_root is None:
            print("native DuckDB ingest requires --accelerate-root")
            return 2
        spec_pin = importlib.util.spec_from_file_location(
            "autoformal_supervisor_pin",
            Path(__file__).with_name("run_autoformal_supervisor.py"),
        )
        helper = importlib.util.module_from_spec(spec_pin)
        spec_pin.loader.exec_module(helper)
        helper.pin_accelerate(args.accelerate_root)
        from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import (
            DatabaseTaskSource,
        )

        args.database.parent.mkdir(parents=True, exist_ok=True)
        source = DatabaseTaskSource(args.database)
    _session = {"value": None}

    def compile_one(text: str) -> dict:
        from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

        if _session["value"] is None:
            _session["value"] = AutoformalSession()
        return compile_span(_session["value"], text, "loop-recensus")

    dispatch = {
        "packet_directory": args.board.parent / "packets",
        "model_identity": args.model_identity or "sha256:loop-census-unbound",
        "database": args.database,
        "runtime_root": args.board.parent,
        "release_id": args.release_id,
        "query": args.query,
    }
    if args.job_template is not None:
        dispatch["job_template"] = args.job_template

    def _lake_probe(rules):
        from ipfs_datasets_py.logic.autoformal.lake_probe import probe_census_rules

        return probe_census_rules(rules)

    def _lake_check(source: str):
        from ipfs_datasets_py.logic.autoformal.lake_probe import lake_check

        return lake_check(source)

    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, compiler_path_hashes

    cache_path = (args.board.parent / "autoformal-span-cache.duckdb") if args.board else Path("autoformal-span-cache.duckdb")
    span_cache = SpanCache(cache_path)
    path_hashes = compiler_path_hashes(REPO_ROOT)
    if args.accelerate_root is not None:
        dispatch["accelerate_root"] = args.accelerate_root
        spec_pin = importlib.util.spec_from_file_location(
            "autoformal_supervisor_pin_dispatch",
            Path(__file__).with_name("run_autoformal_supervisor.py"),
        )
        helper = importlib.util.module_from_spec(spec_pin)
        spec_pin.loader.exec_module(helper)
        helper.pin_accelerate(args.accelerate_root)
        dispatch["code_identity"] = helper.code_identity()
    receipt = None
    try:
        receipt = run_supervisor_loop(
            autoformal,
            max_rounds=args.max_rounds,
            query=args.query,
            release_id=args.release_id,
            board_path=args.board,
            upload=upload,
            source=source,
            prior=prior,
            log=lambda line: print(line, flush=True),
            compile_one=compile_one,
            dispatch=dispatch,
            lake_probe=_lake_probe,
            lean_check=_lake_check,
            span_cache=span_cache,
            path_hashes=path_hashes,
        )
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
        flush = None
        try:
            if span_cache.stats()["sealed"]:
                from ipfs_datasets_py.huggingface.autoformal_span_cache import flush_span_cache

                flush = flush_span_cache(
                    span_cache.sealed_rows(),
                    args.board.parent / "span-cache-hf" if args.board else Path("span-cache-hf"),
                    dry_run=True,
                )
                span_cache.mark_flushed()
        finally:
            span_cache.close()
    if receipt is None:
        return 1
    last = (receipt.get("rounds") or [{}])[-1]
    native = dict(last.get("native_population") or {})
    population_path = args.population_out
    if population_path is None and args.board is not None:
        population_path = args.board.with_name(args.board.stem + ".population.json")
    if population_path is not None:
        write_population_receipt(population_path, receipt)
    census_path = census_snapshot_path(args.board)
    if census_path is not None:
        write_census_snapshot(census_path, receipt)
    log_path = progress_log_path(args.board)
    scheduled = {}
    pointer = Path(
        ((receipt.get("huggingface") or {}).get("pointer") or {}).get("pointer_path")
        or args.pointer
        or ""
    )
    if args.schedule_queue is not None:
        if not pointer.is_file():
            print("schedule-queue requires a Hugging Face pointer; omit --skip-upload")
            return 2
        from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer

        scheduled = schedule_from_pointer(
            pointer,
            repo_root=REPO_ROOT,
            board=args.board,
            queue_path=args.schedule_queue,
            package_root=args.huggingface_package,
            max_tokens=args.max_tokens,
        )
    print(
        json.dumps(
            {
                "admitted": False,
                "formalized": False,
                "jsonl_written": False,
                "proof_count": receipt["proof_count"],
                "round_count": receipt["round_count"],
                "stop_reason": receipt["stop_reason"],
                "todo_count": receipt["todo_count"],
                "compiled_count": receipt.get("compiled_count"),
                "remaining_count": receipt.get("remaining_count"),
                "compiled_span_ids": receipt.get("compiled_span_ids") or [],
                "remaining_span_ids": receipt.get("remaining_span_ids") or [],
                "open_goal_count": receipt.get("open_goal_count"),
                "goal_count": last.get("goal_count"),
                "native_goal_count": native.get("goal_count"),
                "native_task_count": native.get("task_count"),
                "population_path": str(population_path or ""),
                "census_path": str(census_path or ""),
                "progress_log_path": str(log_path or ""),
                "progress": loop_progress_report(receipt),
                "lake": dict(receipt.get("lake") or last.get("lake") or {}),
                "census_spans": list(receipt.get("census_spans") or last.get("census_spans") or []),
                "span_cache": dict(receipt.get("span_cache") or last.get("span_cache") or {}),
                "span_cache_path": str(cache_path),
                "span_cache_flush": flush or {"jsonl_written": False, "uploaded": False, "dry_run": True},
                "huggingface_uploaded": bool(receipt.get("huggingface")),
                "scheduled_task_ids": list(scheduled.get("scheduled_task_ids") or []),
                "wrote_compiler": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
