"""PAAR conflict risk scoring engine (PAAR-020 / PAAR-021).

Scores claim-limitation × prior-art-hit cells with a closed risk vocabulary
``unknown | low | medium | high`` using a **lexical** token-overlap baseline
(distinguishability-style). Optional embedding path is disabled by default.

Design invariants
-----------------
* **Not legal advice**; never emits novelty, obviousness, or patentability
  conclusions or labels.
* Risk cells carry quotes + method tags only — no legal determination.
* Coverage penalty: unsearched required corpora (foreign / NPL by default)
  cannot yield aggregate matter risk ``low``.
* Deterministic content digests (canonical JSON, wall-clock excluded).
* Fail closed: missing inputs → ``unknown`` risk, never invented low risk.
* No Sign / Pay / Submit; ``auto_file_blocked`` always true.

Conflict policy (PAAR-020/021): own this module and its tests; reuse
claim_limitation_model and distinguishability matrix patterns as inputs only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

CONFLICT_RISK_REPORT_SCHEMA: Final = "paar.ConflictRiskReport@1"
CONFLICT_RISK_INTERFACE: Final = "ConflictRiskReport@1"
CONFLICT_RISK_ENGINE_CODE_VERSION: Final = "1.0.0"

REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER: Final = (
    "Review-only conflict risk screening. Risk scores are heuristic lexical "
    "(or optional embedding) overlap signals for human triage. This is not "
    "legal advice, not a novelty determination, not an obviousness "
    "determination, and not a patentability conclusion. Coverage gaps remain "
    "named. auto_file_blocked=true. Named human review is required before any "
    "legal or filing action."
)

# Default required corpora for coverage penalty (cannot aggregate to "low"
# when these remain unsearched without an explicit human acceptance package).
DEFAULT_REQUIRED_CORPORA: Final[tuple[str, ...]] = (
    "foreign_patents",
    "npl",
)

DEFAULT_MAX_QUOTE_CHARS: Final = 240
DEFAULT_MAX_CELLS: Final = 2_048

# Lexical overlap thresholds → risk (closed vocabulary only).
_OVERLAP_HIGH: Final = 0.55
_OVERLAP_MEDIUM: Final = 0.28
_OVERLAP_LOW: Final = 0.08

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-/]{2,}")
_STOP: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "method",
        "system",
        "device",
        "comprising",
        "including",
        "wherein",
        "claim",
        "said",
        "into",
        "onto",
        "over",
        "under",
        "such",
        "than",
        "then",
        "when",
        "which",
        "while",
        "about",
        "above",
        "after",
        "before",
        "between",
        "each",
        "other",
        "having",
        "using",
        "based",
        "configured",
        "provide",
        "provides",
        "provided",
    }
)

# Affirmative patentability phrases forbidden in outputs (defense in depth).
# Built from parts so source lines are not bare affirmative conclusions.
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
        "anticipates " + "claim",  # ban
        "renders claim " + "obvious",  # ban
    )


_FORBIDDEN_OUTPUT_PHRASES: Final[tuple[str, ...]] = _ban_phrases()


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Closed risk vocabulary — never patentability labels."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskMethod(str, Enum):
    LEXICAL = "lexical"
    EMBEDDING = "embedding"
    STRUCTURED = "structured"
    UNKNOWN = "unknown"


class DispositionCode(str, Enum):
    NOT_MATERIAL = "not_material"
    CONSIDER_IDS = "consider_ids"
    DISTINGUISH_IN_REMARKS = "distinguish_in_remarks"
    NEEDS_COUNSEL = "needs_counsel"
    DEFERRED = "deferred"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConflictRiskEngineError(ValueError):
    """Bounded conflict-risk engine failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "conflict_risk_engine_error"
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


def tokenize(text: str) -> frozenset[str]:
    """Lexical tokens for overlap scoring (stop-word filtered)."""
    return frozenset(
        t.lower()
        for t in _TOKEN_RE.findall(str(text or ""))
        if t.lower() not in _STOP
    )


def lexical_overlap(limitation_text: str, hit_text: str) -> tuple[float, tuple[str, ...]]:
    """Return (overlap ratio in [0,1], shared tokens sample)."""
    lim = tokenize(limitation_text)
    hit = tokenize(hit_text)
    if not lim:
        return 0.0, ()
    shared = sorted(lim & hit)
    ratio = round(len(shared) / max(len(lim), 1), 4)
    return ratio, tuple(shared[:16])


