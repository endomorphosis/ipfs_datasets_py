"""Wallet processor compatibility adapters.

WALPROC-G600 permits exactly one adapter to the ADR-selected generic
processor contract (``processors.core.protocol.ProcessorProtocol``).

The rejected legacy ``can_process(input_source)`` surface is intentionally
**not** exposed or registered here.
"""

from __future__ import annotations

from .processor_protocol import (
    ADAPTER_GENERIC_API,
    ADAPTER_NAME,
    LEGACY_CAN_PROCESS_WIRED,
    WalletProcessorProtocolAdapter,
)

__all__ = [
    "ADAPTER_GENERIC_API",
    "ADAPTER_NAME",
    "LEGACY_CAN_PROCESS_WIRED",
    "WalletProcessorProtocolAdapter",
]
