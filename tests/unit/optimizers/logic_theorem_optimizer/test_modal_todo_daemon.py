"""Tests for loss-driven modal TODO generation and batch claiming."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    LossSnapshot,
    ModalLossTodoGenerator,
    ModalTodoQueue,
    ModalTodoSupervisor,
)


def test_loss_generator_turns_high_losses_into_actionable_todos() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice and a hearing before a final order.",
    )
    snapshot = LossSnapshot.from_sample(
        sample,
        extra_losses={
            "cosine_loss": 0.31,
            "cross_entropy_loss": 0.72,
            "frame_ranking_loss": 2.0,
        },
    )

    todos = ModalLossTodoGenerator().generate([snapshot])

    assert [todo.action for todo in todos] == [
        "improve_bm25_frame_selector",
        "improve_modal_family_classifier",
        "improve_encoder_decoder_reconstruction",
    ]
    assert todos[0].loss_name == "frame_ranking_loss"
    assert todos[0].sample_ids == [sample.sample_id]
    assert todos[0].citations == ["5 U.S.C. 552"]


def test_generator_creates_parser_rule_todo_when_no_formulas_are_found() -> None:
    sample = build_us_code_sample(
        title="18",
        section="1",
        text="This section contains definitions and background.",
    )
    snapshot = LossSnapshot.from_sample(sample)

    todos = ModalLossTodoGenerator().generate([snapshot])

    assert len(todos) == 1
    assert todos[0].action == "add_deterministic_parser_rule"
    assert todos[0].loss_name == "parser_formula_count"


def test_queue_claims_multiple_pending_todos_at_once() -> None:
    generator = ModalLossTodoGenerator()
    snapshots = [
        LossSnapshot(
            sample_id=f"sample-{index}",
            citation=f"{index} U.S.C. 1",
            losses={"cross_entropy_loss": 0.2 + index},
            parser_formula_count=1,
        )
        for index in range(4)
    ]
    queue = ModalTodoQueue(generator.generate(snapshots))

    claimed = queue.claim_batch(worker_id="worker-a", max_items=3)

    assert len(claimed) == 3
    assert all(todo.status == "claimed" for todo in claimed)
    assert all(todo.claimed_by == "worker-a" for todo in claimed)
    assert len(queue.pending()) == 1
    assert queue.claim_batch(worker_id="worker-b", max_items=10)[0].sample_ids == ["sample-0"]


def test_queue_jsonl_roundtrip_preserves_claim_state(tmp_path) -> None:
    todo = ModalLossTodoGenerator().generate(
        [
            LossSnapshot(
                sample_id="sample-1",
                citation="1 U.S.C. 1",
                losses={"cosine_loss": 0.2},
                parser_formula_count=1,
            )
        ]
    )[0]
    queue = ModalTodoQueue([todo])
    queue.claim_batch(worker_id="worker-a", max_items=1)
    path = tmp_path / "modal-todos.jsonl"

    queue.save_jsonl(path)
    loaded = ModalTodoQueue.load_jsonl(path)

    assert len(loaded.claimed()) == 1
    assert loaded.claimed()[0].claimed_by == "worker-a"


def test_supervisor_seeds_and_claims_loss_todos_from_samples() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1983",
        text="A person may bring an action when rights are deprived under color of law.",
    )
    sample.losses["cross_entropy_loss"] = 0.5
    supervisor = ModalTodoSupervisor()

    seeded = supervisor.seed_from_evaluation([sample])
    claimed = supervisor.claim_next_batch(worker_id="daemon-worker", max_items=2)

    assert len(seeded) == 1
    assert claimed[0].action == "improve_modal_family_classifier"
    assert claimed[0].claimed_by == "daemon-worker"


def test_supervisor_optimize_once_validates_loss_improvement_before_completion() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice and a hearing before a final order.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor()
    before = autoencoder.evaluate([sample])

    step = supervisor.optimize_once(
        [sample],
        autoencoder=autoencoder,
        worker_id="daemon-worker",
        max_items=4,
        learning_rate=0.5,
    )

    assert step.after.cross_entropy_loss < before.cross_entropy_loss
    assert step.after.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert step.completed_count >= 2
    assert step.cross_entropy_delta > 0.0
    assert step.cosine_similarity_delta > 0.0
    assert supervisor.queue.status_counts()["completed"] == step.completed_count


def test_validation_gating_rejects_sample_memorization_without_holdout_gain() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice and a hearing before a final order.",
    )
    validation = build_us_code_sample(
        title="1",
        section="1",
        text="This section contains definitions and background material.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor(
        generator=ModalLossTodoGenerator(
            thresholds={"cosine_loss": 2.0, "reconstruction_loss": 2.0}
        )
    )

    step = supervisor.optimize_once(
        [train],
        validation_samples=[validation],
        autoencoder=autoencoder,
        worker_id="daemon-worker",
        max_items=4,
        learning_rate=0.5,
    )

    assert step.after.cross_entropy_loss < step.before.cross_entropy_loss
    assert step.validation_after is not None
    assert step.validation_before is not None
    assert step.validation_after.cross_entropy_loss >= step.validation_before.cross_entropy_loss
    assert step.completed_count == 0
    assert step.failed_validation_count == step.claimed_count
    assert supervisor.queue.status_counts()["failed_validation"] == step.claimed_count
    assert not step.improved


def test_validation_gating_completes_todos_only_when_holdout_improves() -> None:
    train = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )
    validation = build_us_code_sample(
        title="5",
        section="553",
        text="The agency must make notices promptly available.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor()

    step = supervisor.optimize_once(
        [train],
        validation_samples=[validation],
        autoencoder=autoencoder,
        worker_id="daemon-worker",
        max_items=4,
        learning_rate=0.5,
    )

    assert step.validation_before is not None
    assert step.validation_after is not None
    assert step.validation_after.cross_entropy_loss < step.validation_before.cross_entropy_loss
    assert step.completed_count >= 1
    assert supervisor.queue.status_counts()["completed"] == step.completed_count
    assert step.improved


def test_supervisor_optimization_run_reduces_ce_and_reconstruction_loss(tmp_path) -> None:
    sample = build_us_code_sample(
        title="42",
        section="1983",
        text="A person may bring an action when rights are deprived under color of law.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    supervisor = ModalTodoSupervisor()
    before = autoencoder.evaluate([sample])

    run = supervisor.optimize(
        [sample],
        autoencoder=autoencoder,
        worker_id="daemon-worker",
        max_iterations=3,
        max_items=3,
        learning_rate=0.5,
    )
    path = tmp_path / "run.json"
    run.save_json(path)

    assert len(run.steps) >= 1
    assert run.final_evaluation.cross_entropy_loss < before.cross_entropy_loss
    assert run.final_evaluation.reconstruction_loss < before.reconstruction_loss
    assert run.final_evaluation.embedding_cosine_similarity == pytest.approx(1.0)
    assert run.to_dict()["steps"]
    assert path.read_text(encoding="utf-8").startswith("{")
