"""The Constitution run receipt is not a formalization."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _module():
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "legal_ir"
        / "run_constitution_on_state.py"
    )
    spec = importlib.util.spec_from_file_location("run_constitution_on_state_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summary_never_counts_a_compile_as_formalized() -> None:
    module = _module()
    summary = module.summarize_spans(
        [
            {"status": "compiled"},
            {"status": "gap"},
            {"status": "non_operative"},
            {"status": "inactive"},
        ]
    )
    assert summary["compiled_count"] == 1
    assert summary["roundtrip_ok_count"] == 0
    assert summary["formalized"] is False
    assert summary["admitted"] is False


@pytest.mark.parametrize(
    ("outcome", "statuses", "expected_status", "expected_reason", "observed"),
    [
        ({"compiler_status": "compiled"}, ["roundtrip_ok"], "compiled", "compiler_roundtrip_observation_only", True),
        ({"compiler_status": "compiled"}, ["roundtrip_ok", "roundtrip_ok"], "compiled", "compiler_roundtrip_observation_only", True),
        ({"compiler_status": "compiled"}, ["roundtrip_ok", "compiled"], "gap", "strict_roundtrip_failed", False),
        ({"compiler_status": "compiled"}, ["compiled"], "gap", "strict_roundtrip_failed", False),
        ({"compiler_status": "abstain", "fields": ["recipient"]}, [], "gap", "compiler_abstain:recipient", False),
        ({"compiler_status": "abstain"}, [], "gap", "compiler_abstain", False),
        ({"compiler_status": "repeal"}, ["roundtrip_ok"], "repeal", "repeal_fixture", False),
    ],
)
def test_strict_compiler_observations_never_promote_constitution_spans(
    outcome, statuses, expected_status, expected_reason, observed,
) -> None:
    module = _module()
    span = {"status": "compiled", "compiler_roundtrip_observed": True}
    module._record_strict_status(
        span, outcome, [SimpleNamespace(status=status) for status in statuses],
    )
    assert span == {
        "status": "compiled",
        "strict_status": expected_status,
        "strict_reason": expected_reason,
        "compiler_roundtrip_observed": observed,
    }
    assert span["strict_status"] != "roundtrip_ok"


def test_compiler_observation_is_not_supervisor_agreement() -> None:
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import agreement_from_strict_spans

    module = _module()
    span = {"id": "synthetic", "status": "compiled", "text": "Synthetic fixture."}
    module._record_strict_status(span, {}, [SimpleNamespace(status="roundtrip_ok")])
    summary = module.summarize_spans([span])
    assert summary["roundtrip_ok_count"] == 0
    assert summary["strict_roundtrip_ok_count"] == 0
    assert summary["compiler_roundtrip_observed_count"] == 1
    assert summary["formalized"] is False
    assert summary["admitted"] is False
    agreement = agreement_from_strict_spans([span])
    assert agreement["agrees"] is False
    assert agreement["agreed"] == 0
    assert agreement["rows"][0]["reason"] == "compiler_roundtrip_observation_only"
    assert agreement["formalized"] is False
    assert agreement["admitted"] is False


def test_summary_does_not_promote_legacy_roundtrip_labels() -> None:
    module = _module()
    legacy = {"status": "roundtrip_ok", "strict_status": "roundtrip_ok"}
    summary = module.summarize_spans([legacy])
    assert summary["status_counts"] == {"roundtrip_ok": 1}
    assert summary["roundtrip_ok_count"] == 0
    assert summary["strict_roundtrip_ok_count"] == 0
    assert summary["compiler_roundtrip_observed_count"] == 0
    assert summary["formalized"] is False
    assert summary["admitted"] is False
    assert legacy == {"status": "roundtrip_ok", "strict_status": "roundtrip_ok"}


def test_synthetic_roundtrip_observation_receipt_has_no_success_status(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    source = tmp_path / "synthetic.txt"
    source.write_text("Article I\nThe agency shall retain records.")
    output = tmp_path / "receipt.json"

    def compile_one(session, _text, document_id):
        session.rows.append(SimpleNamespace(status="roundtrip_ok", document_id=document_id))
        return {"compiler_status": "compiled", "decompiled": "Synthetic compiler output."}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    assert module.main([
        "--compiler-only", "--constitution", str(source), "--output", str(output),
    ]) == 0
    receipt = json.loads(output.read_text())
    assert receipt["roundtrip_ok_count"] == 0
    assert receipt["strict_roundtrip_ok_count"] == 0
    assert receipt["compiler_roundtrip_observed_count"] == 1
    assert receipt["formalized"] is False
    assert receipt["admitted"] is False
    assert receipt["optimizer_step"] is False
    assert all(row["status"] != "roundtrip_ok" for row in receipt["spans"])
    assert all(row["strict_status"] != "roundtrip_ok" for row in receipt["spans"])
    operative = next(row for row in receipt["spans"] if row["status"] == "compiled")
    assert operative["strict_status"] == "compiled"
    assert operative["compiler_roundtrip_observed"] is True
    assert operative["strict_reason"] == "compiler_roundtrip_observation_only"
    assert receipt["supervisor"]["task_count"] >= 1


def test_census_document_ids_preserve_repeated_spans_and_source_versions(monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    calls = []

    def compile_one(_session, text, document_id):
        calls.append((text, document_id))
        return {"compiler_status": "abstain", "reason": "unsupported_fixture", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    text = "Article I\nSection 1\nThe agency shall retain records. The agency shall retain records."
    first = module.compile_constitution(text)["ledger"]
    first_calls = list(calls)
    second = module.compile_constitution(text)["ledger"]
    changed = module.compile_constitution(text + "\n")["ledger"]
    assert len(first_calls) == 2
    assert first_calls[0][0] == first_calls[1][0]
    assert first_calls[0][1] != first_calls[1][1]
    assert first["source_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert [row["source_span_id"] for row in first["spans"]] == [row["source_span_id"] for row in second["spans"]]
    assert {row["source_span_id"] for row in first["spans"]}.isdisjoint(
        row["source_span_id"] for row in changed["spans"]
    )
    assert [row["id"] for row in first["spans"]] == [row["id"] for row in changed["spans"]]
    compiled_spans = [row for row in first["spans"] if row["status"] != "non_operative"]
    assert len(compiled_spans) == 2
    assert all(row["compiler_document_id"] == row["source_span_id"] for row in compiled_spans)
    assert all(row["status"] == "gap" for row in compiled_spans)
    assert first["compiled"] is False


def test_census_session_does_not_reuse_another_spans_vocabulary(monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    original_session = autoformal.AutoformalSession
    sessions = []
    captured = []

    def session_factory():
        session = original_session()
        sessions.append(session)
        return session

    def vocabulary(text):
        return {"actors": [text.split()[1]], "actions": ["retain"], "objects": ["records"], "qualifiers": []}

    def compile_text(text, *, request_id, vocabulary, allow_partial=False):
        assert allow_partial is False
        captured.append((text, request_id, vocabulary))
        return []

    monkeypatch.setattr(autoformal, "AutoformalSession", session_factory)
    monkeypatch.setattr(autoformal, "vocabulary_from_clause", vocabulary)
    monkeypatch.setattr(autoformal, "_compile_text", compile_text)
    text = "Article I\nSection 1\nThe agency shall retain records. The officer shall retain records."
    ledger = module.compile_constitution(text)["ledger"]
    assert len(captured) == 2
    assert captured[0][2]["actors"] == ["agency"]
    assert captured[1][2]["actors"] == ["officer"]
    assert len(sessions[0].vocabularies) == 2
    assert len({row[1] for row in captured}) == 2
    assert all(row["status"] in {"gap", "non_operative"} for row in ledger["spans"])


def test_existing_receipt_is_refused_before_any_compilation(tmp_path, monkeypatch) -> None:
    module = _module()
    output = tmp_path / "receipt.json"
    output.write_bytes(b"historical receipt\n")

    def forbidden(_):
        raise AssertionError("existing receipt must be refused before compilation")

    monkeypatch.setattr(module, "compile_constitution", forbidden)
    assert module.main(["--compiler-only", "--output", str(output)]) == 2
    assert output.read_bytes() == b"historical receipt\n"


def test_compiler_only_receipt_binds_exact_source_bytes(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    source = tmp_path / "constitution.txt"
    raw = b"Article I\r\nSection 1\r\nThe agency shall retain records.\r\n"
    source.write_bytes(raw)
    output = tmp_path / "new-receipt.json"
    monkeypatch.setattr(autoformal, "compile_span", lambda *_: {
        "compiler_status": "abstain", "reason": "unsupported_fixture", "decompiled": "",
    })
    result = module.main([
        "--compiler-only", "--constitution", str(source), "--output", str(output),
    ])
    assert result == 0
    receipt = json.loads(output.read_text())
    assert receipt["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["formalized"] is False
    assert receipt["admitted"] is False
    assert receipt["roundtrip_ok_count"] == 0
    assert all(row["source_span_id"] for row in receipt["spans"])
    operative = next(row for row in receipt["spans"] if row["status"] == "gap")
    assert operative["compiler_document_id"] == operative["source_span_id"]
    assert receipt["jsonl_written"] is False
    assert receipt["supervisor"]["wrote_compiler"] is False
    board = output.with_name(output.stem + ".todo.md")
    assert board.is_file()
    assert "## AFTD-" in board.read_text(encoding="utf-8")
    assert receipt["supervisor"]["task_count"] >= 1


def test_constitution_schedules_from_huggingface_pointer(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    source = tmp_path / "constitution.txt"
    source.write_text("Article I\nThe agency shall retain records.")
    monkeypatch.setattr(autoformal, "compile_span", lambda *_: {
        "compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": "",
    })
    scheduled = {}

    def fake_schedule(pointer, **kwargs):
        scheduled["pointer"] = Path(pointer)
        scheduled["queue"] = kwargs["queue_path"]
        return {"scheduled_task_ids": ["AFTD-001"], "jsonl_written": False, "task_count": 1}

    monkeypatch.setattr(module, "schedule_packaged_todos", fake_schedule)
    code = module.main([
        "--compiler-only",
        "--constitution", str(source),
        "--output", str(tmp_path / "receipt.json"),
        "--huggingface-package", str(tmp_path / "hf"),
        "--pointer", str(tmp_path / "pointer.json"),
        "--schedule-queue", str(tmp_path / "queue.json"),
    ])
    assert code == 0
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["supervisor"]["scheduled"]["scheduled_task_ids"] == ["AFTD-001"]
    assert scheduled["queue"] == tmp_path / "queue.json"
    assert scheduled["pointer"].is_file()
    assert not list(tmp_path.rglob("*.jsonl"))


def test_constitution_schedule_queue_requires_huggingface_pointer(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    source = tmp_path / "constitution.txt"
    source.write_text("Article I\nThe agency shall retain records.")
    monkeypatch.setattr(autoformal, "compile_span", lambda *_: {
        "compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": "",
    })
    code = module.main([
        "--compiler-only",
        "--constitution", str(source),
        "--output", str(tmp_path / "receipt.json"),
        "--schedule-queue", str(tmp_path / "queue.json"),
    ])
    assert code == 2


def test_strict_gaps_become_supervisor_todos_and_the_router_is_not_imported(tmp_path) -> None:
    import json as json_module

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_router import resolve_gap_with_router

    module = _module()
    source = tmp_path / "constitution.txt"
    source.write_text(
        "Article I\nSection 1\n"
        "The agency shall retain records. "
        "The agency shall send the notice to the requester within 10 days.\n"
    )
    output = tmp_path / "receipt.json"
    queue = tmp_path / "control.duckdb"
    code = module.main([
        "--compiler-only",
        "--constitution", str(source),
        "--output", str(output),
        "--native-queue", str(queue),
    ])
    assert code == 0
    receipt = json_module.loads(output.read_text(encoding="utf-8"))
    assert receipt["formalized"] is False
    assert receipt["admitted"] is False
    assert receipt["supervisor"]["router_called"] is False
    assert receipt["supervisor"]["wrote_compiler"] is False
    assert receipt["supervisor"]["native_task_count"] >= 1
    assert receipt["strict_roundtrip_ok_count"] == 0
    assert receipt["compiler_roundtrip_observed_count"] >= 1
    assert all(row["strict_status"] != "roundtrip_ok" for row in receipt["spans"])
    board = output.with_name(output.stem + ".todo.md").read_text(encoding="utf-8")
    assert "requester" in board
    assert "Formalized: false" in board
    assert "proposed_compiler" not in board
    with DatabaseTaskSource(queue, install_schema=False) as tasks:
        ready = tasks.ready_tasks(limit=10)
    assert ready.tasks
    assert all(task.body.get("board_namespace") == "uscode-autoformal-repair-v1" for task in ready.tasks)

    gap = next(row for row in receipt["spans"] if "recipient" in str(row.get("strict_reason") or ""))
    calls = []

    def generate(prompt, temperature=0, task_kind="legal"):
        calls.append((temperature, task_kind, prompt))
        return json_module.dumps({
            "compiler": "def compile(request):\n    return request\n",
            "parser": "def parse_statute(text):\n    return text\n",
        })

    resolved = resolve_gap_with_router(
        {"text": "The agency shall send the notice to the requester within 10 days.",
         "reason": gap.get("strict_reason") or "compiler_abstain:recipient",
         "source_span_id": gap["source_span_id"], "agrees": False, "decompiled": "",
         "allowed_edit_paths": [
             "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
             "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
         ]},
        generate,
    )
    assert calls and calls[0][0] == 0 and calls[0][1] == "legal"
    assert "Do not replace them" in calls[0][2]
    assert resolved["router_called"] is True
    assert resolved["imported"] is False
    assert resolved["wrote_compiler"] is False
    assert resolved["admitted"] is False
    assert resolved["formalized"] is False
    assert resolved["proposal_sha256"]

    def rejected(prompt, temperature=0, task_kind="legal"):
        return json_module.dumps({
            "compiler": "def compile(request):\n    eval('request')\n",
            "parser": "def parse_statute(text):\n    return text\n",
        })

    blocked = resolve_gap_with_router(
        {"text": "The agency shall send the notice to the requester.", "reason": "compiler_abstain:recipient",
         "agrees": False,
         "allowed_edit_paths": [
             "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
             "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
         ]},
        rejected,
    )
    assert blocked["router_called"] is True
    assert blocked["proposal_sha256"] == ""
    assert blocked["reason"] == "forbidden_call"
    assert blocked["imported"] is False

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

    def supervised(prompt, temperature=0, task_kind="legal"):
        assert temperature == 0 and task_kind == "legal"
        assert "Do not replace them" in prompt
        return json_module.dumps({
            "compiler": "def compile(request):\n    return request\n",
            "parser": "def parse_statute(text):\n    return text\n",
        })

    launcher_path = (
        Path(__file__).resolve().parents[3]
        / "scripts" / "ops" / "legal_ir" / "run_autoformal_supervisor.py"
    )
    spec = importlib.util.spec_from_file_location("autoformal_supervisor_under_test", launcher_path)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    with DatabaseTaskSource(queue, install_schema=False) as tasks:
        proposed = launcher.propose_ready_gap(
            tasks, tmp_path, supervised, probe=lambda *_args, **_kwargs: {"passed": True},
        )
    assert proposed["preflight_passed"] is True
    assert proposed["router_called"] is True
    assert proposed["imported"] is False
    assert proposed["wrote_compiler"] is False
    assert proposed["admitted"] is False
    assert proposed["formalized"] is False
    assert proposed["proposal_sha256"]


def test_receipt_creation_cannot_overwrite_a_racing_writer(tmp_path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal
    import pytest

    module = _module()
    source = tmp_path / "constitution.txt"
    source.write_text("Article I\nThe agency shall retain records.")
    output = tmp_path / "receipt.json"

    def compile_one(*_):
        output.write_bytes(b"another writer\n")
        return {"compiler_status": "abstain", "reason": "unsupported_fixture", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    with pytest.raises(FileExistsError):
        module.main(["--compiler-only", "--constitution", str(source), "--output", str(output)])
    assert output.read_bytes() == b"another writer\n"


def test_end_to_end_constitution_packages_gaps_and_schedules(tmp_path: Path) -> None:
    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.persistent_task_queue")
    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.huggingface_todo_locator")
    from ipfs_accelerate_py.agent_supervisor.task_sources.persistent_task_queue import (
        PersistentTaskQueue,
    )
    from ipfs_datasets_py.logic.autoformal.huggingface_schedule import schedule_from_pointer
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

    module = _module()
    source = tmp_path / "constitution.txt"
    source.write_text(
        "Article I\n"
        "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.\n"
    )
    output = tmp_path / "receipt.json"
    code = module.main([
        "--compiler-only",
        "--constitution", str(source),
        "--output", str(output),
        "--huggingface-package", str(tmp_path / "hf"),
        "--pointer", str(tmp_path / "pointer.json"),
        "--board", str(tmp_path / "constitution.todo.md"),
    ])
    assert code == 0
    receipt = json.loads(output.read_text())
    assert receipt["formalized"] is False
    assert receipt["jsonl_written"] is False
    assert receipt["supervisor"]["task_count"] >= 1
    board = Path(receipt["supervisor"]["board_path"])
    validate_supervisor_board(board.read_text(encoding="utf-8"))
    assert (tmp_path / "pointer.json").is_file()
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
