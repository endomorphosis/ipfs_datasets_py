"""Reusable PDF rendering helpers for court filings and exhibit binders."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import re
from pathlib import Path
from textwrap import wrap
from typing import Iterable, Mapping, Optional, Sequence

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfgen import canvas


def humanize_label(text: str) -> str:
    text = text.replace(".md", "").replace(".pdf", "")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", lambda m: humanize_label(m.group(1)), text)
    text = text.replace("  ", " ")
    return text


def normalize_inline_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    return text.strip()


def wrap_text(text: str, width_chars: int = 100) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text or "").splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(wrap(paragraph, width=width_chars, replace_whitespace=False, drop_whitespace=False))
    return lines or [""]


def paginate_wrapped_lines(
    lines: Sequence[str],
    *,
    width_chars: int = 105,
    body_lines_per_page: int = 48,
) -> list[list[str]]:
    wrapped: list[str] = []
    for raw in lines:
        wrapped.extend(wrap_text(raw, width_chars))
    if not wrapped:
        return [[""]]
    return [wrapped[index : index + body_lines_per_page] for index in range(0, len(wrapped), body_lines_per_page)]


def draw_footer(pdf: canvas.Canvas, width: float, label: str, page_num: int, total_pages: int) -> None:
    pdf.setFont("Times-Roman", 10)
    pdf.drawString(0.75 * inch, 0.42 * inch, f"{label} | Page {page_num} of {total_pages}")


def render_text_lines_pdf(
    output_path: str | Path,
    title: str,
    lines: Sequence[str],
    *,
    footer_label: Optional[str] = None,
    width_chars: int = 105,
    body_lines_per_page: int = 48,
) -> Path:
    output_path = Path(output_path)
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    left = 0.75 * inch
    top = height - 0.75 * inch
    bottom = 1.0 * inch
    line_height = 13
    footer_label = footer_label or title
    pages = paginate_wrapped_lines(lines, width_chars=width_chars, body_lines_per_page=body_lines_per_page)
    total_pages = len(pages)

    for page_num, page_lines in enumerate(pages, start=1):
        if page_num > 1:
            pdf.showPage()
        pdf.setFont("Times-Bold", 14)
        pdf.drawString(left, top, title)
        pdf.setFont("Times-Roman", 12)
        y = top - 0.35 * inch
        for line in page_lines:
            pdf.drawString(left, y, line)
            y -= line_height
            if y < bottom:
                break
        draw_footer(pdf, width, footer_label, page_num, total_pages)
    pdf.save()
    return output_path


def match_backtick_block(text: str, heading: str) -> str:
    pattern = rf"`{re.escape(heading)}`\s+`([^`]+)`"
    match = re.search(pattern, text, re.S)
    return normalize_inline_markdown(match.group(1)) if match else ""


def match_numbered_block(text: str, heading: str) -> list[str]:
    pattern = rf"`{re.escape(heading)}`\s+(.*?)(?:\n`[A-Z][^`]*`|\Z)"
    match = re.search(pattern, text, re.S)
    if not match:
        return []
    body = match.group(1)
    items: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if re.match(r"^\d+\.\s+", line):
            items.append(normalize_inline_markdown(re.sub(r"^\d+\.\s+", "", line)))
    return items


def centered_header(pdf: canvas.Canvas, y: float, text: str, size: int = 15) -> None:
    width, _ = letter
    pdf.setFont("Times-Bold", size)
    pdf.drawCentredString(width / 2, y, text)


def draw_labeled_block(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    label: str,
    lines: Sequence[str],
    *,
    line_height: int = 13,
    label_gap: float = 0.18 * inch,
    bottom_gap: float = 0.16 * inch,
) -> float:
    pdf.setFont("Times-Bold", 12)
    pdf.drawString(x, y, label)
    y -= label_gap
    pdf.setFont("Times-Roman", 12)
    width_chars = max(20, int(width / 5.4))
    for line in lines:
        for part in wrap_text(line, width_chars):
            pdf.drawString(x + 0.12 * inch, y, part)
            y -= line_height
    return y - bottom_gap


@dataclass(frozen=True)
class ExhibitCaptionConfig:
    court_lines: Sequence[str]
    case_number: str
    right_block_lines: Sequence[str]
    left_block_label: str = "EXHIBIT VOLUME"


DEFAULT_EXHIBIT_CAPTION = ExhibitCaptionConfig(
    court_lines=(
        "IN THE CIRCUIT COURT OF THE STATE OF OREGON",
        "FOR THE COUNTY OF CLACKAMAS",
        "PROBATE DEPARTMENT",
    ),
    case_number="Case No. 26PR00641",
    right_block_lines=(
        "In the Matter of:",
        "Jane Kay Cortez,",
        "Protected Person.",
    ),
)


def draw_exhibit_caption(pdf: canvas.Canvas, top_y: float, *, config: ExhibitCaptionConfig = DEFAULT_EXHIBIT_CAPTION) -> float:
    width, _ = letter
    left = 0.85 * inch
    right = width - 0.85 * inch
    split_x = width * 0.60
    y = top_y
    pdf.setLineWidth(1)
    pdf.line(left, y, right, y)
    pdf.setFont("Times-Bold", 11)
    pdf.drawCentredString(width / 2, y - 0.18 * inch, str(config.court_lines[0]))
    pdf.setFont("Times-Roman", 11)
    for index, line in enumerate(config.court_lines[1:], start=1):
        pdf.drawCentredString(width / 2, y - (0.18 + (0.18 * index)) * inch, str(line))
    pdf.line(left, y - 0.72 * inch, right, y - 0.72 * inch)
    pdf.line(split_x, y - 0.72 * inch, split_x, y - 1.58 * inch)

    pdf.setFont("Times-Roman", 11)
    pdf.drawString(left + 0.08 * inch, y - 0.98 * inch, config.left_block_label)

    matter_y = y - 0.92 * inch
    for line in config.right_block_lines:
        pdf.drawString(split_x + 0.12 * inch, matter_y, str(line))
        matter_y -= 0.16 * inch
    pdf.drawString(split_x + 0.12 * inch, matter_y - 0.04 * inch, config.case_number)
    pdf.line(left, y - 1.58 * inch, right, y - 1.58 * inch)
    return y - 1.84 * inch


def render_exhibit_tab_from_markdown(
    md_path: str | Path,
    output_path: str | Path,
    *,
    caption_config: ExhibitCaptionConfig = DEFAULT_EXHIBIT_CAPTION,
) -> Path:
    md_path = Path(md_path)
    output_path = Path(output_path)
    text = md_path.read_text(errors="replace")
    exhibit_label = match_backtick_block(text, "EXHIBIT LABEL") or "Exhibit"
    section = match_backtick_block(text, "SECTION")
    short_title = match_backtick_block(text, "SHORT TITLE")
    status = match_backtick_block(text, "STATUS")

    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    left = 0.85 * inch
    y = draw_exhibit_caption(pdf, height - 0.95 * inch, config=caption_config)
    centered_header(pdf, y, "EXHIBIT", 15)
    y -= 0.38 * inch
    centered_header(pdf, y, exhibit_label.upper(), 20)
    y -= 0.5 * inch
    pdf.setLineWidth(1)
    pdf.line(left, y, width - left, y)
    y -= 0.75 * inch
    pdf.setFont("Times-Bold", 14)
    pdf.drawCentredString(width / 2, y, short_title)
    y -= 0.55 * inch
    pdf.setFont("Times-Italic", 11)
    pdf.drawCentredString(width / 2, y, section)
    y -= 0.3 * inch
    if status:
        pdf.setFont("Times-Roman", 11)
        pdf.drawCentredString(width / 2, y, status)
    draw_footer(pdf, width, exhibit_label, 1, 1)
    pdf.save()
    return output_path


def render_exhibit_cover_from_markdown(
    md_path: str | Path,
    output_path: str | Path,
    *,
    caption_config: ExhibitCaptionConfig = DEFAULT_EXHIBIT_CAPTION,
) -> Path:
    md_path = Path(md_path)
    output_path = Path(output_path)
    text = md_path.read_text(errors="replace")
    exhibit_label = match_backtick_block(text, "EXHIBIT LABEL") or "Exhibit"
    short_title = match_backtick_block(text, "SHORT TITLE")
    source = match_backtick_block(text, "SOURCE FILE")
    relied_on_by = match_numbered_block(text, "RELIED ON BY")
    propositions = match_numbered_block(text, "PROPOSITION(S) THIS EXHIBIT IS OFFERED TO SUPPORT")
    foundation = match_backtick_block(text, "AUTHENTICITY / FOUNDATION NOTE")
    limitation = match_backtick_block(text, "LIMITATION NOTE")

    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    left = 0.75 * inch
    right = width - 0.75 * inch
    y = draw_exhibit_caption(pdf, height - 0.95 * inch, config=caption_config)
    centered_header(pdf, y, "EXHIBIT COVER SHEET", 15)
    y -= 0.3 * inch
    centered_header(pdf, y, exhibit_label.upper(), 17)
    y -= 0.35 * inch
    pdf.setLineWidth(1)
    pdf.line(left, y, right, y)
    y -= 0.32 * inch

    y = draw_labeled_block(pdf, left, y, right - left, "1. Exhibit Label", [exhibit_label], line_height=12)
    y = draw_labeled_block(pdf, left, y, right - left, "2. Short Title", [short_title], line_height=12)
    y = draw_labeled_block(pdf, left, y, right - left, "3. Primary Source Record", [source], line_height=11)
    y = draw_labeled_block(
        pdf,
        left,
        y,
        right - left,
        "4. Filings Relying On This Exhibit",
        [f"{index + 1}. {item}" for index, item in enumerate(relied_on_by)] or ["None listed."],
        line_height=12,
    )
    y = draw_labeled_block(
        pdf,
        left,
        y,
        right - left,
        "5. Propositions This Exhibit Is Offered To Support",
        [f"{index + 1}. {item}" for index, item in enumerate(propositions)] or ["None listed."],
        line_height=12,
    )
    y = draw_labeled_block(
        pdf,
        left,
        y,
        right - left,
        "6. Authenticity / Foundation Note",
        wrap_text(foundation, 95),
        line_height=12,
    )
    draw_labeled_block(
        pdf,
        left,
        y,
        right - left,
        "7. Limitation Note",
        wrap_text(limitation, 95),
        line_height=12,
    )
    draw_footer(pdf, width, exhibit_label, 1, 1)
    pdf.save()
    return output_path


def parse_exhibit_cover_source(md_path: str | Path) -> str:
    md_path = Path(md_path)
    return match_backtick_block(md_path.read_text(errors="replace"), "SOURCE FILE")


@dataclass(frozen=True)
class StateCourtPleadingConfig:
    contact_block_html: str
    court_name: str
    state_name: str
    caption_left_html: str
    case_number_line: str = "Case No. __________________"
    filed_date: str = ""
    signature_doc_keywords: Sequence[str] = field(default_factory=tuple)
    declaration_doc_keywords: Sequence[str] = field(default_factory=tuple)


def _state_court_footer(pdf: canvas.Canvas, doc: SimpleDocTemplate) -> None:
    pdf.saveState()
    pdf.setFont("Times-Roman", 10)
    page_label = f"Page {pdf.getPageNumber()} of {doc.page_count}"
    page_x = letter[0] - doc.rightMargin
    page_y = 0.55 * inch
    pdf.drawRightString(page_x, page_y, page_label)
    available_width = page_x - doc.leftMargin - 0.7 * inch
    avg_char_width = 5.1
    max_chars = max(20, int(available_width / avg_char_width))
    wrapped_title = wrap(doc.title, width=max_chars)[:2]
    text_object = pdf.beginText()
    text_object.setTextOrigin(doc.leftMargin, 0.68 * inch if len(wrapped_title) > 1 else page_y)
    text_object.setFont("Times-Roman", 10)
    for line in wrapped_title:
        text_object.textLine(line)
    pdf.drawText(text_object)
    pdf.restoreState()


def _state_court_pleading_paper(pdf: canvas.Canvas, doc: SimpleDocTemplate) -> None:
    _state_court_footer(pdf, doc)
    pdf.saveState()
    pdf.setFont("Times-Roman", 8)
    top = letter[1] - 0.9 * inch
    step = 24
    for index in range(1, 29):
        y = top - (index - 1) * step
        if y < 0.95 * inch:
            break
        pdf.drawRightString(0.62 * inch, y, str(index))
    pdf.setLineWidth(0.3)
    pdf.line(0.7 * inch, 0.9 * inch, 0.7 * inch, letter[1] - 0.82 * inch)
    pdf.restoreState()


def render_state_court_markdown_to_pdf(
    md_path: str | Path,
    pdf_path: str | Path,
    *,
    config: StateCourtPleadingConfig,
    case_number_line: Optional[str] = None,
) -> Path:
    md_path = Path(md_path)
    pdf_path = Path(pdf_path)
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName="Times-Roman", fontSize=11.5, leading=15, spaceAfter=3)
    h1 = ParagraphStyle("h1", parent=base, fontName="Times-Bold", fontSize=12.5, leading=15.5, spaceBefore=2, spaceAfter=8, alignment=1)
    h2 = ParagraphStyle("h2", parent=base, fontName="Times-Bold", fontSize=12, leading=15, spaceBefore=8, spaceAfter=5)
    h3 = ParagraphStyle("h3", parent=base, fontName="Times-BoldItalic", fontSize=11.5, leading=14, spaceBefore=6, spaceAfter=3)
    small = ParagraphStyle("small", parent=base, fontSize=10.2, leading=13)
    quote = ParagraphStyle("quote", parent=base, leftIndent=18, fontName="Courier", fontSize=9.8, leading=12)
    centered = ParagraphStyle("centered", parent=base, alignment=1, fontName="Times-Bold", fontSize=11.5, leading=14)
    cap = ParagraphStyle("cap", parent=base, fontSize=11, leading=13)
    bodynum = ParagraphStyle("bodynum", parent=base, leftIndent=12, firstLineIndent=-12)

    story = []
    lines = md_path.read_text(encoding="utf-8").splitlines()
    title_line = ""
    detected_case_no = case_number_line or config.case_number_line
    body_start = 0
    first_heading_idx = None
    case_idx = None

    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("# ") and first_heading_idx is None:
            first_heading_idx = index
            title_line = stripped[2:].strip()
        if stripped.startswith("Case No."):
            case_idx = index
            detected_case_no = stripped
            break

    if case_idx is not None:
        body_start = case_idx + 1
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
        if body_start < len(lines):
            first_after = lines[body_start].strip()
            if first_after.isupper() or first_after.startswith("DEFENDANTS'") or first_after.startswith("[Proposed]"):
                title_line = first_after
                body_start += 1
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
    elif first_heading_idx is not None:
        body_start = first_heading_idx + 1

    story.append(Paragraph(config.contact_block_html, small))
    story.append(Spacer(1, 0.14 * inch))
    story.append(Paragraph(config.court_name, centered))
    story.append(Paragraph(config.state_name, centered))
    story.append(Spacer(1, 0.12 * inch))

    left = Paragraph(config.caption_left_html, cap)
    right = Paragraph(clean_inline(detected_case_no), cap)
    caption_table = Table([[left, right]], colWidths=[4.1 * inch, 2.0 * inch])
    caption_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBEFORE", (1, 0), (1, 0), 0.8, "black"),
                ("LEFTPADDING", (1, 0), (1, 0), 10),
            ]
        )
    )
    story.append(caption_table)
    story.append(Spacer(1, 0.16 * inch))

    if title_line:
        story.append(Paragraph(clean_inline(title_line), h1))
        story.append(Spacer(1, 0.06 * inch))

    in_code = False
    code_lines: list[str] = []
    for raw in lines[body_start:]:
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                story.append(Paragraph("<br/>".join(clean_inline(item) for item in code_lines), quote))
                story.append(Spacer(1, 0.06 * inch))
                in_code = False
            continue
        if in_code:
            code_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 0.05 * inch))
            continue
        if stripped == "---":
            story.append(Spacer(1, 0.08 * inch))
            continue
        if stripped.startswith("## "):
            story.append(Paragraph(clean_inline(stripped[3:]), h2))
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(clean_inline(stripped[4:]), h3))
            continue
        if re.fullmatch(r"[A-Z0-9 ,.'&()\[\]/-]{8,}", stripped):
            story.append(Paragraph(clean_inline(stripped), h2))
            continue

        ordered_match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if ordered_match:
            number, text = ordered_match.groups()
            story.append(Paragraph(f"<b>{number}.</b> {clean_inline(text)}", bodynum))
            continue

        dash_match = re.match(r"^-\s+(.*)$", stripped)
        if dash_match:
            story.append(Paragraph(f"&#8226; {clean_inline(dash_match.group(1))}", base))
            continue

        story.append(Paragraph(clean_inline(stripped), small if "Case No." in stripped else base))

    stem = md_path.stem.lower()
    if any(keyword in stem for keyword in config.signature_doc_keywords) and not stem.startswith("proposed_order"):
        sig_block = [
            Spacer(1, 0.22 * inch),
            Paragraph(f"Dated: {config.filed_date}", base),
            Spacer(1, 0.08 * inch),
            Paragraph("Respectfully submitted,", base),
            Spacer(1, 0.16 * inch),
            Paragraph("Submitted by Defendants:", base),
            Spacer(1, 0.20 * inch),
            Paragraph("__________________________________", base),
            Paragraph("Signature", small),
            Spacer(1, 0.12 * inch),
            Paragraph("Benjamin Jay Barber, pro se", base),
            Spacer(1, 0.22 * inch),
            Paragraph("__________________________________", base),
            Paragraph("Signature", small),
            Spacer(1, 0.12 * inch),
            Paragraph("Jane Kay Cortez, pro se", base),
        ]
        story.append(KeepTogether(sig_block))
    elif any(keyword in stem for keyword in config.declaration_doc_keywords):
        decl_block = [
            Spacer(1, 0.22 * inch),
            Paragraph(f"Dated: {config.filed_date}", base),
            Spacer(1, 0.24 * inch),
            Paragraph("__________________________________", base),
            Paragraph("Signature", small),
            Spacer(1, 0.12 * inch),
        ]
        decl_block.append(
            Paragraph(
                "Benjamin Jay Barber, Declarant" if "benjamin" in stem else "Jane Kay Cortez, Declarant",
                base,
            )
        )
        story.append(KeepTogether(decl_block))

    doc_title = humanize_label(title_line) if title_line else humanize_label(md_path.stem)
    doc_kwargs = dict(
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.85 * inch,
        title=doc_title,
    )
    count_doc = SimpleDocTemplate(str(pdf_path), **doc_kwargs)
    story_for_count = copy.deepcopy(story)
    page_counter: list[int] = []

    def _capture_page_count(count_pdf: canvas.Canvas, _doc: SimpleDocTemplate) -> None:
        page_counter.append(count_pdf.getPageNumber())

    count_doc.build(story_for_count, onFirstPage=_capture_page_count, onLaterPages=_capture_page_count)
    doc = SimpleDocTemplate(str(pdf_path), **doc_kwargs)
    doc.page_count = len(page_counter)
    doc.build(story, onFirstPage=_state_court_pleading_paper, onLaterPages=_state_court_pleading_paper)
    return pdf_path


def render_state_court_pdf_batch(
    md_paths: Sequence[str | Path],
    output_dir: str | Path,
    *,
    config: StateCourtPleadingConfig,
) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for md_path in md_paths:
        md_path = Path(md_path)
        pdf_path = output_dir / f"{md_path.stem}.pdf"
        render_state_court_markdown_to_pdf(md_path, pdf_path, config=config)
        outputs.append(pdf_path)
    return outputs


def build_state_court_filing_packet(
    md_paths: Sequence[str | Path],
    output_dir: str | Path,
    output_pdf: str | Path,
    *,
    config: StateCourtPleadingConfig,
) -> dict[str, object]:
    rendered_paths = render_state_court_pdf_batch(md_paths, output_dir, config=config)
    from .exhibit_binder_export import merge_pdfs

    packet_path = merge_pdfs(output_pdf, rendered_paths)
    return {
        "rendered_paths": [str(path) for path in rendered_paths],
        "packet_path": str(packet_path),
        "document_count": len(rendered_paths),
    }


__all__ = [
    "DEFAULT_EXHIBIT_CAPTION",
    "ExhibitCaptionConfig",
    "StateCourtPleadingConfig",
    "centered_header",
    "clean_inline",
    "draw_exhibit_caption",
    "draw_footer",
    "draw_labeled_block",
    "humanize_label",
    "match_backtick_block",
    "match_numbered_block",
    "normalize_inline_markdown",
    "paginate_wrapped_lines",
    "parse_exhibit_cover_source",
    "render_exhibit_cover_from_markdown",
    "render_exhibit_tab_from_markdown",
    "build_state_court_filing_packet",
    "render_state_court_pdf_batch",
    "render_state_court_markdown_to_pdf",
    "render_text_lines_pdf",
    "wrap_text",
]
