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
        "search_us_code_corpus",
        "search_state_law_corpus",
        "search_workspace_dataset",
        "search_docket_dataset",
        "search_federal_register_corpus",
        "search_netherlands_law_corpus",
        "recover_missing_legal_citation_source",
        "promote_recovery_manifest_to_canonical_bundle",
        "preview_recovery_manifest_release_plan",
        "merge_recovery_manifest_into_canonical_dataset",
        "collect_packaged_docket_citation_recovery_candidates",
        "recover_packaged_docket_missing_authorities",
        "plan_packaged_docket_missing_authority_follow_up",
        "execute_packaged_docket_missing_authority_follow_up",
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

    uscode_params = by_name["search_us_code_corpus"]["parameters"]
    assert uscode_params["hf_dataset_id"]["default"] == "justicedao/ipfs_uscode"
    assert uscode_params["hf_parquet_prefix"]["default"] == "uscode_parquet"

    state_params = by_name["search_state_law_corpus"]["parameters"]
    assert state_params["state"]["default"] == "OR"
    assert state_params["hf_dataset_id"]["default"] == "justicedao/ipfs_state_laws"
    assert "preferred_case_parquet_names" in state_params
    assert "hf_parquet_files" in state_params
    assert state_params["max_case_parquet_files"]["default"] == 0

    federal_register_params = by_name["search_federal_register_corpus"]["parameters"]
    assert federal_register_params["hf_dataset_id"]["default"] == "justicedao/ipfs_federal_register"
    assert federal_register_params["hf_parquet_file"]["default"] == "laws.parquet"
    assert federal_register_params["cid_metadata_field"]["default"] == "ipfs_cid"
    assert federal_register_params["cid_column"]["default"] == "ipfs_cid"

    netherlands_params = by_name["search_netherlands_law_corpus"]["parameters"]
    assert netherlands_params["hf_dataset_id"]["default"] == "justicedao/ipfs_netherlands_laws"
    assert netherlands_params["hf_parquet_file"]["default"] == "netherlands_laws.parquet"
    assert "citation_query" in netherlands_params
    assert "query_text" in netherlands_params
    assert netherlands_params["context_mode"]["default"] == "exact"
    assert netherlands_params["prefer_current_versions"]["default"] is True
    assert netherlands_params["include_historical_versions"]["default"] is True
    assert "as_of_date" in netherlands_params
    assert "effective_date" in netherlands_params

    workspace_params = by_name["search_workspace_dataset"]["parameters"]
    assert workspace_params["input_path"].get("required") is True
    assert workspace_params["query"].get("required") is True
    assert workspace_params["backend"]["default"] == "bm25"
    assert workspace_params["input_kind"]["default"] == "auto"

    docket_params = by_name["search_docket_dataset"]["parameters"]
    assert docket_params["input_path"].get("required") is True
    assert docket_params["query"].get("required") is True
    assert docket_params["backend"]["default"] == "bm25"
    assert docket_params["input_kind"]["default"] == "auto"

    recovery_params = by_name["recover_missing_legal_citation_source"]["parameters"]
    assert "candidate-file fetch artifacts" in by_name["recover_missing_legal_citation_source"]["description"]
    assert recovery_params["citation_text"].get("required") is True
    assert recovery_params["max_candidates"]["default"] == 8
    assert recovery_params["archive_top_k"]["default"] == 3
    assert recovery_params["publish_to_hf"]["default"] is False

    promotion_params = by_name["promote_recovery_manifest_to_canonical_bundle"]["parameters"]
    assert promotion_params["manifest_path"].get("required") is True
    assert promotion_params["write_parquet"]["default"] is True

    release_plan_params = by_name["preview_recovery_manifest_release_plan"]["parameters"]
    assert release_plan_params["manifest_path"].get("required") is True
    assert release_plan_params["python_bin"]["default"] == "python3"

    merge_params = by_name["merge_recovery_manifest_into_canonical_dataset"]["parameters"]
    assert merge_params["manifest_path"].get("required") is True
    assert merge_params["write_promotion_parquet"]["default"] is True

    packaged_collect_params = by_name["collect_packaged_docket_citation_recovery_candidates"]["parameters"]
    assert packaged_collect_params["manifest_path"].get("required") is True

    packaged_recovery_params = by_name["recover_packaged_docket_missing_authorities"]["parameters"]
    assert packaged_recovery_params["manifest_path"].get("required") is True
    assert packaged_recovery_params["max_candidates"]["default"] == 8
    assert packaged_recovery_params["archive_top_k"]["default"] == 3

    packaged_plan_params = by_name["plan_packaged_docket_missing_authority_follow_up"]["parameters"]
    assert packaged_plan_params["manifest_path"].get("required") is True
    assert packaged_plan_params["max_candidates"]["default"] == 8
    assert packaged_plan_params["archive_top_k"]["default"] == 3

    packaged_execute_params = by_name["execute_packaged_docket_missing_authority_follow_up"]["parameters"]
    assert packaged_execute_params["manifest_path"].get("required") is True
    assert packaged_execute_params["execute_publish"]["default"] is False


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
        "search_us_code_corpus",
        "search_state_law_corpus",
        "search_workspace_dataset",
        "search_docket_dataset",
        "search_netherlands_law_corpus",
        "recover_missing_legal_citation_source",
        "promote_recovery_manifest_to_canonical_bundle",
        "preview_recovery_manifest_release_plan",
        "merge_recovery_manifest_into_canonical_dataset",
        "collect_packaged_docket_citation_recovery_candidates",
        "recover_packaged_docket_missing_authorities",
        "plan_packaged_docket_missing_authority_follow_up",
        "execute_packaged_docket_missing_authority_follow_up",
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
async def test_mcp_workspace_search_auto_loads_single_bundle_and_returns_grouped_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workspace MCP search should auto-load a single bundle and return grouped results."""
    captured = {}

    def _fake_load_single(path):
        captured["load_single"] = str(path)
        return {"dataset_id": "workspace_1"}

    def _fake_search(dataset, query, *, top_k=10):
        captured["search"] = {"dataset": dataset, "query": query, "top_k": top_k}
        return {
            "query": query,
            "top_k": top_k,
            "results": [{"id": "voice_1"}],
            "grouped_results": [{"group_id": "google_voice_bundle_voice_1"}],
            "result_count": 1,
            "group_count": 1,
            "source": "local_bm25",
        }

    monkeypatch.setattr(mcp_tools, "load_workspace_dataset_single_parquet", _fake_load_single)
    monkeypatch.setattr(mcp_tools, "search_workspace_dataset_bm25", _fake_search)

    result = await mcp_tools.search_workspace_dataset(
        {
            "input_path": "/tmp/workspace_bundle.parquet",
            "query": "inspection",
            "top_k": 5,
        }
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_workspace_dataset"
    assert result["input_kind"] == "single"
    assert result["backend"] == "bm25"
    assert result["group_count"] == 1
    assert result["grouped_results"][0]["group_id"] == "google_voice_bundle_voice_1"
    assert captured["load_single"] == "/tmp/workspace_bundle.parquet"
    assert captured["search"]["query"] == "inspection"
    assert captured["search"]["top_k"] == 5


@pytest.mark.anyio
async def test_mcp_workspace_search_auto_loads_packaged_manifest_and_uses_vector_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace MCP search should auto-load packaged manifests and dispatch vector search."""
    captured = {}

    def _fake_load_packaged(path):
        captured["load_packaged"] = str(path)
        return {"dataset_id": "workspace_packaged_1"}

    def _fake_vector_search(dataset, query, *, top_k=10):
        captured["vector_search"] = {"dataset": dataset, "query": query, "top_k": top_k}
        return {
            "query": query,
            "top_k": top_k,
            "results": [{"document_id": "voice_1", "score": 0.81}],
            "grouped_results": [{"group_id": "google_voice_bundle_voice_1"}],
            "result_count": 1,
            "group_count": 1,
        }

    monkeypatch.setattr(mcp_tools, "load_packaged_workspace_dataset", _fake_load_packaged)
    monkeypatch.setattr(mcp_tools, "search_workspace_dataset_vector", _fake_vector_search)

    result = await mcp_tools.search_workspace_dataset(
        {
            "input_path": "/tmp/workspace_package/bundle_manifest.json",
            "query": "inspection",
            "backend": "vector",
            "top_k": 7,
        }
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_workspace_dataset"
    assert result["input_kind"] == "packaged"
    assert result["backend"] == "vector"
    assert result["group_count"] == 1
    assert result["grouped_results"][0]["group_id"] == "google_voice_bundle_voice_1"
    assert captured["load_packaged"] == "/tmp/workspace_package/bundle_manifest.json"
    assert captured["vector_search"]["query"] == "inspection"
    assert captured["vector_search"]["top_k"] == 7


@pytest.mark.anyio
async def test_mcp_workspace_search_rejects_unknown_backend() -> None:
    """Workspace MCP search should fail fast on unsupported backend values."""
    result = await mcp_tools.search_workspace_dataset(
        {
            "input_path": "/tmp/workspace_bundle.parquet",
            "query": "inspection",
            "backend": "hybrid",
        }
    )

    assert result["status"] == "error"
    assert result["operation"] == "search_workspace_dataset"
    assert "Unsupported backend" in result["error"]


@pytest.mark.anyio
async def test_mcp_docket_search_auto_loads_dataset_json_and_dispatches_bm25(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Docket MCP search should auto-load dataset JSON artifacts and dispatch BM25 search."""
    dataset_path = tmp_path / "docket_dataset.json"
    dataset_path.write_text('{"dataset_id": "docket_1"}', encoding="utf-8")
    captured = {}

    def _fake_search(dataset, query, *, top_k=10):
        captured["search"] = {"dataset": dataset, "query": query, "top_k": top_k}
        return {
            "query": query,
            "top_k": top_k,
            "results": [{"id": "doc_1"}],
            "result_count": 1,
            "source": "local_bm25",
        }

    monkeypatch.setattr(mcp_tools, "search_docket_dataset_bm25", _fake_search)

    result = await mcp_tools.search_docket_dataset(
        {
            "input_path": str(dataset_path),
            "query": "complaint",
            "top_k": 4,
        }
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_docket_dataset"
    assert result["input_kind"] == "dataset"
    assert result["backend"] == "bm25"
    assert captured["search"]["dataset"]["dataset_id"] == "docket_1"
    assert captured["search"]["query"] == "complaint"
    assert captured["search"]["top_k"] == 4


@pytest.mark.anyio
async def test_mcp_docket_search_auto_loads_packaged_manifest_and_uses_vector_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docket MCP search should auto-load packaged manifests and dispatch vector search."""
    captured = {}

    def _fake_load_packaged(path):
        captured["load_packaged"] = str(path)
        return {"dataset_id": "packaged_docket_1"}

    def _fake_vector_search(dataset, query, *, top_k=10, vector_dimension=32):
        captured["vector_search"] = {
            "dataset": dataset,
            "query": query,
            "top_k": top_k,
            "vector_dimension": vector_dimension,
        }
        return {
            "query": query,
            "top_k": top_k,
            "results": [{"document_id": "doc_2", "score": 0.75}],
            "result_count": 1,
        }

    monkeypatch.setattr(mcp_tools, "load_packaged_docket_dataset", _fake_load_packaged)
    monkeypatch.setattr(mcp_tools, "search_docket_dataset_vector", _fake_vector_search)

    result = await mcp_tools.search_docket_dataset(
        {
            "input_path": "/tmp/docket_package/bundle_manifest.json",
            "query": "response",
            "backend": "vector",
            "top_k": 6,
        }
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_docket_dataset"
    assert result["input_kind"] == "packaged"
    assert result["backend"] == "vector"
    assert captured["load_packaged"] == "/tmp/docket_package/bundle_manifest.json"
    assert captured["vector_search"]["query"] == "response"
    assert captured["vector_search"]["top_k"] == 6


@pytest.mark.anyio
async def test_mcp_docket_search_rejects_unknown_backend() -> None:
    """Docket MCP search should fail fast on unsupported backend values."""
    result = await mcp_tools.search_docket_dataset(
        {
            "input_path": "/tmp/docket_dataset.json",
            "query": "response",
            "backend": "hybrid",
        }
    )

    assert result["status"] == "error"
    assert result["operation"] == "search_docket_dataset"
    assert "Unsupported backend" in result["error"]


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
async def test_uscode_case_search_applies_dataset_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US Code wrapper should set corpus defaults while reusing CAP search pipeline."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": "search_cases",
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_us_code_corpus_from_parameters(
        {
            "collection_name": "uscode_docs",
            "query_vector": [0.9, 0.1, 0.0],
            "auto_setup_venv": False,
        },
        tool_version="3.0.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert result["tool_version"] == "3.0.0"
    assert captured["operation"] == "search_cases"
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_uscode"
    assert captured["payload"]["hf_parquet_prefix"] == "uscode_parquet"
    assert captured["payload"]["hf_parquet_file"] is None
    assert captured["payload"]["chunk_lookup_enabled"] is False


@pytest.mark.anyio
async def test_state_case_search_applies_oregon_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State-law wrapper should default to OR prefix and disable chunk lookup."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": operation,
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_state_law_corpus_from_parameters(
        {
            "collection_name": "or_docs",
            "query_vector": [0.2, 0.3, 0.4],
            "auto_setup_venv": False,
        },
        tool_version="3.1.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search"
    assert result["tool_version"] == "3.1.0"
    assert result["state"] == "OR"
    assert captured["operation"] == "search"
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert captured["payload"]["collection_name"] == "or_docs"
    assert captured["payload"]["top_k"] == 10


@pytest.mark.anyio
async def test_state_case_search_can_enable_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State-law wrapper should use canonical CID parquet defaults when enrichment is requested."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": operation,
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_state_law_corpus_from_parameters(
        {
            "collection_name": "or_docs",
            "query_vector": [0.2, 0.3, 0.4],
            "state": "OR",
            "enrich_with_cases": True,
            "auto_setup_venv": False,
        },
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert captured["operation"] == "search_cases"
    assert captured["payload"]["hf_parquet_prefix"] is None
    assert captured["payload"]["cid_metadata_field"] == "ipfs_cid"
    assert captured["payload"]["cid_column"] == "ipfs_cid"
    preferred_names = captured["payload"]["preferred_case_parquet_names"]
    assert "STATE-OR.parquet" in preferred_names
    assert "state_laws_all_states.parquet" in preferred_names
    assert "state_admin_rules_all_states.parquet" in preferred_names
    assert captured["payload"]["max_case_parquet_files"] == 4
    assert captured["payload"]["chunk_lookup_enabled"] is False


@pytest.mark.anyio
async def test_state_court_rules_search_uses_canonical_state_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State court-rules wrapper should target the canonical CID-keyed state corpus."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": operation,
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_court_rules_corpus_from_parameters(
        {
            "collection_name": "state_court_rules",
            "query_vector": [0.5, 0.1, 0.9],
            "jurisdiction": "state",
            "state": "OR",
            "auto_setup_venv": False,
        },
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert result["jurisdiction"] == "state"
    assert result["state"] == "OR"
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_court_rules"
    assert captured["payload"]["hf_parquet_prefix"] is None
    assert captured["payload"]["cid_metadata_field"] == "ipfs_cid"
    assert captured["payload"]["cid_column"] == "ipfs_cid"
    assert "STATE-OR.parquet" in captured["payload"]["preferred_case_parquet_names"]
    assert "state_court_rules_all_states.parquet" in captured["payload"]["preferred_case_parquet_names"]


@pytest.mark.anyio
async def test_federal_register_search_uses_canonical_cid_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Federal Register wrapper should target the CID-keyed published parquet."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": operation,
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_federal_register_corpus_from_parameters(
        {
            "collection_name": "federal_register_docs",
            "query_vector": [0.4, 0.2, 0.8],
            "auto_setup_venv": False,
        },
        tool_version="3.3.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert result["tool_version"] == "3.3.0"
    assert captured["operation"] == "search_cases"
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_federal_register"
    assert captured["payload"]["hf_parquet_file"] == "laws.parquet"
    assert captured["payload"]["cid_metadata_field"] == "ipfs_cid"
    assert captured["payload"]["cid_column"] == "ipfs_cid"
    preferred_names = captured["payload"]["preferred_case_parquet_names"]
    assert "laws.parquet" in preferred_names
    assert "federal_register.parquet" in preferred_names
    assert captured["payload"]["chunk_lookup_enabled"] is False


@pytest.mark.anyio
async def test_netherlands_law_search_uses_canonical_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Netherlands-law wrapper should target the canonical CID-keyed published parquet."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        captured["venv_dir"] = venv_dir
        return {
            "status": "success",
            "operation": operation,
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_netherlands_law_corpus_from_parameters(
        {
            "collection_name": "netherlands_laws",
            "query_vector": [0.7, 0.1, 0.2],
            "auto_setup_venv": False,
        },
        tool_version="3.4.0",
    )

    assert result["status"] == "success"
    assert result["operation"] == "search_cases"
    assert result["tool_version"] == "3.4.0"
    assert result["jurisdiction"] == "NL"
    assert captured["payload"]["hf_dataset_id"] == "justicedao/ipfs_netherlands_laws"
    assert captured["payload"]["hf_parquet_file"] == "netherlands_laws.parquet"
    assert captured["payload"]["cid_metadata_field"] == "ipfs_cid"
    assert captured["payload"]["cid_column"] == "ipfs_cid"
    assert "netherlands_laws.parquet" in captured["payload"]["preferred_case_parquet_names"]
    assert captured["payload"]["chunk_lookup_enabled"] is False


@pytest.mark.anyio
async def test_mcp_recovery_tool_delegates_to_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api as real_api

    captured = {}

    async def _fake_recover_missing_legal_citation_source_from_parameters(parameters, *, tool_version="1.0.0"):
        captured["parameters"] = dict(parameters)
        captured["tool_version"] = tool_version
        return {
            "status": "tracked",
            "operation": "recover_missing_legal_citation_source",
            "candidate_files": [
                {
                    "url": "https://www.revisor.mn.gov/statutes/2024/cite/518.17.pdf",
                    "fetch_success": True,
                }
            ],
            "scraper_patch": {
                "patch_path": "/tmp/recovery.patch",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            },
        }

    async def _fake_promote_recovery_manifest_to_canonical_bundle_from_parameters(parameters, *, tool_version="1.0.0"):
        captured["promote_parameters"] = dict(parameters)
        captured["promote_tool_version"] = tool_version
        return {"status": "success", "operation": "promote_recovery_manifest_to_canonical_bundle"}

    async def _fake_preview_recovery_manifest_release_plan_from_parameters(parameters, *, tool_version="1.0.0"):
        captured["release_plan_parameters"] = dict(parameters)
        captured["release_plan_tool_version"] = tool_version
        return {"status": "planned", "operation": "preview_recovery_manifest_release_plan"}

    async def _fake_merge_recovery_manifest_into_canonical_dataset_from_parameters(parameters, *, tool_version="1.0.0"):
        captured["merge_parameters"] = dict(parameters)
        captured["merge_tool_version"] = tool_version
        return {"status": "success", "operation": "merge_recovery_manifest_into_canonical_dataset"}

    monkeypatch.setattr(
        real_api,
        "recover_missing_legal_citation_source_from_parameters",
        _fake_recover_missing_legal_citation_source_from_parameters,
    )
    monkeypatch.setattr(
        real_api,
        "promote_recovery_manifest_to_canonical_bundle_from_parameters",
        _fake_promote_recovery_manifest_to_canonical_bundle_from_parameters,
    )
    monkeypatch.setattr(
        real_api,
        "preview_recovery_manifest_release_plan_from_parameters",
        _fake_preview_recovery_manifest_release_plan_from_parameters,
    )
    monkeypatch.setattr(
        real_api,
        "merge_recovery_manifest_into_canonical_dataset_from_parameters",
        _fake_merge_recovery_manifest_into_canonical_dataset_from_parameters,
    )

    result = await mcp_tools.recover_missing_legal_citation_source(
        {
            "citation_text": "42 U.S.C. § 1983",
            "corpus_key": "us_code",
        }
    )
    promote_result = await mcp_tools.promote_recovery_manifest_to_canonical_bundle(
        {"manifest_path": "/tmp/recovery_manifest.json", "write_parquet": False}
    )
    release_plan_result = await mcp_tools.preview_recovery_manifest_release_plan(
        {"manifest_path": "/tmp/recovery_manifest.json", "python_bin": "/usr/bin/python3"}
    )
    merge_result = await mcp_tools.merge_recovery_manifest_into_canonical_dataset(
        {"manifest_path": "/tmp/recovery_manifest.json", "target_local_parquet_path": "/tmp/target.parquet"}
    )

    assert result["status"] == "tracked"
    assert result["candidate_files"][0]["fetch_success"] is True
    assert result["scraper_patch"]["target_file"] == "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py"
    assert promote_result["status"] == "success"
    assert release_plan_result["status"] == "planned"
    assert merge_result["status"] == "success"
    assert captured["parameters"]["citation_text"] == "42 U.S.C. § 1983"
    assert captured["parameters"]["corpus_key"] == "us_code"
    assert captured["tool_version"] == "1.0.0"
    assert captured["promote_parameters"]["manifest_path"] == "/tmp/recovery_manifest.json"
    assert captured["promote_parameters"]["write_parquet"] is False
    assert captured["promote_tool_version"] == "1.0.0"
    assert captured["release_plan_parameters"]["manifest_path"] == "/tmp/recovery_manifest.json"
    assert captured["release_plan_parameters"]["python_bin"] == "/usr/bin/python3"
    assert captured["release_plan_tool_version"] == "1.0.0"
    assert captured["merge_parameters"]["manifest_path"] == "/tmp/recovery_manifest.json"
    assert captured["merge_parameters"]["target_local_parquet_path"] == "/tmp/target.parquet"
    assert captured["merge_tool_version"] == "1.0.0"


@pytest.mark.anyio
async def test_mcp_packaged_docket_recovery_tools_delegate_to_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api as real_api

    captured = {}

    async def _fake_collect(parameters, *, tool_version="1.0.0"):
        captured["collect_parameters"] = dict(parameters)
        captured["collect_tool_version"] = tool_version
        return {"status": "success", "operation": "collect_packaged_docket_citation_recovery_candidates"}

    async def _fake_recover(parameters, *, tool_version="1.0.0"):
        captured["recover_parameters"] = dict(parameters)
        captured["recover_tool_version"] = tool_version
        return {"status": "success", "operation": "recover_packaged_docket_missing_authorities"}

    async def _fake_plan(parameters, *, tool_version="1.0.0"):
        captured["plan_parameters"] = dict(parameters)
        captured["plan_tool_version"] = tool_version
        return {"status": "success", "operation": "plan_packaged_docket_missing_authority_follow_up"}

    async def _fake_execute(parameters, *, tool_version="1.0.0"):
        captured["execute_parameters"] = dict(parameters)
        captured["execute_tool_version"] = tool_version
        return {"status": "success", "operation": "execute_packaged_docket_missing_authority_follow_up"}

    monkeypatch.setattr(
        real_api,
        "collect_packaged_docket_citation_recovery_candidates_from_parameters",
        _fake_collect,
    )
    monkeypatch.setattr(
        real_api,
        "recover_packaged_docket_missing_authorities_from_parameters",
        _fake_recover,
    )
    monkeypatch.setattr(
        real_api,
        "plan_packaged_docket_missing_authority_follow_up_from_parameters",
        _fake_plan,
    )
    monkeypatch.setattr(
        real_api,
        "execute_packaged_docket_missing_authority_follow_up_from_parameters",
        _fake_execute,
    )

    collect_result = await mcp_tools.collect_packaged_docket_citation_recovery_candidates(
        {"manifest_path": "/tmp/manifest.json"}
    )
    recover_result = await mcp_tools.recover_packaged_docket_missing_authorities(
        {"manifest_path": "/tmp/manifest.json", "publish_to_hf": True}
    )
    plan_result = await mcp_tools.plan_packaged_docket_missing_authority_follow_up(
        {"manifest_path": "/tmp/manifest.json", "publish_to_hf": True}
    )
    execute_result = await mcp_tools.execute_packaged_docket_missing_authority_follow_up(
        {"manifest_path": "/tmp/manifest.json", "execute_publish": True}
    )

    assert collect_result["status"] == "success"
    assert recover_result["status"] == "success"
    assert plan_result["status"] == "success"
    assert execute_result["status"] == "success"
    assert captured["collect_parameters"]["manifest_path"] == "/tmp/manifest.json"
    assert captured["recover_parameters"]["manifest_path"] == "/tmp/manifest.json"
    assert captured["recover_parameters"]["publish_to_hf"] is True
    assert captured["plan_parameters"]["manifest_path"] == "/tmp/manifest.json"
    assert captured["plan_parameters"]["publish_to_hf"] is True
    assert captured["execute_parameters"]["manifest_path"] == "/tmp/manifest.json"
    assert captured["execute_parameters"]["execute_publish"] is True
    assert captured["collect_tool_version"] == "1.0.0"
    assert captured["recover_tool_version"] == "1.0.0"
    assert captured["plan_tool_version"] == "1.0.0"
    assert captured["execute_tool_version"] == "1.0.0"


@pytest.mark.anyio
async def test_federal_court_rules_search_defaults_to_vector_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Federal court-rules search should avoid broken CID enrichment defaults."""
    captured = {}

    def _fake_runner(*, operation, payload, venv_dir=".venv"):
        captured["operation"] = operation
        captured["payload"] = payload
        return {
            "status": "success",
            "operation": operation,
            "results": [],
        }

    monkeypatch.setattr(legal_dataset_api, "_run_cap_vector_operation_in_venv", _fake_runner)

    result = await legal_dataset_api.search_court_rules_corpus_from_parameters(
        {
            "collection_name": "federal_court_rules",
            "query_vector": [0.5, 0.2, 0.3],
            "jurisdiction": "federal",
            "auto_setup_venv": False,
        },
    )

    assert result["status"] == "success"
    assert result["operation"] == "search"
    assert result["jurisdiction"] == "federal"
    assert captured["operation"] == "search"


@pytest.mark.anyio
async def test_state_case_search_rejects_invalid_state() -> None:
    """State-law wrapper should validate state code shape."""
    result = await legal_dataset_api.search_state_law_corpus_from_parameters(
        {
            "collection_name": "or_docs",
            "query_vector": [0.2, 0.3, 0.4],
            "state": "Oregon",
            "auto_setup_venv": False,
        },
    )

    assert result["status"] == "error"
    assert "two-letter" in result["error"]


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
