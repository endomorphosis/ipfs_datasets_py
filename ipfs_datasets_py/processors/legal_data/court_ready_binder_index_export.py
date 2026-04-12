#!/usr/bin/env python3
"""Legacy court-ready binder index renderer extracted from workspace scripts."""

import re
import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


SRC = Path("/home/barberb/HACC/workspace/evidence_binder_exhibit_and_cover_sheet_index_2026-04-09.md")
OUT = Path("/home/barberb/HACC/workspace/evidence_binder_exhibit_and_cover_sheet_index_court_ready_2026-04-09.pdf")

COURT_LINES = [
    "IN THE CIRCUIT COURT OF THE STATE OF OREGON",
    "FOR THE COUNTY OF CLACKAMAS",
    "PROBATE DEPARTMENT",
]
CASE_NO = "Case No. 26PR00641"
MATTER_LINES = [
    "In the Matter of:",
    "Jane Kay Cortez,",
    "Protected Person.",
]


def normalize_md(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    return text.strip()


def parse_backtick_block(text: str, heading: str) -> str:
    m = re.search(rf"`{re.escape(heading)}`\s+`([^`]+)`", text, re.S)
    return normalize_md(m.group(1)) if m else ""


def cover_metadata(cover_path: str, fallback: str) -> dict:
    if not cover_path:
        return {"title": fallback}
    path = Path(cover_path)
    if not path.exists():
        return {"title": fallback}
    text = path.read_text(errors="replace")
    title = parse_backtick_block(text, "SHORT TITLE") or fallback
    return {"title": title}


def parse_tables(lines):
    families = []
    current = None
    in_table = False
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("## "):
            current = {"title": normalize_md(line[3:]), "rows": []}
            families.append(current)
            in_table = False
            continue
        if current is None:
            continue
        if line.startswith("| Exhibit |"):
            in_table = True
            continue
        if in_table and re.match(r"^\|\s*---", line):
            continue
        if in_table and line.startswith("|"):
            links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", line)
            parts = [normalize_md(p) for p in line.strip().strip("|").split("|")]
            if len(parts) >= 4:
                exhibit, tab, cover, source = [p.strip() for p in parts[:4]]
                cover_path = links[1][1] if len(links) >= 2 else ""
                meta = cover_metadata(cover_path, exhibit)
                current["rows"].append(
                    {
                        "exhibit": exhibit,
                        "title": meta["title"],
                        "source": source,
                        "used_in": used_in_from_family(current["title"]),
                    }
                )
            continue
        if in_table and not line.strip():
            in_table = False
    return [f for f in families if f["rows"]]


def title_from_filename(filename: str, fallback: str) -> str:
    name = Path(filename).stem
    name = re.sub(r"(_cover_page|_tab_cover_page)$", "", name)
    name = name.replace("authority_exhibit_", "Authority Exhibit ")
    name = name.replace("exhibit_", "Exhibit ")
    name = name.replace("_", " ").strip()
    if not name:
        return fallback
    if name.lower().startswith("exhibit "):
        return name
    return fallback


def used_in_from_family(family: str) -> str:
    mapping = {
        "1. Shared Housing / State-Court Binder": "Eviction response / injunction filings",
        "2. Shared Motion / Probate / Sanctions Binder": "Probate / sanctions / threshold motions",
        "4. Housing Duty Appendix": "Housing-duty appendix support",
    }
    return mapping.get(family, "Supplemental or support appendix")


def draw_case_caption(c, top_y, width):
    left = 0.65 * inch
    right = width - 0.65 * inch
    split_x = width * 0.60
    c.setLineWidth(1)
    c.line(left, top_y, right, top_y)
    c.setFont("Times-Bold", 11)
    c.drawCentredString(width / 2, top_y - 0.18 * inch, COURT_LINES[0])
    c.setFont("Times-Roman", 11)
    c.drawCentredString(width / 2, top_y - 0.38 * inch, COURT_LINES[1])
    c.drawCentredString(width / 2, top_y - 0.56 * inch, COURT_LINES[2])
    c.line(left, top_y - 0.72 * inch, right, top_y - 0.72 * inch)
    c.line(split_x, top_y - 0.72 * inch, split_x, top_y - 1.58 * inch)
    c.drawString(left + 0.08 * inch, top_y - 0.98 * inch, "EXHIBIT VOLUME")
    line_y = top_y - 0.92 * inch
    for line in MATTER_LINES:
        c.drawString(split_x + 0.12 * inch, line_y, line)
        line_y -= 0.16 * inch
    c.drawString(split_x + 0.12 * inch, line_y - 0.04 * inch, CASE_NO)
    c.line(left, top_y - 1.58 * inch, right, top_y - 1.58 * inch)
    return top_y - 1.84 * inch


def wrap(text, width):
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [""]


def draw_footer(c, width, page_num, total_pages):
    c.setFont("Times-Roman", 10)
    c.drawString(0.75 * inch, 0.38 * inch, f"Evidence Binder Index | Page {page_num} of {total_pages}")


def build_pages(families):
    pages = []
    current = []
    line_count = 0
    max_lines = 36

    for family in families:
        family_header = [family["title"].upper()]
        row_blocks = []
        for row in family["rows"]:
            block = [
                ("bold", row["exhibit"]),
                ("plain", f"Title {row['title']}"),
                ("plain", f"Source {row['source']}"),
                ("plain", f"Use {row['used_in']}"),
                ("blank", ""),
            ]
            row_blocks.append(block)

        needed = 2 + sum(len(block) for block in row_blocks)
        if current and line_count + needed > max_lines:
            pages.append(current)
            current = []
            line_count = 0

        current.append(("section", family_header[0]))
        current.append(("blank", ""))
        line_count += 2

        for block in row_blocks:
            block_lines = []
            for style, text in block:
                if style == "blank":
                    block_lines.append((style, text))
                else:
                    widths = {"bold": 28, "plain": 88}
                    for part in wrap(text, widths[style]):
                        block_lines.append((style, part))
            if current and line_count + len(block_lines) > max_lines:
                pages.append(current)
                current = [("section", family["title"].upper()), ("blank", "")]
                line_count = 2
            current.extend(block_lines)
            line_count += len(block_lines)

    if current:
        pages.append(current)
    return pages


def build_default_court_ready_binder_index() -> Path:
    families = parse_tables(SRC.read_text(errors="replace").splitlines())
    pages = build_pages(families)

    c = canvas.Canvas(str(OUT), pagesize=letter)
    width, height = letter
    total_pages = len(pages)

    for page_num, page in enumerate(pages, start=1):
        if page_num > 1:
            c.showPage()
        y = draw_case_caption(c, height - 0.75 * inch, width)
        c.setFont("Times-Bold", 15)
        c.drawCentredString(width / 2, y, "EVIDENCE BINDER INDEX")
        c.setFont("Times-Bold", 11)
        c.drawCentredString(width / 2, y - 0.22 * inch, "EXHIBIT REGISTER")
        y -= 0.48 * inch

        left = 0.75 * inch
        c.setFont("Times-Bold", 11)
        c.drawString(left, y, "Exhibit")
        c.drawString(left + 1.1 * inch, y, "Description / Source / Use")
        y -= 0.12 * inch
        c.setLineWidth(0.8)
        c.line(left, y, width - left, y)
        y -= 0.18 * inch

        for style, text in page:
            if style == "section":
                c.setFont("Times-Bold", 12)
                c.drawString(left, y, text)
                y -= 0.22 * inch
                c.setLineWidth(0.6)
                c.line(left, y, width - left, y)
                y -= 0.2 * inch
            elif style == "bold":
                c.setFont("Times-Bold", 12)
                c.drawString(left, y, text)
                y -= 0.2 * inch
            elif style == "plain":
                c.setFont("Times-Roman", 12)
                c.drawString(left + 1.1 * inch, y, text)
                y -= 0.19 * inch
            else:
                y -= 0.09 * inch

        draw_footer(c, width, page_num, total_pages)

    c.save()
    print(OUT)
    return OUT


if __name__ == "__main__":
    build_default_court_ready_binder_index()
