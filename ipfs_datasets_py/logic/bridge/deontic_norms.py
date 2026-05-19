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
        round_trip = _round_trip_from_parser_metrics(context["parser_metrics"])
        status = "ok"
        if not ir_document.views["deontic_ir"].metadata.get("norm_count"):
            status = "partial"
        if _coverage_requires_validation(context["coverage_records"]):
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
                "coverage_requires_validation": _coverage_requires_validation(
                    context["coverage_records"]
                ),
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


def _round_trip_from_parser_metrics(metrics: Mapping[str, Any]) -> RoundTripMetrics:
    grounded_phrase_rate = _float(metrics.get("phase8_decoder_grounded_phrase_rate"))
    grounded_slot_rate = _float(metrics.get("phase8_parser_capability_decoder_grounding_rate"))
    if grounded_phrase_rate <= 0.0:
        grounded_phrase_rate = grounded_slot_rate
    syntax_valid_rate = _float(metrics.get("phase8_prover_syntax_valid_rate"))
    quality_requires_validation_rate = _float(metrics.get("phase8_quality_requires_validation_rate"))
    return RoundTripMetrics(
        cosine_similarity=grounded_phrase_rate,
        cosine_loss=max(0.0, 1.0 - grounded_phrase_rate),
        cross_entropy_loss=0.0,
        reconstruction_loss=max(0.0, 1.0 - grounded_slot_rate),
        text_reconstruction_loss=max(0.0, 1.0 - grounded_phrase_rate),
        symbolic_validity_penalty=max(0.0, 1.0 - syntax_valid_rate),
        extra_losses={
            "deontic_quality_requires_validation_loss": quality_requires_validation_rate,
            "deontic_repair_required_rate": _float(metrics.get("repair_required_rate")),
        },
    )


def _proof_gate_from_coverage_records(records: Sequence[Mapping[str, Any]]) -> ProofGateResult:
    attempted_count = 0
    valid_count = 0
    failed_count = 0
    details = []
    verified_by = set()
    for record in records:
        summary = record.get("coverage_summary") or {}
        record_count = int(summary.get("record_count") or record.get("record_count") or 0)
        passed_targets = list(summary.get("passed_targets") or [])
        failed_targets = list(summary.get("failed_targets") or [])
        missing_targets = list(summary.get("missing_targets") or [])
        attempted_count += record_count
        valid_count += len(passed_targets)
        failed_count += len(failed_targets) + len(missing_targets)
        verified_by.update(f"deontic:{target}" for target in passed_targets)
        details.append(
            {
                "coverage_blockers": list(record.get("coverage_blockers") or []),
                "passed_targets": passed_targets,
                "failed_targets": failed_targets,
                "missing_targets": missing_targets,
                "requires_validation": bool(record.get("requires_validation")),
                "source_id": record.get("source_id"),
                "syntax_valid_rate": summary.get("syntax_valid_rate"),
            }
        )
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


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["DeonticNormsBridgeAdapter"]
