"""Load JusticeDAO patent-legal BM25 + graph (+ vector) indexes for revision search.

Task-board track (PATLAW-170–179 / G211–G212) publishes:

* ``justicedao/patent-legal-corpus``
* ``justicedao/patent-legal-bm25``
* ``justicedao/patent-legal-vectors``
* ``justicedao/patent-legal-knowledge-graph``

This client downloads (or reuses the HF hub cache), materializes a local
:class:`PatentIndexBundle` via :func:`build_patent_indexes`, and runs
:func:`hybrid_search` for revision law guides.

No private matter text is sent to remote embedding providers. Default
embedding is local hash. Hub access is read-only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

# Default Hub repositories from patent hub layout v2 (PATLAW HF track).
DEFAULT_ORG: Final = "justicedao"
DEFAULT_CORPUS_REPO: Final = f"{DEFAULT_ORG}/patent-legal-corpus"
DEFAULT_BM25_REPO: Final = f"{DEFAULT_ORG}/patent-legal-bm25"
DEFAULT_KG_REPO: Final = f"{DEFAULT_ORG}/patent-legal-knowledge-graph"
DEFAULT_VECTORS_REPO: Final = f"{DEFAULT_ORG}/patent-legal-vectors"

CORPUS_DOCS_PATH: Final = "indexes/corpus/documents.jsonl"
KG_EDGES_PATH: Final = "indexes/knowledge_graph/edges.jsonl"
KG_NODES_PATH: Final = "indexes/knowledge_graph/nodes.jsonl"

PUBLIC_LEGAL_INDEX_SCHEMA: Final = "patlaw-public-legal-index-client-v1"


class PublicLegalIndexError(PortfolioAutomationError):
    """Fail-closed public legal index client error."""


def _hf_download(repo_id: str, filename: str, *, revision: str | None = None) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise PublicLegalIndexError(
            "huggingface_hub required to load patent-legal indexes "
            "(pip install huggingface_hub)",
            code="hf_hub_missing",
        ) from exc
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        revision=revision or os.environ.get("PATENT_LEGAL_HF_REVISION") or "main",
    )
    return Path(path)


def iter_jsonl(path: Path):
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_corpus_documents(
    *,
    repo_id: str = DEFAULT_CORPUS_REPO,
    local_path: Path | None = None,
    max_docs: int | None = None,
) -> list[dict[str, Any]]:
    """Load public legal corpus document rows from Hub or a local jsonl."""
    if local_path is not None and Path(local_path).is_file():
        path = Path(local_path)
    else:
        path = _hf_download(repo_id, CORPUS_DOCS_PATH)
    out: list[dict[str, Any]] = []
    for row in iter_jsonl(path):
        if not isinstance(row, Mapping):
            continue
        out.append(dict(row))
        if max_docs is not None and len(out) >= int(max_docs):
            break
    return out


def load_graph_edges(
    *,
    repo_id: str = DEFAULT_KG_REPO,
    local_path: Path | None = None,
    max_edges: int | None = None,
) -> list[dict[str, Any]]:
    if local_path is not None and Path(local_path).is_file():
        path = Path(local_path)
    else:
        path = _hf_download(repo_id, KG_EDGES_PATH)
    out: list[dict[str, Any]] = []
    for row in iter_jsonl(path):
        if isinstance(row, Mapping):
            out.append(dict(row))
        if max_edges is not None and len(out) >= int(max_edges):
            break
    return out


def corpus_rows_to_index_documents(
    rows: Sequence[Mapping[str, Any]],
) -> list[Any]:
    """Convert corpus jsonl rows into :class:`PatentIndexDocument` instances."""
    from ipfs_datasets_py.processors.domains.patent.indexing import PatentIndexDocument
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        DisclosureClass,
        SourceLink,
    )

    docs: list[Any] = []
    for row in rows:
        record_id = str(row.get("record_id") or "").strip()
        text = str(row.get("text") or "").strip()
        title = str(row.get("title") or row.get("citation") or record_id).strip()
        if not record_id or not (text or title):
            continue
        source_cid = str(
            row.get("source_cid") or row.get("document_cid") or f"cid:{record_id}"
        )
        # Map classification strings to DisclosureClass
        clf = str(row.get("classification") or "public_official").strip().lower()
        try:
            disclosure = DisclosureClass(clf)
        except Exception:
            disclosure = DisclosureClass.PUBLIC_OFFICIAL

        citation = str(row.get("citation") or "")
        family = str(row.get("family") or "")
        section_id = str(row.get("section_id") or "")
        field_values = {
            "title": title[:2000],
            "description": text[:100_000],
            "legal_bases": citation,
            "numbers": section_id or record_id,
            "abstract": (text[:400] if text else title)[:400],
        }
        docs.append(
            PatentIndexDocument(
                document_id=record_id,
                field_values=field_values,
                source_links=[
                    SourceLink(
                        source_cid=source_cid,
                        artifact_id=f"artifact:{record_id}",
                    )
                ],
                disclosure=disclosure,
                tenant_id="tenant-public",
                effective_from_utc=_to_iso_utc(row.get("effective_start")),
                effective_to_utc=_to_iso_utc(row.get("effective_end")),
                metadata={
                    "family": family,
                    "citation": citation,
                    "authority_kind": str(row.get("authority_kind") or ""),
                },
            )
        )
    return docs


def _to_iso_utc(value: Any) -> str | None:
    """Normalize date or datetime strings to ISO-8601 UTC for index filters."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Already timestamp-like
    if "T" in text:
        if text.endswith("Z"):
            return text[:-1] + "+00:00"
        return text
    # Date only YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return f"{text}T00:00:00+00:00"
    return None


