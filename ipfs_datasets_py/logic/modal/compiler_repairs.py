"""Deterministic repairs for exception precedence and frame-role binding.

The functions in this module deliberately return small, serializable compiler
records.  They retain normalized semantic atoms and provenance identifiers,
never the source sentence or character spans.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


MODAL_COMPILER_REPAIR_SCHEMA_VERSION = "legal-ir-modal-compiler-repair-v1"

_EXCEPTION_RE = re.compile(
    r"\b(?P<cue>except\s+as\s+provided(?:\s+in)?|except(?:\s+for)?|unless|"
    r"subject\s+to|notwithstanding)\b(?P<body>[^,.;]*)",
    re.IGNORECASE,
)
_ROLE_RE = re.compile(
    r"\b(?:the\s+|an?\s+)?(?P<actor>agency|applicant|board|court|director|"
    r"employer|officer|person|recipient|secretary|administrator|commission|"
    r"permittee|licensee|[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?)\s+"
    r"(?P<modal>shall\s+not|must\s+not|may\s+not|shall|must|may|"
    r"is\s+(?:authorized|required|permitted)\s+to)\s+"
    r"(?P<action>[A-Za-z][A-Za-z-]*)(?:\s+(?P<object>.+?))?"
    r"(?=\s+(?:if|unless|except|subject\s+to|notwithstanding|before|after|"
    r"within|until|no\s+later\s+than|not\s+later\s+than)\b|[.;]|$)",
    re.IGNORECASE,
)
_RECIPIENT_RE = re.compile(r"\b(?:to|for)\s+(?:the\s+|an?\s+)?(?P<value>[A-Za-z][A-Za-z -]{1,48})$", re.I)
_SPACE_RE = re.compile(r"\s+")


def compile_exception_precedence(text: str, *, provenance_id: str = "") -> dict[str, Any]:
    """Compile scoped exceptions with explicit exception-over-general ordering."""

    provenance_ids = _provenance_ids(provenance_id)
    exceptions: list[dict[str, Any]] = []
    for order, match in enumerate(_EXCEPTION_RE.finditer(str(text or "")), start=1):
        cue = _atom(match.group("cue"))
        condition = _semantic_phrase(match.group("body"), fallback="scoped_condition")
        identity = {"condition": condition, "cue": cue, "order": order, "provenance_ids": provenance_ids}
        exceptions.append(
            {
                "condition": condition,
                "cue": cue,
                "defeater_id": f"modal-defeater:{_digest(identity)[:24]}",
                "governed_rule": "general_rule",
                "precedence_rank": order - 1,
                "relation": "overrides",
                "scope": "local_norm" if cue != "notwithstanding" else "conflicting_norm",
            }
        )
    identity = {"exceptions": exceptions, "provenance_ids": provenance_ids}
    return {
        "exception_order": [item["defeater_id"] for item in exceptions],
        "exceptions": exceptions,
        "general_rule_id": f"modal-general-rule:{_digest(identity)[:24]}",
        "precedence": "exception_over_general_rule",
        "provenance_ids": provenance_ids,
        "schema_version": MODAL_COMPILER_REPAIR_SCHEMA_VERSION,
    }


def compile_frame_role_bindings(text: str, *, provenance_id: str = "") -> dict[str, Any]:
    """Compile an operative clause into typed subject/predicate/object roles."""

    provenance_ids = _provenance_ids(provenance_id)
    match = _ROLE_RE.search(str(text or ""))
    bindings: list[dict[str, str]] = []
    modality = ""
    polarity = "not_applicable"
    if match:
        actor = _semantic_phrase(match.group("actor"), fallback="actor")
        action = _atom(match.group("action"))
        obj = _semantic_phrase(match.group("object"), fallback="")
        recipient = ""
        recipient_match = _RECIPIENT_RE.search(obj.replace("_", " ")) if obj else None
        if recipient_match:
            recipient = _semantic_phrase(recipient_match.group("value"), fallback="")
        modality = _atom(match.group("modal"))
        polarity = "negative" if modality.endswith("_not") else "positive"
        for role, value, value_type in (
            ("agent", actor, "legal_actor"),
            ("action", action, "legal_action"),
            ("object", obj, "legal_object"),
            ("recipient", recipient, "legal_actor"),
        ):
            if value:
                bindings.append({"role": role, "value": value, "value_type": value_type})
    identity = {"bindings": bindings, "modality": modality, "polarity": polarity, "provenance_ids": provenance_ids}
    return {
        "bindings": bindings,
        "frame_id": f"legal-frame:{_digest(identity)[:24]}",
        "modality": modality,
        "polarity": polarity,
        "provenance_ids": provenance_ids,
        "schema_version": MODAL_COMPILER_REPAIR_SCHEMA_VERSION,
    }


def _provenance_ids(value: Any) -> list[str]:
    item = str(value or "").strip()
    return [item] if item else []


def _atom(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _semantic_phrase(value: Any, *, fallback: str) -> str:
    text = _SPACE_RE.sub(" ", str(value or "")).strip(" ,.;:").lower()
    text = re.sub(r"^(?:the|a|an|any|each)\s+", "", text)
    tokens = re.findall(r"[a-z0-9]+", text)[:10]
    return "_".join(tokens) or fallback


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


__all__ = [
    "MODAL_COMPILER_REPAIR_SCHEMA_VERSION",
    "compile_exception_precedence",
    "compile_frame_role_bindings",
]
