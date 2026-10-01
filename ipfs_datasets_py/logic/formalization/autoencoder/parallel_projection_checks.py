"""Shared proof-resource scheduling for native training-target checks.

All native projections still go through their existing source-replaying Lake
owner. Optional propositional diagnostics use the real Hammer SolverPortfolio
on the same host-local scheduler. Neither diagnostic solver verdicts nor this
batch receipt grant source fidelity, admission, or training qualification.

Native resource leases reserve capacity; they do not impose a hard aggregate
RSS or thread ceiling inside Lake. Existing native owners enforce their own
subprocess time/output/workspace limits. Timeouts here are per native step and
per lease wait, not a purported wall deadline for the entire batch.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, field
from functools import reduce
import hashlib
import json
import math
from pathlib import Path
import re
import time

from . import native_family_lake_v5 as native
from . import projection_validation_contract_v5 as validation
from ...hammers import models, policy, portfolio, translation
from ...parsers import modal
from ....optimizers.logic_theorem_optimizer import resource_scheduler as resources

SCHEMA = "parallel-native-projection-checks/v1"
MAX_ITEM_BYTES = 32 * 1024 * 1024
MAX_BATCH_BYTES = 128 * 1024 * 1024
FALSE = {"admitted": False, "qualified": False, "formalized": False,
         "roundtrip_ok": False, "source_semantics_verified": False,
         "training_executed": False, "checkpoint_promoted": False}
_MODULES = (native, validation, models, policy, portfolio, translation, modal, resources)
_PINS = {str(Path(m.__file__).resolve()): hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
         for m in _MODULES}
_PINS[str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _guard():
    native._guard()
    for path, digest in _PINS.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError("parallel projection producer changed after import")


def _identifier(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value) is None:
        raise ValueError("bounded path-safe unique job identifier required")
    return value


def _integer(value, name, upper=65536):
    if type(value) is not int or not 1 <= value <= upper:
        raise ValueError(name + " must be a bounded positive integer")


def _seconds(value, name, upper):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= upper:
        raise ValueError(name + " must be positive, finite and bounded")


@dataclass(frozen=True)
class NativeProjectionJob:
    job_id: str
    report: dict
    source_inputs: dict
    applicability_review: tuple = ()


@dataclass(frozen=True)
class PortfolioDiagnosticJob:
    """Diagnose exactly one native propositional target; no arbitrary formulas.

    The owning report is replayed against original typed source inputs. Its
    native AST is reparsed and translated into the selected solver formats.
    The association with source meaning remains unverified.
    """
    job_id: str
    target_job_id: str
    projection_id: str
    solver_names: tuple = ("z3", "cvc5")
    executable_overrides: dict = field(default_factory=dict)


def _propositional_term(node, depth=0):
    if depth > 64 or node.get("binders"):
        raise ValueError("bounded binder-free propositional AST required")
    kind, arguments = node["kind"], node["arguments"]
    if kind == "predicate" and not arguments:
        return translation.Const(node["symbol"], translation.PROP_SORT)
    if kind in ("true", "false") and not arguments:
        return translation.BoolLit(kind == "true")
    children = [_propositional_term(child, depth + 1) for child in arguments]
    if kind == "not" and len(children) == 1:
        return translation.Not(children[0])
    if kind in ("and", "or") and len(children) >= 2:
        return reduce(translation.And if kind == "and" else translation.Or, children)
    if kind in ("implies", "iff") and len(children) == 2:
        return (translation.Implies if kind == "implies" else translation.Iff)(*children)
    raise ValueError("unsupported native propositional operator: " + str(kind))


def _diagnostic(job, target, solver_timeout_seconds, solver_memory_mb, max_workers):
    if type(job) is not PortfolioDiagnosticJob:
        raise ValueError("typed PortfolioDiagnosticJob required")
    _identifier(job.job_id)
    if type(job.solver_names) not in (tuple, list) or not 1 <= len(job.solver_names) <= 4:
        raise ValueError("one to four explicit solver names required")
    if len(set(job.solver_names)) != len(job.solver_names):
        raise ValueError("duplicate solver names forbidden")
    if type(job.executable_overrides) is not dict or set(job.executable_overrides) - set(job.solver_names):
        raise ValueError("executable overrides must refer to requested solvers")
    rows = [row for row in target.report["projections"] if row["projection_id"] == job.projection_id]
    if len(rows) != 1:
        raise ValueError("diagnostic requires exactly one existing target projection")
    row = rows[0]
    payload = row["payload"]
    if row["logic_family"] != "propositional" or payload.get("ast_format") != "shared_logic":
        raise ValueError("diagnostic currently supports explicit native propositional targets only")
    parsed = modal.parse_modal(payload["printed"], modal.profile_k())
    if not parsed.ok or parsed.diagnostics or parsed.root.to_dict() != payload["native_ast"]:
        raise ValueError("diagnostic native AST differs from exact target parser replay")
    term = _propositional_term(parsed.root.to_dict())
    attempts, translations = [], []
    owner = translation.TranslationContext(request_id=job.job_id)
    for solver in job.solver_names:
        spec = policy.solver_spec(solver)
        record = owner.translate(source_construct="projection:" + row["target_sha256"], term=term, target=spec.target)
        if record.status is not models.TranslationStatus.SUPPORTED or record.obligations:
            raise ValueError("complete native propositional translation required")
        attempts.append(portfolio.PortfolioAttemptSpec(translation=record, solver_name=solver))
        translations.append(record.to_dict())
    run_policy = policy.PortfolioPolicy(
        hammer_policy=models.HammerPolicy(timeout_seconds=solver_timeout_seconds,
            allowed_solvers=list(job.solver_names), network_allowed=False),
        solver_budgets={name: policy.SolverBudget(timeout_seconds=solver_timeout_seconds,
            memory_mb=solver_memory_mb, cpu_seconds=solver_timeout_seconds) for name in job.solver_names},
        executable_overrides=dict(job.executable_overrides),
        max_parallel_processes=min(max_workers, len(job.solver_names)), cancel_on_first_conclusive=False)
    run_policy.validate()
    binding = {"target_job_id": target.job_id, "domain_id": target.report["domain_id"],
        "source_digest": target.report["source_digest"], "source_sha256": target.report.get("source_sha256"),
        "report_sha256": _digest(target.report), "projection_id": row["projection_id"],
        "target_sha256": row["target_sha256"], "payload_sha256": _digest(payload),
        "relation": "exact_propositional_native_ast_translation", "source_meaning_relation_verified": False,
        "translations": translations,
        "verdict_scope": "SMT inputs assert the formula: SAT is satisfiability, not a proof of validity; ATP uses its documented target semantics."}
    return attempts, run_policy, binding


def run_parallel_projection_checks(native_jobs, *, portfolio_jobs=(), scheduler=None, max_workers=2,
        native_memory_mb=1024, native_cpu_slots=2, native_child_process_slots=2,
        lease_wait_timeout_seconds=30, native_step_timeout_seconds=60,
        lake_executable, output_directory, java_executable=None, tla2tools_jar=None,
        solver_timeout_seconds=15, solver_memory_mb=256):
    """Run every requested native job and diagnostic with one shared scheduler.

    Return ordered live native handles/observations under ``jobs`` plus a JSON
    ``receipt``. Saved JSON cannot reconstruct live gate authority. Failed or
    denied jobs remain explicit rows; no backend substitution is attempted.
    """
    _guard()
    _integer(max_workers, "max_workers", 32)
    for name, value in (("native_memory_mb", native_memory_mb), ("native_cpu_slots", native_cpu_slots),
                        ("native_child_process_slots", native_child_process_slots), ("solver_memory_mb", solver_memory_mb)):
        _integer(value, name)
    _seconds(lease_wait_timeout_seconds, "lease_wait_timeout_seconds", 300)
    _seconds(native_step_timeout_seconds, "native_step_timeout_seconds", 60)
    _seconds(solver_timeout_seconds, "solver_timeout_seconds", 60)
    if type(native_jobs) not in (tuple, list) or not 1 <= len(native_jobs) <= 384:
        raise ValueError("one to 384 explicit native jobs required")
    if type(portfolio_jobs) not in (tuple, list) or len(portfolio_jobs) > 384:
        raise ValueError("bounded portfolio jobs required")
    jobs, seen, batch_bytes = [], set(), 0
    for item in native_jobs:
        if type(item) is not NativeProjectionJob:
            raise ValueError("typed NativeProjectionJob required")
        key = _identifier(item.job_id)
        if key in seen:
            raise ValueError("duplicate job identifier")
        seen.add(key)
        encoded = _raw(item.report)
        if len(encoded) > MAX_ITEM_BYTES:
            raise ValueError("native report exceeds item byte bound")
        source_bytes, _, _ = native.v2._source_bytes(item.report["domain_id"], item.source_inputs)
        if len(source_bytes) > MAX_ITEM_BYTES:
            raise ValueError("native source exceeds item byte bound")
        batch_bytes += len(encoded) + len(source_bytes)
        if batch_bytes > MAX_BATCH_BYTES:
            raise ValueError("native batch exceeds aggregate byte bound")
        # Retain owner-issued typed source objects (some contain MappingProxy).
        # Their exact replay is checked by the native owner before/after build.
        job = NativeProjectionJob(key, json.loads(encoded), dict(item.source_inputs), deepcopy(item.applicability_review))
        # Preload domain producers serially; fail before any subprocess runs.
        native.prepare_native_family_lean(job.report, source_inputs=job.source_inputs)
        jobs.append(job)
    by_id = {job.job_id: job for job in jobs}
    diagnostics = []
    for original in portfolio_jobs:
        item = deepcopy(original)
        if type(item) is not PortfolioDiagnosticJob or item.target_job_id not in by_id:
            raise ValueError("diagnostic must reference an exact native batch job")
        key = _identifier(item.job_id)
        if key in seen:
            raise ValueError("duplicate job identifier")
        seen.add(key)
        diagnostics.append((item, *_diagnostic(item, by_id[item.target_job_id],
            solver_timeout_seconds, solver_memory_mb, max_workers)))
    scheduler = scheduler or resources.get_global_resource_scheduler()
    if not isinstance(scheduler, resources.GlobalResourceScheduler) or not scheduler.config.proof_safety_enabled:
        raise ValueError("shared GlobalResourceScheduler with proof safety enabled required")
    before = scheduler.snapshot()
    other = [value for lane, value in scheduler.config.reservations().items() if lane != resources.ResourceLane.VALIDATION.value]
    capacity = min((scheduler.config.total_cpu_slots - sum(v.cpu_slots for v in other)) // native_cpu_slots,
        (scheduler.config.total_memory_mb - scheduler.config.reserved_memory_mb - sum(v.memory_mb for v in other)) // native_memory_mb,
        scheduler.config.total_child_process_slots // native_child_process_slots)
    if capacity < 1:
        raise ValueError("native worker envelope does not fit scheduler capacity")
    available = min(before["available"]["cpu_slots"] // native_cpu_slots,
        before["available"]["memory_mb"] // native_memory_mb,
        before["available"]["child_process_slots"] // native_child_process_slots)
    workers = min(max_workers, len(jobs) + len(diagnostics), capacity, max(1, available))
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()

    def execute_native(job):
        queued = time.monotonic()
        with scheduler.acquire(resources.ResourceLane.VALIDATION, cpu_slots=native_cpu_slots,
                memory_mb=native_memory_mb, child_process_slots=native_child_process_slots,
                timeout=lease_wait_timeout_seconds, request_id="native:" + job.job_id) as lease:
            begun = time.monotonic()
            _guard()
            handle = native.build_native_family_lake(job.report, source_inputs=job.source_inputs,
                lake_executable=lake_executable, output_directory=output / job.job_id,
                java_executable=java_executable, tla2tools_jar=tla2tools_jar,
                timeout_seconds=native_step_timeout_seconds)
            observation = validation.validate_projection_report(job.report, lake_execution=handle,
                applicability_review=job.applicability_review)
            _guard()
            wire = handle.to_dict()
            receipt = {"job_id": job.job_id, "kind": "native_projection", "domain_id": job.report["domain_id"],
                "status": "completed", "native_status": wire["status"],
                "report_sha256": _digest(job.report), "native": wire,
                "projection_validation": observation.to_dict(),
                "queued_offset_seconds": queued - started, "started_offset_seconds": begun - started,
                "finished_offset_seconds": time.monotonic() - started,
                "lease": {"lane": lease.lane, "cpu_slots": lease.cpu_slots, "memory_mb": lease.memory_mb,
                    "child_process_slots": lease.child_process_slots, "wait_seconds": lease.wait_seconds}, **FALSE}
            return {"job_id": job.job_id, "native_execution": handle, "observation": observation, "report": job.report, "receipt": receipt}

    def execute_diagnostic(item):
        job, attempts, run_policy, binding = item
        begun = time.monotonic()
        target = by_id[job.target_job_id]
        _guard()
        native.prepare_native_family_lean(target.report, source_inputs=target.source_inputs)
        runner = portfolio.SolverPortfolio(run_policy, resource_scheduler=scheduler,
            resource_lane=resources.ResourceLane.HAMMER_LEAN.value,
            resource_wait_timeout_seconds=lease_wait_timeout_seconds)
        result = runner.run(job.job_id, attempts)
        native.prepare_native_family_lean(target.report, source_inputs=target.source_inputs)
        _guard()
        receipt = {"job_id": job.job_id, "kind": "portfolio_diagnostic", "status": "completed",
            "binding": binding, "portfolio": result.to_dict(), "started_offset_seconds": begun - started,
            "finished_offset_seconds": time.monotonic() - started, **FALSE}
        (output / (job.job_id + ".json")).write_bytes(_raw(receipt))
        return {"job_id": job.job_id, "portfolio_result": result, "receipt": receipt}

    results = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="native-projection") as executor:
        diagnostics_by_target = {}
        for item in diagnostics:
            diagnostics_by_target.setdefault(item[0].target_job_id, []).append(item)
        futures = {}
        for job in jobs:
            futures[executor.submit(execute_native, job)] = job.job_id
            # Each path replays its exact target independently. Interleave
            # submissions so native jobs cannot starve their diagnostics.
            for item in diagnostics_by_target.get(job.job_id, ()):
                futures[executor.submit(execute_diagnostic, item)] = item[0].job_id
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                results[key] = {"job_id": key, "receipt": {"job_id": key, "status": "failed", "error_type": type(exc).__name__,
                    "reason": str(exc)[:2000], **FALSE}}
    _guard()
    ordered = [results[job.job_id] for job in jobs] + [results[item[0].job_id] for item in diagnostics]
    receipt = {"schema": SCHEMA, "jobs": [row["receipt"] for row in ordered],
        "requested_workers": max_workers, "effective_workers": workers, "native_job_count": len(jobs),
        "input_bytes_accounted": batch_bytes, "max_batch_bytes": MAX_BATCH_BYTES,
        "portfolio_job_count": len(diagnostics), "elapsed_seconds": time.monotonic() - started,
        "producer": dict(_PINS), "scheduler_before": before, "scheduler_after": scheduler.snapshot(),
        "scheduler_state_path": str(scheduler.state_path), "proof_safety_enabled": True,
        "resource_scope": "native leases reserve capacity; native RSS and internal thread ceilings are not enforced by this adapter",
        "timeout_scope": "per native subprocess step, solver attempt, and lease wait; no batch wall deadline",
        "all_jobs_completed": all(row["receipt"]["status"] == "completed" for row in ordered), **FALSE}
    (output / "receipt.json").write_bytes(_raw(receipt))
    return {"jobs": ordered[:len(jobs)], "portfolio_jobs": ordered[len(jobs):], "receipt": receipt}


__all__ = ["SCHEMA", "NativeProjectionJob", "PortfolioDiagnosticJob", "run_parallel_projection_checks"]
