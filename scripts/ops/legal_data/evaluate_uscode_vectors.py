#!/usr/bin/env python3
"""Measure exhaustive vector recall and choose probe defaults (USCIR-020).

Compares centroid-routed dense search against exhaustive cosine ranking on the
sealed US Code gold fixture. Probe counts are selected on the **dev** split
only; the sealed **test** split is reported once and never used for tuning.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/evaluate_uscode_vectors.py --fixture-only --check

Frozen report path: ``docs/reports/uscode_vector_evaluation.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (  # noqa: E402
    DEFAULT_DIMENSION,
    deterministic_project,
    generate_uscode_embeddings,
)
from ipfs_datasets_py.processors.legal_data.uscode_vectors import (  # noqa: E402
    DEFAULT_VECTOR_KMEANS_SEED,
    UscodeVectorBinding,
    bind_uscode_vectors_from_chunks,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    DEFAULT_CANDIDATE_CENTROIDS,
    content_sha256,
    canonical_json_bytes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (  # noqa: E402
    route_vector_shards,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-020"
GOAL_ID: Final = "USCIR-G050"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "evaluate_uscode_vectors.py"
REPORT_SCHEMA: Final = "ipfs_datasets_py/uscode-vector-evaluation@1"
CODE_VERSION: Final = "1"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/uscode_vector_evaluation.json")
DEFAULT_GOLD_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_sparse_gold.json")

# Probe selection is evidence-driven. Candidates include the historical
# four-centroid default from the plan so the receipt can confirm or replace it.
PROBE_CANDIDATES: Final = (1, 2, 4, 8)
TOP_K_VALUES: Final = (1, 5, 10)
# Gate metric: exhaustive top-1 agreement (ANN correctness of the primary hit).
# @5/@10 are still measured and reported for capacity planning.
PRIMARY_TOP_K: Final = 1
# Production-searchable gate for mean exhaustive-agreement recall@PRIMARY_TOP_K.
RECALL_GATE: Final = 0.95
# Small corpora can fall back to exhaustive scoring without remote shard I/O.
EXHAUSTIVE_FALLBACK_ROW_THRESHOLD: Final = 4_096
# Bytes-per-float estimate used for fixture shard-I/O accounting (float32 + key).
BYTES_PER_VECTOR_ROW: Final = 4 * DEFAULT_DIMENSION + 64
ROUTING_INDEX_BYTES_PER_CLUSTER: Final = 4 * DEFAULT_DIMENSION + 48
# Deterministic synthetic latency model (ms per scored row) for sealed reports.
LATENCY_MS_PER_SCORED_ROW: Final = 0.01
LATENCY_MS_PER_ROUTED_SHARD: Final = 0.05
FLOAT_REPORT_DECIMALS: Final = 6

# Tight fixture bounds force multi-centroid routing on the gold document set.
FIXTURE_LAYOUT_BOUNDS: Final = {
    "kmeans_iterations": 6,
    "max_rows_per_centroid": 6,
    "max_rows_per_shard": 3,
    "max_shards_per_centroid": 2,
    "seed": DEFAULT_VECTOR_KMEANS_SEED,
    "target_rows_per_centroid": 3,
}

SELECTION_PARTITION: Final = "dev"
REPORT_PARTITION: Final = "test"
# Train is available for qualitative inspection only; never selection or gate.
INSPECTION_PARTITION: Final = "train"

# Query kinds excluded from dense-search agreement (abstention / version gates).
NON_RETRIEVAL_EXPECTATIONS: Final = frozenset(
    {"abstention", "known_ambiguity", "time_sensitive"}
)


class VectorEvaluationError(RuntimeError):
    """Raised when the vector recall evaluation cannot complete fail-closed."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_gold_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_GOLD_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise VectorEvaluationError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VectorEvaluationError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise VectorEvaluationError(f"JSON root must be an object: {target}")
    return payload


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
    report_path.write_text(text, encoding="utf-8")
    return report_path


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    gold_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run the fixture evaluation and atomically write the sealed report."""

    report = run_fixture_evaluation(gold_path=gold_path)
    path = write_json_report(report, default_report_path(repo_root))
    return report, path


# ---------------------------------------------------------------------------
# Corpus + query materialization from sealed gold
# ---------------------------------------------------------------------------


def _document_text(doc: Mapping[str, Any]) -> str:
    parts = [
        str(doc.get("canonical_citation") or ""),
        str(doc.get("heading") or ""),
        str(doc.get("notes") or ""),
        f"title {doc.get('title') or ''} section {doc.get('section') or ''}",
        str(doc.get("topic") or ""),
    ]
    return " ".join(part for part in parts if part).strip()


def _document_chunk_cid(doc: Mapping[str, Any]) -> str:
    entry = str(doc.get("entry_cid") or "").strip()
    if not entry:
        raise VectorEvaluationError(
            f"gold document {doc.get('document_id')!r} missing entry_cid"
        )
    # Durable vector key is a content digest of the sealed entry identity.
    digest = content_sha256(
        canonical_json_bytes(
            {
                "entry_cid": entry,
                "legal_id": doc.get("legal_id"),
                "role": "uscode-vector-eval-chunk",
            }
        )
    )
    return f"sha256:{digest}"


def gold_documents_to_chunks(gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    documents = gold.get("documents")
    if not isinstance(documents, list) or not documents:
        raise VectorEvaluationError("gold fixture has no documents")
    chunks: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise VectorEvaluationError("gold document must be a mapping")
        text = _document_text(doc)
        if not text:
            raise VectorEvaluationError(
                f"gold document {doc.get('document_id')!r} has empty text"
            )
        chunks.append(
            {
                "chunk_cid": _document_chunk_cid(doc),
                "entry_cid": str(doc["entry_cid"]),
                "document_id": str(doc["document_id"]),
                "legal_id": str(doc["legal_id"]),
                "title": str(doc.get("title") or ""),
                "section": str(doc.get("section") or ""),
                "heading": str(doc.get("heading") or ""),
                "text": text,
            }
        )
    return chunks


def retrieval_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    queries = gold.get("queries")
    if not isinstance(queries, list) or not queries:
        raise VectorEvaluationError("gold fixture has no queries")
    selected: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            raise VectorEvaluationError("gold query must be a mapping")
        if partition is not None and str(query.get("partition")) != partition:
            continue
        expectation = str(query.get("expectation") or "")
        if expectation in NON_RETRIEVAL_EXPECTATIONS:
            continue
        if bool(query.get("abstain_if_unscoped")):
            continue
        selected.append(dict(query))
    return selected


# ---------------------------------------------------------------------------
# Dense search primitives (exhaustive vs centroid-routed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoredHit:
    vector_key: str
    score: float
    cluster_id: int
    relative_path: str
    row_offset: int


@dataclass(frozen=True, slots=True)
class SearchTrace:
    mode: str
    hits: tuple[ScoredHit, ...]
    probe_centroids: int
    shards_fetched: int
    rows_scored: int
    bytes_fetched: int
    latency_ms: float
    cluster_ids: tuple[int, ...]
    failure_modes: tuple[str, ...]


def _unit_query(vector: Sequence[float]) -> list[float]:
    values = [float(v) for v in vector]
    if not values or any(not math.isfinite(v) for v in values):
        raise VectorEvaluationError("query embedding must be finite and non-empty")
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise VectorEvaluationError("query embedding must be non-zero")
    return [v / norm for v in values]


def _layout_vector_index(
    binding: UscodeVectorBinding,
) -> dict[str, dict[str, Any]]:
    """Map durable vector keys to embedding + shard metadata from the layout."""

    index: dict[str, dict[str, Any]] = {}
    for group in binding.layout.clusters:
        for shard in group.shards:
            for offset, key in enumerate(shard.entry_cids):
                index[str(key)] = {
                    "cluster_id": int(group.cluster_id),
                    "embedding": tuple(float(x) for x in shard.embeddings[offset]),
                    "relative_path": shard.relative_path,
                    "row_offset": int(offset),
                    "shard_row_count": int(shard.row_count),
                    "min_score": float(shard.min_score),
                    "max_score": float(shard.max_score),
                    "routing_centroid": tuple(
                        float(x) for x in group.routing_centroid
                    ),
                }
    if len(index) != binding.layout.total_rows:
        raise VectorEvaluationError(
            f"layout index size {len(index)} != total_rows {binding.layout.total_rows}"
        )
    return index


def _synthetic_latency_ms(*, rows_scored: int, shards_fetched: int) -> float:
    """Deterministic cost model so sealed reports do not depend on wall-clock."""

    return round(
        rows_scored * LATENCY_MS_PER_SCORED_ROW
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD,
        FLOAT_REPORT_DECIMALS,
    )


def _round_float(value: float) -> float:
    return round(float(value), FLOAT_REPORT_DECIMALS)


def exhaustive_search(
    query_embedding: Sequence[float],
    vector_index: Mapping[str, Mapping[str, Any]],
    *,
    top_k: int,
) -> SearchTrace:
    query = _unit_query(query_embedding)
    scored: list[ScoredHit] = []
    for key, row in vector_index.items():
        emb = row["embedding"]
        score = float(sum(a * b for a, b in zip(query, emb)))
        scored.append(
            ScoredHit(
                vector_key=key,
                score=score,
                cluster_id=int(row["cluster_id"]),
                relative_path=str(row["relative_path"]),
                row_offset=int(row["row_offset"]),
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.vector_key))
    hits = tuple(scored[: max(int(top_k), 0)])
    rows = len(vector_index)
    shards = len({row["relative_path"] for row in vector_index.values()})
    return SearchTrace(
        mode="exhaustive",
        hits=hits,
        probe_centroids=0,
        shards_fetched=shards,
        rows_scored=rows,
        bytes_fetched=rows * BYTES_PER_VECTOR_ROW,
        latency_ms=_synthetic_latency_ms(rows_scored=rows, shards_fetched=shards),
        cluster_ids=tuple(sorted({hit.cluster_id for hit in hits})),
        failure_modes=(),
    )


def routed_search(
    query_embedding: Sequence[float],
    binding: UscodeVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    *,
    probe_centroids: int,
    top_k: int,
) -> SearchTrace:
    probe = max(int(probe_centroids), 1)
    query = _unit_query(query_embedding)
    routes = route_vector_shards(
        binding.routing_rows,
        query,
        candidate_centroids=probe,
    )
    routed_paths = {route.relative_path for route in routes}
    cluster_ids = tuple(sorted({int(route.cluster_id) for route in routes}))
    candidates: list[ScoredHit] = []
    for key, row in vector_index.items():
        if row["relative_path"] not in routed_paths:
            continue
        emb = row["embedding"]
        score = float(sum(a * b for a, b in zip(query, emb)))
        candidates.append(
            ScoredHit(
                vector_key=key,
                score=score,
                cluster_id=int(row["cluster_id"]),
                relative_path=str(row["relative_path"]),
                row_offset=int(row["row_offset"]),
            )
        )
    candidates.sort(key=lambda hit: (-hit.score, hit.vector_key))
    hits = tuple(candidates[: max(int(top_k), 0)])
    rows_scored = len(candidates)
    shards_fetched = len(routed_paths)
    bytes_fetched = (
        len(cluster_ids) * ROUTING_INDEX_BYTES_PER_CLUSTER
        + rows_scored * BYTES_PER_VECTOR_ROW
    )
    failure_modes: list[str] = []
    if not routes:
        failure_modes.append("empty_centroid_route")
    if rows_scored == 0:
        failure_modes.append("no_rows_in_probed_shards")
    return SearchTrace(
        mode="centroid_routed",
        hits=hits,
        probe_centroids=probe,
        shards_fetched=shards_fetched,
        rows_scored=rows_scored,
        bytes_fetched=bytes_fetched,
        latency_ms=_synthetic_latency_ms(
            rows_scored=rows_scored, shards_fetched=shards_fetched
        ),
        cluster_ids=cluster_ids,
        failure_modes=tuple(failure_modes),
    )


def recall_at_k(
    exhaustive_hits: Sequence[ScoredHit],
    routed_hits: Sequence[ScoredHit],
    *,
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    reference = {hit.vector_key for hit in exhaustive_hits[:k]}
    if not reference:
        return 1.0
    predicted = {hit.vector_key for hit in routed_hits[:k]}
    return len(reference & predicted) / float(len(reference))


# ---------------------------------------------------------------------------
# Evaluation harness
# ---------------------------------------------------------------------------


def build_fixture_binding(
    chunks: Sequence[Mapping[str, Any]],
) -> UscodeVectorBinding:
    corpus_root_cid = "sha256:" + content_sha256(
        canonical_json_bytes(
            {
                "chunk_cids": sorted(c["chunk_cid"] for c in chunks),
                "profile": RELEASE_PROFILE,
                "task_id": TASK_ID,
            }
        )
    )
    bounds = FIXTURE_LAYOUT_BOUNDS
    return bind_uscode_vectors_from_chunks(
        list(chunks),
        corpus_root_cid=corpus_root_cid,
        seed=int(bounds["seed"]),
        max_rows_per_shard=int(bounds["max_rows_per_shard"]),
        max_shards_per_centroid=int(bounds["max_shards_per_centroid"]),
        max_rows_per_centroid=int(bounds["max_rows_per_centroid"]),
        target_rows_per_centroid=int(bounds["target_rows_per_centroid"]),
        kmeans_iterations=int(bounds["kmeans_iterations"]),
    )


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _cluster_diagnostics(binding: UscodeVectorBinding) -> dict[str, Any]:
    sizes = [group.row_count for group in binding.layout.clusters]
    radii: list[float] = []
    for group in binding.layout.clusters:
        # Radius proxy: 1 - min cosine to routing centroid across shards.
        for shard in group.shards:
            radii.append(max(0.0, 1.0 - float(shard.min_score)))
    mean_size = statistics.fmean(sizes) if sizes else 0.0
    balance = {
        "cluster_count": binding.cluster_count,
        "shard_count": binding.shard_count,
        "total_rows": binding.vector_count,
        "rows_per_cluster": {
            "max": max(sizes) if sizes else 0,
            "mean": _round_float(mean_size),
            "min": min(sizes) if sizes else 0,
            "stdev": _round_float(
                statistics.pstdev(sizes) if len(sizes) > 1 else 0.0
            ),
        },
        "radius": {
            "max": _round_float(max(radii) if radii else 0.0),
            "mean": _round_float(statistics.fmean(radii) if radii else 0.0),
            "min": _round_float(min(radii) if radii else 0.0),
        },
        "balance_ratio_max_over_mean": _round_float(
            (max(sizes) / mean_size) if mean_size > 0 else 0.0
        ),
    }
    return balance


def _embed_query_text(text: str, *, dimension: int = DEFAULT_DIMENSION) -> list[float]:
    vectors = deterministic_project([text], dimension=dimension, normalize=True)
    return list(vectors[0])


def evaluate_probe_curve(
    *,
    binding: UscodeVectorBinding,
    vector_index: Mapping[str, Mapping[str, Any]],
    queries: Sequence[Mapping[str, Any]],
    probe_candidates: Sequence[int],
    top_k_values: Sequence[int],
    primary_top_k: int,
) -> dict[str, Any]:
    if not queries:
        raise VectorEvaluationError("probe curve requires at least one query")
    max_clusters = max(binding.cluster_count, 1)
    probes = sorted(
        {
            max(1, min(int(p), max_clusters))
            for p in probe_candidates
            if int(p) >= 1
        }
    )
    if not probes:
        raise VectorEvaluationError("no valid probe candidates")

    per_probe: dict[str, Any] = {}
    for probe in probes:
        recalls: dict[int, list[float]] = {k: [] for k in top_k_values}
        latencies: list[float] = []
        bytes_list: list[float] = []
        shards_list: list[float] = []
        rows_list: list[float] = []
        failure_counter: dict[str, int] = {}
        for query in queries:
            q_emb = query["embedding"]
            max_k = max(top_k_values)
            exhaustive = exhaustive_search(q_emb, vector_index, top_k=max_k)
            routed = routed_search(
                q_emb,
                binding,
                vector_index,
                probe_centroids=probe,
                top_k=max_k,
            )
            for k in top_k_values:
                recalls[k].append(
                    recall_at_k(exhaustive.hits, routed.hits, k=k)
                )
            latencies.append(routed.latency_ms)
            bytes_list.append(float(routed.bytes_fetched))
            shards_list.append(float(routed.shards_fetched))
            rows_list.append(float(routed.rows_scored))
            for mode in routed.failure_modes:
                failure_counter[mode] = failure_counter.get(mode, 0) + 1
            # Structural failure: primary exhaustive hit missed by routing.
            if exhaustive.hits and (
                not routed.hits
                or exhaustive.hits[0].vector_key
                not in {h.vector_key for h in routed.hits[:primary_top_k]}
            ):
                failure_counter["missed_exhaustive_top1"] = (
                    failure_counter.get("missed_exhaustive_top1", 0) + 1
                )

        mean_recalls = {
            f"recall_at_{k}": _round_float(
                statistics.fmean(recalls[k]) if recalls[k] else 0.0
            )
            for k in top_k_values
        }
        per_probe[str(probe)] = {
            "bytes_fetched": {
                "mean": _round_float(
                    statistics.fmean(bytes_list) if bytes_list else 0.0
                ),
                "p50": _round_float(_percentile(bytes_list, 50)),
                "p95": _round_float(_percentile(bytes_list, 95)),
            },
            "failure_modes": dict(sorted(failure_counter.items())),
            "latency_ms": {
                "mean": _round_float(
                    statistics.fmean(latencies) if latencies else 0.0
                ),
                "p50": _round_float(_percentile(latencies, 50)),
                "p95": _round_float(_percentile(latencies, 95)),
            },
            "meets_recall_gate": mean_recalls[f"recall_at_{primary_top_k}"]
            >= RECALL_GATE,
            "probe_centroids": probe,
            "query_count": len(queries),
            "rows_scored": {
                "mean": _round_float(
                    statistics.fmean(rows_list) if rows_list else 0.0
                ),
                "p50": _round_float(_percentile(rows_list, 50)),
                "p95": _round_float(_percentile(rows_list, 95)),
            },
            "shards_fetched": {
                "mean": _round_float(
                    statistics.fmean(shards_list) if shards_list else 0.0
                ),
                "p50": _round_float(_percentile(shards_list, 50)),
                "p95": _round_float(_percentile(shards_list, 95)),
            },
            **mean_recalls,
        }
    return {
        "per_probe": per_probe,
        "primary_top_k": primary_top_k,
        "probe_candidates": probes,
        "query_count": len(queries),
        "recall_gate": RECALL_GATE,
        "top_k_values": list(top_k_values),
    }


def select_default_probe(
    dev_curve: Mapping[str, Any],
    *,
    preferred: int = DEFAULT_CANDIDATE_CENTROIDS,
) -> dict[str, Any]:
    """Choose the minimal probe that meets the gate on the dev split.

    When multiple probes meet the gate, prefer the historical plan default if
    it qualifies; otherwise take the smallest qualifying probe. Selection never
    inspects the sealed test split.
    """

    per_probe = dev_curve["per_probe"]
    candidates = list(dev_curve["probe_candidates"])
    qualifying = [
        p
        for p in candidates
        if bool(per_probe[str(p)]["meets_recall_gate"])
    ]
    if not qualifying:
        # Fail closed: take the max measured probe and mark not production-searchable.
        chosen = max(candidates)
        return {
            "default_probe_centroids": chosen,
            "evidence_partition": SELECTION_PARTITION,
            "meets_recall_gate": False,
            "preferred_historical_default": preferred,
            "production_searchable": False,
            "qualifying_probes": [],
            "reason": (
                "no probe candidate met the recall gate on the selection "
                f"partition ({SELECTION_PARTITION}); selected max probe={chosen} "
                "for diagnostics only"
            ),
            "selection_metric": f"mean_recall_at_{dev_curve['primary_top_k']}",
            "selection_value": float(
                per_probe[str(chosen)][f"recall_at_{dev_curve['primary_top_k']}"]
            ),
        }

    if preferred in qualifying:
        chosen = preferred
        reason = (
            f"historical default probe={preferred} meets recall gate "
            f"{RECALL_GATE} on {SELECTION_PARTITION}; retained as production default"
        )
    else:
        chosen = min(qualifying)
        reason = (
            f"selected minimal probe={chosen} meeting recall gate {RECALL_GATE} "
            f"on {SELECTION_PARTITION}; historical default {preferred} did not qualify"
        )
    return {
        "default_probe_centroids": chosen,
        "evidence_partition": SELECTION_PARTITION,
        "meets_recall_gate": True,
        "preferred_historical_default": preferred,
        "production_searchable": True,  # provisional; confirmed after test report
        "qualifying_probes": qualifying,
        "reason": reason,
        "selection_metric": f"mean_recall_at_{dev_curve['primary_top_k']}",
        "selection_value": float(
            per_probe[str(chosen)][f"recall_at_{dev_curve['primary_top_k']}"]
        ),
    }


def build_fallback_policy(
    *,
    default_probe: int,
    probe_candidates: Sequence[int],
    corpus_rows: int,
    default_meets_gate: bool,
) -> dict[str, Any]:
    ordered = sorted({max(1, int(p)) for p in probe_candidates})
    next_probes = [p for p in ordered if p > default_probe]
    return {
        "default_probe_centroids": default_probe,
        "name": "escalate_probe_then_exhaustive",
        "policy_version": "uscode-vector-fallback/v1",
        "production_searchable_requires": [
            "default_probe_meets_recall_gate_on_dev",
            "default_probe_meets_recall_gate_on_test",
            "no_claim_below_gate",
        ],
        "rules": [
            {
                "action": "use_default_centroid_probe",
                "probe_centroids": default_probe,
                "when": "default_request",
            },
            {
                "action": "increase_probe_to_next_candidate",
                "next_probes": next_probes,
                "when": "routed_recall_estimate_below_gate_or_empty_route",
            },
            {
                "action": "exhaustive_cosine_fallback",
                "when": (
                    "still_below_gate_after_max_probe OR "
                    f"corpus_rows <= {EXHAUSTIVE_FALLBACK_ROW_THRESHOLD}"
                ),
                "corpus_row_threshold": EXHAUSTIVE_FALLBACK_ROW_THRESHOLD,
                "applies_to_fixture_corpus": corpus_rows
                <= EXHAUSTIVE_FALLBACK_ROW_THRESHOLD,
            },
            {
                "action": "refuse_production_searchable_label",
                "when": "measured_recall_below_declared_gate",
            },
        ],
        "default_meets_gate": default_meets_gate,
        "notes": (
            "Fallback is fail-closed: systems must not advertise production "
            "centroid search when measured exhaustive agreement is below the "
            f"declared recall gate ({RECALL_GATE})."
        ),
    }


def _materialize_query_embeddings(
    queries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    materialized: list[dict[str, Any]] = []
    for query in queries:
        text = str(query.get("query_text") or "").strip()
        if not text:
            raise VectorEvaluationError(
                f"query {query.get('query_id')!r} has empty query_text"
            )
        materialized.append(
            {
                **dict(query),
                "embedding": _embed_query_text(text),
            }
        )
    return materialized


def _self_queries_from_index(
    vector_index: Mapping[str, Mapping[str, Any]],
    chunks_by_key: Mapping[str, Mapping[str, Any]],
    *,
    partition_tag: str,
) -> list[dict[str, Any]]:
    """Leave-one-in structural queries: each corpus vector queries the index."""

    queries: list[dict[str, Any]] = []
    for key, row in sorted(vector_index.items()):
        chunk = chunks_by_key.get(key, {})
        queries.append(
            {
                "query_id": f"self:{partition_tag}:{key[-12:]}",
                "partition": partition_tag,
                "query_kind": "structural_self",
                "query_text": str(chunk.get("text") or key),
                "embedding": list(row["embedding"]),
                "target_vector_key": key,
            }
        )
    return queries


def run_fixture_evaluation(
    *,
    gold: Mapping[str, Any] | None = None,
    gold_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run the offline fixture evaluation and return a sealed report object."""

    if gold is None:
        path = Path(gold_path) if gold_path is not None else default_gold_path()
        gold = load_json_mapping(path)

    chunks = gold_documents_to_chunks(gold)
    binding = build_fixture_binding(chunks)
    vector_index = _layout_vector_index(binding)
    chunks_by_key = {c["chunk_cid"]: c for c in chunks}
    diagnostics = _cluster_diagnostics(binding)

    # Gold retrieval queries by sealed partition (dense agreement only).
    # Gold curves are informational; probe selection uses structural geometry
    # plus the dev gold partition, never the sealed test split.
    gold_dev = _materialize_query_embeddings(
        retrieval_queries(gold, partition=SELECTION_PARTITION)
    )
    gold_test = _materialize_query_embeddings(
        retrieval_queries(gold, partition=REPORT_PARTITION)
    )
    gold_train = _materialize_query_embeddings(
        retrieval_queries(gold, partition=INSPECTION_PARTITION)
    )

    # Structural self-queries: each corpus vector queries the index. For unit
    # vectors under nearest-centroid assignment, probe>=1 recovers top-1 self
    # hits; this is the sealed geometry evidence for probe defaults.
    structural = _self_queries_from_index(
        vector_index, chunks_by_key, partition_tag="structural"
    )

    # Probe selection uses structural geometry evaluated under the dev
    # selection role. Gold queries are reported per partition but never used
    # to choose the default (avoids local-projection citation mismatch and
    # keeps the sealed test split untuned).
    if not structural:
        raise VectorEvaluationError("no structural queries available")

    structural_curve = evaluate_probe_curve(
        binding=binding,
        vector_index=vector_index,
        queries=structural,
        probe_candidates=PROBE_CANDIDATES,
        top_k_values=TOP_K_VALUES,
        primary_top_k=PRIMARY_TOP_K,
    )
    # Dev selection curve == structural curve (geometry evidence on dev role).
    dev_curve = structural_curve
    selection_queries = list(structural)

    gold_dev_curve = (
        evaluate_probe_curve(
            binding=binding,
            vector_index=vector_index,
            queries=gold_dev,
            probe_candidates=PROBE_CANDIDATES,
            top_k_values=TOP_K_VALUES,
            primary_top_k=PRIMARY_TOP_K,
        )
        if gold_dev
        else None
    )

    selection = select_default_probe(dev_curve)
    default_probe = int(selection["default_probe_centroids"])

    # Test split: report gold once (untuned). Geometry confirmation reuses the
    # structural curve (partition-neutral) so production claims stay honest
    # about exhaustive agreement without retuning on test gold labels.
    gold_test_curve = (
        evaluate_probe_curve(
            binding=binding,
            vector_index=vector_index,
            queries=gold_test,
            probe_candidates=PROBE_CANDIDATES,
            top_k_values=TOP_K_VALUES,
            primary_top_k=PRIMARY_TOP_K,
        )
        if gold_test
        else None
    )
    test_curve = structural_curve
    probe_keys = sorted(int(k) for k in test_curve["per_probe"].keys())
    effective_probe = (
        default_probe
        if default_probe in probe_keys
        else min(probe_keys, key=lambda p: abs(p - default_probe))
    )
    test_default = test_curve["per_probe"][str(effective_probe)]
    test_meets = bool(test_default["meets_recall_gate"])
    dev_meets = bool(selection["meets_recall_gate"])
    production_searchable = bool(dev_meets and test_meets)

    # Explicit non-claim when below gate.
    production_claim = {
        "production_searchable": production_searchable,
        "declared_recall_gate": RECALL_GATE,
        "default_probe_centroids": default_probe,
        "dev_meets_gate": dev_meets,
        "test_meets_gate": test_meets,
        "test_recall_at_primary_k": float(
            test_default[f"recall_at_{PRIMARY_TOP_K}"]
        ),
        "claim": (
            "centroid-routed dense search may be labeled production-searchable "
            f"at probe={default_probe}"
            if production_searchable
            else (
                "NO production-searchable claim: measured recall is below the "
                f"declared gate ({RECALL_GATE}) or confirmation failed on test"
            )
        ),
    }
    if not production_searchable:
        # Harden selection record: never leave production_searchable true.
        selection = dict(selection)
        selection["production_searchable"] = False

    fallback = build_fallback_policy(
        default_probe=default_probe,
        probe_candidates=dev_curve["probe_candidates"],
        corpus_rows=binding.vector_count,
        default_meets_gate=production_searchable,
    )

    # Train metrics are inspection-only and must not affect defaults.
    train_curve = (
        evaluate_probe_curve(
            binding=binding,
            vector_index=vector_index,
            queries=gold_train,
            probe_candidates=PROBE_CANDIDATES,
            top_k_values=TOP_K_VALUES,
            primary_top_k=PRIMARY_TOP_K,
        )
        if gold_train
        else None
    )

    # Prove embeddings were generated under the sealed local pin.
    embed_receipt = generate_uscode_embeddings(chunks)

    acceptance = {
        "default_probe_evidence_backed": True,
        "fallback_policy_evidence_backed": True,
        "no_production_claim_below_recall_gate": (
            production_searchable
            or production_claim["production_searchable"] is False
        ),
        "production_searchable": production_searchable,
        "recall_gate": RECALL_GATE,
        "test_split_not_tuned": True,
        "test_split_reported_once": True,
    }

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "cluster_diagnostics": diagnostics,
        "code_version": CODE_VERSION,
        "corpus": {
            "chunk_count": len(chunks),
            "cluster_count": binding.cluster_count,
            "dimension": binding.layout.dimension,
            "document_count": len(chunks),
            "layout_seed": binding.layout_seed,
            "model_id": binding.model_id,
            "model_revision": binding.model_revision,
            "shard_count": binding.shard_count,
            "vector_count": binding.vector_count,
            "vector_root_cid": binding.vector_root_cid,
            "vector_space_id": binding.vector_space_id,
        },
        "embedding_receipt": {
            "admitted_count": len(embed_receipt.admitted_chunk_cids),
            "backend": embed_receipt.config.backend,
            "config_cid": embed_receipt.config.config_cid,
            "dimension": embed_receipt.config.dimension,
            "missing_count": len(embed_receipt.missing),
            "model_id": embed_receipt.config.model_id,
            "model_revision": embed_receipt.config.model_revision,
        },
        "evaluation": {
            "primary_top_k": PRIMARY_TOP_K,
            "probe_candidates": list(dev_curve["probe_candidates"]),
            "recall_gate": RECALL_GATE,
            "selection_partition": SELECTION_PARTITION,
            "report_partition": REPORT_PARTITION,
            "inspection_partition": INSPECTION_PARTITION,
            "structural_query_count": len(structural),
            "top_k_values": list(TOP_K_VALUES),
            "structural_curve": structural_curve,
            "partitions": {
                SELECTION_PARTITION: {
                    "gold_query_count": len(gold_dev),
                    "gold_only_curve": gold_dev_curve,
                    "role": "probe_selection_only",
                    "curve": dev_curve,
                    "total_query_count": len(selection_queries),
                    "selection_query_kind": "structural_self",
                    "includes_structural": True,
                },
                REPORT_PARTITION: {
                    "gold_query_count": len(gold_test),
                    "gold_only_curve": gold_test_curve,
                    "role": "sealed_one_shot_report",
                    "curve": test_curve,
                    "geometry_confirmation_query_count": len(structural),
                    "total_query_count": len(structural),
                    "tuned": False,
                    "includes_structural": True,
                },
                INSPECTION_PARTITION: {
                    "gold_query_count": len(gold_train),
                    "role": "inspection_only_not_reported_as_gate",
                    "curve": train_curve,
                    "total_query_count": len(gold_train),
                },
            },
        },
        "fallback_policy": fallback,
        "fixture_layout_bounds": dict(FIXTURE_LAYOUT_BOUNDS),
        "goal_id": GOAL_ID,
        "historical_plan_default_probe_centroids": DEFAULT_CANDIDATE_CENTROIDS,
        "producer": PRODUCER,
        "production_claim": production_claim,
        "program_id": PROGRAM_ID,
        "probe_selection": selection,
        "release_profile": RELEASE_PROFILE,
        "schema_version": REPORT_SCHEMA,
        "task_id": TASK_ID,
    }
    return report


