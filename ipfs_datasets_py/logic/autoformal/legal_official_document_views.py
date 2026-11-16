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


# Optional supplied-snapshot lineage. Existing V2 extraction and authority stay unchanged.
ORIGIN_MAP_SCHEMA = "legal-official-markup-origin-map/v1"
ORIGIN_MAP_PROFILE = "strict-decoder-emissions-HTMLParser-updatepos-v2-normalization/v1"



def _origin_producer_code_pins():
    import html
    import html.parser
    import sys
    from pathlib import Path
    _need(HTMLParser is html.parser.HTMLParser, "original stdlib HTMLParser identity required")
    roles = {"mapping_owner": Path(__file__), "shared_decoder_owner": Path(contexts.__file__),
        "stdlib_html": Path(html.__file__), "stdlib_html_parser": Path(html.parser.__file__)}
    return {"source_sha256": {role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in roles.items()},
        "python_implementation": sys.implementation.name, "python_version": list(sys.version_info[:3]),
        "python_cache_tag": sys.implementation.cache_tag}


class _OriginBudget:
    """Charge complete observations before retention, under existing ceilings."""
    def __init__(self, bounds, header):
        self.maximum = bounds["max_report_bytes"]; self.nodes = bounds["max_nodes"]
        self.used = self.sources = 0
        self.charge(header, reserve=128)  # final seal plus root/list delimiters

    def charge(self, record, reserve=0):
        size = len(_wire(record)) + reserve + 1
        _need(self.used + size <= self.maximum, "complete origin observation byte budget exceeded before retention")
        self.used += size

    def source(self, source):
        _need(self.sources < self.nodes, "complete origin source-record bound exceeded before retention")
        self.charge(source); self.sources += 1

    def record(self, record):
        # Source members have already been charged individually before append.
        self.charge({k: v for k, v in record.items() if k != "source_origins"}, reserve=32)

def _origin_decode(raw, decoded, encoding, bounds, budget):
    import codecs
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    except (LookupError, TypeError) as error:
        raise OfficialDocumentViewError("origin profile requires a strict incremental text decoder") from error
    runs, controls = [], []
    position = pending = 0

    def retain(output, consumed):
        nonlocal position, pending
        _need(type(output) is str and pending <= consumed <= len(raw), "faithful incremental text emission required")
        _need(decoded.startswith(output, position), "incremental decoder differs from shared strict source decode")
        if output:
            _need(consumed > pending, "zero-input decoded emission is outside origin profile")
            mode = "affine" if len(output) == 1 else "emission_envelope"
            width = consumed - pending if mode == "affine" else None
            if (mode == "affine" and runs and runs[-1]["relation"] == mode
                    and runs[-1]["unit_raw_bytes"] == width
                    and runs[-1]["decoded_char_end"] == position and runs[-1]["raw_byte_end"] == pending):
                runs[-1]["decoded_char_end"] += 1; runs[-1]["raw_byte_end"] = consumed
            else:
                _need(len(runs) < bounds["max_nodes"], "complete decoder emission-run bound exceeded")
                run = {"relation": mode, "decoded_char_start": position,
                    "decoded_char_end": position + len(output), "raw_byte_start": pending,
                    "raw_byte_end": consumed, "unit_raw_bytes": width}
                budget.charge(run, reserve=160)  # later digest and bounded integer growth
                runs.append(run)
            position += len(output); pending = consumed
        elif consumed > pending:
            if controls and controls[-1]["raw_byte_end"] == pending and controls[-1]["decoded_char_anchor"] == position:
                controls[-1]["raw_byte_end"] = consumed
            else:
                _need(len(controls) < bounds["max_nodes"], "complete decoder control-run bound exceeded")
                control = {"raw_byte_start": pending, "raw_byte_end": consumed,
                    "decoded_char_anchor": position, "kind": "decoder_no_output_control"}
                budget.charge(control, reserve=64)
                controls.append(control)
            pending = consumed

    for end in range(1, len(raw) + 1):
        output = decoder.decode(raw[end - 1:end], final=False)
        state = decoder.getstate()
        _need(type(state) is tuple and len(state) == 2 and type(state[0]) is bytes,
              "incremental decoder must expose exact buffered source bytes")
        buffered = state[0]
        _need(len(buffered) <= min(4096, bounds["max_block_bytes"]),
              "incremental decoder emission buffer exceeds explicit origin-profile bound")
        _need(len(buffered) <= end and raw[end - len(buffered):end] == buffered,
              "incremental decoder buffer is not an exact source suffix")
        retain(output, end - len(buffered))
    output = decoder.decode(b"", final=True)
    state = decoder.getstate()
    _need(type(state) is tuple and type(state[0]) is bytes and not state[0], "complete strict decoder flush required")
    retain(output, len(raw))
    _need(position == len(decoded) and pending == len(raw), "complete raw/decoded emission accounting differs")
    for run in runs:
        run["decoded_text_sha256"] = hashlib.sha256(decoded[run["decoded_char_start"]:run["decoded_char_end"]].encode()).hexdigest()
    return runs, controls


