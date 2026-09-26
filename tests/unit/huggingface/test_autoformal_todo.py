"""Hugging Face autoformal todos are parquet + board, not JSONL."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.huggingface.autoformal_todo import (
    AutoformalTodoError,
    build_autoformal_todo_package,
    publish_observation_todos,
    publish_repair_item_todos,
    upload_autoformal_todos,
)
from ipfs_datasets_py.huggingface.publication_profile import (
    AUTOFORMAL_TODO_DEFAULT_REPOSITORY_ID,
    autoformal_todo_publication_profile,
)
from ipfs_datasets_py.logic.autoformal.supervisor_todo import discrepancy_tasks


def _tasks() -> list[dict]:
    return discrepancy_tasks(
        {
            "agrees": False,
            "rows": [
                {
                    "id": "usc:us:5:552.span-1",
                    "legal_id": "usc:us:5:552",
                    "text": "Each agency shall make records available.",
                    "reason": "no_parser_elements",
                    "agrees": False,
                    "skipped": False,
                    "dropped": [],
                    "decompiled": "",
                }
            ],
        }
    )


def test_package_refuses_board_parquet_task_id_drift(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.huggingface import autoformal_todo as module

    original = module.render_supervisor_board

    def drifted_board(tasks):
        markdown = original(tasks)
        return markdown.replace(str(tasks[0]["task_id"]), "AFTD-999-deadbeef", 1)

    monkeypatch.setattr(module, "render_supervisor_board", drifted_board)
    with pytest.raises(AutoformalTodoError, match="match the parquet table"):
        build_autoformal_todo_package(_tasks(), tmp_path / "pkg")


def test_package_writes_parquet_board_and_locator_not_jsonl(tmp_path: Path) -> None:
    package = build_autoformal_todo_package(_tasks(), tmp_path / "pkg")
    root = Path(package["package_root"])
    assert package["jsonl_written"] is False
    assert not list(root.glob("*.jsonl"))
    assert (root / "todos.parquet").is_file()
    table_ids = pq.read_table(root / "todos.parquet").column("task_id").to_pylist()
    board_ids = [
        line.split()[1]
        for line in (root / "board.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## AFTD-")
    ]
    assert table_ids == board_ids
    assert (root / "board.md").is_file()
    assert (root / "locator.json").is_file()
    assert (root / "pointer.json").is_file()
    pointer = json.loads((root / "pointer.json").read_text(encoding="utf-8"))
    assert pointer["schema"] == "ipfs_datasets_py/autoformal-todo-release-pointer/v1"
    assert pointer["package_root"] == str(root)
    assert pointer["jsonl_written"] is False
    assert Path(pointer["locator_path"]).is_file()
    table = pq.read_table(root / "todos.parquet")
    assert table.num_rows == 1
    assert "task_id" in table.column_names
    locator = json.loads((root / "locator.json").read_text(encoding="utf-8"))
    assert locator["schema"] == "ipfs_accelerate_py.agent_supervisor.huggingface_todo_locator/v1"
    assert locator["dataset_repo_id"] == AUTOFORMAL_TODO_DEFAULT_REPOSITORY_ID
    assert locator["board_namespace"] == "uscode-autoformal-todo-v1"
    assert locator["time_management"]["task_count"] == 1
    assert "estimated_tokens" in locator["todos_path"] or locator["todos_path"].endswith("todos.parquet")
    board = (root / "board.md").read_text(encoding="utf-8")
    assert "## AFTD-" in board
    assert "- Preserve:" in board


def test_upload_dry_run_plans_without_write_contact(tmp_path: Path) -> None:
    planned = {}

    class _Publisher:
        def plan_dry_run(self, manifest, **kwargs):
            planned["manifest"] = manifest
            planned["local_root"] = kwargs["local_root"]
            return SimpleNamespace(plan_digest="digest", remote_write_contacted=False)

    receipt = upload_autoformal_todos(
        _tasks(),
        tmp_path / "pkg",
        dry_run=True,
        publisher=_Publisher(),
    )
    assert receipt["dry_run"] is True
    assert receipt["uploaded"] is False
    assert receipt["remote_write_contacted"] is False
    assert receipt["jsonl_written"] is False
    assert planned["manifest"]["jsonl_written"] is False
    assert planned["manifest"]["files"]
    assert all(item["relative_path"] != "todos.jsonl" for item in planned["manifest"]["files"])


def test_live_upload_without_approval_is_refused(tmp_path: Path) -> None:
    class _Publisher:
        def plan_dry_run(self, manifest, **kwargs):
            return SimpleNamespace(plan_digest="digest")

    with pytest.raises(AutoformalTodoError, match="approved publish"):
        upload_autoformal_todos(
            _tasks(),
            tmp_path / "pkg",
            dry_run=False,
            publisher=_Publisher(),
        )


def test_live_upload_with_approval_calls_append_only_publish(tmp_path: Path) -> None:
    seen = {}

    class _Publisher:
        def plan_dry_run(self, manifest, **kwargs):
            return SimpleNamespace(plan_digest="a" * 64, dry_run=True)

        def publish_append_only(self, plan, *, approval, local_root):
            seen["plan"] = plan
            seen["approval"] = approval
            seen["local_root"] = local_root
            return SimpleNamespace(commit_sha="b" * 40, to_dict=lambda: {"commit_sha": "b" * 40})

    receipt = upload_autoformal_todos(
        _tasks(),
        tmp_path / "pkg",
        dry_run=False,
        publisher=_Publisher(),
        approval=SimpleNamespace(plan_digest="a" * 64),
    )
    assert receipt["uploaded"] is True
    assert receipt["dry_run"] is False
    assert receipt["commit_sha"] == "b" * 40
    assert receipt["locator"]["revision"] == "b" * 40
    assert receipt["jsonl_written"] is False
    assert seen["local_root"] == receipt["local_root"]


def test_autoformal_todo_profile_is_not_abby() -> None:
    profile = autoformal_todo_publication_profile()
    payload = json.dumps(profile.to_dict())
    assert "abby" not in payload.casefold()
    assert profile.repository_id == AUTOFORMAL_TODO_DEFAULT_REPOSITORY_ID
    assert profile.allow_remote_write_on_dry_run is False


def test_real_publisher_dry_run_accepts_the_todo_package(tmp_path: Path) -> None:
    from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher

    package = build_autoformal_todo_package(_tasks(), tmp_path / "pkg")
    publisher = HuggingFaceReleasePublisher(profile=autoformal_todo_publication_profile())
    plan = publisher.plan_dry_run(package["manifest"], local_root=package["local_root"])
    assert plan.dry_run is True
    assert plan.remote_write_contacted is False
    assert plan.repository_id == AUTOFORMAL_TODO_DEFAULT_REPOSITORY_ID
    remotes = [item.remote_path for item in plan.operations]
    assert any(path.endswith("/todos.parquet") for path in remotes)
    assert any(path.endswith("/board.md") for path in remotes)
    assert any(path.endswith("/locator.json") for path in remotes)
    assert not any(path.endswith(".jsonl") for path in remotes)


def test_publish_repair_item_todos_uses_sealed_packet_rows(tmp_path: Path) -> None:
    receipt = publish_repair_item_todos(
        [
            {
                "packet": {
                    "row": {
                        "id": "ext-1",
                        "source_span_id": "s1",
                        "text": "Congress supports retaining records.",
                        "reason": "extended_ir_v2",
                        "decompiled": "",
                    }
                }
            }
        ],
        tmp_path / "versioned-pkg",
        board_path=tmp_path / "versioned.todo.md",
        pointer_path=tmp_path / "versioned.pointer.json",
        release_id="parent-task",
    )
    assert receipt["jsonl_written"] is False
    assert receipt["task_count"] == 1
    assert (tmp_path / "versioned.todo.md").is_file()
    assert (tmp_path / "versioned.pointer.json").is_file()
    assert (tmp_path / "versioned-pkg" / "todos.parquet").is_file()


def test_publish_observation_todos_flattens_cycle_batches(tmp_path: Path) -> None:
    receipt = publish_observation_todos(
        [
            {
                "rows": [
                    {
                        "id": "a",
                        "source_span_id": "s1",
                        "text": "Each agency shall make records available.",
                        "reason": "no_parser_elements",
                        "agrees": False,
                        "skipped": False,
                        "dropped": [],
                        "decompiled": "",
                    }
                ]
            },
            {
                "rows": [
                    {
                        "id": "b",
                        "text": "The agency may withhold secrets.",
                        "reason": "",
                        "agrees": True,
                        "skipped": False,
                        "decompiled": "The agency may withhold secrets.",
                    }
                ]
            },
        ],
        tmp_path / "cycle-pkg",
        board_path=tmp_path / "cycle.todo.md",
        pointer_path=tmp_path / "cycle.pointer.json",
        release_id="cycle-1",
    )
    assert receipt["jsonl_written"] is False
    assert receipt["task_count"] == 1
    assert (tmp_path / "cycle.todo.md").is_file()
    assert (tmp_path / "cycle.pointer.json").is_file()
    assert (tmp_path / "cycle-pkg" / "todos.parquet").is_file()
