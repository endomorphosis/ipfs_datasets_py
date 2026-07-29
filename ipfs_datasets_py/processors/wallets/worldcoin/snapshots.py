"""Compatibility snapshot hooks for reusable World ID state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ....wallet.models import ProofReceipt
from .bindings import WorldIdBindingStore
from .challenges import WorldIdChallengeStore


WORLD_ID_STATE_SNAPSHOT_VERSION = 1


def export_world_id_state(
    bindings: WorldIdBindingStore,
    *,
    wallet_id: str | None = None,
    challenges: WorldIdChallengeStore | None = None,
    proofs: Mapping[str, ProofReceipt] | None = None,
) -> dict[str, Any]:
    binding_state = bindings.snapshot(wallet_id=wallet_id)
    selected_ids = {item["binding_id"] for item in binding_state["bindings"]}
    proof_items = []
    for proof in (proofs or {}).values():
        if proof.proof_type != "world_id_proof_of_human":
            continue
        if wallet_id is not None and proof.wallet_id != wallet_id:
            continue
        binding_id = str(proof.public_inputs.get("binding_id") or "")
        if binding_id and binding_id not in selected_ids:
            continue
        proof_items.append(proof.to_dict())
    return {
        "version": WORLD_ID_STATE_SNAPSHOT_VERSION,
        "bindings": binding_state,
        "challenges": challenges.snapshot() if challenges is not None else None,
        "proofs": sorted(proof_items, key=lambda item: item["proof_id"]),
    }


def import_world_id_state(
    snapshot: Mapping[str, Any],
    bindings: WorldIdBindingStore,
    *,
    challenges: WorldIdChallengeStore | None = None,
    proofs: dict[str, ProofReceipt] | None = None,
) -> None:
    """Load the new state envelope or the legacy top-level snapshot shape."""

    state = snapshot.get("world_id_state")
    # DataWalletService historically used the presence/absence of the
    # top-level list as its compatibility contract. Preserve that behavior
    # for old wallet snapshots while allowing state-only processor snapshots.
    legacy_wallet_snapshot = "wallet" in snapshot
    if isinstance(state, Mapping) and (not legacy_wallet_snapshot or "world_id_bindings" in snapshot):
        binding_state = state.get("bindings")
        if isinstance(binding_state, Mapping):
            bindings.restore(binding_state)
        if challenges is not None and isinstance(state.get("challenges"), Mapping):
            challenges.restore(state["challenges"])
        proof_items = state.get("proofs", [])
    else:
        bindings.restore({"world_id_bindings": snapshot.get("world_id_bindings", [])})
        proof_items = []
    if proofs is not None:
        for item in proof_items:
            if isinstance(item, Mapping):
                receipt = ProofReceipt(**dict(item))
                proofs[receipt.proof_id] = receipt


__all__ = [
    "WORLD_ID_STATE_SNAPSHOT_VERSION",
    "export_world_id_state",
    "import_world_id_state",
]
