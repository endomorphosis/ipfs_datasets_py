"""Metrics for deterministic legal parser output."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List

from .exports import parser_elements_for_metrics


def _valid_span(text: str, span: Any) -> bool:
    if not isinstance(span, (list, tuple)) or len(span) != 2:
        return False
    try:
        start = int(span[0])
        end = int(span[1])
    except (TypeError, ValueError):
        return False
    return 0 <= start <= end <= len(text)


def summarize_parser_elements(elements: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Return deterministic quality metrics for parser elements."""

    input_rows: List[Dict[str, Any]] = [item for item in elements or [] if isinstance(item, dict)]
    rows: List[Dict[str, Any]] = parser_elements_for_metrics(input_rows)
    element_count = len(rows)
    if element_count == 0:
        return {
            "element_count": 0,
            "schema_valid_count": 0,
            "schema_valid_rate": 0.0,
            "source_span_valid_count": 0,
            "source_span_valid_rate": 0.0,
            "proof_ready_count": 0,
            "proof_ready_rate": 0.0,
            "repair_required_count": 0,
            "repair_required_rate": 0.0,
            "average_scaffold_quality": 0.0,
            "warning_distribution": {},
            "formal_logic_target_distribution": {},
            "norm_type_distribution": {},
            "modality_distribution": {},
            "cross_reference_resolution_rate": 0.0,
        }

    schema_valid_count = sum(1 for row in rows if row.get("schema_valid") is True)
    source_span_valid_count = sum(
        1 for row in rows if _valid_span(str(row.get("text") or ""), row.get("support_span"))
    )
    proof_ready_count = sum(
        1 for row in rows if (row.get("export_readiness") or {}).get("proof_ready") is True
    )
    repair_required_count = sum(
        1
        for row in rows
        if (row.get("export_readiness") or {}).get(
            "export_repair_required",
            (row.get("llm_repair") or {}).get("required") is True,
        )
        is True
    )

    warnings: Counter[str] = Counter()
    formal_targets: Counter[str] = Counter()
    norm_types: Counter[str] = Counter()
    modalities: Counter[str] = Counter()
    resolved_refs = 0
    total_refs = 0

    for row in rows:
        warnings.update(str(item) for item in row.get("parser_warnings", []) if item)
        readiness = row.get("export_readiness") or {}
        formal_targets.update(str(item) for item in readiness.get("formal_logic_targets", []) if item)
        if row.get("norm_type"):
            norm_types[str(row["norm_type"])] += 1
        if row.get("deontic_operator"):
            modalities[str(row["deontic_operator"])] += 1
        for ref in row.get("resolved_cross_references") or []:
            if isinstance(ref, dict):
                total_refs += 1
                if ref.get("resolution_status") == "resolved" or ref.get("target_exists") is True:
                    resolved_refs += 1

    quality_sum = sum(float(row.get("scaffold_quality") or 0.0) for row in rows)
    return {
        "element_count": element_count,
        "schema_valid_count": schema_valid_count,
        "schema_valid_rate": round(schema_valid_count / element_count, 6),
        "source_span_valid_count": source_span_valid_count,
        "source_span_valid_rate": round(source_span_valid_count / element_count, 6),
        "proof_ready_count": proof_ready_count,
        "proof_ready_rate": round(proof_ready_count / element_count, 6),
        "repair_required_count": repair_required_count,
        "repair_required_rate": round(repair_required_count / element_count, 6),
        "average_scaffold_quality": round(quality_sum / element_count, 6),
        "warning_distribution": dict(sorted(warnings.items())),
        "formal_logic_target_distribution": dict(sorted(formal_targets.items())),
        "norm_type_distribution": dict(sorted(norm_types.items())),
        "modality_distribution": dict(sorted(modalities.items())),
        "cross_reference_resolution_rate": (
            round(resolved_refs / total_refs, 6) if total_refs else 0.0
        ),
    }

