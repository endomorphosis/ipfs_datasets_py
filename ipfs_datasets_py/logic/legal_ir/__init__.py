"""Reviewed Legal IR adapters for the shared formalization contracts."""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORT_MODULE: Final[dict[str, str]] = {
    name: "adapter"
    for name in (
        "LEGAL_IR_ADAPTER_CONFIG_ID",
        "LEGAL_IR_ADAPTER_PRODUCER_ID",
        "LEGAL_IR_DOMAIN",
        "LEGAL_IR_FORMALIZATION_ADAPTER_VERSION",
        "LEGAL_IR_FORMALIZATION_VIEW_REGISTRY",
        "LEGAL_IR_VIEW_REGISTRY",
        "LegalIRAdapter",
        "LegalIRAdapterError",
        "LegalIRFormalizationAdapter",
        "adapt_legal_sample",
    )
}

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    """Load the deterministic Legal adapter without importing Legal runtimes."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
