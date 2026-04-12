"""Reusable official-form draft renderer for JS-44 and AO-440."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


DEFAULT_ROOT = Path("/home/barberb/HACC/workspace")
DEFAULT_FORMS_DIR = DEFAULT_ROOT / "official-forms"
DEFAULT_PREVIEW_DIR = DEFAULT_ROOT / "render-previews"
DEFAULT_OUT_DIR = DEFAULT_FORMS_DIR / "draft-filled"

SCALE_X = 612 / 918
SCALE_Y = 792 / 1188

DEFAULT_JS44_PAYLOAD = {
    "output_name": "js44-draft-filled.pdf",
    "plaintiffs_lines": ["Benjamin Jay Barber, Jane Kay Cortez,", "and Julio Regal Florez-Cortez"],
    "defendants_lines": ["Housing Authority of Clackamas County", "and Quantum Residential"],
    "county_left": "Clackamas",
    "county_right": "Clackamas",
    "filer_lines": ["Benjamin Jay Barber, pro se", "10043 SE 32nd Ave", "Milwaukie, OR 97222"],
    "causes_line_1": "42 U.S.C. §§ 3601-3619; 29 U.S.C. § 794; 42 U.S.C. §§ 12131-12134; 42 U.S.C. §§ 1981, 1983",
    "causes_line_2": "Housing discrimination, retaliation, disability-accommodation denial, and race-based",
    "causes_line_3": "interference with housing-contracting rights.",
    "relief_text": "injunctive relief and damages",
    "date_text": "03/31/2026",
    "signature_text": "Benjamin Jay Barber",
}

DEFAULT_SUMMONS_PAYLOADS = [
    {
        "output_name": "ao440-hacc-draft-filled.pdf",
        "defendant_lines": ["Housing Authority of Clackamas County"],
        "to_lines": ["Housing Authority of Clackamas County", "13930 Gain Street", "Oregon City, OR 97045"],
        "state_text": "Oregon",
        "plaintiffs_lines": ["Benjamin Jay Barber, Jane Kay Cortez,", "and Julio Regal Florez-Cortez"],
        "filer_lines": ["Benjamin Jay Barber, pro se", "10043 SE 32nd Ave", "Milwaukie, OR 97222"],
    },
    {
        "output_name": "ao440-quantum-draft-filled.pdf",
        "defendant_lines": ["Quantum Residential"],
        "to_lines": ["Quantum Residential", "601 E 16th St", "Vancouver, WA 98663"],
        "state_text": "Oregon",
        "plaintiffs_lines": ["Benjamin Jay Barber, Jane Kay Cortez,", "and Julio Regal Florez-Cortez"],
        "filer_lines": ["Benjamin Jay Barber, pro se", "10043 SE 32nd Ave", "Milwaukie, OR 97222"],
    },
]


def sx(x: float) -> float:
    return x * SCALE_X


def sy(top: float) -> float:
    return 792 - (top * SCALE_Y)


def ensure_page_png(*, pdf: Path, stem: str, page: int, preview_dir: Path) -> Path:
    out = preview_dir / f"{stem}-p{page}.png"
    if not out.exists():
        preview_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pdftoppm", "-png", "-f", str(page), "-singlefile", str(pdf), str(out.with_suffix(""))],
            check=True,
        )
    return out


def draw_background(c: canvas.Canvas, image_path: Path) -> None:
    c.drawImage(ImageReader(str(image_path)), 0, 0, width=612, height=792)


def draw_multiline(c: canvas.Canvas, x: float, y: float, lines: list[str], *, font: str = "Times-Roman", size: int = 10) -> None:
    text = c.beginText(x, y)
    text.setFont(font, size)
    for line in lines:
        text.textLine(line)
    c.drawText(text)


def draw_x(c: canvas.Canvas, x: float, y: float, *, size: int = 12) -> None:
    c.setFont("Helvetica-Bold", size)
    c.drawString(x, y, "X")


def build_js44(*, forms_dir: Path, preview_dir: Path, out_dir: Path, payload: dict[str, Any]) -> Path:
    page1 = ensure_page_png(pdf=forms_dir / "js44.pdf", stem="js44-page1-bg", page=1, preview_dir=preview_dir)
    page2 = ensure_page_png(pdf=forms_dir / "js44.pdf", stem="js44-page2-bg", page=2, preview_dir=preview_dir)
    out = out_dir / str(payload.get("output_name") or "js44-draft-filled.pdf")

    c = canvas.Canvas(str(out), pagesize=letter)
    draw_background(c, page1)

    draw_multiline(c, sx(44), sy(118), [str(item) for item in list(payload.get("plaintiffs_lines") or [])], size=10)
    draw_multiline(c, sx(488), sy(118), [str(item) for item in list(payload.get("defendants_lines") or [])], size=10)
    c.setFont("Times-Roman", 10)
    c.drawString(sx(92), sy(176), str(payload.get("county_left") or ""))
    c.drawString(sx(520), sy(176), str(payload.get("county_right") or ""))
    draw_multiline(c, sx(71), sy(236), [str(item) for item in list(payload.get("filer_lines") or [])], size=10)

    draw_x(c, sx(186), sy(318), size=12)
    draw_x(c, sx(182), sy(752), size=12)
    draw_x(c, sx(24), sy(897), size=12)

    c.setFont("Times-Roman", 8.2)
    c.drawString(sx(204), sy(946), str(payload.get("causes_line_1") or ""))
    c.drawString(sx(204), sy(972), str(payload.get("causes_line_2") or ""))
    c.drawString(sx(204), sy(986), str(payload.get("causes_line_3") or ""))
    c.drawString(sx(518), sy(994), str(payload.get("relief_text") or ""))
    draw_x(c, sx(760), sy(1018), size=12)
    c.setFont("Times-Roman", 9)
    c.drawString(sx(64), sy(1084), str(payload.get("date_text") or ""))
    c.drawString(sx(352), sy(1084), str(payload.get("signature_text") or ""))

    c.showPage()
    draw_background(c, page2)
    c.save()
    return out


def build_summons(*, forms_dir: Path, preview_dir: Path, out_dir: Path, payload: dict[str, Any]) -> Path:
    page1 = ensure_page_png(pdf=forms_dir / "ao440.pdf", stem="ao440-page1-bg", page=1, preview_dir=preview_dir)
    page2 = ensure_page_png(pdf=forms_dir / "ao440.pdf", stem="ao440-page2-bg", page=2, preview_dir=preview_dir)
    out = out_dir / str(payload.get("output_name") or "ao440-draft-filled.pdf")

    c = canvas.Canvas(str(out), pagesize=letter)
    draw_background(c, page1)
    c.setFont("Times-Roman", 12)
    c.drawString(sx(422), sy(165), str(payload.get("state_text") or ""))
    draw_multiline(c, sx(66), sy(205), [str(item) for item in list(payload.get("plaintiffs_lines") or [])], size=10)
    draw_multiline(c, sx(66), sy(382), [str(item) for item in list(payload.get("defendant_lines") or [])], size=10)
    draw_multiline(c, sx(86), sy(520), [str(item) for item in list(payload.get("to_lines") or [])], size=9.5)
    draw_multiline(c, sx(59), sy(774), [str(item) for item in list(payload.get("filer_lines") or [])], size=9.2)

    c.showPage()
    draw_background(c, page2)
    c.save()
    return out


def build_official_form_drafts(
    *,
    forms_dir: str | Path,
    preview_dir: str | Path,
    out_dir: str | Path,
    js44_payload: dict[str, Any],
    summons_payloads: list[dict[str, Any]],
) -> list[Path]:
    forms_path = Path(forms_dir)
    preview_path = Path(preview_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = [build_js44(forms_dir=forms_path, preview_dir=preview_path, out_dir=out_path, payload=js44_payload)]
    for payload in summons_payloads:
        outputs.append(build_summons(forms_dir=forms_path, preview_dir=preview_path, out_dir=out_path, payload=payload))
    return outputs


def build_official_form_drafts_from_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    forms_dir_value = str(payload.get("forms_dir") or "official-forms")
    preview_dir_value = str(payload.get("preview_dir") or "render-previews")
    out_dir_value = str(payload.get("out_dir") or "official-forms/draft-filled")

    forms_dir = (base_dir / forms_dir_value) if not Path(forms_dir_value).is_absolute() else Path(forms_dir_value)
    preview_dir = (base_dir / preview_dir_value) if not Path(preview_dir_value).is_absolute() else Path(preview_dir_value)
    out_dir = (base_dir / out_dir_value) if not Path(out_dir_value).is_absolute() else Path(out_dir_value)

    outputs = build_official_form_drafts(
        forms_dir=forms_dir,
        preview_dir=preview_dir,
        out_dir=out_dir,
        js44_payload=dict(payload.get("js44") or DEFAULT_JS44_PAYLOAD),
        summons_payloads=[dict(item) for item in list(payload.get("summons") or DEFAULT_SUMMONS_PAYLOADS)],
    )
    return {
        "config_path": str(config_path),
        "output_paths": [str(item) for item in outputs],
        "output_count": len(outputs),
    }


def build_default_official_form_drafts() -> list[Path]:
    return build_official_form_drafts(
        forms_dir=DEFAULT_FORMS_DIR,
        preview_dir=DEFAULT_PREVIEW_DIR,
        out_dir=DEFAULT_OUT_DIR,
        js44_payload=DEFAULT_JS44_PAYLOAD,
        summons_payloads=DEFAULT_SUMMONS_PAYLOADS,
    )


if __name__ == "__main__":
    for item in build_default_official_form_drafts():
        print(item)
