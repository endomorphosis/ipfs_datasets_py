#!/usr/bin/env python3
"""Reusable court-ready binder index renderer."""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


DEFAULT_SRC = Path("/home/barberb/HACC/workspace/evidence_binder_exhibit_and_cover_sheet_index_2026-04-09.md")
DEFAULT_OUT = Path("/home/barberb/HACC/workspace/evidence_binder_exhibit_and_cover_sheet_index_court_ready_2026-04-09.pdf")
DEFAULT_COURT_LINES = [
    "IN THE CIRCUIT COURT OF THE STATE OF OREGON",
    "FOR THE COUNTY OF CLACKAMAS",
    "PROBATE DEPARTMENT",
]
DEFAULT_CASE_NO = "Case No. 26PR00641"
DEFAULT_MATTER_LINES = ["In the Matter of:", "Jane Kay Cortez,", "Protected Person."]
DEFAULT_USED_IN_MAP = {
    "1. Shared Housing / State-Court Binder": "Eviction response / injunction filings",
    "2. Shared Motion / Probate / Sanctions Binder": "Probate / sanctions / threshold motions",
    "4. Housing Duty Appendix": "Housing-duty appendix support",
}


def normalize_md(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    return text.strip()


def parse_backtick_block(text: str, heading: str) -> str:
    match = re.search(rf"`{re.escape(heading)}`\s+`([^`]+)`", text, re.S)
    return normalize_md(match.group(1)) if match else ""


def cover_metadata(cover_path: str, fallback: str) -> dict[str, str]:
    if not cover_path:
        return {"title": fallback}
    path = Path(cover_path)
    if not path.exists():
        return {"title": fallback}
    text = path.read_text(errors="replace")
    title = parse_backtick_block(text, "SHORT TITLE") or fallback
    return {"title": title}


def parse_tables(lines: list[str], *, used_in_map: dict[str, str], used_in_default: str) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
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
            parts = [normalize_md(part) for part in line.strip().strip("|").split("|")]
            if len(parts) >= 4:
                exhibit = parts[0].strip()
                cover_path = links[1][1] if len(links) >= 2 else ""
                meta = cover_metadata(cover_path, exhibit)
                current["rows"].append(
                    {
                        "exhibit": exhibit,
                        "title": meta["title"],
                        "source": parts[3].strip(),
                        "used_in": used_in_map.get(current["title"], used_in_default),
                    }
                )
            continue
        if in_table and not line.strip():
            in_table = False
    return [family for family in families if family["rows"]]


def draw_case_caption(c: canvas.Canvas, top_y: float, width: float, *, court_lines: list[str], case_no: str, matter_lines: list[str]) -> float:
    left = 0.65 * inch
    right = width - 0.65 * inch
    split_x = width * 0.60
    c.setLineWidth(1)
    c.line(left, top_y, right, top_y)
    c.setFont("Times-Bold", 11)
    c.drawCentredString(width / 2, top_y - 0.18 * inch, court_lines[0])
    c.setFont("Times-Roman", 11)
    c.drawCentredString(width / 2, top_y - 0.38 * inch, court_lines[1])
    c.drawCentredString(width / 2, top_y - 0.56 * inch, court_lines[2])
    c.line(left, top_y - 0.72 * inch, right, top_y - 0.72 * inch)
    c.line(split_x, top_y - 0.72 * inch, split_x, top_y - 1.58 * inch)
    c.drawString(left + 0.08 * inch, top_y - 0.98 * inch, "EXHIBIT VOLUME")
    line_y = top_y - 0.92 * inch
    for line in matter_lines:
        c.drawString(split_x + 0.12 * inch, line_y, line)
        line_y -= 0.16 * inch
    c.drawString(split_x + 0.12 * inch, line_y - 0.04 * inch, case_no)
    c.line(left, top_y - 1.58 * inch, right, top_y - 1.58 * inch)
    return top_y - 1.84 * inch


def wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [""]


def draw_footer(c: canvas.Canvas, page_num: int, total_pages: int, *, footer_label: str) -> None:
    c.setFont("Times-Roman", 10)
    c.drawString(0.75 * inch, 0.38 * inch, f"{footer_label} | Page {page_num} of {total_pages}")


def build_pages(families: list[dict[str, Any]], *, max_lines: int) -> list[list[tuple[str, str]]]:
    pages: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    line_count = 0

    for family in families:
        row_blocks = []
        for row in family["rows"]:
            row_blocks.append(
                [
                    ("bold", row["exhibit"]),
                    ("plain", f"Title {row['title']}"),
                    ("plain", f"Source {row['source']}"),
                    ("plain", f"Use {row['used_in']}"),
                    ("blank", ""),
                ]
            )

        needed = 2 + sum(len(block) for block in row_blocks)
        if current and line_count + needed > max_lines:
            pages.append(current)
            current = []
            line_count = 0

        current.extend([("section", family["title"].upper()), ("blank", "")])
        line_count += 2

        for block in row_blocks:
            block_lines: list[tuple[str, str]] = []
            for style, text in block:
                if style == "blank":
                    block_lines.append((style, text))
                else:
                    width = 28 if style == "bold" else 88
                    block_lines.extend((style, part) for part in wrap(text, width))
            if current and line_count + len(block_lines) > max_lines:
                pages.append(current)
                current = [("section", family["title"].upper()), ("blank", "")]
                line_count = 2
            current.extend(block_lines)
            line_count += len(block_lines)

    if current:
        pages.append(current)
    return pages


def build_court_ready_binder_index(
    *,
    src_path: str | Path,
    out_path: str | Path,
    court_lines: list[str] | None = None,
    case_no: str = DEFAULT_CASE_NO,
    matter_lines: list[str] | None = None,
    used_in_map: dict[str, str] | None = None,
    used_in_default: str = "Supplemental or support appendix",
    document_title: str = "EVIDENCE BINDER INDEX",
    document_subtitle: str = "EXHIBIT REGISTER",
    footer_label: str = "Evidence Binder Index",
    max_lines_per_page: int = 36,
) -> Path:
    src = Path(src_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    families = parse_tables(
        src.read_text(errors="replace").splitlines(),
        used_in_map=(used_in_map or DEFAULT_USED_IN_MAP),
        used_in_default=used_in_default,
    )
    pages = build_pages(families, max_lines=max_lines_per_page)

    court_lines = list(court_lines or DEFAULT_COURT_LINES)
    if len(court_lines) < 3:
        court_lines.extend([""] * (3 - len(court_lines)))
    matter_lines = list(matter_lines or DEFAULT_MATTER_LINES)

    c = canvas.Canvas(str(out), pagesize=letter)
    width, height = letter
    total_pages = len(pages)

    for page_num, page in enumerate(pages, start=1):
        if page_num > 1:
            c.showPage()
        y = draw_case_caption(c, height - 0.75 * inch, width, court_lines=court_lines, case_no=case_no, matter_lines=matter_lines)
        c.setFont("Times-Bold", 15)
        c.drawCentredString(width / 2, y, document_title)
        c.setFont("Times-Bold", 11)
        c.drawCentredString(width / 2, y - 0.22 * inch, document_subtitle)
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

        draw_footer(c, page_num, total_pages, footer_label=footer_label)

    c.save()
    return out


def build_court_ready_binder_index_from_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    src_value = str(payload.get("src_path") or "")
    out_value = str(payload.get("out_path") or "")
    if not src_value or not out_value:
        raise ValueError("config must include 'src_path' and 'out_path'")

    src = (base_dir / src_value) if not Path(src_value).is_absolute() else Path(src_value)
    out = (base_dir / out_value) if not Path(out_value).is_absolute() else Path(out_value)

    output = build_court_ready_binder_index(
        src_path=src,
        out_path=out,
        court_lines=[str(item) for item in list(payload.get("court_lines") or DEFAULT_COURT_LINES)],
        case_no=str(payload.get("case_no") or DEFAULT_CASE_NO),
        matter_lines=[str(item) for item in list(payload.get("matter_lines") or DEFAULT_MATTER_LINES)],
        used_in_map={str(key): str(value) for key, value in dict(payload.get("used_in_map") or DEFAULT_USED_IN_MAP).items()},
        used_in_default=str(payload.get("used_in_default") or "Supplemental or support appendix"),
        document_title=str(payload.get("document_title") or "EVIDENCE BINDER INDEX"),
        document_subtitle=str(payload.get("document_subtitle") or "EXHIBIT REGISTER"),
        footer_label=str(payload.get("footer_label") or "Evidence Binder Index"),
        max_lines_per_page=int(payload.get("max_lines_per_page") or 36),
    )
    return {
        "config_path": str(config_path),
        "output_path": str(output),
    }


def build_default_court_ready_binder_index() -> Path:
    return build_court_ready_binder_index(
        src_path=DEFAULT_SRC,
        out_path=DEFAULT_OUT,
        court_lines=DEFAULT_COURT_LINES,
        case_no=DEFAULT_CASE_NO,
        matter_lines=DEFAULT_MATTER_LINES,
        used_in_map=DEFAULT_USED_IN_MAP,
    )


if __name__ == "__main__":
    print(build_default_court_ready_binder_index())
