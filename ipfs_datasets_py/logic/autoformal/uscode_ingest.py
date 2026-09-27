"""Ingest U.S. Code through sparse GraphRAG retrieval into autoformal spans.

Retrieved hits are source-span candidates. Similarity is not legal authority,
a compile is not a proof, and this module does not call a model or Lake.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.autoformal.constitution_inventory import (
    _sentences,
    census_ledger,
    tag_facets,
)


SCHEMA = "uscode-sparse-autoformal-span-v1"
RETRIEVAL_METHOD = "sparse_bm25"
FORMAL_LOGIC = re.compile(
    r"\b(?:shall|must|may|required|prohibit(?:ed)?|authorized|eligible|entitled|"
    r"except|unless|provided|subject\s+to|not\s+later\s+than|repealed|"
    r"means|defined|includes|penalty|violation)\b",
    re.IGNORECASE,
)


def is_formal_logic(text: str) -> bool:
    """A deontic, temporal, conditional, or definition cue. Not an admit."""

    return bool(FORMAL_LOGIC.search(str(text or "")))


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _hit_mapping(hit: Any) -> dict[str, Any]:
    if hit is None:
        return {}
    if isinstance(hit, Mapping):
        return dict(hit)
    payload = {}
    for name in (
        "entry_cid",
        "legal_id",
        "document_id",
        "title",
        "title_number",
        "section",
        "section_number",
        "canonical_citation",
        "citation",
        "release_point",
        "text",
        "score",
        "record_sha256",
        "text_sha256",
        "source",
        "family",
    ):
        if hasattr(hit, name):
            payload[name] = getattr(hit, name)
    return payload


def normalize_uscode_hit(hit: Any) -> dict[str, Any]:
    """Project a sparse GraphRAG hit or verified corpus row to a document."""

    raw = _hit_mapping(hit)
    title = _clean(raw.get("title") or raw.get("title_number")) or "unknown"
    section = _clean(raw.get("section") or raw.get("section_number")) or "unknown"
    citation = (
        _clean(raw.get("canonical_citation"))
        or _clean(raw.get("citation"))
        or f"{title} U.S.C. {section}"
    )
    text = _clean(raw.get("text"))
    entry_cid = _clean(raw.get("entry_cid"))
    legal_id = _clean(raw.get("legal_id") or raw.get("document_id"))
    document_id = legal_id or entry_cid or citation
    score = raw.get("score")
    try:
        score_value = float(score) if score is not None and score != "" else None
    except (TypeError, ValueError):
        score_value = None
    return {
        "canonical_citation": citation,
        "document_id": document_id,
        "entry_cid": entry_cid,
        "legal_id": legal_id,
        "record_sha256": _clean(raw.get("record_sha256")),
        "release_point": _clean(raw.get("release_point")),
        "retrieval_method": RETRIEVAL_METHOD,
        "score": score_value,
        "section": section,
        "source": _clean(raw.get("source")) or "uscode",
        "text": text,
        "text_sha256": _clean(raw.get("text_sha256"))
        or (hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""),
        "title": title,
    }


def sparse_graphrag_searcher(engine_or_client: Any, **bound: Any) -> Callable[..., Any]:
    """Bind the public BM25 sparse GraphRAG entry point for U.S. Code ingest."""

    from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import bm25_search

    def search(query: str, **kwargs: Any) -> Any:
        options = {"hydrate": True, "include_content": True, **bound, **kwargs}
        return bm25_search(engine_or_client, query, **options)

    return search


def local_sparse_graphrag_searcher(
    release_root: Any,
    *,
    repo_id: str,
    revision: str,
    cache_dir: Any | None = None,
    **bound: Any,
) -> Callable[..., Any]:
    """Offline BM25 searcher over a pinned local sparse GraphRAG release."""

    from pathlib import Path

    from ipfs_datasets_py.retrieval.hf_graphrag.query import BoundedRemoteQueryEngine
    from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
        ImmutableHubResolver,
        LocalRootTransport,
    )

    root = Path(release_root)
    resolver = ImmutableHubResolver(
        repo_id=repo_id,
        revision=revision,
        cache_dir=Path(cache_dir) if cache_dir is not None else root / ".resolver-cache",
        transport=LocalRootTransport(root),
        local_root=root,
    )
    return sparse_graphrag_searcher(BoundedRemoteQueryEngine(resolver), **bound)


def hub_sparse_graphrag_searcher(
    *,
    repo_id: str,
    revision: str,
    cache_dir: Any | None = None,
    **bound: Any,
) -> Callable[..., Any]:
    """BM25 searcher over a pinned Hugging Face sparse GraphRAG revision."""

    from pathlib import Path

    from ipfs_datasets_py.retrieval.hf_graphrag.query import BoundedRemoteQueryEngine
    from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
        HuggingFaceHubTransport,
        ImmutableHubResolver,
    )

    resolver = ImmutableHubResolver(
        repo_id=repo_id,
        revision=revision,
        cache_dir=Path(cache_dir) if cache_dir is not None else None,
        transport=HuggingFaceHubTransport(),
    )
    return sparse_graphrag_searcher(BoundedRemoteQueryEngine(resolver), **bound)


def pinned_sparse_graphrag_searcher(
    *,
    repo_id: str,
    revision: str,
    release_root: Any | None = None,
    cache_dir: Any | None = None,
    **bound: Any,
) -> Callable[..., Any]:
    """Prefer a local pinned root; otherwise fetch the Hub revision."""

    if release_root is not None:
        return local_sparse_graphrag_searcher(
            release_root,
            repo_id=repo_id,
            revision=revision,
            cache_dir=cache_dir,
            **bound,
        )
    return hub_sparse_graphrag_searcher(
        repo_id=repo_id,
        revision=revision,
        cache_dir=cache_dir,
        **bound,
    )


def retrieve_uscode_hits(
    searcher: Callable[..., Any],
    query: str,
    *,
    exclude_document_ids: Iterable[str] = (),
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run sparse GraphRAG retrieval and normalize hits. Does not compile."""

    result = searcher(query, **kwargs)
    if hasattr(result, "results"):
        rows = list(result.results)
    elif isinstance(result, Mapping) and "results" in result:
        rows = list(result.get("results") or [])
    elif isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
        rows = list(result)
    else:
        rows = []
    hits = [normalize_uscode_hit(row) for row in rows if normalize_uscode_hit(row).get("text")]
    skip = {str(item) for item in exclude_document_ids if str(item)}
    if skip:
        hits = [hit for hit in hits if str(hit.get("document_id") or "") not in skip]
    return hits


