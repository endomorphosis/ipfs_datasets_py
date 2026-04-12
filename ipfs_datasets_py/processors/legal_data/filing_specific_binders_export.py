"""Reusable filing-specific exhibit binder merger."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/home/barberb/HACC/workspace/exhibit-binder-court-ready")
DEFAULT_COMPILED_DIR = DEFAULT_ROOT / "compiled"
DEFAULT_FRONT_NAME = "0000_Exhibit_Binder_Front_Sheet.pdf"
DEFAULT_TABLE_NAME = "0001_Table_Of_Exhibits.pdf"
DEFAULT_SETS: dict[str, list[str]] = {
    "Eviction_Set": ["B", "G", "V", "Y", "Z", "AA", "M", "O", "P", "W", "X"],
    "Joinder_Set": ["G", "V", "Y", "Z", "AA"],
    "Show_Cause_Set": ["G", "T", "V", "Y", "Z", "AA"],
    "Benjamin_Declaration_Set": ["C", "D", "E", "G", "H", "T", "R", "V", "W", "X", "M", "O", "P"],
    "Jane_Declaration_Set": ["C", "D", "E", "H", "V", "W", "X", "M", "O", "P"],
}


def merge_pdfs(output: Path, inputs: list[Path]) -> None:
    cmd = ["pdfunite", *[str(p) for p in inputs], str(output)]
    subprocess.run(cmd, check=True)


def build_filing_specific_binders(
    *,
    compiled_dir: str | Path,
    sets: dict[str, list[str]],
    front_name: str = DEFAULT_FRONT_NAME,
    table_name: str = DEFAULT_TABLE_NAME,
    exhibit_packet_template: str = "Exhibit_{code}_packet.pdf",
    output_template: str = "{name}.pdf",
    include_front_and_table: bool = True,
) -> list[Path]:
    compiled = Path(compiled_dir)
    front = compiled / front_name
    table = compiled / table_name

    outputs: list[Path] = []
    for name, exhibits in sets.items():
        inputs: list[Path] = []
        if include_front_and_table:
            inputs.extend([front, table])
        inputs.extend(compiled / exhibit_packet_template.format(code=code, name=name) for code in exhibits)
        output = compiled / output_template.format(name=name)
        merge_pdfs(output, inputs)
        outputs.append(output)
    return outputs


def build_filing_specific_binders_from_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    compiled_dir_value = str(payload.get("compiled_dir") or "compiled")
    compiled_dir = (base_dir / compiled_dir_value) if not Path(compiled_dir_value).is_absolute() else Path(compiled_dir_value)

    sets = payload.get("sets") or {}
    if not isinstance(sets, dict) or not sets:
        raise ValueError("config 'sets' must be a non-empty object mapping set name to exhibit-code list")

    normalized_sets: dict[str, list[str]] = {}
    for name, entries in sets.items():
        if not isinstance(entries, list):
            continue
        normalized_sets[str(name)] = [str(item) for item in entries]

    outputs = build_filing_specific_binders(
        compiled_dir=compiled_dir,
        sets=normalized_sets,
        front_name=str(payload.get("front_name") or DEFAULT_FRONT_NAME),
        table_name=str(payload.get("table_name") or DEFAULT_TABLE_NAME),
        exhibit_packet_template=str(payload.get("exhibit_packet_template") or "Exhibit_{code}_packet.pdf"),
        output_template=str(payload.get("output_template") or "{name}.pdf"),
        include_front_and_table=bool(payload.get("include_front_and_table", True)),
    )
    return {
        "config_path": str(config_path),
        "compiled_dir": str(compiled_dir),
        "output_paths": [str(path) for path in outputs],
        "set_count": len(outputs),
    }


def build_default_filing_specific_binders() -> list[Path]:
    return build_filing_specific_binders(
        compiled_dir=DEFAULT_COMPILED_DIR,
        sets=DEFAULT_SETS,
    )


if __name__ == "__main__":
    for item in build_default_filing_specific_binders():
        print(item)
