"""Legacy official form draft renderer extracted from workspace scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path("/home/barberb/HACC/workspace")
FORMS_DIR = ROOT / "official-forms"
PREVIEW_DIR = ROOT / "render-previews"
OUT_DIR = ROOT / "official-forms" / "draft-filled"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCALE_X = 612 / 918
SCALE_Y = 792 / 1188


def sx(x: float) -> float:
    return x * SCALE_X


def sy(top: float) -> float:
    return 792 - (top * SCALE_Y)


def ensure_page_png(pdf: Path, stem: str, page: int) -> Path:
    out = PREVIEW_DIR / f"{stem}-p{page}.png"
    if not out.exists():
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-f",
                str(page),
                "-singlefile",
                str(pdf),
                str(out.with_suffix("")),
            ],
            check=True,
        )
    return out


def draw_background(c: canvas.Canvas, image_path: Path) -> None:
    c.drawImage(ImageReader(str(image_path)), 0, 0, width=612, height=792)


def draw_multiline(c: canvas.Canvas, x: float, y: float, lines: list[str], font: str = "Times-Roman", size: int = 10, leading: int = 12) -> None:
    text = c.beginText(x, y)
    text.setFont(font, size)
    for line in lines:
        text.textLine(line)
    c.drawText(text)


def draw_x(c: canvas.Canvas, x: float, y: float, size: int = 12) -> None:
    c.setFont("Helvetica-Bold", size)
    c.drawString(x, y, "X")


def build_js44() -> Path:
    page1 = ensure_page_png(FORMS_DIR / "js44.pdf", "js44-page1-bg", 1)
    page2 = ensure_page_png(FORMS_DIR / "js44.pdf", "js44-page2-bg", 2)
    out = OUT_DIR / "js44-draft-filled.pdf"

    c = canvas.Canvas(str(out), pagesize=letter)
    draw_background(c, page1)

    draw_multiline(
        c,
        sx(44),
        sy(118),
        [
            "Benjamin Jay Barber, Jane Kay Cortez,",
            "and Julio Regal Florez-Cortez",
        ],
        size=10,
    )
    draw_multiline(
        c,
        sx(488),
        sy(118),
        [
            "Housing Authority of Clackamas County",
            "and Quantum Residential",
        ],
        size=10,
    )
    c.setFont("Times-Roman", 10)
    c.drawString(sx(92), sy(176), "Clackamas")
    c.drawString(sx(520), sy(176), "Clackamas")
    draw_multiline(
        c,
        sx(71),
        sy(236),
        [
            "Benjamin Jay Barber, pro se",
            "10043 SE 32nd Ave",
            "Milwaukie, OR 97222",
        ],
        size=10,
    )

    draw_x(c, sx(186), sy(318), 12)  # federal question
    draw_x(c, sx(182), sy(752), 12)  # 443 housing/accommodations
    draw_x(c, sx(24), sy(897), 12)   # origin 1

    c.setFont("Times-Roman", 8.2)
    c.drawString(sx(204), sy(946), "42 U.S.C. §§ 3601-3619; 29 U.S.C. § 794; 42 U.S.C. §§ 12131-12134; 42 U.S.C. §§ 1981, 1983")
    c.drawString(sx(204), sy(972), "Housing discrimination, retaliation, disability-accommodation denial, and race-based")
    c.drawString(sx(204), sy(986), "interference with housing-contracting rights.")
    c.drawString(sx(518), sy(994), "injunctive relief and damages")
    draw_x(c, sx(760), sy(1018), 12)  # jury yes
    c.setFont("Times-Roman", 9)
    c.drawString(sx(64), sy(1084), "03/31/2026")
    c.drawString(sx(352), sy(1084), "Benjamin Jay Barber")

    c.showPage()
    draw_background(c, page2)
    c.save()
    return out


def build_summons(filename: str, defendant_lines: list[str], to_lines: list[str]) -> Path:
    page1 = ensure_page_png(FORMS_DIR / "ao440.pdf", "ao440-page1-bg", 1)
    page2 = ensure_page_png(FORMS_DIR / "ao440.pdf", "ao440-page2-bg", 2)
    out = OUT_DIR / filename
    c = canvas.Canvas(str(out), pagesize=letter)

    draw_background(c, page1)
    c.setFont("Times-Roman", 12)
    c.drawString(sx(422), sy(165), "Oregon")
    draw_multiline(
        c,
        sx(66),
        sy(205),
        [
            "Benjamin Jay Barber, Jane Kay Cortez,",
            "and Julio Regal Florez-Cortez",
        ],
        size=10,
        leading=12,
    )
    draw_multiline(c, sx(66), sy(382), defendant_lines, size=10, leading=12)
    draw_multiline(c, sx(86), sy(520), to_lines, size=9.5, leading=11)
    draw_multiline(
        c,
        sx(59),
        sy(774),
        [
            "Benjamin Jay Barber, pro se",
            "10043 SE 32nd Ave",
            "Milwaukie, OR 97222",
        ],
        size=9.2,
        leading=11,
    )

    c.showPage()
    draw_background(c, page2)
    c.save()
    return out


def build_default_official_form_drafts() -> list[Path]:
    outputs = []
    outputs.append(build_js44())
    outputs.append(build_summons(
        "ao440-hacc-draft-filled.pdf",
        ["Housing Authority of Clackamas County"],
        [
            "Housing Authority of Clackamas County",
            "13930 Gain Street",
            "Oregon City, OR 97045",
        ],
    ))
    outputs.append(build_summons(
        "ao440-quantum-draft-filled.pdf",
        ["Quantum Residential"],
        [
            "Quantum Residential",
            "601 E 16th St",
            "Vancouver, WA 98663",
        ],
    ))
    return outputs


if __name__ == "__main__":
    build_default_official_form_drafts()
