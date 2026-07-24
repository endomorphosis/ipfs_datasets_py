"""Strict logic-pipeline report CLI and proof-overlap implementation.

This module implements the Hammer/Leanstral proof report and dispatches the
spaCy/SyMAI front-end report implemented in :mod:`frontend_report`.  Both are
trust boundaries, not presentation-only summaries.  The proof path requires
the complete paired pilot matrix, derives every aggregate from case-level
observations, keeps cold and warm cache modes separate, and admits a verified
outcome only when a native-kernel receipt is present.  Legacy S1 model claims
are retained as a safety diagnostic and never enter candidate metrics.

The CLI also dispatches the reproducible inferential statistics validator in
:mod:`statistics`.  Statistics reports are supplied explicitly because they
are run-scoped analysis outputs rather than a fabricated checked-in efficacy
snapshot.

Delegation-efficiency reports use the same rule.  A measured report must embed
complete case-result and operational-meter receipts.  Without an explicit
results path, the efficiency section validates a structural preflight whose
quality and resource values are null; it never turns absent measurements into
zero-cost efficacy.

The checked-in artifact records a capability-preflight execution because the
requested Leanstral service was unavailable in the capture environment.  This
is intentional missingness: validation proves that the analysis/reporting
contract is complete without manufacturing efficacy measurements.

The robustness boundary additionally classifies the preregistered failure
matrix, proves bounded process isolation, validates pinned fresh-worktree
receipt replay, and emits canonical content-addressed robustness evidence.
"""

from __future__ import annotations

if __package__ in {None, ""}:  # Support ``python benchmarks/.../report.py``.
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Final, Mapping, Protocol, Sequence, Self

from benchmarks.logic_pipeline import BENCHMARK_ID
from benchmarks.logic_pipeline.capabilities import WorktreeSafetyReceipt
from benchmarks.logic_pipeline.cases import (
    FROZEN_SPLIT_SHA256,
    load_reviewed_corpus,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL,
    CaseResultRecord,
    CacheMode,
    DEFAULT_PROTOCOL_SHA256,
    FailureCode,
    OutcomeStatus,
    ProtocolContractError,
    RunContract,
    Split,
    StageName,
    VerificationAuthority,
    canonical_json,
)
from benchmarks.logic_pipeline.metrics import (
    DEFAULT_EFFICIENCY_ESCALATIONS,
    EfficiencyEscalation,
    EfficiencyObservation,
    MetricsContractError,
    analyze_delegation_efficiency,
    validate_kernel_bound_result,
)
from benchmarks.logic_pipeline.variants import (
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
)


PROOF_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.proof-overlap-report.v1"
)
PROOF_OBSERVATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.proof-observation.v1"
)
PROOF_ANALYSIS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.proof-overlap-analysis.v1"
)
EFFICIENCY_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.delegation-efficiency-report.v1"
)
DEFAULT_PROOF_REPORT_PATH: Final = Path(
    "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
    "proof-overlap-ordering-v1.json"
)
DEFAULT_FINAL_DECISION_PATH: Final = Path(
    "docs/performance_snapshots/"
    "2026-07-24_hammer_symai_spacy_leanstral_final_decision.json"
)
DEFAULT_BENCHMARK_RUNBOOK_PATH: Final = Path(
    "docs/implementation/runbooks/"
    "hammer_symai_spacy_leanstral_benchmark.md"
)
FINAL_DECISION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.final-architecture-decision.v1"
)
FINAL_DECISION_EVIDENCE: Final = (
    "evidence-bound final architecture decision, delegation matrix, "
    "and worktree-safe reproduction runbook"
)
PRIMARY_VARIANT_IDS: Final = (
    "A2",
    "A3",
    "A4",
    "A6",
    "A7",
    "A8",
    "A9",
    "A10",
    "A11",
    "A12",
)
DIAGNOSTIC_VARIANT_IDS: Final = ("S1",)
CACHE_MODES: Final = ("cold", "warm")
ELIGIBLE_CASE_IDS: Final = (
    "pilot-p01",
    "pilot-p02",
    "pilot-p03",
    "pilot-p04",
    "pilot-p07",
    "pilot-p08",
    "pilot-p09",
)
EXCLUDED_CASE_IDS: Final = ("pilot-p05", "pilot-p06", "pilot-p10")
STATUS_VALUES: Final = frozenset(
    {
        "verified",
        "not_verified",
        "rejected",
        "unavailable",
        "excluded",
        "infrastructure_failure",
    }
)
SOURCE_VALUES: Final = frozenset({"hammer", "leanstral", "both", "none"})
CAPABILITY_STATUS_VALUES: Final = frozenset(
    {"available", "unavailable", "degraded"}
)
CAPABILITY_KEYS: Final = (
    "spacy",
    "symai",
    "llm_router",
    "hammer",
    "leanstral",
    "lean_kernel",
)
PAIRWISE_COMPARISONS: Final = (
    ("A2", "A3", "hammer_only_vs_fallback"),
    ("A3", "A6", "hammer_first_vs_leanstral_first"),
    ("A4", "A6", "conditional_hammer_first_vs_leanstral_first"),
    ("A4", "A9", "hammer_first_vs_no_hammer"),
    ("A4", "A10", "deterministic_vs_learned_selector"),
    ("A4", "A11", "deterministic_vs_llm_ranking"),
    ("A4", "A12", "conditional_vs_duplicated_work"),
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ProofReportError(ValueError):
    """Raised when proof evidence cannot support a report."""


class FinalDecisionValidationError(ValueError):
    """Raised when the published architecture decision is not trustworthy."""


class RunbookValidationError(ValueError):
    """Raised when the benchmark operator runbook is incomplete or unsafe."""


def HSSLEV1006B8A() -> str:
    """Return AST-verifiable evidence for the final architecture decision."""

    return FINAL_DECISION_EVIDENCE


def HSSLEV0526A41() -> str:
    """Return AST-verifiable evidence for proof overlap and ordering."""

    return (
        "kernel-bound Hammer and Leanstral proof overlap, ordering, "
        "and missingness report"
    )


def HSSLEV0519C80() -> str:
    """Return AST-verifiable evidence for front-end overlap measurement."""

    from benchmarks.logic_pipeline.frontend_report import (
        HSSLEV0519C80 as frontend_evidence,
    )

    return frontend_evidence()


def HSSLEV0608F63() -> str:
    """Return AST-verifiable evidence for reproducible statistical analysis."""

    from benchmarks.logic_pipeline.statistics import (
        HSSLEV0608F63 as statistics_evidence,
    )

    return statistics_evidence()


def HSSLEV0615B24() -> str:
    """Return AST-verifiable evidence for delegation-value accounting."""

    from benchmarks.logic_pipeline.metrics import (
        HSSLEV0615B24 as efficiency_evidence,
    )

    return efficiency_evidence()


def HSSLEV1159F06() -> str:
    """Return AST-verifiable evidence for measured reports and authorization."""

    return (
        "receipt-driven front-end, proof, resource, and statistical reports "
        "with typed missingness and a complete source-bound data-driven "
        "pilot authorization gate"
    )


def HSSLEV0801D68() -> str:
    """Return AST-verifiable evidence for the pilot-shortlist gate."""

    from benchmarks.logic_pipeline.pilot_gate import (
        HSSLEV0801D68 as pilot_gate_evidence,
    )

    return pilot_gate_evidence()


def HSSLEV0909F29() -> str:
    """Return AST-verifiable evidence for the paired holdout phase gate."""

    from benchmarks.logic_pipeline.holdout_gate import (
        HSSLEV0909F29 as holdout_gate_evidence,
    )

    return holdout_gate_evidence()


def build_statistics_report(
    plan: object,
    requests: Sequence[object],
    *,
    pareto_objectives: Sequence[object] = (),
    pareto_candidates: Sequence[object] = (),
) -> dict[str, object]:
    """Build a run-scoped inferential report through the shared CLI boundary."""

    from benchmarks.logic_pipeline.statistics import (
        build_statistics_report as build,
    )

    return build(
        plan,  # type: ignore[arg-type]
        requests,  # type: ignore[arg-type]
        pareto_objectives=pareto_objectives,  # type: ignore[arg-type]
        pareto_candidates=pareto_candidates,  # type: ignore[arg-type]
    )


def validate_statistics_report(value: object) -> dict[str, object]:
    """Recompute and validate a run-scoped inferential report."""

    from benchmarks.logic_pipeline.statistics import (
        validate_statistics_report as validate,
    )

    return validate(value)


def load_statistics_report(path: str | Path) -> dict[str, object]:
    """Load strict canonical statistics JSON through the report entry point."""

    from benchmarks.logic_pipeline.statistics import (
        load_statistics_report as load,
    )

    return load(path)


FAILURE_ISOLATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.failure-isolation.v1"
)
REPLAY_VALIDATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.receipt-replay.v1"
)
ROBUSTNESS_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.robustness-report.v1"
)
BOUNDED_PROCESS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.bounded-process.v1"
)
_ROBUST_SHA256_CHARS = frozenset("0123456789abcdef")
_MAX_DETAIL = 512


class RobustnessValidationError(ValueError):
    """Raised when robustness evidence is incomplete, stale, or inconsistent."""


class FailureInjectionKind(str, Enum):
    """Complete failure-injection matrix required by HSSL-G070."""

    MISSING_TOOL = "missing_tool"
    MALFORMED_OUTPUT = "malformed_output"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    CACHE_CORRUPTION = "cache_corruption"
    BACKEND_DRIFT = "backend_drift"


class ReplayStatus(str, Enum):
    PASSED = "passed"


_EXPECTED_CODES: Final[Mapping[FailureInjectionKind, frozenset[FailureCode]]] = {
    FailureInjectionKind.MISSING_TOOL: frozenset(
        {FailureCode.CAPABILITY_UNAVAILABLE}
    ),
    FailureInjectionKind.MALFORMED_OUTPUT: frozenset(
        {
            FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE,
            FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        }
    ),
    FailureInjectionKind.TIMEOUT: frozenset(
        {
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
            FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        }
    ),
    FailureInjectionKind.CANCELLATION: frozenset(
        {FailureCode.RESOURCE_LEASE_CANCELLATION}
    ),
    FailureInjectionKind.CACHE_CORRUPTION: frozenset(
        {FailureCode.CACHE_CONTAMINATION}
    ),
    FailureInjectionKind.BACKEND_DRIFT: frozenset(
        {FailureCode.RECEIPT_OR_PROVENANCE_FAILURE}
    ),
}


def HSSLEV0702E85() -> str:
    """Return the stable AST evidence marker for the robustness objective."""

    return "failure injection, bounded isolation, and pinned fresh-worktree receipt replay"


def _robust_digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _ROBUST_SHA256_CHARS for character in value)
    ):
        raise RobustnessValidationError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _robust_identifier(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value in {".", ".."}
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "._-") for character in value)
    ):
        raise RobustnessValidationError(f"{field} is not a safe identifier")
    return value


def _robust_exact(
    data: Mapping[str, object], expected: set[str], field: str
) -> None:
    if set(data) != expected:
        raise RobustnessValidationError(
            f"{field} fields changed; expected {sorted(expected)}, got {sorted(data)}"
        )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ProofReportError(f"{field} must be an object with string keys")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    raise ProofReportError(
        f"{field} keys changed; missing={missing}, unknown={unknown}"
    )


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ProofReportError(f"{field} must be an array")
    return value


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ProofReportError(f"{field} must be a nonempty string")
    return value


def _safe_id(value: object, field: str) -> str:
    result = _string(value, field)
    if not _SAFE_ID.fullmatch(result) or result in {".", ".."}:
        raise ProofReportError(f"{field} must be a safe identifier")
    return result


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProofReportError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProofReportError(f"{field} must be boolean")
    return value


