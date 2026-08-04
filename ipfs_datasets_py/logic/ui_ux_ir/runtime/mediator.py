"""Formal-policy mediation and governed invocation requests (UIR-055).

The mediator is the sole pre-invocation decision point for UI/UX IR:

- evaluates candidate actions / staged external effects against typed formal
  and runtime policy evidence;
- returns allow / deny / confirm / defer / rewrite / fallback / rate-limit;
- builds a governed :class:`UIInvocationRequest` **only** for ``allow``;
- never lets UI visibility, enabled state, or raw event payloads grant authority;
- keeps theorem / satisfiability / monitor / policy results as distinct typed
  evidence (never substituted for one another);
- never calls transport or executors itself — callers may use
  :func:`execute_if_allowed` with a spy for tests.

Interface identity: ``UIMediator@1`` / ``UIMediationDecision@1``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Protocol, Sequence

from ..model.bindings import (
    ConfirmationClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)
from ..schema import ProgramBindingTargetKind, UIIRValidationError
from .events import CanonicalInteractionEvent, EventProvenance, validate_event
from .state_machine import EffectKind, RuntimeSnapshot, StagedEffect

UI_MEDIATOR_INTERFACE: Final = "UIMediator@1"
UI_MEDIATION_DECISION_INTERFACE: Final = "UIMediationDecision@1"
UI_INVOCATION_REQUEST_INTERFACE: Final = "UIInvocationRequest@1"
MEDIATOR_ADAPTER_ID: Final = "runtime.mediator@1"
MEDIATOR_SCHEMA_VERSION: Final = "ui-runtime-mediator/v1"

_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Outcomes that never produce an invocation request / never reach an executor.
_NON_EXECUTING_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "deny",
        "confirm",
        "defer",
        "rewrite",
        "fallback",
        "rate_limit",
        "error",
        "unknown",
    }
)


class MediationOutcome(str, Enum):
    """Closed mediation outcomes (UIR-055 acceptance catalogue)."""

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"
    DEFER = "defer"
    REWRITE = "rewrite"
    FALLBACK = "fallback"
    RATE_LIMIT = "rate_limit"
    # Fail-closed terminals — treated as non-executing denials with typed reasons.
    ERROR = "error"
    UNKNOWN = "unknown"


class FormalEvidenceKind(str, Enum):
    """Typed formal / runtime evidence. Kinds are never interchangeable."""

    THEOREM = "theorem"
    SATISFIABILITY = "satisfiability"
    MONITOR = "monitor"
    POLICY = "policy"


class FormalEvidenceResult(str, Enum):
    """Closed result lattice for one evidence kind."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    ERROR = "error"


class ActorKind(str, Enum):
    """Who initiates the interaction for authority checks."""

    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class PolicyVerdict(str, Enum):
    """Explicit policy norm verdict (never inferred from UI state)."""

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"
    DEFER = "defer"
    REWRITE = "rewrite"
    FALLBACK = "fallback"
    RATE_LIMIT = "rate_limit"


@dataclass(frozen=True, slots=True)
class FormalEvidence:
    """One typed formal or runtime authority result.

    Proof is never substituted for policy, monitor, or satisfiability.
    """

    kind: FormalEvidenceKind
    result: FormalEvidenceResult
    evidence_id: str = ""
    detail: str = ""

    def validate(self) -> None:
        if not isinstance(self.kind, FormalEvidenceKind):
            raise UIIRValidationError("FormalEvidence.kind must be FormalEvidenceKind")
        if not isinstance(self.result, FormalEvidenceResult):
            raise UIIRValidationError(
                "FormalEvidence.result must be FormalEvidenceResult"
            )
        if self.evidence_id and not _IDENTIFIER_RE.fullmatch(self.evidence_id):
            raise UIIRValidationError(
                f"FormalEvidence.evidence_id is not a stable identifier: "
                f"{self.evidence_id!r}"
            )


