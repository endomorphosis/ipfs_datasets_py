"""Export-record builders for deterministic legal norm IR.

The builders in this module consume ``LegalNormIR`` only. They intentionally do
not inspect raw legal text except through provenance fields already present on
the IR. Legacy parser-element callers can use ``parser_elements_to_export_tables``
as a compatibility bridge while downstream code migrates to typed IR.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Union

from .decoder import decode_legal_norm_ir
from .formula_builder import (
    build_deontic_formula_record_from_ir,
    build_deontic_formula_records_from_irs,
)
from .ir import LegalNormIR, legal_norm_ir_slot_provenance
from .prover_syntax import validate_ir_with_provers


IRInput = Union[LegalNormIR, Mapping[str, Any]]


EXPORT_TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "canonical": {"primary_key": "source_id", "requires_source_id": True},
    "formal_logic": {"primary_key": "formula_id", "requires_source_id": True},
    "proof_obligations": {"primary_key": "proof_obligation_id", "requires_source_id": True},
    "repair_queue": {"primary_key": "repair_id", "requires_source_id": True},
    "decoder_reconstructions": {"primary_key": "reconstruction_id", "requires_source_id": True},
    "prover_syntax_summaries": {"primary_key": "prover_syntax_summary_id", "requires_source_id": True},
    "reconstruction_slot_loss": {"primary_key": "reconstruction_slot_loss_id", "requires_source_id": True},
    "ir_slot_provenance_audits": {"primary_key": "ir_slot_provenance_audit_id", "requires_source_id": True},
    "phase8_quality_summaries": {"primary_key": "phase8_quality_summary_id", "requires_source_id": True},
}

_SECTION_REFERENCE_RE = re.compile(
    r"\bsection\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)\b", re.IGNORECASE
)
_SECTION_REFERENCE_LIST_RE = re.compile(
    r"\bsections\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*"
    r"(?:\s*(?:,|and|or)\s*[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)+)",
    re.IGNORECASE,
)
_SECTION_REFERENCE_TOKEN_RE = re.compile(r"[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:section|sec\.?|§)\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)\b",
    re.IGNORECASE,
)

LOCAL_PROVER_SYNTAX_TARGETS = (
    "frame_logic",
    "deontic_cec",
    "fol",
    "deontic_fol",
    "deontic_temporal_fol",
)

DEFAULT_RECONSTRUCTION_LEGAL_SLOTS = (
    "actor",
    "modality",
    "action",
    "conditions",
    "exceptions",
    "temporal_constraints",
    "cross_references",
)

DEFAULT_IR_SLOT_PROVENANCE_EXPORT_SLOTS = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS

DEFAULT_DETERMINISTIC_CAPABILITY_PROFILE_SLOTS = (
    "actor",
    "modality",
    "action",
)

DEFAULT_DETERMINISTIC_CAPABILITY_PROFILE_SLOTS_BY_FAMILY = {
    "definition": ("actor", "modality", "action"),
    "applicability_rule": ("actor", "modality", "action", "cross_references"),
    "exemption_rule": ("actor", "modality", "action"),
    "instrument_lifecycle_validity": ("actor", "modality", "action"),
    "instrument_lifecycle_expiration": ("actor", "modality", "action"),
    "instrument_lifecycle": ("actor", "modality", "action"),
}


def build_deterministic_parser_capability_profile_record(
    norm: LegalNormIR,
    slots: Sequence[str] = DEFAULT_DETERMINISTIC_CAPABILITY_PROFILE_SLOTS,
) -> Dict[str, Any]:
    """Build a source-grounded parser capability profile row for one norm.

    Phase 8 reports need family-level coverage visibility that is independent
    of repair-count movement. This diagnostic row classifies the deterministic
    parser construction represented by an IR norm and records whether its core
    parser slots are source-grounded. It does not change repair status,
    theorem promotion, or cross-reference resolution.
    """

    capability_family = _deterministic_norm_family(norm)
    effective_slots = _deterministic_capability_profile_slots(norm, slots)
    formula_record = build_deontic_formula_record_from_ir(norm)
    audit = legal_norm_ir_slot_provenance(norm, effective_slots)
    checked_slots = list(audit["checked_slots"])
    grounded_slots = list(audit["grounded_slots"])
    missing_slots = list(audit["missing_slots"])
    ungrounded_slots = list(audit["ungrounded_slots"])
    checked_count = len(checked_slots)
    grounded_count = len(grounded_slots)

    return {
        "parser_capability_profile_id": _stable_id(
            "parser-capability-profile",
            norm.source_id,
            capability_family,
            formula_record["formula"],
        ),
        "source_id": norm.source_id,
        "target_logic": "deterministic_parser_capability",
        "capability_family": capability_family,
        "norm_type": norm.norm_type,
        "modality": norm.modality,
        "formula": formula_record["formula"],
        "formula_proof_ready": bool(formula_record["proof_ready"]),
        "parser_proof_ready": bool(norm.proof_ready),
        "requires_validation": bool(formula_record["requires_validation"]),
        "repair_required": bool(formula_record["repair_required"]),
        "blockers": list(formula_record["blockers"]),
        "parser_warnings": list(norm.quality.parser_warnings),
        "parent_source_id": norm.parent_source_id,
        "is_enumerated_child": norm.is_enumerated_child,
        "enumeration_label": norm.enumeration_label,
        "enumeration_index": norm.enumeration_index,
        "checked_slots": checked_slots,
        "grounded_slots": grounded_slots,
        "missing_slots": missing_slots,
        "ungrounded_slots": ungrounded_slots,
        "source_grounded_slot_rate": round(grounded_count / checked_count, 6)
        if checked_count
        else 0.0,
        "slot_grounding": audit["slot_grounding"],
        "support_span": norm.support_span.to_list(),
        "field_spans": dict(norm.field_spans),
        "schema_version": norm.schema_version,
    }


def build_deterministic_parser_capability_profile_records(
    norms: Sequence[LegalNormIR],
    slots: Sequence[str] = DEFAULT_DETERMINISTIC_CAPABILITY_PROFILE_SLOTS,
) -> List[Dict[str, Any]]:
    """Build parser capability profile rows while preserving norm order."""

    return [build_deterministic_parser_capability_profile_record(norm, slots) for norm in norms]


def summarize_ir_slot_provenance_audit_records(
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize persisted IR slot-provenance audit rows.

    The row builder records provenance for one norm at a time. Phase 8 reports
    also need a corpus-level view that can show whether legally salient IR slots
    were source-grounded, missing, or present without spans. This helper only
    aggregates already-built audit records; it does not change parser repair or
    proof-readiness gates.
    """

    source_ids: set[str] = set()
    checked_slots: set[str] = set()
    grounded_slots: set[str] = set()
    missing_slots: set[str] = set()
    ungrounded_slots: set[str] = set()
    blockers: set[str] = set()
    valid_records = 0
    checked_slot_instances = 0
    grounded_slot_instances = 0
    missing_slot_instances = 0
    ungrounded_slot_instances = 0

    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        valid_records += 1

        source_id = str(record.get("source_id") or "").strip()
        if source_id:
            source_ids.add(source_id)

        record_checked = _slot_names_from_record(record, "checked_slots")
        record_grounded = _slot_names_from_record(record, "grounded_slots")
        record_missing = _slot_names_from_record(record, "missing_slots")
        record_ungrounded = _slot_names_from_record(record, "ungrounded_slots")
        checked_slots.update(record_checked)
        grounded_slots.update(record_grounded)
        missing_slots.update(record_missing)
        ungrounded_slots.update(record_ungrounded)

        checked_slot_instances += int(record.get("checked_slot_count") or len(record_checked))
        grounded_slot_instances += int(record.get("grounded_slot_count") or len(record_grounded))
        missing_slot_instances += int(record.get("missing_slot_count") or len(record_missing))
        ungrounded_slot_instances += int(record.get("ungrounded_slot_count") or len(record_ungrounded))

        for blocker in record.get("coverage_blockers") or []:
            blocker_text = str(blocker or "").strip()
            if blocker_text:
                blockers.add(blocker_text)

    return {
        "source_ids": sorted(source_ids),
        "record_count": valid_records,
        "checked_slots": sorted(checked_slots),
        "grounded_slots": sorted(grounded_slots),
        "missing_slots": sorted(missing_slots),
        "ungrounded_slots": sorted(ungrounded_slots),
        "checked_slot_instance_count": checked_slot_instances,
        "grounded_slot_instance_count": grounded_slot_instances,
        "missing_slot_instance_count": missing_slot_instances,
        "ungrounded_slot_instance_count": ungrounded_slot_instances,
        "grounded_slot_rate": round(grounded_slot_instances / checked_slot_instances, 6)
        if checked_slot_instances
        else 0.0,
        "ungrounded_slot_rate": round(ungrounded_slot_instances / checked_slot_instances, 6)
        if checked_slot_instances
        else 0.0,
        "all_checked_slots_grounded": checked_slot_instances > 0
        and grounded_slot_instances == checked_slot_instances
        and missing_slot_instances == 0
        and ungrounded_slot_instances == 0,
        "requires_validation": bool(missing_slot_instances or ungrounded_slot_instances),
        "coverage_blockers": sorted(blockers),
    }


def summarize_phase8_quality_records(
    decoder_records: Sequence[Mapping[str, Any]] = (),
    prover_syntax_records: Sequence[Mapping[str, Any]] = (),
    ir_slot_provenance_records: Sequence[Mapping[str, Any]] = (),
    required_slots: Sequence[str] = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS,
    required_targets: Sequence[str] = LOCAL_PROVER_SYNTAX_TARGETS,
) -> Dict[str, Any]:
    """Summarize Phase 8 reconstruction, prover, and provenance quality.

    Encoder/decoder reports need a single deterministic quality gate that can
    show whether readable reconstruction, local prover-target coverage, and IR
    source grounding are all complete. This helper aggregates existing export
    records only; it does not alter parser repair status or theorem promotion.
    """

    reconstruction = summarize_reconstruction_slot_loss(decoder_records, required_slots)
    prover = summarize_prover_syntax_target_coverage(prover_syntax_records, required_targets)
    provenance = summarize_ir_slot_provenance_audit_records(ir_slot_provenance_records)

    blockers = set(reconstruction.get("coverage_blockers") or [])
    blockers.update(
        f"missing_prover_syntax_target:{target}"
        for target in prover.get("missing_targets", [])
    )
    blockers.update(
        f"failed_prover_syntax_target:{target}"
        for target in prover.get("failed_targets", [])
    )
    blockers.update(
        f"skipped_prover_syntax_target:{target}"
        for target in prover.get("skipped_targets", [])
    )
    blockers.update(provenance.get("coverage_blockers") or [])

    complete = (
        reconstruction.get("slot_reconstruction_complete") is True
        and prover.get("all_required_passed") is True
        and provenance.get("all_checked_slots_grounded") is True
    )

    return {
        "phase8_quality_complete": complete,
        "requires_validation": not complete,
        "coverage_blockers": sorted(blockers),
        "reconstruction_slot_loss": reconstruction,
        "prover_syntax_target_coverage": prover,
        "ir_slot_provenance": provenance,
    }


def build_phase8_quality_summary_records(
    decoder_records: Sequence[Mapping[str, Any]] = (),
    prover_syntax_records: Sequence[Mapping[str, Any]] = (),
    ir_slot_provenance_records: Sequence[Mapping[str, Any]] = (),
    required_slots: Sequence[str] = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS,
    required_targets: Sequence[str] = LOCAL_PROVER_SYNTAX_TARGETS,
) -> List[Dict[str, Any]]:
    """Build Phase 8 aggregate quality rows grouped by source norm.

    Corpus exports receive flat decoder, prover-syntax, and IR provenance
    records. This helper groups those records by ``source_id`` and emits one
    primary-keyed diagnostic row per norm without inventing provenance for
    records that cannot be tied back to a source clause.
    """

    decoder_by_source: Dict[str, List[Mapping[str, Any]]] = {}
    prover_by_source: Dict[str, List[Mapping[str, Any]]] = {}
    provenance_by_source: Dict[str, List[Mapping[str, Any]]] = {}

    for record in decoder_records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if source_id:
            decoder_by_source.setdefault(source_id, []).append(record)

    for record in prover_syntax_records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if source_id:
            prover_by_source.setdefault(source_id, []).append(record)

    for record in ir_slot_provenance_records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if source_id:
            provenance_by_source.setdefault(source_id, []).append(record)

    source_ids = sorted(set(decoder_by_source) | set(prover_by_source) | set(provenance_by_source))
    return [
        build_phase8_quality_summary_record(
            source_id,
            decoder_records=decoder_by_source.get(source_id, []),
            prover_syntax_records=prover_by_source.get(source_id, []),
            ir_slot_provenance_records=provenance_by_source.get(source_id, []),
            required_slots=required_slots,
            required_targets=required_targets,
        )
        for source_id in source_ids
    ]


def build_phase8_quality_summary_record(
    source_id: str,
    decoder_records: Sequence[Mapping[str, Any]] = (),
    prover_syntax_records: Sequence[Mapping[str, Any]] = (),
    ir_slot_provenance_records: Sequence[Mapping[str, Any]] = (),
    required_slots: Sequence[str] = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS,
    required_targets: Sequence[str] = LOCAL_PROVER_SYNTAX_TARGETS,
) -> Dict[str, Any]:
    """Build a primary-keyed Phase 8 aggregate quality export row.

    The summary helper is useful for in-memory reports, but corpus exports need
    a stable row that can be persisted alongside decoder, prover-syntax, and IR
    provenance records. This record is diagnostic only; it does not change
    parser repair status or theorem promotion.
    """

    summary = summarize_phase8_quality_records(
        decoder_records=decoder_records,
        prover_syntax_records=prover_syntax_records,
        ir_slot_provenance_records=ir_slot_provenance_records,
        required_slots=required_slots,
        required_targets=required_targets,
    )
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        source_ids = set(summary["reconstruction_slot_loss"].get("source_ids") or [])
        source_ids.update(summary["ir_slot_provenance"].get("source_ids") or [])
        if len(source_ids) == 1:
            normalized_source_id = next(iter(source_ids))

    required_slot_key = "|".join(str(slot) for slot in required_slots if slot)
    required_target_key = "|".join(str(target) for target in required_targets if target)
    return {
        "phase8_quality_summary_id": _stable_id(
            "phase8-quality-summary",
            normalized_source_id,
            required_slot_key,
            required_target_key,
        ),
        "source_id": normalized_source_id,
        "target_logic": "phase8_encoder_decoder_prover_quality",
        "phase8_quality_complete": summary["phase8_quality_complete"],
        "requires_validation": summary["requires_validation"],
        "coverage_blockers": summary["coverage_blockers"],
        "coverage_summary": summary,
    }


def summarize_prover_syntax_target_coverage(
    records: Sequence[Mapping[str, Any]],
    required_targets: Sequence[str] = LOCAL_PROVER_SYNTAX_TARGETS,
) -> Dict[str, Any]:
    """Summarize required local prover-syntax target coverage.

    Phase 8 reports need to distinguish a passing formula from a complete
    prover-target report. A missing required local target is an exporter/report
    coverage defect even when every present record is syntax-valid.
    """

    required = tuple(dict.fromkeys(str(target) for target in required_targets if target))
    status_by_target: Dict[str, str] = {}

    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        target = _prover_syntax_record_target(record)
        if not target:
            continue
        status = _prover_syntax_record_status(record)
        current = status_by_target.get(target)
        if current == "failed" or status == current:
            continue
        if status == "failed" or current is None:
            status_by_target[target] = status
        elif current == "skipped" and status == "passed":
            status_by_target[target] = status

    passed_targets = sorted(
        target for target in required if status_by_target.get(target) == "passed"
    )
    failed_targets = sorted(
        target for target in required if status_by_target.get(target) == "failed"
    )
    skipped_targets = sorted(
        target for target in required if status_by_target.get(target) == "skipped"
    )
    missing_targets = sorted(target for target in required if target not in status_by_target)
    present_required_count = len(required) - len(missing_targets)

    return {
        "required_targets": list(required),
        "record_count": len([record for record in records or [] if isinstance(record, Mapping)]),
        "present_required_target_count": present_required_count,
        "passed_targets": passed_targets,
        "failed_targets": failed_targets,
        "skipped_targets": skipped_targets,
        "missing_targets": missing_targets,
        "all_required_passed": bool(required)
        and len(passed_targets) == len(required)
        and not failed_targets
        and not skipped_targets
        and not missing_targets,
        "syntax_valid_rate": round(len(passed_targets) / len(required), 6) if required else 0.0,
    }


