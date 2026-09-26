"""Loop todos declare train and compiler/decompiler edit work without admitting."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal.supervisor_dispatch import (
    TRAINING_ENTRYPOINT,
    TRAINING_JOB_SCHEMA,
    TRAINING_NAMESPACE,
    WORK_KIND_EDIT,
    WORK_KIND_REVIEW,
    WORK_KIND_TRAIN,
    attach_dispatch,
    classify_work,
    dispatch_counts,
)
from ipfs_datasets_py.logic.autoformal.supervisor_loop import run_supervisor_loop, spawn_goal_tree, supervisor_population
from ipfs_datasets_py.logic.autoformal.supervisor_queue import EDIT_SCOPES, NAMESPACE as REPAIR_NAMESPACE
from ipfs_datasets_py.logic.autoformal.supervisor_todo import discrepancy_tasks, render_supervisor_board, validate_supervisor_board


def _row(span_id: str, *, reason: str, text: str = "Each agency shall make records available.", legal_id: str = "usc:us:5:552") -> dict:
    return {
        "agrees": False,
        "id": span_id,
        "legal_id": legal_id,
        "reason": reason,
        "skipped": False,
        "source_span_id": span_id,
        "text": text,
    }


def _v6_template(path: Path) -> Path:
    path.write_text(json.dumps({"schema_version": TRAINING_JOB_SCHEMA}), encoding="utf-8")
    return path


def test_classify_work_maps_failure_modes_to_train_and_edit() -> None:
    assert classify_work("no_parser_elements") == (WORK_KIND_EDIT,)
    assert classify_work("compiler_abstain:recipient") == (WORK_KIND_EDIT,)
    assert classify_work("CanonicalErrorCode.UNSUPPORTED_SEMANTICS") == (WORK_KIND_EDIT,)
    assert classify_work("strict_roundtrip_failed") == (WORK_KIND_EDIT,)
    assert classify_work("inference_still_failing") == (WORK_KIND_TRAIN,)
    assert classify_work("capture_not_in_decompilation") == (WORK_KIND_EDIT, WORK_KIND_TRAIN)
    assert classify_work("loop_error") == ()


def test_parser_gap_declares_edit_scope_without_training() -> None:
    tasks = discrepancy_tasks({"rows": [_row("s1", reason="no_parser_elements"), _row("s2", reason="no_parser_elements")]})
    tree = spawn_goal_tree(tasks)
    assert {task["work_kind"] for task in tree["tasks"]} == {WORK_KIND_EDIT}
    for task in tree["tasks"]:
        assert task["allowed_edit_paths"] == list(EDIT_SCOPES["no_parser_elements"])
        assert task["predicted_files"] == task["allowed_edit_paths"]
        assert task["conflict_policy"] == "serialize overlapping compiler/decompiler edits"
        assert task.get("training_job") in (None, {}, []) or "training_job" not in task
        assert task["admitted"] is False
        assert task["formalized"] is False
        assert task["wrote_compiler"] is False
        assert task["dispatch_status"] == "awaiting_sealed_packet"
        assert task["review_only"] is True
    markdown = render_supervisor_board(tree["tasks"], goals=tree["goals"])
    validate_supervisor_board(markdown)
    assert "- Work kind: compiler_decompiler_edit" in markdown


def test_inference_failure_declares_training_without_compiler_paths() -> None:
    tasks = discrepancy_tasks({"rows": [_row("inf", reason="inference_still_failing", text="")]})
    tree = spawn_goal_tree(tasks)
    assert len(tree["tasks"]) == 1
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_TRAIN
    assert task["allowed_edit_paths"] == []
    assert task["board_namespace"] == TRAINING_NAMESPACE
    assert task["training_job"]["entrypoint"] == TRAINING_ENTRYPOINT
    assert task["training_job"]["bound"] is False
    assert task["review_only"] is True
    assert task["conflict_policy"] == "do not write compiler or decompiler patches from this task"
    assert task["admitted"] is False
    assert task["formalized"] is False


def test_capture_gap_spawns_edit_and_train_under_one_subgoal() -> None:
    tasks = discrepancy_tasks(
        {
            "rows": [
                _row("cap-1", reason="capture_not_in_decompilation"),
                _row("cap-2", reason="capture_not_in_decompilation"),
            ]
        }
    )
    tree = spawn_goal_tree(tasks)
    kinds = [task["work_kind"] for task in tree["tasks"]]
    assert kinds.count(WORK_KIND_EDIT) == 2
    assert kinds.count(WORK_KIND_TRAIN) == 2
    by_span: dict[str, set[str]] = {}
    for task in tree["tasks"]:
        by_span.setdefault(str(task["source_span_id"]), set()).add(str(task["goal_cid"]))
        by_span[str(task["source_span_id"])].add(str(task["work_kind"]))
    assert all(WORK_KIND_EDIT in kinds and WORK_KIND_TRAIN in kinds for kinds in by_span.values())
    for span, values in by_span.items():
        goal_cids = [item for item in values if item.startswith("goal:")]
        assert len(goal_cids) == 1
    counts = dispatch_counts(tree["tasks"])
    assert counts["edit"] == 2
    assert counts["train"] == 2
    assert counts["sealed_packets"] == 0


def test_sealed_edit_packet_matches_repair_namespace(tmp_path: Path) -> None:
    agreement = {"rows": [_row("art-1", reason="compiler_abstain:recipient")]}
    tasks = discrepancy_tasks(agreement, release_id="rel-1")
    tree = spawn_goal_tree(
        tasks,
        release_id="rel-1",
        dispatch={
            "agreement": agreement,
            "packet_directory": tmp_path / "packets",
            "code_identity": "compiler-tree-1",
            "model_identity": "checkpoint-1",
        },
    )
    assert len(tree["tasks"]) == 1
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_EDIT
    assert task["board_namespace"] == REPAIR_NAMESPACE
    assert task["dispatch_status"] == "sealed_edit"
    assert task["review_only"] is False
    assert Path(task["packet_path"]).is_file()
    assert len(task["packet_sha256"]) == 64
    argv = task["validation_commands"][0]["argv"]
    assert argv[0] == "python3"
    assert argv[1] == "scripts/ops/legal_ir/validate_autoformal_repair.py"
    assert "--packet" in argv
    assert task["packet_sha256"] in argv
    assert task["allowed_edit_paths"] == list(EDIT_SCOPES["compiler_abstain"])
    assert task["admitted"] is False
    assert task["wrote_compiler"] is False


def test_bound_training_job_uses_frozen_v6_cycle(tmp_path: Path) -> None:
    template = _v6_template(tmp_path / "job.json")
    tasks = discrepancy_tasks({"rows": [_row("inf", reason="inference_still_failing", text="")]})
    tree = spawn_goal_tree(
        tasks,
        dispatch={
            "job_template": template,
            "accelerate_root": tmp_path / "accelerate",
            "database": tmp_path / "control.duckdb",
            "runtime_root": tmp_path / "runtime",
        },
    )
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_TRAIN
    assert task["review_only"] is False
    assert task["training_job"]["bound"] is True
    assert task["training_job"]["job_schema"] == TRAINING_JOB_SCHEMA
    argv = task["validation_commands"][0]["argv"]
    assert argv[:2] == ["python3", TRAINING_ENTRYPOINT]
    assert "--job-template" in argv
    assert str(template.resolve()) in argv
    assert task["production_promotion"] is False
    assert task["admitted"] is False
    assert task["formalized"] is False


def test_invalid_job_template_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "job.json"
    bad.write_text(json.dumps({"schema_version": "autoencoder-training-job-v5"}), encoding="utf-8")
    tasks = discrepancy_tasks({"rows": [_row("inf", reason="inference_still_failing", text="")]})
    with pytest.raises(Exception, match="autoencoder-training-job-v6"):
        spawn_goal_tree(tasks, dispatch={"job_template": bad})


def test_loop_population_carries_dispatch_into_duckdb(tmp_path: Path) -> None:
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import ingest_population

    agreement = {
        "rows": [
            _row("s1", reason="no_parser_elements"),
            _row("s2", reason="inference_still_failing", text=""),
        ]
    }
    template = _v6_template(tmp_path / "job.json")
    tasks = discrepancy_tasks(agreement, release_id="rel-1")
    tree = spawn_goal_tree(
        tasks,
        release_id="rel-1",
        dispatch={
            "agreement": agreement,
            "packet_directory": tmp_path / "packets",
            "code_identity": "compiler-tree-1",
            "model_identity": "checkpoint-1",
            "job_template": template,
            "accelerate_root": tmp_path / "accelerate",
            "database": tmp_path / "control.duckdb",
            "runtime_root": tmp_path / "runtime",
        },
    )
    kinds = {task["work_kind"] for task in tree["tasks"]}
    assert kinds == {WORK_KIND_EDIT, WORK_KIND_TRAIN}
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        receipt = ingest_population(source, supervisor_population(tree))
        assert receipt["jsonl_written"] is False
        assert receipt["wrote_compiler"] is False
        assert receipt["admitted"] is False
        records = source.list_tasks(limit=10).tasks
        bodies = [record.body for record in records]
        assert any(body.get("work_kind") == WORK_KIND_EDIT and body.get("packet_sha256") for body in bodies)
        assert any(body.get("work_kind") == WORK_KIND_TRAIN and (body.get("training_job") or {}).get("bound") for body in bodies)
        assert all(body.get("admitted") is False for body in bodies)
        assert all(body.get("formalized") is False for body in bodies)
        assert all(body.get("wrote_compiler") is False for body in bodies)


def test_supervisor_loop_stamps_train_and_edit_on_population(tmp_path: Path) -> None:
    template = _v6_template(tmp_path / "job.json")

    def autoformal():
        return {
            "rows": [
                _row("s1", reason="no_parser_elements"),
                _row("inf", reason="inference_still_failing", text=""),
            ]
        }

    receipt = run_supervisor_loop(
        autoformal,
        ingest=lambda *a, **k: {"task_count": 2},
        max_rounds=1,
        dispatch={
            "packet_directory": tmp_path / "packets",
            "code_identity": "compiler-tree-1",
            "model_identity": "checkpoint-1",
            "job_template": template,
            "accelerate_root": tmp_path / "accelerate",
            "database": tmp_path / "control.duckdb",
            "runtime_root": tmp_path / "runtime",
        },
    )
    tasks = receipt["population"]["tasks"]
    kinds = {task["work_kind"] for task in tasks}
    assert kinds == {WORK_KIND_EDIT, WORK_KIND_TRAIN}
    edit = next(task for task in tasks if task["work_kind"] == WORK_KIND_EDIT)
    train = next(task for task in tasks if task["work_kind"] == WORK_KIND_TRAIN)
    assert edit["dispatch_status"] == "sealed_edit"
    assert edit["packet_sha256"]
    assert train["training_job"]["bound"] is True
    assert receipt["admitted"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["jsonl_written"] is False


def test_review_todos_stay_off_the_compiler() -> None:
    tasks = discrepancy_tasks({"rows": [_row("loop", reason="loop_error", text="census exploded")]})
    tree = spawn_goal_tree(tasks)
    task = tree["tasks"][0]
    assert task["work_kind"] == WORK_KIND_REVIEW
    assert task["review_only"] is True
    assert "compiler/decompiler" in task["conflict_policy"] or "do not write compiler" in task["conflict_policy"]
    assert not task.get("packet_sha256")
    assert not task.get("training_job")