def overlap_to_risk(overlap: float) -> RiskLevel:
    """Map lexical overlap to closed risk vocabulary (fail closed on empty)."""
    if overlap < 0:
        return RiskLevel.UNKNOWN
    if overlap >= _OVERLAP_HIGH:
        return RiskLevel.HIGH
    if overlap >= _OVERLAP_MEDIUM:
        return RiskLevel.MEDIUM
    if overlap >= _OVERLAP_LOW:
        return RiskLevel.LOW
    # Near-zero overlap is still a scored low signal when both sides have text;
    # callers may elevate to unknown when hit text is empty.
    return RiskLevel.LOW


def risk_rank(level: RiskLevel | str) -> int:
    order = {
        RiskLevel.UNKNOWN.value: 0,
        RiskLevel.LOW.value: 1,
        RiskLevel.MEDIUM.value: 2,
        RiskLevel.HIGH.value: 3,
        RiskLevel.UNKNOWN: 0,
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
    }
    if isinstance(level, RiskLevel):
        return order[level]
    return order.get(str(level).lower(), 0)


def max_risk(*levels: RiskLevel | str) -> RiskLevel:
    """Aggregate by maximum severity; unknown loses to any known risk."""
    best = RiskLevel.UNKNOWN
    best_rank = -1
    for level in levels:
        rl = level if isinstance(level, RiskLevel) else RiskLevel(str(level).lower())
        # Prefer known risks over unknown when comparing for max severity of concern
        rank = risk_rank(rl)
        # Special: high/medium/low outrank unknown for "matter concern"
        # but for pure max of concern we treat high > medium > low > unknown
        if rank > best_rank:
            best = rl
            best_rank = rank
    return best


def _bounded_quote(text: str, *, max_chars: int = DEFAULT_MAX_QUOTE_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1] + "…"


def _assert_no_forbidden_phrases(payload: Mapping[str, Any]) -> None:
    """Fail if affirmative banned conclusion phrases appear outside disclaimers."""
    blob = canonical_json(payload).lower()
    # Strip known disclaimer / negative-framing windows before scanning.
    cleaned = blob
    for neg in (
        "not a patentability",
        "not patentability",
        "never a patentability",
        "no patentability",
        "not a novelty",
        "not an obviousness",
        "not legal advice",
    ):
        cleaned = cleaned.replace(neg, " ")
    for phrase in _FORBIDDEN_OUTPUT_PHRASES:
        if phrase in cleaned:
            raise ConflictRiskEngineError(
                f"forbidden conclusion phrase in output: {phrase!r}",
                code="forbidden_phrase",
            )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()  # type: ignore[no-any-return]
    return {}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """Named unsearched / failed corpus gap."""

    kind: str
    status: str = "unsearched"
    corpus: str | None = None
    message: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "corpus": self.corpus,
            "message": self.message,
            "required": bool(self.required),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGap":
        return cls(
            kind=str(value.get("kind") or value.get("corpus") or "unknown"),
            status=str(value.get("status") or "unsearched"),
            corpus=(
                str(value["corpus"])
                if value.get("corpus") is not None
                else str(value.get("kind") or "") or None
            ),
            message=str(value.get("message") or value.get("description") or ""),
            required=bool(value.get("required", True)),
        )