def build_prover_syntax_target_coverage_record(
    source_id: str,
    records: Sequence[Mapping[str, Any]],
    required_targets: Sequence[str] = LOCAL_PROVER_SYNTAX_TARGETS,
) -> Dict[str, Any]:
    """Build a stable export row for required prover-target coverage.

    Syntax-valid formulas are not enough for Phase 8 reporting unless every
    required local target has been checked. This record makes missing, skipped,
    and failed targets explicit so downstream metrics do not count partial
    prover validation as complete formal syntax coverage.
    """

    summary = summarize_prover_syntax_target_coverage(records, required_targets)
    blockers: List[str] = []
    blockers.extend(
        f"missing_prover_syntax_target:{target}"
        for target in summary["missing_targets"]
    )
    blockers.extend(
        f"failed_prover_syntax_target:{target}"
        for target in summary["failed_targets"]
    )
    blockers.extend(
        f"skipped_prover_syntax_target:{target}"
        for target in summary["skipped_targets"]
    )

    normalized_source_id = str(source_id or "").strip()
    return {
        "prover_syntax_summary_id": _stable_id(
            "prover-syntax-coverage",
            normalized_source_id,
            "|".join(summary["required_targets"]),
        ),
        "source_id": normalized_source_id,
        "target_logic": "local_prover_syntax",
        "required_targets": summary["required_targets"],
        "present_required_target_count": summary["present_required_target_count"],
        "record_count": summary["record_count"],
        "syntax_valid_rate": summary["syntax_valid_rate"],
        "formal_syntax_valid": summary["all_required_passed"],
        "requires_validation": not summary["all_required_passed"],
        "coverage_blockers": blockers,
        "coverage_summary": summary,
    }


def build_prover_syntax_target_coverage_records_from_irs(
    norms: Sequence[LegalNormIR],
    required_targets: Sequence[str] = LOCAL_PROVER_SYNTAX_TARGETS,
) -> List[Dict[str, Any]]:
    """Build stable prover-target coverage rows for a sequence of IR norms.

    This is a Phase 8 reporting bridge: syntax records remain target-specific,
    while these rows make required local target completeness explicit for every
    source norm in batch exports. Missing, skipped, or failed local targets stay
    visible as coverage blockers and do not change parser proof-readiness gates.
    """

    return [
        build_prover_syntax_target_coverage_record(
            norm.source_id,
            build_prover_syntax_records_from_ir(norm),
            required_targets,
        )
        for norm in norms
    ]


def _prover_syntax_record_target(record: Mapping[str, Any]) -> str:
    for key in ("target", "target_name", "target_logic", "prover_target"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _prover_syntax_record_status(record: Mapping[str, Any]) -> str:
    status = str(record.get("status") or record.get("parse_status") or "").strip().lower()
    if status in {"skipped", "skip", "unavailable"} or record.get("skipped") is True:
        return "skipped"
    if status in {"failed", "failure", "invalid", "error"}:
        return "failed"
    if record.get("syntax_valid") is False or record.get("valid") is False:
        return "failed"
    if status in {"passed", "pass", "valid", "ok"} or record.get("syntax_valid") is True:
        return "passed"
    return "failed"


def build_ir_slot_provenance_audit_record(
    norm: LegalNormIR,
    slots: Sequence[str] = DEFAULT_IR_SLOT_PROVENANCE_EXPORT_SLOTS,
) -> Dict[str, Any]:
    """Build a stable export row for source-grounded IR slot provenance.

    The IR helper reports grounded, missing, and ungrounded slots for decoder
    audits. This export row persists that audit with stable identifiers and
    explicit blockers so reports can distinguish a readable reconstruction from
    one that omitted or invented legally salient IR slots.
    """

    audit = legal_norm_ir_slot_provenance(norm, slots)
    checked_slots = list(audit["checked_slots"])
    grounded_slots = list(audit["grounded_slots"])
    missing_slots = list(audit["missing_slots"])
    ungrounded_slots = list(audit["ungrounded_slots"])
    blockers = [f"missing_ir_slot_provenance:{slot}" for slot in missing_slots]
    blockers.extend(f"ungrounded_ir_slot_provenance:{slot}" for slot in ungrounded_slots)

    checked_count = len(checked_slots)
    grounded_count = len(grounded_slots)
    ungrounded_count = len(ungrounded_slots)

    return {
        "ir_slot_provenance_audit_id": _stable_id(
            "ir-slot-provenance-audit",
            norm.source_id,
            "|".join(checked_slots),
        ),
        "source_id": norm.source_id,
        "target_logic": "legal_norm_ir",
        "support_span": norm.support_span.to_list(),
        "checked_slots": checked_slots,
        "grounded_slots": grounded_slots,
        "missing_slots": missing_slots,
        "ungrounded_slots": ungrounded_slots,
        "checked_slot_count": checked_count,
        "grounded_slot_count": grounded_count,
        "missing_slot_count": len(missing_slots),
        "ungrounded_slot_count": ungrounded_count,
        "all_checked_slots_grounded": checked_count > 0 and grounded_count == checked_count and ungrounded_count == 0,
        "grounded_slot_rate": round(grounded_count / checked_count, 6) if checked_count else 0.0,
        "ungrounded_slot_rate": round(ungrounded_count / checked_count, 6) if checked_count else 0.0,
        "requires_validation": bool(blockers),
        "coverage_blockers": blockers,
        "slot_grounding": audit["slot_grounding"],
    }


def build_ir_slot_provenance_audit_records(
    norms: Sequence[LegalNormIR],
    slots: Sequence[str] = DEFAULT_IR_SLOT_PROVENANCE_EXPORT_SLOTS,
) -> List[Dict[str, Any]]:
    """Build IR slot-provenance audit rows for a stable sequence of norms."""

    return [build_ir_slot_provenance_audit_record(norm, slots) for norm in norms]


def build_formal_logic_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a parquet-safe formal-logic row from typed legal IR."""

    record = build_deontic_formula_record_from_ir(norm)
    reference_provenance = _cross_reference_provenance_from_ir(norm)
    row = {
        "formula_id": record["formula_id"],
        "source_id": record["source_id"],
        "canonical_citation": record["canonical_citation"],
        "parent_source_id": record["parent_source_id"],
        "enumeration_label": record["enumeration_label"],
        "enumeration_index": record["enumeration_index"],
        "is_enumerated_child": record["is_enumerated_child"],
        "target_logic": record["target_logic"],
        "formula": record["formula"],
        "modality": record["modality"],
        "norm_type": record["norm_type"],
        "support_span": record["support_span"],
        "field_spans": record["field_spans"],
        "proof_ready": record["proof_ready"],
        "requires_validation": record["requires_validation"],
        "repair_required": record["repair_required"],
        "blockers": record["blockers"],
        "parser_warnings": record["parser_warnings"],
        "omitted_formula_slots": record["omitted_formula_slots"],
        "deterministic_resolution": record["deterministic_resolution"],
        "schema_version": record["schema_version"],
    }
    row.update(reference_provenance)
    return row


def build_proof_obligation_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a proof-obligation row without promoting blocked clauses."""

    formula_record = build_deontic_formula_record_from_ir(norm)
    proof_ready = bool(formula_record["proof_ready"])
    blockers = list(formula_record["blockers"])
    reference_provenance = _cross_reference_provenance_from_ir(norm)
    row = {
        "proof_obligation_id": _stable_id("proof", norm.source_id, formula_record["formula"]),
        "formula_id": formula_record["formula_id"],
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "parent_source_id": norm.parent_source_id,
        "enumeration_label": norm.enumeration_label,
        "enumeration_index": norm.enumeration_index,
        "is_enumerated_child": norm.is_enumerated_child,
        "formula": formula_record["formula"],
        "target_logic": formula_record["target_logic"],
        "modality": norm.modality,
        "norm_type": norm.norm_type,
        "support_span": norm.support_span.to_list(),
        "field_spans": dict(norm.field_spans),
        "theorem_candidate": proof_ready,
        "proof_ready": proof_ready,
        "requires_validation": bool(formula_record["requires_validation"]),
        "repair_required": bool(formula_record["repair_required"]),
        "blockers": blockers,
        "parser_warnings": list(norm.quality.parser_warnings),
        "deterministic_resolution": formula_record["deterministic_resolution"],
        "schema_version": norm.schema_version,
    }
    row.update(reference_provenance)
    return row


def build_repair_queue_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build an auditable deterministic repair-queue row for blocked clauses."""

    blockers = list(norm.blockers)
    if not blockers:
        blockers = list(norm.quality.parser_warnings)

    formula_record = build_deontic_formula_record_from_ir(norm)

    reference_provenance = _cross_reference_provenance_from_ir(norm)
    row = {
        "repair_id": _stable_id("repair", norm.source_id, "|".join(blockers)),
        "formula_id": formula_record["formula_id"],
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "source_text": norm.source_text,
        "support_text": norm.support_text,
        "support_span": norm.support_span.to_list(),
        "target_logic": formula_record["target_logic"],
        "formula": formula_record["formula"],
        "omitted_formula_slots": formula_record["omitted_formula_slots"],
        "formula_proof_ready": bool(formula_record["proof_ready"]),
        "formula_repair_required": bool(formula_record["repair_required"]),
        "deterministic_resolution": formula_record["deterministic_resolution"],
        "norm_type": norm.norm_type,
        "modality": norm.modality,
        "reasons": blockers,
        "parser_warnings": list(norm.quality.parser_warnings),
        "requires_llm_repair": False,
        "allow_llm_repair": False,
        "schema_version": norm.schema_version,
    }
    row.update(reference_provenance)
    return row


def build_procedure_event_records_from_ir(norm: LegalNormIR) -> List[Dict[str, Any]]:
    """Build export records for structured procedure event relations.

    Procedure relations are provenance and event-ordering metadata. Only the
    narrow receipt-trigger relation is tagged as a formula prerequisite; before
    and after ordering relations remain export-visible without becoming deontic
    antecedents.
    """

    procedure = norm.procedure
    if not isinstance(procedure, Mapping):
        return []

    records: List[Dict[str, Any]] = []
    for index, relation in enumerate(procedure.get("event_relations") or [], start=1):
        if not isinstance(relation, Mapping):
            continue

        event = str(relation.get("event") or procedure.get("terminal_event") or "").strip()
        relation_type = str(relation.get("relation") or "").strip()
        anchor_event = str(relation.get("anchor_event") or procedure.get("trigger_event") or "").strip()
        if not event and not anchor_event:
            continue

        span = relation.get("span")
        if not isinstance(span, list):
            span = []
        raw_text = str(relation.get("raw_text") or relation.get("value") or "").strip()
        formula_antecedent = relation_type in {
            "triggered_by_receipt_of",
            "triggered_by_filing_of",
            "triggered_by_electronic_filing_of",
            "triggered_by_submission_of",
            "triggered_by_notice_and_hearing",
            "triggered_by_approval_of",
            "triggered_by_completion_of",
            "triggered_by_effective_date_of",
            "triggered_by_certification_of",
            "triggered_by_issuance_of",
            "triggered_by_publication_of",
            "triggered_by_service_of",
            "triggered_by_adoption_of",
            "triggered_by_commencement_of",
            "triggered_by_execution_of",
            "triggered_by_recording_of",
            "triggered_by_renewal_of",
            "triggered_by_registration_of",
            "triggered_by_enrollment_of",
            "triggered_by_acceptance_of",
            "triggered_by_acknowledgment_of",
            "triggered_by_inspection_of",
            "triggered_by_expiration_of",
            "triggered_by_termination_of",
            "triggered_by_revocation_of",
            "triggered_by_denial_of",
            "triggered_by_payment_of",
            "triggered_by_assessment_of",
            "triggered_by_deposit_of",
            "triggered_by_clearing_of",
            "triggered_by_calculation_of",
            "triggered_by_correction_of",
            "triggered_by_adjustment_of",
            "triggered_by_audit_of",
            "triggered_by_determination_of",
            "triggered_by_verification_of",
            "triggered_by_validation_of",
            "triggered_by_review_of",
            "triggered_by_reconsideration_of",
            "triggered_by_hearing_of",
            "triggered_by_public_comment_on",
            "triggered_by_consultation_with",
            "triggered_by_final_decision_of",
            "triggered_by_mailing_of",
            "triggered_by_certified_mailing_of",
            "triggered_by_delivery_of",
            "triggered_by_electronic_service_on",
            "triggered_by_transmission_of",
            "triggered_by_receipt_confirmation_of",
            "triggered_by_posting_of",
            "triggered_by_postmark_of",
            "triggered_by_docketing_of",
            "triggered_by_entry_of",
            "triggered_by_signature_of",
            "triggered_by_notarization_of",
            "triggered_by_countersignature_of",
            "triggered_by_opening_of",
            "triggered_by_return_of",
            "triggered_by_reinstatement_of",
            "triggered_by_withdrawal_of",
            "triggered_by_archiving_of",
            "triggered_by_retention_of",
        }
        proof_role = "prerequisite" if formula_antecedent else "ordering_provenance"

        records.append({
            "event_id": _stable_id(
                "event",
                norm.source_id,
                str(index),
                event,
                relation_type,
                anchor_event,
                "|".join(str(part) for part in span),
            ),
            "source_id": norm.source_id,
            "canonical_citation": norm.canonical_citation,
            "event_order": index,
            "event": event,
            "event_symbol": _procedure_event_symbol(event),
            "relation": relation_type,
            "anchor_event": anchor_event,
            "anchor_symbol": _procedure_event_symbol(anchor_event),
            "raw_text": raw_text,
            "span": list(span),
            "support_span": norm.support_span.to_list(),
            "procedure_value": str(procedure.get("value") or ""),
            "is_formula_antecedent": formula_antecedent,
            "proof_role": proof_role,
            "relation_record": dict(relation),
            "schema_version": norm.schema_version,
        })

    return records


def build_prover_syntax_records_from_ir(
    norm: LegalNormIR,
    targets: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build syntax-only prover validation rows from typed legal IR.

    These records are diagnostics for the Phase 8 encoder/export quality loop.
    They do not alter parser warnings, repair queue status, or theorem promotion
    gates for blocked clauses.
    """

    return [record.to_dict() for record in validate_ir_with_provers(norm, targets).targets]


def build_prover_syntax_summary_record_from_ir(
    norm: LegalNormIR,
    targets: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Build a document-level Phase 8 syntax summary for local prover targets.

    The summary is diagnostic export metadata. It reports whether the formulas
    rendered from this IR are accepted by the local syntax adapters, but it does
    not relax parser warnings, repair rows, or theorem-promotion gates.
    """

    records = build_prover_syntax_records_from_ir(norm, targets)
    checked_records = [record for record in records if record.get("skipped") is not True]
    valid_count = sum(1 for record in checked_records if record.get("syntax_valid") is True)
    invalid_records = [record for record in checked_records if record.get("syntax_valid") is not True]
    diagnostics: Dict[str, int] = {}
    for record in invalid_records:
        for diagnostic in record.get("diagnostics") or []:
            text = str(diagnostic)
            diagnostics[text] = diagnostics.get(text, 0) + 1

    target_names = [str(record.get("target") or "") for record in records]
    required_targets_passed = bool(checked_records) and valid_count == len(checked_records)

    return {
        "prover_syntax_summary_id": _stable_id(
            "prover_syntax",
            norm.source_id,
            "|".join(target_names),
            str(valid_count),
            str(len(checked_records)),
        ),
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "target_count": len(records),
        "checked_target_count": len(checked_records),
        "syntax_valid_count": valid_count,
        "syntax_invalid_count": len(invalid_records),
        "syntax_valid_rate": (valid_count / len(checked_records)) if checked_records else 0.0,
        "required_targets_passed": required_targets_passed,
        "proof_ready": norm.proof_ready,
        "requires_validation": bool(norm.blockers) or not required_targets_passed,
        "parser_warnings": list(norm.quality.parser_warnings),
        "targets": target_names,
        "diagnostic_distribution": diagnostics,
        "prover_syntax_records": records,
        "schema_version": norm.schema_version,
    }


def build_decoder_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build an auditable Phase 8 reconstruction row from typed legal IR.

    The decoder record is diagnostic only: it reports deterministic
    reconstruction text and phrase provenance without changing parser repair
    gates, theorem promotion, or formal logic export readiness.
    """

    decoded = decode_legal_norm_ir(norm)
    phrase_rows = _decoder_phrase_rows_with_reference_provenance(norm, decoded.phrases)
    fixed_phrase_count = sum(1 for phrase in phrase_rows if phrase.get("fixed") is True)
    ungrounded_phrase_count = sum(
        1
        for phrase in phrase_rows
        if phrase.get("fixed") is not True and not phrase.get("spans")
    )
    legal_phrase_count = len(phrase_rows) - fixed_phrase_count
    grounded_phrase_count = legal_phrase_count - ungrounded_phrase_count
    grounded_phrase_rate = (
        grounded_phrase_count / legal_phrase_count if legal_phrase_count else 1.0
    )
    ungrounded_phrase_rate = (
        ungrounded_phrase_count / legal_phrase_count if legal_phrase_count else 0.0
    )

    return {
        "reconstruction_id": _stable_id("reconstruction", norm.source_id, decoded.text),
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "source_text": norm.source_text,
        "support_text": norm.support_text,
        "decoded_text": decoded.text,
        "support_span": decoded.support_span,
        "phrase_count": len(phrase_rows),
        "fixed_phrase_count": fixed_phrase_count,
        "legal_phrase_count": legal_phrase_count,
        "grounded_phrase_count": grounded_phrase_count,
        "ungrounded_decoded_phrase_count": ungrounded_phrase_count,
        "grounded_decoded_phrase_rate": grounded_phrase_rate,
        "ungrounded_decoded_phrase_rate": ungrounded_phrase_rate,
        "missing_slot_count": len(decoded.missing_slots),
        "missing_slots": list(decoded.missing_slots),
        "parser_warnings": list(decoded.parser_warnings),
        "phrase_provenance": phrase_rows,
        "proof_ready": norm.proof_ready,
        "requires_validation": bool(norm.blockers or decoded.missing_slots),
        "schema_version": norm.schema_version,
    }


def build_decoder_records_from_irs(norms: Iterable[LegalNormIR]) -> List[Dict[str, Any]]:
    """Build ordered deterministic reconstruction rows for typed legal IR."""

    return [build_decoder_record_from_ir(norm) for norm in norms]


def _decoder_phrase_rows_with_reference_provenance(
    norm: LegalNormIR,
    phrases: Iterable[Any],
) -> List[Dict[str, Any]]:
    """Return decoder phrase rows plus source-grounded cross-reference rows.

    The natural-language decoder often renders a cross-reference inside an
    exception or override phrase. Phase 8 slot-loss reports still need the
    legally salient ``cross_references`` slot to be explicitly represented in
    provenance. These extra rows are diagnostic-only and do not change the
    decoded text.
    """

    rows = []
    for phrase in phrases:
        row = phrase.to_dict()
        if row.get("fixed") is True:
            row.setdefault("fixed_connective", True)
        rows.append(row)
    seen = {
        (
            str(row.get("slot") or ""),
            str(row.get("text") or ""),
            tuple(tuple(span) for span in row.get("spans") or []),
        )
        for row in rows
        if isinstance(row, Mapping)
    }

    for reference in _decoder_reference_records(norm):
        text = _decoder_reference_text(reference)
        spans = _decoder_reference_spans(reference)
        if not text or not spans:
            continue
        key = ("cross_references", text, tuple(tuple(span) for span in spans))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "text": text,
                "slot": "cross_references",
                "spans": spans,
                "fixed": False,
                "provenance_only": True,
            }
        )

    return rows


