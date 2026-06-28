"""Tests for loss-driven modal TODO generation and batch claiming."""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    decoded_modal_phrase_slot_text_map,
    modal_ir_to_flogic_triples,
)
from ipfs_datasets_py.logic.modal.synthesis import route_autoencoder_residual
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_todo_daemon as daemon
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    LossSnapshot,
    ModalLossTodoGenerator,
    ModalOptimizerPolicy,
    ModalProgramSynthesisTodoGenerator,
    ModalTodo,
    ModalTodoQueue,
    ModalTodoSupervisor,
    bridge_loss_evaluator_for_names,
    select_program_synthesis_vector_bundle,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    apply_codex_worktree_changes_to_main,
    bridge_ir_metric_block,
    build_paired_daemon_commands,
    compiler_guidance_canary_block,
    compiler_guidance_activation_todos,
    compiler_guidance_distillation_candidates,
    compiler_guidance_distillation_todos,
    compiler_guidance_guardrail_todos,
    compiler_guidance_promotion_gate,
    compiler_guidance_scope_hints,
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
    assert todos[0].metadata["target_metrics"] == [
        "frame_ranking_loss",
        "flogic_similarity_loss",
    ]
    assert todos[0].metadata["validation_commands"]
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


def test_loss_generator_routes_source_copy_reward_hacking_to_decompiler_scope() -> None:
    snapshot = LossSnapshot(
        sample_id="sample-source-copy",
        citation="5 U.S.C. 552",
        losses={
            "source_copy_loss": 0.9,
            "source_copy_reward_hack_penalty": 0.4,
            "source_decompiled_text_embedding_cosine_loss": 0.7,
            "source_decompiled_text_token_loss": 0.6,
            "structural_text_reconstruction_loss": 0.8,
        },
        selected_frame="administrative_notice_hearing",
        parser_formula_count=1,
    )

    todos = ModalLossTodoGenerator().generate([snapshot])

    assert all(todo.action == "refine_semantic_decompiler_reconstruction" for todo in todos)
    assert {todo.loss_name for todo in todos} == {
        "source_copy_loss",
        "source_copy_reward_hack_penalty",
        "source_decompiled_text_embedding_cosine_loss",
        "source_decompiled_text_token_loss",
        "structural_text_reconstruction_loss",
    }
    assert all(todo.metadata["program_synthesis_scope"] == "ir_decompiler" for todo in todos)


def test_loss_generator_routes_deontic_bridge_losses_to_deontic_scope() -> None:
    snapshot = LossSnapshot(
        sample_id="sample-deontic",
        citation="5 U.S.C. 552",
        losses={
            "deontic_graph_failure_penalty": 1.0,
            "deontic_proof_failure_ratio": 1.0,
            "deontic_quality_requires_validation_loss": 1.0,
        },
        selected_frame="administrative_notice_hearing",
        parser_formula_count=1,
    )

    todos = ModalLossTodoGenerator().generate([snapshot])

    assert {
        todo.action
        for todo in todos
    } == {
        "repair_deontic_bridge_quality_gate",
        "repair_deontic_graph_bridge",
        "repair_deontic_prover_bridge",
    }
    assert {
        todo.metadata["target_component"]
        for todo in todos
    } == {"deontic.ir"}
    assert {
        todo.metadata["program_synthesis_scope"]
        for todo in todos
    } == {"deontic"}


def test_loss_generator_routes_cross_logic_bridge_losses_to_ast_scopes() -> None:
    snapshot = LossSnapshot(
        sample_id="sample-cross-logic",
        citation="5 U.S.C. 552",
        losses={
            "cec_dcec_event_formula_invalid_ratio": 1.0,
            "cec_dcec_validation_failure_ratio": 1.0,
            "external_prover_unavailable_loss": 1.0,
            "tdfol_parse_failure_ratio": 1.0,
            "zkp_verification_failure_ratio": 1.0,
        },
        parser_formula_count=1,
    )

    todos = ModalLossTodoGenerator().generate([snapshot])
    actions_by_loss = {todo.loss_name: todo for todo in todos}

    assert actions_by_loss["tdfol_parse_failure_ratio"].action == "repair_tdfol_bridge_parse"
    assert actions_by_loss["tdfol_parse_failure_ratio"].metadata["program_synthesis_scope"] == "tdfol"
    assert actions_by_loss["cec_dcec_event_formula_invalid_ratio"].action == "repair_cec_dcec_bridge"
    assert actions_by_loss["cec_dcec_event_formula_invalid_ratio"].metadata["program_synthesis_scope"] == "cec"
    assert actions_by_loss["cec_dcec_validation_failure_ratio"].action == "repair_cec_dcec_bridge"
    assert actions_by_loss["cec_dcec_validation_failure_ratio"].metadata["program_synthesis_scope"] == "cec"
    assert actions_by_loss["external_prover_unavailable_loss"].action == "repair_external_prover_router"
    assert actions_by_loss["external_prover_unavailable_loss"].metadata[
        "program_synthesis_scope"
    ] == "external_provers"
    assert actions_by_loss["zkp_verification_failure_ratio"].action == "repair_zkp_attestation_bridge"
    assert actions_by_loss["zkp_verification_failure_ratio"].metadata[
        "program_synthesis_scope"
    ] == "zkp"


def test_autoencoder_residual_router_targets_logic_submodules() -> None:
    assert route_autoencoder_residual("cross_entropy_loss").target_component == (
        "modal.compiler.registry"
    )
    cosine_route = route_autoencoder_residual("cosine_loss")
    assert cosine_route.target_component == "modal.autoencoder"
    assert cosine_route.action == "improve_encoder_decoder_reconstruction"
    decompiled_cosine_route = route_autoencoder_residual(
        "source_decompiled_text_embedding_cosine_loss"
    )
    assert decompiled_cosine_route.target_component == "modal.ir_decompiler"
    assert decompiled_cosine_route.action == "refine_semantic_decompiler_reconstruction"
    assert route_autoencoder_residual(
        "source_decompiled_text_token_loss"
    ).target_component == "modal.ir_decompiler"
    assert route_autoencoder_residual(
        "legal_ir_multiview_proof_failure_ratio"
    ).target_component == "external_provers.router"
    assert route_autoencoder_residual(
        "legal_ir_multiview_graph_failure_penalty"
    ).target_component == "knowledge_graphs.neo4j_compat"
    assert route_autoencoder_residual("deontic_decoder_slot_loss").target_component == (
        "deontic.ir"
    )
    assert route_autoencoder_residual(
        "unknown_loss",
        focus=("repair_multiview_legal_ir_graph_projection",),
    ).target_component == "knowledge_graphs.neo4j_compat"


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


