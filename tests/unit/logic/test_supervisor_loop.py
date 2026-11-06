"""Supervisor loop converts errors to todos/goals and recurses without admitting."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
    OBJECTIVE_ID,
    POPULATION_SCHEMA,
    SupervisorLoopError,
    agreement_from_run,
    ingest_population,
    loop_progress_report,
    proofs_from_agreement,
    resolve_goals,
    run_supervisor_loop,
    spawn_goal_tree,
    supervisor_population,
    synthesize_goals,
    write_population_receipt,
    load_population_receipt,
    recensus_open_todos,
    write_census_snapshot,
)
from ipfs_datasets_py.logic.autoformal.supervisor_todo import (
    discrepancy_tasks,
    render_supervisor_board,
    validate_supervisor_board,
)


def _gap(span_id: str, *, reason: str = "no_parser_elements", legal_id: str = "usc:us:5:552") -> dict:
    return {
        "agrees": False,
        "id": span_id,
        "legal_id": legal_id,
        "reason": reason,
        "skipped": False,
        "source_span_id": span_id,
        "text": "Each agency shall make records available.",
    }


def test_agreement_from_run_reads_spans_and_does_not_admit() -> None:
    agreement = agreement_from_run(
        {
            "spans": [
                {"id": "a", "status": "gap", "reason": "compiler_abstain", "text": "x", "source_span_id": "a"},
                {"id": "b", "status": "compiled", "text": "Company A shall submit backup report within 10 days unless emergency.", "source_span_id": "b"},
            ]
        }
    )
    assert agreement["admitted"] is False
    assert agreement["formalized"] is False
    assert any(not row["agrees"] for row in agreement["rows"])


def test_proofs_are_roundtrips_not_legal_admits() -> None:
    proofs = proofs_from_agreement(
        {"rows": [{"agrees": True, "id": "ok", "source_span_id": "ok", "skipped": False}]}
    )
    assert proofs == [
        {
            "admitted": False,
            "formalized": False,
            "id": "ok",
            "kind": "strict_roundtrip",
            "proof_authoritative": False,
            "source_span_id": "ok",
        }
    ]


def test_related_parser_gaps_become_an_architecture_goal() -> None:
    tasks = discrepancy_tasks({"rows": [_gap("s1"), _gap("s2"), {"agrees": True, "id": "ok", "skipped": False}]})
    labeled, goals = synthesize_goals(tasks)
    assert len(goals) == 1
    assert goals[0]["kind"] == "architecture-decision"
    assert goals[0]["failure_mode"] == "no_parser_elements"
    assert set(goals[0]["resolves"]) == {item["task_id"] for item in labeled}
    assert all(item["goal_id"] == goals[0]["goal_id"] for item in labeled)
    markdown = render_supervisor_board(labeled, goals=goals)
    validate_supervisor_board(markdown)
    assert "- Kind: architecture-decision" in markdown
    assert "- Resolves:" in markdown


def test_router_prompt_names_the_approved_stage_or_refuses_to_guess() -> None:
    from ipfs_datasets_py.logic.autoformal.supervisor_router import router_prompt

    named = router_prompt(
        {
            "allowed_edit_paths": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
            "preserve": ["deterministic compiler for compiled spans"],
            "reason": "compiler_abstain:recipient",
            "replace": ["unsupported field handling"],
            "text": "The Senate shall send the notice to the requester.",
        }
    )
    assert "deontic_parser.py" in named
    assert "Edit only the existing files" in named
    assert "Do not replace them" in named
    assert "unsupported field handling" in named
    unnamed = router_prompt({"reason": "compiler_abstain", "text": "The Senate shall try impeachments."})
    assert "No approved edit path is recorded" in unnamed
    assert "Do not guess" in unnamed
    from ipfs_datasets_py.logic.autoformal.supervisor_router import resolve_gap_with_router

    calls = []

    def generate(prompt, temperature=0, task_kind="legal"):
        calls.append(prompt)
        return json.dumps({"parser": "def parse_statute(text):\n    return text\n"})

    accepted = resolve_gap_with_router(
        {
            "agrees": False,
            "allowed_edit_paths": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
            "text": "The Senate shall send the notice to the requester.",
        },
        generate,
    )
    assert accepted["router_called"] is True
    assert accepted["proposal_sha256"]
    assert accepted["proposal_keys"] == ["parser"]
    assert accepted["admitted"] is False
    rejected = resolve_gap_with_router(
        {
            "agrees": False,
            "allowed_edit_paths": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
            "text": "The Senate shall send the notice to the requester.",
        },
        lambda prompt, temperature=0, task_kind="legal": json.dumps({
            "decompiler": "def decompile(rule):\n    return ''\n",
        }),
    )
    assert rejected["reason"] == "decompiler_not_in_scope"
    kept = resolve_gap_with_router(
        {
            "agrees": False,
            "allowed_edit_paths": ["ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"],
            "text": "The Senate shall send the notice to the requester.",
        },
        lambda prompt, temperature=0, task_kind="legal": (
            "```json\n"
            + json.dumps({
                "parser": "```python\ndef parse_statute(text):\n    return text\n```",
                "decompiler": "def decompile(rule):\n    return ''\n",
            })
            + "\n```"
        ),
    )
    assert kept["reason"] == ""
    assert kept["proposal_keys"] == ["parser"]
    assert kept["proposal_sha256"]
    assert rejected["proposal_sha256"] == ""
    skipped = resolve_gap_with_router(
        {"agrees": False, "text": "The Senate shall send the notice to the requester."},
        lambda prompt, temperature=0, task_kind="legal": (_ for _ in ()).throw(AssertionError("called")),
    )
    assert skipped["router_called"] is False
    assert skipped["reason"] == "no_approved_edit_path"
    assert len(calls) == 1


def test_constitution_spans_without_citations_become_subgoals() -> None:
    tasks = discrepancy_tasks(
        {
            "rows": [
                _gap("art-1", legal_id=""),
                _gap("art-2", legal_id=""),
            ]
        }
    )
    tree = spawn_goal_tree(
        tasks,
        release_id="us-constitution",
        campaign_title="US Constitution autoformal campaign",
    )
    assert tree["goals"][0]["title"] == "US Constitution autoformal campaign"
    assert tree["goals"][0]["kind"] == "campaign"
    assert tree["goals"][0]["admitted"] is False
    assert tree["goals"][0]["formalized"] is False
    subgoals = [goal for goal in tree["goals"] if goal["kind"] == "subgoal"]
    assert {tuple(goal["source_span_ids"]) for goal in subgoals} == {("art-1",), ("art-2",)}
    assert all("no_parser_elements" in goal["title"] for goal in subgoals)
    assert all(any("parser" in target for target in goal["repair_targets"]) for goal in subgoals)
    parents = {goal["parent_goal_cid"] for goal in subgoals}
    assert len(parents) == 1
    assert parents <= {goal["goal_cid"] for goal in tree["goals"] if goal["kind"] == "architecture-decision"}
    assert {task["goal_cid"] for task in tree["tasks"]} == {goal["goal_cid"] for goal in subgoals}
    assert all(task["admitted"] is False and task["formalized"] is False for task in tree["tasks"])


def _assert_claim_skips_parked_goal(tmp_path: Path, open_task_cid: str) -> None:
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_args
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon_runner import (
        build_database_implementation_daemon_from_args,
    )
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import NAMESPACE

    parsed = parse_args([
        "--todo-path", str(tmp_path / "control.duckdb"),
        "--state-dir", str(tmp_path / "state"),
        "--state-prefix", "parked-goal",
        "--authority-mode", "embedded",
        "--task-source-kind", "duckdb",
        "--board-namespace", NAMESPACE,
        "--state-store-id", "parked-goal",
        "--state-failover-policy", "fail_closed",
        "--max-task-attempts", "3",
    ])
    daemon = build_database_implementation_daemon_from_args(parsed)
    try:
        claim = daemon.claim_next()
        assert claim is not None
        assert claim.task_cid == open_task_cid
    finally:
        daemon.close()


def _assert_no_claim_when_goals_are_inconclusive(tmp_path: Path) -> None:
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_args
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon_runner import (
        build_database_implementation_daemon_from_args,
    )
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import NAMESPACE

    parsed = parse_args([
        "--todo-path", str(tmp_path / "control.duckdb"),
        "--state-dir", str(tmp_path / "state-parked"),
        "--state-prefix", "all-parked",
        "--authority-mode", "embedded",
        "--task-source-kind", "duckdb",
        "--board-namespace", NAMESPACE,
        "--state-store-id", "all-parked",
        "--state-failover-policy", "fail_closed",
        "--max-task-attempts", "3",
    ])
    daemon = build_database_implementation_daemon_from_args(parsed)
    try:
        assert daemon.claim_next() is None
        withdrawal = dict(daemon._last_claim_withdrawal)
    finally:
        daemon.close()
    assert withdrawal["reason"] == "goals_inconclusive"
    assert withdrawal["claim_state"] == "not_claimed"
    assert withdrawal["admitted"] is False
    assert withdrawal["formalized"] is False
    assert withdrawal["task_cids"]
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
        claim_block_for_inconclusive_goals,
    )
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import (
        DatabaseTaskSource,
    )

    with DatabaseTaskSource(tmp_path / "control.duckdb", install_schema=False) as source:
        blocked = claim_block_for_inconclusive_goals(source)
    assert blocked["claim_blocked_reason"] == "goals_inconclusive"
    assert blocked["admitted"] is False
    assert blocked["formalized"] is False
    assert blocked["claim_blocked_task_cids"] == withdrawal["task_cids"]
    assert blocked["claimable_ready_task_cids"] == []


def test_sealed_todos_link_to_constitution_span_subgoals(tmp_path: Path) -> None:
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import attach_goal_tree
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import enqueue_repairs, repair_packets

    agreement = {
        "rows": [
            {
                "agrees": False,
                "id": "art-1",
                "reason": "compiler_abstain:recipient",
                "skipped": False,
                "source_span_id": "art-1",
                "text": "The Senate shall send the notice to the requester.",
            },
            {
                "agrees": False,
                "id": "art-2",
                "reason": "strict_roundtrip_failed",
                "skipped": False,
                "source_span_id": "art-2",
                "text": "The House shall keep a journal.",
            },
        ]
    }
    packets = repair_packets(
        agreement,
        release_id="us-constitution",
        code_identity="constitution-strict-compiler",
        model_identity="router-not-yet-called",
        query="US Constitution",
    )
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        enqueue_repairs(source, packets, packet_directory=tmp_path / "packets")
        attached = attach_goal_tree(
            source,
            agreement,
            release_id="us-constitution",
            campaign_title="US Constitution autoformal campaign",
        )
        assert attached["admitted"] is False
        assert attached["formalized"] is False
        assert attached["router_called"] is False
        assert attached["wrote_compiler"] is False
        assert attached["subgoal_count"] == 2
        assert attached["linked_tasks"] == 2
        tasks = source.list_tasks(limit=10).tasks
        assert len(tasks) == 2
        assert len({task.goal_cid for task in tasks}) == 2
        assert all(str(task.goal_cid).startswith("goal:") for task in tasks)
        assert all(task.body.get("packet_sha256") for task in tasks)
        assert all(task.status == "ready" for task in tasks)
        assert source.snapshot().to_dict()["goal_count"] >= 4
        from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
            goal_status_counts,
            mark_span_subgoal_review,
        )

        before = goal_status_counts(source)
        ready_before = {
            item["goal_cid"]: item["ready_task_cids"] for item in before["open_goals"]
        }
        assert tasks[0].task_cid in ready_before[tasks[0].goal_cid]
        assert tasks[1].task_cid in ready_before[tasks[1].goal_cid]
        marked = mark_span_subgoal_review(
            source, tasks[0].task_cid, "abc123", ["parser"],
        )
        assert marked["updated"] is True
        assert marked["goal_status"] == "analysis_inconclusive"
        assert marked["proposal_keys"] == ["parser"]
        assert marked["admitted"] is False
        assert marked["formalized"] is False
        held = source._intent.get_goal(tasks[0].goal_cid)
        other = source._intent.get_goal(tasks[1].goal_cid)
        campaign_rows = [
            source._intent.get_goal(goal_cid)
            for goal_cid in {held["parent_goal_cid"], other["parent_goal_cid"]}
        ]
        assert held["status"] == "analysis_inconclusive"
        assert held["body"]["completion_receipt"]["admitted"] is False
        assert held["body"]["completion_receipt"]["proposal_keys"] == ["parser"]
        assert other["status"] == "open"
        assert marked["rolled_up"] == []
        assert all(goal["status"] == "open" for goal in campaign_rows)
        from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
            ready_task_cids_under_inconclusive_goals,
        )

        skipped = ready_task_cids_under_inconclusive_goals(source)
        assert tasks[0].task_cid in skipped
        assert tasks[1].task_cid not in skipped
        import importlib.util

        launcher_path = (
            Path(__file__).resolve().parents[3]
            / "scripts" / "ops" / "legal_ir" / "run_autoformal_supervisor.py"
        )
        spec = importlib.util.spec_from_file_location("autoformal_supervisor_preflight", launcher_path)
        assert spec is not None and spec.loader is not None
        supervisor_launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor_launch)
        preflight = supervisor_launch.preflight_next_repair(
            source, tmp_path, probe=lambda *_args, **_kwargs: {"passed": True},
        )
        assert preflight["eligible"] is True
        assert preflight["task_cid"] == tasks[1].task_cid
        assert preflight["claim_blocked_reason"] == ""
        assert preflight["admitted"] is False
        assert preflight["formalized"] is False
        assert preflight["tasks_claimed"] is False
        calls: list[str] = []

        def generate(prompt, temperature=0, task_kind="legal"):
            calls.append(prompt)
            return json.dumps({"parser": "def parse_statute(text):\n    return text\n"})

        proposed = supervisor_launch.propose_ready_gap(
            source, tmp_path, generate, probe=lambda *_args, **_kwargs: {"passed": True},
        )
        assert len(calls) == 1
        assert proposed["router_called"] is True
        assert proposed["preflight_passed"] is True
        assert proposed["task_id"] == tasks[1].task_alias
        assert proposed["admitted"] is False
        assert proposed["formalized"] is False
        assert proposed["imported"] is False
        assert proposed["wrote_compiler"] is False

        def refuse_repeat(*_args, **_kwargs):
            raise AssertionError("router called again for the same proposal")

        repeated = supervisor_launch.propose_ready_gap(
            source, tmp_path, refuse_repeat, probe=lambda *_args, **_kwargs: {"passed": True},
        )
        assert repeated["router_called"] is False
        assert repeated["reason"] == "proposal_already_recorded"
        assert repeated["proposal_sha256"] == proposed["proposal_sha256"]
        assert repeated["proposal_keys"] == proposed["proposal_keys"]
        assert repeated["admitted"] is False
        assert repeated["formalized"] is False
        assert repeated["imported"] is False
        assert source.get(tasks[1].task_cid).status == "ready"
        _assert_claim_skips_parked_goal(tmp_path, tasks[1].task_cid)
        both = mark_span_subgoal_review(
            source, tasks[1].task_cid, "def456", ["compiler"],
        )
        parent = source._intent.get_goal(held["parent_goal_cid"])
        assert both["admitted"] is False
        assert both["formalized"] is False
        assert parent["goal_cid"] in both["rolled_up"]
        assert parent["status"] == "analysis_inconclusive"
        assert parent["status"] != "verified_complete"
        assert set(parent["body"]["completion_receipt"]["proposal_keys"]) == {"compiler", "parser"}
        assert parent["body"]["completion_receipt"]["admitted"] is False
        from ipfs_datasets_py.logic.autoformal.supervisor_loop import goal_status_counts

        summary = goal_status_counts(source)
        assert summary["admitted"] is False
        assert summary["formalized"] is False
        assert summary["verified_complete_count"] == 0
        assert summary["inconclusive_goal_count"] >= 3
        assert summary["goal_status_counts"]["analysis_inconclusive"] == summary["inconclusive_goal_count"]
        named = {item["goal_cid"]: item for item in summary["inconclusive_goals"]}
        assert held["goal_cid"] in named
        assert parent["goal_cid"] in named
        assert named[held["goal_cid"]]["kind"] == "subgoal"
        assert named[held["goal_cid"]]["proposal_keys"] == ["parser"]
        assert named[parent["goal_cid"]]["proposal_keys"] == ["compiler", "parser"]
        assert all(item["status"] == "analysis_inconclusive" for item in named.values())
        assert all(item["admitted"] is False and item["formalized"] is False for item in named.values())
        open_ids = {item["goal_cid"] for item in summary["open_goals"]}
        assert held["goal_cid"] not in open_ids
        assert parent["goal_cid"] not in open_ids
        claimable = [
            task_cid
            for item in summary["open_goals"]
            for task_cid in item["ready_task_cids"]
        ]
        assert tasks[0].task_cid not in claimable
        assert tasks[1].task_cid not in claimable
        assert all(item["status"] == "open" for item in summary["open_goals"])
        assert all(item["admitted"] is False for item in summary["open_goals"])
        refused = supervisor_launch.preflight_next_repair(
            source, tmp_path, probe=lambda *_args, **_kwargs: {"passed": True},
        )
        assert refused["eligible"] is False
        assert refused["claim_blocked_reason"] == "goals_inconclusive"
        assert refused["passed"] is None
        assert refused["tasks_claimed"] is False
        assert refused["admitted"] is False
        assert refused["formalized"] is False

        def refuse_generate(*_args, **_kwargs):
            raise AssertionError("router called for a parked goal")

        parked_proposal = supervisor_launch.propose_ready_gap(
            source, tmp_path, refuse_generate, probe=lambda *_args, **_kwargs: {"passed": True},
        )
        assert parked_proposal["router_called"] is False
        assert parked_proposal["reason"] == "goals_inconclusive"
        assert parked_proposal["preflight_passed"] is False
        assert parked_proposal["admitted"] is False
        assert parked_proposal["formalized"] is False
        assert parked_proposal["imported"] is False
        _assert_no_claim_when_goals_are_inconclusive(tmp_path)


def test_spawn_goal_tree_emits_duckdb_population_semantics() -> None:
    tasks = discrepancy_tasks(
        {
            "rows": [
                _gap("s1", legal_id="usc:us:18:1001"),
                _gap("s2", legal_id="usc:us:18:1519"),
            ]
        }
    )
    tree = spawn_goal_tree(tasks, release_id="rel-1")
    kinds = {goal["kind"] for goal in tree["goals"]}
    assert "campaign" in kinds
    assert "architecture-decision" in kinds
    assert "subgoal" in kinds
    assert tree["goal_edges"]
    assert all(edge.get("edge_kind") == "goal_decomposition" for edge in tree["goal_edges"])
    population = supervisor_population(tree, repository_tree_id="tree:e2e")
    assert population.get("goal_edges") == tree["goal_edges"]
    assert population["schema"] == POPULATION_SCHEMA
    assert population["goals"][0]["objective_id"] == OBJECTIVE_ID
    assert population["plans"][0]["plan_cid"] == tree["plan_cid"]
    task = population["tasks"][0]
    assert task["task_cid"].startswith("task:")
    assert task["goal_cid"].startswith("goal:")
    assert task["plan_cid"] == tree["plan_cid"]
    assert task["objective_id"] == OBJECTIVE_ID
    assert task["outputs"][0]["path"]
    assert task["acceptance_criteria"]
    assert task["validation_commands"][0]["argv"][0] == "python3"
    assert task["admitted"] is False
    assert task["proof_authoritative"] is False
    assert task["status"] == "ready"
    assert task["work_kind"] == "compiler_decompiler_edit"
    assert task["allowed_edit_paths"]
    markdown = render_supervisor_board(tree["tasks"], goals=tree["goals"])
    validate_supervisor_board(markdown)
    assert "- Goal cid:" in markdown
    assert "- Plan cid:" in markdown
    assert "- Objective id:" in markdown
    assert "- Parent goal:" in markdown


def test_goal_resolves_when_every_span_has_a_roundtrip_proof() -> None:
    tasks = discrepancy_tasks({"rows": [_gap("s1"), _gap("s2")]})
    tree = spawn_goal_tree(tasks)
    open_goals, resolved = resolve_goals(tree["goals"], proved_span_ids=["s1"])
    assert any(goal["status"] == "open" for goal in open_goals)
    open_goals, resolved = resolve_goals(tree["goals"], proved_span_ids=["s1", "s2"])
    assert not [goal for goal in open_goals if goal.get("kind") != "campaign" or goal.get("source_span_ids")]
    assert any(
        goal["kind"] == "architecture-decision" and goal["status"] == "provisionally_complete"
        for goal in resolved
    )


def test_population_ingests_through_materialize() -> None:
    class Source:
        def __init__(self):
            self.payload = None

        def materialize(self, population):
            self.payload = population
            return {"task_count": len(population["tasks"]), "goal_count": len(population["goals"])}

    tasks = discrepancy_tasks({"rows": [_gap("s1"), _gap("s2")]})
    tree = spawn_goal_tree(tasks)
    source = Source()
    receipt = ingest_population(source, supervisor_population(tree))
    assert source.payload["goals"]
    assert source.payload["tasks"][0]["goal_cid"]
    assert receipt["task_count"] == 2
    assert receipt["jsonl_written"] is False


def test_loop_resolves_goals_when_later_round_proves_spans() -> None:
    state = {"round": 0}

    def autoformal():
        state["round"] += 1
        if state["round"] == 1:
            return {"rows": [_gap("s1"), _gap("s2")]}
        return {
            "rows": [
                {"agrees": True, "id": "s1", "source_span_id": "s1", "skipped": False},
                {"agrees": True, "id": "s2", "source_span_id": "s2", "skipped": False},
            ]
        }

    receipt = run_supervisor_loop(autoformal, ingest=lambda *a, **k: {"task_count": 2}, max_rounds=3)
    assert receipt["stop_reason"] == "goals_resolved"
    assert receipt["open_goal_count"] == 0
    assert receipt["rounds"][-1]["resolved_goal_count"] >= 1


def test_loop_ingests_errors_then_stops_when_nothing_new(tmp_path: Path) -> None:
    calls = {"n": 0}
    ingested = []

    def autoformal():
        calls["n"] += 1
        return {"rows": [_gap("s1"), _gap("s2")]}

    def ingest(agreement, **kwargs):
        ingested.append(kwargs.get("goals") or [])
        return {"task_count": 2, "jsonl_written": False}

    receipt = run_supervisor_loop(
        autoformal,
        ingest=ingest,
        max_rounds=4,
        board_path=tmp_path / "board.md",
    )
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["stop_reason"] == "no_new_errors"
    assert receipt["round_count"] == 2
    assert calls["n"] == 2
    assert any(goal["kind"] == "architecture-decision" for goal in ingested[0])


def test_loop_records_proofs_when_gaps_clear() -> None:
    def autoformal():
        return {
            "rows": [
                {"agrees": True, "id": "ok", "source_span_id": "ok", "skipped": False, "text": "ok"}
            ]
        }

    receipt = run_supervisor_loop(autoformal, ingest=lambda *a, **k: {"task_count": 0}, max_rounds=2)
    assert receipt["stop_reason"] in {"no_outstanding_todos", "goals_resolved"}
    assert receipt["proof_count"] == 1
    assert receipt["rounds"][0]["proofs"][0]["proof_authoritative"] is False


def test_loop_turns_run_exceptions_into_review_todos() -> None:
    seen = {}

    def autoformal():
        raise RuntimeError("census exploded")

    def ingest(agreement, **kwargs):
        seen["reason"] = agreement["rows"][0]["reason"]
        seen["text"] = agreement["rows"][0]["text"]
        return {"task_count": 1, "jsonl_written": False}

    receipt = run_supervisor_loop(autoformal, ingest=ingest, max_rounds=1)
    assert seen["reason"] == "loop_error"
    assert "census exploded" in seen["text"]
    assert receipt["todo_count"] == 1
    assert receipt["jsonl_written"] is False


def test_loop_runs_real_autoformal_and_ingests_goals(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_uscode_loop_e2e",
        Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/run_uscode_on_sparse_graphrag.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = {}

    def autoformal():
        receipt = module.run_uscode_autoformal(
            hits=[
                {
                    "legal_id": "usc:us:18:1001",
                    "title": "18",
                    "section": "1001",
                    "text": "Whoever knowingly and willfully falsifies a material fact shall be fined under this title.",
                }
            ],
            skip_upload=True,
        )
        return {"spans": receipt["spans"]}

    def ingest(agreement, **kwargs):
        seen["goals"] = kwargs.get("goals") or []
        seen["count"] = len(agreement["rows"])
        return {"task_count": 1, "jsonl_written": False}

    receipt = run_supervisor_loop(
        autoformal,
        ingest=ingest,
        max_rounds=2,
        board_path=tmp_path / "loop.todo.md",
        query="false statements",
        release_id="loop-e2e",
    )
    assert receipt["jsonl_written"] is False
    assert receipt["wrote_compiler"] is False
    assert receipt["admitted"] is False
    assert seen["count"] >= 1
    assert receipt["todo_count"] >= 1


def test_huggingface_upload_runs_once_after_the_loop() -> None:
    calls = []

    def autoformal():
        return {"rows": [_gap("s1"), _gap("s2")]}

    def upload(tasks):
        calls.append(len(list(tasks)))
        return {"jsonl_written": False, "task_count": len(tasks)}

    receipt = run_supervisor_loop(
        autoformal,
        ingest=lambda *a, **k: {"task_count": 2},
        upload=upload,
        max_rounds=3,
    )
    assert len(calls) == 1
    assert calls[0] >= 2
    assert receipt["huggingface"]["jsonl_written"] is False


def test_population_receipt_is_one_json_object(tmp_path: Path) -> None:
    receipt = run_supervisor_loop(
        lambda: {"rows": [_gap("s1"), _gap("s2")]},
        ingest=lambda *a, **k: {"task_count": 2},
        max_rounds=1,
    )
    path = tmp_path / "loop.population.json"
    written = write_population_receipt(path, receipt)
    assert written["jsonl_written"] is False
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == POPULATION_SCHEMA
    assert payload["population"]["tasks"]
    assert payload["population"]["goals"]
    assert payload["jsonl_written"] is False
    loaded = load_population_receipt(path)
    assert loaded["population"]["tasks"][0]["task_cid"] == payload["population"]["tasks"][0]["task_cid"]
    assert loaded["schema"] == POPULATION_SCHEMA
    assert loaded["seen_span_ids"] or loaded["population"]["tasks"]


def test_resume_from_receipt_resolves_goals_when_spans_now_roundtrip() -> None:
    first = run_supervisor_loop(
        lambda: {"rows": [_gap("s1"), _gap("s2")]},
        ingest=lambda *a, **k: {"task_count": 2},
        max_rounds=2,
    )
    assert first["open_goal_count"] >= 1
    prior = {
        "population": first["population"],
        "proved_span_ids": first.get("proved_span_ids") or [],
        "seen_span_ids": first.get("seen_span_ids") or [],
        "schema": POPULATION_SCHEMA,
    }

    def autoformal():
        return {
            "rows": [
                {"agrees": True, "id": "s1", "source_span_id": "s1", "skipped": False},
                {"agrees": True, "id": "s2", "source_span_id": "s2", "skipped": False},
            ]
        }

    second = run_supervisor_loop(
        autoformal,
        ingest=lambda *a, **k: {"task_count": 0},
        max_rounds=2,
        prior=prior,
    )
    assert second["stop_reason"] == "goals_resolved"
    assert second["round_count"] == 1
    assert second["open_goal_count"] == 0
    assert any(
        goal.get("status") == "provisionally_complete"
        for goal in second["population"].get("goals") or []
    )


def test_recensus_does_not_claim_and_can_resolve_goals() -> None:
    first = run_supervisor_loop(
        lambda: {"rows": [_gap("s1"), _gap("s2")]},
        ingest=lambda *a, **k: {"task_count": 2},
        max_rounds=1,
    )
    prior = {
        "population": first["population"],
        "proved_span_ids": [],
        "seen_span_ids": first.get("seen_span_ids") or [],
        "schema": POPULATION_SCHEMA,
    }
    still_open = recensus_open_todos(
        prior,
        lambda text: {"compiler_status": "abstain", "reason": "compiler_abstain", "decompiled": ""},
    )
    assert still_open["claimed"] is False
    assert still_open["stop_reason"] == "open_todos_remain"
    closed = recensus_open_todos(
        prior,
        lambda text: {"compiler_status": "compiled", "reason": "", "decompiled": text},
    )
    assert closed["claimed"] is False
    assert closed["stop_reason"] == "goals_resolved"
    assert closed["proofs"]
    assert closed["admitted"] is False


def test_later_rounds_recensus_instead_of_rerunning_autoformal() -> None:
    calls = {"autoformal": 0, "compile": 0}

    def autoformal():
        calls["autoformal"] += 1
        return {"rows": [_gap("s1"), _gap("s2")]}

    def compile_one(text: str):
        calls["compile"] += 1
        return {"compiler_status": "abstain", "reason": "compiler_abstain", "decompiled": ""}

    receipt = run_supervisor_loop(
        autoformal,
        ingest=lambda *a, **k: {"task_count": 2},
        compile_one=compile_one,
        max_rounds=3,
    )
    assert calls["autoformal"] >= 1
    assert calls["compile"] >= 2
    assert receipt["round_count"] >= 2
    assert any(item.get("phase") == "recensus" for item in receipt.get("rounds") or [])
    assert receipt["remaining_count"] == 2


def test_loop_emits_progress_lines_and_writes_a_progress_log(tmp_path: Path) -> None:
    lines: list[str] = []
    receipt = run_supervisor_loop(
        lambda: {"rows": [_gap("s1"), _gap("s2")]},
        ingest=lambda *a, **k: {"task_count": 2},
        max_rounds=2,
        board_path=tmp_path / "loop.todo.md",
        log=lines.append,
    )
    joined = "\n".join(lines)
    assert "PROGRESS start" in joined
    assert "PROGRESS round=1/2" in joined
    assert "PROGRESS dispatch round=1" in joined
    assert "CENSUS round=1" in joined
    assert "CENSUS span id=" in joined
    assert "LAKE round=1" in joined
    assert "CENSUS span id=" in joined
    assert "edit=2" in joined
    assert "remaining=2" in joined
    assert "PROGRESS stop=" in joined
    assert "CENSUS stop=" in joined
    log_file = tmp_path / "loop.todo.progress.log"
    assert log_file.is_file()
    assert "PROGRESS round=1/2" in log_file.read_text(encoding="utf-8")
    assert receipt["remaining_count"] == 2
    assert receipt["remaining_span_ids"]
    assert "compiled_ids=" in joined
    assert "remaining_ids=" in joined
    census = write_census_snapshot(tmp_path / "loop.todo.census.json", receipt)
    payload = json.loads(Path(census["path"]).read_text(encoding="utf-8"))
    assert payload["remaining_count"] == 2
    assert payload["admitted"] is False


def test_later_retrieve_grows_the_corpus_census() -> None:
    calls = {"autoformal": 0}

    def autoformal():
        calls["autoformal"] += 1
        if calls["autoformal"] == 1:
            return {
                "rows": [
                    _gap("s1"),
                    {"agrees": True, "id": "ok", "source_span_id": "ok", "skipped": False},
                ]
            }
        return {"rows": [_gap("s3", legal_id="usc:us:18:1001")]}

    def compile_one(text: str):
        return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}

    receipt = run_supervisor_loop(
        autoformal,
        ingest=lambda *a, **k: {"task_count": 1},
        compile_one=compile_one,
        max_rounds=3,
    )
    assert calls["autoformal"] == 2
    assert "ok" in (receipt.get("compiled_span_ids") or [])
    assert "s1" in (receipt.get("remaining_span_ids") or [])
    assert "s3" in (receipt.get("remaining_span_ids") or [])
    assert receipt["compiled_count"] == 1
    assert receipt["remaining_count"] == 2
    assert receipt["admitted"] is False
    assert receipt["todo_count"] == 2
    report = loop_progress_report(receipt)
    assert report["compiled_count"] == 1
    assert report["remaining_count"] == 2
    assert report["rounds"]
    assert report["admitted"] is False


def test_max_rounds_is_bounded() -> None:
    with pytest.raises(SupervisorLoopError, match="max_rounds"):
        run_supervisor_loop(lambda: {"rows": []}, max_rounds=0)
    with pytest.raises(SupervisorLoopError, match="max_rounds"):
        run_supervisor_loop(lambda: {"rows": []}, max_rounds=99)

# These controls use normal canonical package imports. The synthetic metadata
# fixture is authored here; expected observations are not a product oracle.
def _inventory0101_wire(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def _inventory0101_frame(role, value):
    import hashlib
    raw = value.encode() if type(value) is str else _inventory0101_wire(value)
    pin = {"path": f"/retained/{role}.json", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return {"original_descriptor": pin, "descriptor": {**pin, "path": f"/transport/{role}.json"}, "utf8": raw.decode()}


def _inventory0101_fixture():
    # Literal original native acceptance text, not obtained from the preparer.
    criteria = [
        "Every selected asset has immutable identity, owner, task, producer and evidence scope.",
        "F15/F17/F18 registrations and the five-variant replay are reused; published or binding counts are not model/accuracy counts.",
        "Reuse historical 16-shard/62,931-row inventory, frozen source partitions and 103-file package; original 5016 release provenance survives current 91 manifest equality. Fresh package verification is separately evidenced, not inferred from metadata or a historical receipt.",
    ]
    objective = "Inventory main, relevant published branches/worktrees, retained model lineages and exact tasks/codecs; adopt the completed source inventory, frozen partitions and portable package under original release provenance before proposing another run."
    scope = {"task_alias": "LIR-0101", "task_cid": "baguqeeraty5cz3vfxxx5hxcvvg4o6rivtl746eoq3remdluqc3o4gqnob2ua",
        "goal_cid": "baguqeerawdzrk72ymyossnu2qifinzljp6s6yqinfgpsfhxm4oehlf5iiizq",
        "plan_cid": "baguqeeraiddmy4khowkyv37gwstmexmmku3lecsjtnaekhpqnlwx4vuwrhza", "revision": 3, "status": "blocked"}
    output = "data/legal_ir_span_graph_lean_20261016/LIR-0101/asset-and-contribution-inventory.json"
    dep_cid = "saved-dependency-9004"
    completion = {"operation": "independent_native_handoff_metadata_completion_v1", "task_cid": dep_cid,
                  "evidence_digest": "saved-accepted-9004-evidence"}
    authored = {"acceptance_criteria": criteria, "objective": objective, "completion": "manual",
                "requires_product_change_scope": False, "outputs": [output]}
    task = {**scope, "body": {**authored, "authored_task": authored}, "outputs": [{"path": output}],
        "acceptance": [{"ordinal": i, "criterion": c} for i, c in enumerate(criteria)],
        "dependencies": [{"dependency_task_cid": dep_cid, "kind": "depends_on"}]}
    runtime_root = "/canonical/fixture/workspace/test-logs/LIR-0101"
    runtime_outputs = {role: f"{runtime_root}/{'verifier-attempt' if role == 'verification' else 'producer-attempt'}/exports/{basename}" for role, basename in zip(
        ("report", "producer_freeze", "verification"), ("asset-and-contribution-inventory.json",
        "asset-and-contribution-inventory.freeze.json", "asset-and-contribution-inventory.verification.json"))}
    task["revision"] = 4  # Authored positive amendment fixture, not a live readback.
    task["body"].update(constraints={"canonical_logic_root": "/canonical/fixture"},
        owned_paths=["workspace/test-logs/LIR-0101"], asset_inventory_0101_v1={"runtime_output_binding": {
            "schema": "legal-ir-0101-runtime-output-binding/v1", "original_output": output,
            "cwd": "/canonical/fixture", "task_root": runtime_root, "outputs": runtime_outputs}})
    task["outputs"] = [{"ordinal": i, "path": str(Path(path).relative_to("/canonical/fixture")),
        "effect": {"path": str(Path(path).relative_to("/canonical/fixture"))}}
        for i, path in enumerate(runtime_outputs.values())]
    dependency = {"task_alias": "LIR-9004", "task_cid": dep_cid, "status": "completed", "revision": 5,
                  "body": {"completion_receipt": completion}}
    docs = {"current_snapshot": {"schema": "ipfs_accelerate_py/agent-supervisor/intent-plan-projection@1",
        "tasks": [task, dependency] + [{"task_alias": f"unselected-{i}"} for i in range(62)]},
        "accepted_dependencies": {"schema": "legal-ir-0101-native-accepted-dependencies/v1",
            "task_cid": scope["task_cid"], "task_revision": 4,
            "dependencies": [{"task_cid": dep_cid, "revision": 5, "status": "completed",
                "authority_spec_cid": "baguqeera" + "a"*52, "completion_receipt_cid": "baguqeera" + "b"*52}]}}
    assets, registered, checkpoints = [], [], []
    for i in range(19):
        identity = {"path_reported": f"/unopened/payload-{i}", "recorded_bytes": i+1,
            "recorded_sha256": f"{i+1:064x}", "payload_bytes_authenticated_by_candidate": False}
        ref = {"evidence_id": "registration_inventory", "json_pointer": f"/selected_assets/{i}"}
        provenance = [{"bytes": 42, "git_path": f"original/source-{i}.json", "git_revision": "b" * 40,
                       "sha256": f"{i+100:064x}"}] if i < 13 else ([
                           {"evidence_id": "component_plan", "json_pointer": f"/models/{i-13}/model_metadata/huggingface_config/metadata_provenance"}]
                           if i < 16 else [{"evidence_id": "embedding_survey", "json_pointer": f"/highest_value_reuse/{i-11}"}])
        refs = [ref, {"evidence_id": "checkpoint_survey", "json_pointer": f"/selected_assets/{i}"}] if i < 16 else [ref, provenance[0]]
        assets.append({"inventory_key": f"asset-{i}", "task": f"task-{i}", "immutable_identity": identity,
            "owner": {"repository": "ipfs_datasets_py", "inventory_metadata_owner": {"evidence_id": "asset_guide", "json_pointer": ""},
                      "historical_producer_process_or_principal": None},
            "producer": {"reported_task": f"task-{i}", "metadata_provenance": provenance,
                         "execution_principal": None, "execution_authenticated_by_candidate": False},
            "evidence_scope": "retained documentary provenance only", "evidence_refs": refs,
            "criterion1_satisfied_by_candidate": False, "task_codec_profile": {"codec_identity": None}})
        registered.append({"inventory_key": f"asset-{i}", "task": f"task-{i}", "path": identity["path_reported"],
                           "recorded_bytes": i+1, "recorded_sha256": identity["recorded_sha256"]})
        if i < 16:
            checkpoints.append({**registered[-1], "recorded_checkpoint_sha256": identity["recorded_sha256"],
                                "metadata_provenance": provenance})
    docs.update({"registration_inventory": {"selected_assets": registered}, "checkpoint_survey": {"selected_assets": checkpoints},
        "embedding_survey": {"highest_value_reuse": [{"reported_task": f"embedding-{i}"} for i in range(8)]},
        "asset_guide": "Recorded canonical inventory owner.\n", "decoder_guide": "Decoder limitations.\n",
        "source_guide": "Retained source provenance.\n"})
    ids = [f"retained-source-record-{i}" for i in range(3)]
    components = [{"label": label, "source_record_id": ids[i], "dimension_role": "source_tokens",
        "latent_conditioning_enabled": False, "runtime_ready": False, "teacher_qualified": False,
        "checkpoint_bytes": i+10, "checkpoint_sha256": f"{i+200:064x}"} for i, label in enumerate(("F15", "F17", "F18"))]
    docs["component_plan"] = {"models": [{"checkpoint_pin": {"bytes": c["checkpoint_bytes"], "sha256": c["checkpoint_sha256"]},
        "model_metadata": {"huggingface_config": {"metadata_provenance": {"immutable_source": "a"*64}, "ir_checkpoint": {"record_id": c["source_record_id"],
            "dimension_role": "source_tokens", "latent_conditioning_enabled": False}}}} for c in components]}
    docs["component_audit"] = {"status": "pass", "population": {"before_count": 684, "after_count": 687,
        "baseline_unique_ids": 684, "baseline_records_changed": 0, "baseline_ids_removed": 0,
        "all_33_stored_fields_equal_for_each_of_684_baseline_records": True, "exact_added_source_record_ids": ids},
        "import": {"registered_count": 3, "persisted_metadata_matched_count": 3, "all_outcomes_registered_verified": True},
        "catalog": {"components": components}}
    variants = ["original_donors", "original_768_initialization", "aligned_768_initialization",
                "original_start_trained_interfaces", "aligned_start_trained_interfaces"]
    results = {"correct_source_primary_exact_stored_reference_by_variant": {v: {"matched": 0, "selected": 2} for v in variants},
        "first_pass_sequences": 60, "first_pass_eos_complete": 60, "first_pass_native_grammar_valid": 60,
        "fresh_load_sequences": 60, "forward_steps": 3240, "native_tests": 173,
        "primary_references_exposed": True, "statutory_gold_or_holdout_claimed": False}
    docs["replay_adoption"] = {"attributed_completed_results": results}
    docs["replay_native_audit"] = {"status": "PASS"}
    commitments = {"release": "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e",
        "selected_manifest_revision": "91ca1838853ac82d7a12dd4ab47d9686f47667f9",
        "selected_manifest_sha256": "1"*64, "inventory_sha256": "2"*64, "partitions_sha256": "3"*64,
        "package_manifest_sha256": "4"*64, "ordered_row_digest": "5"*64, "payloads_rehashed_by_this_proposal": False}
    docs["source_provenance"] = {"manifest_equivalence": {"original_release_commit": commitments["release"],
        "current_observed_release_commit": commitments["selected_manifest_revision"],
        "manifest_sha256": commitments["selected_manifest_sha256"], "current_metadata_snapshot_equals_original_manifest_bytes": True}}
    docs["source_verification"] = {"status": "pass", "all_checks_complete": True,
        "inventory_summary": {"declared_corpus_shards": 16, "rows_scanned": 62931, "declared_row_count": 62931,
            "complete": True, "inventory_sha256": "2"*64, "source_authority_authenticated": False, "training_eligible": False},
        "inventory": {"sha256": "2"*64}, "partitions": {"sha256": "3"*64},
        "package": {"expected_file_count": 103, "verified_file_count": 103, "expected_total_bytes": 263671066,
            "verified_total_bytes": 263671066, "manifest": {"sha256": "4"*64}, "row_digest": "5"*64}}
    source_pin = _inventory0101_frame("source_verification", docs["source_verification"])["original_descriptor"]
    docs["source_native_audit"] = {"audit_status": "pass", "qualification_passed": True, "six_named_artifact_checks_passed": True,
        "worker_report": {k: source_pin[k] for k in ("bytes", "sha256")},
        "retained_source": {"original_repository_revision": commitments["release"], "physical_rows": 62931,
            "declared_corpus_shards": 16, "verified_package_files": 103, "ordered_row_digest": "5"*64},
        "native_closeout": {"completed": True, "artifacts_durable_asserted": True, "native_lease_released": True,
            "reservation_status": "released", "returncode": 0, "cleanup_error": None},
        "source_custody": {"all_current_hashes_match_frozen_request": True,
            "input_and_package_custody_fences_passed": True, "public_copied_exports_equal_native_original_bytes": True}}
    frames = {role: _inventory0101_frame(role, value) for role, value in docs.items()}
    registry = [{"evidence_id": role, "descriptor": frames[role]["original_descriptor"]} for role in docs
                if role not in {"current_snapshot", "accepted_dependencies"}]
    candidate = {"schema": "legal-ir-0101-asset-and-contribution-inventory-candidate/v1", "candidate_only": True,
        "task_scope": scope, "selected_asset_count": 19, "assets": assets, "evidence_registry": registry,
        "accepted_dependency": {"task_cid": dep_cid, "completion_operation": completion["operation"],
                                "completion_evidence_digest": completion["evidence_digest"]},
        "criterion_assessment": [{"ordinal": i, "criterion": c, "status": "historical_candidate_only"} for i, c in enumerate(criteria)],
        "F15_F17_F18_adoption": {"source_record_ids": ids, "source_tokens_only": True, "latent_conditioning_enabled": False,
            "active384D_lane_inferred": False, "native_runtime_or_teacher_qualified": False},
        "five_variant_replay_adoption": {"variants": [v.replace("_768_", "768_") for v in variants],
            "attributed_results": results, "published_or_binding_counts_are_accuracy": False, "replay_reexecuted": False},
        "source_adoption": {"retained_commitments": commitments, "fresh_package_bytes_revalidated_by_candidate": False,
            "source_meaning_or_training_gold_admitted": False, "whole_release_equivalence_inferred_from_selected_manifest": False},
        "four_width_roles": [{"width": w, "selected_keys": [], "new_asset_fabricated": False,
                             "attribution_status": "not_covered_by_selected_retained_evidence"} for w in (8, 384, 768, 4096)],
        "authority": {"native_admission": False, "model_runtime_admitted": False,
                      "supervision_masks": {"evaluation_gold": 0, "training": 0}}}
    frames["candidate"] = _inventory0101_frame("candidate", candidate)
    main_values = {"D": "d"*40, "A": "a"*40}
    docs["public_main_receipt"] = {"schema": "legal-ir-selected-public-main-refs/v1", "observed_at_utc": "cutoff",
        "results": [{"repository": repo, "result": {"content": json.dumps({"ref": "refs/heads/main",
            "object": {"sha": commit, "type": "commit"}})}} for repo, commit in main_values.items()]}
    docs["publication_receipts"] = {"receipts": [{"head_repo_full_name": "D", "number": 1451, "merged": True,
        "head_sha": "b"*40, "merge_commit_sha": "d"*40}, {"head_repo_full_name": "A", "number": 311,
        "merged": False, "head_sha": "c"*40}]}
    for role in ("public_main_receipt", "publication_receipts"):
        frames[role] = _inventory0101_frame(role, docs[role])
    cutoff = {"schema": "legal-ir-0101-selected-contribution-cutoff-addendum/v1", "candidate_inventory": frames["candidate"]["original_descriptor"],
        "exact_public_main_ref_receipt": frames["public_main_receipt"]["original_descriptor"],
        "publication_receipts": frames["publication_receipts"]["original_descriptor"],
        "selected_verified_public_cutoff_observed_at_utc": "cutoff",
        "selected_public_main": [{"repository": repo, "commit": commit} for repo, commit in main_values.items()],
        "selected_public_contributions": [{"repository": "D", "pr": 1451, "merged": True, "head_sha": "b"*40,
                                           "merge_commit_sha": "d"*40}],
        "unmerged_selected_A_contribution": {"repository": "A", "pr": 311, "merged": False, "head_sha": "c"*40,
                                             "runtime_activation_inferred": False},
        **{key: False for key in ("broader_branch_coverage_claimed", "scientific_or_legal_acceptance_claimed",
                                 "new_model_or_checkpoint_claimed", "task_completion_claimed")}}
    frames["publication_cutoff"] = _inventory0101_frame("publication_cutoff", cutoff)
    review = {"schema": "legal-ir-0101-candidate-criterion-gaps/v2", "candidate": frames["candidate"]["original_descriptor"],
        "selected_contribution_cutoff_addendum": frames["publication_cutoff"]["original_descriptor"],
        "static_documentary_attribution_review": {"selected_assets": 19,
            "demonstrated_missing_task_required_attribution_asset_count": 0,
            "demonstrated_missing_task_required_attribution_fields": [], "field_coverage": {str(i): 19 for i in range(5)}},
        "optional_or_presentation_limitations": {"historical_PID_or_DID_recovery_required": False,
            "complete_numerical_runtime_closure_or_payload_authentication_required_for_this_metadata_inventory": False}}
    frames["attribution_review"] = _inventory0101_frame("attribution_review", review)
    return {"documents": frames, "producer_principal": "inventory-producer", "expected_task_revision": 4}


def _inventory0101_damage(inputs, role, change):
    """Re-sign a changed closure to test semantics beyond descriptor fencing."""
    value = json.loads(inputs["documents"][role]["utf8"])
    change(value)
    inputs["documents"][role] = _inventory0101_frame(role, value)
    frames = inputs["documents"]
    if role == "source_verification":
        audit = json.loads(frames["source_native_audit"]["utf8"])
        audit["worker_report"] = {k: frames[role]["original_descriptor"][k] for k in ("bytes", "sha256")}
        frames["source_native_audit"] = _inventory0101_frame("source_native_audit", audit)
    candidate = json.loads(frames["candidate"]["utf8"])
    for row in candidate["evidence_registry"]:
        row["descriptor"] = frames[row["evidence_id"]]["original_descriptor"]
    frames["candidate"] = _inventory0101_frame("candidate", candidate)
    cutoff = json.loads(frames["publication_cutoff"]["utf8"])
    cutoff["candidate_inventory"] = frames["candidate"]["original_descriptor"]
    cutoff["exact_public_main_ref_receipt"] = frames["public_main_receipt"]["original_descriptor"]
    cutoff["publication_receipts"] = frames["publication_receipts"]["original_descriptor"]
    frames["publication_cutoff"] = _inventory0101_frame("publication_cutoff", cutoff)
    review = json.loads(frames["attribution_review"]["utf8"])
    review["candidate"] = frames["candidate"]["original_descriptor"]
    review["selected_contribution_cutoff_addendum"] = frames["publication_cutoff"]["original_descriptor"]
    frames["attribution_review"] = _inventory0101_frame("attribution_review", review)


def test_asset_inventory_0101_normal_documentary_inventory_and_distinct_verifier():
    import hashlib
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
        prepare_current_asset_contribution_inventory_v1, verify_current_asset_contribution_inventory_v1)
    inputs = _inventory0101_fixture()
    report = prepare_current_asset_contribution_inventory_v1(**inputs)
    expected_runtime_binding = json.loads(inputs["documents"]["current_snapshot"]["utf8"])["tasks"][0]["body"]["asset_inventory_0101_v1"]["runtime_output_binding"]
    assert report["runtime_output_binding"] == expected_runtime_binding
    assert report["selected_asset_count"] == 19
    assert all(not a["criterion1_satisfied_by_candidate"] for a in report["assets"])
    assert report["documentary_inventory_criteria_satisfied"] is True
    assert [c["status"] for c in report["criterion_assessment"]] == ["satisfied_for_documentary_inventory_scope"] * 3
    assert report["five_variant_replay_adoption"]["canonical_variants"] == sorted([
        "original_donors", "original_768_initialization", "aligned_768_initialization",
        "original_start_trained_interfaces", "aligned_start_trained_interfaces"])
    assert report["authority"]["native_admission"] is False
    raw = _inventory0101_wire(report)
    freeze = {"schema": "legal-ir-0101-inventory-producer-freeze/v1", "report_sha256": hashlib.sha256(raw).hexdigest(),
        "report_bytes": len(raw), "producer_principal": "inventory-producer", "frozen_before_verification": True}
    verified = verify_current_asset_contribution_inventory_v1(report, producer_freeze=freeze,
        verifier_principal="independent-inventory-verifier", **inputs)
    assert verified["valid"] is True and verified["original_criteria_verified"] == 3
    assert verified["native_admission"] is verified["completion_authority"] is False


@pytest.mark.parametrize("role,damage", [
    ("candidate", lambda d: d["assets"].pop()),
    ("candidate", lambda d: d["assets"].__setitem__(1, d["assets"][0])),
    ("candidate", lambda d: d["assets"][0]["immutable_identity"].__setitem__("recorded_bytes", True)),
    ("candidate", lambda d: d["assets"][0]["immutable_identity"].__setitem__("recorded_sha256", "f"*64)),
    ("candidate", lambda d: d["assets"][0].__setitem__("task", "other-task")),
    ("candidate", lambda d: d["assets"][0]["owner"].__setitem__("repository", "unbound-owner")),
    ("candidate", lambda d: d["assets"][0]["producer"]["metadata_provenance"][0].__setitem__("git_revision", "f"*40)),
    ("candidate", lambda d: d["assets"][0]["evidence_refs"][0].__setitem__("json_pointer", "/selected_assets/99")),
    ("candidate", lambda d: d["assets"][0].__setitem__("criterion1_satisfied_by_candidate", True)),
    ("candidate", lambda d: d["five_variant_replay_adoption"]["variants"].pop()),
    ("candidate", lambda d: d["five_variant_replay_adoption"].__setitem__("published_or_binding_counts_are_accuracy", True)),
    ("candidate", lambda d: d["F15_F17_F18_adoption"].__setitem__("latent_conditioning_enabled", True)),
    ("candidate", lambda d: d["authority"]["supervision_masks"].__setitem__("training", False)),
    ("component_audit", lambda d: d["population"].__setitem__("baseline_records_changed", 1)),
    ("component_audit", lambda d: d["population"].__setitem__("after_count", 687.0)),
    ("component_plan", lambda d: d["models"][0]["checkpoint_pin"].__setitem__("sha256", "f"*64)),
    ("source_verification", lambda d: d["package"].__setitem__("verified_file_count", 102)),
    ("source_native_audit", lambda d: d["worker_report"].__setitem__("sha256", "f"*64)),
    ("source_native_audit", lambda d: d["native_closeout"].__setitem__("returncode", False)),
    ("source_provenance", lambda d: d["manifest_equivalence"].__setitem__("original_release_commit", "f"*40)),
    ("current_snapshot", lambda d: d["tasks"][0].__setitem__("revision", 3)),
    ("current_snapshot", lambda d: d["tasks"][0]["acceptance"][0].__setitem__("criterion", "different criterion")),
    ("current_snapshot", lambda d: d["tasks"][0]["outputs"][0].__setitem__("path", "other.json")),
    ("current_snapshot", lambda d: d["tasks"][0]["body"].pop("asset_inventory_0101_v1")),
    ("current_snapshot", lambda d: d["tasks"][0]["body"]["asset_inventory_0101_v1"]["runtime_output_binding"]["outputs"].__setitem__("report", "/outside/report.json")),
    ("current_snapshot", lambda d: d["tasks"][0]["body"]["asset_inventory_0101_v1"]["runtime_output_binding"]["outputs"].__setitem__("verification",
        str(Path(d["tasks"][0]["body"]["asset_inventory_0101_v1"]["runtime_output_binding"]["outputs"]["report"]).parent / "asset-and-contribution-inventory.verification.json"))),
    ("current_snapshot", lambda d: d["tasks"][1].__setitem__("status", "blocked")),
    ("accepted_dependencies", lambda d: d["dependencies"][0].__setitem__("completion_receipt_cid", None)),
    ("accepted_dependencies", lambda d: d["dependencies"][0].__setitem__("revision", 5.0)),
    ("accepted_dependencies", lambda d: d.__setitem__("task_revision", 3)),
    ("publication_cutoff", lambda d: d["unmerged_selected_A_contribution"].__setitem__("merged", True)),
    ("publication_cutoff", lambda d: d.__setitem__("broader_branch_coverage_claimed", True)),
], ids=["missing-asset", "duplicate-asset", "bool-size", "identity-hash", "task", "owner", "producer-pin", "pointer",
    "rewritten-candidate-history", "variant", "count-as-accuracy", "latent-authority", "bool-zero-mask",
    "baseline-changed", "float-count", "component-plan", "package-count", "audit-join", "bool-return-code",
    "release-provenance", "revision", "criterion", "output", "missing-runtime-binding", "outside-runtime-binding", "verifier-writes-producer-attempt",
    "dependency", "missing-accepted-receipt", "float-dependency-revision", "stale-dependency-export",
    "unmerged-promoted", "all-branches"])
def test_asset_inventory_0101_rejects_resigned_metadata_drift(role, damage):
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import prepare_current_asset_contribution_inventory_v1
    inputs = _inventory0101_fixture()
    _inventory0101_damage(inputs, role, damage)
    # The test helper updates all descriptor joins; refusal must be semantic.
    with pytest.raises(ValueError):
        prepare_current_asset_contribution_inventory_v1(**inputs)


@pytest.mark.parametrize("failure", ["same-principal", "changed-report", "changed-freeze", "float-report-bytes", "wrong-inputs"])
def test_asset_inventory_0101_rejects_invalid_verification(failure):
    import hashlib
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
        prepare_current_asset_contribution_inventory_v1, verify_current_asset_contribution_inventory_v1)
    inputs = _inventory0101_fixture()
    report = prepare_current_asset_contribution_inventory_v1(**inputs)
    raw = _inventory0101_wire(report)
    freeze = {"schema": "legal-ir-0101-inventory-producer-freeze/v1", "report_sha256": hashlib.sha256(raw).hexdigest(),
        "report_bytes": len(raw), "producer_principal": "inventory-producer", "frozen_before_verification": True}
    principal = "independent-inventory-verifier"
    if failure == "same-principal":
        principal = inputs["producer_principal"]
    elif failure == "changed-report":
        report["documentary_inventory_criteria_satisfied"] = False
        changed = _inventory0101_wire(report)
        freeze.update(report_sha256=hashlib.sha256(changed).hexdigest(), report_bytes=len(changed))
    elif failure == "changed-freeze":
        freeze["frozen_before_verification"] = False
    elif failure == "float-report-bytes":
        freeze["report_bytes"] = float(freeze["report_bytes"])
    else:
        inputs["documents"]["asset_guide"]["descriptor"]["path"] = "/different/durable-owner.json"
    with pytest.raises(ValueError):
        verify_current_asset_contribution_inventory_v1(report, producer_freeze=freeze,
            verifier_principal=principal, **inputs)


def test_asset_inventory_0101_rejects_missing_role_and_durable_alias_drift():
    from ipfs_datasets_py.logic.autoformal.supervisor_loop import prepare_current_asset_contribution_inventory_v1
    inputs = _inventory0101_fixture()
    del inputs["documents"]["decoder_guide"]
    with pytest.raises(ValueError):
        prepare_current_asset_contribution_inventory_v1(**inputs)
    inputs = _inventory0101_fixture()
    inputs["documents"]["asset_guide"]["descriptor"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        prepare_current_asset_contribution_inventory_v1(**inputs)


def _inventory0101_cli_fixture(tmp_path):
    import hashlib
    import importlib.util
    inputs = _inventory0101_fixture()
    snapshot = json.loads(inputs["documents"]["current_snapshot"]["utf8"])
    task = snapshot["tasks"][0]
    binding = task["body"]["asset_inventory_0101_v1"]["runtime_output_binding"]
    task_root = tmp_path / "workspace/test-logs/LIR-0101"
    producer_exports, verifier_exports = (task_root / n / "exports" for n in ("producer-attempt", "verifier-attempt"))
    producer_exports.mkdir(parents=True)
    verifier_exports.mkdir(parents=True)
    binding["cwd"] = str(tmp_path)
    binding["task_root"] = str(task_root)
    task["body"]["constraints"]["canonical_logic_root"] = str(tmp_path)
    binding["outputs"] = {role: str((verifier_exports if role == "verification" else producer_exports) / Path(path).name)
                          for role, path in binding["outputs"].items()}
    inputs["documents"]["current_snapshot"] = _inventory0101_frame("current_snapshot", snapshot)
    declarations = {}
    for role, frame in inputs["documents"].items():
        path = tmp_path / f"{role}.metadata"
        path.write_bytes(frame["utf8"].encode())
        declarations[role] = {"original_descriptor": frame["original_descriptor"],
                             "descriptor": {**frame["descriptor"], "path": str(path)}}
    root = Path(__file__).resolve().parents[3]
    owner = root / "ipfs_datasets_py/logic/autoformal/supervisor_loop.py"
    raw = owner.read_bytes()
    spec = {"schema": "legal-ir-0101-asset-contribution-inventory-inputs/v1",
        "canonical_owner": {"path": str(owner), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
        "documents": declarations, "producer_principal": inputs["producer_principal"],
        "expected_task_revision": inputs["expected_task_revision"]}
    input_path = tmp_path / "inputs.json"
    input_path.write_bytes(_inventory0101_wire(spec))
    module_spec = importlib.util.spec_from_file_location("_inventory0101_original_cli",
        root / "scripts/ops/legal_ir/run_autoformal_supervisor.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module, input_path, spec


def test_asset_inventory_0101_actual_early_cli_prepare_and_verify(tmp_path, monkeypatch):
    cli, inputs, _ = _inventory0101_cli_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("0101 early metadata route reached native setup")
    monkeypatch.setattr(cli, "pin_accelerate", forbidden)
    task_root = tmp_path / "workspace/test-logs/LIR-0101"
    producer_exports, verifier_exports = (task_root / n / "exports" for n in ("producer-attempt", "verifier-attempt"))
    report, freeze = (producer_exports / name for name in ("asset-and-contribution-inventory.json",
        "asset-and-contribution-inventory.freeze.json"))
    verification = verifier_exports / "asset-and-contribution-inventory.verification.json"
    assert cli.main(["asset-inventory-0101", "prepare", "--inputs", str(inputs), "--output", str(report),
                     "--freeze-out", str(freeze)]) == 0
    assert cli.main(["asset-inventory-0101", "verify", "--inputs", str(inputs), "--output", str(verification),
                     "--report", str(report), "--freeze", str(freeze),
                     "--verifier-principal", "distinct-cli-verifier"]) == 0
    observed = json.loads(verification.read_bytes())
    assert observed["valid"] is True and observed["selected_assets_verified"] == 19
    assert observed["native_admission"] is observed["completion_authority"] is False
    assert json.loads(report.read_bytes())["operations"] == {
        "payloads_read": 0, "models_run": 0, "replays_run": 0, "provider_calls": 0, "native_status_writes": 0}
    # Original outputs are immutable; a second producer call refuses.
    before = report.read_bytes()
    assert cli.main(["asset-inventory-0101", "prepare", "--inputs", str(inputs), "--output", str(report),
                     "--freeze-out", str(freeze)]) == 2
    assert report.read_bytes() == before


@pytest.mark.parametrize("failure", ["alias-bytes", "owner-pin", "extra-role", "overlap-output"])
def test_asset_inventory_0101_actual_cli_refuses_invalid_declared_inputs(tmp_path, monkeypatch, failure):
    cli, inputs, spec = _inventory0101_cli_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    parent = tmp_path / "workspace/test-logs/LIR-0101/producer-attempt/exports"
    report, freeze = parent / "asset-and-contribution-inventory.json", parent / "asset-and-contribution-inventory.freeze.json"
    if failure == "alias-bytes":
        spec["documents"]["asset_guide"]["original_descriptor"]["sha256"] = "f" * 64
    elif failure == "owner-pin":
        spec["canonical_owner"]["sha256"] = "f" * 64
    elif failure == "extra-role":
        spec["documents"]["undeclared_payload"] = spec["documents"]["asset_guide"]
    else:
        spec["documents"]["asset_guide"]["descriptor"]["path"] = str(report)
    inputs.write_bytes(_inventory0101_wire(spec))
    assert cli.main(["asset-inventory-0101", "prepare", "--inputs", str(inputs), "--output", str(report),
                     "--freeze-out", str(freeze)]) == 2
    assert not report.exists() and not freeze.exists()

