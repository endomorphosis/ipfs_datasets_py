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