def test_queue_add_many_merges_program_synthesis_duplicate_metric_evidence() -> None:
    first = ModalTodo(
        todo_id="program-a",
        action="refine_typed_ir_or_decompiler_slots",
        objective="first",
        sample_ids=["a"],
        citations=["1 U.S.C. 1"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "dedupe_signature": "same-decompiler-gap",
            "metric_sample_payloads": [{"sample_id": "a", "text": "alpha"}],
            "optimizer_role": "program_synthesis",
            "semantic_bundle_key": "decompiler:shall",
            "target_component": "modal.ir_decompiler",
            "target_metrics": ["embedding_cosine_similarity"],
            "validation_commands": ["python -m pytest -q tests/a.py"],
        },
    )
    second = ModalTodo(
        todo_id="program-b",
        action="refine_typed_ir_or_decompiler_slots",
        objective="second",
        sample_ids=["b"],
        citations=["2 U.S.C. 2"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=5.0,
        metadata={
            "dedupe_signature": "same-decompiler-gap",
            "metric_sample_payloads": [{"sample_id": "b", "text": "beta"}],
            "optimizer_role": "program_synthesis",
            "semantic_bundle_key": "decompiler:shall",
            "target_component": "modal.ir_decompiler",
            "target_metrics": ["reconstruction_loss"],
            "validation_commands": ["python -m pytest -q tests/b.py"],
        },
    )

    queue = ModalTodoQueue()
    added = queue.add_many([first, second])

    assert added == 1
    representative = queue.get("program-a")
    assert representative is not None
    assert representative.sample_ids == ["a", "b"]
    assert representative.citations == ["1 U.S.C. 1", "2 U.S.C. 2"]
    assert representative.metadata["target_metrics"] == [
        "embedding_cosine_similarity",
        "reconstruction_loss",
    ]
    assert representative.metadata["validation_commands"] == [
        "python -m pytest -q tests/a.py",
        "python -m pytest -q tests/b.py",
    ]
    assert [
        payload["sample_id"]
        for payload in representative.metadata["metric_sample_payloads"]
    ] == ["a", "b"]


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


def test_queue_autoencoder_dedupe_batches_equivalent_sgd_todos() -> None:
    metadata = {
        "execution_target": "adaptive_autoencoder",
        "optimizer_role": "autoencoder_sgd",
        "selected_frame": "agency_duty",
    }
    first = ModalTodo(
        todo_id="sgd-a",
        action="improve_encoder_decoder_reconstruction",
        objective="improve reconstruction",
        sample_ids=["a"],
        citations=["1 U.S.C. 1"],
        loss_name="cosine_loss",
        loss_value=0.5,
        priority=10.0,
        metadata=dict(metadata),
    )
    second = ModalTodo(
        todo_id="sgd-b",
        action="improve_encoder_decoder_reconstruction",
        objective="improve reconstruction",
        sample_ids=["b"],
        citations=["2 U.S.C. 2"],
        loss_name="cosine_loss",
        loss_value=0.8,
        priority=20.0,
        metadata=dict(metadata),
    )
    queue = ModalTodoQueue([first, second])

    removed = queue.deduplicate_autoencoder()

    assert removed == 1
    representative = queue.get("sgd-b")
    assert representative is not None
    assert queue.get("sgd-a") is None
    assert representative.sample_ids == ["b", "a"]
    assert representative.metadata["support_count"] == 2
    assert representative.metadata["autoencoder_bundle_signature"]


def test_queue_compacts_autoencoder_backlog_without_removing_program_synthesis_history() -> None:
    autoencoder_metadata = {
        "execution_target": "adaptive_autoencoder",
        "optimizer_role": "autoencoder_sgd",
        "selected_frame": "agency_duty",
    }
    program_metadata = {
        "execution_target": "codex_program_repair",
        "optimizer_role": "program_synthesis",
        "target_component": "modal.compiler",
    }
    pending = ModalTodo(
        todo_id="sgd-pending",
        action="improve_encoder_decoder_reconstruction",
        objective="improve reconstruction",
        sample_ids=["a"],
        citations=["1 U.S.C. 1"],
        loss_name="cosine_loss",
        loss_value=0.5,
        priority=10.0,
        metadata=dict(autoencoder_metadata),
    )
    duplicate_failed = ModalTodo(
        todo_id="sgd-duplicate-failed",
        action="improve_encoder_decoder_reconstruction",
        objective="duplicate reconstruction",
        sample_ids=["b"],
        citations=["2 U.S.C. 2"],
        loss_name="cosine_loss",
        loss_value=0.6,
        priority=9.0,
        status="failed_validation",
        metadata=dict(autoencoder_metadata),
    )
    stale_failed = ModalTodo(
        todo_id="sgd-stale-failed",
        action="improve_modal_family_classifier",
        objective="stale family update",
        sample_ids=["c"],
        citations=["3 U.S.C. 3"],
        loss_name="cross_entropy_loss",
        loss_value=0.7,
        priority=8.0,
        status="failed_validation",
        metadata=dict(autoencoder_metadata),
    )
    completed_program = ModalTodo(
        todo_id="program-completed",
        action="add_deterministic_parser_rule",
        objective="program repair history",
        sample_ids=["d"],
        citations=["4 U.S.C. 4"],
        loss_name="parser_formula_count",
        loss_value=1.0,
        priority=7.0,
        status="completed",
        metadata=dict(program_metadata),
    )
    queue = ModalTodoQueue([pending, duplicate_failed, stale_failed, completed_program])

    report = queue.compact_autoencoder_backlog()

    assert report["compacted_count"] == 1
    assert report["retired_failed_validation_count"] == 1
    assert report["pending_after"] == 1
    assert report["preserved_program_synthesis_count"] == 1
    assert queue.get("program-completed").status == "completed"
    representative = queue.get("sgd-pending")
    assert representative is not None
    assert representative.sample_ids == ["a", "b"]
    assert queue.get("sgd-duplicate-failed") is None
    assert queue.get("sgd-stale-failed") is None


def test_supervisor_seeds_failed_validation_rescue_todos_from_cluster() -> None:
    metadata = {
        "execution_target": "codex_program_repair",
        "failure_reason": "main_apply_validation_failed_rolled_back",
        "hint_evidence": [
            {
                "roundtrip_preview": "must provide notice before final order",
                "selected_frame": "administrative_notice_hearing",
            }
        ],
        "metric_sample_payloads": [
            {"sample_id": "sample-a", "text": "The agency must give notice."}
        ],
        "optimizer_role": "program_synthesis",
        "optimizer_stage": "typed_program_synthesis",
        "program_synthesis_scope": "ir_decompiler",
        "target_component": "modal.ir_decompiler",
        "target_metrics": ["embedding_cosine_similarity"],
        "validation_commands": ["python -m pytest -q tests/example_ir.py"],
        "validation_gate": {
            "accepted": False,
            "regressed_metrics": ["embedding_cosine_similarity"],
        },
    }
    failed_a = ModalTodo(
        todo_id="failed-a",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["sample-a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=44.0,
        status="failed_validation",
        metadata=dict(metadata),
    )
    failed_b = ModalTodo(
        todo_id="failed-b",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["sample-b"],
        citations=["5 U.S.C. 553"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=40.0,
        status="failed_validation",
        metadata={
            **metadata,
            "metric_sample_payloads": [
                {"sample_id": "sample-b", "text": "The agency must hold hearing."}
            ],
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([failed_a, failed_b]))

    seeded = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    assert len(seeded) == 1
    rescue = seeded[0]
    assert rescue.action == daemon.FAILED_VALIDATION_RESCUE_ACTION
    assert rescue.status == "pending"
    assert rescue.sample_ids == ["sample-a", "sample-b"]
    assert rescue.citations == ["5 U.S.C. 552", "5 U.S.C. 553"]
    assert rescue.metadata["source"] == "failed_validation_rescue_v1"
    assert rescue.metadata["original_action"] == "refine_typed_ir_or_decompiler_slots"
    assert rescue.metadata["failed_todo_ids"] == ["failed-a", "failed-b"]
    assert rescue.metadata["failed_validation_count"] == 2
    assert rescue.metadata["failed_validation_reason"] == (
        "main_apply_validation_failed_rolled_back"
    )
    assert rescue.metadata["program_synthesis_scope"] == "ir_decompiler"
    assert rescue.metadata["target_component"] == "modal.ir_decompiler"
    assert "embedding_cosine_similarity" in rescue.metadata["target_metrics"]
    assert "reconstruction_loss" in rescue.metadata["target_metrics"]
    assert "python -m pytest -q tests/example_ir.py" in rescue.metadata[
        "validation_commands"
    ]
    assert len(rescue.metadata["metric_sample_payloads"]) == 2
    assert rescue.metadata["hint_evidence"][0]["failed_todo_id"] == "failed-a"
    assert supervisor.queue.get(rescue.todo_id) is rescue

    seeded_again = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    assert seeded_again == []
    assert supervisor.last_program_synthesis_deduped_count == 1


def test_supervisor_routes_syntax_failed_validation_rescue_separately() -> None:
    base_metadata = {
        "execution_target": "codex_program_repair",
        "failure_reason": "main_apply_validation_failed_rolled_back",
        "optimizer_role": "program_synthesis",
        "optimizer_stage": "typed_program_synthesis",
        "program_synthesis_scope": "compiler_ambiguity",
        "target_component": "modal.compiler.ambiguity",
    }
    syntax_failed = ModalTodo(
        todo_id="failed-syntax",
        action="add_or_review_modal_ambiguity_policy",
        objective="syntax failed ambiguity policy",
        sample_ids=["sample-a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=30.0,
        status="failed_validation",
        metadata={
            **base_metadata,
            "failed_validation_report": {
                "main_apply_validation_failure_tokens": [
                    "py_compile:ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py:478",
                ],
                "main_apply_validation_stderr_tail": "SyntaxError: '(' was never closed",
                "main_apply_validation_syntax_locations": [
                    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py:478",
                ],
            },
        },
    )
    pytest_failed = ModalTodo(
        todo_id="failed-pytest",
        action="add_or_review_modal_ambiguity_policy",
        objective="pytest failed ambiguity policy",
        sample_ids=["sample-b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=29.0,
        status="failed_validation",
        metadata={
            **base_metadata,
            "failed_validation_report": {
                "main_apply_validation_failed_tests": [
                    "tests/unit_tests/logic/modal/test_modal_codec.py::test_policy"
                ],
                "main_apply_validation_failure_tokens": [
                    "pytest:tests/unit_tests/logic/modal/test_modal_codec.py::test_policy"
                ],
            },
        },
    )
    supervisor = ModalTodoSupervisor(
        queue=ModalTodoQueue([syntax_failed, pytest_failed])
    )

    seeded = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    assert len(seeded) == 2
    by_kind = {todo.metadata["failed_validation_kind"]: todo for todo in seeded}
    assert set(by_kind) == {"python_syntax", "pytest"}
    syntax_rescue = by_kind["python_syntax"]
    assert syntax_rescue.metadata["rescue_recommended_strategy"] == (
        "repair_python_syntax_before_retrying_semantic_delta"
    )
    assert syntax_rescue.metadata["failed_todo_ids"] == ["failed-syntax"]
    assert syntax_rescue.metadata["hint_evidence"][0]["syntax_locations"] == [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py:478"
    ]
    assert syntax_rescue.metadata["hint_evidence"][0]["failed_validation_tokens"] == [
        "py_compile:ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py:478"
    ]
    assert by_kind["pytest"].metadata["failed_todo_ids"] == ["failed-pytest"]


def test_supervisor_shards_large_failed_validation_rescue_clusters() -> None:
    metadata = {
        "execution_target": "codex_program_repair",
        "failure_reason": "main_apply_validation_failed_rolled_back",
        "optimizer_role": "program_synthesis",
        "optimizer_stage": "typed_program_synthesis",
        "program_synthesis_scope": "ir_decompiler",
        "target_component": "modal.ir_decompiler",
    }
    failed = [
        ModalTodo(
            todo_id=f"failed-{idx:03d}",
            action="refine_typed_ir_or_decompiler_slots",
            objective="repair typed slots",
            sample_ids=[f"sample-{idx:03d}"],
            citations=[],
            loss_name="autoencoder_residual_cluster",
            loss_value=1.0,
            priority=100.0 - idx,
            status="failed_validation",
            metadata=dict(metadata),
        )
        for idx in range(130)
    ]
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue(failed))

    seeded = supervisor.seed_failed_validation_rescue_todos(max_clusters=8)

    assert len(seeded) == 3
    covered = {
        todo_id
        for rescue in seeded
        for todo_id in rescue.metadata["failed_todo_ids"]
    }
    assert covered == {todo.todo_id for todo in failed}
    assert [rescue.metadata.get("rescue_cluster_shard") for rescue in seeded] == [
        "part-1-of-3",
        "part-2-of-3",
        "part-3-of-3",
    ]


def test_supervisor_retries_terminal_failed_validation_rescue_todos() -> None:
    failed = ModalTodo(
        todo_id="failed-ir",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["sample-a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=44.0,
        status="failed_validation",
        metadata={
            "execution_target": "codex_program_repair",
            "failure_reason": "main_apply_validation_failed_rolled_back",
            "optimizer_role": "program_synthesis",
            "optimizer_stage": "typed_program_synthesis",
            "program_synthesis_scope": "ir_decompiler",
            "target_component": "modal.ir_decompiler",
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([failed]))

    first = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)
    assert len(first) == 1
    assert supervisor.queue.fail_validation(
        first[0].todo_id,
        reason="main_apply_validation_failed_rolled_back",
    )

    retry = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    assert len(retry) == 1
    assert retry[0].todo_id != first[0].todo_id
    assert retry[0].status == "pending"
    assert retry[0].metadata["source"] == "failed_validation_rescue_retry_v1"
    assert retry[0].metadata["rescue_attempt"] == 2
    assert retry[0].metadata["previous_rescue_todo_ids"] == [first[0].todo_id]
    assert retry[0].metadata["root_rescue_signature"] == first[0].metadata[
        "dedupe_signature"
    ]

    while retry:
        assert supervisor.queue.fail_validation(
            retry[0].todo_id,
            reason="main_apply_validation_failed_rolled_back",
        )
        retry = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    attempts = [
        todo
        for todo in supervisor.queue.all()
        if todo.action == daemon.FAILED_VALIDATION_RESCUE_ACTION
    ]
    assert len(attempts) == daemon.FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS


def test_supervisor_supersedes_failures_covered_by_completed_rescue() -> None:
    failed = ModalTodo(
        todo_id="failed-ir",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["sample-a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=44.0,
        status="failed_validation",
        metadata={
            "execution_target": "codex_program_repair",
            "failure_reason": "main_apply_validation_failed_rolled_back",
            "optimizer_role": "program_synthesis",
            "optimizer_stage": "typed_program_synthesis",
            "program_synthesis_scope": "ir_decompiler",
            "target_component": "modal.ir_decompiler",
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([failed]))
    first = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)[0]
    assert supervisor.queue.fail_validation(
        first.todo_id,
        reason="main_apply_validation_failed_rolled_back",
    )
    retry = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)[0]
    assert supervisor.queue.complete(retry.todo_id)

    seeded = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    assert seeded == []
    assert supervisor.last_failed_validation_superseded_count == 2
    assert supervisor.queue.get("failed-ir").status == "superseded"
    assert supervisor.queue.get(first.todo_id).status == "superseded"
    assert supervisor.queue.get("failed-ir").metadata[
        "superseded_by_rescue_todo_id"
    ] == retry.todo_id
    assert supervisor.program_synthesis_status()["failed_validation"] == 0


def test_supervisor_refreshes_rescue_for_new_failures_after_completed_rescue() -> None:
    metadata = {
        "execution_target": "codex_program_repair",
        "failure_reason": "main_apply_validation_failed_rolled_back",
        "optimizer_role": "program_synthesis",
        "optimizer_stage": "typed_program_synthesis",
        "program_synthesis_scope": "compiler_registry",
        "target_component": "modal.compiler.registry",
    }
    old_failed = ModalTodo(
        todo_id="failed-old",
        action="refine_modal_family_cue_rules",
        objective="old failed registry repair",
        sample_ids=["sample-old"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=40.0,
        status="failed_validation",
        metadata=dict(metadata),
    )
    completed_rescue = ModalTodo(
        todo_id="rescue-completed",
        action=daemon.FAILED_VALIDATION_RESCUE_ACTION,
        objective="completed old rescue",
        sample_ids=["sample-old"],
        citations=["5 U.S.C. 552"],
        loss_name="failed_validation_rescue",
        loss_value=1.0,
        priority=60.0,
        metadata={
            **metadata,
            "failed_todo_ids": ["failed-old"],
            "original_action": "refine_modal_family_cue_rules",
            "source": "failed_validation_rescue_v1",
        },
    )
    completed_rescue.complete()
    new_failed = ModalTodo(
        todo_id="failed-new",
        action="refine_modal_family_cue_rules",
        objective="new failed registry repair",
        sample_ids=["sample-new"],
        citations=["5 U.S.C. 553"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=42.0,
        status="failed_validation",
        metadata=dict(metadata),
    )
    supervisor = ModalTodoSupervisor(
        queue=ModalTodoQueue([old_failed, completed_rescue, new_failed])
    )

    seeded = supervisor.seed_failed_validation_rescue_todos(max_clusters=4)

    assert len(seeded) == 1
    assert seeded[0].metadata["source"] == "failed_validation_rescue_refresh_v1"
    assert seeded[0].metadata["failed_todo_ids"] == ["failed-new"]
    assert seeded[0].metadata["previous_completed_rescue_todo_ids"] == [
        "rescue-completed"
    ]
    assert supervisor.last_failed_validation_superseded_count == 1
    assert supervisor.queue.get("failed-old").status == "superseded"
    assert supervisor.queue.get("failed-new").status == "failed_validation"
    assert supervisor.program_synthesis_status()["pending"] == 1


def test_supervisor_failed_validation_rescue_filters_scope() -> None:
    ir_failed = ModalTodo(
        todo_id="failed-ir",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["ir-sample"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=30.0,
        status="failed_validation",
        metadata={
            "execution_target": "codex_program_repair",
            "failure_reason": "target_metric_regression",
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "ir_decompiler",
            "target_component": "modal.ir_decompiler",
        },
    )
    bridge_failed = ModalTodo(
        todo_id="failed-bridge",
        action="repair_multiview_legal_ir_loss",
        objective="repair bridge loss",
        sample_ids=["bridge-sample"],
        citations=[],
        loss_name="legal_ir_multiview_total_loss",
        loss_value=1.0,
        priority=20.0,
        status="failed_validation",
        metadata={
            "execution_target": "codex_program_repair",
            "failure_reason": "target_metric_regression",
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "bridge",
            "target_component": "bridge.contracts",
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([ir_failed, bridge_failed]))

    seeded = supervisor.seed_failed_validation_rescue_todos(
        max_clusters=4,
        program_synthesis_scope="bridge",
    )

    assert len(seeded) == 1
    assert seeded[0].metadata["program_synthesis_scope"] == "bridge"
    assert seeded[0].metadata["target_component"] == "bridge.contracts"
    assert seeded[0].metadata["failed_todo_ids"] == ["failed-bridge"]
    assert daemon._failed_validation_rescue_strategy(
        "main_apply_target_metric_regression_rolled_back"
    ) == "preserve_target_metrics_before_expanding_fix"


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

    assert [todo.todo_id for todo in claimed] == [
        "program-anchor",
        "program-different-family",
        "program-sibling",
    ]
    assert claimed[0].metadata["semantic_bundle_anchor_id"] == "program-anchor"
    assert claimed[0].metadata["semantic_bundle_reason"] == "same_semantic_bundle_key"
    assert (
        supervisor.queue.get("program-different-family").metadata[
            "semantic_bundle_reason"
        ]
        == "same_ast_scope_and_target_component"
    )
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


def test_queue_requeues_stale_program_synthesis_claims() -> None:
    stale = ModalTodo(
        todo_id="program-stale-claim",
        action="repair_multiview_legal_ir_loss",
        objective="repair stale bridge claim",
        sample_ids=["sample-1"],
        citations=["5 U.S.C. 552"],
        loss_name="legal_ir_multiview_total_loss",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "bridge",
        },
    )
    fresh = ModalTodo(
        todo_id="program-fresh-claim",
        action="repair_cec_dcec_bridge",
        objective="repair fresh CEC claim",
        sample_ids=["sample-2"],
        citations=["5 U.S.C. 553"],
        loss_name="cec_dcec_validation_failure_ratio",
        loss_value=1.0,
        priority=9.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "cec",
        },
    )
    queue = ModalTodoQueue([stale, fresh])
    queue.claim_todo_ids(
        worker_id="codex-bridge-01",
        todo_ids=["program-stale-claim"],
        optimizer_role="program_synthesis",
    )
    queue.claim_todo_ids(
        worker_id="codex-cec-01",
        todo_ids=["program-fresh-claim"],
        optimizer_role="program_synthesis",
    )
    queue.get("program-stale-claim").claimed_at = "2026-06-05T00:00:00+00:00"
    queue.get("program-fresh-claim").claimed_at = "2026-06-05T00:01:30+00:00"

    report = queue.requeue_stale_claims(
        max_age_seconds=60.0,
        optimizer_role="program_synthesis",
        reason="stale_codex_worker_heartbeat",
        claimed_by=["codex-bridge-01"],
        now=datetime.fromisoformat("2026-06-05T00:02:00+00:00").timestamp(),
    )

    assert report["requeued_count"] == 1
    assert report["requeued_ids"] == ["program-stale-claim"]
    assert queue.get("program-stale-claim").status == "pending"
    assert queue.get("program-stale-claim").claimed_by is None
    assert (
        queue.get("program-stale-claim").metadata["stale_claim_previous_claimed_by"]
        == "codex-bridge-01"
    )
    assert queue.get("program-fresh-claim").status == "claimed"


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


def test_supervisor_seeds_bridge_loss_todos_from_evaluator() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    def fake_bridge_evaluator(samples):
        return {
            samples[0].sample_id: {
                "deontic_quality_requires_validation_loss": 1.0,
            }
        }

    supervisor = ModalTodoSupervisor(bridge_loss_evaluator=fake_bridge_evaluator)

    seeded = supervisor.seed_from_evaluation([sample])

    bridge_todos = [
        todo
        for todo in seeded
        if todo.loss_name == "deontic_quality_requires_validation_loss"
    ]
    assert len(bridge_todos) == 1
    assert bridge_todos[0].action == "repair_deontic_bridge_quality_gate"
    assert bridge_todos[0].metadata["target_component"] == "deontic.ir"
    assert bridge_todos[0].metadata["program_synthesis_scope"] == "deontic"
    assert supervisor.last_bridge_loss_sample_count == 1
    assert supervisor.last_bridge_loss_signal_count == 1
    assert supervisor.last_bridge_loss_failure_count == 0


def test_bridge_loss_evaluator_for_names_runs_deontic_adapter() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    losses = bridge_loss_evaluator_for_names(["deontic_norms"])([sample])

    assert sample.sample_id in losses
    assert "deontic_quality_requires_validation_loss" in losses[sample.sample_id]
    assert "deontic_decoder_slot_loss" in losses[sample.sample_id]
    assert "deontic_ir_slot_provenance_loss" in losses[sample.sample_id]
    assert "deontic_phase8_quality_incomplete_loss" in losses[sample.sample_id]
    assert "legal_ir_multiview_total_loss" in losses[sample.sample_id]
    assert "legal_ir_multiview_view_coverage_loss" in losses[sample.sample_id]
    assert "deontic_graph_failure_penalty" not in losses[sample.sample_id]


def test_bridge_loss_evaluator_caches_multiview_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic import bridge as bridge_module

    cache_dir = tmp_path / "bridge-loss-cache"
    monkeypatch.setenv(daemon.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(daemon.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    calls = {"count": 0}

    class FakeDocument:
        def canonical_hash(self) -> str:
            return "fake-canonical-hash"

    class FakeMultiview:
        acceptance_rate = 1.0
        document = FakeDocument()
        failures = {}
        graph_failure_penalty = 0.0
        proof_failure_ratio = 0.0
        reports = {}
        total_loss = 0.25
        view_count = 1

        def training_target(self):
            return SimpleNamespace(
                losses={"legal_ir_multiview_total_loss": 0.25},
                view_distribution={"deontic.ir": 1.0},
            )

        def view_coverage_loss(self) -> float:
            return 0.0

        def to_dict(self):
            return {
                "acceptance_rate": 1.0,
                "canonical_loss_vector": {"legal_ir_multiview_total_loss": 0.25},
                "failures": {},
                "graph_failure_penalty": 0.0,
                "proof_failure_ratio": 0.0,
                "reports": {},
                "total_loss": 0.25,
                "training_target": {
                    "document_hash": "fake-canonical-hash",
                    "losses": {"legal_ir_multiview_total_loss": 0.25},
                    "view_distribution": {"deontic.ir": 1.0},
                },
                "view_count": 1,
                "view_coverage_loss": 0.0,
                "view_distribution": {"deontic.ir": 1.0},
            }

    def fake_evaluate_legal_ir_multiview(*args, **kwargs):
        calls["count"] += 1
        return FakeMultiview()

    with daemon._BRIDGE_LOSS_CACHE_LOCK:
        daemon._BRIDGE_LOSS_CACHE.clear()
    monkeypatch.setattr(
        bridge_module,
        "evaluate_legal_ir_multiview",
        fake_evaluate_legal_ir_multiview,
    )
    evaluator = bridge_loss_evaluator_for_names(["deontic_norms"], evaluate_provers=False)

    first = evaluator([sample])
    second = evaluator([sample])
    with daemon._BRIDGE_LOSS_CACHE_LOCK:
        daemon._BRIDGE_LOSS_CACHE.clear()
    third = evaluator([sample])

    assert calls["count"] == 1
    assert first == second
    assert first == third
    assert first[sample.sample_id]["legal_ir_multiview_total_loss"] == 0.25
    cache_key = daemon._bridge_loss_cache_key(
        sample,
        bridge_names=("deontic_norms",),
        evaluate_provers=False,
    )
    cache_path = daemon._bridge_loss_disk_cache_path(cache_key)
    assert cache_path is not None
    assert cache_path.is_file()


def test_default_bridge_loss_adapters_cover_registered_logic_views() -> None:
    from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES

    names = runner.bridge_loss_adapter_names(SimpleNamespace())

    assert names == list(DEFAULT_LEGAL_IR_BRIDGE_NAMES)
    assert names == [
        "modal_frame_logic",
        "deontic_norms",
        "fol_tdfol",
        "cec_dcec",
        "external_prover_router",
        "zkp_attestation",
    ]


def test_bridge_evaluate_provers_defaults_to_fast_metric_mode(monkeypatch) -> None:
    monkeypatch.delenv(runner.BRIDGE_EVALUATE_PROVERS_ENV, raising=False)
    parser = runner.build_uscode_modal_daemon_arg_parser()

    args = parser.parse_args(["--run-id", "fast-bridge-default"])

    assert args.bridge_evaluate_provers is runner.DEFAULT_BRIDGE_EVALUATE_PROVERS
    assert args.bridge_evaluate_provers is False


def test_bridge_evaluate_provers_env_can_enable_heavy_mode(monkeypatch) -> None:
    monkeypatch.setenv(runner.BRIDGE_EVALUATE_PROVERS_ENV, "1")
    parser = runner.build_uscode_modal_daemon_arg_parser()

    args = parser.parse_args(["--run-id", "heavy-bridge-env"])

    assert args.bridge_evaluate_provers is True


def test_autoencoder_metric_bridge_samples_use_bounded_metric_text() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=" ".join(["The agency must provide records promptly."] * 8),
    )

    bounded = runner.autoencoder_metric_bridge_samples_for_evaluation(
        [sample],
        max_sample_text_chars=80,
    )

    assert len(bounded) == 1
    assert bounded[0] is not sample
    assert len(bounded[0].text) <= 80
    assert ":metric-prefix:" in bounded[0].sample_id
    assert len(bounded[0].embedding_vector) == len(sample.embedding_vector)
    assert sample.text != bounded[0].text


def test_autoencoder_metric_bridge_samples_leave_short_text_unchanged() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide records promptly.",
    )

    bounded = runner.autoencoder_metric_bridge_samples_for_evaluation(
        [sample],
        max_sample_text_chars=80,
    )

    assert bounded == [sample]


def test_autoencoder_diagnostic_bridge_defaults_to_off(monkeypatch) -> None:
    monkeypatch.delenv(
        "IPFS_DATASETS_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS",
        raising=False,
    )

    names = runner.autoencoder_diagnostic_bridge_adapter_names(
        SimpleNamespace(autoencoder_diagnostic_bridge_adapters=None),
        bridge_adapters=["modal_frame_logic", "deontic_norms"],
        metric_bridge_adapters=["modal_frame_logic"],
    )
    explicit_default = runner.autoencoder_diagnostic_bridge_adapter_names(
        SimpleNamespace(autoencoder_diagnostic_bridge_adapters="default"),
        bridge_adapters=["modal_frame_logic", "deontic_norms"],
        metric_bridge_adapters=["modal_frame_logic"],
    )

    assert names == []
    assert explicit_default == ["modal_frame_logic"]


def test_validation_signal_health_allows_disabled_diagnostic_bridge_when_targets_active() -> None:
    health = runner.autoencoder_validation_signal_health(
        compiler_ir_validation={"evaluated_count": 1, "sample_count": 1},
        learned_ir_validation={"target_count": 1},
        logic_bridge_validation={"adapter_count": 0, "evaluated_count": 0},
        validation_metrics={"sample_count": 8},
        metric_bridge_adapters=["modal_frame_logic"],
        diagnostic_bridge_adapters=[],
    )

    assert health["quality_gate"] == "pass"
    assert "logic_bridge_metrics_inactive" not in health["issues"]
    assert health["recommendations"] == [
        "run occasional diagnostic bridge sweeps for syntax/KG/prover coverage"
    ]


def test_autoencoder_metric_bridge_defaults_survive_disabled_bridge_loss(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "IPFS_DATASETS_AUTOENCODER_METRIC_BRIDGE_ADAPTERS",
        raising=False,
    )
    bridge_adapters = runner.bridge_loss_adapter_names(
        SimpleNamespace(bridge_loss_adapters="none")
    )

    names = runner.autoencoder_metric_bridge_adapter_names(
        SimpleNamespace(autoencoder_metric_bridge_adapters=None),
        bridge_adapters,
    )

    assert bridge_adapters == []
    assert names == list(runner.DEFAULT_AUTOENCODER_METRIC_BRIDGE_ADAPTERS)
    assert runner.autoencoder_metric_bridge_adapter_names(
        SimpleNamespace(autoencoder_metric_bridge_adapters="same"),
        bridge_adapters,
    ) == []
    assert runner.autoencoder_metric_bridge_adapter_names(
        SimpleNamespace(autoencoder_metric_bridge_adapters="none"),
        bridge_adapters,
    ) == []


def test_bridge_ir_metric_block_caches_multiview_reports(monkeypatch) -> None:
    from ipfs_datasets_py.logic import bridge as bridge_module

    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    calls = {"count": 0}

    class FakeDocument:
        def canonical_hash(self) -> str:
            return "fake-canonical-hash"

    class FakeMultiview:
        acceptance_rate = 1.0
        document = FakeDocument()
        failures = {}
        graph_failure_penalty = 0.0
        proof_failure_ratio = 0.0
        reports = {}
        total_loss = 0.25
        view_count = 1

        def training_target(self):
            return SimpleNamespace(
                losses={"legal_ir_multiview_total_loss": 0.25},
                view_distribution={"deontic.ir": 1.0},
            )

        def view_coverage_loss(self) -> float:
            return 0.0

        def to_dict(self):
            return {
                "acceptance_rate": 1.0,
                "canonical_loss_vector": {"legal_ir_multiview_total_loss": 0.25},
                "failures": {},
                "graph_failure_penalty": 0.0,
                "proof_failure_ratio": 0.0,
                "reports": {},
                "total_loss": 0.25,
                "training_target": {
                    "document_hash": "fake-canonical-hash",
                    "losses": {"legal_ir_multiview_total_loss": 0.25},
                    "view_distribution": {"deontic.ir": 1.0},
                },
                "view_count": 1,
                "view_coverage_loss": 0.0,
                "view_distribution": {"deontic.ir": 1.0},
            }

    def fake_evaluate_legal_ir_multiview(*args, **kwargs):
        calls["count"] += 1
        return FakeMultiview()

    with runner._BRIDGE_IR_REPORT_CACHE_LOCK:
        runner._BRIDGE_IR_REPORT_CACHE.clear()
    monkeypatch.setattr(
        bridge_module,
        "evaluate_legal_ir_multiview",
        fake_evaluate_legal_ir_multiview,
    )

    first = bridge_ir_metric_block([sample], ["deontic_norms"], evaluate_provers=False)
    second = bridge_ir_metric_block([sample], ["deontic_norms"], evaluate_provers=False)

    assert calls["count"] == 1
    assert first["cache_hits"] == 0
    assert first["cache_misses"] == 1
    assert second["cache_hits"] == 1
    assert second["cache_misses"] == 0
    assert second["cache_size"] >= 1
    assert first["canonical_ir"] == second["canonical_ir"]
    assert first["canonical_ir"]["total_loss"] == 0.25


def test_bridge_ir_metric_block_uses_persistent_metric_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic import bridge as bridge_module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        _LEGAL_IR_TARGET_CACHE,
        _LEGAL_IR_TARGET_CACHE_LOCK,
        _legal_ir_target_cache_key,
        _read_legal_ir_target_disk_cache,
    )

    cache_dir = tmp_path / "metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    calls = {"count": 0}

    class FakeDocument:
        def canonical_hash(self) -> str:
            return "fake-canonical-hash"

    class FakeMultiview:
        acceptance_rate = 1.0
        document = FakeDocument()
        failures = {}
        graph_failure_penalty = 0.0
        proof_failure_ratio = 0.0
        reports = {}
        total_loss = 0.25
        view_count = 1

        def training_target(self):
            return SimpleNamespace(
                losses={"legal_ir_multiview_total_loss": 0.25},
                view_distribution={"deontic.ir": 1.0},
            )

        def view_coverage_loss(self) -> float:
            return 0.0

        def to_dict(self):
            return {
                "acceptance_rate": 1.0,
                "canonical_loss_vector": {"legal_ir_multiview_total_loss": 0.25},
                "failures": {},
                "graph_failure_penalty": 0.0,
                "proof_failure_ratio": 0.0,
                "reports": {},
                "total_loss": 0.25,
                "training_target": {
                    "document_hash": "fake-canonical-hash",
                    "losses": {"legal_ir_multiview_total_loss": 0.25},
                    "view_distribution": {"deontic.ir": 1.0},
                },
                "view_count": 1,
                "view_coverage_loss": 0.0,
                "view_distribution": {"deontic.ir": 1.0},
            }

    def fake_evaluate_legal_ir_multiview(*args, **kwargs):
        calls["count"] += 1
        return FakeMultiview()

    with runner._BRIDGE_IR_REPORT_CACHE_LOCK:
        runner._BRIDGE_IR_REPORT_CACHE.clear()
    with _LEGAL_IR_TARGET_CACHE_LOCK:
        _LEGAL_IR_TARGET_CACHE.clear()
    monkeypatch.setattr(
        bridge_module,
        "evaluate_legal_ir_multiview",
        fake_evaluate_legal_ir_multiview,
    )

    first = bridge_ir_metric_block(
        [sample],
        ["deontic_norms", "zkp_attestation"],
        evaluate_provers=False,
    )

    assert calls["count"] == 1
    assert first["persistent_cache_hit"] is False
    assert first["legal_ir_target_cache_exports"] == 1
    target_cache_key = _legal_ir_target_cache_key(
        sample,
        bridge_names=("deontic_norms", "zkp_attestation"),
        evaluate_provers=False,
    )
    target = _read_legal_ir_target_disk_cache(target_cache_key)
    assert target is not None
    assert target.losses["legal_ir_multiview_total_loss"] == 0.25
    assert target.view_distribution["deontic.ir"] == 1.0
    block_cache_path = runner._metric_disk_cache_path(
        "bridge_ir_metric_block",
        first["persistent_cache_key"],
    )
    assert block_cache_path is not None
    block_cache_path.unlink()
    with runner._BRIDGE_IR_REPORT_CACHE_LOCK:
        runner._BRIDGE_IR_REPORT_CACHE.clear()
    with _LEGAL_IR_TARGET_CACHE_LOCK:
        _LEGAL_IR_TARGET_CACHE.clear()

    second = bridge_ir_metric_block(
        [sample],
        ["deontic_norms", "zkp_attestation"],
        evaluate_provers=False,
    )
    third = bridge_ir_metric_block(
        [sample],
        ["deontic_norms", "zkp_attestation"],
        evaluate_provers=False,
    )

    assert calls["count"] == 1
    assert second["persistent_cache_hit"] is False
    assert second["persistent_sample_cache_hits"] == 1
    assert second["legal_ir_target_cache_exports"] == 1
    assert third["persistent_cache_hit"] is True
    assert second["persistent_cache_kind"] == "bridge_ir_metric_block"
    assert second["zkp_attestation_cache"]["mode"] == "persistent_metric_certificate"
    assert first["canonical_ir"] == second["canonical_ir"]


def test_supervisor_seeds_canonical_multiview_loss_todos() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    def fake_bridge_evaluator(samples):
        return {
            samples[0].sample_id: {
                "legal_ir_multiview_total_loss": 0.25,
                "legal_ir_multiview_view_coverage_loss": 0.5,
            }
        }

    supervisor = ModalTodoSupervisor(bridge_loss_evaluator=fake_bridge_evaluator)

    seeded = supervisor.seed_from_evaluation([sample])

    actions = {todo.action for todo in seeded}
    assert "repair_multiview_legal_ir_loss" in actions
    assert "repair_multiview_legal_ir_view_coverage" in actions
    by_action = {todo.action: todo for todo in seeded}
    assert by_action["repair_multiview_legal_ir_loss"].metadata[
        "target_component"
    ] == "bridge.contracts"
    assert by_action["repair_multiview_legal_ir_loss"].metadata[
        "program_synthesis_scope"
    ] == "bridge"


def test_generic_legal_ir_loss_backs_off_when_specific_bridge_loss_exists() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    def fake_bridge_evaluator(samples):
        return {
            samples[0].sample_id: {
                "deontic_decoder_slot_loss": 0.5,
                "legal_ir_multiview_total_loss": 0.5,
            }
        }

    supervisor = ModalTodoSupervisor(bridge_loss_evaluator=fake_bridge_evaluator)

    seeded = supervisor.seed_from_evaluation([sample])

    by_action = {todo.action: todo for todo in seeded}
    generic = by_action["repair_multiview_legal_ir_loss"]
    specific = by_action["repair_deontic_bridge_quality_gate"]
    assert generic.metadata["generic_bridge_priority_backoff"] is True
    assert generic.priority < specific.priority


def test_supervisor_seeds_legal_ir_view_cross_entropy_sgd_todo() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    evaluation = autoencoder.evaluate(
        [sample],
        legal_ir_bridge_names=("deontic_norms", "fol_tdfol"),
    )
    supervisor = ModalTodoSupervisor(
        bridge_names=("deontic_norms", "fol_tdfol"),
    )

    seeded = supervisor.seed_from_evaluation([sample], autoencoder=evaluation)

    view_todos = [
        todo
        for todo in seeded
        if todo.loss_name == "legal_ir_view_cross_entropy_loss"
    ]
    assert len(view_todos) == 1
    assert view_todos[0].action == "improve_legal_ir_view_distribution"
    assert view_todos[0].metadata["optimizer_role"] == "autoencoder_sgd"
    assert view_todos[0].metadata["execution_target"] == "adaptive_autoencoder"


def test_autoencoder_caches_legal_ir_view_candidate_scan() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    state = ModalAutoencoderTrainingState(
        feature_family_logits={
            f"feature-{index}": {"modal.frame_logic": 0.1}
            for index in range(100)
        }
    )
    autoencoder = AdaptiveModalAutoencoder(state=state)

    assert autoencoder._legal_ir_view_family_candidates() == ("modal.frame_logic",)
    state.feature_family_logits["feature-new"] = {"CEC.native": 0.2}
    assert autoencoder._legal_ir_view_family_candidates() == ("modal.frame_logic",)

    autoencoder._legal_ir_view_target_cache[sample.sample_id] = {"CEC.native": 1.0}
    assert autoencoder._nudge_legal_ir_view_global_logits(sample, learning_rate=0.1)
    assert "CEC.native" in autoencoder._legal_ir_view_family_candidates()


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
    assert all(todo.metadata["residual_signatures"] for todo in todos)
    assert all(todo.metadata["target_metrics"] for todo in todos)
    assert all(todo.metadata["validation_commands"] for todo in todos)
    assert all(todo.metadata["metric_sample_payloads"] for todo in todos)
    for todo in todos:
        assert {
            evidence["hint_id"] for evidence in todo.metadata["hint_evidence"]
        } == set(todo.metadata["hint_ids"])
        assert all(
            evidence.get("sample_id") in todo.sample_ids
            for evidence in todo.metadata["hint_evidence"]
        )


def test_program_synthesis_generator_uses_legal_ir_view_introspection() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    autoencoder.evaluate(
        [sample],
        legal_ir_bridge_names=("deontic_norms", "fol_tdfol"),
    )
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=1),
        bridge_names=("deontic_norms", "fol_tdfol"),
    )

    seeded = supervisor.seed_program_synthesis_from_introspection(
        [sample],
        autoencoder=autoencoder,
    )

    actions = {todo.action for todo in seeded}
    assert "repair_multiview_legal_ir_loss" in actions
    assert "repair_deontic_bridge_quality_gate" in actions
    by_action = {todo.action: todo for todo in seeded}
    assert by_action["repair_multiview_legal_ir_loss"].metadata[
        "target_component"
    ] == "bridge.contracts"
    assert by_action["repair_deontic_bridge_quality_gate"].metadata[
        "program_synthesis_scope"
    ] == "deontic"
    assert (
        by_action["repair_multiview_legal_ir_loss"].priority
        < by_action["repair_deontic_bridge_quality_gate"].priority
    )
    deontic_evidence = by_action["repair_deontic_bridge_quality_gate"].metadata[
        "hint_evidence"
    ][0]
    assert deontic_evidence["target_view"].startswith("deontic.")
    assert deontic_evidence["predicted_view"].startswith("deontic.")
    assert deontic_evidence["bridge_failure_name"] == "deontic_decoder_slot_loss"
    assert by_action["repair_multiview_legal_ir_loss"].metadata["target_metrics"]
    assert by_action["repair_multiview_legal_ir_loss"].metadata[
        "validation_commands"
    ]


def test_program_synthesis_generator_fans_out_legal_ir_view_introspection() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    autoencoder.evaluate(
        [sample],
        legal_ir_targets={
            sample.sample_id: SimpleNamespace(
                losses={"legal_ir_multiview_total_loss": 0.5},
                view_distribution={
                    "CEC.native": 0.40,
                    "TDFOL.prover": 0.25,
                    "deontic.ir": 0.30,
                    "external_provers.router": 0.03,
                    "knowledge_graphs.neo4j_compat": 0.55,
                    "zkp.circuits": 0.03,
                },
            )
        },
    )
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=1),
        bridge_names=("deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router", "zkp_attestation"),
    )

    seeded = supervisor.seed_program_synthesis_from_introspection(
        [sample],
        autoencoder=autoencoder,
    )

    scopes = {
        todo.metadata["program_synthesis_scope"]
        for todo in seeded
        if todo.metadata["optimizer_role"] == "program_synthesis"
    }
    assert "bridge" in scopes
    assert "cec" in scopes
    assert "deontic" in scopes
    assert "knowledge_graphs" in scopes
    assert "tdfol" in scopes
    assert "external_provers" not in scopes
    assert "zkp" not in scopes


def test_fast_program_synthesis_bootstrap_todos_cover_parallel_scopes() -> None:
    samples = [
        build_us_code_sample(
            title="5",
            section="552",
            text="The agency shall publish notice before the permit takes effect.",
        ),
        build_us_code_sample(
            title="5",
            section="553",
            text="The agency may not adopt a final rule without public comment.",
        ),
    ]

    todos = runner.fast_program_synthesis_bootstrap_todos(
        samples,
        policy=ModalOptimizerPolicy(),
        cycle=7,
    )

    expected_scopes = {
        "bridge",
        "cec",
        "compiler_ambiguity",
        "compiler_parser",
        "compiler_registry",
        "deontic",
        "external_provers",
        "frame_logic",
        "ir_decompiler",
        "knowledge_graphs",
        "tdfol",
        "zkp",
    }
    scopes = {todo.metadata["program_synthesis_scope"] for todo in todos}
    assert expected_scopes <= scopes
    assert all(todo.loss_name == "program_synthesis_bootstrap" for todo in todos)
    assert all(todo.metadata["optimizer_role"] == "program_synthesis" for todo in todos)
    assert all(todo.metadata["execution_target"] == "codex_program_repair" for todo in todos)
    assert all(todo.metadata["source"] == "modal_program_synthesis_fast_bootstrap_v1" for todo in todos)
    assert all(todo.metadata["support_count"] == len(samples) for todo in todos)
    assert all(todo.metadata["hint_evidence"] for todo in todos)
    assert all(todo.metadata["metric_sample_payloads"] for todo in todos)
    assert all(todo.metadata["target_metrics"] for todo in todos)
    assert all(todo.metadata["validation_commands"] for todo in todos)
    assert all(todo.metadata["dedupe_signature"] for todo in todos)
    assert all(todo.metadata["semantic_bundle_key"] for todo in todos)


def test_program_synthesis_residual_persistence_occurrence_counting() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before adopting a rule.",
    )
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=1.0)
    supervisor = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(
            program_synthesis_min_support=1,
            program_synthesis_min_residual_occurrences=2,
            program_synthesis_min_residual_survival_score=0.0,
        ),
    )
    todos = supervisor.program_synthesis_generator.generate(
        [sample],
        autoencoder=autoencoder,
    )
    assert todos
    candidate = todos[0]
    assert supervisor._residual_signature_occurrences(candidate) == 1
    supervisor.queue.add_many(todos)
    duplicate_todos = supervisor.program_synthesis_generator.generate(
        [sample],
        autoencoder=autoencoder,
    )
    assert duplicate_todos
    assert supervisor._residual_signature_occurrences(duplicate_todos[0]) >= 2


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
    program_todos = supervisor.queue.pending(optimizer_role="program_synthesis")
    assert all(todo.metadata["residual_cluster_stage"] == "post_sgd" for todo in program_todos)
    assert all("post_sgd_metric_deltas" in todo.metadata for todo in program_todos)
    assert all(todo.metadata["post_sgd_requires_codex"] is True for todo in program_todos)
    assert all(
        todo.metadata["optimizer_role"] == "program_synthesis"
        for todo in program_todos
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


def test_supervisor_optimizer_queue_summary_separates_autoencoder_and_codex_lanes() -> None:
    autoencoder_todo = ModalTodo(
        todo_id="sgd",
        action="improve_modal_family_classifier",
        objective="improve family logits",
        sample_ids=["a"],
        citations=[],
        loss_name="cross_entropy_loss",
        loss_value=1.0,
        priority=2.0,
        metadata={"optimizer_role": "autoencoder_sgd"},
    )
    program_todo = ModalTodo(
        todo_id="program",
        action="add_deterministic_parser_rule",
        objective="repair parser",
        sample_ids=["b"],
        citations=[],
        loss_name="parser_formula_count",
        loss_value=1.0,
        priority=1.0,
        status="failed_validation",
        metadata={"optimizer_role": "program_synthesis"},
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([autoencoder_todo, program_todo]))
    summary = {}

    statuses = supervisor.update_optimizer_queue_summary(
        summary,
        autoencoder_execution_mode="adaptive_sgd",
        program_execution_mode="codex_cli",
    )

    assert statuses["autoencoder_sgd"]["pending"] == 1
    assert statuses["program_synthesis"]["failed_validation"] == 1
    assert summary["autoencoder_sgd_pending"] == 1
    assert summary["program_synthesis_failed_validation"] == 1
    assert summary["autoencoder_sgd_execution_mode"] == "adaptive_sgd"
    assert summary["program_synthesis_execution_mode"] == "codex_cli"


def test_codex_runner_extracts_todo_validation_commands_and_packet_report() -> None:
    todo = ModalTodo(
        todo_id="program",
        action="add_deterministic_parser_rule",
        objective="repair parser",
        sample_ids=["a"],
        citations=[],
        loss_name="parser_formula_count",
        loss_value=1.0,
        priority=1.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "validation_commands": [
                f"{sys.executable} -m pytest -q tests/unit/foo.py",
                [sys.executable, "-m", "pytest", "-q", "tests/unit/foo.py"],
            ],
        },
    )

    commands = runner._codex_validation_commands_for_todos([todo])
    report = runner._codex_packet_validation_report(
        {
            "main_apply_status": "applied",
            "main_apply_validation": {"status": "passed"},
            "metric_deltas": {"cross_entropy_loss": 0.1},
            "patch_status": "applied_to_main",
            "target_metric_validation": {
                "regressed_metrics": [],
                "status": "passed",
            },
        }
    )

    assert commands == [[sys.executable, "-m", "pytest", "-q", "tests/unit/foo.py"]]
    assert report["status"] == "passed"
    assert report["main_apply_status"] == "applied"
    assert report["metric_deltas"] == {"cross_entropy_loss": 0.1}
    assert report["target_metric_status"] == "passed"

    baseline_red_report = runner._codex_packet_validation_report(
        {
            "main_apply_baseline_failure_accepted": True,
            "main_apply_status": "applied",
            "main_apply_validation": {"status": "failed"},
            "main_apply_baseline_validation": {"status": "failed"},
            "main_apply_validation_gate": "inconclusive_baseline_failed",
            "patch_status": "applied_to_main",
            "target_metric_validation": {
                "regressed_metrics": [],
                "status": "passed",
            },
        }
    )
    assert baseline_red_report["status"] == "passed"
    assert baseline_red_report["baseline_failure_accepted"] is True
    assert baseline_red_report["main_apply_validation_gate"] == (
        "inconclusive_baseline_failed"
    )


