"""Meta-ontology for deontic terms found in statute spans.

Categories sit above the statute graph. A title or section is scope, not a
term. Theft is an act, marriage is a state, a signature is an object, and
police, the president, Congress, and a person are participants. A formula
built from those roles is not a legal admit.
"""
from __future__ import annotations

import json
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


_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_ROLE_KINDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal", "qualifiers")
_LIST_FIELDS = ("definition_targets", "gap_span_ids", "open_stitch_slots", "reasons")


def normalize_lookup(surface: str) -> str:
    """Lookup key: lowercase, collapsed space, one leading article removed.

    The stored surface keeps the compiler text. ``theft`` stays distinct from
    ``steal``. ``habeas corpus`` stays a two-word phrase.
    """

    key = " ".join(str(surface or "").lower().split())
    return " ".join(_LEADING_ARTICLE.sub("", key, count=1).split())


def _phrase_pattern(query: str) -> re.Pattern[str] | None:
    parts = [part for part in normalize_lookup(query).split(" ") if part]
    if not parts:
        return None
    body = r"\s+".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.IGNORECASE)


def contains_lookup_phrase(value: str, query: str) -> bool:
    """True when ``query`` equals ``value`` or sits inside it as whole words.

    A letter on either side blocks the match. The phrase ``habeas corpus``
    does not match a value that is only the word ``corpus``.
    """

    hay = normalize_lookup(value)
    needle = normalize_lookup(query)
    if not hay or not needle:
        return False
    if hay == needle:
        return True
    pattern = _phrase_pattern(needle)
    if pattern is None:
        return False
    return pattern.search(hay) is not None


def _rule_of(span: Mapping[str, Any]) -> dict[str, Any]:
    rule = span.get("rule")
    if isinstance(rule, str):
        try:
            rule = json.loads(rule or "{}")
        except json.JSONDecodeError:
            rule = None
    if isinstance(rule, Mapping):
        return dict(rule)
    raw = span.get("rule_json")
    if isinstance(raw, str) and raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(loaded) if isinstance(loaded, Mapping) else {}
    return {}


