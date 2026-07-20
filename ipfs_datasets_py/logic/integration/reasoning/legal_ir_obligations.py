"""Deterministic proof-obligation extraction for Legal IR hammer runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


LEGAL_IR_OBLIGATION_SCHEMA_VERSION = "legal-ir-proof-obligation-v1"


def _stable_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            converted = value.to_dict()
            if isinstance(converted, Mapping):
                return dict(converted)
        except (TypeError, ValueError):
            return {}
    return {}


def _sequence(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _atom(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")
    return text or fallback


def _sample_id(sample_or_document: Any) -> str:
    return str(
        _get(sample_or_document, "sample_id")
        or _get(sample_or_document, "document_id")
        or _get(_get(sample_or_document, "modal_ir"), "document_id")
        or _as_mapping(sample_or_document).get("sample_id")
        or _as_mapping(sample_or_document).get("document_id")
        or "legal-ir-sample"
    )


def _document(sample_or_document: Any) -> Any:
    return _get(sample_or_document, "modal_ir", sample_or_document)


def _document_mapping(document: Any) -> Dict[str, Any]:
    return _as_mapping(document)


def _formulas(document: Any) -> List[Any]:
    raw = _get(document, "formulas")
    if raw is None:
        raw = _document_mapping(document).get("formulas", [])
    return _sequence(raw)


def _frame_logic(document: Any) -> Any:
    raw = _get(document, "frame_logic")
    if raw is None:
        raw = _document_mapping(document).get("frame_logic", {})
    return raw


def _operator(formula: Any) -> Any:
    raw = _get(formula, "operator")
    if raw is None:
        raw = _as_mapping(formula).get("operator", {})
    return raw


def _predicate(formula: Any) -> Any:
    raw = _get(formula, "predicate")
    if raw is None:
        raw = _as_mapping(formula).get("predicate", {})
    return raw


def _provenance(formula: Any) -> Any:
    raw = _get(formula, "provenance")
    if raw is None:
        raw = _as_mapping(formula).get("provenance", {})
    return raw


def _formula_id(formula: Any, index: int) -> str:
    return str(_get(formula, "formula_id") or _as_mapping(formula).get("formula_id") or f"formula-{index}")


def _source_span_hash(sample_or_document: Any, formula: Any) -> str:
    text = str(_get(sample_or_document, "normalized_text") or _get(_document(sample_or_document), "normalized_text") or "")
    provenance = _provenance(formula)
    try:
        start = max(0, int(_get(provenance, "start_char") or 0))
        end = max(start, int(_get(provenance, "end_char") or 0))
    except (TypeError, ValueError):
        start = 0
        end = 0
    span = text[start:end] if text and end > start else ""
    if not span:
        payload = {
            "formula": _as_mapping(formula),
            "provenance": _as_mapping(provenance),
        }
        return _stable_hash(payload)
    return hashlib.sha256(span.encode("utf-8")).hexdigest()


def _predicate_signature(predicate: Any) -> str:
    name = _atom(_get(predicate, "name") or _as_mapping(predicate).get("name"), fallback="predicate")
    args = _sequence(_get(predicate, "arguments") or _as_mapping(predicate).get("arguments", []))
    role = _atom(_get(predicate, "role") or _as_mapping(predicate).get("role") or "none")
    return f"{name}/arity:{len(args)}/role:{role}"


def _family_view(family: str, symbol: str) -> str:
    normalized_family = _atom(family)
    normalized_symbol = _atom(symbol)
    if normalized_family == "deontic" or normalized_symbol in {"shall", "must", "may", "shall_not", "may_not"}:
        return "deontic.ir"
    if normalized_family in {"temporal", "dynamic"}:
        return "TDFOL.prover"
    if normalized_family == "frame":
        return "modal.frame_logic"
    return "modal.frame_logic"


def _has_temporal_signal(formula: Any) -> bool:
    values = [
        *_sequence(_get(formula, "conditions") or _as_mapping(formula).get("conditions", [])),
        *_sequence(_get(formula, "exceptions") or _as_mapping(formula).get("exceptions", [])),
    ]
    text = " ".join(str(item).lower() for item in values)
    return bool(re.search(r"\b(before|after|within|deadline|not_later_than|until|when)\b", text))


@dataclass(frozen=True)
class LegalIRProofObligation:
    """One deterministic proof/check obligation over a Legal IR view."""

    obligation_id: str
    statement: str
    kind: str
    legal_ir_view: str
    logic_family: str
    sample_id: str = ""
    formula_id: str = ""
    premise_hints: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_OBLIGATION_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "kind": self.kind,
            "legal_ir_view": self.legal_ir_view,
            "logic_family": self.logic_family,
            "metadata": dict(sorted(self.metadata.items())),
            "obligation_id": self.obligation_id,
            "premise_hints": list(self.premise_hints),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
        }


def _obligation(
    *,
    sample_id: str,
    formula_id: str,
    kind: str,
    legal_ir_view: str,
    logic_family: str,
    statement: str,
    premise_hints: Sequence[str] = (),
    metadata: Optional[Mapping[str, Any]] = None,
) -> LegalIRProofObligation:
    id_payload = {
        "formula_id": formula_id,
        "kind": kind,
        "legal_ir_view": legal_ir_view,
        "logic_family": logic_family,
        "sample_id": sample_id,
        "statement": statement,
    }
    return LegalIRProofObligation(
        obligation_id=f"lir-obligation-{_stable_hash(id_payload)[:20]}",
        statement=statement,
        kind=kind,
        legal_ir_view=legal_ir_view,
        logic_family=logic_family,
        sample_id=sample_id,
        formula_id=formula_id,
        premise_hints=list(dict.fromkeys(str(item) for item in premise_hints if str(item))),
        metadata=dict(metadata or {}),
    )


def generate_legal_ir_proof_obligations(sample_or_document: Any) -> List[LegalIRProofObligation]:
    """Return deterministic obligations for modal/deontic/frame/TDFOL/KG views."""

    document = _document(sample_or_document)
    sample_id = _sample_id(sample_or_document)
    obligations: List[LegalIRProofObligation] = []
    formulas = _formulas(document)
    document_hash = str(
        getattr(document, "canonical_hash", lambda: "")()
        if callable(getattr(document, "canonical_hash", None))
        else _stable_hash(_document_mapping(document) or {"sample_id": sample_id})
    )

    if not formulas:
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id="document",
                kind="modal_formula_presence",
                legal_ir_view="modal.frame_logic",
                logic_family="modal",
                statement=f"legal_ir_document_has_modal_formula(document:{sample_id}, hash:{document_hash[:16]})",
                premise_hints=("legal_ir_document_requires_modal_formula_or_explicit_empty_reason",),
                metadata={"document_hash": document_hash},
            )
        )
        return obligations

    for index, formula in enumerate(formulas, start=1):
        formula_id = _formula_id(formula, index)
        operator = _operator(formula)
        predicate = _predicate(formula)
        family = _atom(_get(operator, "family") or _as_mapping(operator).get("family"), fallback="modal")
        system = _atom(_get(operator, "system") or _as_mapping(operator).get("system"), fallback="system")
        symbol = _atom(_get(operator, "symbol") or _as_mapping(operator).get("symbol"), fallback="operator")
        predicate_sig = _predicate_signature(predicate)
        span_hash = _source_span_hash(sample_or_document, formula)
        view = _family_view(family, symbol)
        base_metadata = {
            "document_hash": document_hash,
            "operator_symbol": symbol,
            "operator_system": system,
            "predicate_signature": predicate_sig,
            "source_span_sha256": span_hash,
        }
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=formula_id,
                kind="modal_well_formedness",
                legal_ir_view="modal.frame_logic",
                logic_family=family,
                statement=(
                    f"well_formed_formula({formula_id}) and "
                    f"operator_family({formula_id},{family}) and "
                    f"predicate_signature({formula_id},{predicate_sig})"
                ),
                premise_hints=("modal_operator_well_formed", "predicate_signature_has_arity"),
                metadata=base_metadata,
            )
        )
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=formula_id,
                kind="provenance_preservation",
                legal_ir_view="modal.frame_logic",
                logic_family=family,
                statement=f"source_provenance_present({formula_id}, sha256:{span_hash[:16]})",
                premise_hints=("legal_ir_formula_requires_provenance",),
                metadata=base_metadata,
            )
        )
        if view == "deontic.ir":
            obligations.append(
                _obligation(
                    sample_id=sample_id,
                    formula_id=formula_id,
                    kind="deontic_polarity",
                    legal_ir_view="deontic.ir",
                    logic_family="deontic",
                    statement=f"deontic_polarity_supported({formula_id}, operator:{symbol})",
                    premise_hints=("deontic_norm_polarity_supported",),
                    metadata=base_metadata,
                )
            )
        exceptions = _sequence(_get(formula, "exceptions") or _as_mapping(formula).get("exceptions", []))
        if exceptions:
            obligations.append(
                _obligation(
                    sample_id=sample_id,
                    formula_id=formula_id,
                    kind="exception_scope_precedence",
                    legal_ir_view="deontic.ir",
                    logic_family="conditional_normative",
                    statement=f"exception_scope_precedes_norm({formula_id}, exception_count:{len(exceptions)})",
                    premise_hints=("exception_scope_precedence", "defeasible_priority_orders_exceptions"),
                    metadata={**base_metadata, "exception_count": len(exceptions)},
                )
            )
        if family in {"temporal", "dynamic"} or _has_temporal_signal(formula):
            obligations.append(
                _obligation(
                    sample_id=sample_id,
                    formula_id=formula_id,
                    kind="temporal_event_consistency",
                    legal_ir_view="TDFOL.prover",
                    logic_family="temporal",
                    statement=f"temporal_conditions_have_event_order({formula_id})",
                    premise_hints=("temporal_conditions_have_event_order",),
                    metadata=base_metadata,
                )
            )
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=formula_id,
                kind="decompiler_round_trip_signature",
                legal_ir_view="modal.decompiler",
                logic_family=family,
                statement=f"decompiler_preserves_modal_signature({formula_id}, {family}, {symbol})",
                premise_hints=("decompiler_preserves_modal_signature",),
                metadata=base_metadata,
            )
        )
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=formula_id,
                kind="decompiler_structural_summary",
                legal_ir_view="modal.decompiler",
                logic_family=family,
                statement=(
                    f"decompiler_emits_structural_summary({formula_id}, "
                    f"predicate:{predicate_sig})"
                ),
                premise_hints=(
                    "decompiler_preserves_structural_summary",
                    "source_copy_guardrail_requires_summary_not_span",
                ),
                metadata={
                    **base_metadata,
                    "round_trip_guardrail": "structural_summary_not_source_copy",
                },
            )
        )
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=formula_id,
                kind="decompiler_modality_retention",
                legal_ir_view="modal.decompiler",
                logic_family=family,
                statement=(
                    f"decompiler_retains_modality({formula_id}, "
                    f"family:{family}, operator:{symbol})"
                ),
                premise_hints=(
                    "decompiler_retains_modal_operator",
                    "round_trip_modality_preserved",
                ),
                metadata=base_metadata,
            )
        )
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=formula_id,
                kind="decompiler_source_copy_guardrail",
                legal_ir_view="modal.decompiler",
                logic_family=family,
                statement=(
                    f"decompiler_output_uses_ir_summary_not_source_span("
                    f"{formula_id}, sha256:{span_hash[:16]})"
                ),
                premise_hints=(
                    "source_copy_guardrail_requires_summary_not_span",
                    "decompiler_output_references_provenance_by_hash",
                ),
                metadata={
                    **base_metadata,
                    "source_copy_policy": "hash_only",
                },
            )
        )
        if exceptions:
            obligations.append(
                _obligation(
                    sample_id=sample_id,
                    formula_id=formula_id,
                    kind="decompiler_exception_scope_retention",
                    legal_ir_view="modal.decompiler",
                    logic_family="conditional_normative",
                    statement=(
                        f"decompiler_retains_exception_scope("
                        f"{formula_id}, exception_count:{len(exceptions)})"
                    ),
                    premise_hints=(
                        "decompiler_retains_exception_scope",
                        "exception_scope_precedence",
                    ),
                    metadata={**base_metadata, "exception_count": len(exceptions)},
                )
            )

    frame_logic = _frame_logic(document)
    triples = _sequence(_get(frame_logic, "triples") or _as_mapping(frame_logic).get("triples", []))
    for index, triple in enumerate(triples, start=1):
        triple_map = _as_mapping(triple)
        subject = _atom(_get(triple, "subject") or triple_map.get("subject"), fallback=f"subject_{index}")
        predicate = _atom(_get(triple, "predicate") or triple_map.get("predicate"), fallback="predicate")
        obj = _atom(_get(triple, "object") or triple_map.get("object"), fallback=f"object_{index}")
        statement = f"kg_edge_typed(subject:{subject}, predicate:{predicate}, object:{obj})"
        obligations.append(
            _obligation(
                sample_id=sample_id,
                formula_id=f"frame-triple-{index}",
                kind="knowledge_graph_edge_typing",
                legal_ir_view="knowledge_graphs.neo4j_compat",
                logic_family="frame",
                statement=statement,
                premise_hints=("kg_edges_are_typed", "frame_role_bindings_are_preserved"),
                metadata={
                    "document_hash": document_hash,
                    "frame_predicate": predicate,
                    "triple_index": index,
                },
            )
        )

    return obligations


__all__ = [
    "LEGAL_IR_OBLIGATION_SCHEMA_VERSION",
    "LegalIRProofObligation",
    "generate_legal_ir_proof_obligations",
]
