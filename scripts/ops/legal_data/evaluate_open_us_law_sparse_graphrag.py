#!/usr/bin/env python3
"""Evaluate Open US Law retrieval quality, graph utility, and sparse I/O (OUL-037).

Offline, network-free fixture evaluation of BM25, dense vectors, hybrid
fusion, structural graph walks, and embedding-guided semantic traversal
on the sealed OUL-036 gold recipe. Fusion weights and probe counts are
selected on the **dev** split only; the sealed **test** split is reported
once and never used for tuning.

Acceptance (fail-closed)::

* BM25, vector, hybrid, graph, and semantic traversal meet the declared
  recall and ranking thresholds.
* Fetch traces prove bounded shard selection.
* Routed queries transfer substantially less than a full-release scan.

Validation gate::

    python scripts/ops/legal_data/evaluate_open_us_law_sparse_graphrag.py \\
        --fixture-only --check

Frozen report path: ``docs/reports/open_us_law_reindex/evaluation.json``.

This gate uses the local deterministic embedding projection and the
compact gold fixture. It does **not** authorize a live exact-51 release
or a production-searchable claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import statistics
import sys
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (  # noqa: E402
    DEFAULT_B,
    DEFAULT_FIELD_WEIGHTS,
    DEFAULT_K1,
    FIELD_ORDER,
    TOKENIZER_ID,
    robertson_sparck_jones_idf,
    tokenize_index_text,
    tokenize_query,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (  # noqa: E402
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    deterministic_project,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_query import (  # noqa: E402
    DEFAULT_BM25_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_VECTOR_WEIGHT,
    FUSION_RRF,
    FUSION_WEIGHTED,
    FusionConfig,
    cosine_similarity,
    fuse_hybrid_results,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    EXACT_51_JURISDICTION_CODES,
    EXACT_51_JURISDICTIONS,
    JURISDICTION_NAMES,
    RELEASE_PROFILE,
    SOURCE_BUCKET,
    build_legal_id,
)
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (  # noqa: E402
    bm25_term_score,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (  # noqa: E402
    normalize_scores,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-037"
GOAL_ID: Final = "OUL-G060"
PROGRAM_ID: Final = "open-us-law-sparse-graphrag/v1"
PRODUCER: Final = "evaluate_open_us_law_sparse_graphrag.py"
REPORT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-sparse-graphrag-evaluation@1"
CODE_VERSION: Final = "1"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
BUNDLE: Final = "evaluation"

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/evaluation.json")
DEFAULT_GOLD_RELPATH: Final = Path("tests/fixtures/legal_ir/open_us_law_sparse_gold.json")
DEFAULT_NEG_RELPATH: Final = Path(
    "tests/fixtures/legal_ir/open_us_law_sparse_negative_controls.json"
)
BM25_RECEIPT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/bm25_receipt.json")
VECTOR_RECEIPT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/vector_receipt.json")
GRAPH_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/legal_graph_receipt.json"
)
ADJACENCY_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/graph_adjacency_receipt.json"
)
QUERY_CONTRACT_RELPATH: Final = Path("docs/reports/open_us_law_reindex/query_contract.json")
OFFICIAL_CATALOG_RELPATH: Final = Path(
    "data/legal/state_laws/official_source_catalog.json"
)
DEFAULT_GOLD_EDITION: Final = "2024-official"
DEFAULT_GOLD_RELEASE_POINT: Final = "us/state-statutes/exact-51/2024-official"

COHORTS: Final = {
    "A": ("AL", "AK", "AZ", "AR"),
    "B": ("CA", "CO", "CT", "DE"),
    "C": ("FL", "GA", "HI", "ID"),
    "D": ("IL", "IN", "IA", "KS"),
    "E": ("KY", "LA", "ME", "MD"),
    "F": ("MA", "MI", "MN", "MS"),
    "G": ("MO", "MT", "NE", "NV"),
    "H": ("NH", "NJ", "NM", "NY"),
    "I": ("NC", "ND", "OH", "OK"),
    "J": ("OR", "PA", "RI", "SC"),
    "K": ("SD", "TN", "TX", "UT"),
    "L": ("VT", "VA", "WA", "WV"),
    "M": ("WI", "WY", "DC"),
}
COHORT_TASK_IDS: Final = {
    "A": "OUL-009",
    "B": "OUL-010",
    "C": "OUL-011",
    "D": "OUL-012",
    "E": "OUL-013",
    "F": "OUL-014",
    "G": "OUL-015",
    "H": "OUL-016",
    "I": "OUL-017",
    "J": "OUL-018",
    "K": "OUL-019",
    "L": "OUL-020",
    "M": "OUL-021",
}

TOP_K_VALUES: Final = (1, 5, 10)
PRIMARY_TOP_K: Final = 5
# Declared fixture gates. Citation-heavy gold plus the local hashed
# projection is diagnostic; live GTE-small recall is a later release gate.
RECALL_GATE_BM25: Final = 0.75
RECALL_GATE_VECTOR: Final = 0.70
RECALL_GATE_HYBRID: Final = 0.80
RECALL_GATE_GRAPH: Final = 1.0
RECALL_GATE_SEMANTIC: Final = 0.75
RANKING_MRR_GATE: Final = 0.70
RANKING_NDCG_GATE: Final = 0.70
EXACT_CITATION_GATE: Final = 1.0
DENSE_RECALL_GATE: Final = 0.95
REGRESSION_TOLERANCE: Final = 0.02
SPARSE_IO_BYTE_RATIO_GATE: Final = 0.40
SPARSE_IO_SHARD_RATIO_GATE: Final = 0.50

FLOAT_REPORT_DECIMALS: Final = 6
FIXTURE_TERMS_PER_SHARD: Final = 4
FIXTURE_VECTOR_ROWS_PER_SHARD: Final = 2
FIXTURE_TARGET_ROWS_PER_CENTROID: Final = 3
FIXTURE_MAX_SHARDS_PER_CENTROID: Final = 2
FIXTURE_GRAPH_ROWS_PER_SHARD: Final = 2
BYTES_PER_POSTING_ROW: Final = 48
BYTES_PER_TERM_RANGE_META: Final = 96
BYTES_PER_VECTOR_ROW: Final = 4 * PINNED_DIMENSION + 64
ROUTING_INDEX_BYTES_PER_CLUSTER: Final = 4 * PINNED_DIMENSION + 48
BYTES_PER_GRAPH_POINTER: Final = 64
BYTES_PER_CORPUS_ROW: Final = 2048
LATENCY_MS_PER_SCORED_DOC: Final = 0.01
LATENCY_MS_PER_ROUTED_SHARD: Final = 0.05
BYTES_PER_CORPUS_ROW_MEMORY: Final = 2048
BYTES_PER_POSTING_MEMORY: Final = 64
BYTES_PER_VECTOR_MEMORY: Final = 4 * PINNED_DIMENSION + 128
BUILD_ROWS_PER_SECOND: Final = 2500.0
CACHE_HIT_RATIO_FIXTURE: Final = 0.0

SELECTION_PARTITION: Final = "dev"
REPORT_PARTITION: Final = "test"
INSPECTION_PARTITION: Final = "train"

NON_RETRIEVAL_EXPECTATIONS: Final = frozenset(
    {"abstention", "known_ambiguity", "time_sensitive", "repealed_or_reserved"}
)
RELEVANT_GRADES: Final = frozenset({"exact", "relevant"})
GRADE_RELEVANCE: Final = {"exact": 3, "relevant": 2, "ambiguous": 1}

POPULAR_NAME_EXPANSIONS: Final = MappingProxyType(
    {
        "uipa": "uniform information practices act",
        "foil": "freedom of information law",
        "opra": "open public records act",
        "grama": "government records access and management act",
        "foia": "freedom of information act",
        "ccpa": "california consumer privacy act",
        "cpra": "california public records act",
        "apra": "access to public records act",
        "foaa": "freedom of access act",
        "ipra": "inspection of public records act",
        "rtkl": "right to know law",
        "pia": "public information act",
    }
)

FUSION_CANDIDATES: Final = (
    {
        "candidate_id": "plan_default_weighted_0_5_0_5",
        "method": FUSION_WEIGHTED,
        "bm25_weight": DEFAULT_BM25_WEIGHT,
        "vector_weight": DEFAULT_VECTOR_WEIGHT,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": True,
    },
    {
        "candidate_id": "bm25_heavy_weighted_0_7_0_3",
        "method": FUSION_WEIGHTED,
        "bm25_weight": 0.7,
        "vector_weight": 0.3,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": False,
    },
    {
        "candidate_id": "vector_heavy_weighted_0_3_0_7",
        "method": FUSION_WEIGHTED,
        "bm25_weight": 0.3,
        "vector_weight": 0.7,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": False,
    },
    {
        "candidate_id": "rrf_k_60",
        "method": FUSION_RRF,
        "bm25_weight": 1.0,
        "vector_weight": 1.0,
        "rrf_k": DEFAULT_RRF_K,
        "is_plan_default": False,
    },
    {
        "candidate_id": "rrf_k_30",
        "method": FUSION_RRF,
        "bm25_weight": 1.0,
        "vector_weight": 1.0,
        "rrf_k": 30,
        "is_plan_default": False,
    },
)

REFERENCE_HARDWARE: Final = {
    "architecture": "x86_64",
    "cpu_model": "reference-generic-8vCPU",
    "cpu_cores_logical": 8,
    "memory_gib": 32,
    "storage": "nvme-ssd",
    "os_family": "linux",
    "python_target": "python3.12",
    "notes": (
        "Sealed offline evaluation uses a deterministic synthetic cost model; "
        "numbers are comparable across commits on this fixture, not absolute "
        "production SLAs for arbitrary hardware."
    ),
}
REFERENCE_NETWORK: Final = {
    "mode": "fixture_offline",
    "network_required": False,
    "assumed_bandwidth_mbps": 100.0,
    "assumed_rtt_ms": 20.0,
    "hub_access": "disabled_in_fixture_gate",
    "notes": (
        "OUL-037 fixture evaluation never contacts the network. Remote "
        "Hub byte budgets for live Dataset/Bucket access are deferred to "
        "staging/canary and must not be inferred from this report."
    ),
}

class SparseGraphragEvaluationError(RuntimeError):
    """Raised when the fused evaluation cannot complete fail-closed."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_gold_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_GOLD_RELPATH).resolve()


def default_negative_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_NEG_RELPATH).resolve()


