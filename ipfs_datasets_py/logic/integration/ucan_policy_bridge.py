"""
UCAN Policy Bridge — DID-signed NL→Policy→UCAN evaluation engine.

This module is the integration glue between:

1. ``logic/CEC/nl/`` — NL parsing and DCEC formula production
2. ``logic/integration/nl_ucan_policy_compiler.py`` — full 3-stage pipeline
3. ``mcp_server/temporal_policy.py`` — deontic policy evaluation
4. ``mcp_server/ucan_delegation.py`` — UCAN delegation chain (stub or real)
5. ``mcp_server/did_key_manager.py`` — Ed25519 DID key (optional, real signing)

It exposes a single high-level ``UCANPolicyBridge`` class that can:

* Compile natural-language policy text into a :class:`PolicyObject` +
  delegation tokens (unsigned stubs or DID-signed via ``py-ucan``).
* Evaluate an intent against both the deontic policy *and* the UCAN chain.
* Persist delegation tokens via :class:`~mcp_server.ucan_delegation.DelegationStore`.
* Check revocation via :class:`~mcp_server.ucan_delegation.RevocationList`.

No hard dependency on ``py-ucan`` or ``mcp_server.did_key_manager``;
all advanced features degrade gracefully to stub/simulation mode.

Usage::

    from ipfs_datasets_py.logic.integration.ucan_policy_bridge import (
        UCANPolicyBridge,
    )

    bridge = UCANPolicyBridge()
    result = bridge.compile_nl(
        "Alice must not delete records. Bob is permitted to read files.",
        issuer_did="did:key:z6MkOrg",
        audience_did="did:key:z6MkBob",
    )
    print(result.policy_cid)          # bafy…
    print(result.delegation_count)    # 1  (permission → token)
    print(result.denial_count)        # 1  (prohibition → no token)

    eval_result = bridge.evaluate(
        result.policy_cid, tool="read", actor="Bob",
        audience_did="did:key:z6MkBob",
        leaf_cid=result.leaf_token_cid,
    )
    print(eval_result.decision)       # "allow"
    print(eval_result.ucan_allowed)   # True
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── result types ─────────────────────────────────────────────────────────────


@dataclass
class BridgeCompileResult:
    """Output of :meth:`UCANPolicyBridge.compile_nl`.

    Attributes
    ----------
    success:
        Whether compilation produced at least one policy clause.
    policy_cid:
        Content-addressed identifier of the resulting :class:`PolicyObject`.
    delegation_tokens:
        List of stub :class:`DelegationToken` objects (one per permission/obligation).
    denial_count:
        Number of PROHIBITION clauses (no delegation token emitted).
    leaf_token_cid:
        CID of the *last* delegation token, or ``None`` if no tokens were emitted.
    errors:
        Any errors accumulated during compilation.
    warnings:
        Any warnings accumulated during compilation.
    """
    success: bool = False
    policy_cid: str = ""
    delegation_tokens: List[Any] = field(default_factory=list)
    denial_count: int = 0
    leaf_token_cid: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def delegation_count(self) -> int:
        return len(self.delegation_tokens)


@dataclass
class BridgeEvaluationResult:
    """Output of :meth:`UCANPolicyBridge.evaluate`.

    Attributes
    ----------
    decision:
        ``"allow"``, ``"deny"``, or ``"allow_with_obligations"``.
    policy_cid:
        The policy that was evaluated.
    reason:
        Human-readable justification.
    ucan_allowed:
        Whether the UCAN delegation chain also grants access (``None`` if
        chain evaluation was skipped because no ``leaf_cid`` was provided).
    revoked:
        ``True`` if the leaf token was revoked before evaluation.
    """
    decision: str = "deny"
    policy_cid: str = ""
    reason: str = ""
    ucan_allowed: Optional[bool] = None
    revoked: bool = False


# ─── bridge ──────────────────────────────────────────────────────────────────


@dataclass
class SignedPolicyResult:
    """Output of :meth:`UCANPolicyBridge.compile_and_sign`.

    Attributes
    ----------
    compile_result:
        The :class:`BridgeCompileResult` from Stage 1–3 of the pipeline.
    signed_jwts:
        List of signed UCAN JWT strings (one per permission/obligation token).
        Each string is either a real Ed25519 JWT (when ``py-ucan`` is available
        and a DID key is loaded) or a ``"stub:…"`` base64 JSON string.
    signing_available:
        ``True`` if :class:`~mcp_server.did_key_manager.DIDKeyManager` was
        reachable.  ``False`` means no JWTs were produced.
    """
    compile_result: BridgeCompileResult
    signed_jwts: List[str] = field(default_factory=list)
    signing_available: bool = False

    @property
    def jwt_count(self) -> int:
        """Number of signed JWTs produced."""
        return len(self.signed_jwts)


class UCANPolicyBridge:
    """Coordinates NL→Policy→UCAN compilation and evaluation.

    Parameters
    ----------
    delegation_store:
        Optional :class:`~mcp_server.ucan_delegation.DelegationStore` for
        persisting delegation tokens across calls.  A fresh in-memory store
        is created when ``None``.
    revocation_list:
        Optional :class:`~mcp_server.ucan_delegation.RevocationList`.  A
        fresh empty list is used when ``None``.
    """

    def __init__(
        self,
        delegation_store: Optional[Any] = None,
        revocation_list: Optional[Any] = None,
    ) -> None:
        # Lazy import to avoid hard coupling
        try:
            from ipfs_datasets_py.mcp_server.ucan_delegation import (
                DelegationStore, RevocationList,
            )
            self._store = delegation_store or DelegationStore()
            self._revocations = revocation_list or RevocationList()
        except ImportError:
            self._store = None
            self._revocations = None
            logger.debug("ucan_delegation not available; delegation store disabled")

        self._policy_evaluator: Optional[Any] = None

    # ── compilation ───────────────────────────────────────────────────────────

    def compile_nl(
        self,
        nl_text: str,
        *,
        issuer_did: str = "did:example:root",
        audience_did: str = "did:example:agent",
        lifetime_seconds: int = 86_400,
    ) -> BridgeCompileResult:
        """Compile *nl_text* to a deontic policy + UCAN delegation tokens.

        This calls :func:`~logic.integration.nl_ucan_policy_compiler.compile_nl_to_ucan_policy`
        internally, then registers the resulting delegation tokens with the
        internal :class:`~mcp_server.ucan_delegation.DelegationStore`.

        Returns a :class:`BridgeCompileResult`.
        """
        result = BridgeCompileResult()

        # Stage 1: compile via the 3-stage pipeline
        try:
            from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
                compile_nl_to_ucan_policy,
            )
            compile_result = compile_nl_to_ucan_policy(
                nl_text,
                issuer_did=issuer_did,
                audience_did=audience_did,
            )
        except ImportError as exc:
            result.errors.append(f"NLUCANPolicyCompiler unavailable: {exc}")
            return result
        except Exception as exc:
            result.errors.append(f"Compilation error: {exc}")
            return result

        if compile_result is None:
            result.errors.append("compile_nl_to_ucan_policy returned None")
            return result

        result.success = compile_result.success
        result.errors.extend(compile_result.errors)
        result.warnings.extend(compile_result.warnings)

        # Extract policy CID from the policy object
        if compile_result.policy_result is not None:
            policy = compile_result.policy_result.policy
            if policy is not None:
                result.policy_cid = policy.policy_cid
                # Register with the internal policy evaluator
                self._register_policy(policy)

        # Stage 2: collect delegation tokens + store them
        if compile_result.bridge_result is not None:
            tokens = compile_result.bridge_result.tokens
            deny_caps = compile_result.bridge_result.deny_capabilities
            result.delegation_tokens = list(tokens)
            result.denial_count = len(deny_caps)

            if self._store is not None:
                for tok in tokens:
                    try:
                        self._store.add(tok)
                    except Exception as exc:
                        result.warnings.append(f"Failed to store token: {exc}")

            if tokens:
                result.leaf_token_cid = tokens[-1].cid

        return result

    # ── evaluation ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        policy_cid: str,
        *,
        tool: str,
        actor: Optional[str] = None,
        audience_did: Optional[str] = None,
        leaf_cid: Optional[str] = None,
        at_time: Optional[float] = None,
    ) -> BridgeEvaluationResult:
        """Evaluate *tool* access against *policy_cid* and optional UCAN chain.

        Parameters
        ----------
        policy_cid:
            CID of the policy to evaluate against.
        tool:
            The tool/action being requested.
        actor:
            Optional human-readable actor name (matched against deontic clauses).
        audience_did:
            DID of the requesting principal (for UCAN chain check).
        leaf_cid:
            CID of the leaf delegation token held by *audience_did*.
        at_time:
            Optional Unix timestamp for temporal evaluation.

        Returns
        -------
        BridgeEvaluationResult
        """
        result = BridgeEvaluationResult(policy_cid=policy_cid)

        # Check revocation first
        if leaf_cid is not None and self._revocations is not None:
            if self._revocations.is_revoked(leaf_cid):
                result.revoked = True
                result.decision = "deny"
                result.reason = f"Token {leaf_cid} has been revoked"
                result.ucan_allowed = False
                return result

        # Deontic policy evaluation
        try:
            from ipfs_datasets_py.mcp_server.temporal_policy import PolicyEvaluator
            from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, ALLOW, DENY
            evaluator = self._policy_evaluator or PolicyEvaluator()
            intent = IntentObject(tool=tool)
            decision_obj = evaluator.evaluate(intent, policy_cid, at_time=at_time, actor=actor)
            result.decision = decision_obj.decision
            result.reason = decision_obj.justification or ""
        except ImportError:
            result.decision = "deny"
            result.reason = "PolicyEvaluator unavailable"
        except Exception as exc:
            result.decision = "deny"
            result.reason = f"Policy evaluation error: {exc}"

        # UCAN chain check
        if leaf_cid is not None and audience_did is not None and self._store is not None:
            try:
                evaluator_ucan = self._store.to_evaluator()
                allowed, reason = evaluator_ucan.can_invoke(
                    audience_did,
                    f"logic/{tool}",
                    f"{tool}/invoke",
                    leaf_cid=leaf_cid,
                    at_time=at_time,
                )
                result.ucan_allowed = allowed
                if not allowed and result.decision != "deny":
                    result.decision = "deny"
                    result.reason = f"UCAN chain denied: {reason}"
            except Exception as exc:
                result.ucan_allowed = None
                logger.debug("UCAN chain evaluation skipped: %s", exc)

        return result

    # ── revocation helpers ────────────────────────────────────────────────────

    def revoke_token(self, cid: str) -> None:
        """Add *cid* to the internal revocation list."""
        if self._revocations is not None:
            self._revocations.revoke(cid)

    def is_revoked(self, cid: str) -> bool:
        """Return ``True`` if *cid* has been revoked."""
        if self._revocations is None:
            return False
        return self._revocations.is_revoked(cid)

    async def compile_and_sign(
        self,
        nl_text: str,
        *,
        audience_did: str = "did:example:agent",
        issuer_did: str = "did:example:root",
        lifetime_seconds: int = 86_400,
    ) -> "SignedPolicyResult":
        """Compile NL text to policy + sign each permission token with a DID key.

        Phase 2b of the NL→UCAN pipeline: after Stage 3 produces stub
        :class:`~ipfs_datasets_py.mcp_server.ucan_delegation.DelegationToken`
        objects, this method optionally calls
        :meth:`~ipfs_datasets_py.mcp_server.did_key_manager.DIDKeyManager.sign_delegation_token`
        to turn them into real (or stub-signed) UCAN JWTs.

        Parameters
        ----------
        nl_text:
            Natural-language policy text (e.g. *"Alice may read files"*).
        audience_did:
            DID of the agent receiving the delegations.
        issuer_did:
            DID of the issuing authority (used for stub tokens).
        lifetime_seconds:
            Token lifetime in seconds.

        Returns
        -------
        SignedPolicyResult
            Dataclass with ``.compile_result``, ``.signed_jwts`` list, and
            ``.signing_available`` flag.
        """
        compile_result = self.compile_nl(
            nl_text,
            issuer_did=issuer_did,
            audience_did=audience_did,
        )
        signed_jwts: List[str] = []
        signing_available = False

        try:
            from ipfs_datasets_py.mcp_server.did_key_manager import get_did_key_manager
            mgr = get_did_key_manager()
            signing_available = True
            for token in compile_result.delegation_tokens:
                jwt = await mgr.sign_delegation_token(
                    token,
                    audience_did=audience_did,
                    lifetime_seconds=lifetime_seconds,
                )
                signed_jwts.append(jwt)
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("DIDKeyManager unavailable for signing: %s", exc)

        return SignedPolicyResult(
            compile_result=compile_result,
            signed_jwts=signed_jwts,
            signing_available=signing_available,
        )

    # ── private helpers ───────────────────────────────────────────────────────

    def _register_policy(self, policy: Any) -> None:
        """Register *policy* with the internal PolicyEvaluator."""
        try:
            from ipfs_datasets_py.mcp_server.temporal_policy import PolicyEvaluator
            if self._policy_evaluator is None:
                self._policy_evaluator = PolicyEvaluator()
            self._policy_evaluator.register_policy(policy)
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("Could not register policy: %s", exc)


# ─── module-level singleton ───────────────────────────────────────────────────


_global_bridge: Optional[UCANPolicyBridge] = None


def get_ucan_policy_bridge() -> UCANPolicyBridge:
    """Return the process-global :class:`UCANPolicyBridge` (lazy-init)."""
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = UCANPolicyBridge()
    return _global_bridge


# ─── convenience wrapper ──────────────────────────────────────────────────────


def compile_and_evaluate(
    nl_policy_text: str,
    *,
    tool: str,
    actor: Optional[str] = None,
    issuer_did: str = "did:example:root",
    audience_did: str = "did:example:agent",
) -> BridgeEvaluationResult:
    """One-shot NL→policy→evaluate for *tool* by *actor*.

    Creates a :class:`UCANPolicyBridge`, compiles *nl_policy_text*, and
    immediately evaluates access for *tool*.

    Parameters
    ----------
    nl_policy_text:
        Plain-English policy string (one or more sentences).
    tool:
        The tool/action being checked.
    actor:
        Optional actor name for deontic clause matching.
    issuer_did:
        DID of the policy issuer.
    audience_did:
        DID of the requesting agent.

    Returns
    -------
    BridgeEvaluationResult
    """
    bridge = UCANPolicyBridge()
    compile_result = bridge.compile_nl(
        nl_policy_text,
        issuer_did=issuer_did,
        audience_did=audience_did,
    )
    return bridge.evaluate(
        compile_result.policy_cid,
        tool=tool,
        actor=actor,
        audience_did=audience_did,
        leaf_cid=compile_result.leaf_token_cid,
    )
