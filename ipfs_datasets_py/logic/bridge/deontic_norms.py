"""Deontic LegalNormIR implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)


@dataclass
class DeonticNormsBridgeAdapter:
    """Bridge legal text into deontic LegalNormIR, prover syntax, and frame data."""

    converter: Optional[Any] = None
    converter_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: {
            "enable_monitoring": False,
            "use_cache": True,
            "use_ml": False,
        }
    )

    name: str = "deontic_norms"
    target_component: str = "deontic.ir"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
    ) -> tuple[LegalIRDocument, Any]:
        """Encode legal text into the canonical bridge IR envelope."""

        result = self._converter().convert(text)
        metadata = dict(getattr(result, "metadata", {}) or {})
        norms = _list_of_dicts(metadata.get("legal_norm_irs"))
        parser_elements = _list_of_dicts(metadata.get("parser_elements"))
        if not parser_elements:
            parser_element = metadata.get("parser_element")
            if isinstance(parser_element, Mapping):
                parser_elements = [dict(parser_element)]
        if not norms:
            legal_norm_ir = metadata.get("legal_norm_ir")
            if isinstance(legal_norm_ir, Mapping):
                norms = [dict(legal_norm_ir)]
        deontic_source_rows = parser_elements if parser_elements else norms
        norm_objects = _legal_norm_objects_from_parser_elements(deontic_source_rows)
        if not norms and norm_objects:
            norms = [norm.to_dict() for norm in norm_objects]
        formula_records = _list_of_dicts(metadata.get("legal_formula_records"))
        coverage_records = _list_of_dicts(
            metadata.get("legal_prover_syntax_target_coverage_records")
        )
        embedded_prover_records = _prover_syntax_records_by_source_from_norm_rows(
            norms or deontic_source_rows
        )
        capability_records = _list_of_dicts(
            metadata.get("legal_parser_capability_profile_records")
        )
        if not formula_records and norm_objects:
            formula_records = _formula_records_from_norm_objects(norm_objects)
        if not coverage_records:
            if embedded_prover_records:
                coverage_records = _coverage_records_from_embedded_prover_records(
                    embedded_prover_records
                )
            elif norm_objects:
                coverage_records = _coverage_records_from_norm_objects(norm_objects)
        elif _coverage_records_need_rebuild(coverage_records):
            if embedded_prover_records:
                coverage_records = _coverage_records_from_embedded_prover_records(
                    embedded_prover_records
                )
            elif norm_objects:
                coverage_records = _coverage_records_from_norm_objects(norm_objects)
        coverage_records = _normalize_coverage_validation_records(coverage_records)
        if not capability_records and norm_objects:
            capability_records = _capability_records_from_norm_objects(norm_objects)
        deontic_exports = _deontic_export_context_from_parser_elements(
            deontic_source_rows,
            coverage_records=coverage_records,
        )
        coverage_metrics = _coverage_validation_metrics(coverage_records)
        parser_metrics = _summarize_parser_metrics(deontic_source_rows)
        resolved_document_id = document_id or _document_id_from_norms(norms, text)
        triples = tuple(
            _frame_logic_triples_from_deontic_records(
                resolved_document_id,
                norms=norms,
                formula_records=formula_records,
                coverage_records=coverage_records,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:deontic-flogic",
            metadata={
                "deontic_norm_count": len(norms),
                "source": "deontic_bridge_ir",
            },
        )
        views = {
            "deontic_ir": LogicIRView(
                name="deontic_ir",
                format="legal-norm-ir",
                source_component="deontic.ir",
                payload={"norms": norms},
                metadata={"norm_count": len(norms)},
            ),
            "deontic_formula_records": LogicIRView(
                name="deontic_formula_records",
                format="deontic-formula-records",
                source_component="deontic.formula_builder",
                payload={"records": formula_records},
                metadata={
                    "formula_record_count": len(formula_records),
                    "proof_ready_count": int(
                        metadata.get("legal_formula_record_proof_ready_count") or 0
                    ),
                },
            ),
            "deontic_prover_syntax": LogicIRView(
                name="deontic_prover_syntax",
                format="deontic-local-prover-syntax-coverage",
                source_component="deontic.prover_syntax",
                payload={"records": coverage_records},
                metadata={
                    "coverage_record_count": len(coverage_records),
                    "coverage_requires_validation_count": coverage_metrics[
                        "requires_validation_count"
                    ],
                    "coverage_requires_validation_rate": coverage_metrics[
                        "requires_validation_rate"
                    ],
                    "coverage_validated_count": coverage_metrics["validated_count"],
                },
            ),
            "deontic_parser_metrics": LogicIRView(
                name="deontic_parser_metrics",
                format="deontic-parser-metrics",
                source_component="deontic.metrics",
                payload=parser_metrics,
                metadata={"parser_element_count": len(parser_elements)},
            ),
            "deontic_parser_capability": LogicIRView(
                name="deontic_parser_capability",
                format="deontic-parser-capability-profile",
                source_component="deontic.exports",
                payload={"records": capability_records},
                metadata={"capability_record_count": len(capability_records)},
            ),
            "deontic_decoder_reconstructions": LogicIRView(
                name="deontic_decoder_reconstructions",
                format="deontic-decoder-reconstructions",
                source_component="deontic.decoder",
                payload={"records": deontic_exports["decoder_records"]},
                metadata={
                    "decoder_record_count": len(deontic_exports["decoder_records"]),
                },
            ),
            "deontic_proof_obligations": LogicIRView(
                name="deontic_proof_obligations",
                format="deontic-proof-obligations",
                source_component="deontic.exports",
                payload={"records": deontic_exports["proof_obligation_records"]},
                metadata={
                    "proof_obligation_count": len(
                        deontic_exports["proof_obligation_records"]
                    ),
                },
            ),
            "deontic_repair_queue": LogicIRView(
                name="deontic_repair_queue",
                format="deontic-repair-queue",
                source_component="deontic.exports",
                payload={"records": deontic_exports["repair_queue_records"]},
                metadata={
                    "repair_record_count": len(
                        deontic_exports["repair_queue_records"]
                    ),
                },
            ),
            "deontic_reconstruction_slot_loss": LogicIRView(
                name="deontic_reconstruction_slot_loss",
                format="deontic-reconstruction-slot-loss",
                source_component="deontic.metrics",
                payload={
                    "records": deontic_exports["reconstruction_slot_loss_records"],
                    "summary": deontic_exports["reconstruction_slot_loss_summary"],
                },
                metadata={
                    "slot_loss_record_count": len(
                        deontic_exports["reconstruction_slot_loss_records"]
                    ),
                },
            ),
            "deontic_ir_slot_provenance": LogicIRView(
                name="deontic_ir_slot_provenance",
                format="deontic-ir-slot-provenance-audits",
                source_component="deontic.ir",
                payload={
                    "records": deontic_exports["ir_slot_provenance_records"],
                    "summary": deontic_exports["ir_slot_provenance_summary"],
                },
                metadata={
                    "provenance_record_count": len(
                        deontic_exports["ir_slot_provenance_records"]
                    ),
                },
            ),
            "deontic_phase8_quality": LogicIRView(
                name="deontic_phase8_quality",
                format="deontic-phase8-quality-summaries",
                source_component="deontic.metrics",
                payload={
                    "records": deontic_exports["phase8_quality_records"],
                    "summary": deontic_exports["phase8_quality_summary"],
                },
                metadata={
                    "quality_record_count": len(
                        deontic_exports["phase8_quality_records"]
                    ),
                    "requires_validation_count": int(
                        deontic_exports["phase8_quality_summary"].get(
                            "requires_validation_source_count"
                        )
                        or 0
                    ),
                },
            ),
            "deontic_graph": LogicIRView(
                name="deontic_graph",
                format="deontic-graph-v1",
                source_component="deontic.graph",
                payload=deontic_exports["deontic_graph"],
                metadata=deontic_exports["deontic_graph_metadata"],
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="deontic.prover_syntax",
                payload={"triples": [dict(triple) for triple in triples]},
                metadata={"triple_count": len(triples)},
            ),
        }
        if graph_data is not None:
            views["neo4j_graph_data"] = LogicIRView(
                name="neo4j_graph_data",
                format="neo4j-compatible-graph-data",
                source_component="knowledge_graphs.neo4j_compat",
                payload=graph_data.to_dict(),
                metadata={
                    "node_count": graph_data.node_count,
                    "relationship_count": graph_data.relationship_count,
                },
            )

        return (
            LegalIRDocument(
                document_id=resolved_document_id,
                source_text=text,
                normalized_text=_normalized_text_from_deontic_rows(
                    deontic_source_rows,
                    text,
                ),
                source=source,
                citation=citation or _citation_from_norms(norms),
                views=views,
                frame_logic_triples=triples,
                metadata={
                    "converter_success": bool(getattr(result, "success", False)),
                    "deontic_formula_record_proof_ready_count": int(
                        metadata.get("legal_formula_record_proof_ready_count") or 0
                    ),
                    "deontic_norm_count": len(norms),
                    "parser_element_count": len(deontic_source_rows),
                },
            ),
            {
                "conversion_result": result,
                "coverage_records": coverage_records,
                "deontic_exports": deontic_exports,
                "graph_data": graph_data,
                "parser_metrics": parser_metrics,
            },
        )

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        **_: Any,
    ) -> BridgeEvaluationReport:
        """Run the deontic bridge and return optimizer-visible diagnostics."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        proof_gate = _proof_gate_from_coverage_records(context["coverage_records"])
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        round_trip = _round_trip_from_deontic_context(
            context["parser_metrics"],
            context["deontic_exports"],
        )
        coverage_requires_validation = _coverage_requires_validation(
            context["coverage_records"]
        )
        proof_gate_soft_pass = _deontic_proof_gate_soft_pass(
            coverage_requires_validation=coverage_requires_validation,
            proof_gate=proof_gate,
        )
        status = "ok"
        if not proof_gate.compiles and not proof_gate_soft_pass:
            status = "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=_decoded_text_from_capability_view(ir_document),
            status=status,
            metadata={
                "adapter": "deontic_norms_bridge_v1",
                "coverage_requires_validation": coverage_requires_validation,
                "proof_gate_soft_pass": proof_gate_soft_pass,
            },
        )

    def _converter(self) -> Any:
        if self.converter is not None:
            return self.converter
        from ipfs_datasets_py.logic.deontic import DeonticConverter

        self.converter = DeonticConverter(**dict(self.converter_kwargs))
        return self.converter


