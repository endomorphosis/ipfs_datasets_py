"""Deterministic SMT-LIB lowering and an opt-in Z3 CLI adapter."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Final

from ipfs_datasets_py.logic.backends.registry import (
    AvailabilityProbe,
    BackendRunner,
    BackendRunnerOutput,
    CallableProofBackend,
    CompiledBackendRequest,
    SMT_ENCODINGS,
    UnsupportedBackendRequest,
    compile_smtlib_request,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    QueryKind,
)


Z3_BACKEND_ID: Final = "z3"
Z3_BACKEND_VERSION: Final = "z3-cli-adapter/v1"
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


class Z3Compiler:
    """Lower a shared request payload to a deterministic Z3 SMT-LIB script."""

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
                f"z3 does not support "
                f"{request.logic_family}/{request.query_kind.value}"
            )
        return compile_smtlib_request(
            request,
            backend_id=self.backend_id,
            compiler_version=Z3_BACKEND_VERSION,
            prefix=(
                f"(set-option :timeout {request.bounds.timeout_ms})",
                f"(set-option :rlimit {request.bounds.max_steps})",
            ),
        )

    __call__ = compile


def compile_request(request: BackendRequest) -> CompiledBackendRequest:
    """Compile a request using the stateless default compiler."""

    return Z3Compiler().compile(request)


def _z3_runner(executable: str) -> BackendRunner:
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
    """Z3 adapter whose construction and capability checks are inert."""

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
