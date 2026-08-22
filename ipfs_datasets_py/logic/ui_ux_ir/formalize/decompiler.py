"""Reconstruct supported UI semantics from formal views (UIFormalDecompiler@1)."""

from __future__ import annotations

import re
from typing import Any

from .contracts import UIFormalizationArtifact, UIReconstructionArtifact


UI_FORMAL_DECOMPILER_INTERFACE = "UIFormalDecompiler@1"

_HAS_ROLE = re.compile(r"HasRole\('([^']+)',\s*'([^']+)'\)")
_ENTRY = re.compile(r"EntryComponent\('([^']+)'\)")
_TERMINAL = re.compile(r"TerminalOutcome\('([^']+)',\s*'([^']+)'\)")
_BIND = re.compile(r"BindsProgram\('([^']+)',\s*'([^']+)',\s*'([^']+)'\)")


def decompile_ui_formalization(
    artifact: UIFormalizationArtifact | dict[str, Any],
) -> UIReconstructionArtifact:
    """Deterministic reconstruction of supported graph nodes from formulas.

    Does not invent missing components; ambiguous or unsupported formulas are
    recorded as losses rather than fabricated structure.
    """
    if isinstance(artifact, UIFormalizationArtifact):
        data = artifact.to_dict()
    else:
        data = dict(artifact)

    components: set[str] = set()
    entries: set[str] = set()
    terminals: set[str] = set()
    bindings: set[str] = set()
    losses: list[str] = []
    ambiguous: list[str] = []

    for view in data.get("views") or []:
        for formula in view.get("formulas") or []:
            text = str(formula.get("text") or "")
            fid = str(formula.get("formula_id") or "")
            m = _HAS_ROLE.search(text)
            if m:
                components.add(m.group(1))
                continue
            m = _ENTRY.search(text)
            if m:
                entries.add(m.group(1))
                components.add(m.group(1))
                continue
            m = _TERMINAL.search(text)
            if m:
                terminals.add(m.group(1))
                continue
            m = _BIND.search(text)
            if m:
                bindings.add(m.group(1))
                continue
            if "only_if Mediated" in text or "Mediated(" in text:
                # intentional approximation — keep, no structure invent
                continue
            if text.startswith("Happens(") or text.startswith("Initially("):
                continue
            if text.startswith("Permitted(") or text.startswith("Obligated("):
                continue
            if text.startswith("Perceives(") or text.startswith("Knows("):
                continue
            if text.startswith("Intends(") or text.startswith("Consents("):
                continue
            if text.startswith("Prohibited(") or text.startswith("~Delegates"):
                continue
            if text.startswith("Eventually(") or text.startswith("Always("):
                continue
            if text.startswith("Terminates(") or text.startswith("Initiates("):
                continue
            # Unknown formula shapes stay as losses, never invented nodes
            if fid:
                ambiguous.append(fid)
                losses.append(f"unreconstructed_formula:{fid}")

    return UIReconstructionArtifact(
        source_artifact_id=str(data.get("artifact_id") or ""),
        reconstructed_document_id=str(data.get("document_id") or ""),
        component_ids=tuple(sorted(components)),
        entry_components=tuple(sorted(entries)),
        terminal_outcomes=tuple(sorted(terminals)),
        program_bindings=tuple(sorted(bindings)),
        losses=tuple(losses),
        ambiguous=tuple(sorted(set(ambiguous))),
    )


__all__ = ["UI_FORMAL_DECOMPILER_INTERFACE", "decompile_ui_formalization"]
