"""Extended prior-art operator features: foreign/NPL, citation/family, PPS verify.

Complements :mod:`prior_art_search_client` with:

* Named **foreign-patent** and **NPL** adapters (file-backed or search_fn)
* **Citation** and **family** expansion adapters from graph files / seeds
* Plan augmentation so foreign/NPL queries actually run when enabled
* **Patent Public Search** human-verification checklist (never scraped)
* Prior-art **report** + optional rule **checklist** + human coverage ack

Still never asserts novelty, obviousness, or patentability. Unlicensed NPL
body text is never redistributed. PPS interactive verification is human-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    utc_now_iso,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    PRIOR_ART_CLIENT_SCHEMA,
    PRIOR_ART_DISCLAIMER_SHORT,
    PriorArtSearchClientError,
    _write_json,
    _read_json,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PPS_PUBLIC_URL: Final = "https://ppubs.uspto.gov/pubwebapp/"
PPS_CHECKLIST_SCHEMA: Final = "patlaw-pps-verification-checklist-v1"
PPS_RECORD_SCHEMA: Final = "patlaw-pps-verification-record-v1"
EXTENSIONS_SCHEMA: Final = "patlaw-prior-art-operator-extensions-v1"

PPS_DISCLAIMER: Final = (
    "Patent Public Search (PPS) is an interactive USPTO web interface, not a "
    "documented public API. This checklist helps a human run and record "
    "verification queries. Automation never scrapes or automates PPS. "
    "Not a novelty/patentability determination; not legal advice."
)


# ---------------------------------------------------------------------------
# Loaders: foreign hits, NPL catalog, citation/family graphs
# ---------------------------------------------------------------------------


def _load_json_rows(path: str | Path) -> list[Any]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise PriorArtSearchClientError(
            f"file not found: {p}", code="file_missing"
        )
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    payload = json.loads(raw)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in (
            "documents",
            "hits",
            "records",
            "edges",
            "members",
            "items",
            "rows",
        ):
            if isinstance(payload.get(key), list):
                return list(payload[key])
        if payload.get("document_id") or payload.get("citing_id"):
            return [payload]
    raise PriorArtSearchClientError(
        f"unsupported JSON shape in {p}", code="invalid_json_shape"
    )


def load_foreign_hits(path: str | Path) -> list[Any]:
    """Load foreign-patent JournalHit-compatible mappings from JSON/JSONL."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        normalize_document_id,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        JournalHit,
        make_source_link,
    )

    rows = _load_json_rows(path)
    hits: list[Any] = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        if "source_links" in row and "document_id" in row:
            hits.append(JournalHit.from_dict(row))
            continue
        doc_id = str(
            row.get("document_id")
            or row.get("publication_number")
            or row.get("patent_number")
            or row.get("id")
            or ""
        ).strip()
        if not doc_id:
            continue
        doc_id = normalize_document_id(doc_id) or doc_id
        source_cid = str(row.get("source_cid") or f"cid:foreign:{doc_id}")
        title = str(row.get("title") or row.get("invention_title") or "")[:400]
        hits.append(
            JournalHit(
                document_id=doc_id,
                rank=int(row.get("rank") or i + 1),
                score=float(row.get("score") or max(0.0, 100.0 - i)),
                source_links=(
                    make_source_link(
                        source_cid=source_cid,
                        artifact_id=f"artifact:foreign:{doc_id}",
                        end=max(len(title), 1),
                    ),
                ),
                passage_excerpt=title or None,
                identifiers={
                    "document_id": doc_id,
                    **(
                        {"country": str(row["country"])}
                        if row.get("country")
                        else {}
                    ),
                },
                metadata={
                    "rights_status": str(row.get("rights_status") or "public"),
                    "expansion_mode": "foreign",
                    **(
                        {"title": title}
                        if title
                        else {}
                    ),
                },
            )
        )
    return hits


