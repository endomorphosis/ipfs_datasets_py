#!/usr/bin/env python3

import time

from ipfs_datasets_py.processors.web_archiving.search_engines.base import (
    SearchEngineAdapter,
    SearchEngineConfig,
    SearchEngineResponse,
    SearchEngineResult,
)
from ipfs_datasets_py.processors.web_archiving.search_engines.orchestrator import (
    MultiEngineOrchestrator,
    OrchestratorConfig,
)


class _SlowEngine(SearchEngineAdapter):
    calls = 0

    def search(self, query: str, max_results: int = 20, offset: int = 0, **kwargs) -> SearchEngineResponse:
        type(self).calls += 1
        time.sleep(1.2)
        return SearchEngineResponse(
            results=[
                SearchEngineResult(
                    title="slow",
                    url="https://slow.example",
                    snippet="slow",
                    engine=self.config.engine_type,
                )
            ],
            engine=self.config.engine_type,
            query=query,
            total_results=1,
        )

    def test_connection(self) -> bool:
        return True


class _FastEngine(SearchEngineAdapter):
    calls = 0

    def search(self, query: str, max_results: int = 20, offset: int = 0, **kwargs) -> SearchEngineResponse:
        type(self).calls += 1
        return SearchEngineResponse(
            results=[
                SearchEngineResult(
                    title="fast",
                    url="https://fast.example",
                    snippet="fast",
                    engine=self.config.engine_type,
                )
            ],
            engine=self.config.engine_type,
            query=query,
            total_results=1,
        )

    def test_connection(self) -> bool:
        return True


def test_sequential_mode_times_out_slow_engine_and_falls_back(monkeypatch) -> None:
    _SlowEngine.calls = 0
    _FastEngine.calls = 0
    monkeypatch.setattr(
        MultiEngineOrchestrator,
        "ENGINE_CLASSES",
        {
            "brave": _SlowEngine,
            "duckduckgo": _FastEngine,
        },
        raising=False,
    )

    orchestrator = MultiEngineOrchestrator(
        OrchestratorConfig(
            engines=["brave", "duckduckgo"],
            parallel_enabled=False,
            fallback_enabled=True,
            timeout_seconds=1,
            engine_configs={
                "brave": SearchEngineConfig(engine_type="brave"),
                "duckduckgo": SearchEngineConfig(engine_type="duckduckgo"),
            },
        )
    )

    response = orchestrator.search("state code query", max_results=5)

    assert _SlowEngine.calls == 1
    assert _FastEngine.calls == 1
    assert response.metadata["engines_used"] == ["duckduckgo"]
    assert response.results
    assert response.results[0].url == "https://fast.example"
