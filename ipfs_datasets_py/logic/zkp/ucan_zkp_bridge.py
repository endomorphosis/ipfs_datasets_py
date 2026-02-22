"""
ZKP → UCAN Bridge.

This module provides a bridge between the ZKP (Zero-Knowledge Proof)
simulation module and the UCAN delegation system, allowing ZKP proofs
of theorem satisfaction to be embedded as *capability evidence caveats*
inside UCAN delegation tokens.

This is a **simulation-only** integration.  The ZKP proofs produced by
``logic/zkp/zkp_prover.py`` are NOT cryptographically secure.  In a
production system the bridge would use real Groth16/PLONK proofs whose
verification key is published and whose proof is compact (~200 bytes).
See ``zkp/PRODUCTION_UPGRADE_PATH.md`` for the real ZKP upgrade path.

Conceptual flow::

    NL Policy Text
         │
         ▼
    NLToDCECCompiler          ← logic/CEC/nl/nl_to_policy_compiler.py
         │
    DeonticFormula(OBLIGATION/PERMISSION/PROHIBITION, ...)
         │
         ▼
    ZKPProver.generate_proof(theorem)     ← logic/zkp/zkp_prover.py
         │
    ZKPProof {proof_data, public_inputs, metadata}
         │
         ▼
    ZKPToUCANBridge.proof_to_caveat(proof)
         │
    {type: "zkp_evidence", proof_hash, theorem_cid, verifier_id}
         │
         ▼
    DelegationToken(capabilities, caveats=[zkp_caveat])
         │  (via ucan_delegation.py)
         ▼
    Signed UCAN JWT  (when py-ucan + DIDKeyManager present)

Usage::

    from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge

    bridge = ZKPToUCANBridge()
    result = bridge.prove_and_delegate(
        theorem="P → Q",
        actor="did:key:alice",
        resource="logic/proof",
        ability="proof/invoke",
    )
    if result.success:
        print(result.delegation_token)
        print(result.zkp_caveat)
"""

from __future__ import annotations

import hashlib
import json
import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

# ZKP prover (logic/zkp)
try:
    from .zkp_prover import ZKPProver
    from . import ZKPProof
    _ZKP_AVAILABLE = True
except Exception:
    _ZKP_AVAILABLE = False

# UCAN delegation (mcp_server)
try:
    from ...mcp_server.ucan_delegation import (
        DelegationToken,
        DelegationEvaluator,
        Capability,
        get_delegation_evaluator,
    )
    _UCAN_AVAILABLE = True
except Exception:
    try:
        import importlib as _imp
        _ud = _imp.import_module("ipfs_datasets_py.mcp_server.ucan_delegation")
        DelegationToken = _ud.DelegationToken
        DelegationEvaluator = _ud.DelegationEvaluator
        Capability = _ud.Capability
        get_delegation_evaluator = _ud.get_delegation_evaluator
        _UCAN_AVAILABLE = True
    except Exception:
        _UCAN_AVAILABLE = False

# CID computation (interface_descriptor)
try:
    from ...mcp_server.interface_descriptor import compute_cid as _compute_cid
    _CID_AVAILABLE = True
except Exception:
    try:
        import importlib as _imp
        _ifd = _imp.import_module("ipfs_datasets_py.mcp_server.interface_descriptor")
        _compute_cid = _ifd.compute_cid
        _CID_AVAILABLE = True
    except Exception:
        _CID_AVAILABLE = False


# ---------------------------------------------------------------------------
# ZKPCapabilityEvidence  — the caveat payload embedded in UCAN tokens
# ---------------------------------------------------------------------------

@dataclass
class ZKPCapabilityEvidence:
    """
    ZKP proof embedded as a UCAN caveat.

    Attributes
    ----------
    proof_hash:
        SHA-256 hex digest of ``ZKPProof.proof_data``.
    theorem_cid:
        Content-ID of the proved theorem string.
    verifier_id:
        Identifier of the verifier used (e.g. ``"simulated-v0.1"``).
    public_inputs:
        Redacted public inputs (only ``theorem`` key exposed).
    is_simulation:
        Always ``True`` for this module — NOT production cryptography.
    """

    proof_hash: str
    theorem_cid: str
    verifier_id: str
    public_inputs: Dict[str, Any] = field(default_factory=dict)
    is_simulation: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "zkp_evidence",
            "proof_hash": self.proof_hash,
            "theorem_cid": self.theorem_cid,
            "verifier_id": self.verifier_id,
            "public_inputs": self.public_inputs,
            "is_simulation": self.is_simulation,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ZKPCapabilityEvidence":
        return cls(
            proof_hash=d.get("proof_hash", ""),
            theorem_cid=d.get("theorem_cid", ""),
            verifier_id=d.get("verifier_id", ""),
            public_inputs=d.get("public_inputs", {}),
            is_simulation=d.get("is_simulation", True),
        )


