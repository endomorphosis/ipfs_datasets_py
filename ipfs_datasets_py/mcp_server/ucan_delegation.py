"""Profile C: UCAN-style capability delegation chains.

This module implements MCP++ Profile C (Capability Delegation) based on the
UCAN (User Controlled Authorization Networks) model.  Delegation authority is
explicit, delegable, and attenuated across multi-hop agent workflows.

Reference: docs/spec/ucan-delegation.md

Key concepts
------------
- **Capability** — what a principal ``can do`` (resource + ability).
- **Delegation** — a signed grant from *issuer* to *audience* of a set of
  capabilities, optionally bounded in time and linked to a proof bundle CID.
- **DelegationEvaluator** — validates delegation chains at execution time:
  existence, capability matching, expiry, chain length.
- **InvocationContext** — collects the proof CIDs needed to verify a specific
  tool invocation.
"""

from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "Capability",
    "Delegation",
    "DelegationEvaluator",
    "InvocationContext",
    "add_delegation",
    "get_delegation",
    "get_delegation_evaluator",
]


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------

@dataclass
class Capability:
    """Represents a single capability: a (resource, ability) pair.

    Wildcards
    ---------
    Either ``resource`` or ``ability`` may be ``"*"`` to match any value
    on that dimension.

    Examples::

        Capability("mcp://tool/load_dataset", "invoke")
        Capability("*", "read")   # read any resource
        Capability("mcp://tool/*", "*")  # any action on any mcp://tool/
    """

    resource: str
    ability: str

    def matches(self, resource: str, ability: str) -> bool:
        """Return True if this capability covers *resource*/*ability*.

        Both the stored values and the queried values are checked for
        wildcard ``"*"``.
        """
        resource_ok = (
            self.resource == "*"
            or resource == "*"
            or self.resource == resource
        )
        ability_ok = (
            self.ability == "*"
            or ability == "*"
            or self.ability == ability
        )
        return resource_ok and ability_ok

    def to_dict(self) -> Dict:
        return {"resource": self.resource, "ability": self.ability}


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------

