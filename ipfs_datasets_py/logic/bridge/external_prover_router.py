"""External prover-router implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .fol_tdfol import FolTdfolBridgeAdapter
from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)


@dataclass
class ExternalProverRouterBridgeAdapter:
    """Bridge TDFOL formulas through the lazy external prover router."""

    tdfol_adapter: Optional[FolTdfolBridgeAdapter] = None
    enable_native: bool = True
    enable_external_binaries: bool = False

    name: str = "external_prover_router"
    target_component: str = "external_provers.router"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        """Encode text into router-ready TDFOL formulas and graph records."""

        adapter = self.tdfol_adapter or FolTdfolBridgeAdapter()
        _, context = adapter.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        records = list(context["formula_records"])
        formulas = [
            record.get("formula_object")
            for record in records
            if record.get("formula_object") is not None
        ]
        resolved_document_id = document_id or _document_id("external-prover", text)
        triples = tuple(
            _router_frame_logic_triples(
                resolved_document_id,
                records=records,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:external-prover-flogic",
            metadata={
                "router_formula_count": len(records),
                "source": "external_prover_router_bridge_ir",
            },
        )
        views = {
            "prover_formulas": LogicIRView(
                name="prover_formulas",
                format="tdfol-router-formula-records",
                source_component="external_provers.router",
                payload={
                    "records": [
                        {
                            "formula": record.get("formula"),
                            "source_id": record.get("source_id"),
                        }
                        for record in records
                    ]
                },
                metadata={"formula_count": len(records)},
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="external_provers.router",
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
                citation=citation,
                views=views,
                frame_logic_triples=triples,
                metadata={"router_formula_count": len(records)},
            ),
            {
                "formula_records": records,
                "formulas": formulas,
                "graph_data": graph_data,
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
        """Run router availability and native proof-gate checks."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        router = _build_router(
            enable_native=self.enable_native,
            enable_external_binaries=self.enable_external_binaries,
        )
        formulas = list(context["formulas"])
        proof_gate = _proof_gate_from_router(router, formulas)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(formulas))
        failure_ratio = max(0.0, (attempted - proof_gate.valid_count) / attempted)
        unavailable_loss = 0.0 if router.get_available_provers() else 1.0
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - unavailable_loss),
            cosine_loss=unavailable_loss,
            symbolic_validity_penalty=failure_ratio,
            extra_losses={
                "external_prover_failure_ratio": failure_ratio,
                "external_prover_unavailable_loss": unavailable_loss,
            },
        )
        status = "ok" if formulas and proof_gate.compiles else "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=" ".join(
                str(record.get("formula") or "")
                for record in context["formula_records"]
            ),
            status=status,
            metadata={
                "adapter": "external_prover_router_bridge_v1",
                "available_provers": router.get_available_provers(),
            },
        )


def _build_router(*, enable_native: bool, enable_external_binaries: bool) -> Any:
    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    return ProverRouter(
        enable_cache=False,
        enable_coq=enable_external_binaries,
        enable_cvc5=enable_external_binaries,
        enable_lean=enable_external_binaries,
        enable_native=enable_native,
        enable_symbolicai=enable_external_binaries,
        enable_z3=enable_external_binaries,
    )


def _proof_gate_from_router(router: Any, formulas: Sequence[Any]) -> ProofGateResult:
    available = list(router.get_available_provers())
    attempted = len(formulas)
    if not available:
        return ProofGateResult(
            attempted_count=attempted,
            unavailable_count=attempted,
            details=({"reason": "no_provers_available"},),
        )

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverStrategy

    valid = 0
    failed = 0
    unavailable = 0
    errors = 0
    details = []
    verified_by: set[str] = set()
    for index, formula in enumerate(formulas):
        if formula is None:
            failed += 1
            details.append(
                {
                    "available_provers": available,
                    "reason": "missing_formula_object",
                    "source_index": index,
                }
            )
            continue
        try:
            # Route via the canonical router API and provide the formula itself as
            # a temporary axiom to keep proof-gate checks focused on prover-path
            # viability rather than theorem strength.
            result = router.route(
                formula,
                axioms=[formula],
                strategy=ProverStrategy.SEQUENTIAL,
                timeout=1.0,
            )
        except RuntimeError as exc:
            unavailable += 1
            details.append(
                {
                    "available_provers": available,
                    "error": str(exc),
                    "formula": str(formula),
                    "reason": "router_unavailable",
                    "source_index": index,
                }
            )
            continue
        except Exception as exc:
            errors += 1
            details.append(
                {
                    "available_provers": available,
                    "error": str(exc),
                    "formula": str(formula),
                    "reason": "router_error",
                    "source_index": index,
                }
            )
            continue

        proved = bool(getattr(result, "is_proved", False))
        prover_used = str(getattr(result, "prover_used", "") or "")
        result_reason = str(getattr(result, "reason", "") or "")
        all_results = dict(getattr(result, "all_results", {}) or {})
        completed_provers = sorted(
            str(name)
            for name, prover_result in all_results.items()
            if not isinstance(prover_result, str)
        )
        compiled = bool(
            proved
            or (
                (prover_used or completed_provers)
                and not result_reason.lower().startswith("error:")
            )
        )
        valid += int(compiled)
        failed += int(not compiled)
        if compiled:
            if prover_used:
                verified_by.add(f"external_provers:{prover_used}")
            else:
                verified_by.update(
                    f"external_provers:{name}"
                    for name in completed_provers
                )
        details.append(
            {
                "available_provers": available,
                "compiled": compiled,
                "completed_provers": completed_provers,
                "formula": str(formula),
                "proof_time": float(getattr(result, "proof_time", 0.0) or 0.0),
                "proved": proved,
                "prover_used": prover_used,
                "reason": result_reason,
                "source_index": index,
                "strategy_used": str(getattr(result, "strategy_used", "") or ""),
            }
        )
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        unavailable_count=unavailable,
        error_count=errors,
        failed_count=failed,
        verified_by=tuple(sorted(verified_by)),
        details=tuple(details),
    )


def _router_frame_logic_triples(
    document_id: str,
    *,
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples = [
        {
            "subject": document_id,
            "predicate": "type",
            "object": "external_prover_router_document",
        }
    ]
    for record in records:
        source_id = str(record.get("source_id") or "")
        if not source_id:
            continue
        triples.extend(
            [
                {"subject": document_id, "predicate": "routes_formula", "object": source_id},
                {"subject": source_id, "predicate": "type", "object": "router_formula"},
                {"subject": source_id, "predicate": "formula", "object": str(record.get("formula") or "")},
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


__all__ = ["ExternalProverRouterBridgeAdapter"]
