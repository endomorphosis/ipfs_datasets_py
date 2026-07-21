"""Premise export adapters for Legal IR hammer runs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .hammer import HammerPremise
from .legal_ir_obligations import LegalIRProofObligation, generate_legal_ir_proof_obligations
from .legal_ir_premise_security import sanitize_hammer_premises


LEGAL_IR_PREMISE_LIBRARY_VERSION = "legal-ir-premise-library-v1"


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


def _verified(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "accepted",
        "checked",
        "proved",
        "trusted",
        "true",
        "verified",
    }


def _document(sample_or_document: Any) -> Any:
    return _get(sample_or_document, "modal_ir", sample_or_document)


def _formulas(document: Any) -> List[Any]:
    raw = _get(document, "formulas")
    if raw is None:
        raw = _as_mapping(document).get("formulas", [])
    return _sequence(raw)


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


def _formula_id(formula: Any, index: int) -> str:
    return str(_get(formula, "formula_id") or _as_mapping(formula).get("formula_id") or f"formula-{index}")


def _premise(
    name: str,
    statement: str,
    *,
    legal_ir_view: str,
    logic_family: str,
    source_module: str,
    weight: float = 1.0,
    metadata: Optional[Mapping[str, Any]] = None,
) -> HammerPremise:
    payload = {
        "legal_ir_view": legal_ir_view,
        "logic_family": logic_family,
        "source_module": source_module,
        "statement": statement,
    }
    merged_metadata = {
        "formalism": "legal_ir",
        "legal_ir_view": legal_ir_view,
        "logic_family": logic_family,
        "premise_library_version": LEGAL_IR_PREMISE_LIBRARY_VERSION,
        "source_module": source_module,
        **dict(metadata or {}),
    }
    return HammerPremise(
        name=name or f"legal_ir_premise_{_stable_hash(payload)[:16]}",
        statement=statement,
        weight=float(weight),
        metadata=merged_metadata,
    )


def default_legal_ir_premises() -> List[HammerPremise]:
    """Return reusable domain axioms used by every Legal IR hammer run."""

    return [
        _premise(
            "legal_ir_formula_requires_provenance",
            "Every compiled Legal IR formula must carry source provenance identified by a stable hash.",
            legal_ir_view="modal.frame_logic",
            logic_family="modal",
            source_module="legal_ir_premise_library",
            weight=1.4,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "modal_operator_well_formed",
            "A modal formula is well formed when its operator family, system, symbol, and predicate signature are present.",
            legal_ir_view="modal.frame_logic",
            logic_family="modal",
            source_module="legal_ir_premise_library",
            weight=1.3,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "predicate_signature_has_arity",
            "A predicate signature records predicate name, role, and argument arity without copying the source span.",
            legal_ir_view="modal.frame_logic",
            logic_family="frame",
            source_module="legal_ir_premise_library",
            weight=1.2,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "deontic_norm_polarity_supported",
            "Deontic operators shall, must, may, shall_not, and may_not map to obligation, permission, or prohibition polarity.",
            legal_ir_view="deontic.ir",
            logic_family="deontic",
            source_module="legal_ir_premise_library",
            weight=1.5,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "exception_scope_precedence",
            "Exception clauses constrain or defeat the scoped norm before the norm is projected to deterministic IR.",
            legal_ir_view="deontic.ir",
            logic_family="conditional_normative",
            source_module="legal_ir_premise_library",
            weight=1.5,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "defeasible_priority_orders_exceptions",
            "A specific exception has priority over a general obligation when both share the same source-scoped formula.",
            legal_ir_view="deontic.ir",
            logic_family="conditional_normative",
            source_module="legal_ir_premise_library",
            weight=1.35,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "temporal_conditions_have_event_order",
            "Temporal legal conditions compile to an event order relation before theorem-prover lowering.",
            legal_ir_view="TDFOL.prover",
            logic_family="temporal",
            source_module="legal_ir_premise_library",
            weight=1.3,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "kg_edges_are_typed",
            "Knowledge graph edges must preserve typed subject, predicate, object, and provenance roles.",
            legal_ir_view="knowledge_graphs.neo4j_compat",
            logic_family="frame",
            source_module="legal_ir_premise_library",
            weight=1.25,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "frame_role_bindings_are_preserved",
            "Frame-logic triples preserve actor, action, object, condition, exception, remedy, and authority roles.",
            legal_ir_view="modal.frame_logic",
            logic_family="frame",
            source_module="legal_ir_premise_library",
            weight=1.25,
            metadata={"premise_kind": "theorem_template"},
        ),
        _premise(
            "decompiler_preserves_modal_signature",
            "Decompiler output must preserve formula identity, modal family, operator symbol, and predicate signature.",
            legal_ir_view="modal.decompiler",
            logic_family="modal",
            source_module="legal_ir_premise_library",
            weight=1.3,
            metadata={"premise_kind": "theorem_template"},
        ),
    ]


def premises_from_obligations(obligations: Iterable[LegalIRProofObligation]) -> List[HammerPremise]:
    premises: List[HammerPremise] = []
    for obligation in obligations:
        premises.append(
            _premise(
                f"obligation_context_{obligation.obligation_id}",
                (
                    f"Proof obligation {obligation.obligation_id} targets "
                    f"{obligation.legal_ir_view} kind {obligation.kind} for formula {obligation.formula_id}."
                ),
                legal_ir_view=obligation.legal_ir_view,
                logic_family=obligation.logic_family,
                source_module="legal_ir_obligation_context",
                weight=1.1,
                metadata={
                    "obligation_id": obligation.obligation_id,
                    "obligation_kind": obligation.kind,
                    "formula_id": obligation.formula_id,
                    "obligation_family": str(
                        obligation.metadata.get("obligation_family") or obligation.kind
                    ),
                    "premise_kind": "sample_local_assumption",
                    "sample_id": obligation.sample_id,
                    **{
                        key: obligation.metadata[key]
                        for key in (
                            "contract_id",
                            "contract_view",
                            "document_hash",
                            "required_field",
                        )
                        if key in obligation.metadata
                    },
                },
            )
        )
    return premises


def premises_from_document(sample_or_document: Any) -> List[HammerPremise]:
    document = _document(sample_or_document)
    premises: List[HammerPremise] = []
    for index, formula in enumerate(_formulas(document), start=1):
        formula_id = _formula_id(formula, index)
        operator = _operator(formula)
        predicate = _predicate(formula)
        family = _atom(_get(operator, "family") or _as_mapping(operator).get("family"), fallback="modal")
        system = _atom(_get(operator, "system") or _as_mapping(operator).get("system"), fallback="system")
        symbol = _atom(_get(operator, "symbol") or _as_mapping(operator).get("symbol"), fallback="operator")
        predicate_name = _atom(_get(predicate, "name") or _as_mapping(predicate).get("name"), fallback="predicate")
        arguments = _sequence(_get(predicate, "arguments") or _as_mapping(predicate).get("arguments", []))
        provenance = _as_mapping(_get(formula, "provenance") or _as_mapping(formula).get("provenance", {}))
        provenance_id = str(
            provenance.get("source_id")
            or provenance.get("provenance_id")
            or provenance.get("source_cid")
            or ""
        ).strip()
        citation = str(provenance.get("citation") or "").strip()
        view = "deontic.ir" if family == "deontic" or symbol in {"shall", "must", "may", "shall_not", "may_not"} else "modal.frame_logic"
        premises.append(
            _premise(
                f"formula_fact_{_atom(formula_id)}",
                (
                    f"Formula {formula_id} has family {family}, system {system}, "
                    f"operator {symbol}, predicate {predicate_name}, and arity {len(arguments)}."
                ),
                legal_ir_view=view,
                logic_family=family,
                source_module="legal_ir_document",
                weight=1.2,
                metadata={
                    "contract_fields": [
                        "formula_id",
                        "operator",
                        "predicate",
                        "arguments",
                        "provenance_ids",
                    ],
                    "citation_hash": _stable_hash(citation) if citation else "",
                    "formula_id": formula_id,
                    "operator_symbol": symbol,
                    "premise_kind": "compiler_fact",
                    "predicate_name": predicate_name,
                    "provenance_hash": _stable_hash(provenance_id) if provenance_id else "",
                },
            )
        )
        exceptions = _sequence(_get(formula, "exceptions") or _as_mapping(formula).get("exceptions", []))
        if exceptions:
            premises.append(
                _premise(
                    f"formula_exception_fact_{_atom(formula_id)}",
                    f"Formula {formula_id} has {len(exceptions)} scoped exception clause(s).",
                    legal_ir_view="deontic.ir",
                    logic_family="conditional_normative",
                    source_module="legal_ir_document",
                    weight=1.25,
                    metadata={
                        "contract_fields": ["exceptions"],
                        "exception_count": len(exceptions),
                        "formula_id": formula_id,
                        "premise_kind": "compiler_fact",
                        "provenance_hash": _stable_hash(provenance_id) if provenance_id else "",
                    },
                )
            )
    return premises


def premises_from_theorem_registry(registry: Any) -> List[HammerPremise]:
    if registry is None:
        return []
    if hasattr(registry, "to_dict") and callable(getattr(registry, "to_dict")):
        try:
            registry = registry.to_dict()
        except (TypeError, ValueError):
            return []
    data = _as_mapping(registry)
    raw_theorems = data.get("theorems", []) if data else _sequence(registry)
    registry_hash = str(data.get("registry_hash") or "")
    registry_verified = any(
        _verified(data.get(key))
        for key in (
            "accepted",
            "kernel_verified",
            "proof_checked",
            "proof_status",
            "trust_status",
            "trusted",
            "verification_status",
            "verified",
        )
    )
    verified_theorem_ids = {
        str(item)
        for item in _sequence(data.get("verified_theorem_ids"))
        if str(item)
    }
    premises: List[HammerPremise] = []
    for index, theorem in enumerate(_sequence(raw_theorems), start=1):
        theorem_map = _as_mapping(theorem)
        name = str(
            theorem_map.get("theorem_name")
            or theorem_map.get("name")
            or theorem_map.get("theorem_id")
            or f"registry_theorem_{index}"
        )
        statement = str(theorem_map.get("statement") or theorem_map.get("formula") or "")
        if not statement:
            continue
        theorem_id = str(theorem_map.get("theorem_id") or name)
        verified = (
            registry_verified
            or theorem_id in verified_theorem_ids
            or any(
                _verified(theorem_map.get(key))
                for key in (
                    "accepted",
                    "kernel_verified",
                    "proof_checked",
                    "proof_status",
                    "status",
                    "trust_status",
                    "trusted",
                    "verification_status",
                    "verified",
                )
            )
        )
        evidence = _as_mapping(theorem_map.get("evidence"))
        citation = str(evidence.get("citation") or theorem_map.get("citation") or "").strip()
        provenance_hash = str(
            theorem_map.get("provenance_hash")
            or theorem_map.get("source_span_hash")
            or evidence.get("source_span_hash")
            or evidence.get("sourceSpanHash")
            or ""
        ).strip()
        premises.append(
            _premise(
                name,
                statement,
                legal_ir_view=str(theorem_map.get("legal_ir_view") or theorem_map.get("target_component") or "external_provers.router"),
                logic_family=str(theorem_map.get("logic_family") or theorem_map.get("family") or "prover"),
                source_module="legal_ir_theorem_registry",
                weight=float(theorem_map.get("weight", 1.0) or 1.0),
                metadata={
                    "category": str(theorem_map.get("category") or ""),
                    "citation_hash": _stable_hash(citation) if citation else "",
                    "evidence_hash": str(theorem_map.get("evidence_hash") or ""),
                    "formula_id": str(theorem_map.get("formula_id") or ""),
                    "premise_kind": (
                        "verified_leanstral_theorem" if verified else "leanstral_theorem"
                    ),
                    "provenance_hash": provenance_hash,
                    "registry_hash": registry_hash or _stable_hash(theorem_map)[:16],
                    "template_id": str(theorem_map.get("template_id") or ""),
                    "theorem_id": theorem_id,
                    "verification_status": "verified" if verified else "unverified",
                    "verified": verified,
                },
            )
        )
    return premises


def export_legal_ir_premises(
    sample_or_document: Any = None,
    *,
    obligations: Optional[Sequence[LegalIRProofObligation]] = None,
    theorem_registry: Any = None,
    extra_premises: Optional[Sequence[HammerPremise | Mapping[str, Any] | str]] = None,
) -> List[HammerPremise]:
    """Return de-duplicated hammer premises for a Legal IR sample or artifact."""

    resolved_obligations = list(obligations or [])
    if sample_or_document is not None and not resolved_obligations:
        resolved_obligations = generate_legal_ir_proof_obligations(sample_or_document)

    premises: List[HammerPremise] = []
    premises.extend(default_legal_ir_premises())
    if sample_or_document is not None:
        premises.extend(premises_from_document(sample_or_document))
    premises.extend(premises_from_obligations(resolved_obligations))
    premises.extend(premises_from_theorem_registry(theorem_registry))
    for index, premise in enumerate(extra_premises or [], start=1):
        if isinstance(premise, HammerPremise):
            premises.append(premise)
        elif isinstance(premise, Mapping):
            premises.append(
                HammerPremise(
                    name=str(premise.get("name") or f"extra_premise_{index}"),
                    statement=str(premise.get("statement") or premise.get("formula") or ""),
                    weight=float(premise.get("weight", 1.0) or 1.0),
                    metadata=dict(premise.get("metadata") or {}),
                )
            )
        else:
            premises.append(HammerPremise(name=f"extra_premise_{index}", statement=str(premise)))

    secured = sanitize_hammer_premises(premises)
    deduped: Dict[str, HammerPremise] = {}
    for premise in secured.accepted:
        if not premise.statement:
            continue
        key = premise.name or _stable_hash(premise.statement)[:16]
        if key not in deduped or premise.weight > deduped[key].weight:
            deduped[key] = premise
    return [deduped[key] for key in sorted(deduped)]


__all__ = [
    "LEGAL_IR_PREMISE_LIBRARY_VERSION",
    "default_legal_ir_premises",
    "export_legal_ir_premises",
    "premises_from_document",
    "premises_from_obligations",
    "premises_from_theorem_registry",
]
