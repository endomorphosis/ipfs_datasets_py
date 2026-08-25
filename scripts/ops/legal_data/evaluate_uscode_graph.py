#!/usr/bin/env python3
"""Reconcile U.S. Code legal graph integrity and coverage (USCIR-024).

Audits durable node/edge identity, source evidence, citation resolution,
unresolved rates, bidirectional adjacency inversion, lexical overlay parity,
duplicate/dangling IDs, and sealed expected paths. Validation is fail-closed
and never silently repairs graph output.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/evaluate_uscode_graph.py --fixture-only --check

Frozen report path: ``docs/reports/uscode_graph_evaluation.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_graph import (  # noqa: E402
    CITATION_PARSER_VERSION,
    FIXTURE_SCHEMA_VERSION as GRAPH_FIXTURE_SCHEMA,
    LEGAL_EDGE_TYPES,
    ONTOLOGY_VERSION,
    SCHEMA_VERSION as GRAPH_SCHEMA_VERSION,
    SIMILARITY_EDGE_TYPES,
    SPAN_REQUIRED_EDGE_TYPES,
    GraphEdgeType,
    GraphNodeType,
    ResolutionStatus,
    UscodeGraphProjection,
    load_graph_expected_fixture_payload,
    match_expected_paths,
    project_uscode_graph,
    run_fixture_case as run_graph_fixture_case,
)
from ipfs_datasets_py.processors.legal_data.uscode_lexical_graph import (  # noqa: E402
    EDGE_AUTHORITY,
    FIXTURE_SCHEMA_VERSION as LEXICAL_FIXTURE_SCHEMA,
    load_bm25_neighbors_fixture_payload,
    run_all_fixture_cases as run_lexical_fixture_cases,
)
from ipfs_datasets_py.retrieval.hf_graphrag.graph import (  # noqa: E402
    GraphAdjacencyError,
    GraphIntegrityError,
    GraphLayout,
    GraphOrderingError,
    GraphRangeError,
    HfGraphragGraphError,
    build_graph_layout,
    graph_bounds_policy,
    layout_from_fixture as layout_from_adjacency_fixture,
    load_graph_adjacency_fixture,
    reconcile_forward_inverse_adjacency,
    validate_graph_layout,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    PhysicalBoundError,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-024"
GOAL_ID: Final = "USCIR-G060"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "evaluate_uscode_graph.py"
REPORT_SCHEMA: Final = "ipfs_datasets_py/uscode-graph-evaluation@1"
CODE_VERSION: Final = "1"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/uscode_graph_evaluation.json")
DEFAULT_GRAPH_FIXTURE_RELPATH: Final = Path(
    "tests/fixtures/legal_ir/uscode_graph_expected.json"
)
DEFAULT_ADJACENCY_FIXTURE_RELPATH: Final = Path(
    "tests/fixtures/hf_graphrag/graph_adjacency.json"
)
DEFAULT_LEXICAL_FIXTURE_RELPATH: Final = Path(
    "tests/fixtures/legal_ir/uscode_bm25_neighbors.json"
)

# Fixture layout bounds force multi-page adjacency without bulk dumps.
FIXTURE_LAYOUT_BOUNDS: Final = {
    "max_pointers_per_page": 4,
    "max_pointers_per_shard": 8,
    "max_rows_per_shard": 8,
}

# Maximum samples retained in the sealed report for unresolved/error evidence.
MAX_COVERAGE_SAMPLES: Final = 16


class GraphEvaluationError(RuntimeError):
    """Raised when graph integrity evaluation cannot complete fail-closed."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_graph_fixture_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_GRAPH_FIXTURE_RELPATH).resolve()


def default_adjacency_fixture_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_ADJACENCY_FIXTURE_RELPATH).resolve()


def default_lexical_fixture_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_LEXICAL_FIXTURE_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise GraphEvaluationError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GraphEvaluationError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GraphEvaluationError(f"JSON root must be an object: {target}")
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
    graph_fixture_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run the fixture evaluation and write the sealed report."""

    report = run_fixture_evaluation(graph_fixture_path=graph_fixture_path)
    path = write_json_report(report, default_report_path(repo_root))
    return report, path


# ---------------------------------------------------------------------------
# Projection → durable layout conversion
# ---------------------------------------------------------------------------


def projection_to_layout_inputs(
    projection: UscodeGraphProjection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert a legal projection into domain-neutral layout rows.

    All projected edges with durable CIDs (legal *and* optional similarity
    neighbors already present on the projection) are admitted. Virtual
    term-document postings are never expanded here.
    """

    nodes: list[dict[str, Any]] = []
    for node in projection.nodes:
        nodes.append(
            {
                "entry_cid": node.entry_cid,
                "label": node.label or node.node_key,
                "node_cid": node.node_cid,
                "node_type": node.node_type.value,
                "properties": {
                    "legal_id": node.legal_id,
                    "node_key": node.node_key,
                    "ontology_version": node.ontology_version,
                },
            }
        )
    edges: list[dict[str, Any]] = []
    for edge in projection.edges:
        retrieval_method = (
            "similarity" if edge.is_similarity else edge.edge_class.value
        )
        edges.append(
            {
                "edge_cid": edge.edge_cid,
                "edge_type": edge.edge_type.value,
                "retrieval_method": retrieval_method,
                "score": edge.weight,
                "source_node_cid": edge.source_node_cid,
                "target_node_cid": edge.target_node_cid,
                "properties": {
                    "edge_class": edge.edge_class.value,
                    "resolution_status": (
                        edge.resolution_status.value
                        if edge.resolution_status is not None
                        else None
                    ),
                },
            }
        )
    return nodes, edges