def _origin_sources(runs, lo, hi, budget):
    from bisect import bisect_right
    result, covered = [], lo
    first = max(0, bisect_right(runs, lo, key=lambda run: run["decoded_char_start"]) - 1)
    for index in range(first, len(runs)):
        run = runs[index]
        if run["decoded_char_start"] >= hi:
            break
        start, end = max(lo, run["decoded_char_start"]), min(hi, run["decoded_char_end"])
        if start >= end:
            continue
        _need(start == covered, "complete decoded origin range required")
        if run["relation"] == "affine":
            raw_start = run["raw_byte_start"] + (start - run["decoded_char_start"]) * run["unit_raw_bytes"]
            raw_end = run["raw_byte_start"] + (end - run["decoded_char_start"]) * run["unit_raw_bytes"]
        else:
            raw_start, raw_end = run["raw_byte_start"], run["raw_byte_end"]
        source = {"decoder_run_index": index, "relation": run["relation"],
            "decoded_html_char_start": start, "decoded_html_char_end": end,
            "raw_byte_start": raw_start, "raw_byte_end": raw_end,
            "minimal_per_character_raw_slice_claimed": run["relation"] == "affine"}
        budget.source(source)
        result.append(source)
        covered = end
    _need(covered == hi and lo < hi, "complete nonempty decoded origin range required")
    return result


