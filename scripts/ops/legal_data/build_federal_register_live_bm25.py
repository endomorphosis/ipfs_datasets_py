#!/usr/bin/env python3
"""Build a document-level live BM25 index over materialized FR bodies (LCR-071).

Reads hash-verified JSON bodies from the live corpus directory. Default
``--require-complete`` refuses any index that is not 11,784 verified
documents. Does not authorize Hub upload or publication.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (  # noqa: E402
    TOKENIZER_ID,
    TOKENIZER_VERSION,
    default_tokenizer_config,
    tokenize_legal_text,
    tokenizer_identity,
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
EXPECTED_LIVE_DOCUMENTS = 11784
DEFAULT_CORPUS_DIR = Path("/var/tmp/lcr-071-fr-corpus")
DEFAULT_INDEX_DIR = Path("/var/tmp/lcr-071-fr-bm25")


class LiveBm25Error(RuntimeError):
    pass


def _load_index(corpus_dir: Path) -> list[dict[str, Any]]:
    path = corpus_dir / "index.jsonl"
    if not path.is_file():
        raise LiveBm25Error(f"corpus index missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("status") == "verified":
                rows.append(item)
    return rows


def build_live_bm25(
    *,
    corpus_dir: Path,
    index_dir: Path,
    require_complete: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    rows = _load_index(corpus_dir)
    if limit is not None:
        rows = rows[:limit]
    if require_complete and limit is None and len(rows) != EXPECTED_LIVE_DOCUMENTS:
        raise LiveBm25Error(
            f"live BM25 requires {EXPECTED_LIVE_DOCUMENTS} verified bodies, got {len(rows)}"
        )
    if not rows:
        raise LiveBm25Error("no verified corpus bodies")
    index_dir.mkdir(parents=True, exist_ok=True)
    documents_path = index_dir / "documents.jsonl"
    triples_path = index_dir / "posting_triples.jsonl"
    df: Counter[str] = Counter()
    token_total = 0
    with documents_path.open("w", encoding="utf-8") as docs_out, triples_path.open(
        "w", encoding="utf-8"
    ) as triples_out:
        for row in rows:
            rel = str(row.get("path") or "")
            body_path = corpus_dir / rel
            payload = json.loads(body_path.read_text(encoding="utf-8"))
            text = str(payload.get("text") or "")
            result = tokenize_legal_text(text, drop_stopwords=True)
            terms = list(result.indexable_terms)
            tf = Counter(terms)
            token_total += sum(tf.values())
            df.update(tf.keys())
            docs_out.write(
                json.dumps(
                    {
                        "legal_id": payload.get("legal_id") or row.get("legal_id"),
                        "content_hash": payload.get("content_hash") or row.get("content_hash"),
                        "token_count": sum(tf.values()),
                        "unique_terms": len(tf),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            legal_id = str(payload.get("legal_id") or row.get("legal_id"))
            for term, count in tf.items():
                triples_out.write(
                    json.dumps(
                        {"term": term, "legal_id": legal_id, "tf": int(count)},
                        sort_keys=True,
                    )
                    + "\n"
                )
    vocab = len(df)
    n_docs = len(rows)
    avg_len = token_total / n_docs if n_docs else 0.0
    report = {
        "schema": "ipfs_datasets_py/federal-register-live-bm25@1",
        "producer": "build_federal_register_live_bm25.py",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "tokenizer_id": TOKENIZER_ID,
        "tokenizer_version": TOKENIZER_VERSION,
        "tokenizer_identity": tokenizer_identity(default_tokenizer_config()),
        "documents": n_docs,
        "expected_documents": EXPECTED_LIVE_DOCUMENTS,
        "complete": n_docs == EXPECTED_LIVE_DOCUMENTS and limit is None,
        "vocabulary_size": vocab,
        "token_total": token_total,
        "avg_doc_tokens": avg_len,
        "documents_path": str(documents_path),
        "triples_path": str(triples_path),
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "status": "passed" if n_docs == EXPECTED_LIVE_DOCUMENTS and limit is None else "partial",
    }
    (index_dir / "manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build live FR BM25 over materialized bodies")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--require-complete", action="store_true", default=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    require_complete = bool(args.require_complete) and not bool(args.allow_partial)
    if args.limit is not None:
        require_complete = False
    try:
        report = build_live_bm25(
            corpus_dir=args.corpus_dir,
            index_dir=args.index_dir,
            require_complete=require_complete,
            limit=args.limit,
        )
    except LiveBm25Error as exc:
        sys.stderr.write(f"build_federal_register_live_bm25: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "build_federal_register_live_bm25: "
            f"{report['status'].upper()} docs={report['documents']} "
            f"vocab={report['vocabulary_size']}\n"
        )
    return 0 if report["status"] in {"passed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
