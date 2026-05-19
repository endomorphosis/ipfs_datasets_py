"""Tests for loss-driven modal TODO generation and batch claiming."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    LossSnapshot,
    ModalLossTodoGenerator,
    ModalOptimizerPolicy,
    ModalProgramSynthesisTodoGenerator,
    ModalTodo,
    ModalTodoQueue,
    ModalTodoSupervisor,
    select_program_synthesis_vector_bundle,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    apply_codex_worktree_changes_to_main,
    build_paired_daemon_commands,
    compiler_ir_metric_block,
    create_codex_work_packet,
    execute_codex_work_packet,
    program_synthesis_status_block,
    refresh_codex_work_packet_patch,
    resolve_codex_worktree_repo_root,
    run_tests,
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
    assert todos[0].metadata["optimizer_role"] == "program_synthesis"
    assert todos[1].metadata["optimizer_role"] == "autoencoder_sgd"


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
    assert todos[0].metadata["execution_target"] == "codex_program_repair"


def test_loss_generator_creates_flogic_alignment_todos() -> None:
    snapshot = LossSnapshot(
        sample_id="sample-flogic",
        citation="5 U.S.C. 552",
        losses={
            "flogic_similarity_loss": 0.4,
            "ontology_violation_count": 1.0,
        },
        selected_frame="administrative_notice_hearing",
        parser_formula_count=1,
    )

    todos = ModalLossTodoGenerator().generate([snapshot])

    assert [todo.action for todo in todos] == [
        "repair_flogic_ontology_constraints",
        "improve_flogic_frame_alignment",
    ]
    assert todos[0].metadata["selected_frame"] == "administrative_notice_hearing"
    assert all(todo.metadata["optimizer_role"] == "program_synthesis" for todo in todos)


def test_loss_generator_routes_text_roundtrip_losses_to_program_synthesis() -> None:
    snapshot = LossSnapshot(
        sample_id="sample-roundtrip",
        citation="5 U.S.C. 552",
        losses={
            "modal_span_coverage_loss": 0.4,
            "text_reconstruction_loss": 0.2,
        },
        selected_frame="administrative_notice_hearing",
        parser_formula_count=1,
    )

    todos = ModalLossTodoGenerator().generate([snapshot])

    assert [todo.action for todo in todos] == [
        "increase_modal_ir_span_coverage",
        "refine_semantic_decompiler_reconstruction",
    ]
    assert all(todo.metadata["optimizer_role"] == "program_synthesis" for todo in todos)
    assert all(todo.metadata["execution_target"] == "codex_program_repair" for todo in todos)


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


def test_queue_can_claim_autoencoder_todos_without_claiming_program_synthesis() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )
    snapshot = LossSnapshot.from_sample(
        sample,
        extra_losses={
            "cross_entropy_loss": 0.4,
            "frame_ranking_loss": 1.0,
        },
    )
    queue = ModalTodoQueue(ModalLossTodoGenerator().generate([snapshot]))

    claimed = queue.claim_batch(
        worker_id="worker-a",
        max_items=10,
        optimizer_role="autoencoder_sgd",
    )

    assert [todo.metadata["optimizer_role"] for todo in claimed] == ["autoencoder_sgd"]
    assert queue.pending(optimizer_role="program_synthesis")
    assert queue.pending_count(optimizer_role="program_synthesis") == 1
    assert queue.claimed_count(optimizer_role="autoencoder_sgd") == 1
    assert queue.role_status_counts()["program_synthesis"]["pending"] == 1


def test_queue_merge_preserves_externally_claimed_program_synthesis_todos() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )
    snapshot = LossSnapshot.from_sample(
        sample,
        extra_losses={"frame_ranking_loss": 1.0},
    )
    todo = ModalLossTodoGenerator().generate([snapshot])[0]
    latest = ModalTodoQueue([todo.__class__.from_dict(todo.to_dict())])
    incoming = ModalTodoQueue([todo.__class__.from_dict(todo.to_dict())])
    latest.claim_batch(
        worker_id="codex-program-worker",
        max_items=1,
        optimizer_role="program_synthesis",
    )

    latest.merge_from(incoming, preserve_claimed_role="program_synthesis")

    assert latest.claimed_count(optimizer_role="program_synthesis") == 1
    assert latest.claimed(optimizer_role="program_synthesis")[0].claimed_by == "codex-program-worker"


def test_queue_merge_preserves_externally_completed_program_synthesis_todos() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )
    snapshot = LossSnapshot.from_sample(
        sample,
        extra_losses={"frame_ranking_loss": 1.0},
    )
    todo = ModalLossTodoGenerator().generate([snapshot])[0]
    latest = ModalTodoQueue([todo.__class__.from_dict(todo.to_dict())])
    incoming = ModalTodoQueue([todo.__class__.from_dict(todo.to_dict())])
    latest.claim_batch(
        worker_id="codex-program-worker",
        max_items=1,
        optimizer_role="program_synthesis",
    )
    latest.complete(todo.todo_id)
    incoming.claim_batch(
        worker_id="stale-codex-view",
        max_items=1,
        optimizer_role="program_synthesis",
    )

    latest.merge_from(incoming, preserve_claimed_role="program_synthesis")

    completed = latest.get(todo.todo_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.claimed_by == "codex-program-worker"


def test_queue_semantic_dedupe_collapses_program_synthesis_loss_duplicates() -> None:
    snapshot = LossSnapshot(
        sample_id="sample-1",
        citation="1 U.S.C. 1",
        losses={"symbolic_validity_penalty": 1.0},
        parser_formula_count=0,
    )
    todos = ModalLossTodoGenerator().generate([snapshot])
    assert len([todo for todo in todos if todo.action == "add_deterministic_parser_rule"]) == 2

    queue = ModalTodoQueue()
    added = queue.add_many(todos)

    assert added == 1
    [todo] = queue.pending(optimizer_role="program_synthesis")
    assert todo.metadata["target_component"] == "modal.compiler"
    assert todo.metadata["dedupe_signature"]
    assert todo.metadata["program_synthesis_scope"] == "compiler_parser"


def test_queue_semantic_dedupe_removes_near_duplicate_program_synthesis_items() -> None:
    base_metadata = {
        "dedupe_signature": "custom",
        "optimizer_role": "program_synthesis",
        "target_component": "modal.ir_decompiler",
    }
    first = ModalTodo(
        todo_id="program-a",
        action="refine_typed_ir_or_decompiler_slots",
        objective="first",
        sample_ids=["a", "b", "c", "d"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata=dict(base_metadata),
    )
    second = ModalTodo(
        todo_id="program-b",
        action="refine_typed_ir_or_decompiler_slots",
        objective="second",
        sample_ids=["a", "b", "c", "e"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=5.0,
        metadata={**base_metadata, "dedupe_signature": "custom-2"},
    )
    queue = ModalTodoQueue([first, second])

    removed = queue.deduplicate_semantic(
        optimizer_role="program_synthesis",
        near_duplicate_jaccard=0.6,
    )

    assert removed == 1
    assert queue.get("program-a") is not None
    assert queue.get("program-b") is None


def test_queue_semantic_dedupe_rejects_completed_bundle_duplicates() -> None:
    metadata = {
        "optimizer_role": "program_synthesis",
        "program_synthesis_scope": "frame_logic",
        "semantic_bundle_key": "frame:audit",
        "target_component": "modal.frame_logic",
    }
    completed = ModalTodo(
        todo_id="program-completed",
        action="audit_frame_logic_terms",
        objective="audit frame terms",
        sample_ids=["a"],
        citations=["1 U.S.C. 1"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=5.0,
        status="completed",
        metadata=dict(metadata),
    )
    duplicate = ModalTodo(
        todo_id="program-duplicate",
        action="audit_frame_logic_terms",
        objective="audit frame terms again",
        sample_ids=["b"],
        citations=["2 U.S.C. 2"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=10.0,
        metadata=dict(metadata),
    )
    queue = ModalTodoQueue([completed, duplicate])

    removed = queue.deduplicate_semantic(optimizer_role="program_synthesis")

    assert removed == 1
    representative = queue.get("program-completed")
    assert representative is not None
    assert representative.status == "completed"
    assert queue.get("program-duplicate") is None
    assert representative.sample_ids == ["a", "b"]
    assert representative.metadata["deduped_duplicate_count"] == 1


def test_supervisor_can_claim_program_synthesis_by_ast_scope() -> None:
    compiler = ModalTodo(
        todo_id="program-compiler",
        action="add_deterministic_parser_rule",
        objective="compiler",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=5.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_parser",
            "target_component": "modal.compiler",
        },
    )
    frame = ModalTodo(
        todo_id="program-frame",
        action="audit_frame_logic_terms",
        objective="frame",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "frame_logic",
            "target_component": "modal.frame_logic",
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([compiler, frame]))

    claimed = supervisor.claim_program_synthesis_batch(
        worker_id="frame-worker",
        max_items=2,
        program_synthesis_scope="frame_logic",
    )

    assert [todo.todo_id for todo in claimed] == ["program-frame"]
    assert supervisor.queue.get("program-compiler").status == "pending"
    assert supervisor.queue.get("program-frame").status == "claimed"


def test_supervisor_can_claim_semantic_program_synthesis_bundle_by_ast_scope() -> None:
    shared_metadata = {
        "optimizer_role": "program_synthesis",
        "program_synthesis_scope": "compiler_ambiguity",
        "target_component": "modal.compiler.ambiguity",
        "semantic_bundle_key": "ambiguity:temporal->deontic",
    }
    anchor = ModalTodo(
        todo_id="program-anchor",
        action="add_or_review_modal_ambiguity_policy",
        objective="ambiguity",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata=dict(shared_metadata),
    )
    sibling = ModalTodo(
        todo_id="program-sibling",
        action="add_or_review_modal_ambiguity_policy",
        objective="ambiguity",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=8.0,
        metadata=dict(shared_metadata),
    )
    different_family = ModalTodo(
        todo_id="program-different-family",
        action="add_or_review_modal_ambiguity_policy",
        objective="ambiguity",
        sample_ids=["c"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=9.0,
        metadata={
            **shared_metadata,
            "semantic_bundle_key": "ambiguity:deontic->conditional_normative",
        },
    )
    frame = ModalTodo(
        todo_id="program-frame",
        action="audit_frame_logic_terms",
        objective="frame",
        sample_ids=["d"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=12.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "frame_logic",
            "target_component": "modal.frame_logic",
            "semantic_bundle_key": "frame",
        },
    )
    supervisor = ModalTodoSupervisor(
        queue=ModalTodoQueue([anchor, sibling, different_family, frame])
    )

    claimed = supervisor.claim_program_synthesis_batch(
        worker_id="compiler-worker",
        max_items=3,
        program_synthesis_scope="compiler_ambiguity",
        semantic_bundle=True,
    )

    assert [todo.todo_id for todo in claimed] == ["program-anchor", "program-sibling"]
    assert supervisor.queue.get("program-different-family").status == "pending"
    assert supervisor.queue.get("program-frame").status == "pending"


def test_queue_can_claim_vector_program_synthesis_bundle_by_ast_scope() -> None:
    shared_metadata = {
        "optimizer_role": "program_synthesis",
        "program_synthesis_scope": "compiler_ambiguity",
        "target_component": "modal.compiler.ambiguity",
    }
    anchor = ModalTodo(
        todo_id="program-anchor",
        action="add_or_review_modal_ambiguity_policy",
        objective="temporal deontic modal ambiguity",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={**shared_metadata, "semantic_bundle_key": "ambiguity:temporal->deontic"},
    )
    vector_sibling = ModalTodo(
        todo_id="program-vector-sibling",
        action="add_or_review_modal_ambiguity_policy",
        objective="deadline obligation ambiguity",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=8.0,
        metadata={**shared_metadata, "semantic_bundle_key": "ambiguity:deadline->obligation"},
    )
    distant_same_scope = ModalTodo(
        todo_id="program-distant",
        action="add_or_review_modal_ambiguity_policy",
        objective="unrelated registry issue",
        sample_ids=["c"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=9.0,
        metadata={**shared_metadata, "semantic_bundle_key": "ambiguity:unrelated"},
    )
    different_scope = ModalTodo(
        todo_id="program-frame",
        action="audit_frame_logic_terms",
        objective="temporal deontic frame issue",
        sample_ids=["d"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=12.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "frame_logic",
            "target_component": "modal.frame_logic",
        },
    )
    queue = ModalTodoQueue([anchor, vector_sibling, distant_same_scope, different_scope])

    claimed = queue.claim_vector_bundle(
        worker_id="compiler-worker",
        max_items=3,
        optimizer_role="program_synthesis",
        metadata_filter={"program_synthesis_scope": "compiler_ambiguity"},
        vectors_by_todo_id={
            "program-anchor": [1.0, 0.0],
            "program-vector-sibling": [0.95, 0.05],
            "program-distant": [0.0, 1.0],
            "program-frame": [1.0, 0.0],
        },
        min_similarity=0.9,
    )

    assert [todo.todo_id for todo in claimed] == ["program-anchor", "program-vector-sibling"]
    assert queue.get("program-distant").status == "pending"
    assert queue.get("program-frame").status == "pending"
    assert claimed[1].metadata["vector_bundle_anchor_id"] == "program-anchor"
    assert claimed[1].metadata["vector_bundle_similarity"] >= 0.9


def test_vector_bundle_fill_uses_same_target_component_only() -> None:
    shared_metadata = {
        "optimizer_role": "program_synthesis",
        "program_synthesis_scope": "compiler_registry",
        "target_component": "modal.compiler.registry",
    }
    anchor = ModalTodo(
        todo_id="program-anchor",
        action="refine_modal_family_cue_rules",
        objective="registry cue repair",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata=shared_metadata,
    )
    strict_neighbor = ModalTodo(
        todo_id="program-strict",
        action="refine_modal_family_cue_rules",
        objective="near registry cue repair",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=9.0,
        metadata=shared_metadata,
    )
    fill_neighbor = ModalTodo(
        todo_id="program-fill",
        action="refine_modal_family_cue_rules",
        objective="adjacent registry cue repair",
        sample_ids=["c"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=8.0,
        metadata=shared_metadata,
    )
    different_target = ModalTodo(
        todo_id="program-ambiguity",
        action="add_or_review_modal_ambiguity_policy",
        objective="ambiguity repair",
        sample_ids=["d"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=7.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
            "target_component": "modal.compiler.ambiguity",
        },
    )

    selected = select_program_synthesis_vector_bundle(
        [anchor, strict_neighbor, fill_neighbor, different_target],
        vectors_by_todo_id={
            "program-anchor": [1.0, 0.0],
            "program-strict": [0.95, 0.05],
            "program-fill": [0.6, 0.8],
            "program-ambiguity": [0.6, 0.8],
        },
        max_items=4,
        min_similarity=0.9,
        fill_min_similarity=0.5,
    )

    assert [item["todo"].todo_id for item in selected] == [
        "program-anchor",
        "program-strict",
        "program-fill",
    ]
    assert selected[2]["fill_reason"] == "same_target"


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


def test_supervisor_caps_loss_derived_program_synthesis_todos() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )
    sample.losses.update(
        {
            "cross_entropy_loss": 0.5,
            "frame_ranking_loss": 1.0,
        }
    )
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(max_program_synthesis_pending=0)
    )

    seeded = supervisor.seed_from_evaluation([sample])

    assert [todo.metadata["optimizer_role"] for todo in seeded] == ["autoencoder_sgd"]
    assert supervisor.queue.pending_count(optimizer_role="autoencoder_sgd") == 1
    assert supervisor.queue.pending_count(optimizer_role="program_synthesis") == 0


def test_program_synthesis_generator_clusters_stable_autoencoder_residuals() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    generator = ModalProgramSynthesisTodoGenerator(min_support=2)

    todos = generator.generate(samples, autoencoder=autoencoder)

    assert todos
    assert any(todo.action == "refine_typed_ir_or_decompiler_slots" for todo in todos)
    assert all(todo.metadata["optimizer_role"] == "program_synthesis" for todo in todos)
    assert all(todo.metadata["execution_target"] == "codex_program_repair" for todo in todos)
    assert all(todo.metadata["support_count"] >= 2 for todo in todos)
    assert all(todo.metadata["hint_evidence"] for todo in todos)
    for todo in todos:
        assert {
            evidence["hint_id"] for evidence in todo.metadata["hint_evidence"]
        } == set(todo.metadata["hint_ids"])
        assert all(
            evidence.get("sample_id") in todo.sample_ids
            for evidence in todo.metadata["hint_evidence"]
        )


def test_supervisor_optimizes_autoencoder_first_and_leaves_program_synthesis_backlog() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )

    step = supervisor.optimize_once(
        samples,
        autoencoder=autoencoder,
        worker_id="daemon-worker",
        max_items=4,
        learning_rate=0.5,
    )

    assert step.autoencoder_claimed_count == step.claimed_count
    assert step.completed_count >= 1
    assert step.program_synthesis_seeded_count >= 1
    assert step.program_synthesis_pending_count >= 1
    assert all(
        todo.metadata["optimizer_role"] == "program_synthesis"
        for todo in supervisor.queue.pending(optimizer_role="program_synthesis")
    )


def test_supervisor_caps_program_synthesis_backlog() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(
            max_program_synthesis_pending=1,
            program_synthesis_min_support=2,
        )
    )

    seeded = supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=autoencoder,
    )
    seeded_again = supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=autoencoder,
    )

    assert len(seeded) == 1
    assert seeded_again == []
    assert supervisor.last_program_synthesis_deduped_count >= 1
    assert supervisor.queue.pending_count(optimizer_role="program_synthesis") == 1


def test_supervisor_can_claim_program_synthesis_batch_for_codex_worker() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=autoencoder,
    )

    claimed = supervisor.claim_program_synthesis_batch(
        worker_id="codex-program-worker",
        max_items=2,
    )

    assert claimed
    assert all(todo.claimed_by == "codex-program-worker" for todo in claimed)
    assert all(
        todo.metadata["optimizer_role"] == "program_synthesis"
        for todo in claimed
    )
    assert supervisor.queue.claimed_count(optimizer_role="program_synthesis") == len(claimed)
    status = program_synthesis_status_block(supervisor.queue, supervisor.policy)
    assert status["claimed"] == len(claimed)
    assert status["execution_mode"] == "queued_for_external_codex_worker"


def test_supervisor_program_synthesis_status_reuses_queue_role_counts() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    seeded = supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    assert seeded
    supervisor.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )

    status = supervisor.program_synthesis_status(
        execution_mode="codex_cli_executor",
    )

    assert status["execution_mode"] == "codex_cli_executor"
    assert status["claimed"] == 1
    assert status["pending"] >= 0
    assert status["completed"] == 0


def test_supervisor_program_synthesis_summary_writes_standard_keys() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    supervisor.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    summary = {}

    status = supervisor.update_program_synthesis_summary(
        summary,
        execution_mode="codex_cli_executor",
    )

    assert summary["program_synthesis_claimed"] == status["claimed"]
    assert summary["program_synthesis_pending"] == status["pending"]
    assert summary["program_synthesis_completed"] == status["completed"]
    assert summary["codex_program_synthesis_execution_mode"] == "codex_cli_executor"


def test_supervisor_finalize_program_synthesis_batch_applies_queue_transitions() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed = supervisor.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    assert claimed

    completed = supervisor.finalize_program_synthesis_batch(
        claimed,
        codex_exec_status="succeeded",
        patch_status="created",
    )
    assert completed["updated"] is True
    assert completed["completed_count"] == 1
    assert completed["failed_validation_count"] == 0
    assert supervisor.queue.get(claimed[0].todo_id).status == "completed"

    supervisor_fail = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor_fail.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed_fail = supervisor_fail.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    failed = supervisor_fail.finalize_program_synthesis_batch(
        claimed_fail,
        codex_exec_status="failed",
        patch_status="awaiting_codex_changes",
    )
    assert failed["updated"] is True
    assert failed["completed_count"] == 0
    assert failed["failed_validation_count"] == 1
    assert failed["reason"] == "codex_exec_failed"
    assert supervisor_fail.queue.get(claimed_fail[0].todo_id).status == "failed_validation"

    supervisor_timeout_patch = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor_timeout_patch.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed_timeout_patch = supervisor_timeout_patch.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    timeout_patch = supervisor_timeout_patch.finalize_program_synthesis_batch(
        claimed_timeout_patch,
        codex_exec_status="timeout",
        patch_status="created",
    )
    assert timeout_patch["updated"] is True
    assert timeout_patch["completed_count"] == 1
    assert timeout_patch["failed_validation_count"] == 0
    assert supervisor_timeout_patch.queue.get(claimed_timeout_patch[0].todo_id).status == "completed"

    supervisor_applied = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor_applied.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed_applied = supervisor_applied.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    applied = supervisor_applied.finalize_program_synthesis_batch(
        claimed_applied,
        codex_exec_status="succeeded",
        patch_status="applied_to_main",
    )
    assert applied["updated"] is True
    assert applied["completed_count"] == 1
    assert applied["failed_validation_count"] == 0
    assert supervisor_applied.queue.get(claimed_applied[0].todo_id).status == "completed"


def test_build_paired_daemon_commands_share_autoencoder_queue_run_id() -> None:
    args = SimpleNamespace(
        run_id="paired-run",
        autoencoder_run_id=None,
        codex_run_id=None,
        duration_seconds=120.0,
        train_count=4,
        validation_count=2,
        max_inner_iterations=3,
        max_items=6,
        learning_rate=0.25,
        test_every_cycles=99,
        poll_seconds=1.5,
        paired_grace_seconds=300.0,
        worker_id="codex-worker",
        codex_exec_mode="packet_only",
        codex_command="codex",
        codex_model=None,
        codex_apply_mode="apply_to_main",
        codex_commit_mode="commit_applied",
        codex_scope="frame_logic",
        codex_sandbox="workspace-write",
        codex_timeout_seconds=30.0,
        warm_start_run_id=["warm-a", "warm-b"],
        warm_start_state=["/tmp/warm-state.json"],
    )

    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )

    assert paired["autoencoder_run_id"] == "paired-run-autoencoder"
    assert paired["codex_run_id"] == "paired-run-codex"
    assert paired["queue_run_id"] == "paired-run-autoencoder"
    assert "--queue-run-id" in paired["codex_command"]
    queue_index = paired["codex_command"].index("--queue-run-id")
    assert paired["codex_command"][queue_index + 1] == paired["queue_run_id"]
    duration_index = paired["codex_command"].index("--duration-seconds")
    assert paired["codex_command"][duration_index + 1] == "420.0"
    apply_index = paired["codex_command"].index("--codex-apply-mode")
    assert paired["codex_command"][apply_index + 1] == "apply_to_main"
    commit_index = paired["codex_command"].index("--codex-commit-mode")
    assert paired["codex_command"][commit_index + 1] == "commit_applied"
    scope_index = paired["codex_command"].index("--codex-scope")
    assert paired["codex_command"][scope_index + 1] == "frame_logic"
    assert paired["autoencoder_command"].count("--warm-start-run-id") == 2
    assert paired["autoencoder_command"].count("--warm-start-state") == 1


def test_build_paired_daemon_commands_respect_custom_child_run_ids_and_model() -> None:
    args = SimpleNamespace(
        run_id="paired-root",
        autoencoder_run_id="auto-child",
        codex_run_id="codex-child",
        duration_seconds=60.0,
        train_count=2,
        validation_count=1,
        max_inner_iterations=1,
        max_items=2,
        learning_rate=0.1,
        test_every_cycles=50,
        poll_seconds=2.0,
        worker_id=None,
        codex_exec_mode="codex_cli",
        codex_command="codex",
        codex_model="gpt-5.5",
        codex_apply_mode="patch_only",
        codex_commit_mode="none",
        codex_scope=None,
        codex_sandbox="workspace-write",
        codex_timeout_seconds=45.0,
        warm_start_run_id=[],
        warm_start_state=[],
    )

    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )

    assert paired["autoencoder_run_id"] == "auto-child"
    assert paired["codex_run_id"] == "codex-child"
    assert paired["queue_run_id"] == "auto-child"
    assert "--codex-model" in paired["codex_command"]
    model_index = paired["codex_command"].index("--codex-model")
    assert paired["codex_command"][model_index + 1] == "gpt-5.5"
    assert "--worker-id" not in paired["codex_command"]


def test_build_paired_daemon_commands_can_launch_parallel_scoped_codex_children() -> None:
    args = SimpleNamespace(
        run_id="parallel-root",
        autoencoder_run_id=None,
        codex_run_id=None,
        duration_seconds=60.0,
        train_count=2,
        validation_count=1,
        max_inner_iterations=1,
        max_items=3,
        learning_rate=0.1,
        test_every_cycles=50,
        poll_seconds=2.0,
        worker_id="codex-worker",
        codex_exec_mode="codex_cli",
        codex_command="codex",
        codex_model="gpt-5.3-codex",
        codex_apply_mode="apply_to_main",
        codex_commit_mode="commit_applied",
        codex_scope=None,
        codex_parallel_scopes="compiler_ambiguity,frame_logic",
        codex_bundle_mode="semantic",
        codex_sandbox="workspace-write",
        codex_timeout_seconds=45.0,
        paired_grace_seconds=120.0,
        warm_start_run_id=[],
        warm_start_state=[],
    )

    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )

    children = paired["codex_children"]
    assert [child["scope"] for child in children] == ["compiler_ambiguity", "frame_logic"]
    assert [child["run_id"] for child in children] == [
        "parallel-root-codex-compiler_ambiguity",
        "parallel-root-codex-frame_logic",
    ]
    assert all("--codex-bundle-mode" in child["command"] for child in children)
    assert all("--codex-scope" in child["command"] for child in children)
    assert "--codex-scope" in paired["codex_command"]
    assert paired["codex_command"][paired["codex_command"].index("--codex-scope") + 1] == "compiler_ambiguity"


def test_build_paired_daemon_commands_can_launch_multiple_workers_per_scope() -> None:
    args = SimpleNamespace(
        run_id="parallel-root",
        autoencoder_run_id=None,
        codex_run_id=None,
        duration_seconds=60.0,
        train_count=2,
        validation_count=1,
        max_inner_iterations=1,
        max_items=3,
        learning_rate=0.1,
        test_every_cycles=50,
        poll_seconds=2.0,
        worker_id="codex-worker",
        codex_exec_mode="codex_cli",
        codex_command="codex",
        codex_model="gpt-5.3-codex",
        codex_apply_mode="apply_to_main",
        codex_commit_mode="commit_applied",
        codex_scope=None,
        codex_parallel_scopes="compiler_ambiguity,frame_logic",
        codex_scope_workers=2,
        codex_bundle_mode="semantic",
        codex_sandbox="workspace-write",
        codex_timeout_seconds=45.0,
        paired_grace_seconds=120.0,
        warm_start_run_id=[],
        warm_start_state=[],
    )

    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )

    children = paired["codex_children"]
    assert [child["scope"] for child in children] == [
        "compiler_ambiguity",
        "compiler_ambiguity",
        "frame_logic",
        "frame_logic",
    ]
    assert [child["run_id"] for child in children] == [
        "parallel-root-codex-compiler_ambiguity-01",
        "parallel-root-codex-compiler_ambiguity-02",
        "parallel-root-codex-frame_logic-01",
        "parallel-root-codex-frame_logic-02",
    ]
    assert [child["worker_id"] for child in children] == [
        "codex-worker-compiler_ambiguity-01",
        "codex-worker-compiler_ambiguity-02",
        "codex-worker-frame_logic-01",
        "codex-worker-frame_logic-02",
    ]
    assert {
        child["command"][child["command"].index("--codex-scope") + 1]
        for child in children
    } == {"compiler_ambiguity", "frame_logic"}


def test_build_paired_daemon_commands_accepts_per_scope_worker_map() -> None:
    args = SimpleNamespace(
        run_id="parallel-root",
        autoencoder_run_id=None,
        codex_run_id=None,
        duration_seconds=60.0,
        train_count=2,
        validation_count=1,
        max_inner_iterations=1,
        max_items=3,
        learning_rate=0.1,
        test_every_cycles=50,
        poll_seconds=2.0,
        worker_id="codex-worker",
        codex_exec_mode="codex_cli",
        codex_command="codex",
        codex_model="gpt-5.3-codex",
        codex_apply_mode="apply_to_main",
        codex_commit_mode="commit_applied",
        codex_scope=None,
        codex_parallel_scopes="compiler_ambiguity,compiler_registry,frame_logic",
        codex_scope_workers=2,
        codex_scope_worker_map="compiler_ambiguity=2,compiler_registry=1,frame_logic=0",
        codex_bundle_mode="semantic",
        codex_sandbox="workspace-write",
        codex_timeout_seconds=45.0,
        paired_grace_seconds=120.0,
        warm_start_run_id=[],
        warm_start_state=[],
    )

    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )

    children = paired["codex_children"]
    assert [child["run_id"] for child in children] == [
        "parallel-root-codex-compiler_ambiguity-01",
        "parallel-root-codex-compiler_ambiguity-02",
        "parallel-root-codex-compiler_registry",
    ]
    assert [child["scope"] for child in children] == [
        "compiler_ambiguity",
        "compiler_ambiguity",
        "compiler_registry",
    ]


def test_build_paired_daemon_commands_pass_vector_bundle_options_to_children() -> None:
    args = SimpleNamespace(
        run_id="vector-root",
        autoencoder_run_id=None,
        codex_run_id=None,
        duration_seconds=60.0,
        train_count=2,
        validation_count=1,
        max_inner_iterations=1,
        max_items=3,
        learning_rate=0.1,
        test_every_cycles=50,
        poll_seconds=2.0,
        worker_id="codex-worker",
        codex_exec_mode="codex_cli",
        codex_command="codex",
        codex_model="gpt-5.3-codex",
        codex_apply_mode="apply_to_main",
        codex_commit_mode="commit_applied",
        codex_scope=None,
        codex_parallel_scopes="compiler_parser,ir_decompiler,frame_logic",
        codex_bundle_mode="vector",
        codex_vector_min_bundle_size=3,
        codex_vector_max_bundle_wait_seconds=180.0,
        codex_vector_min_similarity=0.81,
        codex_vector_fill_min_similarity=0.52,
        codex_vector_stale_drain_cooldown_seconds=90.0,
        codex_target_file_lane_lock_seconds=300.0,
        codex_target_file_lane_lock_scopes="compiler_registry",
        codex_vector_index_path="/tmp/codex-task-vectors.json",
        codex_task_embeddings_provider="local_adapter",
        codex_task_embeddings_model="thenlper/gte-small",
        codex_task_embeddings_device="cpu",
        codex_task_embeddings_batch_size=16,
        codex_vector_fallback_mode="hash",
        codex_merge_repair_mode="apply_3way",
        codex_merge_repair_attempts=1,
        codex_sandbox="workspace-write",
        codex_timeout_seconds=45.0,
        paired_grace_seconds=120.0,
        warm_start_run_id=[],
        warm_start_state=[],
    )

    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )

    children = paired["codex_children"]
    assert len(children) == 3
    for child in children:
        command = child["command"]
        assert command[command.index("--codex-bundle-mode") + 1] == "vector"
        assert command[command.index("--codex-vector-min-similarity") + 1] == "0.81"
        assert command[command.index("--codex-vector-fill-min-similarity") + 1] == "0.52"
        assert command[command.index("--codex-vector-min-bundle-size") + 1] == "3"
        assert command[command.index("--codex-vector-max-bundle-wait-seconds") + 1] == "180.0"
        assert command[command.index("--codex-vector-stale-drain-cooldown-seconds") + 1] == "90.0"
        assert command[command.index("--codex-target-file-lane-lock-seconds") + 1] == "300.0"
        assert command[command.index("--codex-target-file-lane-lock-scopes") + 1] == "compiler_registry"
        assert command[command.index("--codex-task-embeddings-provider") + 1] == "local_adapter"
        assert command[command.index("--codex-task-embeddings-model") + 1] == "thenlper/gte-small"
        assert command[command.index("--codex-task-embeddings-device") + 1] == "cpu"
        assert command[command.index("--codex-task-embeddings-batch-size") + 1] == "16"
        assert command[command.index("--codex-vector-index-path") + 1] == "/tmp/codex-task-vectors.json"


def test_codex_task_vector_index_uses_embeddings_router_and_cache(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_router_embeddings(texts, *, args):
        calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(runner, "_router_codex_task_embeddings", fake_router_embeddings)
    args = SimpleNamespace(
        codex_task_embeddings_provider="local_adapter",
        codex_task_embeddings_model=None,
        codex_task_embeddings_device=None,
        codex_task_embeddings_batch_size=8,
        codex_vector_fallback_mode="hash",
    )
    todo = ModalTodo(
        todo_id="program-vector-cache",
        action="add_or_review_modal_ambiguity_policy",
        objective="temporal deontic modal ambiguity",
        sample_ids=["a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
        },
    )
    index_path = tmp_path / "codex-task-vectors.json"

    vectors, report = runner._update_codex_task_vector_index(
        args=args,
        index_path=index_path,
        todos=[todo],
    )
    cached_vectors, cached_report = runner._update_codex_task_vector_index(
        args=args,
        index_path=index_path,
        todos=[todo],
    )

    assert vectors["program-vector-cache"] == [1.0, 0.0]
    assert cached_vectors == vectors
    assert report["backend"] == "embeddings_router"
    assert cached_report["refreshed_count"] == 0
    assert len(calls) == 1
    assert index_path.exists()


def test_vector_claim_waits_for_fresh_undersized_bundle(tmp_path, monkeypatch) -> None:
    todo = ModalTodo(
        todo_id="program-vector-singleton",
        action="add_or_review_modal_ambiguity_policy",
        objective="temporal deontic modal ambiguity",
        sample_ids=["a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([todo]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        return (
            {item.todo_id: [1.0, 0.0] for item in todos},
            {
                "backend": "embeddings_router",
                "fallback_reason": "",
                "indexed_count": len(list(todos)),
                "path": str(index_path),
                "provider": "local_adapter",
                "refreshed_count": len(list(todos)),
            },
        )

    monkeypatch.setattr(runner, "_update_codex_task_vector_index", fake_vector_index)
    args = SimpleNamespace(
        codex_scope="compiler_ambiguity",
        codex_vector_index_path=None,
        codex_vector_min_similarity=0.55,
        codex_vector_min_bundle_size=3,
        codex_vector_max_bundle_wait_seconds=600.0,
        max_items=6,
    )

    claimed, queue, status, report = runner._claim_vector_program_synthesis_batch(
        args=args,
        queue_path=queue_path,
        worker_id="codex-worker",
        policy=ModalOptimizerPolicy(),
        execution_mode="codex_cli_executor",
        summary={},
    )

    assert claimed == []
    assert queue.get("program-vector-singleton").status == "pending"
    assert status["pending"] == 1
    assert report["mode"] == "vector_waiting_for_bundle"
    assert report["proposed_selected_count"] == 1
    assert report["selected_count"] == 0


def test_vector_claim_allows_stale_undersized_bundle(tmp_path, monkeypatch) -> None:
    todo = ModalTodo(
        todo_id="program-vector-stale",
        action="add_or_review_modal_ambiguity_policy",
        objective="temporal deontic modal ambiguity",
        sample_ids=["a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        created_at="2020-01-01T00:00:00+00:00",
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([todo]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        return (
            {item.todo_id: [1.0, 0.0] for item in todos},
            {
                "backend": "embeddings_router",
                "fallback_reason": "",
                "indexed_count": len(list(todos)),
                "path": str(index_path),
                "provider": "local_adapter",
                "refreshed_count": len(list(todos)),
            },
        )

    monkeypatch.setattr(runner, "_update_codex_task_vector_index", fake_vector_index)
    args = SimpleNamespace(
        codex_scope="compiler_ambiguity",
        codex_vector_index_path=None,
        codex_vector_min_similarity=0.55,
        codex_vector_min_bundle_size=3,
        codex_vector_max_bundle_wait_seconds=60.0,
        max_items=6,
    )

    claimed, queue, status, report = runner._claim_vector_program_synthesis_batch(
        args=args,
        queue_path=queue_path,
        worker_id="codex-worker",
        policy=ModalOptimizerPolicy(),
        execution_mode="codex_cli_executor",
        summary={},
    )

    assert [todo.todo_id for todo in claimed] == ["program-vector-stale"]
    assert queue.get("program-vector-stale").status == "claimed"
    assert status["claimed"] == 1
    assert report["mode"] == "vector"
    assert report["selected_count"] == 1


def test_vector_claim_target_file_lane_waits_when_claimed_packet_overlaps(tmp_path, monkeypatch) -> None:
    claimed_todo = ModalTodo(
        todo_id="program-registry-active",
        action="refine_modal_family_cue_rules",
        objective="active registry repair",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
            "target_component": "modal.compiler.registry",
        },
    )
    claimed_todo.claim("other-codex-worker")
    pending_todo = ModalTodo(
        todo_id="program-registry-pending",
        action="refine_modal_family_cue_rules",
        objective="pending registry repair",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=9.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
            "target_component": "modal.compiler.registry",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([claimed_todo, pending_todo]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        return (
            {item.todo_id: [1.0, 0.0] for item in todos},
            {
                "backend": "embeddings_router",
                "fallback_reason": "",
                "indexed_count": len(list(todos)),
                "path": str(index_path),
                "provider": "local_adapter",
                "refreshed_count": len(list(todos)),
            },
        )

    monkeypatch.setattr(runner, "_update_codex_task_vector_index", fake_vector_index)
    args = SimpleNamespace(
        codex_scope="compiler_registry",
        codex_target_file_lane_lock_seconds=600.0,
        codex_vector_index_path=None,
        codex_vector_min_similarity=0.55,
        codex_vector_fill_min_similarity=None,
        codex_vector_min_bundle_size=1,
        codex_vector_max_bundle_wait_seconds=0.0,
        max_items=3,
    )

    claimed, queue, status, report = runner._claim_vector_program_synthesis_batch(
        args=args,
        queue_path=queue_path,
        worker_id="codex-worker",
        policy=ModalOptimizerPolicy(),
        execution_mode="codex_cli_executor",
        summary={},
    )

    assert claimed == []
    assert queue.get("program-registry-pending").status == "pending"
    assert status["pending"] == 1
    assert report["mode"] == "vector_target_file_lanes_busy"
    assert report["target_file_lane_locked_count"] == 1


def test_vector_claim_stale_drain_lease_throttles_parallel_singletons(tmp_path, monkeypatch) -> None:
    first = ModalTodo(
        todo_id="program-registry-first",
        action="refine_modal_family_cue_rules",
        objective="first stale registry repair",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        created_at="2020-01-01T00:00:00+00:00",
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
            "target_component": "modal.compiler.registry",
            "semantic_bundle_key": "registry:modal-cue",
        },
    )
    second = ModalTodo(
        todo_id="program-registry-second",
        action="refine_modal_family_cue_rules",
        objective="second stale registry repair",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=9.0,
        created_at="2020-01-01T00:00:00+00:00",
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
            "target_component": "modal.compiler.registry",
            "semantic_bundle_key": "registry:modal-cue",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([first, second]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        return (
            {
                "program-registry-first": [1.0, 0.0],
                "program-registry-second": [0.0, 1.0],
            },
            {
                "backend": "embeddings_router",
                "fallback_reason": "",
                "indexed_count": len(list(todos)),
                "path": str(index_path),
                "provider": "local_adapter",
                "refreshed_count": len(list(todos)),
            },
        )

    monkeypatch.setattr(runner, "_update_codex_task_vector_index", fake_vector_index)
    args = SimpleNamespace(
        codex_scope="compiler_registry",
        codex_target_file_lane_lock_seconds=0.0,
        codex_vector_index_path=None,
        codex_vector_min_similarity=0.99,
        codex_vector_fill_min_similarity=None,
        codex_vector_min_bundle_size=3,
        codex_vector_max_bundle_wait_seconds=60.0,
        codex_vector_stale_drain_cooldown_seconds=300.0,
        max_items=3,
    )

    claimed_first, _, _, first_report = runner._claim_vector_program_synthesis_batch(
        args=args,
        queue_path=queue_path,
        worker_id="codex-worker-1",
        policy=ModalOptimizerPolicy(),
        execution_mode="codex_cli_executor",
        summary={},
    )
    claimed_second, queue, status, second_report = runner._claim_vector_program_synthesis_batch(
        args=args,
        queue_path=queue_path,
        worker_id="codex-worker-2",
        policy=ModalOptimizerPolicy(),
        execution_mode="codex_cli_executor",
        summary={},
    )

    assert [todo.todo_id for todo in claimed_first] == ["program-registry-first"]
    assert first_report["stale_drain_lease"]["acquired"] is True
    assert claimed_second == []
    assert queue.get("program-registry-second").status == "pending"
    assert status["pending"] == 1
    assert second_report["mode"] == "vector_waiting_for_stale_drain_lease"
    assert second_report["stale_drain_lease"]["held_by"] == "codex-worker-1"


def test_codex_worktree_repo_root_prefers_nested_ipfs_dataset_checkout(tmp_path) -> None:
    parent = tmp_path / "site"
    nested = parent / "ipfs_datasets_py"
    modal_dir = nested / "ipfs_datasets_py" / "logic" / "modal"
    modal_dir.mkdir(parents=True)
    (modal_dir / "codec.py").write_text("# modal codec placeholder\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    parent.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=nested, check=True, capture_output=True, text=True)

    assert resolve_codex_worktree_repo_root(parent) == nested.resolve()
    assert resolve_codex_worktree_repo_root(nested) == nested.resolve()


def test_run_tests_uses_nested_ipfs_dataset_checkout(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "site"
    nested = parent / "ipfs_datasets_py"
    test_dir = nested / "tests" / "unit" / "optimizers" / "logic_theorem_optimizer"
    modal_test_dir = nested / "tests" / "unit_tests" / "logic" / "modal"
    test_dir.mkdir(parents=True)
    modal_test_dir.mkdir(parents=True)
    (nested / "ipfs_datasets_py" / "logic" / "modal").mkdir(parents=True)
    for path in [
        test_dir / "test_modal_autoencoder.py",
        test_dir / "test_modal_todo_daemon.py",
        test_dir / "test_uscode_dataset.py",
        test_dir / "test_spacy_modal_codec.py",
        modal_test_dir / "test_modal_codec.py",
    ]:
        path.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=parent, check=True, capture_output=True, text=True)
    subprocess.run(["git", "init"], cwd=nested, check=True, capture_output=True, text=True)
    captured = {}

    def fake_run(cmd, **kwargs):
        if list(cmd[:1]) != ["pytest"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(cmd, 0, stdout="passed\n", stderr="")

    with monkeypatch.context() as context:
        context.setattr(subprocess, "run", fake_run)
        report = run_tests(parent, tmp_path / "reports", 1)

    assert captured["cwd"] == nested.resolve()
    assert report["test_root"] == str(nested.resolve())
    assert report["exit_code"] == 0


def _create_git_repo_with_program_synthesis_packet(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)

    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency must provide notice within 30 days.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency must provide notice before adopting a rule.",
        ),
    ]
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed = supervisor.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )

    packet = create_codex_work_packet(
        cycle=1,
        queue_path=tmp_path / "queue.jsonl",
        queue_run_id="queue-run",
        repo_root=repo,
        run_id="codex-run",
        todos=claimed,
        work_dir=tmp_path / "codex-work",
        worker_id="codex-worker",
    )
    return repo, packet


def test_codex_work_packet_creates_git_worktree_and_patch_slot(tmp_path) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)

    assert packet["packet_path"]
    assert packet["task_path"]
    assert packet["todo_list_path"]
    assert packet["todo_markdown_path"]
    assert packet["task_source"] == "autoencoder_supervisor_program_synthesis_queue"
    assert packet["worktree_path"]
    assert packet["patch_path"] is None
    assert packet["patch_status"] == "awaiting_codex_changes"
    assert packet["program_synthesis_scopes"]
    assert packet["semantic_bundle_keys"]
    assert packet["suggested_target_files"]
    assert (tmp_path / "codex-work" / "packet-000001" / "packet.json").exists()
    assert (tmp_path / "codex-work" / "packet-000001" / "TODO_LIST.jsonl").exists()
    assert (tmp_path / "codex-work" / "packet-000001" / "TODO_LIST.md").exists()
    task_text = (tmp_path / "codex-work" / "packet-000001" / "CODEX_TASK.md").read_text()
    assert "autoencoder/supervisor output" in task_text
    packet_data = json.loads((tmp_path / "codex-work" / "packet-000001" / "packet.json").read_text())
    assert packet_data["worktree_path"] == packet["worktree_path"]
    assert packet_data["todos"][0]["metadata"]["hint_evidence"]

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_refresh_creates_patch_after_worktree_edit(tmp_path) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    readme = Path(packet["worktree_path"]) / "README.md"
    readme.write_text("test repo\nchanged by codex packet\n", encoding="utf-8")

    updated = refresh_codex_work_packet_patch(packet)

    assert updated["patch_status"] == "created"
    assert updated["patch_path"]
    assert "README.md" in Path(updated["patch_path"]).read_text(encoding="utf-8")
    packet_data = json.loads(Path(updated["packet_path"]).read_text(encoding="utf-8"))
    assert packet_data["patch_status"] == "created"

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_applies_worktree_diff(tmp_path) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    readme = Path(packet["worktree_path"]) / "README.md"
    readme.write_text("test repo\napplied by codex packet\n", encoding="utf-8")

    updated = apply_codex_worktree_changes_to_main(packet, validation_commands=())

    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_validation"]["status"] == "skipped"
    assert updated["patch_path"] is None
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "test repo\napplied by codex packet\n"
    )
    packet_data = json.loads(Path(updated["packet_path"]).read_text(encoding="utf-8"))
    assert packet_data["patch_status"] == "applied_to_main"
    assert packet_data["main_apply_status"] == "applied"

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_can_commit_applied_diff(tmp_path) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    readme = Path(packet["worktree_path"]) / "README.md"
    readme.write_text("test repo\ncommitted by codex packet\n", encoding="utf-8")
    (Path(packet["worktree_path"]) / "changes.patch").write_text(
        "generated patch artifact should not be applied\n",
        encoding="utf-8",
    )

    updated = apply_codex_worktree_changes_to_main(
        packet,
        commit_mode="commit_applied",
        validation_commands=(),
    )

    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_commit"]["status"] == "committed"
    assert updated["main_apply_ignored_artifact_paths"] == ["changes.patch"]
    assert updated["patch_path"] is None
    assert not (repo / "changes.patch").exists()
    latest_subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert latest_subject == "Apply Codex legal IR packet packet-000001"
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_repairs_stale_patch_against_current_main(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    todo = ModalTodo(
        todo_id="program-repair",
        action="add_or_review_modal_ambiguity_policy",
        objective="repair stale apply",
        sample_ids=["a", "b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
            "semantic_bundle_key": "repair",
        },
    )
    packet = create_codex_work_packet(
        cycle=1,
        queue_path=tmp_path / "queue.jsonl",
        queue_run_id="queue-run",
        repo_root=repo,
        run_id="codex-run",
        todos=[todo],
        work_dir=tmp_path / "codex-work",
        worker_id="codex-worker",
    )
    (Path(packet["worktree_path"]) / "README.md").write_text(
        "codex-alpha\nbeta\ngamma\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("alpha\nbeta\nmain-gamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "advance main"], cwd=repo, check=True, capture_output=True, text=True)

    updated = apply_codex_worktree_changes_to_main(
        packet,
        merge_repair_attempts=1,
        merge_repair_mode="apply_3way",
        validation_commands=(),
    )

    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_repair_status"] == "repaired"
    assert updated["main_apply_merge_repair"]["status"] == "repaired"
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "codex-alpha\nbeta\nmain-gamma\n"
    )

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_executor_writes_prompt_and_refreshes_patch(tmp_path, monkeypatch) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    original_run = subprocess.run

    def fake_codex_run(cmd, **kwargs):
        if list(cmd[:2]) != ["codex", "exec"]:
            return original_run(cmd, **kwargs)
        worktree = Path(cmd[cmd.index("--cd") + 1])
        (worktree / "README.md").write_text(
            "test repo\nexecutor changed this packet\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with monkeypatch.context() as context:
        context.setattr(subprocess, "run", fake_codex_run)
        updated = execute_codex_work_packet(
            packet,
            codex_command="codex",
            timeout_seconds=1.0,
        )

    assert updated["codex_exec"]["status"] == "succeeded"
    assert updated["patch_status"] == "created"
    assert updated["patch_path"]
    assert Path(updated["codex_exec"]["prompt_path"]).exists()
    assert Path(updated["codex_exec"]["stdout_path"]).read_text(encoding="utf-8") == "ok\n"

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_executor_can_apply_changes_to_main(tmp_path, monkeypatch) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    original_run = subprocess.run

    def fake_codex_run(cmd, **kwargs):
        if list(cmd[:2]) != ["codex", "exec"]:
            return original_run(cmd, **kwargs)
        worktree = Path(cmd[cmd.index("--cd") + 1])
        (worktree / "README.md").write_text(
            "test repo\nexecutor applied this packet\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with monkeypatch.context() as context:
        context.setattr(subprocess, "run", fake_codex_run)
        updated = execute_codex_work_packet(
            packet,
            apply_mode="apply_to_main",
            codex_command="codex",
            timeout_seconds=1.0,
            validation_commands=(),
        )

    assert updated["codex_exec"]["status"] == "succeeded"
    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["patch_path"] is None
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "test repo\nexecutor applied this packet\n"
    )

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_executor_retries_with_sandbox_fallback(tmp_path, monkeypatch) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    original_run = subprocess.run
    codex_calls = []

    def fake_codex_run(cmd, **kwargs):
        if list(cmd[:2]) != ["codex", "exec"]:
            return original_run(cmd, **kwargs)
        codex_calls.append(list(cmd))
        sandbox_value = cmd[cmd.index("--sandbox") + 1]
        worktree = Path(cmd[cmd.index("--cd") + 1])
        last_message_path = Path(cmd[cmd.index("--output-last-message") + 1])
        if sandbox_value == "workspace-write":
            last_message_path.write_text(
                "Blocked by the execution sandbox before I could inspect or edit the worktree.\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="",
                stderr="bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n",
            )

        (worktree / "README.md").write_text(
            "test repo\nfallback sandbox changed this packet\n",
            encoding="utf-8",
        )
        last_message_path.write_text("fallback completed\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with monkeypatch.context() as context:
        context.setattr(subprocess, "run", fake_codex_run)
        updated = execute_codex_work_packet(
            packet,
            codex_command="codex",
            sandbox="workspace-write",
            timeout_seconds=1.0,
        )

    assert len(codex_calls) == 2
    assert codex_calls[0][codex_calls[0].index("--sandbox") + 1] == "workspace-write"
    assert codex_calls[1][codex_calls[1].index("--sandbox") + 1] == "danger-full-access"
    assert updated["codex_exec"]["status"] == "succeeded"
    assert updated["codex_exec"]["sandbox"] == "danger-full-access"
    assert updated["codex_exec"]["attempt_count"] == 2
    assert updated["codex_exec"]["fallback_from_sandbox"] == "workspace-write"
    assert updated["patch_status"] == "created"
    assert updated["patch_path"]

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_action_hints_cover_parser_rule_without_target_component(tmp_path) -> None:
    repo = tmp_path / "repo-action-hints"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("repo for action hints\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)

    sample = build_us_code_sample(
        title="16",
        section="6451",
        text="The Secretary shall provide notice and an opportunity for hearing before action.",
    )
    todo = ModalLossTodoGenerator().generate(
        [
            LossSnapshot.from_sample(
                sample,
                extra_losses={"symbolic_validity_penalty": 0.25},
            )
        ]
    )[0]
    todo.claim("codex-worker")

    packet = create_codex_work_packet(
        cycle=1,
        queue_path=tmp_path / "queue.jsonl",
        queue_run_id="queue-run",
        repo_root=repo,
        run_id="codex-run",
        todos=[todo],
        work_dir=tmp_path / "codex-work",
        worker_id="codex-worker",
    )

    assert "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_modal_parser.py" in packet[
        "suggested_target_files"
    ]
    assert "ipfs_datasets_py/logic/modal/compiler.py" in packet["suggested_target_files"]

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


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
    state_before = autoencoder.state.to_dict()
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

    assert autoencoder.state.to_dict() == state_before
    assert step.after.cross_entropy_loss == pytest.approx(step.before.cross_entropy_loss)
    assert step.validation_after is not None
    assert step.validation_before is not None
    assert step.validation_after.cross_entropy_loss >= step.validation_before.cross_entropy_loss
    assert step.completed_count == 0
    assert step.failed_validation_count == step.claimed_count
    assert supervisor.queue.status_counts()["failed_validation"] == step.claimed_count
    assert not step.improved


def test_failed_validation_rolls_back_attempted_updates() -> None:
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
        learning_rate=1.0,
    )

    assert step.failed_validation_count == step.claimed_count
    assert step.applied_count == 0
    assert autoencoder.state.applied_todo_ids == []
    assert train.sample_id not in autoencoder.state.family_logits
    assert train.sample_id not in autoencoder.state.decoded_embeddings


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
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
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


def test_compiler_ir_metric_block_reports_deterministic_codec_losses() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide records promptly and may withhold exempt records.",
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )

    block = compiler_ir_metric_block([sample], codec)

    assert block["sample_count"] == 1
    assert block["evaluated_count"] == 1
    assert block["metric_failures"] == 0
    assert block["llm_call_count"] == 0.0
    assert "cross_entropy_loss" in block
    assert "cosine_similarity" in block
    assert "reconstruction_loss" in block
    assert "text_reconstruction_loss" in block
    assert "modal_span_coverage" in block


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
