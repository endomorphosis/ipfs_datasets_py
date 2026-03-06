from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


def _load_module():
	repo_root = Path(__file__).resolve().parents[2]
	module_path = repo_root / "brave_search.py"
	spec = importlib.util.spec_from_file_location("brave_search", module_path)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_brave_search_shim_exports_async_api() -> None:
	module = _load_module()

	assert hasattr(module, "BraveSearchAPI")
	assert callable(module.search_brave)
	assert callable(module.search_brave_news)
	assert callable(module.search_brave_images)
	assert callable(module.batch_search_brave)

	assert asyncio.iscoroutinefunction(module.search_brave)
	assert asyncio.iscoroutinefunction(module.search_brave_news)
	assert asyncio.iscoroutinefunction(module.search_brave_images)
	assert asyncio.iscoroutinefunction(module.batch_search_brave)
