"""Verifier-owned Lean theorem templates for legal modal IR semantics.

This module is the deterministic authority for theorem statements used by the
Leanstral proof lane.  It binds each statement to canonical hashes derived from
the modal IR, source provenance, F-logic graph projection, and decompiler
round-trip surface.  Leanstral may provide proof bodies for these statements,
but it does not author or alter the statements themselves.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
)

from .codec import modal_ir_to_flogic_triples
from .decompiler import decode_modal_ir_document


LEANSTRAL_THEOREM_SCHEMA_VERSION = "legal-ir-leanstral-theorems-v1"
_SAFE_LEAN_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]+")
_TEMPORAL_PREFIXES = frozenset(
    {
        "after",
        "before",
        "by",
        "no_later_than",
        "not_later_than",
        "only_after",
        "until",
        "upon",
        "when",
        "within",
    }
)

LEGAL_IR_THEOREM_LEAN_KERNEL = """
namespace LegalIR

structure LegalTheoremFacts where
  templateId : String
  evidenceHash : String
  modalIRHash : String
  formulaId : String
  family : String
  system : String
  symbol : String
  predicate : String
  permissionExpected : Bool
  prohibitionExpected : Bool
  exceptionHash : String
  exceptionCount : Nat
  temporalHash : String
  temporalCount : Nat
  actor : String
  action : String
  object : String
  sourceId : String
  citation : String
  sourceSpanHash : String
  graphEndpointHash : String
  graphEndpointIntegrity : Bool
  decompilerHash : String
  compilerRoundTripHash : String
  compilerRoundTripOk : Bool
  deriving Repr, DecidableEq

abbrev theoremEvidenceBound
    (facts : LegalTheoremFacts)
    (templateId evidenceHash modalIRHash : String) : Prop :=
  facts.templateId = templateId /\\
  facts.evidenceHash = evidenceHash /\\
  facts.modalIRHash = modalIRHash /\\
  facts.formulaId.length > 0

abbrev modalityPreserved
    (facts : LegalTheoremFacts)
    (family system symbol predicate : String) : Prop :=
  facts.family = family /\\
  facts.system = system /\\
  facts.symbol = symbol /\\
  facts.predicate = predicate

abbrev prohibitionPreserved (facts : LegalTheoremFacts) (expected : Bool) : Prop :=
  facts.prohibitionExpected = expected /\\
  (expected = true -> facts.family = "deontic" /\\ facts.symbol = "F")

abbrev permissionPreserved (facts : LegalTheoremFacts) (expected : Bool) : Prop :=
  facts.permissionExpected = expected /\\
  (expected = true -> facts.family = "deontic" /\\ facts.symbol = "P")

abbrev exceptionScopePreserved
    (facts : LegalTheoremFacts)
    (exceptionHash : String)
    (exceptionCount : Nat) : Prop :=
  facts.exceptionHash = exceptionHash /\\ facts.exceptionCount = exceptionCount

abbrev temporalBoundsPreserved
    (facts : LegalTheoremFacts)
    (temporalHash : String)
    (temporalCount : Nat) : Prop :=
  facts.temporalHash = temporalHash /\\ facts.temporalCount = temporalCount

abbrev sourceRolesPreserved
    (facts : LegalTheoremFacts)
    (actor action object : String) : Prop :=
  facts.actor = actor /\\ facts.action = action /\\ facts.object = object

abbrev sourceProvenancePreserved
    (facts : LegalTheoremFacts)
    (sourceId citation sourceSpanHash : String) : Prop :=
  facts.sourceId = sourceId /\\
  facts.citation = citation /\\
  facts.sourceSpanHash = sourceSpanHash /\\
  facts.sourceId.length > 0 /\\
  facts.sourceSpanHash.length > 0

abbrev graphEndpointIntegrityPreserved
    (facts : LegalTheoremFacts)
    (endpointHash : String) : Prop :=
  facts.graphEndpointHash = endpointHash /\\ facts.graphEndpointIntegrity = true

abbrev compilerDecompilerRoundTripPreserved
    (facts : LegalTheoremFacts)
    (decompilerHash roundTripHash : String) : Prop :=
  facts.decompilerHash = decompilerHash /\\
  facts.compilerRoundTripHash = roundTripHash /\\
  facts.compilerRoundTripOk = true

