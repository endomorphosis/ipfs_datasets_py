"""Failed autoformal jobs become supervisor todos, not compiler patches."""
from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal.supervisor_todo import (
    BOARD_NAMESPACE,
    SupervisorBoardError,
    agreement_from_spans,
    discrepancy_tasks,
    preserve_replace_for,
    render_supervisor_board,
    submit_discrepancies,
    time_management,
    validate_supervisor_board,
)


def _agreement() -> dict:
    return {
        "agrees": False,
        "reason": "compiler_disagreement",
        "rows": [
            {
                "id": "usc:us:5:552.span-1",
                "source_span_id": "uscode-span-aaa",
                "legal_id": "usc:us:5:552",
                "entry_cid": "bafkreiabc",
                "text": "Each agency shall make records available unless the record is secret.",
                "reason": "dropped_clause",
                "dropped": ["unless the record is secret"],
                "decompiled": "Each agency shall make records available.",
                "agrees": False,
                "skipped": False,
            },
            {
                "id": "usc:us:5:552.span-2",
                "text": "The agency may withhold secrets.",
                "reason": "",
                "agrees": True,
                "skipped": False,
                "decompiled": "The agency may withhold secrets.",
            },
        ],
    }


def test_preserve_replace_names_decompiler_without_emitting_a_patch() -> None:
    decision = preserve_replace_for(
        {"reason": "dropped_clause", "dropped": ["unless"]},
        agreed_ids=["usc:us:5:552.span-2"],
    )
    assert any("TypedDeonticCanonicalCompiler" in item for item in decision["preserve"])
    assert any("decompiler reconstruction" in item for item in decision["replace"])
    assert "missing surfaces: unless" in decision["replace"]


def test_discrepancy_tasks_carry_time_management_and_do_not_write_jsonl() -> None:
    tasks = discrepancy_tasks(_agreement(), query="FOIA", release_id="rel-1")
    assert len(tasks) == 1
    task = tasks[0]
    assert task["task_id"].startswith("AFTD-")
    assert task["failure_mode"] == "dropped_clause"
    assert task["estimated_tokens"] > 0
    assert task["estimated_validation_seconds"] > 0
    assert "decompiler reconstruction" in " ".join(task["replace"])
    budget = time_management(tasks)
    assert budget["task_count"] == 1
    assert budget["total_estimated_tokens"] == task["estimated_tokens"]


def test_board_is_supervisor_markdown_and_not_a_compiler_edit(tmp_path: Path) -> None:
    tasks = discrepancy_tasks(_agreement())
    receipt = submit_discrepancies(_agreement(), board_path=tmp_path / "board.md")
    markdown = Path(receipt["board_path"]).read_text(encoding="utf-8")
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["wrote_decompiler"] is False
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False
    assert BOARD_NAMESPACE in markdown
    assert markdown.startswith("# ")
    assert "## AFTD-" in markdown
    assert "- Preserve:" in markdown
    assert "- Replace:" in markdown
    assert "- Estimated tokens:" in markdown
    assert "proposed_compiler" not in markdown
    assert render_supervisor_board(tasks) == markdown


def test_agreement_from_spans_skips_inactive_and_does_not_admit() -> None:
    agreement = agreement_from_spans(
        [
            {"id": "a", "status": "compiled", "text": "The agency shall retain records.", "source_span_id": "s1"},
            {"id": "b", "status": "gap", "reason": "no_parser_elements", "text": "Each agency shall make records available.", "source_span_id": "s2"},
            {"id": "c", "status": "inactive", "text": "repealed"},
        ]
    )
    assert agreement["agrees"] is False
    assert agreement["admitted"] is False
    assert agreement["agreed"] == 1
    assert agreement["operative"] == 2
    assert agreement["rows"][1]["reason"] == "no_parser_elements"


def test_submit_discrepancies_calls_native_after_huggingface() -> None:
    seen = {}

    def upload(tasks):
        seen["uploaded"] = len(list(tasks))
        return {"locator": {"dataset_repo_id": "justicedao/uscode-autoformal-todos"}, "jsonl_written": False}

    def native(agreement, huggingface_locator=None):
        seen["locator"] = huggingface_locator
        seen["rows"] = len(agreement["rows"])
        return {"authority": "accelerate-duckdb", "task_count": 1, "jsonl_written": False}

    receipt = submit_discrepancies(_agreement(), upload=upload, native=native)
    assert seen["uploaded"] == 1
    assert seen["locator"]["dataset_repo_id"] == "justicedao/uscode-autoformal-todos"
    assert receipt["authority"] == "accelerate-duckdb"
    assert receipt["native_queue"]["jsonl_written"] is False
    assert receipt["jsonl_written"] is False


def test_compiled_status_and_stale_rendering_are_not_agreement(monkeypatch) -> None:
    from ipfs_datasets_py.logic.autoformal import autoencoder_router
    observed = []
    def census(spans, inference):
        observed.extend(spans)
        assert inference == {}  # No fabricated model captures.
        return {"rows": [{**spans[0], "agrees": False, "skipped": False,
                          "reason": "dropped_clause", "dropped": ["15"],
                          "decompiled": "The officer must retain records."}]}
    monkeypatch.setattr(autoencoder_router, "agreement_census", census)
    span = {"id": "test", "status": "compiled", "text": "The officer shall retain 15 records.",
            "decompiled": "The officer must retain 15 records.", "agrees": True}
    result = agreement_from_spans([span])
    assert observed == [span]
    assert result["agreed"] == 0 and result["agrees"] is False
    assert result["rows"][0]["reason"] == "dropped_clause"
    assert result["rows"][0]["dropped"] == ["15"]
    assert result["rows"][0]["observed_compiler_status"] == "compiled"
    assert span["agrees"] is True  # Do not rewrite the ledger.


def test_rendered_board_validates_preserve_replace_and_time_budget() -> None:
    markdown = render_supervisor_board(discrepancy_tasks(_agreement()))
    report = validate_supervisor_board(markdown)
    assert report["valid"] is True
    assert report["jsonl_written"] is False
    assert report["task_count"] == 1


def test_board_validator_rejects_jsonl_and_compiler_patches() -> None:
    markdown = render_supervisor_board(discrepancy_tasks(_agreement()))
    with pytest.raises(SupervisorBoardError, match="jsonl"):
        validate_supervisor_board(markdown + "\nSee todos.jsonl\n")
    with pytest.raises(SupervisorBoardError, match="compiler patch"):
        validate_supervisor_board(markdown.replace("Conflict policy:", "proposed_compiler and Conflict policy:"))
    broken = markdown.replace("- Preserve:", "- Note:")
    with pytest.raises(SupervisorBoardError, match="Preserve"):
        validate_supervisor_board(broken)


def test_upload_hook_receives_tasks_instead_of_jsonl() -> None:
    seen = {}

    def upload(tasks):
        seen["count"] = len(list(tasks))
        return {"locator": {"schema": "ipfs_accelerate_py.agent_supervisor.huggingface_todo_locator/v1"}, "jsonl_written": False}

    receipt = submit_discrepancies(_agreement(), upload=upload)
    assert seen["count"] == 1
    assert receipt["locator"]["schema"].endswith("huggingface_todo_locator/v1")
    assert receipt["jsonl_written"] is False
