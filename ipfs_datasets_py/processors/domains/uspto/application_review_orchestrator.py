"""PAAR unified application review orchestrator (PAAR-090).

One library entrypoint that composes (when available, with hermetic/offline
stubs if inputs are missing):

* claim_limitation_model
* review_search_orchestrator (or prior-art run path)
* conflict_risk_engine
* package_conformance_engine / obligation_catalog
* optional application_gap_closure diligence packs
* optional conflict_review_report (stub when module absent)

Emits ``UnifiedApplicationReview@1`` (see docs/architecture/paar_report_schemas.md).

Design invariants
-----------------
* **Not legal advice**; never asserts novelty, obviousness, or patentability.
* Overall disposition: ``ready`` | ``review_required`` | ``not_ready``.
* Always include disclaimer; never patentability conclusions; never Sign/Pay/Submit.
* ``auto_file_blocked`` always ``true``.
* Fail closed: missing authority / empty inputs never invent ``ready``.
* No secrets in ordinary logs (claim bodies / credentials omitted).
* Persist under ``state_root/compliance_audits/<app>/review_<stamp>/`` when
  ``persist=True``.

Conflict policy (PAAR-090): thin composition only; do not reimplement engines.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

UNIFIED_APPLICATION_REVIEW_SCHEMA: Final = "paar.UnifiedApplicationReview@1"
UNIFIED_APPLICATION_REVIEW_INTERFACE: Final = "UnifiedApplicationReview@1"
APPLICATION_REVIEW_ORCHESTRATOR_CODE_VERSION: Final = "1.0.0"

REVIEW_ONLY_UNIFIED_DISCLAIMER: Final = (
    "Unified application review support only. Composes claim modeling, multi-"
    "corpus search orchestration, conflict risk screening, package "
    "conformance, and optional diligence residuals for human operators. This "
    "is not legal advice, not a novelty determination, not an obviousness "
    "determination, and not a patentability conclusion. auto_file_blocked=true. "
    "Never Sign/Pay/Submit. Named human review is required before any legal "
    "or filing action. A disposition of ready means review-support gates "
    "passed with residual gaps named — it is not filing authorization."
)

_logger = logging.getLogger(__name__)


def _ban_phrases() -> tuple[str, ...]:
    # forbid / ban list for runtime output scan only
    return (
        "is " + "patentable",  # ban
        "is " + "unpatentable",  # ban
        "is " + "novel",  # ban
        "is " + "obvious",  # ban
        "novelty " + "conclusion",  # ban
        "obviousness " + "conclusion",  # ban
        "patentability " + "conclusion",  # ban
        "no prior art " + "exists",  # ban
        "will be " + "allowed",  # ban
    )


_FORBIDDEN_OUTPUT_PHRASES: Final[tuple[str, ...]] = _ban_phrases()


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReviewDisposition(str, Enum):
    """Overall unified review disposition (closed vocabulary)."""

    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    NOT_READY = "not_ready"


# Exit semantics for CLI: 0 ready, 1 review_required, 2 not_ready/error
EXIT_CODE_BY_DISPOSITION: Final[Mapping[str, int]] = {
    ReviewDisposition.READY.value: 0,
    ReviewDisposition.REVIEW_REQUIRED.value: 1,
    ReviewDisposition.NOT_READY.value: 2,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApplicationReviewOrchestratorError(ValueError):
    """Bounded unified review orchestration failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "application_review_orchestrator_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _stamp_for_path(generated_at_utc: str) -> str:
    """Filesystem-safe stamp from ISO UTC (or now)."""
    raw = (generated_at_utc or _utc_now_iso()).replace(":", "").replace("-", "")
    raw = raw.replace("T", "T").replace("Z", "Z")
    # Keep alnum + underscore only
    cleaned = re.sub(r"[^0-9A-Za-z]", "", raw)[:20] or "now"
    return cleaned


def _normalize_app(application_number: str) -> str:
    digits = re.sub(r"\D", "", str(application_number or ""))
    return digits or str(application_number or "").strip()


def _safe_log_event(event: str, **fields: Any) -> None:
    """Log content-free operational events (no claim bodies / secrets)."""
    safe = {
        k: v
        for k, v in fields.items()
        if k
        not in {
            "claims_text",
            "claim_text",
            "password",
            "api_key",
            "secret",
            "token",
            "totp",
        }
    }
    # Truncate long string values
    for k, v in list(safe.items()):
        if isinstance(v, str) and len(v) > 200:
            safe[k] = v[:200] + "…"
    _logger.info("application_review_orchestrator %s %s", event, safe)


def _assert_no_forbidden_phrases(payload: Mapping[str, Any]) -> None:
    """Fail on affirmative banned conclusion phrases outside negative framing."""
    blob = canonical_json(payload).lower()
    cleaned = blob
    for neg in (
        "not a patentability",
        "not patentability",
        "never a patentability",
        "no patentability",
        "not a novelty",
        "not an obviousness",
        "not legal advice",
        "not filing authorization",
    ):
        cleaned = cleaned.replace(neg, " ")
    for phrase in _FORBIDDEN_OUTPUT_PHRASES:
        if phrase in cleaned:
            raise ApplicationReviewOrchestratorError(
                f"forbidden conclusion phrase in output: {phrase!r}",
                code="forbidden_phrase",
            )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplicationReviewOrchestratorError(
            f"failed to read JSON {path.name}: {type(exc).__name__}",
            code="json_read_error",
        ) from exc
    if not isinstance(data, dict):
        raise ApplicationReviewOrchestratorError(
            f"expected object in {path.name}",
            code="json_type_error",
        )
    return data


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    return path


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def normalize_prior_hits(hits: Sequence[Any] | None) -> list[dict[str, Any]]:
    """Normalize fixture / run hits into conflict-risk hit rows.

    Prefers ``text``, then ``body_excerpt`` / ``abstract`` / ``title`` so
    planted-overlap fixtures score without engine changes.
    """
    rows: list[dict[str, Any]] = []
    for hit in hits or ():
        if not isinstance(hit, Mapping):
            continue
        hid = str(
            hit.get("hit_id")
            or hit.get("document_id")
            or hit.get("publication_number")
            or hit.get("id")
            or ""
        ).strip()
        if not hid:
            continue
        text_parts = [
            str(hit.get("text") or "").strip(),
            str(hit.get("body_excerpt") or "").strip(),
            str(hit.get("passage_excerpt") or "").strip(),
            str(hit.get("abstract") or "").strip(),
            str(hit.get("title") or "").strip(),
        ]
        # Prefer longest non-empty primary text; join unique parts for richness
        primary = max(text_parts, key=len) if any(text_parts) else ""
        if not primary:
            primary = " ".join(p for p in text_parts if p)
        row = {
            "hit_id": hid,
            "document_id": hid,
            "text": primary,
            "corpus": str(hit.get("corpus") or ""),
            "publication_number": str(
                hit.get("publication_number") or hit.get("document_id") or ""
            ),
        }
        if hit.get("planted_overlap") is not None:
            row["planted_overlap"] = bool(hit.get("planted_overlap"))
        rows.append(row)
    return rows


