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
from .decoder import decode_legal_norm_ir


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
    target_components: Dict[str, Any]
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
    target_components = _target_components(
        target,
        exported_formula,
        ir_slot_summary,
        alignment_summary,
        symbol_alignment,
    )
    diagnostics = _syntax_diagnostics(target, exported_formula)
    syntax_valid = not diagnostics

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
        target_components=target_components,
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


def _target_formula_role(target: str) -> str:
    return {
        "frame_logic": "frame_record",
        "deontic_cec": "event_calculus_state",
        "fol": "first_order_formula",
        "deontic_fol": "deontic_first_order_formula",
        "deontic_temporal_fol": "temporal_deontic_first_order_formula",
    }.get(target, "unknown")


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
) -> Dict[str, Any]:
    text = str(exported_formula or "").strip()
    ir_slot_summary = ir_slot_summary or {}
    alignment_summary = alignment_summary or {}
    symbol_alignment = symbol_alignment or {}
    grounded_ir_slots = list(ir_slot_summary.get("grounded_ir_slots") or [])
    ungrounded_ir_slots = list(ir_slot_summary.get("ungrounded_ir_slots") or [])
    missing_ir_slots = list(ir_slot_summary.get("missing_ir_slots") or [])
    formula_slots = list(alignment_summary.get("formula_slots") or [])
    missing_symbols = list(symbol_alignment.get("missing_exported_formula_symbols") or [])
    source_symbols = list(symbol_alignment.get("source_formula_symbols") or [])
    exported_symbols = list(symbol_alignment.get("exported_formula_symbols") or [])
    return {
        "target": target,
        "formula_role": _target_formula_role(target),
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
    }


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
