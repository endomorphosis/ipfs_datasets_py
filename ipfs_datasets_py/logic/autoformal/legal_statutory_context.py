"""Versioned official-US-Code paragraph context for diagnostic formalization.

This reads GovInfo's explicit paragraph classes, never guesses subsection
structure from inline references.  Source text and hierarchy are evidence for a
reviewer, not independently reviewed legal meanings.  Notes may themselves have
legal effect; distinguishing them from the codified body is not discarding them.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import re
from html.parser import HTMLParser
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


class _EncodingDeclarations(HTMLParser):
    """Read actual markup declarations, excluding comments and script text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.encodings = []

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        for name, value in attrs:
            if name == "charset":
                self.encodings.append(value)
        if any(name == "http-equiv" and (value or "").strip().lower() == "content-type"
               for name, value in attrs):
            for name, value in attrs:
                if name == "content":
                    labels = re.findall(r"\bcharset\s*=\s*[\"']?([^;\s\"']+)",
                                        value or "", re.I)
                    if re.search(r"\bcharset\s*=", value or "", re.I) and not labels:
                        raise ValueError("nonempty explicit source HTML encoding required")
                    self.encodings.extend(labels)

    def handle_pi(self, data):
        if re.match(r"xml\s", data, re.I):
            self.encodings.extend(re.findall(
                r"\bencoding\s*=\s*[\"']([^\"']+)[\"']", data, re.I))


def _decode_source_html(raw: bytes) -> str:
    """Honor exact declared encodings; undeclared source must be valid UTF8.

    Byte hashes retain the original input. A deterministic strict decode keeps
    optional detector packages from changing source text and occurrence offsets.
    Contradictory declarations, unsupported codecs and malformed bytes abstain.
    """
    bom, compatible = None, set()
    for marker, encoding, aliases in (
        (codecs.BOM_UTF32_LE, "utf-32", {"utf-32", "utf-32-le"}),
        (codecs.BOM_UTF32_BE, "utf-32", {"utf-32", "utf-32-be"}),
        (codecs.BOM_UTF16_LE, "utf-16", {"utf-16", "utf-16-le"}),
        (codecs.BOM_UTF16_BE, "utf-16", {"utf-16", "utf-16-be"}),
        (codecs.BOM_UTF8, "utf-8-sig", {"utf-8", "utf-8-sig"}),
    ):
        if raw.startswith(marker):
            bom, compatible = encoding, aliases
            break
    try:
        # Latin1 preserves ASCII declaration syntax without guessing body text.
        declarations = _EncodingDeclarations()
        declarations.feed(raw.decode(bom or "latin-1", errors="strict"))
        declarations.close()
        names = set()
        for label in declarations.encodings:
            if not isinstance(label, str) or not label.strip():
                raise ValueError("nonempty explicit source HTML encoding required")
            names.add(codecs.lookup(label.strip()).name)
        if len(names) > 1 or bom and names and not names <= compatible:
            raise ValueError("conflicting source HTML encoding declarations")
        encoding = bom or next(iter(names), "utf-8")
        return raw.decode(encoding, errors="strict")
    except (LookupError, UnicodeError) as error:
        raise ValueError("source HTML must strictly decode under its declared encoding or UTF8") from error


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
    soup = BeautifulSoup(_decode_source_html(raw), "html.parser")
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


# Additive v2 contracts. The v1 extraction dictionary and validation entry point
# above intentionally retain their original schema and output.
VIEW_SCHEMA = "legal-statutory-normalized-document-view/v2"
SELECTOR_SCHEMA = "legal-statutory-view-occurrence-selector/v2"
CONTEXT_PACKET_SCHEMA = "legal-statutory-context-obligations/v2"
NORMALIZATION_PROFILE = "govinfo-visible-paragraph-whitespace-collapse-lf/v1"
DEPENDENCY_KINDS = ("definition", "authority", "antecedent", "shared_qualifier",
                    "temporal_origin", "referenced_provision")
MAX_CONTEXT_PACKET_BYTES = 32 * 1024 * 1024
MAX_SELECTOR_BYTES = 64 * 1024
MAX_OCCURRENCES = 4096
_VIEW_ID = re.compile(r"legal-normalized-view:sha256:[0-9a-f]{64}\Z")
_REQUEST_KEYS = {"kind", "availability", "locator", "expected_view_id", "candidate_selector"}
_SELECTOR_KEYS = {"schema", "view_id", "document_id", "char_start", "char_end", "utf8_byte_start",
                  "utf8_byte_end", "text", "text_sha256", "occurrence_id"}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _context_wire(value) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise ValueError("bounded finite UTF8 JSON context required") from error
    _require(len(encoded) <= MAX_CONTEXT_PACKET_BYTES, "context packet byte bound exceeded")
    return encoded


