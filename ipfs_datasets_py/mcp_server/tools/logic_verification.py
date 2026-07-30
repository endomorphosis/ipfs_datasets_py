"""Bounded MCP surface for the stable software-verification API (LFV-G071).

Interface: ``LogicVerificationMCP@1``

Thin async wrappers over
:mod:`ipfs_datasets_py.logic.verification_api` (``LogicVerificationAPI@1``).
Schemas and operation names match the Python facade; responses always carry
status, authority, assumptions, bounds, translations, witnesses, and cache
provenance.  Inputs and outputs are size-bounded, diagnostics are secret-safe,
and unavailable or unsupported features are reported explicitly.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

LOGIC_VERIFICATION_MCP_INTERFACE: Final = "LogicVerificationMCP@1"
LOGIC_VERIFICATION_MCP_SCHEMA: Final = "logic-verification-mcp/v1"
LOGIC_VERIFICATION_CLI_INTERFACE: Final = "LogicVerificationCLI@1"

# Match the stable Python operation set (plus discovery helpers).
TOOL_NAMES: Final[tuple[str, ...]] = (
    "verification_list_features",
    "verification_list_logic_families",
    "verification_list_providers",
    "verification_provider_capabilities",
    "verification_compile",
    "verification_check",
    "verification_monitor",
    "verification_portfolio",
    "verification_explain_counterexample",
    "verification_verify_receipt",
    "verification_advise",
    "verification_attest_receipt",
    "verification_probe_provider",
    "verification_install_provider",
    "verification_capabilities",
)

# Map MCP tool name → Python facade operation (for schema parity).
TOOL_TO_OPERATION: Final[dict[str, str]] = {
    "verification_list_features": "list_features",
    "verification_list_logic_families": "list_logic_families",
    "verification_list_providers": "list_providers",
    "verification_provider_capabilities": "provider_capabilities",
    "verification_compile": "compile_verification_artifact",
    "verification_check": "check",
    "verification_monitor": "monitor",
    "verification_portfolio": "run_portfolio",
    "verification_explain_counterexample": "explain_counterexample",
    "verification_verify_receipt": "verify_receipt",
    "verification_advise": "advise",
    "verification_attest_receipt": "attest_receipt",
    "verification_probe_provider": "probe_provider",
    "verification_install_provider": "install_provider",
    "verification_capabilities": "list_features",
}

# Bounds (acceptance: inputs/outputs are bounded).
MAX_JSON_BYTES: Final = 256_000
MAX_STRING_CHARS: Final = 64_000
MAX_DIAGNOSTIC_CHARS: Final = 2_000
MAX_RESULT_DEPTH: Final = 12
MAX_COLLECTION_ITEMS: Final = 500

# Documented schemas for MCP / CLI discovery (parameters align with Python).
TOOL_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "verification_list_features": {
        "name": "verification_list_features",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "list_features",
        "description": "List stable verification operations and feature descriptors.",
        "parameters": {"type": "object", "properties": {}},
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_list_logic_families": {
        "name": "verification_list_logic_families",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "list_logic_families",
        "description": "Return the declarative logic-family catalog.",
        "parameters": {"type": "object", "properties": {}},
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_list_providers": {
        "name": "verification_list_providers",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "list_providers",
        "description": "Return declared providers without environment probes.",
        "parameters": {"type": "object", "properties": {}},
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_provider_capabilities": {
        "name": "verification_provider_capabilities",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "provider_capabilities",
        "description": "Return capability declarations for one or all providers.",
        "parameters": {
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "string",
                    "description": "Optional provider id; omit for the full catalog.",
                }
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_compile": {
        "name": "verification_compile",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "compile_verification_artifact",
        "description": "Compile a verification obligation to a backend artifact.",
        "parameters": {
            "type": "object",
            "required": ["artifact"],
            "properties": {
                "artifact": {"type": "object", "description": "Obligation or IR fragment."},
                "target": {"type": "string", "default": "smtlib2"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_check": {
        "name": "verification_check",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "check",
        "description": "Run a typed proof/satisfiability check.",
        "parameters": {
            "type": "object",
            "required": ["request"],
            "properties": {
                "request": {"type": "object", "description": "BackendRequest-shaped mapping."},
                "backend_id": {"type": "string"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_monitor": {
        "name": "verification_monitor",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "monitor",
        "description": "Evaluate a runtime MTL formula over observations.",
        "parameters": {
            "type": "object",
            "required": ["formula", "observations"],
            "properties": {
                "formula": {
                    "description": "Formula mapping or portable formula payload.",
                },
                "observations": {
                    "description": "Trace mapping or sequence of observations.",
                },
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_portfolio": {
        "name": "verification_portfolio",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "run_portfolio",
        "description": "Plan a property-specific prover portfolio (pure planning).",
        "parameters": {
            "type": "object",
            "required": ["obligation"],
            "properties": {
                "obligation": {"type": "object"},
                "capabilities": {"type": ["array", "object"]},
                "resource_policy": {"type": "object"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_explain_counterexample": {
        "name": "verification_explain_counterexample",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "explain_counterexample",
        "description": "Normalize and explain a counterexample witness.",
        "parameters": {
            "type": "object",
            "required": ["witness"],
            "properties": {
                "witness": {"type": "object"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_verify_receipt": {
        "name": "verification_verify_receipt",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "verify_receipt",
        "description": "Validate a translation or proof receipt without upgrading authority.",
        "parameters": {
            "type": "object",
            "required": ["receipt"],
            "properties": {
                "receipt": {"type": "object"},
                "expectation": {"type": "object"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_advise": {
        "name": "verification_advise",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "advise",
        "description": "Produce untrusted formalization proposals (never proof authority).",
        "parameters": {
            "type": "object",
            "required": ["request"],
            "properties": {
                "request": {"type": "object"},
                "provider": {"type": "string", "default": "static"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_attest_receipt": {
        "name": "verification_attest_receipt",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "attest_receipt",
        "description": "Prepare or record a ZKP attestation for a trusted proof receipt.",
        "parameters": {
            "type": "object",
            "required": ["receipt"],
            "properties": {
                "receipt": {"type": "object"},
                "backend_mode": {"type": "string", "default": "disabled"},
                "backend_policy": {"type": "object"},
                "witness": {"type": "object"},
                "issued_at": {"type": "string"},
                "expires_at": {"type": "string"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_probe_provider": {
        "name": "verification_probe_provider",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "probe_provider",
        "description": "Opt-in probe of a provider's local availability.",
        "parameters": {
            "type": "object",
            "required": ["provider_id"],
            "properties": {
                "provider_id": {"type": "string"},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_install_provider": {
        "name": "verification_install_provider",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "install_provider",
        "description": "Opt-in install of a provider (requires allow_install=true).",
        "parameters": {
            "type": "object",
            "required": ["provider_id"],
            "properties": {
                "provider_id": {"type": "string"},
                "allow_install": {"type": "boolean", "default": False},
                "request_id": {"type": "string"},
            },
        },
        "returns": {"envelope": "logic-verification-response/v1"},
    },
    "verification_capabilities": {
        "name": "verification_capabilities",
        "interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "python_operation": "list_features",
        "description": "MCP capability summary for the verification tool surface.",
        "parameters": {"type": "object", "properties": {}},
        "returns": {
            "success": "bool",
            "tools": "list of tool names",
            "operations": "Python STABLE_OPERATIONS",
            "schemas": "tool schemas",
        },
    },
}


# ---------------------------------------------------------------------------
# Secret-safe / bounded helpers
# ---------------------------------------------------------------------------


def _redact_text(value: str) -> str:
    """Redact credential-like substrings and cap length."""

    text = value
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)bearer\s+[a-z0-9._\-+/=]{8,}", "bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(sk|pk|ghp|gho|xox[baprs])-[a-z0-9\-]{10,}",
        r"\1-[REDACTED]",
        text,
    )
    if len(text) > MAX_DIAGNOSTIC_CHARS:
        text = text[: MAX_DIAGNOSTIC_CHARS - 3] + "..."
    return text


def _bound_value(value: Any, *, depth: int = 0) -> Any:
    """Recursively bound nested structures for machine-readable responses."""

    if depth > MAX_RESULT_DEPTH:
        return {"_truncated": "max_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        redacted = _redact_text(value)
        if len(redacted) > MAX_STRING_CHARS:
            return redacted[: MAX_STRING_CHARS - 3] + "..."
        return redacted
    if isinstance(value, Mapping):
        items = list(value.items())
        if len(items) > MAX_COLLECTION_ITEMS:
            items = items[:MAX_COLLECTION_ITEMS]
        return {
            str(key)[:256]: _bound_value(item, depth=depth + 1) for key, item in items
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        seq = list(value)[:MAX_COLLECTION_ITEMS]
        return [_bound_value(item, depth=depth + 1) for item in seq]
    if isinstance(value, bytes):
        return {"_bytes": len(value), "_truncated": True}
    return _redact_text(str(value))


def _estimate_json_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str).encode("utf-8"))
    except Exception:
        return MAX_JSON_BYTES + 1


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    if _estimate_json_bytes(value) > MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds max JSON size of {MAX_JSON_BYTES} bytes")
    return value


def _optional_str(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string when provided")
    if len(value) > MAX_STRING_CHARS:
        raise ValueError(f"{label} exceeds max length of {MAX_STRING_CHARS}")
    return value


def _parse_jsonish(value: Any, label: str) -> Any:
    """Accept mappings/sequences or JSON strings for CLI/MCP payloads."""

    if value is None:
        return None
    if isinstance(value, (Mapping, list, tuple)):
        if _estimate_json_bytes(value) > MAX_JSON_BYTES:
            raise ValueError(f"{label} exceeds max JSON size of {MAX_JSON_BYTES} bytes")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError(f"{label} exceeds max JSON size of {MAX_JSON_BYTES} bytes")
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{label} is not valid JSON: {error}") from error
    raise TypeError(f"{label} must be a mapping, sequence, or JSON string")


def _get_api():
    from ipfs_datasets_py.logic.verification_api import get_verification_api

    return get_verification_api()


def _envelope_from_response(response: Any, *, tool: str) -> dict[str, Any]:
    """Convert a VerificationResponse into a bounded MCP payload."""

    if hasattr(response, "to_dict"):
        payload = response.to_dict()
    elif isinstance(response, Mapping):
        payload = dict(response)
    else:
        payload = {"result": str(response)}

    bounded = _bound_value(payload)
    if not isinstance(bounded, dict):
        bounded = {"result": bounded}

    status = str(bounded.get("status", "error"))
    success = status in {"succeeded", "declarative", "partial"}
    # Preserve Python envelope keys and add MCP metadata without clobbering.
    out: dict[str, Any] = dict(bounded)
    out.setdefault("success", success)
    out["tool"] = tool
    out["mcp_interface"] = LOGIC_VERIFICATION_MCP_INTERFACE
    out["mcp_schema_version"] = LOGIC_VERIFICATION_MCP_SCHEMA
    out["python_operation"] = TOOL_TO_OPERATION.get(tool, tool)
    return out


def _error_envelope(
    tool: str,
    *,
    error: str,
    status: str = "error",
    error_type: str = "error",
    **extra: Any,
) -> dict[str, Any]:
    """Stable secret-safe error envelope when the facade cannot be reached."""

    return {
        "success": False,
        "status": status,
        "authority": "none",
        "operation": TOOL_TO_OPERATION.get(tool, tool),
        "result": {},
        "assumptions": [],
        "bounds": {},
        "translations": [],
        "witnesses": [],
        "unsupported_features": list(extra.pop("unsupported_features", []) or []),
        "diagnostics": [_redact_text(error)],
        "cache": {"source": "mcp", "hit": False, "cache_key": "", "scope": "none", "freshness": "not_cached"},
        "request_id": str(extra.pop("request_id", "") or ""),
        "property_id": "",
        "provider_id": str(extra.pop("provider_id", "") or ""),
        "interface": "LogicVerificationAPI@1",
        "api_version": "1.0.0",
        "schema_version": "logic-verification-response/v1",
        "tool": tool,
        "mcp_interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "mcp_schema_version": LOGIC_VERIFICATION_MCP_SCHEMA,
        "python_operation": TOOL_TO_OPERATION.get(tool, tool),
        "error": _redact_text(error),
        "error_type": error_type,
        **{key: _bound_value(value) for key, value in extra.items()},
    }


def _run_facade(tool: str, call) -> dict[str, Any]:
    """Invoke a facade callable and normalize the response."""

    try:
        response = call()
        return _envelope_from_response(response, tool=tool)
    except (TypeError, ValueError) as error:
        return _error_envelope(
            tool,
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    except Exception as error:  # pragma: no cover - defensive boundary
        logger.exception("%s failed", tool)
        return _error_envelope(
            tool,
            error=f"{type(error).__name__}: {error}",
            status="error",
            error_type=type(error).__name__,
        )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def list_tools() -> list[dict[str, Any]]:
    """Return documented tool schemas for MCP / CLI discovery."""

    return [dict(TOOL_SCHEMAS[name]) for name in TOOL_NAMES]


def get_tool_schema(name: str) -> dict[str, Any] | None:
    """Return one tool schema by name, or ``None`` if unknown."""

    if not isinstance(name, str):
        return None
    return dict(TOOL_SCHEMAS[name]) if name in TOOL_SCHEMAS else None


# ---------------------------------------------------------------------------
# MCP tool handlers (async for registry / CLI discovery compatibility)
# ---------------------------------------------------------------------------


async def verification_list_features() -> dict[str, Any]:
    """List stable verification operations and feature descriptors."""

    return _run_facade(
        "verification_list_features",
        lambda: _get_api().list_features(),
    )


async def verification_list_logic_families() -> dict[str, Any]:
    """Return the declarative logic-family catalog."""

    return _run_facade(
        "verification_list_logic_families",
        lambda: _get_api().list_logic_families(),
    )


async def verification_list_providers() -> dict[str, Any]:
    """Return declared providers without environment probes."""

    return _run_facade(
        "verification_list_providers",
        lambda: _get_api().list_providers(),
    )


async def verification_provider_capabilities(
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Return capability declarations for one or all providers."""

    pid = _optional_str(provider_id, "provider_id") or None
    return _run_facade(
        "verification_provider_capabilities",
        lambda: _get_api().provider_capabilities(pid),
    )


