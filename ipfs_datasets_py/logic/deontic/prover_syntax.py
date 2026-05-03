"""Syntax-only validation records for deterministic legal norm exports.

This module is deliberately local and conservative. It does not attempt full
theorem proving; it checks that the IR-derived formula can be rendered into the
local prover target dialects with balanced, non-empty syntax and source-grounded
metadata. Full target parser integration can replace these validators target by
target without changing the report shape.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Sequence

from .formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from .ir import LegalNormIR


LOCAL_PROVER_TARGETS = (
    "frame_logic",
    "deontic_cec",
    "fol",
    "deontic_fol",
    "deontic_temporal_fol",
)


@dataclass(frozen=True)
class ProverTargetSyntaxRecord:
    """Syntax validation result for one local prover target."""

    source_id: str
    target: str
    target_version: str
    formula: str
    exported_formula: str
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
    diagnostics = _syntax_diagnostics(target, exported_formula)
    syntax_valid = not diagnostics

    return ProverTargetSyntaxRecord(
        source_id=norm.source_id,
        target=target,
        target_version="syntax_v1",
        formula=formula,
        exported_formula=exported_formula,
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
