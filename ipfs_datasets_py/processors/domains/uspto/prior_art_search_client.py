"""Operator prior-art search client for distinguishing applications.

Wires PATLAW-094 (plans + claim charts) and PATLAW-148 (runtime + journal)
into the portfolio state tree so operators can:

1. Build a reproducible search plan from claim text + filing/priority dates
2. Execute public U.S. prior-art search via local snapshot and/or ODP
3. Persist plan, journal, coverage declaration, and source-linked claim chart
4. Review top candidate hits for claim-limitation distinguishability drafting

Hard rules
----------
* Never asserts novelty, obviousness, or patentability.
* Foreign-patent and NPL coverage gaps remain visible unless a licensed named
  adapter actually ran (none ship by default).
* Does not scrape Patent Center, sign, pay, or file.
* ODP uses ``USPTO_ODP_API_KEY`` from the environment only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

PRIOR_ART_CLIENT_SCHEMA: Final = "patlaw-prior-art-search-client-v1"
PRIOR_ART_RUN_MANIFEST: Final = "run_manifest.json"

CLAIM_NUM_RE = re.compile(
    r"(?im)^\s*(?:claim\s+)?(\d+)[\.\):]\s*(.+?)(?=^\s*(?:claim\s+)?\d+[\.\):]|\Z)",
    re.DOTALL,
)

PRIOR_ART_DISCLAIMER_SHORT: Final = (
    "Review-only prior-art search plan/journal/claim chart. "
    "Not a novelty, obviousness, or patentability determination. "
    "Foreign-patent and NPL gaps remain visible when unsearched. "
    "Not legal advice; not an IDS filing."
)


class PriorArtSearchClientError(PortfolioAutomationError):
    """Fail-closed prior-art search client error."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def prior_art_root(state_root: Path | None = None) -> Path:
    root = Path(state_root) if state_root is not None else default_state_root()
    return root / "prior_art"


def prior_art_app_dir(application_number: str, *, state_root: Path | None = None) -> Path:
    app = _normalize_app(application_number)
    return prior_art_root(state_root) / app


def _normalize_app(application_number: str) -> str:
    app = re.sub(r"[^0-9A-Za-z]", "", str(application_number or "").strip())
    if not app:
        raise PriorArtSearchClientError(
            "application_number is required", code="invalid_application_number"
        )
    return app


def _write_json(path: Path, payload: Mapping[str, Any], *, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise PriorArtSearchClientError(
            f"expected JSON object in {path}", code="invalid_json"
        )
    return dict(data)


# ---------------------------------------------------------------------------
# Claim + temporal loading
# ---------------------------------------------------------------------------


def parse_claims_text(text: str) -> list[dict[str, Any]]:
    """Parse numbered claim text into ``[{claim_number, claim_text}, ...]``."""
    body = str(text or "").strip()
    if not body:
        return []
    matches = list(CLAIM_NUM_RE.finditer(body))
    if matches:
        out: list[dict[str, Any]] = []
        for m in matches:
            ctext = " ".join(m.group(2).split()).strip()
            if ctext:
                out.append({"claim_number": int(m.group(1)), "claim_text": ctext})
        if out:
            return out
    # Single unnumbered claim block
    collapsed = " ".join(body.split()).strip()
    if collapsed:
        return [{"claim_number": 1, "claim_text": collapsed}]
    return []


def load_claims(
    *,
    claims: Sequence[Mapping[str, Any]] | None = None,
    claims_file: str | Path | None = None,
    claims_text: str | None = None,
) -> list[dict[str, Any]]:
    """Load claims from explicit list, JSON file, or free-text."""
    if claims:
        out: list[dict[str, Any]] = []
        for item in claims:
            if not isinstance(item, Mapping):
                raise PriorArtSearchClientError(
                    "each claim must be a mapping", code="invalid_claim"
                )
            out.append(
                {
                    "claim_number": int(item["claim_number"]),
                    "claim_text": str(item["claim_text"]).strip(),
                }
            )
        if out:
            return out

    if claims_file:
        path = Path(claims_file).expanduser().resolve()
        if not path.is_file():
            raise PriorArtSearchClientError(
                f"claims file not found: {path}", code="claims_file_missing"
            )
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".json", ".jsonl"}:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PriorArtSearchClientError(
                    f"invalid claims JSON: {exc}", code="invalid_claims_json"
                ) from exc
            if isinstance(payload, Mapping):
                nested = payload.get("claims") or payload.get("claim_list")
                if isinstance(nested, list):
                    return load_claims(claims=nested)
                # Single claim object
                if "claim_text" in payload:
                    return load_claims(claims=[payload])
            if isinstance(payload, list):
                return load_claims(claims=payload)
            raise PriorArtSearchClientError(
                "claims JSON must be a list or object with claims[]",
                code="invalid_claims_json",
            )
        parsed = parse_claims_text(raw)
        if not parsed:
            raise PriorArtSearchClientError(
                f"no claims parsed from {path}", code="empty_claims"
            )
        return parsed

    if claims_text:
        parsed = parse_claims_text(claims_text)
        if not parsed:
            raise PriorArtSearchClientError(
                "no claims parsed from claims_text", code="empty_claims"
            )
        return parsed

    raise PriorArtSearchClientError(
        "pass claims, --claims-file, or --claims-text",
        code="missing_claims",
    )


