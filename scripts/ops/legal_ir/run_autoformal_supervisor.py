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


def task_alias_shard_index(alias: str, shard_count: int) -> int:
    """Match the database daemon's alias hash lane.

    The key is the alias, or the final colon segment when the alias is a
    namespaced id. The same function decides which parallel repair process
    may preflight the task.
    """

    if isinstance(shard_count, bool) or not isinstance(shard_count, int) or shard_count < 1:
        raise ValueError("task_shard_count must be a positive integer")
    key = str(alias or "")
    if ":" in key:
        key = key.rsplit(":", 1)[-1]
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % shard_count


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


def _read_handoff_metadata_v2(path: Path) -> dict:
    """Read one bounded ordinary metadata file without native constructors."""
    import stat

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 4 * 1024 * 1024:
            raise ValueError("bounded regular handoff metadata file required")
        raw = bytearray()
        while len(raw) <= 4 * 1024 * 1024:
            block = os.read(fd, min(65536, 4 * 1024 * 1024 + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(fd)
        stamp = lambda st: (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if len(raw) != before.st_size or stamp(before) != stamp(after) or stamp(after) != stamp(path.lstat()):
            raise ValueError("handoff metadata changed during read")
    finally:
        os.close(fd)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate handoff metadata key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("nonfinite handoff metadata")
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    if type(value) is not dict:
        raise ValueError("handoff metadata root must be an object")
    return value

def _write_handoff_metadata_v2(path: Path, raw: bytes) -> None:
    """Create one requested output exclusively; preserve partial failures."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("short handoff metadata write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _checked_job_packet_bytes_v1(pin: dict) -> bytes:
    """Read a declared metadata/source file as data; never import its bytes."""
    import stat

    if (type(pin) is not dict or set(pin) != {"path", "bytes", "sha256"}
            or type(pin["path"]) is not str or type(pin["bytes"]) is not int
            or not 0 < pin["bytes"] <= 4 * 1024**2 or type(pin["sha256"]) is not str):
        raise ValueError("bounded metadata descriptor required")
    path = Path(pin["path"])
    if (not path.is_absolute() or ".." in path.parts
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise ValueError("exact unaliased metadata descriptor path required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != pin["bytes"]:
            raise ValueError("metadata descriptor file or size differs")
        raw = bytearray()
        while len(raw) <= 4 * 1024**2:
            block = os.read(fd, min(65536, 4 * 1024**2 + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(fd)
        stamp = lambda st: (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if (stamp(before) != stamp(after) or stamp(after) != stamp(path.lstat())
                or len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]):
            raise ValueError("metadata descriptor bytes changed or differ")
        return bytes(raw)
    finally:
        os.close(fd)


def _job_packet_index_arguments_v1(spec: dict, owner) -> tuple[dict, dict]:
    """Join one shared retained capsule to actual metadata and current sources."""
    def need(value, message):
        if not value:
            raise ValueError(message)

    def json_pin(pin):
        raw = _checked_job_packet_bytes_v1(pin)
        def unique(pairs):
            value = {}
            for key, item in pairs:
                need(key not in value, "duplicate retained metadata key")
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: need(False, "nonfinite retained metadata"))
        need(type(value) is dict, "retained metadata object required")
        return value

    fields = {"schema", "canonical_owner", "inputs", "reuse_audit", "primary_snapshot_root",
              "packet_proposals", "producer_principal", "expected_task_revision"}
    need(type(spec) is dict and set(spec) == fields
         and spec["schema"] == "legal-ir-job-packet-index-cli-inputs/v1", "closed packet-index CLI inputs required")
    need(spec["canonical_owner"]["path"] == str(Path(owner.__file__).resolve()), "canonical metadata owner pin differs")
    _checked_job_packet_bytes_v1(spec["canonical_owner"])
    need(type(spec["inputs"]) is dict and set(spec["inputs"]) ==
         {"current_snapshot", "capability_report", "capability_verification"}, "three actual metadata input files required")
    inputs = {key: json_pin(pin) for key, pin in spec["inputs"].items()}
    kwargs = {**inputs, **{key: spec[key] for key in ("packet_proposals", "producer_principal", "expected_task_revision")}}
    audit = json_pin(spec["reuse_audit"])
    need(audit.get("schema") == "legal-ir-LIR9003-completed-engineering-reuse/v1"
         and audit.get("native_or_model_execution") is False, "existing completed-engineering reuse capsule required")
    root = Path(spec["primary_snapshot_root"])
    need(root.is_absolute() and root.is_dir() and ".." not in root.parts
         and not any(p.is_symlink() for p in (root, *root.parents)), "explicit primary snapshot root required")
    rows = audit.get("packets")
    expected_ids = {row[0] for row in owner._PROGRAMME_WORK_PACKET_SPECS_V1}
    need(type(rows) is list and len(rows) == 4 and all(type(row) is dict for row in rows)
         and {row.get("task_id") for row in rows} == expected_ids, "four existing preparation identities required")
    parents, source_paths, evidence_paths, all_checked = set(), set(), set(), set()
    retained, current_sources, evidence = [], {}, {}
    for row in rows:
        packet, receipt = json_pin(row["packet"]), json_pin(row["receipt"])
        task_id = row["task_id"]
        need(packet.get("schema") == "legal-ir-programme-preparation/v1" and packet.get("task_id") == task_id
             and packet.get("metadata_complete") is True and packet.get("snapshot_binding_only") is True
             and all(packet.get(flag) is False for flag in ("admitted", "formalized", "dispatch_authorized",
                 "mutation_authorized", "model_executed", "training_executed", "scientific_parent_satisfied")),
             "retained preparation must remain unadmitted metadata")
        need(receipt.get("schema") == "legal-ir-supervisor-task-receipt/v1" and receipt.get("task_id") == task_id
             and receipt.get("status") == "implemented" and receipt.get("task_kind") == "programme_preparation"
             and receipt.get("authority") == {"admitted": False, "formalized": False}
             and any(item.get("kind") == "packet" and item.get("sha256") == row["packet"]["sha256"]
                 and type(item.get("path")) is str and row["packet"]["path"].endswith("/" + item["path"])
                 for item in receipt.get("artifacts", []) if type(item) is dict), "retained receipt/packet join differs")
        scope = packet["admission_scope"]
        need(scope["native_binding"] == {"control_revision": None, "status": "original_admission_required", "task_cid": None},
             "historical preparation cannot acquire a native binding")
        selected_parents = [item["task_id"] for item in scope["supporting_parents"]]
        need(selected_parents == row["supporting_parent_contexts"], "retained parent coverage differs")
        parents.update(selected_parents)
        retained.append({key: row[key] for key in ("task_id", "packet", "receipt", "supporting_parent_contexts")})
        all_checked.update((row["packet"]["path"], row["receipt"]["path"]))
        sources = {}
        for item in row["resolved_snapshot_dependencies"]:
            declared, resolved = item["declared"], item["resolved_primary_R"]
            relative = Path(declared["path"])
            need(not relative.is_absolute() and ".." not in relative.parts
                 and item["role"] in {"owner_sources", "evidence"} and resolved["path"] == str(root / relative)
                 and resolved["bytes"] == declared["bytes"] and resolved["sha256"] == declared["sha256"],
                 "explicit retained snapshot root mapping differs")
            _checked_job_packet_bytes_v1(resolved)
            need(declared in scope["dependencies"][item["role"]], "retained dependency membership differs")
            all_checked.add(resolved["path"])
            if item["role"] == "owner_sources":
                source_paths.add(resolved["path"])
                logical = declared["path"].split("/owner-sources/", 1)
                need(len(logical) == 2 and logical[1] in scope["logical_owner_paths"]
                     and not Path(logical[1]).is_absolute() and ".." not in Path(logical[1]).parts,
                     "retained source owner path differs")
                current = {**resolved, "path": str(root / logical[1])}
                _checked_job_packet_bytes_v1(current)
                all_checked.add(current["path"])
                sources[logical[1]] = declared["sha256"]
                current_sources[logical[1]] = {"logical_path": logical[1], "current_primary": current,
                                               "retained_snapshot": resolved}
            else:
                evidence_paths.add(resolved["path"])
                evidence[resolved["path"]] = resolved
        need(set(sources) == set(scope["logical_owner_paths"]), "complete retained source owner closure required")
        # current_W comparisons are immutable historical observations. Current
        # PRIMARY files above are the selected execution-source comparison.
    need(len(source_paths) == 13 and len(evidence_paths) == 11 and len(parents) == 22,
         "existing13-source/11-evidence/22-parent capsule coverage differs")
    native = inputs["current_snapshot"]["tasks"]
    bindings = [{"task_alias": row["task_alias"], "task_cid": row["task_cid"], "revision": row["revision"],
                 "preparations": [item["task_id"] for item in rows
                     if row.get("body", {}).get("legacy_parent_task") in item["supporting_parent_contexts"]]}
                for row in native if row.get("body", {}).get("legacy_parent_task") in parents]
    need(len(bindings) == 49 and len({row["task_cid"] for row in bindings}) == 49, "current49 native child bindings required")
    # These seven native tasks explicitly need an implementation scope. The
    # retained preparation evidence cannot fill code, test, lease or acceptance
    # fields. This control-only CLI preserves that boundary in the frozen report.
    gaps = [{"task_alias": row["task_alias"], "task_cid": row["task_cid"], "revision": row["revision"],
             "current_code_edit_allowlist": row["body"].get("code_edit_allowlist", []),
             "reviewed_implementation_packet_present": False,
             "unbound_requirements": ["exact_code_change_paths", "owning_test_paths", "shared_file_lease_keys",
                                      "independent_implementation_acceptance"]}
            for row in native if row.get("body", {}).get("requires_product_change_scope") is True]
    need(len(gaps) == 7, "current seven implementation scope gaps required")
    context = {"schema": "legal-ir-job-packet-index-review-context/v1",
        "retained_preparations": sorted(retained, key=lambda row: row["task_id"]),
        "current_primary_source_closure": [current_sources[key] for key in sorted(current_sources)],
        "retained_evidence_snapshots": [evidence[key] for key in sorted(evidence)],
        "supporting_parent_contexts": sorted(parents),
        "current_native_child_bindings": sorted(bindings, key=lambda row: row["task_alias"]),
        "implementation_scope_gaps": sorted(gaps, key=lambda row: row["task_alias"]),
        "historical_W_comparisons_are_context_only": True, "native_binding_authority": False}
    proposals = spec["packet_proposals"]
    need(type(proposals) is list and all(type(row) is dict and row.get("task_alias") in
         {"LIR-9003", "LIR-9004"} for row in proposals), "control-only packet proposals required")
    self_proposals = [row for row in proposals if row["task_alias"] == "LIR-9003"]
    need(len(self_proposals) == 1, "concrete9003 self packet required")
    context_raw = owner._handoff_reconciliation_bytes_v2(context)
    need(owner._handoff_reconciliation_bytes_v2(self_proposals[0].get("review_context")) == context_raw,
         "self packet review_context differs from actual retained/current grounding")
    return kwargs, {"review_context_sha256": hashlib.sha256(context_raw).hexdigest(),
        "implementation_scope_gaps": len(gaps), "retained_preparations": 4, "retained_receipts": 4, "retained_owner_sources": 13,
        "current_primary_sources_matching": 13, "retained_evidence": 11, "covered_parent_contexts": 22,
        "current_native_children_bound": 49, "native_child_binding_sha256": hashlib.sha256(
            owner._handoff_reconciliation_bytes_v2(bindings)).hexdigest(), "retained_materializers_rerun": False,
        "historical_W_comparisons_are_context_only": True, "checked_file_count": len(all_checked),
        "checked_file_paths_sha256": hashlib.sha256(owner._handoff_reconciliation_bytes_v2(sorted(all_checked))).hexdigest()}


def job_packet_index_main_v1(argv: list[str]) -> int:
    """Prepare and independently reconstruct concrete, source-bound metadata."""
    parser = argparse.ArgumentParser(description=job_packet_index_main_v1.__doc__)
    parser.add_argument("operation", choices=("prepare", "verify"))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-out", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--verifier-principal")
    args = parser.parse_args(argv)
    if args.operation == "prepare" and (args.freeze_out is None or args.report is not None
            or args.freeze is not None or args.verifier_principal is not None):
        parser.error("prepare requires --freeze-out and forbids verifier inputs")
    if args.operation == "verify" and (args.report is None or args.freeze is None
            or not args.verifier_principal or args.freeze_out is not None):
        parser.error("verify requires --report, --freeze and --verifier-principal")
    try:
        paths = [p for p in (args.inputs, args.output, args.freeze_out, args.report, args.freeze) if p is not None]
        if (any(not p.is_absolute() or ".." in p.parts or any(part.is_symlink() for part in (p, *p.parents)) for p in paths)
                or len({str(p.resolve()) for p in paths}) != len(paths)):
            raise ValueError("distinct absolute unaliased packet-index paths required")
        for path in ([args.output, args.freeze_out] if args.operation == "prepare" else [args.output]):
            if os.path.lexists(path):
                raise ValueError("packet-index output exists; preserve and reconcile")
        sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.logic.autoformal import supervisor_loop as owner
        if Path(owner.__file__).resolve() != ROOT / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py":
            raise ValueError("canonical metadata owner import origin differs")
        spec = _read_handoff_metadata_v2(args.inputs)
        inputs, reuse = _job_packet_index_arguments_v1(spec, owner)
        if args.operation == "prepare":
            value = owner.prepare_current_job_packet_index_v1(**inputs)
            index = value
        else:
            index = _read_handoff_metadata_v2(args.report)
            canonical = owner._handoff_reconciliation_bytes_v2(index)
            if _checked_job_packet_bytes_v1({"path": str(args.report), "bytes": len(canonical),
                    "sha256": hashlib.sha256(canonical).hexdigest()}) != canonical:
                raise ValueError("report is not the frozen canonical serialization")
            value = owner.verify_current_job_packet_index_v1(index, producer_freeze=_read_handoff_metadata_v2(args.freeze),
                verifier_principal=args.verifier_principal, **inputs)
        complete = [row for row in index["entries"] if row["metadata_complete"]]
        if (not complete or any(row["task_alias"] not in {"LIR-9003", "LIR-9004"} for row in complete)
                or not any(row["task_alias"] == "LIR-9003" for row in complete)):
            raise ValueError("concrete9003 control packet required; negative-only previews remain in the pure API")
        self_packet = next(row["packet_proposal"] for row in complete if row["task_alias"] == "LIR-9003")
        prefix = [sys.executable, "-B", str(Path(__file__).resolve()), "job-packet-index"]
        actual = (prefix + ["prepare", "--inputs", str(args.inputs), "--output", str(args.output),
                  "--freeze-out", str(args.freeze_out)] if args.operation == "prepare" else
                  prefix + ["verify", "--inputs", str(args.inputs), "--report", str(args.report), "--freeze", str(args.freeze),
                  "--verifier-principal", args.verifier_principal, "--output", str(args.output)])
        declared_argv = self_packet["argv"] if args.operation == "prepare" else self_packet["verifier"]["argv"]
        if (actual != declared_argv or self_packet["cwd"] != str(Path.cwd())
                or self_packet["validation_argv"] != self_packet["verifier"]["argv"]
                or self_packet["worker"]["principal"] != spec["producer_principal"]
                or (args.operation == "verify" and self_packet["verifier"]["principal"] != args.verifier_principal)):
            raise ValueError("actual producer/verifier command, working directory or declared role differs from the self packet")
        owned = {str(Path(spec["primary_snapshot_root"]) / value) for value in self_packet["outputs"]}
        if not {str(args.output), *([str(args.freeze_out)] if args.operation == "prepare" else [])} <= owned:
            raise ValueError("actual outputs differ from native self-packet ownership")
        declared = [item["descriptor"] for item in self_packet["inputs"]]
        if any(pin not in declared for pin in [*spec["inputs"].values(), spec["reuse_audit"]]):
            raise ValueError("actual metadata and shared reuse capsule must join role-bound self inputs")
        if any(pin["path"] == str(args.inputs) for pin in declared):
            raise ValueError("self input-file hash belongs only in the outer native request")
        checked = {}
        for row in complete:
            packet = row["packet_proposal"]
            pins = packet["source_descriptors"] + [item["descriptor"] for item in packet["inputs"]]
            for pin in pins:
                if pin["path"] in checked and checked[pin["path"]] != pin:
                    raise ValueError("ambiguous repeated metadata descriptor")
                checked[pin["path"]] = pin
                if len(checked) > 256:
                    raise ValueError("packet descriptor population exceeds its bound")
                _checked_job_packet_bytes_v1(pin)
        raw = owner._handoff_reconciliation_bytes_v2(value)
        _write_handoff_metadata_v2(args.output, raw)
        if args.operation == "prepare":
            freeze = {"schema": "legal-ir-job-packet-index-producer-freeze/v1", "report_sha256": hashlib.sha256(raw).hexdigest(),
                "report_bytes": len(raw), "producer_principal": value["producer_principal"], "frozen_before_verification": True}
            _write_handoff_metadata_v2(args.freeze_out, owner._handoff_reconciliation_bytes_v2(freeze))
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(json.dumps({"schema": "legal-ir-job-packet-index-CLI-refusal/v1", "valid": False,
            "reason": str(exc), "native_admission": False, "completion_authority": False}))
        return 2
    print(json.dumps({"schema": value["schema"], "output": str(args.output), "owner_path": str(Path(owner.__file__).resolve()),
        "checked_packet_input_files": len(checked), "reuse": reuse, "task_acceptance_satisfied": False,
        "productive_runnable_coverage_complete": False, "native_admission": False, "completion_authority": False}))
    return 0


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
    run.add_argument("--task-shard-count", type=int, default=1)
    run.add_argument("--task-shard-index", type=int, default=0)
    run.add_argument("--merge-target-branch", default="")
    run.add_argument("--repository-root", type=Path, default=ROOT,
                     help="Clean, operator-prepared repository receiving native repair branches.")
    return result


def asset_inventory_0101_main_v1(argv: list[str]) -> int:
    """Prepare/verify the opt-in LIR-0101 documentary inventory without native effects."""
    parser = argparse.ArgumentParser(description=asset_inventory_0101_main_v1.__doc__)
    parser.add_argument("operation", choices=("prepare", "verify"))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-out", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--verifier-principal")
    args = parser.parse_args(argv)
    if args.operation == "prepare" and (args.freeze_out is None or args.report is not None
            or args.freeze is not None or args.verifier_principal is not None):
        parser.error("prepare requires --freeze-out and forbids verifier inputs")
    if args.operation == "verify" and (args.report is None or args.freeze is None
            or not args.verifier_principal or args.freeze_out is not None):
        parser.error("verify requires --report, --freeze and --verifier-principal")
    try:
        paths = [p for p in (args.inputs, args.output, args.freeze_out, args.report, args.freeze) if p is not None]
        for path in paths:
            if (not path.is_absolute() or ".." in path.parts
                    or any(part.is_symlink() for part in (path, *path.parents))):
                raise ValueError("exact unaliased absolute 0101 metadata paths required")
        if len(paths) != len(set(paths)):
            raise ValueError("0101 input and output paths must be distinct")
        outputs = [args.output, args.freeze_out] if args.operation == "prepare" else [args.output]
        if any(os.path.lexists(path) for path in outputs):
            raise ValueError("0101 output exists; preserve and reconcile without retry")
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from ipfs_datasets_py.logic.autoformal import supervisor_loop as owner
        if Path(owner.__file__).resolve() != ROOT / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py":
            raise ValueError("0101 canonical owner origin differs")
        spec = _read_handoff_metadata_v2(args.inputs)
        if (set(spec) != {"schema", "canonical_owner", "documents", "producer_principal", "expected_task_revision"}
                or spec.get("schema") != "legal-ir-0101-asset-contribution-inventory-inputs/v1"):
            raise ValueError("0101 closed input schema required")
        owner_raw = _checked_job_packet_bytes_v1(spec["canonical_owner"])
        if spec["canonical_owner"]["path"] != str(Path(owner.__file__).resolve()) or not owner_raw:
            raise ValueError("0101 pinned owner path differs")
        pins = spec["documents"]
        if type(pins) is not dict or set(pins) != owner.ASSET_INVENTORY_0101_DOCUMENTS_V1:
            raise ValueError("0101 exact metadata document roles required")
        documents, selected_paths = {}, set(paths)
        for role, pair in pins.items():
            if type(pair) is not dict or set(pair) != {"original_descriptor", "descriptor"}:
                raise ValueError("0101 declared original-to-durable alias required")
            path = Path(pair["descriptor"]["path"])
            if path in selected_paths:
                raise ValueError("0101 metadata paths must not overlap commands, inputs, outputs or other roles")
            selected_paths.add(path)
            raw = _checked_job_packet_bytes_v1(pair["descriptor"])
            documents[role] = {**pair, "utf8": raw.decode("utf-8")}
        kwargs = {"documents": documents, "producer_principal": spec["producer_principal"],
                  "expected_task_revision": spec["expected_task_revision"]}
        # Reconstruct the same task-specific checks before publishing anything;
        # actual argv must be the three outputs admitted by the current native
        # projection, not arbitrary caller-selected paths or historical data/.
        expected = owner.prepare_current_asset_contribution_inventory_v1(**kwargs)
        bound = expected["runtime_output_binding"]
        if Path.cwd() != Path(bound["cwd"]):
            raise ValueError("0101 actual cwd differs from the native output binding")
        if args.operation == "prepare":
            if str(args.output) != bound["outputs"]["report"] or str(args.freeze_out) != bound["outputs"]["producer_freeze"]:
                raise ValueError("0101 producer argv differs from current native runtime outputs")
            value = expected
            raw = owner._handoff_reconciliation_bytes_v2(value)
            freeze = {"schema": "legal-ir-0101-inventory-producer-freeze/v1",
                "report_sha256": hashlib.sha256(raw).hexdigest(), "report_bytes": len(raw),
                "producer_principal": value["producer_principal"], "frozen_before_verification": True}
            _write_handoff_metadata_v2(args.output, raw)
            _write_handoff_metadata_v2(args.freeze_out, owner._handoff_reconciliation_bytes_v2(freeze))
        else:
            if (str(args.output) != bound["outputs"]["verification"]
                    or str(args.report) != bound["outputs"]["report"]
                    or str(args.freeze) != bound["outputs"]["producer_freeze"]):
                raise ValueError("0101 verifier argv differs from current native runtime outputs")
            report = _read_handoff_metadata_v2(args.report)
            raw = owner._handoff_reconciliation_bytes_v2(report)
            _checked_job_packet_bytes_v1({"path": str(args.report), "bytes": len(raw),
                                          "sha256": hashlib.sha256(raw).hexdigest()})
            freeze = _read_handoff_metadata_v2(args.freeze)
            value = owner.verify_current_asset_contribution_inventory_v1(report, producer_freeze=freeze,
                verifier_principal=args.verifier_principal, **kwargs)
            _write_handoff_metadata_v2(args.output, owner._handoff_reconciliation_bytes_v2(value))
        # Existing source custody remains authoritative; this catches local
        # mid-operation source replacement without granting any new lease.
        if _checked_job_packet_bytes_v1(spec["canonical_owner"]) != owner_raw:
            raise ValueError("0101 owner changed during metadata operation")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        print(json.dumps({"schema": "legal-ir-0101-inventory-metadata-refusal/v1", "valid": False,
            "reason": str(exc), "native_admission": False, "completion_authority": False}))
        return 2
    print(json.dumps({"schema": value["schema"], "output": str(args.output),
        "native_admission": False, "completion_authority": False}))
    return 0



CAPACITY_RECOVERY_LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"
CAPACITY_RECOVERY_ROOTS = (ROOT / "workspace/test-logs", ROOT / "workspace/todo-queues",
    ROOT / "docs/implementation/reports/evidence", Path("/tmp/pytest-of-barberb"))
CAPACITY_RECOVERY_SCHEDULER_STATE = Path("/tmp/ipfs-datasets-resource-scheduler-" + str(os.geteuid()) + ".json")
CAPACITY_RECOVERY_POLICY_SHA256 = "4662bd8fe6caf6f2c048e3d7cff7abb4d80e5c875b21e02e204b1b89371b8286"


def _capacity_recovery_json(pin):
    """Use the existing bounded source/metadata reader; refuse duplicate keys."""
    import stat
    raw = _checked_job_packet_bytes_v1(pin)
    info = Path(pin["path"]).lstat()
    if info.st_nlink != 1 or info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode):
        raise ValueError("capacity metadata must be an owned unaliased regular file")
    return _capacity_recovery_decode(raw)


def _capacity_recovery_decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate capacity metadata key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite capacity metadata")))
    if type(value) is not dict:
        raise ValueError("capacity metadata object required")
    return value


def _capacity_recovery_put(path, value):
    """Exclusive durable bookkeeping, using the existing immutable receipt pattern."""
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > 4 * 1024**2:
        raise ValueError("bounded capacity bookkeeping required")
    _write_handoff_metadata_v2(path, raw)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _capacity_recovery_current_json(path):
    """Read changing owner bookkeeping without following an alias or loading a store."""
    import stat
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    path = resources._safe_path(path)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.geteuid() or not 0 < before.st_size <= 4 * 1024**2):
        raise ValueError("bounded owned current metadata required")
    value = _read_handoff_metadata_v2(path)
    after = path.lstat()
    stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if stamp(before) != stamp(after) or after.st_nlink != 1 or after.st_uid != os.geteuid():
        raise ValueError("current metadata changed during read")
    return value


def _capacity_recovery_resolved_lineage(trigger_ref, resolved):
    """A completed authenticated manual closeout consumes this same trigger."""
    if type(resolved) is not list or len(resolved) > 16:
        raise ValueError("finite resolved-trigger lineage required")
    for item in resolved:
        if type(item) is not dict or set(item) != {"closeout", "genuine_reap"}:
            raise ValueError("exact manual closeout/reap descriptor pair required")
        close = _capacity_recovery_json(item["closeout"])
        reap = _capacity_recovery_json(item["genuine_reap"])
        if (any(close.get(key) is not True for key in ("accepted", "completed", "source_READ_closed", "storage_claim_released"))
                or close.get("recovery_API_calls") != 1 or close.get("capacity_policy") != "require_capacity"
                or any(reap.get(key) is not True for key in ("completed", "source_READ_closed", "outer_exec_genuinely_reaped"))
                or type(reap.get("outer_exec_exit_code")) is not int or reap["outer_exec_exit_code"] != 0
                or reap.get("closeout") != item["closeout"]):
            raise ValueError("genuine successful original manual closeout required")
        receipt = _capacity_recovery_json(close["original_reconciliation"])
        if (close["selected_record_after"].get("status") != "released"
                or close["selected_record_after"].get("explicit_reconciliation") != receipt
                or receipt.get("previous_record_sha256") != close.get("selected_record_sha256")
                or receipt.get("artifact_inventory_manifest") != close.get("inventory_manifest")
                or any(receipt.get(key) is not False for key in ("admitted", "outputs_deleted", "automatic_expiry"))):
            raise ValueError("manual reconciliation lineage differs")
        if close.get("trigger_ROOT_failed_0101_reap") == trigger_ref:
            return item
    return None


def _capacity_recovery_trigger(trigger_ref):
    """Classify only an exact genuinely closed original pre-actor refusal."""
    wait = _capacity_recovery_json(trigger_ref)
    if (type(wait.get("schema")) is not str or wait.get("schema") not in CAPACITY_RECOVERY_WATCH_WAIT_SCHEMAS
            or wait.get("actual_wait_completed") is not True or wait.get("exit_code") != 1
            or type(wait.get("exit_code")) is not int):
        raise ValueError("genuine failed original owner wait required")
    terminal = _capacity_recovery_json(wait["stdout"])
    request = _capacity_recovery_json(wait["request"])
    if wait["schema"] == CAPACITY_RECOVERY_METADATA_WAIT_SCHEMA:
        _capacity_recovery_metadata_execution_contract(request)
    required = {"completed": False, "control_effects": "not_started",
        "child_launch_attempted": False, "original_native_compute_closed": True,
        "source_READ_closed": True, "absolute_resource_operation_deadline_closed": True}
    if (terminal.get("schema") != "legal-ir-original-native-control-terminal/v1"
            or any(terminal.get(key) != value or type(terminal.get(key)) is not type(value)
                   for key, value in required.items())
            or terminal.get("request_sha256") != wait["request"]["sha256"]
            or request.get("schema") != "legal-ir-original-native-control-request/v1"
            or request.get("purpose") != "native_control_metadata"
            or request.get("resource_ledger") != str(CAPACITY_RECOVERY_LEDGER)
            or terminal.get("cleanup_errors") != []):
        raise ValueError("closed original pre-actor capacity refusal required")
    reservation = terminal.get("reservation", {})
    if type(reservation) is not dict:
        raise ValueError("capacity reservation metadata object required")
    if (reservation.get("record") is not None or reservation.get("resource_lease") is not None
            or reservation.get("status") != "not_entered"):
        raise ValueError("capacity trigger must have no entered storage/native child")
    observed = terminal.get("resource_capacity_observation")
    names = ("observed_apparent_bytes", "outstanding_full_reservations_bytes",
        "additional_requested_bytes", "charged_bytes", "limit_bytes",
        "minimum_filesystem_free_bytes", "storage_capacity_deficit_bytes", "filesystem_free_deficit_bytes")
    if (type(observed) is not dict or observed.get("schema") != "daemon-resource-capacity-observation/v1"
            or any(type(observed.get(key)) is not int or observed[key] < 0 for key in names)
            or type(request.get("storage_bytes")) is not int or request["storage_bytes"] <= 0
            or observed["additional_requested_bytes"] != request["storage_bytes"]
            or observed["scope"] != "named_roots_only_apparent_bytes"):
        raise ValueError("typed original capacity arithmetic required")
    charged = observed["observed_apparent_bytes"] + observed["outstanding_full_reservations_bytes"] + request["storage_bytes"]
    storage_deficit = max(0, charged - observed["limit_bytes"])
    free_deficit = max(0, observed["outstanding_full_reservations_bytes"] + request["storage_bytes"] - observed["minimum_filesystem_free_bytes"])
    if (observed["charged_bytes"] != charged or observed["storage_capacity_deficit_bytes"] != storage_deficit
            or observed["filesystem_free_deficit_bytes"] != free_deficit
            or type(observed.get("storage_capacity_exceeded")) is not bool
            or type(observed.get("filesystem_free_insufficient")) is not bool
            or observed["storage_capacity_exceeded"] != bool(storage_deficit)
            or observed["filesystem_free_insufficient"] != bool(free_deficit)
            or not (storage_deficit or free_deficit)):
        raise ValueError("capacity trigger arithmetic or refusal differs")
    return wait, terminal, max(storage_deficit, free_deficit)


def _recover_retained_validation_capacity(trigger_ref, candidates, state_directory, *, resolved=()):
    """One cleanup only; callers own source custody and the absolute cleanup clock."""
    import fcntl
    import stat
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    if type(candidates) is not list or not 1 <= len(candidates) <= 16:
        raise ValueError("finite reviewed candidate allowlist required")
    wait, terminal, deficit = _capacity_recovery_trigger(trigger_ref)
    if terminal["resource_capacity_observation"]["limit_bytes"] != resources.MAX_STORAGE_BYTES:
        raise ValueError("capacity trigger limit differs from current original owner")
    directory = resources._safe_path(state_directory, directory=True)
    if not any(directory == root or root in directory.parents for root in CAPACITY_RECOVERY_ROOTS):
        raise ValueError("capacity state must stay inside original named roots")
    info = directory.lstat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("capacity state must be an owned private directory")
    key = hashlib.sha256(json.dumps(trigger_ref, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    started = directory / (key + ".operation-started-v01.json")
    closed = directory / (key + ".original-reconciliation-v01.json")
    failed = directory / (key + ".operation-failure-v01.json")
    postwrite = directory / (key + ".postwrite-capacity-v01.json")
    resolved_path = directory / (key + ".resolved-trigger-v01.json")
    result = dict(trigger=trigger_ref, recovery_API_calls=0, recovery_API_attempted=False,
        recovery_API_returned=False, recovery_outcome="not_called", postwrite_verification_pending=False,
        read_only_postwrite_verification=False, postwrite_verification_attempted=False,
        actor_or_provider_or_task_calls=0,
        admitted=False, formalized=False, retry_authorized=False, outputs_deleted=False)
    resume = None
    lock_path = directory / ".capacity-recovery.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError("capacity instance lock identity differs")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**result, "status": "another_cleanup_instance_running"}
        if (lock_path.lstat().st_dev, lock_path.lstat().st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("capacity instance lock path changed")
        if os.path.lexists(resolved_path):
            prior = _capacity_recovery_current_json(resolved_path)
            if prior.get("trigger") != trigger_ref or prior.get("status") != "authenticated_trigger_already_resolved":
                raise ValueError("resolved-trigger bookkeeping differs")
            return {**result, "status": "authenticated_trigger_already_resolved"}
        lineage = _capacity_recovery_resolved_lineage(trigger_ref, list(resolved))
        if lineage is not None:
            _capacity_recovery_put(resolved_path, {**result, "status": "authenticated_trigger_already_resolved", "lineage": lineage})
            return {**result, "status": "authenticated_trigger_already_resolved"}
        if os.path.lexists(started):
            held = {**result, "status": "trigger_already_started",
                "closed_receipt_present": os.path.lexists(closed), "postwrite_verification_pending": True}
            try:
                marker = _capacity_recovery_current_json(started)
                if (type(marker) is not dict or set(marker) != {"trigger", "approved_candidate", "reservation_id", "no_automatic_retry", "owner_pid"}
                        or marker["trigger"] != trigger_ref or marker["approved_candidate"] not in candidates
                        or marker["no_automatic_retry"] is not True or type(marker["owner_pid"]) is not int
                        or marker["owner_pid"] <= 0):
                    raise ValueError("immutable original operation marker differs")
            except (ValueError, KeyError, TypeError, FileNotFoundError, resources.DaemonResourceError) as error:
                return {**held, "repair_reason": "invalid original operation marker: " + str(error)[:512]}
            if os.path.lexists(postwrite):
                try:
                    proof = _capacity_recovery_current_json(postwrite)
                    receipt = _capacity_recovery_current_json(closed)
                    reference = _capacity_recovery_watch_pin(closed)
                    pre = _capacity_recovery_json(marker["approved_candidate"]["preflight"])
                    review = _capacity_recovery_json(marker["approved_candidate"]["review"])
                    if (type(proof) is not dict or type(receipt) is not dict
                            or proof.get("schema") != "legal-ir-retained-capacity-actual-postwrite-observation/v1"
                            or proof.get("trigger") != trigger_ref or proof.get("approved_candidate") != marker["approved_candidate"]
                            or proof.get("original_start") != _capacity_recovery_watch_pin(started)
                            or proof.get("reservation_id") != marker["reservation_id"]
                            or proof.get("original_reconciliation") != reference
                            or proof.get("bound_attempt_identity") != pre["selected_record"]["attempt_directory"]
                            or proof.get("original_owner_identity") != {"pid": pre["selected_record"]["owner_pid"], "birth": pre["selected_record"]["owner_birth"]}
                            or proof.get("reconciled_by_pid") != marker["owner_pid"]
                            or any(proof.get(name) is not True for name in ("actual_postwrite_census_verified",
                                "original_native_custody_absent", "complete_artifact_inventory_unchanged", "fresh_operation_admission_still_required"))
                            or any(proof.get(name) is not False for name in ("postwrite_verification_pending", "admitted", "retry_authorized", "limits_changed"))
                            or proof.get("capacity_policy") != "administrative_closeout"
                            or receipt.get("schema") != "explicit-retained-reservation-reconciliation/v3"
                            or receipt.get("reservation_id") != marker["reservation_id"]
                            or receipt.get("previous_record_sha256") != pre["selected_record_sha256"]
                            or receipt.get("original_owner_pid") != pre["selected_record"]["owner_pid"]
                            or receipt.get("reconciled_by_pid") != marker["owner_pid"]
                            or receipt.get("artifact_inventory_manifest") != pre["inventory_manifest"]
                            or receipt.get("capacity_policy") != "administrative_closeout"
                            or review.get("accepted") is not True or review.get("source_READ_closed") is not True
                            or review.get("preflight") != marker["approved_candidate"]["preflight"]
                            or review.get("controller") != pre.get("controller")
                            or pre.get("accepted") is not True or pre.get("completed") is not True or pre.get("source_READ_closed") is not True):
                        raise ValueError("completed postwrite proof binding or flags differ")
                    for name in ("selected_record_sha256", "ledger_sha256"):
                        text = proof.get(name)
                        if type(text) is not str or len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
                            raise ValueError("completed postwrite digest differs")
                    accounting = proof.get("actual_postwrite_accounting")
                    if (type(accounting) is not dict or accounting.get("scope") != "named_roots_only_apparent_bytes"
                            or type(accounting.get("additional_requested_bytes")) is not int or accounting["additional_requested_bytes"] != 0):
                        raise ValueError("completed actual census observation differs")
                    return {**held, "postwrite_verification_pending": False,
                        "authenticated_historical_postwrite_proof": _capacity_recovery_watch_pin(postwrite)}
                except (ValueError, KeyError, TypeError, FileNotFoundError, resources.DaemonResourceError) as error:
                    return {**held, "repair_reason": "invalid or incomplete postwrite proof: " + str(error)[:512]}
            if not os.path.lexists(closed) or not os.path.lexists(failed):
                return {**held, "repair_reason": "original API outcome is not durably known"}
            failure = _capacity_recovery_current_json(failed)
            if (type(failure) is not dict
                    or failure.get("trigger") != trigger_ref or failure.get("reservation_id") != marker["reservation_id"]
                    or failure.get("recovery_API_calls") != 1 or failure.get("recovery_API_returned") is not True
                    or failure.get("known_original_API_returned") is not True
                    or failure.get("postwrite_verification_pending") is not True
                    or failure.get("verification_phase") != "actual_postwrite_census"):
                return {**held, "repair_reason": "only an authenticated census-only returned closeout can resume"}
            reference = _capacity_recovery_watch_pin(closed)
            if failure.get("original_reconciliation") != reference:
                return {**held, "repair_reason": "original returned receipt identity changed"}
            for attempt_number in range(1, 4):
                stem = key + ".postwrite-verification-" + str(attempt_number).zfill(2)
                verification_started = directory / (stem + "-started-v01.json")
                verification_failed = directory / (stem + "-failure-v01.json")
                if not os.path.lexists(verification_started):
                    if os.path.lexists(verification_failed):
                        return {**held, "repair_reason": "verification failure lacks its immutable start witness"}
                    resume = dict(marker=marker, failure=failure, reference=reference,
                        number=attempt_number, started=verification_started, failed=verification_failed)
                    break
                witness = _capacity_recovery_current_json(verification_started)
                if (witness.get("trigger") != trigger_ref or witness.get("approved_candidate") != marker["approved_candidate"]
                        or witness.get("verification_attempt") != attempt_number
                        or witness.get("original_reconciliation") != reference
                        or witness.get("released_record_sha256") != failure.get("released_record_sha256")
                        or witness.get("bound_attempt_identity") != failure.get("bound_attempt_identity")):
                    return {**held, "repair_reason": "read-only verification start identity changed"}
                if not os.path.lexists(verification_failed):
                    return {**held, "status": "postwrite_verification_interrupted_manual_repair_required",
                        "postwrite_verification_pending": True, "repair_reason": "read-only verification was interrupted; no retry authority"}
                prior = _capacity_recovery_current_json(verification_failed)
                if (prior.get("trigger") != trigger_ref or prior.get("verification_attempt") != attempt_number
                        or prior.get("read_only_postwrite_verification") is not True
                        or prior.get("recovery_API_calls") != 0
                        or prior.get("verification_phase") != "actual_postwrite_census"
                        or prior.get("original_reconciliation") != reference
                        or prior.get("released_record_sha256") != failure.get("released_record_sha256")
                        or prior.get("bound_attempt_identity") != failure.get("bound_attempt_identity")):
                    return {**held, "postwrite_verification_pending": True,
                        "repair_reason": "read-only verification failed outside the census; manual repair required"}
            if resume is None:
                return {**held, "status": "postwrite_verification_attempts_exhausted",
                    "postwrite_verification_pending": True,
                    "repair_reason": "three read-only verification attempts failed; inspect saved failures before manual repair"}
        if resume is not None:
            resume["intent_returned"] = False
            _capacity_recovery_put(resume["started"], dict(trigger=trigger_ref,
                approved_candidate=resume["marker"]["approved_candidate"], verification_attempt=resume["number"],
                original_reconciliation=resume["reference"],
                released_record_sha256=resume["failure"]["released_record_sha256"],
                bound_attempt_identity=resume["failure"]["bound_attempt_identity"], owner_pid=os.getpid()))
            resume["intent_returned"] = True
            result.update(read_only_postwrite_verification=True, postwrite_verification_attempted=True,
                postwrite_verification_pending=True, verification_attempt=resume["number"],
                verification_phase="resume_authority", known_original_API_returned=True,
                original_reconciliation=resume["reference"],
                released_record_sha256=resume["failure"]["released_record_sha256"],
                bound_attempt_identity=resume["failure"]["bound_attempt_identity"])
        helper = resources.DaemonResourceReservation(CAPACITY_RECOVERY_LEDGER,
            roots=CAPACITY_RECOVERY_ROOTS, storage_bytes=1, memory_mb=1,
            require_existing_ledger=True, ledger_lock_timeout_seconds=30)
        eligible = []
        seen = set()
        for item in candidates:
            if type(item) is not dict or set(item) != {"preflight", "review"}:
                raise ValueError("exact preflight/review allowlist entry required")
            if resume is not None and item != resume["marker"]["approved_candidate"]:
                continue
            pre = _capacity_recovery_json(item["preflight"]);review = _capacity_recovery_json(item["review"])
            if (pre.get("schema") not in {"legal-ir-unblock-eaa-retained-claim-prepare/v1",
                    "legal-ir-unblock-a612-retained-claim-prepare/v1", "legal-ir-failed-source-retained-claim-prepare/v1",
                    "legal-ir-unblock-923-retained-claim-prepare/v1"}
                    or pre.get("accepted") is not True or pre.get("completed") is not True
                    or pre.get("source_READ_closed") is not True or pre.get("capacity_policy") != "require_capacity"
                    or pre.get("recovery_API_calls") != 0 or review.get("accepted") is not True
                    or review.get("source_READ_closed") is not True or review.get("preflight") != item["preflight"]
                    or review.get("controller") != pre.get("controller")):
                raise ValueError("closed positive candidate review required")
            rid = pre["reservation_id"]
            if rid in seen:
                raise ValueError("duplicate approved reservation")
            seen.add(rid)
            for source, module in ((pre["source_api"], recovery), (pre["source_resources"], resources)):
                if source["path"] != str(Path(module.__file__).resolve()):
                    raise ValueError("original recovery owner origin differs")
                _checked_job_packet_bytes_v1(source)
            if (pre["source_api"]["sha256"] != "e132d4db0cd5cfce0c8f9fb0e047decd45c7370e98d4a77a0a2635014e5bb84e"
                    or pre["source_resources"]["sha256"] != "4c351874ac6725bfdaf43b9e16b1ceba70d283044e9d59a4588c35f83f1142c0"
                    or pre["source_scheduler"]["path"] != str(Path(resources.native_deadlines.__file__).resolve())
                    or pre["source_scheduler"]["sha256"] != "2c00683202b4a783b5050329caa24a411f83788010baba86d9380123bae7d083"):
                raise ValueError("qualified recovery source generation differs")
            _checked_job_packet_bytes_v1(pre["source_scheduler"])
            if pre["roots"] != [str(root) for root in CAPACITY_RECOVERY_ROOTS]:
                raise ValueError("approved root scope differs")
            with helper._locked():
                row = helper._read()["reservations"].get(rid)
            if resume is not None:
                receipt = _capacity_recovery_current_json(closed)
                if (rid != resume["marker"]["reservation_id"] or row is None or row.get("status") != "released"
                        or row.get("explicit_reconciliation") != receipt
                        or recovery._digest(row) != resume["failure"].get("released_record_sha256")
                        or pre["selected_record"]["attempt_directory"] != resume["failure"].get("bound_attempt_identity")
                        or receipt.get("reconciled_by_pid") != resume["marker"]["owner_pid"]):
                    raise ValueError("known returned closeout released-row or attempt binding changed")
                row = pre["selected_record"]
            elif row is not None and row["status"] == "released":
                continue
            if (row != pre["selected_record"] or recovery._digest(row) != pre["selected_record_sha256"]
                    or row["status"] != "retained" or row.get("external_charges") != {}
                    or row.get("workload") != "canonical_validation" or row.get("scheduler_lane") != "validation"
                    or pre.get("full_storage_claim_bytes") != row["storage_bytes"]):
                raise ValueError("approved retained validation record changed")
            failure = _capacity_recovery_json(pre["original_failure"])
            if (failure.get("schema") != "owned-validation-result/v1" or failure.get("completed") is not False
                    or type(failure.get("returncode")) is not int or failure["returncode"] == 0
                    or failure.get("request_sha256") != row.get("validation_request_sha256")
                    or any(failure.get(key) is not False for key in ("admitted", "Lean_admitted", "authority_granted", "model_weights_downloaded"))
                    or failure.get("watchdog_errors") != [] or failure.get("received_signals") != []
                    or failure.get("process_cleanup_error") is not None
                    or pre["original_failure"]["path"] != str(Path(row["attempt_directory"]["path"]) / "logs/failure.json")):
                raise ValueError("original failed validation classification differs")
            if row.get("process_scope") == "sampled_birth_bound_descendants":
                observation = failure.get("process_observation", {})
                if (observation.get("live_processes") != 0 or observation.get("out_of_group_live_identities") != []
                        or observation.get("tracking_error") != ""):
                    raise ValueError("sampled validation descendants are unresolved")
            elif row.get("process_scope") != "isolated_process_group_only":
                raise ValueError("unsupported retained process observation scope")
            if resources._process(row["owner_pid"]) is not None:
                raise ValueError("original retained owner PID still exists")
            if any(resources._group_usage(child)["live_processes"] for child in [row.get("child"), *row.get("prior_children", [])]):
                raise ValueError("retained child group remains live")
            if row["scheduler_state_path"] != str(CAPACITY_RECOVERY_SCHEDULER_STATE):
                raise ValueError("original native state path differs")
            native_source = Path(existing.__file__).resolve()
            _checked_job_packet_bytes_v1({"path": str(native_source), "bytes": native_source.lstat().st_size,
                "sha256": "d654ab5ed2fec314ea5ac07a662784ab20843b0b2feb56f13989ce1504607776"})
            scheduler = existing.open_existing_scheduler(CAPACITY_RECOVERY_SCHEDULER_STATE,
                CAPACITY_RECOVERY_POLICY_SHA256, inspection_only=True)
            observation = scheduler.inspect_lease(row["native_lease_id"],
                expected_request_id="validation:" + rid, expected_lane="validation",
                expected_owner_pid=row["owner_pid"], bounded_lock_timeout=5)
            if observation["status"] != "absent" or observation["descendant_count"] != 0:
                raise ValueError("retained native custody is not completely absent")
            if row["storage_bytes"] >= deficit:
                eligible.append((row["storage_bytes"], rid, pre, item))
        if not eligible:
            return {**result, "status": "no_sufficient_eligible_reviewed_claim"}
        _, rid, pre, approved = min(eligible, key=lambda value: (value[0], value[1]))
        attempt = resources._safe_path(pre["selected_record"]["attempt_directory"]["path"], directory=True)
        if resources._root_identity(attempt) != pre["selected_record"]["attempt_directory"]:
            raise ValueError("approved attempt identity changed")
        manifest = _capacity_recovery_json(pre["inventory_manifest"])
        files = recovery._durable_inventory(attempt)
        if (not files or manifest != dict(schema="retained-artifact-inventory/v1",
                attempt_directory=pre["selected_record"]["attempt_directory"], artifacts=files)
                or len(files) != pre["artifact_count"] or sum(row["bytes"] for row in files) != pre["artifact_bytes"]):
            raise ValueError("complete approved nonempty inventory differs")
        def verify_postwrite(receipt, reference):
            # Both first return and the bounded later observation use these
            # same original census, identity, inventory and native checks.
            # Administrative closeout observes an existing overage; its returned
            # accounting is explicitly a prewrite projection, never admission.
            if (receipt.get("capacity_policy") != "administrative_closeout"
                    or receipt.get("actual_postwrite_census_required") is not True
                    or receipt.get("cap_changed") is not False
                    or receipt.get("new_reservation_created") is not False
                    or receipt.get("new_resource_lease_acquired") is not False):
                raise ValueError("original administrative closeout contract differs")
            if resources._root_identity(attempt) != pre["selected_record"]["attempt_directory"]:
                raise ValueError("post-close original attempt identity changed before census")
            with helper._locked():
                actual_ledger = helper._read()
                after = actual_ledger["reservations"][rid]
                if (after["status"] != "released" or after.get("explicit_reconciliation") != receipt
                        or receipt.get("previous_record_sha256") != pre["selected_record_sha256"]
                        or receipt.get("artifact_inventory_manifest") != pre["inventory_manifest"]):
                    raise ValueError("original released record readback differs")
                actual_ledger_sha256 = recovery._digest(actual_ledger)
                result.update(verification_phase="actual_postwrite_census",
                    released_record_sha256=recovery._digest(after),
                    bound_attempt_identity=pre["selected_record"]["attempt_directory"],
                    original_reconciliation=reference)
                accounting = recovery._administrative_census(helper, actual_ledger)
                if recovery._digest(helper._read()) != actual_ledger_sha256:
                    raise ValueError("actual ledger changed during postwrite census")
            result["verification_phase"] = "postwrite_identity_and_inventory"
            if resources._root_identity(attempt) != pre["selected_record"]["attempt_directory"]:
                raise ValueError("post-close original attempt identity changed after census")
            if recovery._durable_inventory(attempt) != files:
                raise ValueError("original post-close evidence differs")
            if resources._root_identity(attempt) != pre["selected_record"]["attempt_directory"]:
                raise ValueError("post-close original attempt identity changed after inventory")
            if (resources._process(pre["selected_record"]["owner_pid"]) is not None
                    or any(resources._group_usage(child)["live_processes"] for child in
                        [pre["selected_record"].get("child"), *pre["selected_record"].get("prior_children", [])])):
                raise ValueError("post-close original owner or child custody differs")
            result["verification_phase"] = "postwrite_native_custody"
            observation = scheduler.inspect_lease(pre["selected_record"]["native_lease_id"],
                expected_request_id="validation:" + rid, expected_lane="validation",
                expected_owner_pid=pre["selected_record"]["owner_pid"], bounded_lock_timeout=5)
            if observation["status"] != "absent" or observation["descendant_count"] != 0:
                raise ValueError("post-close original native custody differs")
            postwrite_reference = _capacity_recovery_put(postwrite, dict(
                schema="legal-ir-retained-capacity-actual-postwrite-observation/v1",
                reservation_id=rid, original_reconciliation=reference,
                trigger=trigger_ref, approved_candidate=approved, original_start=_capacity_recovery_watch_pin(started),
                bound_attempt_identity=pre["selected_record"]["attempt_directory"],
                original_owner_identity={"pid": pre["selected_record"]["owner_pid"], "birth": pre["selected_record"]["owner_birth"]},
                reconciled_by_pid=receipt["reconciled_by_pid"],
                selected_record_sha256=recovery._digest(after), ledger_sha256=actual_ledger_sha256,
                actual_postwrite_accounting=accounting, actual_postwrite_census_verified=True,
                postwrite_verification_pending=False, original_native_custody_absent=True,
                complete_artifact_inventory_unchanged=True, capacity_policy="administrative_closeout",
                admitted=False, retry_authorized=False, limits_changed=False,
                fresh_operation_admission_still_required=True))
            return {**result, "status": "one_reviewed_claim_reconciled", "recovery_outcome": "verified_released",
                "reservation_id": rid, "original_reconciliation": reference,
                "postwrite_observation": postwrite_reference, "postwrite_verification_pending": False,
                "actual_postwrite_census_verified": True,
                "fresh_operation_admission_still_required": True}
        if resume is None:
            _capacity_recovery_put(started, dict(trigger=trigger_ref, approved_candidate=approved,
                reservation_id=rid, no_automatic_retry=True, owner_pid=os.getpid()))
        try:
            result["verification_phase"] = "returned_receipt_and_bound_identity"
            if resume is None:
                result.update(recovery_API_calls=1, recovery_API_attempted=True,
                    recovery_outcome="call_outcome_uncertain", postwrite_verification_pending=True)
                receipt = recovery.reconcile_retained_reservation(CAPACITY_RECOVERY_LEDGER,
                    roots=CAPACITY_RECOVERY_ROOTS, reservation_id=rid,
                    expected_record_sha256=pre["selected_record_sha256"], attempt_directory=attempt,
                    expected_artifacts=files, artifacts_durable=True, capacity_policy="administrative_closeout",
                    artifact_inventory_manifest=pre["inventory_manifest"])
                result.update(recovery_API_returned=True, known_original_API_returned=True,
                    recovery_outcome="returned_unverified")
                reference = _capacity_recovery_put(closed, receipt)
            else:
                reference = resume["reference"]
            return verify_postwrite(receipt, reference)
        except BaseException as error:
            _capacity_recovery_put(failed if resume is None else resume["failed"], {**result, "reservation_id": rid,
                "status": "cleanup_failed_or_uncertain", "automatic_retry_allowed": False,
                "manual_outcome_reconciliation_required": True,
                "error_type": type(error).__name__, "error": str(error)[:4000]})
            raise
    except BaseException as error:
        # A completed intent fences even failures in fresh source/row/identity
        # authentication. Missing intent acknowledgement remains interrupted.
        if (resume is not None and resume.get("intent_returned") is True
                and not os.path.lexists(resume["failed"])):
            _capacity_recovery_put(resume["failed"], {**result,
                "reservation_id": resume["marker"]["reservation_id"],
                "status": "cleanup_failed_or_uncertain", "automatic_retry_allowed": False,
                "manual_outcome_reconciliation_required": True,
                "error_type": type(error).__name__, "error": str(error)[:4000]})
        raise
    finally:
        os.close(fd)


CAPACITY_RECOVERY_WATCH_OWNER_SHA256 = frozenset((
    "9bb22d26e9ff2160b6171e8cfac0b445bff0585f5051d43fa7d5783b7099b23e",
    "d272357589581a08d875d9d9b0d275fba5776fb06edb6d03791c591073c8508c",
    "82235104f05fe468a789532c59afea779e270594fdc8c5b1e821bb1e79eb72f4",
    "d710d6662795dd6ab5c98fe5d01c3b9f71d29f67d30463ab7ebbf0a4014226d1"))
CAPACITY_RECOVERY_WATCH_PREFIXES = frozenset(("native-amendment-plan-v", "native-documentary-amendment-plan-v", "native-completion-plan-v", "actual-native-execution-v"))

CAPACITY_RECOVERY_METADATA_OWNER_SHA256 = "d710d6662795dd6ab5c98fe5d01c3b9f71d29f67d30463ab7ebbf0a4014226d1"
CAPACITY_RECOVERY_METADATA_DRIVER = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/comprehensive-plan-review-v01/supervisor-dispatch-integration-v01/unblock-work-v01/native-metadata-executor-v01/runtime-template-v01/controls/native_metadata_cli_driver_v04.py')
CAPACITY_RECOVERY_METADATA_DRIVER_SHA256 = "0e897547db0760298d92e3a64c0705a5f7aa2bff9f2065a5f546c16ee0b76200"
CAPACITY_RECOVERY_METADATA_WATCH_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/legal-ir-programme-review-20261022-05/comprehensive-plan-review-v01/supervisor-dispatch-integration-v01/unblock-work-v01/native-metadata-executor-v01')
CAPACITY_RECOVERY_METADATA_A_ROOT = Path("/home/barberb/lift_coding/external/ipfs_accelerate")
CAPACITY_RECOVERY_METADATA_RUNTIME_ROOT = Path("/home/barberb/lift_coding/.worktrees/legal-ir-native-metadata-executor-20261029")
CAPACITY_RECOVERY_METADATA_TASK_CID = "baguqeerabt7pfpb5p6nuzmftacfjymnruurxqdsitliniynbxcf4na6ueyia"
CAPACITY_RECOVERY_METADATA_WAIT_SCHEMA = "legal-ir-native0102-execution-ROOT-actual-wait/v1"
CAPACITY_RECOVERY_WATCH_WAIT_SCHEMAS = frozenset(("legal-ir-native0101-amendment-ROOT-actual-wait/v1", "legal-ir-native0101-documentary-rebind-ROOT-actual-wait/v1", "legal-ir-native0101-documentary-completion-ROOT-actual-wait/v1", CAPACITY_RECOVERY_METADATA_WAIT_SCHEMA))


def _capacity_recovery_metadata_execution_contract(request):
    """Authenticate only the reviewed0102 pre-actor resource contract.

    This reads finite immutable owner/driver/plan metadata. It never opens a
    native database, grants admission, starts work, or discovers claims.
    """
    pins = request.get("source_sha256")
    budgets = {"cpu_slots": 1, "memory_mb": 1536, "child_process_slots": 8,
        "storage_bytes": 384 * 1024**2, "timeout_seconds": 300}
    if (type(pins) is not dict or not 1 <= len(pins) <= 1024
            or any(type(request.get(key)) is not int or request[key] != value
                   for key, value in budgets.items())
            or request.get("source_roots") != [str(CAPACITY_RECOVERY_METADATA_A_ROOT)]
            or request.get("cwd") != str(ROOT)):
        raise ValueError("0102 metadata execution resource contract differs")
    owners = [path for path, sha in pins.items() if sha == CAPACITY_RECOVERY_METADATA_OWNER_SHA256]
    argv = request.get("argv")
    if (len(owners) != 1 or type(argv) is not list or len(argv) != 7
            or not all(type(part) is str and "\0" not in part and len(part) <= 8192 for part in argv)
            or argv[:3] != ["/home/barberb/lift_coding/.venv/bin/python", "-B", str(CAPACITY_RECOVERY_METADATA_DRIVER)]
            or argv[3] != "--plan" or argv[5] != "--plan-sha256"
            or pins.get(str(CAPACITY_RECOVERY_METADATA_DRIVER)) != CAPACITY_RECOVERY_METADATA_DRIVER_SHA256
            or pins.get(argv[4]) != argv[6]):
        raise ValueError("0102 metadata execution owner or driver contract differs")
    owner = _capacity_recovery_watch_pin(Path(owners[0]))
    driver = _capacity_recovery_watch_pin(CAPACITY_RECOVERY_METADATA_DRIVER)
    plan_pin = _capacity_recovery_watch_pin(Path(argv[4]))
    if (owner["sha256"] != CAPACITY_RECOVERY_METADATA_OWNER_SHA256
            or driver["sha256"] != CAPACITY_RECOVERY_METADATA_DRIVER_SHA256
            or plan_pin["sha256"] != argv[6]):
        raise ValueError("0102 metadata execution source or plan changed")
    plan = _capacity_recovery_json(plan_pin)
    native = plan.get("native_metadata_cli")
    if (plan.get("operation") != "native_metadata_signed_execution_0102_v1"
            or plan.get("task_cid") != CAPACITY_RECOVERY_METADATA_TASK_CID
            or type(plan.get("expected_ready_revision")) is not int or plan["expected_ready_revision"] != 4
            or plan.get("source_owner") != owner or plan.get("driver") != driver
            or type(native) is not dict or native.get("schema") != "native-metadata-cold-cli/v1"
            or native.get("task_cid") != CAPACITY_RECOVERY_METADATA_TASK_CID or native.get("task_id") != "LIR-0102"
            or type(native.get("expected_revision")) is not int or native["expected_revision"] != 4
            or native.get("runtime_root") != str(CAPACITY_RECOVERY_METADATA_RUNTIME_ROOT)
            or native.get("cwd") != str(ROOT)):
        raise ValueError("0102 metadata execution task or purpose contract differs")
    cli_argv = native.get("cli_argv")
    required = {"--task-source-kind": "duckdb", "--authority-mode": "embedded_exclusive",
        "--max-task-attempts": "1", "--execution-slice-task-id": "LIR-0102",
        "--execution-slice-task-cid": CAPACITY_RECOVERY_METADATA_TASK_CID,
        "--native-metadata-execution-task-cid": CAPACITY_RECOVERY_METADATA_TASK_CID,
        "--native-metadata-execution-task-revision": "4"}
    if (type(cli_argv) is not list or not 4 < len(cli_argv) <= 128
            or not all(type(part) is str and "\0" not in part for part in cli_argv)
            or cli_argv[:4] != ["/home/barberb/lift_coding/.venv/bin/python", "-B", "-m",
                "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon"]
            or any(cli_argv.count(flag) != 1 for flag in ("--once", "--implement"))
            or any(cli_argv.count(flag) != 1 or cli_argv.index(flag) + 1 >= len(cli_argv)
                   or cli_argv[cli_argv.index(flag) + 1] != value for flag, value in required.items())):
        raise ValueError("0102 metadata execution finite CLI slice differs")
    return owner



def _capacity_recovery_watch_pin(path):
    """Authenticate bounded durable owner metadata without following aliases."""
    import stat
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    path = resources._safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or not 0 < before.st_size <= 4 * 1024**2):
            raise ValueError("bounded owned unaliased watched metadata required")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(4 * 1024**2 + 1)
        after = os.fstat(fd);named = path.lstat()
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (len(raw) != before.st_size or stamp(before) != stamp(after) or stamp(after) != stamp(named)
                or named.st_nlink != 1 or named.st_uid != os.geteuid()):
            raise ValueError("watched metadata changed during authenticated read")
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _watch_retained_validation_capacity(config_ref):
    """Discover closed original-owner operations in a finite configured frontier.

    Only immediate explicitly named generation families are inspected. Candidate
    reservations are supplied as immutable independently reviewed descriptors;
    this function never discovers candidates by scanning a resource ledger.
    """
    import fcntl
    import re
    import stat
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    config = _capacity_recovery_json(config_ref)
    if (set(config) != {"schema", "watched_operations", "owner_source_pins", "state_directory", "candidates", "resolved"}
            or config["schema"] != "legal-ir-retained-capacity-watch-config/v1"
            or type(config["watched_operations"]) is not list or not 1 <= len(config["watched_operations"]) <= 4
            or type(config["owner_source_pins"]) is not list or not 1 <= len(config["owner_source_pins"]) <= 4
            or type(config["candidates"]) is not list or not 1 <= len(config["candidates"]) <= 16
            or type(config["resolved"]) is not list or len(config["resolved"]) > 16):
        raise ValueError("finite exact retained-capacity watch config required")
    owners = {}
    for pin in config["owner_source_pins"]:
        if pin["sha256"] not in CAPACITY_RECOVERY_WATCH_OWNER_SHA256 or pin["path"] in owners:
            raise ValueError("watch owner must be an explicitly qualified original generation")
        if _capacity_recovery_watch_pin(Path(pin["path"])) != pin:
            raise ValueError("qualified watched owner source changed")
        owners[pin["path"]] = pin["sha256"]
    directory = resources._safe_path(config["state_directory"], directory=True)
    info = directory.lstat()
    if (info.st_uid != os.geteuid() or info.st_mode & 0o022
            or not any(directory == root or root in directory.parents for root in CAPACITY_RECOVERY_ROOTS)):
        raise ValueError("watched state must be owned private original-root bookkeeping")
    roots = set();generations = []
    for declaration in config["watched_operations"]:
        if set(declaration) != {"root", "generation_prefixes", "request_filename"}:
            raise ValueError("exact watched operation root declaration required")
        identity = declaration["root"];root = resources._safe_path(identity["path"], directory=True)
        if (str(root) in roots or resources._root_identity(root) != identity
                or root.lstat().st_uid != os.geteuid() or root.lstat().st_mode & 0o022
                or not any(root == named or named in root.parents for named in CAPACITY_RECOVERY_ROOTS)):
            raise ValueError("watched root identity, ownership or scope differs")
        roots.add(str(root));prefixes = declaration["generation_prefixes"]
        if (type(prefixes) is not list or not 1 <= len(prefixes) <= 3 or len(set(prefixes)) != len(prefixes)
                or not set(prefixes) <= CAPACITY_RECOVERY_WATCH_PREFIXES or declaration["request_filename"] != "request-v01.json"):
            raise ValueError("only explicit original metadata generation families are watched")
        with os.scandir(root) as entries:
            count = 0
            for entry in entries:
                count += 1
                if count > 256:
                    raise ValueError("watched immediate directory entry bound exceeded")
                if not any(re.fullmatch(re.escape(prefix) + r"[0-9]{1,4}", entry.name) for prefix in prefixes):
                    continue
                generation = resources._safe_path(entry.path, directory=True)
                current = generation.lstat()
                if current.st_uid != os.geteuid() or current.st_mode & 0o022:
                    raise ValueError("owned nonshared watched generation required")
                generations.append((str(root), entry.name, generation, declaration))
                if len(generations) > 64:
                    raise ValueError("watched generation bound exceeded")
    result = dict(status="no_new_closed_capacity_trigger", recovery_API_calls=0,
        actor_or_provider_or_task_calls=0, retry_authorized=False, admitted=False, formalized=False,
        outputs_deleted=False, observations=[])
    lock = directory / ".capacity-watch.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd);named = lock.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError("watch instance lock identity differs")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**result, "status": "another_watch_instance_running"}
        for _, name, generation, declaration in sorted(generations):
            wait_path = generation / "root-actual-wait-v01.json"
            if not os.path.lexists(wait_path):
                continue
            # No publication marker exists until all three exact owner files
            # authenticate and the original owner's PID is actually absent.
            try:
                trigger = _capacity_recovery_watch_pin(wait_path)
                wait = _capacity_recovery_json(trigger)
                if (type(wait.get("schema")) is not str or wait.get("schema") not in CAPACITY_RECOVERY_WATCH_WAIT_SCHEMAS
                        or wait.get("actual_wait_completed") is not True or type(wait.get("exit_code")) is not int
                        or type(wait.get("child_pid")) is not int or wait["child_pid"] <= 0):
                    result["observations"].append(dict(generation=str(generation), status="not_a_closed_original_wait"));continue
                if type(wait.get("request")) is not dict or type(wait.get("stdout")) is not dict:
                    raise ValueError("watched request and stdout descriptors must be objects")
                if (wait["request"]["path"] != str(generation / declaration["request_filename"])
                        or wait["stdout"]["path"] != str(generation / "root-owner-stdout-v01.log")):
                    result["observations"].append(dict(generation=str(generation), status="request_or_stdout_locator_outside_exact_operation"));continue
                request = _capacity_recovery_json(wait["request"]);terminal = _capacity_recovery_json(wait["stdout"])
                source_pins = request.get("source_sha256")
                if type(source_pins) is not dict:
                    raise ValueError("watched source pin map must be an object")
                matching = [path for path, sha in owners.items() if source_pins.get(path) == sha]
                if (len(matching) != 1 or request.get("cwd") != str(ROOT)
                        or request.get("schema") != "legal-ir-original-native-control-request/v1"
                        or request.get("purpose") != "native_control_metadata"
                        or terminal.get("schema") != "legal-ir-original-native-control-terminal/v1"
                        or terminal.get("request_sha256") != wait["request"]["sha256"]
                        or type(terminal.get("owner_pid")) is not int or terminal["owner_pid"] != wait["child_pid"]
                        or type(terminal.get("owner_birth")) is not str or not terminal["owner_birth"].isdecimal()
                        or len(terminal["owner_birth"]) > 64 or int(terminal["owner_birth"]) <= 0
                        or any(terminal.get(key) is not True for key in ("original_native_compute_closed", "source_READ_closed", "absolute_resource_operation_deadline_closed"))
                        or terminal.get("cleanup_errors") != [] or terminal.get("received_signals") != []
                        or resources._process(terminal["owner_pid"]) is not None):
                    result["observations"].append(dict(generation=str(generation), status="owner_provenance_or_closed_custody_unresolved"));continue
                new_owner = owners[matching[0]] == CAPACITY_RECOVERY_METADATA_OWNER_SHA256
                new_namespace = (name.startswith("actual-native-execution-v")
                    and wait["schema"] == CAPACITY_RECOVERY_METADATA_WAIT_SCHEMA)
                if new_owner != new_namespace:
                    raise ValueError("0102 metadata execution owner and namespace differ")
                if new_owner:
                    if str(generation.parent) != str(CAPACITY_RECOVERY_METADATA_WATCH_ROOT):
                        raise ValueError("0102 metadata execution root differs")
                    _capacity_recovery_metadata_execution_contract(request)
                _capacity_recovery_watch_pin(Path(wait["request"]["path"]));_capacity_recovery_watch_pin(Path(wait["stdout"]["path"]))
            except (ValueError, KeyError, FileNotFoundError, resources.DaemonResourceError) as error:
                result["observations"].append(dict(generation=str(generation), status="incomplete_or_untrusted_owner_metadata", error=str(error)[:1024]));continue
            slot_key = hashlib.sha256(json.dumps(dict(root=declaration["root"], name=name), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            slot_path = directory / (slot_key + ".watched-operation-v01.json")
            slot = dict(directory=resources._root_identity(generation), request=wait["request"], trigger=trigger, owner_source_path=matching[0])
            if os.path.lexists(slot_path):
                if _capacity_recovery_current_json(slot_path) != slot:
                    result["observations"].append(dict(generation=str(generation), status="closed_generation_was_replaced_or_rewritten"));continue
            else:
                _capacity_recovery_put(slot_path, slot)
            if wait["exit_code"] == 0:
                result["observations"].append(dict(generation=str(generation), status="closed_success_needs_no_capacity_repair"));continue
            try:
                _capacity_recovery_trigger(trigger)
            except (ValueError, KeyError):
                result["observations"].append(dict(generation=str(generation), status="closed_failure_is_not_pre_actor_capacity_refusal"));continue
            observed = _recover_retained_validation_capacity(trigger, config["candidates"], directory, resolved=config["resolved"])
            result["observations"].append(dict(generation=str(generation), result=observed))
            if (observed["recovery_API_calls"] or observed.get("postwrite_verification_attempted") is True
                    or observed.get("postwrite_verification_pending") is True and observed.get("repair_reason")):
                return {**result, "status": observed["status"], "recovery_API_calls": observed["recovery_API_calls"]}
        return result
    finally:
        os.close(fd)


def _capacity_recovery_source_lease_v1(module, lease_path):
    """Return the original decorated lease after binding its body and wrapper."""
    import contextlib
    import types
    name = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_lease"
    function = getattr(module, "source_lease", None)
    body = getattr(function, "__wrapped__", None)
    spec = getattr(module, "__spec__", None)
    if (not isinstance(module, types.ModuleType) or module.__name__ != name
            or Path(getattr(module, "__file__", "")).resolve() != lease_path
            or getattr(spec, "name", None) != name or Path(getattr(spec, "origin", "")).resolve() != lease_path
            or not isinstance(function, types.FunctionType) or not isinstance(body, types.FunctionType)
            or function.__name__ != "source_lease" or body.__name__ != "source_lease"
            or function.__module__ != name or body.__module__ != name
            or body.__globals__ is not module.__dict__
            or Path(body.__code__.co_filename).resolve() != lease_path
            or function.__globals__ is not contextlib.__dict__
            or function.__code__ is not contextlib.contextmanager(body).__code__
            or function.__code__.co_freevars != ("func",)
            or function.__closure__ is None or len(function.__closure__) != 1
            or function.__closure__[0].cell_contents is not body):
        raise ValueError("original decorated source lease module, body or wrapper origin differs")
    return function


def recover_retained_validation_capacity_main_v1(argv):
    """Explicit cleanup command; separate from every task/provider command."""
    import time
    parser = argparse.ArgumentParser(description="Reconcile at most one explicitly reviewed stopped validation storage claim; never retry a task.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--trigger", help="Exact path/bytes/SHA256 JSON descriptor of the genuine failed owner wait.")
    mode.add_argument("--watch-config", help="Exact immutable finite original-owner frontier/config descriptor JSON.")
    parser.add_argument("--candidate", action="append", default=[], help="Exact existing preflight/review descriptor pair JSON; at most16.")
    parser.add_argument("--resolved-trigger", action="append", default=[], help="Exact authenticated manual closeout/genuine-reap descriptor pair JSON.")
    parser.add_argument("--state-directory", type=Path)
    parser.add_argument("--expected-cli-sha256", required=True)
    args = parser.parse_args(argv)
    if args.watch_config:
        if args.candidate or args.resolved_trigger or args.state_directory is not None:
            raise ValueError("watched policy owns its exact finite candidates, lineage and state")
    elif not args.candidate or args.state_directory is None:
        raise ValueError("explicit trigger requires reviewed candidates and private state directory")
    source = Path(__file__).resolve()
    own_pin = {"path": str(source), "bytes": source.lstat().st_size, "sha256": args.expected_cli_sha256}
    _checked_job_packet_bytes_v1(own_pin)
    lease_path = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_source_lease.py"
    lease_pin = {"path": str(lease_path), "bytes": lease_path.lstat().st_size,
        "sha256": "42e9f07d0d458177079269d9f495f0b70512180c1adc2f7fe0bfdb05518a12f9"}
    _checked_job_packet_bytes_v1(lease_pin)
    os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
        IPFS_AUTO_INSTALL="false", PYTHONDONTWRITEBYTECODE="1")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_lease as lease_module
    source_lease = _capacity_recovery_source_lease_v1(lease_module, lease_path)
    deadline = time.monotonic() + 240
    with source_lease(ROOT, mode="read", timeout_seconds=30):
        _checked_job_packet_bytes_v1(own_pin);_checked_job_packet_bytes_v1(lease_pin)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import resource_cleanup_deadline
        with resource_cleanup_deadline(native_deadline_monotonic=deadline):
            if args.watch_config:
                result = _watch_retained_validation_capacity(_capacity_recovery_decode(args.watch_config))
            else:
                result = _recover_retained_validation_capacity(_capacity_recovery_decode(args.trigger),
                    [_capacity_recovery_decode(value) for value in args.candidate], args.state_directory,
                    resolved=[_capacity_recovery_decode(value) for value in args.resolved_trigger])
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "recover-retained-validation-capacity":
        return recover_retained_validation_capacity_main_v1(effective_argv[1:])
    if effective_argv and effective_argv[0] == "asset-inventory-0101":
        return asset_inventory_0101_main_v1(effective_argv[1:])
    if effective_argv and effective_argv[0] == "job-packet-index":
        return job_packet_index_main_v1(effective_argv[1:])
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
    shard_count = int(getattr(args, "task_shard_count", 1) or 1)
    shard_index = int(getattr(args, "task_shard_index", 0) or 0)
    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("task shard index must be in range [0, task_shard_count)")
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
        "--state-prefix", "autoformal" if shard_count == 1 else f"autoformal-s{shard_index}",
        "--task-source-kind", "duckdb",
        "--authority-mode", "embedded",
        "--state-store-id", "autoformal-" + hashlib.sha256(str(database).encode()).hexdigest()[:16]
        + ("" if shard_count == 1 else f"-s{shard_index}"),
        "--state-failover-policy", "fail_closed",
        "--worktree-root", str(runtime / "worktrees"),
        "--merge-queue-dir", str(runtime / "merge-queue"),
        "--interval", str(args.interval),
        "--implementation-timeout", str(args.implementation_timeout),
        "--max-task-attempts", "3", "--implement",
        "--merged-worktree-cleanup-max", "0",
        "--retain-worktree-artifacts",
    ]
    if shard_count > 1:
        native_args += [
            "--task-shard-count", str(shard_count),
            "--task-shard-index", str(shard_index),
            "--strict-task-sharding",
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
                for task in source.list_tasks(status="in_progress", limit=100).tasks
                if task.body.get("board_namespace") == NAMESPACE
                and (
                    shard_count == 1
                    or task_alias_shard_index(task.task_alias, shard_count) == shard_index
                )
            ]
            if len(inflight) > 1:
                raise ValueError("more than one in-progress repair is open in this shard")
            if len(inflight) == 1:
                args.task_id = inflight[0].task_alias
            elif shard_count > 1:
                ready = [
                    task for task in source.ready_tasks(limit=1000).tasks
                    if task.body.get("board_namespace") == NAMESPACE
                    and task_alias_shard_index(task.task_alias, shard_count) == shard_index
                ]
                if ready:
                    args.task_id = ready[0].task_alias
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
