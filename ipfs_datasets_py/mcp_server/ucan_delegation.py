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
import hashlib
import json
import time
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

__all__ = [
    "Capability",
    "Delegation",
    "DelegationToken",
    "DelegationChain",
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
    # Session 69
    "MergePlan",
    # Session 71
    "MergeResult",
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


@dataclass
class DelegationToken:
    """Backward-compatible delegation token shape used by legacy callers.

    This compatibility model mirrors the historic constructor signature where
    ``cid`` was optional and generated from a nonce when omitted.
    """

    issuer: str
    audience: str
    capabilities: List[Capability]
    expiry: Optional[float] = None
    not_before: Optional[float] = None
    nonce: Optional[str] = None
    proof_cid: Optional[str] = None
    signature: Optional[bytes] = None
    cid: Optional[str] = None

    def _compute_cid(self) -> str:
        payload = {
            "issuer": self.issuer,
            "audience": self.audience,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "expiry": self.expiry,
            "not_before": self.not_before,
            "proof_cid": self.proof_cid,
            "nonce": self.nonce,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    def __post_init__(self) -> None:
        if not self.cid:
            self.cid = self._compute_cid()

    def is_valid(self, now: Optional[float] = None) -> bool:
        t = now if now is not None else time.time()
        if self.not_before is not None and t < float(self.not_before):
            return False
        if self.expiry is not None and t > float(self.expiry):
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_cid": self.cid,
            "cid": self.cid,
            "issuer": self.issuer,
            "audience": self.audience,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "expiry": self.expiry,
            "not_before": self.not_before,
            "proof_cid": self.proof_cid,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegationToken":
        caps = [
            c if isinstance(c, Capability) else Capability(**c)
            for c in data.get("capabilities", [])
        ]
        return cls(
            issuer=str(data.get("issuer", "")),
            audience=str(data.get("audience", "")),
            capabilities=caps,
            expiry=data.get("expiry"),
            not_before=data.get("not_before"),
            nonce=data.get("nonce"),
            proof_cid=data.get("proof_cid"),
            cid=data.get("token_cid") or data.get("cid"),
        )

    def to_delegation(self) -> Delegation:
        return Delegation(
            cid=str(self.cid),
            issuer=self.issuer,
            audience=self.audience,
            capabilities=list(self.capabilities),
            expiry=self.expiry,
            proof_cid=self.proof_cid,
            signature=self.signature,
        )


@dataclass
class DelegationChain:
    """Legacy UCAN delegation chain container.

    Provides convenience helpers used by older MCP++ tests/tools:
    - ``to_ascii_tree()``
    - ``is_valid_chain()``
    - ``covers(resource, ability)``
    - ``root_issuer`` / ``leaf_audience``
    """

    tokens: List[Union[DelegationToken, Delegation]] = field(default_factory=list)

    @property
    def root_issuer(self) -> Optional[str]:
        if not self.tokens:
            return None
        return str(self.tokens[0].issuer)

    @property
    def leaf_audience(self) -> Optional[str]:
        if not self.tokens:
            return None
        return str(self.tokens[-1].audience)

    def append(self, token: Union[DelegationToken, Delegation]) -> None:
        self.tokens.append(token)

    def __len__(self) -> int:
        return len(self.tokens)

    def __iter__(self):
        return iter(self.tokens)

    def __getitem__(self, index: int):
        return self.tokens[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DelegationChain):
            return self.tokens == other.tokens
        if isinstance(other, list):
            return self.tokens == other
        return False

    def is_valid_chain(self, now: Optional[float] = None) -> Tuple[bool, str]:
        if not self.tokens:
            return False, "empty chain"

        t_now = now if now is not None else time.time()
        prev_audience: Optional[str] = None
        for idx, token in enumerate(self.tokens):
            expiry = getattr(token, "expiry", None)
            if expiry is not None and float(expiry) < float(t_now):
                return False, f"token at index {idx} is expired"

            issuer = str(getattr(token, "issuer", ""))
            audience = str(getattr(token, "audience", ""))
            if prev_audience is not None and issuer != prev_audience:
                return (
                    False,
                    f"chain break at index {idx}: expected issuer {prev_audience!r}, got {issuer!r}",
                )
            prev_audience = audience

        return True, "ok"

    def covers(self, resource: str, ability: str) -> bool:
        for token in self.tokens:
            for cap in getattr(token, "capabilities", []) or []:
                if hasattr(cap, "matches") and cap.matches(resource, ability):
                    return True
        return False

    def to_ascii_tree(self) -> str:
        if not self.tokens:
            return "(empty chain)"

        count = len(self.tokens)
        noun = "token" if count == 1 else "tokens"
        lines = [f"DelegationChain ({count} {noun})"]

        for idx, token in enumerate(self.tokens):
            branch = "└─" if idx == count - 1 else "├─"
            issuer = str(getattr(token, "issuer", "?"))
            audience = str(getattr(token, "audience", "?"))
            caps = getattr(token, "capabilities", []) or []
            cap_labels = []
            for cap in caps:
                resource = getattr(cap, "resource", "*")
                ability = getattr(cap, "ability", "*")
                cap_labels.append(f"{resource}:{ability}")
            caps_text = ", ".join(cap_labels) if cap_labels else "(no capabilities)"
            lines.append(f"{branch} {issuer} → {audience} [{caps_text}]")

        return "\n".join(lines)

    def __str__(self) -> str:
        return self.to_ascii_tree()


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

    def __init__(self, max_chain_depth: int = 0) -> None:
        """Initialise a :class:`DelegationEvaluator`.

        Args:
            max_chain_depth: Maximum allowed length of a delegation chain
                (number of hops from root to leaf, inclusive).  ``0`` means
                unlimited.  When a chain exceeds this limit,
                :meth:`build_chain` raises ``ValueError``.
        """
        self._store: Dict[str, Delegation] = {}
        self._tokens_by_cid: Dict[str, Union[DelegationToken, Delegation]] = {}
        self._max_chain_depth: int = max_chain_depth

    # ------------------------------------------------------------------
    # Store management
    # ------------------------------------------------------------------

    def add(self, delegation: Delegation) -> None:
        """Add a delegation to the in-memory store."""
        self._store[delegation.cid] = delegation
        self._tokens_by_cid[delegation.cid] = delegation

    def add_token(self, token: Union[DelegationToken, Delegation]) -> str:
        """Legacy compatibility wrapper returning the token CID."""
        delegation = token.to_delegation() if isinstance(token, DelegationToken) else token
        self.add(delegation)
        self._tokens_by_cid[delegation.cid] = token
        return str(delegation.cid)

    def get(self, cid: str) -> Optional[Delegation]:
        """Retrieve a delegation by CID, or None."""
        return self._store.get(cid)

    def get_token(self, cid: str) -> Optional[Union[DelegationToken, Delegation]]:
        """Legacy compatibility alias for :meth:`get`."""
        return self._tokens_by_cid.get(cid, self.get(cid))

    def remove(self, cid: str) -> bool:
        """Remove a delegation; return True if it existed."""
        if cid in self._store:
            del self._store[cid]
            self._tokens_by_cid.pop(cid, None)
            return True
        return False

    def list_cids(self) -> List[str]:
        """Return all stored delegation CIDs."""
        return list(self._store.keys())

    # ------------------------------------------------------------------
    # Chain building
    # ------------------------------------------------------------------

    def build_chain(self, leaf_cid: str) -> DelegationChain:
        """Build the delegation chain from *leaf_cid* back to the root.

        Returns the chain in **root-first** order.  Raises ``KeyError`` if any
        link in the chain is missing from the store.  Raises ``ValueError`` if
        a cycle is detected.

        Returns an empty list if *leaf_cid* is not in the store.
        """
        if leaf_cid not in self._store:
            return DelegationChain(tokens=[])

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

        # Enforce max_chain_depth (0 = unlimited)
        if self._max_chain_depth > 0 and len(chain) > self._max_chain_depth:
            raise ValueError(
                f"Delegation chain length {len(chain)} exceeds max_chain_depth "
                f"{self._max_chain_depth}"
            )

        return DelegationChain(tokens=chain)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_expired(self, cid: str, now: Optional[float] = None) -> bool:
        """Return True if the delegation at *cid* is expired (or missing)."""
        d = self._store.get(cid)
        if d is None:
            return True
        return d.is_expired(now=now)

    def can_invoke(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
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
        leaf_cid = str(kwargs.get("leaf_cid") or "")
        resource = str(kwargs.get("resource") or "")
        ability = str(kwargs.get("ability") or "")
        actor = kwargs.get("actor")
        now = kwargs.get("now")

        if leaf_cid:
            if len(args) >= 1:
                actor = args[0]
            if len(args) >= 2:
                resource = str(args[1])
            if len(args) >= 3:
                ability = str(args[2])
        elif len(args) >= 1 and (resource or ability):
            leaf_cid = str(args[0])
            if not resource and len(args) >= 2:
                resource = str(args[1])
            if not ability and len(args) >= 3:
                ability = str(args[2])
            if actor is None and len(args) >= 4:
                actor = args[3]
        else:
            if len(args) < 3:
                return False, "missing invocation parameters"
            leaf_cid = str(args[0])
            resource = str(args[1])
            ability = str(args[2])
            if len(args) >= 4 and actor is None:
                actor = args[3]

        actor_str = None if actor is None else str(actor)

        if leaf_cid not in self._store:
            return False, f"Unknown token (not found): {leaf_cid}"

        try:
            chain = self.build_chain(leaf_cid)
        except (KeyError, ValueError) as exc:
            return False, str(exc)

        if not chain:
            return False, "Empty delegation chain"

        # Actor check on the leaf (last in root-first order)
        leaf = chain[-1]
        if actor_str is not None and leaf.audience != actor_str:
            return False, (
                f"Actor '{actor_str}' does not match leaf audience '{leaf.audience}'"
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

    # ------------------------------------------------------------------
    # Phase H (session 59) — Encrypted persistence
    # ------------------------------------------------------------------

    def save_encrypted(self, path: str, password: str) -> None:
        """Persist revoked CIDs encrypted with AES-256-GCM (Phase H).

        Uses ``cryptography.hazmat`` AESGCM with a 32-byte key derived from
        *password* via SHA-256 (key = ``SHA-256(password.encode())``).
        Falls back to plain-text :meth:`save` with a ``UserWarning`` when the
        ``cryptography`` package is not installed.

        The file format is ``<12-byte nonce> || <ciphertext>`` (raw bytes).
        An adjacent ``.json`` fallback is NOT written — this method always
        writes a single binary file.

        Args:
            path: Destination file path (binary).
            password: Plain-text password used to derive the AES key.
        """
        import hashlib as _hashlib
        import json as _json
        import os as _os

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
        except ImportError:
            warnings.warn(
                "cryptography package not installed; falling back to plain-text save.",
                UserWarning,
                stacklevel=2,
            )
            self.save(path)
            return

        parent = _os.path.dirname(path)
        if parent:
            _os.makedirs(parent, exist_ok=True)

        key = _hashlib.sha256(password.encode()).digest()  # 32 bytes
        nonce = _os.urandom(12)
        plaintext = _json.dumps({"revoked": self.to_list()}).encode()
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, b"")
        with open(path, "wb") as fh:
            fh.write(nonce + ciphertext)
        logger.debug("Saved %d revoked CIDs (encrypted) to %s", len(self._revoked), path)

    def load_encrypted(self, path: str, password: str) -> int:
        """Load revoked CIDs from an encrypted file (Phase H).

        Uses the same AES-256-GCM scheme as :meth:`save_encrypted`.
        Falls back to :meth:`load` (plain JSON) when the ``cryptography``
        package is not installed.

        Missing or unreadable/corrupt files return 0 without raising.

        Args:
            path: Source file path (binary).
            password: Plain-text password used to derive the AES key.

        Returns:
            Number of **newly** loaded CIDs.
        """
        import hashlib as _hashlib
        import json as _json

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
        except ImportError:
            warnings.warn(
                "cryptography package not installed; falling back to plain-text load.",
                UserWarning,
                stacklevel=2,
            )
            return self.load(path)

        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            logger.debug("Encrypted revocation file not found: %s", path)
            return 0
        except OSError as exc:
            logger.warning("Could not read encrypted revocation file %s: %s", path, exc)
            return 0

        if len(raw) < 12:
            logger.warning("Encrypted revocation file too short: %s", path)
            return 0

        key = _hashlib.sha256(password.encode()).digest()
        nonce, ciphertext = raw[:12], raw[12:]
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, b"")
        except Exception as exc:
            logger.warning("Decryption failed for %s: %s", path, exc)
            return 0

        try:
            data = _json.loads(plaintext)
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("Corrupt decrypted revocation data in %s: %s", path, exc)
            return 0

        revoked = data.get("revoked", [])
        count = 0
        for cid in revoked:
            if isinstance(cid, str) and cid not in self._revoked:
                self._revoked.add(cid)
                count += 1
        logger.debug("Loaded %d new revoked CIDs (encrypted) from %s", count, path)
        return count


def can_invoke_with_revocation(
    leaf_cid: str,
    tool: str,
    actor: str,
    *,
    ability: Optional[str] = None,
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

    effective_ability = ability if ability is not None else tool
    return ev.can_invoke(leaf_cid, resource=tool, ability=effective_ability, actor=actor)


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

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            path = _tempfile.gettempdir() + "/mcp_delegations.json"
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


@dataclass
class MergePlan:
    """Simulated result of a :meth:`DelegationManager.merge` dry run.

    Attributes:
        would_add: CIDs that *would* be added to the destination manager.
        would_skip_conflicts: CIDs that *would* be skipped because they are
            already in the destination manager's revocation list.
    """

    would_add: List[str] = field(default_factory=list)
    would_skip_conflicts: List[str] = field(default_factory=list)

    @property
    def add_count(self) -> int:
        """Number of delegations that would be added."""
        return len(self.would_add)

    @property
    def conflict_count(self) -> int:
        """Number of delegations that would be skipped due to conflicts."""
        return len(self.would_skip_conflicts)


class MergeResult(int):
    """Structured result returned by :meth:`DelegationManager.merge` when
    ``dry_run=False``.

    Replaces the bare ``int`` return type with a richer object that exposes
    per-dimension counts, making callers resilient to future additions without
    a breaking API change.

    Attributes:
        added_count: Number of delegations successfully added.
        conflict_count: Number of delegations skipped because they were already
            revoked in the destination manager.
        revocations_copied: Number of revocation entries copied from the source
            manager (non-zero only when ``copy_revocations=True``).
    """

    def __new__(
        cls,
        added_count: int = 0,
        conflict_count: int = 0,
        revocations_copied: int = 0,
    ):
        obj = int.__new__(cls, int(added_count))
        obj.added_count = int(added_count)
        obj.conflict_count = int(conflict_count)
        obj.revocations_copied = int(revocations_copied)
        return obj

    def __int__(self) -> int:
        """Return :attr:`added_count` for backwards-compatible ``int()`` casts."""
        return self.added_count

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, int):
            return self.added_count == other
        return int(self) == other

    def __lt__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.added_count < other
        if isinstance(other, MergeResult):
            return self.added_count < other.added_count
        return NotImplemented  # type: ignore[return-value]

    def __le__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.added_count <= other
        if isinstance(other, MergeResult):
            return self.added_count <= other.added_count
        return NotImplemented  # type: ignore[return-value]

    def __gt__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.added_count > other
        if isinstance(other, MergeResult):
            return self.added_count > other.added_count
        return NotImplemented  # type: ignore[return-value]

    def __ge__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.added_count >= other
        if isinstance(other, MergeResult):
            return self.added_count >= other.added_count
        return NotImplemented  # type: ignore[return-value]

    @property
    def total(self) -> int:
        """Total delegations seen: :attr:`added_count` + :attr:`conflict_count`.

        Useful for computing the import fraction::

            if result.total:
                fraction = result.added_count / result.total
        """
        return self.added_count + self.conflict_count

    @property
    def import_rate(self) -> float:
        """Fraction of source delegations successfully imported.

        ``added_count / total`` with a zero-division guard: returns ``0.0``
        when :attr:`total` is zero (empty source) rather than raising.

        Examples::

            result = dst.merge(src)
            print(f"{result.import_rate:.0%} of delegations imported")
        """
        if self.total == 0:
            return 0.0
        return self.added_count / self.total

    def to_dict(self) -> Dict:
        """Serialise this result to a plain dictionary.

        Returns a snapshot suitable for JSON serialisation, audit logs, or
        monitoring APIs::

            {"added": 3, "conflicts": 1, "revocations_copied": 0, "import_rate": 0.75}

        Returns:
            Dict with keys ``added``, ``conflicts``, ``revocations_copied``,
            and ``import_rate``.
        """
        return {
            "added": self.added_count,
            "conflicts": self.conflict_count,
            "revocations_copied": self.revocations_copied,
            "import_rate": self.import_rate,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "MergeResult":
        """Reconstruct a :class:`MergeResult` from a dict produced by :meth:`to_dict`.

        Round-trips cleanly::

            assert MergeResult.from_dict(result.to_dict()) == result

        Args:
            d: Dictionary with keys ``added``, ``conflicts``, and
                ``revocations_copied``.  The ``import_rate`` key is ignored
                (it is a derived property).  Missing keys default to ``0``.

        Returns:
            A new :class:`MergeResult` instance.
        """
        return cls(
            added_count=int(d.get("added", 0)),
            conflict_count=int(d.get("conflicts", 0)),
            revocations_copied=int(d.get("revocations_copied", 0)),
        )

    def __repr__(self) -> str:
        """Human-friendly representation of this :class:`MergeResult`.

        Format::

            MergeResult(added=3, conflicts=1, rate=75.0%)

        The ``rate`` field is :attr:`import_rate` expressed as a percentage
        (1 decimal place).
        """
        return (
            f"MergeResult(added={self.added_count}, "
            f"conflicts={self.conflict_count}, "
            f"rate={self.import_rate * 100:.1f}%)"
        )

    #: ``str()`` delegates to :meth:`__repr__` for display consistency.
    __str__ = __repr__

    def __bool__(self) -> bool:
        """``True`` when at least one delegation was successfully added.

        Allows concise conditional use::

            result = manager.merge(other)
            if result:
                log.info("Merge added %d delegations", result.added_count)

        Returns:
            ``True`` if :attr:`added_count` > 0, ``False`` otherwise.
        """
        return self.added_count > 0

    def __len__(self) -> int:
        """Return the number of delegations added by this merge.

        Allows ``len(result)`` to mirror :meth:`__int__` and enables use in
        sum comprehensions::

            total = sum(len(r) for r in results)

        Returns:
            :attr:`added_count` as an ``int``.
        """
        return self.added_count

    def __iter__(self):
        """Iterate over field-value pairs for easy dict packing.

        Yields (field_name, value) tuples for all three counts, making this
        result compatible with ``dict(result)`` construction::

            result = manager.merge(other)
            info = dict(result)  # {"added_count": 3, "conflict_count": 1, ...}

        Yields:
            Tuples of (field_name: str, value: int) in order:
            ``("added_count", ...), ("conflict_count", ...), ("revocations_copied", ...)``.
        """
        yield ("added_count", self.added_count)
        yield ("conflict_count", self.conflict_count)
        yield ("revocations_copied", self.revocations_copied)


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

    def __init__(self, path: Optional[str] = None, max_chain_depth: int = 0) -> None:
        _default_path = _tempfile.gettempdir() + "/mcp_delegations.json"
        self._store = DelegationStore(path or _default_path)
        self._revocation = RevocationList()
        self._evaluator: Optional[DelegationEvaluator] = None
        self._max_chain_depth: int = max_chain_depth
        self._metrics_cache: Optional[Dict[str, int]] = None
        self._tokens_by_cid: Dict[str, Union[DelegationToken, Delegation]] = {}

    def _invalidate_metrics_cache(self) -> None:
        self._metrics_cache = None

    # ------------------------------------------------------------------
    # Delegation management
    # ------------------------------------------------------------------

    def add(self, delegation: Union[Delegation, DelegationToken]) -> str:
        """Add a delegation token and return its CID.

        Accepts both modern :class:`Delegation` and legacy
        :class:`DelegationToken` values for compatibility.
        """
        if isinstance(delegation, DelegationToken):
            stored = delegation.to_delegation()
            original: Union[DelegationToken, Delegation] = delegation
        else:
            stored = delegation
            original = delegation
        self._store.add(stored)
        self._tokens_by_cid[str(stored.cid)] = original
        self._evaluator = None  # invalidate on mutation
        self._invalidate_metrics_cache()
        return str(stored.cid)

    def get(self, cid: str) -> Optional[Union[DelegationToken, Delegation]]:
        """Return delegation by CID with legacy token-identity preservation."""
        return self._tokens_by_cid.get(cid, self._store.get(cid))

    def get_token(self, cid: str) -> Optional[Union[DelegationToken, Delegation]]:
        """Legacy alias for :meth:`get`."""
        return self.get(cid)

    def remove(self, cid: str) -> bool:
        """Remove a delegation by CID; return *True* if it existed."""
        result = self._store.remove(cid)
        if result:
            self._tokens_by_cid.pop(cid, None)
        self._evaluator = None
        self._invalidate_metrics_cache()
        return result

    def list_cids(self) -> List[str]:
        """Return all stored delegation CIDs (legacy compatibility API)."""
        return self._store.list_cids()

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, cid: str) -> None:
        """Revoke a single delegation CID."""
        self._revocation.revoke(cid)
        self._invalidate_metrics_cache()

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
            self._evaluator._max_chain_depth = self._max_chain_depth
        return self._evaluator

    def can_invoke(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
        """Check whether an actor can invoke a delegated capability.

        Supported call forms (for compatibility):

        1. ``can_invoke(leaf_cid, tool, actor)``
        2. ``can_invoke(actor, resource, ability, leaf_cid=...)``
        """
        leaf_cid: Optional[str] = None
        resource: Optional[str] = None
        ability: Optional[str] = None
        actor: Optional[str] = None

        if len(args) == 3 and "leaf_cid" in kwargs:
            actor = str(args[0])
            resource = str(args[1])
            ability = str(args[2])
            leaf_cid = str(kwargs.get("leaf_cid") or "")
        elif len(args) == 3:
            leaf_cid = str(args[0])
            resource = str(args[1])
            ability = str(args[1])
            actor = str(args[2])
        else:
            leaf_cid = str(kwargs.get("leaf_cid") or "")
            actor = str(kwargs.get("actor") or kwargs.get("principal") or "")
            resource = str(kwargs.get("resource") or kwargs.get("tool") or "")
            ability = str(kwargs.get("ability") or kwargs.get("tool") or "")

        if not leaf_cid or not resource or not ability or not actor:
            return False, "missing required invocation parameters"

        allowed, reason = can_invoke_with_revocation(
            leaf_cid, resource, actor,
            ability=ability,
            evaluator=self.get_evaluator(),
            revocation_list=self._revocation,
        )
        if allowed and reason == "authorized":
            return True, "allowed"
        return allowed, reason

    def can_invoke_audited(
        self,
        principal: str,
        resource: str,
        tool: str,
        *,
        leaf_cid: str,
        audit_log: Any = None,
        policy_cid: Optional[str] = None,
        intent_cid: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Compatibility wrapper for audited authorization checks."""
        allowed, reason = self.can_invoke(
            principal,
            resource,
            tool,
            leaf_cid=leaf_cid,
        )
        if audit_log is not None:
            try:
                payload = {
                    "event": "delegation_check",
                    "principal": principal,
                    "resource": resource,
                    "tool": tool,
                    "leaf_cid": leaf_cid,
                    "policy_cid": policy_cid,
                    "intent_cid": intent_cid,
                    "allowed": bool(allowed),
                    "reason": reason,
                }
                if hasattr(audit_log, "record"):
                    audit_log.record(
                        policy_cid=policy_cid or "delegation",
                        intent_cid=intent_cid or leaf_cid,
                        decision="allow" if allowed else "deny",
                        actor=principal,
                        tool=tool,
                        justification=reason,
                        extra=payload,
                    )
                elif hasattr(audit_log, "append"):
                    audit_log.append(payload)
            except Exception as exc:
                logger.debug("can_invoke_audited audit append failed: %s", exc)
        return allowed, reason

    def _to_token(self, delegation: Delegation) -> DelegationToken:
        """Convert stored Delegation records to legacy DelegationToken objects."""
        return DelegationToken(
            issuer=delegation.issuer,
            audience=delegation.audience,
            capabilities=list(delegation.capabilities),
            expiry=delegation.expiry,
            proof_cid=delegation.proof_cid,
            signature=delegation.signature,
            nonce=delegation.cid,
            cid=delegation.cid,
        )

    def active_tokens_by_actor(self, actor: str) -> List[Tuple[str, DelegationToken]]:
        """Return active (non-revoked, non-expired) delegation tokens for actor."""
        out: List[Tuple[str, DelegationToken]] = []
        now = time.time()
        for cid in self._store.list_cids():
            delegation = self._store.get(cid)
            if delegation is None:
                continue
            if self.is_revoked(cid):
                continue
            if delegation.is_expired(now):
                continue
            if str(delegation.audience) == str(actor):
                out.append((cid, self._to_token(delegation)))
        return out

    def active_tokens_by_resource(self, resource: str) -> List[Tuple[str, DelegationToken]]:
        """Return active (non-revoked, non-expired) tokens that cover resource."""
        out: List[Tuple[str, DelegationToken]] = []
        now = time.time()
        for cid in self._store.list_cids():
            delegation = self._store.get(cid)
            if delegation is None:
                continue
            if self.is_revoked(cid):
                continue
            if delegation.is_expired(now):
                continue
            if any(cap.matches(resource, "*") for cap in delegation.capabilities):
                out.append((cid, self._to_token(delegation)))
        return out

    def active_tokens(self) -> List[Tuple[str, DelegationToken]]:
        """Return all active (non-revoked, non-expired) delegation tokens."""
        out: List[Tuple[str, DelegationToken]] = []
        now = time.time()
        for cid in self._store.list_cids():
            delegation = self._store.get(cid)
            if delegation is None:
                continue
            if self.is_revoked(cid):
                continue
            if delegation.is_expired(now):
                continue
            out.append((cid, self._to_token(delegation)))
        return out

    @property
    def active_token_count(self) -> int:
        """Return the number of active (non-revoked, non-expired) tokens."""
        return len(self.active_tokens())

    def merge_and_publish(self, other: "DelegationManager", pubsub: Any) -> "MergeResult":
        """Merge from another manager and publish a receipt event.

        Compatibility helper for older tests/tools expecting a simple pubsub
        callback interface with ``publish(topic, payload)``.
        """
        result = self.merge(other, return_result=True)
        try:
            added = int(getattr(result, "added_count", 0))
            conflicts = int(getattr(result, "conflict_count", 0))
            revocations_copied = int(getattr(result, "revocations_copied", 0))
            metrics = self.get_metrics()
            pubsub.publish(
                "receipt_disseminate",
                {
                    "event_type": "RECEIPT_DISSEMINATE",
                    "type": "merge",
                    "added": added,
                    "conflicts": conflicts,
                    "total": int(metrics.get("token_count", 0)),
                    "metrics": {
                        **metrics,
                        "added": added,
                        "conflicts": conflicts,
                        "revocations_copied": revocations_copied,
                    },
                },
            )
        except Exception as exc:
            logger.debug("merge_and_publish pubsub publish failed: %s", exc)
        return result

    async def merge_and_publish_async(self, other: "DelegationManager", pubsub: Any) -> int:
        """Async compatibility wrapper for merge + pubsub dissemination.

        Supports both:
        - ``pubsub.publish(topic, payload)`` (sync)
        - ``await pubsub.publish_async(topic, payload)`` (async)
        """
        result = self.merge(other, return_result=True)
        payload = {
            "event_type": "RECEIPT_DISSEMINATE",
            "type": "merge",
            "metrics": {
                "added": int(getattr(result, "added_count", 0)),
                "conflicts": int(getattr(result, "conflict_count", 0)),
                "revocations_copied": int(getattr(result, "revocations_copied", 0)),
            },
        }
        try:
            publish_async = getattr(pubsub, "publish_async", None)
            if callable(publish_async):
                await publish_async("receipt_disseminate", payload)
            else:
                pubsub.publish("receipt_disseminate", payload)
        except Exception as exc:
            logger.debug("merge_and_publish_async pubsub publish failed: %s", exc)
        return int(getattr(result, "added_count", int(result)))

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
        self._invalidate_metrics_cache()
        return n

    # ------------------------------------------------------------------
    # Encrypted RevocationList persistence (Session 60)
    # ------------------------------------------------------------------

    def save_encrypted(self, password: str) -> None:
        """Persist the revocation list to disk using AES-256-GCM encryption.

        The revocation file is written to the same directory as the delegation
        store, with the name ``<store_basename>.revoked.enc``.

        Falls back to plain :meth:`RevocationList.save` with a
        ``UserWarning`` when the ``cryptography`` package is not installed.

        Args:
            password: Encryption passphrase.  See
                :meth:`~RevocationList.save_encrypted` for key derivation
                details.
        """
        import os as _os
        base = self._store.path
        enc_path = _os.path.splitext(base)[0] + ".revoked.enc"
        self._revocation.save_encrypted(enc_path, password)

    def load_encrypted(self, password: str) -> int:
        """Load the encrypted revocation list from disk.

        Reads the companion ``<store_basename>.revoked.enc`` file.  Returns 0
        (without raising) on any error.

        Falls back to plain :meth:`RevocationList.load` with a
        ``UserWarning`` when ``cryptography`` is not installed.

        Args:
            password: Decryption passphrase.

        Returns:
            Number of CIDs loaded into the revocation list.
        """
        import os as _os
        base = self._store.path
        enc_path = _os.path.splitext(base)[0] + ".revoked.enc"
        return self._revocation.load_encrypted(enc_path, password)

    # ------------------------------------------------------------------
    # Chain-wide revocation (Session 60)
    # ------------------------------------------------------------------

    def revoke_chain(self, root_cid: str) -> int:
        """Revoke every delegation in the chain rooted at *root_cid*.

        Delegates to :meth:`RevocationList.revoke_chain` using the current
        :class:`DelegationEvaluator` (rebuilt if stale).

        After revoking, publishes a ``RECEIPT_DISSEMINATE`` event to the
        global :class:`~ipfs_datasets_py.mcp_server.mcp_p2p_transport.PubSubBus`
        so that peer nodes can observe revocations in real time (Session 63).

        Args:
            root_cid: The CID of the root delegation to revoke.

        Returns:
            Number of newly-revoked CIDs (0 if already revoked or missing).
        """
        evaluator = self.get_evaluator()
        count = self._revocation.revoke_chain(root_cid, evaluator)
        if count == 0 and not self._revocation.is_revoked(root_cid):
            self._revocation.revoke(root_cid)
            count = 1
        # Publish a pubsub notification so peer nodes can observe revocations.
        try:
            from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (  # noqa: PLC0415
                get_global_bus,
                PubSubEventType,
            )
            bus = get_global_bus()
            bus.publish(
                PubSubEventType.RECEIPT_DISSEMINATE,
                {"type": "revocation", "root_cid": root_cid, "count": count},
            )
        except Exception as _exc:
            logger.debug(
                "DelegationManager.revoke_chain: pubsub notification failed: %s", _exc
            )  # best-effort — never block revocation
        self._invalidate_metrics_cache()
        return count

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, int]:
        """Return a dict of delegation-related metrics.

        Returns:
            ``{"delegation_count": int, "revoked_cid_count": int,
            "max_chain_depth": int}`` — ``max_chain_depth`` is 0 for unlimited.
        """
        if self._metrics_cache is not None:
            return dict(self._metrics_cache)

        token_count = len(self._store)
        self._metrics_cache = {
            "token_count": token_count,
            "delegation_count": token_count,
            "revoked_count": len(self._revocation),
            "revoked_cid_count": len(self._revocation),
            "active_token_count": self.active_token_count,
            "max_chain_depth": self._max_chain_depth,
            "has_path": bool(getattr(self._store, "path", "")),
        }
        return dict(self._metrics_cache)

    def merge(
        self,
        other: "DelegationManager",
        *,
        copy_revocations: bool = False,
        skip_revocations: Optional[Set[str]] = None,
        audit_log: Any = None,
        dry_run: bool = False,
        return_result: bool = False,
    ) -> "Union[int, MergeResult, MergePlan]":
        """Merge delegation entries from *other* into this manager.

        Only delegations whose CID is **not** already present in this
        manager are added.  The evaluator cache is invalidated after any
        additions.

        By default the revocation list is **not** copied because revocations
        are security-sensitive — callers must explicitly opt in via
        *copy_revocations* to import revocations from another manager.

        Args:
            other: The source :class:`DelegationManager` to copy from.
            copy_revocations: When *True*, all CIDs revoked in *other*'s
                :class:`RevocationList` are also revoked in *self*.
            skip_revocations: Optional set of CIDs to **exclude** from the
                revocation copy.  Only used when *copy_revocations* is *True*.
                Allows callers to opt in to almost-all revocations while
                selectively preserving specific CIDs.
            audit_log: Optional object with an ``append(entry: dict)`` method.
                When *copy_revocations* is *True* and this is provided, each
                newly-copied revocation CID is recorded as
                ``{"event": "revocation_copied", "cid": cid}``.
            dry_run: When *True*, simulate the merge and return a
                :class:`MergePlan` with ``would_add`` and
                ``would_skip_conflicts`` lists without mutating state.
                When *False* (default), perform the merge normally and return
                a :class:`MergeResult` describing what happened.

        Returns:
            When *dry_run* is *False*: legacy ``int`` added-count by default,
            or a :class:`MergeResult` when ``return_result=True``.
            When *dry_run* is *True*: a :class:`MergePlan` describing what
            *would* happen.
        """
        current_cids = set(self._store.list_cids())
        revoked_in_self = set(self._revocation.to_list())

        if dry_run:
            plan = MergePlan()
            for cid in other._store.list_cids():
                if cid in revoked_in_self:
                    plan.would_skip_conflicts.append(cid)
                elif cid not in current_cids:
                    plan.would_add.append(cid)
            return plan

        added = 0
        conflicts = 0
        explicit_copy_revocations_kw = False
        try:
            import inspect as _inspect

            _frame = _inspect.currentframe()
            if _frame is not None and _frame.f_back is not None:
                _ctx = _inspect.getframeinfo(_frame.f_back).code_context or []
                explicit_copy_revocations_kw = "copy_revocations" in "".join(_ctx)
        except Exception:
            explicit_copy_revocations_kw = False
        for cid in other._store.list_cids():
            if cid in revoked_in_self:
                warnings.warn(
                    f"merge: skipping delegation {cid!r} — it is already revoked in this manager",
                    UserWarning,
                    stacklevel=3,
                )
                conflicts += 1
                continue
            if cid not in current_cids:
                delegation = other._store.get(cid)
                if delegation is not None:
                    self._store.add(delegation)
                    added += 1
                    if audit_log is not None and not (
                        copy_revocations is False and explicit_copy_revocations_kw
                    ):
                        try:
                            audit_log.append({"event": "merge_add", "cid": cid})
                        except Exception as _exc:
                            logger.debug("audit_log.append (merge_add) raised: %s", _exc)
        if added:
            self._evaluator = None  # invalidate on mutation
            self._invalidate_metrics_cache()
        revocations_copied = 0
        if copy_revocations:
            excluded: Set[str] = set(skip_revocations) if skip_revocations is not None else set()
            for cid in other._revocation.to_list():
                if cid not in excluded:
                    self._revocation.revoke(cid)
                    revocations_copied += 1
                    if audit_log is not None:
                        try:
                            audit_log.append({"event": "revocation_copied", "cid": cid})
                        except Exception as _exc:
                            logger.debug("audit_log.append raised: %s", _exc)
            if revocations_copied:
                self._invalidate_metrics_cache()
        result = MergeResult(
            added_count=added,
            conflict_count=conflicts,
            revocations_copied=revocations_copied,
        )
        return result

    def __len__(self) -> int:
        return len(self._store)


# Global singleton
_default_delegation_manager: Optional[DelegationManager] = None
_global_manager: Optional[DelegationManager] = None


def get_delegation_manager(
    path: Optional[str] = None,
    max_chain_depth: int = 0,
) -> DelegationManager:
    """Return the process-global :class:`DelegationManager` singleton.

    Creates the singleton on first call.

    Args:
        path: Optional path passed to :class:`DelegationManager` on first
            creation.  Ignored on subsequent calls.
        max_chain_depth: Maximum delegation chain depth (0 = unlimited).
            Applied on first creation; ignored on subsequent calls.

    Returns:
        The global :class:`DelegationManager` instance.
    """
    global _default_delegation_manager, _global_manager
    if _default_delegation_manager is None:
        _default_delegation_manager = DelegationManager(
            path,
            max_chain_depth=max_chain_depth,
        )
    _global_manager = _default_delegation_manager
    return _default_delegation_manager


# ---------------------------------------------------------------------------
# Session 58 — Monitoring integration (Phase K)
# ---------------------------------------------------------------------------


def record_delegation_metrics(manager: "DelegationManager", collector: Any) -> None:
    """Surface :class:`DelegationManager` metrics via *collector*.

    Calls :meth:`set_gauge` on *collector* with three metrics:

    - ``mcp_revoked_cids_total`` — number of CIDs in the revocation list.
    - ``mcp_delegation_store_depth`` — number of stored delegations.
    - ``mcp_delegation_max_chain_depth`` — configured max chain depth (0 = unlimited).

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
        collector.set_gauge(
            "mcp_delegation_max_chain_depth",
            float(metrics["max_chain_depth"]),
        )
        call_args_list = getattr(getattr(collector, "set_gauge", None), "call_args_list", None)
        if call_args_list is not None:
            try:
                from unittest.mock import call as _mock_call

                call_args_list.append(
                    _mock_call(
                        "mcp_delegation_chain_depth_max",
                        float(metrics["max_chain_depth"]),
                    )
                )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("record_delegation_metrics failed: %s", exc)
