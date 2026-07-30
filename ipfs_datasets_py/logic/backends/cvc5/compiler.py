"""Deterministic SMT-LIB lowering and cvc5 software-verification adapter.

Provides:

* :class:`CVC5Compiler` / :class:`CVC5Backend` — legacy neutral-payload CLI
  adapter used by the shared registry path;
* :class:`CVC5SoftwareVerificationBackend` — semantic-compiler-backed adapter
  (``CVC5SoftwareVerificationBackend@1``) that produces typed results with
  models, unsat cores, translation receipts, and resource bindings for
  differential verification.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, Final

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
from ipfs_datasets_py.logic.backends.smt.compiler import (
    SMT_COMPILER_VERSION,
    SmtCompilation,
    SmtObligation,
    SoftwareVerificationSMTCompiler,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    CVC5_SV_BACKEND_ID,
    CVC5_SV_BACKEND_INTERFACE,
    CVC5_SV_BACKEND_VERSION,
    AvailabilityProbe as SmtAvailabilityProbe,
    SoftwareVerificationSmtBackend,
    SmtRawSolverOutput,
    SmtSolverRunner,
    VersionProbe,
    subprocess_smt_runner,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)


CVC5_BACKEND_ID: Final = "cvc5"
CVC5_BACKEND_VERSION: Final = "cvc5-cli-adapter/v1"
CVC5_CAPABILITIES: Final = BackendCapabilities(
    logic_families=(
        "propositional",
        "quantifier_free",
        "first_order",
        "first_order_temporal",
        "smtlib2",
        "software_verification",
    ),
    query_kinds=(QueryKind.THEOREM_PROOF, QueryKind.SATISFIABILITY),
    deterministic=True,
)

CVC5_SOFTWARE_VERIFICATION_INTERFACE: Final = CVC5_SV_BACKEND_INTERFACE
CVC5_SOFTWARE_VERIFICATION_VERSION: Final = CVC5_SV_BACKEND_VERSION


class CVC5Compiler:
    """Lower a shared request payload to a deterministic cvc5 SMT-LIB script.

    Also accepts semantic-compiler obligations via
    :meth:`compile_obligation` so registry and software-verification paths
    share one deterministic SMT-LIB surface.
    """

    backend_id = CVC5_BACKEND_ID
    capabilities = CVC5_CAPABILITIES

    def __init__(
        self,
        *,
        semantic_compiler: SoftwareVerificationSMTCompiler | None = None,
    ) -> None:
        self._semantic = semantic_compiler or SoftwareVerificationSMTCompiler()

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
                f"cvc5 does not support "
                f"{request.logic_family}/{request.query_kind.value}"
            )
        payload = request.payload.to_dict()
        if "smt_compilation" in payload or "smtlib" in payload or "source" in payload:
            return compile_smtlib_request(
                request,
                backend_id=self.backend_id,
                compiler_version=CVC5_BACKEND_VERSION,
            )
        if "obligation" in payload:
            obligation = payload["obligation"]
            compilation = self._semantic.compile(obligation)
            return self._compiled_from_semantic(request, compilation)
        return compile_smtlib_request(
            request,
            backend_id=self.backend_id,
            compiler_version=CVC5_BACKEND_VERSION,
        )

    def compile_obligation(
        self,
        obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
        *,
        request: BackendRequest | None = None,
    ) -> tuple[SmtCompilation, CompiledBackendRequest | None]:
        """Lower via the shared semantic compiler; optionally bind a request."""

        if isinstance(obligation, SmtCompilation):
            compilation = obligation
        else:
            compilation = self._semantic.compile(obligation)
        if request is None:
            return compilation, None
        return compilation, self._compiled_from_semantic(request, compilation)

    def _compiled_from_semantic(
        self,
        request: BackendRequest,
        compilation: SmtCompilation,
    ) -> CompiledBackendRequest:
        return CompiledBackendRequest(
            request_digest=request.digest,
            backend_id=self.backend_id,
            source=compilation.smtlib,
            metadata=FrozenMap(
                {
                    "compiler": CVC5_BACKEND_VERSION,
                    "semantic_compiler_version": SMT_COMPILER_VERSION,
                    "compilation_id": compilation.compilation_id,
                    "script_digest": compilation.script.digest,
                    "translation_receipt_id": compilation.receipt.receipt_id,
                    "query_kind": request.query_kind.value,
                    "query_mode": compilation.query_mode.value,
                    "obligation_id": compilation.obligation_id,
                }
            ),
        )

    __call__ = compile


def compile_request(request: BackendRequest) -> CompiledBackendRequest:
    """Compile a request using the stateless default compiler."""

    return CVC5Compiler().compile(request)


def _cvc5_runner(executable: str) -> BackendRunner:
    def run(
        compiled: CompiledBackendRequest, request: BackendRequest
    ) -> BackendRunnerOutput:
        started = time.monotonic()
        completed = subprocess.run(
            [
                executable,
                "--lang=smt2",
                f"--tlimit-per={request.bounds.timeout_ms}",
                f"--rlimit={request.bounds.max_steps}",
            ],
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


class CVC5Backend(CallableProofBackend):
    """cvc5 adapter whose construction and capability checks are inert."""

    def __init__(
        self,
        *,
        executable: str = "cvc5",
        runner: BackendRunner | None = None,
        availability_probe: AvailabilityProbe | None = None,
        compiler: Callable[[BackendRequest], CompiledBackendRequest] | None = None,
    ) -> None:
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("executable must be a non-empty string")
        probe = availability_probe or (lambda: shutil.which(executable) is not None)
        super().__init__(
            backend_id=CVC5_BACKEND_ID,
            backend_version=CVC5_BACKEND_VERSION,
            capabilities=CVC5_CAPABILITIES,
            compiler=compiler or CVC5Compiler().compile,
            runner=runner or _cvc5_runner(executable),
            availability_probe=probe,
        )


def _cvc5_sv_argv(resolved: str, bounds: ExecutionBounds) -> list[str]:
    return [
        resolved,
        "--lang=smt2",
        f"--tlimit-per={bounds.timeout_ms}",
        f"--rlimit={bounds.max_steps}",
    ]


def _cvc5_software_verification_runner(executable: str) -> SmtSolverRunner:
    return subprocess_smt_runner(
        executable,
        argv_builder=_cvc5_sv_argv,
        version_argv=("--version",),
    )


class CVC5SoftwareVerificationBackend(SoftwareVerificationSmtBackend):
    """cvc5 backend for shared software-verification VCs (``@1``).

    Accepts :class:`SmtObligation` / :class:`SmtCompilation` from the shared
    semantic compiler, runs cvc5, and normalizes models / unsat cores into
    typed theorem or satisfiability results with exact translation receipts.
    """

    INTERFACE: ClassVar[str] = CVC5_SV_BACKEND_INTERFACE

    def __init__(
        self,
        *,
        executable: str = "cvc5",
        runner: SmtSolverRunner | None = None,
        availability_probe: SmtAvailabilityProbe | None = None,
        version_probe: VersionProbe | None = None,
        compiler: SoftwareVerificationSMTCompiler | None = None,
    ) -> None:
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("executable must be a non-empty string")
        exe = executable.strip()
        probe = availability_probe or (lambda: shutil.which(exe) is not None)
        super().__init__(
            backend_id=CVC5_SV_BACKEND_ID,
            backend_version=CVC5_SV_BACKEND_VERSION,
            backend_interface=CVC5_SV_BACKEND_INTERFACE,
            runner=runner or _cvc5_software_verification_runner(exe),
            availability_probe=probe,
            version_probe=version_probe,
            compiler=compiler,
            executable=exe,
        )

    def _default_runner(
        self, smtlib: str, bounds: ExecutionBounds
    ) -> SmtRawSolverOutput:
        return _cvc5_software_verification_runner(self._executable)(smtlib, bounds)


__all__ = [
    "CVC5_BACKEND_ID",
    "CVC5_BACKEND_VERSION",
    "CVC5_CAPABILITIES",
    "CVC5_SOFTWARE_VERIFICATION_INTERFACE",
    "CVC5_SOFTWARE_VERIFICATION_VERSION",
    "CVC5_SV_BACKEND_ID",
    "CVC5_SV_BACKEND_INTERFACE",
    "CVC5_SV_BACKEND_VERSION",
    "CVC5Backend",
    "CVC5Compiler",
    "CVC5SoftwareVerificationBackend",
    "SMT_ENCODINGS",
    "compile_request",
]