def load_export_temporal_anchors(
    application_number: str,
    *,
    state_root: Path | None = None,
) -> dict[str, str]:
    """Pull filing/priority/title from portfolio export package if present."""
    app = _normalize_app(application_number)
    root = Path(state_root) if state_root is not None else default_state_root()
    candidates = [
        root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "application_data.json",
        root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "application_data_v2.json",
        root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "public_application_data.json",
        root
        / "exports"
        / app
        / "public_odp_wrapper"
        / "application_data.json",
    ]
    out: dict[str, str] = {"application_number": app}
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = _read_json(path)
        except Exception:
            continue
        meta = data.get("applicationMetaData") or data.get("application_meta_data") or {}
        if not isinstance(meta, Mapping):
            meta = {}
        filing = _date_only(
            meta.get("filingDate")
            or meta.get("filing_date")
            or data.get("filingDate")
            or data.get("filing_date")
        )
        effective = _date_only(
            meta.get("effectiveFilingDate")
            or meta.get("effective_filing_date")
            or filing
        )
        # Earliest parent continuity filing as priority candidate
        priority = effective or filing
        parents = data.get("parentContinuityBag") or data.get("parent_continuity") or []
        if isinstance(parents, list):
            for parent in parents:
                if not isinstance(parent, Mapping):
                    continue
                pdate = _date_only(parent.get("filingDate") or parent.get("filing_date"))
                if pdate and (not priority or pdate < priority):
                    priority = pdate
        title = str(
            meta.get("inventionTitle")
            or meta.get("invention_title")
            or data.get("inventionTitle")
            or ""
        ).strip()
        if filing:
            out["filing_date"] = filing
        if priority:
            out["priority_date"] = priority
        if title:
            out["invention_title"] = title
        out["source_path"] = str(path)
        break
    return out


def _date_only(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # ISO datetime → date
    if "T" in text:
        text = text.split("T", 1)[0]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    return ""


def _as_of_utc(value: str | None = None) -> str:
    text = (value or utc_now_iso()).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return text


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def build_operator_prior_art_plan(
    *,
    application_number: str,
    claims: Sequence[Mapping[str, Any]],
    filing_date: str,
    priority_date: str | None = None,
    search_date_utc: str | None = None,
    classifications: Sequence[str] = (),
    rank_cutoff: int = 10,
    citation_seed_document_ids: Sequence[str] = (),
    family_seed_document_ids: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
) -> Any:
    """Build a PATLAW-094 :class:`PriorArtSearchPlan` for an application."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        SearchCorpus,
        build_prior_art_search_plan,
    )
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        DisclosureClass,
        PreRankingFilters,
    )

    app = _normalize_app(application_number)
    claim_list = load_claims(claims=claims)
    filing = _date_only(filing_date) or str(filing_date).strip()
    priority = _date_only(priority_date) or filing
    search_ts = _as_of_utc(search_date_utc)

    if not filing:
        raise PriorArtSearchClientError(
            "filing_date is required (YYYY-MM-DD)", code="missing_filing_date"
        )
    if not priority:
        raise PriorArtSearchClientError(
            "priority_date is required (YYYY-MM-DD)", code="missing_priority_date"
        )

    filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc=search_ts,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=True,
        filter_receipt_id=f"filter:prior-art-client:{app}",
    )

    meta = {
        "application_number": app,
        "operator_client": PRIOR_ART_CLIENT_SCHEMA,
        **{
            str(k): str(v)
            for k, v in dict(metadata or {}).items()
            if str(v or "").strip()
        },
    }
    return build_prior_art_search_plan(
        subject_id=f"subject:app-{app}",
        filing_date=filing,
        priority_date=priority,
        search_date_utc=search_ts,
        claims=claim_list,
        classifications=list(classifications or ()),
        rank_cutoff=int(rank_cutoff),
        intended_corpora=(
            SearchCorpus.US_PATENTS,
            SearchCorpus.US_PUBLICATIONS,
        ),
        filters=filters,
        citation_seed_document_ids=list(citation_seed_document_ids or ()),
        family_seed_document_ids=list(family_seed_document_ids or ()),
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Runtime assembly
# ---------------------------------------------------------------------------


def build_local_snapshot_from_docs(
    documents: Sequence[Any],
    *,
    as_of_utc: str | None = None,
    edges: Sequence[Any] = (),
) -> Any:
    """Build a local public-patent snapshot adapter from index documents."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
        build_local_snapshot_adapter,
    )
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        DisclosureClass,
        PreRankingFilters,
    )

    as_of = _as_of_utc(as_of_utc)
    filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc=as_of,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=False,
        filter_receipt_id="filter:prior-art-local-snapshot",
    )
    return build_local_snapshot_adapter(
        list(documents),
        filters=filters,
        edges=list(edges or ()),
    )