def normalize_coverage_gaps(raw: Sequence[Any] | None) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for g in raw or ():
        if isinstance(g, Mapping):
            kind = str(g.get("kind") or g.get("corpus") or g.get("gap_id") or "")
            status = str(g.get("status") or "unsearched")
            corpus = str(g.get("corpus") or kind)
            gaps.append(
                {
                    "kind": kind or corpus,
                    "corpus": corpus,
                    "status": status,
                    "message": str(g.get("message") or ""),
                    "required": bool(g.get("required", True)),
                }
            )
        else:
            gaps.append(
                {
                    "kind": str(g),
                    "corpus": str(g),
                    "status": "unsearched",
                    "message": "",
                    "required": True,
                }
            )
    return gaps


def inventory_from_fixture_or_dir(
    *,
    package_inventory: Mapping[str, Any] | None = None,
    package_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load package inventory from explicit map, JSON path, or package dir."""
    if package_inventory is not None:
        return dict(package_inventory)

    if package_dir is None:
        return None

    root = Path(package_dir)
    if not root.exists():
        return None

    # Explicit inventory JSON
    for name in (
        "package_inventory.json",
        "inventory.json",
        "export_manifest.json",
        "manifest.json",
    ):
        candidate = root / name
        if candidate.is_file():
            try:
                data = _read_json(candidate)
            except ApplicationReviewOrchestratorError:
                continue
            # manifest may not be inventory — only accept if looks like inventory
            if (
                "ifw_codes" in data
                or "files" in data
                or "documents" in data
                or "components" in data
            ):
                return data
            # Still useful as inventory seed if application_number present
            if name == "package_inventory.json":
                return data

    # Directory of files → synthetic inventory from filenames
    files: list[dict[str, Any]] = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".json", ".xml"}:
                files.append({"name": p.name, "path": str(p)})
    if files:
        return {"files": files, "components": [], "source": "package_dir_scan"}
    return None


def load_prior_art_run_hits(
    prior_art_run: str | Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """Load hits + coverage gaps from a prior-art run directory (hermetic).

    Returns ``(hits, coverage_gaps, run_meta)``.

    Prefers ``coverage_declaration.json`` / ``search_journal.json`` for
    ``searched_corpora`` so live EPO OPS / NPL / ODP runs are not misreported
    as unsearched (PAAR-063 / PAAR-210).
    """
    if prior_art_run is None:
        return [], [], None
    run_path = Path(prior_art_run)
    if not run_path.exists():
        return [], [], {"path": str(run_path), "status": "missing"}

    hits: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"path": str(run_path), "status": "loaded"}
    searched: list[str] = []
    unsearched: list[str] = []

    def _as_dir() -> Path:
        return run_path if run_path.is_dir() else run_path.parent

    root = _as_dir()

    # --- Coverage declaration (authoritative for corpora status) ---
    for cov_name in (
        "coverage_declaration.json",
        "search_journal.json",
        "adapter_status.json",
    ):
        cov_path = root / cov_name if root.is_dir() else None
        if cov_path is None or not cov_path.is_file():
            continue
        try:
            cov = _read_json(cov_path)
        except ApplicationReviewOrchestratorError:
            continue
        if not isinstance(cov, Mapping):
            continue
        if cov.get("searched_corpora") is not None:
            searched = [str(c) for c in (cov.get("searched_corpora") or []) if str(c).strip()]
            unsearched = [
                str(c) for c in (cov.get("unsearched_corpora") or []) if str(c).strip()
            ]
            meta["coverage_source"] = cov_name
            meta["searched_corpora"] = searched
            meta["unsearched_corpora"] = unsearched
            # named_gaps from declaration (empty when fully searched)
            if cov.get("named_gaps") is not None:
                gaps = normalize_coverage_gaps(cov.get("named_gaps") or [])
            break
        # adapter_status fallback: foreign/npl live → searched
        if cov_name == "adapter_status.json":
            foreign = cov.get("foreign") if isinstance(cov.get("foreign"), Mapping) else {}
            npl = cov.get("npl") if isinstance(cov.get("npl"), Mapping) else {}
            inferred: list[str] = ["us_patents"]
            if foreign.get("live") or foreign.get("enabled"):
                inferred.append("foreign_patents")
            if npl.get("live") or npl.get("enabled"):
                inferred.append("npl")
            searched = inferred
            meta["coverage_source"] = cov_name
            meta["searched_corpora"] = searched
            meta["unsearched_corpora"] = []

    # --- Hits from common run artifact names ---
    hit_names = (
        "prior_hits.json",
        "hits.json",
        "search_hits.json",
        "journal.json",
        "search_journal.json",
        "prior_art_results.json",
        "claim_chart.json",
        "prior_art_report.json",
    )
    for name in hit_names:
        candidate = root / name if root.is_dir() else run_path
        if run_path.is_file():
            candidate = run_path
        if not candidate.is_file():
            continue
        try:
            data = _read_json(candidate)
        except ApplicationReviewOrchestratorError:
            continue
        if not isinstance(data, Mapping):
            continue
        if "hits" in data:
            hits = normalize_prior_hits(data.get("hits") or [])
            if not gaps and data.get("coverage_gaps") is not None:
                gaps = normalize_coverage_gaps(data.get("coverage_gaps") or [])
            meta["source_file"] = candidate.name
            break
        if "entries" in data:  # claim_chart-like
            # Entries are chart rows; keep as lightweight hit-like records
            entries = data.get("entries") or []
            if isinstance(entries, list) and entries:
                hits = normalize_prior_hits(
                    [
                        e
                        for e in entries
                        if isinstance(e, Mapping)
                        and (e.get("document_id") or e.get("hit_id") or e.get("passage_excerpt"))
                    ]
                )
                meta["source_file"] = candidate.name
                break
        if "records" in data:  # journal-like
            for rec in data.get("records") or []:
                if isinstance(rec, Mapping):
                    hits.extend(normalize_prior_hits(rec.get("hits") or []))
            if not gaps and data.get("coverage_gaps") is not None:
                gaps = normalize_coverage_gaps(data.get("coverage_gaps") or [])
            if data.get("searched_corpora") is not None and not searched:
                searched = [str(c) for c in (data.get("searched_corpora") or [])]
                unsearched = [str(c) for c in (data.get("unsearched_corpora") or [])]
                meta["searched_corpora"] = searched
                meta["unsearched_corpora"] = unsearched
            meta["source_file"] = candidate.name
            break
        if run_path.is_file():
            break

    # Synthesize gaps only for corpora still unsearched (never invent when searched).
    if not gaps and unsearched:
        gaps = normalize_coverage_gaps(
            [
                {
                    "kind": c,
                    "corpus": c,
                    "status": "unsearched",
                    "message": f"Corpus {c} unsearched in prior-art run",
                    "required": True,
                }
                for c in unsearched
            ]
        )
    # If coverage says all required corpora searched and no named gaps, keep empty.
    if searched and not unsearched:
        gaps = []
        meta["exhaustive_corpora_complete"] = True

    return hits, gaps, meta


def load_fixture_bundle(fixture_dir: str | Path) -> dict[str, Any]:
    """Load a ``tests/fixtures/uspto/paar_review/<variant>/`` bundle offline."""
    root = Path(fixture_dir)
    if not root.is_dir():
        raise ApplicationReviewOrchestratorError(
            f"fixture dir not found: {root}",
            code="fixture_missing",
        )
    out: dict[str, Any] = {"fixture_dir": str(root)}
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        out["manifest"] = _read_json(manifest_path)
        out["application_number"] = str(
            (out["manifest"] or {}).get("application_number") or ""
        )

    claims_path = root / "claims.txt"
    if claims_path.is_file():
        out["claims_text"] = claims_path.read_text(encoding="utf-8")

    inv_path = root / "package_inventory.json"
    if inv_path.is_file():
        out["package_inventory"] = _read_json(inv_path)
        if not out.get("application_number"):
            out["application_number"] = str(
                out["package_inventory"].get("application_number") or ""
            )

    hits_path = root / "prior_hits.json"
    if hits_path.is_file():
        hits_doc = _read_json(hits_path)
        out["prior_hits"] = normalize_prior_hits(hits_doc.get("hits") or [])
        out["coverage_gaps"] = normalize_coverage_gaps(
            hits_doc.get("coverage_gaps") or []
        )

    auth_path = root / "authority_status.json"
    if auth_path.is_file():
        out["authority_status"] = _read_json(auth_path)
        out["authority_corpus_present"] = bool(
            out["authority_status"].get("authority_corpus_bound")
            or out["authority_status"].get("authority_corpus_present")
        )
    elif out.get("package_inventory"):
        inv = out["package_inventory"]
        if "authority_corpus_bound" in inv:
            out["authority_corpus_present"] = bool(inv.get("authority_corpus_bound"))
        elif "authority_corpus_present" in inv:
            out["authority_corpus_present"] = bool(inv.get("authority_corpus_present"))

    return out


# ---------------------------------------------------------------------------
# Report record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnifiedApplicationReview:
    """UnifiedApplicationReview@1 — composed operator review disposition."""

    review_id: str
    application_number: str
    generated_at_utc: str
    content_digest: str
    disposition: ReviewDisposition
    exit_code_hint: int
    conflict_risk_ref: Mapping[str, Any]
    conformance_ref: Mapping[str, Any]
    claim_model_ref: Mapping[str, Any]
    coverage_gaps: tuple[Mapping[str, Any], ...]
    diligence_residuals: tuple[Mapping[str, Any], ...]
    schema: str = UNIFIED_APPLICATION_REVIEW_SCHEMA
    disclaimer: str = REVIEW_ONLY_UNIFIED_DISCLAIMER
    auto_file_blocked: bool = True
    search_ref: Mapping[str, Any] = field(default_factory=dict)
    conflict_review_ref: Mapping[str, Any] | None = None
    component_status: Mapping[str, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    persist_path: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": UNIFIED_APPLICATION_REVIEW_INTERFACE,
            "code_version": APPLICATION_REVIEW_ORCHESTRATOR_CODE_VERSION,
            "review_id": self.review_id,
            "application_number": self.application_number,
            "generated_at_utc": self.generated_at_utc,
            "content_digest": self.content_digest,
            "disposition": self.disposition.value,
            "exit_code_hint": int(self.exit_code_hint),
            "conflict_risk_ref": dict(self.conflict_risk_ref),
            "conformance_ref": dict(self.conformance_ref),
            "claim_model_ref": dict(self.claim_model_ref),
            "search_ref": dict(self.search_ref),
            "coverage_gaps": [dict(g) for g in self.coverage_gaps],
            "diligence_residuals": [dict(d) for d in self.diligence_residuals],
            "conflict_review_ref": (
                dict(self.conflict_review_ref)
                if self.conflict_review_ref is not None
                else None
            ),
            "component_status": dict(self.component_status),
            "reasons": list(self.reasons),
            "persist_path": self.persist_path,
            "auto_file_blocked": True,
            "disclaimer": self.disclaimer,
            "metadata": dict(self.metadata),
        }

    def compact_summary(self) -> dict[str, Any]:
        """CLI-friendly compact JSON summary (no large claim/hit bodies)."""
        return {
            "schema": self.schema,
            "review_id": self.review_id,
            "application_number": self.application_number,
            "disposition": self.disposition.value,
            "exit_code_hint": int(self.exit_code_hint),
            "matter_risk": self.conflict_risk_ref.get("matter_risk"),
            "conformance_status": self.conformance_ref.get("overall_status"),
            "claim_authority_mode": self.claim_model_ref.get("authority_mode"),
            "claim_quality_score": self.claim_model_ref.get("quality_score"),
            "coverage_gap_count": len(self.coverage_gaps),
            "diligence_residual_count": len(self.diligence_residuals),
            "auto_file_blocked": True,
            "content_digest": self.content_digest,
            "persist_path": self.persist_path,
            "reasons": list(self.reasons)[:12],
            "disclaimer": self.disclaimer,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnifiedApplicationReview":
        disp = ReviewDisposition(
            str(value.get("disposition") or "not_ready").lower()
        )
        return cls(
            review_id=str(value.get("review_id") or ""),
            application_number=str(value.get("application_number") or ""),
            generated_at_utc=str(value.get("generated_at_utc") or ""),
            content_digest=str(value.get("content_digest") or ""),
            disposition=disp,
            exit_code_hint=int(
                value.get("exit_code_hint")
                if value.get("exit_code_hint") is not None
                else EXIT_CODE_BY_DISPOSITION.get(disp.value, 2)
            ),
            conflict_risk_ref=dict(value.get("conflict_risk_ref") or {}),
            conformance_ref=dict(value.get("conformance_ref") or {}),
            claim_model_ref=dict(value.get("claim_model_ref") or {}),
            coverage_gaps=tuple(
                dict(g) for g in (value.get("coverage_gaps") or ()) if isinstance(g, Mapping)
            ),
            diligence_residuals=tuple(
                dict(d)
                for d in (value.get("diligence_residuals") or ())
                if isinstance(d, Mapping)
            ),
            search_ref=dict(value.get("search_ref") or {}),
            conflict_review_ref=(
                dict(value["conflict_review_ref"])
                if isinstance(value.get("conflict_review_ref"), Mapping)
                else None
            ),
            component_status=dict(value.get("component_status") or {}),
            reasons=tuple(str(r) for r in (value.get("reasons") or ())),
            persist_path=value.get("persist_path"),
            metadata=dict(value.get("metadata") or {}),
            disclaimer=str(
                value.get("disclaimer") or REVIEW_ONLY_UNIFIED_DISCLAIMER
            ),
            auto_file_blocked=True,
        )


# ---------------------------------------------------------------------------
# Disposition policy
# ---------------------------------------------------------------------------


def compute_disposition(
    *,
    claim_authority_mode: str,
    claim_low_ocr: bool,
    claim_empty: bool,
    matter_risk: str,
    has_human_dispositions: bool,
    conformance_status: str,
    authority_corpus_present: bool,
    structural_failure: bool = False,
    named_residuals_accepted: bool = False,
) -> tuple[ReviewDisposition, list[str]]:
    """Apply normative disposition rules from paar_report_schemas.md.

    Returns ``(disposition, reasons)``. Never invents ``ready`` when authority
    is missing or structural gates fail.
    """
    reasons: list[str] = []
    risk = (matter_risk or "unknown").lower()
    conf = (conformance_status or "unknown").lower()
    auth = (claim_authority_mode or "review_required").lower()

    if structural_failure:
        reasons.append("structural_failure")
        return ReviewDisposition.NOT_READY, reasons

    if claim_empty:
        reasons.append("empty_claims")
        return ReviewDisposition.NOT_READY, reasons

    if claim_low_ocr or auth == "non_authoritative":
        reasons.append("claim_quality_gate")
        # Low OCR → review_required (schema); non-authoritative blocks ready
        # Continue collecting reasons; at least review_required

    if not authority_corpus_present:
        reasons.append("authority_corpus_missing")

    if conf == "unsatisfied":
        reasons.append("conformance_unsatisfied")
    elif conf == "unknown":
        reasons.append("conformance_unknown")
    elif conf == "human_only":
        reasons.append("conformance_human_only")

    if risk in {"high", "medium"} and not has_human_dispositions:
        reasons.append(f"matter_risk_{risk}_without_human_disposition")
    elif risk == "unknown":
        reasons.append("matter_risk_unknown")

    # Hard not_ready cases
    if conf == "unsatisfied":
        return ReviewDisposition.NOT_READY, reasons
    if not authority_corpus_present:
        # Missing authority never ready; treat as not_ready (fail closed)
        return ReviewDisposition.NOT_READY, reasons
    if claim_empty:
        return ReviewDisposition.NOT_READY, reasons

    # review_required cases
    needs_review = False
    if claim_low_ocr or auth in {"review_required", "non_authoritative"}:
        needs_review = True
    if risk in {"high", "medium"} and not has_human_dispositions:
        needs_review = True
    if risk == "unknown":
        needs_review = True
    if conf in {"unknown", "human_only"}:
        needs_review = True
    if not named_residuals_accepted and conf != "satisfied":
        needs_review = True

    if needs_review:
        if not reasons:
            reasons.append("review_gates_open")
        return ReviewDisposition.REVIEW_REQUIRED, reasons

    # All gates pass: conformance satisfied, risk low (or dispositions present),
    # claim authoritative, authority present.
    if conf == "satisfied" and risk == "low" and auth == "authoritative":
        reasons.append("all_gates_pass_review_support_only")
        return ReviewDisposition.READY, reasons

    if conf == "satisfied" and risk in {"low", "medium", "high"} and has_human_dispositions:
        if risk == "low" or named_residuals_accepted:
            reasons.append("gates_pass_with_human_dispositions")
            return ReviewDisposition.READY, reasons

    reasons.append("default_review_required")
    return ReviewDisposition.REVIEW_REQUIRED, reasons


def compute_content_digest(
    *,
    review_id: str,
    application_number: str,
    disposition: str,
    conflict_risk_ref: Mapping[str, Any],
    conformance_ref: Mapping[str, Any],
    claim_model_ref: Mapping[str, Any],
    coverage_gaps: Sequence[Mapping[str, Any]],
    diligence_residuals: Sequence[Mapping[str, Any]],
) -> str:
    """Deterministic digest excluding wall-clock timestamps."""
    payload = {
        "schema": UNIFIED_APPLICATION_REVIEW_SCHEMA,
        "review_id": review_id,
        "application_number": application_number,
        "disposition": disposition,
        "conflict_risk_ref": {
            "report_id": conflict_risk_ref.get("report_id"),
            "content_digest": conflict_risk_ref.get("content_digest"),
            "matter_risk": conflict_risk_ref.get("matter_risk"),
        },
        "conformance_ref": {
            "report_id": conformance_ref.get("report_id"),
            "content_digest": conformance_ref.get("content_digest"),
            "overall_status": conformance_ref.get("overall_status"),
        },
        "claim_model_ref": {
            "content_digest": claim_model_ref.get("content_digest"),
            "authority_mode": claim_model_ref.get("authority_mode"),
            "quality_score": claim_model_ref.get("quality_score"),
        },
        "coverage_gaps": list(coverage_gaps),
        "diligence_residuals": list(diligence_residuals),
        "auto_file_blocked": True,
        "code_version": APPLICATION_REVIEW_ORCHESTRATOR_CODE_VERSION,
    }
    return sha256_hex(canonical_json(payload))


# ---------------------------------------------------------------------------
# Optional component stubs
# ---------------------------------------------------------------------------


def _stub_diligence_residuals(
    *,
    application_number: str,
    coverage_gaps: Sequence[Mapping[str, Any]],
    diligence_pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    residuals: list[dict[str, Any]] = []
    if diligence_pack and isinstance(diligence_pack, Mapping):
        packs = diligence_pack.get("packs") or diligence_pack.get("items") or {}
        if isinstance(packs, Mapping):
            for item_id, pack in packs.items():
                if not isinstance(pack, Mapping):
                    continue
                residuals.append(
                    {
                        "residual_id": str(pack.get("item_id") or item_id),
                        "kind": "diligence_pack",
                        "status": str(pack.get("machine_status") or "needs_review"),
                        "category": str(pack.get("category") or item_id),
                        "path": pack.get("path"),
                    }
                )
        elif isinstance(packs, Sequence):
            for pack in packs:
                if isinstance(pack, Mapping):
                    residuals.append(
                        {
                            "residual_id": str(
                                pack.get("item_id") or pack.get("residual_id") or ""
                            ),
                            "kind": "diligence_pack",
                            "status": str(pack.get("machine_status") or "needs_review"),
                            "category": str(pack.get("category") or ""),
                        }
                    )
    # Always surface coverage gaps as residuals when present
    for g in coverage_gaps:
        residuals.append(
            {
                "residual_id": f"gap:{g.get('kind') or g.get('corpus') or 'unknown'}",
                "kind": "coverage_gap",
                "status": str(g.get("status") or "unsearched"),
                "category": str(g.get("kind") or g.get("corpus") or ""),
                "message": str(g.get("message") or ""),
            }
        )
    if not residuals:
        residuals.append(
            {
                "residual_id": "diligence:stub",
                "kind": "diligence_stub",
                "status": "not_run",
                "category": "optional",
                "message": (
                    f"No diligence pack for {application_number}; optional "
                    "application_gap_closure not executed (hermetic stub)."
                ),
            }
        )
    return residuals


def _optional_conflict_review_report(
    *,
    application_number: str,
    conflict_risk: Mapping[str, Any] | None,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Call conflict_review_report if present; else hermetic stub pointer."""
    try:
        from ipfs_datasets_py.processors.domains.uspto.conflict_review_report import (
            build_conflict_review_report,
            report_to_payload,
        )

        report = build_conflict_review_report(
            application_number=application_number,
            engine_report=conflict_risk,
            generated_at_utc=generated_at_utc,
        )
        if callable(report_to_payload):
            payload = report_to_payload(report)
            if isinstance(payload, Mapping):
                out = dict(payload)
                out.setdefault("status", "ok")
                out["auto_file_blocked"] = True
                return out
        if hasattr(report, "to_dict"):
            out = report.to_dict()
            out.setdefault("status", "ok")
            return out
        if isinstance(report, Mapping):
            out = dict(report)
            out.setdefault("status", "ok")
            return out
    except Exception as exc:  # noqa: BLE001 — optional path, fail closed to stub
        _safe_log_event(
            "conflict_review_stub",
            code=type(exc).__name__,
            message=str(exc)[:160],
        )

    digest = sha256_hex(
        canonical_json(
            {
                "application_number": application_number,
                "conflict_digest": (conflict_risk or {}).get("content_digest"),
            }
        )
    )
    return {
        "schema": "paar.ConflictReviewReport@1.stub",
        "status": "stub_module_absent",
        "application_number": application_number,
        "generated_at_utc": generated_at_utc,
        "content_digest": digest,
        "auto_file_blocked": True,
        "message": (
            "conflict_review_report module not available; stub pointer only. "
            "Not a patentability conclusion. Not legal advice."
        ),
        "conflict_risk_digest": (conflict_risk or {}).get("content_digest"),
    }


def _try_diligence_packs(
    *,
    application_number: str,
    state_root: Path | None,
    include_diligence: bool,
) -> dict[str, Any] | None:
    if not include_diligence or state_root is None:
        return None
    try:
        from ipfs_datasets_py.processors.domains.uspto.application_gap_closure import (
            build_human_diligence_packs,
        )

        return build_human_diligence_packs(
            application_number,
            state_root=state_root,
            fetch_odp=False,  # hermetic offline
        )
    except Exception as exc:  # noqa: BLE001
        _safe_log_event(
            "diligence_stub",
            code=type(exc).__name__,
            message=str(exc)[:160],
        )
        return None


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run_unified_application_review(
    *,
    application_number: str = "",
    claims_text: str | None = None,
    claims_file: str | Path | None = None,
    claim_graph: Any | None = None,
    package_dir: str | Path | None = None,
    package_inventory: Mapping[str, Any] | None = None,
    prior_art_run: str | Path | None = None,
    prior_hits: Sequence[Any] | None = None,
    coverage_gaps: Sequence[Any] | None = None,
    extracts: Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
    authority_corpus_present: bool | None = None,
    filing_date: str | None = None,
    priority_date: str | None = None,
    application_type: str = "utility",
    scenario: str = "new_application",
    state_root: str | Path | None = None,
    persist: bool = True,
    include_diligence: bool = True,
    include_conflict_review: bool = True,
    include_search: bool = True,
    acceptance_package: Mapping[str, Any] | None = None,
    dispositions: Sequence[Any] | None = None,
    fixture_dir: str | Path | None = None,
    review_id: str | None = None,
    generated_at_utc: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> UnifiedApplicationReview:
    """Compose engines → UnifiedApplicationReview@1.

    Hermetic/offline: missing inputs use stubs; never network by default.
    ``persist=True`` writes under ``state_root/compliance_audits/<app>/review_<stamp>/``.
    """
    ts = generated_at_utc or _utc_now_iso()
    component_status: dict[str, str] = {}
    structural_failure = False

    # --- Fixture bundle (optional) ---
    fixture: dict[str, Any] = {}
    if fixture_dir is not None:
        fixture = load_fixture_bundle(fixture_dir)
        if not application_number:
            application_number = str(fixture.get("application_number") or "")
        if claims_text is None and fixture.get("claims_text"):
            claims_text = str(fixture["claims_text"])
        if package_inventory is None and fixture.get("package_inventory"):
            package_inventory = fixture["package_inventory"]
        if prior_hits is None and fixture.get("prior_hits") is not None:
            prior_hits = fixture["prior_hits"]
        if coverage_gaps is None and fixture.get("coverage_gaps") is not None:
            coverage_gaps = fixture["coverage_gaps"]
        if authority_corpus_present is None and "authority_corpus_present" in fixture:
            authority_corpus_present = bool(fixture["authority_corpus_present"])

    app = _normalize_app(application_number)
    if not app and package_inventory:
        app = _normalize_app(str(package_inventory.get("application_number") or ""))

    state: Path | None = Path(state_root).expanduser().resolve() if state_root else None

    # --- Inventory ---
    inventory = inventory_from_fixture_or_dir(
        package_inventory=package_inventory,
        package_dir=package_dir,
    )
    if inventory is None and package_dir is not None:
        component_status["package"] = "missing"
    elif inventory is None:
        component_status["package"] = "stub_absent"
    else:
        component_status["package"] = "loaded"
        if not app:
            app = _normalize_app(str(inventory.get("application_number") or ""))
        if authority_corpus_present is None:
            if "authority_corpus_bound" in inventory:
                authority_corpus_present = bool(inventory.get("authority_corpus_bound"))
            elif "authority_corpus_present" in inventory:
                authority_corpus_present = bool(
                    inventory.get("authority_corpus_present")
                )

    if authority_corpus_present is None:
        authority_corpus_present = False  # fail closed

    # Application type / scenario from inventory
    if inventory:
        application_type = str(
            inventory.get("application_type") or application_type or "utility"
        )
        scenario = str(inventory.get("scenario") or scenario or "new_application")

    # --- Prior-art run path ---
    run_hits, run_gaps, run_meta = load_prior_art_run_hits(prior_art_run)
    hits = normalize_prior_hits(prior_hits) if prior_hits is not None else run_hits
    gaps = (
        normalize_coverage_gaps(coverage_gaps)
        if coverage_gaps is not None
        else run_gaps
    )
    if prior_art_run is not None:
        component_status["prior_art_run"] = (
            (run_meta or {}).get("status") or "loaded"
        )
    else:
        component_status["prior_art_run"] = "not_provided"

    # --- (a) Claim limitation model ---
    claim_payload: dict[str, Any] = {}
    claim_empty = False
    claim_low_ocr = False
    claim_authority_mode = "review_required"
    claim_quality_score = 0.0
    claim_digest = ""
    graph_obj: Any = claim_graph

    try:
        from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
            build_claim_limitation_graph,
        )

        if graph_obj is None:
            graph_obj = build_claim_limitation_graph(
                claims_text=claims_text,
                claims_file=str(claims_file) if claims_file else None,
            )
        claim_payload = (
            graph_obj.to_dict(include_text=True)
            if hasattr(graph_obj, "to_dict")
            else dict(graph_obj)
        )
        quality = claim_payload.get("quality") or {}
        claim_authority_mode = str(
            quality.get("authority_mode")
            or getattr(getattr(graph_obj, "quality", None), "authority_mode", "review_required")
        )
        if hasattr(claim_authority_mode, "value"):
            claim_authority_mode = str(claim_authority_mode.value)
        claim_quality_score = float(quality.get("quality_score") or 0.0)
        claim_low_ocr = bool(quality.get("low_ocr_quality"))
        claim_digest = str(claim_payload.get("content_digest") or "")
        claims_list = claim_payload.get("claims") or []
        claim_empty = len(claims_list) == 0
        component_status["claim_model"] = "ok" if not claim_empty else "empty"
    except Exception as exc:  # noqa: BLE001
        structural_failure = True
        component_status["claim_model"] = f"error:{type(exc).__name__}"
        claim_empty = True
        _safe_log_event("claim_model_error", code=type(exc).__name__)

    claim_model_ref = {
        "content_digest": claim_digest,
        "authority_mode": claim_authority_mode,
        "quality_score": claim_quality_score,
        "low_ocr_quality": claim_low_ocr,
        "claim_count": len(claim_payload.get("claims") or []),
        "limitation_count": len(claim_payload.get("limitations") or []),
    }

    # --- (b) Review search orchestrator ---
    search_payload: dict[str, Any] = {}
    if include_search:
        try:
            from ipfs_datasets_py.processors.domains.uspto.review_search_orchestrator import (
                OrchestrationMode,
                compose_review_search,
            )

            # Feed fixture hits as US fixture when provided (hermetic)
            fixture_hits = None
            if hits:
                fixture_hits = {"us_patents": hits, "us_publications": hits}

            # Prefer live prior-art run coverage (PAAR-063/210): do not re-stub
            # foreign/NPL as unsearched when the run already searched them.
            run_searched = {
                str(c).lower()
                for c in ((run_meta or {}).get("searched_corpora") or [])
            }
            run_complete = bool((run_meta or {}).get("exhaustive_corpora_complete"))
            enable_foreign = "foreign_patents" in run_searched or "foreign" in run_searched
            enable_npl = "npl" in run_searched
            search = compose_review_search(
                application_number=app or "00000000",
                claims_text=claims_text,
                claim_graph=graph_obj if not claim_empty else None,
                filing_date=filing_date or "2020-01-01",
                priority_date=priority_date or filing_date or "2019-01-01",
                mode=OrchestrationMode.HERMETIC_STUB,
                enable_foreign=enable_foreign,
                enable_npl=enable_npl,
                fixture_hits=fixture_hits,
                generated_at_utc=ts,
            )
            search_payload = search.to_dict()
            # Promote live run coverage over hermetic stub defaults.
            if run_searched:
                search_payload["searched_corpora"] = sorted(run_searched)
                search_payload["unsearched_corpora"] = list(
                    (run_meta or {}).get("unsearched_corpora") or []
                )
                search_payload["coverage_declaration"] = {
                    c: "searched" for c in run_searched
                }
                for c in search_payload["unsearched_corpora"]:
                    search_payload["coverage_declaration"][str(c)] = "unsearched"
            # Merge search named gaps only when caller/run didn't supply coverage
            if not gaps and not run_complete:
                gaps = normalize_coverage_gaps(search_payload.get("named_gaps") or [])
            elif run_complete:
                gaps = []
            component_status["search"] = "ok"
        except Exception as exc:  # noqa: BLE001
            component_status["search"] = f"stub:{type(exc).__name__}"
            run_searched = {
                str(c).lower()
                for c in ((run_meta or {}).get("searched_corpora") or [])
            }
            search_payload = {
                "schema": "paar.ReviewSearchOrchestration@1.stub",
                "status": "stub",
                "application_number": app,
                "named_gaps": gaps,
                "searched_corpora": sorted(run_searched),
                "unsearched_corpora": list(
                    (run_meta or {}).get("unsearched_corpora") or []
                ),
                "auto_file_blocked": True,
                "message": "review_search_orchestrator unavailable; hermetic stub",
            }
            # Only invent foreign/npl gaps when no live run coverage is present.
            if not gaps and not run_searched:
                gaps = [
                    {
                        "kind": "foreign_patent",
                        "corpus": "foreign_patents",
                        "status": "unsearched",
                        "message": "search stub; foreign unsearched",
                        "required": True,
                    },
                    {
                        "kind": "npl",
                        "corpus": "npl",
                        "status": "unsearched",
                        "message": "search stub; npl unsearched",
                        "required": True,
                    },
                ]
    else:
        component_status["search"] = "skipped"
        search_payload = {
            "status": "skipped",
            "auto_file_blocked": True,
            "searched_corpora": list((run_meta or {}).get("searched_corpora") or []),
            "unsearched_corpora": list((run_meta or {}).get("unsearched_corpora") or []),
        }

    search_ref = {
        "orchestration_id": search_payload.get("orchestration_id")
        or search_payload.get("status"),
        "content_digest": search_payload.get("content_digest"),
        "mode": search_payload.get("mode") or search_payload.get("status"),
        "unsearched_corpora": list(search_payload.get("unsearched_corpora") or []),
        "searched_corpora": list(search_payload.get("searched_corpora") or []),
    }

    # --- (c) Conflict risk engine ---
    conflict_payload: dict[str, Any] = {}
    matter_risk = "unknown"
    has_human_dispositions = bool(dispositions)
    try:
        from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
            score_conflict_risk,
        )

        coverage_declaration = search_payload.get("coverage_declaration")
        conflict = score_conflict_risk(
            application_number=app,
            claim_graph=graph_obj if not claim_empty else None,
            hits=hits,
            coverage_gaps=gaps,
            coverage_declaration=coverage_declaration,
            dispositions=dispositions,
            acceptance_package=acceptance_package,
            generated_at_utc=ts,
        )
        conflict_payload = conflict.to_dict()
        matter_risk = str(conflict_payload.get("matter_risk") or "unknown")
        has_human_dispositions = bool(conflict_payload.get("dispositions"))
        # Prefer engine's coverage_gaps only when live prior-art run did not
        # already declare exhaustive corpora complete (PAAR-063/210).
        if conflict_payload.get("coverage_gaps") and not (
            run_meta or {}
        ).get("exhaustive_corpora_complete"):
            gaps = normalize_coverage_gaps(conflict_payload.get("coverage_gaps"))
        elif (run_meta or {}).get("exhaustive_corpora_complete"):
            gaps = []
        component_status["conflict_risk"] = "ok"
    except Exception as exc:  # noqa: BLE001
        component_status["conflict_risk"] = f"error:{type(exc).__name__}"
        matter_risk = "unknown"
        conflict_payload = {
            "schema": "paar.ConflictRiskReport@1.stub",
            "report_id": f"crr-stub:{app or 'unknown'}",
            "application_number": app,
            "matter_risk": "unknown",
            "content_digest": sha256_hex("conflict-stub"),
            "coverage_gaps": gaps,
            "cells": [],
            "dispositions": [],
            "auto_file_blocked": True,
            "disclaimer": "Conflict risk engine unavailable; fail-closed unknown.",
        }
        _safe_log_event("conflict_risk_error", code=type(exc).__name__)

    conflict_risk_ref = {
        "report_id": conflict_payload.get("report_id"),
        "content_digest": conflict_payload.get("content_digest"),
        "matter_risk": matter_risk,
        "cell_count": len(conflict_payload.get("cells") or []),
        "coverage_penalty_applied": bool(
            conflict_payload.get("coverage_penalty_applied")
        ),
    }

    # --- (d) Package conformance engine ---
    conf_payload: dict[str, Any] = {}
    conf_status = "unknown"
    try:
        from ipfs_datasets_py.processors.domains.uspto.package_conformance_engine import (
            evaluate_package_conformance,
        )

        ext = dict(extracts or {})
        if claims_text and "claims" not in ext:
            ext["claims"] = claims_text
        meta_map = dict(meta or {})
        if inventory and inventory.get("title") and "title" not in meta_map:
            meta_map["title"] = inventory.get("title")
        # Promote live prior-art coverage into inventory/meta for corpus_searched
        inv_for_conf = dict(inventory or {})
        run_searched_list = list((run_meta or {}).get("searched_corpora") or [])
        run_unsearched_list = list((run_meta or {}).get("unsearched_corpora") or [])
        if run_searched_list:
            inv_for_conf["searched_corpora"] = run_searched_list
            inv_for_conf["unsearched_corpora"] = run_unsearched_list
            inv_for_conf["coverage_declaration"] = {
                c: "searched" for c in run_searched_list
            }
            for c in run_unsearched_list:
                inv_for_conf["coverage_declaration"][str(c)] = "unsearched"
            meta_map["searched_corpora"] = run_searched_list
            meta_map["unsearched_corpora"] = run_unsearched_list
            meta_map["coverage_declaration"] = inv_for_conf["coverage_declaration"]

        conf = evaluate_package_conformance(
            inventory=inv_for_conf or inventory,
            application_number=app,
            application_type=application_type,
            scenario=scenario,
            extracts=ext,
            meta=meta_map,
            authority_corpus_present=bool(authority_corpus_present),
            generated_at_utc=ts,
        )
        conf_payload = conf.to_dict()
        conf_status = str(conf_payload.get("overall_status") or "unknown")
        component_status["conformance"] = "ok"
    except Exception as exc:  # noqa: BLE001
        component_status["conformance"] = f"error:{type(exc).__name__}"
        conf_status = "unknown"
        conf_payload = {
            "schema": "paar.ConformanceReport@1.stub",
            "report_id": f"conf-stub:{app or 'unknown'}",
            "application_number": app,
            "overall_status": "unknown",
            "content_digest": sha256_hex("conf-stub"),
            "results": [],
            "auto_file_blocked": True,
            "authority_corpus_present": bool(authority_corpus_present),
            "disclaimer": "Conformance engine unavailable; fail-closed unknown.",
        }
        _safe_log_event("conformance_error", code=type(exc).__name__)

    conformance_ref = {
        "report_id": conf_payload.get("report_id"),
        "content_digest": conf_payload.get("content_digest"),
        "overall_status": conf_status,
        "authority_corpus_present": bool(
            conf_payload.get("authority_corpus_present", authority_corpus_present)
        ),
    }

    # --- (e) Optional diligence packs ---
    diligence_pack = _try_diligence_packs(
        application_number=app,
        state_root=state,
        include_diligence=include_diligence,
    )
    if diligence_pack is not None:
        component_status["diligence"] = "ok"
    else:
        component_status["diligence"] = "stub" if include_diligence else "skipped"

    diligence_residuals = _stub_diligence_residuals(
        application_number=app or "unknown",
        coverage_gaps=gaps,
        diligence_pack=diligence_pack,
    )

    # --- (f) Optional conflict review report ---
    conflict_review_payload: dict[str, Any] | None = None
    if include_conflict_review:
        conflict_review_payload = _optional_conflict_review_report(
            application_number=app,
            conflict_risk=conflict_payload,
            generated_at_utc=ts,
        )
        component_status["conflict_review"] = str(
            conflict_review_payload.get("status") or "ok"
        )
    else:
        component_status["conflict_review"] = "skipped"

    # --- Disposition ---
    disposition, reasons = compute_disposition(
        claim_authority_mode=claim_authority_mode,
        claim_low_ocr=claim_low_ocr,
        claim_empty=claim_empty,
        matter_risk=matter_risk,
        has_human_dispositions=has_human_dispositions,
        conformance_status=conf_status,
        authority_corpus_present=bool(authority_corpus_present),
        structural_failure=structural_failure,
        named_residuals_accepted=bool(
            acceptance_package
            and acceptance_package.get("accepted")
            and acceptance_package.get("acknowledger_id")
        ),
    )
    exit_code = EXIT_CODE_BY_DISPOSITION.get(disposition.value, 2)

    rid = review_id or f"uar:{app or 'unknown'}:{sha256_hex(app + ts)[:12]}"
    digest = compute_content_digest(
        review_id=rid,
        application_number=app,
        disposition=disposition.value,
        conflict_risk_ref=conflict_risk_ref,
        conformance_ref=conformance_ref,
        claim_model_ref=claim_model_ref,
        coverage_gaps=gaps,
        diligence_residuals=diligence_residuals,
    )

    # --- Persist ---
    persist_path: str | None = None
    if persist and state is not None and app:
        stamp = _stamp_for_path(ts)
        out_dir = state / "compliance_audits" / app / f"review_{stamp}"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            # Component snapshots (content-free refs + full structured reports)
            _write_json(out_dir / "claim_model.json", claim_payload or claim_model_ref)
            _write_json(out_dir / "search_orchestration.json", search_payload)
            _write_json(out_dir / "conflict_risk.json", conflict_payload)
            _write_json(out_dir / "conformance.json", conf_payload)
            if diligence_pack is not None:
                _write_json(out_dir / "diligence_packs.json", diligence_pack)
            if conflict_review_payload is not None:
                _write_json(
                    out_dir / "conflict_review.json", conflict_review_payload
                )
            persist_path = str(out_dir)
            component_status["persist"] = "ok"
        except OSError as exc:
            component_status["persist"] = f"error:{type(exc).__name__}"
            _safe_log_event("persist_error", code=type(exc).__name__)
    elif persist and state is None:
        component_status["persist"] = "skipped_no_state_root"
    else:
        component_status["persist"] = "skipped"

    conflict_review_ref = None
    if conflict_review_payload is not None:
        conflict_review_ref = {
            "status": conflict_review_payload.get("status"),
            "content_digest": conflict_review_payload.get("content_digest"),
            "schema": conflict_review_payload.get("schema"),
        }

    report = UnifiedApplicationReview(
        review_id=rid,
        application_number=app,
        generated_at_utc=ts,
        content_digest=digest,
        disposition=disposition,
        exit_code_hint=exit_code,
        conflict_risk_ref=conflict_risk_ref,
        conformance_ref=conformance_ref,
        claim_model_ref=claim_model_ref,
        coverage_gaps=tuple(dict(g) for g in gaps),
        diligence_residuals=tuple(dict(d) for d in diligence_residuals),
        search_ref=search_ref,
        conflict_review_ref=conflict_review_ref,
        component_status=component_status,
        reasons=tuple(reasons),
        persist_path=persist_path,
        metadata=dict(metadata or {}),
    )

    payload = report.to_dict()
    _assert_no_forbidden_phrases(payload)
    if payload.get("auto_file_blocked") is not True:
        raise ApplicationReviewOrchestratorError(
            "auto_file_blocked must be true",
            code="auto_file_invariant",
        )

    # Write unified report last (after digest/refs stable)
    if persist_path:
        try:
            _write_json(
                Path(persist_path) / "unified_application_review.json", payload
            )
            _write_json(
                Path(persist_path) / "summary.json", report.compact_summary()
            )
        except OSError:
            pass

    _safe_log_event(
        "complete",
        application_number=app,
        disposition=disposition.value,
        exit_code=exit_code,
        matter_risk=matter_risk,
        conformance=conf_status,
    )
    return report


