#!/usr/bin/env python3
"""Build live identity gold for LCR-071 from official document numbers and citations.

This is not the sealed LCR-051 human-authored fixture and does not overwrite
``tests/fixtures/legal_ir/federal_register_gold_v1.json``. Labels are derived
from official publication identity and the live citation graph. Hub upload
stays false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    digest_mapping,
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_LIVE_DOCUMENTS = 11784
DEFAULT_CORPUS_DIR = Path("/var/tmp/lcr-071-fr-corpus")
DEFAULT_GRAPH_DIR = Path("/var/tmp/lcr-071-fr-graph")
GOLD_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_gold.live.json")
DEFAULT_EXACT_QUERIES = 32
DEFAULT_CITATION_QUERIES = 16


class LiveGoldError(RuntimeError):
    pass


def _load_index(corpus_dir: Path) -> list[dict[str, Any]]:
    path = corpus_dir / "index.jsonl"
    if not path.is_file():
        raise LiveGoldError(f"corpus index missing: {path}")
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


def _document_number(legal_id: str) -> str:
    parts = str(legal_id).split(":")
    if len(parts) >= 2 and parts[0] == "fr":
        return parts[1]
    return str(legal_id)


def _sample(rows: Sequence[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: hashlib.sha256(
            str(row.get("legal_id") or "").encode("utf-8")
        ).hexdigest(),
    )
    if len(ranked) <= count:
        return list(ranked)
    stride = len(ranked) / float(count)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(count):
        row = ranked[min(len(ranked) - 1, int(index * stride))]
        legal_id = str(row["legal_id"])
        if legal_id in seen:
            continue
        seen.add(legal_id)
        picked.append(row)
    return picked


def _load_citation_postings(graph_dir: Path) -> dict[str, list[str]]:
    path = graph_dir / "edges.jsonl"
    if not path.is_file():
        raise LiveGoldError(f"graph edges missing: {path}")
    postings: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            if item.get("edge_type") != "CITES":
                continue
            source = str(item.get("source") or "")
            target = str(item.get("target") or "")
            if not source.startswith("document:") or not target.startswith("citation:cfr:"):
                continue
            legal_id = source.split(":", 1)[1]
            postings[target].add(legal_id)
    return {key: sorted(values) for key, values in postings.items()}


def _cfr_query_text(node_key: str) -> str:
    # citation:cfr:40:52.21
    parts = node_key.split(":")
    if len(parts) < 4:
        return node_key
    return f"{parts[2]} CFR {parts[3]}"


def build_live_gold(
    *,
    corpus_dir: Path,
    graph_dir: Path,
    repository_root: Path = REPOSITORY_ROOT,
    exact_queries: int = DEFAULT_EXACT_QUERIES,
    citation_queries: int = DEFAULT_CITATION_QUERIES,
    require_complete: bool = True,
    write_receipt: bool = True,
) -> dict[str, Any]:
    rows = _load_index(corpus_dir)
    if require_complete and len(rows) != EXPECTED_LIVE_DOCUMENTS:
        raise LiveGoldError(
            f"live gold requires {EXPECTED_LIVE_DOCUMENTS} verified bodies, got {len(rows)}"
        )
    if not rows:
        raise LiveGoldError("no verified corpus bodies")
    queries: list[dict[str, Any]] = []
    for row in _sample(rows, exact_queries):
        legal_id = str(row["legal_id"])
        docno = _document_number(legal_id)
        queries.append(
            {
                "query_id": f"q-live-exact-{docno}",
                "query_kind": "exact_document_number",
                "partition": "test",
                "text": docno,
                "relevant": [legal_id],
                "label_kind": "exact_document",
            }
        )
    citation_postings = _load_citation_postings(graph_dir)
    eligible = [
        (key, docs)
        for key, docs in citation_postings.items()
        if 3 <= len(docs) <= 80
    ]
    eligible.sort(key=lambda item: hashlib.sha256(item[0].encode("utf-8")).hexdigest())
    for key, docs in eligible[:citation_queries]:
        queries.append(
            {
                "query_id": f"q-live-cite-{key.replace(':', '-')}",
                "query_kind": "citation",
                "partition": "test",
                "text": _cfr_query_text(key),
                "relevant": docs[:25],
                "label_kind": "supporting_citation_path",
                "citation_node": key,
            }
        )
    if len(queries) < 2:
        raise LiveGoldError("live gold produced too few queries")
    report: dict[str, Any] = {
        "schema": "ipfs_datasets_py/federal-register-live-gold@1",
        "producer": "build_federal_register_live_gold.py",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "mode": "live",
        "fixture_only": False,
        "human_authored": False,
        "ground_truth_policy": "official_publication_identity_and_extracted_citations",
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "documents": len(rows),
        "query_count": len(queries),
        "exact_document_queries": sum(
            1 for item in queries if item["query_kind"] == "exact_document_number"
        ),
        "citation_queries": sum(1 for item in queries if item["query_kind"] == "citation"),
        "queries": queries,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "status": "passed",
    }
    digest_body = {k: v for k, v in report.items() if k not in {"content_digest", "queries"}}
    digest_body["query_ids"] = [item["query_id"] for item in queries]
    report["content_digest"] = digest_mapping(digest_body)
    if write_receipt:
        out = repository_root / GOLD_RELPATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["receipt_path"] = GOLD_RELPATH.as_posix()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build live FR identity gold")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--graph-dir", type=Path, default=DEFAULT_GRAPH_DIR)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--exact-queries", type=int, default=DEFAULT_EXACT_QUERIES)
    parser.add_argument("--citation-queries", type=int, default=DEFAULT_CITATION_QUERIES)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--no-write-receipt", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = build_live_gold(
            corpus_dir=args.corpus_dir,
            graph_dir=args.graph_dir,
            repository_root=args.repository_root,
            exact_queries=int(args.exact_queries),
            citation_queries=int(args.citation_queries),
            require_complete=not bool(args.allow_partial),
            write_receipt=not bool(args.no_write_receipt),
        )
    except LiveGoldError as exc:
        sys.stderr.write(f"build_federal_register_live_gold: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "build_federal_register_live_gold: "
            f"{report['status'].upper()} queries={report['query_count']} "
            f"exact={report['exact_document_queries']} "
            f"citation={report['citation_queries']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