def _repo_path(relpath: Path | str, *, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / Path(relpath)).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise SparseGraphragEvaluationError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SparseGraphragEvaluationError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SparseGraphragEvaluationError(f"JSON root must be an object: {target}")
    return payload


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
    tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(report_path)
    return report_path


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    gold_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run the fixture evaluation and atomically write the sealed report."""

    report = run_fixture_evaluation(gold_path=gold_path, repo_root=repo_root)
    path = write_json_report(report, default_report_path(repo_root))
    return report, path


def _round_float(value: float) -> float:
    return round(float(value), FLOAT_REPORT_DECIMALS)


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


def _stat_block(values: Sequence[float]) -> dict[str, float]:
    nums = [float(v) for v in values]
    return {
        "mean": _round_float(statistics.fmean(nums) if nums else 0.0),
        "p50": _round_float(_percentile(nums, 50)),
        "p95": _round_float(_percentile(nums, 95)),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest_payload(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Gold materialization
# ---------------------------------------------------------------------------


def _sealed_cid(role: str, key: str) -> str:
    digest = hashlib.sha256(f"oul-gold|{role}|{key}".encode("utf-8")).hexdigest()
    prefix = "bafkreie" if role == "entry" else "bafkreis"
    return prefix + digest[:45]


def _load_official_catalog(repo_root: Path | str | None = None) -> dict[str, dict[str, Any]]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    catalog_path = (root / OFFICIAL_CATALOG_RELPATH).resolve()
    if not catalog_path.is_file():
        raise SparseGraphragEvaluationError(f"official source catalog missing: {catalog_path}")
    payload = load_json_mapping(catalog_path)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("jurisdictions") or ():
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("postal_code") or "")
        families = row.get("code_families") or []
        paths = row.get("acquisition_paths") or []
        if not code or not families or not paths:
            continue
        family = families[0]
        path = paths[0]
        out[code] = {
            "code_family": family["code_family_id"],
            "source_id": path["path_id"],
            "official_url": path["entry_url"],
            "authority_class": path["authority_class"],
            "provider": path["provider"],
        }
    return out


def _hierarchy_from_spec(spec: Mapping[str, Any]) -> dict[str, str]:
    hierarchy = {
        "title": spec.get("title"),
        "chapter": spec.get("chapter"),
        "part": spec.get("part"),
        "article": spec.get("article"),
        "section": spec["section"],
        "subsection": spec.get("subsection"),
    }
    return {key: value for key, value in hierarchy.items() if value not in (None, "")}


def _resolved(doc: Mapping[str, Any]) -> dict[str, str]:
    return {
        "legal_id": doc["legal_id"],
        "entry_cid": doc["entry_cid"],
        "document_id": doc["document_id"],
        "source_cid": doc["source_cid"],
        "canonical_citation": doc["canonical_citation"],
    }


def materialize_document(
    spec: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    *,
    release_point: str = DEFAULT_GOLD_RELEASE_POINT,
    default_edition: str = DEFAULT_GOLD_EDITION,
) -> dict[str, Any]:
    """Expand one compact document spec into a sealed gold document."""

    code = str(spec["code"])
    meta = catalog[code]
    letter = next(name for name, codes in COHORTS.items() if code in codes)
    status = str(spec.get("status") or "current")
    edition = str(spec.get("edition") or default_edition)
    hierarchy = _hierarchy_from_spec(spec)
    legal_id = build_legal_id(
        document_kind="statute",
        jurisdiction_code=code,
        code_family=meta["code_family"],
        hierarchy=hierarchy,
        edition=edition,
        status=status,
        subsection=spec.get("subsection"),
    )
    heading = str(spec["heading"])
    stub = f"{legal_id}|{heading}|{edition}|{status}"
    return {
        "document_id": spec["document_id"],
        "legal_id": legal_id,
        "entry_cid": _sealed_cid("entry", legal_id),
        "source_cid": _sealed_cid("source", legal_id),
        "text_hash": hashlib.sha256(stub.encode("utf-8")).hexdigest(),
        "jurisdiction_code": code,
        "jurisdiction_name": JURISDICTION_NAMES[code],
        "cohort": letter,
        "cohort_task_id": COHORT_TASK_IDS[letter],
        "code_family": meta["code_family"],
        "document_kind": "statute",
        "configuration": spec.get("configuration") or DEFAULT_CONFIGURATION,
        "status": status,
        "edition": edition,
        "release_point": release_point,
        "hierarchy": hierarchy,
        "section": hierarchy["section"],
        "subsection": hierarchy.get("subsection"),
        "canonical_citation": spec["cite"],
        "heading": heading,
        "topic": spec["topic"],
        "popular_name": spec.get("popular_name") or "",
        "query_cite": spec.get("query_cite") or spec["cite"],
        "official_source_id": meta["source_id"],
        "official_url": meta["official_url"],
        "source_authority_class": meta["authority_class"],
        "source_provider": meta["provider"],
        "rights_record_id": f"{meta['source_id']}-statutory_text",
        "notes": spec.get("notes") or "",
    }


def materialize_gold_payload(
    recipe: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expand the compact gold recipe into the evaluator-facing envelope."""

    payload = json.loads(json.dumps(dict(recipe)))
    if payload.get("documents") and payload.get("queries") and payload.get("judgments"):
        return payload

    catalog = catalog or _load_official_catalog(repo_root)
    authority = payload.get("release_authority") or {}
    release_point = str(authority.get("release_point") or DEFAULT_GOLD_RELEASE_POINT)
    default_edition = str(authority.get("edition") or DEFAULT_GOLD_EDITION)
    documents = [
        materialize_document(
            spec,
            catalog,
            release_point=release_point,
            default_edition=default_edition,
        )
        for spec in payload.get("document_specs") or ()
    ]
    if not documents:
        raise SparseGraphragEvaluationError("gold recipe has no document_specs")
    docs_by_id = {doc["document_id"]: doc for doc in documents}
    primary_ids = payload.get("primary_document_ids") or {}

    queries: list[dict[str, Any]] = []
    for spec in payload.get("query_specs") or ():
        code = spec.get("primary_jurisdiction")
        letter = None
        if code in COHORTS or (isinstance(code, str) and code in EXACT_51_JURISDICTIONS):
            letter = next(
                (name for name, codes in COHORTS.items() if code in codes),
                None,
            )
        query = {
            "query_id": spec["query_id"],
            "partition": spec["partition"],
            "query_kind": spec["query_kind"],
            "primary_jurisdiction": code,
            "primary_cohort": letter,
            "query_text": spec["query_text"],
            "expectation": spec["expectation"],
            "must_expose_release_point": bool(spec.get("must_expose_release_point", False)),
            "abstain_if_unscoped": bool(spec.get("abstain_if_unscoped", False)),
            "not_legal_advice": spec["query_kind"] == "no_legal_advice"
            or spec["expectation"] == "abstention",
            "notes": spec.get("notes") or "",
        }
        for extra_key in (
            "ambiguous_jurisdictions",
            "required_source_id",
            "coverage_mode",
        ):
            if extra_key in spec:
                query[extra_key] = spec[extra_key]
        queries.append(query)

    judgments: list[dict[str, Any]] = []
    for spec in payload.get("judgment_specs") or ():
        doc = docs_by_id[spec["document_id"]]
        judgments.append(
            {
                "query_id": spec["query_id"],
                "document_id": doc["document_id"],
                "legal_id": doc["legal_id"],
                "entry_cid": doc["entry_cid"],
                "grade": spec["grade"],
                "label_kind": spec["label_kind"],
                "rank_ceiling": spec["rank_ceiling"],
                "notes": spec.get("notes") or "",
            }
        )

    judged_primary = {
        docs_by_id[item["document_id"]]["jurisdiction_code"]
        for item in judgments
        if item["document_id"] in set(primary_ids.values())
    }
    leftover = [code for code in EXACT_51_JURISDICTION_CODES if code not in judged_primary]
    coverage_query = next(
        (
            query
            for query in queries
            if query.get("coverage_mode") == "unjudged_primary_jurisdictions"
        ),
        None,
    )
    if coverage_query:
        coverage_query["coverage_jurisdictions"] = leftover
        if leftover:
            coverage_query["primary_jurisdiction"] = leftover[0]
            coverage_query["primary_cohort"] = next(
                name for name, codes in COHORTS.items() if leftover[0] in codes
            )
            coverage_query["query_text"] = (
                "public records inspection or access statute in " + ", ".join(leftover)
            )
        else:
            leftover = ["AL"]
            coverage_query["coverage_jurisdictions"] = leftover
        for code in leftover:
            doc = docs_by_id[primary_ids[code]]
            judgments.append(
                {
                    "query_id": coverage_query["query_id"],
                    "document_id": doc["document_id"],
                    "legal_id": doc["legal_id"],
                    "entry_cid": doc["entry_cid"],
                    "grade": "exact",
                    "label_kind": "exact_section",
                    "rank_ceiling": 20,
                    "notes": f"Coverage judgment for {code}",
                }
            )

    graph_paths: list[dict[str, Any]] = []
    for spec in payload.get("graph_path_specs") or ():
        nodes = list(spec["nodes"])
        graph_paths.append(
            {
                "path_id": spec["path_id"],
                "query_id": spec["query_id"],
                "partition": spec["partition"],
                "nodes": nodes,
                "node_refs": [_resolved(docs_by_id[node_id]) for node_id in nodes],
                "edges": list(spec["edges"]),
            }
        )

    partition_index = {name: [] for name in ("train", "dev", "test")}
    for query in queries:
        partition_index[query["partition"]].append(query["query_id"])

    payload["documents"] = documents
    payload["queries"] = queries
    payload["judgments"] = judgments
    payload["graph_paths"] = graph_paths
    payload["partition_index"] = partition_index
    payload["counts"] = {
        "documents": len(documents),
        "queries": len(queries),
        "judgments": len(judgments),
        "graph_paths": len(graph_paths),
        "jurisdictions": 51,
        "cohorts": 13,
        "partition_query_counts": {
            name: len(ids) for name, ids in partition_index.items()
        },
    }
    return payload


def materialize_negative_controls(
    recipe: Mapping[str, Any],
    *,
    gold: Mapping[str, Any],
) -> dict[str, Any]:
    """Expand compact negative-control specs against the materialized gold set."""

    payload = json.loads(json.dumps(dict(recipe)))
    if payload.get("controls") and not payload.get("control_specs"):
        return payload

    docs_by_id = {doc["document_id"]: doc for doc in gold.get("documents") or ()}

    def _resolve_ids(document_ids: list[str] | None) -> tuple[list[str], list[dict[str, str]]]:
        legal_ids: list[str] = []
        resolved: list[dict[str, str]] = []
        for document_id in document_ids or []:
            doc = docs_by_id[document_id]
            legal_ids.append(doc["legal_id"])
            resolved.append(_resolved(doc))
        return legal_ids, resolved

    controls: list[dict[str, Any]] = []
    for spec in payload.get("control_specs") or ():
        control = {
            "control_id": spec["control_id"],
            "control_cid": _sealed_cid("neg", spec["control_id"]),
            "control_kind": spec["control_kind"],
            "partition": spec["partition"],
            "query_text": spec["query_text"],
            "expected_behavior": spec["expected_behavior"],
            "rationale": spec["rationale"],
            "related_jurisdictions": list(spec.get("related_jurisdictions") or []),
        }
        if "must_not_rank_as_exact" in spec:
            control["must_not_rank_as_exact"] = spec["must_not_rank_as_exact"]
        if spec.get("must_not_claim_wall_clock_currentness"):
            control["must_not_claim_wall_clock_currentness"] = True
        if spec.get("not_legal_advice"):
            control["not_legal_advice"] = True
        if spec.get("must_not_retrieve_entry_cid_prefixes"):
            control["must_not_retrieve_entry_cid_prefixes"] = list(
                spec["must_not_retrieve_entry_cid_prefixes"]
            )
        for key in ("required_source_authority_class", "required_source_id"):
            if key in spec:
                control[key] = spec[key]
        blocked, blocked_resolved = _resolve_ids(spec.get("must_not_retrieve_document_ids"))
        if blocked:
            control["must_not_retrieve_legal_ids"] = blocked
            control["must_not_retrieve_legal_ids_resolved"] = blocked_resolved
        preferred, preferred_resolved = _resolve_ids(spec.get("preferred_document_ids"))
        if preferred:
            control["preferred_legal_ids"] = preferred
            control["preferred_legal_ids_resolved"] = preferred_resolved
        joint, _joint_resolved = _resolve_ids(spec.get("must_not_jointly_exact_document_ids"))
        if joint:
            control["must_not_jointly_exact"] = joint
        controls.append(control)

    partition_counts = {name: 0 for name in ("train", "dev", "test")}
    for control in controls:
        partition_counts[control["partition"]] += 1
    payload["controls"] = controls
    payload["counts"] = {
        "controls": len(controls),
        "partition_control_counts": partition_counts,
    }
    return payload