def _summarize_parser_metrics(parser_elements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not parser_elements:
        return {}
    from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements

    return summarize_parser_elements([dict(item) for item in parser_elements])


def _formula_records_from_norm_objects(norm_objects: Sequence[Any]) -> list[dict[str, Any]]:
    if not norm_objects:
        return []
    from ipfs_datasets_py.logic.deontic.formula_builder import (
        build_deontic_formula_records_from_irs,
    )

    return build_deontic_formula_records_from_irs(norm_objects)


def _coverage_records_from_norm_objects(norm_objects: Sequence[Any]) -> list[dict[str, Any]]:
    if not norm_objects:
        return []
    from ipfs_datasets_py.logic.deontic.exports import (
        build_prover_syntax_target_coverage_records_from_irs,
    )

    return build_prover_syntax_target_coverage_records_from_irs(norm_objects)


def _coverage_records_from_embedded_prover_records(
    records_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Summarize nested target-level prover rows into bridge coverage reports."""

    if not records_by_source:
        return []
    from ipfs_datasets_py.logic.deontic.exports import (
        build_prover_syntax_target_coverage_record,
    )

    return [
        build_prover_syntax_target_coverage_record(source_id, records)
        for source_id, records in sorted(records_by_source.items())
        if source_id and records
    ]


def _prover_syntax_records_by_source_from_norm_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Extract target-level prover syntax rows embedded in LegalNormIR metadata."""

    records_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            continue
        records: list[dict[str, Any]] = []
        for key in ("prover_syntax_records", "local_prover_syntax_records"):
            records.extend(_list_of_dicts(row.get(key)))
        for record in records:
            record_source_id = str(record.get("source_id") or "").strip()
            if not record_source_id:
                record["source_id"] = source_id
            records_by_source.setdefault(source_id, []).append(record)
    return records_by_source


def _coverage_records_need_rebuild(records: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether persisted coverage rows are too legacy for proof-gate use."""

    if not records:
        return True

    for record in records:
        if not isinstance(record, Mapping):
            return True
        summary = record.get("coverage_summary")
        if not isinstance(summary, Mapping):
            return True
        required = summary.get("required_targets")
        status_by_target = summary.get("target_status_by_target")
        if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
            return True
        if not isinstance(status_by_target, Mapping):
            return True
        required_targets = [
            str(target).strip()
            for target in required
            if str(target).strip()
        ]
        if not required_targets:
            return True
        if any(target not in status_by_target for target in required_targets):
            return True
        quality_summary = summary.get("quality_gate_summary")
        if not isinstance(quality_summary, Mapping):
            return True
        role_summary = summary.get("target_role_matrix_summary")
        if not isinstance(role_summary, Mapping):
            return True
    return False


def _capability_records_from_norm_objects(norm_objects: Sequence[Any]) -> list[dict[str, Any]]:
    if not norm_objects:
        return []
    from ipfs_datasets_py.logic.deontic.exports import (
        build_deterministic_parser_capability_profile_records,
    )

    return build_deterministic_parser_capability_profile_records(norm_objects)


def _deontic_export_context_from_parser_elements(
    parser_elements: Sequence[Mapping[str, Any]],
    *,
    coverage_records: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    context = _empty_deontic_export_context()
    norm_objects = _legal_norm_objects_from_parser_elements(parser_elements)
    provenance_required_slots_by_source = _phase8_required_slots_by_source(norm_objects)
    decoder_required_slots_by_source = _decoder_required_slots_by_source(norm_objects)
    context["norm_count"] = len(norm_objects)
    if not norm_objects:
        return context

    from ipfs_datasets_py.logic.deontic.exports import (
        build_document_export_tables_from_ir,
        build_decoder_records_from_irs,
        build_ir_slot_provenance_audit_record,
        build_ir_slot_provenance_audit_records,
        build_phase8_quality_summary_record,
        build_phase8_quality_summary_records,
        build_prover_syntax_records_from_ir,
        build_reconstruction_slot_loss_record,
        build_reconstruction_slot_loss_records,
        summarize_ir_slot_provenance_audit_records,
        summarize_phase8_quality_records,
        summarize_reconstruction_slot_loss,
    )

    try:
        decoder_records = build_decoder_records_from_irs(norm_objects)
        context["decoder_records"] = decoder_records
        (
            reconstruction_slot_loss_records,
            reconstruction_slot_loss_summary,
        ) = _reconstruction_slot_loss_from_decoder_records(
            decoder_records,
            required_slots_by_source=decoder_required_slots_by_source,
            build_record=build_reconstruction_slot_loss_record,
            build_records=build_reconstruction_slot_loss_records,
            summarize=summarize_reconstruction_slot_loss,
        )
        context["reconstruction_slot_loss_records"] = reconstruction_slot_loss_records
        context["reconstruction_slot_loss_summary"] = reconstruction_slot_loss_summary
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "decoder_reconstruction", exc)
        decoder_records = []

    try:
        if provenance_required_slots_by_source:
            ir_slot_provenance_records = []
            for norm in norm_objects:
                source_id = str(getattr(norm, "source_id", "") or "").strip()
                slots = provenance_required_slots_by_source.get(source_id)
                if slots:
                    ir_slot_provenance_records.append(
                        build_ir_slot_provenance_audit_record(norm, slots=slots)
                    )
                else:
                    ir_slot_provenance_records.append(
                        build_ir_slot_provenance_audit_record(norm)
                    )
        else:
            ir_slot_provenance_records = build_ir_slot_provenance_audit_records(
                norm_objects
            )
        context["ir_slot_provenance_records"] = ir_slot_provenance_records
        context["ir_slot_provenance_summary"] = (
            summarize_ir_slot_provenance_audit_records(ir_slot_provenance_records)
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "ir_slot_provenance", exc)
        ir_slot_provenance_records = []

    try:
        prover_syntax_records: list[dict[str, Any]] = []
        for norm in norm_objects:
            prover_syntax_records.extend(build_prover_syntax_records_from_ir(norm))
        context["prover_syntax_records"] = prover_syntax_records
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "prover_syntax_records", exc)
        prover_syntax_records = []

    try:
        # Keep proof/repair rows aligned with the batch export path, which
        # applies deterministic same-document reference resolution before
        # formula-level validation.
        document_export_tables = build_document_export_tables_from_ir(norm_objects)
        context["proof_obligation_records"] = list(
            document_export_tables.get("proof_obligations", [])
        )
        context["repair_queue_records"] = list(
            document_export_tables.get("repair_queue", [])
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "proof_and_repair_records", exc)

    try:
        phase8_required_slots_by_source = (
            decoder_required_slots_by_source
            if decoder_required_slots_by_source
            else provenance_required_slots_by_source
        )
        if phase8_required_slots_by_source:
            decoder_by_source = _group_records_by_source(decoder_records)
            prover_by_source = _group_records_by_source(prover_syntax_records)
            provenance_by_source = _group_records_by_source(ir_slot_provenance_records)
            source_ids = sorted(
                set(decoder_by_source)
                | set(prover_by_source)
                | set(provenance_by_source)
            )
            phase8_records = [
                build_phase8_quality_summary_record(
                    source_id,
                    decoder_records=decoder_by_source.get(source_id, []),
                    prover_syntax_records=prover_by_source.get(source_id, []),
                    ir_slot_provenance_records=provenance_by_source.get(source_id, []),
                    required_slots=phase8_required_slots_by_source.get(source_id, ()),
                )
                for source_id in source_ids
            ]
        else:
            phase8_records = build_phase8_quality_summary_records(
                decoder_records=decoder_records,
                prover_syntax_records=prover_syntax_records,
                ir_slot_provenance_records=ir_slot_provenance_records,
            )
        phase8_records = _merge_phase8_validation_from_coverage_records(
            phase8_records,
            coverage_records,
        )
        _apply_phase8_quality_to_proof_and_repair_records(context, phase8_records)
        context["phase8_quality_records"] = phase8_records
        raw_phase8_summary = summarize_phase8_quality_records(
            decoder_records=decoder_records,
            prover_syntax_records=prover_syntax_records,
            ir_slot_provenance_records=ir_slot_provenance_records,
        )
        context["phase8_quality_summary"] = _phase8_summary_from_records(
            phase8_records,
            raw_phase8_summary,
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "phase8_quality", exc)

    graph_payload, graph_metadata = _deontic_graph_payload_from_norm_objects(norm_objects)
    context["deontic_graph"] = graph_payload
    context["deontic_graph_metadata"] = graph_metadata
    return context


def _empty_deontic_export_context() -> dict[str, Any]:
    return {
        "decoder_records": [],
        "deontic_graph": {},
        "deontic_graph_metadata": {
            "build_error_count": 0,
            "conflict_count": 0,
            "node_count": 0,
            "rule_count": 0,
            "source_gap_count": 0,
        },
        "export_build_errors": {},
        "ir_slot_provenance_records": [],
        "ir_slot_provenance_summary": {},
        "norm_count": 0,
        "phase8_quality_records": [],
        "phase8_quality_summary": {},
        "proof_obligation_records": [],
        "prover_syntax_records": [],
        "reconstruction_slot_loss_records": [],
        "reconstruction_slot_loss_summary": {},
        "repair_queue_records": [],
    }


def _record_export_context_error(
    context: dict[str, Any],
    name: str,
    exc: Exception,
) -> None:
    errors = dict(context.get("export_build_errors") or {})
    errors[name] = f"{type(exc).__name__}: {exc}"
    context["export_build_errors"] = errors


def _legal_norm_objects_from_parser_elements(
    parser_elements: Sequence[Mapping[str, Any]],
) -> list[Any]:
    if not parser_elements:
        return []
    from ipfs_datasets_py.logic.deontic.ir import LegalNormIR

    norms: list[Any] = []
    for element in parser_elements:
        try:
            norms.append(LegalNormIR.from_parser_element(dict(element)))
        except Exception:
            continue
    return norms


def _phase8_required_slots_by_source(
    norm_objects: Sequence[Any],
) -> dict[str, tuple[str, ...]]:
    """Return source-keyed Phase 8 slot requirements derived from typed IR."""

    if not norm_objects:
        return {}
    from ipfs_datasets_py.logic.deontic.ir import legal_norm_ir_phase8_required_slots

    required_by_source: dict[str, tuple[str, ...]] = {}
    for norm in norm_objects:
        source_id = str(getattr(norm, "source_id", "") or "").strip()
        if not source_id:
            continue
        merged = list(required_by_source.get(source_id, ()))
        for slot in legal_norm_ir_phase8_required_slots(norm):
            slot_name = str(slot or "").strip()
            if slot_name and slot_name not in merged:
                merged.append(slot_name)
        required_by_source[source_id] = tuple(merged)
    return required_by_source


def _decoder_required_slots_by_source(
    norm_objects: Sequence[Any],
) -> dict[str, tuple[str, ...]]:
    """Return source-keyed decoder slot requirements by deontic family.

    The decoder emits family-specific phrase slots: definition/applicability
    connectors are fixed text and should not force a missing ``modality`` slot
    in reconstruction loss. This helper keeps core deontic checks strict for
    O/P/F clauses while using decoder-native requirements for other families.
    """

    if not norm_objects:
        return {}

    required_by_source: dict[str, tuple[str, ...]] = {}
    optional_slots = (
        "conditions",
        "exceptions",
        "temporal_constraints",
        "cross_references",
    )
    for norm in norm_objects:
        source_id = str(getattr(norm, "source_id", "") or "").strip()
        if not source_id:
            continue

        merged = list(required_by_source.get(source_id, ()))
        for slot_name in _decoder_required_core_slots_for_norm(norm):
            if slot_name and slot_name not in merged:
                merged.append(slot_name)

        for slot_name in optional_slots:
            if slot_name in merged:
                continue
            slot_value = _decoder_slot_value(norm, slot_name)
            if _slot_value_present(slot_value):
                merged.append(slot_name)

        required_by_source[source_id] = tuple(merged)
    return required_by_source


def _decoder_required_core_slots_for_norm(norm: Any) -> tuple[str, ...]:
    norm_type = str(getattr(norm, "norm_type", "") or "").strip().lower()
    modality = str(getattr(norm, "modality", "") or "").strip().upper()

    if norm_type == "definition" or modality == "DEF":
        return ("actor",)
    if norm_type in {"applicability", "exemption", "instrument_lifecycle"} or modality in {
        "APP",
        "EXEMPT",
        "LIFE",
    }:
        return ("actor", "action")
    return ("actor", "modality", "action")


def _decoder_slot_value(norm: Any, slot_name: str) -> Any:
    if slot_name == "cross_references":
        references = list(getattr(norm, "cross_references", ()) or ())
        references.extend(
            reference
            for reference in list(getattr(norm, "resolved_cross_references", ()) or ())
            if reference not in references
        )
        return references
    return getattr(norm, slot_name, None)


def _slot_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _group_records_by_source(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if not source_id:
            continue
        grouped.setdefault(source_id, []).append(dict(record))
    return grouped


def _reconstruction_slot_loss_from_decoder_records(
    decoder_records: Sequence[Mapping[str, Any]],
    *,
    required_slots_by_source: Mapping[str, Sequence[str]],
    build_record: Any,
    build_records: Any,
    summarize: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build reconstruction slot-loss rows with per-source required slots.

    The bridge already derives per-source Phase 8 required slots from typed IR
    (core slots plus only optional slots that are present). Reuse those
    requirements for decoder slot-loss rows so missing optional structures do
    not inflate reconstruction loss for otherwise complete clauses.
    """

    if not decoder_records:
        return [], {}

    if not required_slots_by_source:
        return (
            list(build_records(decoder_records)),
            dict(summarize(decoder_records)),
        )

    grouped = _group_records_by_source(decoder_records)
    rows: list[dict[str, Any]] = []
    for source_id in sorted(grouped):
        source_slots = tuple(
            slot
            for slot in (
                str(slot_name or "").strip()
                for slot_name in required_slots_by_source.get(source_id, ())
            )
            if slot
        )
        if source_slots:
            rows.append(
                build_record(
                    source_id,
                    grouped[source_id],
                    required_slots=source_slots,
                )
            )
            continue
        rows.append(build_record(source_id, grouped[source_id]))

    return rows, _summarize_reconstruction_slot_loss_rows(rows)


def _summarize_reconstruction_slot_loss_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate source-level reconstruction rows into bridge summary metrics."""

    if not rows:
        return {}

    source_ids: set[str] = set()
    required_slots: list[str] = []
    grounded_required_slots: list[str] = []
    missing_required_slots: list[str] = []
    ungrounded_required_slots: list[str] = []
    extra_ungrounded_slots: list[str] = []
    blockers: set[str] = set()

    record_count = 0
    required_slot_count = 0
    grounded_required_slot_count = 0
    missing_required_slot_count = 0
    ungrounded_slot_count = 0
    all_complete = True

    for row in rows:
        if not isinstance(row, Mapping):
            continue

        summary = row.get("coverage_summary")
        summary_mapping = summary if isinstance(summary, Mapping) else row

        source_id = str(row.get("source_id") or "").strip()
        if source_id:
            source_ids.add(source_id)

        record_count += int(summary_mapping.get("record_count") or 0)
        required_slot_count += int(summary_mapping.get("required_slot_count") or 0)
        grounded_required_slot_count += int(
            summary_mapping.get("grounded_required_slot_count") or 0
        )
        missing_required_slot_count += int(
            summary_mapping.get("missing_required_slot_count") or 0
        )
        ungrounded_slot_count += int(summary_mapping.get("ungrounded_slot_count") or 0)

        _append_unique_strings(required_slots, summary_mapping.get("required_slots"))
        _append_unique_strings(
            grounded_required_slots,
            summary_mapping.get("grounded_required_slots"),
        )
        _append_unique_strings(
            missing_required_slots,
            summary_mapping.get("missing_required_slots"),
        )
        _append_unique_strings(
            ungrounded_required_slots,
            summary_mapping.get("ungrounded_required_slots"),
        )
        _append_unique_strings(
            extra_ungrounded_slots,
            summary_mapping.get("extra_ungrounded_slots"),
        )
        blockers.update(_list_of_strings(row.get("coverage_blockers")))
        blockers.update(_list_of_strings(summary_mapping.get("coverage_blockers")))

        if summary_mapping.get("slot_reconstruction_complete") is not True:
            all_complete = False

    if record_count <= 0:
        record_count = len(
            [row for row in rows if isinstance(row, Mapping)]
        )

    grounded_required_slot_rate = (
        round(grounded_required_slot_count / required_slot_count, 6)
        if required_slot_count
        else 0.0
    )
    grounded_or_ungrounded = grounded_required_slot_count + ungrounded_slot_count
    ungrounded_decoded_slot_rate = (
        round(ungrounded_slot_count / grounded_or_ungrounded, 6)
        if grounded_or_ungrounded
        else 0.0
    )

    return {
        "source_ids": sorted(source_ids),
        "record_count": record_count,
        "required_slots": required_slots,
        "grounded_required_slots": grounded_required_slots,
        "missing_required_slots": missing_required_slots,
        "ungrounded_required_slots": ungrounded_required_slots,
        "extra_ungrounded_slots": extra_ungrounded_slots,
        "required_slot_count": required_slot_count,
        "grounded_required_slot_count": grounded_required_slot_count,
        "missing_required_slot_count": missing_required_slot_count,
        "ungrounded_slot_count": ungrounded_slot_count,
        "slot_reconstruction_complete": bool(rows) and all_complete,
        "grounded_required_slot_rate": grounded_required_slot_rate,
        "ungrounded_decoded_slot_rate": ungrounded_decoded_slot_rate,
        "coverage_blockers": sorted(blockers),
    }


def _append_unique_strings(target: list[str], value: Any) -> None:
    for item in _list_of_strings(value):
        if item not in target:
            target.append(item)


def _phase8_summary_from_records(
    records: Sequence[Mapping[str, Any]],
    default_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay aggregate source-level completion fields from Phase 8 rows."""

    summary = dict(default_summary or {})
    valid_records = [record for record in records or [] if isinstance(record, Mapping)]
    record_count = len(valid_records)
    complete_count = sum(
        1
        for record in valid_records
        if record.get("phase8_quality_complete") is True
    )
    requires_validation_count = sum(
        1
        for record in valid_records
        if record.get("requires_validation") is True
    )
    blockers: set[str] = set()
    for record in valid_records:
        blockers.update(
            str(blocker or "").strip()
            for blocker in (record.get("coverage_blockers") or [])
            if str(blocker or "").strip()
        )

    summary.update(
        {
            "source_record_count": record_count,
            "complete_source_count": complete_count,
            "source_complete_rate": round(complete_count / record_count, 6)
            if record_count
            else 0.0,
            "requires_validation_source_count": requires_validation_count,
            "source_requires_validation_rate": round(
                requires_validation_count / record_count,
                6,
            )
            if record_count
            else 0.0,
            "phase8_quality_complete": bool(record_count and complete_count == record_count),
            "requires_validation": bool(requires_validation_count),
            "coverage_blockers": sorted(blockers),
        }
    )
    return summary


def _apply_phase8_quality_to_proof_and_repair_records(
    context: dict[str, Any],
    phase8_records: Sequence[Mapping[str, Any]],
) -> None:
    """Clear stale proof repair flags for source-level validated Phase 8 rows."""

    validated_source_ids = _phase8_quality_validated_source_ids(phase8_records)
    if not validated_source_ids:
        return

    proof_records: list[dict[str, Any]] = []
    for record in _list_of_dicts(context.get("proof_obligation_records")):
        source_id = str(record.get("source_id") or "").strip()
        if source_id in validated_source_ids:
            record = _phase8_quality_validated_proof_record(record)
        proof_records.append(record)
    context["proof_obligation_records"] = proof_records

    repair_records: list[dict[str, Any]] = []
    for record in _list_of_dicts(context.get("repair_queue_records")):
        source_id = str(record.get("source_id") or "").strip()
        if source_id in validated_source_ids:
            continue
        repair_records.append(record)
    context["repair_queue_records"] = repair_records


def _phase8_quality_validated_source_ids(
    records: Sequence[Mapping[str, Any]],
) -> set[str]:
    source_ids: set[str] = set()
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if not source_id:
            continue
        if record.get("phase8_quality_complete") is not True:
            continue
        if _truthy_flag(record.get("requires_validation")):
            continue
        if _list_of_strings(record.get("coverage_blockers")):
            continue
        source_ids.add(source_id)
    return source_ids


def _phase8_quality_validated_proof_record(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(record)
    row["requires_validation"] = False
    row["repair_required"] = False
    row["theorem_candidate"] = True
    row["proof_ready"] = True
    row["validated_by_phase8_quality_gate"] = True
    resolution = dict(row.get("deterministic_resolution") or {})
    if not resolution:
        resolution = {"type": "phase8_quality_gate_validated"}
    else:
        resolution.setdefault("phase8_quality_gate_validated", True)
    row["deterministic_resolution"] = resolution
    return row


def _deontic_graph_payload_from_norm_objects(
    norm_objects: Sequence[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not norm_objects:
        return {}, dict(_empty_deontic_export_context()["deontic_graph_metadata"])
    try:
        from ipfs_datasets_py.logic.deontic.graph import DeonticGraphBuilder

        rows = [_deontic_graph_row_from_norm(norm) for norm in norm_objects]
        graph = DeonticGraphBuilder().build_from_matrix(rows)
        conflicts = [item.to_dict() for item in graph.detect_conflicts(only_active=False)]
        gap_summary = graph.source_gap_summary()
        payload = graph.to_dict()
        payload["conflicts"] = conflicts
        payload["source_gap_summary"] = gap_summary
        metadata = {
            "build_error_count": 0,
            "conflict_count": len(conflicts),
            "node_count": len(graph.nodes),
            "rule_count": len(graph.rules),
            "source_gap_count": len(gap_summary.get("rules_with_gaps") or []),
        }
        return payload, metadata
    except Exception as exc:  # pragma: no cover - diagnostics only
        return {}, {
            "build_error": f"{type(exc).__name__}: {exc}",
            "build_error_count": 1,
            "conflict_count": 0,
            "node_count": 0,
            "rule_count": 0,
            "source_gap_count": 0,
        }


def _deontic_graph_row_from_norm(norm: Any) -> dict[str, Any]:
    source_id = str(getattr(norm, "source_id", "") or "")
    base_id = source_id or _stable_norm_id(norm)
    actor = str(getattr(norm, "actor", "") or "").strip()
    action = str(getattr(norm, "action", "") or "").strip()
    citation = str(getattr(norm, "canonical_citation", "") or "").strip()
    source_nodes: list[dict[str, Any]] = []
    if actor:
        source_nodes.append(
            {
                "id": f"{base_id}:actor",
                "label": actor,
                "node_type": "actor",
                "active": True,
                "confidence": 1.0,
            }
        )
    for index, condition in enumerate(
        _string_list(getattr(norm, "conditions", ())),
        start=1,
    ):
        source_nodes.append(
            {
                "id": f"{base_id}:condition:{index}",
                "label": condition,
                "node_type": "condition",
                "active": True,
                "confidence": 1.0,
            }
        )
    authority_nodes = (
        [
            {
                "id": f"{base_id}:authority",
                "label": citation,
                "attributes": {"canonical_citation": citation},
            }
        ]
        if citation
        else []
    )
    return {
        "rule_id": base_id,
        "modality": _graph_modality(getattr(norm, "modality", "")),
        "predicate": _safe_predicate(
            action or getattr(norm, "norm_type", "") or "governs"
        ),
        "target_id": f"{base_id}:action",
        "target_label": action
        or str(getattr(norm, "support_text", "") or "Governed action"),
        "target_type": "action",
        "target_active": True,
        "sources": source_nodes,
        "authorities": authority_nodes,
        "evidence_ids": [source_id] if source_id else [],
        "active": True,
        "confidence": 1.0,
        "attributes": {
            "blockers": list(getattr(norm, "blockers", []) or []),
            "canonical_citation": citation,
            "norm_type": str(getattr(norm, "norm_type", "") or ""),
            "proof_ready": bool(getattr(norm, "proof_ready", False)),
            "source_id": source_id,
        },
    }


def _graph_modality(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"obligation", "prohibition", "permission", "entitlement"}:
        return text
    if text in {"must_not", "shall_not", "forbidden", "prohibited"}:
        return "prohibition"
    if text in {"may", "authorized", "allowed"}:
        return "permission"
    return "obligation"


def _stable_norm_id(norm: Any) -> str:
    seed = "|".join(
        str(getattr(norm, name, "") or "")
        for name in ("source_id", "canonical_citation", "support_text", "action")
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"deontic-norm:{digest}"


def _safe_predicate(value: Any) -> str:
    text = str(value or "").strip().lower()
    tokens = [
        "".join(char for char in token if char.isalnum())
        for token in text.split()
    ]
    predicate = "_".join(token for token in tokens if token)
    return predicate or "governs"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        value = value.values()
    if isinstance(value, str):
        value = [value]
    try:
        candidates = list(value)
    except TypeError:
        return []
    return [str(item).strip() for item in candidates if str(item).strip()]


def _round_trip_from_deontic_context(
    metrics: Mapping[str, Any],
    deontic_exports: Mapping[str, Any],
) -> RoundTripMetrics:
    grounded_phrase_rate = _float(metrics.get("phase8_decoder_grounded_phrase_rate"))
    grounded_slot_rate = _float(metrics.get("phase8_parser_capability_decoder_grounding_rate"))
    if grounded_phrase_rate <= 0.0:
        grounded_phrase_rate = grounded_slot_rate
    syntax_valid_rate = _float(metrics.get("phase8_prover_syntax_valid_rate"))
    quality_requires_validation_rate = _float(
        metrics.get("phase8_quality_requires_validation_rate")
    )
    norm_count = int(deontic_exports.get("norm_count") or 0)
    if norm_count <= 0:
        # Non-normative legal text should not force a hard deontic loss.
        grounded_phrase_rate = 1.0
        grounded_slot_rate = 1.0
        syntax_valid_rate = 1.0
        quality_requires_validation_rate = 0.0
    reconstruction_summary = _mapping(
        deontic_exports.get("reconstruction_slot_loss_summary")
    )
    provenance_summary = _mapping(deontic_exports.get("ir_slot_provenance_summary"))
    graph_metadata = _mapping(deontic_exports.get("deontic_graph_metadata"))
    phase8_quality_records = _list_of_dicts(deontic_exports.get("phase8_quality_records"))
    decoder_records = _list_of_dicts(deontic_exports.get("decoder_records"))
    repair_queue_records = _list_of_dicts(deontic_exports.get("repair_queue_records"))
    phase8_quality_summary = _mapping(deontic_exports.get("phase8_quality_summary"))
    quality_incomplete_rate = _record_validation_rate(phase8_quality_records)
    quality_requires_validation_rate = _rate(
        phase8_quality_summary.get("requires_validation_source_count"),
        phase8_quality_summary.get("source_record_count"),
    )
    if not phase8_quality_records and quality_requires_validation_rate <= 0.0:
        quality_requires_validation_rate = _float(
            metrics.get("phase8_quality_requires_validation_rate")
        )
    decoder_requires_validation_rate = _record_validation_rate(decoder_records)
    extra_losses = {
        "deontic_decoder_requires_validation_rate": decoder_requires_validation_rate,
        "deontic_decoder_slot_loss": max(
            0.0,
            1.0 - _float(reconstruction_summary.get("grounded_required_slot_rate")),
        )
        if reconstruction_summary
        else (1.0 if norm_count else 0.0),
        "deontic_graph_build_error_loss": min(
            1.0,
            _float(graph_metadata.get("build_error_count")),
        ),
        "deontic_graph_conflict_loss": _rate(
            graph_metadata.get("conflict_count"),
            graph_metadata.get("rule_count"),
        ),
        "deontic_graph_source_gap_loss": _rate(
            graph_metadata.get("source_gap_count"),
            graph_metadata.get("rule_count"),
        ),
        "deontic_ir_slot_provenance_loss": max(
            0.0,
            1.0 - _float(provenance_summary.get("grounded_slot_rate")),
        )
        if provenance_summary
        else (1.0 if norm_count else 0.0),
        "deontic_phase8_quality_incomplete_loss": quality_incomplete_rate,
        "deontic_quality_requires_validation_loss": quality_requires_validation_rate,
        "deontic_repair_queue_rate": _rate(len(repair_queue_records), norm_count),
        "deontic_repair_required_rate": _float(metrics.get("repair_required_rate")),
    }
    return RoundTripMetrics(
        cosine_similarity=grounded_phrase_rate,
        cosine_loss=max(0.0, 1.0 - grounded_phrase_rate),
        cross_entropy_loss=0.0,
        reconstruction_loss=max(0.0, 1.0 - grounded_slot_rate),
        text_reconstruction_loss=max(0.0, 1.0 - grounded_phrase_rate),
        symbolic_validity_penalty=max(0.0, 1.0 - syntax_valid_rate),
        extra_losses=extra_losses,
    )


def _proof_gate_from_coverage_records(records: Sequence[Mapping[str, Any]]) -> ProofGateResult:
    if not records:
        return ProofGateResult.disabled(reason="no_deontic_coverage_records")
    soft_targets = {"frame_logic"}
    attempted_count = 0
    valid_count = 0
    failed_count = 0
    details = []
    verified_by = set()
    for record in records:
        summary = _coverage_summary_from_record(record)
        passed_targets = list(summary["passed_targets"])
        failed_targets = list(summary["failed_targets"])
        missing_targets = list(summary["missing_targets"])
        soft_failed_targets = [
            target for target in failed_targets if str(target) in soft_targets
        ]
        soft_missing_targets = [
            target for target in missing_targets if str(target) in soft_targets
        ]
        blocking_failed_targets = [
            target for target in failed_targets if str(target) not in soft_targets
        ]
        blocking_missing_targets = [
            target for target in missing_targets if str(target) not in soft_targets
        ]
        attempted_count += (
            len(passed_targets)
            + len(blocking_failed_targets)
            + len(blocking_missing_targets)
        )
        valid_count += len(passed_targets)
        failed_count += len(blocking_failed_targets) + len(blocking_missing_targets)
        verified_by.update(f"deontic:{target}" for target in passed_targets)
        details.append(
            {
                "coverage_blockers": list(record.get("coverage_blockers") or []),
                "passed_targets": passed_targets,
                "failed_targets": failed_targets,
                "blocking_failed_targets": blocking_failed_targets,
                "missing_targets": missing_targets,
                "blocking_missing_targets": blocking_missing_targets,
                "soft_failed_targets": soft_failed_targets,
                "soft_missing_targets": soft_missing_targets,
                "requires_validation": _coverage_record_requires_validation(record),
                "source_id": record.get("source_id"),
                "syntax_valid_rate": summary["syntax_valid_rate"],
            }
        )
    attempted_count = max(attempted_count, valid_count)
    return ProofGateResult(
        attempted_count=attempted_count,
        valid_count=valid_count,
        failed_count=failed_count,
        verified_by=tuple(sorted(verified_by)),
        details=tuple(details),
    )


def _coverage_summary_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    summary = record.get("coverage_summary")
    if isinstance(summary, Mapping):
        has_target_lists = any(
            isinstance(summary.get(key), Sequence) and not isinstance(summary.get(key), (str, bytes))
            for key in ("passed_targets", "failed_targets", "missing_targets")
        )
        if has_target_lists:
            return {
                "passed_targets": [
                    str(target).strip()
                    for target in summary.get("passed_targets") or []
                    if str(target).strip()
                ],
                "failed_targets": [
                    str(target).strip()
                    for target in summary.get("failed_targets") or []
                    if str(target).strip()
                ],
                "missing_targets": [
                    str(target).strip()
                    for target in summary.get("missing_targets") or []
                    if str(target).strip()
                ],
                "syntax_valid_rate": summary.get("syntax_valid_rate"),
            }

        required_targets = _normalized_target_names(summary.get("required_targets"))
        status_by_target = summary.get("target_status_by_target")
        if required_targets and isinstance(status_by_target, Mapping):
            passed_targets: list[str] = []
            failed_targets: list[str] = []
            missing_targets: list[str] = []
            for target in required_targets:
                status = str(status_by_target.get(target) or "").strip().lower()
                if status in {"passed", "pass", "valid", "ok"}:
                    passed_targets.append(target)
                elif status in {"missing", "absent"}:
                    missing_targets.append(target)
                elif status in {"skipped", "skip", "unavailable"}:
                    # Skipped targets stay non-blocking for proof compilation.
                    continue
                elif status in {"failed", "failure", "invalid", "error"}:
                    failed_targets.append(target)
                else:
                    failed_targets.append(target)

            syntax_valid_rate = _float(summary.get("syntax_valid_rate"))
            if syntax_valid_rate <= 0.0 and required_targets:
                syntax_valid_rate = len(passed_targets) / len(required_targets)
            return {
                "passed_targets": passed_targets,
                "failed_targets": failed_targets,
                "missing_targets": missing_targets,
                "syntax_valid_rate": syntax_valid_rate,
            }

    required_targets = _normalized_target_names(record.get("required_targets"))
    if not required_targets:
        required_targets = [
            "frame_logic",
            "deontic_cec",
            "fol",
            "deontic_fol",
            "deontic_temporal_fol",
        ]

    blocked = _blocked_targets_from_coverage_blockers(
        _list_of_strings(record.get("coverage_blockers"))
    )
    failed_targets = blocked["failed"]
    missing_targets = blocked["missing"]
    skipped_targets = blocked["skipped"]
    failed_or_missing = set(failed_targets) | set(missing_targets) | set(skipped_targets)
    present_count = int(record.get("present_required_target_count") or 0)
    if present_count <= 0:
        present_count = len(required_targets)
    present_targets = list(required_targets[:present_count])
    syntax_valid_rate = _float(record.get("syntax_valid_rate"))
    formal_syntax_valid = bool(record.get("formal_syntax_valid") is True)

    if (formal_syntax_valid or syntax_valid_rate >= 1.0) and not failed_or_missing:
        passed_targets = present_targets
    elif failed_or_missing:
        passed_targets = [target for target in present_targets if target not in failed_or_missing]
    else:
        passed_count = int(round(max(0.0, min(1.0, syntax_valid_rate)) * len(present_targets)))
        passed_targets = present_targets[:passed_count]

    return {
        "passed_targets": passed_targets,
        "failed_targets": failed_targets,
        "missing_targets": missing_targets,
        "syntax_valid_rate": syntax_valid_rate,
    }


def _blocked_targets_from_coverage_blockers(
    blockers: Sequence[str],
) -> dict[str, list[str]]:
    missing: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    prefixes = (
        ("missing_prover_syntax_target:", missing),
        ("failed_prover_syntax_target:", failed),
        ("skipped_prover_syntax_target:", skipped),
    )
    for blocker in blockers:
        text = str(blocker or "").strip()
        if not text:
            continue
        for prefix, targets in prefixes:
            if not text.startswith(prefix):
                continue
            target = text[len(prefix) :].strip()
            target = target.split(":", 1)[0].strip()
            if target and target not in targets:
                targets.append(target)
            break
    return {"missing": missing, "failed": failed, "skipped": skipped}


def _frame_logic_triples_from_deontic_records(
    document_id: str,
    *,
    norms: Sequence[Mapping[str, Any]],
    formula_records: Sequence[Mapping[str, Any]],
    coverage_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples: list[dict[str, str]] = [
        {"subject": document_id, "predicate": "type", "object": "legal_deontic_document"}
    ]
    formulas_by_source = {
        str(record.get("source_id")): record
        for record in formula_records
        if record.get("source_id")
    }
    coverage_by_source = {
        str(record.get("source_id")): record
        for record in coverage_records
        if record.get("source_id")
    }
    for index, norm in enumerate(norms):
        source_id = str(norm.get("source_id") or f"{document_id}:norm:{index}")
        triples.extend(
            [
                {"subject": document_id, "predicate": "contains_norm", "object": source_id},
                {"subject": source_id, "predicate": "type", "object": "legal_deontic_norm"},
                {"subject": source_id, "predicate": "norm_type", "object": str(norm.get("norm_type") or "")},
                {"subject": source_id, "predicate": "modality", "object": str(norm.get("modality") or "")},
                {"subject": source_id, "predicate": "actor", "object": str(norm.get("actor") or "")},
                {"subject": source_id, "predicate": "action", "object": str(norm.get("action") or "")},
            ]
        )
        formula_record = formulas_by_source.get(source_id, {})
        if formula_record:
            triples.extend(
                [
                    {"subject": source_id, "predicate": "formula", "object": str(formula_record.get("formula") or "")},
                    {"subject": source_id, "predicate": "target_logic", "object": str(formula_record.get("target_logic") or "")},
                    {"subject": source_id, "predicate": "proof_ready", "object": str(bool(formula_record.get("proof_ready"))).lower()},
                ]
            )
        coverage_record = coverage_by_source.get(source_id, {})
        summary = coverage_record.get("coverage_summary") or {}
        semantic = summary.get("semantic_family_summary") or {}
        if semantic:
            triples.append(
                {
                    "subject": source_id,
                    "predicate": "semantic_formula_family",
                    "object": str(semantic.get("semantic_formula_family") or ""),
                }
            )
        for target in summary.get("passed_targets") or []:
            triples.append(
                {
                    "subject": source_id,
                    "predicate": "syntax_valid_for_target",
                    "object": str(target),
                }
            )
    return [triple for triple in triples if triple["object"]]


def _graph_data_from_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    graph_id: str,
    metadata: Mapping[str, Any],
) -> Any:
    if not triples:
        return None
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    return flogic_triples_to_graph_data(triples, graph_id=graph_id, metadata=metadata)


def _coverage_requires_validation(records: Sequence[Mapping[str, Any]]) -> bool:
    return _coverage_validation_metrics(records)["requires_validation_count"] > 0


def _coverage_validation_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = 0
    requires_validation = 0
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        total += 1
        if _coverage_record_requires_validation(record):
            requires_validation += 1
    validated = max(0, total - requires_validation)
    return {
        "record_count": total,
        "requires_validation_count": requires_validation,
        "requires_validation_rate": round(requires_validation / total, 6) if total else 0.0,
        "validated_count": validated,
    }


def _coverage_record_requires_validation(record: Mapping[str, Any]) -> bool:
    if _coverage_record_validated_by_quality_gate(record):
        return False
    if _truthy_flag(record.get("requires_validation")):
        return True
    summary = record.get("coverage_summary")
    if isinstance(summary, Mapping) and _truthy_flag(summary.get("requires_validation")):
        return True
    return False


def _normalize_coverage_validation_records(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Clear stale validation flags when a complete quality gate validates a row."""

    normalized: list[dict[str, Any]] = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        row = dict(record)
        summary = row.get("coverage_summary")
        if isinstance(summary, Mapping):
            row["coverage_summary"] = dict(summary)

        if _coverage_record_validated_by_quality_gate(row):
            row["requires_validation"] = False
            row["validated_by_quality_gate"] = True
            if isinstance(row.get("coverage_summary"), Mapping):
                coverage_summary = dict(row["coverage_summary"])
                coverage_summary["requires_validation"] = False
                coverage_summary["validated_by_quality_gate"] = True
                row["coverage_summary"] = coverage_summary

        normalized.append(row)
    return normalized


def _coverage_record_validated_by_quality_gate(record: Mapping[str, Any]) -> bool:
    """Return whether bridge-level target quality clears stale validation flags."""

    if _list_of_strings(record.get("coverage_blockers")):
        return False

    summary = record.get("coverage_summary")
    if not isinstance(summary, Mapping):
        return False
    if _list_of_strings(summary.get("coverage_blockers")):
        return False

    quality_summary = summary.get("quality_gate_summary")
    if not isinstance(quality_summary, Mapping):
        quality_summary = record.get("quality_gate_summary")
    if not isinstance(quality_summary, Mapping):
        quality_summary = {}

    required_targets = _normalized_target_names(
        summary.get("required_targets") or record.get("required_targets")
    )
    passed_targets = _normalized_target_names(summary.get("passed_targets"))
    if (
        _normalized_target_names(summary.get("failed_targets"))
        or _normalized_target_names(summary.get("missing_targets"))
        or _normalized_target_names(summary.get("skipped_targets"))
    ):
        return False
    target_status = summary.get("target_status_by_target")
    if not passed_targets and required_targets and isinstance(target_status, Mapping):
        passed_targets = [
            target
            for target in required_targets
            if str(target_status.get(target) or "").strip().lower()
            in {"passed", "pass", "valid", "ok"}
        ]

    all_required_passed = bool(summary.get("all_required_passed") is True)
    if required_targets:
        all_required_passed = all_required_passed or all(
            target in passed_targets for target in required_targets
        )
    if not all_required_passed:
        return False

    quality_complete = quality_summary.get("quality_gate_all_targets_complete")
    legacy_complete_without_quality_summary = (
        not quality_summary
        and all_required_passed
        and bool(required_targets)
    )
    if quality_complete is not True and not legacy_complete_without_quality_summary:
        return False
    if int(quality_summary.get("failed_quality_check_count") or 0) > 0:
        return False
    failed_distribution = quality_summary.get("failed_quality_check_distribution")
    if isinstance(failed_distribution, Mapping) and any(
        int(count or 0) > 0 for count in failed_distribution.values()
    ):
        return False

    role_summary = summary.get("target_role_matrix_summary")
    if not isinstance(role_summary, Mapping):
        role_summary = record.get("target_role_matrix_summary")
    if isinstance(role_summary, Mapping):
        if role_summary.get("target_role_matrix_complete") is False:
            return False
        if _truthy_flag(role_summary.get("target_role_matrix_requires_validation")):
            return False
        if _list_of_strings(role_summary.get("target_role_matrix_blockers")):
            return False

    return True


def _truthy_flag(value: Any) -> bool:
    """Coerce legacy boolean-like values without treating ``\"false\"`` as true."""

    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if not text:
        return False
    if text in {"0", "false", "no", "n", "off"}:
        return False
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    return True


def _merge_phase8_validation_from_coverage_records(
    phase8_records: Sequence[Mapping[str, Any]],
    coverage_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    coverage_by_source: dict[str, dict[str, Any]] = {}
    for record in coverage_records or []:
        if not isinstance(record, Mapping):
            continue
        source_id = str(record.get("source_id") or "").strip()
        if source_id:
            coverage_by_source[source_id] = dict(record)

    if not phase8_records:
        return [
            _phase8_record_from_coverage_record(coverage_by_source[source_id])
            for source_id in sorted(coverage_by_source)
        ]

    merged: list[dict[str, Any]] = []
    merged_source_ids: set[str] = set()
    for phase8_record in phase8_records:
        row = dict(phase8_record)
        source_id = str(row.get("source_id") or "").strip()
        if source_id:
            merged_source_ids.add(source_id)
        coverage_record = coverage_by_source.get(source_id)
        if coverage_record is None:
            merged.append(row)
            continue

        blockers = set(_list_of_strings(row.get("coverage_blockers")))
        blockers.update(_list_of_strings(coverage_record.get("coverage_blockers")))

        requires_validation = _truthy_flag(
            row.get("requires_validation")
        ) or _coverage_record_requires_validation(coverage_record)
        row["coverage_blockers"] = sorted(blockers)
        row["requires_validation"] = requires_validation
        row["phase8_quality_complete"] = (
            bool(row.get("phase8_quality_complete")) and not requires_validation
        )
        coverage_summary = row.get("coverage_summary")
        if isinstance(coverage_summary, Mapping):
            summary = dict(coverage_summary)
            summary["requires_validation"] = requires_validation
            summary["phase8_quality_complete"] = bool(
                summary.get("phase8_quality_complete")
            ) and not requires_validation
            summary_blockers = set(_list_of_strings(summary.get("coverage_blockers")))
            summary_blockers.update(blockers)
            summary["coverage_blockers"] = sorted(summary_blockers)
            row["coverage_summary"] = summary
        merged.append(row)

    for source_id, coverage_record in sorted(coverage_by_source.items()):
        if source_id in merged_source_ids:
            continue
        merged.append(_phase8_record_from_coverage_record(coverage_record))

    return merged


def _phase8_record_from_coverage_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a minimal Phase 8 row when only coverage diagnostics are present."""

    source_id = str(record.get("source_id") or "").strip()
    requires_validation = _coverage_record_requires_validation(record)
    blockers = sorted(_list_of_strings(record.get("coverage_blockers")))
    summary = record.get("coverage_summary")
    coverage_summary = dict(summary) if isinstance(summary, Mapping) else {}
    coverage_summary["requires_validation"] = requires_validation
    coverage_summary["phase8_quality_complete"] = not requires_validation
    summary_blockers = set(_list_of_strings(coverage_summary.get("coverage_blockers")))
    summary_blockers.update(blockers)
    coverage_summary["coverage_blockers"] = sorted(summary_blockers)
    return {
        "source_id": source_id,
        "phase8_quality_complete": not requires_validation,
        "requires_validation": requires_validation,
        "coverage_blockers": blockers,
        "coverage_summary": coverage_summary,
    }


def _deontic_proof_gate_soft_pass(
    *,
    coverage_requires_validation: bool,
    proof_gate: ProofGateResult,
) -> bool:
    """Allow acceptance when partial deontic coverage still proves core syntax."""

    if proof_gate.attempted_count <= 0:
        return False
    if proof_gate.valid_count <= 0:
        return False
    if proof_gate.compiles:
        return False
    if coverage_requires_validation:
        return True

    blocking_targets = _blocking_targets_from_proof_gate_details(proof_gate.details)
    if not blocking_targets:
        return False
    passed_targets = _passed_targets_from_proof_gate_details(proof_gate.details)
    if "fol" not in passed_targets:
        return False
    return blocking_targets.issubset(
        {
            "frame_logic",
            "deontic_cec",
            "deontic_fol",
            "deontic_temporal_fol",
        }
    )


def _blocking_targets_from_proof_gate_details(
    details: Sequence[Mapping[str, Any]],
) -> set[str]:
    targets: set[str] = set()
    for item in details:
        for key in (
            "blocking_failed_targets",
            "blocking_missing_targets",
            "failed_targets",
            "missing_targets",
        ):
            value = item.get(key)
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                continue
            for target in value:
                target_name = str(target or "").strip()
                if target_name:
                    targets.add(target_name)
    return targets


def _passed_targets_from_proof_gate_details(
    details: Sequence[Mapping[str, Any]],
) -> set[str]:
    targets: set[str] = set()
    for item in details:
        value = item.get("passed_targets")
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            continue
        for target in value:
            target_name = str(target or "").strip()
            if target_name:
                targets.add(target_name)
    return targets


def _decoded_text_from_capability_view(ir_document: LegalIRDocument) -> str:
    view = ir_document.views.get("deontic_parser_capability")
    if view is None:
        return ""
    records = view.payload.get("records", [])
    if isinstance(records, Sequence) and records and isinstance(records[0], Mapping):
        return str(records[0].get("decoded_text") or "")
    return ""


def _document_id_from_norms(norms: Sequence[Mapping[str, Any]], text: str) -> str:
    if norms and norms[0].get("source_id"):
        return str(norms[0]["source_id"])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"deontic:{digest}"


def _normalized_text_from_deontic_rows(
    rows: Sequence[Mapping[str, Any]],
    source_text: str,
) -> str:
    if not rows:
        return source_text
    head = rows[0]
    for key in ("text", "source_text", "support_text"):
        value = str(head.get(key) or "").strip()
        if value:
            return value
    return source_text


def _citation_from_norms(norms: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if not norms:
        return None
    citation = norms[0].get("canonical_citation")
    return str(citation) if citation else None


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rate(numerator: Any, denominator: Any) -> float:
    top = _float(numerator)
    bottom = _float(denominator)
    if bottom <= 0.0:
        return 0.0
    return max(0.0, min(1.0, top / bottom))


def _record_validation_rate(records: Sequence[Mapping[str, Any]]) -> float:
    if not records:
        return 0.0
    requires_validation = sum(
        1 for record in records if record.get("requires_validation") is True
    )
    return requires_validation / len(records)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    try:
        values = list(value)
    except TypeError:
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _normalized_target_names(value: Any) -> list[str]:
    names: list[str] = []
    for name in _list_of_strings(value):
        if name not in names:
            names.append(name)
    return names


__all__ = ["DeonticNormsBridgeAdapter"]