def load_npl_records(path: str | Path) -> list[Any]:
    """Load NplRecord rows (body text rights-gated by the adapter)."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        NplRecord,
        RightsStatus,
    )

    rows = _load_json_rows(path)
    records: list[Any] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if "document_id" not in row and "id" in row:
            row = {**row, "document_id": row["id"]}
        if not row.get("document_id"):
            continue
        try:
            records.append(
                NplRecord(
                    document_id=str(row["document_id"]),
                    title=row.get("title"),
                    identifier=row.get("identifier") or row.get("doi") or row.get("url"),
                    rights_status=row.get("rights_status")
                    or RightsStatus.UNLICENSED.value,
                    body_text=row.get("body_text") or row.get("abstract"),
                    rights_approval_id=row.get("rights_approval_id"),
                    metadata={
                        str(k): str(v)
                        for k, v in dict(row.get("metadata") or {}).items()
                        if str(v or "").strip()
                    },
                )
            )
        except Exception:
            # Skip invalid rows fail-soft for catalog load
            continue
    return records


def load_citation_edges(path: str | Path) -> list[Any]:
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        CitationDirection,
        CitationEdge,
    )

    rows = _load_json_rows(path)
    edges: list[Any] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        citing = row.get("citing_id") or row.get("citing") or row.get("from")
        cited = row.get("cited_id") or row.get("cited") or row.get("to")
        if not citing or not cited:
            continue
        direction = row.get("direction") or CitationDirection.BACKWARD.value
        try:
            edges.append(
                CitationEdge(
                    citing_id=str(citing),
                    cited_id=str(cited),
                    direction=direction,
                    category=str(row.get("category") or "citation")[:64],
                    rights_status=row.get("rights_status") or "public",
                    metadata={
                        str(k): str(v)
                        for k, v in dict(row.get("metadata") or {}).items()
                        if str(v or "").strip()
                    },
                )
            )
        except Exception:
            continue
    return edges


def load_family_members(path: str | Path) -> list[Any]:
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        FamilyMember,
        FamilyRelationKind,
    )

    rows = _load_json_rows(path)
    members: list[Any] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        doc_id = row.get("document_id") or row.get("id")
        if not doc_id:
            continue
        try:
            members.append(
                FamilyMember(
                    document_id=str(doc_id),
                    relation=row.get("relation")
                    or FamilyRelationKind.UNKNOWN.value,
                    related_to=str(row.get("related_to") or row.get("seed") or doc_id),
                    filing_date=row.get("filing_date"),
                    priority_date=row.get("priority_date"),
                    country=row.get("country"),
                    rights_status=row.get("rights_status") or "public",
                    metadata={
                        str(k): str(v)
                        for k, v in dict(row.get("metadata") or {}).items()
                        if str(v or "").strip()
                    },
                )
            )
        except Exception:
            continue
    return members


def foreign_hits_from_snapshot(path: str | Path) -> list[Any]:
    """Convert a local patent snapshot JSON into foreign JournalHit list."""
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        load_local_snapshot_documents,
    )
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        normalize_document_id,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        JournalHit,
        make_source_link,
    )

    docs = load_local_snapshot_documents(path)
    hits: list[Any] = []
    for i, doc in enumerate(docs):
        doc_id = normalize_document_id(doc.document_id) or doc.document_id
        links = doc.source_links or ()
        if not links:
            links = (
                make_source_link(
                    source_cid=f"cid:foreign:{doc_id}",
                    artifact_id=f"artifact:foreign:{doc_id}",
                    end=40,
                ),
            )
        title = str((doc.field_values or {}).get("title") or "")[:400]
        hits.append(
            JournalHit(
                document_id=doc_id,
                rank=i + 1,
                score=float(max(0.0, 100.0 - i)),
                source_links=tuple(links),
                passage_excerpt=title or None,
                identifiers={"document_id": doc_id},
                metadata={
                    "rights_status": "public",
                    "expansion_mode": "foreign",
                    "from_snapshot": "true",
                },
            )
        )
    return hits


# ---------------------------------------------------------------------------
# Adapter assembly
# ---------------------------------------------------------------------------


def build_coverage_adapter_registry(
    *,
    enable_foreign: bool = False,
    foreign_hits_path: str | Path | None = None,
    foreign_snapshot_path: str | Path | None = None,
    foreign_licensed: bool = True,
    enable_npl: bool = False,
    npl_catalog_path: str | Path | None = None,
    npl_licensed: bool = False,
    citation_graph_path: str | Path | None = None,
    family_graph_path: str | Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Build PriorArtAdapterRegistry + status metadata for operator search."""
    from ipfs_datasets_py.processors.domains.patent.prior_art_adapters import (
        CitationExpansionAdapter,
        FamilyExpansionAdapter,
        ForeignPatentAdapter,
        NplAdapter,
        RightsStatus,
        build_coverage_adapters,
    )

    status: dict[str, Any] = {
        "foreign": {"enabled": bool(enable_foreign), "backend": None},
        "npl": {"enabled": bool(enable_npl), "backend": None},
        "citation": {"enabled": bool(citation_graph_path), "backend": None},
        "family": {"enabled": bool(family_graph_path), "backend": None},
    }

    foreign_adapter = None
    if enable_foreign or foreign_hits_path or foreign_snapshot_path:
        hits: list[Any] = []
        if foreign_hits_path:
            hits.extend(load_foreign_hits(foreign_hits_path))
            status["foreign"]["backend"] = "hits_file"
            status["foreign"]["hit_count"] = len(hits)
        if foreign_snapshot_path:
            snap_hits = foreign_hits_from_snapshot(foreign_snapshot_path)
            hits.extend(snap_hits)
            status["foreign"]["backend"] = (
                "hits_file+snapshot" if foreign_hits_path else "snapshot"
            )
            status["foreign"]["hit_count"] = len(hits)
        if not hits:
            status["foreign"]["backend"] = "named_gap_no_backend"
        foreign_adapter = ForeignPatentAdapter(
            hits=hits,
            licensed=bool(foreign_licensed),
            accessible=True,
            default_rights_status=RightsStatus.PUBLIC,
        )
        status["foreign"]["enabled"] = True
        status["foreign"]["adapter_name"] = foreign_adapter.identity.adapter_name
        status["foreign"]["licensed"] = bool(foreign_licensed)

    npl_adapter = None
    if enable_npl or npl_catalog_path:
        records: list[Any] = []
        if npl_catalog_path:
            records = load_npl_records(npl_catalog_path)
            status["npl"]["backend"] = "catalog_file"
            status["npl"]["record_count"] = len(records)
        else:
            status["npl"]["backend"] = "named_gap_no_backend"
        # licensed=True only when operator asserts license AND catalog present
        # (or explicit licensed flag with empty → still fail as unlicensed gap)
        npl_adapter = NplAdapter(
            records=records,
            licensed=bool(npl_licensed and records),
            accessible=True,
            default_rights_status=(
                RightsStatus.LICENSED
                if npl_licensed and records
                else RightsStatus.UNLICENSED
            ),
        )
        status["npl"]["enabled"] = True
        status["npl"]["adapter_name"] = npl_adapter.identity.adapter_name
        status["npl"]["licensed"] = bool(npl_licensed and records)
        if npl_licensed and not records:
            status["npl"]["warning"] = (
                "npl_licensed set but catalog empty/missing; corpus remains gap"
            )

    citation_adapter = None
    if citation_graph_path:
        edges = load_citation_edges(citation_graph_path)
        citation_adapter = CitationExpansionAdapter(edges=edges)
        status["citation"]["backend"] = "graph_file"
        status["citation"]["edge_count"] = len(edges)
        status["citation"]["adapter_name"] = citation_adapter.identity.adapter_name

    family_adapter = None
    if family_graph_path:
        members = load_family_members(family_graph_path)
        family_adapter = FamilyExpansionAdapter(members=members)
        status["family"]["backend"] = "graph_file"
        status["family"]["member_count"] = len(members)
        status["family"]["adapter_name"] = family_adapter.identity.adapter_name

    registry = build_coverage_adapters(
        citation=citation_adapter,
        family=family_adapter,
        foreign=foreign_adapter,
        npl=npl_adapter,
    )
    return registry, status


