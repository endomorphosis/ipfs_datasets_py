"""Operator surface for human IDS candidate review (never auto-files).

Loads queues produced by prior-art / compliance audit, records natural-person
relevance and materiality dispositions, and optionally promotes candidates to
IDS-ready. Exports a human checklist for preparing Form SB/08 or equivalent.

Hard rules
----------
* Never auto-files an IDS.
* IDS-ready requires both relevance and materiality natural-person reviews.
* Not a 37 C.F.R. § 1.56 materiality determination by the system — the human
  records their judgment; the system only gates state transitions.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

IDS_OPERATOR_SCHEMA: Final = "patlaw-ids-review-operator-v1"
IDS_OPERATOR_DISCLAIMER: Final = (
    "IDS candidate review is decision support only. Relevance and materiality "
    "dispositions are recorded judgments of a natural person. This system never "
    "auto-files an IDS, never makes a legal materiality or patentability "
    "determination, and is not a substitute for counsel under 37 C.F.R. § 1.56."
)


class IdsReviewOperatorError(PortfolioAutomationError):
    """Fail-closed IDS operator error."""


def _write_json(path: Path, payload: Mapping[str, Any], *, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise IdsReviewOperatorError(
            f"expected JSON object in {path}", code="invalid_json"
        )
    return dict(data)


def resolve_ids_queue_path(
    *,
    queue_path: str | Path | None = None,
    run_dir: str | Path | None = None,
    application_number: str | None = None,
    queue_id: str | None = None,
    state_root: Path | None = None,
) -> Path:
    """Locate an ids_review_queue.json on disk."""
    if queue_path:
        p = Path(queue_path).expanduser().resolve()
        if not p.is_file():
            raise IdsReviewOperatorError(
                f"IDS queue not found: {p}", code="queue_missing"
            )
        return p

    if run_dir:
        p = Path(run_dir).expanduser().resolve() / "ids_review_queue.json"
        if p.is_file():
            return p
        raise IdsReviewOperatorError(
            f"ids_review_queue.json missing under {run_dir}",
            code="queue_missing",
        )

    root = Path(state_root) if state_root is not None else default_state_root()
    app = re.sub(r"[^0-9A-Za-z]", "", str(application_number or "").strip())
    if app and queue_id:
        cand = root / "ids_queues" / app / f"{queue_id.replace(':', '_')}.json"
        if cand.is_file():
            return cand

    if app:
        # Prefer newest under prior_art runs, then ids_queues/
        prior = root / "prior_art" / app
        newest: Path | None = None
        newest_mtime = -1.0
        if prior.is_dir():
            for q in prior.rglob("ids_review_queue.json"):
                m = q.stat().st_mtime
                if m > newest_mtime:
                    newest_mtime = m
                    newest = q
        iq = root / "ids_queues" / app
        if iq.is_dir():
            for q in iq.glob("*.json"):
                m = q.stat().st_mtime
                if m > newest_mtime:
                    newest_mtime = m
                    newest = q
        if newest is not None:
            return newest

    raise IdsReviewOperatorError(
        "pass --queue-path, --run-dir, or --application-number with an existing queue",
        code="queue_not_found",
    )


def load_ids_queue(path: str | Path) -> Any:
    from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
        IdsReviewQueue,
    )

    return IdsReviewQueue.from_dict(_read_json(Path(path)))


def save_ids_queue(queue: Any, path: str | Path) -> Path:
    return _write_json(Path(path), queue.to_dict())


def list_ids_candidates(queue: Any) -> dict[str, Any]:
    rows = []
    for c in queue.candidates:
        rows.append(
            {
                "candidate_id": c.candidate_id,
                "document_id": c.document_id,
                "state": c.state.value if hasattr(c.state, "value") else str(c.state),
                "citation_text": (c.citation_text or "")[:200],
                "relevance": c.relevance.value
                if hasattr(c.relevance, "value")
                else str(c.relevance),
                "materiality": c.materiality.value
                if hasattr(c.materiality, "value")
                else str(c.materiality),
                "is_ids_ready": bool(c.is_ids_ready),
                "identifiers": dict(c.identifiers or {}),
            }
        )
    ready = sum(1 for r in rows if r["is_ids_ready"])
    return {
        "schema": IDS_OPERATOR_SCHEMA,
        "ok": True,
        "queue_id": queue.queue_id,
        "subject_id": queue.subject_id,
        "candidate_count": len(rows),
        "ids_ready_count": ready,
        "auto_file_blocked": bool(getattr(queue, "auto_file_blocked", True)),
        "candidates": rows,
        "disclaimer": IDS_OPERATOR_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


def review_ids_candidate(
    queue_path: str | Path,
    *,
    candidate_id: str,
    reviewer_id: str,
    relevance: str | None = None,
    materiality: str | None = None,
    promote: bool = False,
    reject: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    """Apply natural-person review actions and persist the queue."""
    from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
        IdsReadyGateError,
        IdsReviewQueueError,
        promote_to_ids_ready,
        record_materiality_review,
        record_relevance_review,
        reject_candidate,
    )

    path = Path(queue_path).expanduser().resolve()
    queue = load_ids_queue(path)
    now = utc_now_iso()
    actions_done: list[str] = []

    try:
        if reject:
            queue = reject_candidate(
                queue,
                candidate_id=candidate_id,
                reviewer_id=reviewer_id,
                acted_at_utc=now,
                notes=notes or None,
                is_natural_person=True,
            )
            actions_done.append("reject")
        else:
            if relevance:
                queue = record_relevance_review(
                    queue,
                    candidate_id=candidate_id,
                    reviewer_id=reviewer_id,
                    disposition=relevance,
                    acted_at_utc=now,
                    notes=notes or None,
                    is_natural_person=True,
                )
                actions_done.append(f"relevance:{relevance}")
            if materiality:
                queue = record_materiality_review(
                    queue,
                    candidate_id=candidate_id,
                    reviewer_id=reviewer_id,
                    disposition=materiality,
                    acted_at_utc=now,
                    notes=notes or None,
                    is_natural_person=True,
                )
                actions_done.append(f"materiality:{materiality}")
            if promote:
                queue = promote_to_ids_ready(
                    queue,
                    candidate_id=candidate_id,
                    reviewer_id=reviewer_id,
                    acted_at_utc=now,
                    notes=notes or None,
                    is_natural_person=True,
                    require_coverage_acknowledgement=False,
                )
                actions_done.append("promote_ids_ready")
    except (IdsReadyGateError, IdsReviewQueueError) as exc:
        raise IdsReviewOperatorError(str(exc), code=getattr(exc, "code", "ids_gate")) from exc

    save_ids_queue(queue, path)
    # Mirror under ids_queues if path is under prior_art
    try:
        subject = str(queue.subject_id or "")
        app = subject.split("app-")[-1] if "app-" in subject else ""
        if app:
            state_root = default_state_root()
            # Prefer parent of prior_art if present
            for parent in path.parents:
                if parent.name == "prior_art" or (parent / "portfolio_seed.json").is_file():
                    state_root = parent if (parent / "portfolio_seed.json").is_file() else parent.parent
                    break
            mirror = (
                state_root
                / "ids_queues"
                / app
                / f"{queue.queue_id.replace(':', '_')}.json"
            )
            save_ids_queue(queue, mirror)
    except Exception:
        pass

    cand = queue.candidate(candidate_id)
    return {
        "schema": IDS_OPERATOR_SCHEMA,
        "ok": True,
        "queue_path": str(path),
        "queue_id": queue.queue_id,
        "actions": actions_done,
        "candidate": {
            "candidate_id": cand.candidate_id,
            "document_id": cand.document_id,
            "state": cand.state.value if hasattr(cand.state, "value") else str(cand.state),
            "relevance": cand.relevance.value
            if hasattr(cand.relevance, "value")
            else str(cand.relevance),
            "materiality": cand.materiality.value
            if hasattr(cand.materiality, "value")
            else str(cand.materiality),
            "is_ids_ready": bool(cand.is_ids_ready),
        },
        "ids_ready_count": sum(1 for c in queue.candidates if c.is_ids_ready),
        "candidate_count": len(queue.candidates),
        "auto_file_blocked": True,
        "disclaimer": IDS_OPERATOR_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


def export_ids_ready_checklist(
    queue_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export IDS-ready (+ candidate summary) as JSON + markdown for human forms."""
    path = Path(queue_path).expanduser().resolve()
    queue = load_ids_queue(path)
    ready = [c for c in queue.candidates if c.is_ids_ready]
    deferred = [
        c
        for c in queue.candidates
        if not c.is_ids_ready
        and str(getattr(c.state, "value", c.state)) != "rejected"
    ]

    rows = []
    for c in ready:
        rows.append(
            {
                "candidate_id": c.candidate_id,
                "document_id": c.document_id,
                "citation_text": c.citation_text,
                "identifiers": dict(c.identifiers or {}),
                "relevance": c.relevance.value
                if hasattr(c.relevance, "value")
                else str(c.relevance),
                "materiality": c.materiality.value
                if hasattr(c.materiality, "value")
                else str(c.materiality),
                "relevance_reviewer_id": c.relevance_reviewer_id,
                "materiality_reviewer_id": c.materiality_reviewer_id,
            }
        )

    md_lines = [
        "# IDS-ready reference checklist (human filing)",
        "",
        IDS_OPERATOR_DISCLAIMER,
        "",
        f"- Queue: `{queue.queue_id}`",
        f"- IDS-ready: **{len(ready)}**",
        f"- Remaining candidates: **{len(deferred)}**",
        f"- Auto-file blocked: **yes**",
        "",
        "## IDS-ready references",
        "",
    ]
    if not ready:
        md_lines.append("_None promoted yet. Complete relevance + materiality reviews._")
    else:
        md_lines.append("| # | Document | Citation / title | Reviewers |")
        md_lines.append("|---|----------|------------------|-----------|")
        for i, c in enumerate(ready, 1):
            cite = (c.citation_text or c.document_id or "").replace("|", "/")
            rev = f"{c.relevance_reviewer_id or '?'}/{c.materiality_reviewer_id or '?'}"
            md_lines.append(f"| {i} | `{c.document_id}` | {cite[:80]} | {rev} |")

    md_lines.extend(
        [
            "",
            "## Next human steps",
            "",
            "1. Prepare USPTO IDS form (e.g. SB/08) with the references above.",
            "2. Attach supporting copies as required.",
            "3. File via Patent Center (Sign / Pay / Submit remain human-only).",
            "",
        ]
    )
    md = "\n".join(md_lines) + "\n"

    out_json = {
        "schema": IDS_OPERATOR_SCHEMA,
        "queue_id": queue.queue_id,
        "subject_id": queue.subject_id,
        "ids_ready": rows,
        "ids_ready_count": len(ready),
        "remaining_candidate_count": len(deferred),
        "auto_file_blocked": True,
        "disclaimer": IDS_OPERATOR_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }

    if output_path:
        outp = Path(output_path).expanduser().resolve()
    else:
        outp = path.parent / "ids_ready_export.json"
    json_path = _write_json(outp, out_json)
    md_path = outp.with_suffix(".md")
    md_path.write_text(md, encoding="utf-8")
    try:
        os.chmod(md_path, 0o600)
    except OSError:
        pass

    return {
        "schema": IDS_OPERATOR_SCHEMA,
        "ok": True,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "ids_ready_count": len(ready),
        "remaining_candidate_count": len(deferred),
        "disclaimer": IDS_OPERATOR_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


__all__ = [
    "IDS_OPERATOR_DISCLAIMER",
    "IDS_OPERATOR_SCHEMA",
    "IdsReviewOperatorError",
    "export_ids_ready_checklist",
    "list_ids_candidates",
    "load_ids_queue",
    "resolve_ids_queue_path",
    "review_ids_candidate",
    "save_ids_queue",
]
