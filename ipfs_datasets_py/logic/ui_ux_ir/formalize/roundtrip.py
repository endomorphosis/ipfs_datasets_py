"""Layered semantic round-trip equivalence for UI/UX IR (UIR-026).

``UISemanticRoundTrip@1`` evaluates reconstruction quality in reviewed layers:

1. canonical identity for unchanged declarations;
2. graph isomorphism for semantic component graphs;
3. state-machine trace equivalence over bounded generated traces;
4. formula equivalence / mutual coverage for supported formal fragments;
5. deontic non-weakening for permissions, prohibitions, and obligations;
6. accessibility role/name/action equivalence;
7. modality coverage and fallback equivalence; and
8. declared projection/reconstruction loss below a reviewed threshold.

Source-code equality and pixel equality are **explicitly excluded** from the
equivalence claim surface and never appear as evaluated layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Sequence

from ..model.behavior import BehaviorModel
from ..model.bindings import UIActionBinding
from ..model.components import UIComponentGraph
from ..model.experience import ExperienceModel
from ..model.modality import UIModalityContract
from ..runtime.events import CanonicalInteractionEvent
from ..schema import UIIRValidationError
from .compiler import FormalizationInputs, UIFormalizationArtifact, compile_ui_formalization
from .decompiler import (
    DecompilationRequest,
    UIReconstructionArtifact,
    decompile_ui_formalization,
)
from .tdfol import compile_action_bindings_to_tdfol

UI_SEMANTIC_ROUNDTRIP_INTERFACE: Final = "UISemanticRoundTrip@1"
UI_SEMANTIC_ROUNDTRIP_ID: Final = "ui-ux-ir/semantic-roundtrip@1"
UI_SEMANTIC_ROUNDTRIP_REPORT_SCHEMA: Final = "ui-semantic-roundtrip-report/v1"

# Layers that are never part of the supported claim surface.
EXCLUDED_EQUIVALENCE_CLAIMS: Final = (
    "source_equality",
    "pixel_equality",
)


class EquivalenceLayer(str, Enum):
    """Supported layered equivalence checks (source/pixel excluded)."""

    CANONICAL_IDENTITY = "canonical_identity"
    GRAPH_ISOMORPHISM = "graph_isomorphism"
    TRACE_EQUIVALENCE = "trace_equivalence"
    FORMULA_EQUIVALENCE = "formula_equivalence"
    DEONTIC_NON_WEAKENING = "deontic_non_weakening"
    ACCESSIBILITY = "accessibility"
    MODALITY_COVERAGE = "modality_coverage"
    DECLARED_LOSS = "declared_loss"


@dataclass(frozen=True, slots=True)
class SemanticRoundTripPolicy:
    """Reviewed policy for layered semantic round-trip evaluation."""

    policy_id: str = "ui-roundtrip/default"
    max_trace_depth: int = 8
    max_loss_items: int | None = None  # None = no numeric cap beyond explicit loss
    require_deontic_non_weakening: bool = True
    require_accessibility: bool = True
    require_modality: bool = True
    require_graph_isomorphism: bool = True
    require_trace_equivalence: bool = True
    require_formula_equivalence: bool = True
    # Hard-locked exclusions — cannot be enabled.
    evaluate_source_equality: bool = False
    evaluate_pixel_equality: bool = False

    def __post_init__(self) -> None:
        # Force exclusions even if a caller attempts to enable them.
        object.__setattr__(self, "evaluate_source_equality", False)
        object.__setattr__(self, "evaluate_pixel_equality", False)
        if self.max_trace_depth < 1:
            raise UIIRValidationError(
                "SemanticRoundTripPolicy.max_trace_depth must be >= 1"
            )


@dataclass(frozen=True, slots=True)
class RoundTripDocument:
    """Semantic document snapshot for compile → decompile → compare.

    This is the round-trip input surface for formalize-owned semantics. A full
    envelope ``UIIRDocument`` is not required; callers provide the models that
    the formalization compilers accept plus optional experience/modality seeds.
    """

    document_id: str
    component_graph: UIComponentGraph | None = None
    behavior_model: BehaviorModel | None = None
    action_bindings: tuple[UIActionBinding, ...] = ()
    events: tuple[CanonicalInteractionEvent, ...] = ()
    experience: ExperienceModel | None = None
    modality: UIModalityContract | None = None
    actor_id: str = "user"


@dataclass(frozen=True, slots=True)
class LayerResult:
    """Outcome of one equivalence layer."""

    layer: EquivalenceLayer
    passed: bool
    details: str
    counterexamples: tuple[str, ...] = ()
    evaluated: bool = True


@dataclass(frozen=True, slots=True)
class SemanticRoundTripReport:
    """Layered equivalence evaluation artifact."""

    report_id: str
    document_id: str
    policy_id: str
    overall_passed: bool
    layers: tuple[LayerResult, ...]
    reconstruction: UIReconstructionArtifact | None
    formalization: UIFormalizationArtifact | None
    excluded_claims: tuple[str, ...] = EXCLUDED_EQUIVALENCE_CLAIMS
    counterexamples: tuple[str, ...] = ()
    interface: str = UI_SEMANTIC_ROUNDTRIP_INTERFACE
    schema_version: str = UI_SEMANTIC_ROUNDTRIP_REPORT_SCHEMA
    roundtrip_id: str = UI_SEMANTIC_ROUNDTRIP_ID


def _as_document(document: RoundTripDocument | FormalizationInputs) -> RoundTripDocument:
    if isinstance(document, RoundTripDocument):
        return document
    if isinstance(document, FormalizationInputs):
        return RoundTripDocument(
            document_id=document.artifact_id or "formalization-inputs",
            component_graph=document.component_graph,
            behavior_model=document.behavior_model,
            action_bindings=document.action_bindings,
            events=document.events,
            actor_id=document.actor_id,
        )
    raise UIIRValidationError(
        "roundtrip_ui_ir requires RoundTripDocument or FormalizationInputs"
    )


def _canonical_identity(
    document: RoundTripDocument,
    reconstruction: UIReconstructionArtifact,
) -> LayerResult:
    counterexamples: list[str] = []
    details_parts: list[str] = []

    if document.component_graph is not None:
        orig = {c.component_id for c in document.component_graph.components}
        recon = {c.component_id for c in reconstruction.components}
        missing = sorted(orig - recon)
        extra = sorted(recon - orig)
        if missing:
            counterexamples.extend(f"component.missing:{m}" for m in missing)
        if extra:
            # Extra would imply invention; decompiler should not produce extras
            # beyond formal facts derived from original.
            counterexamples.extend(f"component.extra:{e}" for e in extra)
        details_parts.append(
            f"components orig={len(orig)} recon={len(recon)}"
        )

    if document.action_bindings:
        orig_actions = {b.action_id for b in document.action_bindings}
        recon_actions = {a.action_id for a in reconstruction.actions}
        missing_a = sorted(orig_actions - recon_actions)
        if missing_a:
            counterexamples.extend(f"action.missing:{m}" for m in missing_a)
        details_parts.append(
            f"actions orig={len(orig_actions)} recon={len(recon_actions)}"
        )

    if document.behavior_model is not None:
        orig_states = {s.state_id for s in document.behavior_model.states}
        recon_states = {s.state_id for s in reconstruction.states}
        missing_s = sorted(orig_states - recon_states)
        if missing_s:
            counterexamples.extend(f"state.missing:{m}" for m in missing_s)
        details_parts.append(
            f"states orig={len(orig_states)} recon={len(recon_states)}"
        )

    if not details_parts:
        details_parts.append("no identity-bearing inputs provided")

    return LayerResult(
        layer=EquivalenceLayer.CANONICAL_IDENTITY,
        passed=not counterexamples,
        details="; ".join(details_parts),
        counterexamples=tuple(counterexamples),
    )


def _graph_isomorphism(
    document: RoundTripDocument,
    reconstruction: UIReconstructionArtifact,
) -> LayerResult:
    if document.component_graph is None:
        return LayerResult(
            layer=EquivalenceLayer.GRAPH_ISOMORPHISM,
            passed=True,
            details="skipped: no component_graph",
            evaluated=False,
        )

    counterexamples: list[str] = []
    orig_nodes = {
        c.component_id: c.role for c in document.component_graph.components
    }
    recon_nodes = {
        c.component_id: c.role for c in reconstruction.components
    }
    if set(orig_nodes) != set(recon_nodes):
        counterexamples.append(
            f"node_set_mismatch:orig={sorted(orig_nodes)}:"
            f"recon={sorted(recon_nodes)}"
        )
    for cid, role in orig_nodes.items():
        if cid in recon_nodes and recon_nodes[cid] != role:
            counterexamples.append(
                f"role_mismatch:{cid}:{role}->{recon_nodes[cid]}"
            )

    # Parent edges
    orig_parents = {
        c.component_id: c.parent_id
        for c in document.component_graph.components
        if c.parent_id
    }
    recon_parents = {
        c.component_id: c.parent_id
        for c in reconstruction.components
        if c.parent_id
    }
    for cid, parent in orig_parents.items():
        if recon_parents.get(cid) != parent:
            counterexamples.append(
                f"parent_mismatch:{cid}:{parent}->{recon_parents.get(cid, '')}"
            )

    # Containment edges from child_ids
    orig_contains: set[tuple[str, str]] = set()
    for c in document.component_graph.components:
        for child in c.child_ids:
            orig_contains.add((c.component_id, child))
    recon_contains: set[tuple[str, str]] = set()
    for c in reconstruction.components:
        for child in c.child_ids:
            recon_contains.add((c.component_id, child))
    if orig_contains != recon_contains:
        missing = sorted(orig_contains - recon_contains)
        extra = sorted(recon_contains - orig_contains)
        if missing:
            counterexamples.append(f"contains.missing:{missing}")
        if extra:
            counterexamples.append(f"contains.extra:{extra}")

    return LayerResult(
        layer=EquivalenceLayer.GRAPH_ISOMORPHISM,
        passed=not counterexamples,
        details=(
            f"nodes={len(orig_nodes)} parent_edges={len(orig_parents)} "
            f"contains_edges={len(orig_contains)}"
        ),
        counterexamples=tuple(counterexamples),
    )


def _generate_bounded_traces(
    model: BehaviorModel,
    *,
    max_depth: int,
) -> tuple[tuple[str, ...], ...]:
    """Generate bounded event sequences from the behavior model."""

    by_source: dict[str, list[tuple[str, str]]] = {}
    for transition in model.transitions:
        event = transition.event_id or transition.transition_id
        for source in transition.source_state_ids:
            by_source.setdefault(source, []).append(
                (event, transition.target_state_id)
            )

    traces: list[tuple[str, ...]] = []

    def walk(state: str, path: list[str], depth: int) -> None:
        if depth >= max_depth:
            traces.append(tuple(path))
            return
        options = by_source.get(state, [])
        if not options:
            traces.append(tuple(path))
            return
        for event, target in options:
            walk(target, path + [event], depth + 1)

    for initial in model.initial_state_ids:
        walk(initial, [], 0)

    # Deterministic unique traces.
    return tuple(sorted(set(traces)))


def _trace_equivalence(
    document: RoundTripDocument,
    reconstruction: UIReconstructionArtifact,
    *,
    max_depth: int,
) -> LayerResult:
    if document.behavior_model is None:
        return LayerResult(
            layer=EquivalenceLayer.TRACE_EQUIVALENCE,
            passed=True,
            details="skipped: no behavior_model",
            evaluated=False,
        )

    counterexamples: list[str] = []
    orig_traces = _generate_bounded_traces(
        document.behavior_model, max_depth=max_depth
    )

    # Build adjacency from reconstructed transitions.
    recon_adj: dict[str, list[tuple[str, str]]] = {}
    for tr in reconstruction.transitions:
        for source in tr.source_state_ids:
            recon_adj.setdefault(source, []).append(
                (tr.event_id, tr.target_state_id)
            )

    # Initial states: prefer original initials that appear in reconstruction.
    recon_state_ids = {s.state_id for s in reconstruction.states}
    initials = [
        s
        for s in document.behavior_model.initial_state_ids
        if s in recon_state_ids
    ]
    if not initials and recon_state_ids:
        # Cannot invent initials; require clarification via counterexample.
        counterexamples.append("initial_state.unrecoverable")

    def accepts(trace: Sequence[str]) -> bool:
        if not initials and not trace:
            return True
        if not initials:
            return False
        # BFS-like: any initial that can consume the full trace.
        frontiers = set(initials)
        for event in trace:
            nxt: set[str] = set()
            for state in frontiers:
                for ev, target in recon_adj.get(state, []):
                    if ev == event:
                        nxt.add(target)
            if not nxt:
                return False
            frontiers = nxt
        return True

    for trace in orig_traces:
        if not accepts(trace):
            counterexamples.append(f"trace.rejected:{','.join(trace) or '<epsilon>'}")

    return LayerResult(
        layer=EquivalenceLayer.TRACE_EQUIVALENCE,
        passed=not counterexamples,
        details=f"bounded_traces={len(orig_traces)} max_depth={max_depth}",
        counterexamples=tuple(counterexamples),
    )


def _formula_equivalence(
    document: RoundTripDocument,
    formalization: UIFormalizationArtifact,
    reconstruction: UIReconstructionArtifact,
) -> LayerResult:
    counterexamples: list[str] = []
    details: list[str] = []

    # Structural: every F-logic component fact has a reconstructed component.
    if formalization.flogic is not None:
        fact_components = {
            f.args[0]
            for f in formalization.flogic.facts
            if f.predicate == "ui_component" and f.args
        }
        recon = {c.component_id for c in reconstruction.components}
        missing = sorted(fact_components - recon)
        if missing:
            counterexamples.extend(f"flogic.missing:{m}" for m in missing)
        details.append(f"flogic_components={len(fact_components)}")

    # Deontic: re-derive norms from original bindings and compare operator sets.
    if document.action_bindings:
        original_tdfol = compile_action_bindings_to_tdfol(document.action_bindings)
        orig_keys = {
            (f.operator, f.proposition, f.strength) for f in original_tdfol.formulas
        }
        recon_keys = {
            (n.operator, n.proposition, n.strength) for n in reconstruction.norms
        }
        missing_n = sorted(orig_keys - recon_keys)
        if missing_n:
            for op, prop, strength in missing_n:
                counterexamples.append(f"formula.missing:{op}:{prop}:{strength}")
        details.append(
            f"tdfol_formulas orig={len(orig_keys)} recon={len(recon_keys)}"
        )

    if not details:
        details.append("no formal fragments to compare")

    return LayerResult(
        layer=EquivalenceLayer.FORMULA_EQUIVALENCE,
        passed=not counterexamples,
        details="; ".join(details),
        counterexamples=tuple(counterexamples),
    )


def _deontic_non_weakening(
    document: RoundTripDocument,
    reconstruction: UIReconstructionArtifact,
    *,
    required: bool,
) -> LayerResult:
    if not document.action_bindings:
        return LayerResult(
            layer=EquivalenceLayer.DEONTIC_NON_WEAKENING,
            passed=True,
            details="skipped: no action_bindings",
            evaluated=False,
        )

    original = compile_action_bindings_to_tdfol(document.action_bindings)
    counterexamples: list[str] = []
    strength_rank = {"weak": 1, "default": 2, "strict": 3}
    recon_map = {
        (n.operator, n.proposition): n.strength for n in reconstruction.norms
    }

    for formula in original.formulas:
        if formula.operator not in {"obligation", "prohibition"}:
            continue
        key = (formula.operator, formula.proposition)
        recon_strength = recon_map.get(key)
        if recon_strength is None:
            counterexamples.append(
                f"deontic.dropped:{formula.operator}:{formula.proposition}"
            )
            continue
        if strength_rank.get(recon_strength, 0) < strength_rank.get(
            formula.strength, 0
        ):
            counterexamples.append(
                f"deontic.weakened:{formula.operator}:{formula.proposition}:"
                f"{formula.strength}->{recon_strength}"
            )

    # Reconstruction receipt must also assert non-weakening.
    if not reconstruction.receipt.deontic_non_weakening:
        counterexamples.append("receipt.deontic_non_weakening=false")

    # Invented grants are a deontic/authority violation.
    if reconstruction.receipt.invented_grants:
        counterexamples.append(
            f"invented_grants:{list(reconstruction.receipt.invented_grants)}"
        )
    for action in reconstruction.actions:
        if action.invented_grants:
            counterexamples.append(
                f"action.invented_grants:{action.action_id}"
            )

    passed = not counterexamples
    if not required:
        return LayerResult(
            layer=EquivalenceLayer.DEONTIC_NON_WEAKENING,
            passed=True,
            details=f"advisory_only; issues={len(counterexamples)}",
            counterexamples=tuple(counterexamples),
            evaluated=True,
        )
    return LayerResult(
        layer=EquivalenceLayer.DEONTIC_NON_WEAKENING,
        passed=passed,
        details=f"strict_norms_checked={sum(1 for f in original.formulas if f.operator in {'obligation', 'prohibition'})}",
        counterexamples=tuple(counterexamples),
    )


def _accessibility_equivalence(
    document: RoundTripDocument,
    reconstruction: UIReconstructionArtifact,
    *,
    required: bool,
) -> LayerResult:
    counterexamples: list[str] = []
    details: list[str] = []

    if document.component_graph is not None:
        for component in document.component_graph.components:
            recon_role = reconstruction.accessibility_roles.get(
                component.component_id
            )
            if recon_role is None:
                counterexamples.append(
                    f"a11y.component_missing:{component.component_id}"
                )
            elif recon_role != component.role:
                counterexamples.append(
                    f"a11y.role_mismatch:{component.component_id}:"
                    f"{component.role}->{recon_role}"
                )
        details.append(
            f"component_roles={len(document.component_graph.components)}"
        )

    if document.experience is not None:
        recon_ids = {c.component_id for c in reconstruction.components}
        for binding in document.experience.accessible_names:
            if binding.component_id not in recon_ids:
                counterexamples.append(
                    f"a11y.name_binding_missing:{binding.component_id}"
                )
            if not binding.modality_alternative_ids:
                counterexamples.append(
                    f"a11y.modality_alternative_missing:{binding.component_id}"
                )
        details.append(
            f"accessible_names={len(document.experience.accessible_names)}"
        )

    if not details:
        details.append("no accessibility inputs provided")
        return LayerResult(
            layer=EquivalenceLayer.ACCESSIBILITY,
            passed=True,
            details="; ".join(details),
            evaluated=False,
        )

    if not reconstruction.receipt.accessibility_survived:
        counterexamples.append("receipt.accessibility_survived=false")

    passed = not counterexamples
    if not required:
        return LayerResult(
            layer=EquivalenceLayer.ACCESSIBILITY,
            passed=True,
            details=f"advisory_only; issues={len(counterexamples)}",
            counterexamples=tuple(counterexamples),
        )
    return LayerResult(
        layer=EquivalenceLayer.ACCESSIBILITY,
        passed=passed,
        details="; ".join(details),
        counterexamples=tuple(counterexamples),
    )


def _modality_coverage(
    document: RoundTripDocument,
    reconstruction: UIReconstructionArtifact,
    *,
    required: bool,
) -> LayerResult:
    if document.modality is None:
        return LayerResult(
            layer=EquivalenceLayer.MODALITY_COVERAGE,
            passed=True,
            details="skipped: no modality contract",
            evaluated=False,
        )

    counterexamples: list[str] = []
    essential: set[str] = set()
    for req in document.modality.requirements:
        if req.essential:
            essential.update(req.capability_ids)

    kept = set(reconstruction.essential_modality_capability_ids)
    missing = sorted(essential - kept)
    if missing:
        counterexamples.extend(f"modality.essential_missing:{m}" for m in missing)

    # Reconstruction must not invent device capabilities beyond the seed set.
    invented = sorted(kept - essential) if essential else []
    # Pass-through may include only essential seeds; extras would be invention.
    if invented:
        counterexamples.extend(
            f"modality.invented_capability:{c}" for c in invented
        )

    if not reconstruction.receipt.essential_modality_survived:
        counterexamples.append("receipt.essential_modality_survived=false")

    # Never claim device capability grants.
    if reconstruction.receipt.invented_device_capabilities:
        counterexamples.append(
            f"invented_device_capabilities:"
            f"{list(reconstruction.receipt.invented_device_capabilities)}"
        )

    passed = not counterexamples
    if not required:
        return LayerResult(
            layer=EquivalenceLayer.MODALITY_COVERAGE,
            passed=True,
            details=f"advisory_only; essential={len(essential)}",
            counterexamples=tuple(counterexamples),
        )
    return LayerResult(
        layer=EquivalenceLayer.MODALITY_COVERAGE,
        passed=passed,
        details=f"essential_capabilities={len(essential)} kept={len(kept)}",
        counterexamples=tuple(counterexamples),
    )


def _declared_loss(
    reconstruction: UIReconstructionArtifact,
    *,
    max_loss_items: int | None,
) -> LayerResult:
    # Source/pixel equality must appear as explicit out-of-scope loss, never
    # as a failed equality claim.
    loss_ids = {item.semantic_id for item in reconstruction.loss}
    unsupported = set(reconstruction.unsupported)
    counterexamples: list[str] = []

    for claim in EXCLUDED_EQUIVALENCE_CLAIMS:
        mapped = {
            "source_equality": "source_code_equality",
            "pixel_equality": "pixel_equality",
        }[claim]
        if mapped not in unsupported and mapped not in loss_ids:
            counterexamples.append(f"excluded_claim_not_declared:{claim}")

    if reconstruction.receipt.claims_source_equality:
        counterexamples.append("receipt.claims_source_equality=true")
    if reconstruction.receipt.claims_pixel_equality:
        counterexamples.append("receipt.claims_pixel_equality=true")
    if "source_equality" not in reconstruction.excluded_equivalence_claims:
        counterexamples.append("artifact.missing_excluded:source_equality")
    if "pixel_equality" not in reconstruction.excluded_equivalence_claims:
        counterexamples.append("artifact.missing_excluded:pixel_equality")

    if max_loss_items is not None and len(reconstruction.loss) > max_loss_items:
        counterexamples.append(
            f"loss_threshold_exceeded:{len(reconstruction.loss)}>{max_loss_items}"
        )

    return LayerResult(
        layer=EquivalenceLayer.DECLARED_LOSS,
        passed=not counterexamples,
        details=(
            f"loss_items={len(reconstruction.loss)} "
            f"unsupported={len(reconstruction.unsupported)} "
            f"excluded={list(EXCLUDED_EQUIVALENCE_CLAIMS)}"
        ),
        counterexamples=tuple(counterexamples),
    )


def roundtrip_ui_ir(
    document: RoundTripDocument | FormalizationInputs,
    policy: SemanticRoundTripPolicy | None = None,
) -> SemanticRoundTripReport:
    """Compile, decompile, and evaluate layered semantic round-trip equivalence.

    Source-code and pixel equality are excluded from the result and cannot be
    enabled via policy.
    """

    doc = _as_document(document)
    pol = policy or SemanticRoundTripPolicy()
    if not isinstance(pol, SemanticRoundTripPolicy):
        raise UIIRValidationError(
            "roundtrip_ui_ir policy must be a SemanticRoundTripPolicy"
        )
    if not doc.document_id.strip():
        raise UIIRValidationError("RoundTripDocument.document_id must not be empty")

    # Policy hard-locks.
    if pol.evaluate_source_equality or pol.evaluate_pixel_equality:
        # __post_init__ already forces False; belt-and-suspenders.
        raise UIIRValidationError(
            "source_equality and pixel_equality are excluded from semantic "
            "round-trip evaluation"
        )

    if (
        doc.component_graph is None
        and doc.behavior_model is None
        and not doc.action_bindings
        and not doc.events
    ):
        raise UIIRValidationError(
            "Round-trip requires at least one of component_graph, "
            "behavior_model, action_bindings, or events"
        )

    formalization = compile_ui_formalization(
        FormalizationInputs(
            component_graph=doc.component_graph,
            behavior_model=doc.behavior_model,
            action_bindings=doc.action_bindings,
            events=doc.events,
            actor_id=doc.actor_id,
            artifact_id=f"formalize:{doc.document_id}",
        )
    )

    accessibility_ids: list[str] = []
    if doc.experience is not None:
        accessibility_ids.extend(
            b.component_id for b in doc.experience.accessible_names
        )
    if doc.component_graph is not None:
        accessibility_ids.extend(
            c.component_id for c in doc.component_graph.components
        )

    essential_caps: list[str] = []
    if doc.modality is not None:
        for req in doc.modality.requirements:
            if req.essential:
                essential_caps.extend(req.capability_ids)

    reconstruction = decompile_ui_formalization(
        formalization,
        DecompilationRequest(
            request_id=f"rt:{doc.document_id}",
            allow_alternatives=True,
            accessibility_component_ids=tuple(sorted(set(accessibility_ids))),
            essential_modality_capability_ids=tuple(sorted(set(essential_caps))),
        ),
    )

    layers: list[LayerResult] = [
        _canonical_identity(doc, reconstruction),
        _graph_isomorphism(doc, reconstruction),
        _trace_equivalence(
            doc, reconstruction, max_depth=pol.max_trace_depth
        ),
        _formula_equivalence(doc, formalization, reconstruction),
        _deontic_non_weakening(
            doc,
            reconstruction,
            required=pol.require_deontic_non_weakening,
        ),
        _accessibility_equivalence(
            doc, reconstruction, required=pol.require_accessibility
        ),
        _modality_coverage(
            doc, reconstruction, required=pol.require_modality
        ),
        _declared_loss(
            reconstruction, max_loss_items=pol.max_loss_items
        ),
    ]

    # Apply policy requirements for optional skips.
    required_layers = {
        EquivalenceLayer.CANONICAL_IDENTITY: True,
        EquivalenceLayer.GRAPH_ISOMORPHISM: pol.require_graph_isomorphism,
        EquivalenceLayer.TRACE_EQUIVALENCE: pol.require_trace_equivalence,
        EquivalenceLayer.FORMULA_EQUIVALENCE: pol.require_formula_equivalence,
        EquivalenceLayer.DEONTIC_NON_WEAKENING: pol.require_deontic_non_weakening,
        EquivalenceLayer.ACCESSIBILITY: pol.require_accessibility,
        EquivalenceLayer.MODALITY_COVERAGE: pol.require_modality,
        EquivalenceLayer.DECLARED_LOSS: True,
    }

    gating_failures: list[str] = []
    for layer in layers:
        if not layer.evaluated:
            continue
        if not layer.passed and required_layers.get(layer.layer, True):
            gating_failures.extend(
                f"{layer.layer.value}:{cx}" for cx in layer.counterexamples
            ) or gating_failures.append(layer.layer.value)

    overall = not gating_failures
    # Invention is always a hard failure.
    if reconstruction.receipt.has_inventions():
        overall = False
        gating_failures.append("reconstruction.has_inventions")

    return SemanticRoundTripReport(
        report_id=f"report:{doc.document_id}",
        document_id=doc.document_id,
        policy_id=pol.policy_id,
        overall_passed=overall,
        layers=tuple(layers),
        reconstruction=reconstruction,
        formalization=formalization,
        excluded_claims=EXCLUDED_EQUIVALENCE_CLAIMS,
        counterexamples=tuple(gating_failures),
    )


__all__ = [
    "EXCLUDED_EQUIVALENCE_CLAIMS",
    "EquivalenceLayer",
    "LayerResult",
    "RoundTripDocument",
    "SemanticRoundTripPolicy",
    "SemanticRoundTripReport",
    "UI_SEMANTIC_ROUNDTRIP_ID",
    "UI_SEMANTIC_ROUNDTRIP_INTERFACE",
    "UI_SEMANTIC_ROUNDTRIP_REPORT_SCHEMA",
    "roundtrip_ui_ir",
]