class _OriginMarkup(_Markup):
    """Use the existing parser callbacks; never replace its HTML lexer."""
    def __init__(self, bounds, decoded, runs, budget):
        super().__init__(bounds)
        self.decoded = decoded; self.decoder_runs = runs; self.origin_budget = budget
        self.absolute = 0; self.pending_origin_event = None
        self.origin_tokens = []; self.origin_fragments = []; self.zero_output_references = []
        self.origin_token_count = 0

    def _retain_token(self, tokens, token):
        _need(self.origin_token_count < self.limits["max_nodes"], "complete HTML origin-token bound exceeded before retention")
        self.origin_budget.charge(token)
        tokens.append(token); self.origin_token_count += 1

    def handle_data(self, data):
        _need(self.pending_origin_event is None, "one original parser data callback at a time required")
        before = len(self.parts)
        super().handle_data(data)
        self.pending_origin_event = (data, len(self.parts) > before)

    def updatepos(self, i, j):
        import html
        if self.pending_origin_event is not None:
            data, retained = self.pending_origin_event
            self.pending_origin_event = None
            source = self.rawdata[i:j]
            _need(j > i and source == self.decoded[self.absolute:self.absolute + j - i]
                  and html.unescape(source) == data, "original HTMLParser callback/source boundary differs")
            tokens, cursor = [], 0
            for match in html._charref.finditer(source):
                if cursor < match.start():
                    self._retain_token(tokens, {"text": source[cursor:match.start()], "decoded_start": self.absolute + cursor,
                        "decoded_end": self.absolute + match.start(), "entity": False})
                text = html.unescape(match.group())
                token = {"text": text, "decoded_start": self.absolute + match.start(),
                    "decoded_end": self.absolute + match.end(), "entity": True}
                self._retain_token(tokens, token)
                if not text:
                    _need(len(self.zero_output_references) < self.limits["max_nodes"], "complete removed-reference bound exceeded")
                    removed = {"decoded_html_char_start": token["decoded_start"],
                        "decoded_html_char_end": token["decoded_end"],
                        "source_origins": _origin_sources(self.decoder_runs, token["decoded_start"], token["decoded_end"], self.origin_budget),
                        "kind": "zero_output_HTML_reference"}
                    self.origin_budget.record(removed)
                    self.zero_output_references.append(removed)
                cursor = match.end()
            if cursor < len(source):
                self._retain_token(tokens, {"text": source[cursor:], "decoded_start": self.absolute + cursor,
                    "decoded_end": self.absolute + len(source), "entity": False})
            _need("".join(token["text"] for token in tokens) == data, "stdlib character-reference trace differs")
            if retained:
                self.origin_tokens.extend(tokens)
        self.absolute += j - i
        return super().updatepos(i, j)

    def _retain_fragment(self, fragment):
        _need(len(self.origin_fragments) < self.limits["max_nodes"], "complete output origin-fragment bound exceeded")
        self.origin_budget.record(fragment)
        self.origin_fragments.append(fragment)

    def _flush(self):
        tokens = self.origin_tokens
        verbatim = "".join(self.parts)
        before = len(self.blocks)
        super()._flush()
        self.origin_tokens = []
        if len(self.blocks) == before:
            _need(not _normal(verbatim), "original visible block unexpectedly disappeared")
            return
        block = self.blocks[-1]
        _need("".join(token["text"] for token in tokens) == verbatim, "complete original verbatim-event trace differs")
        if block["block_index"]:
            self._retain_fragment({"kind": "synthetic_interblock_LF", "block_index": block["block_index"],
                "output_char_start": block["char_start"] - 1, "output_char_end": block["char_start"],
                "output_utf8_byte_start": block["utf8_byte_start"] - 1, "output_utf8_byte_end": block["utf8_byte_start"],
                "output_text_sha256": hashlib.sha256(b"\n").hexdigest(), "source_origins": []})
        char_at, byte_at, emitted, spaces = block["char_start"], block["utf8_byte_start"], [], []

        def origin(token, start, end):
            lo, hi = ((token["decoded_start"], token["decoded_end"]) if token["entity"]
                      else (token["decoded_start"] + start, token["decoded_start"] + end))
            return _origin_sources(self.decoder_runs, lo, hi, self.origin_budget)

        def emit(text, kind, sources, extra=None):
            nonlocal char_at, byte_at
            width = len(text.encode())
            self._retain_fragment({"kind": kind, "block_index": block["block_index"],
                "output_char_start": char_at, "output_char_end": char_at + len(text),
                "output_utf8_byte_start": byte_at, "output_utf8_byte_end": byte_at + width,
                "output_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_origins": sources,
                **(extra or {})})
            char_at += len(text); byte_at += width; emitted.append(text)

        for token in tokens:
            for match in re.finditer(r"\s+|\S+", token["text"]):
                text = match.group()
                if text.isspace():
                    if emitted:
                        spaces.extend(origin(token, match.start(), match.end()))
                        _need(len(spaces) <= self.limits["max_nodes"], "complete whitespace-origin bound exceeded")
                    continue
                if spaces:
                    emit(" ", "collapsed_whitespace", spaces)
                    spaces = []
                lo, hi = ((token["decoded_start"], token["decoded_end"]) if token["entity"]
                          else (token["decoded_start"] + match.start(), token["decoded_start"] + match.end()))
                extra = {"decoded_html_char_start": lo, "decoded_html_char_end": hi}
                if token["entity"]:
                    extra.update(entity_output_char_start=match.start(), entity_output_char_end=match.end(),
                        partial_entity_uses_whole_transform_envelope=True)
                emit(text, "HTML_reference_decoded" if token["entity"] else "decoded_literal", origin(token, match.start(), match.end()), extra)
        _need("".join(emitted) == block["text"] and char_at == block["char_end"]
              and byte_at == block["utf8_byte_end"], "complete original normalized-block origin accounting differs")


