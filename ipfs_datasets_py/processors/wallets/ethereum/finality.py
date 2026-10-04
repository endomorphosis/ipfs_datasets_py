"""Ethereum finality labels and reorganization replay policy."""

from __future__ import annotations

from dataclasses import dataclass

from ..finality import (
    DepthFinalityPolicy,
    DepthThresholds,
    FinalityClassification,
)
from ..models import Finality
from ..protocols import OperationContext
from .rpc import EVM_NAMESPACE, EvmHead, parse_quantity


@dataclass(frozen=True, slots=True)
class EthereumFinalityAssessment:
    """Portable state with evidence for explicit-tag or depth fallback."""

    state: Finality
    confirmations: int
    source: str
    explicit_tags_supported: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "confirmations": self.confirmations,
            "source": self.source,
            "explicit_tags_supported": self.explicit_tags_supported,
        }


class EthereumFinalityPolicy(DepthFinalityPolicy):
    """Prefer ``safe``/``finalized`` tags; use explicit depth fallback."""

    def __init__(
        self,
        *,
        confirmed_depth: int = 1,
        safe_fallback_depth: int = 12,
        finalized_fallback_depth: int | None = 64,
        max_reorg_depth: int = 64,
    ) -> None:
        super().__init__(
            chain_namespaces=frozenset({EVM_NAMESPACE}),
            thresholds=DepthThresholds(
                confirmed=confirmed_depth,
                safe=safe_fallback_depth,
                finalized=finalized_fallback_depth,
            ),
            max_reorg_depth=max_reorg_depth,
            provider="ethereum-finality",
        )

    def classify(
        self,
        record: object,
        *,
        head: object,
        context: OperationContext,
    ) -> EthereumFinalityAssessment:
        context.check_active()
        if not isinstance(head, EvmHead):
            fallback = super().classify(record, head=head, context=context)
            assert isinstance(fallback, FinalityClassification)
            return EthereumFinalityAssessment(
                state=fallback.state,
                confirmations=fallback.confirmations,
                source="confirmation_fallback",
                explicit_tags_supported=False,
            )

        sequence = getattr(getattr(record, "ledger_position", None), "sequence", None)
        if sequence is None and isinstance(record, dict):
            position = record.get("ledger_position") or {}
            sequence = position.get("sequence") if isinstance(position, dict) else None
        latest_number = head.sequence
        confirmations = (
            max(0, latest_number - sequence)
            if isinstance(sequence, int)
            else 0
        )
        prior = getattr(record, "finality", None)
        if prior in {Finality.ORPHANED, Finality.REVERTED, Finality.FAILED}:
            return EthereumFinalityAssessment(
                state=prior,
                confirmations=confirmations,
                source="record_correction",
                explicit_tags_supported=head.explicit_tags_supported,
            )

        if head.explicit_tags_supported and isinstance(sequence, int):
            if head.finalized is not None:
                finalized_number = parse_quantity(
                    head.finalized.get("number"), field="finalized.number"
                )
                if sequence <= finalized_number:
                    return EthereumFinalityAssessment(
                        Finality.FINALIZED,
                        confirmations,
                        "finalized_tag",
                        True,
                    )
            if head.safe is not None:
                safe_number = parse_quantity(head.safe.get("number"), field="safe.number")
                if sequence <= safe_number:
                    return EthereumFinalityAssessment(
                        Finality.SAFE,
                        confirmations,
                        "safe_tag",
                        True,
                    )
            state = (
                Finality.CONFIRMED
                if confirmations >= self.thresholds.confirmed
                else Finality.OBSERVED
            )
            return EthereumFinalityAssessment(
                state,
                confirmations,
                "latest_tag",
                True,
            )

        fallback = super().classify(
            record,
            head={"sequence": latest_number, "hash": head.hash},
            context=context,
        )
        return EthereumFinalityAssessment(
            fallback.state,
            fallback.confirmations,
            "confirmation_fallback",
            False,
        )


__all__ = ["EthereumFinalityAssessment", "EthereumFinalityPolicy"]
