"""PAAR conflict review report + human disposition API (PAAR-040 / PAAR-041).

Persists :class:`~ipfs_datasets_py.processors.domains.patent.conflict_risk_engine.ConflictRiskReport`
(``ConflictRiskReport@1``) from ``conflict_risk_engine`` outputs, records
natural-person dispositions, and binds ``consider_ids`` dispositions into the
human IDS review queue **without** auto-filing.

Design invariants
-----------------
* **Not legal advice**; never novelty / obviousness / patentability conclusions.
* Disposition codes closed set: ``not_material`` | ``consider_ids`` |
  ``distinguish_in_remarks`` | ``needs_counsel`` | ``deferred``.
* Every disposition requires a non-empty ``acknowledger_name`` (natural person).
* ``auto_file_blocked`` always ``true``; no Sign / Pay / Submit; fail closed.
* Digests are content-bound (canonical JSON, wall-clock excluded from digest).
* Writes under prior-art run dir and/or review run dir when paths are provided.
* ``consider_ids`` only **enqueues** human IDS candidates; promote remains a
  separate natural-person action via ``ids_review_operator``.

Conflict policy (PAAR-040/041): own this module; call ``conflict_risk_engine``
and ``ids_review_queue`` / ``ids_review_operator`` as libraries only.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
    CONFLICT_RISK_INTERFACE,
    CONFLICT_RISK_REPORT_SCHEMA,
    REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER,
    ConflictRiskEngineError,
    ConflictRiskReport,
    DispositionCode,
    HumanDisposition,
    compute_content_digest,
    score_conflict_risk,
    sha256_hex,
)

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

CONFLICT_REVIEW_REPORT_SCHEMA: Final = CONFLICT_RISK_REPORT_SCHEMA
CONFLICT_REVIEW_INTERFACE: Final = CONFLICT_RISK_INTERFACE
CONFLICT_REVIEW_CODE_VERSION: Final = "1.0.0"

CONFLICT_RISK_REPORT_FILENAME: Final = "conflict_risk_report.json"
CONFLICT_DISPOSITION_LOG_FILENAME: Final = "conflict_dispositions.jsonl"

REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER: Final = (
    "Review-only conflict risk report with human disposition binding. "
    "Risk scores are heuristic triage signals only. Not legal advice, not a "
    "novelty determination, not an obviousness determination, and not a "
    "not a patentability conclusion. Dispositions are natural-person records only. "
    "consider_ids enqueues human IDS candidates and never files an IDS. "
    "auto_file_blocked=true. Named human review is required before any legal "
    "or filing action."
)

DISPOSITION_CODES: Final[frozenset[str]] = frozenset(
    {
        DispositionCode.NOT_MATERIAL.value,
        DispositionCode.CONSIDER_IDS.value,
        DispositionCode.DISTINGUISH_IN_REMARKS.value,
        DispositionCode.NEEDS_COUNSEL.value,
        DispositionCode.DEFERRED.value,
    }
)

_NONEMPTY_NAME_RE = re.compile(r"\A\S.+\S\Z|\A\S\Z")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._:/=+\-]+")


class ConflictReviewReportError(ValueError):
    """Bounded conflict-review report failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "conflict_review_report_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
        raise ConflictReviewReportError(
            f"expected JSON object in {path}", code="invalid_json"
        )
    return dict(data)


def _normalize_app(application_number: str | None) -> str:
    return re.sub(r"\D", "", str(application_number or "")) or str(
        application_number or ""
    ).strip()


def _require_acknowledger_name(name: str | None) -> str:
    text = str(name or "").strip()
    if not text or not _NONEMPTY_NAME_RE.match(text):
        raise ConflictReviewReportError(
            "acknowledger_name is required for every human disposition "
            "(natural person must be named; fail closed)",
            code="acknowledger_name_required",
        )
    if len(text) > 256:
        raise ConflictReviewReportError(
            "acknowledger_name exceeds 256 characters",
            code="acknowledger_name_too_long",
        )
    return text


