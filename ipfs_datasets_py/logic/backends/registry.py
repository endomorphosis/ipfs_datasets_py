"""Side-effect-free proof-backend discovery and bounded execution.

Registration and capability filtering only inspect immutable declarations.
They never import a solver, probe the environment, install a package, start a
process, or write a file.  Availability is checked only for an explicit
``is_available`` call or immediately before ``run``.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from threading import Lock
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    BackendAttempt,
    BackendCapabilities,
    BackendRequest,
    BoundedResult,
    EvidenceGateResult,
    MonitorResult,
    PolicyDecision,
    ProofBackend,
    ProofResult,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
)


BACKEND_ADAPTER_VERSION: Final = "proof-backend-adapter/v1"
SMT_ENCODINGS: Final = frozenset(
    {"smtlib2", "smt-lib", "smt-lib2", "smt-expression/v1"}
)


class BackendRegistryError(ValueError):
    """Base error for invalid registry operations."""


class DuplicateBackendError(BackendRegistryError):
    """Raised when a backend identifier is registered more than once."""


class UnknownBackendError(BackendRegistryError):
    """Raised when a requested backend has not been registered."""


class UnsupportedBackendRequest(BackendRegistryError):
    """Raised when a request cannot be lowered without losing meaning."""


class MalformedBackendOutput(BackendRegistryError):
    """Raised when compiler or runner output violates its contract."""


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise BackendRegistryError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


@dataclass(frozen=True, slots=True)
class CompiledBackendRequest:
    """Deterministic solver input bound to one immutable backend request."""

    request_digest: str
    backend_id: str
    source: str
    source_format: str = "smtlib2"
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_digest, str)
            or len(self.request_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.request_digest
            )
        ):
            raise BackendRegistryError(
                "compiled request_digest must be a lowercase SHA-256 digest"
            )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        if not isinstance(self.source, str) or not self.source.strip():
            raise BackendRegistryError("compiled source must be a non-empty string")
        if "\x00" in self.source:
            raise BackendRegistryError("compiled source must not contain NUL bytes")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "metadata": self.metadata.to_dict(),
            "request_digest": self.request_digest,
            "source": self.source,
            "source_format": self.source_format,
        }


@dataclass(frozen=True, slots=True)
class BackendRunnerOutput:
    """Raw, inert output returned by an injected backend runner."""

    stdout: str = ""
    stderr: str = ""
    returncode: int | None = 0
    elapsed_ms: int = 0
    steps: int = 0
    peak_memory_bytes: int = 0
    solver_version: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise MalformedBackendOutput("runner stdout and stderr must be strings")
        if self.returncode is not None and (
            isinstance(self.returncode, bool) or not isinstance(self.returncode, int)
        ):
            raise MalformedBackendOutput("runner returncode must be an integer or None")
        for field_name in ("elapsed_ms", "steps", "peak_memory_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MalformedBackendOutput(
                    f"runner {field_name} must be a non-negative integer"
                )
        if not isinstance(self.solver_version, str):
            raise MalformedBackendOutput("runner solver_version must be a string")


BackendCompiler = Callable[[BackendRequest], CompiledBackendRequest]
BackendRunner = Callable[
    [CompiledBackendRequest, BackendRequest], BackendRunnerOutput
]
AvailabilityProbe = Callable[[], bool]

_RESULT_CLASSES: Final[dict[QueryKind, type[BoundedResult]]] = {
    QueryKind.THEOREM_PROOF: ProofResult,
    QueryKind.SATISFIABILITY: SatisfiabilityResult,
    QueryKind.RUNTIME_MONITOR: MonitorResult,
    QueryKind.EVIDENCE_READINESS: EvidenceGateResult,
    QueryKind.POLICY_APPROVAL: PolicyDecision,
}


def _string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise UnsupportedBackendRequest(f"{field_name} must be a sequence of strings")
    result = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in result):
        raise UnsupportedBackendRequest(
            f"{field_name} must contain non-empty strings"
        )
    return result


def _assertion(expression: str) -> str:
    stripped = expression.strip()
    return stripped if stripped.startswith("(assert ") else f"(assert {stripped})"


def compile_smtlib_request(
    request: BackendRequest,
    *,
    backend_id: str,
    compiler_version: str,
    prefix: Sequence[str] = (),
) -> CompiledBackendRequest:
    """Lower the shared neutral payload into a deterministic SMT-LIB script."""

    if not isinstance(request, BackendRequest):
        raise TypeError("request must be a BackendRequest")
    payload = request.payload.to_dict()
    encoding_value = payload.get("encoding")
    if encoding_value is not None and not isinstance(encoding_value, str):
        raise UnsupportedBackendRequest("encoding must be a string")
    encoding = (encoding_value or "").lower()
    raw_source = payload.get("smtlib", payload.get("source"))
    lines = list(prefix)

    if raw_source is not None:
        if encoding and encoding not in SMT_ENCODINGS - {"smt-expression/v1"}:
            raise UnsupportedBackendRequest(
                f"{backend_id} cannot compile encoding {encoding!r}; "
                "expected SMT-LIB2"
            )
        if not isinstance(raw_source, str) or not raw_source.strip():
            raise UnsupportedBackendRequest("SMT-LIB source must be a non-empty string")
        if "\x00" in raw_source:
            raise UnsupportedBackendRequest("SMT-LIB source contains a NUL byte")
        lines.append(raw_source.strip())
        if "(check-sat" not in raw_source.lower():
            lines.append("(check-sat)")
    else:
        if encoding and encoding not in SMT_ENCODINGS:
            raise UnsupportedBackendRequest(
                f"{backend_id} cannot compile encoding {encoding!r}"
            )
        formula = payload.get("goal", payload.get("formula"))
        if not isinstance(formula, str) or not formula.strip():
            raise UnsupportedBackendRequest(
                "request payload must provide SMT-LIB source or a goal/formula"
            )
        declarations = _string_sequence(
            payload.get("declarations"), "declarations"
        )
        assumptions = _string_sequence(payload.get("assumptions"), "assumptions")
        logic = payload.get("smt_logic", "ALL")
        if not isinstance(logic, str) or not logic.strip():
            raise UnsupportedBackendRequest("smt_logic must be a non-empty string")
        lines.extend((f"(set-logic {logic.strip()})", *declarations))
        lines.extend(_assertion(item) for item in assumptions)
        goal = formula.strip()
        if request.query_kind is QueryKind.THEOREM_PROOF:
            lines.append(f"(assert (not {goal}))")
        elif request.query_kind is QueryKind.SATISFIABILITY:
            lines.append(_assertion(goal))
        else:
            raise UnsupportedBackendRequest(
                f"{backend_id} cannot compile {request.query_kind.value} requests"
            )
        lines.append("(check-sat)")

    return CompiledBackendRequest(
        request_digest=request.digest,
        backend_id=backend_id,
        source="\n".join(lines) + "\n",
        metadata={
            "compiler": compiler_version,
            "query_kind": request.query_kind.value,
        },
    )


def _attempt_id(backend_id: str, request: BackendRequest) -> str:
    return f"attempt:{backend_id}:{request.digest[:24]}"


def _result_id(backend_id: str, request: BackendRequest) -> str:
    return f"result:{backend_id}:{request.digest[:24]}"


def _bounded_diagnostic(message: Any) -> str:
    normalized = " ".join(str(message).split())
    return (normalized or "backend execution failed")[:512]


def _output_digest(
    *,
    backend_id: str,
    request: BackendRequest,
    classification: str,
    stdout: str = "",
    stderr: str = "",
    returncode: int | None = None,
) -> str:
    return stable_digest(
        {
            "backend_id": backend_id,
            "classification": classification,
            "request_digest": request.digest,
            "returncode": returncode,
            "stderr": stderr,
            "stdout": stdout,
        }
    )


def _authority(
    backend_id: str,
    backend_version: str,
    capabilities: BackendCapabilities,
    request: BackendRequest,
) -> ResultAuthority:
    return ResultAuthority(
        kind=request.query_kind.authority_kind,
        issuer=backend_id,
        method=BACKEND_ADAPTER_VERSION,
        scope_digest=request.digest,
        configuration_digest=stable_digest(
            {
                "adapter_version": BACKEND_ADAPTER_VERSION,
                "backend_id": backend_id,
                "backend_version": backend_version,
                "capabilities": capabilities.to_dict(),
            }
        ),
    )


def _make_outcome(
    *,
    backend_id: str,
    backend_version: str,
    capabilities: BackendCapabilities,
    request: BackendRequest,
    attempt_status: AttemptStatus,
    result_status: ResultStatus,
    classification: str,
    payload: Mapping[str, Any] | None = None,
    diagnostics: Sequence[str] = (),
    usage: ResourceUsage | None = None,
    output_digest: str = "",
) -> tuple[BackendAttempt, BoundedResult]:
    """Build a fully bound attempt/result pair for every terminal path."""

    normalized_diagnostics = tuple(
        dict.fromkeys(_bounded_diagnostic(item) for item in diagnostics)
    )
    bounded_usage = usage or ResourceUsage()
    digest = output_digest or _output_digest(
        backend_id=backend_id,
        request=request,
        classification=classification,
    )
    attempt = BackendAttempt(
        attempt_id=_attempt_id(backend_id, request),
        request_digest=request.digest,
        backend_id=backend_id,
        backend_version=backend_version,
        status=attempt_status,
        bounds=request.bounds,
        usage=bounded_usage,
        output_digest=digest,
        diagnostics=normalized_diagnostics,
    )
    result_class = _RESULT_CLASSES[request.query_kind]
    result = result_class.for_attempt(
        request,
        attempt,
        result_id=_result_id(backend_id, request),
        authority=_authority(backend_id, backend_version, capabilities, request),
        status=result_status,
        payload=dict(payload or {"solver_result": classification}),
        diagnostics=normalized_diagnostics,
        output_digest=digest,
    )
    return attempt, result


def _bounded_usage(
    request: BackendRequest,
    *,
    elapsed_ms: int = 0,
    steps: int = 0,
    peak_memory_bytes: int = 0,
    output_bytes: int = 0,
) -> ResourceUsage:
    """Clamp observations only for recording a non-successful bounded result."""

    return ResourceUsage(
        elapsed_ms=min(elapsed_ms, request.bounds.timeout_ms),
        steps=min(steps, request.bounds.max_steps),
        peak_memory_bytes=min(
            peak_memory_bytes, request.bounds.max_memory_bytes
        ),
        output_bytes=min(output_bytes, request.bounds.max_output_bytes),
    )


def _classify_solver_stdout(stdout: str) -> str:
    """Parse exactly one SMT verdict token and reject ambiguous output."""

    tokens = [
        line.strip().lower()
        for line in stdout.splitlines()
        if line.strip()
        and not line.lstrip().startswith(";")
        and line.strip().lower() != "success"
    ]
    results = [token for token in tokens if token in {"sat", "unsat", "unknown"}]
    if len(results) != 1:
        raise MalformedBackendOutput(
            "solver output must contain exactly one sat, unsat, or unknown result"
        )
    if tokens.index(results[0]) != 0:
        raise MalformedBackendOutput(
            "solver output contains non-result text before its result"
        )
    return results[0]


def _operation_checkpoint(phase: str) -> float | None:
    # Execution-only imports keep declaration/catalog construction inert.
    from .smt.operation_budget import current_proof_operation

    operation = current_proof_operation()
    return operation.checkpoint(phase) if operation is not None else None


def _operation_call(phase: str, callback: Callable[..., Any], *args: Any) -> Any:
    """Cooperative boundary; caller-owned callbacks are never retried/preempted."""
    _operation_checkpoint("before " + phase)
    try:
        value = callback(*args)
    except Exception:
        _operation_checkpoint("after failed " + phase)
        raise
    _operation_checkpoint("after " + phase)
    return value


def _run_scoped_operation(
    backend: ProofBackend, request: BackendRequest, callback: Callable[[], Any],
    *, operation_timeout_ms: int | None, cancellation: Any | None,
) -> tuple[BackendAttempt, BoundedResult]:
    from .smt.operation_budget import (
        MAX_OPERATION_TIMEOUT_MS, ProofOperationInterrupted,
        proof_operation_scope, validate_operation_timeout_ms,
    )

    validate_operation_timeout_ms(operation_timeout_ms)
    timeout = min(request.bounds.timeout_ms, MAX_OPERATION_TIMEOUT_MS,
                  operation_timeout_ms if operation_timeout_ms is not None else MAX_OPERATION_TIMEOUT_MS)
    try:
        with proof_operation_scope(timeout_ms=timeout, cancellation=cancellation):
            return callback()
    except ProofOperationInterrupted as error:
        # This is outside the stopped local scope. A parent remains latched and
        # will reject its own result; no completed/late foreign evidence escapes.
        cancelled = error.kind == "cancelled"
        return _make_outcome(
            backend_id=backend.backend_id, backend_version=backend.backend_version,
            capabilities=backend.capabilities, request=request,
            attempt_status=AttemptStatus.CANCELLED if cancelled else AttemptStatus.TIMED_OUT,
            result_status=ResultStatus.UNKNOWN,
            classification="cancelled" if cancelled else "timeout",
            diagnostics=(f"{type(error).__name__}: {error}",),
            # Existing wire bounds require clamped descriptive usage. This is
            # not a complete resource measurement or a claim of exact wall time.
            usage=ResourceUsage(elapsed_ms=min(request.bounds.timeout_ms, error.elapsed_ms)),
        )


class CallableProofBackend:
    """A backend assembled from inert compiler, runner, and probe callables."""

    def __init__(
        self,
        *,
        backend_id: str,
        backend_version: str,
        capabilities: BackendCapabilities,
        compiler: BackendCompiler,
        runner: BackendRunner,
        availability_probe: AvailabilityProbe | None = None,
    ) -> None:
        self._backend_id = _text(backend_id, "backend_id")
        self._backend_version = _text(backend_version, "backend_version")
        if not isinstance(capabilities, BackendCapabilities):
            raise TypeError("capabilities must be BackendCapabilities")
        if not callable(compiler) or not callable(runner):
            raise TypeError("compiler and runner must be callable")
        if availability_probe is not None and not callable(availability_probe):
            raise TypeError("availability_probe must be callable")
        self._capabilities = capabilities
        self._compiler = compiler
        self._runner = runner
        self._availability_probe = availability_probe or (lambda: True)

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def backend_version(self) -> str:
        return self._backend_version

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    def supports(self, request: BackendRequest) -> bool:
        """Check declared capability without probing availability."""

        return (
            isinstance(request, BackendRequest)
            and (
                not request.requested_backend_id
                or request.requested_backend_id == self.backend_id
            )
            and self.capabilities.supports(
                request.logic_family, request.query_kind
            )
        )

    def is_available(self) -> bool:
        """Run the configured read-only availability probe."""

        try:
            return _operation_call("availability probe", self._availability_probe) is True
        except Exception:
            return False

    def _terminal(
        self,
        request: BackendRequest,
        *,
        attempt_status: AttemptStatus,
        result_status: ResultStatus,
        classification: str,
        diagnostics: Sequence[str],
        usage: ResourceUsage | None = None,
        output_digest: str = "",
    ) -> tuple[BackendAttempt, BoundedResult]:
        return _make_outcome(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            capabilities=self.capabilities,
            request=request,
            attempt_status=attempt_status,
            result_status=result_status,
            classification=classification,
            diagnostics=diagnostics,
            usage=usage,
            output_digest=output_digest,
        )

    def run(
        self, request: BackendRequest, *, operation_timeout_ms: int | None = None,
        cancellation: Any | None = None,
    ) -> tuple[BackendAttempt, BoundedResult]:
        """Run within one inherited, tightening wall/cancellation scope.

        Python callbacks are cooperative. Native transports that already honor
        the ambient proof operation also consume setup/admission time.
        """
        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        return _run_scoped_operation(self, request, lambda: self._run_request(request),
            operation_timeout_ms=operation_timeout_ms, cancellation=cancellation)

    def _run_request(self, request: BackendRequest) -> tuple[BackendAttempt, BoundedResult]:
        if not _operation_call("backend capability check", self.supports, request):
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="unsupported",
                diagnostics=(
                    f"{self.backend_id} does not support "
                    f"{request.logic_family}/{request.query_kind.value}",
                ),
            )
        if not _operation_call("backend availability", self.is_available):
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(f"{self.backend_id} is not available",),
            )

        started = time.monotonic()
        try:
            compiled = _operation_call("backend compilation", self._compiler, request)
            if not isinstance(compiled, CompiledBackendRequest):
                raise MalformedBackendOutput(
                    "compiler did not return CompiledBackendRequest"
                )
            if compiled.request_digest != request.digest:
                raise MalformedBackendOutput(
                    "compiled request is not bound to the input request"
                )
            if compiled.backend_id != self.backend_id:
                raise MalformedBackendOutput(
                    "compiled request is bound to a different backend"
                )
            raw = _operation_call("backend execution", self._runner, compiled, request)
            if not isinstance(raw, BackendRunnerOutput):
                raise MalformedBackendOutput(
                    "runner did not return BackendRunnerOutput"
                )
        except UnsupportedBackendRequest as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="unsupported",
                diagnostics=(str(error),),
            )
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.TIMED_OUT,
                result_status=ResultStatus.UNKNOWN,
                classification="timeout",
                diagnostics=(
                    str(error)
                    or f"{self.backend_id} exceeded {request.bounds.timeout_ms} ms",
                ),
                usage=ResourceUsage(elapsed_ms=request.bounds.timeout_ms),
            )
        except OSError as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(str(error),),
            )
        except Exception as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="malformed_output",
                diagnostics=(f"{type(error).__name__}: {error}",),
            )

        elapsed_ms = raw.elapsed_ms or int((time.monotonic() - started) * 1000)
        output_bytes = len(raw.stdout.encode("utf-8")) + len(
            raw.stderr.encode("utf-8")
        )
        observed = ResourceUsage(
            elapsed_ms=elapsed_ms,
            steps=raw.steps,
            peak_memory_bytes=raw.peak_memory_bytes,
            output_bytes=output_bytes,
        )
        exceeded = observed.exceeds(request.bounds)
        if exceeded:
            classification = (
                "timeout" if "timeout_ms" in exceeded else "resource_limit_exceeded"
            )
            attempt_status = (
                AttemptStatus.TIMED_OUT
                if classification == "timeout"
                else AttemptStatus.FAILED
            )
            digest = _output_digest(
                backend_id=self.backend_id,
                request=request,
                classification=classification,
                stdout=raw.stdout,
                stderr=raw.stderr,
                returncode=raw.returncode,
            )
            return self._terminal(
                request,
                attempt_status=attempt_status,
                result_status=(
                    ResultStatus.UNKNOWN
                    if attempt_status is AttemptStatus.TIMED_OUT
                    else ResultStatus.ERROR
                ),
                classification=classification,
                diagnostics=(
                    f"{self.backend_id} exceeded request bounds: "
                    + ", ".join(exceeded),
                ),
                usage=_bounded_usage(
                    request,
                    elapsed_ms=elapsed_ms,
                    steps=raw.steps,
                    peak_memory_bytes=raw.peak_memory_bytes,
                    output_bytes=output_bytes,
                ),
                output_digest=digest,
            )
        if raw.returncode != 0:
            digest = _output_digest(
                backend_id=self.backend_id,
                request=request,
                classification="backend_error",
                stdout=raw.stdout,
                stderr=raw.stderr,
                returncode=raw.returncode,
            )
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="backend_error",
                diagnostics=(
                    raw.stderr or f"{self.backend_id} exited with {raw.returncode}",
                ),
                usage=observed,
                output_digest=digest,
            )

        try:
            classification = _classify_solver_stdout(raw.stdout)
        except MalformedBackendOutput as error:
            digest = _output_digest(
                backend_id=self.backend_id,
                request=request,
                classification="malformed_output",
                stdout=raw.stdout,
                stderr=raw.stderr,
                returncode=raw.returncode,
            )
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="malformed_output",
                diagnostics=(str(error),),
                usage=observed,
                output_digest=digest,
            )

        if request.query_kind is QueryKind.THEOREM_PROOF:
            result_status = {
                "unsat": ResultStatus.PROVED,
                "sat": ResultStatus.DISPROVED,
                "unknown": ResultStatus.UNKNOWN,
            }[classification]
        else:
            result_status = {
                "sat": ResultStatus.SATISFIABLE,
                "unsat": ResultStatus.UNSATISFIABLE,
                "unknown": ResultStatus.UNKNOWN,
            }[classification]
        digest = _output_digest(
            backend_id=self.backend_id,
            request=request,
            classification=classification,
            stdout=raw.stdout,
            stderr=raw.stderr,
            returncode=raw.returncode,
        )
        payload: dict[str, Any] = {
            "compiled_request_digest": compiled.digest,
            "returncode": raw.returncode,
            "solver_result": classification,
        }
        if raw.solver_version:
            payload["solver_version"] = raw.solver_version
        for key, value in (
            ("solver_output", raw.stdout),
            ("solver_stderr", raw.stderr),
        ):
            if not value:
                continue
            candidate = {**payload, key: value}
            size = len(
                json.dumps(
                    candidate,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8")
            )
            if size <= request.bounds.max_output_bytes:
                payload = candidate
        return _make_outcome(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            capabilities=self.capabilities,
            request=request,
            attempt_status=AttemptStatus.SUCCEEDED,
            result_status=result_status,
            classification=classification,
            payload=payload,
            usage=observed,
            output_digest=digest,
        )


class ProofBackendRegistry(Mapping[str, ProofBackend]):
    """Deterministically ordered registry of explicit backend instances."""

    def __init__(self, backends: Iterable[ProofBackend] = ()) -> None:
        self._backends: dict[str, ProofBackend] = {}
        self._aliases: dict[str, str] = {}
        for backend in backends:
            self.register(backend)

    def __getitem__(self, backend_id: str) -> ProofBackend:
        canonical_id = self._aliases.get(backend_id, backend_id)
        try:
            return self._backends[canonical_id]
        except KeyError as error:
            raise UnknownBackendError(
                f"backend {backend_id!r} is not registered"
            ) from error

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._backends))

    def __len__(self) -> int:
        return len(self._backends)

    @property
    def capabilities(self) -> Mapping[str, BackendCapabilities]:
        """Return declarations without probing or executing backends."""

        return MappingProxyType(
            {
                backend_id: self._backends[backend_id].capabilities
                for backend_id in self
            }
        )

    def capabilities_for(self, backend_id: str) -> BackendCapabilities:
        return self[backend_id].capabilities

    def register(self, backend: ProofBackend) -> None:
        if not isinstance(backend, ProofBackend):
            raise TypeError("backend must implement the ProofBackend protocol")
        backend_id = _text(backend.backend_id, "backend_id")
        _text(backend.backend_version, "backend_version")
        if not isinstance(backend.capabilities, BackendCapabilities):
            raise TypeError("backend capabilities must be BackendCapabilities")
        if backend_id in self._backends or backend_id in self._aliases:
            raise DuplicateBackendError(
                f"backend {backend_id!r} is already registered"
            )
        matrix_entry = getattr(backend, "matrix_entry", None)
        aliases = tuple(getattr(matrix_entry, "aliases", ()) or ())
        canonical_aliases: list[str] = []
        for raw_alias in aliases:
            alias = _text(raw_alias, "backend alias")
            if alias == backend_id:
                continue
            if alias in self._backends or alias in self._aliases:
                raise DuplicateBackendError(
                    f"backend alias {alias!r} is already registered"
                )
            canonical_aliases.append(alias)
        self._backends[backend_id] = backend
        self._aliases.update(
            {alias: backend_id for alias in canonical_aliases}
        )

    def supporting(self, request: BackendRequest) -> tuple[str, ...]:
        """Return capable IDs without invoking backend ``supports`` methods."""

        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        requested_backend_id = self._aliases.get(
            request.requested_backend_id,
            request.requested_backend_id,
        )
        return tuple(
            backend_id
            for backend_id in self
            if (
                (
                    not requested_backend_id
                    or requested_backend_id == backend_id
                )
                and self._backends[backend_id].capabilities.supports(
                    request.logic_family, request.query_kind
                )
            )
        )

    def is_available(self, backend_id: str) -> bool:
        """Explicitly invoke a backend's read-only availability probe."""

        backend = self[backend_id]
        probe = getattr(backend, "is_available", None)
        if probe is None:
            return True
        try:
            return _operation_call("availability probe", probe) is True
        except Exception:
            return False

    def run(
        self,
        request: BackendRequest,
        *,
        backend_id: str | None = None,
        operation_timeout_ms: int | None = None,
        cancellation: Any | None = None,
    ) -> tuple[BackendAttempt, BoundedResult]:
        """Execute with an aggregate setup/run/normalization budget by default.

        Request/type and pure backend routing precede the operation. The budget
        is at most the declared request timeout; optional controls only tighten
        it. Stop results remain bound UNKNOWN pairs with no authority upgrade.
        """

        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        selected_id = self._aliases.get(
            backend_id or request.requested_backend_id,
            backend_id or request.requested_backend_id,
        )
        if (
            backend_id
            and request.requested_backend_id
            and self._aliases.get(backend_id, backend_id)
            != self._aliases.get(
                request.requested_backend_id,
                request.requested_backend_id,
            )
        ):
            raise BackendRegistryError(
                "backend_id conflicts with request.requested_backend_id"
            )
        if not selected_id:
            candidates = self.supporting(request)
            if not candidates:
                raise UnsupportedBackendRequest(
                    "no registered backend supports "
                    f"{request.logic_family}/{request.query_kind.value}"
                )
            # Independent Hyper engines are explicitly selectable. Retain the
            # historical choice for unspecified requests when the compatibility
            # family participates, including ordering against other providers.
            if "hyperltl_autohyper_mchyper" in candidates:
                candidates = tuple(candidate for candidate in candidates
                    if candidate not in {"hyperltl", "autohyper", "mchyper"})
            selected_id = candidates[0]
        backend = self[selected_id]
        return _run_scoped_operation(backend, request,
            lambda: self._run_request(request, backend),
            operation_timeout_ms=operation_timeout_ms, cancellation=cancellation)

    def _run_request(
        self, request: BackendRequest, backend: ProofBackend,
    ) -> tuple[BackendAttempt, BoundedResult]:
        if not _operation_call("registry capability check", backend.capabilities.supports,
            request.logic_family, request.query_kind
        ):
            return _make_outcome(
                backend_id=backend.backend_id,
                backend_version=backend.backend_version,
                capabilities=backend.capabilities,
                request=request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="unsupported",
                diagnostics=(
                    f"{backend.backend_id} does not support "
                    f"{request.logic_family}/{request.query_kind.value}",
                ),
            )
        try:
            returned = _operation_call("registry backend execution", backend.run, request)
            if (
                not isinstance(returned, tuple)
                or len(returned) != 2
                or not isinstance(returned[0], BackendAttempt)
                or not isinstance(returned[1], BoundedResult)
            ):
                raise MalformedBackendOutput(
                    "backend run must return (BackendAttempt, BoundedResult)"
                )
            attempt, result = returned
            expected_result_class = _RESULT_CLASSES[request.query_kind]
            valid = (
                attempt.request_digest == request.digest,
                attempt.backend_id == backend.backend_id,
                attempt.backend_version == backend.backend_version,
                attempt.bounds == request.bounds,
                result.request_digest == request.digest,
                result.attempt_digest == attempt.digest,
                result.backend_id == backend.backend_id,
                result.backend_version == backend.backend_version,
                result.bounds == request.bounds,
                isinstance(result, expected_result_class),
                result.authority.kind is request.query_kind.authority_kind,
                result.claim_digest == request.claim_digest,
                result.declaration_id == request.declaration_id,
                result.obligation_id == request.obligation_id,
                result.obligation_digest == request.obligation_digest,
                result.assumption_ids == request.assumption_ids,
                result.output_digest == attempt.output_digest,
                (
                    attempt.status is AttemptStatus.SUCCEEDED
                    or result.status in {ResultStatus.UNKNOWN, ResultStatus.ERROR}
                ),
            )
            if not all(valid):
                raise MalformedBackendOutput(
                    "backend return does not preserve request and attempt bindings"
                )
            return attempt, result
        except UnsupportedBackendRequest as error:
            classification = "unsupported"
            attempt_status = AttemptStatus.FAILED
            result_status = ResultStatus.ERROR
            diagnostic = f"{type(error).__name__}: {error}"
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            classification = "timeout"
            attempt_status = AttemptStatus.TIMED_OUT
            result_status = ResultStatus.UNKNOWN
            diagnostic = f"{type(error).__name__}: {error}"
        except OSError as error:
            classification = "unavailable"
            attempt_status = AttemptStatus.UNAVAILABLE
            result_status = ResultStatus.UNKNOWN
            diagnostic = f"{type(error).__name__}: {error}"
        except Exception as error:
            classification = "malformed_backend_contract"
            attempt_status = AttemptStatus.FAILED
            result_status = ResultStatus.ERROR
            diagnostic = f"{type(error).__name__}: {error}"
        usage = (
            ResourceUsage(elapsed_ms=request.bounds.timeout_ms)
            if attempt_status is AttemptStatus.TIMED_OUT
            else ResourceUsage()
        )
        return _make_outcome(
            backend_id=backend.backend_id,
            backend_version=backend.backend_version,
            capabilities=backend.capabilities,
            request=request,
            attempt_status=attempt_status,
            result_status=result_status,
            classification=classification,
            diagnostics=(diagnostic,),
            usage=usage,
        )


