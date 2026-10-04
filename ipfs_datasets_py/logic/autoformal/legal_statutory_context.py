"""Versioned official-US-Code paragraph context for diagnostic formalization.

This reads GovInfo's explicit paragraph classes, never guesses subsection
structure from inline references.  Source text and hierarchy are evidence for a
reviewer, not independently reviewed legal meanings.  Notes may themselves have
legal effect; distinguishing them from the codified body is not discarding them.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

SCHEMA = "legal-official-statutory-context/v1"
_BODY = re.compile(r"statutory-body(?:-(\d+)em)?\Z")
_LABEL = re.compile(r"^\(([A-Za-z0-9]+)\)")
_CUES = {
    "condition": r"\b(?:if|provided that|subject to|only if)\b",
    "exception": r"\b(?:unless|except|shall not apply|may waive)\b",
    "temporal": r"\b(?:until|after|before|not later than|take effect|days|months|years)\b",
    "limiting_scope": r"\b(?:only|to the maximum extent practicable|in carrying out this section)\b",
    "negative_construction": r"\bNothing in this section shall be construed\b",
    "defined_term": r"\b(?:means|meaning|meanings)\b",
    "cross_reference": r"\b(?:paragraph|subparagraph|subsection|section|sections|title)\s+(?:\([A-Za-z0-9]+\)|\d+)",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    return " ".join(text.split())


def extract_document(raw: bytes, *, url: str, edition: int, legal_id: str) -> dict:
    """Extract visible paragraphs, preserving exact offsets in the new view.

    Offsets address ``document_text`` (a declared normalized visible-text view),
    not HTML bytes or legacy-parquet text.  HTML bytes must be retained by the
    caller.  Heading + URL distinguish duplicate section numbers.
    """
    from bs4 import BeautifulSoup

    if type(raw) is not bytes or not 1 <= len(raw) <= 8_000_000:
        raise ValueError("bounded nonempty HTML bytes required")
    if type(edition) is not int or f"/USCODE-{edition}-" not in url:
        raise ValueError("explicit URL-bound historical edition required")
    if not url.startswith("https://www.govinfo.gov/content/pkg/USCODE-"):
        raise ValueError("official GovInfo content URL required")
    identity = re.fullmatch(r"usc:us:([0-9]+):([0-9]+[A-Za-z]*)", legal_id)
    parsed_url = urlsplit(url)
    if not identity or parsed_url.query or parsed_url.fragment:
        raise ValueError("explicit section identity and clean official URL required")
    title, section = identity.groups()
    prefix = f"/content/pkg/USCODE-{edition}-title{title}/html/USCODE-{edition}-title{title}-"
    if not parsed_url.path.startswith(prefix) or not re.search(r"-sec" + re.escape(section) + r"(?:-[0-9]+)?\.htm$", parsed_url.path):
        raise ValueError("legal identity differs from edition, title or section URL")
    soup = BeautifulSoup(raw, "html.parser")
    headings = soup.select("h3.section-head")
    if len(headings) != 1:
        raise ValueError("one unambiguous official section heading required")
    heading = normalize(headings[0].get_text())
    if not re.match(r"^§" + re.escape(section) + r"(?:\.|\s)", heading):
        raise ValueError("legal identity differs from official section heading")
    paragraphs, texts, stack, position, notes = [], [], [], 0, []
    for tag in soup.find_all(["p", "h4"]):
        classes = tag.get("class", [])
        text = normalize(tag.get_text())
        if not text:
            continue
        if tag.name == "h4":
            notes.append(text)
            continue
        match = next((m for c in classes if (m := _BODY.fullmatch(c))), None)
        kind = "codified_body" if match else "source_credit" if "source-credit" in classes else "notes_or_other"
        if match and notes:
            raise ValueError("codified body cannot resume after note headings")
        depth, label, path, parent = None, None, None, None
        if match:
            depth = int(match.group(1) or 0)
            lead = _LABEL.match(text)
            label = lead.group(1) if lead else None
            while stack and stack[-1][0] >= depth:
                stack.pop()
            parent = stack[-1][1] if stack else None
            path = (parent or "") + f"({label})" if label else None
            if path:
                stack.append((depth, path))
        row = {"paragraph_index": len(paragraphs), "kind": kind, "classes": classes,
               "text": text, "text_sha256": sha(text), "char_start": position,
               "char_end": position + len(text), "indent_depth": depth,
               "leading_label": label, "subsection_path": path, "parent_path": parent,
               "note_headings": list(notes) if kind == "notes_or_other" else [],
               "linked_references": [{"text": normalize(a.get_text()), "href": a.get("href")}
                                     for a in tag.find_all("a", href=True)]}
        paragraphs.append(row)
        texts.append(text)
        position += len(text) + 1
    body = [p for p in paragraphs if p["kind"] == "codified_body"]
    if not body or not heading.startswith("§"):
        raise ValueError("official codified section body required")
    body_indices = [p["paragraph_index"] for p in body]
    if body_indices != list(range(body_indices[0], body_indices[-1] + 1)):
        raise ValueError("codified body must be contiguous; interleaved notes require another mapping profile")
    document_text = "\n".join(texts)
    blocks = []
    for index, row in enumerate(body):
        end = row["char_end"]
        descendants = []
        for child in body[index + 1:]:
            if child["indent_depth"] <= row["indent_depth"]:
                break
            descendants.append(child["paragraph_index"])
            end = child["char_end"]
        blocks.append({"paragraph_index": row["paragraph_index"], "subsection_path": row["subsection_path"],
                       "char_start": row["char_start"], "char_end": end,
                       "descendant_paragraphs": descendants,
                       "text_sha256": sha(document_text[row["char_start"]:end])})
    return {"schema": SCHEMA, "legal_id": legal_id, "edition": edition, "source_url": url,
            "heading": heading, "document_id": "govinfo-html-sha256:" + hashlib.sha256(raw).hexdigest(),
            "html_sha256": hashlib.sha256(raw).hexdigest(), "document_text": document_text,
            "document_text_sha256": sha(document_text), "paragraphs": paragraphs, "blocks": blocks,
            "offset_coordinate_system": "Unicode code points in normalized visible paragraph text joined by LF",
            "cross_reference_closure_verified": False, "source_semantics_verified": False,
            "independently_reviewed": False, "training_qualified": False}


def validate_document(document: dict, raw: bytes) -> None:
    expected = extract_document(raw, url=document["source_url"], edition=document["edition"],
                                legal_id=document["legal_id"])
    if document != expected:
        raise ValueError("official document differs from deterministic HTML extraction")


def source_cues(text: str) -> list[dict]:
    """Literal review cues only; neither exhaustive semantics nor gold labels."""
    cues = []
    for kind, pattern in _CUES.items():
        for match in re.finditer(pattern, text, re.I):
            cues.append({"kind": kind, "text": match.group(), "char_start": match.start(), "char_end": match.end()})
    return sorted(cues, key=lambda row: (row["char_start"], row["kind"]))


def inspect_prediction(source: dict, prediction: dict) -> dict:
    """Return checkable lexical and context gaps, without an accuracy claim."""
    text = source["source_text"]
    if prediction.get("source_sha256") != sha(text):
        raise ValueError("prediction/source hash mismatch")
    canonical = prediction.get("canonical_ir")
    strings = []
    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str):
            strings.append(normalize(value).casefold())
    collect(canonical)
    cues = [{**cue, "literal_retained_in_any_canonical_string":
             any(normalize(cue["text"]).casefold() in value for value in strings)} for cue in source_cues(text)]
    return {"source_id": source["id"], "decoder_status": prediction["status"], "source_cues": cues,
            "unretained_cues": [cue for cue in cues if not cue["literal_retained_in_any_canonical_string"]],
            "is_codified_body_input": source["kind"] != "notes_control",
            "context_supplied_to_decoder": False, "full_document_available_to_reviewer": True,
            "context_resolution_verified": False, "reference_accuracy": None,
            "source_semantics_verified": False, "training_qualified": False,
            "limitations": "Literal cue accounting is incomplete and can neither prove nor disprove legal equivalence."}
