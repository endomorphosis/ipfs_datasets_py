"""Deterministic prohibition-polarity compilation for Legal IR."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


DEONTIC_COMPILER_REPAIR_SCHEMA_VERSION = "legal-ir-deontic-compiler-repair-v1"

_PROHIBITION_RE = re.compile(
    r"\b(?:the\s+|an?\s+)?(?P<actor>agency|applicant|board|court|director|"
    r"employer|officer|person|recipient|secretary|administrator|commission|"
    r"permittee|licensee|[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?)\s+"
    r"(?:(?P<modal>shall\s+not|must\s+not|may\s+not)\s+|"
    r"(?:is|are)\s+(?P<word>prohibited|forbidden)\s+from\s+)"
    r"(?P<action>[A-Za-z][A-Za-z-]*)(?:\s+(?P<object>.+?))?"
    r"(?=\s+(?:if|unless|except|subject\s+to|notwithstanding|before|after|within|until)\b|[.;]|$)",
    re.IGNORECASE,
)


def compile_prohibition_polarity(text: str, *, provenance_id: str = "") -> dict[str, Any]:
    """Emit ``F(action)`` records without encoding a second action negation."""

    provenance_ids = [str(provenance_id).strip()] if str(provenance_id).strip() else []
    norms: list[dict[str, Any]] = []
    for match in _PROHIBITION_RE.finditer(str(text or "")):
        actor = _phrase(match.group("actor"))
        action = _atom(match.group("action"))
        obj = _phrase(match.group("object"))
        cue = _atom(match.group("modal") or match.group("word"))
        identity = {"action": action, "actor": actor, "object": obj, "provenance_ids": provenance_ids}
        norms.append(
            {
                "action": action,
                "action_negated": False,
                "actor": actor,
                "deontic_operator": "F",
                "modal_cue": cue,
                "norm_id": f"deontic-prohibition:{_digest(identity)[:24]}",
                "norm_type": "prohibition",
                "object": obj,
                "polarity": "negative",
            }
        )
    return {
        "norms": norms,
        "operator_semantics": "F(action)",
        "provenance_ids": provenance_ids,
        "schema_version": DEONTIC_COMPILER_REPAIR_SCHEMA_VERSION,
    }


def _atom(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _phrase(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:").lower()
    text = re.sub(r"^(?:the|a|an|any|each)\s+", "", text)
    return "_".join(re.findall(r"[a-z0-9]+", text)[:10])


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


__all__ = ["DEONTIC_COMPILER_REPAIR_SCHEMA_VERSION", "compile_prohibition_polarity"]
