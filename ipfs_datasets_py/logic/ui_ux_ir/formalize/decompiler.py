"""Semantic decompiler from multi-view formalization to UI reconstruction (UIR-026).

``UIFormalDecompiler@1`` reconstructs *supported* semantic fragments from a
typed ``UIFormalizationArtifact``. Reconstruction is constraint-guided and
fail-closed:

- never invents sources, grants, components, actions, or device capability;
- preserves source grounding only when present on formal formulas/facts;
- retains ambiguity as alternatives or clarification requirements;
- never weakens strict prohibitions or obligations;
- never claims source-code or pixel equality.

The decompiler cannot recreate arbitrary original source text, CSS, React
structure, or visual artwork. Those remain out of scope (source maps / target
artifacts only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..schema import UIIRValidationError
from .compiler import UIFormalizationArtifact
from .contracts import FormalView, ResultAuthority
from .dcec import DCECCompilation
from .event_calculus import EventCalculusCompilation
from .flogic import FLogicCompilation
from .tdfol import TDFOLCompilation

UI_FORMAL_DECOMPILER_INTERFACE: Final = "UIFormalDecompiler@1"
UI_FORMAL_DECOMPILER_ID: Final = "ui-ux-ir/formal-decompiler@1"
UI_RECONSTRUCTION_ARTIFACT_INTERFACE: Final = "UIReconstructionArtifact@1"
UI_RECONSTRUCTION_ARTIFACT_SCHEMA: Final = "ui-reconstruction-artifact/v1"

_PROP_ACTION_RE = re.compile(
    r"^(?:invoke|confirm|weaken_norm)\(([^,)]+)\)$"
)
_BEFORE_CONFIRM_RE = re.compile(
    r"^invoke\(([^)]+)\) before confirm\(\1\)$"
)
_CONFIRM_BEFORE_RE = re.compile(
    r"^confirm\(([^)]+)\) before invoke\(\1\)$"
)
_IN_STATE_RE = re.compile(r"^in_state\(([^)]+)\)$")
_TIMEOUT_RE = re.compile(r"^timeout\(([^)]+)\)$")
_EVENT_CONTENT_RE = re.compile(r"^([A-Za-z0-9_.:/-]+)\(([^)]*)\)$")

# Authority-grant surfaces that reconstruction must never invent.
_FORBIDDEN_GRANT_KEYS: Final = frozenset(
    {
        "authority_grant",
        "capability_token",
        "delegation_grant",
        "grant",
        "grants",
        "permission_elevation",
        "role_grant",
        "ucan",
        "ucan_token",
    }
)


class ReconstructionDisposition(str, Enum):
    """How a reconstructed symbol was obtained."""

    GROUNDED = "grounded"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    CLARIFICATION_REQUIRED = "clarification_required"
    REJECTED_INVENTION = "rejected_invention"


@dataclass(frozen=True, slots=True)
class DecompilationRequest:
    """Request bounds for semantic decompilation."""

    request_id: str = "decompile/default"
    allow_alternatives: bool = True
    # Seed source map is advisory only; never invents missing grounding.
    seed_source_map: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    # Optional accessibility / modality seeds for survival checks (not invention).
    accessibility_component_ids: tuple[str, ...] = ()
    essential_modality_capability_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconstructedComponent:
    """Semantic component recovered from F-logic facts only."""

    component_id: str
    role: str
    parent_id: str = ""
    child_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    disposition: ReconstructionDisposition = ReconstructionDisposition.GROUNDED


@dataclass(frozen=True, slots=True)
class ReconstructedNorm:
    """Deontic norm recovered from TDFOL; strength must not weaken."""

    operator: str  # obligation | permission | prohibition
    proposition: str
    strength: str
    action_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    disposition: ReconstructionDisposition = ReconstructionDisposition.GROUNDED


@dataclass(frozen=True, slots=True)
class ReconstructedAction:
    """Action recovered from deontic propositions; no program grants invented."""

    action_id: str
    operators: tuple[str, ...]
    max_strength: str
    requires_confirmation: bool = False
    source_ref_ids: tuple[str, ...] = ()
    # Explicitly empty: reconstruction never invents program/capability grants.
    invented_grants: tuple[str, ...] = ()
    disposition: ReconstructionDisposition = ReconstructionDisposition.GROUNDED


@dataclass(frozen=True, slots=True)
class ReconstructedState:
    state_id: str
    disposition: ReconstructionDisposition = ReconstructionDisposition.GROUNDED


@dataclass(frozen=True, slots=True)
class ReconstructedTransition:
    event_id: str
    source_state_ids: tuple[str, ...]
    target_state_id: str
    timeout_ms: int | None = None
    disposition: ReconstructionDisposition = ReconstructionDisposition.GROUNDED


@dataclass(frozen=True, slots=True)
class ReconstructedCognitive:
    kind: str
    actor: str
    content: str
    disposition: ReconstructionDisposition = ReconstructionDisposition.GROUNDED


@dataclass(frozen=True, slots=True)
class ReconstructionAlternative:
    """One alternative reading when formal input is ambiguous."""

    alternative_id: str
    subject: str
    description: str
    candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClarificationRequirement:
    """Clarification required before a unique reconstruction is possible."""

    code: str
    message: str
    related_symbols: tuple[str, ...] = ()
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class ReconstructionLossItem:
    """Explicit reconstruction loss; silent drops are forbidden."""

    semantic_id: str
    category: str  # unsupported | approximated | withheld | out_of_scope
    reason: str


@dataclass(frozen=True, slots=True)
class ReconstructionReceipt:
    """Immutable receipt that reconstruction obeyed non-invention rules."""

    receipt_id: str
    faithful: bool
    source_grounding_preserved: bool
    deontic_non_weakening: bool
    invented_sources: tuple[str, ...] = ()
    invented_grants: tuple[str, ...] = ()
    invented_components: tuple[str, ...] = ()
    invented_actions: tuple[str, ...] = ()
    invented_device_capabilities: tuple[str, ...] = ()
    rejected_inventions: tuple[str, ...] = ()
    accessibility_survived: bool = True
    essential_modality_survived: bool = True
    claims_source_equality: bool = False
    claims_pixel_equality: bool = False
    notes: str = ""

    def has_inventions(self) -> bool:
        return bool(
            self.invented_sources
            or self.invented_grants
            or self.invented_components
            or self.invented_actions
            or self.invented_device_capabilities
        )


@dataclass(frozen=True, slots=True)
class UIReconstructionArtifact:
    """Immutable semantic reconstruction (not source/pixel recovery)."""

    reconstruction_id: str
    decompiler_id: str
    source_artifact_id: str
    components: tuple[ReconstructedComponent, ...]
    actions: tuple[ReconstructedAction, ...]
    norms: tuple[ReconstructedNorm, ...]
    states: tuple[ReconstructedState, ...]
    transitions: tuple[ReconstructedTransition, ...]
    cognitive: tuple[ReconstructedCognitive, ...]
    alternatives: tuple[ReconstructionAlternative, ...]
    clarifications: tuple[ClarificationRequirement, ...]
    loss: tuple[ReconstructionLossItem, ...]
    unsupported: tuple[str, ...]
    accessibility_roles: Mapping[str, str]  # component_id -> role
    essential_modality_capability_ids: tuple[str, ...]
    receipt: ReconstructionReceipt
    result_authority: ResultAuthority = ResultAuthority.ADVISORY
    schema_version: str = UI_RECONSTRUCTION_ARTIFACT_SCHEMA
    interface: str = UI_RECONSTRUCTION_ARTIFACT_INTERFACE
    # Hard exclusions from the reconstruction claim surface.
    excluded_equivalence_claims: tuple[str, ...] = (
        "source_equality",
        "pixel_equality",
    )


def _extract_action_id(proposition: str) -> str:
    m = _PROP_ACTION_RE.match(proposition.strip())
    if m:
        return m.group(1)
    for pattern in (_BEFORE_CONFIRM_RE, _CONFIRM_BEFORE_RE):
        m = pattern.match(proposition.strip())
        if m:
            return m.group(1)
    # Fallback: first parenthesized single identifier.
    if "(" in proposition and proposition.endswith(")"):
        inner = proposition[proposition.index("(") + 1 : -1]
        if inner and "," not in inner:
            # handle "invoke(x) before confirm(x)" already covered
            token = inner.split()[0] if " " in inner else inner
            if re.fullmatch(r"[A-Za-z0-9_.:/-]+", token):
                return token
    return ""


def _strength_rank(strength: str) -> int:
    order = {"weak": 1, "default": 2, "strict": 3}
    return order.get(strength, 0)


def _max_strength(strengths: Sequence[str]) -> str:
    if not strengths:
        return "weak"
    return max(strengths, key=_strength_rank)


def _decompile_flogic(
    flogic: FLogicCompilation,
    *,
    diagnostics: list[ClarificationRequirement],
    alternatives: list[ReconstructionAlternative],
    allow_alternatives: bool,
) -> tuple[ReconstructedComponent, ...]:
    roles: dict[str, str] = {}
    sources: dict[str, set[str]] = {}
    parents: dict[str, str] = {}
    children: dict[str, list[str]] = {}
    role_conflicts: dict[str, set[str]] = {}

    for fact in flogic.facts:
        if fact.predicate == "ui_component" and len(fact.args) >= 2:
            cid, role = fact.args[0], fact.args[1]
            if cid in roles and roles[cid] != role:
                role_conflicts.setdefault(cid, {roles[cid]}).add(role)
            else:
                roles[cid] = role
            sources.setdefault(cid, set()).update(fact.source_ref_ids)
        elif fact.predicate == "ui_parent" and len(fact.args) >= 2:
            parent, child = fact.args[0], fact.args[1]
            if child in parents and parents[child] != parent:
                diagnostics.append(
                    ClarificationRequirement(
                        code="parent.ambiguous",
                        message=(
                            f"Component {child!r} has multiple parent facts "
                            f"({parents[child]!r} vs {parent!r})"
                        ),
                        related_symbols=(child, parents[child], parent),
                    )
                )
                if allow_alternatives:
                    alternatives.append(
                        ReconstructionAlternative(
                            alternative_id=f"parent:{child}",
                            subject=child,
                            description="Multiple parent candidates",
                            candidates=tuple(
                                sorted({parents[child], parent})
                            ),
                        )
                    )
            else:
                parents[child] = parent
            sources.setdefault(child, set()).update(fact.source_ref_ids)
            sources.setdefault(parent, set()).update(fact.source_ref_ids)
        elif fact.predicate == "ui_contains" and len(fact.args) >= 2:
            parent, child = fact.args[0], fact.args[1]
            children.setdefault(parent, [])
            if child not in children[parent]:
                children[parent].append(child)
            sources.setdefault(parent, set()).update(fact.source_ref_ids)
            sources.setdefault(child, set()).update(fact.source_ref_ids)

    for cid, conflict_roles in sorted(role_conflicts.items()):
        diagnostics.append(
            ClarificationRequirement(
                code="role.ambiguous",
                message=(
                    f"Component {cid!r} has conflicting roles: "
                    f"{', '.join(sorted(conflict_roles))}"
                ),
                related_symbols=(cid, *sorted(conflict_roles)),
            )
        )
        if allow_alternatives:
            alternatives.append(
                ReconstructionAlternative(
                    alternative_id=f"role:{cid}",
                    subject=cid,
                    description="Conflicting role candidates",
                    candidates=tuple(sorted(conflict_roles)),
                )
            )

    components: list[ReconstructedComponent] = []
    for cid in sorted(roles):
        disposition = ReconstructionDisposition.GROUNDED
        if cid in role_conflicts or (
            cid in parents
            and any(c.code == "parent.ambiguous" and cid in c.related_symbols for c in diagnostics)
        ):
            disposition = ReconstructionDisposition.AMBIGUOUS
        components.append(
            ReconstructedComponent(
                component_id=cid,
                role=roles[cid],
                parent_id=parents.get(cid, ""),
                child_ids=tuple(children.get(cid, ())),
                source_ref_ids=tuple(sorted(sources.get(cid, ()))),
                disposition=disposition,
            )
        )

    # Parent/contains references to unknown components require clarification;
    # do not invent the missing component.
    known = set(roles)
    for child, parent in parents.items():
        if parent not in known:
            diagnostics.append(
                ClarificationRequirement(
                    code="component.missing",
                    message=(
                        f"Parent component {parent!r} referenced but not "
                        "declared by ui_component fact; will not invent it"
                    ),
                    related_symbols=(parent, child),
                    severity="error",
                )
            )
    for parent, kids in children.items():
        if parent not in known:
            diagnostics.append(
                ClarificationRequirement(
                    code="component.missing",
                    message=(
                        f"Container component {parent!r} referenced but not "
                        "declared by ui_component fact; will not invent it"
                    ),
                    related_symbols=(parent, *kids),
                    severity="error",
                )
            )
        for kid in kids:
            if kid not in known:
                diagnostics.append(
                    ClarificationRequirement(
                        code="component.missing",
                        message=(
                            f"Child component {kid!r} referenced but not "
                            "declared by ui_component fact; will not invent it"
                        ),
                        related_symbols=(parent, kid),
                        severity="error",
                    )
                )
    return tuple(components)


def _decompile_tdfol(
    tdfol: TDFOLCompilation,
    *,
    diagnostics: list[ClarificationRequirement],
    alternatives: list[ReconstructionAlternative],
    allow_alternatives: bool,
) -> tuple[tuple[ReconstructedNorm, ...], tuple[ReconstructedAction, ...]]:
    norms: list[ReconstructedNorm] = []
    by_action: dict[str, list[ReconstructedNorm]] = {}

    for formula in tdfol.formulas:
        action_id = _extract_action_id(formula.proposition)
        # Never invent an action id when the proposition is unparseable.
        if not action_id:
            diagnostics.append(
                ClarificationRequirement(
                    code="norm.unparseable",
                    message=(
                        f"Cannot extract action from proposition "
                        f"{formula.proposition!r} without inventing symbols"
                    ),
                    related_symbols=(formula.operator, formula.proposition),
                )
            )
            continue
        norm = ReconstructedNorm(
            operator=formula.operator,
            proposition=formula.proposition,
            strength=formula.strength,
            action_id=action_id,
            source_ref_ids=tuple(formula.source_ref_ids),
            disposition=ReconstructionDisposition.GROUNDED,
        )
        norms.append(norm)
        by_action.setdefault(action_id, []).append(norm)

    actions: list[ReconstructedAction] = []
    for action_id in sorted(by_action):
        action_norms = by_action[action_id]
        operators = tuple(sorted({n.operator for n in action_norms}))
        strengths = [n.strength for n in action_norms]
        max_str = _max_strength(strengths)
        source_refs: set[str] = set()
        for n in action_norms:
            source_refs.update(n.source_ref_ids)

        requires_confirmation = any(
            n.operator in {"obligation", "prohibition"}
            and ("confirm(" in n.proposition)
            for n in action_norms
        )
        has_permission = "permission" in operators
        has_strict_prohibition = any(
            n.operator == "prohibition" and n.strength == "strict"
            for n in action_norms
        )
        disposition = ReconstructionDisposition.GROUNDED
        # Ambiguous: both weak permission and strict invoke prohibition without
        # confirmation scaffolding is an unusual combination needing review.
        if has_permission and has_strict_prohibition and not requires_confirmation:
            if any("weaken_norm" in n.proposition for n in action_norms) and all(
                "weaken_norm" in n.proposition or n.operator == "permission"
                for n in action_norms
                if n.operator in {"permission", "prohibition"}
            ):
                # Normal permission + non-weakening prohibition pair.
                disposition = ReconstructionDisposition.GROUNDED
            else:
                disposition = ReconstructionDisposition.AMBIGUOUS
                diagnostics.append(
                    ClarificationRequirement(
                        code="norm.ambiguous",
                        message=(
                            f"Action {action_id!r} mixes permission with strict "
                            "prohibition; clarify intended deontic posture"
                        ),
                        related_symbols=(action_id,),
                    )
                )
                if allow_alternatives:
                    alternatives.append(
                        ReconstructionAlternative(
                            alternative_id=f"norm:{action_id}",
                            subject=action_id,
                            description="Permission vs prohibition alternatives",
                            candidates=operators,
                        )
                    )

        actions.append(
            ReconstructedAction(
                action_id=action_id,
                operators=operators,
                max_strength=max_str,
                requires_confirmation=requires_confirmation,
                source_ref_ids=tuple(sorted(source_refs)),
                invented_grants=(),
                disposition=disposition,
            )
        )

    norms_sorted = tuple(
        sorted(norms, key=lambda n: (n.operator, n.proposition, n.action_id))
    )
    return norms_sorted, tuple(actions)


def _decompile_event_calculus(
    event_calculus: EventCalculusCompilation,
    *,
    diagnostics: list[ClarificationRequirement],
) -> tuple[tuple[ReconstructedState, ...], tuple[ReconstructedTransition, ...]]:
    states: dict[str, ReconstructedState] = {}
    transitions: list[ReconstructedTransition] = []
    timeouts: dict[str, int] = {}

    for formula in event_calculus.formulas:
        if formula.kind == "fluent" and formula.args:
            m = _IN_STATE_RE.match(formula.args[0])
            if m:
                sid = m.group(1)
                states[sid] = ReconstructedState(state_id=sid)
            else:
                diagnostics.append(
                    ClarificationRequirement(
                        code="fluent.unparseable",
                        message=(
                            f"Fluent {formula.args[0]!r} is not a recognized "
                            "in_state form; will not invent a state"
                        ),
                        related_symbols=formula.args,
                    )
                )
        elif formula.kind == "happens" and formula.args:
            head = formula.args[0]
            tm = _TIMEOUT_RE.match(head)
            if tm and len(formula.args) >= 2:
                try:
                    timeouts[tm.group(1)] = int(formula.args[1])
                except ValueError:
                    diagnostics.append(
                        ClarificationRequirement(
                            code="timeout.unparseable",
                            message=f"Timeout value {formula.args[1]!r} is not an int",
                            related_symbols=(head, formula.args[1]),
                        )
                    )
            elif len(formula.args) >= 3:
                event_id = head
                *sources, target = formula.args[1:]
                transitions.append(
                    ReconstructedTransition(
                        event_id=event_id,
                        source_state_ids=tuple(sources),
                        target_state_id=target,
                    )
                )
                for sid in sources:
                    states.setdefault(sid, ReconstructedState(state_id=sid))
                states.setdefault(target, ReconstructedState(state_id=target))
            else:
                diagnostics.append(
                    ClarificationRequirement(
                        code="happens.incomplete",
                        message=(
                            f"happens formula {formula.args!r} lacks source/target "
                            "states; will not invent them"
                        ),
                        related_symbols=formula.args,
                    )
                )
        elif formula.kind in {"initiates", "terminates"}:
            # Used to corroborate transitions; do not invent extra states.
            if formula.args and len(formula.args) >= 2:
                m = _IN_STATE_RE.match(formula.args[1])
                if m:
                    states.setdefault(
                        m.group(1), ReconstructedState(state_id=m.group(1))
                    )

    # Attach timeouts by transition id when present as timeout(transition_id).
    if timeouts:
        updated: list[ReconstructedTransition] = []
        for tr in transitions:
            # timeout keys are transition ids from compiler; event may differ.
            ms = timeouts.get(tr.event_id)
            if ms is None:
                # try matching any remaining timeout when single transition
                ms = None
            updated.append(
                ReconstructedTransition(
                    event_id=tr.event_id,
                    source_state_ids=tr.source_state_ids,
                    target_state_id=tr.target_state_id,
                    timeout_ms=ms,
                    disposition=tr.disposition,
                )
            )
        # If timeout keys look like transition ids not event ids, attach when
        # there is exactly one timeout and one transition.
        if len(timeouts) == 1 and len(updated) == 1 and updated[0].timeout_ms is None:
            only_ms = next(iter(timeouts.values()))
            tr0 = updated[0]
            updated[0] = ReconstructedTransition(
                event_id=tr0.event_id,
                source_state_ids=tr0.source_state_ids,
                target_state_id=tr0.target_state_id,
                timeout_ms=only_ms,
                disposition=tr0.disposition,
            )
        transitions = updated

    return (
        tuple(sorted(states.values(), key=lambda s: s.state_id)),
        tuple(
            sorted(
                transitions,
                key=lambda t: (t.event_id, t.target_state_id, t.source_state_ids),
            )
        ),
    )


def _decompile_dcec(
    dcec: DCECCompilation,
    *,
    diagnostics: list[ClarificationRequirement],
    alternatives: list[ReconstructionAlternative],
    allow_alternatives: bool,
) -> tuple[ReconstructedCognitive, ...]:
    items: list[ReconstructedCognitive] = []
    for formula in dcec.formulas:
        disposition = ReconstructionDisposition.GROUNDED
        if formula.kind == "intends" and formula.content.startswith("maybe_intent("):
            disposition = ReconstructionDisposition.AMBIGUOUS
            diagnostics.append(
                ClarificationRequirement(
                    code="intent.ambiguous",
                    message=(
                        f"Human observation {formula.content!r} is only a "
                        "candidate intent; confirmation required"
                    ),
                    related_symbols=(formula.actor, formula.content),
                )
            )
            if allow_alternatives:
                alternatives.append(
                    ReconstructionAlternative(
                        alternative_id=f"intent:{formula.content}",
                        subject=formula.actor,
                        description="Candidate human intent vs no-intent",
                        candidates=(
                            formula.content,
                            f"not_intent({formula.content[len('maybe_intent('):-1]})",
                        ),
                    )
                )
        elif formula.kind == "believes" and "not_auto_intent" in formula.content:
            # Agent proposals must not be promoted to user intent.
            disposition = ReconstructionDisposition.GROUNDED
        elif formula.kind == "knows":
            # DCEC leaf never emits knows without evidence; if present, keep it.
            disposition = ReconstructionDisposition.GROUNDED
        items.append(
            ReconstructedCognitive(
                kind=formula.kind,
                actor=formula.actor,
                content=formula.content,
                disposition=disposition,
            )
        )
    return tuple(sorted(items, key=lambda c: (c.kind, c.actor, c.content)))


def _collect_unsupported(
    artifact: UIFormalizationArtifact,
) -> tuple[str, ...]:
    chunks: list[str] = list(artifact.unsupported_semantics)
    for view_name, compilation in (
        ("flogic", artifact.flogic),
        ("event_calculus", artifact.event_calculus),
        ("tdfol", artifact.tdfol),
        ("dcec", artifact.dcec),
    ):
        if compilation is None:
            chunks.append(f"view_absent:{view_name}")
        else:
            chunks.extend(compilation.unsupported)
    # Always exclude source/pixel recovery.
    chunks.extend(
        (
            "source_code_equality",
            "pixel_equality",
            "framework_widget_class_recovery",
            "executable_callback_recovery",
            "authority_grant_invention",
            "device_capability_invention",
        )
    )
    seen: set[str] = set()
    out: list[str] = []
    for item in chunks:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _build_loss(
    artifact: UIFormalizationArtifact,
    unsupported: Sequence[str],
) -> tuple[ReconstructionLossItem, ...]:
    items: list[ReconstructionLossItem] = []
    for u in unsupported:
        category = "out_of_scope" if u in {
            "source_code_equality",
            "pixel_equality",
            "framework_widget_class_recovery",
            "executable_callback_recovery",
        } else "unsupported"
        items.append(
            ReconstructionLossItem(
                semantic_id=u,
                category=category,
                reason=f"explicit reconstruction disposition for {u}",
            )
        )
    for receipt in artifact.coverage:
        if receipt.kind in {"unsupported", "intentionally_non_formal", "approximated"}:
            items.append(
                ReconstructionLossItem(
                    semantic_id=receipt.source_semantic_id,
                    category=receipt.kind,
                    reason=receipt.notes or f"coverage kind {receipt.kind}",
                )
            )
    # Stable order.
    return tuple(
        sorted(items, key=lambda i: (i.category, i.semantic_id, i.reason))
    )


def _verify_no_grants(payload: Mapping[str, Any], path: str = "") -> list[str]:
    rejected: list[str] = []
    for key, value in payload.items():
        lowered = key.lower()
        full = f"{path}/{key}" if path else key
        if lowered in _FORBIDDEN_GRANT_KEYS:
            rejected.append(full)
        if isinstance(value, Mapping):
            rejected.extend(_verify_no_grants(value, full))
    return rejected


def decompile_ui_formalization(
    artifact: UIFormalizationArtifact,
    request: DecompilationRequest | None = None,
) -> UIReconstructionArtifact:
    """Reconstruct supported UI semantics from a multi-view formalization artifact.

    Never invents sources, grants, components, actions, or device capabilities.
    Ambiguous formal input yields alternatives and/or clarification requirements.
    Strict deontic norms are preserved at their declared strength.
    """

    if not isinstance(artifact, UIFormalizationArtifact):
        raise UIIRValidationError(
            "decompile_ui_formalization requires a UIFormalizationArtifact"
        )
    req = request or DecompilationRequest()
    if not req.request_id.strip():
        raise UIIRValidationError("DecompilationRequest.request_id must not be empty")

    clarifications: list[ClarificationRequirement] = []
    alternatives: list[ReconstructionAlternative] = []
    rejected_inventions: list[str] = []

    components: tuple[ReconstructedComponent, ...] = ()
    if artifact.flogic is not None:
        components = _decompile_flogic(
            artifact.flogic,
            diagnostics=clarifications,
            alternatives=alternatives,
            allow_alternatives=req.allow_alternatives,
        )
    else:
        clarifications.append(
            ClarificationRequirement(
                code="view.absent",
                message="F-logic view absent; no components reconstructed",
                related_symbols=(),
                severity="info",
            )
        )

    norms: tuple[ReconstructedNorm, ...] = ()
    actions: tuple[ReconstructedAction, ...] = ()
    if artifact.tdfol is not None:
        norms, actions = _decompile_tdfol(
            artifact.tdfol,
            diagnostics=clarifications,
            alternatives=alternatives,
            allow_alternatives=req.allow_alternatives,
        )
    else:
        clarifications.append(
            ClarificationRequirement(
                code="view.absent",
                message="TDFOL view absent; no norms/actions reconstructed",
                related_symbols=(),
                severity="info",
            )
        )

    states: tuple[ReconstructedState, ...] = ()
    transitions: tuple[ReconstructedTransition, ...] = ()
    if artifact.event_calculus is not None:
        states, transitions = _decompile_event_calculus(
            artifact.event_calculus,
            diagnostics=clarifications,
        )
    else:
        clarifications.append(
            ClarificationRequirement(
                code="view.absent",
                message="Event-calculus view absent; no behavior reconstructed",
                related_symbols=(),
                severity="info",
            )
        )

    cognitive: tuple[ReconstructedCognitive, ...] = ()
    if artifact.dcec is not None:
        cognitive = _decompile_dcec(
            artifact.dcec,
            diagnostics=clarifications,
            alternatives=alternatives,
            allow_alternatives=req.allow_alternatives,
        )
    else:
        clarifications.append(
            ClarificationRequirement(
                code="view.absent",
                message="DCEC view absent; no cognitive formulas reconstructed",
                related_symbols=(),
                severity="info",
            )
        )

    # Accessibility roles: only from reconstructed components (never invented).
    accessibility_roles = MappingProxyType(
        {c.component_id: c.role for c in components}
    )
    # Essential modality: pass through seed only; never invent device capability.
    essential_modality = tuple(
        sorted({c for c in req.essential_modality_capability_ids if c.strip()})
    )
    # Reject any attempt to treat seed modality as invented device grants.
    for cap in essential_modality:
        if cap.lower() in _FORBIDDEN_GRANT_KEYS:
            rejected_inventions.append(f"device_capability:{cap}")
            essential_modality = tuple(
                c for c in essential_modality if c != cap
            )

    # Accessibility survival relative to requested component ids.
    accessibility_survived = True
    if req.accessibility_component_ids:
        known = {c.component_id for c in components}
        missing = [
            cid
            for cid in req.accessibility_component_ids
            if cid not in known
        ]
        if missing:
            accessibility_survived = False
            clarifications.append(
                ClarificationRequirement(
                    code="accessibility.missing",
                    message=(
                        "Accessibility-bound components not reconstructable "
                        f"from formal views: {', '.join(missing)}"
                    ),
                    related_symbols=tuple(missing),
                    severity="error",
                )
            )

    # Essential modality survival: seeds survive only as explicit pass-through
    # (decompiler never fabricates capabilities).
    essential_modality_survived = True
    if req.essential_modality_capability_ids:
        seed = {c for c in req.essential_modality_capability_ids if c.strip()}
        kept = set(essential_modality)
        if seed - kept:
            essential_modality_survived = False

    # Source grounding: only refs that appear on formal facts/formulas or
    # the artifact source_map. Seed map may *filter* but never invent.
    formal_sources: set[str] = set()
    for refs in artifact.source_map.values():
        formal_sources.update(refs)  # values are views, keys are source refs
    formal_sources.update(artifact.source_map.keys())
    if artifact.flogic is not None:
        for fact in artifact.flogic.facts:
            formal_sources.update(fact.source_ref_ids)
    if artifact.tdfol is not None:
        for formula in artifact.tdfol.formulas:
            formal_sources.update(formula.source_ref_ids)
    if artifact.event_calculus is not None:
        for formula in artifact.event_calculus.formulas:
            formal_sources.update(formula.source_ref_ids)
    if artifact.dcec is not None:
        for formula in artifact.dcec.formulas:
            formal_sources.update(formula.source_ref_ids)

    invented_sources: list[str] = []
    for c in components:
        for ref in c.source_ref_ids:
            if ref not in formal_sources and ref not in set(
                sum((list(v) for v in req.seed_source_map.values()), [])
            ) | set(req.seed_source_map.keys()):
                # Source ref on fact but not in formal set is still grounded by
                # the fact itself; formal_sources includes fact refs above.
                invented_sources.append(ref)

    # Deontic non-weakening: reconstructed strict norms must retain strict strength.
    deontic_non_weakening = True
    if artifact.tdfol is not None:
        original_strict = {
            (f.operator, f.proposition): f.strength
            for f in artifact.tdfol.formulas
            if f.strength == "strict"
            and f.operator in {"obligation", "prohibition"}
        }
        reconstructed = {
            (n.operator, n.proposition): n.strength for n in norms
        }
        for key, strength in original_strict.items():
            recon_strength = reconstructed.get(key)
            if recon_strength is None:
                deontic_non_weakening = False
                clarifications.append(
                    ClarificationRequirement(
                        code="deontic.dropped",
                        message=(
                            f"Strict {key[0]} {key[1]!r} missing from reconstruction"
                        ),
                        related_symbols=(key[0], key[1]),
                        severity="error",
                    )
                )
            elif _strength_rank(recon_strength) < _strength_rank(strength):
                deontic_non_weakening = False
                clarifications.append(
                    ClarificationRequirement(
                        code="deontic.weakened",
                        message=(
                            f"Strict {key[0]} {key[1]!r} weakened to {recon_strength!r}"
                        ),
                        related_symbols=(key[0], key[1]),
                        severity="error",
                    )
                )

    # Ensure reconstruction payload carries no grant invention.
    grant_scan_payload: dict[str, Any] = {
        "actions": [
            {
                "action_id": a.action_id,
                "invented_grants": list(a.invented_grants),
            }
            for a in actions
        ],
    }
    rejected_inventions.extend(_verify_no_grants(grant_scan_payload))

    unsupported = _collect_unsupported(artifact)
    loss = _build_loss(artifact, unsupported)

    source_grounding_preserved = not invented_sources
    faithful = (
        deontic_non_weakening
        and source_grounding_preserved
        and not rejected_inventions
        and accessibility_survived
        and essential_modality_survived
    )

    receipt = ReconstructionReceipt(
        receipt_id=f"receipt:{req.request_id}",
        faithful=faithful,
        source_grounding_preserved=source_grounding_preserved,
        deontic_non_weakening=deontic_non_weakening,
        invented_sources=tuple(sorted(set(invented_sources))),
        invented_grants=(),
        invented_components=(),
        invented_actions=(),
        invented_device_capabilities=(),
        rejected_inventions=tuple(sorted(set(rejected_inventions))),
        accessibility_survived=accessibility_survived,
        essential_modality_survived=essential_modality_survived,
        claims_source_equality=False,
        claims_pixel_equality=False,
        notes=(
            "Semantic reconstruction only; source-code and pixel equality "
            "are excluded from the claim surface."
        ),
    )

    return UIReconstructionArtifact(
        reconstruction_id=f"recon:{req.request_id}:{artifact.artifact_id}",
        decompiler_id=UI_FORMAL_DECOMPILER_ID,
        source_artifact_id=artifact.artifact_id,
        components=components,
        actions=actions,
        norms=norms,
        states=states,
        transitions=transitions,
        cognitive=cognitive,
        alternatives=tuple(alternatives),
        clarifications=tuple(clarifications),
        loss=loss,
        unsupported=unsupported,
        accessibility_roles=accessibility_roles,
        essential_modality_capability_ids=essential_modality,
        receipt=receipt,
        result_authority=ResultAuthority.ADVISORY,
    )


__all__ = [
    "ClarificationRequirement",
    "DecompilationRequest",
    "ReconstructionAlternative",
    "ReconstructionDisposition",
    "ReconstructionLossItem",
    "ReconstructionReceipt",
    "ReconstructedAction",
    "ReconstructedCognitive",
    "ReconstructedComponent",
    "ReconstructedNorm",
    "ReconstructedState",
    "ReconstructedTransition",
    "UI_FORMAL_DECOMPILER_ID",
    "UI_FORMAL_DECOMPILER_INTERFACE",
    "UI_RECONSTRUCTION_ARTIFACT_INTERFACE",
    "UI_RECONSTRUCTION_ARTIFACT_SCHEMA",
    "UIReconstructionArtifact",
    "decompile_ui_formalization",
]