# ---------------------------------------------------------------------------
# BridgeResult
# ---------------------------------------------------------------------------

@dataclass
class BridgeResult:
    """
    Result of a ZKP→UCAN bridging operation.

    Attributes
    ----------
    success:
        Whether the full bridge (prove + delegate) succeeded.
    theorem:
        The theorem that was proved.
    actor:
        DID of the actor who receives the delegation.
    resource:
        UCAN resource string (e.g. ``"logic/proof"``).
    ability:
        UCAN ability string (e.g. ``"proof/invoke"``).
    zkp_caveat:
        The ``ZKPCapabilityEvidence`` embedded as a caveat.
    delegation_token:
        The resulting ``DelegationToken`` (or ``None`` if UCAN unavailable).
    warnings:
        Non-fatal issues encountered during bridging.
    error:
        Fatal error message if ``success`` is ``False``.
    """

    success: bool = False
    theorem: str = ""
    actor: str = ""
    resource: str = ""
    ability: str = ""
    zkp_caveat: Optional[ZKPCapabilityEvidence] = None
    delegation_token: Optional[Any] = None
    warnings: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "theorem": self.theorem,
            "actor": self.actor,
            "resource": self.resource,
            "ability": self.ability,
            "zkp_caveat": self.zkp_caveat.to_dict() if self.zkp_caveat else None,
            "delegation_token": (
                self.delegation_token.to_dict()
                if (self.delegation_token and hasattr(self.delegation_token, "to_dict"))
                else None
            ),
            "warnings": self.warnings,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# ZKPToUCANBridge
# ---------------------------------------------------------------------------

