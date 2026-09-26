"""U.S. Code sparse GraphRAG runner queues supervisor todos, not compiler edits."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "legal_ir"
        / "run_uscode_on_sparse_graphrag.py"
    )
    spec = importlib.util.spec_from_file_location("run_uscode_on_sparse_graphrag_under_test", path)
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
            {"status": "uncompiled"},
        ]
    )
    assert summary["compiled_count"] == 1
    assert summary["gap_count"] == 1
    assert summary["formalized"] is False
    assert summary["admitted"] is False


def test_agreement_from_ledger_keeps_identity_and_does_not_admit() -> None:
    module = _module()
    agreement = module.agreement_from_ledger(
        {
            "spans": [
                {
                    "id": "usc:us:5:552.span-1",
                    "source_span_id": "uscode-span-1",
                    "legal_id": "usc:us:5:552",
                    "entry_cid": "cid-1",
                    "status": "gap",
                    "reason": "no_parser_elements",
                    "text": "Each agency shall make records available.",
                },
                {
                    "id": "usc:us:5:552.span-2",
                    "status": "compiled",
                    "text": "The agency may withhold secrets.",
                    "decompiled": "The agency may withhold secrets.",
                },
            ]
        }
    )
    assert agreement["agrees"] is False
    assert agreement["admitted"] is False
    assert agreement["formalized"] is False
    assert agreement["agreed"] == 1
    assert agreement["rows"][0]["legal_id"] == "usc:us:5:552"
    assert agreement["rows"][0]["reason"] == "no_parser_elements"


def test_run_uscode_autoformal_retrieves_via_searcher(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    hits = [
        {
            "entry_cid": "cid-1",
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "text": "Each agency shall make records available.",
        }
    ]
    receipt = module.run_uscode_autoformal(
        searcher=lambda query, **kwargs: hits,
        query="FOIA",
        board_path=tmp_path / "board.md",
        skip_upload=True,
    )
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["task_count"] == 1
    assert receipt["hits"][0]["section"] == "552"
    assert (tmp_path / "board.md").is_file()


def test_run_uscode_autoformal_enqueues_native_supervisor_tasks(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from ipfs_datasets_py.logic import autoformal

    module = _module()

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)

    class FakeTaskSource:
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

    source = FakeTaskSource()
    receipt = module.run_uscode_autoformal(
        hits=[
            {
                "entry_cid": "cid-1",
                "legal_id": "usc:us:5:552",
                "title": "5",
                "section": "552",
                "text": "Each agency shall make records available.",
            }
        ],
        query="FOIA",
        release_id="release-v1",
        board_path=tmp_path / "board.md",
        skip_upload=True,
        task_source=source,
        packet_directory=tmp_path / "packets",
        code_identity="compiler-tree-1",
        model_identity="checkpoint-1",
    )
    assert receipt["authority"] == "accelerate-duckdb"
    assert receipt["native_queue"]["jsonl_written"] is False
    assert receipt["native_queue"]["task_count"] == 1
    assert len(source.materialized) == 1
    task = source.materialized[0]["tasks"][0]
    assert "Preserve" in task["body_markdown"] or "preserve" in str(task.get("preserve") or "").lower()
    assert task["estimated_tokens"] > 0
    assert (tmp_path / "packets").is_dir()


def test_run_uscode_autoformal_writes_huggingface_pointer(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from ipfs_datasets_py.logic import autoformal

    module = _module()

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    pointer = tmp_path / "latest-pointer.json"
    receipt = module.run_uscode_autoformal(
        hits=[
            {
                "entry_cid": "cid-1",
                "legal_id": "usc:us:5:552",
                "title": "5",
                "section": "552",
                "text": "Each agency shall make records available.",
            }
        ],
        query="FOIA",
        board_path=tmp_path / "board.md",
        huggingface_package=tmp_path / "hf",
        pointer_path=pointer,
        publisher=SimpleNamespace(
            plan_dry_run=lambda manifest, **kwargs: SimpleNamespace(plan_digest="a" * 64)
        ),
        dry_run=True,
    )
    assert pointer.is_file()
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert payload["schema"] == "ipfs_datasets_py/autoformal-todo-release-pointer/v1"
    assert payload["jsonl_written"] is False
    assert receipt["huggingface"]["pointer"]["locator_path"].endswith("locator.json")


def test_cli_retrieves_with_injected_searcher_when_hits_are_omitted(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    hits = [
        {
            "entry_cid": "cid-1",
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "text": "Each agency shall make records available.",
        }
    ]
    code = module.main(
        [
            "--query",
            "FOIA",
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--skip-upload",
        ],
        searcher=lambda query, **kwargs: hits,
    )
    assert code == 0
    assert (tmp_path / "board.md").is_file()
    assert not list(tmp_path.glob("*.jsonl"))


def test_cli_end_to_end_query_against_pinned_local_release(tmp_path: Path) -> None:
    import importlib.util

    remote = Path(__file__).resolve().parents[1] / "retrieval/hf_graphrag/test_remote_search.py"
    spec = importlib.util.spec_from_file_location("hf_graphrag_cli_fixture", remote)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    release = tmp_path / "release"
    release.mkdir()
    fixture.build_mini_release(release)
    module = _module()
    code = module.main(
        [
            "--query",
            "foia agency",
            "--graphrag-root",
            str(release),
            "--graphrag-repo-id",
            fixture.REPO_ID,
            "--graphrag-revision",
            fixture.PINNED_REVISION,
            "--graphrag-cache",
            str(tmp_path / "cache"),
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--skip-upload",
        ]
    )
    assert code == 0
    assert not list(tmp_path.rglob("*.jsonl"))
    board = tmp_path / "board.md"
    if board.is_file():
        from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

        validate_supervisor_board(board.read_text(encoding="utf-8"))


def test_end_to_end_sparse_graphrag_retrieval_feeds_autoformal(tmp_path: Path) -> None:
    import importlib.util

    from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
        local_sparse_graphrag_searcher,
        retrieve_uscode_hits,
    )

    remote = Path(__file__).resolve().parents[1] / "retrieval/hf_graphrag/test_remote_search.py"
    spec = importlib.util.spec_from_file_location("hf_graphrag_remote_search_fixture", remote)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    release = tmp_path / "release"
    release.mkdir()
    fixture.build_mini_release(release)
    searcher = local_sparse_graphrag_searcher(
        release,
        repo_id=fixture.REPO_ID,
        revision=fixture.PINNED_REVISION,
        cache_dir=tmp_path / "cache",
    )
    hits = retrieve_uscode_hits(searcher, "foia agency", top_k=5)
    assert hits
    assert all(hit["retrieval_method"] == "sparse_bm25" for hit in hits)
    assert {hit["section"] for hit in hits} <= {"552", "552a"}
    module = _module()
    receipt = module.run_uscode_autoformal(
        hits=hits,
        query="foia agency",
        board_path=tmp_path / "board.md",
        skip_upload=True,
    )
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["formalized"] is False
    assert receipt["summary"]["span_count"] >= 1
    if receipt["task_count"]:
        from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

        validate_supervisor_board((tmp_path / "board.md").read_text(encoding="utf-8"))


def test_cli_without_hits_or_searcher_is_refused(tmp_path: Path) -> None:
    module = _module()
    assert module.main(["--query", "FOIA", "--board", str(tmp_path / "board.md"), "--skip-upload"]) == 2


def test_cli_query_with_graphrag_root_builds_local_searcher(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal
    from ipfs_datasets_py.logic.autoformal import uscode_ingest

    module = _module()

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    seen = {}

    def fake_pinned(*, repo_id, revision, release_root=None, cache_dir=None):
        seen["root"] = Path(release_root) if release_root is not None else None
        seen["revision"] = revision
        seen["repo_id"] = repo_id
        return lambda query, **kwargs: [
            {
                "entry_cid": "cid-1",
                "legal_id": "usc:us:5:552",
                "title": "5",
                "section": "552",
                "text": "Each agency shall make records available.",
            }
        ]

    monkeypatch.setattr(uscode_ingest, "pinned_sparse_graphrag_searcher", fake_pinned)
    (tmp_path / "release").mkdir()
    code = module.main(
        [
            "--query",
            "FOIA",
            "--graphrag-root",
            str(tmp_path / "release"),
            "--graphrag-revision",
            "b" * 40,
            "--board",
            str(tmp_path / "board.md"),
            "--skip-upload",
            "--huggingface-package",
            str(tmp_path / "hf"),
        ]
    )
    assert code == 0
    assert seen["revision"] == "b" * 40
    assert seen["root"] == tmp_path / "release"
    assert (tmp_path / "board.md").is_file()


def test_cli_query_without_local_root_uses_hub_revision(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal
    from ipfs_datasets_py.logic.autoformal import uscode_ingest

    module = _module()
    monkeypatch.setattr(autoformal, "compile_span", lambda *_: {
        "compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": "",
    })
    seen = {}

    def fake_pinned(*, repo_id, revision, release_root=None, cache_dir=None):
        seen["release_root"] = release_root
        seen["revision"] = revision
        return lambda query, **kwargs: [
            {
                "entry_cid": "cid-1",
                "legal_id": "usc:us:5:552",
                "title": "5",
                "section": "552",
                "text": "Each agency shall make records available.",
            }
        ]

    monkeypatch.setattr(uscode_ingest, "pinned_sparse_graphrag_searcher", fake_pinned)
    code = module.main(
        [
            "--query",
            "FOIA",
            "--graphrag-revision",
            "d" * 40,
            "--board",
            str(tmp_path / "board.md"),
            "--skip-upload",
            "--huggingface-package",
            str(tmp_path / "hf"),
        ]
    )
    assert code == 0
    assert seen["release_root"] is None
    assert seen["revision"] == "d" * 40
    assert (tmp_path / "board.md").is_file()


def test_runner_writes_supervisor_board_instead_of_jsonl(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()
    hits_path = tmp_path / "hits.json"
    hits_path.write_text(
        json.dumps(
            [
                {
                    "entry_cid": "cid-1",
                    "legal_id": "usc:us:5:552",
                    "title": "5",
                    "section": "552",
                    "text": "Each agency shall make records available.",
                }
            ]
        ),
        encoding="utf-8",
    )

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    board = tmp_path / "board.md"
    package = tmp_path / "hf"
    code = module.main(
        [
            "--hits",
            str(hits_path),
            "--query",
            "FOIA",
            "--board",
            str(board),
            "--huggingface-package",
            str(package),
            "--skip-upload",
        ]
    )
    assert code == 0
    assert board.is_file()
    markdown = board.read_text(encoding="utf-8")
    assert "## AFTD-" in markdown
    assert "- Preserve:" in markdown
    assert "- Replace:" in markdown
    assert not list(tmp_path.glob("*.jsonl"))
    assert not (tmp_path / "proposed_compiler.py").exists()


def test_schedule_from_pointer_registers_time_budget_without_jsonl(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "schedule_uscode_autoformal_todos_under_test",
        Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/schedule_uscode_autoformal_todos.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pointer = tmp_path / "pointer.json"
    pointer.write_text("{}", encoding="utf-8")
    seen = {}

    def locate(source, **kwargs):
        from ipfs_datasets_py.logic.autoformal.supervisor_todo import (
            discrepancy_tasks,
            render_supervisor_board,
        )

        seen["source"] = Path(source)
        seen["max_tokens"] = kwargs.get("max_tokens")
        seen["queue"] = kwargs.get("queue")
        board = Path(kwargs["board_destination"])
        board.write_text(
            render_supervisor_board(
                discrepancy_tasks(
                    {
                        "agrees": False,
                        "rows": [
                            {
                                "id": "usc:us:5:552.span-1",
                                "text": "Each agency shall make records available.",
                                "reason": "no_parser_elements",
                                "agrees": False,
                                "skipped": False,
                            }
                        ],
                    }
                )
            ),
            encoding="utf-8",
        )
        return {
            "board_path": str(board),
            "dataset_repo_id": "justicedao/uscode-autoformal-todos",
            "enqueued_task_ids": ["AFTD-001"],
            "scheduled_task_ids": ["AFTD-001"],
            "task_count": 1,
            "time_management": {"total_estimated_tokens": 12000},
        }

    class Queue:
        def __init__(self):
            self.saved = False

        def save(self):
            self.saved = True

    queue = Queue()
    receipt = module.schedule_from_pointer(
        pointer,
        repo_root=tmp_path,
        board=tmp_path / "board.md",
        queue_path=tmp_path / "queue.json",
        max_tokens=15000,
        locate=locate,
        queue=queue,
    )
    assert seen["source"] == pointer
    assert seen["max_tokens"] == 15000
    assert queue.saved is True
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["scheduled_task_ids"] == ["AFTD-001"]
    assert receipt["time_management"]["total_estimated_tokens"] == 12000


def test_ingest_cli_schedules_from_huggingface_pointer(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.logic import autoformal

    module = _module()

    def compile_one(_session, text, document_id):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    monkeypatch.setattr(autoformal, "compile_span", compile_one)
    scheduled = {}

    def fake_schedule(pointer, **kwargs):
        scheduled["pointer"] = Path(pointer)
        scheduled["queue"] = kwargs["queue_path"]
        return {"scheduled_task_ids": ["AFTD-001"], "jsonl_written": False, "task_count": 1}

    monkeypatch.setattr(module, "schedule_packaged_todos", fake_schedule)
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "entry_cid": "cid-1",
                    "legal_id": "usc:us:5:552",
                    "title": "5",
                    "section": "552",
                    "text": "Each agency shall make records available.",
                }
            ]
        ),
        encoding="utf-8",
    )
    code = module.main(
        [
            "--hits",
            str(hits),
            "--query",
            "FOIA",
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--schedule-queue",
            str(tmp_path / "queue.json"),
        ]
    )
    assert code == 0
    assert scheduled["queue"] == tmp_path / "queue.json"
    assert scheduled["pointer"].is_file()
    assert not list(tmp_path.rglob("*.jsonl"))


def test_cli_hits_packages_and_schedules_with_real_compiler(tmp_path: Path) -> None:
    import pytest

    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.persistent_task_queue")
    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.huggingface_todo_locator")
    from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

    module = _module()
    hits = tmp_path / "hits.json"
    hits.write_text(
        json.dumps(
            [
                {
                    "entry_cid": "bafkreiabc",
                    "legal_id": "usc:us:5:552",
                    "title": "5",
                    "section": "552",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                }
            ]
        ),
        encoding="utf-8",
    )
    code = module.main(
        [
            "--hits",
            str(hits),
            "--query",
            "agency records",
            "--release-id",
            "cli-e2e-v1",
            "--board",
            str(tmp_path / "board.md"),
            "--huggingface-package",
            str(tmp_path / "hf"),
            "--pointer",
            str(tmp_path / "pointer.json"),
            "--schedule-queue",
            str(tmp_path / "queue.json"),
            "--max-tokens",
            "50000",
        ]
    )
    assert code == 0
    assert (tmp_path / "board.md").is_file()
    validate_supervisor_board((tmp_path / "board.md").read_text(encoding="utf-8"))
    assert (tmp_path / "pointer.json").is_file()
    assert (tmp_path / "hf" / "todos.parquet").is_file()
    assert (tmp_path / "queue.json").is_file()
    assert not list(tmp_path.rglob("*.jsonl"))


def test_cli_graphrag_query_packages_when_there_are_gaps(tmp_path: Path) -> None:
    import importlib.util
    import pytest

    pytest.importorskip("ipfs_accelerate_py.agent_supervisor.task_sources.huggingface_todo_locator")
    remote = Path(__file__).resolve().parents[1] / "retrieval/hf_graphrag/test_remote_search.py"
    spec = importlib.util.spec_from_file_location("hf_graphrag_cli_package_fixture", remote)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    release = tmp_path / "release"
    release.mkdir()
    fixture.build_mini_release(release)
    module = _module()
    args = [
        "--query",
        "foia agency",
        "--graphrag-root",
        str(release),
        "--graphrag-repo-id",
        fixture.REPO_ID,
        "--graphrag-revision",
        fixture.PINNED_REVISION,
        "--graphrag-cache",
        str(tmp_path / "cache"),
        "--release-id",
        "cli-graphrag-e2e-v1",
        "--board",
        str(tmp_path / "board.md"),
        "--huggingface-package",
        str(tmp_path / "hf"),
        "--pointer",
        str(tmp_path / "pointer.json"),
    ]
    if (tmp_path / "board.md").exists():
        raise AssertionError("board must not exist before CLI")
    code = module.main(args)
    assert code == 0
    assert not list(tmp_path.rglob("*.jsonl"))
    board = tmp_path / "board.md"
    if board.is_file():
        from ipfs_datasets_py.logic.autoformal.supervisor_todo import validate_supervisor_board

        validate_supervisor_board(board.read_text(encoding="utf-8"))
        assert (tmp_path / "pointer.json").is_file()
        assert (tmp_path / "hf" / "todos.parquet").is_file()
