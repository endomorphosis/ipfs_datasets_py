"""Syntax-only validation records for deterministic legal norm exports.

This module is deliberately local and conservative. It does not attempt full
theorem proving; it checks that the IR-derived formula can be rendered into the
local prover target dialects with balanced, non-empty syntax and source-grounded
metadata. Full target parser integration can replace these validators target by
target without changing the report shape.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Sequence

from .formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from .ir import LegalNormIR, legal_norm_ir_slot_provenance
from .decoder import decode_legal_norm_ir, decoded_phrase_slot_text_map


LOCAL_PROVER_TARGETS = (
    "frame_logic",
    "deontic_cec",
    "fol",
    "deontic_fol",
    "deontic_temporal_fol",
)

PROVER_IR_AUDIT_SLOTS = (
    "actor",
    "modality",
    "action",
    "mental_state",
    "recipient",
    "conditions",
    "exceptions",
    "temporal_constraints",
    "cross_references",
)


@dataclass(frozen=True)
class ProverTargetSyntaxRecord:
    """Syntax validation result for one local prover target."""

    source_id: str
    target: str
    target_version: str
    formula: str
    exported_formula: str
    target_formula_role: str
    target_formula_fingerprint: str
    ir_semantic_fingerprint: str
    decoded_text: str
    decoded_slots: List[str]
    decoded_slot_fingerprint: str
    decoded_phrase_profile: Dict[str, Any]
    decoded_phrase_profile_fingerprint: str
    grounded_decoded_slots: List[str]
    ungrounded_decoded_slots: List[str]
    missing_decoded_slots: List[str]
    grounded_ir_slots: List[str]
    ungrounded_ir_slots: List[str]
    missing_ir_slots: List[str]
    ir_slot_grounding: List[Dict[str, Any]]
    ir_slot_grounding_fingerprint: str
    formula_slots: List[str]
    omitted_formula_slots: Dict[str, Any]
    decoded_ir_slot_alignment: Dict[str, Any]
    slot_alignment_fingerprint: str
    source_formula_symbols: List[str]
    exported_formula_symbols: List[str]
    target_symbol_alignment: Dict[str, Any]
    target_symbol_alignment_fingerprint: str
    target_semantic_bridge_profile: Dict[str, Any]
    target_semantic_bridge_fingerprint: str
    target_dialect_profile: Dict[str, Any]
    target_dialect_profile_fingerprint: str
    target_parse_profile: Dict[str, Any]
    target_parse_profile_fingerprint: str
    reconstruction_token_profile: Dict[str, Any]
    reconstruction_token_profile_fingerprint: str
    target_components: Dict[str, Any]
    target_quality_gate: Dict[str, Any]
    target_quality_gate_fingerprint: str
    syntax_valid: bool
    skipped: bool
    diagnostics: List[Dict[str, Any]]
    proof_ready: bool
    requires_validation: bool
    schema_version: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProverSyntaxReport:
    """Syntax validation report for all requested local targets."""

    source_id: str
    syntax_valid: bool
    target_count: int
    valid_target_count: int
    skipped_target_count: int
    targets: List[ProverTargetSyntaxRecord]
    proof_ready: bool
    requires_validation: bool
    schema_version: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["targets"] = [target.to_dict() for target in self.targets]
        return data


def validate_ir_with_provers(
    norm: LegalNormIR,
    targets: Iterable[str] | None = None,
) -> ProverSyntaxReport:
    """Return syntax-only validation records for local prover targets."""

    requested_targets = _normalize_targets(targets)
    formula = build_deontic_formula_from_ir(norm)
    formula_record = build_deontic_formula_record_from_ir(norm)
    records = [
        _validate_target_formula(norm, target, formula, formula_record)
        for target in requested_targets
    ]
    valid_count = sum(1 for record in records if record.syntax_valid)
    skipped_count = sum(1 for record in records if record.skipped)
    requires_validation = any(record.requires_validation for record in records)

    return ProverSyntaxReport(
        source_id=norm.source_id,
        syntax_valid=valid_count == len(records),
        target_count=len(records),
        valid_target_count=valid_count,
        skipped_target_count=skipped_count,
        targets=records,
        proof_ready=bool(records and all(record.proof_ready for record in records)),
        requires_validation=requires_validation,
        schema_version=norm.schema_version,
    )


def build_prover_syntax_records_from_ir(
    norm: LegalNormIR,
    targets: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build export-friendly prover syntax rows from one typed IR norm."""

    return [record.to_dict() for record in validate_ir_with_provers(norm, targets).targets]


def _normalize_targets(targets: Iterable[str] | None) -> List[str]:
    if targets is None:
        return list(LOCAL_PROVER_TARGETS)

    normalized: List[str] = []
    for target in targets:
        value = str(target or "").strip().lower().replace("-", "_")
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _validate_target_formula(
    norm: LegalNormIR,
    target: str,
    formula: str,
    formula_record: Dict[str, Any],
) -> ProverTargetSyntaxRecord:
    exported_formula = _render_target_formula(norm, target, formula)
    decoded = decode_legal_norm_ir(norm)
    decoded_slot_summary = _decoded_slot_summary(decoded)
    decoded_phrase_profile = _decoded_phrase_profile(target, norm, decoded)
    ir_slot_summary = _ir_slot_grounding_summary(norm)
    alignment_summary = _decoded_ir_slot_alignment(
        decoded_slot_summary,
        ir_slot_summary,
        formula_record,
    )
    symbol_alignment = _target_symbol_alignment(
        target,
        formula,
        exported_formula,
    )
    semantic_bridge_profile = _target_semantic_bridge_profile(
        target,
        norm,
        formula_record,
        decoded_slot_summary,
        ir_slot_summary,
        alignment_summary,
        symbol_alignment,
    )
    target_dialect_profile = _target_dialect_profile(
        target,
        formula,
        exported_formula,
        norm,
    )
    target_parse_profile = _target_parse_profile(target, exported_formula)
    reconstruction_token_profile = _reconstruction_token_profile(
        target,
        norm,
        decoded.text,
    )
    target_components = _target_components(
        target,
        exported_formula,
        ir_slot_summary,
        alignment_summary,
        symbol_alignment,
        target_dialect_profile,
        target_parse_profile,
        reconstruction_token_profile,
        decoded_phrase_profile,
    )
    diagnostics = _syntax_diagnostics(target, exported_formula)
    syntax_valid = not diagnostics
    target_quality_gate = _target_quality_gate(
        norm,
        target,
        formula_record,
        diagnostics,
        alignment_summary,
        symbol_alignment,
        target_dialect_profile,
        target_parse_profile,
        reconstruction_token_profile,
    )

    return ProverTargetSyntaxRecord(
        source_id=norm.source_id,
        target=target,
        target_version="syntax_v1",
        formula=formula,
        exported_formula=exported_formula,
        target_formula_role=_target_formula_role(target),
        target_formula_fingerprint=_stable_fingerprint(target, exported_formula),
        ir_semantic_fingerprint=_ir_semantic_fingerprint(
            norm,
            formula,
            decoded_slot_summary["decoded_slots"],
            ir_slot_summary["grounded_ir_slots"],
        ),
        decoded_text=decoded.text,
        decoded_slots=decoded_slot_summary["decoded_slots"],
        decoded_slot_fingerprint=_stable_fingerprint(
            norm.source_id,
            "|".join(decoded_slot_summary["decoded_slots"]),
            decoded.text,
        ),
        decoded_phrase_profile=decoded_phrase_profile,
        decoded_phrase_profile_fingerprint=decoded_phrase_profile[
            "decoded_phrase_profile_fingerprint"
        ],
        grounded_decoded_slots=decoded_slot_summary["grounded_decoded_slots"],
        ungrounded_decoded_slots=decoded_slot_summary["ungrounded_decoded_slots"],
        missing_decoded_slots=decoded_slot_summary["missing_decoded_slots"],
        grounded_ir_slots=ir_slot_summary["grounded_ir_slots"],
        ungrounded_ir_slots=ir_slot_summary["ungrounded_ir_slots"],
        missing_ir_slots=ir_slot_summary["missing_ir_slots"],
        ir_slot_grounding=ir_slot_summary["ir_slot_grounding"],
        ir_slot_grounding_fingerprint=ir_slot_summary["ir_slot_grounding_fingerprint"],
        formula_slots=alignment_summary["formula_slots"],
        omitted_formula_slots=alignment_summary["omitted_formula_slots"],
        decoded_ir_slot_alignment=alignment_summary,
        slot_alignment_fingerprint=alignment_summary["slot_alignment_fingerprint"],
        source_formula_symbols=symbol_alignment["source_formula_symbols"],
        exported_formula_symbols=symbol_alignment["exported_formula_symbols"],
        target_symbol_alignment=symbol_alignment,
        target_symbol_alignment_fingerprint=symbol_alignment[
            "target_symbol_alignment_fingerprint"
        ],
        target_semantic_bridge_profile=semantic_bridge_profile,
        target_semantic_bridge_fingerprint=semantic_bridge_profile[
            "target_semantic_bridge_fingerprint"
        ],
        target_dialect_profile=target_dialect_profile,
        target_dialect_profile_fingerprint=target_dialect_profile[
            "target_dialect_profile_fingerprint"
        ],
        target_parse_profile=target_parse_profile,
        target_parse_profile_fingerprint=target_parse_profile[
            "target_parse_profile_fingerprint"
        ],
        reconstruction_token_profile=reconstruction_token_profile,
        reconstruction_token_profile_fingerprint=reconstruction_token_profile[
            "reconstruction_token_profile_fingerprint"
        ],
        target_components=target_components,
        target_quality_gate=target_quality_gate,
        target_quality_gate_fingerprint=target_quality_gate[
            "target_quality_gate_fingerprint"
        ],
        syntax_valid=syntax_valid,
        skipped=False,
        diagnostics=diagnostics,
        proof_ready=bool(formula_record.get("proof_ready") is True and syntax_valid),
        requires_validation=bool(formula_record.get("requires_validation") is not False or diagnostics),
        schema_version=norm.schema_version,
    )


