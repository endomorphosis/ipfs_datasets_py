#!/usr/bin/env python3
"""Validate the sealed US Code sparse GraphRAG supervisor control plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


TASK_PREFIX = "USCIR-"
GOAL_PREFIX = "USCIR-G"
BOARD_NAMESPACE = "uscode-sparse-graphrag-v1"
EXPECTED_TASK_IDS = [f"{TASK_PREFIX}{index:03d}" for index in range(41)]
EXPECTED_INITIAL_READY = [
    "USCIR-001",
    "USCIR-002",
    "USCIR-003",
    "USCIR-004",
    "USCIR-006",
    "USCIR-007",
]
REQUIRED_TASK_FIELDS = {
    "status",
    "completion",
    "is_schedulable",
    "review_only",
    "priority",
    "track",
    "depends_on",
    "goal_id",
    "outputs",
    "validation",
    "board_namespace",
    "bundle",
    "parallel_lane",
    "resource_class",
    "token_class",
    "estimated_tokens",
    "predicted_files",
    "allow_concurrent_with",
    "conflict_policy",
    "preconditions",
    "effects",
    "acceptance",
}
REQUIRED_GOAL_FIELDS = {
    "status",
    "parent",
    "fib_priority",
    "track",
    "priority",
    "bundle",
    "goal",
    "evidence",
    "outputs",
    "validation",
    "acceptance",
    "gap_task",
    "refinement",
    "embedding_query",
    "ast_query",
    "parallel_lane",
    "conflict_policy",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _parse_records(
    path: Path,
    heading_pattern: re.Pattern[str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    current_id = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {}, [f"cannot read {path}: {type(exc).__name__}: {exc}"]

    for lineno, line in enumerate(lines, 1):
        match = heading_pattern.fullmatch(line)
        if match:
            current_id = match.group(1)
            if current_id in records:
                errors.append(f"{path}:{lineno}: duplicate record {current_id}")
            current = {"id": current_id, "title": match.group(2), "line": lineno}
            records[current_id] = current
            continue
        if line.startswith("## ") and current is not None:
            current = None
            current_id = ""
            continue
        if current is None or not line.startswith("- "):
            continue
        field = re.fullmatch(r"- ([^:]+):(.*)", line)
        if not field:
            errors.append(f"{path}:{lineno}: malformed metadata line")
            continue
        name = _key(field.group(1))
        if name in current:
            errors.append(f"{path}:{lineno}: duplicate field {name} in {current_id}")
        current[name] = field.group(2).strip()
    return records, errors


def _cycle(graph: dict[str, list[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    trail: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            start = trail.index(node)
            return trail[start:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        trail.append(node)
        for dependency in graph.get(node, []):
            found = visit(dependency)
            if found:
                return found
        trail.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for item in graph:
        found = visit(item)
        if found:
            return found
    return []


def _transitively_depends(
    task_id: str,
    expected: str,
    graph: dict[str, list[str]],
) -> bool:
    pending = list(graph.get(task_id, []))
    seen: set[str] = set()
    while pending:
        item = pending.pop()
        if item == expected:
            return True
        if item in seen:
            continue
        seen.add(item)
        pending.extend(graph.get(item, []))
    return False


def validate(root: Path) -> dict[str, Any]:
    todo_path = root / "docs/architecture/uscode_sparse_graphrag.todo.md"
    objectives_path = root / "docs/architecture/uscode_sparse_graphrag.objectives.md"
    plan_path = root / "docs/architecture/USCODE_SPARSE_GRAPHRAG_PLAN.md"
    config_path = root / "config/agent_supervisor_uscode_sparse_graphrag_scheduler.json"
    task_pattern = re.compile(r"## (USCIR-\d{3}) (.+)")
    goal_pattern = re.compile(r"## (USCIR-G\d{3}) (.+)")
    tasks, errors = _parse_records(todo_path, task_pattern)
    goals, goal_errors = _parse_records(objectives_path, goal_pattern)
    errors.extend(goal_errors)
    warnings: list[str] = []

    actual_ids = sorted(tasks)
    if actual_ids != EXPECTED_TASK_IDS:
        errors.append(
            "task IDs must be exactly USCIR-000 through USCIR-040; "
            f"missing={sorted(set(EXPECTED_TASK_IDS) - set(actual_ids))}, "
            f"extra={sorted(set(actual_ids) - set(EXPECTED_TASK_IDS))}"
        )

    graph: dict[str, list[str]] = {}
    completed: set[str] = set()
    output_owners: dict[str, list[str]] = defaultdict(list)
    for task_id, task in tasks.items():
        missing = sorted(REQUIRED_TASK_FIELDS - set(task))
        if missing:
            errors.append(f"{task_id}: missing fields {missing}")
        status = str(task.get("status", "")).lower()
        if status not in {"todo", "completed"}:
            errors.append(f"{task_id}: unsupported initial status {status!r}")
        if status == "completed":
            completed.add(task_id)
        if task.get("board_namespace") != BOARD_NAMESPACE:
            errors.append(f"{task_id}: board namespace mismatch")
        try:
            lane = int(str(task.get("parallel_lane", "")))
        except ValueError:
            lane = -1
        expected_lane = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16) % 4
        if lane != expected_lane:
            errors.append(f"{task_id}: lane {lane} must equal the supervisor full-ID hash shard ({expected_lane})")
        try:
            if int(str(task.get("estimated_tokens", "0"))) <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"{task_id}: estimated_tokens must be a positive integer")
        schedulable = str(task.get("is_schedulable", "")).lower()
        review_only = str(task.get("review_only", "")).lower()
        if schedulable not in {"true", "false"} or review_only not in {"true", "false"}:
            errors.append(f"{task_id}: schedulable/review flags must be true or false")
        if task_id != "USCIR-000" and schedulable != "true":
            errors.append(f"{task_id}: pending implementation task must be schedulable")
        goal_id = str(task.get("goal_id", ""))
        if goal_id not in goals:
            errors.append(f"{task_id}: unknown goal {goal_id!r}")
        dependencies = _csv(str(task.get("depends_on", "")))
        graph[task_id] = dependencies
        for dependency in dependencies:
            if dependency not in tasks:
                errors.append(f"{task_id}: unknown dependency {dependency}")
            elif dependency == task_id:
                errors.append(f"{task_id}: self dependency")
        outputs = _csv(str(task.get("outputs", "")))
        predicted = _csv(str(task.get("predicted_files", "")))
        if outputs != predicted:
            errors.append(f"{task_id}: Outputs and Predicted files must match exactly")
        for output in outputs:
            if not _safe_path(output):
                errors.append(f"{task_id}: unsafe output path {output!r}")
            output_owners[output].append(task_id)

    found_cycle = _cycle(graph)
    if found_cycle:
        errors.append(f"task dependency cycle: {' -> '.join(found_cycle)}")

    ready = sorted(
        task_id
        for task_id, dependencies in graph.items()
        if task_id not in completed and all(item in completed for item in dependencies)
    )
    if ready != EXPECTED_INITIAL_READY:
        errors.append(f"initial ready set mismatch: expected {EXPECTED_INITIAL_READY}, got {ready}")

    for output, owners in sorted(output_owners.items()):
        if len(owners) < 2:
            continue
        for left_index, left in enumerate(owners):
            for right in owners[left_index + 1 :]:
                if not (
                    _transitively_depends(left, right, graph)
                    or _transitively_depends(right, left, graph)
                ):
                    errors.append(f"unordered output collision for {output}: {left}, {right}")

    expected_goal_ids = ["USCIR-G000"] + [f"USCIR-G{index:03d}" for index in range(10, 101, 10)]
    if sorted(goals) != sorted(expected_goal_ids):
        errors.append(f"goal IDs mismatch: expected {expected_goal_ids}, got {sorted(goals)}")
    goal_graph: dict[str, list[str]] = {}
    for goal_id, goal in goals.items():
        missing = sorted(REQUIRED_GOAL_FIELDS - set(goal))
        if missing:
            errors.append(f"{goal_id}: missing fields {missing}")
        parent = str(goal.get("parent", "")).strip()
        parents = _csv(parent)
        goal_graph[goal_id] = parents
        if goal_id == "USCIR-G000" and parents:
            errors.append("USCIR-G000 must not have a parent")
        if goal_id != "USCIR-G000" and parents != ["USCIR-G000"]:
            errors.append(f"{goal_id}: direct parent must be USCIR-G000")
        for parent_id in parents:
            if parent_id not in goals:
                errors.append(f"{goal_id}: unknown parent {parent_id}")
        gap = str(goal.get("gap_task", ""))
        if gap not in tasks:
            errors.append(f"{goal_id}: unknown gap task {gap!r}")
    goal_cycle = _cycle(goal_graph)
    if goal_cycle:
        errors.append(f"goal dependency cycle: {' -> '.join(goal_cycle)}")

    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read plan: {exc}")
        plan_text = ""
    for required_term in (
        "4,096",
        "term-range",
        "centroid",
        "entry_cid",
        "human publication seal",
        "justicedao/ipfs_uscode",
    ):
        if required_term not in plan_text:
            errors.append(f"plan missing required term {required_term!r}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read scheduler config: {type(exc).__name__}: {exc}")
        config = {}
    if config:
        if config.get("task_prefix") != TASK_PREFIX:
            errors.append("scheduler task prefix mismatch")
        if config.get("goal_prefix") != GOAL_PREFIX:
            errors.append("scheduler goal prefix mismatch")
        if config.get("board_namespace") != BOARD_NAMESPACE:
            errors.append("scheduler board namespace mismatch")
        projection = config.get("initial_projection", {})
        if projection.get("task_count") != len(EXPECTED_TASK_IDS):
            errors.append("scheduler initial task count mismatch")
        if sorted(projection.get("completed_task_ids", [])) != sorted(completed):
            errors.append("scheduler completed projection mismatch")
        if sorted(projection.get("ready_task_ids", [])) != ready:
            errors.append("scheduler ready projection mismatch")
        lanes = config.get("lanes", [])
        if [lane.get("index") for lane in lanes if isinstance(lane, dict)] != [0, 1, 2, 3]:
            errors.append("scheduler lane order mismatch")
        protected = set(config.get("protected_paths", []))
        for required in (
            "docs/architecture/USCODE_SPARSE_GRAPHRAG_PLAN.md",
            "docs/architecture/uscode_sparse_graphrag.objectives.md",
            "docs/architecture/uscode_sparse_graphrag.todo.md",
            "config/agent_supervisor_uscode_sparse_graphrag_scheduler.json",
            "scripts/validate_uscode_sparse_graphrag_board.py",
        ):
            if required not in protected:
                errors.append(f"scheduler does not protect {required}")

    return {
        "schema": "ipfs_datasets_py/uscode-sparse-graphrag-board-validation@1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "tasks": len(tasks),
            "completed": len(completed),
            "ready": len(ready),
            "goals": len(goals),
            "outputs": len(output_owners),
        },
        "completed_task_ids": sorted(completed),
        "ready_task_ids": ready,
        "lane_task_counts": {
            str(lane): sum(
                1
                for task_id in tasks
                if int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16) % 4 == lane
            )
            for lane in range(4)
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-all", action="store_true", help="validate all sealed control-plane invariants")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    report = validate(args.repo_root.resolve())
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
