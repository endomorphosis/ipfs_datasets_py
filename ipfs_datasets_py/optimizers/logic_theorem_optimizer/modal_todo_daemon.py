"""Loss-driven TODO generation and batch claiming for modal parser work."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, List, Mapping, Optional, Sequence

from .legal_samples import LegalSample
from .modal_autoencoder import AdaptiveModalAutoencoder, AutoencoderEvaluation


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
            "before": self.before.to_dict(),
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
            "pending_count": self.pending_count,
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
    """Convert SGD-style loss signals into deterministic parser TODOs."""

    DEFAULT_THRESHOLDS = {
        "cosine_loss": 0.05,
        "cross_entropy_loss": 0.05,
        "frame_ranking_loss": 0.0,
        "reconstruction_loss": 0.05,
        "symbolic_validity_penalty": 0.0,
    }

    def __init__(self, thresholds: Optional[Mapping[str, float]] = None) -> None:
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update({name: float(value) for name, value in thresholds.items()})

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
            "symbolic_validity_penalty": (
                "add_deterministic_parser_rule",
                "Add a deterministic parser rule or fixture for legal text that failed symbolic validation.",
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
        return ModalTodo(
            todo_id=todo_id,
            action=action,
            objective=objective,
            sample_ids=[snapshot.sample_id],
            citations=[snapshot.citation],
            loss_name=loss_name,
            loss_value=round(loss_value, 12),
            priority=priority,
            metadata={
                "selected_frame": snapshot.selected_frame,
                "source": "modal_loss_todo_generator_v1",
            },
        )


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
            self._todos[todo.todo_id] = todo
            added += 1
        return added

    def pending(self) -> List[ModalTodo]:
        return self._by_priority(status="pending")

    def claimed(self) -> List[ModalTodo]:
        return self._by_priority(status="claimed")

    def all(self) -> List[ModalTodo]:
        return sorted(self._todos.values(), key=lambda todo: (-todo.priority, todo.todo_id))

    def get(self, todo_id: str) -> Optional[ModalTodo]:
        return self._todos.get(todo_id)

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for todo in self._todos.values():
            counts[todo.status] = counts.get(todo.status, 0) + 1
        return dict(sorted(counts.items()))

    def claim_batch(self, *, worker_id: str, max_items: int) -> List[ModalTodo]:
        """Claim up to ``max_items`` pending TODOs for one worker."""
        if max_items < 1:
            return []
        claimed: List[ModalTodo] = []
        for todo in self.pending()[:max_items]:
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
        todos = [
            ModalTodo.from_dict(json.loads(line))
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(todos)

    def _by_priority(self, *, status: str) -> List[ModalTodo]:
        return sorted(
            (todo for todo in self._todos.values() if todo.status == status),
            key=lambda todo: (-todo.priority, todo.created_at, todo.todo_id),
        )


class ModalTodoSupervisor:
    """Coordinator that seeds TODOs from samples/evaluations and claims batches."""

    def __init__(
        self,
        *,
        queue: Optional[ModalTodoQueue] = None,
        generator: Optional[ModalLossTodoGenerator] = None,
    ) -> None:
        self.queue = queue or ModalTodoQueue()
        self.generator = generator or ModalLossTodoGenerator()

    def seed_from_evaluation(
        self,
        samples: Sequence[LegalSample],
        *,
        autoencoder: Optional[AutoencoderEvaluation] = None,
    ) -> List[ModalTodo]:
        """Generate TODOs from a batch and add them to the queue."""
        snapshots = [LossSnapshot.from_sample(sample, autoencoder=autoencoder) for sample in samples]
        todos = self.generator.generate(snapshots)
        self.queue.add_many(todos)
        return todos

    def claim_next_batch(self, *, worker_id: str, max_items: int) -> List[ModalTodo]:
        return self.queue.claim_batch(worker_id=worker_id, max_items=max_items)

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
        before = autoencoder.evaluate(sample_list)
        validation_before = autoencoder.evaluate(validation_list) if validation_list else None
        seeded = self.seed_from_evaluation(sample_list, autoencoder=before)
        claimed = self.claim_next_batch(worker_id=worker_id, max_items=max_items)
        applied_updates = autoencoder.apply_todos(
            claimed,
            samples_by_id,
            learning_rate=learning_rate,
        )
        after = autoencoder.evaluate(sample_list)
        validation_after = autoencoder.evaluate(validation_list) if validation_list else None
        validation_scope = (
            "validation"
            if validation_before is not None and validation_after is not None
            else "training"
        )
        completion_before = validation_before or before
        completion_after = validation_after or after

        completed_ids: List[str] = []
        failed_validation_ids: List[str] = []
        for todo in claimed:
            validation = _todo_validation(todo, before=completion_before, after=completion_after)
            validation["scope"] = validation_scope
            todo.metadata["validation"] = validation
            if validation["improved"]:
                self.queue.complete(todo.todo_id)
                completed_ids.append(todo.todo_id)
            elif validation_scope == "validation":
                self.queue.fail_validation(
                    todo.todo_id,
                    reason="held-out validation metric did not improve",
                )
                failed_validation_ids.append(todo.todo_id)

        return ModalOptimizationStep(
            iteration=iteration,
            worker_id=worker_id,
            before=before,
            after=after,
            seeded_count=len(seeded),
            claimed_count=len(claimed),
            applied_count=len(applied_updates),
            completed_count=len(completed_ids),
            pending_count=len(self.queue.pending()),
            claimed_open_count=len(self.queue.claimed()),
            completed_todo_ids=completed_ids,
            failed_validation_count=len(failed_validation_ids),
            failed_validation_todo_ids=failed_validation_ids,
            applied_updates=applied_updates,
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
        final_evaluation = autoencoder.evaluate(samples)
        validation_final_evaluation = (
            autoencoder.evaluate(validation_samples)
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


def _metric_value(evaluation: AutoencoderEvaluation, name: str) -> Optional[float]:
    return {
        "cosine_loss": evaluation.cosine_loss,
        "cross_entropy_loss": evaluation.cross_entropy_loss,
        "embedding_cosine_similarity": evaluation.embedding_cosine_similarity,
        "frame_ranking_loss": evaluation.frame_ranking_loss,
        "reconstruction_loss": evaluation.reconstruction_loss,
        "symbolic_validity_penalty": evaluation.symbolic_validity_penalty,
    }.get(name)


__all__ = [
    "LossSnapshot",
    "ModalLossTodoGenerator",
    "ModalOptimizationRun",
    "ModalOptimizationStep",
    "ModalTodo",
    "ModalTodoQueue",
    "ModalTodoSupervisor",
]