async def verification_compile(
    artifact: Mapping[str, Any] | str,
    target: str = "smtlib2",
    request_id: str = "",
) -> dict[str, Any]:
    """Compile a verification obligation to a backend artifact."""

    try:
        parsed = _parse_jsonish(artifact, "artifact")
        if not isinstance(parsed, Mapping):
            raise TypeError("artifact must be a mapping")
        tgt = _optional_str(target, "target") or "smtlib2"
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_compile",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_compile",
        lambda: _get_api().compile_verification_artifact(
            parsed, target=tgt, request_id=rid
        ),
    )


async def verification_check(
    request: Mapping[str, Any] | str,
    backend_id: str | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Run a typed proof/satisfiability check."""

    try:
        parsed = _parse_jsonish(request, "request")
        if not isinstance(parsed, Mapping):
            raise TypeError("request must be a mapping")
        bid = _optional_str(backend_id, "backend_id") or None
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_check",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_check",
        lambda: _get_api().check(parsed, backend_id=bid, request_id=rid),
    )


async def verification_monitor(
    formula: Any,
    observations: Any,
    request_id: str = "",
) -> dict[str, Any]:
    """Evaluate a runtime MTL formula over observations."""

    try:
        formula_value = (
            _parse_jsonish(formula, "formula") if isinstance(formula, str) else formula
        )
        obs_value = (
            _parse_jsonish(observations, "observations")
            if isinstance(observations, str)
            else observations
        )
        formula_obj = _coerce_monitor_formula(formula_value)
        observations_obj = _coerce_monitor_observations(obs_value)
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_monitor",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_monitor",
        lambda: _get_api().monitor(formula_obj, observations_obj, request_id=rid),
    )


def _coerce_monitor_formula(value: Any) -> Any:
    if value is None or not isinstance(value, Mapping):
        return value
    try:
        from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
            Formula,
        )

        if hasattr(Formula, "from_dict"):
            return Formula.from_dict(dict(value))
        return Formula(
            operator=str(value.get("operator") or "atom"),
            proposition=str(value.get("proposition") or value.get("atom") or "p"),
        )
    except Exception:
        return value


def _coerce_monitor_observations(value: Any) -> Any:
    if value is None:
        return value
    if not isinstance(value, Mapping):
        return value
    try:
        from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
            Clock,
            Event,
            TimeValue,
            Trace,
            TraceKind,
        )

        if hasattr(Trace, "from_dict"):
            return Trace.from_dict(value)
        clock_payload = value.get("clock") or {"clock_id": "c1"}
        clock = (
            Clock.from_dict(clock_payload)
            if hasattr(Clock, "from_dict") and isinstance(clock_payload, Mapping)
            else Clock(clock_id=str(clock_payload.get("clock_id", "c1")))
            if isinstance(clock_payload, Mapping)
            else Clock(clock_id="c1")
        )
        events = []
        for index, item in enumerate(value.get("events") or ()):
            if not isinstance(item, Mapping):
                continue
            if hasattr(Event, "from_dict"):
                events.append(Event.from_dict(item))
                continue
            time_raw = item.get("time", 0)
            if isinstance(time_raw, Mapping):
                time_val = TimeValue(int(time_raw.get("value", time_raw.get("t", 0))))
            else:
                time_val = TimeValue(int(time_raw))
            events.append(
                Event(
                    event_id=str(item.get("event_id") or f"e{index}"),
                    event_type=str(item.get("event_type") or "obs"),
                    time=time_val,
                    true_propositions=tuple(item.get("true_propositions") or ()),
                )
            )
        kind = value.get("kind", TraceKind.FINITE)
        if not isinstance(kind, TraceKind):
            kind = TraceKind(str(kind))
        return Trace(clock=clock, events=tuple(events), kind=kind)
    except Exception:
        return value


async def verification_portfolio(
    obligation: Mapping[str, Any] | str,
    capabilities: Any = None,
    resource_policy: Any = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Plan a property-specific prover portfolio (pure planning)."""

    try:
        parsed = _parse_jsonish(obligation, "obligation")
        if not isinstance(parsed, Mapping):
            raise TypeError("obligation must be a mapping")
        caps = (
            _parse_jsonish(capabilities, "capabilities")
            if isinstance(capabilities, str)
            else capabilities
        )
        policy = (
            _parse_jsonish(resource_policy, "resource_policy")
            if isinstance(resource_policy, str)
            else resource_policy
        )
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_portfolio",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_portfolio",
        lambda: _get_api().run_portfolio(
            parsed,
            capabilities=caps,
            resource_policy=policy,
            request_id=rid,
        ),
    )


