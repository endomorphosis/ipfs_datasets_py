from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_cli_module():
    module_path = REPO_ROOT / "ipfs_datasets_cli.py"
    spec = importlib.util.spec_from_file_location("ipfs_datasets_cli_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_legal_search_federal_register_generates_embedding_and_dispatches(
    monkeypatch,
    capsys,
) -> None:
    cli_module = _load_cli_module()
    captured: dict[str, object] = {}

    def _fake_embed_text(query_text: str, model_name: str, provider: str | None = None):
        captured["query_text"] = query_text
        captured["model_name"] = model_name
        captured["provider"] = provider
        return [0.11, 0.22, 0.33]

    async def _fake_search_federal_register_corpus_from_parameters(parameters, tool_version: str = "1.0.0"):
        captured["parameters"] = dict(parameters)
        captured["tool_version"] = tool_version
        return {
            "status": "success",
            "operation": "search_cases",
            "results": [{"cid": "bafytest"}],
        }

    fake_embeddings_router = ModuleType("ipfs_datasets_py.embeddings_router")
    fake_embeddings_router.embed_text = _fake_embed_text
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.embeddings_router", fake_embeddings_router)

    fake_legal_dataset_api = ModuleType(
        "ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api"
    )
    fake_legal_dataset_api.search_federal_register_corpus_from_parameters = (
        _fake_search_federal_register_corpus_from_parameters
    )
    monkeypatch.setitem(
        sys.modules,
        "ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api",
        fake_legal_dataset_api,
    )

    cli_module.execute_heavy_command(
        [
            "legal",
            "search-federal-register",
            "--collection_name",
            "federal_register_docs",
            "--query_text",
            "EPA emissions reporting rule",
        ]
    )

    out = capsys.readouterr().out
    assert '"status": "success"' in out
    assert captured["query_text"] == "EPA emissions reporting rule"
    assert captured["model_name"] == "thenlper/gte-small"
    params = captured["parameters"]
    assert params["collection_name"] == "federal_register_docs"
    assert params["query_vector"] == [0.11, 0.22, 0.33]
    assert params["query_text"] == "EPA emissions reporting rule"


def test_legal_search_federal_register_requires_collection_name(capsys) -> None:
    cli_module = _load_cli_module()

    cli_module.execute_heavy_command(
        [
            "legal",
            "search-federal-register",
            "--query_text",
            "EPA emissions reporting rule",
        ]
    )

    out = capsys.readouterr().out
    assert "Usage: ipfs-datasets legal search-federal-register" in out
