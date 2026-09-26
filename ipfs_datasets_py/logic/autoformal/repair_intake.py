"""Route unsafe repair inputs to native review state, never to success.

This is a supervisor-owner pre-dispatch operation, not legal classification.
Original packets, failed observations, attempt history and completion gates
remain intact. Only the native lifecycle API can park an unclaimed task.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .supervisor_queue import (
    NAMESPACE, REGRESSION_TESTS, SCHEMA, RepairQueueError, canonical_bytes,
    read_packet, repair_outputs,
)

INTAKE_SCHEMA = "uscode-autoformal-repair-intake/v1"
UNCLAIMED = frozenset({"proposed", "admitted", "pending", "ready", "todo", "queued", "retrying"})
_EDITORIAL_HEADING = re.compile(
    r"\s*§{1,2}[^.\n]{1,160}\.\s*(?:Omitted|Repealed|Transferred|Reserved)\.?\s*", re.IGNORECASE)
_BRACKETED_EDITORIAL_HEADING = re.compile(
    r"\s*\[\s*§{1,2}[^.\n]{1,160}\.\s*(?:Omitted|Repealed|Transferred|Reserved)"
    r"\.\s*[^\]\n]{0,200}\]\s*", re.IGNORECASE)
_DANGLING_REFERENCE = re.compile(
    r"\b(?:under|pursuant\s+to|in\s+accordance\s+with|as\s+defined\s+in|described\s+in|provided\s+in|governed\s+by|established\s+in)\s*[.;,]"
    r"|\bhas\s+the\s+meaning\s+given\b[^.\n]{0,240}\bin\s*[.;,]"
    r"|\[\s*et\s+seq\.?\s*\]",
    re.IGNORECASE,
)


def review_flags(packet: dict) -> list[str]:
    """A conservative routing alarm; it does not assign a legal status."""
    rows = [packet["row"], *packet.get("preserve_rows", ())]
    flags = []
    if any(_EDITORIAL_HEADING.fullmatch(row["text"])
           or _BRACKETED_EDITORIAL_HEADING.fullmatch(row["text"]) for row in rows):
        flags.append("editorial_heading_requires_source_classification")
    if any(_DANGLING_REFERENCE.search(row["text"]) for row in rows):
        flags.append("dangling_reference_requires_source_hydration")
    return flags


def route_intake_reviews(source, *, apply: bool = False) -> dict:
    """CAS only sealed, unclaimed review tasks to blocked; never reset a retry.

    Callers applying changes must hold the dedicated feedback runtime's owner
    lock. CAS still fences a task concurrently claimed by another native owner.
    Planning is read-only; classification, acceptance and validation are absent.
    """
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity

    before = source.snapshot().revision
    records, cursor = [], ""
    while True:
        page = source.list_tasks(cursor=cursor, limit=100)
        if page.revision != before:
            raise RepairQueueError("queue changed while planning intake review")
        records.extend(page.tasks)
        if len(records) > 1000:
            raise RepairQueueError("intake pass exceeds its bounded task inventory")
        cursor = page.next_cursor
        if not cursor:
            break
    candidates = []
    for record in records:
        if record.body.get("board_namespace") != NAMESPACE:
            raise RepairQueueError("intake requires a dedicated repair queue")
        if record.status not in UNCLAIMED:
            continue
        body = record.body
        digest = body["packet_sha256"]
        path = Path(body["packet_path"])
        if path.is_symlink():
            raise RepairQueueError("intake packet cannot be a symlink")
        packet = read_packet(path, digest)
        if (record.task_cid != content_identity({"schema": SCHEMA, "packet_sha256": digest})
                or packet.get("board_namespace") != NAMESPACE
                or packet.get("admitted") is not False or packet.get("formalized") is not False
                or packet["regression_tests"] != list(REGRESSION_TESTS)
                or [item["path"] for item in record.outputs] != repair_outputs(packet, digest)):
            raise RepairQueueError("intake task differs from sealed evidence or edit policy")
        flags = review_flags(packet)
        if flags:
            candidates.append((record, digest, flags))
    if source.snapshot().revision != before:
        raise RepairQueueError("queue changed before intake review; no transition authorized")
    transitions = []
    for record, digest, flags in candidates:
        receipt = {"schema": INTAKE_SCHEMA, "operation": "autoformal_intake_review_required",
                   "reason": flags[0], "review_flags": flags, "task_cid": record.task_cid,
                   "packet_sha256": digest, "previous_status": record.status,
                   "previous_status_receipt_sha256": hashlib.sha256(
                       canonical_bytes(record.body.get("completion_receipt", {}))).hexdigest(),
                   "source_classification": "unreviewed", "provider_dispatched": False,
                   "counts_as_repair": False, "counts_as_validation": False,
                   "admitted": False, "formalized": False}
        transition = {"task_cid": record.task_cid, "task_alias": record.task_alias,
                      "previous_status": record.status, "proposed_status": "blocked",
                      "packet_sha256": digest, "review_flags": flags, "applied": False}
        if apply:
            result = source.compare_and_set_status(record.task_cid, record.revision, "blocked", receipt=receipt)
            if not result.changed or result.task.status != "blocked":
                raise RepairQueueError("native intake transition did not reach blocked review state")
            transition.update(applied=True, event_cursor=result.event_cursor, receipt_cid=result.receipt_cid,
                              task_revision=result.task.revision)
        transitions.append(transition)
    return {"schema": INTAKE_SCHEMA, "queue_revision_before": before,
            "queue_revision_after": source.snapshot().revision, "apply": apply,
            "transitions": transitions, "review_required": len(transitions),
            "repairs_completed": 0, "tasks_claimed": False, "provider_dispatched": False,
            "admitted": False, "formalized": False}
