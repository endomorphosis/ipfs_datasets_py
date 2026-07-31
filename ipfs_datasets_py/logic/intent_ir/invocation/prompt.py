"""Adapt free-form prompt intent into invocation envelopes.

Interface: ``PromptInvocationAdapter@1``

A bounded :class:`~ipfs_datasets_py.logic.intent_ir.source_adapters.prompt.PromptRecord`
plus host/runtime context is bound to an immutable
:class:`~ipfs_datasets_py.logic.intent_ir.invocation.model.InvocationIntentEnvelope`
**before** Legal/Security evaluation and **before** any model, tool, or shell
execution.

Content segments (user instruction, quoted data, retrieved evidence, tool
output) are host-declared, span-bound, and never elevated into trusted
capabilities or audience.

Non-goals (fail-closed invariants):
- Never executes prompt text, shell markup, or tool-call directives.
- Never treats prompt prose as trusted instructions for this process.
- Never elevates prompt claims to capabilities, audience, or environment.
- Never stores raw secrets; arguments and segment views must be redacted.
- Never accepts a caller-controlled dispatcher identity (confused-deputy guard).
- Never invents permissions or capabilities from candidate inference.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Iterable

from ..schema import IntentIRDocument, StatementKind
from ..source_adapters.prompt import (
    AllowedUseDecision,
    PromptIntentAdapter,
    PromptPolicyError,
    PromptRecord,
    PromptSourcePolicy,
    PromptSourcePolicyDecision,
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
    validate_invocation_envelope,
)


PROMPT_INVOCATION_ADAPTER: Final = "PromptInvocationAdapter@1"
PROMPT_INVOCATION_ADAPTER_VERSION: Final = "prompt-invocation-adapter/v1"
PROMPT_SEGMENT_DIGEST_DOMAIN: Final = "invocation-intent.prompt-segment/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
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
        "skill",
    }
)
_ALLOWED_POLICY_USES: Final = frozenset(
    {
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    }
)
# Prompt prose that looks like authority must stay unsupported, never elevated.
_PROMPT_AUTHORITY_HINTS: Final = frozenset(
    {
        "capability",
        "capabilities",
        "permission",
        "permissions",
        "audience",
        "dispatcher",
        "environment",
        "trust_domain",
        "authorize",
        "grant access",
        "sudo",
        "admin.superuser",
        "role=admin",
    }
)
_REDACTED_TOKEN: Final = "[REDACTED]"
_SECRET_INLINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(
        r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
        r"github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9])"
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
        r"AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9])"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
)


class PromptInvocationError(ValueError):
    """Base error for prompt → invocation envelope adaptation failures."""


class PromptInvocationIdentityError(PromptInvocationError):
    """Raised when prompt/content/Intent identities do not match expectations."""


class PromptInvocationBoundError(PromptInvocationError):
    """Raised when arguments, segments, or nested payloads exceed hard bounds."""


class PromptInvocationSecretError(PromptInvocationError):
    """Raised when raw secrets would be serialized into the envelope."""


class PromptInvocationDispatcherError(PromptInvocationError):
    """Raised when dispatcher/audience identity is caller-controlled."""


class PromptInvocationCapabilityError(PromptInvocationError):
    """Raised when a requested capability is not in the host allowlist."""


class PromptInvocationSideEffectError(PromptInvocationError):
    """Raised when adaptation would execute prompt content or open network I/O."""


class PromptInvocationContextError(PromptInvocationError):
    """Raised when required runtime context is missing or incomplete."""


class PromptInvocationSegmentError(PromptInvocationError):
    """Raised when content segments are malformed, out of range, or conflicting."""


class PromptInvocationPolicyError(PromptInvocationError):
    """Raised when the prompt source policy rejects the record."""

    def __init__(self, decision: PromptSourcePolicyDecision) -> None:
        self.decision = decision
        super().__init__(
            "Prompt is not eligible for invocation adaptation: "
            f"{decision.allowed_use.value}"
        )


class DispatcherAuthority(str, Enum):
    """Who is authoritative for audience/dispatcher binding.

    Only host/runtime authorities are accepted. Caller, prompt text, and
    annotation claims are rejected (confused-deputy prevention).
    """

    HOST = "host"
    RUNTIME = "runtime"


class PromptSegmentKind(str, Enum):
    """Role of one exact prompt content segment.

    Segments classify *data provenance*, not authority.  A ``tool_output``
    segment never invents tool permission; a ``user_instruction`` segment
    never elevates into host capabilities.
    """

    USER_INSTRUCTION = "user_instruction"
    QUOTED_DATA = "quoted_data"
    RETRIEVED_EVIDENCE = "retrieved_evidence"
    TOOL_OUTPUT = "tool_output"


class ResolvedScopeClaim:
    """One host-resolved scope claim (not derived from prompt prose alone)."""

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
            raise PromptInvocationError(
                f"scope claim entry_id is invalid: {entry_id!r}"
            )
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise PromptInvocationError(
                f"scope claim value is invalid for {entry_id}"
            )
        if len(value) > MAX_STRING_CHARS:
            raise PromptInvocationBoundError(
                f"scope claim value for {entry_id} exceeds maximum string length"
            )
        if description is None:
            description = ""
        if not isinstance(description, str) or (
            description and description != description.strip()
        ):
            raise PromptInvocationError(
                f"scope claim description is invalid for {entry_id}"
            )
        if len(description) > MAX_STRING_CHARS:
            raise PromptInvocationBoundError(
                f"scope claim description for {entry_id} exceeds maximum string length"
            )
        self.entry_id = entry_id
        self.value = value
        self.description = description
        self.attributes = dict(attributes or {})


@dataclass(frozen=True, slots=True)
class PromptContentSegment:
    """Host-declared exact span within the prompt body with a content role.

    Spans are half-open ``[start_char, end_char)`` into ``PromptRecord.text``.
    When ``redact`` is true, only a redaction token and content digest enter the
    envelope (sensitive span redaction).
    """

    segment_id: str
    kind: PromptSegmentKind
    start_char: int
    end_char: int
    redact: bool = False
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, str) or not _ID_RE.fullmatch(
            self.segment_id
        ):
            raise PromptInvocationSegmentError(
                f"segment_id is not a stable identifier: {self.segment_id!r}"
            )
        kind = self.kind
        if isinstance(kind, str):
            try:
                kind = PromptSegmentKind(kind)
            except ValueError as exc:
                raise PromptInvocationSegmentError(
                    f"unsupported segment kind: {self.kind!r}"
                ) from exc
        if not isinstance(kind, PromptSegmentKind):
            raise PromptInvocationSegmentError("kind must be a PromptSegmentKind")
        object.__setattr__(self, "kind", kind)
        for name in ("start_char", "end_char"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise PromptInvocationSegmentError(f"{name} must be an integer")
            if value < 0:
                raise PromptInvocationSegmentError(f"{name} must be non-negative")
        if self.end_char < self.start_char:
            raise PromptInvocationSegmentError(
                "segment must satisfy start_char <= end_char"
            )
        if not isinstance(self.redact, bool):
            raise PromptInvocationSegmentError("redact must be a boolean")
        label = self.label if self.label is not None else ""
        if not isinstance(label, str) or (label and label != label.strip()):
            raise PromptInvocationSegmentError("label must be normalized text")
        if len(label) > MAX_STRING_CHARS:
            raise PromptInvocationBoundError("label exceeds maximum string length")
        object.__setattr__(self, "label", label)
        if not isinstance(self.attributes, Mapping):
            raise PromptInvocationSegmentError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "end_char": self.end_char,
            "kind": self.kind.value,
            "label": self.label,
            "redact": self.redact,
            "segment_id": self.segment_id,
            "start_char": self.start_char,
        }


@dataclass(frozen=True, slots=True)
class BoundPromptSegment:
    """Resolved segment view after identity/redaction binding (not elevated)."""

    segment_id: str
    kind: PromptSegmentKind
    start_char: int
    end_char: int
    content_sha256: str
    redacted: bool
    redacted_text: str
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "content_sha256": self.content_sha256,
            "end_char": self.end_char,
            "kind": self.kind.value,
            "label": self.label,
            "redacted": self.redacted,
            "redacted_text": self.redacted_text,
            "segment_id": self.segment_id,
            "start_char": self.start_char,
        }


@dataclass(frozen=True, slots=True)
class PromptInvocationContext:
    """Host- and caller-supplied runtime context for one proposed prompt invocation.

    Identity fields (audience, environment, resolved capabilities/effects, and
    content segment roles) must be supplied by the host/runtime observer.
    Prompt text must not author those fields.
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
    dispatcher_authority: DispatcherAuthority = DispatcherAuthority.HOST
    content_segments: tuple[PromptContentSegment, ...] = ()
    # Target model / prompt channel identity (host-supplied tool binding fields).
    tool_id: str = ""
    tool_name: str = ""
    tool_version: str = ""
    server_id: str = "server:prompt"
    server_name: str = "prompt"
    transport_peer: str = ""
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
    intent_document_id: str = ""
    formalization_artifact_id: str = ""
    # Exact identity pins (optional; when set they must match the record/doc).
    expected_prompt_id: str = ""
    expected_content_sha256: str = ""
    expected_entry_cid: str = ""
    expected_content_cid: str = ""
    expected_source_revision: str = ""
    expected_intent_document_id: str = ""
    expected_formalization_artifact_id: str = ""
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    rollback: tuple[RollbackStep, ...] = ()
    verification: tuple[VerificationStep, ...] = ()
    # Explicit opt-in for tests that try to force side effects — always rejected.
    allow_network: bool = False
    allow_prompt_execute: bool = False
    allow_command_execution: bool = False
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
            raise PromptInvocationContextError("actor must be an ActorBinding")
        if not isinstance(self.audience, AudienceBinding):
            raise PromptInvocationContextError("audience must be an AudienceBinding")
        if not isinstance(self.environment, EnvironmentBinding):
            raise PromptInvocationContextError(
                "environment must be an EnvironmentBinding"
            )
        if not self.environment.environment_id:
            raise PromptInvocationContextError(
                "environment.environment_id is required runtime context"
            )
        if not isinstance(self.redacted_arguments, Mapping):
            raise PromptInvocationError("redacted_arguments must be a mapping")
        authority = self.dispatcher_authority
        if isinstance(authority, str):
            try:
                authority = DispatcherAuthority(authority)
            except ValueError as exc:
                raise PromptInvocationDispatcherError(
                    f"unsupported dispatcher_authority: {self.dispatcher_authority!r}"
                ) from exc
        if not isinstance(authority, DispatcherAuthority):
            raise PromptInvocationDispatcherError(
                "dispatcher_authority must be a DispatcherAuthority"
            )
        object.__setattr__(self, "dispatcher_authority", authority)
        object.__setattr__(
            self,
            "content_segments",
            _coerce_segments(self.content_segments, "content_segments"),
        )
        object.__setattr__(
            self, "tool_id", _optional_identifier(self.tool_id, "tool_id")
        )
        object.__setattr__(
            self, "tool_name", _optional_text(self.tool_name, "tool_name")
        )
        object.__setattr__(
            self, "tool_version", _optional_text(self.tool_version, "tool_version")
        )
        object.__setattr__(
            self, "server_id", _require_identifier(self.server_id, "server_id")
        )
        object.__setattr__(
            self, "server_name", _optional_text(self.server_name, "server_name")
        )
        object.__setattr__(
            self,
            "transport_peer",
            _optional_text(self.transport_peer, "transport_peer"),
        )
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
                raise PromptInvocationError(
                    "delegation entries must be DelegationLink"
                )
        if not isinstance(self.purpose, PurposeContext):
            raise PromptInvocationError("purpose must be a PurposeContext")
        if not isinstance(self.policy, PolicyRequirements):
            raise PromptInvocationError("policy must be PolicyRequirements")
        object.__setattr__(self, "nonce", _require_identifier(self.nonce, "nonce"))
        object.__setattr__(
            self, "created_at", _require_text(self.created_at, "created_at")
        )
        object.__setattr__(self, "deadline", _require_text(self.deadline, "deadline"))
        object.__setattr__(
            self,
            "trust_domain",
            _optional_identifier(self.trust_domain, "trust_domain"),
        )
        object.__setattr__(
            self, "trace_id", _optional_identifier(self.trace_id, "trace_id")
        )
        for name in (
            "intent_document_id",
            "formalization_artifact_id",
            "expected_prompt_id",
            "expected_content_sha256",
            "expected_entry_cid",
            "expected_content_cid",
            "expected_source_revision",
            "expected_intent_document_id",
            "expected_formalization_artifact_id",
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
        if (
            self.allow_network
            or self.allow_prompt_execute
            or self.allow_command_execution
            or self.allow_tool_invoke
        ):
            raise PromptInvocationSideEffectError(
                "network, prompt execution, tool invocation, and command "
                "execution are forbidden during prompt adaptation"
            )
        if not isinstance(self.attributes, Mapping):
            raise PromptInvocationError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))


