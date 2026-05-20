"""External prover-router implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .fol_tdfol import FolTdfolBridgeAdapter, coerce_tdfol_formula
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
        formulas = _router_formulas_from_records(records)
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
                metadata={
                    "router_formula_count": len(records),
                    "router_resolved_formula_count": len(formulas),
                },
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
        attempted = max(1, int(proof_gate.attempted_count or len(formulas)))
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
        status = "ok" if proof_gate.compiles else "partial"
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
    if attempted <= 0:
        return ProofGateResult.disabled(reason="no_router_formulas_available")
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
            result = _route_formula_with_compat(
                router,
                formula,
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

        proved = _result_proved(result)
        prover_used = _result_text(result, "prover_used")
        result_reason = _result_text(result, "reason")
        all_results = _result_mapping(result, "all_results")
        completed_provers = sorted(
            str(name)
            for name, prover_result in all_results.items()
            if not isinstance(prover_result, str)
        )
        compiled = _result_compiled(
            result,
            proved=proved,
            prover_used=prover_used,
            completed_provers=completed_provers,
            reason=result_reason,
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
                "proof_time": _result_float(result, "proof_time"),
                "proved": proved,
                "prover_used": prover_used,
                "reason": result_reason,
                "source_index": index,
                "strategy_used": _result_text(result, "strategy_used"),
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


def _router_formulas_from_records(records: Sequence[Mapping[str, Any]]) -> list[Any]:
    formulas: list[Any] = []
    for record in records:
        formula_object = coerce_tdfol_formula(record.get("formula_object"))
        if formula_object is None:
            formula_object = coerce_tdfol_formula(record.get("formula"))
        if formula_object is not None:
            formulas.append(formula_object)
            continue
        raw_formula = str(record.get("formula") or "").strip()
        if raw_formula:
            # Keep a raw fallback for legacy routers that accept formula text.
            formulas.append(raw_formula)
    return formulas


def _route_formula_with_compat(
    router: Any,
    formula: Any,
    *,
    strategy: Any,
    timeout: float,
) -> Any:
    """Call a router using route/prove compatibility fallbacks."""

    attempts: list[Exception] = []
    strategy_text = str(getattr(strategy, "value", strategy) or "sequential")
    timeout_ms = max(1, int(float(timeout or 0.0) * 1000.0))
    for method_name in ("route", "prove"):
        method = getattr(router, method_name, None)
        if not callable(method):
            continue
        for kwargs in (
            {"strategy": strategy, "timeout": timeout},
            {"strategy": strategy_text, "timeout": timeout},
            {"strategy": strategy_text, "timeout_ms": timeout_ms},
            {"axioms": (), "strategy": strategy, "timeout": timeout},
            {"axioms": (), "strategy": strategy_text, "timeout": timeout},
            {"axioms": (), "strategy": strategy_text, "timeout_ms": timeout_ms},
            {"axioms": (), "timeout": timeout},
            {"timeout": timeout},
            {"timeout_ms": timeout_ms},
            {},
        ):
            try:
                return method(formula, **kwargs)
            except (TypeError, ValueError) as exc:
                attempts.append(exc)
                continue
            except Exception as exc:
                raise exc
    if attempts:
        raise attempts[-1]
    raise RuntimeError("router_missing_route_and_prove")


def _result_compiled(
    result: Any,
    *,
    proved: bool,
    prover_used: str,
    completed_provers: Sequence[str],
    reason: str,
) -> bool:
    if proved:
        return True
    if str(reason or "").strip().lower().startswith("error:"):
        return False
    if prover_used or completed_provers:
        return True
    if result is None:
        return False
    # Legacy routers may return booleans/dicts without explicit prover metadata.
    return not isinstance(result, Exception)


def _result_mapping(result: Any, key: str) -> dict[str, Any]:
    value = _result_value(result, key, {})
    if not isinstance(value, Mapping):
        return {}
    return {str(name): item for name, item in value.items()}


def _result_text(result: Any, key: str) -> str:
    value = _result_value(result, key, "")
    return str(value or "")


def _result_float(result: Any, key: str) -> float:
    value = _result_value(result, key, 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _result_proved(result: Any) -> bool:
    if isinstance(result, bool):
        return result
    value = _result_value(result, "is_proved", False)
    if callable(value):
        try:
            return bool(value())
        except Exception:
            return False
    if value not in (None, ""):
        return bool(value)
    value = _result_value(result, "is_valid", False)
    if callable(value):
        try:
            return bool(value())
        except Exception:
            return False
    return bool(value)


def _result_value(result: Any, key: str, default: Any) -> Any:
    if isinstance(result, Mapping):
        return result.get(key, default)
    return getattr(result, key, default)


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