def _count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofReportError(f"{field} must be a nonnegative integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofReportError(f"{field} must be a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ProofReportError(f"{field} must be a finite nonnegative number")
    return result


def _nullable_digest(value: object, field: str) -> str | None:
    return None if value is None else _digest(value, field)


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProofReportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _robust_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise RobustnessValidationError(f"{field} must be an object")
    return value


def _robust_number(
    value: object, field: str, *, positive: bool = False
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RobustnessValidationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise RobustnessValidationError(f"{field} is outside its allowed bound")
    return result


def _robust_enum(enum_type: type[Enum], value: object, field: str) -> Enum:
    if not isinstance(value, str):
        raise RobustnessValidationError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise RobustnessValidationError(f"unsupported {field}: {value!r}") from exc


def _case_identity(record: CaseResultRecord) -> tuple[object, ...]:
    return (
        record.protocol_sha256,
        record.run_id,
        record.case_id,
        record.case_manifest_sha256,
        record.variant_id,
        record.split,
        record.cache_mode,
    )


def _contract_identity(contract: RunContract) -> tuple[object, ...]:
    return (
        contract.protocol_sha256,
        contract.run_id,
        contract.case_manifest_sha256,
        contract.requested_variant_id,
        contract.split,
        contract.cache_mode,
    )


def _validate_contract_result(
    contract: RunContract, result: CaseResultRecord
) -> None:
    expected = (
        result.protocol_sha256,
        result.run_id,
        result.case_manifest_sha256,
        result.variant_id,
        result.split,
        result.cache_mode,
    )
    if _contract_identity(contract) != expected:
        raise RobustnessValidationError(
            "run contract and case-result identities do not match"
        )


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    """Terminal evidence for one command executed in an isolated process group."""

    schema: str
    argv: tuple[str, ...]
    pid: int | None
    process_group_id: int | None
    returncode: int | None
    elapsed_seconds: float
    limit_seconds: float
    failure_code: FailureCode | None
    timed_out: bool
    cancelled: bool
    stdout: str
    stderr: str
    output_truncated: bool
    orphaned_child_count: int

    def __post_init__(self) -> None:
        if self.schema != BOUNDED_PROCESS_SCHEMA:
            raise RobustnessValidationError("unsupported bounded-process schema")
        if not isinstance(self.argv, tuple) or not self.argv:
            raise RobustnessValidationError("argv must be a nonempty tuple")
        if any(not isinstance(item, str) or not item for item in self.argv):
            raise RobustnessValidationError("argv contains an invalid argument")
        for field in ("pid", "process_group_id"):
            value = getattr(self, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise RobustnessValidationError(f"{field} must be a positive integer")
        if (self.pid is None) != (self.process_group_id is None):
            raise RobustnessValidationError(
                "pid and process_group_id must both be present or absent"
            )
        if self.returncode is not None and (
            isinstance(self.returncode, bool) or not isinstance(self.returncode, int)
        ):
            raise RobustnessValidationError("returncode must be an integer or null")
        _robust_number(self.elapsed_seconds, "elapsed_seconds")
        _robust_number(self.limit_seconds, "limit_seconds", positive=True)
        if self.failure_code is not None and not isinstance(
            self.failure_code, FailureCode
        ):
            raise RobustnessValidationError("failure_code must use FailureCode")
        if type(self.timed_out) is not bool or type(self.cancelled) is not bool:
            raise RobustnessValidationError("process flags must be booleans")
        if self.timed_out and self.cancelled:
            raise RobustnessValidationError(
                "a process cannot be both timed out and explicitly cancelled"
            )
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise RobustnessValidationError("process output must be text")
        if any(
            len(value.encode("utf-8")) > 16 * 1024 * 1024
            for value in (self.stdout, self.stderr)
        ):
            raise RobustnessValidationError("retained process output is too large")
        if type(self.output_truncated) is not bool:
            raise RobustnessValidationError("output_truncated must be a boolean")
        if (
            isinstance(self.orphaned_child_count, bool)
            or not isinstance(self.orphaned_child_count, int)
            or self.orphaned_child_count < 0
        ):
            raise RobustnessValidationError(
                "orphaned_child_count must be a nonnegative integer"
            )
        if self.orphaned_child_count:
            if self.failure_code is not FailureCode.ORPHANED_CHILD:
                raise RobustnessValidationError(
                    "unexpected or surviving children require orphaned_child classification"
                )
        elif self.timed_out or self.cancelled:
            if self.failure_code is not FailureCode.RESOURCE_LEASE_CANCELLATION:
                raise RobustnessValidationError(
                    "timeout/cancellation requires resource-lease classification"
                )

    @property
    def bounded(self) -> bool:
        return self.elapsed_seconds <= self.limit_seconds

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "argv": list(self.argv),
            "pid": self.pid,
            "process_group_id": self.process_group_id,
            "returncode": self.returncode,
            "elapsed_seconds": self.elapsed_seconds,
            "limit_seconds": self.limit_seconds,
            "failure_code": (
                None if self.failure_code is None else self.failure_code.value
            ),
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "output_truncated": self.output_truncated,
            "orphaned_child_count": self.orphaned_child_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _robust_mapping(value, "bounded process")
        _robust_exact(data, set(cls.__dataclass_fields__), "bounded process")
        argv = data["argv"]
        if not isinstance(argv, list):
            raise RobustnessValidationError("argv must be an array")
        code = data["failure_code"]
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            argv=tuple(argv),  # type: ignore[arg-type]
            pid=data["pid"],  # type: ignore[arg-type]
            process_group_id=data["process_group_id"],  # type: ignore[arg-type]
            returncode=data["returncode"],  # type: ignore[arg-type]
            elapsed_seconds=data["elapsed_seconds"],  # type: ignore[arg-type]
            limit_seconds=data["limit_seconds"],  # type: ignore[arg-type]
            failure_code=(  # type: ignore[arg-type]
                None
                if code is None
                else _robust_enum(FailureCode, code, "failure_code")
            ),
            timed_out=data["timed_out"],  # type: ignore[arg-type]
            cancelled=data["cancelled"],  # type: ignore[arg-type]
            stdout=data["stdout"],  # type: ignore[arg-type]
            stderr=data["stderr"],  # type: ignore[arg-type]
            output_truncated=data["output_truncated"],  # type: ignore[arg-type]
            orphaned_child_count=data["orphaned_child_count"],  # type: ignore[arg-type]
        )


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


def _active_process_group_members(process_group_id: int) -> tuple[int, ...]:
    """Return live (non-zombie) Linux processes in a process group."""

    proc = Path("/proc")
    if not proc.is_dir():
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return ()
        except PermissionError:
            return (process_group_id,)
        return (process_group_id,)
    members: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="utf-8").split()
            # /proc/<pid>/stat: state is field 3, process group is field 5.
            if len(fields) > 4 and int(fields[4]) == process_group_id:
                if fields[2] != "Z":
                    members.append(int(entry.name))
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            continue
    return tuple(sorted(members))


def _terminate_process_group(
    process: subprocess.Popen[bytes], *, grace_seconds: float
) -> tuple[int, ...]:
    process_group_id = process.pid
    if process.poll() is None or _active_process_group_members(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process.poll() is None:
            try:
                process.wait(timeout=min(0.02, max(0.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
        if not _active_process_group_members(process_group_id):
            break
        time.sleep(0.005)
    members = _active_process_group_members(process_group_id)
    if members:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        kill_deadline = time.monotonic() + grace_seconds
        while time.monotonic() < kill_deadline:
            if process.poll() is None:
                try:
                    process.wait(timeout=0.02)
                except subprocess.TimeoutExpired:
                    pass
            members = _active_process_group_members(process_group_id)
            if not members:
                break
            time.sleep(0.005)
    if process.poll() is None:
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass
    return _active_process_group_members(process_group_id)


def _read_bounded(stream: object, maximum: int) -> tuple[str, bool]:
    stream.seek(0)  # type: ignore[attr-defined]
    raw = stream.read(maximum + 1)  # type: ignore[attr-defined]
    truncated = len(raw) > maximum
    return raw[:maximum].decode("utf-8", errors="replace"), truncated


def run_bounded_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cancellation: CancellationSignal | None = None,
    termination_grace_seconds: float = 0.25,
    maximum_output_bytes: int = 64 * 1024,
) -> BoundedProcessResult:
    """Run ``argv`` without a shell and kill/reap its whole process group.

    Output is redirected to temporary files so an untrusted child cannot grow
    the supervisor's memory.  Only ``maximum_output_bytes`` from each stream is
    retained in the returned record.
    """

    command = tuple(argv)
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise RobustnessValidationError("argv must be a nonempty string sequence")
    limit = _robust_number(timeout_seconds, "timeout_seconds", positive=True)
    grace = _robust_number(
        termination_grace_seconds, "termination_grace_seconds", positive=True
    )
    if (
        isinstance(maximum_output_bytes, bool)
        or not isinstance(maximum_output_bytes, int)
        or maximum_output_bytes < 1
        or maximum_output_bytes > 16 * 1024 * 1024
    ):
        raise RobustnessValidationError(
            "maximum_output_bytes must be from 1 through 16777216"
        )
    if cwd is not None and not Path(cwd).is_dir():
        raise RobustnessValidationError("cwd must be an existing directory")
    if env is not None and (
        not isinstance(env, Mapping)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items())
    ):
        raise RobustnessValidationError("env must map strings to strings")

    start = time.monotonic()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=None if env is None else dict(env),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                shell=False,
            )
        except FileNotFoundError:
            elapsed = time.monotonic() - start
            return BoundedProcessResult(
                BOUNDED_PROCESS_SCHEMA,
                command,
                None,
                None,
                None,
                elapsed,
                limit + grace * 2,
                FailureCode.CAPABILITY_UNAVAILABLE,
                False,
                False,
                "",
                "",
                False,
                0,
            )
        except OSError as exc:
            raise RobustnessValidationError(
                f"could not start bounded process: {type(exc).__name__}"
            ) from exc

        timed_out = False
        cancelled = False
        deadline = start + limit
        try:
            while process.poll() is None:
                if cancellation is not None and cancellation.is_set():
                    cancelled = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(min(0.01, max(0.001, deadline - time.monotonic())))
        except BaseException:
            # Even supervisor cancellation/interrupt must not leak the child
            # group. Preserve the original exception after best-effort reap.
            _terminate_process_group(process, grace_seconds=grace)
            raise

        survivors: tuple[int, ...] = ()
        unexpected_children: tuple[int, ...] = ()
        if timed_out or cancelled:
            survivors = _terminate_process_group(process, grace_seconds=grace)
        else:
            # A parent can exit while leaving a same-group child holding no
            # output descriptor. Treat that as an orphan and clean it too.
            unexpected_children = tuple(
                pid
                for pid in _active_process_group_members(process.pid)
                if pid != process.pid
            )
            if unexpected_children:
                survivors = _terminate_process_group(process, grace_seconds=grace)
        returncode = process.poll()
        stdout, stdout_truncated = _read_bounded(stdout_file, maximum_output_bytes)
        stderr, stderr_truncated = _read_bounded(stderr_file, maximum_output_bytes)
        elapsed = time.monotonic() - start
        if survivors or unexpected_children:
            failure_code = FailureCode.ORPHANED_CHILD
        elif timed_out or cancelled:
            failure_code = FailureCode.RESOURCE_LEASE_CANCELLATION
        elif returncode == 0:
            failure_code = None
        else:
            failure_code = FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
        return BoundedProcessResult(
            BOUNDED_PROCESS_SCHEMA,
            command,
            process.pid,
            process.pid,
            returncode,
            elapsed,
            limit + grace * 2,
            failure_code,
            timed_out,
            cancelled,
            stdout,
            stderr,
            stdout_truncated or stderr_truncated,
            len(set(survivors) | set(unexpected_children)),
        )


@dataclass(frozen=True, slots=True)
class FailureIsolationRecord:
    """Validated evidence that one injected failure was bounded and local."""

    schema: str
    injection_id: str
    kind: FailureInjectionKind
    case_id: str
    result_sha256: str
    observed_failure_code: FailureCode
    elapsed_seconds: float
    limit_seconds: float
    affected_case_ids: tuple[str, ...]
    child_process_ids: tuple[int, ...] = ()
    reaped_process_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != FAILURE_ISOLATION_SCHEMA:
            raise RobustnessValidationError("unsupported failure-isolation schema")
        _robust_identifier(self.injection_id, "injection_id")
        if not isinstance(self.kind, FailureInjectionKind):
            raise RobustnessValidationError("kind must use FailureInjectionKind")
        _robust_identifier(self.case_id, "case_id")
        _robust_digest(self.result_sha256, "result_sha256")
        if not isinstance(self.observed_failure_code, FailureCode):
            raise RobustnessValidationError(
                "observed_failure_code must use FailureCode"
            )
        if self.observed_failure_code not in _EXPECTED_CODES[self.kind]:
            raise RobustnessValidationError(
                f"{self.kind.value} was misclassified as "
                f"{self.observed_failure_code.value}"
            )
        elapsed = _robust_number(self.elapsed_seconds, "elapsed_seconds")
        limit = _robust_number(
            self.limit_seconds, "limit_seconds", positive=True
        )
        if elapsed > limit:
            raise RobustnessValidationError(
                f"{self.kind.value} exceeded its recorded time bound"
            )
        if (
            not isinstance(self.affected_case_ids, tuple)
            or self.affected_case_ids != (self.case_id,)
        ):
            raise RobustnessValidationError(
                "an injected failure must affect exactly its own case"
            )
        for field in ("child_process_ids", "reaped_process_ids"):
            values = getattr(self, field)
            if (
                not isinstance(values, tuple)
                or len(values) != len(set(values))
                or any(
                    isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
                    for pid in values
                )
            ):
                raise RobustnessValidationError(
                    f"{field} must contain unique positive process ids"
                )
        if not set(self.child_process_ids).issubset(self.reaped_process_ids):
            raise RobustnessValidationError(
                "every child process must be terminated and reaped"
            )
        if DEFAULT_PROTOCOL.stop_required(self.observed_failure_code) != (
            self.kind
            in {
                FailureInjectionKind.CACHE_CORRUPTION,
                FailureInjectionKind.BACKEND_DRIFT,
            }
        ):
            raise RobustnessValidationError(
                "injected failure disagrees with the frozen immediate-stop policy"
            )

    @classmethod
    def classify(
        cls,
        injection_id: str,
        kind: FailureInjectionKind,
        result: CaseResultRecord,
        *,
        elapsed_seconds: float,
        limit_seconds: float,
        affected_case_ids: Sequence[str],
        child_process_ids: Sequence[int] = (),
        reaped_process_ids: Sequence[int] = (),
    ) -> Self:
        if not isinstance(result, CaseResultRecord) or result.failure_code is None:
            raise RobustnessValidationError(
                "injected failure requires a failed CaseResultRecord"
            )
        try:
            validate_kernel_bound_result(result)
        except MetricsContractError as exc:
            raise RobustnessValidationError(
                "injected result failed provenance validation"
            ) from exc
        return cls(
            FAILURE_ISOLATION_SCHEMA,
            injection_id,
            kind,
            result.case_id,
            result.digest,
            result.failure_code,
            elapsed_seconds,
            limit_seconds,
            tuple(affected_case_ids),
            tuple(child_process_ids),
            tuple(reaped_process_ids),
        )

    @property
    def stop_required(self) -> bool:
        return DEFAULT_PROTOCOL.stop_required(self.observed_failure_code)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "injection_id": self.injection_id,
            "kind": self.kind.value,
            "case_id": self.case_id,
            "result_sha256": self.result_sha256,
            "observed_failure_code": self.observed_failure_code.value,
            "elapsed_seconds": self.elapsed_seconds,
            "limit_seconds": self.limit_seconds,
            "affected_case_ids": list(self.affected_case_ids),
            "child_process_ids": list(self.child_process_ids),
            "reaped_process_ids": list(self.reaped_process_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _robust_mapping(value, "failure isolation")
        _robust_exact(data, set(cls.__dataclass_fields__), "failure isolation")
        arrays = {}
        for field in (
            "affected_case_ids",
            "child_process_ids",
            "reaped_process_ids",
        ):
            member = data[field]
            if not isinstance(member, list):
                raise RobustnessValidationError(f"{field} must be an array")
            arrays[field] = member
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            injection_id=data["injection_id"],  # type: ignore[arg-type]
            kind=_robust_enum(  # type: ignore[arg-type]
                FailureInjectionKind, data["kind"], "kind"
            ),
            case_id=data["case_id"],  # type: ignore[arg-type]
            result_sha256=data["result_sha256"],  # type: ignore[arg-type]
            observed_failure_code=_robust_enum(  # type: ignore[arg-type]
                FailureCode, data["observed_failure_code"], "observed_failure_code"
            ),
            elapsed_seconds=data["elapsed_seconds"],  # type: ignore[arg-type]
            limit_seconds=data["limit_seconds"],  # type: ignore[arg-type]
            affected_case_ids=tuple(arrays["affected_case_ids"]),  # type: ignore[arg-type]
            child_process_ids=tuple(arrays["child_process_ids"]),  # type: ignore[arg-type]
            reaped_process_ids=tuple(arrays["reaped_process_ids"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ReplayValidationRecord:
    """Content-addressed proof of one source/fresh-run receipt comparison."""

    schema: str
    status: ReplayStatus
    case_id: str
    original_run_id: str
    replay_run_id: str
    original_result_sha256: str
    replay_result_sha256: str
    original_receipt_sha256: str
    replay_receipt_sha256: str
    environment_sha256: str
    source_commit: str
    worktree_receipt_sha256: str
    original_cache_namespace: str
    replay_cache_namespace: str

    def __post_init__(self) -> None:
        if self.schema != REPLAY_VALIDATION_SCHEMA:
            raise RobustnessValidationError("unsupported replay-validation schema")
        if self.status is not ReplayStatus.PASSED:
            raise RobustnessValidationError("only passed replay evidence is durable")
        for field in ("case_id", "original_run_id", "replay_run_id"):
            _robust_identifier(getattr(self, field), field)
        if self.original_run_id == self.replay_run_id:
            raise RobustnessValidationError("receipt replay requires a fresh run id")
        for field in (
            "original_result_sha256",
            "replay_result_sha256",
            "original_receipt_sha256",
            "replay_receipt_sha256",
            "environment_sha256",
            "worktree_receipt_sha256",
        ):
            _robust_digest(getattr(self, field), field)
        if (
            not isinstance(self.source_commit, str)
            or len(self.source_commit) != 40
            or any(
                character not in _ROBUST_SHA256_CHARS
                for character in self.source_commit
            )
        ):
            raise RobustnessValidationError(
                "source_commit must be a full lowercase Git commit"
            )
        for field in ("original_cache_namespace", "replay_cache_namespace"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise RobustnessValidationError(f"{field} must be nonempty")
        if self.original_cache_namespace == self.replay_cache_namespace:
            raise RobustnessValidationError(
                "receipt replay requires a fresh cache namespace"
            )

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            field: (
                getattr(self, field).value
                if isinstance(getattr(self, field), Enum)
                else getattr(self, field)
            )
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _robust_mapping(value, "replay validation")
        _robust_exact(data, set(cls.__dataclass_fields__), "replay validation")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            status=_robust_enum(  # type: ignore[arg-type]
                ReplayStatus, data["status"], "status"
            ),
            case_id=data["case_id"],  # type: ignore[arg-type]
            original_run_id=data["original_run_id"],  # type: ignore[arg-type]
            replay_run_id=data["replay_run_id"],  # type: ignore[arg-type]
            original_result_sha256=data["original_result_sha256"],  # type: ignore[arg-type]
            replay_result_sha256=data["replay_result_sha256"],  # type: ignore[arg-type]
            original_receipt_sha256=data["original_receipt_sha256"],  # type: ignore[arg-type]
            replay_receipt_sha256=data["replay_receipt_sha256"],  # type: ignore[arg-type]
            environment_sha256=data["environment_sha256"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            worktree_receipt_sha256=data["worktree_receipt_sha256"],  # type: ignore[arg-type]
            original_cache_namespace=data["original_cache_namespace"],  # type: ignore[arg-type]
            replay_cache_namespace=data["replay_cache_namespace"],  # type: ignore[arg-type]
        )


def validate_replay(
    original: CaseResultRecord,
    replayed: CaseResultRecord,
    *,
    original_contract: RunContract,
    replay_contract: RunContract,
    expected_environment_sha256: str,
    worktree_receipt: WorktreeSafetyReceipt,
    expected_source_commit: str,
) -> ReplayValidationRecord:
    """Validate semantic receipt replay in a fresh worktree and cache namespace."""

    if not isinstance(original, CaseResultRecord) or not isinstance(
        replayed, CaseResultRecord
    ):
        raise RobustnessValidationError("replay requires case-result records")
    if not isinstance(original_contract, RunContract) or not isinstance(
        replay_contract, RunContract
    ):
        raise RobustnessValidationError("replay requires source and replay contracts")
    if not isinstance(worktree_receipt, WorktreeSafetyReceipt):
        raise RobustnessValidationError(
            "replay requires a validated worktree safety receipt"
        )
    expected_environment = _robust_digest(
        expected_environment_sha256, "expected_environment_sha256"
    )
    try:
        # Round-trip first so corrupt embedded receipts fail before comparison.
        original = CaseResultRecord.from_dict(original.to_dict())
        replayed = CaseResultRecord.from_dict(replayed.to_dict())
        original_contract = RunContract.from_dict(original_contract.to_dict())
        replay_contract = RunContract.from_dict(replay_contract.to_dict())
        worktree_receipt = WorktreeSafetyReceipt.from_dict(
            worktree_receipt.to_dict()
        )
        validate_kernel_bound_result(original, expected_environment)
        validate_kernel_bound_result(replayed, expected_environment)
    except (
        ProtocolContractError,
        MetricsContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise RobustnessValidationError(
            "corrupt or stale receipt failed replay validation"
        ) from exc
    _validate_contract_result(original_contract, original)
    _validate_contract_result(replay_contract, replayed)
    if original.run_id == replayed.run_id:
        raise RobustnessValidationError("replay must use a fresh run id")
    if original_contract.cache_namespace == replay_contract.cache_namespace:
        raise RobustnessValidationError("replay must use a fresh cache namespace")
    if replay_contract.cache_mode is not CacheMode.COLD:
        raise RobustnessValidationError("receipt replay must start from a cold cache")
    if worktree_receipt.run_id != replayed.run_id:
        raise RobustnessValidationError(
            "worktree receipt is not scoped to the replay run"
        )
    if (
        worktree_receipt.base_commit != expected_source_commit
        or worktree_receipt.worktree_commit != expected_source_commit
    ):
        raise RobustnessValidationError("fresh worktree uses a stale source commit")
    if original_contract.configuration_sha256 != replay_contract.configuration_sha256:
        raise RobustnessValidationError("backend configuration drifted during replay")
    stable_identity = (
        original.protocol_sha256,
        original.case_id,
        original.case_manifest_sha256,
        original.variant_id,
        original.split,
    )
    replay_identity = (
        replayed.protocol_sha256,
        replayed.case_id,
        replayed.case_manifest_sha256,
        replayed.variant_id,
        replayed.split,
    )
    if stable_identity != replay_identity:
        raise RobustnessValidationError("replay changed the stable case identity")
    if (
        original.status is not replayed.status
        or original.failure_code is not replayed.failure_code
        or original.kernel_accepted != replayed.kernel_accepted
        or original.kernel_receipt_sha256 != replayed.kernel_receipt_sha256
    ):
        raise RobustnessValidationError("replay changed the terminal outcome")
    if len(original.stages) != len(replayed.stages):
        raise RobustnessValidationError("replay changed the stage route")
    for source_stage, replay_stage in zip(original.stages, replayed.stages):
        if (
            source_stage.stage is not replay_stage.stage
            or source_stage.status is not replay_stage.status
            or source_stage.adapter_version != replay_stage.adapter_version
            or source_stage.output_sha256 != replay_stage.output_sha256
            or source_stage.failure_code is not replay_stage.failure_code
            or source_stage.provenance.input_sha256
            != replay_stage.provenance.input_sha256
            or source_stage.provenance.requested_identity
            != replay_stage.provenance.requested_identity
            or source_stage.provenance.effective_identity
            != replay_stage.provenance.effective_identity
        ):
            raise RobustnessValidationError(
                f"backend or output drift at {source_stage.stage.value}"
            )
    if original.receipt is None or replayed.receipt is None:  # pragma: no cover
        raise RobustnessValidationError("case result is missing its receipt")
    if (
        original.receipt.reconstruction_sha256
        != replayed.receipt.reconstruction_sha256
    ):
        raise RobustnessValidationError("reconstruction receipt changed on replay")
    return ReplayValidationRecord(
        REPLAY_VALIDATION_SCHEMA,
        ReplayStatus.PASSED,
        original.case_id,
        original.run_id,
        replayed.run_id,
        original.digest,
        replayed.digest,
        original.provenance_receipt_sha256,
        replayed.provenance_receipt_sha256,
        expected_environment,
        expected_source_commit,
        worktree_receipt.sha256,
        original_contract.cache_namespace,
        replay_contract.cache_namespace,
    )


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    """Canonical aggregate requiring the full injection matrix and replay."""

    schema: str
    evidence: str
    failure_isolation: tuple[FailureIsolationRecord, ...]
    receipt_replays: tuple[ReplayValidationRecord, ...]

    def __post_init__(self) -> None:
        if self.schema != ROBUSTNESS_REPORT_SCHEMA:
            raise RobustnessValidationError("unsupported robustness-report schema")
        if self.evidence != HSSLEV0702E85():
            raise RobustnessValidationError("robustness evidence marker changed")
        if not isinstance(self.failure_isolation, tuple) or not isinstance(
            self.receipt_replays, tuple
        ):
            raise RobustnessValidationError("report members must be tuples")
        if any(
            not isinstance(item, FailureIsolationRecord)
            for item in self.failure_isolation
        ) or any(
            not isinstance(item, ReplayValidationRecord)
            for item in self.receipt_replays
        ):
            raise RobustnessValidationError("report contains an invalid record")
        kinds = tuple(item.kind for item in self.failure_isolation)
        if len(kinds) != len(set(kinds)) or set(kinds) != set(FailureInjectionKind):
            raise RobustnessValidationError(
                "report must cover each preregistered failure injection exactly once"
            )
        if not self.receipt_replays:
            raise RobustnessValidationError(
                "report requires at least one fresh-worktree receipt replay"
            )
        replay_cases = tuple(item.case_id for item in self.receipt_replays)
        if len(replay_cases) != len(set(replay_cases)):
            raise RobustnessValidationError("receipt replays contain duplicate cases")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    @property
    def stop_required(self) -> bool:
        return any(item.stop_required for item in self.failure_isolation)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "evidence": self.evidence,
            "failure_isolation": [
                item.to_dict() for item in self.failure_isolation
            ],
            "receipt_replays": [item.to_dict() for item in self.receipt_replays],
        }

    @classmethod
    def create(
        cls,
        failure_isolation: Sequence[FailureIsolationRecord],
        receipt_replays: Sequence[ReplayValidationRecord],
    ) -> Self:
        return cls(
            ROBUSTNESS_REPORT_SCHEMA,
            HSSLEV0702E85(),
            tuple(failure_isolation),
            tuple(receipt_replays),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _robust_mapping(value, "robustness report")
        _robust_exact(
            data, set(cls.__dataclass_fields__), "robustness report"
        )
        failures = data["failure_isolation"]
        replays = data["receipt_replays"]
        if not isinstance(failures, list) or not isinstance(replays, list):
            raise RobustnessValidationError("report members must be arrays")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            evidence=data["evidence"],  # type: ignore[arg-type]
            failure_isolation=tuple(
                FailureIsolationRecord.from_dict(item) for item in failures
            ),
            receipt_replays=tuple(
                ReplayValidationRecord.from_dict(item) for item in replays
            ),
        )


def canonical_robustness_report_json(report: RobustnessReport) -> str:
    if not isinstance(report, RobustnessReport):
        raise TypeError("report must be a RobustnessReport")
    return canonical_json(report.to_dict())


def write_robustness_report(
    robustness_report: RobustnessReport,
    destination: str | Path,
) -> Path:
    """Persist a canonical report once, refusing accidental replacement."""

    if not isinstance(robustness_report, RobustnessReport):
        raise TypeError("robustness_report must be a RobustnessReport")
    path = Path(destination)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_robustness_report_json(robustness_report))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RobustnessValidationError(
            f"refusing to overwrite immutable robustness report: {path}"
        ) from exc
    return path


def _robust_reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RobustnessValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _artifact_digest(value: Mapping[str, object]) -> str:
    body = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _proof_order(variant_id: str) -> list[str]:
    return [
        stage.value
        for stage in VARIANT_REGISTRY[variant_id].proof_order
    ]


def _validate_capabilities(value: object) -> dict[str, dict[str, str]]:
    data = _mapping(value, "capabilities")
    _exact(data, set(CAPABILITY_KEYS), "capabilities")
    result: dict[str, dict[str, str]] = {}
    for name in CAPABILITY_KEYS:
        record = _mapping(data[name], f"capabilities.{name}")
        _exact(record, {"status", "reason"}, f"capabilities.{name}")
        status = _string(record["status"], f"capabilities.{name}.status")
        if status not in CAPABILITY_STATUS_VALUES:
            raise ProofReportError(
                f"unsupported capabilities.{name}.status: {status!r}"
            )
        reason = _string(
            record["reason"],
            f"capabilities.{name}.reason",
            allow_empty=status == "available",
        )
        result[name] = {"status": status, "reason": reason}
    return result


def _required_proof_capabilities(variant_id: str) -> tuple[str, ...]:
    stages = set(VARIANT_REGISTRY[variant_id].stages)
    required: list[str] = []
    if StageName.SPACY in stages:
        required.append("spacy")
    if StageName.SYMAI in stages:
        required.extend(("symai", "llm_router"))
    if StageName.HAMMER in stages:
        required.append("hammer")
    if StageName.LEANSTRAL in stages:
        required.append("leanstral")
    if StageName.KERNEL in stages:
        required.append("lean_kernel")
    return tuple(required)


def _validate_observation(value: object) -> dict[str, object]:
    data = _mapping(value, "observation")
    fields = {
        "schema",
        "case_id",
        "cache_mode",
        "variant_id",
        "status",
        "source_receipt_sha256",
        "case_result",
        "verification_authority",
        "kernel_accepted",
        "kernel_receipt_sha256",
        "verified_source",
        "proof_order",
        "model_claimed_verified",
        "hammer",
        "leanstral",
        "total_wall_time_ms",
        "model_calls",
        "missing_reason",
    }
    _exact(data, fields, "observation")
    if data["schema"] != PROOF_OBSERVATION_SCHEMA:
        raise ProofReportError("unsupported observation schema")
    case_id = _safe_id(data["case_id"], "observation.case_id")
    if case_id not in ELIGIBLE_CASE_IDS:
        raise ProofReportError(f"ineligible proof case: {case_id}")
    cache_mode = _string(data["cache_mode"], "observation.cache_mode")
    if cache_mode not in CACHE_MODES:
        raise ProofReportError(f"unsupported cache mode: {cache_mode!r}")
    variant_id = _safe_id(data["variant_id"], "observation.variant_id")
    if variant_id not in {*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS}:
        raise ProofReportError(f"unsupported proof variant: {variant_id!r}")
    status = _string(data["status"], "observation.status")
    if status not in STATUS_VALUES:
        raise ProofReportError(f"unsupported observation status: {status!r}")
    _digest(data["source_receipt_sha256"], "observation.source_receipt_sha256")
    if data["case_result"] is not None and not isinstance(
        data["case_result"], Mapping
    ):
        raise ProofReportError("observation.case_result must be an object or null")
    authority = data["verification_authority"]
    if authority not in {None, "native_kernel"}:
        raise ProofReportError("verification authority must be native_kernel or null")
    accepted = _boolean(data["kernel_accepted"], "observation.kernel_accepted")
    receipt = _nullable_digest(
        data["kernel_receipt_sha256"], "observation.kernel_receipt_sha256"
    )
    source = _string(data["verified_source"], "observation.verified_source")
    if source not in SOURCE_VALUES:
        raise ProofReportError(f"unsupported verified_source: {source!r}")
    order = _array(data["proof_order"], "observation.proof_order")
    if order != _proof_order(variant_id):
        raise ProofReportError(
            f"observation proof order differs from frozen {variant_id} policy"
        )
    model_claim = _boolean(
        data["model_claimed_verified"], "observation.model_claimed_verified"
    )

    hammer = _mapping(data["hammer"], "observation.hammer")
    _exact(
        hammer,
        {
            "invoked",
            "candidate_created",
            "premise_recall_numerator",
            "premise_recall_denominator",
            "premise_recall_missing_reason",
            "reconstruction_attempted",
            "reconstruction_succeeded",
            "wall_time_ms",
        },
        "observation.hammer",
    )
    hammer_invoked = _boolean(hammer["invoked"], "observation.hammer.invoked")
    hammer_candidate = _boolean(
        hammer["candidate_created"], "observation.hammer.candidate_created"
    )
    recall_numerator = hammer["premise_recall_numerator"]
    recall_denominator = hammer["premise_recall_denominator"]
    recall_reason = hammer["premise_recall_missing_reason"]
    if (recall_numerator is None) != (recall_denominator is None):
        raise ProofReportError("premise recall numerator and denominator pair")
    if recall_denominator is None:
        if not isinstance(recall_reason, str) or not recall_reason.strip():
            raise ProofReportError("unmeasured premise recall requires a reason")
    else:
        numerator = _count(recall_numerator, "premise recall numerator")
        denominator = _count(recall_denominator, "premise recall denominator")
        if denominator == 0 or numerator > denominator or recall_reason is not None:
            raise ProofReportError("invalid measured premise recall")
    reconstruction_attempted = _boolean(
        hammer["reconstruction_attempted"],
        "observation.hammer.reconstruction_attempted",
    )
    reconstruction_succeeded = _boolean(
        hammer["reconstruction_succeeded"],
        "observation.hammer.reconstruction_succeeded",
    )
    _number(hammer["wall_time_ms"], "observation.hammer.wall_time_ms")
    if hammer_candidate and not hammer_invoked:
        raise ProofReportError("Hammer candidate requires invocation")
    if reconstruction_attempted and not hammer_candidate:
        raise ProofReportError("Hammer reconstruction requires a candidate")
    if reconstruction_succeeded and not reconstruction_attempted:
        raise ProofReportError("Hammer reconstruction success requires an attempt")

    leanstral = _mapping(data["leanstral"], "observation.leanstral")
    _exact(
        leanstral,
        {
            "invoked",
            "candidate_created",
            "repair_attempted",
            "repair_succeeded",
            "wall_time_ms",
        },
        "observation.leanstral",
    )
    lean_invoked = _boolean(
        leanstral["invoked"], "observation.leanstral.invoked"
    )
    lean_candidate = _boolean(
        leanstral["candidate_created"],
        "observation.leanstral.candidate_created",
    )
    repair_attempted = _boolean(
        leanstral["repair_attempted"], "observation.leanstral.repair_attempted"
    )
    repair_succeeded = _boolean(
        leanstral["repair_succeeded"], "observation.leanstral.repair_succeeded"
    )
    _number(leanstral["wall_time_ms"], "observation.leanstral.wall_time_ms")
    if lean_candidate and not lean_invoked:
        raise ProofReportError("Leanstral candidate requires invocation")
    if repair_attempted and not lean_invoked:
        raise ProofReportError("Leanstral repair requires invocation")
    if repair_succeeded and not repair_attempted:
        raise ProofReportError("Leanstral repair success requires an attempt")

    _number(data["total_wall_time_ms"], "observation.total_wall_time_ms")
    _count(data["model_calls"], "observation.model_calls")
    missing_reason = data["missing_reason"]
    if status in {"unavailable", "excluded", "infrastructure_failure"}:
        _string(missing_reason, "observation.missing_reason")
    elif missing_reason is not None:
        raise ProofReportError("completed observations cannot have missing_reason")

    verified = status == "verified"
    if verified != (authority == "native_kernel" and accepted and receipt is not None):
        raise ProofReportError(
            "verified status requires native-kernel acceptance and receipt"
        )
    if not verified and (authority is not None or accepted or receipt is not None):
        raise ProofReportError("nonverified observation has proof authority")
    if source != "none" and not verified:
        raise ProofReportError("verified_source requires a verified observation")
    if source in {"hammer", "both"} and not reconstruction_succeeded:
        raise ProofReportError("Hammer verified source requires reconstruction")
    if source in {"leanstral", "both"} and not lean_candidate:
        raise ProofReportError("Leanstral verified source requires a draft")
    if variant_id == "S1":
        if verified or source != "none" or authority is not None:
            raise ProofReportError("S1 is non-authoritative safety evidence")
        if hammer_invoked or lean_invoked:
            raise ProofReportError("S1 cannot invoke Hammer or Leanstral")
    elif model_claim and verified and source == "none":
        raise ProofReportError("verified model claim has no proof source")
    return dict(data)


def _validate_measured_source(
    row: Mapping[str, object], *, expected_run_id: str | None = None
) -> None:
    """Revalidate the complete durable result behind one measured row."""

    try:
        result = CaseResultRecord.from_dict(row["case_result"])
        validate_kernel_bound_result(result)
    except (ProtocolContractError, TypeError, ValueError) as exc:
        raise ProofReportError(
            "measured observations require a valid complete CaseResultRecord"
        ) from exc
    expected_identity = (
        row["case_id"],
        row["variant_id"],
        row["cache_mode"],
    )
    actual_identity = (
        result.case_id,
        result.variant_id,
        result.cache_mode.value,
    )
    if actual_identity != expected_identity:
        raise ProofReportError("measured case-result identity changed")
    if expected_run_id is not None and result.run_id != expected_run_id:
        raise ProofReportError(
            "measured case-result run id differs from the proof report"
        )
    if result.split is not Split.PILOT:
        raise ProofReportError("measured proof results must use the pilot split")
    if result.digest != row["source_receipt_sha256"]:
        raise ProofReportError("measured case-result digest changed")
    expected_status = {
        OutcomeStatus.VERIFIED: "verified",
        OutcomeStatus.NOT_VERIFIED: "not_verified",
        OutcomeStatus.REJECTED: "rejected",
        OutcomeStatus.UNAVAILABLE: "unavailable",
        OutcomeStatus.EXCLUDED: "excluded",
        OutcomeStatus.INFRASTRUCTURE_FAILURE: "infrastructure_failure",
    }[result.status]
    if row["status"] != expected_status:
        raise ProofReportError("measured case-result status changed")
    expected_authority = (
        "native_kernel"
        if result.verification_authority is VerificationAuthority.NATIVE_KERNEL
        else None
    )
    if (
        row["verification_authority"] != expected_authority
        or row["kernel_accepted"] != result.kernel_accepted
        or row["kernel_receipt_sha256"] != result.kernel_receipt_sha256
    ):
        raise ProofReportError("measured kernel authority projection changed")

    definition = VARIANT_REGISTRY[result.variant_id]
    expected_stages = tuple(definition.stages)
    actual_stages = tuple(stage.stage for stage in result.stages)
    terminal_missing = result.status in {
        OutcomeStatus.UNAVAILABLE,
        OutcomeStatus.EXCLUDED,
        OutcomeStatus.INFRASTRUCTURE_FAILURE,
    }
    route_matches = (
        actual_stages == expected_stages[: len(actual_stages)]
        if terminal_missing
        else actual_stages == expected_stages
    )
    if not route_matches:
        raise ProofReportError(
            "measured case-result route differs from the frozen variant"
        )
    total_wall_time_ms = round(
        sum(stage.telemetry.wall_time_ms for stage in result.stages), 6
    )
    if not math.isclose(
        float(row["total_wall_time_ms"]),
        total_wall_time_ms,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ProofReportError(
            "measured proof latency differs from stage telemetry"
        )
    model_calls = sum(stage.telemetry.model_calls for stage in result.stages)
    if row["model_calls"] != model_calls:
        raise ProofReportError(
            "measured proof model calls differ from stage telemetry"
        )

    by_stage = {stage.stage: stage for stage in result.stages}
    hammer_stage = by_stage.get(StageName.HAMMER)
    hammer = _mapping(row["hammer"], "observation.hammer")
    if hammer["invoked"] is not (hammer_stage is not None):
        raise ProofReportError(
            "Hammer invocation differs from the case-result route"
        )
    expected_hammer_wall = (
        0.0 if hammer_stage is None else hammer_stage.telemetry.wall_time_ms
    )
    if not math.isclose(
        float(hammer["wall_time_ms"]),
        expected_hammer_wall,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ProofReportError(
            "Hammer latency differs from stage telemetry"
        )
    hammer_data = (
        {}
        if hammer_stage is None or not isinstance(hammer_stage.data, Mapping)
        else hammer_stage.data
    )
    candidate = hammer_data.get(
        "proof_candidate", hammer_data.get("candidate")
    )
    reconstruction = hammer_data.get("reconstruction")
    if hammer["candidate_created"] is not (candidate is not None):
        raise ProofReportError(
            "Hammer candidate projection differs from stage evidence"
        )
    if hammer["reconstruction_attempted"] is not (
        reconstruction is not None
    ):
        raise ProofReportError(
            "Hammer reconstruction projection differs from stage evidence"
        )
    reconstruction_succeeded = bool(
        reconstruction is not None
        and hammer_stage is not None
        and hammer_stage.status.value == "success"
    )
    if hammer["reconstruction_succeeded"] is not reconstruction_succeeded:
        raise ProofReportError(
            "Hammer reconstruction result differs from stage evidence"
        )

    lean_stage = by_stage.get(StageName.LEANSTRAL)
    leanstral = _mapping(row["leanstral"], "observation.leanstral")
    if leanstral["invoked"] is not (lean_stage is not None):
        raise ProofReportError(
            "Leanstral invocation differs from the case-result route"
        )
    expected_lean_wall = (
        0.0 if lean_stage is None else lean_stage.telemetry.wall_time_ms
    )
    if not math.isclose(
        float(leanstral["wall_time_ms"]),
        expected_lean_wall,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ProofReportError(
            "Leanstral latency differs from stage telemetry"
        )
    lean_data = (
        {}
        if lean_stage is None or not isinstance(lean_stage.data, Mapping)
        else lean_stage.data
    )
    lean_candidate = lean_data.get("draft")
    if leanstral["candidate_created"] is not (lean_candidate is not None):
        raise ProofReportError(
            "Leanstral candidate projection differs from stage evidence"
        )
    repair_attempts = lean_data.get("repair_attempts", 0)
    repair_attempted = (
        isinstance(repair_attempts, int)
        and not isinstance(repair_attempts, bool)
        and repair_attempts > 0
    )
    if leanstral["repair_attempted"] is not repair_attempted:
        raise ProofReportError(
            "Leanstral repair projection differs from stage evidence"
        )
    repair_succeeded = bool(
        repair_attempted
        and lean_candidate is not None
        and lean_stage is not None
        and lean_stage.status.value == "success"
    )
    if leanstral["repair_succeeded"] is not repair_succeeded:
        raise ProofReportError(
            "Leanstral repair result differs from stage evidence"
        )


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _variant_metric(
    variant_id: str,
    cache_mode: str,
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows = [
        row
        for row in observations
        if row["variant_id"] == variant_id and row["cache_mode"] == cache_mode
    ]
    status_counts = {
        status: sum(row["status"] == status for row in rows)
        for status in sorted(STATUS_VALUES)
    }
    eligible = (
        status_counts["verified"]
        + status_counts["not_verified"]
        + status_counts["rejected"]
    )
    hammer = [_mapping(row["hammer"], "hammer") for row in rows]
    lean = [_mapping(row["leanstral"], "leanstral") for row in rows]
    recall_rows = [
        row
        for row in hammer
        if row["premise_recall_denominator"] is not None
    ]
    recall_numerator = sum(int(row["premise_recall_numerator"]) for row in recall_rows)
    recall_denominator = sum(int(row["premise_recall_denominator"]) for row in recall_rows)
    hammer_candidates = sum(bool(row["candidate_created"]) for row in hammer)
    lean_candidates = sum(bool(row["candidate_created"]) for row in lean)
    reconstructions = sum(bool(row["reconstruction_attempted"]) for row in hammer)
    reconstruction_successes = sum(
        bool(row["reconstruction_succeeded"]) for row in hammer
    )
    repairs = sum(bool(row["repair_attempted"]) for row in lean)
    repair_successes = sum(bool(row["repair_succeeded"]) for row in lean)
    total_latency = sum(float(row["total_wall_time_ms"]) for row in rows)
    return {
        "variant_id": variant_id,
        "cache_mode": cache_mode,
        "attempt_count": len(rows),
        "status_counts": status_counts,
        "kernel_verified_count": status_counts["verified"],
        "kernel_verified_rate": _rate(status_counts["verified"], eligible),
        "premise_recall_numerator": (
            recall_numerator if recall_denominator else None
        ),
        "premise_recall_denominator": (
            recall_denominator if recall_denominator else None
        ),
        "premise_recall_at_budget": _rate(
            recall_numerator, recall_denominator
        ),
        "premise_recall_missing_reason": (
            None if recall_denominator else "gold_premise_set_unavailable"
        ),
        "hammer_candidate_count": hammer_candidates,
        "leanstral_candidate_count": lean_candidates,
        "candidate_overlap_count": sum(
            bool(h["candidate_created"]) and bool(l["candidate_created"])
            for h, l in zip(hammer, lean, strict=True)
        ),
        "reconstruction_attempt_count": reconstructions,
        "reconstruction_success_count": reconstruction_successes,
        "reconstruction_success_rate": _rate(
            reconstruction_successes, reconstructions
        ),
        "repair_attempt_count": repairs,
        "repair_success_count": repair_successes,
        "repair_success_rate": _rate(repair_successes, repairs),
        "hammer_unique_verified_count": sum(
            row["verified_source"] == "hammer" for row in rows
        ),
        "leanstral_unique_verified_count": sum(
            row["verified_source"] == "leanstral" for row in rows
        ),
        "both_source_verified_count": sum(
            row["verified_source"] == "both" for row in rows
        ),
        "total_wall_time_ms": total_latency,
        "mean_wall_time_ms": total_latency / len(rows),
        "model_calls": sum(int(row["model_calls"]) for row in rows),
    }


def _pairwise(
    left: str,
    right: str,
    label: str,
    cache_mode: str,
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    keyed = {
        (str(row["case_id"]), str(row["variant_id"])): row
        for row in observations
        if row["cache_mode"] == cache_mode
    }
    left_only: list[str] = []
    right_only: list[str] = []
    both: list[str] = []
    neither: list[str] = []
    latency_deltas: list[float] = []
    for case_id in ELIGIBLE_CASE_IDS:
        left_row = keyed[(case_id, left)]
        right_row = keyed[(case_id, right)]
        left_verified = left_row["status"] == "verified"
        right_verified = right_row["status"] == "verified"
        if left_verified and right_verified:
            both.append(case_id)
        elif left_verified:
            left_only.append(case_id)
        elif right_verified:
            right_only.append(case_id)
        else:
            neither.append(case_id)
        latency_deltas.append(
            float(right_row["total_wall_time_ms"])
            - float(left_row["total_wall_time_ms"])
        )
    return {
        "label": label,
        "cache_mode": cache_mode,
        "left_variant_id": left,
        "right_variant_id": right,
        "left_only_verified_case_ids": left_only,
        "right_only_verified_case_ids": right_only,
        "both_verified_case_ids": both,
        "neither_verified_case_ids": neither,
        "right_minus_left_total_wall_time_ms": sum(latency_deltas),
    }


def derive_proof_analysis(
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Derive all report metrics from validated case-level observations."""

    primary_metrics = [
        _variant_metric(variant, mode, observations)
        for mode in CACHE_MODES
        for variant in PRIMARY_VARIANT_IDS
    ]
    comparisons = [
        _pairwise(left, right, label, mode, observations)
        for mode in CACHE_MODES
        for left, right, label in PAIRWISE_COMPARISONS
    ]
    diagnostic_rows = [
        row for row in observations if row["variant_id"] == "S1"
    ]
    return {
        "schema": PROOF_ANALYSIS_SCHEMA,
        "coverage": {
            "expected_observation_count": (
                len(ELIGIBLE_CASE_IDS)
                * len(CACHE_MODES)
                * (len(PRIMARY_VARIANT_IDS) + len(DIAGNOSTIC_VARIANT_IDS))
            ),
            "observed_observation_count": len(observations),
            "eligible_case_count": len(ELIGIBLE_CASE_IDS),
            "primary_variant_count": len(PRIMARY_VARIANT_IDS),
            "diagnostic_variant_count": len(DIAGNOSTIC_VARIANT_IDS),
            "cache_mode_count": len(CACHE_MODES),
        },
        "primary_metrics": primary_metrics,
        "pairwise_comparisons": comparisons,
        "s1_diagnostic": {
            "attempt_count": len(diagnostic_rows),
            "model_verified_claim_count": sum(
                bool(row["model_claimed_verified"]) for row in diagnostic_rows
            ),
            "native_kernel_verified_count": 0,
            "included_in_primary_metrics": False,
        },
    }


def validate_proof_report(value: object) -> dict[str, object]:
    """Validate a complete report and recompute every serialized aggregate."""

    data = _mapping(value, "proof_report")
    fields = {
        "schema",
        "evidence",
        "benchmark_id",
        "run_id",
        "execution_mode",
        "protocol_sha256",
        "registry_sha256",
        "corpus_manifest_sha256",
        "pilot_split_sha256",
        "split",
        "eligible_case_ids",
        "excluded_case_ids",
        "cache_modes",
        "primary_variant_ids",
        "diagnostic_variant_ids",
        "capability_inventory_sha256",
        "capabilities",
        "observations",
        "analysis",
        "artifact_sha256",
    }
    _exact(data, fields, "proof_report")
    if data["schema"] != PROOF_REPORT_SCHEMA:
        raise ProofReportError("unsupported proof report schema")
    if data["evidence"] != HSSLEV0526A41():
        raise ProofReportError("proof report evidence marker changed")
    if data["benchmark_id"] != BENCHMARK_ID:
        raise ProofReportError("benchmark_id changed")
    _safe_id(data["run_id"], "run_id")
    execution_mode = _string(data["execution_mode"], "execution_mode")
    if execution_mode not in {"measured", "capability_preflight"}:
        raise ProofReportError("unsupported execution_mode")
    if data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256:
        raise ProofReportError("protocol digest changed")
    if data["registry_sha256"] != VARIANT_REGISTRY_SHA256:
        raise ProofReportError("variant registry digest changed")
    corpus = load_reviewed_corpus()
    if data["corpus_manifest_sha256"] != corpus.manifest_sha256:
        raise ProofReportError("corpus manifest digest changed")
    if data["pilot_split_sha256"] != FROZEN_SPLIT_SHA256[Split.PILOT]:
        raise ProofReportError("pilot split digest changed")
    if data["split"] != "pilot":
        raise ProofReportError("proof report must use pilot split")
    fixed_arrays = (
        ("eligible_case_ids", ELIGIBLE_CASE_IDS),
        ("excluded_case_ids", EXCLUDED_CASE_IDS),
        ("cache_modes", CACHE_MODES),
        ("primary_variant_ids", PRIMARY_VARIANT_IDS),
        ("diagnostic_variant_ids", DIAGNOSTIC_VARIANT_IDS),
    )
    for field, expected in fixed_arrays:
        if _array(data[field], field) != list(expected):
            raise ProofReportError(f"{field} differs from frozen proof scope")
    capabilities = _validate_capabilities(data["capabilities"])
    capability_digest = hashlib.sha256(
        canonical_json(capabilities).encode("utf-8")
    ).hexdigest()
    if data["capability_inventory_sha256"] != capability_digest:
        raise ProofReportError("capability inventory digest changed")

    raw_observations = _array(data["observations"], "observations")
    observations = [_validate_observation(item) for item in raw_observations]
    coordinates = [
        (
            str(row["case_id"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
        )
        for row in observations
    ]
    expected_coordinates = {
        (case_id, mode, variant)
        for case_id in ELIGIBLE_CASE_IDS
        for mode in CACHE_MODES
        for variant in (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS)
    }
    if len(coordinates) != len(set(coordinates)):
        raise ProofReportError("proof report contains duplicate observations")
    if set(coordinates) != expected_coordinates:
        missing = sorted(expected_coordinates - set(coordinates))
        extra = sorted(set(coordinates) - expected_coordinates)
        raise ProofReportError(
            f"proof observation matrix is incomplete; missing={missing}, extra={extra}"
        )
    expected_order = sorted(
        coordinates,
        key=lambda item: (
            CACHE_MODES.index(item[1]),
            (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS).index(item[2]),
            ELIGIBLE_CASE_IDS.index(item[0]),
        ),
    )
    if coordinates != expected_order:
        raise ProofReportError("proof observations are not in canonical order")

    if execution_mode == "capability_preflight":
        if not any(
            capabilities[name]["status"] != "available"
            for name in CAPABILITY_KEYS
        ):
            raise ProofReportError("preflight missingness requires a capability gap")
        if any(row["status"] != "unavailable" for row in observations):
            raise ProofReportError(
                "capability-preflight observations must remain unavailable"
            )
        if any(row["case_result"] is not None for row in observations):
            raise ProofReportError(
                "capability preflight cannot embed fabricated case results"
            )
    else:
        for row in observations:
            if row["case_result"] is None:
                raise ProofReportError(
                    "measured observations require full case-result evidence"
                )
            _validate_measured_source(
                row, expected_run_id=str(data["run_id"])
            )
            if row["status"] not in {
                "unavailable",
                "excluded",
                "infrastructure_failure",
            }:
                missing = [
                    name
                    for name in _required_proof_capabilities(
                        str(row["variant_id"])
                    )
                    if capabilities[name]["status"] != "available"
                ]
                if missing:
                    raise ProofReportError(
                        "measured proof result conflicts with unavailable "
                        f"capabilities: {', '.join(missing)}"
                    )
    derived = derive_proof_analysis(observations)
    if data["analysis"] != derived:
        raise ProofReportError("serialized proof analysis differs from observations")
    expected_digest = _artifact_digest(data)
    if data["artifact_sha256"] != expected_digest:
        raise ProofReportError("proof report artifact digest changed")
    return dict(data)


def load_proof_report(path: str | Path = DEFAULT_PROOF_REPORT_PATH) -> dict[str, object]:
    """Load canonical newline JSON and validate the full proof report."""

    report_path = Path(path)
    try:
        text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProofReportError(f"cannot read proof report: {report_path}") from exc
    if not text.endswith("\n"):
        raise ProofReportError("proof report is not canonical newline JSON")
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ProofReportError) as exc:
        raise ProofReportError("proof report is not strict JSON") from exc
    if canonical_json(value) + "\n" != text:
        raise ProofReportError("proof report is not canonical JSON")
    return validate_proof_report(value)


def create_capability_preflight_report() -> dict[str, object]:
    """Create the canonical checked-in missingness evidence.

    The capture reflects the repository preflight on 2026-07-24.  Receipt
    digests bind each scheduled coordinate to the immutable inventory digest;
    they are not kernel receipts and can never enter the verified numerator.
    """

    capabilities = {
        "spacy": {
            "status": "unavailable",
            "reason": "requested en_core_web_sm pipeline is not installed",
        },
        "symai": {
            "status": "degraded",
            "reason": "provider and model identity are incomplete",
        },
        "llm_router": {
            "status": "degraded",
            "reason": "provider and model identity are incomplete",
        },
        "hammer": {
            "status": "available",
            "reason": "",
        },
        "leanstral": {
            "status": "unavailable",
            "reason": "endpoint and model identity are not configured",
        },
        "lean_kernel": {
            "status": "available",
            "reason": "",
        },
    }
    capability_inventory_sha256 = hashlib.sha256(
        canonical_json(capabilities).encode("utf-8")
    ).hexdigest()
    observations: list[dict[str, object]] = []
    for mode in CACHE_MODES:
        for variant in (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS):
            definition = VARIANT_REGISTRY[variant]
            missing = []
            if variant != "S1" and capabilities["spacy"]["status"] != "available":
                missing.append("spacy")
            if any(stage.value == "symai" for stage in definition.stages):
                if capabilities["symai"]["status"] != "available":
                    missing.append("symai")
                if capabilities["llm_router"]["status"] != "available":
                    missing.append("llm_router")
            if any(stage.value == "leanstral" for stage in definition.stages):
                if capabilities["leanstral"]["status"] != "available":
                    missing.append("leanstral")
            missing_reason = "capability unavailable or degraded: " + ", ".join(
                dict.fromkeys(missing)
            )
            for case_id in ELIGIBLE_CASE_IDS:
                coordinate = {
                    "capability_inventory_sha256": capability_inventory_sha256,
                    "case_id": case_id,
                    "cache_mode": mode,
                    "variant_id": variant,
                    "missing_reason": missing_reason,
                }
                observations.append(
                    {
                        "schema": PROOF_OBSERVATION_SCHEMA,
                        "case_id": case_id,
                        "cache_mode": mode,
                        "variant_id": variant,
                        "status": "unavailable",
                        "source_receipt_sha256": hashlib.sha256(
                            canonical_json(coordinate).encode("utf-8")
                        ).hexdigest(),
                        "case_result": None,
                        "verification_authority": None,
                        "kernel_accepted": False,
                        "kernel_receipt_sha256": None,
                        "verified_source": "none",
                        "proof_order": _proof_order(variant),
                        "model_claimed_verified": False,
                        "hammer": {
                            "invoked": False,
                            "candidate_created": False,
                            "premise_recall_numerator": None,
                            "premise_recall_denominator": None,
                            "premise_recall_missing_reason": (
                                "gold_premise_set_unavailable"
                            ),
                            "reconstruction_attempted": False,
                            "reconstruction_succeeded": False,
                            "wall_time_ms": 0.0,
                        },
                        "leanstral": {
                            "invoked": False,
                            "candidate_created": False,
                            "repair_attempted": False,
                            "repair_succeeded": False,
                            "wall_time_ms": 0.0,
                        },
                        "total_wall_time_ms": 0.0,
                        "model_calls": 0,
                        "missing_reason": missing_reason,
                    }
                )
    report: dict[str, object] = {
        "schema": PROOF_REPORT_SCHEMA,
        "evidence": HSSLEV0526A41(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": "proof-overlap-ordering-v1",
        "execution_mode": "capability_preflight",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": load_reviewed_corpus().manifest_sha256,
        "pilot_split_sha256": FROZEN_SPLIT_SHA256[Split.PILOT],
        "split": "pilot",
        "eligible_case_ids": list(ELIGIBLE_CASE_IDS),
        "excluded_case_ids": list(EXCLUDED_CASE_IDS),
        "cache_modes": list(CACHE_MODES),
        "primary_variant_ids": list(PRIMARY_VARIANT_IDS),
        "diagnostic_variant_ids": list(DIAGNOSTIC_VARIANT_IDS),
        "capability_inventory_sha256": capability_inventory_sha256,
        "capabilities": capabilities,
        "observations": observations,
        "analysis": derive_proof_analysis(observations),
        "artifact_sha256": "",
    }
    report["artifact_sha256"] = _artifact_digest(report)
    return validate_proof_report(report)


def build_proof_report(
    run_id: str,
    capabilities: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build canonical measured proof evidence from complete case receipts.

    Observation rows carry descriptive proof-source fields, but their durable
    ``CaseResultRecord`` remains authoritative.  This builder canonicalizes
    the complete frozen pilot matrix, derives all aggregate proof and routing
    metrics, content-addresses the artifact, and executes strict validation.
    """

    safe_run_id = _safe_id(run_id, "run_id")
    capability_records = _validate_capabilities(capabilities)
    if isinstance(observations, (str, bytes, Mapping)):
        raise ProofReportError(
            "observations must be a sequence of observation mappings"
        )
    try:
        rows = [_validate_observation(item) for item in observations]
    except TypeError as exc:
        raise ProofReportError(
            "observations must be a sequence of observation mappings"
        ) from exc
    for row in rows:
        _validate_measured_source(row, expected_run_id=safe_run_id)

    variant_order = (*PRIMARY_VARIANT_IDS, *DIAGNOSTIC_VARIANT_IDS)
    order = {
        (case_id, mode, variant): index
        for index, (case_id, mode, variant) in enumerate(
            (
                (case_id, mode, variant)
                for mode in CACHE_MODES
                for variant in variant_order
                for case_id in ELIGIBLE_CASE_IDS
            )
        )
    }
    coordinates = [
        (
            str(row["case_id"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
        )
        for row in rows
    ]
    if len(coordinates) != len(set(coordinates)):
        raise ProofReportError(
            "proof report contains duplicate observations"
        )
    if set(coordinates) != set(order):
        raise ProofReportError(
            "proof observation matrix is incomplete; "
            f"missing={sorted(set(order) - set(coordinates))}, "
            f"extra={sorted(set(coordinates) - set(order))}"
        )
    rows.sort(
        key=lambda row: order[
            (
                str(row["case_id"]),
                str(row["cache_mode"]),
                str(row["variant_id"]),
            )
        ]
    )
    capability_inventory_sha256 = hashlib.sha256(
        canonical_json(capability_records).encode("utf-8")
    ).hexdigest()
    value: dict[str, object] = {
        "schema": PROOF_REPORT_SCHEMA,
        "evidence": HSSLEV0526A41(),
        "benchmark_id": BENCHMARK_ID,
        "run_id": safe_run_id,
        "execution_mode": "measured",
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "registry_sha256": VARIANT_REGISTRY_SHA256,
        "corpus_manifest_sha256": load_reviewed_corpus().manifest_sha256,
        "pilot_split_sha256": FROZEN_SPLIT_SHA256[Split.PILOT],
        "split": "pilot",
        "eligible_case_ids": list(ELIGIBLE_CASE_IDS),
        "excluded_case_ids": list(EXCLUDED_CASE_IDS),
        "cache_modes": list(CACHE_MODES),
        "primary_variant_ids": list(PRIMARY_VARIANT_IDS),
        "diagnostic_variant_ids": list(DIAGNOSTIC_VARIANT_IDS),
        "capability_inventory_sha256": capability_inventory_sha256,
        "capabilities": capability_records,
        "observations": rows,
        "analysis": derive_proof_analysis(rows),
        "artifact_sha256": "",
    }
    value["artifact_sha256"] = _artifact_digest(value)
    return validate_proof_report(value)


class EfficiencyReportError(ValueError):
    """Raised when delegation-efficiency evidence is incomplete or altered."""


def build_efficiency_report(
    escalations: Sequence[EfficiencyEscalation],
    observations: Sequence[EfficiencyObservation],
    *,
    execution_mode: str = "measured",
    missing_reason: str | None = None,
) -> dict[str, object]:
    """Build a canonical report from case-result and resource receipts."""

    if execution_mode not in {"measured", "capability_preflight"}:
        raise EfficiencyReportError("unsupported efficiency execution_mode")
    escalation_records = tuple(escalations)
    observation_records = tuple(observations)
    if not escalation_records or any(
        not isinstance(item, EfficiencyEscalation) for item in escalation_records
    ):
        raise EfficiencyReportError(
            "escalations must contain EfficiencyEscalation values"
        )
    if any(
        not isinstance(item, EfficiencyObservation) for item in observation_records
    ):
        raise EfficiencyReportError(
            "observations must contain EfficiencyObservation values"
        )
    if execution_mode == "measured":
        if missing_reason is not None:
            raise EfficiencyReportError(
                "a measured efficiency report cannot carry missing_reason"
            )
        if not observation_records:
            raise EfficiencyReportError(
                "a measured efficiency report requires observations"
            )
    else:
        if not isinstance(missing_reason, str) or not missing_reason.strip():
            raise EfficiencyReportError(
                "capability preflight requires a missing_reason"
            )
        if observation_records:
            raise EfficiencyReportError(
                "capability preflight cannot contain measured observations"
            )
    ordered_escalations = tuple(
        sorted(escalation_records, key=lambda item: item.step_index)
    )
    step_order = {
        item.variant_id: item.step_index for item in ordered_escalations
    }
    try:
        ordered_observations = tuple(
            sorted(
                observation_records,
                key=lambda item: (
                    step_order[item.case_result.variant_id],
                    item.case_result.case_id,
                ),
            )
        )
        analysis = analyze_delegation_efficiency(
            ordered_escalations,
            ordered_observations,
            allow_empty=execution_mode == "capability_preflight",
        )
    except (MetricsContractError, KeyError) as exc:
        raise EfficiencyReportError(str(exc)) from exc
    value: dict[str, object] = {
        "schema": EFFICIENCY_REPORT_SCHEMA,
        "evidence": HSSLEV0615B24(),
        "benchmark_id": BENCHMARK_ID,
        "execution_mode": execution_mode,
        "missing_reason": missing_reason,
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "escalations": [item.to_dict() for item in ordered_escalations],
        "observations": [item.to_dict() for item in ordered_observations],
        "analysis": analysis,
        "artifact_sha256": "",
    }
    value["artifact_sha256"] = _artifact_digest(value)
    return validate_efficiency_report(value)


def create_efficiency_capability_preflight_report() -> dict[str, object]:
    """Create non-efficacy evidence for environments without measured traces."""

    return build_efficiency_report(
        DEFAULT_EFFICIENCY_ESCALATIONS,
        (),
        execution_mode="capability_preflight",
        missing_reason=(
            "no complete paired A1-A4 case-result and operational-resource "
            "receipt matrix was supplied; efficacy and cost ratios remain null"
        ),
    )


def validate_efficiency_report(value: object) -> dict[str, object]:
    """Strictly reparse and recompute a delegation-efficiency report."""

    data = _mapping(value, "efficiency_report")
    fields = {
        "schema",
        "evidence",
        "benchmark_id",
        "execution_mode",
        "missing_reason",
        "protocol_sha256",
        "escalations",
        "observations",
        "analysis",
        "artifact_sha256",
    }
    try:
        _exact(data, fields, "efficiency_report")
        if data["schema"] != EFFICIENCY_REPORT_SCHEMA:
            raise EfficiencyReportError("unsupported efficiency report schema")
        if data["evidence"] != HSSLEV0615B24():
            raise EfficiencyReportError("efficiency evidence marker changed")
        if data["benchmark_id"] != BENCHMARK_ID:
            raise EfficiencyReportError("efficiency benchmark_id changed")
        if data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256:
            raise EfficiencyReportError("efficiency protocol digest changed")
        execution_mode = _string(data["execution_mode"], "execution_mode")
        if execution_mode not in {"measured", "capability_preflight"}:
            raise EfficiencyReportError(
                "unsupported efficiency execution_mode"
            )
        raw_steps = _array(data["escalations"], "escalations")
        steps = tuple(EfficiencyEscalation.from_dict(item) for item in raw_steps)
        if any(item.variant_id not in VARIANT_REGISTRY for item in steps):
            raise EfficiencyReportError(
                "efficiency escalation references an unregistered variant"
            )
        if [item.step_index for item in steps] != list(range(len(steps))):
            raise EfficiencyReportError(
                "efficiency escalations are not in canonical order"
            )
        raw_observations = _array(data["observations"], "observations")
        observations = tuple(
            EfficiencyObservation.from_dict(item) for item in raw_observations
        )
        order = {item.variant_id: item.step_index for item in steps}
        coordinates = [
            (order[item.case_result.variant_id], item.case_result.case_id)
            for item in observations
        ]
        if coordinates != sorted(coordinates):
            raise EfficiencyReportError(
                "efficiency observations are not in canonical order"
            )
        if len(coordinates) != len(set(coordinates)):
            raise EfficiencyReportError(
                "efficiency report contains duplicate observations"
            )
        missing_reason = data["missing_reason"]
        if execution_mode == "capability_preflight":
            if observations:
                raise EfficiencyReportError(
                    "capability preflight cannot contain measured observations"
                )
            _string(missing_reason, "missing_reason")
        else:
            if not observations:
                raise EfficiencyReportError(
                    "measured efficiency report requires observations"
                )
            if missing_reason is not None:
                raise EfficiencyReportError(
                    "measured efficiency report cannot carry missing_reason"
                )
        derived = analyze_delegation_efficiency(
            steps,
            observations,
            allow_empty=execution_mode == "capability_preflight",
        )
    except (MetricsContractError, ProofReportError, KeyError) as exc:
        if isinstance(exc, EfficiencyReportError):
            raise
        raise EfficiencyReportError(str(exc)) from exc
    if data["analysis"] != derived:
        raise EfficiencyReportError(
            "serialized efficiency analysis differs from observations"
        )
    if data["artifact_sha256"] != _artifact_digest(data):
        raise EfficiencyReportError("efficiency report artifact digest changed")
    return dict(data)


def load_efficiency_report(path: str | Path) -> dict[str, object]:
    """Load strict canonical newline JSON efficiency evidence."""

    report_path = Path(path)
    try:
        text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EfficiencyReportError(
            f"cannot read efficiency report: {report_path}"
        ) from exc
    if not text.endswith("\n"):
        raise EfficiencyReportError(
            "efficiency report is not canonical newline JSON"
        )
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ProofReportError) as exc:
        raise EfficiencyReportError(
            "efficiency report is not strict JSON"
        ) from exc
    if canonical_json(value) + "\n" != text:
        raise EfficiencyReportError("efficiency report is not canonical JSON")
    return validate_efficiency_report(value)


def efficiency_summary(report: Mapping[str, object]) -> dict[str, object]:
    """Return the stable one-line CLI summary for validated evidence."""

    analysis = _mapping(report["analysis"], "analysis")
    frontier = _array(analysis["frontier_variant_ids"], "frontier_variant_ids")
    return {
        "section": "efficiency",
        "status": "valid",
        "execution_mode": report["execution_mode"],
        "artifact_sha256": report["artifact_sha256"],
        "observation_count": len(_array(report["observations"], "observations")),
        "measured": analysis["measured"],
        "frontier_variant_ids": frontier,
        "safety_is_hard_constraint": analysis["safety_is_hard_constraint"],
        "missing_reason": report["missing_reason"],
    }


_FINAL_DECISION_SOURCE_ARTIFACTS: Final = {
    "baseline": (
        "workspace/benchmarks/hammer-symai-spacy-leanstral/"
        "a0-baseline-v1/state/baseline-manifest.json",
        "ipfs-datasets.logic-pipeline-benchmark.frozen-baseline-manifest.v1",
    ),
    "frontend": (
        "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
        "frontend-overlap-v1.json",
        "ipfs-datasets.logic-pipeline-benchmark.frontend-overlap-report.v1",
    ),
    "proof": (
        "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
        "proof-overlap-ordering-v1.json",
        "ipfs-datasets.logic-pipeline-benchmark.proof-overlap-report.v1",
    ),
    "pilot": (
        "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
        "pilot-shortlist-v1.json",
        "ipfs-datasets.logic-pipeline-benchmark.pilot-shortlist-gate.v1",
    ),
    "holdout": (
        "workspace/benchmarks/hammer-symai-spacy-leanstral/results/"
        "holdout-evaluation-v1.json",
        "ipfs-datasets.logic-pipeline-benchmark.paired-holdout-gate.v1",
    ),
}
_FINAL_DECISION_COMPONENTS: Final = ("spacy", "symai", "hammer", "leanstral")
_FINAL_DECISION_VARIANTS: Final = (
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "A7",
    "A8",
    "A9",
    "A10",
    "A11",
    "A12",
    "S1",
)
_RUNBOOK_HEADINGS: Final = (
    "Purpose and authority",
    "Published decision",
    "Ownership and delegation matrix",
    "Trust boundaries and invariants",
    "Clean-worktree operating flow",
    "Preflight and capability probe",
    "Objective ingestion and backlog alignment",
    "Baseline and ablation execution",
    "Pilot and shortlist gate",
    "Holdout gate",
    "Replay and reporting",
    "Phase gates",
    "Evidence inventory and freshness",
    "Incident response",
    "Rollback and fallback",
    "Handoff checklist",
    "HSSLEV1006B8A traceability",
)


def _decision_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise FinalDecisionValidationError(f"{field} must be an object")
    return value


def _decision_array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise FinalDecisionValidationError(f"{field} must be an array")
    return value


def _decision_exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    if set(value) != expected:
        raise FinalDecisionValidationError(
            f"{field} fields changed; expected {sorted(expected)}, "
            f"got {sorted(value)}"
        )


def _decision_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinalDecisionValidationError(f"{field} must be a nonempty string")
    return value


def _decision_false(value: object, field: str) -> None:
    if value is not False:
        raise FinalDecisionValidationError(
            f"{field} must remain false without paired holdout evidence"
        )


def _repository_file(root: Path, relative_path: str, field: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise FinalDecisionValidationError(
            f"{field} must be a repository-relative path"
        )
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise FinalDecisionValidationError(f"{field} escapes the repository")
    if not resolved.is_file():
        raise FinalDecisionValidationError(f"{field} does not exist: {candidate}")
    return resolved


def _strict_json_file(path: Path, description: str) -> tuple[object, bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise FinalDecisionValidationError(
            f"cannot read {description}: {path}"
        ) from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ProofReportError) as exc:
        raise FinalDecisionValidationError(
            f"{description} is not strict JSON"
        ) from exc
    return value, raw


def validate_final_decision(
    value: object, *, repository_root: str | Path = "."
) -> dict[str, object]:
    """Validate the final decision and every immutable evidence binding.

    The decision intentionally remains inconclusive while the paired holdout
    is sealed and unopened.  This validator therefore fails if missing
    measurements are converted to efficacy, a component is promoted, or a
    bound source artifact changes on disk.
    """

    envelope = _decision_mapping(value, "snapshot")
    _decision_exact(
        envelope,
        {"benchmark_script", "captured_on", "notes", "results"},
        "snapshot",
    )
    if envelope["benchmark_script"] != (
        "python benchmarks/logic_pipeline/report.py --validate-final-decision"
    ):
        raise FinalDecisionValidationError("benchmark_script changed")
    captured_on = _decision_string(envelope["captured_on"], "captured_on")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured_on) is None:
        raise FinalDecisionValidationError("captured_on must use YYYY-MM-DD")
    notes = _decision_array(envelope["notes"], "notes")
    if not notes or any(
        not isinstance(note, str) or not note.strip() for note in notes
    ):
        raise FinalDecisionValidationError("notes must contain nonempty strings")

    results = _decision_mapping(envelope["results"], "results")
    _decision_exact(
        results,
        {
            "artifact_sha256",
            "schema",
            "evidence",
            "evidence_symbol",
            "source_artifacts",
            "decision",
            "component_decisions",
            "delegation_matrix",
            "policy_decisions",
            "tradeoffs",
            "rejected_alternatives",
            "required_follow_up",
        },
        "results",
    )
    if results["schema"] != FINAL_DECISION_SCHEMA:
        raise FinalDecisionValidationError("final decision schema changed")
    if results["evidence"] != HSSLEV1006B8A():
        raise FinalDecisionValidationError("final decision evidence marker changed")
    if results["evidence_symbol"] != "HSSLEV1006B8A":
        raise FinalDecisionValidationError("final decision evidence symbol changed")
    artifact_sha256 = results["artifact_sha256"]
    if not isinstance(artifact_sha256, str) or not _SHA256.fullmatch(
        artifact_sha256
    ):
        raise FinalDecisionValidationError(
            "artifact_sha256 must be a lowercase SHA-256 digest"
        )
    expected_artifact_sha256 = hashlib.sha256(
        canonical_json(
            {
                key: item
                for key, item in results.items()
                if key != "artifact_sha256"
            }
        ).encode("utf-8")
    ).hexdigest()
    if artifact_sha256 != expected_artifact_sha256:
        raise FinalDecisionValidationError("final decision artifact digest changed")

    root = Path(repository_root)
    sources = _decision_mapping(results["source_artifacts"], "source_artifacts")
    if tuple(sources) != tuple(_FINAL_DECISION_SOURCE_ARTIFACTS):
        raise FinalDecisionValidationError(
            "source_artifacts must retain baseline-to-holdout order and scope"
        )
    for name, (expected_path, expected_schema) in (
        _FINAL_DECISION_SOURCE_ARTIFACTS.items()
    ):
        binding = _decision_mapping(
            sources[name], f"source_artifacts.{name}"
        )
        _decision_exact(
            binding,
            {"path", "content_sha256", "semantic_sha256", "schema"},
            f"source_artifacts.{name}",
        )
        if binding["path"] != expected_path:
            raise FinalDecisionValidationError(
                f"source_artifacts.{name}.path changed"
            )
        if binding["schema"] != expected_schema:
            raise FinalDecisionValidationError(
                f"source_artifacts.{name}.schema changed"
            )
        source_path = _repository_file(
            root, expected_path, f"source_artifacts.{name}.path"
        )
        source_value, source_bytes = _strict_json_file(
            source_path, f"{name} source artifact"
        )
        content_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if binding["content_sha256"] != content_sha256:
            raise FinalDecisionValidationError(
                f"source_artifacts.{name}.content_sha256 changed"
            )
        source_data = _decision_mapping(
            source_value, f"source_artifacts.{name}.document"
        )
        if source_data.get("schema") != expected_schema:
            raise FinalDecisionValidationError(
                f"bound {name} source schema differs from its binding"
            )
        semantic_sha256 = source_data.get("artifact_sha256")
        if semantic_sha256 is None:
            semantic_sha256 = hashlib.sha256(
                canonical_json(source_data).encode("utf-8")
            ).hexdigest()
        if binding["semantic_sha256"] != semantic_sha256:
            raise FinalDecisionValidationError(
                f"source_artifacts.{name}.semantic_sha256 changed"
            )

    # Recompute both phase gates through their own source-backed trust
    # boundaries.  Digest agreement alone is insufficient: a coordinated
    # rewrite of a gate and this snapshot must not turn an unopened holdout
    # into authorization.
    from benchmarks.logic_pipeline.holdout_gate import (
        HoldoutGateError,
        load_holdout_gate_report,
    )
    from benchmarks.logic_pipeline.pilot_gate import (
        PilotGateError,
        load_pilot_gate_report,
    )

    try:
        pilot_gate = load_pilot_gate_report(repository_root=root)
        holdout_gate = load_holdout_gate_report(repository_root=root)
    except (PilotGateError, HoldoutGateError) as exc:
        raise FinalDecisionValidationError(
            f"final decision phase-gate source validation failed: {exc}"
        ) from exc
    pilot_shortlist = _decision_mapping(
        pilot_gate.get("shortlist"), "pilot.shortlist"
    )
    pilot_decision = _decision_mapping(
        pilot_gate.get("decision"), "pilot.decision"
    )
    if (
        pilot_shortlist.get("status") != "incomplete"
        or pilot_shortlist.get("selected_variant_ids") != []
        or pilot_shortlist.get("selected_count") != 0
        or pilot_shortlist.get("frozen") is not True
        or pilot_decision.get("holdout_authorized") is not False
        or pilot_decision.get("production_promotion_authorized") is not False
    ):
        raise FinalDecisionValidationError(
            "final decision requires an incomplete, empty, frozen pilot "
            "shortlist with no holdout or production authorization"
        )
    holdout_decision = _decision_mapping(
        holdout_gate.get("decision"), "holdout.decision"
    )
    holdout_access = _decision_mapping(
        holdout_gate.get("access"), "holdout.access"
    )
    holdout_outcomes = _decision_mapping(
        holdout_gate.get("outcomes"), "holdout.outcomes"
    )
    if (
        holdout_decision.get("status") != "blocked"
        or holdout_decision.get("seal_status") != "sealed_unopened"
        or holdout_decision.get("holdout_untouched") is not True
        or holdout_decision.get("paired_evaluation_complete") is not False
        or holdout_decision.get("production_promotion_authorized") is not False
        or holdout_access.get("status") != "unopened"
        or holdout_access.get("authorized") is not False
        or holdout_access.get("outcomes_inspected") is not False
        or holdout_outcomes.get("status") != "not_run"
        or holdout_outcomes.get("efficacy_claimed") is not False
        or holdout_outcomes.get("case_results") != []
    ):
        raise FinalDecisionValidationError(
            "final decision requires the blocked, sealed, unopened holdout "
            "with no access, outcomes, efficacy, or promotion"
        )

    decision = _decision_mapping(results["decision"], "decision")
    _decision_exact(
        decision,
        {
            "architecture_outcome",
            "current_architecture_action",
            "evidence_status",
            "holdout_status",
            "paired_holdout_evidence_available",
            "production_promotion_authorized",
            "selected_variant_id",
            "selected_policy",
            "rationale",
        },
        "decision",
    )
    required_decision = {
        "architecture_outcome": "gather_more_evidence",
        "current_architecture_action": "retain_unchanged_pending_evidence",
        "evidence_status": "inconclusive",
        "holdout_status": "sealed_unopened",
        "paired_holdout_evidence_available": False,
        "production_promotion_authorized": False,
        "selected_variant_id": None,
        "selected_policy": None,
    }
    for field, expected in required_decision.items():
        if decision.get(field) != expected:
            raise FinalDecisionValidationError(
                f"decision.{field} must remain {expected!r}"
            )
    _decision_string(decision.get("rationale"), "decision.rationale")

    components = _decision_array(
        results["component_decisions"], "component_decisions"
    )
    component_names: list[str] = []
    for index, item in enumerate(components):
        component = _decision_mapping(item, f"component_decisions[{index}]")
        _decision_exact(
            component,
            {
                "component",
                "current_responsibility",
                "candidate_responsibility",
                "disposition",
                "promotion_authorized",
                "evidence_basis",
            },
            f"component_decisions[{index}]",
        )
        name = _decision_string(
            component.get("component"), f"component_decisions[{index}].component"
        )
        component_names.append(name)
        _decision_false(
            component.get("promotion_authorized"),
            f"component_decisions[{index}].promotion_authorized",
        )
        _decision_string(
            component.get("disposition"),
            f"component_decisions[{index}].disposition",
        )
        _decision_string(
            component.get("evidence_basis"),
            f"component_decisions[{index}].evidence_basis",
        )
    if tuple(component_names) != _FINAL_DECISION_COMPONENTS:
        raise FinalDecisionValidationError(
            "component decisions must cover spaCy, SyMAI, Hammer, and Leanstral "
            "exactly once in canonical order"
        )

    matrix = _decision_array(results["delegation_matrix"], "delegation_matrix")
    variant_ids: list[str] = []
    for index, item in enumerate(matrix):
        row = _decision_mapping(item, f"delegation_matrix[{index}]")
        _decision_exact(
            row,
            {
                "variant_id",
                "role",
                "disposition",
                "promotion_authorized",
                "evidence_basis",
            },
            f"delegation_matrix[{index}]",
        )
        variant_ids.append(
            _decision_string(
                row.get("variant_id"),
                f"delegation_matrix[{index}].variant_id",
            )
        )
        _decision_string(
            row.get("role"), f"delegation_matrix[{index}].role"
        )
        _decision_string(
            row.get("disposition"),
            f"delegation_matrix[{index}].disposition",
        )
        _decision_false(
            row.get("promotion_authorized"),
            f"delegation_matrix[{index}].promotion_authorized",
        )
        _decision_string(
            row.get("evidence_basis"),
            f"delegation_matrix[{index}].evidence_basis",
        )
    if tuple(variant_ids) != _FINAL_DECISION_VARIANTS:
        raise FinalDecisionValidationError(
            "delegation matrix must cover A0-A12 and S1 in canonical order"
        )
    if _decision_mapping(matrix[0], "delegation_matrix[0]").get(
        "disposition"
    ) != "current_reference_only":
        raise FinalDecisionValidationError(
            "A0 must remain current_reference_only"
        )
    if any(
        _decision_mapping(item, "delegation_matrix row").get("disposition")
        != "evidence_ineligible"
        for item in matrix[1:13]
    ):
        raise FinalDecisionValidationError(
            "A1-A12 must remain evidence_ineligible"
        )
    if _decision_mapping(matrix[-1], "delegation_matrix[-1]").get(
        "disposition"
    ) != "diagnostic_only_never_candidate":
        raise FinalDecisionValidationError(
            "S1 must remain diagnostic_only_never_candidate"
        )

    policies = _decision_array(results["policy_decisions"], "policy_decisions")
    policy_names: list[str] = []
    for index, item in enumerate(policies):
        policy = _decision_mapping(item, f"policy_decisions[{index}]")
        _decision_exact(
            policy,
            {
                "policy",
                "role",
                "selected",
                "production_authorized",
                "disposition",
            },
            f"policy_decisions[{index}]",
        )
        policy_names.append(
            _decision_string(
                policy.get("policy"),
                f"policy_decisions[{index}].policy",
            )
        )
        _decision_false(
            policy.get("selected"), f"policy_decisions[{index}].selected"
        )
        _decision_false(
            policy.get("production_authorized"),
            f"policy_decisions[{index}].production_authorized",
        )
        if (
            policy.get("disposition")
            != "not_selected_insufficient_paired_holdout_evidence"
        ):
            raise FinalDecisionValidationError(
                f"policy_decisions[{index}] has an unsupported disposition"
            )
        _decision_string(policy.get("role"), f"policy_decisions[{index}].role")
    if policy_names != [
        "P0_ALWAYS_ON",
        "P1_DETERMINISTIC_FIRST",
        "P2_PROOF_FAMILY",
        "P3_BOUNDED_LEARNED",
    ]:
        raise FinalDecisionValidationError(
            "policy decisions must cover P0-P3 in canonical order"
        )

    tradeoffs = _decision_mapping(results["tradeoffs"], "tradeoffs")
    _decision_exact(
        tradeoffs,
        {"verification_authority", "execution_accounting", "domains"},
        "tradeoffs",
    )
    if tradeoffs.get("verification_authority") != "independent_native_kernel_only":
        raise FinalDecisionValidationError(
            "tradeoffs must retain independent native-kernel authority"
        )
    accounting = _decision_mapping(
        tradeoffs.get("execution_accounting"), "tradeoffs.execution_accounting"
    )
    _decision_exact(
        accounting,
        {
            "scheduled_pair_count",
            "observed_pair_count",
            "kernel_verified_success_count",
            "efficacy_claimed",
            "interpretation",
        },
        "tradeoffs.execution_accounting",
    )
    if accounting.get("scheduled_pair_count") != 0:
        raise FinalDecisionValidationError(
            "scheduled_pair_count must reflect the unopened holdout"
        )
    if accounting.get("observed_pair_count") != 0:
        raise FinalDecisionValidationError(
            "observed_pair_count must reflect the unopened holdout"
        )
    if accounting.get("kernel_verified_success_count") != 0:
        raise FinalDecisionValidationError(
            "kernel_verified_success_count must reflect the unopened holdout"
        )
    _decision_false(
        accounting.get("efficacy_claimed"),
        "tradeoffs.execution_accounting.efficacy_claimed",
    )
    _decision_string(
        accounting.get("interpretation"),
        "tradeoffs.execution_accounting.interpretation",
    )
    domains = _decision_array(tradeoffs.get("domains"), "tradeoffs.domains")
    if [
        _decision_mapping(item, "tradeoff domain").get("domain")
        for item in domains
    ] != ["quality", "resource", "complexity"]:
        raise FinalDecisionValidationError(
            "tradeoffs must cover quality, resource, and complexity"
        )
    for index, item in enumerate(domains):
        domain = _decision_mapping(item, f"tradeoffs.domains[{index}]")
        _decision_exact(
            domain,
            {"domain", "measurement_status", "values", "reason"},
            f"tradeoffs.domains[{index}]",
        )
        if domain.get("measurement_status") != "not_observed":
            raise FinalDecisionValidationError(
                f"tradeoffs.domains[{index}] must remain not_observed"
            )
        values = _decision_mapping(
            domain.get("values"), f"tradeoffs.domains[{index}].values"
        )
        if not values or any(item is not None for item in values.values()):
            raise FinalDecisionValidationError(
                f"tradeoffs.domains[{index}] must retain explicit null values"
            )
        _decision_string(
            domain.get("reason"), f"tradeoffs.domains[{index}].reason"
        )

    rejected = _decision_array(
        results["rejected_alternatives"], "rejected_alternatives"
    )
    if not rejected:
        raise FinalDecisionValidationError(
            "rejected_alternatives cannot be empty"
        )
    for index, item in enumerate(rejected):
        alternative = _decision_mapping(
            item, f"rejected_alternatives[{index}]"
        )
        _decision_exact(
            alternative,
            {"alternative", "disposition", "reason"},
            f"rejected_alternatives[{index}]",
        )
        _decision_string(
            alternative.get("alternative"),
            f"rejected_alternatives[{index}].alternative",
        )
        _decision_string(
            alternative.get("reason"),
            f"rejected_alternatives[{index}].reason",
        )
    follow_up = _decision_array(
        results["required_follow_up"], "required_follow_up"
    )
    if len(follow_up) < 4 or any(
        not isinstance(step, str) or not step.strip() for step in follow_up
    ):
        raise FinalDecisionValidationError(
            "required_follow_up must retain the complete gated workflow"
        )
    follow_up_text = " ".join(str(step).lower() for step in follow_up)
    required_follow_up_terms = (
        "capability",
        "pilot",
        "holdout",
        "cold",
        "warm",
        "replay",
        "production promotion",
    )
    if any(term not in follow_up_text for term in required_follow_up_terms):
        raise FinalDecisionValidationError(
            "required_follow_up omits a capability, gate, replay, cache, or "
            "promotion boundary"
        )
    return dict(envelope)


def load_final_decision(
    path: str | Path = DEFAULT_FINAL_DECISION_PATH,
    *,
    repository_root: str | Path = ".",
) -> dict[str, object]:
    """Load and validate the published final architecture decision snapshot."""

    decision_path = Path(path)
    if not decision_path.is_absolute():
        decision_path = Path(repository_root) / decision_path
    try:
        if decision_path.is_symlink() or not decision_path.is_file():
            raise FinalDecisionValidationError(
                "final decision path must be a regular non-symlink file"
            )
        if not 0 < decision_path.stat().st_size <= 2 * 1024 * 1024:
            raise FinalDecisionValidationError(
                "final decision file size is outside the safe bound"
            )
    except OSError as exc:
        raise FinalDecisionValidationError(
            f"cannot inspect final decision snapshot: {decision_path}"
        ) from exc
    value, _ = _strict_json_file(decision_path, "final decision snapshot")
    return validate_final_decision(value, repository_root=repository_root)


def final_decision_summary(value: Mapping[str, object]) -> dict[str, object]:
    """Return the stable CLI summary for a validated final decision."""

    results = _decision_mapping(value["results"], "results")
    decision = _decision_mapping(results["decision"], "decision")
    return {
        "section": "final-decision",
        "status": "valid",
        "artifact_sha256": results["artifact_sha256"],
        "architecture_outcome": decision["architecture_outcome"],
        "evidence_status": decision["evidence_status"],
        "holdout_status": decision["holdout_status"],
        "production_promotion_authorized": False,
        "component_decision_count": len(
            _decision_array(
                results["component_decisions"], "component_decisions"
            )
        ),
        "delegation_row_count": len(
            _decision_array(results["delegation_matrix"], "delegation_matrix")
        ),
        "policy_decision_count": len(
            _decision_array(results["policy_decisions"], "policy_decisions")
        ),
    }


def _runbook_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = re.fullmatch(r"([A-Za-z][A-Za-z -]+):\s+(.+?)\s*", line)
        if match is not None:
            metadata[match.group(1)] = match.group(2).strip().strip("`")
    return metadata


def validate_runbook(
    text: str, *, repository_root: str | Path = "."
) -> dict[str, object]:
    """Validate runbook traceability, coverage, ordering, and safety posture."""

    if not isinstance(text, str) or not text.endswith("\n") or "\x00" in text:
        raise RunbookValidationError(
            "runbook must be newline-terminated UTF-8 text without NUL bytes"
        )
    metadata = _runbook_metadata(text)
    expected_metadata = {
        "Evidence": "HSSLEV1006B8A",
        "Evidence marker": HSSLEV1006B8A(),
        "Decision artifact": DEFAULT_FINAL_DECISION_PATH.as_posix(),
        "Protocol revision": "1",
    }
    for field, expected in expected_metadata.items():
        if metadata.get(field) != expected:
            raise RunbookValidationError(
                f"runbook metadata {field!r} must be {expected!r}"
            )
    headings = re.findall(r"^## (.+?)\s*$", text, flags=re.MULTILINE)
    if tuple(headings) != _RUNBOOK_HEADINGS:
        raise RunbookValidationError(
            "runbook headings changed, are duplicated, or are out of order"
        )

    required_tokens = (
        "detached worktree",
        "benchmarks.logic_pipeline.capabilities",
        "objective_daemon",
        "benchmarks/logic_pipeline/runner.py",
        "--gate pilot-shortlist",
        "--gate holdout",
        "--validate-final-decision",
        "--validate-runbook",
        "independent native kernel",
        "cold",
        "warm",
        "fresh worktree",
        "production promotion",
        "active checkout",
        "data/agent_supervisor/discovery",
        "docs/implementation/plans/"
        "hammer_symai_spacy_leanstral_benchmark_objectives.md",
    )
    lowered = text.lower()
    missing_tokens = [token for token in required_tokens if token.lower() not in lowered]
    if missing_tokens:
        raise RunbookValidationError(
            f"runbook is missing required operating evidence: {missing_tokens}"
        )
    for component in ("spaCy", "SyMAI", "Hammer", "Leanstral"):
        if component not in text:
            raise RunbookValidationError(
                f"runbook delegation matrix does not mention {component}"
            )
    if re.search(
        r"production promotion (?:is |is automatically )?authorized",
        lowered,
    ):
        raise RunbookValidationError(
            "runbook must not authorize production promotion"
        )

    try:
        decision = load_final_decision(
            metadata["Decision artifact"], repository_root=repository_root
        )
    except FinalDecisionValidationError as exc:
        raise RunbookValidationError(
            f"runbook decision binding is invalid: {exc}"
        ) from exc
    results = _decision_mapping(decision["results"], "results")
    return {
        "section": "runbook",
        "status": "valid",
        "path": DEFAULT_BENCHMARK_RUNBOOK_PATH.as_posix(),
        "evidence_symbol": "HSSLEV1006B8A",
        "decision_artifact_sha256": results["artifact_sha256"],
        "heading_count": len(headings),
        "production_promotion_authorized": False,
    }


def load_runbook(
    path: str | Path = DEFAULT_BENCHMARK_RUNBOOK_PATH,
    *,
    repository_root: str | Path = ".",
) -> dict[str, object]:
    """Load and validate the worktree-safe benchmark operator runbook."""

    runbook_path = Path(path)
    if not runbook_path.is_absolute():
        runbook_path = Path(repository_root) / runbook_path
    try:
        if runbook_path.is_symlink() or not runbook_path.is_file():
            raise RunbookValidationError(
                "runbook path must be a regular non-symlink file"
            )
        if not 0 < runbook_path.stat().st_size <= 512 * 1024:
            raise RunbookValidationError(
                "runbook file size is outside the safe bound"
            )
        text = runbook_path.read_text(encoding="utf-8")
    except RunbookValidationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise RunbookValidationError(
            f"cannot read benchmark runbook: {runbook_path}"
        ) from exc
    return validate_runbook(text, repository_root=repository_root)


def _summary(report: Mapping[str, object]) -> dict[str, object]:
    analysis = _mapping(report["analysis"], "analysis")
    coverage = _mapping(analysis["coverage"], "coverage")
    metrics = _array(analysis["primary_metrics"], "primary_metrics")
    return {
        "section": "proof",
        "status": "valid",
        "execution_mode": report["execution_mode"],
        "artifact_sha256": report["artifact_sha256"],
        "observation_count": coverage["observed_observation_count"],
        "kernel_verified_count": sum(
            int(_mapping(item, "metric")["kernel_verified_count"])
            for item in metrics
        ),
        "missingness_retained": any(
            _mapping(item, "metric")["kernel_verified_rate"] is None
            for item in metrics
        ),
        "s1_included_in_primary_metrics": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate logic-pipeline benchmark reports"
    )
    parser.add_argument(
        "--section",
        choices=("frontend", "proof", "statistics", "efficiency"),
        default=None,
    )
    parser.add_argument(
        "--gate",
        choices=("pilot-shortlist", "holdout"),
        default=None,
    )
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--validate-final-decision",
        action="store_true",
        help="validate the content-addressed final architecture decision",
    )
    parser.add_argument(
        "--validate-runbook",
        action="store_true",
        help="validate the final decision's worktree-safe operator runbook",
    )
    parser.add_argument(
        "--results-path",
        type=Path,
        default=None,
        help="override the selected report, decision, or runbook path",
    )
    args = parser.parse_args(argv)
    final_modes = int(args.validate_final_decision) + int(args.validate_runbook)
    if final_modes:
        if final_modes != 1:
            parser.error(
                "--validate-final-decision and --validate-runbook are "
                "mutually exclusive"
            )
        if args.section is not None or args.gate is not None or args.validate:
            parser.error(
                "final decision validators cannot be combined with "
                "--section, --gate, or --validate"
            )
        if args.validate_final_decision:
            try:
                value = load_final_decision(
                    args.results_path or DEFAULT_FINAL_DECISION_PATH
                )
            except FinalDecisionValidationError as exc:
                parser.error(str(exc))
            summary = final_decision_summary(value)
        else:
            try:
                summary = load_runbook(
                    args.results_path or DEFAULT_BENCHMARK_RUNBOOK_PATH
                )
            except RunbookValidationError as exc:
                parser.error(str(exc))
        sys.stdout.write(canonical_json(summary) + "\n")
        return 0
    if args.gate is not None:
        if args.section is not None:
            parser.error("--gate and --section are mutually exclusive")
        if args.gate == "holdout":
            from benchmarks.logic_pipeline.holdout_gate import (
                DEFAULT_HOLDOUT_GATE_PATH,
                HoldoutGateError,
                holdout_gate_summary,
                load_holdout_gate_report,
            )

            try:
                report = load_holdout_gate_report(
                    args.results_path or DEFAULT_HOLDOUT_GATE_PATH
                )
            except HoldoutGateError as exc:
                parser.error(str(exc))
            summary = holdout_gate_summary(report)
            sys.stdout.write(canonical_json(summary) + "\n")
            return 0
        from benchmarks.logic_pipeline.pilot_gate import (
            DEFAULT_PILOT_SHORTLIST_PATH,
            PilotGateError,
            load_pilot_shortlist_report,
            pilot_shortlist_summary,
        )

        try:
            report = load_pilot_shortlist_report(
                args.results_path or DEFAULT_PILOT_SHORTLIST_PATH
            )
        except PilotGateError as exc:
            parser.error(str(exc))
        summary = pilot_shortlist_summary(report)
        sys.stdout.write(canonical_json(summary) + "\n")
        return 0
    if args.section is None:
        parser.error("one of --section or --gate is required")
    if not args.validate:
        parser.error("--section requires --validate")

    if args.section == "efficiency":
        try:
            report = (
                create_efficiency_capability_preflight_report()
                if args.results_path is None
                else load_efficiency_report(args.results_path)
            )
        except EfficiencyReportError as exc:
            parser.error(str(exc))
        summary = efficiency_summary(report)
    elif args.section == "statistics":
        from benchmarks.logic_pipeline.statistics import (
            StatisticsError,
            load_statistics_report,
            statistics_summary,
        )

        if args.results_path is None:
            parser.error("--section statistics requires --results-path")
        try:
            report = load_statistics_report(args.results_path)
        except StatisticsError as exc:
            parser.error(str(exc))
        summary = statistics_summary(report)
    elif args.section == "frontend":
        from benchmarks.logic_pipeline.frontend_report import (
            DEFAULT_FRONTEND_REPORT_PATH,
            FrontendReportError,
            frontend_summary,
            load_frontend_report,
        )

        try:
            report = load_frontend_report(
                args.results_path or DEFAULT_FRONTEND_REPORT_PATH
            )
        except FrontendReportError as exc:
            parser.error(str(exc))
        summary = frontend_summary(report)
    else:
        try:
            report = load_proof_report(
                args.results_path or DEFAULT_PROOF_REPORT_PATH
            )
        except ProofReportError as exc:
            parser.error(str(exc))
        summary = _summary(report)
    sys.stdout.write(canonical_json(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CACHE_MODES",
    "DEFAULT_BENCHMARK_RUNBOOK_PATH",
    "DEFAULT_FINAL_DECISION_PATH",
    "DEFAULT_PROOF_REPORT_PATH",
    "DIAGNOSTIC_VARIANT_IDS",
    "EFFICIENCY_REPORT_SCHEMA",
    "ELIGIBLE_CASE_IDS",
    "EXCLUDED_CASE_IDS",
    "EfficiencyReportError",
    "FINAL_DECISION_EVIDENCE",
    "FINAL_DECISION_SCHEMA",
    "FinalDecisionValidationError",
    "HSSLEV0519C80",
    "HSSLEV0526A41",
    "HSSLEV0608F63",
    "HSSLEV0615B24",
    "HSSLEV0801D68",
    "HSSLEV1006B8A",
    "PRIMARY_VARIANT_IDS",
    "PROOF_ANALYSIS_SCHEMA",
    "PROOF_OBSERVATION_SCHEMA",
    "PROOF_REPORT_SCHEMA",
    "ProofReportError",
    "RunbookValidationError",
    "build_efficiency_report",
    "build_statistics_report",
    "create_efficiency_capability_preflight_report",
    "create_capability_preflight_report",
    "derive_proof_analysis",
    "efficiency_summary",
    "final_decision_summary",
    "load_efficiency_report",
    "load_final_decision",
    "load_runbook",
    "load_statistics_report",
    "load_proof_report",
    "validate_final_decision",
    "validate_runbook",
    "validate_statistics_report",
    "validate_efficiency_report",
    "validate_proof_report",
]


def load_robustness_report(source: str | Path) -> RobustnessReport:
    """Load only strict, canonical, newline-terminated report evidence."""

    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RobustnessValidationError(
            f"cannot read robustness report: {path}"
        ) from exc
    if not text.endswith("\n"):
        raise RobustnessValidationError(
            "robustness report is not canonical newline JSON"
        )
    try:
        payload = json.loads(
            text, object_pairs_hook=_robust_reject_duplicate_pairs
        )
    except (json.JSONDecodeError, RobustnessValidationError) as exc:
        raise RobustnessValidationError(
            "robustness report is not strict JSON"
        ) from exc
    loaded = RobustnessReport.from_dict(payload)
    if canonical_robustness_report_json(loaded) + "\n" != text:
        raise RobustnessValidationError("robustness report is not canonical JSON")
    return loaded


__all__ += [
    "BOUNDED_PROCESS_SCHEMA",
    "FAILURE_ISOLATION_SCHEMA",
    "REPLAY_VALIDATION_SCHEMA",
    "ROBUSTNESS_REPORT_SCHEMA",
    "BoundedProcessResult",
    "FailureInjectionKind",
    "FailureIsolationRecord",
    "HSSLEV0702E85",
    "ReplayStatus",
    "ReplayValidationRecord",
    "RobustnessReport",
    "RobustnessValidationError",
    "canonical_robustness_report_json",
    "load_robustness_report",
    "run_bounded_process",
    "validate_replay",
    "write_robustness_report",
]
