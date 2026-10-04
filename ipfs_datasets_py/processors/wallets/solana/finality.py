"""Solana commitment/finality policy without confirmation-depth collapsing."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import InvalidRequestError
from ..models import Finality
from ..protocols import Capabilities, Capability, OperationContext
from .models import Commitment, SOLANA_NAMESPACE


@dataclass(frozen=True, slots=True)
class SolanaFinalityAssessment:
    state: Finality
    commitment: Commitment
    source: str = "rpc_commitment"

    def to_dict(self) -> dict[str, str]:
        return {
            "state": self.state.value,
            "commitment": self.commitment.value,
            "source": self.source,
        }


class SolanaFinalityPolicy:
    """Map each RPC commitment to a distinct portable lifecycle state."""

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider="solana-commitment-finality",
            chain_namespaces=frozenset({SOLANA_NAMESPACE}),
            features=frozenset({Capability.FINALITY, Capability.REORG_RECOVERY}),
            metadata={
                "processed": Finality.OBSERVED.value,
                "confirmed": Finality.CONFIRMED.value,
                "finalized": Finality.FINALIZED.value,
                "depth_fallback": False,
            },
        )

    @staticmethod
    def state_for(commitment: Commitment) -> Finality:
        if commitment is Commitment.PROCESSED:
            return Finality.OBSERVED
        if commitment is Commitment.CONFIRMED:
            return Finality.CONFIRMED
        if commitment is Commitment.FINALIZED:
            return Finality.FINALIZED
        raise InvalidRequestError("unknown Solana commitment")

    def classify(
        self,
        record: object,
        *,
        head: object,
        context: OperationContext,
    ) -> SolanaFinalityAssessment:
        del head
        context.check_active()
        prior = getattr(record, "finality", None)
        if prior in {Finality.ORPHANED, Finality.REVERTED, Finality.FAILED}:
            commitment = getattr(record, "commitment", Commitment.PROCESSED)
            if not isinstance(commitment, Commitment):
                commitment = Commitment.PROCESSED
            return SolanaFinalityAssessment(
                prior, commitment, source="record_correction"
            )
        commitment = getattr(record, "commitment", None)
        if commitment is None and isinstance(record, dict):
            commitment = record.get("commitment")
        try:
            normalized = (
                commitment
                if isinstance(commitment, Commitment)
                else Commitment(commitment)
            )
        except (TypeError, ValueError):
            raise InvalidRequestError(
                "Solana record must carry an explicit RPC commitment"
            ) from None
        return SolanaFinalityAssessment(self.state_for(normalized), normalized)

    @staticmethod
    def rewind_position(
        position: int,
        *,
        depth: int,
        context: OperationContext,
    ) -> int:
        context.check_active()
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 0
            or isinstance(depth, bool)
            or not isinstance(depth, int)
            or depth < 0
        ):
            raise InvalidRequestError("position and depth must be non-negative integers")
        return max(0, position - depth)


__all__ = ["SolanaFinalityAssessment", "SolanaFinalityPolicy"]