def load_local_snapshot_documents(path: str | Path) -> list[Any]:
    """Load PatentIndexDocument-compatible rows from JSON/JSONL."""
    from ipfs_datasets_py.processors.domains.patent.indexing import PatentIndexDocument
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        DisclosureClass,
        SourceLink,
        SourceSpan,
    )

    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise PriorArtSearchClientError(
            f"local snapshot not found: {p}", code="local_snapshot_missing"
        )
    raw = p.read_text(encoding="utf-8")
    rows: list[Any]
    if p.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        payload = json.loads(raw)
        if isinstance(payload, Mapping):
            rows = list(payload.get("documents") or payload.get("docs") or [])
            if not rows and payload.get("document_id"):
                rows = [payload]
        elif isinstance(payload, list):
            rows = payload
        else:
            raise PriorArtSearchClientError(
                "local snapshot JSON must be list or {documents:[]}",
                code="invalid_local_snapshot",
            )

    docs: list[Any] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if "field_values" in row:
            docs.append(PatentIndexDocument.from_dict(row))
            continue
        doc_id = str(row.get("document_id") or row.get("id") or "").strip()
        title = str(row.get("title") or row.get("inventionTitle") or doc_id).strip()
        abstract = str(row.get("abstract") or row.get("description") or "").strip()
        claims = str(row.get("claims") or row.get("claim_text") or "").strip()
        cpc = str(row.get("cpc") or row.get("classification") or "").strip()
        if not doc_id:
            continue
        source_cid = str(row.get("source_cid") or f"cid:{doc_id}")
        text_len = max(len(title) + len(abstract) + len(claims), 1)
        docs.append(
            PatentIndexDocument(
                document_id=doc_id,
                field_values={
                    "title": title[:2000],
                    "abstract": abstract[:8000],
                    "claims": claims[:20000],
                    "cpc": cpc[:256],
                    "description": (abstract or claims or title)[:20000],
                },
                source_links=(
                    SourceLink(
                        source_cid=source_cid,
                        artifact_id=f"artifact:{doc_id}",
                        span=SourceSpan(start=0, end=min(text_len, 400), unit="char"),
                    ),
                ),
                disclosure=DisclosureClass.PUBLIC_OFFICIAL,
                tenant_id="tenant-public",
                publication_utc=_to_iso_or_none(row.get("publication_utc") or row.get("publicationDate")),
                metadata={
                    str(k): str(v)
                    for k, v in {
                        "application_number": row.get("application_number")
                        or row.get("applicationNumberText")
                        or "",
                        "patent_number": row.get("patent_number") or "",
                    }.items()
                    if v
                },
            )
        )
    if not docs:
        raise PriorArtSearchClientError(
            f"no documents loaded from {p}", code="empty_local_snapshot"
        )
    return docs


def _to_iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        if text.endswith("Z"):
            return text[:-1] + "+00:00"
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return f"{text}T00:00:00+00:00"
    return None


def build_odp_adapter_live(
    *,
    api_key: str | None = None,
    base_url: str = "https://api.uspto.gov",
    max_pages: int = 1,
) -> Any:
    """Build a live ODP public search adapter (requires USPTO_ODP_API_KEY)."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
        OdpPublicSearchAdapter,
    )
    from ipfs_datasets_py.processors.domains.uspto.providers.base import (
        ApiKeySecret,
        RetryPolicy,
    )
    from ipfs_datasets_py.processors.domains.uspto.providers.http_transport import (
        BoundedHttpTransport,
        BoundedTransportLimits,
        HostAllowlistPolicy,
    )
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
        PatentFileWrapperClient,
    )

    key = (api_key or os.environ.get("USPTO_ODP_API_KEY") or "").strip()
    if not key:
        raise PriorArtSearchClientError(
            "USPTO_ODP_API_KEY not set (required for --odp search)",
            code="missing_odp_key",
        )
    transport = BoundedHttpTransport(
        policy=HostAllowlistPolicy.odp_default(),
        limits=BoundedTransportLimits(),
    )
    client = PatentFileWrapperClient(
        transport=transport,
        api_key=ApiKeySecret(key),
        base_url=base_url,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.5),
    )
    return OdpPublicSearchAdapter(client=client, max_pages=int(max_pages))


def build_operator_runtime(
    *,
    use_odp: bool = False,
    odp_adapter: Any | None = None,
    local_adapter: Any | None = None,
    local_snapshot_path: str | Path | None = None,
    max_odp_pages: int = 1,
) -> Any:
    """Assemble PriorArtSearchRuntime from optional local + ODP adapters."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
        build_public_prior_art_runtime,
    )

    local = local_adapter
    if local is None and local_snapshot_path:
        docs = load_local_snapshot_documents(local_snapshot_path)
        local = build_local_snapshot_from_docs(docs)

    odp = odp_adapter
    if odp is None and use_odp:
        odp = build_odp_adapter_live(max_pages=max_odp_pages)

    if local is None and odp is None:
        raise PriorArtSearchClientError(
            "no search backend: pass --odp and/or --local-snapshot",
            code="no_search_backend",
        )
    return build_public_prior_art_runtime(local_adapter=local, odp_adapter=odp)