def edges_to_graph_edges(rows: Sequence[Mapping[str, Any]]) -> list[Any]:
    """Convert KG edge jsonl rows into GraphEdge-compatible mappings."""
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        AuthorityClaim,
        DisclosureClass,
        EdgeKind,
        EdgeProvenance,
    )

    edges: list[dict[str, Any]] = []
    for row in rows:
        try:
            kind = str(row.get("kind") or "related")
            # Map unknown kinds to RELATED
            try:
                EdgeKind(kind)
            except Exception:
                kind = EdgeKind.OTHER.value
            links = row.get("source_links") or []
            if not links and row.get("source_cid"):
                links = [
                    {
                        "source_cid": row["source_cid"],
                        "artifact_id": str(row.get("edge_id") or "artifact:edge"),
                    }
                ]
            edges.append(
                {
                    "schema_version": row.get("schema_version")
                    or RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                    "edge_id": str(row.get("edge_id") or ""),
                    "subject_id": str(row.get("subject_id") or ""),
                    "object_id": str(row.get("object_id") or ""),
                    "kind": kind,
                    "provenance": str(
                        row.get("provenance") or EdgeProvenance.SOURCE_DERIVED.value
                    ),
                    "authority_claim": str(
                        row.get("authority_claim") or AuthorityClaim.SOURCE_BOUND.value
                    ),
                    "source_links": links,
                    "disclosure": str(
                        row.get("disclosure") or DisclosureClass.PUBLIC_OFFICIAL.value
                    ),
                    "tenant_id": str(row.get("tenant_id") or "tenant-public"),
                    "weight": float(row.get("weight") or 1.0),
                    "metadata": {
                        str(k): str(v)
                        for k, v in dict(row.get("metadata") or {}).items()
                    },
                }
            )
        except Exception:
            continue
    return edges


@dataclass
class PublicLegalIndexSession:
    """In-memory hybrid index session over Hub public legal corpora."""

    bundle: Any
    filters: Any
    corpus_repo: str = DEFAULT_CORPUS_REPO
    kg_repo: str = DEFAULT_KG_REPO
    document_count: int = 0
    edge_count: int = 0
    doc_text_by_id: dict[str, str] = field(default_factory=dict)
    citation_by_id: dict[str, str] = field(default_factory=dict)
    loaded_at_utc: str = ""

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        query_id: str = "rev-law",
    ) -> dict[str, Any]:
        from ipfs_datasets_py.processors.domains.patent.hybrid_retrieval import (
            hybrid_search,
        )
        from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
            DisclosureClass,
        )

        result = hybrid_search(
            query,
            self.bundle,
            filters=self.filters,
            query_id=query_id,
            top_k=top_k,
            allow_remote_embeddings=False,
            query_disclosure=DisclosureClass.PUBLIC_USER,
        )
        hits: list[dict[str, Any]] = []
        fusion = result.fusion
        for hit in fusion.fused_hits[:top_k]:
            doc_id = hit.document_id
            text = self.doc_text_by_id.get(doc_id, "")
            excerpt = text[:900] if text else ""
            hits.append(
                {
                    "rank": hit.rank,
                    "document_id": doc_id,
                    "score": round(float(hit.score), 6),
                    "family": hit.family.value
                    if hasattr(hit.family, "value")
                    else str(hit.family),
                    "citation": self.citation_by_id.get(doc_id, ""),
                    "source_cids": [
                        link.source_cid for link in (hit.source_links or ())
                    ],
                    "excerpt": excerpt,
                    "matched_fields": list(hit.matched_fields or ()),
                }
            )
        return {
            "schema": PUBLIC_LEGAL_INDEX_SCHEMA,
            "query": query,
            "top_k": top_k,
            "hit_count": len(hits),
            "hits": hits,
            "bm25_hit_count": len(fusion.bm25_hits),
            "vector_hit_count": len(fusion.vector_hits),
            "graph_hit_count": len(fusion.graph_hits),
            "corpus_repo": self.corpus_repo,
            "kg_repo": self.kg_repo,
            "document_count": self.document_count,
            "edge_count": self.edge_count,
            "loaded_at_utc": self.loaded_at_utc,
            "generated_at_utc": utc_now_iso(),
        }


