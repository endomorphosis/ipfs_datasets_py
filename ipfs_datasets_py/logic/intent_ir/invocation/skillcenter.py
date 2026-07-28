"""Adapt SkillCenter intent into invocation envelopes.

Interface: ``SkillCenterInvocationAdapter@1``

A pinned SkillCenter skill record plus caller/runtime context is bound to an
immutable
:class:`~ipfs_datasets_py.logic.intent_ir.invocation.model.InvocationIntentEnvelope`
**before** Legal/Security evaluation and **before** any skill or command
execution.

Non-goals (fail-closed invariants):
- Never executes ``skill_md`` / ``library_md`` content, shell, or tool calls.
- Never fetches mutable dataset revisions (``main`` / ``latest`` / etc.).
- Never elevates skill text claims to trusted capabilities or audience.
- Never stores raw secrets; arguments must already be redacted views.
- Never accepts a caller-controlled dispatcher identity (confused-deputy guard).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Iterable

from ..normalize.skill import (
    INTENT_NORMALIZER_VERSION,
    NormalizationSeverity,
    SkillCenterIntentNormalizer,
    SkillNormalizationError,
    SkillNormalizationPolicyError,
    SkillNormalizationResult,
)
from ..schema import (
    IntentAction,
    IntentIRDocument,
    StatementKind,
)
from ..source_adapters.policy import (
    AllowedUseDecision,
    SkillSourcePolicy,
    SkillSourcePolicyDecision,
    TrustDecision,
)
from ..source_adapters.skillcenter import SkillCenterSkillRecord
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


SKILLCENTER_INVOCATION_ADAPTER: Final = "SkillCenterInvocationAdapter@1"
SKILLCENTER_INVOCATION_ADAPTER_VERSION: Final = "skillcenter-invocation-adapter/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_MUTABLE_REVISION_NAMES = frozenset(
    {
        "head",
        "latest",
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
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
        "skill",
    }
)
_ALLOWED_POLICY_USES: Final = frozenset(
    {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    }
)
# Skill body keys that may claim authority but must never elevate into scope.
_SKILL_AUTHORITY_SECTION_HINTS: Final = frozenset(
    {
        "capabilities",
        "capability",
        "audience",
        "dispatcher",
        "environment",
        "trust_domain",
        "network",
        "filesystem",
        "subprocess",
        "secrets",
        "secret",
    }
)


class SkillCenterInvocationError(ValueError):
    """Base error for SkillCenter → invocation envelope adaptation failures."""


class SkillCenterInvocationIdentityError(SkillCenterInvocationError):
    """Raised when snapshot/record/content/Intent/formalization identities mismatch."""


class SkillCenterInvocationBoundError(SkillCenterInvocationError):
    """Raised when arguments or nested payloads exceed hard bounds."""


class SkillCenterInvocationSecretError(SkillCenterInvocationError):
    """Raised when raw secrets would be serialized into the envelope."""


class SkillCenterInvocationDispatcherError(SkillCenterInvocationError):
    """Raised when dispatcher/audience identity is caller-controlled."""


class SkillCenterInvocationCapabilityError(SkillCenterInvocationError):
    """Raised when a requested capability is not in the host allowlist."""


class SkillCenterInvocationSideEffectError(SkillCenterInvocationError):
    """Raised when adaptation would execute skill content or open network I/O."""


class SkillCenterInvocationContextError(SkillCenterInvocationError):
    """Raised when required runtime context is missing or incomplete."""


class SkillCenterInvocationMutableError(SkillCenterInvocationError):
    """Raised when a mutable snapshot revision is supplied."""


class SkillCenterInvocationPolicyError(SkillCenterInvocationError):
    """Raised when the SkillCenter source policy rejects the record."""

    def __init__(self, decision: SkillSourcePolicyDecision) -> None:
        self.decision = decision
        super().__init__(
            "SkillCenter record is not eligible for invocation adaptation: "
            f"{decision.allowed_use.value}"
        )


class DispatcherAuthority(str, Enum):
    """Who is authoritative for audience/dispatcher binding.

    Only host/runtime authorities are accepted. Caller, skill text, and
    annotation claims are rejected (confused-deputy prevention).
    """

    HOST = "host"
    RUNTIME = "runtime"


class ResolvedScopeClaim:
    """One host-resolved scope claim (not derived from skill prose alone)."""

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
            raise SkillCenterInvocationError(
                f"scope claim entry_id is invalid: {entry_id!r}"
            )
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise SkillCenterInvocationError(
                f"scope claim value is invalid for {entry_id}"
            )
        if len(value) > MAX_STRING_CHARS:
            raise SkillCenterInvocationBoundError(
                f"scope claim value for {entry_id} exceeds maximum string length"
            )
        if description is None:
            description = ""
        if not isinstance(description, str) or (
            description and description != description.strip()
        ):
            raise SkillCenterInvocationError(
                f"scope claim description is invalid for {entry_id}"
            )
        if len(description) > MAX_STRING_CHARS:
            raise SkillCenterInvocationBoundError(
                f"scope claim description for {entry_id} exceeds maximum string length"
            )
        self.entry_id = entry_id
        self.value = value
        self.description = description
        self.attributes = dict(attributes or {})


@dataclass(frozen=True, slots=True)
class SkillCenterInvocationContext:
    """Host- and caller-supplied runtime context for one proposed skill invocation.

    Identity fields (snapshot pins, audience, environment, resolved
    capabilities/effects) must be supplied by the host/runtime observer.
    Skill markdown must not author those fields.
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
    expected_skill_id: str = ""
    expected_content_sha256: str = ""
    expected_entry_cid: str = ""
    expected_content_cid: str = ""
    expected_dataset_id: str = ""
    expected_dataset_revision: str = ""
    expected_repository_file: str = ""
    expected_bundle_sha256: str = ""
    expected_intent_document_id: str = ""
    expected_formalization_artifact_id: str = ""
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    rollback: tuple[RollbackStep, ...] = ()
    verification: tuple[VerificationStep, ...] = ()
    # Explicit opt-in for tests that try to force side effects — always rejected.
    allow_network: bool = False
    allow_skill_execute: bool = False
    allow_command_execution: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "envelope_id", _require_identifier(self.envelope_id, "envelope_id")
        )
        object.__setattr__(
            self, "tenant_id", _require_identifier(self.tenant_id, "tenant_id")
        )
        if not isinstance(self.actor, ActorBinding):
            raise SkillCenterInvocationContextError("actor must be an ActorBinding")
        if not isinstance(self.audience, AudienceBinding):
            raise SkillCenterInvocationContextError(
                "audience must be an AudienceBinding"
            )
        if not isinstance(self.environment, EnvironmentBinding):
            raise SkillCenterInvocationContextError(
                "environment must be an EnvironmentBinding"
            )
        if not self.environment.environment_id:
            raise SkillCenterInvocationContextError(
                "environment.environment_id is required runtime context"
            )
        if not isinstance(self.redacted_arguments, Mapping):
            raise SkillCenterInvocationError("redacted_arguments must be a mapping")
        authority = self.dispatcher_authority
        if isinstance(authority, str):
            try:
                authority = DispatcherAuthority(authority)
            except ValueError as exc:
                raise SkillCenterInvocationDispatcherError(
                    f"unsupported dispatcher_authority: {self.dispatcher_authority!r}"
                ) from exc
        if not isinstance(authority, DispatcherAuthority):
            raise SkillCenterInvocationDispatcherError(
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
                raise SkillCenterInvocationError(
                    "delegation entries must be DelegationLink"
                )
        if not isinstance(self.purpose, PurposeContext):
            raise SkillCenterInvocationError("purpose must be a PurposeContext")
        if not isinstance(self.policy, PolicyRequirements):
            raise SkillCenterInvocationError("policy must be PolicyRequirements")
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
            "expected_skill_id",
            "expected_content_sha256",
            "expected_entry_cid",
            "expected_content_cid",
            "expected_dataset_id",
            "expected_dataset_revision",
            "expected_repository_file",
            "expected_bundle_sha256",
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
            or self.allow_skill_execute
            or self.allow_command_execution
        ):
            raise SkillCenterInvocationSideEffectError(
                "network, skill execution, and command execution are forbidden "
                "during SkillCenter adaptation"
            )
        if not isinstance(self.attributes, Mapping):
            raise SkillCenterInvocationError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))