def augment_plan_for_coverage(
    plan: Any,
    *,
    enable_foreign: bool = False,
    enable_npl: bool = False,
    enable_citation: bool = False,
    enable_family: bool = False,
    rank_cutoff: int | None = None,
    max_mirror_queries: int = 4,
) -> Any:
    """Add foreign/NPL/citation/family queries onto an existing plan when enabled."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        PriorArtSearchPlan,
        QueryFamily,
        SearchCorpus,
        SearchQuerySpec,
        default_coverage_gaps,
    )

    cutoff = int(rank_cutoff or plan.rank_cutoff or 10)
    extra: list[Any] = []
    existing_ids = {q.query_id for q in plan.queries}

    def _add(q: SearchQuerySpec) -> None:
        if q.query_id not in existing_ids:
            extra.append(q)
            existing_ids.add(q.query_id)

    # Mirror top keyword/limitation queries into foreign/NPL corpora
    mirror_src = [
        q
        for q in plan.queries
        if q.family
        in (
            QueryFamily.KEYWORD,
            QueryFamily.CLAIM_LIMITATION,
            QueryFamily.CLASSIFICATION_CPC,
            QueryFamily.CLASSIFICATION_IPC,
        )
    ][: max(1, int(max_mirror_queries))]

    if enable_foreign:
        for q in mirror_src:
            _add(
                SearchQuerySpec(
                    query_id=f"q-foreign-{q.query_id}"[:200],
                    query_text=q.query_text,
                    family=q.family,
                    intended_corpora=(SearchCorpus.FOREIGN_PATENTS,),
                    rank_cutoff=cutoff,
                    related_limitation_ids=q.related_limitation_ids,
                    classification_codes=q.classification_codes,
                    metadata={
                        "source": "foreign_mirror",
                        "mirrored_from": q.query_id,
                    },
                )
            )

    if enable_npl:
        for q in mirror_src:
            _add(
                SearchQuerySpec(
                    query_id=f"q-npl-{q.query_id}"[:200],
                    query_text=q.query_text,
                    family=q.family,
                    intended_corpora=(SearchCorpus.NPL,),
                    rank_cutoff=cutoff,
                    related_limitation_ids=q.related_limitation_ids,
                    metadata={
                        "source": "npl_mirror",
                        "mirrored_from": q.query_id,
                    },
                )
            )

    # Citation / family expansion queries if seeds already on plan
    if enable_citation:
        seeds = []
        for q in plan.queries:
            if q.family is QueryFamily.CITATION_EXPANSION:
                seeds.extend(q.seed_document_ids or ())
        # Also use any citation-expansion query text tokens
        if not seeds:
            for q in plan.queries:
                if q.family is QueryFamily.CITATION_EXPANSION:
                    seeds.append(q.query_text)
        if seeds:
            _add(
                SearchQuerySpec(
                    query_id="q-cite-run",
                    query_text=" ".join(str(s) for s in seeds[:8]),
                    family=QueryFamily.CITATION_EXPANSION,
                    intended_corpora=(
                        SearchCorpus.US_PATENTS,
                        SearchCorpus.US_PUBLICATIONS,
                    ),
                    rank_cutoff=cutoff,
                    seed_document_ids=tuple(str(s) for s in seeds[:16]),
                    metadata={"source": "citation_expansion_run"},
                )
            )

    if enable_family:
        seeds = []
        for q in plan.queries:
            if q.family is QueryFamily.FAMILY_EXPANSION:
                seeds.extend(q.seed_document_ids or ())
        if seeds:
            _add(
                SearchQuerySpec(
                    query_id="q-family-run",
                    query_text=" ".join(str(s) for s in seeds[:8]),
                    family=QueryFamily.FAMILY_EXPANSION,
                    intended_corpora=(
                        SearchCorpus.US_PATENTS,
                        SearchCorpus.US_PUBLICATIONS,
                    ),
                    rank_cutoff=cutoff,
                    seed_document_ids=tuple(str(s) for s in seeds[:16]),
                    metadata={"source": "family_expansion_run"},
                )
            )

    if not extra:
        return plan

    corpora = list(plan.intended_corpora or ())
    if enable_foreign and SearchCorpus.FOREIGN_PATENTS not in corpora:
        corpora.append(SearchCorpus.FOREIGN_PATENTS)
    if enable_npl and SearchCorpus.NPL not in corpora:
        corpora.append(SearchCorpus.NPL)

    # Gaps always keep foreign/NPL visible; searched flag only after real run
    gaps = default_coverage_gaps(
        searched_corpora=tuple(
            c
            for c in corpora
            if c in (SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS)
        )
    )

    d = plan.to_dict()
    d["queries"] = [q.to_dict() for q in list(plan.queries) + extra]
    d["intended_corpora"] = [
        c.value if hasattr(c, "value") else str(c) for c in corpora
    ]
    d["coverage_gaps"] = [g.to_dict() for g in gaps]
    meta = dict(d.get("metadata") or {})
    meta["coverage_augmented"] = "true"
    meta["extensions_schema"] = EXTENSIONS_SCHEMA
    d["metadata"] = meta
    return PriorArtSearchPlan.from_dict(d)


# ---------------------------------------------------------------------------
# Patent Public Search (human verification only)
# ---------------------------------------------------------------------------


def build_pps_verification_checklist(
    plan: Any,
    *,
    application_number: str = "",
    run_id: str | None = None,
    max_queries: int = 24,
) -> dict[str, Any]:
    """Build a human PPS verification checklist from a prior-art plan.

    Operators copy each query into Patent Public Search interactively.
    This does **not** automate or scrape PPS.
    """
    items: list[dict[str, Any]] = []
    for q in list(plan.queries)[: int(max_queries)]:
        family = q.family.value if hasattr(q.family, "value") else str(q.family)
        corpora = [
            c.value if hasattr(c, "value") else str(c)
            for c in (q.intended_corpora or ())
        ]
        items.append(
            {
                "query_id": q.query_id,
                "query_text": q.query_text,
                "family": family,
                "intended_corpora": corpora,
                "rank_cutoff": q.rank_cutoff,
                "classification_codes": list(q.classification_codes or ()),
                "seed_document_ids": list(q.seed_document_ids or ()),
                "pps_hint": _pps_query_hint(q.query_text, family),
                "status": "pending",
                "human_result_count": None,
                "human_notes": "",
                "verified_at_utc": None,
                "verified_by": None,
            }
        )

    return {
        "schema": PPS_CHECKLIST_SCHEMA,
        "application_number": application_number,
        "plan_id": getattr(plan, "plan_id", None),
        "subject_id": getattr(plan, "subject_id", None),
        "run_id": run_id,
        "pps_url": PPS_PUBLIC_URL,
        "item_count": len(items),
        "items": items,
        "instructions": [
            f"Open Patent Public Search: {PPS_PUBLIC_URL}",
            "For each pending item, paste pps_hint / query_text into PPS.",
            "Record human_result_count and optional notes via prior-art pps-record.",
            "Do not treat zero hits as proof of novelty.",
            "Foreign patents and NPL may require other databases beyond PPS.",
        ],
        "disclaimer": PPS_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


def _pps_query_hint(query_text: str, family: str) -> str:
    text = " ".join(str(query_text or "").split())
    if family.startswith("classification"):
        # CPC/IPC often works as bare code in PPS advanced search
        return text.upper().replace(" ", "")
    # Quote multi-word phrases lightly for copy-paste
    if len(text.split()) > 6:
        return text[:500]
    return text[:500]


def persist_pps_checklist(
    checklist: Mapping[str, Any],
    run_dir: str | Path,
) -> Path:
    path = Path(run_dir) / "pps_verification_checklist.json"
    return _write_json(path, dict(checklist))


def record_pps_verification(
    run_dir: str | Path,
    *,
    results: Sequence[Mapping[str, Any]],
    verified_by: str,
    notes: str = "",
) -> dict[str, Any]:
    """Merge human PPS verification results into the checklist on disk.

    Each result mapping: ``{query_id, human_result_count, human_notes?, status?}``
    status defaults to ``verified`` when a count is provided.
    """
    run_path = Path(run_dir).expanduser().resolve()
    checklist_path = run_path / "pps_verification_checklist.json"
    if not checklist_path.is_file():
        raise PriorArtSearchClientError(
            f"PPS checklist not found in {run_path}; run pps-checklist first",
            code="pps_checklist_missing",
        )
    checklist = _read_json(checklist_path)
    by_id = {str(item.get("query_id")): item for item in checklist.get("items") or []}
    now = utc_now_iso()
    updated = 0
    for row in results:
        if not isinstance(row, Mapping):
            continue
        qid = str(row.get("query_id") or "").strip()
        if not qid or qid not in by_id:
            continue
        item = by_id[qid]
        if row.get("human_result_count") is not None:
            item["human_result_count"] = int(row["human_result_count"])
        if row.get("human_notes") is not None:
            item["human_notes"] = str(row.get("human_notes") or "")[:2000]
        status = str(row.get("status") or "").strip()
        if not status:
            status = (
                "verified"
                if row.get("human_result_count") is not None
                else "pending"
            )
        item["status"] = status
        item["verified_at_utc"] = now
        item["verified_by"] = str(verified_by)
        updated += 1

    checklist["items"] = list(by_id.values())
    checklist["updated_at_utc"] = now
    checklist["last_verified_by"] = str(verified_by)
    if notes:
        checklist["operator_notes"] = str(notes)[:4000]
    pending = sum(
        1 for it in checklist["items"] if it.get("status") == "pending"
    )
    verified = sum(
        1 for it in checklist["items"] if it.get("status") == "verified"
    )
    checklist["pending_count"] = pending
    checklist["verified_count"] = verified
    checklist["complete"] = pending == 0 and verified > 0

    record = {
        "schema": PPS_RECORD_SCHEMA,
        "run_dir": str(run_path),
        "verified_by": str(verified_by),
        "updated_items": updated,
        "pending_count": pending,
        "verified_count": verified,
        "complete": checklist["complete"],
        "recorded_at_utc": now,
        "notes": notes,
        "disclaimer": PPS_DISCLAIMER,
    }
    _write_json(checklist_path, checklist)
    _write_json(run_path / "pps_verification_record.json", record)
    return {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "checklist_path": str(checklist_path),
        "record": record,
        "checklist_summary": {
            "item_count": checklist.get("item_count"),
            "pending_count": pending,
            "verified_count": verified,
            "complete": checklist["complete"],
            "pps_url": checklist.get("pps_url"),
        },
        "disclaimer": PPS_DISCLAIMER,
    }


def show_pps_verification(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir).expanduser().resolve()
    checklist_path = run_path / "pps_verification_checklist.json"
    record_path = run_path / "pps_verification_record.json"
    if not checklist_path.is_file():
        raise PriorArtSearchClientError(
            f"no PPS checklist in {run_path}", code="pps_checklist_missing"
        )
    return {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "run_dir": str(run_path),
        "checklist": _read_json(checklist_path),
        "record": _read_json(record_path) if record_path.is_file() else None,
        "disclaimer": PPS_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Report + human coverage acknowledgment + rule checklist
# ---------------------------------------------------------------------------


def build_operator_prior_art_report(
    plan: Any,
    journal: Any,
    chart: Any,
    *,
    report_id: str | None = None,
) -> Any:
    """Assemble a PATLAW-094 PriorArtReport from plan + journal-derived chart."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        PriorArtReport,
        RankedPassageHit,
        SearchCorpus,
        SearchQuerySpec,
        QueryFamily,
        record_dated_query_log,
    )

    query_by_id = {q.query_id: q for q in plan.queries}
    logs = []
    for rec in journal.records:
        qspec = query_by_id.get(rec.query_id)
        if qspec is None:
            qspec = SearchQuerySpec(
                query_id=rec.query_id,
                query_text=rec.query_text,
                family=QueryFamily.KEYWORD,
                intended_corpora=(SearchCorpus.US_PATENTS,),
                rank_cutoff=int(getattr(rec, "rank_cutoff", None) or 10),
            )
        hits: list[Any] = []
        for hit in rec.hits or ():
            links = list(hit.source_links or ())
            if not links:
                continue
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
        corpus = SearchCorpus.US_PATENTS
        db = rec.database.value if hasattr(rec.database, "value") else str(rec.database)
        if "foreign" in db:
            corpus = SearchCorpus.FOREIGN_PATENTS
        elif db == "npl":
            corpus = SearchCorpus.NPL
        elif "publication" in db:
            corpus = SearchCorpus.US_PUBLICATIONS
        logs.append(
            record_dated_query_log(
                qspec,
                hits,
                search_date_utc=plan.search_date_utc,
                corpus=corpus,
                filters=plan.filters,
                log_id=f"log:{journal.journal_id}:{rec.query_id}",
            )
        )

    return PriorArtReport(
        schema_version=plan.schema_version,
        report_id=report_id or f"report:{plan.plan_id}",
        plan=plan,
        query_logs=tuple(logs),
        chart=chart,
        coverage_gaps=plan.coverage_gaps,
        metadata={
            "journal_id": journal.journal_id,
            "source": "prior_art_operator_extensions",
            "extensions_schema": EXTENSIONS_SCHEMA,
        },
    )