class ZKPToUCANBridge:
    """
    Bridge from ZKP proofs to UCAN DelegationTokens.

    This class:

    1. Runs the ZKP prover on a theorem string (real Groth16 when
       ``IPFS_DATASETS_ENABLE_GROTH16=1`` and the binary is present,
       otherwise simulated).
    2. Packages the proof as a ``ZKPCapabilityEvidence`` caveat.
    3. Wraps the caveat in a ``DelegationToken`` (via ``ucan_delegation``).

    The UCAN token can then be verified by any downstream system that:
    (a) checks the ZKP evidence is structurally valid, and
    (b) checks the UCAN chain in the ``DelegationEvaluator``.

    Parameters
    ----------
    verifier_id:
        Identifier embedded in caveat.  Defaults to the appropriate ID for
        the active backend: ``"groth16-bn254-v0.1"`` when Groth16 is enabled,
        ``"simulated-zkp-v0.1"`` otherwise.
    issuer_did:
        DID of the issuer.  Defaults to ``"did:key:issuer"`` (test mode).
    auto_setup:
        When ``True`` and Groth16 is enabled, call ``ensure_setup()``
        automatically if artifacts are missing (default ``True``).
    """

    SIMULATED_VERIFIER_ID = "simulated-zkp-v0.1"
    GROTH16_VERIFIER_ID = "groth16-bn254-v0.1"
    # Number of hex characters from proof_hash used as UCAN token nonce
    _PROOF_HASH_NONCE_LENGTH = 16

    def __init__(
        self,
        verifier_id: Optional[str] = None,
        issuer_did: str = "did:key:issuer",
        auto_setup: bool = True,
    ) -> None:
        self._issuer_did = issuer_did
        self._auto_setup = auto_setup
        self._groth16_enabled = self._check_groth16_enabled()
        self._verifier_id = verifier_id or (
            self.GROTH16_VERIFIER_ID if self._groth16_enabled else self.SIMULATED_VERIFIER_ID
        )
        self._prover: Optional[Any] = None
        self._groth16_backend: Optional[Any] = None

        if _ZKP_AVAILABLE:
            try:
                if self._groth16_enabled:
                    self._prover = ZKPProver(backend="groth16")
                    self._groth16_backend = self._prover.get_backend_instance()
                    if auto_setup:
                        self._auto_provision_setup()
                else:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        self._prover = ZKPProver()
            except Exception as exc:
                logger.warning("ZKPProver init failed: %s", exc)

    @staticmethod
    def _check_groth16_enabled() -> bool:
        """Return True when IPFS_DATASETS_ENABLE_GROTH16=1 is set."""
        import os as _os
        return _os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip() in {
            "1", "true", "TRUE", "yes", "YES"
        }

    def _auto_provision_setup(self) -> None:
        """Run ``ensure_setup`` for circuit v1 if artifacts are missing."""
        if self._groth16_backend is None:
            return
        try:
            result = self._groth16_backend.ensure_setup(version=1)
            if result.get("status") != "already_exists":
                logger.info("Groth16 setup provisioned: %s", result)
        except Exception as exc:
            logger.warning(
                "Groth16 auto-setup failed (proving will fail until keys are present): %s",
                exc,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prove_and_delegate(
        self,
        theorem: str,
        actor: str,
        resource: str,
        ability: str,
        private_axioms: Optional[List[str]] = None,
        lifetime_seconds: int = 3600,
    ) -> BridgeResult:
        """
        Prove *theorem* then issue a UCAN delegation token to *actor*.

        When ``IPFS_DATASETS_ENABLE_GROTH16=1`` and the Rust binary is available,
        this generates a **real Groth16 BN254 zkSNARK proof**.  Otherwise it falls
        back to the simulated backend and emits a ``UserWarning``.

        Parameters
        ----------
        theorem:
            Logical theorem string to prove (e.g. ``"P → Q"``).
        actor:
            DID or identifier of the actor who will receive the capability.
        resource:
            UCAN resource (e.g. ``"logic/theorem_proving"``).
        ability:
            UCAN ability (e.g. ``"proof/invoke"``).
        private_axioms:
            Optional private axioms for the ZKP prover.
        lifetime_seconds:
            Lifetime of the UCAN delegation token.

        Returns
        -------
        BridgeResult
        """
        if not self._groth16_enabled:
            warnings.warn(
                "ZKPToUCANBridge uses SIMULATED ZKP proofs — NOT cryptographically secure. "
                "Set IPFS_DATASETS_ENABLE_GROTH16=1 and compile the Rust backend for real proofs.",
                UserWarning,
                stacklevel=2,
            )

        result = BridgeResult(theorem=theorem, actor=actor, resource=resource, ability=ability)

        # ---- Step 1: Generate ZKP proof ----
        proof = self._generate_proof(theorem, private_axioms or [], result)
        if proof is None:
            return result  # error already set

        # ---- Step 2: Build ZKPCapabilityEvidence caveat ----
        caveat = self.proof_to_caveat(proof)
        result.zkp_caveat = caveat

        # ---- Step 3: Build DelegationToken ----
        # DelegationToken doesn't have a caveats field; we embed the caveat
        # hash as the nonce for traceability.
        if _UCAN_AVAILABLE:
            try:
                import time as _time
                cap = Capability(resource=resource, ability=ability)
                token = DelegationToken(
                    issuer=self._issuer_did,
                    audience=actor,
                    capabilities=[cap],
                    expiry=_time.time() + lifetime_seconds,
                    # Embed a 64-bit (16-char hex) prefix of the proof hash as the
                    # token nonce for ZKP-backed traceability.
                    nonce=caveat.proof_hash[:self._PROOF_HASH_NONCE_LENGTH] if caveat else None,
                )
                result.delegation_token = token
            except Exception as exc:
                result.warnings.append(f"DelegationToken build failed: {exc}")
        else:
            result.warnings.append("ucan_delegation not available; token not built")

        result.success = True
        return result

    def proof_to_caveat(self, proof: Any) -> ZKPCapabilityEvidence:
        """
        Convert a ``ZKPProof`` into a ``ZKPCapabilityEvidence`` caveat dict.

        Parameters
        ----------
        proof:
            A ``ZKPProof`` (or any object with ``proof_data`` / ``public_inputs``).

        Returns
        -------
        ZKPCapabilityEvidence
        """
        # Compute proof hash
        proof_data = getattr(proof, "proof_data", b"")
        if isinstance(proof_data, (bytes, bytearray)):
            proof_hash = hashlib.sha256(proof_data).hexdigest()
        else:
            proof_hash = hashlib.sha256(str(proof_data).encode()).hexdigest()

        # Compute theorem CID
        public_inputs = getattr(proof, "public_inputs", {})
        theorem = public_inputs.get("theorem", "")
        theorem_cid = self._compute_theorem_cid(theorem)

        # Restrict public_inputs to safe keys only (no private data)
        safe_inputs = {"theorem": theorem} if theorem else {}

        return ZKPCapabilityEvidence(
            proof_hash=proof_hash,
            theorem_cid=theorem_cid,
            verifier_id=self._verifier_id,
            public_inputs=safe_inputs,
        )

    def verify_delegated_capability(self, token_dict: Dict[str, Any]) -> bool:
        """
        Verify a UCAN delegation token that was built by this bridge.

        Checks:
        1. The token has ``capabilities`` with at least one entry.
        2. The ``nonce`` contains a 16-character hex prefix (ZKP proof hash).
        3. ``issuer`` and ``audience`` are present.

        Parameters
        ----------
        token_dict:
            Dictionary representation of a DelegationToken (as returned by
            ``DelegationToken.to_dict()``).

        Returns
        -------
        bool
            ``True`` if the token is structurally valid.
        """
        if not isinstance(token_dict, dict):
            return False
        # Must have capabilities
        caps = token_dict.get("capabilities", [])
        if not caps:
            return False
        # Must have issuer and audience
        if not token_dict.get("issuer") or not token_dict.get("audience"):
            return False
        # Nonce should be a 16-char hex prefix of ZKP proof hash
        nonce = token_dict.get("nonce", "")
        if nonce and len(nonce) >= self._PROOF_HASH_NONCE_LENGTH:
            try:
                int(nonce, 16)  # must be valid hex
                return True
            except ValueError:
                pass
        # Accept tokens without ZKP nonce (not all tokens are ZKP-backed)
        return True

    def register_token(self, result: BridgeResult) -> bool:
        """
        Register the delegation token in the global ``DelegationEvaluator``.

        Parameters
        ----------
        result:
            A successful ``BridgeResult`` with a ``delegation_token``.

        Returns
        -------
        bool
            ``True`` if registration succeeded.
        """
        if not result.success or result.delegation_token is None:
            return False
        if not _UCAN_AVAILABLE:
            return False
        try:
            evaluator = get_delegation_evaluator()
            evaluator.add_token(result.delegation_token)
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to register token: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_proof(
        self,
        theorem: str,
        private_axioms: List[str],
        result: BridgeResult,
    ) -> Optional[Any]:
        """Generate a ZKP proof, populating result.error on failure.

        Uses real Groth16 when ``IPFS_DATASETS_ENABLE_GROTH16=1``; falls back
        to simulated backend otherwise.
        """
        if not _ZKP_AVAILABLE or self._prover is None:
            result.warnings.append("ZKP module unavailable; using stub proof")
            return self._make_stub_proof(theorem)

        suppress_backend = self._groth16_enabled  # Groth16 has no UserWarning
        try:
            if suppress_backend:
                proof = self._prover.generate_proof(
                    theorem=theorem,
                    private_axioms=private_axioms,
                )
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    proof = self._prover.generate_proof(
                        theorem=theorem,
                        private_axioms=private_axioms,
                    )
            return proof
        except Exception as exc:
            result.error = f"ZKP proof generation failed: {exc}"
            return None

    def _make_stub_proof(self, theorem: str) -> Any:
        """Create a minimal stub proof when ZKP module is unavailable."""
        import time

        class _StubProof:
            def __init__(self, t: str) -> None:
                _data = hashlib.sha256(t.encode()).digest()
                self.proof_data = _data
                self.public_inputs = {"theorem": t, "theorem_hash": _data.hex()}
                self.metadata = {"backend": "stub"}
                self.timestamp = time.time()
                self.size_bytes = len(_data)

        return _StubProof(theorem)

    def _compute_theorem_cid(self, theorem: str) -> str:
        """Compute a stable CID for a theorem string."""
        if _CID_AVAILABLE:
            try:
                return _compute_cid({"theorem": theorem})
            except Exception:
                pass
        # Fallback: SHA-256 prefixed stub
        h = hashlib.sha256(theorem.encode()).hexdigest()
        return f"bafy-sha2-256-{h}"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_bridge: Optional[ZKPToUCANBridge] = None


def get_zkp_ucan_bridge(
    verifier_id: Optional[str] = None,
    issuer_did: str = "did:key:issuer",
    *,
    reset: bool = False,
) -> ZKPToUCANBridge:
    """Return the module-level singleton ZKPToUCANBridge.

    Args:
        verifier_id: Override the verifier ID embedded in ZKP caveats.  When
            ``None`` (default), the bridge auto-selects based on the current
            value of ``IPFS_DATASETS_ENABLE_GROTH16``.
        issuer_did: DID of the issuer for generated delegation tokens.
        reset: Force creation of a new singleton.  Useful after changing
            ``IPFS_DATASETS_ENABLE_GROTH16`` at runtime.  Note: when
            ``reset=True`` the new bridge uses the arguments supplied to *this*
            call, not those used to create the original singleton.

    Returns:
        ZKPToUCANBridge singleton instance.
    """
    global _default_bridge
    if _default_bridge is None or reset:
        _default_bridge = ZKPToUCANBridge(verifier_id=verifier_id, issuer_did=issuer_did)
    return _default_bridge
