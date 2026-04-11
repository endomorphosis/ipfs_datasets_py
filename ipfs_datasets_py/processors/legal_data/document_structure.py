"""
Reusable legal document structure parsing helpers.

These helpers extract pleading headers, structural sections, and a
lightweight document knowledge graph from markdown or plain-text legal
documents so downstream processors can reuse the same normalized view.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence


_ALL_CAPS_HEADING_PATTERN = re.compile(r"^[A-Z0-9 ,.'&()\[\]/:-]{8,}$")
_ROMAN_HEADING_PATTERN = re.compile(r"^[IVXLC]+\.\s+[A-Z].*$")
_LETTER_HEADING_PATTERN = re.compile(r"^[A-Z]\.\s+[A-Z].*$")
_SUBHEADING_PATTERN = re.compile(r"^\([0-9a-zA-Z]+\)\s+.*$")
_NUMBERED_PARAGRAPH_PATTERN = re.compile(r"^(\d+)\.\s+(.*)$")
_BULLET_PATTERN = re.compile(r"^[-*]\s+(.*)$")


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value).strip().lower()).strip("-")
    return text or "item"


@dataclass
class PleadingHeader:
    """Top-of-document pleading caption/header."""

    court_lines: List[str] = field(default_factory=list)
    case_number: str = ""
    party_lines: List[str] = field(default_factory=list)
    title_lines: List[str] = field(default_factory=list)
    start_line: int = 0
    body_start_line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentSection:
    """Detected section in a legal document."""

    kind: str
    heading: str
    line_number: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedLegalDocument:
    """Normalized summary for a legal-text export."""

    header: Optional[PleadingHeader]
    sections: List[DocumentSection] = field(default_factory=list)
    numbered_paragraph_count: int = 0
    bullet_count: int = 0
    code_block_count: int = 0
    all_caps_heading_count: int = 0
    title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "header": self.header.to_dict() if self.header else None,
            "sections": [section.to_dict() for section in self.sections],
            "numbered_paragraph_count": self.numbered_paragraph_count,
            "bullet_count": self.bullet_count,
            "code_block_count": self.code_block_count,
            "all_caps_heading_count": self.all_caps_heading_count,
            "title": self.title,
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "has_header": self.header is not None,
            "court_line_count": len(self.header.court_lines) if self.header else 0,
            "party_line_count": len(self.header.party_lines) if self.header else 0,
            "title_line_count": len(self.header.title_lines) if self.header else 0,
            "section_count": len(self.sections),
            "section_kinds": sorted({section.kind for section in self.sections}),
            "numbered_paragraph_count": self.numbered_paragraph_count,
            "bullet_count": self.bullet_count,
            "code_block_count": self.code_block_count,
            "all_caps_heading_count": self.all_caps_heading_count,
            "title": self.title,
        }


@dataclass
class PleadingCaption:
    """Court-ready caption metadata for document headers."""

    court_lines: List[str] = field(default_factory=list)
    left_title: str = ""
    right_title: str = ""
    case_number: str = ""
    party_lines: List[str] = field(default_factory=list)
    filing_title_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_pleading_header(text: str | Sequence[str]) -> tuple[Optional[PleadingHeader], int]:
    """Parse a common pleading caption/header from leading lines."""

    lines = list(text.splitlines() if isinstance(text, str) else text)
    idx = 0
    total = len(lines)

    while idx < total and not str(lines[idx]).strip():
        idx += 1

    start_line = idx
    if idx >= total or not str(lines[idx]).strip().startswith("IN THE "):
        return None, 0

    court_lines: List[str] = []
    while idx < total and str(lines[idx]).strip():
        court_lines.append(str(lines[idx]).strip())
        idx += 1

    while idx < total and not str(lines[idx]).strip():
        idx += 1

    case_number = ""
    if idx < total and str(lines[idx]).strip().startswith("Case No."):
        case_number = str(lines[idx]).strip()
        idx += 1
        while idx < total and not str(lines[idx]).strip():
            idx += 1

    party_lines: List[str] = []
    while idx < total and str(lines[idx]).strip():
        party_lines.append(str(lines[idx]).strip())
        idx += 1

    while idx < total and not str(lines[idx]).strip():
        idx += 1

    title_lines: List[str] = []
    while idx < total and str(lines[idx]).strip():
        title_lines.append(str(lines[idx]).strip())
        idx += 1

    while idx < total and not str(lines[idx]).strip():
        idx += 1

    return (
        PleadingHeader(
            court_lines=court_lines,
            case_number=case_number,
            party_lines=party_lines,
            title_lines=title_lines,
            start_line=start_line + 1,
            body_start_line=idx + 1,
        ),
        idx,
    )


def parse_legal_document(text: str) -> ParsedLegalDocument:
    """Extract structural signals from a markdown/plain-text legal document."""

    lines = text.splitlines()
    header, body_start = extract_pleading_header(lines)
    sections: List[DocumentSection] = []
    numbered_paragraph_count = 0
    bullet_count = 0
    code_block_count = 0
    all_caps_heading_count = 0

    if header:
        for offset, title_line in enumerate(header.title_lines):
            if _ALL_CAPS_HEADING_PATTERN.fullmatch(title_line):
                sections.append(
                    DocumentSection(
                        kind="header_title",
                        heading=title_line,
                        line_number=max(
                            1,
                            header.body_start_line - len(header.title_lines) + offset - 1,
                        ),
                    )
                )
                all_caps_heading_count += 1

    in_code = False

    for index, raw_line in enumerate(lines[body_start:], start=body_start + 1):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            if not in_code:
                code_block_count += 1
            continue
        if in_code or not stripped:
            continue

        if stripped.startswith("# "):
            sections.append(DocumentSection(kind="markdown_h1", heading=stripped[2:].strip(), line_number=index))
            continue
        if stripped.startswith("## "):
            sections.append(DocumentSection(kind="markdown_h2", heading=stripped[3:].strip(), line_number=index))
            continue
        if stripped.startswith("### "):
            sections.append(DocumentSection(kind="markdown_h3", heading=stripped[4:].strip(), line_number=index))
            continue
        if stripped.startswith("#### "):
            sections.append(DocumentSection(kind="markdown_h4", heading=stripped[5:].strip(), line_number=index))
            continue
        if _ROMAN_HEADING_PATTERN.match(stripped):
            sections.append(DocumentSection(kind="roman_heading", heading=stripped, line_number=index))
            continue
        if _LETTER_HEADING_PATTERN.match(stripped):
            sections.append(DocumentSection(kind="letter_heading", heading=stripped, line_number=index))
            continue
        if _SUBHEADING_PATTERN.match(stripped):
            sections.append(DocumentSection(kind="subheading", heading=stripped, line_number=index))
            continue
        if _ALL_CAPS_HEADING_PATTERN.fullmatch(stripped):
            sections.append(DocumentSection(kind="all_caps_heading", heading=stripped, line_number=index))
            all_caps_heading_count += 1
            continue
        if _NUMBERED_PARAGRAPH_PATTERN.match(stripped):
            numbered_paragraph_count += 1
            continue
        if _BULLET_PATTERN.match(stripped):
            bullet_count += 1

    if in_code:
        code_block_count += 1

    title = ""
    if header and header.title_lines:
        title = " ".join(header.title_lines).strip()
    elif sections:
        title = sections[0].heading

    return ParsedLegalDocument(
        header=header,
        sections=sections,
        numbered_paragraph_count=numbered_paragraph_count,
        bullet_count=bullet_count,
        code_block_count=code_block_count,
        all_caps_heading_count=all_caps_heading_count,
        title=title,
    )


def build_pleading_caption(
    *,
    court_lines: Sequence[str],
    case_number: str,
    party_lines: Sequence[str],
    filing_title_lines: Sequence[str],
    left_title: str = "",
    right_title: str = "",
) -> PleadingCaption:
    """Build a normalized pleading caption payload."""

    return PleadingCaption(
        court_lines=[str(line).strip() for line in court_lines if str(line).strip()],
        left_title=str(left_title).strip(),
        right_title=str(right_title).strip(),
        case_number=str(case_number).strip(),
        party_lines=[str(line).strip() for line in party_lines if str(line).strip()],
        filing_title_lines=[str(line).strip() for line in filing_title_lines if str(line).strip()],
    )


def render_pleading_caption_block(caption: PleadingCaption) -> str:
    """Render a plain-text court-style caption block."""

    left_width = 46
    right_width = 26
    separator = "  |  "
    lines: List[str] = []

    for line in caption.court_lines:
        lines.append(line.center(left_width + len(separator) + right_width).rstrip())
    if caption.court_lines:
        lines.append("")

    left_column = list(caption.party_lines)
    if caption.left_title:
        left_column.append(caption.left_title)

    right_column: List[str] = []
    if caption.right_title:
        right_column.append(caption.right_title)
    if caption.case_number:
        right_column.append(caption.case_number)
    right_column.extend(caption.filing_title_lines)

    row_count = max(len(left_column), len(right_column), 1)
    for index in range(row_count):
        left = left_column[index] if index < len(left_column) else ""
        right = right_column[index] if index < len(right_column) else ""
        lines.append(f"{left:<{left_width}}{separator}{right:<{right_width}}".rstrip())

    return "\n".join(lines).rstrip() + "\n"


def paginate_pleading_lines(
    lines: Sequence[str],
    *,
    page_size: int = 45,
    footer_label: str = "",
) -> List[List[str]]:
    """Paginate body lines and append court-style page labels."""

    normalized = [str(line) for line in lines]
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if not normalized:
        return [[_format_page_footer(1, 1, footer_label)]]

    pages: List[List[str]] = []
    for start in range(0, len(normalized), page_size):
        pages.append(normalized[start : start + page_size])

    total_pages = len(pages)
    for index, page in enumerate(pages, start=1):
        page.append(_format_page_footer(index, total_pages, footer_label))
    return pages


try:
    from lib.legal_document import (
        DocumentSection as _SharedDocumentSection,
        ParsedLegalDocument as _SharedParsedLegalDocument,
        PleadingCaption as _SharedPleadingCaption,
        PleadingHeader as _SharedPleadingHeader,
        build_pleading_caption as _shared_build_pleading_caption,
        extract_pleading_header as _shared_extract_pleading_header,
        paginate_pleading_lines as _shared_paginate_pleading_lines,
        parse_legal_document as _shared_parse_legal_document,
        render_pleading_caption_block as _shared_render_pleading_caption_block,
    )
except ImportError:  # pragma: no cover - standalone ipfs_datasets_py fallback
    _SHARED_LEGAL_DOCUMENT_HELPERS = False
else:
    _SHARED_LEGAL_DOCUMENT_HELPERS = True
    DocumentSection = _SharedDocumentSection
    ParsedLegalDocument = _SharedParsedLegalDocument
    PleadingCaption = _SharedPleadingCaption
    PleadingHeader = _SharedPleadingHeader
    build_pleading_caption = _shared_build_pleading_caption
    extract_pleading_header = _shared_extract_pleading_header
    paginate_pleading_lines = _shared_paginate_pleading_lines
    parse_legal_document = _shared_parse_legal_document
    render_pleading_caption_block = _shared_render_pleading_caption_block


def build_document_knowledge_graph(
    parsed: ParsedLegalDocument,
    *,
    graph_id: str = "legal_document",
) -> Dict[str, Any]:
    """Build a lightweight document-centric knowledge graph payload."""

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    document_node_id = f"{graph_id}:document"

    nodes.append(
        {
            "id": document_node_id,
            "type": "document",
            "label": parsed.title or graph_id,
            "properties": parsed.summary(),
        }
    )

    if parsed.header:
        for index, line in enumerate(parsed.header.court_lines, start=1):
            node_id = f"{graph_id}:court:{index}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "court_line",
                    "label": line,
                    "properties": {"line_number": index},
                }
            )
            edges.append({"source": document_node_id, "target": node_id, "type": "filed_in"})

        if parsed.header.case_number:
            case_node_id = f"{graph_id}:case-number"
            nodes.append(
                {
                    "id": case_node_id,
                    "type": "case_number",
                    "label": parsed.header.case_number,
                    "properties": {},
                }
            )
            edges.append({"source": document_node_id, "target": case_node_id, "type": "identified_by"})

        for index, line in enumerate(parsed.header.party_lines, start=1):
            node_id = f"{graph_id}:party:{index}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "party_line",
                    "label": line,
                    "properties": {"line_number": index},
                }
            )
            edges.append({"source": document_node_id, "target": node_id, "type": "styles"})

        for index, line in enumerate(parsed.header.title_lines, start=1):
            node_id = f"{graph_id}:title:{index}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "title_line",
                    "label": line,
                    "properties": {"line_number": index},
                }
            )
            edges.append({"source": document_node_id, "target": node_id, "type": "titled_as"})

    for index, section in enumerate(parsed.sections, start=1):
        node_id = f"{graph_id}:section:{index}:{_slugify(section.heading)}"
        nodes.append(
            {
                "id": node_id,
                "type": section.kind,
                "label": section.heading,
                "properties": {"line_number": section.line_number},
            }
        )
        edges.append({"source": document_node_id, "target": node_id, "type": "has_section"})

    return {
        "graph_id": graph_id,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "document_title": parsed.title,
        },
    }


def parse_legal_document_to_graph(text: str, *, graph_id: str = "legal_document") -> Dict[str, Any]:
    """Convenience helper returning structure and graph payload together."""

    parsed = parse_legal_document(text)
    return {
        "parsed_document": parsed.to_dict(),
        "summary": parsed.summary(),
        "knowledge_graph": build_document_knowledge_graph(parsed, graph_id=graph_id),
    }


def required_formal_document_markers() -> List[str]:
    """Return default formal pleading markers for complaint-style documents."""

    return [
        "IN THE UNITED STATES DISTRICT COURT",
        "Civil Action No. ________________",
        "COMPLAINT FOR",
        "JURISDICTION AND VENUE",
        "FACTUAL ALLEGATIONS",
        "EVIDENTIARY SUPPORT AND NOTICE",
        "COUNT I -",
        "PRAYER FOR RELIEF",
        "JURY DEMAND",
        "SIGNATURE BLOCK",
    ]


def forbidden_formal_document_meta_phrases() -> List[str]:
    """Return meta phrases that indicate non-filing-style output."""

    return [
        "workflow summary",
        "complaint record",
        "support matrix",
        "mcp",
        "sdk",
        "product explanation",
        "json",
    ]


def validate_formal_document(
    body: str,
    *,
    required_markers: Optional[Sequence[str]] = None,
    preferred_heading: str = "",
    preferred_count_heading: str = "",
) -> List[str]:
    """Validate that a legal document resembles a formal complaint."""

    document_body = str(body or "").strip()
    issues: List[str] = []
    for marker in required_markers or required_formal_document_markers():
        if marker not in document_body:
            issues.append(f"Missing formal marker: {marker}")

    if not re.search(r"(?m)^\s*\d+\.\s+", document_body):
        issues.append("Missing numbered pleading paragraphs.")

    lowered = document_body.lower()
    for phrase in forbidden_formal_document_meta_phrases():
        if phrase in lowered:
            issues.append(f"Contains meta-summary language: {phrase}")

    if preferred_heading and preferred_heading not in document_body:
        issues.append(f"Missing preferred complaint heading: {preferred_heading}")
    if preferred_count_heading and preferred_count_heading not in document_body:
        issues.append(f"Missing preferred count heading: {preferred_count_heading}")
    return issues


def summarize_formal_document(
    body: str,
    *,
    required_markers: Optional[Sequence[str]] = None,
    preferred_heading: str = "",
    preferred_count_heading: str = "",
) -> Dict[str, Any]:
    """Summarize formal-structure signals for a pleading-style document."""

    parsed = parse_legal_document(body)
    markers = list(required_markers or required_formal_document_markers())
    issues = validate_formal_document(
        body,
        required_markers=markers,
        preferred_heading=preferred_heading,
        preferred_count_heading=preferred_count_heading,
    )
    present_markers = {marker: marker in str(body or "") for marker in markers}
    return {
        "parsed_document": parsed.to_dict(),
        "summary": parsed.summary(),
        "formal_sections_present": present_markers,
        "validation_issues": issues,
        "is_formally_valid": not issues,
    }


def _format_page_footer(page_number: int, total_pages: int, footer_label: str) -> str:
    label = f"{footer_label}  " if footer_label else ""
    return f"{label}Page {page_number} of {total_pages}".strip()