end LegalIR
"""


@dataclass(frozen=True)
class LeanstralTheorem:
    """One fixed theorem statement and its canonical evidence binding."""

    theorem_id: str
    theorem_name: str
    template_id: str
    category: str
    statement: str
    evidence_hash: str
    evidence_id: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    formula_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "evidence": _sorted_jsonable(self.evidence),
            "evidence_hash": self.evidence_hash,
            "evidence_id": self.evidence_id,
            "formula_id": self.formula_id,
            "statement": self.statement,
            "template_id": self.template_id,
            "theorem_id": self.theorem_id,
            "theorem_name": self.theorem_name,
        }


@dataclass(frozen=True)
class LeanstralTheoremRegistry:
    """Deterministic theorem set for a canonical LegalIR sample."""

    schema_version: str
    sample_id: str
    modal_ir_hash: str
    registry_hash: str
    source_hash: str
    graph_hash: str
    decompiler_hash: str
    theorem_count: int
    theorems: Sequence[LeanstralTheorem] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decompiler_hash": self.decompiler_hash,
            "graph_hash": self.graph_hash,
            "modal_ir_hash": self.modal_ir_hash,
            "registry_hash": self.registry_hash,
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_hash": self.source_hash,
            "theorem_count": self.theorem_count,
            "theorems": [theorem.to_dict() for theorem in self.theorems],
        }

    def theorem_ids(self) -> Tuple[str, ...]:
        return tuple(theorem.theorem_id for theorem in self.theorems)

    def theorem_by_id(self, theorem_id: str) -> Optional[LeanstralTheorem]:
        for theorem in self.theorems:
            if theorem.theorem_id == theorem_id:
                return theorem
        return None

    def render_lean_source(self, proofs: Mapping[str, str]) -> str:
        """Render only verifier-owned statements with externally supplied proofs."""
        theorem_blocks: List[str] = []
        for theorem in self.theorems:
            proof = str(proofs.get(theorem.theorem_id, "")).strip()
            if not proof:
                continue
            theorem_blocks.append(
                f"theorem {theorem.theorem_name} : {theorem.statement} := {proof}"
            )
        return (
            LEGAL_IR_THEOREM_LEAN_KERNEL
            + "\nnamespace LegalIR\n\n"
            + "\n\n".join(theorem_blocks)
            + ("\n\n" if theorem_blocks else "")
            + "end LegalIR\n"
        )


def generate_legal_semantics_theorem_registry(
    sample: LegalSample,
) -> LeanstralTheoremRegistry:
    """Generate all verifier-owned theorem templates for one LegalSample."""

    modal_ir = sample.modal_ir
    modal_ir_hash = modal_ir.canonical_hash()
    triples = modal_ir_to_flogic_triples(modal_ir)
    decoded = decode_modal_ir_document(modal_ir)
    source_hash = _hash_text(sample.normalized_text or sample.text)
    graph_hash = _hash_payload(_canonical_triples(triples))
    decompiler_hash = _hash_payload(
        {
            "formulas": list(decoded.formulas),
            "modal_span_coverage": round(float(decoded.modal_span_coverage), 12),
            "reconstruction_similarity": round(
                float(decoded.reconstruction_similarity), 12
            ),
            "strategy": decoded.reconstruction_strategy,
            "text_hash": _hash_text(decoded.text),
        }
    )
    theorem_builder = _RegistryBuilder(
        sample=sample,
        modal_ir=modal_ir,
        modal_ir_hash=modal_ir_hash,
        source_hash=source_hash,
        triples=triples,
        graph_hash=graph_hash,
        decompiler_hash=decompiler_hash,
    )
    theorems: List[LeanstralTheorem] = []
    for formula in sorted(modal_ir.formulas, key=lambda item: item.formula_id):
        theorems.extend(theorem_builder.formula_theorems(formula))
    theorems.append(theorem_builder.graph_endpoint_integrity_theorem())
    registry_payload = {
        "modal_ir_hash": modal_ir_hash,
        "sample_id": sample.sample_id,
        "schema_version": LEANSTRAL_THEOREM_SCHEMA_VERSION,
        "theorems": [
            {
                "evidence_hash": theorem.evidence_hash,
                "statement": theorem.statement,
                "template_id": theorem.template_id,
                "theorem_id": theorem.theorem_id,
            }
            for theorem in theorems
        ],
    }
    registry_hash = _hash_payload(registry_payload)
    return LeanstralTheoremRegistry(
        schema_version=LEANSTRAL_THEOREM_SCHEMA_VERSION,
        sample_id=sample.sample_id,
        modal_ir_hash=modal_ir_hash,
        registry_hash=registry_hash,
        source_hash=source_hash,
        graph_hash=graph_hash,
        decompiler_hash=decompiler_hash,
        theorem_count=len(theorems),
        theorems=tuple(theorems),
    )


def lean_theorem_proof_rejection_reasons(
    registry: Optional[LeanstralTheoremRegistry | Mapping[str, Any]],
    theorem_proofs: Mapping[str, str],
    *,
    forbidden_pattern: re.Pattern[str],
    max_proof_bytes: int = 12000,
) -> List[str]:
    """Validate theorem proof-map boundaries without invoking Lean."""

    if not theorem_proofs:
        return []
    theorem_ids = _registry_theorem_ids(registry)
    reasons: List[str] = []
    for theorem_id, proof in theorem_proofs.items():
        normalized_id = str(theorem_id).strip()
        normalized_proof = str(proof or "").strip()
        if normalized_id not in theorem_ids:
            reasons.append("unknown_theorem_proof_id")
            continue
        if not normalized_proof.startswith("by"):
            reasons.append("theorem_proof_must_start_with_by")
        if len(normalized_proof.encode("utf-8")) > max_proof_bytes:
            reasons.append("theorem_proof_too_large")
        if forbidden_pattern.search(normalized_proof):
            reasons.append("forbidden_theorem_proof_construct")
    return list(dict.fromkeys(reasons))


class _RegistryBuilder:
    def __init__(
        self,
        *,
        sample: LegalSample,
        modal_ir: ModalIRDocument,
        modal_ir_hash: str,
        source_hash: str,
        triples: Sequence[Mapping[str, Any]],
        graph_hash: str,
        decompiler_hash: str,
    ) -> None:
        self.sample = sample
        self.modal_ir = modal_ir
        self.modal_ir_hash = modal_ir_hash
        self.source_hash = source_hash
        self.triples = tuple(_canonical_triples(triples))
        self.graph_hash = graph_hash
        self.decompiler_hash = decompiler_hash

    def formula_theorems(self, formula: ModalIRFormula) -> List[LeanstralTheorem]:
        facts = self._facts(formula)
        common = self._common_formula_evidence(formula, facts)
        templates: Sequence[Tuple[str, str, str]] = (
            (
                "modal_operator_preserved",
                "modality",
                (
                    "LegalIR.modalityPreserved {facts} {family} {system} "
                    "{symbol} {predicate}"
                ),
            ),
            (
                "prohibition_semantics_preserved",
                "prohibition",
                "LegalIR.prohibitionPreserved {facts} {prohibition_expected}",
            ),
            (
                "permission_semantics_preserved",
                "permission",
                "LegalIR.permissionPreserved {facts} {permission_expected}",
            ),
            (
                "exception_scope_preserved",
                "exception_scope",
                (
                    "LegalIR.exceptionScopePreserved {facts} {exception_hash} "
                    "{exception_count}"
                ),
            ),
            (
                "temporal_bounds_preserved",
                "temporal_bounds",
                (
                    "LegalIR.temporalBoundsPreserved {facts} {temporal_hash} "
                    "{temporal_count}"
                ),
            ),
            (
                "actor_action_object_roles_preserved",
                "source_roles",
                "LegalIR.sourceRolesPreserved {facts} {actor} {action} {object}",
            ),
            (
                "source_provenance_preserved",
                "source_provenance",
                (
                    "LegalIR.sourceProvenancePreserved {facts} {source_id} "
                    "{citation} {source_span_hash}"
                ),
            ),
            (
                "compiler_decompiler_round_trip_preserved",
                "compiler_decompiler_round_trip",
                (
                    "LegalIR.compilerDecompilerRoundTripPreserved {facts} "
                    "{decompiler_hash} {round_trip_hash}"
                ),
            ),
        )
        return [
            self._theorem(
                template_id=template_id,
                category=category,
                formula_id=formula.formula_id,
                facts=facts,
                evidence={
                    **common,
                    "category": category,
                    "template_id": template_id,
                },
                statement_template=statement_template,
            )
            for template_id, category, statement_template in templates
        ]

    def graph_endpoint_integrity_theorem(self) -> LeanstralTheorem:
        endpoint_hash, endpoint_integrity, endpoint_evidence = _graph_endpoint_evidence(
            self.modal_ir,
            self.triples,
        )
        facts = {
            "templateId": "graph_endpoint_integrity_preserved",
            "evidenceHash": "",
            "modalIRHash": self.modal_ir_hash,
            "formulaId": self.modal_ir.document_id,
            "family": "graph",
            "system": "flogic",
            "symbol": "endpoint",
            "predicate": "graph_endpoint_integrity",
            "permissionExpected": False,
            "prohibitionExpected": False,
            "exceptionHash": _hash_payload([]),
            "exceptionCount": 0,
            "temporalHash": _hash_payload([]),
            "temporalCount": 0,
            "actor": "",
            "action": "",
            "object": "",
            "sourceId": self.modal_ir.document_id,
            "citation": str(self.sample.citation or ""),
            "sourceSpanHash": self.source_hash,
            "graphEndpointHash": endpoint_hash,
            "graphEndpointIntegrity": endpoint_integrity,
            "decompilerHash": self.decompiler_hash,
            "compilerRoundTripHash": _hash_payload(
                {
                    "decompiler_hash": self.decompiler_hash,
                    "modal_ir_hash": self.modal_ir_hash,
                }
            ),
            "compilerRoundTripOk": bool(self.modal_ir_hash and self.decompiler_hash),
        }
        return self._theorem(
            template_id="graph_endpoint_integrity_preserved",
            category="graph_endpoint_integrity",
            formula_id="",
            facts=facts,
            evidence={
                "category": "graph_endpoint_integrity",
                "endpoint_evidence": endpoint_evidence,
                "graph_hash": self.graph_hash,
                "sample_id": self.sample.sample_id,
                "template_id": "graph_endpoint_integrity_preserved",
            },
            statement_template=(
                "LegalIR.graphEndpointIntegrityPreserved {facts} {endpoint_hash}"
            ),
        )

    def _theorem(
        self,
        *,
        template_id: str,
        category: str,
        formula_id: str,
        facts: Mapping[str, Any],
        evidence: Mapping[str, Any],
        statement_template: str,
    ) -> LeanstralTheorem:
        evidence_payload = {
            "evidence": _sorted_jsonable(evidence),
            "facts": _sorted_jsonable(facts),
            "modal_ir_hash": self.modal_ir_hash,
            "sample_id": self.sample.sample_id,
            "schema_version": LEANSTRAL_THEOREM_SCHEMA_VERSION,
            "template_id": template_id,
        }
        evidence_hash = _hash_payload(evidence_payload)
        bound_facts = dict(facts)
        bound_facts["templateId"] = template_id
        bound_facts["evidenceHash"] = evidence_hash
        fact_literal = _lean_facts_literal(bound_facts)
        statement = (
            "LegalIR.theoremEvidenceBound "
            + f"{fact_literal} {_lean_string(template_id)} "
            + f"{_lean_string(evidence_hash)} {_lean_string(self.modal_ir_hash)}"
            + " /\\ "
            + statement_template.format(
                facts=fact_literal,
                family=_lean_string(bound_facts.get("family")),
                system=_lean_string(bound_facts.get("system")),
                symbol=_lean_string(bound_facts.get("symbol")),
                predicate=_lean_string(bound_facts.get("predicate")),
                prohibition_expected=_lean_bool(
                    bool(bound_facts.get("prohibitionExpected", False))
                ),
                permission_expected=_lean_bool(
                    bool(bound_facts.get("permissionExpected", False))
                ),
                exception_hash=_lean_string(bound_facts.get("exceptionHash")),
                exception_count=_lean_nat(bound_facts.get("exceptionCount", 0)),
                temporal_hash=_lean_string(bound_facts.get("temporalHash")),
                temporal_count=_lean_nat(bound_facts.get("temporalCount", 0)),
                actor=_lean_string(bound_facts.get("actor")),
                action=_lean_string(bound_facts.get("action")),
                object=_lean_string(bound_facts.get("object")),
                source_id=_lean_string(bound_facts.get("sourceId")),
                citation=_lean_string(bound_facts.get("citation")),
                source_span_hash=_lean_string(bound_facts.get("sourceSpanHash")),
                endpoint_hash=_lean_string(bound_facts.get("graphEndpointHash")),
                decompiler_hash=_lean_string(bound_facts.get("decompilerHash")),
                round_trip_hash=_lean_string(
                    bound_facts.get("compilerRoundTripHash")
                ),
            )
        )
        theorem_id_payload = {
            "evidence_hash": evidence_hash,
            "template_id": template_id,
            "formula_id": formula_id,
        }
        theorem_id = "legal-ir-theorem-" + _hash_payload(theorem_id_payload)[:16]
        theorem_name = _safe_theorem_name(template_id, formula_id, theorem_id)
        return LeanstralTheorem(
            theorem_id=theorem_id,
            theorem_name=theorem_name,
            template_id=template_id,
            category=category,
            statement=statement,
            evidence_hash=evidence_hash,
            evidence_id="legal-ir-evidence-" + evidence_hash[:16],
            evidence=evidence_payload,
            formula_id=formula_id,
        )

    def _facts(self, formula: ModalIRFormula) -> Dict[str, Any]:
        formula_triples = [
            triple for triple in self.triples if triple["subject"] == formula.formula_id
        ]
        exception_values = _formula_exception_values(formula, formula_triples)
        temporal_values = _formula_temporal_values(formula, formula_triples)
        roles = _formula_source_roles(formula, formula_triples)
        source_span_hash = _formula_source_span_hash(self.sample, formula)
        round_trip_hash = _hash_payload(
            {
                "decompiler_hash": self.decompiler_hash,
                "formula_id": formula.formula_id,
                "modal_ir_hash": self.modal_ir_hash,
                "source_span_hash": source_span_hash,
            }
        )
        endpoint_hash, endpoint_integrity, _ = _graph_endpoint_evidence(
            self.modal_ir,
            self.triples,
        )
        return {
            "templateId": "",
            "evidenceHash": "",
            "modalIRHash": self.modal_ir_hash,
            "formulaId": formula.formula_id,
            "family": formula.operator.family,
            "system": formula.operator.system,
            "symbol": formula.operator.symbol,
            "predicate": formula.predicate.name,
            "permissionExpected": _is_permission_formula(formula),
            "prohibitionExpected": _is_prohibition_formula(formula),
            "exceptionHash": _hash_payload(exception_values),
            "exceptionCount": len(exception_values),
            "temporalHash": _hash_payload(temporal_values),
            "temporalCount": len(temporal_values),
            "actor": roles.get("actor", ""),
            "action": roles.get("action", ""),
            "object": roles.get("object", ""),
            "sourceId": formula.provenance.source_id,
            "citation": formula.provenance.citation or self.sample.citation,
            "sourceSpanHash": source_span_hash,
            "graphEndpointHash": endpoint_hash,
            "graphEndpointIntegrity": endpoint_integrity,
            "decompilerHash": self.decompiler_hash,
            "compilerRoundTripHash": round_trip_hash,
            "compilerRoundTripOk": bool(
                self.modal_ir_hash and self.decompiler_hash and source_span_hash
            ),
        }

    def _common_formula_evidence(
        self,
        formula: ModalIRFormula,
        facts: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return {
            "formula": {
                "conditions_hash": _hash_payload(list(formula.conditions)),
                "exceptions_hash": _hash_payload(list(formula.exceptions)),
                "formula_id": formula.formula_id,
                "operator": formula.operator.to_dict(),
                "predicate": formula.predicate.to_dict(),
                "provenance": formula.provenance.to_dict(),
            },
            "formula_facts_hash": _hash_payload(facts),
            "graph_hash": self.graph_hash,
            "sample_id": self.sample.sample_id,
            "source_hash": self.source_hash,
        }


def _formula_exception_values(
    formula: ModalIRFormula,
    triples: Sequence[Mapping[str, str]],
) -> List[str]:
    values = [str(value).strip() for value in formula.exceptions if str(value).strip()]
    for triple in triples:
        predicate = str(triple.get("predicate", ""))
        if predicate == "exception" or predicate.startswith("exception_"):
            value = str(triple.get("object", "")).strip()
            if value:
                values.append(f"{predicate}:{value}")
    return sorted(dict.fromkeys(values))


def _formula_temporal_values(
    formula: ModalIRFormula,
    triples: Sequence[Mapping[str, str]],
) -> List[str]:
    values: List[str] = []
    for clause in (*formula.conditions, *formula.exceptions):
        key, value = _typed_clause_key_value(clause)
        if key in _TEMPORAL_PREFIXES:
            values.append(f"{key}:{value}")
    for triple in triples:
        predicate = str(triple.get("predicate", "")).strip()
        value = str(triple.get("object", "")).strip()
        if not value:
            continue
        if "temporal" in predicate or predicate.endswith("_deadline"):
            values.append(f"{predicate}:{value}")
        elif predicate in {"condition_prefix_key", "exception_prefix_key"} and value in _TEMPORAL_PREFIXES:
            values.append(f"{predicate}:{value}")
    return sorted(dict.fromkeys(values))


def _formula_source_roles(
    formula: ModalIRFormula,
    triples: Sequence[Mapping[str, str]],
) -> Dict[str, str]:
    roles: Dict[str, str] = {"actor": "", "action": "", "object": ""}
    triple_role_map = {
        "source_subject_anchor": "actor",
        "source_action_anchor": "action",
        "source_object_anchor": "object",
    }
    for triple in triples:
        role = triple_role_map.get(str(triple.get("predicate", "")).strip())
        value = str(triple.get("object", "")).strip()
        if role and value and not roles[role]:
            roles[role] = value
    for argument in formula.predicate.arguments:
        key, value = _typed_clause_key_value(str(argument), delimiter=":")
        if key == "subject" and not roles["actor"]:
            roles["actor"] = value
        elif key == "action" and not roles["action"]:
            roles["action"] = value
        elif key == "object" and not roles["object"]:
            roles["object"] = value
    if not roles["action"]:
        roles["action"] = formula.predicate.name
    return roles


def _graph_endpoint_evidence(
    modal_ir: ModalIRDocument,
    triples: Sequence[Mapping[str, str]],
) -> Tuple[str, bool, Dict[str, Any]]:
    canonical = _canonical_triples(triples)
    formula_ids = {formula.formula_id for formula in modal_ir.formulas}
    formulas_with_document_edges = {
        triple["subject"]
        for triple in canonical
        if triple["predicate"] == "belongs_to_document"
        and triple["object"] == modal_ir.document_id
    }
    nonempty_endpoints = all(
        bool(triple["subject"] and triple["predicate"] and triple["object"])
        for triple in canonical
    )
    unknown_document_edges = [
        triple
        for triple in canonical
        if triple["predicate"] == "belongs_to_document"
        and triple["object"] != modal_ir.document_id
    ]
    evidence = {
        "document_id": modal_ir.document_id,
        "formula_ids": sorted(formula_ids),
        "formulas_with_document_edges": sorted(formulas_with_document_edges),
        "nonempty_endpoints": nonempty_endpoints,
        "triple_count": len(canonical),
        "unknown_document_edge_count": len(unknown_document_edges),
    }
    endpoint_integrity = (
        nonempty_endpoints
        and not unknown_document_edges
        and formula_ids.issubset(formulas_with_document_edges)
    )
    return _hash_payload(evidence), endpoint_integrity, evidence


def _registry_theorem_ids(
    registry: Optional[LeanstralTheoremRegistry | Mapping[str, Any]],
) -> set[str]:
    if registry is None:
        return set()
    if isinstance(registry, LeanstralTheoremRegistry):
        return set(registry.theorem_ids())
    raw_theorems = registry.get("theorems", ()) if isinstance(registry, Mapping) else ()
    theorem_ids: set[str] = set()
    if isinstance(raw_theorems, Sequence) and not isinstance(raw_theorems, (str, bytes)):
        for theorem in raw_theorems:
            if isinstance(theorem, Mapping):
                theorem_id = str(theorem.get("theorem_id", "")).strip()
                if theorem_id:
                    theorem_ids.add(theorem_id)
    return theorem_ids


def _canonical_triples(
    triples: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    canonical = [
        {
            "object": str(triple.get("object", "")).strip(),
            "predicate": str(triple.get("predicate", "")).strip(),
            "subject": str(triple.get("subject", "")).strip(),
        }
        for triple in triples
    ]
    return sorted(
        canonical,
        key=lambda triple: (
            triple["subject"],
            triple["predicate"],
            triple["object"],
        ),
    )


def _formula_source_span_hash(sample: LegalSample, formula: ModalIRFormula) -> str:
    start = max(0, int(formula.provenance.start_char))
    end = max(start, int(formula.provenance.end_char))
    span = sample.normalized_text[start:end].strip() or sample.text[start:end].strip()
    return _hash_text(span)


def _is_permission_formula(formula: ModalIRFormula) -> bool:
    return (
        str(formula.operator.family).strip().lower() == "deontic"
        and str(formula.operator.symbol).strip() == "P"
    )


def _is_prohibition_formula(formula: ModalIRFormula) -> bool:
    return (
        str(formula.operator.family).strip().lower() == "deontic"
        and str(formula.operator.symbol).strip() == "F"
    )


def _typed_clause_key_value(
    value: str,
    *,
    delimiter: str = ":",
) -> Tuple[str, str]:
    if delimiter not in value:
        return "", ""
    key, raw_value = value.split(delimiter, 1)
    normalized_key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return normalized_key, raw_value.strip()


def _safe_theorem_name(template_id: str, formula_id: str, theorem_id: str) -> str:
    raw_suffix = f"{template_id}_{formula_id or 'document'}_{theorem_id[-8:]}"
    suffix = _SAFE_LEAN_IDENTIFIER.sub("_", raw_suffix).strip("_")
    if not suffix or suffix[0].isdigit():
        suffix = f"t_{suffix}"
    return f"legal_ir_{suffix}"


def _lean_facts_literal(facts: Mapping[str, Any]) -> str:
    return (
        "{ "
        + f"templateId := {_lean_string(facts.get('templateId'))}, "
        + f"evidenceHash := {_lean_string(facts.get('evidenceHash'))}, "
        + f"modalIRHash := {_lean_string(facts.get('modalIRHash'))}, "
        + f"formulaId := {_lean_string(facts.get('formulaId'))}, "
        + f"family := {_lean_string(facts.get('family'))}, "
        + f"system := {_lean_string(facts.get('system'))}, "
        + f"symbol := {_lean_string(facts.get('symbol'))}, "
        + f"predicate := {_lean_string(facts.get('predicate'))}, "
        + f"permissionExpected := {_lean_bool(bool(facts.get('permissionExpected')))}, "
        + f"prohibitionExpected := {_lean_bool(bool(facts.get('prohibitionExpected')))}, "
        + f"exceptionHash := {_lean_string(facts.get('exceptionHash'))}, "
        + f"exceptionCount := {_lean_nat(facts.get('exceptionCount', 0))}, "
        + f"temporalHash := {_lean_string(facts.get('temporalHash'))}, "
        + f"temporalCount := {_lean_nat(facts.get('temporalCount', 0))}, "
        + f"actor := {_lean_string(facts.get('actor'))}, "
        + f"action := {_lean_string(facts.get('action'))}, "
        + f"object := {_lean_string(facts.get('object'))}, "
        + f"sourceId := {_lean_string(facts.get('sourceId'))}, "
        + f"citation := {_lean_string(facts.get('citation'))}, "
        + f"sourceSpanHash := {_lean_string(facts.get('sourceSpanHash'))}, "
        + f"graphEndpointHash := {_lean_string(facts.get('graphEndpointHash'))}, "
        + f"graphEndpointIntegrity := {_lean_bool(bool(facts.get('graphEndpointIntegrity')))}, "
        + f"decompilerHash := {_lean_string(facts.get('decompilerHash'))}, "
        + f"compilerRoundTripHash := {_lean_string(facts.get('compilerRoundTripHash'))}, "
        + f"compilerRoundTripOk := {_lean_bool(bool(facts.get('compilerRoundTripOk')))} "
        + "}"
    )


def _lean_string(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _lean_bool(value: bool) -> str:
    return "true" if value else "false"


def _lean_nat(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return str(max(0, number))


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(
        _sorted_jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sorted_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sorted_jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_sorted_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_sorted_jsonable(item) for item in sorted(value, key=str)]
    if hasattr(value, "to_dict"):
        return _sorted_jsonable(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return _sorted_jsonable(asdict(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "LEANSTRAL_THEOREM_SCHEMA_VERSION",
    "LEGAL_IR_THEOREM_LEAN_KERNEL",
    "LeanstralTheorem",
    "LeanstralTheoremRegistry",
    "generate_legal_semantics_theorem_registry",
    "lean_theorem_proof_rejection_reasons",
]
