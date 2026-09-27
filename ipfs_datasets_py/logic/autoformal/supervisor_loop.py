"""Bounded supervisor loop: autoformal errors become ingestible todos and goals.

The accelerate supervisor owns claims and completion. This adapter runs the
autoformal script, converts remaining gaps into todos, synthesizes related
todos into goals, and re-ingests. A strict round-trip is an engineering
receipt, not a legal proof or admit. JSONL is not written.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .supervisor_todo import (
    GOAL_PREFIX,
    agreement_from_spans,
    agreement_from_strict_spans,
    discrepancy_tasks,
    submit_discrepancies,
)


SCHEMA = "uscode-autoformal-supervisor-loop/v1"
ARCHITECTURE_MODES = frozenset(
    {
        "no_parser_elements",
        "compiler_abstain",
        "schema_placeholder",
        "strict_roundtrip_failed",
    }
)
MAX_ROUNDS = 8
OBJECTIVE_ID = "objective:uscode-autoformal"
CAMPAIGN_GOAL_ID = f"{GOAL_PREFIX}000"
POPULATION_SCHEMA = "ipfs_accelerate_py.agent_supervisor.database_task_source.population/v1"


class SupervisorLoopError(RuntimeError):
    """The autoformal supervisor loop cannot continue without inventing work."""


def progress_log_path(board_path: Any) -> Path | None:
    if board_path is None:
        return None
    return Path(board_path).with_name(Path(board_path).stem + ".progress.log")


def census_snapshot_path(board_path: Any) -> Path | None:
    if board_path is None:
        return None
    return Path(board_path).with_name(Path(board_path).stem + ".census.json")


def _emit_progress(message: str, *, log: Callable[[str], None] | None, board_path: Any) -> None:
    text = str(message).rstrip()
    if log is not None:
        log(text)
    progress = progress_log_path(board_path)
    if progress is None:
        return
    progress.parent.mkdir(parents=True, exist_ok=True)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def _span_id(task: Mapping[str, Any]) -> str:
    return str(task.get("source_span_id") or task.get("id") or "")


def census_span_records(agreement: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One operator-facing census row per agreement row. Not an admit."""

    records: list[dict[str, Any]] = []
    for row in agreement.get("rows") or []:
        if not isinstance(row, Mapping) or row.get("skipped"):
            continue
        records.append(
            {
                "agrees": row.get("agrees") is True,
                "decompiled": str(row.get("decompiled") or "")[:240],
                "fields": [str(item) for item in row.get("dropped") or row.get("unsupported_fields") or [] if str(item)],
                "id": str(row.get("source_span_id") or row.get("id") or ""),
                "legal_id": str(row.get("legal_id") or ""),
                "reason": str(row.get("reason") or ""),
                "status": "agreed" if row.get("agrees") is True else "gap",
                "text": str(row.get("text") or "")[:240],
            }
        )
    return records


def _emit_census_stage(
    agreement: Mapping[str, Any],
    *,
    index: int,
    log: Callable[[str], None] | None,
    board_path: Any,
    lake_probe: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, Any]:
    records = census_span_records(agreement)
    for record in records[:24]:
        _emit_progress(
            f"CENSUS span id={record['id']} status={record['status']} "
            f"reason={record['reason'] or 'none'} fields={','.join(record['fields']) or 'none'} "
            f"decompiled={record['decompiled'] or ''} text={record['text']}",
            log=log,
            board_path=board_path,
        )
    rules = [
        dict(row["rule"])
        for row in agreement.get("rows") or []
        if isinstance(row, Mapping) and row.get("agrees") is True and isinstance(row.get("rule"), Mapping) and row.get("rule")
    ]
    lake: dict[str, Any] = {
        "admitted": False,
        "error": "lake_not_run",
        "formalized": False,
        "lake_ok": False,
        "log": "",
        "target": "Legal",
        "theorem_count": 0,
    }
    if lake_probe is not None:
        probed = dict(lake_probe(rules) or {})
        lake.update(probed)
        lake["admitted"] = False
        lake["formalized"] = False
        error = str(lake.get("error") or "")
        _emit_progress(
            f"LAKE round={index} target=Legal theorems={int(lake.get('theorem_count') or 0)} "
            f"lake_ok={str(bool(lake.get('lake_ok'))).lower()} error={error or 'none'}",
            log=log,
            board_path=board_path,
        )
        if error and error not in {"lake_not_run", "no_renderable_norms", "lake_not_on_path"}:
            for line in error.splitlines()[:12]:
                _emit_progress(f"LAKE error {line}", log=log, board_path=board_path)
    elif not records:
        pass
    else:
        _emit_progress(
            f"LAKE round={index} target=Legal theorems=0 lake_ok=false error=lake_not_run",
            log=log,
            board_path=board_path,
        )
    return {"spans": records, "lake": lake}


def _mode(failure: str) -> str:
    key = str(failure or "compiler_disagreement").split(":", 1)[0]
    if key.startswith("CanonicalErrorCode."):
        return "compiler_abstain"
    return key or "compiler_disagreement"