def test_codex_target_metric_validation_reports_regressions() -> None:
    before = {
        "metrics": {
            "cross_entropy_loss": 1.0,
            "embedding_cosine_similarity": 0.5,
        },
        "status": "measured",
        "target_metrics": [
            "cross_entropy_loss",
            "embedding_cosine_similarity",
            "missing_metric",
        ],
    }
    after = {
        "metrics": {
            "cross_entropy_loss": 0.8,
            "embedding_cosine_similarity": 0.25,
        },
        "status": "measured",
        "target_metrics": [
            "cross_entropy_loss",
            "embedding_cosine_similarity",
            "missing_metric",
        ],
    }

    report = runner._codex_target_metric_validation_report(
        before=before,
        after=after,
    )

    assert report["metric_deltas"]["cross_entropy_loss"] == pytest.approx(0.2)
    assert report["metric_deltas"]["embedding_cosine_similarity"] == pytest.approx(-0.25)
    assert report["improved_metrics"] == ["cross_entropy_loss"]
    assert report["regressed_metrics"] == ["embedding_cosine_similarity"]
    assert report["missing_metrics"] == ["missing_metric"]
    assert report["status"] == "regressed"

    unavailable = runner._codex_target_metric_validation_report(
        before={
            "metrics": {},
            "status": "failed",
            "target_metrics": ["cross_entropy_loss"],
        },
        after={
            "metrics": {"cross_entropy_loss": 0.8},
            "status": "measured",
            "target_metrics": ["cross_entropy_loss"],
        },
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["regressed_metrics"] == []


def test_codex_target_metric_snapshot_uses_shared_process_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    packet = {
        "todos": [
            {
                "metadata": {
                    "metric_sample_payloads": [
                        {
                            "citation": "5 U.S.C. 552",
                            "sample_id": "sample-a",
                            "section": "552",
                            "text": "The agency shall provide notice.",
                            "title": "5",
                        }
                    ],
                    "target_metrics": ["cross_entropy_loss"],
                },
                "todo_id": "todo-a",
            }
        ]
    }
    cache_dir = tmp_path / "target-metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))

    def fake_capture(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return {
            "exit_code": 0,
            "status": "completed",
            "stderr": "",
            "stdout": json.dumps(
                {
                    "metric_count": 1,
                    "metrics": {"cross_entropy_loss": 0.42},
                    "sample_count": 1,
                    "status": "measured",
                    "target_metrics": ["cross_entropy_loss"],
                }
            ),
        }

    monkeypatch.setattr(runner, "accelerate_run_process_group_capture", fake_capture)

    snapshot = runner._codex_packet_target_metric_snapshot(
        packet,
        tmp_path,
        timeout_seconds=7.0,
    )

    assert captured["command"][:2] == [sys.executable, "-c"]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert (
        captured["kwargs"]["env"][runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV]
        == str(cache_dir)
    )
    assert captured["kwargs"]["timeout_seconds"] == 7.0
    assert "sample-a" in captured["kwargs"]["input_text"]
    payload = json.loads(captured["kwargs"]["input_text"])
    assert payload["bridge_names"] == []
    assert snapshot["status"] == "measured"
    assert snapshot["metrics"] == {"cross_entropy_loss": 0.42}
    assert snapshot["timeout_seconds"] == 7.0


def test_codex_target_metric_snapshot_targets_bridge_adapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    packet = {
        "todos": [
            {
                "metadata": {
                    "metric_sample_payloads": [
                        {
                            "citation": "5 U.S.C. 552",
                            "sample_id": "sample-a",
                            "section": "552",
                            "text": "The agency shall provide notice.",
                            "title": "5",
                        }
                    ],
                    "target_metrics": ["zkp_verification_failure_ratio"],
                },
                "todo_id": "todo-a",
            }
        ]
    }

    def fake_capture(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return {
            "exit_code": 0,
            "status": "completed",
            "stderr": "",
            "stdout": json.dumps(
                {
                    "metric_count": 1,
                    "metrics": {"zkp_verification_failure_ratio": 0.0},
                    "sample_count": 1,
                    "status": "measured",
                    "target_bridge_names": ["zkp_attestation"],
                    "target_metrics": ["zkp_verification_failure_ratio"],
                }
            ),
        }

    monkeypatch.setattr(runner, "accelerate_run_process_group_capture", fake_capture)

    snapshot = runner._codex_packet_target_metric_snapshot(
        packet,
        tmp_path,
        timeout_seconds=7.0,
    )

    assert captured["command"][:2] == [sys.executable, "-c"]
    payload = json.loads(captured["kwargs"]["input_text"])
    assert payload["bridge_names"] == ["zkp_attestation"]
    assert snapshot["status"] == "measured"
    assert snapshot["metrics"] == {"zkp_verification_failure_ratio": 0.0}


def test_codex_target_metric_bridge_adapter_selection_is_metric_scoped() -> None:
    from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES

    assert runner._codex_target_metric_bridge_adapter_names(["cross_entropy_loss"]) == []
    assert runner._codex_target_metric_bridge_adapter_names(
        ["zkp_verification_failure_ratio"]
    ) == ["zkp_attestation"]
    assert runner._codex_target_metric_bridge_adapter_names(
        ["deontic_decoder_slot_loss", "legal_ir_view_cross_entropy_loss"]
    ) == ["deontic_norms"]
    assert runner._codex_target_metric_bridge_adapter_names(
        ["legal_ir_multiview_total_loss"]
    ) == list(DEFAULT_LEGAL_IR_BRIDGE_NAMES)


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
    claimed[0].metadata["target_metrics"] = ["cross_entropy_loss"]

    completed = supervisor.finalize_program_synthesis_batch(
        claimed,
        codex_exec_status="succeeded",
        patch_status="created",
        validation_report={
            "metric_deltas": {"cross_entropy_loss": 0.2},
            "status": "passed",
        },
    )
    assert completed["updated"] is True
    assert completed["completed_count"] == 1
    assert completed["failed_validation_count"] == 0
    completed_todo = supervisor.queue.get(claimed[0].todo_id)
    assert completed_todo.status == "completed"
    assert completed_todo.metadata["validation_gate"]["accepted"] is True
    assert completed_todo.metadata["validation_gate"]["improved_metrics"] == [
        "cross_entropy_loss"
    ]

    supervisor_regression = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor_regression.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed_regression = supervisor_regression.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    claimed_regression[0].metadata["target_metrics"] = ["cross_entropy_loss"]
    regression = supervisor_regression.finalize_program_synthesis_batch(
        claimed_regression,
        codex_exec_status="succeeded",
        patch_status="created",
        validation_report={
            "metric_deltas": {"cross_entropy_loss": -0.2},
            "status": "passed",
        },
    )
    regression_todo = supervisor_regression.queue.get(claimed_regression[0].todo_id)
    assert regression["updated"] is True
    assert regression["completed_count"] == 0
    assert regression["failed_validation_count"] == 1
    assert regression["reason"] == "target_metric_regression"
    assert regression_todo.status == "failed_validation"
    assert regression_todo.metadata["validation_gate"]["accepted"] is False
    assert regression_todo.metadata["validation_gate"]["regressed_metrics"] == [
        "cross_entropy_loss"
    ]
    assert regression_todo.metadata["failed_validation_reason"] == (
        "target_metric_regression"
    )
    assert regression_todo.metadata["failed_validation_patch_status"] == "created"
    assert regression_todo.metadata["failed_validation_report"]["metric_deltas"] == {
        "cross_entropy_loss": -0.2
    }

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
    assert failed["failed_validation_count"] == 0
    assert failed["requeued_count"] == 1
    assert failed["reason"] == "awaiting_codex_changes"
    failed_todo = supervisor_fail.queue.get(claimed_fail[0].todo_id)
    assert failed_todo.status == "pending"
    assert failed_todo.metadata["transient_failure_count"] == 1
    assert failed_todo.metadata["last_transient_codex_exec_status"] == "failed"
    assert failed_todo.metadata["last_transient_patch_status"] == "awaiting_codex_changes"

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

    supervisor_applied_failed = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor_applied_failed.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed_applied_failed = supervisor_applied_failed.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    applied_failed = supervisor_applied_failed.finalize_program_synthesis_batch(
        claimed_applied_failed,
        codex_exec_status="succeeded",
        patch_status="applied_to_main",
        validation_report={
            "main_apply_validation_status": "failed",
            "main_apply_validation_failure_tokens": [
                "py_compile:ipfs_datasets_py/logic/bridge/modal_frame_logic.py:511",
            ],
            "main_apply_validation_stderr_tail": "IndentationError: expected an indented block",
            "main_apply_validation_syntax_locations": [
                "ipfs_datasets_py/logic/bridge/modal_frame_logic.py:511",
            ],
            "status": "failed",
        },
    )
    applied_failed_todo = supervisor_applied_failed.queue.get(
        claimed_applied_failed[0].todo_id
    )
    assert applied_failed["updated"] is True
    assert applied_failed["completed_count"] == 0
    assert applied_failed["failed_validation_count"] == 1
    assert applied_failed["reason"] == "main_apply_validation_python_syntax_error"
    assert applied_failed_todo.status == "failed_validation"
    assert applied_failed_todo.metadata["failed_validation_reason"] == (
        "main_apply_validation_python_syntax_error"
    )
    assert applied_failed_todo.metadata["failed_validation_kind"] == "python_syntax"
    assert applied_failed_todo.metadata["failed_validation_report"][
        "main_apply_validation_failure_tokens"
    ] == ["py_compile:ipfs_datasets_py/logic/bridge/modal_frame_logic.py:511"]
    assert applied_failed_todo.metadata["failed_validation_report"][
        "main_apply_validation_syntax_locations"
    ] == ["ipfs_datasets_py/logic/bridge/modal_frame_logic.py:511"]
    assert "IndentationError" in applied_failed_todo.metadata[
        "failed_validation_report"
    ]["main_apply_validation_stderr_tail"]

    supervisor_no_delta = ModalTodoSupervisor(
        policy=ModalOptimizerPolicy(program_synthesis_min_support=2)
    )
    supervisor_no_delta.seed_program_synthesis_from_introspection(
        samples,
        autoencoder=AdaptiveModalAutoencoder(feature_family_logit_scale=1.0),
    )
    claimed_no_delta = supervisor_no_delta.claim_program_synthesis_batch(
        worker_id="codex-worker",
        max_items=1,
    )
    no_delta = supervisor_no_delta.finalize_program_synthesis_batch(
        claimed_no_delta,
        codex_exec_status="succeeded",
        patch_status="main_apply_no_merged_delta",
    )
    assert no_delta["updated"] is True
    assert no_delta["completed_count"] == 1
    assert no_delta["failed_validation_count"] == 0
    assert supervisor_no_delta.queue.get(claimed_no_delta[0].todo_id).status == "completed"


def test_supervisor_finalize_requeues_transient_codex_failure() -> None:
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

    requeued = supervisor.finalize_program_synthesis_batch(
        claimed,
        codex_exec_status="transient_failure",
        patch_status="awaiting_codex_changes",
    )

    todo = supervisor.queue.get(claimed[0].todo_id)
    assert requeued["updated"] is True
    assert requeued["outcome"] == "requeued"
    assert requeued["requeued_count"] == 1
    assert requeued["failed_validation_count"] == 0
    assert todo is not None
    assert todo.status == "pending"
    assert todo.claimed_by is None
    assert todo.metadata["transient_failure_count"] == 1


def test_supervisor_finalize_requeues_baseline_validation_failure() -> None:
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

    requeued = supervisor.finalize_program_synthesis_batch(
        claimed,
        codex_exec_status="succeeded",
        patch_status="main_apply_baseline_validation_failed_rolled_back",
    )

    todo = supervisor.queue.get(claimed[0].todo_id)
    assert requeued["updated"] is True
    assert requeued["outcome"] == "requeued"
    assert requeued["requeued_count"] == 1
    assert requeued["failed_validation_count"] == 0
    assert requeued["reason"] == "main_apply_baseline_validation_failed"
    assert todo is not None
    assert todo.status == "pending"
    assert todo.claimed_by is None
    assert todo.metadata["transient_failure_count"] == 1


def test_supervisor_finalize_requeues_target_metric_infrastructure_failure() -> None:
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

    requeued = supervisor.finalize_program_synthesis_batch(
        claimed,
        codex_exec_status="succeeded",
        patch_status="main_apply_target_metric_unavailable_rolled_back",
    )

    todo = supervisor.queue.get(claimed[0].todo_id)
    assert requeued["updated"] is True
    assert requeued["outcome"] == "requeued"
    assert requeued["requeued_count"] == 1
    assert requeued["failed_validation_count"] == 0
    assert requeued["reason"] == "target_metric_unavailable"
    assert todo is not None
    assert todo.status == "pending"
    assert todo.metadata["transient_failure_count"] == 1


def test_supervisor_transient_requeue_has_retry_limit() -> None:
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
    claimed[0].metadata["transient_failure_count"] = 3

    failed = supervisor.finalize_program_synthesis_batch(
        claimed,
        codex_exec_status="transient_failure",
        patch_status="awaiting_codex_changes",
    )

    todo = supervisor.queue.get(claimed[0].todo_id)
    assert failed["updated"] is True
    assert failed["outcome"] == "failed_validation"
    assert failed["requeued_count"] == 0
    assert failed["failed_validation_count"] == 1
    assert todo is not None
    assert todo.status == "failed_validation"


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
    canary_index = paired["autoencoder_command"].index("--validation-canary-count")
    assert paired["autoencoder_command"][canary_index + 1] == str(
        runner.DEFAULT_VALIDATION_CANARY_COUNT
    )
    prover_index = paired["autoencoder_command"].index("--bridge-evaluate-provers")
    assert paired["autoencoder_command"][prover_index + 1] == "false"
    bridge_text_index = paired["autoencoder_command"].index(
        "--autoencoder-metric-bridge-max-sample-text-chars"
    )
    assert paired["autoencoder_command"][bridge_text_index + 1] == str(
        runner.DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS
    )
    diagnostic_bridge_index = paired["autoencoder_command"].index(
        "--autoencoder-diagnostic-bridge-adapters"
    )
    assert paired["autoencoder_command"][diagnostic_bridge_index + 1] == "none"
    text_policy_index = paired["autoencoder_command"].index(
        "--compiler-ir-metric-text-policy"
    )
    assert paired["autoencoder_command"][text_policy_index + 1] == "truncate"
    sample_timeout_index = paired["autoencoder_command"].index(
        "--compiler-ir-metric-sample-timeout-seconds"
    )
    assert paired["autoencoder_command"][sample_timeout_index + 1] == str(
        runner.DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS
    )
    projection_timeout_index = paired["autoencoder_command"].index(
        "--generalizable-projection-timeout-seconds"
    )
    assert paired["autoencoder_command"][projection_timeout_index + 1] == str(
        runner.DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS
    )
    apply_index = paired["codex_command"].index("--codex-apply-mode")
    assert paired["codex_command"][apply_index + 1] == "apply_to_main"
    scale_index = paired["autoencoder_command"].index(
        "--autoencoder-feature-family-logit-scale"
    )
    assert paired["autoencoder_command"][scale_index + 1] == "1.0"
    commit_index = paired["codex_command"].index("--codex-commit-mode")
    assert paired["codex_command"][commit_index + 1] == "commit_applied"
    scope_index = paired["codex_command"].index("--codex-scope")
    assert paired["codex_command"][scope_index + 1] == "frame_logic"
    assert paired["autoencoder_command"].count("--warm-start-run-id") == 2
    assert paired["autoencoder_command"].count("--warm-start-state") == 1
    assert "--generalizable-projection-max-cosine-regression" in paired["autoencoder_command"]
    assert "--generalizable-projection-max-reconstruction-regression" in paired["autoencoder_command"]
    assert "--generalizable-projection-max-cross-entropy-regression" in paired["autoencoder_command"]
    assert "--generalizable-projection-max-legal-ir-loss-regression" in paired["autoencoder_command"]
    assert "--autoencoder-projection-deadband-mode" in paired["autoencoder_command"]
    deadband_index = paired["autoencoder_command"].index(
        "--autoencoder-projection-deadband-mode"
    )
    assert paired["autoencoder_command"][deadband_index + 1] == "shadow"
    ce_deadband_index = paired["autoencoder_command"].index(
        "--autoencoder-max-ce-deadband"
    )
    assert paired["autoencoder_command"][ce_deadband_index + 1] == "0.0001"
    assert "--autoencoder-hard-guardrail-metrics" in paired["autoencoder_command"]
    assert "--autoencoder-projection-prescreen-mode" in paired["autoencoder_command"]
    prescreen_mode_index = paired["autoencoder_command"].index(
        "--autoencoder-projection-prescreen-mode"
    )
    assert paired["autoencoder_command"][prescreen_mode_index + 1] == "off"
    prescreen_top_k_index = paired["autoencoder_command"].index(
        "--autoencoder-projection-prescreen-top-k"
    )
    assert paired["autoencoder_command"][prescreen_top_k_index + 1] == "3"
    full_search_index = paired["autoencoder_command"].index(
        "--autoencoder-projection-periodic-full-search-every-n-cycles"
    )
    assert paired["autoencoder_command"][full_search_index + 1] == "8"
    compiler_train_mode_index = paired["autoencoder_command"].index(
        "--compiler-ir-train-mode"
    )
    assert (
        paired["autoencoder_command"][compiler_train_mode_index + 1]
        == runner.DEFAULT_COMPILER_IR_TRAIN_MODE
    )
    compiler_train_cadence_index = paired["autoencoder_command"].index(
        "--compiler-ir-train-every-n-cycles"
    )
    assert paired["autoencoder_command"][compiler_train_cadence_index + 1] == "4"
    guided_train_mode_index = paired["autoencoder_command"].index(
        "--compiler-ir-guided-train-mode"
    )
    assert (
        paired["autoencoder_command"][guided_train_mode_index + 1]
        == runner.DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE
    )
    guided_train_cadence_index = paired["autoencoder_command"].index(
        "--compiler-ir-guided-train-every-n-cycles"
    )
    assert paired["autoencoder_command"][guided_train_cadence_index + 1] == "4"
    before_train_mode_index = paired["autoencoder_command"].index(
        "--autoencoder-before-train-eval-mode"
    )
    assert (
        paired["autoencoder_command"][before_train_mode_index + 1]
        == runner.DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE
    )
    before_train_cadence_index = paired["autoencoder_command"].index(
        "--autoencoder-before-train-eval-every-n-cycles"
    )
    assert paired["autoencoder_command"][before_train_cadence_index + 1] == "4"
    memory_probe_mode_index = paired["autoencoder_command"].index(
        "--autoencoder-sample-memory-probe-mode"
    )
    assert (
        paired["autoencoder_command"][memory_probe_mode_index + 1]
        == runner.DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE
    )
    memory_probe_cadence_index = paired["autoencoder_command"].index(
        "--autoencoder-sample-memory-probe-every-n-cycles"
    )
    assert paired["autoencoder_command"][memory_probe_cadence_index + 1] == "4"
    todo_supervisor_mode_index = paired["autoencoder_command"].index(
        "--autoencoder-todo-supervisor-mode"
    )
    assert (
        paired["autoencoder_command"][todo_supervisor_mode_index + 1]
        == runner.DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE
    )
    todo_supervisor_min_open_index = paired["autoencoder_command"].index(
        "--autoencoder-todo-supervisor-min-open"
    )
    assert paired["autoencoder_command"][todo_supervisor_min_open_index + 1] == "12"
    assert "--autoencoder-max-cosine-regression" not in paired["autoencoder_command"]
    assert "--learning-rate-floor-ratio" in paired["autoencoder_command"]
    assert "--learning-rate-cap-ratio" in paired["autoencoder_command"]
    assert "--learning-rate-plateau-delta" in paired["autoencoder_command"]
    metric_bridge_index = paired["autoencoder_command"].index(
        "--autoencoder-metric-bridge-adapters"
    )
    assert paired["autoencoder_command"][metric_bridge_index + 1] == "default"
    diagnostic_bridge_index = paired["autoencoder_command"].index(
        "--autoencoder-diagnostic-bridge-adapters"
    )
    assert paired["autoencoder_command"][diagnostic_bridge_index + 1] == "none"


def test_cycle_learning_rate_reacts_to_plateau_and_cosine_regression() -> None:
    args = SimpleNamespace(
        learning_rate=0.3,
        learning_rate_floor_ratio=0.25,
        learning_rate_cap_ratio=1.5,
        learning_rate_plateau_delta=1.0e-5,
    )
    baseline_lr, baseline_policy = runner._cycle_learning_rate(args, {})
    plateau_lr, plateau_policy = runner._cycle_learning_rate(
        args,
        {"learning_rate_plateau_streak": 4, "learning_rate_cosine_regression_streak": 0},
    )
    regressed_lr, regressed_policy = runner._cycle_learning_rate(
        args,
        {"learning_rate_plateau_streak": 4, "learning_rate_cosine_regression_streak": 2},
    )

    assert baseline_lr == pytest.approx(0.3)
    assert plateau_lr < baseline_lr
    assert regressed_lr < plateau_lr
    assert baseline_policy["plateau_streak"] == 0
    assert plateau_policy["plateau_streak"] == 4
    assert regressed_policy["cosine_regression_streak"] == 2


def test_cycle_cadence_modes() -> None:
    assert runner._should_run_cycle_cadence(
        cycle=3,
        mode="every_cycle",
        every_n_cycles=4,
    )
    assert not runner._should_run_cycle_cadence(
        cycle=4,
        mode="off",
        every_n_cycles=4,
    )
    assert runner._should_run_cycle_cadence(
        cycle=8,
        mode="periodic",
        every_n_cycles=4,
    )
    assert not runner._should_run_cycle_cadence(
        cycle=7,
        mode="periodic",
        every_n_cycles=4,
    )


def test_todo_supervisor_starvation_skip_decision_counts_open_work() -> None:
    stocked = runner._todo_supervisor_skip_decision(
        mode="starved",
        program_synthesis_status={
            "pending": 9,
            "claimed": 3,
            "completed": 40,
            "failed_validation": 12,
        },
        min_open=12,
    )
    assert stocked["skipped"] is True
    assert stocked["open_count"] == 12
    assert stocked["skip_reason"] == "program_synthesis_queue_sufficient"

    starved = runner._todo_supervisor_skip_decision(
        mode="starved",
        program_synthesis_status={
            "pending": 8,
            "claimed": 3,
            "completed": 40,
            "failed_validation": 99,
        },
        min_open=12,
    )
    assert starved["skipped"] is False
    assert starved["open_count"] == 11
    assert starved["skip_reason"] == ""

    disabled = runner._todo_supervisor_skip_decision(
        mode="off",
        program_synthesis_status={"pending": 0, "claimed": 0},
        min_open=12,
    )
    assert disabled["skipped"] is True
    assert disabled["skip_reason"] == "todo_supervisor_disabled"


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
        codex_model="gpt-5.5",
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
        codex_model="gpt-5.5",
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
        codex_model="gpt-5.5",
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
        codex_model="gpt-5.5",
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


def test_build_paired_daemon_commands_pass_projection_bounds_to_autoencoder() -> None:
    args = SimpleNamespace(
        run_id="projection-root",
        autoencoder_run_id=None,
        codex_run_id=None,
        duration_seconds=60.0,
        train_count=2,
        validation_count=1,
        max_inner_iterations=1,
        max_items=3,
        learning_rate=0.1,
        sampling_seed="shared-hparam-seed",
        generalizable_projection_timeout_seconds=123.0,
        generalizable_projection_max_line_search_attempts=4,
        autoencoder_bootstrap_mode="fast",
        test_every_cycles=50,
        poll_seconds=2.0,
        worker_id="codex-worker",
        codex_exec_mode="codex_cli",
        codex_command="codex",
        codex_model="gpt-5.3-codex",
        codex_apply_mode="apply_to_main",
        codex_commit_mode="commit_applied",
        codex_scope=None,
        codex_parallel_scopes="",
        codex_scope_workers=1,
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

    command = paired["autoencoder_command"]
    assert command[command.index("--sampling-seed") + 1] == "shared-hparam-seed"
    assert command[command.index("--generalizable-projection-timeout-seconds") + 1] == "123.0"
    assert (
        command[command.index("--generalizable-projection-max-line-search-attempts") + 1]
        == "4"
    )
    assert command[command.index("--autoencoder-bootstrap-mode") + 1] == "fast"


def test_initial_summary_uses_explicit_sampling_seed(tmp_path) -> None:
    args = SimpleNamespace(
        run_id="summary-run",
        sampling_seed="shared-hparam-seed",
        queue_run_id=None,
        bridge_evaluate_provers=False,
        bridge_loss_adapters="none",
        uscode_embeddings_mode="off",
        uscode_embeddings_path="",
        learning_rate=0.1,
    )

    summary = runner.initial_summary(
        args,
        log_path=tmp_path / "run.jsonl",
        queue_path=tmp_path / "queue.json",
        state_path=tmp_path / "state.json",
    )
    expected_seed, expected_source = runner._sampling_seed_for_args(args)

    assert summary["seed"] == expected_seed
    assert summary["sampling_seed_source"] == expected_source
    assert summary["sampling_seed_source"] == "shared-hparam-seed"


def test_autoencoder_signal_health_flags_inactive_legal_ir_and_timeouts() -> None:
    health = runner.autoencoder_validation_signal_health(
        compiler_ir_validation={
            "evaluated_count": 0,
            "sample_count": 2,
            "sample_timeouts": 2,
            "skipped_sample_count": 2,
        },
        learned_ir_validation={"target_count": 0},
        logic_bridge_validation={"adapter_count": 0, "evaluated_count": 0},
        validation_metrics={"sample_count": 4},
        metric_bridge_adapters=[],
        diagnostic_bridge_adapters=[],
    )

    assert health["quality_gate"] == "fail"
    assert "learned_ir_targets_inactive" in health["issues"]
    assert "compiler_ir_all_samples_timed_out" in health["issues"]
    assert "validation_holdout_too_small" in health["issues"]
    assert health["learned_ir"]["target_count"] == 0


def test_paired_autoencoder_child_health_detects_stale_projection(tmp_path) -> None:
    summary_path = tmp_path / "autoencoder.summary"
    summary_path.write_text(
        json.dumps(
            {
                "active_cycle": 4,
                "active_cycle_elapsed_seconds": 1200.0,
                "active_cycle_last_heartbeat_at": "2026-06-05T00:00:00Z",
                "active_cycle_phase": "generalizable_projection",
                "active_cycle_projection_progress": {"stage": "line_search_attempt"},
                "active_cycle_projection_stage": "line_search_attempt",
                "cycles": 3,
                "final": False,
                "latest_stop_reason": "running",
                "updated_at": "2026-06-05T00:00:05Z",
            }
        ),
        encoding="utf-8",
    )

    health = runner.paired_autoencoder_child_health(
        summary_path,
        now=runner.parse_utc("2026-06-05T00:20:00+00:00"),
    )

    assert health["autoencoder_summary_exists"] is True
    assert health["autoencoder_active_cycle"] == 4
    assert health["autoencoder_active_cycle_phase"] == "generalizable_projection"
    assert health["autoencoder_active_cycle_heartbeat_age_seconds"] == pytest.approx(1200.0)
    assert health["autoencoder_effective_heartbeat_age_seconds"] == pytest.approx(1200.0)
    assert health["autoencoder_summary_final"] is False
    assert health["autoencoder_summary_age_seconds"] == pytest.approx(1195.0)


def test_save_summary_writes_complete_json_and_cleans_tempfile(tmp_path) -> None:
    summary_path = tmp_path / "daemon.summary"
    summary = {"cycles": 3}

    runner.save_summary(summary_path, summary)

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["cycles"] == 3
    assert data["final"] is False
    assert data["updated_at"]
    assert not list(tmp_path.glob(".daemon.summary.*.tmp"))


def test_paired_codex_status_accepts_runner_terminated_children() -> None:
    assert runner._paired_codex_children_succeeded(
        {
            "paired-root-codex-compiler_ambiguity": -signal.SIGTERM,
            "paired-root-codex-ir_decompiler": 0,
        },
        autoencoder_exit_code=0,
        runner_terminated_children={"paired-root-codex-compiler_ambiguity"},
        stop_requested=False,
    )
    assert runner._paired_codex_children_succeeded(
        {
            "paired-root-codex-compiler_ambiguity": -signal.SIGTERM,
            "paired-root-codex-ir_decompiler": 0,
        },
        autoencoder_exit_code=-signal.SIGTERM,
        autoencoder_success=True,
        runner_terminated_children={
            "paired-root-autoencoder",
            "paired-root-codex-compiler_ambiguity",
        },
        stop_requested=False,
    )


def test_paired_codex_status_rejects_external_or_crashed_children() -> None:
    assert not runner._paired_codex_children_succeeded(
        {"paired-root-codex-compiler_ambiguity": -signal.SIGTERM},
        autoencoder_exit_code=0,
        runner_terminated_children={"paired-root-codex-compiler_ambiguity"},
        stop_requested=True,
    )
    assert not runner._paired_codex_children_succeeded(
        {"paired-root-codex-compiler_ambiguity": 2},
        autoencoder_exit_code=0,
        runner_terminated_children=set(),
        stop_requested=False,
    )
    assert not runner._paired_codex_children_succeeded(
        {"paired-root-codex-compiler_ambiguity": -signal.SIGTERM},
        autoencoder_exit_code=1,
        runner_terminated_children={"paired-root-codex-compiler_ambiguity"},
        stop_requested=False,
    )


def test_paired_autoencoder_status_requires_own_clean_stop() -> None:
    assert runner._paired_autoencoder_succeeded(
        autoencoder_run_id="paired-root-autoencoder",
        autoencoder_exit_code=0,
        runner_terminated_children=set(),
    )
    assert not runner._paired_autoencoder_succeeded(
        autoencoder_run_id="paired-root-autoencoder",
        autoencoder_exit_code=0,
        runner_terminated_children={"paired-root-autoencoder"},
    )
    assert runner._paired_autoencoder_succeeded(
        autoencoder_run_id="paired-root-autoencoder",
        autoencoder_exit_code=-signal.SIGTERM,
        autoencoder_child_health={
            "autoencoder_cycles": 31,
            "autoencoder_latest_stop_reason": "no_claimed_todos",
            "autoencoder_summary_final": False,
        },
        runner_terminated_children={"paired-root-autoencoder"},
    )
    assert not runner._paired_autoencoder_succeeded(
        autoencoder_run_id="paired-root-autoencoder",
        autoencoder_exit_code=1,
        runner_terminated_children=set(),
    )
    assert not runner._paired_autoencoder_succeeded(
        autoencoder_run_id="paired-root-autoencoder",
        autoencoder_exit_code=-signal.SIGTERM,
        autoencoder_child_health={
            "autoencoder_cycles": 0,
            "autoencoder_latest_stop_reason": "no_claimed_todos",
            "autoencoder_summary_final": False,
        },
        runner_terminated_children={"paired-root-autoencoder"},
    )
    assert not runner._paired_autoencoder_succeeded(
        autoencoder_run_id="paired-root-autoencoder",
        autoencoder_exit_code=-signal.SIGTERM,
        autoencoder_child_health={
            "autoencoder_cycles": 31,
            "autoencoder_latest_stop_reason": "no_claimed_todos",
            "autoencoder_summary_final": False,
        },
        runner_terminated_children={"paired-root-autoencoder"},
        stop_requested=True,
    )


def test_paired_accelerate_style_restart_policy_replaces_only_crashed_children() -> None:
    assert runner._paired_child_exit_should_restart(
        exit_code=2,
        restart_count=0,
        restart_limit=3,
    )
    assert runner._paired_child_exit_should_restart(
        exit_code=-signal.SIGKILL,
        restart_count=2,
        restart_limit=3,
    )
    assert runner._paired_child_exit_should_restart(
        exit_code=0,
        latest_stop_reason="signal_15",
        restart_count=0,
        restart_limit=3,
    )
    assert not runner._paired_child_exit_should_restart(
        exit_code=0,
        restart_count=0,
        restart_limit=3,
    )
    assert not runner._paired_child_exit_should_restart(
        exit_code=None,
        restart_count=0,
        restart_limit=3,
    )
    assert not runner._paired_child_exit_should_restart(
        exit_code=2,
        restart_count=3,
        restart_limit=3,
    )
    assert not runner._paired_child_exit_should_restart(
        exit_code=2,
        restart_count=0,
        restart_limit=3,
        stop_requested=True,
    )
    assert not runner._paired_child_exit_should_restart(
        exit_code=0,
        latest_stop_reason="signal_15",
        restart_count=0,
        restart_limit=3,
        stop_requested=True,
    )


def test_paired_supervisor_backend_defaults_to_accelerate_style() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-default",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
        ]
    )

    assert args.paired_supervisor_backend == "accelerate_style"


def test_should_run_cycle_tests_treats_nonpositive_cadence_as_disabled() -> None:
    assert runner._should_run_cycle_tests(1, 0) is False
    assert runner._should_run_cycle_tests(1, -5) is False
    assert runner._should_run_cycle_tests(3, 2) is False
    assert runner._should_run_cycle_tests(4, 2) is True


def test_rollout_baseline_snapshot_collects_go_no_go_fields() -> None:
    snapshot = runner.rollout_baseline_snapshot(
        summary={
            "autoencoder_architecture_version": "test-arch",
            "autoencoder_state_schema_version": "state-v-test",
            "metric_schema_version": "metric-v-test",
            "run_id": "baseline-run",
            "state_path": "/tmp/state.json",
        },
        cycle=3,
        cycle_seconds=12.3456,
        cycle_phase_timings={
            "sampling": 0.5,
            "compiler_ir_metrics": 3.25,
        },
        validation_metrics={
            "cosine_similarity": 0.91,
            "cross_entropy_excess_loss": 0.2,
            "cross_entropy_loss": 1.7,
            "reconstruction_loss": 0.04,
            "sample_count": 5,
        },
        compiler_ir_validation={
            "cosine_similarity": 0.62,
            "cross_entropy_loss": 2.5,
            "evaluated_count": 2,
            "metric_failures": 1,
            "persistent_sample_cache_hits": 7,
            "persistent_sample_cache_misses": 3,
            "sample_count": 4,
            "sample_timeouts": 1,
            "skipped_sample_count": 2,
            "source_copy_reward_hack_penalty": 0.33,
            "text_length_skipped_count": 1,
        },
        compiler_ir_guided_validation={
            "cosine_similarity": 0.66,
            "cross_entropy_loss": 2.1,
            "persistent_cache_hit": True,
            "source_copy_reward_hack_penalty": 0.22,
        },
        learned_ir_validation={
            "family_cross_entropy_excess_loss": 0.4,
            "target_count": 6,
            "view_cosine_similarity": 0.73,
            "view_cross_entropy_loss": 1.2,
        },
        logic_bridge_validation={
            "acceptance_rate": 0.8,
            "adapter_count": 2,
            "evaluated_count": 3,
            "metric_failures": 0,
            "proof_failure_ratio": 0.1,
            "sample_count": 3,
            "total_loss": 0.25,
        },
        queue_counts={"pending": 9, "failed_validation": 2},
        role_queue_counts={"program_synthesis": {"pending": 9}},
        state_telemetry={
            "generalizable_entry_count": 11,
            "nested_logit_entry_count": 13,
            "state_file": {
                "path": "/tmp/state.json",
                "size_bytes": 1024,
                "size_mb": 0.001,
            },
            "low_rank_sidecar": {
                "complete": False,
                "enabled": True,
                "status": "saved",
                "vector_entry_count": 16,
            },
            "vector_entry_count": 17,
        },
        embedding_report={"embedding_model": "mock:test", "enabled": True},
        backend_metadata={
            "autoencoder_compute_backend": "torch_cpu",
            "autoencoder_compute_device": "cpu",
        },
        host_resource_health={
            "cpu_count": 8,
            "memory_available_gb": 32.0,
            "swap_free_gb": 4.0,
        },
        metric_bridge_adapters=["modal_frame_logic", "deontic_norms"],
        diagnostic_bridge_adapters=["modal_frame_logic", "deontic_norms"],
    )

    assert snapshot["run_id"] == "baseline-run"
    assert snapshot["cycle_seconds"] == pytest.approx(12.346)
    assert snapshot["failed_validation_count"] == 2
    assert snapshot["validation"]["cross_entropy_loss"] == pytest.approx(1.7)
    assert snapshot["compiler_ir_validation"]["sample_timeouts"] == 1
    assert snapshot["compiler_ir_metric_cache"]["validation_sample_cache_hits"] == 7
    assert snapshot["compiler_ir_metric_cache"]["guided_validation_block_cache_hit"] is True
    assert snapshot["learned_ir_view_validation"]["target_count"] == 6
    assert snapshot["logic_bridge_validation"]["acceptance_rate"] == pytest.approx(0.8)
    assert snapshot["state_file"]["size_bytes"] == 1024
    assert snapshot["learned_feature_rows"]["vector_entry_count"] == 17
    assert snapshot["backend"]["autoencoder_compute_backend"] == "torch_cpu"
    assert snapshot["host_resource_health"]["memory_available_gb"] == pytest.approx(32.0)
    assert snapshot["signal_health"]["quality_gate"] == "warn"
    assert "validation_holdout_too_small" in snapshot["signal_health"]["issues"]


def test_paired_codex_worker_resource_plan_caps_memory_heavy_pool() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-resource-plan",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--paired-resource-guard",
            "auto",
            "--paired-reserved-memory-gb",
            "24",
            "--paired-codex-worker-memory-gb",
            "2",
        ]
    )

    plan = runner.paired_codex_worker_resource_plan(
        args,
        requested_workers=29,
        resource_health={
            "cpu_count": 20,
            "memory_available_gb": 85.0,
            "memory_total_gb": 121.0,
        },
    )

    assert plan["reason"] == "auto_cpu_memory_cap"
    assert plan["cpu_cap"] == 12
    assert plan["memory_cap"] == 30
    assert plan["effective_workers"] == 12