class SkillCenterInvocationAdapter:
    """Project a SkillCenter record + runtime context into an invocation envelope.

    Interface: ``SkillCenterInvocationAdapter@1``.

    Wraps the completed SkillCenter source policy and Intent normalizer without
    fetching mutable revisions or executing skill content.
    """

    def __init__(
        self,
        *,
        normalizer: SkillCenterIntentNormalizer | None = None,
        policy: SkillSourcePolicy | None = None,
        max_argument_nodes: int = MAX_JSON_NODES,
        max_argument_depth: int = MAX_JSON_DEPTH,
        max_argument_chars: int = MAX_STRING_CHARS,
    ) -> None:
        if normalizer is not None and not isinstance(
            normalizer, SkillCenterIntentNormalizer
        ):
            raise TypeError("normalizer must be a SkillCenterIntentNormalizer")
        if policy is not None and not isinstance(policy, SkillSourcePolicy):
            raise TypeError("policy must be a SkillSourcePolicy")
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
        self.policy = policy or SkillSourcePolicy()
        self.normalizer = normalizer or SkillCenterIntentNormalizer(policy=self.policy)
        self.interface = SKILLCENTER_INVOCATION_ADAPTER
        self.adapter_version = SKILLCENTER_INVOCATION_ADAPTER_VERSION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adapt(
        self,
        record: SkillCenterSkillRecord,
        context: SkillCenterInvocationContext,
        *,
        intent_document: IntentIRDocument | None = None,
        intent_document_id: str = "",
        formalization_artifact_id: str = "",
    ) -> InvocationIntentEnvelope:
        """Return a validated invocation envelope for the proposed skill use."""

        return self.adapt_with_policy(
            record,
            context,
            intent_document=intent_document,
            intent_document_id=intent_document_id,
            formalization_artifact_id=formalization_artifact_id,
        )[0]

    def adapt_with_policy(
        self,
        record: SkillCenterSkillRecord,
        context: SkillCenterInvocationContext,
        *,
        intent_document: IntentIRDocument | None = None,
        intent_document_id: str = "",
        formalization_artifact_id: str = "",
    ) -> tuple[InvocationIntentEnvelope, SkillSourcePolicyDecision]:
        """Adapt and also return the source-policy decision used."""

        self._reject_side_effects(context)
        if not isinstance(record, SkillCenterSkillRecord):
            raise TypeError("record must be a SkillCenterSkillRecord")
        if not isinstance(context, SkillCenterInvocationContext):
            raise TypeError("context must be a SkillCenterInvocationContext")

        self._reject_mutable_revision(record)
        decision = self.policy.evaluate(record)
        if decision.allowed_use not in _ALLOWED_POLICY_USES:
            raise SkillCenterInvocationPolicyError(decision)
        if decision.trust_decision is TrustDecision.QUARANTINED:
            raise SkillCenterInvocationPolicyError(decision)

        normalization: SkillNormalizationResult | None = None
        if intent_document is None:
            try:
                normalization = self.normalizer.normalize_with_diagnostics(record)
            except SkillNormalizationPolicyError as exc:
                raise SkillCenterInvocationPolicyError(exc.decision) from exc
            except SkillNormalizationError as exc:
                raise SkillCenterInvocationError(str(exc)) from exc
            intent_document = normalization.document
        elif not isinstance(intent_document, IntentIRDocument):
            raise TypeError("intent_document must be an IntentIRDocument")

        self._validate_identity(
            record,
            context,
            intent_document=intent_document,
            intent_document_id=intent_document_id
            or context.intent_document_id
            or intent_document.document_id,
            formalization_artifact_id=formalization_artifact_id
            or context.formalization_artifact_id,
        )
        self._validate_dispatcher(context)
        self._validate_arguments(context.redacted_arguments)
        arguments = self._commit_arguments(context)
        tool = self._build_tool_binding(record, context)
        source = self._build_source_binding(
            record,
            context,
            intent_document=intent_document,
            intent_document_id=intent_document_id
            or context.intent_document_id
            or intent_document.document_id,
            formalization_artifact_id=formalization_artifact_id
            or context.formalization_artifact_id,
        )
        scope, intent_source_maps = self._build_scope(record, context, intent_document)
        unsupported, diagnostics, assumptions = self._collect_unsupported(
            record, intent_document, normalization
        )
        source_maps = self._source_maps(record, source.source_ref, intent_document) + (
            intent_source_maps
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
                assumption_id=_stable_assumption_id(record, "pinned-revision"),
                statement=(
                    "SkillCenter snapshot revision is immutable and was not "
                    "re-fetched during adaptation"
                ),
                source_ref=source.source_ref,
            ),
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "no-execution"),
                statement=(
                    "Adaptation performed no network I/O and did not execute "
                    "skill markdown, shell commands, or tool invocations"
                ),
                source_ref=source.source_ref,
            ),
            InvocationAssumption(
                assumption_id=_stable_assumption_id(record, "skill-untrusted"),
                statement=(
                    "Skill markdown remains untrusted data; host-resolved "
                    "capabilities and audience bindings are authoritative"
                ),
                source_ref=source.source_ref,
            ),
        )

        diagnostics = (
            (
                InvocationDiagnostic(
                    code="invocation.skillcenter.adapted",
                    message=(
                        f"Adapted SkillCenter skill {record.skill_id!r} via "
                        f"{SKILLCENTER_INVOCATION_ADAPTER} without execution"
                    ),
                    severity=DiagnosticSeverity.INFO,
                ),
            )
            + diagnostics
        )

        try:
            envelope = InvocationIntentEnvelope(
                envelope_id=context.envelope_id,
                invocation_kind=InvocationKind.SKILLCENTER,
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
                or ("skill validation failure", "missing runtime context"),
                rollback=tuple(context.rollback)
                or (
                    RollbackStep(
                        step_id="rollback:skillcenter-noop",
                        description=(
                            "No side effects declared at adaptation time; "
                            "skill execution remains blocked until authorization"
                        ),
                    ),
                ),
                verification=tuple(verification)
                or (
                    VerificationStep(
                        step_id="verify:skillcenter-content",
                        description="Pinned skill content_sha256 must match record",
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
                raise SkillCenterInvocationSecretError(str(exc)) from exc
            if "depth" in message or "nodes" in message or "maximum" in message:
                raise SkillCenterInvocationBoundError(str(exc)) from exc
            raise SkillCenterInvocationError(str(exc)) from exc

        return validate_invocation_envelope(envelope), decision

    normalize = adapt
    normalize_with_policy = adapt_with_policy

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _reject_side_effects(self, context: SkillCenterInvocationContext) -> None:
        if (
            context.allow_network
            or context.allow_skill_execute
            or context.allow_command_execution
        ):
            raise SkillCenterInvocationSideEffectError(
                "network, skill execution, and command execution are forbidden "
                "during SkillCenter adaptation"
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
            "skill_execute",
        ):
            if forbidden in attrs and attrs[forbidden]:
                raise SkillCenterInvocationSideEffectError(
                    f"context attribute {forbidden!r} would trigger a side effect"
                )

    def _reject_mutable_revision(self, record: SkillCenterSkillRecord) -> None:
        revision = (record.dataset_revision or "").strip()
        if not revision:
            raise SkillCenterInvocationMutableError(
                "dataset_revision is required; mutable refs are rejected"
            )
        if revision.lower() in _MUTABLE_REVISION_NAMES:
            raise SkillCenterInvocationMutableError(
                f"mutable dataset_revision {revision!r} is rejected"
            )

    def _validate_identity(
        self,
        record: SkillCenterSkillRecord,
        context: SkillCenterInvocationContext,
        *,
        intent_document: IntentIRDocument,
        intent_document_id: str,
        formalization_artifact_id: str,
    ) -> None:
        if context.expected_skill_id and context.expected_skill_id != record.skill_id:
            raise SkillCenterInvocationIdentityError(
                f"skill_id mismatch: expected {context.expected_skill_id!r}, "
                f"got {record.skill_id!r}"
            )
        if (
            context.expected_content_sha256
            and context.expected_content_sha256 != record.content_sha256
        ):
            raise SkillCenterInvocationIdentityError(
                "content_sha256 mismatch (identity drift or wrong revision)"
            )
        if (
            context.expected_entry_cid
            and context.expected_entry_cid != record.entry_cid
        ):
            raise SkillCenterInvocationIdentityError(
                "entry_cid mismatch between context expectation and record"
            )
        if (
            context.expected_content_cid
            and context.expected_content_cid != record.content_cid
        ):
            raise SkillCenterInvocationIdentityError(
                "content_cid mismatch between context expectation and record"
            )
        if (
            context.expected_dataset_id
            and context.expected_dataset_id != record.dataset_id
        ):
            raise SkillCenterInvocationIdentityError(
                f"dataset_id mismatch: expected {context.expected_dataset_id!r}, "
                f"got {record.dataset_id!r}"
            )
        if (
            context.expected_dataset_revision
            and context.expected_dataset_revision != record.dataset_revision
        ):
            raise SkillCenterInvocationIdentityError(
                "dataset_revision mismatch between context expectation and record"
            )
        if (
            context.expected_repository_file
            and context.expected_repository_file != record.repository_file
        ):
            raise SkillCenterInvocationIdentityError(
                "repository_file mismatch between context expectation and record"
            )
        if (
            context.expected_bundle_sha256
            and context.expected_bundle_sha256 != record.bundle_sha256
        ):
            raise SkillCenterInvocationIdentityError(
                "bundle_sha256 mismatch (snapshot identity drift)"
            )
        bound_intent_id = intent_document_id or intent_document.document_id
        if bound_intent_id != intent_document.document_id:
            raise SkillCenterInvocationIdentityError(
                "intent_document_id mismatch between supplied identity and "
                f"Intent IR document ({bound_intent_id!r} != "
                f"{intent_document.document_id!r})"
            )
        if (
            context.expected_intent_document_id
            and context.expected_intent_document_id != bound_intent_id
        ):
            raise SkillCenterInvocationIdentityError(
                "expected_intent_document_id does not match Intent IR document"
            )
        if context.expected_formalization_artifact_id:
            if not formalization_artifact_id:
                raise SkillCenterInvocationIdentityError(
                    "expected_formalization_artifact_id set but no formalization "
                    "artifact identity was supplied"
                )
            if (
                context.expected_formalization_artifact_id
                != formalization_artifact_id
            ):
                raise SkillCenterInvocationIdentityError(
                    "formalization_artifact_id mismatch between context expectation "
                    "and supplied identity"
                )
        # SourceRef validates digest shapes without interpreting body content.
        record.to_source_ref().validate()

    def _validate_dispatcher(self, context: SkillCenterInvocationContext) -> None:
        if context.dispatcher_authority not in {
            DispatcherAuthority.HOST,
            DispatcherAuthority.RUNTIME,
        }:
            raise SkillCenterInvocationDispatcherError(
                "dispatcher_authority must be host or runtime; "
                "caller-controlled dispatcher is rejected"
            )
        audience = context.audience
        if audience.kind.lower() in _CALLER_DISPATCHER_MARKERS:
            raise SkillCenterInvocationDispatcherError(
                "caller-controlled dispatcher audience is rejected "
                f"(audience.kind={audience.kind!r})"
            )
        for label, candidate in (
            ("audience_id", audience.audience_id),
            ("deployment_id", audience.deployment_id),
            ("trust_domain", audience.trust_domain),
        ):
            if _is_caller_dispatcher_marker(candidate):
                raise SkillCenterInvocationDispatcherError(
                    "caller-controlled dispatcher audience is rejected "
                    f"({label}={candidate!r})"
                )
        for key, value in audience.attributes.items():
            if isinstance(value, str) and _is_caller_dispatcher_marker(value):
                raise SkillCenterInvocationDispatcherError(
                    "caller-controlled dispatcher audience is rejected "
                    f"(attributes.{key}={value!r})"
                )
            if key in {"authority", "controlled_by", "source"} and isinstance(
                value, str
            ):
                if value.lower() in _CALLER_DISPATCHER_MARKERS:
                    raise SkillCenterInvocationDispatcherError(
                        "audience.attributes.authority must not be caller-controlled"
                    )
        if audience.attributes.get("caller_controlled") is True:
            raise SkillCenterInvocationDispatcherError(
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
            raise SkillCenterInvocationBoundError(
                f"{path}: callable/dynamic values are rejected in arguments"
            )
        if isinstance(value, Mapping):
            if any(key in value for key in ("__call__", "__class__", "__import__")):
                raise SkillCenterInvocationBoundError(
                    f"{path}: dynamic/introspection argument keys are rejected"
                )
            for key, item in value.items():
                if not isinstance(key, str):
                    raise SkillCenterInvocationBoundError(
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
            raise SkillCenterInvocationBoundError(
                f"{name} exceeds maximum of {max_nodes} JSON nodes"
            )
        if depth > max_depth:
            raise SkillCenterInvocationBoundError(
                f"{name} exceeds maximum JSON depth of {max_depth}"
            )
        if isinstance(value, str) and len(value) > max_chars:
            raise SkillCenterInvocationBoundError(
                f"{name} string exceeds maximum length of {max_chars}"
            )
        if isinstance(value, Mapping):
            if len(value) > MAX_COLLECTION_ITEMS:
                raise SkillCenterInvocationBoundError(
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
                raise SkillCenterInvocationBoundError(
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
        self, context: SkillCenterInvocationContext
    ) -> ArgumentCommitment:
        try:
            return ArgumentCommitment.from_redacted(
                dict(context.redacted_arguments),
                secret_refs=context.secret_refs,
            )
        except InvocationEnvelopeValidationError as exc:
            message = str(exc).lower()
            if "raw secret" in message or "redacted token" in message:
                raise SkillCenterInvocationSecretError(str(exc)) from exc
            if "depth" in message or "nodes" in message or "maximum" in message:
                raise SkillCenterInvocationBoundError(str(exc)) from exc
            raise SkillCenterInvocationError(str(exc)) from exc

    def _build_tool_binding(
        self,
        record: SkillCenterSkillRecord,
        context: SkillCenterInvocationContext,
    ) -> ToolBinding:
        tool_id = _skill_tool_id(record.skill_id)
        attributes: dict[str, Any] = {
            "adapter": SKILLCENTER_INVOCATION_ADAPTER,
            "adapter_version": SKILLCENTER_INVOCATION_ADAPTER_VERSION,
            "normalizer_version": INTENT_NORMALIZER_VERSION,
            "entry_cid": record.entry_cid,
            "content_cid": record.content_cid,
            "dataset_id": record.dataset_id,
            "dataset_revision": record.dataset_revision,
            "repository_file": record.repository_file,
            "bundle_sha256": record.bundle_sha256,
            "domain": record.domain,
            "profile": record.profile,
            "skill_kind": record.skill_kind,
        }
        return ToolBinding(
            tool_id=tool_id,
            tool_name=record.title or record.skill_id,
            tool_version=record.dataset_revision,
            server_id="server:skillcenter",
            server_name="skillcenter",
            transport_peer="",
            attributes=attributes,
        )

    def _build_source_binding(
        self,
        record: SkillCenterSkillRecord,
        context: SkillCenterInvocationContext,
        *,
        intent_document: IntentIRDocument,
        intent_document_id: str,
        formalization_artifact_id: str,
    ) -> SourceBinding:
        source_ref = record.to_source_ref()
        source_id = (
            record.primary_source_id or record.source_id or record.skill_id
        )
        # SourceBinding.source_id must be a stable identifier when present.
        if source_id and not _ID_RE.fullmatch(source_id):
            source_id = f"source:{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:24]}"
        return SourceBinding(
            kind=InvocationKind.SKILLCENTER,
            source_ref=source_ref.ref_id,
            source_id=source_id if _ID_RE.fullmatch(source_id or "") else "",
            source_revision=record.dataset_revision,
            content_sha256=record.content_sha256,
            content_cid=record.content_cid,
            intent_document_id=intent_document_id or intent_document.document_id,
            formalization_artifact_id=formalization_artifact_id,
            attributes={
                "skill_id": record.skill_id,
                "entry_cid": record.entry_cid,
                "dataset_id": record.dataset_id,
                "repository_file": record.repository_file,
                "bundle_sha256": record.bundle_sha256,
                "title": record.title,
            },
        )

    def _build_scope(
        self,
        record: SkillCenterSkillRecord,
        context: SkillCenterInvocationContext,
        intent_document: IntentIRDocument,
    ) -> tuple[InvocationScope, tuple[SourceMapEntry, ...]]:
        known = set(context.known_capabilities)
        capability_entries: list[ScopeEntry] = []
        for claim in context.resolved_capabilities:
            if claim.value not in known:
                raise SkillCenterInvocationCapabilityError(
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

        action_entries: list[ScopeEntry] = []
        effect_entries: list[ScopeEntry] = list(
            _claims_to_entries(context.resolved_effects, ScopeKind.EFFECT)
        )
        source_maps: list[SourceMapEntry] = []
        sources_by_id = {src.ref_id: src for src in intent_document.sources}

        for index, action in enumerate(intent_document.actions):
            entry_id = f"scope:action:{_safe_token(action.action_id)[:48]}"
            if not _ID_RE.fullmatch(entry_id):
                entry_id = f"scope:action:{index}:{_hash_token(action.action_id)}"
            value = _action_value(action)
            action_entries.append(
                ScopeEntry(
                    entry_id=entry_id,
                    kind=ScopeKind.ACTION,
                    value=value,
                    description=f"{action.actor} {action.verb}".strip(),
                    attributes={
                        "action_id": action.action_id,
                        "actor": action.actor,
                        "verb": action.verb,
                        "grounding": "intent",
                    },
                )
            )
            span = _first_span(action.source_ref_ids, sources_by_id)
            if span is not None:
                source_maps.append(
                    SourceMapEntry(
                        map_id=f"map:action:{index}:{_hash_token(action.action_id)[:12]}",
                        field_path=f"/scope/actions/{index}",
                        source_ref=record.to_source_ref().ref_id,
                        start_char=span[0],
                        end_char=span[1],
                        note="intent action grounded in skill_md span",
                    )
                )

        if not action_entries:
            # Capability-style skills still need a concrete action label.
            action_entries.append(
                ScopeEntry(
                    entry_id=f"scope:action:{_safe_token(record.skill_id)}",
                    kind=ScopeKind.ACTION,
                    value=record.title or record.skill_id,
                    description="SkillCenter skill without enumerated procedure steps",
                    attributes={"grounding": "record-title"},
                )
            )

        # Intent effect statements are recorded as effects with source maps,
        # but never replace host-resolved effects.
        effect_offset = len(effect_entries)
        for index, statement in enumerate(intent_document.statements):
            if statement.kind is not StatementKind.EFFECT:
                continue
            text = statement.normalized_text.strip()
            if not text:
                continue
            entry_id = (
                f"scope:effect:intent:{_safe_token(statement.statement_id)[:40]}"
            )
            if not _ID_RE.fullmatch(entry_id):
                entry_id = (
                    f"scope:effect:intent:{index}:"
                    f"{_hash_token(statement.statement_id)}"
                )
            effect_entries.append(
                ScopeEntry(
                    entry_id=entry_id,
                    kind=ScopeKind.EFFECT,
                    value=text[:MAX_STRING_CHARS],
                    description="Intent-derived effect (untrusted claim, host may refine)",
                    attributes={
                        "statement_id": statement.statement_id,
                        "grounding": "intent",
                        "trusted": False,
                    },
                )
            )
            span = _first_span(statement.source_ref_ids, sources_by_id)
            map_index = effect_offset + index
            if span is not None:
                source_maps.append(
                    SourceMapEntry(
                        map_id=(
                            f"map:effect:{map_index}:"
                            f"{_hash_token(statement.statement_id)[:12]}"
                        ),
                        field_path=f"/scope/effects/{len(effect_entries) - 1}",
                        source_ref=record.to_source_ref().ref_id,
                        start_char=span[0],
                        end_char=span[1],
                        note="intent effect grounded in skill_md span",
                    )
                )

        scope = InvocationScope(
            actions=tuple(action_entries),
            effects=tuple(effect_entries),
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
        return scope, tuple(source_maps)

    def _collect_unsupported(
        self,
        record: SkillCenterSkillRecord,
        intent_document: IntentIRDocument,
        normalization: SkillNormalizationResult | None,
    ) -> tuple[
        tuple[UnsupportedField, ...],
        tuple[InvocationDiagnostic, ...],
        tuple[InvocationAssumption, ...],
    ]:
        unsupported: list[UnsupportedField] = []
        diagnostics: list[InvocationDiagnostic] = []
        assumptions: list[InvocationAssumption] = []
        source_ref = record.to_source_ref().ref_id

        if normalization is not None:
            for item in normalization.diagnostics:
                if (
                    ".unsupported" not in item.code
                    and ".ambiguous" not in item.code
                ):
                    continue
                field_path = "/skill_md"
                start = end = None
                if item.span is not None:
                    start = item.span.start_char
                    end = item.span.end_char
                    field_path = f"/skill_md[{start}:{end}]"
                unsupported.append(
                    UnsupportedField(
                        field_path=field_path,
                        reason=item.message,
                        source_ref=source_ref,
                        raw_kind="skill_md",
                        attributes={
                            "code": item.code,
                            "severity": item.severity.value,
                            "start_char": start,
                            "end_char": end,
                            "trusted": False,
                        },
                    )
                )
                severity = (
                    DiagnosticSeverity.WARNING
                    if item.severity
                    in {
                        NormalizationSeverity.WARNING,
                        NormalizationSeverity.ERROR,
                    }
                    else DiagnosticSeverity.INFO
                )
                diagnostics.append(
                    InvocationDiagnostic(
                        code=f"invocation.skillcenter.{item.code}",
                        message=item.message,
                        severity=severity,
                        field_path=field_path,
                    )
                )

        # Authority-shaped prose sections stay as unsupported claims.
        lowered = record.skill_md.casefold()
        for hint in sorted(_SKILL_AUTHORITY_SECTION_HINTS):
            if re.search(rf"(?m)^[ \t]{{0,3}}#{{1,6}}[ \t]+.*\b{re.escape(hint)}\b", lowered):
                field_path = f"/skill_md/section/{hint}"
                unsupported.append(
                    UnsupportedField(
                        field_path=field_path,
                        reason=(
                            "skill section may claim authority; host-resolved "
                            "bindings remain authoritative"
                        ),
                        source_ref=source_ref,
                        raw_kind="skill_section",
                        attributes={"hint": hint, "trusted": False},
                    )
                )

        if unsupported:
            diagnostics.append(
                InvocationDiagnostic(
                    code="invocation.skillcenter.unsupported_retained",
                    message=(
                        f"Retained {len(unsupported)} unsupported/ambiguous "
                        "skill field(s) without elevating them"
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
                        "Unsupported and ambiguous skill constructs were retained "
                        "as diagnostics and unsupported fields"
                    ),
                    source_ref=source_ref,
                )
            )

        # Intent document assumptions become envelope assumptions when present.
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

        return tuple(unsupported), tuple(diagnostics), tuple(assumptions)

    def _source_maps(
        self,
        record: SkillCenterSkillRecord,
        source_ref: str,
        intent_document: IntentIRDocument,
    ) -> tuple[SourceMapEntry, ...]:
        title_end = min(len(record.title), MAX_STRING_CHARS)
        maps = [
            SourceMapEntry(
                map_id="map:skillcenter-title",
                field_path="/tool/tool_name",
                source_ref=source_ref,
                start_char=0,
                end_char=title_end,
                note="skill title bound as tool_name",
            ),
            SourceMapEntry(
                map_id="map:skillcenter-body",
                field_path="/source/content_sha256",
                source_ref=source_ref,
                start_char=0,
                end_char=min(len(record.skill_md), MAX_STRING_CHARS),
                note="skill_md content identity",
            ),
            SourceMapEntry(
                map_id="map:skillcenter-intent",
                field_path="/source/intent_document_id",
                source_ref=source_ref,
                note=f"intent document {intent_document.document_id}",
            ),
        ]
        return tuple(maps)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillCenterInvocationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise SkillCenterInvocationError(f"{name} must not have surrounding whitespace")
    if len(value) > MAX_STRING_CHARS:
        raise SkillCenterInvocationBoundError(f"{name} exceeds maximum string length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, name)


def _require_identifier(value: Any, name: str) -> str:
    text = _require_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise SkillCenterInvocationError(f"{name} is not a stable identifier")
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
        raise SkillCenterInvocationError(f"{name} must be a sequence of strings")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise SkillCenterInvocationBoundError(f"{name} exceeds maximum collection size")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise SkillCenterInvocationError(f"{name} entries must be non-empty strings")
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
            raise SkillCenterInvocationError(
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
        raise SkillCenterInvocationError(f"{name} must be a sequence of strings")
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise SkillCenterInvocationBoundError(f"{name} exceeds maximum collection size")
    if ordered:
        result: list[str] = []
        for item in items:
            if not isinstance(item, str) or not item.strip() or item != item.strip():
                raise SkillCenterInvocationError(
                    f"{name} entries must be non-empty strings"
                )
            if len(item) > MAX_STRING_CHARS:
                raise SkillCenterInvocationBoundError(
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
        raise SkillCenterInvocationError(
            f"{name} must be a sequence of ResolvedScopeClaim"
        )
    items = tuple(values)
    if len(items) > MAX_COLLECTION_ITEMS:
        raise SkillCenterInvocationBoundError(f"{name} exceeds maximum collection size")
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
            raise SkillCenterInvocationError(
                f"{name} entries must be ResolvedScopeClaim"
            )
        if item.entry_id in seen:
            raise SkillCenterInvocationError(
                f"duplicate scope claim entry_id: {item.entry_id}"
            )
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


def _skill_tool_id(skill_id: str) -> str:
    if _ID_RE.fullmatch(skill_id):
        candidate = f"skill:{skill_id}"
        if _ID_RE.fullmatch(candidate):
            return candidate
    digest = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()[:24]
    return f"skill:{digest}"


def _action_value(action: IntentAction) -> str:
    parts = [action.verb]
    if action.object_refs:
        parts.append(" ".join(action.object_refs))
    value = " ".join(part for part in parts if part).strip()
    return value[:MAX_STRING_CHARS] if value else action.action_id


def _first_span(
    source_ref_ids: Sequence[str],
    sources_by_id: Mapping[str, Any],
) -> tuple[int, int] | None:
    for ref_id in source_ref_ids:
        source = sources_by_id.get(ref_id)
        if source is None or source.span is None:
            continue
        return source.span.start_char, source.span.end_char
    return None


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


def _stable_assumption_id(record: SkillCenterSkillRecord, label: str) -> str:
    material = f"{record.skill_id}|{record.content_sha256}|{label}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"assume:sc-{label}-{digest}"


__all__ = [
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
]
