"""Court-ready exhibit binder template renderers."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import re
from textwrap import wrap
from typing import Mapping, Sequence

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


@dataclass(frozen=True)
class BinderCourtConfig:
    case_number: str
    court_name: str
    state_name: str
    contact_block_html: str
    caption_left_html: str


DEFAULT_BINDER_COURT_CONFIG = BinderCourtConfig(
    case_number="__________________",
    court_name="IN THE COURT OF COMPETENT JURISDICTION",
    state_name="STATE / JURISDICTION",
    contact_block_html=(
        "Filing Party, pro se<br/>Street Address<br/>City, State ZIP<br/>"
        "Phone<br/>Email<br/>Party Role"
    ),
    caption_left_html=(
        "PLAINTIFF OR PETITIONER,<br/>Role,<br/><br/>v.<br/><br/>"
        "DEFENDANT OR RESPONDENT,<br/>Role."
    ),
)


def shorten_display_paths(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        path = Path(match.group(0))
        parts = path.parts
        if len(parts) >= 2:
            return "/".join(parts[-2:])
        return path.name

    return re.sub(r"/home/barberb/HACC/[^\s)]+", repl, text)


def _footer(pdf, doc) -> None:
    pdf.saveState()
    pdf.setFont("Times-Roman", 10)
    page_label = f"Page {pdf.getPageNumber()} of {doc.page_count}"
    page_x = letter[0] - doc.rightMargin
    page_y = 0.55 * inch
    pdf.drawRightString(page_x, page_y, page_label)
    wrapped_title = wrap(doc.title, width=70)[:2]
    text = pdf.beginText()
    text.setTextOrigin(doc.leftMargin, 0.68 * inch if len(wrapped_title) > 1 else page_y)
    text.setFont("Times-Roman", 10)
    for line in wrapped_title:
        text.textLine(line)
    pdf.drawText(text)
    pdf.restoreState()


def _binder_page(pdf, doc) -> None:
    _footer(pdf, doc)


def _caption_table(config: BinderCourtConfig, cap_style: ParagraphStyle) -> Table:
    left = Paragraph(config.caption_left_html, cap_style)
    right = Paragraph(f"Case No. {config.case_number}", cap_style)
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
    return caption_table


def _build_doc(pdf_path: Path, story: list, *, title: str) -> Path:
    doc_kwargs = dict(
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.85 * inch,
        title=title,
    )
    count_doc = SimpleDocTemplate(str(pdf_path), **doc_kwargs)
    counter: list[int] = []

    def count_pages(pdf, _doc):
        counter.append(pdf.getPageNumber())

    count_doc.build(copy.deepcopy(story), onFirstPage=count_pages, onLaterPages=count_pages)
    doc = SimpleDocTemplate(str(pdf_path), **doc_kwargs)
    doc.page_count = len(counter)
    doc.build(story, onFirstPage=_binder_page, onLaterPages=_binder_page)
    return pdf_path


def render_exhibit_binder_front_sheet(
    md_path: str | Path,
    pdf_path: str | Path,
    *,
    config: BinderCourtConfig = DEFAULT_BINDER_COURT_CONFIG,
) -> Path:
    md_path = Path(md_path)
    pdf_path = Path(pdf_path)
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName="Times-Roman", fontSize=11.5, leading=15, spaceAfter=3)
    small = ParagraphStyle("small", parent=base, fontSize=10.2, leading=13)
    centered = ParagraphStyle("centered", parent=base, alignment=1, fontName="Times-Bold", fontSize=11.5, leading=14)
    cap = ParagraphStyle("cap", parent=base, fontSize=11, leading=13)
    h1 = ParagraphStyle("h1", parent=base, fontName="Times-Bold", fontSize=12.5, leading=15.5, spaceBefore=2, spaceAfter=8, alignment=1)

    def clean(text: str) -> str:
        text = shorten_display_paths(text)
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("`", "")

    lines = md_path.read_text(encoding="utf-8").splitlines()
    body_lines: list[str] = []
    title = "Defendants' Exhibit Binder"
    body_started = False
    for raw in lines:
        stripped = raw.strip()
        if not body_started and (
            not stripped
            or stripped.startswith("IN THE ")
            or stripped == config.state_name
            or stripped.startswith("Case No.")
        ):
            continue
        body_started = True
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            continue
        body_lines.append(raw)

    story = [
        Paragraph(config.contact_block_html, small),
        Spacer(1, 0.14 * inch),
        Paragraph(config.court_name, centered),
        Paragraph(config.state_name, centered),
        Spacer(1, 0.12 * inch),
        _caption_table(config, cap),
        Spacer(1, 0.16 * inch),
        Paragraph(clean(title), h1),
        Spacer(1, 0.06 * inch),
    ]
    for raw in body_lines:
        stripped = raw.strip()
        if not stripped:
            story.append(Spacer(1, 0.05 * inch))
            continue
        if stripped.startswith("- "):
            story.append(Paragraph(f"&#8226; {clean(stripped[2:])}", base))
            continue
        if len(stripped) > 1 and stripped[:2].isdigit() and stripped[1] == ".":
            story.append(Paragraph(clean(stripped), base))
            continue
        story.append(Paragraph(clean(stripped), base))
    return _build_doc(pdf_path, story, title=title)


def render_table_of_exhibits_pdf(
    pdf_path: str | Path,
    *,
    exhibit_order: Sequence[str],
    exhibit_titles: Mapping[str, str],
    starts: Mapping[str, int],
    counts: Mapping[str, int],
    config: BinderCourtConfig = DEFAULT_BINDER_COURT_CONFIG,
) -> Path:
    pdf_path = Path(pdf_path)
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName="Times-Roman", fontSize=10.3, leading=12.5, spaceAfter=2)
    small = ParagraphStyle("small", parent=base, fontSize=9.5, leading=11.5)
    h1 = ParagraphStyle("h1", parent=base, fontName="Times-Bold", fontSize=12.5, leading=15.5, alignment=1, spaceAfter=8)
    centered = ParagraphStyle("centered", parent=base, alignment=1, fontName="Times-Bold", fontSize=11.2, leading=13.5)
    cap = ParagraphStyle("cap", parent=base, fontSize=10.8, leading=12.5)

    story = [
        Paragraph(config.court_name, centered),
        Paragraph(config.state_name, centered),
        Spacer(1, 0.10 * inch),
        _caption_table(config, cap),
        Spacer(1, 0.14 * inch),
        Paragraph("Table Of Exhibits", h1),
        Paragraph(
            "Binder page references correspond to the compiled master volume beginning with the binder front sheet as page 1.",
            base,
        ),
        Spacer(1, 0.08 * inch),
    ]

    rows = [[
        Paragraph("<b>Exhibit</b>", small),
        Paragraph("<b>Title</b>", small),
        Paragraph("<b>Start</b>", small),
        Paragraph("<b>Range</b>", small),
    ]]
    for exhibit_code in exhibit_order:
        start = int(starts[exhibit_code])
        page_count = int(counts[exhibit_code])
        end = start + page_count - 1
        page_range = f"{start}-{end}" if end != start else f"{start}"
        rows.append([
            Paragraph(f"Exhibit {exhibit_code}", small),
            Paragraph(str(exhibit_titles[exhibit_code]), small),
            Paragraph(str(start), small),
            Paragraph(page_range, small),
        ])

    toc_table = Table(rows, colWidths=[1.0 * inch, 4.2 * inch, 0.6 * inch, 0.8 * inch], repeatRows=1)
    toc_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, "black"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), "#EDEDED"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend(
        [
            toc_table,
            Spacer(1, 0.10 * inch),
            Paragraph(
                "Each exhibit is preceded by a tab divider and a cover sheet identifying the source file, key source location, supported assertion, and where that assertion appears in the filing papers.",
                base,
            ),
        ]
    )
    return _build_doc(pdf_path, story, title="Table Of Exhibits")


__all__ = [
    "BinderCourtConfig",
    "DEFAULT_BINDER_COURT_CONFIG",
    "render_exhibit_binder_front_sheet",
    "render_table_of_exhibits_pdf",
    "shorten_display_paths",
]
