"""
MCP Tool: NL → UCAN Policy Compiler

Exposes the end-to-end natural language → DCEC → PolicyObject + UCAN
delegation pipeline as MCP server tools.

Tools
-----
- ``nl_compile_policy`` — compile NL sentences into a PolicyObject + UCAN tokens
- ``nl_evaluate_policy`` — evaluate an actor/action against a compiled policy
- ``nl_inspect_policy`` — return structured details about a compiled policy
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_async(coro):
    """Run a coroutine synchronously, compatible with Python 3.12."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _get_compiler_class():
    from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
        NLUCANPolicyCompiler,
        compile_nl_to_ucan_policy,
    )
    return NLUCANPolicyCompiler, compile_nl_to_ucan_policy


# ── in-memory policy registry ─────────────────────────────────────────────────
_COMPILED_POLICIES: Dict[str, Any] = {}


# ── tool implementations ──────────────────────────────────────────────────────

def nl_compile_policy(
    sentences: List[str],
    policy_id: Optional[str] = None,
    issuer_did: str = "did:key:root",
    default_actor: Optional[str] = None,
    valid_until: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compile natural language sentences into a PolicyObject + UCAN delegation tokens.

    Parameters
    ----------
    sentences:
        List of plain-English policy statements.
        Example: ["Alice must not delete records", "Bob is permitted to read files"]
    policy_id:
        Optional identifier for the policy.  Auto-generated if omitted.
    issuer_did:
        DID of the root issuer for UCAN delegation tokens.
    default_actor:
        Fallback actor when NL extraction fails.
    valid_until:
        Optional Unix timestamp for policy expiry.

    Returns
    -------
    dict
        ``success``, ``policy_id``, ``clause_count``, ``token_count``,
        ``denial_count``, ``errors``, ``warnings``, ``clauses`` list,
        ``tokens`` list.
    """
    try:
        _, compile_fn = _get_compiler_class()
        result = compile_fn(
            sentences,
            policy_id=policy_id,
            issuer_did=issuer_did,
            default_actor=default_actor,
            valid_until=valid_until,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_code": "COMPILER_ERROR",
        }

    # Serialise clauses
    clauses_out = []
    if result.policy_result and result.policy_result.clauses:
        for c in result.policy_result.clauses:
            clauses_out.append({
                "clause_type": getattr(c, "clause_type", None),
                "actor": getattr(c, "actor", None),
                "action": getattr(c, "action", None),
                "resource": getattr(c, "resource", None),
                "valid_until": getattr(c, "valid_until", None),
            })

    # Serialise UCAN tokens
    tokens_out = []
    if result.bridge_result and result.bridge_result.tokens:
        for t in result.bridge_result.tokens:
            caps = []
            for cap in getattr(t, "capabilities", []):
                caps.append({
                    "resource": getattr(cap, "resource", None),
                    "ability": getattr(cap, "ability", None),
                })
            tokens_out.append({
                "issuer": getattr(t, "issuer", None),
                "audience": getattr(t, "audience", None),
                "capabilities": caps,
                "expiry": getattr(t, "expiry", None),
                "cid": t.cid if hasattr(t, "cid") else None,
            })

    # Denials
    denials_out = []
    if result.bridge_result and result.bridge_result.denials:
        for d in result.bridge_result.denials:
            denials_out.append({
                "resource": getattr(d, "resource", None),
                "ability": getattr(d, "ability", None),
                "actor": getattr(d, "actor", None),
            })

    pid = result.metadata.get("policy_id", policy_id)

    # Cache for evaluate / inspect
    if result.success and pid:
        _COMPILED_POLICIES[pid] = result

    return {
        "success": result.success,
        "policy_id": pid,
        "clause_count": len(clauses_out),
        "token_count": len(tokens_out),
        "denial_count": len(denials_out),
        "clauses": clauses_out,
        "tokens": tokens_out,
        "denials": denials_out,
        "errors": result.errors,
        "warnings": result.warnings,
        "metadata": result.metadata,
    }


def nl_evaluate_policy(
    policy_id: str,
    actor: str,
    action: str,
    check_ucan: bool = False,
    audience_did: Optional[str] = None,
    resource: Optional[str] = None,
    ability: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate an actor/action pair against a previously compiled policy.

    Parameters
    ----------
    policy_id:
        ID returned by ``nl_compile_policy``.
    actor:
        Name/DID of the actor to check.
    action:
        Action name to evaluate.
    check_ucan:
        If *True*, also check the UCAN delegation evaluator.
    audience_did:
        DID to use for UCAN check (defaults to ``did:key:<actor>``).
    resource:
        Resource name for UCAN check (defaults to ``logic/<action>``).
    ability:
        Ability string for UCAN check (defaults to ``<action>/invoke``).

    Returns
    -------
    dict
        ``policy_allowed``, ``ucan_allowed`` (if requested), ``policy_id``.
    """
    compiled = _COMPILED_POLICIES.get(policy_id)
    if compiled is None:
        return {
            "success": False,
            "error": f"Policy '{policy_id}' not found.  Call nl_compile_policy first.",
            "error_code": "POLICY_NOT_FOUND",
        }

    policy = compiled.policy
    policy_allowed = None
    if policy is not None:
        try:
            policy_allowed = policy.evaluate(actor, action)
        except Exception as exc:
            policy_allowed = None
            logger.warning("Policy evaluate failed: %s", exc)

    ucan_allowed = None
    if check_ucan and compiled.delegation_evaluator is not None:
        ev = compiled.delegation_evaluator
        res = resource or f"logic/{action}"
        abl = ability or f"{action}/invoke"
        aud = audience_did or f"did:key:{actor}"
        try:
            ucan_allowed = ev.can_invoke(aud, res, abl)
        except Exception as exc:
            ucan_allowed = None
            logger.warning("UCAN evaluate failed: %s", exc)

    result = {
        "success": True,
        "policy_id": policy_id,
        "actor": actor,
        "action": action,
        "policy_allowed": policy_allowed,
    }
    if check_ucan:
        result["ucan_allowed"] = ucan_allowed
    return result


def nl_inspect_policy(policy_id: str) -> Dict[str, Any]:
    """
    Return structured details about a compiled policy.

    Parameters
    ----------
    policy_id:
        ID returned by ``nl_compile_policy``.

    Returns
    -------
    dict
        Full policy description including clauses, tokens, sentences, metadata.
    """
    compiled = _COMPILED_POLICIES.get(policy_id)
    if compiled is None:
        return {
            "success": False,
            "error": f"Policy '{policy_id}' not found.",
            "error_code": "POLICY_NOT_FOUND",
        }

    clauses = []
    if compiled.policy_result and compiled.policy_result.clauses:
        for c in compiled.policy_result.clauses:
            clauses.append({
                "clause_type": getattr(c, "clause_type", None),
                "actor": getattr(c, "actor", None),
                "action": getattr(c, "action", None),
                "resource": getattr(c, "resource", None),
            })

    tokens = []
    if compiled.bridge_result and compiled.bridge_result.tokens:
        for t in compiled.bridge_result.tokens:
            tokens.append({
                "issuer": getattr(t, "issuer", None),
                "audience": getattr(t, "audience", None),
                "capabilities": [
                    {"resource": c.resource, "ability": c.ability}
                    for c in getattr(t, "capabilities", [])
                ],
                "cid": t.cid if hasattr(t, "cid") else None,
            })

    return {
        "success": True,
        "policy_id": policy_id,
        "sentences": compiled.input_sentences,
        "clauses": clauses,
        "tokens": tokens,
        "denials": [
            {"resource": d.resource, "ability": d.ability, "actor": d.actor}
            for d in compiled.deny_capabilities
        ],
        "errors": compiled.errors,
        "warnings": compiled.warnings,
        "metadata": compiled.metadata,
    }


# ── list of exported tools for MCP registration ──────────────────────────────
TOOL_FUNCTIONS = [
    nl_compile_policy,
    nl_evaluate_policy,
    nl_inspect_policy,
]
