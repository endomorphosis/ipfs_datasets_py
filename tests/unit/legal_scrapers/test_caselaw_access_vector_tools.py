"""Tests for CAP legal vector dataset API wiring and metadata specs."""

from __future__ import annotations

import importlib.util
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, relative_path: str):
    """Load a module directly from file path to avoid package side-effect imports."""
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legal_dataset_api = _load_module(
    "legal_dataset_api_under_test",
    "ipfs_datasets_py/processors/legal_scrapers/legal_dataset_api.py",
)
mcp_tools = _load_module(
    "legal_dataset_mcp_tools_under_test",
    "ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/mcp_tools.py",
)
vector_search_integration = _load_module(
    "cap_vector_search_integration_under_test",
    "ipfs_datasets_py/processors/legal_scrapers/caselaw_access_program/vector_search_integration.py",
)
tool_registration = importlib.import_module("ipfs_datasets_py.mcp_server.tools.tool_registration")

CAP_LEGAL_DATASET_TOOL_SPECS = mcp_tools.CAP_LEGAL_DATASET_TOOL_SPECS
get_cap_legal_dataset_tool_specs = mcp_tools.get_cap_legal_dataset_tool_specs
TOOL_MAPPINGS = tool_registration.TOOL_MAPPINGS


@pytest.mark.anyio
async def test_ingest_bundle_requires_collection_names() -> None:
    """Bundle ingest should fail fast when required collection names are missing."""
    result = await legal_dataset_api.ingest_caselaw_access_vector_bundle_from_parameters(
        {"auto_setup_venv": False}
    )

    assert result["status"] == "error"
    assert result["operation"] == "ingest_bundle"
    assert "target_collection_name" in result["error"]
    assert "centroid_collection_name" in result["error"]


