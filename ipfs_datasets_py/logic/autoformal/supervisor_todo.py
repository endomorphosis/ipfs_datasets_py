"""Route autoformal discrepancies to the agent-supervisor todo loop.

Failed jobs are not sent to the autoencoder, compiler, or decompiler. Each
gap becomes a supervisor task that records what to preserve and what to
replace, plus a time-management estimate the accelerate daemon can locate.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "uscode-autoformal-supervisor-todo/v1"
LOCATOR_SCHEMA = "ipfs_accelerate_py.agent_supervisor.huggingface_todo_locator/v1"
BOARD_NAMESPACE = "uscode-autoformal-todo-v1"
TASK_PREFIX = "AFTD-"
GOAL_PREFIX = "AFTD-G"
TASK_HEADER_PREFIX = "## AFTD-"
BOARD_TITLE = "U.S. Code autoformal discrepancy board"

_FAILURE_BUDGETS = {
    "extended_ir_v2": {
        "estimated_tokens": 14000, "estimated_validation_seconds": 300,
        "priority": "P0", "resource_class": "cpu-medium", "token_class": "large",
        "preserve": ("canonical v1 behavior and frozen tests", "existing sealed tasks and evidence"),
        "replace": ("opt-in v2 compiler and source-withheld decompiler",),
    },
    "roundtrip_repair_v2": {
        "estimated_tokens": 14000, "estimated_validation_seconds": 600,
        "priority": "P0", "resource_class": "cpu-medium", "token_class": "large",
        "preserve": ("freshly verified round-trip rows", "all original sealed tasks and evidence"),
        "replace": ("joint compiler/decompiler handling of independently reproduced loss",),
    },
    "no_parser_elements": {
        "estimated_tokens": 12000,
        "estimated_validation_seconds": 600,
        "priority": "P0",
        "resource_class": "cpu-medium",
        "token_class": "large",
        "preserve": ("compiled compiler rows", "existing Lake Legal target"),
        "replace": ("parser atom inventory", "compiler coverage for this span"),
    },
    "compiler_abstain": {
        "estimated_tokens": 10000,
        "estimated_validation_seconds": 480,
        "priority": "P0",
        "resource_class": "cpu-medium",
        "token_class": "large",
        "preserve": ("deterministic compiler for compiled spans",),
        "replace": ("compiler abstain path", "unsupported field handling"),
    },
    "strict_roundtrip_failed": {
        "estimated_tokens": 14000,
        "estimated_validation_seconds": 600,
        "priority": "P0",
        "resource_class": "cpu-medium",
        "token_class": "large",
        "preserve": ("strict round-trip rows", "TypedDeonticCanonicalCompiler", "decompile_rule"),
        "replace": ("parser or compiler edit that makes this span round-trip",),
    },
    "dropped_clause": {
        "estimated_tokens": 8000,
        "estimated_validation_seconds": 300,
        "priority": "P1",
        "resource_class": "cpu-small",
        "token_class": "medium",
        "preserve": ("compiled clauses that already round-trip", "TypedDeonticCanonicalCompiler"),
        "replace": ("decompiler reconstruction for dropped clauses",),
    },
    "qualifier_not_in_decompilation": {
        "estimated_tokens": 6000,
        "estimated_validation_seconds": 240,
        "priority": "P1",
        "resource_class": "cpu-small",
        "token_class": "medium",
        "preserve": ("compiler slots that already emit the qualifier",),
        "replace": ("decompile_rule qualifier rendering",),
    },
    "schema_placeholder": {
        "estimated_tokens": 8000,
        "estimated_validation_seconds": 300,
        "priority": "P1",
        "resource_class": "cpu-small",
        "token_class": "medium",
        "preserve": ("non-placeholder compiled rows",),
        "replace": ("compiler schema rendering",),
    },
    "capture_not_in_decompilation": {
        "estimated_tokens": 7000,
        "estimated_validation_seconds": 300,
        "priority": "P1",
        "resource_class": "cpu-small",
        "token_class": "medium",
        "preserve": ("autoencoder capture tokens that already appear",),
        "replace": ("decompiler token coverage for autoencoder captures", "autoencoder checkpoint for missing captures"),
    },
    "inference_still_failing": {
        "estimated_tokens": 8000,
        "estimated_validation_seconds": 600,
        "priority": "P1",
        "resource_class": "cpu-medium",
        "token_class": "medium",
        "preserve": ("compiled compiler/decompiler for agreed spans",),
        "replace": ("autoencoder checkpoint trained on this failure family",),
    },
}
_DEFAULT_BUDGET = {
    "estimated_tokens": 8000,
    "estimated_validation_seconds": 360,
    "priority": "P2",
    "resource_class": "cpu-small",
    "token_class": "medium",
    "preserve": ("compiled compiler/decompiler for agreed spans",),
    "replace": ("discrepancy handling for this span",),
}


def _line(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _csv(values: Sequence[str]) -> str:
    return ", ".join(item for item in values if item)


def _budget(failure_mode: str) -> dict[str, Any]:
    key = str(failure_mode or "").split(":", 1)[0]
    return dict(_FAILURE_BUDGETS.get(key) or _DEFAULT_BUDGET)


def _row_id(row: Mapping[str, Any], index: int) -> str:
    raw = str(row.get("id") or row.get("source_span_id") or index)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{TASK_PREFIX}{index:03d}-{digest}"


def preserve_replace_for(row: Mapping[str, Any], *, agreed_ids: Sequence[str] = ()) -> dict[str, list[str]]:
    """Name the compiler/decompiler parts to keep or replace. Not an edit."""

    budget = _budget(str(row.get("reason") or row.get("failure_mode") or ""))
    preserve = [str(item) for item in budget["preserve"]]
    if agreed_ids:
        preserve.append(f"agreed spans {', '.join(agreed_ids[:8])}")
    replace = [str(item) for item in budget["replace"]]
    dropped = [str(item) for item in row.get("dropped") or [] if str(item)]
    if dropped:
        replace.append("missing surfaces: " + ", ".join(dropped[:8]))
    return {"preserve": preserve, "replace": replace}


def discrepancy_tasks(
    agreement: Mapping[str, Any],
    *,
    query: str = "",
    release_id: str = "",
) -> list[dict[str, Any]]:
    """Turn compiler/autoencoder disagreements into supervisor tasks."""

    rows = [dict(row) for row in agreement.get("rows") or []]
    if not rows:
        for todo in agreement.get("todos") or []:
            metadata = dict(todo.get("metadata") or {}) if isinstance(todo, Mapping) else {}
            rows.append(
                {
                    "id": str((todo.get("sample_ids") or [""])[0] if isinstance(todo, Mapping) else ""),
                    "text": str(metadata.get("source_text") or ""),
                    "reason": str(metadata.get("failure_mode") or todo.get("loss_name") or "compiler_disagreement"),
                    "dropped": list((metadata.get("acceptance") or {}).get("must_contain") or []),
                    "decompiled": str(metadata.get("decompiled") or ""),
                    "agrees": False,
                    "skipped": False,
                    "capture": dict(metadata.get("autoencoder_features") or {}),
                }
            )
    agreed_ids = [str(row.get("id") or "") for row in rows if row.get("agrees") and not row.get("skipped")]
    tasks: list[dict[str, Any]] = []
    for index, row in enumerate((item for item in rows if not item.get("skipped") and not item.get("agrees")), start=1):
        failure_mode = str(row.get("reason") or "compiler_disagreement")
        budget = _budget(failure_mode)
        decision = preserve_replace_for(row, agreed_ids=agreed_ids)
        task_id = _row_id(row, index)
        source_text = str(row.get("text") or "")
        tasks.append(
            {
                "acceptance": (
                    "Do not mark formalized. Do not import a proposed compiler. "
                    "Record preserve/replace, then only edit the replace list."
                ),
                "board_namespace": BOARD_NAMESPACE,
                "canonical_citation": str(row.get("canonical_citation") or ""),
                "decompiled": str(row.get("decompiled") or ""),
                "dropped": [str(item) for item in row.get("dropped") or []],
                "entry_cid": str(row.get("entry_cid") or ""),
                "estimated_tokens": int(budget["estimated_tokens"]),
                "estimated_validation_seconds": int(budget["estimated_validation_seconds"]),
                "failure_mode": failure_mode,
                "goal_id": f"{GOAL_PREFIX}010",
                "legal_id": str(row.get("legal_id") or ""),
                "match_is_not_admit": True,
                "preserve": decision["preserve"],
                "priority": str(budget["priority"]),
                "query": query,
                "release_id": release_id,
                "replace": decision["replace"],
                "resource_class": str(budget["resource_class"]),
                "schema": SCHEMA,
                "source_span_id": str(row.get("source_span_id") or row.get("id") or ""),
                "source_text": source_text,
                "status": "todo",
                "task_id": task_id,
                "title": _line(f"Preserve or replace {failure_mode} for {row.get('id') or task_id}"),
                "token_class": str(budget["token_class"]),
                "track": "autoformal-discrepancy",
            }
        )
    return tasks


def render_supervisor_board(
    tasks: Sequence[Mapping[str, Any]],
    *,
    goals: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Markdown the implementation daemon can parse. One metadata line per field."""

    lines = [
        f"# {BOARD_TITLE}",
        "",
        "This board is parsed by `ipfs_accelerate_py`. Metadata stays on one physical line per field.",
        "Failed jobs become supervisor todos. Each todo declares preserve/replace plus train or compiler/decompiler edit work.",
        "",
    ]
    for task in tasks:
        lines.append(f"## {task['task_id']} {task['title']}")
        lines.append("- Status: todo")
        lines.append("- Completion: evidence")
        lines.append("- Is schedulable: true")
        lines.append("- Review only: " + ("true" if task.get("review_only") is True else "false"))
        lines.append(f"- Priority: {task['priority']}")
        lines.append(f"- Track: {task['track']}")
        lines.append("- Depends on:")
        lines.append(f"- Goal id: {task['goal_id']}")
        if task.get("goal_cid"):
            lines.append("- Goal cid: " + _line(task.get("goal_cid")))
        if task.get("plan_cid"):
            lines.append("- Plan cid: " + _line(task.get("plan_cid")))
        if task.get("objective_id"):
            lines.append("- Objective id: " + _line(task.get("objective_id")))
        if task.get("parent_goal_cid"):
            lines.append("- Parent goal: " + _line(task.get("parent_goal_cid")))
        if task.get("task_cid"):
            lines.append("- Task cid: " + _line(task.get("task_cid")))
        lines.append("- Outputs:")
        argv = []
        for command in task.get("validation_commands") or []:
            if isinstance(command, Mapping):
                argv = [str(item) for item in command.get("argv") or []]
                break
        lines.append("- Validation: " + _line(" ".join(argv) or "python -m pytest tests/unit/logic/test_supervisor_todo.py -q"))
        lines.append("- Board namespace: " + _line(task.get("board_namespace") or BOARD_NAMESPACE))
        lines.append("- Bundle: autoformal-discrepancy")
        lines.append("- Resource class: " + str(task["resource_class"]))
        lines.append("- Token class: " + str(task["token_class"]))
        lines.append(f"- Estimated tokens: {int(task['estimated_tokens'])}")
        lines.append(f"- Estimated validation seconds: {int(task['estimated_validation_seconds'])}")
        lines.append("- Predicted files: " + _line(_csv([str(item) for item in task.get("predicted_files") or task.get("allowed_edit_paths") or []])))
        lines.append("- Allow concurrent with: none")
        lines.append("- Conflict policy: " + _line(task.get("conflict_policy") or "do not write compiler or decompiler patches from this task"))
        lines.append("- Work kind: " + _line(task.get("work_kind") or "preserve_replace_review"))
        lines.append("- Dispatch status: " + _line(task.get("dispatch_status") or ""))
        lines.append("- Allowed edit paths: " + _line(_csv([str(item) for item in task.get("allowed_edit_paths") or []])))
        if task.get("packet_path"):
            lines.append("- Packet path: " + _line(task.get("packet_path")))
        if task.get("packet_sha256"):
            lines.append("- Packet sha256: " + _line(task.get("packet_sha256")))
        training = task.get("training_job") if isinstance(task.get("training_job"), Mapping) else {}
        if training:
            lines.append("- Training entrypoint: " + _line(training.get("entrypoint")))
            lines.append("- Training job template: " + _line(training.get("job_template")))
            lines.append("- Training job schema: " + _line(training.get("job_schema")))
        lines.append("- Failure mode: " + _line(task.get("failure_mode")))
        lines.append("- Source span id: " + _line(task.get("source_span_id")))
        lines.append("- Legal id: " + _line(task.get("legal_id")))
        lines.append("- Entry cid: " + _line(task.get("entry_cid")))
        lines.append("- Preserve: " + _line(_csv(list(task.get("preserve") or []))))
        lines.append("- Replace: " + _line(_csv(list(task.get("replace") or []))))
        lines.append("- Source text: " + _line(task.get("source_text")))
        lines.append("- Decompiled: " + _line(task.get("decompiled")))
        lines.append("- Match is not admit: true")
        lines.append("- Formalized: false")
        lines.append("- Admitted: false")
        lines.append("- Preconditions: Sparse GraphRAG retrieval located the span; compiler and autoencoder disagreed.")
        lines.append("- Effects: Declares preserve/replace plus train or compiler/decompiler edit work for the accelerate supervisor.")
        lines.append("- Acceptance: " + _line(task.get("acceptance")))
        lines.append("")
    if goals:
        extra = render_goal_sections(goals)
        if extra:
            lines.append(extra.rstrip())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_goal_sections(goals: Sequence[Mapping[str, Any]]) -> str:
    """Markdown goal headers. One metadata line per field."""

    lines: list[str] = []
    for goal in goals:
        lines.append(f"## {goal['goal_id']} {goal['title']}")
        lines.append("- Status: todo")
        lines.append("- Completion: evidence")
        lines.append("- Is schedulable: false")
        lines.append("- Review only: true")
        lines.append(f"- Priority: {goal.get('priority') or 'P1'}")
        lines.append("- Track: autoformal-goal")
        lines.append("- Depends on:")
        lines.append(f"- Goal id: {goal['goal_id']}")
        if goal.get("goal_cid"):
            lines.append("- Goal cid: " + _line(goal.get("goal_cid")))
        if goal.get("parent_goal_cid"):
            lines.append("- Parent goal: " + _line(goal.get("parent_goal_cid")))
        if goal.get("objective_id"):
            lines.append("- Objective id: " + _line(goal.get("objective_id")))
        lines.append("- Outputs:")
        lines.append("- Validation: python -m pytest tests/unit/logic/test_supervisor_loop.py -q")
        lines.append(f"- Board namespace: {BOARD_NAMESPACE}")
        lines.append("- Bundle: autoformal-goal")
        lines.append("- Resource class: cpu-small")
        lines.append("- Token class: medium")
        lines.append(f"- Estimated tokens: {int(goal.get('estimated_tokens') or 0)}")
        lines.append(f"- Estimated validation seconds: {int(goal.get('estimated_validation_seconds') or 0)}")
        lines.append("- Predicted files:")
        lines.append("- Allow concurrent with: none")
        lines.append("- Conflict policy: do not write compiler or decompiler patches from this goal")
        lines.append("- Failure mode: " + _line(goal.get("failure_mode")))
        lines.append("- Source span id: ")
        lines.append("- Legal id: ")
        lines.append("- Entry cid: ")
        lines.append("- Preserve: grouped outstanding todos; do not admit a compile as law")
        lines.append("- Replace: one architecture or cluster resolution covering Resolves")
        lines.append("- Source text: ")
        lines.append("- Decompiled: ")
        lines.append("- Match is not admit: true")
        lines.append("- Formalized: false")
        lines.append("- Admitted: false")
        lines.append(f"- Kind: {goal.get('kind') or 'cluster'}")
        lines.append("- Resolves: " + ", ".join(str(item) for item in goal.get("resolves") or []))
        lines.append("- Preconditions: Related autoformal errors share a failure family or citation.")
        lines.append("- Effects: One goal can close several outstanding todos without a compiler patch.")
        lines.append("- Acceptance: Do not mark formalized. Resolving the goal must close every listed todo or leave them explicit.")
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


