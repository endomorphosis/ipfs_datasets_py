"""Admit one derived task when a board validation gap is unchanged.

The seed task command and validation stay as written. A rendered-control
census that is missing or empty is the static-template gap: the repair is a
live DOM census that does not click tool buttons. The derived task is
content-addressed by its id, so a second admission is a duplicate.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

RENDERED_CENSUS_COMMAND = "node swissknife/scripts/run-rendered-census.mjs"
MATRIX_JOIN_COMMAND = "node swissknife/scripts/build-orb-idl-control-matrix.cjs"
_MIN_CENSUS_APPS = 45
_INVOKE_DISPOSITIONS = {"invoke", "confirm-then-invoke", "deny"}


def derived_task_id(task_id: str) -> str:
    head, separator, tail = str(task_id).rpartition("-")
    if not separator or not tail.isdigit() or not head:
        raise ValueError(f"task id {task_id} cannot grow a refill id")
    return f"{head}-R{tail}"


def derived_goal_id(goal_id: str) -> str:
    text = str(goal_id or "").strip()
    if not text:
        return ""
    if text.endswith("-R"):
        return text
    return f"{text}-R"


def rendered_census_gap(fields: Mapping[str, str], artifact_text: str) -> bool:
    """True when the artifact does not satisfy the live rendered-census contract."""

    predicted = str(fields.get("predicted_files") or "")
    validation = str(fields.get("validation") or "")
    named = (
        "rendered-control-census.json" in predicted
        or "vog_rendered_census_requires_live_dom.py" in validation
    )
    if not named:
        return False
    text = artifact_text or ""
    if len(text.encode("utf-8")) < 128:
        return True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return True
    if not isinstance(payload, dict):
        return True
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    controls = payload.get("controls") if isinstance(payload.get("controls"), list) else []
    return len(rows) < _MIN_CENSUS_APPS and len(controls) < _MIN_CENSUS_APPS


def matrix_binding_gap(fields: Mapping[str, str], artifact_text: str) -> bool:
    """True when a live gateway selector was joined as if it had no binding.

    The rendered census stores the binding in the selector. A join that leaves
    that selector unsupported, with IDL method none, did not read the term.
    """

    predicted = str(fields.get("predicted_files") or "")
    validation = str(fields.get("validation") or "")
    named = (
        "orb-idl-control-matrix.json" in predicted
        or "vog_orb_idl_matrix_requires_join.py" in validation
    )
    if not named:
        return False
    try:
        payload = json.loads(artifact_text or "")
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        selector = str(row.get("selector") or "")
        if "data-live-gateway-binding=" not in selector:
            continue
        disposition = str(row.get("disposition") or "")
        tool_id = str(row.get("tool_id") or "")
        method = str(row.get("idl_method") or "")
        if (
            disposition in _INVOKE_DISPOSITIONS
            and tool_id.startswith("mcp++")
            and method
            and method != "none"
        ):
            continue
        return True
    return False


def _task_present(todo_text: str, task_id: str) -> bool:
    return f"## {task_id} " in todo_text or f"## {task_id}\n" in todo_text


def admit_validation_gap(
    todo_text: str,
    *,
    task_header_prefix: str,
    task_id: str,
    fields: Mapping[str, str],
    artifact_text: str,
) -> dict[str, Any]:
    """Append one derived goal and task, or report why none was admitted.

    The returned todo is the only board mutation. Completion authority stays false.
    """

    if rendered_census_gap(fields, artifact_text):
        repair_reason = "rendered_census_live_dom"
        title = "Refill the rendered census from the live DOM"
        command = RENDERED_CENSUS_COMMAND
        outputs = "swissknife/test-results/virtual-desktop-ipfs-mcp-orb/vog/rendered-control-census.json"
        conflict = "Do not click tool buttons. Do not edit app source."
        acceptance = (
            "Live DOM census, source_template false, clicked false, "
            "at least 45 apps, no template selectors."
        )
    elif matrix_binding_gap(fields, artifact_text):
        repair_reason = "matrix_binding_join"
        title = "Refill the ORB/IDL join from gateway bindings"
        command = MATRIX_JOIN_COMMAND
        outputs = "swissknife/test-results/virtual-desktop-ipfs-mcp-orb/vog/orb-idl-control-matrix.json"
        conflict = "Do not edit app source. Do not edit the census script."
        acceptance = (
            "A data-live-gateway-binding selector is invoke or confirm-then-invoke "
            "and names an mcp++ tool id. Shell chrome stays local-only."
        )
    else:
        return {
            "admitted": False,
            "reason": "no_symbolic_repair",
            "todo_text": todo_text,
            "work_complete": False,
            "completion_authority": False,
        }
    family = task_header_prefix.strip().removeprefix("## ").strip()
    try:
        refill_id = derived_task_id(task_id)
    except ValueError as exc:
        return {
            "admitted": False,
            "reason": str(exc),
            "todo_text": todo_text,
            "work_complete": False,
            "completion_authority": False,
        }
    if family and not refill_id.startswith(family):
        return {
            "admitted": False,
            "reason": "task_prefix_mismatch",
            "todo_text": todo_text,
            "work_complete": False,
            "completion_authority": False,
        }
    if _task_present(todo_text, refill_id):
        return {
            "admitted": False,
            "reason": "duplicate_refill",
            "derived_task_id": refill_id,
            "todo_text": todo_text,
            "work_complete": False,
            "completion_authority": False,
        }
    goal = derived_goal_id(str(fields.get("goal_id") or ""))
    depends = str(fields.get("depends_on") or "").strip()
    validation = str(fields.get("validation") or "").strip()
    predicted = str(fields.get("predicted_files") or "").strip()
    timeout = str(fields.get("implementation_timeout_seconds") or "7200").strip()
    resource = str(fields.get("resource_class") or "cpu-browser").strip()
    block = "\n".join(
        [
            f"## {refill_id} {title}",
            "- Status: pending",
            "- Priority: P0",
            "- Track: refill",
            f"- Depends on: {depends}",
            f"- Goal id: {goal}",
            f"- Satisfies: {task_id}",
            f"- Outputs: {outputs}",
            f"- Deterministic command: {command}",
            f"- Validation: {validation}",
            "- Resource class: " + resource,
            f"- Implementation timeout seconds: {timeout}",
            f"- Predicted files: {predicted}",
            f"- Conflict policy: {conflict}",
            f"- Acceptance: {acceptance}",
            "",
        ]
    )
    updated = todo_text
    if updated and not updated.endswith("\n"):
        updated += "\n"
    updated += "\n" + block
    return {
        "admitted": True,
        "reason": repair_reason,
        "derived_task_id": refill_id,
        "derived_goal_id": goal,
        "todo_text": updated,
        "work_complete": False,
        "completion_authority": False,
    }
