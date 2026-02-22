"""
End-to-End NL → DCEC → UCAN Policy Compiler

This module provides the high-level ``NLUCANPolicyCompiler`` class that
orchestrates the full pipeline:

1. **NL parsing**: raw text → DCEC ``DeonticFormula`` objects
   (via ``CEC.nl.nl_to_policy_compiler.NLToDCECCompiler``)
2. **Policy assembly**: DCEC formulas → ``PolicyObject`` with ``PolicyClause``
   list  (via ``mcp_server.temporal_policy``)
3. **UCAN bridge**: DCEC formulas → ``DelegationToken`` objects with explicit
   deny markers  (via ``CEC.nl.dcec_to_ucan_bridge.DCECToUCANBridge``)
4. **Evaluation**: ``PolicyEvaluator`` + ``DelegationEvaluator`` for runtime
   access decisions

Usage example::

    from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
        NLUCANPolicyCompiler, compile_nl_to_ucan_policy,
    )

    compiler = NLUCANPolicyCompiler(issuer_did="did:key:org")
    result = compiler.compile([
        "Alice must not delete records",
        "Bob is permitted to read files",
        "Carol is required to audit all access events",
    ])

    assert result.success
    # Policy-level check (deontic)
    print(result.policy_result.policy.evaluate("bob", "read"))   # True
    print(result.policy_result.policy.evaluate("alice", "delete"))  # False

    # UCAN-level delegation check
    evaluator = result.delegation_evaluator
    print(evaluator.can_invoke("did:key:bob", "logic/read", "read/invoke"))  # True

No external dependencies beyond stdlib + sibling logic modules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NLUCANCompilerResult:
    """
    Combined result of the full NL → Policy + UCAN pipeline.

    Attributes
    ----------
    success:
        ``True`` if at least a policy *or* UCAN chain was produced.
    input_sentences:
        Original input sentences.
    policy_result:
        :class:`~logic.CEC.nl.nl_to_policy_compiler.CompilationResult` from
        the policy compilation stage.
    bridge_result:
        :class:`~logic.CEC.nl.dcec_to_ucan_bridge.BridgeResult` from the
        UCAN bridge stage.
    delegation_evaluator:
        Pre-populated :class:`~mcp_server.ucan_delegation.DelegationEvaluator`
        ready for runtime access decisions.
    errors:
        Aggregated error messages from all stages.
    warnings:
        Aggregated warnings from all stages.
    metadata:
        Arbitrary pipeline metadata (timing, counts, etc.).
    """
    success: bool = False
    input_sentences: List[str] = field(default_factory=list)
    policy_result: Any = None    # CompilationResult | None
    bridge_result: Any = None    # BridgeResult | None
    delegation_evaluator: Any = None   # DelegationEvaluator | None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    # ── convenience accessors ────────────────────────────────────────────────

    @property
    def policy(self):
        """Shortcut: policy_result.policy or None."""
        if self.policy_result is not None:
            return getattr(self.policy_result, "policy", None)
        return None

    @property
    def delegation_chain(self):
        """Shortcut: bridge_result.build_chain() or None."""
        if self.bridge_result is not None and self.bridge_result.tokens:
            try:
                return self.bridge_result.build_chain()
            except Exception:
                return None
        return None

    @property
    def deny_capabilities(self) -> List[Any]:
        """Shortcut: bridge_result.denials or []."""
        if self.bridge_result is not None:
            return list(self.bridge_result.denials)
        return []


class NLUCANPolicyCompiler:
    """
    Full NL → DCEC → Policy + UCAN pipeline compiler.

    Parameters
    ----------
    policy_id:
        Identifier for the produced :class:`PolicyObject`.
    issuer_did:
        DID of the delegation issuer (used in ``DelegationToken.issuer``).
    default_actor:
        Fallback actor name when NL extraction fails.
    valid_until:
        Optional Unix timestamp for policy/token expiry.
    strict:
        If *True*, the first error aborts the pipeline with an exception.

    Example
    -------
    >>> compiler = NLUCANPolicyCompiler(policy_id="acl-001")
    >>> result = compiler.compile(["Alice must not delete records"])
    >>> result.success
    True
    >>> result.policy.evaluate("alice", "delete")
    False
    """

    def __init__(
        self,
        policy_id: Optional[str] = None,
        issuer_did: str = "did:key:root",
        default_actor: Optional[str] = None,
        valid_until: Optional[float] = None,
        strict: bool = False,
    ) -> None:
        self.policy_id = policy_id
        self.issuer_did = issuer_did
        self.default_actor = default_actor
        self.valid_until = valid_until
        self.strict = strict

    # ── stage helpers ────────────────────────────────────────────────────────

    def _stage_nl_to_policy(self, sentences: List[str], policy_id: str):
        from ipfs_datasets_py.logic.CEC.nl.nl_to_policy_compiler import NLToDCECCompiler
        compiler = NLToDCECCompiler(
            policy_id=policy_id,
            default_actor=self.default_actor,
            valid_until=self.valid_until,
            strict=self.strict,
        )
        return compiler.compile(sentences, policy_id=policy_id)

    def _stage_dcec_to_ucan(self, dcec_formulas: List[Any]):
        from ipfs_datasets_py.logic.CEC.nl.dcec_to_ucan_bridge import DCECToUCANBridge
        expiry_offset = None
        if self.valid_until is not None:
            import time
            expiry_offset = max(0.0, self.valid_until - time.time())
        bridge = DCECToUCANBridge(
            issuer_did=self.issuer_did,
            expiry_offset=expiry_offset,
        )
        return bridge.map_formulas(dcec_formulas)

    def _build_evaluator(self, bridge_result) -> Any:
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationEvaluator
        ev = DelegationEvaluator()
        for token in bridge_result.tokens:
            ev.add_token(token)
        return ev

    # ── public interface ─────────────────────────────────────────────────────

    def compile(
        self,
        sentences: List[str],
        policy_id: Optional[str] = None,
    ) -> NLUCANCompilerResult:
        """
        Compile *sentences* through the full NL → Policy + UCAN pipeline.

        Parameters
        ----------
        sentences:
            Plain-English policy statements.
        policy_id:
            Override the instance-level ``policy_id``.

        Returns
        -------
        NLUCANCompilerResult
            Combined result with policy, bridge tokens, and a ready-to-use
            delegation evaluator.
        """
        pid = policy_id or self.policy_id
        if pid is None:
            import hashlib
            pid = "nl-ucan-" + hashlib.sha256(
                "\n".join(sentences).encode()
            ).hexdigest()[:10]

        overall = NLUCANCompilerResult(input_sentences=list(sentences))
        overall.metadata["policy_id"] = pid
        overall.metadata["sentence_count"] = len(sentences)

        # ── Stage 1: NL → DCEC + PolicyObject ───────────────────────────────
        try:
            policy_result = self._stage_nl_to_policy(sentences, pid)
        except Exception as exc:
            overall.add_error(f"Stage 1 (NL→Policy) failed: {exc}")
            if self.strict:
                raise
            return overall

        overall.policy_result = policy_result
        overall.errors.extend(policy_result.errors)
        overall.warnings.extend(policy_result.warnings)
        overall.metadata["policy_clauses"] = len(policy_result.clauses)
        overall.metadata["dcec_formulas"] = len(policy_result.dcec_formulas)

        if not policy_result.dcec_formulas:
            overall.add_error("No DCEC formulas produced; aborting UCAN stage.")
            if self.strict:
                raise ValueError("\n".join(overall.errors))
            return overall

        # ── Stage 2: DCEC → UCAN delegation tokens ──────────────────────────
        try:
            bridge_result = self._stage_dcec_to_ucan(policy_result.dcec_formulas)
        except Exception as exc:
            overall.add_error(f"Stage 2 (DCEC→UCAN) failed: {exc}")
            if self.strict:
                raise
            # Still mark partial success if policy was produced
            overall.success = policy_result.success
            return overall

        overall.bridge_result = bridge_result
        overall.errors.extend(bridge_result.errors)
        overall.metadata["ucan_tokens"] = len(bridge_result.tokens)
        overall.metadata["ucan_denials"] = len(bridge_result.denials)

        # ── Stage 3: Build DelegationEvaluator ──────────────────────────────
        try:
            overall.delegation_evaluator = self._build_evaluator(bridge_result)
        except Exception as exc:
            overall.add_warning(f"Stage 3 (evaluator) failed: {exc}")

        overall.success = policy_result.success or bridge_result.success
        return overall


# ── one-shot convenience wrapper ─────────────────────────────────────────────

def compile_nl_to_ucan_policy(
    sentences: List[str],
    *,
    policy_id: Optional[str] = None,
    issuer_did: str = "did:key:root",
    default_actor: Optional[str] = None,
    valid_until: Optional[float] = None,
) -> NLUCANCompilerResult:
    """
    One-shot convenience wrapper for the full NL → Policy + UCAN pipeline.

    Example
    -------
    >>> result = compile_nl_to_ucan_policy(
    ...     ["Alice must not delete records", "Bob may read files"],
    ...     policy_id="data-access-policy",
    ... )
    >>> result.success
    True
    >>> result.policy.evaluate("alice", "delete")
    False
    """
    compiler = NLUCANPolicyCompiler(
        policy_id=policy_id,
        issuer_did=issuer_did,
        default_actor=default_actor,
        valid_until=valid_until,
    )
    return compiler.compile(sentences, policy_id=policy_id)