def _public_filters():
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        DisclosureClass,
        PreRankingFilters,
    )

    # PreRankingFilters expects ISO-8601 UTC; normalize Z suffix.
    as_of = utc_now_iso()
    if as_of.endswith("Z"):
        as_of = as_of[:-1] + "+00:00"
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc=as_of,
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
        ),
        applied=True,
        filter_receipt_id="filter:public-legal-index-client",
    )


_SESSION: PublicLegalIndexSession | None = None


def get_public_legal_index_session(
    *,
    corpus_repo: str = DEFAULT_CORPUS_REPO,
    kg_repo: str = DEFAULT_KG_REPO,
    max_docs: int | None = None,
    max_edges: int | None = None,
    force_reload: bool = False,
    local_corpus_path: Path | None = None,
    local_edges_path: Path | None = None,
) -> PublicLegalIndexSession:
    """Load (or return cached) hybrid index session from HF Hub."""
    global _SESSION
    if _SESSION is not None and not force_reload:
        return _SESSION

    from ipfs_datasets_py.processors.domains.patent.indexing import build_patent_indexes

    rows = load_corpus_documents(
        repo_id=corpus_repo, local_path=local_corpus_path, max_docs=max_docs
    )
    if not rows:
        raise PublicLegalIndexError(
            f"no corpus documents loaded from {corpus_repo}",
            code="empty_corpus",
        )
    docs = corpus_rows_to_index_documents(rows)
    edge_rows = load_graph_edges(
        repo_id=kg_repo, local_path=local_edges_path, max_edges=max_edges
    )
    edges = edges_to_graph_edges(edge_rows)

    filters = _public_filters()
    # build_patent_indexes may drop edges that fail validation — pass soft
    # build_patent_indexes requires a CIDv1-shaped string; pin a stable public-legal marker.
    from ipfs_datasets_py.processors.domains.patent.indexing import DEFAULT_CORPUS_CID

    bundle = build_patent_indexes(
        docs,
        filters=filters,
        edges=edges,
        allow_remote=False,
        corpus_cid=DEFAULT_CORPUS_CID,
    )

    text_map = {
        str(r.get("record_id")): str(r.get("text") or "")
        for r in rows
        if r.get("record_id")
    }
    cite_map = {
        str(r.get("record_id")): str(r.get("citation") or r.get("title") or "")
        for r in rows
        if r.get("record_id")
    }

    _SESSION = PublicLegalIndexSession(
        bundle=bundle,
        filters=filters,
        corpus_repo=corpus_repo,
        kg_repo=kg_repo,
        document_count=len(docs),
        edge_count=len(edges),
        doc_text_by_id=text_map,
        citation_by_id=cite_map,
        loaded_at_utc=utc_now_iso(),
    )
    return _SESSION


def search_public_legal(
    query: str,
    *,
    top_k: int = 8,
    **session_kwargs: Any,
) -> dict[str, Any]:
    """Convenience: ensure session + hybrid search."""
    session = get_public_legal_index_session(**session_kwargs)
    return session.search(query, top_k=top_k)


