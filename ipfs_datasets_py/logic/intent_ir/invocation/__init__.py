"""Canonical invocation intent envelopes and source adapters (LIG-G090).

Defines :class:`InvocationIntentEnvelope` plus SkillCenter, prompt, and MCP
adapters that project source records into envelopes **without executing** skill,
prompt, or tool bodies.

Colliding adapter helper names resolve to the first reviewed owner (model, then
skillcenter).  Adapters remain importable as leaf modules when a specific
``DispatcherAuthority`` or ``ResolvedScopeClaim`` class is required.

Exports are lazy and dependency-light.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "model": (
        "ARGUMENT_COMMITMENT_DOMAIN",
        "INVOCATION_ENVELOPE_COLLECTION_SCHEMA",
        "INVOCATION_ENVELOPE_IDENTITY_DOMAIN",
        "INVOCATION_ENVELOPE_INTERFACE",
        "INVOCATION_ENVELOPE_SCHEMA_VERSION",
        "MAX_COLLECTION_ITEMS",
        "MAX_JSON_DEPTH",
        "MAX_JSON_NODES",
        "MAX_STRING_CHARS",
        "ActorBinding",
        "ArgumentCommitment",
        "AudienceBinding",
        "DelegationLink",
        "DiagnosticSeverity",
        "EnvironmentBinding",
        "InvocationAssumption",
        "InvocationDiagnostic",
        "InvocationEnvelopeValidationError",
        "InvocationIntentEnvelope",
        "InvocationKind",
        "InvocationScope",
        "PolicyRequirements",
        "PurposeContext",
        "RollbackStep",
        "ScopeEntry",
        "ScopeKind",
        "SourceBinding",
        "SourceMapEntry",
        "ToolBinding",
        "UnsupportedField",
        "VerificationStep",
        "commit_redacted_arguments",
        "validate_invocation_envelope",
    ),
    "skillcenter": (
        "SKILLCENTER_INVOCATION_ADAPTER",
        "SKILLCENTER_INVOCATION_ADAPTER_VERSION",
        "DispatcherAuthority",
        "ResolvedScopeClaim",
        "SkillCenterInvocationAdapter",
        "SkillCenterInvocationBoundError",
        "SkillCenterInvocationCapabilityError",
        "SkillCenterInvocationContext",
        "SkillCenterInvocationContextError",
        "SkillCenterInvocationDispatcherError",
        "SkillCenterInvocationError",
        "SkillCenterInvocationIdentityError",
        "SkillCenterInvocationMutableError",
        "SkillCenterInvocationPolicyError",
        "SkillCenterInvocationSecretError",
        "SkillCenterInvocationSideEffectError",
    ),
    "prompt": (
        "PROMPT_INVOCATION_ADAPTER",
        "PROMPT_INVOCATION_ADAPTER_VERSION",
        "PROMPT_SEGMENT_DIGEST_DOMAIN",
        "BoundPromptSegment",
        "PromptContentSegment",
        "PromptInvocationAdapter",
        "PromptInvocationBoundError",
        "PromptInvocationCapabilityError",
        "PromptInvocationContext",
        "PromptInvocationContextError",
        "PromptInvocationDispatcherError",
        "PromptInvocationError",
        "PromptInvocationIdentityError",
        "PromptInvocationPolicyError",
        "PromptInvocationSecretError",
        "PromptInvocationSegmentError",
        "PromptInvocationSideEffectError",
        "PromptSegmentKind",
    ),
    "mcp": (
        "MCP_INVOCATION_ADAPTER",
        "MCP_INVOCATION_ADAPTER_VERSION",
        "MCP_REQUESTED_OUTPUT_DOMAIN",
        "MCPInvocationAdapter",
        "MCPInvocationBoundError",
        "MCPInvocationCapabilityError",
        "MCPInvocationContext",
        "MCPInvocationDispatcherError",
        "MCPInvocationError",
        "MCPInvocationIdentityError",
        "MCPInvocationPolicyError",
        "MCPInvocationSchemaError",
        "MCPInvocationSecretError",
        "MCPInvocationSideEffectError",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

if len(_EXPORT_MODULE) != sum(len(names) for names in _EXPORTS.values()):
    raise RuntimeError("package exports must have one owning module per symbol")

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> Any:
    """Load a reviewed contract from its owning leaf module (lazy, cycle-safe)."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