def review_application(
    application_number: str,
    **kwargs: Any,
) -> UnifiedApplicationReview:
    """Alias entrypoint: ``review_application(app, ...)``."""
    return run_unified_application_review(
        application_number=application_number, **kwargs
    )


def disposition_exit_code(disposition: ReviewDisposition | str) -> int:
    """Map disposition to CLI exit code (0/1/2)."""
    key = (
        disposition.value
        if isinstance(disposition, ReviewDisposition)
        else str(disposition).lower()
    )
    return int(EXIT_CODE_BY_DISPOSITION.get(key, 2))


__all__ = [
    "UNIFIED_APPLICATION_REVIEW_SCHEMA",
    "UNIFIED_APPLICATION_REVIEW_INTERFACE",
    "APPLICATION_REVIEW_ORCHESTRATOR_CODE_VERSION",
    "REVIEW_ONLY_UNIFIED_DISCLAIMER",
    "EXIT_CODE_BY_DISPOSITION",
    "ReviewDisposition",
    "ApplicationReviewOrchestratorError",
    "UnifiedApplicationReview",
    "run_unified_application_review",
    "review_application",
    "compute_disposition",
    "compute_content_digest",
    "disposition_exit_code",
    "load_fixture_bundle",
    "normalize_prior_hits",
    "normalize_coverage_gaps",
    "load_prior_art_run_hits",
    "inventory_from_fixture_or_dir",
    "sha256_hex",
    "canonical_json",
]
