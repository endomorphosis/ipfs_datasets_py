"""Source verification composition with admitted default SMT backends.

The source-to-VC translation and receipt semantics live in the source pipeline
module. This subclass supplies admitted backends at construction;
explicit caller backends and compile-only operation keep their existing roles.
One cooperative deadline covers the complete call, including every obligation.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .pipeline import (
    ContractSpec,
    PipelineError,
    SourceToVerificationPipeline as _LegacyPipeline,
    SourceToVerificationResult,
)
from .contracts import ProgramContract
from .contracts import LoopContract
from ..backends.smt.admitted_differential import _checkpoint, _guard_backend, _guard_compiler
from ..backends.smt.operation_budget import (
    _Signals, proof_operation_scope, validate_operation_timeout_ms,
)


@dataclass(frozen=True, slots=True)
class SourceToVerificationPipeline(_LegacyPipeline):
    """The source pipeline with admitted defaults for missing SMT peers."""

    operation_timeout_ms: int | None = field(default=None, kw_only=True)
    cancellation: Any = field(default=None, kw_only=True, repr=False, compare=False)

    def __post_init__(self) -> None:
        validate_operation_timeout_ms(self.operation_timeout_ms)
        _LegacyPipeline.__post_init__(self)
        if self.execute_solvers:
            if self.z3_backend is None:
                from ..backends.z3 import Z3SoftwareVerificationBackend

                object.__setattr__(self, "z3_backend", Z3SoftwareVerificationBackend(compiler=self.compiler))
            if self.cvc5_backend is None:
                from ..backends.cvc5 import CVC5SoftwareVerificationBackend

                object.__setattr__(self, "cvc5_backend", CVC5SoftwareVerificationBackend(compiler=self.compiler))

    def run(self, source: str, *, path: str = "", language: str = "",
            contracts: Sequence[ContractSpec | ProgramContract] | None = None,
            loop_contracts: Sequence[LoopContract] = (), revision: str = "workspace:local",
            mirror: bool = True,
            operation_timeout_ms: int | None = None, cancellation=None) -> SourceToVerificationResult:
        """Run under one budget and reject results returned after interruption.

Source parsing and VC generation are cooperative Python work: interruption is
checked at the next available boundary, not by terminating a Python thread.
``mirror=False`` opts out of the optional supervisor's metadata mirroring for
this call without disabling its source evidence or changing proof authority.
"""
        if type(mirror) is not bool:
            raise PipelineError("metadata mirroring must be an exact boolean")
        validate_operation_timeout_ms(operation_timeout_ms)
        timeout = self.operation_timeout_ms if operation_timeout_ms is None else operation_timeout_ms
        if timeout is None:
            timeout = self.bounds.timeout_ms
        with proof_operation_scope(timeout_ms=timeout,
                cancellation=_Signals(self.cancellation, cancellation)):
            # Every wrapper belongs to this invocation. Stored caller objects
            # remain unchanged and may be reused by concurrent operations.
            local = replace(self, compiler=_guard_compiler(self.compiler),
                z3_backend=_guard_backend(self.z3_backend) if self.execute_solvers else self.z3_backend,
                cvc5_backend=_guard_backend(self.cvc5_backend) if self.execute_solvers else self.cvc5_backend)
            return _LegacyPipeline.run(local, source, path=path, language=language,
                contracts=contracts, loop_contracts=loop_contracts, revision=revision,
                **({"mirror": False} if not mirror else {}))

    def _resolve_contracts(self, program, contracts):
        _checkpoint("before contract resolution")
        result = _LegacyPipeline._resolve_contracts(self, program, contracts)
        _checkpoint("after contract resolution")
        return result

    def _bindings(self, **kwargs):
        _checkpoint("before source bindings")
        result = _LegacyPipeline._bindings(self, **kwargs)
        _checkpoint("after source bindings")
        return result


def run_source_to_verification_pipeline(
    source: str,
    *,
    path: str = "",
    language: str = "",
    contracts: Sequence[ContractSpec | ProgramContract] | None = None,
    **kwargs: Any,
) -> SourceToVerificationResult:
    """Run the source pipeline with admitted defaults and unchanged argument roles."""
    pipeline_kwargs = {
        key: kwargs.pop(key)
        for key in (
            "compiler", "z3_backend", "cvc5_backend", "bounds",
            "fail_on_unsupported", "execute_solvers", "include_supervisor_evidence", "solver_rules",
            "operation_timeout_ms", "cancellation",
        )
        if key in kwargs
    }
    return SourceToVerificationPipeline(**pipeline_kwargs).run(
        source, path=path, language=language, contracts=contracts, **kwargs,
    )


__all__ = ["SourceToVerificationPipeline", "run_source_to_verification_pipeline"]
