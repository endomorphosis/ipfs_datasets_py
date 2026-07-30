"""Differential Z3/CVC5 verification for shared software-verification VCs.

``SmtDifferentialVerification@1`` runs identical canonical obligations through
Z3 and CVC5 after the shared semantic SMT compiler, normalizes models and
unsat cores into typed results, binds translation receipts and resource
observations, and preserves disagreement evidence fail-closed.

Both solvers must see the same SMT-LIB script.  Availability is never inferred
from success heuristics: a missing executable yields an explicit
``unavailable`` status.  Ambiguous or multi-verdict solver output is rejected
as ``malformed``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
    TypedBackendResult,
)
from ipfs_datasets_py.logic.backends.smt.compiler import (
    SMT_COMPILER_ID,
    SMT_COMPILER_VERSION,
    SmtCompilation,
    SmtObligation,
    SmtQueryMode,
    SoftwareVerificationSMTCompiler,
    compile_obligation,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    ExecutionBounds,
    ResourceUsage,
)
from ipfs_datasets_py.logic.software_verification.receipts import (
    LogicTranslationReceipt,
)

SMT_DIFFERENTIAL_INTERFACE: Final = "SmtDifferentialVerification@1"
SMT_DIFFERENTIAL_SCHEMA_VERSION: Final = "smt-differential-verification/v1"
SMT_SOFTWARE_VERIFICATION_OUTCOME_VERSION: Final = (
    "smt-software-verification-outcome/v1"
)
SOFTWARE_VERIFICATION_SMT_BACKEND_VERSION: Final = (
    "software-verification-smt-backend/v1"
)

Z3_SV_BACKEND_ID: Final = "z3"
Z3_SV_BACKEND_INTERFACE: Final = "Z3SoftwareVerificationBackend@1"
Z3_SV_BACKEND_VERSION: Final = "z3-software-verification/v1"

CVC5_SV_BACKEND_ID: Final = "cvc5"
CVC5_SV_BACKEND_INTERFACE: Final = "CVC5SoftwareVerificationBackend@1"
CVC5_SV_BACKEND_VERSION: Final = "cvc5-software-verification/v1"

_VERDICT_TOKENS: Final = frozenset({"sat", "unsat", "unknown"})
_SOLVER_RESULT_LINE = re.compile(r"^(sat|unsat|unknown)\s*$", re.IGNORECASE)
_UNSAT_CORE_ATOM = re.compile(r"[A-Za-z_][A-Za-z0-9._:/-]*")


class SmtDifferentialError(ValueError):
    """Raised when differential verification cannot proceed without loss."""


class MalformedSmtSolverOutput(SmtDifferentialError):
    """Raised when solver stdout has no unambiguous sat/unsat/unknown verdict."""


class SmtSolverVerdict(StrEnum):
    """Closed solver-level classifications after fail-closed parsing."""

    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


class DifferentialClassification(StrEnum):
    """How Z3 and CVC5 relate on one obligation."""

    AGREE_PROVED = "agree_proved"
    AGREE_DISPROVED = "agree_disproved"
    AGREE_SATISFIABLE = "agree_satisfiable"
    AGREE_UNSATISFIABLE = "agree_unsatisfiable"
    AGREE_UNKNOWN = "agree_unknown"
    DISAGREE = "disagree"
    PARTIAL_UNAVAILABLE = "partial_unavailable"
    BOTH_UNAVAILABLE = "both_unavailable"
    MALFORMED = "malformed"
    ERROR = "error"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise SmtDifferentialError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SmtDifferentialError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_diagnostic(message: object) -> str:
    normalized = " ".join(str(message).split())
    return (normalized or "smt backend diagnostic")[:512]


@dataclass(frozen=True, slots=True)
class SmtRawSolverOutput:
    """Inert process observation from one SMT solver invocation."""

    stdout: str = ""
    stderr: str = ""
    returncode: int | None = 0
    elapsed_ms: int = 0
    solver_version: str = ""
    timed_out: bool = False
    unavailable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise MalformedSmtSolverOutput("stdout and stderr must be strings")
        if self.returncode is not None and (
            isinstance(self.returncode, bool)
            or not isinstance(self.returncode, int)
        ):
            raise MalformedSmtSolverOutput(
                "returncode must be an integer or None"
            )
        object.__setattr__(
            self, "elapsed_ms", _non_negative_int(self.elapsed_ms, "elapsed_ms")
        )
        if not isinstance(self.solver_version, str):
            raise MalformedSmtSolverOutput("solver_version must be a string")
        if not isinstance(self.timed_out, bool) or not isinstance(
            self.unavailable, bool
        ):
            raise MalformedSmtSolverOutput(
                "timed_out and unavailable must be booleans"
            )


SmtSolverRunner = Callable[
    [str, ExecutionBounds],
    SmtRawSolverOutput,
]
AvailabilityProbe = Callable[[], bool]
VersionProbe = Callable[[], str]


_SET_INFO_BARE = re.compile(
    r"^\(\s*set-info\s+(:[A-Za-z0-9_-]+)\s+([^\"\s)][^)]*)\s*\)\s*$",
    re.IGNORECASE,
)
_SOLVER_SOFT_ERROR = re.compile(r"^\(\s*error\b", re.IGNORECASE)


def normalize_smtlib_for_solver(source: str) -> str:
    """Quote bare ``set-info`` values so identifiers with ``:`` remain valid.

    The shared semantic compiler may emit
    ``(set-info :obligation obl:vc-x-positive)``.  SMT-LIB parsers treat the
    second colon as a keyword, which Z3/CVC5 reject.  Quoting the value is a
    pure syntactic normalization and does not change the obligation identity
    bound on the compilation receipt.
    """

    if not isinstance(source, str) or not source.strip():
        raise SmtDifferentialError("SMT-LIB source must be a non-empty string")
    if "\x00" in source:
        raise SmtDifferentialError("SMT-LIB source must not contain NUL bytes")

    lines: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        match = _SET_INFO_BARE.match(stripped)
        if match is None:
            lines.append(line)
            continue
        key, value = match.group(1), match.group(2).strip()
        if value.startswith('"') and value.endswith('"'):
            lines.append(line)
            continue
        # Quote only values that would otherwise parse as multi-token / keywords
        # (notably identifiers containing ':'). Leave simple tokens like 2.6 alone.
        needs_quote = (
            ":" in value
            or " " in value
            or any(ch in value for ch in "()[]{}")
        )
        if not needs_quote:
            lines.append(line)
            continue
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'(set-info {key} "{escaped}")')
    normalized = "\n".join(lines)
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def parse_smt_solver_stdout(
    stdout: str,
    *,
    expect_model: bool = False,
    expect_unsat_core: bool = False,
) -> tuple[str, tuple[str, ...], str]:
    """Parse exactly one SMT verdict plus optional model / unsat-core text.

    Returns ``(verdict, unsat_core_names, model_text)``.
    Raises :class:`MalformedSmtSolverOutput` when the stream is ambiguous.

    Soft ``(error ...)`` diagnostics emitted *before* a single conclusive
    sat/unsat/unknown token are ignored only when a unique verdict remains;
    multiple verdicts or non-error noise before a verdict stay fail-closed.
    """

    if not isinstance(stdout, str):
        raise MalformedSmtSolverOutput("stdout must be a string")
    if "\x00" in stdout:
        raise MalformedSmtSolverOutput("stdout must not contain NUL bytes")

    lines = stdout.splitlines()
    verdict_index: int | None = None
    verdict: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.lower() == "success":
            continue
        if _SOLVER_SOFT_ERROR.match(stripped) and verdict is None:
            # Soft CLI diagnostics (e.g. unknown option) before a verdict.
            continue
        match = _SOLVER_RESULT_LINE.match(stripped)
        if match is None:
            # Non-result content before the first verdict is malformed.
            if verdict is None:
                raise MalformedSmtSolverOutput(
                    "solver output contains non-result text before its result"
                )
            continue
        token = match.group(1).lower()
        if verdict is None:
            verdict = token
            verdict_index = index
        else:
            raise MalformedSmtSolverOutput(
                "solver output must contain exactly one sat, unsat, or unknown result"
            )

    if verdict is None or verdict_index is None:
        raise MalformedSmtSolverOutput(
            "solver output must contain exactly one sat, unsat, or unknown result"
        )

    tail = "\n".join(lines[verdict_index + 1 :]).strip()
    unsat_core: tuple[str, ...] = ()
    model_text = ""

    if verdict == "unsat" and expect_unsat_core and tail:
        # Accept both single-line and multi-line S-expression cores.
        atoms = _UNSAT_CORE_ATOM.findall(tail)
        # Drop the outer "get-unsat-core" echoes if present; keep named asserts.
        filtered = [
            atom
            for atom in atoms
            if atom.lower()
            not in {
                "get-unsat-core",
                "unsat",
                "sat",
                "unknown",
                "error",
                "model",
            }
        ]
        # Preserve order, drop duplicates.
        seen: set[str] = set()
        ordered: list[str] = []
        for atom in filtered:
            if atom not in seen:
                seen.add(atom)
                ordered.append(atom)
        unsat_core = tuple(ordered)
    elif verdict == "sat" and expect_model and tail:
        model_text = tail
    elif tail and not expect_model and not expect_unsat_core:
        # Extra trailing content without a requested artifact is tolerated only
        # when it is blank or pure comments (already stripped).
        non_comment = [
            line
            for line in tail.splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        if non_comment and verdict == "unknown":
            # Some solvers print reason-unknown after the verdict.
            pass
        elif non_comment and verdict in {"sat", "unsat"}:
            # Keep trailing text as model/core-less payload for diagnostics only.
            pass

    return verdict, unsat_core, model_text


def _status_for_verdict(
    query_mode: SmtQueryMode,
    verdict: SmtSolverVerdict,
) -> ResultStatus:
    if verdict is SmtSolverVerdict.TIMEOUT:
        return ResultStatus.TIMEOUT
    if verdict is SmtSolverVerdict.UNAVAILABLE:
        return ResultStatus.UNAVAILABLE
    if verdict is SmtSolverVerdict.MALFORMED:
        return ResultStatus.MALFORMED
    if verdict is SmtSolverVerdict.ERROR:
        return ResultStatus.ERROR
    if verdict is SmtSolverVerdict.UNSUPPORTED:
        return ResultStatus.UNSUPPORTED
    if verdict is SmtSolverVerdict.UNKNOWN:
        return ResultStatus.UNKNOWN

    if query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
        if verdict is SmtSolverVerdict.UNSAT:
            return ResultStatus.PROVED
        if verdict is SmtSolverVerdict.SAT:
            return ResultStatus.DISPROVED
        return ResultStatus.UNKNOWN

    # Satisfiability and fixed-point queries share SAT/UNSAT semantics.
    if verdict is SmtSolverVerdict.SAT:
        return ResultStatus.SATISFIABLE
    if verdict is SmtSolverVerdict.UNSAT:
        return ResultStatus.UNSATISFIABLE
    return ResultStatus.UNKNOWN


def _authority_for_query_mode(query_mode: SmtQueryMode) -> ResultAuthority:
    if query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
        return ResultAuthority.THEOREM
    return ResultAuthority.SATISFIABILITY


def _result_class_for(
    query_mode: SmtQueryMode,
) -> type[TypedBackendResult]:
    if query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
        return TheoremResult
    return SatisfiabilityResult


@dataclass(frozen=True, slots=True)
class SoftwareVerificationSmtOutcome:
    """Typed, receipt-bound outcome of one software-verification SMT run."""

    backend_id: str
    backend_version: str
    backend_interface: str
    obligation_id: str
    query_mode: SmtQueryMode
    verdict: SmtSolverVerdict
    result: TypedBackendResult
    compilation: SmtCompilation | None = None
    solver_version: str = ""
    unsat_core: tuple[str, ...] = ()
    model_text: str = ""
    raw_stdout: str = ""
    raw_stderr: str = ""
    schema_version: str = SMT_SOFTWARE_VERIFICATION_OUTCOME_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        object.__setattr__(
            self,
            "backend_interface",
            _text(self.backend_interface, "backend_interface"),
        )
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "query_mode", _enum_query_mode(self.query_mode)
        )
        object.__setattr__(
            self, "verdict", _enum_verdict(self.verdict)
        )
        if not isinstance(self.result, TypedBackendResult):
            raise SmtDifferentialError("result must be a TypedBackendResult")
        if self.compilation is not None and not isinstance(
            self.compilation, SmtCompilation
        ):
            raise SmtDifferentialError("compilation must be SmtCompilation or None")
        if not isinstance(self.solver_version, str):
            raise SmtDifferentialError("solver_version must be a string")
        object.__setattr__(
            self,
            "unsat_core",
            tuple(_text(item, "unsat_core item") for item in self.unsat_core),
        )
        if not isinstance(self.model_text, str) or "\x00" in self.model_text:
            raise SmtDifferentialError(
                "model_text must be a string without NUL bytes"
            )
        if not isinstance(self.raw_stdout, str) or not isinstance(
            self.raw_stderr, str
        ):
            raise SmtDifferentialError("raw_stdout/raw_stderr must be strings")
        if self.schema_version != SMT_SOFTWARE_VERIFICATION_OUTCOME_VERSION:
            raise SmtDifferentialError(
                f"unsupported outcome schema_version {self.schema_version!r}"
            )

    @property
    def is_conclusive(self) -> bool:
        return self.verdict in {
            SmtSolverVerdict.SAT,
            SmtSolverVerdict.UNSAT,
        }

    @property
    def translation_receipt(self) -> LogicTranslationReceipt | None:
        if self.compilation is None:
            return None
        return self.compilation.receipt

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backend_id": self.backend_id,
            "backend_interface": self.backend_interface,
            "backend_version": self.backend_version,
            "is_conclusive": self.is_conclusive,
            "model_text": self.model_text,
            "obligation_id": self.obligation_id,
            "query_mode": self.query_mode.value,
            "result": self.result.to_dict(),
            "schema_version": self.schema_version,
            "solver_version": self.solver_version,
            "unsat_core": list(self.unsat_core),
            "verdict": self.verdict.value,
        }
        if self.compilation is not None:
            payload["compilation_id"] = self.compilation.compilation_id
            payload["script_digest"] = self.compilation.script.digest
            payload["translation_receipt_id"] = self.compilation.receipt.receipt_id
            payload["translation_authority_ceiling"] = (
                self.compilation.receipt.authority_ceiling.value
            )
        return payload


def _enum_query_mode(value: object) -> SmtQueryMode:
    try:
        return value if isinstance(value, SmtQueryMode) else SmtQueryMode(value)
    except (TypeError, ValueError) as error:
        raise SmtDifferentialError(
            f"query_mode must be a SmtQueryMode, got {value!r}"
        ) from error


def _enum_verdict(value: object) -> SmtSolverVerdict:
    try:
        return (
            value if isinstance(value, SmtSolverVerdict) else SmtSolverVerdict(value)
        )
    except (TypeError, ValueError) as error:
        raise SmtDifferentialError(
            f"verdict must be a SmtSolverVerdict, got {value!r}"
        ) from error


def _build_typed_result(
    *,
    backend_id: str,
    backend_version: str,
    query_mode: SmtQueryMode,
    verdict: SmtSolverVerdict,
    bounds: ExecutionBounds,
    usage: ResourceUsage,
    compilation: SmtCompilation | None,
    unsat_core: Sequence[str],
    model_text: str,
    solver_version: str,
    diagnostics: Sequence[str],
    reason: str,
    obligation_id: str,
) -> TypedBackendResult:
    status = _status_for_verdict(query_mode, verdict)
    authority = _authority_for_query_mode(query_mode)
    result_cls = _result_class_for(query_mode)

    witness: dict[str, Any] = {
        "solver_verdict": verdict.value,
        "obligation_id": obligation_id,
        "query_mode": query_mode.value,
    }
    if solver_version:
        witness["solver_version"] = solver_version
    if unsat_core:
        witness["unsat_core"] = list(unsat_core)
    if model_text:
        # Bound model text in the witness by output budget later if needed.
        witness["model"] = model_text[: bounds.max_output_bytes]
        witness["model_digest"] = stable_digest({"model": model_text})

    metadata: dict[str, Any] = {
        "adapter_version": SOFTWARE_VERIFICATION_SMT_BACKEND_VERSION,
        "backend_interface": (
            Z3_SV_BACKEND_INTERFACE
            if backend_id == Z3_SV_BACKEND_ID
            else CVC5_SV_BACKEND_INTERFACE
            if backend_id == CVC5_SV_BACKEND_ID
            else SOFTWARE_VERIFICATION_SMT_BACKEND_VERSION
        ),
        "semantic_compiler_id": SMT_COMPILER_ID,
        "semantic_compiler_version": SMT_COMPILER_VERSION,
    }
    translation_ceiling = EvidenceAuthority.NONE
    assumptions: tuple[str, ...] = ()
    if compilation is not None:
        receipt = compilation.receipt
        metadata["compilation_id"] = compilation.compilation_id
        metadata["script_digest"] = compilation.script.digest
        metadata["source_identity"] = compilation.source_identity
        metadata["target_identity"] = compilation.target_identity
        metadata["translation_receipt_id"] = receipt.receipt_id
        metadata["smt_logic"] = compilation.script.logic
        metadata["request_model"] = compilation.script.request_model
        metadata["request_unsat_core"] = compilation.script.request_unsat_core
        translation_ceiling = receipt.authority_ceiling
        assumptions = receipt.assumptions
        witness["translation_receipt"] = {
            "receipt_id": receipt.receipt_id,
            "source_identity": receipt.source_identity,
            "target_identity": receipt.target_identity,
            "authority_ceiling": receipt.authority_ceiling.value,
            "preservation_kind": receipt.preservation_claim.kind.value,
            "compilers": [item.to_dict() for item in receipt.compilers],
        }

    result_id = (
        f"result:{backend_id}:{stable_digest({'obligation': obligation_id, 'verdict': verdict.value})[:24]}"
    )
    return result_cls(
        result_id=result_id,
        backend_id=backend_id,
        backend_version=backend_version,
        authority=authority,
        status=status,
        assumptions=assumptions,
        bounds=bounds,
        translation_ceiling=translation_ceiling,
        usage=usage,
        witness=FrozenMap(witness),
        diagnostics=tuple(
            dict.fromkeys(_bounded_diagnostic(item) for item in diagnostics if item)
        ),
        reason=reason,
        metadata=FrozenMap(metadata),
    )


class SoftwareVerificationSmtBackend:
    """Semantic-compiler-backed SMT solver adapter for software verification.

    Construction and :meth:`is_available` are inert with respect to proving.
    Execution only happens in :meth:`run` / :meth:`run_compilation`.
    """

    INTERFACE: ClassVar[str] = SOFTWARE_VERIFICATION_SMT_BACKEND_VERSION

    def __init__(
        self,
        *,
        backend_id: str,
        backend_version: str,
        backend_interface: str,
        runner: SmtSolverRunner | None = None,
        availability_probe: AvailabilityProbe | None = None,
        version_probe: VersionProbe | None = None,
        compiler: SoftwareVerificationSMTCompiler | None = None,
        executable: str = "",
    ) -> None:
        self._backend_id = _text(backend_id, "backend_id")
        self._backend_version = _text(backend_version, "backend_version")
        self._backend_interface = _text(backend_interface, "backend_interface")
        self._compiler = compiler or SoftwareVerificationSMTCompiler()
        self._executable = executable.strip() if isinstance(executable, str) else ""
        if runner is not None and not callable(runner):
            raise TypeError("runner must be callable")
        if availability_probe is not None and not callable(availability_probe):
            raise TypeError("availability_probe must be callable")
        if version_probe is not None and not callable(version_probe):
            raise TypeError("version_probe must be callable")
        self._runner = runner
        self._availability_probe = availability_probe
        self._version_probe = version_probe

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def backend_version(self) -> str:
        return self._backend_version

    @property
    def backend_interface(self) -> str:
        return self._backend_interface

    @property
    def compiler(self) -> SoftwareVerificationSMTCompiler:
        return self._compiler

    def is_available(self) -> bool:
        if self._availability_probe is not None:
            try:
                return self._availability_probe() is True
            except Exception:
                return False
        if self._runner is not None:
            # Injected runners are treated as available unless a probe says otherwise.
            return True
        if self._executable:
            return shutil.which(self._executable) is not None
        return False

    def solver_version(self) -> str:
        if self._version_probe is not None:
            try:
                value = self._version_probe()
                return value if isinstance(value, str) else ""
            except Exception:
                return ""
        if not self._executable:
            return ""
        resolved = shutil.which(self._executable)
        if not resolved:
            return ""
        try:
            completed = subprocess.run(
                [resolved, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        output = (completed.stdout or completed.stderr or "").strip().splitlines()
        return output[0] if output else ""

    def compile(
        self, obligation: SmtObligation | Mapping[str, Any] | SmtCompilation
    ) -> SmtCompilation:
        if isinstance(obligation, SmtCompilation):
            return obligation
        return self._compiler.compile(obligation)

    def run(
        self,
        obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
        *,
        bounds: ExecutionBounds | None = None,
    ) -> SoftwareVerificationSmtOutcome:
        compilation = self.compile(obligation)
        return self.run_compilation(
            compilation,
            bounds=bounds or ExecutionBounds(timeout_ms=5_000, max_steps=100_000),
        )

    def run_compilation(
        self,
        compilation: SmtCompilation,
        *,
        bounds: ExecutionBounds,
    ) -> SoftwareVerificationSmtOutcome:
        if not isinstance(compilation, SmtCompilation):
            raise TypeError("compilation must be an SmtCompilation")
        if not isinstance(bounds, ExecutionBounds):
            raise TypeError("bounds must be an ExecutionBounds")

        obligation_id = compilation.obligation_id
        query_mode = compilation.query_mode

        if not self.is_available():
            usage = ResourceUsage()
            verdict = SmtSolverVerdict.UNAVAILABLE
            reason = f"{self.backend_id} executable is not available"
            result = _build_typed_result(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                query_mode=query_mode,
                verdict=verdict,
                bounds=bounds,
                usage=usage,
                compilation=compilation,
                unsat_core=(),
                model_text="",
                solver_version="",
                diagnostics=(reason,),
                reason=reason,
                obligation_id=obligation_id,
            )
            return SoftwareVerificationSmtOutcome(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_interface=self.backend_interface,
                obligation_id=obligation_id,
                query_mode=query_mode,
                verdict=verdict,
                result=result,
                compilation=compilation,
            )

        smtlib = normalize_smtlib_for_solver(compilation.smtlib)
        raw = self._invoke(smtlib, bounds)
        return self._outcome_from_raw(
            compilation=compilation,
            bounds=bounds,
            raw=raw,
        )

    def _default_runner(
        self, smtlib: str, bounds: ExecutionBounds
    ) -> SmtRawSolverOutput:
        raise SmtDifferentialError(
            f"{self.backend_id} has no default runner; inject a runner or subclass"
        )

    def _invoke(
        self, smtlib: str, bounds: ExecutionBounds
    ) -> SmtRawSolverOutput:
        runner = self._runner or self._default_runner
        try:
            raw = runner(smtlib, bounds)
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            return SmtRawSolverOutput(
                stdout="",
                stderr=str(error),
                returncode=None,
                elapsed_ms=bounds.timeout_ms,
                timed_out=True,
            )
        except FileNotFoundError as error:
            return SmtRawSolverOutput(
                stdout="",
                stderr=str(error),
                returncode=None,
                unavailable=True,
            )
        except OSError as error:
            return SmtRawSolverOutput(
                stdout="",
                stderr=str(error),
                returncode=None,
                unavailable=True,
            )
        if not isinstance(raw, SmtRawSolverOutput):
            raise MalformedSmtSolverOutput(
                "runner must return SmtRawSolverOutput"
            )
        return raw

    def _outcome_from_raw(
        self,
        *,
        compilation: SmtCompilation,
        bounds: ExecutionBounds,
        raw: SmtRawSolverOutput,
    ) -> SoftwareVerificationSmtOutcome:
        obligation_id = compilation.obligation_id
        query_mode = compilation.query_mode
        output_bytes = len(raw.stdout.encode("utf-8")) + len(
            raw.stderr.encode("utf-8")
        )
        usage = ResourceUsage(
            elapsed_ms=min(raw.elapsed_ms, bounds.timeout_ms),
            steps=0,
            peak_memory_bytes=0,
            output_bytes=min(output_bytes, bounds.max_output_bytes),
        )
        solver_version = raw.solver_version or self.solver_version()

        if raw.unavailable:
            verdict = SmtSolverVerdict.UNAVAILABLE
            reason = raw.stderr or f"{self.backend_id} is unavailable"
            result = _build_typed_result(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                query_mode=query_mode,
                verdict=verdict,
                bounds=bounds,
                usage=usage,
                compilation=compilation,
                unsat_core=(),
                model_text="",
                solver_version=solver_version,
                diagnostics=(reason,),
                reason=reason,
                obligation_id=obligation_id,
            )
            return SoftwareVerificationSmtOutcome(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_interface=self.backend_interface,
                obligation_id=obligation_id,
                query_mode=query_mode,
                verdict=verdict,
                result=result,
                compilation=compilation,
                solver_version=solver_version,
                raw_stdout=raw.stdout,
                raw_stderr=raw.stderr,
            )

        if raw.timed_out:
            verdict = SmtSolverVerdict.TIMEOUT
            reason = (
                raw.stderr
                or f"{self.backend_id} exceeded {bounds.timeout_ms} ms"
            )
            result = _build_typed_result(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                query_mode=query_mode,
                verdict=verdict,
                bounds=bounds,
                usage=ResourceUsage(
                    elapsed_ms=bounds.timeout_ms,
                    output_bytes=usage.output_bytes,
                ),
                compilation=compilation,
                unsat_core=(),
                model_text="",
                solver_version=solver_version,
                diagnostics=(reason,),
                reason=reason,
                obligation_id=obligation_id,
            )
            return SoftwareVerificationSmtOutcome(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_interface=self.backend_interface,
                obligation_id=obligation_id,
                query_mode=query_mode,
                verdict=verdict,
                result=result,
                compilation=compilation,
                solver_version=solver_version,
                raw_stdout=raw.stdout,
                raw_stderr=raw.stderr,
            )

        if raw.returncode not in (0, None) and not raw.stdout.strip():
            # Non-zero with empty stdout is a hard solver error.
            verdict = SmtSolverVerdict.ERROR
            reason = raw.stderr or (
                f"{self.backend_id} exited with return code {raw.returncode}"
            )
            result = _build_typed_result(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                query_mode=query_mode,
                verdict=verdict,
                bounds=bounds,
                usage=usage,
                compilation=compilation,
                unsat_core=(),
                model_text="",
                solver_version=solver_version,
                diagnostics=(reason,),
                reason=reason,
                obligation_id=obligation_id,
            )
            return SoftwareVerificationSmtOutcome(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_interface=self.backend_interface,
                obligation_id=obligation_id,
                query_mode=query_mode,
                verdict=verdict,
                result=result,
                compilation=compilation,
                solver_version=solver_version,
                raw_stdout=raw.stdout,
                raw_stderr=raw.stderr,
            )

        try:
            token, unsat_core, model_text = parse_smt_solver_stdout(
                raw.stdout,
                expect_model=compilation.script.request_model,
                expect_unsat_core=compilation.script.request_unsat_core,
            )
            verdict = SmtSolverVerdict(token)
        except MalformedSmtSolverOutput as error:
            verdict = SmtSolverVerdict.MALFORMED
            reason = str(error)
            result = _build_typed_result(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                query_mode=query_mode,
                verdict=verdict,
                bounds=bounds,
                usage=usage,
                compilation=compilation,
                unsat_core=(),
                model_text="",
                solver_version=solver_version,
                diagnostics=(reason, _bounded_diagnostic(raw.stdout[:256])),
                reason=reason,
                obligation_id=obligation_id,
            )
            return SoftwareVerificationSmtOutcome(
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_interface=self.backend_interface,
                obligation_id=obligation_id,
                query_mode=query_mode,
                verdict=verdict,
                result=result,
                compilation=compilation,
                solver_version=solver_version,
                raw_stdout=raw.stdout,
                raw_stderr=raw.stderr,
            )

        reason = f"{self.backend_id} returned {verdict.value}"
        result = _build_typed_result(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            query_mode=query_mode,
            verdict=verdict,
            bounds=bounds,
            usage=usage,
            compilation=compilation,
            unsat_core=unsat_core,
            model_text=model_text,
            solver_version=solver_version,
            diagnostics=(),
            reason=reason,
            obligation_id=obligation_id,
        )
        return SoftwareVerificationSmtOutcome(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_interface=self.backend_interface,
            obligation_id=obligation_id,
            query_mode=query_mode,
            verdict=verdict,
            result=result,
            compilation=compilation,
            solver_version=solver_version,
            unsat_core=unsat_core,
            model_text=model_text,
            raw_stdout=raw.stdout,
            raw_stderr=raw.stderr,
        )


def classify_differential(
    left: SoftwareVerificationSmtOutcome,
    right: SoftwareVerificationSmtOutcome,
) -> tuple[DifferentialClassification, str]:
    """Classify a Z3/CVC5 pair fail-closed."""

    if left.obligation_id != right.obligation_id:
        raise SmtDifferentialError(
            "differential outcomes must share the same obligation_id"
        )
    if left.query_mode is not right.query_mode:
        raise SmtDifferentialError(
            "differential outcomes must share the same query_mode"
        )

    left_v = left.verdict
    right_v = right.verdict

    if left_v is SmtSolverVerdict.MALFORMED or right_v is SmtSolverVerdict.MALFORMED:
        return (
            DifferentialClassification.MALFORMED,
            "at least one solver produced malformed output",
        )
    if left_v is SmtSolverVerdict.ERROR or right_v is SmtSolverVerdict.ERROR:
        return (
            DifferentialClassification.ERROR,
            "at least one solver returned an error",
        )

    unavailable = {
        SmtSolverVerdict.UNAVAILABLE,
    }
    if left_v in unavailable and right_v in unavailable:
        return (
            DifferentialClassification.BOTH_UNAVAILABLE,
            "both solvers are unavailable",
        )
    if left_v in unavailable or right_v in unavailable:
        return (
            DifferentialClassification.PARTIAL_UNAVAILABLE,
            "exactly one solver is unavailable",
        )

    conclusive = {SmtSolverVerdict.SAT, SmtSolverVerdict.UNSAT}
    if left_v in conclusive and right_v in conclusive and left_v is not right_v:
        return (
            DifferentialClassification.DISAGREE,
            f"solvers disagree: {left.backend_id}={left_v.value}, "
            f"{right.backend_id}={right_v.value}",
        )

    if left_v is right_v is SmtSolverVerdict.UNSAT:
        if left.query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
            return (
                DifferentialClassification.AGREE_PROVED,
                "both solvers returned unsat for theorem-by-negation",
            )
        return (
            DifferentialClassification.AGREE_UNSATISFIABLE,
            "both solvers returned unsat",
        )
    if left_v is right_v is SmtSolverVerdict.SAT:
        if left.query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
            return (
                DifferentialClassification.AGREE_DISPROVED,
                "both solvers returned sat (counterexample) for theorem-by-negation",
            )
        return (
            DifferentialClassification.AGREE_SATISFIABLE,
            "both solvers returned sat",
        )
    if left_v is right_v:
        return (
            DifferentialClassification.AGREE_UNKNOWN,
            f"both solvers returned {left_v.value}",
        )

    # One conclusive, one unknown/timeout — treat as non-agreement unknown.
    return (
        DifferentialClassification.AGREE_UNKNOWN,
        f"inconclusive pair: {left.backend_id}={left_v.value}, "
        f"{right.backend_id}={right_v.value}",
    )


@dataclass(frozen=True, slots=True)
class SmtDifferentialReport:
    """Exact differential report for one shared obligation."""

    obligation_id: str
    query_mode: SmtQueryMode
    classification: DifferentialClassification
    classification_reason: str
    left: SoftwareVerificationSmtOutcome
    right: SoftwareVerificationSmtOutcome
    compilation: SmtCompilation
    script_digest: str
    agreement: bool
    disagreement_evidence: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SMT_DIFFERENTIAL_SCHEMA_VERSION
    interface: str = SMT_DIFFERENTIAL_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(self, "query_mode", _enum_query_mode(self.query_mode))
        try:
            classification = (
                self.classification
                if isinstance(self.classification, DifferentialClassification)
                else DifferentialClassification(self.classification)
            )
        except (TypeError, ValueError) as error:
            raise SmtDifferentialError(
                f"invalid differential classification {self.classification!r}"
            ) from error
        object.__setattr__(self, "classification", classification)
        object.__setattr__(
            self,
            "classification_reason",
            _text(self.classification_reason, "classification_reason"),
        )
        if not isinstance(self.left, SoftwareVerificationSmtOutcome):
            raise SmtDifferentialError("left must be SoftwareVerificationSmtOutcome")
        if not isinstance(self.right, SoftwareVerificationSmtOutcome):
            raise SmtDifferentialError("right must be SoftwareVerificationSmtOutcome")
        if not isinstance(self.compilation, SmtCompilation):
            raise SmtDifferentialError("compilation must be SmtCompilation")
        object.__setattr__(
            self, "script_digest", _text(self.script_digest, "script_digest")
        )
        if not isinstance(self.agreement, bool):
            raise SmtDifferentialError("agreement must be a boolean")
        object.__setattr__(
            self,
            "disagreement_evidence",
            (
                self.disagreement_evidence
                if isinstance(self.disagreement_evidence, FrozenMap)
                else FrozenMap(self.disagreement_evidence)
            ),
        )
        if self.schema_version != SMT_DIFFERENTIAL_SCHEMA_VERSION:
            raise SmtDifferentialError(
                f"unsupported differential schema_version {self.schema_version!r}"
            )

    @property
    def report_id(self) -> str:
        return stable_digest(self.semantic_dict())

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "agreement": self.agreement,
            "classification": self.classification.value,
            "classification_reason": self.classification_reason,
            "disagreement_evidence": self.disagreement_evidence.to_dict(),
            "interface": self.interface,
            "left_backend_id": self.left.backend_id,
            "left_verdict": self.left.verdict.value,
            "obligation_id": self.obligation_id,
            "query_mode": self.query_mode.value,
            "right_backend_id": self.right.backend_id,
            "right_verdict": self.right.verdict.value,
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
            "compilation_id": self.compilation.compilation_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload.update(
            {
                "report_id": self.report_id,
                "left": self.left.to_dict(),
                "right": self.right.to_dict(),
                "translation_receipt_id": self.compilation.receipt.receipt_id,
                "semantic_compiler_version": SMT_COMPILER_VERSION,
            }
        )
        return payload


class SmtDifferentialVerifier:
    """Run one obligation through two software-verification SMT backends."""

    INTERFACE: ClassVar[str] = SMT_DIFFERENTIAL_INTERFACE

    def __init__(
        self,
        *,
        left: SoftwareVerificationSmtBackend,
        right: SoftwareVerificationSmtBackend,
        compiler: SoftwareVerificationSMTCompiler | None = None,
    ) -> None:
        if not isinstance(left, SoftwareVerificationSmtBackend):
            raise TypeError("left must be a SoftwareVerificationSmtBackend")
        if not isinstance(right, SoftwareVerificationSmtBackend):
            raise TypeError("right must be a SoftwareVerificationSmtBackend")
        if left.backend_id == right.backend_id:
            raise SmtDifferentialError(
                "differential backends must have distinct backend_id values"
            )
        self._left = left
        self._right = right
        self._compiler = compiler or SoftwareVerificationSMTCompiler()

    @property
    def left(self) -> SoftwareVerificationSmtBackend:
        return self._left

    @property
    def right(self) -> SoftwareVerificationSmtBackend:
        return self._right

    def verify(
        self,
        obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
        *,
        bounds: ExecutionBounds | None = None,
    ) -> SmtDifferentialReport:
        effective_bounds = bounds or ExecutionBounds(
            timeout_ms=5_000, max_steps=100_000
        )
        if isinstance(obligation, SmtCompilation):
            compilation = obligation
        else:
            compilation = self._compiler.compile(obligation)

        left_outcome = self._left.run_compilation(
            compilation, bounds=effective_bounds
        )
        right_outcome = self._right.run_compilation(
            compilation, bounds=effective_bounds
        )
        return self._report(compilation, left_outcome, right_outcome)

    def _report(
        self,
        compilation: SmtCompilation,
        left: SoftwareVerificationSmtOutcome,
        right: SoftwareVerificationSmtOutcome,
    ) -> SmtDifferentialReport:
        classification, reason = classify_differential(left, right)
        agreement = classification in {
            DifferentialClassification.AGREE_PROVED,
            DifferentialClassification.AGREE_DISPROVED,
            DifferentialClassification.AGREE_SATISFIABLE,
            DifferentialClassification.AGREE_UNSATISFIABLE,
            DifferentialClassification.AGREE_UNKNOWN,
        }
        disagreement_evidence: dict[str, Any] = {}
        if classification is DifferentialClassification.DISAGREE:
            disagreement_evidence = {
                "left": {
                    "backend_id": left.backend_id,
                    "verdict": left.verdict.value,
                    "status": left.result.status.value,
                    "solver_version": left.solver_version,
                    "stdout_digest": stable_digest({"stdout": left.raw_stdout}),
                },
                "right": {
                    "backend_id": right.backend_id,
                    "verdict": right.verdict.value,
                    "status": right.result.status.value,
                    "solver_version": right.solver_version,
                    "stdout_digest": stable_digest({"stdout": right.raw_stdout}),
                },
                "script_digest": compilation.script.digest,
                "preserved": True,
            }
        return SmtDifferentialReport(
            obligation_id=compilation.obligation_id,
            query_mode=compilation.query_mode,
            classification=classification,
            classification_reason=reason,
            left=left,
            right=right,
            compilation=compilation,
            script_digest=compilation.script.digest,
            agreement=agreement,
            disagreement_evidence=FrozenMap(disagreement_evidence),
        )


def default_z3_cvc5_verifier(
    *,
    z3_backend: SoftwareVerificationSmtBackend | None = None,
    cvc5_backend: SoftwareVerificationSmtBackend | None = None,
    compiler: SoftwareVerificationSMTCompiler | None = None,
) -> SmtDifferentialVerifier:
    """Construct a Z3/CVC5 differential verifier (lazy backend imports)."""

    if z3_backend is None:
        from ipfs_datasets_py.logic.backends.z3.compiler import (
            Z3SoftwareVerificationBackend,
        )

        z3_backend = Z3SoftwareVerificationBackend()
    if cvc5_backend is None:
        from ipfs_datasets_py.logic.backends.cvc5.compiler import (
            CVC5SoftwareVerificationBackend,
        )

        cvc5_backend = CVC5SoftwareVerificationBackend()
    return SmtDifferentialVerifier(
        left=z3_backend,
        right=cvc5_backend,
        compiler=compiler,
    )


def run_z3_cvc5_differential(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
    *,
    bounds: ExecutionBounds | None = None,
    z3_backend: SoftwareVerificationSmtBackend | None = None,
    cvc5_backend: SoftwareVerificationSmtBackend | None = None,
    compiler: SoftwareVerificationSMTCompiler | None = None,
) -> SmtDifferentialReport:
    """Compile once and differentially verify with Z3 and CVC5."""

    verifier = default_z3_cvc5_verifier(
        z3_backend=z3_backend,
        cvc5_backend=cvc5_backend,
        compiler=compiler,
    )
    return verifier.verify(obligation, bounds=bounds)


def subprocess_smt_runner(
    executable: str,
    *,
    argv_builder: Callable[[str, ExecutionBounds], list[str]],
    version_argv: Sequence[str] | None = None,
) -> SmtSolverRunner:
    """Build a CLI runner that feeds SMT-LIB on stdin."""

    exe = _text(executable, "executable")

    def run(smtlib: str, bounds: ExecutionBounds) -> SmtRawSolverOutput:
        resolved = shutil.which(exe) if "/" not in exe and "\\" not in exe else exe
        if not resolved:
            return SmtRawSolverOutput(
                stderr=f"executable not found: {exe}",
                returncode=None,
                unavailable=True,
            )
        argv = argv_builder(resolved, bounds)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                input=smtlib,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(bounds.timeout_ms / 1000.0, 0.001),
            )
        except subprocess.TimeoutExpired as error:
            return SmtRawSolverOutput(
                stdout=error.stdout or "" if isinstance(error.stdout, str) else "",
                stderr=error.stderr or "" if isinstance(error.stderr, str) else "timeout",
                returncode=None,
                elapsed_ms=bounds.timeout_ms,
                timed_out=True,
            )
        except FileNotFoundError as error:
            return SmtRawSolverOutput(
                stderr=str(error),
                returncode=None,
                unavailable=True,
            )

        version = ""
        if version_argv is not None:
            try:
                version_run = subprocess.run(
                    [resolved, *version_argv],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                lines = (
                    version_run.stdout or version_run.stderr or ""
                ).strip().splitlines()
                version = lines[0] if lines else ""
            except (OSError, subprocess.TimeoutExpired):
                version = ""

        return SmtRawSolverOutput(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            solver_version=version,
        )

    return run


__all__ = [
    "AvailabilityProbe",
    "CVC5_SV_BACKEND_ID",
    "CVC5_SV_BACKEND_INTERFACE",
    "CVC5_SV_BACKEND_VERSION",
    "DifferentialClassification",
    "MalformedSmtSolverOutput",
    "SMT_DIFFERENTIAL_INTERFACE",
    "SMT_DIFFERENTIAL_SCHEMA_VERSION",
    "SMT_SOFTWARE_VERIFICATION_OUTCOME_VERSION",
    "SOFTWARE_VERIFICATION_SMT_BACKEND_VERSION",
    "SmtDifferentialError",
    "SmtDifferentialReport",
    "SmtDifferentialVerifier",
    "SmtRawSolverOutput",
    "SmtSoftwareVerificationOutcome",
    "SmtSolverRunner",
    "SmtSolverVerdict",
    "SoftwareVerificationSmtBackend",
    "SoftwareVerificationSmtOutcome",
    "VersionProbe",
    "Z3_SV_BACKEND_ID",
    "Z3_SV_BACKEND_INTERFACE",
    "Z3_SV_BACKEND_VERSION",
    "classify_differential",
    "compile_obligation",
    "default_z3_cvc5_verifier",
    "normalize_smtlib_for_solver",
    "parse_smt_solver_stdout",
    "run_z3_cvc5_differential",
    "subprocess_smt_runner",
]

# Alias retained for discoverability with the shorter product name.
SmtSoftwareVerificationOutcome = SoftwareVerificationSmtOutcome
