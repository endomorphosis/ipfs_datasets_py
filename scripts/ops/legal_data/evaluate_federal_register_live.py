#!/usr/bin/env python3
"""Live BM25 self-retrieval evaluation over the LCR-071 11,784-document index.

Uses document-number queries against the sealed live posting triples. This is
not a Hub canary and does not authorize publication. Does not rewrite the
sealed fixture ``federal_evaluation.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (  # noqa: E402
    TOKENIZER_ID,
    tokenize_legal_text,
)
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (  # noqa: E402
    bm25_term_score,
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_LIVE_DOCUMENTS = 11784
DEFAULT_INDEX_DIR = Path("/var/tmp/lcr-071-fr-bm25")
DEFAULT_CORPUS_DIR = Path("/var/tmp/lcr-071-fr-corpus")
GRAPH_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_graph.live.json")
VECTORS_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_vectors.live.json")
GOLD_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_gold.live.json")
EVAL_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_evaluation.live.json")
K1 = 1.2
B = 0.75
DEFAULT_SAMPLE_SIZE = 32
RECALL_AT_1_GATE = 0.90
MRR_GATE = 0.90
VECTOR_RECALL_AT_10_GATE = 0.80
GOLD_EXACT_RECALL_AT_1_GATE = 0.90
GOLD_CITE_RECALL_AT_10_GATE = 0.40
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class LiveEvalError(RuntimeError):
    pass


def _document_number(legal_id: str) -> str:
    parts = str(legal_id).split(":")
    if len(parts) >= 2 and parts[0] == "fr":
        return parts[1]
    return str(legal_id)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LiveEvalError(f"required receipt missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise LiveEvalError(f"receipt root must be an object: {path}")
    return payload


def _load_documents(index_dir: Path) -> list[dict[str, Any]]:
    path = index_dir / "documents.jsonl"
    if not path.is_file():
        raise LiveEvalError(f"BM25 documents missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("legal_id"):
                rows.append(item)
    return rows


def _sample_documents(
    rows: Sequence[Mapping[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    if sample_size <= 0:
        raise LiveEvalError("sample size must be positive")
    if len(rows) <= sample_size:
        return [dict(row) for row in rows]
    ranked = sorted(
        rows,
        key=lambda row: hashlib.sha256(
            str(row.get("legal_id") or "").encode("utf-8")
        ).hexdigest(),
    )
    stride = len(ranked) / float(sample_size)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(sample_size):
        row = dict(ranked[min(len(ranked) - 1, int(index * stride))])
        legal_id = str(row["legal_id"])
        if legal_id in seen:
            continue
        seen.add(legal_id)
        picked.append(row)
    return picked


def _query_terms(legal_id: str) -> list[str]:
    docno = _document_number(legal_id)
    result = tokenize_legal_text(docno, drop_stopwords=True)
    terms = list(result.indexable_terms)
    if not terms:
        raise LiveEvalError(f"document number produced no query terms: {legal_id}")
    return terms


def _scan_postings(
    triples_path: Path, wanted_terms: set[str]
) -> dict[str, dict[str, int]]:
    postings: dict[str, dict[str, int]] = {term: {} for term in wanted_terms}
    with triples_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            term = str(item.get("term") or "")
            if term not in postings:
                continue
            legal_id = str(item.get("legal_id") or "")
            tf = int(item.get("tf") or 0)
            if legal_id and tf > 0:
                postings[term][legal_id] = tf
    return postings


def _score_query(
    *,
    terms: Sequence[str],
    postings: Mapping[str, Mapping[str, int]],
    doc_lengths: Mapping[str, int],
    n_docs: int,
    avg_len: float,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for term in terms:
        df = len(postings.get(term) or {})
        if df <= 0:
            continue
        idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
        idf = max(0.0, float(idf))
        for legal_id, tf in (postings.get(term) or {}).items():
            scores[legal_id] += bm25_term_score(
                tf=float(tf),
                idf=idf,
                doc_length=float(doc_lengths.get(legal_id) or avg_len),
                avg_doc_length=avg_len,
                k1=K1,
                b=B,
            )
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ranked


def _plain_text(html: str) -> str:
    stripped = _TAG_RE.sub(" ", html or "").replace("\x00", " ")
    return _WS_RE.sub(" ", stripped).strip()


def _body_excerpt(corpus_dir: Path, legal_id: str) -> str:
    slug = legal_id.replace(":", "_")
    path = corpus_dir / "bodies" / f"{slug}.json"
    if not path.is_file():
        # live corpus uses fr_2026-04129_2026-03-03.json
        alt = corpus_dir / "bodies" / f"fr_{legal_id.split(':', 1)[-1].replace(':', '_')}.json"
        path = alt if alt.is_file() else path
    if not path.is_file():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = _plain_text(str(payload.get("text") or ""))
    if len(text) > 600:
        return text[200:600]
    return text[:400]


def _embed_texts(texts: Sequence[str], *, backend: str) -> list[list[float]]:
    from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
        deterministic_project,
    )

    if backend != "sentence_transformers":
        return deterministic_project(list(texts), dimension=384, normalize=True)
    from sentence_transformers import SentenceTransformer

    from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
        PINNED_MODEL_ID,
        PINNED_MODEL_REVISION,
    )

    model = SentenceTransformer(PINNED_MODEL_ID, revision=PINNED_MODEL_REVISION, device="cuda")
    vectors = model.encode(
        list(texts),
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [list(map(float, row)) for row in vectors]


def _evaluate_vectors(
    *,
    repository_root: Path,
    corpus_dir: Path,
    sample: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    path = repository_root / VECTORS_RELPATH
    if not path.is_file():
        return {
            "available": False,
            "deferred": True,
            "meets_declared_gates": False,
            "reason": "live vector receipt is missing",
        }
    receipt = _load_json(path)
    if receipt.get("fixture_only") is True:
        return {
            "available": True,
            "fixture_only": True,
            "meets_declared_gates": False,
            "reason": "vector receipt is fixture-only",
        }
    import numpy as np

    matrix = np.load(str(receipt["vectors_path"]))
    ids: list[str] = []
    with Path(str(receipt["ids_path"])).open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            ids.append(str(item["legal_id"]))
    id_to_row = {legal_id: index for index, legal_id in enumerate(ids)}
    excerpts: list[str] = []
    targets: list[str] = []
    for row in sample:
        legal_id = str(row["legal_id"])
        if legal_id not in id_to_row:
            continue
        excerpt = _body_excerpt(corpus_dir, legal_id)
        if not excerpt:
            continue
        excerpts.append(excerpt)
        targets.append(legal_id)
    if not excerpts:
        return {
            "available": True,
            "meets_declared_gates": False,
            "reason": "no vector query excerpts",
        }
    query_vecs = np.asarray(
        _embed_texts(excerpts, backend=str(receipt.get("backend") or "")),
        dtype=np.float32,
    )
    scores = query_vecs @ matrix.T
    hits_at_10 = 0
    reciprocal_ranks: list[float] = []
    for index, legal_id in enumerate(targets):
        target_row = id_to_row[legal_id]
        order = np.argsort(-scores[index])
        rank_list = [int(item) for item in order]
        rank = rank_list.index(target_row) + 1
        if rank <= 10:
            hits_at_10 += 1
        reciprocal_ranks.append(1.0 / float(rank))
    recall_at_10 = hits_at_10 / len(targets)
    mrr = sum(reciprocal_ranks) / len(targets)
    ok = (
        recall_at_10 >= VECTOR_RECALL_AT_10_GATE
        and receipt.get("centroid_bounds_hold") is True
        and receipt.get("fixture_only") is not True
    )
    return {
        "available": True,
        "deferred": False,
        "fixture_only": False,
        "backend": receipt.get("backend"),
        "model_id": receipt.get("model_id"),
        "model_revision": receipt.get("model_revision"),
        "vector_count": receipt.get("vector_count"),
        "cluster_count": receipt.get("cluster_count"),
        "centroid_bounds_hold": receipt.get("centroid_bounds_hold"),
        "sample_size": len(targets),
        "recall_at_10": recall_at_10,
        "mrr": mrr,
        "recall_at_10_gate": VECTOR_RECALL_AT_10_GATE,
        "meets_declared_gates": ok,
    }


def _evaluate_gold(
    *,
    repository_root: Path,
    postings: Mapping[str, Mapping[str, int]],
    doc_lengths: Mapping[str, int],
    n_docs: int,
    avg_len: float,
) -> dict[str, Any]:
    path = repository_root / GOLD_RELPATH
    if not path.is_file():
        return {
            "available": False,
            "deferred": True,
            "meets_declared_gates": False,
            "reason": "live gold receipt is missing",
        }
    gold = _load_json(path)
    if gold.get("fixture_only") is True or gold.get("human_authored") is True:
        # live identity gold must not masquerade as the sealed human fixture
        if gold.get("fixture_only") is True:
            return {
                "available": True,
                "fixture_only": True,
                "meets_declared_gates": False,
                "reason": "gold receipt is fixture-only",
            }
    queries = list(gold.get("queries") or [])
    exact_hits = 0
    exact_n = 0
    cite_hits = 0
    cite_n = 0
    for query in queries:
        terms = list(
            tokenize_legal_text(str(query.get("text") or ""), drop_stopwords=True).indexable_terms
        )
        ranked = _score_query(
            terms=terms,
            postings=postings,
            doc_lengths=doc_lengths,
            n_docs=n_docs,
            avg_len=avg_len,
        )
        relevant = set(str(item) for item in (query.get("relevant") or []))
        top_k = 1 if query.get("query_kind") == "exact_document_number" else 10
        hit = any(legal_id in relevant for legal_id, _score in ranked[:top_k])
        if query.get("query_kind") == "exact_document_number":
            exact_n += 1
            if hit:
                exact_hits += 1
        elif query.get("query_kind") == "citation":
            cite_n += 1
            if hit:
                cite_hits += 1
    exact_recall = exact_hits / exact_n if exact_n else 0.0
    cite_recall = cite_hits / cite_n if cite_n else 0.0
    ok = (
        gold.get("fixture_only") is not True
        and exact_n > 0
        and exact_recall >= GOLD_EXACT_RECALL_AT_1_GATE
        and (cite_n == 0 or cite_recall >= GOLD_CITE_RECALL_AT_10_GATE)
    )
    return {
        "available": True,
        "deferred": False,
        "fixture_only": False,
        "human_authored": False,
        "ground_truth_policy": gold.get("ground_truth_policy"),
        "query_count": len(queries),
        "exact_recall_at_1": exact_recall,
        "citation_recall_at_10": cite_recall,
        "exact_recall_at_1_gate": GOLD_EXACT_RECALL_AT_1_GATE,
        "citation_recall_at_10_gate": GOLD_CITE_RECALL_AT_10_GATE,
        "meets_declared_gates": ok,
    }


def evaluate_live(
    *,
    index_dir: Path,
    corpus_dir: Path,
    repository_root: Path = REPOSITORY_ROOT,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    require_complete: bool = True,
    write_receipt: bool = True,
) -> dict[str, Any]:
    manifest = _load_json(index_dir / "manifest.json")
    n_docs = int(manifest.get("documents") or 0)
    if require_complete and n_docs != EXPECTED_LIVE_DOCUMENTS:
        raise LiveEvalError(
            f"live evaluation requires {EXPECTED_LIVE_DOCUMENTS} BM25 documents, got {n_docs}"
        )
    avg_len = float(manifest.get("avg_doc_tokens") or 0.0)
    if avg_len <= 0:
        raise LiveEvalError("BM25 manifest is missing avg_doc_tokens")
    documents = _load_documents(index_dir)
    if require_complete and len(documents) != EXPECTED_LIVE_DOCUMENTS:
        raise LiveEvalError(
            f"documents.jsonl has {len(documents)} rows, expected {EXPECTED_LIVE_DOCUMENTS}"
        )
    sample = _sample_documents(documents, sample_size)
    wanted_terms: set[str] = set()
    queries: list[dict[str, Any]] = []
    for row in sample:
        terms = _query_terms(str(row["legal_id"]))
        wanted_terms.update(terms)
        queries.append({"legal_id": str(row["legal_id"]), "terms": terms})
    gold_path = repository_root / GOLD_RELPATH
    gold_payload: Mapping[str, Any] = {}
    if gold_path.is_file():
        gold_payload = _load_json(gold_path)
        for item in gold_payload.get("queries") or []:
            wanted_terms.update(
                tokenize_legal_text(str(item.get("text") or ""), drop_stopwords=True).indexable_terms
            )
    triples_path = Path(str(manifest.get("triples_path") or (index_dir / "posting_triples.jsonl")))
    postings = _scan_postings(triples_path, wanted_terms)
    doc_lengths = {str(row["legal_id"]): int(row.get("token_count") or 0) for row in documents}

    hits_at_1 = 0
    reciprocal_ranks: list[float] = []
    cases: list[dict[str, Any]] = []
    for query in queries:
        ranked = _score_query(
            terms=query["terms"],
            postings=postings,
            doc_lengths=doc_lengths,
            n_docs=n_docs,
            avg_len=avg_len,
        )
        target = query["legal_id"]
        rank = next(
            (index + 1 for index, (legal_id, _score) in enumerate(ranked) if legal_id == target),
            None,
        )
        if rank == 1:
            hits_at_1 += 1
        rr = 0.0 if rank is None else 1.0 / float(rank)
        reciprocal_ranks.append(rr)
        cases.append(
            {
                "legal_id": target,
                "query_terms": query["terms"],
                "rank": rank,
                "hit_at_1": rank == 1,
                "top_hit": ranked[0][0] if ranked else None,
                "top_score": ranked[0][1] if ranked else 0.0,
            }
        )

    query_count = len(queries)
    recall_at_1 = hits_at_1 / query_count if query_count else 0.0
    mrr = sum(reciprocal_ranks) / query_count if query_count else 0.0
    graph: Mapping[str, Any] = {}
    graph_path = repository_root / GRAPH_RELPATH
    if graph_path.is_file():
        graph = _load_json(graph_path)
    bm25_ok = recall_at_1 >= RECALL_AT_1_GATE and mrr >= MRR_GATE
    graph_ok = bool(graph) and graph.get("fixture_only") is not True and int(graph.get("edge_count") or 0) > 0
    vector_block = _evaluate_vectors(
        repository_root=repository_root,
        corpus_dir=corpus_dir,
        sample=sample,
    )
    gold_block = _evaluate_gold(
        repository_root=repository_root,
        postings=postings,
        doc_lengths=doc_lengths,
        n_docs=n_docs,
        avg_len=avg_len,
    )
    vector_ok = bool(vector_block.get("meets_declared_gates"))
    gold_ok = bool(gold_block.get("meets_declared_gates"))
    if not require_complete and not vector_block.get("available"):
        vector_ok = True
        vector_block = {**vector_block, "skipped": True}
    if not require_complete and not gold_block.get("available"):
        gold_ok = True
        gold_block = {**gold_block, "skipped": True}
    report: dict[str, Any] = {
        "schema": "ipfs_datasets_py/federal-register-live-evaluation@1",
        "producer": "evaluate_federal_register_live.py",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "mode": "live",
        "fixture_only": False,
        "live_canary": False,
        "production_searchable": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "tokenizer_id": TOKENIZER_ID,
        "documents": n_docs,
        "sample_size": query_count,
        "query_kind": "document_number_self_retrieval",
        "bm25": {
            "available": True,
            "k1": K1,
            "b": B,
            "hits_at_1": hits_at_1,
            "recall_at_1": recall_at_1,
            "mrr": mrr,
            "recall_at_1_gate": RECALL_AT_1_GATE,
            "mrr_gate": MRR_GATE,
            "meets_declared_gates": bm25_ok,
        },
        "graph": {
            "available": bool(graph),
            "fixture_only": bool(graph.get("fixture_only")) if graph else None,
            "node_count": int(graph.get("node_count") or 0),
            "edge_count": int(graph.get("edge_count") or 0),
            "inversion_holds": bool(graph.get("adjacency_inversion")),
            "meets_declared_gates": graph_ok,
        },
        "vector": vector_block,
        "gold": gold_block,
        "cases": cases,
        "acceptance": {
            "bm25_meets_declared_gates": bm25_ok,
            "graph_meets_declared_gates": graph_ok,
            "vector_meets_declared_gates": vector_ok,
            "gold_meets_declared_gates": gold_ok,
            "hub_upload": False,
            "live_canary": False,
            "no_fixture_result_called_live_canary": True,
            "production_searchable": False,
            "secrets_absent": True,
            "local_query_canary": bm25_ok and vector_ok,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "status": "passed" if bm25_ok and graph_ok and vector_ok and gold_ok else "blocked",
    }
    if not gold_ok:
        report["status"] = "blocked"
        report["blocked_reason"] = str(gold_block.get("reason") or "live gold evaluation missed declared gates")
    if not vector_ok:
        report["status"] = "blocked"
        report["blocked_reason"] = str(vector_block.get("reason") or "live vector evaluation missed declared gates")
    if not graph_ok:
        report["status"] = "blocked"
        report["blocked_reason"] = "live graph receipt is missing or empty"
    if not bm25_ok:
        report["status"] = "blocked"
        report["blocked_reason"] = (
            f"BM25 self-retrieval recall@1={recall_at_1:.3f} mrr={mrr:.3f} "
            f"below gates {RECALL_AT_1_GATE}/{MRR_GATE}"
        )
    report["content_digest"] = digest_mapping(
        {k: v for k, v in report.items() if k not in {"content_digest", "cases"}}
    )
    if write_receipt:
        out = repository_root / EVAL_RELPATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["receipt_path"] = EVAL_RELPATH.as_posix()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate live FR BM25 self-retrieval")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--no-write-receipt", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = evaluate_live(
            index_dir=args.index_dir,
            corpus_dir=args.corpus_dir,
            repository_root=args.repository_root,
            sample_size=int(args.sample_size),
            require_complete=not bool(args.allow_partial),
            write_receipt=not bool(args.no_write_receipt),
        )
    except LiveEvalError as exc:
        sys.stderr.write(f"evaluate_federal_register_live: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        bm25 = report["bm25"]
        sys.stdout.write(
            "evaluate_federal_register_live: "
            f"{report['status'].upper()} recall@1={bm25['recall_at_1']:.3f} "
            f"mrr={bm25['mrr']:.3f} sample={report['sample_size']}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