def _coerce_disposition_code(value: str | DispositionCode) -> DispositionCode:
    if isinstance(value, DispositionCode):
        return value
    raw = str(value or "").strip().lower()
    if raw not in DISPOSITION_CODES:
        raise ConflictReviewReportError(
            f"invalid disposition_code {value!r}; allowed: "
            + ", ".join(sorted(DISPOSITION_CODES)),
            code="invalid_disposition_code",
        )
    return DispositionCode(raw)


def _safe_document_id(hit_id: str) -> str:
    """Sanitize hit id into IdsReferenceCandidate document_id vocabulary."""
    raw = str(hit_id or "").strip() or "unknown"
    cleaned = _SAFE_ID_RE.sub("-", raw).strip(".-")
    if not cleaned:
        cleaned = f"hit-{sha256_hex(raw)[:12]}"
    if not cleaned[0].isalnum():
        cleaned = f"d{cleaned}"
    return cleaned[:256]


def _safe_reviewer_id(name: str) -> str:
    """Map natural-person display name to IdsReviewAction reviewer_id form."""
    raw = str(name or "").strip()
    # Prefer operator:slug form when spaces/punctuation present
    slug = re.sub(r"[^A-Za-z0-9._:/=+\-]+", "-", raw).strip("-")
    if not slug:
        slug = f"person-{sha256_hex(raw)[:12]}"
    if not slug[0].isalnum():
        slug = f"p{slug}"
    if ":" not in slug and " " in raw:
        slug = f"operator:{slug}"[:256]
    return slug[:256]


def _as_report(value: ConflictRiskReport | Mapping[str, Any]) -> ConflictRiskReport:
    if isinstance(value, ConflictRiskReport):
        return value
    if isinstance(value, Mapping):
        return ConflictRiskReport.from_dict(value)
    raise ConflictReviewReportError(
        "report must be ConflictRiskReport or mapping", code="invalid_report"
    )


def recompute_report_digest(report: ConflictRiskReport) -> ConflictRiskReport:
    """Return a copy with content_digest rebound to current report content."""
    digest = compute_content_digest(
        report_id=report.report_id,
        application_number=report.application_number,
        matter_risk=report.matter_risk,
        cells=report.cells,
        coverage_gaps=report.coverage_gaps,
        dispositions=report.dispositions,
        coverage_penalty_applied=report.coverage_penalty_applied,
    )
    if digest == report.content_digest:
        return report
    return ConflictRiskReport(
        report_id=report.report_id,
        application_number=report.application_number,
        matter_risk=report.matter_risk,
        cells=report.cells,
        coverage_gaps=report.coverage_gaps,
        content_digest=digest,
        generated_at_utc=report.generated_at_utc,
        dispositions=report.dispositions,
        schema=report.schema,
        disclaimer=report.disclaimer,
        auto_file_blocked=True,
        method_default=report.method_default,
        metadata=dict(report.metadata),
        coverage_penalty_applied=report.coverage_penalty_applied,
    )


def report_to_payload(report: ConflictRiskReport) -> dict[str, Any]:
    """Serialize report with hard auto_file_blocked invariant."""
    payload = report.to_dict()
    payload["auto_file_blocked"] = True
    payload["interface"] = CONFLICT_REVIEW_INTERFACE
    payload["disclaimer"] = payload.get("disclaimer") or REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER
    # Surface acknowledger_name alongside schema acknowledger_id for operators.
    disps: list[dict[str, Any]] = []
    for d in payload.get("dispositions") or []:
        if not isinstance(d, Mapping):
            continue
        row = dict(d)
        if row.get("acknowledger_id") and not row.get("acknowledger_name"):
            row["acknowledger_name"] = row["acknowledger_id"]
        disps.append(row)
    payload["dispositions"] = disps
    if payload.get("auto_file_blocked") is not True:
        raise ConflictReviewReportError(
            "auto_file_blocked must be true", code="auto_file_invariant"
        )
    return payload


