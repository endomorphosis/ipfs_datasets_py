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
    # Phase H (session 57)
    "RevocationList",
    "can_invoke_with_revocation",
    # Phase I (session 57)
    "DelegationStore",
    # Session 56
    "DIDSignedDelegation",
    "sign_delegation",
    "verify_delegation_signature",
    # Session 58
    "DelegationManager",
    "get_delegation_manager",
    "record_delegation_metrics",
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


# ---------------------------------------------------------------------------
# Phase H — Revocation list (session 57)
# ---------------------------------------------------------------------------

class RevocationList:
    """Tracks revoked delegation CIDs to prevent use in chain evaluation.

    Revoked CIDs are stored in a ``set`` for O(1) lookup.  This is
    intentionally a simple in-process store; persistence is the caller's
    responsibility (e.g., save :meth:`to_list` to a secrets vault).

    Usage::

        revlist = RevocationList()
        revlist.revoke("cid-compromised")
        assert revlist.is_revoked("cid-compromised")

        # Revoke an entire chain at once
        revlist.revoke_chain("leaf-cid", evaluator)
    """

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, cid: str) -> None:
        """Mark *cid* as revoked."""
        self._revoked.add(cid)

    def is_revoked(self, cid: str) -> bool:
        """Return *True* if *cid* has been revoked."""
        return cid in self._revoked

    def revoke_chain(
        self,
        root_cid: str,
        evaluator: "DelegationEvaluator",
    ) -> int:
        """Revoke *root_cid* and every delegation reachable from it.

        Uses :meth:`DelegationEvaluator.build_chain` to follow ``proof_cid``
        links.  CIDs already in the revocation list are counted but not
        double-added.

        Returns:
            Number of **newly** revoked CIDs (≥ 0).
        """
        try:
            chain = evaluator.build_chain(root_cid)
        except Exception:
            chain = []
        count = 0
        for delegation in chain:
            if delegation.cid not in self._revoked:
                self._revoked.add(delegation.cid)
                count += 1
        return count

    def clear(self) -> None:
        """Remove all revocations."""
        self._revoked.clear()

    def to_list(self) -> List[str]:
        """Return a sorted list of revoked CIDs."""
        return sorted(self._revoked)

    def __len__(self) -> int:
        return len(self._revoked)

    def __contains__(self, cid: str) -> bool:
        return cid in self._revoked

    def save(self, path: str) -> None:
        """Persist revoked CIDs to a JSON file at *path*.

        Creates parent directories if necessary.

        Args:
            path: Filesystem path for the JSON revocation file.
        """
        import json as _json
        import os as _os

        parent = _os.path.dirname(path)
        if parent:
            _os.makedirs(parent, exist_ok=True)
        data: Dict[str, Any] = {"revoked": self.to_list()}
        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(data, fh, indent=2)
        logger.debug("Saved %d revoked CIDs to %s", len(self._revoked), path)

    def load(self, path: str) -> int:
        """Load revoked CIDs from a JSON file at *path*.

        Missing or unreadable files return 0 without raising.

        Args:
            path: Filesystem path of the JSON revocation file.

        Returns:
            Number of **newly** loaded CIDs (already-present CIDs are skipped).
        """
        import json as _json

        try:
            with open(path, encoding="utf-8") as fh:
                data = _json.load(fh)
        except FileNotFoundError:
            logger.debug("Revocation list file not found: %s", path)
            return 0
        except (OSError, ValueError) as exc:
            logger.warning("Could not read revocation list %s: %s", path, exc)
            return 0

        revoked = data.get("revoked", [])
        count = 0
        for cid in revoked:
            if isinstance(cid, str) and cid not in self._revoked:
                self._revoked.add(cid)
                count += 1
        logger.debug("Loaded %d new revoked CIDs from %s", count, path)
        return count


def can_invoke_with_revocation(
    leaf_cid: str,
    tool: str,
    actor: str,
    *,
    evaluator: Optional["DelegationEvaluator"] = None,
    revocation_list: Optional["RevocationList"] = None,
) -> Tuple[bool, str]:
    """Check whether *actor* can invoke *tool* via *leaf_cid*, respecting revocations.

    Like :meth:`DelegationEvaluator.can_invoke` but checks every CID in the
    chain against *revocation_list* before performing the capability check.
    This allows individual delegations to be revoked without rebuilding the
    entire chain.

    Args:
        leaf_cid: The leaf delegation CID to check.
        tool: The tool name / resource / ability to authorise.
        actor: The actor requesting the invocation.
        evaluator: :class:`DelegationEvaluator` to use.  Defaults to the
            global singleton.
        revocation_list: :class:`RevocationList` to check against.  If *None*,
            no revocation check is performed.

    Returns:
        ``(authorized, reason)`` tuple.  *authorized* is ``True`` only when
        the delegation chain is valid **and** no CID is revoked.
    """
    ev = evaluator if evaluator is not None else get_delegation_evaluator()

    try:
        chain = ev.build_chain(leaf_cid)
    except Exception as exc:
        return False, f"chain build failed: {exc}"

    # Check revocations first.
    if revocation_list is not None:
        for delegation in chain:
            if revocation_list.is_revoked(delegation.cid):
                return False, f"delegation {delegation.cid!r} has been revoked"

    return ev.can_invoke(leaf_cid, resource=tool, ability=tool, actor=actor)


