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
    live_foreign: bool = False,
    enable_npl: bool = False,
    npl_catalog_path: str | Path | None = None,
    npl_licensed: bool = False,
    live_npl: bool = False,
    npl_providers: Sequence[str] = ("openalex", "crossref"),
    citation_graph_path: str | Path | None = None,
    family_graph_path: str | Path | None = None,
    max_live_results: int = 10,
) -> tuple[Any, dict[str, Any]]:
    """Build PriorArtAdapterRegistry + status metadata for operator search.

    Live backends:
    * ``live_foreign`` → EPO OPS (env ``EPO_OPS_KEY`` + ``EPO_OPS_SECRET``)
    * ``live_npl`` → OpenAlex + Crossref public metadata APIs
    """
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
    if enable_foreign or foreign_hits_path or foreign_snapshot_path or live_foreign:
        hits: list[Any] = []
        search_fn = None
        backends: list[str] = []
        if foreign_hits_path:
            hits.extend(load_foreign_hits(foreign_hits_path))
            backends.append("hits_file")
            status["foreign"]["hit_count"] = len(hits)
        if foreign_snapshot_path:
            snap_hits = foreign_hits_from_snapshot(foreign_snapshot_path)
            hits.extend(snap_hits)
            backends.append("snapshot")
            status["foreign"]["hit_count"] = len(hits)
        if live_foreign:
            from ipfs_datasets_py.processors.domains.uspto.providers.epo_ops_client import (
                build_epo_foreign_search_fn,
                has_epo_ops_credentials,
            )

            if has_epo_ops_credentials():
                search_fn = build_epo_foreign_search_fn(max_results=max_live_results)
                backends.append("epo_ops_live")
            else:
                backends.append("epo_ops_missing_credentials")
                status["foreign"]["warning"] = (
                    "live_foreign requested but EPO_OPS_KEY/EPO_OPS_SECRET unset; "
                    "register at https://developers.epo.org/"
                )
        if not hits and search_fn is None:
            backends.append("named_gap_no_backend")
        status["foreign"]["backend"] = "+".join(backends) if backends else None
        foreign_adapter = ForeignPatentAdapter(
            hits=hits,
            search_fn=search_fn,
            licensed=bool(foreign_licensed),
            accessible=True,
            default_rights_status=RightsStatus.PUBLIC,
            adapter_name=(
                "foreign_patent_epo_ops.v1" if search_fn is not None else "foreign_patent_metadata.v1"
            ),
        )
        status["foreign"]["enabled"] = True
        status["foreign"]["adapter_name"] = foreign_adapter.identity.adapter_name
        status["foreign"]["licensed"] = bool(foreign_licensed)
        status["foreign"]["live"] = bool(search_fn is not None)

    npl_adapter = None
    if enable_npl or npl_catalog_path or live_npl:
        records: list[Any] = []
        search_fn = None
        backends_npl: list[str] = []
        if npl_catalog_path:
            records = load_npl_records(npl_catalog_path)
            backends_npl.append("catalog_file")
            status["npl"]["record_count"] = len(records)
        if live_npl:
            from ipfs_datasets_py.processors.domains.uspto.providers.npl_public_clients import (
                build_npl_public_search_fn,
            )

            search_fn = build_npl_public_search_fn(
                providers=tuple(npl_providers or ("openalex", "crossref")),
                max_results=max_live_results,
                licensed=True,  # public metadata rights
            )
            backends_npl.append("openalex+crossref_live")
        if not records and search_fn is None:
            backends_npl.append("named_gap_no_backend")
        status["npl"]["backend"] = "+".join(backends_npl) if backends_npl else None
        # Live public metadata counts as licensed for adapter run; catalog may differ
        is_licensed = bool(
            (npl_licensed and records) or (live_npl and search_fn is not None)
        )
        npl_adapter = NplAdapter(
            records=records,
            search_fn=search_fn,
            licensed=is_licensed,
            accessible=True,
            default_rights_status=(
                RightsStatus.PUBLIC
                if live_npl
                else (
                    RightsStatus.LICENSED
                    if npl_licensed and records
                    else RightsStatus.UNLICENSED
                )
            ),
            adapter_name=(
                "npl_public_metadata.v1" if search_fn is not None else "npl_metadata.v1"
            ),
        )
        status["npl"]["enabled"] = True
        status["npl"]["adapter_name"] = npl_adapter.identity.adapter_name
        status["npl"]["licensed"] = is_licensed
        status["npl"]["live"] = bool(search_fn is not None)
        if npl_licensed and not records and not live_npl:
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


# ---------------------------------------------------------------------------
# Distinguishability matrix (overlap candidates — never patentability)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-/]{2,}")
_STOP = frozenset(
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
    }
)


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(str(text or ""))
        if t.lower() not in _STOP
    }