def _render_target_formula(norm: LegalNormIR, target: str, formula: str) -> str:
    source_symbol = _source_symbol(norm.source_id)
    fol_formula = _to_ascii_logic(_strip_deontic_wrapper(formula))
    deontic_formula = _to_ascii_deontic_formula(formula)
    if target == "frame_logic":
        actor = _predicate_symbol(norm.actor or "Actor")
        action = _predicate_symbol(norm.action or "Action")
        frame_formula = _to_frame_logic_atom(formula)
        return f"legal_norm({source_symbol})[actor->{actor}; action->{action}; formula->{frame_formula}]"
    if target == "deontic_cec":
        return f"Happens(legal_norm({source_symbol}), t) => HoldsAt({deontic_formula}, t)"
    if target == "fol":
        return fol_formula
    if target == "deontic_fol":
        return deontic_formula
    if target == "deontic_temporal_fol":
        return f"always({deontic_formula})"
    return formula


def _syntax_diagnostics(target: str, exported_formula: str) -> List[Dict[str, Any]]:
    diagnostics: List[Dict[str, Any]] = []
    if target not in LOCAL_PROVER_TARGETS:
        diagnostics.append({"code": "unknown_target", "message": f"unsupported local prover target: {target}"})
    if not exported_formula.strip():
        diagnostics.append({"code": "empty_formula", "message": "exported formula is empty"})
    if not _balanced_delimiters(exported_formula):
        diagnostics.append({"code": "unbalanced_delimiters", "message": "formula delimiters are unbalanced"})
    if re.search(r"\bNone\b|\?\?", exported_formula):
        diagnostics.append({"code": "placeholder_token", "message": "formula contains a placeholder token"})
    if target in {"deontic_cec", "fol", "deontic_fol", "deontic_temporal_fol"} and re.search(r"[∀∧→¬]", exported_formula):
        diagnostics.append({"code": "display_connective", "message": "target formula contains display-only logic connectives"})
    if (
        target in {"fol", "deontic_fol", "deontic_temporal_fol"}
        and "forall x." not in exported_formula
        and not _is_frame_style_formula(exported_formula)
        and not _contains_frame_style_formula(exported_formula)
    ):
        diagnostics.append({"code": "missing_quantifier", "message": "FOL target lacks a quantifier or accepted frame atom"})
    diagnostics.extend(_target_shape_diagnostics(target, exported_formula))
    return diagnostics


def _decoded_slot_summary(decoded: Any) -> Dict[str, List[str]]:
    decoded_slots: List[str] = []
    grounded_slots: List[str] = []
    ungrounded_slots: List[str] = []

    for phrase in getattr(decoded, "phrases", []) or []:
        if getattr(phrase, "fixed", False):
            continue
        slot = str(getattr(phrase, "slot", "") or "").strip()
        if not slot or slot in decoded_slots:
            continue
        decoded_slots.append(slot)
        if getattr(phrase, "spans", []) or []:
            grounded_slots.append(slot)
        else:
            ungrounded_slots.append(slot)

    missing_slots = [
        str(slot)
        for slot in getattr(decoded, "missing_slots", []) or []
        if str(slot).strip()
    ]
    return {
        "decoded_slots": decoded_slots,
        "grounded_decoded_slots": grounded_slots,
        "ungrounded_decoded_slots": ungrounded_slots,
        "missing_decoded_slots": missing_slots,
    }


def _decoded_phrase_profile(
    target: str,
    norm: LegalNormIR,
    decoded: Any,
) -> Dict[str, Any]:
    """Audit the decoded phrase stream consumed by prover target records."""

    phrase_slots: List[str] = []
    grounded_phrase_slots: List[str] = []
    ungrounded_phrase_slots: List[str] = []
    fixed_slots: List[str] = []
    provenance_only_slots: List[str] = []
    phrase_texts: List[str] = []
    phrase_texts_by_slot: Dict[str, List[str]] = {}
    legal_phrase_texts_by_slot: Dict[str, List[str]] = {}
    provenance_phrase_texts_by_slot: Dict[str, List[str]] = {}
    phrase_count = 0
    legal_phrase_count = 0
    fixed_phrase_count = 0
    provenance_only_phrase_count = 0
    grounded_phrase_count = 0

    for phrase in getattr(decoded, "phrases", []) or []:
        phrase_count += 1
        slot = str(getattr(phrase, "slot", "") or "").strip()
        text = str(getattr(phrase, "text", "") or "").strip()
        fixed = bool(getattr(phrase, "fixed", False))
        provenance_only = bool(getattr(phrase, "provenance_only", False))
        spans = list(getattr(phrase, "spans", []) or [])
        if text:
            phrase_texts.append(text)
            if slot and not fixed:
                _append_slot_text(phrase_texts_by_slot, slot, text)
        if fixed:
            fixed_phrase_count += 1
            if slot and slot not in fixed_slots:
                fixed_slots.append(slot)
            continue
        if provenance_only:
            provenance_only_phrase_count += 1
            if slot and slot not in provenance_only_slots:
                provenance_only_slots.append(slot)
            if slot and text:
                _append_slot_text(provenance_phrase_texts_by_slot, slot, text)
        else:
            legal_phrase_count += 1
            if slot and text:
                _append_slot_text(legal_phrase_texts_by_slot, slot, text)
        if slot and slot not in phrase_slots:
            phrase_slots.append(slot)
        if spans:
            grounded_phrase_count += 1
            if slot and slot not in grounded_phrase_slots:
                grounded_phrase_slots.append(slot)
        elif slot and slot not in ungrounded_phrase_slots:
            ungrounded_phrase_slots.append(slot)

    missing_slots = [
        str(slot)
        for slot in getattr(decoded, "missing_slots", []) or []
        if str(slot).strip()
    ]
    complete = not missing_slots and not ungrounded_phrase_slots
    fingerprint = _stable_fingerprint(
        target,
        norm.source_id,
        "|".join(phrase_slots),
        "|".join(fixed_slots),
        "|".join(provenance_only_slots),
        "|".join(missing_slots),
        "|".join(phrase_texts),
        str(complete),
    )
    return {
        "target": target,
        "source_id": norm.source_id,
        "decoded_text": getattr(decoded, "text", ""),
        "phrase_count": phrase_count,
        "legal_phrase_count": legal_phrase_count,
        "fixed_phrase_count": fixed_phrase_count,
        "provenance_only_phrase_count": provenance_only_phrase_count,
        "grounded_phrase_count": grounded_phrase_count,
        "phrase_slots": phrase_slots,
        "grounded_phrase_slots": grounded_phrase_slots,
        "ungrounded_phrase_slots": ungrounded_phrase_slots,
        "fixed_slots": fixed_slots,
        "provenance_only_slots": provenance_only_slots,
        "phrase_texts_by_slot": decoded_phrase_slot_text_map(decoded),
        "legal_phrase_texts_by_slot": legal_phrase_texts_by_slot,
        "provenance_phrase_texts_by_slot": provenance_phrase_texts_by_slot,
        "missing_slots": missing_slots,
        "phrase_texts": phrase_texts,
        "all_decoded_phrases_grounded": not ungrounded_phrase_slots,
        "decoded_phrase_profile_complete": complete,
        "decoded_phrase_profile_fingerprint": fingerprint,
    }


def _target_formula_role(target: str) -> str:
    return {
        "frame_logic": "frame_record",
        "deontic_cec": "event_calculus_state",
        "fol": "first_order_formula",
        "deontic_fol": "deontic_first_order_formula",
        "deontic_temporal_fol": "temporal_deontic_first_order_formula",
    }.get(target, "unknown")


def _append_slot_text(target: Dict[str, List[str]], slot: str, text: str) -> None:
    values = target.setdefault(slot, [])
    if text not in values:
        values.append(text)


