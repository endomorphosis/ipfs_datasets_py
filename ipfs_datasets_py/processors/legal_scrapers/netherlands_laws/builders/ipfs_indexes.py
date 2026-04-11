"""Build CID-keyed vector, BM25, and JSON-LD indexes for Netherlands laws."""

from __future__ import annotations

import json
import math
import pickle
import re
from collections import Counter
from pathlib import Path
from typing import Any

import faiss
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_obj

from .common import read_jsonl, sha256, write_jsonl, write_parquet
from ..paths import HF_DATA_DIR


SOURCE_DIR = HF_DATA_DIR / "ipfs_netherlands_laws"
TOKENIZER_RE = re.compile(r"[0-9A-Za-zÀ-ÿ_]+", re.UNICODE)


def file_cid(path: Path) -> str:
    return cid_for_bytes(path.read_bytes())


def tokenise(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKENIZER_RE.finditer(text or "")]


def load_source_rows() -> list[dict[str, Any]]:
    laws = read_jsonl(SOURCE_DIR / "data/laws/ipfs_netherlands_laws.jsonl")
    articles = read_jsonl(SOURCE_DIR / "data/articles/ipfs_netherlands_laws_articles.jsonl")
    corpus: list[dict[str, Any]] = []
    for row in laws:
        corpus.append(
            {
                "record_type": "law",
                "source_cid": row["cid"],
                "law_cid": row["cid"],
                "law_identifier": row.get("law_identifier"),
                "article_identifier": None,
                "title": row.get("title") or row.get("citation") or row.get("law_identifier"),
                "citation": row.get("citation"),
                "content_address": row.get("content_address"),
                "source_url": row.get("source_url"),
                "text": row.get("text") or "",
            }
        )
    for row in articles:
        corpus.append(
            {
                "record_type": "article",
                "source_cid": row["cid"],
                "law_cid": row.get("law_cid"),
                "law_identifier": row.get("law_identifier"),
                "article_identifier": row.get("article_identifier"),
                "title": row.get("citation") or row.get("article_identifier"),
                "citation": row.get("citation"),
                "content_address": row.get("content_address"),
                "source_url": None,
                "text": row.get("text") or "",
            }
        )
    return corpus