def build_distinguishability_matrix(
    plan: Any,
    journal: Any | None = None,
    chart: Any | None = None,
    *,
    max_docs: int = 12,
) -> dict[str, Any]:
    """Build a limitation × document token-overlap matrix for human drafting.

    Cells report **candidate lexical overlap only**. They do not mean a document
    teaches, anticipates, or renders obvious any claim element.
    """
    # Collect documents from chart entries or journal hits
    docs: dict[str, dict[str, Any]] = {}
    if chart is not None:
        for entry in chart.entries or ():
            did = entry.document_id
            docs.setdefault(
                did,
                {
                    "document_id": did,
                    "excerpts": [],
                    "ranks": [],
                    "scores": [],
                },
            )
            if entry.passage_excerpt:
                docs[did]["excerpts"].append(entry.passage_excerpt)
            docs[did]["ranks"].append(int(entry.rank))
            docs[did]["scores"].append(float(entry.score))
    if journal is not None:
        for rec in journal.records or ():
            for hit in rec.hits or ():
                did = hit.document_id
                docs.setdefault(
                    did,
                    {
                        "document_id": did,
                        "excerpts": [],
                        "ranks": [],
                        "scores": [],
                    },
                )
                if hit.passage_excerpt:
                    docs[did]["excerpts"].append(hit.passage_excerpt)
                docs[did]["ranks"].append(int(hit.rank))
                docs[did]["scores"].append(float(hit.score))
                title = (hit.metadata or {}).get("title")
                if title:
                    docs[did]["excerpts"].append(str(title))

    # Rank docs by best score
    ranked_docs = sorted(
        docs.values(),
        key=lambda d: max(d["scores"] or [0.0]),
        reverse=True,
    )[: int(max_docs)]

    limitations = list(plan.limitations or ())[:32]
    cells: list[dict[str, Any]] = []
    for lim in limitations:
        lim_toks = _tokens(lim.text)
        for doc in ranked_docs:
            doc_text = " ".join(doc["excerpts"]) or doc["document_id"]
            doc_toks = _tokens(doc_text)
            if not lim_toks:
                overlap = 0.0
                shared: list[str] = []
            else:
                shared = sorted(lim_toks & doc_toks)
                overlap = round(len(shared) / max(len(lim_toks), 1), 4)
            missing = sorted(lim_toks - doc_toks)[:12]
            cells.append(
                {
                    "limitation_id": lim.limitation_id,
                    "claim_number": lim.claim_number,
                    "document_id": doc["document_id"],
                    "lexical_overlap": overlap,
                    "shared_tokens": shared[:12],
                    "limitation_tokens_absent_from_excerpt": missing,
                    "review_label": "candidate_overlap_only",
                    "not_a_determination": (
                        "Overlap is lexical only. Does not teach, anticipate, "
                        "or render obvious any element."
                    ),
                }
            )

    # Suggest distinguishability drafting anchors: low-overlap limitations
    drafting_hints: list[dict[str, Any]] = []
    for lim in limitations:
        lim_cells = [c for c in cells if c["limitation_id"] == lim.limitation_id]
        if not lim_cells:
            continue
        max_ov = max(c["lexical_overlap"] for c in lim_cells)
        # Tokens absent across all compared docs
        absent_all = set(_tokens(lim.text))
        for c in lim_cells:
            absent_all &= set(c["limitation_tokens_absent_from_excerpt"])
        drafting_hints.append(
            {
                "limitation_id": lim.limitation_id,
                "claim_number": lim.claim_number,
                "candidate_text": str(lim.text)[:240],
                "max_lexical_overlap_vs_hits": max_ov,
                "tokens_absent_from_all_compared_excerpts": sorted(absent_all)[:16],
                "drafting_note": (
                    "Consider emphasizing elements with low lexical overlap "
                    "or tokens absent from candidate hit excerpts when drafting "
                    "remarks. Human legal judgment required."
                ),
            }
        )

    return {
        "schema": "patlaw-distinguishability-matrix-v1",
        "subject_id": plan.subject_id,
        "plan_id": plan.plan_id,
        "limitation_count": len(limitations),
        "document_count": len(ranked_docs),
        "documents": [
            {
                "document_id": d["document_id"],
                "best_rank": min(d["ranks"]) if d["ranks"] else None,
                "best_score": max(d["scores"]) if d["scores"] else None,
                "excerpt_preview": " ".join(d["excerpts"])[:300],
            }
            for d in ranked_docs
        ],
        "cells": cells,
        "drafting_hints": drafting_hints,
        "purpose": (
            "Candidate lexical overlap matrix for human distinguishability "
            "drafting. Not a novelty, obviousness, or patentability determination."
        ),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        "generated_at_utc": utc_now_iso(),
    }


def build_and_persist_distinguishability_matrix(
    run_dir: str | Path,
) -> dict[str, Any]:
    """Load run artifacts and write distinguishability_matrix.json."""
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        ClaimChart,
        PriorArtSearchPlan,
        assert_no_patentability_conclusions,
    )
    from ipfs_datasets_py.processors.domains.patent.search_journal import (
        SearchJournal,
    )

    run_path = Path(run_dir).expanduser().resolve()
    plan = PriorArtSearchPlan.from_dict(_read_json(run_path / "prior_art_plan.json"))
    journal = None
    chart = None
    if (run_path / "search_journal.json").is_file():
        journal = SearchJournal.from_dict(_read_json(run_path / "search_journal.json"))
    if (run_path / "claim_chart.json").is_file():
        chart = ClaimChart.from_dict(_read_json(run_path / "claim_chart.json"))
    matrix = build_distinguishability_matrix(plan, journal, chart)
    assert_no_patentability_conclusions(matrix)
    path = _write_json(run_path / "distinguishability_matrix.json", matrix)
    return {
        "schema": PRIOR_ART_CLIENT_SCHEMA,
        "ok": True,
        "run_dir": str(run_path),
        "matrix_path": str(path),
        "limitation_count": matrix["limitation_count"],
        "document_count": matrix["document_count"],
        "cell_count": len(matrix["cells"]),
        "disclaimer": PRIOR_ART_DISCLAIMER_SHORT,
        "generated_at_utc": utc_now_iso(),
    }


__all__ = [
    "EXTENSIONS_SCHEMA",
    "PPS_DISCLAIMER",
    "PPS_PUBLIC_URL",
    "acknowledge_prior_art_run",
    "augment_plan_for_coverage",
    "build_and_persist_distinguishability_matrix",
    "build_coverage_adapter_registry",
    "build_distinguishability_matrix",
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