@dataclass
class Delegation:
    """A delegation from *issuer* to *audience* of a set of capabilities.

    Parameters
    ----------
    cid:
        Content identifier of this delegation record (used as a primary key).
    issuer:
        DID / principal that is granting authority.
    audience:
        DID / principal that is receiving authority.
    capabilities:
        Non-empty list of :class:`Capability` objects granted.
    expiry:
        Unix timestamp (float) after which this delegation is invalid.
        ``None`` means no expiry.
    proof_cid:
        CID of the parent delegation (i.e., the delegation that granted
        authority to the issuer).  ``None`` for root delegations.
    signature:
        Opaque signature bytes.  In a full UCAN implementation this would be
        a real cryptographic signature; here it is stored as-is for
        future verification.
    """

    cid: str
    issuer: str
    audience: str
    capabilities: List[Capability]
    expiry: Optional[float] = None
    proof_cid: Optional[str] = None
    signature: Optional[bytes] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Return True if this delegation has passed its expiry time."""
        if self.expiry is None:
            return False
        t = now if now is not None else time.time()
        return t > self.expiry

    def has_capability(self, resource: str, ability: str) -> bool:
        """Return True if any capability in this delegation matches."""
        return any(c.matches(resource, ability) for c in self.capabilities)

    def to_dict(self) -> Dict:
        return {
            "cid": self.cid,
            "issuer": self.issuer,
            "audience": self.audience,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "expiry": self.expiry,
            "proof_cid": self.proof_cid,
        }


# ---------------------------------------------------------------------------
# DelegationEvaluator
# ---------------------------------------------------------------------------

class DelegationEvaluator:
    """Validates UCAN-style delegation chains at execution time.

    The store maps ``cid → Delegation``.  Each :class:`Delegation` may have a
    ``proof_cid`` pointing to its parent.

    Chain traversal
    ---------------
    :meth:`build_chain` follows ``proof_cid`` links until it reaches a root
    (``proof_cid is None``).  It returns the chain in *root-first* order
    (i.e., the root delegation is at index 0).

    Validation rules
    ----------------
    :meth:`can_invoke` checks:

    1. The leaf delegation exists in the store.
    2. Every delegation in the chain exists.
    3. Every delegation in the chain is not expired.
    4. At least one delegation in the chain has the requested capability.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Delegation] = {}

    # ------------------------------------------------------------------
    # Store management
    # ------------------------------------------------------------------

    def add(self, delegation: Delegation) -> None:
        """Add a delegation to the in-memory store."""
        self._store[delegation.cid] = delegation

    def get(self, cid: str) -> Optional[Delegation]:
        """Retrieve a delegation by CID, or None."""
        return self._store.get(cid)

    def remove(self, cid: str) -> bool:
        """Remove a delegation; return True if it existed."""
        if cid in self._store:
            del self._store[cid]
            return True
        return False

    def list_cids(self) -> List[str]:
        """Return all stored delegation CIDs."""
        return list(self._store.keys())

    # ------------------------------------------------------------------
    # Chain building
    # ------------------------------------------------------------------

    def build_chain(self, leaf_cid: str) -> List[Delegation]:
        """Build the delegation chain from *leaf_cid* back to the root.

        Returns the chain in **root-first** order.  Raises ``KeyError`` if any
        link in the chain is missing from the store.  Raises ``ValueError`` if
        a cycle is detected.

        Returns an empty list if *leaf_cid* is not in the store.
        """
        if leaf_cid not in self._store:
            return []

        chain: List[Delegation] = []
        seen: set = set()
        current_cid: Optional[str] = leaf_cid

        while current_cid is not None:
            if current_cid in seen:
                raise ValueError(
                    f"Cycle detected in delegation chain at CID '{current_cid}'"
                )
            seen.add(current_cid)
            delegation = self._store.get(current_cid)
            if delegation is None:
                raise KeyError(
                    f"Delegation '{current_cid}' not found in store"
                )
            chain.append(delegation)
            current_cid = delegation.proof_cid

        # chain is [leaf, ..., root]; reverse to root-first
        chain.reverse()
        return chain

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_expired(self, cid: str, now: Optional[float] = None) -> bool:
        """Return True if the delegation at *cid* is expired (or missing)."""
        d = self._store.get(cid)
        if d is None:
            return True
        return d.is_expired(now=now)

    def can_invoke(
        self,
        leaf_cid: str,
        resource: str,
        ability: str,
        actor: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Check whether the leaf delegation authorises *resource*/*ability*.

        Parameters
        ----------
        leaf_cid:
            CID of the most-derived delegation in the chain.
        resource:
            Resource identifier (e.g. ``"mcp://tool/load_dataset"``).
        ability:
            Action label (e.g. ``"invoke"``).
        actor:
            If provided, the leaf delegation's ``audience`` must match *actor*.
        now:
            Timestamp for expiry checks; defaults to ``time.time()``.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        if leaf_cid not in self._store:
            return False, f"Delegation '{leaf_cid}' not found"

        try:
            chain = self.build_chain(leaf_cid)
        except (KeyError, ValueError) as exc:
            return False, str(exc)

        if not chain:
            return False, "Empty delegation chain"

        # Actor check on the leaf (last in root-first order)
        leaf = chain[-1]
        if actor is not None and leaf.audience != actor:
            return False, (
                f"Actor '{actor}' does not match leaf audience '{leaf.audience}'"
            )

        # Expiry check across the whole chain
        t = now if now is not None else time.time()
        for d in chain:
            if d.is_expired(now=t):
                return False, f"Delegation '{d.cid}' has expired"

        # Capability check — at least one delegation must cover the request
        for d in chain:
            if d.has_capability(resource, ability):
                return True, "authorized"

        return False, (
            f"No delegation in chain grants '{ability}' on '{resource}'"
        )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_GLOBAL_EVALUATOR: Optional[DelegationEvaluator] = None


def get_delegation_evaluator() -> DelegationEvaluator:
    """Return the global :class:`DelegationEvaluator` singleton."""
    global _GLOBAL_EVALUATOR
    if _GLOBAL_EVALUATOR is None:
        _GLOBAL_EVALUATOR = DelegationEvaluator()
    return _GLOBAL_EVALUATOR


def add_delegation(delegation: Delegation) -> None:
    """Add *delegation* to the global evaluator store."""
    get_delegation_evaluator().add(delegation)


def get_delegation(cid: str) -> Optional[Delegation]:
    """Retrieve a delegation from the global store by CID."""
    return get_delegation_evaluator().get(cid)


# ---------------------------------------------------------------------------
# Invocation context
# ---------------------------------------------------------------------------

@dataclass
class InvocationContext:
    """Proof bundle gathered when a tool invocation is dispatched.

    This bundles the identifiers specified in the spec's invocation shape:
    ``intent_cid``, ``ucan_proofs``, ``policy_cid``, and ``context_cids``.
    """

    intent_cid: str
    ucan_proofs: List[str] = field(default_factory=list)
    policy_cid: Optional[str] = None
    context_cids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "intent_cid": self.intent_cid,
            "ucan_proofs": self.ucan_proofs,
            "policy_cid": self.policy_cid,
            "context_cids": self.context_cids,
        }


# ---------------------------------------------------------------------------
# DID key manager integration (session 56)
# ---------------------------------------------------------------------------

@dataclass
class DIDSignedDelegation:
    """A :class:`Delegation` signed with a DID:key Ed25519 private key.

    This bridges :mod:`ucan_delegation` (the in-process delegation chain) with
    :mod:`did_key_manager` (the Ed25519 key material), allowing delegations to
    carry a verifiable signature that can be checked without trusting the
    source.

    Args:
        delegation: The underlying :class:`Delegation`.
        signature: Hex-encoded Ed25519 signature over the delegation's
            canonical JSON representation.
        signer_did: The DID:key of the signing key (``"did:key:z6Mk..."``)
        verified: Whether :func:`verify_delegation_signature` has already
            confirmed the signature.
    """

    delegation: Delegation
    signature: str
    signer_did: str
    verified: bool = False

    def to_dict(self) -> Dict:
        d = self.delegation.to_dict()
        d["signature"] = self.signature
        d["signer_did"] = self.signer_did
        d["verified"] = self.verified
        return d


def sign_delegation(delegation: Delegation, *, key_manager: Any = None) -> "DIDSignedDelegation":
    """Sign *delegation* using an Ed25519 key from *key_manager*.

    When :mod:`did_key_manager` is available and a *key_manager* is provided
    (or the global singleton exists), the delegation's canonical JSON is
    signed with the manager's Ed25519 private key and the DID:key is stored
    in the returned :class:`DIDSignedDelegation`.

    When the key manager is unavailable (or raises), the function returns a
    :class:`DIDSignedDelegation` with an empty signature and a sentinel DID
    ``"did:key:unsigned"``.

    Args:
        delegation: The :class:`Delegation` to sign.
        key_manager: An optional :class:`~did_key_manager.DIDKeyManager`
            instance.  If *None*, the global singleton is tried.

    Returns:
        A :class:`DIDSignedDelegation` wrapping *delegation*.
    """
    import json

    payload = json.dumps(delegation.to_dict(), sort_keys=True).encode()

    mgr = key_manager
    if mgr is None:
        try:
            from .did_key_manager import get_default_manager  # noqa: PLC0415
            mgr = get_default_manager()
        except Exception:
            pass

    if mgr is None:
        return DIDSignedDelegation(
            delegation=delegation,
            signature="",
            signer_did="did:key:unsigned",
            verified=False,
        )

    try:
        sig_bytes: bytes = mgr.sign(payload)
        return DIDSignedDelegation(
            delegation=delegation,
            signature=sig_bytes.hex(),
            signer_did=getattr(mgr, "did", "did:key:unknown"),
            verified=False,
        )
    except Exception as exc:
        logger.warning("sign_delegation failed: %s", exc)
        return DIDSignedDelegation(
            delegation=delegation,
            signature="",
            signer_did="did:key:unsigned",
            verified=False,
        )


def verify_delegation_signature(
    signed: "DIDSignedDelegation",
    *,
    key_manager: Any = None,
) -> bool:
    """Verify the Ed25519 signature on *signed*.

    Re-derives the canonical JSON payload of the wrapped delegation and checks
    it against ``signed.signature`` using the key manager's ``verify``
    method.  Returns ``False`` on any error (missing manager, bad sig, etc.).

    Args:
        signed: A :class:`DIDSignedDelegation` to verify.
        key_manager: Optional :class:`~did_key_manager.DIDKeyManager`.

    Returns:
        ``True`` if the signature is valid; ``False`` otherwise.
    """
    import json

    if not signed.signature:
        return False

    payload = json.dumps(signed.delegation.to_dict(), sort_keys=True).encode()

    mgr = key_manager
    if mgr is None:
        try:
            from .did_key_manager import get_default_manager  # noqa: PLC0415
            mgr = get_default_manager()
        except Exception:
            pass

    if mgr is None:
        return False

    try:
        sig_bytes = bytes.fromhex(signed.signature)
        ok: bool = mgr.verify(payload, sig_bytes)
        return bool(ok)
    except Exception as exc:
        logger.warning("verify_delegation_signature failed: %s", exc)
        return False
