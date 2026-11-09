"""Classify external gates the datasets supervisor must not recycle.

A closed compiled lineage, a length-truncated spent phase, and an official
release that is still missing are retained. A receipt from this module keeps
completion authority false. It does not mark a task complete, spend a model
call, invent a missing file, or open a campaign result on disk. The caller
passes the evidence in the observation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "ipfs_datasets_py.optimizers.todo_daemon.external-resolution@1"
OBSERVATION_FILENAME = "external_resolution_observation.json"
RECEIPT_FILENAME = "external_resolution_receipt.json"
_DONE = {"completed", "complete", "done"}
_GATE_INCIDENTS = frozenset({"gate_fixed_point", "planned_work_blocked_frontier"})
_RETAIN_ACTIONS = frozenset(
    {"retain_closed_lineage", "retain_truncated_phase", "retain_official_release"}
)
_OWNED_JSON_LIMIT = 1_000_000
_TRUNCATED_REASON = (
    "both bounded calls returned finish_reason length and no closed proof; "
    "retain the spent phase, do not spend another call, and do not grant completion"
)
_CLOSED_REASON = (
    "this owner's compiled lineage keeps the published contracts unchanged; "
    "retain the planned row, do not flip it to pending, and do not grant completion"
)
_RELEASE_REASON = (
    "official full cohort file is unavailable; retain the release wait, "
    "do not invent the file, and do not grant completion"
)
_REVIEW_REASON = (
    "dependency-ready planned work stays planned until a reviewed execution contract exists"
)
_OPEN_REASON = "open task is not an external retain"


def read_owned_json(path: Path, *, limit: int = _OWNED_JSON_LIMIT) -> dict[str, Any] | None:
    """Read one regular JSON object. A symlink or an oversized file is ignored."""

    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _closed_model_proof(content: str) -> bool:
    """True when the model body already contains a closed proof object.

    A closed body is not truncation. This does not accept the proof.
    """

    text = content.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        body = text[newline + 1 :] if newline >= 0 else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        text = body.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    proof = parsed.get("proof") if isinstance(parsed, dict) else None
    return isinstance(proof, str) and bool(proof.strip())


def truncated_spent_phase(document: Mapping[str, Any] | None) -> bool:
    """True only for a spent phase whose bounded calls ended on the length cap.

    A winner, a completion claim, a promoted row, or a body that already
    parses as a proof is not this shape.
    """

    if not isinstance(document, Mapping):
        return False
    if document.get("status") != "NO_CONFIRMED_WINNER":
        return False
    if document.get("winner") not in (None, False):
        return False
    if document.get("completion_authority") is not False or document.get("proof_authority") is not False:
        return False
    if document.get("promoted") is not False or document.get("full_campaign_complete") is not False:
        return False
    limits = document.get("limits")
    attempts = document.get("attempts")
    if not isinstance(limits, Mapping) or not isinstance(attempts, list) or not attempts:
        return False
    max_calls = limits.get("max_calls")
    if type(max_calls) is not int or max_calls < 1 or len(attempts) != max_calls:
        return False
    if document.get("local_inference_calls") != max_calls:
        return False
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            return False
        if attempt.get("status") != "RETURNED" or attempt.get("http_status") != 200:
            return False
        if not str(attempt.get("candidate_error") or "").strip():
            return False
        if "sample_index" in attempt and attempt.get("sample_index") is not None:
            return False
        response = attempt.get("response")
        choices = response.get("choices") if isinstance(response, Mapping) else None
        if not isinstance(choices, list) or not choices:
            return False
        for choice in choices:
            if not isinstance(choice, Mapping) or choice.get("finish_reason") != "length":
                return False
            message = choice.get("message")
            content = message.get("content") if isinstance(message, Mapping) else None
            if not isinstance(content, str) or not content.strip() or _closed_model_proof(content):
                return False
    return True


def waiting_official_release(document: Mapping[str, Any] | None) -> bool:
    """True for a release wait that has not called a model and claims no completion.

    A completion claim, a model call, or a promoted row is not this shape.
    The missing cohort file is not invented.
    """

    if not isinstance(document, Mapping):
        return False
    if document.get("status") != "WAITING_RELEASE":
        return False
    if document.get("reason") != "official_full_cohort_file_unavailable":
        return False
    if type(document.get("model_calls")) is not int or document.get("model_calls") != 0:
        return False
    if document.get("completion_authority") is not False or document.get("proof_authority") is not False:
        return False
    if document.get("full_campaign_complete") is not False or document.get("promoted") is True:
        return False
    return True


def _contract_set(value: Any) -> set[str] | None:
    if isinstance(value, dict):
        if not value or any(not isinstance(key, str) or not key for key in value):
            return None
        return set(value)
    if isinstance(value, list):
        if not value or any(not isinstance(item, str) or not item for item in value):
            return None
        return set(value)
    return None


def closed_lineage_match(task_id: str, lineage: Mapping[str, Any] | None) -> bool:
    """True when the published contracts equal the baseline and exclude task_id.

    A drifted set, an empty set, or a boolean flag without the contract ids
    stays reviewable. This does not read a profile from disk.
    """

    if not task_id or not isinstance(lineage, Mapping):
        return False
    published = _contract_set(lineage.get("published_contracts"))
    baseline = _contract_set(lineage.get("baseline_contracts"))
    if published is None or baseline is None:
        return False
    return published == baseline and task_id not in published


def _work_complete_allowed(node: Mapping[str, Any]) -> bool:
    decisions = node.get("decisions")
    subgoals = node.get("subgoals")
    mutations = node.get("board_mutations")
    if not isinstance(decisions, list) or not decisions:
        return False
    if not isinstance(subgoals, list) or subgoals:
        return False
    if not isinstance(mutations, list) or mutations:
        return False
    return all(
        isinstance(item, Mapping)
        and item.get("action") == "task_status_complete"
        and item.get("completion_authority") is False
        and item.get("board_mutation") is False
        for item in decisions
    )


def correct_completion_claims(document: Any) -> tuple[Any, int]:
    """Force illegal completion claims off. Never grants completion authority.

    ``work_complete`` may stay true only when every decision is already
    ``task_status_complete``, no subgoal remains, and no board mutation is recorded.
    """

    changed = 0

    def walk(node: Any) -> Any:
        nonlocal changed
        if isinstance(node, dict):
            corrected = {key: walk(value) for key, value in node.items()}
            if "completion_authority" in corrected and corrected["completion_authority"] is not False:
                corrected["completion_authority"] = False
                changed += 1
            if (
                "work_complete" in corrected
                and corrected["work_complete"] is not False
                and not _work_complete_allowed(corrected)
            ):
                corrected["work_complete"] = False
                changed += 1
            return corrected
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(document), changed


def _ids(values: Any) -> set[str]:
    if isinstance(values, str):
        text = values.strip()
        return {text} if text else set()
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and value}


def _phase_result(task: Mapping[str, Any], results: Mapping[str, Any], task_id: str) -> Mapping[str, Any] | None:
    phase = task.get("phase_result")
    if isinstance(phase, Mapping):
        return phase
    shared = results.get(task_id)
    return shared if isinstance(shared, Mapping) else None


def _lineage(task: Mapping[str, Any], observation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    lineage = task.get("lineage")
    if isinstance(lineage, Mapping):
        return lineage
    shared = observation.get("lineage")
    return shared if isinstance(shared, Mapping) else None


def _task_decision(
    task: Mapping[str, Any],
    *,
    results: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> dict[str, Any] | None:
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        return None
    status = str(task.get("status") or "").strip().lower()
    base = {
        "task_id": task_id,
        "status": status,
        "board_mutation": False,
        "completion_authority": False,
        "provider_calls": False,
    }
    if status in _DONE:
        return {**base, "action": "task_status_complete", "reason": "recorded status is already completed"}
    if status == "planned":
        if closed_lineage_match(task_id, _lineage(task, observation)):
            return {**base, "action": "retain_closed_lineage", "reason": _CLOSED_REASON}
        return {**base, "action": "review_execution_contract", "reason": _REVIEW_REASON}
    phase = _phase_result(task, results, task_id)
    if waiting_official_release(phase):
        return {**base, "action": "retain_official_release", "reason": _RELEASE_REASON}
    if truncated_spent_phase(phase):
        return {**base, "action": "retain_truncated_phase", "reason": _TRUNCATED_REASON}
    return {**base, "action": "review_open_task", "reason": _OPEN_REASON}


def _frontier_is_explicit(observation: Mapping[str, Any]) -> bool:
    if any(
        key in observation
        for key in (
            "blocked_task_ids",
            "dependency_ready_task_ids",
            "dependency_ready",
            "active_task_id",
            "incidents",
            "planned_work",
        )
    ):
        return True
    lanes = observation.get("lanes")
    return isinstance(lanes, list) and any(
        isinstance(lane, Mapping) and str(lane.get("active_task_id") or "") for lane in lanes
    )


def resolve_external_frontier(observation: Any) -> dict[str, Any]:
    """Return a retain receipt for an external frontier. Completion stays false.

    The frontier is retained only when every open task is a closed lineage, a
    truncated spent phase, or an official-release wait. Any other task, a
    drifted contract set, or a completion claim on a phase result stays
    reviewable. Board mutations in the observation are not applied.
    """

    if not isinstance(observation, Mapping):
        observation = {}
    results = observation.get("results") if isinstance(observation.get("results"), Mapping) else {}
    tasks = observation.get("tasks")
    decisions: list[dict[str, Any]] = []
    if isinstance(tasks, list):
        for item in tasks:
            if not isinstance(item, Mapping):
                continue
            decision = _task_decision(item, results=results, observation=observation)
            if decision is not None:
                decisions.append(decision)
    by_id = {item["task_id"]: item for item in decisions}

    blocked = _ids(observation.get("blocked_task_ids"))
    ready = _ids(observation.get("dependency_ready_task_ids")) | _ids(observation.get("dependency_ready"))
    active = _ids(observation.get("active_task_id"))
    planned = observation.get("planned_work") if isinstance(observation.get("planned_work"), Mapping) else {}
    blocked |= _ids(planned.get("blocked_task_ids"))
    ready |= _ids(planned.get("dependency_ready_planned_task_ids"))
    named: set[str] = set()
    incident_ok = True
    incidents = observation.get("incidents")
    if "incidents" in observation:
        if not isinstance(incidents, list) or not incidents:
            incident_ok = False
        else:
            for item in incidents:
                if not isinstance(item, Mapping) or item.get("kind") not in _GATE_INCIDENTS:
                    incident_ok = False
                    break
                named |= _ids(item.get("task"))
                evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
                named |= _ids(evidence.get("task_id"))
                blocked |= _ids(evidence.get("blocked_task_ids"))
                ready |= _ids(evidence.get("dependency_ready_planned_task_ids"))
    lanes = observation.get("lanes")
    if isinstance(lanes, list):
        for lane in lanes:
            if isinstance(lane, Mapping):
                active |= _ids(lane.get("active_task_id"))
    involved = blocked | named | active
    if not involved and not ready and not _frontier_is_explicit(observation):
        involved = {item["task_id"] for item in decisions if item["action"] != "task_status_complete"}

    retained = False
    reason = ""
    open_ids = involved | ready
    if incident_ok and open_ids and all(by_id.get(task_id, {}).get("action") in _RETAIN_ACTIONS for task_id in open_ids):
        if all(by_id.get(task_id, {}).get("action") == "retain_closed_lineage" for task_id in ready):
            actions = {by_id[task_id]["action"] for task_id in involved}
            if actions == {"retain_truncated_phase"} and not ready:
                reason = "truncated_phase_retained"
            else:
                reason = "retained_external_frontier"
            retained = True

    subgoals = observation.get("subgoals") if isinstance(observation.get("subgoals"), list) else []
    mutations = observation.get("board_mutations") if isinstance(observation.get("board_mutations"), list) else []
    work_complete = bool(
        decisions
        and not subgoals
        and not mutations
        and all(item["action"] == "task_status_complete" for item in decisions)
    )
    receipt = {
        "schema": SCHEMA,
        "retained": retained,
        "reason": reason,
        "completion_authority": False,
        "work_complete": work_complete,
        "board_mutations": [],
        "subgoals": [],
        "provider_calls": False,
        "decisions": decisions,
    }
    corrected, _count = correct_completion_claims(receipt)
    return corrected if isinstance(corrected, dict) else receipt