# ---------------------------------------------------------------------------
# ExecutableProviderMatrix@1 — full lazy LFV provider matrix
# ---------------------------------------------------------------------------

EXECUTABLE_PROVIDER_MATRIX_INTERFACE: Final = "ExecutableProviderMatrix@1"
EXECUTABLE_PROVIDER_MATRIX_VERSION: Final = "1.0.0"
PROVIDER_MATRIX_ENTRY_SCHEMA: Final = "executable-provider-matrix-entry/v1"

# Family keys used by acceptance / portfolio routing.
PROVIDER_MATRIX_FAMILY_SMT: Final = "smt"
PROVIDER_MATRIX_FAMILY_STATE_MODEL: Final = "state_model"
PROVIDER_MATRIX_FAMILY_RUNTIME: Final = "runtime"
PROVIDER_MATRIX_FAMILY_AUTHORIZATION: Final = "authorization"
PROVIDER_MATRIX_FAMILY_PROTOCOL: Final = "protocol"
PROVIDER_MATRIX_FAMILY_HYPERPROPERTY: Final = "hyperproperty"
PROVIDER_MATRIX_FAMILY_ATP: Final = "atp"
PROVIDER_MATRIX_FAMILY_HAMMER: Final = "hammer"
PROVIDER_MATRIX_FAMILY_KERNEL: Final = "kernel"

