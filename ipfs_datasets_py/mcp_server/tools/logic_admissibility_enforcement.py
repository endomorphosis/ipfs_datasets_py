"""MCP tools for hardened intent authorization evaluation (LIG-038).

Interface: ``MCPIntentAuthorization@1``

Thin MCP surface over :mod:`ipfs_datasets_py.logic.admissibility.api`.
Handlers evaluate exact-context authorization requests and verify receipts
through stable redacted schemas.  Evaluation remains distinct from tool
execution.

Hard invariants
---------------
* Handlers never execute skill text, prompt bodies, MCP tool targets, shell,
  or eval.
* Handlers never issue or consume a dispatch capability (that is reserved for
  the pre-dispatch enforcement leaf).
* Malformed input, unknown fields that break validation, and backend-
  unavailable paths fail closed (never silent allow).
* Responses never include raw prompts, unrestricted arguments, secrets,
  witnesses, or private formulas.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

MCP_INTENT_AUTHORIZATION_INTERFACE: Final = "MCPIntentAuthorization@1"
MCP_INTENT_AUTHORIZATION_SCHEMA_VERSION: Final = "mcp-intent-authorization/v1"

TOOL_NAMES: Final[tuple[str, ...]] = (
    "evaluate_intent_authorization",
    "verify_authorization_receipt",
    "authorization_api_capabilities",
)

# Capability / execution verbs that this module must never expose as tools.
FORBIDDEN_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "issue_dispatch_capability",
        "consume_dispatch_capability",
        "execute_authorized_target",
        "dispatch_tool",
        "run_tool",
        "invoke_tool",
    }
)

TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "evaluate_intent_authorization": {
        "name": "evaluate_intent_authorization",
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "description": (
            "Evaluate an exact-context authorization request. Requires explicit "
            "source/actor/audience/tool/arguments/environment and exact "
            "policy/corpus/revocation roots. Returns allow/reject/abstain "
            "compatibility plus typed decision/receipt refs with redacted views. "
            "Never executes the target and never issues/consumes a dispatch "
            "capability."
        ),
        "parameters": {
            "type": "object",
            "required": [
                "source",
                "actor",
                "audience",
                "tool",
                "arguments",
                "environment",
                "policy_root",
                "corpus_roots",
                "revocation_root",
            ],
            "properties": {
                "source": {
                    "description": "Source binding (kind + source_ref) or string ref.",
                },
                "actor": {
                    "description": "Actor binding or actor_id string.",
                },
                "audience": {
                    "description": "Audience binding or audience_id string.",
                },
                "tool": {
                    "description": "Tool binding (tool_id, tool_version) or tool_id.",
                },
                "arguments": {
                    "description": (
                        "Redacted argument map or ArgumentCommitment. "
                        "Raw secrets/prompts are rejected."
                    ),
                },
                "environment": {
                    "description": (
                        "Environment binding with environment_id and "
                        "snapshot_digest (sha256:<hex>)."
                    ),
                },
                "policy_root": {"type": "string"},
                "corpus_roots": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "revocation_root": {"type": "string"},
                "legal_corpus_ref": {"type": "string"},
                "security_corpus_ref": {"type": "string"},
                "intent_corpus_ref": {"type": "string"},
                "profile": {"type": "string", "default": "legal-strict"},
                "invocation": {
                    "description": "Optional pre-built envelope (still requires explicit fields).",
                },
                "budget": {"type": "object"},
            },
        },
        "returns": {
            "success": "bool",
            "status": "allow | reject | abstain | error",
            "compatibility": "allow | reject | abstain",
            "decision_ref": "typed AuthorizationDecision@1 ref when available",
            "receipt_ref": "typed DecisionReceipt@1 ref when available",
            "decision_view": "redacted decision view",
            "receipt_view": "redacted receipt view",
            "executed": "always false",
            "capability_issued": "always false",
            "capability_consumed": "always false",
        },
    },
    "verify_authorization_receipt": {
        "name": "verify_authorization_receipt",
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "description": (
            "Verify a DecisionReceipt@1 without consuming any dispatch "
            "capability. Optionally pins expected policy/corpus/revocation "
            "roots and actor/audience. Never executes a target."
        ),
        "parameters": {
            "type": "object",
            "required": ["receipt"],
            "properties": {
                "receipt": {
                    "description": "DecisionReceipt@1 map.",
                },
                "expected_policy_root": {"type": "string"},
                "expected_corpus_roots": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "expected_revocation_root": {"type": "string"},
                "expected_audience": {"type": "string"},
                "expected_actor": {"type": "string"},
                "now": {"type": "string"},
            },
        },
        "returns": {
            "success": "bool",
            "status": "allow | reject | abstain | error",
            "compatibility": "allow | reject | abstain",
            "receipt_ref": "typed receipt ref when valid",
            "receipt_view": "redacted receipt view",
            "executed": "always false",
            "capability_issued": "always false",
            "capability_consumed": "always false",
        },
    },
    "authorization_api_capabilities": {
        "name": "authorization_api_capabilities",
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "description": (
            "Describe the MCP authorization surface without evaluating or "
            "executing anything."
        ),
        "parameters": {"type": "object", "properties": {}},
        "returns": {
            "success": "bool",
            "tools": "list of tool names",
            "forbidden_tools": "capability/execution verbs this module will not host",
            "executed": "always false",
        },
    },
}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _base_response(tool: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "executed": False,
        "capability_issued": False,
        "capability_consumed": False,
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "schema_version": MCP_INTENT_AUTHORIZATION_SCHEMA_VERSION,
        "tool": tool,
    }
    payload.update(extra)
    # Hard safety: never allow execution or capability flags to flip true.
    payload["executed"] = False
    payload["capability_issued"] = False
    payload["capability_consumed"] = False
    return payload


def _ok(tool: str, **extra: Any) -> dict[str, Any]:
    return _base_response(tool, success=True, status="ok", **extra)


def _fail(
    tool: str,
    *,
    status: str = "reject",
    error: str,
    error_type: str = "fail_closed",
    **extra: Any,
) -> dict[str, Any]:
    """Structured fail-closed response (never status=allow)."""

    if status == "allow":
        status = "reject"
        error = f"{error}; coerced away from allow (fail closed)"
    return _base_response(
        tool,
        success=False,
        status=status,
        compatibility="reject" if status == "reject" else "abstain",
        error=error,
        error_type=error_type,
        **extra,
    )


def _project_api_result(tool: str, result: Any) -> dict[str, Any]:
    """Map AuthorizationAPIResult to an MCP tool response."""

    from ipfs_datasets_py.logic.admissibility.api import AuthorizationAPIResult
    from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

    if not isinstance(result, AuthorizationAPIResult):
        return _fail(
            tool,
            status="error",
            error="authorization API returned unexpected type; fail closed",
            error_type="invalid_result",
        )

    payload = result.to_dict()
    compatibility = payload.get("compatibility") or payload.get("wire_status")
    if compatibility not in {
        AdmissibilityStatus.ALLOW.value,
        AdmissibilityStatus.REJECT.value,
        AdmissibilityStatus.ABSTAIN.value,
    }:
        return _fail(
            tool,
            status="reject",
            error=f"unknown compatibility {compatibility!r}; fail closed",
            error_type="invalid_compatibility",
        )

    # Never upgrade a non-allow internal status.
    success = bool(result.is_allow)
    status = compatibility
    if result.error and not success:
        # Prefer explicit error status only when compatibility is abstain and
        # the error type indicates a hard failure path.
        if result.error_type in {
            "backend_unavailable",
            "AuthorizationAPIValidationError",
            "AuthorizationServiceError",
            "fail_closed",
        } and compatibility == AdmissibilityStatus.ABSTAIN.value:
            status = "error" if result.error_type != "AuthorizationAPIValidationError" else "reject"
            if result.error_type == "AuthorizationAPIValidationError":
                status = "reject"
            elif result.error_type in {"backend_unavailable", "fail_closed"}:
                status = "abstain"

    return _base_response(
        tool,
        success=success,
        status=status if status != "ok" else compatibility,
        compatibility=compatibility,
        internal_status=payload.get("status"),
        reasons=payload.get("reasons") or [],
        reason_codes=payload.get("reason_codes") or [],
        decision_ref=payload.get("decision_ref"),
        receipt_ref=payload.get("receipt_ref"),
        decision_view=payload.get("decision_view"),
        receipt_view=payload.get("receipt_view"),
        context_view=payload.get("context_view"),
        roots_view=payload.get("roots_view"),
        profile_id=payload.get("profile_id") or "",
        error=payload.get("error") or "",
        error_type=payload.get("error_type") or "",
        diagnostics=payload.get("diagnostics") or [],
        api_interface=payload.get("interface"),
        api_schema_version=payload.get("schema_version"),
    )


def _reject_forbidden_kwargs(kwargs: Mapping[str, Any]) -> str | None:
    forbidden = {
        "derive_capability_on_allow",
        "issue_capability",
        "consume_capability",
        "execute_target",
        "dispatch",
        "capability_token",
        "dispatch_capability",
    }
    present = sorted(k for k in kwargs if k in forbidden)
    if present:
        return (
            "forbidden capability/execution parameter(s): "
            + ", ".join(present)
            + "; fail closed"
        )
    # Reject truthy attempt via alternate names.
    for key in ("execute", "run", "invoke", "dispatch_now"):
        if kwargs.get(key):
            return f"forbidden execution flag {key!r}; fail closed"
    return None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def evaluate_intent_authorization(
    source: Any = None,
    actor: Any = None,
    audience: Any = None,
    tool: Any = None,
    arguments: Any = None,
    environment: Any = None,
    policy_root: Any = None,
    corpus_roots: Any = None,
    revocation_root: Any = None,
    *,
    legal_corpus_ref: str = "",
    security_corpus_ref: str = "",
    intent_corpus_ref: str = "",
    profile: str | None = None,
    invocation: Any = None,
    budget: Mapping[str, Any] | None = None,
    deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Evaluate authorization; never executes targets or issues capabilities."""

    tool_name = "evaluate_intent_authorization"
    forbidden = _reject_forbidden_kwargs(kwargs)
    if forbidden:
        return _fail(tool_name, error=forbidden, error_type="forbidden_parameter")

    required = {
        "source": source,
        "actor": actor,
        "audience": audience,
        "tool": tool,
        "arguments": arguments,
        "environment": environment,
        "policy_root": policy_root,
        "corpus_roots": corpus_roots,
        "revocation_root": revocation_root,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return _fail(
            tool_name,
            error=(
                "missing required field(s): "
                + ", ".join(missing)
                + "; fail closed"
            ),
            error_type="validation",
        )

    try:
        from ipfs_datasets_py.logic.admissibility.api import (
            IntentAuthorizationAPI,
        )

        api = IntentAuthorizationAPI()
        result = api.evaluate(
            source=source,
            actor=actor,
            audience=audience,
            tool=tool,
            arguments=arguments,
            environment=environment,
            policy_root=policy_root,
            corpus_roots=corpus_roots,
            revocation_root=revocation_root,
            legal_corpus_ref=legal_corpus_ref,
            security_corpus_ref=security_corpus_ref,
            intent_corpus_ref=intent_corpus_ref,
            profile=profile,
            invocation=invocation,
            budget=budget,
            deps=deps,
            # Force-safe: handlers never request capability derivation.
            derive_capability_on_allow=False,
            execute_target=False,
            consume_capability=False,
            issue_capability=False,
        )
        return _project_api_result(tool_name, result)
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.exception("%s failed closed", tool_name)
        return _fail(
            tool_name,
            status="error",
            error=f"{tool_name} failed closed: {exc}",
            error_type=type(exc).__name__,
        )


async def verify_authorization_receipt(
    receipt: Any = None,
    *,
    expected_policy_root: str = "",
    expected_corpus_roots: Sequence[str] | None = None,
    expected_revocation_root: str | None = None,
    expected_audience: str = "",
    expected_actor: str = "",
    now: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Verify a receipt without consuming a dispatch capability."""

    tool_name = "verify_authorization_receipt"
    forbidden = _reject_forbidden_kwargs(kwargs)
    if forbidden:
        return _fail(tool_name, error=forbidden, error_type="forbidden_parameter")

    if receipt is None:
        return _fail(
            tool_name,
            error="receipt is required; fail closed",
            error_type="validation",
        )

    # Explicitly refuse any attempt to pass a capability for consumption.
    if kwargs.get("capability") is not None or kwargs.get("consume") is True:
        return _fail(
            tool_name,
            error=(
                "verify_authorization_receipt cannot consume or accept a "
                "dispatch capability; fail closed"
            ),
            error_type="capability_forbidden",
        )

    try:
        from ipfs_datasets_py.logic.admissibility.api import (
            IntentAuthorizationAPI,
        )

        api = IntentAuthorizationAPI()
        result = api.verify_receipt(
            receipt,
            expected_policy_root=expected_policy_root,
            expected_corpus_roots=expected_corpus_roots,
            expected_revocation_root=expected_revocation_root,
            expected_audience=expected_audience,
            expected_actor=expected_actor,
            now=now,
        )
        return _project_api_result(tool_name, result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s failed closed", tool_name)
        return _fail(
            tool_name,
            status="error",
            error=f"{tool_name} failed closed: {exc}",
            error_type=type(exc).__name__,
        )


async def authorization_api_capabilities(**kwargs: Any) -> dict[str, Any]:
    """Report MCP authorization surface without evaluating or executing."""

    tool_name = "authorization_api_capabilities"
    if kwargs:
        # Unknown kwargs are ignored for discovery, but forbidden execution
        # verbs still fail closed.
        forbidden = _reject_forbidden_kwargs(kwargs)
        if forbidden:
            return _fail(
                tool_name, error=forbidden, error_type="forbidden_parameter"
            )

    try:
        from ipfs_datasets_py.logic.admissibility.api import api_capabilities

        caps = api_capabilities()
        return _ok(
            tool_name,
            tools=list(TOOL_NAMES),
            forbidden_tools=sorted(FORBIDDEN_TOOL_NAMES),
            schemas=list_tools(),
            api=caps,
            issues_capability=False,
            consumes_capability=False,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            tool_name,
            status="error",
            error=f"{tool_name} failed closed: {exc}",
            error_type=type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Discovery helpers (not registered as side-effecting tools)
# ---------------------------------------------------------------------------


def list_tools() -> list[dict[str, Any]]:
    """Return documented tool schemas for MCP / operator discovery."""

    return [dict(TOOL_SCHEMAS[name]) for name in TOOL_NAMES]


def get_tool_schema(name: str) -> dict[str, Any] | None:
    """Return one tool schema by name, or ``None`` if unknown."""

    if not isinstance(name, str):
        return None
    if name in FORBIDDEN_TOOL_NAMES:
        return None
    return dict(TOOL_SCHEMAS[name]) if name in TOOL_SCHEMAS else None


def handler_issues_capability() -> bool:
    """Capability issue is never offered by this module."""

    return False


def handler_consumes_capability() -> bool:
    """Capability consumption is never offered by this module."""

    return False


def handler_executes_targets() -> bool:
    """Target execution is never offered by this module."""

    return False


__all__ = [
    "FORBIDDEN_TOOL_NAMES",
    "MCP_INTENT_AUTHORIZATION_INTERFACE",
    "MCP_INTENT_AUTHORIZATION_SCHEMA_VERSION",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "authorization_api_capabilities",
    "evaluate_intent_authorization",
    "get_tool_schema",
    "handler_consumes_capability",
    "handler_executes_targets",
    "handler_issues_capability",
    "list_tools",
    "verify_authorization_receipt",
]
