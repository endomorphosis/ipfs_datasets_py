"""Integrated multi-view UI/UX IR formalization compiler (UIR-025).

Consumes the four leaf compilers (F-logic, event calculus, TDFOL, DCEC) and
emits one immutable multi-view artifact with cross-view links, coverage
dispositions, diagnostics, backend requests, and explicit unsupported
semantics. Never concatenates mixed-logic into a single blob, never imports
optional provers eagerly, and never reports backend unavailability as proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..model.behavior import BehaviorModel
from ..model.bindings import UIActionBinding
from ..model.components import UIComponentGraph
from ..runtime.events import CanonicalInteractionEvent
from ..schema import UIIRValidationError
from .contracts import (
    CoverageDisposition,
    FormalView,
    ResultAuthority,
    default_compiler_contracts,
)
from .dcec import DCECCompilation, compile_events_to_dcec
from .event_calculus import EventCalculusCompilation, compile_behavior_to_event_calculus
from .flogic import FLogicCompilation, compile_component_graph_to_flogic
from .ontology import SourceSemanticCoverage, default_ui_formal_ontology
from .tdfol import TDFOLCompilation, compile_action_bindings_to_tdfol

UI_FORMALIZATION_COMPILER_INTERFACE: Final = "UIFormalizationCompiler@1"
UI_FORMALIZATION_ARTIFACT_INTERFACE: Final = "UIFormalizationArtifact@1"
UI_FORMALIZATION_COMPILER_ID: Final = "ui-ux-ir/formalization-compiler@1"
UI_FORMALIZATION_ARTIFACT_SCHEMA: Final = "ui-formalization-artifact/v1"


class CoverageKind(str):
    """How one source semantic is covered in the integrated artifact."""

    REPRESENTED = "represented"
    APPROXIMATED = "approximated"
    UNSUPPORTED = "unsupported"
    INTENTIONALLY_NON_FORMAL = "intentionally_non_formal"


# Stable mapping from ontology dispositions to integrated coverage kinds.
_DISPOSITION_TO_KIND: Mapping[CoverageDisposition, str] = MappingProxyType(
    {
        CoverageDisposition.FULL: CoverageKind.REPRESENTED,
        CoverageDisposition.PARTIAL: CoverageKind.APPROXIMATED,
        CoverageDisposition.LOSSY: CoverageKind.APPROXIMATED,
        CoverageDisposition.EXPLICIT_UNSUPPORTED: CoverageKind.UNSUPPORTED,
        CoverageDisposition.OUT_OF_SCOPE: CoverageKind.INTENTIONALLY_NON_FORMAL,
    }
)


@dataclass(frozen=True, slots=True)
class CrossViewLink:
    """Agreement link between symbols across formal views."""

    link_id: str
    source_view: FormalView
    target_view: FormalView
    source_symbol: str
    target_symbol: str
    relation: str = "corresponds"


@dataclass(frozen=True, slots=True)
class CoverageReceipt:
    """Per-source semantic coverage disposition across views."""

    source_semantic_id: str
    kind: str
    views: Mapping[str, str]  # FormalView value -> CoverageKind
    notes: str = ""


@dataclass(frozen=True, slots=True)
class BackendRequest:
    """Typed optional-backend request; unavailability is never proof."""

    backend_id: str
    view: FormalView
    status: str  # available | unavailable | not_requested
    result_authority: ResultAuthority
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FormalizationDiagnostic:
    code: str
    message: str
    severity: str = "info"  # info | warning | error
    source_ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UIFormalizationArtifact:
    """Immutable multi-view formalization artifact (not a mixed-logic blob)."""

    artifact_id: str
    compiler_id: str
    flogic: FLogicCompilation | None
    event_calculus: EventCalculusCompilation | None
    tdfol: TDFOLCompilation | None
    dcec: DCECCompilation | None
    cross_view_links: tuple[CrossViewLink, ...]
    coverage: tuple[CoverageReceipt, ...]
    diagnostics: tuple[FormalizationDiagnostic, ...]
    backend_requests: tuple[BackendRequest, ...]
    unsupported_semantics: tuple[str, ...]
    proof_obligations: tuple[str, ...]
    source_map: Mapping[str, tuple[str, ...]]
    result_authority: ResultAuthority = ResultAuthority.ADVISORY
    schema_version: str = UI_FORMALIZATION_ARTIFACT_SCHEMA
    interface: str = UI_FORMALIZATION_ARTIFACT_INTERFACE


@dataclass(frozen=True, slots=True)
class FormalizationInputs:
    """Inputs for integrated compilation; empty collections skip that view."""

    component_graph: UIComponentGraph | None = None
    behavior_model: BehaviorModel | None = None
    action_bindings: tuple[UIActionBinding, ...] = ()
    events: tuple[CanonicalInteractionEvent, ...] = ()
    actor_id: str = "user"
    artifact_id: str = "ui-formalization/default"


def _union_unsupported(*chunks: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for chunk in chunks:
        for item in chunk:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return tuple(out)


def _build_coverage_receipts() -> tuple[CoverageReceipt, ...]:
    ontology = default_ui_formal_ontology()
    receipts: list[CoverageReceipt] = []
    for item in ontology.source_coverage:
        views: dict[str, str] = {}
        kinds: set[str] = set()
        for view, disposition in item.dispositions.items():
            kind = _DISPOSITION_TO_KIND.get(disposition, CoverageKind.UNSUPPORTED)
            views[view.value] = kind
            kinds.add(kind)
        # Prefer the most specific non-represented kind for the aggregate label.
        if CoverageKind.INTENTIONALLY_NON_FORMAL in kinds and len(kinds) == 1:
            aggregate = CoverageKind.INTENTIONALLY_NON_FORMAL
        elif CoverageKind.UNSUPPORTED in kinds:
            aggregate = CoverageKind.UNSUPPORTED
        elif CoverageKind.APPROXIMATED in kinds:
            aggregate = CoverageKind.APPROXIMATED
        else:
            aggregate = CoverageKind.REPRESENTED
        receipts.append(
            CoverageReceipt(
                source_semantic_id=item.source_semantic_id,
                kind=aggregate,
                views=MappingProxyType(views),
                notes=getattr(item, "notes", "") or "",
            )
        )
    return tuple(sorted(receipts, key=lambda r: r.source_semantic_id))


def _build_cross_view_links(
    *,
    flogic: FLogicCompilation | None,
    event_calculus: EventCalculusCompilation | None,
    tdfol: TDFOLCompilation | None,
    dcec: DCECCompilation | None,
) -> tuple[CrossViewLink, ...]:
    """Link shared component/action symbols across views without merging logics."""

    links: list[CrossViewLink] = []
    component_ids: set[str] = set()
    if flogic is not None:
        for fact in flogic.facts:
            if fact.predicate == "ui_component" and fact.args:
                component_ids.add(fact.args[0])

    action_ids: set[str] = set()
    if tdfol is not None:
        for formula in tdfol.formulas:
            # proposition shapes like invoke(action) / confirm(action)
            prop = formula.proposition
            if "(" in prop and prop.endswith(")"):
                inner = prop[prop.index("(") + 1 : -1]
                if inner and "," not in inner:
                    action_ids.add(inner)

    event_targets: set[str] = set()
    if dcec is not None:
        for formula in dcec.formulas:
            content = formula.content
            if "(" in content and content.endswith(")"):
                inner = content[content.index("(") + 1 : -1]
                if inner:
                    event_targets.add(inner.split(",")[0])

    link_n = 0
    for cid in sorted(component_ids):
        if event_calculus is not None:
            link_n += 1
            links.append(
                CrossViewLink(
                    link_id=f"xlink:{link_n}",
                    source_view=FormalView.FLOGIC,
                    target_view=FormalView.EVENT_CALCULUS,
                    source_symbol=cid,
                    target_symbol=cid,
                    relation="component_fluent_scope",
                )
            )
        if cid in event_targets and dcec is not None:
            link_n += 1
            links.append(
                CrossViewLink(
                    link_id=f"xlink:{link_n}",
                    source_view=FormalView.FLOGIC,
                    target_view=FormalView.DCEC,
                    source_symbol=cid,
                    target_symbol=cid,
                    relation="component_observation_target",
                )
            )
    for action in sorted(action_ids):
        if flogic is not None:
            link_n += 1
            links.append(
                CrossViewLink(
                    link_id=f"xlink:{link_n}",
                    source_view=FormalView.TDFOL,
                    target_view=FormalView.FLOGIC,
                    source_symbol=action,
                    target_symbol=action,
                    relation="action_component_agreement",
                )
            )
        if dcec is not None:
            link_n += 1
            links.append(
                CrossViewLink(
                    link_id=f"xlink:{link_n}",
                    source_view=FormalView.TDFOL,
                    target_view=FormalView.DCEC,
                    source_symbol=action,
                    target_symbol=action,
                    relation="action_intention_scope",
                )
            )
    return tuple(links)


def _backend_requests() -> tuple[BackendRequest, ...]:
    """Declare optional backends as unavailable without claiming proof."""

    requests: list[BackendRequest] = []
    for contract in default_compiler_contracts():
        for bound in contract.backend_bounds:
            # Optional provers are never eagerly imported; mark unavailable.
            requests.append(
                BackendRequest(
                    backend_id=bound.backend_id,
                    view=bound.view,
                    status="unavailable",
                    result_authority=ResultAuthority.NONE
                    if bound.supports_proof
                    else bound.result_authority,
                    reason=(
                        "optional_backend_not_loaded"
                        if bound.supports_proof
                        else "advisory_backend_not_invoked"
                    ),
                )
            )
    return tuple(requests)


def _proof_obligations(
    tdfol: TDFOLCompilation | None,
) -> tuple[str, ...]:
    if tdfol is None:
        return ()
    obligations: list[str] = []
    for formula in tdfol.formulas:
        if formula.operator in {"obligation", "prohibition"} and formula.strength == "strict":
            obligations.append(f"{formula.operator}:{formula.proposition}")
    return tuple(sorted(set(obligations)))


def _source_map(
    *,
    flogic: FLogicCompilation | None,
    event_calculus: EventCalculusCompilation | None,
    tdfol: TDFOLCompilation | None,
    dcec: DCECCompilation | None,
) -> Mapping[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {}

    def _add(view: str, refs: Sequence[str]) -> None:
        for ref in refs:
            mapping.setdefault(ref, []).append(view)

    if flogic is not None:
        for fact in flogic.facts:
            _add(FormalView.FLOGIC.value, fact.source_ref_ids)
    if event_calculus is not None:
        for formula in event_calculus.formulas:
            _add(FormalView.EVENT_CALCULUS.value, formula.source_ref_ids)
    if tdfol is not None:
        for formula in tdfol.formulas:
            _add(FormalView.TDFOL.value, formula.source_ref_ids)
    if dcec is not None:
        for formula in dcec.formulas:
            _add(FormalView.DCEC.value, formula.source_ref_ids)

    return MappingProxyType(
        {key: tuple(sorted(set(views))) for key, views in sorted(mapping.items())}
    )


def compile_ui_formalization(inputs: FormalizationInputs) -> UIFormalizationArtifact:
    """Compile all provided views into one immutable multi-view artifact."""

    if (
        inputs.component_graph is None
        and inputs.behavior_model is None
        and not inputs.action_bindings
        and not inputs.events
    ):
        raise UIIRValidationError(
            "Formalization requires at least one of component_graph, "
            "behavior_model, action_bindings, or events"
        )

    flogic: FLogicCompilation | None = None
    event_calculus: EventCalculusCompilation | None = None
    tdfol: TDFOLCompilation | None = None
    dcec: DCECCompilation | None = None
    diagnostics: list[FormalizationDiagnostic] = []

    if inputs.component_graph is not None:
        flogic = compile_component_graph_to_flogic(inputs.component_graph)
    else:
        diagnostics.append(
            FormalizationDiagnostic(
                code="view.skipped",
                message="F-logic view skipped: no component_graph",
                severity="info",
            )
        )

    if inputs.behavior_model is not None:
        event_calculus = compile_behavior_to_event_calculus(inputs.behavior_model)
    else:
        diagnostics.append(
            FormalizationDiagnostic(
                code="view.skipped",
                message="Event-calculus view skipped: no behavior_model",
                severity="info",
            )
        )

    if inputs.action_bindings:
        tdfol = compile_action_bindings_to_tdfol(inputs.action_bindings)
    else:
        diagnostics.append(
            FormalizationDiagnostic(
                code="view.skipped",
                message="TDFOL view skipped: no action_bindings",
                severity="info",
            )
        )

    if inputs.events:
        dcec = compile_events_to_dcec(inputs.events, actor_id=inputs.actor_id)
    else:
        diagnostics.append(
            FormalizationDiagnostic(
                code="view.skipped",
                message="DCEC view skipped: no events",
                severity="info",
            )
        )

    unsupported = _union_unsupported(
        flogic.unsupported if flogic else (),
        event_calculus.unsupported if event_calculus else (),
        tdfol.unsupported if tdfol else (),
        dcec.unsupported if dcec else (),
        ("mixed_logic_concatenation", "eager_optional_prover_import"),
    )

    # Cross-view symbol agreement: every represented component that appears
    # as a DCEC target should also exist in F-logic when both views compiled.
    if flogic is not None and dcec is not None:
        flogic_components = {
            fact.args[0]
            for fact in flogic.facts
            if fact.predicate == "ui_component" and fact.args
        }
        for formula in dcec.formulas:
            if formula.kind != "observes":
                continue
            content = formula.content
            if "(" not in content or not content.endswith(")"):
                continue
            target = content[content.index("(") + 1 : -1]
            if target and target not in flogic_components:
                diagnostics.append(
                    FormalizationDiagnostic(
                        code="cross_view.disagreement",
                        message=(
                            f"DCEC observation target {target!r} missing from "
                            "F-logic component symbols"
                        ),
                        severity="warning",
                    )
                )

    backend_requests = _backend_requests()
    for req in backend_requests:
        if req.status == "unavailable" and req.result_authority is ResultAuthority.NONE:
            diagnostics.append(
                FormalizationDiagnostic(
                    code="backend.unavailable",
                    message=(
                        f"Backend {req.backend_id!r} for view {req.view.value} "
                        f"is unavailable ({req.reason}); not reported as proof"
                    ),
                    severity="info",
                )
            )

    artifact = UIFormalizationArtifact(
        artifact_id=inputs.artifact_id or "ui-formalization/default",
        compiler_id=UI_FORMALIZATION_COMPILER_ID,
        flogic=flogic,
        event_calculus=event_calculus,
        tdfol=tdfol,
        dcec=dcec,
        cross_view_links=_build_cross_view_links(
            flogic=flogic,
            event_calculus=event_calculus,
            tdfol=tdfol,
            dcec=dcec,
        ),
        coverage=_build_coverage_receipts(),
        diagnostics=tuple(diagnostics),
        backend_requests=backend_requests,
        unsupported_semantics=unsupported,
        proof_obligations=_proof_obligations(tdfol),
        source_map=_source_map(
            flogic=flogic,
            event_calculus=event_calculus,
            tdfol=tdfol,
            dcec=dcec,
        ),
        result_authority=ResultAuthority.ADVISORY,
    )
    return artifact


__all__ = [
    "BackendRequest",
    "CoverageKind",
    "CoverageReceipt",
    "CrossViewLink",
    "FormalizationDiagnostic",
    "FormalizationInputs",
    "UI_FORMALIZATION_ARTIFACT_INTERFACE",
    "UI_FORMALIZATION_COMPILER_ID",
    "UI_FORMALIZATION_COMPILER_INTERFACE",
    "UIFormalizationArtifact",
    "compile_ui_formalization",
]