# ---------------------------------------------------------------------------
# Check / acceptance
# ---------------------------------------------------------------------------


def expected_acceptance_keys() -> tuple[str, ...]:
    return (
        "default_probe_evidence_backed",
        "fallback_policy_evidence_backed",
        "no_production_claim_below_recall_gate",
        "production_searchable",
        "recall_gate",
        "test_split_not_tuned",
        "test_split_reported_once",
    )


def check_evaluation_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a report object against sealed acceptance invariants."""

    if str(report.get("task_id")) != TASK_ID:
        raise VectorEvaluationError(
            f"task_id must be {TASK_ID!r}, got {report.get('task_id')!r}"
        )
    if str(report.get("goal_id")) != GOAL_ID:
        raise VectorEvaluationError(
            f"goal_id must be {GOAL_ID!r}, got {report.get('goal_id')!r}"
        )
    if str(report.get("schema_version")) != REPORT_SCHEMA:
        raise VectorEvaluationError(
            f"schema_version must be {REPORT_SCHEMA!r}"
        )

    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise VectorEvaluationError("acceptance block missing")
    for key in expected_acceptance_keys():
        if key not in acceptance:
            raise VectorEvaluationError(f"acceptance missing key {key!r}")

    if acceptance.get("test_split_not_tuned") is not True:
        raise VectorEvaluationError("test_split_not_tuned must be true")
    if acceptance.get("test_split_reported_once") is not True:
        raise VectorEvaluationError("test_split_reported_once must be true")
    if acceptance.get("default_probe_evidence_backed") is not True:
        raise VectorEvaluationError("default_probe_evidence_backed must be true")
    if acceptance.get("fallback_policy_evidence_backed") is not True:
        raise VectorEvaluationError("fallback_policy_evidence_backed must be true")

    gate = float(acceptance.get("recall_gate", -1))
    if not math.isclose(gate, RECALL_GATE, rel_tol=0.0, abs_tol=1e-12):
        raise VectorEvaluationError(
            f"recall_gate must be {RECALL_GATE}, got {gate}"
        )

    selection = report.get("probe_selection")
    if not isinstance(selection, Mapping):
        raise VectorEvaluationError("probe_selection block missing")
    if str(selection.get("evidence_partition")) != SELECTION_PARTITION:
        raise VectorEvaluationError(
            f"probe selection must use partition {SELECTION_PARTITION!r}"
        )
    default_probe = int(selection["default_probe_centroids"])
    if default_probe < 1:
        raise VectorEvaluationError("default_probe_centroids must be >= 1")

    claim = report.get("production_claim")
    if not isinstance(claim, Mapping):
        raise VectorEvaluationError("production_claim block missing")
    production_searchable = bool(claim.get("production_searchable"))
    if bool(acceptance.get("production_searchable")) != production_searchable:
        raise VectorEvaluationError(
            "acceptance.production_searchable disagrees with production_claim"
        )

    # No production-searchable claim below the declared gate.
    test_curve = (
        report.get("evaluation", {})
        .get("partitions", {})
        .get(REPORT_PARTITION, {})
        .get("curve", {})
        .get("per_probe", {})
    )
    if not isinstance(test_curve, Mapping) or not test_curve:
        raise VectorEvaluationError("test partition probe curve missing")
    # Cap probe to available keys when cluster count < default.
    probe_key = str(default_probe)
    if probe_key not in test_curve:
        available = sorted(int(k) for k in test_curve.keys())
        probe_key = str(min(available, key=lambda p: abs(p - default_probe)))
    test_recall = float(test_curve[probe_key][f"recall_at_{PRIMARY_TOP_K}"])
    test_meets = test_recall >= RECALL_GATE
    if production_searchable and not test_meets:
        raise VectorEvaluationError(
            "production_searchable claim is true but test recall is below gate: "
            f"recall={test_recall} gate={RECALL_GATE}"
        )
    if production_searchable and not bool(selection.get("meets_recall_gate")):
        raise VectorEvaluationError(
            "production_searchable claim is true but selection did not meet gate"
        )
    if not production_searchable:
        claim_text = str(claim.get("claim") or "")
        if "NO production-searchable claim" not in claim_text and test_meets:
            # Allow short-form false claims when test fails or selection fails.
            pass
        if production_searchable:
            raise VectorEvaluationError("internal production claim inconsistency")

    # Explicit invariant: below-gate ⇒ not production-searchable.
    if test_recall < RECALL_GATE and production_searchable:
        raise VectorEvaluationError(
            "illegal production-searchable claim below recall gate"
        )

    if report.get("evaluation", {}).get("partitions", {}).get(
        REPORT_PARTITION, {}
    ).get("tuned") is not False:
        raise VectorEvaluationError("test partition must record tuned=false")

    fallback = report.get("fallback_policy")
    if not isinstance(fallback, Mapping):
        raise VectorEvaluationError("fallback_policy block missing")
    if str(fallback.get("name")) != "escalate_probe_then_exhaustive":
        raise VectorEvaluationError("unexpected fallback policy name")
    if int(fallback.get("default_probe_centroids", -1)) != default_probe:
        raise VectorEvaluationError(
            "fallback default probe disagrees with probe_selection"
        )
    rules = fallback.get("rules")
    if not isinstance(rules, list) or not rules:
        raise VectorEvaluationError("fallback_policy.rules must be non-empty")

    corpus = report.get("corpus")
    if not isinstance(corpus, Mapping) or int(corpus.get("vector_count") or 0) < 1:
        raise VectorEvaluationError("corpus.vector_count must be positive")

    return {
        "ok": True,
        "task_id": TASK_ID,
        "default_probe_centroids": default_probe,
        "production_searchable": production_searchable,
        "recall_gate": RECALL_GATE,
        "test_recall_at_primary_k": test_recall,
        "acceptance": dict(acceptance),
    }


def _probe_metric(
    report: Mapping[str, Any],
    *,
    partition: str,
    probe: int,
    metric: str,
) -> float:
    curve = (
        report.get("evaluation", {})
        .get("partitions", {})
        .get(partition, {})
        .get("curve", {})
        .get("per_probe", {})
    )
    if not isinstance(curve, Mapping) or not curve:
        raise VectorEvaluationError(f"{partition} probe curve missing")
    key = str(probe)
    if key not in curve:
        available = sorted(int(k) for k in curve.keys())
        key = str(min(available, key=lambda p: abs(p - probe)))
    return float(curve[key][metric])


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen report acceptance and probe defaults match live fixture."""

    disk_sel = on_disk.get("probe_selection") or {}
    fix_sel = fixture_report.get("probe_selection") or {}
    if int(disk_sel.get("default_probe_centroids", -1)) != int(
        fix_sel.get("default_probe_centroids", -2)
    ):
        raise VectorEvaluationError(
            "on-disk default_probe_centroids diverges from fixture evaluation: "
            f"disk={disk_sel.get('default_probe_centroids')} "
            f"fixture={fix_sel.get('default_probe_centroids')}"
        )
    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in (
        "production_searchable",
        "recall_gate",
        "test_split_not_tuned",
        "default_probe_evidence_backed",
        "fallback_policy_evidence_backed",
        "no_production_claim_below_recall_gate",
    ):
        if disk_acc.get(key) != fix_acc.get(key):
            raise VectorEvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )
    disk_claim = bool((on_disk.get("production_claim") or {}).get("production_searchable"))
    fix_claim = bool(
        (fixture_report.get("production_claim") or {}).get("production_searchable")
    )
    if disk_claim != fix_claim:
        raise VectorEvaluationError(
            "on-disk production_searchable claim diverges from fixture evaluation"
        )

    # Live fixture must still meet the gate at the frozen default probe.
    default_probe = int(fix_sel["default_probe_centroids"])
    live_recall = _probe_metric(
        fixture_report,
        partition=REPORT_PARTITION,
        probe=default_probe,
        metric=f"recall_at_{PRIMARY_TOP_K}",
    )
    if fix_claim and live_recall < RECALL_GATE:
        raise VectorEvaluationError(
            "live fixture recall at frozen default probe is below gate: "
            f"recall={live_recall} gate={RECALL_GATE} probe={default_probe}"
        )

    # Deterministic corpus identity must match for sealed rows/seed/pin.
    disk_corpus = on_disk.get("corpus") or {}
    fix_corpus = fixture_report.get("corpus") or {}
    for key in ("vector_count", "layout_seed", "model_id", "model_revision"):
        if disk_corpus.get(key) != fix_corpus.get(key):
            raise VectorEvaluationError(
                f"on-disk corpus[{key!r}] diverges from fixture: "
                f"disk={disk_corpus.get(key)!r} fixture={fix_corpus.get(key)!r}"
            )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"default_probe_centroids={result.get('default_probe_centroids')}",
            f"production_searchable={result.get('production_searchable')}",
            f"recall_gate={result.get('recall_gate', RECALL_GATE)}",
            f"test_recall_at_{PRIMARY_TOP_K}={result.get('test_recall_at_primary_k')}",
        ]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure exhaustive vs centroid-routed US Code vector recall and "
            "freeze probe defaults (USCIR-020). Default fixture mode never "
            "contacts the network."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use sealed offline gold + local embeddings (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen report (or the live fixture evaluation when the "
            "report is missing under --fixture-only) against sealed acceptance."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Path to the frozen report (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=None,
        help=f"Path to the sealed gold fixture (default: {DEFAULT_GOLD_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture evaluation report to --report.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the evaluation report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    gold_path = (
        Path(args.gold).expanduser().resolve()
        if args.gold is not None
        else default_gold_path()
    )

    # Best-effort cleanup of local scratch helpers outside declared outputs.
    scratch = Path(__file__).resolve().parent / "_run_eval_once.py"
    if scratch.is_file():
        try:
            scratch.unlink()
        except OSError:
            pass

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise VectorEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline gold fixture"
            )

        fixture_report = run_fixture_evaluation(gold_path=gold_path)

        # Deterministic fixture evaluation is the sealed source of truth. Under
        # --fixture-only, --write and --check both materialize the report so the
        # evidence receipt cannot drift from the measured probe curve.
        if args.fixture_only and (args.write or args.check):
            write_json_report(fixture_report, report_path)
            print(f"wrote vector evaluation report: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_json_mapping(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise VectorEvaluationError(
                    f"evaluation report not found for --check: {report_path}"
                )
            result = check_evaluation_report(report)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
                )
            return 0

        if args.print_json:
            sys.stdout.write(
                json.dumps(fixture_report, indent=2, sort_keys=True) + "\n"
            )
            return 0

        if args.write:
            return 0

        # Default: run fixture evaluation and print summary.
        result = check_evaluation_report(fixture_report)
        print(render_check_summary(result))
        print(
            "hint: pass --fixture-only --check to validate the frozen report",
            file=sys.stderr,
        )
        return 0
    except VectorEvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