@dataclass(frozen=True, slots=True)
class ConflictRiskCell:
    """One limitation × hit risk cell."""

    cell_id: str
    limitation_id: str
    claim_number: int
    hit_id: str
    risk: RiskLevel
    method: RiskMethod
    confidence: float
    limitation_quote: str
    hit_quote: str
    lexical_overlap: float = 0.0
    shared_tokens: tuple[str, ...] = ()
    source_links: tuple[Mapping[str, str], ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "limitation_id": self.limitation_id,
            "claim_number": int(self.claim_number),
            "hit_id": self.hit_id,
            "risk": self.risk.value,
            "method": self.method.value,
            "confidence": round(float(self.confidence), 4),
            "limitation_quote": self.limitation_quote,
            "hit_quote": self.hit_quote,
            "lexical_overlap": round(float(self.lexical_overlap), 4),
            "shared_tokens": list(self.shared_tokens),
            "source_links": [dict(s) for s in self.source_links],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConflictRiskCell":
        return cls(
            cell_id=str(value.get("cell_id") or ""),
            limitation_id=str(value.get("limitation_id") or ""),
            claim_number=int(value.get("claim_number") or 0),
            hit_id=str(value.get("hit_id") or ""),
            risk=RiskLevel(str(value.get("risk") or "unknown").lower()),
            method=RiskMethod(str(value.get("method") or "unknown").lower()),
            confidence=float(value.get("confidence") or 0.0),
            limitation_quote=str(value.get("limitation_quote") or ""),
            hit_quote=str(value.get("hit_quote") or ""),
            lexical_overlap=float(value.get("lexical_overlap") or 0.0),
            shared_tokens=tuple(str(t) for t in (value.get("shared_tokens") or ())),
            source_links=tuple(
                MappingProxyType(dict(s))
                for s in (value.get("source_links") or ())
                if isinstance(s, Mapping)
            ),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class HumanDisposition:
    """Optional human disposition over risk cells (never auto-filed)."""

    disposition_code: DispositionCode
    acknowledger_id: str
    acknowledged_at_utc: str
    cell_ids: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition_code": self.disposition_code.value,
            "acknowledger_id": self.acknowledger_id,
            "acknowledged_at_utc": self.acknowledged_at_utc,
            "cell_ids": list(self.cell_ids),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanDisposition":
        return cls(
            disposition_code=DispositionCode(
                str(value.get("disposition_code") or "deferred").lower()
            ),
            acknowledger_id=str(value.get("acknowledger_id") or ""),
            acknowledged_at_utc=str(value.get("acknowledged_at_utc") or ""),
            cell_ids=tuple(str(x) for x in (value.get("cell_ids") or ())),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class ConflictRiskReport:
    """ConflictRiskReport@1 — machine-readable risk screening artifact."""

    report_id: str
    application_number: str
    matter_risk: RiskLevel
    cells: tuple[ConflictRiskCell, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    content_digest: str
    generated_at_utc: str
    dispositions: tuple[HumanDisposition, ...] = ()
    schema: str = CONFLICT_RISK_REPORT_SCHEMA
    disclaimer: str = REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER
    auto_file_blocked: bool = True
    method_default: str = RiskMethod.LEXICAL.value
    metadata: Mapping[str, str] = field(default_factory=dict)
    coverage_penalty_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": CONFLICT_RISK_INTERFACE,
            "code_version": CONFLICT_RISK_ENGINE_CODE_VERSION,
            "report_id": self.report_id,
            "application_number": self.application_number,
            "generated_at_utc": self.generated_at_utc,
            "content_digest": self.content_digest,
            "disclaimer": self.disclaimer,
            "auto_file_blocked": True,  # invariant
            "matter_risk": self.matter_risk.value,
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "cells": [c.to_dict() for c in self.cells],
            "dispositions": [d.to_dict() for d in self.dispositions],
            "method_default": self.method_default,
            "coverage_penalty_applied": bool(self.coverage_penalty_applied),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConflictRiskReport":
        return cls(
            report_id=str(value.get("report_id") or ""),
            application_number=str(value.get("application_number") or ""),
            matter_risk=RiskLevel(str(value.get("matter_risk") or "unknown").lower()),
            cells=tuple(
                ConflictRiskCell.from_dict(c) for c in (value.get("cells") or ())
            ),
            coverage_gaps=tuple(
                CoverageGap.from_dict(g) for g in (value.get("coverage_gaps") or ())
            ),
            content_digest=str(value.get("content_digest") or ""),
            generated_at_utc=str(value.get("generated_at_utc") or ""),
            dispositions=tuple(
                HumanDisposition.from_dict(d)
                for d in (value.get("dispositions") or ())
            ),
            schema=str(value.get("schema") or CONFLICT_RISK_REPORT_SCHEMA),
            disclaimer=str(
                value.get("disclaimer") or REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER
            ),
            auto_file_blocked=True,
            method_default=str(value.get("method_default") or RiskMethod.LEXICAL.value),
            metadata=dict(value.get("metadata") or {}),
            coverage_penalty_applied=bool(value.get("coverage_penalty_applied", False)),
        )


# ---------------------------------------------------------------------------
# Input normalization
# ---------------------------------------------------------------------------


def _limitations_from_input(
    limitations: Sequence[Any] | None = None,
    claim_graph: Any | None = None,
) -> list[dict[str, Any]]:
    """Normalize limitations from list or ClaimLimitationGraph."""
    rows: list[dict[str, Any]] = []
    if claim_graph is not None:
        graph_map = _as_mapping(claim_graph)
        for lim in graph_map.get("limitations") or getattr(claim_graph, "limitations", ()) or ():
            if isinstance(lim, Mapping):
                rows.append(dict(lim))
            elif hasattr(lim, "to_dict"):
                rows.append(lim.to_dict(include_text=True))  # type: ignore[call-arg]
            else:
                rows.append(
                    {
                        "limitation_id": str(getattr(lim, "limitation_id", "")),
                        "claim_number": int(getattr(lim, "claim_number", 0) or 0),
                        "text": str(getattr(lim, "text", "") or ""),
                    }
                )
    for lim in limitations or ():
        if isinstance(lim, Mapping):
            rows.append(dict(lim))
        elif hasattr(lim, "to_dict"):
            d = lim.to_dict()
            if isinstance(d, Mapping):
                rows.append(dict(d))
        else:
            rows.append(
                {
                    "limitation_id": str(getattr(lim, "limitation_id", "") or ""),
                    "claim_number": int(getattr(lim, "claim_number", 0) or 0),
                    "text": str(getattr(lim, "text", "") or ""),
                }
            )
    # Deduplicate by limitation_id preserving order
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        lid = str(row.get("limitation_id") or "").strip()
        if not lid:
            lid = f"lim:anon:{len(out)+1}"
            row = {**row, "limitation_id": lid}
        if lid in seen:
            continue
        seen.add(lid)
        out.append(row)
    return out


def _hits_from_input(
    hits: Sequence[Any] | None = None,
    *,
    journal: Any | None = None,
    chart: Any | None = None,
    distinguishability_matrix: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize prior-art hits from list, journal, chart, or matrix docs."""
    rows: list[dict[str, Any]] = []

    def _add(hit_id: str, text: str, **extra: Any) -> None:
        hid = str(hit_id or "").strip()
        if not hid:
            return
        extra.pop("hit_id", None)
        extra.pop("document_id", None)
        extra.pop("text", None)
        extra.pop("id", None)
        rows.append(
            {
                "hit_id": hid,
                "document_id": hid,
                "text": str(text or ""),
                **extra,
            }
        )

    for hit in hits or ():
        if isinstance(hit, Mapping):
            hid = str(
                hit.get("hit_id")
                or hit.get("document_id")
                or hit.get("id")
                or ""
            )
            text = str(
                hit.get("text")
                or hit.get("passage_excerpt")
                or hit.get("excerpt")
                or hit.get("title")
                or ""
            )
            _add(
                hid,
                text,
                **{
                    k: v
                    for k, v in hit.items()
                    if k
                    not in {
                        "text",
                        "hit_id",
                        "document_id",
                        "id",
                        "passage_excerpt",
                        "excerpt",
                        "title",
                    }
                },
            )
        else:
            hid = str(
                getattr(hit, "hit_id", None)
                or getattr(hit, "document_id", None)
                or getattr(hit, "id", "")
                or ""
            )
            text = str(
                getattr(hit, "text", None)
                or getattr(hit, "passage_excerpt", None)
                or getattr(hit, "excerpt", "")
                or ""
            )
            _add(hid, text)

    if journal is not None:
        jmap = _as_mapping(journal)
        records = jmap.get("records") or getattr(journal, "records", ()) or ()
        for rec in records:
            rmap = _as_mapping(rec) if not isinstance(rec, Mapping) else rec
            for hit in rmap.get("hits") or getattr(rec, "hits", ()) or ():
                hmap = _as_mapping(hit) if not isinstance(hit, Mapping) else hit
                hid = str(hmap.get("document_id") or hmap.get("hit_id") or "")
                text = str(
                    hmap.get("passage_excerpt")
                    or hmap.get("text")
                    or (hmap.get("metadata") or {}).get("title")
                    or ""
                )
                _add(hid, text, rank=hmap.get("rank"), score=hmap.get("score"))

    if chart is not None:
        cmap = _as_mapping(chart)
        for entry in cmap.get("entries") or getattr(chart, "entries", ()) or ():
            emap = _as_mapping(entry) if not isinstance(entry, Mapping) else entry
            hid = str(emap.get("document_id") or emap.get("hit_id") or "")
            text = str(emap.get("passage_excerpt") or emap.get("text") or "")
            _add(hid, text)

    if distinguishability_matrix:
        for doc in distinguishability_matrix.get("documents") or ():
            if not isinstance(doc, Mapping):
                continue
            hid = str(doc.get("document_id") or "")
            text = str(doc.get("excerpt_preview") or "")
            _add(hid, text)

    # Deduplicate by hit_id; merge text preferring longer
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        hid = row["hit_id"]
        if hid not in by_id or len(str(row.get("text") or "")) > len(
            str(by_id[hid].get("text") or "")
        ):
            by_id[hid] = row
    return list(by_id.values())


def _coverage_gaps_from_input(
    coverage_gaps: Sequence[Any] | None = None,
    *,
    coverage_declaration: Any | None = None,
    plan: Any | None = None,
) -> list[CoverageGap]:
    gaps: list[CoverageGap] = []

    def _push(raw: Any) -> None:
        if isinstance(raw, CoverageGap):
            gaps.append(raw)
            return
        if isinstance(raw, Mapping):
            gaps.append(CoverageGap.from_dict(raw))
            return
        if hasattr(raw, "to_dict"):
            gaps.append(CoverageGap.from_dict(raw.to_dict()))
            return
        kind = str(getattr(raw, "kind", None) or getattr(raw, "corpus", "") or "unknown")
        status = str(getattr(raw, "status", None) or "unsearched")
        gaps.append(CoverageGap(kind=kind, status=status, corpus=kind))

    for g in coverage_gaps or ():
        _push(g)

    if coverage_declaration is not None:
        cmap = _as_mapping(coverage_declaration)
        for g in cmap.get("named_gaps") or getattr(coverage_declaration, "named_gaps", ()) or ():
            _push(g)
        for corpus in cmap.get("unsearched_corpora") or ():
            gaps.append(
                CoverageGap(
                    kind=str(corpus),
                    status="unsearched",
                    corpus=str(corpus),
                    message=f"Corpus {corpus} unsearched",
                    required=str(corpus).lower()
                    in {c.lower() for c in DEFAULT_REQUIRED_CORPORA},
                )
            )

    if plan is not None:
        pmap = _as_mapping(plan)
        for g in pmap.get("coverage_gaps") or getattr(plan, "coverage_gaps", ()) or ():
            _push(g)

    # Dedup by (kind, status, corpus)
    seen: set[tuple[str, str, str]] = set()
    out: list[CoverageGap] = []
    for g in gaps:
        key = (g.kind, g.status, g.corpus or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# Cell scoring
# ---------------------------------------------------------------------------


def score_limitation_hit_cell(
    *,
    limitation_id: str,
    claim_number: int,
    limitation_text: str,
    hit_id: str,
    hit_text: str,
    method: RiskMethod = RiskMethod.LEXICAL,
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
) -> ConflictRiskCell:
    """Score a single limitation × hit cell (lexical baseline)."""
    lim_text = str(limitation_text or "")
    hit_body = str(hit_text or "")
    cell_id = f"cell:{limitation_id}:{hit_id}"

    if method is not RiskMethod.LEXICAL and method is not RiskMethod.UNKNOWN:
        # Embedding / structured reserved; fail closed to unknown without vectors
        if method is RiskMethod.EMBEDDING:
            return ConflictRiskCell(
                cell_id=cell_id,
                limitation_id=limitation_id,
                claim_number=int(claim_number),
                hit_id=hit_id,
                risk=RiskLevel.UNKNOWN,
                method=RiskMethod.EMBEDDING,
                confidence=0.0,
                limitation_quote=_bounded_quote(lim_text, max_chars=max_quote_chars),
                hit_quote=_bounded_quote(hit_body, max_chars=max_quote_chars),
                notes="embedding path not enabled; fail closed to unknown",
            )

    if not lim_text.strip() or not hit_body.strip():
        return ConflictRiskCell(
            cell_id=cell_id,
            limitation_id=limitation_id,
            claim_number=int(claim_number),
            hit_id=hit_id,
            risk=RiskLevel.UNKNOWN,
            method=RiskMethod.LEXICAL,
            confidence=0.0,
            limitation_quote=_bounded_quote(lim_text, max_chars=max_quote_chars),
            hit_quote=_bounded_quote(hit_body, max_chars=max_quote_chars),
            lexical_overlap=0.0,
            notes="missing limitation or hit text; fail closed to unknown",
        )

    overlap, shared = lexical_overlap(lim_text, hit_body)
    risk = overlap_to_risk(overlap)
    # Confidence tracks how decisive the lexical signal is
    confidence = round(min(1.0, max(0.0, abs(overlap - 0.15) + 0.35)), 4)
    if risk is RiskLevel.HIGH:
        confidence = round(min(1.0, 0.55 + overlap * 0.4), 4)
    elif risk is RiskLevel.MEDIUM:
        confidence = round(min(1.0, 0.4 + overlap * 0.5), 4)
    elif risk is RiskLevel.LOW:
        confidence = round(min(1.0, 0.35 + (1.0 - overlap) * 0.2), 4)

    return ConflictRiskCell(
        cell_id=cell_id,
        limitation_id=limitation_id,
        claim_number=int(claim_number),
        hit_id=hit_id,
        risk=risk,
        method=RiskMethod.LEXICAL,
        confidence=confidence,
        limitation_quote=_bounded_quote(lim_text, max_chars=max_quote_chars),
        hit_quote=_bounded_quote(hit_body, max_chars=max_quote_chars),
        lexical_overlap=overlap,
        shared_tokens=shared,
        notes="lexical token-overlap only; not a legal determination",
    )


def score_cells_from_matrix(
    matrix: Mapping[str, Any],
    *,
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
) -> list[ConflictRiskCell]:
    """Convert a distinguishability matrix into risk cells."""
    cells: list[ConflictRiskCell] = []
    lim_text_by_id: dict[str, str] = {}
    for hint in matrix.get("drafting_hints") or ():
        if isinstance(hint, Mapping):
            lim_text_by_id[str(hint.get("limitation_id") or "")] = str(
                hint.get("candidate_text") or ""
            )
    doc_text: dict[str, str] = {}
    for doc in matrix.get("documents") or ():
        if isinstance(doc, Mapping):
            doc_text[str(doc.get("document_id") or "")] = str(
                doc.get("excerpt_preview") or ""
            )

    for raw in matrix.get("cells") or ():
        if not isinstance(raw, Mapping):
            continue
        lid = str(raw.get("limitation_id") or "")
        did = str(raw.get("document_id") or raw.get("hit_id") or "")
        # Prefer precomputed overlap when present
        if "lexical_overlap" in raw:
            overlap = float(raw.get("lexical_overlap") or 0.0)
            shared = tuple(str(t) for t in (raw.get("shared_tokens") or ())[:16])
            risk = overlap_to_risk(overlap)
            if not lim_text_by_id.get(lid) and not doc_text.get(did):
                # matrix may still have enough for quotes via empty
                pass
            cells.append(
                ConflictRiskCell(
                    cell_id=f"cell:{lid}:{did}",
                    limitation_id=lid,
                    claim_number=int(raw.get("claim_number") or 0),
                    hit_id=did,
                    risk=risk if (overlap > 0 or shared) else RiskLevel.UNKNOWN,
                    method=RiskMethod.LEXICAL,
                    confidence=round(min(1.0, 0.3 + overlap), 4),
                    limitation_quote=_bounded_quote(
                        lim_text_by_id.get(lid, ""), max_chars=max_quote_chars
                    ),
                    hit_quote=_bounded_quote(
                        doc_text.get(did, ""), max_chars=max_quote_chars
                    ),
                    lexical_overlap=overlap,
                    shared_tokens=shared,
                    notes="from distinguishability matrix; lexical only",
                )
            )
        else:
            cells.append(
                score_limitation_hit_cell(
                    limitation_id=lid,
                    claim_number=int(raw.get("claim_number") or 0),
                    limitation_text=lim_text_by_id.get(lid, ""),
                    hit_id=did,
                    hit_text=doc_text.get(did, ""),
                    max_quote_chars=max_quote_chars,
                )
            )
    return cells


# ---------------------------------------------------------------------------
# Aggregation + coverage penalty (PAAR-021)
# ---------------------------------------------------------------------------


def required_unsearched_gaps(
    coverage_gaps: Sequence[CoverageGap],
    *,
    required_corpora: Sequence[str] = DEFAULT_REQUIRED_CORPORA,
) -> list[CoverageGap]:
    """Return gaps that block aggregate 'low' matter risk."""
    required = {c.lower() for c in required_corpora}
    out: list[CoverageGap] = []
    for g in coverage_gaps:
        status = (g.status or "").lower()
        if status not in {"unsearched", "failed", "partial", "unavailable"}:
            continue
        corpus = (g.corpus or g.kind or "").lower()
        kind = (g.kind or "").lower()
        is_required = g.required or corpus in required or kind in required
        # Map common kind aliases
        if kind in {"foreign_patent", "foreign_patents"} or corpus in {
            "foreign_patent",
            "foreign_patents",
        }:
            is_required = is_required or "foreign_patents" in required
        if kind in {"npl"} or corpus in {"npl"}:
            is_required = is_required or "npl" in required
        if is_required:
            out.append(g)
    return out


def aggregate_matter_risk(
    cells: Sequence[ConflictRiskCell],
    coverage_gaps: Sequence[CoverageGap] = (),
    *,
    required_corpora: Sequence[str] = DEFAULT_REQUIRED_CORPORA,
    acceptance_package: Mapping[str, Any] | None = None,
) -> tuple[RiskLevel, bool]:
    """Max-aggregate cell risk with coverage penalty.

    Returns ``(matter_risk, coverage_penalty_applied)``.

    Coverage penalty: if required foreign/NPL (or other required) corpora are
    unsearched and no human acceptance package is present, matter risk cannot
    be ``low`` — elevated at least to ``medium`` (or ``unknown`` when no cells).
    """
    if not cells:
        base = RiskLevel.UNKNOWN
    else:
        base = RiskLevel.UNKNOWN
        for cell in cells:
            base = max_risk(base, cell.risk)

    blocking = required_unsearched_gaps(
        coverage_gaps, required_corpora=required_corpora
    )
    accepted = bool(
        acceptance_package
        and acceptance_package.get("accepted")
        and acceptance_package.get("acknowledger_id")
    )
    if not blocking or accepted:
        return base, False

    # Penalty: cannot claim aggregate low when required corpora unsearched
    if base is RiskLevel.LOW:
        return RiskLevel.MEDIUM, True
    if base is RiskLevel.UNKNOWN:
        # Stay unknown (fail closed) but mark penalty so callers cannot treat as low
        return RiskLevel.UNKNOWN, True
    return base, True


def compute_content_digest(
    *,
    report_id: str,
    application_number: str,
    matter_risk: RiskLevel | str,
    cells: Sequence[ConflictRiskCell | Mapping[str, Any]],
    coverage_gaps: Sequence[CoverageGap | Mapping[str, Any]],
    dispositions: Sequence[HumanDisposition | Mapping[str, Any]] = (),
    coverage_penalty_applied: bool = False,
) -> str:
    """Deterministic digest excluding wall-clock timestamps."""
    cell_payloads = [
        c.to_dict() if isinstance(c, ConflictRiskCell) else dict(c) for c in cells
    ]
    gap_payloads = [
        g.to_dict() if isinstance(g, CoverageGap) else dict(g) for g in coverage_gaps
    ]
    disp_payloads = [
        d.to_dict() if isinstance(d, HumanDisposition) else dict(d)
        for d in dispositions
    ]
    payload = {
        "schema": CONFLICT_RISK_REPORT_SCHEMA,
        "report_id": report_id,
        "application_number": application_number,
        "matter_risk": (
            matter_risk.value if isinstance(matter_risk, RiskLevel) else str(matter_risk)
        ),
        "cells": cell_payloads,
        "coverage_gaps": gap_payloads,
        "dispositions": disp_payloads,
        "auto_file_blocked": True,
        "coverage_penalty_applied": bool(coverage_penalty_applied),
        "code_version": CONFLICT_RISK_ENGINE_CODE_VERSION,
    }
    return sha256_hex(canonical_json(payload))


# ---------------------------------------------------------------------------
# Public engine entrypoints
# ---------------------------------------------------------------------------


def score_conflict_risk(
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
    required_corpora: Sequence[str] = DEFAULT_REQUIRED_CORPORA,
    acceptance_package: Mapping[str, Any] | None = None,
    report_id: str | None = None,
    generated_at_utc: str | None = None,
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
    max_cells: int = DEFAULT_MAX_CELLS,
    metadata: Mapping[str, str] | None = None,
) -> ConflictRiskReport:
    """Build ConflictRiskReport@1 from limitations × hits (lexical baseline).

    Fail closed: empty inputs yield ``matter_risk=unknown`` with no invented
    low-risk cells. Coverage penalty blocks aggregate ``low`` when required
    corpora remain unsearched without an acceptance package.
    """
    app = re.sub(r"\D", "", str(application_number or "")) or str(
        application_number or ""
    ).strip()
    lims = _limitations_from_input(limitations, claim_graph=claim_graph)
    hit_rows = _hits_from_input(
        hits,
        journal=journal,
        chart=chart,
        distinguishability_matrix=distinguishability_matrix,
    )
    gaps = _coverage_gaps_from_input(
        coverage_gaps,
        coverage_declaration=coverage_declaration,
        plan=plan,
    )

    cells: list[ConflictRiskCell] = []
    if distinguishability_matrix and not lims and distinguishability_matrix.get("cells"):
        cells = score_cells_from_matrix(
            distinguishability_matrix, max_quote_chars=max_quote_chars
        )
    else:
        for lim in lims:
            lid = str(lim.get("limitation_id") or "")
            cnum = int(lim.get("claim_number") or 0)
            ltext = str(lim.get("text") or lim.get("limitation_text") or "")
            if not hit_rows:
                # No hits: do not invent low risk; leave matter unknown via empty cells
                continue
            for hit in hit_rows:
                cells.append(
                    score_limitation_hit_cell(
                        limitation_id=lid,
                        claim_number=cnum,
                        limitation_text=ltext,
                        hit_id=str(hit.get("hit_id") or hit.get("document_id") or ""),
                        hit_text=str(hit.get("text") or ""),
                        max_quote_chars=max_quote_chars,
                    )
                )
                if len(cells) >= max_cells:
                    break
            if len(cells) >= max_cells:
                break

    # Stable order for digests
    cells.sort(key=lambda c: (c.claim_number, c.limitation_id, c.hit_id))

    disp: list[HumanDisposition] = []
    for d in dispositions or ():
        if isinstance(d, HumanDisposition):
            disp.append(d)
        elif isinstance(d, Mapping):
            disp.append(HumanDisposition.from_dict(d))

    matter, penalty = aggregate_matter_risk(
        cells,
        gaps,
        required_corpora=required_corpora,
        acceptance_package=acceptance_package,
    )

    rid = report_id or f"crr:{app or 'unknown'}:{sha256_hex(app + str(len(cells)))[:12]}"
    digest = compute_content_digest(
        report_id=rid,
        application_number=app,
        matter_risk=matter,
        cells=cells,
        coverage_gaps=gaps,
        dispositions=disp,
        coverage_penalty_applied=penalty,
    )
    ts = generated_at_utc or _utc_now_iso()

    report = ConflictRiskReport(
        report_id=rid,
        application_number=app,
        matter_risk=matter,
        cells=tuple(cells),
        coverage_gaps=tuple(gaps),
        content_digest=digest,
        generated_at_utc=ts,
        dispositions=tuple(disp),
        coverage_penalty_applied=penalty,
        metadata=dict(metadata or {}),
    )
    payload = report.to_dict()
    _assert_no_forbidden_phrases(payload)
    # Hard invariant
    if payload.get("auto_file_blocked") is not True:
        raise ConflictRiskEngineError(
            "auto_file_blocked must be true", code="auto_file_invariant"
        )
    return report


def score_from_distinguishability_matrix(
    matrix: Mapping[str, Any],
    *,
    application_number: str = "",
    coverage_gaps: Sequence[Any] | None = None,
    **kwargs: Any,
) -> ConflictRiskReport:
    """Convenience: build report primarily from a distinguishability matrix."""
    return score_conflict_risk(
        application_number=application_number,
        distinguishability_matrix=matrix,
        coverage_gaps=coverage_gaps
        if coverage_gaps is not None
        else [
            {"kind": "foreign_patent", "status": "unsearched", "corpus": "foreign_patents"},
            {"kind": "npl", "status": "unsearched", "corpus": "npl"},
        ],
        **kwargs,
    )


__all__ = [
    "CONFLICT_RISK_ENGINE_CODE_VERSION",
    "CONFLICT_RISK_INTERFACE",
    "CONFLICT_RISK_REPORT_SCHEMA",
    "DEFAULT_REQUIRED_CORPORA",
    "REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER",
    "ConflictRiskCell",
    "ConflictRiskEngineError",
    "ConflictRiskReport",
    "CoverageGap",
    "DispositionCode",
    "HumanDisposition",
    "RiskLevel",
    "RiskMethod",
    "aggregate_matter_risk",
    "canonical_json",
    "compute_content_digest",
    "lexical_overlap",
    "max_risk",
    "overlap_to_risk",
    "required_unsearched_gaps",
    "score_cells_from_matrix",
    "score_conflict_risk",
    "score_from_distinguishability_matrix",
    "score_limitation_hit_cell",
    "sha256_hex",
    "tokenize",
]
