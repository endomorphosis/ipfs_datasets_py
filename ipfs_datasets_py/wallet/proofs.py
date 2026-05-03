"""Proof receipt helpers for wallet MVP workflows."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List

from .manifest import canonical_bytes
from .models import ProofReceipt


SIMULATED_VERIFIER_ID = "simulated-wallet-zkp-v0.1"


def create_simulated_proof_receipt(
    *,
    wallet_id: str,
    proof_type: str,
    statement: Dict[str, Any],
    public_inputs: Dict[str, Any],
    witness_record_ids: List[str],
) -> ProofReceipt:
    proof_hash = hashlib.sha256(
        canonical_bytes(
            {
                "wallet_id": wallet_id,
                "proof_type": proof_type,
                "statement": statement,
                "public_inputs": public_inputs,
                "witness_record_ids": witness_record_ids,
                "verifier_id": SIMULATED_VERIFIER_ID,
            }
        )
    ).hexdigest()
    return ProofReceipt(
        proof_id=f"proof-{uuid.uuid4().hex}",
        wallet_id=wallet_id,
        proof_type=proof_type,
        statement=statement,
        verifier_id=SIMULATED_VERIFIER_ID,
        public_inputs=public_inputs,
        proof_hash=proof_hash,
        witness_record_ids=list(witness_record_ids),
        is_simulated=True,
    )
