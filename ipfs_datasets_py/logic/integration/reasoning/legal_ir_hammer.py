"""Legal IR wrapper around the generic hammer pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .hammer import HammerBackendRunner, HammerGoal, HammerPipeline, HammerPremise, KernelVerifier
from .hammer_backends import backend_health_for_runners, hammer_backend_health_summary
from .hammer_guidance import HammerGuidanceArtifact
from .legal_ir_contract_telemetry import collect_legal_ir_contract_telemetry
from .legal_ir_obligations import LegalIRProofObligation, generate_legal_ir_proof_obligations
from .legal_ir_premises import export_legal_ir_premises
from .legal_ir_premise_selection import (
    LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION,
    LegalIRPremiseSelector,
)
from .legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    HammerReconstructionReceipt,
    HammerTranslationRecord,
    reconstruction_receipt_from_hammer_result,
    translation_records_from_hammer_result,
)
from .legal_ir_proof_router import (
    DEFAULT_STAGE_BUDGETS,
    LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
    LegalIRProofRouteResult,
    LegalIRProofRouter,
    ProofRouteRunner,
    ProofRouteStage,
    ProofRoutingPolicy,
    ProofTrustLevel,
)


LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION = "legal-ir-hammer-report-v1"


@dataclass(frozen=True)
class LegalIRHammerConfig:
    """Runtime controls for hammer-checking Legal IR obligations."""

    max_premises: int = 256
    timeout_seconds: float = 10.0
    parallel_workers: Optional[int] = None
    verify_reconstruction: bool = False
    trusted_requires_reconstruction: bool = False
    max_obligations: int = 0
    staged_routing: bool = True
    required_trust_level: str = ""
    total_timeout_seconds: Optional[float] = None
    deterministic_timeout_seconds: float = 0.25
    native_logic_timeout_seconds: float = 2.0
    reconstruction_timeout_seconds: float = 10.0
    enabled_proof_routes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegalIRHammerReport:
    """Batch hammer result over a Legal IR sample/document."""

    artifacts: List[HammerGuidanceArtifact]
    obligation_count: int
    premise_count: int
    proved_count: int
    trusted_count: int
    elapsed_seconds: float
    schema_version: str = LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION
    metadata: Dict[str, Any] = field(default_factory=dict)
    translation_records: List[HammerTranslationRecord] = field(default_factory=list)
    reconstruction_receipts: List[HammerReconstructionReceipt] = field(default_factory=list)
    route_results: List[LegalIRProofRouteResult] = field(default_factory=list)

    @property
    def proof_routing_results(self) -> List[LegalIRProofRouteResult]:
        """Compatibility alias emphasizing that records are per proof."""

        return self.route_results

    @property
    def proof_success_rate(self) -> float:
        if self.obligation_count <= 0:
            return 0.0
        return self.proved_count / self.obligation_count

    @property
    def trusted_success_rate(self) -> float:
        if self.obligation_count <= 0:
            return 0.0
        return self.trusted_count / self.obligation_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "elapsed_seconds": round(float(self.elapsed_seconds), 12),
            "metadata": dict(sorted(self.metadata.items())),
            "obligation_count": int(self.obligation_count),
            "premise_count": int(self.premise_count),
            "proof_success_rate": round(self.proof_success_rate, 12),
            "proved_count": int(self.proved_count),
            "reconstruction_receipts": [
                receipt.to_dict() for receipt in self.reconstruction_receipts
            ],
            "route_results": [result.to_dict() for result in self.route_results],
            "schema_version": self.schema_version,
            "translation_records": [
                record.to_dict() for record in self.translation_records
            ],
            "trusted_count": int(self.trusted_count),
            "trusted_success_rate": round(self.trusted_success_rate, 12),
        }


class LegalIRHammerRunner:
    """Run the hammer against deterministic Legal IR obligations."""

    def __init__(
        self,
        *,
        config: Optional[LegalIRHammerConfig] = None,
        backends: Optional[Sequence[HammerBackendRunner]] = None,
        kernel_verifier: Optional[KernelVerifier] = None,
        pipeline: Optional[HammerPipeline] = None,
        proof_router: Optional[LegalIRProofRouter] = None,
        route_runners: Optional[Mapping[str, ProofRouteRunner]] = None,
    ) -> None:
        self.config = config or LegalIRHammerConfig()
        self.backends = list(backends) if backends is not None else None
        self.kernel_verifier = kernel_verifier
        self.pipeline = pipeline
        self.proof_router = proof_router
        self.route_runners = dict(route_runners or {})

    def prove(
        self,
        sample_or_document: Any,
        *,
        obligations: Optional[Sequence[LegalIRProofObligation | Mapping[str, Any]]] = None,
        premises: Optional[Sequence[HammerPremise | Mapping[str, Any] | str]] = None,
        theorem_registry: Any = None,
        extra_candidate_metadata: Optional[Mapping[str, Any]] = None,
    ) -> LegalIRHammerReport:
        start = time.time()
        resolved_obligations = [
            self._as_obligation(item)
            for item in (obligations or generate_legal_ir_proof_obligations(sample_or_document))
        ]
        if self.config.max_obligations > 0:
            resolved_obligations = resolved_obligations[: self.config.max_obligations]
        resolved_premises = list(
            premises
            if premises is not None
            else export_legal_ir_premises(
                sample_or_document,
                obligations=resolved_obligations,
                theorem_registry=theorem_registry,
            )
        )
        if self.proof_router is not None:
            pipeline = self.proof_router.pipeline
        elif self.pipeline is not None:
            pipeline = self.pipeline
        else:
            contract_telemetry = collect_legal_ir_contract_telemetry(sample_or_document)
            pipeline = HammerPipeline(
                backends=self.backends,
                premise_selector=LegalIRPremiseSelector(
                    contract_telemetry=contract_telemetry
                ),
                max_premises=self.config.max_premises,
                timeout_seconds=self.config.timeout_seconds,
                parallel_workers=self.config.parallel_workers,
                verify_reconstruction=self.config.verify_reconstruction,
                kernel_verifier=self.kernel_verifier,
            )
        backend_health = backend_health_for_runners(pipeline.backends)
        backend_health_summary = hammer_backend_health_summary(backend_health)
        artifacts: List[HammerGuidanceArtifact] = []
        translation_records: List[HammerTranslationRecord] = []
        reconstruction_receipts: List[HammerReconstructionReceipt] = []
        route_results: List[LegalIRProofRouteResult] = []
        proof_router = self.proof_router
        if proof_router is None and self.config.staged_routing:
            policy = self._routing_policy()
            proof_router = LegalIRProofRouter(
                pipeline,
                policy=policy,
                route_runners=self.route_runners,
            )
        for obligation in resolved_obligations:
            goal = HammerGoal(
                statement=obligation.statement,
                itp_system=str(obligation.metadata.get("itp_system") or "lean"),
                name=obligation.obligation_id,
                metadata={
                    "goal_source": "legal_ir_proof_obligation",
                    "legal_ir_view": obligation.legal_ir_view,
                    "logic_family": obligation.logic_family,
                    "obligation_id": obligation.obligation_id,
                    "obligation_kind": obligation.kind,
                    "proof_obligation_ids": [obligation.obligation_id],
                    "sample_id": obligation.sample_id,
                    "target_component": obligation.legal_ir_view,
                    **dict(obligation.metadata),
                },
            )
            if proof_router is not None:
                route_result = proof_router.route(
                    obligation,
                    goal,
                    resolved_premises,
                    sample_or_document=sample_or_document,
                )
                result = route_result.hammer_result
                route_results.append(route_result)
            else:
                result = pipeline.prove(goal, resolved_premises)
            candidate_metadata = {
                "legal_ir_view": obligation.legal_ir_view,
                "logic_family": obligation.logic_family,
                "obligation_id": obligation.obligation_id,
                "obligation_kind": obligation.kind,
                "proof_obligation_ids": [obligation.obligation_id],
                "target_component": obligation.legal_ir_view,
                "target_metrics": self._target_metrics_for_obligation(obligation),
                **dict(obligation.metadata),
                **dict(extra_candidate_metadata or {}),
            }
            artifact = HammerGuidanceArtifact.from_hammer_result(
                result,
                candidate_metadata=candidate_metadata,
                trusted_requires_reconstruction=self.config.trusted_requires_reconstruction,
            )
            if proof_router is not None:
                artifact = replace(
                    artifact,
                    proved=route_result.proved,
                    trusted=route_result.trust_satisfied,
                    failure_reason="" if route_result.proved else route_result.status.value,
                    rejection_reasons=(
                        artifact.rejection_reasons
                        if route_result.trust_satisfied
                        else sorted(
                            set(
                                [
                                    *artifact.rejection_reasons,
                                    (
                                        "required_trust_not_obtained"
                                        if route_result.proved
                                        else route_result.status.value
                                    ),
                                ]
                            )
                        )
                    ),
                    metadata={
                        **artifact.metadata,
                        "proof_route_schema_version": LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
                        "proof_route_status": route_result.status.value,
                        "proof_route_stop_reason": route_result.stop_reason,
                        "proof_route_trust_level": route_result.trust_level.name.lower(),
                    },
                )
            records = translation_records_from_hammer_result(
                result,
                obligation_id=obligation.obligation_id,
                input_formula_id=obligation.formula_id,
            )
            receipt = reconstruction_receipt_from_hammer_result(
                result,
                translation_records=records,
                obligation_id=obligation.obligation_id,
                input_formula_id=obligation.formula_id,
                trusted_requires_reconstruction=self.config.trusted_requires_reconstruction,
                trusted=artifact.trusted,
            )
            artifacts.append(artifact)
            translation_records.extend(records)
            reconstruction_receipts.append(receipt)

        proved_count = sum(1 for artifact in artifacts if artifact.proved)
        trusted_count = sum(1 for artifact in artifacts if artifact.trusted)
        return LegalIRHammerReport(
            artifacts=artifacts,
            obligation_count=len(resolved_obligations),
            premise_count=len(resolved_premises),
            proved_count=proved_count,
            trusted_count=trusted_count,
            elapsed_seconds=time.time() - start,
            translation_records=translation_records,
            reconstruction_receipts=reconstruction_receipts,
            route_results=route_results,
            metadata={
                "backend_health": backend_health_summary,
                "reconstruction_receipt_count": len(reconstruction_receipts),
                "reconstruction_receipt_schema_version": (
                    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
                ),
                "max_premises": self.config.max_premises,
                "premise_selection_schema_version": LEGAL_IR_PREMISE_SELECTION_SCHEMA_VERSION,
                "timeout_seconds": self.config.timeout_seconds,
                "translation_record_count": len(translation_records),
                "translation_schema_version": LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
                "verify_reconstruction": self.config.verify_reconstruction,
                "proof_route_count": len(route_results),
                "proof_router_schema_version": LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
                "proof_routing_enabled": bool(proof_router is not None),
                "proof_route_stage_order": [stage.value for stage in ProofRouteStage],
            },
        )

    def _routing_policy(self) -> ProofRoutingPolicy:
        required = self.config.required_trust_level or (
            "kernel"
            if self.config.trusted_requires_reconstruction or self.config.verify_reconstruction
            else "backend"
        )
        budgets = dict(DEFAULT_STAGE_BUDGETS)
        budgets.update(
            {
                ProofRouteStage.DETERMINISTIC: self.config.deterministic_timeout_seconds,
                ProofRouteStage.NATIVE_LOGIC: self.config.native_logic_timeout_seconds,
                ProofRouteStage.SMT_ATP: self.config.timeout_seconds,
                ProofRouteStage.LEAN_RECONSTRUCTION: self.config.reconstruction_timeout_seconds,
            }
        )
        total = self.config.total_timeout_seconds
        if total is None:
            total = sum(budgets.values())
        return ProofRoutingPolicy(
            required_trust=ProofTrustLevel.parse(required),
            total_timeout_seconds=total,
            stage_timeout_seconds=budgets,
            enabled_routes=self.config.enabled_proof_routes,
        )

    def _as_obligation(
        self,
        value: LegalIRProofObligation | Mapping[str, Any],
    ) -> LegalIRProofObligation:
        if isinstance(value, LegalIRProofObligation):
            return value
        return LegalIRProofObligation(
            obligation_id=str(value.get("obligation_id") or ""),
            statement=str(value.get("statement") or ""),
            kind=str(value.get("kind") or ""),
            legal_ir_view=str(value.get("legal_ir_view") or value.get("target_component") or ""),
            logic_family=str(value.get("logic_family") or value.get("family") or ""),
            sample_id=str(value.get("sample_id") or ""),
            formula_id=str(value.get("formula_id") or ""),
            premise_hints=[str(item) for item in value.get("premise_hints", []) or []],
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(value.get("schema_version") or "legal-ir-proof-obligation-v1"),
        )

    def _target_metrics_for_obligation(self, obligation: LegalIRProofObligation) -> List[str]:
        metrics = ["symbolic_validity", "hammer_proof_success_rate"]
        if obligation.legal_ir_view == "modal.decompiler":
            metrics.extend(["round_trip_loss", "source_copy_penalty"])
        elif obligation.legal_ir_view == "knowledge_graphs.neo4j_compat":
            metrics.append("knowledge_graph_validity")
        elif obligation.legal_ir_view in {"deontic.ir", "TDFOL.prover", "CEC.native"}:
            metrics.append("compiler_ir_cross_entropy_loss")
        else:
            metrics.append("compiler_ir_cosine_similarity")
        return list(dict.fromkeys(metrics))


def run_legal_ir_hammer(
    sample_or_document: Any,
    *,
    obligations: Optional[Sequence[LegalIRProofObligation | Mapping[str, Any]]] = None,
    premises: Optional[Sequence[HammerPremise | Mapping[str, Any] | str]] = None,
    theorem_registry: Any = None,
    config: Optional[LegalIRHammerConfig] = None,
    backends: Optional[Sequence[HammerBackendRunner]] = None,
    kernel_verifier: Optional[KernelVerifier] = None,
    proof_router: Optional[LegalIRProofRouter] = None,
    route_runners: Optional[Mapping[str, ProofRouteRunner]] = None,
) -> LegalIRHammerReport:
    return LegalIRHammerRunner(
        config=config,
        backends=backends,
        kernel_verifier=kernel_verifier,
        proof_router=proof_router,
        route_runners=route_runners,
    ).prove(
        sample_or_document,
        obligations=obligations,
        premises=premises,
        theorem_registry=theorem_registry,
    )


__all__ = [
    "LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION",
    "LegalIRHammerConfig",
    "LegalIRHammerReport",
    "LegalIRHammerRunner",
    "HammerReconstructionReceipt",
    "HammerTranslationRecord",
    "LegalIRProofRouteResult",
    "LegalIRProofRouter",
    "ProofRoutingPolicy",
    "ProofTrustLevel",
    "run_legal_ir_hammer",
]
