"""Reusable helpers for exhibit-binder PDF assembly."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path
import shutil
import subprocess
from typing import Mapping, Optional, Sequence

from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from .court_pdf_rendering import (
    DEFAULT_EXHIBIT_CAPTION,
    ExhibitCaptionConfig,
    centered_header,
    draw_exhibit_caption,
    draw_footer,
    draw_labeled_block,
    parse_exhibit_cover_source,
    render_exhibit_cover_from_markdown,
    render_exhibit_tab_from_markdown,
    render_text_lines_pdf,
)

try:
    from PyPDF2 import PdfMerger
except Exception:  # pragma: no cover - dependency fallback
    try:
        from pypdf import PdfMerger  # type: ignore
    except Exception:  # pragma: no cover - dependency fallback
        PdfMerger = None  # type: ignore


def run_command(args: Sequence[str]) -> None:
    subprocess.run(list(args), check=True)


def slugify_exhibit_label(label: str) -> str:
    if label.startswith("Authority Exhibit "):
        text = label.replace("Authority Exhibit ", "authority_exhibit_")
        return text.replace("-", "_").replace(" ", "_").lower()
    text = label.replace("Exhibit ", "")
    return f"exhibit_{text.replace('-', '_').replace(' ', '_')}"


def family_slug(family: str) -> str:
    return family.lower().replace(" / ", "_").replace(" ", "_").replace("-", "_")


def render_binder_title_pdf(
    output_path: str | Path,
    *,
    lean_mode: bool,
    caption_config: ExhibitCaptionConfig = DEFAULT_EXHIBIT_CAPTION,
    submitted_by: str = "Filing Party, Pro Se",
) -> Path:
    output_path = Path(output_path)
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    left = 1.0 * inch
    y = draw_exhibit_caption(pdf, height - 0.95 * inch, config=caption_config)
    centered_header(pdf, y, "EVIDENCE BINDER", 18)
    y -= 0.35 * inch
    centered_header(pdf, y, "LODGED EXHIBIT VOLUME", 13)
    y -= 0.55 * inch
    pdf.setLineWidth(1)
    pdf.line(left, y, width - left, y)
    y -= 0.55 * inch

    blocks = [
        ("Document", ["Lodged exhibit volume for the above-captioned matter."]),
        ("Print Set", ["Deduplicated exhibit print set." if lean_mode else "Full exhibit print set."]),
        ("Submitted By", [submitted_by]),
        ("Contents", ["Exhibit schedule, divider pages, exhibit cover sheets, and underlying exhibit source pages."]),
    ]
    for label, lines in blocks:
        y = draw_labeled_block(pdf, left, y, width - (2 * left), label, lines)

    draw_footer(pdf, width, "Evidence Binder", 1, 1)
    pdf.save()
    return output_path


def render_family_divider_pdf(
    output_path: str | Path,
    family: str,
    labels: Sequence[str],
    *,
    caption_config: ExhibitCaptionConfig = DEFAULT_EXHIBIT_CAPTION,
) -> Path:
    output_path = Path(output_path)
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter
    left = 0.95 * inch
    y = draw_exhibit_caption(pdf, height - 0.95 * inch, config=caption_config)
    centered_header(pdf, y, "EXHIBIT SECTION", 14)
    y -= 0.45 * inch
    centered_header(pdf, y, family.upper(), 16)
    y -= 0.55 * inch
    pdf.setLineWidth(1)
    pdf.line(left, y, width - left, y)
    y -= 0.55 * inch
    draw_labeled_block(pdf, left, y, width - (2 * left), "Included Exhibits", [", ".join(labels)])
    draw_footer(pdf, width, family, 1, 1)
    pdf.save()
    return output_path


def convert_markdown_to_binder_pdf(
    md_path: str | Path,
    output_path: str | Path,
    *,
    generated_dir: Optional[str | Path] = None,
    caption_config: ExhibitCaptionConfig = DEFAULT_EXHIBIT_CAPTION,
    libreoffice_program: str = "libreoffice",
) -> Path:
    md_path = Path(md_path)
    output_path = Path(output_path)
    if md_path.name.endswith("_tab_cover_page.md"):
        return render_exhibit_tab_from_markdown(md_path, output_path, caption_config=caption_config)
    if md_path.name.endswith("_cover_page.md"):
        return render_exhibit_cover_from_markdown(md_path, output_path, caption_config=caption_config)

    out_dir = Path(generated_dir) if generated_dir is not None else output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_input = out_dir / f"{output_path.name}.md"
    shutil.copy2(md_path, temp_input)
    run_command(
        [
            libreoffice_program,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(temp_input),
        ]
    )
    produced = out_dir / f"{temp_input.stem}.pdf"
    if produced != output_path:
        produced.rename(output_path)
    temp_input.unlink(missing_ok=True)
    return output_path


def image_to_pdf(image_path: str | Path, output_path: str | Path) -> Path:
    image_path = Path(image_path)
    output_path = Path(output_path)
    image = Image.open(image_path)
    if image.mode in ("RGBA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.save(output_path, "PDF", resolution=150.0)
    return output_path


def markdown_or_text_to_pdf(source_path: str | Path, output_path: str | Path) -> Path:
    source_path = Path(source_path)
    output_path = Path(output_path)
    if source_path.suffix.lower() == ".md":
        return convert_markdown_to_binder_pdf(source_path, output_path, generated_dir=output_path.parent)
    render_text_lines_pdf(output_path, source_path.name, source_path.read_text(errors="replace").splitlines(), footer_label=source_path.stem)
    return output_path


def eml_to_pdf(source_path: str | Path, output_path: str | Path) -> Path:
    source_path = Path(source_path)
    output_path = Path(output_path)
    with source_path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    lines = [
        f"File: {source_path}",
        f"Subject: {message.get('subject', '')}",
        f"From: {message.get('from', '')}",
        f"To: {message.get('to', '')}",
        f"Cc: {message.get('cc', '')}",
        f"Date: {message.get('date', '')}",
        "",
        "Body:",
        "",
    ]
    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_content()
                    break
                except Exception:
                    continue
    else:
        try:
            body = message.get_content()
        except Exception:
            body = ""
    if not body:
        body = "[No plain-text body extracted. See original EML file.]"
    lines.extend(body.splitlines())
    render_text_lines_pdf(output_path, source_path.name, lines, footer_label=source_path.stem)
    return output_path


def note_pdf(output_path: str | Path, title: str, body_lines: Sequence[str]) -> Path:
    return render_text_lines_pdf(output_path, title, list(body_lines), footer_label=title)


def source_to_pdf(
    source: str,
    *,
    output_path: str | Path,
    label: str,
    family: str,
    lean_mode: bool = False,
    lean_replacements: Optional[Mapping[tuple[str, str], Sequence[str]]] = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if lean_mode and lean_replacements and (family, label) in lean_replacements:
        return note_pdf(output_path, f"{label} lean cross-reference", lean_replacements[(family, label)])
    if not source:
        return note_pdf(output_path, f"{label} source note", ["No source path was parsed from the exhibit cover page."])
    if source.startswith("Not yet obtained.") or source.startswith("Reserved:"):
        return note_pdf(
            output_path,
            f"{label} source note",
            [
                f"Exhibit label: {label}",
                f"Source description: {source}",
                "",
                "This exhibit is a placeholder or reserved demonstrative.",
                "No underlying source file is currently attached in the repository.",
                "Use the tab cover page and exhibit cover page to preserve the slot and limitation note.",
            ],
        )

    source_path = Path(source)
    if not source_path.exists():
        return note_pdf(
            output_path,
            f"{label} source note",
            [
                f"Exhibit label: {label}",
                f"Expected source: {source}",
                "",
                "The referenced source file was not found at build time.",
                "Use the exhibit cover page for the current source and limitation statement.",
            ],
        )
    if source_path.is_dir():
        sample = sorted([path.name for path in source_path.iterdir()])[:20]
        return note_pdf(
            output_path,
            f"{label} directory source note",
            [
                f"Exhibit label: {label}",
                f"Directory source: {source}",
                "",
                "This exhibit source is a directory rather than a single file.",
                "Representative contents:",
                *sample,
            ],
        )

    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        shutil.copy2(source_path, output_path)
        return output_path
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}:
        return image_to_pdf(source_path, output_path)
    if suffix in {".md", ".txt"}:
        return markdown_or_text_to_pdf(source_path, output_path)
    if suffix == ".eml":
        return eml_to_pdf(source_path, output_path)
    return note_pdf(
        output_path,
        f"{label} source note",
        [
            f"Exhibit label: {label}",
            f"Source path: {source}",
            f"Source file type: {suffix or 'unknown'}",
            "",
            "No specialized renderer was configured for this source type.",
            "Use the original file path from the exhibit cover page.",
        ],
    )


def _merge_pdfs_python(output_path: Path, pdf_paths: Sequence[str | Path]) -> Path:
    if PdfMerger is None:
        raise RuntimeError("Python PDF merger is unavailable")
    merger = PdfMerger()
    try:
        for path in pdf_paths:
            merger.append(str(Path(path)))
        with output_path.open("wb") as handle:
            merger.write(handle)
    finally:
        merger.close()
    return output_path


def merge_pdfs(
    output_path: str | Path,
    pdf_paths: Sequence[str | Path],
    *,
    program: str = "pdfunite",
    engine: str = "auto",
) -> Path:
    output_path = Path(output_path)
    if engine not in {"auto", "python", "pdfunite"}:
        raise ValueError(f"Unsupported merge engine: {engine}")
    if engine in {"auto", "python"}:
        try:
            return _merge_pdfs_python(output_path, pdf_paths)
        except Exception:
            if engine == "python":
                raise
    run_command([program, *(str(Path(path)) for path in pdf_paths), str(output_path)])
    return output_path


def pdf_page_count(pdf_path: str | Path, *, program: str = "pdfinfo") -> int:
    pdf_path = Path(pdf_path)
    result = subprocess.run(
        [program, str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"Could not determine page count for {pdf_path}")


def build_exhibit_binder(
    *,
    front_pdf: str | Path,
    packet_pdfs: Sequence[str | Path],
    output_pdf: str | Path,
    table_pdf: str | Path | None = None,
) -> Path:
    ordered_inputs = [Path(front_pdf)]
    if table_pdf is not None:
        ordered_inputs.append(Path(table_pdf))
    ordered_inputs.extend(Path(path) for path in packet_pdfs)
    return merge_pdfs(output_pdf, ordered_inputs, engine="auto")


__all__ = [
    "convert_markdown_to_binder_pdf",
    "build_exhibit_binder",
    "eml_to_pdf",
    "family_slug",
    "image_to_pdf",
    "markdown_or_text_to_pdf",
    "merge_pdfs",
    "note_pdf",
    "parse_exhibit_cover_source",
    "pdf_page_count",
    "render_binder_title_pdf",
    "render_family_divider_pdf",
    "run_command",
    "slugify_exhibit_label",
    "source_to_pdf",
]
