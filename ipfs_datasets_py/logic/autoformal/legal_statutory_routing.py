"""Conservative source/context routing before a single-rule O/P/F decoder.

Routes describe explicit structural and lexical evidence. They are neither
legal meanings nor training labels. ``possible_norm`` means a decoder candidate;
it does not mean semantic equivalence, scope closure, or independent review.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import legal_statutory_context as context

SCHEMA = "legal-statutory-context-routing/v1"
ROUTES = ("structural", "definition", "applicability", "interpretive", "notes",
          "incomplete_list", "needs_context", "possible_norm")
_LEAD = re.compile(r"^\([A-Za-z0-9]+\)\s*")
_NORM = re.compile(r"\b(?:shall(?:\s+not)?|must(?:\s+not)?|may(?:\s+not)?)\b", re.I)
_LOCAL_REFERENCE = re.compile(r"\b(subsection|paragraph|subparagraph|clause)\s+((?:\([A-Za-z0-9]+\))+)", re.I)
_EXTERNAL_REFERENCE = re.compile(r"\b(?:sections?|titles?)\s+[0-9]+[A-Za-z]*(?:\([A-Za-z0-9]+\))*", re.I)
_SELF_REFERENCE = re.compile(r"\b(?:this|such|the preceding)\s+(?:section|subsection|paragraph|subparagraph|chapter|subchapter|title)\b", re.I)
_DEFINITION = re.compile(r'\b(?:the\s+)?terms?\s+[\s\S]{1,180}?\s+(?:means?|includes?|has\s+the\s+meaning|have\s+the\s+meanings)\b', re.I)
_APPLICABILITY = re.compile(r"\b(?:shall\s+(?:not\s+)?apply|shall\s+take\s+effect|takes?\s+effect)\b", re.I)
_INTERPRETIVE = re.compile(r"\b(?:shall\s+be\s+(?:deemed|construed)|nothing\s+in\s+.+?\s+(?:authorizes?|shall\s+be\s+construed))\b", re.I)


def file_ref(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def read_ref(pin: dict) -> Any:
    if file_ref(pin["path"]) != {k: pin[k] for k in ("path", "sha256", "bytes")}:
        raise ValueError("source document reference changed")
    return json.loads(Path(pin["path"]).read_text())


def _expected_views(document: dict) -> list[dict]:
    """Reconstruct the frozen diagnostic-view contract without reading labels."""
    body = [p for p in document["paragraphs"] if p["kind"] == "codified_body"]
    rows = []
    def add(kind, start, end, suffix, path):
        text = document["document_text"][start:end]
        rows.append({"id": document["document_id"] + ":" + suffix, "kind": kind,
                     "source_text": text, "source_sha256": context.sha(text),
                     "document_id": document["document_id"], "legal_id": document["legal_id"],
                     "section_heading": document["heading"], "edition": document["edition"],
                     "char_start": start, "char_end": end, "subsection_path": path,
                     "split": "exposed_diagnostic_only", "independent_reference": None,
                     "training_qualified": False})
    for row in body:
        add("paragraph", row["char_start"], row["char_end"], f"paragraph-{row['paragraph_index']}", row["subsection_path"])
    for row in document["blocks"]:
        if row["descendant_paragraphs"]:
            add("enclosing_block", row["char_start"], row["char_end"], f"block-{row['paragraph_index']}", row["subsection_path"])
    add("full_codified_body", body[0]["char_start"], body[-1]["char_end"], "codified-body", None)
    notes = [p for p in document["paragraphs"] if p["kind"] == "notes_or_other"]
    if notes:
        row = notes[0]
        add("notes_control", row["char_start"], row["char_end"], f"notes-{row['paragraph_index']}", None)
    return rows


def validate_source(source: dict, document: dict, raw_html: bytes) -> None:
    context.validate_document(document, raw_html)
    if read_ref(source["document"]) != document:
        raise ValueError("caller document differs from source document reference")
    matches = [row for row in _expected_views(document) if row["id"] == source.get("id")]
    if len(matches) != 1 or any(source.get(k) != v for k, v in matches[0].items()):
        raise ValueError("caller source differs from official diagnostic view")


def _caption(text: str) -> tuple[str | None, str]:
    text = _LEAD.sub("", text).strip()
    match = re.match(r"^([^.!?]{1,100})\s*\.\s*—\s*(.*)$", text, re.S)
    if match:
        return match.group(1).strip().casefold(), match.group(2).strip()
    return None, text


def _paragraph_route(paragraph: dict, body: list[dict]) -> str | None:
    if paragraph["kind"] != "codified_body":
        return "notes"
    caption, tail = _caption(paragraph["text"])
    ancestors = [p for p in body if p["subsection_path"] and paragraph["subsection_path"]
                 and paragraph["subsection_path"].startswith(p["subsection_path"])
                 and p["subsection_path"] != paragraph["subsection_path"]]
    definition_ancestor = any(_caption(p["text"])[0] in ("definition", "definitions") for p in ancestors)
    if caption in ("definition", "definitions") or definition_ancestor or _DEFINITION.search(tail):
        return "definition"
    if caption in ("applicability", "effective date", "effective dates") or _APPLICABILITY.search(tail):
        return "applicability"
    if caption in ("rule of construction", "construction") or _INTERPRETIVE.search(tail):
        return "interpretive"
    if caption and not tail:
        return "structural"
    return None


def _interval(document: dict, start: int, end: int, **metadata) -> dict:
    text = document["document_text"][start:end]
    return {"char_start": start, "char_end": end, "text": text, "text_sha256": context.sha(text), **metadata}


def _reference_evidence(document: dict, paragraphs: list[dict], *, origin: str) -> list[dict]:
    body = [p for p in document["paragraphs"] if p["kind"] == "codified_body"]
    by_path = {p["subsection_path"]: p for p in body if p["subsection_path"]}
    blocks = {b["paragraph_index"]: b for b in document["blocks"]}
    results = []
    for paragraph in paragraphs:
        text = paragraph["text"]
        for pattern, kind in [(_LOCAL_REFERENCE, "same_section_locator"),
                              (_EXTERNAL_REFERENCE, "external_section_or_title"),
                              (_SELF_REFERENCE, "relative_context_reference")]:
            for match in pattern.finditer(text):
                target = None
                if kind == "same_section_locator":
                    level, label = match.groups()
                    labels = re.findall(r"\([A-Za-z0-9]+\)", paragraph["subsection_path"] or "")
                    retain = {"subsection": 0, "paragraph": 1, "subparagraph": 2, "clause": 3}[level.casefold()]
                    if len(labels) >= retain:
                        target = by_path.get("".join(labels[:retain]) + label)
                item = {"origin": origin, "kind": kind, "text": match.group(),
                        "char_start": paragraph["char_start"] + match.start(),
                        "char_end": paragraph["char_start"] + match.end(),
                        "paragraph_index": paragraph["paragraph_index"],
                        "locator_resolved": target is not None, "semantic_dependency_resolved": False}
                if target:
                    block = blocks[target["paragraph_index"]]
                    item["target"] = _interval(document, block["char_start"], block["char_end"],
                                               subsection_path=target["subsection_path"],
                                               paragraph_index=target["paragraph_index"])
                results.append(item)
    return results


def route_source(source: dict, document: dict, raw_html: bytes) -> dict:
    """Validate exact source identity and produce a conservative routing decision."""
    validate_source(source, document, raw_html)
    body = [p for p in document["paragraphs"] if p["kind"] == "codified_body"]
    included = [p for p in document["paragraphs"] if source["char_start"] <= p["char_start"] and p["char_end"] <= source["char_end"]]
    source_indices = {p["paragraph_index"] for p in included}
    ancestors = []
    for p in body:
        if p["paragraph_index"] in source_indices or not p["subsection_path"]:
            continue
        if any(q["subsection_path"] and q["subsection_path"].startswith(p["subsection_path"])
               and q["subsection_path"] != p["subsection_path"] for q in included):
            ancestors.append(p)
    definition_roots = [p for p in body if _caption(p["text"])[0] in ("definition", "definitions")]
    definitions = [p for p in body if _paragraph_route(p, body) == "definition" and
                   not any(root["subsection_path"] and p["subsection_path"] and
                           p["subsection_path"].startswith(root["subsection_path"]) and
                           p["paragraph_index"] != root["paragraph_index"] for root in definition_roots)]
    applicability = [p for p in body if _paragraph_route(p, body) == "applicability"]
    block_by_index = {b["paragraph_index"]: b for b in document["blocks"]}
    def evidence(paragraphs, whole_block=False):
        result = []
        for p in paragraphs:
            end = block_by_index[p["paragraph_index"]]["char_end"] if whole_block else p["char_end"]
            result.append(_interval(document, p["char_start"], end, paragraph_index=p["paragraph_index"],
                                    subsection_path=p["subsection_path"], kind=p["kind"]))
        return result
    relevant_context_indices = {p["paragraph_index"] for p in ancestors + definitions + applicability}
    for p in definitions + applicability:
        relevant_context_indices.update(block_by_index[p["paragraph_index"]]["descendant_paragraphs"])
    context_paragraphs = [p for p in body if p["paragraph_index"] in relevant_context_indices and p["paragraph_index"] not in source_indices]
    source_refs = _reference_evidence(document, included, origin="source")
    context_refs = _reference_evidence(document, context_paragraphs, origin="context_bundle")
    used_defined_terms = []
    for p in context_paragraphs:
        if _paragraph_route(p, body) != "definition":
            continue
        definition = re.search(r"\bterms?\s+(.{1,180}?)\s+(?:means?|includes?|has\s+the\s+meaning|have\s+the\s+meanings)\b", p["text"], re.I)
        if not definition:
            continue
        for term in re.findall(r'["“\u2018\']([^"”\u2019\']+)["”\u2019\']', definition.group(1)):
            hits = list(re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", source["source_text"], re.I))
            if hits:
                used_defined_terms.append({"term": term, "definition_paragraph_index": p["paragraph_index"],
                                           "definition_subsection_path": p["subsection_path"],
                                           "source_occurrences": [{"char_start": m.start(), "char_end": m.end()} for m in hits],
                                           "semantic_dependency_resolved": False})
    omitted_applicability = [p for p in applicability if p["paragraph_index"] not in source_indices]
    categories = [_paragraph_route(p, body) for p in included]
    reasons, route = [], None
    specialized = {r for r in categories if r not in (None, "structural")}
    if source["kind"] == "notes_control":
        route, reasons = "notes", ["official paragraph belongs to notes/other region"]
    elif specialized and all(r in specialized or r == "structural" for r in categories) and len(specialized) == 1:
        route = next(iter(specialized)); reasons = ["explicit heading, ancestry, or lexical construction identifies another logic route"]
    elif specialized:
        route, reasons = "needs_context", ["view combines distinct structural or logic routes"]
    elif categories and all(r == "structural" for r in categories):
        route, reasons = "structural", ["heading without an asserted clause"]
    norm_matches = list(_NORM.finditer(source["source_text"]))
    content_ancestors = [p for p in ancestors if _paragraph_route(p, body) != "structural"]
    if route is None:
        tail = source["source_text"].rstrip()
        labelled_tail = source["kind"] == "paragraph" and included[0]["leading_label"] is not None and not norm_matches
        if tail.endswith((";", "—", ":")) or (labelled_tail and ancestors):
            route, reasons = "incomplete_list", ["list introduction or dependent list item is not a complete standalone norm"]
        elif content_ancestors:
            route, reasons = "needs_context", ["substantive ancestor meaning is outside the selected source interval"]
        elif omitted_applicability:
            route, reasons = "needs_context", ["same-section applicability evidence is outside the selected source interval"]
        elif used_defined_terms:
            route, reasons = "needs_context", ["an explicitly used same-section defined term requires semantic resolution"]
        elif len(included) > 1:
            route, reasons = "needs_context", ["multiple body paragraphs require composition beyond one flat rule"]
        elif len(norm_matches) != 1:
            route, reasons = "needs_context", ["no single explicit normative operator" if not norm_matches else "multiple normative operators require rule-count and scope resolution"]
        elif _NORM.match(_caption(source["source_text"])[1]) or re.match(r"^(?:and|or)\b", _caption(source["source_text"])[1], re.I) or tail.endswith(("...", "…")):
            route, reasons = "needs_context", ["missing explicit actor, connective continuation, or visibly truncated clause"]
        elif source_refs:
            route, reasons = "needs_context", ["source references require semantic resolution even when a local locator is found"]
        elif re.search(r"\b(?:he|she|they|it|such\s+(?:person|agency|officer|entity)|the\s+foregoing)\b", source["source_text"], re.I):
            route, reasons = "needs_context", ["explicit anaphoric wording requires antecedent resolution"]
        else:
            route, reasons = "possible_norm", ["one explicit normative operator and no recognized standalone-profile exclusion"]
    bundle = {"document": source["document"], "document_id": document["document_id"],
              "legal_id": document["legal_id"], "section_heading": document["heading"],
              "edition": document["edition"], "source_url": document["source_url"],
              "html_sha256": document["html_sha256"], "document_text_sha256": document["document_text_sha256"],
              "offset_coordinate_system": document["offset_coordinate_system"],
              "source_intervals": evidence(included), "ancestors": evidence(ancestors),
              "same_section_definitions": evidence(definitions, True),
              "same_section_applicability": evidence(applicability, True),
              "source_references": source_refs, "context_references": context_refs,
              "explicitly_used_defined_terms": used_defined_terms,
              "unresolved_cross_references": [r for r in source_refs + context_refs if not r["locator_resolved"]],
              "resolved_local_locators": [r for r in source_refs + context_refs if r["locator_resolved"]],
              "context_resolved": False, "semantic_closure_verified": False,
              "definition_relevance": "same-section overinclusive candidate context; legal applicability unreviewed"}
    return {"schema": SCHEMA, "source_id": source["id"], "source_sha256": source["source_sha256"],
            "source_identity": {k: source[k] for k in ("document_id", "legal_id", "section_heading", "edition", "kind", "char_start", "char_end", "subsection_path")},
            "route": route, "decoder_eligible": route == "possible_norm", "reasons": reasons,
            "normative_operator_cues": [{"text": m.group(), "source_char_start": m.start(), "source_char_end": m.end()} for m in norm_matches],
            "context_bundle": bundle, "context_resolved": False, "semantic_rejection": False,
            "reference_accuracy": None, "source_semantics_verified": False,
            "independently_reviewed": False, "training_qualified": False,
            "limitations": ["Routing is an explicit structural/lexical profile, not legal classification gold.",
                            "Noneligible includes meaningful laws requiring other logic families or more context; it never means legally meaningless.",
                            "A resolved local locator is not a resolved legal dependency.",
                            "Possible norms still need decoding, preservation checks, independent legal review and formal validation.",
                            "Context bundles retain evidence; the existing source-only decoder does not automatically consume them."]}