def _origin_raw_partition(raw, fragments, controls, bounds, budget):
    events = {}
    for fragment in fragments:
        for source in fragment["source_origins"]:
            lo, hi = source["raw_byte_start"], source["raw_byte_end"]
            for position, change in ((lo, 1), (hi, -1)):
                _need(position in events or len(events) < bounds["max_nodes"], "complete raw origin endpoint bound exceeded before retention")
                events[position] = events.get(position, 0) + change
    positions = set()
    for position in (0, len(raw), *events):
        _need(position in positions or len(positions) < bounds["max_nodes"], "complete raw partition endpoint bound exceeded before retention")
        positions.add(position)
    for control in controls:
        for position in (control["raw_byte_start"], control["raw_byte_end"]):
            _need(position in positions or len(positions) < bounds["max_nodes"], "complete raw partition endpoint bound exceeded before retention")
            positions.add(position)
    positions = sorted(positions)
    result, count, control_index = [], 0, 0
    for lo, hi in zip(positions, positions[1:]):
        count += events.get(lo, 0)
        _need(0 <= lo < hi <= len(raw) and len(result) < bounds["max_nodes"], "complete raw partition bound exceeded")
        while control_index < len(controls) and controls[control_index]["raw_byte_end"] <= lo:
            control_index += 1
        control = (control_index < len(controls) and controls[control_index]["raw_byte_start"] <= lo
                   and hi <= controls[control_index]["raw_byte_end"])
        piece = {"raw_byte_start": lo, "raw_byte_end": hi,
            "raw_sha256": hashlib.sha256(raw[lo:hi]).hexdigest(),
            "kind": "output_origin_envelope" if count else "decoder_control_removed" if control else "not_in_normalized_output"}
        budget.charge(piece)
        result.append(piece)
    return result



def _origin_payload_preflight(value):
    """Bound only the new map's caller JSON before canonical-buffer allocation."""
    maximum = DEFAULT_LIMITS["max_report_bytes"]
    remaining = maximum
    stack = [(iter((value,)), 0, False)]

    def charge(size):
        nonlocal remaining
        _need(type(size) is int and 0 <= size <= remaining,
              "origin caller JSON byte bound exceeded before serialization")
        remaining -= size

    def string_size(text):
        _need(type(text) is str, "plain JSON string keys and values required")
        # Even ASCII JSON needs one output byte per source code point.
        _need(len(text) <= remaining, "origin caller string bound exceeded before serialization")
        charge(2)
        for start in range(0, len(text), 1024):
            try:
                chunk = json.dumps(text[start:start + 1024], ensure_ascii=False).encode("utf-8")
            except (ValueError, TypeError, UnicodeError) as error:
                raise OfficialDocumentViewError("finite UTF8 origin caller JSON required") from error
            charge(len(chunk) - 2)

    while stack:
        iterator, depth, dictionary = stack[-1]
        try:
            entry = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        if dictionary:
            key, item = entry
            string_size(key); charge(1)
        else:
            item = entry
        _need(depth <= DEFAULT_LIMITS["max_depth"], "origin caller JSON depth bound exceeded")
        if type(item) is dict:
            _need(len(item) <= DEFAULT_LIMITS["max_nodes"], "origin caller JSON container bound exceeded before serialization")
            charge(2 + max(0, len(item) - 1))
            stack.append((iter(item.items()), depth + 1, True))
        elif type(item) is list:
            _need(len(item) <= DEFAULT_LIMITS["max_nodes"], "origin caller JSON container bound exceeded before serialization")
            charge(2 + max(0, len(item) - 1))
            stack.append((iter(item), depth + 1, False))
        elif type(item) is str:
            string_size(item)
        elif item is None:
            charge(4)
        elif type(item) is bool:
            charge(4 if item else 5)
        elif type(item) in (int, float):
            try:
                encoded = json.dumps(item, allow_nan=False)
            except (ValueError, TypeError) as error:
                raise OfficialDocumentViewError("finite origin caller JSON numbers required") from error
            charge(len(encoded))
        else:
            raise OfficialDocumentViewError("plain built-in origin caller JSON required")
    return maximum - remaining