def build_vector_package(corpus: list[dict[str, Any]]) -> Path:
    out_dir = HF_DATA_DIR / "ipfs_netherlands_laws_vector_index"
    docs: list[dict[str, Any]] = []
    texts: list[str] = []
    for row in corpus:
        search_text = f"{row.get('title') or ''}\n{row.get('citation') or ''}\n{row.get('text') or ''}".strip()
        docs.append({**row, "search_text": search_text})
        texts.append(search_text)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=8192)
    tfidf = vectorizer.fit_transform(texts)
    max_components = min(256, max(2, tfidf.shape[0] - 1), max(2, tfidf.shape[1] - 1))
    svd = TruncatedSVD(n_components=max_components, random_state=42)
    dense = normalize(svd.fit_transform(tfidf), norm="l2").astype("float32")

    index = faiss.IndexFlatIP(dense.shape[1])
    index.add(dense)

    mapping_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(docs):
        payload = {
            "cid": row["source_cid"],
            "source_cid": row["source_cid"],
            "law_cid": row.get("law_cid"),
            "record_type": row["record_type"],
            "law_identifier": row.get("law_identifier"),
            "article_identifier": row.get("article_identifier"),
            "title": row.get("title"),
            "citation": row.get("citation"),
            "content_address": row.get("content_address"),
            "embedding": dense[idx].tolist(),
            "embedding_dim": int(dense.shape[1]),
            "search_text_preview": row["search_text"][:500],
        }
        payload["index_row_cid"] = cid_for_obj(payload)
        mapping_rows.append(payload)

    metadata = {
        "dataset_name": "ipfs_netherlands_laws_vector_index",
        "source_dataset": "justicedao/ipfs_netherlands_laws",
        "records": len(mapping_rows),
        "embedding_method": "tfidf_plus_truncated_svd",
        "embedding_dim": int(dense.shape[1]),
        "faiss_metric": "inner_product_on_l2_normalized_vectors",
        "index_key": "source_cid",
    }

    write_parquet(out_dir / "parquet/mapping/train-00000-of-00001.parquet", mapping_rows)
    write_jsonl(out_dir / "data/mapping/ipfs_netherlands_laws_vector_mapping.jsonl", mapping_rows)
    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (out_dir / "artifacts/faiss.index").write_bytes(faiss.serialize_index(index).tobytes())
    (out_dir / "artifacts/vectorizer.pkl").write_bytes(pickle.dumps(vectorizer))
    (out_dir / "artifacts/svd.pkl").write_bytes(pickle.dumps(svd))
    (out_dir / "artifacts/metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_dir


def build_bm25_package(corpus: list[dict[str, Any]]) -> Path:
    out_dir = HF_DATA_DIR / "ipfs_netherlands_laws_bm25_index"
    doc_tokens: dict[str, list[str]] = {}
    doc_lengths: dict[str, int] = {}
    tf_by_doc: dict[str, Counter[str]] = {}
    doc_rows: list[dict[str, Any]] = []
    row_by_cid: dict[str, dict[str, Any]] = {}

    for row in corpus:
        text = f"{row.get('title') or ''} {row.get('citation') or ''} {row.get('text') or ''}".strip()
        source_cid = row["source_cid"]
        tokens = tokenise(text)
        doc_tokens[source_cid] = tokens
        doc_lengths[source_cid] = len(tokens)
        tf_by_doc[source_cid] = Counter(tokens)
        payload = {
            "cid": source_cid,
            "source_cid": source_cid,
            "law_cid": row.get("law_cid"),
            "record_type": row["record_type"],
            "law_identifier": row.get("law_identifier"),
            "article_identifier": row.get("article_identifier"),
            "title": row.get("title"),
            "citation": row.get("citation"),
            "content_address": row.get("content_address"),
            "doc_length": len(tokens),
            "token_count_unique": len(tf_by_doc[source_cid]),
            "text_preview": text[:500],
        }
        payload["doc_row_cid"] = cid_for_obj(payload)
        doc_rows.append(payload)
        row_by_cid[source_cid] = payload

    n_docs = len(doc_tokens)
    avgdl = sum(doc_lengths.values()) / max(1, n_docs)
    doc_freq: Counter[str] = Counter()
    for tokens in doc_tokens.values():
        doc_freq.update(set(tokens))

    k1 = 1.5
    b = 0.75
    term_rows: list[dict[str, Any]] = []
    for term in sorted(doc_freq):
        df = doc_freq[term]
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        postings = []
        for source_cid, tf_counter in tf_by_doc.items():
            tf = tf_counter.get(term, 0)
            if not tf:
                continue
            dl = doc_lengths[source_cid]
            score = idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avgdl))))
            postings.append(
                {
                    "source_cid": source_cid,
                    "law_cid": row_by_cid[source_cid]["law_cid"],
                    "tf": tf,
                    "doc_length": dl,
                    "bm25_term_score": score,
                }
            )
        row = {"term": term, "doc_freq": df, "idf": idf, "postings_count": len(postings), "postings": postings}
        row["term_row_cid"] = cid_for_obj(row)
        term_rows.append(row)

    write_parquet(out_dir / "parquet/documents/train-00000-of-00001.parquet", doc_rows)
    write_parquet(out_dir / "parquet/terms/train-00000-of-00001.parquet", term_rows)
    write_jsonl(out_dir / "data/documents/ipfs_netherlands_laws_bm25_documents.jsonl", doc_rows)
    write_jsonl(out_dir / "data/terms/ipfs_netherlands_laws_bm25_terms.jsonl", term_rows)
    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (out_dir / "artifacts/metadata.json").write_text(
        json.dumps(
            {
                "dataset_name": "ipfs_netherlands_laws_bm25_index",
                "source_dataset": "justicedao/ipfs_netherlands_laws",
                "records": {"documents": len(doc_rows), "terms": len(term_rows)},
                "bm25": {"k1": k1, "b": b, "avgdl": avgdl},
                "index_key": "source_cid",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out_dir


def build_knowledge_graph_package(corpus: list[dict[str, Any]]) -> Path:
    out_dir = HF_DATA_DIR / "ipfs_netherlands_laws_knowledge_graph"
    laws = [row for row in corpus if row["record_type"] == "law"]
    articles = [row for row in corpus if row["record_type"] == "article"]
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    jsonld_graph: list[dict[str, Any]] = []

    context = {
        "@vocab": "https://schema.org/",
        "source_cid": "https://schema.org/identifier",
        "law_cid": "https://schema.org/isPartOf",
        "article_identifier": "https://schema.org/identifier",
        "law_identifier": "https://schema.org/identifier",
        "content_address": "https://schema.org/url",
        "hasPart": {"@id": "https://schema.org/hasPart", "@type": "@id"},
        "isPartOf": {"@id": "https://schema.org/isPartOf", "@type": "@id"},
    }

    for law in laws:
        node = {
            "@id": law["content_address"],
            "@type": "Legislation",
            "source_cid": law["source_cid"],
            "law_identifier": law["law_identifier"],
            "name": law["title"],
        }
        jsonld_graph.append(node)
        graph_nodes.append(
            {
                "cid": law["source_cid"],
                "node_cid": cid_for_obj(node),
                "source_cid": law["source_cid"],
                "record_type": "law",
                "label": law["title"],
                "jsonld_id": law["content_address"],
                "law_identifier": law["law_identifier"],
                "article_identifier": None,
            }
        )

    law_map = {law["law_identifier"]: law for law in laws}
    for article in articles:
        law = law_map.get(article["law_identifier"])
        node = {
            "@id": article["content_address"],
            "@type": "LegislationObject",
            "source_cid": article["source_cid"],
            "article_identifier": article["article_identifier"],
            "law_identifier": article["law_identifier"],
            "name": article["title"],
        }
        if law:
            node["isPartOf"] = {"@id": law["content_address"]}
        jsonld_graph.append(node)
        graph_nodes.append(
            {
                "cid": article["source_cid"],
                "node_cid": cid_for_obj(node),
                "source_cid": article["source_cid"],
                "record_type": "article",
                "label": article["title"],
                "jsonld_id": article["content_address"],
                "law_identifier": article["law_identifier"],
                "article_identifier": article["article_identifier"],
            }
        )
        if law:
            edge = {
                "cid": article["source_cid"],
                "edge_type": "isPartOf",
                "source_cid": article["source_cid"],
                "target_cid": law["source_cid"],
                "source_id": article["content_address"],
                "target_id": law["content_address"],
                "law_identifier": article["law_identifier"],
                "article_identifier": article["article_identifier"],
            }
            edge["edge_cid"] = cid_for_obj(edge)
            graph_edges.append(edge)

    for law in laws:
        children = [{"@id": article["content_address"]} for article in articles if article["law_identifier"] == law["law_identifier"]]
        if children:
            for obj in jsonld_graph:
                if obj["@id"] == law["content_address"]:
                    obj["hasPart"] = children
                    break

    jsonld_doc = {"@context": context, "@graph": jsonld_graph}
    write_jsonl(out_dir / "data/nodes/ipfs_netherlands_laws_kg_nodes.jsonl", graph_nodes)
    write_jsonl(out_dir / "data/edges/ipfs_netherlands_laws_kg_edges.jsonl", graph_edges)
    (out_dir / "data/graph").mkdir(parents=True, exist_ok=True)
    (out_dir / "data/graph/ipfs_netherlands_laws_kg.jsonld").write_text(json.dumps(jsonld_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    write_parquet(out_dir / "parquet/nodes/train-00000-of-00001.parquet", graph_nodes)
    write_parquet(out_dir / "parquet/edges/train-00000-of-00001.parquet", graph_edges)
    (out_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (out_dir / "artifacts/metadata.json").write_text(
        json.dumps(
            {
                "dataset_name": "ipfs_netherlands_laws_knowledge_graph",
                "source_dataset": "justicedao/ipfs_netherlands_laws",
                "records": {"nodes": len(graph_nodes), "edges": len(graph_edges)},
                "graph_root_cid": cid_for_obj(jsonld_doc),
                "index_key": "source_cid",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return out_dir


def write_manifest(out_dir: Path) -> None:
    files = [path for path in out_dir.rglob("*") if path.is_file() and path.name != "dataset_manifest.json"]
    manifest: dict[str, Any] = {"dataset_name": out_dir.name, "source_dataset": "justicedao/ipfs_netherlands_laws", "files": {}}
    for path in sorted(files):
        rel = path.relative_to(out_dir).as_posix()
        manifest["files"][rel] = {"bytes": path.stat().st_size, "sha256": sha256(path), "file_cid": file_cid(path)}
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    corpus = load_source_rows()
    built = [build_vector_package(corpus), build_bm25_package(corpus), build_knowledge_graph_package(corpus)]
    for out_dir in built:
        write_manifest(out_dir)
    print(json.dumps([str(path) for path in built], indent=2))


if __name__ == "__main__":
    main()