def _decoder_reference_records(norm: LegalNormIR) -> List[Mapping[str, Any]]:
    records: List[Mapping[str, Any]] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    for reference in list(norm.cross_references or []) + list(norm.resolved_cross_references or []):
        if not isinstance(reference, Mapping):
            continue
        text = _decoder_reference_text(reference)
        spans = _decoder_reference_spans(reference)
        key = tuple((span[0], span[1]) for span in spans)
        if not text or key in seen:
            continue
        seen.add(key)
        records.append(reference)
    return records


def _decoder_reference_text(reference: Mapping[str, Any]) -> str:
    for key in ("normalized_text", "raw_text", "canonical_citation", "value", "target"):
        value = str(reference.get(key) or "").strip()
        if value:
            return value
    return ""


def _decoder_reference_spans(reference: Mapping[str, Any]) -> List[List[int]]:
    spans: List[List[int]] = []
    for key in ("span", "source_span", "support_span", "clause_span"):
        spans.extend(_decoder_coerce_spans(reference.get(key)))
    return _dedupe_decoder_spans(spans)


def _decoder_coerce_spans(value: Any) -> List[List[int]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) == 2 and all(isinstance(item, int) for item in value):
            return [[int(value[0]), int(value[1])]]
        spans: List[List[int]] = []
        for item in value:
            spans.extend(_decoder_coerce_spans(item))
        return spans
    return []