def _ir_slot_grounding_summary(norm: LegalNormIR) -> Dict[str, Any]:
    audit = legal_norm_ir_slot_provenance(norm, PROVER_IR_AUDIT_SLOTS)
    grounded_slots = list(audit["grounded_slots"])
    ungrounded_slots = list(audit["ungrounded_slots"])
    missing_slots = list(audit["missing_slots"])
    return {
        "grounded_ir_slots": grounded_slots,
        "ungrounded_ir_slots": ungrounded_slots,
        "missing_ir_slots": missing_slots,
        "ir_slot_grounding": list(audit["slot_grounding"]),
        "ir_slot_grounding_fingerprint": _stable_fingerprint(
            norm.source_id,
            "|".join(grounded_slots),
            "|".join(ungrounded_slots),
            "|".join(missing_slots),
        ),
    }


def _decoded_ir_slot_alignment(
    decoded_slot_summary: Dict[str, List[str]],
    ir_slot_summary: Dict[str, Any],
    formula_record: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare decoded slots, grounded IR slots, and formula-included slots."""

    decoded_slots = _ordered_unique(decoded_slot_summary.get("decoded_slots") or [])
    grounded_ir_slots = _ordered_unique(ir_slot_summary.get("grounded_ir_slots") or [])
    formula_slots = _ordered_unique(formula_record.get("included_formula_slots") or [])
    omitted_formula_slots = dict(formula_record.get("omitted_formula_slots") or {})
    omitted_formula_slot_names = sorted(
        str(slot) for slot in omitted_formula_slots.keys() if str(slot).strip()
    )

    decoded_set = set(decoded_slots)
    grounded_ir_set = set(grounded_ir_slots)
    formula_set = set(formula_slots)
    missing_decoded = [
        slot for slot in grounded_ir_slots if slot not in decoded_set
    ]
    ungrounded_decoded = [
        slot for slot in decoded_slots if slot not in grounded_ir_set
    ]
    formula_missing_decoded = [
        slot for slot in formula_slots if slot not in decoded_set
    ]
    formula_ungrounded = [
        slot for slot in formula_slots if slot not in grounded_ir_set
    ]
    decoded_formula_overlap = [
        slot for slot in decoded_slots if slot in formula_set
    ]
    grounded_formula_overlap = [
        slot for slot in grounded_ir_slots if slot in formula_set
    ]
    complete = (
        not missing_decoded
        and not ungrounded_decoded
        and not formula_missing_decoded
        and not formula_ungrounded
    )

    fingerprint = _stable_fingerprint(
        "|".join(decoded_slots),
        "|".join(grounded_ir_slots),
        "|".join(formula_slots),
        "|".join(omitted_formula_slot_names),
        str(complete),
    )
    return {
        "decoded_slots": decoded_slots,
        "grounded_ir_slots": grounded_ir_slots,
        "formula_slots": formula_slots,
        "omitted_formula_slots": omitted_formula_slots,
        "omitted_formula_slot_names": omitted_formula_slot_names,
        "decoded_formula_overlap": decoded_formula_overlap,
        "grounded_formula_overlap": grounded_formula_overlap,
        "decoded_missing_grounded_ir_slots": missing_decoded,
        "ungrounded_decoded_slots": ungrounded_decoded,
        "formula_missing_decoded_slots": formula_missing_decoded,
        "formula_ungrounded_slots": formula_ungrounded,
        "alignment_complete": complete,
        "slot_alignment_fingerprint": fingerprint,
    }


def _ordered_unique(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _target_components(
    target: str,
    exported_formula: str,
    ir_slot_summary: Dict[str, Any] | None = None,
    alignment_summary: Dict[str, Any] | None = None,
    symbol_alignment: Dict[str, Any] | None = None,
    target_dialect_profile: Dict[str, Any] | None = None,
    target_parse_profile: Dict[str, Any] | None = None,
    reconstruction_token_profile: Dict[str, Any] | None = None,
    decoded_phrase_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    text = str(exported_formula or "").strip()
    ir_slot_summary = ir_slot_summary or {}
    alignment_summary = alignment_summary or {}
    symbol_alignment = symbol_alignment or {}
    target_dialect_profile = target_dialect_profile or {}
    target_parse_profile = target_parse_profile or {}
    reconstruction_token_profile = reconstruction_token_profile or {}
    decoded_phrase_profile = decoded_phrase_profile or {}
    grounded_ir_slots = list(ir_slot_summary.get("grounded_ir_slots") or [])
    ungrounded_ir_slots = list(ir_slot_summary.get("ungrounded_ir_slots") or [])
    missing_ir_slots = list(ir_slot_summary.get("missing_ir_slots") or [])
    formula_slots = list(alignment_summary.get("formula_slots") or [])
    formula_slot_coverage = _formula_slot_coverage_profile(alignment_summary)
    missing_symbols = list(symbol_alignment.get("missing_exported_formula_symbols") or [])
    source_symbols = list(symbol_alignment.get("source_formula_symbols") or [])
    exported_symbols = list(symbol_alignment.get("exported_formula_symbols") or [])
    semantic_profile = _semantic_formula_profile(
        source_symbols,
        exported_symbols,
        formula_slots,
    )
    return {
        "target": target,
        "formula_role": _target_formula_role(target),
        "semantic_formula_family": semantic_profile["semantic_formula_family"],
        "semantic_formula_predicate": semantic_profile["semantic_formula_predicate"],
        "semantic_formula_symbols": semantic_profile["semantic_formula_symbols"],
        "semantic_formula_source": semantic_profile["semantic_formula_source"],
        "semantic_formula_slot_count": semantic_profile["semantic_formula_slot_count"],
        "uses_frame_record": target == "frame_logic" and text.startswith("legal_norm("),
        "uses_event_calculus_wrapper": target == "deontic_cec" and text.startswith("Happens("),
        "uses_deontic_wrapper": bool(re.match(r"^[OPF]\(", text)),
        "uses_temporal_wrapper": text.startswith("always("),
        "uses_first_order_quantifier": "forall x." in text,
        "contains_display_connectives": bool(re.search(r"[∀∧→¬]", text)),
        "grounded_ir_slots": grounded_ir_slots,
        "ungrounded_ir_slots": ungrounded_ir_slots,
        "missing_ir_slots": missing_ir_slots,
        "grounded_ir_slot_count": len(grounded_ir_slots),
        "ungrounded_ir_slot_count": len(ungrounded_ir_slots),
        "missing_ir_slot_count": len(missing_ir_slots),
        "formula_slots": formula_slots,
        "formula_slot_count": len(formula_slots),
        "formula_slot_coverage_complete": formula_slot_coverage[
            "formula_slot_coverage_complete"
        ],
        "formula_slot_decoder_rate": formula_slot_coverage[
            "formula_slot_decoder_rate"
        ],
        "formula_slot_grounding_rate": formula_slot_coverage[
            "formula_slot_grounding_rate"
        ],
        "decoded_formula_slots": formula_slot_coverage["decoded_formula_slots"],
        "grounded_formula_slots": formula_slot_coverage["grounded_formula_slots"],
        "omitted_formula_slot_names": formula_slot_coverage[
            "omitted_formula_slot_names"
        ],
        "slot_alignment_complete": bool(
            alignment_summary.get("alignment_complete") is True
        ),
        "decoded_missing_grounded_ir_slots": list(
            alignment_summary.get("decoded_missing_grounded_ir_slots") or []
        ),
        "formula_missing_decoded_slots": list(
            alignment_summary.get("formula_missing_decoded_slots") or []
        ),
        "formula_ungrounded_slots": list(
            alignment_summary.get("formula_ungrounded_slots") or []
        ),
        "source_formula_symbols": source_symbols,
        "exported_formula_symbols": exported_symbols,
        "source_formula_symbol_count": len(source_symbols),
        "exported_formula_symbol_count": len(exported_symbols),
        "missing_exported_formula_symbols": missing_symbols,
        "target_symbol_alignment_complete": bool(
            symbol_alignment.get("target_symbol_alignment_complete") is True
        ),
        "dialect_family": target_dialect_profile.get("dialect_family", "unknown"),
        "connective_style": target_dialect_profile.get("connective_style", "unknown"),
        "quantifier_policy": target_dialect_profile.get("quantifier_policy", "unknown"),
        "required_wrappers_present": bool(
            target_dialect_profile.get("required_wrappers_present") is True
        ),
        "forbidden_wrappers_absent": bool(
            target_dialect_profile.get("forbidden_wrappers_absent") is True
        ),
        "target_dialect_profile_complete": bool(
            target_dialect_profile.get("target_dialect_profile_complete") is True
        ),
        "target_parse_profile_complete": bool(
            target_parse_profile.get("target_parse_profile_complete") is True
        ),
        "reconstruction_token_profile_complete": bool(
            reconstruction_token_profile.get("reconstruction_token_profile_complete")
            is True
        ),
        "decoded_phrase_profile_complete": bool(
            decoded_phrase_profile.get("decoded_phrase_profile_complete") is True
        ),
        "decoded_phrase_count": int(decoded_phrase_profile.get("phrase_count") or 0),
        "decoded_legal_phrase_count": int(
            decoded_phrase_profile.get("legal_phrase_count") or 0
        ),
        "decoded_fixed_phrase_count": int(
            decoded_phrase_profile.get("fixed_phrase_count") or 0
        ),
        "decoded_provenance_only_phrase_count": int(
            decoded_phrase_profile.get("provenance_only_phrase_count") or 0
        ),
        "decoded_phrase_slots": list(decoded_phrase_profile.get("phrase_slots") or []),
        "decoded_fixed_slots": list(decoded_phrase_profile.get("fixed_slots") or []),
        "decoded_provenance_only_slots": list(
            decoded_phrase_profile.get("provenance_only_slots") or []
        ),
        "decoded_phrase_texts_by_slot": dict(
            decoded_phrase_profile.get("phrase_texts_by_slot") or {}
        ),
        "decoded_legal_phrase_texts_by_slot": dict(
            decoded_phrase_profile.get("legal_phrase_texts_by_slot") or {}
        ),
        "decoded_provenance_phrase_texts_by_slot": dict(
            decoded_phrase_profile.get("provenance_phrase_texts_by_slot") or {}
        ),
        "source_salient_token_count": int(
            reconstruction_token_profile.get("source_salient_token_count") or 0
        ),
        "decoded_salient_token_count": int(
            reconstruction_token_profile.get("decoded_salient_token_count") or 0
        ),
        "matched_salient_token_count": int(
            reconstruction_token_profile.get("matched_salient_token_count") or 0
        ),
        "unreconstructed_source_tokens": list(
            reconstruction_token_profile.get("unreconstructed_source_tokens") or []
        ),
        "added_decoded_tokens": list(
            reconstruction_token_profile.get("added_decoded_tokens") or []
        ),
        "salient_token_coverage_rate": float(
            reconstruction_token_profile.get("salient_token_coverage_rate") or 0.0
        ),
        "decoded_token_precision_rate": float(
            reconstruction_token_profile.get("decoded_token_precision_rate") or 0.0
        ),
        "top_level_symbol": target_parse_profile.get("top_level_symbol", ""),
        "parse_wrappers": list(target_parse_profile.get("wrapper_sequence") or []),
        "parse_atom_symbols": list(target_parse_profile.get("atom_symbols") or []),
        "parse_connectives": list(target_parse_profile.get("connectives") or []),
        "parse_quantifier_variables": list(
            target_parse_profile.get("quantifier_variables") or []
        ),
        "parse_quantifier_scope_count": len(
            target_parse_profile.get("quantifier_scopes") or []
        ),
        "parse_quantifier_scopes": list(
            target_parse_profile.get("quantifier_scopes") or []
        ),
        "parse_deontic_scope_count": len(
            target_parse_profile.get("deontic_scopes") or []
        ),
        "parse_deontic_scopes": list(
            target_parse_profile.get("deontic_scopes") or []
        ),
        "parse_deontic_operator_sequence": list(
            target_parse_profile.get("deontic_operator_sequence") or []
        ),
        "parse_deontic_scope_symbols": list(
            target_parse_profile.get("deontic_scope_symbols") or []
        ),
        "parse_frame_slots": list(target_parse_profile.get("frame_slots") or []),
        "parse_event_predicates": list(
            target_parse_profile.get("event_predicates") or []
        ),
    }


def _semantic_formula_profile(
    source_symbols: Sequence[str],
    exported_symbols: Sequence[str],
    formula_slots: Sequence[str],
) -> Dict[str, Any]:
    """Classify the target-visible formula semantics for Phase 8 reports."""

    symbols = _ordered_unique(source_symbols)
    symbol_source = "source_formula_symbols"
    if not symbols:
        symbols = _ordered_unique(exported_symbols)
        symbol_source = "exported_formula_symbols"

    predicate = _semantic_formula_predicate(symbols)
    family = _semantic_formula_family(predicate)
    return {
        "semantic_formula_family": family,
        "semantic_formula_predicate": predicate,
        "semantic_formula_symbols": symbols,
        "semantic_formula_source": symbol_source,
        "semantic_formula_slot_count": len(_ordered_unique(formula_slots)),
    }


def _semantic_formula_predicate(symbols: Sequence[str]) -> str:
    ordered_symbols = _ordered_unique(symbols)
    if not ordered_symbols:
        return ""

    frame_predicates = {
        "AppliesTo",
        "Definition",
        "ExemptFrom",
        "ExpiresAfter",
        "Lifecycle",
        "ValidFor",
    }
    for symbol in ordered_symbols:
        if symbol in frame_predicates:
            return symbol
    return ordered_symbols[-1]


def _semantic_formula_family(predicate: str) -> str:
    value = str(predicate or "").strip()
    if not value:
        return "unknown"
    if value == "Definition":
        return "definition"
    if value == "AppliesTo":
        return "applicability_rule"
    if value == "ExemptFrom":
        return "exemption_rule"
    if value == "ValidFor":
        return "instrument_lifecycle_validity"
    if value == "ExpiresAfter":
        return "instrument_lifecycle_expiration"
    if value == "Lifecycle":
        return "instrument_lifecycle"
    if value.startswith((
        "Arbitrate",
        "Conciliate",
        "Mediate",
        "Negotiate",
        "Settle",
    )):
        return "dispute_resolution_duty"
    if value.startswith((
        "DepositSecurity",
        "EstablishEscrow",
        "MaintainLiabilityInsurance",
        "PostBond",
        "ProvideProofInsurance",
        "ReleaseBond",
    )):
        return "financial_assurance_duty"
    if value.startswith((
        "Continue",
        "Defer",
        "Extend",
        "Postpone",
        "Stay",
        "Waive",
    )):
        return "administrative_relief_duty"
    if value.startswith((
        "AdministerAgreement",
        "AdministerContract",
        "AdministerProcurement",
        "Award",
        "OpenBid",
        "OpenBids",
        "OpenProposal",
        "OpenProposals",
        "Procure",
        "SelectBidder",
        "SelectContractor",
        "SelectVendor",
        "Solicit",
    )):
        return "procurement_contracting_duty"
    if value.startswith((
        "Acknowledge",
        "Authenticate",
        "Attest",
        "Confirm",
        "Notarize",
        "Ratify",
    )):
        return "document_authentication_duty"
    if value.startswith((
        "PermitInspection",
        "ProvideAccess",
        "ProvideCopy",
        "ProvidePublicAccess",
        "ProvideRecordsInspection",
    )):
        return "public_access_records_duty"
    if value.startswith((
        "Announce",
        "Circulate",
        "Disseminate",
        "Display",
        "Distribute",
        "Post",
        "Transmit",
    )):
        return "public_information_duty"
    if value.startswith(("Comment", "Object", "Respond")):
        return "review_participation_duty"
    if value.startswith(("Abate", "Enforce", "Mitigate", "Remediate", "Remedy")):
        return "enforcement_remedy_duty"
    if value.startswith(("Condemn", "Embargo", "Quarantine", "Recall")):
        return "regulatory_control_duty"
    if value.startswith((
        "Analyze",
        "Diagnose",
        "Examine",
        "Immunize",
        "Screen",
        "Vaccinate",
    )):
        return "health_compliance_duty"
    if value.startswith((
        "Adjudicate",
        "Decide",
        "Dismiss",
        "Dispose",
        "Find",
    )):
        return "judicial_disposition_duty"
    if value.startswith(("FileAppeal", "MakeAppeal", "SubmitAppeal")):
        return "administrative_review_request_duty"
    if value.startswith((
        "Accession",
        "DocumentChainCustody",
        "InventoryEvidence",
        "PreserveEvidence",
    )):
        return "evidence_custody_duty"
    if value.startswith((
        "Anonymize",
        "Decrypt",
        "Deidentify",
        "Destroy",
        "Detokenize",
        "Encrypt",
        "Erase",
        "Expunge",
        "Hash",
        "Mask",
        "Pseudonymize",
        "Redact",
        "Seal",
        "Tokenize",
        "Unseal",
    )):
        return "data_protection_duty"
    if value.startswith((
        "Archive",
        "Memorialize",
        "Preserve",
        "Record",
        "Restore",
        "Retain",
    )):
        return "legal_recordkeeping_duty"
    if value.startswith((
        "Catalog",
        "Index",
        "Interpret",
        "Summarize",
        "Transcribe",
        "Translate",
    )):
        return "records_information_processing_duty"
    if value.startswith((
        "Compare",
        "CrossCheck",
        "Deduplicate",
        "Match",
        "Normalize",
        "Validate",
    )):
        return "data_quality_processing_duty"
    if value.startswith(("Cancel", "Revoke", "Suspend")):
        return "instrument_status_duty"
    return "ordinary_duty"


def _target_quality_gate(
    norm: LegalNormIR,
    target: str,
    formula_record: Dict[str, Any],
    diagnostics: Sequence[Dict[str, Any]],
    alignment_summary: Dict[str, Any],
    symbol_alignment: Dict[str, Any],
    target_dialect_profile: Dict[str, Any],
    target_parse_profile: Dict[str, Any],
    reconstruction_token_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a compact Phase 8 quality gate for one target formula.

    Syntax validity is necessary but not enough for a proof/export quality
    report. This record joins syntax, formula readiness, target dialect shape,
    symbol preservation, decoder alignment, and reconstruction token coverage
    without changing parser proof-readiness or repair gates.
    """

    diagnostic_codes = [
        str(item.get("code") or "").strip()
        for item in diagnostics
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    syntax_valid = not diagnostic_codes
    formula_proof_ready = bool(formula_record.get("proof_ready") is True)
    formula_requires_validation = bool(
        formula_record.get("requires_validation") is not False
    )
    slot_alignment_complete = bool(
        alignment_summary.get("alignment_complete") is True
    )
    symbol_alignment_complete = bool(
        symbol_alignment.get("target_symbol_alignment_complete") is True
    )
    dialect_complete = bool(
        target_dialect_profile.get("target_dialect_profile_complete") is True
    )
    parse_complete = bool(
        target_parse_profile.get("target_parse_profile_complete") is True
    )
    token_complete = bool(
        reconstruction_token_profile.get("reconstruction_token_profile_complete")
        is True
    )
    formula_slot_coverage = _formula_slot_coverage_profile(alignment_summary)
    known_local_target = target in LOCAL_PROVER_TARGETS
    structural_checks_complete = all(
        (
            symbol_alignment_complete,
            dialect_complete,
            parse_complete,
            token_complete,
            known_local_target,
        )
    )
    formal_validation_complete = bool(
        syntax_valid
        and formula_proof_ready
        and not formula_requires_validation
        and structural_checks_complete
    )
    parser_theorem_promotable = bool(norm.proof_ready and formal_validation_complete)

    failed_checks: List[str] = []
    if not syntax_valid:
        failed_checks.append("syntax")
    if not formula_proof_ready:
        failed_checks.append("formula_proof_ready")
    if formula_requires_validation:
        failed_checks.append("formula_requires_validation")
    if not symbol_alignment_complete:
        failed_checks.append("symbol_alignment")
    if not dialect_complete:
        failed_checks.append("target_dialect")
    if not parse_complete:
        failed_checks.append("target_parse")
    if not token_complete:
        failed_checks.append("reconstruction_tokens")
    if not known_local_target:
        failed_checks.append("known_local_target")

    quality_checks = _target_quality_gate_checks(
        syntax_valid=syntax_valid,
        formula_proof_ready=formula_proof_ready,
        formula_requires_validation=formula_requires_validation,
        symbol_alignment_complete=symbol_alignment_complete,
        dialect_complete=dialect_complete,
        parse_complete=parse_complete,
        token_complete=token_complete,
        known_local_target=known_local_target,
        diagnostic_codes=diagnostic_codes,
    )
    quality_blockers = [
        record["blocker"]
        for record in quality_checks
        if record.get("passed") is False and record.get("blocking") is True
    ]
    source_grounding_diagnostics = {
        "parser_warnings": list(norm.quality.parser_warnings),
        "blockers": list(norm.blockers),
        "missing_ir_slots": list(alignment_summary.get("decoded_missing_grounded_ir_slots") or []),
        "ungrounded_decoded_slots": list(alignment_summary.get("ungrounded_decoded_slots") or []),
        "formula_missing_decoded_slots": list(
            alignment_summary.get("formula_missing_decoded_slots") or []
        ),
        "formula_ungrounded_slots": list(alignment_summary.get("formula_ungrounded_slots") or []),
        "formula_slot_coverage": formula_slot_coverage,
        "omitted_formula_slot_names": list(
            alignment_summary.get("omitted_formula_slot_names") or []
        ),
        "missing_exported_formula_symbols": list(
            symbol_alignment.get("missing_exported_formula_symbols") or []
        ),
        "unreconstructed_source_tokens": list(
            reconstruction_token_profile.get("unreconstructed_source_tokens") or []
        ),
        "added_decoded_tokens": list(
            reconstruction_token_profile.get("added_decoded_tokens") or []
        ),
    }

    fingerprint = _stable_fingerprint(
        norm.source_id,
        target,
        str(syntax_valid),
        str(formula_proof_ready),
        str(formula_requires_validation),
        str(structural_checks_complete),
        str(formal_validation_complete),
        str(parser_theorem_promotable),
        "|".join(failed_checks),
        "|".join(quality_blockers),
        "|".join(diagnostic_codes),
    )
    return {
        "target": target,
        "known_local_target": known_local_target,
        "syntax_valid": syntax_valid,
        "diagnostic_codes": diagnostic_codes,
        "formula_proof_ready": formula_proof_ready,
        "formula_requires_validation": formula_requires_validation,
        "parser_proof_ready": bool(norm.proof_ready),
        "slot_alignment_complete": slot_alignment_complete,
        "formula_slot_coverage": formula_slot_coverage,
        "target_symbol_alignment_complete": symbol_alignment_complete,
        "target_dialect_profile_complete": dialect_complete,
        "target_parse_profile_complete": parse_complete,
        "reconstruction_token_profile_complete": token_complete,
        "structural_checks_complete": structural_checks_complete,
        "formal_validation_complete": formal_validation_complete,
        "parser_theorem_promotable": parser_theorem_promotable,
        "failed_quality_checks": failed_checks,
        "quality_gate_checks": quality_checks,
        "quality_gate_blockers": quality_blockers,
        "source_grounding_diagnostics": source_grounding_diagnostics,
        "target_quality_gate_fingerprint": fingerprint,
    }


def _formula_slot_coverage_profile(alignment_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Return target-independent coverage diagnostics for formula slots.

    Formula slots are the IR slots that materially contributed to the exported
    theorem text. The quality gate keeps this profile separate from the broader
    decoder/IR alignment so lossy reconstruction of a formula antecedent is
    visible even when target syntax and symbol checks pass.
    """

    formula_slots = _ordered_unique(alignment_summary.get("formula_slots") or [])
    decoded_overlap = set(
        _ordered_unique(alignment_summary.get("decoded_formula_overlap") or [])
    )
    grounded_overlap = set(
        _ordered_unique(alignment_summary.get("grounded_formula_overlap") or [])
    )
    decoded_formula_slots = [slot for slot in formula_slots if slot in decoded_overlap]
    grounded_formula_slots = [slot for slot in formula_slots if slot in grounded_overlap]
    missing_decoded = _ordered_unique(
        alignment_summary.get("formula_missing_decoded_slots") or []
    )
    ungrounded = _ordered_unique(alignment_summary.get("formula_ungrounded_slots") or [])
    omitted = _ordered_unique(alignment_summary.get("omitted_formula_slot_names") or [])
    formula_slot_count = len(formula_slots)
    decoded_count = len(decoded_formula_slots)
    grounded_count = len(grounded_formula_slots)
    complete = not missing_decoded and not ungrounded
    return {
        "formula_slots": formula_slots,
        "decoded_formula_slots": decoded_formula_slots,
        "grounded_formula_slots": grounded_formula_slots,
        "missing_decoded_formula_slots": missing_decoded,
        "ungrounded_formula_slots": ungrounded,
        "omitted_formula_slot_names": omitted,
        "formula_slot_count": formula_slot_count,
        "decoded_formula_slot_count": decoded_count,
        "grounded_formula_slot_count": grounded_count,
        "omitted_formula_slot_count": len(omitted),
        "formula_slot_decoder_rate": round(decoded_count / formula_slot_count, 6)
        if formula_slot_count
        else 1.0,
        "formula_slot_grounding_rate": round(grounded_count / formula_slot_count, 6)
        if formula_slot_count
        else 1.0,
        "formula_slot_coverage_complete": complete,
    }


def _target_quality_gate_checks(
    *,
    syntax_valid: bool,
    formula_proof_ready: bool,
    formula_requires_validation: bool,
    symbol_alignment_complete: bool,
    dialect_complete: bool,
    parse_complete: bool,
    token_complete: bool,
    known_local_target: bool,
    diagnostic_codes: Sequence[str],
) -> List[Dict[str, Any]]:
    checks = [
        (
            "syntax",
            syntax_valid,
            "syntax diagnostics must be empty",
            list(diagnostic_codes),
        ),
        (
            "formula_proof_ready",
            formula_proof_ready,
            "formula record must be proof-ready",
            [],
        ),
        (
            "formula_requires_validation",
            not formula_requires_validation,
            "formula record must not require validation",
            [],
        ),
        (
            "symbol_alignment",
            symbol_alignment_complete,
            "target formula must preserve source formula symbols",
            [],
        ),
        (
            "target_dialect",
            dialect_complete,
            "target dialect profile must be complete",
            [],
        ),
        (
            "target_parse",
            parse_complete,
            "target parse profile must be complete",
            [],
        ),
        (
            "reconstruction_tokens",
            token_complete,
            "decoder reconstruction token profile must be complete",
            [],
        ),
        (
            "known_local_target",
            known_local_target,
            "target must be one of the local prover dialects",
            [],
        ),
    ]
    return [
        {
            "check": name,
            "passed": bool(passed),
            "blocking": True,
            "blocker": "" if passed else f"failed_prover_quality_check:{name}",
            "description": description,
            "diagnostic_codes": codes,
        }
        for name, passed, description, codes in checks
    ]


_RECONSTRUCTION_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "must",
    "not",
    "of",
    "provided",
    "shall",
    "that",
    "the",
    "to",
}


def _reconstruction_token_profile(
    target: str,
    norm: LegalNormIR,
    decoded_text: str,
) -> Dict[str, Any]:
    """Compare source and decoded salient legal tokens for Phase 8 audits."""

    source_text = str(norm.source_text or norm.support_text or "").strip()
    source_tokens = _salient_reconstruction_tokens(source_text)
    decoded_tokens = _salient_reconstruction_tokens(decoded_text)
    source_set = set(source_tokens)
    decoded_set = set(decoded_tokens)
    matched_tokens = [token for token in source_tokens if token in decoded_set]
    unreconstructed_tokens = [token for token in source_tokens if token not in decoded_set]
    added_tokens = [token for token in decoded_tokens if token not in source_set]
    coverage_rate = round(len(matched_tokens) / len(source_tokens), 6) if source_tokens else 1.0
    precision_rate = round(
        sum(1 for token in decoded_tokens if token in source_set) / len(decoded_tokens),
        6,
    ) if decoded_tokens else 1.0
    complete = not unreconstructed_tokens and not added_tokens
    fingerprint = _stable_fingerprint(
        target,
        norm.source_id,
        "|".join(source_tokens),
        "|".join(decoded_tokens),
        "|".join(unreconstructed_tokens),
        "|".join(added_tokens),
        str(complete),
    )
    return {
        "target": target,
        "source_text_basis": "source_text" if norm.source_text else "support_text",
        "source_salient_tokens": source_tokens,
        "decoded_salient_tokens": decoded_tokens,
        "matched_salient_tokens": matched_tokens,
        "unreconstructed_source_tokens": unreconstructed_tokens,
        "added_decoded_tokens": added_tokens,
        "source_salient_token_count": len(source_tokens),
        "decoded_salient_token_count": len(decoded_tokens),
        "matched_salient_token_count": len(matched_tokens),
        "salient_token_coverage_rate": coverage_rate,
        "decoded_token_precision_rate": precision_rate,
        "reconstruction_token_profile_complete": complete,
        "reconstruction_token_profile_fingerprint": fingerprint,
    }


def _salient_reconstruction_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    for token in re.findall(r"[A-Za-z0-9]+", str(text or "").lower()):
        if token in _RECONSTRUCTION_TOKEN_STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _target_parse_profile(target: str, exported_formula: str) -> Dict[str, Any]:
    """Return a compact deterministic parse profile for the rendered dialect.

    This is intentionally syntax-only. It exposes the target-visible structure
    that the local validators inspected so Phase 8 reports can distinguish a
    valid string from the kind of formula accepted by a target adapter.
    """

    text = str(exported_formula or "").strip()
    top_level_symbol = _top_level_symbol(text)
    wrapper_sequence = _wrapper_sequence(text)
    atom_symbols = _formula_symbols(text)
    connectives = _target_connectives(text)
    quantifier_variables = _quantifier_variables(text)
    quantifier_scopes = _quantifier_scope_profiles(text)
    deontic_scopes = _deontic_scope_profiles(text)
    frame_slots = _frame_slots(text) if target == "frame_logic" else []
    event_predicates = _event_predicates(text) if target == "deontic_cec" else []
    complete = bool(
        text
        and top_level_symbol
        and _target_parse_profile_shape_complete(
            target,
            top_level_symbol,
            wrapper_sequence,
            frame_slots,
            event_predicates,
        )
    )
    fingerprint = _stable_fingerprint(
        target,
        top_level_symbol,
        "|".join(wrapper_sequence),
        "|".join(atom_symbols),
        "|".join(connectives),
        "|".join(quantifier_variables),
        _scope_profiles_fingerprint_part(quantifier_scopes),
        _scope_profiles_fingerprint_part(deontic_scopes),
        "|".join(frame_slots),
        "|".join(event_predicates),
        str(complete),
    )
    return {
        "target": target,
        "top_level_symbol": top_level_symbol,
        "wrapper_sequence": wrapper_sequence,
        "atom_symbols": atom_symbols,
        "connectives": connectives,
        "quantifier_variables": quantifier_variables,
        "quantifier_scopes": quantifier_scopes,
        "quantifier_scope_count": len(quantifier_scopes),
        "deontic_scopes": deontic_scopes,
        "deontic_scope_count": len(deontic_scopes),
        "deontic_operator_sequence": [
            scope["operator"] for scope in deontic_scopes
        ],
        "deontic_scope_symbols": _ordered_unique(
            symbol
            for scope in deontic_scopes
            for symbol in scope.get("formula_symbols", [])
        ),
        "frame_slots": frame_slots,
        "event_predicates": event_predicates,
        "contains_quantifier": bool(quantifier_variables),
        "target_parse_profile_complete": complete,
        "target_parse_profile_fingerprint": fingerprint,
    }


def _top_level_symbol(text: str) -> str:
    match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[\(\[]", text)
    if match:
        return match.group(1)
    if re.match(r"^\s*forall\s+[A-Za-z][A-Za-z0-9_]*\.", text):
        return "forall"
    return ""


def _wrapper_sequence(text: str) -> List[str]:
    wrappers: List[str] = []
    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(", text):
        wrapper = match.group(1)
        if wrapper in {"legal_norm", "Happens", "HoldsAt", "always", "O", "P", "F"}:
            wrappers.append(wrapper)
    return wrappers


def _target_connectives(text: str) -> List[str]:
    connectives: List[str] = []
    for symbol, pattern in (
        ("forall", r"\bforall\s+[A-Za-z][A-Za-z0-9_]*\."),
        ("and", r"\band\b"),
        ("or", r"\bor\b"),
        ("not", r"\bnot\b"),
        ("implies", r"(?:->|=>)"),
    ):
        if re.search(pattern, text):
            connectives.append(symbol)
    return connectives


def _quantifier_variables(text: str) -> List[str]:
    variables: List[str] = []
    for variable in re.findall(r"\bforall\s+([A-Za-z][A-Za-z0-9_]*)\.", text):
        if variable not in variables:
            variables.append(variable)
    return variables


def _quantifier_scope_profiles(text: str) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for match in re.finditer(r"\bforall\s+([A-Za-z][A-Za-z0-9_]*)\.\s*", text):
        variable = match.group(1)
        scope_text = _balanced_scope_after(text, match.end())
        if not scope_text:
            continue
        antecedent, consequent = _split_implication_scope(scope_text)
        profile = {
            "variable": variable,
            "scope_text": scope_text,
            "matrix_symbols": _formula_symbols(scope_text),
            "antecedent_symbols": _formula_symbols(antecedent),
            "consequent_symbols": _formula_symbols(consequent),
            "has_implication": bool(consequent),
        }
        profiles.append(profile)
    return profiles


def _deontic_scope_profiles(text: str) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for match in re.finditer(r"\b([OPF])\s*\(", text):
        operator = match.group(1)
        scope_text = _balanced_scope_after(text, match.end() - 1)
        if not scope_text:
            continue
        profiles.append(
            {
                "operator": operator,
                "scope_text": scope_text,
                "formula_symbols": _formula_symbols(scope_text),
                "quantifier_variables": _quantifier_variables(scope_text),
                "contains_quantifier": bool(_quantifier_variables(scope_text)),
            }
        )
    return profiles


def _balanced_scope_after(text: str, start_index: int) -> str:
    value = str(text or "")
    index = start_index
    while index < len(value) and value[index].isspace():
        index += 1
    if index >= len(value):
        return ""
    if value[index] != "(":
        return value[index:].strip()

    depth = 0
    for cursor in range(index, len(value)):
        char = value[cursor]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return value[index + 1 : cursor].strip()
    return ""


def _split_implication_scope(scope_text: str) -> tuple[str, str]:
    text = str(scope_text or "").strip()
    match = re.search(r"(?:->|=>)", text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def _scope_profiles_fingerprint_part(profiles: Sequence[Mapping[str, Any]]) -> str:
    parts: List[str] = []
    for profile in profiles:
        if "variable" in profile:
            parts.append(
                "forall:"
                + str(profile.get("variable") or "")
                + ":"
                + "|".join(profile.get("matrix_symbols") or [])
                + ":"
                + "|".join(profile.get("antecedent_symbols") or [])
                + ":"
                + "|".join(profile.get("consequent_symbols") or [])
            )
        elif "operator" in profile:
            parts.append(
                "deontic:"
                + str(profile.get("operator") or "")
                + ":"
                + "|".join(profile.get("formula_symbols") or [])
                + ":"
                + "|".join(profile.get("quantifier_variables") or [])
            )
    return ";".join(parts)


def _frame_slots(text: str) -> List[str]:
    match = re.match(r"^legal_norm\([^)]+\)\[(.+)\]$", text)
    if not match:
        return []
    slots: List[str] = []
    for slot in re.findall(r"([A-Za-z][A-Za-z0-9_]*)->", match.group(1)):
        if slot not in slots:
            slots.append(slot)
    return slots


def _event_predicates(text: str) -> List[str]:
    predicates: List[str] = []
    for predicate in re.findall(r"\b(Happens|HoldsAt)\s*\(", text):
        if predicate not in predicates:
            predicates.append(predicate)
    return predicates


def _target_parse_profile_shape_complete(
    target: str,
    top_level_symbol: str,
    wrapper_sequence: Sequence[str],
    frame_slots: Sequence[str],
    event_predicates: Sequence[str],
) -> bool:
    wrappers = list(wrapper_sequence)
    if target == "frame_logic":
        return top_level_symbol == "legal_norm" and list(frame_slots) == [
            "actor",
            "action",
            "formula",
        ]
    if target == "deontic_cec":
        return top_level_symbol == "Happens" and list(event_predicates) == [
            "Happens",
            "HoldsAt",
        ]
    if target == "fol":
        return top_level_symbol in {
            "forall",
            "AppliesTo",
            "Definition",
            "ExemptFrom",
            "ValidFor",
            "ExpiresAfter",
            "Lifecycle",
        }
    if target == "deontic_fol":
        return (
            bool(top_level_symbol)
            and "always" not in wrappers
            and "Happens" not in wrappers
        )
    if target == "deontic_temporal_fol":
        return top_level_symbol == "always" and "always" in wrappers
    return False


def _target_dialect_profile(
    target: str,
    formula: str,
    exported_formula: str,
    norm: LegalNormIR,
) -> Dict[str, Any]:
    """Describe target-specific syntax obligations for audit records.

    The syntax validator should expose not only whether a target string parsed,
    but why that string belongs to the requested local dialect. This profile is
    deterministic metadata derived from the target name and rendered formula.
    """

    text = str(exported_formula or "").strip()
    source_operator = _source_deontic_operator(formula, norm)
    policy = _target_dialect_policy(target)
    required_wrappers = list(policy["required_wrappers"])
    forbidden_wrappers = list(policy["forbidden_wrappers"])
    present_wrappers = _present_target_wrappers(text)
    required_present = all(wrapper in present_wrappers for wrapper in required_wrappers)
    forbidden_absent = all(wrapper not in present_wrappers for wrapper in forbidden_wrappers)
    display_connectives_absent = not bool(re.search(r"[∀∧∨→¬]", text))
    quantifier_present = "forall x." in text
    quantifier_policy = str(policy["quantifier_policy"])
    quantifier_ok = (
        quantifier_present
        if quantifier_policy == "required"
        else not quantifier_present
        if quantifier_policy == "forbidden"
        else True
    )
    deontic_operator_preserved = (
        source_operator == ""
        or source_operator not in {"O", "P", "F"}
        or source_operator in present_wrappers
        or target == "fol"
    )
    complete = (
        required_present
        and forbidden_absent
        and display_connectives_absent
        and quantifier_ok
        and deontic_operator_preserved
    )
    fingerprint = _stable_fingerprint(
        target,
        policy["dialect_family"],
        "|".join(required_wrappers),
        "|".join(forbidden_wrappers),
        "|".join(present_wrappers),
        quantifier_policy,
        str(complete),
    )
    return {
        "target": target,
        "dialect_family": policy["dialect_family"],
        "formula_role": _target_formula_role(target),
        "connective_style": "ascii",
        "source_deontic_operator": source_operator,
        "required_wrappers": required_wrappers,
        "forbidden_wrappers": forbidden_wrappers,
        "present_wrappers": present_wrappers,
        "required_wrappers_present": required_present,
        "forbidden_wrappers_absent": forbidden_absent,
        "display_connectives_absent": display_connectives_absent,
        "quantifier_policy": quantifier_policy,
        "quantifier_present": quantifier_present,
        "quantifier_policy_satisfied": quantifier_ok,
        "deontic_operator_preserved": deontic_operator_preserved,
        "target_dialect_profile_complete": complete,
        "target_dialect_profile_fingerprint": fingerprint,
    }


def _target_dialect_policy(target: str) -> Dict[str, Any]:
    policies: Dict[str, Dict[str, Any]] = {
        "frame_logic": {
            "dialect_family": "frame_logic",
            "required_wrappers": ("legal_norm",),
            "forbidden_wrappers": ("Happens", "HoldsAt", "always"),
            "quantifier_policy": "optional",
        },
        "deontic_cec": {
            "dialect_family": "event_calculus",
            "required_wrappers": ("Happens", "HoldsAt"),
            "forbidden_wrappers": ("always",),
            "quantifier_policy": "optional",
        },
        "fol": {
            "dialect_family": "first_order",
            "required_wrappers": (),
            "forbidden_wrappers": ("Happens", "HoldsAt", "always", "O", "P", "F"),
            "quantifier_policy": "optional",
        },
        "deontic_fol": {
            "dialect_family": "deontic_first_order",
            "required_wrappers": (),
            "forbidden_wrappers": ("Happens", "HoldsAt", "always"),
            "quantifier_policy": "optional",
        },
        "deontic_temporal_fol": {
            "dialect_family": "deontic_temporal_first_order",
            "required_wrappers": ("always",),
            "forbidden_wrappers": ("Happens", "HoldsAt"),
            "quantifier_policy": "optional",
        },
    }
    return policies.get(
        target,
        {
            "dialect_family": "unknown",
            "required_wrappers": (),
            "forbidden_wrappers": (),
            "quantifier_policy": "optional",
        },
    )


def _present_target_wrappers(exported_formula: str) -> List[str]:
    text = str(exported_formula or "")
    wrappers: List[str] = []
    for wrapper in ("legal_norm", "Happens", "HoldsAt", "always", "O", "P", "F"):
        if re.search(r"\b" + re.escape(wrapper) + r"\s*\(", text):
            wrappers.append(wrapper)
    return wrappers


def _source_deontic_operator(formula: str, norm: LegalNormIR) -> str:
    text = str(formula or "").strip()
    if len(text) > 2 and text[0] in {"O", "P", "F"} and text[1] == "(":
        return text[0]
    modality = str(norm.modality or "").strip().upper()
    return modality if modality in {"O", "P", "F"} else ""


def _target_symbol_alignment(
    target: str,
    formula: str,
    exported_formula: str,
) -> Dict[str, Any]:
    """Audit whether target rendering preserved formal formula symbols.

    Syntax checks catch malformed target strings, while slot alignment checks
    that decoded legal slots and formula slots agree. This audit focuses on the
    rendered target formula itself: every predicate or frame symbol in the
    source formula must still be visible in the target dialect.
    """

    source_symbols = _formula_symbols(formula)
    exported_symbols = _formula_symbols(exported_formula)
    exported_symbol_set = set(exported_symbols)
    missing_symbols = [
        symbol for symbol in source_symbols if symbol not in exported_symbol_set
    ]
    extra_symbols = [
        symbol for symbol in exported_symbols if symbol not in set(source_symbols)
    ]
    complete = not missing_symbols
    fingerprint = _stable_fingerprint(
        target,
        "|".join(source_symbols),
        "|".join(exported_symbols),
        "|".join(missing_symbols),
        str(complete),
    )
    return {
        "target": target,
        "source_formula_symbols": source_symbols,
        "exported_formula_symbols": exported_symbols,
        "missing_exported_formula_symbols": missing_symbols,
        "extra_exported_formula_symbols": extra_symbols,
        "source_formula_symbol_count": len(source_symbols),
        "exported_formula_symbol_count": len(exported_symbols),
        "target_symbol_alignment_complete": complete,
        "target_symbol_alignment_fingerprint": fingerprint,
    }


def _target_semantic_bridge_profile(
    target: str,
    norm: LegalNormIR,
    formula_record: Dict[str, Any],
    decoded_slot_summary: Dict[str, List[str]],
    ir_slot_summary: Dict[str, Any],
    alignment_summary: Dict[str, Any],
    symbol_alignment: Dict[str, Any],
) -> Dict[str, Any]:
    """Join formula, decoder, IR, and target-symbol audits for one target."""

    decoded_slots = _ordered_unique(decoded_slot_summary.get("decoded_slots") or [])
    grounded_ir_slots = _ordered_unique(ir_slot_summary.get("grounded_ir_slots") or [])
    formula_slots = _ordered_unique(alignment_summary.get("formula_slots") or [])
    decoded_formula_overlap = [slot for slot in formula_slots if slot in decoded_slots]
    grounded_formula_overlap = [
        slot for slot in formula_slots if slot in grounded_ir_slots
    ]
    formula_missing_decoded = _ordered_unique(
        alignment_summary.get("formula_missing_decoded_slots") or []
    )
    formula_ungrounded = _ordered_unique(
        alignment_summary.get("formula_ungrounded_slots") or []
    )
    omitted_formula_slots = _ordered_unique(
        alignment_summary.get("omitted_formula_slot_names") or []
    )
    missing_symbols = _ordered_unique(
        symbol_alignment.get("missing_exported_formula_symbols") or []
    )
    semantic_profile = _semantic_formula_profile(
        symbol_alignment.get("source_formula_symbols") or [],
        symbol_alignment.get("exported_formula_symbols") or [],
        formula_slots,
    )

    blockers: List[str] = []
    blockers.extend(
        f"formula_slot_missing_from_decoder:{slot}"
        for slot in formula_missing_decoded
    )
    blockers.extend(f"formula_slot_ungrounded:{slot}" for slot in formula_ungrounded)
    blockers.extend(f"target_symbol_missing:{symbol}" for symbol in missing_symbols)
    if semantic_profile["semantic_formula_family"] == "unknown":
        blockers.append("unknown_semantic_formula_family")
    if formula_record.get("requires_validation") is not False:
        blockers.append("formula_requires_validation")

    complete = not blockers
    fingerprint = _stable_fingerprint(
        target,
        norm.source_id,
        semantic_profile["semantic_formula_family"],
        semantic_profile["semantic_formula_predicate"],
        "|".join(formula_slots),
        "|".join(decoded_formula_overlap),
        "|".join(grounded_formula_overlap),
        "|".join(blockers),
        str(complete),
    )
    return {
        "target": target,
        "source_id": norm.source_id,
        "semantic_formula_family": semantic_profile["semantic_formula_family"],
        "semantic_formula_predicate": semantic_profile["semantic_formula_predicate"],
        "semantic_formula_symbols": semantic_profile["semantic_formula_symbols"],
        "formula_slots": formula_slots,
        "decoded_slots": decoded_slots,
        "grounded_ir_slots": grounded_ir_slots,
        "decoded_formula_overlap": decoded_formula_overlap,
        "grounded_formula_overlap": grounded_formula_overlap,
        "formula_missing_decoded_slots": formula_missing_decoded,
        "formula_ungrounded_slots": formula_ungrounded,
        "omitted_formula_slot_names": omitted_formula_slots,
        "missing_exported_formula_symbols": missing_symbols,
        "semantic_bridge_complete": complete,
        "semantic_bridge_requires_validation": not complete,
        "semantic_bridge_blockers": blockers,
        "target_semantic_bridge_fingerprint": fingerprint,
    }


_FORMULA_SYMBOL_STOPWORDS = {
    "O",
    "P",
    "F",
    "DEF",
    "APP",
    "EXEMPT",
    "LIFE",
    "forall",
    "exists",
    "and",
    "or",
    "not",
    "always",
    "Happens",
    "HoldsAt",
    "legal_norm",
    "actor",
    "action",
    "formula",
    "source",
    "unknown",
    "ForallX",
    "t",
    "x",
}


def _formula_symbols(formula: str) -> List[str]:
    text = _to_ascii_logic(str(formula or ""))
    symbols: List[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text):
        if token in _FORMULA_SYMBOL_STOPWORDS:
            continue
        if token.lower() in _FORMULA_SYMBOL_STOPWORDS:
            continue
        if token.startswith("deontic_"):
            continue
        normalized = _canonical_formula_symbol(token)
        if normalized in _FORMULA_SYMBOL_STOPWORDS:
            continue
        if normalized.lower() in _FORMULA_SYMBOL_STOPWORDS:
            continue
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    return symbols


def _canonical_formula_symbol(symbol: str) -> str:
    value = str(symbol or "").strip("_")
    if not value:
        return ""
    for prefix in ("And", "Or", "Not"):
        if value.startswith(prefix) and len(value) > len(prefix):
            remainder = value[len(prefix) :]
            if remainder[:1].isupper():
                value = remainder
                break
    if "_" not in value:
        return value
    parts = [
        part
        for part in value.split("_")
        if part and part.lower() not in _FORMULA_SYMBOL_STOPWORDS
    ]
    if not parts:
        return ""
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _ir_semantic_fingerprint(
    norm: LegalNormIR,
    formula: str,
    decoded_slots: Sequence[str],
    grounded_ir_slots: Sequence[str] = (),
) -> str:
    return _stable_fingerprint(
        norm.schema_version,
        norm.source_id,
        norm.norm_type,
        norm.modality,
        norm.actor,
        norm.action,
        formula,
        "|".join(decoded_slots),
        "|".join(grounded_ir_slots),
    )


def _stable_fingerprint(*parts: Any) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _target_shape_diagnostics(target: str, exported_formula: str) -> List[Dict[str, Any]]:
    text = str(exported_formula or "").strip()
    diagnostics: List[Dict[str, Any]] = []
    if not text or target not in LOCAL_PROVER_TARGETS:
        return diagnostics

    if target == "frame_logic" and not re.match(
        r"^legal_norm\([A-Za-z0-9_]+\)\[actor->[A-Za-z][A-Za-z0-9_]*; action->[A-Za-z][A-Za-z0-9_]*; formula->[A-Za-z0-9_().,\->=]+\]$",
        text,
    ):
        diagnostics.append({
            "code": "frame_logic_shape",
            "message": "frame logic target must render a legal_norm frame with actor, action, and formula slots",
        })
    elif target == "deontic_cec" and not re.match(
        r"^Happens\(legal_norm\([A-Za-z0-9_]+\), t\) => HoldsAt\(.+, t\)$",
        text,
    ):
        diagnostics.append({
            "code": "deontic_cec_shape",
            "message": "deontic CEC target must render Happens(..., t) => HoldsAt(..., t)",
        })
    elif target == "deontic_temporal_fol" and not (
        text.startswith("always(") and text.endswith(")")
    ):
        diagnostics.append({
            "code": "temporal_wrapper",
            "message": "deontic temporal FOL target must wrap the target formula in always(...)",
        })
    elif target == "deontic_fol" and re.match(r"^(?:always|Happens|HoldsAt)\(", text):
        diagnostics.append({
            "code": "deontic_fol_shape",
            "message": "deontic FOL target must not include event-calculus or temporal wrappers",
        })
    elif target == "fol" and re.match(r"^(?:O|P|F|always|Happens|HoldsAt)\(", text):
        diagnostics.append({
            "code": "fol_shape",
            "message": "FOL target must not include deontic, temporal, or event-calculus wrappers",
        })
    return diagnostics


def _balanced_delimiters(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    stack: List[str] = []
    for char in text:
        if char in pairs:
            stack.append(pairs[char])
        elif char in closing:
            if not stack or stack.pop() != char:
                return False
    return not stack


def _strip_deontic_wrapper(formula: str) -> str:
    text = str(formula or "").strip()
    if len(text) > 3 and text[1] == "(" and text[0] in {"O", "P", "F"} and text.endswith(")"):
        return text[2:-1].strip()
    return text


def _to_ascii_deontic_formula(formula: str) -> str:
    text = str(formula or "").strip()
    if len(text) > 3 and text[1] == "(" and text[0] in {"O", "P", "F"} and text.endswith(")"):
        return f"{text[0]}({_to_ascii_logic(text[2:-1])})"
    return _to_ascii_logic(text)


def _to_ascii_logic(formula: str) -> str:
    text = str(formula or "").strip()
    if not text:
        return ""
    text = re.sub(r"∀\s*([A-Za-z][A-Za-z0-9_]*)\s*", r"forall \1. ", text)
    replacements = {
        "∧": "and",
        "∨": "or",
        "→": "->",
        "¬": "not ",
        "≤": "<=",
        "≥": ">=",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"not\s+", "not ", text)
    return text.strip()


def _to_frame_logic_atom(formula: str) -> str:
    text = _to_ascii_logic(formula)
    return re.sub(r"\s+", "_", text).strip("_") or "formula"


def _is_frame_style_formula(formula: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*\(.+\)$", formula.strip()))


def _contains_frame_style_formula(formula: str) -> bool:
    return bool(re.search(r"[A-Za-z][A-Za-z0-9_]*\([^()]+\)", formula.strip()))


def _source_symbol(source_id: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(source_id or "unknown")).strip("_")
    return value or "unknown"


def _predicate_symbol(value: str) -> str:
    words = re.findall(r"[0-9A-Za-z]+", str(value or ""))
    return "".join(word[:1].upper() + word[1:] for word in words) if words else "Unknown"
