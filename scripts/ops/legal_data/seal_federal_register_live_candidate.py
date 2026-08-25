#!/usr/bin/env python3
"""Seal a non-fixture LCR-071 live candidate that still does not authorize Hub upload.

Writes ``federal_candidate.live.json``. Does not overwrite the sealed fixture
``federal_candidate.json``. Publication and dataset-repo upload remain false.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    digest_mapping,
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "seal_federal_register_live_candidate.py"
CANDIDATE_KIND = "live_official_complete"
LIVE_CANDIDATE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.live.json"
)
LIVE_FULLTEXT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.live.json"
)
LIVE_CORPUS_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_live_corpus.json")
LIVE_BM25_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_live_bm25.json")
LIVE_GRAPH_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_graph.live.json")
LIVE_ADJACENCY_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.live.json"
)
LIVE_EVAL_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.live.json"
)
LIVE_VECTORS_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_vectors.live.json"
)
LIVE_GOLD_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_gold.live.json")
INVENTORY_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_inventory.json")
RIGHTS_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)
EXPECTED_LIVE_DOCUMENTS = 11784
FORBIDDEN_KINDS = frozenset(
    {
        "fixture",
        "fixture_descriptor_complete",
        "compact_recipe",
        "sample",
        "sampled",
        "capped",
        "partial_checkpoint",
        "metadata_as_body",
        "stale_success",
        "failed_final",
    }
)


class LiveCandidateError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LiveCandidateError(f"required receipt missing: {path.as_posix()}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise LiveCandidateError(f"receipt root must be an object: {path.as_posix()}")
    return payload


def _require_live_pass(payload: Mapping[str, Any], *, label: str) -> None:
    if payload.get("fixture_only") is True:
        raise LiveCandidateError(f"{label} is fixture-only")
    if payload.get("authorizing_hub_upload") is True:
        raise LiveCandidateError(f"{label} authorizing_hub_upload is forbidden")
    status = str(payload.get("status") or "")
    if status and status not in {"passed", "complete"}:
        raise LiveCandidateError(f"{label} status is {status!r}")


def seal_live_candidate(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    write_receipt: bool = True,
) -> dict[str, Any]:
    inventory = _load(repository_root / INVENTORY_RELPATH)
    fulltext = _load(repository_root / LIVE_FULLTEXT_RELPATH)
    corpus = _load(repository_root / LIVE_CORPUS_RELPATH)
    bm25 = _load(repository_root / LIVE_BM25_RELPATH)
    graph = _load(repository_root / LIVE_GRAPH_RELPATH)
    adjacency = _load(repository_root / LIVE_ADJACENCY_RELPATH)
    evaluation = _load(repository_root / LIVE_EVAL_RELPATH)
    vectors = _load(repository_root / LIVE_VECTORS_RELPATH)
    gold = _load(repository_root / LIVE_GOLD_RELPATH)
    rights = _load(repository_root / RIGHTS_RELPATH)

    official_total = int((inventory.get("acceptance") or {}).get("official_total") or 0)
    if official_total != EXPECTED_LIVE_DOCUMENTS:
        raise LiveCandidateError(
            f"inventory official_total {official_total} != {EXPECTED_LIVE_DOCUMENTS}"
        )
    if str((inventory.get("acceptance") or {}).get("mode") or "") != "live":
        raise LiveCandidateError("inventory mode is not live")
    if int(fulltext.get("full_text_admitted") or 0) != official_total:
        raise LiveCandidateError("live full-text is not exhausted")
    if fulltext.get("sample_identity") is True or fulltext.get("compact_recipe") is True:
        raise LiveCandidateError("live full-text is still sampled or compact")
    for label, payload in (
        ("corpus", corpus),
        ("bm25", bm25),
        ("graph", graph),
        ("adjacency", adjacency),
        ("evaluation", evaluation),
        ("vectors", vectors),
        ("gold", gold),
    ):
        _require_live_pass(payload, label=label)
    if int(corpus.get("verified") or 0) != official_total:
        raise LiveCandidateError("live corpus is not fully verified")
    if int(bm25.get("documents") or 0) != official_total:
        raise LiveCandidateError("live BM25 is not complete")
    if evaluation.get("fixture_only") is not False:
        raise LiveCandidateError("live evaluation must set fixture_only=false")
    if int(vectors.get("vector_count") or 0) != official_total:
        raise LiveCandidateError("live vectors are not complete")
    if vectors.get("centroid_bounds_hold") is not True:
        raise LiveCandidateError("centroid routing bounds do not hold")
    if str(vectors.get("backend") or "") != "sentence_transformers":
        raise LiveCandidateError("live vectors must use sentence_transformers GTE-small")
    if gold.get("fixture_only") is not False:
        raise LiveCandidateError("live gold must set fixture_only=false")
    if CANDIDATE_KIND in FORBIDDEN_KINDS:
        raise LiveCandidateError("internal candidate kind is forbidden")

    present = [
        "bm25_documents",
        "bm25_postings",
        "centroids",
        "corpus",
        "graph_adjacency_in",
        "graph_adjacency_out",
        "graph_edges",
        "graph_nodes",
        "locator_index",
        "routing_index",
        "vectors",
    ]
    missing: list[str] = []
    payload: dict[str, Any] = {
        "acceptance": {
            "publication_not_authorized": True,
            "secrets_absent": True,
            "source_rights_bound": True,
            "live_fulltext_exhausted": True,
            "live_corpus_verified": True,
            "live_bm25_complete": True,
            "live_graph_projected": True,
            "live_evaluation_not_fixture": True,
            "live_vectors_complete": True,
            "live_gold_not_fixture": True,
            "vectors_deferred": False,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "board_namespace": "legal-corpora-reindex-v1",
        "bundle": "federal-full-live-e2e",
        "candidate": {
            "dataset_id": DEFAULT_DATASET_REPO_ID,
            "kind": CANDIDATE_KIND,
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "release_point": "federal-register/v2/2026-08-10",
            "release_profile": "federal-register-ir-graphrag/v2",
            "official_total": official_total,
            "full_text_admitted": int(fulltext.get("full_text_admitted") or 0),
            "corpus_verified": int(corpus.get("verified") or 0),
            "bm25_documents": int(bm25.get("documents") or 0),
            "graph_nodes": int(graph.get("node_count") or 0),
            "graph_edges": int(graph.get("edge_count") or 0),
            "vector_count": int(vectors.get("vector_count") or 0),
            "cluster_count": int(vectors.get("cluster_count") or 0),
            "evaluation_status": evaluation.get("status"),
        },
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": ["LCR-050", "LCR-061", "LCR-079", "LCR-055", "LCR-056", "LCR-058"],
        "evidence_root": LIVE_CANDIDATE_RELPATH.as_posix(),
        "fixture_only": False,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "live_family_outputs": {
            "adjacency_digest": adjacency.get("content_digest") or adjacency.get("graph_edge_digest"),
            "bm25_documents": int(bm25.get("documents") or 0),
            "bm25_vocabulary": int(bm25.get("vocabulary_size") or 0),
            "corpus_verified": int(corpus.get("verified") or 0),
            "evaluation_digest": evaluation.get("content_digest"),
            "fulltext_sha256": fulltext.get("checkpoint_sha256"),
            "graph_digest": graph.get("content_digest") or graph.get("edge_digest"),
            "vector_root_cid": vectors.get("vector_root_cid"),
            "vector_count": int(vectors.get("vector_count") or 0),
            "gold_digest": gold.get("content_digest"),
            "producer_task_id": TASK_ID,
        },
        "mode": "live",
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": False,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-candidate-live@1",
        "semantic_family_closure": {
            "closed": True,
            "missing": missing,
            "present": present,
            "required": present,
        },
        "source_rights": {
            "catalog_digest_sha256": rights.get("catalog_digest_sha256")
            or (rights.get("catalog") or {}).get("digest_sha256"),
            "receipt_digest": rights.get("receipt_digest"),
            "receipt_path": RIGHTS_RELPATH.as_posix(),
            "unknown_or_prohibited_excluded_from_default": True,
        },
        "task_id": TASK_ID,
        "vectors_deferred": False,
    }
    payload["content_digest"] = digest_mapping(
        {k: v for k, v in payload.items() if k != "content_digest"}
    )
    if write_receipt:
        out = repository_root / LIVE_CANDIDATE_RELPATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload["receipt_path"] = LIVE_CANDIDATE_RELPATH.as_posix()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seal live FR candidate without Hub upload")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--no-write-receipt", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        payload = seal_live_candidate(
            repository_root=args.repository_root,
            write_receipt=not bool(args.no_write_receipt),
        )
    except LiveCandidateError as exc:
        sys.stderr.write(f"seal_federal_register_live_candidate: FAILED: {exc}\n")
        return 1
    if payload.get("authorizing_hub_upload") is True:
        sys.stderr.write(
            "seal_federal_register_live_candidate: FAILED: hub upload must stay false\n"
        )
        return 1
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "seal_federal_register_live_candidate: "
            f"kind={payload['candidate']['kind']} "
            f"fixture_only={payload['fixture_only']} "
            f"hub_upload={payload['authorizing_hub_upload']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
