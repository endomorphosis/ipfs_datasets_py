"""XRPL validated-ledger finality policy.

On XRPL, only **validated** ledger results are treated as final for ingestion
purposes. Unvalidated (open/current) results remain provisional. Ledger
hash/index continuity anchors checkpoints; reorg depth is shallow compared
with proof-of-work chains but still modeled via the shared depth policy for
rewind coordination.
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
from .models import TxOutcome, XRPLTransaction
from .networks import XRPL_NAMESPACE, XRPLNetwork

# XRPL validated ledgers are consensus-final under normal operation. We map
# validated success to FINALIZED and keep unvalidated as PENDING/OBSERVED.
DEFAULT_XRPL_THRESHOLDS = DepthThresholds(
    confirmed=0,
    safe=0,
    finalized=0,
)
DEFAULT_MAX_REORG_DEPTH = 256


@dataclass
class XRPLFinalityPolicy:
    """Validated-ledger finality for XRPL networks behind the shared protocol."""

    network: XRPLNetwork = XRPLNetwork.MAINNET
    thresholds: DepthThresholds = field(default_factory=lambda: DEFAULT_XRPL_THRESHOLDS)
    max_reorg_depth: int = DEFAULT_MAX_REORG_DEPTH
    provider: str = "xrpl-validated-finality"

    def __post_init__(self) -> None:
        if not isinstance(self.network, XRPLNetwork):
            raise TypeError("network must be an XRPLNetwork")
        self._delegate = DepthFinalityPolicy(
            chain_namespaces=frozenset({XRPL_NAMESPACE, self.network.value}),
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

    def finality_for_transaction(self, tx: XRPLTransaction) -> Finality:
        """Map a native XRPL outcome to portable Finality.

        Only validated results may be final. Failed/unvalidated/unknown remain
        distinct and are never collapsed into a single success state.
        """

        if not isinstance(tx, XRPLTransaction):
            raise TypeError("tx must be XRPLTransaction")
        if tx.outcome is TxOutcome.VALIDATED_SUCCESS:
            return Finality.FINALIZED
        if tx.outcome is TxOutcome.VALIDATED_FAILED:
            return Finality.FAILED
        if tx.outcome is TxOutcome.UNVALIDATED:
            return Finality.PENDING
        return Finality.UNKNOWN

    def finality_for_validated(self, *, validated: bool, success: bool | None) -> Finality:
        """Map validated flag + optional success to Finality without collapsing states."""

        if not validated:
            return Finality.PENDING
        if success is True:
            return Finality.FINALIZED
        if success is False:
            return Finality.FAILED
        return Finality.UNKNOWN


__all__ = [
    "DEFAULT_MAX_REORG_DEPTH",
    "DEFAULT_XRPL_THRESHOLDS",
    "XRPLFinalityPolicy",
]