PROVIDER_MATRIX_FAMILIES: Final[tuple[str, ...]] = (
    PROVIDER_MATRIX_FAMILY_SMT,
    PROVIDER_MATRIX_FAMILY_STATE_MODEL,
    PROVIDER_MATRIX_FAMILY_RUNTIME,
    PROVIDER_MATRIX_FAMILY_AUTHORIZATION,
    PROVIDER_MATRIX_FAMILY_PROTOCOL,
    PROVIDER_MATRIX_FAMILY_HYPERPROPERTY,
    PROVIDER_MATRIX_FAMILY_ATP,
    PROVIDER_MATRIX_FAMILY_HAMMER,
    PROVIDER_MATRIX_FAMILY_KERNEL,
)


@dataclass(frozen=True, slots=True)
class ProviderMatrixEntry:
    """Inert declaration for one executable-matrix provider lane.

    Construction never imports a solver, probes the environment, installs a
    package, or starts a process.  Factories are resolved only by explicit
    availability probes or execution.
    """

    provider_id: str
    family: str
    logic_families: tuple[str, ...]
    query_kinds: tuple[str, ...]
    deterministic: bool = True
    aliases: tuple[str, ...] = ()
    factory_key: str = ""
    notes: str = ""
    schema_version: str = PROVIDER_MATRIX_ENTRY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _text(self.provider_id, "provider_id"))
        object.__setattr__(self, "family", _text(self.family, "family"))
        if self.family not in PROVIDER_MATRIX_FAMILIES:
            raise BackendRegistryError(
                f"provider matrix family must be one of {PROVIDER_MATRIX_FAMILIES}"
            )
        families = tuple(
            _text(item, "logic_families item") for item in self.logic_families
        )
        if not families:
            raise BackendRegistryError("logic_families must be non-empty")
        object.__setattr__(self, "logic_families", families)
        kinds = tuple(_text(item, "query_kinds item") for item in self.query_kinds)
        if not kinds:
            raise BackendRegistryError("query_kinds must be non-empty")
        object.__setattr__(self, "query_kinds", kinds)
        object.__setattr__(
            self,
            "aliases",
            tuple(_text(item, "aliases item") for item in self.aliases),
        )
        if not isinstance(self.factory_key, str):
            raise BackendRegistryError("factory_key must be a string")
        object.__setattr__(
            self,
            "notes",
            self.notes if isinstance(self.notes, str) else str(self.notes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "availability": "declared",
            "deterministic": self.deterministic,
            "factory_key": self.factory_key,
            "family": self.family,
            "logic_families": list(self.logic_families),
            "metadata": {
                "executable_provider_matrix": EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
                "family": self.family,
                "notes": self.notes,
            },
            "notes": self.notes,
            "provider_id": self.provider_id,
            "provider_version": "declared",
            "query_kinds": list(self.query_kinds),
            "schema_version": "logic-verification-provider/v1",
            # Keep the historical discovery source label for catalog consumers;
            # matrix identity lives under metadata.executable_provider_matrix.
            "source": "backend_registry",
        }

    def capabilities(self) -> BackendCapabilities:
        kinds: list[QueryKind] = []
        for raw in self.query_kinds:
            try:
                kinds.append(QueryKind(raw))
            except ValueError:
                continue
        if not kinds:
            kinds = [QueryKind.SATISFIABILITY]
        return BackendCapabilities(
            logic_families=self.logic_families,
            query_kinds=tuple(kinds),
            deterministic=self.deterministic,
        )


def _matrix_entry(
    provider_id: str,
    family: str,
    *,
    logic_families: Sequence[str],
    query_kinds: Sequence[str],
    deterministic: bool = True,
    aliases: Sequence[str] = (),
    factory_key: str = "",
    notes: str = "",
) -> ProviderMatrixEntry:
    return ProviderMatrixEntry(
        provider_id=provider_id,
        family=family,
        logic_families=tuple(logic_families),
        query_kinds=tuple(query_kinds),
        deterministic=deterministic,
        aliases=tuple(aliases),
        factory_key=factory_key or provider_id,
        notes=notes,
    )


# Closed catalog: SMT, state-model, runtime, authorization, protocol,
# hyperproperty, ATP, Hammer, and kernel lanes.  Portfolio-facing IDs are
# preferred so planning and execution share one namespace.
EXECUTABLE_PROVIDER_MATRIX: Final[tuple[ProviderMatrixEntry, ...]] = (
    _matrix_entry(
        "z3",
        PROVIDER_MATRIX_FAMILY_SMT,
        logic_families=("first_order", "smt", "software_verification"),
        query_kinds=("satisfiability", "theorem_proof"),
        factory_key="z3",
    ),
    _matrix_entry(
        "cvc5",
        PROVIDER_MATRIX_FAMILY_SMT,
        logic_families=("first_order", "smt", "software_verification"),
        query_kinds=("satisfiability", "theorem_proof"),
        factory_key="cvc5",
    ),
    _matrix_entry(
        "tla_tlc",
        PROVIDER_MATRIX_FAMILY_STATE_MODEL,
        logic_families=(
            "state_transition",
            "temporal",
            "tla_plus",
            "software_verification",
        ),
        query_kinds=("satisfiability",),
        aliases=("tlc",),
        factory_key="tla_tlc",
        notes="TLC model checker (portfolio id tla_tlc)",
    ),
    _matrix_entry(
        "apalache",
        PROVIDER_MATRIX_FAMILY_STATE_MODEL,
        logic_families=(
            "state_transition",
            "temporal",
            "tla_plus",
            "software_verification",
        ),
        query_kinds=("satisfiability",),
        factory_key="apalache",
    ),
    _matrix_entry(
        "runtime_mtl",
        PROVIDER_MATRIX_FAMILY_RUNTIME,
        logic_families=("temporal", "runtime", "software_verification"),
        query_kinds=("runtime_monitor",),
        factory_key="runtime_mtl",
        notes="Runtime MTL monitor lane (facade-native)",
    ),
    _matrix_entry(
        "datalog_secpal",
        PROVIDER_MATRIX_FAMILY_AUTHORIZATION,
        logic_families=(
            "authorization",
            "datalog",
            "secpal",
            "policy",
            "software_verification",
        ),
        query_kinds=("policy_approval",),
        aliases=("datalog-authorization", "secpal-authorization"),
        factory_key="datalog_secpal",
    ),
    _matrix_entry(
        "proverif",
        PROVIDER_MATRIX_FAMILY_PROTOCOL,
        logic_families=(
            "cryptographic_protocol",
            "protocol",
            "protocol_logic",
            "proverif",
            "software_verification",
        ),
        query_kinds=("theorem_proof",),
        factory_key="proverif",
    ),
    _matrix_entry(
        "tamarin",
        PROVIDER_MATRIX_FAMILY_PROTOCOL,
        logic_families=(
            "cryptographic_protocol",
            "protocol",
            "protocol_logic",
            "tamarin",
            "software_verification",
        ),
        query_kinds=("theorem_proof",),
        factory_key="tamarin",
    ),
    _matrix_entry(
        "hyperltl_autohyper_mchyper",
        PROVIDER_MATRIX_FAMILY_HYPERPROPERTY,
        logic_families=(
            "hyperproperty",
            "hyperltl",
            "noninterference",
            "software_verification",
        ),
        query_kinds=("theorem_proof", "satisfiability"),
        factory_key="hyperltl_autohyper_mchyper",
        notes="Compatibility entry using HyperLTL; select an independent engine ID for AutoHyper or MCHyper.",
    ),
    _matrix_entry(
        "hyperltl",
        PROVIDER_MATRIX_FAMILY_HYPERPROPERTY,
        logic_families=("hyperproperty", "hyperltl", "noninterference", "software_verification"),
        query_kinds=("theorem_proof", "satisfiability"),
        factory_key="hyperltl",
        notes="Independent HyperLTL execution; generic results remain non-conclusive.",
    ),
    _matrix_entry(
        "autohyper",
        PROVIDER_MATRIX_FAMILY_HYPERPROPERTY,
        logic_families=("hyperproperty", "hyperltl", "autohyper", "noninterference", "software_verification"),
        query_kinds=("theorem_proof", "satisfiability"),
        factory_key="autohyper",
        notes="Independent AutoHyper execution; no fallback to another engine.",
    ),
    _matrix_entry(
        "mchyper",
        PROVIDER_MATRIX_FAMILY_HYPERPROPERTY,
        logic_families=("hyperproperty", "hyperltl", "mchyper", "noninterference", "software_verification"),
        query_kinds=("theorem_proof", "satisfiability"),
        factory_key="mchyper",
        notes="Independent MCHyper execution requiring an explicit AIGER system model.",
    ),
    _matrix_entry(
        "vampire",
        PROVIDER_MATRIX_FAMILY_ATP,
        logic_families=("first_order", "fol", "dcec", "tdfol"),
        query_kinds=("theorem_proof", "satisfiability"),
        deterministic=False,
        factory_key="vampire",
    ),
    _matrix_entry(
        "eprover",
        PROVIDER_MATRIX_FAMILY_ATP,
        logic_families=("first_order", "fol", "dcec", "tdfol"),
        query_kinds=("theorem_proof", "satisfiability"),
        deterministic=False,
        aliases=("e",),
        factory_key="eprover",
    ),
    _matrix_entry(
        "hammer",
        PROVIDER_MATRIX_FAMILY_HAMMER,
        logic_families=(
            "first_order",
            "higher_order",
            "dependent_type_theory",
            "software_verification",
        ),
        query_kinds=("theorem_proof",),
        factory_key="hammer",
    ),
    _matrix_entry(
        "lean",
        PROVIDER_MATRIX_FAMILY_KERNEL,
        logic_families=(
            "lean",
            "lean4",
            "dependent_type_theory",
            "higher_order",
            "software_verification",
        ),
        query_kinds=("theorem_proof",),
        factory_key="lean",
    ),
    _matrix_entry(
        "rocq",
        PROVIDER_MATRIX_FAMILY_KERNEL,
        logic_families=(
            "rocq",
            "coq",
            "dependent_type_theory",
            "higher_order",
            "software_verification",
        ),
        query_kinds=("theorem_proof",),
        aliases=("coq", "coqc"),
        factory_key="rocq",
    ),
    _matrix_entry(
        "isabelle",
        PROVIDER_MATRIX_FAMILY_KERNEL,
        logic_families=(
            "isabelle",
            "higher_order",
            "hol",
            "software_verification",
        ),
        query_kinds=("theorem_proof",),
        factory_key="isabelle",
    ),
)

# Exact closed executable-matrix provider IDs (portfolio namespace).  Presence in
# this set is a declaration only; it never proves a binary is installed or that
# a proof claim is available.  Advisory lanes (ergoai, symbolicai) are outside
# this matrix and live in the provider-capability catalog.
EXECUTABLE_PROVIDER_IDS: Final[tuple[str, ...]] = tuple(
    entry.provider_id for entry in EXECUTABLE_PROVIDER_MATRIX
)

# Reviewed dual-read aliases bound to executable-matrix canonical IDs.
EXECUTABLE_PROVIDER_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        alias: entry.provider_id
        for entry in EXECUTABLE_PROVIDER_MATRIX
        for alias in entry.aliases
    }
)