# ---------------------------------------------------------------------------
# Phase I — Persistent delegation store (session 57)
# ---------------------------------------------------------------------------

class DelegationStore:
    """Persistent store for :class:`Delegation` objects backed by a JSON file.

    The in-memory store maps ``cid → Delegation``.  :meth:`save` serialises
    all delegations to a JSON file; :meth:`load` reconstructs them.

    Args:
        path: Filesystem path for the JSON delegation file.

    Usage::

        store = DelegationStore("/var/lib/mcp/delegations.json")
        store.add(delegation)
        store.save()    # persist on shutdown

        store2 = DelegationStore("/var/lib/mcp/delegations.json")
        store2.load()   # restore on startup
        ev = store2.to_evaluator()
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._store: Dict[str, Delegation] = {}

    # ------------------------------------------------------------------
    # In-memory operations
    # ------------------------------------------------------------------

    def add(self, delegation: Delegation) -> None:
        """Add *delegation* to the in-memory store."""
        self._store[delegation.cid] = delegation

    def get(self, cid: str) -> Optional[Delegation]:
        """Retrieve a delegation by CID; returns *None* if not found."""
        return self._store.get(cid)

    def remove(self, cid: str) -> bool:
        """Remove a delegation; return *True* if it existed."""
        if cid in self._store:
            del self._store[cid]
            return True
        return False

    def list_cids(self) -> List[str]:
        """Return a sorted list of stored delegation CIDs."""
        return sorted(self._store)

    def __len__(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist all delegations to *path* as JSON.

        Creates parent directories if necessary.
        """
        import json as _json
        import os

        data: Dict[str, Any] = {
            cid: d.to_dict() for cid, d in self._store.items()
        }
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            _json.dump(data, fh, indent=2)
        logger.debug("Saved %d delegations to %s", len(data), self.path)

    def load(self) -> int:
        """Load delegations from *path*.

        Missing or unreadable files return 0 without raising.

        Returns:
            The number of delegations successfully loaded.
        """
        import json as _json

        try:
            with open(self.path, encoding="utf-8") as fh:
                data: Dict[str, Any] = _json.load(fh)
        except FileNotFoundError:
            logger.debug("Delegation store file not found: %s", self.path)
            return 0
        except (OSError, ValueError) as exc:
            logger.warning("Could not read delegation store %s: %s", self.path, exc)
            return 0

        loaded = 0
        for cid, entry in data.items():
            try:
                caps = [
                    Capability(resource=c["resource"], ability=c["ability"])
                    for c in entry.get("capabilities", [])
                ]
                d = Delegation(
                    cid=cid,
                    issuer=entry.get("issuer", ""),
                    audience=entry.get("audience", ""),
                    capabilities=caps,
                    expiry=entry.get("expiry"),
                    proof_cid=entry.get("proof_cid"),
                    signature=entry.get("signature", ""),
                )
                self._store[cid] = d
                loaded += 1
            except Exception as exc:
                logger.warning("Skipping malformed delegation %r: %s", cid, exc)
        logger.debug("Loaded %d delegations from %s", loaded, self.path)
        return loaded

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def to_evaluator(self) -> "DelegationEvaluator":
        """Create a :class:`DelegationEvaluator` populated with all stored delegations."""
        ev = DelegationEvaluator()
        for delegation in self._store.values():
            ev.add(delegation)
        return ev


# ---------------------------------------------------------------------------
# Session 58 — DelegationManager (bundles Store + RevocationList + Evaluator)
# ---------------------------------------------------------------------------

import tempfile as _tempfile


