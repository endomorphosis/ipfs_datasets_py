"""Structural ontology for UI/UX IR formalization."""

from __future__ import annotations

from typing import Any

from ..schema import UIIRDocument
from .contracts import FormalSymbol


def ontology_symbols(document: UIIRDocument) -> tuple[FormalSymbol, ...]:
    """Emit base type/predicate symbols for a UI document."""
    symbols: list[FormalSymbol] = [
        FormalSymbol("sym:type:Component", "Component", "type", sort="entity"),
        FormalSymbol("sym:type:Event", "Event", "type", sort="entity"),
        FormalSymbol("sym:type:Outcome", "Outcome", "type", sort="entity"),
        FormalSymbol("sym:type:Binding", "Binding", "type", sort="entity"),
        FormalSymbol("sym:type:Agent", "Agent", "type", sort="entity"),
        FormalSymbol(
            "sym:pred:HasRole", "HasRole", "predicate", arity=2, sort="Component×Role"
        ),
        FormalSymbol(
            "sym:pred:ChildOf", "ChildOf", "predicate", arity=2, sort="Component×Component"
        ),
        FormalSymbol(
            "sym:pred:EntryComponent",
            "EntryComponent",
            "predicate",
            arity=1,
            sort="Component",
        ),
        FormalSymbol(
            "sym:pred:TerminalOutcome",
            "TerminalOutcome",
            "predicate",
            arity=2,
            sort="Outcome×Kind",
        ),
        FormalSymbol(
            "sym:pred:BindsProgram",
            "BindsProgram",
            "predicate",
            arity=3,
            sort="Binding×TargetKind×TargetRef",
        ),
        FormalSymbol(
            "sym:pred:BindsMcpIdl",
            "BindsMcpIdl",
            "predicate",
            arity=2,
            sort="Binding×Method",
        ),
    ]
    for component in document.components:
        symbols.append(
            FormalSymbol(
                f"sym:comp:{component.component_id}",
                component.component_id,
                "role" if component.role else "type",
                source_ref=component.component_id,
                sort=component.role or "Component",
            )
        )
    for event in document.events:
        symbols.append(
            FormalSymbol(
                f"sym:event:{event.event_id}",
                event.event_id,
                "event",
                source_ref=event.event_id,
                sort=event.kind or "Event",
            )
        )
    for binding in document.program_bindings:
        symbols.append(
            FormalSymbol(
                f"sym:binding:{binding.binding_id}",
                binding.binding_id,
                "action",
                source_ref=binding.binding_id,
                sort=str(
                    binding.target_kind.value
                    if hasattr(binding.target_kind, "value")
                    else binding.target_kind
                ),
            )
        )
    return tuple(symbols)


def document_facts(document: UIIRDocument) -> list[dict[str, Any]]:
    """Body-free structural facts used by all compilers."""
    facts: list[dict[str, Any]] = []
    for component in document.components:
        facts.append(
            {
                "kind": "component",
                "id": component.component_id,
                "role": component.role,
                "parent_id": component.parent_id,
                "child_ids": list(component.child_ids),
                "source_ref_ids": list(component.source_ref_ids),
            }
        )
    for outcome in document.terminal_outcomes:
        kind = (
            outcome.kind.value
            if hasattr(outcome.kind, "value")
            else str(outcome.kind)
        )
        facts.append(
            {
                "kind": "terminal_outcome",
                "id": outcome.outcome_id,
                "outcome_kind": kind,
                "source_ref_ids": list(outcome.source_ref_ids),
            }
        )
    for event in document.events:
        facts.append(
            {
                "kind": "event",
                "id": event.event_id,
                "event_kind": event.kind,
                "source_ref_ids": list(event.source_ref_ids),
            }
        )
    for binding in document.program_bindings:
        target_kind = (
            binding.target_kind.value
            if hasattr(binding.target_kind, "value")
            else str(binding.target_kind)
        )
        facts.append(
            {
                "kind": "program_binding",
                "id": binding.binding_id,
                "target_kind": target_kind,
                "target_ref": binding.target_ref,
                "risk_class": binding.risk_class,
                "confirmation_class": binding.confirmation_class,
                "source_ref_ids": list(binding.source_ref_ids),
            }
        )
    for binding in document.mcp_idl_bindings:
        facts.append(
            {
                "kind": "mcp_idl_binding",
                "id": binding.binding_id,
                "method_name": binding.method_name,
                "interface_cid": binding.interface_cid,
                "source_ref_ids": list(binding.source_ref_ids),
            }
        )
    for entry in document.entry_components:
        facts.append({"kind": "entry_component", "id": entry})
    return facts


__all__ = ["document_facts", "ontology_symbols"]
