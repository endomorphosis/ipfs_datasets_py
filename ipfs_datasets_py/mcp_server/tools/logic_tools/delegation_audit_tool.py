"""CH144 — MCP Tool: Delegation Manager + Policy Audit Log

Exposes delegation lifecycle management and policy audit log querying as
MCP server tools.

Tools
-----
- ``delegation_add_token``   — add a UCAN delegation token to the manager
- ``delegation_can_invoke``  — check whether a principal can invoke a tool
- ``delegation_revoke``      — revoke a single token CID
- ``delegation_revoke_chain``— revoke an entire delegation chain
- ``delegation_get_metrics`` — return delegation manager metrics
- ``audit_log_recent``       — return recent audit log entries
- ``audit_log_stats``        — return audit log statistics
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_manager():
    from ipfs_datasets_py.mcp_server.ucan_delegation import get_delegation_manager
    return get_delegation_manager()


def _get_audit_log():
    from ipfs_datasets_py.mcp_server.policy_audit_log import get_audit_log
    return get_audit_log()


# ---------------------------------------------------------------------------
# delegation tools
# ---------------------------------------------------------------------------

def delegation_add_token(
    issuer: str,
    audience: str,
    resource: str = "*",
    ability: str = "*",
    lifetime_seconds: int = 86_400,
    proof_cid: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Add a delegation token to the global :class:`DelegationManager`.

    Parameters
    ----------
    issuer:
        DID of the token issuer.
    audience:
        DID of the token audience (recipient).
    resource:
        Capability resource pattern (default ``"*"``).
    ability:
        Capability ability pattern (default ``"*"``).
    lifetime_seconds:
        Token validity window in seconds from now (default 86400).
    proof_cid:
        Optional CID of the parent proof token.

    Returns
    -------
    dict with ``cid`` of the newly-added token.
    """
    import time
    try:
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, Capability,
        )
        mgr = _get_manager()
        cap = Capability(resource=resource, ability=ability)
        now = time.time()
        token = DelegationToken(
            issuer=issuer,
            audience=audience,
            capabilities=[cap],
            expiry=now + lifetime_seconds,
            proof_cid=proof_cid,
        )
        cid = mgr.add(token)
        return {"status": "ok", "cid": cid}
    except Exception as exc:
        logger.error("delegation_add_token failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def delegation_can_invoke(
    principal: str,
    tool: str,
    resource: str = "*",
    leaf_cid: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Check whether *principal* can invoke *tool*.

    Parameters
    ----------
    principal:
        DID or actor name.
    tool:
        Tool name / ability.
    resource:
        Resource pattern (default ``"*"``).
    leaf_cid:
        CID of the leaf delegation token held by *principal*.

    Returns
    -------
    dict with ``allowed`` (bool) and ``reason`` (str).
    """
    try:
        mgr = _get_manager()
        audit = _get_audit_log()
        allowed, reason = mgr.can_invoke_audited(
            principal,
            resource,
            tool,
            leaf_cid=leaf_cid or principal,
            audit_log=audit,
            policy_cid="delegation_tool",
            intent_cid=f"invoke:{tool}",
        )
        return {"status": "ok", "allowed": allowed, "reason": reason}
    except Exception as exc:
        logger.error("delegation_can_invoke failed: %s", exc)
        return {"status": "error", "error": str(exc), "allowed": False}


def delegation_revoke(token_cid: str, **kwargs: Any) -> Dict[str, Any]:
    """Revoke a single delegation token by CID.

    Parameters
    ----------
    token_cid:
        CID of the token to revoke.

    Returns
    -------
    dict with ``status``.
    """
    try:
        mgr = _get_manager()
        mgr.revoke(token_cid)
        return {"status": "ok", "revoked_cid": token_cid}
    except Exception as exc:
        logger.error("delegation_revoke failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def delegation_revoke_chain(root_cid: str, **kwargs: Any) -> Dict[str, Any]:
    """Revoke an entire delegation chain rooted at *root_cid*.

    Parameters
    ----------
    root_cid:
        CID of the root token in the chain.

    Returns
    -------
    dict with ``status`` and ``revoked_count``.
    """
    try:
        mgr = _get_manager()
        count = mgr.revoke_chain(root_cid)
        return {"status": "ok", "root_cid": root_cid, "revoked_count": count}
    except Exception as exc:
        logger.error("delegation_revoke_chain failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def delegation_get_metrics(**kwargs: Any) -> Dict[str, Any]:
    """Return a snapshot of the global :class:`DelegationManager` metrics.

    Returns
    -------
    dict with ``token_count``, ``revoked_count``, ``has_path``.
    """
    try:
        mgr = _get_manager()
        metrics = mgr.get_metrics()
        metrics["status"] = "ok"
        return metrics
    except Exception as exc:
        logger.error("delegation_get_metrics failed: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# audit log tools
# ---------------------------------------------------------------------------

def audit_log_recent(n: int = 20, **kwargs: Any) -> Dict[str, Any]:
    """Return the *n* most recent audit log entries.

    Parameters
    ----------
    n:
        Number of entries to return (default 20).

    Returns
    -------
    dict with ``entries`` list.
    """
    try:
        log = _get_audit_log()
        entries = [e.to_dict() for e in log.recent(n)]
        return {"status": "ok", "entries": entries, "count": len(entries)}
    except Exception as exc:
        logger.error("audit_log_recent failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def audit_log_stats(**kwargs: Any) -> Dict[str, Any]:
    """Return statistics from the global :class:`PolicyAuditLog`.

    Returns
    -------
    dict with ``total_recorded``, ``by_decision``, ``enabled``.
    """
    try:
        log = _get_audit_log()
        stats = log.stats()
        stats["status"] = "ok"
        return stats
    except Exception as exc:
        logger.error("audit_log_stats failed: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool registry for MCP server discovery
# ---------------------------------------------------------------------------

DELEGATION_AUDIT_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "delegation_add_token",
        "description": "Add a UCAN delegation token to the global DelegationManager",
        "function": delegation_add_token,
    },
    {
        "name": "delegation_can_invoke",
        "description": "Check whether a principal can invoke a tool via UCAN delegation",
        "function": delegation_can_invoke,
    },
    {
        "name": "delegation_revoke",
        "description": "Revoke a single delegation token CID",
        "function": delegation_revoke,
    },
    {
        "name": "delegation_revoke_chain",
        "description": "Revoke an entire delegation chain rooted at a CID",
        "function": delegation_revoke_chain,
    },
    {
        "name": "delegation_get_metrics",
        "description": "Return delegation manager metrics",
        "function": delegation_get_metrics,
    },
    {
        "name": "audit_log_recent",
        "description": "Return the N most recent policy audit log entries",
        "function": audit_log_recent,
    },
    {
        "name": "audit_log_stats",
        "description": "Return statistics from the policy audit log",
        "function": audit_log_stats,
    },
]
