"""The local release pointer is what accelerate uses to find Hugging Face todos."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.autoformal_todo import (
    POINTER_SCHEMA,
    build_autoformal_todo_package,
    write_autoformal_todo_pointer,
)
from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer
from ipfs_datasets_py.logic.autoformal.supervisor_todo import discrepancy_tasks


def test_package_pointer_names_the_huggingface_locator_not_jsonl(tmp_path: Path) -> None:
    tasks = discrepancy_tasks(
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
    latest = tmp_path / "autoformal-todo-release-pointer.json"
    package = build_autoformal_todo_package(tasks, tmp_path / "pkg")
    pointer = write_autoformal_todo_pointer(package, pointer_path=latest)
    assert pointer["schema"] == POINTER_SCHEMA
    assert latest.is_file()
    assert pointer["jsonl_written"] is False
    assert Path(pointer["locator_path"]).is_file()
    assert Path(pointer["board_path"]).is_file()
    assert Path(pointer["todos_path"]).suffix == ".parquet"
    locator = json.loads(Path(pointer["locator_path"]).read_text(encoding="utf-8"))
    assert locator["schema"] == "ipfs_accelerate_py.agent_supervisor.huggingface_todo_locator/v1"
    assert locator["time_management"]["task_count"] == 1
    assert not list(tmp_path.rglob("*.jsonl"))


def test_schedule_from_pointer_library_registers_budget(tmp_path: Path) -> None:
    tasks = discrepancy_tasks(
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
    latest = tmp_path / "pointer.json"
    package = build_autoformal_todo_package(tasks, tmp_path / "pkg")
    write_autoformal_todo_pointer(package, pointer_path=latest)
    seen = {}

    def locate(source, **kwargs):
        seen["source"] = source
        seen["max_tokens"] = kwargs.get("max_tokens")
        destination = Path(kwargs["board_destination"])
        destination.write_text((Path(package["package_root"]) / "board.md").read_text(encoding="utf-8"))
        return {
            "board_path": str(destination),
            "dataset_repo_id": "justicedao/uscode-autoformal-todos",
            "enqueued_task_ids": ["AFTD-001"],
            "scheduled_task_ids": ["AFTD-001"],
            "task_count": 1,
            "time_management": {"total_estimated_tokens": 12000},
        }

    class Queue:
        saved = False

        def save(self):
            self.saved = True

    queue = Queue()
    receipt = schedule_from_pointer(
        latest,
        repo_root=tmp_path,
        board=tmp_path / "board.md",
        queue_path=tmp_path / "queue.json",
        max_tokens=15000,
        locate=locate,
        queue=queue,
    )
    assert queue.saved is True
    assert seen["max_tokens"] == 15000
    assert receipt["jsonl_written"] is False
    assert receipt["scheduled_task_ids"] == ["AFTD-001"]


def test_end_to_end_ingest_packages_and_schedules_without_jsonl(tmp_path: Path) -> None:
    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.persistent_task_queue")
    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.huggingface_todo_locator")
    import importlib.util
    from types import SimpleNamespace

    from ipfs_accelerate_py.agent_supervisor.task_sources.persistent_task_queue import (
        PersistentTaskQueue,
    )
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

    spec = importlib.util.spec_from_file_location(
        "run_uscode_e2e",
        Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/run_uscode_on_sparse_graphrag.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeSource:
        def __init__(self):
            self.records = {}
            self.materialized = []

        def list_tasks(self, cursor="", limit=100):
            return SimpleNamespace(tasks=list(self.records.values()), next_cursor="")

        def get(self, task_cid):
            return self.records.get(task_cid)

        def materialize(self, payload):
            self.materialized.append(payload)
            for task in payload["tasks"]:
                self.records[task["task_cid"]] = SimpleNamespace(
                    task_cid=task["task_cid"],
                    task_alias=task["task_id"],
                    status=task.get("status") or "ready",
                    body=dict(task),
                )

    source = FakeSource()
    receipt = module.run_uscode_autoformal(
        hits=[
            {
                "entry_cid": "bafkreiabc",
                "legal_id": "usc:us:5:552",
                "title": "5",
                "section": "552",
                "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
            }
        ],
        query="agency records",
        release_id="e2e-release-v1",
        board_path=tmp_path / "board.md",
        huggingface_package=tmp_path / "hf",
        pointer_path=tmp_path / "pointer.json",
        dry_run=True,
        task_source=source,
        packet_directory=tmp_path / "packets",
        code_identity="compiler-tree-e2e",
        model_identity="checkpoint-e2e",
    )
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["formalized"] is False
    assert receipt["task_count"] >= 1
    validate_supervisor_board((tmp_path / "board.md").read_text(encoding="utf-8"))
    assert source.materialized
    queue = PersistentTaskQueue.load(tmp_path / "queue.json")
    scheduled = schedule_from_pointer(
        tmp_path / "pointer.json",
        repo_root=tmp_path,
        board=tmp_path / "scheduled.md",
        queue_path=tmp_path / "queue.json",
        package_root=tmp_path / "hf",
        queue=queue,
        max_tokens=50_000,
    )
    assert scheduled["jsonl_written"] is False
    assert scheduled["enqueued_task_ids"]
    assert not list(tmp_path.rglob("*.jsonl"))


def test_schedule_from_pointer_rejects_jsonl_board(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import SupervisorBoardError

    pointer = tmp_path / "pointer.json"
    pointer.write_text("{}", encoding="utf-8")

    def locate(source, **kwargs):
        destination = Path(kwargs["board_destination"])
        destination.write_text("## AFTD-001 x\nSee todos.jsonl\n", encoding="utf-8")
        return {"board_path": str(destination), "scheduled_task_ids": ["AFTD-001"]}

    with pytest.raises(SupervisorBoardError, match="jsonl"):
        schedule_from_pointer(
            pointer,
            repo_root=tmp_path,
            board=tmp_path / "board.md",
            queue_path=tmp_path / "queue.json",
            locate=locate,
            queue=type("Q", (), {"save": lambda self: None})(),
        )
