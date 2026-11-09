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


SOURCE_COORDINATE_SCHEMA = "uscode-source-coordinates/v1"
SOURCE_COORDINATE_PROFILE = "python_whitespace_collapse_sentence_inventory/v1"
SOURCE_COORDINATE_LIMITS = {
    "max_documents": 128,
    "max_text_bytes": 1024 * 1024,
    "max_total_text_bytes": 8 * 1024 * 1024,
    "max_spans": 8192,
    "max_metadata_bytes": 64 * 1024,
    "max_report_bytes": 32 * 1024 * 1024,
}


class USCodeSourceCoordinatesError(ValueError):
    """Exact supplied text, coordinate replay, or a finite bound differs."""


def _source_coordinates_wire(value: Any, maximum: int) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise USCodeSourceCoordinatesError("finite UTF8 JSON required") from error
    if len(raw) > maximum:
        raise USCodeSourceCoordinatesError("complete source-coordinate byte bound exceeded")
    return raw


def _source_coordinates_limits(limits: Mapping[str, int] | None) -> dict[str, int]:
    if limits is not None and type(limits) is not dict:
        raise USCodeSourceCoordinatesError("lower-only source-coordinate limits required")
    result = dict(SOURCE_COORDINATE_LIMITS)
    for name, value in (limits or {}).items():
        if name not in result or type(value) is not int or not 0 < value <= result[name]:
            raise USCodeSourceCoordinatesError("unknown or raised source-coordinate limit: " + str(name))
        result[name] = value
    return result


def _source_coordinates_metadata(value: dict, maximum: int) -> dict:
    # Refuse non-JSON metadata rather than coerce objects into identity strings.
    pending = [(value, 0)]
    visited = 0
    minimum_bytes = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        minimum_bytes += 1  # Every JSON node consumes at least one byte.
        if depth > 32:
            raise USCodeSourceCoordinatesError("source metadata nesting bound exceeded")
        if type(item) in (dict, list):
            if visited + len(pending) + len(item) > maximum:
                raise USCodeSourceCoordinatesError("source metadata node bound exceeded")
            if type(item) is dict:
                for key in item:
                    if type(key) is not str:
                        raise USCodeSourceCoordinatesError("source metadata requires string JSON keys")
                    minimum_bytes += len(key)
                    if minimum_bytes > maximum:
                        raise USCodeSourceCoordinatesError("source metadata byte bound exceeded")
                children = item.values()
            else:
                children = item
            pending.extend((child, depth + 1) for child in children)
        elif type(item) is str:
            minimum_bytes += len(item)
        elif item is not None and type(item) not in (int, float, bool):
            raise USCodeSourceCoordinatesError("source metadata requires ordinary finite JSON")
        if minimum_bytes > maximum:
            raise USCodeSourceCoordinatesError("source metadata byte bound exceeded")
    _source_coordinates_wire(value, maximum)
    # Keep nested insertion order: legacy identity coercion uses str(value).
    # Canonical serialization is for seals, not a change to caller metadata.
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _source_coordinates_boundaries(text: str, positions: list[int]) -> dict[int, int]:
    """Map requested normalized token boundaries in one monotone source scan."""
    requested = sorted(set(positions))
    result: dict[int, int] = {}
    index = 0
    normalized_start = 0
    for token in re.finditer(r"\S+", text):
        normalized_end = normalized_start + token.end() - token.start()
        while index < len(requested) and requested[index] <= normalized_end:
            position = requested[index]
            if position < normalized_start:
                raise USCodeSourceCoordinatesError("span boundary falls in collapsed whitespace")
            result[position] = token.start() + position - normalized_start
            index += 1
        normalized_start = normalized_end + 1
        if index == len(requested):
            break
    if index != len(requested):
        raise USCodeSourceCoordinatesError("normalized source boundary is unavailable")
    return result


def uscode_source_coordinates_sha256(report: Mapping[str, Any]) -> str:
    """Hash the FULL canonical report, including its content seal."""
    return hashlib.sha256(_source_coordinates_wire(
        report, SOURCE_COORDINATE_LIMITS["max_report_bytes"])).hexdigest()


