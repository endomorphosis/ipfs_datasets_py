"""Bitcoin confirmation-depth finality policy.

Confirmation thresholds are configuration, not universal chain truth. The
default profile uses a conservative safe depth suitable for public-ledger
ingestion; operators may lower or raise thresholds explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..finality import (
    DepthFinalityPolicy,
    DepthThresholds,
    FinalityClassification,
    ReorgDecision,
)
from ..models import Finality
from ..protocols import Capabilities, OperationContext
from .networks import BITCOIN_NAMESPACE, BitcoinNetwork

# Defaults are policy choices, not consensus rules.
DEFAULT_BITCOIN_THRESHOLDS = DepthThresholds(
    confirmed=1,
    safe=6,
    finalized=100,
)
DEFAULT_MAX_REORG_DEPTH = 100


@dataclass
class BitcoinFinalityPolicy:
    """Depth-based finality for Bitcoin networks behind the shared protocol."""

    network: BitcoinNetwork = BitcoinNetwork.MAINNET
    thresholds: DepthThresholds = field(default_factory=lambda: DEFAULT_BITCOIN_THRESHOLDS)
    max_reorg_depth: int = DEFAULT_MAX_REORG_DEPTH
    provider: str = "bitcoin-depth-finality"

    def __post_init__(self) -> None:
        if not isinstance(self.network, BitcoinNetwork):
            raise TypeError("network must be a BitcoinNetwork")
        self._delegate = DepthFinalityPolicy(
            chain_namespaces=frozenset({BITCOIN_NAMESPACE, self.network.value}),
            thresholds=self.thresholds,
            max_reorg_depth=self.max_reorg_depth,
            provider=self.provider,
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._delegate.capabilities

    def classify(
        self,
        record: object,
        *,
        head: object,
        context: OperationContext,
    ) -> FinalityClassification:
        return self._delegate.classify(record, head=head, context=context)

    def rewind_position(
        self,
        checkpoint: object,
        *,
        observed_anchor: object,
        context: OperationContext,
    ) -> int | None:
        return self._delegate.rewind_position(
            checkpoint,
            observed_anchor=observed_anchor,
            context=context,
        )

    def evaluate_reorg(
        self,
        checkpoint: object,
        *,
        observed_anchor: object,
        context: OperationContext,
        **kwargs: Any,
    ) -> ReorgDecision:
        return self._delegate.evaluate_reorg(
            checkpoint,
            observed_anchor=observed_anchor,
            context=context,
            **kwargs,
        )

    def finality_for_confirmations(self, confirmations: int) -> Finality:
        """Map a confirmation count through the configured thresholds."""

        if (
            isinstance(confirmations, bool)
            or not isinstance(confirmations, int)
            or confirmations < 0
        ):
            raise ValueError("confirmations must be a non-negative integer")
        return self._delegate._state_for_confirmations(confirmations)  # noqa: SLF001


__all__ = [
    "DEFAULT_BITCOIN_THRESHOLDS",
    "DEFAULT_MAX_REORG_DEPTH",
    "BitcoinFinalityPolicy",
]
