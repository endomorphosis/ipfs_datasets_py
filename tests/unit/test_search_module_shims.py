from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str):
    module_path = REPO_ROOT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_level_search_shims_export_async_api() -> None:
    brave_search = _load_module("brave_search")
    google_search = _load_module("google_search")
    github_search = _load_module("github_search")
    huggingface_search = _load_module("huggingface_search")

    assert hasattr(brave_search, "BraveSearchAPI")
    assert asyncio.iscoroutinefunction(brave_search.search_brave)
    assert asyncio.iscoroutinefunction(brave_search.search_brave_news)
    assert asyncio.iscoroutinefunction(brave_search.search_brave_images)
    assert asyncio.iscoroutinefunction(brave_search.batch_search_brave)

    assert asyncio.iscoroutinefunction(google_search.search_google)
    assert asyncio.iscoroutinefunction(google_search.search_google_images)
    assert asyncio.iscoroutinefunction(google_search.batch_search_google)

    assert asyncio.iscoroutinefunction(github_search.search_github_repositories)
    assert asyncio.iscoroutinefunction(github_search.search_github_code)
    assert asyncio.iscoroutinefunction(github_search.search_github_users)
    assert asyncio.iscoroutinefunction(github_search.search_github_issues)
    assert asyncio.iscoroutinefunction(github_search.batch_search_github)

    assert asyncio.iscoroutinefunction(huggingface_search.search_huggingface_models)
    assert asyncio.iscoroutinefunction(huggingface_search.search_huggingface_datasets)
    assert asyncio.iscoroutinefunction(huggingface_search.search_huggingface_spaces)
    assert asyncio.iscoroutinefunction(huggingface_search.get_huggingface_model_info)
    assert asyncio.iscoroutinefunction(huggingface_search.batch_search_huggingface)