@dataclass(frozen=True, slots=True)
class PolicyNorm:
    """Closed policy rule evaluated against an action candidate."""

    norm_id: str
    verdict: PolicyVerdict
    priority: int = 0
    binding_id: str = ""
    action_id: str = ""
    # Optional rewrite / fallback targets (must be explicit when used).
    rewrite_binding_id: str = ""
    fallback_binding_id: str = ""
    rate_limit_remaining: int | None = None
    reason: str = ""

    def validate(self) -> None:
        if not _IDENTIFIER_RE.fullmatch(self.norm_id):
            raise UIIRValidationError(f"PolicyNorm.norm_id invalid: {self.norm_id!r}")
        if not isinstance(self.verdict, PolicyVerdict):
            raise UIIRValidationError("PolicyNorm.verdict must be PolicyVerdict")
        if self.verdict is PolicyVerdict.REWRITE and not self.rewrite_binding_id:
            raise UIIRValidationError(
                f"PolicyNorm {self.norm_id!r} REWRITE requires rewrite_binding_id"
            )
        if self.verdict is PolicyVerdict.FALLBACK and not self.fallback_binding_id:
            raise UIIRValidationError(
                f"PolicyNorm {self.norm_id!r} FALLBACK requires fallback_binding_id"
            )


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Exact actor identity, delegation, and consent for mediation."""

    actor_id: str
    kind: ActorKind
    # Exact capability scope the agent is delegated (empty for human).
    delegation_scope: frozenset[str] = frozenset()
    # Explicit human consent token / flag for consent-class actions.
    human_consent: bool = False
    # Confirmation already obtained for this decision lineage.
    confirmation_granted: bool = False

    def validate(self) -> None:
        if not _IDENTIFIER_RE.fullmatch(self.actor_id):
            raise UIIRValidationError(f"ActorContext.actor_id invalid: {self.actor_id!r}")
        if not isinstance(self.kind, ActorKind):
            raise UIIRValidationError("ActorContext.kind must be ActorKind")
        if self.kind is ActorKind.AGENT and not self.delegation_scope:
            # Agents may still be evaluated; missing scope is denied later.
            pass


@dataclass(frozen=True, slots=True)
class RuntimeMediationContext:
    """Runtime + projection + declaration context. UI state is never authority."""

    declaration_digest: str
    projection_id: str
    state_version: int
    active_state_ids: frozenset[str] = frozenset()
    actor: ActorContext | None = None
    # Observational UI state — **never** used to grant permission.
    ui_visible: bool = True
    ui_enabled: bool = True
    ui_phase: str = ""
    rate_limit_remaining: int | None = None
    formal_evidence: tuple[FormalEvidence, ...] = ()
    policy_norms: tuple[PolicyNorm, ...] = ()
    facts: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({}))
    # Optional staged external effects from the state machine.
    staged_effects: tuple[StagedEffect, ...] = ()
    schema_version: str = MEDIATOR_SCHEMA_VERSION

    def validate(self) -> None:
        if not self.declaration_digest.strip():
            raise UIIRValidationError(
                "RuntimeMediationContext.declaration_digest must not be empty"
            )
        if not self.projection_id.strip():
            raise UIIRValidationError(
                "RuntimeMediationContext.projection_id must not be empty"
            )
        if self.state_version < 0:
            raise UIIRValidationError("state_version must be non-negative")
        if self.actor is not None:
            self.actor.validate()
        for item in self.formal_evidence:
            item.validate()
        for norm in self.policy_norms:
            norm.validate()
        if type(self.facts) is not MappingProxyType:
            object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


@dataclass(frozen=True, slots=True)
class UIInvocationRequest:
    """Governed invocation request — only produced for MediationOutcome.ALLOW.

    Binds declaration / projection / state / event / actor / policy / IDL /
    Intent / expected effects. Never carries authority grants.
    """

    request_id: str
    binding_id: str
    action_id: str
    declaration_digest: str
    projection_id: str
    state_version: int
    event_id: str
    actor_id: str
    policy_norm_id: str
    program_target_kind: str
    program_target_ref: str
    mcp_idl_interface_cid: str = ""
    mcp_idl_method_name: str = ""
    intent_document_id: str = ""
    intent_action_id: str = ""
    invocation_template_cid: str = ""
    expected_effect_ids: tuple[str, ...] = ()
    risk_class: str = RiskClass.LOW.value
    confirmation_class: str = ConfirmationClass.NONE.value
    interface: str = UI_INVOCATION_REQUEST_INTERFACE
    schema_version: str = MEDIATOR_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "actor_id": self.actor_id,
            "binding_id": self.binding_id,
            "confirmation_class": self.confirmation_class,
            "declaration_digest": self.declaration_digest,
            "event_id": self.event_id,
            "expected_effect_ids": list(self.expected_effect_ids),
            "intent_action_id": self.intent_action_id,
            "intent_document_id": self.intent_document_id,
            "interface": self.interface,
            "invocation_template_cid": self.invocation_template_cid,
            "mcp_idl_interface_cid": self.mcp_idl_interface_cid,
            "mcp_idl_method_name": self.mcp_idl_method_name,
            "policy_norm_id": self.policy_norm_id,
            "program_target_kind": self.program_target_kind,
            "program_target_ref": self.program_target_ref,
            "projection_id": self.projection_id,
            "request_id": self.request_id,
            "risk_class": self.risk_class,
            "schema_version": self.schema_version,
            "state_version": self.state_version,
        }


@dataclass(frozen=True, slots=True)
class UIMediationDecision:
    """Typed mediation decision (``UIMediationDecision@1``)."""

    decision_id: str
    outcome: MediationOutcome
    binding_id: str
    action_id: str
    event_id: str
    reasons: tuple[str, ...]
    can_execute: bool
    invocation_request: UIInvocationRequest | None = None
    selected_policy_norm_id: str = ""
    rewrite_binding_id: str = ""
    fallback_binding_id: str = ""
    formal_evidence: tuple[FormalEvidence, ...] = ()
    # Explicitly record that UI state was not used as authority.
    ui_state_authority_used: bool = False
    adapter_id: str = MEDIATOR_ADAPTER_ID
    interface: str = UI_MEDIATION_DECISION_INTERFACE
    schema_version: str = MEDIATOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.outcome is MediationOutcome.ALLOW:
            if not self.can_execute or self.invocation_request is None:
                raise UIIRValidationError(
                    "ALLOW decisions must set can_execute=True and carry "
                    "an invocation_request"
                )
        else:
            if self.can_execute:
                raise UIIRValidationError(
                    f"Non-allow outcome {self.outcome.value!r} must not set can_execute"
                )
            if self.invocation_request is not None:
                raise UIIRValidationError(
                    f"Non-allow outcome {self.outcome.value!r} must not carry "
                    "an invocation_request"
                )
        if self.ui_state_authority_used:
            raise UIIRValidationError(
                "UI state must never be recorded as authority for mediation"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "adapter_id": self.adapter_id,
            "binding_id": self.binding_id,
            "can_execute": self.can_execute,
            "decision_id": self.decision_id,
            "event_id": self.event_id,
            "fallback_binding_id": self.fallback_binding_id,
            "formal_evidence": [
                {
                    "detail": e.detail,
                    "evidence_id": e.evidence_id,
                    "kind": e.kind.value,
                    "result": e.result.value,
                }
                for e in self.formal_evidence
            ],
            "interface": self.interface,
            "invocation_request": (
                None
                if self.invocation_request is None
                else self.invocation_request.to_dict()
            ),
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "rewrite_binding_id": self.rewrite_binding_id,
            "schema_version": self.schema_version,
            "selected_policy_norm_id": self.selected_policy_norm_id,
            "ui_state_authority_used": self.ui_state_authority_used,
        }


class InvocationExecutor(Protocol):
    """Spy-friendly executor protocol (never implemented by the mediator)."""

    def __call__(self, request: UIInvocationRequest) -> Any: ...


def _stable_id(*parts: str) -> str:
    material = "\0".join(parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"med-{digest}"


def _target_ref(program: UIProgramRef) -> str:
    return program.target_ref()


def _binding_in_scope(binding: UIActionBinding, actor: ActorContext | None) -> bool:
    """Agent actions require an exact delegation match on binding or action id."""

    if actor is None:
        return False
    if actor.kind is not ActorKind.AGENT:
        return True
    scope = actor.delegation_scope
    return binding.binding_id in scope or binding.action_id in scope


def _select_policy_norm(
    norms: Sequence[PolicyNorm],
    binding: UIActionBinding,
) -> PolicyNorm | None:
    """Pick highest-priority matching norm; deny-over-permit on ties of different verdicts."""

    matching = [
        n
        for n in norms
        if (not n.binding_id or n.binding_id == binding.binding_id)
        and (not n.action_id or n.action_id == binding.action_id)
    ]
    if not matching:
        return None

    # Higher priority first; on equal priority, deny-family beats allow.
    def sort_key(n: PolicyNorm) -> tuple[int, int, str]:
        deny_rank = {
            PolicyVerdict.DENY: 700,
            PolicyVerdict.RATE_LIMIT: 600,
            PolicyVerdict.CONFIRM: 500,
            PolicyVerdict.FALLBACK: 400,
            PolicyVerdict.REWRITE: 300,
            PolicyVerdict.DEFER: 200,
            PolicyVerdict.ALLOW: 100,
        }[n.verdict]
        return (-n.priority, -deny_rank, n.norm_id)

    return sorted(matching, key=sort_key)[0]


def _evidence_blocks_allow(evidence: Sequence[FormalEvidence]) -> FormalEvidence | None:
    """Any FAIL/ERROR/UNKNOWN on required-like evidence blocks allow.

    Kinds stay typed: we never treat theorem PASS as policy PASS.
    Missing policy evidence is handled separately.
    """

    for item in evidence:
        if item.result in {
            FormalEvidenceResult.FAIL,
            FormalEvidenceResult.ERROR,
            FormalEvidenceResult.UNKNOWN,
        }:
            return item
    return None


def _confirmation_required(
    binding: UIActionBinding,
    actor: ActorContext | None,
) -> bool:
    if binding.confirmation_class is ConfirmationClass.NONE:
        return False
    if actor is None:
        return True
    if binding.confirmation_class is ConfirmationClass.CONSENT:
        return not actor.human_consent
    # CONFIRM / DOUBLE_CONFIRM require an explicit confirmation_granted.
    return not actor.confirmation_granted


def _build_invocation_request(
    *,
    binding: UIActionBinding,
    event: CanonicalInteractionEvent,
    context: RuntimeMediationContext,
    policy_norm_id: str,
    actor_id: str,
) -> UIInvocationRequest:
    program = binding.program_ref
    request_id = _stable_id(
        "inv",
        binding.binding_id,
        event.event_id,
        context.declaration_digest,
        str(context.state_version),
        policy_norm_id,
    )
    return UIInvocationRequest(
        request_id=request_id,
        binding_id=binding.binding_id,
        action_id=binding.action_id,
        declaration_digest=context.declaration_digest,
        projection_id=context.projection_id,
        state_version=context.state_version,
        event_id=event.event_id,
        actor_id=actor_id,
        policy_norm_id=policy_norm_id,
        program_target_kind=program.target_kind.value,
        program_target_ref=_target_ref(program),
        mcp_idl_interface_cid=program.mcp_idl_interface_cid,
        mcp_idl_method_name=program.mcp_idl_method_name,
        intent_document_id=program.intent_document_id,
        intent_action_id=program.intent_action_id,
        invocation_template_cid=program.invocation_template_cid,
        expected_effect_ids=tuple(binding.effect_ids),
        risk_class=binding.risk_class.value,
        confirmation_class=binding.confirmation_class.value,
    )


def _decision(
    *,
    outcome: MediationOutcome,
    binding: UIActionBinding,
    event: CanonicalInteractionEvent,
    reasons: Sequence[str],
    context: RuntimeMediationContext,
    policy_norm_id: str = "",
    rewrite_binding_id: str = "",
    fallback_binding_id: str = "",
    invocation_request: UIInvocationRequest | None = None,
) -> UIMediationDecision:
    can_execute = outcome is MediationOutcome.ALLOW
    decision_id = _stable_id(
        "dec",
        binding.binding_id,
        event.event_id,
        outcome.value,
        policy_norm_id,
        "|".join(reasons[:4]),
    )
    return UIMediationDecision(
        decision_id=decision_id,
        outcome=outcome,
        binding_id=binding.binding_id,
        action_id=binding.action_id,
        event_id=event.event_id,
        reasons=tuple(reasons),
        can_execute=can_execute,
        invocation_request=invocation_request,
        selected_policy_norm_id=policy_norm_id,
        rewrite_binding_id=rewrite_binding_id,
        fallback_binding_id=fallback_binding_id,
        formal_evidence=context.formal_evidence,
        ui_state_authority_used=False,
    )


class UIMediator:
    """Fail-closed formal-policy mediator (``UIMediator@1``)."""

    def __init__(
        self,
        *,
        require_policy_norm: bool = True,
        require_policy_evidence: bool = False,
    ) -> None:
        """Create a mediator.

        Parameters
        ----------
        require_policy_norm:
            When True (default), missing matching policy norms fail closed to
            DENY (no Hallucinate-style default-allow path).
        require_policy_evidence:
            When True, a typed :class:`FormalEvidence` with kind POLICY and
            result PASS must be present to allow.
        """

        self.require_policy_norm = require_policy_norm
        self.require_policy_evidence = require_policy_evidence

    def mediate(
        self,
        binding: UIActionBinding,
        event: CanonicalInteractionEvent,
        context: RuntimeMediationContext,
    ) -> UIMediationDecision:
        """Evaluate one action binding against policy and formal evidence."""

        try:
            binding.validate()
            validate_event(event)
            context.validate()
        except UIIRValidationError as exc:
            return _decision(
                outcome=MediationOutcome.ERROR,
                binding=binding if isinstance(binding, UIActionBinding) else _dummy_binding(),
                event=event
                if isinstance(event, CanonicalInteractionEvent)
                else _dummy_event(),
                reasons=(f"validation_error:{exc}",),
                context=context
                if isinstance(context, RuntimeMediationContext)
                else _dummy_context(),
            )

        # Explicit: UI visibility / enabled never grant permission.
        # We only *observe* them in reasons when deny paths mention UX, but
        # never flip a deny to allow because ui_enabled is True.
        _ = (context.ui_visible, context.ui_enabled, context.ui_phase)

        actor = context.actor
        if actor is None:
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=("missing_actor",),
                context=context,
            )

        # Agent provenance on the event must not expand beyond actor delegation.
        if event.provenance is EventProvenance.AGENT and actor.kind is not ActorKind.AGENT:
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=("agent_event_without_agent_actor",),
                context=context,
            )

        if not _binding_in_scope(binding, actor):
            scope_reason = (
                "agent_delegation_mismatch"
                if actor.kind is ActorKind.AGENT
                else "actor_out_of_scope"
            )
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=(scope_reason,),
                context=context,
            )

        # Formal evidence: FAIL/ERROR/UNKNOWN block allow; kinds stay typed.
        blocking = _evidence_blocks_allow(context.formal_evidence)
        if blocking is not None:
            outcome = (
                MediationOutcome.ERROR
                if blocking.result is FormalEvidenceResult.ERROR
                else MediationOutcome.DENY
                if blocking.result is FormalEvidenceResult.FAIL
                else MediationOutcome.UNKNOWN
            )
            return _decision(
                outcome=outcome,
                binding=binding,
                event=event,
                reasons=(
                    f"formal_{blocking.kind.value}_{blocking.result.value}",
                    blocking.detail or blocking.evidence_id or "formal_block",
                ),
                context=context,
            )

        if self.require_policy_evidence:
            policy_pass = any(
                e.kind is FormalEvidenceKind.POLICY
                and e.result is FormalEvidenceResult.PASS
                for e in context.formal_evidence
            )
            if not policy_pass:
                return _decision(
                    outcome=MediationOutcome.DENY,
                    binding=binding,
                    event=event,
                    reasons=("missing_policy_evidence_pass",),
                    context=context,
                )

        # Local-state-only bindings never produce external invocation requests.
        if binding.program_ref.target_kind is ProgramBindingTargetKind.LOCAL_STATE:
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=("local_state_only_no_external_invocation",),
                context=context,
            )

        selected = _select_policy_norm(context.policy_norms, binding)
        if selected is None:
            if self.require_policy_norm:
                return _decision(
                    outcome=MediationOutcome.DENY,
                    binding=binding,
                    event=event,
                    reasons=("no_matching_policy_norm", "fail_closed"),
                    context=context,
                )
            # Explicit open path still cannot default to allow without a norm.
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=("no_matching_policy_norm",),
                context=context,
            )

        # Map policy verdict → mediation outcome (rewrite/fallback stay explicit).
        if selected.verdict is PolicyVerdict.DENY:
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=(selected.reason or "policy_deny", selected.norm_id),
                context=context,
                policy_norm_id=selected.norm_id,
            )

        if selected.verdict is PolicyVerdict.DEFER:
            return _decision(
                outcome=MediationOutcome.DEFER,
                binding=binding,
                event=event,
                reasons=(selected.reason or "policy_defer", selected.norm_id),
                context=context,
                policy_norm_id=selected.norm_id,
            )

        if selected.verdict is PolicyVerdict.REWRITE:
            return _decision(
                outcome=MediationOutcome.REWRITE,
                binding=binding,
                event=event,
                reasons=(selected.reason or "policy_rewrite", selected.norm_id),
                context=context,
                policy_norm_id=selected.norm_id,
                rewrite_binding_id=selected.rewrite_binding_id,
            )

        if selected.verdict is PolicyVerdict.FALLBACK:
            return _decision(
                outcome=MediationOutcome.FALLBACK,
                binding=binding,
                event=event,
                reasons=(selected.reason or "policy_fallback", selected.norm_id),
                context=context,
                policy_norm_id=selected.norm_id,
                fallback_binding_id=selected.fallback_binding_id,
            )

        if selected.verdict is PolicyVerdict.RATE_LIMIT:
            remaining = (
                selected.rate_limit_remaining
                if selected.rate_limit_remaining is not None
                else context.rate_limit_remaining
            )
            return _decision(
                outcome=MediationOutcome.RATE_LIMIT,
                binding=binding,
                event=event,
                reasons=(
                    selected.reason or "policy_rate_limit",
                    selected.norm_id,
                    f"remaining={remaining}",
                ),
                context=context,
                policy_norm_id=selected.norm_id,
            )

        if selected.verdict is PolicyVerdict.CONFIRM:
            return _decision(
                outcome=MediationOutcome.CONFIRM,
                binding=binding,
                event=event,
                reasons=(selected.reason or "policy_confirm", selected.norm_id),
                context=context,
                policy_norm_id=selected.norm_id,
            )

        # Policy ALLOW path — still subject to confirmation class & rate budget.
        assert selected.verdict is PolicyVerdict.ALLOW

        remaining = context.rate_limit_remaining
        if remaining is not None and remaining <= 0:
            return _decision(
                outcome=MediationOutcome.RATE_LIMIT,
                binding=binding,
                event=event,
                reasons=("rate_limit_exhausted", selected.norm_id),
                context=context,
                policy_norm_id=selected.norm_id,
            )

        if _confirmation_required(binding, actor):
            reason = (
                "human_consent_required"
                if binding.confirmation_class is ConfirmationClass.CONSENT
                else "confirmation_required"
            )
            return _decision(
                outcome=MediationOutcome.CONFIRM,
                binding=binding,
                event=event,
                reasons=(reason, selected.norm_id, binding.confirmation_class.value),
                context=context,
                policy_norm_id=selected.norm_id,
            )

        # Staged external effects must remain unexecuted at mediation time.
        for staged in context.staged_effects:
            if staged.kind is EffectKind.EXTERNAL_REQUEST and staged.executed:
                return _decision(
                    outcome=MediationOutcome.ERROR,
                    binding=binding,
                    event=event,
                    reasons=(
                        "external_effect_already_executed",
                        staged.effect_id,
                    ),
                    context=context,
                    policy_norm_id=selected.norm_id,
                )

        request = _build_invocation_request(
            binding=binding,
            event=event,
            context=context,
            policy_norm_id=selected.norm_id,
            actor_id=actor.actor_id,
        )
        return _decision(
            outcome=MediationOutcome.ALLOW,
            binding=binding,
            event=event,
            reasons=("policy_allow", selected.norm_id),
            context=context,
            policy_norm_id=selected.norm_id,
            invocation_request=request,
        )

    def evaluate_staged_effect(
        self,
        binding: UIActionBinding,
        event: CanonicalInteractionEvent,
        context: RuntimeMediationContext,
        effect: StagedEffect,
    ) -> UIMediationDecision:
        """Mediate one staged external effect (must not already be executed)."""

        if effect.kind is not EffectKind.EXTERNAL_REQUEST:
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=("not_external_effect", effect.effect_id),
                context=context,
            )
        if effect.executed:
            return _decision(
                outcome=MediationOutcome.ERROR,
                binding=binding,
                event=event,
                reasons=("external_effect_already_executed", effect.effect_id),
                context=context,
            )
        # Prefer binding_ref match when present.
        if effect.binding_ref and effect.binding_ref != binding.binding_id:
            return _decision(
                outcome=MediationOutcome.DENY,
                binding=binding,
                event=event,
                reasons=("effect_binding_mismatch", effect.effect_id),
                context=context,
            )
        return self.mediate(binding, event, context)


def execute_if_allowed(
    decision: UIMediationDecision,
    executor: InvocationExecutor,
) -> Any | None:
    """Call ``executor`` only for ALLOW decisions; otherwise return None.

    Blocking / unknown / error / confirm / defer / rewrite / fallback /
    rate-limit outcomes never reach the executor.
    """

    if decision.outcome is not MediationOutcome.ALLOW or not decision.can_execute:
        return None
    if decision.invocation_request is None:
        return None
    if decision.outcome.value in _NON_EXECUTING_OUTCOMES:
        return None
    return executor(decision.invocation_request)


def context_from_snapshot(
    snapshot: RuntimeSnapshot,
    *,
    declaration_digest: str,
    projection_id: str,
    actor: ActorContext,
    formal_evidence: Sequence[FormalEvidence] = (),
    policy_norms: Sequence[PolicyNorm] = (),
    rate_limit_remaining: int | None = None,
) -> RuntimeMediationContext:
    """Build a mediation context from a state-machine snapshot (UI state observational only)."""

    return RuntimeMediationContext(
        declaration_digest=declaration_digest,
        projection_id=projection_id,
        state_version=snapshot.state_version,
        active_state_ids=snapshot.active_state_ids,
        actor=actor,
        ui_visible=True,
        ui_enabled=True,
        ui_phase=snapshot.phase.value,
        rate_limit_remaining=rate_limit_remaining,
        formal_evidence=tuple(formal_evidence),
        policy_norms=tuple(policy_norms),
        facts=snapshot.facts,
        staged_effects=snapshot.staged_effects,
    )


def create_mediator(**kwargs: Any) -> UIMediator:
    """Factory for ``UIMediator@1``."""

    return UIMediator(**kwargs)


# --- internal fallbacks used only when validation itself fails early ---


def _dummy_binding() -> UIActionBinding:
    return UIActionBinding(
        binding_id="binding:invalid",
        action_id="action:invalid",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.LOCAL_STATE,
            local_state_transition="noop",
        ),
    )


def _dummy_event() -> CanonicalInteractionEvent:
    from .events import EventKind

    return CanonicalInteractionEvent(
        event_id="event:invalid",
        kind=EventKind.CUSTOM,
        target_component_id="component:invalid",
        timestamp_ms=0,
        provenance=EventProvenance.UNKNOWN,
        capability_id="cap:invalid",
        consent_ok=True,
    )


def _dummy_context() -> RuntimeMediationContext:
    return RuntimeMediationContext(
        declaration_digest="decl:invalid",
        projection_id="proj:invalid",
        state_version=0,
    )