@pytest.mark.anyio
async def test_list_files_uses_runner_and_sets_tool_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """File-list API should use internal runner and return expected envelope."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": "list_files",
            "result": {
                "embedding_files": ["sample_embeddings.parquet"],
                "available_models": ["gte-small"],
            },
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.list_caselaw_access_vector_files_from_parameters(
        {
            "auto_setup_venv": False,
            "venv_dir": ".venv",
            "model_hint": "gte-small",
        },
        tool_version="9.9.9",
    )

    assert result["status"] == "success"
    assert result["operation"] == "list_files"
    assert result["tool_version"] == "9.9.9"
    assert captured["operation"] == "list_files"
    assert captured["payload"]["model_hint"] == "gte-small"


def test_cap_tool_specs_include_bundle_and_centroid_search() -> None:
    """CAP metadata specs should include recently added tools and required shape."""
    specs = get_cap_legal_dataset_tool_specs()

    assert specs is CAP_LEGAL_DATASET_TOOL_SPECS
    assert isinstance(specs, list)
    assert len(specs) >= 6

    by_name = {spec["name"]: spec for spec in specs}

    for required_name in (
        "list_caselaw_access_vector_files",
        "ingest_caselaw_access_vector_bundle",
        "search_caselaw_access_cases",
        "search_caselaw_access_vectors_with_centroids",
    ):
        assert required_name in by_name
        spec = by_name[required_name]
        assert "description" in spec
        assert isinstance(spec.get("parameters"), dict)
        assert spec.get("category") == "legal_dataset_tools"

    bundle_params = by_name["ingest_caselaw_access_vector_bundle"]["parameters"]
    assert "target_collection_name" in bundle_params
    assert "centroid_collection_name" in bundle_params
    assert bundle_params["target_collection_name"].get("required") is True
    assert bundle_params["centroid_collection_name"].get("required") is True

    case_search_params = by_name["search_caselaw_access_cases"]["parameters"]
    assert "local_case_parquet_file" in case_search_params
    assert "chunk_hf_parquet_file" in case_search_params
    assert "chunk_lookup_enabled" in case_search_params


def test_tool_registration_mapping_includes_cap_entries() -> None:
    """Central migrated tool mapping should expose CAP entries for auto registration."""
    legal_mapping = TOOL_MAPPINGS["legal_dataset_tools"]["functions"]

    for func_name in (
        "setup_legal_tools_venv",
        "list_caselaw_access_vector_files",
        "ingest_caselaw_access_vectors",
        "ingest_caselaw_access_vector_bundle",
        "search_caselaw_access_vectors",
        "search_caselaw_access_cases",
        "search_caselaw_access_vectors_with_centroids",
    ):
        assert func_name in legal_mapping
        assert "name" in legal_mapping[func_name]
        assert "description" in legal_mapping[func_name]


@pytest.mark.anyio
async def test_search_requires_query_vector() -> None:
    """CAP search endpoint should enforce query_vector."""
    result = await legal_dataset_api.search_caselaw_access_vectors_from_parameters(
        {"collection_name": "cap_docs", "auto_setup_venv": False}
    )

    assert result["status"] == "error"
    assert result["operation"] == "search"
    assert "query_vector is required" in result["error"]


@pytest.mark.anyio
async def test_search_uses_runner_with_search_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    """CAP search endpoint should invoke subprocess runner with search payload."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": "search",
            "results": [{"chunk_id": "x", "score": 0.9, "content": "demo", "metadata": {}}],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_caselaw_access_vectors_from_parameters(
        {
            "collection_name": "cap_docs",
            "query_vector": [0.1, 0.2, 0.3],
            "top_k": 7,
            "auto_setup_venv": False,
            "venv_dir": ".venv",
        },
        tool_version="2.1.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search"
    assert result["tool_version"] == "2.1.0"
    assert captured["operation"] == "search"
    assert captured["payload"]["collection_name"] == "cap_docs"
    assert captured["payload"]["top_k"] == 7


@pytest.mark.anyio
async def test_case_search_requires_query_vector() -> None:
    """CAP case-search endpoint should enforce query_vector."""
    result = await legal_dataset_api.search_caselaw_access_cases_from_parameters(
        {"collection_name": "cap_docs", "auto_setup_venv": False}
    )

    assert result["status"] == "error"
    assert result["operation"] == "search_cases"
    assert "query_vector is required" in result["error"]


@pytest.mark.anyio
async def test_case_search_uses_runner_with_search_cases_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAP case-search endpoint should invoke subprocess runner with search_cases payload."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": "search_cases",
            "results": [
                {
                    "chunk_id": "x",
                    "score": 0.9,
                    "content": "demo",
                    "metadata": {"cid": "abc"},
                    "cid": "abc",
                    "case": {"cid": "abc", "name": "Case A", "snippet": "..."},
                }
            ],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_caselaw_access_cases_from_parameters(
        {
            "collection_name": "cap_docs",
            "query_vector": [0.1, 0.2, 0.3],
            "top_k": 7,
            "auto_setup_venv": False,
            "venv_dir": ".venv",
            "hf_dataset_id": "justicedao/ipfs_caselaw_access_project",
            "local_case_parquet_file": "/tmp/caselaw.parquet",
            "chunk_lookup_enabled": True,
            "chunk_hf_parquet_file": "embeddings/sparse_chunks.parquet",
            "local_chunk_parquet_file": "/tmp/sparse_chunks.parquet",
            "chunk_snippet_chars": 750,
        },
        tool_version="2.2.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert result["tool_version"] == "2.2.0"
    assert captured["operation"] == "search_cases"
    assert captured["payload"]["collection_name"] == "cap_docs"
    assert captured["payload"]["top_k"] == 7
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_caselaw_access_project"
    assert captured["payload"]["local_case_parquet_file"] == "/tmp/caselaw.parquet"
    assert captured["payload"]["chunk_lookup_enabled"] is True
    assert captured["payload"]["chunk_hf_parquet_file"] == "embeddings/sparse_chunks.parquet"
    assert captured["payload"]["local_chunk_parquet_file"] == "/tmp/sparse_chunks.parquet"
    assert captured["payload"]["chunk_snippet_chars"] == 750


@pytest.mark.anyio
async def test_centroid_search_requires_collection_names_and_query() -> None:
    """Centroid search should validate required fields before execution."""
    missing_query = await legal_dataset_api.search_caselaw_access_vectors_with_centroids_from_parameters(
        {
            "target_collection_name": "cap_docs",
            "centroid_collection_name": "cap_centroids",
            "auto_setup_venv": False,
        }
    )
    assert missing_query["status"] == "error"
    assert missing_query["operation"] == "centroid_search"
    assert "query_vector is required" in missing_query["error"]

    missing_names = await legal_dataset_api.search_caselaw_access_vectors_with_centroids_from_parameters(
        {
            "query_vector": [0.2, 0.4],
            "auto_setup_venv": False,
        }
    )
    assert missing_names["status"] == "error"
    assert "target_collection_name" in missing_names["error"]
    assert "centroid_collection_name" in missing_names["error"]


@pytest.mark.anyio
async def test_centroid_routing_merges_and_ranks_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Centroid routing should dedupe by chunk_id and keep the best score."""
    cap = vector_search_integration.CaselawAccessVectorSearch()

    centroid_hits = [
        SimpleNamespace(chunk_id="c1", score=0.91, metadata={"cluster_id": "cluster-a"}, content=""),
        SimpleNamespace(chunk_id="c2", score=0.87, metadata={"cluster_id": "cluster-b"}, content=""),
    ]
    cluster_a_hits = [
        SimpleNamespace(chunk_id="doc-1", score=0.82, metadata={"cluster_id": "cluster-a"}, content="A1"),
        SimpleNamespace(chunk_id="doc-2", score=0.71, metadata={"cluster_id": "cluster-a"}, content="A2"),
    ]
    cluster_b_hits = [
        SimpleNamespace(chunk_id="doc-1", score=0.93, metadata={"cluster_id": "cluster-b"}, content="B1"),
        SimpleNamespace(chunk_id="doc-3", score=0.65, metadata={"cluster_id": "cluster-b"}, content="B3"),
    ]

    calls = []

    async def _fake_search_by_vector(*, collection_name, query_vector, store_type="faiss", top_k=10, filter_dict=None, **kwargs):
        calls.append(
            {
                "collection_name": collection_name,
                "top_k": top_k,
                "filter_dict": dict(filter_dict or {}),
            }
        )
        if collection_name == "cap_centroids":
            return centroid_hits
        cluster_id = (filter_dict or {}).get("cluster_id")
        if cluster_id == "cluster-a":
            return cluster_a_hits
        if cluster_id == "cluster-b":
            return cluster_b_hits
        return []

    monkeypatch.setattr(cap, "search_by_vector", _fake_search_by_vector)

    plan = await cap.search_with_centroid_routing(
        target_collection_name="cap_docs",
        centroid_collection_name="cap_centroids",
        query_vector=[0.1, 0.2, 0.3],
        centroid_top_k=2,
        per_cluster_top_k=5,
        final_top_k=3,
        cluster_metadata_field="cluster_id",
    )

    assert plan.centroid_collection_name == "cap_centroids"
    assert plan.target_collection_name == "cap_docs"
    assert plan.selected_cluster_ids == ["cluster-a", "cluster-b"]

    by_id = {r.chunk_id: r for r in plan.retrieved_results}
    assert by_id["doc-1"].score == 0.93

    scores = [r.score for r in plan.retrieved_results]
    assert scores == sorted(scores, reverse=True)

    assert calls[0]["collection_name"] == "cap_centroids"
    assert calls[1]["collection_name"] == "cap_docs"
    assert calls[1]["filter_dict"]["cluster_id"] == "cluster-a"
    assert calls[2]["filter_dict"]["cluster_id"] == "cluster-b"


@pytest.mark.anyio
async def test_centroid_routing_uses_cluster_cid_map_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Centroid routing should constrain target results to mapped CIDs per cluster."""
    cap = vector_search_integration.CaselawAccessVectorSearch()

    centroid_hits = [
        SimpleNamespace(chunk_id="cent-1", score=0.9, metadata={"cluster_id": "cluster-a"}, content=""),
    ]
    target_hits = [
        SimpleNamespace(chunk_id="doc-allowed", score=0.88, metadata={"cid": "cid-allow"}, content="ok"),
        SimpleNamespace(chunk_id="doc-blocked", score=0.95, metadata={"cid": "cid-block"}, content="no"),
    ]

    calls = []

    async def _fake_search_by_vector(*, collection_name, query_vector, store_type="faiss", top_k=10, filter_dict=None, **kwargs):
        calls.append({"collection_name": collection_name, "top_k": top_k, "filter_dict": dict(filter_dict or {})})
        if collection_name == "cap_centroids":
            return centroid_hits
        return target_hits

    def _fake_load_cluster_to_cids_map(*args, **kwargs):
        return {"cluster-a": ["cid-allow"]}

    monkeypatch.setattr(cap, "search_by_vector", _fake_search_by_vector)
    monkeypatch.setattr(cap, "_load_cluster_to_cids_map", _fake_load_cluster_to_cids_map)

    plan = await cap.search_with_centroid_routing(
        target_collection_name="cap_docs",
        centroid_collection_name="cap_centroids",
        query_vector=[0.1, 0.2, 0.3],
        centroid_top_k=1,
        per_cluster_top_k=2,
        final_top_k=5,
        cluster_metadata_field="cluster_id",
        cluster_cids_parquet_file="hf://fake/cluster_cids.parquet",
        cid_metadata_field="cid",
    )

    assert plan.selected_cluster_ids == ["cluster-a"]
    assert [hit.chunk_id for hit in plan.retrieved_results] == ["doc-allowed"]
    assert calls[0]["collection_name"] == "cap_centroids"
    assert calls[1]["collection_name"] == "cap_docs"
    # CID map path does not require cluster metadata filtering in target retrieval.
    assert calls[1]["filter_dict"] == {}