def official_document_origin_map_sha256(origin_map):
    """Full canonical map digest, including origin_map_sha256."""
    _origin_payload_preflight(origin_map)
    return _digest(origin_map)


def prepare_official_document_origin_map(view_report, raw, *, expected_view_report_sha256, **trusted_inputs):
    """Trace only the supplied snapshot; do not authenticate producer or law."""
    import html
    producer_pins = _origin_producer_code_pins()
    checked = validate_official_document_view(view_report, raw,
        expected_report_sha256=expected_view_report_sha256, **trusted_inputs)
    _need(checked["status"] == "comparison_view_extracted" and type(raw) is bytes,
          "complete independently replayed V2 view and original HTML required")
    bounds = checked["limits"]
    decoded, encoding = contexts._decode_source_html_with_encoding(raw)
    result = {"schema": ORIGIN_MAP_SCHEMA, "profile": ORIGIN_MAP_PROFILE,
        "full_official_view_report_sha256": expected_view_report_sha256,
        "view_id": checked["normalized_view"]["view_id"], "document_id": checked["document"]["document_id"],
        "raw_sha256": checked["raw_sha256"], "raw_bytes": len(raw),
        "decoded_HTML_sha256": hashlib.sha256(decoded.encode()).hexdigest(), "decoded_HTML_characters": len(decoded),
        "chosen_codec": encoding, "incremental_decoder_buffer_limit": min(4096, bounds["max_block_bytes"]),
        "decoder_profile": DECODER_PROFILE, "parser_profile": PARSER_PROFILE,
        "stdlib_entity_pattern_sha256": hashlib.sha256(html._charref.pattern.encode()).hexdigest(),
        "normalization_profile": NORMALIZATION_PROFILE, "limits": deepcopy(bounds),
        "producer_code_pins": producer_pins, "decoder_runs": [], "decoder_controls": [],
        "zero_output_references": [], "output_fragments": [],
        "raw_partition": [],
        "scope": "supplied_snapshot_decoder_and_markup_transformation_only_not_historical_producer_or_legal_correspondence",
        "whole_raw_emission_envelopes_may_include_other_decoded_characters": True,
        "old_V2_reports_or_raw_mapping_authority_promoted": False, "authority": dict(AUTHORITY)}
    budget = _OriginBudget(bounds, result)
    runs, controls = _origin_decode(raw, decoded, encoding, bounds, budget)
    parser = _OriginMarkup(bounds, decoded, runs, budget); parser.feed(decoded); parser.finish()
    _need(parser.pending_origin_event is None and parser.absolute == len(decoded), "complete original parser input accounting required")
    _need(parser.blocks == checked["document"]["blocks"] and parser.comments == checked["document"]["comments"]
          and _normal("".join(parser.title_parts)) == checked["document"]["title_observation"],
          "origin trace changed original V2 verbatim/blocks/comments/title")
    text = checked["document"]["document_text"]
    cursor = byte_cursor = 0
    for fragment in parser.origin_fragments:
        lo, hi = fragment["output_char_start"], fragment["output_char_end"]
        _need(lo == cursor and fragment["output_utf8_byte_start"] == byte_cursor
              and hashlib.sha256(text[lo:hi].encode()).hexdigest() == fragment["output_text_sha256"],
              "complete ordered output origin partition differs")
        cursor = hi; byte_cursor = fragment["output_utf8_byte_end"]
    _need(cursor == len(text) and byte_cursor == len(text.encode()), "complete extracted UTF8 origin population required")
    result.update(decoder_runs=runs, decoder_controls=controls,
        zero_output_references=parser.zero_output_references, output_fragments=parser.origin_fragments,
        raw_partition=_origin_raw_partition(raw, parser.origin_fragments, controls, bounds, budget))
    _need(_origin_producer_code_pins() == producer_pins, "origin producer code changed during complete replay")
    result["origin_map_sha256"] = _digest(result)
    _need(len(_wire(result)) <= bounds["max_report_bytes"], "complete origin-map report byte bound exceeded")
    return result


