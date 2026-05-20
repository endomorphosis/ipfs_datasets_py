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
        formula_records = _list_of_dicts(metadata.get("legal_formula_records"))
        coverage_records = _list_of_dicts(
            metadata.get("legal_prover_syntax_target_coverage_records")
        )
        capability_records = _list_of_dicts(
            metadata.get("legal_parser_capability_profile_records")
        )
        deontic_exports = _deontic_export_context_from_parser_elements(parser_elements)
        parser_metrics = _summarize_parser_metrics(parser_elements)
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
                metadata={"coverage_record_count": len(coverage_records)},
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
                normalized_text=str(parser_elements[0].get("text") or text) if parser_elements else text,
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
                    "parser_element_count": len(parser_elements),
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
        status = "ok"
        if not ir_document.views["deontic_ir"].metadata.get("norm_count"):
            status = "partial"
        if not proof_gate.compiles:
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


def _deontic_export_context_from_parser_elements(
    parser_elements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    context = _empty_deontic_export_context()
    norm_objects = _legal_norm_objects_from_parser_elements(parser_elements)
    context["norm_count"] = len(norm_objects)
    if not norm_objects:
        return context

    from ipfs_datasets_py.logic.deontic.exports import (
        build_decoder_records_from_irs,
        build_ir_slot_provenance_audit_records,
        build_phase8_quality_summary_records,
        build_proof_obligation_record_from_ir,
        build_prover_syntax_records_from_ir,
        build_reconstruction_slot_loss_records,
        build_repair_queue_record_from_ir,
        summarize_ir_slot_provenance_audit_records,
        summarize_phase8_quality_records,
        summarize_reconstruction_slot_loss,
    )

    try:
        decoder_records = build_decoder_records_from_irs(norm_objects)
        context["decoder_records"] = decoder_records
        context["reconstruction_slot_loss_records"] = (
            build_reconstruction_slot_loss_records(decoder_records)
        )
        context["reconstruction_slot_loss_summary"] = (
            summarize_reconstruction_slot_loss(decoder_records)
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "decoder_reconstruction", exc)
        decoder_records = []

    try:
        ir_slot_provenance_records = build_ir_slot_provenance_audit_records(norm_objects)
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
        proof_records = [
            build_proof_obligation_record_from_ir(norm)
            for norm in norm_objects
        ]
        context["proof_obligation_records"] = proof_records
        context["repair_queue_records"] = [
            build_repair_queue_record_from_ir(norm)
            for norm, proof_record in zip(norm_objects, proof_records)
            if proof_record.get("requires_validation") is True
        ]
    except Exception as exc:  # pragma: no cover - diagnostics only
        _record_export_context_error(context, "proof_and_repair_records", exc)

    try:
        phase8_records = build_phase8_quality_summary_records(
            decoder_records=decoder_records,
            prover_syntax_records=prover_syntax_records,
            ir_slot_provenance_records=ir_slot_provenance_records,
        )
        context["phase8_quality_records"] = phase8_records
        context["phase8_quality_summary"] = summarize_phase8_quality_records(
            decoder_records=decoder_records,
            prover_syntax_records=prover_syntax_records,
            ir_slot_provenance_records=ir_slot_provenance_records,
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
    quality_requires_validation_rate = _float(metrics.get("phase8_quality_requires_validation_rate"))
    norm_count = int(deontic_exports.get("norm_count") or 0)
    reconstruction_summary = _mapping(
        deontic_exports.get("reconstruction_slot_loss_summary")
    )
    provenance_summary = _mapping(deontic_exports.get("ir_slot_provenance_summary"))
    graph_metadata = _mapping(deontic_exports.get("deontic_graph_metadata"))
    phase8_quality_records = _list_of_dicts(deontic_exports.get("phase8_quality_records"))
    decoder_records = _list_of_dicts(deontic_exports.get("decoder_records"))
    repair_queue_records = _list_of_dicts(deontic_exports.get("repair_queue_records"))
    quality_incomplete_rate = _record_validation_rate(phase8_quality_records)
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
    soft_targets = {"frame_logic"}
    attempted_count = 0
    valid_count = 0
    failed_count = 0
    details = []
    verified_by = set()
    for record in records:
        summary = record.get("coverage_summary") or {}
        passed_targets = list(summary.get("passed_targets") or [])
        failed_targets = list(summary.get("failed_targets") or [])
        missing_targets = list(summary.get("missing_targets") or [])
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
                "requires_validation": bool(record.get("requires_validation")),
                "source_id": record.get("source_id"),
                "syntax_valid_rate": summary.get("syntax_valid_rate"),
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
    return any(bool(record.get("requires_validation")) for record in records)


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


__all__ = ["DeonticNormsBridgeAdapter"]
