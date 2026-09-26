"""Sparse citation index for a legal ledger. Not a formalization and not a dense graph."""
from __future__ import annotations

import re
from typing import Any


_USC = re.compile(r"\b(\d+)\s+U\.S\.C\.\s+§?\s*(\d+[a-zA-Z-]*)", re.I)
SOURCE_DATASET = "justicedao/open-us-law-sparse-graphrag"
LOGIC_IR_DATASET = "logic-ir-us-legal-ledger"


def source_legal_id(unit_id: str) -> str:
    """Open US Law id for the original GraphRAG document. Empty when the span is not a section."""

    from ipfs_datasets_py.processors.legal_data.open_us_law_schema import build_legal_id

    text = str(unit_id or "")
    article = ""
    section = ""
    note = ""
    if text.startswith("art-"):
        body = text[4:]
        article, _, section_text = body.partition(".sec-")
        section = section_text
    elif text.startswith("amend-"):
        body = text[6:]
        article, _, section_text = body.partition(".sec-")
        section = section_text
        note = "amendment"
    else:
        return ""
    if not article:
        return ""
    hierarchy = {"article": article}
    if section:
        hierarchy["section"] = section
    return build_legal_id(
        document_kind="constitution",
        jurisdiction_code="US",
        code_family="us-constitution",
        hierarchy=hierarchy,
        edition="2024-official",
        note=note or None,
    )


def link_source_documents(spans: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Point each span at the original document id. Does not claim the span is formalized."""

    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for span in spans:
        legal_id = source_legal_id(str(span.get("unit_id") or ""))
        if not legal_id:
            continue
        key = (str(span.get("id") or ""), legal_id)
        if key in seen or not key[0]:
            continue
        seen.add(key)
        links.append({
            "span_id": key[0],
            "source_dataset": SOURCE_DATASET,
            "source_legal_id": legal_id,
            "formalized": False,
        })
    return links


def triples_from_ledger(ledger: dict[str, Any]) -> list[dict[str, str]]:
    """Citation and repeal triples already named by the ledger. No new edges are guessed."""

    triples: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(subject: str, predicate: str, obj: str) -> None:
        key = (subject, predicate, obj)
        if not subject or not obj or key in seen:
            return
        seen.add(key)
        triples.append({"subject": subject, "predicate": predicate, "object": obj})

    for edge in ledger.get("edges") or []:
        if edge.get("kind") == "repeal":
            add(str(edge.get("source") or ""), "repeals", str(edge.get("target") or ""))
    for span in ledger.get("spans") or []:
        span_id = str(span.get("id") or "")
        for match in _USC.finditer(str(span.get("text") or "")):
            add(span_id, "citation", f"{match.group(1)} U.S.C. {match.group(2)}")
        legal_id = source_legal_id(str(span.get("unit_id") or ""))
        if legal_id:
            add(span_id, "source_document", legal_id)
    return triples


def sparse_index(triples: list[dict[str, str]]) -> dict[str, Any]:
    """One-hop citation neighbors after the legal projection. Not an all-pairs scan."""

    from ipfs_datasets_py.logic.autoformal import citation_neighbors
    from ipfs_datasets_py.knowledge_graphs.neo4j_compat.legal_ir_projection import (
        augment_legal_ir_projection_triples,
    )

    augmented = augment_legal_ir_projection_triples(triples)
    subjects = sorted({str(item.get("subject") or "") for item in augmented if item.get("subject")})
    neighbors = {subject: citation_neighbors(augmented, subject) for subject in subjects}
    for triple in augmented:
        if triple.get("predicate") not in {"repeals", "source_document"}:
            continue
        source = str(triple.get("subject") or "")
        target = str(triple.get("object") or "")
        if not source or not target:
            continue
        neighbors.setdefault(source, [])
        if target not in neighbors[source]:
            neighbors[source].append(target)
        neighbors[source] = sorted(neighbors[source])
    return {
        "kind": "sparse_citation",
        "dense": False,
        "triple_count": len(augmented),
        "neighbors": neighbors,
    }
