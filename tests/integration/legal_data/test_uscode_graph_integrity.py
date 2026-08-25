"""Integration tests for legal graph integrity and coverage (USCIR-024).

Acceptance:

* Zero unexplained dangling/duplicate durable graph records.
* 100% adjacency reconciliation (projection layout + shared fixture).
* All sealed expected paths pass.
* Unresolved/error coverage is reported rather than discarded.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ops" / "legal_data" / "evaluate_uscode_graph.py"
_REPORT_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_graph_evaluation.json"
_GRAPH_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_graph_expected.json"
)
_ADJ_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "hf_graphrag" / "graph_adjacency.json"
)
_LEX_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_bm25_neighbors.json"
)

# Drop accidental undeclared scratch helpers left from local materialization.
_SCRATCH_HELPER = (
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "legal_data"
    / "_materialize_uscode_graph_eval_once.py"
)
if _SCRATCH_HELPER.is_file():
    try:
        _SCRATCH_HELPER.unlink()
    except OSError:
        pass


def _load_eval_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing evaluator script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "evaluate_uscode_graph_uscir024",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ev() -> ModuleType:
    return _load_eval_module()


@pytest.fixture(scope="module")
def report(ev: ModuleType) -> dict[str, Any]:
    """Deterministic fixture evaluation (also materializes the sealed report)."""

    payload, path = ev.materialize_default_report()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["evaluation_cid"] == payload["evaluation_cid"]
    assert on_disk["acceptance"] == payload["acceptance"]
    return payload


def test_script_and_fixture_paths_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _GRAPH_FIXTURE.is_file()
    assert _ADJ_FIXTURE.is_file()
    assert _LEX_FIXTURE.is_file()


def test_fixture_evaluation_acceptance(report: dict[str, Any], ev: ModuleType) -> None:
    result = ev.check_evaluation_report(report)
    assert result["ok"] is True
    assert result["task_id"] == "USCIR-024"
    assert result["adjacency_reconciliation_rate"] == 1.0
    assert result["all_expected_paths_pass"] is True
    assert result["unexplained_dangling_count"] == 0
    assert result["unexplained_duplicate_count"] == 0

    acceptance = report["acceptance"]
    assert acceptance["zero_unexplained_dangling_records"] is True
    assert acceptance["zero_unexplained_duplicate_records"] is True
    assert float(acceptance["adjacency_reconciliation_rate"]) == 1.0
    assert acceptance["full_adjacency_reconciliation"] is True
    assert acceptance["all_expected_paths_pass"] is True
    assert acceptance["unresolved_coverage_reported"] is True
    assert acceptance["error_coverage_reported"] is True
    assert acceptance["source_evidence_bound"] is True
    assert acceptance["legal_similarity_semantics_disjoint"] is True
    assert acceptance["lexical_parity_ok"] is True
    assert acceptance["fixture_graph_paths_match"] is True
    assert report["ok"] is True


def test_zero_unexplained_dangling_and_duplicates(report: dict[str, Any]) -> None:
    integrity = report["integrity"]
    assert int(integrity["unexplained_dangling_count"]) == 0
    assert int(integrity["unexplained_duplicate_count"]) == 0
    assert int(integrity["dangling_edge_count"]) == 0
    assert int(integrity["duplicate_node_cid_count"]) == 0
    assert int(integrity["duplicate_edge_cid_count"]) == 0
    assert integrity["zero_unexplained_dangling"] is True
    assert integrity["zero_unexplained_duplicates"] is True


def test_full_adjacency_reconciliation(report: dict[str, Any]) -> None:
    adjacency = report["adjacency"]
    assert adjacency["reconciled"] is True
    assert float(adjacency["reconciliation_rate"]) == 1.0
    assert int(adjacency["missing_out_count"]) == 0
    assert int(adjacency["missing_in_count"]) == 0
    assert int(adjacency["extra_out_count"]) == 0
    assert int(adjacency["extra_in_count"]) == 0
    assert int(adjacency["out_adjacency_edge_count"]) == int(adjacency["edge_count"])
    assert int(adjacency["in_adjacency_edge_count"]) == int(adjacency["edge_count"])
    assert not adjacency.get("errors")

    shared = report["shared_adjacency_fixture"]
    assert shared["ok"] is True
    assert float(shared["reconciliation_rate"]) == 1.0
    assert int(shared["node_count"]) >= 1
    assert int(shared["edge_count"]) >= 1


def test_all_expected_paths_pass(report: dict[str, Any]) -> None:
    paths = report["paths"]
    assert paths["all_pass"] is True
    assert int(paths["expected_count"]) >= 8
    assert int(paths["matched_count"]) == int(paths["expected_count"])
    assert int(paths["failed_count"]) == 0
    assert not paths.get("failed")
    for item in paths["matches"]:
        assert item["matched"] is True
        assert item.get("matched_path") is not None


def test_unresolved_coverage_reported_not_discarded(report: dict[str, Any]) -> None:
    coverage = report["unresolved_coverage"]
    assert coverage["reported"] is True
    assert coverage["discarded"] is False
    assert int(coverage["unresolved_edge_count"]) >= 1
    assert int(coverage["unresolved_node_count"]) >= 1
    assert coverage["honesty_ok"] is True
    assert isinstance(coverage["samples"], list)
    assert coverage["samples"]

    citation = report["citation_resolution"]
    assert citation["reported"] is True
    assert citation["discarded"] is False
    assert citation["honesty_ok"] is True
    assert float(citation["unresolved_rate"]) >= 0.0
    assert citation["citation_parser_version"]


def test_error_coverage_reported_not_discarded(report: dict[str, Any]) -> None:
    errors = report["error_coverage"]
    assert errors["reported"] is True
    assert errors["discarded"] is False
    assert "error_count" in errors
    assert isinstance(errors["errors"], list)
    # Clean fixture evaluation should not surface integrity failures.
    assert int(errors["error_count"]) == 0


def test_source_evidence_and_semantics(report: dict[str, Any]) -> None:
    source = report["source_evidence"]
    assert source["source_evidence_bound"] is True
    assert int(source["missing_span_count"]) == 0
    assert int(source["inverted_span_count"]) == 0
    assert int(source["empty_text_count"]) == 0
    assert int(source["span_bound_count"]) == int(source["span_required_count"])

    semantics = report["semantics"]
    assert semantics["disjoint"] is True
    assert not semantics.get("collisions")
    assert int(semantics["legal_edge_count"]) >= 15
    # Similarity edges may be present but never collide with legal authority.
    assert int(semantics["similarity_edge_count"]) >= 0


def test_lexical_parity(report: dict[str, Any]) -> None:
    lexical = report["lexical_parity"]
    assert lexical["parity_ok"] is True
    assert lexical["all_cases_ok"] is True
    assert int(lexical["case_count"]) >= 5
    assert lexical["authority"] == "non_authoritative"
    assert not lexical.get("failed_cases")
    assert not lexical.get("errors")
    for case in lexical["cases"]:
        assert case["ok"] is True


def test_projection_counts_and_identity(report: dict[str, Any], ev: ModuleType) -> None:
    projection = report["projection"]
    assert int(projection["node_count"]) >= 20
    assert int(projection["edge_count"]) >= 15
    assert int(projection["legal_edge_count"]) >= 15
    assert int(projection["unresolved_count"]) >= 1
    assert projection["graph_cid"].startswith("sha256:")
    assert projection["ontology_version"]
    assert projection["schema_version"]
    assert report["evaluation_cid"].startswith("sha256:")
    assert report["schema_version"] == ev.REPORT_SCHEMA
    assert report["task_id"] == ev.TASK_ID
    assert report["goal_id"] == ev.GOAL_ID
    assert report["producer"] == ev.PRODUCER
    assert report["program_id"] == ev.PROGRAM_ID


def test_layout_inputs_are_durable_and_endpoint_complete(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    """Projection converts to a layout with no dangling durable endpoints."""

    from ipfs_datasets_py.processors.legal_data.uscode_graph import (
        load_graph_expected_fixture_payload,
        project_uscode_graph,
    )

    fixture = load_graph_expected_fixture_payload(_GRAPH_FIXTURE)
    projection = project_uscode_graph(
        fixture["records"],
        similarity_neighbors=fixture.get("similarity_neighbors") or [],
    )
    nodes, edges = ev.projection_to_layout_inputs(projection)
    node_cids = {n["node_cid"] for n in nodes}
    assert len(node_cids) == len(nodes)
    edge_cids = {e["edge_cid"] for e in edges}
    assert len(edge_cids) == len(edges)
    for edge in edges:
        assert edge["source_node_cid"] in node_cids
        assert edge["target_node_cid"] in node_cids

    layout = ev.build_projection_layout(projection)
    assert layout.node_count == len(nodes)
    assert layout.edge_count == len(edges)
    recon = ev.audit_adjacency_reconciliation(layout)
    assert recon["reconciled"] is True
    assert float(recon["reconciliation_rate"]) == 1.0


def test_evaluation_never_silently_repairs(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    """Integrity audit reports dangling endpoints without inventing nodes."""

    from ipfs_datasets_py.processors.legal_data.uscode_graph import (
        GraphEdgeClass,
        GraphEdgeType,
        GraphNodeType,
        SourceSpan,
        UscodeGraphEdge,
        UscodeGraphNode,
        UscodeGraphProjection,
    )

    # Minimal valid projection.
    n1 = UscodeGraphNode(
        node_type=GraphNodeType.SECTION,
        node_key="section:usc:us:1:1",
        legal_id="usc:us:1:1",
        label="§ 1",
    )
    n2 = UscodeGraphNode(
        node_type=GraphNodeType.SECTION,
        node_key="section:usc:us:1:2",
        legal_id="usc:us:1:2",
        label="§ 2",
    )
    mention = "1 U.S.C. § 2"
    good_edge = UscodeGraphEdge(
        edge_type=GraphEdgeType.CITES,
        source_node_cid=n1.node_cid,
        target_node_cid=n2.node_cid,
        edge_class=GraphEdgeClass.CITATION,
        source_span=SourceSpan(
            source_cid="sha256:" + ("a" * 64),
            start=0,
            end=len(mention),
            text=mention,
        ),
    )
    projection = UscodeGraphProjection(nodes=(n1, n2), edges=(good_edge,))
    integrity = ev.audit_duplicate_and_dangling(projection)
    assert integrity["zero_unexplained_dangling"] is True

    # Synthesize a dangling edge *outside* UscodeGraphProjection (which would
    # reject it) by auditing a hand-built mapping surface.
    class _Edge:
        edge_cid = "edge-dangling"
        edge_type = GraphEdgeType.CITES
        source_node_cid = n1.node_cid
        target_node_cid = "sha256:" + ("f" * 64)  # missing endpoint

    class _Proj:
        nodes = (n1, n2)
        edges = (_Edge(),)

    dangling = ev.audit_duplicate_and_dangling(_Proj())  # type: ignore[arg-type]
    assert dangling["unexplained_dangling_count"] == 1
    assert dangling["zero_unexplained_dangling"] is False
    # Audit does not invent a target node — only reports.
    assert dangling["dangling_edges"][0]["missing_target"] is True


def test_check_cli_entrypoint(ev: ModuleType, report: dict[str, Any]) -> None:
    rc = ev.main(["--fixture-only", "--check"])
    assert rc == 0
    assert _REPORT_PATH.is_file()
    on_disk = json.loads(_REPORT_PATH.read_text(encoding="utf-8"))
    ev.check_evaluation_report(on_disk)
    ev.check_report_matches_fixture(on_disk, report)


def test_frozen_report_schema_identity(report: dict[str, Any], ev: ModuleType) -> None:
    assert report["schema_version"] == ev.REPORT_SCHEMA
    assert report["task_id"] == ev.TASK_ID
    assert report["goal_id"] == ev.GOAL_ID
    assert report["producer"] == ev.PRODUCER
    assert report["release_profile"] == ev.RELEASE_PROFILE
    assert "fixtures" in report
    assert report["fixtures"]["graph"]["path"].endswith("uscode_graph_expected.json")
    assert report["fixtures"]["adjacency"]["path"].endswith("graph_adjacency.json")
    assert report["fixtures"]["lexical"]["path"].endswith("uscode_bm25_neighbors.json")
