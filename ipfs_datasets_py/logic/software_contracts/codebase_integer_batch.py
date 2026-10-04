"""Owner-thread coordination for bounded parallel conditional integer checks.

Workers receive source bytes and declarative contracts. Native SQL, cache and
CAS access remain on the calling thread. Indexed observations stay historical;
every batch performs fresh checks and fences delivery against the current source.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import time
from typing import Any

from .codebase_integer_profile import PROFILE, COMPILED_SCHEMA, IntegerOffsetContract
from .codebase_integer_verification import CodebaseIntegerVerifier, CodebaseVerificationError, _new_result
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_structured
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLease, ResourceLane, ResourceUnavailableError,
    LeaseCancelledError, LeaseTimeoutError, get_global_resource_scheduler,
)

SCHEMA = "codebase-integer-batch@1"
MAX_CONTRACTS = 64
MAX_WORKERS = 32
DEFAULT_MAX_WORKERS = 4


def _controls(contracts, scheduler, parent_lease, max_workers, memory_mb):
    if type(contracts) not in {list, tuple} or not 1 <= len(contracts) <= MAX_CONTRACTS:
        raise CodebaseVerificationError("contracts must be a list/tuple of 1–64 native contracts")
    if any(type(item) is not IntegerOffsetContract for item in contracts):
        raise CodebaseVerificationError("all contracts must be exact IntegerOffsetContract values")
    copied = [IntegerOffsetContract.from_dict(item.to_dict()) for item in contracts]
    if scheduler is not None and parent_lease is not None:
        raise CodebaseVerificationError("choose scheduler or parent_lease, not both")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise CodebaseVerificationError("scheduler must be a datasets scheduler")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise CodebaseVerificationError("parent must be a datasets resource lease")
    if max_workers is not None and (type(max_workers) is not int or not 1 <= max_workers <= MAX_WORKERS):
        raise CodebaseVerificationError("max_workers must be an exact integer in 1–32")
    if memory_mb is not None and (type(memory_mb) is not int or memory_mb < 1024):
        raise CodebaseVerificationError("batch memory must be an exact integer of at least 1024 MiB")
    if parent_lease is not None:
        cpu, processes, memory = parent_lease.cpu_slots, parent_lease.child_process_slots, parent_lease.memory_mb
        owner = None
    else:
        owner = scheduler if scheduler is not None else get_global_resource_scheduler()
        config = owner.config
        reservations = config.reservations()
        others = [r for lane, r in reservations.items() if lane != ResourceLane.SNAPSHOT_EVALUATION.value]
        cpu = config.total_cpu_slots - sum(r.cpu_slots for r in others)
        memory = config.total_memory_mb - config.reserved_memory_mb - sum(r.memory_mb for r in others)
        processes = config.total_child_process_slots
    if memory_mb is not None:
        memory = min(memory, memory_mb)
    width = min(max_workers or DEFAULT_MAX_WORKERS, len({item.cid for item in copied}),
                cpu, processes, (memory - 512) // 512)
    if width < 1:
        raise ResourceUnavailableError("batch needs one CPU/process and at least 1024 MiB in its envelope")
    reservation = memory_mb if memory_mb is not None else 512 + 512 * width
    # An explicit cap is also the requested reservation, never silently expanded.
    if reservation > memory:
        raise ResourceUnavailableError("requested memory exceeds the batch owner envelope")
    return copied, owner, width, reservation


def verify_integer_batch(
    verifier: CodebaseIntegerVerifier, repository: str | Path, *, expected_head: Any,
    contracts: Any, scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
    admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
    max_workers: int | None = None, memory_mb: int | None = None, evidence_index: Any = None,
) -> dict[str, Any]:
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
    from .codebase_integer_workers import IntegerCheckJob, run_integer_checks

    if type(verifier) is not CodebaseIntegerVerifier or type(expected_head) is not CodebaseHead:
        raise CodebaseVerificationError("native verifier and canonical current head required")
    for name, value, allow_zero in (("timeout_seconds", timeout_seconds, False),
                                    ("admission_timeout_seconds", admission_timeout_seconds, True)):
        if (type(value) not in {int, float} or not math.isfinite(value)
                or value < 0 or (not allow_zero and value == 0)):
            raise CodebaseVerificationError(name + " must be finite and within its positive bound")
    if timeout_seconds > 600:
        raise CodebaseVerificationError("batch overall timeout must not exceed 600 seconds")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise CodebaseVerificationError("cancel_event must provide is_set()")
    if evidence_index is not None and (type(evidence_index) is not CodebaseEvidenceIndex
                                       or evidence_index.catalog is not verifier.index.catalog):
        raise CodebaseVerificationError("evidence index must share this exact current catalog owner")
    deadline = time.monotonic() + timeout_seconds
    requests, owner, width, memory = _controls(contracts, scheduler, parent_lease, max_workers, memory_mb)
    with acquire_codebase_resources(
        scheduler=owner, parent_lease=parent_lease, cancel_event=cancel_event,
        timeout_seconds=min(admission_timeout_seconds, max(0, deadline - time.monotonic())),
        memory_mb=memory, cpu_slots=width, child_process_slots=width,
    ) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)

        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("integer batch cancelled")
            value = deadline - time.monotonic()
            if value <= 0:
                raise LeaseTimeoutError("integer batch overall deadline exceeded")
            return value

        def observe():
            duration = remaining()
            return verifier.index.observe_current(
                repository, expected_head=expected_head, parent_lease=lease, cancel_event=signal,
                timeout_seconds=duration, admission_timeout_seconds=min(admission_timeout_seconds, duration),
                memory_mb=512,
            )

        observation = observe()
        entries = {entry.path: entry for entry in observation.manifest.snapshot.entries}
        unique = {contract.cid: contract for contract in requests}
        staged, jobs = {}, []
        for key, contract in unique.items():
            remaining()
            result = _new_result(expected_head, contract)
            staged[key] = result
            entry = entries.get(contract.path)
            if entry is None or entry.is_opaque:
                result["diagnostics"] = ["selected source is absent or opaque in the current snapshot"]
                continue
            result["source_cid"] = entry.source_cid
            if entry.size_bytes > 64 * 1024:
                result["diagnostics"] = ["source exceeds the 64 KiB integer profile bound"]
                continue
            source = verifier.index.artifacts.get_bytes(entry.source_cid)
            if len(source) != entry.size_bytes:
                raise CodebaseVerificationError("captured source length differs")
            jobs.append(IntegerCheckJob(key, source, contract, "snapshot:" + expected_head.snapshot_cid))
        outcomes = run_integer_checks(
            jobs, parent_lease=lease, max_workers=width, cancel_event=signal,
            timeout_seconds=remaining(), per_check_timeout_seconds=10.0,
        ) if jobs else []
        remaining()
        if type(outcomes) is not list or len(outcomes) != len(jobs):
            raise CodebaseVerificationError("worker result inventory differs from admitted jobs")
        for job, outcome in zip(jobs, outcomes):
            remaining()
            if type(outcome) is not dict or outcome.get("job_id") != job.job_id:
                raise CodebaseVerificationError("worker result belongs to another job")
            result = staged[job.job_id]
            compiled, checks = outcome.get("compiled"), outcome.get("checks")
            if compiled is None:
                if outcome.get("status") != "unsupported" or checks is not None:
                    raise CodebaseVerificationError("missing native compilation for supported outcome")
                diagnostics = outcome.get("diagnostics")
                if (type(diagnostics) is not list or len(diagnostics) > 8
                        or any(type(item) is not str or len(item.encode()) > 4096 for item in diagnostics)):
                    raise CodebaseVerificationError("unsupported diagnostics exceed their bound")
                result["diagnostics"] = diagnostics
                continue
            if (type(compiled) is not dict or compiled.get("schema") != COMPILED_SCHEMA
                    or compiled.get("profile") != PROFILE or compiled.get("source_cid") != result["source_cid"]
                    or canonical_dag_json_bytes(compiled.get("contract")) != canonical_dag_json_bytes(result["contract"])
                    or compiled.get("contract_cid") != result["contract_cid"]
                    or compiled.get("revision") != job.revision):
                raise CodebaseVerificationError("worker compilation does not bind its captured job")
            compiled_cid = verifier.index.artifacts.put(compiled)
            if compiled_cid != cid_for_structured(compiled):
                raise CodebaseVerificationError("worker compilation changed during sealing")
            result["compiled_cid"] = compiled_cid
            verifier._accept_checks(result, checks)
            if outcome.get("status") != result["status"]:
                raise CodebaseVerificationError("worker aggregate status differs from its checks")
        receipts = {}
        for key, result in staged.items():
            remaining()
            receipts[key] = {**result, "receipt_cid": verifier.index.artifacts.put(result)}
        # No owner database call occurred in a worker. All checks have joined
        # before this current-source fence and native publication transaction.
        observe()
        if evidence_index is None:
            evidence_index = CodebaseEvidenceIndex(verifier.index.catalog)
        terminal = sorted({value["receipt_cid"] for value in receipts.values()
                           if value["status"] in {"proved", "refuted"}})
        if terminal:
            evidence_index.publish_many(terminal, expected_head=expected_head, checkpoint=remaining)
        result = {
            "schema": SCHEMA, "profile": PROFILE, "head": expected_head.to_dict(),
            "requested_contracts": [contract.to_dict() for contract in requests],
            "results": [receipts[contract.cid] for contract in requests],
            "max_workers": width, "memory_mb": memory, "unique_contracts": len(unique),
            "solver_jobs": sum(value["solver_check_attempted"] for value in receipts.values()),
            "cache_history_hits": sum(value["cache_history_hit"] for value in receipts.values()),
            "evidence_receipt_cids": terminal,
            "evidence_publication": {"schema": "codebase-integer-index-publication@1",
                                     "receipt_cids": terminal, "authority": "historical_conditional",
                                     "requires_fresh_native_checks": True},
            "kernel_checked": False, "behavior_authority": False,
            "execution_authority": False, "completion_authority": False,
            "evidence_scope": "conditional_integer_contract",
        }
        remaining()
        receipt_cid = verifier.index.artifacts.put(result)
        observe()
        remaining()
        # Detach aliases introduced by duplicate contracts in the request.
        return {**json.loads(canonical_dag_json_bytes(result)), "receipt_cid": receipt_cid}


__all__ = ["SCHEMA", "verify_integer_batch"]
