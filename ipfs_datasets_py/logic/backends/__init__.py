"""Explicit, side-effect-free proof backend adapters."""

from .registry import (
    BackendRunnerOutput,
    CallableProofBackend,
    CompiledBackendRequest,
    ProofBackendRegistry,
    default_backend_registry,
)

__all__ = [
    "BackendRunnerOutput",
    "CallableProofBackend",
    "CompiledBackendRequest",
    "ProofBackendRegistry",
    "default_backend_registry",
]