def test_paired_codex_worker_resource_plan_caps_swap_pressure() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-resource-plan-swap",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--paired-resource-guard",
            "auto",
            "--paired-reserved-memory-gb",
            "24",
            "--paired-codex-worker-memory-gb",
            "2",
            "--paired-min-swap-free-gb",
            "1",
        ]
    )

    plan = runner.paired_codex_worker_resource_plan(
        args,
        requested_workers=29,
        resource_health={
            "cpu_count": 20,
            "memory_available_gb": 85.0,
            "memory_total_gb": 121.0,
            "swap_free_gb": 0.05,
            "swap_total_gb": 16.0,
        },
    )

    assert plan["reason"] == "auto_cpu_memory_swap_cap"
    assert plan["swap_pressure"] is True
    assert plan["swap_cap"] == 8
    assert plan["effective_workers"] == 8


def test_paired_resource_pressure_includes_low_swap() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-resource-pressure-swap",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--paired-min-available-memory-gb",
            "12",
            "--paired-min-swap-free-gb",
            "1",
        ]
    )

    pressure, report = runner._paired_resource_pressure(
        args,
        resource_health={
            "cpu_count": 20,
            "memory_available_gb": 64.0,
            "memory_total_gb": 121.0,
            "swap_free_gb": 0.05,
            "swap_total_gb": 16.0,
        },
    )

    assert pressure is True
    assert report["memory_pressure"] is False
    assert report["swap_pressure"] is True
    assert report["resource_pressure"] is True
    assert report["swap_blocks_restart"] is True


def test_paired_resource_pressure_does_not_swap_block_autoencoder_restart() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-resource-pressure-autoencoder-swap",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--paired-min-available-memory-gb",
            "12",
            "--paired-min-swap-free-gb",
            "1",
        ]
    )

    pressure, report = runner._paired_resource_pressure(
        args,
        role="autoencoder",
        resource_health={
            "cpu_count": 20,
            "memory_available_gb": 64.0,
            "memory_total_gb": 121.0,
            "swap_free_gb": 0.05,
            "swap_total_gb": 16.0,
        },
    )

    assert pressure is False
    assert report["memory_pressure"] is False
    assert report["restart_role"] == "autoencoder"
    assert report["swap_blocks_restart"] is False
    assert report["swap_pressure"] is True
    assert report["resource_pressure"] is False


def test_paired_codex_child_env_hides_cuda_by_default() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-codex-env",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
        ]
    )

    env = runner.paired_codex_child_env(args)

    assert env["CUDA_VISIBLE_DEVICES"] == ""
    assert env["NVIDIA_VISIBLE_DEVICES"] == "none"
    assert env["IPFS_DATASETS_CODEX_TASK_EMBEDDINGS_DEVICE"] == "cpu"


def test_paired_codex_child_env_can_leave_cuda_visible() -> None:
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "paired-codex-env-visible",
            "--duration-seconds",
            "1",
            "--loop-role",
            "paired",
            "--paired-codex-disable-cuda",
            "false",
        ]
    )

    assert runner.paired_codex_child_env(args) == {}


def test_round_robin_codex_worker_cap_preserves_scope_coverage() -> None:
    children = [
        {"run_id": "bridge-1", "scope": "bridge"},
        {"run_id": "bridge-2", "scope": "bridge"},
        {"run_id": "cec-1", "scope": "cec"},
        {"run_id": "cec-2", "scope": "cec"},
        {"run_id": "tdfol-1", "scope": "tdfol"},
        {"run_id": "tdfol-2", "scope": "tdfol"},
    ]

    selected = runner._round_robin_codex_children(children, limit=3)

    assert [child["run_id"] for child in selected] == [
        "bridge-1",
        "cec-1",
        "tdfol-1",
    ]


