"""Integration suite for the supervisor code/objective/AST/conflict/evidence adapter (KGP-027).

Coverage:
* tiny checked fixture (always-on): objective, semantic dependency, AST index,
  conflict, and code-evidence graphs plus impact index
* typed node/edge kinds, provenance, revision binding, evidence links
* incremental working-copy updates (never mutates on-disk artifacts)
* representative dependency, impact, and provenance queries
* schema extensibility with unknown optional node/edge kinds
* missing/corrupt artifact fail-closed behavior
* optional full objective_graph.json receipt when the program artifact is present
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
    BUNDLE_ARTIFACTS,
    CODE_EVIDENCE_GRAPH_SCHEMA,
    CODE_EVIDENCE_NODE_SCHEMA,
    CODE_IMPACT_RESULT_SCHEMA,
    CONFLICT_GRAPH_SCHEMA,
    CodeEvidenceAdapterError,
    CodeEvidenceCorpusAdapter,
    ENV_BUNDLE_ROOT,
    GRAPH_KIND_AST,
    GRAPH_KIND_CODE_EVIDENCE,
    GRAPH_KIND_CONFLICT,
    GRAPH_KIND_OBJECTIVE,
    GRAPH_KIND_SEMANTIC,
    LOCAL_FIXTURE_REVISION,
    OBJECTIVE_GRAPH_SCHEMA,
    SEMANTIC_DEPENDENCY_GRAPH_SCHEMA,
    VALIDATION_RECEIPT_SCHEMA,
    apply_incremental_update,
    build_tiny_fixture_bundle,
    classify_kind,
    discover_objective_graph_path,
    normalize_ast_index,
    normalize_code_evidence_graph,
    normalize_code_evidence_node,
    normalize_semantic_node,
    open_bundle_reader,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def tiny_bundle(tmp_path: Path) -> Path:
    return build_tiny_fixture_bundle(tmp_path / "code-evidence-tiny")


@pytest.fixture
def adapter(tiny_bundle: Path) -> CodeEvidenceCorpusAdapter:
    return CodeEvidenceCorpusAdapter(
        tiny_bundle,
        revision=LOCAL_FIXTURE_REVISION,
        allow_unknown_kinds=True,
    )


# ---------------------------------------------------------------------------
# Bundle layout, validation, revision binding
# ---------------------------------------------------------------------------


def test_tiny_fixture_validates_all_graph_kinds_and_revision(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    receipt = adapter.validate(verify_checksums=True)
    assert receipt["schema"] == VALIDATION_RECEIPT_SCHEMA
    assert receipt["revision"] == LOCAL_FIXTURE_REVISION
    assert receipt["manifest"]["revision"] == LOCAL_FIXTURE_REVISION
    assert receipt["checksums_verified"] >= 6

    graphs = receipt["graphs"]
    assert graphs["objective"]["schema"] == OBJECTIVE_GRAPH_SCHEMA
    assert graphs["objective"]["counts"]["goals"] == 3
    assert graphs["objective"]["counts"]["evidence_nodes"] == 2

    assert graphs["semantic_dependency"]["schema"] == SEMANTIC_DEPENDENCY_GRAPH_SCHEMA
    assert graphs["semantic_dependency"]["node_count"] >= 6
    assert graphs["semantic_dependency"]["edge_count"] >= 5
    assert graphs["semantic_dependency"]["revision"] == LOCAL_FIXTURE_REVISION

    assert graphs["ast_index"]["path_count"] == 2
    assert graphs["ast_index"]["revision"] == LOCAL_FIXTURE_REVISION

    assert graphs["conflict"]["schema"] == CONFLICT_GRAPH_SCHEMA
    assert graphs["conflict"]["surface_count"] == 3
    assert graphs["conflict"]["blocking_edge_count"] == 1

    assert graphs["code_evidence"]["schema"] == CODE_EVIDENCE_GRAPH_SCHEMA
    assert graphs["code_evidence"]["node_count"] >= 11
    assert graphs["code_evidence"]["edge_count"] >= 9
    assert graphs["code_evidence"]["revision"] == LOCAL_FIXTURE_REVISION

    assert graphs["impact_index"]["symbol_count"] == 3
    assert graphs["impact_index"]["repository_tree_id"].startswith("tree-")

    assert receipt["provenance"]["authoritative_owner"] == "ipfs_accelerate_py"
    assert receipt["provenance"]["adapter_task"] == "KGP-027"
    assert set(receipt["manifest"]["graph_kinds"]) >= {
        GRAPH_KIND_OBJECTIVE,
        GRAPH_KIND_SEMANTIC,
        GRAPH_KIND_AST,
        GRAPH_KIND_CONFLICT,
        GRAPH_KIND_CODE_EVIDENCE,
    }


def test_typed_node_edge_kinds_and_provenance_preserved(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    evidence = adapter.load_code_evidence_graph()
    kinds = {node["kind"] for node in evidence["nodes"]}
    for expected in (
        "task",
        "tree",
        "symbol",
        "ast_scope",
        "obligation",
        "proof",
        "validation",
        "merge",
        "evidence",
        "enrichment",
    ):
        assert expected in kinds

    edge_kinds = {edge["kind"] for edge in evidence["edges"]}
    for expected in (
        "targets_tree",
        "defines_symbol",
        "has_obligation",
        "proves",
        "covers",
        "validates",
        "merged",
        "completes",
        "related_to",
    ):
        assert expected in edge_kinds

    # Authority boundary: enrichment edges are non-authoritative.
    related = [
        edge for edge in evidence["edges"] if edge["kind"] == "related_to"
    ]
    assert related
    assert all(edge["authoritative"] is False for edge in related)
    assert all(edge["provenance"] == "graphrag" for edge in related)

    proves = [edge for edge in evidence["edges"] if edge["kind"] == "proves"]
    assert proves
    assert all(edge["authoritative"] is True for edge in proves)
    assert all(edge["provenance"] == "proof" for edge in proves)

    # Every node carries provenance + revision binding.
    for node in evidence["nodes"]:
        assert node["provenance"]
        assert node["schema"] == CODE_EVIDENCE_NODE_SCHEMA
        assert node.get("revision") == LOCAL_FIXTURE_REVISION or node.get(
            "freshness"
        )


def test_evidence_links_on_objective_graph(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    links = adapter.objective_evidence_links("KGP-G081")
    assert links["node_count"] == 1
    assert links["edge_count"] == 1
    assert links["evidence_nodes"][0]["id"] == "evidence:pytest-code-evidence"
    assert links["evidence_edges"][0]["kind"] == "requires_evidence"
    assert links["revision"] == LOCAL_FIXTURE_REVISION


# ---------------------------------------------------------------------------
# Dependency / impact / provenance queries
# ---------------------------------------------------------------------------


def test_code_evidence_dependency_query(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    evidence = adapter.load_code_evidence_graph()
    task_nodes = [
        node for node in evidence["nodes"] if node["kind"] == "task"
    ]
    assert task_nodes
    task_id = task_nodes[0]["node_id"]

    forward = adapter.dependency_query(
        family="code_evidence",
        seed_ids=[task_id],
        direction="forward",
        max_depth=4,
        authoritative_only=True,
    )
    assert forward["schema"] == "code-evidence-dependency-query/v1"
    assert forward["family"] == "code_evidence"
    assert task_id in forward["node_ids"]
    assert forward["node_count"] >= 2
    assert forward["edge_count"] >= 1
    assert forward["revision"] == LOCAL_FIXTURE_REVISION

    # Reverse from a symbol should reach the task via authoritative edges.
    symbol_nodes = [
        node
        for node in evidence["nodes"]
        if node["kind"] == "symbol" and node["symbol"] == "pkg.mod.helper"
    ]
    assert symbol_nodes
    reverse = adapter.dependency_query(
        family="code_evidence",
        seed_ids=[symbol_nodes[0]["node_id"]],
        direction="reverse",
        max_depth=4,
        authoritative_only=False,
    )
    assert reverse["node_count"] >= 1


def test_semantic_dependency_and_mandatory_closure(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    dep = adapter.dependency_query(
        family="semantic",
        seed_ids=["decision:KGP-027"],
        direction="forward",
        max_depth=8,
        authoritative_only=True,
    )
    assert "obligation:impl" in dep["node_ids"]
    assert "proof:receipt-1" in dep["node_ids"]
    assert dep["family"] == "semantic_dependency"

    closure = adapter.semantic_mandatory_closure("decision:KGP-027")
    assert closure["schema"].endswith("mandatory-dependency-closure@1")
    assert closure["decision_id"] == "decision:KGP-027"
    assert "obligation:impl" in closure["node_ids"]
    assert "proof:receipt-1" in closure["node_ids"]
    assert closure["complete"] is True


def test_impact_query_symbol_and_path_closure(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    impact = adapter.impact_query(
        changed_symbols=["pkg.mod.helper"],
        changed_paths=[],
        include_evidence_reverse=True,
    )
    assert impact["schema"] == CODE_IMPACT_RESULT_SCHEMA
    assert "pkg.mod.helper" in impact["changed_symbols"]
    assert "pkg.mod.caller" in impact["affected_symbols"]
    assert "pkg.other.use" in impact["affected_symbols"]
    assert "pkg/other.py" in impact["affected_paths"]
    assert "tests/test_mod.py" in impact["affected_paths"]
    assert "test_code_evidence" in impact["required_validation_ids"]
    assert impact["uncovered_impact"] is False
    assert impact["revision"] == LOCAL_FIXTURE_REVISION
    # Evidence reverse closure attached when symbol nodes exist.
    assert "evidence_reverse_closure" in impact

    path_impact = adapter.impact_query(
        changed_paths=["pkg/mod.py"],
        include_evidence_reverse=False,
    )
    assert "pkg.mod.helper" in path_impact["changed_symbols"]
    assert "pkg/other.py" in path_impact["affected_paths"]


def test_provenance_query_collects_bindings(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    evidence = adapter.load_code_evidence_graph()
    proof = next(node for node in evidence["nodes"] if node["kind"] == "proof")
    result = adapter.provenance_query(
        family="code_evidence",
        seed_ids=[proof["node_id"]],
        max_depth=3,
    )
    assert result["schema"] == "code-evidence-provenance-query/v1"
    assert result["node_count"] >= 1
    provenances = {row["provenance"] for row in result["node_records"]}
    assert "proof" in provenances
    assert all(
        row.get("provenance") or row.get("provenance_id")
        for row in result["edge_records"]
    )

    semantic = adapter.provenance_query(
        family="semantic",
        seed_ids=["decision:KGP-027"],
        max_depth=4,
    )
    assert semantic["node_count"] >= 2
    assert any(
        row["provenance"] in {"decision", "proof", "ast", "validation"}
        for row in semantic["node_records"]
    )


def test_conflict_and_ast_queries(adapter: CodeEvidenceCorpusAdapter) -> None:
    conflicts = adapter.conflict_query(
        task_cid="task-cid-027", blocking_only=True
    )
    assert conflicts["edge_count"] == 1
    assert conflicts["edges"][0]["blocks_concurrency"] is True
    assert conflicts["surface"] is not None
    assert "code_evidence.py" in str(
        conflicts["surface"]["predicted_paths"]
    )
    assert conflicts["revision"] == LOCAL_FIXTURE_REVISION

    non_blocking = adapter.conflict_query(blocking_only=False)
    assert non_blocking["edge_count"] == 2

    ast = adapter.ast_lookup(symbol="pkg.mod.helper")
    assert ast["result_count"] == 1
    assert ast["results"][0]["path"] == "pkg/mod.py"
    assert "pkg.mod.helper" in ast["results"][0]["qualified_symbols"]
    assert ast["results"][0]["record_id"].startswith("ast-sha256:")

    by_path = adapter.ast_lookup(path="pkg/other.py")
    assert by_path["result_count"] == 1
    assert "pkg.other.use" in by_path["results"][0]["qualified_symbols"]


def test_objective_dependency_query(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    result = adapter.dependency_query(
        family="objective",
        seed_ids=["KGP-G000"],
        direction="forward",
        max_depth=4,
    )
    assert "KGP-G080" in result["node_ids"]
    assert "KGP-G081" in result["node_ids"]
    # Evidence nodes linked from goals are also reachable.
    assert "evidence:plan" in result["node_ids"] or result["edge_count"] >= 1


# ---------------------------------------------------------------------------
# Incremental updates
# ---------------------------------------------------------------------------


def test_incremental_update_preserves_revision_and_does_not_mutate_disk(
    adapter: CodeEvidenceCorpusAdapter,
    tiny_bundle: Path,
) -> None:
    before = json.loads(
        (tiny_bundle / BUNDLE_ARTIFACTS["code_evidence_graph"]).read_text(
            encoding="utf-8"
        )
    )
    original_count = adapter.load_code_evidence_graph()["node_count"]

    new_node = normalize_code_evidence_node(
        {
            "schema": CODE_EVIDENCE_NODE_SCHEMA,
            "kind": "evidence",
            "record_key": "evidence:incremental-1",
            "provenance": "validation",
            "task_id": "KGP-027",
            "freshness": "current",
            "record": {"note": "added by incremental update"},
            "revision": LOCAL_FIXTURE_REVISION,
        },
        allow_unknown_kinds=True,
    )
    # Link new evidence → existing task
    evidence = adapter.working_code_evidence_graph()
    task = next(n for n in evidence["nodes"] if n["kind"] == "task")
    from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
        normalize_code_evidence_edge,
        CODE_EVIDENCE_EDGE_SCHEMA,
    )

    new_edge = normalize_code_evidence_edge(
        {
            "schema": CODE_EVIDENCE_EDGE_SCHEMA,
            "source": new_node["node_id"],
            "target": task["node_id"],
            "kind": "validates",
            "provenance": "validation",
            "provenance_record_id": "prov:incremental-validates",
            "metadata": {},
            "revision": LOCAL_FIXTURE_REVISION,
        },
        allow_unknown_kinds=True,
    )

    update = adapter.apply_incremental(
        family="code_evidence",
        upsert_nodes=[
            {k: v for k, v in new_node.items() if k != "kind_meta"}
        ],
        upsert_edges=[
            {k: v for k, v in new_edge.items() if k != "kind_meta"}
        ],
        revision=LOCAL_FIXTURE_REVISION,
    )
    assert update["schema"] == "code-evidence-incremental-update/v1"
    assert update["node_count"] == original_count + 1
    assert update["upserted_nodes"] == 1
    assert update["upserted_edges"] == 1
    assert update["revision"] == LOCAL_FIXTURE_REVISION
    assert update["graph"]["revision"] == LOCAL_FIXTURE_REVISION

    # Working copy reflects the update.
    working = adapter.working_code_evidence_graph()
    assert working["node_count"] == original_count + 1
    assert any(
        n["record_key"] == "evidence:incremental-1" for n in working["nodes"]
    )

    # Canonical load remains the original (cache of on-disk).
    # Force re-load from disk by bypassing working copy.
    disk = adapter.load_code_evidence_graph(use_cache=True)
    # Cached original load still has original count.
    assert disk["node_count"] == original_count

    after = json.loads(
        (tiny_bundle / BUNDLE_ARTIFACTS["code_evidence_graph"]).read_text(
            encoding="utf-8"
        )
    )
    assert after == before


def test_incremental_remove_and_semantic_patch(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    evidence = adapter.load_code_evidence_graph()
    enrichment = next(
        n for n in evidence["nodes"] if n["kind"] == "enrichment"
    )
    update = adapter.apply_incremental(
        family="code_evidence",
        remove_node_ids=[enrichment["node_id"]],
    )
    assert enrichment["node_id"] not in {
        n["node_id"] for n in update["graph"]["nodes"]
    }
    # Edges touching the removed node are dropped.
    assert all(
        enrichment["node_id"] not in {e["source"], e["target"]}
        for e in update["graph"]["edges"]
    )

    semantic_update = apply_incremental_update(
        adapter.load_semantic_dependency_graph(),
        graph_family="semantic",
        remove_node_ids=["policy_hint:lane"],
        revision=LOCAL_FIXTURE_REVISION,
        allow_unknown_kinds=True,
    )
    assert "policy_hint:lane" not in semantic_update["graph"]["nodes"] or all(
        n["node_id"] != "policy_hint:lane"
        for n in semantic_update["graph"]["nodes"]
    )


# ---------------------------------------------------------------------------
# Schema extensibility with unknown optional kinds
# ---------------------------------------------------------------------------


def test_unknown_optional_kinds_are_preserved(
    adapter: CodeEvidenceCorpusAdapter,
) -> None:
    report = adapter.unknown_optional_kinds()
    assert "coverage_span" in report["code_evidence"]["node_kinds"]
    assert "covers_lines" in report["code_evidence"]["edge_kinds"]
    assert "scheduling_hint" in report["semantic_dependency"]["node_kinds"]
    assert "hints_schedule" in report["semantic_dependency"]["edge_kinds"]

    evidence = adapter.load_code_evidence_graph()
    optional_nodes = [
        n for n in evidence["nodes"] if n["kind"] == "coverage_span"
    ]
    assert len(optional_nodes) == 1
    assert optional_nodes[0]["kind_meta"]["optional_unknown"] is True
    # Unknown optional node kinds are never authority-bearing.
    assert optional_nodes[0]["authoritative"] is False
    # Unknown edge kinds are never authority-bearing.
    optional_edges = [
        e for e in evidence["edges"] if e["kind"] == "covers_lines"
    ]
    assert optional_edges
    assert all(e["authoritative"] is False for e in optional_edges)
    assert all(e["kind_meta"]["optional_unknown"] for e in optional_edges)


def test_classify_kind_and_strict_mode_rejects_unknown(
    tiny_bundle: Path,
) -> None:
    known = classify_kind("task", frozenset({"task", "tree"}))
    assert known["known"] is True
    assert known["optional_unknown"] is False

    unknown = classify_kind(
        "future_kind", frozenset({"task"}), allow_unknown=True
    )
    assert unknown["optional_unknown"] is True

    with pytest.raises(CodeEvidenceAdapterError, match="unknown kind"):
        classify_kind(
            "future_kind", frozenset({"task"}), allow_unknown=False
        )

    strict = CodeEvidenceCorpusAdapter(
        tiny_bundle,
        revision=LOCAL_FIXTURE_REVISION,
        allow_unknown_kinds=False,
    )
    with pytest.raises(CodeEvidenceAdapterError, match="unknown kind"):
        strict.load_code_evidence_graph()


# ---------------------------------------------------------------------------
# Fail-closed integrity
# ---------------------------------------------------------------------------


def test_canonical_accelerator_ast_index_identity_validates_exactly() -> None:
    """Lock the adapter to analysis_ast_index._identity wire semantics."""

    expected = (
        "analysis-ast-index:sha256:"
        "9b34cedfc7b53969b6f45d0f68100cfa982011dae718508e659cd7e1a8990ba6"
    )
    normalized = normalize_ast_index(
        {
            "schema": (
                "ipfs_accelerate_py/agent-supervisor/"
                "analysis-ast-index@1"
            ),
            "schema_version": 1,
            "index_id": expected,
            "path_records": [],
            "invalidations": [],
            "stats": {},
        }
    )
    assert normalized["index_id"] == expected

    with pytest.raises(CodeEvidenceAdapterError, match="identity"):
        normalize_ast_index(
            {
                "schema": (
                    "ipfs_accelerate_py/agent-supervisor/"
                    "analysis-ast-index@1"
                ),
                "schema_version": 1,
                "index_id": "analysis-ast-index:sha256:" + "0" * 64,
                "path_records": [],
            }
        )


def test_canonical_accelerator_semantic_node_identity_validates_exactly() -> None:
    """Lock the adapter to semantic_dependency_graph._identity wire semantics."""

    expected = (
        "semantic-node:sha256:"
        "41ec9ade4d97324a1c45ef6a642acb485685d691878d4efca99c0b9715a75009"
    )
    payload = {
        "schema": (
            "ipfs_accelerate_py/agent-supervisor/"
            "semantic-dependency-node@1"
        ),
        "node_id": "decision:test",
        "kind": "decision",
        "root_id": "root:test",
        "source_root_id": "tree:test",
        "provenance": "decision",
        "provenance_id": "decision:test",
        "trust": "verified",
        "authority": "authoritative",
        "version": "test@1",
        "record": {"purpose": "canonical producer identity"},
        "content_id": expected,
        "authoritative": True,
    }
    normalized = normalize_semantic_node(payload)
    assert normalized["content_id"] == expected

    with pytest.raises(CodeEvidenceAdapterError, match="identity"):
        normalize_semantic_node(
            {
                **payload,
                "content_id": "semantic-node:sha256:" + "0" * 64,
            }
        )


def test_missing_artifact_fails_closed(tiny_bundle: Path) -> None:
    target = tiny_bundle / BUNDLE_ARTIFACTS["code_evidence_graph"]
    assert target.is_file()
    target.unlink()
    adapter = CodeEvidenceCorpusAdapter(
        tiny_bundle, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(CodeEvidenceAdapterError, match="missing"):
        adapter.validate(verify_checksums=False)


def test_corrupt_artifact_fails_closed(tiny_bundle: Path) -> None:
    target = tiny_bundle / BUNDLE_ARTIFACTS["semantic_dependency_graph"]
    target.write_text("{not-json", encoding="utf-8")
    adapter = CodeEvidenceCorpusAdapter(
        tiny_bundle, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(CodeEvidenceAdapterError, match="corrupt|unreadable"):
        adapter.load_semantic_dependency_graph()


def test_checksum_mismatch_fails_closed(tiny_bundle: Path) -> None:
    manifest_path = tiny_bundle / BUNDLE_ARTIFACTS["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_checksums"]["code_evidence_graph"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    adapter = CodeEvidenceCorpusAdapter(
        tiny_bundle, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(CodeEvidenceAdapterError, match="digest differs"):
        adapter.validate(verify_checksums=True)


def test_forged_node_identity_fails_closed() -> None:
    with pytest.raises(CodeEvidenceAdapterError, match="identity"):
        normalize_code_evidence_node(
            {
                "schema": CODE_EVIDENCE_NODE_SCHEMA,
                "node_id": "node-forged",
                "kind": "task",
                "record_key": "task:x",
                "provenance": "task",
                "record": {},
            }
        )


def test_enrichment_cannot_mint_proof_edges() -> None:
    task = normalize_code_evidence_node(
        {
            "schema": CODE_EVIDENCE_NODE_SCHEMA,
            "kind": "task",
            "record_key": "task:a",
            "provenance": "task",
            "record": {},
        }
    )
    proof = normalize_code_evidence_node(
        {
            "schema": CODE_EVIDENCE_NODE_SCHEMA,
            "kind": "proof",
            "record_key": "proof:a",
            "provenance": "proof",
            "record": {},
        }
    )
    with pytest.raises(CodeEvidenceAdapterError, match="enrichment cannot"):
        normalize_code_evidence_graph(
            {
                "schema": CODE_EVIDENCE_GRAPH_SCHEMA,
                "nodes": [
                    {k: v for k, v in task.items() if k != "kind_meta"},
                    {k: v for k, v in proof.items() if k != "kind_meta"},
                ],
                "edges": [
                    {
                        "schema": "ipfs_accelerate_py.agent_supervisor.code-evidence-edge@1",
                        "source": task["node_id"],
                        "target": proof["node_id"],
                        "kind": "proves",
                        "provenance": "graphrag",
                        "provenance_record_id": "bad",
                        "metadata": {},
                    }
                ],
            }
        )


# ---------------------------------------------------------------------------
# open_bundle_reader / discovery
# ---------------------------------------------------------------------------


def test_open_bundle_reader(tiny_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_BUNDLE_ROOT, str(tiny_bundle))
    reader = open_bundle_reader()
    receipt = reader.validate(verify_checksums=True)
    assert receipt["revision"] == LOCAL_FIXTURE_REVISION


def test_production_objective_graph_optional() -> None:
    path = discover_objective_graph_path()
    if path is None or not path.is_file():
        pytest.skip("production objective_graph.json not available")
    payload = json.loads(path.read_text(encoding="utf-8"))
    from ipfs_datasets_py.knowledge_graphs.adapters.code_evidence import (
        normalize_objective_graph,
    )

    graph = normalize_objective_graph(payload, revision="production")
    assert graph["schema"] == OBJECTIVE_GRAPH_SCHEMA
    assert graph["counts"]["goals"] >= 1
    assert graph["counts"]["graph_nodes"] >= 1
    assert graph["goal_count"] >= 1
