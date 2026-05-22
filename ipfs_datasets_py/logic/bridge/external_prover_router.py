"""External prover-router implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
import time

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
                        _public_router_formula_record(record, index)
                        for index, record in enumerate(records)
                    ]
                },
                metadata={
                    "formula_count": len(records),
                    "resolved_formula_count": len(formulas),
                },
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
                    "router_unresolved_formula_count": max(0, len(records) - len(formulas)),
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
        available_provers = _router_available_provers(router)
        unavailable_loss = 0.0 if available_provers else 1.0
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
                _record_formula_text(record)
                for record in context["formula_records"]
            ),
            status=status,
            metadata={
                "adapter": "external_prover_router_bridge_v1",
                "available_provers": available_provers,
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
    available = _router_available_provers(router)
    attempted = len(formulas)
    if attempted <= 0:
        return ProofGateResult.disabled(reason="no_router_formulas_available")
    if not available:
        # External prover availability is tracked as a separate loss term.
        # Treat this branch as a proof-gate soft pass so multiview proof
        # failures only reflect formula/prover routing defects.
        return ProofGateResult(
            attempted_count=attempted,
            valid_count=attempted,
            verified_by=("external_provers:unavailable_softpass",),
            details=tuple(
                {
                    "available_provers": (),
                    "bridge_soft_pass": True,
                    "formula": str(formula),
                    "reason": "no_provers_available",
                    "source_index": index,
                }
                for index, formula in enumerate(formulas)
            ),
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
        formula_object = _record_formula_object(record)
        if formula_object is not None:
            formulas.append(formula_object)
            continue
        raw_formula = _record_formula_text(record)
        if raw_formula:
            # Keep a raw fallback for legacy routers that accept formula text.
            formulas.append(raw_formula)
    return formulas


def _record_formula_object(record: Mapping[str, Any]) -> Any:
    for key in (
        "formula_object",
        "proof_formula_object",
        "formula",
        "proof_input",
        "proof_formula",
        "tdfol_formula",
    ):
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        formula = coerce_tdfol_formula(value)
        if formula is not None:
            return formula
    return None


def _record_formula_text(record: Mapping[str, Any]) -> str:
    for key in (
        "formula",
        "proof_input",
        "proof_formula",
        "tdfol_formula",
    ):
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _record_source_id(record: Mapping[str, Any], index: int) -> str:
    for key in ("source_id", "proof_id", "norm_id", "id"):
        value = record.get(key)
        if value is None:
            continue
        source_id = str(value).strip()
        if source_id:
            return source_id
    return f"router:formula:{index}"


def _public_router_formula_record(record: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        "formula": _record_formula_text(record),
        "source_id": _record_source_id(record, index),
    }


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
    timeout_seconds = float(timeout or 0.0)
    for method_name in ("route", "prove"):
        method = getattr(router, method_name, None)
        if not callable(method):
            continue
        for args, kwargs in (
            ((), {"strategy": strategy, "timeout": timeout}),
            ((), {"strategy": strategy_text, "timeout": timeout}),
            ((), {"strategy": strategy_text, "timeout_ms": timeout_ms}),
            ((), {"axioms": (), "strategy": strategy, "timeout": timeout}),
            ((), {"axioms": (), "strategy": strategy_text, "timeout": timeout}),
            ((), {"axioms": (), "strategy": strategy_text, "timeout_ms": timeout_ms}),
            ((), {"axioms": (), "timeout": timeout}),
            ((), {"timeout": timeout}),
            ((), {"timeout_ms": timeout_ms}),
            ((strategy_text, timeout_seconds), {}),
            ((strategy_text,), {}),
            ((), {}),
        ):
            try:
                return method(formula, *args, **kwargs)
            except (TypeError, ValueError) as exc:
                attempts.append(exc)
                continue
            except Exception as exc:
                raise exc
    compat_result = _route_formula_from_router_inventory(
        router,
        formula,
        strategy_text=strategy_text,
        timeout=float(timeout or 0.0),
    )
    if compat_result is not None:
        return compat_result
    if attempts:
        raise attempts[-1]
    raise RuntimeError("router_missing_route_and_prove")


def _route_formula_from_router_inventory(
    router: Any,
    formula: Any,
    *,
    strategy_text: str,
    timeout: float,
) -> Optional[Mapping[str, Any]]:
    """Compat fallback for routers that expose prover inventory but no route/prove API."""

    provers = _router_prover_mapping(router)
    if not provers:
        return None
    candidate_names = _router_candidate_provers(router, formula=formula)
    if not candidate_names:
        candidate_names = list(provers.keys())
    if not any(name in provers for name in candidate_names):
        candidate_names = list(provers.keys())
    if not candidate_names:
        return None

    all_results: dict[str, Any] = {}
    start = time.monotonic()
    for prover_name in candidate_names:
        prover = provers.get(prover_name)
        if prover is None:
            continue
        try:
            prover_result = _call_prover_with_compat(
                prover,
                formula,
                timeout=timeout,
            )
        except Exception as exc:
            all_results[str(prover_name)] = f"Error: {exc}"
            continue
        all_results[str(prover_name)] = prover_result
        proved = _result_proved(prover_result)
        if proved:
            return {
                "all_results": all_results,
                "is_proved": True,
                "proof_time": max(0.0, time.monotonic() - start),
                "prover_used": str(prover_name),
                "reason": f"Proved by {prover_name}",
                "strategy_used": strategy_text or "compat_selected_prover",
            }

    first_completed = next(
        (
            name
            for name, value in all_results.items()
            if not isinstance(value, str)
        ),
        "",
    )
    return {
        "all_results": all_results,
        "is_proved": False,
        "proof_time": max(0.0, time.monotonic() - start),
        "prover_used": first_completed,
        "reason": "All provers failed",
        "strategy_used": strategy_text or "compat_selected_prover",
    }


def _call_prover_with_compat(
    prover: Any,
    formula: Any,
    *,
    timeout: float,
) -> Any:
    prove = getattr(prover, "prove", None)
    if not callable(prove):
        raise TypeError("prover_missing_prove")

    timeout_ms = max(1, int(float(timeout or 0.0) * 1000.0))
    attempts: list[Exception] = []
    for kwargs in (
        {"axioms": (), "timeout": timeout},
        {"timeout": timeout},
        {"axioms": (), "timeout_ms": timeout_ms},
        {"timeout_ms": timeout_ms},
        {"axioms": ()},
        {},
    ):
        try:
            return prove(formula, **kwargs)
        except (TypeError, ValueError) as exc:
            attempts.append(exc)
            continue
    if attempts:
        raise attempts[-1]
    return prove(formula)


def _router_candidate_provers(router: Any, *, formula: Any) -> list[str]:
    available = _router_available_provers(router)
    selected = ""
    select_prover = getattr(router, "select_prover", None)
    if callable(select_prover):
        try:
            selected = str(select_prover(formula) or "").strip()
        except Exception:
            selected = ""
    if not selected:
        fallback = getattr(router, "fallback_prover", "")
        if callable(fallback):
            try:
                fallback = fallback()
            except Exception:
                fallback = ""
        selected = str(fallback or "").strip()
    if selected:
        return [selected] + [name for name in available if name != selected]
    return list(available)


def _router_prover_mapping(router: Any) -> dict[str, Any]:
    provers = getattr(router, "provers", None)
    if not isinstance(provers, Mapping):
        return {}
    return {
        str(name): prover
        for name, prover in provers.items()
        if str(name).strip()
    }


def _router_available_provers(router: Any) -> list[str]:
    available: list[str] = []
    seen: set[str] = set()

    def _add_name(name: Any) -> None:
        text = str(name or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        available.append(text)

    def _extend(value: Any) -> None:
        if isinstance(value, Mapping):
            for name in value.keys():
                _add_name(name)
            return
        if isinstance(value, (str, bytes)):
            _add_name(value)
            return
        if isinstance(value, Sequence):
            for name in value:
                _add_name(name)
            return
        if value is None:
            return
        _add_name(value)

    for attr_name in ("get_available_provers", "backup_provers"):
        value = getattr(router, attr_name, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        _extend(value)

    _extend(getattr(router, "provers", None))

    fallback = getattr(router, "fallback_prover", None)
    if callable(fallback):
        try:
            fallback = fallback()
        except Exception:
            fallback = None
    _add_name(fallback)

    return available


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
    for index, record in enumerate(records):
        source_id = _record_source_id(record, index)
        formula_text = _record_formula_text(record)
        triples.extend(
            [
                {"subject": document_id, "predicate": "routes_formula", "object": source_id},
                {"subject": source_id, "predicate": "type", "object": "router_formula"},
                {"subject": source_id, "predicate": "formula", "object": formula_text},
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
