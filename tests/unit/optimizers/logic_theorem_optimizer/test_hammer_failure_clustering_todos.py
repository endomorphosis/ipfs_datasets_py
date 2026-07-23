"""Recurrence and boundedness tests for hammer failure Codex TODO clusters."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalOptimizerPolicy,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    HAMMER_FAILURE_CLUSTER_DEDUPE_FIELDS,
    hammer_failure_projection_todos,
    load_leanstral_direct_guidance_artifacts,
)


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir"


def _failure(
    guidance_id: str,
    *,
    allowed_paths: tuple[str, ...] = (
        "ipfs_datasets_py/logic/bridge/deontic_norms.py",
    ),
    contract_id: str = "legal-ir-view/deontic/v1",
    failure_reason: str = "hammer_unproved",
    obligation_family: str = "exception_scope_precedence",
    target_view: str = "deontic.ir",
    validation_command: str = (
        ".venv-cuda/bin/python -m pytest "
        "tests/unit/logic/integration/test_legal_ir_view_contracts.py -q"
    ),
) -> dict:
    return {
        "allowed_paths": list(allowed_paths),
        "backend_statuses": {"z3": "failed"},
        "contract_id": contract_id,
        "failure_reason": failure_reason,
        "guidance_id": guidance_id,
        "legal_ir_view": target_view,
        "metadata": {
            "citation": "5 U.S.C. 552",
            "obligation_family": obligation_family,
            "sample_id": f"sample-{guidance_id}",
        },
        "obligation_id": f"obligation-{guidance_id}",
        "proof_checked": False,
        "proof_obligation_ids": [f"obligation-{guidance_id}"],
        "proved": False,
        "reconstruction_status": "kernel_rejected",
        "schema_version": "legal-ir-hammer-guidance-v1",
        "source": "hammer_verified_guidance",
        "target_component": target_view,
        "target_view": target_view,
        "trusted": False,
        "validation_commands": [validation_command],
    }


def _pair(prefix: str, **overrides: object) -> list[dict]:
    return [
        _failure(f"{prefix}-1", **overrides),
        _failure(f"{prefix}-2", **overrides),
    ]


def test_only_independent_recurring_verified_failures_create_todos() -> None:
    recurring = _pair("recurring")
    duplicated_one_off = _failure(
        "duplicate",
        obligation_family="duplicate_one_off_family",
    )
    unavailable = _pair("unavailable", failure_reason="backend_unavailable")
    for item in unavailable:
        item["backend_statuses"] = {"z3": "unavailable", "cvc5": "unavailable"}
    successful = _failure("successful", failure_reason="")
    successful.update(
        {
            "backend_statuses": {"z3": "proved"},
            "proved": True,
            "reconstruction_status": "verified",
            "trusted": True,
        }
    )

    todos = hammer_failure_projection_todos(
        [*recurring, duplicated_one_off, dict(duplicated_one_off), *unavailable, successful],
        policy=ModalOptimizerPolicy(),
        min_support=2,
        max_todos_per_cycle=10,
        max_todos_per_scope=10,
    )

    assert len(todos) == 1
    metadata = todos[0].metadata
    assert metadata["support_count"] == 2
    assert metadata["observation_count"] == 2
    assert metadata["qualification_reason"] == "recurring_verified_failure"
    assert metadata["recurring_verified_failure"] is True
    assert metadata["high_impact_replay_failure"] is False


def test_cluster_identity_uses_every_required_dedupe_dimension() -> None:
    path_b = ("ipfs_datasets_py/logic/deontic/converter.py",)
    failures = [
        *_pair("base"),
        *_pair("contract", contract_id="legal-ir-view/deontic/v2"),
        *_pair("family", obligation_family="temporal_deadline"),
        *_pair("view", target_view="deontic"),
        *_pair("reason", failure_reason="reconstruction_failed"),
        *_pair("path", allowed_paths=path_b),
    ]

    todos = hammer_failure_projection_todos(
        failures,
        max_todos_per_cycle=20,
        max_todos_per_scope=20,
    )

    assert len(todos) == 6
    assert len({todo.todo_id for todo in todos}) == 6
    assert len({todo.metadata["dedupe_signature"] for todo in todos}) == 6
    for todo in todos:
        metadata = todo.metadata
        assert tuple(metadata["dedupe_keys"]) == HAMMER_FAILURE_CLUSTER_DEDUPE_FIELDS
        assert tuple(metadata["dedupe_key_fields"]) == HAMMER_FAILURE_CLUSTER_DEDUPE_FIELDS
        assert set(metadata["cluster_key"]) == set(HAMMER_FAILURE_CLUSTER_DEDUPE_FIELDS)
        assert metadata["cluster_key"] == metadata["dedupe_key_values"]
        assert metadata["allowed_paths"] == sorted(metadata["allowed_paths"])
        assert 0 < len(metadata["allowed_paths"]) <= 8

    reversed_todos = hammer_failure_projection_todos(
        list(reversed(failures)),
        max_todos_per_cycle=20,
        max_todos_per_scope=20,
    )
    assert [todo.todo_id for todo in reversed_todos] == [
        todo.todo_id for todo in todos
    ]


def test_single_high_impact_replay_qualifies_but_low_impact_replay_does_not() -> None:
    high_impact = {
        "case_id": "critical-replay",
        "impact": "high",
        "hammer_guidance_artifacts": [_failure("critical-replay")],
        "schema_version": "legal-ir-contract-replay-v1",
    }
    low_impact = {
        "case_id": "diagnostic-replay",
        "hammer_guidance_artifacts": [_failure("diagnostic-replay")],
        "schema_version": "legal-ir-contract-replay-v1",
    }

    high_todos = hammer_failure_projection_todos(high_impact)
    low_todos = hammer_failure_projection_todos(low_impact)

    assert len(high_todos) == 1
    assert low_todos == []
    metadata = high_todos[0].metadata
    assert metadata["support_count"] == 1
    assert metadata["high_impact_replay_failure"] is True
    assert metadata["qualification_reason"] == "high_impact_replay_failure"
    assert metadata["replay_case_ids"] == ["critical-replay"]


def test_source_copy_replay_metric_regressions_are_high_impact(tmp_path: Path) -> None:
    source = FIXTURES / "source_copy_reward_hack_replay.jsonl"
    replay_path = tmp_path / "replay.jsonl"
    # Keep the loader boundary in the test: replay context must survive flattening.
    replay_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    loaded = load_leanstral_direct_guidance_artifacts([replay_path])
    todos = hammer_failure_projection_todos(
        loaded["guidance_items"],
        max_todos_per_cycle=10,
        max_todos_per_scope=10,
    )

    assert loaded["guidance_count"] == 3
    assert len(todos) == 3
    assert all(todo.metadata["high_impact_replay_failure"] for todo in todos)
    assert {case_id for todo in todos for case_id in todo.metadata["replay_case_ids"]} == {
        "cosine-improves-symbolic-validity-regresses",
        "decompiler-copies-source-without-structure",
        "raw-source-span-used-as-ir",
    }


def test_loader_preserves_same_failure_recurring_across_cycle_artifacts(
    tmp_path: Path,
) -> None:
    failure = _failure("stable-hammer-guidance-id")
    paths = [tmp_path / "cycle-1.json", tmp_path / "cycle-2.json"]
    for path in paths:
        path.write_text(
            json.dumps({"hammer_guidance_artifacts": [failure]}, sort_keys=True),
            encoding="utf-8",
        )

    loaded = load_leanstral_direct_guidance_artifacts(paths)
    todos = hammer_failure_projection_todos(loaded["guidance_items"])

    assert loaded["guidance_count"] == 2
    assert loaded["guidance_ids"] == ["stable-hammer-guidance-id"]
    assert len(todos) == 1
    assert todos[0].metadata["support_count"] == 2


def test_scope_and_cycle_caps_are_hard_and_high_impact_replays_rank_first() -> None:
    high_impact = {
        "case_id": "urgent",
        "high_impact_replay_failure": True,
        "hammer_guidance_artifacts": [
            _failure("urgent", obligation_family="urgent_family")
        ],
        "schema_version": "legal-ir-replay-v1",
    }
    failures = [
        high_impact,
        *_pair("family-a", obligation_family="family_a"),
        *_pair("family-b", obligation_family="family_b"),
        *_pair(
            "tdfol",
            contract_id="legal-ir-view/tdfol/v1",
            obligation_family="tdfol_parse",
            target_view="TDFOL.prover",
            allowed_paths=("ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",),
        ),
    ]

    todos = hammer_failure_projection_todos(
        failures,
        max_todos_per_cycle=2,
        max_todos_per_scope=1,
    )

    assert len(todos) == 2
    assert todos[0].metadata["qualification_reason"] == "high_impact_replay_failure"
    assert {todo.metadata["program_synthesis_scope"] for todo in todos} == {
        "deontic",
        "tdfol",
    }
    assert hammer_failure_projection_todos(failures, max_todos_per_cycle=0) == []
    assert hammer_failure_projection_todos(failures, max_todos_per_scope=0) == []


def test_every_clustered_todo_has_executable_validation_commands() -> None:
    custom_validation = (
        ".venv-cuda/bin/python -m pytest "
        "tests/unit/logic/integration/test_legal_ir_subgoal_decomposition.py -q"
    )
    todos = hammer_failure_projection_todos(
        _pair("validation", validation_command=custom_validation)
    )

    assert len(todos) == 1
    todo = todos[0]
    commands = todo.metadata["validation_commands"]
    assert custom_validation in commands
    assert commands == todo.metadata["validation_set"]["validation_commands"]
    assert all(isinstance(command, str) and "pytest" in command for command in commands)
    # TODO metadata must remain JSON serializable for the JSONL queue.
    json.dumps(todo.to_dict(), sort_keys=True)