def _context_digest(value) -> str:
    return hashlib.sha256(_context_wire(value)).hexdigest()


def normalized_document_view(document: dict, raw: bytes) -> dict:
    """Authenticate v1 extraction and name its immutable normalized text view.

    Both selector units refer exclusively to the extracted ``document_text``.
    The HTML digest binds custody; it is never an HTML byte-offset mapping.
    """
    _require(type(document) is dict and document.get("schema") == SCHEMA
             and all(key in document for key in ("source_url", "edition", "legal_id")),
             "v1 official document extraction required")
    expected = extract_document(raw, url=document["source_url"], edition=document["edition"],
                                legal_id=document["legal_id"])
    _require(_context_wire(document) == _context_wire(expected),
             "document differs from exact immutable normalized extraction")
    text = document["document_text"]
    identity = {"schema": VIEW_SCHEMA, "normalization_profile": NORMALIZATION_PROFILE,
                **{key: document[key] for key in ("document_id", "legal_id", "edition", "source_url",
                                                  "html_sha256", "document_text_sha256")}}
    return {**identity, "view_id": "legal-normalized-view:sha256:" + _context_digest(identity),
            "unicode_code_points": len(text), "utf8_bytes": len(text.encode("utf-8")),
            "char_coordinate_system": "Unicode code points in document_text; half-open",
            "byte_coordinate_system": "UTF8 bytes of document_text; half-open",
            "raw_html_coordinate_mapping_verified": False}


def _selector(document: dict, view: dict, char_start: int, char_end: int) -> dict:
    text = document["document_text"]
    _require(type(char_start) is int and type(char_end) is int
             and 0 <= char_start < char_end <= len(text), "bounded nonempty character selector required")
    selected = text[char_start:char_end]
    _require(len(selected.encode("utf-8")) <= MAX_SELECTOR_BYTES, "selected source byte bound exceeded")
    identity = {"schema": SELECTOR_SCHEMA, "view_id": view["view_id"],
                "document_id": document["document_id"], "char_start": char_start, "char_end": char_end,
                "utf8_byte_start": len(text[:char_start].encode("utf-8")),
                "utf8_byte_end": len(text[:char_end].encode("utf-8")),
                "text": selected, "text_sha256": sha(selected)}
    return {**identity, "occurrence_id": "legal-view-occurrence:sha256:" + _context_digest(identity)}


def source_selector(document: dict, raw: bytes, *, char_start: int, char_end: int) -> dict:
    """Create an exact physical occurrence selector, preserving repeated text."""
    view = normalized_document_view(document, raw)
    return _selector(document, view, char_start, char_end)


def _validate_selector(selector: dict, document: dict, view: dict) -> None:
    _require(type(selector) is dict and set(selector) == _SELECTOR_KEYS,
             "closed source occurrence selector required")
    expected = _selector(document, view, selector["char_start"], selector["char_end"])
    _require(_context_wire(selector) == _context_wire(expected),
             "selector identity, character or UTF8 byte coordinates differ")


def validate_source_selector(selector: dict, document: dict, raw: bytes) -> None:
    _validate_selector(selector, document, normalized_document_view(document, raw))


def exact_view_occurrences(document: dict, raw: bytes, *, text: str,
                           max_occurrences: int = MAX_OCCURRENCES) -> list[dict]:
    """Enumerate every exact match, including overlap, or refuse the bound.

    This function performs no text normalization and chooses no occurrence.
    Absence and multiple occurrences remain explicit to the caller.
    """
    view = normalized_document_view(document, raw)
    _require(type(text) is str and text and len(text.encode("utf-8")) <= MAX_SELECTOR_BYTES,
             "bounded nonempty exact source text required")
    _require(type(max_occurrences) is int and 0 < max_occurrences <= MAX_OCCURRENCES,
             "bounded exact occurrence limit required")
    matches, position = [], 0
    while (start := document["document_text"].find(text, position)) >= 0:
        _require(len(matches) < max_occurrences, "exact occurrence bound exceeded; inventory incomplete")
        matches.append(_selector(document, view, start, start + len(text)))
        position = start + 1
    return matches


