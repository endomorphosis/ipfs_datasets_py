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

from .formula_builder import build_deontic_formula_record_from_ir
from .ir import LegalNormIR


IRInput = Union[LegalNormIR, Mapping[str, Any]]


EXPORT_TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "canonical": {"primary_key": "source_id", "requires_source_id": True},
    "formal_logic": {"primary_key": "formula_id", "requires_source_id": True},
    "proof_obligations": {"primary_key": "proof_obligation_id", "requires_source_id": True},
    "repair_queue": {"primary_key": "repair_id", "requires_source_id": True},
}

_SECTION_REFERENCE_RE = re.compile(
    r"\bsection\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)\b", re.IGNORECASE
)


def build_formal_logic_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a parquet-safe formal-logic row from typed legal IR."""

    record = build_deontic_formula_record_from_ir(norm)
    reference_provenance = _cross_reference_provenance_from_ir(norm)
    row = {
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


def build_document_export_tables_from_ir(norms: Iterable[LegalNormIR]) -> Dict[str, List[Dict[str, Any]]]:
    """Build deterministic export tables from typed legal norms."""

    tables: Dict[str, List[Dict[str, Any]]] = {
        "canonical": [],
        "formal_logic": [],
        "proof_obligations": [],
        "repair_queue": [],
    }

    resolved_norms = _with_same_document_reference_resolutions(list(norms))

    for norm in resolved_norms:
        tables["canonical"].append(_canonical_record_from_ir(norm))
        tables["formal_logic"].append(build_formal_logic_record_from_ir(norm))
        proof_record = build_proof_obligation_record_from_ir(norm)
        tables["proof_obligations"].append(proof_record)
        if proof_record["requires_validation"]:
            tables["repair_queue"].append(build_repair_queue_record_from_ir(norm))

    return tables


def parser_elements_to_export_tables(elements: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Compatibility bridge from parser dictionaries to IR export tables."""

    return build_document_export_tables_from_ir(
        LegalNormIR.from_parser_element(dict(element)) for element in elements
    )


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

    aligned: List[Dict[str, Any]] = []
    for element in elements:
        copied = dict(element)
        norm = LegalNormIR.from_parser_element(copied)
        formula_record = build_deontic_formula_record_from_ir(norm)
        deterministic_resolution = formula_record.get("deterministic_resolution") or {}

        export_readiness = dict(copied.get("export_readiness") or {})
        export_readiness["parser_proof_ready"] = bool(copied.get("promotable_to_theorem"))
        export_readiness["formula_proof_ready"] = bool(formula_record.get("proof_ready"))
        export_readiness["proof_ready"] = bool(formula_record.get("proof_ready"))
        export_readiness["requires_validation"] = bool(formula_record.get("requires_validation"))
        export_readiness["repair_required"] = bool(formula_record.get("repair_required"))
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

        aligned.append(copied)
    return aligned


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

        citation = _reference_section_citation(reference)
        if not citation or citation not in section_index or citation in existing:
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
    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        citation = _canonical_section_citation(str(reference.get(key) or ""))
        if citation:
            return citation

    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    target = str(reference.get("target") or reference.get("section") or "").strip()
    if reference_type == "section" and target and target.lower() not in {"this", "current"}:
        return _canonical_section_citation(f"section {target}")
    return ""


def _canonical_section_citation(text: str) -> str:
    match = _SECTION_REFERENCE_RE.search(str(text or ""))
    if not match:
        return ""
    return f"section {match.group(1).lower()}"


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
    for key in ("value", "canonical_citation", "citation", "normalized_text", "raw_text", "text"):
        value = str(reference.get(key) or "").strip()
        if value:
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


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
