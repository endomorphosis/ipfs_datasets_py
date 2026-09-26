"""Read-only ready-task observations using an isolated SQLite task-store fixture."""
from contextlib import contextmanager
import json
import sqlite3
from types import SimpleNamespace

from ipfs_datasets_py.logic.autoformal.supervisor_loop import (
    goal_status_counts,
    ready_task_cids_under_inconclusive_goals,
)


def test_ready_task_ids_are_sorted_scoped_and_do_not_mutate_task_or_goal_state():
    database = sqlite3.connect(":memory:")
    try:
        database.execute("CREATE TABLE goals (goal_cid TEXT, status TEXT, body TEXT)")
        database.execute("CREATE TABLE tasks (task_cid TEXT, goal_cid TEXT, status TEXT)")
        database.executemany("INSERT INTO goals VALUES (?, ?, ?)", [
            ("goal-a", "open", json.dumps({"kind": "subgoal"})),
            ("goal-b", "open", "{}"),
            ("goal-parked", "analysis_inconclusive", "{}"),
        ])
        database.executemany("INSERT INTO tasks VALUES (?, ?, ?)", [
            ("task-z", "goal-a", "ready"), ("task-a", "goal-a", "ready"),
            ("task-b", "goal-b", "ready"), ("blocked", "goal-a", "blocked"),
            ("running", "goal-a", "running"), ("done", "goal-a", "completed"),
            ("parked-ready", "goal-parked", "ready"), ("orphan", None, "ready"),
            ("parked-upper", "goal-parked", "READY"),
            ("parked-blocked", "goal-parked", "blocked"),
            ("missing-goal", "absent", "ready"),
        ])
        database.commit()

        def snapshot():
            return {name: database.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
                    for name in ("tasks", "goals")}

        class Intent:
            @contextmanager
            def _connection(self, *, write):
                assert write is False
                yield database

            def get_goal(self, goal_cid):
                row = database.execute("SELECT * FROM goals WHERE goal_cid = ?", [goal_cid]).fetchone()
                return {"goal_cid": row[0], "status": row[1], "body": json.loads(row[2])} if row else None

        before = snapshot()
        task_source = SimpleNamespace(_intent=Intent())
        report = goal_status_counts(task_source)
        opened = {row["goal_cid"]: row for row in report["open_goals"]}
        assert opened["goal-a"]["ready_task_cids"] == ["task-a", "task-z"]
        assert opened["goal-b"]["ready_task_cids"] == ["task-b"]
        assert set(opened) == {"goal-a", "goal-b"}
        assert report["inconclusive_goals"][0]["ready_task_cids"] == ["parked-ready"]
        assert report["verified_complete_count"] == 0
        assert report["admitted"] is False and report["formalized"] is False
        assert all(row["admitted"] is False and row["formalized"] is False
                   for row in report["open_goals"] + report["inconclusive_goals"])
        assert ready_task_cids_under_inconclusive_goals(task_source) == {"parked-ready", "parked-upper"}
        assert snapshot() == before
    finally:
        database.close()


def test_parked_ready_lookup_with_missing_intent_returns_no_candidates():
    assert ready_task_cids_under_inconclusive_goals(SimpleNamespace()) == set()
    assert ready_task_cids_under_inconclusive_goals(SimpleNamespace(_intent=None)) == set()
