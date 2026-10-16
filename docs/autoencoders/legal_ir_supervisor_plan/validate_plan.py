#!/usr/bin/env python3
"""Check/render the LegalIR planning documents; no product/runtime imports.

This verifies authored documentation structure and local path metadata only.
It does not call the supervisor parser, materialize jobs or validate task results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[2]


def load(name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads((ROOT / name).read_text(encoding="utf-8"), object_pairs_hook=unique)


def need(value, message):
    if not value:
        raise ValueError(message)


def csv(values):
    return ", ".join(values)


def task_markdown(plan):
    lines = [
        "# LegalIR span, graph and Lean supervisor task board",
        "",
        "Prepared native legacy-Markdown projection of tasks.json. See README.md for",
        "handoff, completion, resource and authority boundaries. No tasks are imported",
        "or launched by this file. All initial completion modes are manual; executable",
        "Validation fields remain empty until exact reviewed job packets exist.",
        "",
    ]
    for task in plan["tasks"]:
        fields = [
            ("Status", task["status"]),
            ("Completion", task["completion"]),
            ("Priority", task["priority"]),
            ("Track", task["track"]),
            ("Goal id", task["goal_id"]),
            ("Parent goal", task["goal_id"]),
            ("Legacy parent task", task["legacy_parent_task"] or "none; separate engineering/control subgoal"),
            ("Related LAC tasks", csv(task["related_lac_tasks"])),
            ("Owning repository", task["repository"]),
            ("Objective", task["objective"]),
            ("Depends on", csv(task["depends_on"])),
            ("Input roles", csv(task["inputs"]["roles"])),
            ("Inputs", csv(task["inputs"]["references"])),
            ("Denied input roles", csv(task["inputs"].get("denied_roles", []))),
            ("Outputs", csv(task["outputs"])),
            ("Validation", ""),
            ("Acceptance", task["acceptance"]),
            ("Existing owners", csv(task["existing_owners"])),
            ("Owned paths", csv(task["owned_paths"]) + "; logical results only; code/test edit allowlist must be bound in job packet"),
            ("Resource stage", task["resource_stage"]),
            ("Stage packets", csv(task["required_stage_packets"]) + "; distinct admitted owners and role separation"),
            ("Resource profile", task["resource_profile"] + "; proposed only, no grant"),
            ("Exclusive keys", csv(task["exclusive_keys"])),
            ("Board namespace", plan["board_namespace"]),
            ("Blocked reason", task["blocked_reason"]),
            ("Execution authorization", "none from this planning file; task-specific native admission required"),
            ("Evidence subset", "Exact task/source/input/context/profile/checkpoint/toolchain roots, output ownership, complete coverage, actual commands/native closeout and independent acceptance"),
        ]
        lines.extend([f'## {task["task_id"]} {task["title"]}', ""])
        lines.extend(f"- {key}: {value}".rstrip() for key, value in fields)
        lines.append("")
    return "\n".join(lines)


def goal_markdown(plan):
    lines = [
        "# LegalIR supervisor objectives",
        "",
        "Durable planning goal hierarchy. Active means unfulfilled objective, not an",
        "activated scheduler or completed result. See README.md and source_baseline.json.",
        "",
    ]
    for goal in plan["goal_hierarchy"]:
        lines.extend([
            f'## {goal["goal_id"]} {goal["title"]}',
            "",
            f'- Status: {goal["status"]}',
            f'- Parent: {goal["parent"] or ""}'.rstrip(),
            f'- Priority: {goal["priority"]}',
            f'- Goal: {goal["title"]}.',
            f'- Acceptance criteria: {"; ".join(goal["acceptance"])}',
            "- Evidence: Current input-bound accepted child results and independent stage-appropriate evidence; planning status alone is insufficient.",
        ])
        if goal.get("legacy_parent_task"):
            lines.append(f'- Legacy parent task: {goal["legacy_parent_task"]}')
        lines.append("")
    return "\n".join(lines)


def check(plan, campaign, *, render=False):
    need(plan["schema"] == "legal-ir-supervisor-refinement/v1", "wrong authoring schema")
    need(plan["status"] == campaign["status"] == "prepared_not_launched", "handoff status differs")
    need(not plan["execution_authorized_by_this_file"] and not campaign["launch_started"], "unexpected execution authority")
    need(campaign["task_import_started"] is False and campaign["execution_authorized_by_this_file"] is False, "unexpected task import/execution")
    need(campaign["is_activated_scheduler_config"] is False, "unexpected activated config")
    need(plan["authoring_manifest_is_native_ingest_schema"] is False and campaign["authoring_manifest_is_native_ingest_schema"] is False, "authoring schema mislabeled native")
    need(campaign["source_binding"]["bootstrap_task_source"] == "legacy-markdown", "wrong Markdown transport")
    need(campaign["task_header_prefix"] == "## LIR-", "wrong task prefix")
    need(campaign["board_namespace"] == plan["board_namespace"], "namespace differs")
    tasks = plan["tasks"]
    goals = plan["goal_hierarchy"]
    by_id = {t["task_id"]: t for t in tasks}
    by_goal = {g["goal_id"]: g for g in goals}
    need(len(tasks) == len(by_id) == 64, "unexpected/duplicate task population")
    need(len(goals) == len(by_goal) == 34, "unexpected/duplicate goal population")
    need([g["goal_id"] for g in goals if g["parent"] is None] == [plan["root_goal_id"]], "root goal differs")
    for goal in goals:
        seen = set()
        node = goal
        while node["parent"] is not None:
            need(node["goal_id"] not in seen, "goal cycle")
            seen.add(node["goal_id"])
            need(node["parent"] in by_goal, "unknown parent goal")
            node = by_goal[node["parent"]]
        need(goal["acceptance"], "missing goal acceptance")
    for task in tasks:
        tid = task["task_id"]
        need(re.fullmatch(r"LIR-\d{4}", tid), "unexpected child task ID")
        need(task["goal_id"] in by_goal, f"{tid}: unknown goal")
        need(task["status"] in {"todo", "blocked"}, f"{tid}: unexpected completion claim")
        need(task["completion"] == "manual" and task["validation"] == [], f"{tid}: initial executable completion")
        need(not task["execution_authorized_by_this_file"] and not task["gold_or_teacher_admission_granted"], f"{tid}: authority")
        need(task["objective"] and task["acceptance_criteria"] and task["outputs"] and task["inputs"]["roles"], f"{tid}: missing task contract")
        need(task["acceptance"] == "; ".join(task["acceptance_criteria"]), f"{tid}: acceptance projection differs")
        need(len(task["depends_on"]) == len(set(task["depends_on"])), f"{tid}: duplicate dependency")
        need(all(dep in by_id and dep != tid for dep in task["depends_on"]), f"{tid}: unknown/self dependency")
        need(task["inputs"]["required_dependency_results"] == task["depends_on"], f"{tid}: input dependencies differ")
        need(task["resource_profile"] in campaign["resource_profiles"], f"{tid}: unknown resource profile")
        profile = campaign["resource_profiles"][task["resource_profile"]]
        need(profile["proposed_only"] is True and profile["native_admission_granted"] is False, f"{tid}: profile authority")
        need(task["required_stage_packets"] and task["required_stage_packets"][0] == task["resource_stage"], f"{tid}: stage packets differ")
        need(task["code_edit_allowlist"] == [], f"{tid}: unbound planning code edit grant")
        if task["status"] == "blocked":
            need(task["blocked_reason"], f"{tid}: missing blocker")
        if task["resource_stage"] != "analysis":
            need(task["status"] == "blocked", f"{tid}: runtime/review task not blocked")
        for path in task["outputs"]:
            need(not Path(path).is_absolute() and ".." not in Path(path).parts, f"{tid}: unsafe logical output")
            need(f"/{tid}/" in path, f"{tid}: output ownership differs")
        for path in task["existing_owners"]:
            need((REPOSITORY / path).is_file(), f"{tid}: missing owner reference {path}")
    state = {}

    def ancestors(tid):
        need(state.get(tid) != "visiting", f"dependency cycle at {tid}")
        if isinstance(state.get(tid), set):
            return state[tid]
        state[tid] = "visiting"
        result = set(by_id[tid]["depends_on"])
        for dep in by_id[tid]["depends_on"]:
            result.update(ancestors(dep))
        state[tid] = result
        return result

    for task in tasks:
        ancestors(task["task_id"])
    parents = {p["id"]: p for p in plan["legacy_parent_crosswalk"]}
    need(set(parents) == {f"LIR-{n:02d}" for n in range(1, 25)}, "legacy parent population differs")
    child_ids = []
    for parent in parents.values():
        children = parent["subtasks"]
        child_ids.extend(children)
        terminal = parent["terminal_task"]
        need(terminal in children and children, "parent terminal differs")
        need(all(by_id[c]["legacy_parent_task"] == parent["id"] for c in children), "parent ownership differs")
        need(set(children) - {terminal} <= ancestors(terminal), "parent leaves not joined")
        for dep in parent["depends_on"]:
            need(parents[dep]["terminal_task"] in ancestors(terminal), f"lost original parent edge {dep}->{parent['id']}")
    need(len(child_ids) == len(set(child_ids)), "child assigned to multiple parents")
    for before, after in [("LIR-04", "LIR-08"), ("LIR-09", "LIR-10"), ("LIR-11", "LIR-15"), ("LIR-14", "LIR-15")]:
        need(parents[before]["terminal_task"] in ancestors(parents[after]["terminal_task"]), "lost critical edge")
    baseline = load("source_baseline.json")
    source_parents = {p["id"]: p for p in baseline["legacy_backlog"]["tasks"]}
    for key, parent in parents.items():
        need(all(parent[field] == source_parents[key][field] for field in ("title", "priority", "status", "depends_on")), "legacy snapshot changed")
    lac = {t["id"] for t in baseline["lac_campaign"]["task_headers"]}
    need(all(set(t["related_lac_tasks"]) <= lac for t in tasks), "unknown LAC reference")
    need(plan["engineering_e1"]["fulfills_reviewed_training_parent"] is False, "E1 cannot satisfy reviewed training")
    need(plan["engineering_e1"]["recipe"]["total_experimental_updates"] == 64, "E1 two-arm budget differs")
    for filename, expected in [("tasks.todo.md", task_markdown(plan)), ("goals.objectives.md", goal_markdown(plan))]:
        path = ROOT / filename
        if render:
            path.write_text(expected, encoding="utf-8")
        need(path.read_text(encoding="utf-8") == expected, f"{filename}: projection differs; deliberate changes require --render")
    ready = [t["task_id"] for t in tasks if t["status"] == "todo" and not t["depends_on"]]
    need(ready == ["LIR-9001"], "unexpected dependency-free task")
    return dict(valid=True, scope="documentation structure only; no genuine supervisor/parser/runtime execution", tasks=len(tasks), goals=len(goals), legacy_parents=len(parents), dependency_free_planning_tasks=ready, blocked=sum(t["status"] == "blocked" for t in tasks), product_or_supervisor_execution=False, corpus_or_model_payload_reads=False, task_import_or_launch=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true", help="Deliberately regenerate Markdown from tasks.json")
    args = parser.parse_args()
    result = check(load("tasks.json"), load("campaign.json"), render=args.render)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
