"""Meta-ontology for deontic terms found in statute spans.

Categories sit above the statute graph. A title or section is scope, not a
term. Theft is an act, marriage is a state, a signature is an object, and
police, the president, Congress, and a person are participants. A formula
built from those roles is not a legal admit.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


# Graph node and edge types already stored on justicedao/ipfs_uscode.
# Participant, act, state, and object are reserved for span terms. This graph
# does not encode those terms as nodes.
GRAPH_NODE_CATEGORY = {
    "section": "scope",
    "title": "scope",
    "public_law": "instrument",
    "statutes_at_large": "instrument",
    "unresolved_citation": "citation",
    "source_package": "provenance",
}
GRAPH_EDGE_CATEGORY = {
    "CONTAINS": "scope",
    "CODIFIES": "instrument",
    "CITES": "citation",
    "CITES_UNRESOLVED": "citation",
    "HAS_SOURCE": "provenance",
    "DERIVED_FROM": "provenance",
    "IN_TITLE": "scope",
    "HAS_SECTION": "scope",
}


def graph_node_category(node_type: str) -> str:
    return GRAPH_NODE_CATEGORY.get(str(node_type or ""), "scope")


def graph_edge_category(edge_type: str) -> str:
    return GRAPH_EDGE_CATEGORY.get(str(edge_type or ""), "provenance")


# How each stored edge is used when the Lean corpus is rebuilt from the graph.
# in_formula is false for structure and provenance. Citation is the only
# logical hop that enters a section's definition closure.
LOGICAL_RELATIONS: dict[str, dict[str, str | bool]] = {
    "CONTAINS": {
        "meta_category": "scope",
        "logic_role": "containment",
        "in_formula": False,
        "domain": "title",
        "range": "section",
        "lean_use": "Group a section's spans into one statute file. A title does not absorb its other sections.",
    },
    "CODIFIES": {
        "meta_category": "instrument",
        "logic_role": "codification",
        "in_formula": False,
        "domain": "instrument",
        "range": "section",
        "lean_use": "Record which public law or Statutes at Large citation codifies the section.",
    },
    "CITES": {
        "meta_category": "citation",
        "logic_role": "reference",
        "in_formula": True,
        "domain": "section",
        "range": "section",
        "lean_use": "Definition closure, at most two hops, when the target defines a term used by the source.",
    },
    "CITES_UNRESOLVED": {
        "meta_category": "citation",
        "logic_role": "unresolved_reference",
        "in_formula": False,
        "domain": "section",
        "range": "citation",
        "lean_use": "Keep as a gap. Do not guess the target.",
    },
    "HAS_SOURCE": {
        "meta_category": "provenance",
        "logic_role": "source",
        "in_formula": False,
        "domain": "section",
        "range": "provenance",
        "lean_use": "Source of the text. Exclude from the deontic formula.",
    },
    "DERIVED_FROM": {
        "meta_category": "provenance",
        "logic_role": "derivation",
        "in_formula": False,
        "domain": "node",
        "range": "node",
        "lean_use": "Derivation of a node. Exclude from the deontic formula.",
    },
}


def logical_relation(edge_type: str) -> dict[str, str | bool]:
    return dict(
        LOGICAL_RELATIONS.get(
            str(edge_type or ""),
            {
                "meta_category": "provenance",
                "logic_role": "derivation",
                "in_formula": False,
                "domain": "node",
                "range": "node",
                "lean_use": "Unclassified graph edge. Exclude from the deontic formula.",
            },
        )
    )


CATEGORIES: dict[str, dict[str, str]] = {
    "participant": {
        "deontic_role": "bearer",
        "definition": "A person, office, or institution that can bear a duty, permission, or prohibition.",
    },
    "act": {
        "deontic_role": "conduct",
        "definition": "A verb or course of conduct, including offense names used as acts, such as theft.",
    },
    "state": {
        "deontic_role": "condition",
        "definition": "A condition that holds of a participant or object, such as marriage.",
    },
    "object": {
        "deontic_role": "thing",
        "definition": "A thing that conduct concerns, such as a signature, record, or property.",
    },
    "deontic": {
        "deontic_role": "connector",
        "definition": "The normative link: obligation, permission, or prohibition.",
    },
    "scope": {
        "deontic_role": "scope",
        "definition": "The section or title that limits where a formula applies. Scope is not a domain term.",
    },
    "instrument": {
        "deontic_role": "authority",
        "definition": "A public law or Statutes at Large citation that codifies into the Code.",
    },
    "citation": {
        "deontic_role": "reference",
        "definition": "A resolved or unresolved citation edge. Unresolved citations stay gaps.",
    },
    "provenance": {
        "deontic_role": "source",
        "definition": "Where a text was derived or sourced. Provenance is not part of the deontic formula.",
    },
}

# Longest surface first. Explicit kinds override a later guess from grammar.
LEXICON: tuple[tuple[str, str], ...] = (
    ("the president", "participant"),
    ("a person", "participant"),
    ("congress", "participant"),
    ("police", "participant"),
    ("president", "participant"),
    ("person", "participant"),
    ("agency", "participant"),
    ("theft", "act"),
    ("steal", "act"),
    ("marriage", "state"),
    ("married", "state"),
    ("signature", "object"),
    ("record", "object"),
    ("property", "object"),
)

_MODAL = (
    (re.compile(r"\bshall not\b|\bmust not\b", re.I), "prohibition"),
    (re.compile(r"\bmay not\b", re.I), "prohibition"),
    (re.compile(r"\bmay\b", re.I), "permission"),
    (re.compile(r"\bshall\b|\bmust\b", re.I), "obligation"),
)


def classify_surface(surface: str) -> str:
    """Return the meta-category for a surface form, or an empty string."""

    key = " ".join(str(surface or "").lower().split())
    for lemma, category in LEXICON:
        if key == lemma:
            return category
    return ""


def deontic_formula(
    modality: str,
    *,
    participant: str = "",
    act: str = "",
    object_: str = "",
    state: str = "",
) -> str:
    """Render one deontic atom. Empty roles are omitted. Not an admit."""

    parts = [f"participant:{participant}" if participant else "", f"act:{act}" if act else ""]
    if object_:
        parts.append(f"object:{object_}")
    if state:
        parts.append(f"state:{state}")
    body = ", ".join(part for part in parts if part)
    return f"{modality}({body})"


def _find_terms(text: str) -> list[tuple[str, str]]:
    lowered = f" {text.lower()} "
    found: list[tuple[str, str]] = []
    occupied: list[tuple[int, int]] = []
    for lemma, category in LEXICON:
        start = 0
        needle = lemma.lower()
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            end = index + len(needle)
            if lowered[index - 1].isalnum() or (end < len(lowered) and lowered[end].isalnum()):
                start = index + 1
                continue
            if any(not (end <= left or index >= right) for left, right in occupied):
                start = index + 1
                continue
            occupied.append((index, end))
            found.append((lemma, category))
            start = end
    return found


def modality_of(text: str) -> str:
    for pattern, name in _MODAL:
        if pattern.search(text):
            return name
    return ""


def read_span(text: str, *, legal_id: str = "", span_id: str = "") -> dict[str, Any]:
    """Classify terms in one span and, when roles allow, one deontic link."""

    terms = _find_terms(text)
    modality = modality_of(text)
    participant = next((lemma for lemma, kind in terms if kind == "participant"), "")
    act = next((lemma for lemma, kind in terms if kind == "act"), "")
    object_ = next((lemma for lemma, kind in terms if kind == "object"), "")
    state = next((lemma for lemma, kind in terms if kind == "state"), "")
    link = ""
    if modality and participant and act:
        link = deontic_formula(modality, participant=participant, act=act, object_=object_, state=state)
    return {
        "act": act,
        "admitted": False,
        "formalized": False,
        "formula": link,
        "legal_id": legal_id,
        "modality": modality,
        "object": object_,
        "participant": participant,
        "span_id": span_id,
        "state": state,
        "terms": [{"category": kind, "lemma": lemma} for lemma, kind in terms],
    }


def ontology_rows(spans: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Category definitions, lexicon terms, and deontic links found in spans."""

    rows: list[dict[str, Any]] = []
    for name, spec in CATEGORIES.items():
        rows.append(
            {
                "admitted": False,
                "formalized": False,
                "formula": "",
                "legal_id": "",
                "lemma": name,
                "meta_category": name,
                "record_kind": "category",
                "role": spec["deontic_role"],
                "span_id": "",
                "surface": spec["definition"],
            }
        )
    for lemma, category in LEXICON:
        rows.append(
            {
                "admitted": False,
                "formalized": False,
                "formula": "",
                "legal_id": "",
                "lemma": lemma,
                "meta_category": category,
                "record_kind": "term",
                "role": CATEGORIES[category]["deontic_role"],
                "span_id": "",
                "surface": lemma,
            }
        )
    seen_links: set[tuple[str, str, str]] = set()
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        read = read_span(
            str(span.get("text") or ""),
            legal_id=str(span.get("legal_id") or ""),
            span_id=str(span.get("source_span_id") or span.get("id") or ""),
        )
        if not read["formula"]:
            continue
        key = (read["formula"], read["legal_id"], read["span_id"])
        if key in seen_links:
            continue
        seen_links.add(key)
        rows.append(
            {
                "admitted": False,
                "formalized": False,
                "formula": read["formula"],
                "legal_id": read["legal_id"],
                "lemma": read["act"],
                "meta_category": "deontic",
                "record_kind": "link",
                "role": "connector",
                "span_id": read["span_id"],
                "surface": read["formula"],
            }
        )
    return rows
