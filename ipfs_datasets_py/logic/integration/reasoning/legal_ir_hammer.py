"""Legal IR wrapper around the generic hammer pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .hammer import HammerBackendRunner, HammerGoal, HammerPipeline, HammerPremise, KernelVerifier
from .hammer_backends import backend_health_for_runners, hammer_backend_health_summary
from .hammer_guidance import HammerGuidanceArtifact
from .legal_ir_obligations import LegalIRProofObligation, generate_legal_ir_proof_obligations
from .legal_ir_premises import export_legal_ir_premises


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
            "schema_version": self.schema_version,
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
    ) -> None:
        self.config = config or LegalIRHammerConfig()
        self.backends = list(backends) if backends is not None else None
        self.kernel_verifier = kernel_verifier
        self.pipeline = pipeline

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
        pipeline = self.pipeline or HammerPipeline(
            backends=self.backends,
            max_premises=self.config.max_premises,
            timeout_seconds=self.config.timeout_seconds,
            parallel_workers=self.config.parallel_workers,
            verify_reconstruction=self.config.verify_reconstruction,
            kernel_verifier=self.kernel_verifier,
        )
        backend_health = backend_health_for_runners(pipeline.backends)
        backend_health_summary = hammer_backend_health_summary(backend_health)
        artifacts: List[HammerGuidanceArtifact] = []
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
            artifacts.append(
                HammerGuidanceArtifact.from_hammer_result(
                    result,
                    candidate_metadata=candidate_metadata,
                    trusted_requires_reconstruction=self.config.trusted_requires_reconstruction,
                )
            )

        proved_count = sum(1 for artifact in artifacts if artifact.proved)
        trusted_count = sum(1 for artifact in artifacts if artifact.trusted)
        return LegalIRHammerReport(
            artifacts=artifacts,
            obligation_count=len(resolved_obligations),
            premise_count=len(resolved_premises),
            proved_count=proved_count,
            trusted_count=trusted_count,
            elapsed_seconds=time.time() - start,
            metadata={
                "backend_health": backend_health_summary,
                "max_premises": self.config.max_premises,
                "timeout_seconds": self.config.timeout_seconds,
                "verify_reconstruction": self.config.verify_reconstruction,
            },
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
) -> LegalIRHammerReport:
    return LegalIRHammerRunner(
        config=config,
        backends=backends,
        kernel_verifier=kernel_verifier,
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
    "run_legal_ir_hammer",
]
