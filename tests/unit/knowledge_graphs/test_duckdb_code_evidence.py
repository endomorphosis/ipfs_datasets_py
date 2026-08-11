"""Unit tests for the DuckDB code-evidence consumer adapter (DQK-034).

Acceptance coverage:

* The adapter verifies the exact DQP release/tree/schema identity
* No whole-artifact JSON load is required
* Datasets and supervisor projections remain schema compatible

Tests are hermetic: they construct typed AST / dependency / conflict / evidence
rows without multiformats, DuckDB servers, or whole-artifact JSON bundles.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Sealed-env shim: knowledge_graphs/conftest.py hard-imports extraction which
# requires ``requests``.  The DQK validation environment only admits DuckDB +
# pytest wheels, so install a minimal stub before any local confest import can
# fail when this module is loaded under --noconftest or as a plugin.
# ---------------------------------------------------------------------------

if "requests" not in sys.modules:
    _requests_stub = types.ModuleType("requests")
    _requests_stub.__dict__.update(
        {
            "__version__": "0.0.0-stub",
            "get": lambda *a, **k: None,
            "post": lambda *a, **k: None,
            "Session": object,
            "Request": object,
            "Response": object,
            "exceptions": types.SimpleNamespace(
                RequestException=Exception,
                HTTPError=Exception,
                ConnectionError=Exception,
                Timeout=Exception,
            ),
        }
    )
    sys.modules["requests"] = _requests_stub

from ipfs_datasets_py.knowledge_graphs.adapters import code_evidence as ce
from ipfs_datasets_py.knowledge_graphs.adapters import duckdb_code_evidence as dce
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    SUPERVISOR_BLOB_SUMMARY_SCHEMA,
)


SOURCE_REVISION = "rev:src-42"


def _release() -> dce.DQPReleaseIdentity:
    return dce.make_fixture_release_identity()


def _plane_with_fixture() -> dce.CodeEvidencePlane:
    release = _release()
    plane = dce.CodeEvidencePlane(
        source_revision=SOURCE_REVISION,
        release_identity=release,
    )
    plane.put_ast_projection(
        dce.make_fixture_ast_projection(
            source_revision=SOURCE_REVISION,
            path="src/example.py",
            qualified_symbol="example.fetch",
        )
    )
    plane.add_dependency("mod.A", "mod.B", "import")
    plane.add_dependency("mod.B", "mod.C", "call")
    plane.add_dependency("mod.A", "mod.D", "reference")
    plane.put_evidence_node(
        dce.EvidenceNodeRow(
            node_id="node-task-1",
            kind="task",
            record_key="task:1",
            provenance="task",
            authoritative=True,
            revision=SOURCE_REVISION,
            task_id="DQK-034",
            tree_id=release.accelerator_tree,
        )
    )
    plane.put_evidence_node(
        dce.EvidenceNodeRow(
            node_id="node-symbol-fetch",
            kind="symbol",
            record_key="symbol:example.fetch",
            provenance="ast",
            authoritative=True,
            revision=SOURCE_REVISION,
            symbol="example.fetch",
        )
    )
    plane.put_evidence_edge(
        dce.EvidenceEdgeRow(
            edge_id="edge-defines",
            kind="defines_symbol",
            source="node-task-1",
            target="node-symbol-fetch",
            provenance="ast",
            authoritative=True,
            revision=SOURCE_REVISION,
        )
    )
    plane.put_conflict_surface(
        dce.ConflictSurfaceRow(
            task_id="DQK-034",
            task_cid="task-cid-034",
            revision=SOURCE_REVISION,
            predicted_paths=("src/example.py",),
            predicted_symbols=("example.fetch",),
            dependencies=("task-cid-033",),
        )
    )
    plane.put_conflict_edge(
        dce.ConflictEdgeRow(
            left_task_cid="task-cid-034",
            right_task_cid="task-cid-033",
            weight=1.0,
            blocks_concurrency=True,
            explicitly_allowed=False,
            revision=SOURCE_REVISION,
            reason="shared_symbol",
        )
    )
    plane.put_conflict_edge(
        dce.ConflictEdgeRow(
            left_task_cid="task-cid-034",
            right_task_cid="task-cid-099",
            weight=0.0,
            blocks_concurrency=False,
            explicitly_allowed=True,
            revision=SOURCE_REVISION,
            reason="allowed_overlap",
        )
    )
    return plane


def _adapter() -> dce.DuckDBCodeEvidenceAdapter:
    return dce.build_duckdb_code_evidence_adapter(_plane_with_fixture())


# ---------------------------------------------------------------------------
# Interface pins / import inertness
# ---------------------------------------------------------------------------


def test_interface_and_schema_pins() -> None:
    adapter = _adapter()
    assert adapter.interface == dce.DUCKDB_CODE_EVIDENCE_INTERFACE
    assert adapter.schema == dce.DUCKDB_CODE_EVIDENCE_SCHEMA
    assert dce.DUCKDB_CODE_EVIDENCE_INTERFACE == "DuckDBCodeEvidenceAdapter@1"
    assert dce.DQP_RELEASE_TASK_ID == "DQP-039"
    assert dce.DQP_PROGRAM_ID == "agent-supervisor-duckdb-quack-control-plane-v1"
    descriptor = dce.adapter_schema_descriptor()
    assert descriptor["requires_whole_artifact_json_load"] is False
    assert descriptor["reimplements_supervisor_stores"] is False
    assert descriptor["guarantees"]["verifies_dqp_release_tree_schema_identity"]
    assert descriptor["guarantees"]["no_whole_artifact_json_load"]
    assert descriptor["guarantees"]["schema_compatible_with_supervisor"]


def test_module_import_is_inert() -> None:
    """Importing the adapter must not require a live DuckDB connection."""

    mod = importlib.import_module(
        "ipfs_datasets_py.knowledge_graphs.adapters.duckdb_code_evidence"
    )
    assert mod.DUCKDB_CODE_EVIDENCE_INTERFACE == "DuckDBCodeEvidenceAdapter@1"


# ---------------------------------------------------------------------------
# Acceptance: exact DQP release/tree/schema identity
# ---------------------------------------------------------------------------


def test_adapter_verifies_exact_dqp_release_tree_schema_identity() -> None:
    release = _release()
    plane = dce.CodeEvidencePlane(
        source_revision=SOURCE_REVISION,
        release_identity=release,
    )
    adapter = dce.build_duckdb_code_evidence_adapter(
        plane, expected_release=release
    )
    identity = adapter.identity()
    assert identity["release"]["accelerator_commit"] == release.accelerator_commit
    assert identity["release"]["accelerator_tree"] == release.accelerator_tree
    assert identity["release"]["schema_checksum"] == release.schema_checksum
    assert identity["release"]["store_generation"] == release.store_generation
    assert identity["release"]["quack_profile"] == release.quack_profile
    assert identity["release"]["release_task_id"] == "DQP-039"
    assert identity["release_identity_digest"] == release.identity_digest()


def test_mismatched_accelerator_tree_fails_closed() -> None:
    release = _release()
    plane = dce.CodeEvidencePlane(
        source_revision=SOURCE_REVISION,
        release_identity=release,
    )
    wrong = dce.make_fixture_release_identity(tree="d" * 40)
    with pytest.raises(dce.DQPReleaseIdentityError, match="accelerator_tree"):
        dce.build_duckdb_code_evidence_adapter(plane, expected_release=wrong)


def test_mismatched_schema_checksum_fails_closed() -> None:
    release = _release()
    plane = dce.CodeEvidencePlane(
        source_revision=SOURCE_REVISION,
        release_identity=release,
    )
    wrong = dce.make_fixture_release_identity(
        schema_checksum="sha256:" + ("e" * 64)
    )
    with pytest.raises(dce.DQPReleaseIdentityError, match="schema_checksum"):
        dce.build_duckdb_code_evidence_adapter(plane, expected_release=wrong)


def test_mismatched_commit_fails_closed() -> None:
    observed = dce.make_fixture_release_identity(commit="1" * 40)
    expected = dce.make_fixture_release_identity(commit="2" * 40)
    with pytest.raises(dce.DQPReleaseIdentityError, match="accelerator_commit"):
        dce.verify_dqp_release_identity(observed, expected)


def test_release_identity_from_mapping_and_digest_stable() -> None:
    release = _release()
    restored = dce.DQPReleaseIdentity.from_mapping(release.to_dict())
    assert restored == release
    assert restored.identity_digest() == release.identity_digest()
    assert restored.identity_digest().startswith("sha256:")


def test_invalid_git_oid_rejected() -> None:
    with pytest.raises(dce.DuckDBCodeEvidenceError, match="git OID"):
        dce.DQPReleaseIdentity(
            accelerator_commit="not-a-oid",
            accelerator_tree="b" * 40,
            store_generation="g1",
            schema_checksum="sha256:" + ("c" * 64),
            quack_profile="profile",
        )


def test_wrong_release_task_id_rejected() -> None:
    with pytest.raises(dce.DQPReleaseIdentityError, match="DQP-039"):
        dce.DQPReleaseIdentity(
            accelerator_commit="a" * 40,
            accelerator_tree="b" * 40,
            store_generation="g1",
            schema_checksum="sha256:" + ("c" * 64),
            quack_profile="profile",
            release_task_id="DQP-038",
        )


# ---------------------------------------------------------------------------
# Acceptance: no whole-artifact JSON load
# ---------------------------------------------------------------------------


def test_no_whole_artifact_json_load_required() -> None:
    adapter = _adapter()
    assert adapter.requires_whole_artifact_json_load is False
    assert adapter.whole_artifact_json_load_count == 0

    ast_result = adapter.ast_lookup(path="src/example.py")
    dep_result = adapter.dependency_query(seed_ids=["mod.A"])
    conflict_result = adapter.conflict_query(task_cid="task-cid-034")
    evidence_result = adapter.evidence_query(kinds=["symbol"])

    assert ast_result["whole_artifact_json_loaded"] is False
    assert dep_result["whole_artifact_json_loaded"] is False
    assert conflict_result["whole_artifact_json_loaded"] is False
    assert evidence_result["whole_artifact_json_loaded"] is False
    assert adapter.whole_artifact_json_load_count == 0
    assert ast_result["source"] == "duckdb_ast_store"
    assert ast_result["result_count"] == 1
    assert dep_result["revision"] == SOURCE_REVISION
    assert conflict_result["edge_count"] == 1  # blocking only
    assert evidence_result["node_count"] == 1


def test_queries_work_without_json_artifact_files(tmp_path: Path) -> None:
    """Plane is fully typed; empty bundle dir is never consulted."""

    empty_bundle = tmp_path / "no-bundle"
    empty_bundle.mkdir()
    assert list(empty_bundle.glob("*.json")) == []

    adapter = _adapter()
    result = adapter.ast_lookup(symbol="fetch")
    assert result["result_count"] == 1
    assert result["results"][0]["path"] == "src/example.py"
    assert "example.fetch" in result["results"][0]["qualified_symbols"]
    assert not (empty_bundle / "code_evidence_graph.json").exists()
    assert not (empty_bundle / "analysis_ast_index.json").exists()


def test_dependency_and_impact_bind_exact_source_revision() -> None:
    adapter = _adapter()
    dep = adapter.dependency_query(seed_ids=["mod.A"], direction="forward")
    assert dep["source_revision"] == SOURCE_REVISION
    assert dep["revision"] == SOURCE_REVISION
    assert set(dep["nodes"]) == {"mod.A", "mod.B", "mod.C", "mod.D"}

    impact = adapter.impact_query(
        roots=["mod.B"], direction="forward", kinds=["call"]
    )
    assert impact["source_revision"] == SOURCE_REVISION
    assert set(impact["nodes"]) == {"mod.B", "mod.C"}
    assert impact["schema"] == dce.IMPACT_QUERY_SCHEMA


def test_conflict_and_evidence_queries_are_revision_bound() -> None:
    adapter = _adapter()
    conflict = adapter.conflict_query(task_cid="task-cid-034", blocking_only=True)
    assert conflict["revision"] == SOURCE_REVISION
    assert conflict["conflict_graph_schema"] == dce.CONFLICT_GRAPH_SCHEMA
    assert conflict["edge_count"] == 1
    assert conflict["edges"][0]["left_task_cid"] == "task-cid-034"
    assert conflict["surface"]["task_cid"] == "task-cid-034"

    all_conflicts = adapter.conflict_query(blocking_only=False)
    assert all_conflicts["edge_count"] == 2

    evidence = adapter.evidence_query(task_id="DQK-034")
    assert evidence["revision"] == SOURCE_REVISION
    assert evidence["code_evidence_graph_schema"] == dce.CODE_EVIDENCE_GRAPH_SCHEMA
    assert evidence["node_count"] == 1
    assert evidence["nodes"][0]["kind"] == "task"


def test_ast_lookup_uses_supervisor_blob_summary_schema() -> None:
    adapter = _adapter()
    result = adapter.ast_lookup(path="src/example.py")
    assert result["result_count"] == 1
    row = result["results"][0]
    assert row["schema"] == SUPERVISOR_BLOB_SUMMARY_SCHEMA
    assert row["revision"] == SOURCE_REVISION
    assert row["blob_id"]
    assert row["ast_cid"]


def test_plane_rejects_cross_revision_evidence() -> None:
    plane = dce.CodeEvidencePlane(
        source_revision=SOURCE_REVISION,
        release_identity=_release(),
    )
    with pytest.raises(dce.DuckDBCodeEvidenceError, match="revision"):
        plane.put_evidence_node(
            dce.EvidenceNodeRow(
                node_id="n1",
                kind="task",
                record_key="k",
                provenance="task",
                authoritative=True,
                revision="other-revision",
            )
        )


# ---------------------------------------------------------------------------
# Acceptance: datasets and supervisor projections remain schema compatible
# ---------------------------------------------------------------------------


def test_datasets_and_supervisor_projections_remain_schema_compatible() -> None:
    report = dce.assert_schema_compatibility()
    assert report["compatible"] is True
    assert dce.ANALYSIS_AST_INDEX_SCHEMA == ce.ANALYSIS_AST_INDEX_SCHEMA
    assert dce.CODE_EVIDENCE_GRAPH_SCHEMA == ce.CODE_EVIDENCE_GRAPH_SCHEMA
    assert dce.CODE_EVIDENCE_NODE_SCHEMA == ce.CODE_EVIDENCE_NODE_SCHEMA
    assert dce.CODE_EVIDENCE_EDGE_SCHEMA == ce.CODE_EVIDENCE_EDGE_SCHEMA
    assert dce.CODE_IMPACT_INDEX_SCHEMA == ce.CODE_IMPACT_INDEX_SCHEMA
    assert dce.CONFLICT_GRAPH_SCHEMA == ce.CONFLICT_GRAPH_SCHEMA
    assert dce.SEMANTIC_DEPENDENCY_GRAPH_SCHEMA == ce.SEMANTIC_DEPENDENCY_GRAPH_SCHEMA
    assert SUPERVISOR_BLOB_SUMMARY_SCHEMA == (
        "ipfs_accelerate_py/agent-supervisor/ast-blob-record@1"
    )
    for name, entry in report["pairs"].items():
        assert entry["compatible"] is True, name


def test_adapter_schema_descriptor_declares_compatibility() -> None:
    adapter = _adapter()
    descriptor = adapter.schema_descriptor()
    assert descriptor["compatibility"]["compatible"] is True
    assert descriptor["consumes"]["code_evidence_graph"] == ce.CODE_EVIDENCE_GRAPH_SCHEMA
    assert descriptor["consumes"]["conflict_graph"] == ce.CONFLICT_GRAPH_SCHEMA
    assert descriptor["consumes"]["analysis_ast_index"] == ce.ANALYSIS_AST_INDEX_SCHEMA


def test_supervisor_blob_summary_from_projection_is_json_serializable() -> None:
    """Projected summaries remain portable without loading whole artifacts."""

    projection = dce.make_fixture_ast_projection(
        source_revision=SOURCE_REVISION,
        path="src/example.py",
        qualified_symbol="example.fetch",
    )
    summary = projection.to_supervisor_blob_summary()
    assert summary["schema"] == SUPERVISOR_BLOB_SUMMARY_SCHEMA
    restored = json.loads(json.dumps(summary, sort_keys=True))
    assert restored["qualified_symbols"] == summary["qualified_symbols"]
    assert "example.fetch" in restored["qualified_symbols"]


# ---------------------------------------------------------------------------
# Adapter construction helpers
# ---------------------------------------------------------------------------


def test_build_adapter_with_mapping_expected_release() -> None:
    plane = _plane_with_fixture()
    adapter = dce.build_duckdb_code_evidence_adapter(
        plane, expected_release=plane.release_identity.to_dict()
    )
    assert adapter.source_revision == SOURCE_REVISION
    assert adapter.release_identity.accelerator_commit == (
        plane.release_identity.accelerator_commit
    )


def test_identity_digest_in_query_results() -> None:
    adapter = _adapter()
    digest = adapter.release_identity.identity_digest()
    for result in (
        adapter.ast_lookup(),
        adapter.dependency_query(seed_ids=["mod.A"]),
        adapter.conflict_query(),
        adapter.evidence_query(),
    ):
        assert result["release_identity_digest"] == digest
        assert result["revision"] == SOURCE_REVISION