def test_codex_scope_fallback_claims_global_backlog_when_lane_empty() -> None:
    todo = ModalTodo(
        todo_id="program-tdfol",
        action="repair_tdfol_bridge_parse",
        objective="repair tdfol parser",
        sample_ids=["sample-tdfol"],
        citations=["5 U.S.C. 552"],
        loss_name="program_synthesis",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "tdfol",
            "target_component": "modal.tdfol",
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([todo]))

    claimed, report = runner._claim_program_synthesis_batch_with_scope_fallback(
        supervisor,
        worker_id="codex-bridge-01",
        max_items=1,
        requested_scope="bridge",
        semantic_bundle=False,
        fallback_to_global=True,
    )

    assert [item.todo_id for item in claimed] == ["program-tdfol"]
    assert claimed[0].claimed_by == "codex-bridge-01"
    assert report["fallback_used"] is True
    assert report["borrowed_scopes"] == ["tdfol"]
    assert report["requested_scope"] == "bridge"


def test_codex_scope_fallback_prefers_local_scope() -> None:
    local = ModalTodo(
        todo_id="program-bridge",
        action="repair_multiview_legal_ir_graph_projection",
        objective="repair bridge",
        sample_ids=["sample-bridge"],
        citations=["5 U.S.C. 552"],
        loss_name="program_synthesis",
        loss_value=1.0,
        priority=5.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "bridge",
            "target_component": "modal.bridge",
        },
    )
    other = ModalTodo(
        todo_id="program-tdfol",
        action="repair_tdfol_bridge_parse",
        objective="repair tdfol parser",
        sample_ids=["sample-tdfol"],
        citations=["5 U.S.C. 552"],
        loss_name="program_synthesis",
        loss_value=1.0,
        priority=50.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "tdfol",
            "target_component": "modal.tdfol",
        },
    )
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue([local, other]))

    claimed, report = runner._claim_program_synthesis_batch_with_scope_fallback(
        supervisor,
        worker_id="codex-bridge-01",
        max_items=1,
        requested_scope="bridge",
        semantic_bundle=False,
        fallback_to_global=True,
    )

    assert [item.todo_id for item in claimed] == ["program-bridge"]
    assert report["fallback_used"] is False
    assert supervisor.queue.get("program-tdfol").status == "pending"


def test_nested_bridge_adapter_parallelism_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "4")

    report = runner._clamp_nested_bridge_adapter_parallelism(
        bridge_parallel_workers=8,
        sample_parallel_workers=8,
        adapter_count=4,
    )

    assert report["clamped"] is True
    assert report["effective_adapter_workers"] == 1
    assert os.environ["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] == "1"


def test_nested_bridge_adapter_parallelism_uses_budget_for_small_metric_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "4")

    report = runner._clamp_nested_bridge_adapter_parallelism(
        bridge_parallel_workers=8,
        sample_parallel_workers=2,
        adapter_count=3,
    )

    assert report["clamped"] is True
    assert report["effective_adapter_workers"] == 3
    assert report["estimated_nested_workers"] == 6
    assert report["nested_worker_budget"] == 8
    assert os.environ["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] == "3"


def test_nested_bridge_adapter_parallelism_defaults_to_adapter_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", raising=False)

    report = runner._clamp_nested_bridge_adapter_parallelism(
        bridge_parallel_workers=8,
        sample_parallel_workers=2,
        adapter_count=3,
    )

    assert report["clamped"] is False
    assert report["effective_adapter_workers"] == 3
    assert report["estimated_nested_workers"] == 6
    assert report["requested_adapter_workers"] == 3
    assert os.environ["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] == "3"


def test_compiler_ir_metric_block_uses_persistent_sample_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    class FakeCodec:
        config = SimpleNamespace(mode="compiler-sample-cache")

        def __init__(self) -> None:
            self.calls = 0

        def encode(self, *args: object, **kwargs: object) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(
                decoded_modal_text="shall publish notice",
                frame_candidates=[object()],
                losses={
                    "cosine_loss": 0.1,
                    "cosine_similarity": 0.9,
                    "cross_entropy_loss": 0.2,
                    "source_decompiled_text_embedding_cosine_loss": 0.3,
                },
                metadata={
                    "llm_call_count": 0.0,
                    "modal_decompiler_structural_text": "The agency shall publish notice.",
                },
                modal_ir=SimpleNamespace(formulas=[object(), object()]),
            )

    codec = FakeCodec()

    first = runner.compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=32,
    )
    second = runner.compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=31,
    )

    assert codec.calls == 1
    assert first["persistent_sample_cache_misses"] == 1
    assert second["persistent_sample_cache_hits"] == 1
    assert second["cosine_similarity"] == pytest.approx(0.9)
    assert second["formula_count"] == pytest.approx(2.0)


def test_compiler_ir_metric_sample_cache_key_ignores_runner_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    codec = SimpleNamespace(
        config=SimpleNamespace(mode="compiler-sample-cache"),
    )

    first = runner._compiler_ir_metric_sample_cache_key(
        sample,
        codec=codec,
        compiler_guidance=None,
        guidance_top_k=16,
    )

    def fail_metric_fingerprint() -> str:
        raise AssertionError("compiler sample cache must not use runner fingerprint")

    monkeypatch.setattr(runner, "_metric_code_fingerprint", fail_metric_fingerprint)
    second = runner._compiler_ir_metric_sample_cache_key(
        sample,
        codec=codec,
        compiler_guidance=None,
        guidance_top_k=16,
    )

    assert second == first


def test_codex_validation_failure_details_extracts_pytest_banner_node_id() -> None:
    details = runner._codex_validation_failure_details(
        command=["python", "-m", "pytest", "tests/unit/example.py"],
        command_index=2,
        status="failed",
        exit_code=1,
        stdout=(
            "=================================== FAILURES ===================================\n"
            "___ test_spacy_compiler_adds_title_transfer_power_heading_prefix_for_43_617f ___\n"
            "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py:7642: "
            "in test_spacy_compiler_adds_title_transfer_power_heading_prefix_for_43_617f\n"
            "    assert \"transfer of title;\" in prefix_spans\n"
            "E   AssertionError: assert 'transfer of title;' in {'Canals and appurtenant structures;'}\n"
        ),
        stderr="",
    )

    node_id = (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py::"
        "test_spacy_compiler_adds_title_transfer_power_heading_prefix_for_43_617f"
    )
    assert details["failed_tests"] == [node_id]
    assert details["failure_tokens"] == [f"pytest:{node_id}"]