class SupervisorBoardError(ValueError):
    """The supervisor markdown board is missing required preserve/replace metadata."""


_REQUIRED_BOARD_FIELDS = (
    "Status",
    "Preserve",
    "Replace",
    "Estimated tokens",
    "Estimated validation seconds",
    "Match is not admit",
    "Formalized",
    "Admitted",
    "Failure mode",
)


def validate_supervisor_board(markdown: str) -> dict[str, Any]:
    """Refuse JSONL, compiler patches, or tasks without preserve/replace budgets."""

    errors: list[str] = []
    lowered = markdown.casefold()
    if ".jsonl" in lowered:
        errors.append("board must not reference jsonl")
    if "proposed_compiler" in lowered:
        errors.append("board must not propose a compiler patch")
    headers = list(re.finditer(r"^## (AFTD-\S+)\s+", markdown, re.MULTILINE))
    if not headers:
        errors.append("board has no AFTD tasks")
    spans = [match.start() for match in headers] + [len(markdown)]
    for index, match in enumerate(headers):
        block = markdown[spans[index] : spans[index + 1]]
        task_id = match.group(1)
        if task_id.startswith("AFTD-G"):
            for field in ("Status", "Kind", "Resolves", "Formalized", "Admitted", "Match is not admit"):
                if f"- {field}:" not in block:
                    errors.append(f"{task_id} is missing {field}")
            if "- Formalized: true" in block or "- Admitted: true" in block:
                errors.append(f"{task_id} must not mark formalized or admitted")
            continue
        for field in _REQUIRED_BOARD_FIELDS:
            if f"- {field}:" not in block:
                errors.append(f"{task_id} is missing {field}")
        if "- Formalized: true" in block or "- Admitted: true" in block:
            errors.append(f"{task_id} must not mark formalized or admitted")
        if "- Match is not admit: true" not in block:
            errors.append(f"{task_id} must declare match is not admit")
        preserve = _line(block.split("- Preserve:", 1)[-1].splitlines()[0] if "- Preserve:" in block else "")
        replace = _line(block.split("- Replace:", 1)[-1].splitlines()[0] if "- Replace:" in block else "")
        if "- Preserve:" in block and not preserve:
            errors.append(f"{task_id} preserve list is empty")
        if "- Replace:" in block and not replace:
            errors.append(f"{task_id} replace list is empty")
    if errors:
        raise SupervisorBoardError("; ".join(errors))
    return {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "task_count": len(headers),
        "valid": True,
        "wrote_compiler": False,
    }


