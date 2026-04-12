from __future__ import annotations

from pathlib import Path
import subprocess

"""Legacy filing-specific exhibit binder merger extracted from workspace scripts."""


ROOT = Path("/home/barberb/HACC/workspace/exhibit-binder-court-ready")
COMPILED = ROOT / "compiled"
FRONT = COMPILED / "0000_Exhibit_Binder_Front_Sheet.pdf"
TABLE = COMPILED / "0001_Table_Of_Exhibits.pdf"


SETS = {
    "Eviction_Set": ["B", "G", "V", "Y", "Z", "AA", "M", "O", "P", "W", "X"],
    "Joinder_Set": ["G", "V", "Y", "Z", "AA"],
    "Show_Cause_Set": ["G", "T", "V", "Y", "Z", "AA"],
    "Benjamin_Declaration_Set": ["C", "D", "E", "G", "H", "T", "R", "V", "W", "X", "M", "O", "P"],
    "Jane_Declaration_Set": ["C", "D", "E", "H", "V", "W", "X", "M", "O", "P"],
}


def merge_pdfs(output: Path, inputs: list[Path]) -> None:
    cmd = [
        "pdfunite",
        *[str(p) for p in inputs],
        str(output),
    ]
    subprocess.run(cmd, check=True)


def build_default_filing_specific_binders() -> list[Path]:
    outputs: list[Path] = []
    for name, exhibits in SETS.items():
        inputs = [FRONT, TABLE]
        inputs.extend(COMPILED / f"Exhibit_{ex}_packet.pdf" for ex in exhibits)
        output = COMPILED / f"{name}.pdf"
        merge_pdfs(output, inputs)
        print(output)
        outputs.append(output)
    return outputs


if __name__ == "__main__":
    build_default_filing_specific_binders()