def test_paired_program_synthesis_health_detects_starved_codex_queue(tmp_path: Path) -> None:
    metadata = {
        "optimizer_role": "program_synthesis",
        "program_synthesis_scope": "ir_decompiler",
    }
    completed = ModalTodo(
        todo_id="completed",
        action="refine_typed_ir_or_decompiler_slots",
        objective="completed",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=2.0,
        status="completed",
        metadata=dict(metadata),
    )
    failed = ModalTodo(
        todo_id="failed",
        action="refine_typed_ir_or_decompiler_slots",
        objective="failed",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=1.0,
        status="failed_validation",
        metadata={
            **metadata,
            "failed_validation_reason": "main_apply_validation_failed_rolled_back",
            "failed_validation_report": {
                "main_apply_validation_failed_tests": [
                    "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py::test_heading_prefix"
                ],
                "main_apply_validation_failure_tokens": [
                    "pytest:tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py::test_heading_prefix"
                ],
            },
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([completed, failed]).save_jsonl(queue_path)
    child_summary = tmp_path / "codex.summary"
    child_summary.write_text(
        json.dumps(
            {
                "codex_claimed_total": 2,
                "codex_execution_count": 2,
                "codex_scope": "ir_decompiler",
                "latest_stop_reason": "waiting_for_program_synthesis_todos",
            }
        ),
        encoding="utf-8",
    )

    health = runner.paired_program_synthesis_health(
        queue_path=queue_path,
        codex_summary_paths=[child_summary],
    )

    assert health["program_synthesis_pending"] == 0
    assert health["program_synthesis_claimed"] == 0
    assert health["program_synthesis_completed"] == 1
    assert health["program_synthesis_failed_validation"] == 1
    assert health["program_synthesis_failed_validation_reason_counts"] == {
        "main_apply_validation_failed_rolled_back": 1
    }
    assert health["program_synthesis_failed_validation_kind_counts"] == {
        "pytest": 1
    }
    assert health["program_synthesis_failed_validation_test_counts"] == {
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py::test_heading_prefix": 1
    }
    assert health["codex_queue_starved"] is True
    assert health["codex_workers_waiting_for_todos_count"] == 1
    assert health["codex_claimed_total"] == 2


def test_paired_program_synthesis_health_treats_active_packet_as_working(
    tmp_path: Path,
) -> None:
    metadata = {
        "optimizer_role": "program_synthesis",
        "program_synthesis_scope": "bridge",
    }
    claimed = ModalTodo(
        todo_id="claimed",
        action="repair_multiview_legal_ir_loss",
        objective="claimed",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=2.0,
        status="claimed",
        claimed_by="codex-bridge-01",
        metadata=dict(metadata),
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([claimed]).save_jsonl(queue_path)
    child_summary = tmp_path / "codex.summary"
    child_summary.write_text(
        json.dumps(
            {
                "active_packet_claimed_todo_ids": ["claimed"],
                "active_packet_phase": "executing_codex_packet",
                "codex_claimed_total": 0,
                "codex_execution_count": 0,
                "codex_scope": "bridge",
                "latest_stop_reason": "waiting_for_program_synthesis_todos",
                "worker_id": "codex-bridge-01",
            }
        ),
        encoding="utf-8",
    )

    health = runner.paired_program_synthesis_health(
        queue_path=queue_path,
        codex_summary_paths=[child_summary],
    )

    assert health["program_synthesis_claimed"] == 1
    assert health["codex_workers_active_packet_count"] == 1
    assert health["codex_workers_waiting_for_todos_count"] == 0
    assert health["codex_queue_starved"] is False


def test_paired_failed_validation_rescue_should_seed_starved_queue() -> None:
    health = {
        "codex_queue_starved": True,
        "program_synthesis_claimed": 0,
        "program_synthesis_failed_validation": 3,
        "program_synthesis_pending": 0,
        "queue_exists": True,
    }

    assert runner._paired_failed_validation_rescue_should_seed(
        health,
        mode="auto",
        last_seed_at=10.0,
        interval_seconds=30.0,
        now=41.0,
    )
    assert not runner._paired_failed_validation_rescue_should_seed(
        health,
        mode="off",
        last_seed_at=10.0,
        interval_seconds=30.0,
        now=41.0,
    )
    assert not runner._paired_failed_validation_rescue_should_seed(
        {**health, "program_synthesis_pending": 1},
        mode="auto",
        last_seed_at=10.0,
        interval_seconds=30.0,
        now=41.0,
    )
    busy_health = {
        **health,
        "codex_queue_starved": False,
        "codex_worker_summary_count": 4,
        "codex_workers_active_packet_count": 2,
        "codex_workers_waiting_for_todos_count": 2,
        "program_synthesis_claimed": 1,
        "program_synthesis_pending": 2,
    }
    assert runner._paired_failed_validation_rescue_should_seed(
        busy_health,
        mode="auto",
        last_seed_at=10.0,
        interval_seconds=30.0,
        now=41.0,
    )
    backlog_health = {
        **busy_health,
        "codex_workers_active_packet_count": 4,
        "codex_workers_waiting_for_todos_count": 0,
        "program_synthesis_failed_validation": 40,
    }
    assert runner._paired_failed_validation_rescue_should_seed(
        backlog_health,
        mode="auto",
        last_seed_at=10.0,
        interval_seconds=30.0,
        backlog_threshold=32,
        now=41.0,
    )
    assert not runner._paired_failed_validation_rescue_should_seed(
        busy_health,
        mode="starved",
        last_seed_at=10.0,
        interval_seconds=30.0,
        now=41.0,
    )
    assert not runner._paired_failed_validation_rescue_should_seed(
        busy_health,
        mode="auto",
        last_seed_at=20.0,
        interval_seconds=30.0,
        now=41.0,
    )


def test_paired_supervisor_seeds_failed_validation_rescue_for_starved_queue(
    tmp_path: Path,
) -> None:
    failed = ModalTodo(
        todo_id="failed-ir",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["sample-a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=44.0,
        status="failed_validation",
        metadata={
            "execution_target": "codex_program_repair",
            "failure_reason": "main_apply_validation_failed_rolled_back",
            "optimizer_role": "program_synthesis",
            "optimizer_stage": "typed_program_synthesis",
            "program_synthesis_scope": "ir_decompiler",
            "target_component": "modal.ir_decompiler",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([failed]).save_jsonl(queue_path)

    report = runner.seed_failed_validation_rescue_todos_for_queue(
        queue_path=queue_path,
        max_clusters=4,
    )

    queue = ModalTodoQueue.load_jsonl(queue_path)
    rescue_todos = [
        todo
        for todo in queue.pending(optimizer_role="program_synthesis")
        if todo.action == daemon.FAILED_VALIDATION_RESCUE_ACTION
    ]
    health = runner.paired_program_synthesis_health(
        queue_path=queue_path,
        codex_summary_paths=[],
    )

    assert report["seeded_count"] == 1
    assert report["deduped_count"] == 0
    assert report["seeded_todo_ids"] == [rescue_todos[0].todo_id]
    assert report["before"]["failed_validation"] == 1
    assert report["after"]["pending"] == 1
    assert len(rescue_todos) == 1
    assert rescue_todos[0].metadata["source"] == "failed_validation_rescue_v1"
    assert health["codex_queue_starved"] is False
    assert health["program_synthesis_pending"] == 1

    duplicate_report = runner.seed_failed_validation_rescue_todos_for_queue(
        queue_path=queue_path,
        max_clusters=4,
    )

    assert duplicate_report["seeded_count"] == 0
    assert duplicate_report["deduped_count"] == 1


def test_paired_supervisor_supersedes_completed_rescue_backlog(
    tmp_path: Path,
) -> None:
    failed = ModalTodo(
        todo_id="failed-ir",
        action="refine_typed_ir_or_decompiler_slots",
        objective="repair typed slots",
        sample_ids=["sample-a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=2.0,
        priority=44.0,
        status="failed_validation",
        metadata={
            "execution_target": "codex_program_repair",
            "failure_reason": "main_apply_validation_failed_rolled_back",
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "ir_decompiler",
            "target_component": "modal.ir_decompiler",
        },
    )
    rescue = ModalTodo(
        todo_id="rescue-completed",
        action=daemon.FAILED_VALIDATION_RESCUE_ACTION,
        objective="completed rescue",
        sample_ids=["sample-a"],
        citations=["5 U.S.C. 552"],
        loss_name="failed_validation_rescue",
        loss_value=1.0,
        priority=50.0,
        metadata={
            "failed_todo_ids": ["failed-ir"],
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "ir_decompiler",
            "target_component": "modal.ir_decompiler",
        },
    )
    rescue.complete()
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([failed, rescue]).save_jsonl(queue_path)

    report = runner.seed_failed_validation_rescue_todos_for_queue(
        queue_path=queue_path,
        max_clusters=4,
    )
    health = runner.paired_program_synthesis_health(
        queue_path=queue_path,
        codex_summary_paths=[],
    )
    queue = ModalTodoQueue.load_jsonl(queue_path)

    assert report["seeded_count"] == 0
    assert report["superseded_count"] == 1
    assert report["reason"] == "resolved_by_completed_rescue"
    assert queue.get("failed-ir").status == "superseded"
    assert health["program_synthesis_failed_validation"] == 0
    assert health["program_synthesis_superseded"] == 1
    assert health["codex_queue_drained"] is True
    assert health["codex_queue_starved"] is False


def test_paired_program_synthesis_health_detects_stale_claimed_codex_worker(
    tmp_path: Path,
) -> None:
    claimed = ModalTodo(
        todo_id="claimed-bridge",
        action="repair_multiview_legal_ir_loss",
        objective="claimed bridge repair",
        sample_ids=["sample-a"],
        citations=[],
        loss_name="legal_ir_multiview_total_loss",
        loss_value=1.0,
        priority=3.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "bridge",
        },
    )
    queue = ModalTodoQueue([claimed])
    queue.claim_batch(
        worker_id="codex-bridge-01",
        max_items=1,
        optimizer_role="program_synthesis",
    )
    queue_path = tmp_path / "queue.jsonl"
    queue.save_jsonl(queue_path)
    child_summary = tmp_path / "codex-bridge-01.summary"
    child_summary.write_text(
        json.dumps(
            {
                "codex_claimed_total": 1,
                "codex_execution_count": 0,
                "codex_scope": "bridge",
                "heartbeat_at": "2026-06-05T00:00:00+00:00",
                "latest_stop_reason": "claimed_program_synthesis_todos",
                "worker_id": "codex-bridge-01",
            }
        ),
        encoding="utf-8",
    )

    health = runner.paired_program_synthesis_health(
        queue_path=queue_path,
        codex_summary_paths=[child_summary],
        codex_worker_stale_seconds=60.0,
    )

    assert health["program_synthesis_claimed"] == 1
    assert health["program_synthesis_claimed_by_worker"] == {"codex-bridge-01": 1}
    assert health["codex_worker_stale_count"] == 1
    assert health["codex_idle_worker_stale_count"] == 0
    assert health["stale_claimed_codex_worker_ids"] == ["codex-bridge-01"]


def test_codex_main_apply_backpressure_blocks_new_claims_when_lane_is_full() -> None:
    claimed = ModalTodo(
        todo_id="claimed-bridge",
        action="repair_bridge",
        objective="claimed bridge repair",
        sample_ids=["sample-a"],
        citations=[],
        loss_name="legal_ir_bridge_loss",
        loss_value=1.0,
        priority=3.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "bridge",
        },
    )
    pending = ModalTodo(
        todo_id="pending-bridge",
        action="repair_next_bridge",
        objective="pending bridge repair",
        sample_ids=["sample-b"],
        citations=[],
        loss_name="legal_ir_bridge_loss",
        loss_value=1.0,
        priority=2.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "bridge",
        },
    )
    queue = ModalTodoQueue([claimed, pending])
    queue.claim_batch(
        worker_id="codex-bridge-01",
        max_items=1,
        optimizer_role="program_synthesis",
    )

    report = runner._codex_main_apply_backpressure_report(
        queue,
        args=SimpleNamespace(
            codex_apply_mode="apply_to_main",
            codex_main_apply_max_inflight_packets=1,
        ),
        policy=ModalOptimizerPolicy(),
        worker_id="codex-bridge-02",
    )

    assert report["blocked"] is True
    assert report["reason"] == "main_apply_inflight_limit_reached"
    assert report["active_packet_count"] == 1
    assert report["pending_count"] == 1


def test_vector_claim_rechecks_main_apply_backpressure_after_indexing(
    tmp_path,
    monkeypatch,
) -> None:
    first = ModalTodo(
        todo_id="program-first",
        action="repair_first",
        objective="first repair",
        sample_ids=["sample-a"],
        citations=[],
        loss_name="legal_ir_loss",
        loss_value=1.0,
        priority=3.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
        },
    )
    second = ModalTodo(
        todo_id="program-second",
        action="repair_second",
        objective="second repair",
        sample_ids=["sample-b"],
        citations=[],
        loss_name="legal_ir_loss",
        loss_value=1.0,
        priority=2.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_registry",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([first, second]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        items = list(todos)
        queue = ModalTodoQueue.load_jsonl(queue_path)
        queue.claim_todo_ids(
            worker_id="codex-other",
            todo_ids=["program-second"],
            optimizer_role="program_synthesis",
        )
        queue.save_jsonl(queue_path)
        return (
            {item.todo_id: [1.0, 0.0] for item in items},
            {
                "backend": "local",
                "fallback_reason": "",
                "indexed_count": len(items),
                "path": str(index_path),
                "provider": "test",
                "refreshed_count": len(items),
            },
        )

    monkeypatch.setattr(runner, "_update_codex_task_vector_index", fake_vector_index)
    args = SimpleNamespace(
        codex_apply_mode="apply_to_main",
        codex_main_apply_max_inflight_packets=1,
        codex_scope="compiler_registry",
        codex_scope_fallback_to_global=True,
        codex_target_file_lane_lock_scopes="all",
        codex_target_file_lane_lock_seconds=0.0,
        codex_lane_lock_mode="hybrid",
        codex_vector_fill_min_similarity=0.0,
        codex_vector_index_path=None,
        codex_vector_min_bundle_size=1,
        codex_vector_min_similarity=0.0,
        codex_vector_max_bundle_wait_seconds=0.0,
        codex_vector_stale_drain_cooldown_seconds=0.0,
        codex_task_embeddings_batch_size=32,
        codex_task_embeddings_provider="local_adapter",
        codex_vector_fallback_mode="hash",
        max_items=1,
    )

    claimed, queue, status, report = runner._claim_vector_program_synthesis_batch(
        args=args,
        queue_path=queue_path,
        worker_id="codex-this",
        policy=ModalOptimizerPolicy(),
        execution_mode="codex_cli_executor",
        summary={},
    )

    assert claimed == []
    assert queue.get("program-first").status == "pending"
    assert queue.get("program-second").status == "claimed"
    assert status["pending"] == 1
    assert status["claimed"] == 1
    assert report["mode"] == "main_apply_backpressure"
    assert report["main_apply_backpressure_active_workers"] == ["codex-other"]


def test_paired_program_synthesis_health_separates_stale_idle_codex_worker(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([]).save_jsonl(queue_path)
    child_summary = tmp_path / "codex-bridge-01.summary"
    child_summary.write_text(
        json.dumps(
            {
                "codex_claimed_total": 1,
                "codex_execution_count": 1,
                "codex_scope": "bridge",
                "heartbeat_at": "2026-06-05T00:00:00+00:00",
                "latest_stop_reason": "waiting_for_program_synthesis_todos",
                "worker_id": "codex-bridge-01",
            }
        ),
        encoding="utf-8",
    )

    health = runner.paired_program_synthesis_health(
        queue_path=queue_path,
        codex_summary_paths=[child_summary],
        codex_worker_stale_seconds=60.0,
    )

    assert health["program_synthesis_claimed"] == 0
    assert health["codex_worker_stale_count"] == 0
    assert health["codex_idle_worker_stale_count"] == 1
    assert health["stale_claimed_codex_worker_ids"] == []
    assert health["stale_idle_codex_worker_ids"] == ["codex-bridge-01"]


def test_codex_transient_failure_detection_reads_exec_logs(tmp_path) -> None:
    stderr_path = tmp_path / "codex-stderr.log"
    stderr_path.write_text(
        "ERROR: Selected model is at capacity. Please try a different model.\n",
        encoding="utf-8",
    )
    packet = {
        "codex_exec": {"status": "failed", "stderr_path": str(stderr_path)},
        "main_apply_status": "no_changes",
        "patch_status": "awaiting_codex_changes",
    }

    assert runner._codex_packet_should_requeue_transient(packet)


def test_codex_transient_failure_detection_ignores_applied_packets(tmp_path) -> None:
    stderr_path = tmp_path / "codex-stderr.log"
    stderr_path.write_text(
        "ERROR: Selected model is at capacity. Please try a different model.\n",
        encoding="utf-8",
    )
    packet = {
        "codex_exec": {"status": "failed", "stderr_path": str(stderr_path)},
        "main_apply_status": "applied",
        "patch_status": "applied_to_main",
    }

    assert not runner._codex_packet_should_requeue_transient(packet)


def test_run_codex_exec_attempt_timeout_returns_promptly(tmp_path) -> None:
    codex_stub = tmp_path / "codex-stub.py"
    codex_stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "import time\n"
        "sys.stdin.read()\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    codex_stub.chmod(0o755)

    result = runner._run_codex_exec_attempt(
        codex_command=str(codex_stub),
        model="gpt-5.5",
        prompt="do work\n",
        prompt_path=tmp_path / "prompt.md",
        sandbox="danger-full-access",
        stderr_path=tmp_path / "stderr.log",
        stdout_path=tmp_path / "stdout.log",
        timeout_seconds=0.1,
        worktree_path=tmp_path,
        last_message_path=tmp_path / "last.md",
    )

    assert result["status"] == "timeout"
    assert result["duration_seconds"] < 6
    assert str(codex_stub) in result["command"]


def test_codex_apply_validation_timeout_returns_promptly(tmp_path) -> None:
    result = runner._run_codex_apply_validation(
        tmp_path,
        tmp_path,
        validation_commands=[
            [
                sys.executable,
                "-c",
                "import time; time.sleep(10)",
            ]
        ],
        timeout_seconds=0.1,
    )

    assert result["status"] == "timeout"
    assert result["commands"][0]["status"] == "timeout"
    assert result["commands"][0]["duration_seconds"] < 6


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


def test_vector_claim_skips_fresh_singleton_when_later_bundle_is_ready(
    tmp_path,
    monkeypatch,
) -> None:
    singleton = ModalTodo(
        todo_id="program-parser-singleton",
        action="increase_modal_ir_span_coverage",
        objective="single parser repair",
        sample_ids=["a"],
        citations=["5 U.S.C. 552"],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_parser",
            "target_component": "modal.compiler",
        },
    )
    deontic_one = ModalTodo(
        todo_id="program-deontic-one",
        action="repair_deontic_bridge_quality_gate",
        objective="deontic bridge quality repair one",
        sample_ids=["b"],
        citations=["5 U.S.C. 552"],
        loss_name="legal_ir_multiview_total_loss",
        loss_value=0.9,
        priority=5.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "deontic",
            "target_component": "deontic.ir",
        },
    )
    deontic_two = ModalTodo(
        todo_id="program-deontic-two",
        action="repair_deontic_prover_bridge",
        objective="deontic bridge quality repair two",
        sample_ids=["c"],
        citations=["5 U.S.C. 552"],
        loss_name="legal_ir_multiview_total_loss",
        loss_value=0.8,
        priority=4.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "deontic",
            "target_component": "deontic.ir",
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([singleton, deontic_one, deontic_two]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        return (
            {
                "program-parser-singleton": [1.0, 0.0],
                "program-deontic-one": [0.0, 1.0],
                "program-deontic-two": [0.0, 0.99],
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
        codex_scope=None,
        codex_target_file_lane_lock_seconds=0.0,
        codex_vector_index_path=None,
        codex_vector_min_similarity=0.55,
        codex_vector_fill_min_similarity=None,
        codex_vector_min_bundle_size=2,
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

    assert [todo.todo_id for todo in claimed] == [
        "program-deontic-one",
        "program-deontic-two",
    ]
    assert queue.get("program-parser-singleton").status == "pending"
    assert status["claimed"] == 2
    assert report["mode"] == "vector_skipped_fresh_undersized_anchor"
    assert report["skipped_fresh_undersized_anchor_ids"] == [
        "program-parser-singleton"
    ]
    assert report["selected_count"] == 2


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


def test_vector_claim_ast_lane_allows_disjoint_modal_family_pairs(tmp_path, monkeypatch) -> None:
    active = ModalTodo(
        todo_id="program-ambiguity-active",
        action="add_or_review_modal_ambiguity_policy",
        objective="active ambiguity repair",
        sample_ids=["a"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=10.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
            "semantic_bundle_key": json.dumps(
                {
                    "action": "add_or_review_modal_ambiguity_policy",
                    "family_pairs": ["frame->deontic"],
                    "program_synthesis_scope": "compiler_ambiguity",
                    "target_component": "modal.compiler.ambiguity",
                }
            ),
        },
    )
    active.claim("other-codex-worker")
    blocked = ModalTodo(
        todo_id="program-ambiguity-blocked",
        action="add_or_review_modal_ambiguity_policy",
        objective="same family-pair ambiguity repair",
        sample_ids=["b"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=9.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
            "semantic_bundle_key": json.dumps(
                {
                    "action": "add_or_review_modal_ambiguity_policy",
                    "family_pairs": ["frame->deontic"],
                    "program_synthesis_scope": "compiler_ambiguity",
                    "target_component": "modal.compiler.ambiguity",
                }
            ),
        },
    )
    allowed = ModalTodo(
        todo_id="program-ambiguity-allowed",
        action="add_or_review_modal_ambiguity_policy",
        objective="different family-pair ambiguity repair",
        sample_ids=["c"],
        citations=[],
        loss_name="autoencoder_residual_cluster",
        loss_value=1.0,
        priority=8.0,
        metadata={
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "compiler_ambiguity",
            "target_component": "modal.compiler.ambiguity",
            "semantic_bundle_key": json.dumps(
                {
                    "action": "add_or_review_modal_ambiguity_policy",
                    "family_pairs": ["temporal->frame"],
                    "program_synthesis_scope": "compiler_ambiguity",
                    "target_component": "modal.compiler.ambiguity",
                }
            ),
        },
    )
    queue_path = tmp_path / "queue.jsonl"
    ModalTodoQueue([active, blocked, allowed]).save_jsonl(queue_path)

    def fake_vector_index(*, args, index_path, todos):
        todo_list = list(todos)
        return (
            {item.todo_id: [1.0, 0.0] for item in todo_list},
            {
                "backend": "embeddings_router",
                "fallback_reason": "",
                "indexed_count": len(todo_list),
                "path": str(index_path),
                "provider": "local_adapter",
                "refreshed_count": len(todo_list),
            },
        )

    monkeypatch.setattr(runner, "_update_codex_task_vector_index", fake_vector_index)
    args = SimpleNamespace(
        codex_scope="compiler_ambiguity",
        codex_lane_lock_mode="ast",
        codex_target_file_lane_lock_seconds=600.0,
        codex_target_file_lane_lock_scopes="all",
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

    assert [todo.todo_id for todo in claimed] == ["program-ambiguity-allowed"]
    assert queue.get("program-ambiguity-blocked").status == "pending"
    assert queue.get("program-ambiguity-allowed").status == "claimed"
    assert status["claimed"] == 2
    assert report["target_file_lane_lock_mode"] == "ast"
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


def _create_git_repo_with_program_synthesis_packet(
    tmp_path,
    *,
    tracked_python_module: bool = False,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    if tracked_python_module:
        (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    if tracked_python_module:
        subprocess.run(["git", "add", "module.py"], cwd=repo, check=True)
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
    assert "## Metric Guard" in task_text
    assert "target_metrics:" in task_text
    assert "sample_text:" in task_text
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


def test_codex_work_packet_apply_to_main_keeps_patch_when_baseline_validation_is_red(
    tmp_path,
) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    readme = Path(packet["worktree_path"]) / "README.md"
    readme.write_text("test repo\nbaseline red packet edit\n", encoding="utf-8")

    updated = apply_codex_worktree_changes_to_main(
        packet,
        validation_commands=(
            [sys.executable, "-c", "raise SystemExit(1)"],
        ),
    )

    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_validation"]["status"] == "failed"
    assert updated["main_apply_baseline_validation"]["status"] == "failed"
    assert updated["main_apply_validation_gate"] == "inconclusive_baseline_failed"
    assert updated["main_apply_baseline_failure_accepted"] is True
    assert updated["main_apply_rollback"]["exit_code"] == 0
    assert updated["main_apply_reapply_after_baseline_validation"]["exit_code"] == 0
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "test repo\nbaseline red packet edit\n"
    )

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_keeps_unavailable_target_metrics_diagnostic(
    tmp_path,
    monkeypatch,
) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    readme = Path(packet["worktree_path"]) / "README.md"
    readme.write_text("test repo\nmetric unavailable edit\n", encoding="utf-8")

    monkeypatch.setattr(
        runner,
        "_codex_packet_should_measure_target_metrics",
        lambda packet, *, target_files: True,
    )
    snapshots = iter(
        [
            {
                "metric_count": 0,
                "metrics": {},
                "sample_count": 1,
                "status": "failed",
                "target_metrics": ["cross_entropy_loss"],
            },
            {
                "metric_count": 1,
                "metrics": {"cross_entropy_loss": 0.8},
                "sample_count": 1,
                "status": "measured",
                "target_metrics": ["cross_entropy_loss"],
            },
        ]
    )
    monkeypatch.setattr(
        runner,
        "_codex_packet_target_metric_snapshot",
        lambda packet, source_repo_root: next(snapshots),
    )

    updated = apply_codex_worktree_changes_to_main(packet, validation_commands=())

    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_target_metric_gate"] == "diagnostic_unavailable"
    assert updated["target_metric_validation"]["status"] == "unavailable"
    assert "main_apply_rollback" not in updated
    assert not updated["patch_path"]
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "test repo\nmetric unavailable edit\n"
    )

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_rejects_packet_only_validation_failure(
    tmp_path,
) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    readme = Path(packet["worktree_path"]) / "README.md"
    readme.write_text("test repo\npacket-only validation edit\n", encoding="utf-8")
    validation_script = (
        "from pathlib import Path\n"
        "text = Path('README.md').read_text()\n"
        "if 'packet-only validation edit' in text:\n"
        "    print('FAILED tests/test_packet.py::test_packet_only')\n"
        "else:\n"
        "    print('FAILED tests/test_baseline.py::test_existing_baseline')\n"
        "raise SystemExit(1)\n"
    )

    updated = apply_codex_worktree_changes_to_main(
        packet,
        validation_commands=(
            [sys.executable, "-c", validation_script],
        ),
    )

    assert updated["patch_status"] == "main_apply_baseline_validation_failed_rolled_back"
    assert updated["main_apply_status"] == "failed"
    assert updated["main_apply_validation"]["status"] == "failed"
    assert updated["main_apply_baseline_validation"]["status"] == "failed"
    comparison = updated["main_apply_validation_comparison"]
    assert comparison["packet_only_failure_tokens"] == [
        "pytest:tests/test_packet.py::test_packet_only"
    ]
    assert comparison["baseline_only_failure_tokens"] == [
        "pytest:tests/test_baseline.py::test_existing_baseline"
    ]
    assert (repo / "README.md").read_text(encoding="utf-8") == "test repo\n"

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_apply_to_main_py_compile_preflight_reports_syntax_failure(
    tmp_path,
) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(
        tmp_path,
        tracked_python_module=True,
    )

    worktree_module = Path(packet["worktree_path"]) / "module.py"
    worktree_module.write_text("def broken(:\n    pass\n", encoding="utf-8")
    validation_script = "print('full validation passed')"

    updated = apply_codex_worktree_changes_to_main(
        packet,
        validation_commands=([sys.executable, "-c", validation_script],),
    )

    assert updated["patch_status"] == "main_apply_validation_failed_rolled_back"
    validation = updated["main_apply_validation"]
    assert validation["status"] == "failed"
    assert validation["commands"][0]["command"][:3] == [
        sys.executable,
        "-m",
        "py_compile",
    ]
    assert "module.py" in validation["commands"][0]["command"]
    assert len(validation["commands"]) == 1
    assert any(
        token.startswith("py_compile:") and "module.py" in token
        for token in validation["failure_tokens"]
    )
    report = runner._codex_packet_validation_report(updated)
    assert report["main_apply_validation_failed_command"][:3] == [
        sys.executable,
        "-m",
        "py_compile",
    ]
    assert any(
        token.startswith("py_compile:") and "module.py" in token
        for token in report["main_apply_validation_failure_tokens"]
    )
    assert report["main_apply_validation_syntax_locations"]
    assert (repo / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_apply_validation_hides_cuda_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.delenv("IPFS_DATASETS_CODEX_APPLY_VALIDATION_ALLOW_CUDA", raising=False)

    validation = runner._run_codex_apply_validation(
        tmp_path,
        tmp_path,
        validation_commands=(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "raise SystemExit(0 if os.environ.get('CUDA_VISIBLE_DEVICES') == '' else 1)"
                ),
            ],
        ),
    )

    assert validation["status"] == "passed"


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


def test_codex_work_packet_apply_to_main_union_repairs_stale_patch_conflict(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    todo = ModalTodo(
        todo_id="program-stale-union-repair",
        action="add_or_review_modal_ambiguity_policy",
        objective="repair stale apply conflict",
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
    (repo / "README.md").write_text("main-alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "advance main"], cwd=repo, check=True, capture_output=True, text=True)

    updated = apply_codex_worktree_changes_to_main(
        packet,
        merge_repair_attempts=1,
        merge_repair_mode="apply_3way",
        validation_commands=(),
    )

    merged_text = (repo / "README.md").read_text(encoding="utf-8")
    repair = updated["main_apply_merge_repair"]
    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_repair_status"] == "repaired"
    assert repair["status"] == "repaired"
    assert repair["apply_conflict_resolution_strategy"] == "union"
    assert repair["apply_conflict_resolution"]["status"] == "resolved"
    assert "main-alpha" in merged_text
    assert "codex-alpha" in merged_text
    assert "<<<<<<<" not in merged_text

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_repairs_dirty_target_in_worktree(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    todo = ModalTodo(
        todo_id="program-dirty-repair",
        action="add_or_review_modal_ambiguity_policy",
        objective="repair dirty apply",
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

    updated = apply_codex_worktree_changes_to_main(
        packet,
        merge_repair_attempts=1,
        merge_repair_mode="apply_3way",
        validation_commands=(),
    )

    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_repair_status"] == "repaired"
    assert updated["main_apply_merge_repair"]["mode"] == "dirty_target_worktree_merge"
    assert updated["main_apply_merge_repair"]["status"] == "repaired"
    assert updated["main_apply_dirty_files"] == ["README.md"]
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


def test_codex_work_packet_apply_to_main_union_repairs_dirty_target_conflict(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    todo = ModalTodo(
        todo_id="program-dirty-union-repair",
        action="add_or_review_modal_ambiguity_policy",
        objective="repair dirty conflict",
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
    (repo / "README.md").write_text("source-alpha\nbeta\ngamma\n", encoding="utf-8")

    updated = apply_codex_worktree_changes_to_main(
        packet,
        merge_repair_attempts=1,
        merge_repair_mode="apply_3way",
        validation_commands=(),
    )

    merged_text = (repo / "README.md").read_text(encoding="utf-8")
    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_repair_status"] == "repaired"
    assert updated["main_apply_merge_repair"]["status"] == "repaired"
    assert updated["main_apply_merge_repair"]["conflict_resolution_strategy"] == "union"
    assert updated["main_apply_merge_repair"]["conflict_resolution"]["status"] == "resolved"
    assert "source-alpha" in merged_text
    assert "codex-alpha" in merged_text
    assert "<<<<<<<" not in merged_text

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_marks_no_merged_delta_as_complete(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    todo = ModalTodo(
        todo_id="program-dirty-no-delta",
        action="add_or_review_modal_ambiguity_policy",
        objective="recognize superseded dirty repair",
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
    (repo / "README.md").write_text("codex-alpha\nbeta\ngamma\n", encoding="utf-8")

    updated = apply_codex_worktree_changes_to_main(
        packet,
        merge_repair_attempts=1,
        merge_repair_mode="apply_3way",
        validation_commands=(),
    )

    assert updated["patch_status"] == "main_apply_no_merged_delta"
    assert updated["main_apply_status"] == "no_changes"
    assert updated["main_apply_repair_status"] == "no_merged_delta"
    assert updated["patch_error"] is None
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "codex-alpha\nbeta\ngamma\n"
    )

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_apply_to_main_union_repairs_dirty_and_stale_conflict(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    todo = ModalTodo(
        todo_id="program-dirty-stale-union-repair",
        action="add_or_review_modal_ambiguity_policy",
        objective="repair dirty stale conflict",
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
    (repo / "README.md").write_text("main-alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "advance main"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("source-alpha\nbeta\ngamma\n", encoding="utf-8")

    updated = apply_codex_worktree_changes_to_main(
        packet,
        merge_repair_attempts=1,
        merge_repair_mode="apply_3way",
        validation_commands=(),
    )

    merged_text = (repo / "README.md").read_text(encoding="utf-8")
    repair = updated["main_apply_merge_repair"]
    assert updated["patch_status"] == "applied_to_main"
    assert updated["main_apply_status"] == "applied"
    assert updated["main_apply_repair_status"] == "repaired"
    assert repair["status"] == "repaired"
    assert repair["codex_apply_conflict_resolution_strategy"] == "union"
    assert repair["codex_apply_conflict_resolution"]["status"] == "resolved"
    assert "source-alpha" in merged_text
    assert "codex-alpha" in merged_text
    assert "<<<<<<<" not in merged_text

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_executor_writes_prompt_and_refreshes_patch(tmp_path, monkeypatch) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    codex_stub = tmp_path / "codex-stub.py"
    codex_stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv\n"
        "worktree = Path(args[args.index('--cd') + 1])\n"
        "sys.stdin.read()\n"
        "(worktree / 'README.md').write_text("
        "'test repo\\nexecutor changed this packet\\n', encoding='utf-8')\n"
        "print('ok')\n",
        encoding="utf-8",
    )
    codex_stub.chmod(0o755)

    updated = execute_codex_work_packet(
        packet,
        codex_command=str(codex_stub),
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
    codex_stub = tmp_path / "codex-stub.py"
    codex_stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv\n"
        "worktree = Path(args[args.index('--cd') + 1])\n"
        "sys.stdin.read()\n"
        "(worktree / 'README.md').write_text("
        "'test repo\\nexecutor applied this packet\\n', encoding='utf-8')\n"
        "print('ok')\n",
        encoding="utf-8",
    )
    codex_stub.chmod(0o755)

    updated = execute_codex_work_packet(
        packet,
        apply_mode="apply_to_main",
        codex_command=str(codex_stub),
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


def test_codex_work_packet_executor_requeues_when_main_apply_lock_times_out(
    tmp_path,
) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    codex_stub = tmp_path / "codex-stub.py"
    codex_stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv\n"
        "worktree = Path(args[args.index('--cd') + 1])\n"
        "sys.stdin.read()\n"
        "(worktree / 'README.md').write_text("
        "'test repo\\nlock timeout packet\\n', encoding='utf-8')\n"
        "print('ok')\n",
        encoding="utf-8",
    )
    codex_stub.chmod(0o755)

    lock_path = repo / ".git" / "codex-main-apply.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            updated = execute_codex_work_packet(
                packet,
                apply_mode="apply_to_main",
                codex_command=str(codex_stub),
                main_apply_lock_timeout_seconds=0.01,
                timeout_seconds=1.0,
                validation_commands=(),
            )
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

    assert updated["codex_exec"]["status"] == "succeeded"
    assert updated["main_apply_status"] == "lock_timeout"
    assert updated["patch_status"] == "main_apply_lock_timeout"
    assert updated["patch_path"]
    assert runner._codex_packet_should_requeue_transient(updated) is True
    assert (repo / "README.md").read_text(encoding="utf-8") == "test repo\n"

    subprocess.run(
        ["git", "worktree", "remove", packet["worktree_path"], "--force"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_codex_work_packet_executor_retries_with_sandbox_fallback(tmp_path, monkeypatch) -> None:
    repo, packet = _create_git_repo_with_program_synthesis_packet(tmp_path)
    call_log = tmp_path / "codex-calls.log"
    codex_stub = tmp_path / "codex-stub.py"
    codex_stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv\n"
        "sandbox = (\n"
        "    'danger-full-access'\n"
        "    if '--dangerously-bypass-approvals-and-sandbox' in args\n"
        "    else args[args.index('--sandbox') + 1]\n"
        ")\n"
        "worktree = Path(args[args.index('--cd') + 1])\n"
        "last_message = Path(args[args.index('--output-last-message') + 1])\n"
        f"Path({str(call_log)!r}).open('a', encoding='utf-8').write(sandbox + '\\n')\n"
        "sys.stdin.read()\n"
        "if sandbox == 'workspace-write':\n"
        "    last_message.write_text("
        "'Blocked by the execution sandbox before I could inspect or edit the worktree.\\n', "
        "encoding='utf-8')\n"
        "    sys.stderr.write('bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\\n')\n"
        "    raise SystemExit(0)\n"
        "(worktree / 'README.md').write_text("
        "'test repo\\nfallback sandbox changed this packet\\n', encoding='utf-8')\n"
        "last_message.write_text('fallback completed\\n', encoding='utf-8')\n"
        "print('ok')\n",
        encoding="utf-8",
    )
    codex_stub.chmod(0o755)

    updated = execute_codex_work_packet(
        packet,
        codex_command=str(codex_stub),
        sandbox="workspace-write",
        timeout_seconds=1.0,
    )

    codex_calls = call_log.read_text(encoding="utf-8").splitlines()
    assert codex_calls == ["workspace-write", "danger-full-access"]
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


def test_compiler_ir_metric_block_reports_deterministic_codec_losses(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
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
    assert "cross_entropy_entropy_loss" in block
    assert "cross_entropy_excess_loss" in block
    assert "cross_entropy_loss" in block
    assert "cosine_similarity" in block
    assert "reconstruction_loss" in block
    assert "source_copy_loss" in block
    assert "source_copy_reward_hack_penalty" in block
    assert "source_span_copy_ratio" in block
    assert "source_decompiled_text_embedding_cosine_loss" in block
    assert "source_decompiled_text_embedding_cosine_similarity" in block
    assert "source_decompiled_text_token_loss" in block
    assert "source_decompiled_text_token_similarity" in block
    assert "structural_text_reconstruction_loss" in block
    assert "text_reconstruction_loss" in block
    assert "modal_span_coverage" in block
    assert block["source_decompiled_text_embedding_cosine_loss"] == pytest.approx(
        max(0.0, 1.0 - block["source_decompiled_text_embedding_cosine_similarity"])
    )
    assert block["source_decompiled_text_embedding_cosine_similarity"] == pytest.approx(
        block["cosine_similarity"]
    )
    assert block["source_decompiled_text_token_loss"] == pytest.approx(
        block["structural_text_reconstruction_loss"]
    )
    assert block["sample_metric_records"][0]["source_text_preview"]
    assert block["sample_metric_records"][0]["decompiled_text_preview"]
    assert "worst_source_decompiled_text_records" in block


def test_compiler_ir_metric_block_skips_long_metric_samples(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=" ".join(["The agency must provide records promptly."] * 8),
    )

    class ExplodingCodec:
        config = SimpleNamespace(mode="compiler-ir-text-limit")

        def encode(self, *_args, **_kwargs):
            raise AssertionError("text-length skip should avoid codec.encode")

    progress: list[Mapping[str, object]] = []

    block = compiler_ir_metric_block(
        [sample],
        ExplodingCodec(),
        max_sample_metric_records=1,
        max_sample_text_chars=32,
        metric_text_policy="skip",
        progress_callback=progress.append,
    )

    assert block["sample_count"] == 1
    assert block["evaluated_count"] == 0
    assert block["metric_failures"] == 0
    assert block["metric_text_policy"] == "skip"
    assert block["skipped_sample_count"] == 1
    assert block["text_length_skipped_count"] == 1
    assert block["sample_metric_records"][0]["skip_reason"] == "text_length_limit"
    assert "sample_skipped" in [entry["stage"] for entry in progress]


def test_compiler_ir_metric_block_truncates_long_metric_samples(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=" ".join(["The agency must provide records promptly."] * 8),
    )

    class RecordingCodec:
        config = SimpleNamespace(mode="compiler-ir-text-truncate")

        def __init__(self) -> None:
            self.calls: list[Mapping[str, object]] = []

        def encode(
            self,
            text,
            *,
            document_id,
            citation,
            source,
            source_embedding,
            compiler_guidance=None,
        ):
            self.calls.append(
                {
                    "document_id": document_id,
                    "embedding": list(source_embedding),
                    "text": text,
                }
            )
            return SimpleNamespace(
                decoded_modal_text="must provide records",
                frame_candidates=[object()],
                losses={
                    "cosine_similarity": 0.8,
                    "cross_entropy_loss": 0.3,
                    "source_decompiled_text_embedding_cosine_similarity": 0.8,
                },
                metadata={"llm_call_count": 0.0},
                modal_ir=SimpleNamespace(formulas=[object()]),
            )

    codec = RecordingCodec()
    progress: list[Mapping[str, object]] = []

    block = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=1,
        max_sample_text_chars=80,
        progress_callback=progress.append,
    )

    assert block["evaluated_count"] == 1
    assert block["metric_text_policy"] == "truncate"
    assert block["text_length_skipped_count"] == 0
    assert block["text_length_truncated_count"] == 1
    assert len(codec.calls) == 1
    assert len(str(codec.calls[0]["text"])) <= 80
    assert ":metric-prefix:" in str(codec.calls[0]["document_id"])
    assert block["sample_metric_records"][0]["metric_text_truncated"] is True
    assert block["sample_metric_records"][0]["metric_text_length"] <= 80
    assert "sample_text_truncated" in [entry["stage"] for entry in progress]


def test_compiler_ir_metric_block_cache_respects_metric_text_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=" ".join(["The agency must provide records promptly."] * 8),
    )

    class CountingCodec:
        config = SimpleNamespace(mode="compiler-ir-text-policy-cache")

        def __init__(self) -> None:
            self.calls = 0

        def encode(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                decoded_modal_text="must provide records",
                frame_candidates=[object()],
                losses={
                    "cosine_similarity": 0.8,
                    "cross_entropy_loss": 0.3,
                },
                metadata={"llm_call_count": 0.0},
                modal_ir=SimpleNamespace(formulas=[object()]),
            )

    codec = CountingCodec()

    skipped = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_text_chars=32,
        metric_text_policy="skip",
    )
    truncated = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_text_chars=32,
        metric_text_policy="truncate",
    )

    assert skipped["evaluated_count"] == 0
    assert skipped["persistent_cache_hit"] is False
    assert truncated["evaluated_count"] == 1
    assert truncated["persistent_cache_hit"] is False
    assert codec.calls == 1


def test_compiler_ir_metric_block_times_out_slow_metric_samples(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
    if not runner._compiler_ir_metric_sample_timeout_supported(0.05):
        pytest.skip("compiler IR metric sample timeouts need SIGALRM support")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide records promptly.",
    )

    class SlowCodec:
        config = SimpleNamespace(mode="compiler-ir-timeout")

        def encode(self, *_args, **_kwargs):
            time.sleep(1.0)
            raise AssertionError("timeout should interrupt codec.encode")

    progress: list[Mapping[str, object]] = []

    block = compiler_ir_metric_block(
        [sample],
        SlowCodec(),
        max_sample_metric_records=1,
        progress_callback=progress.append,
        sample_timeout_seconds=0.05,
    )

    assert block["sample_count"] == 1
    assert block["evaluated_count"] == 1
    assert block["metric_failures"] == 1
    assert block["sample_timeouts"] == 1
    assert block["skipped_sample_count"] == 1
    assert block["timeout_fallback_count"] == 1
    assert 0.0 <= block["source_decompiled_text_token_loss"] <= 1.0
    assert 0.0 <= block["symbolic_validity_penalty"] < 1.0
    assert block["sample_timeout_supported"] is True
    assert block["sample_metric_records"][0]["skip_reason"] == "sample_timeout"
    assert block["sample_metric_records"][0]["compiler_ir_metric_timeout_fallback"] is True
    assert (
        block["sample_metric_records"][0]["compiler_ir_metric_timeout_fallback_kind"]
        == "surface_modal_approximation"
    )
    assert "sample_timeout" in [entry["stage"] for entry in progress]


def test_compiler_ir_metric_block_caches_sample_timeouts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if not runner._compiler_ir_metric_sample_timeout_supported(0.05):
        pytest.skip("compiler IR metric sample timeouts need SIGALRM support")
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide records promptly.",
    )

    class SlowCodec:
        config = SimpleNamespace(mode="compiler-ir-timeout-cache")

        def __init__(self) -> None:
            self.calls = 0

        def encode(self, *_args, **_kwargs):
            self.calls += 1
            time.sleep(1.0)
            raise AssertionError("timeout should interrupt codec.encode")

    codec = SlowCodec()
    progress: list[Mapping[str, object]] = []

    first = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=1,
        progress_callback=progress.append,
        sample_timeout_seconds=0.05,
    )
    second = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=1,
        progress_callback=progress.append,
        sample_timeout_seconds=0.05,
    )

    assert codec.calls == 1
    assert first["persistent_sample_cache_misses"] == 1
    assert second["persistent_sample_cache_hits"] == 1
    assert second["persistent_sample_cache_misses"] == 0
    assert second["persistent_sample_timeout_cache_hits"] == 1
    assert second["evaluated_count"] == 1
    assert second["sample_timeouts"] == 1
    assert second["timeout_fallback_count"] == 1
    assert second["sample_metric_records"][0]["from_persistent_sample_cache"] is True
    assert "sample_timeout_cache_hit" in [entry["stage"] for entry in progress]


def test_compiler_ir_metric_timeout_cache_respects_timeout_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if not runner._compiler_ir_metric_sample_timeout_supported(0.05):
        pytest.skip("compiler IR metric sample timeouts need SIGALRM support")
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide records promptly.",
    )

    class RecoveringCodec:
        config = SimpleNamespace(mode="compiler-ir-timeout-budget")

        def __init__(self) -> None:
            self.calls = 0

        def encode(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                time.sleep(1.0)
                raise AssertionError("timeout should interrupt the first call")
            return SimpleNamespace(
                decoded_modal_text="must provide records",
                frame_candidates=[object()],
                losses={
                    "cosine_loss": 0.1,
                    "cosine_similarity": 0.9,
                    "cross_entropy_loss": 0.2,
                },
                metadata={"llm_call_count": 0.0},
                modal_ir=SimpleNamespace(formulas=[object()]),
            )

    codec = RecoveringCodec()

    first = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=1,
        sample_timeout_seconds=0.05,
    )
    second = compiler_ir_metric_block(
        [sample],
        codec,
        max_sample_metric_records=1,
        sample_timeout_seconds=1.0,
    )

    assert codec.calls == 2
    assert first["sample_timeouts"] == 1
    assert second["evaluated_count"] == 1
    assert second["sample_timeouts"] == 0
    assert second["persistent_sample_timeout_cache_hits"] == 0
    assert second["cosine_similarity"] == pytest.approx(0.9)


def test_compiler_ir_metric_timeout_cache_ignores_guidance_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if not runner._compiler_ir_metric_sample_timeout_supported(0.05):
        pytest.skip("compiler IR metric sample timeouts need SIGALRM support")
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide records promptly.",
    )

    class ChangingGuidance:
        def __init__(self) -> None:
            self.calls = 0

        def compiler_guidance_for_sample(self, *_args, **_kwargs):
            self.calls += 1
            return {
                "ranked_guidance_features": [
                    {"feature": f"feature-{self.calls}", "weight": 1.0}
                ],
                "synthesis_focus": f"focus-{self.calls}",
            }

    class SlowCodec:
        config = SimpleNamespace(mode="compiler-ir-timeout-guidance-drift")

        def __init__(self) -> None:
            self.calls = 0

        def encode(self, *_args, **_kwargs):
            self.calls += 1
            time.sleep(1.0)
            raise AssertionError("timeout should interrupt codec.encode")

    codec = SlowCodec()
    guidance = ChangingGuidance()

    first = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=guidance,
        use_autoencoder_guidance=True,
        max_sample_metric_records=1,
        sample_timeout_seconds=0.05,
    )
    second = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=guidance,
        use_autoencoder_guidance=True,
        max_sample_metric_records=1,
        sample_timeout_seconds=0.05,
    )

    assert guidance.calls == 2
    assert codec.calls == 1
    assert first["sample_timeouts"] == 1
    assert second["persistent_sample_timeout_cache_hits"] == 1
    assert second["sample_metric_records"][0]["persistent_cache_kind"] == (
        "compiler_ir_metric_sample_timeout"
    )


def test_compiler_ir_metric_block_uses_persistent_metric_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_dir = tmp_path / "metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
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
    original_encode = codec.encode
    calls = {"count": 0}

    def counted_encode(*args, **kwargs):
        calls["count"] += 1
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(codec, "encode", counted_encode)

    first = compiler_ir_metric_block([sample], codec)
    second = compiler_ir_metric_block([sample], codec)

    assert calls["count"] == 1
    assert first["persistent_cache_hit"] is False
    assert second["persistent_cache_hit"] is True
    assert second["persistent_cache_kind"] == "compiler_ir_metric_block"
    assert second["sample_cache_not_consulted_due_block_hit"] is True
    assert first["cross_entropy_loss"] == second["cross_entropy_loss"]


def test_compiler_ir_metric_block_cache_reuses_success_across_timeout_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_dir = tmp_path / "metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
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
    original_encode = codec.encode
    calls = {"count": 0}

    def counted_encode(*args, **kwargs):
        calls["count"] += 1
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(codec, "encode", counted_encode)

    first = compiler_ir_metric_block([sample], codec, sample_timeout_seconds=0.0)
    second = compiler_ir_metric_block([sample], codec, sample_timeout_seconds=30.0)

    assert calls["count"] == 1
    assert first["persistent_cache_hit"] is False
    assert second["persistent_cache_hit"] is True
    assert second["sample_timeout_seconds"] == pytest.approx(30.0)
    assert second["sample_timeout_cache_policy"] == (
        runner._COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY
    )
    assert second["persistent_sample_cache_misses"] == 0
    assert first["cross_entropy_loss"] == second["cross_entropy_loss"]


def test_compiler_ir_metric_block_uses_guided_persistent_metric_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_dir = tmp_path / "metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
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
    autoencoder = AdaptiveModalAutoencoder()
    autoencoder.evaluate([sample], legal_ir_bridge_names=["modal.frame_logic"])
    original_encode = codec.encode
    original_guidance = autoencoder.compiler_guidance_for_sample
    calls = {"encode": 0, "guidance": 0}

    def counted_encode(*args, **kwargs):
        calls["encode"] += 1
        return original_encode(*args, **kwargs)

    def counted_guidance(*args, **kwargs):
        calls["guidance"] += 1
        return original_guidance(*args, **kwargs)

    monkeypatch.setattr(codec, "encode", counted_encode)
    monkeypatch.setattr(autoencoder, "compiler_guidance_for_sample", counted_guidance)

    first = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
    )
    second = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
    )

    assert calls["guidance"] == 2
    assert calls["encode"] == 1
    assert first["persistent_cache_hit"] is False
    assert second["persistent_cache_hit"] is True
    assert second["persistent_cache_kind"] == "compiler_ir_metric_block"
    assert second["sample_cache_not_consulted_due_block_hit"] is True
    assert second["autoencoder_guidance_enabled"] is True
    assert first["cross_entropy_loss"] == second["cross_entropy_loss"]


def test_compiler_ir_metric_guided_cache_ignores_decoded_embedding_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_dir = tmp_path / "metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide records unless an exemption applies.",
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )
    autoencoder = AdaptiveModalAutoencoder()
    original_encode = codec.encode
    calls = {"encode": 0, "guidance": 0}

    def counted_encode(*args, **kwargs):
        calls["encode"] += 1
        return original_encode(*args, **kwargs)

    def drifting_guidance(sample_arg, **_kwargs):
        calls["guidance"] += 1
        return {
            "decoded_embedding": [float(calls["guidance"]), 0.25, 0.5],
            "family_distribution": {"obligation": 1.0},
            "feature_groups": {
                "decompiler_surface_template": [
                    "decompiler-surface:force-lexeme:lexeme:shall",
                ],
            },
            "ranked_guidance_features": [
                {
                    "embedding_weight_norm": 0.1,
                    "family_logit_magnitude": 0.2,
                    "feature": "decompiler-surface:force-lexeme:lexeme:shall",
                    "legal_ir_view_logit_magnitude": 0.3,
                    "score": 0.4,
                },
            ],
            "sample_id": sample_arg.sample_id,
            "sample_memory_used": False,
            "top_embedding_contributions": [
                {"feature": f"volatile-{calls['guidance']}", "score": 1.0},
            ],
        }

    monkeypatch.setattr(codec, "encode", counted_encode)
    monkeypatch.setattr(autoencoder, "compiler_guidance_for_sample", drifting_guidance)

    first = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
    )
    second = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
    )

    assert calls["guidance"] == 2
    assert calls["encode"] == 1
    assert first["persistent_cache_hit"] is False
    assert second["persistent_cache_hit"] is True
    assert second["sample_cache_not_consulted_due_block_hit"] is True
    assert (
        second["compiler_ir_guidance_cache_policy"]
        == runner._COMPILER_IR_GUIDANCE_CACHE_POLICY
    )
    assert first["cross_entropy_loss"] == second["cross_entropy_loss"]


def test_compiler_ir_metric_sample_cache_preserves_guidance_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_dir = tmp_path / "metric-cache"
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(cache_dir))
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "1")
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
    autoencoder = AdaptiveModalAutoencoder()
    autoencoder.evaluate([sample], legal_ir_bridge_names=["modal.frame_logic"])

    first = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
        max_sample_metric_records=32,
    )
    second = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
        max_sample_metric_records=31,
    )

    assert first["persistent_sample_cache_misses"] == 1
    assert second["persistent_cache_hit"] is False
    assert second["persistent_sample_cache_hits"] == 1
    assert second["compiler_guidance_feature_groups"]
    assert second["compiler_guidance_surface_features"]


