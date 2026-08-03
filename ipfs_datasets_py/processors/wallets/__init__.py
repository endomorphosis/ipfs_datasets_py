"""Multi-chain wallet processors — lightweight package root (WALPROC-G600).

Importing this package does **not**:

* load optional chain SDKs or extras;
* open network sockets;
* resolve secrets;
* auto-install dependencies; or
* register wallet processors into either generic processor registry.

Lazy construction lives in :mod:`.registry`.  Exactly one generic-protocol
adapter is available under :mod:`.adapters.processor_protocol` (core
``ProcessorProtocol`` only; the legacy ``can_process`` surface is not wired).
"""

from __future__ import annotations

from typing import Any

from .errors import (
    CheckpointError,
    DatasetSinkError,
    DeadlineExceededError,
    ExportError,
    InvalidRequestError,
    NormalizationError,
    OperationCancelledError,
    ProviderError,
    ResourceLimitError,
    SecretResolutionError,
    UnsupportedCapabilityError,
    WalletProcessorError,
)
from .protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RequestLimits,
)
from .registry import (
    AmbiguousNetworkError,
    OptionalDependencyError,
    ProcessorFamilySpec,
    UnknownProcessorError,
    WalletProcessorRegistry,
    default_registry,
    get_wallet_processor,
    reset_default_registry,
)

__all__ = [
    # Errors
    "AmbiguousNetworkError",
    "CheckpointError",
    "DatasetSinkError",
    "DeadlineExceededError",
    "ExportError",
    "InvalidRequestError",
    "NormalizationError",
    "OperationCancelledError",
    "OptionalDependencyError",
    "ProviderError",
    "ResourceLimitError",
    "SecretResolutionError",
    "UnknownProcessorError",
    "UnsupportedCapabilityError",
    "WalletProcessorError",
    # Protocols (dependency-light)
    "BoundedRequest",
    "Capabilities",
    "Capability",
    "OperationContext",
    "RequestLimits",
    # Registry / factory
    "ProcessorFamilySpec",
    "WalletProcessorRegistry",
    "default_registry",
    "get_wallet_processor",
    "reset_default_registry",
]

# Submodules intentionally omitted from eager imports so chain packages stay
# lazy.  ``__getattr__`` provides discoverable attribute access without paying
# import cost at package load time.
_LAZY_SUBMODULES = frozenset(
    {
        "adapters",
        "bitcoin",
        "canonical",
        "checkpoints",
        "errors",
        "ethereum",
        "export",
        "finality",
        "models",
        "pipeline",
        "protocols",
        "providers",
        "registry",
        "security",
        "solana",
        "storage",
        "worldcoin",
        "xaman",
        "xrpl",
    }
)


def __getattr__(name: str) -> Any:
    if name in _LAZY_SUBMODULES:
        import importlib

        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_LAZY_SUBMODULES) | set(globals()))
