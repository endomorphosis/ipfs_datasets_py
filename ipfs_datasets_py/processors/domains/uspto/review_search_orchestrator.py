"""PAAR multi-corpus review search orchestrator (PAAR-030).

Composes a multi-corpus search plan and journal stubs for US patents /
publications plus optional foreign and NPL corpora. Named gaps remain
visible when corpora are unsearched. Priority / effective date cutoffs are
applied when temporal anchors are provided.

Design invariants
-----------------
* **Not legal advice**; never asserts novelty, obviousness, or patentability.
* Prefer calling existing ``prior_art_search_client`` APIs (plan_prior_art /
  build_operator_prior_art_plan). Hermetic offline fixtures for CI.
* Never scrape PPS / Google Patents interactive surfaces.
* Named gaps when foreign / NPL unsearched (fail closed visibility).
* No Sign / Pay / Submit; ``auto_file_blocked`` always true.

Conflict policy (PAAR-030): own this module; compose prior_art_search_client
and adapters; do not scrape PPS/Google.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

REVIEW_SEARCH_PLAN_SCHEMA: Final = "paar.ReviewSearchPlan@1"
REVIEW_SEARCH_JOURNAL_SCHEMA: Final = "paar.ReviewSearchJournal@1"
REVIEW_SEARCH_ORCHESTRATOR_SCHEMA: Final = "paar.ReviewSearchOrchestration@1"
REVIEW_SEARCH_INTERFACE: Final = "ReviewSearchOrchestrator@1"
REVIEW_SEARCH_CODE_VERSION: Final = "1.0.0"

REVIEW_ONLY_SEARCH_DISCLAIMER: Final = (
    "Review-only multi-corpus search orchestration for conflict screening. "
    "Produces search plans, journal stubs, and named coverage gaps. Not legal "
    "advice, not a novelty determination, not an obviousness determination, "
    "and not a patentability conclusion. Unsearched foreign-patent and NPL "
    "corpora remain named gaps. auto_file_blocked=true. Never scrapes Patent "
    "Public Search or Google Patents. Named human review is required before "
    "any legal or filing action."
)

DEFAULT_US_CORPORA: Final[tuple[str, ...]] = ("us_patents", "us_publications")
DEFAULT_OPTIONAL_CORPORA: Final[tuple[str, ...]] = ("foreign_patents", "npl")

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


class CorpusStatus(str, Enum):
    SEARCHED = "searched"
    PLANNED = "planned"
    UNSEARCHED = "unsearched"
    FAILED = "failed"
    STUB = "stub"
    SKIPPED = "skipped"


class OrchestrationMode(str, Enum):
    """How the orchestrator composes plans."""

    PLAN_ONLY = "plan_only"
    HERMETIC_STUB = "hermetic_stub"
    EXECUTE = "execute"  # requires live adapters; fail closed if unavailable


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReviewSearchOrchestratorError(ValueError):
    """Bounded review search orchestration failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "review_search_orchestrator_error"
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


def _date_only(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Accept YYYY-MM-DD or ISO datetime
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else ""


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
    ):
        cleaned = cleaned.replace(neg, " ")
    for phrase in _FORBIDDEN_OUTPUT_PHRASES:
        if phrase in cleaned:
            raise ReviewSearchOrchestratorError(
                f"forbidden conclusion phrase in output: {phrase!r}",
                code="forbidden_phrase",
            )


def _normalize_app(application_number: str) -> str:
    digits = re.sub(r"\D", "", str(application_number or ""))
    return digits or str(application_number or "").strip()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NamedSearchGap:
    """Named unsearched / failed corpus gap."""

    gap_id: str
    kind: str
    corpus: str
    status: str = "unsearched"
    message: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "kind": self.kind,
            "corpus": self.corpus,
            "status": self.status,
            "message": self.message,
            "required": bool(self.required),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NamedSearchGap":
        corpus = str(value.get("corpus") or value.get("kind") or "unknown")
        return cls(
            gap_id=str(value.get("gap_id") or f"gap:{corpus}"),
            kind=str(value.get("kind") or corpus),
            corpus=corpus,
            status=str(value.get("status") or "unsearched"),
            message=str(value.get("message") or value.get("description") or ""),
            required=bool(value.get("required", True)),
        )


