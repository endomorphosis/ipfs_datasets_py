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
            return self._availability_probe() is True
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

    def run(self, request: BackendRequest) -> tuple[BackendAttempt, BoundedResult]:
        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        if not self.supports(request):
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
        if not self.is_available():
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(f"{self.backend_id} is not available",),
            )

        started = time.monotonic()
        try:
            compiled = self._compiler(request)
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
            raw = self._runner(compiled, request)
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
        for backend in backends:
            self.register(backend)

    def __getitem__(self, backend_id: str) -> ProofBackend:
        try:
            return self._backends[backend_id]
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
        if backend_id in self._backends:
            raise DuplicateBackendError(
                f"backend {backend_id!r} is already registered"
            )
        self._backends[backend_id] = backend

    def supporting(self, request: BackendRequest) -> tuple[str, ...]:
        """Return capable IDs without invoking backend ``supports`` methods."""

        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        return tuple(
            backend_id
            for backend_id in self
            if (
                (
                    not request.requested_backend_id
                    or request.requested_backend_id == backend_id
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
            return probe() is True
        except Exception:
            return False

    def run(
        self,
        request: BackendRequest,
        *,
        backend_id: str | None = None,
    ) -> tuple[BackendAttempt, BoundedResult]:
        """Execute one backend and fail closed on malformed return values."""

        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        selected_id = backend_id or request.requested_backend_id
        if (
            backend_id
            and request.requested_backend_id
            and backend_id != request.requested_backend_id
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
            selected_id = candidates[0]
        backend = self[selected_id]
        if not backend.capabilities.supports(
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
            returned = backend.run(request)
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


def default_backend_registry() -> ProofBackendRegistry:
    """Construct inert Z3/cvc5 adapters without probing either solver."""

    from .cvc5.compiler import CVC5Backend
    from .z3.compiler import Z3Backend

    return ProofBackendRegistry((Z3Backend(), CVC5Backend()))


__all__ = [
    "BACKEND_ADAPTER_VERSION",
    "AvailabilityProbe",
    "BackendCompiler",
    "BackendRegistryError",
    "BackendRunner",
    "BackendRunnerOutput",
    "CallableProofBackend",
    "CompiledBackendRequest",
    "DuplicateBackendError",
    "MalformedBackendOutput",
    "ProofBackendRegistry",
    "UnknownBackendError",
    "UnsupportedBackendRequest",
    "compile_smtlib_request",
    "default_backend_registry",
]
