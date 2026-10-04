"""Current-source, conditional integer contracts with fresh bounded checking.

This owner composes the structural catalog, existing source/VC/SMT pipeline,
native bounded solver execution and historical cache. A cache hit never grants
proof authority: every supported verification rederives and executes its checks.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import time
from typing import Any

from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .content import cid_for_structured

SCHEMA = "codebase-integer-verification@1"
_TERMINAL_STATUSES = {"proved", "refuted"}
_STATUSES = _TERMINAL_STATUSES | {
    "unknown", "timeout", "unavailable", "disagreement", "unsupported", "error",
}


class CodebaseVerificationError(ValueError):
    """Malformed or inconsistent current-source checking evidence."""


def _implementation_identity() -> dict[str, str]:
    # These are installed owner sources, never files from the repository tested.
    base = Path(__file__).resolve().parent
    paths = [Path(__file__).resolve(), base / "codebase_integer_profile.py",
             base / "codebase_property_cache.py", base / "codebase_ir.py",
             base / "codebase_integer_batch.py", base / "codebase_integer_workers.py",
             base.parent / "software_verification/pipeline.py",
             base.parent / "software_verification/source_adapters.py",
             base.parent / "software_verification/vc.py",
             base.parent / "backends/process.py"]
    result = {}
    for path in paths:
        with path.open("rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise CodebaseVerificationError("checker implementation source exceeds its bound")
        result[str(path.relative_to(base.parent))] = hashlib.sha256(raw).hexdigest()
    return result


def _new_result(expected_head: Any, contract: Any) -> dict[str, Any]:
    from .codebase_integer_profile import PROFILE
    result = {
        "schema": SCHEMA, "profile": PROFILE, "status": "unsupported",
        "head": expected_head.to_dict(), "contract": contract.to_dict(),
        "contract_cid": contract.cid, "source_cid": None,
        "compiled_cid": None, "checks": None, "cache_binding": None,
        "cache_history_hit": False, "solver_check_attempted": False, "solver_replayed": False,
        "kernel_checked": False, "behavior_authority": False,
        "execution_authority": False, "completion_authority": False,
        "evidence_scope": "conditional_integer_contract", "diagnostics": [],
    }
    return result


class CodebaseIntegerVerifier:
    """Verify an explicit typed contract against an exact current catalog head.

    Native execution has solver assurance within the declared profile. It is
    not kernel reconstruction, general Python equivalence or worker admission.
    A supplied parent remains owned by the caller; native checks use descendants
    of this call's shared reservation.
    """

    def __init__(self, index: RepositoryCodebaseIndex, cache: Any = None) -> None:
        from .codebase_property_cache import CodebasePropertyCache

        if type(index) is not RepositoryCodebaseIndex or index.catalog is None or index.artifacts is None:
            raise CodebaseVerificationError("verification requires a native current codebase owner")
        if cache is not None and type(cache) is not CodebasePropertyCache:
            raise CodebaseVerificationError("cache must be a CodebasePropertyCache")
        self.index, self.cache = index, cache

    def _accept_checks(self, result: dict[str, Any], checks: dict[str, Any]) -> None:
        """Bind fresh internal checker output to the complete owner request."""
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        from .codebase_integer_profile import PROFILE, RESULT_SCHEMA, ASSUMPTIONS
        from .codebase_property_cache import build_codebase_property_binding

        expected_head = CodebaseHead.from_dict(result["head"])
        if (type(checks) is not dict or checks.get("schema") != RESULT_SCHEMA
                or checks.get("profile") != PROFILE
                or checks.get("status") not in _STATUSES
                or checks.get("compiled_cid") != result["compiled_cid"]
                or checks.get("contract_cid") != result["contract_cid"]
                or checks.get("source_cid") != result["source_cid"]
                or checks.get("revision") != "snapshot:" + expected_head.snapshot_cid
                or checks.get("assumptions") != list(ASSUMPTIONS)
                or checks.get("evidence_kind") != "conditional_smt"
                or checks.get("kernel_checked") is not False
                or checks.get("behavior_authority") is not False):
            raise CodebaseVerificationError("native check did not bind the exact compiled contract")
        observations = checks.get("solvers", [])
        replayed = (
            type(observations) is list and len(observations) == 2
            and all(type(item) is dict for item in observations)
            and {item.get("solver") for item in observations} == {"z3", "cvc5"}
            and all(item.get("verdict") in {"sat", "unsat", "unknown"}
                    and item.get("status") in {"proved", "refuted", "unknown"}
                    for item in observations)
        )
        if checks["status"] in _TERMINAL_STATUSES and not replayed:
            raise CodebaseVerificationError("terminal outcome requires both fresh native solver verdicts")
        if checks["status"] in _TERMINAL_STATUSES:
            verdict = "unsat" if checks["status"] == "proved" else "sat"
            if any(item["status"] != checks["status"] or item["verdict"] != verdict
                   for item in observations):
                raise CodebaseVerificationError("terminal outcome contradicts native solver verdicts")
        result.update(status=checks["status"], compiled_cid=result["compiled_cid"],
                      checks=checks, solver_check_attempted=True, solver_replayed=replayed)
        if checks["status"] in _TERMINAL_STATUSES:
            if type(checks.get("checker_identity")) is not dict or type(checks.get("bounds")) is not dict:
                raise CodebaseVerificationError("native checker identity and bounds are required")
            binding = build_codebase_property_binding(
                source_cid=result["source_cid"], snapshot_cid=expected_head.snapshot_cid,
                profile={"name": PROFILE, "contract": result["contract"],
                         "assumptions": checks["assumptions"],
                         "implementation_sha256": _implementation_identity()},
                contract_cid=result["contract_cid"], compiled_cid=result["compiled_cid"],
                bounds=checks["bounds"], environment=checks["checker_identity"],
                provider="native-z3-cvc5", checker="current-integer-offset@1",
            )
            result["cache_binding"] = binding
            if self.cache is not None:
                historical = self.cache.lookup(binding)
                if historical is not None:
                    # The stored status can veto reuse, never provide
                    # a positive result without fresh native checks.
                    for name in ("status", "profile", "source_cid", "contract_cid",
                                 "compiled_cid", "revision", "assumptions"):
                        if historical.get(name) != checks.get(name):
                            raise CodebaseVerificationError("cached evidence disagrees with fresh native checking")
                    result["cache_history_hit"] = True
                else:
                    self.cache.put(binding, checks)

    def verify(
        self, repository: str | Path, *, expected_head: Any, contract: Any,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
        memory_mb: int = 1024,
    ) -> dict[str, Any]:
        from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            LeaseCancelledError, LeaseTimeoutError,
        )
        from .codebase_integer_profile import (
            PROFILE, IntegerOffsetContract, UnsupportedIntegerProfile,
            compile_integer_offset, execute_integer_offset,
        )

        if type(expected_head) is not CodebaseHead or type(contract) is not IntegerOffsetContract:
            raise CodebaseVerificationError("canonical head and integer-offset contract required")
        if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise CodebaseVerificationError("timeout_seconds must be finite and positive")
        if type(admission_timeout_seconds) not in {int, float} or not math.isfinite(admission_timeout_seconds) or admission_timeout_seconds < 0:
            raise CodebaseVerificationError("admission_timeout_seconds must be finite and nonnegative")
        if type(memory_mb) is not int or memory_mb < 512:
            raise CodebaseVerificationError("integer verification requires at least a 512 MiB reservation")
        deadline = time.monotonic() + timeout_seconds
        with acquire_codebase_resources(
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb,
        ) as lease:
            cancelled = lease.combined_cancellation_signal(cancel_event)

            def remaining() -> float:
                if cancelled.is_set():
                    raise LeaseCancelledError("current integer verification cancelled")
                duration = deadline - time.monotonic()
                if duration <= 0:
                    raise LeaseTimeoutError("current integer verification deadline exceeded")
                return duration

            def observe():
                duration = remaining()
                return self.index.observe_current(
                    repository, expected_head=expected_head, parent_lease=lease,
                    cancel_event=cancelled, timeout_seconds=duration,
                    admission_timeout_seconds=min(admission_timeout_seconds, duration),
                    memory_mb=512,
                )

            observation = observe()
            entry = next((entry for entry in observation.manifest.snapshot.entries
                          if entry.path == contract.path), None)
            result = _new_result(expected_head, contract)
            if entry is None or entry.is_opaque:
                result["diagnostics"] = ["selected source is absent or opaque in the current snapshot"]
            else:
                source = self.index.artifacts.get_bytes(entry.source_cid)
                result["source_cid"] = entry.source_cid
                remaining()
                try:
                    compiled = compile_integer_offset(
                        source, contract, revision="snapshot:" + expected_head.snapshot_cid,
                    )
                except UnsupportedIntegerProfile as error:
                    result["diagnostics"] = [str(error)]
                else:
                    if compiled.source_cid != entry.source_cid or compiled.contract != contract:
                        raise CodebaseVerificationError("lowering changed source or contract identity")
                    sealed = self.index.artifacts.put(compiled.to_dict())
                    if sealed != compiled.cid:
                        raise CodebaseVerificationError("compiled artifact identity changed during sealing")
                    remaining()
                    checks = execute_integer_offset(
                        compiled, parent_lease=lease, cancel_event=cancelled,
                        timeout_seconds=min(10.0, remaining()),
                    )
                    remaining()
                    result["compiled_cid"] = compiled.cid
                    self._accept_checks(result, checks)
            remaining()
            receipt_cid = self.index.artifacts.put(result)
            observe()
            remaining()
            return {**result, "receipt_cid": receipt_cid}


    def verify_many(
        self, repository: str | Path, *, expected_head: Any, contracts: Any,
        scheduler: Any = None, parent_lease: Any = None, cancel_event: Any = None,
        admission_timeout_seconds: float = 30.0, timeout_seconds: float = 120.0,
        max_workers: int | None = None, memory_mb: int | None = None,
        evidence_index: Any = None,
    ) -> dict[str, Any]:
        """Verify a complete bounded contract list under one shared envelope.

        SQL/CAS/cache access stays on this calling owner thread. Independent
        native checks run in resource-admitted workers; their results are
        published as conditional history only after all workers have joined.
        """
        from .codebase_integer_batch import verify_integer_batch
        return verify_integer_batch(
            self, repository, expected_head=expected_head, contracts=contracts,
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            max_workers=max_workers, memory_mb=memory_mb, evidence_index=evidence_index,
        )


__all__ = ["SCHEMA", "CodebaseVerificationError", "CodebaseIntegerVerifier"]
