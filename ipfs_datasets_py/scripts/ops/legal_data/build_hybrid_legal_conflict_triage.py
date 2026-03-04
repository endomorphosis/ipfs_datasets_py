"""WS12-05: Conflict Triage Report Builder (JSON + Markdown).

Produces a deterministic conflict-triage report in both JSON and Markdown
formats using ``detect_proof_conflicts`` from ``hybrid_v2_blueprint``.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the reasoner package is importable when this module is used standalone.
_LEGAL_DATA_DIR = Path(__file__).resolve().parents[4] / "processors" / "legal_data"
if str(_LEGAL_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGAL_DATA_DIR))

from reasoner.hybrid_v2_blueprint import (  # noqa: E402
    CONFLICT_REASON_CODES,
    LegalIRV2,
    detect_proof_conflicts,
)

TRIAGE_REPORT_VERSION = "1.0"

REMEDIATION_HINTS: Dict[str, str] = {
    "PC_CONFLICT_MODAL": (
        "Review overlapping obligation and prohibition norms on the same frame. "
        "Apply priority ordering or introduce exception conditions."
    ),
    "PC_CONFLICT_TEMPORAL": (
        "Review norms with differing temporal constraints on the same frame. "
        "Harmonize temporal windows or introduce jurisdiction-specific overrides."
    ),
    "PC_CONFLICT_EXCEPTION_PRECEDENCE": (
        "Review exception conditions that may override mandatory obligations. "
        "Ensure exception scoping is explicit and bounded."
    ),
    "PC_CONFLICT_UNKNOWN_CLASS": (
        "Unknown conflict class detected. Review taxonomy and register the "
        "conflict class in CONFLICT_REASON_CODES."
    ),
}


def _sort_key(conflict: Dict[str, Any]) -> tuple:
    """Stable sort key: (class, first_norm_id, second_norm_id)."""
    norm_ids = conflict.get("norm_ids", ["", ""])
    return (
        conflict.get("class", ""),
        norm_ids[0] if len(norm_ids) > 0 else "",
        norm_ids[1] if len(norm_ids) > 1 else "",
    )


def build_conflict_triage_report(
    ir: LegalIRV2, *, report_id: Optional[str] = None
) -> Dict[str, Any]:
    """Build a deterministic conflict triage report for an IR instance.

    Parameters
    ----------
    ir:
        The :class:`LegalIRV2` instance to analyse.
    report_id:
        Optional explicit report identifier.  When *None* a deterministic
        sha256-based identifier is derived from the jurisdiction and sorted
        conflict data.

    Returns
    -------
    dict
        Keys: ``report_id``, ``triage_version``, ``conflict_count``,
        ``conflicts``, ``generated_at``.
    """
    raw = detect_proof_conflicts(ir)
    conflicts: List[Dict[str, Any]] = sorted(raw["conflicts"], key=_sort_key)

    # Attach remediation hints.
    enriched: List[Dict[str, Any]] = []
    for c in conflicts:
        entry = dict(c)
        entry["remediation_hint"] = REMEDIATION_HINTS.get(
            c.get("reason_code", ""), REMEDIATION_HINTS["PC_CONFLICT_UNKNOWN_CLASS"]
        )
        enriched.append(entry)

    # Deterministic generated_at: sha256 of the sorted conflict JSON.
    conflicts_json = json.dumps(enriched, sort_keys=True, ensure_ascii=True)
    generated_at = hashlib.sha256(conflicts_json.encode()).hexdigest()

    # Deterministic report_id if not provided.
    if report_id is None:
        id_source = ir.jurisdiction + "|" + conflicts_json
        report_id = "triage-" + hashlib.sha256(id_source.encode()).hexdigest()[:16]

    return {
        "report_id": report_id,
        "triage_version": TRIAGE_REPORT_VERSION,
        "conflict_count": len(enriched),
        "conflicts": enriched,
        "generated_at": generated_at,
    }


def render_triage_json(report: Dict[str, Any]) -> str:
    """Render triage report as a deterministic JSON string (sorted keys)."""
    return json.dumps(report, sort_keys=True, ensure_ascii=True, indent=2)


def render_triage_markdown(report: Dict[str, Any]) -> str:
    """Render triage report as a deterministic Markdown string.

    Includes a title, summary table, and per-conflict detail sections with
    remediation hints.
    """
    lines: List[str] = []
    lines.append(f"# Conflict Triage Report")
    lines.append("")
    lines.append(f"**Report ID:** {report['report_id']}")
    lines.append(f"**Triage Version:** {report['triage_version']}")
    lines.append(f"**Conflict Count:** {report['conflict_count']}")
    lines.append(f"**Generated At (hash):** {report['generated_at']}")
    lines.append("")

    conflicts: List[Dict[str, Any]] = report.get("conflicts", [])

    # Summary table.
    lines.append("## Summary")
    lines.append("")
    lines.append("| # | Class | Reason Code | Norms | Frame |")
    lines.append("|---|-------|-------------|-------|-------|")
    for idx, c in enumerate(conflicts, 1):
        norms = ", ".join(c.get("norm_ids", []))
        lines.append(
            f"| {idx} | {c.get('class', '')} | {c.get('reason_code', '')} "
            f"| {norms} | {c.get('frame_ref', '')} |"
        )
    lines.append("")

    # Per-conflict detail.
    lines.append("## Conflict Details")
    lines.append("")
    for idx, c in enumerate(conflicts, 1):
        lines.append(f"### Conflict {idx}: {c.get('class', '')}")
        lines.append("")
        lines.append(f"- **Reason Code:** {c.get('reason_code', '')}")
        lines.append(f"- **Norm IDs:** {', '.join(c.get('norm_ids', []))}")
        lines.append(f"- **Frame Ref:** {c.get('frame_ref', '')}")
        lines.append(f"- **Description:** {c.get('description', '')}")
        lines.append("")
        lines.append(f"**Remediation:** {c.get('remediation_hint', '')}")
        lines.append("")

    return "\n".join(lines)