def time_management(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Token and wall-time budget the accelerate scheduler can consume."""

    task_list = list(tasks)
    priority_counts: dict[str, int] = {}
    for task in task_list:
        key = str(task.get("priority") or "P2")
        priority_counts[key] = priority_counts.get(key, 0) + 1
    return {
        "priority_counts": priority_counts,
        "resource_classes": sorted({str(task.get("resource_class") or "") for task in task_list if task.get("resource_class")}),
        "task_count": len(task_list),
        "total_estimated_tokens": sum(int(task.get("estimated_tokens") or 0) for task in task_list),
        "total_estimated_validation_seconds": sum(
            int(task.get("estimated_validation_seconds") or 0) for task in task_list
        ),
    }


def huggingface_todo_locator(
    *,
    repository_id: str,
    release_id: str,
    board_path: str,
    todos_path: str,
    revision: str = "main",
    tasks: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """How the accelerate supervisor locates the Hugging Face todo release."""

    return {
        "board_namespace": BOARD_NAMESPACE,
        "board_path": board_path,
        "dataset_repo_id": repository_id,
        "goal_prefix": GOAL_PREFIX,
        "release_id": release_id,
        "revision": revision,
        "schema": LOCATOR_SCHEMA,
        "task_header_prefix": TASK_HEADER_PREFIX,
        "task_prefix": TASK_PREFIX,
        "time_management": time_management(tasks),
        "todos_path": todos_path,
    }


def write_supervisor_board(
    path: str | Path,
    tasks: Sequence[Mapping[str, Any]],
    *,
    goals: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Materialize a local board the implementation daemon can watch."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_supervisor_board(tasks, goals=goals)
    validate_supervisor_board(markdown)
    destination.write_text(markdown, encoding="utf-8")
    return {
        "admitted": False,
        "board_namespace": BOARD_NAMESPACE,
        "board_path": str(destination),
        "formalized": False,
        "jsonl_written": False,
        "task_count": len(list(tasks)),
        "time_management": time_management(tasks),
        "wrote_compiler": False,
        "wrote_decompiler": False,
    }


def agreement_from_strict_spans(spans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Agree only when a span's strict compile round-tripped.

    A decompiled sentence is not agreement. A repeal fixture is not a compiler
    edit. Neither result is an admit.
    """

    rows = []
    for span in spans:
        status = str(span.get("status") or "")
        if status in {"non_operative", "inactive"}:
            continue
        strict = str(span.get("strict_status") or "")
        if strict == "repeal" or status == "repeal":
            rows.append(_strict_row(span, agrees=False, skipped=True, reason="repeal_fixture"))
            continue
        agrees = strict == "roundtrip_ok"
        reason = "" if agrees else str(span.get("strict_reason") or span.get("reason") or "compiler_abstain")
        rows.append(_strict_row(span, agrees=agrees, skipped=False, reason=reason))
    operative = [row for row in rows if not row["skipped"]]
    agreed = sum(1 for row in operative if row["agrees"])
    return {
        "admitted": False,
        "agreed": agreed,
        "agrees": bool(operative) and agreed == len(operative),
        "formalized": False,
        "operative": len(operative),
        "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
        "rows": rows,
    }


def _strict_row(span: Mapping[str, Any], *, agrees: bool, skipped: bool, reason: str) -> dict[str, Any]:
    return {
        "agrees": agrees,
        "canonical_citation": str(span.get("canonical_citation") or ""),
        "decompiled": str(span.get("decompiled") or ""),
        "dropped": [str(item) for item in span.get("unsupported_fields") or [] if str(item)],
        "entry_cid": str(span.get("entry_cid") or ""),
        "id": str(span.get("id") or ""),
        "legal_id": str(span.get("legal_id") or ""),
        "reason": reason,
        "skipped": skipped,
        "source_span_id": str(span.get("source_span_id") or span.get("id") or ""),
        "text": str(span.get("text") or ""),
    }


def agreement_from_spans(spans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Replay compiled spans before treating them as preservation evidence.

    A ledger's compiled status is not round-trip agreement. Known gap rows
    retain their diagnostics; compiled rows get a fresh, source-bound census
    without pretending to have model captures. Agreement is not formalization.
    """

    from .autoencoder_router import agreement_census

    spans = list(spans)
    compiled = [dict(span) for span in spans if span.get("status") == "compiled"]
    replayed = iter(agreement_census(compiled, {})["rows"] if compiled else [])

    rows = []
    for span in spans:
        status = str(span.get("status") or "")
        if status in {"non_operative", "inactive"}:
            continue
        fresh = next(replayed) if status == "compiled" else None
        agrees = fresh is not None and fresh.get("agrees") is True and not fresh.get("skipped")
        rows.append(
            {
                "agrees": agrees,
                "canonical_citation": str(span.get("canonical_citation") or ""),
                "decompiled": str(span.get("decompiled") or ""),
                "dropped": list(span.get("unsupported_fields") or []),
                "entry_cid": str(span.get("entry_cid") or ""),
                "id": str(span.get("id") or ""),
                "legal_id": str(span.get("legal_id") or ""),
                "reason": "" if agrees else str(span.get("reason") or span.get("facet") or "compiler_abstain"),
                "rule": dict(span["rule"]) if isinstance(span.get("rule"), Mapping) else {},
                "skipped": False,
                "source_span_id": str(span.get("source_span_id") or ""),
                "text": str(span.get("text") or ""),
            }
        )
        if fresh is not None:
            rule = dict(rows[-1].get("rule") or {})
            rows[-1].update(fresh)
            rows[-1]["agrees"] = agrees
            rows[-1]["observed_compiler_status"] = status
            if rule and not rows[-1].get("rule"):
                rows[-1]["rule"] = rule
    operative = [row for row in rows if not row["skipped"]]
    agreed = sum(1 for row in operative if row["agrees"])
    return {
        "admitted": False,
        "agreed": agreed,
        "agrees": bool(operative) and agreed == len(operative),
        "formalized": False,
        "operative": len(operative),
        "reason": "" if operative and agreed == len(operative) else "compiler_disagreement",
        "rows": rows,
    }


def submit_discrepancies(
    agreement: Mapping[str, Any],
    *,
    board_path: str | Path | None = None,
    query: str = "",
    release_id: str = "",
    upload: Callable[..., dict[str, Any]] | None = None,
    native: Callable[..., dict[str, Any]] | None = None,
    goals: Sequence[Mapping[str, Any]] = (),
    tasks: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Submit failed jobs to the supervisor loop. Does not write JSONL."""

    tasks = [dict(item) for item in tasks] if tasks is not None else discrepancy_tasks(agreement, query=query, release_id=release_id)
    if goals:
        by_task = {
            str(task_id): str(goal.get("goal_id") or "")
            for goal in goals
            for task_id in goal.get("resolves") or []
        }
        for task in tasks:
            assigned = by_task.get(str(task.get("task_id") or ""))
            if assigned:
                task["goal_id"] = assigned
    receipt: dict[str, Any] = {
        "admitted": False,
        "board_namespace": BOARD_NAMESPACE,
        "formalized": False,
        "jsonl_written": False,
        "reason": str(agreement.get("reason") or "compiler_disagreement"),
        "router_called": False,
        "stage": "supervisor_todo",
        "task_count": len(tasks),
        "tasks": tasks,
        "time_management": time_management(tasks),
        "wrote_compiler": False,
        "wrote_decompiler": False,
        "goals": list(goals),
    }
    if board_path is not None:
        receipt["board"] = write_supervisor_board(board_path, tasks, goals=goals)
        receipt["board_path"] = receipt["board"]["board_path"]
    if upload is not None:
        receipt["huggingface"] = upload(tasks)
        receipt["locator"] = dict(receipt["huggingface"].get("locator") or {})
    if native is not None:
        receipt["native_queue"] = native(
            agreement,
            huggingface_locator=receipt.get("locator") or None,
        )
        receipt["authority"] = str(receipt["native_queue"].get("authority") or "accelerate-duckdb")
    return receipt
