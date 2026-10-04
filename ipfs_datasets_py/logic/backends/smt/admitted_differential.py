"""Differential composition with admitted Z3/CVC5 defaults.

The frozen differential module continues to own compilation, comparison and
evidence semantics. These helpers replace only missing backend defaults.
One cooperative deadline covers compilation and both sequential solvers. Native
phases inherit the remaining deadline; explicit backend instances retain their
caller-owned lifecycle and are checked before and after each call.
"""
from __future__ import annotations

from collections.abc import Mapping

from . import differential as _legacy
from .compiler import SmtCompilation, SmtObligation, SoftwareVerificationSMTCompiler
from ...ir_core.protocols import ExecutionBounds
from .operation_budget import (
    _Signals, current_proof_operation, proof_operation_scope, validate_operation_timeout_ms,
)


def _effective_bounds(bounds):
    if bounds is None:
        return ExecutionBounds(timeout_ms=5_000, max_steps=100_000)
    if not isinstance(bounds, ExecutionBounds):
        raise TypeError("bounds must be an ExecutionBounds")
    return bounds


def _checkpoint(phase):
    operation = current_proof_operation()
    if operation is not None:
        operation.checkpoint(phase)


class _GuardedCompiler:
    def __init__(self, compiler):
        self._compiler = compiler

    def compile(self, obligation):
        _checkpoint("before compilation")
        result = self._compiler.compile(obligation)
        _checkpoint("after compilation")
        return result


class _GuardedBackend(_legacy.SoftwareVerificationSmtBackend):
    def __init__(self, backend):
        if not isinstance(backend, _legacy.SoftwareVerificationSmtBackend):
            raise TypeError("backend must be a SoftwareVerificationSmtBackend")
        self._delegate = backend
        super().__init__(backend_id=backend.backend_id, backend_version=backend.backend_version,
            backend_interface=backend.backend_interface, compiler=backend.compiler,
            version_probe=lambda: "")

    def run_compilation(self, compilation, *, bounds):
        _checkpoint(f"before {self.backend_id}")
        outcome = self._delegate.run_compilation(compilation, bounds=bounds)
        _checkpoint(f"after {self.backend_id}")
        return outcome


def _guard_compiler(compiler):
    return _GuardedCompiler(compiler if compiler is not None else SoftwareVerificationSMTCompiler())


def _guard_backend(backend):
    return _GuardedBackend(backend)


def _admitted_defaults(z3_backend, cvc5_backend, compiler):
    if z3_backend is None:
        from ..z3 import Z3SoftwareVerificationBackend

        z3_backend = Z3SoftwareVerificationBackend(compiler=compiler)
    if cvc5_backend is None:
        from ..cvc5 import CVC5SoftwareVerificationBackend

        cvc5_backend = CVC5SoftwareVerificationBackend(compiler=compiler)
    return z3_backend, cvc5_backend


def default_z3_cvc5_verifier(
    *,
    z3_backend: _legacy.SoftwareVerificationSmtBackend | None = None,
    cvc5_backend: _legacy.SoftwareVerificationSmtBackend | None = None,
    compiler: SoftwareVerificationSMTCompiler | None = None,
    operation_timeout_ms: int | None = None,
    cancellation=None,
) -> _legacy.SmtDifferentialVerifier:
    """Construct a verifier with one cooperative budget for each verify call."""
    validate_operation_timeout_ms(operation_timeout_ms)
    z3_backend, cvc5_backend = _admitted_defaults(z3_backend, cvc5_backend, compiler)
    return _OperationBoundVerifier(
        left=z3_backend, right=cvc5_backend, compiler=compiler,
        operation_timeout_ms=operation_timeout_ms, cancellation=cancellation,
    )


class _OperationBoundVerifier(_legacy.SmtDifferentialVerifier):
    def __init__(self, *, left, right, compiler, operation_timeout_ms, cancellation):
        super().__init__(left=left, right=right, compiler=compiler)
        self._operation_timeout_ms = operation_timeout_ms
        self._operation_cancellation = cancellation

    def verify(self, obligation, *, bounds=None, operation_timeout_ms=None, cancellation=None):
        validate_operation_timeout_ms(operation_timeout_ms)
        timeout = self._operation_timeout_ms if operation_timeout_ms is None else operation_timeout_ms
        return run_z3_cvc5_differential(obligation, bounds=bounds,
            z3_backend=self.left, cvc5_backend=self.right, compiler=self._compiler,
            operation_timeout_ms=timeout, cancellation=_Signals(self._operation_cancellation, cancellation))


def run_z3_cvc5_differential(
    obligation: SmtObligation | Mapping[str, object] | SmtCompilation,
    *,
    bounds: ExecutionBounds | None = None,
    z3_backend: _legacy.SoftwareVerificationSmtBackend | None = None,
    cvc5_backend: _legacy.SoftwareVerificationSmtBackend | None = None,
    compiler: SoftwareVerificationSMTCompiler | None = None,
    operation_timeout_ms: int | None = None,
    cancellation=None,
) -> _legacy.SmtDifferentialReport:
    """Compile and compare under one deadline, withholding any late result.

The aggregate timeout defaults to bounds.timeout_ms. An explicit override may
allow several per-backend budgets; an enclosing operation still limits it.
Arbitrary caller callbacks cannot be preempted and retain their original bounds.
"""
    validate_operation_timeout_ms(operation_timeout_ms)
    bounds = _effective_bounds(bounds)
    timeout = bounds.timeout_ms if operation_timeout_ms is None else operation_timeout_ms
    with proof_operation_scope(timeout_ms=timeout, cancellation=cancellation):
        z3_backend, cvc5_backend = _admitted_defaults(z3_backend, cvc5_backend, compiler)
        return _legacy.run_z3_cvc5_differential(
            obligation, bounds=bounds, z3_backend=_guard_backend(z3_backend),
            cvc5_backend=_guard_backend(cvc5_backend),
            compiler=_guard_compiler(compiler or SoftwareVerificationSMTCompiler()),
        )


__all__ = ["default_z3_cvc5_verifier", "run_z3_cvc5_differential"]