def inventory_uscode_source_coordinates(
    documents: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    query: str = "",
    release_id: str = "",
    limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Bind legacy spans to exact supplied text occurrences without changing IDs.

    This separate report retains every supplied document, including empty text.
    Coordinates address the decoded input field, before Python whitespace
    collapse. They do not recover upstream trimming, markup, Parquet bytes or
    an authenticated legal source. The historical inventory remains unchanged.
    """
    bounds = _source_coordinates_limits(limits)
    if type(documents) not in (list, tuple) or len(documents) > bounds["max_documents"]:
        raise USCodeSourceCoordinatesError("bounded document list or tuple required")
    if type(query) is not str or type(release_id) is not str:
        raise USCodeSourceCoordinatesError("query and release_id must be exact strings")
    if len(query) + len(release_id) > bounds["max_metadata_bytes"]:
        raise USCodeSourceCoordinatesError("query and release_id byte bound exceeded")
    _source_coordinates_wire({"query": query, "release_id": release_id}, bounds["max_metadata_bytes"])
    inputs = []
    views = []
    total_bytes = 0
    span_count = 0
    document_ordinal = 0
    for ordinal, document in enumerate(documents):
        if not isinstance(document, Mapping) or type(document.get("text")) is not str:
            raise USCodeSourceCoordinatesError("each document requires an exact string text field")
        if len(document) > bounds["max_metadata_bytes"] + 1:
            raise USCodeSourceCoordinatesError("source metadata node bound exceeded")
        text = document["text"]
        if (len(text) > bounds["max_text_bytes"]
                or total_bytes + len(text) > bounds["max_total_text_bytes"]):
            raise USCodeSourceCoordinatesError("complete source text byte bound exceeded")
        try:
            raw = text.encode("utf-8")
        except UnicodeError as error:
            raise USCodeSourceCoordinatesError("source text must encode as exact UTF8") from error
        total_bytes += len(raw)
        if len(raw) > bounds["max_text_bytes"] or total_bytes > bounds["max_total_text_bytes"]:
            raise USCodeSourceCoordinatesError("complete source text byte bound exceeded")
        metadata = _source_coordinates_metadata(
            {key: value for key, value in document.items() if key != "text"}, bounds["max_metadata_bytes"])
        normalized = _clean(text)
        if normalized:
            # Count the existing _sentences delimiter before the legacy owner
            # allocates span rows. Segmentation and IDs still come from it.
            span_count += 1
            if span_count > bounds["max_spans"]:
                raise USCodeSourceCoordinatesError("complete source span count exceeds bound")
            for _ in re.finditer(r"(?<=[.!?])\s+", normalized):
                span_count += 1
                if span_count > bounds["max_spans"]:
                    raise USCodeSourceCoordinatesError("complete source span count exceeds bound")
        views.append({
            "input_document_ordinal": ordinal,
            "document_ordinal": document_ordinal if normalized else None,
            "source_metadata": metadata,
            "source_text": text,
            "source_text_sha256": hashlib.sha256(raw).hexdigest(),
            "source_char_count": len(text),
            "source_utf8_bytes": len(raw),
            "normalized_text": normalized,
            "normalized_text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        })
        inputs.append({**metadata, "text": text})
        document_ordinal += bool(normalized)
    legacy = inventory_uscode_documents(inputs, query=query, release_id=release_id)
    if len(legacy["spans"]) != span_count:
        raise USCodeSourceCoordinatesError("sentence inventory profile changed")
    grouped: dict[int, list[dict]] = {}
    for span in legacy["spans"]:
        grouped.setdefault(span["document_ordinal"], []).append(span)
    spans = []
    if span_count:
        # The existing geometry helper retains requested boundaries only; it
        # makes no parent-custody claim and constructs no per-character array.
        from .legal_parent_text_views import _byte_positions
    for view in views:
        selected = grouped.get(view["document_ordinal"], [])
        if not selected:
            continue
        ranges = []
        cursor = 0
        for span in selected:
            start = view["normalized_text"].find(span["text"], cursor)
            if start < cursor:
                raise USCodeSourceCoordinatesError("ordered normalized source occurrence differs")
            cursor = start + len(span["text"])
            ranges.append((start, cursor))
        source_positions = _source_coordinates_boundaries(
            view["source_text"], [position for pair in ranges for position in pair])
        byte_positions = _byte_positions(view["source_text"], list(source_positions.values()))
        for span, (start, end) in zip(selected, ranges):
            source_start, source_end = source_positions[start], source_positions[end]
            text = view["source_text"][source_start:source_end]
            if _clean(text) != span["text"]:
                raise USCodeSourceCoordinatesError("selected source does not reproduce the normalized span")
            spans.append({
                "input_document_ordinal": view["input_document_ordinal"],
                "document_ordinal": view["document_ordinal"],
                "source_document_sha256": view["source_text_sha256"],
                "source_span_id": span["source_span_id"],
                "text": span["text"],
                "span_text_sha256": span["span_text_sha256"],
                "normalized_char_start": start, "normalized_char_end": end,
                "source_char_start": source_start, "source_char_end": source_end,
                "source_utf8_byte_start": byte_positions[source_start],
                "source_utf8_byte_end": byte_positions[source_end],
                "source_text": text,
                "source_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
    report = {
        "schema": SOURCE_COORDINATE_SCHEMA, "profile": SOURCE_COORDINATE_PROFILE,
        "query": query, "release_id": release_id, "limits": bounds,
        "span_identity_schema": SCHEMA,
        "coordinate_origin": {
            "field": "text", "supplied_field": "exact decoded input mapping text",
            "characters": "Unicode code points; half-open",
            "bytes": "UTF8 encoding of exact decoded supplied text; half-open",
            "parquet_file_byte_mapping_verified": False, "raw_html_byte_mapping_verified": False,
        },
        "authority": dict.fromkeys(("source_authority_authenticated", "legal_meaning_verified",
            "training_authorized", "training_gold_qualified", "formalized", "admitted"), False),
        "documents": views, "spans": spans,
    }
    report["source_coordinates_sha256"] = hashlib.sha256(
        _source_coordinates_wire(report, bounds["max_report_bytes"])).hexdigest()
    _source_coordinates_wire(report, bounds["max_report_bytes"])
    return report


def validate_uscode_source_coordinates(
    report: Mapping[str, Any],
    documents: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    expected_report_sha256: str,
    query: str = "",
    release_id: str = "",
    limits: Mapping[str, int] | None = None,
) -> None:
    """Verify an independent full-report pin and replay every supplied document."""
    if (type(report) is not dict or type(expected_report_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_report_sha256) is None
            or uscode_source_coordinates_sha256(report) != expected_report_sha256):
        raise USCodeSourceCoordinatesError("independent source-coordinate report pin differs")
    expected = inventory_uscode_source_coordinates(
        documents, query=query, release_id=release_id, limits=limits)
    maximum = expected["limits"]["max_report_bytes"]
    if _source_coordinates_wire(report, maximum) != _source_coordinates_wire(expected, maximum):
        raise USCodeSourceCoordinatesError("complete source-coordinate replay differs")