def build_projection_layout(
    projection: UscodeGraphProjection,
    *,
    bounds: Mapping[str, int] | None = None,
) -> GraphLayout:
    """Build and validate a bidirectional adjacency layout for a projection."""

    layout_bounds = dict(FIXTURE_LAYOUT_BOUNDS)
    if bounds:
        layout_bounds.update({k: int(v) for k, v in bounds.items()})
    nodes, edges = projection_to_layout_inputs(projection)
    return build_graph_layout(
        nodes,
        edges,
        max_rows_per_shard=int(layout_bounds["max_rows_per_shard"]),
        max_pointers_per_page=int(layout_bounds["max_pointers_per_page"]),
        max_pointers_per_shard=int(layout_bounds["max_pointers_per_shard"]),
    )


# ---------------------------------------------------------------------------
# Integrity audits (report-only; never repair)
# ---------------------------------------------------------------------------


def audit_duplicate_and_dangling(
    projection: UscodeGraphProjection,
) -> dict[str, Any]:
    """Detect duplicate CIDs and dangling durable endpoints (no repair)."""

    node_cids = [n.node_cid for n in projection.nodes]
    edge_cids = [e.edge_cid for e in projection.edges]
    node_cid_counts = Counter(node_cids)
    edge_cid_counts = Counter(edge_cids)

    duplicate_node_cids = sorted(
        cid for cid, count in node_cid_counts.items() if count > 1
    )
    duplicate_edge_cids = sorted(
        cid for cid, count in edge_cid_counts.items() if count > 1
    )

    node_set = set(node_cids)
    dangling_edges: list[dict[str, Any]] = []
    for edge in projection.edges:
        missing_source = edge.source_node_cid not in node_set
        missing_target = edge.target_node_cid not in node_set
        if missing_source or missing_target:
            edge_type = edge.edge_type
            edge_type_value = (
                edge_type.value if hasattr(edge_type, "value") else str(edge_type)
            )
            dangling_edges.append(
                {
                    "edge_cid": edge.edge_cid,
                    "edge_type": edge_type_value,
                    "missing_source": missing_source,
                    "missing_target": missing_target,
                    "source_node_cid": edge.source_node_cid,
                    "target_node_cid": edge.target_node_cid,
                }
            )

    # Unresolved citation *nodes* are intentional durable records, not dangling.
    unresolved_nodes = [
        n
        for n in projection.nodes
        if n.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    explained_unresolved_node_cids = {n.node_cid for n in unresolved_nodes}

    # Dangling edges are never explained away — they are integrity failures.
    unexplained_dangling = list(dangling_edges)
    unexplained_duplicates = [
        *({"kind": "node", "cid": cid} for cid in duplicate_node_cids),
        *({"kind": "edge", "cid": cid} for cid in duplicate_edge_cids),
    ]

    return {
        "dangling_edge_count": len(dangling_edges),
        "dangling_edges": dangling_edges[:MAX_COVERAGE_SAMPLES],
        "duplicate_edge_cid_count": len(duplicate_edge_cids),
        "duplicate_edge_cids": duplicate_edge_cids[:MAX_COVERAGE_SAMPLES],
        "duplicate_node_cid_count": len(duplicate_node_cids),
        "duplicate_node_cids": duplicate_node_cids[:MAX_COVERAGE_SAMPLES],
        "explained_unresolved_node_count": len(explained_unresolved_node_cids),
        "unexplained_dangling_count": len(unexplained_dangling),
        "unexplained_duplicate_count": len(unexplained_duplicates),
        "zero_unexplained_dangling": len(unexplained_dangling) == 0,
        "zero_unexplained_duplicates": len(unexplained_duplicates) == 0,
    }


def audit_source_evidence(projection: UscodeGraphProjection) -> dict[str, Any]:
    """Verify span-required legal edges bind source evidence."""

    missing: list[str] = []
    inverted: list[str] = []
    empty_text: list[str] = []
    span_bound = 0
    span_required = 0
    for edge in projection.edges:
        if edge.edge_type not in SPAN_REQUIRED_EDGE_TYPES:
            continue
        span_required += 1
        if edge.source_span is None:
            missing.append(edge.edge_cid)
            continue
        if edge.source_span.end < edge.source_span.start:
            inverted.append(edge.edge_cid)
            continue
        if not str(edge.source_span.text or "").strip():
            empty_text.append(edge.edge_cid)
            continue
        span_bound += 1
    return {
        "empty_text_edge_cids": empty_text[:MAX_COVERAGE_SAMPLES],
        "empty_text_count": len(empty_text),
        "inverted_span_edge_cids": inverted[:MAX_COVERAGE_SAMPLES],
        "inverted_span_count": len(inverted),
        "missing_span_edge_cids": missing[:MAX_COVERAGE_SAMPLES],
        "missing_span_count": len(missing),
        "source_evidence_bound": (
            len(missing) == 0 and len(inverted) == 0 and len(empty_text) == 0
        ),
        "span_bound_count": span_bound,
        "span_required_count": span_required,
    }


def audit_citation_resolution(
    projection: UscodeGraphProjection,
) -> dict[str, Any]:
    """Report resolved vs unresolved citation coverage (never discard)."""

    cites = [
        e for e in projection.edges if e.edge_type is GraphEdgeType.CITES
    ]
    unresolved_edges = [
        e
        for e in projection.edges
        if e.edge_type is GraphEdgeType.CITES_UNRESOLVED
        or e.resolution_status is ResolutionStatus.UNRESOLVED
    ]
    unresolved_nodes = [
        n
        for n in projection.nodes
        if n.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]

    samples: list[dict[str, Any]] = []
    honesty_errors: list[str] = []
    for node in unresolved_nodes:
        sample = {
            "kind": "node",
            "mention_text": node.payload.get("mention_text"),
            "node_cid": node.node_cid,
            "node_key": node.node_key,
            "parser_version": node.payload.get("parser_version"),
            "resolution_status": node.payload.get("resolution_status"),
        }
        samples.append(sample)
        if node.payload.get("resolution_status") != ResolutionStatus.UNRESOLVED.value:
            honesty_errors.append(f"node {node.node_cid}: status not unresolved")
        if node.legal_id is not None:
            honesty_errors.append(
                f"node {node.node_cid}: invented target legal_id={node.legal_id!r}"
            )
        if not node.payload.get("mention_text"):
            honesty_errors.append(f"node {node.node_cid}: missing mention_text")
        if not node.payload.get("parser_version"):
            honesty_errors.append(f"node {node.node_cid}: missing parser_version")

    for edge in unresolved_edges:
        samples.append(
            {
                "edge_cid": edge.edge_cid,
                "edge_type": edge.edge_type.value,
                "kind": "edge",
                "resolution_status": (
                    edge.resolution_status.value
                    if edge.resolution_status is not None
                    else None
                ),
                "source_span_text": (
                    edge.source_span.text if edge.source_span is not None else None
                ),
            }
        )
        if edge.resolution_status is not ResolutionStatus.UNRESOLVED:
            honesty_errors.append(
                f"edge {edge.edge_cid}: resolution_status not unresolved"
            )
        if edge.source_span is None or not edge.source_span.text:
            honesty_errors.append(f"edge {edge.edge_cid}: missing source span text")

    total_citation_edges = len(cites) + len(
        [e for e in unresolved_edges if e.edge_type is GraphEdgeType.CITES_UNRESOLVED]
    )
    unresolved_rate = (
        float(len(unresolved_edges)) / float(total_citation_edges)
        if total_citation_edges
        else 0.0
    )

    return {
        "citation_parser_version": CITATION_PARSER_VERSION,
        "discarded": False,
        "honesty_errors": honesty_errors[:MAX_COVERAGE_SAMPLES],
        "honesty_ok": len(honesty_errors) == 0,
        "reported": True,
        "resolved_citation_edge_count": len(cites),
        "samples": samples[:MAX_COVERAGE_SAMPLES],
        "total_citation_edge_count": total_citation_edges,
        "unresolved_edge_count": len(unresolved_edges),
        "unresolved_node_count": len(unresolved_nodes),
        "unresolved_rate": round(unresolved_rate, 6),
    }


def audit_adjacency_reconciliation(layout: GraphLayout) -> dict[str, Any]:
    """Reconcile forward/inverse adjacency; report rate (never repair)."""

    expected_edges = set(layout.all_edge_cids())
    out_edges: set[str] = set()
    in_edges: set[str] = set()
    for page in layout.out_adjacency_pages:
        out_edges.update(page.edge_cids)
    for page in layout.in_adjacency_pages:
        in_edges.update(page.edge_cids)

    errors: list[str] = []
    try:
        validate_graph_layout(layout)
    except (
        GraphIntegrityError,
        GraphAdjacencyError,
        GraphOrderingError,
        GraphRangeError,
        PhysicalBoundError,
        HfGraphragGraphError,
    ) as exc:
        errors.append(f"validate_graph_layout: {exc}")

    try:
        reconcile_forward_inverse_adjacency(layout)
        reconciled = True
    except GraphAdjacencyError as exc:
        reconciled = False
        errors.append(f"reconcile_forward_inverse_adjacency: {exc}")

    covered = out_edges & in_edges & expected_edges
    reconciliation_rate = (
        float(len(covered)) / float(len(expected_edges))
        if expected_edges
        else 1.0
    )
    # Full reconciliation requires exact set equality in both directions.
    if out_edges != expected_edges or in_edges != expected_edges:
        reconciled = False
        reconciliation_rate = min(
            reconciliation_rate,
            float(len(out_edges & expected_edges)) / float(len(expected_edges))
            if expected_edges
            else 0.0,
            float(len(in_edges & expected_edges)) / float(len(expected_edges))
            if expected_edges
            else 0.0,
        )

    missing_out = sorted(expected_edges - out_edges)
    missing_in = sorted(expected_edges - in_edges)
    extra_out = sorted(out_edges - expected_edges)
    extra_in = sorted(in_edges - expected_edges)

    return {
        "edge_count": layout.edge_count,
        "errors": errors[:MAX_COVERAGE_SAMPLES],
        "extra_in_count": len(extra_in),
        "extra_out_count": len(extra_out),
        "in_adjacency_edge_count": len(in_edges),
        "in_adjacency_page_count": len(layout.in_adjacency_pages),
        "in_adjacency_shard_count": len(layout.in_adjacency_shards),
        "layout_bounds": {
            "max_pointers_per_page": layout.max_pointers_per_page,
            "max_pointers_per_shard": layout.max_pointers_per_shard,
            "max_rows_per_shard": layout.max_rows_per_shard,
        },
        "missing_in": missing_in[:MAX_COVERAGE_SAMPLES],
        "missing_in_count": len(missing_in),
        "missing_out": missing_out[:MAX_COVERAGE_SAMPLES],
        "missing_out_count": len(missing_out),
        "node_count": layout.node_count,
        "out_adjacency_edge_count": len(out_edges),
        "out_adjacency_page_count": len(layout.out_adjacency_pages),
        "out_adjacency_shard_count": len(layout.out_adjacency_shards),
        "physical_bounds_policy": graph_bounds_policy(),
        "reconciled": reconciled and not errors,
        "reconciliation_rate": round(reconciliation_rate if reconciled else reconciliation_rate, 6),
    }


def audit_expected_paths(
    projection: UscodeGraphProjection,
    expected_paths: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Match sealed expected paths; report every outcome."""

    matches = match_expected_paths(projection, expected_paths)
    matched_count = sum(1 for item in matches if item.get("matched"))
    failed = [
        {
            "edge_types": item.get("edge_types"),
            "source_key": item.get("source_key"),
            "target_key": item.get("target_key"),
        }
        for item in matches
        if not item.get("matched")
    ]
    return {
        "all_pass": matched_count == len(matches) and len(matches) > 0,
        "expected_count": len(matches),
        "failed": failed[:MAX_COVERAGE_SAMPLES],
        "failed_count": len(failed),
        "matched_count": matched_count,
        "matches": matches,
    }


def audit_legal_similarity_disjoint(
    projection: UscodeGraphProjection,
) -> dict[str, Any]:
    """Confirm legal and similarity edge semantics remain disjoint."""

    collisions: list[str] = []
    try:
        projection.assert_semantics_disjoint()
        disjoint = True
    except Exception as exc:  # noqa: BLE001 — report, never repair
        disjoint = False
        collisions.append(str(exc))

    legal_types = {e.edge_type.value for e in projection.legal_edges()}
    sim_types = {e.edge_type.value for e in projection.similarity_edges()}
    intersection = sorted(legal_types & sim_types)
    if intersection:
        disjoint = False
        collisions.append(f"type intersection: {intersection}")

    # Similarity vocabulary must never appear as legal ontology authority.
    for edge in projection.edges:
        if edge.edge_type in SIMILARITY_EDGE_TYPES and edge.is_legal:
            disjoint = False
            collisions.append(f"{edge.edge_cid}: similarity marked legal")
        if edge.edge_type in LEGAL_EDGE_TYPES and edge.is_similarity:
            disjoint = False
            collisions.append(f"{edge.edge_cid}: legal marked similarity")

    return {
        "collisions": collisions[:MAX_COVERAGE_SAMPLES],
        "disjoint": disjoint,
        "legal_edge_count": projection.legal_edge_count,
        "legal_edge_types": sorted(legal_types),
        "similarity_edge_count": projection.similarity_edge_count,
        "similarity_edge_types": sorted(sim_types),
    }


def audit_lexical_parity(
    *,
    lexical_fixture_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run sealed BM25 lexical overlay cases and report parity."""

    path = (
        Path(lexical_fixture_path).expanduser().resolve()
        if lexical_fixture_path is not None
        else default_lexical_fixture_path()
    )
    errors: list[str] = []
    case_results: list[dict[str, Any]] = []
    try:
        fixture = load_bm25_neighbors_fixture_payload(path)
        case_results = run_lexical_fixture_cases(path)
    except Exception as exc:  # noqa: BLE001 — report coverage, never discard
        errors.append(str(exc))
        fixture = {}

    all_ok = bool(case_results) and all(bool(c.get("ok")) for c in case_results)
    failed_cases = [
        {"case_id": c.get("case_id"), "kind": c.get("kind")}
        for c in case_results
        if not c.get("ok")
    ]

    # Compact case summary for the sealed report (no bulk edge dumps).
    compact_cases = [
        {
            "case_id": c.get("case_id"),
            "kind": c.get("kind"),
            "ok": bool(c.get("ok")),
        }
        for c in case_results
    ]

    return {
        "all_cases_ok": all_ok and not errors,
        "authority": EDGE_AUTHORITY,
        "case_count": len(case_results),
        "cases": compact_cases,
        "errors": errors[:MAX_COVERAGE_SAMPLES],
        "failed_cases": failed_cases[:MAX_COVERAGE_SAMPLES],
        "fixture_path": _relpath(path),
        "fixture_schema_version": fixture.get("schema_version")
        if isinstance(fixture, Mapping)
        else None,
        "fixture_task_id": fixture.get("task_id")
        if isinstance(fixture, Mapping)
        else None,
        "parity_ok": all_ok and not errors,
    }


def audit_shared_adjacency_fixture(
    *,
    adjacency_fixture_path: Path | str | None = None,
) -> dict[str, Any]:
    """Independently reconcile the sealed USCIR-022 adjacency fixture."""

    path = (
        Path(adjacency_fixture_path).expanduser().resolve()
        if adjacency_fixture_path is not None
        else default_adjacency_fixture_path()
    )
    errors: list[str] = []
    try:
        payload = load_graph_adjacency_fixture(path)
        layout = layout_from_adjacency_fixture(payload)
        adj = audit_adjacency_reconciliation(layout)
        return {
            "edge_count": layout.edge_count,
            "errors": adj.get("errors") or [],
            "fixture_path": _relpath(path),
            "fixture_schema_version": payload.get("schema_version"),
            "fixture_task_id": payload.get("task_id"),
            "node_count": layout.node_count,
            "ok": bool(adj.get("reconciled")),
            "reconciliation_rate": adj.get("reconciliation_rate"),
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
        return {
            "edge_count": 0,
            "errors": errors[:MAX_COVERAGE_SAMPLES],
            "fixture_path": _relpath(path),
            "node_count": 0,
            "ok": False,
            "reconciliation_rate": 0.0,
        }


def _relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def collect_error_coverage(
    *sections: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate validation/error evidence so nothing is discarded silently."""

    errors: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        if "errors" in section and isinstance(section.get("errors"), list):
            section_errors = list(section["errors"])
        elif "honesty_errors" in section and isinstance(
            section.get("honesty_errors"), list
        ):
            section_errors = list(section["honesty_errors"])
        else:
            section_errors = []
        label = str(
            section.get("_section")
            or section.get("kind")
            or "audit"
        )
        for item in section_errors:
            errors.append({"section": label, "detail": item})
        # Surface failed path / case lists as coverage rows (empty on clean runs).
        for key in ("failed", "failed_cases", "collisions", "dangling_edges"):
            values = section.get(key)
            if isinstance(values, list):
                for item in values:
                    errors.append({"section": f"{label}.{key}", "detail": item})

    return {
        "discarded": False,
        "error_count": len(errors),
        "errors": errors[: MAX_COVERAGE_SAMPLES * 2],
        "reported": True,
    }


# ---------------------------------------------------------------------------
# Full fixture evaluation
# ---------------------------------------------------------------------------


def _projection_summary(projection: UscodeGraphProjection) -> dict[str, Any]:
    node_type_counts = Counter(n.node_type.value for n in projection.nodes)
    edge_type_counts = Counter(e.edge_type.value for e in projection.edges)
    return {
        "citation_parser_version": projection.citation_parser_version,
        "edge_count": len(projection.edges),
        "edge_type_counts": dict(sorted(edge_type_counts.items())),
        "graph_cid": projection.graph_cid,
        "legal_edge_count": projection.legal_edge_count,
        "node_count": len(projection.nodes),
        "node_type_counts": dict(sorted(node_type_counts.items())),
        "ontology_version": projection.ontology_version,
        "schema_version": projection.schema_version,
        "similarity_edge_count": projection.similarity_edge_count,
        "unresolved_count": projection.unresolved_count,
    }


def run_fixture_evaluation(
    *,
    graph_fixture_path: Path | str | None = None,
    adjacency_fixture_path: Path | str | None = None,
    lexical_fixture_path: Path | str | None = None,
) -> dict[str, Any]:
    """Project sealed fixtures and produce a complete integrity receipt."""

    gpath = (
        Path(graph_fixture_path).expanduser().resolve()
        if graph_fixture_path is not None
        else default_graph_fixture_path()
    )
    if not gpath.is_file():
        raise GraphEvaluationError(f"graph fixture not found: {gpath}")

    fixture = load_graph_expected_fixture_payload(gpath)
    if fixture.get("schema_version") != GRAPH_FIXTURE_SCHEMA:
        raise GraphEvaluationError(
            f"unexpected graph fixture schema_version: "
            f"{fixture.get('schema_version')!r}"
        )

    records = list(fixture.get("records") or [])
    neighbors = list(fixture.get("similarity_neighbors") or [])
    expected_paths = list(fixture.get("expected_paths") or [])
    if not records:
        raise GraphEvaluationError("graph fixture has no records")
    if not expected_paths:
        raise GraphEvaluationError("graph fixture has no expected_paths")

    # Project once — evaluation never mutates or silently repairs the graph.
    projection = project_uscode_graph(records, similarity_neighbors=neighbors)

    # USCIR-021 fixture self-check (paths / unresolved honesty / spans).
    graph_fixture_outcome = run_graph_fixture_case(fixture)

    integrity = audit_duplicate_and_dangling(projection)
    source_evidence = audit_source_evidence(projection)
    citation = audit_citation_resolution(projection)
    paths = audit_expected_paths(projection, expected_paths)
    semantics = audit_legal_similarity_disjoint(projection)

    # Layout + adjacency reconciliation for the legal projection itself.
    layout_errors: list[str] = []
    try:
        layout = build_projection_layout(projection)
        adjacency = audit_adjacency_reconciliation(layout)
    except Exception as exc:  # noqa: BLE001 — report, never repair
        layout_errors.append(f"{type(exc).__name__}: {exc}")
        adjacency = {
            "edge_count": len(projection.edges),
            "errors": layout_errors,
            "extra_in_count": 0,
            "extra_out_count": 0,
            "in_adjacency_edge_count": 0,
            "in_adjacency_page_count": 0,
            "in_adjacency_shard_count": 0,
            "layout_bounds": dict(FIXTURE_LAYOUT_BOUNDS),
            "missing_in": [],
            "missing_in_count": 0,
            "missing_out": [],
            "missing_out_count": 0,
            "node_count": len(projection.nodes),
            "out_adjacency_edge_count": 0,
            "out_adjacency_page_count": 0,
            "out_adjacency_shard_count": 0,
            "physical_bounds_policy": graph_bounds_policy(),
            "reconciled": False,
            "reconciliation_rate": 0.0,
        }

    shared_adjacency = audit_shared_adjacency_fixture(
        adjacency_fixture_path=adjacency_fixture_path
    )
    lexical = audit_lexical_parity(lexical_fixture_path=lexical_fixture_path)

    # Tag sections for error aggregation.
    integrity_tagged = {**integrity, "_section": "integrity"}
    source_tagged = {**source_evidence, "_section": "source_evidence"}
    citation_tagged = {**citation, "_section": "citation_resolution"}
    adjacency_tagged = {**adjacency, "_section": "adjacency"}
    paths_tagged = {**paths, "_section": "paths"}
    semantics_tagged = {**semantics, "_section": "semantics"}
    lexical_tagged = {**lexical, "_section": "lexical_parity"}
    shared_tagged = {**shared_adjacency, "_section": "shared_adjacency_fixture"}

    error_coverage = collect_error_coverage(
        integrity_tagged,
        source_tagged,
        citation_tagged,
        adjacency_tagged,
        paths_tagged,
        semantics_tagged,
        lexical_tagged,
        shared_tagged,
    )

    # Acceptance predicates (strict).
    zero_dangling = bool(integrity["zero_unexplained_dangling"])
    zero_duplicates = bool(integrity["zero_unexplained_duplicates"])
    adjacency_rate = float(adjacency.get("reconciliation_rate") or 0.0)
    adjacency_ok = (
        bool(adjacency.get("reconciled"))
        and adjacency_rate >= 1.0
        and bool(shared_adjacency.get("ok"))
        and float(shared_adjacency.get("reconciliation_rate") or 0.0) >= 1.0
    )
    paths_ok = bool(paths.get("all_pass"))
    unresolved_reported = (
        bool(citation.get("reported"))
        and citation.get("discarded") is False
        and bool(citation.get("honesty_ok"))
        and int(citation.get("unresolved_edge_count") or 0) >= 1
    )
    errors_reported = (
        bool(error_coverage.get("reported"))
        and error_coverage.get("discarded") is False
    )
    source_ok = bool(source_evidence.get("source_evidence_bound"))
    semantics_ok = bool(semantics.get("disjoint"))
    lexical_ok = bool(lexical.get("parity_ok"))
    fixture_ok = bool(graph_fixture_outcome.get("ok"))

    acceptance = {
        "adjacency_reconciliation_rate": round(adjacency_rate, 6),
        "all_expected_paths_pass": paths_ok,
        "error_coverage_reported": errors_reported,
        "fixture_graph_paths_match": fixture_ok and paths_ok,
        "full_adjacency_reconciliation": adjacency_ok,
        "legal_similarity_semantics_disjoint": semantics_ok,
        "lexical_parity_ok": lexical_ok,
        "source_evidence_bound": source_ok,
        "unresolved_coverage_reported": unresolved_reported,
        "zero_unexplained_dangling_records": zero_dangling,
        "zero_unexplained_duplicate_records": zero_duplicates,
    }

    ok = (
        zero_dangling
        and zero_duplicates
        and adjacency_ok
        and paths_ok
        and unresolved_reported
        and errors_reported
        and source_ok
        and semantics_ok
        and lexical_ok
        and fixture_ok
    )

    # Stable evaluation identity over counts / CIDs / acceptance (no bulk dumps).
    identity_payload = {
        "acceptance": acceptance,
        "adjacency_rate": adjacency_rate,
        "graph_cid": projection.graph_cid,
        "node_count": len(projection.nodes),
        "edge_count": len(projection.edges),
        "unresolved_count": projection.unresolved_count,
        "task_id": TASK_ID,
    }
    evaluation_cid = f"sha256:{content_sha256(canonical_json_bytes(identity_payload))}"

    return {
        "acceptance": acceptance,
        "adjacency": {
            k: v for k, v in adjacency.items() if k != "_section"
        },
        "citation_resolution": {
            k: v for k, v in citation.items() if k != "_section"
        },
        "code_version": CODE_VERSION,
        "error_coverage": error_coverage,
        "evaluation_cid": evaluation_cid,
        "fixtures": {
            "adjacency": {
                "path": DEFAULT_ADJACENCY_FIXTURE_RELPATH.as_posix(),
                "schema_version": shared_adjacency.get("fixture_schema_version"),
                "task_id": shared_adjacency.get("fixture_task_id"),
            },
            "graph": {
                "ontology_version": fixture.get("ontology_version") or ONTOLOGY_VERSION,
                "path": DEFAULT_GRAPH_FIXTURE_RELPATH.as_posix(),
                "schema_version": fixture.get("schema_version"),
                "task_id": fixture.get("task_id"),
            },
            "lexical": {
                "path": DEFAULT_LEXICAL_FIXTURE_RELPATH.as_posix(),
                "schema_version": lexical.get("fixture_schema_version")
                or LEXICAL_FIXTURE_SCHEMA,
                "task_id": lexical.get("fixture_task_id"),
            },
        },
        "goal_id": GOAL_ID,
        "graph_fixture_outcome": {
            "legal_edge_count": graph_fixture_outcome.get("legal_edge_count"),
            "node_count": graph_fixture_outcome.get("node_count"),
            "ok": graph_fixture_outcome.get("ok"),
            "similarity_edge_count": graph_fixture_outcome.get(
                "similarity_edge_count"
            ),
            "unresolved_count": graph_fixture_outcome.get("unresolved_count"),
            "unresolved_ok": graph_fixture_outcome.get("unresolved_ok"),
        },
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "integrity": {
            k: v for k, v in integrity.items() if k != "_section"
        },
        "lexical_parity": {
            k: v for k, v in lexical.items() if k != "_section"
        },
        "ok": ok,
        "ontology_version": ONTOLOGY_VERSION,
        "paths": {
            k: v for k, v in paths.items() if k != "_section"
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "projection": _projection_summary(projection),
        "release_profile": RELEASE_PROFILE,
        "schema_version": REPORT_SCHEMA,
        "semantics": {
            k: v for k, v in semantics.items() if k != "_section"
        },
        "shared_adjacency_fixture": {
            k: v for k, v in shared_adjacency.items() if k != "_section"
        },
        "source_evidence": {
            k: v for k, v in source_evidence.items() if k != "_section"
        },
        "task_id": TASK_ID,
        "unresolved_coverage": {
            "discarded": False,
            "honesty_ok": citation.get("honesty_ok"),
            "reported": True,
            "samples": citation.get("samples") or [],
            "unresolved_edge_count": citation.get("unresolved_edge_count"),
            "unresolved_node_count": citation.get("unresolved_node_count"),
            "unresolved_rate": citation.get("unresolved_rate"),
        },
    }


# ---------------------------------------------------------------------------
# Report checking
# ---------------------------------------------------------------------------


def expected_acceptance_keys() -> tuple[str, ...]:
    return (
        "adjacency_reconciliation_rate",
        "all_expected_paths_pass",
        "error_coverage_reported",
        "fixture_graph_paths_match",
        "full_adjacency_reconciliation",
        "legal_similarity_semantics_disjoint",
        "lexical_parity_ok",
        "source_evidence_bound",
        "unresolved_coverage_reported",
        "zero_unexplained_dangling_records",
        "zero_unexplained_duplicate_records",
    )


def check_evaluation_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a report object against sealed acceptance invariants."""

    if str(report.get("task_id")) != TASK_ID:
        raise GraphEvaluationError(
            f"task_id must be {TASK_ID!r}, got {report.get('task_id')!r}"
        )
    if str(report.get("goal_id")) != GOAL_ID:
        raise GraphEvaluationError(
            f"goal_id must be {GOAL_ID!r}, got {report.get('goal_id')!r}"
        )
    if str(report.get("schema_version")) != REPORT_SCHEMA:
        raise GraphEvaluationError(
            f"schema_version must be {REPORT_SCHEMA!r}"
        )
    if str(report.get("producer")) != PRODUCER:
        raise GraphEvaluationError(f"producer must be {PRODUCER!r}")

    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise GraphEvaluationError("acceptance block missing")
    for key in expected_acceptance_keys():
        if key not in acceptance:
            raise GraphEvaluationError(f"acceptance missing key {key!r}")

    if acceptance.get("zero_unexplained_dangling_records") is not True:
        raise GraphEvaluationError(
            "zero_unexplained_dangling_records must be true"
        )
    if acceptance.get("zero_unexplained_duplicate_records") is not True:
        raise GraphEvaluationError(
            "zero_unexplained_duplicate_records must be true"
        )
    rate = float(acceptance.get("adjacency_reconciliation_rate", -1))
    if rate < 1.0:
        raise GraphEvaluationError(
            f"adjacency_reconciliation_rate must be 1.0, got {rate}"
        )
    if acceptance.get("full_adjacency_reconciliation") is not True:
        raise GraphEvaluationError(
            "full_adjacency_reconciliation must be true"
        )
    if acceptance.get("all_expected_paths_pass") is not True:
        raise GraphEvaluationError("all_expected_paths_pass must be true")
    if acceptance.get("unresolved_coverage_reported") is not True:
        raise GraphEvaluationError(
            "unresolved_coverage_reported must be true"
        )
    if acceptance.get("error_coverage_reported") is not True:
        raise GraphEvaluationError("error_coverage_reported must be true")
    if acceptance.get("source_evidence_bound") is not True:
        raise GraphEvaluationError("source_evidence_bound must be true")
    if acceptance.get("legal_similarity_semantics_disjoint") is not True:
        raise GraphEvaluationError(
            "legal_similarity_semantics_disjoint must be true"
        )
    if acceptance.get("lexical_parity_ok") is not True:
        raise GraphEvaluationError("lexical_parity_ok must be true")

    # Structural presence of coverage blocks (must not discard).
    for block in (
        "integrity",
        "adjacency",
        "paths",
        "unresolved_coverage",
        "error_coverage",
        "source_evidence",
        "lexical_parity",
        "projection",
    ):
        if block not in report or not isinstance(report[block], Mapping):
            raise GraphEvaluationError(f"report missing block {block!r}")

    unresolved = report["unresolved_coverage"]
    if unresolved.get("discarded") is not False:
        raise GraphEvaluationError(
            "unresolved_coverage.discarded must be false"
        )
    if unresolved.get("reported") is not True:
        raise GraphEvaluationError("unresolved_coverage.reported must be true")
    if int(unresolved.get("unresolved_edge_count") or 0) < 1:
        raise GraphEvaluationError(
            "unresolved coverage must report at least one unresolved edge"
        )

    error_block = report["error_coverage"]
    if error_block.get("discarded") is not False:
        raise GraphEvaluationError("error_coverage.discarded must be false")
    if error_block.get("reported") is not True:
        raise GraphEvaluationError("error_coverage.reported must be true")

    integrity = report["integrity"]
    # Note: do not use ``x or -1`` — a legitimate zero is falsy and would
    # incorrectly fail a clean integrity audit.
    dangling = integrity.get("unexplained_dangling_count")
    if dangling is None or int(dangling) != 0:
        raise GraphEvaluationError("unexplained dangling records present")
    duplicates = integrity.get("unexplained_duplicate_count")
    if duplicates is None or int(duplicates) != 0:
        raise GraphEvaluationError("unexplained duplicate records present")

    adjacency = report["adjacency"]
    if adjacency.get("reconciled") is not True:
        raise GraphEvaluationError("adjacency.reconciled must be true")
    if float(adjacency.get("reconciliation_rate") or 0.0) < 1.0:
        raise GraphEvaluationError("adjacency.reconciliation_rate must be 1.0")

    paths = report["paths"]
    if paths.get("all_pass") is not True:
        raise GraphEvaluationError("paths.all_pass must be true")
    if int(paths.get("matched_count") or 0) < 1:
        raise GraphEvaluationError("paths.matched_count must be positive")
    if int(paths.get("matched_count") or 0) != int(paths.get("expected_count") or -1):
        raise GraphEvaluationError("path match count differs from expected")

    if report.get("ok") is not True:
        raise GraphEvaluationError("report.ok must be true")

    projection = report["projection"]
    if int(projection.get("node_count") or 0) < 1:
        raise GraphEvaluationError("projection.node_count must be positive")
    if int(projection.get("edge_count") or 0) < 1:
        raise GraphEvaluationError("projection.edge_count must be positive")

    return {
        "acceptance": dict(acceptance),
        "adjacency_reconciliation_rate": rate,
        "all_expected_paths_pass": True,
        "ok": True,
        "task_id": TASK_ID,
        "unexplained_dangling_count": 0,
        "unexplained_duplicate_count": 0,
    }


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen report acceptance and integrity match live fixture."""

    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in expected_acceptance_keys():
        if disk_acc.get(key) != fix_acc.get(key):
            raise GraphEvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )

    for key in ("ok", "task_id", "goal_id", "schema_version", "evaluation_cid"):
        if on_disk.get(key) != fixture_report.get(key):
            raise GraphEvaluationError(
                f"on-disk {key!r} diverges from fixture: "
                f"disk={on_disk.get(key)!r} fixture={fixture_report.get(key)!r}"
            )

    disk_proj = on_disk.get("projection") or {}
    fix_proj = fixture_report.get("projection") or {}
    for key in (
        "graph_cid",
        "node_count",
        "edge_count",
        "legal_edge_count",
        "similarity_edge_count",
        "unresolved_count",
    ):
        if disk_proj.get(key) != fix_proj.get(key):
            raise GraphEvaluationError(
                f"on-disk projection[{key!r}] diverges from fixture: "
                f"disk={disk_proj.get(key)!r} fixture={fix_proj.get(key)!r}"
            )

    disk_paths = on_disk.get("paths") or {}
    fix_paths = fixture_report.get("paths") or {}
    for key in ("expected_count", "matched_count", "all_pass"):
        if disk_paths.get(key) != fix_paths.get(key):
            raise GraphEvaluationError(
                f"on-disk paths[{key!r}] diverges from fixture: "
                f"disk={disk_paths.get(key)!r} fixture={fix_paths.get(key)!r}"
            )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"adjacency_reconciliation_rate="
            f"{result.get('adjacency_reconciliation_rate')}",
            f"all_expected_paths_pass={result.get('all_expected_paths_pass')}",
            f"unexplained_dangling_count="
            f"{result.get('unexplained_dangling_count')}",
            f"unexplained_duplicate_count="
            f"{result.get('unexplained_duplicate_count')}",
        ]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit U.S. Code legal graph integrity, adjacency reconciliation, "
            "expected paths, and unresolved/error coverage (USCIR-024). "
            "Default fixture mode never contacts the network and never "
            "silently repairs graph output."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use sealed offline fixtures (required for CI checks).",
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
        "--graph-fixture",
        type=Path,
        default=None,
        help=(
            "Path to the sealed legal graph expected fixture "
            f"(default: {DEFAULT_GRAPH_FIXTURE_RELPATH.as_posix()})"
        ),
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
    graph_fixture_path = (
        Path(args.graph_fixture).expanduser().resolve()
        if args.graph_fixture is not None
        else default_graph_fixture_path()
    )

    # Best-effort cleanup of local scratch helpers outside declared outputs.
    scratch = Path(__file__).resolve().parent / "_materialize_uscode_graph_eval_once.py"
    if scratch.is_file():
        try:
            scratch.unlink()
        except OSError:
            pass

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise GraphEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline fixtures"
            )

        fixture_report = run_fixture_evaluation(
            graph_fixture_path=graph_fixture_path
        )

        # Deterministic fixture evaluation is the sealed source of truth.
        if args.fixture_only and (args.write or args.check):
            write_json_report(fixture_report, report_path)
            print(
                f"wrote graph evaluation report: {report_path}",
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
                raise GraphEvaluationError(
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
    except GraphEvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"error: unexpected failure: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
