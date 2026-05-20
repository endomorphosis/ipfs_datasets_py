"""CEC/DCEC implementation of the legal IR bridge contract."""

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
class CecDcecBridgeAdapter:
    """Bridge legal norm text into DCEC event-calculus records."""

    converter: Optional[Any] = None
    converter_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: {
            "enable_monitoring": False,
            "use_cache": True,
            "use_ml": False,
        }
    )

    name: str = "cec_dcec"
    target_component: str = "CEC.native"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        """Encode legal text into a DCEC bridge document."""

        norms = _deontic_norms_from_text(text, converter=self._converter())
        resolved_document_id = document_id or _document_id("dcec", text)
        records = _dcec_records(norms)
        triples = tuple(
            _dcec_frame_logic_triples(
                resolved_document_id,
                records=records,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:dcec-flogic",
            metadata={
                "dcec_formula_count": len(records),
                "source": "cec_dcec_bridge_ir",
            },
        )
        views = {
            "cec_events": LogicIRView(
                name="cec_events",
                format="cec-event-records",
                source_component="CEC.native",
                payload={
                    "events": [
                        {
                            "actor": record["actor"],
                            "event": record["event"],
                            "source_id": record["source_id"],
                        }
                        for record in records
                    ]
                },
                metadata={"event_count": len(records)},
            ),
            "dcec_formula": LogicIRView(
                name="dcec_formula",
                format="dcec-formula-records",
                source_component="CEC.native",
                payload={
                    "records": [
                        {
                            "formula": record["formula"],
                            "source_id": record["source_id"],
                            "valid": bool(record["valid"]),
                        }
                        for record in records
                    ]
                },
                metadata={"formula_count": len(records)},
            ),
            "proof_trace": LogicIRView(
                name="proof_trace",
                format="dcec-validation-trace",
                source_component="CEC.native",
                payload={
                    "records": [
                        {
                            "reason": record["validation_reason"],
                            "source_id": record["source_id"],
                            "valid": bool(record["valid"]),
                        }
                        for record in records
                    ]
                },
                metadata={"validated_count": sum(1 for record in records if record["valid"])},
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="CEC.native",
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
                normalized_text=" ".join(str(text or "").split()),
                source=source,
                citation=citation or _citation_from_norms(norms),
                views=views,
                frame_logic_triples=triples,
                metadata={
                    "dcec_formula_count": len(records),
                    "deontic_norm_count": len(norms),
                },
            ),
            {
                "graph_data": graph_data,
                "norms": norms,
                "records": records,
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
        """Run the CEC/DCEC bridge and return optimizer-visible diagnostics."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        records = list(context["records"])
        proof_gate = _proof_gate_from_dcec_records(records)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(records))
        failure_ratio = max(0.0, (attempted - proof_gate.valid_count) / attempted)
        no_formula_loss = 0.0 if records else 1.0
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - no_formula_loss),
            cosine_loss=no_formula_loss,
            symbolic_validity_penalty=failure_ratio,
            extra_losses={
                "cec_dcec_no_formula_loss": no_formula_loss,
                "cec_dcec_validation_failure_ratio": failure_ratio,
            },
        )
        status = "ok" if records and proof_gate.compiles else "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=" ".join(str(record.get("formula") or "") for record in records),
            status=status,
            metadata={"adapter": "cec_dcec_bridge_v1"},
        )

    def _converter(self) -> Any:
        if self.converter is not None:
            return self.converter
        from ipfs_datasets_py.logic.deontic import DeonticConverter

        self.converter = DeonticConverter(**dict(self.converter_kwargs))
        return self.converter


def _deontic_norms_from_text(text: str, *, converter: Any) -> list[dict[str, Any]]:
    result = converter.convert(text)
    metadata = dict(getattr(result, "metadata", {}) or {})
    return _list_of_dicts(metadata.get("legal_norm_irs"))


def _dcec_records(norms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, norm in enumerate(norms):
        actor = _symbol(norm.get("actor") or "actor")
        event = _symbol(norm.get("action") or norm.get("predicate") or "act")
        modality = _dcec_modality(norm)
        source_id = str(norm.get("source_id") or f"dcec:norm:{index}")
        formula_object = _native_dcec_event_formula(
            actor=actor,
            event=event,
            modality=modality,
        )
        formula = (
            str(formula_object.to_string())
            if formula_object is not None and hasattr(formula_object, "to_string")
            else f"{modality}({actor},{event},t0)"
        )
        valid, validation_reason = _compile_dcec_proof_input(formula_object)
        records.append(
            {
                "actor": actor,
                "event": event,
                "formula": formula,
                "formula_object": formula_object,
                "modality": modality,
                "source_id": source_id,
                "source_norm": dict(norm),
                "valid": valid,
                "validation_reason": validation_reason,
            }
        )
    return records


def _dcec_modality(norm: Mapping[str, Any]) -> str:
    modality = str(norm.get("modality") or norm.get("norm_type") or "").lower()
    if "prohib" in modality or "forbid" in modality:
        return "forbidden"
    if "permit" in modality or "may" in modality:
        return "permitted"
    return "obligated"


def _proof_gate_from_dcec_records(records: Sequence[Mapping[str, Any]]) -> ProofGateResult:
    attempted = len(records)
    valid = sum(1 for record in records if record.get("valid"))
    failed = attempted - valid
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        failed_count=failed,
        verified_by=("dcec:native_compile",) if valid else (),
        details=tuple(
            {
                "formula": record.get("formula"),
                "source_id": record.get("source_id"),
                "valid": bool(record.get("valid")),
                "validation_reason": record.get("validation_reason"),
            }
            for record in records
        ),
    )


def _dcec_frame_logic_triples(
    document_id: str,
    *,
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples = [
        {"subject": document_id, "predicate": "type", "object": "legal_dcec_document"}
    ]
    for record in records:
        source_id = str(record.get("source_id") or "")
        if not source_id:
            continue
        triples.extend(
            [
                {"subject": document_id, "predicate": "contains_event_formula", "object": source_id},
                {"subject": source_id, "predicate": "type", "object": "dcec_formula"},
                {"subject": source_id, "predicate": "actor", "object": str(record.get("actor") or "")},
                {"subject": source_id, "predicate": "event", "object": str(record.get("event") or "")},
                {"subject": source_id, "predicate": "formula", "object": str(record.get("formula") or "")},
                {"subject": source_id, "predicate": "modality", "object": str(record.get("modality") or "")},
                {"subject": source_id, "predicate": "valid", "object": str(bool(record.get("valid"))).lower()},
            ]
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


def _document_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _citation_from_norms(norms: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if not norms:
        return None
    citation = norms[0].get("canonical_citation")
    return str(citation) if citation else None


def _native_dcec_event_formula(*, actor: str, event: str, modality: str) -> Any:
    if not actor or not event:
        return None
    from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        AtomicFormula,
        DeonticFormula,
        DeonticOperator,
        Function,
        FunctionTerm,
        Predicate,
        Sort,
    )

    agent_sort = Sort("Agent")
    event_sort = Sort("Event")
    moment_sort = Sort("Moment")
    actor_term = FunctionTerm(Function(actor, [], agent_sort), [])
    event_term = FunctionTerm(Function(event, [], event_sort), [])
    moment_term = FunctionTerm(Function("t0", [], moment_sort), [])
    happens_predicate = Predicate(
        "happens",
        [agent_sort, event_sort, moment_sort],
    )
    happens_formula = AtomicFormula(
        happens_predicate,
        [actor_term, event_term, moment_term],
    )
    return DeonticFormula(
        _deontic_operator_for_modality(modality),
        happens_formula,
        agent=actor_term,
    )


def _deontic_operator_for_modality(modality: str) -> Any:
    from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticOperator

    normalized = str(modality or "").strip().lower()
    if normalized == "forbidden":
        return DeonticOperator.PROHIBITION
    if normalized == "permitted":
        return DeonticOperator.PERMISSION
    return DeonticOperator.OBLIGATION


def _compile_dcec_proof_input(formula: Any) -> tuple[bool, str]:
    if formula is None:
        return (False, "missing_actor_or_event_symbol")
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECContainer

        container = DCECContainer()
        container.add_statement(formula)
        return (True, "compiled_dcec_native_container")
    except Exception as exc:
        return (False, f"native_compile_error:{type(exc).__name__}")


def _symbol(value: Any) -> str:
    text = str(value or "").strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    return "_".join(part for part in "".join(chars).split("_") if part)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


__all__ = ["CecDcecBridgeAdapter"]