def provider_matrix_declarations() -> tuple[ProviderMatrixEntry, ...]:
    """Return the closed executable provider matrix without imports or probes."""

    return EXECUTABLE_PROVIDER_MATRIX


def provider_matrix_by_family() -> dict[str, tuple[str, ...]]:
    """Map each matrix family to sorted provider ids (pure data)."""

    grouped: dict[str, list[str]] = {family: [] for family in PROVIDER_MATRIX_FAMILIES}
    for entry in EXECUTABLE_PROVIDER_MATRIX:
        grouped.setdefault(entry.family, []).append(entry.provider_id)
    return {family: tuple(sorted(ids)) for family, ids in grouped.items()}


def _factory_constructors() -> dict[str, Callable[[], Any]]:
    """Map factory keys to zero-arg constructors.  Imports stay inside callables."""

    def z3():
        from .z3 import Z3Backend

        return Z3Backend()

    def cvc5():
        from .cvc5 import CVC5Backend

        return CVC5Backend()

    def tla_tlc():
        from .tla.runners import TLCBackend

        return TLCBackend()

    def apalache():
        from .tla.runners import ApalacheBackend

        return ApalacheBackend()

    def datalog_secpal():
        from .datalog.adapters import DatalogAuthorizationBackend

        return DatalogAuthorizationBackend()

    def proverif():
        from .protocol.proverif import ProVerifBackend

        return ProVerifBackend()

    def tamarin():
        from .protocol.tamarin import TamarinBackend

        return TamarinBackend()

    def hyperltl():
        from .hyperproperties.adapters import HyperLTLBackend

        return HyperLTLBackend()

    def autohyper():
        from .hyperproperties.adapters import AutoHyperBackend

        return AutoHyperBackend()

    def mchyper():
        from .hyperproperties.adapters import MCHyperBackend

        return MCHyperBackend()

    def vampire():
        from .atp.adapters import VampireBackend

        return VampireBackend()

    def eprover():
        from .atp.adapters import EProverBackend

        return EProverBackend()

    def hammer():
        from ipfs_datasets_py.logic.hammers.backend import HammerBackend

        return HammerBackend()

    def lean():
        from .kernel.lean import LeanKernelBackend

        return LeanKernelBackend()

    def rocq():
        from .kernel.rocq import RocqKernelBackend

        return RocqKernelBackend()

    def isabelle():
        from .kernel.isabelle import IsabelleKernelBackend

        return IsabelleKernelBackend()

    def runtime_mtl():
        # Facade-native lane: no external process.
        return None

    return {
        "z3": z3,
        "cvc5": cvc5,
        "tla_tlc": tla_tlc,
        "apalache": apalache,
        "datalog_secpal": datalog_secpal,
        "proverif": proverif,
        "tamarin": tamarin,
        "hyperltl_autohyper_mchyper": hyperltl,
        "hyperltl": hyperltl,
        "autohyper": autohyper,
        "mchyper": mchyper,
        "vampire": vampire,
        "eprover": eprover,
        "hammer": hammer,
        "lean": lean,
        "rocq": rocq,
        "isabelle": isabelle,
        "runtime_mtl": runtime_mtl,
    }


