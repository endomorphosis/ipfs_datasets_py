#!/usr/bin/env python3
"""Validate the reviewed patent-legal objective heap and supervisor board.

The validator is intentionally stdlib-only so it can fail before an agent
provider or either Python package is imported.  It validates the operator-owned
inputs that the implementation supervisors execute; it does not mutate them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


TASK_HEADER = re.compile(r"^##\s+(PATLAW-\d+)\s+(.+?)\s*$", re.MULTILINE)
GOAL_HEADER = re.compile(r"^##\s+(PATLAW-G\d+)\s+(.+?)\s*$", re.MULTILINE)
FIELD = re.compile(r"^-\s+([^:]+):\s*(.*?)\s*$")
REQUIRED_TASK_FIELDS = {
    "status",
    "completion",
    "is schedulable",
    "review only",
    "priority",
    "track",
    "depends on",
    "goal id",
    "outputs",
    "validation",
    "board namespace",
    "bundle",
    "parallel lane",
    "resource class",
    "token class",
    "estimated tokens",
    "predicted files",
    "allow concurrent with",
    "conflict policy",
    "preconditions",
    "effects",
    "acceptance",
}
REQUIRED_GOAL_FIELDS = {
    "status",
    "parent",
    "fib priority",
    "track",
    "priority",
    "bundle",
    "goal",
    "evidence",
    "outputs",
    "validation",
    "acceptance",
    "gap task",
    "refinement",
    "embedding query",
    "ast query",
}
NON_EXECUTABLE_STATUSES = {"completed", "cancelled", "canceled", "deferred"}


@dataclass(frozen=True)
class Card:
    identifier: str
    title: str
    fields: Mapping[str, str]
    line: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_cards(text: str, pattern: re.Pattern[str]) -> list[Card]:
    matches = list(pattern.finditer(text))
    cards: list[Card] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields: dict[str, str] = {}
        for raw_line in text[match.end() : end].splitlines():
            field_match = FIELD.match(raw_line.strip())
            if not field_match:
                continue
            key = " ".join(field_match.group(1).strip().lower().split())
            value = field_match.group(2).strip()
            if key in fields:
                fields[key] = ", ".join(item for item in (fields[key], value) if item)
            else:
                fields[key] = value
        cards.append(
            Card(
                identifier=match.group(1),
                title=match.group(2).strip(),
                fields=fields,
                line=text.count("\n", 0, match.start()) + 1,
            )
        )
    return cards


def _relative_safe(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _cycle(nodes: Iterable[str], edges: Mapping[str, Sequence[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    trail: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            start = trail.index(node)
            return [*trail[start:], node]
        if node in visited:
            return []
        visiting.add(node)
        trail.append(node)
        for parent in edges.get(node, ()):
            found = visit(parent)
            if found:
                return found
        trail.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in nodes:
        found = visit(node)
        if found:
            return found
    return []


def _ancestors(task_id: str, dependencies: Mapping[str, Sequence[str]]) -> set[str]:
    found: set[str] = set()
    pending = list(dependencies.get(task_id, ()))
    while pending:
        dependency = pending.pop()
        if dependency in found:
            continue
        found.add(dependency)
        pending.extend(dependencies.get(dependency, ()))
    return found


def validate(repo_root: Path, config_path: Path) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"cannot load config: {exc}"], "warnings": []}
    if not isinstance(config, dict):
        return {"ok": False, "errors": ["config root must be an object"], "warnings": []}

    paths = config.get("paths")
    if not isinstance(paths, dict):
        return {"ok": False, "errors": ["config.paths must be an object"], "warnings": []}
    for name in ("plan", "objectives", "todo", "validator", "launcher", "status"):
        value = str(paths.get(name) or "")
        if not _relative_safe(value):
            errors.append(f"config path {name!r} is not a safe repo-relative path: {value!r}")
        elif not (repo_root / value).is_file():
            errors.append(f"config path {name!r} does not exist: {value}")

    objective_path = repo_root / str(paths.get("objectives") or "")
    todo_path = repo_root / str(paths.get("todo") or "")
    objective_text = objective_path.read_text(encoding="utf-8") if objective_path.is_file() else ""
    todo_text = todo_path.read_text(encoding="utf-8") if todo_path.is_file() else ""
    goals = _parse_cards(objective_text, GOAL_HEADER)
    tasks = _parse_cards(todo_text, TASK_HEADER)

    goal_counts = Counter(card.identifier for card in goals)
    task_counts = Counter(card.identifier for card in tasks)
    for identifier, count in sorted(goal_counts.items()):
        if count != 1:
            errors.append(f"goal {identifier} appears {count} times")
    for identifier, count in sorted(task_counts.items()):
        if count != 1:
            errors.append(f"task {identifier} appears {count} times")
    if not goals:
        errors.append("objective heap contains no PATLAW-G goals")
    if not tasks:
        errors.append("task board contains no PATLAW tasks")

    goals_by_id = {card.identifier: card for card in goals}
    tasks_by_id = {card.identifier: card for card in tasks}
    root_goals = [card.identifier for card in goals if not card.fields.get("parent", "").strip()]
    if root_goals != ["PATLAW-G000"]:
        errors.append(f"expected exactly root PATLAW-G000, found {root_goals}")

    goal_parents: dict[str, list[str]] = {}
    for goal in goals:
        missing = REQUIRED_GOAL_FIELDS - set(goal.fields)
        if missing:
            errors.append(f"{goal.identifier} line {goal.line} missing goal fields: {sorted(missing)}")
        for key in REQUIRED_GOAL_FIELDS - {"parent"}:
            if key in goal.fields and not goal.fields[key].strip():
                errors.append(f"{goal.identifier} has empty required field {key!r}")
        parents = _csv(goal.fields.get("parent", ""))
        goal_parents[goal.identifier] = parents
        for parent in parents:
            if parent not in goals_by_id:
                errors.append(f"{goal.identifier} has unknown parent {parent}")
            if parent == goal.identifier:
                errors.append(f"{goal.identifier} is its own parent")
    goal_cycle = _cycle(goals_by_id, goal_parents)
    if goal_cycle:
        errors.append(f"objective hierarchy cycle: {' -> '.join(goal_cycle)}")

    task_dependencies: dict[str, list[str]] = {}
    protected = {str(item) for item in config.get("protected_paths", [])}
    board_namespace = str(config.get("program") or "")
    executable_ids: set[str] = set()
    initial_ready_by_lane: defaultdict[int, list[str]] = defaultdict(list)
    for task in tasks:
        missing = REQUIRED_TASK_FIELDS - set(task.fields)
        if missing:
            errors.append(f"{task.identifier} line {task.line} missing task fields: {sorted(missing)}")
        for key in REQUIRED_TASK_FIELDS - {"depends on", "allow concurrent with"}:
            if key in task.fields and not task.fields[key].strip():
                errors.append(f"{task.identifier} has empty required field {key!r}")
        if task.fields.get("board namespace") != board_namespace:
            errors.append(
                f"{task.identifier} board namespace {task.fields.get('board namespace')!r} "
                f"does not match {board_namespace!r}"
            )
        goal_id = task.fields.get("goal id", "")
        if goal_id not in goals_by_id:
            errors.append(f"{task.identifier} has unknown Goal id {goal_id!r}")
        dependencies = _csv(task.fields.get("depends on", ""))
        task_dependencies[task.identifier] = dependencies
        for dependency in dependencies:
            if dependency not in tasks_by_id:
                errors.append(f"{task.identifier} has dangling dependency {dependency}")
            if dependency == task.identifier:
                errors.append(f"{task.identifier} depends on itself")
        for field_name in ("outputs", "predicted files"):
            values = _csv(task.fields.get(field_name, ""))
            if not values:
                errors.append(f"{task.identifier} has no {field_name}")
            for value in values:
                if not _relative_safe(value):
                    errors.append(f"{task.identifier} has unsafe {field_name} path {value!r}")
                if value in protected:
                    errors.append(f"{task.identifier} claims protected operator path {value}")
        try:
            estimated_tokens = int(task.fields.get("estimated tokens", ""))
            if estimated_tokens <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"{task.identifier} estimated tokens must be a positive integer")
        status = task.fields.get("status", "").strip().lower()
        schedulable = task.fields.get("is schedulable", "").strip().lower() == "true"
        if schedulable and status not in NON_EXECUTABLE_STATUSES:
            executable_ids.add(task.identifier)

    task_cycle = _cycle(tasks_by_id, task_dependencies)
    if task_cycle:
        errors.append(f"task dependency cycle: {' -> '.join(task_cycle)}")

    slices = config.get("lane_slices")
    if not isinstance(slices, dict):
        slices = {}
        errors.append("config.lane_slices must be an object")
    try:
        shard_count = int(config.get("shard_count", 0))
    except (TypeError, ValueError):
        shard_count = 0
    if shard_count < 2:
        errors.append("shard_count must be at least 2 for this parallel program")
    sliced: list[str] = []
    lane_for_task: dict[str, int] = {}
    for lane in range(max(0, shard_count)):
        values = slices.get(str(lane), []) if isinstance(slices, dict) else []
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            errors.append(f"lane_slices[{lane}] must be a string list")
            continue
        for task_id in values:
            sliced.append(task_id)
            if task_id in lane_for_task:
                errors.append(f"task {task_id} is assigned to multiple lanes")
            lane_for_task[task_id] = lane
            match = re.search(r"(\d+)$", task_id)
            if match and int(match.group(1)) % shard_count != lane:
                errors.append(
                    f"task {task_id} is in lane {lane} but strict numeric shard is "
                    f"{int(match.group(1)) % shard_count}"
                )
    unknown_sliced = set(sliced) - set(tasks_by_id)
    if unknown_sliced:
        errors.append(f"lane slices contain unknown tasks: {sorted(unknown_sliced)}")
    missing_sliced = executable_ids - set(sliced)
    extra_sliced = set(sliced) - executable_ids
    if missing_sliced:
        errors.append(f"executable tasks missing from lane slices: {sorted(missing_sliced)}")
    if extra_sliced:
        errors.append(f"non-executable tasks present in lane slices: {sorted(extra_sliced)}")

    for task_id in executable_ids:
        if not task_dependencies.get(task_id):
            lane = lane_for_task.get(task_id)
            if lane is not None:
                initial_ready_by_lane[lane].append(task_id)
    for lane in range(max(0, shard_count)):
        if not initial_ready_by_lane.get(lane):
            errors.append(f"lane {lane} has no dependency-free initial task and would start idle")

    bundle_root = repo_root / "data/agent_supervisor/patent_legal_intelligence/bundles"
    policy_payloads: dict[str, dict[str, object]] = {}
    for filename in (
        "lane_matrix.json",
        "launch_recipe.json",
        "private_boundary_policy.json",
        "protected_paths.json",
        "source_authority_policy.json",
    ):
        path = bundle_root / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load supervisor policy {path.relative_to(repo_root)}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"supervisor policy {path.relative_to(repo_root)} must be an object")
            continue
        policy_payloads[filename] = payload
    lane_matrix = policy_payloads.get("lane_matrix.json", {})
    if lane_matrix:
        if lane_matrix.get("board_namespace") != board_namespace:
            errors.append("lane_matrix board_namespace does not match config program")
        if lane_matrix.get("task_prefix") != config.get("task_prefix"):
            errors.append("lane_matrix task_prefix does not match config")
        if lane_matrix.get("shard_count") != shard_count:
            errors.append("lane_matrix shard_count does not match config")
        expected_initial = {
            str(lane): sorted(task_ids)
            for lane, task_ids in sorted(initial_ready_by_lane.items())
        }
        actual_initial = {
            str(lane): sorted(str(task_id) for task_id in task_ids)
            for lane, task_ids in (lane_matrix.get("initial_ready") or {}).items()
            if isinstance(task_ids, list)
        }
        if actual_initial != expected_initial:
            errors.append(
                f"lane_matrix initial_ready does not match board DAG: "
                f"expected {expected_initial}, found {actual_initial}"
            )
    launch_recipe = policy_payloads.get("launch_recipe.json", {})
    if launch_recipe:
        if launch_recipe.get("datasets_branch") != config.get("merge_target_branch"):
            errors.append("launch_recipe datasets_branch does not match merge target")
        provider_policy = launch_recipe.get("provider_policy")
        configured_provider = config.get("provider") or {}
        if (
            not isinstance(provider_policy, dict)
            or provider_policy.get("mode") != configured_provider.get("name")
            or provider_policy.get("primary") != configured_provider.get("primary")
            or provider_policy.get("backup") != configured_provider.get("backup")
            or provider_policy.get("backup_requires_fresh_attempt") is not True
        ):
            errors.append("launch_recipe provider policy does not match reviewed config fallback")
    protected_policy = policy_payloads.get("protected_paths.json", {})
    if protected_policy:
        policy_paths = protected_policy.get("paths")
        if not isinstance(policy_paths, list) or set(map(str, policy_paths)) != protected:
            errors.append("protected_paths policy must exactly match config.protected_paths")

    producer_map: defaultdict[str, list[str]] = defaultdict(list)
    for task in tasks:
        if task.identifier not in executable_ids:
            continue
        for path in _csv(task.fields.get("predicted files", "")):
            producer_map[path].append(task.identifier)
    for path, producers in sorted(producer_map.items()):
        if len(producers) < 2:
            continue
        for index, left in enumerate(producers):
            left_ancestors = _ancestors(left, task_dependencies)
            for right in producers[index + 1 :]:
                right_ancestors = _ancestors(right, task_dependencies)
                if left not in right_ancestors and right not in left_ancestors:
                    errors.append(
                        f"concurrently reachable tasks {left} and {right} predict the same path {path}"
                    )

    for protected_path in protected:
        if not _relative_safe(protected_path):
            errors.append(f"protected path is unsafe: {protected_path!r}")
        elif not (repo_root / protected_path).is_file():
            errors.append(f"protected path does not exist: {protected_path}")

    provider = config.get("provider")
    if not isinstance(provider, dict) or provider.get("name") != "auto":
        errors.append("provider.name must be 'auto' for reviewed Grok-primary selection")
    elif (
        provider.get("primary") != "grok"
        or provider.get("backup") != "codex"
        or provider.get("fresh_attempt_fallback") is not True
        or provider.get("same_workspace_fallback_forbidden") is not True
    ):
        errors.append(
            "provider must require Grok primary and Codex backup in a distinct fresh attempt"
        )
    accelerator = config.get("accelerator")
    if not isinstance(accelerator, dict) or not str(
        accelerator.get("required_feature_commit") or ""
    ).strip():
        errors.append("accelerator.required_feature_commit must pin reviewed failover support")
    if isinstance(provider, dict) and (
        not str(provider.get("primary_model") or "").strip()
        or not str(provider.get("backup_model") or "").strip()
    ):
        errors.append("provider primary_model and backup_model must be pinned")
    if not isinstance(accelerator, dict) or not str(
        accelerator.get("required_capability") or ""
    ).strip():
        errors.append("accelerator.required_capability must describe the reviewed supervisor contract")
    supervisor = config.get("supervisor")
    if not isinstance(supervisor, dict) or supervisor.get("strict_task_sharding") is not True:
        errors.append("supervisor.strict_task_sharding must be true")
    if isinstance(supervisor, dict) and supervisor.get("reviewed_board_execution_only") is not True:
        errors.append("supervisor.reviewed_board_execution_only must be true")

    leaf_goals = {
        goal_id
        for goal_id in goals_by_id
        if not any(goal_id in parents for parents in goal_parents.values())
    }
    goals_with_tasks = {task.fields.get("goal id", "") for task in tasks}
    uncovered_leaf_goals = leaf_goals - goals_with_tasks
    if uncovered_leaf_goals:
        errors.append(f"leaf goals without executable task evidence: {sorted(uncovered_leaf_goals)}")

    return {
        "ok": not errors,
        "program": board_namespace,
        "root": str(repo_root),
        "config": str(config_path),
        "goal_count": len(goals),
        "task_count": len(tasks),
        "executable_task_count": len(executable_ids),
        "shard_count": shard_count,
        "initial_ready_by_lane": {
            str(lane): sorted(task_ids) for lane, task_ids in sorted(initial_ready_by_lane.items())
        },
        "errors": errors,
        "warnings": warnings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/agent_supervisor_patent_legal_intelligence.json"),
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    config_path = args.config.expanduser()
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    report = validate(repo_root, config_path.resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        state = "PASS" if report.get("ok") else "FAIL"
        print(
            f"{state}: {report.get('program') or 'patent-legal-intelligence'}; "
            f"goals={report.get('goal_count', 0)} tasks={report.get('task_count', 0)} "
            f"executable={report.get('executable_task_count', 0)} "
            f"shards={report.get('shard_count', 0)}"
        )
        for lane, task_ids in (report.get("initial_ready_by_lane") or {}).items():
            print(f"  lane {lane} initial ready: {', '.join(task_ids)}")
        for warning in report.get("warnings", []):
            print(f"WARNING: {warning}", file=sys.stderr)
        for error in report.get("errors", []):
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