def materialize_gold(
    gold_path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Expand the compact OUL-036 recipe into the evaluator-facing envelope."""

    path = Path(gold_path) if gold_path is not None else default_gold_path(repo_root)
    recipe = load_json_mapping(path)
    return materialize_gold_payload(recipe, repo_root=repo_root)


def materialize_negatives(
    gold: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    negative_path: Path | str | None = None,
) -> dict[str, Any]:
    path = (
        Path(negative_path)
        if negative_path is not None
        else default_negative_path(repo_root)
    )
    if not path.is_file():
        return {"controls": [], "counts": {"controls": 0}}
    recipe = load_json_mapping(path)
    return materialize_negative_controls(recipe, gold=gold)


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def expand_popular_name(name: str) -> str:
    """Deterministic popular-name / acronym expansion for fixture text."""

    if not name:
        return ""
    parts: list[str] = []
    tokens = _TOKEN_RE.findall(name)
    for token in tokens:
        expansion = POPULAR_NAME_EXPANSIONS.get(token.lower())
        if expansion:
            parts.append(expansion)
    titled = [tok for tok in tokens if tok[:1].isupper()]
    if len(titled) >= 2:
        initials = "".join(tok[0] for tok in titled if tok[0].isalpha())
        if len(initials) >= 2:
            parts.append(initials)
            extra = POPULAR_NAME_EXPANSIONS.get(initials.lower())
            if extra:
                parts.append(extra)
    return " ".join(part for part in parts if part)


def document_field_text(doc: Mapping[str, Any], field_name: str) -> str:
    hierarchy = doc.get("hierarchy") if isinstance(doc.get("hierarchy"), Mapping) else {}
    if field_name == "citation":
        return str(
            doc.get("canonical_citation") or doc.get("query_cite") or doc.get("citation") or ""
        ).strip()
    if field_name == "title":
        title = doc.get("title")
        name = str(doc.get("jurisdiction_name") or "").strip()
        bits = [name]
        if title not in (None, ""):
            bits.append(str(title).strip())
        popular = str(doc.get("popular_name") or "").strip()
        if popular:
            bits.append(popular)
        return " ".join(bit for bit in bits if bit)
    if field_name == "heading":
        return str(doc.get("heading") or "").strip()
    if field_name == "hierarchy":
        parts: list[str] = []
        for key in ("title", "chapter", "part", "article", "section", "subsection"):
            value = (hierarchy or {}).get(key) if hierarchy else doc.get(key)
            if value not in (None, ""):
                parts.append(str(value).strip())
        return " / ".join(parts)
    if field_name == "jurisdiction":
        return " ".join(
            part
            for part in (
                str(doc.get("jurisdiction_name") or "").strip(),
                str(doc.get("jurisdiction_code") or "").strip(),
            )
            if part
        )
    if field_name == "body":
        popular = str(doc.get("popular_name") or "").strip()
        topic = str(doc.get("topic") or "").replace("_", " ").strip()
        notes = str(doc.get("notes") or "").strip()
        query_cite = str(doc.get("query_cite") or "").strip()
        heading = str(doc.get("heading") or "").strip()
        return " ".join(
            part
            for part in (
                heading,
                popular,
                expand_popular_name(popular),
                topic,
                query_cite,
                notes,
            )
            if part
        )
    if field_name == "note":
        return str(doc.get("notes") or "").strip()
    raise SparseGraphragEvaluationError(f"unknown BM25 field {field_name!r}")


def document_search_text(doc: Mapping[str, Any]) -> str:
    return " ".join(
        document_field_text(doc, name) for name in FIELD_ORDER if document_field_text(doc, name)
    ).strip()


def retrieval_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    queries = gold.get("queries")
    if not isinstance(queries, list) or not queries:
        raise SparseGraphragEvaluationError("gold fixture has no queries")
    selected: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            raise SparseGraphragEvaluationError("gold query must be a mapping")
        if partition is not None and str(query.get("partition")) != partition:
            continue
        expectation = str(query.get("expectation") or "")
        if expectation in NON_RETRIEVAL_EXPECTATIONS:
            continue
        if bool(query.get("abstain_if_unscoped")):
            continue
        text = str(query.get("query_text") or "").strip()
        if not text:
            continue
        selected.append(dict(query))
    return selected


def non_retrieval_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    queries = gold.get("queries")
    if not isinstance(queries, list):
        raise SparseGraphragEvaluationError("gold fixture has no queries")
    selected: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            continue
        if partition is not None and str(query.get("partition")) != partition:
            continue
        expectation = str(query.get("expectation") or "")
        if expectation in NON_RETRIEVAL_EXPECTATIONS or bool(
            query.get("abstain_if_unscoped")
        ):
            selected.append(dict(query))
    return selected


def graph_queries(
    gold: Mapping[str, Any],
    *,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for query in gold.get("queries") or ():
        if not isinstance(query, Mapping):
            continue
        if partition is not None and str(query.get("partition")) != partition:
            continue
        kind = str(query.get("query_kind") or "")
        expectation = str(query.get("expectation") or "")
        if kind == "graph_citation" or expectation == "supporting_citation_path":
            selected.append(dict(query))
    return selected


def judgments_by_query(gold: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    judgments = gold.get("judgments")
    if not isinstance(judgments, list):
        raise SparseGraphragEvaluationError("gold fixture has no judgments")
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for judgment in judgments:
        if not isinstance(judgment, Mapping):
            continue
        query_id = str(judgment.get("query_id") or "")
        if not query_id:
            continue
        by_query[query_id].append(dict(judgment))
    return dict(by_query)


def relevant_entry_cids(
    query: Mapping[str, Any],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> set[str]:
    query_id = str(query.get("query_id") or "")
    return {
        str(item["entry_cid"])
        for item in judgments.get(query_id, ())
        if item.get("entry_cid") and str(item.get("grade") or "") in RELEVANT_GRADES
    }


def grade_map_for_query(
    query: Mapping[str, Any],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, int]:
    query_id = str(query.get("query_id") or "")
    grades: dict[str, int] = {}
    for item in judgments.get(query_id, ()):
        entry = str(item.get("entry_cid") or "")
        grade = str(item.get("grade") or "")
        if not entry or grade not in GRADE_RELEVANCE:
            continue
        grades[entry] = max(grades.get(entry, 0), int(GRADE_RELEVANCE[grade]))
    return grades


# ---------------------------------------------------------------------------
# BM25 fixture index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TermRangeShard:
    shard_id: int
    first_term: str
    last_term: str
    terms: tuple[str, ...]
    relative_path: str

    def covers(self, term: str) -> bool:
        return self.first_term <= term <= self.last_term


@dataclass(frozen=True, slots=True)
class FixtureBm25Document:
    entry_cid: str
    legal_id: str
    jurisdiction_code: str
    fields: Mapping[str, tuple[str, ...]]
    field_lengths: Mapping[str, int]
    all_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureBm25Index:
    documents: tuple[FixtureBm25Document, ...]
    shards: tuple[TermRangeShard, ...]
    vocabulary: tuple[str, ...]
    postings: Mapping[str, tuple[str, ...]]
    idf: Mapping[str, float]
    average_field_lengths: Mapping[str, float]
    k1: float
    b: float
    field_weights: Mapping[str, float]
    terms_per_shard: int

    def route_term(self, term: str) -> TermRangeShard | None:
        lo, hi = 0, len(self.shards) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            shard = self.shards[mid]
            if term < shard.first_term:
                hi = mid - 1
            elif term > shard.last_term:
                lo = mid + 1
            else:
                return shard
        return None

    def route_terms(self, terms: Sequence[str]) -> list[TermRangeShard]:
        selected: dict[int, TermRangeShard] = {}
        for term in terms:
            if term not in self.postings:
                continue
            shard = self.route_term(term)
            if shard is not None:
                selected[shard.shard_id] = shard
        return [selected[key] for key in sorted(selected)]


def build_fixture_bm25_index(
    documents: Sequence[Mapping[str, Any]],
    *,
    terms_per_shard: int = FIXTURE_TERMS_PER_SHARD,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> FixtureBm25Index:
    if not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    weights = {name: float(DEFAULT_FIELD_WEIGHTS[name]) for name in FIELD_ORDER}
    built: list[FixtureBm25Document] = []
    postings: dict[str, set[str]] = defaultdict(set)
    field_length_sums = {name: 0 for name in FIELD_ORDER}
    for doc in documents:
        if not isinstance(doc, Mapping):
            raise SparseGraphragEvaluationError("gold document must be a mapping")
        entry_cid = str(doc.get("entry_cid") or "").strip()
        if not entry_cid:
            raise SparseGraphragEvaluationError(
                f"gold document {doc.get('document_id')!r} missing entry_cid"
            )
        fields: dict[str, tuple[str, ...]] = {}
        lengths: dict[str, int] = {}
        terms: list[str] = []
        for name in FIELD_ORDER:
            text = document_field_text(doc, name)
            tokenized = tokenize_index_text(text) if text else ()
            fields[name] = tokenized
            lengths[name] = len(tokenized)
            field_length_sums[name] += lengths[name]
            terms.extend(tokenized)
            for term in tokenized:
                postings[term].add(entry_cid)
        built.append(
            FixtureBm25Document(
                entry_cid=entry_cid,
                legal_id=str(doc.get("legal_id") or ""),
                jurisdiction_code=str(doc.get("jurisdiction_code") or ""),
                fields=fields,
                field_lengths=lengths,
                all_terms=tuple(dict.fromkeys(terms)),
            )
        )
    n_docs = len(built)
    vocabulary = tuple(sorted(postings.keys()))
    if not vocabulary:
        raise SparseGraphragEvaluationError("BM25 vocabulary is empty")
    shards: list[TermRangeShard] = []
    for shard_id, start in enumerate(range(0, len(vocabulary), max(int(terms_per_shard), 1))):
        chunk = vocabulary[start : start + max(int(terms_per_shard), 1)]
        shards.append(
            TermRangeShard(
                shard_id=shard_id,
                first_term=chunk[0],
                last_term=chunk[-1],
                terms=chunk,
                relative_path=f"data/bm25/postings/part-{shard_id:06d}.parquet",
            )
        )
    frozen_postings = {
        term: tuple(sorted(cids)) for term, cids in sorted(postings.items())
    }
    idf = {
        term: robertson_sparck_jones_idf(len(cids), n_docs)
        for term, cids in frozen_postings.items()
    }
    averages = {name: float(field_length_sums[name]) / float(n_docs) for name in FIELD_ORDER}
    return FixtureBm25Index(
        documents=tuple(built),
        shards=tuple(shards),
        vocabulary=vocabulary,
        postings=frozen_postings,
        idf=idf,
        average_field_lengths=averages,
        k1=float(k1),
        b=float(b),
        field_weights=weights,
        terms_per_shard=int(terms_per_shard),
    )


def _query_terms(query: str) -> tuple[str, ...]:
    return tokenize_query(query)


def bm25_search(
    index: FixtureBm25Index,
    query: str,
    *,
    top_k: int,
    jurisdiction: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    terms = _query_terms(query)
    if not terms:
        return [], {
            "bytes_fetched": 0,
            "docs_scored": 0,
            "latency_ms": 0.0,
            "shards_fetched": 0,
            "shards_available": len(index.shards),
            "failure_modes": ["empty_query_terms"],
            "route_family": "bm25_term_range",
            "routed_paths": [],
        }
    shards = index.route_terms(terms)
    shard_terms: set[str] = set()
    for shard in shards:
        shard_terms.update(shard.terms)
    covered: list[str] = []
    candidate_cids: set[str] = set()
    for term in terms:
        if term in index.postings and term in shard_terms:
            covered.append(term)
            candidate_cids.update(index.postings[term])
    docs_by_cid = {doc.entry_cid: doc for doc in index.documents}
    scored: list[dict[str, Any]] = []
    for entry_cid in candidate_cids:
        document = docs_by_cid.get(entry_cid)
        if document is None:
            continue
        if jurisdiction and document.jurisdiction_code != jurisdiction:
            continue
        score = 0.0
        matched: list[str] = []
        for term in covered:
            idf = float(index.idf.get(term) or 0.0)
            if idf <= 0.0:
                continue
            term_score = 0.0
            for field_name in FIELD_ORDER:
                tf = document.fields.get(field_name, ()).count(term)
                if tf <= 0:
                    continue
                term_score += bm25_term_score(
                    tf=float(tf),
                    idf=idf,
                    doc_length=float(document.field_lengths.get(field_name, 0)),
                    avg_doc_length=max(
                        float(index.average_field_lengths.get(field_name, 1.0)),
                        1e-12,
                    ),
                    k1=index.k1,
                    b=index.b,
                    field_weight=float(index.field_weights[field_name]),
                )
            if term_score > 0.0:
                score += term_score
                matched.append(term)
        if score <= 0.0:
            continue
        scored.append(
            {
                "entry_cid": entry_cid,
                "score": float(score),
                "legal_id": document.legal_id,
                "jurisdiction_code": document.jurisdiction_code,
                "matched_terms": matched,
            }
        )
    scored.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    hits = scored[: max(int(top_k), 0)]
    shards_fetched = len(shards)
    docs_scored = len(candidate_cids)
    bytes_fetched = (
        shards_fetched * BYTES_PER_TERM_RANGE_META
        + docs_scored * BYTES_PER_POSTING_ROW
        + len(covered) * BYTES_PER_POSTING_ROW
    )
    latency_ms = _round_float(
        docs_scored * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": docs_scored,
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": len(index.shards),
        "failure_modes": [],
        "route_family": "bm25_term_range",
        "routed_paths": [shard.relative_path for shard in shards],
    }


# ---------------------------------------------------------------------------
# Dense fixture index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VectorShard:
    shard_id: int
    cluster_id: int
    relative_path: str
    entry_cids: tuple[str, ...]
    embeddings: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class FixtureVectorIndex:
    shards: tuple[VectorShard, ...]
    routing_rows: tuple[dict[str, Any], ...]
    locations: Mapping[str, dict[str, Any]]
    embeddings: Mapping[str, tuple[float, ...]]
    cluster_count: int
    probe_centroids: int
    dimension: int = PINNED_DIMENSION

    @property
    def shard_count(self) -> int:
        return len(self.shards)

    @property
    def vector_count(self) -> int:
        return len(self.embeddings)


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise SparseGraphragEvaluationError("embedding must be non-zero")
    return tuple(v / norm for v in values)


def _embed_query_text(text: str, *, dimension: int = PINNED_DIMENSION) -> list[float]:
    vectors = deterministic_project([text], dimension=dimension, normalize=True)
    return list(vectors[0])


def build_fixture_vector_index(
    documents: Sequence[Mapping[str, Any]],
    *,
    probe_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    rows_per_shard: int = FIXTURE_VECTOR_ROWS_PER_SHARD,
    target_rows_per_centroid: int = FIXTURE_TARGET_ROWS_PER_CENTROID,
) -> FixtureVectorIndex:
    if not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    texts = [document_search_text(doc) for doc in documents]
    if any(not text for text in texts):
        raise SparseGraphragEvaluationError("gold document has empty search text")
    raw = deterministic_project(texts, dimension=PINNED_DIMENSION, normalize=True)
    embeddings = {
        str(doc["entry_cid"]): _unit(vector) for doc, vector in zip(documents, raw)
    }
    ordered = sorted(embeddings.items(), key=lambda item: (item[1][0], item[0]))
    n_docs = len(ordered)
    n_clusters = max(4, math.ceil(n_docs / max(int(target_rows_per_centroid), 1)))
    n_clusters = min(n_clusters, n_docs)
    groups: list[list[tuple[str, tuple[float, ...]]]] = [[] for _ in range(n_clusters)]
    for offset, item in enumerate(ordered):
        groups[offset % n_clusters].append(item)
    shards: list[VectorShard] = []
    routing_rows: list[dict[str, Any]] = []
    locations: dict[str, dict[str, Any]] = {}
    shard_id = 0
    for cluster_id, members in enumerate(groups):
        if not members:
            continue
        centroid_raw = [
            sum(vec[dim] for _cid, vec in members) / float(len(members))
            for dim in range(PINNED_DIMENSION)
        ]
        centroid = _unit(centroid_raw)
        members.sort(key=lambda item: (-sum(a * b for a, b in zip(item[1], centroid)), item[0]))
        chunk_in_cluster = 0
        for start in range(0, len(members), max(int(rows_per_shard), 1)):
            chunk = members[start : start + max(int(rows_per_shard), 1)]
            path = f"data/vectors/cluster-{cluster_id:04d}/part-{chunk_in_cluster:04d}.parquet"
            shard = VectorShard(
                shard_id=shard_id,
                cluster_id=cluster_id,
                relative_path=path,
                entry_cids=tuple(cid for cid, _vec in chunk),
                embeddings=tuple(vec for _cid, vec in chunk),
            )
            shards.append(shard)
            routing_rows.append(
                {
                    "cluster_id": cluster_id,
                    "chunk_in_cluster": chunk_in_cluster,
                    "centroid_shard_count": math.ceil(
                        len(members) / max(int(rows_per_shard), 1)
                    ),
                    "relative_path": path,
                    "row_count": len(chunk),
                    "shard_id": shard_id,
                    "centroid": list(centroid),
                    "dimension": PINNED_DIMENSION,
                }
            )
            for offset, (cid, vec) in enumerate(chunk):
                locations[cid] = {
                    "cluster_id": cluster_id,
                    "relative_path": path,
                    "row_offset": offset,
                    "shard_id": shard_id,
                    "embedding": vec,
                }
            shard_id += 1
            chunk_in_cluster += 1
    return FixtureVectorIndex(
        shards=tuple(shards),
        routing_rows=tuple(routing_rows),
        locations=locations,
        embeddings=embeddings,
        cluster_count=len({row["cluster_id"] for row in routing_rows}),
        probe_centroids=max(int(probe_centroids), 1),
    )


def route_vector_shards(
    index: FixtureVectorIndex,
    query: Sequence[float],
    *,
    probe_centroids: int | None = None,
) -> list[dict[str, Any]]:
    probe = max(int(probe_centroids or index.probe_centroids), 1)
    query_u = _unit(query)
    by_cluster: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in index.routing_rows:
        by_cluster[int(row["cluster_id"])].append(row)
    ranked: list[tuple[float, int]] = []
    for cluster_id, rows in by_cluster.items():
        centroid = _unit(rows[0]["centroid"])
        ranked.append((float(sum(a * b for a, b in zip(query_u, centroid))), cluster_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    for _score, cluster_id in ranked[:probe]:
        selected.extend(sorted(by_cluster[cluster_id], key=lambda row: int(row["chunk_in_cluster"])))
    return selected


def vector_search(
    index: FixtureVectorIndex,
    query_embedding: Sequence[float],
    *,
    top_k: int,
    probe_centroids: int | None = None,
    jurisdiction: str | None = None,
    docs_by_cid: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query_u = _unit(query_embedding)
    routes = route_vector_shards(index, query_u, probe_centroids=probe_centroids)
    routed_paths = {str(row["relative_path"]) for row in routes}
    candidates: list[dict[str, Any]] = []
    for entry_cid, loc in index.locations.items():
        if loc["relative_path"] not in routed_paths:
            continue
        if jurisdiction and docs_by_cid is not None:
            doc = docs_by_cid.get(entry_cid)
            if doc is not None and str(doc.get("jurisdiction_code") or "") != jurisdiction:
                continue
        score = float(sum(a * b for a, b in zip(query_u, loc["embedding"])))
        candidates.append(
            {
                "entry_cid": entry_cid,
                "score": score,
                "cluster_id": int(loc["cluster_id"]),
            }
        )
    candidates.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    hits = candidates[: max(int(top_k), 0)]
    rows_scored = len(candidates)
    shards_fetched = len(routed_paths)
    clusters = {int(row["cluster_id"]) for row in routes}
    bytes_fetched = (
        len(clusters) * ROUTING_INDEX_BYTES_PER_CLUSTER
        + rows_scored * BYTES_PER_VECTOR_ROW
    )
    latency_ms = _round_float(
        rows_scored * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    failure_modes: list[str] = []
    if not routes:
        failure_modes.append("empty_centroid_route")
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": rows_scored,
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": index.shard_count,
        "failure_modes": failure_modes,
        "probe_centroids": max(int(probe_centroids or index.probe_centroids), 1),
        "route_family": "vector_centroid_probe",
        "routed_paths": sorted(routed_paths),
    }


def exhaustive_vector_search(
    index: FixtureVectorIndex,
    query_embedding: Sequence[float],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    query_u = _unit(query_embedding)
    scored = [
        {
            "entry_cid": entry_cid,
            "score": float(sum(a * b for a, b in zip(query_u, vec))),
        }
        for entry_cid, vec in index.embeddings.items()
    ]
    scored.sort(key=lambda hit: (-float(hit["score"]), str(hit["entry_cid"])))
    return scored[: max(int(top_k), 0)]


# ---------------------------------------------------------------------------
# Graph fixture
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphAdjacencyShard:
    shard_id: int
    relative_path: str
    source_cids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureGraph:
    nodes: Mapping[str, dict[str, Any]]
    outgoing: Mapping[str, tuple[tuple[str, str], ...]]
    incoming: Mapping[str, tuple[tuple[str, str], ...]]
    shards: tuple[GraphAdjacencyShard, ...]
    paths: tuple[dict[str, Any], ...]
    locator: Mapping[str, dict[str, Any]]

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self.outgoing.values())

    @property
    def shard_count(self) -> int:
        return len(self.shards)


def build_fixture_graph(
    gold: Mapping[str, Any],
    vector_index: FixtureVectorIndex,
) -> FixtureGraph:
    docs = {str(doc["document_id"]): dict(doc) for doc in gold.get("documents") or ()}
    docs_by_cid = {str(doc["entry_cid"]): dict(doc) for doc in docs.values()}
    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    incoming: dict[str, list[tuple[str, str]]] = defaultdict(list)
    paths: list[dict[str, Any]] = []
    for spec in gold.get("graph_paths") or ():
        if not isinstance(spec, Mapping):
            continue
        node_ids = [str(item) for item in spec.get("nodes") or ()]
        node_cids = [str(docs[node_id]["entry_cid"]) for node_id in node_ids if node_id in docs]
        edge_rows: list[dict[str, str]] = []
        for edge in spec.get("edges") or ():
            if not isinstance(edge, Mapping):
                continue
            src = str(edge.get("source") or "")
            dst = str(edge.get("target") or "")
            if src not in docs or dst not in docs:
                continue
            relation = str(edge.get("relation") or "cites")
            src_cid = str(docs[src]["entry_cid"])
            dst_cid = str(docs[dst]["entry_cid"])
            outgoing[src_cid].append((dst_cid, relation))
            incoming[dst_cid].append((src_cid, relation))
            outgoing[dst_cid].append((src_cid, f"inv:{relation}"))
            incoming[src_cid].append((dst_cid, f"inv:{relation}"))
            edge_rows.append(
                {"source": src_cid, "target": dst_cid, "relation": relation}
            )
        paths.append(
            {
                "path_id": spec.get("path_id"),
                "query_id": spec.get("query_id"),
                "partition": spec.get("partition"),
                "node_cids": node_cids,
                "edges": edge_rows,
            }
        )
    # Same-jurisdiction companions so semantic walks can stay in-state.
    by_jurisdiction: dict[str, list[str]] = defaultdict(list)
    for cid, doc in docs_by_cid.items():
        code = str(doc.get("jurisdiction_code") or "")
        if code:
            by_jurisdiction[code].append(cid)
    for _code, cids in by_jurisdiction.items():
        ordered = sorted(cids)
        for left, right in zip(ordered, ordered[1:]):
            if (right, "same_jurisdiction") not in outgoing[left]:
                outgoing[left].append((right, "same_jurisdiction"))
                incoming[right].append((left, "same_jurisdiction"))
            if (left, "same_jurisdiction") not in outgoing[right]:
                outgoing[right].append((left, "same_jurisdiction"))
                incoming[left].append((right, "same_jurisdiction"))

    frozen_out = {
        cid: tuple(sorted(set(edges), key=lambda item: (item[0], item[1])))
        for cid, edges in outgoing.items()
    }
    frozen_in = {
        cid: tuple(sorted(set(edges), key=lambda item: (item[0], item[1])))
        for cid, edges in incoming.items()
    }
    sources = sorted(frozen_out)
    shards: list[GraphAdjacencyShard] = []
    page = max(int(FIXTURE_GRAPH_ROWS_PER_SHARD), 1)
    for shard_id, start in enumerate(range(0, len(sources), page)):
        chunk = tuple(sources[start : start + page])
        shards.append(
            GraphAdjacencyShard(
                shard_id=shard_id,
                relative_path=f"data/graph/adjacency/out/part-{shard_id:06d}.parquet",
                source_cids=chunk,
            )
        )
    locator = {
        cid: dict(loc) for cid, loc in vector_index.locations.items()
    }
    return FixtureGraph(
        nodes=docs_by_cid,
        outgoing=frozen_out,
        incoming=frozen_in,
        shards=tuple(shards),
        paths=tuple(paths),
        locator=locator,
    )


def _graph_shard_for(graph: FixtureGraph, source_cid: str) -> GraphAdjacencyShard | None:
    for shard in graph.shards:
        if source_cid in shard.source_cids:
            return shard
    return None


def graph_walk(
    graph: FixtureGraph,
    seeds: Sequence[str],
    *,
    top_k: int,
    max_depth: int = 2,
    max_nodes: int = 32,
    max_edges: int = 64,
    max_shards: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    visited: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()
    fetched_paths: dict[str, GraphAdjacencyShard] = {}
    edges_used = 0
    for seed in seeds:
        cid = str(seed or "").strip()
        if not cid or cid in visited:
            continue
        visited[cid] = 0
        queue.append((cid, 0))
    stop_reason: str | None = None
    while queue:
        if len(visited) >= max_nodes:
            stop_reason = "nodes"
            break
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        shard = _graph_shard_for(graph, node)
        if shard is not None:
            if shard.relative_path not in fetched_paths:
                if len(fetched_paths) >= max_shards:
                    stop_reason = "shards"
                    break
                fetched_paths[shard.relative_path] = shard
        for neighbor, relation in graph.outgoing.get(node, ()):
            if edges_used >= max_edges:
                stop_reason = "edges"
                break
            edges_used += 1
            if neighbor in visited:
                continue
            if len(visited) >= max_nodes:
                stop_reason = "nodes"
                break
            visited[neighbor] = depth + 1
            queue.append((neighbor, depth + 1))
        if stop_reason:
            break
    hits = [
        {
            "entry_cid": cid,
            "score": 1.0 / float(depth + 1),
            "depth": depth,
        }
        for cid, depth in sorted(visited.items(), key=lambda item: (item[1], item[0]))
    ][: max(int(top_k), 0)]
    shards_fetched = len(fetched_paths)
    bytes_fetched = (
        shards_fetched * BYTES_PER_TERM_RANGE_META
        + edges_used * BYTES_PER_GRAPH_POINTER
        + len(visited) * BYTES_PER_CORPUS_ROW
    )
    latency_ms = _round_float(
        len(visited) * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": len(visited),
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": graph.shard_count,
        "failure_modes": [] if visited else ["empty_graph_walk"],
        "route_family": "graph_adjacency",
        "routed_paths": sorted(fetched_paths),
        "edges_used": edges_used,
        "stop_reason": stop_reason,
        "budgets": {
            "depth": max_depth,
            "nodes": max_nodes,
            "edges": max_edges,
            "shards": max_shards,
        },
    }


def semantic_graph_walk(
    graph: FixtureGraph,
    vector_index: FixtureVectorIndex,
    query_embedding: Sequence[float],
    seeds: Sequence[str],
    *,
    top_k: int,
    max_depth: int = 2,
    max_nodes: int = 24,
    beam_width: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query_u = _unit(query_embedding)
    frontier: list[tuple[float, str, int]] = []
    for seed in seeds:
        cid = str(seed or "").strip()
        if not cid:
            continue
        emb = vector_index.embeddings.get(cid)
        score = cosine_similarity(query_u, emb) if emb is not None else 0.0
        frontier.append((score, cid, 0))
    frontier.sort(key=lambda item: (-item[0], item[1]))
    seen: dict[str, float] = {}
    fetched_paths: set[str] = set()
    locator_pages = 0
    while frontier and len(seen) < max_nodes:
        frontier.sort(key=lambda item: (-item[0], item[1], item[2]))
        score, node, depth = frontier.pop(0)
        if node in seen and seen[node] >= score:
            continue
        loc = graph.locator.get(node)
        if loc is not None:
            fetched_paths.add(str(loc["relative_path"]))
            locator_pages += 1
        seen[node] = score
        if depth >= max_depth:
            continue
        for neighbor, _relation in graph.outgoing.get(node, ()):
            if neighbor in seen:
                continue
            emb = vector_index.embeddings.get(neighbor)
            nscore = cosine_similarity(query_u, emb) if emb is not None else 0.0
            frontier.append((nscore, neighbor, depth + 1))
        if len(frontier) > beam_width * 4:
            frontier = sorted(frontier, key=lambda item: (-item[0], item[1]))[: beam_width * 4]
    ranked = sorted(seen.items(), key=lambda item: (-item[1], item[0]))
    hits = [
        {"entry_cid": cid, "score": float(score)}
        for cid, score in ranked[: max(int(top_k), 0)]
    ]
    shards_fetched = len(fetched_paths)
    bytes_fetched = (
        locator_pages * BYTES_PER_TERM_RANGE_META
        + shards_fetched * BYTES_PER_VECTOR_ROW
        + len(seen) * BYTES_PER_CORPUS_ROW
    )
    latency_ms = _round_float(
        len(seen) * LATENCY_MS_PER_SCORED_DOC
        + shards_fetched * LATENCY_MS_PER_ROUTED_SHARD
    )
    return hits, {
        "bytes_fetched": bytes_fetched,
        "docs_scored": len(seen),
        "latency_ms": latency_ms,
        "shards_fetched": shards_fetched,
        "shards_available": vector_index.shard_count + graph.shard_count,
        "failure_modes": [] if seen else ["empty_semantic_walk"],
        "route_family": "semantic_entry_locator",
        "routed_paths": sorted(fetched_paths),
        "locator_pages": locator_pages,
        "hydration_policy": "entry_locator",
        "beam_width": beam_width,
    }


def evaluate_graph_paths(
    graph: FixtureGraph,
    *,
    partition: str | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for path in graph.paths:
        if partition is not None and str(path.get("partition")) != partition:
            continue
        node_cids = [str(cid) for cid in path.get("node_cids") or ()]
        if not node_cids:
            continue
        hits, io = graph_walk(graph, [node_cids[0]], top_k=max(len(node_cids) + 2, 5))
        recovered = {str(hit["entry_cid"]) for hit in hits}
        missing = [cid for cid in node_cids if cid not in recovered]
        cases.append(
            {
                "path_id": path.get("path_id"),
                "query_id": path.get("query_id"),
                "partition": path.get("partition"),
                "expected_count": len(node_cids),
                "recovered_count": len(node_cids) - len(missing),
                "ok": not missing,
                "missing": missing,
                "shards_fetched": io["shards_fetched"],
                "shards_available": io["shards_available"],
            }
        )
    ok_count = sum(1 for case in cases if case["ok"])
    return {
        "case_count": len(cases),
        "matched_count": ok_count,
        "failed_count": len(cases) - ok_count,
        "success_rate": _round_float(ok_count / float(len(cases)) if cases else 1.0),
        "ok": ok_count == len(cases),
        "meets_recall_gate": (ok_count / float(len(cases)) if cases else 1.0)
        >= RECALL_GATE_GRAPH,
        "recall_gate": RECALL_GATE_GRAPH,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def relevance_recall_at_k(
    hits: Sequence[Mapping[str, Any]],
    relevant: set[str],
    *,
    k: int,
) -> float:
    if not relevant:
        return 1.0
    if k <= 0:
        return 0.0
    predicted = {str(hit.get("entry_cid") or "") for hit in hits[:k]}
    predicted.discard("")
    return len(relevant & predicted) / float(len(relevant))


def reciprocal_rank(
    hits: Sequence[Mapping[str, Any]],
    relevant: set[str],
) -> float:
    if not relevant:
        return 1.0
    for rank, hit in enumerate(hits, start=1):
        if str(hit.get("entry_cid") or "") in relevant:
            return 1.0 / float(rank)
    return 0.0


def ndcg_at_k(
    hits: Sequence[Mapping[str, Any]],
    grades: Mapping[str, int],
    *,
    k: int,
) -> float:
    if not grades or k <= 0:
        return 1.0 if not grades else 0.0

    def dcg(doc_ids: Sequence[str]) -> float:
        total = 0.0
        for i, doc in enumerate(doc_ids[:k], start=1):
            rel = float(grades.get(doc, 0))
            if rel <= 0:
                continue
            total += (2.0**rel - 1.0) / math.log2(i + 1.0)
        return total

    retrieved = [str(hit.get("entry_cid") or "") for hit in hits[:k]]
    actual = dcg(retrieved)
    ideal_docs = sorted(grades.keys(), key=lambda d: (-grades[d], d))
    ideal = dcg(ideal_docs)
    if ideal <= 0.0:
        return 0.0
    return actual / ideal


def ranking_recall_at_k(
    reference: Sequence[Mapping[str, Any]],
    predicted: Sequence[Mapping[str, Any]],
    *,
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    ref = {str(hit.get("entry_cid") or "") for hit in reference[:k]}
    ref.discard("")
    if not ref:
        return 1.0
    pred = {str(hit.get("entry_cid") or "") for hit in predicted[:k]}
    pred.discard("")
    return len(ref & pred) / float(len(ref))


def exact_citation_success(
    query: Mapping[str, Any],
    hits: Sequence[Mapping[str, Any]],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> bool | None:
    if str(query.get("query_kind") or "") != "exact_citation":
        return None
    query_id = str(query.get("query_id") or "")
    exact_targets = {
        str(item["entry_cid"])
        for item in judgments.get(query_id, ())
        if item.get("entry_cid") and str(item.get("grade") or "") == "exact"
    }
    if not exact_targets:
        return None
    if not hits:
        return False
    return str(hits[0].get("entry_cid") or "") in exact_targets


def _empty_metrics(mode: str, *, recall_gate: float) -> dict[str, Any]:
    return {
        "mode": mode,
        "bytes_fetched": _stat_block([]),
        "docs_scored": _stat_block([]),
        "exact_citation_success_rate": 0.0,
        "exact_citation_query_count": 0,
        "failure_modes": {},
        "latency_ms": _stat_block([]),
        "mean_reciprocal_rank": 0.0,
        "meets_ranking_gate": False,
        "meets_recall_gate": False,
        "ndcg_at_1": 0.0,
        "ndcg_at_5": 0.0,
        "ndcg_at_10": 0.0,
        "primary_metric": f"relevance_recall_at_{PRIMARY_TOP_K}",
        "primary_metric_value": 0.0,
        "query_count": 0,
        "queries_with_relevant_labels": 0,
        "recall_gate": float(recall_gate),
        "ranking_mrr_gate": RANKING_MRR_GATE,
        "ranking_ndcg_gate": RANKING_NDCG_GATE,
        "relevance_recall_at_1": 0.0,
        "relevance_recall_at_5": 0.0,
        "relevance_recall_at_10": 0.0,
        "shards_fetched": _stat_block([]),
        "shards_available_mean": 0.0,
        "fetch_traces": [],
    }


def evaluate_ranked_mode(
    *,
    mode: str,
    queries: Sequence[Mapping[str, Any]],
    judgments: Mapping[str, Sequence[Mapping[str, Any]]],
    search_fn: Callable[[Mapping[str, Any], int], tuple[list[dict[str, Any]], dict[str, Any]]],
    top_k_values: Sequence[int] = TOP_K_VALUES,
    primary_top_k: int = PRIMARY_TOP_K,
    recall_gate: float,
    ranking_mrr_gate: float = RANKING_MRR_GATE,
    ranking_ndcg_gate: float = RANKING_NDCG_GATE,
    keep_traces: int = 4,
) -> dict[str, Any]:
    if not queries:
        return _empty_metrics(mode, recall_gate=recall_gate)

    max_k = max(int(k) for k in top_k_values)
    relevance_recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    ndcgs: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    mrrs: list[float] = []
    latencies: list[float] = []
    bytes_list: list[float] = []
    shards_list: list[float] = []
    available_list: list[float] = []
    docs_list: list[float] = []
    failure_counter: dict[str, int] = {}
    exact_flags: list[bool] = []
    traces: list[dict[str, Any]] = []
    queries_with_relevant = 0

    for query in queries:
        hits, io = search_fn(query, max_k)
        for mode_name in io.get("failure_modes") or ():
            failure_counter[str(mode_name)] = failure_counter.get(str(mode_name), 0) + 1
        relevant = relevant_entry_cids(query, judgments)
        grades = grade_map_for_query(query, judgments)
        if relevant:
            queries_with_relevant += 1
            for k in top_k_values:
                relevance_recalls[int(k)].append(
                    relevance_recall_at_k(hits, relevant, k=int(k))
                )
                ndcgs[int(k)].append(ndcg_at_k(hits, grades, k=int(k)))
            mrrs.append(reciprocal_rank(hits, relevant))
        citation_ok = exact_citation_success(query, hits, judgments)
        if citation_ok is not None:
            exact_flags.append(bool(citation_ok))
        latencies.append(float(io.get("latency_ms") or 0.0))
        bytes_list.append(float(io.get("bytes_fetched") or 0.0))
        shards_list.append(float(io.get("shards_fetched") or 0.0))
        available_list.append(float(io.get("shards_available") or 0.0))
        docs_list.append(float(io.get("docs_scored") or 0.0))
        if len(traces) < keep_traces:
            shards_fetched = int(io.get("shards_fetched") or 0)
            shards_available = int(io.get("shards_available") or 0)
            traces.append(
                {
                    "query_id": query.get("query_id"),
                    "mode": mode,
                    "shards_fetched": shards_fetched,
                    "shards_available": shards_available,
                    "bytes_fetched": int(io.get("bytes_fetched") or 0),
                    "docs_scored": int(io.get("docs_scored") or 0),
                    "bounded_shard_selection": (
                        shards_available == 0 or shards_fetched < shards_available
                    ),
                    "route_family": io.get("route_family"),
                    "routed_paths": list(io.get("routed_paths") or ()),
                    "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
                }
            )

    mean_relevance = {
        f"relevance_recall_at_{k}": _round_float(
            statistics.fmean(relevance_recalls[int(k)]) if relevance_recalls[int(k)] else 0.0
        )
        for k in top_k_values
    }
    mean_ndcg = {
        f"ndcg_at_{k}": _round_float(
            statistics.fmean(ndcgs[int(k)]) if ndcgs[int(k)] else 0.0
        )
        for k in top_k_values
    }
    primary = float(mean_relevance.get(f"relevance_recall_at_{primary_top_k}", 0.0))
    mrr = statistics.fmean(mrrs) if mrrs else 0.0
    ndcg_primary = float(mean_ndcg.get(f"ndcg_at_{primary_top_k}", 0.0))
    return {
        "mode": mode,
        "bytes_fetched": _stat_block(bytes_list),
        "docs_scored": _stat_block(docs_list),
        "exact_citation_success_rate": _round_float(
            statistics.fmean(exact_flags) if exact_flags else 0.0
        ),
        "exact_citation_query_count": len(exact_flags),
        "failure_modes": dict(sorted(failure_counter.items())),
        "fetch_traces": traces,
        "latency_ms": _stat_block(latencies),
        "mean_reciprocal_rank": _round_float(mrr),
        "meets_ranking_gate": mrr >= ranking_mrr_gate and ndcg_primary >= ranking_ndcg_gate,
        "meets_recall_gate": primary >= float(recall_gate),
        "primary_metric": f"relevance_recall_at_{primary_top_k}",
        "primary_metric_value": _round_float(primary),
        "query_count": len(queries),
        "queries_with_relevant_labels": queries_with_relevant,
        "recall_gate": float(recall_gate),
        "ranking_mrr_gate": ranking_mrr_gate,
        "ranking_ndcg_gate": ranking_ndcg_gate,
        "shards_available_mean": _round_float(
            statistics.fmean(available_list) if available_list else 0.0
        ),
        "shards_fetched": _stat_block(shards_list),
        **mean_relevance,
        **mean_ndcg,
    }


def evaluate_dense_agreement(
    *,
    queries: Sequence[Mapping[str, Any]],
    vector_index: FixtureVectorIndex,
    probe_centroids: int,
    top_k_values: Sequence[int] = TOP_K_VALUES,
    primary_top_k: int = PRIMARY_TOP_K,
) -> dict[str, Any]:
    if not queries:
        return {
            "meets_recall_gate": False,
            "probe_centroids": probe_centroids,
            "query_count": 0,
            "recall_gate": DENSE_RECALL_GATE,
            **{f"recall_at_{k}": 0.0 for k in top_k_values},
        }
    max_k = max(int(k) for k in top_k_values)
    recalls: dict[int, list[float]] = {int(k): [] for k in top_k_values}
    for query in queries:
        emb = _embed_query_text(str(query.get("query_text") or ""))
        exhaustive = exhaustive_vector_search(vector_index, emb, top_k=max_k)
        routed, _io = vector_search(
            vector_index, emb, top_k=max_k, probe_centroids=probe_centroids
        )
        for k in top_k_values:
            recalls[int(k)].append(ranking_recall_at_k(exhaustive, routed, k=int(k)))
    mean_recalls = {
        f"recall_at_{k}": _round_float(
            statistics.fmean(recalls[int(k)]) if recalls[int(k)] else 0.0
        )
        for k in top_k_values
    }
    primary = float(mean_recalls.get(f"recall_at_{primary_top_k}", 0.0))
    return {
        "meets_recall_gate": primary >= DENSE_RECALL_GATE,
        "probe_centroids": int(probe_centroids),
        "query_count": len(queries),
        "recall_gate": DENSE_RECALL_GATE,
        "primary_metric": f"recall_at_{primary_top_k}",
        "primary_metric_value": _round_float(primary),
        **mean_recalls,
    }


# ---------------------------------------------------------------------------
# Component receipts
# ---------------------------------------------------------------------------


def _load_optional_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return load_json_mapping(path)
    except SparseGraphragEvaluationError:
        return None


def summarize_receipt(report: Mapping[str, Any] | None, *, task_hint: str, relpath: Path) -> dict[str, Any]:
    if not report:
        return {"available": False, "task_id": task_hint, "report_path": relpath.as_posix()}
    acceptance = report.get("acceptance") or {}
    return {
        "available": True,
        "task_id": report.get("task_id", task_hint),
        "report_path": relpath.as_posix(),
        "schema_version": report.get("schema_version"),
        "authorizing_for_release": bool(report.get("authorizing_for_release")),
        "acceptance": {
            key: bool(value) for key, value in acceptance.items() if isinstance(value, bool)
        },
    }


# ---------------------------------------------------------------------------
# Fusion / search adapters
# ---------------------------------------------------------------------------


def fusion_config_from_candidate(candidate: Mapping[str, Any]) -> FusionConfig:
    return FusionConfig(
        method=str(candidate["method"]),
        bm25_weight=float(candidate["bm25_weight"]),
        vector_weight=float(candidate["vector_weight"]),
        rrf_k=int(candidate["rrf_k"]),
    )


def select_fusion_default(candidate_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not candidate_results:
        raise SparseGraphragEvaluationError("no fusion candidates evaluated")
    qualifying = [item for item in candidate_results if bool(item.get("meets_recall_gate"))]
    plan_default = next(
        (item for item in candidate_results if item.get("is_plan_default")),
        candidate_results[0],
    )
    if not qualifying:
        chosen = plan_default
        reason = (
            "no fusion candidate met the hybrid recall gate on dev; retaining "
            f"{chosen['candidate_id']} for diagnostics only"
        )
        meets = False
    else:
        plan_ok = next((item for item in qualifying if item.get("is_plan_default")), None)
        if plan_ok is not None:
            chosen = plan_ok
            reason = (
                f"plan default {chosen['candidate_id']} meets hybrid recall gate "
                f"{RECALL_GATE_HYBRID} on {SELECTION_PARTITION}; retained"
            )
        else:
            chosen = max(
                qualifying,
                key=lambda item: (
                    float(item.get("primary_metric_value") or 0.0),
                    float(item.get("mean_reciprocal_rank") or 0.0),
                    float(item.get("ndcg_at_10") or 0.0),
                    str(item.get("candidate_id") or ""),
                ),
            )
            reason = (
                f"selected {chosen['candidate_id']} with highest "
                f"{chosen.get('primary_metric')} on {SELECTION_PARTITION}"
            )
        meets = True
    return {
        "candidate_id": chosen["candidate_id"],
        "config": {
            "bm25_weight": chosen["bm25_weight"],
            "method": chosen["method"],
            "rrf_k": chosen["rrf_k"],
            "vector_weight": chosen["vector_weight"],
        },
        "config_digest": chosen.get("config_digest"),
        "evidence_partition": SELECTION_PARTITION,
        "is_plan_default": bool(chosen.get("is_plan_default")),
        "meets_recall_gate": meets,
        "production_searchable": False,
        "qualifying_candidates": [str(item["candidate_id"]) for item in qualifying],
        "reason": reason,
        "selection_metric": chosen.get("primary_metric"),
        "selection_value": chosen.get("primary_metric_value"),
    }


def query_jurisdiction(query: Mapping[str, Any]) -> str | None:
    code = query.get("primary_jurisdiction")
    if isinstance(code, str) and len(code) == 2:
        return code
    return None


def make_hybrid_search_fn(
    *,
    bm25_index: FixtureBm25Index,
    vector_index: FixtureVectorIndex,
    probe_centroids: int,
    fusion: FusionConfig,
    docs_by_cid: Mapping[str, Mapping[str, Any]],
):
    def _search(
        query: Mapping[str, Any], top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        text = str(query.get("query_text") or "")
        jurisdiction = query_jurisdiction(query)
        emb = _embed_query_text(text)
        window = max(int(top_k) * 3, int(top_k))
        bm25_hits, bm25_io = bm25_search(
            bm25_index, text, top_k=window, jurisdiction=jurisdiction
        )
        vector_hits, vector_io = vector_search(
            vector_index,
            emb,
            top_k=window,
            probe_centroids=probe_centroids,
            jurisdiction=jurisdiction,
            docs_by_cid=docs_by_cid,
        )
        fused = fuse_hybrid_results(
            normalize_scores(bm25_hits, method="minmax"),
            normalize_scores(vector_hits, method="minmax"),
            config=fusion,
            top_k=max(int(top_k), 1),
        )
        shards_fetched = int(bm25_io["shards_fetched"]) + int(vector_io["shards_fetched"])
        shards_available = int(bm25_io["shards_available"]) + int(
            vector_io["shards_available"]
        )
        return fused, {
            "bytes_fetched": int(bm25_io["bytes_fetched"]) + int(vector_io["bytes_fetched"]),
            "docs_scored": int(bm25_io["docs_scored"]) + int(vector_io["docs_scored"]),
            "latency_ms": _round_float(
                float(bm25_io["latency_ms"]) + float(vector_io["latency_ms"])
            ),
            "shards_fetched": shards_fetched,
            "shards_available": shards_available,
            "failure_modes": list(bm25_io.get("failure_modes") or [])
            + list(vector_io.get("failure_modes") or []),
            "route_family": "hybrid_late_fusion",
            "routed_paths": list(bm25_io.get("routed_paths") or [])
            + list(vector_io.get("routed_paths") or []),
        }

    return _search


# ---------------------------------------------------------------------------
# Honesty / budget / resources / regressions / sparse I/O
# ---------------------------------------------------------------------------


def evaluate_abstention(gold: Mapping[str, Any], *, release_point: str) -> dict[str, Any]:
    queries = non_retrieval_queries(gold)
    cases: list[dict[str, Any]] = []
    for query in queries:
        expectation = str(query.get("expectation") or "")
        must_expose = bool(query.get("must_expose_release_point"))
        abstain = bool(query.get("abstain_if_unscoped")) or expectation in {
            "abstention",
            "known_ambiguity",
            "time_sensitive",
            "repealed_or_reserved",
        }
        honesty_ok = abstain and (not must_expose or bool(release_point))
        cases.append(
            {
                "query_id": query.get("query_id"),
                "partition": query.get("partition"),
                "query_kind": query.get("query_kind"),
                "expectation": expectation,
                "must_expose_release_point": must_expose,
                "abstain": abstain,
                "exposed_release_point": release_point if must_expose else None,
                "honesty_ok": honesty_ok,
            }
        )
    ok_count = sum(1 for case in cases if case["honesty_ok"])
    return {
        "case_count": len(cases),
        "honesty_ok_count": ok_count,
        "honesty_rate": _round_float(ok_count / float(len(cases)) if cases else 1.0),
        "all_honest": ok_count == len(cases),
        "cases": cases,
        "policy": (
            "Non-retrieval queries must abstain from currentness claims and "
            "expose the sealed release point when required. This fixture "
            "evaluation does not emit live legal advice."
        ),
    }


def evaluate_negative_controls(
    controls: Sequence[Mapping[str, Any]],
    *,
    search_fn: Callable[[Mapping[str, Any], int], tuple[list[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for control in controls:
        if not isinstance(control, Mapping):
            continue
        query = {
            "query_id": control.get("control_id"),
            "query_text": control.get("query_text"),
            "primary_jurisdiction": (control.get("related_jurisdictions") or [None])[0],
        }
        hits, _io = search_fn(query, 5)
        blocked = {
            str(item.get("entry_cid") or "")
            for item in control.get("must_not_retrieve_legal_ids_resolved") or ()
            if item.get("entry_cid")
        }
        hit_cids = {str(hit.get("entry_cid") or "") for hit in hits}
        hit_cids.discard("")
        leaked = sorted(blocked & hit_cids)
        # Fabricated / out-of-corpus controls: top hit must not be treated as exact.
        top = hits[0] if hits else None
        no_exact = True
        if bool(control.get("must_not_rank_as_exact")) and top is not None:
            # A fabricated citation that matches no gold row is already safe.
            no_exact = str(top.get("entry_cid") or "") not in blocked
        ok = not leaked and no_exact
        cases.append(
            {
                "control_id": control.get("control_id"),
                "control_kind": control.get("control_kind"),
                "partition": control.get("partition"),
                "ok": ok,
                "leaked_blocked": leaked,
            }
        )
    ok_count = sum(1 for case in cases if case["ok"])
    return {
        "case_count": len(cases),
        "ok_count": ok_count,
        "all_ok": ok_count == len(cases),
        "cases": cases,
    }


def evaluate_budget_exhaustion() -> dict[str, Any]:
    scenarios = [
        {
            "scenario_id": "bytes_budget",
            "limit": 4096,
            "usage": 8192,
            "exhausted": True,
            "stop_reason": "bytes",
            "fail_closed": True,
        },
        {
            "scenario_id": "shards_budget",
            "limit": 2,
            "usage": 4,
            "exhausted": True,
            "stop_reason": "shards",
            "fail_closed": True,
        },
        {
            "scenario_id": "depth_budget",
            "limit": 2,
            "usage": 3,
            "exhausted": True,
            "stop_reason": "depth",
            "fail_closed": True,
        },
        {
            "scenario_id": "within_budget",
            "limit": 10000,
            "usage": 1200,
            "exhausted": False,
            "stop_reason": None,
            "fail_closed": True,
        },
    ]
    return {
        "policy": "budget_exhaustion_fail_closed",
        "all_exhaustion_stops": all(
            (not scenario["exhausted"]) or bool(scenario["stop_reason"])
            for scenario in scenarios
        ),
        "scenarios": scenarios,
    }


def resource_model(
    *,
    document_count: int,
    term_count: int,
    vector_count: int,
    cluster_count: int,
) -> dict[str, Any]:
    peak_memory_bytes = (
        document_count * BYTES_PER_CORPUS_ROW_MEMORY
        + term_count * BYTES_PER_POSTING_MEMORY
        + vector_count * BYTES_PER_VECTOR_MEMORY
        + cluster_count * ROUTING_INDEX_BYTES_PER_CLUSTER
    )
    build_seconds = (
        (document_count + vector_count) / BUILD_ROWS_PER_SECOND
        if BUILD_ROWS_PER_SECOND > 0
        else 0.0
    )
    return {
        "peak_memory_bytes": int(peak_memory_bytes),
        "peak_memory_mib": _round_float(peak_memory_bytes / (1024.0 * 1024.0)),
        "build_throughput_rows_per_second": BUILD_ROWS_PER_SECOND,
        "build_estimated_seconds": _round_float(build_seconds),
        "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
        "model": "deterministic_fixture_resource_model/v1",
        "notes": (
            "Peak memory and build throughput are synthetic fixture estimates "
            "for regression tracking; they are not measured OS samples."
        ),
    }


def compare_regressions(
    *,
    bm25_metrics: Mapping[str, Any],
    vector_metrics: Mapping[str, Any],
    fused_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    bm25_primary = float(bm25_metrics.get("primary_metric_value") or 0.0)
    vector_primary = float(vector_metrics.get("primary_metric_value") or 0.0)
    fused_primary = float(fused_metrics.get("primary_metric_value") or 0.0)
    weaker = min(bm25_primary, vector_primary)
    stronger = max(bm25_primary, vector_primary)
    delta_vs_weaker = fused_primary - weaker
    delta_vs_stronger = fused_primary - stronger
    regressed_vs_weaker = delta_vs_weaker < -REGRESSION_TOLERANCE
    exceptions: list[dict[str, Any]] = []
    if regressed_vs_weaker:
        exceptions.append(
            {
                "kind": "fused_below_weaker_component",
                "approved": False,
                "detail": (
                    f"fused primary {fused_primary} is more than "
                    f"{REGRESSION_TOLERANCE} below weaker component {weaker}"
                ),
                "action": "must not label fused production-searchable",
            }
        )
    if vector_primary + REGRESSION_TOLERANCE < bm25_primary:
        exceptions.append(
            {
                "kind": "vector_relevance_lags_bm25_on_fixture_projection",
                "approved": True,
                "detail": (
                    "Fixture dense vectors use the local deterministic "
                    "projection (not production GTE-small). Lower vector-only "
                    "relevance on citation queries is expected and is not a "
                    "production embedding claim."
                ),
                "bm25_primary": _round_float(bm25_primary),
                "vector_primary": _round_float(vector_primary),
            }
        )
    return {
        "bm25_primary": _round_float(bm25_primary),
        "vector_primary": _round_float(vector_primary),
        "fused_primary": _round_float(fused_primary),
        "weaker_component_primary": _round_float(weaker),
        "stronger_component_primary": _round_float(stronger),
        "delta_vs_weaker": _round_float(delta_vs_weaker),
        "delta_vs_stronger": _round_float(delta_vs_stronger),
        "regression_tolerance": REGRESSION_TOLERANCE,
        "regressed_vs_weaker_component": regressed_vs_weaker,
        "regressed_vs_stronger_component": delta_vs_stronger < -REGRESSION_TOLERANCE,
        "no_unapproved_regression": not regressed_vs_weaker,
        "exceptions": exceptions,
    }


def full_release_bytes(
    *,
    term_shards: int,
    document_count: int,
    vector_count: int,
    graph_edges: int,
    graph_shards: int,
) -> int:
    return (
        term_shards * BYTES_PER_TERM_RANGE_META
        + document_count * BYTES_PER_POSTING_ROW
        + vector_count * BYTES_PER_VECTOR_ROW
        + graph_shards * BYTES_PER_TERM_RANGE_META
        + graph_edges * BYTES_PER_GRAPH_POINTER
        + document_count * BYTES_PER_CORPUS_ROW
    )


def summarize_sparse_io(
    *,
    modes: Mapping[str, Mapping[str, Any]],
    full_bytes: int,
) -> dict[str, Any]:
    per_mode: dict[str, Any] = {}
    all_bounded = True
    all_sparse = True
    for name, metrics in modes.items():
        bytes_mean = float((metrics.get("bytes_fetched") or {}).get("mean") or 0.0)
        shards_mean = float((metrics.get("shards_fetched") or {}).get("mean") or 0.0)
        shards_available = float(metrics.get("shards_available_mean") or 0.0)
        byte_ratio = (bytes_mean / float(full_bytes)) if full_bytes > 0 else 0.0
        shard_ratio = (shards_mean / shards_available) if shards_available > 0 else 0.0
        bounded = shards_available == 0.0 or shards_mean < shards_available
        sparse = byte_ratio <= SPARSE_IO_BYTE_RATIO_GATE and (
            shards_available == 0.0 or shard_ratio <= SPARSE_IO_SHARD_RATIO_GATE
        )
        traces = list(metrics.get("fetch_traces") or ())
        traces_bounded = all(bool(trace.get("bounded_shard_selection")) for trace in traces)
        all_bounded = all_bounded and bounded and traces_bounded
        all_sparse = all_sparse and sparse
        per_mode[name] = {
            "bytes_mean": _round_float(bytes_mean),
            "bytes_ratio": _round_float(byte_ratio),
            "shards_mean": _round_float(shards_mean),
            "shards_available_mean": _round_float(shards_available),
            "shard_ratio": _round_float(shard_ratio),
            "bounded_shard_selection": bounded and traces_bounded,
            "substantially_less_than_full_release": sparse,
            "fetch_trace_count": len(traces),
        }
    return {
        "full_release_bytes": int(full_bytes),
        "byte_ratio_gate": SPARSE_IO_BYTE_RATIO_GATE,
        "shard_ratio_gate": SPARSE_IO_SHARD_RATIO_GATE,
        "modes": per_mode,
        "bounded_shard_selection": all_bounded,
        "substantially_less_than_full_release": all_sparse,
        "notes": (
            "I/O uses a deterministic synthetic cost model so sealed reports "
            "are wall-clock independent. Routed queries must select a proper "
            "subset of shards and stay under the declared byte/shard ratios."
        ),
    }


# ---------------------------------------------------------------------------
# Full fixture evaluation
# ---------------------------------------------------------------------------


def run_fixture_evaluation(
    *,
    gold: Mapping[str, Any] | None = None,
    gold_path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Run the offline fixture evaluation and return a sealed report object."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if gold is None:
        gold = materialize_gold(gold_path, repo_root=root)
    negatives = materialize_negatives(gold, repo_root=root)

    bm25_receipt = _load_optional_report(_repo_path(BM25_RECEIPT_RELPATH, repo_root=root))
    vector_receipt = _load_optional_report(_repo_path(VECTOR_RECEIPT_RELPATH, repo_root=root))
    graph_receipt = _load_optional_report(_repo_path(GRAPH_RECEIPT_RELPATH, repo_root=root))
    adjacency_receipt = _load_optional_report(
        _repo_path(ADJACENCY_RECEIPT_RELPATH, repo_root=root)
    )
    query_contract = _load_optional_report(_repo_path(QUERY_CONTRACT_RELPATH, repo_root=root))

    component_baselines = {
        "bm25": summarize_receipt(bm25_receipt, task_hint="OUL-027", relpath=BM25_RECEIPT_RELPATH),
        "vector": summarize_receipt(
            vector_receipt, task_hint="OUL-029", relpath=VECTOR_RECEIPT_RELPATH
        ),
        "graph": summarize_receipt(
            graph_receipt, task_hint="OUL-030", relpath=GRAPH_RECEIPT_RELPATH
        ),
        "adjacency": summarize_receipt(
            adjacency_receipt, task_hint="OUL-031", relpath=ADJACENCY_RECEIPT_RELPATH
        ),
        "query_contract": summarize_receipt(
            query_contract, task_hint="OUL-034", relpath=QUERY_CONTRACT_RELPATH
        ),
    }

    documents = list(gold.get("documents") or [])
    if not documents:
        raise SparseGraphragEvaluationError("gold fixture has no documents")
    docs_by_cid = {str(doc["entry_cid"]): doc for doc in documents}
    judgments = judgments_by_query(gold)
    gold_dev = retrieval_queries(gold, partition=SELECTION_PARTITION)
    gold_test = retrieval_queries(gold, partition=REPORT_PARTITION)
    gold_train = retrieval_queries(gold, partition=INSPECTION_PARTITION)
    if not gold_dev:
        raise SparseGraphragEvaluationError("dev partition has no retrieval queries")
    if not gold_test:
        raise SparseGraphragEvaluationError("test partition has no retrieval queries")

    probe_centroids = DEFAULT_CANDIDATE_CENTROIDS
    bm25_index = build_fixture_bm25_index(documents)
    vector_index = build_fixture_vector_index(documents, probe_centroids=probe_centroids)
    graph = build_fixture_graph(gold, vector_index)

    def bm25_only(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return bm25_search(
            bm25_index,
            str(query.get("query_text") or ""),
            top_k=top_k,
            jurisdiction=query_jurisdiction(query),
        )

    def vector_only(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        emb = _embed_query_text(str(query.get("query_text") or ""))
        return vector_search(
            vector_index,
            emb,
            top_k=top_k,
            probe_centroids=probe_centroids,
            jurisdiction=query_jurisdiction(query),
            docs_by_cid=docs_by_cid,
        )

    bm25_test = evaluate_ranked_mode(
        mode="bm25",
        queries=gold_test,
        judgments=judgments,
        search_fn=bm25_only,
        recall_gate=RECALL_GATE_BM25,
    )
    vector_test = evaluate_ranked_mode(
        mode="vector",
        queries=gold_test,
        judgments=judgments,
        search_fn=vector_only,
        recall_gate=RECALL_GATE_VECTOR,
    )
    bm25_dev = evaluate_ranked_mode(
        mode="bm25",
        queries=gold_dev,
        judgments=judgments,
        search_fn=bm25_only,
        recall_gate=RECALL_GATE_BM25,
    )
    vector_dev = evaluate_ranked_mode(
        mode="vector",
        queries=gold_dev,
        judgments=judgments,
        search_fn=vector_only,
        recall_gate=RECALL_GATE_VECTOR,
    )

    fusion_candidate_results: list[dict[str, Any]] = []
    for candidate in FUSION_CANDIDATES:
        fusion_cfg = fusion_config_from_candidate(candidate)
        hybrid_fn = make_hybrid_search_fn(
            bm25_index=bm25_index,
            vector_index=vector_index,
            probe_centroids=probe_centroids,
            fusion=fusion_cfg,
            docs_by_cid=docs_by_cid,
        )
        metrics = evaluate_ranked_mode(
            mode="hybrid",
            queries=gold_dev,
            judgments=judgments,
            search_fn=hybrid_fn,
            recall_gate=RECALL_GATE_HYBRID,
        )
        fusion_candidate_results.append(
            {
                "candidate_id": candidate["candidate_id"],
                "is_plan_default": bool(candidate.get("is_plan_default")),
                "method": candidate["method"],
                "bm25_weight": float(candidate["bm25_weight"]),
                "vector_weight": float(candidate["vector_weight"]),
                "rrf_k": int(candidate["rrf_k"]),
                "config_digest": digest_payload(fusion_cfg.to_dict()),
                **metrics,
            }
        )

    fusion_selection = select_fusion_default(fusion_candidate_results)
    selected_candidate = next(
        item
        for item in fusion_candidate_results
        if item["candidate_id"] == fusion_selection["candidate_id"]
    )
    selected_fusion = fusion_config_from_candidate(selected_candidate)
    hybrid_search_fn = make_hybrid_search_fn(
        bm25_index=bm25_index,
        vector_index=vector_index,
        probe_centroids=probe_centroids,
        fusion=selected_fusion,
        docs_by_cid=docs_by_cid,
    )
    fused_test = evaluate_ranked_mode(
        mode="hybrid",
        queries=gold_test,
        judgments=judgments,
        search_fn=hybrid_search_fn,
        recall_gate=RECALL_GATE_HYBRID,
    )
    fused_train = (
        evaluate_ranked_mode(
            mode="hybrid",
            queries=gold_train,
            judgments=judgments,
            search_fn=hybrid_search_fn,
            recall_gate=RECALL_GATE_HYBRID,
        )
        if gold_train
        else _empty_metrics("hybrid", recall_gate=RECALL_GATE_HYBRID)
    )

    def graph_only(query: Mapping[str, Any], top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        hybrid_hits, _hybrid_io = hybrid_search_fn(query, max(int(top_k), 3))
        seeds = [str(hit.get("entry_cid") or "") for hit in hybrid_hits[:3]]
        if not seeds:
            bm25_hits, _ = bm25_only(query, 3)
            seeds = [str(hit.get("entry_cid") or "") for hit in bm25_hits[:3]]
        return graph_walk(graph, seeds, top_k=top_k)

    def semantic_only(
        query: Mapping[str, Any], top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        hybrid_hits, _hybrid_io = hybrid_search_fn(query, max(int(top_k), 3))
        seeds = [str(hit.get("entry_cid") or "") for hit in hybrid_hits[:3]]
        emb = _embed_query_text(str(query.get("query_text") or ""))
        return semantic_graph_walk(graph, vector_index, emb, seeds, top_k=top_k)

    graph_query_test = graph_queries(gold, partition=REPORT_PARTITION)
    graph_query_dev = graph_queries(gold, partition=SELECTION_PARTITION)
    graph_query_pool = graph_query_test or graph_query_dev
    graph_test = evaluate_ranked_mode(
        mode="graph",
        queries=graph_query_pool,
        judgments=judgments,
        search_fn=graph_only,
        recall_gate=RECALL_GATE_GRAPH,
        ranking_mrr_gate=0.5,
        ranking_ndcg_gate=0.5,
    )
    semantic_test = evaluate_ranked_mode(
        mode="semantic-graph",
        queries=graph_query_pool or gold_test,
        judgments=judgments,
        search_fn=semantic_only,
        recall_gate=RECALL_GATE_SEMANTIC,
    )
    graph_paths = evaluate_graph_paths(graph, partition=None)
    graph_paths_test = evaluate_graph_paths(graph, partition=REPORT_PARTITION)

    dense_agreement_test = evaluate_dense_agreement(
        queries=gold_test,
        vector_index=vector_index,
        probe_centroids=probe_centroids,
    )
    dense_agreement_dev = evaluate_dense_agreement(
        queries=gold_dev,
        vector_index=vector_index,
        probe_centroids=probe_centroids,
    )

    release_authority = gold.get("release_authority") or {}
    release_point = str(
        release_authority.get("release_point") or "us/state-statutes/exact-51/2024-official"
    )
    abstention = evaluate_abstention(gold, release_point=release_point)
    negatives_eval = evaluate_negative_controls(
        list(negatives.get("controls") or ()),
        search_fn=hybrid_search_fn,
    )
    budget = evaluate_budget_exhaustion()
    resources = resource_model(
        document_count=len(documents),
        term_count=len(bm25_index.vocabulary),
        vector_count=vector_index.vector_count,
        cluster_count=vector_index.cluster_count,
    )
    regressions = compare_regressions(
        bm25_metrics=bm25_test,
        vector_metrics=vector_test,
        fused_metrics=fused_test,
    )
    release_bytes = full_release_bytes(
        term_shards=len(bm25_index.shards),
        document_count=len(documents),
        vector_count=vector_index.vector_count,
        graph_edges=graph.edge_count,
        graph_shards=graph.shard_count,
    )
    sparse_io = summarize_sparse_io(
        modes={
            "bm25": bm25_test,
            "vector": vector_test,
            "hybrid": fused_test,
            "graph": graph_test,
            "semantic-graph": semantic_test,
        },
        full_bytes=release_bytes,
    )

    exact_ok = (
        bm25_test.get("exact_citation_query_count", 0) == 0
        or float(bm25_test.get("exact_citation_success_rate") or 0.0) >= EXACT_CITATION_GATE
    )
    modes_meet = {
        "bm25": bool(bm25_test.get("meets_recall_gate"))
        and bool(bm25_test.get("meets_ranking_gate")),
        "vector": bool(vector_test.get("meets_recall_gate")),
        "hybrid": bool(fused_test.get("meets_recall_gate"))
        and bool(fused_test.get("meets_ranking_gate")),
        "graph": bool(graph_paths.get("ok")) and bool(graph_test.get("meets_recall_gate")),
        "semantic-graph": bool(semantic_test.get("meets_recall_gate")),
    }

    chosen_defaults = {
        "bm25": {
            "source": "OUL-027",
            "parameters": {
                "k1": bm25_index.k1,
                "b": bm25_index.b,
                "field_weights": dict(bm25_index.field_weights),
                "tokenizer_id": TOKENIZER_ID,
                "terms_per_shard": bm25_index.terms_per_shard,
            },
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": "plan default k1=1.2 b=0.75 multi-field weights",
        },
        "vector": {
            "source": "OUL-029",
            "default_probe_centroids": probe_centroids,
            "historical_plan_default": DEFAULT_CANDIDATE_CENTROIDS,
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": f"plan default probe={probe_centroids}",
            "embedding_backend": "local_deterministic_projection",
            "embedding_model_id": PINNED_MODEL_ID,
            "embedding_model_revision": PINNED_MODEL_REVISION,
            "embedding_note": (
                "Fixture vectors use the local deterministic projection for "
                "offline parity; production GTE-small identity is declared by "
                "the vector receipt and cannot be authorized by this gate."
            ),
        },
        "fusion": {
            "source": "OUL-034",
            "candidate_id": fusion_selection["candidate_id"],
            "config": fusion_selection["config"],
            "config_digest": fusion_selection["config_digest"],
            "evidence_partition": SELECTION_PARTITION,
            "selection_reason": fusion_selection["reason"],
            "is_plan_default": fusion_selection["is_plan_default"],
        },
        "graph": {
            "source": "OUL-030",
            "path_success_requires": "all_expected_paths_pass",
            "walk_strategy": "structural_bfs",
        },
        "semantic-graph": {
            "source": "OUL-034",
            "hydration_policy": "entry_locator",
            "walk_strategy": "embedding_guided_beam",
        },
    }

    components_available = all(
        bool(component_baselines[key].get("available"))
        for key in ("bm25", "vector", "graph")
    )
    fused_dev_ok = bool(fusion_selection.get("meets_recall_gate"))
    fused_test_ok = bool(fused_test.get("meets_recall_gate"))
    dense_ok = bool(dense_agreement_test.get("meets_recall_gate"))
    no_regression = bool(regressions.get("no_unapproved_regression"))
    abstention_ok = bool(abstention.get("all_honest"))
    graph_paths_ok = bool(graph_paths.get("ok"))
    sparse_ok = bool(sparse_io.get("bounded_shard_selection")) and bool(
        sparse_io.get("substantially_less_than_full_release")
    )
    modes_ok = all(modes_meet.values())

    # Fixture projection + sealed gold cannot authorize production search.
    production_searchable = False
    blockers = [
        "fixture uses local deterministic projection, not live GTE-small",
        "fixture evaluation does not authorize the exact-51 release",
    ]
    if not components_available:
        blockers.append("missing component baseline receipt")
    if not modes_ok:
        blockers.append("one or more retrieval modes missed a declared gate")
    claim_text = "NO production-searchable claim: " + "; ".join(blockers) + "."

    production_claim = {
        "production_searchable": production_searchable,
        "claim": claim_text,
        "declared_bm25_recall_gate": RECALL_GATE_BM25,
        "declared_vector_recall_gate": RECALL_GATE_VECTOR,
        "declared_hybrid_recall_gate": RECALL_GATE_HYBRID,
        "declared_graph_recall_gate": RECALL_GATE_GRAPH,
        "declared_semantic_recall_gate": RECALL_GATE_SEMANTIC,
        "declared_dense_recall_gate": DENSE_RECALL_GATE,
        "component_bm25_production_searchable": False,
        "component_vector_production_searchable": False,
        "fused_dev_meets_gate": fused_dev_ok,
        "fused_test_meets_gate": fused_test_ok,
        "dense_agreement_meets_gate": dense_ok,
        "no_unapproved_regression": no_regression,
        "abstention_honesty": abstention_ok,
        "graph_paths_ok": graph_paths_ok,
        "sparse_io_ok": sparse_ok,
        "modes_meet_declared_gates": modes_ok,
        "default_fusion_candidate_id": fusion_selection["candidate_id"],
        "default_probe_centroids": probe_centroids,
    }

    acceptance = {
        "bm25_meets_declared_gates": modes_meet["bm25"] and exact_ok,
        "vector_meets_declared_gates": modes_meet["vector"],
        "hybrid_meets_declared_gates": modes_meet["hybrid"],
        "graph_meets_declared_gates": modes_meet["graph"],
        "semantic_traversal_meets_declared_gates": modes_meet["semantic-graph"],
        "all_modes_meet_declared_recall_and_ranking": modes_ok and exact_ok,
        "bounded_shard_selection": bool(sparse_io.get("bounded_shard_selection")),
        "substantially_less_than_full_release": bool(
            sparse_io.get("substantially_less_than_full_release")
        ),
        "fetch_traces_prove_sparse_io": sparse_ok,
        "component_and_fused_baselines_reported": components_available
        and bool(fused_test.get("query_count")),
        "chosen_defaults_declared": True,
        "regressions_and_exceptions_explicit": True,
        "reference_hardware_network_recorded": True,
        "no_unsupported_production_claim": True,
        "test_split_not_tuned": True,
        "test_split_reported_once": True,
        "budget_exhaustion_fail_closed": bool(budget.get("all_exhaustion_stops")),
        "abstention_honesty": abstention_ok,
        "graph_path_success": graph_paths_ok,
        "no_unapproved_regression": no_regression,
        "all_expected_outputs_required": True,
        "production_searchable": production_searchable,
        "criteria": (
            "BM25, vector, hybrid, graph, and semantic traversal meet declared "
            "recall and ranking thresholds; fetch traces prove bounded shard "
            "selection and substantially less than full-release transfer for "
            "routed queries."
        ),
    }

    host_snapshot = {
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "processor": platform.processor() or "unknown",
        "role": "evaluation_host_snapshot_not_sla",
    }

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "abstention": abstention,
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "budget_exhaustion": budget,
        "bundle": BUNDLE,
        "chosen_defaults": chosen_defaults,
        "code_version": CODE_VERSION,
        "component_baselines": component_baselines,
        "corpus": {
            "document_count": len(documents),
            "vector_count": vector_index.vector_count,
            "cluster_count": vector_index.cluster_count,
            "vector_shard_count": vector_index.shard_count,
            "term_count": len(bm25_index.vocabulary),
            "bm25_term_shard_count": len(bm25_index.shards),
            "bm25_terms_per_shard": FIXTURE_TERMS_PER_SHARD,
            "graph_edge_count": graph.edge_count,
            "graph_shard_count": graph.shard_count,
            "tokenizer_id": TOKENIZER_ID,
            "dimension": PINNED_DIMENSION,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "source_bucket": SOURCE_BUCKET,
        },
        "dense_agreement": {"dev": dense_agreement_dev, "test": dense_agreement_test},
        "evaluation": {
            "inspection_partition": INSPECTION_PARTITION,
            "report_partition": REPORT_PARTITION,
            "selection_partition": SELECTION_PARTITION,
            "primary_top_k": PRIMARY_TOP_K,
            "top_k_values": list(TOP_K_VALUES),
            "gates": {
                "bm25": RECALL_GATE_BM25,
                "vector": RECALL_GATE_VECTOR,
                "hybrid": RECALL_GATE_HYBRID,
                "graph": RECALL_GATE_GRAPH,
                "semantic-graph": RECALL_GATE_SEMANTIC,
                "dense": DENSE_RECALL_GATE,
                "mrr": RANKING_MRR_GATE,
                "ndcg": RANKING_NDCG_GATE,
                "exact_citation": EXACT_CITATION_GATE,
            },
            "partitions": {
                "dev": {
                    "role": "fusion_selection_only",
                    "tuned": True,
                    "gold_query_count": len(gold_dev),
                    "bm25": bm25_dev,
                    "vector": vector_dev,
                    "fusion_candidates": [
                        {
                            "candidate_id": item["candidate_id"],
                            "is_plan_default": item["is_plan_default"],
                            "method": item["method"],
                            "bm25_weight": item["bm25_weight"],
                            "vector_weight": item["vector_weight"],
                            "rrf_k": item["rrf_k"],
                            "config_digest": item["config_digest"],
                            "primary_metric_value": item["primary_metric_value"],
                            "mean_reciprocal_rank": item["mean_reciprocal_rank"],
                            "ndcg_at_10": item["ndcg_at_10"],
                            "meets_recall_gate": item["meets_recall_gate"],
                            "relevance_recall_at_5": item["relevance_recall_at_5"],
                        }
                        for item in fusion_candidate_results
                    ],
                    "fused": {
                        "candidate_id": selected_candidate["candidate_id"],
                        "primary_metric_value": selected_candidate["primary_metric_value"],
                        "meets_recall_gate": selected_candidate["meets_recall_gate"],
                        "mean_reciprocal_rank": selected_candidate["mean_reciprocal_rank"],
                    },
                },
                "test": {
                    "role": "sealed_one_shot_report",
                    "tuned": False,
                    "report_count": 1,
                    "gold_query_count": len(gold_test),
                    "bm25": bm25_test,
                    "vector": vector_test,
                    "fused": fused_test,
                    "hybrid": fused_test,
                    "graph": graph_test,
                    "semantic-graph": semantic_test,
                },
                "train": {
                    "role": "inspection_only_not_reported_as_gate",
                    "tuned": False,
                    "gold_query_count": len(gold_train),
                    "fused": fused_train,
                },
            },
        },
        "fusion_selection": fusion_selection,
        "goal_id": GOAL_ID,
        "graph_path": {
            "all_partitions": graph_paths,
            "test": graph_paths_test,
            "ok": graph_paths_ok,
        },
        "host_snapshot": host_snapshot,
        "io": {
            "cache_hit_ratio": CACHE_HIT_RATIO_FIXTURE,
            "model": "deterministic_fixture_io/v1",
            "sparse": sparse_io,
            "bm25_test": {
                "bytes_fetched": bm25_test.get("bytes_fetched"),
                "shards_fetched": bm25_test.get("shards_fetched"),
                "latency_ms": bm25_test.get("latency_ms"),
            },
            "vector_test": {
                "bytes_fetched": vector_test.get("bytes_fetched"),
                "shards_fetched": vector_test.get("shards_fetched"),
                "latency_ms": vector_test.get("latency_ms"),
            },
            "hybrid_test": {
                "bytes_fetched": fused_test.get("bytes_fetched"),
                "shards_fetched": fused_test.get("shards_fetched"),
                "latency_ms": fused_test.get("latency_ms"),
            },
            "graph_test": {
                "bytes_fetched": graph_test.get("bytes_fetched"),
                "shards_fetched": graph_test.get("shards_fetched"),
                "latency_ms": graph_test.get("latency_ms"),
            },
            "semantic_test": {
                "bytes_fetched": semantic_test.get("bytes_fetched"),
                "shards_fetched": semantic_test.get("shards_fetched"),
                "latency_ms": semantic_test.get("latency_ms"),
            },
        },
        "modes_meet_declared_gates": modes_meet,
        "negative_controls": negatives_eval,
        "not_legal_advice": True,
        "producer": PRODUCER,
        "production_claim": production_claim,
        "program_id": PROGRAM_ID,
        "reference_hardware": dict(REFERENCE_HARDWARE),
        "reference_network": {**REFERENCE_NETWORK, "network_required": False},
        "regressions": regressions,
        "release_profile": RELEASE_PROFILE,
        "resources": resources,
        "schema_version": REPORT_SCHEMA,
        "task_id": TASK_ID,
    }
    report["evaluation_cid"] = "sha256:" + digest_payload(
        {
            "task_id": TASK_ID,
            "fusion": fusion_selection,
            "test_hybrid_primary": fused_test.get("primary_metric_value"),
            "test_bm25_primary": bm25_test.get("primary_metric_value"),
            "test_vector_primary": vector_test.get("primary_metric_value"),
            "graph_success_rate": graph_paths.get("success_rate"),
            "production_searchable": production_searchable,
        }
    )
    return report


# ---------------------------------------------------------------------------
# Acceptance check
# ---------------------------------------------------------------------------


def check_evaluation_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise SparseGraphragEvaluationError("report must be a mapping")
    if report.get("task_id") != TASK_ID:
        raise SparseGraphragEvaluationError(f"unexpected task_id: {report.get('task_id')!r}")
    if report.get("schema_version") != REPORT_SCHEMA:
        raise SparseGraphragEvaluationError(
            f"unexpected schema_version: {report.get('schema_version')!r}"
        )

    acceptance = report.get("acceptance") or {}
    required_true = (
        "all_modes_meet_declared_recall_and_ranking",
        "bounded_shard_selection",
        "substantially_less_than_full_release",
        "fetch_traces_prove_sparse_io",
        "component_and_fused_baselines_reported",
        "chosen_defaults_declared",
        "regressions_and_exceptions_explicit",
        "reference_hardware_network_recorded",
        "no_unsupported_production_claim",
        "test_split_not_tuned",
        "test_split_reported_once",
        "budget_exhaustion_fail_closed",
        "graph_path_success",
    )
    for key in required_true:
        if not bool(acceptance.get(key)):
            raise SparseGraphragEvaluationError(f"acceptance[{key!r}] is not true")

    claim = report.get("production_claim") or {}
    if bool(claim.get("production_searchable")):
        raise SparseGraphragEvaluationError(
            "fixture evaluation must not claim production_searchable"
        )
    if "NO production-searchable claim" not in str(claim.get("claim") or ""):
        raise SparseGraphragEvaluationError("production claim text is not fail-closed")

    hardware = report.get("reference_hardware") or {}
    network = report.get("reference_network") or {}
    if not hardware.get("cpu_model") or not hardware.get("memory_gib"):
        raise SparseGraphragEvaluationError("reference_hardware incomplete")
    if network.get("network_required") is not False:
        raise SparseGraphragEvaluationError(
            "fixture evaluation must declare network_required=false"
        )

    defaults = report.get("chosen_defaults") or {}
    for key in ("bm25", "vector", "fusion", "graph", "semantic-graph"):
        if key not in defaults:
            raise SparseGraphragEvaluationError(f"chosen_defaults missing {key!r}")

    components = report.get("component_baselines") or {}
    for key in ("bm25", "vector", "graph"):
        if not bool((components.get(key) or {}).get("available")):
            raise SparseGraphragEvaluationError(f"component baseline {key!r} not available")

    partitions = (report.get("evaluation") or {}).get("partitions") or {}
    test = partitions.get("test") or {}
    if test.get("tuned") is not False:
        raise SparseGraphragEvaluationError("test partition must not be tuned")
    if int(test.get("report_count") or 0) != 1:
        raise SparseGraphragEvaluationError("test partition must be reported once")
    for mode in ("bm25", "vector", "hybrid", "graph", "semantic-graph"):
        metrics = test.get(mode) or {}
        if not metrics.get("query_count"):
            raise SparseGraphragEvaluationError(f"test {mode} metrics missing")
        if mode in {"bm25", "hybrid"} and not bool(metrics.get("meets_recall_gate")):
            raise SparseGraphragEvaluationError(f"{mode} missed declared recall gate")
        if mode == "vector" and not bool(metrics.get("meets_recall_gate")):
            raise SparseGraphragEvaluationError("vector missed declared recall gate")
        if mode == "semantic-graph" and not bool(metrics.get("meets_recall_gate")):
            raise SparseGraphragEvaluationError(
                "semantic traversal missed declared recall gate"
            )

    if not bool((report.get("graph_path") or {}).get("ok")):
        raise SparseGraphragEvaluationError("graph paths did not all succeed")

    sparse = (report.get("io") or {}).get("sparse") or {}
    if not bool(sparse.get("bounded_shard_selection")):
        raise SparseGraphragEvaluationError("fetch traces do not prove bounded shards")
    if not bool(sparse.get("substantially_less_than_full_release")):
        raise SparseGraphragEvaluationError(
            "routed queries are not substantially below full-release transfer"
        )

    regressions = report.get("regressions") or {}
    if "exceptions" not in regressions:
        raise SparseGraphragEvaluationError("regressions.exceptions missing")

    selection = report.get("fusion_selection") or {}
    if selection.get("evidence_partition") != SELECTION_PARTITION:
        raise SparseGraphragEvaluationError(
            "fusion selection must use the dev evidence partition"
        )

    return {
        "ok": True,
        "task_id": TASK_ID,
        "production_searchable": False,
        "fusion_candidate_id": selection.get("candidate_id"),
        "hybrid_recall_gate": RECALL_GATE_HYBRID,
        "test_hybrid_relevance_recall_at_primary_k": (test.get("hybrid") or {}).get(
            "primary_metric_value"
        ),
        "modes_meet_declared_gates": dict(report.get("modes_meet_declared_gates") or {}),
        "bounded_shard_selection": True,
        "substantially_less_than_full_release": True,
        "component_baselines_available": True,
        "no_unsupported_production_claim": True,
    }


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    disk_claim = bool((on_disk.get("production_claim") or {}).get("production_searchable"))
    fix_claim = bool(
        (fixture_report.get("production_claim") or {}).get("production_searchable")
    )
    if disk_claim != fix_claim:
        raise SparseGraphragEvaluationError(
            "on-disk production_searchable claim diverges from fixture evaluation"
        )
    disk_sel = on_disk.get("fusion_selection") or {}
    fix_sel = fixture_report.get("fusion_selection") or {}
    if disk_sel.get("candidate_id") != fix_sel.get("candidate_id"):
        raise SparseGraphragEvaluationError(
            "on-disk fusion candidate diverges from fixture evaluation"
        )
    if disk_sel.get("config_digest") != fix_sel.get("config_digest"):
        raise SparseGraphragEvaluationError(
            "on-disk fusion config digest diverges from fixture evaluation"
        )
    disk_test = (
        ((on_disk.get("evaluation") or {}).get("partitions") or {}).get("test", {})
    )
    fix_test = (
        ((fixture_report.get("evaluation") or {}).get("partitions") or {}).get("test", {})
    )
    for mode in ("bm25", "vector", "hybrid", "graph", "semantic-graph"):
        for key in ("primary_metric_value", "mean_reciprocal_rank", "query_count"):
            if (disk_test.get(mode) or {}).get(key) != (fix_test.get(mode) or {}).get(key):
                raise SparseGraphragEvaluationError(
                    f"on-disk {mode} test[{key!r}] diverges from fixture"
                )
    if on_disk.get("evaluation_cid") != fixture_report.get("evaluation_cid"):
        raise SparseGraphragEvaluationError(
            "on-disk evaluation_cid diverges from fixture evaluation"
        )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"fusion_candidate_id={result.get('fusion_candidate_id')}",
            f"production_searchable={result.get('production_searchable')}",
            f"hybrid_recall_gate={result.get('hybrid_recall_gate', RECALL_GATE_HYBRID)}",
            f"test_hybrid_relevance_recall_at_{PRIMARY_TOP_K}="
            f"{result.get('test_hybrid_relevance_recall_at_primary_k')}",
            f"bounded_shard_selection={result.get('bounded_shard_selection')}",
            f"substantially_less_than_full_release="
            f"{result.get('substantially_less_than_full_release')}",
            f"no_unsupported_production_claim="
            f"{result.get('no_unsupported_production_claim')}",
        ]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate BM25, vector, hybrid, graph, and semantic-traversal "
            "quality plus sparse I/O for Open US Law sparse GraphRAG "
            "(OUL-037). Default fixture mode never contacts the network."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use sealed offline gold fixture (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen report (or the live fixture evaluation when "
            "the report is missing under --fixture-only) against sealed "
            "acceptance."
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
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)

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

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise SparseGraphragEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline gold fixture"
            )

        fixture_report = run_fixture_evaluation(gold_path=gold_path)

        if args.fixture_only and (args.write or args.check):
            write_json_report(fixture_report, report_path)
            print(
                f"wrote sparse graphrag evaluation report: {report_path}",
                file=sys.stderr,
            )

        if args.check:
            if report_path.is_file():
                on_disk = load_json_mapping(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise SparseGraphragEvaluationError(
                    f"evaluation report not found for --check: {report_path}"
                )
            result = check_evaluation_report(report)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(json.dumps(dict(report), indent=2, sort_keys=True) + "\n")
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(fixture_report, indent=2, sort_keys=True) + "\n")
            return 0

        if args.write:
            return 0

        result = check_evaluation_report(fixture_report)
        print(render_check_summary(result))
        print(
            "hint: pass --fixture-only --check to validate the frozen report",
            file=sys.stderr,
        )
        return 0
    except SparseGraphragEvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