async def verification_explain_counterexample(
    witness: Mapping[str, Any] | str,
    request_id: str = "",
) -> dict[str, Any]:
    """Normalize and explain a counterexample witness."""

    try:
        parsed = _parse_jsonish(witness, "witness")
        if not isinstance(parsed, Mapping):
            raise TypeError("witness must be a mapping")
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_explain_counterexample",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_explain_counterexample",
        lambda: _get_api().explain_counterexample(parsed, request_id=rid),
    )


async def verification_verify_receipt(
    receipt: Mapping[str, Any] | str | None,
    expectation: Mapping[str, Any] | str | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """Validate a translation or proof receipt without upgrading authority."""

    try:
        parsed = _parse_jsonish(receipt, "receipt") if receipt is not None else None
        exp = (
            _parse_jsonish(expectation, "expectation")
            if expectation is not None
            else None
        )
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_verify_receipt",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_verify_receipt",
        lambda: _get_api().verify_receipt(parsed, exp, request_id=rid),
    )


async def verification_advise(
    request: Mapping[str, Any] | str,
    provider: str = "static",
    request_id: str = "",
) -> dict[str, Any]:
    """Produce untrusted formalization proposals (never proof authority)."""

    try:
        parsed = _parse_jsonish(request, "request")
        if not isinstance(parsed, Mapping):
            raise TypeError("request must be a mapping")
        prov = _optional_str(provider, "provider") or "static"
        rid = _optional_str(request_id, "request_id")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_advise",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_advise",
        lambda: _get_api().advise(parsed, provider=prov, request_id=rid),
    )


