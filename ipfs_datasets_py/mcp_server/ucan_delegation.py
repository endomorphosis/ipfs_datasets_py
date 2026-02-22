"""
Profile C: UCAN Delegation (stub)

Implements the delegation chain profile from the MCP++ specification:
  https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/ucan-delegation.md

This is a lightweight **stub** implementation that provides the delegation
chain data model without external UCAN library dependencies.  It is
intended for development, testing, and exploration.  A production deployment
should use a full UCAN library (e.g. ``py-ucan``, ``ucan-core``).

Key concepts (from the spec):
- **Capability**: a ``(resource, ability)`` pair describing what is allowed.
- **DelegationToken**: a signed unit granting an *audience* a set of
  capabilities, optionally scoped by an expiry time and a proof chain.
- **DelegationChain**: an ordered list of :class:`DelegationToken` objects
  leading from the root issuer down to the requestor.
- **DelegationEvaluator**: checks whether a *principal* holds a valid
  delegation for a requested capability.

No external dependencies beyond stdlib.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .interface_descriptor import _canonicalize, compute_cid

logger = logging.getLogger(__name__)


# ─── data model ─────────────────────────────────────────────────────────────


@dataclass
class Capability:
    """A single ``(resource, ability)`` capability pair."""
    resource: str
    ability: str  # e.g. "tools/invoke", "tools/list", "*"

    def matches(self, resource: str, ability: str) -> bool:
        """Return True if this capability covers *resource* / *ability*.

        Wildcard abilities (``"*"``) match any requested ability.
        Wildcard resources (``"*"``) match any requested resource.
        """
        resource_ok = self.resource == "*" or self.resource == resource
        ability_ok = self.ability == "*" or self.ability == ability
        return resource_ok and ability_ok


@dataclass
class DelegationToken:
    """
    A single UCAN delegation token (Profile C: spec §3).

    Attributes:
        issuer: DID of the issuer (grants capabilities).
        audience: DID of the recipient (receives capabilities).
        capabilities: List of capabilities being delegated.
        expiry: Optional Unix timestamp after which the token is invalid.
        proof_cid: CID of a parent token authorising this delegation.
        not_before: Optional Unix timestamp before which token is inactive.
        nonce: Optional nonce for replay protection.
    """
    issuer: str
    audience: str
    capabilities: List[Capability] = field(default_factory=list)
    expiry: Optional[float] = None
    proof_cid: Optional[str] = None
    not_before: Optional[float] = None
    nonce: Optional[str] = None

    _cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def cid(self) -> str:
        """Lazily compute the token CID from its canonical bytes."""
        if self._cid is None:
            self._cid = compute_cid(self._canonical_bytes())
        return self._cid

    def _canonical_bytes(self) -> bytes:
        d = {
            "issuer": self.issuer,
            "audience": self.audience,
            "capabilities": [
                {"resource": c.resource, "ability": c.ability}
                for c in sorted(
                    self.capabilities, key=lambda x: (x.resource, x.ability)
                )
            ],
            "expiry": self.expiry,
            "proof_cid": self.proof_cid,
            "not_before": self.not_before,
            "nonce": self.nonce,
        }
        return _canonicalize(d)

    def is_valid(self, at_time: Optional[float] = None) -> bool:
        """Return True if the token is within its temporal validity window."""
        t = at_time if at_time is not None else time.time()
        if self.not_before is not None and t < self.not_before:
            return False
        if self.expiry is not None and t > self.expiry:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_cid": self.cid,
            "issuer": self.issuer,
            "audience": self.audience,
            "capabilities": [
                {"resource": c.resource, "ability": c.ability}
                for c in self.capabilities
            ],
            "expiry": self.expiry,
            "proof_cid": self.proof_cid,
            "not_before": self.not_before,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegationToken":
        capabilities = [
            Capability(resource=c["resource"], ability=c["ability"])
            for c in data.get("capabilities", [])
        ]
        return cls(
            issuer=data["issuer"],
            audience=data["audience"],
            capabilities=capabilities,
            expiry=data.get("expiry"),
            proof_cid=data.get("proof_cid"),
            not_before=data.get("not_before"),
            nonce=data.get("nonce"),
        )


@dataclass
class DelegationChain:
    """
    An ordered chain of :class:`DelegationToken` objects.

    The chain begins at the root issuer and ends at the leaf token whose
    audience is the requesting principal.  Each token's issuer must equal
    the previous token's audience (unless it is the root).
    """
    tokens: List[DelegationToken] = field(default_factory=list)

    def append(self, token: DelegationToken) -> None:
        """Add *token* to the end of the chain."""
        self.tokens.append(token)

    @property
    def root_issuer(self) -> Optional[str]:
        """DID of the original capability issuer (first token's issuer)."""
        return self.tokens[0].issuer if self.tokens else None

    @property
    def leaf_audience(self) -> Optional[str]:
        """DID of the terminal recipient (last token's audience)."""
        return self.tokens[-1].audience if self.tokens else None

    def is_valid_chain(self, at_time: Optional[float] = None) -> Tuple[bool, str]:
        """Validate structural and temporal integrity.

        Checks:
        1. All tokens are within their temporal window.
        2. Each token's audience matches the next token's issuer.

        Returns:
            A ``(valid: bool, reason: str)`` tuple.
        """
        if not self.tokens:
            return False, "Empty chain"

        t = at_time if at_time is not None else time.time()

        for i, token in enumerate(self.tokens):
            if not token.is_valid(t):
                return False, f"Token at index {i} is expired or not yet valid"
            if i > 0:
                prev = self.tokens[i - 1]
                if prev.audience != token.issuer:
                    return (
                        False,
                        f"Chain break at index {i}: expected issuer "
                        f"'{prev.audience}', got '{token.issuer}'",
                    )

        return True, "valid"

    def covers(
        self,
        resource: str,
        ability: str,
        at_time: Optional[float] = None,
    ) -> bool:
        """Return True if the chain grants *ability* on *resource*.

        The chain must be structurally valid, AND at least one token in
        the chain must carry a matching capability.
        """
        valid, _ = self.is_valid_chain(at_time)
        if not valid:
            return False
        return any(
            any(cap.matches(resource, ability) for cap in token.capabilities)
            for token in self.tokens
        )


# ─── evaluator ──────────────────────────────────────────────────────────────


class DelegationEvaluator:
    """
    Checks whether a principal holds a valid delegation for a capability.

    Tokens are indexed by their CID.  Chains are assembled on demand by
    following ``proof_cid`` links from leaf to root.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, DelegationToken] = {}

    def add_token(self, token: DelegationToken) -> str:
        """Store *token* and return its CID."""
        cid = token.cid
        self._tokens[cid] = token
        return cid

    def get_token(self, cid: str) -> Optional[DelegationToken]:
        return self._tokens.get(cid)

    def build_chain(self, leaf_cid: str) -> DelegationChain:
        """Follow ``proof_cid`` links to build the full delegation chain.

        The chain is returned in root-first order (root → ... → leaf).
        """
        chain_tokens: List[DelegationToken] = []
        current_cid: Optional[str] = leaf_cid
        visited: set = set()

        while current_cid is not None:
            if current_cid in visited:
                logger.warning("Cycle detected in delegation chain at %s", current_cid)
                break
            visited.add(current_cid)
            token = self._tokens.get(current_cid)
            if token is None:
                break
            chain_tokens.append(token)
            current_cid = token.proof_cid

        # Reverse to get root-first order
        chain_tokens.reverse()
        return DelegationChain(tokens=chain_tokens)

    def can_invoke(
        self,
        principal: str,
        resource: str,
        ability: str,
        *,
        leaf_cid: str,
        at_time: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Check whether *principal* can invoke *ability* on *resource*.

        Args:
            principal: The DID of the requesting agent.
            resource:  The resource being requested.
            ability:   The ability being requested.
            leaf_cid:  CID of the leaf delegation token held by *principal*.
            at_time:   Optional evaluation time (default: now).

        Returns:
            A ``(allowed: bool, reason: str)`` tuple.
        """
        leaf = self._tokens.get(leaf_cid)
        if leaf is None:
            return False, f"Unknown token CID: {leaf_cid}"

        if leaf.audience != principal:
            return (
                False,
                f"Token audience '{leaf.audience}' does not match principal "
                f"'{principal}'",
            )

        chain = self.build_chain(leaf_cid)
        valid, reason = chain.is_valid_chain(at_time)
        if not valid:
            return False, reason

        if not chain.covers(resource, ability, at_time):
            return False, f"No capability covering resource='{resource}' ability='{ability}'"

        return True, "allowed"

    def can_invoke_with_revocation(
        self,
        principal: str,
        resource: str,
        ability: str,
        *,
        leaf_cid: str,
        revocation_list: Optional["RevocationList"] = None,
        at_time: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Like :meth:`can_invoke` but also checks *revocation_list*.

        If any token in the chain has been revoked the request is denied.
        """
        if revocation_list is not None:
            chain = self.build_chain(leaf_cid)
            for token in chain.tokens:
                if revocation_list.is_revoked(token.cid):
                    return False, f"Token {token.cid} has been revoked"

        return self.can_invoke(
            principal, resource, ability,
            leaf_cid=leaf_cid, at_time=at_time,
        )


# ─── revocation list (spec §7) ────────────────────────────────────────────────


class RevocationList:
    """Tracks revoked delegation token CIDs (spec Profile C §7).

    Revoked tokens are permanently invalid regardless of their temporal window.
    """

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, cid: str) -> None:
        """Add *cid* to the revocation list."""
        self._revoked.add(cid)

    def is_revoked(self, cid: str) -> bool:
        """Return ``True`` if *cid* is on the revocation list."""
        return cid in self._revoked

    def revoke_chain(self, chain: "DelegationChain") -> None:
        """Revoke every token CID in *chain*."""
        for token in chain.tokens:
            self._revoked.add(token.cid)

    def clear(self) -> None:
        """Remove all revocations."""
        self._revoked.clear()

    def to_list(self) -> List[str]:
        """Return a sorted list of revoked CIDs."""
        return sorted(self._revoked)

    def __len__(self) -> int:
        return len(self._revoked)

    def __contains__(self, cid: object) -> bool:
        return cid in self._revoked

    def __repr__(self) -> str:
        return f"RevocationList({len(self._revoked)} revoked)"


# ─── delegation store (spec §6) ──────────────────────────────────────────────


import json
import os


class DelegationStore:
    """Durable delegation token store with optional JSON persistence.

    Provides add/get/remove operations and can serialise to/from a JSON file.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        """Initialise store, optionally loading from *store_path* if it exists."""
        self._tokens: Dict[str, DelegationToken] = {}
        self._store_path = store_path
        if store_path and os.path.isfile(store_path):
            try:
                self.load(store_path)
            except Exception as exc:
                logger.warning("Could not load delegation store from %s: %s", store_path, exc)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add(self, token: DelegationToken) -> str:
        """Store *token* and return its CID."""
        cid = token.cid
        self._tokens[cid] = token
        return cid

    def get(self, cid: str) -> Optional[DelegationToken]:
        """Return the token for *cid*, or ``None`` if not found."""
        return self._tokens.get(cid)

    def remove(self, cid: str) -> bool:
        """Remove *cid* from the store.  Returns ``True`` if it existed."""
        if cid in self._tokens:
            del self._tokens[cid]
            return True
        return False

    def list_cids(self) -> List[str]:
        """Return a sorted list of all stored CIDs."""
        return sorted(self._tokens)

    # ── persistence ───────────────────────────────────────────────────────────

    def save(self, path: Optional[str] = None) -> str:
        """Serialise all tokens to JSON.

        Args:
            path: File path to write.  Falls back to the path given at
                  construction time.  If neither is set, raises ``ValueError``.

        Returns:
            The path that was written.
        """
        target = path or self._store_path
        if not target:
            raise ValueError("No store_path configured and no path given to save()")
        records = {cid: tok.to_dict() for cid, tok in self._tokens.items()}
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({"tokens": list(records.values())}, fh, indent=2)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def load(self, path: Optional[str] = None) -> int:
        """Load tokens from a JSON file.

        Returns the number of tokens loaded.
        """
        target = path or self._store_path
        if not target:
            raise ValueError("No store_path configured and no path given to load()")
        with open(target, encoding="utf-8") as fh:
            data = json.load(fh)
        loaded = 0
        for record in data.get("tokens", []):
            try:
                tok = DelegationToken.from_dict(record)
                self._tokens[tok.cid] = tok
                loaded += 1
            except Exception as exc:
                logger.warning("Skipping malformed token record: %s", exc)
        return loaded

    # ── helpers ───────────────────────────────────────────────────────────────

    def to_evaluator(self) -> DelegationEvaluator:
        """Return a :class:`DelegationEvaluator` seeded with all stored tokens."""
        ev = DelegationEvaluator()
        for tok in self._tokens.values():
            ev.add_token(tok)
        return ev

    # ── dunder ────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._tokens)

    def __contains__(self, cid: object) -> bool:
        return cid in self._tokens

    def __repr__(self) -> str:
        return f"DelegationStore({len(self._tokens)} tokens, path={self._store_path!r})"


# ─── module-level singletons ─────────────────────────────────────────────────


_global_evaluator: Optional[DelegationEvaluator] = None
_global_store: Optional[DelegationStore] = None


def get_delegation_evaluator() -> DelegationEvaluator:
    """Return the process-global DelegationEvaluator (lazy-init)."""
    global _global_evaluator
    if _global_evaluator is None:
        _global_evaluator = DelegationEvaluator()
    return _global_evaluator


def get_delegation_store() -> DelegationStore:
    """Return the process-global DelegationStore (lazy-init, no persistence)."""
    global _global_store
    if _global_store is None:
        _global_store = DelegationStore()
    return _global_store
