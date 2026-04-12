"""Manifest-driven builder for multi-family evidence binders."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from .exhibit_binder_export import (
    convert_markdown_to_binder_pdf,
    family_slug,
    merge_pdfs,
    parse_exhibit_cover_source,
    render_binder_title_pdf,
    render_family_divider_pdf,
    slugify_exhibit_label,
    source_to_pdf,
)
from .court_pdf_rendering import DEFAULT_EXHIBIT_CAPTION, ExhibitCaptionConfig
from .legal_pdf_manifest import load_json_manifest


def _resolve_path(base_dir: Path, value: str | Path | None) -> Path:
    text = str(value or "").strip()
    if not text:
        return base_dir
    path = Path(text)
    return path if path.is_absolute() else (base_dir / path)


def _normalize_lean_replacements(payload: Mapping[str, Any]) -> dict[tuple[str, str], list[str]]:
    normalized: dict[tuple[str, str], list[str]] = {}
    for item in list(payload.get("lean_replacements") or []):
        if not isinstance(item, Mapping):
            continue
        family = str(item.get("family") or "").strip()
        label = str(item.get("label") or "").strip()
        lines = [str(line) for line in list(item.get("lines") or [])]
        if family and label and lines:
            normalized[(family, label)] = lines
    return normalized


def _render_manifest_lines(manifest_lines: Sequence[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")


def _find_cover_paths(exhibit_covers_root: Path, family_payload: Mapping[str, Any], label: str) -> tuple[Path, Path]:
    slug = slugify_exhibit_label(label)
    tab_paths: list[Path] = []
    cover_paths: list[Path] = []
    for cover_dir in list(family_payload.get("cover_dirs") or []):
        directory = exhibit_covers_root / str(cover_dir)
        candidate_tab = directory / f"{slug}_tab_cover_page.md"
        candidate_cover = directory / f"{slug}_cover_page.md"
        if candidate_tab.exists():
            tab_paths.append(candidate_tab)
        if candidate_cover.exists():
            cover_paths.append(candidate_cover)
    if len(tab_paths) != 1 or len(cover_paths) != 1:
        raise FileNotFoundError(
            f"Could not uniquely locate cover pages for {label}: {tab_paths} / {cover_paths}"
        )
    return tab_paths[0], cover_paths[0]


def _run_index_command(base_dir: Path, payload: Mapping[str, Any]) -> None:
    command = list(payload.get("index_command") or [])
    if not command:
        return
    resolved_command = [str(_resolve_path(base_dir, item)) if index == 1 and str(command[0]).endswith("python") else str(item) for index, item in enumerate(command)]
    subprocess.run(resolved_command, check=True, cwd=str(base_dir))


def _caption_config_from_manifest(payload: Mapping[str, Any]) -> ExhibitCaptionConfig:
    data = dict(payload.get("caption_config") or {})
    default = DEFAULT_EXHIBIT_CAPTION
    court_lines = [str(item) for item in list(data.get("court_lines") or list(default.court_lines))]
    if not court_lines:
        court_lines = list(default.court_lines)
    return ExhibitCaptionConfig(
        court_lines=tuple(court_lines),
        case_number=str(data.get("case_number") or default.case_number),
        right_block_lines=tuple(str(item) for item in list(data.get("right_block_lines") or list(default.right_block_lines))),
        left_block_label=str(data.get("left_block_label") or default.left_block_label),
    )


def build_full_evidence_binder_from_manifest(path: str | Path, *, lean_mode: bool = False) -> dict[str, Any]:
    manifest_path = Path(path)
    payload = load_json_manifest(manifest_path)
    base_dir = manifest_path.parent

    exhibit_covers_root = _resolve_path(base_dir, payload.get("exhibit_covers_root") or "")
    working_dir = _resolve_path(base_dir, payload.get("working_dir") or "build")
    generated_dir = _resolve_path(base_dir, payload.get("generated_dir") or (working_dir / "generated_pdfs"))
    manifest_output = _resolve_path(base_dir, payload.get("build_manifest_output") or (working_dir / "manifest.txt"))
    output_pdf = _resolve_path(
        base_dir,
        payload.get("lean_output_pdf") if lean_mode and payload.get("lean_output_pdf") else payload.get("output_pdf") or "binder.pdf",
    )

    if working_dir.exists():
        shutil.rmtree(working_dir)
    generated_dir.mkdir(parents=True, exist_ok=True)

    lean_replacements = _normalize_lean_replacements(payload)
    caption_config = _caption_config_from_manifest(payload)
    merged_inputs: list[str] = []
    family_inputs: dict[str, list[str]] = {}
    family_output_paths: dict[str, str] = {}
    manifest_lines: list[str] = [f"lean_mode={lean_mode}", ""]

    title_pdf = generated_dir / "binder_title_page.pdf"
    render_binder_title_pdf(
        title_pdf,
        lean_mode=lean_mode,
        caption_config=caption_config,
        submitted_by=str(payload.get("submitted_by") or "Filing Party, Pro Se"),
    )
    merged_inputs.append(str(title_pdf))
    manifest_lines.extend(["## Binder Front Matter", f"- title: {title_pdf}"])

    _run_index_command(base_dir, payload)
    index_pdf_value = str(payload.get("index_pdf") or "").strip()
    if index_pdf_value:
        index_pdf = _resolve_path(base_dir, index_pdf_value)
        if index_pdf.exists():
            merged_inputs.append(str(index_pdf))
            manifest_lines.append(f"- index: {index_pdf}")

    for family_payload in list(payload.get("families") or []):
        if not isinstance(family_payload, Mapping):
            continue
        family_name = str(family_payload.get("name") or "").strip()
        if not family_name:
            continue
        labels = [str(label) for label in list(family_payload.get("labels") or []) if str(label).strip()]
        family_inputs[family_name] = []
        divider_pdf = generated_dir / f"{family_slug(family_name)}_divider_page.pdf"
        render_family_divider_pdf(divider_pdf, family_name, labels, caption_config=caption_config)
        merged_inputs.append(str(divider_pdf))
        family_inputs[family_name].append(str(divider_pdf))
        manifest_lines.append(f"## {family_name}")
        manifest_lines.append(f"- divider: {divider_pdf}")

        family_output_value = family_payload.get("lean_output_pdf") if lean_mode and family_payload.get("lean_output_pdf") else family_payload.get("output_pdf")
        if family_output_value:
            family_output_paths[family_name] = str(_resolve_path(base_dir, family_output_value))

        for label in labels:
            tab_md, cover_md = _find_cover_paths(exhibit_covers_root, family_payload, label)
            slug = f"{family_slug(family_name)}_{slugify_exhibit_label(label)}"
            tab_pdf = convert_markdown_to_binder_pdf(
                tab_md,
                generated_dir / f"{slug}_tab_cover_page.pdf",
                generated_dir=generated_dir,
                caption_config=caption_config,
            )
            cover_pdf = convert_markdown_to_binder_pdf(
                cover_md,
                generated_dir / f"{slug}_cover_page.pdf",
                generated_dir=generated_dir,
                caption_config=caption_config,
            )
            source = parse_exhibit_cover_source(cover_md)
            source_pdf = source_to_pdf(
                source,
                output_path=generated_dir / (f"{slug}_source.pdf" if source and not source.startswith(("Not yet obtained.", "Reserved:")) else f"{slug}_source_note.pdf"),
                label=label,
                family=family_name,
                lean_mode=lean_mode,
                lean_replacements=lean_replacements,
            )
            merged_inputs.extend([str(tab_pdf), str(cover_pdf), str(source_pdf)])
            family_inputs[family_name].extend([str(tab_pdf), str(cover_pdf), str(source_pdf)])
            manifest_lines.extend(
                [
                    f"- {label}",
                    f"  tab: {tab_pdf}",
                    f"  cover: {cover_pdf}",
                    f"  source: {source_pdf}",
                ]
            )

    _render_manifest_lines(manifest_lines, manifest_output)

    for family_name, paths in family_inputs.items():
        family_output = family_output_paths.get(family_name)
        if not family_output:
            continue
        family_output_path = Path(family_output)
        family_output_path.parent.mkdir(parents=True, exist_ok=True)
        family_output_path.unlink(missing_ok=True)
        merge_pdfs(family_output_path, paths)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_pdf.unlink(missing_ok=True)
    merge_pdfs(output_pdf, merged_inputs)
    return {
        "manifest_path": str(manifest_path),
        "working_dir": str(working_dir),
        "generated_dir": str(generated_dir),
        "build_manifest_output": str(manifest_output),
        "output_pdf": str(output_pdf),
        "family_outputs": family_output_paths,
        "family_count": len(family_inputs),
        "merged_input_count": len(merged_inputs),
        "lean_mode": lean_mode,
    }


__all__ = ["build_full_evidence_binder_from_manifest"]