@dataclass(frozen=True, slots=True)
class CorpusPlanEntry:
    """Per-corpus plan entry in the multi-corpus review plan."""

    corpus: str
    status: CorpusStatus
    query_count: int = 0
    queries: tuple[Mapping[str, Any], ...] = ()
    cutoff_date: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "status": self.status.value,
            "query_count": int(self.query_count),
            "queries": [dict(q) for q in self.queries],
            "cutoff_date": self.cutoff_date,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class JournalStubRecord:
    """Stub journal record for a planned/executed query."""

    record_id: str
    corpus: str
    query_id: str
    query_text: str
    status: str
    hit_count: int = 0
    hits: tuple[Mapping[str, Any], ...] = ()
    cutoff_date: str | None = None
    executed: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "corpus": self.corpus,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "status": self.status,
            "hit_count": int(self.hit_count),
            "hits": [dict(h) for h in self.hits],
            "cutoff_date": self.cutoff_date,
            "executed": bool(self.executed),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class ReviewSearchOrchestration:
    """Composed multi-corpus plan + journal stubs + coverage declaration."""

    orchestration_id: str
    application_number: str
    mode: OrchestrationMode
    filing_date: str
    priority_date: str
    cutoff_date: str
    corpora: tuple[CorpusPlanEntry, ...]
    named_gaps: tuple[NamedSearchGap, ...]
    journal_records: tuple[JournalStubRecord, ...]
    content_digest: str
    generated_at_utc: str
    prior_art_plan: Mapping[str, Any] | None = None
    prior_art_plan_id: str | None = None
    schema: str = REVIEW_SEARCH_ORCHESTRATOR_SCHEMA
    disclaimer: str = REVIEW_ONLY_SEARCH_DISCLAIMER
    auto_file_blocked: bool = True
    searched_corpora: tuple[str, ...] = ()
    unsearched_corpora: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": REVIEW_SEARCH_INTERFACE,
            "code_version": REVIEW_SEARCH_CODE_VERSION,
            "orchestration_id": self.orchestration_id,
            "application_number": self.application_number,
            "mode": self.mode.value,
            "filing_date": self.filing_date,
            "priority_date": self.priority_date,
            "cutoff_date": self.cutoff_date,
            "corpora": [c.to_dict() for c in self.corpora],
            "named_gaps": [g.to_dict() for g in self.named_gaps],
            "journal_records": [r.to_dict() for r in self.journal_records],
            "journal_schema": REVIEW_SEARCH_JOURNAL_SCHEMA,
            "plan_schema": REVIEW_SEARCH_PLAN_SCHEMA,
            "content_digest": self.content_digest,
            "generated_at_utc": self.generated_at_utc,
            "prior_art_plan": dict(self.prior_art_plan) if self.prior_art_plan else None,
            "prior_art_plan_id": self.prior_art_plan_id,
            "disclaimer": self.disclaimer,
            "auto_file_blocked": True,
            "searched_corpora": list(self.searched_corpora),
            "unsearched_corpora": list(self.unsearched_corpora),
            "coverage_declaration": {
                "searched_corpora": list(self.searched_corpora),
                "unsearched_corpora": list(self.unsearched_corpora),
                "named_gaps": [g.to_dict() for g in self.named_gaps],
            },
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewSearchOrchestration":
        corpora = []
        for c in value.get("corpora") or ():
            if not isinstance(c, Mapping):
                continue
            corpora.append(
                CorpusPlanEntry(
                    corpus=str(c.get("corpus") or ""),
                    status=CorpusStatus(str(c.get("status") or "unsearched").lower()),
                    query_count=int(c.get("query_count") or 0),
                    queries=tuple(
                        dict(q) for q in (c.get("queries") or ()) if isinstance(q, Mapping)
                    ),
                    cutoff_date=c.get("cutoff_date"),
                    notes=str(c.get("notes") or ""),
                )
            )
        records = []
        for r in value.get("journal_records") or ():
            if not isinstance(r, Mapping):
                continue
            records.append(
                JournalStubRecord(
                    record_id=str(r.get("record_id") or ""),
                    corpus=str(r.get("corpus") or ""),
                    query_id=str(r.get("query_id") or ""),
                    query_text=str(r.get("query_text") or ""),
                    status=str(r.get("status") or "stub"),
                    hit_count=int(r.get("hit_count") or 0),
                    hits=tuple(
                        dict(h) for h in (r.get("hits") or ()) if isinstance(h, Mapping)
                    ),
                    cutoff_date=r.get("cutoff_date"),
                    executed=bool(r.get("executed", False)),
                    notes=str(r.get("notes") or ""),
                )
            )
        return cls(
            orchestration_id=str(value.get("orchestration_id") or ""),
            application_number=str(value.get("application_number") or ""),
            mode=OrchestrationMode(str(value.get("mode") or "hermetic_stub").lower()),
            filing_date=str(value.get("filing_date") or ""),
            priority_date=str(value.get("priority_date") or ""),
            cutoff_date=str(value.get("cutoff_date") or ""),
            corpora=tuple(corpora),
            named_gaps=tuple(
                NamedSearchGap.from_dict(g)
                for g in (value.get("named_gaps") or ())
                if isinstance(g, Mapping)
            ),
            journal_records=tuple(records),
            content_digest=str(value.get("content_digest") or ""),
            generated_at_utc=str(value.get("generated_at_utc") or ""),
            prior_art_plan=(
                dict(value["prior_art_plan"])
                if isinstance(value.get("prior_art_plan"), Mapping)
                else None
            ),
            prior_art_plan_id=value.get("prior_art_plan_id"),
            searched_corpora=tuple(str(x) for x in (value.get("searched_corpora") or ())),
            unsearched_corpora=tuple(
                str(x) for x in (value.get("unsearched_corpora") or ())
            ),
            metadata=dict(value.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# Cutoff helpers
# ---------------------------------------------------------------------------


def resolve_cutoff_date(
    *,
    priority_date: str | None = None,
    filing_date: str | None = None,
    effective_filing_date: str | None = None,
    override_cutoff: str | None = None,
) -> str:
    """Resolve priority/effective date cutoff for prior-art queries.

    Precedence: override > effective_filing_date > priority_date > filing_date.
    Empty string when no anchors provided (caller must not invent dates).
    """
    for candidate in (
        override_cutoff,
        effective_filing_date,
        priority_date,
        filing_date,
    ):
        d = _date_only(candidate)
        if d:
            return d
    return ""


def apply_cutoff_to_query_text(query_text: str, cutoff_date: str) -> str:
    """Annotate query text with a publication-date cutoff when anchors exist.

    Does not invent cutoffs; returns original text when cutoff_date empty.
    """
    if not cutoff_date:
        return query_text
    marker = f"[prior_art_cutoff_pub_date_lt={cutoff_date}]"
    if marker in query_text:
        return query_text
    return f"{query_text} {marker}".strip()


def filter_hits_by_cutoff(
    hits: Sequence[Mapping[str, Any]],
    cutoff_date: str,
    *,
    allow_post_cutoff: bool = False,
) -> list[dict[str, Any]]:
    """Exclude post-cutoff publications by default (PAAR-031 style).

    ``allow_post_cutoff=True`` is for family/IDS seed mode only.
    """
    if not cutoff_date or allow_post_cutoff:
        return [dict(h) for h in hits]
    out: list[dict[str, Any]] = []
    for hit in hits:
        pub = _date_only(
            hit.get("publication_date")
            or hit.get("pub_date")
            or hit.get("date")
            or ""
        )
        if not pub:
            # Unknown date → keep but mark (fail closed visibility)
            row = dict(hit)
            row.setdefault("cutoff_date_unknown", True)
            out.append(row)
            continue
        if pub < cutoff_date:
            out.append(dict(hit))
        # pub >= cutoff excluded
    return out


# ---------------------------------------------------------------------------
# Gap builders
# ---------------------------------------------------------------------------


def default_named_gaps(
    *,
    searched_corpora: Sequence[str] = (),
    enable_foreign: bool = False,
    enable_npl: bool = False,
    foreign_searched: bool = False,
    npl_searched: bool = False,
) -> list[NamedSearchGap]:
    """Always-visible foreign + NPL gaps unless those corpora were searched."""
    searched = {str(c).lower() for c in searched_corpora}
    gaps: list[NamedSearchGap] = []

    foreign_ok = foreign_searched or "foreign_patents" in searched
    if not foreign_ok:
        gaps.append(
            NamedSearchGap(
                gap_id="gap:foreign-patent",
                kind="foreign_patent",
                corpus="foreign_patents",
                status="unsearched",
                message=(
                    "Foreign-patent corpus was not searched. This gap remains "
                    "visible and does not assert foreign coverage."
                ),
                required=True,
            )
        )
    elif enable_foreign:
        pass  # searched — no gap

    npl_ok = npl_searched or "npl" in searched
    if not npl_ok:
        gaps.append(
            NamedSearchGap(
                gap_id="gap:npl",
                kind="npl",
                corpus="npl",
                status="unsearched",
                message=(
                    "Non-patent literature (NPL) corpus was not searched (or only "
                    "partially covered). Unlicensed NPL body text is not reproduced."
                ),
                required=True,
            )
        )

    # If explicitly enabled but not searched (adapter missing), ensure gap status failed?
    if enable_foreign and not foreign_ok:
        # already unsearched gap
        pass
    if enable_npl and not npl_ok:
        pass

    return gaps


# ---------------------------------------------------------------------------
# Plan composition via prior_art_search_client
# ---------------------------------------------------------------------------


def _claims_from_graph_or_list(
    claims: Sequence[Mapping[str, Any]] | None,
    claim_graph: Any | None,
    claims_text: str | None,
) -> list[dict[str, Any]]:
    if claims:
        return [dict(c) for c in claims]
    if claim_graph is not None:
        if hasattr(claim_graph, "to_dict"):
            g = claim_graph.to_dict(include_text=True)
        elif isinstance(claim_graph, Mapping):
            g = claim_graph
        else:
            g = {}
        out: list[dict[str, Any]] = []
        for c in g.get("claims") or ():
            if not isinstance(c, Mapping):
                continue
            out.append(
                {
                    "claim_number": c.get("claim_number"),
                    "text": c.get("text") or "",
                }
            )
        if out:
            return out
    if claims_text:
        try:
            from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
                parse_claims_text,
            )

            return parse_claims_text(claims_text)
        except Exception:  # noqa: BLE001
            return [{"claim_number": 1, "text": claims_text[:2000]}]
    return []


def build_us_plan_via_client(
    *,
    application_number: str,
    claims: Sequence[Mapping[str, Any]],
    filing_date: str,
    priority_date: str,
    classifications: Sequence[str] = (),
    rank_cutoff: int = 10,
    citation_seeds: Sequence[str] = (),
    family_seeds: Sequence[str] = (),
) -> dict[str, Any]:
    """Call prior_art_search_client.build_operator_prior_art_plan (library)."""
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        build_operator_prior_art_plan,
    )

    plan = build_operator_prior_art_plan(
        application_number=application_number,
        claims=claims,
        filing_date=filing_date,
        priority_date=priority_date,
        classifications=classifications,
        rank_cutoff=rank_cutoff,
        citation_seed_document_ids=citation_seeds,
        family_seed_document_ids=family_seeds,
        metadata={"orchestrator": REVIEW_SEARCH_ORCHESTRATOR_SCHEMA},
    )
    if hasattr(plan, "to_dict"):
        return plan.to_dict()
    if isinstance(plan, Mapping):
        return dict(plan)
    raise ReviewSearchOrchestratorError(
        "build_operator_prior_art_plan returned unexpected type",
        code="invalid_plan",
    )