def _first_item(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
    return ""


def _state_of(rule: Mapping[str, Any]) -> str:
    return _first_item(rule.get("conditions")) or _first_item(rule.get("temporal"))


def _clause_logic(span: Mapping[str, Any]) -> dict[str, str]:
    rule = _rule_of(span)
    participant = str(rule.get("actor") or "").strip()
    act = str(rule.get("action") or "").strip()
    object_ = str(rule.get("object") or "").strip()
    modality = str(rule.get("modality") or "").strip()
    state = _state_of(rule)
    formula = ""
    if modality and participant and act:
        formula = deontic_formula(modality, participant=participant, act=act, object_=object_, state=state)
    return {
        "act": act,
        "formula": formula,
        "modality": modality,
        "object": object_,
        "participant": participant,
        "state": state,
    }


def _occurrence(**fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "act": "",
        "admitted": False,
        "category": "",
        "definition_targets": [],
        "document_id": "",
        "document_label": "",
        "entity_id": "",
        "formalized": False,
        "formula": "",
        "gap_span_ids": [],
        "hit_kind": "",
        "kind": "",
        "legal_id": "",
        "modality": "",
        "normalized": "",
        "object": "",
        "open_stitch_slots": [],
        "participant": "",
        "reasons": [],
        "section_label": "",
        "span_id": "",
        "state": "",
        "surface": "",
        "term_id": "",
    }
    row.update(fields)
    row["admitted"] = False
    row["formalized"] = False
    return row


def _category_for(kind: str, value: str) -> str:
    from .entity_cache import term_category

    return term_category(kind, value)


def occurrences_for_span(span: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Role rows for one sealed clause, plus lexicon mentions the roles do not already carry."""

    if not isinstance(span, Mapping):
        return []
    from .span_cache import terms_from_rule

    logic = _clause_logic(span)
    rule = _rule_of(span)
    span_id = str(span.get("source_span_id") or span.get("id") or "")
    legal_id = str(span.get("legal_id") or "")
    text = str(span.get("source_text") or span.get("text") or "")
    rows: list[dict[str, Any]] = []
    role_keys: set[str] = set()
    for term in terms_from_rule(rule):
        kind = str(term.get("kind") or "")
        if kind not in _ROLE_KINDS:
            continue
        value = str(term.get("value") or "")
        normalized = normalize_lookup(value)
        role_keys.add(normalized)
        rows.append(
            _occurrence(
                act=logic["act"],
                category=_category_for(kind, value),
                formula=logic["formula"],
                hit_kind="role",
                kind=kind,
                legal_id=legal_id,
                modality=logic["modality"],
                normalized=normalized,
                object=logic["object"],
                participant=logic["participant"],
                span_id=span_id,
                state=logic["state"],
                surface=value,
                term_id=str(term.get("term_id") or ""),
            )
        )
    for lemma, category in _find_terms(text):
        normalized = normalize_lookup(lemma)
        if normalized in role_keys:
            continue
        role_keys.add(normalized)
        rows.append(
            _occurrence(
                act=logic["act"],
                category=category,
                formula=logic["formula"],
                hit_kind="mention",
                legal_id=legal_id,
                modality=logic["modality"],
                normalized=normalized,
                object=logic["object"],
                participant=logic["participant"],
                span_id=span_id,
                state=logic["state"],
                surface=lemma,
            )
        )
    return rows


def mention_for_span(span: Mapping[str, Any], query: str) -> dict[str, Any] | None:
    """A text mention of ``query``. Absent when a role on the span already carries it.

    The matched words stay in ``surface``. The clause formula is copied when the
    sealed rule has a modality, a participant, and an act. Not an admit.
    """

    if not isinstance(span, Mapping):
        return None
    normalized = normalize_lookup(query)
    if len(normalized) < 3:
        return None
    text = str(span.get("source_text") or span.get("text") or "")
    pattern = _phrase_pattern(normalized)
    if pattern is None:
        return None
    found = pattern.search(text)
    if found is None and not contains_lookup_phrase(text, normalized):
        return None
    if any(
        row["hit_kind"] == "role" and contains_lookup_phrase(str(row.get("surface") or ""), normalized)
        for row in occurrences_for_span(span)
    ):
        return None
    if found is None:
        surface = normalized
    else:
        surface = " ".join(found.group(0).split())
    logic = _clause_logic(span)
    return _occurrence(
        act=logic["act"],
        category=classify_surface(surface),
        formula=logic["formula"],
        hit_kind="mention",
        legal_id=str(span.get("legal_id") or ""),
        modality=logic["modality"],
        normalized=normalize_lookup(surface),
        object=logic["object"],
        participant=logic["participant"],
        span_id=str(span.get("source_span_id") or span.get("id") or ""),
        state=logic["state"],
        surface=surface,
    )


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return list(loaded) if isinstance(loaded, list) else []
    return []


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    public = dict(row)
    public["admitted"] = False
    public["formalized"] = False
    for key in _LIST_FIELDS:
        if key in public:
            public[key] = _as_list(public.get(key))
    return public


def _match_rank(row: Mapping[str, Any], normalized: str) -> int | None:
    hit = str(row.get("hit_kind") or "")
    surface = str(row.get("normalized") or row.get("surface") or "")
    exact = bool(surface) and normalize_lookup(surface) == normalized
    inside = bool(surface) and not exact and contains_lookup_phrase(surface, normalized)
    labels = {
        normalize_lookup(str(row.get("section_label") or "")),
        normalize_lookup(str(row.get("document_label") or "")),
    }
    identifiers = {
        normalize_lookup(str(row.get(key) or ""))
        for key in ("legal_id", "entity_id", "document_id")
    }
    label_hit = normalized in labels
    id_hit = normalized in identifiers
    if not (exact or inside or label_hit or id_hit):
        return None
    if hit == "role" and exact:
        return 0
    if hit == "role":
        return 1
    if hit == "mention" and not label_hit and not id_hit:
        return 3
    if hit == "label" or label_hit or id_hit:
        if hit == "mention":
            return 3
        return 2
    if hit == "mention":
        return 3
    return 2


def lookup_logic(rows: Sequence[Mapping[str, Any]], query: str) -> dict[str, Any]:
    """Filter occurrence rows for one surface, section, or document. Not an admit.

    Exact role equality comes before a whole-word hit inside a longer role, then
    a label, then a mention. A query shorter than three characters is refused.
    Nothing is dropped to fit a cap.
    """

    normalized = normalize_lookup(query)
    if len(normalized) < 3:
        raise ValueError("lookup query must be at least three characters")
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        rank = _match_rank(row, normalized)
        if rank is None:
            continue
        ranked.append((rank, _public_row(row)))
    ranked.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("legal_id") or ""),
            str(item[1].get("span_id") or ""),
            str(item[1].get("kind") or ""),
            str(item[1].get("term_id") or ""),
        )
    )
    chosen = [row for _, row in ranked]
    roles = [row for row in chosen if row.get("hit_kind") == "role"]
    labels = [row for row in chosen if row.get("hit_kind") == "label"]
    mentions = [row for row in chosen if row.get("hit_kind") == "mention"]
    category = ""
    for row in roles:
        if row.get("category") and normalize_lookup(str(row.get("normalized") or "")) == normalized:
            category = str(row["category"])
            break
    if not category:
        category = classify_surface(normalized)
    if not category:
        for row in roles:
            if row.get("category"):
                category = str(row["category"])
                break
    kinds = sorted({str(row.get("kind") or "") for row in roles if row.get("kind")})
    return {
        "admitted": False,
        "category": category,
        "formalized": False,
        "kinds": kinds,
        "labels": labels,
        "mentions": mentions,
        "normalized": normalized,
        "query": str(query),
        "roles": roles,
        "rows": chosen,
    }


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