def build_revision_retrieval_queries(case: Any) -> list[str]:
    """Construct search queries from a revision case + letter analysis."""
    queries: list[str] = []
    trigger = getattr(case, "trigger", None)
    la = (getattr(case, "letter_analysis", None) or {}).get("analysis") or {}

    if trigger is not None:
        if getattr(trigger, "document_code", None):
            queries.append(str(trigger.document_code))
        if getattr(trigger, "document_description", None):
            queries.append(str(trigger.document_description)[:200])
        kind = getattr(trigger, "kind", "") or ""
        if "missing" in kind:
            queries.append("37 CFR 1.53 missing parts incomplete application")
        if "office_action" in kind or "nonfinal" in kind or "final" in kind:
            queries.append(
                "37 CFR 1.111 1.121 office action response claim amendments remarks"
            )

    for rej in (la.get("rejections") or [])[:3]:
        queries.append(str(rej)[:240])
    for cite in (la.get("citations") or [])[:5]:
        queries.append(str(cite))
    for instr in (la.get("response_instructions") or [])[:2]:
        queries.append(str(instr)[:200])

    # Always include core response rules
    queries.extend(
        [
            "37 C.F.R. § 1.121 manner of making amendments",
            "37 C.F.R. § 1.111 reply by applicant",
            "35 U.S.C. 103 obviousness",
        ]
    )
    # de-dup preserve order
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        qn = " ".join(str(q).split())
        if not qn or qn.lower() in seen:
            continue
        seen.add(qn.lower())
        out.append(qn)
    return out[:12]


def retrieve_for_revision_case(
    case: Any,
    *,
    top_k: int = 6,
    max_docs: int | None = None,
) -> dict[str, Any]:
    """Run hybrid retrieval for a revision case; return merged unique hits."""
    queries = build_revision_retrieval_queries(case)
    try:
        session = get_public_legal_index_session(max_docs=max_docs)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": PUBLIC_LEGAL_INDEX_SCHEMA,
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "queries": queries,
            "hits": [],
            "disclaimer": (
                "Public legal hybrid index unavailable. "
                "Hub repos: justicedao/patent-legal-{corpus,bm25,vectors,knowledge-graph}."
            ),
        }

    merged: dict[str, dict[str, Any]] = {}
    per_query: list[dict[str, Any]] = []
    for q in queries:
        try:
            res = session.search(q, top_k=top_k, query_id=f"rev:{q[:40]}")
        except Exception as exc:  # noqa: BLE001
            per_query.append({"query": q, "error": f"{type(exc).__name__}:{exc}"})
            continue
        per_query.append(
            {
                "query": q,
                "hit_count": res.get("hit_count"),
                "top_ids": [h["document_id"] for h in (res.get("hits") or [])[:5]],
            }
        )
        for h in res.get("hits") or []:
            doc_id = h["document_id"]
            prev = merged.get(doc_id)
            if prev is None or float(h.get("score") or 0) > float(prev.get("score") or 0):
                merged[doc_id] = dict(h)
                merged[doc_id]["matched_queries"] = list(
                    dict.fromkeys(
                        (prev or {}).get("matched_queries", []) + [q[:80]]
                    )
                )

    ranked = sorted(
        merged.values(), key=lambda h: float(h.get("score") or 0), reverse=True
    )
    return {
        "schema": PUBLIC_LEGAL_INDEX_SCHEMA,
        "ok": True,
        "queries": queries,
        "per_query": per_query,
        "hit_count": len(ranked),
        "hits": ranked[: max(top_k * 2, 12)],
        "index": {
            "corpus_repo": session.corpus_repo,
            "kg_repo": session.kg_repo,
            "document_count": session.document_count,
            "edge_count": session.edge_count,
            "loaded_at_utc": session.loaded_at_utc,
        },
        "generated_at_utc": utc_now_iso(),
        "disclaimer": (
            "Hybrid BM25+vector+graph hits from public JusticeDAO Hub indexes. "
            "Decision support only — not legal advice."
        ),
    }


__all__ = [
    "DEFAULT_BM25_REPO",
    "DEFAULT_CORPUS_REPO",
    "DEFAULT_KG_REPO",
    "DEFAULT_VECTORS_REPO",
    "PUBLIC_LEGAL_INDEX_SCHEMA",
    "PublicLegalIndexError",
    "PublicLegalIndexSession",
    "build_revision_retrieval_queries",
    "corpus_rows_to_index_documents",
    "get_public_legal_index_session",
    "load_corpus_documents",
    "load_graph_edges",
    "retrieve_for_revision_case",
    "search_public_legal",
]