def build_human_coverage_acknowledgment(
    *,
    acknowledger_name: str,
    report: Any,
    coverage_scope_text: str | None = None,
    statement: str | None = None,
) -> Any:
    """Build HumanCoverageAcknowledgment bound to report digest."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import content_digest
    from ipfs_datasets_py.processors.domains.patent.rules import (
        HumanCoverageAcknowledgment,
    )

    digest = content_digest(report.to_dict())
    scope = coverage_scope_text or (
        "I reviewed the prior-art plan, search journal, coverage declaration, "
        "claim chart, and named foreign/NPL gaps. Foreign patents and NPL remain "
        "unsearched or only partially covered unless named adapters show success. "
        "Patent Public Search interactive verification is a separate human step."
    )
    stmt = statement or (
        "I acknowledge the coverage scope and that visible gaps remain. "
        "This is not a patentability determination."
    )
    return HumanCoverageAcknowledgment(
        acknowledger_name=acknowledger_name,
        acknowledged_at_utc=utc_now_iso(),
        report_id=report.report_id,
        report_digest=digest,
        coverage_scope_text=scope,
        acknowledges_gaps_visible=True,
        statement=stmt,
        metadata={"source": "prior_art_operator_extensions"},
    )


def build_operator_rule_checklist(
    *,
    subject_id: str,
    report: Any,
    human_ack: Any | None = None,
    claim_complete: bool = False,
) -> Any:
    """Build prior-art rule preflight checklist (no patentability conclusions)."""
    from ipfs_datasets_py.processors.domains.patent.rules import (
        build_prior_art_rule_checklist,
    )

    as_of = getattr(report, "search_date_utc", None) or report.plan.search_date_utc
    return build_prior_art_rule_checklist(
        subject_id=subject_id,
        as_of_utc=as_of,
        prior_art_report=report,
        human_coverage_acknowledgment=human_ack,
        claim_prior_art_search_complete=bool(claim_complete) if human_ack else False,
        metadata={"source": "prior_art_operator_extensions"},
    )


def acknowledge_prior_art_run(
    run_dir: str | Path,
    *,
    acknowledger_name: str,
    claim_search_complete: bool = False,
    coverage_scope_text: str | None = None,
) -> dict[str, Any]:
    """Write human coverage ack (+ optional rule checklist) into a completed run."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        PriorArtReport,
        PriorArtSearchPlan,
        assert_no_patentability_conclusions,
        content_digest,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        SearchJournal,
    )
    from ipfs_datasets_py.processors.domains.patent.prior_art import ClaimChart

    run_path = Path(run_dir).expanduser().resolve()
    plan_path = run_path / "prior_art_plan.json"
    journal_path = run_path / "search_journal.json"
    chart_path = run_path / "claim_chart.json"
    report_path = run_path / "prior_art_report.json"

    if report_path.is_file():
        report = PriorArtReport.from_dict(_read_json(report_path))
    else:
        if not (plan_path.is_file() and journal_path.is_file() and chart_path.is_file()):
            raise PriorArtSearchClientError(
                "run missing plan/journal/chart for acknowledgment",
                code="run_incomplete",
            )
        plan = PriorArtSearchPlan.from_dict(_read_json(plan_path))
        journal = SearchJournal.from_dict(_read_json(journal_path))
        chart = ClaimChart.from_dict(_read_json(chart_path))
        report = build_operator_prior_art_report(plan, journal, chart)
        _write_json(report_path, report.to_dict())

    ack = build_human_coverage_acknowledgment(
        acknowledger_name=acknowledger_name,
        report=report,
        coverage_scope_text=coverage_scope_text,
    )
    ack_path = _write_json(run_path / "human_coverage_acknowledgment.json", ack.to_dict())

    checklist = build_operator_rule_checklist(
        subject_id=report.plan.subject_id,
        report=report,
        human_ack=ack,
        claim_complete=bool(claim_search_complete),
    )
    checklist_path = _write_json(
        run_path / "prior_art_rule_checklist.json", checklist.to_dict()
    )

    payload = {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "run_dir": str(run_path),
        "report_id": report.report_id,
        "report_digest": content_digest(report.to_dict()),
        "acknowledgment_path": str(ack_path),
        "checklist_path": str(checklist_path),
        "checklist_readiness": (
            checklist.readiness.value
            if hasattr(checklist.readiness, "value")
            else str(checklist.readiness)
        ),
        "prior_art_search_complete": bool(
            getattr(checklist, "prior_art_search_complete", False)
        ),
        "blocking_reason_codes": list(
            getattr(checklist, "blocking_reason_codes", ()) or ()
        ),
        "claim_search_complete_requested": bool(claim_search_complete),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        "generated_at_utc": utc_now_iso(),
    }
    assert_no_patentability_conclusions(payload)
    _write_json(run_path / "acknowledgment_summary.json", payload)
    return payload


__all__ = [
    "EXTENSIONS_SCHEMA",
    "PPS_DISCLAIMER",
    "PPS_PUBLIC_URL",
    "acknowledge_prior_art_run",
    "augment_plan_for_coverage",
    "build_coverage_adapter_registry",
    "build_human_coverage_acknowledgment",
    "build_operator_prior_art_report",
    "build_operator_rule_checklist",
    "build_pps_verification_checklist",
    "foreign_hits_from_snapshot",
    "load_citation_edges",
    "load_family_members",
    "load_foreign_hits",
    "load_npl_records",
    "persist_pps_checklist",
    "record_pps_verification",
    "show_pps_verification",
]