class DelegationManager:
    """Bundles :class:`DelegationStore`, :class:`RevocationList`, and
    :class:`DelegationEvaluator` into a single convenience object.

    Provides a complete delegation lifecycle:

    - **Persisting** delegation chains (:class:`DelegationStore`)
    - **Revoking** individual or chain-wide CIDs (:class:`RevocationList`)
    - **Evaluating** capability invocations (:class:`DelegationEvaluator`)

    The :func:`get_delegation_manager` factory provides a process-global
    singleton.

    Usage::

        mgr = get_delegation_manager()
        mgr.add(delegation)
        mgr.revoke("compromised-cid")
        ok, reason = mgr.can_invoke("leaf-cid", "some_tool", "alice")
        mgr.save()

    Args:
        path: Filesystem path for the JSON delegation file.  Defaults to
            a temporary-directory path.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        _default_path = _tempfile.gettempdir() + "/mcp_delegations.json"
        self._store = DelegationStore(path or _default_path)
        self._revocation = RevocationList()
        self._evaluator: Optional[DelegationEvaluator] = None

    # ------------------------------------------------------------------
    # Delegation management
    # ------------------------------------------------------------------

    def add(self, delegation: Delegation) -> None:
        """Add a delegation; invalidates the cached evaluator."""
        self._store.add(delegation)
        self._evaluator = None  # invalidate on mutation

    def remove(self, cid: str) -> bool:
        """Remove a delegation by CID; return *True* if it existed."""
        result = self._store.remove(cid)
        self._evaluator = None
        return result

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, cid: str) -> None:
        """Revoke a single delegation CID."""
        self._revocation.revoke(cid)

    def is_revoked(self, cid: str) -> bool:
        """Return *True* if *cid* has been revoked."""
        return self._revocation.is_revoked(cid)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def get_evaluator(self) -> DelegationEvaluator:
        """Return a :class:`DelegationEvaluator` populated from the store.

        The evaluator is cached and re-created only when the store changes.
        """
        if self._evaluator is None:
            self._evaluator = self._store.to_evaluator()
        return self._evaluator

    def can_invoke(self, leaf_cid: str, tool: str, actor: str) -> Tuple[bool, str]:
        """Check whether *actor* can invoke *tool* via *leaf_cid*.

        Delegates to :func:`can_invoke_with_revocation` using the current
        evaluator and revocation list.

        Returns:
            ``(authorized, reason)`` tuple.
        """
        return can_invoke_with_revocation(
            leaf_cid, tool, actor,
            evaluator=self.get_evaluator(),
            revocation_list=self._revocation,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the delegation store to disk."""
        self._store.save()

    def load(self) -> int:
        """Load delegations from disk; invalidates the evaluator cache.

        Returns:
            Number of delegations loaded.
        """
        n = self._store.load()
        self._evaluator = None
        return n

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, int]:
        """Return a dict of delegation-related metrics.

        Returns:
            ``{"delegation_count": int, "revoked_cid_count": int}``
        """
        return {
            "delegation_count": len(self._store),
            "revoked_cid_count": len(self._revocation),
        }

    def __len__(self) -> int:
        return len(self._store)


# Global singleton
_default_delegation_manager: Optional[DelegationManager] = None


def get_delegation_manager(path: Optional[str] = None) -> DelegationManager:
    """Return the process-global :class:`DelegationManager` singleton.

    Creates the singleton on first call.

    Args:
        path: Optional path passed to :class:`DelegationManager` on first
            creation.  Ignored on subsequent calls.

    Returns:
        The global :class:`DelegationManager` instance.
    """
    global _default_delegation_manager
    if _default_delegation_manager is None:
        _default_delegation_manager = DelegationManager(path)
    return _default_delegation_manager


# ---------------------------------------------------------------------------
# Session 58 — Monitoring integration (Phase K)
# ---------------------------------------------------------------------------


def record_delegation_metrics(manager: "DelegationManager", collector: Any) -> None:
    """Surface :class:`DelegationManager` metrics via *collector*.

    Calls :meth:`set_gauge` on *collector* with two metrics:

    - ``mcp_revoked_cids_total`` — number of CIDs in the revocation list.
    - ``mcp_delegation_store_depth`` — number of stored delegations.

    All collector errors are swallowed with a warning so that metric
    recording never crashes the server.

    Args:
        manager: A :class:`DelegationManager` instance.
        collector: An :class:`~monitoring.EnhancedMetricsCollector`-compatible
            object; only :meth:`set_gauge` is called.
    """
    try:
        metrics = manager.get_metrics()
        collector.set_gauge(
            "mcp_revoked_cids_total",
            float(metrics["revoked_cid_count"]),
        )
        collector.set_gauge(
            "mcp_delegation_store_depth",
            float(metrics["delegation_count"]),
        )
    except Exception as exc:
        logger.warning("record_delegation_metrics failed: %s", exc)