class LazyMatrixProofBackend:
    """ProofBackend wrapper that registers a matrix entry without import side effects.

    Construction stores only the inert :class:`ProviderMatrixEntry`.  The
    underlying adapter is imported on first ``is_available`` / ``run`` call.
    Protocol-mismatched adapters are normalized into bound attempt/result
    pairs. Missing native Hyper tools may use explicitly requested bounded
    self-composition; public availability still describes the native tool.
    """

    def __init__(
        self,
        entry: ProviderMatrixEntry,
        *,
        factory: Callable[[], Any] | None = None,
        availability_probe: AvailabilityProbe | None = None,
    ) -> None:
        if not isinstance(entry, ProviderMatrixEntry):
            raise TypeError("entry must be a ProviderMatrixEntry")
        self._entry = entry
        self._factory = factory
        self._availability_probe = availability_probe
        self._delegate: Any | None = None
        self._delegate_error: str = ""
        self._delegate_loaded = False
        self._delegate_lock = Lock()
        self._capabilities = entry.capabilities()
        self._backend_id = entry.provider_id
        self._backend_version = "matrix-declared/v1"

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def backend_version(self) -> str:
        return self._backend_version

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    @property
    def matrix_entry(self) -> ProviderMatrixEntry:
        return self._entry

    def supports(self, request: BackendRequest) -> bool:
        if not isinstance(request, BackendRequest):
            return False
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self._entry.aliases,
        }:
            return False
        return self._capabilities.supports(request.logic_family, request.query_kind)

    def _load_delegate(self) -> Any | None:
        from .smt.operation_budget import ProofOperationInterrupted

        _operation_checkpoint("before lazy backend construction")
        if self._delegate_loaded:
            return self._delegate
        # A concurrent caller sees either a completed cached delegate or waits
        # under its own scope; it never mistakes in-progress setup for absence.
        while True:
            remaining = _operation_checkpoint("waiting for lazy backend construction")
            if self._delegate_lock.acquire(timeout=0.05 if remaining is None else min(0.05, remaining)):
                break
        try:
            _operation_checkpoint("before lazy backend construction")
            if self._delegate_loaded:
                return self._delegate
            if self._factory is None:
                self._delegate_loaded = True
                return None
            try:
                delegate = _operation_call("lazy backend factory", self._factory)
            except ProofOperationInterrupted:
                # A later fresh operation may retry; this interrupted one may not.
                raise
            except Exception as error:
                detail = f"{type(error).__name__}: {error}"
                _operation_checkpoint("after lazy backend failure normalization")
                self._delegate_error = detail
                self._delegate_loaded = True
                return None
            _operation_checkpoint("before lazy backend publication")
            self._delegate = delegate
            self._delegate_loaded = True
            return delegate
        finally:
            self._delegate_lock.release()

    def is_available(self) -> bool:
        """Explicit availability probe; never runs during discovery."""

        if self._availability_probe is not None:
            try:
                return _operation_call("availability probe", self._availability_probe) is True
            except Exception:
                return False
        if self._entry.factory_key == "runtime_mtl":
            return True
        if self._entry.factory_key == "datalog_secpal":
            return True
        delegate = _operation_call("lazy delegate access", self._load_delegate)
        if delegate is None:
            return False
        probe = _operation_call("delegate availability lookup", getattr, delegate, "is_available", None)
        if probe is None:
            return True
        try:
            return _operation_call("availability probe", probe) is True
        except Exception:
            return False

    def _is_available_for_request(self, request: BackendRequest) -> bool:
        """Allow local Hyper fallback only after canonical missing-tool discovery.

        A caller veto, a failed probe, or an opaque delegate is not evidence of
        a missing native executable. Eligibility belongs to this request only;
        it neither changes public availability nor persists on the delegate.
        """
        traces = request.payload.get("traces")
        if (
            self._availability_probe is not None
            or getattr(self.is_available, "__func__", None) is not _CANONICAL_MATRIX_AVAILABILITY
            or request.payload.get("allow_fallback") is not True
            or not isinstance(traces, (tuple, list)) or not traces
            or self._entry.family != PROVIDER_MATRIX_FAMILY_HYPERPROPERTY
            or self.backend_id not in {"hyperltl_autohyper_mchyper", "hyperltl", "autohyper", "mchyper"}
            or self._entry.factory_key != self.backend_id
        ):
            return _operation_call("backend availability", self.is_available)

        # Import only on execution of an eligible request; catalog discovery
        # and registration remain inert. Exact types keep custom adapters on
        # their original availability contract.
        from .hyperproperties.adapters import (
            AutoHyperBackend, HyperEngine, HyperEngineCapability, HyperLTLBackend, MCHyperBackend,
            _CANONICAL_NATIVE_AVAILABILITY, _CANONICAL_NATIVE_PROBE,
        )
        from .smt.operation_budget import ProofOperationInterrupted

        expected_type, engine = {
            "hyperltl_autohyper_mchyper": (HyperLTLBackend, HyperEngine.HYPERLTL),
            "hyperltl": (HyperLTLBackend, HyperEngine.HYPERLTL),
            "autohyper": (AutoHyperBackend, HyperEngine.AUTOHYPER),
            "mchyper": (MCHyperBackend, HyperEngine.MCHYPER),
        }[self.backend_id]
        delegate = _operation_call("lazy delegate access", self._load_delegate)
        if delegate is None:
            return False
        if (
            type(delegate) is not expected_type
            or delegate.engine is not engine
            or not isinstance(delegate.capability, HyperEngineCapability)
            or delegate.capability.engine is not engine
            or delegate.capability.supports_self_composition_fallback is not True
            or getattr(delegate.is_available, "__func__", None) is not _CANONICAL_NATIVE_AVAILABILITY
            or getattr(delegate.probe, "__func__", None) is not _CANONICAL_NATIVE_PROBE
        ):
            return _operation_call("backend availability", self.is_available)
        try:
            available = _operation_call("Hyper native availability", delegate.is_available)
        except ProofOperationInterrupted:
            raise
        except Exception:
            return False
        # Canonical discovery returns a bool. A normal False permits the
        # selected adapter to evaluate supplied traces under the same scope.
        # It rechecks discovery itself; a newly appearing binary still uses
        # the ordinary admitted native runner rather than a forced fallback.
        return available is True or available is False

    def _terminal(
        self,
        request: BackendRequest,
        *,
        attempt_status: AttemptStatus,
        result_status: ResultStatus,
        classification: str,
        diagnostics: Sequence[str],
        usage: ResourceUsage | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[BackendAttempt, BoundedResult]:
        return _make_outcome(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            capabilities=self._capabilities,
            request=request,
            attempt_status=attempt_status,
            result_status=result_status,
            classification=classification,
            diagnostics=diagnostics,
            usage=usage,
            payload=payload,
        )

    def run(
        self, request: BackendRequest, *, operation_timeout_ms: int | None = None,
        cancellation: Any | None = None,
    ) -> tuple[BackendAttempt, BoundedResult]:
        """Run within one inherited, tightening wall/cancellation scope.

        Python callbacks are cooperative. Native transports that already honor
        the ambient proof operation also consume setup/admission time.
        """
        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        return _run_scoped_operation(self, request, lambda: self._run_request(request),
            operation_timeout_ms=operation_timeout_ms, cancellation=cancellation)

    def _run_request(self, request: BackendRequest) -> tuple[BackendAttempt, BoundedResult]:
        if not _operation_call("backend capability check", self.supports, request):
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="unsupported",
                diagnostics=(
                    f"{self.backend_id} does not support "
                    f"{request.logic_family}/{request.query_kind.value}",
                ),
            )

        if self._entry.factory_key == "runtime_mtl":
            return _operation_call("runtime MTL normalization", self._run_runtime_mtl, request)

        if not _operation_call("request availability", self._is_available_for_request, request):
            detail = self._delegate_error or f"{self.backend_id} is not available"
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(detail,),
            )

        delegate = _operation_call("lazy delegate access", self._load_delegate)
        if delegate is None:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(
                    self._delegate_error
                    or f"no executable adapter bound for {self.backend_id}",
                ),
            )

        run = _operation_call("delegate run lookup", getattr, delegate, "run", None)
        if not callable(run):
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="malformed_backend_contract",
                diagnostics=(f"{self.backend_id} adapter has no run method",),
            )

        try:
            returned = _operation_call("delegate execution", run, request)
        except UnsupportedBackendRequest as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="unsupported",
                diagnostics=(f"{type(error).__name__}: {error}",),
            )
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.TIMED_OUT,
                result_status=ResultStatus.UNKNOWN,
                classification="timeout",
                diagnostics=(f"{type(error).__name__}: {error}",),
                usage=ResourceUsage(elapsed_ms=request.bounds.timeout_ms),
            )
        except OSError as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(f"{type(error).__name__}: {error}",),
            )
        except Exception as error:
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="malformed_backend_contract",
                diagnostics=(f"{type(error).__name__}: {error}",),
            )

        if (
            isinstance(returned, tuple)
            and len(returned) == 2
            and isinstance(returned[0], BackendAttempt)
            and isinstance(returned[1], BoundedResult)
        ):
            return _operation_call("protocol pair rebinding", self._rebind_protocol_pair,
                                   request, returned[0], returned[1])

        return _operation_call("foreign outcome normalization", self._normalize_foreign_outcome,
                               request, returned)


    def _rebind_protocol_pair(
        self,
        request: BackendRequest,
        attempt: BackendAttempt,
        result: BoundedResult,
    ) -> tuple[BackendAttempt, BoundedResult]:
        """Rebind delegate outcomes onto this matrix backend identity.

        Delegate adapters may use a different ``backend_id`` / version (for
        example portfolio id ``eprover`` vs adapter id ``e``).  The registry
        requires exact identity match with the registered wrapper.
        """

        if (
            attempt.backend_id == self.backend_id
            and attempt.backend_version == self.backend_version
            and result.backend_id == self.backend_id
            and result.backend_version == self.backend_version
        ):
            return attempt, result

        result_status = getattr(result, "status", ResultStatus.UNKNOWN)
        if not isinstance(result_status, ResultStatus):
            try:
                result_status = ResultStatus(str(getattr(result_status, "value", result_status)))
            except ValueError:
                result_status = ResultStatus.UNKNOWN
        attempt_status = getattr(attempt, "status", AttemptStatus.SUCCEEDED)
        if not isinstance(attempt_status, AttemptStatus):
            try:
                attempt_status = AttemptStatus(str(getattr(attempt_status, "value", attempt_status)))
            except ValueError:
                attempt_status = AttemptStatus.SUCCEEDED
        payload = {}
        if hasattr(result, "payload") and result.payload is not None:
            payload = (
                result.payload.to_dict()
                if hasattr(result.payload, "to_dict")
                else dict(result.payload)
            )
        diagnostics = tuple(getattr(attempt, "diagnostics", ()) or ()) + tuple(
            getattr(result, "diagnostics", ()) or ()
        )
        usage = getattr(attempt, "usage", None)
        return _make_outcome(
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            capabilities=self._capabilities,
            request=request,
            attempt_status=attempt_status,
            result_status=result_status,
            classification=str(getattr(result_status, "value", result_status)),
            diagnostics=diagnostics or (f"rebound from {attempt.backend_id}",),
            usage=usage if isinstance(usage, ResourceUsage) else None,
            payload=payload,
            output_digest=getattr(attempt, "output_digest", "") or "",
        )

    def _run_runtime_mtl(
        self, request: BackendRequest
    ) -> tuple[BackendAttempt, BoundedResult]:
        payload = request.payload.to_dict() if hasattr(request.payload, "to_dict") else {}
        formula = payload.get("formula") or payload.get("goal") or payload.get("statement")
        if formula in (None, ""):
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="malformed",
                diagnostics=("runtime_mtl requires a formula in the request payload",),
            )
        return self._terminal(
            request,
            attempt_status=AttemptStatus.SUCCEEDED,
            result_status=ResultStatus.UNKNOWN,
            classification="runtime_mtl_deferred",
            diagnostics=(
                "runtime_mtl lane is registered; use LogicVerificationAPI.monitor "
                "for full MTL evaluation over observations",
            ),
            payload={"lane": "runtime_mtl", "formula_present": True},
        )

    def _normalize_foreign_outcome(
        self, request: BackendRequest, returned: Any
    ) -> tuple[BackendAttempt, BoundedResult]:
        """Retain foreign evidence without translating its semantic authority.

        A foreign status can describe a terminal execution failure, but cannot
        establish a conclusion for the query kind chosen by the caller. Only
        the separate protocol-pair path handles already bound protocol results.
        """

        classification = "foreign_adapter_outcome"
        attempt_status = AttemptStatus.SUCCEEDED
        result_status = ResultStatus.UNKNOWN
        diagnostics = [
            "foreign outcome recorded without authority upgrade; "
            "generic conclusions remain non-conclusive"
        ]
        payload: dict[str, Any] = {"adapter_return_type": type(returned).__name__}

        def field(value: Any, name: str) -> Any:
            return _operation_call("foreign " + name + " access",
                value.get if isinstance(value, Mapping) else lambda key: getattr(value, key, None), name)

        def declared_text(value: Any, name: str) -> str:
            raw = _operation_call("foreign enum value access", getattr, value, "value", value)
            if (not isinstance(raw, str) or not raw or raw != raw.strip()
                    or "\x00" in raw or len(raw) > 256):
                raise MalformedBackendOutput(f"foreign {name} must be bounded non-empty text")
            return raw

        def bounded_payload(value: Mapping[str, Any]) -> dict[str, Any]:
            # Apply the same finite-JSON contract as BoundedResult, then count
            # encoded chunks without joining an arbitrarily large JSON string.
            frozen = FrozenMap(value).to_dict()
            remaining = request.bounds.max_output_bytes
            encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"),
                                       sort_keys=True, allow_nan=False)
            for chunk in encoder.iterencode(frozen):
                if len(chunk) > remaining:
                    raise MalformedBackendOutput("foreign payload exceeds max_output_bytes")
                remaining -= len(chunk.encode("utf-8"))
                if remaining < 0:
                    raise MalformedBackendOutput("foreign payload exceeds max_output_bytes")
            return frozen

        phase = "result access"
        try:
            result_obj = field(returned, "result")
            nested = result_obj is not None
            if not nested:
                result_obj = returned
            phase = "status access"
            status = field(result_obj, "status")
            if status is not None:
                status_value = declared_text(status, "status")
                payload["result_status"] = status_value
                # This is deliberately a terminal-only map, never ResultStatus
                # construction from a foreign verdict or the requested query.
                terminal = {
                    "unavailable": (AttemptStatus.UNAVAILABLE, ResultStatus.UNKNOWN),
                    "timeout": (AttemptStatus.TIMED_OUT, ResultStatus.UNKNOWN),
                    "timed_out": (AttemptStatus.TIMED_OUT, ResultStatus.UNKNOWN),
                    "cancelled": (AttemptStatus.CANCELLED, ResultStatus.UNKNOWN),
                    "canceled": (AttemptStatus.CANCELLED, ResultStatus.UNKNOWN),
                    "error": (AttemptStatus.FAILED, ResultStatus.ERROR),
                    "malformed": (AttemptStatus.FAILED, ResultStatus.ERROR),
                    "unsupported": (AttemptStatus.FAILED, ResultStatus.ERROR),
                }.get(status_value.lower())
                if terminal is not None:
                    attempt_status, result_status = terminal
            phase = "authority access"
            authority = field(result_obj, "authority")
            if authority is not None:
                raw_authority = _operation_call("foreign authority value access", getattr,
                                                authority, "value", authority)
                if isinstance(raw_authority, str):
                    payload["result_authority"] = declared_text(raw_authority, "authority")
                elif isinstance(raw_authority, Mapping):
                    payload["result_authority"] = dict(raw_authority)
                else:
                    serializer = _operation_call("foreign authority serializer lookup", getattr,
                                                 raw_authority, "to_dict", None)
                    if not callable(serializer):
                        raise MalformedBackendOutput("foreign authority is not descriptive JSON")
                    serialized = _operation_call("foreign authority serialization", serializer)
                    if not isinstance(serialized, Mapping):
                        raise MalformedBackendOutput("foreign authority serialization must be a mapping")
                    payload["result_authority"] = dict(serialized)
            if self._entry.family in {
                PROVIDER_MATRIX_FAMILY_ATP, PROVIDER_MATRIX_FAMILY_HAMMER,
            }:
                payload["authority_note"] = (
                    "foreign ATP/Hammer outcomes remain candidate evidence until kernel reconstruction; "
                    "this generic wrapper establishes no proof"
                )
            phase = "result serialization" if nested else "outcome serialization"
            serializer = _operation_call("foreign result serializer lookup", getattr,
                                         result_obj, "to_dict", None)
            if serializer is not None:
                if not callable(serializer):
                    raise MalformedBackendOutput("foreign to_dict must be callable")
                serialized = _operation_call("foreign result serialization", serializer)
                if not isinstance(serialized, Mapping):
                    raise MalformedBackendOutput("foreign serialization must be a mapping")
                payload["result" if nested else "outcome"] = dict(serialized)
            elif isinstance(result_obj, Mapping):
                payload["result" if nested else "outcome"] = dict(result_obj)
            phase = "payload validation"
            payload = _operation_call("foreign payload validation", bounded_payload, payload)
        except Exception as error:
            _operation_checkpoint("foreign outcome failure normalization")
            # A broken getter/serializer cannot turn a foreign result into a
            # successful generic attempt. Do not evaluate arbitrary exception
            # string methods, retry callbacks, or catch process-control signals.
            attempt_status = AttemptStatus.FAILED
            result_status = ResultStatus.ERROR
            diagnostics.append(f"foreign {phase} failed ({type(error).__name__}); payload omitted")
            fallback: dict[str, Any] = {"foreign_payload_omitted": True}
            try:
                fallback = bounded_payload(fallback)
            except MalformedBackendOutput:
                # Small limits may not fit the descriptive marker. The existing
                # terminal helper requires a representable non-empty payload.
                fallback = bounded_payload({"omitted": True})
            for name in ("adapter_return_type", "result_status", "result_authority", "authority_note"):
                value = payload.get(name)
                if not isinstance(value, str) or len(value) > 256:
                    continue
                try:
                    fallback = bounded_payload({**fallback, name: value})
                except (ValueError, TypeError):
                    continue
            payload = fallback

        return self._terminal(
            request,
            attempt_status=attempt_status,
            result_status=result_status,
            classification=classification,
            diagnostics=diagnostics,
            payload=payload,
        )


