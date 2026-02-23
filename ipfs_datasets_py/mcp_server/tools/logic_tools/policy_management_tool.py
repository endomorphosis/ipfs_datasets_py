"""MCP++ Policy Management Tools.

Exposes the :class:`~ipfs_datasets_py.mcp_server.nl_ucan_policy.PolicyRegistry`
(NL→UCAN policy registration / evaluation) and the
:class:`~ipfs_datasets_py.mcp_server.interface_descriptor.InterfaceRepository`
(IDL-style interface registration / compatibility checks) as callable MCP tools
so that AI agents can inspect and manage policies at runtime.

All mutations are in-process (no persistent storage by default) and operate on
the global singletons returned by :func:`get_policy_registry` and a
module-level :class:`InterfaceRepository` instance.

Tool Summary
------------
``policy_register``    — compile and register an NL policy.
``policy_list``        — list registered policy names.
``policy_remove``      — remove a registered policy.
``policy_evaluate``    — evaluate an actor+tool pair against a policy.
``interface_register`` — register an :class:`InterfaceDescriptor` by name.
``interface_list``     — list registered interface CIDs / names.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Lazy singletons — imported at call-time to avoid circular imports at module
# load time.
# ---------------------------------------------------------------------------

_interface_repo: Any = None  # InterfaceRepository singleton


def _get_interface_repo() -> Any:
    global _interface_repo
    if _interface_repo is None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceRepository
        _interface_repo = InterfaceRepository()
    return _interface_repo


# ---------------------------------------------------------------------------
# Policy tools
# ---------------------------------------------------------------------------


def policy_register(name: str, nl_policy: str, description: str = "") -> Dict[str, Any]:
    """Register (or replace) a named natural-language UCAN policy.

    The policy text is compiled to deontic :class:`PolicyClause` objects and
    stored in the global :class:`PolicyRegistry`.  The returned dict contains
    the source CID (a multiformats CIDv1 when the *multiformats* package is
    installed) and the number of compiled clauses.

    Args:
        name: Unique policy name (e.g. ``"admin_only"``).
        nl_policy: Raw natural-language policy string.
        description: Optional human-readable label.

    Returns:
        Dict with ``name``, ``source_cid``, ``clause_count``, ``status``.
    """
    try:
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import get_policy_registry
        registry = get_policy_registry()
        compiled = registry.register(name, nl_policy, description=description)
        return {
            "status": "registered",
            "name": name,
            "source_cid": compiled.source_cid,
            "clause_count": len(compiled.policy.clauses),
        }
    except Exception as exc:
        return {"status": "error", "name": name, "error": str(exc)}


def policy_list() -> Dict[str, Any]:
    """List all registered NL policy names.

    Returns:
        Dict with ``names`` (list of str) and ``count``.
    """
    try:
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import get_policy_registry
        registry = get_policy_registry()
        names = registry.list_names()
        return {"status": "ok", "names": names, "count": len(names)}
    except Exception as exc:
        return {"status": "error", "names": [], "count": 0, "error": str(exc)}


def policy_remove(name: str) -> Dict[str, Any]:
    """Remove a named policy from the global registry.

    Args:
        name: Policy name to remove.

    Returns:
        Dict with ``name``, ``removed`` (bool), ``status``.
    """
    try:
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import get_policy_registry
        registry = get_policy_registry()
        removed = registry.remove(name)
        return {"status": "ok", "name": name, "removed": removed}
    except Exception as exc:
        return {"status": "error", "name": name, "removed": False, "error": str(exc)}


def policy_evaluate(
    name: str,
    actor: str,
    tool_name: str,
) -> Dict[str, Any]:
    """Evaluate whether *actor* may invoke *tool_name* under policy *name*.

    Uses the :class:`UCANPolicyGate` from :mod:`nl_ucan_policy`.

    Args:
        name: Policy name to evaluate against (must be registered).
        actor: Actor DID / identifier string.
        tool_name: Tool name the actor wishes to invoke.

    Returns:
        Dict with ``verdict`` (``"allow"`` / ``"deny"``), ``policy_name``,
        ``actor``, ``tool_name``, ``status``.
    """
    try:
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import get_policy_registry, UCANPolicyGate
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, artifact_cid
        registry = get_policy_registry()
        gate = UCANPolicyGate(registry=registry)
        intent = IntentObject(interface_cid="", tool=tool_name, input_cid="")
        decision = gate.evaluate(intent, actor=actor, policy_name=name)
        return {
            "status": "ok",
            "verdict": decision.decision,  # DecisionObject uses 'decision' not 'verdict'
            "policy_name": name,
            "actor": actor,
            "tool_name": tool_name,
        }
    except Exception as exc:
        return {
            "status": "error",
            "verdict": "error",
            "policy_name": name,
            "actor": actor,
            "tool_name": tool_name,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Interface descriptor tools
# ---------------------------------------------------------------------------


def interface_register(
    name: str,
    version: str = "1.0.0",
    methods: Optional[List[Dict[str, Any]]] = None,
    description: str = "",
) -> Dict[str, Any]:
    """Register an MCP++ Interface Descriptor.

    Args:
        name: Interface name (e.g. ``"ipfs_datasets/v1"``).
        version: Semantic version string.
        methods: Optional list of method dicts with ``name``, ``params``,
            ``returns`` fields.
        description: Human-readable description.

    Returns:
        Dict with ``interface_cid``, ``name``, ``version``, ``status``.
    """
    try:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor,
            MethodSignature,
        )
        sigs = []
        for m in (methods or []):
            sigs.append(MethodSignature(
                name=m.get("name", ""),
                input_schema=m.get("params", m.get("input_schema", {})),
                output_schema=m.get("returns", m.get("output_schema", {})),
            ))
        desc = InterfaceDescriptor(
            name=name,
            namespace=name,  # use name as namespace default
            version=version,
            methods=sigs,
        )
        repo = _get_interface_repo()
        cid = repo.register(desc)
        return {"status": "registered", "interface_cid": cid, "name": name, "version": version}
    except Exception as exc:
        return {"status": "error", "name": name, "error": str(exc)}


def interface_list() -> Dict[str, Any]:
    """List all registered Interface Descriptor CIDs.

    Returns:
        Dict with ``interface_cids`` (list of str) and ``count``.
    """
    try:
        repo = _get_interface_repo()
        cids = repo.list()
        return {"status": "ok", "interface_cids": cids, "count": len(cids)}
    except Exception as exc:
        return {"status": "error", "interface_cids": [], "count": 0, "error": str(exc)}


__all__ = [
    "policy_register",
    "policy_list",
    "policy_remove",
    "policy_evaluate",
    "interface_register",
    "interface_list",
]
