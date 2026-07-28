"""Adapt MCP tool definitions and call context into invocation envelopes.

Interface: ``MCPInvocationAdapter@1``

A concrete MCP call proposal is bound to an immutable
:class:`~ipfs_datasets_py.logic.intent_ir.invocation.model.InvocationIntentEnvelope`
**before** Legal/Security evaluation and **before** any transport dispatch.

Non-goals (fail-closed invariants):
- Never connects to an MCP server, opens sockets, or invokes a tool.
- Never evaluates JSON Schema as code, follows ``$ref`` / ``$dynamicRef``, or
  loads remote schemas.
- Never elevates tool annotations to trusted facts (capabilities, effects,
  audience, or dispatcher identity).
- Never stores raw secrets; arguments must already be redacted views.
- Never accepts a caller-controlled dispatcher identity (confused-deputy guard).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Iterable

from ..source_adapters.mcp_tool import (
    AllowedUseDecision,
    MCPToolIntentAdapter,
    MCPToolPolicyError,
    MCPToolRecord,
    MCPToolSourcePolicy,
    MCPToolSourcePolicyDecision,
    TrustDecision,
)
from .model import (
    MAX_COLLECTION_ITEMS,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_STRING_CHARS,
    ActorBinding,
    ArgumentCommitment,
    AudienceBinding,
    DelegationLink,
    DiagnosticSeverity,
    EnvironmentBinding,
    InvocationAssumption,
    InvocationDiagnostic,
    InvocationEnvelopeValidationError,
    InvocationIntentEnvelope,
    InvocationKind,
    InvocationScope,
    PolicyRequirements,
    PurposeContext,
    RollbackStep,
    ScopeEntry,
    ScopeKind,
    SourceBinding,
    SourceMapEntry,
    ToolBinding,
    UnsupportedField,
    VerificationStep,
    commit_redacted_arguments,
    validate_invocation_envelope,
)


MCP_INVOCATION_ADAPTER: Final = "MCPInvocationAdapter@1"
MCP_INVOCATION_ADAPTER_VERSION: Final = "mcp-invocation-adapter/v1"
MCP_REQUESTED_OUTPUT_DOMAIN: Final = "invocation-intent.mcp-requested-output/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,255}$")
_DYNAMIC_SCHEMA_KEYS: Final = frozenset(
    {
        "$ref",
        "$dynamicRef",
        "$dynamicAnchor",
        "$recursiveRef",
        "$recursiveAnchor",
    }
)
_CALLER_DISPATCHER_MARKERS: Final = frozenset(
    {
        "caller",
        "client",
        "user",
        "untrusted",
        "annotation",
        "tool",
        "self",
        "request",
        "prompt",
    }
)

# Keys that must never appear as elevated authority from tool annotations.
_ANNOTATION_AUTHORITY_KEYS: Final = frozenset(
    {
        "audience",
        "audience_id",
        "dispatcher",
        "dispatcher_id",
        "capabilities",
        "effects",
        "resolved_capabilities",
        "resolved_effects",
        "environment",
        "environment_id",
        "transport_peer",
        "server_id",
        "trust_domain",
    }
)


class MCPInvocationError(ValueError):
    """Base error for MCP → invocation envelope adaptation failures."""


class MCPInvocationIdentityError(MCPInvocationError):
    """Raised when tool/server/schema identities do not match expectations."""


class MCPInvocationSchemaError(MCPInvocationError):
    """Raised when input/output schemas are dynamic, oversized, or malformed."""


class MCPInvocationBoundError(MCPInvocationError):
    """Raised when arguments or nested payloads exceed hard bounds."""


class MCPInvocationSecretError(MCPInvocationError):
    """Raised when raw secrets would be serialized into the envelope."""


class MCPInvocationDispatcherError(MCPInvocationError):
    """Raised when dispatcher/audience identity is caller-controlled."""


class MCPInvocationCapabilityError(MCPInvocationError):
    """Raised when a requested capability is not in the host allowlist."""


class MCPInvocationSideEffectError(MCPInvocationError):
    """Raised when adaptation would perform network or tool side effects."""


class MCPInvocationPolicyError(MCPInvocationError):
    """Raised when the underlying MCP source policy rejects the tool record."""

    def __init__(self, decision: MCPToolSourcePolicyDecision) -> None:
        self.decision = decision
        super().__init__(
            "MCP tool is not eligible for invocation adaptation: "
            f"{decision.allowed_use.value}"
        )


class DispatcherAuthority(str, Enum):
    """Who is authoritative for audience/dispatcher binding.

    Only host/runtime authorities are accepted. Caller, annotation, and tool
    claims are rejected (confused-deputy prevention).
    """

    HOST = "host"
    RUNTIME = "runtime"


class ResolvedScopeClaim:
    """One host-resolved scope claim (not an annotation)."""

    __slots__ = ("entry_id", "value", "description", "attributes")

    def __init__(
        self,
        entry_id: str,
        value: str,
        *,
        description: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(entry_id, str) or not _ID_RE.fullmatch(entry_id):
            raise MCPInvocationError(f"scope claim entry_id is invalid: {entry_id!r}")
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise MCPInvocationError(f"scope claim value is invalid for {entry_id}")
        if len(value) > MAX_STRING_CHARS:
            raise MCPInvocationBoundError(
                f"scope claim value for {entry_id} exceeds maximum string length"
            )
        if description is None:
            description = ""
        if not isinstance(description, str) or (
            description and description != description.strip()
        ):
            raise MCPInvocationError(
                f"scope claim description is invalid for {entry_id}"
            )
        self.entry_id = entry_id
        self.value = value
        self.description = description
        self.attributes = dict(attributes or {})


@dataclass(frozen=True, slots=True)
class MCPInvocationContext:
    """Host- and caller-supplied runtime context for one proposed MCP call.

    Identity fields (server, transport peer, tool version, audience,
    environment, resolved capabilities/effects) must be supplied by the
    host/runtime observer. Tool annotations must not author these fields.
    """

    envelope_id: str
    tenant_id: str
    actor: ActorBinding
    audience: AudienceBinding
    environment: EnvironmentBinding
    redacted_arguments: Mapping[str, Any]
    nonce: str
    created_at: str
    deadline: str
    server_id: str
    transport_peer: str = ""
    tool_version: str = ""
    server_name: str = ""
    dispatcher_authority: DispatcherAuthority = DispatcherAuthority.HOST
    known_capabilities: tuple[str, ...] = ()
    resolved_capabilities: tuple[ResolvedScopeClaim, ...] = ()
    resolved_effects: tuple[ResolvedScopeClaim, ...] = ()
    resolved_resources: tuple[ResolvedScopeClaim, ...] = ()
    resolved_network: tuple[ResolvedScopeClaim, ...] = ()
    resolved_filesystem: tuple[ResolvedScopeClaim, ...] = ()
    resolved_subprocess: tuple[ResolvedScopeClaim, ...] = ()
    resolved_data_classes: tuple[ResolvedScopeClaim, ...] = ()
    resolved_assets: tuple[ResolvedScopeClaim, ...] = ()
    secret_refs: tuple[str, ...] = ()
    delegation: tuple[DelegationLink, ...] = ()
    purpose: PurposeContext = field(default_factory=PurposeContext)
    policy: PolicyRequirements = field(default_factory=PolicyRequirements)
    trust_domain: str = ""
    trace_id: str = ""
    requested_output: Mapping[str, Any] | str | None = None
    expected_tool_name: str = ""
    expected_tool_id: str = ""
    expected_content_sha256: str = ""
    expected_input_schema_sha256: str = ""
    expected_server_id: str = ""
    expected_server_name: str = ""
    expected_transport_peer: str = ""
    intent_document_id: str = ""
    formalization_artifact_id: str = ""
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    rollback: tuple[RollbackStep, ...] = ()
    verification: tuple[VerificationStep, ...] = ()
    # Explicit opt-in for tests that try to force side effects — always rejected.
    allow_network: bool = False
    allow_tool_invoke: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "envelope_id", _require_identifier(self.envelope_id, "envelope_id")
        )
        object.__setattr__(
            self, "tenant_id", _require_identifier(self.tenant_id, "tenant_id")
        )
        if not isinstance(self.actor, ActorBinding):
            raise MCPInvocationError("actor must be an ActorBinding")
        if not isinstance(self.audience, AudienceBinding):
            raise MCPInvocationError("audience must be an AudienceBinding")
        if not isinstance(self.environment, EnvironmentBinding):
            raise MCPInvocationError("environment must be an EnvironmentBinding")
        if not isinstance(self.redacted_arguments, Mapping):
            raise MCPInvocationError("redacted_arguments must be a mapping")
        object.__setattr__(
            self, "server_id", _require_identifier(self.server_id, "server_id")
        )
        object.__setattr__(
            self,
            "transport_peer",
            _optional_text(self.transport_peer, "transport_peer"),
        )
        object.__setattr__(
            self, "tool_version", _optional_text(self.tool_version, "tool_version")
        )
        object.__setattr__(
            self, "server_name", _optional_text(self.server_name, "server_name")
        )
        authority = self.dispatcher_authority
        if isinstance(authority, str):
            try:
                authority = DispatcherAuthority(authority)
            except ValueError as exc:
                raise MCPInvocationDispatcherError(
                    f"unsupported dispatcher_authority: {self.dispatcher_authority!r}"
                ) from exc
        if not isinstance(authority, DispatcherAuthority):
            raise MCPInvocationDispatcherError(
                "dispatcher_authority must be a DispatcherAuthority"
            )
        object.__setattr__(self, "dispatcher_authority", authority)
        object.__setattr__(
            self,
            "known_capabilities",
            _unique_strings(self.known_capabilities, "known_capabilities"),
        )
        object.__setattr__(
            self,
            "resolved_capabilities",
            _coerce_claims(self.resolved_capabilities, "resolved_capabilities"),
        )
        object.__setattr__(
            self,
            "resolved_effects",
            _coerce_claims(self.resolved_effects, "resolved_effects"),
        )
        object.__setattr__(
            self,
            "resolved_resources",
            _coerce_claims(self.resolved_resources, "resolved_resources"),
        )
        object.__setattr__(
            self,
            "resolved_network",
            _coerce_claims(self.resolved_network, "resolved_network"),
        )
        object.__setattr__(
            self,
            "resolved_filesystem",
            _coerce_claims(self.resolved_filesystem, "resolved_filesystem"),
        )
        object.__setattr__(
            self,
            "resolved_subprocess",
            _coerce_claims(self.resolved_subprocess, "resolved_subprocess"),
        )
        object.__setattr__(
            self,
            "resolved_data_classes",
            _coerce_claims(self.resolved_data_classes, "resolved_data_classes"),
        )
        object.__setattr__(
            self,
            "resolved_assets",
            _coerce_claims(self.resolved_assets, "resolved_assets"),
        )
        object.__setattr__(
            self, "secret_refs", _unique_identifiers(self.secret_refs, "secret_refs")
        )
        if not isinstance(self.delegation, tuple):
            object.__setattr__(self, "delegation", tuple(self.delegation))
        for link in self.delegation:
            if not isinstance(link, DelegationLink):
                raise MCPInvocationError("delegation entries must be DelegationLink")
        if not isinstance(self.purpose, PurposeContext):
            raise MCPInvocationError("purpose must be a PurposeContext")
        if not isinstance(self.policy, PolicyRequirements):
            raise MCPInvocationError("policy must be PolicyRequirements")
        object.__setattr__(
            self, "nonce", _require_identifier(self.nonce, "nonce")
        )
        object.__setattr__(
            self, "created_at", _require_text(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "deadline", _require_text(self.deadline, "deadline")
        )
        object.__setattr__(
            self,
            "trust_domain",
            _optional_identifier(self.trust_domain, "trust_domain"),
        )
        object.__setattr__(
            self, "trace_id", _optional_identifier(self.trace_id, "trace_id")
        )
        for name in (
            "expected_tool_name",
            "expected_tool_id",
            "expected_content_sha256",
            "expected_input_schema_sha256",
            "expected_server_id",
            "expected_server_name",
            "expected_transport_peer",
            "intent_document_id",
            "formalization_artifact_id",
        ):
            value = getattr(self, name)
            object.__setattr__(self, name, _optional_text(value, name))
        object.__setattr__(
            self,
            "preconditions",
            _unique_texts(self.preconditions, "preconditions", ordered=True),
        )
        object.__setattr__(
            self,
            "postconditions",
            _unique_texts(self.postconditions, "postconditions", ordered=True),
        )
        object.__setattr__(
            self,
            "failure_modes",
            _unique_texts(self.failure_modes, "failure_modes", ordered=True),
        )
        if not isinstance(self.rollback, tuple):
            object.__setattr__(self, "rollback", tuple(self.rollback))
        if not isinstance(self.verification, tuple):
            object.__setattr__(self, "verification", tuple(self.verification))
        if self.allow_network or self.allow_tool_invoke:
            raise MCPInvocationSideEffectError(
                "network and tool invocation are forbidden during MCP adaptation"
            )
        if not isinstance(self.attributes, Mapping):
            raise MCPInvocationError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))


class MCPInvocationAdapter:
    """Project an MCP tool record + call context into an invocation envelope.

    Interface: ``MCPInvocationAdapter@1``.

    Wraps the completed :class:`MCPToolIntentAdapter` source path for policy
    evaluation and Intent document production without connecting to a server
    or invoking the described tool.
    """

    def __init__(
        self,
        *,
        source_adapter: MCPToolIntentAdapter | None = None,
        policy: MCPToolSourcePolicy | None = None,
        max_argument_nodes: int = MAX_JSON_NODES,
        max_argument_depth: int = MAX_JSON_DEPTH,
        max_argument_chars: int = MAX_STRING_CHARS,
    ) -> None:
        if source_adapter is not None and not isinstance(
            source_adapter, MCPToolIntentAdapter
        ):
            raise TypeError("source_adapter must be an MCPToolIntentAdapter")
        if policy is not None and not isinstance(policy, MCPToolSourcePolicy):
            raise TypeError("policy must be an MCPToolSourcePolicy")
        for name, value in (
            ("max_argument_nodes", max_argument_nodes),
            ("max_argument_depth", max_argument_depth),
            ("max_argument_chars", max_argument_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.max_argument_nodes = max_argument_nodes
        self.max_argument_depth = max_argument_depth
        self.max_argument_chars = max_argument_chars
        self.source_adapter = source_adapter or MCPToolIntentAdapter(policy=policy)
        self.interface = MCP_INVOCATION_ADAPTER
        self.adapter_version = MCP_INVOCATION_ADAPTER_VERSION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adapt(
        self,
        record: MCPToolRecord,
        context: MCPInvocationContext,
        *,
        intent_document_id: str = "",
        formalization_artifact_id: str = "",
    ) -> InvocationIntentEnvelope:
        """Return a validated invocation envelope for the proposed MCP call."""

        return self.adapt_with_policy(
            record,
            context,
            intent_document_id=intent_document_id,
            formalization_artifact_id=formalization_artifact_id,
        )[0]

    def adapt_with_policy(
        self,
        record: MCPToolRecord,
        context: MCPInvocationContext,
        *,
        intent_document_id: str = "",
        formalization_artifact_id: str = "",
    ) -> tuple[InvocationIntentEnvelope, MCPToolSourcePolicyDecision]:
        """Adapt and also return the source-policy decision used."""

        self._reject_side_effects(context)
        if not isinstance(record, MCPToolRecord):
            raise TypeError("record must be an MCPToolRecord")
        if not isinstance(context, MCPInvocationContext):
            raise TypeError("context must be an MCPInvocationContext")

        decision = self.source_adapter.evaluate(record)
        if decision.allowed_use is not AllowedUseDecision.ALLOW_INTERNAL_EVALUATION:
            raise MCPInvocationPolicyError(decision)
        if decision.trust_decision is TrustDecision.QUARANTINED:
            raise MCPInvocationPolicyError(decision)

        # Optionally produce Intent IR through the existing source adapter path.
        # This still never invokes the tool or opens a network connection.
        intent_document = None
        try:
            intent_document, decision = self.source_adapter.adapt_with_policy(record)
        except MCPToolPolicyError as exc:
            raise MCPInvocationPolicyError(exc.decision) from exc

        self._validate_identity(record, context)
        self._validate_dispatcher(context)
        input_schema = self._parse_and_bound_schema(
            record.input_schema_json, "input_schema"
        )
        output_schema = (
            self._parse_and_bound_schema(record.output_schema_json, "output_schema")
            if record.output_schema_json
            else {}
        )
        self._validate_arguments(context.redacted_arguments, input_schema)
        arguments = self._commit_arguments(context)
        scope = self._build_scope(record, context)
        tool = self._build_tool_binding(record, context, input_schema, output_schema)
        source = self._build_source_binding(
            record,
            context,
            intent_document_id=intent_document_id
            or context.intent_document_id
            or (intent_document.document_id if intent_document is not None else ""),
            formalization_artifact_id=formalization_artifact_id
            or context.formalization_artifact_id,
        )
        annotations_unsupported, annotation_diagnostics, annotation_assumptions = (
            self._record_annotations_as_untrusted(record)
        )
        requested_output_fields = self._bind_requested_output(
            record, context, output_schema
        )
        unsupported = annotations_unsupported + requested_output_fields.unsupported
        diagnostics = (
            (
                InvocationDiagnostic(
                    code="invocation.mcp.adapted",
                    message=(
                        f"Adapted MCP tool {record.name!r} via "
                        f"{MCP_INVOCATION_ADAPTER} without transport call"
                    ),
                    severity=DiagnosticSeverity.INFO,
                ),
            )
            + annotation_diagnostics
            + requested_output_fields.diagnostics
        )
        source_maps = self._source_maps(record, source.source_ref)
        assumptions = annotation_assumptions + (
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "schema-stable"),
                statement=(
                    "Tool input schema is stable for the bound revision and "
                    "was not re-fetched during adaptation"
                ),
                source_ref=source.source_ref,
            ),
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "no-side-effect"),
                statement=(
                    "Adaptation performed no network I/O and did not invoke "
                    "the described MCP tool"
                ),
                source_ref=source.source_ref,
            ),
        )

        postconditions = list(context.postconditions)
        if requested_output_fields.postcondition:
            postconditions.append(requested_output_fields.postcondition)
        verification = list(context.verification)
        if requested_output_fields.verification is not None:
            verification.append(requested_output_fields.verification)

        try:
            envelope = InvocationIntentEnvelope(
                envelope_id=context.envelope_id,
                invocation_kind=InvocationKind.MCP_TOOL,
                source=source,
                tenant_id=context.tenant_id,
                actor=context.actor,
                audience=context.audience,
                tool=tool,
                arguments=arguments,
                scope=scope,
                purpose=context.purpose,
                environment=context.environment,
                preconditions=tuple(context.preconditions),
                postconditions=tuple(postconditions),
                failure_modes=tuple(context.failure_modes)
                or ("tool timeout", "schema validation failure"),
                rollback=tuple(context.rollback)
                or (
                    RollbackStep(
                        step_id="rollback:mcp-noop",
                        description=(
                            "No side effects declared at adaptation time; "
                            "dispatch remains blocked until authorization"
                        ),
                    ),
                ),
                verification=tuple(verification)
                or (
                    VerificationStep(
                        step_id="verify:mcp-schema",
                        description="Response must match bound output schema identity",
                        predicate="output_schema_bound",
                    ),
                ),
                policy=context.policy,
                nonce=context.nonce,
                created_at=context.created_at,
                deadline=context.deadline,
                trace_id=context.trace_id,
                source_maps=source_maps,
                assumptions=assumptions,
                diagnostics=diagnostics,
                unsupported_fields=unsupported,
                delegation=tuple(context.delegation),
                trust_domain=context.trust_domain or context.actor.trust_domain,
            )
        except InvocationEnvelopeValidationError as exc:
            message = str(exc).lower()
            if "raw secret" in message or "redacted token" in message:
                raise MCPInvocationSecretError(str(exc)) from exc
            if "depth" in message or "nodes" in message or "maximum" in message:
                raise MCPInvocationBoundError(str(exc)) from exc
            raise MCPInvocationError(str(exc)) from exc

        return validate_invocation_envelope(envelope), decision

    normalize = adapt
    normalize_with_policy = adapt_with_policy

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _reject_side_effects(self, context: MCPInvocationContext) -> None:
        if context.allow_network or context.allow_tool_invoke:
            raise MCPInvocationSideEffectError(
                "network and tool invocation are forbidden during MCP adaptation"
            )
        # Defense in depth: refuse obvious dispatch hooks on context attributes.
        attrs = context.attributes
        for forbidden in (
            "connect",
            "invoke",
            "dispatch",
            "endpoint_url",
            "call_tool",
            "transport_call",
        ):
            if forbidden in attrs and attrs[forbidden]:
                raise MCPInvocationSideEffectError(
                    f"context attribute {forbidden!r} would trigger a side effect"
                )

    def _validate_identity(
        self, record: MCPToolRecord, context: MCPInvocationContext
    ) -> None:
        if context.expected_tool_name and context.expected_tool_name != record.name:
            raise MCPInvocationIdentityError(
                f"tool name mismatch: expected {context.expected_tool_name!r}, "
                f"got {record.name!r}"
            )
        if context.expected_tool_id and context.expected_tool_id != record.tool_id:
            raise MCPInvocationIdentityError(
                f"tool id mismatch: expected {context.expected_tool_id!r}, "
                f"got {record.tool_id!r}"
            )
        if (
            context.expected_content_sha256
            and context.expected_content_sha256 != record.content_sha256
        ):
            raise MCPInvocationIdentityError(
                "tool content_sha256 mismatch (identity drift or wrong revision)"
            )
        input_schema_sha = _sha256_hex_of_text(record.input_schema_json)
        if (
            context.expected_input_schema_sha256
            and context.expected_input_schema_sha256 != input_schema_sha
        ):
            raise MCPInvocationIdentityError(
                "input schema sha256 mismatch between context expectation and record"
            )
        if context.expected_server_id and context.expected_server_id != context.server_id:
            raise MCPInvocationIdentityError(
                f"server_id mismatch: expected {context.expected_server_id!r}, "
                f"got {context.server_id!r}"
            )
        bound_server_name = context.server_name or record.server_name
        if (
            context.expected_server_name
            and context.expected_server_name != bound_server_name
        ):
            raise MCPInvocationIdentityError(
                f"server_name mismatch: expected {context.expected_server_name!r}, "
                f"got {bound_server_name!r}"
            )
        if (
            context.expected_transport_peer
            and context.expected_transport_peer != context.transport_peer
        ):
            raise MCPInvocationIdentityError(
                f"transport_peer mismatch: expected "
                f"{context.expected_transport_peer!r}, got {context.transport_peer!r}"
            )
        if record.server_name and context.server_name:
            if record.server_name != context.server_name:
                raise MCPInvocationIdentityError(
                    f"record server_name {record.server_name!r} does not match "
                    f"context server_name {context.server_name!r}"
                )

    def _validate_dispatcher(self, context: MCPInvocationContext) -> None:
        if context.dispatcher_authority not in {
            DispatcherAuthority.HOST,
            DispatcherAuthority.RUNTIME,
        }:
            raise MCPInvocationDispatcherError(
                "dispatcher_authority must be host or runtime; "
                "caller-controlled dispatcher is rejected"
            )
        audience = context.audience
        # Reject markers that indicate the caller/tool chose the dispatcher.
        if audience.kind.lower() in _CALLER_DISPATCHER_MARKERS:
            raise MCPInvocationDispatcherError(
                "caller-controlled dispatcher audience is rejected "
                f"(audience.kind={audience.kind!r})"
            )
        for label, candidate in (
            ("audience_id", audience.audience_id),
            ("deployment_id", audience.deployment_id),
            ("trust_domain", audience.trust_domain),
        ):
            if _is_caller_dispatcher_marker(candidate):
                raise MCPInvocationDispatcherError(
                    "caller-controlled dispatcher audience is rejected "
                    f"({label}={candidate!r})"
                )
        for key, value in audience.attributes.items():
            if isinstance(value, str) and _is_caller_dispatcher_marker(value):
                raise MCPInvocationDispatcherError(
                    "caller-controlled dispatcher audience is rejected "
                    f"(attributes.{key}={value!r})"
                )
            if key in {"authority", "controlled_by", "source"} and isinstance(
                value, str
            ):
                if value.lower() in _CALLER_DISPATCHER_MARKERS:
                    raise MCPInvocationDispatcherError(
                        "audience.attributes.authority must not be caller-controlled"
                    )
        if audience.attributes.get("caller_controlled") is True:
            raise MCPInvocationDispatcherError(
                "caller_controlled audience attribute is forbidden"
            )

    def _parse_and_bound_schema(
        self, schema_json: str, label: str
    ) -> dict[str, Any]:
        if not schema_json:
            return {}
        try:
            parsed = json.loads(schema_json)
        except json.JSONDecodeError as exc:
            raise MCPInvocationSchemaError(f"{label} is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise MCPInvocationSchemaError(f"{label} must be a JSON object")
        self._reject_dynamic_schema(parsed, path=f"/{label}")
        self._bound_json(
            parsed,
            name=label,
            max_depth=self.max_argument_depth,
            max_nodes=self.max_argument_nodes,
            max_chars=self.max_argument_chars,
        )
        return parsed

    def _reject_dynamic_schema(self, value: Any, *, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise MCPInvocationSchemaError(
                        f"{path} contains a non-string schema key"
                    )
                if key in _DYNAMIC_SCHEMA_KEYS:
                    raise MCPInvocationSchemaError(
                        f"{path}: dynamic schema feature {key!r} is rejected "
                        "(no remote/dynamic resolution during adaptation)"
                    )
                if key == "additionalProperties" and item is True:
                    # Unrestricted additionalProperties enables dynamic inputs.
                    raise MCPInvocationSchemaError(
                        f"{path}: unrestricted additionalProperties is rejected "
                        "as dynamic input surface"
                    )
                child = f"{path}/{key}" if path != "/" else f"/{key}"
                self._reject_dynamic_schema(item, path=child)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                self._reject_dynamic_schema(item, path=f"{path}[{index}]")

    def _validate_arguments(
        self, arguments: Mapping[str, Any], input_schema: Mapping[str, Any]
    ) -> None:
        self._bound_json(
            arguments,
            name="redacted_arguments",
            max_depth=self.max_argument_depth,
            max_nodes=self.max_argument_nodes,
            max_chars=self.max_argument_chars,
        )
        self._reject_dynamic_arguments(arguments, path="/redacted_arguments")
        # Lightweight required-key check without evaluating JSON Schema as code.
        required = input_schema.get("required")
        if isinstance(required, list):
            missing = [
                key
                for key in required
                if isinstance(key, str) and key not in arguments
            ]
            if missing:
                raise MCPInvocationSchemaError(
                    "arguments missing required input fields: "
                    + ", ".join(sorted(missing))
                )
        properties = input_schema.get("properties")
        if isinstance(properties, Mapping) and properties:
            # Reject completely unknown top-level keys when schema declares props.
            extras = sorted(set(arguments) - set(properties))
            # Allow empty properties object to accept no keys only.
            if extras and properties:
                # Keep fail-closed for undeclared parameters.
                raise MCPInvocationSchemaError(
                    "arguments contain undeclared input fields: "
                    + ", ".join(extras)
                )

    def _reject_dynamic_arguments(self, value: Any, *, path: str) -> None:
        if callable(value) and not isinstance(value, type):
            raise MCPInvocationSchemaError(
                f"{path}: callable/dynamic values are rejected in arguments"
            )
        if isinstance(value, Mapping):
            if any(key in value for key in ("__call__", "__class__", "__import__")):
                raise MCPInvocationSchemaError(
                    f"{path}: dynamic/introspection argument keys are rejected"
                )
            for key, item in value.items():
                if not isinstance(key, str):
                    raise MCPInvocationBoundError(f"{path}: argument keys must be strings")
                self._reject_dynamic_arguments(item, path=f"{path}.{key}")
            return
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for index, item in enumerate(value):
                self._reject_dynamic_arguments(item, path=f"{path}[{index}]")

    def _bound_json(
        self,
        value: Any,
        *,
        name: str,
        max_depth: int,
        max_nodes: int,
        max_chars: int,
        depth: int = 0,
        counter: list[int] | None = None,
    ) -> None:
        if counter is None:
            counter = [0]
        counter[0] += 1
        if counter[0] > max_nodes:
            raise MCPInvocationBoundError(
                f"{name} exceeds maximum of {max_nodes} JSON nodes"
            )
        if depth > max_depth:
            raise MCPInvocationBoundError(
                f"{name} exceeds maximum JSON depth of {max_depth}"
            )
        if isinstance(value, str) and len(value) > max_chars:
            raise MCPInvocationBoundError(
                f"{name} string exceeds maximum length of {max_chars}"
            )
        if isinstance(value, Mapping):
            if len(value) > MAX_COLLECTION_ITEMS:
                raise MCPInvocationBoundError(
                    f"{name} mapping exceeds maximum of {MAX_COLLECTION_ITEMS} keys"
                )
            for key, item in value.items():
                child = f"{name}.{key}" if isinstance(key, str) else f"{name}.?"
                self._bound_json(
                    item,
                    name=child,
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    max_chars=max_chars,
                    depth=depth + 1,
                    counter=counter,
                )
            return
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            if len(value) > MAX_COLLECTION_ITEMS:
                raise MCPInvocationBoundError(
                    f"{name} sequence exceeds maximum of {MAX_COLLECTION_ITEMS} items"
                )
            for index, item in enumerate(value):
                self._bound_json(
                    item,
                    name=f"{name}[{index}]",
                    max_depth=max_depth,
                    max_nodes=max_nodes,
                    max_chars=max_chars,
                    depth=depth + 1,
                    counter=counter,
                )

    def _commit_arguments(
        self, context: MCPInvocationContext
    ) -> ArgumentCommitment:
        try:
            return ArgumentCommitment.from_redacted(
                dict(context.redacted_arguments),
                secret_refs=context.secret_refs,
            )
        except InvocationEnvelopeValidationError as exc:
            message = str(exc).lower()
            if "raw secret" in message or "redacted token" in message:
                raise MCPInvocationSecretError(str(exc)) from exc
            if "depth" in message or "nodes" in message or "maximum" in message:
                raise MCPInvocationBoundError(str(exc)) from exc
            raise MCPInvocationError(str(exc)) from exc

    def _build_tool_binding(
        self,
        record: MCPToolRecord,
        context: MCPInvocationContext,
        input_schema: Mapping[str, Any],
        output_schema: Mapping[str, Any],
    ) -> ToolBinding:
        input_schema_sha = _sha256_hex_of_text(record.input_schema_json)
        input_schema_id = f"schema:{record.name}.input"
        if not _ID_RE.fullmatch(input_schema_id):
            input_schema_id = f"schema:mcp-input:{input_schema_sha[:24]}"
        output_schema_id = ""
        if record.output_schema_json:
            output_sha = _sha256_hex_of_text(record.output_schema_json)
            output_schema_id = f"schema:{record.name}.output"
            if not _ID_RE.fullmatch(output_schema_id):
                output_schema_id = f"schema:mcp-output:{output_sha[:24]}"
        server_name = context.server_name or record.server_name
        attributes: dict[str, Any] = {
            "adapter": MCP_INVOCATION_ADAPTER,
            "adapter_version": MCP_INVOCATION_ADAPTER_VERSION,
            "entry_cid": record.entry_cid,
            "record_tool_id": record.tool_id,
            "input_schema_keys": sorted(input_schema.keys())[:64],
        }
        if output_schema:
            attributes["output_schema_keys"] = sorted(output_schema.keys())[:64]
        return ToolBinding(
            tool_id=record.tool_id,
            tool_name=record.name,
            tool_version=context.tool_version or record.source_revision,
            server_id=context.server_id,
            server_name=server_name,
            transport_peer=context.transport_peer,
            input_schema_id=input_schema_id,
            input_schema_sha256=input_schema_sha,
            output_schema_id=output_schema_id,
            attributes=attributes,
        )

    def _build_source_binding(
        self,
        record: MCPToolRecord,
        context: MCPInvocationContext,
        *,
        intent_document_id: str,
        formalization_artifact_id: str,
    ) -> SourceBinding:
        source_ref = record.to_source_ref()
        return SourceBinding(
            kind=InvocationKind.MCP_TOOL,
            source_ref=source_ref.ref_id,
            source_id=record.source_id or record.tool_id,
            source_revision=record.source_revision,
            content_sha256=record.content_sha256,
            content_cid=record.content_cid,
            intent_document_id=intent_document_id or record.tool_id,
            formalization_artifact_id=formalization_artifact_id,
            attributes={
                "server_name": record.server_name,
                "tool_name": record.name,
                "entry_cid": record.entry_cid,
            },
        )

    def _build_scope(
        self, record: MCPToolRecord, context: MCPInvocationContext
    ) -> InvocationScope:
        known = set(context.known_capabilities)
        capability_entries: list[ScopeEntry] = []
        for claim in context.resolved_capabilities:
            if claim.value not in known:
                raise MCPInvocationCapabilityError(
                    f"unknown capability: {claim.value!r} is not in "
                    "host known_capabilities allowlist"
                )
            capability_entries.append(
                ScopeEntry(
                    entry_id=claim.entry_id,
                    kind=ScopeKind.CAPABILITY,
                    value=claim.value,
                    description=claim.description,
                    attributes=claim.attributes,
                )
            )
        # Annotation-advertised capabilities are never auto-elevated into scope.
        action_entry = ScopeEntry(
            entry_id=f"scope:action:{_safe_token(record.name)}",
            kind=ScopeKind.ACTION,
            value=record.name,
            description=record.description[:512] if record.description else "",
        )
        return InvocationScope(
            actions=(action_entry,),
            effects=_claims_to_entries(context.resolved_effects, ScopeKind.EFFECT),
            capabilities=tuple(capability_entries),
            assets=_claims_to_entries(context.resolved_assets, ScopeKind.ASSET),
            resources=_claims_to_entries(
                context.resolved_resources, ScopeKind.RESOURCE
            ),
            data_classes=_claims_to_entries(
                context.resolved_data_classes, ScopeKind.DATA
            ),
            network=_claims_to_entries(context.resolved_network, ScopeKind.NETWORK),
            filesystem=_claims_to_entries(
                context.resolved_filesystem, ScopeKind.FILESYSTEM
            ),
            subprocess=_claims_to_entries(
                context.resolved_subprocess, ScopeKind.SUBPROCESS
            ),
            secret_refs=tuple(
                ScopeEntry(
                    # Avoid embedding the word "secret" + ":" in entry_id; the
                    # envelope rejects raw secret-like patterns in identifiers.
                    entry_id=(
                        f"scope:sref:{index}:"
                        f"{hashlib.sha256(ref.encode('utf-8')).hexdigest()[:16]}"
                    ),
                    kind=ScopeKind.SECRET_REF,
                    value=ref,
                )
                for index, ref in enumerate(context.secret_refs)
            ),
        )

    def _record_annotations_as_untrusted(
        self, record: MCPToolRecord
    ) -> tuple[
        tuple[UnsupportedField, ...],
        tuple[InvocationDiagnostic, ...],
        tuple[InvocationAssumption, ...],
    ]:
        try:
            annotations = json.loads(record.annotations_json or "{}")
        except json.JSONDecodeError:
            return (
                (
                    UnsupportedField(
                        field_path="/annotations",
                        reason="annotations_json is malformed and was not elevated",
                        source_ref=record.to_source_ref().ref_id,
                        raw_kind="annotation",
                    ),
                ),
                (
                    InvocationDiagnostic(
                        code="invocation.mcp.annotation_malformed",
                        message="MCP annotations are untrusted and malformed",
                        severity=DiagnosticSeverity.WARNING,
                        field_path="/annotations",
                    ),
                ),
                (),
            )
        if not isinstance(annotations, Mapping) or not annotations:
            return (), (), ()

        unsupported: list[UnsupportedField] = []
        diagnostics: list[InvocationDiagnostic] = []
        assumptions: list[InvocationAssumption] = []
        source_ref = record.to_source_ref().ref_id
        for key, value in sorted(annotations.items(), key=lambda item: str(item[0])):
            key_text = str(key)
            field_path = f"/annotations/{key_text}"
            reason = "annotation is untrusted claim, not elevated"
            if key_text in _ANNOTATION_AUTHORITY_KEYS or key_text.lower() in {
                k.lower() for k in _ANNOTATION_AUTHORITY_KEYS
            }:
                reason = (
                    "annotation authority claim is untrusted and must not bind "
                    "audience, capabilities, effects, or environment"
                )
                diagnostics.append(
                    InvocationDiagnostic(
                        code="invocation.mcp.annotation_authority_ignored",
                        message=(
                            f"Ignored untrusted annotation authority key {key_text!r}"
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field_path=field_path,
                    )
                )
            unsupported.append(
                UnsupportedField(
                    field_path=field_path,
                    reason=reason,
                    source_ref=source_ref,
                    raw_kind="annotation",
                    attributes={
                        "value_kind": type(value).__name__,
                        "claimed": True,
                        "trusted": False,
                    },
                )
            )
        diagnostics.append(
            InvocationDiagnostic(
                code="invocation.mcp.annotations_untrusted",
                message=(
                    f"Recorded {len(unsupported)} MCP annotation claim(s) as "
                    "untrusted; none elevated into scope or audience"
                ),
                severity=DiagnosticSeverity.INFO,
                field_path="/annotations",
            )
        )
        assumptions.append(
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "annotations-untrusted"),
                statement=(
                    "MCP tool annotations are untrusted claims and do not "
                    "authorize capabilities, effects, audience, or environment"
                ),
                source_ref=source_ref,
            )
        )
        return tuple(unsupported), tuple(diagnostics), tuple(assumptions)

    def _bind_requested_output(
        self,
        record: MCPToolRecord,
        context: MCPInvocationContext,
        output_schema: Mapping[str, Any],
    ) -> "_RequestedOutputBinding":
        unsupported: list[UnsupportedField] = []
        diagnostics: list[InvocationDiagnostic] = []
        postcondition = ""
        verification: VerificationStep | None = None

        requested = context.requested_output
        if requested is None:
            if output_schema:
                digest = _sha256_hex_of_text(record.output_schema_json)
                postcondition = (
                    f"response conforms to bound output schema sha256:{digest}"
                )
                verification = VerificationStep(
                    step_id="verify:mcp-output-schema",
                    description="Validate tool result against bound output schema id",
                    predicate=f"output_schema_sha256:{digest}",
                )
            return _RequestedOutputBinding(
                postcondition=postcondition,
                verification=verification,
                unsupported=tuple(unsupported),
                diagnostics=tuple(diagnostics),
            )

        if isinstance(requested, str):
            requested_text = requested.strip()
            if not requested_text:
                raise MCPInvocationError("requested_output string must be non-empty")
            if len(requested_text) > MAX_STRING_CHARS:
                raise MCPInvocationBoundError("requested_output exceeds maximum length")
            commitment = _domain_digest(
                MCP_REQUESTED_OUTPUT_DOMAIN, {"requested_output": requested_text}
            )
            postcondition = f"requested_output commitment {commitment}"
            verification = VerificationStep(
                step_id="verify:mcp-requested-output",
                description="Returned payload matches requested output commitment",
                predicate=commitment,
            )
            return _RequestedOutputBinding(
                postcondition=postcondition,
                verification=verification,
                unsupported=(),
                diagnostics=(
                    InvocationDiagnostic(
                        code="invocation.mcp.requested_output_bound",
                        message="Bound requested output string commitment",
                        severity=DiagnosticSeverity.INFO,
                        field_path="/requested_output",
                    ),
                ),
            )

        if not isinstance(requested, Mapping):
            raise MCPInvocationError("requested_output must be a mapping or string")

        self._bound_json(
            requested,
            name="requested_output",
            max_depth=self.max_argument_depth,
            max_nodes=self.max_argument_nodes,
            max_chars=self.max_argument_chars,
        )
        commitment = _domain_digest(
            MCP_REQUESTED_OUTPUT_DOMAIN, {"requested_output": dict(requested)}
        )
        postcondition = f"requested_output commitment {commitment}"
        verification = VerificationStep(
            step_id="verify:mcp-requested-output",
            description="Returned payload matches requested output commitment",
            predicate=commitment,
        )
        if output_schema and set(requested) - set(output_schema.get("properties", {})):
            # Extra keys beyond declared output properties stay as unsupported claims.
            for key in sorted(set(requested) - set(output_schema.get("properties", {}))):
                unsupported.append(
                    UnsupportedField(
                        field_path=f"/requested_output/{key}",
                        reason=(
                            "requested output field is not declared in tool "
                            "output schema properties"
                        ),
                        source_ref=record.to_source_ref().ref_id,
                        raw_kind="requested_output",
                    )
                )
        diagnostics.append(
            InvocationDiagnostic(
                code="invocation.mcp.requested_output_bound",
                message="Bound requested output object commitment",
                severity=DiagnosticSeverity.INFO,
                field_path="/requested_output",
            )
        )
        return _RequestedOutputBinding(
            postcondition=postcondition,
            verification=verification,
            unsupported=tuple(unsupported),
            diagnostics=tuple(diagnostics),
        )

    def _source_maps(
        self, record: MCPToolRecord, source_ref: str
    ) -> tuple[SourceMapEntry, ...]:
        name_end = len(record.name)
        return (
            SourceMapEntry(
                map_id="map:mcp-tool-name",
                field_path="/tool/tool_name",
                source_ref=source_ref,
                start_char=0,
                end_char=name_end,
            ),
            SourceMapEntry(
                map_id="map:mcp-input-schema",
                field_path="/tool/input_schema_sha256",
                source_ref=source_ref,
                start_char=0,
                end_char=min(len(record.input_schema_json), MAX_STRING_CHARS),
            ),
        )


@dataclass(frozen=True, slots=True)
class _RequestedOutputBinding:
    postcondition: str
    verification: VerificationStep | None
    unsupported: tuple[UnsupportedField, ...]
    diagnostics: tuple[InvocationDiagnostic, ...]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MCPInvocationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise MCPInvocationError(f"{name} must not have surrounding whitespace")
    if len(value) > MAX_STRING_CHARS:
        raise MCPInvocationBoundError(f"{name} exceeds maximum string length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, name)


def _require_identifier(value: Any, name: str) -> str:
    text = _require_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise MCPInvocationError(f"{name} is not a stable identifier")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_identifier(value, name)


def _unique_strings(
    values: Sequence[str] | Iterable[str] | None, name: str
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise MCPInvocationError(f"{name} must be a sequence of strings")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise MCPInvocationBoundError(f"{name} exceeds maximum collection size")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise MCPInvocationError(f"{name} entries must be non-empty strings")
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _unique_identifiers(
    values: Sequence[str] | Iterable[str] | None, name: str
) -> tuple[str, ...]:
    items = _unique_strings(values, name)
    for item in items:
        if not _ID_RE.fullmatch(item):
            raise MCPInvocationError(f"{name} contains an invalid identifier: {item!r}")
    return items


def _unique_texts(
    values: Sequence[str] | Iterable[str] | None,
    name: str,
    *,
    ordered: bool,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise MCPInvocationError(f"{name} must be a sequence of strings")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise MCPInvocationBoundError(f"{name} exceeds maximum collection size")
    if ordered:
        result: list[str] = []
        for item in items:
            if not isinstance(item, str) or not item.strip() or item != item.strip():
                raise MCPInvocationError(f"{name} entries must be non-empty strings")
            if len(item) > MAX_STRING_CHARS:
                raise MCPInvocationBoundError(f"{name} entry exceeds maximum length")
            result.append(item)
        return tuple(result)
    return _unique_strings(values, name)


def _coerce_claims(
    values: Sequence[ResolvedScopeClaim] | Iterable[ResolvedScopeClaim] | None,
    name: str,
) -> tuple[ResolvedScopeClaim, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise MCPInvocationError(f"{name} must be a sequence of ResolvedScopeClaim")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise MCPInvocationBoundError(f"{name} exceeds maximum collection size")
    result: list[ResolvedScopeClaim] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            item = ResolvedScopeClaim(
                entry_id=item["entry_id"],
                value=item["value"],
                description=item.get("description", ""),
                attributes=item.get("attributes"),
            )
        if not isinstance(item, ResolvedScopeClaim):
            raise MCPInvocationError(f"{name} entries must be ResolvedScopeClaim")
        if item.entry_id in seen:
            raise MCPInvocationError(f"duplicate scope claim entry_id: {item.entry_id}")
        seen.add(item.entry_id)
        result.append(item)
    return tuple(result)


def _claims_to_entries(
    claims: Sequence[ResolvedScopeClaim], kind: ScopeKind
) -> tuple[ScopeEntry, ...]:
    return tuple(
        ScopeEntry(
            entry_id=claim.entry_id,
            kind=kind,
            value=claim.value,
            description=claim.description,
            attributes=claim.attributes,
        )
        for claim in claims
    )


def _sha256_hex_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _domain_digest(domain: str, payload: Mapping[str, Any]) -> str:
    material = {
        "domain": domain,
        "payload": payload,
    }
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        .encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _safe_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    if not cleaned:
        cleaned = "x"
    return cleaned[:64]


def _is_caller_dispatcher_marker(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    for marker in _CALLER_DISPATCHER_MARKERS:
        if (
            lowered == marker
            or lowered.startswith(f"{marker}:")
            or lowered.startswith(f"{marker}.")
            or lowered.startswith(f"{marker}-")
            or lowered.startswith(f"{marker}_")
        ):
            return True
    return False


def _stable_assumption_id(record: MCPToolRecord, label: str) -> str:
    material = f"{record.tool_id}|{label}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"assume:mcp-{label}-{digest}"


__all__ = [
    "MCP_INVOCATION_ADAPTER",
    "MCP_INVOCATION_ADAPTER_VERSION",
    "MCP_REQUESTED_OUTPUT_DOMAIN",
    "DispatcherAuthority",
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
    "ResolvedScopeClaim",
    "commit_redacted_arguments",
]
