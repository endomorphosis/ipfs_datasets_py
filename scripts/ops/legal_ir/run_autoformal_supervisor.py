#!/usr/bin/env python3
"""Feed and run the native accelerate DuckDB repair supervisor.

Use an explicit accelerate checkout: ambient editable installs may resolve a
different migration catalog. No HF publication, model download or synthetic
task completion is performed by this entry point.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[3]
PROTECTED = (
    "ipfs_datasets_py/logic/autoformal/feedback_cycle.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_queue.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_todo.py",
    "ipfs_datasets_py/logic/autoformal/autoencoder_router.py",
    "ipfs_datasets_py/logic/autoformal/validator_profile.py",
    "ipfs_datasets_py/logic/autoformal/repair_intake.py",
    "ipfs_datasets_py/logic/autoformal/repair_context.py",
    "ipfs_datasets_py/logic/autoformal/learned_feedback.py",
    "ipfs_datasets_py/logic/autoformal/training_cycle_inputs.py",
    "ipfs_datasets_py/logic/autoformal/extended_repair.py",
    "ipfs_datasets_py/logic/legal_ir/extended_contracts.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/autoformal/uscode_ingest.py",
    "scripts/ops/legal_ir/run_autoformal_supervisor.py",
    "scripts/ops/legal_ir/run_autoformal_training_cycle.py",
    "scripts/ops/legal_ir/run_autoformal_feedback_loop.py",
    "scripts/ops/legal_ir/validate_autoformal_repair.py",
    "scripts/ops/legal_ir/prepare_autoformal_repair_repository.py",
    "scripts/ops/legal_ir/prepare_autoformal_dependency.py",
    "scripts/ops/legal_ir/prepare_autoformal_validator_profile.py",
    "scripts/ops/legal_ir/prepare_autoformal_repair_context.py",
    "scripts/ops/legal_ir/prepare_versioned_autoformal_tasks.py",
    "tests/unit/logic/test_supervisor_queue.py",
    "tests/unit/logic/test_supervisor_todo.py",
    "tests/unit/logic/test_autoformal_supervisor_launch.py",
    "tests/unit/logic/test_autoformal_feedback_cycle.py",
    "tests/unit/logic/test_autoformal_training_cycle.py",
    "tests/unit/logic/test_autoformal_validator_profile.py",
    "tests/unit/logic/test_autoformal_repair_intake.py",
    "tests/unit/logic/test_autoformal_repair_context.py",
    "tests/unit/logic/test_autoformal_learned_feedback.py",
    "tests/unit/logic/test_autoformal_campaign_training_inputs.py",
    "tests/unit/logic/test_autoformal_campaign_learned_feedback.py",
    "tests/unit/logic/test_autoencoder_router.py",
    "tests/unit/logic/test_autoformal.py",
    "tests/unit/logic/test_uscode_ingest.py",
    "tests/unit/logic/legal_ir/test_canonical_decompiler.py",
    "docs/implementation/plans/US_CODE_AUTOFORMALIZATION_PLAN.md",
)


def pin_accelerate(root: Path) -> dict[str, str]:
    root = root.resolve(strict=True)
    expected = root / "ipfs_accelerate_py" / "__init__.py"
    if not expected.is_file():
        raise ValueError("accelerate root must contain ipfs_accelerate_py/__init__.py")
    loaded = sys.modules.get("ipfs_accelerate_py")
    if loaded is not None and Path(loaded.__file__).resolve() != expected.resolve():
        raise ValueError("a different accelerate checkout is already imported")
    sys.path.insert(0, str(root))
    module = importlib.import_module("ipfs_accelerate_py")
    if Path(module.__file__).resolve() != expected.resolve():
        raise ValueError("accelerate checkout pin did not hold")
    sys.path.insert(0, str(ROOT))
    # Child interpreter selection remains explicit even if launched from a
    # datasets checkout containing another package with the same name.
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (str(root), str(ROOT), existing)))
    return {"accelerate_root": str(root), "accelerate_module": str(expected)}


def code_identity(root: Path = ROOT) -> str:
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import EDIT_SCOPES, canonical_bytes
    paths = sorted({path for scope in EDIT_SCOPES.values() for path in scope})
    hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    return "sha256:" + hashlib.sha256(canonical_bytes(hashes)).hexdigest()


def require_native_transition_contract(intent_class=None, source_class=None) -> None:
    """Check the native claim CAS call before opening execution/claim stores.

    Never adapt by dropping expected_control_receipt: it is an authority guard,
    not an optional convenience argument. Queue CRUD alone doesn't qualify a
    dependency for real autonomous execution.
    """
    if intent_class is None:
        from ipfs_accelerate_py.agent_supervisor.task_sources.intent_repository import IntentRepository
        intent_class = IntentRepository
    if source_class is None:
        from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
        source_class = DatabaseTaskSource
    # Validate the actual native call, not an assumed API revision. Older
    # matching caller/callee pairs use revision+receipt fencing without the
    # later expected_control_receipt argument. Do not monkey-patch either
    # implementation or drop any keyword that the selected caller forwards.
    tree = ast.parse(textwrap.dedent(inspect.getsource(source_class.compare_and_set_status)))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "cas_task_status"
             and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "_intent"]
    if len(calls) != 1 or calls[0].args or any(key.arg is None for key in calls[0].keywords):
        raise RuntimeError("cannot qualify the native transition call statically; no work will be claimed")
    names = {key.arg for key in calls[0].keywords}
    if not {"task_cid", "expected_revision", "new_status", "receipt", "evidence_digests"} <= names:
        raise RuntimeError("native caller omits revision/receipt/evidence fields; no work will be claimed")
    try:
        inspect.signature(intent_class.cas_task_status).bind(None, **{name: None for name in names})
    except TypeError as exc:
        raise RuntimeError(
            "accelerate claim contract is incompatible: IntentRepository.cas_task_status "
            "must accept all forwarded fields (" + ", ".join(sorted(names)) + "). No work will be claimed; qualify a "
            "compatible dependency rather than bypassing the receipt guard."
        ) from exc


def validated_task_id(value: str) -> str:
    """An explicit operator selection, not a status or dependency override."""
    if not re.fullmatch(r"AFTD-[0-9a-f]{20}", value):
        raise ValueError("task ID must be an exact AFTD- plus 20 lowercase hex digits")
    return value


def native_task_binding(report: dict) -> list[str]:
    """Bind one live invocation to the preflighted immutable task, never a fallback."""
    if report.get("eligible") is not True or report.get("passed") is not True:
        raise ValueError("native task binding requires passing eligible preflight")
    task_cid = report.get("task_cid")
    if not isinstance(task_cid, str) or not re.fullmatch(r"baguqeera[a-z2-7]{52}", task_cid):
        raise ValueError("native task binding requires an exact sealed task CID")
    return ["--execution-slice-task-cid", task_cid]


def preflight_next_repair(source, repository: Path, *, probe=None, task_id: str = "") -> dict:
    """Read native eligibility and dependency policy before creating an attempt.

    This is an early diagnostic, not dispatch authority: the native bridge must
    still repeat its own checks in the isolated execution workspace.
    """
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import (
        NAMESPACE, SCHEMA, REGRESSION_TESTS, RepairQueueError, read_packet, repair_outputs,
    )
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
    from ipfs_datasets_py.logic.autoformal.validator_profile import require_deployment
    from ipfs_datasets_py.logic.autoformal.repair_intake import review_flags

    deployment = require_deployment(repository)
    if task_id:
        validated_task_id(task_id)
    before = source.snapshot().revision
    # Never use status alone, caller-supplied completed IDs, or priority
    # changes to select a task. Absence from this bounded native-ready set
    # means no dispatch; it never falls back to another alias. A requested
    # alias under a parked goal is not replaced by a different task.
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
        ready_task_cids_under_inconclusive_goals,
    )

    parked = ready_task_cids_under_inconclusive_goals(source)
    page = source.ready_tasks(limit=1000)
    selected = [record for record in page.tasks if not task_id or record.task_alias == task_id]
    if task_id and len(selected) > 1:
        raise RepairQueueError("requested task alias is ambiguous in native readiness")
    requested_parked = bool(task_id and selected and str(selected[0].task_cid) in parked)
    if requested_parked:
        selected = []
    elif not task_id:
        selected = [record for record in selected if str(record.task_cid) not in parked][:1]
    elif not selected:
        # The daemon resumes a running attempt before it claims ready work.
        # An explicit alias still names that attempt; it does not fall back.
        list_tasks = getattr(source, "list_tasks", None)
        if callable(list_tasks):
            inflight = [
                record
                for record in list_tasks(status="in_progress", limit=20).tasks
                if record.task_alias == task_id and str(record.task_cid) not in parked
            ]
            if len(inflight) > 1:
                raise RepairQueueError("requested in-progress task alias is ambiguous")
            selected = inflight
    blocked_reason = "goals_inconclusive" if (requested_parked or (not selected and parked)) else ""
    report = {"schema": "uscode-autoformal-launch-preflight/v1", "queue_revision": before,
              "eligible": bool(selected), "passed": None, "tasks_claimed": False,
              "provider_dispatched": False, "production_promotion": False,
              "admitted": False, "formalized": False,
              "claim_blocked_reason": blocked_reason}
    if task_id:
        report.update(requested_task_id=task_id, selection_scan_limit=1000)
    if deployment is not None:
        report["validator_deployment"] = deployment
    if selected:
        record = selected[0]
        body = record.body
        if body.get("board_namespace") != NAMESPACE:
            raise RepairQueueError("preflight requires a dedicated repair queue")
        digest = body["packet_sha256"]
        packet = read_packet(Path(body["packet_path"]), digest)
        if (record.task_cid != content_identity({"schema": SCHEMA, "packet_sha256": digest})
                or packet["regression_tests"] != list(REGRESSION_TESTS)):
            raise RepairQueueError("task evidence or frozen regression policy differs")
        outputs = [item["path"] for item in record.outputs]
        if outputs != repair_outputs(packet, digest):
            raise RepairQueueError("task outputs differ from sealed repair scope")
        if len(record.validations) != 1:
            raise RepairQueueError("repair requires exactly one sealed validation command")
        argv = list(record.validations[0]["argv"])
        if (len(argv) != 6 or argv[0] != "python3"
                or argv[1:] != ["scripts/ops/legal_ir/validate_autoformal_repair.py",
                                "--packet", body["packet_path"], "--sha256", digest]):
            raise RepairQueueError("validation command differs from sealed repair policy (python3 launcher required)")
        # Check the actual runtime grammar as well as dependency admission.
        # This constructs reviewed argv only; it does not execute the command.
        from ipfs_accelerate_py.agent_supervisor.validation.validation_runtime import validation_shell_command
        validation_shell_command(shlex.join(argv))
        # A conservative intake alarm, NOT a legal classification or agreement.
        # Replay currently forces rows to operative. An editorial-only heading
        # therefore needs source review, not an agent inventing a deontic norm.
        flags = review_flags(packet)
        if probe is None:
            from ipfs_accelerate_py.agent_supervisor.validation.project_dependency_preflight import (
                preflight_validation_project_dependencies,
            )
            probe = preflight_validation_project_dependencies
        receipt = probe(repository, [shlex.join(argv)], task_authority={
            "board_namespace": NAMESPACE, "canonical_task_cid": record.task_cid,
            "declared_outputs": outputs,
        })
        report.update({"task_id": record.task_alias, "task_cid": record.task_cid,
                       "packet_sha256": digest, "packet_path": body["packet_path"],
                       "dependency_preflight": receipt,
                       "review_flags": flags,
                       "passed": receipt.get("passed") is True and not flags})
    if page.revision != before or source.snapshot().revision != before:
        raise RepairQueueError("queue changed during launch preflight; no claim is authorized")
    return report


def propose_ready_gap(source, repository: Path, generate, *, probe=None) -> dict:
    """Ask llm_router about the next ready gap. Do not claim the task or import the edit."""

    from ipfs_datasets_py.logic.autoformal.supervisor_queue import read_packet
    from ipfs_datasets_py.logic.autoformal.supervisor_router import resolve_gap_with_router, row_for_packet

    report = preflight_next_repair(source, repository, probe=probe)
    receipt = {
        "admitted": False,
        "formalized": False,
        "imported": False,
        "preflight_passed": report.get("passed") is True,
        "router_called": False,
        "task_id": report.get("task_id") or "",
        "wrote_compiler": False,
    }
    if report.get("claim_blocked_reason") == "goals_inconclusive":
        receipt["reason"] = "goals_inconclusive"
        receipt["preflight_passed"] = False
        return receipt
    if report.get("passed") is not True:
        receipt["reason"] = "preflight_refused"
        return receipt
    record = source.get(report["task_cid"])
    body = dict(record.body or {})
    recorded = body.get("router_proposal")
    if (
        isinstance(recorded, dict)
        and str(recorded.get("proposal_sha256") or "")
        and recorded.get("applied") is False
        and recorded.get("imported") is False
        and recorded.get("wrote_compiler") is False
    ):
        receipt.update(
            reason="proposal_already_recorded",
            proposal_sha256=str(recorded.get("proposal_sha256") or ""),
            proposal_keys=list(recorded.get("proposal_keys") or []),
            preflight_passed=True,
        )
        return receipt
    packet = read_packet(Path(report["packet_path"]), report["packet_sha256"])
    resolved = resolve_gap_with_router(row_for_packet(packet), generate)
    receipt.update(resolved)
    receipt["preflight_passed"] = True
    if resolved.get("proposal_sha256") and not resolved.get("reason"):
        body["router_proposal"] = {
            "admitted": False,
            "applied": False,
            "formalized": False,
            "imported": False,
            "proposal_keys": list(resolved.get("proposal_keys") or []),
            "proposal_sha256": str(resolved.get("proposal_sha256") or ""),
            "wrote_compiler": False,
        }
        source._intent.upsert_task(
            task_cid=record.task_cid,
            task_alias=record.task_alias,
            goal_cid=str(record.goal_cid or ""),
            ordinal=int(record.ordinal),
            status=str(record.status),
            priority=str(record.priority or "P0"),
            plan_cid=str(record.plan_cid or ""),
            objective_id=str(record.objective_id or ""),
            body=body,
            expected_revision=int(record.revision),
            dependencies=list(record.dependencies),
            outputs=list(record.outputs),
            acceptance=list(record.acceptance),
            validations=list(record.validations),
        )
    return receipt


def require_validation_preflight(report: dict) -> None:
    if report["eligible"] and report["passed"] is not True:
        receipt = report["dependency_preflight"]
        reasons = [receipt.get("reason", "dependency_preflight_failed"), *report["review_flags"]]
        reasons.extend(project["contract_error_reason"] for project in receipt.get("projects", ())
                       if project.get("contract_error_reason"))
        raise RuntimeError("repair launch preflight refused before claim: " + "; ".join(reasons))


def execute_goal_loop(
    *,
    binding: dict,
    database: Path,
    runtime: Path,
    hits: Path | None,
    recensus: bool,
    population_in: Path | None,
    population_out: Path | None,
    board: Path | None,
    query: str,
    release_id: str,
    max_rounds: int,
    command: str,
    graphrag_root: Path | None = None,
    graphrag_repo_id: str = "justicedao/ipfs_uscode",
    graphrag_revision: str = "",
    graphrag_cache: Path | None = None,
    job_template: Path | None = None,
    model_identity: str = "sha256:loop-census-unbound",
) -> dict:
    """Run autoformal, ingest DuckDB goals/todos, optional recensus. Does not claim."""

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
        census_snapshot_path,
        load_population_receipt,
        loop_progress_report,
        progress_log_path,
        recensus_open_todos,
        run_supervisor_loop,
        write_census_snapshot,
        write_population_receipt,
    )

    if recensus and population_in is None:
        raise ValueError("recensus requires --population-in")
    if not recensus and hits is None and not (query and graphrag_root and graphrag_revision):
        raise ValueError(
            "autoformal loop requires --hits, or --query with --graphrag-root and --graphrag-revision, "
            "or --recensus with --population-in"
        )
    board_path = (board or (runtime / "uscode-autoformal-loop.todo.md")).resolve()
    out = (population_out or board_path.with_name(board_path.stem + ".population.json")).resolve()
    prior = load_population_receipt(population_in) if population_in else None
    spec = importlib.util.spec_from_file_location(
        "run_uscode_on_sparse_graphrag",
        Path(__file__).with_name("run_uscode_on_sparse_graphrag.py"),
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    _session: dict[str, Any] = {"value": None}

    def _compile_one(text: str) -> dict:
        from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

        if _session["value"] is None:
            _session["value"] = AutoformalSession()
        return compile_span(_session["value"], text, "loop-recensus")

    seen_docs = {str(item) for item in (prior or {}).get("seen_document_ids") or [] if str(item)}
    retrieve_count = {"n": 0}
    cache_slot: dict[str, Any] = {"cache": None}

    def autoformal():
        retrieve_count["n"] += 1
        if recensus:
            from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span

            session = AutoformalSession()
            tick = recensus_open_todos(
                prior,
                lambda text, _session=session: compile_span(_session, text, "recensus"),
                span_cache=cache_slot["cache"],
            )
            return {"rows": tick["agreement"]["rows"]}
        if hits is not None:
            if retrieve_count["n"] > 1:
                return {"spans": []}
            receipt = runner.run_uscode_autoformal(
                hits_path=hits,
                query=query,
                release_id=release_id,
                skip_upload=True,
            )
            return {"spans": list(receipt.get("spans") or [])}
        from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
            pinned_sparse_graphrag_searcher,
            retrieve_uscode_hits,
        )

        searcher = pinned_sparse_graphrag_searcher(
            repo_id=graphrag_repo_id,
            revision=graphrag_revision,
            release_root=graphrag_root,
            cache_dir=graphrag_cache,
        )
        window = min(1000, 10 * retrieve_count["n"])
        found = retrieve_uscode_hits(
            searcher,
            query,
            top_k=window,
            exclude_document_ids=seen_docs,
        )
        for hit in found:
            doc = str(hit.get("document_id") or "")
            if doc:
                seen_docs.add(doc)
        receipt = runner.run_uscode_autoformal(
            hits=found,
            query=query,
            release_id=release_id,
            skip_upload=True,
        )
        return {
            "spans": list(receipt.get("spans") or []),
            "retrieved_hit_count": len(found),
            "top_k": window,
        }

    database.parent.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    dispatch = {
        "packet_directory": runtime / "packets",
        "code_identity": code_identity(),
        "model_identity": model_identity or "sha256:loop-census-unbound",
        "accelerate_root": binding.get("accelerate_root"),
        "database": database,
        "runtime_root": runtime,
        "release_id": release_id,
        "query": query,
    }
    if job_template is not None:
        dispatch["job_template"] = job_template

    def _lake_probe(rules):
        from ipfs_datasets_py.logic.autoformal.lake_probe import probe_census_rules

        return probe_census_rules(rules)

    def _lake_check(source: str):
        from ipfs_datasets_py.logic.autoformal.lake_probe import lake_check

        return lake_check(source)

    from ipfs_datasets_py.logic.autoformal.span_cache import (
        SpanCache,
        compiler_path_hashes,
    )

    cache_path = runtime / "autoformal-span-cache.duckdb"
    span_cache = SpanCache(cache_path)
    cache_slot["cache"] = span_cache
    path_hashes = compiler_path_hashes(ROOT)
    receipt = None
    try:
        with DatabaseTaskSource(database) as source:
            receipt = run_supervisor_loop(
                autoformal,
                max_rounds=max_rounds,
                query=query,
                release_id=release_id,
                board_path=board_path,
                source=source,
                prior=prior,
                log=lambda line: print(line, flush=True),
                compile_one=_compile_one,
                dispatch=dispatch,
                lake_probe=_lake_probe,
                lean_check=_lake_check,
                span_cache=span_cache,
                path_hashes=path_hashes,
                code_identity=code_identity(),
            )
    finally:
        flush = None
        try:
            if span_cache.due_for_flush(every=1) or span_cache.stats()["sealed"]:
                from ipfs_datasets_py.huggingface.autoformal_span_cache import flush_span_cache

                flush = flush_span_cache(
                    span_cache.sealed_rows(),
                    runtime / "span-cache-hf",
                    dry_run=True,
                )
                span_cache.mark_flushed()
        except Exception as exc:
            flush = {
                "admitted": False,
                "dry_run": True,
                "error": type(exc).__name__,
                "jsonl_written": False,
                "uploaded": False,
            }
        finally:
            span_cache.close()
    if receipt is None:
        raise RuntimeError("autoformal supervisor loop did not produce a receipt")
    receipt["seen_document_ids"] = sorted(seen_docs)
    write_population_receipt(out, receipt)
    census_path = census_snapshot_path(board_path) or board_path.with_name(board_path.stem + ".census.json")
    write_census_snapshot(census_path, receipt)
    last = (receipt.get("rounds") or [{}])[-1]
    native = dict(last.get("native_population") or {})
    log_path = progress_log_path(board_path)
    return {
        **binding,
        "admitted": False,
        "board_path": str(board_path),
        "command": command,
        "formalized": False,
        "goal_count": last.get("goal_count"),
        "jsonl_written": False,
        "native_goal_count": native.get("goal_count"),
        "native_task_count": native.get("task_count"),
        "open_goal_count": receipt.get("open_goal_count"),
        "population_path": str(out),
        "census_path": str(census_path),
        "progress_log_path": str(log_path) if log_path is not None else "",
        "proof_count": receipt["proof_count"],
        "stop_reason": receipt["stop_reason"],
        "tasks_claimed": False,
        "todo_count": receipt["todo_count"],
        "compiled_count": receipt.get("compiled_count"),
        "remaining_count": receipt.get("remaining_count"),
        "compiled_span_ids": receipt.get("compiled_span_ids") or [],
        "remaining_span_ids": receipt.get("remaining_span_ids") or [],
        "progress": loop_progress_report(receipt),
        "lake": dict(receipt.get("lake") or last.get("lake") or {}),
        "census_spans": list(receipt.get("census_spans") or last.get("census_spans") or []),
        "span_cache": dict(receipt.get("span_cache") or last.get("span_cache") or {}),
        "span_cache_path": str(cache_path),
        "span_cache_flush": flush or {"jsonl_written": False, "uploaded": False, "dry_run": True},
        "wrote_compiler": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--accelerate-root", type=Path, required=True)
    result.add_argument("--database", type=Path, required=True)
    result.add_argument("--runtime-root", type=Path, required=True)
    result.add_argument("--task-id", type=validated_task_id, default=None,
                        help="Select one native-ready sealed task for preflight/supervise; no fallback or status changes.")
    sub = result.add_subparsers(dest="command", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--agreement", type=Path, required=True)
    enqueue.add_argument("--release-id", required=True)
    enqueue.add_argument("--model-identity", required=True)
    enqueue.add_argument("--query", default="")
    enqueue.add_argument("--huggingface-package", type=Path, default=None)
    enqueue.add_argument("--pointer", type=Path, default=None)
    enqueue.add_argument("--board", type=Path, default=None)
    sub.add_parser("status")
    intake = sub.add_parser("route-intake", help="Park sealed editorial-heading tasks for review, not completion.")
    intake.add_argument("--apply", action="store_true", help="Use native CAS; default is a read-only plan.")
    intake.add_argument("--receipt", type=Path, required=True)
    preflight = sub.add_parser("preflight", help="Inspect the next native-eligible task without claiming it.")
    preflight.add_argument("--repository-root", type=Path, required=True)
    preflight.add_argument("--receipt", type=Path, required=True, help="New generated JSON evidence file; never overwritten.")
    sub.add_parser("upgrade-ready-outputs", help="Explicit pre-dispatch output-contract migration.")
    cycle = sub.add_parser(
        "loop",
        help="Run autoformal, ingest DuckDB goals/todos, recensus until goals resolve.",
    )
    cycle.add_argument("--hits", type=Path, default=None)
    cycle.add_argument("--query", default="")
    cycle.add_argument("--release-id", default="loop-v1")
    cycle.add_argument("--max-rounds", type=int, default=3)
    cycle.add_argument("--board", type=Path, default=None)
    cycle.add_argument("--population-in", type=Path, default=None)
    cycle.add_argument("--population-out", type=Path, default=None)
    cycle.add_argument("--recensus", action="store_true")
    cycle.add_argument("--graphrag-root", type=Path, default=None)
    cycle.add_argument("--graphrag-repo-id", default="justicedao/ipfs_uscode")
    cycle.add_argument("--graphrag-revision", default="")
    cycle.add_argument("--graphrag-cache", type=Path, default=None)
    cycle.add_argument("--job-template", type=Path, default=None,
                       help="Frozen autoencoder-training-job-v6 JSON. Required to bind train todos.")
    cycle.add_argument("--model-identity", default="sha256:loop-census-unbound")
    run = sub.add_parser("supervise")
    run.add_argument("--implement", action="store_true")
    run.add_argument("--once", action="store_true")
    run.add_argument(
        "--autoformal-loop",
        action="store_true",
        help="Run autoformal, ingest DuckDB goals/todos, then recensus. Does not claim.",
    )
    run.add_argument("--hits", type=Path, default=None)
    run.add_argument("--max-rounds", type=int, default=3)
    run.add_argument("--release-id", default="loop-v1")
    run.add_argument("--query", default="")
    run.add_argument("--board", type=Path, default=None)
    run.add_argument("--population-in", type=Path, default=None)
    run.add_argument("--population-out", type=Path, default=None)
    run.add_argument("--graphrag-root", type=Path, default=None)
    run.add_argument("--graphrag-repo-id", default="justicedao/ipfs_uscode")
    run.add_argument("--graphrag-revision", default="")
    run.add_argument("--graphrag-cache", type=Path, default=None)
    run.add_argument("--job-template", type=Path, default=None,
                     help="Frozen autoencoder-training-job-v6 JSON. Required to bind train todos.")
    run.add_argument("--model-identity", default="sha256:loop-census-unbound")
    run.add_argument("--interval", type=float, default=30)
    run.add_argument("--implementation-timeout", type=float, default=1800)
    run.add_argument("--merge-target-branch", default="")
    run.add_argument("--repository-root", type=Path, default=ROOT,
                     help="Clean, operator-prepared repository receiving native repair branches.")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.task_id = args.task_id or ""
    if args.task_id and args.command not in {"preflight", "supervise"}:
        raise ValueError("--task-id is only supported for preflight and supervise")
    autoformal_supervise = args.command == "supervise" and (
        getattr(args, "autoformal_loop", False)
        or getattr(args, "hits", None) is not None
        or getattr(args, "population_in", None) is not None
        or (getattr(args, "query", "") and getattr(args, "graphrag_root", None) is not None)
    )
    if autoformal_supervise and args.implement:
        raise ValueError("autoformal-loop does not claim or implement compiler patches")
    if autoformal_supervise and not args.once:
        raise ValueError("autoformal-loop requires --once")
    if args.command == "supervise" and args.implement and not args.once:
        # The diagnostic is bound to one task and candidate revision. The
        # coordinator regenerates it between native passes; reusing it in a
        # multi-task daemon would fail the binding on the next dispatch.
        raise ValueError("live supervise requires --once; use run_autoformal_feedback_loop.py for continuous work")
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    # A released native pool lease can reset/remove a failed scratch checkout
    # even when merged-worktree cleanup is disabled. Keep non-pooled attempts
    # for this retain-all-evidence workflow; enforce the storage stop instead.
    os.environ["IPFS_ACCELERATE_AGENT_WORKTREE_POOL_ENABLED"] = "0"
    binding = pin_accelerate(args.accelerate_root)
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import NAMESPACE, enqueue_repairs, repair_packets

    database = args.database.resolve()
    runtime = args.runtime_root.resolve()
    if args.command == "loop":
        print(json.dumps(execute_goal_loop(
            binding=binding,
            database=database,
            runtime=runtime,
            hits=args.hits,
            recensus=args.recensus,
            population_in=args.population_in,
            population_out=args.population_out,
            board=args.board,
            query=args.query,
            release_id=args.release_id,
            max_rounds=args.max_rounds,
            command="loop",
            graphrag_root=getattr(args, "graphrag_root", None),
            graphrag_repo_id=getattr(args, "graphrag_repo_id", "justicedao/ipfs_uscode"),
            graphrag_revision=getattr(args, "graphrag_revision", "") or "",
            graphrag_cache=getattr(args, "graphrag_cache", None),
            job_template=getattr(args, "job_template", None),
            model_identity=getattr(args, "model_identity", "sha256:loop-census-unbound"),
        ), sort_keys=True))
        return 0
    if args.command == "supervise" and (
        args.autoformal_loop
        or args.hits is not None
        or args.population_in is not None
        or (args.query and getattr(args, "graphrag_root", None) is not None)
    ):
        first = execute_goal_loop(
            binding=binding,
            database=database,
            runtime=runtime,
            hits=args.hits,
            recensus=False,
            population_in=args.population_in,
            population_out=args.population_out,
            board=args.board,
            query=args.query,
            release_id=args.release_id,
            max_rounds=args.max_rounds,
            command="supervise-autoformal-loop",
            graphrag_root=getattr(args, "graphrag_root", None),
            graphrag_repo_id=getattr(args, "graphrag_repo_id", "justicedao/ipfs_uscode"),
            graphrag_revision=getattr(args, "graphrag_revision", "") or "",
            graphrag_cache=getattr(args, "graphrag_cache", None),
            job_template=getattr(args, "job_template", None),
            model_identity=getattr(args, "model_identity", "sha256:loop-census-unbound"),
        )
        recensed = execute_goal_loop(
            binding=binding,
            database=database,
            runtime=runtime,
            hits=None,
            recensus=True,
            population_in=Path(first["population_path"]),
            population_out=Path(first["population_path"]),
            board=Path(first["board_path"]),
            query=args.query,
            release_id=args.release_id,
            max_rounds=1,
            command="supervise-autoformal-recensus",
            job_template=getattr(args, "job_template", None),
            model_identity=getattr(args, "model_identity", "sha256:loop-census-unbound"),
        )
        print(json.dumps({**first, "recensus": recensed, "tasks_claimed": False}, sort_keys=True))
        return 0
    if args.command == "enqueue":
        if args.agreement.stat().st_size > 1024 * 1024:
            raise ValueError("agreement exceeds bounded input size")
        agreement = json.loads(args.agreement.read_bytes())
        items = repair_packets(agreement, release_id=args.release_id, code_identity=code_identity(),
                               model_identity=args.model_identity, query=args.query)
        database.parent.mkdir(parents=True, exist_ok=True)
        locator = None
        huggingface = None
        if args.huggingface_package is not None or args.board is not None:
            from ipfs_datasets_py.huggingface.autoformal_todo import upload_autoformal_todos
            from ipfs_datasets_py.logic.autoformal.supervisor_todo import submit_discrepancies

            upload = None
            if args.huggingface_package is not None:
                def upload(tasks, _root=args.huggingface_package, _pointer=args.pointer):
                    return upload_autoformal_todos(tasks, _root, pointer_path=_pointer, dry_run=True)

            huggingface = submit_discrepancies(
                agreement,
                board_path=args.board,
                query=args.query,
                release_id=args.release_id,
                upload=upload,
            )
            locator = huggingface.get("locator") or None
        extra = {"jsonl_written": False}
        if locator:
            extra["huggingface_todo_locator"] = dict(locator)
        with DatabaseTaskSource(database) as source:
            receipt = enqueue_repairs(
                source,
                items,
                packet_directory=runtime / "packets",
                extra_task_fields=extra,
            )
        if huggingface:
            receipt["huggingface"] = {
                "jsonl_written": False,
                "locator": huggingface.get("locator") or {},
                "task_count": huggingface.get("task_count") or 0,
                "board_path": huggingface.get("board_path") or "",
            }
        print(json.dumps({**binding, **receipt}, sort_keys=True))
        return 0
    if not database.is_file():
        raise ValueError("task database does not exist; enqueue evidence first")
    if args.command == "route-intake":
        from ipfs_datasets_py.logic.autoformal.feedback_cycle import exclusive_loop
        from ipfs_datasets_py.logic.autoformal.repair_intake import route_intake_reviews
        if not database.is_relative_to(runtime):
            raise ValueError("intake requires a database inside the owned runtime")
        require_native_transition_contract()
        # Reserve the report name before mutation; never overwrite an old receipt.
        with args.receipt.open("x") as stream, exclusive_loop(runtime):
            with DatabaseTaskSource(database, install_schema=False) as source:
                report = route_intake_reviews(source, apply=args.apply)
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({key: value for key, value in report.items() if key != "transitions"}, sort_keys=True))
        return 0
    if args.command == "upgrade-ready-outputs":
        from ipfs_datasets_py.logic.autoformal.supervisor_queue import upgrade_ready_outputs
        with DatabaseTaskSource(database, install_schema=False) as source:
            print(json.dumps(upgrade_ready_outputs(source), sort_keys=True))
        return 0
    if args.command == "status":
        with DatabaseTaskSource(database, install_schema=False) as source:
            counts: dict[str, int] = {}
            cursor = ""
            while True:
                page = source.list_tasks(cursor=cursor, limit=100)
                for task in page.tasks:
                    counts[task.status] = counts.get(task.status, 0) + 1
                cursor = page.next_cursor
                if not cursor:
                    break
            from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
                claim_block_for_inconclusive_goals,
                goal_status_counts,
            )
            from ipfs_datasets_py.logic.autoformal.supervisor_router import review_holds
            holds = review_holds(source)
            goals = goal_status_counts(source)
            blocked = claim_block_for_inconclusive_goals(source)
            print(json.dumps({
                **binding,
                "admitted": False,
                "claim_blocked_reason": blocked["claim_blocked_reason"],
                "claim_blocked_task_cids": blocked["claim_blocked_task_cids"],
                "claimable_ready_task_cids": blocked["claimable_ready_task_cids"],
                "counts": counts,
                "formalized": False,
                "goal_status_counts": goals["goal_status_counts"],
                "inconclusive_goal_count": goals["inconclusive_goal_count"],
                "inconclusive_goals": goals["inconclusive_goals"],
                "open_goal_count": goals["open_goal_count"],
                "open_goals": goals["open_goals"],
                "review_hold_count": len(holds["holds"]),
                "review_hold_keys": holds["review_hold_keys"],
                "review_holds": holds["holds"],
                "router_called": False,
                "snapshot": source.snapshot().to_dict(),
                "verified_complete_count": goals["verified_complete_count"],
                "wrote_compiler": False,
            }, sort_keys=True))
        return 0
    if args.command == "preflight":
        with DatabaseTaskSource(database, install_schema=False) as source:
            report = preflight_next_repair(source, args.repository_root.resolve(strict=True), task_id=args.task_id)
        with args.receipt.open("x") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({key: value for key, value in report.items() if key != "dependency_preflight"}, sort_keys=True))
        return 2 if report["passed"] is False or (args.task_id and not report["eligible"]) else 0
    if not 1 <= args.interval <= 3600 or not 30 <= args.implementation_timeout <= 7200:
        raise ValueError("invalid supervisor time bounds")
    require_native_transition_contract()
    # The external watchdog requires Quack. For a new local queue use the
    # supported exclusive in-process database daemon, with its real Portal
    # execution bridge and event-driven loop; never downgrade a Quack store.
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon_runner import (
        run_configured_portal_implementation_daemon,
    )
    native_args = [
        "--todo-path", str(database), "--state-dir", str(runtime / "state"),
        "--task-prefix", "AFTD-", "--board-namespace", NAMESPACE,
        "--state-prefix", "autoformal", "--task-source-kind", "duckdb",
        "--authority-mode", "embedded", "--state-store-id", "autoformal-" + hashlib.sha256(str(database).encode()).hexdigest()[:16],
        "--state-failover-policy", "fail_closed",
        "--worktree-root", str(runtime / "worktrees"),
        "--merge-queue-dir", str(runtime / "merge-queue"),
        "--interval", str(args.interval),
        "--implementation-timeout", str(args.implementation_timeout),
        "--max-task-attempts", "3", "--implement",
        "--merged-worktree-cleanup-max", "0",
        "--retain-worktree-artifacts",
    ]
    if args.merge_target_branch:
        native_args += ["--merge-target-branch", args.merge_target_branch]
    from ipfs_datasets_py.logic.autoformal.validator_profile import DEPLOYMENT_PROTECTED
    for path in dict.fromkeys((*PROTECTED, *DEPLOYMENT_PROTECTED)):
        native_args += ["--implementation-protected-path", path]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.once:
        native_args.append("--once")
    if not args.implement:
        # The native no-provider database daemon is a testing surface, not
        # an implementation dry run. Do not claim tasks with fake callbacks.
        from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_args
        if args.task_id:
            native_args += ["--execution-slice-task-id", args.task_id]
        parse_args(native_args)
        print(json.dumps({**binding, "engine": "accelerate-native-database-daemon",
                          "execution_enabled": False, "authority": "embedded-single-owner",
                          "native_arguments": native_args, "tasks_claimed": False}, sort_keys=True))
        return 0
    repository = args.repository_root.resolve(strict=True)
    top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repository, text=True).strip()
    if Path(top).resolve() != repository:
        raise ValueError("repair repository must be a Git root")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=repository):
        raise ValueError("automatic repairs require a clean isolated snapshot; shared dirty worktrees are refused")
    for path in PROTECTED:
        expected = ROOT / path
        actual = repository / path
        if actual.is_symlink() or not actual.is_file() or actual.read_bytes() != expected.read_bytes():
            raise ValueError("repair repository lacks current protected evaluator: " + path)
    if not args.merge_target_branch:
        # Repair worktrees are seeded from this branch. A snapshot's main ref
        # is the pre-overlay source, so the checked-out candidate must be the
        # base or the provider edits a different compiler than the census.
        current_branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=repository, text=True,
        ).strip()
        if current_branch:
            native_args += ["--merge-target-branch", current_branch]
    with DatabaseTaskSource(database, install_schema=False) as source:
        for record in source.list_tasks(status="ready", limit=100).tasks:
            if record.body.get("board_namespace") == NAMESPACE and not record.outputs:
                raise ValueError("ready repair lacks native output declarations; run explicit migration first")
        if not args.task_id:
            inflight = [
                task
                for task in source.list_tasks(status="in_progress", limit=20).tasks
                if task.body.get("board_namespace") == NAMESPACE
            ]
            if len(inflight) > 1:
                raise ValueError("more than one in-progress repair is open")
            if len(inflight) == 1:
                args.task_id = inflight[0].task_alias
        report = preflight_next_repair(source, repository, task_id=args.task_id)
        require_validation_preflight(report)
        if not report["eligible"]:
            raise ValueError("no native-eligible task remains before dispatch")
        native_args += native_task_binding(report)
        record = source.get(report["task_cid"])
        context_command = [
            sys.executable, str(repository / "scripts/ops/legal_ir/prepare_autoformal_repair_context.py"),
            "--accelerate-root", str(args.accelerate_root.resolve()),
            "--packet", record.body["packet_path"], "--sha256", report["packet_sha256"],
            "--task-cid", record.task_cid, "--output-directory", str(runtime / "repair-context"),
        ]
        generated = subprocess.run(context_command, cwd=repository, check=True, capture_output=True,
                                   text=True, timeout=60)
        note = json.loads(generated.stdout.strip().splitlines()[-1])
        if note["task_cid"] != record.task_cid or note["counts_as_validation"] is not False:
            raise ValueError("repair context returned an invalid task binding")
        native_args += ["--operator-repair-note", note["path"],
                        "--operator-repair-note-sha256", note["sha256"]]
    for child in ("state", "worktrees", "merge-queue", "repair-context"):
        (runtime / child).mkdir(parents=True, exist_ok=True)
    run_configured_portal_implementation_daemon(
        native_args, repo_root=repository, logger=logging.getLogger("autoformal.supervisor"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
