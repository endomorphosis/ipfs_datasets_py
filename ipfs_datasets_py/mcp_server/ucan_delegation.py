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

    # CC139 ── ASCII visualization ───────────────────────────────────────────

    def to_ascii_tree(self) -> str:
        """CC139: Return an ASCII-art tree showing the delegation chain.

        Each row shows the token index, issuer→audience link, and capabilities.
        An empty chain returns ``"(empty chain)"``.

        Example output::

            DelegationChain [3 tokens]
            ├─[0] did:key:root → did:key:agent1  (caps: logic/*:invoke/*)
            ├─[1] did:key:agent1 → did:key:agent2  (caps: logic/read:read/invoke)
            └─[2] did:key:agent2 → did:key:leaf  (caps: *)

        Returns
        -------
        str
            Multi-line ASCII representation.
        """
        if not self.tokens:
            return "(empty chain)"

        num_tokens = len(self.tokens)
        lines: List[str] = [f"DelegationChain [{num_tokens} token{'s' if num_tokens != 1 else ''}]"]
        for i, tok in enumerate(self.tokens):
            prefix = "└─" if i == num_tokens - 1 else "├─"
            caps_str = ", ".join(
                f"{c.resource}:{c.ability}" for c in tok.capabilities
            ) or "(no caps)"
            cid_short = tok.cid[:12] + "…" if len(tok.cid) > 12 else tok.cid
            lines.append(
                f"{prefix}[{i}] {tok.issuer} → {tok.audience}"
                f"  (cid: {cid_short}, caps: {caps_str})"
            )
        return "\n".join(lines)

    def __str__(self) -> str:  # CC139
        return self.to_ascii_tree()

    def __len__(self) -> int:
        return len(self.tokens)


# ─── evaluator ──────────────────────────────────────────────────────────────


class DelegationEvaluator:
    """
    Checks whether a principal holds a valid delegation for a capability.

    Tokens are indexed by their CID.  Chains are assembled on demand by
    following ``proof_cid`` links from leaf to root.
    """

    def __init__(self) -> None:
        self._tokens: Dict[str, DelegationToken] = {}
        # Phase 6: chain assembly cache.
        # Key: leaf_cid → DelegationChain (root-first).
        # Invalidated when a new token is added.
        self._chain_cache: Dict[str, "DelegationChain"] = {}

    def add_token(self, token: DelegationToken) -> str:
        """Store *token* and return its CID.

        Adding a new token invalidates the chain cache because existing chains
        may now be extendable.
        """
        cid = token.cid
        if cid not in self._tokens:
            # Clear chain cache on new tokens to avoid stale chain references.
            self._chain_cache.clear()
        self._tokens[cid] = token
        return cid

    def get_token(self, cid: str) -> Optional[DelegationToken]:
        return self._tokens.get(cid)

    def build_chain(self, leaf_cid: str, *, use_cache: bool = True) -> DelegationChain:
        """Follow ``proof_cid`` links to build the full delegation chain.

        The chain is returned in root-first order (root → ... → leaf).

        Parameters
        ----------
        leaf_cid:
            CID of the leaf (innermost) token to start chain assembly from.
        use_cache:
            When *True* (default) the assembled chain is stored in an in-memory
            cache keyed by *leaf_cid* and reused on subsequent identical calls.
        """
        if use_cache and leaf_cid in self._chain_cache:
            return self._chain_cache[leaf_cid]

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
        chain = DelegationChain(tokens=chain_tokens)
        if use_cache:
            self._chain_cache[leaf_cid] = chain
        return chain

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

    def save(self, path: str) -> None:
        """Persist the revocation list to a JSON file.

        If ``ipfs_datasets_py.mcp_server.secrets_vault`` is available and
        *path* ends in ``.enc``, the file is written via the global
        :class:`~ipfs_datasets_py.mcp_server.secrets_vault.SecretsVault` so
        that the content is encrypted at rest.  Otherwise it is written as
        plain JSON with ``0o600`` permissions.

        Parameters
        ----------
        path:
            Destination file path.
        """
        import json as _json
        import os as _os

        data = {"revoked": self.to_list(), "count": len(self._revoked)}

        if path.endswith(".enc"):
            # Encrypted path via SecretsVault
            try:
                from ipfs_datasets_py.mcp_server.secrets_vault import get_secrets_vault
                vault = get_secrets_vault()
                vault.set("__revocation_list__", _json.dumps(data))
                # Also write a plaintext marker so the path exists
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("vault-backed")
                _os.chmod(path, 0o600)
                return
            except ImportError:
                pass  # Fall through to plaintext

        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(data, fh)
        _os.chmod(path, 0o600)

    def load(self, path: str) -> int:
        """Load a revocation list from a JSON file previously written by :meth:`save`.

        Returns the number of CIDs loaded.
        """
        import json as _json
        import os as _os

        if not _os.path.isfile(path):
            return 0

        if path.endswith(".enc"):
            try:
                from ipfs_datasets_py.mcp_server.secrets_vault import get_secrets_vault
                vault = get_secrets_vault()
                raw = vault.get("__revocation_list__")
                if raw is None:
                    return 0
                data = _json.loads(raw)
            except (ImportError, Exception):
                return 0
        else:
            with open(path, encoding="utf-8") as fh:
                data = _json.load(fh)

        cids: List[str] = data.get("revoked", [])
        for cid in cids:
            self._revoked.add(cid)
        return len(cids)

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
_global_manager: Optional["DelegationManager"] = None


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


