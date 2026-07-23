"""Legacy court-style packet renderer extracted from workspace scripts."""

from __future__ import annotations

import email
import json
import re
import subprocess
import textwrap
from copy import deepcopy
from email import policy
from pathlib import Path
from typing import Any

from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path("/home/barberb/HACC/workspace")
SUMMARY_PATH = ROOT / "improved-complaint-from-temporary-session.summary.json"
COMPLAINT_MD = ROOT / "improved-complaint-from-temporary-session.md"
FULL_PACKET_DIR = ROOT / "assembled-full-packet"
REDUCED_PACKET_DIR = ROOT / "assembled-reduced-packet"


DEFAULT_COURTSTYLE_PACKET_CONFIG: dict[str, Any] = {
    "root_dir": str(ROOT),
    "summary_path": str(SUMMARY_PATH),
    "complaint_md_path": str(COMPLAINT_MD),
    "full_packet_dir": str(FULL_PACKET_DIR),
    "reduced_packet_dir": str(REDUCED_PACKET_DIR),
    "complaint_output_relative": "rendered/0001_complaint_courtstyle_v2.pdf",
    "body_start_marker": "Plaintiffs allege as follows:",
    "curated_sources": {
        "Exhibit J": [
            "README.md",
            "representative_messages/J-12_message.eml",
            "representative_messages/J-13_message.eml",
            "representative_messages/J-14_message.eml",
            "representative_messages/J-15_message.eml",
            "representative_messages/J-16_message.eml",
            "retained_attachments/J-1_Additional-Information-Needed-02.09.2026.pdf",
            "retained_attachments/J-5_Additional-Information-Needed-02.25.2026.pdf",
            "retained_attachments/J-12_Image_260226_173823.jpeg",
            "retained_attachments/J-12_Image_260226_173852.jpeg",
            "retained_attachments/J-15_Image_260309_103446.jpeg",
        ],
        "Exhibit M": [
            "README.md",
            "representative_messages/M-3_message.eml",
            "representative_messages/M-4_message.eml",
            "representative_messages/M-7_message.eml",
            "representative_messages/M-8_message.eml",
            "representative_messages/M-9_message.eml",
            "representative_messages/M-10_message.eml",
            "representative_messages/M-11_message.eml",
            "retained_attachments/M-3_Cortez-TRSW-3.18.26.pdf",
            "retained_attachments/M-4_TRSW---JC---03.19.2026.pdf",
            "retained_attachments/M-4_VO---JC---03.19.2026.pdf",
            "retained_attachments/M-7_Orientation---Required-Signatures-03.19.2026.pdf",
            "retained_attachments/M-10_output.pdf",
            "retained_attachments/M-8_Image_260320_142045.jpeg",
            "retained_attachments/M-8_Image_260320_142321.jpeg",
            "retained_attachments/M-8_Image_260320_142448.jpeg",
        ],
        "Exhibit R": [
            "summary.json",
            "seq_10269/headers.txt",
            "seq_10269/body-snippet.txt",
            "seq_10270/headers.txt",
            "seq_10270/body-snippet.txt",
            "seq_10273/headers.txt",
            "seq_10273/body-snippet.txt",
            "seq_10279/headers.txt",
            "seq_10279/body-snippet.txt",
            "seq_10280/headers.txt",
            "seq_10280/body-snippet.txt",
        ],
    },
    "r_snippet_ids": ["seq_10269", "seq_10270", "seq_10273", "seq_10279", "seq_10280"],
    "r_summary_intro_lines": [
        "Preserved Gmail sent-mail records confirm complaint emails on February 26, March 2, and March 9, 2026.",
        "The preserved headers show recipients Kati Tilton, Ashley Ferron, and charity@magikcorp.com.",
        "The body snippets say Blossom refused to process the application, refused to house a service animal, and engaged in discrimination on the basis of race.",
    ],
    "summary_sections": {
        "Exhibit J": [
            {
                "heading": "Representative messages",
                "lines": [
                    "J-12_message.eml, J-13_message.eml, J-14_message.eml, J-15_message.eml, and J-16_message.eml are the strongest complaint-thread records.",
                    "These messages capture the February 26, March 2, and March 9, 2026 sequence tied to additional-information demands, Blossom processing complaints, service-animal issues, and race-discrimination allegations.",
                ],
            },
            {
                "heading": "Key retained attachments",
                "lines": [
                    "J-1_Additional-Information-Needed-02.09.2026.pdf",
                    "J-5_Additional-Information-Needed-02.25.2026.pdf",
                    "J-12_Image_260226_173823.jpeg",
                    "J-12_Image_260226_173852.jpeg",
                    "J-15_Image_260309_103446.jpeg",
                ],
            },
        ],
        "Exhibit M": [
            {
                "heading": "Representative messages",
                "lines": [
                    "M-3_message.eml, M-4_message.eml, M-7_message.eml, M-8_message.eml, M-9_message.eml, M-10_message.eml, and M-11_message.eml capture the orientation, voucher reversal, and accommodation sequence.",
                    "These materials support the March 17 through March 20, 2026 chronology concerning the two-bedroom voucher issuance, reversal, and accommodation-related follow-up.",
                ],
            },
            {
                "heading": "Key retained attachments",
                "lines": [
                    "M-4_TRSW---JC---03.19.2026.pdf",
                    "M-4_VO---JC---03.19.2026.pdf",
                    "M-7_Orientation---Required-Signatures-03.19.2026.pdf",
                    "M-10_output.pdf",
                    "M-8_Image_260320_142045.jpeg",
                    "M-8_Image_260320_142321.jpeg",
                    "M-8_Image_260320_142448.jpeg",
                ],
            },
        ],
    },
    "static_image_exhibits": [
        {
            "source": "improved-complaint-from-temporary-session.former-employee-review.png",
            "output_name": "Exhibit_Q_image.pdf",
            "title": "Exhibit Q - Former-employee review screenshot",
        },
        {
            "source": "improved-complaint-from-temporary-session.shs-race-goal.png",
            "output_name": "Exhibit_S_image.pdf",
            "title": "Exhibit S - SHS race-conscious outcome goal screenshot",
        },
        {
            "source": "temporary-cli-session-migration/prior-research-results/full-evidence-review-run/chronology/emergency_motion_packet/exhibits/Exhibit N - Julio Eviction notice.jpeg",
            "output_name": "Exhibit_N_image.pdf",
            "title": "Exhibit N - Julio eviction notice",
        },
    ],
}


