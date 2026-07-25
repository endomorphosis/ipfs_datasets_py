"""Deterministic SMT-LIB lowering and an opt-in Z3 CLI backend adapter."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any, Final

from ipfs_datasets_py.logic.backends.registry import (
    AvailabilityProbe,
    BackendRunner,
    BackendRunnerOutput,
    CallableProofBackend,
    CompiledBackendRequest,
    UnsupportedBackendRequest,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    QueryKind,
)


Z3_BACKEND_ID: Final = "z3"
Z3_BACKEND_VERSION: Final = "z3-cli-adapter/v1"
SMT_ENCODINGS: Final = frozenset({"smtlib2", "smt-lib", "smt-lib2"})
Z3_CAPABILITIES: Final = BackendCapabilities(
    logic_families=(
        "propositional",
        "quantifier_free",
        "first_order",
        "first_order_temporal",
        "smtlib2",
    ),
    query_kinds=(QueryKind.THEOREM_PROOF, QueryKind.SATISFIABILITY),
    deterministic=True,
)


def _string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
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


def _source_from_payload(request: BackendRequest) -> str:
    payload = request.payload.to_dict()
    encoding = str(payload.get("encoding") or "").lower()
    raw_source = payload.get("smtlib", payload.get("source"))
    if raw_source is not None:
        if encoding and encoding not in SMT_ENCODINGS:
            raise UnsupportedBackendRequest(
                f"z3 cannot compile encoding {encoding!r}; expected SMT-LIB2"
            )
        if not isinstance(raw_source, str) or not raw_source.strip():
            raise UnsupportedBackendRequest("SMT-LIB source must be a non-empty string")
        source = raw_source.strip()
        if "\x00" in source:
            raise UnsupportedBackendRequest("SMT-LIB source contains a NUL byte")
        if "(check-sat" not in source.lower():
            source += "\n(check-sat)"
        return source + "\n"

    formula = payload.get("goal", payload.get("formula"))
    if not isinstance(formula, str) or not formula.strip():
        raise UnsupportedBackendRequest(
            "request payload must provide SMT-LIB source or a goal/formula expression"
        )
    if encoding and encoding not in SMT_ENCODINGS | {"smt-expression/v1"}:
        raise UnsupportedBackendRequest(
            f"z3 cannot compile encoding {encoding!r}"
        )
    declarations = _string_sequence(payload.get("declarations"), "declarations")
    assumptions = _string_sequence(payload.get("assumptions"), "assumptions")
    lines = ["(set-logic ALL)", *declarations]
    lines.extend(_assertion(item) for item in assumptions)
    goal = formula.strip()
    if request.query_kind is QueryKind.THEOREM_PROOF:
        lines.append(f"(assert (not {goal}))")
    elif request.query_kind is QueryKind.SATISFIABILITY:
        lines.append(_assertion(goal))
    else:
        raise UnsupportedBackendRequest(
            f"z3 cannot compile {request.query_kind.value} requests"
        )
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


class Z3Compiler:
    """Lower the shared request payload to a deterministic Z3 SMT-LIB script."""

    backend_id = Z3_BACKEND_ID
    capabilities = Z3_CAPABILITIES

    def supports(self, request: BackendRequest) -> bool:
        return (
            isinstance(request, BackendRequest)
            and self.capabilities.supports(
                request.logic_family, request.query_kind
            )
        )

    def compile(self, request: BackendRequest) -> CompiledBackendRequest:
        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        if not self.supports(request):
            raise UnsupportedBackendRequest(
                f"z3 does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        source = _source_from_payload(request)
        options = (
            f"(set-option :timeout {request.bounds.timeout_ms})\n"
            f"(set-option :rlimit {request.bounds.max_steps})\n"
        )
        return CompiledBackendRequest(
            request_digest=request.digest,
            backend_id=self.backend_id,
            source=options + source,
            metadata={
                "compiler": Z3_BACKEND_VERSION,
                "query_kind": request.query_kind.value,
            },
        )

    __call__ = compile


def compile_request(request: BackendRequest) -> CompiledBackendRequest:
    """Compile a request using the stateless default compiler."""

    return Z3Compiler().compile(request)


def _z3_runner(
    executable: str,
) -> BackendRunner:
    def run(
        compiled: CompiledBackendRequest, request: BackendRequest
    ) -> BackendRunnerOutput:
        started = time.monotonic()
        completed = subprocess.run(
            [executable, "-in", "-smt2"],
            input=compiled.source,
            capture_output=True,
            text=True,
            check=False,
            timeout=request.bounds.timeout_ms / 1000,
        )
        return BackendRunnerOutput(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    return run


class Z3Backend(CallableProofBackend):
    """Z3 CLI adapter whose construction and capability checks are inert."""

    def __init__(
        self,
        *,
        executable: str = "z3",
        runner: BackendRunner | None = None,
        availability_probe: AvailabilityProbe | None = None,
        compiler: Callable[[BackendRequest], CompiledBackendRequest] | None = None,
    ) -> None:
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("executable must be a non-empty string")
        probe = availability_probe or (lambda: shutil.which(executable) is not None)
        super().__init__(
            backend_id=Z3_BACKEND_ID,
            backend_version=Z3_BACKEND_VERSION,
            capabilities=Z3_CAPABILITIES,
            compiler=compiler or Z3Compiler().compile,
            runner=runner or _z3_runner(executable),
            availability_probe=probe,
        )


__all__ = [
    "SMT_ENCODINGS",
    "Z3_BACKEND_ID",
    "Z3_BACKEND_VERSION",
    "Z3_CAPABILITIES",
    "Z3Backend",
    "Z3Compiler",
    "compile_request",
]
