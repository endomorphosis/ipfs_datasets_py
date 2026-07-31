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
        aliases=("hyperltl", "autohyper", "mchyper"),
        factory_key="hyperltl_autohyper_mchyper",
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
        from .z3.compiler import Z3Backend

        return Z3Backend()

    def cvc5():
        from .cvc5.compiler import CVC5Backend

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
    pairs; unavailable tools report ``UNAVAILABLE`` rather than succeeding.
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
        if self._delegate_loaded:
            return self._delegate
        self._delegate_loaded = True
        if self._factory is None:
            return None
        try:
            self._delegate = self._factory()
        except Exception as error:
            self._delegate = None
            self._delegate_error = f"{type(error).__name__}: {error}"
        return self._delegate

    def is_available(self) -> bool:
        """Explicit availability probe; never runs during discovery."""

        if self._availability_probe is not None:
            try:
                return self._availability_probe() is True
            except Exception:
                return False
        if self._entry.factory_key == "runtime_mtl":
            return True
        if self._entry.factory_key == "datalog_secpal":
            return True
        delegate = self._load_delegate()
        if delegate is None:
            return False
        probe = getattr(delegate, "is_available", None)
        if probe is None:
            return True
        try:
            return probe() is True
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

        if self._entry.factory_key == "runtime_mtl":
            return self._run_runtime_mtl(request)

        if not self.is_available():
            detail = self._delegate_error or f"{self.backend_id} is not available"
            return self._terminal(
                request,
                attempt_status=AttemptStatus.UNAVAILABLE,
                result_status=ResultStatus.UNKNOWN,
                classification="unavailable",
                diagnostics=(detail,),
            )

        delegate = self._load_delegate()
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

        run = getattr(delegate, "run", None)
        if not callable(run):
            return self._terminal(
                request,
                attempt_status=AttemptStatus.FAILED,
                result_status=ResultStatus.ERROR,
                classification="malformed_backend_contract",
                diagnostics=(f"{self.backend_id} adapter has no run method",),
            )

        try:
            returned = run(request)
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
            return self._rebind_protocol_pair(request, returned[0], returned[1])

        return self._normalize_foreign_outcome(request, returned)


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
        """Map non-protocol adapter returns onto bound attempt/result pairs."""

        classification = "foreign_adapter_outcome"
        attempt_status = AttemptStatus.SUCCEEDED
        result_status = ResultStatus.UNKNOWN
        diagnostics: list[str] = []
        payload: dict[str, Any] = {"adapter_return_type": type(returned).__name__}

        result_obj = getattr(returned, "result", None)
        if result_obj is not None:
            status = getattr(result_obj, "status", None)
            if status is not None:
                status_value = getattr(status, "value", str(status)).lower()
                payload["result_status"] = status_value
                try:
                    result_status = ResultStatus(status_value)
                except ValueError:
                    result_status = ResultStatus.UNKNOWN
                if status_value in {"unavailable"}:
                    attempt_status = AttemptStatus.UNAVAILABLE
                    result_status = ResultStatus.UNKNOWN
                elif status_value in {"error", "malformed"}:
                    attempt_status = AttemptStatus.FAILED
                    result_status = ResultStatus.ERROR
                elif status_value in {"timeout"}:
                    attempt_status = AttemptStatus.TIMED_OUT
                    result_status = ResultStatus.UNKNOWN
            if hasattr(result_obj, "to_dict"):
                try:
                    payload["result"] = result_obj.to_dict()
                except Exception as error:
                    diagnostics.append(f"result serialization failed: {error}")
        elif hasattr(returned, "to_dict"):
            try:
                payload["outcome"] = returned.to_dict()
            except Exception as error:
                diagnostics.append(f"outcome serialization failed: {error}")
        else:
            diagnostics.append(
                f"{self.backend_id} returned non-protocol outcome "
                f"{type(returned).__name__}; recorded without authority upgrade"
            )

        if result_status not in {
            ResultStatus.UNKNOWN,
            ResultStatus.ERROR,
            ResultStatus.TIMEOUT,
            ResultStatus.UNAVAILABLE,
            ResultStatus.UNSUPPORTED,
            ResultStatus.MALFORMED,
            ResultStatus.CANDIDATE,
        }:
            if self._entry.family in {
                PROVIDER_MATRIX_FAMILY_ATP,
                PROVIDER_MATRIX_FAMILY_HAMMER,
            }:
                result_status = ResultStatus.CANDIDATE
                payload["authority_note"] = (
                    "foreign ATP/Hammer outcomes remain candidate until kernel reconstruction"
                )

        return self._terminal(
            request,
            attempt_status=attempt_status,
            result_status=result_status,
            classification=classification,
            diagnostics=diagnostics
            or (f"normalized foreign outcome from {self.backend_id}",),
            payload=payload,
        )


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
