"""Loss-driven TODO generation and batch claiming for modal parser work."""

from __future__ import annotations

import hashlib
import heapq
import json
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.modal.synthesis import (
    ModalProgramSynthesisHint,
    residual_signature_for_hint,
    synthesis_hints_from_autoencoder_introspections,
)
from ipfs_datasets_py.logic.submodule_registry import logic_optimizer_scope_for_component

from .legal_samples import LegalSample
from .modal_autoencoder import AdaptiveModalAutoencoder, AutoencoderEvaluation


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


AUTOENCODER_SGD_ROLE = "autoencoder_sgd"
PROGRAM_SYNTHESIS_ROLE = "program_synthesis"
AUTOENCODER_EXECUTION_TARGET = "adaptive_autoencoder"
PROGRAM_SYNTHESIS_EXECUTION_TARGET = "codex_program_repair"
TODO_STATUS_RANK = {
    "pending": 0,
    "claimed": 1,
    "completed": 2,
    "failed_validation": 2,
}
PROGRAM_SYNTHESIS_DEDUPE_KEEP_RANK = {
    "failed_validation": 0,
    "pending": 1,
    "claimed": 2,
    "completed": 3,
}
AUTOENCODER_DEDUPE_KEEP_RANK = {
    "failed_validation": 0,
    "pending": 1,
    "claimed": 2,
    "completed": 3,
}
PROGRAM_SYNTHESIS_NEAR_DUPLICATE_JACCARD = 0.8
PROGRAM_SYNTHESIS_ACTION_TARGETS = {
    "add_deterministic_parser_rule": "modal.compiler",
    "add_or_review_modal_ambiguity_policy": "modal.compiler.ambiguity",
    "audit_frame_logic_terms": "modal.frame_logic",
    "improve_bm25_frame_selector": "modal.frame_logic",
    "improve_flogic_frame_alignment": "modal.frame_logic",
    "increase_modal_ir_span_coverage": "modal.compiler",
    "refine_modal_family_cue_rules": "modal.compiler.registry",
    "refine_semantic_decompiler_reconstruction": "modal.ir_decompiler",
    "refine_typed_ir_or_decompiler_slots": "modal.ir_decompiler",
    "repair_deontic_bridge_quality_gate": "deontic.ir",
    "repair_deontic_graph_bridge": "deontic.ir",
    "repair_deontic_prover_bridge": "deontic.ir",
    "repair_cec_dcec_bridge": "CEC.native",
    "repair_external_prover_router": "external_provers.router",
    "repair_multiview_legal_ir_acceptance": "bridge.contracts",
    "repair_multiview_legal_ir_graph_projection": "knowledge_graphs.neo4j_compat",
    "repair_multiview_legal_ir_loss": "bridge.contracts",
    "repair_multiview_legal_ir_prover_gate": "external_provers.router",
    "repair_multiview_legal_ir_view_coverage": "bridge.contracts",
    "repair_flogic_ontology_constraints": "modal.frame_logic",
    "repair_tdfol_bridge_parse": "TDFOL.prover",
    "repair_zkp_attestation_bridge": "zkp.circuits",
}
PROGRAM_SYNTHESIS_ACTION_TARGET_METRICS = {
    "add_deterministic_parser_rule": ("symbolic_validity_penalty", "modal_span_coverage_loss"),
    "add_or_review_modal_ambiguity_policy": ("cross_entropy_loss",),
    "audit_frame_logic_terms": ("flogic_similarity_loss", "ontology_violation_count"),
    "improve_bm25_frame_selector": ("frame_ranking_loss",),
    "improve_flogic_frame_alignment": ("flogic_similarity_loss",),
    "increase_modal_ir_span_coverage": ("modal_span_coverage_loss",),
    "refine_modal_family_cue_rules": ("cross_entropy_loss",),
    "refine_semantic_decompiler_reconstruction": (
        "source_copy_loss",
        "source_copy_reward_hack_penalty",
        "structural_text_reconstruction_loss",
        "text_reconstruction_loss",
    ),
    "refine_typed_ir_or_decompiler_slots": (
        "embedding_cosine_similarity",
        "reconstruction_loss",
        "legal_ir_multiview_cosine_loss",
        "legal_ir_multiview_reconstruction_loss",
    ),
    "repair_cec_dcec_bridge": (
        "cec_dcec_event_formula_invalid_ratio",
        "cec_dcec_validation_failure_ratio",
        "legal_ir_view_cross_entropy_loss",
    ),
    "repair_deontic_bridge_quality_gate": (
        "deontic_decoder_slot_loss",
        "deontic_quality_requires_validation_loss",
        "legal_ir_view_cross_entropy_loss",
    ),
    "repair_deontic_graph_bridge": ("deontic_graph_failure_penalty",),
    "repair_deontic_prover_bridge": ("deontic_proof_failure_ratio",),
    "repair_external_prover_router": (
        "external_prover_unavailable_loss",
        "legal_ir_multiview_proof_failure_ratio",
    ),
    "repair_multiview_legal_ir_acceptance": ("legal_ir_multiview_acceptance_loss",),
    "repair_multiview_legal_ir_graph_projection": (
        "legal_ir_multiview_graph_failure_penalty",
        "legal_ir_view_cross_entropy_loss",
    ),
    "repair_multiview_legal_ir_loss": (
        "legal_ir_view_cross_entropy_loss",
        "legal_ir_multiview_cross_entropy_loss",
        "legal_ir_multiview_total_loss",
    ),
    "repair_multiview_legal_ir_prover_gate": (
        "legal_ir_multiview_proof_failure_ratio",
    ),
    "repair_multiview_legal_ir_view_coverage": (
        "legal_ir_multiview_view_coverage_loss",
    ),
    "repair_flogic_ontology_constraints": (
        "flogic_similarity_loss",
        "ontology_violation_count",
    ),
    "repair_tdfol_bridge_parse": (
        "tdfol_parse_failure_ratio",
        "tdfol_no_formula_loss",
        "legal_ir_view_cross_entropy_loss",
    ),
    "repair_zkp_attestation_bridge": (
        "zkp_verification_failure_ratio",
        "zkp_attestation_missing_loss",
        "legal_ir_view_cross_entropy_loss",
    ),
}
PROGRAM_SYNTHESIS_SCOPE_VALIDATION_TESTS = {
    "bridge": (
        "tests/unit/logic/test_logic_bridge_layer.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ),
    "cec": (
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "compiler_ambiguity": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "compiler_parser": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "compiler_registry": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "deontic": (
        "tests/unit/logic/test_deontic_graph.py",
        "tests/unit/logic/test_deontic_knowledge_base.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "external_provers": (
        "tests/unit/logic/test_logic_bridge_layer.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ),
    "frame_logic": (
        "ipfs_datasets_py/logic/test_flogic_optimizer.py",
        "tests/unit/logic/test_flogic_integration.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "ir_decompiler": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "knowledge_graphs": (
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "tdfol": (
        "tests/unit/logic/TDFOL/test_formula_dependency_graph.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "zkp": (
        "tests/unit/logic/test_flogic_cache_zkp.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
}
BRIDGE_LOSS_CACHE_MAX = 4096
_BRIDGE_LOSS_CACHE_LOCK = threading.Lock()
_BRIDGE_LOSS_CACHE: Dict[str, Dict[str, float]] = {}

AUTOENCODER_TRAINABLE_ACTIONS = {
    "improve_encoder_decoder_reconstruction",
    "improve_legal_ir_view_distribution",
    "improve_modal_family_classifier",
}
AUTOENCODER_TRAINABLE_LOSSES = {
    "cosine_loss",
    "cross_entropy_loss",
    "legal_ir_view_cross_entropy_loss",
    "reconstruction_loss",
}
BridgeLossEvaluator = Callable[
    [Sequence[LegalSample]],
    Mapping[str, Mapping[str, float]],
]


@dataclass(frozen=True)
class ModalOptimizerPolicy:
    """Policy separating continuous optimizer updates from program repair."""

    autoencoder_role: str = AUTOENCODER_SGD_ROLE
    program_synthesis_role: str = PROGRAM_SYNTHESIS_ROLE
    program_synthesis_min_support: int = 2
    enable_program_synthesis_todos: bool = True
    max_autoencoder_pending: int = 256
    max_program_synthesis_pending: int = 512
    program_synthesis_near_duplicate_jaccard: float = PROGRAM_SYNTHESIS_NEAR_DUPLICATE_JACCARD
    program_synthesis_min_residual_occurrences: int = 1
    program_synthesis_min_residual_survival_score: float = 0.0

    def role_for(self, *, action: str, loss_name: str = "") -> str:
        if (
            action in AUTOENCODER_TRAINABLE_ACTIONS
            or loss_name in AUTOENCODER_TRAINABLE_LOSSES
        ):
            return self.autoencoder_role
        return self.program_synthesis_role

    def execution_target_for(self, *, action: str, loss_name: str = "") -> str:
        if self.role_for(action=action, loss_name=loss_name) == self.autoencoder_role:
            return AUTOENCODER_EXECUTION_TARGET
        return PROGRAM_SYNTHESIS_EXECUTION_TARGET

    def metadata_for(self, *, action: str, loss_name: str = "") -> Dict[str, str]:
        role = self.role_for(action=action, loss_name=loss_name)
        return {
            "execution_target": self.execution_target_for(
                action=action,
                loss_name=loss_name,
            ),
            "optimizer_role": role,
            "optimizer_stage": (
                "continuous_state_update"
                if role == self.autoencoder_role
                else "typed_program_synthesis"
            ),
        }

    def is_trainable(self, todo: "ModalTodo") -> bool:
        return _todo_optimizer_role(todo) == self.autoencoder_role


@dataclass(frozen=True)
class LossSnapshot:
    """One sample's loss signals used to create deterministic work items."""

    sample_id: str
    citation: str
    losses: Dict[str, float]
    selected_frame: Optional[str] = None
    parser_formula_count: int = 0

    @classmethod
    def from_sample(
        cls,
        sample: LegalSample,
        *,
        autoencoder: Optional[AutoencoderEvaluation] = None,
        extra_losses: Optional[Mapping[str, float]] = None,
    ) -> "LossSnapshot":
        """Build a snapshot from a legal sample and optional aggregate losses."""
        losses: Dict[str, float] = {}
        if autoencoder is not None:
            losses.update(
                {
                    "cosine_loss": autoencoder.cosine_loss,
                    "cross_entropy_loss": autoencoder.cross_entropy_loss,
                    "frame_ranking_loss": autoencoder.frame_ranking_loss,
                    "reconstruction_loss": autoencoder.reconstruction_loss,
                    "symbolic_validity_penalty": autoencoder.symbolic_validity_penalty,
                }
            )
            losses.update(
                {
                    str(name): float(value)
                    for name, value in autoencoder.legal_ir_losses.items()
                }
            )
        losses.update({name: float(value) for name, value in sample.losses.items()})
        if extra_losses:
            losses.update({name: float(value) for name, value in extra_losses.items()})
        return cls(
            sample_id=sample.sample_id,
            citation=sample.citation,
            losses=dict(sorted(losses.items())),
            selected_frame=sample.selected_frame,
            parser_formula_count=len(sample.modal_ir.formulas),
        )

    def total_loss(self) -> float:
        """Return the aggregate loss magnitude for prioritization."""
        return sum(max(0.0, float(value)) for value in self.losses.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation": self.citation,
            "losses": dict(sorted(self.losses.items())),
            "parser_formula_count": self.parser_formula_count,
            "sample_id": self.sample_id,
            "selected_frame": self.selected_frame,
        }


def bridge_loss_evaluator_for_names(
    bridge_names: Sequence[str],
    *,
    evaluate_provers: Optional[bool] = None,
) -> BridgeLossEvaluator:
    """Build a lazy bridge evaluator that returns optimizer-visible losses.

    The evaluator is intentionally sample-id keyed so the supervisor can merge
    bridge diagnostics into the existing ``LossSnapshot`` flow without coupling
    TODO generation to any one logic adapter.
    """

    names = tuple(
        dict.fromkeys(
            str(name).strip()
            for name in bridge_names
            if str(name).strip() and str(name).strip().lower() not in {"none", "off", "false"}
        )
    )
    def evaluate(samples: Sequence[LegalSample]) -> Mapping[str, Mapping[str, float]]:
        losses_by_sample: Dict[str, Dict[str, float]] = {}
        if not names:
            return losses_by_sample
        from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

        for sample in samples:
            sample_losses: Dict[str, float] = {}
            cache_key = _bridge_loss_cache_key(
                sample,
                bridge_names=names,
                evaluate_provers=evaluate_provers,
            )
            with _BRIDGE_LOSS_CACHE_LOCK:
                cached_losses = _BRIDGE_LOSS_CACHE.get(cache_key)
            if cached_losses is not None:
                losses_by_sample[sample.sample_id] = dict(cached_losses)
                continue
            try:
                multiview = evaluate_legal_ir_multiview(
                    sample.text,
                    bridge_names=names,
                    document_id=sample.sample_id,
                    evaluate_provers=evaluate_provers,
                    citation=sample.citation,
                    source=sample.source,
                    source_embedding=sample.embedding_vector,
                )
                sample_losses.update(_multiview_losses_for_optimizer(multiview))
            except Exception:
                sample_losses["legal_ir_multiview_bridge_evaluation_failure_loss"] = 1.0
            if sample_losses:
                sample_losses = dict(sorted(sample_losses.items()))
                with _BRIDGE_LOSS_CACHE_LOCK:
                    if len(_BRIDGE_LOSS_CACHE) >= BRIDGE_LOSS_CACHE_MAX:
                        _BRIDGE_LOSS_CACHE.pop(next(iter(_BRIDGE_LOSS_CACHE)), None)
                    _BRIDGE_LOSS_CACHE[cache_key] = dict(sample_losses)
                losses_by_sample[sample.sample_id] = dict(sorted(sample_losses.items()))
        return losses_by_sample

    return evaluate


def _bridge_loss_cache_key(
    sample: LegalSample,
    *,
    bridge_names: Sequence[str],
    evaluate_provers: Optional[bool],
) -> str:
    """Return a stable key for optimizer-visible bridge diagnostics."""
    embedding = [
        round(float(value), 12)
        for value in list(getattr(sample, "embedding_vector", []) or [])
    ]
    payload = {
        "bridge_names": list(bridge_names),
        "citation": str(getattr(sample, "citation", "") or ""),
        "embedding_hash": hashlib.sha256(
            json.dumps(embedding, ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "evaluate_provers": evaluate_provers,
        "sample_id": str(getattr(sample, "sample_id", "") or ""),
        "source": str(getattr(sample, "source", "") or ""),
        "text_hash": hashlib.sha256(
            str(getattr(sample, "text", "") or "").encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _multiview_losses_for_optimizer(multiview: Any) -> Dict[str, float]:
    """Flatten a multi-view bridge report into TODO-generator loss names."""

    losses: Dict[str, float] = {}
    training_target = multiview.training_target()
    losses.update(
        {
            str(name): _safe_float(value)
            for name, value in dict(getattr(training_target, "losses", {}) or {}).items()
        }
    )
    for report in dict(getattr(multiview, "reports", {}) or {}).values():
        losses.update(_bridge_losses_from_report(report))
    for adapter_name in dict(getattr(multiview, "failures", {}) or {}):
        prefix = _bridge_loss_prefix(adapter_name)
        losses[f"{prefix}_bridge_evaluation_failure_loss"] = 1.0
    return dict(sorted(losses.items()))


def _bridge_losses_from_report(report: Any) -> Dict[str, float]:
    prefix = _bridge_loss_prefix(str(getattr(report, "adapter_name", "bridge")))
    round_trip = getattr(report, "round_trip", None)
    proof_gate = getattr(report, "proof_gate", None)
    graph_projection = getattr(report, "graph_projection", None)
    losses: Dict[str, float] = {}

    for name, value in dict(getattr(round_trip, "extra_losses", {}) or {}).items():
        losses[str(name)] = _safe_float(value)

    proof_failure_ratio = _safe_float(getattr(proof_gate, "failure_ratio", 0.0))
    if proof_failure_ratio > 0.0:
        losses[f"{prefix}_proof_failure_ratio"] = proof_failure_ratio

    graph_failure_penalty = _safe_float(
        getattr(graph_projection, "graph_failure_penalty", 0.0)
    )
    if graph_failure_penalty > 0.0:
        losses[f"{prefix}_graph_failure_penalty"] = graph_failure_penalty

    return dict(sorted(losses.items()))


def _bridge_loss_prefix(name: str) -> str:
    normalized = "".join(
        char.lower() if char.isalnum() else "_"
        for char in str(name or "bridge").strip()
    ).strip("_")
    if normalized == "deontic_norms":
        return "deontic"
    if normalized == "zkp_attestation":
        return "zkp"
    return normalized or "bridge"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class ModalTodo:
    """A deterministic unit of optimizer work created from loss signals."""

    todo_id: str
    action: str
    objective: str
    sample_ids: List[str]
    citations: List[str]
    loss_name: str
    loss_value: float
    priority: float
    status: str = "pending"
    created_at: str = field(default_factory=_utc_now)
    claimed_by: Optional[str] = None
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def claim(self, worker_id: str) -> None:
        self.status = "claimed"
        self.claimed_by = worker_id
        self.claimed_at = _utc_now()

    def complete(self) -> None:
        self.status = "completed"
        self.completed_at = _utc_now()

    def fail_validation(self, reason: str) -> None:
        self.status = "failed_validation"
        self.completed_at = None
        self.metadata["failure_reason"] = reason
        self.metadata["failed_validation_at"] = _utc_now()

    def requeue(self, reason: str) -> None:
        self.status = "pending"
        self.claimed_by = None
        self.claimed_at = None
        self.completed_at = None
        retry_count = int(self.metadata.get("transient_failure_count", 0)) + 1
        self.metadata["transient_failure_count"] = retry_count
        self.metadata["transient_failure_reason"] = reason
        self.metadata["transient_failure_at"] = _utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "citations": list(self.citations),
            "claimed_at": self.claimed_at,
            "claimed_by": self.claimed_by,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "loss_name": self.loss_name,
            "loss_value": self.loss_value,
            "metadata": dict(sorted(self.metadata.items())),
            "objective": self.objective,
            "priority": self.priority,
            "sample_ids": list(self.sample_ids),
            "status": self.status,
            "todo_id": self.todo_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModalTodo":
        return cls(
            todo_id=str(data["todo_id"]),
            action=str(data["action"]),
            objective=str(data["objective"]),
            sample_ids=[str(value) for value in data.get("sample_ids", [])],
            citations=[str(value) for value in data.get("citations", [])],
            loss_name=str(data["loss_name"]),
            loss_value=float(data["loss_value"]),
            priority=float(data["priority"]),
            status=str(data.get("status", "pending")),
            created_at=str(data.get("created_at") or _utc_now()),
            claimed_by=data.get("claimed_by"),
            claimed_at=data.get("claimed_at"),
            completed_at=data.get("completed_at"),
            metadata=dict(data.get("metadata", {})),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ModalOptimizationStep:
    """One supervisor iteration from evaluation through validated TODO work."""

    iteration: int
    worker_id: str
    before: AutoencoderEvaluation
    after: AutoencoderEvaluation
    seeded_count: int
    claimed_count: int
    applied_count: int
    completed_count: int
    pending_count: int
    claimed_open_count: int
    completed_todo_ids: List[str] = field(default_factory=list)
    failed_validation_count: int = 0
    failed_validation_todo_ids: List[str] = field(default_factory=list)
    applied_updates: List[Dict[str, Any]] = field(default_factory=list)
    autoencoder_claimed_count: int = 0
    bridge_loss_failure_count: int = 0
    bridge_loss_sample_count: int = 0
    bridge_loss_signal_count: int = 0
    loss_seeded_count: int = 0
    program_synthesis_deduped_count: int = 0
    program_synthesis_pending_count: int = 0
    program_synthesis_seeded_count: int = 0
    validation_before: Optional[AutoencoderEvaluation] = None
    validation_after: Optional[AutoencoderEvaluation] = None
    created_at: str = field(default_factory=_utc_now)

    @property
    def cross_entropy_delta(self) -> float:
        return self.before.cross_entropy_loss - self.after.cross_entropy_loss

    @property
    def cosine_similarity_delta(self) -> float:
        return self.after.embedding_cosine_similarity - self.before.embedding_cosine_similarity

    @property
    def validation_cross_entropy_delta(self) -> Optional[float]:
        if self.validation_before is None or self.validation_after is None:
            return None
        return self.validation_before.cross_entropy_loss - self.validation_after.cross_entropy_loss

    @property
    def validation_cosine_similarity_delta(self) -> Optional[float]:
        if self.validation_before is None or self.validation_after is None:
            return None
        return (
            self.validation_after.embedding_cosine_similarity
            - self.validation_before.embedding_cosine_similarity
        )

    @property
    def improved(self) -> bool:
        if self.validation_before is not None and self.validation_after is not None:
            return bool(
                (self.validation_cross_entropy_delta or 0.0) > 0.0
                or (self.validation_cosine_similarity_delta or 0.0) > 0.0
            )
        return self.cross_entropy_delta > 0.0 or self.cosine_similarity_delta > 0.0

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "after": self.after.to_dict(),
            "applied_count": self.applied_count,
            "applied_updates": list(self.applied_updates),
            "autoencoder_claimed_count": self.autoencoder_claimed_count,
            "before": self.before.to_dict(),
            "bridge_loss_failure_count": self.bridge_loss_failure_count,
            "bridge_loss_sample_count": self.bridge_loss_sample_count,
            "bridge_loss_signal_count": self.bridge_loss_signal_count,
            "claimed_count": self.claimed_count,
            "claimed_open_count": self.claimed_open_count,
            "completed_count": self.completed_count,
            "completed_todo_ids": list(self.completed_todo_ids),
            "cosine_similarity_delta": self.cosine_similarity_delta,
            "created_at": self.created_at,
            "cross_entropy_delta": self.cross_entropy_delta,
            "failed_validation_count": self.failed_validation_count,
            "failed_validation_todo_ids": list(self.failed_validation_todo_ids),
            "improved": self.improved,
            "iteration": self.iteration,
            "loss_seeded_count": self.loss_seeded_count,
            "pending_count": self.pending_count,
            "program_synthesis_deduped_count": self.program_synthesis_deduped_count,
            "program_synthesis_pending_count": self.program_synthesis_pending_count,
            "program_synthesis_seeded_count": self.program_synthesis_seeded_count,
            "seeded_count": self.seeded_count,
            "worker_id": self.worker_id,
        }
        if self.validation_before is not None and self.validation_after is not None:
            data.update(
                {
                    "validation_after": self.validation_after.to_dict(),
                    "validation_before": self.validation_before.to_dict(),
                    "validation_cosine_similarity_delta": self.validation_cosine_similarity_delta,
                    "validation_cross_entropy_delta": self.validation_cross_entropy_delta,
                }
            )
        return data


@dataclass(frozen=True)
class ModalOptimizationRun:
    """Result of a bounded modal daemon optimization run."""

    steps: List[ModalOptimizationStep]
    final_evaluation: AutoencoderEvaluation
    stopped_reason: str
    validation_final_evaluation: Optional[AutoencoderEvaluation] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "final_evaluation": self.final_evaluation.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "stopped_reason": self.stopped_reason,
        }
        if self.validation_final_evaluation is not None:
            data["validation_final_evaluation"] = self.validation_final_evaluation.to_dict()
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def save_json(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.to_json() + "\n", encoding="utf-8")


class ModalLossTodoGenerator:
    """Convert loss signals into optimizer or program-repair TODOs."""

    DEFAULT_THRESHOLDS = {
        "cec_dcec_no_formula_loss": 0.0,
        "cec_dcec_event_formula_invalid_ratio": 0.0,
        "cec_dcec_validation_failure_ratio": 0.0,
        "cosine_loss": 0.05,
        "cross_entropy_loss": 0.05,
        "deontic_bridge_evaluation_failure_loss": 0.0,
        "deontic_decoder_requires_validation_rate": 0.0,
        "deontic_decoder_slot_loss": 0.0,
        "deontic_graph_build_error_loss": 0.0,
        "deontic_graph_conflict_loss": 0.0,
        "deontic_graph_failure_penalty": 0.0,
        "deontic_graph_source_gap_loss": 0.0,
        "deontic_ir_slot_provenance_loss": 0.0,
        "deontic_phase8_quality_incomplete_loss": 0.0,
        "deontic_proof_failure_ratio": 0.0,
        "deontic_quality_requires_validation_loss": 0.0,
        "deontic_repair_queue_rate": 0.0,
        "deontic_repair_required_rate": 0.0,
        "external_prover_failure_ratio": 0.0,
        "external_prover_unavailable_loss": 0.0,
        "flogic_similarity_loss": 0.05,
        "frame_ranking_loss": 0.0,
        "legal_ir_multiview_acceptance_loss": 0.0,
        "legal_ir_multiview_bridge_evaluation_failure_loss": 0.0,
        "legal_ir_multiview_cosine_loss": 0.05,
        "legal_ir_multiview_cross_entropy_loss": 0.05,
        "legal_ir_multiview_frame_logic_missing_loss": 0.0,
        "legal_ir_multiview_graph_failure_penalty": 0.0,
        "legal_ir_multiview_proof_failure_ratio": 0.0,
        "legal_ir_multiview_reconstruction_loss": 0.05,
        "legal_ir_multiview_text_reconstruction_loss": 0.0,
        "legal_ir_multiview_total_loss": 0.05,
        "legal_ir_multiview_view_coverage_loss": 0.0,
        "legal_ir_view_cross_entropy_loss": 0.05,
        "modal_span_coverage_loss": 0.0,
        "ontology_violation_count": 0.0,
        "reconstruction_loss": 0.05,
        "source_copy_loss": 0.35,
        "source_copy_reward_hack_penalty": 0.10,
        "structural_text_reconstruction_loss": 0.50,
        "symbolic_validity_penalty": 0.0,
        "tdfol_no_formula_loss": 0.0,
        "tdfol_parse_failure_ratio": 0.0,
        "text_reconstruction_loss": 0.0,
        "zkp_attestation_missing_loss": 0.0,
        "zkp_graph_failure_penalty": 0.0,
        "zkp_proof_failure_ratio": 0.0,
        "zkp_verification_failure_ratio": 0.0,
    }

    def __init__(
        self,
        thresholds: Optional[Mapping[str, float]] = None,
        *,
        policy: Optional[ModalOptimizerPolicy] = None,
    ) -> None:
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update({name: float(value) for name, value in thresholds.items()})
        self.policy = policy or ModalOptimizerPolicy()

    def generate(self, snapshots: Iterable[LossSnapshot]) -> List[ModalTodo]:
        """Generate unique pending TODOs sorted by highest priority first."""
        todos: Dict[str, ModalTodo] = {}
        for snapshot in snapshots:
            for loss_name, loss_value in snapshot.losses.items():
                threshold = self.thresholds.get(loss_name)
                if threshold is None or float(loss_value) <= threshold:
                    continue
                todo = self._todo_for_loss(snapshot, loss_name, float(loss_value))
                todos[todo.todo_id] = todo
            if snapshot.parser_formula_count == 0:
                todo = self._parser_failure_todo(snapshot)
                todos[todo.todo_id] = todo
        return sorted(todos.values(), key=lambda todo: (-todo.priority, todo.todo_id))

    def _todo_for_loss(self, snapshot: LossSnapshot, loss_name: str, loss_value: float) -> ModalTodo:
        action, objective = {
            "cross_entropy_loss": (
                "improve_modal_family_classifier",
                "Add or refine deterministic modal-family cues so the encoder predicts the target family.",
            ),
            "cosine_loss": (
                "improve_encoder_decoder_reconstruction",
                "Tune the text encoder/decoder representation so decoded embeddings stay close by cosine similarity.",
            ),
            "reconstruction_loss": (
                "improve_encoder_decoder_reconstruction",
                "Reduce embedding reconstruction error through a better intermediate representation.",
            ),
            "frame_ranking_loss": (
                "improve_bm25_frame_selector",
                "Add ontology frame vocabulary or weights so the expected frame ranks first.",
            ),
            "legal_ir_view_cross_entropy_loss": (
                "improve_legal_ir_view_distribution",
                "Use SGD to align the adaptive IR view distribution with the canonical multiview LegalIR target.",
            ),
            "flogic_similarity_loss": (
                "improve_flogic_frame_alignment",
                "Refine ontology frame triples or decoded IR text so F-logic semantic similarity improves.",
            ),
            "modal_span_coverage_loss": (
                "increase_modal_ir_span_coverage",
                "Add deterministic parser or IR coverage for source spans preserved as text but not typed as modal logic.",
            ),
            "ontology_violation_count": (
                "repair_flogic_ontology_constraints",
                "Fix F-logic frame triples or ontology signatures that violate deterministic frame constraints.",
            ),
            "symbolic_validity_penalty": (
                "add_deterministic_parser_rule",
                "Add a deterministic parser rule or fixture for legal text that failed symbolic validation.",
            ),
            "text_reconstruction_loss": (
                "refine_semantic_decompiler_reconstruction",
                "Fix deterministic decompiler reconstruction so source semantics survive the IR round trip.",
            ),
            "source_copy_loss": (
                "refine_semantic_decompiler_reconstruction",
                "Reduce provenance-span copying so decompiler quality comes from typed IR slots rather than replayed source text.",
            ),
            "source_copy_reward_hack_penalty": (
                "refine_semantic_decompiler_reconstruction",
                "Penalize round-trip text similarity that is explained by copied source spans instead of typed IR slots.",
            ),
            "structural_text_reconstruction_loss": (
                "refine_semantic_decompiler_reconstruction",
                "Improve structural decompiler text reconstructed from modal/frame/deontic IR slots with copied source spans removed.",
            ),
            "cec_dcec_no_formula_loss": (
                "repair_cec_dcec_bridge",
                "Add or repair CEC/DCEC event-calculus records for legal text with no event formulas.",
            ),
            "cec_dcec_event_formula_invalid_ratio": (
                "repair_cec_dcec_bridge",
                "Repair CEC event-calculus state formulas so bridge exports pass deterministic shape checks.",
            ),
            "cec_dcec_validation_failure_ratio": (
                "repair_cec_dcec_bridge",
                "Improve CEC/DCEC bridge validation so event formulas compile as proof inputs.",
            ),
            "deontic_bridge_evaluation_failure_loss": (
                "repair_deontic_bridge_quality_gate",
                "Fix deontic bridge evaluation so legal text can compile into LegalNormIR diagnostics.",
            ),
            "deontic_decoder_requires_validation_rate": (
                "repair_deontic_bridge_quality_gate",
                "Improve deontic decoder reconstruction rows so LegalNormIR round trips do not require validation.",
            ),
            "deontic_decoder_slot_loss": (
                "repair_deontic_bridge_quality_gate",
                "Recover legally salient deontic slots in decoder reconstruction records.",
            ),
            "deontic_graph_build_error_loss": (
                "repair_deontic_graph_bridge",
                "Repair the deontic graph projection built from LegalNormIR records.",
            ),
            "deontic_graph_conflict_loss": (
                "repair_deontic_graph_bridge",
                "Reduce conflicting deontic graph rules emitted from equivalent LegalNormIR slots.",
            ),
            "deontic_graph_failure_penalty": (
                "repair_deontic_graph_bridge",
                "Project deontic frame logic into Neo4j-compatible graph data without empty graph output.",
            ),
            "deontic_graph_source_gap_loss": (
                "repair_deontic_graph_bridge",
                "Source-ground deontic graph rule support nodes so graph diagnostics stay complete.",
            ),
            "deontic_ir_slot_provenance_loss": (
                "repair_deontic_bridge_quality_gate",
                "Preserve source provenance for legally salient LegalNormIR slots.",
            ),
            "deontic_phase8_quality_incomplete_loss": (
                "repair_deontic_bridge_quality_gate",
                "Complete Phase 8 deontic quality records across decoder, prover syntax, and IR provenance.",
            ),
            "deontic_proof_failure_ratio": (
                "repair_deontic_prover_bridge",
                "Improve deontic prover syntax coverage so LegalNormIR obligations compile cleanly.",
            ),
            "deontic_quality_requires_validation_loss": (
                "repair_deontic_bridge_quality_gate",
                "Promote deontic LegalNormIR and prover syntax outputs from syntax-only to validated bridge reports.",
            ),
            "deontic_repair_queue_rate": (
                "repair_deontic_bridge_quality_gate",
                "Reduce deterministic deontic repair queue rows before emitting proof obligations.",
            ),
            "deontic_repair_required_rate": (
                "repair_deontic_bridge_quality_gate",
                "Reduce deontic parser repair requirements before emitting formal LegalNormIR.",
            ),
            "external_prover_failure_ratio": (
                "repair_external_prover_router",
                "Repair external prover-router proof dispatch for formulas that failed routed validation.",
            ),
            "external_prover_unavailable_loss": (
                "repair_external_prover_router",
                "Wire lazy prover installation and native fallback so at least one prover is available.",
            ),
            "legal_ir_multiview_acceptance_loss": (
                "repair_multiview_legal_ir_acceptance",
                "Repair the canonical multiview LegalIR bridge so every requested logic view accepts the legal text.",
            ),
            "legal_ir_multiview_bridge_evaluation_failure_loss": (
                "repair_multiview_legal_ir_acceptance",
                "Fix a canonical multiview LegalIR evaluation failure before optimizer loss routing.",
            ),
            "legal_ir_multiview_cosine_loss": (
                "repair_multiview_legal_ir_loss",
                "Improve the canonical multiview LegalIR round-trip cosine objective across bridge views.",
            ),
            "legal_ir_multiview_cross_entropy_loss": (
                "repair_multiview_legal_ir_loss",
                "Improve the canonical multiview LegalIR view-family cross-entropy objective.",
            ),
            "legal_ir_multiview_frame_logic_missing_loss": (
                "repair_multiview_legal_ir_view_coverage",
                "Ensure canonical LegalIR contains frame-logic triples across modal and deontic bridge views.",
            ),
            "legal_ir_multiview_graph_failure_penalty": (
                "repair_multiview_legal_ir_graph_projection",
                "Repair canonical LegalIR graph projection into the Neo4j-compatible decentralized KG layer.",
            ),
            "legal_ir_multiview_proof_failure_ratio": (
                "repair_multiview_legal_ir_prover_gate",
                "Repair canonical LegalIR proof-gate routing across local and external theorem provers.",
            ),
            "legal_ir_multiview_reconstruction_loss": (
                "repair_multiview_legal_ir_loss",
                "Improve canonical multiview LegalIR reconstruction across encoder and decoder views.",
            ),
            "legal_ir_multiview_text_reconstruction_loss": (
                "repair_multiview_legal_ir_loss",
                "Improve canonical multiview LegalIR decompiler text reconstruction.",
            ),
            "legal_ir_multiview_total_loss": (
                "repair_multiview_legal_ir_loss",
                "Reduce total canonical multiview LegalIR loss across adapters, proof gates, and graph projections.",
            ),
            "legal_ir_multiview_view_coverage_loss": (
                "repair_multiview_legal_ir_view_coverage",
                "Fill missing canonical LegalIR views so modal, deontic, TDFOL, CEC, frame, and prover outputs stay coherent.",
            ),
            "tdfol_no_formula_loss": (
                "repair_tdfol_bridge_parse",
                "Add or repair TDFOL formula construction for legal text with no proof obligations.",
            ),
            "tdfol_parse_failure_ratio": (
                "repair_tdfol_bridge_parse",
                "Improve TDFOL parser compatibility so bridge formulas compile into prover inputs.",
            ),
            "zkp_attestation_missing_loss": (
                "repair_zkp_attestation_bridge",
                "Wire formal proof obligations into ZKP attestation records for the canonical LegalIR.",
            ),
            "zkp_graph_failure_penalty": (
                "repair_zkp_attestation_bridge",
                "Repair ZKP attestation graph records so proof evidence imports into the Neo4j-compatible graph layer.",
            ),
            "zkp_proof_failure_ratio": (
                "repair_zkp_attestation_bridge",
                "Repair ZKP proof-attestation verification so proof records satisfy the circuit bridge.",
            ),
            "zkp_verification_failure_ratio": (
                "repair_zkp_attestation_bridge",
                "Repair ZKP proof verification so generated proof attestations validate deterministically.",
            ),
        }.get(
            loss_name,
            (
                "inspect_modal_loss_regression",
                "Inspect the sample and add a parser, encoder, decoder, or frame-selector improvement.",
            ),
        )
        return self._build_todo(snapshot, action, objective, loss_name, loss_value)

    def _parser_failure_todo(self, snapshot: LossSnapshot) -> ModalTodo:
        return self._build_todo(
            snapshot,
            "add_deterministic_parser_rule",
            "Create a golden parser case for legal text that produced no modal formulas.",
            "parser_formula_count",
            1.0,
        )

    def _build_todo(
        self,
        snapshot: LossSnapshot,
        action: str,
        objective: str,
        loss_name: str,
        loss_value: float,
    ) -> ModalTodo:
        priority = round((loss_value * 100.0) + snapshot.total_loss(), 6)
        todo_id = _todo_id(action, snapshot.sample_id, loss_name, loss_value)
        target_component = PROGRAM_SYNTHESIS_ACTION_TARGETS.get(action)
        metadata = {
            **self.policy.metadata_for(action=action, loss_name=loss_name),
            "selected_frame": snapshot.selected_frame,
            "source": "modal_loss_todo_generator_v1",
        }
        if target_component:
            metadata["target_component"] = target_component
        if (
            action == "repair_multiview_legal_ir_loss"
            and target_component == "bridge.contracts"
            and _snapshot_has_component_specific_program_loss(snapshot)
        ):
            priority = round(priority * 0.35, 6)
            metadata["generic_bridge_priority_backoff"] = True
        if metadata.get("optimizer_role") == PROGRAM_SYNTHESIS_ROLE:
            metadata["program_synthesis_scope"] = _program_synthesis_scope(
                action=action,
                target_component=str(target_component or ""),
            )
            metadata["dedupe_signature"] = _program_todo_signature(
                action=action,
                target_component=str(target_component or ""),
                sample_ids=[snapshot.sample_id],
            )
            metadata["semantic_bundle_key"] = _program_todo_bundle_signature(
                action=action,
                target_component=str(target_component or ""),
                program_synthesis_scope=str(metadata["program_synthesis_scope"]),
                family_pairs=[],
            )
            metadata["target_metrics"] = _program_synthesis_target_metrics(
                action=action,
                target_component=str(target_component or ""),
            )
            metadata["validation_commands"] = _program_synthesis_validation_commands(
                action=action,
                target_component=str(target_component or ""),
                program_synthesis_scope=str(metadata["program_synthesis_scope"]),
            )
        return ModalTodo(
            todo_id=todo_id,
            action=action,
            objective=objective,
            sample_ids=[snapshot.sample_id],
            citations=[snapshot.citation],
            loss_name=loss_name,
            loss_value=round(loss_value, 12),
            priority=priority,
            metadata=metadata,
        )


def _snapshot_has_component_specific_program_loss(snapshot: LossSnapshot) -> bool:
    """Return true when a broad LegalIR TODO would duplicate a narrower repair."""
    specific_loss_names = {
        "legal_ir_multiview_graph_failure_penalty",
        "legal_ir_multiview_proof_failure_ratio",
    }
    specific_prefixes = (
        "cec_",
        "deontic_",
        "external_prover_",
        "tdfol_",
        "zkp_",
    )
    for loss_name, value in dict(snapshot.losses or {}).items():
        if float(value or 0.0) <= 0.0:
            continue
        normalized = str(loss_name)
        if normalized in specific_loss_names or normalized.startswith(specific_prefixes):
            return True
    return False


class ModalProgramSynthesisTodoGenerator:
    """Create Codex/program-repair TODOs from stable autoencoder residual hints."""

    def __init__(
        self,
        *,
        policy: Optional[ModalOptimizerPolicy] = None,
        min_support: Optional[int] = None,
    ) -> None:
        self.policy = policy or ModalOptimizerPolicy()
        self.min_support = (
            self.policy.program_synthesis_min_support
            if min_support is None
            else int(min_support)
        )

    def generate(
        self,
        samples: Sequence[LegalSample],
        *,
        autoencoder: AdaptiveModalAutoencoder,
    ) -> List[ModalTodo]:
        """Generate program-repair TODOs only for repeated interpretable hints."""
        if not self.policy.enable_program_synthesis_todos:
            return []
        sample_list = list(samples)
        if not sample_list:
            return []

        samples_by_id = {sample.sample_id: sample for sample in sample_list}
        introspections = [
            autoencoder.introspect_sample(sample, use_sample_memory=False).to_dict()
            for sample in sample_list
        ]
        hints = synthesis_hints_from_autoencoder_introspections(introspections)
        clusters: Dict[tuple[str, str], List[ModalProgramSynthesisHint]] = {}
        for hint in hints:
            clusters.setdefault((hint.action, hint.target_component), []).append(hint)

        todos: List[ModalTodo] = []
        min_support = max(1, self.min_support)
        for (action, target_component), cluster in sorted(clusters.items()):
            sample_ids = _unique_preserve_order(
                str(hint.evidence.get("sample_id") or _sample_id_from_hint(hint))
                for hint in cluster
            )
            sample_ids = [sample_id for sample_id in sample_ids if sample_id]
            if len(sample_ids) < min_support:
                continue
            citations = _unique_preserve_order(
                samples_by_id[sample_id].citation
                for sample_id in sample_ids
                if sample_id in samples_by_id
            )
            priority = sum(float(hint.priority) for hint in cluster) / len(cluster)
            representative = max(cluster, key=lambda hint: (hint.priority, hint.hint_id))
            dedupe_signature = _program_todo_signature(
                action=action,
                target_component=target_component,
                sample_ids=sample_ids,
            )
            hint_evidence = [
                _compact_hint_evidence(hint)
                for hint in sorted(cluster, key=lambda hint: hint.hint_id)
            ]
            residual_signatures = _unique_preserve_order(
                residual_signature_for_hint(hint)
                for hint in sorted(cluster, key=lambda hint: hint.hint_id)
            )
            program_synthesis_scope = _program_synthesis_scope(
                action=action,
                target_component=target_component,
            )
            metadata = {
                **self.policy.metadata_for(
                    action=action,
                    loss_name="autoencoder_residual_cluster",
                ),
                "hint_ids": sorted(hint.hint_id for hint in cluster),
                "dedupe_signature": dedupe_signature,
                "program_synthesis_scope": program_synthesis_scope,
                "hint_evidence": hint_evidence,
                "residual_signatures": residual_signatures,
                "source": "modal_program_synthesis_todo_generator_v1",
                "support_count": len(sample_ids),
                "target_component": target_component,
            }
            metadata["target_metrics"] = _program_synthesis_target_metrics(
                action=action,
                target_component=target_component,
            )
            metadata["validation_commands"] = _program_synthesis_validation_commands(
                action=action,
                target_component=target_component,
                program_synthesis_scope=program_synthesis_scope,
            )
            metadata["metric_sample_payloads"] = _program_synthesis_sample_payloads(
                sample_ids,
                samples_by_id=samples_by_id,
            )
            metadata["residual_cluster_stage"] = "post_sgd_or_current_state"
            metadata["semantic_bundle_key"] = _program_todo_bundle_signature(
                action=action,
                target_component=target_component,
                program_synthesis_scope=program_synthesis_scope,
                family_pairs=_program_todo_family_pairs_from_evidence(hint_evidence),
            )
            todo = ModalTodo(
                todo_id=_program_todo_id(
                    action=action,
                    target_component=target_component,
                    sample_ids=sample_ids,
                ),
                action=action,
                objective=representative.rationale,
                sample_ids=sample_ids,
                citations=citations,
                loss_name="autoencoder_residual_cluster",
                loss_value=round(priority, 12),
                priority=round((priority * 100.0) + len(sample_ids), 6),
                metadata=metadata,
            )
            todos.append(todo)
        return sorted(todos, key=lambda todo: (-todo.priority, todo.todo_id))


class ModalTodoQueue:
    """Small JSONL-friendly queue that can claim multiple TODOs at once."""

    def __init__(self, todos: Optional[Iterable[ModalTodo]] = None) -> None:
        self._todos: Dict[str, ModalTodo] = {}
        if todos:
            self.add_many(todos)

    def add_many(self, todos: Iterable[ModalTodo]) -> int:
        """Add TODOs by id, returning the number of new items."""
        added = 0
        for todo in todos:
            if todo.todo_id in self._todos:
                continue
            duplicate = self.find_semantic_duplicate(todo)
            if duplicate is not None:
                _merge_program_todo_evidence(duplicate, todo)
                continue
            self._todos[todo.todo_id] = todo
            added += 1
        return added

    def find_semantic_duplicate(
        self,
        todo: ModalTodo,
        *,
        optimizer_role: Optional[str] = None,
        near_duplicate_jaccard: float = PROGRAM_SYNTHESIS_NEAR_DUPLICATE_JACCARD,
        include_bundle_key: bool = False,
    ) -> Optional[ModalTodo]:
        """Return existing program-repair TODO that already covers ``todo``."""
        role = optimizer_role or _todo_optimizer_role(todo)
        if role != PROGRAM_SYNTHESIS_ROLE:
            return None
        for existing in self._todos.values():
            if _todo_optimizer_role(existing) != role:
                continue
            if existing.todo_id == todo.todo_id:
                return existing
            if _program_todos_near_duplicate(
                existing,
                todo,
                jaccard_threshold=near_duplicate_jaccard,
            ):
                return existing
            if include_bundle_key and _program_todos_share_semantic_bundle(existing, todo):
                return existing
        return None

    def merge_from(
        self,
        other: "ModalTodoQueue",
        *,
        preserve_claimed_role: Optional[str] = None,
    ) -> None:
        """Merge another queue while preserving external role progress."""
        for todo in other.all():
            existing = self._todos.get(todo.todo_id)
            if (
                existing is not None
                and preserve_claimed_role is not None
                and _todo_optimizer_role(existing) == preserve_claimed_role
                and TODO_STATUS_RANK.get(existing.status, 0)
                >= TODO_STATUS_RANK.get(todo.status, 0)
                and existing.status != "pending"
            ):
                continue
            self._todos[todo.todo_id] = todo

    def has_semantic_duplicate(
        self,
        todo: ModalTodo,
        *,
        optimizer_role: Optional[str] = None,
        near_duplicate_jaccard: float = PROGRAM_SYNTHESIS_NEAR_DUPLICATE_JACCARD,
        include_bundle_key: bool = False,
    ) -> bool:
        """Return whether a queue item already covers the same synthesis work."""
        return self.find_semantic_duplicate(
            todo,
            optimizer_role=optimizer_role,
            near_duplicate_jaccard=near_duplicate_jaccard,
            include_bundle_key=include_bundle_key,
        ) is not None

    def deduplicate_semantic(
        self,
        *,
        optimizer_role: str = PROGRAM_SYNTHESIS_ROLE,
        near_duplicate_jaccard: float = PROGRAM_SYNTHESIS_NEAR_DUPLICATE_JACCARD,
    ) -> int:
        """Remove exact and near-duplicate program-synthesis TODOs."""
        kept: List[ModalTodo] = []
        removed_ids: List[str] = []
        for todo in sorted(
            self._todos.values(),
            key=lambda item: (
                -PROGRAM_SYNTHESIS_DEDUPE_KEEP_RANK.get(item.status, 0),
                -item.priority,
                item.created_at,
                item.todo_id,
            ),
        ):
            if _todo_optimizer_role(todo) != optimizer_role:
                kept.append(todo)
                continue
            duplicate = any(
                _program_todos_duplicate_for_repair(
                    existing,
                    todo,
                    jaccard_threshold=near_duplicate_jaccard,
                )
                for existing in kept
                if _todo_optimizer_role(existing) == optimizer_role
            )
            if duplicate:
                representative = next(
                    existing
                    for existing in kept
                    if _todo_optimizer_role(existing) == optimizer_role
                    and _program_todos_duplicate_for_repair(
                        existing,
                        todo,
                        jaccard_threshold=near_duplicate_jaccard,
                    )
                )
                _merge_program_todo_evidence(representative, todo)
                removed_ids.append(todo.todo_id)
            else:
                kept.append(todo)
        if not removed_ids:
            return 0
        self._todos = {todo.todo_id: todo for todo in kept}
        return len(removed_ids)

    def find_autoencoder_duplicate(
        self,
        todo: ModalTodo,
        *,
        optimizer_role: str = AUTOENCODER_SGD_ROLE,
    ) -> Optional[ModalTodo]:
        """Return an existing trainable TODO that covers the same optimizer work."""
        signature = _autoencoder_todo_signature(todo)
        if not signature:
            return None
        for existing in self._todos.values():
            if _todo_optimizer_role(existing) != optimizer_role:
                continue
            if _autoencoder_todo_signature(existing) == signature:
                return existing
        return None

    def deduplicate_autoencoder(
        self,
        *,
        optimizer_role: str = AUTOENCODER_SGD_ROLE,
    ) -> int:
        """Collapse duplicate autoencoder SGD TODOs into batchable representatives."""
        kept: List[ModalTodo] = []
        removed_ids: List[str] = []
        for todo in sorted(
            self._todos.values(),
            key=lambda item: (
                -AUTOENCODER_DEDUPE_KEEP_RANK.get(item.status, 0),
                -item.priority,
                item.created_at,
                item.todo_id,
            ),
        ):
            if _todo_optimizer_role(todo) != optimizer_role:
                kept.append(todo)
                continue
            signature = _autoencoder_todo_signature(todo)
            duplicate = next(
                (
                    existing
                    for existing in kept
                    if _todo_optimizer_role(existing) == optimizer_role
                    and _autoencoder_todo_signature(existing) == signature
                ),
                None,
            )
            if duplicate is None:
                todo.metadata["autoencoder_bundle_signature"] = signature
                kept.append(todo)
                continue
            _merge_autoencoder_todo_evidence(duplicate, todo)
            removed_ids.append(todo.todo_id)
        if not removed_ids:
            return 0
        self._todos = {todo.todo_id: todo for todo in kept}
        return len(removed_ids)

    def compact_autoencoder_backlog(
        self,
        *,
        optimizer_role: str = AUTOENCODER_SGD_ROLE,
        retire_failed_validation: bool = True,
    ) -> Dict[str, int]:
        """Compact transient autoencoder SGD backlog while preserving Codex work."""
        before = self.role_status_counts()
        before_role = before.get(optimizer_role, {})
        before_total = sum(before_role.values())
        program_before = sum(before.get(PROGRAM_SYNTHESIS_ROLE, {}).values())

        deduped = self.deduplicate_autoencoder(optimizer_role=optimizer_role)
        retired_failed_validation = 0
        if retire_failed_validation:
            retired_ids = [
                todo.todo_id
                for todo in self._todos.values()
                if _todo_optimizer_role(todo) == optimizer_role
                and todo.status == "failed_validation"
            ]
            for todo_id in retired_ids:
                self._todos.pop(todo_id, None)
            retired_failed_validation = len(retired_ids)

        after = self.role_status_counts()
        after_role = after.get(optimizer_role, {})
        after_total = sum(after_role.values())
        program_after = sum(after.get(PROGRAM_SYNTHESIS_ROLE, {}).values())
        return {
            "after_autoencoder_total": after_total,
            "before_autoencoder_total": before_total,
            "compacted_count": deduped,
            "pending_after": int(after_role.get("pending", 0)),
            "pending_before": int(before_role.get("pending", 0)),
            "preserved_program_synthesis_count": program_after,
            "program_synthesis_count_before": program_before,
            "retired_failed_validation_count": retired_failed_validation,
        }

    def pending(self, *, optimizer_role: Optional[str] = None) -> List[ModalTodo]:
        return self._by_priority(status="pending", optimizer_role=optimizer_role)

    def claimed(self, *, optimizer_role: Optional[str] = None) -> List[ModalTodo]:
        return self._by_priority(status="claimed", optimizer_role=optimizer_role)

    def all(self) -> List[ModalTodo]:
        return sorted(self._todos.values(), key=_todo_priority_key)

    def get(self, todo_id: str) -> Optional[ModalTodo]:
        return self._todos.get(todo_id)

    def pending_count(self, *, optimizer_role: Optional[str] = None) -> int:
        """Return pending queue depth without materializing a sorted TODO list."""
        return self._count(status="pending", optimizer_role=optimizer_role)

    def claimed_count(self, *, optimizer_role: Optional[str] = None) -> int:
        """Return open claimed queue depth without materializing a sorted TODO list."""
        return self._count(status="claimed", optimizer_role=optimizer_role)

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for todo in self._todos.values():
            counts[todo.status] = counts.get(todo.status, 0) + 1
        return dict(sorted(counts.items()))

    def role_status_counts(self) -> Dict[str, Dict[str, int]]:
        """Return queue counts grouped by optimizer role and status."""
        counts: Dict[str, Dict[str, int]] = {}
        for todo in self._todos.values():
            role = _todo_optimizer_role(todo)
            role_counts = counts.setdefault(role, {})
            role_counts[todo.status] = role_counts.get(todo.status, 0) + 1
        return {
            role: dict(sorted(role_counts.items()))
            for role, role_counts in sorted(counts.items())
        }

    def claim_batch(
        self,
        *,
        worker_id: str,
        max_items: int,
        optimizer_role: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        """Claim up to ``max_items`` pending TODOs for one worker."""
        if max_items < 1:
            return []
        claimed: List[ModalTodo] = []
        for todo in self._top_by_priority(
            status="pending",
            optimizer_role=optimizer_role,
            metadata_filter=metadata_filter,
            max_items=max_items,
        ):
            todo.claim(worker_id)
            claimed.append(todo)
        return claimed

    def claim_todo_ids(
        self,
        *,
        worker_id: str,
        todo_ids: Sequence[str],
        optimizer_role: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        """Claim pending TODOs by id while still enforcing role/scope filters."""
        claimed: List[ModalTodo] = []
        for todo_id in todo_ids:
            todo = self._todos.get(str(todo_id))
            if todo is None:
                continue
            if not _todo_matches(
                todo,
                status="pending",
                optimizer_role=optimizer_role,
                metadata_filter=metadata_filter,
            ):
                continue
            todo.claim(worker_id)
            claimed.append(todo)
        return claimed

    def claim_semantic_bundle(
        self,
        *,
        worker_id: str,
        max_items: int,
        optimizer_role: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        """Claim a priority anchor plus semantically similar pending TODOs."""
        if max_items < 1:
            return []
        candidates = self._by_priority(
            status="pending",
            optimizer_role=optimizer_role,
            metadata_filter=metadata_filter,
        )
        if not candidates:
            return []

        anchor = candidates[0]
        anchor_key = _program_todo_semantic_bundle_key(anchor)
        anchor_scope = _program_todo_scope(anchor)
        anchor_target = _todo_target_component(anchor)
        claimed = [anchor]
        for todo in candidates[1:]:
            if len(claimed) >= max_items:
                break
            todo_key = _program_todo_semantic_bundle_key(todo)
            same_exact_bundle = todo_key == anchor_key
            same_ast_lane = (
                _program_todo_scope(todo) == anchor_scope
                and _todo_target_component(todo) == anchor_target
            )
            if not same_exact_bundle and not same_ast_lane:
                continue
            claimed.append(todo)

        anchor_id = anchor.todo_id
        for todo in claimed:
            todo.metadata["semantic_bundle_anchor_id"] = anchor_id
            todo.metadata["semantic_bundle_reason"] = (
                "same_semantic_bundle_key"
                if _program_todo_semantic_bundle_key(todo) == anchor_key
                else "same_ast_scope_and_target_component"
            )
            todo.claim(worker_id)
        return claimed

    def claim_vector_bundle(
        self,
        *,
        worker_id: str,
        max_items: int,
        vectors_by_todo_id: Mapping[str, Sequence[float]],
        min_similarity: float = 0.72,
        optimizer_role: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        """Claim a priority anchor plus vector-nearest TODOs in the same AST scope."""
        candidates = self._by_priority(
            status="pending",
            optimizer_role=optimizer_role,
            metadata_filter=metadata_filter,
        )
        selected = select_program_synthesis_vector_bundle(
            candidates,
            vectors_by_todo_id=vectors_by_todo_id,
            max_items=max_items,
            min_similarity=min_similarity,
        )
        claimed: List[ModalTodo] = []
        anchor_id = selected[0]["todo"].todo_id if selected else ""
        for item in selected:
            todo = item["todo"]
            todo.metadata["vector_bundle_anchor_id"] = anchor_id
            todo.metadata["vector_bundle_similarity"] = round(float(item["similarity"]), 6)
            todo.claim(worker_id)
            claimed.append(todo)
        return claimed

    def complete(self, todo_id: str) -> bool:
        todo = self._todos.get(todo_id)
        if todo is None:
            return False
        todo.complete()
        return True

    def fail_validation(self, todo_id: str, *, reason: str) -> bool:
        todo = self._todos.get(todo_id)
        if todo is None:
            return False
        todo.fail_validation(reason)
        return True

    def save_jsonl(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(todo.to_json() for todo in self.all()) + "\n", encoding="utf-8")

    @classmethod
    def load_jsonl(cls, path: str | Path) -> "ModalTodoQueue":
        source = Path(path)
        if not source.exists():
            return cls()
        queue = cls()
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            todo = ModalTodo.from_dict(json.loads(line))
            if todo.todo_id not in queue._todos:
                queue._todos[todo.todo_id] = todo
        return queue

    def _by_priority(
        self,
        *,
        status: str,
        optimizer_role: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        return sorted(
            (
                todo
                for todo in self._todos.values()
                if _todo_matches(
                    todo,
                    status=status,
                    optimizer_role=optimizer_role,
                    metadata_filter=metadata_filter,
                )
            ),
            key=_todo_priority_key,
        )

    def _top_by_priority(
        self,
        *,
        status: str,
        optimizer_role: Optional[str],
        max_items: int,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        candidates = (
            todo
            for todo in self._todos.values()
            if _todo_matches(
                todo,
                status=status,
                optimizer_role=optimizer_role,
                metadata_filter=metadata_filter,
            )
        )
        return heapq.nsmallest(max_items, candidates, key=_todo_priority_key)

    def _count(self, *, status: str, optimizer_role: Optional[str] = None) -> int:
        return sum(
            1
            for todo in self._todos.values()
            if _todo_matches(todo, status=status, optimizer_role=optimizer_role)
        )


class ModalTodoSupervisor:
    """Coordinator that seeds TODOs from samples/evaluations and claims batches."""

    def __init__(
        self,
        *,
        queue: Optional[ModalTodoQueue] = None,
        generator: Optional[ModalLossTodoGenerator] = None,
        policy: Optional[ModalOptimizerPolicy] = None,
        program_synthesis_generator: Optional[ModalProgramSynthesisTodoGenerator] = None,
        bridge_loss_evaluator: Optional[BridgeLossEvaluator] = None,
        bridge_names: Sequence[str] = (),
        bridge_evaluate_provers: Optional[bool] = None,
    ) -> None:
        self.policy = policy or ModalOptimizerPolicy()
        self.queue = queue or ModalTodoQueue()
        self.generator = generator or ModalLossTodoGenerator(policy=self.policy)
        self.program_synthesis_generator = (
            program_synthesis_generator
            or ModalProgramSynthesisTodoGenerator(policy=self.policy)
        )
        self.bridge_names = tuple(
            dict.fromkeys(
                str(name).strip()
                for name in bridge_names
                if str(name).strip()
                and str(name).strip().lower() not in {"none", "off", "false"}
            )
        )
        self.bridge_evaluate_provers = bridge_evaluate_provers
        self.bridge_loss_evaluator = (
            bridge_loss_evaluator
            if bridge_loss_evaluator is not None
            else (
                bridge_loss_evaluator_for_names(
                    self.bridge_names,
                    evaluate_provers=self.bridge_evaluate_provers,
                )
                if self.bridge_names
                else None
            )
        )
        self.last_bridge_loss_failure_count = 0
        self.last_bridge_loss_sample_count = 0
        self.last_bridge_loss_signal_count = 0
        self.last_program_synthesis_deduped_count = 0

    def seed_from_evaluation(
        self,
        samples: Sequence[LegalSample],
        *,
        autoencoder: Optional[AutoencoderEvaluation] = None,
    ) -> List[ModalTodo]:
        """Generate TODOs from a batch and add them to the queue."""
        sample_list = list(samples)
        bridge_losses_by_sample = self._bridge_losses_for_samples(sample_list)
        snapshots = [
            LossSnapshot.from_sample(
                sample,
                autoencoder=autoencoder,
                extra_losses=bridge_losses_by_sample.get(sample.sample_id, {}),
            )
            for sample in sample_list
        ]
        todos = self._bounded_new_todos(self.generator.generate(snapshots))
        self.queue.add_many(todos)
        return todos

    def _bridge_losses_for_samples(
        self,
        samples: Sequence[LegalSample],
    ) -> Dict[str, Dict[str, float]]:
        self.last_bridge_loss_failure_count = 0
        self.last_bridge_loss_sample_count = 0
        self.last_bridge_loss_signal_count = 0
        if self.bridge_loss_evaluator is None:
            return {}
        try:
            raw = self.bridge_loss_evaluator(samples)
        except Exception:
            return {}
        normalized: Dict[str, Dict[str, float]] = {}
        for sample_id, losses in dict(raw or {}).items():
            if not isinstance(losses, Mapping):
                continue
            normalized_losses = {
                str(name): _safe_float(value)
                for name, value in losses.items()
            }
            normalized_losses = {
                name: value
                for name, value in normalized_losses.items()
                if value != 0.0
            }
            if normalized_losses:
                normalized[str(sample_id)] = dict(sorted(normalized_losses.items()))
        self.last_bridge_loss_sample_count = len(normalized)
        self.last_bridge_loss_signal_count = sum(len(losses) for losses in normalized.values())
        self.last_bridge_loss_failure_count = sum(
            1
            for losses in normalized.values()
            for name, value in losses.items()
            if name.endswith("_bridge_evaluation_failure_loss") and value > 0.0
        )
        return normalized

    def _autoencoder_evaluation(
        self,
        autoencoder: AdaptiveModalAutoencoder,
        samples: Sequence[LegalSample],
        *,
        use_sample_memory: bool = True,
    ) -> AutoencoderEvaluation:
        kwargs: Dict[str, Any] = {"use_sample_memory": use_sample_memory}
        if self.bridge_names:
            kwargs["legal_ir_bridge_names"] = self.bridge_names
            kwargs["legal_ir_evaluate_provers"] = self.bridge_evaluate_provers
        return autoencoder.evaluate(list(samples), **kwargs)

    def seed_program_synthesis_from_introspection(
        self,
        samples: Sequence[LegalSample],
        *,
        autoencoder: AdaptiveModalAutoencoder,
        residual_before: Optional[AutoencoderEvaluation] = None,
        residual_after: Optional[AutoencoderEvaluation] = None,
        residual_stage: str = "current_state",
        require_residual_survival: bool = False,
    ) -> List[ModalTodo]:
        """Seed Codex/program-repair TODOs from stable autoencoder evidence."""
        todos = self.program_synthesis_generator.generate(
            list(samples),
            autoencoder=autoencoder,
        )
        if residual_before is not None and residual_after is not None:
            annotated: List[ModalTodo] = []
            for todo in todos:
                survives = _annotate_post_sgd_residual_evidence(
                    todo,
                    before=residual_before,
                    after=residual_after,
                    residual_stage=residual_stage,
                )
                signature_occurrences = self._residual_signature_occurrences(todo)
                todo.metadata["residual_signature_occurrences"] = signature_occurrences
                min_occurrences = max(
                    1,
                    int(self.policy.program_synthesis_min_residual_occurrences),
                )
                survival_score = _safe_float(
                    todo.metadata.get("post_sgd_residual_survival_score", 0.0)
                )
                min_survival_score = max(
                    0.0,
                    float(self.policy.program_synthesis_min_residual_survival_score),
                )
                persistent = signature_occurrences >= min_occurrences
                sufficiently_surviving = survival_score >= min_survival_score
                todo.metadata["post_sgd_residual_persistent"] = persistent
                todo.metadata["post_sgd_residual_survival_gate_passed"] = (
                    sufficiently_surviving
                )
                if not require_residual_survival:
                    annotated.append(todo)
                    continue
                if survives and persistent and sufficiently_surviving:
                    annotated.append(todo)
            todos = annotated
        self.last_program_synthesis_deduped_count = 0
        todos = self._bounded_new_todos(todos, track_program_deduped=True)
        self.queue.add_many(todos)
        return todos

    def _residual_signature_occurrences(self, todo: ModalTodo) -> int:
        signatures = {
            str(signature)
            for signature in _as_list(todo.metadata.get("residual_signatures", []))
            if str(signature)
        }
        if not signatures:
            return 1
        matches = 1
        for existing in self.queue.all():
            existing_signatures = {
                str(signature)
                for signature in _as_list(
                    existing.metadata.get("residual_signatures", [])
                )
                if str(signature)
            }
            if signatures.intersection(existing_signatures):
                matches += 1
        return matches

    def compact_autoencoder_backlog(
        self,
        *,
        retire_failed_validation: bool = True,
    ) -> Dict[str, int]:
        """Compact transient autoencoder SGD work without touching Codex TODOs."""
        return self.queue.compact_autoencoder_backlog(
            optimizer_role=self.policy.autoencoder_role,
            retire_failed_validation=retire_failed_validation,
        )

    def _bounded_new_todos(
        self,
        todos: Iterable[ModalTodo],
        *,
        track_program_deduped: bool = False,
    ) -> List[ModalTodo]:
        """Drop duplicates and keep program-repair work within the pending cap."""
        todos = _coalesce_autoencoder_todos(
            list(todos),
            optimizer_role=self.policy.autoencoder_role,
        )
        autoencoder_capacity = max(
            0,
            int(self.policy.max_autoencoder_pending)
            - self.queue.pending_count(
                optimizer_role=self.policy.autoencoder_role,
            ),
        )
        program_capacity = max(
            0,
            int(self.policy.max_program_synthesis_pending)
            - self.queue.pending_count(
                optimizer_role=self.policy.program_synthesis_role,
            ),
        )
        selected: List[ModalTodo] = []
        program_deduped_count = 0
        for todo in todos:
            role = _todo_optimizer_role(todo)
            if self.queue.get(todo.todo_id) is not None:
                if track_program_deduped and role == self.policy.program_synthesis_role:
                    program_deduped_count += 1
                continue
            if role == self.policy.autoencoder_role:
                duplicate = self.queue.find_autoencoder_duplicate(
                    todo,
                    optimizer_role=self.policy.autoencoder_role,
                )
                if duplicate is not None:
                    if duplicate.status == "pending":
                        _merge_autoencoder_todo_evidence(duplicate, todo)
                    continue
                duplicate = next(
                    (
                        existing
                        for existing in selected
                        if _todo_optimizer_role(existing) == self.policy.autoencoder_role
                        and _autoencoder_todo_signature(existing)
                        == _autoencoder_todo_signature(todo)
                    ),
                    None,
                )
                if duplicate is not None:
                    _merge_autoencoder_todo_evidence(duplicate, todo)
                    continue
                if autoencoder_capacity < 1:
                    continue
                autoencoder_capacity -= 1
            if role == self.policy.program_synthesis_role:
                duplicate = self.queue.find_semantic_duplicate(
                    todo,
                    optimizer_role=self.policy.program_synthesis_role,
                    near_duplicate_jaccard=self.policy.program_synthesis_near_duplicate_jaccard,
                    include_bundle_key=True,
                )
                if duplicate is not None:
                    _merge_program_todo_evidence(duplicate, todo)
                    if track_program_deduped:
                        program_deduped_count += 1
                    continue
                selected_duplicate = next(
                    (
                        existing
                        for existing in selected
                        if _todo_optimizer_role(existing) == self.policy.program_synthesis_role
                        and _program_todos_duplicate_for_repair(
                            existing,
                            todo,
                            jaccard_threshold=self.policy.program_synthesis_near_duplicate_jaccard,
                        )
                    ),
                    None,
                )
                if selected_duplicate is not None:
                    _merge_program_todo_evidence(selected_duplicate, todo)
                    if track_program_deduped:
                        program_deduped_count += 1
                    continue
                if program_capacity < 1:
                    continue
                program_capacity -= 1
            selected.append(todo)
        if track_program_deduped:
            self.last_program_synthesis_deduped_count = program_deduped_count
        return selected

    def claim_next_batch(
        self,
        *,
        worker_id: str,
        max_items: int,
        optimizer_role: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, str]] = None,
    ) -> List[ModalTodo]:
        return self.queue.claim_batch(
            worker_id=worker_id,
            max_items=max_items,
            optimizer_role=optimizer_role,
            metadata_filter=metadata_filter,
        )

    def claim_program_synthesis_batch(
        self,
        *,
        worker_id: str,
        max_items: int,
        program_synthesis_scope: Optional[str] = None,
        semantic_bundle: bool = False,
        vector_bundle: bool = False,
        vectors_by_todo_id: Optional[Mapping[str, Sequence[float]]] = None,
        vector_min_similarity: float = 0.72,
    ) -> List[ModalTodo]:
        """Claim reviewable deterministic repair TODOs for an external Codex worker."""
        metadata_filter = (
            {"program_synthesis_scope": program_synthesis_scope}
            if program_synthesis_scope
            else None
        )
        if vector_bundle:
            return self.queue.claim_vector_bundle(
                worker_id=worker_id,
                max_items=max_items,
                vectors_by_todo_id=vectors_by_todo_id or {},
                min_similarity=vector_min_similarity,
                optimizer_role=self.policy.program_synthesis_role,
                metadata_filter=metadata_filter,
            )
        if semantic_bundle:
            return self.queue.claim_semantic_bundle(
                worker_id=worker_id,
                max_items=max_items,
                optimizer_role=self.policy.program_synthesis_role,
                metadata_filter=metadata_filter,
            )
        return self.claim_next_batch(
            worker_id=worker_id,
            max_items=max_items,
            optimizer_role=self.policy.program_synthesis_role,
            metadata_filter=metadata_filter,
        )

    def role_status(
        self,
        *,
        optimizer_role: str,
        execution_mode: str,
    ) -> Dict[str, Any]:
        """Return queue counters for one optimizer role."""
        counts = self.queue.role_status_counts().get(optimizer_role, {})
        return {
            "claimed": int(counts.get("claimed", 0)),
            "completed": int(counts.get("completed", 0)),
            "execution_mode": execution_mode,
            "failed_validation": int(counts.get("failed_validation", 0)),
            "pending": int(counts.get("pending", 0)),
        }

    def program_synthesis_status(
        self,
        *,
        execution_mode: str = "queued_for_external_codex_worker",
    ) -> Dict[str, Any]:
        """Return queue counters for program-synthesis TODOs."""
        return self.role_status(
            optimizer_role=self.policy.program_synthesis_role,
            execution_mode=execution_mode,
        )

    def autoencoder_status(
        self,
        *,
        execution_mode: str = "adaptive_autoencoder_sgd",
    ) -> Dict[str, Any]:
        """Return queue counters for transient autoencoder SGD TODOs."""
        return self.role_status(
            optimizer_role=self.policy.autoencoder_role,
            execution_mode=execution_mode,
        )

    def update_optimizer_queue_summary(
        self,
        summary: Dict[str, Any],
        *,
        autoencoder_execution_mode: str = "adaptive_autoencoder_sgd",
        program_execution_mode: str = "queued_for_external_codex_worker",
    ) -> Dict[str, Dict[str, Any]]:
        """Apply both optimizer-role counters onto a run summary mapping."""
        auto_status = self.autoencoder_status(execution_mode=autoencoder_execution_mode)
        program_status = self.program_synthesis_status(execution_mode=program_execution_mode)
        for prefix, status in (
            ("autoencoder_sgd", auto_status),
            ("program_synthesis", program_status),
        ):
            summary[f"{prefix}_pending"] = status["pending"]
            summary[f"{prefix}_claimed"] = status["claimed"]
            summary[f"{prefix}_completed"] = status["completed"]
            summary[f"{prefix}_failed_validation"] = status["failed_validation"]
            summary[f"{prefix}_execution_mode"] = status["execution_mode"]
        return {
            "autoencoder_sgd": auto_status,
            "program_synthesis": program_status,
        }

    def update_program_synthesis_summary(
        self,
        summary: Dict[str, Any],
        *,
        execution_mode: str = "queued_for_external_codex_worker",
    ) -> Dict[str, Any]:
        """Apply program-synthesis queue counters onto a run summary mapping."""
        status = self.program_synthesis_status(execution_mode=execution_mode)
        summary["program_synthesis_pending"] = status["pending"]
        summary["program_synthesis_claimed"] = status["claimed"]
        summary["program_synthesis_completed"] = status["completed"]
        summary["program_synthesis_failed_validation"] = status["failed_validation"]
        summary["codex_program_synthesis_execution_mode"] = status["execution_mode"]
        return status

    def finalize_program_synthesis_batch(
        self,
        claimed_todos: Sequence[ModalTodo],
        *,
        codex_exec_status: str,
        patch_status: Optional[str],
        validation_report: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Finalize claimed program-synthesis TODOs based on Codex execution outcome."""
        todo_ids = [
            todo.todo_id
            for todo in claimed_todos
            if _todo_optimizer_role(todo) == self.policy.program_synthesis_role
        ]
        if not todo_ids:
            return {
                "completed_count": 0,
                "failed_validation_count": 0,
                "outcome": "no_program_synthesis_todos",
                "reason": None,
                "updated": False,
            }

        normalized_exec_status = str(codex_exec_status or "").strip().lower()
        normalized_patch_status = str(patch_status or "").strip().lower()
        completed_count = 0
        failed_validation_count = 0
        requeued_count = 0
        reason: Optional[str] = None
        outcome = "no_status_change"

        if normalized_patch_status in {
            "created",
            "applied_to_main",
            "main_apply_no_merged_delta",
        }:
            for todo_id in todo_ids:
                todo = self.queue.get(todo_id)
                validation_gate = None
                if todo is not None:
                    validation_gate = _program_synthesis_validation_gate(
                        todo,
                        patch_status=normalized_patch_status,
                        validation_report=validation_report,
                    )
                    todo.metadata["validation_gate"] = validation_gate
                if validation_gate is not None and not validation_gate.get("accepted"):
                    reason = (
                        "target_metric_regression"
                        if validation_gate.get("regressed_metrics")
                        else "program_synthesis_validation_rejected"
                    )
                    failed_validation_count += int(
                        self.queue.fail_validation(todo_id, reason=reason)
                    )
                    continue
                completed_count += int(self.queue.complete(todo_id))
            outcome = (
                "partial"
                if completed_count and failed_validation_count
                else "failed_validation"
                if failed_validation_count
                else "completed"
            )
        elif normalized_patch_status.startswith("main_apply_baseline_validation_failed"):
            reason = "main_apply_baseline_validation_failed"
            for todo_id in todo_ids:
                todo = self.queue.get(todo_id)
                if todo is None:
                    continue
                if int(todo.metadata.get("transient_failure_count", 0)) >= 3:
                    failed_validation_count += int(
                        self.queue.fail_validation(todo_id, reason=reason)
                    )
                    continue
                todo.requeue(reason)
                requeued_count += 1
            outcome = "requeued" if requeued_count else "failed_validation"
        elif normalized_exec_status == "transient_failure":
            reason = "codex_exec_transient_failure"
            for todo_id in todo_ids:
                todo = self.queue.get(todo_id)
                if todo is None:
                    continue
                if int(todo.metadata.get("transient_failure_count", 0)) >= 3:
                    failed_validation_count += int(
                        self.queue.fail_validation(todo_id, reason=reason)
                    )
                    continue
                todo.requeue(reason)
                requeued_count += 1
            outcome = "requeued" if requeued_count else "failed_validation"
        elif normalized_exec_status in {"failed", "timeout"}:
            reason = f"codex_exec_{normalized_exec_status}"
            for todo_id in todo_ids:
                failed_validation_count += int(
                    self.queue.fail_validation(todo_id, reason=reason)
                )
            outcome = "failed_validation"
        elif normalized_patch_status not in {"created", "applied_to_main"}:
            reason = str(patch_status or "patch_not_created")
            for todo_id in todo_ids:
                failed_validation_count += int(
                    self.queue.fail_validation(todo_id, reason=reason)
                )
            outcome = "failed_validation"

        return {
            "completed_count": completed_count,
            "failed_validation_count": failed_validation_count,
            "outcome": outcome,
            "reason": reason,
            "requeued_count": requeued_count,
            "updated": bool(completed_count or failed_validation_count or requeued_count),
        }

    def optimize_once(
        self,
        samples: Sequence[LegalSample],
        *,
        autoencoder: AdaptiveModalAutoencoder,
        validation_samples: Optional[Sequence[LegalSample]] = None,
        worker_id: str = "modal-todo-daemon",
        max_items: int = 4,
        learning_rate: float = 0.35,
        iteration: int = 1,
    ) -> ModalOptimizationStep:
        """Generate TODOs, claim a batch, apply updates, and validate progress."""
        sample_list = list(samples)
        validation_list = list(validation_samples or [])
        samples_by_id = {sample.sample_id: sample for sample in sample_list}
        before = self._autoencoder_evaluation(autoencoder, sample_list)
        validation_before = (
            self._autoencoder_evaluation(
                autoencoder,
                validation_list,
                use_sample_memory=False,
            )
            if validation_list
            else None
        )
        loss_seeded = self.seed_from_evaluation(sample_list, autoencoder=before)
        bridge_loss_failure_count = int(self.last_bridge_loss_failure_count)
        bridge_loss_sample_count = int(self.last_bridge_loss_sample_count)
        bridge_loss_signal_count = int(self.last_bridge_loss_signal_count)
        self.queue.deduplicate_autoencoder(
            optimizer_role=self.policy.autoencoder_role,
        )
        claimed = self.claim_next_batch(
            worker_id=worker_id,
            max_items=max_items,
            optimizer_role=self.policy.autoencoder_role,
        )
        validation_scope = (
            "validation"
            if validation_before is not None
            else "training"
        )

        applied_updates: List[Dict[str, Any]] = []
        completed_ids: List[str] = []
        failed_validation_ids: List[str] = []
        if claimed:
            state_before_batch = autoencoder.state.copy()
            batch_updates = autoencoder.apply_todos(
                claimed,
                samples_by_id,
                learning_rate=learning_rate,
            )
            attempted_after = self._autoencoder_evaluation(autoencoder, sample_list)
            attempted_validation_after = (
                self._autoencoder_evaluation(
                    autoencoder,
                    validation_list,
                    use_sample_memory=False,
                )
                if validation_list
                else None
            )
            completion_before = validation_before or before
            completion_after = attempted_validation_after or attempted_after
            validations: List[Dict[str, Any]] = []
            for todo in claimed:
                validation = _todo_validation(
                    todo,
                    before=completion_before,
                    after=completion_after,
                )
                validation["scope"] = validation_scope
                validation["batch_size"] = len(claimed)
                todo.metadata["validation"] = validation
                validations.append(validation)

            batch_improved = _evaluation_improved(completion_before, completion_after) or any(
                bool(validation.get("improved")) for validation in validations
            )
            if batch_improved:
                applied_updates.extend(batch_updates)
                for todo in claimed:
                    self.queue.complete(todo.todo_id)
                    completed_ids.append(todo.todo_id)
            else:
                autoencoder.state = state_before_batch
                for todo in claimed:
                    validation = dict(todo.metadata.get("validation", {}))
                    validation["rolled_back"] = True
                    todo.metadata["validation"] = validation
                    self.queue.fail_validation(
                        todo.todo_id,
                        reason=(
                            "held-out validation metric did not improve"
                            if validation_scope == "validation"
                            else "training metric did not improve"
                        ),
                    )
                    failed_validation_ids.append(todo.todo_id)

        after = self._autoencoder_evaluation(autoencoder, sample_list)
        validation_after = (
            self._autoencoder_evaluation(
                autoencoder,
                validation_list,
                use_sample_memory=False,
            )
            if validation_list
            else None
        )
        program_synthesis_seeded = self.seed_program_synthesis_from_introspection(
            sample_list,
            autoencoder=autoencoder,
            residual_before=before,
            residual_after=after,
            residual_stage="post_sgd" if claimed else "current_state_no_sgd",
            require_residual_survival=bool(claimed),
        )
        program_synthesis_deduped = int(self.last_program_synthesis_deduped_count)

        return ModalOptimizationStep(
            iteration=iteration,
            worker_id=worker_id,
            before=before,
            after=after,
            seeded_count=len(loss_seeded) + len(program_synthesis_seeded),
            claimed_count=len(claimed),
            applied_count=len(applied_updates),
            completed_count=len(completed_ids),
            pending_count=self.queue.pending_count(),
            claimed_open_count=self.queue.claimed_count(),
            completed_todo_ids=completed_ids,
            failed_validation_count=len(failed_validation_ids),
            failed_validation_todo_ids=failed_validation_ids,
            applied_updates=applied_updates,
            autoencoder_claimed_count=len(claimed),
            bridge_loss_failure_count=bridge_loss_failure_count,
            bridge_loss_sample_count=bridge_loss_sample_count,
            bridge_loss_signal_count=bridge_loss_signal_count,
            loss_seeded_count=len(loss_seeded),
            program_synthesis_deduped_count=program_synthesis_deduped,
            program_synthesis_pending_count=self.queue.pending_count(
                optimizer_role=self.policy.program_synthesis_role
            ),
            program_synthesis_seeded_count=len(program_synthesis_seeded),
            validation_before=validation_before,
            validation_after=validation_after,
        )

    def optimize(
        self,
        samples: Sequence[LegalSample],
        *,
        autoencoder: AdaptiveModalAutoencoder,
        validation_samples: Optional[Sequence[LegalSample]] = None,
        worker_id: str = "modal-todo-daemon",
        max_items: int = 4,
        learning_rate: float = 0.35,
        max_iterations: int = 5,
        target_cross_entropy_loss: float = 0.05,
        target_cosine_similarity: float = 0.99,
    ) -> ModalOptimizationRun:
        """Run bounded daemon iterations until targets are met or progress stops."""
        steps: List[ModalOptimizationStep] = []
        stopped_reason = "max_iterations"
        final_evaluation = self._autoencoder_evaluation(autoencoder, list(samples))
        validation_final_evaluation = (
            self._autoencoder_evaluation(
                autoencoder,
                list(validation_samples),
                use_sample_memory=False,
            )
            if validation_samples is not None and len(validation_samples) > 0
            else None
        )

        for iteration in range(1, max_iterations + 1):
            step = self.optimize_once(
                samples,
                autoencoder=autoencoder,
                validation_samples=validation_samples,
                worker_id=worker_id,
                max_items=max_items,
                learning_rate=learning_rate,
                iteration=iteration,
            )
            steps.append(step)
            final_evaluation = step.after
            validation_final_evaluation = step.validation_after or validation_final_evaluation
            target_evaluation = validation_final_evaluation or final_evaluation
            if (
                target_evaluation.cross_entropy_loss <= target_cross_entropy_loss
                and target_evaluation.embedding_cosine_similarity >= target_cosine_similarity
            ):
                stopped_reason = "targets_met"
                break
            if step.claimed_count == 0:
                stopped_reason = "no_claimed_todos"
                break
            if not step.improved:
                stopped_reason = "no_validated_improvement"
                break

        return ModalOptimizationRun(
            steps=steps,
            final_evaluation=final_evaluation,
            stopped_reason=stopped_reason,
            validation_final_evaluation=validation_final_evaluation,
        )

    def optimize_uscode_parquet(
        self,
        laws_parquet: str | Path | BinaryIO,
        *,
        autoencoder: AdaptiveModalAutoencoder,
        embeddings_parquet: str | Path | BinaryIO | None = None,
        limit: int = 25,
        offset: int = 0,
        validation_limit: int = 0,
        validation_offset: Optional[int] = None,
        worker_id: str = "modal-todo-daemon",
        max_items: int = 4,
        learning_rate: float = 0.35,
        max_iterations: int = 5,
        target_cross_entropy_loss: float = 0.05,
        target_cosine_similarity: float = 0.99,
    ) -> ModalOptimizationRun:
        """Load U.S. Code parquet samples and run daemon optimization."""
        from .uscode_dataset import load_uscode_samples_from_parquet

        samples = load_uscode_samples_from_parquet(
            laws_parquet,
            embeddings_parquet=embeddings_parquet,
            limit=limit,
            offset=offset,
        )
        validation_samples = None
        if validation_limit > 0:
            validation_samples = load_uscode_samples_from_parquet(
                laws_parquet,
                embeddings_parquet=embeddings_parquet,
                limit=validation_limit,
                offset=validation_offset if validation_offset is not None else offset + limit,
            )
        return self.optimize(
            samples,
            autoencoder=autoencoder,
            validation_samples=validation_samples,
            worker_id=worker_id,
            max_items=max_items,
            learning_rate=learning_rate,
            max_iterations=max_iterations,
            target_cross_entropy_loss=target_cross_entropy_loss,
            target_cosine_similarity=target_cosine_similarity,
        )


def _todo_id(action: str, sample_id: str, loss_name: str, loss_value: float) -> str:
    payload = f"{action}:{sample_id}:{loss_name}:{loss_value:.6f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _autoencoder_todo_signature(todo: ModalTodo) -> str:
    """Return the optimizer-work signature used to batch trainable TODOs."""
    if (
        todo.action not in AUTOENCODER_TRAINABLE_ACTIONS
        and todo.loss_name not in AUTOENCODER_TRAINABLE_LOSSES
    ):
        return ""
    payload = {
        "action": str(todo.action),
        "loss_name": str(todo.loss_name),
        "selected_frame": str(todo.metadata.get("selected_frame") or ""),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _coalesce_autoencoder_todos(
    todos: Iterable[ModalTodo],
    *,
    optimizer_role: str = AUTOENCODER_SGD_ROLE,
) -> List[ModalTodo]:
    """Merge equivalent trainable TODOs so SGD sees batches instead of drips."""
    selected: List[ModalTodo] = []
    by_signature: Dict[str, ModalTodo] = {}
    for todo in todos:
        if _todo_optimizer_role(todo) != optimizer_role:
            selected.append(todo)
            continue
        signature = _autoencoder_todo_signature(todo)
        representative = by_signature.get(signature)
        if representative is None:
            todo.metadata["autoencoder_bundle_signature"] = signature
            by_signature[signature] = todo
            selected.append(todo)
            continue
        _merge_autoencoder_todo_evidence(representative, todo)
    return selected


def _merge_autoencoder_todo_evidence(target: ModalTodo, duplicate: ModalTodo) -> None:
    """Merge trainable TODO evidence while preserving the representative status."""
    duplicate_count = int(target.metadata.get("deduped_duplicate_count", 0)) + 1
    duplicate_count += int(duplicate.metadata.get("deduped_duplicate_count", 0))
    target.metadata["deduped_duplicate_count"] = duplicate_count

    duplicate_ids = [duplicate.todo_id]
    duplicate_ids.extend(list(target.metadata.get("deduped_todo_ids", [])))
    duplicate_ids.extend(list(duplicate.metadata.get("deduped_todo_ids", [])))
    target.metadata["deduped_todo_ids"] = _unique_preserve_order(
        str(todo_id) for todo_id in duplicate_ids if str(todo_id)
    )[:256]

    target.sample_ids = _unique_preserve_order(
        [*target.sample_ids, *duplicate.sample_ids]
    )
    target.citations = _unique_preserve_order(
        [*target.citations, *duplicate.citations]
    )
    target.loss_value = max(float(target.loss_value), float(duplicate.loss_value))
    target.priority = max(float(target.priority), float(duplicate.priority))
    target.metadata["autoencoder_bundle_signature"] = _autoencoder_todo_signature(target)
    target.metadata["support_count"] = len(target.sample_ids)
    if duplicate.status == "failed_validation":
        target.metadata["deduped_failed_validation_count"] = (
            int(target.metadata.get("deduped_failed_validation_count", 0)) + 1
        )


def _program_synthesis_validation_gate(
    todo: ModalTodo,
    *,
    patch_status: str,
    validation_report: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Record why a Codex patch was accepted for a program-synthesis TODO."""
    report = dict(validation_report or {})
    metric_deltas = dict(report.get("metric_deltas", {}) or {})
    targeted_metrics = [
        str(metric)
        for metric in todo.metadata.get("target_metrics", [])
        if str(metric).strip()
    ]
    improved_metrics = [
        metric
        for metric in targeted_metrics
        if float(metric_deltas.get(metric, 0.0) or 0.0) > 0.0
    ]
    regressed_metrics = [
        metric
        for metric in targeted_metrics
        if float(metric_deltas.get(metric, 0.0) or 0.0) < 0.0
    ]
    deterministic_fix = str(report.get("status") or "").lower() in {
        "passed",
        "skipped",
        "not_measured",
        "",
    }
    return {
        "accepted": bool(improved_metrics or (deterministic_fix and not regressed_metrics)),
        "deterministic_validation_fix": deterministic_fix,
        "improved_metrics": improved_metrics,
        "metric_deltas": metric_deltas,
        "patch_status": patch_status,
        "regressed_metrics": regressed_metrics,
        "target_metrics": targeted_metrics,
        "validation_status": str(report.get("status") or "not_measured"),
    }


def _annotate_post_sgd_residual_evidence(
    todo: ModalTodo,
    *,
    before: AutoencoderEvaluation,
    after: AutoencoderEvaluation,
    residual_stage: str,
) -> bool:
    """Record before/after SGD metric deltas and whether Codex work remains."""
    target_metrics = _unique_preserve_order(
        str(metric)
        for metric in _as_list(todo.metadata.get("target_metrics", []))
        if str(metric)
    )
    before_metrics: Dict[str, float] = {}
    after_metrics: Dict[str, float] = {}
    metric_deltas: Dict[str, float] = {}
    resolved_metrics: List[str] = []
    surviving_metrics: List[str] = []
    unmeasured_metrics: List[str] = []

    for metric in target_metrics:
        before_value = _metric_value(before, metric)
        after_value = _metric_value(after, metric)
        if before_value is None or after_value is None:
            unmeasured_metrics.append(metric)
            continue
        before_metrics[metric] = round(float(before_value), 9)
        after_metrics[metric] = round(float(after_value), 9)
        delta = _metric_improvement_delta(
            metric,
            before_value=float(before_value),
            after_value=float(after_value),
        )
        metric_deltas[metric] = round(delta, 9)
        if _metric_residual_survives(metric, float(after_value)):
            surviving_metrics.append(metric)
        else:
            resolved_metrics.append(metric)

    survives = bool(surviving_metrics)
    if target_metrics and len(unmeasured_metrics) == len(target_metrics):
        survives = True
    todo.metadata["post_sgd_metric_after"] = after_metrics
    todo.metadata["post_sgd_metric_before"] = before_metrics
    todo.metadata["post_sgd_metric_deltas"] = metric_deltas
    todo.metadata["post_sgd_residual_resolved_metrics"] = resolved_metrics
    todo.metadata["post_sgd_residual_surviving_metrics"] = surviving_metrics
    todo.metadata["post_sgd_residual_unmeasured_metrics"] = unmeasured_metrics
    todo.metadata["post_sgd_requires_codex"] = survives
    measured_count = max(1, len(before_metrics))
    todo.metadata["post_sgd_residual_survival_score"] = round(
        len(surviving_metrics) / measured_count,
        9,
    )
    todo.metadata["post_sgd_residual_resolved_score"] = round(
        len(resolved_metrics) / measured_count,
        9,
    )
    todo.metadata["residual_cluster_stage"] = residual_stage
    return survives


def _metric_improvement_delta(
    metric_name: str,
    *,
    before_value: float,
    after_value: float,
) -> float:
    if _metric_higher_is_better(metric_name):
        return after_value - before_value
    return before_value - after_value


def _metric_residual_survives(metric_name: str, value: float) -> bool:
    threshold = _metric_residual_threshold(metric_name)
    if _metric_higher_is_better(metric_name):
        return float(value) < threshold
    return float(value) > threshold


def _metric_higher_is_better(metric_name: str) -> bool:
    normalized = str(metric_name)
    return (
        normalized in {"embedding_cosine_similarity", "cosine_similarity"}
        or normalized.endswith("_similarity")
        or normalized.endswith("_score")
        or normalized.endswith("_rate")
    ) and not normalized.endswith("_loss")


def _metric_residual_threshold(metric_name: str) -> float:
    normalized = str(metric_name)
    if _metric_higher_is_better(normalized):
        return 0.98
    thresholds = dict(ModalLossTodoGenerator.DEFAULT_THRESHOLDS)
    thresholds.update(
        {
            "cosine_loss": 0.02,
            "embedding_cosine_similarity": 0.98,
            "legal_ir_multiview_cross_entropy_loss": 0.05,
            "legal_ir_multiview_total_loss": 0.05,
            "legal_ir_view_cross_entropy_loss": 0.05,
        }
    )
    return float(thresholds.get(normalized, 0.0))


def _program_todo_id(
    *,
    action: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> str:
    payload = _program_todo_signature_payload(
        action=action,
        target_component=target_component,
        sample_ids=sample_ids,
    )
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"program-{digest}"


def _program_todo_signature(
    *,
    action: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> str:
    payload = _program_todo_signature_payload(
        action=action,
        target_component=target_component,
        sample_ids=sample_ids,
    )
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _program_todo_signature_payload(
    *,
    action: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> Dict[str, Any]:
    return {
        "action": action,
        "sample_ids": sorted(sample_ids),
        "target_component": target_component,
    }


def _program_todo_bundle_signature(
    *,
    action: str,
    target_component: str,
    program_synthesis_scope: str,
    family_pairs: Sequence[str],
) -> str:
    payload = {
        "action": action,
        "family_pairs": sorted(set(str(pair) for pair in family_pairs if str(pair))),
        "program_synthesis_scope": program_synthesis_scope,
        "target_component": target_component,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _program_todo_semantic_bundle_key(todo: ModalTodo) -> str:
    stored_key = str(todo.metadata.get("semantic_bundle_key") or "").strip()
    if stored_key:
        return stored_key
    target_component = _todo_target_component(todo)
    scope = str(todo.metadata.get("program_synthesis_scope") or "").strip()
    if not scope:
        scope = _program_synthesis_scope(
            action=todo.action,
            target_component=target_component,
        )
    hint_evidence = todo.metadata.get("hint_evidence", [])
    return _program_todo_bundle_signature(
        action=todo.action,
        target_component=target_component,
        program_synthesis_scope=scope,
        family_pairs=_program_todo_family_pairs_from_evidence(hint_evidence),
    )


def program_synthesis_todo_embedding_text(todo: ModalTodo) -> str:
    """Return the text that the Codex task vector index embeds for bundling."""
    metadata = todo.metadata or {}
    evidence_lines: List[str] = []
    for evidence in list(metadata.get("hint_evidence") or [])[:8]:
        if not isinstance(evidence, Mapping):
            continue
        evidence_lines.append(
            " ".join(
                str(evidence.get(key) or "").strip()
                for key in (
                    "hint_id",
                    "predicted_family",
                    "target_family",
                    "selected_frame",
                    "frame_features",
                    "roundtrip_preview",
                )
                if str(evidence.get(key) or "").strip()
            )
        )
    parts = [
        f"action: {todo.action}",
        f"objective: {todo.objective}",
        f"loss: {todo.loss_name}",
        f"target_component: {_todo_target_component(todo)}",
        f"program_synthesis_scope: {_program_todo_scope(todo)}",
        f"semantic_bundle_key: {_program_todo_semantic_bundle_key(todo)}",
        f"citations: {' '.join(todo.citations[:8])}",
        f"sample_ids: {' '.join(todo.sample_ids[:16])}",
        f"evidence: {' '.join(line for line in evidence_lines if line)}",
    ]
    return "\n".join(part for part in parts if part.strip())


def select_program_synthesis_vector_bundle(
    todos: Sequence[ModalTodo],
    *,
    vectors_by_todo_id: Mapping[str, Sequence[float]],
    max_items: int,
    min_similarity: float = 0.72,
    fill_min_similarity: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Select a vector-nearest program-synthesis bundle from pending candidates.

    The first item is always the highest-priority anchor. Neighbors must remain
    in the same program_synthesis_scope so parallel Codex workers stay inside
    their AST/write lanes.  When ``fill_min_similarity`` is set lower than the
    strict threshold, remaining slots may be filled from the same target
    component so one Codex call can handle adjacent repairs without crossing
    write-lane boundaries.
    """
    if max_items < 1:
        return []
    candidates = [
        todo
        for todo in sorted(todos, key=_todo_priority_key)
        if _coerce_vector(vectors_by_todo_id.get(todo.todo_id))
    ]
    if not candidates:
        return []

    anchor = candidates[0]
    anchor_vector = _coerce_vector(vectors_by_todo_id.get(anchor.todo_id))
    if not anchor_vector:
        return []

    selected: List[Dict[str, Any]] = [
        {"similarity": 1.0, "todo": anchor},
    ]
    scored: List[tuple[float, tuple[float, str, str], ModalTodo]] = []
    fill_scored: List[tuple[float, tuple[float, str, str], ModalTodo]] = []
    fill_threshold = (
        float(fill_min_similarity)
        if fill_min_similarity is not None
        else float(min_similarity)
    )
    allow_fill = fill_threshold < float(min_similarity)
    for todo in candidates[1:]:
        if not _program_todo_vector_bundle_compatible(anchor, todo):
            continue
        vector = _coerce_vector(vectors_by_todo_id.get(todo.todo_id))
        if not vector:
            continue
        similarity = _cosine_similarity(anchor_vector, vector)
        if similarity >= float(min_similarity):
            scored.append((similarity, _todo_priority_key(todo), todo))
            continue
        if not allow_fill or similarity < fill_threshold:
            continue
        if _todo_target_component(anchor) != _todo_target_component(todo):
            continue
        fill_scored.append((similarity, _todo_priority_key(todo), todo))

    for similarity, _, todo in sorted(scored, key=lambda item: (-item[0], item[1])):
        if len(selected) >= max_items:
            break
        selected.append({"similarity": similarity, "todo": todo})
    selected_ids = {str(item["todo"].todo_id) for item in selected}
    for similarity, _, todo in sorted(fill_scored, key=lambda item: (-item[0], item[1])):
        if len(selected) >= max_items:
            break
        if todo.todo_id in selected_ids:
            continue
        selected.append({"similarity": similarity, "todo": todo, "fill_reason": "same_target"})
        selected_ids.add(todo.todo_id)
    return selected


def _program_todo_scope(todo: ModalTodo) -> str:
    scope = str(todo.metadata.get("program_synthesis_scope") or "").strip()
    if scope:
        return scope
    return _program_synthesis_scope(
        action=todo.action,
        target_component=_todo_target_component(todo),
    )


def _program_todo_vector_bundle_compatible(anchor: ModalTodo, candidate: ModalTodo) -> bool:
    if _program_todo_scope(anchor) != _program_todo_scope(candidate):
        return False
    return _todo_optimizer_role(anchor) == _todo_optimizer_role(candidate)


def _coerce_vector(value: Optional[Sequence[float]]) -> List[float]:
    if value is None:
        return []
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError):
        return []
    return vector if vector else []


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    dot = sum(float(left[index]) * float(right[index]) for index in range(size))
    left_norm = sum(float(left[index]) ** 2 for index in range(size)) ** 0.5
    right_norm = sum(float(right[index]) ** 2 for index in range(size)) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _program_todo_family_pairs_from_evidence(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    pairs: List[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        predicted = str(item.get("predicted_family") or "").strip()
        target = str(item.get("target_family") or "").strip()
        if predicted and target:
            pairs.append(f"{predicted}->{target}")
    return sorted(set(pairs))


def _program_todos_near_duplicate(
    existing: ModalTodo,
    candidate: ModalTodo,
    *,
    jaccard_threshold: float,
) -> bool:
    if existing.action != candidate.action:
        return False
    if _todo_target_component(existing) != _todo_target_component(candidate):
        return False
    existing_signature = str(existing.metadata.get("dedupe_signature") or "")
    candidate_signature = str(candidate.metadata.get("dedupe_signature") or "")
    if existing_signature and candidate_signature and existing_signature == candidate_signature:
        return True
    existing_samples = set(existing.sample_ids)
    candidate_samples = set(candidate.sample_ids)
    if not existing_samples or not candidate_samples:
        return False
    intersection = len(existing_samples & candidate_samples)
    union = len(existing_samples | candidate_samples)
    if union == 0:
        return False
    return (intersection / union) >= float(jaccard_threshold)


def _program_todos_duplicate_for_repair(
    existing: ModalTodo,
    candidate: ModalTodo,
    *,
    jaccard_threshold: float,
) -> bool:
    """Return True when two program-repair TODOs should share one Codex task."""

    return _program_todos_near_duplicate(
        existing,
        candidate,
        jaccard_threshold=jaccard_threshold,
    ) or _program_todos_share_semantic_bundle(existing, candidate)


def _program_todos_share_semantic_bundle(existing: ModalTodo, candidate: ModalTodo) -> bool:
    """Return True for same action/component/scope/family-pair repair requests."""

    if existing.action != candidate.action:
        return False
    if _todo_target_component(existing) != _todo_target_component(candidate):
        return False
    existing_key = _program_todo_semantic_bundle_key(existing)
    candidate_key = _program_todo_semantic_bundle_key(candidate)
    return bool(existing_key and candidate_key and existing_key == candidate_key)


def _merge_program_todo_evidence(target: ModalTodo, duplicate: ModalTodo) -> None:
    """Carry duplicate evidence into the representative program-repair TODO."""

    target.sample_ids = _unique_preserve_order([*target.sample_ids, *duplicate.sample_ids])
    target.citations = _unique_preserve_order([*target.citations, *duplicate.citations])
    target.priority = max(float(target.priority), float(duplicate.priority))
    target.loss_value = max(float(target.loss_value), float(duplicate.loss_value))
    target.metadata["deduped_duplicate_count"] = int(
        target.metadata.get("deduped_duplicate_count", 0)
    ) + 1 + int(duplicate.metadata.get("deduped_duplicate_count", 0))
    target.metadata["merged_sample_count"] = len(target.sample_ids)

    duplicate_ids = list(target.metadata.get("deduped_todo_ids", []))
    duplicate_ids.append(duplicate.todo_id)
    duplicate_ids.extend(list(duplicate.metadata.get("deduped_todo_ids", [])))
    target.metadata["deduped_todo_ids"] = _unique_preserve_order(
        str(todo_id) for todo_id in duplicate_ids if str(todo_id)
    )[:64]

    hint_ids = _unique_preserve_order(
        [
            *list(target.metadata.get("hint_ids", [])),
            *list(duplicate.metadata.get("hint_ids", [])),
        ]
    )
    if hint_ids:
        target.metadata["hint_ids"] = hint_ids[:128]

    evidence = _merge_hint_evidence(
        list(target.metadata.get("hint_evidence", [])),
        list(duplicate.metadata.get("hint_evidence", [])),
    )
    if evidence:
        target.metadata["hint_evidence"] = evidence
    for key, limit in (
        ("target_metrics", 32),
        ("validation_commands", 16),
        ("residual_signatures", 32),
    ):
        merged_values = _merge_jsonish_metadata_values(
            target.metadata.get(key, []),
            duplicate.metadata.get(key, []),
            limit=limit,
        )
        if merged_values:
            target.metadata[key] = merged_values
    metric_payloads = _merge_jsonish_metadata_values(
        target.metadata.get("metric_sample_payloads", []),
        duplicate.metadata.get("metric_sample_payloads", []),
        limit=16,
        identity_key="sample_id",
    )
    if metric_payloads:
        target.metadata["metric_sample_payloads"] = metric_payloads
    if target.sample_ids:
        target.metadata["support_count"] = max(
            int(target.metadata.get("support_count", 0) or 0),
            len(target.sample_ids),
        )


def _merge_jsonish_metadata_values(
    left: Any,
    right: Any,
    *,
    limit: int,
    identity_key: Optional[str] = None,
) -> List[Any]:
    """Merge metadata lists while preserving order and JSON-stable identity."""
    merged: List[Any] = []
    seen: set[str] = set()
    for item in [*_as_list(left), *_as_list(right)]:
        key = _jsonish_metadata_identity(item, identity_key=identity_key)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= max(0, int(limit)):
            break
    return merged


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _jsonish_metadata_identity(item: Any, *, identity_key: Optional[str]) -> str:
    if identity_key and isinstance(item, Mapping):
        identity_value = str(item.get(identity_key) or "").strip()
        if identity_value:
            return f"{identity_key}:{identity_value}"
    try:
        return json.dumps(item, ensure_ascii=True, sort_keys=True, default=str)
    except TypeError:
        return str(item)


def _merge_hint_evidence(left: Sequence[Any], right: Sequence[Any]) -> List[Any]:
    merged: List[Any] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        try:
            key = json.dumps(item, ensure_ascii=True, sort_keys=True, default=str)
        except TypeError:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= 32:
            break
    return merged


def _todo_target_component(todo: ModalTodo) -> str:
    return str(
        todo.metadata.get("target_component")
        or PROGRAM_SYNTHESIS_ACTION_TARGETS.get(todo.action)
        or ""
    )


def _program_synthesis_scope(*, action: str, target_component: str) -> str:
    target = target_component or PROGRAM_SYNTHESIS_ACTION_TARGETS.get(action, "")
    return logic_optimizer_scope_for_component(target, action=action)


def _sample_id_from_hint(hint: ModalProgramSynthesisHint) -> str:
    return str(hint.evidence.get("sample_id") or "").strip()


def _program_synthesis_target_metrics(
    *,
    action: str,
    target_component: str,
) -> List[str]:
    """Return metrics a Codex patch for this synthesis TODO should improve."""
    metrics = list(PROGRAM_SYNTHESIS_ACTION_TARGET_METRICS.get(str(action), ()))
    component_defaults = {
        "bridge.contracts": (
            "legal_ir_view_cross_entropy_loss",
            "legal_ir_multiview_total_loss",
        ),
        "CEC.native": ("cec_dcec_validation_failure_ratio",),
        "TDFOL.prover": ("tdfol_parse_failure_ratio",),
        "deontic.ir": ("deontic_decoder_slot_loss",),
        "external_provers.router": ("legal_ir_multiview_proof_failure_ratio",),
        "knowledge_graphs.neo4j_compat": (
            "legal_ir_multiview_graph_failure_penalty",
        ),
        "modal.compiler": ("symbolic_validity_penalty",),
        "modal.compiler.ambiguity": ("cross_entropy_loss",),
        "modal.compiler.registry": ("cross_entropy_loss",),
        "modal.frame_logic": ("flogic_similarity_loss",),
        "modal.ir_decompiler": (
            "embedding_cosine_similarity",
            "reconstruction_loss",
        ),
        "zkp.circuits": ("zkp_verification_failure_ratio",),
    }
    metrics.extend(component_defaults.get(str(target_component), ()))
    return _unique_preserve_order(str(metric) for metric in metrics if str(metric))


def _program_synthesis_validation_commands(
    *,
    action: str,
    target_component: str,
    program_synthesis_scope: str,
) -> List[str]:
    """Return targeted validation commands for a generated Codex TODO."""
    tests = list(
        PROGRAM_SYNTHESIS_SCOPE_VALIDATION_TESTS.get(str(program_synthesis_scope), ())
    )
    if not tests:
        tests = [
            "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py"
        ]
    if str(target_component).startswith("modal.") or str(action).startswith("refine_"):
        tests.append(
            "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py"
        )
    tests = _unique_preserve_order(str(path) for path in tests if str(path))
    return [f"{sys.executable} -m pytest -q {' '.join(tests)}"]


def _program_synthesis_sample_payloads(
    sample_ids: Sequence[str],
    *,
    samples_by_id: Mapping[str, LegalSample],
    max_samples: int = 8,
) -> List[Dict[str, Any]]:
    """Return compact legal sample payloads for patch metric revalidation."""
    limit = max(0, int(max_samples))
    if limit < 1:
        return []
    payloads: List[Dict[str, Any]] = []
    for sample_id in sample_ids:
        sample = samples_by_id.get(str(sample_id))
        if sample is None:
            continue
        payloads.append(
            {
                "citation": sample.citation,
                "embedding_model": sample.embedding_model,
                "embedding_vector": [float(value) for value in sample.embedding_vector],
                "sample_id": sample.sample_id,
                "section": sample.section,
                "source": sample.source,
                "text": sample.text,
                "title": sample.title,
            }
        )
        if len(payloads) >= limit:
            break
    return payloads


def _compact_hint_evidence(hint: ModalProgramSynthesisHint) -> Dict[str, Any]:
    """Keep the autoencoder evidence needed for later deterministic repair."""
    evidence = dict(hint.evidence)
    summary: Dict[str, Any] = {
        "hint_id": hint.hint_id,
        "priority": hint.priority,
    }
    for key in (
        "bridge_failure_name",
        "cosine_similarity",
        "family_margin",
        "frame_features",
        "generic_bridge_priority_backoff",
        "legal_ir_component_gaps",
        "legal_ir_underrepresented_components",
        "predicted_family",
        "predicted_view",
        "reconstruction_loss",
        "sample_id",
        "target_file_lane",
        "target_family",
        "target_probability",
        "target_view",
        "top_embedding_features",
        "top_family_features",
    ):
        value = evidence.get(key)
        if value not in (None, "", []):
            summary[key] = value
    return summary


def _todo_optimizer_role(todo: ModalTodo) -> str:
    role = str(todo.metadata.get("optimizer_role") or "").strip()
    if role:
        return role
    return ModalOptimizerPolicy().role_for(
        action=str(todo.action),
        loss_name=str(todo.loss_name),
    )


def _todo_matches(
    todo: ModalTodo,
    *,
    status: str,
    optimizer_role: Optional[str] = None,
    metadata_filter: Optional[Mapping[str, str]] = None,
) -> bool:
    if todo.status != status:
        return False
    if optimizer_role is not None and _todo_optimizer_role(todo) != optimizer_role:
        return False
    if metadata_filter:
        for key, value in metadata_filter.items():
            if str(todo.metadata.get(key) or "") != str(value):
                return False
    return True


def _todo_priority_key(todo: ModalTodo) -> tuple[float, str, str]:
    return (-todo.priority, todo.created_at, todo.todo_id)


def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _todo_validation(
    todo: ModalTodo,
    *,
    before: AutoencoderEvaluation,
    after: AutoencoderEvaluation,
) -> Dict[str, Any]:
    before_value = _metric_value(before, todo.loss_name)
    after_value = _metric_value(after, todo.loss_name)
    if todo.loss_name == "cosine_loss":
        improved = after.embedding_cosine_similarity > before.embedding_cosine_similarity
    elif before_value is None or after_value is None:
        improved = False
    else:
        improved = after_value < before_value
    return {
        "after": after_value,
        "after_cosine_similarity": after.embedding_cosine_similarity,
        "before": before_value,
        "before_cosine_similarity": before.embedding_cosine_similarity,
        "improved": improved,
    }


def _evaluation_improved(before: AutoencoderEvaluation, after: AutoencoderEvaluation) -> bool:
    """Return whether the aggregate objective moved in the desired direction."""
    return (
        _evaluation_objective(after) < _evaluation_objective(before)
        and after.embedding_cosine_similarity + 0.01 >= before.embedding_cosine_similarity
        and after.reconstruction_loss <= before.reconstruction_loss + 0.02
        and after.cross_entropy_loss <= before.cross_entropy_loss
    )


def _evaluation_objective(evaluation: AutoencoderEvaluation) -> float:
    return (
        evaluation.cross_entropy_loss
        + evaluation.reconstruction_loss
        + max(0.0, 1.0 - evaluation.embedding_cosine_similarity)
        + _legal_ir_objective_component(evaluation.legal_ir_losses)
    )


def _legal_ir_objective_component(losses: Mapping[str, float]) -> float:
    values = {str(name): max(0.0, float(value)) for name, value in dict(losses).items()}
    if not values:
        return 0.0
    component = 0.0
    component += min(1.0, values.get("legal_ir_multiview_total_loss", 0.0))
    component += min(1.0, values.get("legal_ir_view_cross_entropy_loss", 0.0) / 3.0)
    component += min(1.0, values.get("legal_ir_multiview_proof_failure_ratio", 0.0))
    component += min(1.0, values.get("legal_ir_multiview_graph_failure_penalty", 0.0))
    detail = 0.0
    for name, value in values.items():
        if name in {
            "legal_ir_multiview_total_loss",
            "legal_ir_view_cross_entropy_loss",
            "legal_ir_multiview_proof_failure_ratio",
            "legal_ir_multiview_graph_failure_penalty",
        }:
            continue
        if name.startswith("legal_ir_") or name.startswith(
            ("deontic_", "tdfol_", "cec_", "zkp_", "external_prover_")
        ):
            detail += min(0.25, value)
    return component + min(1.0, detail)


def _metric_value(evaluation: AutoencoderEvaluation, name: str) -> Optional[float]:
    metric = {
        "cosine_loss": evaluation.cosine_loss,
        "cross_entropy_loss": evaluation.cross_entropy_loss,
        "embedding_cosine_similarity": evaluation.embedding_cosine_similarity,
        "frame_ranking_loss": evaluation.frame_ranking_loss,
        "reconstruction_loss": evaluation.reconstruction_loss,
        "symbolic_validity_penalty": evaluation.symbolic_validity_penalty,
    }.get(name)
    if metric is not None:
        return metric
    if name in evaluation.legal_ir_losses:
        return float(evaluation.legal_ir_losses[name])
    return None


__all__ = [
    "LossSnapshot",
    "ModalLossTodoGenerator",
    "ModalOptimizerPolicy",
    "ModalOptimizationRun",
    "ModalOptimizationStep",
    "ModalProgramSynthesisTodoGenerator",
    "ModalTodo",
    "ModalTodoQueue",
    "ModalTodoSupervisor",
]
