"""Lower UIIRDocument to target-neutral semantic projection items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..decoder import decode_ui_ir
from ..schema import UIIRDocument, validate_ui_ir


@dataclass(frozen=True, slots=True)
class SemanticItem:
    item_id: str
    semantic_kind: str
    label: str = ""
    component_id: str = ""
    order: int = 100
    mandatory: bool = False
    disposition: str = "preserved"
    fallback_ref: str = ""
    text: str = ""
    risk_class: str = "low"
    confirmation_class: str = "none"
    target_ref: str = ""
    modality_hints: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "confirmation_class": self.confirmation_class,
            "disposition": self.disposition,
            "fallback_ref": self.fallback_ref,
            "item_id": self.item_id,
            "label": self.label,
            "mandatory": self.mandatory,
            "modality_hints": list(self.modality_hints),
            "order": self.order,
            "risk_class": self.risk_class,
            "semantic_kind": self.semantic_kind,
            "target_ref": self.target_ref,
            "text": self.text or self.label,
        }


def _as_document(document: UIIRDocument | Mapping[str, Any]) -> UIIRDocument:
    if isinstance(document, UIIRDocument):
        return validate_ui_ir(document)
    return decode_ui_ir(document)


def document_to_semantic_items(
    document: UIIRDocument | Mapping[str, Any],
) -> list[SemanticItem]:
    """Project a declaration into ordered semantic items for target adapters."""
    doc = _as_document(document)
    items: list[SemanticItem] = []
    order = 0

    for component in sorted(doc.components, key=lambda c: c.component_id):
        kind = "structure"
        role = (component.role or "").lower()
        if role in {"button", "link", "menuitem"}:
            kind = "action"
        elif role in {"alert", "status"}:
            kind = "feedback"
        elif role in {"dialog", "alertdialog", "form"}:
            kind = "structure"
        elif role in {"textbox", "searchbox", "input"}:
            kind = "text_input"
        mandatory = component.component_id in doc.entry_components or kind == "action"
        items.append(
            SemanticItem(
                item_id=f"item:{component.component_id}",
                semantic_kind=kind,
                label=component.purpose or component.component_id,
                component_id=component.component_id,
                order=order,
                mandatory=mandatory,
                text=component.purpose or component.role,
            )
        )
        order += 10

    for binding in doc.program_bindings:
        conf = binding.confirmation_class or "none"
        risk = binding.risk_class or "low"
        kind = "confirmation" if conf != "none" else "action"
        mandatory = conf != "none" or risk in {"high", "critical"}
        items.append(
            SemanticItem(
                item_id=f"item:binding:{binding.binding_id}",
                semantic_kind=kind,
                label=f"Invoke {binding.target_ref}",
                order=order,
                mandatory=mandatory,
                risk_class=risk,
                confirmation_class=conf,
                target_ref=binding.target_ref,
                fallback_ref=(
                    f"fallback:mobile:{binding.binding_id}"
                    if risk in {"high", "critical"}
                    else ""
                ),
            )
        )
        order += 10

    for feedback in doc.feedback_contracts:
        items.append(
            SemanticItem(
                item_id=f"item:feedback:{feedback.feedback_id}",
                semantic_kind="feedback",
                label=f"Feedback via {feedback.channel}",
                component_id=feedback.component_id,
                order=order,
                mandatory=True,
            )
        )
        order += 10

    for outcome in doc.terminal_outcomes:
        kind = (
            outcome.kind.value
            if hasattr(outcome.kind, "value")
            else str(outcome.kind)
        )
        semantic = "error" if kind == "failure" else "status"
        items.append(
            SemanticItem(
                item_id=f"item:outcome:{outcome.outcome_id}",
                semantic_kind=semantic,
                label=outcome.description or outcome.outcome_id,
                order=order,
                mandatory=True,
            )
        )
        order += 10

    return items


__all__ = ["SemanticItem", "document_to_semantic_items"]
