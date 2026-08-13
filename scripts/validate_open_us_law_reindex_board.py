#!/usr/bin/env python3
"""Validate the sealed, refill-aware Open US Law reindex supervisor board."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

TASK_PREFIX = "OUL-"
GOAL_PREFIX = "OUL-G"
BOARD_NAMESPACE = "open-us-law-reindex-v1"
CONFIG = Path("config/agent_supervisor_open_us_law_reindex_scheduler.json")
PLAN = Path("docs/architecture/OPEN_US_LAW_REINDEX_PLAN.md")
OBJECTIVES = Path("docs/architecture/open_us_law_reindex.objectives.md")
TASKBOARD = Path("docs/architecture/open_us_law_reindex.todo.md")
RELEASE_POLICY = Path("data/agent_supervisor/open_us_law_reindex/release_policy.json")
LANE_MATRIX = Path("data/agent_supervisor/open_us_law_reindex/lane_matrix.json")
TARGET_DATASET = "justicedao/open-us-law-sparse-graphrag"
SOURCE_BUCKET = "justicedao/open-us-law-bucket"
MODEL_ID = "thenlper/gte-small"
MODEL_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"
PAIRED_ACCELERATOR_REVISION = "bcadc044f8accd411280d86772616b8e0d7a4b28"

INITIAL_TASK_IDS = tuple(f"OUL-{number:03d}" for number in range(49))
INITIAL_GOAL_IDS = (
    "OUL-G000", "OUL-G010", "OUL-G020", "OUL-G021", "OUL-G022",
    "OUL-G023", "OUL-G024", "OUL-G030", "OUL-G040", "OUL-G050",
    "OUL-G060", "OUL-G070", "OUL-G080", "OUL-G090",
)
INITIAL_READY = (
    "OUL-001", "OUL-002", "OUL-003", "OUL-004",
    "OUL-005", "OUL-006", "OUL-007", "OUL-008",
)
TASK_FIELDS = frozenset({
    "status", "completion", "is_schedulable", "review_only", "priority",
    "track", "depends_on", "goal_id", "outputs", "validation",
    "board_namespace", "bundle", "parallel_lane", "resource_class",
    "token_class", "estimated_tokens", "predicted_files",
    "allow_concurrent_with", "conflict_policy", "preconditions", "effects",
    "acceptance",
})
GOAL_FIELDS = frozenset({
    "status", "parent", "depends_on", "fib_priority", "track", "priority",
    "bundle", "goal", "evidence", "outputs", "validation", "acceptance",
    "gap_task", "refinement", "embedding_query", "ast_query",
    "parallel_lane", "conflict_policy",
})
TASK_STATUS = frozenset({"todo", "in_progress", "completed", "blocked"})
GOAL_STATUS = frozenset({
    "active", "provisionally_complete", "verified_complete",
    "analysis_inconclusive", "blocked", "reopened",
})
GOAL_TASKS = {
    "OUL-G010": tuple(f"OUL-{number:03d}" for number in range(9)),
    "OUL-G020": tuple(f"OUL-{number:03d}" for number in range(9, 24)),
    "OUL-G021": ("OUL-009", "OUL-010", "OUL-011", "OUL-012"),
    "OUL-G022": ("OUL-013", "OUL-014", "OUL-015", "OUL-016"),
    "OUL-G023": ("OUL-017", "OUL-018", "OUL-019", "OUL-020", "OUL-021"),
    "OUL-G024": ("OUL-022", "OUL-023"),
    "OUL-G030": ("OUL-024", "OUL-025", "OUL-026"),
    "OUL-G040": ("OUL-027", "OUL-028", "OUL-029", "OUL-030", "OUL-031", "OUL-032"),
    "OUL-G050": ("OUL-033", "OUL-034", "OUL-035"),
    "OUL-G060": ("OUL-036", "OUL-037", "OUL-038", "OUL-039"),
    "OUL-G070": ("OUL-040", "OUL-041", "OUL-042"),
    "OUL-G080": ("OUL-043", "OUL-044", "OUL-045", "OUL-046"),
    "OUL-G090": ("OUL-047", "OUL-048"),
}
JURISDICTIONS = frozenset({
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL",
    "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
    "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI",
    "SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
})
COHORTS = {
    "OUL-009": ("AL","AK","AZ","AR"),
    "OUL-010": ("CA","CO","CT","DE"),
    "OUL-011": ("FL","GA","HI","ID"),
    "OUL-012": ("IL","IN","IA","KS"),
    "OUL-013": ("KY","LA","ME","MD"),
    "OUL-014": ("MA","MI","MN","MS"),
    "OUL-015": ("MO","MT","NE","NV"),
    "OUL-016": ("NH","NJ","NM","NY"),
    "OUL-017": ("NC","ND","OH","OK"),
    "OUL-018": ("OR","PA","RI","SC"),
    "OUL-019": ("SD","TN","TX","UT"),
    "OUL-020": ("VT","VA","WA","WV"),
    "OUL-021": ("WI","WY","DC"),
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _csv(value: Any) -> list[str]:
    return [
        item.strip() for item in str(value or "").split(",")
        if item.strip() and item.strip().lower() not in {"none", "n/a"}
    ]


def _safe_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() == value


def _task_lane(task_id: str) -> int:
    return int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16) % 4


def _number(identifier: str, prefix: str) -> int:
    return int(identifier[len(prefix):])


def _parse(path: Path, pattern: re.Pattern[str], heading_prefix: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    current: dict[str, Any] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [f"cannot read {path}: {type(exc).__name__}: {exc}"]
    for lineno, line in enumerate(lines, 1):
        if line.startswith(heading_prefix):
            match = pattern.fullmatch(line)
            if not match:
                errors.append(f"{path}:{lineno}: malformed heading {line!r}")
                current = None
                continue
            identifier, title = match.groups()
            if identifier in records:
                errors.append(f"{path}:{lineno}: duplicate record {identifier}")
            current = {"id": identifier, "title": title.strip(), "line": lineno}
            records[identifier] = current
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is None or not line.startswith("- "):
            continue
        field = re.fullmatch(r"- ([^:]+):(.*)", line)
        if not field:
            errors.append(f"{path}:{lineno}: malformed metadata")
            continue
        name = _key(field.group(1))
        if name in current:
            errors.append(f"{path}:{lineno}: duplicate field {name} in {current['id']}")
        current[name] = field.group(2).strip()
    return records, errors


def _cycle(graph: Mapping[str, Iterable[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    trail: list[str] = []
    def visit(node: str) -> list[str]:
        if node in visiting:
            return trail[trail.index(node):] + [node]
        if node in visited:
            return []
        visiting.add(node)
        trail.append(node)
        for child in graph.get(node, ()):
            found = visit(child)
            if found:
                return found
        trail.pop()
        visiting.remove(node)
        visited.add(node)
        return []
    for node in graph:
        found = visit(node)
        if found:
            return found
    return []


def _depends(task_id: str, wanted: str, graph: Mapping[str, Iterable[str]]) -> bool:
    pending = list(graph.get(task_id, ()))
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == wanted:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, ()))
    return False


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {label} {path}: {type(exc).__name__}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return {}
    return value


def _validate_config(config: Mapping[str, Any], tasks: Mapping[str, Any], errors: list[str]) -> None:
    exact = {
        "schema": "ipfs_accelerate_py.agent_supervisor.open_us_law_reindex.scheduler_config@1",
        "taskboard_path": TASKBOARD.as_posix(),
        "objectives_path": OBJECTIVES.as_posix(),
        "plan_path": PLAN.as_posix(),
        "validator_path": "scripts/validate_open_us_law_reindex_board.py",
        "task_prefix": TASK_PREFIX,
        "goal_prefix": GOAL_PREFIX,
        "board_namespace": BOARD_NAMESPACE,
        "merge_target_branch": "feature/legal-corpora-reindex",
        "max_lanes": 4,
        "strict_task_sharding": True,
        "exit_when_all_tracks_terminal": True,
        "objective_refill_enabled": True,
        "codebase_refill_enabled": True,
    }
    for field, expected in exact.items():
        if config.get(field) != expected:
            errors.append(f"config {field} must be {expected!r}")
    expected_projection = {
        "task_count": 49,
        "completed_task_ids": ["OUL-000"],
        "ready_task_ids": list(INITIAL_READY),
        "blocked_task_ids": [],
        "terminal_task_id": "OUL-048",
        "goal_count": len(INITIAL_GOAL_IDS),
        "root_goal_id": "OUL-G000",
    }
    if config.get("initial_projection") != expected_projection:
        errors.append("config initial_projection does not match the sealed initial board")
    provider = config.get("provider")
    expected_provider = {
        "primary_provider_id": "grok_cli",
        "primary_model_id": "grok-4.6",
        "fallback_provider_id": "codex",
        "fallback_model_id": "gpt-5.6-terra",
        "fallback_trigger": "primary_quota_exhausted",
        "fallback_reasoning_effort": "medium",
        "max_concurrency": 4,
        "secrets_from_environment_only": True,
        "secrets_in_argv_prompts_logs_or_receipts": False,
    }
    if provider != expected_provider:
        errors.append("config provider route must be Grok 4.6 with Terra quota-only fallback")
    source = config.get("source_binding")
    paired = source.get("paired_accelerator") if isinstance(source, Mapping) else None
    if not isinstance(paired, Mapping) or paired.get("required_revision") != PAIRED_ACCELERATOR_REVISION:
        errors.append("config paired accelerator revision mismatch")
    runtime = config.get("runtime_paths")
    expected_root = "workspace/agent-supervisor/open-us-law-reindex"
    if not isinstance(runtime, Mapping) or runtime.get("root") != expected_root:
        errors.append("config runtime root mismatch")
    else:
        for field in ("state", "worktrees", "merge_queue", "logs"):
            value = runtime.get(field)
            if not isinstance(value, str) or not value.startswith(expected_root + "/") or not _safe_path(value):
                errors.append(f"config runtime {field} must be a safe child of runtime root")
    refill = config.get("refill_policy")
    required_refill = {
        "generated_task_number_floor": 49,
        "generated_tasks_must_use_next_numeric_id": True,
        "generated_goals_and_tasks_must_preserve_metadata_contract": True,
        "generated_work_must_bind_discovery_evidence": True,
        "generated_work_must_preserve_output_ownership_and_dependencies": True,
        "deduplicate_equivalent_gaps": True,
        "publication_gate_denies_nonterminal_generated_work": True,
        "minimum_open_tasks": 4,
        "maximum_findings_per_scan": 5,
        "objective_task_janitor_enabled": True,
        "objective_goal_completion_reconcile_enabled": True,
        "objective_goal_migration_enabled": False,
    }
    if not isinstance(refill, Mapping):
        errors.append("config refill_policy must be an object")
    else:
        for field, expected in required_refill.items():
            if refill.get(field) != expected:
                errors.append(f"config refill_policy.{field} must be {expected!r}")
    release = config.get("release_policy")
    release_exact = {
        "source_bucket": SOURCE_BUCKET,
        "target_dataset": TARGET_DATASET,
        "required_jurisdiction_count": 51,
        "district_of_columbia_required": True,
        "maximum_rows_per_physical_shard": 4096,
        "maximum_posting_pointers_per_row": 4096,
        "maximum_adjacency_pointers_per_row": 4096,
        "maximum_rows_per_vector_centroid": 8192,
        "maximum_vector_shards_per_centroid": 2,
        "sparse_route": "lexicographic_bm25_term_ranges",
        "dense_route": "normalized_embedding_centroids",
        "embedding_model": MODEL_ID,
        "embedding_revision": MODEL_REVISION,
        "embedding_dimension": 384,
        "legacy_artifact_deletion_allowed": False,
        "force_push_allowed": False,
        "history_rewrite_allowed": False,
    }
    if not isinstance(release, Mapping):
        errors.append("config release_policy must be an object")
    else:
        for field, expected in release_exact.items():
            if release.get(field) != expected:
                errors.append(f"config release_policy.{field} must be {expected!r}")
    lanes = config.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 4:
        errors.append("config must define four lanes")
    else:
        for index, lane in enumerate(lanes):
            expected = [
                task_id for task_id in INITIAL_READY if _task_lane(task_id) == index
            ]
            if not isinstance(lane, Mapping) or lane.get("index") != index or lane.get("strict_shard_remainder") != index or lane.get("initial_task_ids") != expected:
                errors.append(f"config lane {index} initial shard projection mismatch")
    groups = config.get("task_groups")
    if not isinstance(groups, Mapping):
        errors.append("config task_groups must be an object")
    else:
        for goal_id, expected in GOAL_TASKS.items():
            if groups.get(goal_id) != list(expected):
                errors.append(f"config task group {goal_id} mismatch")
    protected = config.get("protected_paths")
    required = {
        ".gitignore", PLAN.as_posix(), OBJECTIVES.as_posix(), TASKBOARD.as_posix(),
        CONFIG.as_posix(), "scripts/validate_open_us_law_reindex_board.py",
        "scripts/ops/agent_supervisor/configured_board_scheduler.py",
        "scripts/ops/open_us_law_reindex/preflight.py",
        "scripts/ops/open_us_law_reindex/status.py",
        "tests/unit/supervisor/test_open_us_law_reindex_board.py",
        RELEASE_POLICY.as_posix(), LANE_MATRIX.as_posix(),
    }
    if not isinstance(protected, list) or not required.issubset(set(protected)):
        errors.append("config protected_paths misses an Open US Law control file")


def validate(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    tasks, parse_errors = _parse(
        root / TASKBOARD, re.compile(r"## (OUL-\d{3,}) (.+)"), "## OUL-"
    )
    errors.extend(parse_errors)
    goals, parse_errors = _parse(
        root / OBJECTIVES, re.compile(r"## (OUL-G\d{3,}) (.+)"), "## OUL-G"
    )
    errors.extend(parse_errors)

    missing_initial = sorted(set(INITIAL_TASK_IDS) - set(tasks))
    if missing_initial:
        errors.append(f"missing initial tasks: {missing_initial}")
    initial_numbers = sorted(
        _number(task_id, TASK_PREFIX) for task_id in tasks
        if _number(task_id, TASK_PREFIX) < 49
    )
    if initial_numbers != list(range(49)):
        errors.append("initial task IDs must be exactly OUL-000 through OUL-048")
    generated_numbers = sorted(
        _number(task_id, TASK_PREFIX) for task_id in tasks
        if _number(task_id, TASK_PREFIX) >= 49
    )
    if generated_numbers and generated_numbers != list(range(49, generated_numbers[-1] + 1)):
        errors.append("generated task IDs must be contiguous from OUL-049")

    if not set(INITIAL_GOAL_IDS).issubset(goals):
        errors.append(f"missing initial goals: {sorted(set(INITIAL_GOAL_IDS) - set(goals))}")
    generated_goal_numbers = sorted(
        _number(goal_id, GOAL_PREFIX) for goal_id in goals
        if _number(goal_id, GOAL_PREFIX) > 90
    )
    if generated_goal_numbers and generated_goal_numbers != list(range(91, generated_goal_numbers[-1] + 1)):
        errors.append("generated goal IDs must be contiguous from OUL-G091")

    goal_graph: dict[str, list[str]] = {}
    for goal_id, goal in goals.items():
        missing = sorted(GOAL_FIELDS - (set(goal) - {"id", "title", "line"}))
        if missing:
            errors.append(f"{goal_id}: missing goal fields {missing}")
        status = str(goal.get("status") or "").lower()
        if status not in GOAL_STATUS:
            errors.append(f"{goal_id}: unsupported status {status!r}")
        parents = _csv(goal.get("parent"))
        dependencies = _csv(goal.get("depends_on"))
        goal_graph[goal_id] = [*parents, *dependencies]
        if goal_id == "OUL-G000" and parents:
            errors.append("OUL-G000 must not have a parent")
        if goal_id != "OUL-G000" and not parents:
            errors.append(f"{goal_id}: non-root goal must have a parent")
        for reference in goal_graph[goal_id]:
            if reference not in goals:
                errors.append(f"{goal_id}: unknown goal reference {reference}")
        try:
            if int(str(goal.get("fib_priority"))) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{goal_id}: Fib priority must be positive")
        for output in _csv(goal.get("outputs")):
            if not _safe_path(output):
                errors.append(f"{goal_id}: unsafe output {output!r}")
        if goal.get("gap_task") not in tasks:
            errors.append(f"{goal_id}: Gap task does not exist")
    found = _cycle(goal_graph)
    if found:
        errors.append("goal cycle: " + " -> ".join(found))

    task_graph: dict[str, list[str]] = {}
    completed: set[str] = set()
    blocked: set[str] = set()
    in_progress: set[str] = set()
    outputs: dict[str, list[str]] = defaultdict(list)
    for task_id, task in tasks.items():
        missing = sorted(TASK_FIELDS - (set(task) - {"id", "title", "line"}))
        if missing:
            errors.append(f"{task_id}: missing task fields {missing}")
        status = str(task.get("status") or "").lower()
        if status not in TASK_STATUS:
            errors.append(f"{task_id}: unsupported status {status!r}")
        if status == "completed":
            completed.add(task_id)
        elif status == "blocked":
            blocked.add(task_id)
        elif status == "in_progress":
            in_progress.add(task_id)
        if task.get("board_namespace") != BOARD_NAMESPACE:
            errors.append(f"{task_id}: Board namespace mismatch")
        for field in ("is_schedulable", "review_only"):
            if str(task.get(field) or "").lower() not in {"true", "false"}:
                errors.append(f"{task_id}: {field} must be true or false")
        if not re.fullmatch(r"P\d", str(task.get("priority") or "")):
            errors.append(f"{task_id}: invalid Priority")
        try:
            if int(str(task.get("estimated_tokens"))) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{task_id}: Estimated tokens must be positive")
        try:
            lane = int(str(task.get("parallel_lane")))
        except ValueError:
            lane = -1
        if lane != _task_lane(task_id):
            errors.append(f"{task_id}: Parallel lane {lane} does not match SHA-256 shard {_task_lane(task_id)}")
        goal_id = str(task.get("goal_id") or "")
        if goal_id not in goals:
            errors.append(f"{task_id}: unknown Goal id {goal_id!r}")
        dependencies = _csv(task.get("depends_on"))
        task_graph[task_id] = dependencies
        for dependency in dependencies:
            if dependency not in tasks:
                errors.append(f"{task_id}: unknown dependency {dependency}")
            if dependency == task_id:
                errors.append(f"{task_id}: self dependency")
        for output in _csv(task.get("outputs")):
            if not _safe_path(output):
                errors.append(f"{task_id}: unsafe output {output!r}")
            outputs[output].append(task_id)
        if tuple(_csv(task.get("outputs"))) != tuple(_csv(task.get("predicted_files"))):
            errors.append(f"{task_id}: Outputs and Predicted files must match")
    found = _cycle(task_graph)
    if found:
        errors.append("task cycle: " + " -> ".join(found))
    for task_id in completed:
        missing_dependencies = [dep for dep in task_graph.get(task_id, ()) if dep not in completed]
        if missing_dependencies:
            errors.append(f"{task_id}: completed before dependencies {missing_dependencies}")
    for output, owners in outputs.items():
        if len(owners) < 2:
            continue
        for index, left in enumerate(owners):
            for right in owners[index + 1:]:
                if not (_depends(left, right, task_graph) or _depends(right, left, task_graph)):
                    errors.append(f"unordered output collision for {output}: {left}, {right}")

    cohort_union = {code for codes in COHORTS.values() for code in codes}
    if cohort_union != JURISDICTIONS or sum(map(len, COHORTS.values())) != 51:
        errors.append("cohort matrix must partition exactly 50 states plus DC")
    for required in INITIAL_TASK_IDS[:-1]:
        if not _depends("OUL-048", required, task_graph):
            errors.append(f"OUL-048 must transitively depend on {required}")
    for required in ("OUL-001","OUL-002","OUL-003","OUL-004","OUL-005","OUL-006","OUL-007","OUL-008","OUL-022","OUL-023","OUL-028","OUL-029","OUL-031","OUL-039","OUL-040","OUL-041","OUL-042","OUL-043"):
        if not _depends("OUL-044", required, task_graph):
            errors.append(f"OUL-044 must transitively depend on publication prerequisite {required}")

    ready = sorted(
        task_id for task_id, task in tasks.items()
        if str(task.get("status") or "").lower() == "todo"
        and str(task.get("is_schedulable") or "").lower() == "true"
        and all(dependency in completed for dependency in task_graph.get(task_id, ()))
    )
    waiting = sorted(
        task_id for task_id, task in tasks.items()
        if str(task.get("status") or "").lower() == "todo" and task_id not in ready
    )
    generated_nonterminal = sorted(
        task_id for task_id, task in tasks.items()
        if _number(task_id, TASK_PREFIX) >= 49
        and str(task.get("status") or "").lower() != "completed"
    )
    if generated_nonterminal:
        for guarded in ("OUL-041", "OUL-044", "OUL-048"):
            if str(tasks.get(guarded, {}).get("status") or "").lower() in {"in_progress", "completed"}:
                errors.append(f"{guarded} cannot advance while generated work is nonterminal: {generated_nonterminal}")

    config = _load_json(root / CONFIG, errors, "scheduler config")
    if config:
        _validate_config(config, tasks, errors)
    policy = _load_json(root / RELEASE_POLICY, errors, "release policy")
    if policy:
        if policy.get("source_bucket") != SOURCE_BUCKET or policy.get("target_dataset") != TARGET_DATASET:
            errors.append("release policy target identities mismatch")
        vector = policy.get("vector")
        if not isinstance(vector, Mapping) or vector.get("model") != MODEL_ID or vector.get("revision") != MODEL_REVISION or vector.get("maximum_rows_per_physical_shard") != 4096 or vector.get("sort_order") != "centroid_cosine_desc_then_entry_cid":
            errors.append("release policy vector contract mismatch")
        bm25 = policy.get("bm25")
        if not isinstance(bm25, Mapping) or bm25.get("route") != "lexicographic_term_ranges" or bm25.get("maximum_rows_per_physical_shard") != 4096:
            errors.append("release policy BM25 contract mismatch")
        graph = policy.get("graph")
        if not isinstance(graph, Mapping) or graph.get("lexical_source") != "bm25_postings" or graph.get("maximum_pointers_per_page") != 4096:
            errors.append("release policy graph contract mismatch")
        jurisdictions = policy.get("jurisdictions")
        if not isinstance(jurisdictions, Mapping) or set(jurisdictions.get("required_codes") or []) != JURISDICTIONS:
            errors.append("release policy exact-51 jurisdiction contract mismatch")
    matrix = _load_json(root / LANE_MATRIX, errors, "lane matrix")
    if matrix:
        observed: set[str] = set()
        for lane in matrix.get("lanes") or []:
            if not isinstance(lane, Mapping):
                errors.append("lane matrix lane is not an object")
                continue
            index = lane.get("index")
            for task_id in lane.get("all_initial_board_task_ids") or []:
                observed.add(task_id)
                if index != _task_lane(task_id):
                    errors.append(f"lane matrix places {task_id} on wrong lane")
        if observed != set(INITIAL_TASK_IDS):
            errors.append("lane matrix must contain every initial task exactly once")

    try:
        plan_text = (root / PLAN).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read plan: {type(exc).__name__}: {exc}")
        plan_text = ""
    for term in (
        SOURCE_BUCKET, TARGET_DATASET, "50 states and the District of Columbia",
        MODEL_ID, MODEL_REVISION, "4,096", "lexicographic term ranges",
        "balanced spherical k-means", "entry-to-vector-shard locator",
        "releases/<manifest_sha256>/", "Grok `grok-4.6`",
        "Codex `gpt-5.6-terra`", "objective and codebase refill scans are enabled",
    ):
        if term not in plan_text:
            errors.append(f"plan missing required contract term {term!r}")

    return {
        "schema": "ipfs_datasets_py/open-us-law-reindex-board-validation@1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "tasks": len(tasks),
            "goals": len(goals),
            "completed": len(completed),
            "ready": len(ready),
            "waiting": len(waiting),
            "blocked": len(blocked),
            "in_progress": len(in_progress),
            "generated_tasks": sum(_number(task_id, TASK_PREFIX) >= 49 for task_id in tasks),
            "generated_goals": sum(_number(goal_id, GOAL_PREFIX) > 90 for goal_id in goals),
            "jurisdictions": len(cohort_union),
            "outputs": len(outputs),
        },
        "current_projection": {
            "completed_task_ids": sorted(completed),
            "ready_task_ids": ready,
            "waiting_task_ids": waiting,
            "blocked_task_ids": sorted(blocked),
            "in_progress_task_ids": sorted(in_progress),
            "generated_nonterminal_task_ids": generated_nonterminal,
        },
        "lane_task_counts": {
            str(index): sum(_task_lane(task_id) == index for task_id in tasks)
            for index in range(4)
        },
        "targets": {
            "source_bucket": SOURCE_BUCKET,
            "dataset": TARGET_DATASET,
            "model": f"{MODEL_ID}@{MODEL_REVISION}",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-all", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    report = validate(args.repo_root)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