def inventory_uscode_documents(
    documents: Iterable[Any],
    *,
    query: str = "",
    release_id: str = "",
) -> dict[str, Any]:
    """One uncompiled span per sentence. No compiler and no model."""

    docs = [normalize_uscode_hit(item) for item in documents]
    docs = [item for item in docs if item.get("text")]
    spans: list[dict[str, Any]] = []
    for ordinal, document in enumerate(docs):
        sentences = _sentences(document["text"]) or [document["text"]]
        unit_id = document["document_id"]
        for index, sentence in enumerate(sentences, start=1):
            identity = {
                "canonical_citation": document["canonical_citation"],
                "entry_cid": document["entry_cid"],
                "legal_id": document["legal_id"],
                "ordinal": len(spans),
                "query": query,
                "release_id": release_id,
                "release_point": document["release_point"],
                "schema_version": SCHEMA,
                "section": document["section"],
                "text_sha256": hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
                "title": document["title"],
                "unit_id": unit_id,
            }
            digest = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest()
            spans.append(
                {
                    "canonical_citation": document["canonical_citation"],
                    "document_ordinal": ordinal,
                    "entry_cid": document["entry_cid"],
                    "id": f"{unit_id}.span-{index}",
                    "legal_id": document["legal_id"],
                    "reason": "",
                    "release_point": document["release_point"],
                    "retrieval_method": RETRIEVAL_METHOD,
                    "retrieval_score": document["score"],
                    "section": document["section"],
                    "source_span_id": f"uscode-span-{digest}",
                    "span_text_sha256": identity["text_sha256"],
                    "status": "uncompiled",
                    "text": sentence,
                    "title": document["title"],
                    "unit_id": unit_id,
                }
            )
    return {
        "admitted": False,
        "compiled": False,
        "documents": docs,
        "edges": [],
        "formalized": False,
        "query": query,
        "release_id": release_id,
        "retrieval": {
            "authority": False,
            "document_count": len(docs),
            "method": RETRIEVAL_METHOD,
            "query": query,
            "span_count": len(spans),
        },
        "span_identity_schema": SCHEMA,
        "spans": spans,
    }


def census_uscode_ledger(ledger: dict[str, Any], compile_one) -> dict[str, Any]:
    """Compile each uncompiled U.S. Code span. Abstain becomes a named gap."""

    report = census_ledger(ledger, compile_one)
    tag_facets(report["ledger"])
    for span in report["ledger"]["spans"]:
        if span.get("status") == "roundtrip_ok":
            span["status"] = "compiled"
    report["ledger"]["compiled"] = False
    report["ledger"]["admitted"] = False
    report["ledger"]["formalized"] = False
    return report