def test_compiler_ir_metric_block_reports_progress_callbacks(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
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
    progress: list[Mapping[str, object]] = []

    block = compiler_ir_metric_block(
        [sample],
        codec,
        progress_callback=progress.append,
    )

    assert block["evaluated_count"] == 1
    stages = [entry["stage"] for entry in progress]
    assert stages[0] == "start"
    assert "sample_start" in stages
    assert "sample_done" in stages
    assert stages[-1] == "done"
    assert progress[-1]["evaluated_count"] == 1


def test_compiler_ir_metric_block_can_apply_autoencoder_guidance() -> None:
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
    autoencoder = AdaptiveModalAutoencoder()
    autoencoder.evaluate([sample], legal_ir_bridge_names=["modal.frame_logic"])

    block = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=autoencoder,
        use_autoencoder_guidance=True,
    )

    assert block["autoencoder_guidance_enabled"] is True
    assert block["autoencoder_guidance_applied_count"] == 1
    assert block["autoencoder_guidance_empty_count"] == 0
    assert block["autoencoder_guidance_failures"] == 0
    assert block["autoencoder_guidance_produced_count"] == 1
    assert block["autoencoder_guidance_requested_count"] == 1
    assert block["autoencoder_guidance_unapplied_count"] == 0
    assert block["evaluated_count"] == 1
    assert block["compiler_guidance_feature_groups"]
    assert block["compiler_guidance_surface_features"]
    assert "guidance_family_cross_entropy_excess_loss" in block


def test_compiler_ir_metric_block_reports_guidance_overlay_terms() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may not provide records except when authorized.",
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )

    class SurfaceGuidance:
        def compiler_guidance_for_sample(self, sample, **_kwargs):
            return {
                "feature_groups": {
                    "decompiler_surface_template": [
                        "decompiler-surface:force-lexeme:permission:may",
                        "decompiler-surface:scope-realizer:exception-suffix",
                    ],
                },
                "family_distribution": {"deontic": 1.0},
                "legal_ir_predicted_view_distribution": {"modal.frame_logic": 1.0},
                "legal_ir_target_view_distribution": {"deontic.norms": 1.0},
            }

    block = compiler_ir_metric_block(
        [sample],
        codec,
        autoencoder=SurfaceGuidance(),
        use_autoencoder_guidance=True,
    )

    assert block["autoencoder_guidance_applied_count"] == 1
    assert block["compiler_guidance_semantic_overlay_count"] == 2.0
    assert block["compiler_guidance_semantic_overlay_terms"] == {
        "except": 1,
        "may": 1,
    }
    assert block["compiler_guidance_legal_ir_view_gaps"] == {
        "deontic_norms:underrepresented": 1,
        "modal_frame_logic:overrepresented": 1,
    }


def test_compiler_guidance_diagnostics_do_not_pad_structural_decode_metrics() -> None:
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
    plain = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )
    guided = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance={
            "family_distribution": {"deontic": 1.0},
            "feature_groups": {
                "decompiler_surface_template": [
                    "decompiler-surface:diagnostic-only-token"
                ],
            },
            "legal_ir_predicted_view_distribution": {"modal.frame_logic": 1.0},
            "legal_ir_target_view_distribution": {"modal.frame_logic": 1.0},
            "synthesis_focus": ["repair_deontic_bridge_quality_gate"],
        },
    )

    guided_slots = decoded_modal_phrase_slot_text_map(guided.decoded_modal_text)

    assert guided.metadata["compiler_guidance_applied"] is True
    assert any(
        "diagnostic-only-token" in value
        for value in guided_slots[
            "compiler_guidance_decompiler_surface_template_feature"
        ]
    )
    assert "diagnostic-only-token" not in guided.metadata[
        "modal_decompiler_structural_text"
    ]
    assert "repair_deontic_bridge_quality_gate" not in guided.metadata[
        "modal_decompiler_structural_text"
    ]
    assert guided.losses["source_copy_loss"] == pytest.approx(
        plain.losses["source_copy_loss"]
    )


def test_compiler_guidance_surface_terms_activate_structural_decode() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may not provide records except when authorized.",
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )
    plain = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
    )
    guided = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance={
            "feature_groups": {
                "decompiler_surface_template": [
                    "decompiler-surface:force-lexeme:permission:may",
                    "decompiler-surface:scope-realizer:exception-suffix",
                    "decompiler-surface:negation-placement:pre-action",
                    "decompiler-surface:diagnostic-only-token",
                ],
            },
            "family_distribution": {"deontic": 1.0},
            "legal_ir_predicted_view_distribution": {"modal.frame_logic": 1.0},
            "legal_ir_target_view_distribution": {"modal.frame_logic": 1.0},
        },
    )

    overlay_terms = guided.metadata["compiler_guidance_semantic_overlay_terms"]

    assert overlay_terms == ["may", "except", "not"]
    assert "diagnostic-only-token" not in overlay_terms
    structural_text = guided.metadata["modal_decompiler_structural_text"]
    assert "may" in structural_text
    assert "except" in structural_text
    assert "not" in structural_text


def test_compiler_guidance_cue_terms_and_views_reach_deterministic_ir() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "If authorized, the agency may provide records and shall withhold "
            "records except protected records."
        ),
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )

    guided = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance={
            "feature_groups": {
                "decompiler_surface_template": [
                    "decompiler-surface:cue-surface-ir:authority:frame:frame:unscoped",
                    "decompiler-surface:cue-surface-ir:permission:deontic:frame:unscoped",
                    "decompiler-surface:cue-surface-ir:obligation:deontic:frame:unscoped",
                    "decompiler-surface:cue-surface-ir:condition:modal:frame:conditioned",
                    "decompiler-surface:cue-surface-ir:exception:modal:frame:excepted",
                ],
            },
            "family_distribution": {"deontic": 1.0},
            "legal_ir_predicted_view_distribution": {
                "deontic.norms": 0.2,
                "modal.frame_logic": 0.8,
            },
            "legal_ir_target_view_distribution": {
                "deontic.norms": 0.7,
                "modal.frame_logic": 0.3,
            },
        },
    )
    triples = modal_ir_to_flogic_triples(guided.modal_ir)
    triples_by_predicate = {}
    for triple in triples:
        triples_by_predicate.setdefault(triple["predicate"], set()).add(
            triple["object"]
        )

    assert guided.metadata["compiler_guidance_semantic_overlay_terms"] == [
        "authority",
        "may",
        "shall",
        "if",
        "except",
    ]
    assert guided.metadata["compiler_guidance_legal_ir_view_gap_distribution"] == {
        "deontic.norms": pytest.approx(0.5),
        "modal.frame_logic": pytest.approx(-0.5),
    }
    assert {
        "deontic.norms",
        "modal.frame_logic",
    } <= triples_by_predicate["learned_legal_ir_predicted_view"]
    assert {
        "deontic.norms",
        "modal.frame_logic",
    } <= triples_by_predicate["learned_legal_ir_target_view"]
    assert any(
        value.startswith("deontic.norms:")
        for value in triples_by_predicate["learned_legal_ir_view_gap"]
    )
    slot_texts = decoded_modal_phrase_slot_text_map(guided.decoded_modal_text)
    assert "deontic_norms" in slot_texts["compiler_guidance_legal_ir_view_gap"]
    assert (
        "deontic_norms:underrepresented"
        in slot_texts["compiler_guidance_legal_ir_view_gap_direction"]
    )


def test_compiler_guidance_promotes_exception_and_prohibition_to_typed_ir() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The agency may not disclose protected records except as authorized "
            "by subsection (b)."
        ),
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )

    guided = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance={
            "feature_groups": {
                "decompiler_surface_template": [
                    "decompiler-surface:cue-surface-ir:prohibition:deontic:frame:excepted",
                    "decompiler-surface:cue-surface-ir:exception:modal:frame:excepted",
                ],
            },
            "family_distribution": {"deontic": 1.0},
        },
    )
    triples = modal_ir_to_flogic_triples(guided.modal_ir)
    triples_by_predicate = {}
    for triple in triples:
        triples_by_predicate.setdefault(triple["predicate"], set()).add(
            triple["object"]
        )

    typed_semantics = guided.modal_ir.metadata["compiler_guidance_typed_semantics"]
    assert guided.metadata["compiler_guidance_semantic_overlay_terms"] == [
        "not",
        "except",
    ]
    assert typed_semantics["exception_formula_count"] >= 1
    assert typed_semantics["prohibition_formula_count"] >= 1
    assert any(formula.exceptions for formula in guided.modal_ir.formulas)
    assert any(
        formula.metadata.get("compiler_guidance_typed_prohibition") is True
        for formula in guided.modal_ir.formulas
    )
    assert {"exception", "prohibition"} <= triples_by_predicate[
        "compiler_guidance_typed_semantic"
    ]
    assert "negative" in triples_by_predicate["compiler_guidance_force_polarity"]
    assert "prohibition" in triples_by_predicate["compiler_guidance_deontic_force"]
    assert any(
        value.lower().startswith("except")
        for value in triples_by_predicate["exception"]
    )


def test_compiler_guidance_overlay_drops_redundant_negation_marker() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency may not disclose protected records.",
    )
    codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )

    guided = codec.encode(
        sample.text,
        document_id=sample.sample_id,
        citation=sample.citation,
        source=sample.source,
        source_embedding=sample.embedding_vector,
        compiler_guidance={
            "feature_groups": {
                "decompiler_surface_template": [
                    "decompiler-surface:force-lexeme:obligation:prohibited",
                    "decompiler-surface:negation-placement:pre-action",
                    "decompiler-surface:scope-realizer:condition-prefix",
                ],
            },
            "family_distribution": {"deontic": 1.0},
        },
    )

    overlay_terms = guided.metadata["compiler_guidance_semantic_overlay_terms"]

    assert overlay_terms == ["prohibited"]
    assert "not" not in overlay_terms


def test_compiler_guidance_canary_block_reports_quality_gate() -> None:
    deterministic = {
        "cosine_similarity": 0.2,
        "cross_entropy_excess_loss": 0.4,
        "cross_entropy_loss": 1.4,
        "sample_metric_records": [
            {
                "metrics": {
                    "cosine_similarity": 0.2,
                    "cross_entropy_excess_loss": 0.4,
                    "cross_entropy_loss": 1.4,
                    "source_copy_loss": 0.5,
                    "source_copy_reward_hack_penalty": 0.3,
                },
                "sample_id": "sample-guidance",
            }
        ],
        "source_copy_loss": 0.5,
        "source_copy_reward_hack_penalty": 0.3,
    }
    guided = {
        "autoencoder_guidance_applied_count": 1,
        "autoencoder_guidance_enabled": True,
        "compiler_guidance_frame_boost_count": 2.0,
        "compiler_guidance_frame_changed_count": 1,
        "sample_metric_records": [
            {
                "compiler_guidance_applied": True,
                "compiler_guidance_legal_ir_view_gaps": [
                    "deontic_norms:underrepresented"
                ],
                "compiler_guidance_semantic_overlay_terms": ["shall"],
                "compiler_guidance_todo_routes": [
                    "refine_semantic_decompiler_reconstruction"
                ],
                "metrics": {
                    "cosine_similarity": 0.25,
                    "cross_entropy_excess_loss": 0.35,
                    "cross_entropy_loss": 1.2,
                    "source_copy_loss": 0.45,
                    "source_copy_reward_hack_penalty": 0.1,
                },
                "sample_id": "sample-guidance",
            }
        ],
        "cosine_similarity": 0.25,
        "cross_entropy_excess_loss": 0.35,
        "cross_entropy_loss": 1.2,
        "source_copy_loss": 0.45,
        "source_copy_reward_hack_penalty": 0.1,
    }

    block = compiler_guidance_canary_block(
        deterministic,
        guided,
        plateau_threshold=1.0e-5,
    )

    assert block["quality_gate"] == "pass"
    assert block["improved"] is True
    assert block["regressed"] is False
    assert block["ce_delta"] == pytest.approx(0.2)
    assert block["cosine_delta"] == pytest.approx(0.05)
    assert block["copy_hack_delta"] == pytest.approx(0.2)
    assert block["frame_boost_count"] == pytest.approx(2.0)
    assert block["frame_changed_count"] == 1
    assert block["attribution"]["basis"] == "sample_records"
    assert block["attribution"]["matched_sample_count"] == 1
    assert block["attribution"]["semantic_overlay_terms"]["shall"][
        "quality_gate"
    ] == "pass"
    assert block["attribution"]["semantic_overlay_terms"]["shall"][
        "ce_delta"
    ] == pytest.approx(0.2)
    assert block["attribution"]["legal_ir_view_gaps"][
        "deontic_norms:underrepresented"
    ]["quality_gate"] == "pass"
    assert block["attribution"]["legal_ir_view_gaps"][
        "deontic_norms:underrepresented"
    ]["copy_hack_delta"] == pytest.approx(0.2)
    assert block["attribution"]["todo_routes"][
        "refine_semantic_decompiler_reconstruction"
    ]["cosine_delta"] == pytest.approx(0.05)

    regressed = compiler_guidance_canary_block(
        deterministic,
        {
            **guided,
            "cosine_similarity": 0.1,
            "cross_entropy_loss": 1.6,
            "source_copy_reward_hack_penalty": 0.4,
        },
        plateau_threshold=1.0e-5,
    )

    assert regressed["quality_gate"] == "fail"
    assert regressed["regressed"] is True


