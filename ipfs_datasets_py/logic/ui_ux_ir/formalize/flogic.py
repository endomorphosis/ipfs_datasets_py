"""Structural FOL / F-logic compiler leaf for UI/UX IR (UIR-021)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..model.components import UIComponentGraph, validate_component_graph
from ..schema import UIIRValidationError
from .contracts import FormalView, ResultAuthority
from .ontology import default_ui_formal_ontology

UI_FLOGIC_COMPILER: Final = "ui-ux-ir/flogic@1"


@dataclass(frozen=True, slots=True)
class FLogicFact:
    predicate: str
    args: tuple[str, ...]
    source_ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FLogicCompilation:
    compiler: str
    view: FormalView
    facts: tuple[FLogicFact, ...]
    unsupported: tuple[str, ...] = ()
    result_authority: ResultAuthority = ResultAuthority.ADVISORY
    schema_version: str = "ui-flogic-compilation/v1"


def compile_component_graph_to_flogic(graph: UIComponentGraph) -> FLogicCompilation:
    """Compile a validated component graph into deterministic structural facts."""

    validated = validate_component_graph(graph)
    # Ontology must be present for symbol stability.
    default_ui_formal_ontology()
    facts: list[FLogicFact] = []
    for component in validated.components:
        facts.append(
            FLogicFact(
                predicate="ui_component",
                args=(component.component_id, component.role),
                source_ref_ids=component.source_ref_ids,
            )
        )
        if component.parent_id:
            facts.append(
                FLogicFact(
                    predicate="ui_parent",
                    args=(component.parent_id, component.component_id),
                    source_ref_ids=component.source_ref_ids,
                )
            )
        for child in component.child_ids:
            facts.append(
                FLogicFact(
                    predicate="ui_contains",
                    args=(component.component_id, child),
                    source_ref_ids=component.source_ref_ids,
                )
            )
    for rel in validated.relationships:
        facts.append(
            FLogicFact(
                predicate=f"ui_rel_{rel.kind.value}",
                args=(rel.source_component_id, rel.target_component_id),
                source_ref_ids=rel.source_ref_ids,
            )
        )
    # Stable order for determinism.
    facts_sorted = tuple(
        sorted(facts, key=lambda f: (f.predicate, f.args, f.source_ref_ids))
    )
    if not facts_sorted:
        raise UIIRValidationError("F-logic compilation produced no facts")
    unsupported = (
        "pixel_layout",
        "framework_widget_class",
        "executable_callbacks",
    )
    return FLogicCompilation(
        compiler=UI_FLOGIC_COMPILER,
        view=FormalView.FLOGIC,
        facts=facts_sorted,
        unsupported=unsupported,
    )


__all__ = [
    "FLogicCompilation",
    "FLogicFact",
    "UI_FLOGIC_COMPILER",
    "compile_component_graph_to_flogic",
]