# ---------------------------------------------------------------------------
# Build / load / persist
# ---------------------------------------------------------------------------


def build_conflict_review_report(
    *,
    application_number: str = "",
    limitations: Sequence[Any] | None = None,
    hits: Sequence[Any] | None = None,
    claim_graph: Any | None = None,
    journal: Any | None = None,
    chart: Any | None = None,
    distinguishability_matrix: Mapping[str, Any] | None = None,
    coverage_gaps: Sequence[Any] | None = None,
    coverage_declaration: Any | None = None,
    plan: Any | None = None,
    dispositions: Sequence[Any] | None = None,
    report_id: str | None = None,
    generated_at_utc: str | None = None,
    metadata: Mapping[str, str] | None = None,
    engine_report: ConflictRiskReport | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> ConflictRiskReport:
    """Build ConflictRiskReport@1 via engine or wrap an existing engine report.

    When *engine_report* is provided it is normalized and digest-rebound;
    otherwise delegates to :func:`score_conflict_risk`.
    """
    if engine_report is not None:
        report = _as_report(engine_report)
        # Force invariants
        report = ConflictRiskReport(
            report_id=report.report_id or (report_id or f"crr:wrap:{sha256_hex('x')[:12]}"),
            application_number=report.application_number
            or _normalize_app(application_number),
            matter_risk=report.matter_risk,
            cells=report.cells,
            coverage_gaps=report.coverage_gaps,
            content_digest=report.content_digest or "",
            generated_at_utc=report.generated_at_utc or generated_at_utc or _utc_now_iso(),
            dispositions=report.dispositions,
            schema=CONFLICT_RISK_REPORT_SCHEMA,
            disclaimer=report.disclaimer or REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER,
            auto_file_blocked=True,
            method_default=report.method_default,
            metadata={**dict(report.metadata), **dict(metadata or {})},
            coverage_penalty_applied=report.coverage_penalty_applied,
        )
        return recompute_report_digest(report)

    try:
        report = score_conflict_risk(
            application_number=application_number,
            limitations=limitations,
            hits=hits,
            claim_graph=claim_graph,
            journal=journal,
            chart=chart,
            distinguishability_matrix=distinguishability_matrix,
            coverage_gaps=coverage_gaps,
            coverage_declaration=coverage_declaration,
            plan=plan,
            dispositions=dispositions,
            report_id=report_id,
            generated_at_utc=generated_at_utc,
            metadata=metadata,
            **kwargs,
        )
    except ConflictRiskEngineError as exc:
        raise ConflictReviewReportError(
            str(exc), code=getattr(exc, "code", "conflict_risk_engine_error")
        ) from exc
    return recompute_report_digest(report)


def resolve_conflict_report_path(
    *,
    path: str | Path | None = None,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
) -> Path | None:
    """Locate an on-disk conflict report if present."""
    if path:
        p = Path(path).expanduser().resolve()
        return p if p.is_file() else None
    for base in (prior_art_run_dir, review_run_dir):
        if not base:
            continue
        candidate = Path(base).expanduser().resolve() / CONFLICT_RISK_REPORT_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_conflict_review_report(
    path: str | Path | None = None,
    *,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
) -> ConflictRiskReport:
    """Load ConflictRiskReport@1 from an explicit path or run directories."""
    resolved = resolve_conflict_report_path(
        path=path,
        prior_art_run_dir=prior_art_run_dir,
        review_run_dir=review_run_dir,
    )
    if resolved is None:
        raise ConflictReviewReportError(
            "conflict_risk_report.json not found; pass path, prior_art_run_dir, "
            "or review_run_dir",
            code="report_not_found",
        )
    report = ConflictRiskReport.from_dict(_read_json(resolved))
    return recompute_report_digest(report)


def persist_conflict_review_report(
    report: ConflictRiskReport | Mapping[str, Any],
    *,
    path: str | Path | None = None,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist ConflictRiskReport@1 under provided run dirs and/or path.

    Writes ``conflict_risk_report.json``. When both prior_art and review run
    dirs are given, the same payload is written to both (digest-identical).
    """
    report_obj = recompute_report_digest(_as_report(report))
    if report_obj.auto_file_blocked is not True:
        raise ConflictReviewReportError(
            "auto_file_blocked must be true", code="auto_file_invariant"
        )
    payload = report_to_payload(report_obj)

    targets: list[Path] = []
    if path:
        targets.append(Path(path).expanduser().resolve())
    if prior_art_run_dir:
        targets.append(
            Path(prior_art_run_dir).expanduser().resolve()
            / CONFLICT_RISK_REPORT_FILENAME
        )
    if review_run_dir:
        targets.append(
            Path(review_run_dir).expanduser().resolve() / CONFLICT_RISK_REPORT_FILENAME
        )
    if not targets:
        raise ConflictReviewReportError(
            "pass path, prior_art_run_dir, and/or review_run_dir to persist",
            code="missing_persist_target",
        )

    written: list[str] = []
    for dest in targets:
        written.append(str(_write_json(dest, payload)))

    return {
        "schema": CONFLICT_REVIEW_REPORT_SCHEMA,
        "ok": True,
        "report_id": report_obj.report_id,
        "application_number": report_obj.application_number,
        "content_digest": report_obj.content_digest,
        "matter_risk": report_obj.matter_risk.value
        if hasattr(report_obj.matter_risk, "value")
        else str(report_obj.matter_risk),
        "cell_count": len(report_obj.cells),
        "disposition_count": len(report_obj.dispositions),
        "coverage_gap_count": len(report_obj.coverage_gaps),
        "auto_file_blocked": True,
        "paths": written,
        "primary_path": written[0],
        "disclaimer": REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER,
        "generated_at_utc": _utc_now_iso(),
    }


def build_and_persist_conflict_review_report(
    *,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
    path: str | Path | None = None,
    **build_kwargs: Any,
) -> dict[str, Any]:
    """Score (or wrap) then persist ConflictRiskReport@1."""
    report = build_conflict_review_report(**build_kwargs)
    result = persist_conflict_review_report(
        report,
        path=path,
        prior_art_run_dir=prior_art_run_dir,
        review_run_dir=review_run_dir,
    )
    result["report"] = report_to_payload(report)
    return result


# ---------------------------------------------------------------------------
# Human disposition API
# ---------------------------------------------------------------------------


def record_human_disposition(
    report: ConflictRiskReport | Mapping[str, Any],
    *,
    disposition_code: str | DispositionCode,
    acknowledger_name: str,
    cell_ids: Sequence[str] | None = None,
    notes: str = "",
    acknowledged_at_utc: str | None = None,
    persist: bool = False,
    path: str | Path | None = None,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Append a human disposition requiring *acknowledger_name*.

    Returns updated report payload. Optionally re-persists under run dirs.
    Never auto-files; ``auto_file_blocked`` remains true.
    """
    name = _require_acknowledger_name(acknowledger_name)
    code = _coerce_disposition_code(disposition_code)
    report_obj = _as_report(report)

    known = {c.cell_id for c in report_obj.cells}
    requested = tuple(str(x).strip() for x in (cell_ids or ()) if str(x).strip())
    if requested:
        missing = [cid for cid in requested if cid not in known]
        if missing and known:
            # Fail closed when report has cells but disposition cites unknowns.
            raise ConflictReviewReportError(
                f"disposition cell_ids not in report: {missing[:8]}",
                code="unknown_cell_ids",
            )
    else:
        # Empty cell_ids = disposition applies to all cells (or none if empty report)
        requested = tuple(c.cell_id for c in report_obj.cells)

    ts = acknowledged_at_utc or _utc_now_iso()
    # Normalize to Z suffix for ISO consistency
    if ts.endswith("+00:00"):
        ts = ts[:-6] + "Z"

    disp = HumanDisposition(
        disposition_code=code,
        acknowledger_id=name,  # schema field; value is natural-person name
        acknowledged_at_utc=ts,
        cell_ids=requested,
        notes=str(notes or "")[:4096],
    )

    updated = ConflictRiskReport(
        report_id=report_obj.report_id,
        application_number=report_obj.application_number,
        matter_risk=report_obj.matter_risk,
        cells=report_obj.cells,
        coverage_gaps=report_obj.coverage_gaps,
        content_digest="",  # recomputed
        generated_at_utc=report_obj.generated_at_utc,
        dispositions=(*report_obj.dispositions, disp),
        schema=report_obj.schema,
        disclaimer=report_obj.disclaimer,
        auto_file_blocked=True,
        method_default=report_obj.method_default,
        metadata=dict(report_obj.metadata),
        coverage_penalty_applied=report_obj.coverage_penalty_applied,
    )
    updated = recompute_report_digest(updated)
    payload = report_to_payload(updated)

    out: dict[str, Any] = {
        "schema": CONFLICT_REVIEW_REPORT_SCHEMA,
        "ok": True,
        "report_id": updated.report_id,
        "application_number": updated.application_number,
        "content_digest": updated.content_digest,
        "previous_content_digest": report_obj.content_digest,
        "disposition": {
            **disp.to_dict(),
            "acknowledger_name": name,
        },
        "disposition_count": len(updated.dispositions),
        "auto_file_blocked": True,
        "report": payload,
        "disclaimer": REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER,
        "generated_at_utc": _utc_now_iso(),
    }

    # Optional append-only disposition log next to report
    log_bases: list[Path] = []
    if path:
        log_bases.append(Path(path).expanduser().resolve().parent)
    for base in (prior_art_run_dir, review_run_dir):
        if base:
            log_bases.append(Path(base).expanduser().resolve())

    if persist or path or prior_art_run_dir or review_run_dir:
        persisted = persist_conflict_review_report(
            updated,
            path=path,
            prior_art_run_dir=prior_art_run_dir,
            review_run_dir=review_run_dir,
        )
        out["paths"] = persisted.get("paths")
        out["primary_path"] = persisted.get("primary_path")
        for base in log_bases:
            try:
                log_path = base / CONFLICT_DISPOSITION_LOG_FILENAME
                line = (
                    json.dumps(
                        {
                            "report_id": updated.report_id,
                            "content_digest": updated.content_digest,
                            "disposition": out["disposition"],
                            "auto_file_blocked": True,
                            "logged_at_utc": _utc_now_iso(),
                        },
                        sort_keys=True,
                        default=str,
                    )
                    + "\n"
                )
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass

    return out


# ---------------------------------------------------------------------------
# IDS binding (PAAR-041) — consider_ids only, never auto-file
# ---------------------------------------------------------------------------


def _cells_for_consider_ids(
    report: ConflictRiskReport,
) -> list[tuple[Any, HumanDisposition]]:
    """Return (cell, disposition) pairs covered by consider_ids dispositions."""
    consider = [
        d
        for d in report.dispositions
        if d.disposition_code is DispositionCode.CONSIDER_IDS
    ]
    if not consider:
        return []
    cell_by_id = {c.cell_id: c for c in report.cells}
    pairs: list[tuple[Any, HumanDisposition]] = []
    seen_hits: set[str] = set()
    for disp in consider:
        if not str(disp.acknowledger_id or "").strip():
            # Fail closed: disposition without acknowledger must not bind
            raise ConflictReviewReportError(
                "consider_ids disposition missing acknowledger; refuse IDS bind",
                code="acknowledger_name_required",
            )
        cell_ids = disp.cell_ids or tuple(cell_by_id.keys())
        for cid in cell_ids:
            cell = cell_by_id.get(cid)
            if cell is None:
                continue
            hit = str(cell.hit_id or "").strip()
            if not hit or hit in seen_hits:
                continue
            seen_hits.add(hit)
            pairs.append((cell, disp))
    return pairs


def bind_consider_ids_to_ids_queue(
    report: ConflictRiskReport | Mapping[str, Any],
    *,
    queue_path: str | Path | None = None,
    run_dir: str | Path | None = None,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
    subject_id: str | None = None,
    application_number: str | None = None,
    create_queue_if_missing: bool = True,
    persist_report: bool = False,
    state_root: str | Path | None = None,
) -> dict[str, Any]:
    """Enqueue hits from ``consider_ids`` dispositions onto the human IDS queue.

    * Never promotes to IDS-ready.
    * Never files an IDS.
    * Always returns ``auto_file_blocked: true``.
    * Only dispositions with code ``consider_ids`` and a non-empty
      acknowledger are bound.
    """
    from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
        IdsCandidateState,
        IdsReferenceCandidate,
        IdsReviewAction,
        IdsReviewActionKind,
        build_ids_review_queue,
        content_digest,
    )
    from ipfs_datasets_py.processors.domains.uspto.ids_review_operator import (
        IDS_OPERATOR_DISCLAIMER,
        load_ids_queue,
        save_ids_queue,
    )

    report_obj = recompute_report_digest(_as_report(report))
    pairs = _cells_for_consider_ids(report_obj)

    app = _normalize_app(application_number or report_obj.application_number)
    subj = (
        str(subject_id or "").strip()
        or (f"app-{app}" if app else f"app-unknown-{report_obj.report_id[:12]}")
    )
    # IdsReferenceCandidate subject_id must match identifier regex
    subj = _safe_document_id(subj)

    # Resolve queue path preference: explicit → run_dir → prior_art → review
    qpath: Path | None = None
    if queue_path:
        qpath = Path(queue_path).expanduser().resolve()
    else:
        for base in (run_dir, prior_art_run_dir, review_run_dir):
            if not base:
                continue
            candidate = Path(base).expanduser().resolve() / "ids_review_queue.json"
            if candidate.is_file() or create_queue_if_missing:
                qpath = candidate
                break

    if qpath is None:
        raise ConflictReviewReportError(
            "pass queue_path, run_dir, prior_art_run_dir, or review_run_dir "
            "to bind consider_ids into an IDS queue",
            code="missing_queue_target",
        )

    if qpath.is_file():
        queue = load_ids_queue(qpath)
    elif create_queue_if_missing:
        queue = build_ids_review_queue(
            subject_id=subj,
            queue_id=f"ids-queue:crr:{content_digest(report_obj.report_id)[:12]}",
            metadata={
                "source": "conflict_review_report",
                "conflict_report_id": report_obj.report_id,
                "conflict_content_digest": report_obj.content_digest,
                "application_number": app,
                "auto_file_blocked": "true",
            },
        )
    else:
        raise ConflictReviewReportError(
            f"IDS queue not found: {qpath}", code="queue_missing"
        )

    existing_docs = {c.document_id for c in queue.candidates}
    existing_ids = {c.candidate_id for c in queue.candidates}
    added: list[dict[str, Any]] = []
    now = _utc_now_iso()
    new_candidates = list(queue.candidates)

    for cell, disp in pairs:
        doc_id = _safe_document_id(cell.hit_id)
        if doc_id in existing_docs:
            # Already on queue — record provenance only via metadata merge skip
            continue
        cand_id = f"ids-cand:crr:{content_digest([doc_id, report_obj.report_id])[:14]}"
        if cand_id in existing_ids:
            cand_id = f"ids-cand:crr:{content_digest([doc_id, cell.cell_id])[:14]}"
        # Ensure acted_at_utc matches ISO pattern expected by IdsReviewAction
        acted = disp.acknowledged_at_utc or now
        if acted.endswith("+00:00"):
            acted = acted[:-6] + "Z"
        if not re.match(
            r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z",
            acted,
        ):
            acted = now
        action = IdsReviewAction(
            action_id=f"act:{cand_id}:v1",
            candidate_id=cand_id,
            version=1,
            action_kind=IdsReviewActionKind.ENQUEUE,
            reviewer_id=_safe_reviewer_id(disp.acknowledger_id),
            acted_at_utc=acted,
            is_natural_person=True,
            notes=(
                f"enqueued from conflict report consider_ids "
                f"(cell={cell.cell_id}; report={report_obj.report_id})"
            )[:4096],
        )
        citation = (cell.hit_quote or cell.hit_id or doc_id)[:200]
        candidate = IdsReferenceCandidate(
            candidate_id=cand_id,
            document_id=doc_id,
            subject_id=str(queue.subject_id or subj),
            state=IdsCandidateState.CANDIDATE,
            chart_cell_ids=(cell.cell_id,) if cell.cell_id else (),
            citation_text=citation,
            identifiers={
                "document_id": doc_id,
                "hit_id": str(cell.hit_id),
                "limitation_id": str(cell.limitation_id or ""),
            },
            review_history=(action,),
            is_ids_ready=False,
            auto_file_blocked=True,
            metadata={
                "source": "conflict_review_consider_ids",
                "conflict_report_id": report_obj.report_id,
                "conflict_content_digest": report_obj.content_digest,
                "disposition_code": DispositionCode.CONSIDER_IDS.value,
                "acknowledger_name": str(disp.acknowledger_id),
                "risk": cell.risk.value if hasattr(cell.risk, "value") else str(cell.risk),
                "auto_file_blocked": "true",
            },
        )
        new_candidates.append(candidate)
        existing_docs.add(doc_id)
        existing_ids.add(cand_id)
        added.append(
            {
                "candidate_id": cand_id,
                "document_id": doc_id,
                "cell_id": cell.cell_id,
                "hit_id": cell.hit_id,
                "is_ids_ready": False,
                "auto_file_blocked": True,
            }
        )

    from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
        IdsReviewQueue,
        IDS_REVIEW_QUEUE_DISCLAIMER,
        IDS_REVIEW_QUEUE_SCHEMA_VERSION,
        OUTPUT_KIND_IDS_QUEUE,
    )

    updated_queue = IdsReviewQueue(
        schema_version=getattr(queue, "schema_version", IDS_REVIEW_QUEUE_SCHEMA_VERSION),
        queue_id=queue.queue_id,
        subject_id=queue.subject_id,
        candidates=tuple(new_candidates),
        chart_id=getattr(queue, "chart_id", None),
        coverage_acknowledgement=getattr(queue, "coverage_acknowledgement", None),
        auto_file_blocked=True,
        claims_exhaustive_search=False,
        disclaimer=getattr(queue, "disclaimer", None) or IDS_REVIEW_QUEUE_DISCLAIMER,
        metadata={
            **dict(getattr(queue, "metadata", {}) or {}),
            "conflict_report_id": report_obj.report_id,
            "conflict_content_digest": report_obj.content_digest,
            "last_consider_ids_bind_utc": now,
        },
    )
    # Hard invariant on queue object
    if updated_queue.auto_file_blocked is not True:
        raise ConflictReviewReportError(
            "auto_file_blocked must be true on IDS queue",
            code="auto_file_invariant",
        )
    if any(bool(c.get("is_ids_ready")) for c in added):
        raise ConflictReviewReportError(
            "consider_ids bind must not mark candidates IDS-ready",
            code="ids_ready_forbidden",
        )
    if any(c.is_ids_ready for c in updated_queue.candidates if c.candidate_id in {a["candidate_id"] for a in added}):
        raise ConflictReviewReportError(
            "consider_ids bind must not mark candidates IDS-ready",
            code="ids_ready_forbidden",
        )

    saved = save_ids_queue(updated_queue, qpath)

    # Mirror under state ids_queues when state_root provided
    mirror_path: str | None = None
    if state_root is not None and app:
        try:
            mirror = (
                Path(state_root).expanduser().resolve()
                / "ids_queues"
                / app
                / f"{updated_queue.queue_id.replace(':', '_')}.json"
            )
            save_ids_queue(updated_queue, mirror)
            mirror_path = str(mirror)
        except Exception:
            pass

    # Also write under prior_art / review run dirs if distinct from qpath
    extra_paths: list[str] = [str(saved)]
    for base in (prior_art_run_dir, review_run_dir, run_dir):
        if not base:
            continue
        alt = Path(base).expanduser().resolve() / "ids_review_queue.json"
        if alt.resolve() != qpath.resolve():
            try:
                extra_paths.append(str(save_ids_queue(updated_queue, alt)))
            except Exception:
                pass

    if persist_report:
        persist_conflict_review_report(
            report_obj,
            prior_art_run_dir=prior_art_run_dir,
            review_run_dir=review_run_dir,
        )

    return {
        "schema": "paar.conflict_consider_ids_bind@1",
        "ok": True,
        "report_id": report_obj.report_id,
        "content_digest": report_obj.content_digest,
        "queue_id": updated_queue.queue_id,
        "queue_path": str(saved),
        "paths": extra_paths,
        "mirror_path": mirror_path,
        "subject_id": updated_queue.subject_id,
        "application_number": app,
        "added_count": len(added),
        "added_candidates": added,
        "candidate_count": len(updated_queue.candidates),
        "ids_ready_count": sum(1 for c in updated_queue.candidates if c.is_ids_ready),
        "auto_file_blocked": True,
        "patent_center_filing": False,
        "promoted": False,
        "disclaimer": (
            "consider_ids dispositions enqueued as human IDS candidates only. "
            + IDS_OPERATOR_DISCLAIMER
        ),
        "generated_at_utc": _utc_now_iso(),
    }