def validate_official_document_origin_map(origin_map, view_report, raw, *, expected_origin_map_sha256,
        expected_view_report_sha256, **trusted_inputs):
    _sha(expected_origin_map_sha256)
    _need(official_document_origin_map_sha256(origin_map) == expected_origin_map_sha256,
          "independent FULL origin-map pin differs")
    expected = prepare_official_document_origin_map(view_report, raw,
        expected_view_report_sha256=expected_view_report_sha256, **trusted_inputs)
    _need(_wire(origin_map) == _wire(expected), "origin map differs from complete independent original regeneration")
    return expected


def official_origin_span_fragments(origin_map, view_report, raw, *, selector, expected_origin_map_sha256,
        expected_view_report_sha256, **trusted_inputs):
    checked = validate_official_document_origin_map(origin_map, view_report, raw,
        expected_origin_map_sha256=expected_origin_map_sha256,
        expected_view_report_sha256=expected_view_report_sha256, **trusted_inputs)
    projection_view = validate_official_document_view(view_report, raw,
        expected_report_sha256=expected_view_report_sha256, **trusted_inputs)
    _need(type(selector) is dict, "closed exact V2 selector required")
    expected = _selector(projection_view, selector.get("char_start"), selector.get("char_end"))
    _need(type(selector) is dict and _wire(selector) == _wire(expected), "exact existing V2 occurrence identity required")
    text = projection_view["document"]["document_text"]
    result = {"schema": "legal-official-markup-origin-span/v1", "profile": ORIGIN_MAP_PROFILE,
        "origin_map_sha256": expected_origin_map_sha256, "selector": deepcopy(selector), "fragments": [],
        "whole_transform_envelopes_are_not_minimal_raw_substrings": True, "authority": dict(AUTHORITY)}
    budget = _OriginBudget(checked["limits"], result)
    fragments = []
    byte_cursor = selector["utf8_byte_start"]
    for original in checked["output_fragments"]:
        lo, hi = max(selector["char_start"], original["output_char_start"]), min(selector["char_end"], original["output_char_end"])
        if lo >= hi:
            continue
        fragment = {key: deepcopy(value) for key, value in original.items() if key != "source_origins"}
        fragment["source_origins"] = []
        clipped = text[lo:hi].encode()
        fragment.update(output_char_start=lo, output_char_end=hi,
            output_utf8_byte_start=byte_cursor, output_utf8_byte_end=byte_cursor + len(clipped),
            output_text_sha256=hashlib.sha256(clipped).hexdigest())
        byte_cursor += len(clipped)
        offset = lo - original["output_char_start"]
        if fragment["kind"] == "decoded_literal":
            start = original["decoded_html_char_start"] + offset
            fragment.update(decoded_html_char_start=start, decoded_html_char_end=start + hi - lo,
                source_origins=_origin_sources(checked["decoder_runs"], start, start + hi - lo, budget))
        elif fragment["kind"] == "HTML_reference_decoded":
            fragment.update(entity_output_char_start=original["entity_output_char_start"] + offset,
                entity_output_char_end=original["entity_output_char_start"] + offset + hi - lo)
        if fragment["kind"] != "decoded_literal":
            for source in original["source_origins"]:
                budget.source(source)
                fragment["source_origins"].append(deepcopy(source))
        budget.record(fragment)
        fragments.append(fragment)
    _need(sum(f["output_char_end"] - f["output_char_start"] for f in fragments)
          == selector["char_end"] - selector["char_start"] and byte_cursor == selector["utf8_byte_end"],
          "complete selected origin population required")
    result["fragments"] = fragments
    _need(len(_wire(result)) <= checked["limits"]["max_report_bytes"], "complete origin-span byte bound exceeded")
    return result


__all__ += ["ORIGIN_MAP_SCHEMA", "ORIGIN_MAP_PROFILE", "prepare_official_document_origin_map",
    "official_document_origin_map_sha256", "validate_official_document_origin_map", "official_origin_span_fragments"]
