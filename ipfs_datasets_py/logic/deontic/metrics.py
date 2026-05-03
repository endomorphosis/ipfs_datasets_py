"""Metrics for deterministic legal parser output."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping

from .exports import (
    build_decoder_records_from_irs,
    build_ir_slot_provenance_audit_records,
    build_phase8_quality_summary_records,
    build_prover_syntax_records_from_ir,
    parser_elements_for_metrics,
    summarize_decoder_reconstruction_records,
    summarize_ir_slot_provenance_audit_records,
    summarize_phase8_quality_records,
    summarize_prover_syntax_target_coverage,
)
from .ir import LegalNormIR


def _valid_span(text: str, span: Any) -> bool:
    if not isinstance(span, (list, tuple)) or len(span) != 2:
        return False
    try:
        start = int(span[0])
        end = int(span[1])
    except (TypeError, ValueError):
        return False
    return 0 <= start <= end <= len(text)


def summarize_phase8_parser_metrics(elements: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return Phase 8 reconstruction/prover metrics for parser elements."""

    input_rows: List[Dict[str, Any]] = [
        dict(item) for item in elements or [] if isinstance(item, Mapping)
    ]
    rows: List[Dict[str, Any]] = parser_elements_for_metrics(input_rows)
    return _summarize_phase8_rows(rows)


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
            **_summarize_phase8_rows(rows),
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
        **_summarize_phase8_rows(rows),
    }


def _summarize_phase8_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    norms: List[LegalNormIR] = []
    build_errors: Counter[str] = Counter()
    for row in rows:
        try:
            norms.append(LegalNormIR.from_parser_element(row))
        except Exception as exc:  # pragma: no cover - diagnostic only
            build_errors[type(exc).__name__] += 1

    decoder_records = build_decoder_records_from_irs(norms)
    prover_syntax_records: List[Dict[str, Any]] = []
    for norm in norms:
        prover_syntax_records.extend(build_prover_syntax_records_from_ir(norm))
    ir_slot_provenance_records = build_ir_slot_provenance_audit_records(norms)
    phase8_quality_records = build_phase8_quality_summary_records(
        decoder_records=decoder_records,
        prover_syntax_records=prover_syntax_records,
        ir_slot_provenance_records=ir_slot_provenance_records,
    )

    decoder_summary = summarize_decoder_reconstruction_records(decoder_records)
    prover_summary = summarize_prover_syntax_target_coverage(prover_syntax_records)
    provenance_summary = summarize_ir_slot_provenance_audit_records(ir_slot_provenance_records)
    phase8_quality_summary = summarize_phase8_quality_records(
        decoder_records=decoder_records,
        prover_syntax_records=prover_syntax_records,
        ir_slot_provenance_records=ir_slot_provenance_records,
    )

    quality_record_count = len(phase8_quality_records)
    quality_complete_count = sum(
        1 for record in phase8_quality_records if record.get("phase8_quality_complete") is True
    )
    quality_requires_validation_count = sum(
        1 for record in phase8_quality_records if record.get("requires_validation") is True
    )
    coverage_blockers: Counter[str] = Counter()
    for record in phase8_quality_records:
        coverage_blockers.update(str(item) for item in record.get("coverage_blockers", []) if item)

    return {
        "phase8_source_count": len(norms),
        "phase8_record_build_error_count": sum(build_errors.values()),
        "phase8_record_build_error_distribution": dict(sorted(build_errors.items())),
        "phase8_decoder_reconstruction_record_count": decoder_summary["record_count"],
        "phase8_decoder_grounded_phrase_rate": round(
            float(decoder_summary["mean_grounded_decoded_phrase_rate"]), 6
        ),
        "phase8_decoder_ungrounded_phrase_rate": round(
            float(decoder_summary["mean_ungrounded_decoded_phrase_rate"]), 6
        ),
        "phase8_decoder_records_with_missing_slots": decoder_summary[
            "records_with_missing_slots"
        ],
        "phase8_prover_required_target_count": len(prover_summary["required_targets"]),
        "phase8_prover_present_required_target_count": prover_summary[
            "present_required_target_count"
        ],
        "phase8_prover_syntax_valid_rate": prover_summary["syntax_valid_rate"],
        "phase8_ir_grounded_slot_rate": provenance_summary["grounded_slot_rate"],
        "phase8_quality_record_count": quality_record_count,
        "phase8_quality_complete_count": quality_complete_count,
        "phase8_quality_complete_rate": round(
            quality_complete_count / quality_record_count, 6
        )
        if quality_record_count
        else 0.0,
        "phase8_quality_requires_validation_count": quality_requires_validation_count,
        "phase8_quality_requires_validation_rate": round(
            quality_requires_validation_count / quality_record_count, 6
        )
        if quality_record_count
        else 0.0,
        "phase8_coverage_blocker_distribution": dict(sorted(coverage_blockers.items())),
        "decoder_reconstruction_metrics": decoder_summary,
        "prover_syntax_target_coverage": prover_summary,
        "ir_slot_provenance": provenance_summary,
        "phase8_quality_summary": phase8_quality_summary,
    }