async def verification_attest_receipt(
    receipt: Mapping[str, Any] | str,
    backend_mode: str = "disabled",
    backend_policy: Any = None,
    witness: Any = None,
    issued_at: str = "",
    expires_at: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """Prepare or record a ZKP attestation for a trusted proof receipt."""

    try:
        parsed = _parse_jsonish(receipt, "receipt")
        if not isinstance(parsed, Mapping):
            raise TypeError("receipt must be a mapping")
        policy = (
            _parse_jsonish(backend_policy, "backend_policy")
            if isinstance(backend_policy, str)
            else backend_policy
        )
        wit = _parse_jsonish(witness, "witness") if isinstance(witness, str) else witness
        mode = _optional_str(backend_mode, "backend_mode") or "disabled"
        rid = _optional_str(request_id, "request_id")
        issued = _optional_str(issued_at, "issued_at")
        expires = _optional_str(expires_at, "expires_at")
    except (TypeError, ValueError) as error:
        return _error_envelope(
            "verification_attest_receipt",
            error=f"{type(error).__name__}: {error}",
            status="invalid",
            error_type=type(error).__name__,
        )
    return _run_facade(
        "verification_attest_receipt",
        lambda: _get_api().attest_receipt(
            parsed,
            backend_policy=policy,
            witness=wit,
            issued_at=issued,
            expires_at=expires,
            backend_mode=mode,
            request_id=rid,
        ),
    )


async def verification_probe_provider(
    provider_id: str,
    request_id: str = "",
) -> dict[str, Any]:
    """Opt-in probe of a provider's local availability."""

    pid = _optional_str(provider_id, "provider_id")
    if not pid:
        return _error_envelope(
            "verification_probe_provider",
            error="provider_id is required",
            status="invalid",
            error_type="ValueError",
        )
    rid = _optional_str(request_id, "request_id")
    return _run_facade(
        "verification_probe_provider",
        lambda: _get_api().probe_provider(pid, request_id=rid),
    )


async def verification_install_provider(
    provider_id: str,
    allow_install: bool = False,
    request_id: str = "",
) -> dict[str, Any]:
    """Opt-in install of a provider (requires allow_install=true)."""

    pid = _optional_str(provider_id, "provider_id")
    if not pid:
        return _error_envelope(
            "verification_install_provider",
            error="provider_id is required",
            status="invalid",
            error_type="ValueError",
        )
    rid = _optional_str(request_id, "request_id")
    return _run_facade(
        "verification_install_provider",
        lambda: _get_api().install_provider(
            pid, allow_install=bool(allow_install), request_id=rid
        ),
    )


async def verification_capabilities() -> dict[str, Any]:
    """Report MCP verification tool surface without probing tools."""

    from ipfs_datasets_py.logic.verification_api import (
        LOGIC_VERIFICATION_API_INTERFACE,
        STABLE_OPERATIONS,
    )

    return {
        "success": True,
        "status": "declarative",
        "authority": "declarative",
        "tool": "verification_capabilities",
        "mcp_interface": LOGIC_VERIFICATION_MCP_INTERFACE,
        "mcp_schema_version": LOGIC_VERIFICATION_MCP_SCHEMA,
        "cli_interface": LOGIC_VERIFICATION_CLI_INTERFACE,
        "python_interface": LOGIC_VERIFICATION_API_INTERFACE,
        "tools": list(TOOL_NAMES),
        "operations": list(STABLE_OPERATIONS),
        "tool_to_operation": dict(TOOL_TO_OPERATION),
        "schemas": list_tools(),
        "bounds": {
            "max_json_bytes": MAX_JSON_BYTES,
            "max_string_chars": MAX_STRING_CHARS,
            "max_diagnostic_chars": MAX_DIAGNOSTIC_CHARS,
            "max_result_depth": MAX_RESULT_DEPTH,
            "max_collection_items": MAX_COLLECTION_ITEMS,
        },
    }


__all__ = [
    "LOGIC_VERIFICATION_CLI_INTERFACE",
    "LOGIC_VERIFICATION_MCP_INTERFACE",
    "LOGIC_VERIFICATION_MCP_SCHEMA",
    "MAX_JSON_BYTES",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "TOOL_TO_OPERATION",
    "get_tool_schema",
    "list_tools",
    "verification_advise",
    "verification_attest_receipt",
    "verification_capabilities",
    "verification_check",
    "verification_compile",
    "verification_explain_counterexample",
    "verification_install_provider",
    "verification_list_features",
    "verification_list_logic_families",
    "verification_list_providers",
    "verification_monitor",
    "verification_portfolio",
    "verification_probe_provider",
    "verification_provider_capabilities",
    "verification_verify_receipt",
]
