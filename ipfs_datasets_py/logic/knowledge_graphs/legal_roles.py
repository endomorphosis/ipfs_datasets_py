"""Compile legal actor/action/object/remedy roles into a typed graph.

The compiler emits semantic slot values and stable provenance identifiers.  It
never stores the input sentence, raw source spans, or character offsets in the
graph payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


LEGAL_ROLE_GRAPH_SCHEMA_VERSION = "legal-ir-role-graph-v1"

_NORM_RE = re.compile(
    r"\b(?:the\s+|an?\s+)?"
    r"(?P<actor>agency|applicant|board|court|director|employer|officer|"
    r"person|recipient|secretary|administrator|commission|permittee|licensee|"
    r"[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?)\s+"
    r"(?P<modal>shall\s+not|must\s+not|may\s+not|shall|must|may|"
    r"is\s+(?:authorized|required|permitted)\s+to)\s+"
    r"(?P<action>[A-Za-z][A-Za-z-]*)"
    r"(?:\s+(?P<object>.+?))?"
    r"(?=\s+(?:if|unless|except|subject\s+to|notwithstanding|before|after|"
    r"within|until|no\s+later\s+than|not\s+later\s+than)\b|[.;]|$)",
    re.IGNORECASE,
)
_REMEDY_RE = re.compile(
    r"\b(?P<remedy>"
    r"(?:civil|criminal|administrative)\s+(?:penalty|fine|sanction|action)|"
    r"compensatory\s+damages|punitive\s+damages|"
    r"damages|injunction|penalty|fine|sanction|restitution|remedy"
    r")\b",
    re.IGNORECASE,
)
_OBJECT_STOP_RE = re.compile(
    r"\s+(?:and\s+)?(?:shall|must|may)\b|"
    r"\s+(?:as\s+)?(?:a|an|the)\s+(?:remedy|penalty|sanction)\b",
    re.IGNORECASE,
)
_DETERMINERS_RE = re.compile(r"^(?:the|a|an|any|each)\s+", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def compile_legal_role_graph(
    text: str,
    *,
    provenance_id: str = "",
) -> dict[str, Any]:
    """Return a stable typed role graph for the first operative legal norm.

    The graph contains a norm node plus any actor, action, object, and remedy
    nodes deterministically recoverable from ``text``.  Every relationship is
    directed from the norm to its typed role node.  An empty or non-operative
    input still returns a valid empty graph envelope.
    """

    source = str(text or "")
    provenance_ids = [str(provenance_id).strip()] if str(provenance_id).strip() else []
    match = _NORM_RE.search(source)
    roles: dict[str, str] = {}
    polarity = "not_applicable"
    modality = ""
    if match:
        actor = _clean_role_value(match.group("actor"))
        action = _clean_role_value(match.group("action"))
        object_value = _clean_object_value(match.group("object") or "")
        modality = _canonical_modal(match.group("modal"))
        polarity = "negative" if "not" in modality else "positive"
        if actor:
            roles["actor"] = actor
        if action:
            roles["action"] = action
        if object_value:
            roles["object"] = object_value

    remedy_match = _REMEDY_RE.search(source)
    if remedy_match:
        remedy = _clean_role_value(remedy_match.group("remedy"))
        if remedy and remedy != "remedy":
            roles["remedy"] = remedy

    identity = {
        "modality": modality,
        "polarity": polarity,
        "provenance_ids": provenance_ids,
        "roles": roles,
    }
    graph_digest = _digest(identity)
    graph_id = f"legal-role-graph:{graph_digest[:24]}"
    norm_id = f"legal-norm:{graph_digest[:24]}"
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    if roles:
        nodes.append(
            {
                "id": norm_id,
                "labels": ["LegalNorm"],
                "modality": modality,
                "polarity": polarity,
                "type": "norm",
            }
        )
    for role in ("actor", "action", "object", "remedy"):
        value = roles.get(role)
        if not value:
            continue
        node_id = f"legal-{role}:{_digest({'role': role, 'value': value})[:24]}"
        nodes.append(
            {
                "id": node_id,
                "labels": [_role_label(role)],
                "type": role,
                "value": value,
            }
        )
        edge_identity = {
            "end_node": node_id,
            "role": role,
            "start_node": norm_id,
        }
        relationships.append(
            {
                "directed": True,
                "end_node": node_id,
                "id": f"legal-role-edge:{_digest(edge_identity)[:24]}",
                "role": role,
                "start_node": norm_id,
                "type": f"HAS_{role.upper()}",
            }
        )

    return {
        "graph_id": graph_id,
        "nodes": nodes,
        "provenance_ids": provenance_ids,
        "relationships": relationships,
        "schema_version": LEGAL_ROLE_GRAPH_SCHEMA_VERSION,
    }


def _clean_role_value(value: Any) -> str:
    text = _SPACE_RE.sub(" ", str(value or "")).strip(" ,.;:").lower()
    return _DETERMINERS_RE.sub("", text).strip()


def _clean_object_value(value: str) -> str:
    text = _OBJECT_STOP_RE.split(str(value or ""), maxsplit=1)[0]
    return _clean_role_value(text)


def _canonical_modal(value: Any) -> str:
    return _SPACE_RE.sub("_", str(value or "").strip().lower())


def _role_label(role: str) -> str:
    return "Legal" + role[:1].upper() + role[1:]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["LEGAL_ROLE_GRAPH_SCHEMA_VERSION", "compile_legal_role_graph"]
