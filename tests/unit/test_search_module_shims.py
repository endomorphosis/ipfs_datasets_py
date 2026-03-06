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


def test_public_namespace_search_shims_export_expected_api() -> None:
    from ipfs_datasets_py.web_archiving import archive_is_engine
    from ipfs_datasets_py.web_archiving import autoscraper_engine
    from ipfs_datasets_py.web_archiving import brave_search_engine
    from ipfs_datasets_py.web_archiving import github_search_engine
    from ipfs_datasets_py.web_archiving import google_search_engine
    from ipfs_datasets_py.web_archiving import huggingface_search_engine
    from ipfs_datasets_py.web_archiving import ipwb_engine
    from ipfs_datasets_py.web_archiving import openverse_engine
    from ipfs_datasets_py.web_archiving import serpstack_engine
    from ipfs_datasets_py.web_archiving import wayback_machine_engine

    assert hasattr(brave_search_engine, "BraveSearchAPI")
    assert asyncio.iscoroutinefunction(brave_search_engine.search_brave)
    assert asyncio.iscoroutinefunction(brave_search_engine.batch_search_brave)

    assert asyncio.iscoroutinefunction(google_search_engine.search_google)
    assert asyncio.iscoroutinefunction(google_search_engine.batch_search_google)

    assert asyncio.iscoroutinefunction(github_search_engine.search_github_repositories)
    assert asyncio.iscoroutinefunction(github_search_engine.batch_search_github)

    assert asyncio.iscoroutinefunction(huggingface_search_engine.search_huggingface_models)
    assert asyncio.iscoroutinefunction(huggingface_search_engine.batch_search_huggingface)

    assert hasattr(openverse_engine, "OpenVerseSearchAPI")
    assert asyncio.iscoroutinefunction(openverse_engine.search_openverse_images)
    assert asyncio.iscoroutinefunction(openverse_engine.search_openverse_audio)
    assert asyncio.iscoroutinefunction(openverse_engine.batch_search_openverse)

    assert hasattr(serpstack_engine, "SerpStackSearchAPI")
    assert asyncio.iscoroutinefunction(serpstack_engine.search_serpstack)
    assert asyncio.iscoroutinefunction(serpstack_engine.search_serpstack_images)
    assert asyncio.iscoroutinefunction(serpstack_engine.batch_search_serpstack)

    assert asyncio.iscoroutinefunction(wayback_machine_engine.search_wayback_machine)
    assert asyncio.iscoroutinefunction(wayback_machine_engine.get_wayback_content)
    assert asyncio.iscoroutinefunction(wayback_machine_engine.archive_to_wayback)

    assert asyncio.iscoroutinefunction(ipwb_engine.index_warc_to_ipwb)
    assert asyncio.iscoroutinefunction(ipwb_engine.start_ipwb_replay)
    assert asyncio.iscoroutinefunction(ipwb_engine.search_ipwb_archive)
    assert asyncio.iscoroutinefunction(ipwb_engine.get_ipwb_content)
    assert asyncio.iscoroutinefunction(ipwb_engine.verify_ipwb_archive)

    assert asyncio.iscoroutinefunction(archive_is_engine.archive_to_archive_is)
    assert asyncio.iscoroutinefunction(archive_is_engine.search_archive_is)
    assert asyncio.iscoroutinefunction(archive_is_engine.get_archive_is_content)
    assert asyncio.iscoroutinefunction(archive_is_engine.check_archive_status)
    assert asyncio.iscoroutinefunction(archive_is_engine.batch_archive_to_archive_is)

    assert asyncio.iscoroutinefunction(autoscraper_engine.create_autoscraper_model)
    assert asyncio.iscoroutinefunction(autoscraper_engine.scrape_with_autoscraper)
    assert asyncio.iscoroutinefunction(autoscraper_engine.optimize_autoscraper_model)
    assert asyncio.iscoroutinefunction(autoscraper_engine.batch_scrape_with_autoscraper)
    assert asyncio.iscoroutinefunction(autoscraper_engine.list_autoscraper_models)
