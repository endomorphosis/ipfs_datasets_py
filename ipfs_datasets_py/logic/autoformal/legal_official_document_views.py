"""Additive, bounded GovInfo markup views; no v1 coordinates are reinterpreted.

Every admitted body text event belongs to exactly one ordered block. Balanced
markup/comment fields, tables and headings are observations, not legal roles.
HTML/CSS rendering, original cache correspondence and governing meaning remain
unverified. Raw HTML stays in independently pinned caller storage.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
import re

from . import legal_official_source_custody as custody
from . import legal_statutory_context as contexts

DOCUMENT_SCHEMA = "legal-official-markup-document/v2"
REPORT_SCHEMA = "legal-official-document-view-custody/v2"
VIEW_SCHEMA = "legal-official-markup-normalized-view/v2"
SELECTOR_SCHEMA = "legal-official-markup-occurrence-selector/v2"
NORMALIZATION_PROFILE = "HTML-entities-body-text-block-whitespace-collapse-UTF8-LF/v2"
DECODER_PROFILE = "legal_statutory_context-declared-encoding-BOM-strict-default-UTF8/v1"
HEADING_PROFILE = "literal-section-token-with-ASCII-hyphen-or-en-dash-render/v1"
PARSER_PROFILE = "stdlib-html-parser-balanced-GovInfo-markup-events/v1"
MAX_OCCURRENCES = 4096
MAX_SELECTOR_BYTES = 1024 * 1024
DEFAULT_LIMITS = {"max_nodes": 100000, "max_depth": 128, "max_blocks": 20000,
    "max_comments": 10000, "max_block_bytes": 1024 * 1024, "max_decoded_text_bytes": 8_000_000,
    "max_report_bytes": 32 * 1024 * 1024}
AUTHORITY = dict.fromkeys((*custody.AUTHORITY, "css_rendering_verified", "legal_roles_verified",
    "original_source_body_mapping_verified", "source_semantics_verified", "proof_authority"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_VOID = {"br", "hr", "link", "meta"}
_BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "article", "blockquote",
          "pre", "li", "ul", "ol", "table", "caption", "thead", "tbody", "tfoot", "tr", "td", "th"}
_ALLOWED = _BLOCK | _VOID | {"html", "head", "body", "title", "span", "a", "i", "b", "strong", "em",
    "u", "sup", "sub", "small", "cap-smallcap", "s", "strike"}


class OfficialDocumentViewError(ValueError):
    """An independent pin, exact coordinate or finite contract bound differs."""


class UnsupportedDocumentMarkup(OfficialDocumentViewError):
    """No complete admitted markup view can be claimed for these bytes."""


def _need(ok, message):
    if not ok:
        raise OfficialDocumentViewError(message)


def _profile(ok, message):
    if not ok:
        raise UnsupportedDocumentMarkup(message)


def _wire(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise OfficialDocumentViewError("finite canonical UTF8 view JSON required") from error
    _need(len(raw) <= DEFAULT_LIMITS["max_report_bytes"], "complete view JSON byte bound exceeded")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value), "independent lowercase SHA256 required")


def _limits(value):
    _need(value is None or type(value) is dict and not (set(value) - set(DEFAULT_LIMITS)), "closed optional view limits required")
    result = dict(DEFAULT_LIMITS, **(value or {}))
    for key, bound in result.items():
        _need(type(bound) is int and 0 < bound <= DEFAULT_LIMITS[key], "positive lowered finite view limit required: " + key)
    return result


def _normal(text):
    return " ".join(text.split())


class _Markup(HTMLParser):
    def __init__(self, limits):
        super().__init__(convert_charrefs=True)
        self.limits = limits
        self.stack = []
        self.fields = []
        self.comments = []
        self.blocks = []
        self.parts = []
        self.current = None
        self.nodes = self.text_bytes = self.part_bytes = self.report_bytes = 0
        self.heads = self.bodies = self.char_position = self.byte_position = 0
        self.seen_section = False
        self.note_group = None
        self.title_parts = []
        self.root_children = 0

    def _body(self):
        return any(node["tag"] == "body" for node in self.stack)

    def _owner(self):
        body = next(i for i, node in enumerate(self.stack) if node["tag"] == "body")
        return next((node for node in reversed(self.stack[body + 1:]) if node["tag"] in _BLOCK),
                    self.stack[body + 1] if len(self.stack) > body + 1 else self.stack[body])

    def _table(self):
        table_index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]["tag"] == "table"), None)
        if table_index is None:
            return None
        table = self.stack[table_index]
        row = next((node for node in reversed(self.stack[table_index + 1:]) if node["tag"] == "tr"), None)
        cell = next((node for node in reversed(self.stack[table_index + 1:]) if node["tag"] in ("td", "th")), None)
        return {"table_dom_path": table["path"], "table_attributes": table["attributes"],
            "row_ordinal": row["row_ordinal"] if row else None, "column_ordinal": cell["column_ordinal"] if cell else None,
            "cell_tag": cell["tag"] if cell else None, "cell_attributes": cell["attributes"] if cell else None}

    def _region(self, owner):
        classes = owner["classes"]
        if "footnote" in self.fields or "footnote" in classes:
            return "footnote"
        if "notes" in self.fields or any(field.endswith("-note") for field in self.fields):
            if self.note_group == "Statutory Notes and Related Subsidiaries": return "statutory_notes"
            if self.note_group == "Editorial Notes": return "editorial_notes"
            if "historicalandrevision-note" in self.fields: return "historical_revision_notes"
            return "notes"
        if "sourcecredit" in self.fields or "source-credit" in classes: return "source_credit"
        if "head" in self.fields or "section-head" in classes: return "section_heading"
        if "statute" in self.fields: return "statute"
        if self.fields: return "other_declared_field"
        return "metadata_header" if not self.seen_section else "unclassified_body_text"

    def _flush(self):
        if self.current is not None:
            verbatim = "".join(self.parts)
            text = _normal(verbatim)
            if text:
                _need(len(self.blocks) < self.limits["max_blocks"], "complete visible block population bound exceeded")
                current = self.current
                if "note-head" in current["classes"] and text in ("Editorial Notes", "Statutory Notes and Related Subsidiaries"):
                    self.note_group = text
                    current["note_group_observation"] = text
                    current["region_kind"] = "editorial_notes" if text == "Editorial Notes" else "statutory_notes"
                width = len(text.encode("utf-8"))
                if self.blocks:
                    self.char_position += 1; self.byte_position += 1
                block = {**current, "block_index": len(self.blocks), "verbatim_text": verbatim,
                    "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "char_start": self.char_position, "char_end": self.char_position + len(text),
                    "utf8_byte_start": self.byte_position, "utf8_byte_end": self.byte_position + width}
                block["block_id"] = "legal-markup-block:sha256:" + _digest(block)
                self.report_bytes += len(_wire(block))
                _need(self.report_bytes <= self.limits["max_report_bytes"], "incremental complete view byte bound exceeded")
                self.blocks.append(block)
                self.char_position += len(text); self.byte_position += width
                if block["tag"] == "h3" and "section-head" in block["classes"]:
                    self.seen_section = True
        self.current = None
        self.parts = []
        self.part_bytes = 0

    def handle_starttag(self, tag, attrs):
        _profile(tag in _ALLOWED, "unsupported tag cannot be omitted: " + tag)
        _profile(len(attrs) <= 32 and len({key for key, _ in attrs}) == len(attrs), "duplicate or unbounded markup attributes")
        attributes = {key: value for key, value in attrs}
        _need(len(_wire(attributes)) <= 8192, "bounded per-element attributes required")
        _profile("hidden" not in attributes and "aria-hidden" not in attributes and not any(key.startswith("on") for key in attributes),
                 "unsupported visibility or active markup attributes")
        if "style" in attributes:
            style = attributes["style"]
            _profile(type(style) is str and all(re.fullmatch(r"\s*(?:font-size\s*:\s*[0-9.]+(?:pt|px|em)|font-weight\s*:\s*(?:bold|normal)|font-style\s*:\s*(?:italic|normal))\s*", part)
                for part in style.split(";") if part.strip()), "unsupported CSS rendering cannot be silently inferred")
        self.nodes += 1
        _need(self.nodes <= self.limits["max_nodes"] and len(self.stack) < self.limits["max_depth"], "markup node/depth bound exceeded")
        if self._body() and (tag in _BLOCK or tag == "br" or self.stack[-1]["tag"] == "body"):
            self._flush()
        if self.stack:
            parent = self.stack[-1]; number = parent["children"]; parent["children"] += 1
            path = parent["path"] + [[tag, number]]
        else:
            path = [[tag, self.root_children]]; self.root_children += 1
        node = {"tag": tag, "path": path, "attributes": attributes,
                "classes": (attributes.get("class") or "").split(), "children": 0}
        if tag == "html": _profile(not self.stack and self.root_children == 1, "html must be the unique outer element")
        if tag == "head":
            self.heads += 1; _profile(self.heads == 1 and self.stack and self.stack[-1]["tag"] == "html", "one explicit head required")
        if tag == "body":
            self.bodies += 1; _profile(self.bodies == 1 and self.heads == 1 and self.stack and self.stack[-1]["tag"] == "html", "one explicit body after head required")
        if tag in ("title", "meta", "link"):
            _profile(self.stack and self.stack[-1]["tag"] == "head", "head metadata must be inside explicit head")
        if tag == "table": node["rows"] = 0
        if tag == "tr":
            table = next((item for item in reversed(self.stack) if item["tag"] == "table"), None)
            _profile(table is not None, "table row requires explicit table")
            node["row_ordinal"] = table["rows"]; table["rows"] += 1; node["columns"] = 0
        if tag in ("td", "th"):
            _profile(self.stack and self.stack[-1]["tag"] == "tr", "table cell requires explicit row")
            node["column_ordinal"] = self.stack[-1]["columns"]; self.stack[-1]["columns"] += 1
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        _profile(tag not in _VOID and self.stack and self.stack[-1]["tag"] == tag, "unbalanced markup closing tag: " + tag)
        if self.current is not None and self.current["dom_path"] == self.stack[-1]["path"]:
            self._flush()
        elif tag in _BLOCK or tag == "body":
            self._flush()
        self.stack.pop()

    def handle_data(self, data):
        size = len(data.encode("utf-8"))
        self.text_bytes += size
        _need(self.text_bytes <= self.limits["max_decoded_text_bytes"], "decoded complete text byte bound exceeded")
        if any(node["tag"] == "title" for node in self.stack): self.title_parts.append(data)
        if not self._body():
            _profile(not data.strip() or any(node["tag"] == "title" for node in self.stack), "visible text outside admitted body/title")
            return
        owner = self._owner()
        if self.current is None:
            if not data.strip(): return
            tag = owner["tag"]
            self.current = {"tag": tag, "classes": owner["classes"], "attributes": owner["attributes"],
                "dom_path": owner["path"], "field_regions": list(self.fields), "region_kind": self._region(owner),
                "note_group_observation": self.note_group, "table_coordinates": self._table(),
                "block_kind": "table_cell" if tag in ("td", "th") else "table_caption" if tag == "caption" else
                    "heading" if re.fullmatch(r"h[1-6]", tag) else "paragraph" if tag == "p" else "text_block"}
        self.part_bytes += size
        _need(self.part_bytes <= self.limits["max_block_bytes"], "complete block text byte bound exceeded")
        self.parts.append(data)

    def handle_comment(self, data):
        _need(len(self.comments) < self.limits["max_comments"], "complete markup comment bound exceeded")
        before = list(self.fields)
        match = re.fullmatch(r"\s*field-(start|end):([A-Za-z0-9_-]+)\s*", data)
        if match:
            _profile(self._body(), "declared text fields must be inside body")
            self._flush()
            kind, field = match.groups()
            if kind == "start":
                _profile(field not in self.fields and len(self.fields) < self.limits["max_depth"], "ambiguous repeated or excessive declared field")
                self.fields.append(field)
            else:
                _profile(self.fields and self.fields[-1] == field, "unbalanced declared field regions")
                self.fields.pop()
        else:
            _profile("field-start:" not in data and "field-end:" not in data, "malformed declared field marker")
        comment = {"comment_index": len(self.comments), "text": data, "field_regions_before": before,
            "field_regions_after": list(self.fields), "parser_line": self.getpos()[0], "parser_column": self.getpos()[1]}
        self.report_bytes += len(_wire(comment))
        _need(self.report_bytes <= self.limits["max_report_bytes"], "incremental comment/report byte bound exceeded")
        self.comments.append(comment)

    def handle_decl(self, decl):
        _profile(decl.lower() == "doctype html", "unsupported declaration")

    def unknown_decl(self, data):
        raise UnsupportedDocumentMarkup("unsupported HTML declaration")

    def handle_pi(self, data):
        raise UnsupportedDocumentMarkup("processing instruction outside admitted HTML markup profile")

    def finish(self):
        self.close(); self._flush()
        _profile(not self.stack and not self.fields and self.heads == self.bodies == 1, "complete balanced HTML and field population required")


def _extract(raw, descriptor, limits):
    try:
        decoded = contexts._decode_source_html(raw)
    except ValueError as error:
        raise UnsupportedDocumentMarkup("shared strict source HTML decoding profile refused: " + str(error)) from error
    _profile("\x00" not in decoded, "NUL is outside the admitted HTML profile")
    parser = _Markup(limits); parser.feed(decoded); parser.finish()
    headings = [block for block in parser.blocks if block["tag"] == "h3" and "section-head" in block["classes"]]
    _profile(len(headings) == 1, "one complete unambiguous section heading required")
    section = descriptor["legal_id"].split(":")[-1]
    heading = headings[0]["text"]
    match = re.match(r"^§([^\s.]+)(?:\.|\s)", heading)
    allowed = (section, section.replace("-", "–"))
    _profile(match is not None and match.group(1) in allowed, "heading token differs from explicit versioned literal rendering profile")
    _profile(any(block["region_kind"] == "statute" and block["tag"] == "p" for block in parser.blocks), "explicit complete statute field/body required")
    text = "\n".join(block["text"] for block in parser.blocks)
    html_sha = hashlib.sha256(raw).hexdigest()
    document = {"schema": DOCUMENT_SCHEMA, "legal_id": descriptor["legal_id"], "edition": descriptor["edition"],
        "source_url": descriptor["url"], "document_id": "govinfo-markup-v2-html-sha256:" + html_sha,
        "html_sha256": html_sha, "title_observation": _normal("".join(parser.title_parts)),
        "heading": heading, "heading_render_observation": {"profile": HEADING_PROFILE, "canonical_section_token": section,
            "rendered_section_token": match.group(1), "cache_identity_aliases_used": False},
        "document_text": text, "document_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "blocks": parser.blocks, "comments": parser.comments, "visible_block_count": len(parser.blocks),
        "region_kind_counts": dict(Counter(block["region_kind"] for block in parser.blocks)),
        "body_text_event_coverage": "every_admitted_body_text_event_once_in_DOM_order_except_declared_whitespace_normalization",
        "parser_profile": PARSER_PROFILE, "decoder_profile": DECODER_PROFILE, "authority": dict(AUTHORITY)}
    view_identity = {"schema": VIEW_SCHEMA, "normalization_profile": NORMALIZATION_PROFILE, "heading_profile": HEADING_PROFILE,
        "parser_profile": PARSER_PROFILE, "decoder_profile": DECODER_PROFILE, "document_id": document["document_id"], "html_sha256": html_sha,
        "document_text_sha256": document["document_text_sha256"], "legal_id": descriptor["legal_id"],
        "edition": descriptor["edition"], "source_url": descriptor["url"]}
    view = {**view_identity, "view_id": "legal-official-markup-view:sha256:" + _digest(view_identity),
        "unicode_code_points": len(text), "utf8_bytes": len(text.encode()),
        "char_coordinate_system": "Unicode code points in v2 document_text; half-open",
        "byte_coordinate_system": "UTF8 bytes of v2 document_text; half-open", "raw_html_coordinate_mapping_verified": False}
    return document, view


def prepare_official_document_view(raw, *, descriptor, expected_descriptor_sha256,
        expected_raw_sha256, expected_raw_bytes, limits=None):
    """Verify external custody then create a distinct complete v2 markup view."""
    descriptor = custody._descriptor(descriptor)
    _sha(expected_descriptor_sha256); _sha(expected_raw_sha256)
    _need(custody.acquisition_descriptor_sha256(descriptor) == expected_descriptor_sha256, "independent acquisition descriptor pin differs")
    _need(type(expected_raw_bytes) is int and 0 < expected_raw_bytes <= custody.MAX_HTML_BYTES,
          "independent bounded raw byte count required")
    _need((descriptor["raw_sha256"], descriptor["raw_bytes"]) == (expected_raw_sha256, expected_raw_bytes), "independent raw content pins differ")
    _need(raw is None or type(raw) is bytes, "exact independent raw bytes or explicit missing body required")
    if raw is not None:
        _need(len(raw) == expected_raw_bytes and hashlib.sha256(raw).hexdigest() == expected_raw_sha256, "independent raw body bytes/hash differ")
    limits = _limits(limits)
    document = view = None
    issues = []
    if raw is None:
        status = "raw_comparison_document_missing"
        issues.append({"code": "independently_pinned_raw_body_not_supplied"})
    else:
        try:
            document, view = _extract(raw, descriptor, limits)
            status = "comparison_view_extracted"
        except UnsupportedDocumentMarkup as error:
            status = "comparison_view_profile_refused"
            issues.append({"code": "complete_markup_profile_refused", "message": str(error)[:512]})
    report = {"schema": REPORT_SCHEMA, "descriptor": descriptor, "descriptor_sha256": expected_descriptor_sha256,
        "raw_sha256": expected_raw_sha256, "raw_bytes": expected_raw_bytes, "raw_body_verified": raw is not None,
        "document": document, "normalized_view": view, "status": status, "issues": issues, "limits": limits,
        "raw_payload_location": "independently_pinned_caller_retained_raw_bytes",
        "edition_scope": "independently_selected_comparison_only_not_producer_edition_correspondence",
        "authority": dict(AUTHORITY)}
    report["document_report_sha256"] = _digest(report)
    _need(len(_wire(report)) <= limits["max_report_bytes"], "complete view report byte bound exceeded")
    return report


def document_view_report_sha256(report):
    """Full canonical report SHA including document_report_sha256, for retention."""
    return _digest(report)


def validate_official_document_view(report, raw, *, expected_report_sha256, **trusted_inputs):
    _sha(expected_report_sha256)
    _need(document_view_report_sha256(report) == expected_report_sha256, "independent full document-view report pin differs")
    expected = prepare_official_document_view(raw, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "view differs from complete independent raw/descriptor regeneration")
    return expected


def _selector(report, start, end):
    _need(report.get("status") == "comparison_view_extracted", "complete extracted v2 comparison view required")
    document, view = report["document"], report["normalized_view"]
    text = document["document_text"]
    _need(type(start) is int and type(end) is int and 0 <= start < end <= len(text), "exact bounded half-open v2 character range required")
    selected = text[start:end]
    _need(len(selected.encode()) <= MAX_SELECTOR_BYTES, "bounded exact selector UTF8 bytes required")
    identity = {"schema": SELECTOR_SCHEMA, "view_id": view["view_id"], "document_id": document["document_id"],
        "char_start": start, "char_end": end, "utf8_byte_start": len(text[:start].encode()),
        "utf8_byte_end": len(text[:end].encode()), "text": selected, "text_sha256": hashlib.sha256(selected.encode()).hexdigest()}
    return {**identity, "occurrence_id": "legal-official-markup-occurrence:sha256:" + _digest(identity)}


def exact_view_occurrences(report, raw, *, expected_report_sha256, text, max_occurrences=MAX_OCCURRENCES, **trusted_inputs):
    """Replay custody and enumerate every exact overlap; never select one."""
    checked = validate_official_document_view(report, raw, expected_report_sha256=expected_report_sha256, **trusted_inputs)
    _need(checked["status"] == "comparison_view_extracted", "complete extracted v2 comparison view required")
    _need(type(text) is str and text and len(text.encode()) <= MAX_SELECTOR_BYTES, "bounded nonempty exact text required")
    _need(type(max_occurrences) is int and 0 < max_occurrences <= MAX_OCCURRENCES, "bounded complete occurrence limit required")
    result, position, output_bytes = [], 0, 2
    while (start := checked["document"]["document_text"].find(text, position)) >= 0:
        _need(len(result) < max_occurrences, "complete exact occurrence bound exceeded; truncation refused")
        selector = _selector(checked, start, start + len(text))
        output_bytes += len(_wire(selector)) + bool(result)
        _need(output_bytes <= checked["limits"]["max_report_bytes"],
              "complete selector output byte bound exceeded; truncation refused")
        result.append(selector); position = start + 1
    return result


def occurrence_region_intersections(report, selector):
    """Intersect a selector with blocks of an independently validated report.

    This geometry helper does not itself authenticate the supplied report. Public
    custody callers must replay it with validate_official_document_view first.
    """
    _need(type(selector) is dict, "closed v2 occurrence selector required")
    expected = _selector(report, selector.get("char_start"), selector.get("char_end"))
    _need(_wire(selector) == _wire(expected), "selector differs from exact v2 view identity/coordinates")
    left, right = selector["char_start"], selector["char_end"]
    intersections, covered = [], 0
    for block in report["document"]["blocks"]:
        start, end = max(left, block["char_start"]), min(right, block["char_end"])
        if start < end:
            covered += end - start
            intersections.append({"block_index": block["block_index"], "block_id": block["block_id"],
                "char_start": start, "char_end": end, "utf8_byte_start": len(report["document"]["document_text"][:start].encode()),
                "utf8_byte_end": len(report["document"]["document_text"][:end].encode()),
                **{key: deepcopy(block[key]) for key in ("region_kind", "block_kind", "field_regions", "tag", "classes", "dom_path", "table_coordinates", "note_group_observation")}})
    return {"blocks": intersections, "interblock_separator_codepoints": right - left - covered,
        "coverage_scope": "v2_normalized_markup_block_intersections_only_no_governing_meaning"}


__all__ = ["OfficialDocumentViewError", "prepare_official_document_view", "validate_official_document_view",
    "document_view_report_sha256", "exact_view_occurrences", "occurrence_region_intersections"]
