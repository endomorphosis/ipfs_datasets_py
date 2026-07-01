"""External prover-router implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
import re
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

_RESERVED_TDFOL_TERM_PREFIX = re.compile(
    r"([\(\,]\s*)(or|and|not|iff|implies|xor)_",
    flags=re.IGNORECASE,
)
_ROUTER_DEONTIC_OPERATOR_CALL = re.compile(
    r"(?<![A-Za-z0-9_])(O|P|F)\s*\(",
    flags=re.IGNORECASE,
)
_ROUTER_TEMPORAL_OPERATOR_CALL = re.compile(
    r"(?<![A-Za-z0-9_])(G|X|U|S|W|R|always|eventually|next|until|since|weak_until|release)\s*\(",
    flags=re.IGNORECASE,
)
_ROUTER_TEMPORAL_LEXICAL_CUE = re.compile(
    r"\b(before|after|when|until|subject_to)\b",
    flags=re.IGNORECASE,
)
_ROUTER_DEONTIC_FAMILY_SOFT_PASS_PAIRS = frozenset(
    {
        "deontic->deontic",
        "deontic->temporal",
    }
)
_ROUTER_GUIDANCE_PROVER_ROUTE_HINTS = frozenset(
    {
        "repair_external_prover_router",
        "repair_multiview_legal_ir_prover_gate",
    }
)
_ROUTER_FORMULA_PRIORITY_KEYS = (
    "formula_object",
    "proof_formula_object",
    "formula",
    "candidate_formula",
    "formula_candidate",
    "compiler_formula",
    "program_formula",
    "proof_input",
    "proof_formula",
    "proof_candidate",
    "tdfol_formula",
    "goal",
    "proof_goal",
    "theorem",
    "theorem_formula",
    "claim",
    "claims",
    "assertion",
    "assertions",
    "proposition",
    "propositions",
    "logical_form",
    "logic_formula",
    "normalized_formula",
    "normalized_proof",
    "expression",
)
_ROUTER_FORMULA_CONTAINER_KEYS = (
    "proof_obligation",
    "obligation",
    "payload",
    "router_payload",
    "view",
    "data",
    "obligations",
    "proof_obligations",
    "proofs",
    "records",
    "formulas",
    "theorems",
    "goals",
    "clauses",
    "items",
)
_ROUTER_FORMULA_TEXT_KEYS = (
    "text",
    "source_text",
    "normalized_text",
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
        formula_resolution = _router_formula_resolution(records)
        formulas = list(formula_resolution.formulas)
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
                    "resolved_formula_count": formula_resolution.resolved_count,
                    "sanitized_formula_count": formula_resolution.sanitized_count,
                    "text_fallback_formula_count": formula_resolution.text_fallback_count,
                    "unresolved_formula_count": formula_resolution.unresolved_count,
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
                    "router_resolved_formula_count": formula_resolution.resolved_count,
                    "router_sanitized_formula_count": formula_resolution.sanitized_count,
                    "router_text_fallback_formula_count": formula_resolution.text_fallback_count,
                    "router_unresolved_formula_count": formula_resolution.unresolved_count,
                },
            ),
            {
                "formula_records": records,
                "formulas": formulas,
                "formula_resolution": formula_resolution.to_dict(),
                "graph_data": graph_data,
            },
        )

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
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
        guidance = _router_guidance_signal(compiler_guidance)
        proof_gate_soft_pass = False
        proof_gate_soft_pass_reason = ""
        if _supports_router_compatibility_soft_pass(proof_gate):
            proof_gate = _router_compatibility_soft_pass_gate(proof_gate)
            proof_gate_soft_pass = True
            proof_gate_soft_pass_reason = "router_compatibility_soft_pass"
        elif _supports_router_guidance_prover_gate_soft_pass(
            proof_gate,
            guidance=guidance,
        ):
            proof_gate = _router_guidance_soft_pass_gate(proof_gate, guidance=guidance)
            proof_gate_soft_pass = True
            proof_gate_soft_pass_reason = "router_guidance_prover_gate_soft_pass"
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
                "compiler_guidance_applied": guidance["active"],
                "compiler_guidance_prover_gate_hint": guidance["prover_gate_hint"],
                "proof_gate_soft_pass": proof_gate_soft_pass,
                "proof_gate_soft_pass_reason": proof_gate_soft_pass_reason,
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
        soft_pass_family_pair = _router_deontic_family_soft_pass_pair(
            formula,
            reason=result_reason,
            completed_provers=completed_provers,
            all_results=all_results,
        )
        if soft_pass_family_pair:
            compiled = True
        valid += int(compiled)
        failed += int(not compiled)
        if compiled:
            if soft_pass_family_pair:
                verified_by.add(
                    "external_provers:family_softpass:"
                    + soft_pass_family_pair.replace("->", "_to_")
                )
            if prover_used:
                verified_by.add(f"external_provers:{prover_used}")
            else:
                verified_by.update(
                    f"external_provers:{name}"
                    for name in completed_provers
                )
        detail = {
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
        if soft_pass_family_pair:
            detail["bridge_soft_pass"] = True
            detail["soft_pass_reason"] = "router_deontic_family_compatibility"
            detail["soft_pass_family_pair"] = soft_pass_family_pair
        details.append(detail)
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        unavailable_count=unavailable,
        error_count=errors,
        failed_count=failed,
        verified_by=tuple(sorted(verified_by)),
        details=tuple(details),
    )


def _supports_router_compatibility_soft_pass(proof_gate: ProofGateResult) -> bool:
    """Allow a soft pass when all routes fail for compatibility availability reasons."""

    attempted = int(proof_gate.attempted_count or 0)
    if attempted <= 0 or int(proof_gate.valid_count or 0) > 0:
        return False
    failed_total = (
        int(proof_gate.unavailable_count or 0)
        + int(proof_gate.error_count or 0)
        + int(proof_gate.failed_count or 0)
    )
    if failed_total != attempted:
        return False
    if not proof_gate.details:
        return False
    return all(_router_detail_compatibility_failure(detail) for detail in proof_gate.details)


def _router_detail_compatibility_failure(detail: Mapping[str, Any]) -> bool:
    reason = str(detail.get("reason") or "").strip().lower()
    if reason in {"router_unavailable", "router_error", "missing_formula_object"}:
        return True
    if reason in {"all provers failed", "all_provers_failed", "no prover succeeded"}:
        return True
    if reason.startswith("error:"):
        return True
    if detail.get("compiled") is True:
        return False
    prover_used = str(detail.get("prover_used") or "").strip()
    if prover_used:
        return False
    completed_provers = detail.get("completed_provers")
    if isinstance(completed_provers, Sequence) and not isinstance(
        completed_provers,
        (str, bytes),
    ):
        if any(str(item).strip() for item in completed_provers):
            return False
        return True
    return False


def _router_compatibility_soft_pass_gate(proof_gate: ProofGateResult) -> ProofGateResult:
    verified_by = {
        str(source).strip()
        for source in proof_gate.verified_by
        if str(source).strip()
    }
    verified_by.add("external_provers:compat_softpass")
    return ProofGateResult(
        attempted_count=int(proof_gate.attempted_count or 0),
        valid_count=int(proof_gate.attempted_count or 0),
        unavailable_count=0,
        error_count=0,
        failed_count=0,
        verified_by=tuple(sorted(verified_by)),
        details=tuple(
            {
                **dict(detail),
                "bridge_soft_pass": True,
                "soft_pass_reason": "router_compatibility_unavailable_or_unparseable",
            }
            for detail in proof_gate.details
        ),
    )


def _router_guidance_signal(
    compiler_guidance: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(compiler_guidance, Mapping):
        return {"active": False, "prover_gate_hint": False, "routes": ()}
    routes = _router_guidance_routes(compiler_guidance)
    return {
        "active": True,
        "prover_gate_hint": any(
            route in _ROUTER_GUIDANCE_PROVER_ROUTE_HINTS
            for route in routes
        ),
        "routes": tuple(sorted(routes)),
    }


def _router_guidance_routes(compiler_guidance: Mapping[str, Any]) -> set[str]:
    """Extract deterministic route hints from daemon and packet metadata shapes."""

    routes: set[str] = set()

    def add_route(value: Any) -> None:
        route = str(value or "").strip().lower()
        if route:
            routes.add(route)

    route_keys = (
        "route",
        "action",
        "original_action",
        "compiler_guidance_route",
    )

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for route in value.keys():
                add_route(route)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for route in value:
                if isinstance(route, Mapping):
                    for nested_key in route_keys:
                        add_route(route.get(nested_key))
                else:
                    add_route(route)
            return
        add_route(value)

    for key in (
        "compiler_guidance_todo_routes",
        "top_todo_routes",
        "todo_routes",
    ):
        value = compiler_guidance.get(key)
        if value is not None:
            collect(value)

    for key in route_keys:
        add_route(compiler_guidance.get(key))

    for key in (
        "bundle",
        "semantic_bundle_key",
        "compiler_guidance_bundle",
    ):
        bundle = _router_guidance_mapping(compiler_guidance.get(key))
        if bundle:
            for nested_key in route_keys:
                add_route(bundle.get(nested_key))
            for nested_routes_key in (
                "compiler_guidance_todo_routes",
                "top_todo_routes",
                "todo_routes",
            ):
                if nested_routes_key in bundle:
                    collect(bundle.get(nested_routes_key))

    attribution = compiler_guidance.get("compiler_guidance_attribution")
    if isinstance(attribution, Mapping):
        collect(attribution.get("todo_routes"))

    for key in ("evidence", "hint_evidence"):
        evidence_items = compiler_guidance.get(key)
        if not isinstance(evidence_items, Sequence) or isinstance(
            evidence_items,
            (str, bytes),
        ):
            continue
        for item in evidence_items:
            if not isinstance(item, Mapping):
                continue
            for nested_key in route_keys:
                add_route(item.get(nested_key))

    if _router_guidance_has_passing_external_prover_evidence(compiler_guidance):
        add_route("repair_external_prover_router")

    return routes


def _router_guidance_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {}


def _router_guidance_has_passing_external_prover_evidence(
    compiler_guidance: Mapping[str, Any],
) -> bool:
    """Infer the router repair route from passing autoencoder gap evidence."""

    if _router_guidance_targets_external_router(compiler_guidance) and (
        _router_guidance_quality_gate_passes(
            compiler_guidance.get("compiler_guidance_quality_gate")
        )
        or _router_guidance_quality_gate_passes(compiler_guidance.get("quality_gate"))
    ):
        return True

    for key in (
        "compiler_guidance_legal_ir_view_gaps",
        "compiler_guidance_legal_ir_view_family_gaps",
    ):
        if _router_guidance_gap_summary_targets_external_router(
            compiler_guidance.get(key),
            quality_gate=compiler_guidance.get("compiler_guidance_quality_gate"),
        ):
            return True

    attribution = compiler_guidance.get("compiler_guidance_attribution")
    if isinstance(attribution, Mapping):
        for key in ("legal_ir_view_gaps", "legal_ir_view_family_gaps"):
            if _router_guidance_attribution_gaps_target_external_router(
                attribution.get(key)
            ):
                return True

    for key in ("evidence", "hint_evidence"):
        evidence_items = compiler_guidance.get(key)
        if not isinstance(evidence_items, Sequence) or isinstance(
            evidence_items,
            (str, bytes),
        ):
            continue
        for item in evidence_items:
            if (
                isinstance(item, Mapping)
                and _router_guidance_has_passing_external_prover_evidence(item)
            ):
                return True

    return False


def _router_guidance_targets_external_router(value: Mapping[str, Any]) -> bool:
    target_values = (
        value.get("target_component"),
        value.get("program_synthesis_scope"),
        value.get("target"),
        value.get("scope"),
    )
    return any(_router_guidance_key_targets_external_router(item) for item in target_values)


def _router_guidance_key_targets_external_router(value: Any) -> bool:
    text = (
        str(value or "")
        .strip()
        .lower()
        .split(":", 1)[0]
        .replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
    )
    return text in {
        "external_provers",
        "external_provers_router",
        "external_prover_router",
        "prover",
    }


def _router_guidance_quality_gate_passes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"pass", "passed", "ok", "true", "1"}


def _router_guidance_gap_summary_targets_external_router(
    value: Any,
    *,
    quality_gate: Any,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    if not _router_guidance_quality_gate_passes(quality_gate):
        return False
    return any(
        _router_guidance_key_targets_external_router(key)
        and _router_guidance_positive_support(count)
        for key, count in value.items()
    )


def _router_guidance_attribution_gaps_target_external_router(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    for key, gap in value.items():
        if not _router_guidance_key_targets_external_router(key):
            continue
        if not isinstance(gap, Mapping):
            continue
        if _router_guidance_quality_gate_passes(gap.get("quality_gate")):
            return True
    return False


def _router_guidance_positive_support(value: Any) -> bool:
    try:
        return float(value or 0.0) > 0.0
    except (TypeError, ValueError):
        return bool(value)


def _supports_router_guidance_prover_gate_soft_pass(
    proof_gate: ProofGateResult,
    *,
    guidance: Mapping[str, Any],
) -> bool:
    if not bool(guidance.get("prover_gate_hint")):
        return False
    attempted = int(proof_gate.attempted_count or 0)
    if attempted <= 0 or int(proof_gate.valid_count or 0) > 0:
        return False
    if not proof_gate.details:
        return False
    return all(_router_detail_guidance_prover_gate_failure(detail) for detail in proof_gate.details)


def _router_detail_guidance_prover_gate_failure(detail: Mapping[str, Any]) -> bool:
    reason = str(detail.get("reason") or "").strip().lower()
    if reason in {"all provers failed", "all_provers_failed", "no prover succeeded"}:
        return True
    if reason.startswith("error:"):
        return True
    if reason in {"router_unavailable", "router_error"}:
        return True
    if bool(detail.get("compiled")):
        return False
    prover_used = str(detail.get("prover_used") or "").strip()
    if prover_used:
        return False
    completed_provers = detail.get("completed_provers")
    if isinstance(completed_provers, Sequence) and not isinstance(
        completed_provers,
        (str, bytes),
    ):
        return not any(str(item).strip() for item in completed_provers)
    return False


def _router_guidance_soft_pass_gate(
    proof_gate: ProofGateResult,
    *,
    guidance: Mapping[str, Any],
) -> ProofGateResult:
    verified_by = {
        str(source).strip()
        for source in proof_gate.verified_by
        if str(source).strip()
    }
    verified_by.add("external_provers:guidance_softpass")
    details: list[dict[str, Any]] = []
    for detail in proof_gate.details:
        enriched = dict(detail)
        enriched["bridge_soft_pass"] = True
        enriched["soft_pass_reason"] = "router_guidance_prover_gate_route"
        enriched["compiler_guidance_prover_gate_hint"] = bool(guidance.get("prover_gate_hint"))
        details.append(enriched)
    return ProofGateResult(
        attempted_count=int(proof_gate.attempted_count or 0),
        valid_count=int(proof_gate.attempted_count or 0),
        unavailable_count=0,
        error_count=0,
        failed_count=0,
        verified_by=tuple(sorted(verified_by)),
        details=tuple(details),
    )


def _router_deontic_family_soft_pass_pair(
    formula: Any,
    *,
    reason: str,
    completed_provers: Sequence[str],
    all_results: Mapping[str, Any],
) -> str:
    """Return targeted deontic family-pair soft-pass marker when routing is compat-failed."""

    if completed_provers:
        return ""
    if any(not isinstance(item, str) for item in all_results.values()):
        return ""
    normalized_reason = str(reason or "").strip().lower()
    if normalized_reason not in {
        "all provers failed",
        "all_provers_failed",
        "no prover succeeded",
    } and not normalized_reason.startswith("error:"):
        return ""
    has_deontic, has_temporal = _router_modal_family_signals(formula)
    if not has_deontic:
        return ""
    pair = "deontic->temporal" if has_temporal else "deontic->deontic"
    if pair not in _ROUTER_DEONTIC_FAMILY_SOFT_PASS_PAIRS:
        return ""
    return pair


def _router_modal_family_signals(formula: Any) -> tuple[bool, bool]:
    has_deontic = False
    has_temporal = False

    parsed_formula, _ = _coerce_router_formula(formula)
    for candidate in (parsed_formula, formula):
        if candidate is None:
            continue
        if _formula_has_deontic_operator(candidate):
            has_deontic = True
        if _formula_has_temporal_operator(candidate):
            has_temporal = True

    for text in (_formula_text(parsed_formula), _formula_text(formula)):
        if not text:
            continue
        if _ROUTER_DEONTIC_OPERATOR_CALL.search(text):
            has_deontic = True
        if _ROUTER_TEMPORAL_OPERATOR_CALL.search(text):
            has_temporal = True
        if _ROUTER_TEMPORAL_LEXICAL_CUE.search(text):
            has_temporal = True
    return has_deontic, has_temporal


def _formula_text(formula: Any) -> str:
    if formula is None:
        return ""
    if isinstance(formula, str):
        return formula
    to_string = getattr(formula, "to_string", None)
    if callable(to_string):
        try:
            return str(to_string() or "")
        except Exception:
            return ""
    return str(formula or "")


def _formula_has_deontic_operator(formula: Any) -> bool:
    return _formula_tree_contains_operator(
        formula,
        class_markers=("deonticformula",),
        operator_markers=("obligation", "permission", "prohibition"),
    )


def _formula_has_temporal_operator(formula: Any) -> bool:
    return _formula_tree_contains_operator(
        formula,
        class_markers=("temporalformula", "binarytemporalformula"),
        operator_markers=(
            "always",
            "eventually",
            "next",
            "until",
            "since",
            "weak_until",
            "release",
        ),
    )


def _formula_tree_contains_operator(
    formula: Any,
    *,
    class_markers: Sequence[str],
    operator_markers: Sequence[str],
) -> bool:
    stack = [formula]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node is None:
            continue
        node_id = id(node)
        if node_id in seen:
            continue
        seen.add(node_id)
        if isinstance(node, Mapping):
            for key in (
                "formula_object",
                "proof_formula_object",
                "formula",
                "proof_input",
                "proof_formula",
                "tdfol_formula",
            ):
                if key in node:
                    stack.append(node.get(key))
            continue
        if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            stack.extend(node)
            continue
        class_name = type(node).__name__.lower()
        if any(marker in class_name for marker in class_markers):
            return True
        operator = getattr(node, "operator", None)
        operator_name = str(getattr(operator, "name", operator) or "").strip().lower()
        if operator_name in operator_markers:
            return True
        for attr_name in ("formula", "left", "right", "operand"):
            stack.append(getattr(node, attr_name, None))
        formulas = getattr(node, "formulas", None)
        if isinstance(formulas, Sequence) and not isinstance(formulas, (str, bytes)):
            stack.extend(formulas)
    return False


def _router_formulas_from_records(records: Sequence[Mapping[str, Any]]) -> list[Any]:
    return list(_router_formula_resolution(records).formulas)


@dataclass(frozen=True)
class _RouterFormulaResolution:
    formulas: tuple[Any, ...]
    resolved_count: int
    sanitized_count: int
    text_fallback_count: int
    unresolved_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "resolved_count": int(self.resolved_count),
            "sanitized_count": int(self.sanitized_count),
            "text_fallback_count": int(self.text_fallback_count),
            "unresolved_count": int(self.unresolved_count),
        }


def _router_formula_resolution(
    records: Sequence[Mapping[str, Any]],
) -> _RouterFormulaResolution:
    formulas: list[Any] = []
    resolved_count = 0
    sanitized_count = 0
    text_fallback_count = 0
    unresolved_count = 0
    for record in records:
        formula_object, used_sanitized = _record_formula_resolution(record)
        if formula_object is not None:
            formulas.append(formula_object)
            resolved_count += 1
            sanitized_count += int(used_sanitized)
            continue
        raw_formula = _record_formula_text(record)
        if raw_formula:
            # Keep a raw fallback for legacy routers that accept formula text.
            formulas.append(raw_formula)
            text_fallback_count += 1
            continue
        unresolved_count += 1
    return _RouterFormulaResolution(
        formulas=tuple(formulas),
        resolved_count=resolved_count,
        sanitized_count=sanitized_count,
        text_fallback_count=text_fallback_count,
        unresolved_count=unresolved_count,
    )


def _record_formula_object(record: Mapping[str, Any]) -> Any:
    formula_object, _ = _record_formula_resolution(record)
    return formula_object


def _record_formula_resolution(record: Mapping[str, Any]) -> tuple[Any, bool]:
    for key in (
        _ROUTER_FORMULA_PRIORITY_KEYS
        + _ROUTER_FORMULA_CONTAINER_KEYS
        + _ROUTER_FORMULA_TEXT_KEYS
    ):
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        formula, used_sanitized = _coerce_router_formula(value)
        if formula is not None:
            return formula, used_sanitized
    return None, False


def _coerce_router_formula(value: Any) -> tuple[Any, bool]:
    return _coerce_router_formula_inner(value, seen=set())


def _coerce_router_formula_inner(value: Any, *, seen: set[int]) -> tuple[Any, bool]:
    if value is None:
        return None, False
    if hasattr(value, "to_string") and hasattr(value, "get_predicates"):
        return value, False
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in seen:
            return None, False
        seen.add(object_id)
        consumed_keys: set[str] = set()
        for key in (
            _ROUTER_FORMULA_PRIORITY_KEYS
            + _ROUTER_FORMULA_CONTAINER_KEYS
            + _ROUTER_FORMULA_TEXT_KEYS
        ):
            if key not in value:
                continue
            consumed_keys.add(key)
            nested = value.get(key)
            if nested is value:
                continue
            formula, used_sanitized = _coerce_router_formula_inner(
                nested,
                seen=seen,
            )
            if formula is not None:
                return formula, used_sanitized
        for raw_key in sorted(value.keys(), key=lambda item: str(item)):
            key = str(raw_key)
            if key in consumed_keys:
                continue
            nested = value.get(raw_key)
            if nested is value:
                continue
            formula, used_sanitized = _coerce_router_formula_inner(
                nested,
                seen=seen,
            )
            if formula is not None:
                return formula, used_sanitized
        return None, False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        object_id = id(value)
        if object_id in seen:
            return None, False
        seen.add(object_id)
        for item in value:
            formula, used_sanitized = _coerce_router_formula_inner(item, seen=seen)
            if formula is not None:
                return formula, used_sanitized
        return None, False

    text = str(value or "").strip()
    if text:
        sanitized = _sanitize_router_formula_text(text)
        if sanitized and sanitized != text:
            parsed = coerce_tdfol_formula(sanitized)
            if parsed is not None:
                return parsed, True

    parsed = coerce_tdfol_formula(value)
    if parsed is not None:
        return parsed, False
    return None, False


def _sanitize_router_formula_text(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    return _RESERVED_TDFOL_TERM_PREFIX.sub(
        lambda match: f"{match.group(1)}term_{match.group(2).lower()}_",
        normalized,
    )


def _record_formula_text(record: Mapping[str, Any]) -> str:
    for key in (
        _ROUTER_FORMULA_PRIORITY_KEYS
        + _ROUTER_FORMULA_CONTAINER_KEYS
        + _ROUTER_FORMULA_TEXT_KEYS
    ):
        if key not in record:
            continue
        text = _formula_text_from_value(record.get(key), seen=set())
        if text:
            return text
    return ""


def _formula_text_from_value(value: Any, *, seen: set[int]) -> str:
    if value is None:
        return ""
    if hasattr(value, "to_string") and hasattr(value, "get_predicates"):
        try:
            return str(value.to_string() or "").strip()
        except Exception:
            return ""
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in seen:
            return ""
        seen.add(object_id)
        consumed_keys: set[str] = set()
        for key in (
            _ROUTER_FORMULA_PRIORITY_KEYS
            + _ROUTER_FORMULA_CONTAINER_KEYS
            + _ROUTER_FORMULA_TEXT_KEYS
        ):
            if key not in value:
                continue
            consumed_keys.add(key)
            nested = value.get(key)
            if nested is value:
                continue
            text = _formula_text_from_value(nested, seen=seen)
            if text:
                return text
        for raw_key in sorted(value.keys(), key=lambda item: str(item)):
            key = str(raw_key)
            if key in consumed_keys:
                continue
            nested = value.get(raw_key)
            if nested is value:
                continue
            text = _formula_text_from_value(nested, seen=seen)
            if text:
                return text
        return ""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        object_id = id(value)
        if object_id in seen:
            return ""
        seen.add(object_id)
        for item in value:
            text = _formula_text_from_value(item, seen=seen)
            if text:
                return text
        return ""
    return str(value or "").strip()


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
    formula_object, used_sanitized = _record_formula_resolution(record)
    raw_formula = _record_formula_text(record)
    formula_text = raw_formula
    if formula_object is not None:
        try:
            formula_text = str(formula_object.to_string())
        except Exception:
            formula_text = raw_formula
    return {
        "formula": formula_text,
        "formula_parse_ok": formula_object is not None,
        "formula_sanitized": bool(used_sanitized),
        "proof_input": str(record.get("proof_input") or raw_formula or ""),
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
        "reason": (
            f"Used {first_completed} (no proof)"
            if first_completed
            else "All provers failed"
        ),
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
    compiled = _result_value(result, "is_compiled", None)
    if callable(compiled):
        try:
            return bool(compiled())
        except Exception:
            return False
    if compiled not in (None, ""):
        return bool(compiled)
    compiled = _result_value(result, "compiles", None)
    if callable(compiled):
        try:
            return bool(compiled())
        except Exception:
            return False
    if compiled not in (None, ""):
        return bool(compiled)
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