def agreement_from_run(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an autoformal receipt into census rows. Not an admit."""

    if not isinstance(receipt, Mapping):
        raise SupervisorLoopError("autoformal receipt must be an object")
    nested = receipt.get("agreement")
    if isinstance(nested, Mapping) and nested.get("rows") is not None:
        return dict(nested)
    if receipt.get("rows") is not None:
        rows = [dict(row) for row in receipt.get("rows") or [] if isinstance(row, Mapping)]
        operative = [row for row in rows if not row.get("skipped")]
        agreed = sum(1 for row in operative if row.get("agrees"))
        return {
            "admitted": False,
            "agreed": agreed,
            "agrees": bool(operative) and agreed == len(operative),
            "formalized": False,
            "operative": len(operative),
            "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
            "rows": rows,
        }
    ledger = receipt.get("ledger") if isinstance(receipt.get("ledger"), Mapping) else {}
    if "spans" in receipt or "spans" in ledger:
        spans = list(receipt.get("spans") or ledger.get("spans") or [])
        if any(span.get("strict_status") for span in spans if isinstance(span, Mapping)):
            return agreement_from_strict_spans(spans)
        return agreement_from_spans(spans)
    raise SupervisorLoopError("autoformal receipt has no spans or agreement rows")


def proofs_from_agreement(agreement: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Engineering round-trip receipts. Not legal proofs and not admits."""

    proofs = []
    for row in agreement.get("rows") or []:
        if row.get("skipped") or not row.get("agrees"):
            continue
        proofs.append(
            {
                "admitted": False,
                "formalized": False,
                "id": str(row.get("id") or ""),
                "kind": "strict_roundtrip",
                "proof_authoritative": False,
                "source_span_id": str(row.get("source_span_id") or row.get("id") or ""),
            }
        )
    return proofs


def agreement_from_exception(exc: BaseException, *, round_index: int) -> dict[str, Any]:
    """A loop failure is a review todo, not a compiler patch."""

    return {
        "admitted": False,
        "agreed": 0,
        "agrees": False,
        "formalized": False,
        "operative": 1,
        "reason": "loop_error",
        "rows": [
            {
                "agrees": False,
                "id": f"loop-error-{round_index}",
                "reason": "loop_error",
                "skipped": False,
                "source_span_id": f"loop-error-{round_index}",
                "text": str(exc),
            }
        ],
    }


def synthesize_goals(
    tasks: Sequence[Mapping[str, Any]],
    *,
    min_cluster: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group related todos into goals that can close several outstanding items."""

    labeled = [dict(task) for task in tasks]
    if not labeled:
        return [], []
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for task in labeled:
        mode = _mode(str(task.get("failure_mode") or ""))
        legal_id = str(task.get("legal_id") or "")
        if mode in ARCHITECTURE_MODES:
            buckets[("architecture-decision", mode)].append(task)
        elif legal_id:
            buckets[("cluster", legal_id)].append(task)
        else:
            buckets[("cluster", mode)].append(task)
    goals: list[dict[str, Any]] = []
    assigned: dict[str, str] = {}
    next_index = 20
    for (kind, key), members in sorted(buckets.items(), key=lambda item: item[0]):
        if len(members) < min_cluster:
            continue
        goal_id = f"{GOAL_PREFIX}{next_index:03d}"
        next_index += 10
        title = (
            f"Architecture: {key} coverage"
            if kind == "architecture-decision"
            else f"Cluster: {key}"
        )
        goals.append(
            {
                "admitted": False,
                "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in members),
                "estimated_validation_seconds": sum(
                    int(item.get("estimated_validation_seconds") or 0) for item in members
                ),
                "failure_mode": key if kind == "architecture-decision" else str(members[0].get("failure_mode") or key),
                "formalized": False,
                "goal_id": goal_id,
                "kind": kind,
                "priority": "P0" if kind == "architecture-decision" else "P1",
                "resolves": [str(item["task_id"]) for item in members],
                "status": "todo",
                "title": title,
            }
        )
        for item in members:
            assigned[str(item["task_id"])] = goal_id
    default = f"{GOAL_PREFIX}010"
    for task in labeled:
        task["goal_id"] = assigned.get(str(task["task_id"]), default)
    for goal in goals:
        members = [item for item in labeled if item.get("goal_id") == goal["goal_id"]]
        goal["source_span_ids"] = [str(item.get("source_span_id") or "") for item in members]
    return labeled, goals


def _cid(kind: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{kind}:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def spawn_goal_tree(
    tasks: Sequence[Mapping[str, Any]],
    *,
    release_id: str = "",
    min_cluster: int = 2,
    campaign_title: str = "U.S. Code autoformal campaign",
    dispatch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Campaign goal, architecture/cluster goals, optional citation subgoals, todos."""

    labeled, clusters = synthesize_goals(tasks, min_cluster=min_cluster)
    campaign_cid = _cid("goal", CAMPAIGN_GOAL_ID, release_id)
    plan_cid = _cid("plan", CAMPAIGN_GOAL_ID, release_id or "loop")
    campaign = {
        "admitted": False,
        "estimated_tokens": 0,
        "estimated_validation_seconds": 0,
        "failure_mode": "",
        "formalized": False,
        "goal_alias": CAMPAIGN_GOAL_ID,
        "goal_cid": campaign_cid,
        "goal_id": CAMPAIGN_GOAL_ID,
        "kind": "campaign",
        "objective_id": OBJECTIVE_ID,
        "ordinal": 1,
        "parent_goal_cid": "",
        "priority": "P0",
        "resolves": [],
        "source_span_ids": [],
        "status": "open",
        "title": campaign_title,
    }
    goals = [campaign]
    edges: list[dict[str, str]] = []
    next_sub = 21
    for ordinal, cluster in enumerate(clusters, start=2):
        cluster = dict(cluster)
        cluster["goal_alias"] = cluster["goal_id"]
        cluster["goal_cid"] = _cid("goal", cluster["goal_id"], cluster["kind"], cluster.get("failure_mode"))
        cluster["objective_id"] = OBJECTIVE_ID
        cluster["ordinal"] = ordinal
        cluster["parent_goal_cid"] = campaign_cid
        cluster["status"] = "open"
        members = [item for item in labeled if item.get("goal_id") == cluster["goal_id"]]
        citations = sorted({str(item.get("legal_id") or "") for item in members if item.get("legal_id")})
        goals.append(cluster)
        edges.append(
            {
                "parent": campaign_cid,
                "child": cluster["goal_cid"],
                "parent_goal_cid": campaign_cid,
                "child_goal_cid": cluster["goal_cid"],
                "edge_kind": "goal_decomposition",
            }
        )
        if cluster.get("kind") == "architecture-decision" and len(citations) > 1:
            for citation in citations:
                sub_id = f"{GOAL_PREFIX}{next_sub:03d}"
                next_sub += 1
                sub_cid = _cid("goal", sub_id, "subgoal", citation)
                subset = [item for item in members if str(item.get("legal_id") or "") == citation]
                goals.append(
                    {
                        "admitted": False,
                        "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in subset),
                        "estimated_validation_seconds": sum(
                            int(item.get("estimated_validation_seconds") or 0) for item in subset
                        ),
                        "failure_mode": cluster.get("failure_mode") or "",
                        "formalized": False,
                        "goal_alias": sub_id,
                        "goal_cid": sub_cid,
                        "goal_id": sub_id,
                        "kind": "subgoal",
                        "legal_id": citation,
                        "objective_id": OBJECTIVE_ID,
                        "ordinal": len(goals) + 1,
                        "parent_goal_cid": cluster["goal_cid"],
                        "priority": "P1",
                        "resolves": [str(item["task_id"]) for item in subset],
                        "repair_targets": [
                            str(item)
                            for item in (subset[0].get("replace") or [])
                            if str(item)
                        ] if subset else [],
                        "source_span_ids": [str(item.get("source_span_id") or "") for item in subset],
                        "status": "open",
                        "title": "Subgoal: "
                        + citation
                        + (": " + str(subset[0].get("failure_mode") or "") if subset else ""),
                    }
                )
                edges.append(
                    {
                        "parent": cluster["goal_cid"],
                        "child": sub_cid,
                        "parent_goal_cid": cluster["goal_cid"],
                        "child_goal_cid": sub_cid,
                        "edge_kind": "goal_decomposition",
                    }
                )
                for item in subset:
                    item["goal_id"] = sub_id
                    item["goal_cid"] = sub_cid
                    item["parent_goal_cid"] = cluster["goal_cid"]
        else:
            span_ids: list[str] = []
            for item in members:
                span = str(item.get("source_span_id") or "")
                if span and span not in span_ids:
                    span_ids.append(span)
            if span_ids:
                for span in span_ids:
                    sub_id = f"{GOAL_PREFIX}{next_sub:03d}"
                    next_sub += 1
                    sub_cid = _cid("goal", sub_id, "subgoal", span)
                    subset = [item for item in members if str(item.get("source_span_id") or "") == span]
                    goals.append(
                        {
                            "admitted": False,
                            "estimated_tokens": sum(int(item.get("estimated_tokens") or 0) for item in subset),
                            "estimated_validation_seconds": sum(
                                int(item.get("estimated_validation_seconds") or 0) for item in subset
                            ),
                            "failure_mode": cluster.get("failure_mode") or "",
                            "formalized": False,
                            "goal_alias": sub_id,
                            "goal_cid": sub_cid,
                            "goal_id": sub_id,
                            "kind": "subgoal",
                            "objective_id": OBJECTIVE_ID,
                            "ordinal": len(goals) + 1,
                            "parent_goal_cid": cluster["goal_cid"],
                            "priority": "P1",
                            "resolves": [str(item["task_id"]) for item in subset],
                            "repair_targets": [
                                str(item)
                                for item in (subset[0].get("replace") or [])
                                if str(item)
                            ] if subset else [],
                            "source_span_ids": [span],
                            "status": "open",
                            "title": f"Subgoal: {span}"
                            + (": " + str(subset[0].get("failure_mode") or "") if subset else ""),
                        }
                    )
                    edges.append(
                        {
                            "parent": cluster["goal_cid"],
                            "child": sub_cid,
                            "parent_goal_cid": cluster["goal_cid"],
                            "child_goal_cid": sub_cid,
                            "edge_kind": "goal_decomposition",
                        }
                    )
                    for item in subset:
                        item["goal_id"] = sub_id
                        item["goal_cid"] = sub_cid
                        item["parent_goal_cid"] = cluster["goal_cid"]
            else:
                for item in members:
                    item["goal_cid"] = cluster["goal_cid"]
                    item["parent_goal_cid"] = campaign_cid
    default_goal_id = f"{GOAL_PREFIX}010"
    default_cid = _cid("goal", default_goal_id, "ungrouped")
    ungrouped = [item for item in labeled if not item.get("goal_cid")]
    if ungrouped:
        goals.append(
            {
                "admitted": False,
                "formalized": False,
                "goal_alias": default_goal_id,
                "goal_cid": default_cid,
                "goal_id": default_goal_id,
                "kind": "ungrouped",
                "objective_id": OBJECTIVE_ID,
                "ordinal": len(goals) + 1,
                "parent_goal_cid": campaign_cid,
                "priority": "P2",
                "resolves": [str(item["task_id"]) for item in ungrouped],
                "source_span_ids": [str(item.get("source_span_id") or "") for item in ungrouped],
                "status": "open",
                "title": "Ungrouped autoformal discrepancies",
            }
        )
        edges.append(
            {
                "parent": campaign_cid,
                "child": default_cid,
                "parent_goal_cid": campaign_cid,
                "child_goal_cid": default_cid,
                "edge_kind": "goal_decomposition",
            }
        )
        for item in ungrouped:
            item["goal_id"] = default_goal_id
            item["goal_cid"] = default_cid
            item["parent_goal_cid"] = campaign_cid
    for index, task in enumerate(labeled, start=1):
        task["objective_id"] = OBJECTIVE_ID
        task["plan_cid"] = plan_cid
        task["ordinal"] = index
        task["task_cid"] = _cid("task", task.get("task_id"), task.get("source_span_id"))
        task["status"] = "ready"
        task["is_schedulable"] = True
        task["review_only"] = False
        task["completion"] = "evidence"
        task["admitted"] = False
        task["formalized"] = False
        task["proof_authoritative"] = False
        task["match_is_not_admit"] = True
        task["outputs"] = [{"path": "workspace/todo-queues/uscode-autoformal-loop.todo.md"}]
        task["acceptance_criteria"] = [str(task.get("acceptance") or "Do not mark formalized.")]
        task["validation_commands"] = [
            {"argv": ["python3", "-m", "pytest", "tests/unit/logic/test_supervisor_loop.py", "-q"]}
        ]
        task["depends_on"] = list(task.get("depends_on") or [])
    campaign["resolves"] = [goal["goal_id"] for goal in goals if goal["goal_id"] != CAMPAIGN_GOAL_ID]
    campaign["source_span_ids"] = [str(item.get("source_span_id") or "") for item in labeled]
    campaign["estimated_tokens"] = sum(int(item.get("estimated_tokens") or 0) for item in labeled)
    campaign["validation_commands"] = [
        {"argv": ["python3", "-m", "pytest", "tests/unit/logic/test_supervisor_loop.py", "-q"]}
    ]
    campaign["acceptance_criteria"] = [
        "Do not mark formalized. Child goals and todos must round-trip or stay explicit."
    ]
    tree = {
        "edges": edges,
        "goal_edges": edges,
        "goals": goals,
        "objective_id": OBJECTIVE_ID,
        "plan_cid": plan_cid,
        "tasks": labeled,
    }
    from .supervisor_dispatch import attach_dispatch

    allowed = (
        "agreement",
        "packet_directory",
        "code_identity",
        "model_identity",
        "job_template",
        "accelerate_root",
        "database",
        "runtime_root",
        "release_id",
        "query",
    )
    options = {key: value for key, value in dict(dispatch or {}).items() if key in allowed}
    options.setdefault("release_id", release_id)
    attach_dispatch(tree, **options)
    return tree


def resolve_goals(
    goals: Sequence[Mapping[str, Any]],
    *,
    proved_span_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A goal resolves when every listed source span has a round-trip receipt."""

    proved = {str(item) for item in proved_span_ids if str(item)}
    resolved: list[dict[str, Any]] = []
    open_goals: list[dict[str, Any]] = []
    for goal in goals:
        item = dict(goal)
        spans = [str(span) for span in item.get("source_span_ids") or [] if str(span)]
        if not spans or all(span in proved for span in spans):
            # DuckDB closed set uses verified_complete for admitted proof.
            # A compile round-trip is only provisionally complete.
            item["status"] = "provisionally_complete"
            resolved.append(item)
        else:
            item["status"] = "open"
            open_goals.append(item)
    return open_goals, resolved


def supervisor_population(
    tree: Mapping[str, Any],
    *,
    repository_tree_id: str = "tree:uscode-autoformal",
    proofs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """DuckDB DatabaseTaskSource.materialize payload. Not JSONL."""

    plan_cid = str(tree.get("plan_cid") or _cid("plan", CAMPAIGN_GOAL_ID))
    goals = [dict(item) for item in tree.get("goals") or []]
    campaign_cid = next((item["goal_cid"] for item in goals if item.get("kind") == "campaign"), "")
    return {
        "admitted": False,
        "formalized": False,
        "goals": goals,
        "goal_edges": [dict(item) for item in tree.get("goal_edges") or []],
        "jsonl_written": False,
        "plan_root_cid": plan_cid,
        "plans": [
            {
                "admitted": False,
                "formalized": False,
                "goal_cid": campaign_cid,
                "plan_alias": "autoformal-loop",
                "plan_cid": plan_cid,
                "proofs": list(proofs),
                "status": "active",
            }
        ],
        "repository_tree_id": repository_tree_id,
        "schema": POPULATION_SCHEMA,
        "tasks": [dict(item) for item in tree.get("tasks") or []],
        "wrote_compiler": False,
    }


def _ensure_span_subgoals(tree: dict[str, Any]) -> dict[str, Any]:
    """One open subgoal per source span, under its failure goal or the campaign.

    An ungrouped bucket is not a second copy of the default todo goal.
    """

    goals = [dict(goal) for goal in tree.get("goals") or []]
    tasks = [dict(task) for task in tree.get("tasks") or []]
    edges = [dict(edge) for edge in tree.get("goal_edges") or []]
    campaign = next((goal for goal in goals if goal.get("kind") == "campaign"), None)
    if campaign is None:
        return tree
    drop = {goal["goal_cid"] for goal in goals if goal.get("kind") == "ungrouped"}
    goals = [goal for goal in goals if goal["goal_cid"] not in drop]
    edges = [
        edge for edge in edges
        if edge.get("child_goal_cid") not in drop and edge.get("parent_goal_cid") not in drop
    ]
    spans: list[str] = []
    for task in tasks:
        span = str(task.get("source_span_id") or "")
        if span and span not in spans:
            spans.append(span)
    next_sub = 500
    for span in spans:
        subset = [task for task in tasks if str(task.get("source_span_id") or "") == span]
        if subset and all(
            any(
                goal.get("goal_cid") == task.get("goal_cid") and goal.get("kind") == "subgoal"
                for goal in goals
            )
            for task in subset
        ):
            continue
        sub_id = f"{GOAL_PREFIX}{next_sub:03d}"
        next_sub += 1
        sub_cid = _cid("goal", sub_id, "subgoal", span)
        parent = campaign["goal_cid"]
        current = str(subset[0].get("goal_cid") or "") if subset else ""
        if any(goal.get("goal_cid") == current and goal.get("kind") == "architecture-decision" for goal in goals):
            parent = current
        goals.append(
            {
                "admitted": False,
                "failure_mode": str(subset[0].get("failure_mode") or "") if subset else "",
                "formalized": False,
                "goal_alias": sub_id,
                "goal_cid": sub_cid,
                "goal_id": sub_id,
                "kind": "subgoal",
                "objective_id": OBJECTIVE_ID,
                "ordinal": len(goals) + 1,
                "parent_goal_cid": parent,
                "priority": "P1",
                "resolves": [str(task.get("task_id") or "") for task in subset],
                "repair_targets": [
                    str(item) for item in (subset[0].get("replace") or []) if str(item)
                ] if subset else [],
                "source_span_ids": [span],
                "status": "open",
                "title": f"Subgoal: {span}"
                + (": " + str(subset[0].get("failure_mode") or "") if subset else ""),
            }
        )
        edges.append(
            {
                "parent": parent,
                "child": sub_cid,
                "parent_goal_cid": parent,
                "child_goal_cid": sub_cid,
                "edge_kind": "goal_decomposition",
            }
        )
        for task in subset:
            task["goal_id"] = sub_id
            task["goal_cid"] = sub_cid
            task["parent_goal_cid"] = parent
    tree["goals"] = goals
    tree["tasks"] = tasks
    tree["goal_edges"] = edges
    tree["edges"] = edges
    return tree


def _child_goals(task_source: Any, parent_cid: str) -> list[Mapping[str, Any]]:
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT goal_cid FROM goals WHERE parent_goal_cid = ?",
            [parent_cid],
        ).fetchall()
    children = []
    for row in rows:
        goal = task_source._intent.get_goal(str(row[0]))
        if goal is not None:
            children.append(goal)
    return children


def _roll_inconclusive_parents(task_source: Any, child: Mapping[str, Any]) -> list[str]:
    """Park a parent only when every child subgoal is already inconclusive."""

    updated: list[str] = []
    parent_cid = str(child.get("parent_goal_cid") or "")
    seen: set[str] = set()
    while parent_cid and parent_cid not in seen:
        seen.add(parent_cid)
        parent = task_source._intent.get_goal(parent_cid)
        if parent is None:
            break
        children = _child_goals(task_source, parent_cid)
        if not children or any(
            str(item.get("status") or "") != "analysis_inconclusive" for item in children
        ):
            break
        keys: list[str] = []
        for item in children:
            body = item.get("body") if isinstance(item.get("body"), Mapping) else {}
            receipt = body.get("completion_receipt") if isinstance(body, Mapping) else {}
            if not isinstance(receipt, Mapping):
                continue
            for key in receipt.get("proposal_keys") or []:
                text = str(key)
                if text in {"parser", "compiler", "decompiler"} and text not in keys:
                    keys.append(text)
        keys.sort()
        if str(parent.get("status") or "") != "analysis_inconclusive":
            task_source._intent.cas_goal_status(
                goal_cid=str(parent["goal_cid"]),
                expected_revision=int(parent["revision"]),
                new_status="analysis_inconclusive",
                receipt={
                    "admitted": False,
                    "applied": False,
                    "formalized": False,
                    "imported": False,
                    "operation": "router_proposal_review",
                    "proposal_keys": keys,
                    "wrote_compiler": False,
                },
            )
            updated.append(str(parent["goal_cid"]))
        parent_cid = str(parent.get("parent_goal_cid") or "")
    return updated


def goal_status_counts(task_source: Any) -> dict[str, Any]:
    """Count goal statuses. Inconclusive is not verified-complete and not an admit."""

    counts: dict[str, int] = {}
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) FROM goals GROUP BY status"
        ).fetchall()
    for row in rows:
        counts[str(row[0] or "")] = int(row[1])
    inconclusive = inconclusive_goals(task_source)
    opened = open_goals(task_source)
    return {
        "admitted": False,
        "formalized": False,
        "goal_status_counts": counts,
        "inconclusive_goal_count": counts.get("analysis_inconclusive", 0),
        "inconclusive_goals": inconclusive,
        "open_goal_count": counts.get("open", 0),
        "open_goals": opened,
        "verified_complete_count": counts.get("verified_complete", 0),
    }


def _ready_tasks_by_goal(task_source: Any) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT task_cid, goal_cid, status FROM tasks"
        ).fetchall()
    for row in rows:
        if str(row[2] or "") != "ready":
            continue
        grouped.setdefault(str(row[1] or ""), []).append(str(row[0]))
    for task_ids in grouped.values():
        task_ids.sort()
    return grouped


def _goals_with_status(task_source: Any, status: str) -> list[dict[str, Any]]:
    ready_by_goal = _ready_tasks_by_goal(task_source)
    with task_source._intent._connection(write=False) as connection:
        rows = connection.execute(
            "SELECT goal_cid FROM goals WHERE status = ? ORDER BY goal_cid",
            [status],
        ).fetchall()
    listed: list[dict[str, Any]] = []
    for row in rows:
        goal = task_source._intent.get_goal(str(row[0]))
        if goal is None or str(goal.get("status") or "") != status:
            continue
        body = goal.get("body") if isinstance(goal.get("body"), Mapping) else {}
        receipt = body.get("completion_receipt") if isinstance(body.get("completion_receipt"), Mapping) else {}
        keys = [
            str(key)
            for key in (receipt.get("proposal_keys") or [])
            if str(key) in {"parser", "compiler", "decompiler"}
        ]
        spans = [str(item) for item in body.get("source_span_ids") or [] if str(item)]
        targets = [str(item) for item in body.get("repair_targets") or [] if str(item)]
        listed.append({
            "admitted": False,
            "formalized": False,
            "goal_cid": str(goal.get("goal_cid") or ""),
            "kind": str(body.get("kind") or ""),
            "parent_goal_cid": str(goal.get("parent_goal_cid") or ""),
            "proposal_keys": keys,
            "ready_task_cids": list(ready_by_goal.get(str(goal.get("goal_cid") or ""), [])),
            "repair_targets": targets,
            "source_span_ids": spans,
            "status": status,
            "title": str(goal.get("title") or ""),
        })
    return listed


def ready_task_cids_under_inconclusive_goals(task_source: Any) -> set[str]:
    """Ready todos whose goal is already parked. A claim must not take these."""

    intent = getattr(task_source, "_intent", None)
    if intent is None:
        return set()
    with intent._connection(write=False) as connection:
        goal_rows = connection.execute(
            "SELECT goal_cid FROM goals WHERE status = ?",
            ["analysis_inconclusive"],
        ).fetchall()
        task_rows = connection.execute(
            "SELECT task_cid, goal_cid, status FROM tasks"
        ).fetchall()
    parked = {str(row[0]) for row in goal_rows}
    return {
        str(row[0])
        for row in task_rows
        if str(row[2] or "").lower() == "ready" and str(row[1] or "") in parked
    }


def claim_block_for_inconclusive_goals(task_source: Any) -> dict[str, Any]:
    """Explain a refused claim when ready todos sit under parked goals."""

    blocked = sorted(ready_task_cids_under_inconclusive_goals(task_source))
    blocked_set = set(blocked)
    claimable: list[str] = []
    intent = getattr(task_source, "_intent", None)
    if intent is not None:
        with intent._connection(write=False) as connection:
            rows = connection.execute("SELECT task_cid, status FROM tasks").fetchall()
        claimable = sorted(
            str(row[0])
            for row in rows
            if str(row[1] or "").lower() == "ready" and str(row[0]) not in blocked_set
        )
    return {
        "admitted": False,
        "claim_blocked_reason": "goals_inconclusive" if blocked else "",
        "claim_blocked_task_cids": blocked,
        "claimable_ready_task_cids": claimable,
        "formalized": False,
    }


def open_goals(task_source: Any) -> list[dict[str, Any]]:
    """Name goals the supervisor can still work. Parked goals are not included."""

    return _goals_with_status(task_source, "open")


def inconclusive_goals(task_source: Any) -> list[dict[str, Any]]:
    """Name parked goals. This does not reopen them or mark them complete."""

    return _goals_with_status(task_source, "analysis_inconclusive")


def mark_span_subgoal_review(
    task_source: Any,
    task_cid: str,
    proposal_sha256: str,
    proposal_keys: Sequence[str] = (),
) -> dict[str, Any]:
    """Mark one span subgoal inconclusive. Do not close the campaign or admit it."""

    keys = [str(key) for key in proposal_keys or [] if str(key) in {"parser", "compiler", "decompiler"}]
    task = task_source.get(str(task_cid or ""))
    goal_cid = str(getattr(task, "goal_cid", "") or "") if task is not None else ""
    unchanged = {
        "admitted": False,
        "formalized": False,
        "goal_cid": goal_cid,
        "goal_status": "",
        "proposal_keys": keys,
        "rolled_up": [],
        "updated": False,
        "wrote_compiler": False,
    }
    if task is None or not goal_cid:
        return unchanged
    goal = task_source._intent.get_goal(goal_cid)
    if goal is None:
        return unchanged
    body = goal.get("body") if isinstance(goal.get("body"), Mapping) else {}
    if body.get("kind") != "subgoal":
        return unchanged
    if str(goal.get("status") or "") == "analysis_inconclusive":
        unchanged["goal_status"] = "analysis_inconclusive"
        unchanged["rolled_up"] = _roll_inconclusive_parents(task_source, goal)
        return unchanged
    task_source._intent.cas_goal_status(
        goal_cid=str(goal["goal_cid"]),
        expected_revision=int(goal["revision"]),
        new_status="analysis_inconclusive",
        receipt={
            "admitted": False,
            "applied": False,
            "formalized": False,
            "imported": False,
            "operation": "router_proposal_review",
            "proposal_keys": keys,
            "proposal_sha256": str(proposal_sha256 or ""),
            "wrote_compiler": False,
        },
    )
    return {
        "admitted": False,
        "formalized": False,
        "goal_cid": str(goal["goal_cid"]),
        "goal_status": "analysis_inconclusive",
        "proposal_keys": keys,
        "rolled_up": _roll_inconclusive_parents(task_source, goal),
        "updated": True,
        "wrote_compiler": False,
    }


def attach_goal_tree(
    source: Any,
    agreement: Mapping[str, Any],
    *,
    release_id: str,
    campaign_title: str = "US Constitution autoformal campaign",
) -> dict[str, Any]:
    """Attach sealed repair todos to a campaign, failure goal, and span subgoals.

    Does not call the router or replace the sealed packet on an existing task.
    """

    tasks = discrepancy_tasks(agreement, query=campaign_title, release_id=release_id)
    if not tasks:
        return {
            "admitted": False,
            "formalized": False,
            "goal_count": 0,
            "linked_tasks": 0,
            "router_called": False,
            "subgoal_count": 0,
            "wrote_compiler": False,
        }
    tree = _ensure_span_subgoals(
        spawn_goal_tree(tasks, release_id=release_id, campaign_title=campaign_title)
    )
    population = supervisor_population(tree, repository_tree_id="tree:us-constitution")
    population["tasks"] = []
    ingest_population(source, population)
    span_goal = {
        str(item.get("source_span_id") or ""): str(item.get("goal_cid") or "")
        for item in tree["tasks"]
        if item.get("source_span_id") and item.get("goal_cid")
    }
    from .supervisor_queue import read_packet

    linked = 0
    cursor = ""
    while True:
        page = source.list_tasks(cursor=cursor, limit=100)
        for record in page.tasks:
            body = record.body if isinstance(record.body, Mapping) else {}
            path = str(body.get("packet_path") or "")
            digest = str(body.get("packet_sha256") or "")
            if not path or not digest:
                continue
            packet = read_packet(Path(path), digest)
            row = packet.get("row") if isinstance(packet, Mapping) else {}
            span = str((row or {}).get("source_span_id") or "")
            goal_cid = span_goal.get(span) or ""
            if not goal_cid:
                continue
            if record.goal_cid != goal_cid:
                source._intent.upsert_task(
                    task_cid=record.task_cid,
                    task_alias=record.task_alias,
                    goal_cid=goal_cid,
                    ordinal=int(record.ordinal),
                    status=str(record.status),
                    priority=str(record.priority or "P0"),
                    plan_cid=str(tree["plan_cid"]),
                    objective_id=OBJECTIVE_ID,
                    body=dict(body),
                    expected_revision=int(record.revision),
                    dependencies=list(record.dependencies),
                    outputs=list(record.outputs),
                    acceptance=list(record.acceptance),
                    validations=list(record.validations),
                )
            linked += 1
        cursor = str(getattr(page, "next_cursor", "") or "")
        if not cursor:
            break
    return {
        "admitted": False,
        "formalized": False,
        "goal_count": len(tree["goals"]),
        "linked_tasks": linked,
        "router_called": False,
        "subgoal_count": sum(1 for goal in tree["goals"] if goal.get("kind") == "subgoal"),
        "wrote_compiler": False,
    }


def ingest_population(source: Any, population: Mapping[str, Any]) -> dict[str, Any]:
    """Hand the goal/todo tree to DatabaseTaskSource.materialize."""

    receipt = source.materialize(population)
    if hasattr(receipt, "get"):
        payload = dict(receipt)
    else:
        payload = {"task_count": 0}
    payload["admitted"] = False
    payload["formalized"] = False
    payload["jsonl_written"] = False
    payload["wrote_compiler"] = False
    return payload


def run_supervisor_loop(
    autoformal: Callable[[], Mapping[str, Any]],
    *,
    ingest: Callable[..., dict[str, Any]] | None = None,
    max_rounds: int = 3,
    query: str = "",
    release_id: str = "",
    board_path: Any = None,
    upload: Callable[..., dict[str, Any]] | None = None,
    native: Callable[..., dict[str, Any]] | None = None,
    source: Any | None = None,
    repository_tree_id: str = "tree:uscode-autoformal",
    prior: Mapping[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
    compile_one: Callable[[str], Mapping[str, Any]] | None = None,
    dispatch: Mapping[str, Any] | None = None,
    lake_probe: Callable[..., Mapping[str, Any]] | None = None,
    lean_check: Callable[..., Mapping[str, Any]] | None = None,
    span_cache: Any | None = None,
    path_hashes: Mapping[str, str] | None = None,
    code_identity: str = "",
) -> dict[str, Any]:
    """Run autoformal, ingest DuckDB-shaped goals/todos, recurse until goals resolve."""

    if max_rounds < 1 or max_rounds > MAX_ROUNDS:
        raise SupervisorLoopError(f"max_rounds must be 1..{MAX_ROUNDS}")
    seen, proved = _prior_span_state(prior)
    resumed = bool(seen or proved or prior)
    rounds: list[dict[str, Any]] = []
    stop = "max_rounds"
    last_open: list[dict[str, Any]] = []
    last_tasks: list[dict[str, Any]] = list(
        ((prior or {}).get("population") or {}).get("tasks") or []
    )
    corpus_gaps: dict[str, dict[str, Any]] = {}
    for task in last_tasks:
        span = _span_id(task)
        if span and str(task.get("work_kind") or "") != "autoencoder_training":
            corpus_gaps[span] = dict(task)
    prior_remaining = {str(item) for item in (prior or {}).get("remaining_span_ids") or [] if str(item)}
    retrieved_rounds = 0
    gap_ids: set[str] = set(corpus_gaps) | prior_remaining
    _emit_progress(
        f"PROGRESS start max_rounds={max_rounds} resumed={str(resumed).lower()} "
        f"prior_compiled={len(proved)} prior_seen_gaps={len(seen)} "
        f"prior_remaining={len(prior_remaining)}",
        log=log,
        board_path=board_path,
    )
    for index in range(1, max_rounds + 1):
        recensed = False
        try:
            recensus_tick = (
                index > 1
                and compile_one is not None
                and last_tasks
                and retrieved_rounds >= 1
                and index % 2 == 0
            )
            if recensus_tick:
                recensed = True
                _emit_progress(
                    f"PROGRESS recensus round={index}/{max_rounds} open_todos={len(last_tasks)} "
                    f"corpus_remaining={len(gap_ids - proved)}",
                    log=log,
                    board_path=board_path,
                )
                tick = recensus_open_todos(
                    {"population": {"tasks": last_tasks}, "proved_span_ids": sorted(proved)},
                    compile_one,
                    dispatch=dispatch,
                    span_cache=span_cache,
                )
                agreement = tick["agreement"]
                receipt = {"rows": agreement.get("rows") or []}
            else:
                _emit_progress(
                    f"PROGRESS retrieve round={index}/{max_rounds} "
                    f"corpus_compiled={len(proved)} corpus_remaining={len(gap_ids - proved)}",
                    log=log,
                    board_path=board_path,
                )
                receipt = autoformal()
                retrieved_rounds += 1
                agreement = agreement_from_run(receipt)
        except SupervisorLoopError:
            raise
        except Exception as exc:
            agreement = agreement_from_exception(exc, round_index=index)
            receipt = {"error": str(exc)}
        cache_receipt: dict[str, Any] = {}
        if span_cache is not None:
            cache_receipt = dict(
                span_cache.apply_census(
                    agreement,
                    code_identity=code_identity,
                    path_hashes=path_hashes,
                )
                or {}
            )
            _emit_progress(
                f"CACHE round={index} sealed={cache_receipt.get('sealed_total')} "
                f"gaps={cache_receipt.get('gap_total')} pending={cache_receipt.get('pending_total')} "
                f"unsealed={cache_receipt.get('unsealed')} "
                f"changed_paths={','.join(cache_receipt.get('changed_paths') or []) or 'none'}",
                log=log,
                board_path=board_path,
            )
            if compile_one is not None:
                drained = span_cache.process_pending(
                    compile_one,
                    code_identity=code_identity,
                    path_hashes=path_hashes,
                )
                cache_receipt["drained"] = drained
                if int(drained.get("processed") or 0) or int(drained.get("skipped_sealed") or 0):
                    _emit_progress(
                        f"CACHE drain processed={drained.get('processed')} "
                        f"skipped_sealed={drained.get('skipped_sealed')} "
                        f"sealed_total={drained.get('sealed_total')}",
                        log=log,
                        board_path=board_path,
                    )
            lean = span_cache.build_lean_units(
                check=lean_check,
                verify=lean_check is not None,
            )
            cache_receipt["lean"] = {
                "statute_count": lean.get("statute_count"),
                "term_count": lean.get("term_count"),
                "admitted": False,
                "formalized": False,
            }
            for item in (lean.get("statutes") or [])[:8]:
                _emit_progress(
                    f"STATUTE legal_id={item.get('legal_id')} clauses={item.get('clause_count')} "
                    f"lake_ok={str(bool(item.get('lake_ok'))).lower()} "
                    f"error={item.get('lake_error') or 'none'}",
                    log=log,
                    board_path=board_path,
                )
            for item in (lean.get("terms") or [])[:12]:
                _emit_progress(
                    f"TERM kind={item.get('kind')} value={item.get('value')} "
                    f"statutes={item.get('statute_count')} "
                    f"lake_ok={str(bool(item.get('lake_ok'))).lower()} "
                    f"error={item.get('lake_error') or 'none'}",
                    log=log,
                    board_path=board_path,
                )
        stage = _emit_census_stage(
            agreement,
            index=index,
            log=log,
            board_path=board_path,
            lake_probe=lake_probe,
        )
        proofs = proofs_from_agreement(agreement)
        new_compiled = {
            str(item.get("source_span_id") or "")
            for item in proofs
            if item.get("source_span_id") and str(item.get("source_span_id") or "") not in proved
        }
        proved |= {str(item.get("source_span_id") or "") for item in proofs if item.get("source_span_id")}
        batch_todos = discrepancy_tasks(agreement, query=query, release_id=release_id)
        batch_gap_ids = {_span_id(task) for task in batch_todos if _span_id(task)}
        new_ids = batch_gap_ids - seen
        for span in list(corpus_gaps):
            if span in proved:
                corpus_gaps.pop(span, None)
        for task in batch_todos:
            span = _span_id(task)
            if span and span not in proved:
                corpus_gaps[span] = dict(task)
        todos = [dict(item) for item in corpus_gaps.values()]
        dispatch_options = dict(dispatch or {})
        dispatch_options["agreement"] = agreement
        dispatch_options.setdefault("query", query)
        dispatch_options.setdefault("release_id", release_id)
        tree = spawn_goal_tree(todos, release_id=release_id, dispatch=dispatch_options)
        todos = tree["tasks"]
        open_goals, resolved_goals = resolve_goals(tree["goals"], proved_span_ids=sorted(proved))
        status_by_id = {
            str(item.get("goal_id") or ""): str(item.get("status") or "open")
            for item in list(open_goals) + list(resolved_goals)
        }
        for goal in tree["goals"]:
            goal["status"] = status_by_id.get(str(goal.get("goal_id") or ""), str(goal.get("status") or "open"))
        last_open = open_goals
        last_tasks = list(todos)
        gap_ids = {_span_id(task) for task in todos if _span_id(task)} | prior_remaining
        remaining_ids = sorted(gap_ids - proved)
        ingested: dict[str, Any] = {"jsonl_written": False, "task_count": 0, "goal_count": 0}
        population = supervisor_population(
            tree, repository_tree_id=repository_tree_id, proofs=proofs
        )
        if todos:
            submit = ingest or submit_discrepancies
            ingested = submit(
                agreement,
                board_path=board_path,
                query=query,
                release_id=release_id,
                upload=None,
                native=native,
                goals=tree["goals"],
                tasks=todos,
            )
            ingested = dict(ingested)
            ingested["goals"] = tree["goals"]
            ingested["population"] = population
            ingested["jsonl_written"] = False
            ingested["wrote_compiler"] = False
        if source is not None:
            ingested = dict(ingested)
            ingested["native_population"] = ingest_population(source, population)
            ingested["jsonl_written"] = False
            ingested["wrote_compiler"] = False
        native_population = dict(ingested.get("native_population") or {})
        compiled = len(proved)
        operative = compiled + len(remaining_ids)
        modes = sorted({str(task.get("failure_mode") or "") for task in todos if task.get("failure_mode")})
        from .supervisor_dispatch import dispatch_counts

        counts = dispatch_counts(todos)
        phase = "recensus" if recensed else "retrieve"
        _emit_progress(
            f"PROGRESS round={index}/{max_rounds} phase={phase} "
            f"compiled={compiled}/{operative} remaining={len(remaining_ids)} "
            f"new_gaps={len(new_ids)} new_compiled={len(new_compiled)} "
            f"proofs_total={len(proved)} open_goals={len(open_goals)} "
            f"provisionally_complete={len(resolved_goals)} "
            f"ingested_tasks={int(ingested.get('task_count') or 0)} "
            f"failure_modes={','.join(modes) or 'none'}",
            log=log,
            board_path=board_path,
        )
        _emit_progress(
            f"CENSUS round={index} compiled_total={compiled} remaining={len(remaining_ids)} "
            f"new_compiled={len(new_compiled)} new_gaps={len(new_ids)} phase={phase} "
            f"compiled_ids={','.join(sorted(new_compiled)) or 'none'} "
            f"remaining_ids={','.join(remaining_ids) or 'none'}",
            log=log,
            board_path=board_path,
        )
        _emit_progress(
            f"PROGRESS dispatch round={index} edit={counts['edit']} train={counts['train']} "
            f"review={counts['review']} sealed_packets={counts['sealed_packets']} "
            f"bound_training={counts['bound_training']}",
            log=log,
            board_path=board_path,
        )
        for task in todos[:12]:
            text = str(task.get("source_text") or task.get("text") or "")
            _emit_progress(
                f"PROGRESS gap id={_span_id(task)} "
                f"reason={task.get('failure_mode') or task.get('reason')} "
                f"work_kind={task.get('work_kind') or ''} "
                f"goal={task.get('goal_id')} "
                f"text={text[:160]}",
                log=log,
                board_path=board_path,
            )
        round_receipt = {
            "admitted": False,
            "formalized": False,
            "gap_count": len(remaining_ids),
            "goal_count": len(tree["goals"]),
            "goals": tree["goals"],
            "ingested_task_count": int(ingested.get("task_count") or 0),
            "native_population": native_population,
            "jsonl_written": False,
            "new_compiled_count": len(new_compiled),
            "new_error_count": len(new_ids),
            "open_goal_count": len(open_goals),
            "phase": phase,
            "population": population,
            "proof_count": len(proofs),
            "proofs": proofs,
            "resolved_goal_count": len(resolved_goals),
            "resolved_goals": resolved_goals,
            "round": index,
            "compiled_count": compiled,
            "operative_count": operative,
            "remaining_count": len(remaining_ids),
            "census_spans": stage["spans"],
            "lake": stage["lake"],
            "span_cache": cache_receipt,
            "wrote_compiler": False,
        }
        rounds.append(round_receipt)
        snapshot = census_snapshot_path(board_path)
        if snapshot is not None:
            write_census_snapshot(
                snapshot,
                {
                    "compiled_count": compiled,
                    "compiled_span_ids": sorted(proved),
                    "failure_modes": modes,
                    "open_goal_count": len(open_goals),
                    "phase": phase,
                    "remaining_count": len(remaining_ids),
                    "remaining_span_ids": remaining_ids,
                    "round": index,
                    "census_spans": stage["spans"],
                    "lake": stage["lake"],
                    "stop_reason": "",
                },
            )
        if not remaining_ids and not open_goals:
            stop = "goals_resolved"
            break
        if not remaining_ids:
            stop = "no_outstanding_todos"
            break
        if recensed and not new_ids and not new_compiled and index < max_rounds:
            _emit_progress(
                f"PROGRESS plateau round={index} remaining={len(remaining_ids)} "
                f"next=retrieve_more_uscode",
                log=log,
                board_path=board_path,
            )
            seen |= batch_gap_ids
            continue
        if (index > 1 or resumed) and not new_ids and not new_compiled:
            stop = "no_new_errors" if open_goals else "goals_resolved"
            _emit_progress(
                f"PROGRESS plateau round={index} remaining={len(remaining_ids)} "
                f"reason={'retrieval_returned_no_new_spans' if not recensed else 'recensus_unchanged'}",
                log=log,
                board_path=board_path,
            )
            break
        seen |= batch_gap_ids | gap_ids
    remaining_ids = sorted((gap_ids | prior_remaining) - proved) if rounds else sorted(prior_remaining - proved)
    compiled_ids = sorted(proved)
    remaining = len(remaining_ids)
    compiled_total = len(compiled_ids)
    note = (
        "census complete"
        if remaining == 0
        else (
            "remaining spans need compiler/parser coverage or a wider GraphRAG query; "
            "todos declare train or edit work"
        )
    )
    _emit_progress(
        f"PROGRESS stop={stop} compiled_total={compiled_total} remaining={remaining} "
        f"open_goals={len(last_open)} rounds={len(rounds)} "
        f"compiled_ids={','.join(compiled_ids) or 'none'} "
        f"remaining_ids={','.join(remaining_ids) or 'none'} "
        f"note={note}",
        log=log,
        board_path=board_path,
    )
    _emit_progress(
        f"CENSUS stop={stop} compiled_total={compiled_total} remaining={remaining} "
        f"admitted=false formalized=false",
        log=log,
        board_path=board_path,
    )
    huggingface: dict[str, Any] = {}
    last_population = (rounds[-1].get("population") if rounds else {}) or {}
    last_tasks = list(last_population.get("tasks") or [])
    if upload is not None and last_tasks:
        huggingface = dict(upload(last_tasks) or {})
        huggingface["jsonl_written"] = False
    return {
        "admitted": False,
        "formalized": False,
        "huggingface": huggingface,
        "jsonl_written": False,
        "open_goal_count": len(last_open),
        "population": last_population,
        "proof_count": sum(int(item["proof_count"]) for item in rounds),
        "round_count": len(rounds),
        "rounds": rounds,
        "schema": SCHEMA,
        "stop_reason": stop,
        "proved_span_ids": sorted(proved),
        "seen_span_ids": sorted(seen | {
            str(task.get("source_span_id") or "")
            for task in last_tasks
            if task.get("source_span_id")
        }),
        "todo_count": remaining,
        "compiled_count": compiled_total,
        "compiled_span_ids": compiled_ids,
        "remaining_count": remaining,
        "remaining_span_ids": remaining_ids,
        "census_spans": list((rounds[-1].get("census_spans") if rounds else []) or []),
        "lake": dict((rounds[-1].get("lake") if rounds else {}) or {}),
        "span_cache": dict((rounds[-1].get("span_cache") if rounds else {}) or {}),
        "wrote_compiler": False,
    }


def write_population_receipt(
    path: str | Path,
    loop_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """One JSON object the supervisor can reload. Not JSONL."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "open_goal_count": loop_receipt.get("open_goal_count"),
        "population": loop_receipt.get("population") or {},
        "compiled_count": loop_receipt.get("compiled_count"),
        "compiled_span_ids": list(loop_receipt.get("compiled_span_ids") or []),
        "proved_span_ids": list(loop_receipt.get("proved_span_ids") or []),
        "remaining_count": loop_receipt.get("remaining_count"),
        "remaining_span_ids": list(loop_receipt.get("remaining_span_ids") or []),
        "schema": POPULATION_SCHEMA,
        "seen_span_ids": list(loop_receipt.get("seen_span_ids") or []),
        "seen_document_ids": list(loop_receipt.get("seen_document_ids") or []),
        "stop_reason": loop_receipt.get("stop_reason"),
        "wrote_compiler": False,
    }
    destination.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"path": str(destination), "jsonl_written": False}


def loop_progress_report(loop_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Operator-facing corpus census for CLI JSON. Not a legal admit."""

    rounds = []
    for item in loop_receipt.get("rounds") or []:
        if not isinstance(item, Mapping):
            continue
        rounds.append(
            {
                "compiled_count": int(item.get("compiled_count") or 0),
                "new_compiled_count": int(item.get("new_compiled_count") or 0),
                "new_error_count": int(item.get("new_error_count") or 0),
                "phase": str(item.get("phase") or ""),
                "remaining_count": int(item.get("remaining_count") or 0),
                "round": item.get("round"),
            }
        )
    return {
        "admitted": False,
        "compiled_count": int(loop_receipt.get("compiled_count") or 0),
        "compiled_span_ids": list(loop_receipt.get("compiled_span_ids") or []),
        "formalized": False,
        "remaining_count": int(loop_receipt.get("remaining_count") or 0),
        "remaining_span_ids": list(loop_receipt.get("remaining_span_ids") or []),
        "rounds": rounds,
        "lake": dict(loop_receipt.get("lake") or {}),
        "stop_reason": loop_receipt.get("stop_reason"),
        "wrote_compiler": False,
    }


def write_census_snapshot(path: str | Path, loop_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Operator-facing census: compiled vs remaining. Not a legal admit."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    compiled_ids = [str(item) for item in loop_receipt.get("compiled_span_ids") or []]
    remaining_ids = [str(item) for item in loop_receipt.get("remaining_span_ids") or []]
    payload = {
        "admitted": False,
        "compiled_count": int(loop_receipt.get("compiled_count") or len(compiled_ids)),
        "compiled_span_ids": compiled_ids,
        "failure_modes": list(loop_receipt.get("failure_modes") or []),
        "formalized": False,
        "open_goal_count": loop_receipt.get("open_goal_count"),
        "phase": str(loop_receipt.get("phase") or ""),
        "remaining_count": int(loop_receipt.get("remaining_count") or len(remaining_ids)),
        "remaining_span_ids": remaining_ids,
        "round": loop_receipt.get("round"),
        "census_spans": list(loop_receipt.get("census_spans") or []),
        "lake": dict(loop_receipt.get("lake") or {}),
        "stop_reason": loop_receipt.get("stop_reason"),
        "wrote_compiler": False,
    }
    destination.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"path": str(destination), "jsonl_written": False}


def load_population_receipt(path: str | Path) -> dict[str, Any]:
    """Reload a loop population. JSONL is not accepted."""

    destination = Path(path)
    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SupervisorLoopError(f"cannot read population receipt: {destination}") from exc
    if not isinstance(payload, Mapping):
        raise SupervisorLoopError("population receipt must be one JSON object")
    if payload.get("schema") != POPULATION_SCHEMA:
        raise SupervisorLoopError("population receipt schema is not the supervisor population")
    if payload.get("jsonl_written") is True:
        raise SupervisorLoopError("population receipt must not be JSONL-authored")
    population = payload.get("population")
    if not isinstance(population, Mapping):
        raise SupervisorLoopError("population receipt is missing the goal/todo tree")
    return {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "open_goal_count": payload.get("open_goal_count"),
        "population": dict(population),
        "compiled_count": payload.get("compiled_count"),
        "compiled_span_ids": [str(item) for item in payload.get("compiled_span_ids") or []],
        "proved_span_ids": [str(item) for item in payload.get("proved_span_ids") or []],
        "remaining_count": payload.get("remaining_count"),
        "remaining_span_ids": [str(item) for item in payload.get("remaining_span_ids") or []],
        "schema": POPULATION_SCHEMA,
        "seen_span_ids": [str(item) for item in payload.get("seen_span_ids") or []],
        "seen_document_ids": [str(item) for item in payload.get("seen_document_ids") or []],
        "stop_reason": payload.get("stop_reason"),
        "wrote_compiler": False,
    }


def recensus_open_todos(
    prior: Mapping[str, Any],
    compile_one: Callable[[str], Mapping[str, Any]],
    *,
    dispatch: Mapping[str, Any] | None = None,
    span_cache: Any | None = None,
) -> dict[str, Any]:
    """Re-run autoformal on outstanding todo source text. Does not claim a task."""

    loaded = dict(prior)
    tasks = list((loaded.get("population") or {}).get("tasks") or [])
    if not tasks:
        raise SupervisorLoopError("no open todos to recensus")
    rows: list[dict[str, Any]] = []
    seen_spans: set[str] = set()
    for task in tasks:
        text = str(task.get("source_text") or task.get("text") or "")
        span_id = str(task.get("source_span_id") or task.get("id") or task.get("task_id") or "")
        if span_id and span_id in seen_spans:
            continue
        if span_id:
            seen_spans.add(span_id)
        legal_id = str(task.get("legal_id") or "")
        if not text:
            rows.append(
                {
                    "agrees": False,
                    "id": span_id or "missing-text",
                    "legal_id": legal_id,
                    "reason": "loop_error",
                    "skipped": False,
                    "source_span_id": span_id or "missing-text",
                    "text": "",
                }
            )
            continue
        cached = None
        if span_cache is not None:
            cached = span_cache.skip_compile(span_id, source_text=text)
        if cached is not None:
            rows.append(
                {
                    "agrees": True,
                    "canonical_citation": str(task.get("canonical_citation") or ""),
                    "decompiled": str(cached.get("decompiled") or ""),
                    "dropped": [],
                    "id": str(task.get("id") or span_id),
                    "legal_id": legal_id,
                    "reason": "",
                    "rule": dict(cached.get("rule") or {}),
                    "skipped": False,
                    "skipped_compile": True,
                    "source_span_id": span_id,
                    "text": text,
                }
            )
            continue
        result = compile_one(text)
        status = str(result.get("compiler_status") or result.get("status") or "")
        agrees = status in {"compiled", "roundtrip_ok"}
        rows.append(
            {
                "agrees": agrees,
                "canonical_citation": str(task.get("canonical_citation") or ""),
                "decompiled": str(result.get("decompiled") or ""),
                "dropped": [str(item) for item in result.get("unsupported_fields") or [] if str(item)],
                "id": str(task.get("id") or span_id),
                "legal_id": legal_id,
                "reason": "" if agrees else str(result.get("reason") or "compiler_abstain"),
                "rule": dict(result["rule"]) if isinstance(result.get("rule"), Mapping) else {},
                "skipped": False,
                "source_span_id": span_id,
                "text": text,
            }
        )
    operative = [row for row in rows if not row.get("skipped")]
    agreed = sum(1 for row in operative if row.get("agrees"))
    agreement = {
        "admitted": False,
        "agreed": agreed,
        "agrees": bool(operative) and agreed == len(operative),
        "formalized": False,
        "operative": len(operative),
        "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
        "rows": rows,
    }
    proofs = proofs_from_agreement(agreement)
    todos = discrepancy_tasks(agreement)
    dispatch_options = dict(dispatch or {})
    dispatch_options["agreement"] = agreement
    tree = spawn_goal_tree(todos, dispatch=dispatch_options)
    proved = {str(item.get("source_span_id") or "") for item in proofs if item.get("source_span_id")}
    proved |= {str(item) for item in loaded.get("proved_span_ids") or [] if str(item)}
    open_goals, resolved_goals = resolve_goals(tree["goals"], proved_span_ids=sorted(proved))
    status_by_id = {
        str(item.get("goal_id") or ""): str(item.get("status") or "open")
        for item in list(open_goals) + list(resolved_goals)
    }
    for goal in tree["goals"]:
        goal["status"] = status_by_id.get(str(goal.get("goal_id") or ""), str(goal.get("status") or "open"))
    stop = "goals_resolved" if not todos and not open_goals else (
        "goals_resolved" if not todos else "open_todos_remain"
    )
    return {
        "admitted": False,
        "agreement": agreement,
        "claimed": False,
        "formalized": False,
        "jsonl_written": False,
        "open_goals": open_goals,
        "proofs": proofs,
        "resolved_goals": resolved_goals,
        "stop_reason": stop,
        "tree": tree,
        "wrote_compiler": False,
    }


def _prior_span_state(prior: Mapping[str, Any] | None) -> tuple[set[str], set[str]]:
    seen: set[str] = set()
    proved: set[str] = set()
    if not isinstance(prior, Mapping):
        return seen, proved
    for key in prior.get("seen_span_ids") or []:
        if str(key):
            seen.add(str(key))
    for key in prior.get("proved_span_ids") or []:
        if str(key):
            proved.add(str(key))
    population = prior.get("population") or {}
    for task in population.get("tasks") or []:
        span = str(task.get("source_span_id") or "")
        if span:
            seen.add(span)
    for plan in population.get("plans") or []:
        for item in plan.get("proofs") or []:
            span = str(item.get("source_span_id") or "")
            if span:
                proved.add(span)
    return seen, proved