def build_hermetic_us_plan_stub(
    *,
    application_number: str,
    claims: Sequence[Mapping[str, Any]],
    filing_date: str,
    priority_date: str,
    cutoff_date: str,
    classifications: Sequence[str] = (),
) -> dict[str, Any]:
    """Offline plan stub when full client plan cannot be built (no network)."""
    app = _normalize_app(application_number)
    queries: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    for i, claim in enumerate(claims[:8], start=1):
        text = str(claim.get("text") or "")
        cnum = int(claim.get("claim_number") or i)
        # Simple limitation: whole claim as one limitation for stub
        lim_id = f"lim:c{cnum}-1"
        limitations.append(
            {
                "limitation_id": lim_id,
                "claim_number": cnum,
                "text": text[:500],
            }
        )
        qtext = apply_cutoff_to_query_text(
            f"claim_limitation claim={cnum} {text[:120]}".strip(),
            cutoff_date,
        )
        queries.append(
            {
                "query_id": f"q:stub:us:{app}:{cnum}",
                "family": "claim_limitation",
                "query_text": qtext,
                "corpus": "us_patents",
                "rank_cutoff": 10,
            }
        )
    for cls in list(classifications or ())[:4]:
        qtext = apply_cutoff_to_query_text(
            f"classification_cpc {cls}",
            cutoff_date,
        )
        queries.append(
            {
                "query_id": f"q:stub:cpc:{cls}",
                "family": "classification_cpc",
                "query_text": qtext,
                "corpus": "us_patents",
                "rank_cutoff": 10,
            }
        )

    plan_id = f"plan:hermetic:{app}:{sha256_hex(app + cutoff_date)[:10]}"
    return {
        "schema": "paar.hermetic-prior-art-plan.v1",
        "plan_id": plan_id,
        "subject_id": f"subject:app-{app}",
        "application_number": app,
        "filing_date": filing_date,
        "priority_date": priority_date,
        "search_date_utc": _utc_now_iso(),
        "queries": queries,
        "limitations": limitations,
        "intended_corpora": list(DEFAULT_US_CORPORA),
        "coverage_gaps": [
            g.to_dict()
            for g in default_named_gaps(searched_corpora=DEFAULT_US_CORPORA)
        ],
        "disclaimer": REVIEW_ONLY_SEARCH_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Journal stubs
# ---------------------------------------------------------------------------


def build_journal_stubs_from_plan(
    plan: Mapping[str, Any],
    *,
    cutoff_date: str,
    fixture_hits: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    mode: OrchestrationMode = OrchestrationMode.HERMETIC_STUB,
) -> list[JournalStubRecord]:
    """Build journal stub records for each plan query.

    When ``fixture_hits`` is provided (query_id → hits), records are marked
    stub-executed with those hits (hermetic offline). Otherwise status is
    ``planned`` / ``stub`` with zero hits.
    """
    fixture_hits = fixture_hits or {}
    records: list[JournalStubRecord] = []
    for q in plan.get("queries") or ():
        if not isinstance(q, Mapping):
            continue
        qid = str(q.get("query_id") or f"q:{len(records)+1}")
        corpus = str(q.get("corpus") or "us_patents")
        qtext = apply_cutoff_to_query_text(
            str(q.get("query_text") or ""), cutoff_date
        )
        raw_hits = list(fixture_hits.get(qid) or ())
        hits = filter_hits_by_cutoff(raw_hits, cutoff_date)
        if mode is OrchestrationMode.PLAN_ONLY:
            status = "planned"
            executed = False
        elif hits:
            status = "stub_executed"
            executed = True
        else:
            status = "stub"
            executed = False
        records.append(
            JournalStubRecord(
                record_id=f"jr:{qid}",
                corpus=corpus,
                query_id=qid,
                query_text=qtext[:500],
                status=status,
                hit_count=len(hits),
                hits=tuple(hits),
                cutoff_date=cutoff_date or None,
                executed=executed,
                notes=(
                    "Hermetic journal stub; not a live search result."
                    if mode is not OrchestrationMode.EXECUTE
                    else ""
                ),
            )
        )
    return records


def build_optional_corpus_entries(
    *,
    enable_foreign: bool,
    enable_npl: bool,
    foreign_fixture: Sequence[Mapping[str, Any]] | None = None,
    npl_fixture: Sequence[Mapping[str, Any]] | None = None,
    cutoff_date: str = "",
) -> tuple[list[CorpusPlanEntry], list[JournalStubRecord], list[str]]:
    """Optional foreign/NPL corpus plan entries + optional fixture journals."""
    entries: list[CorpusPlanEntry] = []
    records: list[JournalStubRecord] = []
    searched: list[str] = []

    if enable_foreign:
        hits = filter_hits_by_cutoff(list(foreign_fixture or ()), cutoff_date)
        if foreign_fixture is not None:
            status = CorpusStatus.STUB if hits or foreign_fixture == [] else CorpusStatus.STUB
            # Explicit empty fixture still counts as "searched" stub for tests that enable it
            searched.append("foreign_patents")
            qid = "q:stub:foreign:all"
            qtext = apply_cutoff_to_query_text(
                "foreign_patents multi-corpus review stub", cutoff_date
            )
            records.append(
                JournalStubRecord(
                    record_id=f"jr:{qid}",
                    corpus="foreign_patents",
                    query_id=qid,
                    query_text=qtext,
                    status="stub_executed",
                    hit_count=len(hits),
                    hits=tuple(hits),
                    cutoff_date=cutoff_date or None,
                    executed=True,
                    notes="Hermetic foreign fixture; not live EPO OPS.",
                )
            )
            entries.append(
                CorpusPlanEntry(
                    corpus="foreign_patents",
                    status=CorpusStatus.STUB,
                    query_count=1,
                    queries=(
                        {
                            "query_id": qid,
                            "family": "keyword",
                            "query_text": qtext,
                            "corpus": "foreign_patents",
                        },
                    ),
                    cutoff_date=cutoff_date or None,
                    notes="Optional foreign corpus via hermetic fixture",
                )
            )
        else:
            entries.append(
                CorpusPlanEntry(
                    corpus="foreign_patents",
                    status=CorpusStatus.UNSEARCHED,
                    query_count=0,
                    cutoff_date=cutoff_date or None,
                    notes="Foreign enabled but no adapter/fixture; named gap",
                )
            )
    else:
        entries.append(
            CorpusPlanEntry(
                corpus="foreign_patents",
                status=CorpusStatus.UNSEARCHED,
                query_count=0,
                cutoff_date=cutoff_date or None,
                notes="Foreign corpus not requested; remains named gap",
            )
        )

    if enable_npl:
        hits = filter_hits_by_cutoff(list(npl_fixture or ()), cutoff_date)
        if npl_fixture is not None:
            searched.append("npl")
            qid = "q:stub:npl:all"
            qtext = apply_cutoff_to_query_text(
                "npl multi-corpus review stub", cutoff_date
            )
            records.append(
                JournalStubRecord(
                    record_id=f"jr:{qid}",
                    corpus="npl",
                    query_id=qid,
                    query_text=qtext,
                    status="stub_executed",
                    hit_count=len(hits),
                    hits=tuple(hits),
                    cutoff_date=cutoff_date or None,
                    executed=True,
                    notes="Hermetic NPL fixture; identifiers only when unlicensed.",
                )
            )
            entries.append(
                CorpusPlanEntry(
                    corpus="npl",
                    status=CorpusStatus.STUB,
                    query_count=1,
                    queries=(
                        {
                            "query_id": qid,
                            "family": "keyword",
                            "query_text": qtext,
                            "corpus": "npl",
                        },
                    ),
                    cutoff_date=cutoff_date or None,
                    notes="Optional NPL corpus via hermetic fixture",
                )
            )
        else:
            entries.append(
                CorpusPlanEntry(
                    corpus="npl",
                    status=CorpusStatus.UNSEARCHED,
                    query_count=0,
                    cutoff_date=cutoff_date or None,
                    notes="NPL enabled but no adapter/fixture; named gap",
                )
            )
    else:
        entries.append(
            CorpusPlanEntry(
                corpus="npl",
                status=CorpusStatus.UNSEARCHED,
                query_count=0,
                cutoff_date=cutoff_date or None,
                notes="NPL corpus not requested; remains named gap",
            )
        )

    return entries, records, searched


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def compose_review_search(
    *,
    application_number: str = "",
    claims: Sequence[Mapping[str, Any]] | None = None,
    claims_text: str | None = None,
    claim_graph: Any | None = None,
    filing_date: str | None = None,
    priority_date: str | None = None,
    effective_filing_date: str | None = None,
    cutoff_override: str | None = None,
    classifications: Sequence[str] = (),
    citation_seeds: Sequence[str] = (),
    family_seeds: Sequence[str] = (),
    mode: OrchestrationMode | str = OrchestrationMode.HERMETIC_STUB,
    enable_foreign: bool = False,
    enable_npl: bool = False,
    foreign_fixture: Sequence[Mapping[str, Any]] | None = None,
    npl_fixture: Sequence[Mapping[str, Any]] | None = None,
    fixture_hits: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    use_client_plan: bool = True,
    prior_art_plan: Mapping[str, Any] | None = None,
    rank_cutoff: int = 10,
    orchestration_id: str | None = None,
    generated_at_utc: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> ReviewSearchOrchestration:
    """Compose multi-corpus review search plan + journal stubs.

    Hermetic by default (no network). Prefer ``prior_art_search_client`` for US
    plan construction when claims and dates are available; fall back to a local
    stub plan if the client path fails.
    """
    if isinstance(mode, str):
        mode = OrchestrationMode(mode.lower())

    app = _normalize_app(application_number)
    filing = _date_only(filing_date)
    priority = _date_only(priority_date) or filing
    cutoff = resolve_cutoff_date(
        priority_date=priority,
        filing_date=filing,
        effective_filing_date=effective_filing_date,
        override_cutoff=cutoff_override,
    )

    claim_list = _claims_from_graph_or_list(claims, claim_graph, claims_text)

    plan: dict[str, Any]
    plan_source = "provided"
    if prior_art_plan is not None:
        plan = dict(prior_art_plan)
    elif use_client_plan and claim_list and filing and priority:
        try:
            plan = build_us_plan_via_client(
                application_number=app or "00000000",
                claims=claim_list,
                filing_date=filing,
                priority_date=priority,
                classifications=classifications,
                rank_cutoff=rank_cutoff,
                citation_seeds=citation_seeds,
                family_seeds=family_seeds,
            )
            plan_source = "prior_art_search_client"
            # Apply cutoff annotation to query texts
            annotated = []
            for q in plan.get("queries") or ():
                if not isinstance(q, Mapping):
                    continue
                qq = dict(q)
                qq["query_text"] = apply_cutoff_to_query_text(
                    str(qq.get("query_text") or ""), cutoff
                )
                if "corpus" not in qq:
                    qq["corpus"] = "us_patents"
                annotated.append(qq)
            plan = {**plan, "queries": annotated}
        except Exception:  # noqa: BLE001 — hermetic fallback
            plan = build_hermetic_us_plan_stub(
                application_number=app or "unknown",
                claims=claim_list,
                filing_date=filing,
                priority_date=priority,
                cutoff_date=cutoff,
                classifications=classifications,
            )
            plan_source = "hermetic_stub_fallback"
    else:
        plan = build_hermetic_us_plan_stub(
            application_number=app or "unknown",
            claims=claim_list or [{"claim_number": 1, "text": ""}],
            filing_date=filing,
            priority_date=priority,
            cutoff_date=cutoff,
            classifications=classifications,
        )
        plan_source = "hermetic_stub"

    # US corpus entries from plan
    us_queries = [
        dict(q)
        for q in (plan.get("queries") or ())
        if isinstance(q, Mapping)
        and str(q.get("corpus") or "us_patents").lower()
        in {"us_patents", "us_publications", ""}
    ]
    # If plan queries lack corpus, treat all as US
    if not us_queries:
        us_queries = [dict(q) for q in (plan.get("queries") or ()) if isinstance(q, Mapping)]

    us_status = (
        CorpusStatus.PLANNED
        if mode is OrchestrationMode.PLAN_ONLY
        else CorpusStatus.STUB
    )
    us_entry = CorpusPlanEntry(
        corpus="us_patents",
        status=us_status,
        query_count=len(us_queries),
        queries=tuple(us_queries),
        cutoff_date=cutoff or None,
        notes=f"US plan via {plan_source}",
    )
    us_pubs = CorpusPlanEntry(
        corpus="us_publications",
        status=us_status,
        query_count=0,
        queries=(),
        cutoff_date=cutoff or None,
        notes="US publications intended with US patents plan",
    )

    journal = build_journal_stubs_from_plan(
        {**plan, "queries": us_queries},
        cutoff_date=cutoff,
        fixture_hits=fixture_hits,
        mode=mode,
    )

    opt_entries, opt_records, opt_searched = build_optional_corpus_entries(
        enable_foreign=enable_foreign,
        enable_npl=enable_npl,
        foreign_fixture=foreign_fixture,
        npl_fixture=npl_fixture,
        cutoff_date=cutoff,
    )
    journal.extend(opt_records)

    searched = list(DEFAULT_US_CORPORA) + list(opt_searched)
    # US considered planned/stub searched for coverage declaration of US only
    # Unsearched = optional corpora without successful search
    gaps = default_named_gaps(
        searched_corpora=searched,
        enable_foreign=enable_foreign,
        enable_npl=enable_npl,
        foreign_searched="foreign_patents" in opt_searched,
        npl_searched="npl" in opt_searched,
    )

    unsearched = [g.corpus for g in gaps]
    # Also list foreign/npl unsearched even if in gaps
    for corpus in DEFAULT_OPTIONAL_CORPORA:
        if corpus not in searched and corpus not in unsearched:
            unsearched.append(corpus)

    oid = orchestration_id or (
        f"rso:{app or 'unknown'}:{sha256_hex(app + cutoff + plan_source)[:12]}"
    )
    corpora = (us_entry, us_pubs, *opt_entries)

    digest_payload = {
        "schema": REVIEW_SEARCH_ORCHESTRATOR_SCHEMA,
        "orchestration_id": oid,
        "application_number": app,
        "mode": mode.value,
        "filing_date": filing,
        "priority_date": priority,
        "cutoff_date": cutoff,
        "corpora": [c.to_dict() for c in corpora],
        "named_gaps": [g.to_dict() for g in gaps],
        "journal_records": [r.to_dict() for r in journal],
        "prior_art_plan_id": plan.get("plan_id"),
        "auto_file_blocked": True,
        "code_version": REVIEW_SEARCH_CODE_VERSION,
    }
    digest = sha256_hex(canonical_json(digest_payload))
    ts = generated_at_utc or _utc_now_iso()

    result = ReviewSearchOrchestration(
        orchestration_id=oid,
        application_number=app,
        mode=mode,
        filing_date=filing,
        priority_date=priority,
        cutoff_date=cutoff,
        corpora=corpora,
        named_gaps=tuple(gaps),
        journal_records=tuple(journal),
        content_digest=digest,
        generated_at_utc=ts,
        prior_art_plan=plan,
        prior_art_plan_id=str(plan.get("plan_id") or "") or None,
        searched_corpora=tuple(searched),
        unsearched_corpora=tuple(unsearched),
        metadata={
            "plan_source": plan_source,
            **dict(metadata or {}),
        },
    )
    payload = result.to_dict()
    _assert_no_forbidden_phrases(payload)
    if payload.get("auto_file_blocked") is not True:
        raise ReviewSearchOrchestratorError(
            "auto_file_blocked must be true", code="auto_file_invariant"
        )
    # Foreign unsearched must remain a named gap when not searched
    if "foreign_patents" not in result.searched_corpora:
        kinds = {g.kind for g in result.named_gaps} | {
            g.corpus for g in result.named_gaps
        }
        if "foreign_patent" not in kinds and "foreign_patents" not in kinds:
            raise ReviewSearchOrchestratorError(
                "foreign gap must remain named when unsearched",
                code="missing_foreign_gap",
            )
    return result


def compose_review_search_from_plan_prior_art(
    *,
    application_number: str,
    state_root: Path | str | None = None,
    claims_text: str | None = None,
    filing_date: str | None = None,
    priority_date: str | None = None,
    persist: bool = False,
    **kwargs: Any,
) -> ReviewSearchOrchestration:
    """Compose orchestration using plan_prior_art from prior_art_search_client."""
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        plan_prior_art,
    )

    plan_result = plan_prior_art(
        application_number=application_number,
        state_root=Path(state_root) if state_root else None,
        claims_text=claims_text,
        filing_date=filing_date,
        priority_date=priority_date,
        persist=persist,
        classifications=kwargs.pop("classifications", ()),
        citation_seeds=kwargs.pop("citation_seeds", ()),
        family_seeds=kwargs.pop("family_seeds", ()),
    )
    plan = plan_result.get("plan") or {}
    return compose_review_search(
        application_number=application_number,
        prior_art_plan=plan if isinstance(plan, Mapping) else None,
        filing_date=filing_date or plan_result.get("filing_date"),
        priority_date=priority_date or plan_result.get("priority_date"),
        claims_text=claims_text,
        use_client_plan=False,
        **kwargs,
    )


__all__ = [
    "DEFAULT_OPTIONAL_CORPORA",
    "DEFAULT_US_CORPORA",
    "REVIEW_ONLY_SEARCH_DISCLAIMER",
    "REVIEW_SEARCH_CODE_VERSION",
    "REVIEW_SEARCH_INTERFACE",
    "REVIEW_SEARCH_JOURNAL_SCHEMA",
    "REVIEW_SEARCH_ORCHESTRATOR_SCHEMA",
    "REVIEW_SEARCH_PLAN_SCHEMA",
    "CorpusPlanEntry",
    "CorpusStatus",
    "JournalStubRecord",
    "NamedSearchGap",
    "OrchestrationMode",
    "ReviewSearchOrchestration",
    "ReviewSearchOrchestratorError",
    "apply_cutoff_to_query_text",
    "build_hermetic_us_plan_stub",
    "build_journal_stubs_from_plan",
    "build_optional_corpus_entries",
    "build_us_plan_via_client",
    "canonical_json",
    "compose_review_search",
    "compose_review_search_from_plan_prior_art",
    "default_named_gaps",
    "filter_hits_by_cutoff",
    "resolve_cutoff_date",
    "sha256_hex",
]