# ─── DelegationManager (BH118) ───────────────────────────────────────────────


class DelegationManager:
    """High-level facade that combines :class:`DelegationStore`,
    :class:`DelegationEvaluator`, and :class:`RevocationList` into a single
    lifecycle object with optional persistence.

    Parameters
    ----------
    path:
        Optional path to store delegation tokens on disk.  When ``None``,
        the manager works entirely in-memory.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._store = DelegationStore(store_path=path)
        self._revocation = RevocationList()
        self._evaluator: Optional[DelegationEvaluator] = None  # lazy / cache
        self._metrics_cache: Optional[Dict[str, Any]] = None  # CM149: memoize get_metrics

    # ------------------------------------------------------------------
    # Token lifecycle
    # ------------------------------------------------------------------

    def add(self, token: DelegationToken) -> str:
        """Add *token* and return its CID.  Invalidates the evaluator cache."""
        cid = self._store.add(token)
        self._evaluator = None  # invalidate cache
        self._metrics_cache = None  # CM149: invalidate metrics cache
        return cid

    def remove(self, cid: str) -> bool:
        """Remove token by *cid*.  Invalidates the evaluator cache."""
        result = self._store.remove(cid)
        if result:
            self._evaluator = None
            self._metrics_cache = None  # CM149: invalidate metrics cache
        return result

    def get(self, cid: str) -> Optional[DelegationToken]:
        """Return token by *cid* or ``None``."""
        return self._store.get(cid)

    def list_cids(self) -> List[str]:
        """Return list of all token CIDs in the store."""
        return self._store.list_cids()

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, cid: str) -> None:
        """Revoke a token by *cid*."""
        self._revocation.revoke(cid)
        self._metrics_cache = None  # DV184: invalidate cache on revoke

    def revoke_chain(self, root_cid: str) -> int:
        """Revoke an entire chain rooted at *root_cid*.

        Builds the chain from the store and revokes all constituent tokens.
        If the chain is empty or cannot be built, *root_cid* itself is revoked.
        Returns the number of tokens revoked (at least 1).
        """
        ev = self.get_evaluator()
        try:
            chain = ev.build_chain(root_cid)
            if chain.tokens:
                self._revocation.revoke_chain(chain)
                return len(chain.tokens)
            # Empty chain — unknown root_cid; still revoke it directly
            self._revocation.revoke(root_cid)
            return 1
        except (KeyError, ValueError, RuntimeError) as exc:
            logger.warning("revoke_chain(%s): could not build chain, revoking root only: %s", root_cid, exc)
            self._revocation.revoke(root_cid)
            return 1

    def is_revoked(self, cid: str) -> bool:
        """Return ``True`` if *cid* has been revoked."""
        return self._revocation.is_revoked(cid)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def get_evaluator(self) -> DelegationEvaluator:
        """Return a :class:`DelegationEvaluator` (cached; rebuilt on add/remove)."""
        if self._evaluator is None:
            self._evaluator = self._store.to_evaluator()
        return self._evaluator

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

        Also checks the revocation list before evaluating the chain.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        ev = self.get_evaluator()
        return ev.can_invoke_with_revocation(
            principal,
            resource,
            ability,
            leaf_cid=leaf_cid,
            revocation_list=self._revocation,
            at_time=at_time,
        )

    def can_invoke_audited(
        self,
        principal: str,
        resource: str,
        ability: str,
        *,
        leaf_cid: str,
        at_time: Optional[float] = None,
        audit_log: Optional[Any] = None,
        policy_cid: str = "delegation",
        intent_cid: str = "intent",
    ) -> Tuple[bool, str]:
        """Check whether *principal* can invoke *ability* on *resource*.

        Like :meth:`can_invoke` but additionally records the decision to
        *audit_log* (a :class:`~policy_audit_log.PolicyAuditLog`) when provided.

        Returns (allowed: bool, reason: str).
        """
        allowed, reason = self.can_invoke(
            principal, resource, ability,
            leaf_cid=leaf_cid, at_time=at_time,
        )
        if audit_log is not None:
            try:
                decision_str = "allow" if allowed else "deny"
                audit_log.record(
                    policy_cid=policy_cid,
                    intent_cid=intent_cid,
                    decision=decision_str,
                    tool=ability,
                    actor=principal,
                )
            except (TypeError, AttributeError, ValueError) as exc:  # pragma: no cover
                logger.warning("can_invoke_audited: audit record failed: %s", exc)
        return allowed, reason

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> str:
        """Persist the store to disk.  Returns the path written."""
        return self._store.save()

    def load(self) -> int:
        """Load the store from disk.  Returns the number of tokens loaded."""
        count = self._store.load()
        self._evaluator = None  # invalidate cache
        self._metrics_cache = None  # CM149: invalidate metrics cache
        return count

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """Return a metrics snapshot.

        CM149: Extended to include ``max_chain_depth`` — the maximum chain
        length observed across all stored delegation tokens (0 when empty).

        The result is memoised and invalidated whenever tokens are added,
        removed, or loaded, so repeated calls are O(1) after the first.
        """
        if self._metrics_cache is not None:
            return dict(self._metrics_cache)
        max_depth = 0
        try:
            evaluator = self.get_evaluator()
            for cid in self._store.list_cids():
                try:
                    chain = evaluator.build_chain(cid)
                    if len(chain) > max_depth:
                        max_depth = len(chain)
                except Exception:
                    pass
        except Exception:
            pass
        result = {
            "token_count": len(self._store),
            "revoked_count": len(self._revocation),
            "active_token_count": max(0, len(self._store) - len(self._revocation)),  # DV184
            "has_path": self._store._store_path is not None,
            "max_chain_depth": max_depth,
        }
        self._metrics_cache = result
        return dict(result)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # CQ153: Merge
    # ------------------------------------------------------------------

    def merge(self, other: "DelegationManager") -> int:
        """CQ153: Copy non-duplicate delegation tokens from *other* into *self*.

        Tokens whose CID is already present in this manager are skipped.
        Revocations are **not** copied (use explicit revoke() calls for that).

        Parameters
        ----------
        other:
            Source :class:`DelegationManager`.

        Returns
        -------
        int
            Number of tokens actually added (0 if all were duplicates).
        """
        added = 0
        for cid in other.list_cids():
            if cid not in self._store:
                token = other.get(cid)
                if token is not None:
                    self._store.add(token)
                    added += 1
        if added > 0:
            self._evaluator = None  # invalidate
            self._metrics_cache = None
        return added

    def merge_and_publish(self, other: "DelegationManager", pubsub: Any) -> int:
        """CQ153/CY161: Merge tokens from *other*, then publish a receipt-dissemination event.

        Calls :meth:`merge` and then ``pubsub.publish("receipt_disseminate",
        {"type": "merge", "added": N, "total": M, "metrics": {...}})``.

        The ``"metrics"`` key contains the full snapshot from
        :meth:`get_metrics` (``delegation_count``, ``revoked_cid_count``,
        ``max_chain_depth``) so consumers can react to the current state
        without an additional round-trip.

        Parameters
        ----------
        other:
            Source :class:`DelegationManager`.
        pubsub:
            Any object with a ``publish(topic: str, payload: dict) -> None``
            method.  The topic ``"receipt_disseminate"`` is used.

        Returns
        -------
        int
            Number of tokens added (same as :meth:`merge`).
        """
        added = self.merge(other)
        try:
            pubsub.publish(
                "receipt_disseminate",
                {
                    "type": "merge",
                    "added": added,
                    "total": len(self._store),
                    "metrics": self.get_metrics(),  # CY161: full snapshot
                },
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("merge_and_publish: pubsub.publish failed: %s", exc)
        return added

    async def merge_and_publish_async(self, other: "DelegationManager", pubsub: Any) -> int:
        """DK173/DQ179: Async variant of :meth:`merge_and_publish`.

        Merges tokens from *other* synchronously (thread-safe), then calls
        ``await pubsub.publish_async("receipt_disseminate", payload)`` when
        the pubsub has a ``publish_async`` coroutine, falling back to the
        synchronous ``publish`` if it does not.

        DQ179: The topic string ``"receipt_disseminate"`` is the well-known
        MCP+P2P pubsub topic key (see ``MCP_P2P_PUBSUB_TOPICS`` in
        ``mcp_p2p_transport.py``).  The ``event_type`` field in the payload
        is set to ``"RECEIPT_DISSEMINATE"`` for consumers that need to
        distinguish event types.

        The payload is otherwise identical to :meth:`merge_and_publish`.

        Parameters
        ----------
        other:
            Source :class:`DelegationManager`.
        pubsub:
            Any object with a ``publish_async(topic, payload)`` coroutine
            **or** a synchronous ``publish(topic, payload)`` method as a
            fallback.

        Returns
        -------
        int
            Number of tokens added (same as :meth:`merge`).
        """
        added = self.merge(other)
        payload = {
            "type": "merge",
            "event_type": "RECEIPT_DISSEMINATE",  # DQ179: explicit event type
            "added": added,
            "total": len(self._store),
            "metrics": self.get_metrics(),
        }
        try:
            import inspect
            publish_fn = getattr(pubsub, "publish_async", None)
            if publish_fn is not None and inspect.iscoroutinefunction(publish_fn):
                await publish_fn("receipt_disseminate", payload)
            else:
                # Fallback: synchronous publish
                sync_fn = getattr(pubsub, "publish", None)
                if sync_fn is not None:
                    sync_fn("receipt_disseminate", payload)
        except Exception as exc:
            logger.debug("merge_and_publish_async: publish failed: %s", exc)
        return added

    def __repr__(self) -> str:
        return (
            f"DelegationManager(tokens={len(self._store)}, "
            f"revoked={len(self._revocation)})"
        )


def get_delegation_manager() -> "DelegationManager":
    """Return the process-global :class:`DelegationManager` (lazy-init)."""
    global _global_manager
    if _global_manager is None:
        _global_manager = DelegationManager()
    return _global_manager



# ---------------------------------------------------------------------------
# CM149: record_delegation_metrics — publish DelegationManager metrics to Prometheus
# ---------------------------------------------------------------------------

def record_delegation_metrics(
    manager: Optional["DelegationManager"],
    collector: Any,
) -> None:
    """CM149: Record :class:`DelegationManager` metrics to a Prometheus *collector*.

    Sets three gauges:

    * ``mcp_revoked_cids_total`` — number of revoked CIDs
    * ``mcp_delegation_store_depth`` — number of stored tokens
    * ``mcp_delegation_chain_depth_max`` — maximum delegation chain depth observed

    Parameters
    ----------
    manager:
        A :class:`DelegationManager` instance, or ``None`` (no-op).
    collector:
        Any object with a ``set_gauge(name: str, value: float)`` method
        (e.g. :class:`~mcp_server.monitoring.PrometheusExporter`).

    Notes
    -----
    All exceptions are swallowed and logged at DEBUG level so that monitoring
    failures cannot crash the calling server loop.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    if manager is None:
        return
    try:
        metrics = manager.get_metrics()
        collector.set_gauge("mcp_revoked_cids_total", float(metrics.get("revoked_count", 0)))
        collector.set_gauge("mcp_delegation_store_depth", float(metrics.get("token_count", 0)))
        collector.set_gauge("mcp_delegation_chain_depth_max", float(metrics.get("max_chain_depth", 0)))
    except Exception as exc:
        _log.debug("record_delegation_metrics: failed: %s", exc)