# ---------------------------------------------------------------------------
# Journal → claim chart projection
# ---------------------------------------------------------------------------


def claim_chart_from_journal(
    plan: Any,
    journal: Any,
    *,
    chart_id: str | None = None,
) -> Any:
    """Project search-journal hits into a source-linked claim chart."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        QueryFamily,
        RankedPassageHit,
        SearchCorpus,
        SearchQuerySpec,
        build_claim_chart,
        build_claim_chart_entries_from_logs,
        record_dated_query_log,
    )

    query_by_id = {q.query_id: q for q in plan.queries}
    logs = []
    for rec in journal.records:
        qspec = query_by_id.get(rec.query_id)
        if qspec is None:
            # Synthetic query for journal-only records
            default_family = (
                plan.queries[0].family if plan.queries else QueryFamily.KEYWORD
            )
            qspec = SearchQuerySpec(
                query_id=rec.query_id,
                query_text=rec.query_text,
                family=default_family,
                intended_corpora=(SearchCorpus.US_PATENTS,),
                rank_cutoff=int(
                    getattr(rec, "rank_cutoff", None) or plan.rank_cutoff or 10
                ),
                related_limitation_ids=(),
            )
        hits: list[RankedPassageHit] = []
        for hit in rec.hits or ():
            links = tuple(hit.source_links or ())
            if not links:
                continue
            # Ensure at least one span for chart contract
            fixed = []
            for link in links:
                if getattr(link, "span", None) is None:
                    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
                        SourceLink,
                        SourceSpan,
                    )

                    fixed.append(
                        SourceLink(
                            source_cid=link.source_cid,
                            artifact_id=link.artifact_id,
                            span=SourceSpan(start=0, end=1, unit="char"),
                            source_receipt_id=getattr(link, "source_receipt_id", None),
                            authority_tier=getattr(link, "authority_tier", None),
                        )
                    )
                else:
                    fixed.append(link)
            try:
                hits.append(
                    RankedPassageHit(
                        document_id=hit.document_id,
                        rank=int(hit.rank),
                        score=float(hit.score),
                        source_links=tuple(fixed),
                        passage_excerpt=getattr(hit, "passage_excerpt", None),
                        family=str((hit.metadata or {}).get("family") or "fusion"),
                        metadata={
                            str(k): str(v)
                            for k, v in dict(getattr(hit, "metadata", None) or {}).items()
                        },
                    )
                )
            except Exception:
                continue
        logs.append(
            record_dated_query_log(
                qspec,
                hits,
                search_date_utc=plan.search_date_utc,
                corpus=SearchCorpus.US_PATENTS,
                filters=plan.filters,
                log_id=f"log:{journal.journal_id}:{rec.query_id}",
            )
        )

    entries = build_claim_chart_entries_from_logs(
        query_logs=logs,
        limitations=plan.limitations,
    )
    return build_claim_chart(
        subject_id=plan.subject_id,
        filing_date=plan.filing_date,
        priority_date=plan.priority_date,
        search_date_utc=plan.search_date_utc,
        entries=entries,
        limitations=plan.limitations,
        coverage_gaps=plan.coverage_gaps,
        plan_id=plan.plan_id,
        chart_id=chart_id,
        metadata={
            "journal_id": journal.journal_id,
            "source": "prior_art_search_client",
        },
    )


def distinguishability_summary(
    plan: Any,
    journal: Any,
    chart: Any | None,
    coverage: Any | None,
    *,
    max_hits: int = 12,
) -> dict[str, Any]:
    """Human-review summary: candidate hits + gaps (no patentability conclusions)."""
    hit_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rec in journal.records:
        outcome = rec.outcome.value if hasattr(rec.outcome, "value") else str(rec.outcome)
        for hit in rec.hits or ():
            doc_id = hit.document_id
            if doc_id in seen:
                continue
            seen.add(doc_id)
            hit_rows.append(
                {
                    "document_id": doc_id,
                    "rank": hit.rank,
                    "score": round(float(hit.score), 6),
                    "query_id": rec.query_id,
                    "query_text": rec.query_text[:200],
                    "outcome": outcome,
                    "database": rec.database.value
                    if hasattr(rec.database, "value")
                    else str(rec.database),
                    "adapter": rec.adapter.adapter_name
                    if getattr(rec, "adapter", None)
                    else None,
                    "identifiers": dict(getattr(hit, "identifiers", None) or {}),
                    "source_cids": [
                        link.source_cid for link in (hit.source_links or ())
                    ],
                    "passage_excerpt": (getattr(hit, "passage_excerpt", None) or "")[
                        :400
                    ],
                }
            )
            if len(hit_rows) >= max_hits:
                break
        if len(hit_rows) >= max_hits:
            break

    gaps: list[dict[str, Any]] = []
    if coverage is not None:
        for g in coverage.named_gaps or ():
            gaps.append(g.to_dict() if hasattr(g, "to_dict") else dict(g))
    else:
        for g in plan.coverage_gaps or ():
            gaps.append(g.to_dict() if hasattr(g, "to_dict") else dict(g))

    limitation_hints = [
        {
            "limitation_id": lim.limitation_id,
            "claim_number": lim.claim_number,
            "candidate_text": str(lim.text)[:240],
            "role": "candidate",
        }
        for lim in (plan.limitations or ())[:24]
    ]

    chart_entry_count = len(chart.entries) if chart is not None else 0
    query_outcomes = []
    for rec in journal.records:
        query_outcomes.append(
            {
                "query_id": rec.query_id,
                "outcome": rec.outcome.value
                if hasattr(rec.outcome, "value")
                else str(rec.outcome),
                "hit_count": len(rec.hits or ()),
                "claims_corpus_searched": bool(
                    getattr(rec, "claims_corpus_searched", False)
                ),
                "error_code": getattr(rec, "error_code", None),
            }
        )

    return {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "purpose": (
            "Candidate prior-art hits and claim-limitation map for human "
            "distinguishability drafting. Does not determine patentability."
        ),
        "subject_id": plan.subject_id,
        "plan_id": plan.plan_id,
        "journal_id": journal.journal_id,
        "query_count": len(plan.queries),
        "limitation_count": len(plan.limitations or ()),
        "keyword_count": len(plan.keywords or ()),
        "chart_entry_count": chart_entry_count,
        "candidate_hits": hit_rows,
        "limitations": limitation_hints,
        "query_outcomes": query_outcomes,
        "coverage_gaps": gaps,
        "searched_corpora": [
            c.value if hasattr(c, "value") else str(c)
            for c in (getattr(journal, "searched_corpora", None) or ())
        ],
        "unsearched_corpora": [
            c.value if hasattr(c, "value") else str(c)
            for c in (getattr(journal, "unsearched_corpora", None) or ())
        ],
        "review_tips": [
            "Compare each independent-claim limitation to candidate hit passages.",
            "Draft remarks that emphasize claim elements absent from cited hits.",
            "Foreign patents and NPL remain unsearched gaps unless licensed adapters ran.",
            "Confirm critical hits in Patent Public Search before IDS or response filing.",
            "Do not treat empty hit lists as proof of novelty.",
        ],
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
    }


# ---------------------------------------------------------------------------
# Full operator run
# ---------------------------------------------------------------------------


@dataclass
class PriorArtRunResult:
    """Artifacts written for one prior-art operator run."""

    ok: bool
    run_id: str
    run_dir: str
    application_number: str
    plan_id: str | None = None
    journal_id: str | None = None
    chart_id: str | None = None
    coverage_id: str | None = None
    paths: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    disclaimer: str = PRIOR_ART_DISCLAIMER_SHORT

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PRIOR_ART_CLIENT_SCHEMA,
            "ok": self.ok,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "application_number": self.application_number,
            "plan_id": self.plan_id,
            "journal_id": self.journal_id,
            "chart_id": self.chart_id,
            "coverage_id": self.coverage_id,
            "paths": dict(self.paths),
            "summary": dict(self.summary),
            "error": self.error,
            "disclaimer": self.disclaimer,
            "generated_at_utc": utc_now_iso(),
        }


def plan_prior_art(
    *,
    application_number: str,
    state_root: Path | None = None,
    claims: Sequence[Mapping[str, Any]] | None = None,
    claims_file: str | Path | None = None,
    claims_text: str | None = None,
    filing_date: str | None = None,
    priority_date: str | None = None,
    classifications: Sequence[str] = (),
    rank_cutoff: int = 10,
    citation_seeds: Sequence[str] = (),
    family_seeds: Sequence[str] = (),
    persist: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build (and optionally persist) a prior-art search plan only."""
    app = _normalize_app(application_number)
    root = Path(state_root) if state_root is not None else default_state_root()
    claim_list = load_claims(
        claims=claims, claims_file=claims_file, claims_text=claims_text
    )
    anchors = load_export_temporal_anchors(app, state_root=root)
    filing = _date_only(filing_date) or anchors.get("filing_date") or ""
    priority = (
        _date_only(priority_date)
        or anchors.get("priority_date")
        or filing
    )
    if not filing:
        raise PriorArtSearchClientError(
            "filing_date required (pass --filing-date or export application_data first)",
            code="missing_filing_date",
        )

    plan = build_operator_prior_art_plan(
        application_number=app,
        claims=claim_list,
        filing_date=filing,
        priority_date=priority,
        classifications=classifications,
        rank_cutoff=rank_cutoff,
        citation_seed_document_ids=citation_seeds,
        family_seed_document_ids=family_seeds,
        metadata={
            "invention_title": anchors.get("invention_title") or "",
            "anchor_source": anchors.get("source_path") or "cli",
        },
    )

    result: dict[str, Any] = {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "action": "plan",
        "application_number": app,
        "plan_id": plan.plan_id,
        "subject_id": plan.subject_id,
        "filing_date": plan.filing_date,
        "priority_date": plan.priority_date,
        "search_date_utc": plan.search_date_utc,
        "query_count": len(plan.queries),
        "limitation_count": len(plan.limitations),
        "keyword_count": len(plan.keywords),
        "coverage_gaps": [g.to_dict() for g in plan.coverage_gaps],
        "queries": [
            {
                "query_id": q.query_id,
                "family": q.family.value if hasattr(q.family, "value") else str(q.family),
                "query_text": q.query_text[:300],
                "rank_cutoff": q.rank_cutoff,
            }
            for q in plan.queries
        ],
        "plan": plan.to_dict(),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        "generated_at_utc": utc_now_iso(),
    }

    if persist:
        rid = run_id or f"plan-{plan.plan_id.split(':')[-1][:16]}"
        run_dir = prior_art_app_dir(app, state_root=root) / rid
        plan_path = _write_json(run_dir / "prior_art_plan.json", plan.to_dict())
        manifest = {
            "schema": PRIOR_ART_CLIENT_SCHEMA,
            "run_id": rid,
            "action": "plan",
            "application_number": app,
            "plan_id": plan.plan_id,
            "created_at_utc": utc_now_iso(),
            "paths": {"plan": str(plan_path)},
            "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        }
        man_path = _write_json(run_dir / PRIOR_ART_RUN_MANIFEST, manifest)
        result["run_id"] = rid
        result["run_dir"] = str(run_dir)
        result["paths"] = {"plan": str(plan_path), "manifest": str(man_path)}
    return result


def search_prior_art(
    *,
    application_number: str,
    state_root: Path | None = None,
    claims: Sequence[Mapping[str, Any]] | None = None,
    claims_file: str | Path | None = None,
    claims_text: str | None = None,
    filing_date: str | None = None,
    priority_date: str | None = None,
    classifications: Sequence[str] = (),
    rank_cutoff: int = 10,
    citation_seeds: Sequence[str] = (),
    family_seeds: Sequence[str] = (),
    use_odp: bool = False,
    local_snapshot_path: str | Path | None = None,
    odp_adapter: Any | None = None,
    local_adapter: Any | None = None,
    max_odp_pages: int = 1,
    max_queries: int | None = None,
    run_id: str | None = None,
    plan: Any | None = None,
) -> dict[str, Any]:
    """Plan + execute prior-art search; write journal, coverage, claim chart."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        assert_no_patentability_conclusions,
    )
    from ipfs_datasets_py.processors.domains.patent.prior_art_coverage import (
        build_coverage_from_journal,
    )
    from ipfs_datasets_py.processors.domains.patent.prior_art_runtime import (
        public_search_plan_from_prior_art_plan,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        SearchDatabase,
    )

    app = _normalize_app(application_number)
    root = Path(state_root) if state_root is not None else default_state_root()

    if plan is None:
        plan_result = plan_prior_art(
            application_number=app,
            state_root=root,
            claims=claims,
            claims_file=claims_file,
            claims_text=claims_text,
            filing_date=filing_date,
            priority_date=priority_date,
            classifications=classifications,
            rank_cutoff=rank_cutoff,
            citation_seeds=citation_seeds,
            family_seeds=family_seeds,
            persist=False,
        )
        from ipfs_datasets_py.processors.domains.patent.prior_art import (
            PriorArtSearchPlan,
        )

        plan = PriorArtSearchPlan.from_dict(plan_result["plan"])

    # Optionally bound query count for live ODP cost control
    if max_queries is not None and max_queries > 0 and len(plan.queries) > max_queries:
        from dataclasses import replace

        # Prefer keyword/limitation queries first
        kept = list(plan.queries[: int(max_queries)])
        try:
            plan = replace(plan, queries=tuple(kept))
        except Exception:
            # Frozen dataclass with slots — rebuild via from_dict
            d = plan.to_dict()
            d["queries"] = [q.to_dict() for q in kept]
            from ipfs_datasets_py.processors.domains.patent.prior_art import (
                PriorArtSearchPlan,
            )

            plan = PriorArtSearchPlan.from_dict(d)

    runtime = build_operator_runtime(
        use_odp=use_odp,
        odp_adapter=odp_adapter,
        local_adapter=local_adapter,
        local_snapshot_path=local_snapshot_path,
        max_odp_pages=max_odp_pages,
    )

    # Prefer ODP database when ODP is active; else local snapshot / US patents
    database = SearchDatabase.US_PATENTS
    if use_odp or odp_adapter is not None:
        database = SearchDatabase.ODP_PATENT_FILE_WRAPPER
    elif local_adapter is not None or local_snapshot_path:
        database = SearchDatabase.LOCAL_PUBLIC_SNAPSHOT

    public_plan = public_search_plan_from_prior_art_plan(
        plan, corpus_cutoff=plan.priority_date, database=database
    )
    journal = runtime.execute_plan(public_plan)
    coverage = build_coverage_from_journal(
        journal,
        metadata={"operator_client": PRIOR_ART_CLIENT_SCHEMA},
    )
    chart = claim_chart_from_journal(plan, journal)
    summary = distinguishability_summary(plan, journal, chart, coverage)

    assert_no_patentability_conclusions(plan.to_dict())
    assert_no_patentability_conclusions(journal.to_dict())
    assert_no_patentability_conclusions(chart.to_dict())
    assert_no_patentability_conclusions(summary)

    rid = run_id or f"run-{journal.journal_id.split(':')[-1][:16]}"
    if rid == journal.journal_id:
        rid = f"run-{rid[-16:]}"
    run_dir = prior_art_app_dir(app, state_root=root) / rid

    paths = {
        "plan": str(_write_json(run_dir / "prior_art_plan.json", plan.to_dict())),
        "public_plan": str(
            _write_json(run_dir / "public_search_plan.json", public_plan.to_dict())
        ),
        "journal": str(_write_json(run_dir / "search_journal.json", journal.to_dict())),
        "coverage": str(
            _write_json(run_dir / "coverage_declaration.json", coverage.to_dict())
        ),
        "claim_chart": str(_write_json(run_dir / "claim_chart.json", chart.to_dict())),
        "summary": str(
            _write_json(run_dir / "distinguishability_summary.json", summary)
        ),
    }
    manifest = {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "run_id": rid,
        "action": "search",
        "application_number": app,
        "plan_id": plan.plan_id,
        "journal_id": journal.journal_id,
        "chart_id": chart.chart_id,
        "coverage_id": coverage.declaration_id,
        "backends": {
            "odp": bool(use_odp or odp_adapter is not None),
            "local_snapshot": bool(local_adapter is not None or local_snapshot_path),
            "database": database.value
            if hasattr(database, "value")
            else str(database),
        },
        "created_at_utc": utc_now_iso(),
        "paths": paths,
        "hit_count": len(summary.get("candidate_hits") or []),
        "gap_count": len(summary.get("coverage_gaps") or []),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
    }
    paths["manifest"] = str(_write_json(run_dir / PRIOR_ART_RUN_MANIFEST, manifest))

    result = PriorArtRunResult(
        ok=True,
        run_id=rid,
        run_dir=str(run_dir),
        application_number=app,
        plan_id=plan.plan_id,
        journal_id=journal.journal_id,
        chart_id=chart.chart_id,
        coverage_id=coverage.declaration_id,
        paths=paths,
        summary=summary,
    )
    return result.to_dict()


def list_prior_art_runs(
    *,
    application_number: str | None = None,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """List persisted prior-art runs under the portfolio state tree."""
    root = Path(state_root) if state_root is not None else default_state_root()
    base = prior_art_root(root)
    runs: list[dict[str, Any]] = []
    if not base.is_dir():
        return {
            "schema": PRIOR_ART_CLIENT_SCHEMA,
            "ok": True,
            "count": 0,
            "runs": [],
            "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        }

    app_filter = _normalize_app(application_number) if application_number else None
    for app_dir in sorted(base.iterdir()):
        if not app_dir.is_dir():
            continue
        if app_filter and app_dir.name != app_filter:
            continue
        for run_dir in sorted(app_dir.iterdir()):
            man = run_dir / PRIOR_ART_RUN_MANIFEST
            if man.is_file():
                try:
                    payload = _read_json(man)
                except Exception:
                    payload = {"run_id": run_dir.name, "error": "unreadable_manifest"}
            else:
                payload = {"run_id": run_dir.name, "action": "unknown"}
            payload.setdefault("application_number", app_dir.name)
            payload.setdefault("run_dir", str(run_dir))
            runs.append(payload)

    return {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "count": len(runs),
        "runs": runs,
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        "generated_at_utc": utc_now_iso(),
    }


def show_prior_art_run(
    *,
    run_id: str | None = None,
    application_number: str | None = None,
    run_dir: str | Path | None = None,
    state_root: Path | None = None,
    include_full: bool = False,
) -> dict[str, Any]:
    """Load a prior-art run summary (and optionally full artifacts)."""
    root = Path(state_root) if state_root is not None else default_state_root()
    target: Path | None = None
    if run_dir:
        target = Path(run_dir).expanduser().resolve()
    elif run_id and application_number:
        target = prior_art_app_dir(application_number, state_root=root) / run_id
    elif run_id:
        # Search all apps
        base = prior_art_root(root)
        if base.is_dir():
            for app_dir in base.iterdir():
                cand = app_dir / run_id
                if cand.is_dir():
                    target = cand
                    break
    if target is None or not target.is_dir():
        raise PriorArtSearchClientError(
            "run not found (pass --run-id and/or --application-number)",
            code="run_not_found",
        )

    man_path = target / PRIOR_ART_RUN_MANIFEST
    manifest = _read_json(man_path) if man_path.is_file() else {"run_id": target.name}
    summary_path = target / "distinguishability_summary.json"
    summary = _read_json(summary_path) if summary_path.is_file() else {}

    out: dict[str, Any] = {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "run_dir": str(target),
        "manifest": manifest,
        "summary": summary,
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        "generated_at_utc": utc_now_iso(),
    }
    if include_full:
        for name in (
            "prior_art_plan",
            "search_journal",
            "coverage_declaration",
            "claim_chart",
        ):
            p = target / f"{name}.json"
            if p.is_file():
                out[name] = _read_json(p)
    return out


def attach_prior_art_to_revision(
    revision_id: str,
    run_dir: str | Path,
    *,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Attach distinguishability summary + claim chart paths onto a revision case."""
    from ipfs_datasets_py.processors.domains.uspto.revision_response import (
        load_revision_case,
        save_revision_case,
    )

    root = Path(state_root) if state_root is not None else default_state_root()
    case = load_revision_case(revision_id, state_root=root)
    target = Path(run_dir).expanduser().resolve()
    if not target.is_dir():
        raise PriorArtSearchClientError(
            f"prior-art run_dir not found: {target}", code="run_not_found"
        )
    summary_path = target / "distinguishability_summary.json"
    chart_path = target / "claim_chart.json"
    journal_path = target / "search_journal.json"
    coverage_path = target / "coverage_declaration.json"
    man_path = target / PRIOR_ART_RUN_MANIFEST

    pointer = {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "revision_id": revision_id,
        "application_number": case.application_number,
        "run_dir": str(target),
        "paths": {
            "manifest": str(man_path) if man_path.is_file() else None,
            "summary": str(summary_path) if summary_path.is_file() else None,
            "claim_chart": str(chart_path) if chart_path.is_file() else None,
            "journal": str(journal_path) if journal_path.is_file() else None,
            "coverage": str(coverage_path) if coverage_path.is_file() else None,
        },
        "attached_at_utc": utc_now_iso(),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
    }
    case_dir = Path(case.case_dir) if getattr(case, "case_dir", None) else None
    if case_dir is None or not str(case_dir):
        case_dir = root / "revisions" / case.application_number / revision_id
    pointer_path = _write_json(case_dir / "prior_art_attachment.json", pointer)

    case.notes = list(case.notes or []) + [
        f"prior-art search attached: {target.name} @ {utc_now_iso()}"
    ]
    save_revision_case(case, state_root=root)

    return {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "revision_id": revision_id,
        "application_number": case.application_number,
        "prior_art_attachment": str(pointer_path),
        "run_dir": str(target),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
    }


__all__ = [
    "PRIOR_ART_CLIENT_SCHEMA",
    "PRIOR_ART_DISCLAIMER_SHORT",
    "PriorArtRunResult",
    "PriorArtSearchClientError",
    "attach_prior_art_to_revision",
    "build_local_snapshot_from_docs",
    "build_odp_adapter_live",
    "build_operator_prior_art_plan",
    "build_operator_runtime",
    "claim_chart_from_journal",
    "distinguishability_summary",
    "list_prior_art_runs",
    "load_claims",
    "load_export_temporal_anchors",
    "load_local_snapshot_documents",
    "parse_claims_text",
    "plan_prior_art",
    "prior_art_app_dir",
    "prior_art_root",
    "search_prior_art",
    "show_prior_art_run",
]
