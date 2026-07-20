"""Tests for projecting hammer-verified failures into Codex TODOs."""

from __future__ import annotations

import json
from argparse import Namespace

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalOptimizerPolicy,
    ModalTodoQueue,
    ModalTodoSupervisor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    hammer_failure_projection_todos,
    project_verified_leanstral_guidance_artifacts_into_queue,
)


def _failed_hammer_artifact(
    guidance_id: str,
    *,
    legal_ir_view: str = "deontic.ir",
    reason: str = "hammer_unproved",
    sample_id: str = "sample-1",
) -> dict:
    return {
        "backend_statuses": {"z3": "failed"},
        "failure_reason": reason,
        "goal_name": guidance_id,
        "goal_statement_hash": f"{guidance_id}-statement",
        "guidance_id": guidance_id,
        "legal_ir_view": legal_ir_view,
        "logic_family": "deontic",
        "metadata": {
            "citation": "5 U.S.C. 552",
            "obligation_kind": "exception_scope_precedence",
            "sample_id": sample_id,
        },
        "obligation_id": guidance_id,
        "premise_views": [legal_ir_view],
        "proof_checked": False,
        "proof_obligation_ids": [guidance_id],
        "proved": False,
        "reconstruction_status": "not_reconstructed",
        "rejection_reasons": [reason],
        "schema_version": "legal-ir-hammer-guidance-v1",
        "selected_premises": ["premise.exception_scope"],
        "source": "hammer_verified_guidance",
        "target_component": legal_ir_view,
        "target_metrics": ["hammer_proof_success_rate"],
        "trusted": False,
        "winner_backend": "",
    }


def test_hammer_failure_projection_requires_recurring_failures_and_bounds_paths() -> None:
    one_off = _failed_hammer_artifact(
        "one-off",
        legal_ir_view="TDFOL.prover",
        sample_id="sample-tdfol",
    )
    recurring = [
        _failed_hammer_artifact("recurring-1", sample_id="sample-1"),
        _failed_hammer_artifact("recurring-2", sample_id="sample-2"),
    ]

    todos = hammer_failure_projection_todos(
        [one_off, *recurring],
        policy=ModalOptimizerPolicy(),
        min_support=2,
        max_todos_per_cycle=5,
        max_todos_per_scope=1,
    )

    assert len(todos) == 1
    todo = todos[0]
    assert todo.action == "repair_deontic_bridge_quality_gate"
    assert todo.loss_name == "hammer_verified_failure"
    assert todo.metadata["source"] == "hammer_failure_projection_v1"
    assert todo.metadata["program_synthesis_scope"] == "deontic"
    assert todo.metadata["support_count"] == 2
    assert "hammer_proof_success_rate" in todo.metadata["target_metrics"]
    assert "hammer_reconstruction_success_rate" in todo.metadata["target_metrics"]
    assert set(todo.metadata["proof_obligation_ids"]) == {"recurring-1", "recurring-2"}
    assert todo.metadata["allowed_paths"]
    assert all(path.startswith("ipfs_datasets_py/") for path in todo.metadata["allowed_paths"])
    assert todo.metadata["validation_commands"]


def test_direct_guidance_projection_seeds_recurring_hammer_failure_todo(tmp_path) -> None:
    artifact_path = tmp_path / "hammer-guidance.json"
    artifact_path.write_text(
        json.dumps(
            {
                "hammer_guidance_artifacts": [
                    _failed_hammer_artifact("obl-a", sample_id="sample-a"),
                    _failed_hammer_artifact("obl-b", sample_id="sample-b"),
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    queue_path = tmp_path / "queue.jsonl"
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue())
    args = Namespace(
        autoencoder_max_audits_per_cycle=0,
        autoencoder_max_todos_per_cycle=5,
        autoencoder_target_scope_filters="",
        leanstral_direct_guidance_max_todos_per_scope=2,
        leanstral_direct_guidance_path=str(artifact_path),
        leanstral_direct_guidance_projection_enabled=True,
        leanstral_direct_guidance_require_executor_available=False,
        leanstral_direct_guidance_train_autoencoder=False,
        leanstral_rule_gap_max_todos_per_scope=2,
        max_program_synthesis_pending=512,
    )

    result = project_verified_leanstral_guidance_artifacts_into_queue(
        args=args,
        queue_path=queue_path,
        root=tmp_path,
        supervisor=supervisor,
    )
    queue = ModalTodoQueue.load_jsonl(queue_path)
    todos = queue.all()

    assert result["status"] == "projected"
    assert result["hammer_failure_projection"]["seeded_count"] == 1
    assert result["seeded_count"] == 1
    assert len(todos) == 1
    assert todos[0].metadata["source"] == "hammer_failure_projection_v1"
