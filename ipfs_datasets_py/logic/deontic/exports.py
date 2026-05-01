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

from .formula_builder import (
    build_deontic_formula_record_from_ir,
    build_deontic_formula_records_from_irs,
)
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
_SECTION_REFERENCE_LIST_RE = re.compile(
    r"\bsections\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*"
    r"(?:\s*(?:,|and|or)\s*[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)+)",
    re.IGNORECASE,
)
_SECTION_REFERENCE_TOKEN_RE = re.compile(r"[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*", re.IGNORECASE)


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


def parser_elements_for_metrics(
    elements: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return parser elements with deterministic readiness for metrics.

    Metrics should report active deterministic repair work, not stale parser
    repair flags that the IR/formula layer has already resolved. This wrapper
    keeps the metric contract explicit while reusing the same no-LLM readiness
    projection used by converter/export callers.
    """

    metric_elements = parser_elements_with_ir_export_readiness(elements)
    for element in metric_elements:
        export_readiness = dict(element.get("export_readiness") or {})
        formula_proof_ready = export_readiness.get("formula_proof_ready") is True
        formula_requires_validation = bool(export_readiness.get("formula_requires_validation"))
        formula_repair_required = bool(export_readiness.get("formula_repair_required"))

        if formula_proof_ready and not formula_requires_validation and not formula_repair_required:
            export_readiness["requires_validation"] = []
            export_readiness["repair_required"] = False
            export_readiness["metric_requires_validation"] = False
            export_readiness["metric_repair_required"] = False
            element["repair_required_warnings"] = []
            element["active_repair_warnings"] = []

            element["llm_repair"] = _cleared_deterministic_repair_payload(element)
        else:
            export_readiness["metric_requires_validation"] = formula_requires_validation
            export_readiness["metric_repair_required"] = formula_repair_required
            active_warnings = list(element.get("parser_warnings") or [])
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
                "source_id": element.get("source_id", ""),
                "canonical_citation": element.get("canonical_citation", ""),
                "text": element.get("text", ""),
                "support_text": element.get("support_text", ""),
                "support_span": element.get("support_span", []),
                "norm_type": element.get("norm_type", ""),
                "modality": element.get("deontic_operator"),
                "subject": list(element.get("subject") or []),
                "action": list(element.get("action") or []),
                "parser_warnings": list(element.get("parser_warnings") or []),
                "active_repair_warnings": active_warnings,
                "llm_repair": llm_repair,
                "deterministic_resolution": export_readiness.get("deterministic_resolution") or {},
            }
        )
    return details


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


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