_CANONICAL_MATRIX_AVAILABILITY: Final = LazyMatrixProofBackend.is_available


def default_backend_registry() -> ProofBackendRegistry:
    """Construct the full lazy executable provider matrix without probing tools.

    Every LFV family lane (SMT, state-model, runtime, authorization, protocol,
    hyperproperty, ATP, Hammer, kernel) is registered behind
    :class:`LazyMatrixProofBackend`.  Importing this function's module and
    calling this constructor never probes the environment or installs packages.
    """

    factories = _factory_constructors()
    backends: list[ProofBackend] = []
    for entry in EXECUTABLE_PROVIDER_MATRIX:
        factory = factories.get(entry.factory_key)
        backends.append(
            LazyMatrixProofBackend(
                entry,
                factory=factory,
            )
        )
    return ProofBackendRegistry(backends)


def declared_backend_catalog(
    registry: ProofBackendRegistry | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return declarative provider/backend descriptors without probes.

    Used by :mod:`ipfs_datasets_py.logic.verification_api` for side-effect-free
    ``list_providers`` / capability discovery.  Never calls ``is_available``.

    When *registry* is omitted the closed :data:`EXECUTABLE_PROVIDER_MATRIX` is
    returned directly (no adapter construction).  When a registry is supplied,
    its registered backends are described instead.
    """

    if registry is None:
        return tuple(entry.to_dict() for entry in EXECUTABLE_PROVIDER_MATRIX)

    entries: list[dict[str, Any]] = []
    for backend_id in registry:
        backend = registry[backend_id]
        capabilities = backend.capabilities
        caps_dict = (
            capabilities.to_dict()
            if hasattr(capabilities, "to_dict")
            else {
                "logic_families": list(getattr(capabilities, "logic_families", ())),
                "query_kinds": [
                    getattr(kind, "value", str(kind))
                    for kind in getattr(capabilities, "query_kinds", ())
                ],
                "deterministic": bool(getattr(capabilities, "deterministic", True)),
            }
        )
        raw_kinds = caps_dict.get("query_kinds", ())
        query_kinds = [getattr(kind, "value", str(kind)) for kind in raw_kinds]
        matrix_entry = getattr(backend, "matrix_entry", None)
        family = (
            matrix_entry.family
            if isinstance(matrix_entry, ProviderMatrixEntry)
            else ""
        )
        entries.append(
            {
                "availability": "declared",
                "deterministic": bool(caps_dict.get("deterministic", True)),
                "logic_families": list(caps_dict.get("logic_families", ())),
                "metadata": {
                    "executable_provider_matrix": EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
                    "family": family,
                },
                "provider_id": backend_id,
                "provider_version": str(
                    getattr(backend, "backend_version", "declared")
                ),
                "query_kinds": query_kinds,
                "schema_version": "logic-verification-provider/v1",
                "source": "backend_registry",
            }
        )
    return tuple(entries)


__all__ = [
    "BACKEND_ADAPTER_VERSION",
    "EXECUTABLE_PROVIDER_ALIASES",
    "EXECUTABLE_PROVIDER_IDS",
    "EXECUTABLE_PROVIDER_MATRIX",
    "EXECUTABLE_PROVIDER_MATRIX_INTERFACE",
    "EXECUTABLE_PROVIDER_MATRIX_VERSION",
    "AvailabilityProbe",
    "BackendCompiler",
    "BackendRegistryError",
    "BackendRunner",
    "BackendRunnerOutput",
    "CallableProofBackend",
    "CompiledBackendRequest",
    "DuplicateBackendError",
    "LazyMatrixProofBackend",
    "MalformedBackendOutput",
    "PROVIDER_MATRIX_FAMILIES",
    "ProviderMatrixEntry",
    "ProofBackendRegistry",
    "UnknownBackendError",
    "UnsupportedBackendRequest",
    "compile_smtlib_request",
    "declared_backend_catalog",
    "default_backend_registry",
    "provider_matrix_by_family",
    "provider_matrix_declarations",
]