def _deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _resolve_path(base_dir: Path, value: str | Path) -> Path:
    value_path = Path(value)
    return value_path if value_path.is_absolute() else base_dir / value_path


def _footer(c: canvas.Canvas, doc: SimpleDocTemplate) -> None:
    c.saveState()
    c.setFont("Times-Roman", 10)
    c.drawString(doc.leftMargin, 0.5 * inch, "Complaint")
    c.drawRightString(letter[0] - doc.rightMargin, 0.5 * inch, f"Page {doc.page}")
    c.restoreState()


def _load_body_lines(*, complaint_md_path: Path = COMPLAINT_MD, body_start_marker: str = "Plaintiffs allege as follows:") -> list[str]:
    lines = complaint_md_path.read_text(encoding="utf-8").splitlines()
    body: list[str] = []
    skip = True
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if skip:
            if line == body_start_marker:
                skip = False
            continue
        body.append(line)
    return body


def _caption_breaks(text: str) -> str:
    text = text.replace(", and ", ",<br/>and ")
    text = text.replace(" and Quantum Residential", "<br/>and Quantum Residential")
    text = text.replace(" and Julio Regal Florez-Cortez", "<br/>and Julio Regal Florez-Cortez")
    return text


def build_courtstyle_complaint(
    out_pdf: Path,
    *,
    summary_path: Path = SUMMARY_PATH,
    complaint_md_path: Path = COMPLAINT_MD,
    body_start_marker: str = "Plaintiffs allege as follows:",
) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    meta = summary.get("filing_metadata", {})
    caption_plaintiffs = summary.get("caption_plaintiffs", "")
    caption_defendants = summary.get("defendants", meta.get("caption_defendants", ""))
    address = meta.get("mailing_address", "")
    sig_name = meta.get("signature_plaintiff", "Benjamin Jay Barber")
    body_lines = _load_body_lines(complaint_md_path=complaint_md_path, body_start_marker=body_start_marker)

    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "base",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=12,
        leading=22,
        spaceAfter=0,
    )
    small = ParagraphStyle("small", parent=base, fontSize=10, leading=12)
    center = ParagraphStyle("center", parent=base, alignment=1, fontSize=11.5, leading=13.5, spaceAfter=2)
    heading = ParagraphStyle(
        "heading",
        parent=base,
        fontName="Times-Bold",
        fontSize=11.5,
        alignment=1,
        leading=14,
        spaceBefore=5,
        spaceAfter=3,
        keepWithNext=True,
    )
    sub = ParagraphStyle("sub", parent=base, fontName="Times-Bold", leading=16, spaceBefore=4, spaceAfter=4)
    cap = ParagraphStyle("cap", parent=base, fontSize=11, leading=12)
    case_box = ParagraphStyle("case_box", parent=cap, fontName="Times-Roman", leading=13)
    title = ParagraphStyle("title", parent=base, fontName="Times-Bold", fontSize=12.4, leading=14.2, alignment=1)

    story = []
    contact = [f"{sig_name}, pro se"]
    if address:
        contact.append(address)
    story.append(Paragraph("<br/>".join(contact), small))
    story.append(Spacer(1, 0.14 * inch))

    story.append(Paragraph("IN THE UNITED STATES DISTRICT COURT", center))
    story.append(Paragraph("FOR THE DISTRICT OF OREGON", center))
    story.append(Paragraph("Portland Division", center))
    story.append(Spacer(1, 0.12 * inch))

    caption_left = Paragraph(
        (
            f"{_caption_breaks(caption_plaintiffs)}<br/>"
            "<b>Plaintiffs,</b><br/><br/>"
            "<b>v.</b><br/><br/>"
            f"{_caption_breaks(caption_defendants)}<br/>"
            "<b>Defendants.</b>"
        ),
        cap,
    )
    right_case = Paragraph(
        "Civil Action No. __________________<br/><br/><b>COMPLAINT</b><br/><b>DEMAND FOR JURY TRIAL</b>",
        case_box,
    )
    caption_table = Table(
        [[caption_left, right_case]],
        colWidths=[3.95 * inch, 2.25 * inch],
    )
    caption_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (1, 0), (1, 0), "LEFT"),
                ("LINEBEFORE", (1, 0), (1, 0), 0.8, "black"),
                ("LEFTPADDING", (1, 0), (1, 0), 10),
                ("LINEABOVE", (0, 0), (1, 0), 0.8, "black"),
                ("LINEBELOW", (0, 0), (1, 0), 0.8, "black"),
            ]
        )
    )
    story.append(caption_table)
    story.append(Spacer(1, 0.12 * inch))

    long_title = (
        "COMPLAINT FOR VIOLATION OF THE FAIR HOUSING ACT, SECTION 504 OF THE "
        "REHABILITATION ACT, TITLE II OF THE AMERICANS WITH DISABILITIES ACT, "
        "42 U.S.C. sections 1981 and 1983, AND RELATED OREGON HOUSING LAW"
    )
    story.append(Paragraph(long_title, title))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Plaintiffs allege as follows:", base))
    story.append(Spacer(1, 0.08 * inch))

    for line in body_lines:
        if line == "JURISDICTION AND VENUE":
            story.append(PageBreak())
        if re.fullmatch(r"[A-Z][A-Z\s&\-]+", line):
            story.append(Paragraph(line, heading))
            continue
        if line in {"COUNT I", "COUNT II", "COUNT III", "COUNT IV", "COUNT V", "COUNT VI", "COUNT VII", "PRAYER FOR RELIEF", "JURY DEMAND", "SIGNATURE BLOCK"}:
            story.append(Paragraph(line, heading))
            continue
        if line.startswith("Against "):
            story.append(Paragraph(line, sub))
            continue
        match_num = re.match(r"^(\d+)\.\s+(.*)$", line)
        if match_num:
            num, body = match_num.groups()
            story.append(Paragraph(f"<b>{num}.</b> {body.replace('`', '')}", base))
            continue
        match_letter = re.match(r"^([A-I])\.\s+(.*)$", line)
        if match_letter:
            label, body = match_letter.groups()
            story.append(Paragraph(f"<b>{label}.</b> {body.replace('`', '')}", base))
            continue
        story.append(Paragraph(line.replace("`", ""), base))

    doc = SimpleDocTemplate(
        str(out_pdf),
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.8 * inch,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def make_text_pdf(path: Path, title: str, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 72
    c.setFont("Times-Bold", 16)
    c.drawString(72, y, title)
    y -= 28
    c.setFont("Times-Roman", 11)
    for line in lines:
        for wrapped in textwrap.wrap(str(line), width=88) or [""]:
            if y < 72:
                c.showPage()
                y = height - 72
                c.setFont("Times-Roman", 11)
            c.drawString(72, y, wrapped)
            y -= 14
        y -= 4
    c.save()


def make_summary_exhibit_pdf(path: Path, title: str, sections: list[tuple[str, list[str]]]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 72
    c.setFont("Times-Bold", 16)
    c.drawString(72, y, title)
    y -= 24
    for heading, lines in sections:
        if y < 110:
            c.showPage()
            y = height - 72
        c.setFont("Times-Bold", 12)
        c.drawString(72, y, heading)
        y -= 18
        c.setFont("Times-Roman", 11)
        for line in lines:
            for wrapped in textwrap.wrap(str(line), width=88) or [""]:
                if y < 72:
                    c.showPage()
                    y = height - 72
                    c.setFont("Times-Roman", 11)
                c.drawString(84, y, wrapped)
                y -= 14
            y -= 2
        y -= 8
    c.save()


def make_exhibit_index_pdf(path: Path, entries: list[tuple[str, str, int, int]]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    left = 72
    right = width - 72
    y = height - 72

    def header() -> float:
        c.setFont("Times-Bold", 16)
        c.drawString(left, height - 50, "Exhibit Index")
        c.setFont("Times-Roman", 11)
        c.drawString(left, height - 68, "Curated filing packet exhibit order and starting page references.")
        c.setFont("Times-Bold", 11)
        c.drawString(left, height - 92, "Exhibit")
        c.drawString(left + 72, height - 92, "Description")
        c.drawRightString(right - 40, height - 92, "Start")
        c.drawRightString(right, height - 92, "End")
        c.line(left, height - 98, right, height - 98)
        return height - 114

    y = header()
    c.setFont("Times-Roman", 10.5)
    for label, desc, start, end in entries:
        wrapped = textwrap.wrap(desc, width=54) or [desc]
        row_height = 14 * len(wrapped) + 3
        if y - row_height < 62:
            c.showPage()
            y = header()
            c.setFont("Times-Roman", 10.5)
        c.drawString(left, y, label)
        for i, line in enumerate(wrapped):
            c.drawString(left + 72, y - (14 * i), line)
        c.drawRightString(right - 40, y, str(start))
        c.drawRightString(right, y, str(end))
        y -= row_height
    c.save()


def make_filing_cover_pdf(path: Path, plaintiffs: str, defendants: str, filer: str, address: str, page_count: int) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    left = 72
    right = width - 72
    y = height - 72

    c.setFont("Times-Bold", 16)
    c.drawCentredString(width / 2, y, "PRO SE FILING COVER SHEET")
    y -= 28
    c.setFont("Times-Roman", 11)
    c.drawCentredString(width / 2, y, "For hand-filing or print assembly with the complaint packet below.")
    y -= 34

    c.setFont("Times-Bold", 12)
    c.drawString(left, y, "Court")
    c.setFont("Times-Roman", 11)
    c.drawString(left + 90, y, "United States District Court for the District of Oregon, Portland Division")
    y -= 22

    c.setFont("Times-Bold", 12)
    c.drawString(left, y, "Filer")
    c.setFont("Times-Roman", 11)
    c.drawString(left + 90, y, f"{filer}, pro se")
    y -= 18
    c.drawString(left + 90, y, address)
    y -= 24

    c.setFont("Times-Bold", 12)
    c.drawString(left, y, "Document")
    c.setFont("Times-Roman", 11)
    c.drawString(left + 90, y, "Complaint with curated exhibit packet and exhibit index")
    y -= 24

    c.setFont("Times-Bold", 12)
    c.drawString(left, y, "Parties")
    y -= 18
    c.setFont("Times-Roman", 11)
    text = c.beginText(left + 12, y)
    text.textLine(f"Plaintiffs: {plaintiffs}")
    text.textLine("")
    text.textLine(f"Defendants: {defendants}")
    c.drawText(text)
    y -= 52

    c.setFont("Times-Bold", 12)
    c.drawString(left, y, "Contents")
    y -= 18
    c.setFont("Times-Roman", 11)
    for line in [
        "1. Complaint",
        "2. Exhibit index",
        "3. Curated Exhibits A through R",
        f"4. Total packet length: approximately {page_count} pages",
    ]:
        c.drawString(left + 12, y, line)
        y -= 16

    y -= 12
    c.setFont("Times-Bold", 12)
    c.drawString(left, y, "Clerk Note")
    y -= 18
    c.setFont("Times-Roman", 11)
    note = (
        "This cover sheet is a packet separator prepared for print assembly. It is not intended "
        "to substitute for any official civil cover sheet, summons form, or local filing form "
        "required by the court."
    )
    text = c.beginText(left + 12, y)
    for line in textwrap.wrap(note, width=86):
        text.textLine(line)
    c.drawText(text)

    c.rect(0.8 * inch, 0.8 * inch, width - 1.6 * inch, height - 1.6 * inch)
    c.save()


def make_document_pdf(path: Path, title: str, lines: list[str], mono: bool = False) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    left = 72
    top = height - 72
    bottom = 60
    body_font = "Courier" if mono else "Times-Roman"
    wrap_width = 88 if not mono else 78

    def new_page() -> float:
        c.showPage()
        c.setFont("Times-Bold", 14)
        c.drawString(left, height - 50, title)
        c.setFont(body_font, 10.5 if mono else 11)
        return height - 78

    c.setFont("Times-Bold", 14)
    c.drawString(left, height - 50, title)
    c.setFont(body_font, 10.5 if mono else 11)
    y = height - 78

    for line in lines:
        pieces = textwrap.wrap(str(line), width=wrap_width) or [""]
        for piece in pieces:
            if y < bottom:
                y = new_page()
            c.drawString(left, y, piece)
            y -= 13 if mono else 14
        y -= 3
    c.save()


def make_exhibit_cover(path: Path, label: str, title: str, use: str) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    c.setLineWidth(1)
    c.rect(0.9 * inch, 1.2 * inch, width - 1.8 * inch, height - 2.4 * inch)
    c.setFont("Times-Bold", 24)
    c.drawCentredString(width / 2, height - 2.0 * inch, label)
    c.setFont("Times-Bold", 18)
    text = c.beginText(1.35 * inch, height - 2.8 * inch)
    for line in textwrap.wrap(title, width=42):
        text.textLine(line)
    c.drawText(text)
    c.setFont("Times-Roman", 13)
    use_text = c.beginText(1.35 * inch, height - 4.2 * inch)
    use_text.textLine("Use:")
    for line in textwrap.wrap(use, width=68):
        use_text.textLine(line)
    c.drawText(use_text)
    c.save()


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _eml_lines(path: Path) -> list[str]:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    lines = [
        f"File: {path.name}",
        f"From: {msg.get('from', '')}",
        f"To: {msg.get('to', '')}",
        f"Cc: {msg.get('cc', '')}",
        f"Date: {msg.get('date', '')}",
        f"Subject: {msg.get('subject', '')}",
        "",
        "Body:",
    ]
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in (part.get("Content-Disposition", "") or ""):
                try:
                    body = part.get_content()
                    break
                except Exception:
                    continue
    else:
        try:
            body = msg.get_content()
        except Exception:
            body = ""
    body = _clean_text(body)
    if not body:
        body = "[No plain-text body extracted from preserved message.]"
    lines.extend(body.splitlines())
    return lines


def _text_file_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    lines = [f"File: {path.name}", ""]
    lines.extend(_clean_text(text).splitlines())
    return lines


def _merge_pdfs(out_path: Path, inputs: list[Path]) -> None:
    if not inputs:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "gs",
        "-dBATCH",
        "-dNOPAUSE",
        "-q",
        "-sDEVICE=pdfwrite",
        f"-sOutputFile={out_path}",
    ]
    cmd.extend(str(item) for item in inputs)
    subprocess.run(cmd, check=True)


def _render_folder_exhibit(exhibit_dir: Path, out_pdf: Path, title: str) -> None:
    component_dir = out_pdf.with_suffix("")
    component_dir.mkdir(parents=True, exist_ok=True)
    merge_inputs: list[Path] = []
    index_lines = [f"Expanded source path: {exhibit_dir}", ""]

    for source in sorted(p for p in exhibit_dir.rglob("*") if p.is_file()):
        rel = source.relative_to(exhibit_dir)
        suffix = source.suffix.lower()
        safe_name = "__".join(rel.parts).replace(" ", "_")
        index_lines.append(str(rel))
        if suffix == ".pdf":
            merge_inputs.append(source)
            continue
        if suffix in {".png", ".jpg", ".jpeg"}:
            rendered = component_dir / f"{safe_name}.pdf"
            image_to_pdf(source, rendered, str(rel))
            merge_inputs.append(rendered)
            continue
        if suffix == ".eml":
            rendered = component_dir / f"{safe_name}.pdf"
            make_document_pdf(rendered, str(rel), _eml_lines(source), mono=False)
            merge_inputs.append(rendered)
            continue
        if suffix in {".txt", ".md", ".json"}:
            rendered = component_dir / f"{safe_name}.pdf"
            make_document_pdf(rendered, str(rel), _text_file_lines(source), mono=(suffix in {".txt", ".json"}))
            merge_inputs.append(rendered)
            continue

    index_pdf = component_dir / "_index.pdf"
    make_document_pdf(index_pdf, title, index_lines)
    _merge_pdfs(out_pdf, [index_pdf, *merge_inputs])


def _render_selected_sources(exhibit_dir: Path, out_pdf: Path, title: str, selected_relpaths: list[str]) -> None:
    component_dir = out_pdf.with_suffix("")
    component_dir.mkdir(parents=True, exist_ok=True)
    merge_inputs: list[Path] = []
    index_lines = [f"Curated source path: {exhibit_dir}", "", "Included items:"]

    for relpath in selected_relpaths:
        source = exhibit_dir / relpath
        if not source.exists():
            continue
        suffix = source.suffix.lower()
        safe_name = relpath.replace("/", "__").replace(" ", "_")
        index_lines.append(relpath)
        if suffix == ".pdf":
            merge_inputs.append(source)
            continue
        if suffix in {".png", ".jpg", ".jpeg"}:
            rendered = component_dir / f"{safe_name}.pdf"
            image_to_pdf(source, rendered, relpath)
            merge_inputs.append(rendered)
            continue
        if suffix == ".eml":
            rendered = component_dir / f"{safe_name}.pdf"
            make_document_pdf(rendered, relpath, _eml_lines(source), mono=False)
            merge_inputs.append(rendered)
            continue
        if suffix in {".txt", ".md", ".json"}:
            rendered = component_dir / f"{safe_name}.pdf"
            make_document_pdf(rendered, relpath, _text_file_lines(source), mono=(suffix in {".txt", ".json"}))
            merge_inputs.append(rendered)
            continue

    index_pdf = component_dir / "_index.pdf"
    make_document_pdf(index_pdf, title, index_lines)
    _merge_pdfs(out_pdf, [index_pdf, *merge_inputs])


def image_to_pdf(img_path: Path, pdf_path: Path, title: str) -> None:
    img = Image.open(img_path)
    width, height = letter
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.setFont("Times-Bold", 14)
    c.drawString(72, height - 50, title)
    max_w = width - 144
    max_h = height - 140
    iw, ih = img.size
    scale = min(max_w / iw, max_h / ih)
    dw, dh = iw * scale, ih * scale
    x = (width - dw) / 2
    y = 60
    c.drawImage(ImageReader(img), x, y, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
    c.save()


def prepare_exhibit_support(
    *,
    summary_path: Path = SUMMARY_PATH,
    packet_dirs: tuple[Path, ...] = (REDUCED_PACKET_DIR, FULL_PACKET_DIR),
    root_dir: Path = ROOT,
    support_config: dict[str, Any] | None = None,
) -> None:
    config = support_config or {}
    curated_sources = dict(config.get("curated_sources") or DEFAULT_COURTSTYLE_PACKET_CONFIG["curated_sources"])
    summary_sections_config = dict(config.get("summary_sections") or DEFAULT_COURTSTYLE_PACKET_CONFIG["summary_sections"])
    snippet_ids = [str(item) for item in list(config.get("r_snippet_ids") or DEFAULT_COURTSTYLE_PACKET_CONFIG["r_snippet_ids"])]
    r_intro = [str(item) for item in list(config.get("r_summary_intro_lines") or DEFAULT_COURTSTYLE_PACKET_CONFIG["r_summary_intro_lines"])]
    static_images = list(config.get("static_image_exhibits") or DEFAULT_COURTSTYLE_PACKET_CONFIG["static_image_exhibits"])

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    exhibits = {str(item["label"]): Path(item["path"]) for item in summary["recommended_exhibits"]}
    exhibit_meta = {str(item["label"]): item for item in summary["recommended_exhibits"]}

    for packet_dir in packet_dirs:
        for label, item in exhibit_meta.items():
            make_exhibit_cover(
                packet_dir / "rendered" / f"{label.replace(' ', '_')}_cover.pdf",
                label,
                item.get("title", label),
                item.get("use", ""),
            )

    for exhibit_label in ("Exhibit J", "Exhibit M", "Exhibit R"):
        exhibit_dir = exhibits.get(exhibit_label)
        if not exhibit_dir:
            continue
        short = exhibit_label.split()[-1]
        for packet_dir in packet_dirs:
            _render_folder_exhibit(
                exhibit_dir,
                packet_dir / "rendered" / f"Exhibit_{short}_expanded.pdf",
                f"Exhibit {short} Expanded Contents",
            )
            _render_selected_sources(
                exhibit_dir,
                packet_dir / "rendered" / f"Exhibit_{short}_curated.pdf",
                f"Exhibit {short} Curated Contents",
                [str(item) for item in list(curated_sources.get(exhibit_label) or [])],
            )

    j_sections = [(str(item.get("heading") or ""), [str(line) for line in list(item.get("lines") or [])]) for item in list(summary_sections_config.get("Exhibit J") or [])]
    m_sections = [(str(item.get("heading") or ""), [str(line) for line in list(item.get("lines") or [])]) for item in list(summary_sections_config.get("Exhibit M") or [])]
    if exhibits.get("Exhibit J"):
        j_sections.append(("Source path", [str(exhibits["Exhibit J"])]))
    if exhibits.get("Exhibit M"):
        m_sections.append(("Source path", [str(exhibits["Exhibit M"])]))

    r_lines = list(r_intro)
    exhibit_r = exhibits.get("Exhibit R")
    if exhibit_r:
        for seq_id in snippet_ids:
            header_path = exhibit_r / seq_id / "headers.txt"
            if header_path.exists():
                first_lines = [line.strip() for line in header_path.read_text(encoding="utf-8").splitlines() if line.strip()][:5]
                r_lines.append(" | ".join(first_lines))
    r_sections = [("Summary", r_lines)]
    if exhibit_r:
        r_sections.append(("Source path", [str(exhibit_r)]))

    for packet_dir in packet_dirs:
        make_summary_exhibit_pdf(packet_dir / "rendered" / "Exhibit_J_summary.pdf", "Exhibit J Summary", j_sections)
        make_summary_exhibit_pdf(packet_dir / "rendered" / "Exhibit_M_summary.pdf", "Exhibit M Summary", m_sections)
        make_summary_exhibit_pdf(packet_dir / "rendered" / "Exhibit_R_summary.pdf", "Exhibit R Summary", r_sections)
        for image_entry in static_images:
            source = _resolve_path(root_dir, str(image_entry.get("source") or ""))
            if not source.exists():
                continue
            output_name = str(image_entry.get("output_name") or "")
            if not output_name:
                continue
            image_to_pdf(
                source,
                packet_dir / "rendered" / output_name,
                str(image_entry.get("title") or source.name),
            )


def build_courtstyle_packet_from_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    config = _deep_update(deepcopy(DEFAULT_COURTSTYLE_PACKET_CONFIG), dict(payload))
    base_dir = config_path.parent

    root_dir = _resolve_path(base_dir, str(config.get("root_dir") or DEFAULT_COURTSTYLE_PACKET_CONFIG["root_dir"]))
    summary_path = _resolve_path(base_dir, str(config.get("summary_path") or DEFAULT_COURTSTYLE_PACKET_CONFIG["summary_path"]))
    complaint_md_path = _resolve_path(base_dir, str(config.get("complaint_md_path") or DEFAULT_COURTSTYLE_PACKET_CONFIG["complaint_md_path"]))
    full_packet_dir = _resolve_path(base_dir, str(config.get("full_packet_dir") or DEFAULT_COURTSTYLE_PACKET_CONFIG["full_packet_dir"]))
    reduced_packet_dir = _resolve_path(base_dir, str(config.get("reduced_packet_dir") or DEFAULT_COURTSTYLE_PACKET_CONFIG["reduced_packet_dir"]))
    complaint_output = full_packet_dir / str(config.get("complaint_output_relative") or "rendered/0001_complaint_courtstyle_v2.pdf")

    build_courtstyle_complaint(
        complaint_output,
        summary_path=summary_path,
        complaint_md_path=complaint_md_path,
        body_start_marker=str(config.get("body_start_marker") or "Plaintiffs allege as follows:"),
    )
    prepare_exhibit_support(
        summary_path=summary_path,
        packet_dirs=(reduced_packet_dir, full_packet_dir),
        root_dir=root_dir,
        support_config=config,
    )
    return {
        "config_path": str(config_path),
        "summary_path": str(summary_path),
        "complaint_md_path": str(complaint_md_path),
        "complaint_output": str(complaint_output),
        "full_packet_dir": str(full_packet_dir),
        "reduced_packet_dir": str(reduced_packet_dir),
    }


def build_default_courtstyle_packet() -> None:
    build_courtstyle_complaint(FULL_PACKET_DIR / "rendered" / "0001_complaint_courtstyle_v2.pdf")
    prepare_exhibit_support()


if __name__ == "__main__":
    build_default_courtstyle_packet()
