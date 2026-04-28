"""Export-record builders for deterministic legal norm IR.

The builders in this module consume ``LegalNormIR`` only. They intentionally do
not inspect raw legal text except through provenance fields already present on
the IR. Legacy parser-element callers can use ``parser_elements_to_export_tables``
as a compatibility bridge while downstream code migrates to typed IR.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Union

from .formula_builder import build_deontic_formula_record_from_ir
from .ir import LegalNormIR


IRInput = Union[LegalNormIR, Mapping[str, Any]]


EXPORT_TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "canonical": {"primary_key": "source_id", "requires_source_id": True},
    "formal_logic": {"primary_key": "formula_id", "requires_source_id": True},
    "proof_obligations": {"primary_key": "proof_obligation_id", "requires_source_id": True},
    "repair_queue": {"primary_key": "repair_id", "requires_source_id": True},
}


def build_formal_logic_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a parquet-safe formal-logic row from typed legal IR."""

    record = build_deontic_formula_record_from_ir(norm)
    return {
        "formula_id": record["formula_id"],
        "source_id": record["source_id"],
        "canonical_citation": record["canonical_citation"],
        "target_logic": record["target_logic"],
        "formula": record["formula"],
        "modality": record["modality"],
        "norm_type": record["norm_type"],
        "support_span": record["support_span"],
        "field_spans": record["field_spans"],
        "proof_ready": record["proof_ready"],
        "requires_validation": record["requires_validation"],
        "blockers": record["blockers"],
        "parser_warnings": record["parser_warnings"],
        "omitted_formula_slots": record["omitted_formula_slots"],
        "schema_version": record["schema_version"],
    }


def build_proof_obligation_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a proof-obligation row without promoting blocked clauses."""

    formula_record = build_formal_logic_record_from_ir(norm)
    proof_ready = bool(norm.proof_ready)
    blockers = list(norm.blockers)
    return {
        "proof_obligation_id": _stable_id("proof", norm.source_id, formula_record["formula"]),
        "formula_id": formula_record["formula_id"],
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "formula": formula_record["formula"],
        "target_logic": formula_record["target_logic"],
        "modality": norm.modality,
        "norm_type": norm.norm_type,
        "support_span": norm.support_span.to_list(),
        "field_spans": dict(norm.field_spans),
        "theorem_candidate": proof_ready,
        "proof_ready": proof_ready,
        "requires_validation": not proof_ready,
        "blockers": blockers,
        "parser_warnings": list(norm.quality.parser_warnings),
        "schema_version": norm.schema_version,
    }


def build_repair_queue_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build an auditable deterministic repair-queue row for blocked clauses."""

    blockers = list(norm.blockers)
    if not blockers:
        blockers = list(norm.quality.parser_warnings)

    return {
        "repair_id": _stable_id("repair", norm.source_id, "|".join(blockers)),
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "source_text": norm.source_text,
        "support_text": norm.support_text,
        "support_span": norm.support_span.to_list(),
        "norm_type": norm.norm_type,
        "modality": norm.modality,
        "reasons": blockers,
        "parser_warnings": list(norm.quality.parser_warnings),
        "requires_llm_repair": False,
        "allow_llm_repair": False,
        "schema_version": norm.schema_version,
    }


def build_document_export_tables_from_ir(norms: Iterable[LegalNormIR]) -> Dict[str, List[Dict[str, Any]]]:
    """Build deterministic export tables from typed legal norms."""

    tables: Dict[str, List[Dict[str, Any]]] = {
        "canonical": [],
        "formal_logic": [],
        "proof_obligations": [],
        "repair_queue": [],
    }

    for norm in norms:
        tables["canonical"].append(_canonical_record_from_ir(norm))
        tables["formal_logic"].append(build_formal_logic_record_from_ir(norm))
        proof_record = build_proof_obligation_record_from_ir(norm)
        tables["proof_obligations"].append(proof_record)
        if not proof_record["proof_ready"]:
            tables["repair_queue"].append(build_repair_queue_record_from_ir(norm))

    return tables


def parser_elements_to_export_tables(elements: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Compatibility bridge from parser dictionaries to IR export tables."""

    return build_document_export_tables_from_ir(
        LegalNormIR.from_parser_element(dict(element)) for element in elements
    )


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
    return {
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
        "quality_label": norm.quality.quality_label,
        "proof_ready": norm.proof_ready,
        "blockers": list(norm.blockers),
        "schema_version": norm.schema_version,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