def _dependency_slots(document: dict, view: dict, origin: dict, requests: list | None) -> list[dict]:
    if requests is None:
        requests = [{"kind": kind, "availability": "missing", "locator": None,
                     "expected_view_id": None, "candidate_selector": None} for kind in DEPENDENCY_KINDS]
    _require(type(requests) is list and len(requests) == len(DEPENDENCY_KINDS),
             "one explicit open obligation for each context dependency kind required")
    by_kind = {}
    for request in requests:
        _require(type(request) is dict and set(request) == _REQUEST_KEYS, "closed context dependency request required")
        kind = request["kind"]
        _require(type(kind) is str and kind in DEPENDENCY_KINDS and kind not in by_kind,
                 "unknown or duplicate context dependency kind")
        _require(request["availability"] in ("missing", "unavailable", "available"),
                 "explicit context content availability required")
        locator, expected_id, candidate = request["locator"], request["expected_view_id"], request["candidate_selector"]
        _require(locator is None or type(locator) is str and 0 < len(locator.encode("utf-8")) <= 4096,
                 "bounded context locator or null required")
        _require(expected_id is None or type(expected_id) is str and _VIEW_ID.fullmatch(expected_id),
                 "exact expected normalized view identity or null required")
        stale = expected_id is not None and expected_id != view["view_id"]
        if candidate is not None:
            _require(request["availability"] == "available" and not stale,
                     "candidate content cannot be missing, unavailable or stale")
            _validate_selector(candidate, document, view)
        if stale:
            status = "open_stale"
        elif request["availability"] == "unavailable":
            status = "open_unavailable"
        elif candidate is not None:
            status = "open_content_available"
        elif locator is not None:
            status = "open_locator_only"
        else:
            status = "open_missing"
        slot = {**request, "status": status, "open": True, "attachments": [],
                "semantic_attachment_verified": False}
        slot["slot_id"] = "legal-context-slot:sha256:" + _context_digest(
            {"origin_occurrence_id": origin["occurrence_id"], "request": request})
        by_kind[kind] = slot
    return [by_kind[kind] for kind in DEPENDENCY_KINDS]


def build_context_packet(document: dict, raw: bytes, *, char_start: int, char_end: int,
                         dependency_requests: list | None = None) -> dict:
    """Prepare source geometry and open context obligations without admission.

    Candidate selectors in this bounded profile address the same authenticated
    document view. External locators remain open; a cross-document content
    binding needs a separately versioned profile. ``expected_view_id`` names
    that same local view; another identity flags stale local custody, not an
    independently established fact about an external source. Slot categories
    are a review checklist, not an exhaustive inferred dependency inventory.
    """
    view = normalized_document_view(document, raw)
    selection = _selector(document, view, char_start, char_end)
    slots = _dependency_slots(document, view, selection, dependency_requests)
    body = {"schema": CONTEXT_PACKET_SCHEMA, "source_document": document,
            "normalized_view": view, "selection": selection, "dependency_slots": slots,
            "dependency_inventory_exhaustive": False, "context_closure_verified": False,
            "source_semantics_verified": False, "independently_reviewed": False,
            "training_qualified": False, "proof_authority": False,
            "semantic_attachments_inferred": False, "raw_html_coordinate_mapping_verified": False}
    # Detach caller-owned dictionaries so later edits cannot mutate a packet.
    body = json.loads(_context_wire(body))
    return {**body, "packet_id": "legal-context-packet:sha256:" + _context_digest(body)}


def validate_context_packet(packet: dict, document: dict, raw: bytes, *, expected_selector: dict,
                            dependency_requests: list | None = None) -> dict:
    """Replay trusted source occurrence and explicit dependency request set.

    A separately supplied selector prevents a self-consistent rewritten packet
    from choosing a different identical-text occurrence on the caller's behalf.
    """
    _require(type(packet) is dict and type(packet.get("selection")) is dict, "versioned context packet required")
    validate_source_selector(expected_selector, document, raw)
    expected = build_context_packet(document, raw, char_start=expected_selector["char_start"],
                                    char_end=expected_selector["char_end"], dependency_requests=dependency_requests)
    _require(_context_wire(packet) == _context_wire(expected),
             "context packet differs from source geometry or open dependency obligations")
    return {"schema": "legal-statutory-context-obligations-validation/v2",
            "packet_id": packet["packet_id"], "view_id": packet["normalized_view"]["view_id"],
            "source_geometry_verified": True, "open_dependency_slots": len(DEPENDENCY_KINDS),
            "context_closure_verified": False, "semantic_attachments_verified": False,
            "source_semantics_verified": False, "training_qualified": False, "proof_authority": False}