def test_compiler_guidance_promotion_gate_blocks_failed_canary() -> None:
    passed = compiler_guidance_promotion_gate(
        {"applied_count": 3, "quality_gate": "pass"}
    )
    failed = compiler_guidance_promotion_gate(
        {"applied_count": 3, "quality_gate": "fail"}
    )
    inactive = compiler_guidance_promotion_gate(
        {"applied_count": 0, "quality_gate": "inactive"}
    )

    assert passed["promotion_allowed"] is True
    assert passed["recommended_mode"] == "promote_deterministic_rules"
    assert failed["promotion_allowed"] is False
    assert failed["promotion_block_reason"] == "quality_gate_fail"
    assert inactive["promotion_allowed"] is False
    assert inactive["promotion_block_reason"] == "insufficient_guidance_samples"


def test_compiler_guidance_scope_hints_route_learned_todos_to_codex_scopes() -> None:
    hints = compiler_guidance_scope_hints(
        {
            "compiler_guidance_todo_routes": {
                "repair_deontic_bridge_quality_gate": 3,
                "refine_semantic_decompiler_reconstruction": 2,
                "repair_tdfol_bridge_parse": 1,
            }
        }
    )

    assert hints["scope_counts"] == {
        "deontic": 3,
        "ir_decompiler": 2,
        "tdfol": 1,
    }
    assert hints["recommended_parallel_scopes"] == [
        "deontic",
        "ir_decompiler",
        "tdfol",
    ]
    assert hints["route_scope_map"]["repair_deontic_bridge_quality_gate"][
        "target_component"
    ] == "deontic.ir"


def test_compiler_guidance_signed_view_gaps_route_to_codex_scopes() -> None:
    guided_block = {
        "compiler_guidance_legal_ir_view_gaps": {
            "deontic_norms:underrepresented": 3,
            "modal_frame_logic:overrepresented": 2,
            "TDFOL_prover:underrepresented": 1,
        }
    }

    hints = compiler_guidance_scope_hints(guided_block)
    candidates = compiler_guidance_distillation_candidates(
        guided_block,
        {"applied_count": 3, "quality_gate": "pass"},
    )

    assert hints["scope_counts"] == {
        "deontic": 3,
        "frame_logic": 2,
        "tdfol": 1,
    }
    assert candidates["top_legal_ir_view_gaps"] == {
        "deontic_norms:underrepresented": 3,
        "modal_frame_logic:overrepresented": 2,
        "TDFOL_prover:underrepresented": 1,
    }
    assert candidates["todo_routes_inferred_from_features"] is True
    assert candidates["top_todo_routes"] == {
        "repair_deontic_bridge_quality_gate": 3,
        "repair_flogic_ontology_constraints": 2,
        "repair_tdfol_bridge_parse": 1,
    }

    todos = compiler_guidance_distillation_todos(candidates)

    assert [todo.action for todo in todos[:3]] == [
        "repair_deontic_bridge_quality_gate",
        "repair_flogic_ontology_constraints",
        "repair_tdfol_bridge_parse",
    ]
    assert todos[0].metadata["compiler_guidance_legal_ir_view_gaps"] == {
        "deontic_norms:underrepresented": 3,
        "modal_frame_logic:overrepresented": 2,
        "TDFOL_prover:underrepresented": 1,
    }
    assert todos[0].metadata["program_synthesis_scope"] == "deontic"


def test_compiler_guidance_distillation_candidates_include_promotion_and_routes() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_feature_groups": {"decompiler_plan": 2},
            "compiler_guidance_surface_features": {"must_provide_notice": 2},
            "compiler_guidance_todo_routes": {
                "refine_semantic_decompiler_reconstruction": 2
            },
            "compiler_guidance_todo_route_examples": {
                "refine_semantic_decompiler_reconstruction": [
                    {
                        "citation": "5 U.S.C. 552",
                        "sample_id": "sample-552",
                        "text_preview": "The agency must provide notice.",
                    }
                ]
            },
        },
        {"applied_count": 2, "quality_gate": "pass"},
    )

    assert candidates["has_candidates"] is True
    assert candidates["promotion_allowed"] is True
    assert candidates["recommended_mode"] == "promote_deterministic_rules"
    assert candidates["top_feature_groups"] == {"decompiler_plan": 2}
    assert candidates["top_todo_routes"] == {
        "refine_semantic_decompiler_reconstruction": 2
    }
    assert candidates["top_todo_route_examples"][
        "refine_semantic_decompiler_reconstruction"
    ][0]["sample_id"] == "sample-552"
    assert candidates["scope_hints"]["scope_counts"] == {"ir_decompiler": 2}


def test_compiler_guidance_distillation_candidates_augment_surface_route() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_semantic_overlay_terms": {"except": 1},
            "compiler_guidance_surface_features": {
                "decompiler-surface:force-lexeme:obligation:prohibited": 2,
            },
            "compiler_guidance_todo_routes": {
                "repair_multiview_legal_ir_graph_projection": 1,
            },
        },
        {
            "applied_count": 1,
            "attribution": {
                "basis": "sample_records",
                "matched_sample_count": 1,
                "semantic_overlay_terms": {
                    "except": {
                        "ce_delta": 0.0,
                        "copy_hack_delta": 0.0,
                        "cosine_delta": 0.0,
                        "count": 1,
                        "quality_gate": "warn",
                    }
                },
            },
            "quality_gate": "warn",
        },
    )

    assert candidates["todo_routes_inferred_from_features"] is False
    assert candidates["todo_routes_augmented_from_features"] is True
    assert candidates["guidance_attribution"]["basis"] == "sample_records"
    assert candidates["guidance_attribution_summary"] == {
        "basis": "sample_records",
        "matched_sample_count": 1,
        "warn_semantic_overlay_terms": ["except"],
    }
    assert candidates["top_semantic_overlay_terms"] == {"except": 1}
    assert candidates["top_todo_routes"] == {
        "refine_semantic_decompiler_reconstruction": 2,
        "repair_multiview_legal_ir_graph_projection": 1,
    }
    assert candidates["scope_hints"]["scope_counts"] == {
        "ir_decompiler": 2,
        "knowledge_graphs": 1,
    }

    todos = compiler_guidance_activation_todos(
        candidates,
        {
            "applied_count": 1,
            "ce_delta": 0.0,
            "copy_hack_delta": 0.0,
            "cosine_delta": 0.0,
            "quality_gate": "warn",
        },
    )

    assert todos[0].action == "refine_semantic_decompiler_reconstruction"
    assert todos[0].metadata["program_synthesis_scope"] == "ir_decompiler"
    assert todos[0].metadata["compiler_guidance_semantic_overlay_terms"] == {
        "except": 1,
    }
    assert todos[0].metadata["compiler_guidance_attribution"]["basis"] == (
        "sample_records"
    )
    assert todos[0].metadata["compiler_guidance_attribution_summary"][
        "warn_semantic_overlay_terms"
    ] == ["except"]
    assert (
        todos[0].metadata["compiler_guidance_todo_routes_augmented_from_features"]
        is True
    )


def test_compiler_guidance_distillation_todos_convert_passing_routes() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_todo_routes": {
                "refine_semantic_decompiler_reconstruction": 2
            },
            "compiler_guidance_todo_route_examples": {
                "refine_semantic_decompiler_reconstruction": [
                    {
                        "citation": "5 U.S.C. 552",
                        "sample_id": "sample-552",
                        "selected_frame_after": "administrative_notice_hearing",
                        "selected_frame_before": "generic_frame",
                        "text_preview": "The agency must provide notice.",
                    }
                ]
            },
        },
        {"applied_count": 2, "quality_gate": "pass"},
    )

    todos = compiler_guidance_distillation_todos(candidates)

    assert len(todos) == 1
    todo = todos[0]
    assert todo.action == "refine_semantic_decompiler_reconstruction"
    assert todo.sample_ids == ["sample-552"]
    assert todo.citations == ["5 U.S.C. 552"]
    assert todo.metadata["optimizer_role"] == "program_synthesis"
    assert todo.metadata["program_synthesis_scope"] == "ir_decompiler"
    assert todo.metadata["target_component"] == "modal.ir_decompiler"
    assert todo.metadata["source"] == "compiler_guidance_distillation_v1"
    assert "source_copy_reward_hack_penalty" in todo.metadata["target_metrics"]
    assert todo.metadata["metric_sample_payloads"][0]["text"] == (
        "The agency must provide notice."
    )


def test_compiler_guidance_distillation_todos_infer_surface_route() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_feature_groups": {
                "decompiler_surface_template": 1,
                "logic_view_contract": 1,
            },
            "compiler_guidance_surface_features": {
                "decompiler-surface:force-lexeme:permission:may": 1,
                "decompiler-surface:scope-realizer:exception-suffix": 1,
            },
        },
        {"applied_count": 1, "quality_gate": "pass"},
    )

    todos = compiler_guidance_distillation_todos(candidates)

    assert candidates["todo_routes_inferred_from_features"] is True
    assert candidates["top_todo_routes"] == {
        "refine_semantic_decompiler_reconstruction": 2
    }
    assert candidates["scope_hints"]["scope_counts"] == {"ir_decompiler": 2}
    assert len(todos) == 1
    todo = todos[0]
    assert todo.action == "refine_semantic_decompiler_reconstruction"
    assert todo.sample_ids == [
        "compiler-guidance:refine_semantic_decompiler_reconstruction"
    ]
    assert todo.metadata["program_synthesis_scope"] == "ir_decompiler"
    assert todo.metadata["compiler_guidance_todo_routes_inferred_from_features"] is True
    assert todo.metadata["compiler_guidance_surface_features"] == {
        "decompiler-surface:force-lexeme:permission:may": 1,
        "decompiler-surface:scope-realizer:exception-suffix": 1,
    }


def test_compiler_guidance_distillation_todos_skip_blocked_candidates() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_todo_routes": {
                "refine_semantic_decompiler_reconstruction": 2
            },
        },
        {"applied_count": 2, "quality_gate": "fail"},
    )

    assert compiler_guidance_distillation_todos(candidates) == []


def test_compiler_guidance_activation_todos_convert_warn_routes() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_todo_routes": {
                "repair_multiview_legal_ir_graph_projection": 1
            },
            "compiler_guidance_todo_route_examples": {
                "repair_multiview_legal_ir_graph_projection": [
                    {
                        "citation": "25 U.S.C. 605",
                        "sample_id": "sample-605",
                        "selected_frame_after": "administrative_notice_hearing",
                        "selected_frame_before": "administrative_notice_hearing",
                        "text_preview": "The agency shall publish notice.",
                    }
                ]
            },
        },
        {"applied_count": 1, "quality_gate": "warn"},
    )

    todos = compiler_guidance_activation_todos(
        candidates,
        {
            "applied_count": 1,
            "ce_delta": 0.0,
            "copy_hack_delta": 0.0,
            "cosine_delta": 0.0,
            "quality_gate": "warn",
        },
    )

    assert len(todos) == 1
    todo = todos[0]
    assert todo.action == "repair_multiview_legal_ir_graph_projection"
    assert todo.sample_ids == ["sample-605"]
    assert todo.metadata["source"] == "compiler_guidance_activation_v1"
    assert todo.metadata["program_synthesis_scope"] == "knowledge_graphs"
    assert todo.metadata["target_component"] == "knowledge_graphs.neo4j_compat"
    assert todo.metadata["compiler_guidance_activation_reason"] == (
        "guidance_applied_without_metric_movement"
    )
    assert "legal_ir_view_cross_entropy_loss" in todo.metadata["target_metrics"]

    assert (
        compiler_guidance_activation_todos(
            candidates,
            {"applied_count": 1, "quality_gate": "pass"},
        )
        == []
    )


def test_compiler_guidance_guardrail_todos_convert_copy_hack_regression() -> None:
    candidates = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_todo_routes": {
                "repair_deontic_bridge_quality_gate": 1,
                "repair_multiview_legal_ir_graph_projection": 1,
            },
            "compiler_guidance_todo_route_examples": {
                "repair_deontic_bridge_quality_gate": [
                    {
                        "citation": "33 U.S.C. 3609",
                        "sample_id": "sample-3609",
                        "selected_frame_after": "administrative_notice_hearing",
                        "selected_frame_before": "administrative_notice_hearing",
                        "text_preview": "Congress finds that agencies shall publish notice.",
                    }
                ]
            },
        },
        {"applied_count": 1, "quality_gate": "fail"},
    )

    todos = compiler_guidance_guardrail_todos(
        candidates,
        {
            "applied_count": 1,
            "ce_delta": 0.0,
            "copy_hack_delta": -0.02,
            "cosine_delta": 0.12,
            "quality_gate": "fail",
        },
    )

    assert len(todos) == 1
    todo = todos[0]
    assert todo.action == "refine_semantic_decompiler_reconstruction"
    assert todo.sample_ids == ["sample-3609"]
    assert todo.metadata["source"] == "compiler_guidance_guardrail_v1"
    assert todo.metadata["program_synthesis_scope"] == "ir_decompiler"
    assert todo.metadata["target_component"] == "modal.ir_decompiler"
    assert todo.metadata["compiler_guidance_guardrail_reason"] == (
        "copy_hack_regression_with_useful_guidance"
    )
    assert "source_copy_reward_hack_penalty" in todo.metadata["target_metrics"]

    assert (
        compiler_guidance_guardrail_todos(
            candidates,
            {
                "applied_count": 1,
                "ce_delta": 0.0,
                "copy_hack_delta": -0.02,
                "cosine_delta": -0.01,
                "quality_gate": "fail",
            },
        )
        == []
    )

    cosine_guardrail = compiler_guidance_guardrail_todos(
        candidates,
        {
            "applied_count": 1,
            "ce_delta": 0.0,
            "copy_hack_delta": 0.01,
            "cosine_delta": -0.12,
            "quality_gate": "fail",
        },
    )

    assert len(cosine_guardrail) == 1
    assert cosine_guardrail[0].action == "refine_typed_ir_or_decompiler_slots"
    assert cosine_guardrail[0].metadata["compiler_guidance_guardrail_reason"] == (
        "cosine_regression_with_useful_guidance"
    )
    assert "cosine_similarity" in cosine_guardrail[0].metadata["target_metrics"]


def test_bridge_ir_metric_block_reports_per_adapter_views(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    block = bridge_ir_metric_block([sample], ["deontic_norms", "fol_tdfol"])

    assert block["sample_count"] == 1
    assert block["adapter_count"] == 2
    assert block["cache_hits"] >= 0
    assert block["cache_misses"] >= 0
    assert block["evaluation_seconds_max"] >= 0.0
    assert block["evaluated_count"] == 2
    assert block["metric_failures"] == 0
    assert "acceptance_rate" in block
    assert "total_loss" in block
    assert block["total_loss"] >= 0.0
    assert block["canonical_ir"]["view_count"] >= 8
    assert block["canonical_ir"]["total_loss"] >= 0.0
    assert block["canonical_ir"]["view_coverage_loss"] == 0.0
    assert block["canonical_ir"]["losses"]["legal_ir_multiview_total_loss"] >= 0.0
    assert block["canonical_ir"]["view_distribution"]
    assert block["worker_count"] == 1

    deontic = block["adapters"]["deontic_norms"]
    assert deontic["views"]["deontic_ir"]["metadata"]["norm_count"] >= 1
    assert deontic["views"]["deontic_decoder_reconstructions"]["metadata"][
        "decoder_record_count"
    ] >= 1
    assert deontic["views"]["deontic_ir_slot_provenance"]["metadata"][
        "provenance_record_count"
    ] >= 1
    assert deontic["views"]["deontic_graph"]["metadata"]["rule_count"] >= 1
    assert deontic["views"]["frame_logic"]["metadata"]["triple_count"] >= 1
    assert "deontic_decoder_slot_loss" in deontic
    assert "deontic_ir_slot_provenance_loss" in deontic
    assert "deontic_quality_requires_validation_loss" in deontic

    tdfol = block["adapters"]["fol_tdfol"]
    assert tdfol["views"]["tdfol_formula"]["metadata"]["formula_count"] >= 1
    assert tdfol["views"]["proof_obligations"]["metadata"]["obligation_count"] >= 1
    assert "tdfol_parse_failure_ratio" in tdfol


def test_bridge_ir_metric_block_reports_progress_callbacks(monkeypatch) -> None:
    monkeypatch.setenv(runner.LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV, "0")
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    progress: list[Mapping[str, object]] = []

    block = bridge_ir_metric_block(
        [sample],
        ["deontic_norms"],
        evaluate_provers=False,
        progress_callback=progress.append,
    )

    assert block["sample_count"] == 1
    assert block["worker_count"] == 1
    stages = [entry["stage"] for entry in progress]
    assert stages[0] == "start"
    assert "sample_start" in stages
    assert any(stage in stages for stage in ("sample_cache_hit", "sample_done"))
    assert stages[-1] == "done"


def test_metric_block_includes_autoencoder_legal_ir_target_losses() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    evaluation = AdaptiveModalAutoencoder().evaluate(
        [sample],
        legal_ir_bridge_names=("deontic_norms", "fol_tdfol"),
    )

    block = runner.metric_block(evaluation)

    assert block["legal_ir_target_count"] == 1
    assert block["legal_ir_losses"]["legal_ir_multiview_total_loss"] >= 0.0
    assert block["legal_ir_losses"]["legal_ir_multiview_view_coverage_loss"] == 0.0
    assert block["legal_ir_losses"]["legal_ir_view_cross_entropy_loss"] > 0.0
    assert block["legal_ir_target_hashes"][sample.sample_id]
    assert block["legal_ir_view_distribution"]
    assert block["legal_ir_predicted_view_distribution"]


def test_autoencoder_memory_gap_block_flags_memorization_probe() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    autoencoder = AdaptiveModalAutoencoder()
    generalized = autoencoder.evaluate([sample], use_sample_memory=False)
    autoencoder.state.decoded_embeddings[sample.sample_id] = list(
        sample.embedding_vector
    )
    sample_memory = autoencoder.evaluate([sample], use_sample_memory=True)

    block = runner.autoencoder_memory_gap_block(
        generalized,
        sample_memory,
        dataset="validation",
        expected_holdout=True,
    )

    assert block["dataset"] == "validation"
    assert block["generalized_label"] == "sample_memory_disabled"
    assert block["sample_memory_label"] == "sample_memory_enabled"
    assert block["cosine_gain_from_sample_memory"] > 0.0
    assert block["reconstruction_gain_from_sample_memory"] > 0.0
    assert block["sample_memory_advantage_detected"] is True
    assert block["unexpected_holdout_memory_advantage"] is True


def test_autoencoder_state_telemetry_includes_low_rank_shadow(tmp_path) -> None:
    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={"token:agency": [1.0, 2.0, 3.0, 4.0]}
    )
    state_path = tmp_path / "state.json"
    state.save_json(state_path)

    telemetry = runner.autoencoder_state_telemetry(state, state_path=state_path)

    assert telemetry["state_file"]["exists"] is True
    assert telemetry["state_file"]["size_bytes"] > 0
    assert telemetry["low_rank_shadow"]["shadow_mode"] is True
    assert telemetry["low_rank_shadow"]["rank"] > 0
    assert telemetry["low_rank_shadow"]["dense_vector_entry_count"] == 1
    assert telemetry["low_rank_shadow"]["sampled_reconstruction_count"] == 1
    assert telemetry["low_rank_sidecar"]["enabled"] is False


def test_autoencoder_state_telemetry_can_write_low_rank_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={
            "token:agency": [1.0, 2.0, 3.0, 4.0],
            "token:duty": [4.0, 3.0, 2.0, 1.0],
        }
    )
    state_path = tmp_path / "state.json"
    state.save_json(state_path)
    monkeypatch.setenv(
        "IPFS_DATASETS_AUTOENCODER_LOW_RANK_SIDECAR_MAX_VECTORS",
        "1",
    )

    telemetry = runner.autoencoder_state_telemetry(state, state_path=state_path)
    sidecar = telemetry["low_rank_sidecar"]

    assert sidecar["enabled"] is True
    assert sidecar["status"] == "saved"
    assert sidecar["complete"] is False
    assert sidecar["vector_entry_count"] == 1
    assert sidecar["file"]["exists"] is True
    payload = json.loads(Path(sidecar["path"]).read_text(encoding="utf-8"))
    assert payload["vector_entry_count"] == 1
    assert payload["complete"] is False


def test_autoencoder_low_rank_load_report_hydrates_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    source = ModalAutoencoderTrainingState(
        feature_embedding_weights={
            "token:agency": [1.0, -2.0, 3.0, -4.0],
            "token:duty": [2.0, 0.0, -2.0, 1.0],
        },
    )
    state_path = tmp_path / "state.json"
    sidecar_path = ModalAutoencoderTrainingState.low_rank_shadow_sidecar_path(
        state_path
    )
    source.save_low_rank_shadow_json(sidecar_path, rank=4)
    target = ModalAutoencoderTrainingState(
        feature_embedding_weights={"token:agency": [9.0, 9.0, 9.0, 9.0]},
    )
    monkeypatch.setenv("IPFS_DATASETS_AUTOENCODER_LOW_RANK_LOAD", "1")

    report = runner.autoencoder_low_rank_load_report(
        target,
        state_path=state_path,
    )

    assert report["enabled"] is True
    assert report["dense_state_hydrated"] is True
    assert report["merged_vector_entry_count"] == 1
    assert report["skipped_existing_vector_entry_count"] == 1
    assert target.feature_embedding_weights["token:agency"] == [
        9.0,
        9.0,
        9.0,
        9.0,
    ]
    assert target.feature_embedding_weights["token:duty"] == pytest.approx(
        [2.0, 0.0, -2.0, 1.0]
    )


def test_learned_ir_metric_block_reports_autoencoder_view_alignment() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall publish notice before the permit takes effect.",
    )
    evaluation = AdaptiveModalAutoencoder().evaluate(
        [sample],
        legal_ir_bridge_names=("deontic_norms", "fol_tdfol"),
    )

    block = runner.learned_ir_metric_block(evaluation)

    assert block["target_count"] == 1
    assert block["view_cross_entropy_loss"] > 0.0
    assert 0.0 <= block["view_cosine_similarity"] <= 1.0
    assert block["family_cross_entropy_excess_loss"] >= 0.0
    assert block["worst_family_cross_entropy_excess_loss"] >= 0.0
    assert block["worst_family_cross_entropy_excess_name"]
    assert block["worst_family_cosine_gap_loss"] >= 0.0
    assert block["family_cross_entropy_excess_by_family"]
    assert block["target_view_distribution"]
    assert block["predicted_view_distribution"]


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
    assert (
        run.final_evaluation.embedding_cosine_similarity
        > before.embedding_cosine_similarity
    )
    assert run.final_evaluation.embedding_cosine_similarity > 0.999
    assert run.to_dict()["steps"]
    assert path.read_text(encoding="utf-8").startswith("{")


def test_supervisor_optimize_refreshes_external_program_synthesis_queue_state() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice before adopting a rule.",
    )
    stale_todo = ModalTodo(
        todo_id="program-stale-external",
        action="repair_tdfol_bridge_parse",
        objective="external Codex work should not remain pending after refresh",
        sample_ids=[sample.sample_id],
        citations=[sample.citation],
        loss_name="tdfol_parse_failure_ratio",
        loss_value=1.0,
        priority=1.0,
        metadata={
            "execution_target": "codex_program_repair",
            "optimizer_role": "program_synthesis",
            "program_synthesis_scope": "tdfol",
        },
    )
    supervisor = ModalTodoSupervisor(
        queue=ModalTodoQueue([stale_todo]),
        policy=ModalOptimizerPolicy(enable_program_synthesis_todos=False),
    )
    refresh_stages = []
    progress_stages = []

    def refresh_queue(target_supervisor: ModalTodoSupervisor) -> None:
        refreshed = ModalTodoQueue([ModalTodo.from_dict(stale_todo.to_dict())])
        refreshed.complete(stale_todo.todo_id)
        target_supervisor.queue = refreshed
        refresh_stages.append(target_supervisor.queue.status_counts())

    def record_progress(progress: Mapping[str, object]) -> None:
        progress_stages.append(str(progress.get("stage") or ""))

    run = supervisor.optimize(
        [sample],
        autoencoder=AdaptiveModalAutoencoder(),
        max_iterations=1,
        max_items=2,
        queue_refresh_callback=refresh_queue,
        progress_callback=record_progress,
    )

    assert refresh_stages
    assert supervisor.queue.pending_count(optimizer_role="program_synthesis") == 0
    assert supervisor.queue.status_counts().get("completed") == 1
    assert run.steps[0].program_synthesis_pending_count == 0
    assert "queue_refresh_before_iteration" in progress_stages
    assert "before_train_evaluation_start" in progress_stages