def _dedupe_decoder_spans(spans: Sequence[Sequence[int]]) -> List[List[int]]:
    seen: set[tuple[int, int]] = set()
    deduped: List[List[int]] = []
    for span in spans:
        if len(span) != 2:
            continue
        key = (int(span[0]), int(span[1]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append([key[0], key[1]])
    return deduped


def build_decoder_slot_grounding_audit_record(
    decoder_record: Mapping[str, Any],
    required_slots: Sequence[str] = ("actor", "action"),
) -> Dict[str, Any]:
    """Build a deterministic audit row for decoded IR-slot grounding.

    Decoder reconstruction rows are useful only when legally salient phrases can
    be traced back to IR slots and source spans. This helper consumes an
    existing decoder row and reports whether required decoded slots are present
    and source-grounded. It is diagnostic export metadata only; it does not
    change parser warnings, repair status, or theorem-promotion gates.
    """

    required = _normalized_decoder_required_slots(required_slots)
    phrase_rows = [
        dict(phrase)
        for phrase in decoder_record.get("phrase_provenance") or []
        if isinstance(phrase, Mapping)
    ]

    slot_status: Dict[str, Dict[str, Any]] = {}
    missing_slots: List[str] = []
    ungrounded_slots: List[str] = []
    grounded_slots: List[str] = []

    for slot in required:
        slot_phrases = [
            phrase for phrase in phrase_rows if slot in _decoder_phrase_slot_names(phrase)
        ]
        grounded_phrases = [
            phrase for phrase in slot_phrases if _decoder_phrase_has_source_span(phrase)
        ]
        present = bool(slot_phrases)
        grounded = bool(grounded_phrases)
        if not present:
            missing_slots.append(slot)
        elif not grounded:
            ungrounded_slots.append(slot)
        else:
            grounded_slots.append(slot)

        slot_status[slot] = {
            "present": present,
            "grounded": grounded,
            "phrase_count": len(slot_phrases),
            "grounded_phrase_count": len(grounded_phrases),
        }

    blockers = [f"missing_decoded_slot:{slot}" for slot in missing_slots]
    blockers.extend(f"ungrounded_decoded_slot:{slot}" for slot in ungrounded_slots)
    source_id = str(decoder_record.get("source_id") or "").strip()

    return {
        "decoder_slot_grounding_audit_id": _stable_id(
            "decoder-slot-grounding",
            source_id,
            "|".join(required),
            str(decoder_record.get("reconstruction_id") or ""),
        ),
        "source_id": source_id,
        "reconstruction_id": str(decoder_record.get("reconstruction_id") or ""),
        "decoded_text": str(decoder_record.get("decoded_text") or ""),
        "required_slots": required,
        "grounded_slots": grounded_slots,
        "missing_slots": missing_slots,
        "ungrounded_slots": ungrounded_slots,
        "slot_status": slot_status,
        "slot_grounding_complete": not missing_slots and not ungrounded_slots,
        "requires_validation": bool(
            decoder_record.get("requires_validation") is True
            or missing_slots
            or ungrounded_slots
        ),
        "grounding_blockers": blockers,
        "proof_ready": bool(decoder_record.get("proof_ready")),
        "parser_warnings": list(decoder_record.get("parser_warnings") or []),
        "schema_version": str(decoder_record.get("schema_version") or ""),
    }


def build_decoder_slot_grounding_audit_record_from_ir(
    norm: LegalNormIR,
    required_slots: Sequence[str] = ("actor", "action"),
) -> Dict[str, Any]:
    """Build a decoder slot-grounding audit row from typed legal IR."""

    return build_decoder_slot_grounding_audit_record(
        build_decoder_record_from_ir(norm),
        required_slots,
    )


def build_decoder_slot_grounding_audit_records_from_irs(
    norms: Iterable[LegalNormIR],
    required_slots: Sequence[str] = ("actor", "action"),
) -> List[Dict[str, Any]]:
    """Build ordered decoder slot-grounding audit rows for typed legal IR.

    Phase 8 reconstruction reports need batch-level diagnostics, not just
    per-row audit records. This helper keeps the audit source-grounded by
    deriving each row from the existing deterministic decoder record path.
    """

    return [
        build_decoder_slot_grounding_audit_record_from_ir(norm, required_slots)
        for norm in norms
    ]


def summarize_decoder_slot_grounding_audit_records(
    records: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize decoded-slot grounding audit rows for export reports.

    The summary is diagnostic metadata for encoder/decoder quality reporting.
    It does not alter parser warnings, theorem promotion, or repair status.
    """

    rows = [dict(record) for record in records if isinstance(record, Mapping)]
    required_slots: List[str] = []
    grounded_slots: Dict[str, int] = {}
    missing_slots: Dict[str, int] = {}
    ungrounded_slots: Dict[str, int] = {}
    blocker_distribution: Dict[str, int] = {}

    complete_count = 0
    requires_validation_count = 0
    proof_ready_count = 0
    total_required_slot_mentions = 0
    grounded_required_slot_mentions = 0

    for row in rows:
        if row.get("slot_grounding_complete") is True:
            complete_count += 1
        if row.get("requires_validation") is True:
            requires_validation_count += 1
        if row.get("proof_ready") is True:
            proof_ready_count += 1

        for slot in row.get("required_slots") or []:
            slot_name = str(slot)
            if slot_name and slot_name not in required_slots:
                required_slots.append(slot_name)
            total_required_slot_mentions += 1

        for slot in row.get("grounded_slots") or []:
            slot_name = str(slot)
            grounded_slots[slot_name] = grounded_slots.get(slot_name, 0) + 1
            grounded_required_slot_mentions += 1

        for slot in row.get("missing_slots") or []:
            slot_name = str(slot)
            missing_slots[slot_name] = missing_slots.get(slot_name, 0) + 1

        for slot in row.get("ungrounded_slots") or []:
            slot_name = str(slot)
            ungrounded_slots[slot_name] = ungrounded_slots.get(slot_name, 0) + 1

        for blocker in row.get("grounding_blockers") or []:
            blocker_text = str(blocker)
            blocker_distribution[blocker_text] = blocker_distribution.get(blocker_text, 0) + 1

    record_count = len(rows)
    return {
        "record_count": record_count,
        "proof_ready_count": proof_ready_count,
        "slot_grounding_complete_count": complete_count,
        "requires_validation_count": requires_validation_count,
        "required_slots": required_slots,
        "grounded_slot_distribution": grounded_slots,
        "missing_slot_distribution": missing_slots,
        "ungrounded_slot_distribution": ungrounded_slots,
        "grounding_blocker_distribution": blocker_distribution,
        "slot_grounding_complete_rate": complete_count / record_count if record_count else 0.0,
        "grounded_required_slot_rate": (
            grounded_required_slot_mentions / total_required_slot_mentions
            if total_required_slot_mentions
            else 1.0
        ),
    }


def _normalized_decoder_required_slots(required_slots: Sequence[str]) -> List[str]:
    slots: List[str] = []
    for slot in required_slots or []:
        value = str(slot or "").strip()
        if value and value not in slots:
            slots.append(value)
    return slots


def _decoder_phrase_slot_names(phrase: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()

    def add_value(value: Any) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text:
                names.add(text)
        elif isinstance(value, Mapping):
            for nested_key in (
                "slot",
                "slots",
                "source_slot",
                "source_slots",
                "field",
                "fields",
                "source_field",
                "source_fields",
                "ir_slot",
                "slot_name",
            ):
                add_value(value.get(nested_key))
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            for item in value:
                add_value(item)

    for key in (
        "slot",
        "slots",
        "source_slot",
        "source_slots",
        "field",
        "fields",
        "source_field",
        "source_fields",
        "ir_slot",
        "slot_name",
        "provenance",
        "sources",
    ):
        add_value(phrase.get(key))
    return names


def _decoder_phrase_has_source_span(phrase: Mapping[str, Any]) -> bool:
    if phrase.get("fixed") is True:
        return False

    for key in ("spans", "source_spans", "field_spans"):
        spans = phrase.get(key)
        if isinstance(spans, Sequence) and not isinstance(spans, (str, bytes, bytearray)):
            if any(_span_like(span) for span in spans):
                return True

    for key in ("span", "source_span", "support_span", "field_span"):
        if _span_like(phrase.get(key)):
            return True
    return False


def _span_like(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
        and value[0] is not None
        and value[1] is not None
    )


def summarize_decoder_reconstruction_records(
    records: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return deterministic aggregate metrics for decoder reconstruction rows.

    The summary consumes only decoder export rows. It is diagnostic and does not
    change theorem promotion, repair status, or parser warnings.
    """

    rows = [dict(record) for record in records]
    warning_distribution: Dict[str, int] = {}
    for row in rows:
        for warning in row.get("parser_warnings") or []:
            warning_text = str(warning)
            warning_distribution[warning_text] = warning_distribution.get(warning_text, 0) + 1

    grounded_rates = [
        float(row.get("grounded_decoded_phrase_rate") or 0.0)
        for row in rows
    ]
    ungrounded_rates = [
        float(row.get("ungrounded_decoded_phrase_rate") or 0.0)
        for row in rows
    ]
    total_missing_slots = sum(int(row.get("missing_slot_count") or 0) for row in rows)
    records_with_missing_slots = sum(
        1 for row in rows if int(row.get("missing_slot_count") or 0) > 0
    )
    validation_required = [row for row in rows if row.get("requires_validation") is True]
    proof_ready = [row for row in rows if row.get("proof_ready") is True]

    worst_grounded = sorted(
        (
            {
                "source_id": row.get("source_id", ""),
                "grounded_decoded_phrase_rate": float(
                    row.get("grounded_decoded_phrase_rate") or 0.0
                ),
                "missing_slot_count": int(row.get("missing_slot_count") or 0),
            }
            for row in rows
        ),
        key=lambda item: (item["grounded_decoded_phrase_rate"], -item["missing_slot_count"]),
    )

    return {
        "record_count": len(rows),
        "proof_ready_count": len(proof_ready),
        "requires_validation_count": len(validation_required),
        "mean_grounded_decoded_phrase_rate": (
            sum(grounded_rates) / len(grounded_rates) if grounded_rates else 0.0
        ),
        "mean_ungrounded_decoded_phrase_rate": (
            sum(ungrounded_rates) / len(ungrounded_rates) if ungrounded_rates else 0.0
        ),
        "total_missing_slot_count": total_missing_slots,
        "records_with_missing_slots": records_with_missing_slots,
        "parser_warning_distribution": warning_distribution,
        "worst_grounded_reconstructions": worst_grounded[:5],
    }


def _procedure_event_symbol(value: str) -> str:
    words = re.findall(r"[0-9A-Za-z]+", str(value or ""))
    return "".join(word.capitalize() for word in words) if words else ""


def build_document_export_tables_from_ir(norms: Iterable[LegalNormIR]) -> Dict[str, List[Dict[str, Any]]]:
    """Build deterministic export tables from typed legal norms."""

    tables: Dict[str, List[Dict[str, Any]]] = {
        "canonical": [],
        "formal_logic": [],
        "proof_obligations": [],
        "repair_queue": [],
        "decoder_reconstructions": [],
        "prover_syntax_summaries": [],
    }

    resolved_norms = _with_same_document_reference_resolutions(list(norms))

    for norm in resolved_norms:
        tables["canonical"].append(_canonical_record_from_ir(norm))
        tables["formal_logic"].append(build_formal_logic_record_from_ir(norm))
        proof_record = build_proof_obligation_record_from_ir(norm)
        tables["proof_obligations"].append(proof_record)
        tables["decoder_reconstructions"].append(build_decoder_record_from_ir(norm))
        tables["prover_syntax_summaries"].append(build_prover_syntax_summary_record_from_ir(norm))
        if proof_record["requires_validation"]:
            tables["repair_queue"].append(build_repair_queue_record_from_ir(norm))

    return tables


def parser_elements_to_export_tables(elements: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Compatibility bridge from parser dictionaries to IR export tables."""

    return build_document_export_tables_from_ir(
        LegalNormIR.from_parser_element(dict(element)) for element in elements
    )


def parser_elements_for_metrics(
    elements: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return parser elements with deterministic readiness for metrics.

    Metrics should report active deterministic repair work, not stale parser
    repair flags that the IR/formula layer has already resolved. This wrapper
    keeps the metric contract explicit while reusing the same no-LLM readiness
    projection used by converter/export callers.
    """

    all_source_elements = [
        _hydrate_parser_element_from_prompt_context(dict(element))
        for element in elements
    ]
    _hydrate_prompt_context_modal_slots(all_source_elements)
    for element in all_source_elements:
        _hydrate_prompt_context_override_clause_details(element)

    source_elements = [element for element in all_source_elements if not _is_context_only_parser_element(element)]
    for element in source_elements:
        _hydrate_prompt_context_same_document_references(element, all_source_elements)
    source_norms = [LegalNormIR.from_parser_element(element) for element in all_source_elements]
    resolved_norms = _with_same_document_reference_resolutions(source_norms)
    resolved_references_by_source_id = {
        norm.source_id: list(norm.resolved_cross_references)
        for norm in resolved_norms
        if norm.source_id
    }
    inactive_projection_by_source_id = {
        str(element.get("source_id") or ""): element
        for element in source_elements
        if element.get("source_id") and _has_inactive_deterministic_repair_projection(element)
    }
    metric_elements = parser_elements_with_ir_export_readiness(source_elements)
    batch_formula_records_by_source_id = {
        record.get("source_id"): record
        for record in build_deontic_formula_records_from_irs(resolved_norms)
        if record.get("source_id")
    }

    for element in metric_elements:
        export_readiness = dict(element.get("export_readiness") or {})
        inactive_projection = inactive_projection_by_source_id.get(str(element.get("source_id") or ""))
        batch_formula_record = batch_formula_records_by_source_id.get(element.get("source_id"))
        if batch_formula_record:
            export_readiness["formula_proof_ready"] = bool(batch_formula_record.get("proof_ready"))
            export_readiness["formula_requires_validation"] = bool(
                batch_formula_record.get("requires_validation")
            )
            export_readiness["formula_repair_required"] = bool(
                batch_formula_record.get("repair_required")
            )
            export_readiness["deterministic_resolution"] = dict(
                batch_formula_record.get("deterministic_resolution") or {}
            )
            _project_same_document_resolved_cross_references(
                element,
                resolved_references_by_source_id.get(str(element.get("source_id") or ""), []),
                batch_formula_record,
            )
            _project_formula_record_active_repair_status(element, batch_formula_record)
        _clear_stale_active_repair_from_export_readiness(element)

        if inactive_projection:
            projected_readiness = dict(inactive_projection.get("export_readiness") or {})
            deterministic_resolution = dict(
                projected_readiness.get("deterministic_resolution")
                or dict(inactive_projection.get("llm_repair") or {}).get("deterministic_resolution")
                or {}
            )
            if deterministic_resolution:
                export_readiness["deterministic_resolution"] = deterministic_resolution
            export_readiness["formula_proof_ready"] = True
            export_readiness["formula_requires_validation"] = False
            export_readiness["formula_repair_required"] = False
            export_readiness["export_requires_validation"] = False
            export_readiness["export_repair_required"] = False

        formula_proof_ready = export_readiness.get("formula_proof_ready") is True
        formula_requires_validation = bool(export_readiness.get("formula_requires_validation"))
        formula_repair_required = bool(export_readiness.get("formula_repair_required"))

        if formula_proof_ready and not formula_requires_validation and not formula_repair_required:
            export_readiness["requires_validation"] = []
            export_readiness["repair_required"] = False
            export_readiness["metric_requires_validation"] = False
            export_readiness["metric_repair_required"] = False
            element["active_repair_required"] = False
            element["repair_required"] = False
            element["repair_required_warnings"] = []
            element["active_repair_warnings"] = []

            element["llm_repair"] = _cleared_deterministic_repair_payload(element)
        else:
            export_readiness["metric_requires_validation"] = formula_requires_validation
            export_readiness["metric_repair_required"] = formula_repair_required
            active_warnings = list(element.get("parser_warnings") or [])
            element["active_repair_required"] = formula_repair_required
            element["repair_required"] = formula_repair_required
            element["repair_required_warnings"] = active_warnings
            element["active_repair_warnings"] = active_warnings

        element["export_readiness"] = export_readiness

    return metric_elements


def parser_element_has_active_repair(element: Mapping[str, Any]) -> bool:
    """Return whether a parser element still represents active repair work.

    This is the metrics-facing repair predicate. It runs the same IR/formula
    readiness projection used by export callers, so conservative parser warnings
    remain visible without being counted as active repair after deterministic
    formula resolution. Unresolved numbered or external references remain active.
    """

    rows = parser_elements_for_metrics([element])
    return bool(rows and _metric_row_has_active_repair(rows[0]))


def active_repair_details_from_parser_elements(
    elements: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return active repair-required detail rows after IR readiness projection.

    The raw parser intentionally preserves conservative warnings and historical
    repair payloads for auditability. Metric detail collectors, however, should
    not count a row as active repair work after the IR/formula layer has produced
    an explicit deterministic no-LLM resolution. This helper gives those
    collectors a single source-grounded contract: resolved rows keep their
    warnings, while only still-blocked rows emit repair detail records.
    """

    details: List[Dict[str, Any]] = []
    for element in parser_elements_for_metrics(elements):
        export_readiness = dict(element.get("export_readiness") or {})
        llm_repair = dict(element.get("llm_repair") or {})
        active_warnings = list(element.get("active_repair_warnings") or [])

        if not _metric_row_has_active_repair(element):
            continue

        if not active_warnings:
            active_warnings = list(
                llm_repair.get("reasons")
                or element.get("repair_required_warnings")
                or element.get("parser_warnings")
                or []
            )

        details.append(
            {
                "sample_id": element.get("sample_id") or element.get("_probe_sample_id", ""),
                "source_id": element.get("source_id", ""),
                "canonical_citation": element.get("canonical_citation", ""),
                "text": element.get("text", ""),
                "support_text": element.get("support_text", ""),
                "support_span": element.get("support_span", []),
                "norm_type": element.get("norm_type", ""),
                "modality": element.get("deontic_operator"),
                "subject": list(element.get("subject") or []),
                "action": list(element.get("action") or []),
                "object": element.get("object") or element.get("action_object"),
                "parser_warnings": list(element.get("parser_warnings") or []),
                "active_repair_warnings": active_warnings,
                "llm_repair": llm_repair,
                "deterministic_resolution": export_readiness.get("deterministic_resolution") or {},
            }
        )
    return details


def summarize_active_repair_from_parser_elements(
    elements: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return metric-ready active repair counts after IR readiness projection.

    This helper is intentionally narrow: it reports active deterministic repair
    work, not every conservative parser warning. Formula-resolved rows keep
    their warnings for auditability, while unresolved numbered or external
    references remain active repair details.
    """

    rows = parser_elements_for_metrics(elements)
    details = active_repair_details_from_parser_elements(rows)
    active_source_ids = {str(detail.get("source_id") or "") for detail in details}

    return {
        "element_count": len(rows),
        "repair_required_count": len(details),
        "repair_required_rate": (len(details) / len(rows)) if rows else 0.0,
        "repair_required": [detail["source_id"] for detail in details],
        "repair_required_details": details,
        "active_repair_required_by_source_id": {
            str(row.get("source_id") or ""): str(row.get("source_id") or "") in active_source_ids
            for row in rows
        },
    }


def normalize_repair_required_details_from_parser_elements(
    elements: Iterable[Mapping[str, Any]],
    raw_details: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return active repair details after deterministic IR readiness projection.

    Some metrics pipelines first collect raw parser repair details and only then
    ask export helpers to normalize them. Raw parser details can contain stale
    prompt payloads for rows that are now resolved by the deterministic
    IR/formula layer. This helper keeps that reporting path source-grounded: it
    preserves still-blocked raw detail metadata, but drops rows whose source ID
    is no longer active repair work after formula readiness projection.
    """

    summary = summarize_active_repair_from_parser_elements(elements)
    active_by_source_id = summary["active_repair_required_by_source_id"]
    active_detail_by_source_id = {
        str(detail.get("source_id") or ""): dict(detail)
        for detail in summary["repair_required_details"]
    }

    normalized: List[Dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for raw_detail in raw_details:
        source_id = str(raw_detail.get("source_id") or "")
        if not source_id or active_by_source_id.get(source_id) is not True:
            continue

        detail = dict(raw_detail)
        projected_detail = active_detail_by_source_id.get(source_id, {})
        if projected_detail:
            detail["active_repair_warnings"] = list(
                projected_detail.get("active_repair_warnings") or []
            )
            detail["deterministic_resolution"] = (
                projected_detail.get("deterministic_resolution") or {}
            )
            detail["llm_repair"] = projected_detail.get("llm_repair") or detail.get("llm_repair", {})

        normalized.append(detail)
        seen_source_ids.add(source_id)

    for source_id, projected_detail in active_detail_by_source_id.items():
        if source_id not in seen_source_ids:
            normalized.append(dict(projected_detail))

    return normalized


def normalize_repair_required_evaluation(
    elements: Iterable[Mapping[str, Any]],
    evaluation: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return evaluation metrics with stale repair details removed.

    Some metric runners preserve the raw parser's historical
    ``repair_required`` and ``repair_required_details`` fields even after the
    deterministic IR/formula layer has resolved a row for export. This helper is
    the boundary adapter for that payload shape: it preserves all unrelated
    evaluation metrics, but replaces repair-required accounting with the active
    repair projection used by export and converter callers.

    Unresolved numbered or external references remain active because
    ``summarize_active_repair_from_parser_elements`` only clears rows backed by
    explicit deterministic formula-resolution metadata.
    """

    source_elements = _evaluation_parser_elements(elements, evaluation)
    summary = summarize_active_repair_from_parser_elements(source_elements)
    normalized = dict(evaluation)

    normalized_details = normalize_repair_required_details_from_parser_elements(
        source_elements,
        _evaluation_repair_required_details(evaluation),
    )
    normalized_source_ids = [
        str(detail.get("source_id") or "")
        for detail in normalized_details
        if detail.get("source_id")
    ]

    normalized["repair_required_details"] = normalized_details
    normalized["repair_required"] = normalized_source_ids
    normalized["repair_required_count"] = len(normalized_details)
    normalized["repair_required_rate"] = (
        len(normalized_details) / summary["element_count"]
        if summary["element_count"]
        else 0.0
    )
    normalized["active_repair_required_by_source_id"] = summary[
        "active_repair_required_by_source_id"
    ]

    metrics = evaluation.get("metrics")
    if isinstance(metrics, Mapping):
        normalized_metrics = dict(metrics)
        normalized_metrics["repair_required_count"] = normalized["repair_required_count"]
        normalized_metrics["repair_required_rate"] = normalized["repair_required_rate"]
        normalized_metrics["repair_required"] = list(normalized_source_ids)
        normalized_metrics["repair_required_details"] = [dict(detail) for detail in normalized_details]
        normalized_metrics["active_repair_required_by_source_id"] = dict(summary["active_repair_required_by_source_id"])
        coverage_gaps = normalized_metrics.get("coverage_gaps")
        if isinstance(coverage_gaps, list):
            normalized_metrics["coverage_gaps"] = [
                gap
                for gap in coverage_gaps
                if not str(gap).strip().startswith("repair_required_count:")
            ]
        normalized["metrics"] = normalized_metrics

    return normalized


def _evaluation_parser_elements(
    elements: Iterable[Mapping[str, Any]],
    evaluation: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return parser elements for evaluation repair normalization.

    Some metric runners call ``normalize_repair_required_evaluation`` with an
    empty element list while carrying parser-shaped rows inside ``samples``.
    Without recovering those rows, stale raw repair detail counts survive even
    though the deterministic IR/formula layer can clear the row. Prefer the
    explicit element argument, then fall back to sample rows that already expose
    source-grounded parser fields.
    """

    explicit_elements = [dict(element) for element in elements]
    if explicit_elements:
        return explicit_elements

    recovered: List[Dict[str, Any]] = []
    recovered.extend(
        _parser_context_elements_from_evaluation_document_text(evaluation)
    )
    metrics = evaluation.get("metrics")
    if isinstance(metrics, Mapping):
        recovered.extend(
            _parser_context_elements_from_evaluation_document_text(metrics)
        )

    for sample in _evaluation_samples(evaluation):
        if not isinstance(sample, Mapping):
            continue
        sample_elements = sample.get("elements") or sample.get("parser_elements")
        if isinstance(sample_elements, list):
            recovered.extend(
                dict(element)
                for element in sample_elements
                if isinstance(element, Mapping)
            )
            continue

        context_candidate = _parser_context_element_from_text_only_section_sample(sample)
        if context_candidate and not _sample_has_parser_norm_slots(sample):
            recovered.append(context_candidate)
            continue

        candidate = _parser_element_from_evaluation_sample(sample)
        if candidate:
            recovered.append(candidate)

    for detail in _evaluation_repair_required_details(evaluation):
        if not isinstance(detail, Mapping):
            continue
        llm_repair = detail.get("llm_repair")
        prompt_context = dict(llm_repair.get("prompt_context") or {}) if isinstance(llm_repair, Mapping) else {}
        candidate = _parser_element_from_evaluation_sample(prompt_context)
        candidate = _hydrate_parser_element_from_prompt_context(candidate) if candidate else {}
        if candidate:
            _recover_detail_only_precedence_override_slots(candidate, detail)
            recovered.append(candidate)
            continue

        candidate = _parser_element_from_repair_detail(detail)
        if candidate:
            recovered.append(candidate)

    return _dedupe_evaluation_parser_elements(recovered)


def _evaluation_samples(evaluation: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return parser/context samples from top-level and nested metric payloads.

    Optimizer payloads can carry repair details at the top level while placing
    the reviewed probe samples under ``metrics.samples``. Those samples may be
    context-only section-heading evidence used to resolve same-document
    references, so evaluation recovery must inspect both locations before the
    active repair projection runs.
    """

    samples: List[Mapping[str, Any]] = []
    for container in (evaluation, evaluation.get("metrics")):
        if not isinstance(container, Mapping):
            continue
        for sample in container.get("samples", []) if isinstance(container.get("samples"), list) else []:
            if isinstance(sample, Mapping):
                samples.append(sample)
    return samples


def _evaluation_repair_required_details(evaluation: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return raw repair details from top-level or nested metrics payloads."""

    recovered: List[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add_details(details: Any) -> None:
        if not isinstance(details, list):
            return
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            key = "|".join(
                str(detail.get(field) or "")
                for field in ("source_id", "sample_id", "text")
            )
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            recovered.append(detail)

    details = evaluation.get("repair_required_details")
    add_details(details)

    metrics = evaluation.get("metrics")
    if isinstance(metrics, Mapping):
        add_details(metrics.get("repair_required_details"))

    return recovered


def _dedupe_evaluation_parser_elements(elements: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return recovered evaluation parser rows without losing context rows.

    Evaluation payloads can split same-document evidence across ``samples`` and
    ``repair_required_details``: the sample row may carry section 552 context,
    while the repair detail carries the blocked exception row.  Keep both rows
    so batch IR reference resolution can prove the citation, but avoid duplicate
    rows when the same source appears in both payload sections.
    """

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for element in elements:
        row = dict(element)
        source_id = str(row.get("source_id") or "")
        key = source_id or "|".join(
            str(row.get(field) or "")
            for field in ("canonical_citation", "text", "support_text")
        )
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(row)
    return deduped


def _parser_element_from_repair_detail(detail: Mapping[str, Any]) -> Dict[str, Any]:
    """Recover parser evidence from a raw repair detail row.

    Some stalled metric payloads preserve only ``repair_required_details`` and
    omit the original parser rows plus the richer repair prompt context. The
    detail rows are still source-grounded: they carry source text, source ID,
    norm type, parser warnings, actor, and action. Recover only that narrow
    shape and infer the deontic operator from the audited warning pattern plus
    norm type so existing IR/formula readiness can decide whether repair is
    still active. Numbered-reference exceptions remain blocked because their
    cross-reference warning is preserved without resolution evidence.
    """

    candidate = _hydrate_parser_element_from_prompt_context(
        _parser_element_from_evaluation_sample(detail)
    )
    if not candidate:
        return {}

    if candidate.get("deontic_operator"):
        _recover_detail_only_precedence_override_slots(candidate, detail)
        return candidate

    inferred_operator = _infer_detail_deontic_operator(detail)
    if not inferred_operator:
        return {}

    candidate["deontic_operator"] = inferred_operator
    _recover_detail_only_precedence_override_slots(candidate, detail)
    return candidate


def _recover_detail_only_precedence_override_slots(
    candidate: Dict[str, Any],
    detail: Mapping[str, Any],
) -> None:
    """Recover narrow precedence-only override provenance from detail text.

    Metric payloads can contain raw repair detail rows without prompt_context or
    structured override/cross-reference slots.  For the concrete stalled probe,
    the source text itself carries all provenance needed by the existing
    pure-precedence override formula resolution.  Reconstruct only that exact
    shape; mixed warnings, missing actor/action, or non-``notwithstanding
    section ...`` text remain conservative.
    """

    warnings = set(str(warning) for warning in candidate.get("parser_warnings") or [])
    if candidate.get("norm_type") != "permission" or candidate.get("deontic_operator") != "P":
        return
    if warnings != {"cross_reference_requires_resolution", "override_clause_requires_precedence_review"}:
        return
    if candidate.get("override_clause_details") or candidate.get("cross_reference_details"):
        return
    if not candidate.get("subject") or not candidate.get("action"):
        return

    text = str(
        detail.get("text")
        or detail.get("source_text")
        or candidate.get("text")
        or ""
    ).strip()
    if not text:
        return

    match = re.search(
        r"\bnotwithstanding\s+"
        r"(section\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*))"
        r"\s*,\s*(?:the\s+)?(.+?)\s+may\s+(.+?)(?:[.;:]|$)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return

    reference_text = match.group(1)
    section_value = match.group(2)
    reference_span = [match.start(1), match.end(1)]
    override_record = {
        "type": "notwithstanding",
        "value": reference_text,
        "raw_text": reference_text,
        "normalized_text": reference_text.lower(),
        "span": reference_span,
        "clause_span": [match.start(), match.end(1)],
    }
    reference_record = {
        "type": "section",
        "reference_type": "section",
        "value": section_value,
        "target": section_value,
        "raw_text": reference_text,
        "normalized_text": reference_text.lower(),
        "canonical_citation": f"section {section_value.lower()}",
        "span": reference_span,
    }

    candidate["override_clause_details"] = [override_record]
    candidate["cross_reference_details"] = [reference_record]


def _infer_detail_deontic_operator(detail: Mapping[str, Any]) -> str:
    norm_type = str(detail.get("norm_type") or "").strip().lower()
    warnings = set(str(warning) for warning in detail.get("parser_warnings") or [])

    if norm_type == "applicability" and warnings == {"cross_reference_requires_resolution"}:
        return "APP"
    if norm_type == "permission" and warnings == {
        "cross_reference_requires_resolution",
        "override_clause_requires_precedence_review",
    }:
        return "P"
    if norm_type == "obligation" and "exception_requires_scope_review" in warnings:
        return "O"
    if norm_type == "prohibition" and "exception_requires_scope_review" in warnings:
        return "F"
    return ""


def _raw_repair_details(evaluation: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    details = evaluation.get("repair_required_details", [])
    return [detail for detail in details if isinstance(detail, Mapping)] if isinstance(details, list) else []


def _detail_records_from_sample(
    sample: Mapping[str, Any],
    detail_key: str,
    legacy_key: str,
) -> List[Any]:
    """Return rich slot records from recovered metric payloads when present.

    Raw repair prompt contexts historically place dict-shaped records under
    legacy keys such as ``exceptions`` and ``cross_references``. Passing those
    through as legacy string lists causes the IR bridge to stringify the dicts,
    which hides deterministic formula resolutions for otherwise source-grounded
    rows. Prefer explicit detail fields, then promote dict-shaped legacy values
    to detail records while leaving plain strings on the legacy list.
    """

    detail_values = sample.get(detail_key)
    if isinstance(detail_values, list) and detail_values:
        return list(detail_values)

    legacy_values = sample.get(legacy_key)
    if not isinstance(legacy_values, list):
        return []
    return [dict(value) for value in legacy_values if isinstance(value, Mapping)]


def _hydrate_parser_element_from_prompt_context(element: Mapping[str, Any]) -> Dict[str, Any]:
    """Fill absent parser slots from deterministic repair prompt context.

    Metric payloads may carry a detail-only parser row at the top level and the
    richer source-grounded parser slots inside ``llm_repair.prompt_context``.
    Those prompt-context slots were emitted by the deterministic parser before
    the row entered the optional repair lane, so metrics can safely use them as
    parser evidence.  Hydration is deliberately fill-only: explicit caller slots
    win, and unresolved reference warnings still flow through the normal IR and
    formula readiness gates.
    """

    hydrated = dict(element)
    llm_repair = hydrated.get("llm_repair")
    if not isinstance(llm_repair, Mapping):
        return hydrated

    prompt_context = llm_repair.get("prompt_context")
    if not isinstance(prompt_context, Mapping):
        return hydrated

    prompt = dict(prompt_context)

    _fill_empty_field(hydrated, prompt, "schema_version")
    _fill_empty_field(hydrated, prompt, "source_id")
    _fill_empty_field(hydrated, prompt, "canonical_citation")
    _fill_empty_field(hydrated, prompt, "support_text")
    _fill_empty_field(hydrated, prompt, "support_span")
    _fill_empty_field(hydrated, prompt, "source_span")
    _fill_empty_field(hydrated, prompt, "field_spans")
    _fill_empty_field(hydrated, prompt, "norm_type")
    _fill_empty_field(hydrated, prompt, "deontic_operator")
    if not hydrated.get("deontic_operator") and prompt.get("modality"):
        hydrated["deontic_operator"] = prompt.get("modality")
    if not hydrated.get("text"):
        hydrated["text"] = prompt.get("text") or prompt.get("source_text") or ""

    for key in ("subject", "action", "parser_warnings"):
        if not hydrated.get(key):
            hydrated[key] = _list_field(prompt.get(key))

    _hydrate_slot_records(hydrated, prompt, "conditions", "condition_details")
    _hydrate_slot_records(hydrated, prompt, "exceptions", "exception_details")
    _hydrate_slot_records(hydrated, prompt, "override_clauses", "override_clause_details")
    _hydrate_slot_records(hydrated, prompt, "cross_references", "cross_reference_details")

    for key in (
        "resolved_cross_references",
        "enforcement_links",
        "conflict_links",
        "defined_term_refs",
        "ontology_terms",
        "kg_relationship_hints",
    ):
        if not hydrated.get(key) and isinstance(prompt.get(key), list):
            hydrated[key] = list(prompt.get(key) or [])

    for key in ("legal_frame", "formal_terms", "section_context", "export_readiness"):
        if not hydrated.get(key) and isinstance(prompt.get(key), Mapping):
            hydrated[key] = dict(prompt.get(key) or {})

    return hydrated


def _fill_empty_field(target: Dict[str, Any], source: Mapping[str, Any], key: str) -> None:
    if target.get(key) not in (None, "", [], {}):
        return
    value = source.get(key)
    if value not in (None, "", [], {}):
        if isinstance(value, Mapping):
            target[key] = dict(value)
        elif isinstance(value, list):
            target[key] = list(value)
        else:
            target[key] = value


def _hydrate_slot_records(
    target: Dict[str, Any],
    source: Mapping[str, Any],
    legacy_key: str,
    detail_key: str,
) -> None:
    if not target.get(detail_key):
        detail_records = _detail_records_from_sample(source, detail_key, legacy_key)
        if detail_records:
            target[detail_key] = detail_records
    if not target.get(legacy_key):
        legacy_values = _legacy_text_values_from_sample(source, legacy_key)
        if legacy_values:
            target[legacy_key] = legacy_values


def _legacy_text_values_from_sample(sample: Mapping[str, Any], key: str) -> List[Any]:
    values = sample.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if not isinstance(value, Mapping)]


def _parser_element_from_evaluation_sample(sample: Mapping[str, Any]) -> Dict[str, Any]:
    """Recover a minimal parser element from a metric sample row when present."""

    required = {"source_id", "text", "norm_type", "deontic_operator", "subject", "action"}
    if not any(key in sample for key in required):
        return {}

    return {
        "schema_version": sample.get("schema_version", ""),
        "source_id": sample.get("source_id", ""),
        "canonical_citation": sample.get("canonical_citation", ""),
        "sample_id": sample.get("sample_id", ""),
        "text": sample.get("text", sample.get("source_text", "")),
        "support_text": sample.get("support_text", sample.get("text", sample.get("source_text", ""))),
        "support_span": list(sample.get("support_span") or sample.get("source_span") or []),
        "source_span": list(sample.get("source_span") or sample.get("support_span") or []),
        "field_spans": dict(sample.get("field_spans") or {}),
        "norm_type": sample.get("norm_type", ""),
        "deontic_operator": sample.get("deontic_operator") or sample.get("modality") or "",
        "subject": _list_field(sample.get("subject")),
        "action": _list_field(sample.get("action")),
        "conditions": _legacy_text_values_from_sample(sample, "conditions"),
        "condition_details": _detail_records_from_sample(sample, "condition_details", "conditions"),
        "exceptions": _legacy_text_values_from_sample(sample, "exceptions"),
        "exception_details": _detail_records_from_sample(sample, "exception_details", "exceptions"),
        "override_clauses": _legacy_text_values_from_sample(sample, "override_clauses"),
        "override_clause_details": _detail_records_from_sample(sample, "override_clause_details", "override_clauses"),
        "cross_references": _legacy_text_values_from_sample(sample, "cross_references"),
        "cross_reference_details": _detail_records_from_sample(sample, "cross_reference_details", "cross_references"),
        "resolved_cross_references": list(sample.get("resolved_cross_references") or []),
        "parser_warnings": list(sample.get("parser_warnings") or []),
        "llm_repair": dict(sample.get("llm_repair") or {}),
        "export_readiness": dict(sample.get("export_readiness") or {}),
        "promotable_to_theorem": bool(sample.get("promotable_to_theorem")),
    }


def _sample_has_parser_norm_slots(sample: Mapping[str, Any]) -> bool:
    return any(
        key in sample
        for key in ("norm_type", "deontic_operator", "modality", "subject", "action")
    )


def _parser_context_element_from_text_only_section_sample(sample: Mapping[str, Any]) -> Dict[str, Any]:
    """Recover same-document section context from text-only evaluation samples.

    Metric payloads may include a cited section as a sample with only raw text,
    while the active repair detail carries the parser-shaped reference row.  The
    text-only sample is not itself a norm and must not become a repair metric
    denominator, but it is source-grounded evidence that a numbered reference is
    resolvable in the same evaluation batch.
    """

    text = str(sample.get("text") or sample.get("source_text") or "").strip()
    if not text:
        return {}

    citation = ""
    for key in ("canonical_citation", "citation", "section_citation"):
        citation = _canonical_section_citation(str(sample.get(key) or ""))
        if citation:
            break
    if not citation:
        citations = _section_citations_from_text(text)
        citation = citations[0] if citations else ""
    if not citation:
        return {}

    section = citation[len("section ") :]
    source_id = str(sample.get("source_id") or "").strip()
    if not source_id:
        source_id = _stable_id("context", str(sample.get("sample_id") or ""), citation, text)

    return {
        "schema_version": str(sample.get("schema_version") or ""),
        "source_id": source_id,
        "canonical_citation": citation,
        "sample_id": sample.get("sample_id", ""),
        "text": text,
        "support_text": text,
        "support_span": [0, len(text)],
        "source_span": [0, len(text)],
        "field_spans": {},
        "norm_type": "document_context",
        "deontic_operator": "",
        "subject": [],
        "action": [],
        "section_context": {"section": section, "canonical_citation": citation},
        "parser_warnings": [],
        "llm_repair": {"required": False, "reasons": []},
        "export_readiness": {},
        "promotable_to_theorem": False,
        "context_only": True,
        "extraction_method": "evaluation_text_section_context",
    }


def _list_field(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if value:
        return [value]
    return []


def _is_context_only_parser_element(element: Mapping[str, Any]) -> bool:
    if element.get("context_only") is True:
        return True
    if element.get("_context_only") is True:
        return True

    norm_type = str(element.get("norm_type") or "").strip().lower()
    if not norm_type and element.get("document_text") and not _sample_has_parser_norm_slots(element):
        return True
    if norm_type not in {"document_context", "section_context"}:
        return False
    return not _list_field(element.get("subject")) and not _list_field(element.get("action"))


def _parser_context_elements_from_evaluation_document_text(
    evaluation: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Recover section context from explicit document-level evaluation text.

    Repair details for numbered exceptions can clear only with same-document
    evidence. Some metric payloads carry that evidence as whole-document text
    rather than as a parser sample row. Treat only explicit document/context
    fields with section headings as context; do not infer context from the
    repair clause text itself.
    """

    texts: List[tuple[str, str]] = []
    for key in ("document_text", "full_document_text", "context_text"):
        value = evaluation.get(key)
        if isinstance(value, str) and value.strip():
            texts.append((key, value.strip()))

    for key in ("document", "context"):
        value = evaluation.get(key)
        if not isinstance(value, Mapping):
            continue
        text = value.get("text") or value.get("document_text") or value.get("source_text")
        if isinstance(text, str) and text.strip():
            texts.append((key, text.strip()))

    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for key, text in texts:
        for match in _SECTION_HEADING_RE.finditer(text):
            citation = _canonical_section_citation(f"section {match.group(1)}")
            if not citation or citation in seen:
                continue
            section = citation[len("section ") :]
            source_id = _stable_id("context", key, citation, text)
            records.append(
                {
                    "schema_version": "",
                    "source_id": source_id,
                    "canonical_citation": citation,
                    "sample_id": key,
                    "text": text,
                    "support_text": text,
                    "support_span": [0, len(text)],
                    "source_span": [0, len(text)],
                    "field_spans": {},
                    "norm_type": "document_context",
                    "deontic_operator": "",
                    "subject": [],
                    "action": [],
                    "section_context": {"section": section, "canonical_citation": citation},
                    "parser_warnings": [],
                    "llm_repair": {"required": False, "reasons": []},
                    "export_readiness": {},
                    "promotable_to_theorem": False,
                    "context_only": True,
                    "extraction_method": "evaluation_document_text_section_context",
                }
            )
            seen.add(citation)
    return records


def _metric_row_has_active_repair(element: Mapping[str, Any]) -> bool:
    """Return active repair status for an already metrics-projected row."""

    export_readiness = dict(element.get("export_readiness") or {})

    metric_repair_required = export_readiness.get("metric_repair_required")
    if metric_repair_required is not None:
        return metric_repair_required is True

    formula_repair_required = export_readiness.get("formula_repair_required")
    if formula_repair_required is not None:
        return formula_repair_required is True

    export_repair_required = export_readiness.get("export_repair_required")
    if export_repair_required is not None:
        return export_repair_required is True

    llm_repair = dict(element.get("llm_repair") or {})
    active_warnings = element.get("active_repair_warnings") or element.get("repair_required_warnings") or []
    return llm_repair.get("required") is True or bool(active_warnings)


def _has_inactive_deterministic_repair_projection(element: Mapping[str, Any]) -> bool:
    """Return whether a row already carries explicit inactive repair status.

    Some metrics pipelines call projection helpers more than once. A row that
    was already cleared by deterministic formula readiness, especially a
    same-document reference exception, should not become active repair again
    merely because the second pass lacks the original batch context.
    """

    export_readiness = dict(element.get("export_readiness") or {})
    llm_repair = dict(element.get("llm_repair") or {})
    deterministic_resolution = (
        export_readiness.get("deterministic_resolution")
        or llm_repair.get("deterministic_resolution")
        or {}
    )
    if not deterministic_resolution:
        return False
    if element.get("active_repair_required") is False or element.get("repair_required") is False:
        return True
    return llm_repair.get("required") is False and llm_repair.get("deterministically_resolved") is True


def _cleared_deterministic_repair_payload(element: Mapping[str, Any]) -> Dict[str, Any]:
    """Return an inactive repair payload for deterministically resolved rows.

    Some reporting paths inspect more than the boolean ``required`` flag and
    treat lingering ``reasons`` or prompt context as active repair work. Once
    the IR/formula layer has produced an explicit deterministic resolution, the
    metrics-facing row should expose an auditable inactive repair marker rather
    than a stale llm_router prompt.
    """

    repair = dict(element.get("llm_repair") or {})
    export_readiness = dict(element.get("export_readiness") or {})
    deterministic_resolution = export_readiness.get("deterministic_resolution") or {}

    repair["required"] = False
    repair["allow_llm_repair"] = False
    repair["reasons"] = []
    repair["prompt_context"] = {}
    repair["prompt_hash"] = ""
    repair["suggested_router"] = ""
    repair["deterministically_resolved"] = True
    repair["deterministic_resolution"] = deterministic_resolution
    return repair


def parser_elements_with_ir_export_readiness(
    elements: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return parser elements annotated with deterministic export readiness.

    Parser elements intentionally keep their original theorem-promotion gate:
    ``promotable_to_theorem`` still reflects the conservative parser decision.
    Export and metrics callers also need to know when a blocked parser warning
    has already been resolved by the typed IR/formula layer, so the repair lane
    does not stay noisy for source-grounded deterministic resolutions.

    This helper projects formula-record readiness back onto copied parser
    dictionaries. It never calls an LLM and never clears unresolved numbered or
    external references unless the formula record has an explicit deterministic
    resolution.
    """

    copied_elements = [dict(element) for element in elements]
    norms = [LegalNormIR.from_parser_element(element) for element in copied_elements]
    resolved_norms = _with_same_document_reference_resolutions(norms)
    formula_records = build_deontic_formula_records_from_irs(resolved_norms)

    aligned: List[Dict[str, Any]] = []
    for copied, resolved_norm, formula_record in zip(copied_elements, resolved_norms, formula_records):
        deterministic_resolution = formula_record.get("deterministic_resolution") or {}
        formula_requires_validation = bool(formula_record.get("requires_validation"))
        formula_repair_required = bool(formula_record.get("repair_required"))

        export_readiness = dict(copied.get("export_readiness") or {})
        export_readiness["parser_proof_ready"] = bool(copied.get("promotable_to_theorem"))
        export_readiness["formula_proof_ready"] = bool(formula_record.get("proof_ready"))
        export_readiness["proof_ready"] = bool(formula_record.get("proof_ready"))
        export_readiness["formula_requires_validation"] = formula_requires_validation
        export_readiness["formula_repair_required"] = formula_repair_required
        export_readiness["export_requires_validation"] = formula_requires_validation
        export_readiness["export_repair_required"] = formula_repair_required
        export_readiness["formula_blockers"] = list(formula_record.get("blockers") or [])

        if deterministic_resolution.get("type") == "pure_precedence_override":
            precedence_references = _precedence_override_reference_records(resolved_norm)
            if precedence_references:
                copied["resolved_cross_references"] = precedence_references
                copied["cross_reference_details"] = precedence_references

        # Legacy parser elements use list-shaped requires_validation values such
        # as ["llm_router_repair"] for parquet/backward-compatible callers.
        # Preserve that field shape and publish IR/formula readiness in explicit
        # formula_* and export_* fields instead. Elements constructed outside the
        # parser may still use a boolean field, so keep supporting that shape.
        if not isinstance(export_readiness.get("requires_validation"), list):
            export_readiness["requires_validation"] = formula_requires_validation
        if not isinstance(export_readiness.get("repair_required"), list):
            export_readiness["repair_required"] = formula_repair_required
        export_readiness["deterministic_resolution"] = deterministic_resolution
        copied["export_readiness"] = export_readiness

        if deterministic_resolution and formula_record.get("repair_required") is False:
            llm_repair = dict(copied.get("llm_repair") or {})
            llm_repair["required"] = False
            llm_repair["allow_llm_repair"] = False
            llm_repair["deterministically_resolved"] = True
            llm_repair["deterministic_resolution"] = deterministic_resolution
            llm_repair["reasons"] = [
                reason
                for reason in llm_repair.get("reasons", [])
                if reason not in set(formula_record.get("blockers") or [])
            ]
            copied["llm_repair"] = llm_repair
            projected_references = _project_parser_resolved_cross_references(
                copied.get("resolved_cross_references", []),
                resolved_norm.resolved_cross_references,
            )
            projected_references = _extend_unique_references(
                projected_references,
                _local_scope_parser_resolved_cross_references(copied, deterministic_resolution),
            )
            copied["resolved_cross_references"] = projected_references
            _clear_parser_exception_repair_if_formula_resolved(copied, deterministic_resolution)
            _project_formula_resolved_metric_readiness(copied, deterministic_resolution)

        aligned.append(copied)
    return aligned


def _project_parser_resolved_cross_references(
    original_references: Any,
    resolved_references: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return parser-shaped resolved references after IR same-document repair.

    Parser elements can carry stale unresolved records even after the IR batch
    has resolved the cited section from same-document context. Metrics and
    converter callers inspect these copied parser dictionaries directly, so
    project only explicit same-document resolutions back while preserving any
    non-stale existing resolved records.
    """

    projected: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for reference in original_references if isinstance(original_references, list) else []:
        if not isinstance(reference, dict):
            continue
        if reference.get("resolution_status") == "unresolved" or reference.get("target_exists") is False:
            continue
        key = _reference_provenance_key(_normalized_reference_record(reference))
        if key and key not in seen:
            projected.append(dict(reference))
            seen.add(key)

    for reference in resolved_references:
        if not isinstance(reference, Mapping):
            continue
        if not _is_same_document_resolved_reference(reference):
            continue
        normalized = _normalized_reference_record(reference)
        key = _reference_provenance_key(normalized)
        if key and key not in seen:
            normalized["resolved"] = True
            normalized["resolution_status"] = "resolved"
            normalized["target_exists"] = True
            projected.append(normalized)
            seen.add(key)

    return projected


def _extend_unique_references(
    references: Sequence[Mapping[str, Any]],
    additions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Append reference records without duplicating canonical/local keys."""

    projected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for reference in list(references) + list(additions):
        if not isinstance(reference, Mapping):
            continue
        normalized = dict(reference)
        key = _reference_provenance_key(normalized)
        if key and key in seen:
            continue
        projected.append(normalized)
        if key:
            seen.add(key)
    return projected


def _local_scope_parser_resolved_cross_references(
    element: Mapping[str, Any],
    deterministic_resolution: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return parser-facing resolved records for local self-scope repairs.

    Formula records can deterministically resolve clauses such as ``This section
    applies to ...`` because the reference is to the current local scope. Metrics
    and converter callers inspect copied parser dictionaries directly, so expose
    that same source-grounded local resolution without relaxing parser theorem
    promotion or resolving numbered/external references.
    """

    if deterministic_resolution.get("type") not in {
        "local_scope_applicability",
        "local_scope_reference_condition",
        "local_scope_reference_exception",
    }:
        return []

    resolved: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("cross_reference_details", "cross_references", "resolved_cross_references"):
        values = element.get(key)
        if not isinstance(values, list):
            continue
        for reference in values:
            if not isinstance(reference, Mapping):
                continue
            if not _is_local_scope_reference_record(reference):
                continue
            normalized = _normalized_reference_record(reference)
            normalized["target"] = normalized.get("target") or _local_scope_reference_target(reference)
            normalized["resolved"] = True
            normalized["same_document"] = True
            normalized["resolution_scope"] = "local_self"
            normalized["resolution_status"] = "resolved"
            normalized["target_exists"] = True
            provenance_key = _reference_provenance_key(normalized)
            if provenance_key and provenance_key in seen:
                continue
            resolved.append(normalized)
            if provenance_key:
                seen.add(provenance_key)
    return resolved


def _local_scope_reference_target(reference: Mapping[str, Any]) -> str:
    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    if reference_type not in {"section", "subsection", "chapter", "title", "article", "part"}:
        return ""

    for key in ("target", "section", "subsection"):
        value = str(reference.get(key) or "").strip().lower()
        if value in {"this", "current"}:
            return value
    for key in ("value", "normalized_text", "raw_text", "text", "canonical_citation", "citation"):
        text = str(reference.get(key) or "").strip().lower()
        if text in {f"this {reference_type}", f"current {reference_type}"}:
            return text.split()[0]
    return ""


def _clear_parser_exception_repair_if_formula_resolved(
    element: Dict[str, Any],
    deterministic_resolution: Mapping[str, Any],
) -> None:
    """Clear stale exception repair metadata for formula-resolved exceptions.

    Parser theorem promotion remains conservative, but metrics and converter
    callers should not count a standard substantive exception as requiring LLM
    repair once the formula layer has represented it as a negated antecedent.
    Reference exceptions are intentionally excluded because they require source
    resolution provenance before repair can be cleared.
    """

    if deterministic_resolution.get("type") != "standard_substantive_exception":
        return

    llm_repair = dict(element.get("llm_repair") or {})
    reasons = [
        reason
        for reason in llm_repair.get("reasons", [])
        if reason != "exception_requires_scope_review"
    ]
    llm_repair["required"] = bool(reasons)
    llm_repair["allow_llm_repair"] = False
    llm_repair["reasons"] = reasons
    llm_repair["deterministically_resolved"] = True
    llm_repair["deterministic_resolution"] = dict(deterministic_resolution)
    element["llm_repair"] = llm_repair


def _project_formula_resolved_metric_readiness(
    element: Dict[str, Any],
    deterministic_resolution: Mapping[str, Any],
) -> None:
    """Expose inactive repair status for formula-resolved parser rows.

    Parser warnings remain audit metadata. Metric collectors that inspect copied
    parser dictionaries directly should see the same active-repair decision as
    the IR/formula exporter: a single substantive exception represented as a
    negated antecedent is resolved, while numbered or external references stay
    blocked because they have no source-grounded target.
    """

    if deterministic_resolution.get("type") not in {
        "standard_substantive_exception",
        "local_scope_applicability",
        "local_scope_reference_exception",
        "local_scope_reference_condition",
        "pure_precedence_override",
        "resolved_same_document_reference_exception",
        "resolved_same_document_reference_condition",
    }:
        return

    export_readiness = dict(element.get("export_readiness") or {})
    export_readiness["metric_requires_validation"] = False
    export_readiness["metric_repair_required"] = False
    element["export_readiness"] = export_readiness
    element["active_repair_warnings"] = []
    element["repair_required_warnings"] = []


def parser_elements_to_ir_aligned_export_tables(
    elements: Iterable[Mapping[str, Any]],
    legacy_tables: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return IR-owned export rows while preserving legacy auxiliary tables.

    Core table rows may already have parquet-facing legacy fields that are not
    owned by the typed IR exporter yet, such as ``logic_frame`` and
    ``legal_frame`` on canonical rows.  Preserve those fields by source ID while
    letting IR-derived proof, validation, and repair status take precedence.

    The deterministic parser still has legacy table builders for KG triples,
    clause records, references, procedures, sanctions, and ontology entities.
    Core proof/repair status now lives in the typed IR exporter. This helper is
    the narrow migration bridge: it replaces only the IR-owned core tables and
    carries every non-core legacy table forward unchanged.
    """

    aligned_elements = parser_elements_with_ir_export_readiness(elements)
    ir_tables = parser_elements_to_export_tables(aligned_elements)
    merged: Dict[str, List[Dict[str, Any]]] = {
        name: [dict(row) for row in rows]
        for name, rows in ir_tables.items()
    }
    if not legacy_tables:
        return merged

    for table_name in EXPORT_TABLE_SPECS:
        if table_name not in merged:
            continue
        legacy_rows = legacy_tables.get(table_name, [])
        if not legacy_rows:
            continue
        merged[table_name] = _merge_legacy_core_rows(
            table_name,
            merged[table_name],
            legacy_rows,
        )

    for table_name, rows in legacy_tables.items():
        if table_name in EXPORT_TABLE_SPECS:
            continue
        merged[table_name] = [dict(row) for row in rows]
    return merged


def _merge_legacy_core_rows(
    table_name: str,
    ir_rows: Sequence[Mapping[str, Any]],
    legacy_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Preserve legacy-only core fields without reintroducing stale repair rows."""

    if table_name == "repair_queue":
        return _merge_repair_queue_rows(ir_rows, legacy_rows)

    legacy_by_source_id: Dict[str, Dict[str, Any]] = {}
    for row in legacy_rows:
        source_id = str(row.get("source_id") or "")
        if source_id and source_id not in legacy_by_source_id:
            legacy_by_source_id[source_id] = dict(row)

    merged_rows: List[Dict[str, Any]] = []
    for ir_row in ir_rows:
        source_id = str(ir_row.get("source_id") or "")
        merged_row = dict(legacy_by_source_id.get(source_id, {}))
        merged_row.update(dict(ir_row))
        merged_rows.append(merged_row)
    return merged_rows


def _merge_repair_queue_rows(
    ir_rows: Sequence[Mapping[str, Any]],
    legacy_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep only repair rows that remain blocked under IR formula readiness."""

    ir_by_source_id = {
        str(row.get("source_id") or ""): dict(row)
        for row in ir_rows
        if row.get("source_id")
    }
    merged_rows: List[Dict[str, Any]] = []
    seen_source_ids: set[str] = set()

    for ir_row in ir_rows:
        source_id = str(ir_row.get("source_id") or "")
        legacy_row = next(
            (dict(row) for row in legacy_rows if str(row.get("source_id") or "") == source_id),
            {},
        )
        merged_row = legacy_row
        merged_row.update(dict(ir_row))
        merged_rows.append(merged_row)
        seen_source_ids.add(source_id)

    for legacy_row in legacy_rows:
        source_id = str(legacy_row.get("source_id") or "")
        if source_id and source_id in seen_source_ids:
            continue
        if source_id and source_id not in ir_by_source_id:
            continue
        merged_rows.append(dict(legacy_row))
    return merged_rows


def validate_export_tables(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    """Validate primary keys and source IDs for IR-derived export tables."""

    errors: List[Dict[str, Any]] = []
    seen_keys: Dict[str, set] = {}

    for table_name, spec in EXPORT_TABLE_SPECS.items():
        rows = list(tables.get(table_name, []))
        primary_key = spec["primary_key"]
        seen_keys[table_name] = set()
        for index, row in enumerate(rows):
            key_value = row.get(primary_key)
            if not key_value:
                errors.append(
                    {
                        "table": table_name,
                        "row_index": index,
                        "field": primary_key,
                        "message": "missing primary key",
                    }
                )
            elif key_value in seen_keys[table_name]:
                errors.append(
                    {
                        "table": table_name,
                        "row_index": index,
                        "field": primary_key,
                        "message": "duplicate primary key",
                    }
                )
            else:
                seen_keys[table_name].add(key_value)

            if spec.get("requires_source_id") and not row.get("source_id"):
                errors.append(
                    {
                        "table": table_name,
                        "row_index": index,
                        "field": "source_id",
                        "message": "missing source_id",
                    }
                )

    return {"valid": not errors, "errors": errors}


def _canonical_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    formula_record = build_deontic_formula_record_from_ir(norm)
    parser_proof_ready = norm.proof_ready
    reference_provenance = _cross_reference_provenance_from_ir(norm)
    row = {
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "text": norm.source_text,
        "support_text": norm.support_text,
        "source_span": norm.source_span.to_list(),
        "support_span": norm.support_span.to_list(),
        "norm_type": norm.norm_type,
        "modality": norm.modality,
        "actor": norm.actor,
        "action": norm.action,
        "definition_scope": dict(norm.definition_scope),
        "quality_label": norm.quality.quality_label,
        "proof_ready": bool(formula_record["proof_ready"]),
        "parser_proof_ready": parser_proof_ready,
        "requires_validation": bool(formula_record["requires_validation"]),
        "repair_required": bool(formula_record["repair_required"]),
        "export_proof_ready": bool(formula_record["proof_ready"]),
        "export_repair_required": bool(formula_record["repair_required"]),
        "blockers": list(norm.blockers),
        "parser_warnings": list(norm.quality.parser_warnings),
        "deterministic_resolution": formula_record["deterministic_resolution"],
        "schema_version": norm.schema_version,
    }
    row.update(reference_provenance)
    return row


def _with_same_document_reference_resolutions(norms: List[LegalNormIR]) -> List[LegalNormIR]:
    """Resolve exact section references against norms in the same export batch.

    This is deliberately narrow: it only marks a reference same-document when
    the cited section has a matching canonical citation in the current batch.
    Absent references and externally scoped references remain blocked by the
    formula builder's existing repair gates.
    """

    section_index = _same_document_section_index(norms)
    if not section_index:
        return norms

    return [
        _resolve_norm_same_document_references(norm, section_index)
        for norm in norms
    ]


def _same_document_section_index(norms: Sequence[LegalNormIR]) -> Dict[str, str]:
    section_index: Dict[str, str] = {}
    for norm in norms:
        citation = _canonical_section_citation(norm.canonical_citation)
        if citation and norm.source_id:
            section_index.setdefault(citation, norm.source_id)
        for citation in _section_context_citations(norm):
            if citation and norm.source_id:
                section_index.setdefault(citation, norm.source_id)
    return section_index


def _resolve_norm_same_document_references(
    norm: LegalNormIR,
    section_index: Mapping[str, str],
) -> LegalNormIR:
    additions: List[Dict[str, Any]] = []
    existing = {
        _canonical_section_citation(str(item.get("canonical_citation") or item.get("value") or ""))
        for item in norm.resolved_cross_references
        if isinstance(item, dict)
    }

    for reference in norm.cross_references:
        if not isinstance(reference, dict):
            continue
        if _reference_is_external(reference):
            continue

        citations = _reference_section_citations(reference)
        if not citations or any(citation not in section_index for citation in citations):
            continue

        for citation in citations:
            if citation in existing:
                continue
            additions.append(
                {
                    "reference_type": "section",
                    "target": citation[len("section ") :],
                    "canonical_citation": citation,
                    "value": citation,
                    "resolution_scope": "same_document",
                    "same_document": True,
                    "resolved_source_id": section_index[citation],
                    "source_id": section_index[citation],
                    "span": reference.get("span", []),
                }
            )
            existing.add(citation)

    if not additions:
        return norm
    return replace(
        norm,
        resolved_cross_references=list(norm.resolved_cross_references) + additions,
    )


def _reference_section_citation(reference: Mapping[str, Any]) -> str:
    citations = _reference_section_citations(reference)
    return citations[0] if citations else ""


def _reference_section_citations(reference: Mapping[str, Any]) -> List[str]:
    citations: List[str] = []

    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        for citation in _section_citations_from_text(str(reference.get(key) or "")):
            if citation not in citations:
                citations.append(citation)

    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    target = str(reference.get("target") or reference.get("section") or "").strip()
    if reference_type == "section" and target and target.lower() not in {"this", "current"}:
        for citation in _section_citations_from_text(f"section {target}"):
            if citation not in citations:
                citations.append(citation)
    return citations


def _canonical_section_citation(text: str) -> str:
    citations = _section_citations_from_text(text)
    return citations[0] if citations else ""


def _section_citations_from_text(text: str) -> List[str]:
    value = str(text or "")
    citations: List[str] = []

    for match in _SECTION_REFERENCE_RE.finditer(value):
        citation = f"section {match.group(1).lower()}"
        if citation not in citations:
            citations.append(citation)

    for match in _SECTION_REFERENCE_LIST_RE.finditer(value):
        for token in _SECTION_REFERENCE_TOKEN_RE.findall(match.group(1)):
            citation = f"section {token.lower()}"
            if citation not in citations:
                citations.append(citation)

    return citations


def _section_context_citations(norm: LegalNormIR) -> List[str]:
    """Return exact numbered section citations carried by parser context.

    Export batch resolution has document context, so a section present only in
    parser ``section_context`` can resolve a matching numbered same-document
    reference. Unnumbered local self-references and absent context remain
    blocked by the formula/export repair gates.
    """

    context = norm.section_context
    if not isinstance(context, dict):
        return []

    citations: List[str] = []
    for key in (
        "canonical_citation",
        "citation",
        "section_citation",
        "current_section_citation",
    ):
        citation = _canonical_section_citation(str(context.get(key) or ""))
        if citation and citation not in citations:
            citations.append(citation)

    for key in ("section", "section_number", "current_section", "current_section_number"):
        value = str(context.get(key) or "").strip()
        if not value or value.lower() in {"this", "current"}:
            continue
        citation = _canonical_section_citation(f"section {value}")
        if citation and citation not in citations:
            citations.append(citation)

    return citations


def _reference_is_external(reference: Mapping[str, Any]) -> bool:
    for key in ("resolution_scope", "document_scope", "source_scope", "scope"):
        value = str(reference.get(key) or "").strip().lower().replace("-", "_")
        if value in {"external", "external_document", "other_document"}:
            return True
    return False


def _cross_reference_provenance_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Return de-duplicated cross-reference provenance for export rows."""

    references: Dict[str, Dict[str, Any]] = {}
    resolved_by_key: Dict[str, Dict[str, Any]] = {}
    for reference in norm.cross_references:
        if not isinstance(reference, dict):
            continue
        normalized = _normalized_reference_record(reference)
        key = _reference_provenance_key(normalized)
        if not key:
            continue
        if _is_local_scope_reference_record(reference) or _is_local_scope_reference_record(normalized):
            normalized["resolved"] = True
            normalized["same_document"] = True
            normalized.setdefault("resolution_scope", "local_self")
            resolved_by_key[key] = normalized
        references.setdefault(key, normalized)

    for resolved in norm.resolved_cross_references:
        if not isinstance(resolved, dict):
            continue
        normalized = _normalized_reference_record(resolved)
        key = _reference_provenance_key(normalized)
        if not key:
            continue
        normalized["resolved"] = True
        normalized["same_document"] = _is_same_document_resolved_reference(resolved)
        resolved_by_key[key] = normalized
        references.setdefault(key, normalized)

    resolved_records: List[Dict[str, Any]] = []
    unresolved_records: List[Dict[str, Any]] = []
    for key in sorted(references):
        reference = dict(references[key])
        resolved = resolved_by_key.get(key)
        if resolved and _is_same_document_resolved_reference(resolved):
            resolved_records.append(resolved)
        else:
            reference["resolved"] = False
            unresolved_records.append(reference)

    if not references:
        status = "none"
    elif unresolved_records:
        status = "unresolved"
    else:
        status = "resolved"

    return {
        "cross_reference_count": len(references),
        "cross_reference_resolution_status": status,
        "resolved_cross_references": resolved_records,
        "unresolved_cross_references": unresolved_records,
    }


def _normalized_reference_record(reference: Mapping[str, Any]) -> Dict[str, Any]:
    citation = _reference_section_citation(reference)
    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    target = str(reference.get("target") or reference.get("section") or reference.get("subsection") or "").strip()
    text = _reference_display_text(reference)

    normalized = {
        "reference_type": reference_type or ("section" if citation else ""),
        "target": target,
        "canonical_citation": citation,
        "value": citation or text,
        "raw_text": str(reference.get("raw_text") or reference.get("text") or "").strip(),
        "span": list(reference.get("span") or []),
        "resolution_scope": str(reference.get("resolution_scope") or reference.get("scope") or "").strip(),
    }
    for key in ("source_id", "resolved_source_id", "target_document", "document_scope", "source_scope"):
        value = reference.get(key)
        if value:
            normalized[key] = value
    if reference.get("same_document") is True:
        normalized["same_document"] = True
    return {key: value for key, value in normalized.items() if value not in ("", [], None)}


def _reference_display_text(reference: Mapping[str, Any]) -> str:
    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    value_text = str(reference.get("value") or "").strip()
    if reference_type == "section" and value_text.lower() in {
        "this",
        "this section",
        "current",
        "current section",
    }:
        return value_text

    for key in ("canonical_citation", "citation", "normalized_text", "raw_text", "text", "value"):
        value = str(reference.get(key) or "").strip()
        if value:
            if (
                key == "value"
                and reference_type == "section"
                and value.lower() not in {"this", "current"}
                and not value.lower().startswith("section ")
                and not re.search(r"\s", value)
            ):
                return f"section {value}"
            return value

    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    target = str(reference.get("target") or reference.get("section") or reference.get("subsection") or "").strip()
    if reference_type and target:
        return target if target.lower().startswith(reference_type + " ") else f"{reference_type} {target}"
    return ""


def _reference_provenance_key(reference: Mapping[str, Any]) -> str:
    citation = _canonical_section_citation(str(reference.get("canonical_citation") or reference.get("value") or ""))
    if citation:
        return citation
    value = str(reference.get("value") or reference.get("raw_text") or "").strip().lower()
    return value


def _is_same_document_resolved_reference(reference: Mapping[str, Any]) -> bool:
    if reference.get("same_document") is True:
        return True

    for key in ("resolution_scope", "document_scope", "source_scope", "scope"):
        value = str(reference.get(key) or "").strip().lower().replace("-", "_")
        if value in {"same_document", "this_document", "current_document", "local"}:
            return True

    target_document = str(reference.get("target_document") or "").strip().lower()
    return target_document in {"same_document", "this_document", "current_document"}


def _is_local_scope_reference_record(reference: Mapping[str, Any]) -> bool:
    """Return whether a reference explicitly points to the current local scope."""

    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    if reference_type not in {"section", "subsection", "chapter", "title", "article", "part"}:
        return False

    target = str(reference.get("target") or reference.get("section") or reference.get("subsection") or "").strip().lower()
    if target in {"this", "current", f"this {reference_type}", f"current {reference_type}"}:
        return True

    for key in ("value", "normalized_text", "raw_text", "text", "canonical_citation", "citation"):
        text = str(reference.get(key) or "").strip().lower()
        if text in {f"this {reference_type}", f"current {reference_type}"}:
            return True

    return False


def _precedence_override_reference_records(norm: LegalNormIR) -> List[Dict[str, Any]]:
    """Return parser-facing provenance records for pure precedence overrides.

    Formula readiness can deterministically clear a clause like
    ``Notwithstanding section 5.01.020, ...`` when the cited section is used
    only as override provenance and not as an operative formula antecedent. The
    reference should still be visible to parser/export callers as resolved
    precedence provenance, not as a same-document factual resolution.
    """

    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for reference in norm.cross_references:
        if not isinstance(reference, dict):
            continue
        normalized = _normalized_reference_record(reference)
        key = _reference_provenance_key(normalized)
        if not key or key in seen:
            continue
        normalized["resolved"] = True
        normalized["resolution_scope"] = "precedence_provenance"
        normalized["precedence_only"] = True
        normalized["resolution_status"] = "resolved"
        normalized["same_document"] = False
        records.append(normalized)
        seen.add(key)
    return records


def _hydrate_prompt_context_override_clause_details(element: Dict[str, Any]) -> None:
    """Recover source-grounded precedence override slots for metric rows.

    Repair-required metric payloads can be detail-only: they preserve the raw
    parser prompt_context and cross-reference record, but omit the top-level
    ``override_clause_details`` array. Formula readiness for a pure
    ``Notwithstanding section ...`` clause depends on that structured override
    slot, so reconstruct only that narrow parser-native record from the cited
    source text before IR projection.
    """

    if element.get("override_clause_details"):
        return

    warnings = set(str(warning) for warning in element.get("parser_warnings") or [])
    llm_repair = dict(element.get("llm_repair") or {})
    prompt_context = dict(llm_repair.get("prompt_context") or {})
    warnings.update(str(warning) for warning in prompt_context.get("parser_warnings") or [])
    if "override_clause_requires_precedence_review" not in warnings:
        return

    source_text = str(
        prompt_context.get("source_text")
        or element.get("text")
        or element.get("source_text")
        or ""
    )
    match = re.search(r"\bnotwithstanding\s+(.+?)(?:,|$)", source_text, re.IGNORECASE)
    if not match:
        return

    reference = _first_reference_record(element, prompt_context)
    raw_text = str(
        reference.get("raw_text")
        or reference.get("normalized_text")
        or reference.get("value")
        or match.group(1)
        or ""
    ).strip()
    if not raw_text:
        return

    span = list(reference.get("span") or [])
    if len(span) != 2:
        span = [match.start(1), match.end(1)]

    clause_span = [match.start(), match.end()]
    record = {
        "type": "override",
        "clause_type": "notwithstanding",
        "raw_text": raw_text,
        "normalized_text": raw_text,
        "span": span,
        "clause_span": clause_span,
    }
    element["override_clause_details"] = [record]
    element["override_clauses"] = [raw_text]


def _hydrate_prompt_context_modal_slots(elements: Sequence[Dict[str, Any]]) -> None:
    """Recover omitted modal slots from deterministic repair prompt context.

    Optimizer repair-detail rows often preserve the parser's prompt_context but
    set top-level ``modality`` to null and omit ``deontic_operator``. The IR can
    infer an operator from ``norm_type`` for formula construction, but metric
    readiness projection still sees stale repair flags on the source row. Copy
    only parser-produced modal slots from prompt_context so detail-only rows use
    the same deterministic readiness path as ordinary parser elements.
    """

    allowed = {"O", "P", "F", "DEF", "APP", "EXEMPT", "LIFE"}
    for element in elements:
        llm_repair = dict(element.get("llm_repair") or {})
        prompt_context = llm_repair.get("prompt_context") or {}
        if not isinstance(prompt_context, Mapping):
            continue

        prompt_operator = str(
            prompt_context.get("deontic_operator") or prompt_context.get("modality") or ""
        ).strip().upper()
        if prompt_operator not in allowed:
            continue

        current_operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
        if current_operator in allowed:
            continue

        element["deontic_operator"] = prompt_operator
        element["modality"] = prompt_operator


def _hydrate_prompt_context_same_document_references(
    element: Dict[str, Any],
    all_elements: Sequence[Mapping[str, Any]],
) -> None:
    """Recover same-document numbered reference evidence for detail rows.

    Optimizer repair-detail payloads can preserve the blocked clause plus a
    prompt-context document excerpt, while omitting the parsed target section as
    a separate parser element. Clear active repair only when the cited numbered
    section is explicitly present in same-document source supplied to the
    deterministic evaluation payload. Standalone ``section 552`` exceptions
    still lack this evidence and remain blocked.
    """

    if element.get("resolved_cross_references"):
        return

    warnings = set(str(warning) for warning in element.get("parser_warnings") or [])
    llm_repair = dict(element.get("llm_repair") or {})
    prompt_context = dict(llm_repair.get("prompt_context") or {})
    warnings.update(str(warning) for warning in prompt_context.get("parser_warnings") or [])
    if "cross_reference_requires_resolution" not in warnings:
        return

    references = _prompt_context_reference_records(element, prompt_context)
    if not references:
        return

    section_index = _prompt_context_section_index(element, prompt_context, all_elements)
    if not section_index:
        return

    projected: List[Dict[str, Any]] = []
    for reference in references:
        citation = _canonical_section_citation(_reference_display_text(reference))
        if not citation:
            citation = _canonical_section_citation(
                f"section {reference.get('target') or reference.get('section') or reference.get('value') or ''}"
            )
        if not citation or citation not in section_index:
            return
        projected.append(_parser_native_same_document_reference(reference, citation, section_index[citation]))

    if projected:
        element["resolved_cross_references"] = projected


def _prompt_context_reference_records(
    element: Mapping[str, Any],
    prompt_context: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for source in (element, prompt_context):
        for key in ("cross_reference_details", "cross_references"):
            for candidate in source.get(key) or []:
                if isinstance(candidate, Mapping):
                    records.append(dict(candidate))
    return records


def _prompt_context_section_index(
    element: Mapping[str, Any],
    prompt_context: Mapping[str, Any],
    all_elements: Sequence[Mapping[str, Any]],
) -> Dict[str, str]:
    section_index: Dict[str, str] = {}
    source_id = str(element.get("source_id") or prompt_context.get("source_id") or "")

    for candidate in all_elements:
        candidate_id = str(candidate.get("source_id") or "")
        for key in ("canonical_citation", "citation"):
            citation = _canonical_section_citation(str(candidate.get(key) or ""))
            if citation:
                section_index.setdefault(citation, candidate_id or source_id)
        section_context = candidate.get("section_context") or {}
        if isinstance(section_context, Mapping):
            citation = _canonical_section_citation(f"section {section_context.get('section') or ''}")
            if citation:
                section_index.setdefault(citation, candidate_id or source_id)
        for key in ("document_text", "source_document", "full_text", "same_document_text"):
            text = str(candidate.get(key) or "")
            for match in _SECTION_HEADING_RE.finditer(text):
                citation = f"section {match.group(1)}".lower()
                section_index.setdefault(citation, candidate_id or source_id)

    for key in ("document_text", "source_document", "full_text", "same_document_text"):
        text = str(prompt_context.get(key) or element.get(key) or "")
        for match in _SECTION_HEADING_RE.finditer(text):
            section_index.setdefault(f"section {match.group(1)}".lower(), source_id)

    return section_index


def _parser_native_same_document_reference(
    reference: Mapping[str, Any],
    citation: str,
    source_id: str,
) -> Dict[str, Any]:
    target = citation[len("section ") :] if citation.startswith("section ") else citation
    raw_text = str(reference.get("raw_text") or reference.get("text") or citation).strip()
    return {
        "type": str(reference.get("type") or reference.get("reference_type") or "section"),
        "value": str(reference.get("value") or reference.get("target") or target),
        "raw_text": raw_text,
        "normalized_text": str(reference.get("normalized_text") or citation).strip(),
        "span": list(reference.get("span") or []),
        "resolution_status": "resolved",
        "target_exists": True,
        "resolution_scope": "same_document",
        "same_document": True,
        "resolved": True,
        "source_id": source_id,
        "resolved_source_id": source_id,
    }


def _first_reference_record(
    element: Mapping[str, Any],
    prompt_context: Mapping[str, Any],
) -> Dict[str, Any]:
    for source in (element, prompt_context):
        for key in ("cross_reference_details", "cross_references"):
            for candidate in source.get(key) or []:
                if isinstance(candidate, Mapping):
                    return dict(candidate)
    return {}


def _project_same_document_resolved_cross_references(
    element: Dict[str, Any],
    resolved_references: Sequence[Mapping[str, Any]],
    formula_record: Mapping[str, Any],
) -> None:
    """Attach parser-native same-document reference resolutions to a metrics row.

    Formula batch resolution uses IR reference records. Metrics and repair-detail
    collectors still inspect parser elements, so a resolved numbered exception
    must carry the same evidence in ``resolved_cross_references`` without
    forcing those callers to understand formula-record provenance.
    """

    deterministic_resolution = dict(formula_record.get("deterministic_resolution") or {})
    if deterministic_resolution.get("type") != "resolved_same_document_reference_exception":
        return

    projected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for reference in resolved_references:
        if not isinstance(reference, Mapping):
            continue
        if not _is_same_document_resolved_reference(reference):
            continue
        normalized = _normalized_reference_record(reference)
        key = _reference_provenance_key(normalized)
        if not key or key in seen:
            continue
        projected.append(_parser_native_resolved_reference_record(element, reference))
        seen.add(key)

    if projected:
        element["resolved_cross_references"] = projected


def _project_formula_record_active_repair_status(
    element: Dict[str, Any],
    formula_record: Mapping[str, Any],
) -> None:
    """Align metric active-repair flags with deterministic formula readiness.

    Repair-detail evaluation rows can carry stale ``llm_repair.required=True``
    even after IR/formula projection has a source-grounded deterministic
    resolution. Metrics should count active repair work, so only clear the flag
    when the formula record is proof-ready and explicitly carries a deterministic
    resolution. Unresolved numbered references keep their repair-required state.
    """

    deterministic_resolution = dict(formula_record.get("deterministic_resolution") or {})
    if not deterministic_resolution:
        return
    if formula_record.get("repair_required") is not False:
        return
    if formula_record.get("requires_validation") is not False:
        return

    export_readiness = dict(element.get("export_readiness") or {})
    export_readiness["formula_proof_ready"] = True
    export_readiness["formula_requires_validation"] = False
    export_readiness["formula_repair_required"] = False
    export_readiness["metric_requires_validation"] = False
    export_readiness["metric_repair_required"] = False
    export_readiness["deterministic_resolution"] = deterministic_resolution
    element["export_readiness"] = export_readiness

    llm_repair = dict(element.get("llm_repair") or {})
    llm_repair["required"] = False
    llm_repair["allow_llm_repair"] = False
    llm_repair["reasons"] = []
    llm_repair["deterministically_resolved"] = True
    llm_repair["deterministic_resolution"] = deterministic_resolution
    element["llm_repair"] = llm_repair
    element["active_repair_required"] = False
    element["active_repair_warnings"] = []


def _clear_stale_active_repair_from_export_readiness(element: Dict[str, Any]) -> None:
    """Clear stale metric repair flags after deterministic formula projection.

    Optimizer repair-detail rows can preserve an old ``llm_repair.required``
    flag even after IR/formula export readiness has deterministically resolved
    the row. Metrics should count active repair work, so this helper only clears
    that stale flag when export readiness explicitly says formula repair is not
    required and carries a deterministic resolution. Unresolved numbered
    references do not meet that contract and remain active repair.
    """

    export_readiness = dict(element.get("export_readiness") or {})
    deterministic_resolution = dict(export_readiness.get("deterministic_resolution") or {})
    if not deterministic_resolution:
        return
    if export_readiness.get("formula_repair_required") is not False:
        return
    if export_readiness.get("formula_requires_validation") is not False:
        return

    export_readiness["formula_proof_ready"] = True
    export_readiness["metric_requires_validation"] = False
    export_readiness["metric_repair_required"] = False
    element["export_readiness"] = export_readiness

    llm_repair = dict(element.get("llm_repair") or {})
    llm_repair["required"] = False
    llm_repair["allow_llm_repair"] = False
    llm_repair["reasons"] = []
    llm_repair["deterministically_resolved"] = True
    llm_repair["deterministic_resolution"] = deterministic_resolution
    element["llm_repair"] = llm_repair
    element["active_repair_required"] = False
    element["active_repair_warnings"] = []


def _parser_native_resolved_reference_record(
    element: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> Dict[str, Any]:
    normalized = _normalized_reference_record(reference)
    original = _matching_parser_reference(element, normalized)
    reference_type = str(
        original.get("type")
        or original.get("reference_type")
        or normalized.get("reference_type")
        or "section"
    )
    target = str(original.get("value") or original.get("target") or normalized.get("target") or "")
    citation = str(normalized.get("canonical_citation") or normalized.get("value") or "").strip()
    raw_text = str(original.get("raw_text") or original.get("text") or citation or target).strip()
    normalized_text = str(original.get("normalized_text") or citation or raw_text).strip()

    record = {
        "type": reference_type,
        "value": target,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "span": list(original.get("span") or normalized.get("span") or []),
        "resolution_status": "resolved",
        "target_exists": True,
        "resolution_scope": "same_document",
        "same_document": True,
        "resolved": True,
    }
    for key in ("source_id", "resolved_source_id"):
        value = reference.get(key)
        if value:
            record[key] = value
    return record


def _matching_parser_reference(
    element: Mapping[str, Any],
    normalized_reference: Mapping[str, Any],
) -> Dict[str, Any]:
    target_key = _reference_provenance_key(normalized_reference)
    for key in ("cross_reference_details", "cross_references"):
        for candidate in element.get(key) or []:
            if not isinstance(candidate, Mapping):
                continue
            candidate_key = _reference_provenance_key(_normalized_reference_record(candidate))
            if candidate_key and candidate_key == target_key:
                return dict(candidate)
    return {}


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def summarize_reconstruction_slot_loss(
    records: Sequence[Mapping[str, Any]],
    required_slots: Sequence[str] = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS,
) -> Dict[str, Any]:
    """Summarize legally salient slot loss in decoder reconstruction records.

    Phase 8 reconstruction reports need a deterministic way to distinguish a
    readable decoded sentence from a legally complete one. This helper consumes
    export-style reconstruction or grounding records and reports which required
    IR slots were grounded, missing, or decoded without provenance. It does not
    change parser proof-readiness or repair gates.
    """

    required = tuple(dict.fromkeys(str(slot) for slot in required_slots if slot))
    grounded_slots: set[str] = set()
    missing_slots: set[str] = set()
    ungrounded_slots: set[str] = set()
    source_ids: set[str] = set()

    for record in records or []:
        if not isinstance(record, Mapping):
            continue

        source_id = str(record.get("source_id") or "").strip()
        if source_id:
            source_ids.add(source_id)

        grounded_slots.update(_slot_names_from_record(record, "grounded_slots"))
        missing_slots.update(_slot_names_from_record(record, "missing_slots"))
        ungrounded_slots.update(_slot_names_from_record(record, "ungrounded_slots"))

        for slot_record in _slot_grounding_records(record):
            slot_name = str(
                slot_record.get("slot")
                or slot_record.get("slot_name")
                or slot_record.get("field")
                or ""
            ).strip()
            if not slot_name:
                continue
            status = str(
                slot_record.get("status")
                or slot_record.get("grounding_status")
                or ""
            ).strip().lower()
            if slot_record.get("grounded") is True or status in {"grounded", "present"}:
                grounded_slots.add(slot_name)
            elif slot_record.get("ungrounded") is True or status in {"ungrounded", "unprovenanced"}:
                ungrounded_slots.add(slot_name)
            elif slot_record.get("missing") is True or status in {"missing", "omitted"}:
                missing_slots.add(slot_name)

        provenance = record.get("decoded_phrase_provenance") or record.get("phrase_provenance")
        if isinstance(provenance, Sequence) and not isinstance(provenance, (str, bytes)):
            for phrase in provenance:
                if not isinstance(phrase, Mapping):
                    continue
                slot_name = str(phrase.get("slot") or phrase.get("slot_name") or "").strip()
                if not slot_name:
                    continue
                spans = phrase.get("spans") or phrase.get("source_spans") or phrase.get("field_spans")
                if spans:
                    grounded_slots.add(slot_name)
                elif phrase.get("fixed_connective") is not True:
                    ungrounded_slots.add(slot_name)

    grounded_required = sorted(slot for slot in required if slot in grounded_slots)
    missing_required = sorted(slot for slot in required if slot not in grounded_slots or slot in missing_slots)
    extra_ungrounded = sorted(slot for slot in ungrounded_slots if slot not in required)
    ungrounded_required = sorted(slot for slot in required if slot in ungrounded_slots)
    blockers = [f"missing_reconstruction_slot:{slot}" for slot in missing_required]
    blockers.extend(f"ungrounded_reconstruction_slot:{slot}" for slot in ungrounded_required)
    blockers.extend(f"ungrounded_decoded_slot:{slot}" for slot in extra_ungrounded)

    required_count = len(required)
    grounded_count = len(grounded_required)
    ungrounded_count = len(ungrounded_required) + len(extra_ungrounded)

    return {
        "source_ids": sorted(source_ids),
        "record_count": len([record for record in records or [] if isinstance(record, Mapping)]),
        "required_slots": list(required),
        "grounded_required_slots": grounded_required,
        "missing_required_slots": missing_required,
        "ungrounded_required_slots": ungrounded_required,
        "extra_ungrounded_slots": extra_ungrounded,
        "required_slot_count": required_count,
        "grounded_required_slot_count": grounded_count,
        "missing_required_slot_count": len(missing_required),
        "ungrounded_slot_count": ungrounded_count,
        "slot_reconstruction_complete": required_count > 0 and grounded_count == required_count and ungrounded_count == 0,
        "grounded_required_slot_rate": round(grounded_count / required_count, 6) if required_count else 0.0,
        "ungrounded_decoded_slot_rate": round(ungrounded_count / (grounded_count + ungrounded_count), 6)
        if grounded_count + ungrounded_count
        else 0.0,
        "coverage_blockers": blockers,
    }


def build_reconstruction_slot_loss_record(
    source_id: str,
    records: Sequence[Mapping[str, Any]],
    required_slots: Sequence[str] = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS,
) -> Dict[str, Any]:
    """Build a stable export row for decoder slot-loss diagnostics.

    The summary helper is useful inside tests and reports, but Phase 8 export
    consumers also need a primary-keyed row that can be persisted alongside
    decoder reconstruction records. This row keeps missing and ungrounded legal
    slots explicit without changing parser repair or proof-readiness gates.
    """

    summary = summarize_reconstruction_slot_loss(records, required_slots)
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id and len(summary["source_ids"]) == 1:
        normalized_source_id = summary["source_ids"][0]

    return {
        "reconstruction_slot_loss_id": _stable_id(
            "reconstruction-slot-loss",
            normalized_source_id,
            "|".join(summary["required_slots"]),
        ),
        "source_id": normalized_source_id,
        "target_logic": "decoder_reconstruction",
        "record_count": summary["record_count"],
        "required_slots": summary["required_slots"],
        "grounded_required_slot_rate": summary["grounded_required_slot_rate"],
        "ungrounded_decoded_slot_rate": summary["ungrounded_decoded_slot_rate"],
        "slot_reconstruction_complete": summary["slot_reconstruction_complete"],
        "requires_validation": not summary["slot_reconstruction_complete"],
        "coverage_blockers": summary["coverage_blockers"],
        "coverage_summary": summary,
    }


def build_reconstruction_slot_loss_records(
    records: Sequence[Mapping[str, Any]],
    required_slots: Sequence[str] = DEFAULT_RECONSTRUCTION_LEGAL_SLOTS,
) -> List[Dict[str, Any]]:
    """Build stable decoder slot-loss export rows grouped by source norm.

    Corpus-level Phase 8 reports receive a flat stream of decoder reconstruction
    and slot-grounding records. This helper groups those records by their
    source_id and emits one primary-keyed slot-loss row per source norm. Records
    without a source_id are ignored because the export row must remain
    source-grounded and must not invent provenance.
    """

    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if not source_id:
            continue
        grouped.setdefault(source_id, []).append(record)

    return [
        build_reconstruction_slot_loss_record(source_id, grouped[source_id], required_slots)
        for source_id in sorted(grouped)
    ]


def _slot_names_from_record(record: Mapping[str, Any], key: str) -> set[str]:
    values = record.get(key) or []
    if isinstance(values, Mapping):
        values = values.keys()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Sequence):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _slot_grounding_records(record: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    for key in ("slot_grounding", "slot_grounding_records", "slot_audits"):
        values = record.get(key) or []
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            return [value for value in values if isinstance(value, Mapping)]
    return []


def _deterministic_capability_profile_slots(
    norm: LegalNormIR,
    requested_slots: Sequence[str],
) -> Sequence[str]:
    requested = tuple(dict.fromkeys(str(slot) for slot in requested_slots if slot))
    if requested != DEFAULT_DETERMINISTIC_CAPABILITY_PROFILE_SLOTS:
        return requested

    family = _deterministic_norm_family(norm)
    return DEFAULT_DETERMINISTIC_CAPABILITY_PROFILE_SLOTS_BY_FAMILY.get(family, requested)


def _deterministic_norm_family(norm: LegalNormIR) -> str:
    if norm.is_enumerated_child:
        return "enumerated_child_duty"

    legal_frame = norm.legal_frame if isinstance(norm.legal_frame, Mapping) else {}
    category = str(legal_frame.get("category") or "").strip().lower()

    if norm.norm_type == "definition":
        return "definition"
    if norm.norm_type == "applicability":
        return "applicability_rule"
    if norm.norm_type == "exemption":
        return "exemption_rule"
    if norm.norm_type == "instrument_lifecycle":
        action = str(norm.action or "").strip().lower()
        if action.startswith("valid for "):
            return "instrument_lifecycle_validity"
        if action.startswith("expires "):
            return "instrument_lifecycle_expiration"
        return "instrument_lifecycle"

    formula = build_deontic_formula_record_from_ir(norm)["formula"]
    action_predicate = _deterministic_formula_action_predicate(formula)

    if action_predicate.startswith(("Abate", "Remediate", "Mitigate", "Enforce", "Remedy")):
        return "enforcement_remedy_duty"
    if action_predicate.startswith((
        "Announce",
        "Circulate",
        "Disseminate",
        "Display",
        "Distribute",
        "Post",
        "Transmit",
    )):
        return "public_information_duty"
    if action_predicate.startswith(("Comment", "Object", "Respond")):
        return "review_participation_duty"
    if action_predicate.startswith((
        "FileAppeal",
        "FileApplication",
        "FilePetition",
        "MakeAppeal",
        "MakeApplication",
        "MakePetition",
        "SubmitAppeal",
        "SubmitApplication",
        "SubmitPetition",
    )):
        return "administrative_review_request_duty"
    if norm.modality == "P" and category == "authority":
        return "authority_grant"
    if norm.norm_type == "penalty" or norm.penalty:
        return "sanction_clause"
    if _has_deadline_temporal_constraint(norm):
        return "temporal_deadline_duty"
    if norm.procedure:
        return "procedural_event_duty"
    if norm.modality == "O" and norm.norm_type == "obligation":
        return "ordinary_duty"
    if norm.modality == "F" or norm.norm_type == "prohibition":
        return "prohibition"
    return norm.norm_type or norm.modality or "unknown"


def _has_deadline_temporal_constraint(norm: LegalNormIR) -> bool:
    for record in norm.temporal_constraints or []:
        if not isinstance(record, Mapping):
            continue
        constraint_type = str(record.get("type") or "").strip().lower()
        relation = str(record.get("relation") or "").strip().lower()
        value = str(record.get("value") or record.get("normalized_text") or "").strip().lower()
        if constraint_type == "deadline" or relation in {"deadline", "due_by"}:
            return True
        if value.startswith(("within ", "not later than ", "no later than ", "by ", "before ")):
            return True
    return False


def _deterministic_formula_action_predicate(formula: str) -> str:
    """Return the consequent predicate from a generated deontic formula."""

    match = re.search(
        r"\u2192\s*([A-Za-z][A-Za-z0-9_]*)\s*\(x\)\)\)$",
        str(formula or "").strip(),
    )
    return match.group(1) if match else ""