class PromptInvocationAdapter:
    """Project a prompt record + runtime context into an invocation envelope.

    Interface: ``PromptInvocationAdapter@1``.

    Wraps the completed :class:`PromptIntentAdapter` source path for policy
    evaluation and Intent document production without executing prompt text.
    """

    def __init__(
        self,
        *,
        source_adapter: PromptIntentAdapter | None = None,
        policy: PromptSourcePolicy | None = None,
        max_argument_nodes: int = MAX_JSON_NODES,
        max_argument_depth: int = MAX_JSON_DEPTH,
        max_argument_chars: int = MAX_STRING_CHARS,
        max_segments: int = MAX_COLLECTION_ITEMS,
    ) -> None:
        if source_adapter is not None and not isinstance(
            source_adapter, PromptIntentAdapter
        ):
            raise TypeError("source_adapter must be a PromptIntentAdapter")
        if policy is not None and not isinstance(policy, PromptSourcePolicy):
            raise TypeError("policy must be a PromptSourcePolicy")
        for name, value in (
            ("max_argument_nodes", max_argument_nodes),
            ("max_argument_depth", max_argument_depth),
            ("max_argument_chars", max_argument_chars),
            ("max_segments", max_segments),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.max_argument_nodes = max_argument_nodes
        self.max_argument_depth = max_argument_depth
        self.max_argument_chars = max_argument_chars
        self.max_segments = max_segments
        self.source_adapter = source_adapter or PromptIntentAdapter(policy=policy)
        self.interface = PROMPT_INVOCATION_ADAPTER
        self.adapter_version = PROMPT_INVOCATION_ADAPTER_VERSION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adapt(
        self,
        record: PromptRecord,
        context: PromptInvocationContext,
        *,
        intent_document: IntentIRDocument | None = None,
        intent_document_id: str = "",
        formalization_artifact_id: str = "",
    ) -> InvocationIntentEnvelope:
        """Return a validated invocation envelope for the proposed prompt use."""

        return self.adapt_with_policy(
            record,
            context,
            intent_document=intent_document,
            intent_document_id=intent_document_id,
            formalization_artifact_id=formalization_artifact_id,
        )[0]

    def adapt_with_policy(
        self,
        record: PromptRecord,
        context: PromptInvocationContext,
        *,
        intent_document: IntentIRDocument | None = None,
        intent_document_id: str = "",
        formalization_artifact_id: str = "",
    ) -> tuple[InvocationIntentEnvelope, PromptSourcePolicyDecision]:
        """Adapt and also return the source-policy decision used."""

        self._reject_side_effects(context)
        if not isinstance(record, PromptRecord):
            raise TypeError("record must be a PromptRecord")
        if not isinstance(context, PromptInvocationContext):
            raise TypeError("context must be a PromptInvocationContext")

        decision = self.source_adapter.evaluate(record)
        if decision.allowed_use not in _ALLOWED_POLICY_USES:
            raise PromptInvocationPolicyError(decision)
        if decision.trust_decision is TrustDecision.QUARANTINED:
            raise PromptInvocationPolicyError(decision)

        if intent_document is None:
            try:
                intent_document, decision = self.source_adapter.adapt_with_policy(
                    record
                )
            except PromptPolicyError as exc:
                raise PromptInvocationPolicyError(exc.decision) from exc
        elif not isinstance(intent_document, IntentIRDocument):
            raise TypeError("intent_document must be an IntentIRDocument")

        bound_intent_id = (
            intent_document_id
            or context.intent_document_id
            or intent_document.document_id
        )
        bound_formalization_id = (
            formalization_artifact_id or context.formalization_artifact_id
        )

        self._validate_identity(
            record,
            context,
            intent_document=intent_document,
            intent_document_id=bound_intent_id,
            formalization_artifact_id=bound_formalization_id,
        )
        self._validate_dispatcher(context)
        self._validate_arguments(context.redacted_arguments)

        bound_segments = self._bind_segments(record, context)
        arguments = self._commit_arguments(context, bound_segments)
        tool = self._build_tool_binding(record, context)
        source = self._build_source_binding(
            record,
            context,
            intent_document_id=bound_intent_id,
            formalization_artifact_id=bound_formalization_id,
        )
        scope = self._build_scope(record, context, intent_document)
        unsupported, diagnostics, assumptions = self._collect_unsupported(
            record, context, bound_segments, intent_document
        )
        source_maps = self._source_maps(
            record, source.source_ref, bound_segments, intent_document
        )

        preconditions = list(context.preconditions)
        postconditions = list(context.postconditions)
        failure_modes = list(context.failure_modes)
        verification = list(context.verification)
        for statement in intent_document.statements:
            text = statement.normalized_text.strip()
            if not text:
                continue
            if statement.kind is StatementKind.PRECONDITION and text not in preconditions:
                preconditions.append(text)
            elif (
                statement.kind is StatementKind.POSTCONDITION
                and text not in postconditions
            ):
                postconditions.append(text)
            elif statement.kind is StatementKind.FAILURE and text not in failure_modes:
                failure_modes.append(text)
            elif statement.kind is StatementKind.VERIFICATION:
                step_id = f"verify:intent:{_safe_token(statement.statement_id)[:48]}"
                if not any(step.step_id == step_id for step in verification):
                    verification.append(
                        VerificationStep(
                            step_id=step_id,
                            description=text[:MAX_STRING_CHARS],
                            predicate=statement.statement_id,
                        )
                    )

        assumptions = assumptions + (
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "content-bound"),
                statement=(
                    "Prompt content_sha256 and entry identity were bound without "
                    "reinterpreting prompt text as trusted process instructions"
                ),
                source_ref=source.source_ref,
            ),
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "no-execution"),
                statement=(
                    "Adaptation performed no network I/O and did not execute "
                    "prompt text, shell commands, or tool invocations"
                ),
                source_ref=source.source_ref,
            ),
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "segments-role-only"),
                statement=(
                    "Content segment kinds distinguish data roles only and do "
                    "not invent permissions or capabilities"
                ),
                source_ref=source.source_ref,
            ),
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "prompt-untrusted"),
                statement=(
                    "Prompt body remains untrusted data; host-resolved "
                    "capabilities, audience, tool, and environment bindings "
                    "are authoritative"
                ),
                source_ref=source.source_ref,
            ),
        )

        diagnostics = (
            (
                InvocationDiagnostic(
                    code="invocation.prompt.adapted",
                    message=(
                        f"Adapted prompt {record.prompt_id!r} via "
                        f"{PROMPT_INVOCATION_ADAPTER} without execution"
                    ),
                    severity=DiagnosticSeverity.INFO,
                ),
            )
            + diagnostics
        )

        try:
            envelope = InvocationIntentEnvelope(
                envelope_id=context.envelope_id,
                invocation_kind=InvocationKind.PROMPT,
                source=source,
                tenant_id=context.tenant_id,
                actor=context.actor,
                audience=context.audience,
                tool=tool,
                arguments=arguments,
                scope=scope,
                purpose=context.purpose,
                environment=context.environment,
                preconditions=tuple(preconditions),
                postconditions=tuple(postconditions),
                failure_modes=tuple(failure_modes)
                or (
                    "prompt policy rejection",
                    "missing runtime context",
                    "segment identity mismatch",
                ),
                rollback=tuple(context.rollback)
                or (
                    RollbackStep(
                        step_id="rollback:prompt-noop",
                        description=(
                            "No side effects declared at adaptation time; "
                            "prompt execution remains blocked until authorization"
                        ),
                    ),
                ),
                verification=tuple(verification)
                or (
                    VerificationStep(
                        step_id="verify:prompt-content",
                        description="Pinned prompt content_sha256 must match record",
                        predicate=f"content_sha256:{record.content_sha256}",
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
                raise PromptInvocationSecretError(str(exc)) from exc
            if "depth" in message or "nodes" in message or "maximum" in message:
                raise PromptInvocationBoundError(str(exc)) from exc
            raise PromptInvocationError(str(exc)) from exc

        return validate_invocation_envelope(envelope), decision

    normalize = adapt
    normalize_with_policy = adapt_with_policy

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _reject_side_effects(self, context: PromptInvocationContext) -> None:
        if (
            context.allow_network
            or context.allow_prompt_execute
            or context.allow_command_execution
            or context.allow_tool_invoke
        ):
            raise PromptInvocationSideEffectError(
                "network, prompt execution, tool invocation, and command "
                "execution are forbidden during prompt adaptation"
            )
        attrs = context.attributes
        for forbidden in (
            "connect",
            "invoke",
            "dispatch",
            "endpoint_url",
            "call_tool",
            "transport_call",
            "execute",
            "shell",
            "subprocess",
            "popen",
            "os_system",
            "run_command",
            "prompt_execute",
            "model_call",
        ):
            if forbidden in attrs and attrs[forbidden]:
                raise PromptInvocationSideEffectError(
                    f"context attribute {forbidden!r} would trigger a side effect"
                )

    def _validate_identity(
        self,
        record: PromptRecord,
        context: PromptInvocationContext,
        *,
        intent_document: IntentIRDocument,
        intent_document_id: str,
        formalization_artifact_id: str,
    ) -> None:
        if (
            context.expected_prompt_id
            and context.expected_prompt_id != record.prompt_id
        ):
            raise PromptInvocationIdentityError(
                f"prompt_id mismatch: expected {context.expected_prompt_id!r}, "
                f"got {record.prompt_id!r}"
            )
        if (
            context.expected_content_sha256
            and context.expected_content_sha256 != record.content_sha256
        ):
            raise PromptInvocationIdentityError(
                "content_sha256 mismatch (identity drift or wrong revision)"
            )
        if (
            context.expected_entry_cid
            and context.expected_entry_cid != record.entry_cid
        ):
            raise PromptInvocationIdentityError(
                "entry_cid mismatch between context expectation and record"
            )
        if (
            context.expected_content_cid
            and context.expected_content_cid != record.content_cid
        ):
            raise PromptInvocationIdentityError(
                "content_cid mismatch between context expectation and record"
            )
        if (
            context.expected_source_revision
            and context.expected_source_revision != record.source_revision
        ):
            raise PromptInvocationIdentityError(
                "source_revision mismatch between context expectation and record"
            )
        if intent_document_id != intent_document.document_id:
            raise PromptInvocationIdentityError(
                "intent_document_id mismatch between supplied identity and "
                f"Intent IR document ({intent_document_id!r} != "
                f"{intent_document.document_id!r})"
            )
        if (
            context.expected_intent_document_id
            and context.expected_intent_document_id != intent_document_id
        ):
            raise PromptInvocationIdentityError(
                "expected_intent_document_id does not match Intent IR document"
            )
        if context.expected_formalization_artifact_id:
            if not formalization_artifact_id:
                raise PromptInvocationIdentityError(
                    "expected_formalization_artifact_id set but no formalization "
                    "artifact identity was supplied"
                )
            if (
                context.expected_formalization_artifact_id
                != formalization_artifact_id
            ):
                raise PromptInvocationIdentityError(
                    "formalization_artifact_id mismatch between context expectation "
                    "and supplied identity"
                )
        record.to_source_ref().validate()

    def _validate_dispatcher(self, context: PromptInvocationContext) -> None:
        if context.dispatcher_authority not in {
            DispatcherAuthority.HOST,
            DispatcherAuthority.RUNTIME,
        }:
            raise PromptInvocationDispatcherError(
                "dispatcher_authority must be host or runtime; "
                "caller-controlled dispatcher is rejected"
            )
        audience = context.audience
        if audience.kind.lower() in _CALLER_DISPATCHER_MARKERS:
            raise PromptInvocationDispatcherError(
                "caller-controlled dispatcher audience is rejected "
                f"(audience.kind={audience.kind!r})"
            )
        for label, candidate in (
            ("audience_id", audience.audience_id),
            ("deployment_id", audience.deployment_id),
            ("trust_domain", audience.trust_domain),
        ):
            if _is_caller_dispatcher_marker(candidate):
                raise PromptInvocationDispatcherError(
                    "caller-controlled dispatcher audience is rejected "
                    f"({label}={candidate!r})"
                )
        for key, value in audience.attributes.items():
            if isinstance(value, str) and _is_caller_dispatcher_marker(value):
                raise PromptInvocationDispatcherError(
                    "caller-controlled dispatcher audience is rejected "
                    f"(attributes.{key}={value!r})"
                )
            if key in {"authority", "controlled_by", "source"} and isinstance(
                value, str
            ):
                if value.lower() in _CALLER_DISPATCHER_MARKERS:
                    raise PromptInvocationDispatcherError(
                        "audience.attributes.authority must not be caller-controlled"
                    )
        if audience.attributes.get("caller_controlled") is True:
            raise PromptInvocationDispatcherError(
                "caller_controlled audience attribute is forbidden"
            )

    def _validate_arguments(self, arguments: Mapping[str, Any]) -> None:
        self._bound_json(
            arguments,
            name="redacted_arguments",
            max_depth=self.max_argument_depth,
            max_nodes=self.max_argument_nodes,
            max_chars=self.max_argument_chars,
        )
        self._reject_dynamic_arguments(arguments, path="/redacted_arguments")

    def _reject_dynamic_arguments(self, value: Any, *, path: str) -> None:
        if callable(value) and not isinstance(value, type):
            raise PromptInvocationBoundError(
                f"{path}: callable/dynamic values are rejected in arguments"
            )
        if isinstance(value, Mapping):
            if any(key in value for key in ("__call__", "__class__", "__import__")):
                raise PromptInvocationBoundError(
                    f"{path}: dynamic/introspection argument keys are rejected"
                )
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PromptInvocationBoundError(
                        f"{path}: argument keys must be strings"
                    )
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
            raise PromptInvocationBoundError(
                f"{name} exceeds maximum of {max_nodes} JSON nodes"
            )
        if depth > max_depth:
            raise PromptInvocationBoundError(
                f"{name} exceeds maximum JSON depth of {max_depth}"
            )
        if isinstance(value, str) and len(value) > max_chars:
            raise PromptInvocationBoundError(
                f"{name} string exceeds maximum length of {max_chars}"
            )
        if isinstance(value, Mapping):
            if len(value) > MAX_COLLECTION_ITEMS:
                raise PromptInvocationBoundError(
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
                raise PromptInvocationBoundError(
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

    # ------------------------------------------------------------------
    # Segment binding
    # ------------------------------------------------------------------

    def _bind_segments(
        self, record: PromptRecord, context: PromptInvocationContext
    ) -> tuple[BoundPromptSegment, ...]:
        text = record.text
        text_len = len(text)
        declared = list(context.content_segments)
        if len(declared) > self.max_segments:
            raise PromptInvocationBoundError(
                f"content_segments exceeds maximum of {self.max_segments}"
            )

        if not declared:
            # Default: entire body is user instruction (role classification only).
            declared = [
                PromptContentSegment(
                    segment_id="seg:user-instruction:full",
                    kind=PromptSegmentKind.USER_INSTRUCTION,
                    start_char=0,
                    end_char=text_len,
                    label="default-user-instruction",
                )
            ]

        seen_ids: set[str] = set()
        bound: list[BoundPromptSegment] = []
        for segment in declared:
            if segment.segment_id in seen_ids:
                raise PromptInvocationSegmentError(
                    f"duplicate segment_id: {segment.segment_id}"
                )
            seen_ids.add(segment.segment_id)
            if segment.end_char > text_len:
                raise PromptInvocationSegmentError(
                    f"segment {segment.segment_id} end_char {segment.end_char} "
                    f"exceeds prompt text length {text_len}"
                )
            if segment.start_char > text_len:
                raise PromptInvocationSegmentError(
                    f"segment {segment.segment_id} start_char out of range"
                )
            span_text = text[segment.start_char : segment.end_char]
            content_sha = hashlib.sha256(span_text.encode("utf-8")).hexdigest()
            force_redact = segment.redact or _contains_inline_secret(span_text)
            if force_redact and not segment.redact:
                # Host did not mark redact, but raw secret material is present —
                # fail closed rather than silently shipping secrets.
                raise PromptInvocationSecretError(
                    f"segment {segment.segment_id} contains raw secret material; "
                    "mark redact=True and supply secret_refs instead"
                )
            redacted_text = _REDACTED_TOKEN if force_redact else span_text
            if not force_redact and len(redacted_text) > self.max_argument_chars:
                raise PromptInvocationBoundError(
                    f"segment {segment.segment_id} text exceeds maximum length of "
                    f"{self.max_argument_chars}"
                )
            attrs = dict(segment.attributes)
            attrs["kind_role"] = segment.kind.value
            attrs["trusted"] = False
            attrs["elevates_capability"] = False
            bound.append(
                BoundPromptSegment(
                    segment_id=segment.segment_id,
                    kind=segment.kind,
                    start_char=segment.start_char,
                    end_char=segment.end_char,
                    content_sha256=content_sha,
                    redacted=force_redact,
                    redacted_text=redacted_text,
                    label=segment.label,
                    attributes=attrs,
                )
            )
        return tuple(bound)

    def _commit_arguments(
        self,
        context: PromptInvocationContext,
        bound_segments: tuple[BoundPromptSegment, ...],
    ) -> ArgumentCommitment:
        # Fold segment digests into redacted arguments without elevating roles.
        payload = dict(context.redacted_arguments)
        segment_views = [
            {
                "content_sha256": seg.content_sha256,
                "end_char": seg.end_char,
                "kind": seg.kind.value,
                "label": seg.label,
                "redacted": seg.redacted,
                "redacted_text": seg.redacted_text,
                "segment_id": seg.segment_id,
                "start_char": seg.start_char,
            }
            for seg in bound_segments
        ]
        # Only inject when caller has not already supplied the structured view.
        if "content_segments" not in payload:
            payload["content_segments"] = segment_views
        else:
            # Caller-supplied segment views must match host-bound digests.
            supplied = payload["content_segments"]
            if not isinstance(supplied, Sequence) or isinstance(
                supplied, (str, bytes, bytearray)
            ):
                raise PromptInvocationSegmentError(
                    "redacted_arguments.content_segments must be a sequence"
                )
            if len(supplied) != len(bound_segments):
                raise PromptInvocationSegmentError(
                    "redacted_arguments.content_segments length does not match "
                    "host content_segments"
                )
            for index, (item, bound) in enumerate(zip(supplied, bound_segments)):
                if not isinstance(item, Mapping):
                    raise PromptInvocationSegmentError(
                        f"content_segments[{index}] must be a mapping"
                    )
                if item.get("content_sha256") and item.get(
                    "content_sha256"
                ) != bound.content_sha256:
                    raise PromptInvocationIdentityError(
                        f"content_segments[{index}] content_sha256 mismatch"
                    )
                if item.get("kind") and item.get("kind") != bound.kind.value:
                    raise PromptInvocationSegmentError(
                        f"content_segments[{index}] kind mismatch with host segment"
                    )
                if bound.redacted and item.get("redacted_text") not in (
                    None,
                    _REDACTED_TOKEN,
                    "[REDACTED]",
                    "<REDACTED>",
                    "REDACTED",
                ):
                    # Sensitive spans must stay redacted in argument view.
                    if _contains_inline_secret(str(item.get("redacted_text", ""))):
                        raise PromptInvocationSecretError(
                            f"content_segments[{index}] still carries raw secret text"
                        )
        self._validate_arguments(payload)
        try:
            return ArgumentCommitment.from_redacted(
                payload,
                secret_refs=context.secret_refs,
                attributes={
                    "segment_count": len(bound_segments),
                    "segment_kinds": sorted(
                        {seg.kind.value for seg in bound_segments}
                    ),
                },
            )
        except InvocationEnvelopeValidationError as exc:
            message = str(exc).lower()
            if "raw secret" in message or "redacted token" in message:
                raise PromptInvocationSecretError(str(exc)) from exc
            if "depth" in message or "nodes" in message or "maximum" in message:
                raise PromptInvocationBoundError(str(exc)) from exc
            raise PromptInvocationError(str(exc)) from exc

    def _build_tool_binding(
        self, record: PromptRecord, context: PromptInvocationContext
    ) -> ToolBinding:
        tool_id = context.tool_id or _prompt_tool_id(record.prompt_id)
        tool_name = context.tool_name or record.title or "prompt"
        attributes: dict[str, Any] = {
            "adapter": PROMPT_INVOCATION_ADAPTER,
            "adapter_version": PROMPT_INVOCATION_ADAPTER_VERSION,
            "entry_cid": record.entry_cid,
            "content_cid": record.content_cid,
            "prompt_id": record.prompt_id,
            "language": record.language,
            "source_revision": record.source_revision,
        }
        return ToolBinding(
            tool_id=tool_id,
            tool_name=tool_name,
            tool_version=context.tool_version or record.source_revision,
            server_id=context.server_id,
            server_name=context.server_name or "prompt",
            transport_peer=context.transport_peer,
            attributes=attributes,
        )

    def _build_source_binding(
        self,
        record: PromptRecord,
        context: PromptInvocationContext,
        *,
        intent_document_id: str,
        formalization_artifact_id: str,
    ) -> SourceBinding:
        source_ref = record.to_source_ref()
        source_id = record.source_id or record.prompt_id
        if source_id and not _ID_RE.fullmatch(source_id):
            source_id = (
                f"source:{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:24]}"
            )
        return SourceBinding(
            kind=InvocationKind.PROMPT,
            source_ref=source_ref.ref_id,
            source_id=source_id if _ID_RE.fullmatch(source_id or "") else "",
            source_revision=record.source_revision,
            content_sha256=record.content_sha256,
            content_cid=record.content_cid,
            intent_document_id=intent_document_id,
            formalization_artifact_id=formalization_artifact_id,
            attributes={
                "prompt_id": record.prompt_id,
                "entry_cid": record.entry_cid,
                "title": record.title,
                "language": record.language,
            },
        )

    def _build_scope(
        self,
        record: PromptRecord,
        context: PromptInvocationContext,
        intent_document: IntentIRDocument,
    ) -> InvocationScope:
        known = set(context.known_capabilities)
        capability_entries: list[ScopeEntry] = []
        for claim in context.resolved_capabilities:
            if claim.value not in known:
                raise PromptInvocationCapabilityError(
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

        # Prompt never invents capabilities from text. Action is a request label.
        action_entries: list[ScopeEntry] = [
            ScopeEntry(
                entry_id=f"scope:action:{_safe_token(record.prompt_id)[:48]}",
                kind=ScopeKind.ACTION,
                value=record.title or "prompt-request",
                description="Host-bound free-form prompt request (untrusted body)",
                attributes={
                    "grounding": "prompt-record",
                    "prompt_id": record.prompt_id,
                    "trusted": False,
                },
            )
        ]
        for index, action in enumerate(intent_document.actions):
            entry_id = f"scope:action:intent:{_safe_token(action.action_id)[:40]}"
            if not _ID_RE.fullmatch(entry_id):
                entry_id = f"scope:action:intent:{index}:{_hash_token(action.action_id)}"
            value = f"{action.verb}".strip() or action.action_id
            action_entries.append(
                ScopeEntry(
                    entry_id=entry_id,
                    kind=ScopeKind.ACTION,
                    value=value[:MAX_STRING_CHARS],
                    description=f"{action.actor} {action.verb}".strip(),
                    attributes={
                        "action_id": action.action_id,
                        "actor": action.actor,
                        "verb": action.verb,
                        "grounding": "intent",
                        "trusted": False,
                    },
                )
            )

        return InvocationScope(
            actions=tuple(action_entries),
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

    def _collect_unsupported(
        self,
        record: PromptRecord,
        context: PromptInvocationContext,
        bound_segments: tuple[BoundPromptSegment, ...],
        intent_document: IntentIRDocument,
    ) -> tuple[
        tuple[UnsupportedField, ...],
        tuple[InvocationDiagnostic, ...],
        tuple[InvocationAssumption, ...],
    ]:
        unsupported: list[UnsupportedField] = []
        diagnostics: list[InvocationDiagnostic] = []
        assumptions: list[InvocationAssumption] = []
        source_ref = record.to_source_ref().ref_id
        lowered = record.text.casefold()

        for hint in sorted(_PROMPT_AUTHORITY_HINTS):
            if hint in lowered:
                field_path = f"/prompt/text/claim/{_safe_token(hint)}"
                unsupported.append(
                    UnsupportedField(
                        field_path=field_path,
                        reason=(
                            "prompt text may claim authority; host-resolved "
                            "bindings remain authoritative (no permission invented)"
                        ),
                        source_ref=source_ref,
                        raw_kind="prompt_claim",
                        attributes={"hint": hint, "trusted": False},
                    )
                )

        # Non-instruction segment kinds stay visible as untrusted data roles.
        for seg in bound_segments:
            if seg.kind is PromptSegmentKind.USER_INSTRUCTION:
                continue
            unsupported.append(
                UnsupportedField(
                    field_path=f"/content_segments/{seg.segment_id}",
                    reason=(
                        f"segment kind {seg.kind.value!r} is untrusted data and "
                        "does not authorize capabilities, tools, or audience"
                    ),
                    source_ref=source_ref,
                    raw_kind=seg.kind.value,
                    attributes={
                        "content_sha256": seg.content_sha256,
                        "end_char": seg.end_char,
                        "start_char": seg.start_char,
                        "trusted": False,
                        "redacted": seg.redacted,
                    },
                )
            )

        # Metadata JSON keys are never elevated.
        if record.metadata_json and record.metadata_json not in ("{}", ""):
            unsupported.append(
                UnsupportedField(
                    field_path="/prompt/metadata_json",
                    reason="prompt metadata is untrusted packaging, not elevated",
                    source_ref=source_ref,
                    raw_kind="metadata",
                    attributes={"trusted": False},
                )
            )

        if unsupported:
            diagnostics.append(
                InvocationDiagnostic(
                    code="invocation.prompt.unsupported_retained",
                    message=(
                        f"Retained {len(unsupported)} unsupported/ambiguous "
                        "prompt field(s) without elevating them"
                    ),
                    severity=DiagnosticSeverity.INFO,
                )
            )
            assumptions.append(
                InvocationAssumption(
                    assumption_id=_stable_assumption_id(
                        record, "unsupported-retained"
                    ),
                    statement=(
                        "Unsupported and ambiguous prompt constructs were retained "
                        "as diagnostics and unsupported fields"
                    ),
                    source_ref=source_ref,
                )
            )

        for statement in intent_document.statements:
            if statement.kind is StatementKind.ASSUMPTION:
                assumptions.append(
                    InvocationAssumption(
                        assumption_id=(
                            f"assume:intent:{_hash_token(statement.statement_id)}"
                        ),
                        statement=statement.normalized_text[:MAX_STRING_CHARS],
                        source_ref=source_ref,
                        attributes={"statement_id": statement.statement_id},
                    )
                )

        # Segment role inventory diagnostic.
        kind_counts: dict[str, int] = {}
        for seg in bound_segments:
            kind_counts[seg.kind.value] = kind_counts.get(seg.kind.value, 0) + 1
        diagnostics.append(
            InvocationDiagnostic(
                code="invocation.prompt.segments_bound",
                message=(
                    "Bound "
                    + ", ".join(
                        f"{count} {kind}" for kind, count in sorted(kind_counts.items())
                    )
                    + " segment(s) with exact source spans"
                ),
                severity=DiagnosticSeverity.INFO,
                field_path="/content_segments",
            )
        )
        return tuple(unsupported), tuple(diagnostics), tuple(assumptions)

    def _source_maps(
        self,
        record: PromptRecord,
        source_ref: str,
        bound_segments: tuple[BoundPromptSegment, ...],
        intent_document: IntentIRDocument,
    ) -> tuple[SourceMapEntry, ...]:
        maps: list[SourceMapEntry] = [
            SourceMapEntry(
                map_id="map:prompt-content-sha256",
                field_path="/source/content_sha256",
                source_ref=source_ref,
                start_char=0,
                end_char=min(len(record.text), MAX_STRING_CHARS),
                note="prompt body content identity",
            ),
            SourceMapEntry(
                map_id="map:prompt-entry-cid",
                field_path="/source/attributes/entry_cid",
                source_ref=source_ref,
                note=f"entry_cid {record.entry_cid}",
            ),
            SourceMapEntry(
                map_id="map:prompt-intent",
                field_path="/source/intent_document_id",
                source_ref=source_ref,
                note=f"intent document {intent_document.document_id}",
            ),
        ]
        if record.title:
            maps.append(
                SourceMapEntry(
                    map_id="map:prompt-title",
                    field_path="/tool/tool_name",
                    source_ref=source_ref,
                    start_char=0,
                    end_char=min(len(record.title), MAX_STRING_CHARS),
                    note="prompt title bound as tool_name when host tool_name empty",
                )
            )
        for index, seg in enumerate(bound_segments):
            maps.append(
                SourceMapEntry(
                    map_id=f"map:segment:{_safe_token(seg.segment_id)[:40]}",
                    field_path=f"/arguments/redacted_arguments/content_segments/{index}",
                    source_ref=source_ref,
                    start_char=seg.start_char,
                    end_char=seg.end_char,
                    note=(
                        f"segment kind={seg.kind.value} "
                        f"sha256={seg.content_sha256[:16]} "
                        f"redacted={seg.redacted}"
                    ),
                    attributes={
                        "kind": seg.kind.value,
                        "content_sha256": seg.content_sha256,
                        "redacted": seg.redacted,
                        "segment_id": seg.segment_id,
                    },
                )
            )
        return tuple(maps)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptInvocationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise PromptInvocationError(f"{name} must not have surrounding whitespace")
    if len(value) > MAX_STRING_CHARS:
        raise PromptInvocationBoundError(f"{name} exceeds maximum string length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, name)


def _require_identifier(value: Any, name: str) -> str:
    text = _require_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise PromptInvocationError(f"{name} is not a stable identifier")
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
        raise PromptInvocationError(f"{name} must be a sequence of strings")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise PromptInvocationBoundError(f"{name} exceeds maximum collection size")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise PromptInvocationError(f"{name} entries must be non-empty strings")
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
            raise PromptInvocationError(
                f"{name} contains an invalid identifier: {item!r}"
            )
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
        raise PromptInvocationError(f"{name} must be a sequence of strings")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise PromptInvocationBoundError(f"{name} exceeds maximum collection size")
    if ordered:
        result: list[str] = []
        for item in items:
            if not isinstance(item, str) or not item.strip() or item != item.strip():
                raise PromptInvocationError(
                    f"{name} entries must be non-empty strings"
                )
            if len(item) > MAX_STRING_CHARS:
                raise PromptInvocationBoundError(
                    f"{name} entry exceeds maximum length"
                )
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
        raise PromptInvocationError(
            f"{name} must be a sequence of ResolvedScopeClaim"
        )
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise PromptInvocationBoundError(f"{name} exceeds maximum collection size")
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
            raise PromptInvocationError(
                f"{name} entries must be ResolvedScopeClaim"
            )
        if item.entry_id in seen:
            raise PromptInvocationError(
                f"duplicate scope claim entry_id: {item.entry_id}"
            )
        seen.add(item.entry_id)
        result.append(item)
    return tuple(result)


def _coerce_segments(
    values: Sequence[PromptContentSegment] | Iterable[PromptContentSegment] | None,
    name: str,
) -> tuple[PromptContentSegment, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise PromptInvocationSegmentError(
            f"{name} must be a sequence of PromptContentSegment"
        )
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise PromptInvocationBoundError(f"{name} exceeds maximum collection size")
    result: list[PromptContentSegment] = []
    for item in items:
        if isinstance(item, Mapping):
            item = PromptContentSegment(
                segment_id=item["segment_id"],
                kind=item["kind"],
                start_char=item["start_char"],
                end_char=item["end_char"],
                redact=bool(item.get("redact", False)),
                label=item.get("label", ""),
                attributes=item.get("attributes") or {},
            )
        if not isinstance(item, PromptContentSegment):
            raise PromptInvocationSegmentError(
                f"{name} entries must be PromptContentSegment"
            )
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


def _prompt_tool_id(prompt_id: str) -> str:
    if _ID_RE.fullmatch(prompt_id):
        candidate = f"tool:{prompt_id}"
        if _ID_RE.fullmatch(candidate):
            return candidate
    digest = hashlib.sha256(prompt_id.encode("utf-8")).hexdigest()[:24]
    return f"tool:prompt-{digest}"


def _safe_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    if not cleaned:
        cleaned = "x"
    return cleaned[:64]


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


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


def _stable_assumption_id(record: PromptRecord, label: str) -> str:
    material = f"{record.prompt_id}|{record.content_sha256}|{label}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"assume:prompt-{label}-{digest}"


def _contains_inline_secret(text: str) -> bool:
    if not text:
        return False
    for pattern in _SECRET_INLINE_PATTERNS:
        if pattern.search(text):
            return True
    return False


__all__ = [
    "PROMPT_INVOCATION_ADAPTER",
    "PROMPT_INVOCATION_ADAPTER_VERSION",
    "PROMPT_SEGMENT_DIGEST_DOMAIN",
    "BoundPromptSegment",
    "DispatcherAuthority",
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
    "ResolvedScopeClaim",
]