def record_disposition_and_bind_ids(
    report: ConflictRiskReport | Mapping[str, Any],
    *,
    disposition_code: str | DispositionCode,
    acknowledger_name: str,
    cell_ids: Sequence[str] | None = None,
    notes: str = "",
    queue_path: str | Path | None = None,
    run_dir: str | Path | None = None,
    prior_art_run_dir: str | Path | None = None,
    review_run_dir: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Record disposition; if ``consider_ids``, also bind to IDS queue.

    Convenience for operator flows. Non-``consider_ids`` codes skip queue bind.
    """
    recorded = record_human_disposition(
        report,
        disposition_code=disposition_code,
        acknowledger_name=acknowledger_name,
        cell_ids=cell_ids,
        notes=notes,
        persist=True,
        path=None,
        prior_art_run_dir=prior_art_run_dir,
        review_run_dir=review_run_dir or run_dir,
    )
    code = _coerce_disposition_code(disposition_code)
    out: dict[str, Any] = {
        "ok": True,
        "disposition_result": recorded,
        "ids_bind": None,
        "auto_file_blocked": True,
    }
    if code is DispositionCode.CONSIDER_IDS:
        bind = bind_consider_ids_to_ids_queue(
            recorded["report"],
            queue_path=queue_path,
            run_dir=run_dir,
            prior_art_run_dir=prior_art_run_dir,
            review_run_dir=review_run_dir,
            **{k: v for k, v in kwargs.items() if k in {
                "subject_id",
                "application_number",
                "create_queue_if_missing",
                "state_root",
            }},
        )
        out["ids_bind"] = bind
    return out


__all__ = [
    "CONFLICT_DISPOSITION_LOG_FILENAME",
    "CONFLICT_REVIEW_CODE_VERSION",
    "CONFLICT_REVIEW_INTERFACE",
    "CONFLICT_REVIEW_REPORT_SCHEMA",
    "CONFLICT_RISK_REPORT_FILENAME",
    "DISPOSITION_CODES",
    "REVIEW_ONLY_CONFLICT_REVIEW_DISCLAIMER",
    "ConflictReviewReportError",
    "bind_consider_ids_to_ids_queue",
    "build_and_persist_conflict_review_report",
    "build_conflict_review_report",
    "load_conflict_review_report",
    "persist_conflict_review_report",
    "recompute_report_digest",
    "record_disposition_and_bind_ids",
    "record_human_disposition",
    "report_to_payload",
    "resolve_conflict_report_path",
]
