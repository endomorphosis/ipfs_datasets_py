"""MCP tools for hardened Intent authorization evaluation (LIG-038).

Interface: ``MCPIntentAuthorization@1``

Exposed tools
-------------
* ``authorize_invocation`` — evaluate an exact invocation via
  ``IntentAuthorizationAPI@1`` and return a redacted allow/reject/abstain
  compatibility payload with typed decision/receipt refs.
* ``verify_authorization_receipt`` — independently verify a decision receipt
  without consuming any capability.
* ``list_authorization_api_tools`` — discovery / schema listing (no evaluation).

Fail-closed invariants
----------------------
* Handlers **never execute** skill_md, prompt text, MCP tool bodies, shell,
  eval, or any invocation target.
* Handlers **cannot issue** a dispatch capability and **cannot consume** one
  (no derive / consume surfaces are exposed).
* Malformed input, missing roots/bindings, unknown fields, and backend
  unavailability return structured non-allow payloads — never a silent allow.
* Response views are **redacted**: no prompts, raw arguments, secrets,
  witnesses, or private formulas.
* This module is additive to ``logic_admissibility_tools``; it does not rewrite
  that base module or register shared exports.
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
    "authorize_invocation",
    "verify_authorization_receipt",
    "list_authorization_api_tools",
)

# Explicit ban: these capability-lifecycle operations must never be exposed.
FORBIDDEN_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "derive_capability",
        "issue_capability",
        "consume_capability",
        "consume_dispatch_capability",
        "dispatch_invocation",
        "execute_tool",
        "execute_invocation",
        "run_target",
    }
)

TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "authorize_invocation": {
        "name": "authorize_invocation",
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "description": (
            "Evaluate an exact invocation against pinned policy/corpus/"
            "revocation roots. Returns allow/reject/abstain compatibility "
            "plus typed decision/receipt refs. Never executes the target and "
            "never issues or consumes a dispatch capability."
        ),
        "parameters": {
            "type": "object",
            "required": [
                "invocation",
                "policy_ref",
                "revocation_root",
            ],
            "properties": {
                "invocation": {
                    "type": "object",
                    "description": (
                        "Canonical InvocationIntentEnvelope map with explicit "
                        "source, actor, audience, tool, arguments (commitment), "
                        "and environment bindings."
                    ),
                },
                "policy_ref": {
                    "type": "string",
                    "description": "Exact policy root identity.",
                },
                "legal_corpus_ref": {"type": "string"},
                "security_corpus_ref": {"type": "string"},
                "intent_corpus_ref": {"type": "string"},
                "corpus_roots": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact corpus root identities when not split.",
                },
                "revocation_root": {
                    "type": "string",
                    "description": "Exact revocation root identity.",
                },
                "environment": {
                    "type": "object",
                    "description": (
                        "Optional live environment snapshot "
                        "(environment_id / digest only; no secrets)."
                    ),
                },
                "profile": {
                    "type": "string",
                    "default": "legal-strict",
                    "description": "Admissibility profile id.",
                },
                "budget": {
                    "type": "object",
                    "description": "Optional authorization budget map.",
                },
            },
        },
        "returns": {
            "success": "bool",
            "status": "allow | reject | abstain | error",
            "wire_status": "allow | reject | abstain",
            "decision_ref": "typed decision ref map when available",
            "receipt_ref": "typed receipt ref map when available",
            "view": "redacted authorization view",
            "executed": "always false",
            "capability_issued": "always false",
            "capability_consumed": "always false",
        },
    },
    "verify_authorization_receipt": {
        "name": "verify_authorization_receipt",
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "description": (
            "Independently verify a DecisionReceipt@1 without consuming a "
            "dispatch capability. Fail closed on mutation, expiry, or root drift."
        ),
        "parameters": {
            "type": "object",
            "required": ["receipt"],
            "properties": {
                "receipt": {
                    "type": "object",
                    "description": "DecisionReceipt@1 map.",
                },
                "now": {
                    "type": "string",
                    "description": "ISO-8601 evaluation time for expiry checks.",
                },
                "expected_audience": {"type": "string"},
                "expected_actor": {"type": "string"},
                "expected_nonce": {"type": "string"},
                "expected_request_digest": {"type": "string"},
                "expected_roots": {
                    "type": "object",
                    "description": "BoundRoots map for root revalidation.",
                },
                "require_not_expired": {
                    "type": "boolean",
                    "default": True,
                },
            },
        },
        "returns": {
            "success": "bool",
            "status": "allow | reject | abstain | error",
            "wire_status": "allow | reject | abstain",
            "receipt_ref": "typed receipt ref when verified",
            "executed": "always false",
            "capability_issued": "always false",
            "capability_consumed": "always false",
        },
    },
    "list_authorization_api_tools": {
        "name": "list_authorization_api_tools",
        "interface": MCP_INTENT_AUTHORIZATION_INTERFACE,
        "description": (
            "List MCPIntentAuthorization@1 tool schemas without evaluation "
            "or execution."
        ),
        "parameters": {"type": "object", "properties": {}},
        "returns": {
            "success": "bool",
            "tools": "list of tool schema maps",
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
    # Hard enforce non-execution / non-capability flags after extras.
    payload["executed"] = False
    payload["capability_issued"] = False
    payload["capability_consumed"] = False
    return payload


def _ok(tool: str, **extra: Any) -> dict[str, Any]:
    return _base_response(tool, success=True, **extra)


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
        wire_status="reject" if status == "error" else status,
        error=error,
        error_type=error_type,
        **extra,
    )


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _optional_str(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string when provided")
    return value


def _optional_str_seq(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise TypeError(f"{label} must be a sequence of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{label}[{index}] must be a string")
        items.append(item)
    return tuple(items)


def _assert_no_forbidden_tools() -> None:
    overlap = set(TOOL_NAMES) & FORBIDDEN_TOOL_NAMES
    if overlap:
        raise RuntimeError(
            f"forbidden capability lifecycle tools exposed: {sorted(overlap)}"
        )


_assert_no_forbidden_tools()


# ---------------------------------------------------------------------------
# Lazy API surface
# ---------------------------------------------------------------------------


def _load_api():
    """Import the hardened Python API (lazy to keep MCP load light)."""

    try:
        from ipfs_datasets_py.logic.admissibility import api as auth_api
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            f"authorization API backend unavailable: {exc}"
        ) from exc
    return auth_api


def _redact_public_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    auth_api = _load_api()
    redacted = auth_api.redact_mapping(dict(payload))
    if not isinstance(redacted, dict):
        return {"status": "reject", "error": "redaction failed", "executed": False}
    redacted["executed"] = False
    redacted["capability_issued"] = False
    redacted["capability_consumed"] = False
    return redacted


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def list_authorization_api_tools() -> dict[str, Any]:
    """Return tool schemas without evaluation or execution."""

    tools = [TOOL_SCHEMAS[name] for name in TOOL_NAMES]
    return _ok(
        "list_authorization_api_tools",
        status="ok",
        tools=tools,
        tool_names=list(TOOL_NAMES),
        forbidden_tool_names=sorted(FORBIDDEN_TOOL_NAMES),
    )


async def authorize_invocation(
    invocation: Mapping[str, Any] | None = None,
    *,
    policy_ref: str = "",
    legal_corpus_ref: str = "",
    security_corpus_ref: str = "",
    intent_corpus_ref: str = "",
    corpus_roots: Sequence[str] | None = None,
    revocation_root: str = "",
    environment: Mapping[str, Any] | None = None,
    profile: str = "legal-strict",
    budget: Mapping[str, Any] | None = None,
    # Intentionally no derive_capability / consume / execute parameters.
    **unknown: Any,
) -> dict[str, Any]:
    """Evaluate an exact invocation; never execute and never issue capabilities."""

    tool = "authorize_invocation"
    if unknown:
        return _fail(
            tool,
            status="reject",
            error=f"unknown field(s): {', '.join(sorted(unknown))}",
            error_type="malformed_input",
        )

    if invocation is None:
        return _fail(
            tool,
            status="reject",
            error="invocation is required",
            error_type="malformed_input",
        )

    try:
        invocation_map = _require_mapping(invocation, "invocation")
        policy = _optional_str(policy_ref, "policy_ref")
        rev = _optional_str(revocation_root, "revocation_root")
        if not policy.strip():
            return _fail(
                tool,
                status="reject",
                error="policy_ref is required (exact policy root)",
                error_type="missing_roots",
            )
        if not rev.strip():
            return _fail(
                tool,
                status="reject",
                error="revocation_root is required (exact revocation root)",
                error_type="missing_roots",
            )
        legal = _optional_str(legal_corpus_ref, "legal_corpus_ref")
        security = _optional_str(security_corpus_ref, "security_corpus_ref")
        intent = _optional_str(intent_corpus_ref, "intent_corpus_ref")
        roots = _optional_str_seq(corpus_roots, "corpus_roots")
        if not any((legal, security, intent, roots)):
            return _fail(
                tool,
                status="reject",
                error=(
                    "exact corpus root is required "
                    "(legal/security/intent corpus_ref or corpus_roots)"
                ),
                error_type="missing_roots",
            )
        env = None
        if environment is not None:
            env = dict(_require_mapping(environment, "environment"))
        budget_map = None
        if budget is not None:
            budget_map = dict(_require_mapping(budget, "budget"))
        profile_id = _optional_str(profile, "profile") or "legal-strict"
    except (TypeError, ValueError) as exc:
        return _fail(
            tool,
            status="reject",
            error=str(exc),
            error_type="malformed_input",
        )

    try:
        auth_api = _load_api()
    except RuntimeError as exc:
        return _fail(
            tool,
            status="abstain",
            error=str(exc),
            error_type="backend_unavailable",
        )

    try:
        api = auth_api.IntentAuthorizationAPI()
        result = api.evaluate(
            dict(invocation_map),
            policy_ref=policy,
            legal_corpus_ref=legal,
            security_corpus_ref=security,
            intent_corpus_ref=intent,
            corpus_roots=roots,
            revocation_root=rev,
            environment=env,
            profile=profile_id,
            budget=budget_map,
            # Offline unit path: no network/backends; service still fail-closes
            # when deps are absent.  Callers inject deps only via Python API.
        )
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.debug("authorize_invocation failed closed: %s", exc, exc_info=True)
        return _fail(
            tool,
            status="abstain",
            error=f"backend unavailable: {type(exc).__name__}",
            error_type="backend_unavailable",
        )

    payload = result.to_dict()
    wire = payload.get("wire_status", "abstain")
    if wire not in {"allow", "reject", "abstain"}:
        wire = "abstain"
    success = wire == "allow"
    status = wire if wire != "allow" or success else "reject"
    # Preserve allow only when truly allow; never upgrade.
    response = _base_response(
        tool,
        success=success,
        status=status if status != "allow" or success else "reject",
        wire_status=wire,
        internal_status=payload.get("internal_status", ""),
        reasons=payload.get("reasons", []),
        reason_codes=payload.get("reason_codes", []),
        decision_ref=payload.get("decision_ref"),
        receipt_ref=payload.get("receipt_ref"),
        view=payload.get("view"),
        profile_id=payload.get("profile_id", profile_id),
    )
    return _redact_public_payload(response)


async def verify_authorization_receipt(
    receipt: Mapping[str, Any] | None = None,
    *,
    now: str | None = None,
    expected_audience: str | None = None,
    expected_actor: str | None = None,
    expected_nonce: str | None = None,
    expected_request_digest: str | None = None,
    expected_roots: Mapping[str, Any] | None = None,
    require_not_expired: bool = True,
    **unknown: Any,
) -> dict[str, Any]:
    """Verify a receipt; never consume a capability or execute a target."""

    tool = "verify_authorization_receipt"
    if unknown:
        return _fail(
            tool,
            status="reject",
            error=f"unknown field(s): {', '.join(sorted(unknown))}",
            error_type="malformed_input",
        )
    if receipt is None:
        return _fail(
            tool,
            status="reject",
            error="receipt is required",
            error_type="malformed_input",
        )

    try:
        receipt_map = _require_mapping(receipt, "receipt")
        now_text = _optional_str(now, "now") or None
        audience = _optional_str(expected_audience, "expected_audience") or None
        actor = _optional_str(expected_actor, "expected_actor") or None
        nonce = _optional_str(expected_nonce, "expected_nonce") or None
        request_digest = (
            _optional_str(expected_request_digest, "expected_request_digest")
            or None
        )
        roots = None
        if expected_roots is not None:
            roots = dict(_require_mapping(expected_roots, "expected_roots"))
        if not isinstance(require_not_expired, bool):
            raise TypeError("require_not_expired must be a bool")
    except (TypeError, ValueError) as exc:
        return _fail(
            tool,
            status="reject",
            error=str(exc),
            error_type="malformed_input",
        )

    try:
        auth_api = _load_api()
    except RuntimeError as exc:
        return _fail(
            tool,
            status="abstain",
            error=str(exc),
            error_type="backend_unavailable",
        )

    try:
        api = auth_api.IntentAuthorizationAPI()
        result = api.verify_receipt(
            dict(receipt_map),
            now=now_text,
            expected_roots=roots,
            expected_audience=audience,
            expected_actor=actor,
            expected_nonce=nonce,
            expected_request_digest=request_digest,
            require_not_expired=require_not_expired,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "verify_authorization_receipt failed closed: %s", exc, exc_info=True
        )
        return _fail(
            tool,
            status="abstain",
            error=f"backend unavailable: {type(exc).__name__}",
            error_type="backend_unavailable",
        )

    payload = result.to_dict()
    wire = payload.get("wire_status", "abstain")
    if wire not in {"allow", "reject", "abstain"}:
        wire = "abstain"
    # Verification success means integrity ok; status still reflects decision.
    verified = result.receipt_ref is not None and not any(
        code == "auth.api.receipt_verify_failed"
        for code in (payload.get("reason_codes") or [])
    )
    # Fail-closed verify: missing receipt_ref means verification did not pass.
    if result.receipt_ref is None:
        return _fail(
            tool,
            status="reject",
            error="; ".join(payload.get("reasons") or ["receipt verification failed"]),
            error_type="receipt_verify_failed",
            reasons=payload.get("reasons", []),
            reason_codes=payload.get("reason_codes", []),
        )

    success = verified and wire in {"allow", "reject", "abstain"}
    response = _base_response(
        tool,
        success=True if success else False,
        status=wire,
        wire_status=wire,
        internal_status=payload.get("internal_status", ""),
        reasons=payload.get("reasons", []),
        reason_codes=payload.get("reason_codes", []),
        decision_ref=payload.get("decision_ref"),
        receipt_ref=payload.get("receipt_ref"),
        view=payload.get("view"),
        profile_id=payload.get("profile_id", ""),
    )
    return _redact_public_payload(response)


async def capabilities() -> dict[str, Any]:
    """Alias for discovery used by some MCP registries."""

    return await list_authorization_api_tools()


# Explicit export surface — no capability lifecycle handlers.
__all__ = [
    "FORBIDDEN_TOOL_NAMES",
    "MCP_INTENT_AUTHORIZATION_INTERFACE",
    "MCP_INTENT_AUTHORIZATION_SCHEMA_VERSION",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "authorize_invocation",
    "capabilities",
    "list_authorization_api_tools",
    "verify_authorization_receipt",
]
